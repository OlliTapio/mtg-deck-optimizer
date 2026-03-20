#!/usr/bin/env python3
"""Launch a Commander game where Codex agents pilot each deck.

Each player runs as a separate `codex exec` process with full-auto mode.
Agents communicate with the HTTP game server via curl.
Each agent's conversation history serves as persistent memory across turns.

Usage:
    # Start the game server first:
    python3 game_http_server.py &

    # Then launch a game:
    python3 codex_game.py decks/wise_mothman/decklist.txt decks/yuma/decklist.txt \
        decks/ashling/decklist.txt decks/ureni/decklist.txt \
        --seed 42 --max-turns 12
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

SERVER_URL = "http://127.0.0.1:8080"


def post(endpoint, data=None):
    """POST JSON to game server."""
    body = json.dumps(data or {}).encode('utf-8')
    req = urllib.request.Request(
        f"{SERVER_URL}/{endpoint}",
        data=body,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return {'error': str(e)}


def load_deck_claude_md(decklist_path):
    """Load the deck's CLAUDE.md for strategy context."""
    deck_dir = os.path.dirname(decklist_path)
    claude_md = os.path.join(deck_dir, 'CLAUDE.md')
    if os.path.exists(claude_md):
        with open(claude_md) as f:
            return f.read()
    return ""


def build_player_prompt(player_name, decklist_path, game_id, all_players, strategy_md):
    """Build the system prompt for a codex player agent."""
    return f"""You are playing a Commander/EDH game of Magic: The Gathering. You are a skilled player who plays to WIN.

## CRITICAL: DO NOT SCRIPT OR AUTOMATE
Do NOT write bash scripts, loops, or automation. Play each turn MANUALLY by running one curl command at a time, thinking about the result, then deciding your next action. You are a thinking player, not a bot.

## Your Identity
- **Your player name**: {player_name}
- **Your deck**: {os.path.basename(os.path.dirname(decklist_path))}
- **Game ID**: {game_id}

## Other Players
{', '.join(p for p in all_players if p != player_name)}

## API Reference
Server: {SERVER_URL}. All calls are POST with JSON body containing game_id and player.

| Endpoint | Body | When to use |
|----------|------|------------|
| /wait | game_id, player, timeout:120 | Block until your turn |
| /hand | game_id, player | See your cards |
| /mulligan | game_id, player | Shuffle and redraw |
| /keep | game_id, player | Keep current hand |
| /begin | game_id, player | Start turn (untap, upkeep triggers, draw) |
| /valid | game_id, player | See legal actions (includes activate abilities!) |
| /action | game_id, player, action:"..." | Play land/cast/attack/activate |
| /draw | game_id, player, count:N | Draw N cards (for spell/ability effects) |
| /modify | game_id, player, target_player, permanent, counter_type, amount | Add/remove counters |
| /keyword | game_id, player, target_player, permanent, keyword | Grant keyword to permanent |
| /proliferate | game_id, player, targets:[...] | Proliferate counters |
| /equip | game_id, player, equipment, creature | Equip equipment to creature |
| /scry | game_id, player, count, bottom:["cards"] | Scry N, put named cards on bottom |
| /mill | game_id, player, count | Mill N cards to graveyard |
| /search | game_id, player, card_name, destination, tapped | Search library for card |
| /move | game_id, player, card_name, from_zone, to_zone | Move card between zones |
| /state | game_id, player | See full board |
| /end | game_id, player | End your turn |
| /respond | game_id, player, action:"pass" | Respond at instant speed |
| /judge | game_id, player, question:"..." | Ask rules question |

Example curl:
```bash
curl -s -X POST {SERVER_URL}/wait -d '{{"game_id":"{game_id}","player":"{player_name}","timeout":120}}'
curl -s -X POST {SERVER_URL}/valid -d '{{"game_id":"{game_id}","player":"{player_name}"}}'
curl -s -X POST {SERVER_URL}/action -d '{{"game_id":"{game_id}","player":"{player_name}","action":"attack all -> SomePlayer"}}'
curl -s -X POST {SERVER_URL}/action -d '{{"game_id":"{game_id}","player":"{player_name}","action":"activate Karn'"'"'s Bastion"}}'
curl -s -X POST {SERVER_URL}/draw -d '{{"game_id":"{game_id}","player":"{player_name}","count":3}}'
```

## Resolving Spell/Ability Effects
The engine moves cards between zones but does NOT auto-resolve spell effects. YOU resolve them yourself:

| Effect | Endpoint | Example |
|--------|----------|---------|
| Draw N cards | /draw | `{{"count":3}}` after Harmonize |
| Search library | /search | `{{"card_name":"Forest","destination":"battlefield","tapped":true}}` after Cultivate |
| +1/+1 counters | /modify | `{{"target_player":"{player_name}","permanent":"Card","counter_type":"+1/+1","amount":3}}` |
| Keywords | /keyword | `{{"target_player":"{player_name}","permanent":"Card","keyword":"trample"}}` |
| Proliferate | /proliferate | `{{"targets":[{{"player":"{player_name}","permanent":"Card","counter_type":"+1/+1"}}]}}` |
| Damage | /damage | `{{"target":"TargetPlayer","amount":3}}` |
| Destroy (→ graveyard) | /destroy | `{{"target_player":"TargetPlayer","permanent":"Card Name"}}` — triggers "dies" |
| Exile (→ exile) | /destroy | `{{"target_player":"TargetPlayer","permanent":"Card Name","exile":true}}` — no "dies" trigger |
| Move between zones | /move | `{{"card_name":"Card","from_zone":"graveyard","to_zone":"hand"}}` |

**IMPORTANT: Resolve effects YOURSELF using the table below. Do NOT call /judge unless truly ambiguous.**

## Oracle Text → Command Mapping
Read the oracle text of the card you cast. Match the effect to the right endpoint:

| Oracle text pattern | Command | Example |
|---|---|---|
| "draw N cards" / "draw a card" | `/draw` count=N | Mulldrifter → `/draw` count=2 |
| "search your library for a ... card" | `/search` card_name + destination | STE → `/search` card_name="Forest" destination="battlefield" tapped=true |
| "search ... put onto the battlefield tapped" | `/search` destination="battlefield" tapped=true | Cultivate → 2x `/search`: one dest="battlefield", one dest="hand" |
| "search ... put into your hand" | `/search` destination="hand" | Worldly Tutor → `/search` dest="hand" |
| "return ... from your graveyard to your hand" | `/move` from_zone="graveyard" to_zone="hand" | Regrowth → `/move` |
| "return ... from your graveyard to the battlefield" | `/move` from_zone="graveyard" to_zone="battlefield" | Reanimate → `/move` |
| "put a +1/+1 counter" / "N +1/+1 counters" | `/modify` counter_type="+1/+1" amount=N | Hardened Scales → `/modify` amount=1 |
| "deals N damage to" | `/damage` target + amount | Drakuseth ETB → `/damage` |
| "destroy target" / "destroy all" | `/destroy` target_player + permanent | Wrath → `/destroy` each creature |
| "exile target" / "exile all" | `/destroy` with exile=true | Path to Exile → `/destroy` exile=true (no "dies" trigger) |
| "return to hand" / bounce | `/move` from_zone="battlefield" to_zone="hand" | Unsummon → `/move` (LTB triggers fire, counters lost) |
| "exile, then return" / blink | `/move` to exile, then `/move` back | Ephemerate → `/move` to exile, then `/move` to battlefield (gets ETB!) |
| "ninjutsu" / "commander ninjutsu" | `/move` attacker battlefield→hand, then `/move` ninja hand→battlefield | Attack with evasive creature, then swap for ninja before damage |
| "mill N cards" | `/mill` count=N | Satyr Wayfinder → `/mill` count=4 then check GY for land |
| "scry N" | `/scry` count=N, then bottom=["cards to bottom"] | Temple ETB → `/scry` count=1 |
| "proliferate" | `/proliferate` targets=[...] | Karn's Bastion → `/proliferate` |
| "gains trample/flying/etc" | `/keyword` permanent + keyword | |
| "sacrifice" (your permanent) | `/destroy` your own permanent | Harrow → `/destroy` your land |
| "equip" / Equipment on board | `/equip` equipment + creature | Swiftfoot Boots → `/equip` |

## TRIGGERS — CRITICAL
When you play a card or attack, the response includes a `triggers` array. **You MUST resolve each trigger.**
Each trigger has a `resolve_hint` telling you which endpoint to call.

Examples:
- Mothman attacks → trigger: "rad counter" → call `/modify` on each opponent with permanent="" counter_type="rad" amount=1 (PLAYER counter, leave permanent empty)
- Mothman attacks → trigger: "proliferate" → call `/proliferate`
- Yuriko deals combat damage → trigger: "reveal top card, lose life" → call `/scry` count=1, then `/damage`
- Landfall trigger → check oracle text, call `/draw`, `/modify`, or `/search` as needed
- ETB trigger → check oracle text, resolve with appropriate endpoint

**After EVERY attack action, check the triggers in the response and resolve them before ending your turn.**

When resolving multi-step effects (e.g. Cultivate = search basic to battlefield tapped + search basic to hand + shuffle), call each step in sequence.

Only call `/judge` for truly complex interactions you cannot figure out from the oracle text.

## Turn Sequence (do this EVERY turn)
1. `/wait` — blocks until your turn
2. `/begin` — draws a card, returns board state + valid actions + rad resolution (ALL IN ONE CALL)
3. Play land, cast spells, attack — use `/action` for each, check `/valid` between actions
4. **Resolve triggers** from action responses before continuing
5. `/end` — end your turn

`/begin` gives you everything: drew card, board state, valid actions, upkeep triggers, rad resolution. No need for separate `/state` or `/valid` after `/begin`.

Think about each action. What advances your win condition? What do opponents threaten? Check opponent commanders' oracle text in the state.

## COMBAT
Attack when it advances your win condition. Consider:
- Do you need blockers to survive? Keep them back.
- Is an opponent close to dying? Finish them.
- Does attacking trigger abilities for your deck (e.g. combat damage triggers)?
- Who is the biggest threat at the table?

The /valid response shows: `"attack all -> PlayerName"` — sends all creatures at one player.
You can also split: `"attack CreatureA -> Player1, CreatureB -> Player2"`

## Mulligan Guide
First mulligan is FREE (you get 7 cards back). Keep a hand with:
- At least 2-3 lands
- At least 1 piece of ramp or early play
- A path to your game plan

## Priority / Responses
When /wait returns "priority", an opponent did something. Call /respond with either:
- An instant-speed spell: `"cast Counterspell"` or `"cast Path to Exile"`
- A block declaration: `"block AttackerName with MyCreature"` — your creature blocks theirs
- Or just: `"pass"` — if all defenders pass, combat damage resolves

**Blocking**: When an opponent attacks, you get priority to block. Use `/respond` with:
`"block Xenagos, God of Revels with Sakura-Tribe Elder"` — your creature intercepts theirs.
Blocked creatures deal damage to blockers instead of you. If blocker toughness <= attacker power, blocker dies.
If attacker has trample, excess damage goes to you. You can block multiple attackers with different creatures.

When /wait returns "judge_pause", a rules question is being resolved. Just call /wait again — do NOT call /judge yourself.

## Your Deck Strategy
{strategy_md if strategy_md else "No specific strategy notes. Play smart based on what you draw."}

## START NOW
This may be a new game OR a resumed game. Either way:
1. Call /wait to check game phase
2. If mulligan: /hand, evaluate, /keep or /mulligan
3. If playing: call /state first to see the current board, then follow the turn sequence
4. Keep playing until /wait returns "game_over"
5. NEVER stop early.

## POST-GAME REPORT
When the game ends, write a brief report:
1. Did you win or lose? What turn did it end?
2. What was your win condition / how did you die?
3. Which cards were MVPs? Which cards were useless or stuck in hand?
4. What was missing from the engine that prevented you from executing your strategy?
5. What would you change about the deck?
"""


def start_server():
    """Start the HTTP game server if not already running."""
    try:
        post('priority', {'game_id': 'ping'})
        print("[orchestrator] Game server already running")
        return None
    except Exception:
        pass

    print("[orchestrator] Starting game server...")
    proc = subprocess.Popen(
        [sys.executable, 'game_http_server.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    for _ in range(20):
        time.sleep(0.5)
        try:
            post('priority', {'game_id': 'ping'})
            print("[orchestrator] Game server ready")
            return proc
        except Exception:
            continue
    print("[orchestrator] ERROR: Server failed to start")
    proc.kill()
    sys.exit(1)


def create_game(decklists, seed=None):
    """Create a new game on the server."""
    data = {'decklists': decklists}
    if seed is not None:
        data['seed'] = seed
    result = post('create', data)
    if 'error' in result:
        print(f"[orchestrator] ERROR creating game: {result['error']}")
        sys.exit(1)
    return result


def launch_player(player_name, decklist_path, game_id, all_players, output_dir):
    """Launch a codex exec process for one player."""
    strategy_md = load_deck_claude_md(decklist_path)
    prompt = build_player_prompt(player_name, decklist_path, game_id, all_players, strategy_md)

    # Sanitize player name for filenames
    safe_name = player_name.replace(' ', '_').replace(',', '')

    # Write prompt to file for codex to read from stdin
    prompt_file = os.path.join(output_dir, f"{safe_name}_prompt.txt")
    with open(prompt_file, 'w') as f:
        f.write(prompt)

    output_file = os.path.join(output_dir, f"{safe_name}_output.txt")
    log_file = os.path.join(output_dir, f"{safe_name}_log.jsonl")

    cmd = [
        'codex', 'exec',
        '--dangerously-bypass-approvals-and-sandbox',
        '--skip-git-repo-check',
        '--json',  # JSONL output for monitoring
        '-c', 'model_reasoning_effort="low"',  # Low thinking per user request
        '-o', output_file,
        '-',  # Read prompt from stdin
    ]

    with open(prompt_file) as stdin_f, open(log_file, 'w') as log_f:
        proc = subprocess.Popen(
            cmd,
            stdin=stdin_f,
            stdout=log_f,
            stderr=subprocess.PIPE,
        )

    print(f"[orchestrator] Launched {player_name} (PID {proc.pid})")
    return proc, output_file, log_file


def build_judge_prompt(game_id, player_names, judge_calls, board_state):
    """Build a one-shot prompt for the judge to resolve a specific call."""
    calls_text = "\n".join(
        f"- Turn {jc['turn']}, {jc['player']}: {jc['question']}"
        for jc in judge_calls
    )
    return f"""You are the JUDGE for a Commander/EDH game. Resolve the pending judge call(s) below.

## Game: {game_id}
## Players: {', '.join(player_names)}

## Pending Judge Calls
{calls_text}

## Current Board State
{board_state}

## Your Tools (curl to {SERVER_URL})

# Search library (tutor effects: STE, Cultivate, Rampant Growth, etc.)
curl -s -X POST {SERVER_URL}/search -d '{{"game_id":"{game_id}","player":"PLAYER","card_name":"Forest","destination":"battlefield","tapped":true}}'
# destination: "battlefield", "hand", "graveyard", "top"

# Move card between zones (recursion, exile effects, etc.)
curl -s -X POST {SERVER_URL}/move -d '{{"game_id":"{game_id}","player":"PLAYER","card_name":"Card","from_zone":"graveyard","to_zone":"hand"}}'
# zones: hand, battlefield, graveyard, exile, command_zone, library

# Draw cards
curl -s -X POST {SERVER_URL}/draw -d '{{"game_id":"{game_id}","player":"PLAYER","count":2}}'

# Add/remove counters
curl -s -X POST {SERVER_URL}/modify -d '{{"game_id":"{game_id}","player":"PLAYER","target_player":"PLAYER","permanent":"Card","counter_type":"+1/+1","amount":3}}'

# Grant keyword
curl -s -X POST {SERVER_URL}/keyword -d '{{"game_id":"{game_id}","player":"PLAYER","target_player":"PLAYER","permanent":"Card","keyword":"trample"}}'

# Deal damage
curl -s -X POST {SERVER_URL}/damage -d '{{"game_id":"{game_id}","player":"PLAYER","target":"TARGET","amount":3}}'

# Destroy permanent
curl -s -X POST {SERVER_URL}/destroy -d '{{"game_id":"{game_id}","player":"PLAYER","target_player":"TARGET","permanent":"Card"}}'

# MUST call this last to resume the game
curl -s -X POST {SERVER_URL}/resolve_judge -d '{{"game_id":"{game_id}","ruling":"Your ruling explanation"}}'

## Common Rulings
- **Tutor/Search** (STE, Cultivate, Rampant Growth, Farseek): /search with correct destination
- **ETB triggers** (draw, damage, counters): /draw, /damage, /modify
- **Token creation**: NOT supported — note in ruling, skip token
- **Graveyard recursion**: /move from graveyard to hand/battlefield
- **Board wipes**: /destroy for each permanent
- **Counter effects**: /modify with counter_type and amount

## Instructions
1. Read the judge call question carefully
2. Check the oracle text of the relevant card in the board state
3. Apply the correct state changes using the endpoints above
4. Call /resolve_judge with a clear ruling explaining what you did and any limitations
5. If token creation is needed, note it in the ruling but skip it (engine limitation)

DO NOT poll or loop. Resolve this ONE call and finish.
"""


def launch_judge_for_call(game_id, player_names, judge_calls, board_state, output_dir, call_num):
    """Launch a one-shot codex agent to resolve a judge call."""
    prompt = build_judge_prompt(game_id, player_names, judge_calls, board_state)

    safe_id = f"judge_call_{call_num}"
    prompt_file = os.path.join(output_dir, f"{safe_id}_prompt.txt")
    with open(prompt_file, 'w') as f:
        f.write(prompt)

    output_file = os.path.join(output_dir, f"{safe_id}_output.txt")
    log_file = os.path.join(output_dir, f"{safe_id}_log.jsonl")

    cmd = [
        'codex', 'exec',
        '--dangerously-bypass-approvals-and-sandbox',
        '--skip-git-repo-check',
        '--json',
        '-c', 'model_reasoning_effort="high"',
        '-o', output_file,
        '-',
    ]

    with open(prompt_file) as stdin_f, open(log_file, 'w') as log_f:
        proc = subprocess.Popen(
            cmd,
            stdin=stdin_f,
            stdout=log_f,
            stderr=subprocess.PIPE,
        )

    print(f"[orchestrator] Launched Judge #{call_num} (PID {proc.pid})")
    return proc, output_file, log_file


def monitor_game(game_id, processes, max_turns=15, poll_interval=15, output_dir="/tmp"):
    """Monitor the game until completion or max turns."""
    start_time = time.time()
    last_turn = 0
    consecutive_errors = 0
    last_phase = ''
    judge_call_count = 0
    judge_procs = []

    while True:
        time.sleep(poll_interval)

        # Check game state
        result = post('priority', {'game_id': game_id})
        if 'error' in result:
            consecutive_errors += 1
            if consecutive_errors <= 8:
                continue
            print(f"[orchestrator] Too many errors: {result['error'][:80]}")
            break
        consecutive_errors = 0

        phase = result.get('phase', '')
        turn = result.get('turn', 0)
        active = result.get('active_player', '?')
        pq = result.get('priority_queue', [])

        if turn != last_turn or phase != last_phase:
            elapsed = int(time.time() - start_time)
            print(f"[orchestrator] T{turn} — {active[:25]} — {elapsed}s — {phase}")
            last_turn = turn
            last_phase = phase

        # Detect JUDGE call — only spawn if no judge already active
        if 'JUDGE' in pq:
            judge_alive = any(p.poll() is None for p, _, _ in judge_procs)
            if not judge_alive:
                judge_call_count += 1
                print(f"[orchestrator] JUDGE CALL #{judge_call_count} detected! Spawning judge agent...")

                try:
                    import pickle
                    with open(f'/tmp/mtg_games/{game_id}.pkl', 'rb') as f:
                        data = pickle.load(f)
                    meta = data['meta']
                    judge_calls = meta.get('judge_calls', [])

                    player_names = result.get('mulligan_order', [])
                    board = post('state', {'game_id': game_id, 'player': player_names[0] if player_names else 'any'})
                    board_state = board.get('state', 'N/A')

                    proc, out, log = launch_judge_for_call(
                        game_id, player_names, judge_calls, board_state,
                        output_dir, judge_call_count
                    )
                    judge_procs.append((proc, out, log))
                except Exception as e:
                    print(f"[orchestrator] Failed to launch judge: {e}")
            else:
                pass  # Judge already working on it

        if phase == 'done':
            print("[orchestrator] Game over!")
            break

        if turn > max_turns:
            print(f"[orchestrator] Max turns ({max_turns}) reached")
            break

        # Check if player agents have died (ignore judge procs)
        player_procs = {k: v for k, v in processes.items() if k != 'JUDGE'}
        all_dead = True
        for name, (proc, _, _) in player_procs.items():
            if proc.poll() is None:
                all_dead = False
            else:
                rc = proc.returncode
                if rc != 0:
                    print(f"[orchestrator] {name} exited with code {rc}")
        if all_dead and player_procs:
            print("[orchestrator] All player agents have exited")
            break

    # Clean up judge procs
    for proc, _, _ in judge_procs:
        if proc.poll() is None:
            proc.kill()

    return result


def collect_results(game_id, player_names, processes, output_dir):
    """Collect and display game results."""
    print("\n" + "=" * 60)
    print("GAME RESULTS")
    print("=" * 60)

    # Get final state
    for name in player_names:
        state = post('state', {'game_id': game_id, 'player': name})
        state_text = state.get('state', 'N/A')
        print(f"\n--- {name} ---")
        # Print first few lines of state
        for line in state_text.split('\n')[:10]:
            print(f"  {line}")

    # Print agent outputs
    print("\n" + "=" * 60)
    print("AGENT SUMMARIES")
    print("=" * 60)
    for name, (proc, output_file, log_file) in processes.items():
        print(f"\n--- {name} ---")
        if os.path.exists(output_file):
            with open(output_file) as f:
                content = f.read().strip()
            if content:
                # Print last 500 chars of output
                if len(content) > 500:
                    print(f"  ...({len(content)} chars total)")
                    print(f"  {content[-500:]}")
                else:
                    print(f"  {content}")
            else:
                print("  (no output)")
        else:
            print("  (no output file)")

    # Save full game report
    report_file = os.path.join(output_dir, 'game_report.txt')
    with open(report_file, 'w') as f:
        f.write(f"Game ID: {game_id}\n\n")
        for name in player_names:
            state = post('state', {'game_id': game_id, 'player': name})
            f.write(f"=== {name} ===\n")
            f.write(state.get('state', 'N/A'))
            f.write('\n\n')
    print(f"\n[orchestrator] Full report saved to {report_file}")


def resume_game(game_id):
    """Get game info for an existing game to resume."""
    result = post('priority', {'game_id': game_id})
    if 'error' in result:
        return None
    return result


def main():
    parser = argparse.ArgumentParser(description='Launch a Commander game with Codex agents')
    parser.add_argument('decklists', nargs='*', help='Paths to decklist files (2-4)')
    parser.add_argument('--seed', type=int, default=None, help='Random seed')
    parser.add_argument('--max-turns', type=int, default=15, help='Maximum turns before stopping')
    parser.add_argument('--poll', type=int, default=30, help='Seconds between status polls')
    parser.add_argument('--output-dir', default=None, help='Directory for game output')
    parser.add_argument('--resume', type=str, default=None, help='Resume an existing game by game_id')
    args = parser.parse_args()

    # Output directory
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    output_dir = args.output_dir or f"/tmp/mtg_codex_game_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"[orchestrator] Output dir: {output_dir}")

    # Start server if needed
    server_proc = start_server()

    try:
        if args.resume:
            # Resume existing game
            game_id = args.resume
            info = resume_game(game_id)
            if not info:
                print(f"ERROR: Game {game_id} not found on server")
                sys.exit(1)

            # Get player names from the mulligan_order (always populated)
            player_names = info.get('mulligan_order', [])
            if not player_names:
                print("ERROR: Could not determine players from game state")
                sys.exit(1)

            # Match player names to decklists
            if not args.decklists or len(args.decklists) != len(player_names):
                print(f"ERROR: --resume requires {len(player_names)} decklists in player order: {', '.join(player_names)}")
                sys.exit(1)

            print(f"[orchestrator] Resuming game {game_id}")
            print(f"[orchestrator] Players: {', '.join(player_names)}")
            print(f"[orchestrator] Turn: {info.get('turn', '?')}, Phase: {info.get('phase', '?')}")

        else:
            # New game
            if len(args.decklists) < 2 or len(args.decklists) > 4:
                print("ERROR: Need 2-4 decklists")
                sys.exit(1)

            for dl in args.decklists:
                if not os.path.exists(dl):
                    print(f"ERROR: Decklist not found: {dl}")
                    sys.exit(1)

            result = create_game(args.decklists, args.seed)
            game_id = result['game_id']
            player_names = [p['name'] for p in result['players']]
            print(f"[orchestrator] Game {game_id} created")
            print(f"[orchestrator] Players: {', '.join(player_names)}")
            print(f"[orchestrator] Phase: {result['phase']}")

        # Launch one codex agent per player (judge spawned on-demand by monitor)
        processes = {}
        for i, (name, dl) in enumerate(zip(player_names, args.decklists)):
            proc, output_file, log_file = launch_player(
                name, dl, game_id, player_names, output_dir
            )
            processes[name] = (proc, output_file, log_file)
            time.sleep(1)  # Stagger launches slightly

        # Monitor
        print(f"\n[orchestrator] Game running... (max {args.max_turns} turns)")
        final = monitor_game(game_id, processes, args.max_turns, args.poll, output_dir)

        # Wait for agents to finish (give them 60s)
        print("[orchestrator] Waiting for agents to finish...")
        deadline = time.time() + 60
        for name, (proc, _, _) in processes.items():
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                print(f"[orchestrator] Killing {name} (timeout)")
                proc.kill()

        # Results
        collect_results(game_id, player_names, processes, output_dir)

    finally:
        # Never kill the game server — it persists for resume
        if server_proc:
            print(f"[orchestrator] Game server still running (PID {server_proc.pid}). Kill manually when done.")


if __name__ == '__main__':
    main()
