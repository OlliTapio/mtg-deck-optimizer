"""Convert a decklist to JSON format enriched with Scryfall data and otags.

Usage:
    python3 deck_to_json.py decks/<deck>/decklist.txt
    python3 deck_to_json.py decks/<deck>/decklist.txt --output decks/<deck>/deck.json
"""
import json
import sys
import os

from card_cache import get_deck_cards
from otag_fetcher import fetch_otags_for_cards, BASICS
from deck_analyzer import (
    get_type_line, get_mana_cost, get_oracle_text, get_cmc,
    get_keywords, get_color_identity, get_produced_mana, classify_type,
)


def deck_to_json(decklist_file):
    """Convert a decklist to a JSON structure with full Scryfall data and otags."""
    cards, parsed = get_deck_cards(decklist_file)

    # Fetch otags
    names = sorted(set(c['name'] for c in cards if c['name'] not in BASICS))
    otags = fetch_otags_for_cards(names)

    result = {
        'commander': None,
        'deck': [],
        'metadata': {
            'source_file': decklist_file,
            'total_cards': 0,
        },
    }

    for c in cards:
        sf = c.get('scryfall', {}) or {}
        is_cmdr = any('Commander' in t for t in c.get('tags', []))
        is_buy = any(t == 'Buy' for t in c.get('tags', []))

        card_json = {
            'name': c['name'],
            'count': c['count'],
            'mana_cost': get_mana_cost(sf),
            'cmc': get_cmc(sf),
            'type_line': get_type_line(sf),
            'types': sorted(classify_type(get_type_line(sf))),
            'oracle_text': get_oracle_text(sf),
            'color_identity': get_color_identity(sf),
            'keywords': get_keywords(sf),
            'produced_mana': get_produced_mana(sf),
            'otags': otags.get(c['name'], []),
            'price_eur': sf.get('prices', {}).get('eur'),
            'set': c.get('set', ''),
            'number': c.get('number', ''),
            'foil': c.get('foil', False),
            'buy': is_buy,
        }

        if is_cmdr:
            result['commander'] = card_json
        else:
            result['deck'].append(card_json)

    result['metadata']['total_cards'] = (
        (1 if result['commander'] else 0) +
        sum(c['count'] for c in result['deck'])
    )

    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Convert decklist to JSON')
    ap.add_argument('decklist', help='Decklist file')
    ap.add_argument('--output', '-o', help='Output JSON file (default: stdout)')
    args = ap.parse_args()

    data = deck_to_json(args.decklist)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(data, indent=2))
