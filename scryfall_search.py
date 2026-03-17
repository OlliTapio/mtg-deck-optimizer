"""Search Scryfall for card suggestions. Supports filtering by color identity, price, and keywords."""
import urllib.request
import urllib.parse
import json
import sys
import time

SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"
SCRYFALL_NAMED = "https://api.scryfall.com/cards/named"

# Be nice to Scryfall API
REQUEST_DELAY = 0.1

HEADERS = {'User-Agent': 'MTGDeckOptimizer/1.0', 'Accept': 'application/json'}


def search_cards(query, max_results=20):
    """Search Scryfall with a query string. Returns list of card dicts."""
    params = urllib.parse.urlencode({'q': query, 'order': 'edhrec'})
    url = f"{SCRYFALL_SEARCH}?{params}"

    cards = []
    while url and len(cards) < max_results:
        time.sleep(REQUEST_DELAY)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        for card in data.get('data', []):
            cards.append(extract_card_info(card))
            if len(cards) >= max_results:
                break

        url = data.get('next_page') if data.get('has_more') else None

    return cards


def get_card(name):
    """Look up a single card by exact name."""
    params = urllib.parse.urlencode({'exact': name})
    url = f"{SCRYFALL_NAMED}?{params}"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        return extract_card_info(data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Try fuzzy search
            params = urllib.parse.urlencode({'fuzzy': name})
            url = f"{SCRYFALL_NAMED}?{params}"
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            return extract_card_info(data)
        raise


def extract_card_info(card):
    """Extract relevant fields from a Scryfall card object."""
    prices = card.get('prices', {})
    eur_price = prices.get('eur') or prices.get('eur_foil')

    # Handle double-faced cards
    if 'card_faces' in card and 'mana_cost' not in card:
        mana_cost = card['card_faces'][0].get('mana_cost', '')
        type_line = card['card_faces'][0].get('type_line', '')
        oracle_text = card['card_faces'][0].get('oracle_text', '')
    else:
        mana_cost = card.get('mana_cost', '')
        type_line = card.get('type_line', '')
        oracle_text = card.get('oracle_text', '')

    return {
        'name': card.get('name', ''),
        'mana_cost': mana_cost,
        'cmc': card.get('cmc', 0),
        'type_line': type_line,
        'oracle_text': oracle_text,
        'color_identity': card.get('color_identity', []),
        'price_eur': float(eur_price) if eur_price else None,
        'edhrec_rank': card.get('edhrec_rank'),
        'keywords': card.get('keywords', []),
        'legalities': card.get('legalities', {}),
    }


def format_card(card, verbose=False):
    """Format a card for display."""
    price_str = f"€{card['price_eur']:.2f}" if card['price_eur'] else "N/A"
    line = f"{card['name']} {card['mana_cost']} (CMC {card['cmc']}) - {price_str}"
    if verbose:
        line += f"\n  {card['type_line']}"
        line += f"\n  {card['oracle_text']}"
    return line


def search_for_deck(commander_colors, category, extra_query="", max_price_eur=10, max_results=15):
    """Search for cards suitable for a Sultai commander deck.

    category: e.g. 'ramp', 'removal', 'draw', 'counter', 'proliferate'
    """
    color_id = ''.join(sorted(commander_colors))
    # commander:BUG ensures color identity fits
    query_parts = [f"commander:{color_id}", f"legal:commander"]

    if max_price_eur:
        query_parts.append(f"eur<={max_price_eur}")

    category_queries = {
        'ramp': '(oracle:"add" oracle:"mana" or oracle:"search your library" oracle:"land") type:creature',
        'draw': 'oracle:"draw" -type:land',
        'removal': '(oracle:"destroy" or oracle:"exile") -type:land',
        'counter_synergy': '(oracle:"+1/+1 counter" or oracle:"proliferate")',
        'proliferate': 'oracle:"proliferate"',
        'mill': '(oracle:"mill" or oracle:"into their graveyard")',
        'rad_counters': 'oracle:"rad counter"',
        'board_wipe': '(oracle:"destroy all" or oracle:"each creature" oracle:"damage")',
        'recursion': '(oracle:"return" oracle:"from your graveyard")',
        'protection': '(oracle:"hexproof" or oracle:"indestructible" or oracle:"ward")',
    }

    if category in category_queries:
        query_parts.append(category_queries[category])

    if extra_query:
        query_parts.append(extra_query)

    query = ' '.join(query_parts)
    print(f"Scryfall query: {query}\n", file=sys.stderr)

    cards = search_cards(query, max_results)

    # Filter out cards over budget
    if max_price_eur:
        cards = [c for c in cards if c['price_eur'] is None or c['price_eur'] <= max_price_eur]

    return cards


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scryfall_search.py <card_name|search_query>")
        print("  --search <query>     Raw Scryfall search")
        print("  --lookup <name>      Look up a specific card")
        print("  --category <cat>     Search by category for Sultai (BUG)")
        print("  --extra <query>      Additional query terms")
        print("  --max-price <eur>    Max price in EUR (default 10)")
        print("  --verbose            Show oracle text")
        sys.exit(1)

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--search', type=str, help='Raw Scryfall query')
    ap.add_argument('--lookup', type=str, help='Look up specific card by name')
    ap.add_argument('--category', type=str, help='Category search for Sultai')
    ap.add_argument('--extra', type=str, default='', help='Extra query terms')
    ap.add_argument('--max-price', type=float, default=10, help='Max EUR price')
    ap.add_argument('--verbose', '-v', action='store_true')
    ap.add_argument('--max-results', type=int, default=15)
    args = ap.parse_args()

    if args.lookup:
        card = get_card(args.lookup)
        print(format_card(card, verbose=True))
    elif args.search:
        cards = search_cards(args.search, args.max_results)
        for c in cards:
            print(format_card(c, args.verbose))
    elif args.category:
        cards = search_for_deck(['B', 'G', 'U'], args.category, args.extra, args.max_price, args.max_results)
        for c in cards:
            print(format_card(c, args.verbose))
    else:
        print("Specify --search, --lookup, or --category")
