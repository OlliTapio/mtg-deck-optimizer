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


def is_creature(card):
    sf = card.get('scryfall')
    if sf is None:
        return False
    return 'Creature' in classify_type(get_type_line(sf))


def get_land_info(card):
    """Analyze a land card and return its tap condition, colors produced, and type."""
    sf = card.get('scryfall', {})
    oracle = sf.get('oracle_text', '')
    type_line = sf.get('type_line', '')
    produced = sf.get('produced_mana', [])
    name = card.get('name', '')

    # Determine land subtypes
    subtypes = set()
    for t in ['Forest', 'Island', 'Swamp', 'Plains', 'Mountain']:
        if t in type_line and 'non' not in type_line.lower():
            subtypes.add(t)

    # Determine tap condition
    if subtypes and not any(kw in oracle for kw in ['enters tapped', 'enter tapped']):
        # Basic lands with subtypes and no tap text
        condition = 'untapped'
    elif 'enters tapped.' in oracle and 'unless' not in oracle:
        # "This land enters tapped." with possible "You may have" for Mariposa
        if 'You may have this land enter tapped' in oracle:
            condition = 'untapped'  # Player chooses, assume untapped
        else:
            condition = 'always_tapped'
    elif 'two or fewer other lands' in oracle:
        condition = 'fast'  # Fast lands: untapped T1-3
    elif 'unless you control a Forest or an Island' in oracle:
        condition = 'check_forest_island'
    elif 'unless you control an Island or a Swamp' in oracle:
        condition = 'check_island_swamp'
    elif 'unless you control a Swamp or a Forest' in oracle:
        condition = 'check_swamp_forest'
    elif 'unless you have two or more opponents' in oracle:
        condition = 'untapped'  # Always untapped in Commander
    elif 'unless you control two or more basic lands' in oracle:
        condition = 'check_2basics'
    elif '{1}, {T}:' in oracle and 'Add {' in oracle:
        condition = 'filter'  # Filter lands always untap but need mana input for color
    elif 'Activate only if you control a Swamp' in oracle:
        condition = 'tainted'  # Tainted lands: untapped but colorless without Swamp
    else:
        condition = 'untapped'

    # Colors produced (for colored mana, not colorless)
    colors = set(c for c in produced if c in ('W', 'U', 'B', 'R', 'G'))
    has_colorless = 'C' in produced or condition == 'filter' or condition == 'tainted'

    return {
        'name': name,
        'condition': condition,
        'colors': colors,
        'has_colorless': has_colorless,
        'subtypes': subtypes,
        'produced': produced,
    }


def simulate_mana_turn(lands_info, turn, is_commander=True):
    """Simulate which lands are untapped and what colors are available on a given turn.

    Assumes lands are played in order (index 0 = T1, index 1 = T2, etc.).
    Returns the set of colors available and count of total mana on that turn.

    Args:
        lands_info: list of land_info dicts for lands in hand, ordered by play sequence
        turn: which turn to evaluate (1-indexed)
        is_commander: True if playing Commander (for 2+ opponents check)
    """
    played = lands_info[:turn]  # Lands played so far (1 per turn)
    available_colors = set()
    available_mana = 0

    for i, land in enumerate(played):
        play_turn = i + 1  # Turn this land was played
        cond = land['condition']
        entered_tapped = False

        # Check if this land enters tapped based on what was on battlefield before it
        prior_lands = played[:i]
        prior_subtypes = set()
        prior_basics = 0
        has_swamp = False
        for pl in prior_lands:
            prior_subtypes |= pl['subtypes']
            if pl['name'] in ('Swamp', 'Forest', 'Island', 'Plains', 'Mountain'):
                prior_basics += 1
            # Also count typed duals as basics for the "basic lands" check?
            # No — "basic lands" means basic supertype only
            if 'Swamp' in pl['subtypes']:
                has_swamp = True

        if cond == 'always_tapped':
            entered_tapped = True
        elif cond == 'fast':
            entered_tapped = (i >= 3)  # Tapped if 3+ other lands when it enters
        elif cond == 'check_forest_island':
            entered_tapped = not ('Forest' in prior_subtypes or 'Island' in prior_subtypes)
        elif cond == 'check_island_swamp':
            entered_tapped = not ('Island' in prior_subtypes or 'Swamp' in prior_subtypes)
        elif cond == 'check_swamp_forest':
            entered_tapped = not ('Swamp' in prior_subtypes or 'Forest' in prior_subtypes)
        elif cond == 'check_2basics':
            entered_tapped = (prior_basics < 2)
        elif cond == 'untapped':
            entered_tapped = False
        elif cond == 'filter':
            entered_tapped = False
        elif cond == 'tainted':
            entered_tapped = False

        # On the current turn, a land that entered tapped on this turn can't tap
        if play_turn == turn and entered_tapped:
            continue  # Can't use this land this turn

        # Check what mana this land actually produces given board state
        all_lands_in_play = played[:i] + [land]  # Lands in play including this one
        all_subtypes = set()
        board_has_swamp = False
        for pl in all_lands_in_play:
            all_subtypes |= pl['subtypes']
            if 'Swamp' in pl['subtypes']:
                board_has_swamp = True

        if cond == 'tainted':
            if board_has_swamp:
                available_colors |= land['colors']
            # Always produces colorless regardless
            available_mana += 1
        elif cond == 'filter':
            # Filter lands can tap for colorless freely
            # For color, they need mana input — count as colorless for simplicity
            available_mana += 1
        else:
            available_colors |= land['colors']
            available_mana += 1

    return available_colors, available_mana


def optimal_land_order(lands_info):
    """Order lands for optimal play sequence.

    Strategy: Play tapped lands early (T1) so they're online T2+.
    Then basics (enable check lands and tainted), then conditional untapped.
    Filter/colorless lands last since they don't add colors.
    """
    # Separate tapped and untapped lands
    always_tapped = [l for l in lands_info if l['condition'] == 'always_tapped']
    basics = [l for l in lands_info if l['name'] in ('Forest', 'Island', 'Swamp', 'Plains', 'Mountain')]
    conditional = [l for l in lands_info if l['condition'] in (
        'fast', 'check_swamp_forest', 'check_forest_island', 'check_island_swamp', 'check_2basics'
    )]
    tainted = [l for l in lands_info if l['condition'] == 'tainted']
    filters = [l for l in lands_info if l['condition'] == 'filter']
    other_untapped = [l for l in lands_info if l['condition'] == 'untapped'
                      and l['name'] not in ('Forest', 'Island', 'Swamp', 'Plains', 'Mountain')]

    # Sort each group by color count (more colors first)
    for group in [always_tapped, basics, conditional, tainted, filters, other_untapped]:
        group.sort(key=lambda l: -len(l['colors']))

    # Optimal order: tapped T1 (get it out of the way), then basics, then untapped colored,
    # then conditional, then tainted, then filters
    # But only play 1 tapped land early; if we have multiple, basics first for the rest
    # Exception: if we have a basic that produces needed colors for T1 plays, lead with that
    result = []
    has_untapped_t1 = bool(basics) or bool(other_untapped)
    if always_tapped and len(lands_info) >= 2 and has_untapped_t1:
        # We have both tapped and untapped — play tapped T1, untapped T2
        result.append(always_tapped[0])
        remaining_tapped = always_tapped[1:]
    elif always_tapped and len(lands_info) >= 2 and not has_untapped_t1:
        # Only tapped + conditional — play tapped first
        result.append(always_tapped[0])
        remaining_tapped = always_tapped[1:]
    else:
        remaining_tapped = always_tapped

    # Then basics (enable check lands and tainted)
    result.extend(basics)
    # Then other untapped colored lands (Command Tower, Exotic Orchard, etc.)
    result.extend(other_untapped)
    # Then conditional lands (check lands, fast lands)
    result.extend(conditional)
    # Then tainted lands
    result.extend(tainted)
    # Then filters
    result.extend(filters)
    # Then any remaining tapped lands
    result.extend(remaining_tapped)

    return result


def can_cast(card, available_colors):
    """Check if a card's color requirements are met by available colors."""
    sf = card.get('scryfall', {})
    cost = sf.get('mana_cost', '')
    # Extract colored pips from mana cost
    pips = re.findall(r'\{([WUBRGC])\}', cost)
    needed_colors = set()
    for pip in pips:
        if pip in ('W', 'U', 'B', 'R', 'G'):
            needed_colors.add(pip)
    return needed_colors.issubset(available_colors)


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


def get_dork_colors(card):
    """Return the colors a mana dork can produce, or None if not a dork."""
    sf = card.get('scryfall', {})
    oracle = get_oracle_text(sf).lower()
    name = card.get('name', '')
    cmc = get_cmc(sf)

    # Only consider creatures that tap for mana
    type_line = get_type_line(sf)
    if 'Creature' not in type_line:
        return None

    if '{t}: add one mana of any color' in oracle or '{t}: add {c}' in oracle and 'any color' in oracle:
        return {'W', 'U', 'B', 'R', 'G'}  # Birds of Paradise, etc.
    if name == 'Birds of Paradise':
        return {'W', 'U', 'B', 'R', 'G'}
    if '{t}: add {g}' in oracle:
        return {'G'}  # Llanowar Elves, Devoted Druid, etc.
    if name in ('Llanowar Elves', 'Devoted Druid'):
        return {'G'}
    if 'add one mana of any type' in oracle:
        return {'W', 'U', 'B', 'R', 'G'}  # Incubation Druid
    if name == 'Incubation Druid':
        return {'W', 'U', 'B', 'R', 'G'}

    return None


def get_ramp_colors(card):
    """Return colors a ramp spell can add to the mana base, or None if not ramp."""
    sf = card.get('scryfall', {})
    oracle = get_oracle_text(sf).lower()
    name = card.get('name', '')

    if not is_ramp(card):
        return None

    # Land-fetch ramp can find what you need
    if 'search your library for a basic land' in oracle:
        return {'W', 'U', 'B', 'R', 'G'}  # Rampant Growth, STE
    if 'search your library for a forest card' in oracle:
        # Nature's Lore — finds Forest-typed duals (can give any Forest-type color)
        return {'G', 'U', 'B'}  # Forest, Forest Island, Swamp Forest duals
    if 'search your library for a plains, island, swamp, or mountain' in oracle:
        return {'W', 'U', 'B', 'R'}  # Farseek — finds typed duals
    if name == 'Sakura-Tribe Elder':
        return {'W', 'U', 'B', 'R', 'G'}

    return None


def evaluate_hand(hand, cmdr_card=None):
    """Evaluate a 7-card hand with mana awareness. Returns a dict with metrics."""
    lands = [c for c in hand if is_land(c)]
    ramp = [c for c in hand if is_ramp(c)]
    draw = [c for c in hand if is_draw(c)]
    creatures = [c for c in hand if is_creature(c) and not is_land(c)]
    nonland = [c for c in hand if not is_land(c)]

    land_count = len(lands)

    # Analyze lands
    lands_info = [get_land_info(l) for l in lands]
    ordered_lands = optimal_land_order(lands_info)

    # Count always-tapped lands
    tapped_count = sum(1 for l in lands_info if l['condition'] == 'always_tapped')

    # Simulate base mana from lands for turns 1-5
    base_turn_data = {}
    for t in range(1, 6):
        colors, mana = simulate_mana_turn(ordered_lands, t)
        base_turn_data[t] = {'colors': set(colors), 'mana': mana}

    # Now layer in dorks and ramp spells
    turn_data = {t: {'colors': set(base_turn_data[t]['colors']), 'mana': base_turn_data[t]['mana']} for t in range(1, 6)}

    # Check for T1 mana dork (CMC 1 creature that taps for mana)
    t1_dork = None
    t1_dork_colors = set()
    for c in nonland:
        cmc = get_cmc(c.get('scryfall', {}))
        dork_colors = get_dork_colors(c)
        if dork_colors and cmc <= 1 and base_turn_data[1]['mana'] >= 1 and can_cast(c, base_turn_data[1]['colors']):
            t1_dork = c
            t1_dork_colors = dork_colors
            # Dork adds 1 mana + its colors on T2+
            for t in range(2, 6):
                turn_data[t]['mana'] += 1
                turn_data[t]['colors'] |= dork_colors
            break

    # Check for T2 ramp spell (CMC <= 2, castable with T2 mana including dork)
    t2_ramp = None
    t2_ramp_colors = set()
    for c in ramp:
        cmc = get_cmc(c.get('scryfall', {}))
        ramp_colors = get_ramp_colors(c)
        if ramp_colors and cmc <= 2 and turn_data[2]['mana'] >= cmc and can_cast(c, turn_data[2]['colors']):
            t2_ramp = c
            t2_ramp_colors = ramp_colors
            # Ramp adds 1 mana + its findable colors on T3+
            for t in range(3, 6):
                turn_data[t]['mana'] += 1
                turn_data[t]['colors'] |= ramp_colors
            break

    # Also check T2 dork (CMC 2 creature that taps for mana) if no T2 ramp used
    if not t2_ramp:
        for c in nonland:
            if c == t1_dork:
                continue
            cmc = get_cmc(c.get('scryfall', {}))
            dork_colors = get_dork_colors(c)
            if dork_colors and cmc <= 2 and turn_data[2]['mana'] >= cmc and can_cast(c, turn_data[2]['colors']):
                # T2 dork adds mana on T3+
                for t in range(3, 6):
                    turn_data[t]['mana'] += 1
                    turn_data[t]['colors'] |= dork_colors
                break

    # Filter lands can produce color if there's spare mana (mana > 1 from other sources)
    for t in range(1, 6):
        for land in ordered_lands[:t]:
            if land['condition'] == 'filter' and turn_data[t]['mana'] >= 2:
                # Filter land + 1 mana input = 2 colored mana (net +1 colored, -1 generic)
                turn_data[t]['colors'] |= land['colors']

    # Check T1 play (1CMC)
    t1_play = False
    for c in nonland:
        cmc = get_cmc(c.get('scryfall', {}))
        if cmc <= 1 and turn_data[1]['mana'] >= cmc and can_cast(c, turn_data[1]['colors']):
            t1_play = True
            break

    # Check T2 play: any nonland card with CMC <= 2 that we have colors for
    t2_play = False
    t2_creature = False
    for c in nonland:
        cmc = get_cmc(c.get('scryfall', {}))
        if cmc <= 2 and turn_data[2]['mana'] >= cmc and can_cast(c, turn_data[2]['colors']):
            t2_play = True
            if is_creature(c):
                t2_creature = True

    # Check T3 creature: any creature with CMC <= 3 castable by T3
    t3_creature = t2_creature  # If we had a T2 creature, we have a T3 creature
    if not t3_creature:
        for c in creatures:
            cmc = get_cmc(c.get('scryfall', {}))
            if cmc <= 3 and turn_data[3]['mana'] >= cmc and can_cast(c, turn_data[3]['colors']):
                t3_creature = True
                break

    # Check if commander is castable by T4
    cmdr_t4 = False
    if cmdr_card:
        cmdr_sf = cmdr_card.get('scryfall', {})
        cmdr_cmc = get_cmc(cmdr_sf)
        cmdr_t4 = (turn_data[4]['mana'] >= cmdr_cmc and can_cast(cmdr_card, turn_data[4]['colors']))

    # Quality assessment
    quality = "KEEP" if 2 <= land_count <= 5 else "MULLIGAN"

    if land_count <= 1:
        quality = "MULLIGAN (too few lands)"
    elif land_count >= 6:
        quality = "MULLIGAN (too many lands)"
    elif tapped_count >= 2 and land_count <= 3:
        quality = "MULLIGAN (too many tapped lands)"
    elif land_count >= 3 and len(ramp) >= 1 and t2_play:
        quality = "STRONG KEEP"
    elif land_count >= 2 and t1_play and t3_creature:
        quality = "STRONG KEEP"

    # Downgrade if no colors for any spells by T2
    if 'MULLIGAN' not in quality and land_count >= 2 and not t2_play and not t1_play:
        if not any(can_cast(c, turn_data[3]['colors']) for c in nonland if get_cmc(c.get('scryfall', {})) <= 3):
            quality = "MULLIGAN (no castable spells)"

    return {
        'lands': land_count,
        'tapped_lands': tapped_count,
        'ramp': len(ramp),
        'draw': len(draw),
        'nonland': len(nonland),
        'quality': quality,
        't1_play': t1_play,
        't2_play': t2_play,
        't3_creature': t3_creature,
        'cmdr_t4': cmdr_t4,
        'colors_t2': turn_data[2]['colors'],
        'mana_t2': turn_data[2]['mana'],
        'colors_t3': turn_data[3]['colors'],
        'mana_t3': turn_data[3]['mana'],
        'hand': [c['name'] for c in hand],
    }


def simulate(cards, n_hands=10, hand_size=7):
    """Draw n opening hands and evaluate them."""
    pool = build_card_pool(cards)
    cmdr_card = None
    for c in cards:
        if any('Commander' in t for t in c.get('tags', [])):
            cmdr_card = c
            break
    results = []
    for _ in range(n_hands):
        hand = random.sample(pool, min(hand_size, len(pool)))
        results.append(evaluate_hand(hand, cmdr_card))
    return results


def print_simulation(results):
    """Pretty print simulation results."""
    keeps = 0
    total_lands = 0
    t2_plays = 0
    t3_creatures = 0
    cmdr_t4s = 0
    keepable_count = 0

    for i, r in enumerate(results, 1):
        print(f"Hand {i}: [{r['quality']}]")
        tags = []
        if r['t1_play']:
            tags.append("T1-play")
        if r['t2_play']:
            tags.append("T2-play")
        if r['t3_creature']:
            tags.append("T3-creature")
        if r['cmdr_t4']:
            tags.append("cmdr-T4")
        if r['tapped_lands'] > 0:
            tags.append(f"{r['tapped_lands']}x-tapped")

        mana_info = f"T2: {r['mana_t2']}mana {{{','.join(sorted(r['colors_t2']))}}}  T3: {r['mana_t3']}mana {{{','.join(sorted(r['colors_t3']))}}}"
        print(f"  Lands: {r['lands']}, Ramp: {r['ramp']}, Draw: {r['draw']}  |  {mana_info}")
        if tags:
            print(f"  [{', '.join(tags)}]")
        for name in r['hand']:
            print(f"    - {name}")
        print()

        if 'MULLIGAN' not in r['quality']:
            keeps += 1
            keepable_count += 1
            if r['t2_play']:
                t2_plays += 1
            if r['t3_creature']:
                t3_creatures += 1
            if r['cmdr_t4']:
                cmdr_t4s += 1
        total_lands += r['lands']

    n = len(results)
    print(f"=== Summary ({n} hands) ===")
    print(f"Keepable: {keeps}/{n} ({keeps/n*100:.0f}%)")
    print(f"Avg lands in hand: {total_lands/n:.1f}")
    if keepable_count > 0:
        print(f"\nAmong keepable hands:")
        print(f"  T2 play available: {t2_plays}/{keepable_count} ({t2_plays/keepable_count*100:.0f}%)")
        print(f"  Creature by T3:    {t3_creatures}/{keepable_count} ({t3_creatures/keepable_count*100:.0f}%)")
        print(f"  Commander by T4:   {cmdr_t4s}/{keepable_count} ({cmdr_t4s/keepable_count*100:.0f}%)")


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
