#!/usr/bin/env python3
"""MCP Server for the Commander Game Engine.

Exposes game engine tools that Claude subagents can call directly:
- new_game: create a game with N decks
- get_state: see the board from your perspective
- get_hand: see your hand with oracle text
- play_land: play a land from hand
- cast_spell: cast a spell (engine validates mana)
- cast_commander: cast commander from command zone
- attack: declare attackers
- pass_turn: end your turn
- respond: play instant-speed interaction during opponent's turn

Run: python3 game_mcp_server.py
"""
import json
import sys
import os
import random
from game_orchestrator import GameEngine, card_summary, perm_summary, detect_triggers
from game_simulator import get_available_mana, can_cast, play_land, cast_spell
from auto_pilot import pick_land_to_play, pick_spells_to_cast


# ==================== Game State (global singleton) ====================

_engine = None
_game_id = None


def _get_engine():
    global _engine
    if _engine is None:
        raise RuntimeError("No game in progress. Call new_game first.")
    return _engine


# ==================== Tool Implementations ====================

def new_game(decklists: list, seed: int = None) -> dict:
    """Create a new game with the given decklist paths."""
    global _engine, _game_id
    if seed is None:
        seed = random.randint(1, 99999)
    _engine = GameEngine(decklists, seed=seed)
    _game_id = f"game_{seed}"

    players = []
    for p in _engine.players:
        cmdr = p.command_zone[0]['name'] if p.command_zone else "none"
        players.append({
            "name": p.name,
            "commander": cmdr,
            "hand_size": len(p.hand),
            "life": p.life,
        })

    return {
        "game_id": _game_id,
        "seed": seed,
        "players": players,
        "turn": _engine.turn,
        "active_player": _engine.active_player.name,
    }


def get_state(player_name: str) -> dict:
    """Get the game state from a player's perspective. Shows all boards but only your hand."""
    engine = _get_engine()
    player = _find_player(engine, player_name)
    snapshot = engine.get_snapshot(player)
    return {"state": snapshot, "turn": engine.turn, "phase": engine.phase}


def get_hand(player_name: str) -> dict:
    """Get your hand with full oracle text. Only works for your own hand."""
    engine = _get_engine()
    player = _find_player(engine, player_name)
    cards = []
    for c in sorted(player.hand, key=lambda x: (x.get('cmc', 0), x['name'])):
        castable = can_cast(player, c)
        cards.append({
            "name": c['name'],
            "mana_cost": c.get('mana_cost', ''),
            "cmc": c.get('cmc', 0),
            "type_line": c.get('type_line', ''),
            "oracle_text": c.get('oracle_text', ''),
            "power": c.get('power', 0),
            "toughness": c.get('toughness', 0),
            "castable": castable,
        })

    mana = get_available_mana(player)
    return {
        "hand": cards,
        "hand_size": len(cards),
        "mana_total": mana.get('total', 0),
        "land_drops": player.land_drops_remaining,
        "commander_in_cz": bool(player.command_zone),
        "commander_tax": player.commander_tax,
    }


def begin_turn(player_name: str) -> dict:
    """Begin a turn: untap, draw. Returns the drawn card."""
    engine = _get_engine()
    drew = engine.begin_turn()
    player = engine.active_player

    if player.name != player_name:
        return {"error": f"It's {player.name}'s turn, not {player_name}'s"}

    drew_info = None
    if drew:
        drew_info = {
            "name": drew['name'],
            "mana_cost": drew.get('mana_cost', ''),
            "type_line": drew.get('type_line', ''),
            "oracle_text": drew.get('oracle_text', ''),
        }

    return {
        "turn": engine.turn,
        "drew": drew_info,
        "life": player.life,
        "hand_size": len(player.hand),
    }


def do_action(player_name: str, action: str) -> dict:
    """Execute an action: play <land>, cast <spell>, cast commander, attack all -> <target>, activate <permanent>, pass."""
    engine = _get_engine()
    player = _find_player(engine, player_name)

    ok, msg, judge = engine.resolve_action(player, action)

    # Check for triggers
    triggers = []
    if ok and ('play' in action.lower() or 'cast' in action.lower()):
        event_type = 'landfall' if 'play' in action.lower() else 'etb'
        trigs = detect_triggers(engine.players, event_type, {})
        for tp, perm, oracle in trigs:
            triggers.append(f"{tp.name}'s {perm.name}")

    # Check for eliminations
    eliminations = []
    for p in engine.players:
        if p.life <= 0 and p.life > -999:
            eliminations.append(p.name)
            p.life = -999

    result = {
        "success": ok,
        "message": msg,
        "judge_needed": judge,
        "triggers": triggers,
        "eliminations": eliminations,
        "life": player.life,
        "hand_size": len(player.hand),
    }

    # Auto-check game over
    alive = [p for p in engine.players if p.life > 0]
    if len(alive) <= 1:
        engine.game_over = True
        result["game_over"] = True
        result["winner"] = alive[0].name if alive else "draw"

    return result


def end_turn(player_name: str) -> dict:
    """End your turn. Handles discard to 7 automatically (discards highest CMC)."""
    engine = _get_engine()
    player = _find_player(engine, player_name)

    discarded = []
    while len(player.hand) > 7:
        worst = max(player.hand, key=lambda c: c.get('cmc', 0))
        player.hand.remove(worst)
        player.graveyard.append(worst)
        discarded.append(worst['name'])

    engine.advance_turn()

    return {
        "discarded": discarded,
        "next_player": engine.active_player.name,
        "turn": engine.turn,
        "game_over": engine.game_over,
    }


def get_valid_actions(player_name: str) -> dict:
    """Get list of valid actions for the current player."""
    engine = _get_engine()
    player = _find_player(engine, player_name)

    actions = []

    # Lands
    for c in player.hand:
        if 'Land' in c.get('type_line', '') and player.land_drops_remaining > 0:
            actions.append(f"play {c['name']}")

    # Spells
    for c in player.hand:
        if 'Land' not in c.get('type_line', '') and can_cast(player, c):
            actions.append(f"cast {c['name']}")

    # Commander
    if player.command_zone:
        cmdr = player.command_zone[0]
        if can_cast(player, cmdr, commander_tax=player.commander_tax):
            actions.append("cast commander")

    # Attacks
    creatures = [p for p in player.battlefield if p.is_creature() and not p.tapped and not p.summoning_sick]
    if creatures:
        opponents = [p for p in engine.players if p is not player and p.life > 0]
        for opp in opponents:
            actions.append(f"attack all -> {opp.name}")

    actions.append("pass")

    return {"actions": actions, "phase": engine.phase}


def get_summary() -> dict:
    """Get the game summary (call after game_over)."""
    engine = _get_engine()
    return {"summary": engine.get_game_summary()}


def _find_player(engine, name):
    for p in engine.players:
        if name.lower() in p.name.lower():
            return p
    raise ValueError(f"Player '{name}' not found")


# ==================== CLI Interface ====================

def main():
    """Simple CLI: reads JSON commands from stdin, writes JSON results to stdout."""
    if len(sys.argv) > 1 and sys.argv[1] == '--serve':
        # Continuous server mode
        print(json.dumps({"status": "ready", "tools": list(TOOLS.keys())}), flush=True)
        for line in sys.stdin:
            try:
                cmd = json.loads(line.strip())
                tool = cmd.get('tool', '')
                args = cmd.get('args', {})
                if tool in TOOLS:
                    result = TOOLS[tool](**args)
                    print(json.dumps({"ok": True, "result": result}), flush=True)
                else:
                    print(json.dumps({"ok": False, "error": f"Unknown tool: {tool}"}), flush=True)
            except Exception as e:
                print(json.dumps({"ok": False, "error": str(e)}), flush=True)
    else:
        # Single command mode: python3 game_mcp_server.py '{"tool":"new_game","args":{"decklists":[...]}}'
        if len(sys.argv) < 2:
            print("Usage:")
            print("  Server: python3 game_mcp_server.py --serve")
            print("  Single: python3 game_mcp_server.py '{\"tool\":\"new_game\",\"args\":{...}}'")
            print(f"\nTools: {', '.join(TOOLS.keys())}")
            sys.exit(1)

        cmd = json.loads(sys.argv[1])
        tool = cmd.get('tool', '')
        args = cmd.get('args', {})
        if tool in TOOLS:
            result = TOOLS[tool](**args)
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps({"error": f"Unknown tool: {tool}"}))


TOOLS = {
    'new_game': new_game,
    'get_state': get_state,
    'get_hand': get_hand,
    'begin_turn': begin_turn,
    'do_action': do_action,
    'end_turn': end_turn,
    'get_valid_actions': get_valid_actions,
    'get_summary': get_summary,
}


if __name__ == '__main__':
    main()
