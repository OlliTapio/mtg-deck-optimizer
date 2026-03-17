"""Simulate opening hands for a Commander deck. Uses Scryfall data for card classification."""
import random
import re
import sys
from card_cache import get_deck_cards
from deck_analyzer import get_type_line, get_oracle_text, get_cmc, classify_type, RAMP_PATTERNS


def is_land(card):
    sf = card.get('scryfall')
    if sf is None:
        return False
    return 'Land' in classify_type(get_type_line(sf))


def is_ramp(card):
    sf = card.get('scryfall')
    if sf is None:
        return False
    if is_land(card):
        return False
    oracle = get_oracle_text(sf).lower()
    for pat in RAMP_PATTERNS:
        if re.search(pat, oracle):
            return True
    return False


def is_draw(card):
    sf = card.get('scryfall')
    if sf is None:
        return False
    oracle = get_oracle_text(sf).lower()
    return bool(re.search(r'draw a card|draw .* cards', oracle))


def build_card_pool(cards):
    """Build a list of cards representing the 99 (no commander)."""
    pool = []
    for card in cards:
        is_cmdr = any('Commander' in t for t in card.get('tags', []))
        if is_cmdr:
            continue
        for _ in range(card['count']):
            pool.append(card)
    return pool


def evaluate_hand(hand):
    """Evaluate a 7-card hand. Returns a dict with metrics."""
    lands = [c for c in hand if is_land(c)]
    ramp = [c for c in hand if is_ramp(c)]
    draw = [c for c in hand if is_draw(c)]
    nonland = [c for c in hand if not is_land(c)]

    land_count = len(lands)
    quality = "KEEP" if 2 <= land_count <= 5 else "MULLIGAN"

    if land_count >= 3 and len(ramp) >= 1:
        quality = "STRONG KEEP"
    elif land_count <= 1:
        quality = "MULLIGAN (too few lands)"
    elif land_count >= 6:
        quality = "MULLIGAN (too many lands)"

    return {
        'lands': land_count,
        'ramp': len(ramp),
        'draw': len(draw),
        'nonland': len(nonland),
        'quality': quality,
        'hand': [c['name'] for c in hand],
    }


def simulate(cards, n_hands=10, hand_size=7):
    """Draw n opening hands and evaluate them."""
    pool = build_card_pool(cards)
    results = []
    for _ in range(n_hands):
        hand = random.sample(pool, min(hand_size, len(pool)))
        results.append(evaluate_hand(hand))
    return results


def print_simulation(results):
    """Pretty print simulation results."""
    keeps = 0
    total_lands = 0

    for i, r in enumerate(results, 1):
        print(f"Hand {i}: [{r['quality']}]")
        print(f"  Lands: {r['lands']}, Ramp: {r['ramp']}, Draw: {r['draw']}")
        for name in r['hand']:
            print(f"    - {name}")
        print()
        if 'MULLIGAN' not in r['quality']:
            keeps += 1
        total_lands += r['lands']

    n = len(results)
    print(f"=== Summary ({n} hands) ===")
    print(f"Keepable: {keeps}/{n} ({keeps/n*100:.0f}%)")
    print(f"Avg lands in hand: {total_lands/n:.1f}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 hand_simulator.py <decklist_file> [n_hands]")
        sys.exit(1)

    filepath = sys.argv[1]
    n_hands = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    print("Loading deck and Scryfall data...", file=sys.stderr)
    cards, parsed = get_deck_cards(filepath)
    cmdr_name = "Unknown"
    for c in cards:
        if any('Commander' in t for t in c.get('tags', [])):
            cmdr_name = c['name']
            break

    print(f"Simulating {n_hands} opening hands for {cmdr_name}...\n")
    results = simulate(cards, n_hands)
    print_simulation(results)
