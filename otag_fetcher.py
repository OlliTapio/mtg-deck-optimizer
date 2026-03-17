"""Fetch and cache Scryfall otags for cards in a deck.

Queries Scryfall search API with otag: filters in batches, then caches
results per card in cache/otags.json. Only queries API for cards not yet cached.

Usage:
    python3 otag_fetcher.py decks/<deck>/decklist.txt
    python3 otag_fetcher.py --card "Binding the Old Gods"
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from parser import parse_decklist

CACHE_FILE = os.path.join(os.path.dirname(__file__), 'cache', 'otags.json')
HEADERS = {'User-Agent': 'MTGDeckOptimizer/1.0', 'Accept': 'application/json'}
REQUEST_DELAY = 0.1

OTAGS = [
    'ramp', 'removal', 'draw', 'board-wipe', 'counterspell',
    'tutor', 'mill', 'recursion', 'mana-dork', 'card-advantage',
    'evasion', 'lifegain', 'graveyard-hate', 'sacrifice-outlet',
]

BASICS = {'Forest', 'Island', 'Swamp', 'Mountain', 'Plains'}


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def batch_names(names, max_chars=600):
    """Split card names into batches that fit in Scryfall query length limits."""
    batches = []
    current = []
    current_len = 0
    for n in names:
        addition = f'!"{n}"'
        if current_len + len(addition) + 4 > max_chars and current:
            batches.append(current)
            current = []
            current_len = 0
        current.append(addition)
        current_len += len(addition) + 4
    if current:
        batches.append(current)
    return batches


def search_otag(otag, name_batches):
    """Search Scryfall for cards matching an otag from the given name batches."""
    matches = set()
    for batch in name_batches:
        time.sleep(REQUEST_DELAY)
        name_filter = ' or '.join(batch)
        q = f'otag:{otag} ({name_filter})'
        params = urllib.parse.urlencode({'q': q})
        url = f'https://api.scryfall.com/cards/search?{params}'
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
                for card in data.get('data', []):
                    matches.add(card['name'])
                while data.get('has_more'):
                    time.sleep(REQUEST_DELAY)
                    req2 = urllib.request.Request(data['next_page'], headers=HEADERS)
                    with urllib.request.urlopen(req2) as resp2:
                        data = json.loads(resp2.read())
                        for card in data.get('data', []):
                            matches.add(card['name'])
        except urllib.error.HTTPError:
            pass
    return matches


def fetch_otags_for_cards(card_names):
    """Fetch otags for a list of card names. Returns dict of {card_name: [otags]}."""
    cache = load_cache()

    # Find cards not yet cached
    uncached = [n for n in card_names if n not in cache and n not in BASICS]

    if uncached:
        print(f"Fetching otags for {len(uncached)} uncached cards...", file=sys.stderr)
        batches = batch_names(uncached)
        total_queries = 0

        # Initialize uncached cards with empty lists
        for name in uncached:
            cache[name] = []

        for otag in OTAGS:
            matches = search_otag(otag, batches)
            total_queries += len(batches)
            for name in matches:
                if name in cache and otag not in cache[name]:
                    cache[name].append(otag)

        print(f"  {total_queries} API queries made.", file=sys.stderr)
        save_cache(cache)
    else:
        print(f"All {len(card_names)} cards already cached.", file=sys.stderr)

    return {n: cache.get(n, []) for n in card_names}


def fetch_otags_for_deck(decklist_file):
    """Fetch otags for all cards in a decklist."""
    parsed = parse_decklist(decklist_file)
    all_cards = []
    if parsed['commander']:
        all_cards.append(parsed['commander'])
    all_cards.extend(parsed['deck'])

    names = sorted(set(c['name'] for c in all_cards if c['name'] not in BASICS))
    return fetch_otags_for_cards(names)


def print_otags(otags_by_card):
    """Print otags grouped by tag."""
    # Group by otag
    by_tag = {}
    for name, tags in sorted(otags_by_card.items()):
        for tag in tags:
            by_tag.setdefault(tag, []).append(name)

    # Print per-tag summary
    print("=== Otags by Category ===\n")
    for tag in OTAGS:
        cards = sorted(by_tag.get(tag, []))
        if cards:
            print(f"  {tag} ({len(cards)}):")
            for c in cards:
                print(f"    - {c}")
            print()

    # Print per-card summary
    print("=== Otags by Card ===\n")
    for name, tags in sorted(otags_by_card.items()):
        if tags:
            print(f"  {name}: {', '.join(sorted(tags))}")
        else:
            print(f"  {name}: (no otags)")

    # Template check
    removal = set(by_tag.get('removal', []))
    counters = set(by_tag.get('counterspell', []))
    wipes = set(by_tag.get('board-wipe', []))
    draw = set(by_tag.get('draw', []))
    card_adv = set(by_tag.get('card-advantage', []))
    ramp = set(by_tag.get('ramp', []))

    print("\n=== Command Zone Template Check (otag-based) ===")
    print(f"  Targeted Disruption (removal + counters): {len(removal | counters)}/12")
    print(f"  Mass Disruption (board wipes):            {len(wipes)}/6")
    print(f"  Card Advantage (draw + card-advantage):   {len(draw | card_adv)}/12")
    print(f"  Ramp:                                     {len(ramp)}/10")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Fetch Scryfall otags for deck cards')
    ap.add_argument('decklist', nargs='?', help='Decklist file')
    ap.add_argument('--card', type=str, help='Look up otags for a single card')
    ap.add_argument('--refresh', action='store_true', help='Force refresh (ignore cache)')
    args = ap.parse_args()

    if args.refresh and os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)

    if args.card:
        result = fetch_otags_for_cards([args.card])
        for name, tags in result.items():
            print(f"{name}: {', '.join(tags) if tags else '(no otags)'}")
    elif args.decklist:
        result = fetch_otags_for_deck(args.decklist)
        print_otags(result)
    else:
        print("Usage: python3 otag_fetcher.py <decklist> | --card 'Card Name'")
