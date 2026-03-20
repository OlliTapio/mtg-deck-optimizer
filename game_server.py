#!/usr/bin/env python3
"""Persistent Commander Game Server.

Game state is saved to a JSON file after every action. Any agent can call
the server at any time — state persists across process invocations.

Usage:
    # Create a game (returns game_id)
    python3 game_server.py create decks/a.txt decks/b.txt decks/c.txt decks/d.txt

    # Player sees their hand (private)
    python3 game_server.py hand <game_id> <player_name>

    # Player decides mulligan
    python3 game_server.py mulligan <game_id> <player_name>
    python3 game_server.py keep <game_id> <player_name> [card_to_bottom]

    # Begin turn (untap, draw)
    python3 game_server.py begin <game_id> <player_name>

    # Do an action
    python3 game_server.py action <game_id> <player_name> "play Forest"
    python3 game_server.py action <game_id> <player_name> "cast Sol Ring"
    python3 game_server.py action <game_id> <player_name> "cast commander"
    python3 game_server.py action <game_id> <player_name> "attack all -> Edric"
    python3 game_server.py action <game_id> <player_name> "pass"

    # See valid actions
    python3 game_server.py valid <game_id> <player_name>

    # See board from your perspective
    python3 game_server.py state <game_id> <player_name>

    # End turn
    python3 game_server.py end <game_id> <player_name>

    # Check priority (who needs to act?)
    python3 game_server.py priority <game_id>

    # Respond during opponent's turn (instant speed)
    python3 game_server.py respond <game_id> <player_name> "cast Swords to Plowshares"
    python3 game_server.py respond <game_id> <player_name> "pass"
"""
import json
import os
import random
import sys
import pickle
from pathlib import Path

from card_cache import get_deck_cards
from game_simulator import (
    Player, Permanent, card_from_scryfall,
    get_available_mana, can_cast, tap_mana_for,
    play_land, cast_spell, create_token,
)
from game_orchestrator import GameEngine, detect_triggers

GAMES_DIR = Path("/tmp/mtg_games")
GAMES_DIR.mkdir(exist_ok=True)


def _trigger_hint(oracle_text, player_name, perm_name):
    """Generate a resolution hint from oracle text telling the player what to call."""
    oracle = oracle_text.lower()
    hints = []

    if 'draw' in oracle and 'card' in oracle:
        import re
        m = re.search(r'draw (\w+) card', oracle)
        n = {'a': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}.get(m.group(1), 1) if m else 1
        hints.append(f'/draw count={n}')
    if 'put that card into your hand' in oracle or 'put it into your hand' in oracle:
        # Yuriko-style: reveal top card → into hand (it's a draw)
        hints.append('/draw count=1 (reveal top card and put into hand)')
    if 'rad counter' in oracle:
        hints.append('/modify target_player=OPPONENT permanent="" counter_type="rad" amount=1 (player counter, not permanent)')
    if 'proliferate' in oracle:
        hints.append('/proliferate with targets for each permanent/player that has counters')
    if '+1/+1 counter' in oracle:
        import re
        m = re.search(r'(\w+) \+1/\+1 counter', oracle)
        n = {'a': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4}.get(m.group(1), 1) if m else 1
        hints.append(f'/modify counter_type="+1/+1" amount={n}')
    if 'search your library' in oracle or 'search their library' in oracle:
        if 'battlefield' in oracle:
            hints.append('/search destination="battlefield" tapped=true')
        elif 'hand' in oracle:
            hints.append('/search destination="hand"')
        else:
            hints.append('/search destination="hand"')
    if 'mill' in oracle:
        import re
        m = re.search(r'mill (\w+)', oracle)
        n = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}.get(m.group(1) if m else '', 2)
        hints.append(f'/mill count={n}')
    if 'deals' in oracle and 'damage' in oracle:
        hints.append('/damage target=PLAYER amount=N')
    if 'destroy' in oracle:
        hints.append('/destroy target_player=PLAYER permanent=CARD')
    if 'return' in oracle and 'graveyard' in oracle:
        if 'battlefield' in oracle:
            hints.append('/move from_zone="graveyard" to_zone="battlefield"')
        elif 'hand' in oracle:
            hints.append('/move from_zone="graveyard" to_zone="hand"')
    if 'scry' in oracle:
        hints.append('/scry count=N')
    if 'exile' in oracle:
        hints.append('/move to_zone="exile"')
    if 'loses' in oracle and 'life' in oracle:
        if 'each opponent' in oracle:
            hints.append('/damage each opponent (life loss = mana value of revealed card)')
        else:
            hints.append('/damage (as life loss)')
    if 'gains' in oracle and 'life' in oracle:
        hints.append('(life gain not tracked beyond life total — use /damage with negative if needed)')
    if 'experience counter' in oracle:
        hints.append('/modify on player-tracking permanent with counter_type="experience"')

    return '; '.join(hints) if hints else 'Read oracle text and resolve manually'


# ==================== State Persistence ====================

import fcntl

def _save_game(game_id, engine, meta=None):
    """Save engine state to disk with file locking."""
    path = GAMES_DIR / f"{game_id}.pkl"
    lock_path = GAMES_DIR / f"{game_id}.lock"
    with open(lock_path, 'w') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        state = {
            'engine': engine,
            'meta': meta or {},
        }
        with open(path, 'wb') as f:
            pickle.dump(state, f)
        fcntl.flock(lock_f, fcntl.LOCK_UN)


def _load_game(game_id):
    """Load engine state from disk with file locking."""
    path = GAMES_DIR / f"{game_id}.pkl"
    lock_path = GAMES_DIR / f"{game_id}.lock"
    if not path.exists():
        return None, None
    with open(lock_path, 'w') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_SH)
        with open(path, 'rb') as f:
            state = pickle.load(f)
        fcntl.flock(lock_f, fcntl.LOCK_UN)
    return state['engine'], state.get('meta', {})


# ==================== Game Creation ====================

def cmd_create(decklists, seed=None):
    """Create a new game. Returns game_id and player info."""
    if seed is None:
        seed = random.randint(1, 99999)

    game_id = f"g{seed}"

    # Create engine without auto-mulligan
    from game_mcp_server import _create_engine_no_mulligan
    engine = _create_engine_no_mulligan(decklists, seed)

    # Randomize first player (Commander rule)
    rng = random.Random(seed)
    first_idx = rng.randint(0, len(engine.players) - 1)
    engine.active_idx = first_idx

    # Set mulligan order (sequential, starting from first player)
    mulligan_order = []
    for i in range(len(engine.players)):
        idx = (first_idx + i) % len(engine.players)
        mulligan_order.append(engine.players[idx].name)

    meta = {
        'seed': seed,
        'phase': 'mulligan',  # mulligan -> playing -> done
        'mulligan_order': mulligan_order,  # sequential order
        'mulligan_current': 0,  # index into mulligan_order
        'mulligan_status': {},  # player_name -> 'pending' | 'kept'
        'mulligan_count': {},   # player_name -> int
        'priority_queue': [],   # list of player names who need to respond
        'pending_triggers': [], # triggers waiting for resolution
        'last_action': None,
        'turn_actions': [],     # actions taken this turn
    }

    for p in engine.players:
        meta['mulligan_status'][p.name] = 'pending'
        meta['mulligan_count'][p.name] = 0

    _save_game(game_id, engine, meta)

    result = {
        'game_id': game_id,
        'seed': seed,
        'phase': 'mulligan',
        'players': [],
    }
    for p in engine.players:
        cmdr = p.command_zone[0]['name'] if p.command_zone else 'none'
        result['players'].append({
            'name': p.name,
            'commander': cmdr,
            'hand_size': len(p.hand),
        })

    return result


# ==================== Hand & Mulligan ====================

def cmd_hand(game_id, player_name):
    """Show a player's hand with oracle text."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    cards = []
    for c in sorted(player.hand, key=lambda x: (x.get('cmc', 0), x['name'])):
        is_land = 'Land' in c.get('type_line', '')
        castable = can_cast(player, c) if not is_land else player.land_drops_remaining > 0
        cards.append({
            'name': c['name'],
            'mana_cost': c.get('mana_cost', ''),
            'type_line': c.get('type_line', ''),
            'oracle_text': c.get('oracle_text', '')[:120],
            'power': c.get('power', 0),
            'toughness': c.get('toughness', 0),
            'castable': castable,
        })

    mana = get_available_mana(player)
    lands = sum(1 for c in player.hand if 'Land' in c.get('type_line', ''))

    return {
        'hand': cards,
        'hand_size': len(cards),
        'lands_in_hand': lands,
        'mana_available': mana.get('total', 0),
        'land_drops': player.land_drops_remaining,
        'life': player.life,
        'commander_in_cz': bool(player.command_zone),
        'commander_tax': player.commander_tax,
    }


def cmd_mulligan(game_id, player_name):
    """Mulligan: shuffle hand back, draw 7 new."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)
    # Use canonical name from engine
    pname = player.name

    meta['mulligan_count'][pname] = meta['mulligan_count'].get(pname, 0) + 1
    count = meta['mulligan_count'][pname]

    player.library.extend(player.hand)
    player.hand.clear()
    engine.rng.shuffle(player.library)
    player.draw(7)

    _save_game(game_id, engine, meta)

    # Commander: first mulligan is free
    bottom = max(0, count - 1)

    hand = cmd_hand(game_id, player_name)
    return {
        'mulligan_number': count,
        'bottom_required': bottom,
        'free': count == 1,
        'hand': hand['hand'],
        'message': f"Mulligan #{count}." + (" FREE — keep all 7!" if count == 1 else f" Bottom {bottom} when you keep."),
    }


def cmd_keep(game_id, player_name, bottom_cards=None):
    """Keep hand, bottom N cards (N = mulligan_count - 1)."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)
    pname = player.name  # canonical name

    count = meta['mulligan_count'].get(pname, 0)
    bottom = max(0, count - 1)

    if bottom > 0:
        if bottom_cards:
            for name in bottom_cards[:bottom]:
                card = _find_card(player.hand, name)
                if card:
                    player.hand.remove(card)
                    player.library.insert(0, card)
        else:
            for _ in range(bottom):
                if player.hand:
                    worst = max(player.hand, key=lambda c: c.get('cmc', 0))
                    player.hand.remove(worst)
                    player.library.insert(0, worst)

    meta['mulligan_status'][pname] = 'kept'

    # Advance to next player in mulligan order
    meta['mulligan_current'] = meta.get('mulligan_current', 0) + 1

    # Check if all players have kept
    all_kept = all(s == 'kept' for s in meta['mulligan_status'].values())
    if all_kept:
        meta['phase'] = 'playing'

    _save_game(game_id, engine, meta)

    return {
        'kept': True,
        'hand_size': len(player.hand),
        'bottomed': bottom,
        'all_ready': all_kept,
        'phase': meta['phase'],
    }


# ==================== Turn Actions ====================

def cmd_begin(game_id, player_name):
    """Begin turn: untap, upkeep triggers, draw. ONLY the active player can call this."""
    engine, meta = _load_game(game_id)

    if meta['phase'] != 'playing':
        return {'error': f"Game in {meta['phase']} phase, not playing"}

    # MUST check active player BEFORE mutating state
    player = _find(engine, player_name)
    active = engine.active_player
    if active.name != player.name:
        return {'error': f"It's {active.name}'s turn, not {player.name}'s. Use 'wait' to block until your turn."}

    # Also block if priority queue has pending responses
    pq = meta.get('priority_queue', [])
    if pq:
        return {'error': f"Priority pending for: {', '.join(pq)}. Cannot begin turn."}

    drew = engine.begin_turn()

    # Detect upkeep triggers
    upkeep_triggers = []
    for tp, perm, oracle in detect_triggers(engine.players, 'upkeep', {}):
        upkeep_triggers.append({
            'player': tp.name,
            'permanent': perm.name,
            'type': 'upkeep',
            'oracle': oracle[:120],
        })

    # Auto-resolve rad counters for the active player
    # Rad: at beginning of precombat main phase, mill N (where N = rad counters),
    # lose 1 life per nonland card milled, then remove all rad counters
    rad_result = None
    rad_count = player.counters.get('rad', 0)
    if rad_count > 0:
        milled = []
        life_lost = 0
        for _ in range(rad_count):
            if not player.library:
                break
            card = player.library.pop(0)
            player.graveyard.append(card)
            is_land = 'Land' in card.get('type_line', '')
            milled.append({'name': card['name'], 'is_land': is_land})
            if not is_land:
                life_lost += 1

        player.life -= life_lost
        player.counters['rad'] = 0
        if player.counters['rad'] == 0:
            del player.counters['rad']

        nonland_milled = sum(1 for c in milled if not c['is_land'])
        mill_names = ', '.join(c['name'] for c in milled)
        engine.events.append(f"☢ {player.name} resolves {rad_count} rad: mills {mill_names}, loses {life_lost} life (→ {player.life})")

        # Check for Mothman's mill trigger: "Whenever one or more nonland cards are milled,
        # put a +1/+1 counter on each of up to X target creatures, where X is nonland cards milled"
        mill_triggers = []
        if nonland_milled > 0:
            for tp in engine.players:
                if tp.life <= 0:
                    continue
                for perm in tp.battlefield:
                    oracle = perm.card.get('oracle_text', '').lower()
                    if 'nonland cards are milled' in oracle and '+1/+1 counter' in oracle:
                        mill_triggers.append({
                            'player': tp.name,
                            'permanent': perm.name,
                            'nonland_count': nonland_milled,
                            'resolve_hint': f'/modify counter_type="+1/+1" amount=1 on up to {nonland_milled} creatures (Mothman mill trigger)',
                        })
                        engine.events.append(f"  ⚡ MILL TRIGGER: {perm.name} — {nonland_milled} nonland(s) milled → up to {nonland_milled} +1/+1 counters")

        rad_result = {
            'rad_counters': rad_count,
            'milled': milled,
            'life_lost': life_lost,
            'life_remaining': player.life,
            'mill_triggers': mill_triggers,
        }

    meta['turn_actions'] = []
    meta['priority_queue'] = []
    _save_game(game_id, engine, meta)

    drew_info = None
    if drew:
        drew_info = {
            'name': drew['name'],
            'mana_cost': drew.get('mana_cost', ''),
            'type_line': drew.get('type_line', ''),
            'oracle_text': drew.get('oracle_text', '')[:100],
        }

    # Include board state and valid actions so agent doesn't need separate calls
    snapshot = engine.get_snapshot(player)
    valid = cmd_valid(game_id, player_name)

    return {
        'turn': engine.turn,
        'player': player.name,
        'drew': drew_info,
        'life': player.life,
        'hand_size': len(player.hand),
        'upkeep_triggers': upkeep_triggers,
        'rad': rad_result,
        'player_counters': player.counters if player.counters else None,
        'state': snapshot,
        'valid_actions': valid.get('actions', []),
    }


def cmd_draw(game_id, player_name, count=1):
    """Draw cards (for spell/ability effects). Agent calls this to resolve draw effects."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    drawn = []
    for _ in range(count):
        if player.library:
            card = player.library.pop(0)
            player.hand.append(card)
            drawn.append({
                'name': card['name'],
                'mana_cost': card.get('mana_cost', ''),
                'type_line': card.get('type_line', ''),
            })
        else:
            player.life = 0
            engine.events.append(f"{player.name} draws from empty library and loses!")
            break

    # Detect draw triggers
    draw_triggers = []
    for tp, perm, oracle in detect_triggers(engine.players, 'draw', {}):
        draw_triggers.append({
            'player': tp.name,
            'permanent': perm.name,
            'oracle': oracle[:120],
        })

    _save_game(game_id, engine, meta)
    engine.events.append(f"{player.name} draws {len(drawn)} card(s)")

    return {
        'drawn': drawn,
        'hand_size': len(player.hand),
        'draw_triggers': draw_triggers,
    }


def cmd_action(game_id, player_name, action):
    """Execute an action. Engine validates everything."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    # Check it's their turn or they have priority
    active = engine.active_player
    pq = meta.get('priority_queue', [])
    has_priority = player.name in pq
    is_active = active.name == player.name

    # Active player can't act while priority queue has pending responses
    if is_active and pq:
        return {'error': f"Waiting for priority responses from: {', '.join(pq)}. They must respond or pass first."}

    if not is_active and not has_priority:
        return {'error': f"It's {active.name}'s turn and you don't have priority"}

    ok, msg, judge = engine.resolve_action(player, action)

    result = {
        'success': ok,
        'message': msg,
        'judge_needed': judge,
    }

    if ok:
        meta['turn_actions'].append(f"{player.name}: {msg}")
        meta['last_action'] = f"{player.name}: {msg}"

        # Check triggers based on action type
        triggers = []
        action_lower = action.lower()

        # Build event_data for trigger filtering
        # Find the card involved in the action
        event_card = None
        if 'cast' in action_lower:
            card_name = action_lower.replace('cast ', '').replace('commander', '').strip()
            # Find the card on battlefield (just cast) or in command zone
            for pp in engine.players:
                for perm in pp.battlefield:
                    if card_name and card_name in perm.name.lower():
                        event_card = perm.card
                        break
        if 'play' in action_lower:
            land_name = action_lower.replace('play ', '').strip()
            for perm in player.battlefield:
                if land_name in perm.name.lower():
                    event_card = perm.card
                    break

        event_data = {'card': event_card, 'player': player} if event_card else {}

        # For attacks, pass the attacker info
        if 'attack' in action_lower:
            # Extract first attacker name for self-referential trigger filtering
            attacker_name = ''
            if hasattr(engine, 'pending_combat') and engine.pending_combat:
                attacks = engine.pending_combat.get('attacks', [])
                if attacks:
                    attacker_name = attacks[0]['creature']
            event_data['attacker'] = attacker_name

        # Determine which trigger types to check
        trigger_checks = []
        if 'play' in action_lower:
            trigger_checks.append('landfall')
        if 'cast' in action_lower:
            trigger_checks.append('etb')
            trigger_checks.append('cast')
        if 'attack' in action_lower:
            trigger_checks.append('attack')
            trigger_checks.append('damage')
        if 'activate' in action_lower:
            trigger_checks.append('ltb')

        for trigger_type in trigger_checks:
            for tp, perm, oracle in detect_triggers(engine.players, trigger_type, event_data):
                hint = _trigger_hint(oracle, tp.name, perm.name)
                triggers.append({
                    'player': tp.name,
                    'permanent': perm.name,
                    'type': trigger_type,
                    'oracle': oracle[:200],
                    'resolve_hint': hint,
                })

        if triggers:
            engine.events.append(f"  ⚡ TRIGGERS: {', '.join(t['permanent'] + '(' + t['type'] + ')' for t in triggers)}")

        result['triggers'] = triggers

        # Set up priority for opponents if spell was cast or attack declared
        # Skip priority for land plays — no one responds to land drops
        if ('cast' in action.lower() or 'attack' in action.lower()) and ok and 'play' not in action.lower():
            opponents_with_responses = []
            for opp in engine.players:
                if opp is player or opp.life <= 0:
                    continue
                if engine.has_instant_speed(opp):
                    opponents_with_responses.append(opp.name)

            # For attacks, ALL defenders get priority to declare blockers
            if 'attack' in action.lower():
                for opp in engine.players:
                    if opp is player or opp.life <= 0:
                        continue
                    # Anyone with creatures can block
                    has_blockers = any(p.is_creature() and not p.tapped for p in opp.battlefield)
                    if has_blockers and opp.name not in opponents_with_responses:
                        opponents_with_responses.append(opp.name)
                meta['combat_pending'] = True
                result['combat'] = 'Attackers declared. Defenders may block or respond.'

            meta['priority_queue'] = opponents_with_responses
            result['priority_to'] = opponents_with_responses

        # Check eliminations
        elims = []
        for p in engine.players:
            if p.life <= 0 and p.life > -999:
                elims.append(p.name)
                p.life = -999
        result['eliminations'] = elims

        # Check game over
        alive = [p for p in engine.players if p.life > 0]
        if len(alive) <= 1:
            engine.game_over = True
            meta['phase'] = 'done'
            result['game_over'] = True
            result['winner'] = alive[0].name if alive else 'draw'

    _save_game(game_id, engine, meta)
    return result


def cmd_respond(game_id, player_name, action):
    """Respond during an opponent's turn — instant-speed spells, abilities, or block declarations."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)
    pname = player.name

    if pname not in meta.get('priority_queue', []):
        return {'error': f"{pname} doesn't have priority"}

    action_lower = action.lower().strip()

    # Pass priority
    if action_lower == 'pass':
        meta['priority_queue'].remove(pname)

        # If all defenders have passed and combat is pending, resolve it
        combat_result = None
        if not meta['priority_queue'] and meta.get('combat_pending'):
            if hasattr(engine, 'pending_combat') and engine.pending_combat:
                ok, msg, killed = engine.resolve_combat()
                combat_result = {'combat_resolved': True, 'message': msg, 'killed': killed}
            meta['combat_pending'] = False
            meta['blocks'] = []

        _save_game(game_id, engine, meta)
        result = {'passed': True, 'priority_remaining': meta['priority_queue']}
        if combat_result:
            result['combat'] = combat_result
        return result

    # Block declaration: "block <attacker> with <blocker>"
    if action_lower.startswith('block '):
        # Parse: "block CreatureName with MyCreature"
        parts = action[6:].split(' with ')
        if len(parts) == 2:
            attacker_name = parts[0].strip()
            blocker_name = parts[1].strip()

            # Find the attacker on any opponent's battlefield
            attacker = None
            for opp in engine.players:
                for perm in opp.battlefield:
                    if perm.is_creature() and perm.tapped and blocker_name.lower() != perm.name.lower():
                        if attacker_name.lower() in perm.name.lower():
                            attacker = perm
                            break

            # Find the blocker on this player's battlefield
            blocker = None
            for perm in player.battlefield:
                if perm.is_creature() and not perm.tapped and blocker_name.lower() in perm.name.lower():
                    blocker = perm
                    break

            if not blocker:
                return {'error': f"No untapped creature '{blocker_name}' on your battlefield"}

            # Record block in both meta and engine's pending_combat
            if 'blocks' not in meta:
                meta['blocks'] = []
            block_record = {
                'blocker': blocker.name,
                'blocker_owner': pname,
                'blocker_power': blocker.power,
                'blocker_toughness': blocker.toughness,
                'attacker': attacker_name,
            }
            meta['blocks'].append(block_record)

            # Also add to engine's pending_combat
            if hasattr(engine, 'pending_combat') and engine.pending_combat:
                engine.pending_combat['blocks'].append(block_record)

            engine.events.append(f"  ↪ {pname} blocks {attacker_name} with {blocker.name}")

            meta['priority_queue'].remove(pname)

            # If all defenders have passed/blocked, resolve combat
            combat_result = None
            if not meta['priority_queue'] and meta.get('combat_pending'):
                ok, msg, killed = engine.resolve_combat()
                meta['combat_pending'] = False
                meta['blocks'] = []
                combat_result = {'combat_resolved': True, 'message': msg, 'killed': killed}

            _save_game(game_id, engine, meta)
            result = {
                'blocked': True,
                'message': f"Blocking {attacker_name} with {blocker.name}",
                'priority_remaining': meta['priority_queue'],
            }
            if combat_result:
                result['combat'] = combat_result
            return result

        return {'error': 'Block format: "block <attacker> with <your creature>"'}

    # Instant-speed spell or ability
    result = cmd_action(game_id, player_name, action)
    if result.get('success'):
        # Reload meta since cmd_action saved
        _, meta = _load_game(game_id)
        if pname in meta.get('priority_queue', []):
            meta['priority_queue'].remove(pname)
            _save_game(game_id, engine, meta)

    return result


def cmd_valid(game_id, player_name):
    """Get valid actions for a player."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    actions = []

    for c in player.hand:
        if 'Land' in c.get('type_line', '') and player.land_drops_remaining > 0:
            actions.append(f"play {c['name']}")
    for c in player.hand:
        if 'Land' not in c.get('type_line', '') and can_cast(player, c):
            actions.append(f"cast {c['name']}")
    if player.command_zone:
        cmdr = player.command_zone[0]
        if can_cast(player, cmdr, commander_tax=player.commander_tax):
            actions.append("cast commander")

    # Activated abilities on untapped permanents
    for perm in player.battlefield:
        if perm.tapped:
            continue
        oracle = perm.card.get('oracle_text', '')
        # Find {T}: abilities that aren't pure mana
        if '{T}:' in oracle or '{T},':
            parts = oracle.split('{T}')
            for part in parts[1:]:
                ability = part.lstrip(':').lstrip(',').strip().split('\n')[0].strip()
                # Skip pure mana abilities
                if ability.startswith('Add {') or ability.startswith('Add one mana'):
                    continue
                if ability and len(ability) > 5:
                    actions.append(f"activate {perm.name}")
                    break
        # Sacrifice abilities
        if 'sacrifice' in oracle.lower() and '{T}' not in oracle:
            if 'sacrifice ' + perm.card.get('name', '').lower() in oracle.lower() or 'sacrifice this' in oracle.lower():
                actions.append(f"activate {perm.name}")

    # Equipment — show equip options
    equipments = [p for p in player.battlefield if 'Equipment' in p.card.get('type_line', '')]
    equip_targets = [p for p in player.battlefield if p.is_creature()]
    if equipments and equip_targets:
        for eq in equipments:
            for cr in equip_targets:
                actions.append(f"equip {eq.name} -> {cr.name}")

    creatures = [p for p in player.battlefield if p.is_creature() and not p.tapped and not p.summoning_sick]
    if creatures:
        alive_opps = [opp for opp in engine.players if opp is not player and opp.life > 0]
        for opp in alive_opps:
            actions.append(f"attack all -> {opp.name}")
        # Also show individual creature attacks if multiple creatures
        if len(creatures) >= 2 and len(alive_opps) >= 2:
            for c in creatures:
                for opp in alive_opps:
                    actions.append(f"attack {c.name} -> {opp.name}")

    actions.append("pass")

    return {'actions': actions, 'phase': engine.phase, 'turn': engine.turn}


def cmd_state(game_id, player_name):
    """Get board state from player's perspective."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)
    snapshot = engine.get_snapshot(player)
    return {
        'state': snapshot,
        'turn': engine.turn,
        'phase': meta.get('phase', 'unknown'),
        'active_player': engine.active_player.name,
        'priority_queue': meta.get('priority_queue', []),
    }


def cmd_end(game_id, player_name):
    """End turn. Auto-discard to 7. ONLY active player can end."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    if engine.active_player.name != player.name:
        return {'error': f"It's {engine.active_player.name}'s turn, not {player.name}'s. Cannot end."}

    pq = meta.get('priority_queue', [])
    if pq:
        return {'error': f"Priority pending for: {', '.join(pq)}. Cannot end turn yet."}

    discarded = []
    while len(player.hand) > 7:
        worst = max(player.hand, key=lambda c: c.get('cmc', 0))
        player.hand.remove(worst)
        player.graveyard.append(worst)
        discarded.append(worst['name'])

    meta['priority_queue'] = []
    engine.advance_turn()

    _save_game(game_id, engine, meta)

    return {
        'discarded': discarded,
        'next_player': engine.active_player.name,
        'turn': engine.turn,
        'game_over': engine.game_over,
    }


def cmd_damage(game_id, player_name, target_player, amount):
    """Deal damage to a player. Active player or priority holder can call this."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)
    target = _find(engine, target_player)

    target.life -= int(amount)
    engine.events.append(f"{player.name} deals {amount} damage to {target.name} (life: {target.life})")

    result = {'target': target.name, 'damage': int(amount), 'life_remaining': target.life}

    if target.life <= 0 and target.life > -999:
        target.life = -999
        result['eliminated'] = True
        engine.events.append(f"{target.name} eliminated!")

    alive = [p for p in engine.players if p.life > 0]
    if len(alive) <= 1:
        engine.game_over = True
        meta['phase'] = 'done'
        result['game_over'] = True
        result['winner'] = alive[0].name if alive else 'draw'

    _save_game(game_id, engine, meta)
    return result


def cmd_destroy(game_id, player_name, target_player, permanent_name, exile=False):
    """Remove a permanent from the battlefield.

    exile=False: destroy (goes to graveyard, triggers "dies" / "when put into graveyard")
    exile=True: exile (goes to exile zone, does NOT trigger "dies")

    Commanders always go to command zone (owner's choice per rules).
    """
    engine, meta = _load_game(game_id)
    target = _find(engine, target_player)

    perm = None
    for p in target.battlefield:
        if permanent_name.lower() in p.name.lower():
            perm = p
            break

    if not perm:
        return {'error': f"'{permanent_name}' not found on {target.name}'s battlefield"}

    target.battlefield.remove(perm)

    # Determine destination
    destination = 'exile' if exile else 'graveyard'
    action_word = 'exiled' if exile else 'destroyed'

    if perm.card.get('is_commander'):
        # Commander always goes to command zone (owner's choice, we default to CZ)
        target.command_zone.append(perm.card)
        engine.events.append(f"{perm.name} {action_word} → command zone")
        destination = 'command_zone'
    elif exile:
        target.exile.append(perm.card)
        engine.events.append(f"{perm.name} exiled")
    else:
        target.graveyard.append(perm.card)
        engine.events.append(f"{perm.name} destroyed → graveyard")

    # Detect death/LTB triggers (only on destroy, not exile)
    triggers = []
    if not exile:
        for tp, trig_perm, oracle in detect_triggers(engine.players, 'ltb', {}):
            hint = _trigger_hint(oracle, tp.name, trig_perm.name)
            triggers.append({
                'player': tp.name,
                'permanent': trig_perm.name,
                'type': 'dies',
                'oracle': oracle[:200],
                'resolve_hint': hint,
            })
        if triggers:
            engine.events.append(f"  ⚡ DEATH TRIGGERS: {', '.join(t['permanent'] + '(' + t['type'] + ')' for t in triggers)}")

    _save_game(game_id, engine, meta)
    return {
        'removed': perm.name,
        'owner': target.name,
        'destination': destination,
        'exile': exile,
        'triggers': triggers,
    }


def cmd_modify(game_id, player_name, target_player, permanent_name, counter_type='+1/+1', amount=1):
    """Add or remove counters on a permanent OR player.

    counter_type: '+1/+1', '-1/-1', 'loyalty', 'rad', 'lore', 'charge', 'poison', 'experience', etc.
    amount: positive to add, negative to remove.
    permanent_name: name of permanent, OR empty/"" to target the player directly (for rad, poison, experience)
    """
    engine, meta = _load_game(game_id)
    target = _find(engine, target_player)

    # Player-level counters (rad, poison, experience)
    if not permanent_name or permanent_name.lower() in ('player', '', 'self'):
        old_count = target.counters.get(counter_type, 0)
        new_count = max(0, old_count + int(amount))
        if new_count == 0 and counter_type in target.counters:
            del target.counters[counter_type]
        elif new_count > 0:
            target.counters[counter_type] = new_count

        action_word = "gains" if amount > 0 else "loses"
        engine.events.append(f"{target.name} {action_word} {abs(amount)} {counter_type} counter(s) ({new_count} total)")

        _save_game(game_id, engine, meta)
        return {
            'player': target.name,
            'counter_type': counter_type,
            'old_count': old_count,
            'new_count': new_count,
            'all_player_counters': target.counters,
        }

    # Permanent-level counters
    perm = None
    for p in target.battlefield:
        if permanent_name.lower() in p.name.lower():
            perm = p
            break

    if not perm:
        return {'error': f"'{permanent_name}' not found on {target.name}'s battlefield"}

    old_count = perm.counters.get(counter_type, 0)
    new_count = max(0, old_count + int(amount))
    if new_count == 0 and counter_type in perm.counters:
        del perm.counters[counter_type]
    elif new_count > 0:
        perm.counters[counter_type] = new_count

    # Check if creature died from -1/-1 counters
    result = {
        'permanent': perm.name,
        'owner': target.name,
        'counter_type': counter_type,
        'old_count': old_count,
        'new_count': new_count,
    }

    if perm.is_creature() and perm.toughness <= 0:
        target.battlefield.remove(perm)
        if perm.card.get('is_commander'):
            target.command_zone.append(perm.card)
            engine.events.append(f"{perm.name} dies from -1/-1 counters → command zone")
        else:
            target.graveyard.append(perm.card)
            engine.events.append(f"{perm.name} dies from -1/-1 counters → graveyard")
        result['died'] = True
    else:
        if perm.is_creature():
            result['power'] = perm.power
            result['toughness'] = perm.toughness

    action_word = "adds" if amount > 0 else "removes"
    engine.events.append(f"{player_name} {action_word} {abs(amount)} {counter_type} counter(s) on {perm.name} ({new_count} total)")

    _save_game(game_id, engine, meta)
    return result


def cmd_keyword(game_id, player_name, target_player, permanent_name, keyword, remove=False):
    """Grant or remove a keyword on a permanent.

    Keywords: trample, flying, hexproof, indestructible, deathtouch, lifelink,
              menace, vigilance, reach, haste, first strike, double strike, finality, ward
    """
    engine, meta = _load_game(game_id)
    target = _find(engine, target_player)

    perm = None
    for p in target.battlefield:
        if permanent_name.lower() in p.name.lower():
            perm = p
            break

    if not perm:
        return {'error': f"'{permanent_name}' not found on {target.name}'s battlefield"}

    kw = keyword.lower().strip()
    if remove:
        perm.granted_keywords.discard(kw)
        engine.events.append(f"{perm.name} loses {kw}")
    else:
        perm.granted_keywords.add(kw)
        engine.events.append(f"{perm.name} gains {kw}")

    _save_game(game_id, engine, meta)
    return {
        'permanent': perm.name,
        'keyword': kw,
        'action': 'removed' if remove else 'granted',
        'all_keywords': sorted(perm.all_keywords),
    }


def cmd_proliferate(game_id, player_name, targets):
    """Proliferate: for each target (permanent or player), add one counter of a type already there.

    targets: list of dicts, each with:
      - {'player': 'Name', 'permanent': 'CardName', 'counter_type': '+1/+1'}
      - {'player': 'Name', 'counter_type': 'poison'}  (for player counters — future)
    """
    engine, meta = _load_game(game_id)
    results = []

    for t in targets:
        target_player = t.get('player', player_name)
        perm_name = t.get('permanent', '')
        counter_type = t.get('counter_type', '+1/+1')

        if not perm_name:
            # Player counter (poison, rad, etc.) — skip for now
            results.append({'skipped': True, 'reason': 'player counters not yet supported'})
            continue

        target = _find(engine, target_player)
        perm = None
        for p in target.battlefield:
            if perm_name.lower() in p.name.lower():
                perm = p
                break

        if not perm:
            results.append({'error': f"'{perm_name}' not found"})
            continue

        # Can only proliferate a counter type already present
        if counter_type not in perm.counters or perm.counters[counter_type] <= 0:
            results.append({'skipped': True, 'permanent': perm.name, 'reason': f'no {counter_type} counters to proliferate'})
            continue

        perm.counters[counter_type] += 1
        entry = {
            'permanent': perm.name,
            'counter_type': counter_type,
            'new_count': perm.counters[counter_type],
        }
        if perm.is_creature():
            entry['power'] = perm.power
            entry['toughness'] = perm.toughness
        results.append(entry)

    counter_summary = ", ".join(
        f"{r['permanent']}({r['counter_type']}→{r['new_count']})"
        for r in results if 'permanent' in r and 'new_count' in r
    )
    engine.events.append(f"{player_name} proliferates: {counter_summary}" if counter_summary else f"{player_name} proliferates (no targets)")

    _save_game(game_id, engine, meta)
    return {'proliferated': results}


def cmd_equip(game_id, player_name, equipment_name, target_creature):
    """Equip an equipment to a creature. Grants keywords from the equipment's oracle text."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    equip = None
    creature = None
    for perm in player.battlefield:
        if equipment_name.lower() in perm.name.lower() and 'Equipment' in perm.card.get('type_line', ''):
            equip = perm
        if target_creature.lower() in perm.name.lower() and perm.is_creature():
            creature = perm

    if not equip:
        return {'error': f"Equipment '{equipment_name}' not found on your battlefield"}
    if not creature:
        return {'error': f"Creature '{target_creature}' not found on your battlefield"}

    # Parse keywords from oracle text
    oracle = equip.card.get('oracle_text', '').lower()
    granted = []
    for kw in ['hexproof', 'shroud', 'haste', 'trample', 'flying', 'vigilance',
               'lifelink', 'deathtouch', 'first strike', 'double strike', 'menace',
               'indestructible', 'reach', 'ward']:
        if kw in oracle:
            creature.granted_keywords.add(kw)
            granted.append(kw)

    # Parse power/toughness boost
    import re
    pt_match = re.search(r'gets? \+(\d+)/\+(\d+)', oracle)
    if pt_match:
        power_boost = int(pt_match.group(1))
        creature.counters['equipment_power'] = creature.counters.get('equipment_power', 0) + power_boost
        granted.append(f"+{pt_match.group(1)}/+{pt_match.group(2)}")

    # Track equip on the permanent
    equip.counters['equipped_to'] = id(creature)

    engine.events.append(f"{player.name} equips {equip.name} to {creature.name} ({', '.join(granted)})")
    _save_game(game_id, engine, meta)
    return {
        'equipment': equip.name,
        'creature': creature.name,
        'granted': granted,
        'creature_keywords': sorted(creature.all_keywords),
    }


def cmd_scry(game_id, player_name, count=1, bottom=None):
    """Scry N: look at top N cards, put any on bottom in specified order.

    bottom: list of card names to put on bottom (rest stay on top in current order)
    """
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    n = min(int(count), len(player.library))
    top_cards = player.library[:n]

    card_info = [{'name': c['name'], 'type_line': c.get('type_line', ''), 'mana_cost': c.get('mana_cost', '')} for c in top_cards]

    if bottom is None:
        # Just reveal the top N without rearranging
        _save_game(game_id, engine, meta)
        return {'top_cards': card_info, 'count': n, 'message': 'Specify bottom: [card names] to put cards on bottom'}

    # Move specified cards to bottom
    bottomed = []
    kept_on_top = []
    for card in top_cards:
        if any(b.lower() in card['name'].lower() for b in (bottom or [])):
            bottomed.append(card)
        else:
            kept_on_top.append(card)

    # Rebuild library: kept on top + rest of library + bottomed
    player.library = kept_on_top + player.library[n:] + bottomed

    engine.events.append(f"{player.name} scries {n}: {len(bottomed)} to bottom")
    _save_game(game_id, engine, meta)
    return {
        'kept_on_top': [c['name'] for c in kept_on_top],
        'bottomed': [c['name'] for c in bottomed],
    }


def cmd_mill(game_id, player_name, count=1):
    """Mill N cards: move top N from library to graveyard."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    milled = []
    for _ in range(int(count)):
        if not player.library:
            break
        card = player.library.pop(0)
        player.graveyard.append(card)
        milled.append({'name': card['name'], 'type_line': card.get('type_line', '')})

    nonland_milled = sum(1 for c in milled if 'Land' not in c.get('type_line', ''))
    engine.events.append(f"{player.name} mills {len(milled)}: {', '.join(c['name'] for c in milled)}")

    # Check for Mothman-style mill triggers
    mill_triggers = []
    if nonland_milled > 0:
        for tp in engine.players:
            if tp.life <= 0:
                continue
            for perm in tp.battlefield:
                oracle = perm.card.get('oracle_text', '').lower()
                if 'nonland cards are milled' in oracle and '+1/+1 counter' in oracle:
                    mill_triggers.append({
                        'player': tp.name,
                        'permanent': perm.name,
                        'nonland_count': nonland_milled,
                        'resolve_hint': f'/modify counter_type="+1/+1" amount=1 on up to {nonland_milled} creatures',
                    })
                    engine.events.append(f"  ⚡ MILL TRIGGER: {perm.name} — {nonland_milled} nonland(s) milled")

    _save_game(game_id, engine, meta)
    return {'milled': milled, 'library_size': len(player.library), 'mill_triggers': mill_triggers}


def cmd_search(game_id, player_name, card_name, destination='battlefield', tapped=True):
    """Search a player's library for a card and put it somewhere.

    For tutor effects (Sakura-Tribe Elder, Cultivate, etc.)
    destination: 'battlefield', 'hand', 'graveyard', 'top' (top of library)
    tapped: whether the card enters tapped (for lands)
    """
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    # Find card in library
    found = None
    for i, card in enumerate(player.library):
        if card_name.lower() in card['name'].lower():
            found = i
            break

    if found is None:
        # List available matches for the search
        matches = [c['name'] for c in player.library if any(
            t in c.get('type_line', '').lower() for t in card_name.lower().split()
        )][:10]
        return {'error': f"'{card_name}' not in library", 'similar': matches}

    card = player.library.pop(found)

    if destination == 'battlefield':
        from game_simulator import Permanent
        perm = Permanent(card=card, tapped=bool(tapped))
        player.battlefield.append(perm)
        engine.events.append(f"{player.name} searches library → {card['name']} to battlefield{'(tapped)' if tapped else ''}")
    elif destination == 'hand':
        player.hand.append(card)
        engine.events.append(f"{player.name} searches library → {card['name']} to hand")
    elif destination == 'graveyard':
        player.graveyard.append(card)
        engine.events.append(f"{player.name} searches library → {card['name']} to graveyard")
    elif destination == 'top':
        player.library.insert(0, card)
        engine.events.append(f"{player.name} searches library → {card['name']} to top of library")
    else:
        return {'error': f"Unknown destination: {destination}"}

    # Shuffle library after search (MTG rules)
    import random
    random.shuffle(player.library)

    _save_game(game_id, engine, meta)
    return {
        'found': card['name'],
        'destination': destination,
        'tapped': tapped if destination == 'battlefield' else None,
        'library_size': len(player.library),
    }


def cmd_resolve_judge(game_id, ruling):
    """Judge resolves a pending call. Clears JUDGE from priority and resumes the game.

    ruling: text explanation of the ruling
    """
    engine, meta = _load_game(game_id)

    # Clear JUDGE from priority
    pq = meta.get('priority_queue', [])
    if 'JUDGE' in pq:
        pq.remove('JUDGE')
    meta['priority_queue'] = pq

    # Log the ruling
    engine.events.append(f"⚖️ JUDGE RULING: {ruling}")

    if 'judge_calls' not in meta:
        meta['judge_calls'] = []

    _save_game(game_id, engine, meta)
    return {
        'resolved': True,
        'ruling': ruling,
        'priority_queue': pq,
    }


def cmd_move(game_id, player_name, card_name, from_zone, to_zone):
    """Move a card between zones. For judge/effect resolution.

    Zones: hand, battlefield, graveyard, exile, command_zone, library
    """
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    zone_map = {
        'hand': player.hand,
        'graveyard': player.graveyard,
        'exile': player.exile,
        'command_zone': player.command_zone,
        'library': player.library,
    }

    triggers_ltb = []
    # Find and remove from source zone
    if from_zone == 'battlefield':
        found = None
        for perm in player.battlefield:
            if card_name.lower() in perm.name.lower():
                found = perm
                break
        if not found:
            return {'error': f"'{card_name}' not on battlefield"}
        player.battlefield.remove(found)
        card = found.card
        # LTB triggers when leaving battlefield
        for tp, trig_perm, oracle in detect_triggers(engine.players, 'ltb', {}):
            hint = _trigger_hint(oracle, tp.name, trig_perm.name)
            triggers_ltb.append({
                'player': tp.name,
                'permanent': trig_perm.name,
                'type': 'ltb',
                'oracle': oracle[:200],
                'resolve_hint': hint,
            })
    elif from_zone in zone_map:
        source = zone_map[from_zone]
        found = None
        for i, c in enumerate(source):
            if card_name.lower() in c['name'].lower():
                found = i
                break
        if found is None:
            return {'error': f"'{card_name}' not in {from_zone}"}
        card = source.pop(found)
    else:
        return {'error': f"Unknown zone: {from_zone}"}

    # Add to destination
    triggers = []
    if to_zone == 'battlefield':
        from game_simulator import Permanent
        perm = Permanent(card=card)
        if 'Creature' in card.get('type_line', ''):
            perm.summoning_sick = True
        player.battlefield.append(perm)
        # Entering battlefield triggers ETB
        for tp, trig_perm, oracle in detect_triggers(engine.players, 'etb', {}):
            hint = _trigger_hint(oracle, tp.name, trig_perm.name)
            triggers.append({
                'player': tp.name,
                'permanent': trig_perm.name,
                'type': 'etb',
                'oracle': oracle[:200],
                'resolve_hint': hint,
            })
        if triggers:
            engine.events.append(f"  ⚡ ETB TRIGGERS: {', '.join(t['permanent'] for t in triggers)}")
    elif to_zone in zone_map:
        zone_map[to_zone].append(card)
    else:
        return {'error': f"Unknown zone: {to_zone}"}

    all_triggers = triggers_ltb + triggers
    if all_triggers:
        engine.events.append(f"  ⚡ TRIGGERS: {', '.join(t['permanent'] + '(' + t['type'] + ')' for t in all_triggers)}")

    engine.events.append(f"{player.name} moves {card['name']} from {from_zone} → {to_zone}")
    _save_game(game_id, engine, meta)
    return {'moved': card['name'], 'from': from_zone, 'to': to_zone, 'triggers': all_triggers}


def cmd_judge(game_id, player_name, question):
    """Any player can call judge — flags a rules question or suspected illegal play."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

    if 'judge_calls' not in meta:
        meta['judge_calls'] = []

    meta['judge_calls'].append({
        'player': player.name,
        'question': question,
        'turn': engine.turn,
        'phase': engine.phase,
    })

    # Pause game until judge resolves
    meta['priority_queue'] = ['JUDGE']

    _save_game(game_id, engine, meta)

    return {
        'judge_called': True,
        'player': player.name,
        'question': question,
        'message': f"JUDGE CALLED by {player.name}: {question}. Game paused until resolved.",
    }


def cmd_wait(game_id, player_name, timeout=300):
    """Block until it's this player's turn or they have priority.

    Uses file locking to ensure only one agent acts at a time.
    When released, the player is guaranteed to be the active player or have priority.
    """
    import time
    start = time.time()

    while time.time() - start < timeout:
        # Acquire exclusive lock to check and claim
        lock_path = GAMES_DIR / f"{game_id}.lock"
        with open(lock_path, 'w') as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                engine, meta = _load_game(game_id)
                if engine is None:
                    return {'error': 'Game not found'}

                player = _find(engine, player_name)
                pname = player.name

                # Game over?
                if meta.get('phase') == 'done' or engine.game_over:
                    return {'status': 'game_over', 'winner': next((p.name for p in engine.players if p.life > 0), 'draw')}

                # Mulligan phase?
                if meta.get('phase') == 'mulligan':
                    if meta['mulligan_status'].get(pname) == 'pending':
                        hand = cmd_hand(game_id, player_name)
                        return {'status': 'mulligan', 'message': 'Decide: mulligan or keep', 'hand': hand}
                    else:
                        pass  # Already kept, wait for others

                # Playing phase — check if it's our turn
                elif meta.get('phase') == 'playing':
                    active = engine.active_player
                    pq = meta.get('priority_queue', [])

                    if active.name == pname and not pq:
                        # It's our turn and no priority pending
                        return {
                            'status': 'your_turn',
                            'turn': engine.turn,
                            'phase': engine.phase,
                            'message': f"It's your turn (T{engine.turn}). Use begin, action, end.",
                        }

                    if pname in pq:
                        # We have priority to respond
                        return {
                            'status': 'priority',
                            'turn': engine.turn,
                            'message': f"You have priority. Respond or pass.",
                            'last_action': meta.get('last_action', ''),
                        }
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

        # Not our turn, sleep and retry
        time.sleep(2)

    return {'status': 'timeout', 'message': f'Waited {timeout}s, still not your turn'}


def cmd_priority(game_id):
    """Check who needs to act."""
    engine, meta = _load_game(game_id)
    mulligan_order = meta.get('mulligan_order', [])
    mulligan_current = meta.get('mulligan_current', 0)
    current_mulligan = mulligan_order[mulligan_current] if mulligan_current < len(mulligan_order) else None

    return {
        'active_player': engine.active_player.name,
        'turn': engine.turn,
        'phase': meta.get('phase', 'unknown'),
        'priority_queue': meta.get('priority_queue', []),
        'mulligan_pending': [name for name, status in meta.get('mulligan_status', {}).items() if status == 'pending'],
        'mulligan_order': mulligan_order,
        'mulligan_current': mulligan_current,
        'mulligan_active': current_mulligan,
    }


# ==================== Helpers ====================

def _find(engine, name):
    for p in engine.players:
        if name.lower() in p.name.lower() or p.name.lower() in name.lower():
            return p
    raise ValueError(f"Player '{name}' not found")


def _find_card(hand, name):
    name_lower = name.lower()
    for c in hand:
        if c['name'].lower() == name_lower:
            return c
    for c in hand:
        if name_lower in c['name'].lower():
            return c
    return None


# ==================== CLI ====================

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 game_server.py <command> [args...]")
        print("Commands: create, hand, mulligan, keep, begin, action, valid, state, end, respond, priority")
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == 'create':
            decklists = []
            seed = None
            args = sys.argv[2:]
            i = 0
            while i < len(args):
                if args[i] == '--seed' and i + 1 < len(args):
                    seed = int(args[i + 1])
                    i += 2
                else:
                    decklists.append(args[i])
                    i += 1
            result = cmd_create(decklists, seed=seed)

        elif cmd == 'hand':
            result = cmd_hand(sys.argv[2], sys.argv[3])

        elif cmd == 'mulligan':
            result = cmd_mulligan(sys.argv[2], sys.argv[3])

        elif cmd == 'keep':
            bottom = sys.argv[4:] if len(sys.argv) > 4 else None
            result = cmd_keep(sys.argv[2], sys.argv[3], bottom)

        elif cmd == 'begin':
            result = cmd_begin(sys.argv[2], sys.argv[3])

        elif cmd == 'action':
            result = cmd_action(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))

        elif cmd == 'valid':
            result = cmd_valid(sys.argv[2], sys.argv[3])

        elif cmd == 'state':
            result = cmd_state(sys.argv[2], sys.argv[3])

        elif cmd == 'end':
            result = cmd_end(sys.argv[2], sys.argv[3])

        elif cmd == 'respond':
            result = cmd_respond(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))

        elif cmd == 'damage':
            result = cmd_damage(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])

        elif cmd == 'destroy':
            result = cmd_destroy(sys.argv[2], sys.argv[3], sys.argv[4], ' '.join(sys.argv[5:]))

        elif cmd == 'wait':
            timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 300
            result = cmd_wait(sys.argv[2], sys.argv[3], timeout=timeout)

        elif cmd == 'judge':
            result = cmd_judge(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))

        elif cmd == 'priority':
            result = cmd_priority(sys.argv[2])

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
