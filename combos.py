#!/usr/bin/env python3
"""Known combos in a deck, from Commander Spellbook (commanderspellbook.com).

Sends the decklist to Commander Spellbook's free find-my-combos API and lists:
- combos the deck already contains, with steps, prerequisites and what they produce
- near-misses: combos that need one or more cards the deck doesn't have (same colours)

Results are cached in cache/combos.json, keyed by the exact card list, so a deck
is only looked up again after it changes.

Bracket check (from CLAUDE.md): two-card infinite combos are banned in brackets 1-2
and only allowed late in bracket 3. Each combo is flagged against the deck's bracket,
read from decks/<deck>/CLAUDE.md ("Bracket: N").

Usage:
    python3 combos.py decks/<deck>/decklist.txt              # combos + near-misses
    python3 combos.py decks/<deck>/decklist.txt --almost 30  # more near-misses
    python3 combos.py decks/<deck>/decklist.txt --prices     # Scryfall EUR price of missing cards
    python3 combos.py decks/<deck>/decklist.txt --json
    python3 combos.py decks/<deck>/decklist.txt --refresh    # ignore the cache
"""
import argparse
import hashlib
import json
import os
import re
import signal
import sys
import urllib.error
import urllib.request

API = 'https://backend.commanderspellbook.com/find-my-combos'
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'combos.json')
HEADERS = {'User-Agent': 'MTGDeckOptimizer/1.0', 'Accept': 'application/json',
           'Content-Type': 'application/json'}
TIMEOUT = 60

BRACKET_TAGS = {'R': 'Ruthless', 'S': 'Spicy', 'P': 'Powerful', 'O': 'Oddball',
                'C': 'Core', 'E': 'Exhibition', 'B': 'Banned'}


# ==================== Cache ====================

def _load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=1, sort_keys=True, ensure_ascii=False)


def deck_key(card_names, commanders):
    blob = json.dumps({'main': sorted(card_names), 'commanders': sorted(commanders)})
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ==================== API ====================

def _compact(variant, deck_names):
    """Keep only what the tools use from one Commander Spellbook variant."""
    cards = [u['card']['name'] for u in variant.get('uses', [])]
    deck_lower = {n.lower() for n in deck_names}
    missing = [c for c in cards if c.lower() not in deck_lower
               and not any(c.lower() == n.split(' // ')[0] for n in deck_lower)]
    templates = [r.get('template', {}).get('name') for r in variant.get('requires', [])]
    produces = [p['feature']['name'] for p in variant.get('produces', [])]
    return {
        'id': variant.get('id'),
        'url': f"https://commanderspellbook.com/combo/{variant.get('id')}/",
        'cards': cards,
        'missing': missing,
        'requires': [t for t in templates if t],
        'produces': produces,
        'infinite': any(p.lower().startswith('infinite') for p in produces),
        'bracket_tag': variant.get('bracketTag'),
        'identity': variant.get('identity'),
        'popularity': variant.get('popularity') or 0,
        'mana_needed': variant.get('manaNeeded') or '',
        'prerequisites': ' '.join(' '.join(x.split()) for x in (variant.get('easyPrerequisites'),
                                                                variant.get('notablePrerequisites')) if x),
        'steps': variant.get('description') or '',
        'notes': variant.get('notes') or '',
    }


def _post(payload, url=API):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def fetch_combos(card_names, commanders=(), refresh=False):
    """Return {'included': [...], 'almost': [...]} for a deck, using the cache.

    Raises urllib.error.URLError (or OSError) if Commander Spellbook can't be reached
    and the deck isn't cached.
    """
    card_names = sorted(set(card_names) - set(commanders))
    commanders = sorted(set(commanders))
    key = deck_key(card_names, commanders)
    cache = _load_cache()
    if not refresh and key in cache:
        return cache[key]

    payload = {'main': [{'card': n} for n in card_names],
               'commanders': [{'card': n} for n in commanders]}
    deck_names = card_names + commanders
    included, almost = [], []
    url = API
    while url:
        page = _post(payload, url)
        results = page.get('results', {})
        included += [_compact(v, deck_names) for v in results.get('included', [])]
        almost += [_compact(v, deck_names) for v in results.get('almostIncluded', [])]
        url = page.get('next')
    almost.sort(key=lambda c: (len(c['missing']), -c['popularity']))
    included.sort(key=lambda c: -c['popularity'])
    entry = {'commanders': commanders, 'included': included, 'almost': almost}
    cache[key] = entry
    _save_cache(cache)
    return entry


# ==================== Bracket check ====================

def deck_bracket(decklist):
    """Read 'Bracket: N' from the deck's CLAUDE.md, or None."""
    path = os.path.join(os.path.dirname(os.path.abspath(decklist)), 'CLAUDE.md')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        m = re.search(r'bracket\W{0,4}\s*(\d)', f.read(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def bracket_flag(combo, bracket):
    """Explain why a combo may break the deck's bracket, or return ''."""
    if bracket is None:
        return ''
    two_card_infinite = combo['infinite'] and len(combo['cards']) <= 2
    if combo['bracket_tag'] == 'B':
        return 'contains a banned card'
    if two_card_infinite and bracket <= 2:
        return f'two-card infinite: not allowed in bracket {bracket}'
    if two_card_infinite and bracket == 3:
        return 'two-card infinite: bracket 3 allows it only if it cannot win in the first ~6 turns'
    if combo['bracket_tag'] == 'R' and bracket <= 3:
        return f'Spellbook rates it Ruthless (bracket 4 territory)'
    return ''


# ==================== Loading ====================

def load_deck_names(decklist):
    from deck_analyzer import load_deck
    all_cards, cmdr = load_deck(decklist)
    names = sorted({c['name'] for c in all_cards})
    commanders = [cmdr] if cmdr and cmdr != 'Unknown' else []
    return names, commanders


def combos_for_deck(decklist, refresh=False):
    names, commanders = load_deck_names(decklist)
    return fetch_combos(names, commanders, refresh=refresh)


# ==================== Output ====================

def _price(name):
    try:
        from card_cache import get_card
        sf = get_card(name)
        eur = (sf or {}).get('prices', {}).get('eur')
        return f'€{float(eur):.2f}' if eur else 'N/A'
    except Exception:
        return '?'


def print_combo(c, bracket, show_steps=True):
    tag = BRACKET_TAGS.get(c['bracket_tag'], c['bracket_tag'] or '-')
    print(f"  {' + '.join(c['cards'])}")
    print(f"    produces: {', '.join(c['produces'][:4])}")
    print(f"    Spellbook tag: {tag} | popularity {c['popularity']} | {c['url']}")
    if c['requires']:
        print(f"    also needs: {', '.join(c['requires'])}")
    if c['prerequisites']:
        print(f"    prerequisites: {c['prerequisites']}")
    if c['mana_needed']:
        print(f"    mana: {c['mana_needed']}")
    flag = bracket_flag(c, bracket)
    if flag:
        print(f"    !! BRACKET: {flag}")
    if show_steps and c['steps']:
        for line in c['steps'].split('\n'):
            print(f"      - {line}")


def print_report(result, bracket, n_almost=15, prices=False):
    print(f"=== Combos (Commander Spellbook) ===")
    print(f"Deck bracket: {bracket if bracket is not None else 'unknown (no Bracket: N in deck CLAUDE.md)'}\n")
    print(f"--- IN THE DECK ({len(result['included'])}) ---")
    if not result['included']:
        print("  none found")
    for c in result['included']:
        print_combo(c, bracket)
        print()
    print(f"--- NEAR-MISSES: combos missing cards (top {n_almost} of {len(result['almost'])}) ---")
    for c in result['almost'][:n_almost]:
        missing = ', '.join(f"{m} ({_price(m)})" if prices else m for m in c['missing'])
        print(f"  missing: {missing}")
        print_combo(c, bracket, show_steps=False)
        print()
    print("Near-misses are leads, not suggestions: check theme, bracket and the €10 budget first.")


def main():
    if hasattr(signal, 'SIGPIPE'):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description='Known combos in a deck (Commander Spellbook)')
    ap.add_argument('decklist')
    ap.add_argument('--almost', type=int, default=15, help='How many near-misses to list')
    ap.add_argument('--prices', action='store_true', help='Show Scryfall EUR price of missing cards')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--refresh', action='store_true', help='Ignore the cache and ask the API again')
    args = ap.parse_args()

    print(f"Loading deck from {args.decklist}...", file=sys.stderr)
    try:
        result = combos_for_deck(args.decklist, refresh=args.refresh)
    except (urllib.error.URLError, OSError) as e:
        print(f"Could not reach Commander Spellbook ({e}). Is backend.commanderspellbook.com allowed?",
              file=sys.stderr)
        sys.exit(1)
    bracket = deck_bracket(args.decklist)
    if args.json:
        for c in result['included'] + result['almost']:
            c['bracket_flag'] = bracket_flag(c, bracket)
        json.dump(dict(result, bracket=bracket), sys.stdout, indent=1, ensure_ascii=False)
        print()
    else:
        print_report(result, bracket, args.almost, args.prices)


if __name__ == '__main__':
    main()
