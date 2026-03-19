#!/usr/bin/env python3
"""Watch a live Commander game — polls the server and shows updates.

Usage:
    python3 game_watch.py g400              # Watch a specific game
    python3 game_watch.py g400 --once       # Print state once and exit
    python3 game_watch.py --list            # List all active games
    python3 game_watch.py g400 --events     # Show only events
    python3 game_watch.py g400 --json       # Raw JSON output
"""
import argparse
import json
import os
import pickle
import sys
import time
import urllib.request
import urllib.error

SERVER_URL = "http://127.0.0.1:8080"
GAMES_DIR = "/tmp/mtg_games"


def post(endpoint, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/{endpoint}", data=body,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}


def load_pickle(game_id):
    """Load game state directly from pickle for richer data."""
    path = os.path.join(GAMES_DIR, f"{game_id}.pkl")
    if not os.path.exists(path):
        return None, None
    with open(path, 'rb') as f:
        data = pickle.load(f)
    return data.get('engine') or data, data.get('meta', {})


def list_games():
    """List all games on the server."""
    if not os.path.exists(GAMES_DIR):
        print("No games directory found")
        return
    games = set()
    for f in os.listdir(GAMES_DIR):
        if f.endswith('.pkl'):
            games.add(f.replace('.pkl', ''))
    if not games:
        print("No games found")
        return

    print(f"{'Game':>8}  {'Turn':>4}  {'Phase':>10}  {'Active':>25}  Players")
    print("-" * 90)
    for gid in sorted(games):
        p = post('priority', {'game_id': gid})
        if 'error' in p:
            engine, meta = load_pickle(gid)
            if engine:
                names = [pl.name for pl in engine.players]
                print(f"{gid:>8}  {'?':>4}  {'offline':>10}  {'':>25}  {', '.join(names)}")
            continue
        turn = p.get('turn', '?')
        phase = p.get('phase', '?')
        active = p.get('active_player', '?')[:25]
        pq = p.get('priority_queue', [])
        names = p.get('mulligan_order', [])
        pq_str = f" [JUDGE]" if 'JUDGE' in pq else ""
        print(f"{gid:>8}  {turn:>4}  {phase:>10}  {active:>25}  {', '.join(n[:15] for n in names)}{pq_str}")


def show_scoreboard(game_id):
    """Compact scoreboard view."""
    engine, meta = load_pickle(game_id)
    if not engine:
        print(f"Game {game_id} not found")
        return

    p = post('priority', {'game_id': game_id})
    turn = p.get('turn', '?') if 'error' not in p else '?'
    phase = p.get('phase', '?') if 'error' not in p else '?'
    active = p.get('active_player', '?') if 'error' not in p else '?'
    pq = p.get('priority_queue', []) if 'error' not in p else []

    print(f"\n{'=' * 70}")
    print(f"  GAME {game_id} — Turn {turn} — {phase}")
    if 'JUDGE' in pq:
        print(f"  ⚠️  JUDGE CALL PENDING")
    print(f"{'=' * 70}")
    print(f"{'Player':30s} {'Life':>6} {'Lands':>5} {'Creatures':>9} {'Hand':>4}  Board")
    print(f"{'-' * 70}")

    for pl in engine.players:
        if pl.life <= 0:
            print(f"{'☠ ' + pl.name[:28]:30s} {'DEAD':>6}")
            continue

        lands = len([p for p in pl.battlefield if p.is_land()])
        creatures = [p for p in pl.battlefield if p.is_creature()]
        nonland_noncreat = [p for p in pl.battlefield if not p.is_land() and not p.is_creature()]
        hand = len(pl.hand)

        marker = " ◄" if pl.name == active else ""
        creature_names = ", ".join(
            f"{c.name[:15]}({c.power}/{c.toughness})" for c in creatures[:4]
        )
        if len(creatures) > 4:
            creature_names += f" +{len(creatures)-4}"

        other = ", ".join(p.name[:15] for p in nonland_noncreat[:3])
        if other:
            creature_names += f" | {other}"

        print(f"{pl.name[:28] + marker:30s} {pl.life:>6} {lands:>5} {len(creatures):>9} {hand:>4}  {creature_names}")

    # Recent events
    if engine.events:
        print(f"\n  Recent:")
        for e in engine.events[-6:]:
            if e.startswith('---'):
                print(f"  {e}")
            elif '⚖' in e:
                print(f"  {e[:80]}")
            else:
                print(f"    {e}")

    # Judge calls
    judge_calls = meta.get('judge_calls', [])
    if judge_calls:
        latest = judge_calls[-1]
        print(f"\n  Last judge call (T{latest['turn']}): {latest['player']}: {latest['question'][:80]}")

    print()


def show_full_state(game_id, player=None):
    """Full board state from a player's perspective."""
    engine, meta = load_pickle(game_id)
    if not engine:
        print(f"Game {game_id} not found")
        return

    if player is None:
        # Show from first alive player's view
        for pl in engine.players:
            if pl.life > 0:
                player = pl.name
                break
        else:
            player = engine.players[0].name

    result = post('state', {'game_id': game_id, 'player': player})
    if 'error' in result:
        print(f"Error: {result['error']}")
        return
    print(result['state'])


def show_events(game_id, count=20):
    """Show event log."""
    engine, meta = load_pickle(game_id)
    if not engine:
        print(f"Game {game_id} not found")
        return

    print(f"=== Events for {game_id} (last {count}) ===")
    for e in engine.events[-count:]:
        print(f"  {e}")

    judge_calls = meta.get('judge_calls', [])
    if judge_calls:
        print(f"\n=== Judge Calls ({len(judge_calls)}) ===")
        for jc in judge_calls:
            print(f"  T{jc['turn']} {jc['player']}: {jc['question'][:100]}")


def watch_loop(game_id, interval=10):
    """Continuously watch a game."""
    last_turn = -1
    last_event_count = 0

    while True:
        engine, meta = load_pickle(game_id)
        if not engine:
            print(f"Game {game_id} not found, waiting...")
            time.sleep(interval)
            continue

        p = post('priority', {'game_id': game_id})
        turn = p.get('turn', 0) if 'error' not in p else 0
        event_count = len(engine.events)

        # Only redraw if something changed
        if turn != last_turn or event_count != last_event_count:
            os.system('clear' if os.name == 'posix' else 'cls')
            show_scoreboard(game_id)
            last_turn = turn
            last_event_count = event_count

        phase = p.get('phase', '') if 'error' not in p else ''
        if phase == 'done':
            print("🏆 GAME OVER!")
            alive = [pl for pl in engine.players if pl.life > 0]
            if alive:
                print(f"Winner: {alive[0].name}")
            break

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='Watch a live Commander game')
    parser.add_argument('game_id', nargs='?', help='Game ID to watch')
    parser.add_argument('--list', action='store_true', help='List all games')
    parser.add_argument('--once', action='store_true', help='Print state once and exit')
    parser.add_argument('--events', action='store_true', help='Show event log')
    parser.add_argument('--full', action='store_true', help='Full board state')
    parser.add_argument('--player', type=str, help='Show state from this player perspective')
    parser.add_argument('--json', action='store_true', help='Raw JSON output')
    parser.add_argument('--interval', type=int, default=10, help='Poll interval in seconds')
    parser.add_argument('--event-count', type=int, default=30, help='Number of events to show')
    args = parser.parse_args()

    if args.list:
        list_games()
        return

    if not args.game_id:
        print("Usage: python3 game_watch.py <game_id> [--list|--once|--events|--full]")
        return

    if args.json:
        result = post('priority', {'game_id': args.game_id})
        print(json.dumps(result, indent=2))
        return

    if args.events:
        show_events(args.game_id, args.event_count)
        return

    if args.full:
        show_full_state(args.game_id, args.player)
        return

    if args.once:
        show_scoreboard(args.game_id)
        return

    # Live watch mode
    print(f"Watching game {args.game_id} (Ctrl+C to stop)...")
    try:
        watch_loop(args.game_id, args.interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")


if __name__ == '__main__':
    main()
