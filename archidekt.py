#!/usr/bin/env python3
"""Pull decklists from Archidekt (public decks, no login).

Writes, in Archidekt's own export format so every tool reads them unchanged:
  decks/<deck>/decklist.txt   the deck itself (commander + every card counted in the deck)
  decks/<deck>/maybelist.txt  the maybeboard and other categories left out of the deck
and decks/<deck>/source.json with the deck's Archidekt id, name and bracket so the
deck can be pulled again later. decks/<deck>/swaps.txt (proposed swaps) is never touched.

Usage:
    python3 archidekt.py pull https://archidekt.com/decks/25455075/the_wise_mothman
    python3 archidekt.py pull 25455075 --deck wise_mothman      # into decks/wise_mothman/
    python3 archidekt.py pull 25455075 --synergy                # then run synergy.py and save synergy.json
    python3 archidekt.py pull decks/wise_mothman                # re-pull using its source.json
    python3 archidekt.py pull --all                             # re-pull every deck with a source.json
    python3 archidekt.py search "Wise Mothman"                  # find public decks by name

Archidekt has no official API. This uses the public JSON the website itself loads,
which can change without notice.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

API = 'https://archidekt.com/api/decks'
HEADERS = {'User-Agent': 'MTGDeckOptimizer/1.0', 'Accept': 'application/json'}
TIMEOUT = 30
REPO = os.path.dirname(os.path.abspath(__file__))
DECKS_DIR = os.path.join(REPO, 'decks')


def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def parse_deck_id(ref):
    """Accept a deck id, an archidekt.com URL, or a decks/<deck> folder with source.json."""
    ref = str(ref).strip()
    if ref.isdigit():
        return int(ref)
    m = re.search(r'archidekt\.com/(?:api/)?decks/(\d+)', ref)
    if m:
        return int(m.group(1))
    src = os.path.join(ref, 'source.json')
    if os.path.isdir(ref) and os.path.exists(src):
        with open(src) as f:
            return int(json.load(f)['archidekt_id'])
    raise ValueError(f"Not an Archidekt deck id, URL or deck folder with source.json: {ref}")


def fetch_deck(deck_id):
    try:
        return _get(f'{API}/{deck_id}/')
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise RuntimeError(f"Deck {deck_id} not found or private (HTTP {e.code}). "
                               "Only public and unlisted decks can be pulled.") from e
        raise


def search_decks(name, limit=10):
    q = urllib.parse.urlencode({'name': name, 'pageSize': limit})
    return _get(f'{API}/v3/?{q}').get('results', [])


# ==================== Conversion ====================

def card_line(entry, categories):
    """One Archidekt card entry -> one export line: 1x Name (set) number *F* [Tags]."""
    card = entry['card']
    name = card['oracleCard']['name']
    qty = entry.get('quantity', 1)
    edition = card.get('edition', {}).get('editioncode', '')
    number = card.get('collectorNumber', '') or '0'
    foil = ' *F*' if (entry.get('modifier') or '').lower() == 'foil' else ''
    tags = []
    for cat in entry.get('categories') or []:
        info = categories.get(cat, {})
        flags = ''
        if not info.get('includedInDeck', True):
            flags += '{noDeck}'
        if not info.get('includedInPrice', True):
            flags += '{noPrice}'
        tags.append(cat + flags)
    return f"{qty}x {name} ({edition}) {number}{foil} [{','.join(tags)}]"


def split_deck(deck):
    """Archidekt deck JSON -> (decklist text, maybelist text).

    The decklist holds the commander and every card counted in the deck; the
    maybelist holds the maybeboard and any other category left out of the deck.
    Each is sorted commander first, then by category and name.
    """
    categories = {c['name']: c for c in deck.get('categories', [])}
    entries = [e for e in deck.get('cards', []) if not e.get('deletedAt')]

    def is_cmdr(e):
        return any(categories.get(c, {}).get('isPremier') or c == 'Commander'
                   for c in e.get('categories') or [])

    def in_deck(e):
        return is_cmdr(e) or all(categories.get(c, {}).get('includedInDeck', True)
                                 for c in e.get('categories') or [])

    def order(e):
        return (not is_cmdr(e), ((e.get('categories') or ['']))[0], e['card']['oracleCard']['name'])

    def text(es):
        return ''.join(card_line(e, categories) + '\n' for e in sorted(es, key=order))

    return text([e for e in entries if in_deck(e)]), text([e for e in entries if not in_deck(e)])


def to_decklist(deck):
    """Archidekt deck JSON -> decklist.txt text (cards in the deck only)."""
    return split_deck(deck)[0]


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return s or 'deck'


def _main_deck_counts(text):
    """Card -> count for cards that are in the deck (for the change summary)."""
    counts = Counter()
    for line in text.splitlines():
        m = re.match(r'^(\d+)x\s+(.+?)\s+\(\w*\)\s+\S+.*\[([^\]]*)\]$', line.strip())
        if m and '{noDeck}' not in m.group(3):
            counts[m.group(2)] += int(m.group(1))
    return counts


def summarize_changes(old_text, new_text):
    old, new = _main_deck_counts(old_text), _main_deck_counts(new_text)
    added = sorted((n, new[n] - old.get(n, 0)) for n in new if new[n] > old.get(n, 0))
    removed = sorted((n, old[n] - new.get(n, 0)) for n in old if old[n] > new.get(n, 0))
    return added, removed


# ==================== Pull ====================

def pull(ref, deck_name=None, out_dir=None):
    """Pull one deck. Returns (deck folder, added, removed)."""
    deck_id = parse_deck_id(ref)
    if out_dir is None and os.path.isdir(str(ref)):
        out_dir = str(ref)
    deck = fetch_deck(deck_id)
    if out_dir is None:
        out_dir = os.path.join(DECKS_DIR, deck_name or slugify(deck['name']))
    os.makedirs(out_dir, exist_ok=True)

    path = os.path.join(out_dir, 'decklist.txt')
    new_text, maybe_text = split_deck(deck)
    old_text = open(path).read() if os.path.exists(path) else ''
    added, removed = summarize_changes(old_text, new_text)
    with open(path, 'w') as f:
        f.write(new_text)
    maybe_path = os.path.join(out_dir, 'maybelist.txt')
    if maybe_text:
        with open(maybe_path, 'w') as f:
            f.write(maybe_text)
    elif os.path.exists(maybe_path):
        os.remove(maybe_path)

    source = {
        'archidekt_id': deck_id,
        'url': f'https://archidekt.com/decks/{deck_id}',
        'name': deck.get('name'),
        'owner': (deck.get('owner') or {}).get('username'),
        'bracket': deck.get('edhBracket'),
        'updated_at': deck.get('updatedAt'),
        'pulled_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with open(os.path.join(out_dir, 'source.json'), 'w') as f:
        json.dump(source, f, indent=1, ensure_ascii=False)
        f.write('\n')
    return out_dir, added, removed, source


def report(out_dir, added, removed, source, had_file):
    rel = os.path.relpath(out_dir, REPO)
    print(f"Pulled '{source['name']}' by {source['owner']} -> {rel}/decklist.txt")
    if not had_file:
        print("  new deck")
    elif not added and not removed:
        print("  no changes")
    for n, k in added:
        print(f"  + {k}x {n}")
    for n, k in removed:
        print(f"  - {k}x {n}")


def main():
    ap = argparse.ArgumentParser(description='Pull public decklists from Archidekt')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('pull', help='Pull a deck into decks/<deck>/decklist.txt')
    p.add_argument('ref', nargs='?', help='Deck id, archidekt.com URL, or decks/<deck> folder')
    p.add_argument('--deck', help='Folder name under decks/ (default: from the deck name)')
    p.add_argument('--all', action='store_true', help='Re-pull every deck that has a source.json')
    p.add_argument('--synergy', action='store_true', help='Run synergy.py afterwards and save synergy.json')
    s = sub.add_parser('search', help='Find public decks by name')
    s.add_argument('name')
    s.add_argument('--limit', type=int, default=10)
    args = ap.parse_args()

    if args.cmd == 'search':
        for r in search_decks(args.name, args.limit):
            owner = (r.get('owner') or {}).get('username')
            print(f"  {r['id']:>10}  {r['name']}  (by {owner})  https://archidekt.com/decks/{r['id']}")
        return

    if args.all:
        refs = sorted(os.path.join(DECKS_DIR, d) for d in os.listdir(DECKS_DIR)
                      if os.path.exists(os.path.join(DECKS_DIR, d, 'source.json')))
        if not refs:
            print("No deck has a source.json yet. Pull each deck once by id or URL first.")
            return
    elif args.ref:
        refs = [args.ref]
    else:
        ap.error('pull needs a deck id, URL or folder (or --all)')

    failed = False
    for ref in refs:
        try:
            target = args.deck and os.path.join(DECKS_DIR, args.deck)
            had_file = os.path.exists(os.path.join(target or str(ref), 'decklist.txt'))
            out_dir, added, removed, source = pull(ref, args.deck)
        except (ValueError, RuntimeError, urllib.error.URLError, OSError) as e:
            print(f"FAILED {ref}: {e}", file=sys.stderr)
            failed = True
            continue
        report(out_dir, added, removed, source, had_file)
        if args.synergy:
            decklist = os.path.join(out_dir, 'decklist.txt')
            subprocess.run([sys.executable, os.path.join(REPO, 'synergy.py'), decklist, '--save'],
                           check=False)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
