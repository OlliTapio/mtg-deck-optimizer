"""Check prices for all cards in a deck or a list of card names via Scryfall."""
import sys
import time
from scryfall_search import get_card
from parser import parse_decklist


def check_deck_prices(filepath):
    """Check EUR prices for all cards in a decklist."""
    parsed = parse_decklist(filepath)
    all_cards = []
    if parsed['commander']:
        all_cards.append(parsed['commander'])
    all_cards.extend(parsed['deck'])

    total = 0.0
    buy_total = 0.0
    results = []

    for card in all_cards:
        time.sleep(0.1)  # Be nice to Scryfall
        try:
            info = get_card(card['name'])
            price = info['price_eur']
            price_str = f"€{price:.2f}" if price else "N/A"
            is_buy = any(t == 'Buy' for t in card['tags'])
            results.append({
                'name': card['name'],
                'count': card['count'],
                'price': price,
                'price_str': price_str,
                'buy': is_buy,
                'tags': card.get('clean_tags', []),
            })
            if price:
                total += price * card['count']
                if is_buy:
                    buy_total += price * card['count']
        except Exception as e:
            results.append({
                'name': card['name'],
                'count': card['count'],
                'price': None,
                'price_str': f"ERROR: {e}",
                'buy': False,
                'tags': [],
            })

    # Sort by price descending
    results.sort(key=lambda x: x['price'] or 0, reverse=True)

    print(f"=== Deck Price Check ===\n")
    for r in results:
        buy_marker = " [BUY]" if r['buy'] else ""
        print(f"  {r['count']}x {r['name']}: {r['price_str']}{buy_marker}")

    print(f"\n--- Totals ---")
    print(f"  Deck total: €{total:.2f}")
    print(f"  Still need to buy: €{buy_total:.2f}")

    # Show buy list sorted by price
    buy_cards = [r for r in results if r['buy']]
    if buy_cards:
        print(f"\n--- Buy List ({len(buy_cards)} cards, €{buy_total:.2f}) ---")
        for r in sorted(buy_cards, key=lambda x: x['price'] or 0, reverse=True):
            print(f"  {r['name']}: {r['price_str']}")


def check_card_list(names):
    """Check prices for a list of card names."""
    total = 0.0
    for name in names:
        time.sleep(0.1)
        try:
            info = get_card(name)
            price = info['price_eur']
            price_str = f"€{price:.2f}" if price else "N/A"
            print(f"  {name}: {price_str}")
            print(f"    {info['mana_cost']} | {info['type_line']}")
            print(f"    {info['oracle_text'][:120]}")
            if price:
                total += price
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
        print()
    print(f"Total: €{total:.2f}")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Check card prices via Scryfall')
    ap.add_argument('--deck', type=str, help='Check all prices in a decklist file')
    ap.add_argument('--cards', nargs='+', help='Check prices for specific card names')
    args = ap.parse_args()

    if args.deck:
        check_deck_prices(args.deck)
    elif args.cards:
        check_card_list(args.cards)
    else:
        print("Usage: python price_check.py --deck <file> | --cards 'Card Name' 'Card Name' ...")
