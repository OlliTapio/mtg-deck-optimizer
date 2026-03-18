#!/usr/bin/env python3
"""Auto-pilot for game_simulator: plays a deck with simple heuristic AI."""
import argparse
import random
import sys

from card_cache import get_deck_cards
from game_simulator import (
    GameState, Player, Opponent, Permanent,
    card_from_scryfall, init_game_from_cards,
    get_available_mana, can_cast, tap_mana_for,
    play_land, cast_spell, create_token, resolve_combat,
    opponent_turn, check_game_over, format_state,
    _post_game_summary,
)


def pick_land_to_play(player):
    """Pick the best land to play from hand."""
    lands = [c for c in player.hand if 'Land' in c.get('type_line', '')]
    if not lands:
        return None
    # Prefer lands that produce colors we need, then multicolor, then basics
    # Simple heuristic: prefer lands with more produced colors (taplands/duals)
    # but actually prefer lands that untap (no "enters tapped" in oracle)
    untapped = [l for l in lands if 'enters tapped' not in l.get('oracle_text', '').lower()
                and 'enters the battlefield tapped' not in l.get('oracle_text', '').lower()]
    tapped = [l for l in lands if l not in untapped]
    # Play untapped first
    target = untapped if untapped else tapped
    # Prefer multicolor
    target.sort(key=lambda l: len(l.get('produced_mana', [])), reverse=True)
    return target[0]


def pick_spells_to_cast(player, commander_tax=0):
    """Pick spells to cast in priority order."""
    castable = []
    for c in player.hand:
        if 'Land' in c.get('type_line', ''):
            continue
        if can_cast(player, c):
            castable.append(c)

    # Also check commander
    cmdr = None
    if player.command_zone:
        cmdr = player.command_zone[0]
        if can_cast(player, cmdr, commander_tax=commander_tax):
            castable.append(cmdr)

    if not castable:
        return []

    # Priority: ramp/mana < draw/engine < threats, but cast what fits the mana
    def priority(c):
        tl = c.get('type_line', '').lower()
        oracle = c.get('oracle_text', '').lower()
        cmc = c.get('cmc', 0)
        score = 0
        # Ramp is high priority early
        if any(kw in oracle for kw in ['add', 'search your library for a', 'land card']):
            score += 100
        # Draw/card advantage
        if 'draw' in oracle:
            score += 80
        # Commander is important
        if c.get('is_commander'):
            score += 90
        # Creatures that produce mana
        if c.get('produced_mana'):
            score += 95
        # Prefer lower CMC to deploy more
        score += (10 - cmc)
        return score

    castable.sort(key=priority, reverse=True)
    return castable


def auto_play_turn(gs, rng, log):
    """Play one full turn with heuristic AI."""
    p = gs.player

    # === Untap + Draw ===
    if gs.turn_number > 1:
        p.untap_all()
    p.reset_land_drops()

    if gs.turn_number > 1:
        p.draw()
        if p.life <= 0:
            return

    log(f"\n{'='*60}")
    log(f"  TURN {gs.turn_number}")
    log(f"{'='*60}")

    # === Main Phase 1 ===
    gs.phase = "main1"

    # Play a land
    land = pick_land_to_play(p)
    if land:
        play_land(p, land)
        gs.cards_played.append(land['name'])
        log(f"  Played {land['name']}")

    # Cast spells (ramp/setup first)
    cast_count = 0
    while cast_count < 5:  # safety limit
        spells = pick_spells_to_cast(p, p.commander_tax)
        if not spells:
            break
        card = spells[0]
        is_cmdr = card.get('is_commander')
        tax = p.commander_tax if is_cmdr else 0

        if is_cmdr:
            if cast_spell(p, card, commander_tax=tax):
                if gs.commander_first_cast_turn == 0:
                    gs.commander_first_cast_turn = gs.turn_number
                gs.cards_played.append(card['name'])
                p.commander_tax += 2
                log(f"  Cast {card['name']} from command zone!")
                cast_count += 1
            else:
                break
        else:
            if cast_spell(p, card):
                gs.cards_played.append(card['name'])
                log(f"  Cast {card['name']}")
                cast_count += 1
            else:
                break

    # === Combat ===
    gs.phase = "combat"
    creatures = [perm for perm in p.battlefield
                 if perm.is_creature() and not perm.tapped and not perm.summoning_sick]
    if creatures:
        # Attack weakest alive opponent
        alive_opps = [o for o in gs.opponents if not o.eliminated]
        if alive_opps:
            target = min(alive_opps, key=lambda o: o.life)
            attacks = [(c, target) for c in creatures]
            dmg = resolve_combat(p, attacks)
            if dmg > 0:
                log(f"  Attacked {target.name} for {dmg} damage (life: {target.life})")
                if target.eliminated:
                    log(f"  {target.name} ELIMINATED!")

    # === Main Phase 2 ===
    gs.phase = "main2"
    # Try to cast more after combat
    while True:
        spells = pick_spells_to_cast(p, p.commander_tax)
        if not spells:
            break
        card = spells[0]
        is_cmdr = card.get('is_commander')
        tax = p.commander_tax if is_cmdr else 0
        if is_cmdr:
            if cast_spell(p, card, commander_tax=tax):
                if gs.commander_first_cast_turn == 0:
                    gs.commander_first_cast_turn = gs.turn_number
                gs.cards_played.append(card['name'])
                p.commander_tax += 2
                log(f"  Cast {card['name']} from command zone!")
            else:
                break
        else:
            if cast_spell(p, card):
                gs.cards_played.append(card['name'])
                log(f"  Cast {card['name']}")
            else:
                break

    # === End Step — discard to 7 ===
    while len(p.hand) > 7:
        # Discard highest CMC
        worst = max(p.hand, key=lambda c: c.get('cmc', 0))
        p.hand.remove(worst)
        p.graveyard.append(worst)
        log(f"  Discarded {worst['name']}")

    # === Opponent Turns ===
    for opp in gs.opponents:
        if opp.eliminated:
            continue
        events = opponent_turn(opp, gs.turn_number, p, rng=rng, other_opponents=gs.opponents)
        for e in events:
            log(f"  {e}")
        # If combo, try to respond with instant
        if any("combo" in e.lower() for e in events):
            instants = [perm for perm in p.battlefield
                        if 'Instant' in perm.card.get('type_line', '')]
            # Check hand for instants
            hand_instants = [c for c in p.hand
                             if 'Instant' in c.get('type_line', '') and can_cast(p, c)]
            if hand_instants:
                resp = hand_instants[0]
                cast_spell(p, resp)
                gs.cards_played.append(resp['name'])
                opp.board_power = max(0, opp.board_power - 5)
                log(f"  Responded with {resp['name']}! Combo disrupted!")
            else:
                p.life = 0
                log(f"  {opp.name}'s combo succeeds! You lose!")

    # State summary
    mana = get_available_mana(p)
    alive = [o for o in gs.opponents if not o.eliminated]
    log(f"  >> Life: {p.life} | Hand: {len(p.hand)} | Battlefield: {len(p.battlefield)} | "
        f"Opponents alive: {len(alive)}")


def run_auto_game(decklist_path, seed=None, max_turns=15, opponent_archetypes=None):
    """Run a full auto-piloted game."""
    print(f"Loading deck from {decklist_path}...", file=sys.stderr)
    all_cards, parsed = get_deck_cards(decklist_path)
    cards = [card_from_scryfall(c) for c in all_cards]

    if opponent_archetypes is None:
        opponent_archetypes = ['aggro', 'midrange', 'control']

    gs = init_game_from_cards(cards, seed=seed, opponent_archetypes=opponent_archetypes)
    rng = random.Random(seed)

    lines = []
    def log(msg):
        lines.append(msg)

    cmdr_name = gs.player.command_zone[0]['name'] if gs.player.command_zone else "Unknown"
    log(f"=== Game Start: {cmdr_name} ===")
    log(f"Opponents: {', '.join(o.name + ' (' + o.archetype + ')' for o in gs.opponents)}")
    log(f"Opening hand: {', '.join(c['name'] for c in gs.player.hand)}")

    while gs.turn_number <= max_turns and not gs.game_over:
        auto_play_turn(gs, rng, log)

        if check_game_over(gs.player, gs.opponents):
            gs.game_over = True
            if gs.player.life <= 0:
                gs.winner = "opponents"
            else:
                gs.winner = gs.player.name

        gs.turn_number += 1

    log(_post_game_summary(gs))

    return '\n'.join(lines), gs


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Auto-pilot a Commander game')
    ap.add_argument('decklist', help='Path to decklist file')
    ap.add_argument('--opponents', type=str, default='aggro,midrange,control')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--max-turns', type=int, default=15)
    args = ap.parse_args()

    archetypes = [a.strip() for a in args.opponents.split(',')]
    output, gs = run_auto_game(args.decklist, seed=args.seed, max_turns=args.max_turns,
                                opponent_archetypes=archetypes)
    print(output)
