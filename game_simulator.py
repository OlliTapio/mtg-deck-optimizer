#!/usr/bin/env python3
"""Commander game simulator engine.

Manages game state (zones, mana, combat, life) and communicates via stdin/stdout
so a Claude subagent (or human) can pilot a deck against 3 simulated opponents.

Usage:
    python3 game_simulator.py decks/<deck>/decklist.txt [--opponents aggro,midrange,control] [--seed 42] [--max-turns 15]
"""
import argparse
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ==================== Data Structures ====================

PIP_RE = re.compile(r'\{([WUBRGC])\}')
HYBRID_RE = re.compile(r'\{([WUBRG])/([WUBRG])\}')
GENERIC_RE = re.compile(r'\{(\d+)\}')

PERMANENT_TYPES = {'Creature', 'Artifact', 'Enchantment', 'Planeswalker', 'Land', 'Battle'}
SPELL_ONLY_TYPES = {'Instant', 'Sorcery'}


def make_card(name, cmc=0, mana_cost="", type_line="", oracle_text="",
              power=0, toughness=0, produced_mana=None, keywords=None,
              is_commander=False):
    """Create a card dict matching the structure used by the rest of the project."""
    return {
        'name': name,
        'cmc': cmc,
        'mana_cost': mana_cost,
        'type_line': type_line,
        'oracle_text': oracle_text or "",
        'power': power,
        'toughness': toughness,
        'produced_mana': produced_mana or [],
        'keywords': keywords or [],
        'is_commander': is_commander,
    }


def make_land(name, produced_mana=None):
    return make_card(name, type_line="Land", produced_mana=produced_mana or [])


def make_spell(name, cmc=0, mana_cost="", type_line="", oracle_text="",
               power=0, toughness=0, produced_mana=None, keywords=None,
               is_commander=False):
    return make_card(name, cmc=cmc, mana_cost=mana_cost, type_line=type_line,
                     oracle_text=oracle_text, power=power, toughness=toughness,
                     produced_mana=produced_mana, keywords=keywords,
                     is_commander=is_commander)


def card_from_scryfall(card_entry):
    """Convert a card dict with scryfall data into our simplified card format."""
    sf = card_entry.get('scryfall') or {}

    # Handle double-faced cards
    if 'card_faces' in sf:
        front = sf['card_faces'][0]
        type_line = front.get('type_line', sf.get('type_line', ''))
        oracle_text = front.get('oracle_text', '')
        mana_cost = front.get('mana_cost', '')
        power = front.get('power', '0')
        toughness = front.get('toughness', '0')
    else:
        type_line = sf.get('type_line', '')
        oracle_text = sf.get('oracle_text', '')
        mana_cost = sf.get('mana_cost', '')
        power = sf.get('power', '0')
        toughness = sf.get('toughness', '0')

    try:
        power_int = int(power)
    except (ValueError, TypeError):
        power_int = 0
    try:
        toughness_int = int(toughness)
    except (ValueError, TypeError):
        toughness_int = 0

    is_cmdr = any('Commander' in t for t in card_entry.get('tags', []))

    return make_card(
        name=card_entry['name'],
        cmc=sf.get('cmc', 0),
        mana_cost=mana_cost,
        type_line=type_line,
        oracle_text=oracle_text,
        power=power_int,
        toughness=toughness_int,
        produced_mana=sf.get('produced_mana', []),
        keywords=sf.get('keywords', []),
        is_commander=is_cmdr,
    )


@dataclass
class Permanent:
    card: dict
    tapped: bool = False
    summoning_sick: bool = False
    counters: dict = field(default_factory=dict)

    @property
    def name(self):
        return self.card['name']

    @property
    def power(self):
        return self.card.get('power', 0)

    @property
    def toughness(self):
        return self.card.get('toughness', 0)

    def is_creature(self):
        return 'Creature' in self.card.get('type_line', '')

    def is_land(self):
        return 'Land' in self.card.get('type_line', '')

    def can_produce_mana(self):
        return bool(self.card.get('produced_mana'))

    def is_permanent_type(self):
        tl = self.card.get('type_line', '')
        return any(t in tl for t in PERMANENT_TYPES)


class Player:
    def __init__(self, name="Player", life=40):
        self.name = name
        self.life = life
        self.hand: list[dict] = []
        self.library: list[dict] = []
        self.battlefield: list[Permanent] = []
        self.graveyard: list[dict] = []
        self.exile: list[dict] = []
        self.command_zone: list[dict] = []
        self.commander_tax: int = 0
        self.land_drops_remaining: int = 1

    def draw(self, n=1):
        for _ in range(n):
            if not self.library:
                self.life = -1  # lose from empty library
                return
            card = self.library.pop()
            self.hand.append(card)

    def untap_all(self):
        for perm in self.battlefield:
            perm.tapped = False
            perm.summoning_sick = False

    def reset_land_drops(self):
        self.land_drops_remaining = 1

    def mulligan(self):
        """Shuffle hand back into library and draw 7 new cards."""
        self.library.extend(self.hand)
        self.hand.clear()
        # Re-shuffle (caller should use a seeded rng for reproducibility)
        return self  # caller shuffles and draws


@dataclass
class MulliganGuide:
    """Deck-specific mulligan rules parsed from CLAUDE.md."""
    required_colors: list = field(default_factory=list)  # e.g. ['R', 'G', 'W']
    min_lands: int = 2
    max_lands: int = 5
    early_play_cmc: int = 3  # max CMC to count as "early play"
    needs_ramp: bool = False  # deck with high-CMC commander needs ramp
    needs_green: bool = False  # green is primary ramp color


# Map color words to symbols
_COLOR_WORD_MAP = {
    'white': 'W', 'plains': 'W',
    'blue': 'U', 'island': 'U',
    'black': 'B', 'swamp': 'B',
    'red': 'R', 'mountain': 'R',
    'green': 'G', 'forest': 'G',
}


def parse_mulligan_guide(deck_dir):
    """Parse mulligan rules from a deck's CLAUDE.md.

    Extracts required colors, land thresholds, and ramp needs from the
    mulligan strategy section.
    """
    import os
    claude_path = os.path.join(deck_dir, 'CLAUDE.md')
    if not os.path.exists(claude_path):
        return MulliganGuide()

    with open(claude_path) as f:
        content = f.read()

    guide = MulliganGuide()

    # Extract commander cost to determine required colors
    # Look for patterns like "costs {2}{R}{W}" or "{1}{B}{G}{U}"
    cost_match = re.search(r'costs?\s+(\{[^.]+?\}(?:\s*(?:minus|—))?)', content)
    if cost_match:
        cost_str = cost_match.group(1)
        for m in PIP_RE.finditer(cost_str):
            color = m.group(1)
            if color != 'C' and color not in guide.required_colors:
                guide.required_colors.append(color)

    # Check for "no green sources" or "green is primary" patterns
    mulligan_section = ""
    in_mulligan = False
    for line in content.split('\n'):
        if '## Mulligan' in line:
            in_mulligan = True
            continue
        if in_mulligan and line.startswith('## ') and 'Mulligan' not in line:
            break
        if in_mulligan:
            mulligan_section += line + '\n'

    mulligan_lower = mulligan_section.lower()

    # Detect "no X sources" requirements
    for color_word, symbol in _COLOR_WORD_MAP.items():
        if f'no {color_word} source' in mulligan_lower or f'no {color_word}' in mulligan_lower:
            if symbol not in guide.required_colors:
                guide.required_colors.append(symbol)

    # Check if deck emphasizes green as essential
    if 'green is the primary' in mulligan_lower or 'green is primary' in mulligan_lower:
        guide.needs_green = True
    if 'no green' in mulligan_lower:
        guide.needs_green = True

    # Check if high-CMC commander means ramp is essential
    if 'ramp' in mulligan_lower and ('auto-keep' in mulligan_lower or 'strong keep' in mulligan_lower):
        guide.needs_ramp = True

    # Check for "all high-CMC" or "all 4+" or "all top-end" mulligan triggers
    if 'all 4+' in mulligan_lower or 'all high-cmc' in mulligan_lower or 'all top-end' in mulligan_lower:
        guide.early_play_cmc = 3
    if 'all 5+' in mulligan_lower:
        guide.early_play_cmc = 4

    return guide


def _land_produces_color(card, color):
    """Check if a land/mana source can produce a specific color."""
    produced = card.get('produced_mana', [])
    return color in produced


def evaluate_hand_for_mulligan(hand, guide=None):
    """Evaluate whether a 7-card hand is keepable using deck-specific rules.

    Returns (keepable: bool, reason: str).
    """
    if guide is None:
        guide = MulliganGuide()

    lands = [c for c in hand if 'Land' in c.get('type_line', '')]
    nonlands = [c for c in hand if c not in lands]
    # Include non-land mana sources (mana dorks, rocks)
    mana_sources = lands + [c for c in nonlands if c.get('produced_mana')]
    land_count = len(lands)

    # Hard fails
    if land_count <= 1:
        return False, f"too few lands ({land_count})"
    if land_count >= 6:
        return False, f"too many lands ({land_count})"

    # Check required colors — need at least one source for each
    available_colors = set()
    for src in mana_sources:
        for color in src.get('produced_mana', []):
            available_colors.add(color)

    missing_colors = [c for c in guide.required_colors if c not in available_colors]
    if missing_colors:
        # Allow keeping if we have 2+ of the required colors and a fixer
        any_color_sources = [s for s in mana_sources
                             if len(s.get('produced_mana', [])) >= 3]
        if not any_color_sources:
            color_names = {'W': 'white', 'U': 'blue', 'B': 'black', 'R': 'red', 'G': 'green'}
            missing_names = [color_names.get(c, c) for c in missing_colors]
            return False, f"missing colors: {', '.join(missing_names)}"

    # Green requirement for ramp-dependent decks
    if guide.needs_green and 'G' not in available_colors:
        return False, "no green source (deck needs green for ramp)"

    # Early plays check
    early_plays = [c for c in nonlands if c.get('cmc', 0) <= guide.early_play_cmc]
    if not early_plays and land_count < 4:
        return False, f"no early plays (CMC ≤{guide.early_play_cmc}) and fewer than 4 lands"

    # Ramp check for high-CMC commander decks
    ramp_patterns = ['add', 'search your library for a', 'mana']
    has_ramp = any(
        c.get('produced_mana') or
        any(p in c.get('oracle_text', '').lower() for p in ramp_patterns)
        for c in nonlands if c.get('cmc', 0) <= 3
    )
    if guide.needs_ramp and not has_ramp and land_count < 4:
        return False, "no ramp and fewer than 4 lands (high-CMC commander)"

    return True, f"{land_count} lands, {len(early_plays)} early plays, colors: {sorted(available_colors)}"


class Opponent:
    """Simulated opponent with archetype-based behavior."""

    ARCHETYPE_CONFIG = {
        'aggro': {
            'power_growth': 1.5, 'max_board_power': 20, 'attack_chance': 0.85,
            'removal_chance': 0.10, 'counter_chance': 0.0, 'evasion_base': 0.15,
            'combo_turn': None,
        },
        'midrange': {
            'power_growth': 1.2, 'max_board_power': 25, 'attack_chance': 0.65,
            'removal_chance': 0.20, 'counter_chance': 0.05, 'evasion_base': 0.1,
            'combo_turn': None,
        },
        'control': {
            'power_growth': 0.7, 'max_board_power': 18, 'attack_chance': 0.3,
            'removal_chance': 0.30, 'counter_chance': 0.25, 'evasion_base': 0.05,
            'combo_turn': None,
        },
        'combo': {
            'power_growth': 0.5, 'max_board_power': 12, 'attack_chance': 0.2,
            'removal_chance': 0.15, 'counter_chance': 0.1, 'evasion_base': 0.0,
            'combo_turn': 8,
        },
    }

    def __init__(self, name, archetype, life=40):
        self.name = name
        self.archetype = archetype
        self.life = life
        self.board_power = 0
        self.mana_available = 0
        self.eliminated = False
        cfg = self.ARCHETYPE_CONFIG.get(archetype, self.ARCHETYPE_CONFIG['midrange'])
        self.power_growth = cfg['power_growth']
        self.max_board_power = cfg['max_board_power']
        self.attack_chance = cfg['attack_chance']
        self.removal_chance = cfg['removal_chance']
        self.counter_chance = cfg['counter_chance']
        self.evasion_base = cfg['evasion_base']
        self.combo_turn = cfg['combo_turn']
        self.combo_attempted = False

    def should_attempt_combo(self, turn_number):
        if self.combo_turn is None:
            return False
        return turn_number >= self.combo_turn and not self.combo_attempted

    def apply_removal(self, spell_cmc):
        """AI's removal reduces opponent's board power."""
        reduction = max(1, spell_cmc)
        self.board_power = max(0, self.board_power - reduction)

    def take_damage(self, amount):
        self.life -= amount
        if self.life <= 0:
            self.eliminated = True


@dataclass
class GameState:
    player: Player
    opponents: list
    turn_number: int = 1
    phase: str = "main1"
    game_log: list = field(default_factory=list)
    game_over: bool = False
    winner: str = ""
    cards_played: list = field(default_factory=list)
    cards_stuck_in_hand: list = field(default_factory=list)
    damage_dealt_per_turn: list = field(default_factory=list)
    damage_taken_per_turn: list = field(default_factory=list)
    commander_first_cast_turn: int = 0


# ==================== Mana System ====================

def _parse_pips(mana_cost):
    """Parse mana cost string into color pips and generic amount."""
    pips = Counter()
    for m in HYBRID_RE.finditer(mana_cost):
        # For hybrid, we need either color — count both as potential
        pips[m.group(1)] += 1
    for m in PIP_RE.finditer(mana_cost):
        pips[m.group(1)] += 1
    generic = 0
    for m in GENERIC_RE.finditer(mana_cost):
        generic += int(m.group(1))
    return pips, generic


def get_available_mana(player):
    """Count mana available from untapped permanents."""
    mana = Counter()
    for perm in player.battlefield:
        if perm.tapped:
            continue
        if perm.is_creature() and perm.summoning_sick:
            continue
        produced = perm.card.get('produced_mana', [])
        if not produced:
            continue
        for color in produced:
            mana[color] += 1
    # Total = sum of mana each source can produce (1 per source, except sources
    # that list the same color multiple times like Sol Ring ["C","C"] = 2 mana).
    total = 0
    for perm in player.battlefield:
        if perm.tapped:
            continue
        if perm.is_creature() and perm.summoning_sick:
            continue
        produced = perm.card.get('produced_mana', [])
        if not produced:
            continue
        # Deduplicated colors = choices for a single mana, duplicated = produces multiple
        # e.g. ["G"] = 1 mana, ["W","U","B","R","G"] = 1 mana (choice), ["C","C"] = 2 mana
        unique_colors = set(produced)
        if len(produced) == len(unique_colors):
            total += 1  # one mana, choice of colors
        else:
            total += len(produced) - len(unique_colors) + 1
    mana['total'] = total
    return mana


def _mana_count_for_source(produced):
    """How many mana does a source produce? e.g. ["C","C"]=2, ["W","U","B","R","G"]=1."""
    unique = set(produced)
    if len(produced) == len(unique):
        return 1
    return len(produced) - len(unique) + 1


def _get_untapped_sources(player):
    """Get list of (perm_index, color_set, mana_count) for untapped mana sources."""
    sources = []
    for i, perm in enumerate(player.battlefield):
        if perm.tapped:
            continue
        if perm.is_creature() and perm.summoning_sick:
            continue
        produced = perm.card.get('produced_mana', [])
        if produced:
            sources.append((i, set(produced), _mana_count_for_source(produced)))
    return sources


def can_cast(player, card, commander_tax=0):
    """Check if player has enough mana to cast a card."""
    cmc = card.get('cmc', 0) + commander_tax
    mana_cost = card.get('mana_cost', '')
    pips, generic = _parse_pips(mana_cost)

    available = get_available_mana(player)

    # Check total mana
    if available['total'] < cmc:
        return False

    # Check each color pip has a source
    sources = _get_untapped_sources(player)

    # Greedy assignment: assign color-specific pips first
    # Track remaining mana per source
    remaining_mana = {i: count for i, colors, count in sources}
    source_colors = {i: colors for i, colors, count in sources}

    for color, needed in sorted(pips.items(), key=lambda x: -x[1]):
        still_need = needed
        # Prefer mono-color sources for specific pips
        for i, colors, count in sources:
            if remaining_mana[i] <= 0 or color not in colors:
                continue
            if len(colors) == 1:
                use = min(remaining_mana[i], still_need)
                remaining_mana[i] -= use
                still_need -= use
                if still_need == 0:
                    break
        if still_need > 0:
            for i, colors, count in sources:
                if remaining_mana[i] <= 0 or color not in colors:
                    continue
                use = min(remaining_mana[i], still_need)
                remaining_mana[i] -= use
                still_need -= use
                if still_need == 0:
                    break
        if still_need > 0:
            return False

    # Check generic mana
    generic_needed = cmc - sum(pips.values())
    if generic_needed < 0:
        generic_needed = 0
    unused_mana = sum(remaining_mana.values())
    return unused_mana >= generic_needed


def tap_mana_for(player, card, commander_tax=0):
    """Tap permanents to pay for a card. Returns True if successful."""
    if not can_cast(player, card, commander_tax=commander_tax):
        return False

    cmc = card.get('cmc', 0) + commander_tax
    mana_cost = card.get('mana_cost', '')
    pips, generic = _parse_pips(mana_cost)

    sources = _get_untapped_sources(player)
    to_tap = set()

    # Assign color pips first, preferring mono-color sources
    for color, needed in sorted(pips.items(), key=lambda x: -x[1]):
        remaining = needed
        # Mono-color first
        for idx, colors, count in sources:
            if idx in to_tap or color not in colors:
                continue
            if len(colors) == 1:
                to_tap.add(idx)
                remaining -= 1
                if remaining == 0:
                    break
        if remaining > 0:
            for idx, colors, count in sources:
                if idx in to_tap or color not in colors:
                    continue
                to_tap.add(idx)
                remaining -= 1
                if remaining == 0:
                    break

    # Generic mana — count how much the already-tapped sources over-produce
    mana_from_tapped = sum(
        _mana_count_for_source(player.battlefield[idx].card.get('produced_mana', []))
        for idx in to_tap
    )
    generic_needed = cmc - mana_from_tapped
    if generic_needed > 0:
        for idx, colors, count in sources:
            if idx in to_tap:
                continue
            to_tap.add(idx)
            generic_needed -= count
            if generic_needed <= 0:
                break

    # Tap the selected sources
    for idx in to_tap:
        player.battlefield[idx].tapped = True

    return True


# ==================== Zone Management ====================

def play_land(player, card):
    """Play a land from hand to battlefield."""
    if card not in player.hand:
        return False
    if player.land_drops_remaining <= 0:
        return False
    player.hand.remove(card)
    player.battlefield.append(Permanent(card=card))
    player.land_drops_remaining -= 1
    return True


def cast_spell(player, card, commander_tax=0):
    """Cast a spell from hand. Taps mana, moves card to appropriate zone."""
    if card not in player.hand and card not in player.command_zone:
        return False
    if not tap_mana_for(player, card, commander_tax=commander_tax):
        return False

    from_zone = None
    if card in player.hand:
        player.hand.remove(card)
        from_zone = 'hand'
    elif card in player.command_zone:
        player.command_zone.remove(card)
        from_zone = 'command_zone'

    type_line = card.get('type_line', '')
    is_permanent = any(t in type_line for t in PERMANENT_TYPES) and not any(t in type_line for t in SPELL_ONLY_TYPES)

    if is_permanent:
        perm = Permanent(card=card)
        if 'Creature' in type_line:
            perm.summoning_sick = True
        player.battlefield.append(perm)
    else:
        player.graveyard.append(card)

    return True


def create_token(player, name, power, toughness, type_line="Creature Token",
                 keywords=None):
    """Create a token on the battlefield."""
    token_card = make_card(
        name=f"{name} Token",
        type_line=type_line,
        power=power,
        toughness=toughness,
        keywords=keywords or [],
    )
    perm = Permanent(card=token_card, summoning_sick=True)
    player.battlefield.append(perm)
    return perm


# ==================== Combat ====================

def resolve_combat(player, attacks):
    """Resolve combat. attacks is list of (Permanent, Opponent) tuples.

    Attackers deal damage equal to their power to the targeted opponent.
    Permanents that are tapped or summoning sick cannot attack.
    """
    damage_dealt = 0
    for perm, target in attacks:
        if perm.tapped or perm.summoning_sick:
            continue
        if not perm.is_creature():
            continue
        dmg = perm.power
        if dmg > 0:
            target.take_damage(dmg)
            perm.tapped = True
            damage_dealt += dmg
    return damage_dealt


# ==================== Opponent Simulation ====================

def _player_threat_score(player):
    """Estimate how threatening the AI player's board is."""
    score = 0
    for perm in player.battlefield:
        if perm.is_creature():
            score += perm.power + 1
        elif not perm.is_land():
            score += perm.card.get('cmc', 1)
    return score


def opponent_turn(opp, turn_number, player, rng=None, other_opponents=None):
    """Simulate one opponent's turn. Returns list of events.

    Opponents attack whoever has the strongest board — they don't just pile on
    the player. The AI player competes on equal footing with other opponents.
    """
    if rng is None:
        rng = random.Random()

    if opp.eliminated:
        return []

    events = []
    opp.mana_available = min(turn_number, 10)

    # Board power grows (capped per archetype)
    growth = opp.power_growth * (1 + turn_number * 0.05)
    opp.board_power = min(opp.board_power + growth, opp.max_board_power)
    events.append(f"{opp.name} develops board (power: {opp.board_power:.1f})")

    # --- Choose attack target based on threat (strongest board gets attacked) ---
    if rng.random() < opp.attack_chance and opp.board_power > 0:
        # Build target list: player + other alive opponents, weighted by threat
        player_threat = _player_threat_score(player)
        targets = [('you', player_threat, None)]
        if other_opponents:
            for o in other_opponents:
                if o is opp or o.eliminated:
                    continue
                targets.append((o.name, o.board_power, o))

        if targets:
            # Highest threat gets attacked most often, but add randomness
            # Sort by threat descending, pick from top with weighted random
            targets.sort(key=lambda t: t[1], reverse=True)
            # Weight: threat score + small random factor so it's not deterministic
            weights = [max(1, t[1]) + rng.uniform(0, 3) for t in targets]
            total_weight = sum(weights)
            roll = rng.uniform(0, total_weight)
            cumulative = 0
            chosen = targets[0]
            for i, w in enumerate(weights):
                cumulative += w
                if roll <= cumulative:
                    chosen = targets[i]
                    break

            # Evasion
            evasion_chance = opp.evasion_base + turn_number * 0.02
            evasion_bonus = 1.0
            if rng.random() < evasion_chance:
                evasion_bonus = 1.4
                events.append(f"{opp.name} has evasive attackers!")

            base_damage = opp.board_power * 0.3 * evasion_bonus
            damage = max(0, int(base_damage * rng.uniform(0.4, 1.0)))

            if damage > 0:
                target_name, _, target_opp = chosen
                if target_opp is None:
                    # Attacking player
                    player.life -= damage
                    events.append(f"{opp.name} attacks you for {damage} damage (life: {player.life})")
                else:
                    target_opp.take_damage(damage)
                    events.append(f"{opp.name} attacks {target_name} for {damage} ({target_name} life: {target_opp.life})")
                    if target_opp.eliminated:
                        events.append(f"{target_name} has been eliminated!")

    # --- Removal: target the biggest threat across ALL players ---
    if rng.random() < opp.removal_chance:
        # Consider removing an opponent's board power OR the player's permanents
        # Whoever is the biggest threat gets targeted
        player_threat = _player_threat_score(player)
        biggest_opp_threat = 0
        biggest_opp = None
        if other_opponents:
            for o in other_opponents:
                if o is opp or o.eliminated:
                    continue
                if o.board_power > biggest_opp_threat:
                    biggest_opp_threat = o.board_power
                    biggest_opp = o

        # Target player's board if they're the biggest threat, otherwise hit an opponent
        if player_threat >= biggest_opp_threat and player.battlefield:
            nonlands = [p for p in player.battlefield if not p.is_land()]
            if nonlands:
                creatures = [p for p in nonlands if p.is_creature()]
                if creatures:
                    target = max(creatures, key=lambda p: p.power)
                else:
                    target = max(nonlands, key=lambda p: p.card.get('cmc', 0))
                player.battlefield.remove(target)
                player.graveyard.append(target.card)
                events.append(f"{opp.name} removes your {target.name}")
        elif biggest_opp:
            # Remove opponent's board power (like destroying their best creature)
            reduction = rng.uniform(2, 5)
            biggest_opp.board_power = max(0, biggest_opp.board_power - reduction)
            events.append(f"{opp.name} removes {biggest_opp.name}'s threat (power: {biggest_opp.board_power:.1f})")

    # --- Combo attempt ---
    if opp.should_attempt_combo(turn_number):
        opp.combo_attempted = True
        events.append(f"{opp.name} attempts to combo off! Respond?")

    return events


# ==================== Game Over Check ====================

def check_game_over(player, opponents):
    """Check if the game is over. Returns True if game should end.

    Game ends when player dies OR all opponents are eliminated.
    A single opponent dying doesn't end the game.
    """
    if player.life <= 0:
        return True
    # Mark dead opponents as eliminated
    for o in opponents:
        if o.life <= 0:
            o.eliminated = True
    alive = [o for o in opponents if not o.eliminated]
    if not alive:
        return True
    return False


# ==================== Game Init ====================

def init_game_from_cards(cards, seed=None, opponent_archetypes=None, mulligan_guide=None):
    """Initialize a game from a list of card dicts.

    cards: list of simplified card dicts (from make_card or card_from_scryfall)
    mulligan_guide: optional MulliganGuide for deck-specific mulligan evaluation
    """
    rng = random.Random(seed)

    player = Player()
    commander = None

    # Separate commander from library
    library = []
    for c in cards:
        if c.get('is_commander'):
            commander = c
        else:
            library.append(c)

    if commander:
        player.command_zone.append(commander)

    rng.shuffle(library)
    player.library = library

    # Draw opening hand with mulligan logic (up to 2 mulligans)
    player.draw(7)
    mulligan_count = 0
    for _ in range(2):
        keepable, reason = evaluate_hand_for_mulligan(player.hand, guide=mulligan_guide)
        if keepable:
            break
        mulligan_count += 1
        player.mulligan()
        rng.shuffle(player.library)
        player.draw(7)

    # Vancouver mulligan: bottom N cards for N mulligans
    # (simplified: just lose cards from hand)
    if mulligan_count > 0 and len(player.hand) > 7 - mulligan_count:
        # Discard highest CMC cards
        while len(player.hand) > 7 - mulligan_count:
            worst = max(player.hand, key=lambda c: c.get('cmc', 0))
            player.hand.remove(worst)
            player.library.insert(0, worst)  # bottom of library

    # Set up opponents
    if opponent_archetypes is None:
        opponent_archetypes = ['aggro', 'midrange', 'control']

    opponents = []
    for i, arch in enumerate(opponent_archetypes):
        opp = Opponent(name=f"{arch.capitalize()}", archetype=arch)
        opponents.append(opp)

    gs = GameState(player=player, opponents=opponents)
    return gs


# ==================== State Formatting ====================

def format_state(gs):
    """Format game state as structured text for AI to read."""
    lines = []
    p = gs.player

    lines.append(f"=== Turn {gs.turn_number} — Phase: {gs.phase} ===")
    lines.append(f"Life: {p.life}")
    lines.append(f"Land drops remaining: {p.land_drops_remaining}")

    # Command zone
    if p.command_zone:
        cmdr_names = [c['name'] for c in p.command_zone]
        lines.append(f"Command Zone: {', '.join(cmdr_names)} (tax: {p.commander_tax})")

    # Hand
    lines.append(f"\n--- Hand ({len(p.hand)}) ---")
    for c in sorted(p.hand, key=lambda x: (x.get('cmc', 0), x['name'])):
        type_info = c.get('type_line', '')
        cost = c.get('mana_cost', '')
        extras = []
        if c.get('power') or c.get('toughness'):
            extras.append(f"{c['power']}/{c['toughness']}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"  {c['name']}  {cost}  [{type_info}]{extra_str}")

    # Battlefield
    lines.append(f"\n--- Battlefield ({len(p.battlefield)}) ---")
    lands = [perm for perm in p.battlefield if perm.is_land()]
    nonlands = [perm for perm in p.battlefield if not perm.is_land()]

    if lands:
        tapped_lands = [l for l in lands if l.tapped]
        untapped_lands = [l for l in lands if not l.tapped]
        land_names = Counter(l.name for l in untapped_lands)
        tapped_names = Counter(l.name for l in tapped_lands)
        land_parts = [f"{n}x {name}" if n > 1 else name for name, n in sorted(land_names.items())]
        tapped_parts = [f"{n}x {name}" if n > 1 else name for name, n in sorted(tapped_names.items())]
        lines.append(f"  Lands (untapped): {', '.join(land_parts) if land_parts else 'none'}")
        if tapped_parts:
            lines.append(f"  Lands (tapped): {', '.join(tapped_parts)}")

    for perm in sorted(nonlands, key=lambda p: p.name):
        status = []
        if perm.tapped:
            status.append("tapped")
        if perm.summoning_sick:
            status.append("sick")
        status_str = f" [{', '.join(status)}]" if status else ""
        p_t = ""
        if perm.is_creature():
            p_t = f" ({perm.power}/{perm.toughness})"
        lines.append(f"  {perm.name}{p_t}{status_str}")

    # Mana
    mana = get_available_mana(p)
    mana_parts = []
    for color in ['W', 'U', 'B', 'R', 'G', 'C']:
        if mana.get(color, 0) > 0:
            mana_parts.append(f"{{{color}}}x{mana[color]}")
    lines.append(f"\nAvailable mana: {', '.join(mana_parts) if mana_parts else 'none'} (total: {mana['total']})")

    # Graveyard
    if p.graveyard:
        lines.append(f"\n--- Graveyard ({len(p.graveyard)}) ---")
        gy_names = Counter(c['name'] for c in p.graveyard)
        for name, n in sorted(gy_names.items()):
            lines.append(f"  {f'{n}x ' if n > 1 else ''}{name}")

    # Library
    lines.append(f"\nLibrary: {len(p.library)} cards")

    # Opponents
    lines.append(f"\n--- Opponents ---")
    for opp in gs.opponents:
        status = "ELIMINATED" if opp.eliminated or opp.life <= 0 else f"life: {opp.life}"
        lines.append(f"  {opp.name} ({opp.archetype}): {status}, board power: {opp.board_power:.1f}, mana: {opp.mana_available}")

    return '\n'.join(lines)


# ==================== Turn Loop ====================

def run_game(gs, input_fn=None, output_fn=None, max_turns=15, rng=None):
    """Run the game loop. input_fn reads player actions, output_fn writes state."""
    if input_fn is None:
        input_fn = lambda prompt: input(prompt)
    if output_fn is None:
        output_fn = lambda msg: print(msg)
    if rng is None:
        rng = random.Random()

    p = gs.player
    turn_damage_dealt = []
    turn_damage_taken = []

    while gs.turn_number <= max_turns and not gs.game_over:
        # ---- Untap + Upkeep ----
        if gs.turn_number > 1:
            p.untap_all()
        p.reset_land_drops()
        gs.phase = "upkeep"

        output_fn(f"\n{'='*60}")
        output_fn(f"  TURN {gs.turn_number}")
        output_fn(f"{'='*60}")

        # ---- Draw (skip turn 1) ----
        if gs.turn_number > 1:
            p.draw()
            drawn = p.hand[-1]['name'] if p.hand else "nothing"
            output_fn(f"You draw: {drawn}")

        if p.life <= 0:
            gs.game_over = True
            gs.winner = "opponents"
            break

        # ---- Main Phase 1 ----
        gs.phase = "main1"
        output_fn(format_state(gs))
        output_fn("\n--- Main Phase 1 ---")
        output_fn("Actions: play <land>, cast <spell>, cast commander, pass")

        turn_dmg_dealt = 0
        while True:
            action = input_fn("main1> ").strip()
            if not action or action.lower() == "pass":
                break
            result = _handle_action(gs, action)
            output_fn(result)

        # ---- Combat ----
        gs.phase = "combat"
        creatures = [perm for perm in p.battlefield
                     if perm.is_creature() and not perm.tapped and not perm.summoning_sick]
        if creatures:
            output_fn(f"\n--- Combat Phase ---")
            output_fn(f"Available attackers: {', '.join(f'{c.name} ({c.power}/{c.toughness})' for c in creatures)}")
            output_fn(f"Opponents: {', '.join(f'{o.name} (life: {o.life})' for o in gs.opponents if not o.eliminated)}")
            output_fn("Declare attackers: <creature> -> <opponent>, or 'attack all -> <opponent>', or 'pass'")

            action = input_fn("combat> ").strip()
            if action.lower() != "pass" and action:
                attacks = _parse_attacks(gs, action)
                dmg = resolve_combat(p, attacks)
                turn_dmg_dealt += dmg
                if dmg > 0:
                    output_fn(f"You dealt {dmg} combat damage!")
                # Report opponent status
                for opp in gs.opponents:
                    if opp.eliminated:
                        output_fn(f"  {opp.name} has been eliminated!")

        # ---- Main Phase 2 ----
        gs.phase = "main2"
        output_fn(f"\n--- Main Phase 2 ---")
        output_fn(format_state(gs))
        output_fn("Actions: play <land>, cast <spell>, cast commander, pass")

        while True:
            action = input_fn("main2> ").strip()
            if not action or action.lower() == "pass":
                break
            result = _handle_action(gs, action)
            output_fn(result)

        # ---- End Step ----
        gs.phase = "end"
        # Discard to 7
        while len(p.hand) > 7:
            output_fn(f"Hand size {len(p.hand)}, discard to 7.")
            output_fn(f"Hand: {', '.join(c['name'] for c in p.hand)}")
            action = input_fn("discard> ").strip()
            discarded = _handle_discard(gs, action)
            output_fn(discarded)

        # ---- Opponent Turns ----
        turn_dmg_taken = 0
        output_fn(f"\n--- Opponent Turns ---")
        for opp in gs.opponents:
            if opp.eliminated:
                continue
            events = opponent_turn(opp, gs.turn_number, p, rng=rng, other_opponents=gs.opponents)
            for e in events:
                output_fn(f"  {e}")

            # If combo attempt, give player chance to respond
            if any("combo" in e.lower() for e in events):
                output_fn("You have priority! Respond with instant-speed action or 'pass'")
                resp = input_fn("response> ").strip()
                if resp.lower() != "pass" and resp:
                    result = _handle_action(gs, resp)
                    output_fn(result)
                    # If player interacted, combo fails
                    if "cast" in resp.lower() or "activate" in resp.lower():
                        opp.board_power = max(0, opp.board_power - 5)
                        opp.combo_attempted = False  # delay next attempt
                        output_fn(f"  {opp.name}'s combo is disrupted!")
                    else:
                        # Combo succeeds
                        p.life = 0
                        output_fn(f"  {opp.name}'s combo succeeds! You lose!")

            turn_dmg_taken += max(0, 40 - p.life) if p.life < 40 else 0

        turn_damage_dealt.append(turn_dmg_dealt)

        # Check game over
        if check_game_over(p, gs.opponents):
            gs.game_over = True
            if p.life <= 0:
                gs.winner = "opponents"
            else:
                gs.winner = p.name

        gs.turn_number += 1

    # ---- Post-Game Summary ----
    gs.damage_dealt_per_turn = turn_damage_dealt
    output_fn(_post_game_summary(gs))
    return gs


def _handle_action(gs, action):
    """Parse and execute a player action. Returns result string."""
    p = gs.player
    action_lower = action.lower().strip()

    # Play land
    if action_lower.startswith("play "):
        card_name = action[5:].strip()
        card = _find_card_in_hand(p, card_name)
        if not card:
            return f"'{card_name}' not found in hand."
        if 'Land' not in card.get('type_line', ''):
            return f"'{card_name}' is not a land."
        if play_land(p, card):
            gs.cards_played.append(card['name'])
            return f"Played {card['name']}."
        else:
            return f"Cannot play land (no land drops remaining)."

    # Cast spell
    if action_lower.startswith("cast "):
        card_name = action[5:].strip()

        # Cast from command zone
        if card_name.lower() == "commander":
            if not p.command_zone:
                return "No commander in command zone."
            card = p.command_zone[0]
            if cast_spell(p, card, commander_tax=p.commander_tax):
                if gs.commander_first_cast_turn == 0:
                    gs.commander_first_cast_turn = gs.turn_number
                gs.cards_played.append(card['name'])
                p.commander_tax += 2
                return f"Cast {card['name']} from command zone (tax now {p.commander_tax})."
            else:
                return f"Cannot cast {card['name']} (not enough mana, need {card['cmc'] + p.commander_tax})."

        card = _find_card_in_hand(p, card_name)
        if not card:
            return f"'{card_name}' not found in hand."
        if cast_spell(p, card):
            gs.cards_played.append(card['name'])
            return f"Cast {card['name']}."
        else:
            return f"Cannot cast {card['name']} (not enough mana)."

    # Create token (AI narrates)
    if action_lower.startswith("create token "):
        # Format: create token <name> <P>/<T>
        parts = action[13:].strip().split()
        if len(parts) >= 3 and '/' in parts[-1]:
            pt = parts[-1].split('/')
            name = ' '.join(parts[:-1])
            try:
                pwr, tgh = int(pt[0]), int(pt[1])
                tok = create_token(p, name, pwr, tgh)
                return f"Created {name} {pwr}/{tgh} token."
            except ValueError:
                pass
        return "Format: create token <name> <P>/<T>"

    # Narrate (for triggers, AI describes what happens)
    if action_lower.startswith("narrate "):
        description = action[8:].strip()
        gs.game_log.append(f"Turn {gs.turn_number}: {description}")
        return f"Noted: {description}"

    return f"Unknown action: {action}. Try: play <land>, cast <spell>, cast commander, create token <name> <P>/<T>, narrate <description>, pass"


def _find_card_in_hand(player, name):
    """Find a card in hand by name (case-insensitive partial match)."""
    name_lower = name.lower()
    # Exact match first
    for c in player.hand:
        if c['name'].lower() == name_lower:
            return c
    # Partial match
    for c in player.hand:
        if name_lower in c['name'].lower():
            return c
    return None


def _parse_attacks(gs, action):
    """Parse attack declarations into list of (Permanent, Opponent) tuples."""
    p = gs.player
    attacks = []
    action_lower = action.lower().strip()

    # "attack all -> <opponent>"
    if action_lower.startswith("attack all"):
        target_name = action_lower.split("->")[-1].strip() if "->" in action_lower else ""
        target = _find_opponent(gs, target_name)
        if target:
            for perm in p.battlefield:
                if perm.is_creature() and not perm.tapped and not perm.summoning_sick:
                    attacks.append((perm, target))
        return attacks

    # Individual assignments: "Bear -> Aggro, Elf -> Control"
    parts = action.split(",")
    for part in parts:
        if "->" not in part:
            continue
        creature_name, opp_name = part.split("->", 1)
        creature_name = creature_name.strip()
        opp_name = opp_name.strip()

        perm = _find_permanent(p, creature_name)
        opp = _find_opponent(gs, opp_name)
        if perm and opp:
            attacks.append((perm, opp))

    return attacks


def _find_permanent(player, name):
    """Find a permanent on battlefield by name."""
    name_lower = name.lower()
    for perm in player.battlefield:
        if perm.name.lower() == name_lower:
            return perm
    for perm in player.battlefield:
        if name_lower in perm.name.lower():
            return perm
    return None


def _find_opponent(gs, name):
    """Find an opponent by name."""
    name_lower = name.lower()
    for opp in gs.opponents:
        if opp.name.lower() == name_lower or opp.archetype.lower() == name_lower:
            return opp
    # Partial match
    for opp in gs.opponents:
        if name_lower in opp.name.lower() or name_lower in opp.archetype.lower():
            return opp
    # Default to first alive opponent
    for opp in gs.opponents:
        if not opp.eliminated:
            return opp
    return None


def _handle_discard(gs, action):
    """Handle discard action."""
    p = gs.player
    card_name = action.strip()
    card = _find_card_in_hand(p, card_name)
    if card:
        p.hand.remove(card)
        p.graveyard.append(card)
        return f"Discarded {card['name']}."
    return f"Card '{card_name}' not found in hand."


# ==================== Post-Game Summary ====================

def _post_game_summary(gs):
    """Generate post-game summary."""
    p = gs.player
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  GAME SUMMARY")
    lines.append(f"{'='*60}")
    lines.append(f"Result: {'VICTORY' if gs.winner == p.name else 'DEFEAT'}")
    lines.append(f"Final turn: {gs.turn_number - 1}")
    lines.append(f"Final life: {p.life}")

    if gs.commander_first_cast_turn > 0:
        lines.append(f"Commander first cast: turn {gs.commander_first_cast_turn}")
    else:
        lines.append(f"Commander: never cast")

    # Cards played
    lines.append(f"\nCards played ({len(gs.cards_played)}):")
    for name in gs.cards_played:
        lines.append(f"  - {name}")

    # Cards stuck in hand
    stuck = [c['name'] for c in p.hand]
    if stuck:
        lines.append(f"\nCards still in hand ({len(stuck)}):")
        for name in stuck:
            lines.append(f"  - {name}")

    # Mana analysis
    lands_on_bf = sum(1 for perm in p.battlefield if perm.is_land())
    lines.append(f"\nLands on battlefield: {lands_on_bf}")
    lands_in_gy = sum(1 for c in p.graveyard if 'Land' in c.get('type_line', ''))
    lines.append(f"Lands in graveyard: {lands_in_gy}")

    # Damage per turn
    if gs.damage_dealt_per_turn:
        lines.append(f"\nCombat damage dealt per turn:")
        for i, dmg in enumerate(gs.damage_dealt_per_turn, 1):
            lines.append(f"  Turn {i}: {dmg}")
        lines.append(f"  Total: {sum(gs.damage_dealt_per_turn)}")

    # Opponent status
    lines.append(f"\nOpponent final status:")
    for opp in gs.opponents:
        status = "ELIMINATED" if opp.eliminated or opp.life <= 0 else f"life: {opp.life}"
        lines.append(f"  {opp.name} ({opp.archetype}): {status}")

    lines.append(f"\n{'='*60}")
    return '\n'.join(lines)


# ==================== CLI Entry Point ====================

def main():
    ap = argparse.ArgumentParser(description='Commander game simulator')
    ap.add_argument('decklist', help='Path to decklist file')
    ap.add_argument('--opponents', type=str, default='aggro,midrange,control',
                    help='Comma-separated opponent archetypes')
    ap.add_argument('--seed', type=int, default=None, help='Random seed')
    ap.add_argument('--max-turns', type=int, default=15, help='Maximum turns')
    args = ap.parse_args()

    from card_cache import get_deck_cards

    print("Loading deck and Scryfall data...", file=sys.stderr)
    all_cards, parsed = get_deck_cards(args.decklist)

    # Convert to simplified card format
    cards = [card_from_scryfall(c) for c in all_cards]

    archetypes = [a.strip() for a in args.opponents.split(',')]
    gs = init_game_from_cards(cards, seed=args.seed, opponent_archetypes=archetypes)

    rng = random.Random(args.seed)
    run_game(gs, max_turns=args.max_turns, rng=rng)


if __name__ == '__main__':
    main()
