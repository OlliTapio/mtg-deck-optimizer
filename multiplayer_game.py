#!/usr/bin/env python3
"""Multiplayer Commander game with LLM-piloted players.

Each player is piloted by a separate Claude invocation. The engine manages
game state, turn order, stack/priority, and combat. Players communicate via
structured text prompts.

Usage:
    python3 multiplayer_game.py decks/yuma/decklist.txt decks/wise_mothman/decklist.txt decks/ashling/decklist.txt decks/muldrotha/decklist.txt --ai llm --seed 42 --max-turns 12
    python3 multiplayer_game.py decks/yuma/decklist.txt decks/ashling/decklist.txt --ai auto --seed 42
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

from card_cache import get_deck_cards
from game_simulator import (
    Player, Permanent, GameState, MulliganGuide,
    make_card, card_from_scryfall,
    get_available_mana, can_cast, tap_mana_for,
    play_land, cast_spell, create_token, resolve_combat,
    check_game_over, format_state, evaluate_hand_for_mulligan,
    parse_mulligan_guide, _player_threat_score,
    _parse_pips, PIP_RE, GENERIC_RE,
)

# Re-use auto-pilot heuristics
from auto_pilot import pick_land_to_play, pick_spells_to_cast


# ==================== Stack ====================

@dataclass
class StackEntry:
    """A spell or ability on the stack."""
    card: dict
    controller: Player
    description: str


class GameStack:
    """The stack for spell/ability resolution."""

    def __init__(self):
        self.entries: list[StackEntry] = []

    def push(self, entry: StackEntry):
        self.entries.append(entry)

    def pop(self):
        return self.entries.pop() if self.entries else None

    def is_empty(self):
        return len(self.entries) == 0

    def format(self):
        if not self.entries:
            return "Stack: (empty)"
        lines = ["Stack (top resolves first):"]
        for i, e in enumerate(reversed(self.entries)):
            lines.append(f"  {i+1}. {e.description} (by {e.controller.name})")
        return '\n'.join(lines)


# ==================== Multiplayer State ====================

class MultiplayerGame:
    """Manages a multiplayer Commander game with N real-deck players."""

    def __init__(self, players, seed=None):
        """players: list of Player objects with loaded decks."""
        self.players = players
        self.rng = random.Random(seed)
        self.turn_number = 1
        self.active_player_idx = 0
        self.phase = "setup"
        self.stack = GameStack()
        self.game_log: list[str] = []
        self.game_over = False
        self.winner = None
        # Track auto-skip per player (hidden)
        self.auto_skip: dict[str, bool] = {p.name: False for p in players}
        # Track per-player stats
        self.stats = {p.name: {
            'cards_played': [],
            'damage_dealt': 0,
            'damage_taken': 0,
            'commander_first_cast': 0,
        } for p in players}

    @property
    def active_player(self):
        return self.players[self.active_player_idx]

    def alive_players(self):
        return [p for p in self.players if p.life > 0]

    def opponents_of(self, player):
        return [p for p in self.players if p is not player and p.life > 0]

    def next_player_idx(self, from_idx=None):
        if from_idx is None:
            from_idx = self.active_player_idx
        idx = (from_idx + 1) % len(self.players)
        # Skip dead players
        attempts = 0
        while self.players[idx].life <= 0 and attempts < len(self.players):
            idx = (idx + 1) % len(self.players)
            attempts += 1
        return idx

    def log(self, msg):
        self.game_log.append(msg)
        print(msg)

    def has_instant_speed_options(self, player):
        """Check if player has any instant-speed plays available."""
        for c in player.hand:
            tl = c.get('type_line', '')
            kw = c.get('keywords', [])
            if 'Instant' in tl or 'Flash' in kw:
                if can_cast(player, c):
                    return True
        # Check activated abilities on untapped permanents (simplified)
        for perm in player.battlefield:
            oracle = perm.card.get('oracle_text', '')
            if '{T}' in oracle and not perm.tapped:
                return True
        return False

    # ==================== State Formatting ====================

    def format_state_for_player(self, viewer):
        """Format game state from a specific player's perspective."""
        lines = []
        lines.append(f"=== Turn {self.turn_number} — {self.active_player.name}'s turn — Phase: {self.phase} ===")
        lines.append(f"You are: {viewer.name}")
        lines.append(f"Your life: {viewer.life}")

        # Command zone
        if viewer.command_zone:
            cmdr_names = [c['name'] for c in viewer.command_zone]
            lines.append(f"Your command zone: {', '.join(cmdr_names)} (tax: {viewer.commander_tax})")

        # Your hand (only visible to you)
        lines.append(f"\n--- Your Hand ({len(viewer.hand)}) ---")
        for c in sorted(viewer.hand, key=lambda x: (x.get('cmc', 0), x['name'])):
            cost = c.get('mana_cost', '')
            tl = c.get('type_line', '')
            extras = []
            if c.get('power') or c.get('toughness'):
                extras.append(f"{c['power']}/{c['toughness']}")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            castable = " [CASTABLE]" if can_cast(viewer, c) else ""
            lines.append(f"  {c['name']}  {cost}  [{tl}]{extra_str}{castable}")

        # Available mana
        mana = get_available_mana(viewer)
        mana_parts = []
        for color in ['W', 'U', 'B', 'R', 'G', 'C']:
            if mana.get(color, 0) > 0:
                mana_parts.append(f"{{{color}}}x{mana[color]}")
        lines.append(f"\nYour mana: {', '.join(mana_parts) if mana_parts else 'none'} (total: {mana['total']})")
        lines.append(f"Land drops remaining: {viewer.land_drops_remaining}")

        # All battlefields (public info)
        for p in self.players:
            status = f"life: {p.life}" if p.life > 0 else "ELIMINATED"
            is_you = " (YOU)" if p is viewer else ""
            is_active = " [ACTIVE]" if p is self.active_player else ""
            lines.append(f"\n--- {p.name}{is_you}{is_active} ({status}) ---")

            if p.life <= 0:
                continue

            # Lands
            lands = [perm for perm in p.battlefield if perm.is_land()]
            nonlands = [perm for perm in p.battlefield if not perm.is_land()]
            if lands:
                untapped = Counter(l.name for l in lands if not l.tapped)
                tapped = Counter(l.name for l in lands if l.tapped)
                if untapped:
                    parts = [f"{n}x {name}" if n > 1 else name for name, n in sorted(untapped.items())]
                    lines.append(f"  Lands (untapped): {', '.join(parts)}")
                if tapped:
                    parts = [f"{n}x {name}" if n > 1 else name for name, n in sorted(tapped.items())]
                    lines.append(f"  Lands (tapped): {', '.join(parts)}")

            for perm in sorted(nonlands, key=lambda p: p.name):
                status_parts = []
                if perm.tapped:
                    status_parts.append("tapped")
                if perm.summoning_sick:
                    status_parts.append("sick")
                status_str = f" [{', '.join(status_parts)}]" if status_parts else ""
                p_t = f" ({perm.power}/{perm.toughness})" if perm.is_creature() else ""
                lines.append(f"  {perm.name}{p_t}{status_str}")

            if not lands and not nonlands:
                lines.append("  (empty)")

            # Hand size (visible) but not contents
            if p is not viewer:
                lines.append(f"  Cards in hand: {len(p.hand)}")

            # Graveyard summary
            if p.graveyard:
                gy_names = Counter(c['name'] for c in p.graveyard)
                gy_str = ', '.join(f"{name}" + (f" x{n}" if n > 1 else "") for name, n in sorted(gy_names.items()))
                lines.append(f"  Graveyard ({len(p.graveyard)}): {gy_str}")

        # Stack
        if not self.stack.is_empty():
            lines.append(f"\n{self.stack.format()}")

        # Recent game log (last 5 events)
        if self.game_log:
            lines.append(f"\n--- Recent Events ---")
            for msg in self.game_log[-8:]:
                lines.append(f"  {msg}")

        return '\n'.join(lines)

    # ==================== Priority / Stack ====================

    def pass_priority(self, starting_player, prompt, get_action):
        """Pass priority around the table starting from a player.

        Returns True if anyone responded, False if all passed.
        """
        idx = self.players.index(starting_player)
        for _ in range(len(self.players)):
            idx = self.next_player_idx(idx)
            p = self.players[idx]
            if p is starting_player or p.life <= 0:
                continue

            # Auto-skip if no instant speed options
            if self.auto_skip.get(p.name) and not self.has_instant_speed_options(p):
                continue

            state = self.format_state_for_player(p)
            action = get_action(p, state, f"{prompt}\nYou have priority. Respond with an instant-speed action or 'pass'.")
            action = action.strip().lower()

            if action and action != 'pass':
                # Try to cast instant
                result = self._execute_action(p, action)
                if result:
                    self.log(f"  {p.name}: {result}")
                    return True
        return False

    # ==================== Action Execution ====================

    def _execute_action(self, player, action):
        """Execute a player action. Returns result string or None."""
        action_lower = action.lower().strip()

        # Play land
        if action_lower.startswith("play "):
            card_name = action[5:].strip()
            card = self._find_in_hand(player, card_name)
            if not card:
                return None
            if 'Land' not in card.get('type_line', ''):
                return None
            if play_land(player, card):
                self.stats[player.name]['cards_played'].append(card['name'])
                return f"plays {card['name']}"
            return None

        # Cast spell
        if action_lower.startswith("cast "):
            card_name = action[5:].strip()

            if card_name.lower() == "commander":
                if not player.command_zone:
                    return None
                card = player.command_zone[0]
                if cast_spell(player, card, commander_tax=player.commander_tax):
                    if self.stats[player.name]['commander_first_cast'] == 0:
                        self.stats[player.name]['commander_first_cast'] = self.turn_number
                    self.stats[player.name]['cards_played'].append(card['name'])
                    player.commander_tax += 2
                    return f"casts {card['name']} from command zone (tax now {player.commander_tax})"
                return None

            card = self._find_in_hand(player, card_name)
            if not card:
                return None
            if cast_spell(player, card):
                self.stats[player.name]['cards_played'].append(card['name'])
                return f"casts {card['name']}"
            return None

        # Attack
        if action_lower.startswith("attack "):
            return self._handle_attack(player, action)

        return None

    def _find_in_hand(self, player, name):
        name_lower = name.lower()
        for c in player.hand:
            if c['name'].lower() == name_lower:
                return c
        for c in player.hand:
            if name_lower in c['name'].lower():
                return c
        return None

    def _find_player(self, name):
        name_lower = name.lower()
        for p in self.players:
            if p.name.lower() == name_lower:
                return p
        for p in self.players:
            if name_lower in p.name.lower():
                return p
        return None

    def _handle_attack(self, attacker, action):
        """Parse attack declarations and resolve combat."""
        action_lower = action.lower().strip()
        opponents = self.opponents_of(attacker)
        if not opponents:
            return None

        attacks = []

        # "attack all -> PlayerName"
        if "attack all" in action_lower:
            target_name = action_lower.split("->")[-1].strip() if "->" in action_lower else ""
            target = self._find_player(target_name) if target_name else None
            if not target or target.life <= 0:
                target = opponents[0]
            for perm in attacker.battlefield:
                if perm.is_creature() and not perm.tapped and not perm.summoning_sick:
                    attacks.append((perm, target))
        else:
            # "CreatureName -> PlayerName, ..."
            parts = action.split(",")
            for part in parts:
                if "->" not in part:
                    continue
                creature_name, target_name = part.split("->", 1)
                creature_name = creature_name.strip().lower()
                target_name = target_name.strip()
                perm = None
                for p in attacker.battlefield:
                    if p.is_creature() and creature_name in p.name.lower():
                        perm = p
                        break
                target = self._find_player(target_name)
                if perm and target and target.life > 0:
                    attacks.append((perm, target))

        if not attacks:
            return None

        # Resolve combat
        damage_by_target = Counter()
        total_dmg = 0
        for perm, target in attacks:
            if perm.tapped or perm.summoning_sick or not perm.is_creature():
                continue
            dmg = perm.power
            if dmg > 0:
                target.life -= dmg
                perm.tapped = True
                total_dmg += dmg
                damage_by_target[target.name] += dmg

        self.stats[attacker.name]['damage_dealt'] += total_dmg
        for name, dmg in damage_by_target.items():
            for p in self.players:
                if p.name == name:
                    self.stats[name]['damage_taken'] += dmg

        parts = [f"{dmg} to {name}" for name, dmg in damage_by_target.items()]
        return f"attacks for {', '.join(parts)}" if parts else None

    # ==================== Turn Structure ====================

    def play_turn(self, get_action):
        """Play one full turn for the active player."""
        player = self.active_player
        if player.life <= 0:
            return

        # Untap + Draw
        if self.turn_number > 1 or self.active_player_idx > 0:
            player.untap_all()
        player.reset_land_drops()

        self.log(f"\n{'='*60}")
        self.log(f"  TURN {self.turn_number} — {player.name}")
        self.log(f"{'='*60}")

        # Draw (Commander: everyone draws including first player T1)
        player.draw()
        if player.life <= 0:
            self.log(f"  {player.name} draws from empty library and loses!")
            return

        # Main Phase 1
        self.phase = "main1"
        self._do_main_phase(player, get_action, "main1")

        # Combat
        self.phase = "combat"
        self._do_combat(player, get_action)

        # Main Phase 2
        self.phase = "main2"
        self._do_main_phase(player, get_action, "main2")

        # End Step — discard to 7
        self.phase = "end"
        while len(player.hand) > 7:
            state = self.format_state_for_player(player)
            action = get_action(player, state,
                f"Hand size {len(player.hand)}, discard to 7. Name a card to discard.")
            card_name = action.strip()
            card = self._find_in_hand(player, card_name)
            if card:
                player.hand.remove(card)
                player.graveyard.append(card)
                self.log(f"  {player.name} discards {card['name']}")
            else:
                # Auto-discard highest CMC
                worst = max(player.hand, key=lambda c: c.get('cmc', 0))
                player.hand.remove(worst)
                player.graveyard.append(worst)
                self.log(f"  {player.name} discards {worst['name']}")

        # Update auto-skip based on current hand
        self.auto_skip[player.name] = not self.has_instant_speed_options(player)

        # Check eliminations
        for p in self.players:
            if p.life <= 0 and p.life != -999:
                self.log(f"  {p.name} has been ELIMINATED!")
                p.life = -999  # mark as processed

    def _do_main_phase(self, player, get_action, phase_name):
        """Handle a main phase with multiple actions."""
        for _ in range(10):  # safety limit
            state = self.format_state_for_player(player)
            prompt = (f"--- {phase_name.upper()} ---\n"
                     f"Actions: play <land>, cast <spell>, cast commander, pass\n"
                     f"Respond with ONE action or 'pass' to end this phase.")
            action = get_action(player, state, prompt)
            action_clean = action.strip().lower()

            if not action_clean or action_clean == 'pass':
                break

            result = self._execute_action(player, action)
            if result:
                self.log(f"  {player.name} {result}")
                # Give other players priority to respond
                self.pass_priority(player,
                    f"{player.name} just: {result}",
                    get_action)
            else:
                break  # invalid action, move on

    def _do_combat(self, player, get_action):
        """Handle combat phase."""
        creatures = [perm for perm in player.battlefield
                     if perm.is_creature() and not perm.tapped and not perm.summoning_sick]
        if not creatures:
            return

        opponents = self.opponents_of(player)
        if not opponents:
            return

        state = self.format_state_for_player(player)
        opp_list = ', '.join(f"{o.name} (life: {o.life})" for o in opponents)
        creature_list = ', '.join(f"{c.name} ({c.power}/{c.toughness})" for c in creatures)
        prompt = (f"--- COMBAT ---\n"
                 f"Your attackers: {creature_list}\n"
                 f"Opponents: {opp_list}\n"
                 f"Declare attacks: 'attack all -> PlayerName' or 'CreatureName -> PlayerName, ...' or 'pass'")
        action = get_action(player, state, prompt)

        if action.strip().lower() == 'pass':
            return

        result = self._handle_attack(player, action)
        if result:
            self.log(f"  {player.name} {result}")
            # Check for kills
            for p in self.players:
                if p.life <= 0 and p is not player:
                    self.log(f"  {p.name} is ELIMINATED by {player.name}!")

    # ==================== Game Loop ====================

    def run(self, get_action, max_turns=15):
        """Run the full game."""
        self.log(f"\n{'#'*60}")
        self.log(f"  MULTIPLAYER COMMANDER GAME")
        self.log(f"{'#'*60}")
        self.log(f"Players: {', '.join(p.name for p in self.players)}")
        for p in self.players:
            cmdr = p.command_zone[0]['name'] if p.command_zone else "none"
            self.log(f"  {p.name}: {cmdr} (hand: {len(p.hand)} cards)")
        self.log("")

        turn_count = 0
        while turn_count < max_turns * len(self.players) and not self.game_over:
            self.play_turn(get_action)

            # Advance to next player
            self.active_player_idx = self.next_player_idx()
            if self.active_player_idx == 0:
                self.turn_number += 1

            # Check game over
            alive = self.alive_players()
            if len(alive) <= 1:
                self.game_over = True
                self.winner = alive[0] if alive else None
            turn_count += 1

        self.log(self._summary())
        return self

    def _summary(self):
        lines = []
        lines.append(f"\n{'#'*60}")
        lines.append(f"  GAME SUMMARY")
        lines.append(f"{'#'*60}")
        if self.winner:
            lines.append(f"Winner: {self.winner.name}!")
        else:
            lines.append(f"Game ended after {self.turn_number} turns (no winner)")

        lines.append(f"\nFinal standings:")
        for p in sorted(self.players, key=lambda p: p.life, reverse=True):
            status = f"life: {p.life}" if p.life > 0 else "ELIMINATED"
            cmdr_turn = self.stats[p.name]['commander_first_cast']
            cmdr_str = f"turn {cmdr_turn}" if cmdr_turn else "never"
            played = len(self.stats[p.name]['cards_played'])
            dmg_dealt = self.stats[p.name]['damage_dealt']
            dmg_taken = self.stats[p.name]['damage_taken']
            lines.append(f"  {p.name}: {status} | cmdr: {cmdr_str} | "
                        f"played: {played} | dealt: {dmg_dealt} | taken: {dmg_taken}")

        lines.append(f"\n{'#'*60}")
        return '\n'.join(lines)


# ==================== AI Backends ====================

def auto_ai(player, state, prompt):
    """Heuristic AI — same logic as auto_pilot.py."""
    prompt_lower = prompt.lower()

    # Main phase: play land, then cast spell
    if 'main' in prompt_lower and 'actions:' in prompt_lower:
        # Try to play a land
        land = pick_land_to_play(player)
        if land:
            return f"play {land['name']}"
        # Try to cast a spell
        spells = pick_spells_to_cast(player, player.commander_tax)
        if spells:
            card = spells[0]
            if card.get('is_commander'):
                return "cast commander"
            return f"cast {card['name']}"
        return "pass"

    # Combat: attack weakest opponent
    if 'combat' in prompt_lower:
        creatures = [perm for perm in player.battlefield
                     if perm.is_creature() and not perm.tapped and not perm.summoning_sick]
        if not creatures:
            return "pass"
        # Find weakest opponent from the prompt
        # Parse opponent names from the prompt
        import re
        opp_matches = re.findall(r'(\w[\w\s]*?)\s*\(life:\s*(\d+)\)', prompt)
        if opp_matches:
            weakest = min(opp_matches, key=lambda x: int(x[1]))
            return f"attack all -> {weakest[0].strip()}"
        return "pass"

    # Discard: highest CMC
    if 'discard' in prompt_lower:
        if player.hand:
            worst = max(player.hand, key=lambda c: c.get('cmc', 0))
            return worst['name']
        return "pass"

    # Priority response: check for instant-speed plays
    if 'priority' in prompt_lower or 'respond' in prompt_lower:
        for c in player.hand:
            tl = c.get('type_line', '')
            if 'Instant' in tl and can_cast(player, c):
                return f"cast {c['name']}"
        return "pass"

    return "pass"


def llm_ai(player, state, prompt, model="haiku"):
    """LLM AI — calls claude CLI for decisions."""
    system_prompt = (
        f"You are playing a Commander game of Magic: The Gathering. "
        f"You are {player.name}. Play strategically to win.\n"
        f"IMPORTANT: Respond with ONLY a single action line. No explanation.\n"
        f"Valid actions: 'play <land name>', 'cast <spell name>', 'cast commander', "
        f"'attack all -> <player name>', '<creature> -> <player>, ...', 'pass', "
        f"or a card name (for discard).\n"
        f"Be concise. One line only."
    )

    full_prompt = f"{state}\n\n{prompt}"

    try:
        result = subprocess.run(
            ['claude', '--print', '-p', full_prompt, '--model', model,
             '--system', system_prompt, '--max-tokens', '100'],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        response = result.stdout.strip()
        # Extract first action line (ignore any extra text)
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('*'):
                return line
        return "pass"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"  [LLM error for {player.name}: {e}]", file=sys.stderr)
        return auto_ai(player, state, prompt)


def make_ai(ai_type, model="haiku"):
    """Create an AI function for the given type."""
    if ai_type == "auto":
        return auto_ai
    elif ai_type == "llm":
        return lambda player, state, prompt: llm_ai(player, state, prompt, model=model)
    else:
        raise ValueError(f"Unknown AI type: {ai_type}")


# ==================== Game Setup ====================

def load_player(decklist_path, name=None, seed=None):
    """Load a deck and create a Player."""
    all_cards, parsed = get_deck_cards(decklist_path)
    cards = [card_from_scryfall(c) for c in all_cards]

    # Get commander name for player name
    commander = None
    library = []
    for c in cards:
        if c.get('is_commander'):
            commander = c
        else:
            library.append(c)

    if name is None:
        name = commander['name'] if commander else os.path.basename(os.path.dirname(decklist_path))

    player = Player(name=name)
    if commander:
        player.command_zone.append(commander)

    rng = random.Random(seed)
    rng.shuffle(library)
    player.library = library

    # Mulligan with deck-specific guide
    deck_dir = os.path.dirname(os.path.abspath(decklist_path))
    guide = parse_mulligan_guide(deck_dir)

    player.draw(7)
    mulligan_count = 0
    for _ in range(2):
        keepable, reason = evaluate_hand_for_mulligan(player.hand, guide=guide)
        if keepable:
            break
        mulligan_count += 1
        player.mulligan()
        rng.shuffle(player.library)
        player.draw(7)

    if mulligan_count > 0 and len(player.hand) > 7 - mulligan_count:
        while len(player.hand) > 7 - mulligan_count:
            worst = max(player.hand, key=lambda c: c.get('cmc', 0))
            player.hand.remove(worst)
            player.library.insert(0, worst)

    print(f"  {name}: hand {len(player.hand)} cards (mulligans: {mulligan_count})", file=sys.stderr)
    return player


# ==================== CLI ====================

def main():
    ap = argparse.ArgumentParser(description='Multiplayer Commander game')
    ap.add_argument('decklists', nargs='+', help='Paths to decklist files (2-4 players)')
    ap.add_argument('--ai', type=str, default='auto', choices=['auto', 'llm'],
                    help='AI backend for all players')
    ap.add_argument('--model', type=str, default='haiku',
                    help='Claude model for LLM mode')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--max-turns', type=int, default=12)
    args = ap.parse_args()

    if len(args.decklists) < 2:
        print("Need at least 2 decks to play", file=sys.stderr)
        sys.exit(1)

    print("Loading decks...", file=sys.stderr)
    players = []
    for i, path in enumerate(args.decklists):
        seed = args.seed + i if args.seed else None
        players.append(load_player(path, seed=seed))

    game = MultiplayerGame(players, seed=args.seed)
    ai_fn = make_ai(args.ai, model=args.model)
    game.run(ai_fn, max_turns=args.max_turns)


if __name__ == '__main__':
    main()
