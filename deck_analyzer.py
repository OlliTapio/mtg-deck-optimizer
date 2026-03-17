#!/usr/bin/env python3
"""Deck analyzer using Scryfall data via card_cache.py.

Usage:
    python3 deck_analyzer.py decks/<deck>/decklist.txt              # Full analysis
    python3 deck_analyzer.py decks/<deck>/decklist.txt --oracle     # Full oracle text dump
    python3 deck_analyzer.py decks/<deck>/decklist.txt --speed      # Instant vs sorcery breakdown
    python3 deck_analyzer.py decks/<deck>/decklist.txt --cuts       # Cut candidates sorted by impact
    python3 deck_analyzer.py decks/<deck>/decklist.txt --search rad # Grep oracle text
"""
import argparse
import sys
import re
from collections import Counter, defaultdict

from card_cache import get_deck_cards


# --- Helpers to extract Scryfall fields, handling double-faced / split cards ---

def get_type_line(sf):
    if sf is None:
        return ""
    if 'card_faces' in sf and 'type_line' not in sf:
        return sf['card_faces'][0].get('type_line', '')
    return sf.get('type_line', '')


def get_mana_cost(sf):
    if sf is None:
        return ""
    if 'card_faces' in sf:
        costs = [face.get('mana_cost', '') for face in sf['card_faces']]
        return ' // '.join(c for c in costs if c)
    return sf.get('mana_cost', '')


def get_oracle_text(sf):
    if sf is None:
        return ""
    if 'card_faces' in sf:
        texts = [face.get('oracle_text', '') for face in sf['card_faces']]
        return '\n---\n'.join(t for t in texts if t)
    return sf.get('oracle_text', '')


def get_cmc(sf):
    if sf is None:
        return 0
    return sf.get('cmc', 0)


def get_keywords(sf):
    if sf is None:
        return []
    return sf.get('keywords', [])


def get_color_identity(sf):
    if sf is None:
        return []
    return sf.get('color_identity', [])


def get_produced_mana(sf):
    if sf is None:
        return []
    return sf.get('produced_mana', [])


def get_price_eur(sf):
    if sf is None:
        return None
    p = sf.get('prices', {}).get('eur')
    return float(p) if p else None


# --- Card type classification ---

MAIN_TYPES = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Land', 'Planeswalker', 'Battle']


def classify_type(type_line):
    types = set()
    for t in MAIN_TYPES:
        if t in type_line:
            types.add(t)
    return types


# --- Mana pip counting ---

PIP_PATTERN = re.compile(r'\{([WUBRGC])\}')
HYBRID_PATTERN = re.compile(r'\{([WUBRG])/([WUBRG])\}')


def count_pips(mana_cost_str):
    pips = Counter()
    for m in HYBRID_PATTERN.finditer(mana_cost_str):
        pips[m.group(1)] += 1
        pips[m.group(2)] += 1
    for m in PIP_PATTERN.finditer(mana_cost_str):
        pips[m.group(1)] += 1
    return pips


# --- Ramp detection (for nonland cards) ---

RAMP_PATTERNS = [
    r'add\b.*\bmana\b', r'search your library for a.*(land|forest|island|swamp|mountain|plains)',
    r'add \{', r'puts? .* land.* onto the battlefield',
    r'put .* onto the battlefield tapped, then shuffle',
]


COLOR_NAMES = {'W': 'White', 'U': 'Blue', 'B': 'Black', 'R': 'Red', 'G': 'Green', 'C': 'Colorless'}
COLOR_ORDER = ['W', 'U', 'B', 'R', 'G', 'C']


# ==================== SHARED HELPERS ====================

def load_deck(decklist_file):
    """Load and split deck into commander + cards list."""
    cards, parsed = get_deck_cards(decklist_file)
    commander = None
    deck_cards = []
    for c in cards:
        if c.get('scryfall') is None:
            print(f"  SKIPPING (no Scryfall data): {c['name']}", file=sys.stderr)
            continue
        if any('Commander' in t for t in c.get('tags', [])):
            commander = c
        else:
            deck_cards.append(c)
    all_cards = ([commander] if commander else []) + deck_cards
    cmdr_name = commander['name'] if commander else "Unknown"
    return all_cards, cmdr_name


def oracle_text_search(cards, keyword):
    """Search oracle texts for a keyword. Returns set of card names."""
    matches = set()
    pattern = re.compile(keyword, re.IGNORECASE)
    for c in cards:
        oracle = get_oracle_text(c.get('scryfall'))
        if pattern.search(oracle):
            matches.add(c['name'])
    return matches


# ==================== MODES ====================

def mode_full(all_cards, cmdr_name):
    """Full deck analysis."""
    print("=" * 60)
    print(f"  DECK ANALYSIS: {cmdr_name}")
    print("=" * 60)

    total = sum(c['count'] for c in all_cards)
    print(f"\nTotal cards: {total}")

    # Card Type Breakdown
    print("\n--- Card Type Breakdown ---")
    type_counts = Counter()
    for c in all_cards:
        for t in classify_type(get_type_line(c['scryfall'])):
            type_counts[t] += c['count']
    for t in MAIN_TYPES:
        if type_counts[t]:
            print(f"  {t:15s} {type_counts[t]:3d}")

    # Mana Curve
    print("\n--- Mana Curve (nonland cards) ---")
    cmc_counts = Counter()
    for c in all_cards:
        if 'Land' in classify_type(get_type_line(c['scryfall'])):
            continue
        cmc_counts[int(get_cmc(c['scryfall']))] += c['count']
    if cmc_counts:
        for cmc_val in range(0, max(cmc_counts.keys()) + 1):
            cnt = cmc_counts.get(cmc_val, 0)
            print(f"  {cmc_val:2d} CMC: {'#' * cnt} ({cnt})")
        avg = sum(k * v for k, v in cmc_counts.items()) / max(sum(cmc_counts.values()), 1)
        print(f"  Average CMC: {avg:.2f}")

    # Color Pip Requirements
    print("\n--- Color Pip Requirements ---")
    total_pips = Counter()
    for c in all_cards:
        if 'Land' in classify_type(get_type_line(c['scryfall'])):
            continue
        pips = count_pips(get_mana_cost(c['scryfall']))
        for color, cnt in pips.items():
            total_pips[color] += cnt * c['count']
    for color in COLOR_ORDER:
        if total_pips[color]:
            print(f"  {{{color}}} ({COLOR_NAMES[color]:>10s}): {total_pips[color]}")

    # Mana Source Analysis
    print("\n--- Mana Source Analysis ---")
    color_sources = Counter()
    mana_source_cards = []
    for c in all_cards:
        sf = c['scryfall']
        produced = get_produced_mana(sf)
        if produced:
            for color in produced:
                if color in COLOR_NAMES:
                    color_sources[color] += c['count']
            mana_source_cards.append(c)
    for color in COLOR_ORDER:
        if color_sources[color]:
            print(f"  {{{color}}} ({COLOR_NAMES[color]:>10s}): {color_sources[color]} sources")
    any_count = sum(1 for c in mana_source_cards for _ in range(c['count'])
                    if set(get_produced_mana(c['scryfall'])) >= {'W', 'U', 'B', 'R', 'G'})
    if any_count:
        print(f"  Any color: {any_count} sources")

    # Keyword Analysis
    print("\n--- Keyword Analysis ---")
    kw_counts = Counter()
    for c in all_cards:
        for kw in get_keywords(c['scryfall']):
            kw_counts[kw] += c['count']
    for kw, cnt in kw_counts.most_common():
        print(f"  {kw}: {cnt}")

    # Category Breakdown (otags)
    print("\n--- Functional Category Breakdown (Scryfall otags) ---")
    from otag_fetcher import fetch_otags_for_cards, BASICS, OTAGS
    card_names = sorted(set(c['name'] for c in all_cards if c['name'] not in BASICS))
    otags_by_card = fetch_otags_for_cards(card_names)

    otag_groups = defaultdict(list)
    for c in all_cards:
        for tag in otags_by_card.get(c['name'], []):
            otag_groups[tag].append(c['name'])

    proliferate_cards = [c['name'] for c in all_cards
                        if 'proliferate' in get_oracle_text(c['scryfall']).lower()]
    if proliferate_cards:
        otag_groups['proliferate'] = proliferate_cards

    for tag in (['proliferate'] + OTAGS):
        names = sorted(set(otag_groups.get(tag, [])))
        if names:
            print(f"\n  {tag} ({len(names)}):")
            for n in names:
                print(f"    - {n}")

    # Command Zone Template Check
    removal = set(otag_groups.get('removal', []))
    counters = set(otag_groups.get('counterspell', []))
    wipes = set(otag_groups.get('board-wipe', []))
    draw = set(otag_groups.get('draw', []))
    card_adv = set(otag_groups.get('card-advantage', []))
    ramp = set(otag_groups.get('ramp', []))

    print(f"\n  --- Command Zone Template Check (otag-based) ---")
    print(f"  Targeted Disruption (removal + counters): {len(removal | counters)}/12")
    print(f"  Mass Disruption (board wipes):            {len(wipes)}/6")
    print(f"  Card Advantage (draw + card-advantage):   {len(draw | card_adv)}/12")
    print(f"  Ramp:                                     {len(ramp)}/10")

    print("\n" + "=" * 60)
    print("  Analysis complete.")
    print("=" * 60)


def mode_oracle(all_cards, cmdr_name):
    """Print full oracle text for every card."""
    print(f"=== Oracle Text Dump: {cmdr_name} ===\n")
    basics = {'Forest', 'Island', 'Swamp', 'Mountain', 'Plains'}

    for c in sorted(all_cards, key=lambda x: x['name']):
        if c['name'] in basics:
            continue
        sf = c['scryfall']
        price = get_price_eur(sf)
        price_str = f"€{price:.2f}" if price else "N/A"
        print(f"### {c['name']}  {get_mana_cost(sf)}  (CMC {get_cmc(sf):.0f})  —  {price_str}")
        print(f"{get_type_line(sf)}")
        print(f"{get_oracle_text(sf)}")
        print()


def mode_speed(all_cards, cmdr_name):
    """Break down instant vs sorcery speed interaction."""
    print(f"=== Interaction Speed Analysis: {cmdr_name} ===\n")

    from otag_fetcher import fetch_otags_for_cards, BASICS
    card_names = sorted(set(c['name'] for c in all_cards if c['name'] not in BASICS))
    otags_by_card = fetch_otags_for_cards(card_names)

    interaction_tags = {'removal', 'board-wipe', 'counterspell'}
    protection_tags = {'hexproof', 'indestructible', 'phase'}

    instant_interaction = []
    sorcery_interaction = []
    instant_protection = []
    sorcery_protection = []

    for c in all_cards:
        sf = c['scryfall']
        type_line = get_type_line(sf)
        oracle = get_oracle_text(sf)
        tags = set(otags_by_card.get(c['name'], []))
        keywords = set(get_keywords(sf))

        is_interaction = bool(tags & interaction_tags)
        is_protection = bool(re.search(
            r'hexproof|indestructible|phase out|can\'t be the target', oracle.lower()))

        if not is_interaction and not is_protection:
            continue

        is_instant_speed = (
            'Instant' in type_line or
            'Flash' in keywords or
            # Activated abilities on permanents are instant speed
            ('{T}' in oracle and ('Creature' in type_line or 'Artifact' in type_line))
        )

        entry = {
            'name': c['name'],
            'cost': get_mana_cost(sf),
            'type': type_line,
            'tags': sorted(tags & interaction_tags) if is_interaction else ['protection'],
            'oracle_preview': oracle[:100],
        }

        if is_interaction:
            if is_instant_speed:
                instant_interaction.append(entry)
            else:
                sorcery_interaction.append(entry)

        if is_protection:
            if is_instant_speed:
                instant_protection.append(entry)
            else:
                sorcery_protection.append(entry)

    print("--- INSTANT-SPEED INTERACTION (can stop opponents from winning) ---")
    for e in sorted(instant_interaction, key=lambda x: x['name']):
        print(f"  {e['name']}  {e['cost']}  [{', '.join(e['tags'])}]")
        print(f"    {e['type']}")
        print(f"    {e['oracle_preview']}")
        print()
    print(f"  Count: {len(instant_interaction)}")

    print("\n--- SORCERY-SPEED INTERACTION ---")
    for e in sorted(sorcery_interaction, key=lambda x: x['name']):
        print(f"  {e['name']}  {e['cost']}  [{', '.join(e['tags'])}]")
        print(f"    {e['type']}")
        print(f"    {e['oracle_preview']}")
        print()
    print(f"  Count: {len(sorcery_interaction)}")

    print("\n--- INSTANT-SPEED PROTECTION ---")
    for e in sorted(instant_protection, key=lambda x: x['name']):
        print(f"  {e['name']}  {e['cost']}")
        print(f"    {e['oracle_preview']}")
        print()
    print(f"  Count: {len(instant_protection)}")

    print("\n--- SORCERY-SPEED PROTECTION ---")
    for e in sorted(sorcery_protection, key=lambda x: x['name']):
        print(f"  {e['name']}  {e['cost']}")
        print(f"    {e['oracle_preview']}")
        print()
    print(f"  Count: {len(sorcery_protection)}")


def mode_cuts(all_cards, cmdr_name):
    """List potential cut candidates sorted by CMC (high to low), with otags and price."""
    print(f"=== Cut Candidates: {cmdr_name} ===\n")

    from otag_fetcher import fetch_otags_for_cards, BASICS
    card_names = sorted(set(c['name'] for c in all_cards if c['name'] not in BASICS))
    otags_by_card = fetch_otags_for_cards(card_names)

    nonland = []
    for c in all_cards:
        sf = c['scryfall']
        types = classify_type(get_type_line(sf))
        if 'Land' in types:
            continue
        if any('Commander' in t for t in c.get('tags', [])):
            continue

        cmc = get_cmc(sf)
        tags = otags_by_card.get(c['name'], [])
        price = get_price_eur(sf)
        price_str = f"€{price:.2f}" if price else "N/A"
        type_line = get_type_line(sf)

        nonland.append({
            'name': c['name'],
            'cmc': cmc,
            'cost': get_mana_cost(sf),
            'type': type_line,
            'tags': tags,
            'price': price_str,
            'oracle_preview': get_oracle_text(sf)[:80],
        })

    # Sort by CMC descending, then name
    nonland.sort(key=lambda x: (-x['cmc'], x['name']))

    print(f"{'CMC':>3s}  {'Card':<35s}  {'Cost':<12s}  {'Price':>6s}  Otags")
    print("-" * 90)
    for c in nonland:
        tags_str = ', '.join(c['tags']) if c['tags'] else '(none)'
        print(f"{c['cmc']:3.0f}  {c['name']:<35s}  {c['cost']:<12s}  {c['price']:>6s}  {tags_str}")

    # Flag cards with no otags (potentially low-impact)
    no_tags = [c for c in nonland if not c['tags']]
    if no_tags:
        print(f"\n--- Cards with NO otags ({len(no_tags)}) — potential cut candidates ---")
        for c in sorted(no_tags, key=lambda x: (-x['cmc'], x['name'])):
            print(f"  CMC {c['cmc']:.0f}  {c['name']}  {c['cost']}")
            print(f"    {c['oracle_preview']}")
            print()


def mode_search(all_cards, keyword):
    """Search oracle texts for a keyword."""
    matches = []
    pattern = re.compile(keyword, re.IGNORECASE)
    for c in all_cards:
        sf = c['scryfall']
        oracle = get_oracle_text(sf)
        if pattern.search(oracle):
            matches.append(c)

    if not matches:
        print(f"No cards found matching '{keyword}'")
        return

    print(f"=== Oracle search: '{keyword}' — {len(matches)} card(s) ===\n")
    for c in sorted(matches, key=lambda x: x['name']):
        sf = c['scryfall']
        price = get_price_eur(sf)
        price_str = f"€{price:.2f}" if price else "N/A"
        print(f"### {c['name']}  {get_mana_cost(sf)}  (CMC {get_cmc(sf):.0f})  —  {price_str}")
        print(f"{get_type_line(sf)}")
        # Highlight matching lines
        oracle = get_oracle_text(sf)
        for line in oracle.split('\n'):
            if pattern.search(line):
                print(f"  >>> {line}")
            else:
                print(f"  {line}")
        print()


# ==================== MAIN ====================

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Analyze a Commander deck')
    ap.add_argument('decklist', help='Path to decklist file')
    ap.add_argument('--oracle', action='store_true', help='Dump full oracle text for all cards')
    ap.add_argument('--speed', action='store_true', help='Instant vs sorcery speed interaction breakdown')
    ap.add_argument('--cuts', action='store_true', help='List cut candidates sorted by CMC')
    ap.add_argument('--search', type=str, help='Search oracle texts for a keyword')
    args = ap.parse_args()

    print(f"Loading deck from {args.decklist}...", file=sys.stderr)
    all_cards, cmdr_name = load_deck(args.decklist)

    if args.oracle:
        mode_oracle(all_cards, cmdr_name)
    elif args.speed:
        mode_speed(all_cards, cmdr_name)
    elif args.cuts:
        mode_cuts(all_cards, cmdr_name)
    elif args.search:
        mode_search(all_cards, args.search)
    else:
        mode_full(all_cards, cmdr_name)
