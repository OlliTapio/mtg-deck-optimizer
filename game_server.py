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


# ==================== State Persistence ====================

def _save_game(game_id, engine, meta=None):
    """Save engine state to disk."""
    path = GAMES_DIR / f"{game_id}.pkl"
    state = {
        'engine': engine,
        'meta': meta or {},
    }
    with open(path, 'wb') as f:
        pickle.dump(state, f)


def _load_game(game_id):
    """Load engine state from disk."""
    path = GAMES_DIR / f"{game_id}.pkl"
    if not path.exists():
        return None, None
    with open(path, 'rb') as f:
        state = pickle.load(f)
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

    meta = {
        'seed': seed,
        'phase': 'mulligan',  # mulligan -> playing -> done
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
    """Begin turn: untap, draw."""
    engine, meta = _load_game(game_id)

    if meta['phase'] != 'playing':
        return {'error': f"Game in {meta['phase']} phase, not playing"}

    drew = engine.begin_turn()
    player = engine.active_player

    if player.name.lower() not in player_name.lower() and player_name.lower() not in player.name.lower():
        _save_game(game_id, engine, meta)
        return {'error': f"It's {player.name}'s turn, not {player_name}'s"}

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

    return {
        'turn': engine.turn,
        'player': player.name,
        'drew': drew_info,
        'life': player.life,
        'hand_size': len(player.hand),
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

        # Check triggers
        triggers = []
        if 'play' in action.lower():
            for tp, perm, oracle in detect_triggers(engine.players, 'landfall', {}):
                triggers.append({
                    'player': tp.name,
                    'permanent': perm.name,
                    'type': 'landfall',
                    'oracle': oracle[:80],
                })
        if 'cast' in action.lower():
            for tp, perm, oracle in detect_triggers(engine.players, 'etb', {}):
                triggers.append({
                    'player': tp.name,
                    'permanent': perm.name,
                    'type': 'etb',
                    'oracle': oracle[:80],
                })

        result['triggers'] = triggers

        # Set up priority for opponents if spell was cast or attack declared
        if ('cast' in action.lower() or 'attack' in action.lower()) and ok:
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
        _save_game(game_id, engine, meta)
        return {'passed': True, 'priority_remaining': meta['priority_queue']}

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

            # Record the block
            if 'blocks' not in meta:
                meta['blocks'] = []
            meta['blocks'].append({
                'blocker': blocker.name,
                'blocker_owner': pname,
                'attacker': attacker_name,
            })

            engine.events.append(f"  ↪ {pname} blocks {attacker_name} with {blocker.name}")

            meta['priority_queue'].remove(pname)
            _save_game(game_id, engine, meta)
            return {
                'blocked': True,
                'message': f"Blocking {attacker_name} with {blocker.name}",
                'priority_remaining': meta['priority_queue'],
            }

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

    creatures = [p for p in player.battlefield if p.is_creature() and not p.tapped and not p.summoning_sick]
    if creatures:
        for opp in engine.players:
            if opp is not player and opp.life > 0:
                actions.append(f"attack all -> {opp.name}")

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
    """End turn. Auto-discard to 7."""
    engine, meta = _load_game(game_id)
    player = _find(engine, player_name)

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


def cmd_destroy(game_id, player_name, target_player, permanent_name):
    """Move a permanent to its owner's graveyard. For combat kills, removal, etc."""
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
    if perm.card.get('is_commander'):
        target.command_zone.append(perm.card)
        engine.events.append(f"{perm.name} destroyed → command zone")
    else:
        target.graveyard.append(perm.card)
        engine.events.append(f"{perm.name} destroyed → graveyard")

    _save_game(game_id, engine, meta)
    return {'destroyed': perm.name, 'owner': target.name}


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
    """Block until it's this player's turn or they have priority. Returns game state when ready."""
    import time
    start = time.time()

    while time.time() - start < timeout:
        engine, meta = _load_game(game_id)
        if engine is None:
            return {'error': 'Game not found'}

        player = _find(engine, player_name)
        pname = player.name

        # Check if game is over
        if meta.get('phase') == 'done' or engine.game_over:
            return {'status': 'game_over', 'winner': next((p.name for p in engine.players if p.life > 0), 'draw')}

        # Check if still in mulligan phase and this player needs to act
        if meta.get('phase') == 'mulligan':
            if meta['mulligan_status'].get(pname) == 'pending':
                hand = cmd_hand(game_id, player_name)
                return {'status': 'mulligan', 'message': 'Decide: mulligan or keep', 'hand': hand}
            else:
                # Already kept, wait for others
                time.sleep(1)
                continue

        # Check if it's their turn
        active = engine.active_player
        if active.name == pname:
            return {
                'status': 'your_turn',
                'turn': engine.turn,
                'phase': engine.phase,
                'message': f"It's your turn (T{engine.turn}). Use begin, action, end commands.",
            }

        # Check if they have priority to respond
        pq = meta.get('priority_queue', [])
        if pname in pq:
            return {
                'status': 'priority',
                'turn': engine.turn,
                'message': f"You have priority to respond. Use respond command or pass.",
                'last_action': meta.get('last_action', ''),
            }

        # Not our turn, wait
        time.sleep(2)

    return {'status': 'timeout', 'message': f'Waited {timeout}s, still not your turn'}


def cmd_priority(game_id):
    """Check who needs to act."""
    engine, meta = _load_game(game_id)
    return {
        'active_player': engine.active_player.name,
        'turn': engine.turn,
        'phase': meta.get('phase', 'unknown'),
        'priority_queue': meta.get('priority_queue', []),
        'mulligan_pending': [name for name, status in meta.get('mulligan_status', {}).items() if status == 'pending'],
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
