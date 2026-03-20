#!/usr/bin/env python3
"""Game orchestrator: runs a multiplayer Commander game with state tracking.

Produces turn-by-turn game logs with full state snapshots that can be fed
to LLM subagents for decisions. Handles auto-resolution of simple actions
and flags JUDGE calls for complex interactions.

The orchestrator:
1. Manages the canonical game state (libraries, hands, boards, GYs, life)
2. For each player decision, outputs a STATE SNAPSHOT with oracle text
3. Parses player actions and resolves what it can
4. Flags JUDGE requests when it can't auto-resolve
5. Writes a game log to stdout

Usage:
    python3 game_orchestrator.py decks/ashling/decklist.txt decks/wise_mothman/decklist.txt decks/muldrotha/decklist.txt decks/ureni/decklist.txt --seed 42 --max-turns 12
"""
import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

from card_cache import get_deck_cards
from game_simulator import (
    Player, Permanent,
    card_from_scryfall, make_card,
    get_available_mana, can_cast, tap_mana_for,
    play_land, cast_spell, create_token,
    evaluate_hand_for_mulligan, parse_mulligan_guide,
    _parse_pips, PIP_RE, GENERIC_RE, PERMANENT_TYPES, SPELL_ONLY_TYPES,
)


# ==================== Oracle Text Helpers ====================

def card_summary(card, show_oracle=True):
    """One-line card summary with optional oracle text."""
    name = card['name']
    cost = card.get('mana_cost', '')
    tl = card.get('type_line', '')
    p = card.get('power', 0)
    t = card.get('toughness', 0)
    pt = f" ({p}/{t})" if 'Creature' in tl else ""
    oracle = card.get('oracle_text', '')
    parts = [f"{name}  {cost}  [{tl}]{pt}"]
    if show_oracle and oracle:
        # Compact oracle: first 120 chars
        compact = oracle.replace('\n', ' | ')
        if len(compact) > 120:
            compact = compact[:117] + "..."
        parts.append(f"    Oracle: {compact}")
    return '\n'.join(parts)


def perm_summary(perm):
    """Summary of a permanent on the battlefield."""
    card = perm.card
    name = card['name']
    status = []
    if perm.tapped:
        status.append("tapped")
    if perm.summoning_sick:
        status.append("summoning sick")
    status_str = f" [{', '.join(status)}]" if status else ""
    # Power/toughness with counter info
    pt = ""
    if perm.is_creature():
        if perm.counters.get('+1/+1', 0) > 0:
            pt = f" ({perm.power}/{perm.toughness}, base {perm.base_power}/{perm.base_toughness} +{perm.counters['+1/+1']} counters)"
        elif perm.counters.get('-1/-1', 0) > 0:
            pt = f" ({perm.power}/{perm.toughness}, base {perm.base_power}/{perm.base_toughness} -{perm.counters['-1/-1']} counters)"
        else:
            pt = f" ({perm.power}/{perm.toughness})"
    # Non-+1/+1 counters (loyalty, rad, lore, etc.)
    counter_parts = []
    for ctype, count in perm.counters.items():
        if ctype not in ('+1/+1', '-1/-1') and count > 0:
            counter_parts.append(f"{count} {ctype}")
    counter_str = f" [{', '.join(counter_parts)}]" if counter_parts else ""
    # Granted keywords
    kw_str = ""
    if perm.granted_keywords:
        kw_str = f" {{{', '.join(sorted(perm.granted_keywords))}}}"
    produced = card.get('produced_mana', [])
    mana_str = f" [mana: {','.join(produced)}]" if produced and not perm.is_land() else ""
    return f"{name}{pt}{counter_str}{kw_str}{status_str}{mana_str}"


# ==================== Trigger Detection ====================

def detect_triggers(players, event_type, event_data):
    """Scan permanents for triggers matching an event.

    Returns list of (player, permanent, trigger_description) tuples.
    Events: 'etb', 'ltb', 'landfall', 'cast', 'attack', 'damage', 'draw', 'upkeep'

    event_data can contain:
      'card': the card that entered/left/was cast
      'player': the player who owns the card
      'attacker': the creature that attacked
    """
    triggers = []

    # Self-referential ETB: "when THIS enters" — only fires for the card itself
    # vs "whenever A creature enters" — fires for any creature entering
    SELF_ETB = [r'when this .* enters', r'when .* enters the battlefield\b(?!.*whenever)']
    OTHER_ETB = [r'whenever .* enters', r'whenever a .* enters']

    trigger_patterns = {
        'etb': SELF_ETB + OTHER_ETB,
        'ltb': [r'when .* leaves', r'when .* dies', r'when .* is put into a graveyard', r'whenever .* dies'],
        'landfall': [r'landfall', r'whenever a land .* enters'],
        'cast': [r'whenever .* cast', r'when you cast'],
        'attack': [r'whenever .* attacks', r'when .* attacks'],
        'upkeep': [r'at the beginning of your upkeep', r'at the beginning of each upkeep'],
        'draw': [r'whenever you draw', r'whenever a player draws'],
        'damage': [r'whenever .* deals combat damage', r'whenever .* deals damage'],
    }

    entering_card_name = event_data.get('card', {}).get('name', '').lower() if event_data.get('card') else ''
    attacking_perm_name = event_data.get('attacker', '').lower() if event_data.get('attacker') else ''

    patterns = trigger_patterns.get(event_type, [])
    if not patterns:
        return triggers

    for player in players:
        if player.life <= 0:
            continue
        for perm in player.battlefield:
            oracle = perm.card.get('oracle_text', '').lower()
            perm_name_lower = perm.name.lower()

            for pat in patterns:
                if not re.search(pat, oracle):
                    continue

                # Filter self-referential triggers:
                # "when this land enters" should only fire if THIS permanent just entered
                if event_type == 'etb' and pat in SELF_ETB:
                    # Self-ETB: only if this perm is the one that entered
                    if entering_card_name and perm_name_lower != entering_card_name:
                        continue
                    # If no entering card specified, skip self-ETBs to be safe
                    if not entering_card_name:
                        continue

                # "whenever THIS attacks" — only the attacker triggers
                if event_type == 'attack':
                    # Check if oracle says "whenever [card name] attacks" (self) vs "whenever a creature attacks" (any)
                    if 'whenever a ' not in oracle and 'whenever an ' not in oracle:
                        # Self-referential attack trigger — only fire for the attacking creature
                        if attacking_perm_name and perm_name_lower != attacking_perm_name:
                            continue

                triggers.append((player, perm, oracle))
                break

    return triggers


# ==================== State Snapshot ====================

def format_snapshot(game, viewer, prompt=""):
    """Full state snapshot from a player's perspective with oracle text."""
    lines = []
    lines.append(f"╔══ TURN {game['turn']} — {game['active_player']} — Phase: {game['phase']} ══╗")
    lines.append(f"You are: {viewer['name']} | Life: {viewer['life']}")
    lines.append("")

    # Your hand with full oracle text
    lines.append(f"── YOUR HAND ({len(viewer['hand'])}) ──")
    for i, c in enumerate(sorted(viewer['hand'], key=lambda x: (x.get('cmc', 0), x['name'])), 1):
        castable = ""
        # Simple castability check
        available_mana = viewer.get('available_mana', 0)
        if 'Land' not in c.get('type_line', ''):
            if c.get('cmc', 0) <= available_mana:
                castable = " ★CASTABLE"
        else:
            if viewer.get('land_drops', 0) > 0:
                castable = " ★PLAYABLE"
        lines.append(f"  {i}. {card_summary(c)}{castable}")
    lines.append("")

    # Your mana
    lines.append(f"Available mana: {viewer.get('mana_display', 'none')} (total: {viewer.get('available_mana', 0)})")
    lines.append(f"Land drops remaining: {viewer.get('land_drops', 0)}")
    lines.append("")

    # All battlefields
    for p in game['players']:
        is_you = " (YOU)" if p['name'] == viewer['name'] else ""
        is_active = " ◄ACTIVE" if p['name'] == game['active_player'] else ""
        status = f"life: {p['life']}" if p['life'] > 0 else "ELIMINATED"
        # Show player counters (rad, poison, experience) and commander damage
        pcounters = p.get('player_counters', {})
        cmd_dmg = p.get('commander_damage', {})
        extra_parts = []
        if pcounters:
            extra_parts.extend(f"{v} {k}" for k, v in pcounters.items())
        if cmd_dmg:
            extra_parts.extend(f"{v}/21 cmd dmg from {k}" for k, v in cmd_dmg.items() if v > 0)
        counter_str = f" | {', '.join(extra_parts)}" if extra_parts else ""
        lines.append(f"── {p['name']}{is_you}{is_active} ({status}{counter_str}) ──")

        if p['life'] <= 0:
            lines.append("  (eliminated)")
            continue

        # Battlefield
        if p.get('lands'):
            lines.append(f"  Lands: {', '.join(p['lands'])}")
        if p.get('nonlands'):
            for nl in p['nonlands']:
                lines.append(f"  {nl}")
        if not p.get('lands') and not p.get('nonlands'):
            lines.append("  (empty board)")

        # Hand size (hidden for opponents)
        if p['name'] != viewer['name']:
            lines.append(f"  Hand: {p.get('hand_size', '?')} cards")

        # Graveyard
        if p.get('graveyard'):
            lines.append(f"  Graveyard: {', '.join(p['graveyard'])}")

        # Command zone
        if p.get('command_zone'):
            lines.append(f"  Command zone: {', '.join(p['command_zone'])}")
        lines.append("")

    # Recent events
    if game.get('recent_events'):
        lines.append("── RECENT EVENTS ──")
        for ev in game['recent_events'][-6:]:
            lines.append(f"  {ev}")
        lines.append("")

    # Pending triggers
    if game.get('pending_triggers'):
        lines.append("── PENDING TRIGGERS ──")
        for trig in game['pending_triggers']:
            lines.append(f"  ⚡ {trig}")
        lines.append("")

    if prompt:
        lines.append(f"── ACTION REQUIRED ──")
        lines.append(prompt)
        lines.append("")
        lines.append("Respond with ONE action: play <land>, cast <spell>, cast commander,")
        lines.append("activate <permanent> <ability description>, attack <creature> -> <player>,")
        lines.append("pass, or JUDGE: <question about rules/interactions>")

    return '\n'.join(lines)


# ==================== Game State Manager ====================

class GameEngine:
    """Manages canonical game state for multiplayer Commander."""

    def __init__(self, decklist_paths, seed=None):
        self.rng = random.Random(seed)
        self.players: list[Player] = []
        self.turn = 1
        self.active_idx = 0
        self.phase = "setup"
        self.events: list[str] = []
        self.judge_requests: list[str] = []
        self.game_over = False

        # Load decks
        for i, path in enumerate(decklist_paths):
            player = self._load_deck(path, seed=(seed + i) if seed else None)
            self.players.append(player)

    def _load_deck(self, path, seed=None):
        cards_raw, _ = get_deck_cards(path)
        cards = [card_from_scryfall(c) for c in cards_raw]

        rng = random.Random(seed)
        commander = None
        library = []
        for c in cards:
            if c.get('is_commander'):
                commander = c
            else:
                library.append(c)

        name = commander['name'] if commander else os.path.basename(os.path.dirname(path))
        player = Player(name=name)
        if commander:
            player.command_zone.append(commander)

        rng.shuffle(library)
        player.library = library

        # Mulligan
        deck_dir = os.path.dirname(os.path.abspath(path))
        guide = parse_mulligan_guide(deck_dir)
        player.draw(7)
        mull_count = 0
        for _ in range(2):
            keepable, reason = evaluate_hand_for_mulligan(player.hand, guide=guide)
            if keepable:
                break
            mull_count += 1
            player.mulligan()
            rng.shuffle(player.library)
            player.draw(7)

        if mull_count > 0:
            while len(player.hand) > 7 - mull_count:
                worst = max(player.hand, key=lambda c: c.get('cmc', 0))
                player.hand.remove(worst)
                player.library.insert(0, worst)

        print(f"  Loaded {name}: {len(player.hand)} cards (mulligans: {mull_count})", file=sys.stderr)
        return player

    @property
    def active_player(self):
        return self.players[self.active_idx]

    def alive_players(self):
        return [p for p in self.players if p.life > 0]

    def get_snapshot(self, viewer: Player, prompt=""):
        """Build a snapshot dict for format_snapshot."""
        mana = get_available_mana(viewer)
        mana_parts = []
        for color in ['W', 'U', 'B', 'R', 'G', 'C']:
            if mana.get(color, 0) > 0:
                mana_parts.append(f"{{{color}}}x{mana[color]}")

        game_dict = {
            'turn': self.turn,
            'active_player': self.active_player.name,
            'phase': self.phase,
            'players': [],
            'recent_events': self.events[-8:],
            'pending_triggers': [],
        }

        for p in self.players:
            pd = {
                'name': p.name,
                'life': p.life,
                'hand_size': len(p.hand),
                'lands': [],
                'nonlands': [],
                'graveyard': [c['name'] for c in p.graveyard],
                'command_zone': [c['name'] for c in p.command_zone],
                'player_counters': dict(p.counters) if hasattr(p, 'counters') and p.counters else {},
                'commander_damage': dict(p.commander_damage) if hasattr(p, 'commander_damage') and p.commander_damage else {},
            }
            # Lands
            land_counts = Counter()
            special_lands = []
            for perm in p.battlefield:
                if perm.is_land():
                    if perm.counters or perm.granted_keywords:
                        special_lands.append(perm_summary(perm))
                    else:
                        status = " (tapped)" if perm.tapped else ""
                        land_counts[perm.name + status] += 1
            pd['lands'] = [f"{n}x {name}" if n > 1 else name for name, n in sorted(land_counts.items())]
            pd['lands'].extend(special_lands)

            # Nonlands — show oracle snippet for commanders only (threat assessment without context bloat)
            for perm in sorted(p.battlefield, key=lambda x: x.name):
                if not perm.is_land():
                    summary = perm_summary(perm)
                    if perm.card.get('is_commander') and p is not viewer:
                        oracle = perm.card.get('oracle_text', '')
                        if oracle:
                            summary += f"\n      ⚠ {oracle[:80]}..."
                    pd['nonlands'].append(summary)

            game_dict['players'].append(pd)

        viewer_dict = {
            'name': viewer.name,
            'life': viewer.life,
            'hand': viewer.hand,
            'available_mana': mana.get('total', 0),
            'mana_display': ', '.join(mana_parts) if mana_parts else 'none',
            'land_drops': viewer.land_drops_remaining,
        }

        return format_snapshot(game_dict, viewer_dict, prompt)

    def resolve_action(self, player, action):
        """Parse and resolve a player action. Returns (success, message, judge_needed)."""
        action = action.strip()
        action_lower = action.lower()

        # JUDGE call
        if action_lower.startswith("judge:"):
            question = action[6:].strip()
            self.judge_requests.append(f"{player.name}: {question}")
            return True, f"JUDGE CALLED: {question}", True

        # Pass
        if action_lower == "pass":
            return True, "passes", False

        # Play land
        if action_lower.startswith("play "):
            card_name = action[5:].strip()
            card = self._find_in_hand(player, card_name)
            if not card:
                return False, f"'{card_name}' not in hand", False
            if 'Land' not in card.get('type_line', ''):
                return False, f"'{card_name}' is not a land", False
            if play_land(player, card):
                self.events.append(f"{player.name} plays {card['name']}")
                # Check landfall triggers
                triggers = detect_triggers(
                    self.players,
                    'landfall',
                    {'card': card, 'player': player}
                )
                trigger_msgs = []
                for tp, perm, oracle in triggers:
                    trigger_msgs.append(f"⚡ TRIGGER: {tp.name}'s {perm.name} — landfall")
                return True, f"plays {card['name']}" + ("\n" + "\n".join(trigger_msgs) if trigger_msgs else ""), False
            return False, "cannot play land (no land drops remaining)", False

        # Cast spell
        if action_lower.startswith("cast "):
            card_name = action[5:].strip()

            # Commander
            if card_name.lower() == "commander":
                if not player.command_zone:
                    return False, "no commander in command zone", False
                card = player.command_zone[0]
                if cast_spell(player, card, commander_tax=player.commander_tax):
                    self.events.append(f"{player.name} casts {card['name']} from command zone!")
                    player.commander_tax += 2
                    # Check ETB triggers
                    triggers = detect_triggers(
                        self.players, 'etb', {'card': card, 'player': player})
                    trigger_msgs = []
                    for tp, perm, oracle in triggers:
                        trigger_msgs.append(f"⚡ TRIGGER: {tp.name}'s {perm.name} — ETB")
                    return True, f"casts {card['name']} from command zone (tax now {player.commander_tax})" + (
                        "\n" + "\n".join(trigger_msgs) if trigger_msgs else ""), False
                return False, f"cannot cast commander (need {card['cmc'] + player.commander_tax} mana)", False

            card = self._find_in_hand(player, card_name)
            if not card:
                return False, f"'{card_name}' not in hand", False
            if cast_spell(player, card):
                self.events.append(f"{player.name} casts {card['name']}")
                # Check ETB triggers for permanents
                type_line = card.get('type_line', '')
                if any(t in type_line for t in PERMANENT_TYPES) and 'Instant' not in type_line and 'Sorcery' not in type_line:
                    triggers = detect_triggers(
                        self.players, 'etb', {'card': card, 'player': player})
                    trigger_msgs = []
                    for tp, perm, oracle in triggers:
                        trigger_msgs.append(f"⚡ TRIGGER: {tp.name}'s {perm.name} — ETB")
                    if trigger_msgs:
                        return True, f"casts {card['name']}\n" + "\n".join(trigger_msgs), False
                return True, f"casts {card['name']}", False
            return False, f"cannot cast {card['name']} (not enough mana)", False

        # Activate ability
        if action_lower.startswith("activate "):
            perm_name = action[9:].strip()
            perm = self._find_permanent(player, perm_name)
            if not perm:
                return False, f"'{perm_name}' not on your battlefield", False
            oracle = perm.card.get('oracle_text', '').lower()

            # Sacrifice abilities (Seal of Doom, Spore Frog, etc.)
            if 'sacrifice' in oracle:
                player.battlefield.remove(perm)
                player.graveyard.append(perm.card)
                self.events.append(f"{player.name} activates {perm.name} (sacrifice)")
                return True, f"activates {perm.name} (sacrificed)", False

            # Tap abilities
            if '{t}' in oracle and not perm.tapped:
                perm.tapped = True
                self.events.append(f"{player.name} activates {perm.name} (tap)")
                return True, f"activates {perm.name} (tapped)", False

            return False, f"can't activate {perm.name}", False

        # Equip
        if action_lower.startswith("equip "):
            # "equip Equipment -> Creature"
            if '->' in action:
                eq_name, cr_name = action[6:].split('->', 1)
                eq_name = eq_name.strip()
                cr_name = cr_name.strip()
                equip = self._find_permanent(player, eq_name)
                creature = self._find_permanent(player, cr_name)
                if equip and creature and creature.is_creature():
                    # Grant keywords from oracle text
                    oracle = equip.card.get('oracle_text', '').lower()
                    granted = []
                    for kw in ['hexproof', 'shroud', 'haste', 'trample', 'flying', 'vigilance',
                               'lifelink', 'deathtouch', 'first strike', 'double strike', 'menace',
                               'indestructible', 'reach', 'ward']:
                        if kw in oracle:
                            creature.granted_keywords.add(kw)
                            granted.append(kw)
                    self.events.append(f"{player.name} equips {equip.name} to {creature.name} ({', '.join(granted) or 'attached'})")
                    return True, f"equips {equip.name} to {creature.name} ({', '.join(granted) or 'attached'})", False
                return False, f"can't equip: equipment or creature not found", False
            return False, "equip format: equip Equipment -> Creature", False

        # Attack
        if action_lower.startswith("attack "):
            return self._resolve_attack(player, action)

        return False, f"unknown action: {action}", False

    def _resolve_attack(self, attacker, action):
        """Resolve attack declarations."""
        action_lower = action.lower()
        attacks = []

        if "attack all" in action_lower:
            target_name = action_lower.split("->")[-1].strip() if "->" in action_lower else ""
            target = self._find_player(target_name)
            if not target or target.life <= 0 or target is attacker:
                return False, "invalid attack target", False
            for perm in attacker.battlefield:
                if perm.is_creature() and not perm.tapped and not perm.summoning_sick:
                    attacks.append((perm, target))
        else:
            parts = action.split(",")
            for part in parts:
                if "->" not in part:
                    continue
                cname, tname = part.split("->", 1)
                cname = cname.strip().replace("attack ", "").strip()
                tname = tname.strip()
                perm = self._find_permanent(attacker, cname)
                target = self._find_player(tname)
                if perm and target and target.life > 0:
                    attacks.append((perm, target))

        if not attacks:
            return False, "no valid attacks", False

        # Phase 1: Declare attackers — tap them, store pending attacks
        # Damage is NOT applied yet — defenders get to block first
        attacker_info = []
        for perm, target in attacks:
            if perm.tapped or perm.summoning_sick or not perm.is_creature():
                continue
            perm.tapped = True
            attacker_info.append({
                'creature': perm.name,
                'power': perm.power,
                'toughness': perm.toughness,
                'target': target.name,
                'keywords': sorted(perm.all_keywords),
                'is_commander': bool(perm.card.get('is_commander')),
            })

        if not attacker_info:
            return False, "no valid attackers (all tapped or summoning sick)", False

        # Store pending combat for resolution after blocks
        self.pending_combat = {
            'attacker': attacker.name,
            'attacks': attacker_info,
            'blocks': [],  # filled by block declarations
        }

        targets_str = ", ".join(f"{a['creature']}({a['power']}/{a['toughness']}) → {a['target']}" for a in attacker_info)
        total_by_target = Counter()
        for a in attacker_info:
            total_by_target[a['target']] += a['power']
        summary = ", ".join(f"{dmg} to {name}" for name, dmg in total_by_target.items())
        msg = f"declares attackers: {summary} (defenders may block)"
        self.events.append(f"{attacker.name} {msg}")

        return True, msg, False

    def resolve_combat(self):
        """Resolve pending combat after blocks are declared. Called by the server."""
        if not hasattr(self, 'pending_combat') or not self.pending_combat:
            return False, "no pending combat"

        combat = self.pending_combat
        blocks = combat.get('blocks', [])
        attacker_player = self._find_player(combat['attacker'])

        # Build block mapping: attacker_creature -> list of blockers
        blocked_by = {}  # creature_name -> [(blocker_name, blocker_power, blocker_toughness)]
        for block in blocks:
            att_name = block['attacker']
            if att_name not in blocked_by:
                blocked_by[att_name] = []
            blocked_by[att_name].append(block)

        total_dmg = 0
        damage_report = Counter()
        killed_creatures = []

        for attack in combat['attacks']:
            creature_name = attack['creature']
            target_name = attack['target']
            power = attack['power']
            target = self._find_player(target_name)

            if creature_name in blocked_by:
                # Creature is blocked — damage goes to blockers, not player
                blockers = blocked_by[creature_name]
                remaining_dmg = power
                for b in blockers:
                    # Attacker damages blocker
                    if remaining_dmg > 0:
                        self.events.append(f"  ↪ {creature_name} ({power}) blocked by {b['blocker']} ({b['blocker_power']}/{b['blocker_toughness']})")
                        # Check if blocker dies (damage >= toughness)
                        if remaining_dmg >= b['blocker_toughness']:
                            killed_creatures.append({'name': b['blocker'], 'owner': b['blocker_owner']})
                        remaining_dmg -= b['blocker_toughness']
                    # Blocker damages attacker
                    if b['blocker_power'] >= attack['toughness']:
                        killed_creatures.append({'name': creature_name, 'owner': combat['attacker']})

                # Trample: excess damage goes to player
                has_trample = 'trample' in attack.get('keywords', [])
                if has_trample and remaining_dmg > 0 and target:
                    target.life -= remaining_dmg
                    damage_report[target_name] += remaining_dmg
                    self.events.append(f"  ↪ {creature_name} tramples {remaining_dmg} to {target_name}")
            else:
                # Unblocked — all damage to player
                if power > 0 and target:
                    target.life -= power
                    total_dmg += power
                    damage_report[target_name] += power
                    # Track commander damage
                    if attack.get('is_commander'):
                        cmdr_name = creature_name
                        if not hasattr(target, 'commander_damage'):
                            target.commander_damage = {}
                        target.commander_damage[cmdr_name] = target.commander_damage.get(cmdr_name, 0) + power

        # Report damage
        if damage_report:
            parts = [f"{dmg} to {name}" for name, dmg in damage_report.items()]
            self.events.append(f"Combat damage: {', '.join(parts)}")

        # Report commander damage totals
        for attack in combat['attacks']:
            if attack.get('is_commander'):
                target = self._find_player(attack['target'])
                if target and hasattr(target, 'commander_damage'):
                    cmdr_total = target.commander_damage.get(attack['creature'], 0)
                    if cmdr_total > 0:
                        self.events.append(f"  ⚔ Commander damage: {attack['creature']} → {target.name}: {cmdr_total}/21")

        # Report killed creatures
        for kill in killed_creatures:
            self.events.append(f"  ☠ {kill['name']} dies in combat")

        # Check for player eliminations (life or commander damage)
        msg_parts = []
        for name in damage_report:
            p = self._find_player(name)
            if not p:
                continue
            eliminated = False
            if p.life <= 0:
                eliminated = True
                msg_parts.append(f"☠ {name} is ELIMINATED! (life)")
            elif hasattr(p, 'commander_damage'):
                for cmdr, dmg in p.commander_damage.items():
                    if dmg >= 21:
                        eliminated = True
                        msg_parts.append(f"☠ {name} is ELIMINATED! (21 commander damage from {cmdr})")
                        break
            if eliminated:
                self.events.append(f"{name} eliminated in combat!")

        self.pending_combat = None

        result_msg = f"Combat resolved: {', '.join(f'{d} to {n}' for n, d in damage_report.items())}"
        if msg_parts:
            result_msg += "\n" + "\n".join(msg_parts)
        if killed_creatures:
            result_msg += f"\nCreatures killed: {', '.join(k['name'] for k in killed_creatures)}"

        return True, result_msg, killed_creatures

    def has_instant_speed(self, player):
        """Check if player has any instant-speed options available.

        Checks: instants/flash in hand, activated abilities on untapped permanents,
        sacrifice abilities on permanents (Seal of Doom, Spore Frog, etc.)
        """
        # Instants and flash creatures in hand
        for c in player.hand:
            tl = c.get('type_line', '')
            kw = c.get('keywords', [])
            if ('Instant' in tl or 'Flash' in kw) and can_cast(player, c):
                return True

        # Activated abilities on untapped permanents (skip pure mana sources)
        for perm in player.battlefield:
            if perm.tapped:
                continue
            if perm.is_land():
                continue
            oracle = perm.card.get('oracle_text', '').lower()
            produced = perm.card.get('produced_mana', [])

            # Skip pure mana rocks/dorks (cards whose only ability is producing mana)
            if produced and not any(kw in oracle for kw in ['destroy', 'exile', 'damage',
                    'counter', 'return', 'tap target', 'prevent', 'each opponent',
                    'sacrifice .* destroy', 'sacrifice .* prevent', 'sacrifice .* return']):
                continue

            # Tap abilities with interaction effects
            if '{t}' in oracle:
                if any(kw in oracle for kw in ['destroy', 'exile', 'damage to',
                       'tap target', 'prevent all combat']):
                    return True
            # Sacrifice abilities with effects (Seal of Doom, Spore Frog, etc.)
            if 'sacrifice' in oracle and ':' in oracle:
                if any(kw in oracle for kw in ['destroy target', 'prevent all combat',
                       'each opponent loses', 'deals damage']):
                    return True

        return False

    def get_priority_responses(self, casting_player, spell_description, respond_fn):
        """Give each opponent a chance to respond to a spell/action.

        respond_fn(player, event_description) -> action string or 'pass'
        Returns list of (player, action, result) for any responses.
        """
        responses = []
        idx = self.players.index(casting_player)
        for i in range(1, len(self.players)):
            opp_idx = (idx + i) % len(self.players)
            opp = self.players[opp_idx]
            if opp.life <= 0 or opp is casting_player:
                continue
            if not self.has_instant_speed(opp):
                continue
            action = respond_fn(opp, spell_description)
            if action and action.strip().lower() != 'pass':
                ok, msg, judge = self.resolve_action(opp, action)
                if ok:
                    self.events.append(f"  ↪ {opp.name} responds: {msg}")
                    responses.append((opp, action, msg))
        return responses

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
            if p.name.lower() == name_lower or name_lower in p.name.lower():
                return p
        return None

    def _find_permanent(self, player, name):
        name_lower = name.lower()
        for perm in player.battlefield:
            if perm.name.lower() == name_lower or name_lower in perm.name.lower():
                return perm
        return None

    def begin_turn(self):
        """Start a new turn for the active player."""
        player = self.active_player
        if player.life <= 0:
            self.advance_turn()
            return None

        # Untap (skip first turn of game)
        if self.turn > 1 or self.active_idx > 0:
            player.untap_all()
        player.reset_land_drops()

        # Draw (Commander: everyone draws, including first player turn 1)
        drew = None
        player.draw()
        if player.hand:
            drew = player.hand[-1]
        if player.life <= 0:
            self.events.append(f"{player.name} draws from empty library and loses!")
            return None

        self.phase = "main1"
        self.events.append(f"--- Turn {self.turn}: {player.name} ---")
        return drew

    def advance_turn(self):
        """Move to next player, increment turn if wrapped around."""
        self.active_idx = (self.active_idx + 1) % len(self.players)
        # Skip dead players
        attempts = 0
        while self.players[self.active_idx].life <= 0 and attempts < len(self.players):
            self.active_idx = (self.active_idx + 1) % len(self.players)
            attempts += 1

        if self.active_idx == 0:
            self.turn += 1

        # Check game over
        alive = self.alive_players()
        if len(alive) <= 1:
            self.game_over = True

    def get_game_summary(self):
        """Final game summary."""
        lines = []
        lines.append(f"\n{'#'*60}")
        lines.append(f"  GAME OVER — Turn {self.turn}")
        lines.append(f"{'#'*60}")
        alive = self.alive_players()
        if alive:
            lines.append(f"Winner: {alive[0].name}!")
        else:
            lines.append("No winner (draw)")

        lines.append("\nFinal standings:")
        for p in sorted(self.players, key=lambda p: p.life, reverse=True):
            status = f"life: {p.life}" if p.life > 0 else "ELIMINATED"
            bf_count = len(p.battlefield)
            lines.append(f"  {p.name}: {status} | board: {bf_count} permanents")

        if self.judge_requests:
            lines.append(f"\nJudge calls ({len(self.judge_requests)}):")
            for jr in self.judge_requests:
                lines.append(f"  {jr}")

        return '\n'.join(lines)


# ==================== CLI ====================

def main():
    ap = argparse.ArgumentParser(description='Game orchestrator for LLM multiplayer Commander')
    ap.add_argument('decklists', nargs='+', help='Paths to decklist files')
    ap.add_argument('--seed', type=int, default=None, help='Random seed (default: random)')
    ap.add_argument('--max-turns', type=int, default=12)
    ap.add_argument('--auto', action='store_true', help='Run with auto-pilot (no LLM)')
    ap.add_argument('--verbose', '-v', action='store_true', help='Show triggers and detailed output')
    args = ap.parse_args()

    if args.seed is None:
        args.seed = random.randint(1, 99999)
    print(f"Seed: {args.seed}", file=sys.stderr)
    print("Loading decks...", file=sys.stderr)
    engine = GameEngine(args.decklists, seed=args.seed)

    print(f"\nPlayers:", file=sys.stderr)
    for p in engine.players:
        cmdr = p.command_zone[0]['name'] if p.command_zone else "none"
        print(f"  {p.name} ({cmdr}) — hand: {len(p.hand)}", file=sys.stderr)

    if args.auto:
        from auto_pilot import pick_land_to_play, pick_spells_to_cast

        def auto_respond(responder, event_description):
            """Auto-pilot instant-speed response: cast instants or use activated abilities."""
            # Check instants in hand first
            for c in responder.hand:
                tl = c.get('type_line', '')
                kw = c.get('keywords', [])
                if ('Instant' in tl or 'Flash' in kw) and can_cast(responder, c):
                    oracle = c.get('oracle_text', '').lower()
                    if any(kw in oracle for kw in ['destroy', 'exile', 'counter', 'damage',
                                                     'return target', 'shuffle target']):
                        return f"cast {c['name']}"

            # Check activated abilities on untapped non-land, non-mana-only permanents
            for perm in responder.battlefield:
                if perm.tapped or perm.is_land():
                    continue
                oracle = perm.card.get('oracle_text', '').lower()
                produced = perm.card.get('produced_mana', [])
                # Skip pure mana sources
                if produced and 'destroy' not in oracle and 'prevent' not in oracle and 'damage' not in oracle:
                    continue
                # Sacrifice-based removal (Seal of Doom, Spore Frog, etc.)
                if 'sacrifice' in oracle and any(kw in oracle for kw in
                        ['destroy target', 'prevent all combat', 'each opponent loses']):
                    return f"activate {perm.name}"
                # Tap abilities with real effects (Goldmeadow Harrier, Brion fling, etc.)
                if '{t}' in oracle and any(kw in oracle for kw in
                        ['tap target', 'deals damage', 'destroy target']):
                    return f"activate {perm.name}"

            return "pass"

        while engine.turn <= args.max_turns and not engine.game_over:
            drew = engine.begin_turn()
            player = engine.active_player
            if player.life <= 0:
                engine.advance_turn()
                continue

            actions = []

            # Main 1: play land + cast spells
            engine.phase = "main1"
            land = pick_land_to_play(player)
            if land:
                ok, msg, _ = engine.resolve_action(player, f"play {land['name']}")
                if ok:
                    actions.append(msg)

            for _ in range(5):
                spells = pick_spells_to_cast(player, player.commander_tax)
                if not spells:
                    break
                card = spells[0]
                if card.get('is_commander'):
                    ok, msg, _ = engine.resolve_action(player, "cast commander")
                else:
                    ok, msg, _ = engine.resolve_action(player, f"cast {card['name']}")
                if not ok:
                    break
                # Strip trigger noise unless verbose
                msg_clean = msg.split('\n')[0] if not args.verbose else msg
                actions.append(msg_clean)

                # Priority: opponents can respond to spells
                responses = engine.get_priority_responses(
                    player, f"{player.name} {msg_clean}", auto_respond)
                for opp, act, resp_msg in responses:
                    resp_clean = resp_msg.split('\n')[0] if not args.verbose else resp_msg
                    actions.append(f"↪{opp.name[:8]} responds: {resp_clean}")

            # Combat: attack weakest
            engine.phase = "combat"
            creatures = [perm for perm in player.battlefield if perm.is_creature() and not perm.tapped and not perm.summoning_sick]
            if creatures:
                opponents = [op for op in engine.players if op is not player and op.life > 0]
                if opponents:
                    target = min(opponents, key=lambda o: o.life)
                    ok, msg, _ = engine.resolve_action(player, f"attack all -> {target.name}")
                    if ok:
                        actions.append(msg)

                    # Priority after attackers declared: opponents can respond
                    if ok:
                        responses = engine.get_priority_responses(
                            player, f"{player.name} attacks", auto_respond)
                        for opp, act, resp_msg in responses:
                            resp_clean = resp_msg.split('\n')[0] if not args.verbose else resp_msg
                            actions.append(f"↪{opp.name[:8]} responds: {resp_clean}")

            # Discard
            while len(player.hand) > 7:
                worst = max(player.hand, key=lambda c: c.get('cmc', 0))
                player.hand.remove(worst)
                player.graveyard.append(worst)

            # Compact output: one line per player turn
            if actions:
                statuses = ' | '.join(f'{op.name[:10]}:{op.life}' for op in engine.players)
                action_str = ' → '.join(actions)
                print(f"T{engine.turn} {player.name[:15]:15s} {action_str}  [{statuses}]")

            for op in engine.players:
                if op.life <= 0 and op.life > -999:
                    print(f"  *** {op.name} ELIMINATED! ***")
                    op.life = -999

            alive = [op for op in engine.players if op.life > 0]
            if len(alive) <= 1:
                engine.game_over = True

            engine.advance_turn()

        print(engine.get_game_summary())
    else:
        # Interactive mode: print snapshots for each player's turn
        while engine.turn <= args.max_turns and not engine.game_over:
            drew = engine.begin_turn()
            player = engine.active_player
            if player.life <= 0:
                engine.advance_turn()
                continue

            draw_msg = f"You drew: {card_summary(drew, show_oracle=True)}" if drew else "No draw (first turn)"
            engine.phase = "main1"

            # Print the snapshot — this is what gets sent to the LLM agent
            snapshot = engine.get_snapshot(player, prompt=f"{draw_msg}\n\nMain Phase 1 — what do you do?")
            print(snapshot)
            print("---AWAITING_ACTION---")

            # Read action from stdin
            try:
                action = input().strip()
            except EOFError:
                break

            ok, msg, judge = engine.resolve_action(player, action)
            print(f">> {player.name}: {msg}")

            if judge:
                print(f">>> JUDGE NEEDED: {engine.judge_requests[-1]}")
                print("---AWAITING_JUDGE---")
                try:
                    resolution = input().strip()
                    print(f">> Judge rules: {resolution}")
                    engine.events.append(f"Judge: {resolution}")
                except EOFError:
                    break

            engine.advance_turn()

        print(engine.get_game_summary())


if __name__ == '__main__':
    main()
