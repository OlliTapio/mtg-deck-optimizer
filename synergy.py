#!/usr/bin/env python3
"""Synergy calculator: which cards in a deck work together, and why.

Every card is read for its keywords, types and triggers, then tagged with what
it PRODUCES (e.g. +1/+1 counters, creature tokens, cards in graveyards) and what
it CARES ABOUT (e.g. "whenever a +1/+1 counter is put on", "whenever you draw").
Two cards synergise when one produces what the other cares about. Every score
comes with the card text that caused it, so the model reasons from evidence.

Scoring rules:
- A theme only counts when the deck has both a producer and a payoff for it.
  Ten foretell cards with nothing that cares about casting from exile score 0.
- Denser themes weigh more: each producer-payoff pair adds to both cards.
- The deck's main theme (most synergy) gets a x1.5 bonus, the subtheme x1.25.
- Pairs that involve the commander count x2.
- Cut candidates combine low synergy with high mana value.

Usage:
    python3 synergy.py decks/<deck>/decklist.txt               # report
    python3 synergy.py decks/<deck>/decklist.txt --card "Name" # one card's partners
    python3 synergy.py decks/<deck>/decklist.txt --cuts        # cut candidates
    python3 synergy.py decks/<deck>/decklist.txt --features    # extracted features
    python3 synergy.py decks/<deck>/decklist.txt --save        # write decks/<deck>/synergy.json
    python3 synergy.py decks/<deck>/decklist.txt --json        # JSON to stdout
"""
import argparse
import json
import math
import os
import re
import signal
import sys
from collections import defaultdict, namedtuple

# ==================== Tuning ====================

MAIN_THEME_BONUS = 1.5
SUBTHEME_BONUS = 1.25
SUBTHEME_MIN_SHARE = 0.25     # subtheme needs >= 25% of the main theme's synergy
COMMANDER_BONUS = 2.0
WEAK = 0.3                    # type-derived producers ("every creature enters")
PAIR_CAP = 4.0                # max score for one pair of cards
CUT_CMC_WEIGHT = 0.5          # how much mana value pushes a card up the cut list
COMBO_WEIGHT = 2.0            # per pair of pieces in a known combo (Commander Spellbook)
# Combos that win the game get an extra bonus that shrinks fast as the deck's target
# bracket drops: bonus = WINCON_BONUS * WINCON_DECAY ** (4 - bracket).
# Bracket 4: +6.0, 3: +2.1, 2: +0.74, 1: +0.26 (on top of COMBO_WEIGHT).
WINCON_BONUS = 6.0
WINCON_DECAY = 0.35
# Ramp: worth more with an expensive commander and a high curve.
#   commander pair = base(commander MV) * timing * creature bonus, then x2 commander bonus
#     base   = RAMP_CMDR_BASE + RAMP_CMDR_PER_MV per MV above 4 (0 for MV <= 3, max RAMP_CMDR_MAX)
#     timing = 1.0 if the ramp costs <= commander MV - 2 (commander a turn early), 0.5 at MV - 1, else 0
#     creature ramp x RAMP_CREATURE_BONUS
#   curve bonus    = RAMP_CURVE_WEIGHT * (average mana value - 2.5, 0..2) * number of 5+ mana spells
#   land ramp      = RAMP_LAND_PER_TURN * (expected game length in turns - 5): lands survive board wipes
RAMP_CMDR_BASE = 1.0
RAMP_CMDR_PER_MV = 0.5
RAMP_CMDR_MAX = 2.5
RAMP_CREATURE_BONUS = 1.5
RAMP_CURVE_WEIGHT = 0.25
RAMP_LAND_PER_TURN = 0.25
# Expected game length per bracket (CLAUDE.md: games last 9+, 8+, 6+, 4+ turns)
GAME_TURNS = {1: 10, 2: 9, 3: 7, 4: 5}
LAND_RAMP_PATTERN = re.compile(
    r"search your library for [^.]*\b(?:lands?|forests?|islands?|swamps?|mountains?|plains)\b[^.]*onto the battlefield|put [^.]*\blands? cards?[^.]*onto the battlefield"
    r"|play an additional land|play (?:lands|land cards) from your graveyard|return [^.]*\blands? cards?[^.]*to the battlefield")
RAMP_EXPENSIVE_MV = 5
RAMP_PATTERN = re.compile(
    r"\badd (?:\{|one mana|two mana|three mana|x mana|an amount of|mana)|search your library for [^.]*\blands?\b"
    r"|put [^.]*\blands? cards?[^.]*onto the battlefield|play an additional land|create [^.]*treasure")
# Protection: pairs with the commander by how much the deck depends on it.
#   dependence = (commander's synergy / average card's synergy - 1) / 3, capped 0..1
#                + PLAN_CMDR_DAMAGE if the deck plans to win with commander damage / voltron
#   protection pair = PROTECTION_WEIGHT * dependence, then x2 commander bonus
#   protection card bonus = PROTECTION_SHARE * dependence * median card synergy (scales with the deck,
#     since one pair can't compete with totals built from dozens of pairs)
PROTECTION_WEIGHT = 1.0
PROTECTION_SHARE = 0.5
PLAN_CMDR_DAMAGE = 0.75
PROTECTION_PATTERN = re.compile(
    r"(?<!~ )(?<!~ also )\b(?:gains?|has|have) [^.]*(?:hexproof|shroud|indestructible|protection from)"
    r"|(?<!opponents control )\bphases? out"
    r"|counter target (?:spell|ability)[^.]*that targets (?:a|one or more) (?:creature|permanent)s? you control")
# Reactive cards (removal, counterspells, protection) do nothing on their own. Beyond the
# template's 12 targeted-disruption slots (+2 for commander-damage decks, which need more
# protection), every reactive card loses REACTIVE_PENALTY per extra card.
REACTIVE_LIMIT = 12
REACTIVE_LIMIT_CMDR_DAMAGE = 14
REACTIVE_PENALTY = 0.5
# Card draw and selection are always useful: a base bonus scaled to the deck.
#   draw      (draws cards, impulse draw, card-advantage otag) = DRAW_SHARE * median card synergy
#   selection (scry, surveil, looting, look at the top N)      = SELECTION_SHARE * median card synergy
DRAW_SHARE = 0.25
SELECTION_SHARE = 0.125
DRAW_PATTERN = re.compile(
    r"\bdraws? (?:a|an|one|two|three|four|five|x|that many|\d+|cards equal|\w+) (?:additional )?cards?"
    r"|exile the top [^.]*(?:you may play|you may cast)")
SELECTION_PATTERN = re.compile(
    r"\bscry \d|\bscry x|\bsurveil\b|look at the top|reveal the top|\bexplores?\b|\bconnives?\b"
    r"|draw [^.]*, then discard|discard [^.]*, then draw")
DEFAULT_BRACKET = 3           # when the deck's CLAUDE.md names no bracket
WINCON_PATTERN = re.compile(
    r"win the game|loses? the game|\binfinite (?:combat )?damage(?! to creatures)|near-infinite damage(?! to creatures)"
    r"|lifeloss|life loss|infinite combat phases|infinite turns|infinite mill(?! of your)|opponents? mills?", re.I)

TAG_WEIGHTS = {
    'counters_p1p1': 1.0, 'counters_m1m1': 1.0, 'rad': 1.0, 'counters_present': 0.5, 'counters_any': 0.75, 'proliferate': 1.0,
    'token_creature': 1.0, 'token_artifact': 0.75, 'go_wide': 0.75,
    'sacrifice': 1.0, 'dies': 1.0, 'fodder': 1.0,
    'mill': 1.0, 'graveyard': 0.75, 'land_gy': 1.0, 'discard': 0.75,
    'lifegain': 1.0, 'draw': 0.75, 'landfall': 1.0,
    'cast_noncreature': 0.75, 'cast_exile': 1.0,
    'etb': 0.5, 'big_power': 0.75,
    'trigger_dies': 1.0, 'trigger_etb': 1.0,
}
PREFIX_WEIGHTS = {'kw:': 0.75, 'type:': 1.0, 'color:': 1.0}

TAG_LABELS = {
    'counters_p1p1': '+1/+1 counters', 'counters_present': 'counters to proliferate', 'counters_m1m1': '-1/-1 counters', 'rad': 'rad counters', 'counters_any': 'counters (any kind)',
    'proliferate': 'proliferate', 'token_creature': 'creature tokens', 'token_artifact': 'artifact tokens',
    'go_wide': 'go wide', 'sacrifice': 'sacrifice', 'dies': 'creatures dying', 'fodder': 'sacrifice fodder',
    'mill': 'mill', 'graveyard': 'graveyard', 'land_gy': 'lands in graveyard', 'discard': 'discard',
    'lifegain': 'lifegain', 'draw': 'card draw', 'landfall': 'landfall',
    'cast_noncreature': 'noncreature spells', 'cast_exile': 'casting from exile',
    'etb': 'creatures entering', 'big_power': 'power 4+',
    'trigger_dies': 'death-trigger doubling', 'trigger_etb': 'ETB-trigger doubling',
    'ramp': 'ramp', 'protection': 'protects the commander', 'combo': 'known combo', 'combo_win': 'known combo (wins the game)',
}


def tag_weight(tag):
    for prefix, w in PREFIX_WEIGHTS.items():
        if tag.startswith(prefix):
            return w
    return TAG_WEIGHTS.get(tag, 0.75)


def tag_label(tag):
    if tag.startswith('kw:'):
        return f'{tag[3:]} matters'
    if tag.startswith('type:'):
        return f'{tag[5:]} matters'
    if tag.startswith('color:'):
        _, color, kind = tag.split(':')
        return f'{color.lower()} {kind} spells'
    return TAG_LABELS.get(tag, tag)


# ==================== Card view ====================

Feature = namedtuple('Feature', 'tag side scope evidence strength')
# side: 'P' produces | 'C' cares about
# scope: 'self' (only this card) | 'yours' | 'any' | 'opp' (opponents' only)

MAIN_TYPES = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Land', 'Planeswalker', 'Battle']
EVASION_KEYWORDS = {'Flying', 'Trample', 'Lifelink', 'Deathtouch', 'Menace', 'Reach', 'Vigilance',
                    'Haste', 'First strike', 'Double strike', 'Hexproof', 'Indestructible', 'Ward'}


def _faces(d):
    return d.get('card_faces') or [d]


def card_view(d, otags=None):
    """Normalise a raw Scryfall dict or a deck.json entry into one flat view."""
    faces = _faces(d)
    oracle = d.get('oracle_text') if not d.get('card_faces') else None
    if oracle is None:
        oracle = '\n'.join(f.get('oracle_text', '') for f in faces if f.get('oracle_text'))
    type_lines = [f.get('type_line', '') for f in faces] if d.get('card_faces') else [d.get('type_line', '')]
    front = type_lines[0] if type_lines else ''
    if d.get('card_faces') and ' // ' in (d.get('type_line') or ''):
        front = d['type_line'].split(' // ')[0]
    subtypes = set()
    for tl in (d.get('type_line') or ' // '.join(type_lines)).split(' // '):
        if '—' in tl:
            subtypes.update(tl.split('—', 1)[1].split())
    power = d.get('power') or faces[0].get('power')
    try:
        power = int(power)
    except (TypeError, ValueError):
        power = None
    return {
        'name': d['name'],
        'oracle': oracle or '',
        'front_types': {t for t in MAIN_TYPES if t in front},
        'back_land': bool(d.get('card_faces')) and any('Land' in tl for tl in type_lines[1:]),
        'subtypes': subtypes,
        'keywords': set(d.get('keywords') or []),
        'power': power,
        'cmc': d.get('cmc') or 0,
        'otags': set(otags if otags is not None else d.get('otags') or []),
        'colors': set(d.get('colors') or faces[0].get('colors') or d.get('color_identity') or []),
    }


# ==================== Text normalisation ====================

def normalize_text(view):
    """Lowercase, drop reminder text and quoted granted abilities, and replace
    references to the card itself with '~'."""
    t = view['oracle'].lower()
    t = re.sub(r'\([^)]*\)', '', t)
    t = re.sub(r'"[^"]*"', '', t)
    names = set()
    for face_name in view['name'].lower().split(' // '):
        names.add(face_name)
        if ',' in face_name:
            names.add(face_name.split(',')[0])
    for n in sorted(names, key=len, reverse=True):
        t = t.replace(n, '~')
    t = re.sub(r'\bthis (creature|artifact|enchantment|permanent|land|card|token|spell|vehicle)\b', '~', t)
    return t


def split_abilities(text):
    """Return a list of (kind, condition, body) per sentence.

    kind: 'trigger' (condition = trigger event), 'activated' (condition = cost),
    'static' (condition empty).
    """
    out = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or line == '---':
            continue
        cost, body = '', line
        m = re.match(r'^([^"]*?):\s+(.*)$', line)
        if m and not re.match(r'^(when|whenever|at)\b', line):
            cost, body = m.group(1), m.group(2)
            out.append(('activated', cost, body))
            continue
        for sent in re.split(r'(?<=\.)\s+', body):
            tm = re.match(r'^(when|whenever|at the beginning of)\b([^,]*),\s*(.*)$', sent)
            if tm:
                out.append(('trigger', tm.group(2).strip(), tm.group(3)))
            else:
                out.append(('static', '', sent))
    return out


def _scope_of(text):
    if re.search(r'(an opponent controls|opponents control|each opponent|an opponent\b)', text):
        return 'opp'
    if re.search(r'(you control|you own|your graveyard|\byou\b)', text):
        return 'yours'
    return 'any'


def _clip(s, n=80):
    s = ' '.join(s.split())
    return s if len(s) <= n else s[:n - 1] + '…'


# ==================== Feature extraction ====================

NUM = r'(?:a|an|one|two|three|four|five|six|x|that many|\d+|\w+)'

# Trigger conditions -> (tag, side). Side P for self-triggers that make the card a
# producer for something else (e.g. "when ~ dies" makes it sacrifice fodder).
CONDITION_RULES = [
    (r'\+1/\+1 counters? (?:is|are) put on', 'counters_p1p1'),
    (r'-1/-1 counters? (?:is|are) put on', 'counters_m1m1'),
    (r'rad counters?', 'rad'),
    (r'counters? (?:is|are) put on', 'counters_any'),
    (r'(?:nonland )?cards? (?:is|are) milled|\bmills?\b', 'mill'),
    (r'you draw', 'draw'),
    (r'you gain life', 'lifegain'),
    (r'you sacrifice', 'sacrifice'),
    (r'you discard|discards? (?:a|one or more) cards?', 'discard'),
    (r'\bland\b[^.]*\benters', 'landfall'),
    (r'cast [^.]*from exile|cast [^.]*from anywhere other than your hand', 'cast_exile'),
    (r'cast (?:a|an|your first) (?:noncreature|instant or sorcery|instant|sorcery)', 'cast_noncreature'),
    (r'(?:creature )?tokens? [^.]*(?:enters|is created|are created|leaves)', 'token_creature'),
    (r'(?:creatures?|permanents?)[^.]*\bdies\b|\bdies\b|put into (?:a|your|an opponent\'s) graveyard from the battlefield', 'dies'),
    (r'one or more [^.]*creatures? you control attack|creatures? you control attacks?', 'go_wide'),
    (r'(?:another|a|one or more|nontoken) (?:\w+ )?creatures?[^.]*\benters', 'etb'),
    (r'cards? (?:is|are) put into your graveyard', 'graveyard'),
]

# Effect / cost text -> (tag, side, strength)
EFFECT_RULES = [
    # +1/+1 counters
    (r'put ' + NUM + r' (?:additional )?\+1/\+1 counters? on', 'counters_p1p1', 'P', 1.0),
    (r'enters with ' + r'[^.]*\+1/\+1 counters?', 'counters_p1p1', 'P', 1.0),
    (r'if one or more (?:\+1/\+1 )?counters would be put|twice that many (?:\+1/\+1 )?counters|that many plus one (?:\+1/\+1 )?counters', 'counters_p1p1', 'PC', 1.0),
    (r'if one or more counters would be put|twice that many counters|that many plus one counters', 'counters_any', 'PC', 1.0),
    (r'with(?:out)? (?:a |one or more )?\+1/\+1 counters? on (?:it|them)|for each \+1/\+1 counter|remove (?:a|one|x|\w+) \+1/\+1 counters?|number of \+1/\+1 counters', 'counters_p1p1', 'C', 1.0),
    (r'(?:creatures?|permanents?) (?:you control )?with (?:one or more )?counters|for each counter|counters? of each kind', 'counters_any', 'C', 1.0),
    # -1/-1 counters
    (r'put ' + NUM + r' (?:additional )?-1/-1 counters? on|enters with [^.]*-1/-1 counters?|-1/-1 counters? on (?:each|target|up to)', 'counters_m1m1', 'P', 1.0),
    (r'with (?:a |one or more )?-1/-1 counters? on (?:it|them)|for each -1/-1 counter|remove (?:a|one|x|\w+) -1/-1 counters?|-1/-1 counters? would be put|that many plus one -1/-1', 'counters_m1m1', 'C', 1.0),
    (r'that many plus one -1/-1|twice that many -1/-1|-1/-1 counters? would be put', 'counters_m1m1', 'P', 1.0),
    # rad counters (rad mills its holder: it also produces mill)
    (r'(?:get|gets|put) ' + NUM + r' rad counters?', 'rad', 'P', 1.0),
    (r'(?:get|gets|put) ' + NUM + r' rad counters?', 'mill', 'P', 1.0),
    (r'rad counters? (?:on|than)|for each rad counter|with rad counters|had rad counters', 'rad', 'C', 1.0),
    # tokens
    (r'create [^.]*creature tokens?', 'token_creature', 'P', 1.0),
    (r'create [^.]*creature tokens?', 'go_wide', 'P', 1.0),
    (r'create [^.]*creature tokens?', 'fodder', 'P', 1.0),
    (r'create [^.]*creature tokens?', 'etb', 'P', 1.0),
    (r'create [^.]*(?:treasure|clue|food|blood|map|powerstone|gold|junk|incubator) tokens?', 'token_artifact', 'P', 1.0),
    (r'create [^.]*(?:treasure|clue|food|blood|map|powerstone|gold|junk|incubator) tokens?', 'type:Artifact', 'P', 1.0),
    (r'for each creature you control|creatures you control get \+|number of creatures you control', 'go_wide', 'C', 1.0),
    # sacrifice
    (r'sacrifice (?:a|an|another|one|two|x) (?:\w+ )?(?:creature|artifact|permanent|token)', 'sacrifice', 'P', 1.0),
    (r'sacrifice (?:a|an|another|one|two|x) (?:\w+ )?(?:creature|permanent|token)', 'dies', 'P', 1.0),
    (r'sacrifice (?:a|an|another|one|two|x) (?:\w+ )?(?:creature|permanent|token)', 'fodder', 'C', 1.0),
    (r'causes? a triggered ability of a permanent you control to trigger', 'trigger_dies', 'C', 1.0),
    # graveyard / mill
    (r'\bmills? ' + NUM + r' cards?|\bmill ' + NUM + r'\b', 'mill', 'P', 1.0),
    (r'\bmills? ' + NUM + r' cards?|\bmill ' + NUM + r'\b|\bsurveil\b', 'graveyard', 'P', 1.0),
    (r'\bdiscards? ' + NUM + r' cards?|then discard', 'discard', 'P', 1.0),
    (r'\bdiscards? ' + NUM + r' cards?|then discard', 'graveyard', 'P', 1.0),
    (r'(?:card|cards) (?:in|from) your graveyard|from your graveyard|cards in graveyards|graveyard to the battlefield|from a graveyard', 'graveyard', 'C', 1.0),
    (r'land cards? (?:in|from) your graveyard|lands? from your graveyard', 'land_gy', 'C', 1.0),
    (r'sacrifice ~: search|sacrifice (?:a|an) land\b', 'land_gy', 'P', 1.0),
    # Self-mill (incl. rad counters on you) puts some of your lands into your graveyard
    (r'each player (?:gets? [^.]*rad counters?|mills?)|\byou (?:get [^.]*rad counters?|mill)\b|^mill (?:a|one|two|three|four|five|x|\d+) cards?',
     'land_gy', 'P', 0.5),
    # card draw / lifegain
    (r'draws? ' + NUM + r' (?:additional )?cards?|draw cards equal', 'draw', 'P', 1.0),
    (r'you gain ' + NUM + r' life|you gain life equal|gain that much life', 'lifegain', 'P', 1.0),
    (r'if you would gain life', 'lifegain', 'C', 1.0),
    # lands
    (r'put [^.]*\blands? cards?[^.]*onto the battlefield|search your library for [^.]*lands?[^.]*onto the battlefield|play an additional land|play lands from your graveyard', 'landfall', 'P', 1.0),
    # spells from exile
    (r'you may (?:cast|play) (?:it|that card|them|those cards)[^.]*(?:this turn|until)', 'cast_exile', 'P', 1.0),
    (r'cast [^.]*from exile', 'cast_exile', 'C', 1.0),
    # power
    (r'power (?:[4-9]|\d\d) or greater|greatest power|total power', 'big_power', 'C', 1.0),
    # ETB trigger doubling
    (r'(?:entering|enters)[^.]*causes? a triggered ability[^.]*to trigger', 'trigger_etb', 'C', 1.0),
    # blink / reanimate make creatures enter
    (r'return [^.]*(?:creature|permanent)[^.]*to the battlefield', 'etb', 'P', 1.0),
    # artifact / enchantment matters
    (r'whenever (?:an|another|one or more) (?:nontoken )?artifacts?[^.]*enters|for each artifact you control|artifacts you control', 'type:Artifact', 'C', 1.0),
    (r'whenever (?:an|another|one or more) (?:nontoken )?enchantments?[^.]*enters|for each enchantment you control|enchantments you control|whenever you cast an enchantment', 'type:Enchantment', 'C', 1.0),
]

KEYWORD_FEATURES = {
    'Evolve': [('counters_p1p1', 'P', 'self'), ('etb', 'C', 'yours')],
    'Adapt': [('counters_p1p1', 'P', 'self')],
    'Monstrosity': [('counters_p1p1', 'P', 'self')],
    'Bolster': [('counters_p1p1', 'P', 'yours')],
    'Outlast': [('counters_p1p1', 'P', 'self')],
    'Modular': [('counters_p1p1', 'P', 'yours')],
    'Training': [('counters_p1p1', 'P', 'self')],
    'Support': [('counters_p1p1', 'P', 'yours')],
    'Graft': [('counters_p1p1', 'P', 'yours')],
    'Proliferate': [('proliferate', 'P', 'any')],
    'Wither': [('counters_m1m1', 'P', 'any')],
    'Infect': [('counters_m1m1', 'P', 'any')],
    'Blight': [('counters_m1m1', 'P', 'yours')],
    'Afterlife': [('token_creature', 'P', 'yours'), ('fodder', 'P', 'self'), ('go_wide', 'P', 'yours')],
    'Fabricate': [('token_creature', 'P', 'yours'), ('counters_p1p1', 'P', 'self')],
    'Amass': [('token_creature', 'P', 'yours'), ('counters_p1p1', 'P', 'yours')],
    'Populate': [('token_creature', 'P', 'yours'), ('token_creature', 'C', 'yours')],
    'Investigate': [('token_artifact', 'P', 'yours'), ('type:Artifact', 'P', 'yours')],
    'Persist': [('fodder', 'P', 'self'), ('dies', 'P', 'self'), ('counters_m1m1', 'P', 'self')],
    'Undying': [('fodder', 'P', 'self'), ('dies', 'P', 'self'), ('counters_p1p1', 'P', 'self')],
    'Blitz': [('fodder', 'P', 'self')],
    'Mill': [('mill', 'P', 'any'), ('graveyard', 'P', 'any')],
    'Surveil': [('graveyard', 'P', 'yours')],
    'Dredge': [('graveyard', 'C', 'yours')],
    'Landfall': [('landfall', 'C', 'yours')],
    'Lifelink': [('lifegain', 'P', 'yours')],
    'Ferocious': [('big_power', 'C', 'yours')],
    'Foretell': [('cast_exile', 'P', 'yours')],
    'Plot': [('cast_exile', 'P', 'yours')],
    'Rebound': [('cast_exile', 'P', 'yours')],
    'Suspend': [('cast_exile', 'P', 'yours')],
    'Disturb': [('graveyard', 'C', 'self')],
    'Flashback': [('graveyard', 'C', 'self')],
    'Escape': [('graveyard', 'C', 'self')],
    'Unearth': [('graveyard', 'C', 'self')],
    'Delirium': [('graveyard', 'C', 'yours')],
    'Threshold': [('graveyard', 'C', 'yours')],
    'Morbid': [('dies', 'C', 'any')],
    'Revolt': [('fodder', 'C', 'yours')],
}

# Proliferate adds every counter kind already there, so it feeds both counter axes. It only
# multiplies existing counters, so it is weak (x0.5) unless the deck has PROLIFERATE_DENSE or
# more other producers of that counter, then full strength.
PROLIFERATE_FEEDS = [('counters_p1p1', 0.5), ('counters_m1m1', 0.5), ('rad', 0.5), ('counters_any', 1.0)]
PROLIFERATE_DENSE = 8
MASS_COUNTERS = 1.5   # counters on each creature you control vs one creature
# Rad counters sit on players and survive board wipes, so a few producers are enough.
PROLIFERATE_DENSE_BY_AXIS = {'rad': 3}
COUNTER_AXES = ('counters_p1p1', 'counters_m1m1', 'rad')

# Repeatable producers are worth more than one-shots:
#   one-shot (instant/sorcery, "when ~ enters/dies", sacrifice ~)        x1.0
#   your turn (attack, "you cast", your upkeep), activated, static         x1.25
#   any player's turn (a player casts, cards are milled, counters put...)  x1.5
REPEAT_ONE_SHOT, REPEAT_YOUR_TURN, REPEAT_ANY_TURN = 1.0, 1.25, 1.5
TYPE_DERIVED = ('is a', 'is an', 'power ', 'keyword: Flying', 'keyword: Trample')


def ability_repeat(kind, cond, is_permanent, body=''):
    """How often an ability can produce its effect (see REPEAT_*)."""
    if not is_permanent:
        return REPEAT_ONE_SHOT
    if kind == 'activated':
        return REPEAT_ONE_SHOT if re.search(r'(?:sacrifice|exile) ~', cond) else REPEAT_YOUR_TURN
    if kind == 'static':
        return REPEAT_ONE_SHOT if re.search(r'~ enters with|\bas ~ enters', body) else REPEAT_YOUR_TURN
    if re.match(r'^~ (?:enters|dies|is put into)', cond) and ' or ' not in cond:
        return REPEAT_ONE_SHOT
    if re.search(r'\byour (?:turn|upkeep|end step|precombat|combat|draw step)|\byou cast|\byou attack|\battacks?\b'
                 r'|\benters\b', cond):
        return REPEAT_YOUR_TURN
    return REPEAT_ANY_TURN

# Irregular plurals for tribal matching.
PLURALS = {'Elf': 'elves', 'Dwarf': 'dwarves', 'Wolf': 'wolves', 'Werewolf': 'werewolves',
           'Fungus': 'fungi', 'Mouse': 'mice', 'Ox': 'oxen', 'Sphinx': 'sphinxes', 'Fox': 'foxes'}
# Subtypes that are too generic or usually part of other phrases.
SUBTYPE_STOPWORDS = {'Human', 'Equipment', 'Aura', 'Saga', 'Class', 'Case', 'Room', 'Food', 'Clue',
                     'Treasure', 'Blood', 'Map', 'Gold', 'Powerstone', 'Forest', 'Island', 'Swamp',
                     'Mountain', 'Plains', 'Cave', 'Gate', 'Town', 'Sphere', 'Lesson', 'Adventure',
                     'Arcane', 'Trap', 'Siege', 'Vehicle', 'Spacecraft', 'Planet'}


TYPE_GRANT = re.compile(r"(?:is|are|becomes?) (?:an? )?[\w ]+ in addition to (?:its|their) other (?:creature )?types|becomes? an? [\w ]+ creature")


def _subtype_pattern(sub):
    s = sub.lower()
    plural = PLURALS.get(sub, s + ('es' if s.endswith(('s', 'x', 'ch')) else 's'))
    return re.compile(r'\b(?:%s|%s)\b' % (re.escape(s), re.escape(plural)))


def _repeat_since(feats, start, factor):
    """Scale producer features added since `start` by how often their ability repeats."""
    if factor == 1.0:
        return
    for i in range(start, len(feats)):
        f = feats[i]
        if f.side == 'P' and not f.evidence.startswith(TYPE_DERIVED):
            feats[i] = f._replace(strength=round(f.strength * factor, 3))


def extract_features(view, deck_subtypes=frozenset()):
    """Return a list of Features for one card."""
    feats = []
    text = normalize_text(view)
    types = view['front_types']

    def add(tag, side, scope, evidence, strength=1.0):
        feats.append(Feature(tag, side, scope, _clip(evidence), strength))

    is_permanent = bool(types) and not (types & {'Instant', 'Sorcery'})
    card_repeat = REPEAT_ONE_SHOT
    for kind, cond, body in split_abilities(text):
        start = len(feats)
        factor = ability_repeat(kind, cond, is_permanent, body)
        if kind != 'static' or re.search(r'\bwould\b', body):
            card_repeat = max(card_repeat, factor)
        _apply_after = (start, factor)
        if kind == 'trigger':
            self_trigger = '~' in cond and not re.search(r'\banother\b|\bother\b', cond)
            for pattern, tag in CONDITION_RULES:
                if not re.search(pattern, cond):
                    continue
                if tag == 'dies' and self_trigger and re.search(r'~[^.]*dies|~ is put into', cond):
                    add('fodder', 'P', 'self', f'{cond}, {body}')
                    add('trigger_dies', 'P', 'self', f'{cond}, {body}')
                    break
                if tag == 'etb' and self_trigger:
                    add('trigger_etb', 'P', 'self', f'{cond}, {body}')
                    break
                if self_trigger and tag in ('counters_p1p1', 'counters_any'):
                    add(tag, 'C', 'self', f'{cond}, {body}')
                    break
                if self_trigger:
                    break
                scope = _scope_of(cond)
                if tag == 'dies':
                    add('trigger_dies', 'P', 'self', f'{cond}, {body}')
                if tag == 'etb':
                    add('trigger_etb', 'P', 'self', f'{cond}, {body}')
                add(tag, 'C', scope, f'{cond}, {body}')
                break
            segments = [body]
        elif kind == 'activated':
            segments = [cond, body]
        else:
            segments = [body]

        for seg in segments:
            for pattern, tag, side, strength in EFFECT_RULES:
                m = re.search(pattern, seg)
                if not m:
                    continue
                if 'P' in side and tag in ('counters_p1p1', 'counters_m1m1') and re.search(
                        r'on each (?:other )?creature|on each of up to|on (?:all )?creatures you control', seg):
                    strength *= MASS_COUNTERS
                if 'P' in side:
                    scope = 'self' if re.search(r'on ~|~ enters with|~ gets', seg) and not re.search(r'target|each|another|other', seg) else 'yours'
                    if tag in ('mill', 'rad') and re.search(r'each player|each opponent|target player|target opponent', seg):
                        scope = 'any'
                    add(tag, 'P', scope, seg, strength)
                if 'C' in side:
                    scope = 'self' if re.search(r'from ~|on ~', seg) else _scope_of(seg)
                    if scope == 'opp' and tag not in ('dies',):
                        scope = 'any'
                    if tag in ('fodder', 'sacrifice'):
                        scope = 'yours'   # you can only sacrifice your own permanents
                    add(tag, 'C', scope, seg, strength)

        _repeat_since(feats, *_apply_after)

    # Colour matters: "whenever you cast a green permanent spell" (producers added per deck)
    for m in re.finditer(r'cast (?:a|an|your first) (white|blue|black|red|green) (?:(permanent|creature|instant or sorcery) )?spell', text):
        add(f"color:{m.group(1).capitalize()}:{m.group(2) or 'any'}", 'C', 'yours', m.group(0))

    # Keywords
    keyword_start = len(feats)
    for kw in view['keywords']:
        for tag, side, scope in KEYWORD_FEATURES.get(kw, []):
            add(tag, side, scope, f'keyword: {kw}')
        if kw in EVASION_KEYWORDS:
            add(f'kw:{kw}', 'P', 'self', f'keyword: {kw}')
    for kw_m in re.finditer(r'creatures? (?:you control )?with (flying|trample|lifelink|deathtouch|menace|reach|vigilance|haste|first strike|double strike)', text):
        kw = kw_m.group(1).capitalize()
        add(f'kw:{kw}', 'C', 'yours', kw_m.group(0))

    # Keyword abilities (Evolve, Afterlife...) on permanents repeat like their card's best ability
    _repeat_since(feats, keyword_start, max(card_repeat, REPEAT_YOUR_TURN) if is_permanent else REPEAT_ONE_SHOT)

    # Proliferate feeds every counter axis
    if any(f.tag == 'proliferate' and f.side == 'P' for f in feats) or re.search(r'\bproliferate\b', text):
        if not any(f.tag == 'proliferate' for f in feats):
            add('proliferate', 'P', 'any', 'proliferate')
        prolif_start = len(feats)
        for tag, strength in PROLIFERATE_FEEDS:
            add(tag, 'P', 'any', 'proliferate', strength)
        _repeat_since(feats, prolif_start, card_repeat)

    # Type-derived (weak) producers
    if 'Creature' in types:
        add('etb', 'P', 'self', 'is a creature', WEAK)
        if view['power'] is not None and view['power'] >= 4:
            add('big_power', 'P', 'self', f'power {view["power"]}')
    if types & {'Instant', 'Sorcery'}:
        add('cast_noncreature', 'P', 'self', 'is an instant/sorcery')
    elif types and 'Creature' not in types and 'Land' not in types:
        add('cast_noncreature', 'P', 'self', 'is a noncreature spell', WEAK)
    if types and 'Land' not in types:
        pass
    if 'Artifact' in types:
        add('type:Artifact', 'P', 'self', 'is an artifact')
    if 'Enchantment' in types:
        add('type:Enchantment', 'P', 'self', 'is an enchantment')

    # Tribal: subtypes this card has, and deck subtypes its text names
    own = set(view['subtypes'])
    if 'Changeling' in view['keywords']:
        own |= set(deck_subtypes)
    for sub in own:
        if sub not in SUBTYPE_STOPWORDS:
            add(f'type:{sub}', 'P', 'self', f'is a {sub}')
    for sub in deck_subtypes:
        if sub in SUBTYPE_STOPWORDS:
            continue
        m = _subtype_pattern(sub).search(TYPE_GRANT.sub('', text))
        if m:
            line = next((ln for ln in text.split('\n') if m.group(0) in ln), m.group(0))
            add(f'type:{sub}', 'C', 'yours', line)

    # otags back up the regexes
    OTAG_MAP = {'sacrifice-outlet': ('sacrifice', 'P'), 'lifegain': ('lifegain', 'P'),
                'mill': ('mill', 'P'), 'recursion': ('graveyard', 'C')}
    for otag in view['otags']:
        if otag in OTAG_MAP:
            tag, side = OTAG_MAP[otag]
            if not any(f.tag == tag and f.side == side for f in feats):
                add(tag, side, 'yours', f'otag: {otag}')
                if tag == 'sacrifice':
                    add('dies', 'P', 'yours', f'otag: {otag}')
                    add('fodder', 'C', 'yours', f'otag: {otag}')

    return _dedupe(feats)


def _dedupe(feats):
    """Keep the strongest feature per (tag, side, scope)."""
    best = {}
    for f in feats:
        k = (f.tag, f.side, f.scope)
        if k not in best or f.strength > best[k].strength:
            best[k] = f
    return list(best.values())


# ==================== Scoring ====================

def _compatible(p, c):
    """Can producer feature p feed payoff feature c (on different cards)?"""
    if c.scope == 'opp':
        return False
    if p.scope == 'self' and c.scope == 'self':
        return False
    return True


def is_wincon(combo):
    """Does the combo win the game by itself (damage, life loss, mill, extra turns...)?"""
    return any(WINCON_PATTERN.search(p) and 'self-mill' not in p.lower() for p in combo.get('produces', []))


def combo_weight(combo, bracket=None):
    """Pair weight for a known combo: wincons get a bonus that decays fast with lower brackets."""
    if not is_wincon(combo):
        return COMBO_WEIGHT
    b = min(4, max(1, bracket if bracket is not None else DEFAULT_BRACKET))
    return round(COMBO_WEIGHT + WINCON_BONUS * WINCON_DECAY ** (4 - b), 3)


def _combo_matches(views, combos, bracket=None):
    """Pair reasons for every two pieces of each known combo the deck contains."""
    by_lower = {}
    for v in views:
        by_lower[v['name'].lower()] = v['name']
        by_lower.setdefault(v['name'].split(' // ')[0].lower(), v['name'])
    out = {}
    for combo in combos or []:
        pieces = [by_lower.get(c.lower()) for c in combo['cards']]
        if None in pieces:
            continue
        what = ', '.join(combo.get('produces', [])[:2])
        weight = combo_weight(combo, bracket)
        tag = 'combo_win' if is_wincon(combo) else 'combo'
        for i, a in enumerate(pieces):
            for b in pieces[i + 1:]:
                key = (a, b) if a < b else (b, a)
                if key in out and out[key]['weight'] >= weight:
                    continue
                out[key] = {'tag': tag, 'producer': a, 'payoff': b, 'weight': weight,
                            'producer_evidence': ' + '.join(combo['cards']),
                            'payoff_evidence': f"{what} ({combo.get('url', '')})"}
    return out


def is_ramp(view):
    """Nonland card that makes extra mana or puts extra lands out (otags back up the regex)."""
    if 'Land' in view['front_types']:
        return False
    if view['otags'] & {'ramp', 'mana-dork'}:
        return True
    if view.get('back_land'):
        return False  # spell // land MDFC: the back face is a land drop, not ramp
    return bool(RAMP_PATTERN.search(normalize_text(view)))


def ramp_kind(view):
    """'land' (puts lands onto the battlefield: survives wipes), 'creature' or 'artifact'
    (mana from a permanent that a wipe kills), or 'other' (rituals, treasure...)."""
    text = normalize_text(view)
    if LAND_RAMP_PATTERN.search(text):
        return 'land'
    if 'Creature' in view['front_types']:
        return 'creature'
    if view['front_types'] & {'Artifact', 'Enchantment'}:
        return 'artifact'
    return 'other'


def ramp_timing(ramp_mv, cmdr_mv):
    """1.0 if this ramp lets the commander come down a turn early, 0.5 if barely, else 0."""
    if ramp_mv <= cmdr_mv - 2:
        return 1.0
    if ramp_mv <= cmdr_mv - 1:
        return 0.5
    return 0.0


def ramp_context(views, commander_name, bracket=None):
    """How much the deck wants ramp: commander base weight, curve bonus, land-ramp bonus."""
    spells = [v for v in views if 'Land' not in v['front_types'] and v['name'] != commander_name]
    avg_mv = sum(v['cmc'] for v in spells) / len(spells) if spells else 0.0
    expensive = sorted(v['name'] for v in spells if v['cmc'] >= RAMP_EXPENSIVE_MV)
    cmdr = next((v for v in views if v['name'] == commander_name), None)
    cmdr_mv = cmdr['cmc'] if cmdr else 0
    base = 0.0
    if cmdr and cmdr_mv >= 4:
        base = min(RAMP_CMDR_MAX, RAMP_CMDR_BASE + RAMP_CMDR_PER_MV * (cmdr_mv - 4))
    curve_factor = min(2.0, max(0.0, avg_mv - 2.5))
    b = min(4, max(1, bracket if bracket is not None else DEFAULT_BRACKET))
    turns = GAME_TURNS[b]
    return {'avg_mv': round(avg_mv, 2), 'commander_mv': cmdr_mv, 'expensive': expensive,
            'commander_base': round(base, 3), 'game_turns': turns,
            'curve_bonus': round(RAMP_CURVE_WEIGHT * curve_factor * len(expensive), 3),
            'land_bonus': round(RAMP_LAND_PER_TURN * max(0, turns - 5), 3)}


def ramp_commander_weight(view, ramp):
    """Commander-pair weight for one ramp card (before the x2 commander bonus)."""
    w = ramp['commander_base'] * ramp_timing(view['cmc'], ramp['commander_mv'])
    if 'Creature' in view['front_types']:
        w *= RAMP_CREATURE_BONUS
    return round(w, 3)


def is_protection(view):
    """Protects your own creatures or permanents: hexproof, indestructible, phasing..."""
    if 'Land' in view['front_types']:
        return False
    for sentence in re.split(r'[.\n]', normalize_text(view)):
        if PROTECTION_PATTERN.search(sentence) and not re.search(r'opponents? controls?|you don\'t control', sentence):
            return True
    return False


def is_reactive(view):
    """Interaction that answers something: targeted removal, counterspells, protection."""
    if 'Land' in view['front_types']:
        return False
    if is_protection(view):
        return True
    tags = view['otags']
    # Creatures with removal attached are threats too; board wipes are mass disruption, not reactive slots.
    return ('Creature' not in view['front_types'] and bool(tags & {'removal', 'counterspell'})
            and 'board-wipe' not in tags)


def draw_kind(view):
    """'draw' (card advantage), 'selection' (filtering only) or None."""
    if 'Land' in view['front_types']:
        return None
    text = normalize_text(view)
    # Not your draws: draw triggers ("whenever you draw a card") and other players drawing
    text = re.sub(r"\b(?:when|whenever|if) you draw [^,.]*", '', text)
    text = re.sub(r"\b(?:its controller|that player|each opponent|target opponent|an opponent|each other player)"
                  r" (?:may )?draws? [^,.]*", '', text)
    loots = re.search(r'draw [^.]*, then discard|discard [^.]*, then draw', text)
    if view['otags'] & {'card-advantage'} or (DRAW_PATTERN.search(text) and not loots):
        return 'draw'
    if view['otags'] & {'draw'} and not loots:
        return 'draw'
    if loots or SELECTION_PATTERN.search(text):
        return 'selection'
    return None


def deck_plan(decklist):
    """Plans named in the deck's CLAUDE.md that change scoring: {'commander_damage'}."""
    path = os.path.join(os.path.dirname(os.path.abspath(decklist)), 'CLAUDE.md')
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        text = f.read().lower()
    plans = set()
    if re.search(r'commander damage|voltron', text):
        plans.add('commander_damage')
    return plans


def commander_dependence(commander_name, names, raw_matches, plans=frozenset()):
    """0..1.75: how much of the deck's synergy runs through the commander."""
    if not commander_name or len(names) < 2:
        return 0.0, 0.0
    mass = defaultdict(float)
    for m in raw_matches:
        mass[m['producer']] += m['weight']
        mass[m['payoff']] += m['weight']
    avg = sum(mass.values()) / len(names)
    ratio = mass[commander_name] / avg if avg else 0.0
    dep = min(1.0, max(0.0, (ratio - 1) / 3))
    if 'commander_damage' in plans:
        dep += PLAN_CMDR_DAMAGE
    return round(dep, 3), round(ratio, 2)


def compute_synergy(views, commander_name=None, combos=None, bracket=None, plans=frozenset()):
    """Score every card pair. `views` is a list of card_view dicts. `combos` is the
    'included' list from combos.fetch_combos: each pair of pieces gets a bonus reason,
    bigger for game-winning combos and scaled by the deck's target `bracket`."""
    deck_subtypes = set()
    for v in views:
        deck_subtypes |= v['subtypes']
    features = {v['name']: extract_features(v, deck_subtypes) for v in views}
    names = [v['name'] for v in views]

    # Proliferate is full strength on a counter axis the deck is dense in
    for axis in ('counters_p1p1', 'counters_m1m1', 'rad'):
        n_prod = len({n for n, fs in features.items()
                      if any(f.tag == axis and f.side == 'P' and f.evidence != 'proliferate' for f in fs)})
        if n_prod >= PROLIFERATE_DENSE_BY_AXIS.get(axis, PROLIFERATE_DENSE):
            for n, fs in features.items():
                features[n] = [f._replace(strength=round(f.strength * 2, 3))
                               if f.tag == axis and f.evidence == 'proliferate' else f for f in fs]
        # Rad counters mill their holder, so proliferating them mills too
        if axis == 'rad' and n_prod:
            for n, fs in features.items():
                rad = [f for f in fs if f.tag == 'rad' and f.side == 'P' and f.evidence == 'proliferate']
                if rad:
                    features[n] = fs + [Feature('mill', 'P', 'any', 'proliferate on rad counters (rad mills)',
                                                rad[0].strength)]

    # Proliferate needs counters already on the board: every card that puts counters down
    # (any axis, not proliferate itself) feeds every proliferate card.
    for n, fs in list(features.items()):
        extra = []
        prolif = [f for f in fs if f.tag == 'proliferate' and f.side == 'P']
        if prolif:
            extra.append(Feature('counters_present', 'C', 'any', 'proliferate needs counters on the board',
                                 max(f.strength for f in prolif)))
        placed = [f for f in fs if f.side == 'P' and f.tag in COUNTER_AXES and f.evidence != 'proliferate']
        if placed:
            best = max(placed, key=lambda f: f.strength)
            extra.append(Feature('counters_present', 'P', best.scope, best.evidence, best.strength))
        features[n] = fs + extra

    # Colour-matters payoffs: every permanent/creature/spell of that colour is a producer
    color_tags = {f.tag for fs in features.values() for f in fs if f.side == 'C' and f.tag.startswith('color:')}
    COLOR_CODES = {'White': 'W', 'Blue': 'U', 'Black': 'B', 'Red': 'R', 'Green': 'G'}
    for v in views:
        if 'Land' in v['front_types']:
            continue
        for tag in color_tags:
            _, color, kind = tag.split(':')
            if COLOR_CODES[color] not in v['colors']:
                continue
            is_perm = not (v['front_types'] & {'Instant', 'Sorcery'})
            ok = {'any': True, 'permanent': is_perm, 'creature': 'Creature' in v['front_types'],
                  'instant or sorcery': not is_perm}[kind]
            if ok:
                features[v['name']] = features[v['name']] + [
                    Feature(tag, 'P', 'self', f"is a {color.lower()} {kind if kind != 'any' else 'spell'}", 0.5)]

    # Commander-damage plan: counters that grow the commander pay off through it
    if commander_name in features and 'commander_damage' in plans:
        features[commander_name] = features[commander_name] + [Feature(
            'counters_p1p1', 'C', 'self', 'commander-damage plan: +1/+1 counters grow the commander', 1.0)]

    producers = defaultdict(list)   # tag -> [(name, feature)]
    payoffs = defaultdict(list)
    for n in names:
        for f in features[n]:
            (producers if f.side == 'P' else payoffs)[f.tag].append((n, f))

    # Raw matches: (producer, payoff, tag) -> best match
    matches = {}
    for tag, cs in payoffs.items():
        for cn, cf in cs:
            for pn, pf in producers.get(tag, []):
                if pn == cn or not _compatible(pf, cf):
                    continue
                w = tag_weight(tag) * pf.strength * cf.strength
                key = (pn, cn, tag)
                if key not in matches or w > matches[key]['weight']:
                    matches[key] = {'tag': tag, 'producer': pn, 'payoff': cn, 'weight': w,
                                    'producer_evidence': pf.evidence, 'payoff_evidence': cf.evidence}

    # Themes: total synergy per tag. Only tags with both sides present exist here.
    theme_mass = defaultdict(float)
    for m in matches.values():
        if m['tag'] != 'counters_present':  # part of the counter themes, not a theme of its own
            theme_mass[m['tag']] += m['weight']
    ranked = sorted(theme_mass.items(), key=lambda kv: -kv[1])
    main_theme = ranked[0][0] if ranked else None
    subtheme = None
    if len(ranked) > 1 and ranked[1][1] >= SUBTHEME_MIN_SHARE * ranked[0][1]:
        subtheme = ranked[1][0]
    bonus = {main_theme: MAIN_THEME_BONUS, subtheme: SUBTHEME_BONUS}
    bonus.pop(None, None)
    # Counters placed for proliferate share the bonus of the deck's counter theme
    bonus['counters_present'] = max([bonus.get(a, 1.0) for a in COUNTER_AXES])

    combo_matches = _combo_matches(views, combos, bracket)
    ramp = ramp_context(views, commander_name, bracket)
    ramp_views = {v['name']: v for v in views if is_ramp(v) and v['name'] != commander_name}
    ramp_cards = sorted(ramp_views)
    ramp_kinds = {n: ramp_kind(v) for n, v in ramp_views.items()}
    for rn, rv in ramp_views.items():
        w = ramp_commander_weight(rv, ramp)
        if w > 0:
            kind = 'creature ramp' if 'Creature' in rv['front_types'] else 'ramp'
            combo_matches[('ramp', rn)] = {
                'tag': 'ramp', 'producer': rn, 'payoff': commander_name, 'weight': w,
                'producer_evidence': f"{kind}, costs {rv['cmc']:g}",
                'payoff_evidence': f"commander costs {ramp['commander_mv']:g}"}
    combo_pieces = {n for m in combo_matches.values() if m['tag'].startswith('combo')
                    for n in (m['producer'], m['payoff'])}

    # Protection scales with how much the deck depends on its commander
    dependence, cmdr_ratio = commander_dependence(
        commander_name, names, list(matches.values()) + list(combo_matches.values()), plans)
    protection_cards = sorted(v['name'] for v in views if v['name'] != commander_name and is_protection(v))
    prot_weight = round(PROTECTION_WEIGHT * dependence, 3)
    if prot_weight > 0:
        why = f"commander dependence {dependence:g}" + (' (commander-damage plan)' if 'commander_damage' in plans else '')
        for pn in protection_cards:
            combo_matches[('protection', pn)] = {
                'tag': 'protection', 'producer': pn, 'payoff': commander_name, 'weight': prot_weight,
                'producer_evidence': 'protects your creatures', 'payoff_evidence': why}

    # Too many reactive cards: each loses a little per card over the limit
    reactive_cards = sorted(v['name'] for v in views if v['name'] != commander_name and is_reactive(v))
    limit = REACTIVE_LIMIT_CMDR_DAMAGE if 'commander_damage' in plans else REACTIVE_LIMIT
    reactive_penalty = round(REACTIVE_PENALTY * max(0, len(reactive_cards) - limit), 3)

    # Pair scores
    pairs = defaultdict(lambda: {'score': 0.0, 'reasons': []})
    for m in list(matches.values()) + list(combo_matches.values()):
        a, b = sorted((m['producer'], m['payoff']))
        w = m['weight'] * bonus.get(m['tag'], 1.0)
        m = dict(m, weight=round(w, 3))
        pairs[(a, b)]['reasons'].append(m)
    for key, p in pairs.items():
        # The cap limits text synergy only; known combos add on top of it.
        text = sum(r['weight'] for r in p['reasons'] if not r['tag'].startswith('combo'))
        combo = sum(r['weight'] for r in p['reasons'] if r['tag'].startswith('combo'))
        p['score'] = round(min(PAIR_CAP, text) + combo, 3)
        if commander_name in key:
            p['score'] = round(p['score'] * COMMANDER_BONUS, 3)
        p['reasons'].sort(key=lambda r: -r['weight'])

    # Per-card totals
    cards = {}
    for n in names:
        cards[n] = {'total': 0.0, 'cmdr_fit': 0.0, 'partners': 0, 'best_partner': None,
                    'combo_piece': n in combo_pieces, 'ramp_bonus': 0.0, 'reactive_penalty': 0.0,
                    'themes': defaultdict(float)}
    for (a, b), p in pairs.items():
        for me, other in ((a, b), (b, a)):
            c = cards[me]
            c['total'] += p['score']
            c['partners'] += 1
            if other == commander_name:
                c['cmdr_fit'] = p['score']
            if c['best_partner'] is None or p['score'] > pairs[tuple(sorted((me, c['best_partner'])))]['score']:
                c['best_partner'] = other
            for r in p['reasons']:
                c['themes'][r['tag']] += r['weight']
    # Deck scale for card-level bonuses: median pair synergy of nonland, non-commander cards
    spell_totals = sorted(cards[v['name']]['total'] for v in views
                          if 'Land' not in v['front_types'] and v['name'] != commander_name)
    median_total = spell_totals[len(spell_totals) // 2] if spell_totals else 0.0
    draw_kinds = {v['name']: draw_kind(v) for v in views if v['name'] != commander_name}
    draw_kinds = {n: k for n, k in draw_kinds.items() if k}
    draw_bonus = {'draw': round(DRAW_SHARE * median_total, 3),
                  'selection': round(SELECTION_SHARE * median_total, 3)}
    for n, k in draw_kinds.items():
        cards[n]['draw_bonus'] = draw_bonus[k]
        cards[n]['draw_kind'] = k
        cards[n]['total'] += draw_bonus[k]
        if draw_bonus[k]:
            cards[n]['themes']['card draw' if k == 'draw' else 'card selection'] += draw_bonus[k]
    for rn in ramp_cards:
        bonus = ramp['curve_bonus'] + (ramp['land_bonus'] if ramp_kinds[rn] == 'land' else 0.0)
        cards[rn]['ramp_bonus'] = round(bonus, 3)
        cards[rn]['ramp_kind'] = ramp_kinds[rn]
        cards[rn]['total'] += bonus
        if bonus:
            cards[rn]['themes']['ramp'] += bonus
    prot_bonus = round(PROTECTION_SHARE * dependence * median_total, 3)
    for n in protection_cards:
        cards[n]['protection_bonus'] = prot_bonus
        cards[n]['total'] += prot_bonus
        if prot_bonus:
            cards[n]['themes']['protection'] += prot_bonus
    for n in reactive_cards:
        cards[n]['reactive_penalty'] = reactive_penalty
        cards[n]['total'] -= reactive_penalty
    for c in cards.values():
        c['total'] = round(c['total'], 2)
        c['themes'] = {t: round(w, 2) for t, w in sorted(c['themes'].items(), key=lambda kv: -kv[1])}

    # Hooks with nothing on the other side
    unmatched = []
    for tag, cs in payoffs.items():
        for cn, cf in cs:
            if not any(m['payoff'] == cn and m['tag'] == tag for m in matches.values()):
                unmatched.append({'card': cn, 'side': 'cares', 'tag': tag, 'evidence': cf.evidence})
    for tag, ps in producers.items():
        if tag in payoffs or tag.startswith(('type:', 'kw:')) or tag in ('etb', 'cast_noncreature', 'big_power'):
            continue
        for pn, pf in ps:
            if pf.strength >= 1.0:
                unmatched.append({'card': pn, 'side': 'produces', 'tag': tag, 'evidence': pf.evidence})

    return {
        'commander': commander_name,
        'main_theme': main_theme,
        'subtheme': subtheme,
        'themes': [{'tag': t, 'label': tag_label(t), 'score': round(s, 2),
                    'producers': len({n for n, _ in producers[t]}),
                    'payoffs': len({n for n, _ in payoffs[t]})} for t, s in ranked],
        'features': {n: [f._asdict() for f in fs] for n, fs in features.items()},
        'pairs': [{'a': a, 'b': b, 'score': p['score'], 'reasons': p['reasons']}
                  for (a, b), p in sorted(pairs.items(), key=lambda kv: -kv[1]['score'])],
        'cards': cards,
        'combos': list(combos or []),
        'ramp': dict(ramp, cards=ramp_cards, kinds=ramp_kinds),
        'plans': sorted(plans),
        'commander_dependence': {'score': dependence, 'synergy_vs_average_card': cmdr_ratio,
                                 'protection_weight': prot_weight, 'protection_bonus': prot_bonus,
                                 'protection_cards': protection_cards},
        'draw': {'median_card_synergy': median_total, 'bonus': draw_bonus,
                 'cards': {k: sorted(n for n, x in draw_kinds.items() if x == k) for k in ('draw', 'selection')}},
        'reactive': {'cards': reactive_cards, 'limit': limit, 'penalty_per_card': reactive_penalty},
        'unmatched': unmatched,
    }


# ==================== Cuts ====================

ROLE_OTAGS = ['removal', 'board-wipe', 'counterspell', 'ramp', 'mana-dork', 'draw',
              'card-advantage', 'tutor', 'graveyard-hate']


def _percentiles(values):
    """Map each value to its percentile rank in [0, 1] (ties share a rank)."""
    order = sorted(values)
    n = len(order)
    if n <= 1:
        return {v: 0.5 for v in values}
    return {v: order.index(v) / (n - 1) for v in values}


def rank_cuts(result, views, commander_name=None):
    """Rank nonland, non-commander cards for cutting: low synergy and high mana
    value first. Cards with a template role (removal, ramp, draw...) and pieces of
    known combos are returned separately: synergy alone shouldn't cut them."""
    rows = []
    for v in views:
        if v['name'] == commander_name or 'Land' in v['front_types']:
            continue
        c = result['cards'].get(v['name'], {})
        rows.append({'name': v['name'], 'cmc': v['cmc'], 'synergy': c.get('total', 0.0),
                     'cmdr_fit': c.get('cmdr_fit', 0.0), 'combo_piece': c.get('combo_piece', False),
                     'roles': sorted(set(v['otags']) & set(ROLE_OTAGS))
                     + (['combo piece'] if c.get('combo_piece') else [])})
    syn_pct = _percentiles([r['synergy'] for r in rows])
    cmc_pct = _percentiles([r['cmc'] for r in rows])
    for r in rows:
        r['cut_score'] = round(syn_pct[r['synergy']] - CUT_CMC_WEIGHT * cmc_pct[r['cmc']], 3)
    rows.sort(key=lambda r: (r['cut_score'], -r['cmc'], r['name']))
    candidates = [r for r in rows if not r['roles']]
    role_cards = [r for r in rows if r['roles']]
    return candidates, role_cards


# ==================== Loading ====================

def load_views(decklist, use_otags=True):
    """Load a deck through the existing tools and return (views, commander_name)."""
    from deck_analyzer import load_deck
    all_cards, cmdr_name = load_deck(decklist)
    otags = {}
    if use_otags:
        from otag_fetcher import fetch_otags_for_cards, BASICS
        otags = fetch_otags_for_cards(sorted({c['name'] for c in all_cards if c['name'] not in BASICS}))
    views = []
    seen = set()
    for c in all_cards:
        if c['name'] in seen:
            continue
        seen.add(c['name'])
        sf = dict(c['scryfall'])
        sf['name'] = c['name']
        views.append(card_view(sf, otags.get(c['name'], [])))
    return views, (cmdr_name if cmdr_name != 'Unknown' else None)


def views_from_deck_json(path):
    """Build views from a generated deck.json (no network needed)."""
    with open(path) as f:
        d = json.load(f)
    entries = ([d['commander']] if d.get('commander') else []) + d['deck']
    seen, views = set(), []
    for e in entries:
        if e['name'] in seen:
            continue
        seen.add(e['name'])
        views.append(card_view(e))
    return views, (d['commander']['name'] if d.get('commander') else None)


def load_combos(views, commander_name, decklist=None):
    """Known combos in the deck: Commander Spellbook (cached) plus the deck's own combos.json.
    Returns None only if neither is available."""
    from combos import fetch_combos, local_combos, merge_local
    names = [v['name'] for v in views]
    commanders = [commander_name] if commander_name else []
    local = local_combos(decklist) if decklist else []
    try:
        result = fetch_combos(names, commanders)
    except Exception as e:  # network down, host not allowed: synergy still works without
        print(f"  (Commander Spellbook lookup skipped: {e})", file=sys.stderr)
        if not local:
            return None
        result = {'included': [], 'almost': []}
    return merge_local(result, local, names)['included']


# ==================== Output ====================

def _reason_line(r):
    return (f"{tag_label(r['tag'])} ({r['weight']:.2f}): {r['producer']} \"{r['producer_evidence']}\""
            f" -> {r['payoff']} \"{r['payoff_evidence']}\"")


def print_report(result, views, top=20):
    cm = result['commander']
    print(f"=== Synergy: {cm or 'no commander'} ===")
    b = result.get('bracket')
    print(f"Target bracket: {b if b is not None else f'unknown (scored as {DEFAULT_BRACKET})'}")
    r = result['ramp']
    kinds = defaultdict(int)
    for k in r['kinds'].values():
        kinds[k] += 1
    print(f"Ramp: {len(r['cards'])} cards ({', '.join(f'{n} {k}' for k, n in sorted(kinds.items()))})")
    print(f"  commander MV {r['commander_mv']:g}: up to +{r['commander_base']:g} per ramp card costing"
          f" <= {r['commander_mv'] - 2:g} (half at {r['commander_mv'] - 1:g}), creature ramp x{RAMP_CREATURE_BONUS:g},"
          f" then x{COMMANDER_BONUS:g} commander")
    print(f"  curve: avg MV {r['avg_mv']}, {len(r['expensive'])} spells at MV {RAMP_EXPENSIVE_MV}+"
          f" -> +{r['curve_bonus']:g} per ramp card")
    print(f"  land ramp: ~{r['game_turns']} turn games -> +{r['land_bonus']:g} per land-ramp card")
    d = result['commander_dependence']
    plan = ', '.join(result['plans']) or 'none in deck CLAUDE.md'
    print(f"Commander dependence: {d['score']:g} (commander synergy {d['synergy_vs_average_card']:g}x an average card;"
          f" plans: {plan}) -> +{d['protection_weight']:g} per protection card"
          f" (x{COMMANDER_BONUS:g} commander) and +{d['protection_bonus']:g} card bonus,"
          f" {len(d['protection_cards'])} protection cards")
    dr = result['draw']
    print(f"Card draw: {len(dr['cards']['draw'])} cards +{dr['bonus']['draw']:g} each, selection:"
          f" {len(dr['cards']['selection'])} cards +{dr['bonus']['selection']:g} each"
          f" (median card synergy {dr['median_card_synergy']:g})")
    rc = result['reactive']
    print(f"Reactive cards: {len(rc['cards'])} (limit {rc['limit']}) -> -{rc['penalty_per_card']:g} each\n")
    print("--- THEMES (producer -> payoff synergy) ---")
    for t in result['themes'][:10]:
        mark = ' [MAIN x%.2g]' % MAIN_THEME_BONUS if t['tag'] == result['main_theme'] else (
            ' [SUB x%.3g]' % SUBTHEME_BONUS if t['tag'] == result['subtheme'] else '')
        print(f"  {t['label']:<26s} {t['score']:7.2f}   {t['producers']:2d} producers / {t['payoffs']:2d} payoffs{mark}")

    if cm:
        print(f"\n--- COMMANDER FEATURES: {cm} ---")
        for f in result['features'].get(cm, []):
            if f['strength'] >= 1.0:
                side = 'produces' if f['side'] == 'P' else 'cares   '
                print(f"  {side} {tag_label(f['tag']):<24s} \"{f['evidence']}\"")

    print(f"\n--- TOP {top} PAIRS ---")
    for p in result['pairs'][:top]:
        print(f"  {p['score']:5.2f}  {p['a']}  +  {p['b']}")
        for r in p['reasons'][:2]:
            print(f"         {_reason_line(r)}")

    if cm:
        print(f"\n--- COMMANDER FIT (top {top}) ---")
        fit = sorted(((n, c['cmdr_fit']) for n, c in result['cards'].items() if c['cmdr_fit'] > 0),
                     key=lambda x: -x[1])
        for n, s in fit[:top]:
            print(f"  {s:5.2f}  {n}")

    print("\n--- PER-CARD SYNERGY ---")
    print(f"  {'Card':<38s} {'Total':>6s} {'Cmdr':>5s} {'#':>3s}  Best partner / main themes")
    rows = sorted(result['cards'].items(), key=lambda kv: -kv[1]['total'])
    for n, c in rows:
        themes = ', '.join(tag_label(t) for t in list(c['themes'])[:2])
        print(f"  {n[:38]:<38s} {c['total']:6.2f} {c['cmdr_fit']:5.2f} {c['partners']:3d}  "
              f"{(c['best_partner'] or '-')[:28]}  [{themes}]")

    print_unmatched(result)


def print_unmatched(result):
    if not result['unmatched']:
        return
    print("\n--- UNMATCHED HOOKS (no partner in the deck) ---")
    for u in sorted(result['unmatched'], key=lambda u: (u['side'], u['tag'], u['card'])):
        print(f"  {u['card']:<34s} {u['side']:<8s} {tag_label(u['tag']):<22s} \"{u['evidence']}\"")


def print_card(result, name):
    match = next((n for n in result['cards'] if n.lower() == name.lower()), None)
    if not match:
        print(f"Card not in deck: {name}")
        return
    c = result['cards'][match]
    print(f"=== {match}: total {c['total']:.2f}, commander fit {c['cmdr_fit']:.2f}, {c['partners']} partners ===\n")
    print("Features:")
    for f in result['features'][match]:
        side = 'produces' if f['side'] == 'P' else 'cares   '
        strength = ', weak' if f['strength'] < 1 else (f", x{f['strength']:g}" if f['strength'] > 1 else '')
        print(f"  {side} {tag_label(f['tag']):<24s} [{f['scope']}{strength}] \"{f['evidence']}\"")
    print("\nPartners:")
    for p in result['pairs']:
        if match in (p['a'], p['b']):
            other = p['b'] if p['a'] == match else p['a']
            print(f"  {p['score']:5.2f}  {other}")
            for r in p['reasons']:
                print(f"         {_reason_line(r)}")


def print_features(result):
    for n, fs in result['features'].items():
        print(f"## {n}")
        for f in sorted(fs, key=lambda f: (f['side'], f['tag'])):
            side = 'P' if f['side'] == 'P' else 'C'
            print(f"  {side} {f['tag']:<22s} {f['scope']:<5s} {f['strength']:.1f}  \"{f['evidence']}\"")


def print_cuts(candidates, role_cards, n=15):
    print(f"=== Cut candidates: low synergy + high mana value (lowest score first) ===\n")
    print(f"  {'Score':>6s} {'CMC':>3s} {'Syn':>6s} {'Cmdr':>5s}  Card")
    for r in candidates[:n]:
        combo = '  [COMBO PIECE]' if r['combo_piece'] else ''
        print(f"  {r['cut_score']:6.2f} {r['cmc']:3.0f} {r['synergy']:6.2f} {r['cmdr_fit']:5.2f}  {r['name']}{combo}")
    if role_cards:
        print("\n--- Role cards and combo pieces (not cut candidates by synergy alone) ---")
        for r in role_cards[:n]:
            print(f"  {r['cut_score']:6.2f} {r['cmc']:3.0f} {r['synergy']:6.2f} {r['cmdr_fit']:5.2f}  "
                  f"{r['name']}  [{', '.join(r['roles'])}]")


def to_json(result, candidates=None, role_cards=None):
    """JSON-ready result. Pair reasons keep tag, direction and weight only; the
    card text behind each tag is in `features`, so it is not repeated per pair."""
    out = {k: v for k, v in result.items() if k not in ('features', 'pairs')}
    out['pairs'] = [{'a': p['a'], 'b': p['b'], 'score': p['score'],
                     'reasons': [{'tag': r['tag'], 'producer': r['producer'], 'payoff': r['payoff'],
                                  'weight': r['weight']} for r in p['reasons']]}
                    for p in result['pairs']]
    out['features'] = {n: [{k: f[k] for k in ('tag', 'side', 'scope', 'strength', 'evidence')} for f in fs]
                       for n, fs in result['features'].items()}
    if candidates is not None:
        out['cuts'] = {'candidates': candidates, 'role_cards': role_cards}
    return out


def default_save_path(decklist):
    return os.path.join(os.path.dirname(os.path.abspath(decklist)), 'synergy.json')


# ==================== CLI ====================

def main():
    if hasattr(signal, 'SIGPIPE'):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet exit when piped into head
    ap = argparse.ArgumentParser(description='Card synergy calculator for a Commander deck')
    ap.add_argument('decklist', help='Path to decklist.txt (or a deck.json)')
    ap.add_argument('--top', type=int, default=20, help='How many pairs/cards to list')
    ap.add_argument('--card', type=str, help='Show one card\'s features and partners')
    ap.add_argument('--cuts', nargs='?', const=15, type=int, help='Cut candidates (synergy + mana value)')
    ap.add_argument('--features', action='store_true', help='Dump extracted features per card')
    ap.add_argument('--json', action='store_true', help='Print the full result as JSON')
    ap.add_argument('--save', nargs='?', const='', help='Write JSON to decks/<deck>/synergy.json (or a path)')
    ap.add_argument('--no-otags', action='store_true', help='Skip Scryfall otags (no extra network calls)')
    ap.add_argument('--no-combos', action='store_true', help='Skip Commander Spellbook combo lookup')
    args = ap.parse_args()

    print(f"Loading deck from {args.decklist}...", file=sys.stderr)
    if args.decklist.endswith('.json'):
        views, cmdr = views_from_deck_json(args.decklist)
    else:
        views, cmdr = load_views(args.decklist, use_otags=not args.no_otags)
    combos = None if args.no_combos else load_combos(views, cmdr, args.decklist)
    from combos import deck_bracket
    bracket = deck_bracket(args.decklist)
    result = compute_synergy(views, cmdr, combos, bracket, deck_plan(args.decklist))
    result['bracket'] = bracket
    candidates, role_cards = rank_cuts(result, views, cmdr)

    if args.save is not None:
        path = args.save or default_save_path(args.decklist)
        with open(path, 'w') as f:
            json.dump(to_json(result, candidates, role_cards), f, indent=1, ensure_ascii=False)
        print(f"Wrote {path}", file=sys.stderr)

    if args.json:
        json.dump(to_json(result, candidates, role_cards), sys.stdout, indent=1, ensure_ascii=False)
        print()
    elif args.card:
        print_card(result, args.card)
    elif args.features:
        print_features(result)
    elif args.cuts is not None:
        print_cuts(candidates, role_cards, args.cuts)
    else:
        print_report(result, views, args.top)


if __name__ == '__main__':
    main()
