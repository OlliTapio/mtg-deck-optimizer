"""Parse Archidekt export format into structured deck data."""
import re
import sys
import json
from collections import Counter

def parse_decklist(filepath):
    """Parse an Archidekt export file.

    Returns dict with keys: commander, deck, removed, change, maybeboard, buy_list
    Each card is a dict with: name, count, set, number, tags, foil
    """
    cards = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(
                r'^(\d+)x\s+(.+?)\s+\((\w+)\)\s+(\S+)\s*(\*F\*)?\s*\[(.+)\]$',
                line
            )
            if not m:
                print(f"WARN: Could not parse: {line}", file=sys.stderr)
                continue
            count, name, card_set, number, foil, tags_raw = m.groups()
            tags = [t.strip() for t in tags_raw.split(',')]
            cards.append({
                'name': name,
                'count': int(count),
                'set': card_set,
                'number': number,
                'foil': bool(foil),
                'tags': tags,
            })

    # Categorize
    deck = []
    commander = None
    removed = []
    change = []
    maybeboard = []
    buy_list = []

    for card in cards:
        no_deck = any('{noDeck}' in t for t in card['tags'])
        is_commander = any('Commander' in t for t in card['tags'])
        is_removed = any('Removed' in t for t in card['tags'])
        is_change = any('Change' in t for t in card['tags'])
        is_maybe = any('Maybeboard' in t for t in card['tags'])
        is_buy = any(t == 'Buy' for t in card['tags'])

        # Clean tags for display
        clean_tags = [re.sub(r'\{[^}]+\}', '', t).strip() for t in card['tags']]
        clean_tags = [t for t in clean_tags if t and t not in ('Removed', 'Change', 'Maybeboard', 'Buy')]
        card['clean_tags'] = clean_tags

        if is_commander:
            commander = card
        elif is_removed:
            removed.append(card)
        elif is_change and no_deck:
            change.append(card)
        elif is_maybe:
            maybeboard.append(card)
        elif no_deck:
            continue  # Skip other noDeck cards
        else:
            deck.append(card)

        if is_buy:
            buy_list.append(card)

    return {
        'commander': commander,
        'deck': deck,
        'removed': removed,
        'change': change,
        'maybeboard': maybeboard,
        'buy_list': buy_list,
    }


def analyze_deck(parsed):
    """Print deck analysis: card counts, mana curve, category breakdown."""
    deck = parsed['deck']
    commander = parsed['commander']

    # Count total cards (including commander)
    total = sum(c['count'] for c in deck) + (1 if commander else 0)

    # Category breakdown
    categories = Counter()
    for card in deck + ([commander] if commander else []):
        for tag in card['clean_tags']:
            if tag in ('Creature', 'Sorcery', 'Enchantment', 'Artifact'):
                continue
            categories[tag] += card['count']

    # Land count
    lands = [c for c in deck if 'Land' in card_types(c)]
    land_count = sum(c['count'] for c in lands)
    nonland = [c for c in deck if 'Land' not in card_types(c)]

    print(f"=== {commander['name'] if commander else 'Unknown'} ===")
    print(f"Total cards in deck: {total}")
    print(f"Lands: {land_count}")
    print(f"Non-land: {total - land_count - 1} (+ commander)")
    print()

    print("--- Category Breakdown ---")
    for cat, count in categories.most_common():
        print(f"  {cat}: {count}")
    print()

    print(f"--- Cards to Buy ({len(parsed['buy_list'])}) ---")
    for c in sorted(parsed['buy_list'], key=lambda x: x['name']):
        status = ""
        if any('Maybeboard' in t for t in c['tags']):
            status = " [MAYBE]"
        elif any('Removed' in t for t in c['tags']):
            status = " [REMOVED]"
        print(f"  {c['name']}{status}")
    print()

    print(f"--- Considering Changes ({len(parsed['change'])}) ---")
    for c in sorted(parsed['change'], key=lambda x: x['name']):
        print(f"  {c['name']} ({', '.join(c['clean_tags'])})")
    print()

    print(f"--- Maybeboard ({len(parsed['maybeboard'])}) ---")
    for c in sorted(parsed['maybeboard'], key=lambda x: x['name']):
        print(f"  {c['name']} ({', '.join(c['clean_tags'])})")
    print()

    print(f"--- Removed ({len(parsed['removed'])}) ---")
    for c in sorted(parsed['removed'], key=lambda x: x['name']):
        print(f"  {c['name']} ({', '.join(c['clean_tags'])})")


def card_types(card):
    """Infer card types from tags."""
    types = set()
    for tag in card['tags']:
        clean = re.sub(r'\{[^}]+\}', '', tag).strip()
        if clean in ('Land', 'Creature', 'Sorcery', 'Enchantment', 'Artifact'):
            types.add(clean)
    return types


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python parser.py <decklist_file>")
        sys.exit(1)
    parsed = parse_decklist(sys.argv[1])
    analyze_deck(parsed)
