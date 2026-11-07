"""Tests for synergy.py: feature extraction, scoring rules and cut ranking."""
import os

import pytest

from synergy import (card_view, compute_synergy, extract_features, rank_cuts, combo_weight, is_wincon,
                     views_from_deck_json, COMBO_WEIGHT, COMMANDER_BONUS, MAIN_THEME_BONUS)


def _card(name, type_line, oracle, keywords=(), power=None, otags=(), cmc=3):
    return card_view({'name': name, 'type_line': type_line, 'oracle_text': oracle,
                      'keywords': list(keywords), 'power': power, 'cmc': cmc}, list(otags))


def _feats(view, subtypes=frozenset()):
    return {(f.tag, f.side, f.scope) for f in extract_features(view, subtypes)}


def _pair(result, a, b):
    for p in result['pairs']:
        if {p['a'], p['b']} == {a, b}:
            return p
    return None


# Real oracle texts
BLOOD_ARTIST = _card('Blood Artist', 'Creature — Vampire',
                     'Whenever Blood Artist or another creature dies, target player loses 1 life and you gain 1 life.',
                     power=0, cmc=2)
DOOMED_TRAVELER = _card('Doomed Traveler', 'Creature — Human Soldier',
                        'When Doomed Traveler dies, create a 1/1 white Spirit creature token with flying.',
                        power=1, cmc=1)
VISCERA_SEER = _card('Viscera Seer', 'Creature — Vampire Wizard',
                     'Sacrifice a creature: Scry 1.', power=1, cmc=1)
HARDENED_SCALES = _card('Hardened Scales', 'Enchantment',
                        'If one or more +1/+1 counters would be put on a creature you control, that many plus one '
                        '+1/+1 counters are put on it instead.', cmc=1)
FATHOM_MAGE = _card('Fathom Mage', 'Creature — Human Wizard',
                    'Evolve (Whenever a creature you control enters, if that creature has greater power or toughness '
                    'than this creature, put a +1/+1 counter on this creature.)\n'
                    'Whenever a +1/+1 counter is put on this creature, you may draw a card.',
                    keywords=['Evolve'], power=1, cmc=4)
TRISKELION = _card('Triskelion', 'Artifact Creature — Construct',
                   'This creature enters with three +1/+1 counters on it.\n'
                   'Remove a +1/+1 counter from this creature: It deals 1 damage to any target.', power=1, cmc=6)
YAHENNI = _card('Yahenni, Undying Partisan', 'Legendary Creature — Aetherborn',
                'Haste\nWhenever a creature an opponent controls dies, put a +1/+1 counter on Yahenni, Undying Partisan.\n'
                'Sacrifice another creature: Yahenni gains indestructible until end of turn.',
                keywords=['Haste'], power=2, cmc=3)
PSYCHIC_CORROSION = _card('Psychic Corrosion', 'Enchantment',
                          'Whenever you draw a card, each opponent mills two cards.', keywords=['Mill'], cmc=3)
MOTHMAN = _card('The Wise Mothman', 'Legendary Creature — Insect Mutant',
                'Flying\nWhenever The Wise Mothman enters or attacks, each player gets a rad counter.\n'
                'Whenever one or more nonland cards are milled, put a +1/+1 counter on each of up to X target '
                'creatures, where X is the number of nonland cards milled this way.',
                keywords=['Flying'], power=3, cmc=4)
GOBLIN_LORD = _card('Goblin King', 'Creature — Goblin',
                    'Other Goblin creatures get +1/+1 and have mountainwalk.', power=2, cmc=3)
GOBLIN = _card('Goblin Piker', 'Creature — Goblin Warrior', "Goblin Piker can't block.", power=2, cmc=2)
ELF = _card('Llanowar Elves', 'Creature — Elf Druid', '{T}: Add {G}.', power=1, cmc=1)
MORPH = _card('Hidden Thing', 'Creature — Beast',
              'Morph {3}{G} (You may cast this card face down as a 2/2 creature for {3}. '
              'Turn it face up any time for its morph cost.)', keywords=['Morph'], power=3, cmc=4)


class TestExtraction:
    def test_death_payoff(self):
        assert ('dies', 'C', 'any') in _feats(BLOOD_ARTIST)

    def test_self_dies_is_fodder_and_token_maker(self):
        f = _feats(DOOMED_TRAVELER)
        assert ('fodder', 'P', 'self') in f
        assert ('token_creature', 'P', 'yours') in f

    def test_sac_outlet_from_cost(self):
        f = _feats(VISCERA_SEER)
        assert ('sacrifice', 'P', 'yours') in f
        assert ('fodder', 'C', 'yours') in f

    def test_doubler_both_sides(self):
        f = _feats(HARDENED_SCALES)
        assert ('counters_p1p1', 'C', 'yours') in f
        assert ('counters_p1p1', 'P', 'yours') in f

    def test_own_name_is_self(self):
        f = _feats(FATHOM_MAGE)
        assert ('counters_p1p1', 'C', 'self') in f
        assert ('draw', 'P', 'yours') in f

    def test_rad_also_produces_mill(self):
        f = _feats(MOTHMAN)
        assert ('rad', 'P', 'any') in f
        assert ('mill', 'P', 'any') in f
        assert ('mill', 'C', 'any') in f

    def test_counter_axes_are_separate(self):
        ool = _card('Auntie Ool, Cursewretch', 'Legendary Creature — Goblin Warlock',
                    'Whenever one or more -1/-1 counters are put on a creature, draw a card if you control '
                    'that creature.', power=4)
        f = _feats(ool)
        assert ('counters_m1m1', 'C', 'any') in f
        assert not any(t == 'counters_p1p1' for t, _, _ in f)
        r = compute_synergy([ool, HARDENED_SCALES])
        assert _pair(r, 'Auntie Ool, Cursewretch', 'Hardened Scales') is None

    def test_reminder_text_ignored(self):
        assert not any(t == 'token_creature' for t, _, _ in _feats(MORPH))

    def test_split_card_uses_all_faces(self):
        v = card_view({'name': 'Find // Finality', 'type_line': 'Sorcery // Sorcery', 'cmc': 6, 'keywords': [],
                       'card_faces': [
                           {'name': 'Find', 'type_line': 'Sorcery',
                            'oracle_text': 'Return up to two target creature cards from your graveyard to your hand.'},
                           {'name': 'Finality', 'type_line': 'Sorcery',
                            'oracle_text': 'You may put two +1/+1 counters on a creature you control. '
                                           'Then all creatures get -4/-4 until end of turn.'}]})
        f = _feats(v)
        assert ('graveyard', 'C', 'yours') in f
        assert ('counters_p1p1', 'P', 'yours') in f

    def test_mdfc_front_face_decides_land(self):
        v = card_view({'name': 'Spell // Land', 'type_line': 'Instant // Land', 'keywords': [],
                       'card_faces': [{'name': 'Spell', 'type_line': 'Instant', 'oracle_text': 'Draw a card.'},
                                      {'name': 'Land', 'type_line': 'Land', 'oracle_text': '{T}: Add {G}.'}]})
        assert 'Land' not in v['front_types']


class TestScoping:
    def test_opponent_only_payoff_does_not_pair(self):
        r = compute_synergy([YAHENNI, DOOMED_TRAVELER])
        p = _pair(r, YAHENNI['name'], DOOMED_TRAVELER['name'])
        assert p is None or all(x['tag'] != 'dies' for x in p['reasons'])

    def test_self_counters_do_not_feed_self_payoff(self):
        r = compute_synergy([TRISKELION, FATHOM_MAGE])
        p = _pair(r, 'Triskelion', 'Fathom Mage')
        assert p is None or all(x['tag'] != 'counters_p1p1' for x in p['reasons'])

    def test_doubler_feeds_self_payoff(self):
        r = compute_synergy([TRISKELION, HARDENED_SCALES])
        assert _pair(r, 'Triskelion', 'Hardened Scales')['score'] > 0

    def test_no_self_pairs(self):
        r = compute_synergy([HARDENED_SCALES])
        assert r['pairs'] == []


class TestTribalAndKeywords:
    def test_tribal(self):
        r = compute_synergy([GOBLIN_LORD, GOBLIN, ELF])
        assert _pair(r, 'Goblin King', 'Goblin Piker')['score'] > 0
        assert _pair(r, 'Goblin King', 'Llanowar Elves') is None

    def test_changeling_counts_as_every_type(self):
        shape = _card('Universal Shapeshifter', 'Creature — Shapeshifter', 'Changeling', keywords=['Changeling'])
        r = compute_synergy([GOBLIN_LORD, shape])
        assert _pair(r, 'Goblin King', 'Universal Shapeshifter')['score'] > 0

    def test_keyword_payoff(self):
        lord = _card('Sky Lord', 'Creature — Bird', 'Creatures you control with flying get +1/+1.', power=2)
        r = compute_synergy([lord, MOTHMAN])
        assert any(x['tag'] == 'kw:Flying' for x in _pair(r, 'Sky Lord', 'The Wise Mothman')['reasons'])

    def test_plain_creatures_do_not_pair(self):
        a = _card('Bear A', 'Creature — Bear', '', power=2)
        b = _card('Bear B', 'Creature — Ox', '', power=2)
        assert compute_synergy([a, b])['pairs'] == []


class TestScoring:
    def test_theme_needs_payoff(self):
        """Ten foretell cards with nothing that cares about casting from exile score nothing."""
        foretell = [_card(f'Foretell {i}', 'Instant', 'Foretell {1}{U}\nDraw a card.', keywords=['Foretell'])
                    for i in range(10)]
        r = compute_synergy(foretell)
        assert all(t['tag'] != 'cast_exile' for t in r['themes'])
        payoff = _card('Exile Payoff', 'Creature — Wizard',
                       'Whenever you cast a spell from exile, draw a card.', power=2)
        r2 = compute_synergy(foretell + [payoff])
        assert any(t['tag'] == 'cast_exile' for t in r2['themes'])

    def test_denser_theme_scores_more(self):
        outlets = [_card(f'Outlet {i}', 'Creature — Vampire', 'Sacrifice a creature: Scry 1.', power=1)
                   for i in range(4)]
        few = compute_synergy([BLOOD_ARTIST, outlets[0]])['cards']['Blood Artist']['total']
        many = compute_synergy([BLOOD_ARTIST] + outlets)['cards']['Blood Artist']['total']
        assert many > few

    def test_main_theme_bonus(self):
        r = compute_synergy([HARDENED_SCALES, TRISKELION, FATHOM_MAGE, BLOOD_ARTIST, VISCERA_SEER])
        assert r['main_theme'] == 'counters_p1p1'
        p = _pair(r, 'Triskelion', 'Hardened Scales')
        assert p['reasons'][0]['weight'] == pytest.approx(1.0 * MAIN_THEME_BONUS)

    def test_commander_bonus(self):
        plain = compute_synergy([HARDENED_SCALES, TRISKELION])
        cmdr = compute_synergy([HARDENED_SCALES, TRISKELION], commander_name='Triskelion')
        a = _pair(plain, 'Triskelion', 'Hardened Scales')['score']
        b = _pair(cmdr, 'Triskelion', 'Hardened Scales')['score']
        assert b == pytest.approx(a * COMMANDER_BONUS)
        assert cmdr['cards']['Hardened Scales']['cmdr_fit'] == b

    def test_every_score_has_reasons(self):
        r = compute_synergy([BLOOD_ARTIST, DOOMED_TRAVELER, VISCERA_SEER, HARDENED_SCALES, TRISKELION])
        for p in r['pairs']:
            assert p['score'] > 0 and p['reasons']


class TestCombos:
    COMBO = {'cards': ['Vigor', 'Triskelion', 'Hardened Scales'], 'produces': ['Infinite damage'],
             'url': 'https://commanderspellbook.com/combo/x/'}
    VIGOR = _card('Vigor', 'Creature — Elemental Incarnation',
                  'Trample\nIf damage would be dealt to another creature you control, prevent that damage. '
                  'Put a +1/+1 counter on that creature for each 1 damage prevented this way.',
                  keywords=['Trample'], power=6, cmc=6)

    def test_combo_pieces_get_bonus_and_flag(self):
        views = [self.VIGOR, TRISKELION, HARDENED_SCALES]
        plain = compute_synergy(views)
        with_combo = compute_synergy(views, combos=[self.COMBO])
        assert _pair(with_combo, 'Vigor', 'Hardened Scales')['score'] > _pair(plain, 'Vigor', 'Hardened Scales')['score']
        assert any(r['tag'] == 'combo_win' for r in _pair(with_combo, 'Vigor', 'Triskelion')['reasons'])
        assert with_combo['cards']['Vigor']['combo_piece']
        assert all(not t['tag'].startswith('combo') for t in with_combo['themes'])
        candidates, protected = rank_cuts(with_combo, views)
        assert 'Vigor' not in [x['name'] for x in candidates]
        assert 'combo piece' in next(x for x in protected if x['name'] == 'Vigor')['roles']

    def test_wincon_detection(self):
        assert is_wincon({'produces': ['Infinite damage']})
        assert is_wincon({'produces': ['Each opponent loses the game']})
        assert is_wincon({'produces': ['Near-infinite lifeloss']})
        assert not is_wincon({'produces': ['Infinite colored mana', 'Infinite creature ETB']})
        assert not is_wincon({'produces': ['Near-infinite damage to creatures']})
        assert not is_wincon({'produces': ['Infinite self-mill']})

    def test_wincon_weight_decays_fast_with_bracket(self):
        w = {b: combo_weight(self.COMBO, b) for b in (1, 2, 3, 4)}
        assert w[4] > w[3] > w[2] > w[1] > COMBO_WEIGHT
        bonus = {b: w[b] - COMBO_WEIGHT for b in w}
        assert bonus[3] < bonus[4] / 2 and bonus[2] < bonus[3] / 2 and bonus[1] < bonus[2] / 2
        mana = {'cards': ['A', 'B'], 'produces': ['Infinite colored mana']}
        assert combo_weight(mana, 4) == combo_weight(mana, 1) == COMBO_WEIGHT

    def test_bracket_changes_pair_score(self):
        views = [self.VIGOR, TRISKELION, HARDENED_SCALES]
        b4 = _pair(compute_synergy(views, combos=[self.COMBO], bracket=4), 'Vigor', 'Triskelion')['score']
        b2 = _pair(compute_synergy(views, combos=[self.COMBO], bracket=2), 'Vigor', 'Triskelion')['score']
        assert b4 > b2

    def test_combo_needs_every_piece_in_deck(self):
        r = compute_synergy([self.VIGOR, TRISKELION], combos=[self.COMBO])
        assert not r['cards']['Vigor']['combo_piece']


class TestRamp:
    DORK = _card('Llanowar Elves', 'Creature — Elf Druid', '{T}: Add {G}.', power=1, cmc=1)
    ROCK = _card('Mind Stone', 'Artifact', '{T}: Add {C}.', cmc=2)

    @staticmethod
    def _cmdr(cmc):
        return _card('Big Boss', 'Legendary Creature — Giant', '', power=6, cmc=cmc)

    @staticmethod
    def _spells(cmc, n=6):
        return [_card(f'Spell {cmc}-{i}', 'Sorcery', 'Target player sacrifices a land.', cmc=cmc) for i in range(n)]

    def test_detects_ramp_not_lands(self):
        from synergy import is_ramp
        land = _card('Forest Thing', 'Land', '{T}: Add {G}.', cmc=0)
        assert is_ramp(self.DORK) and is_ramp(self.ROCK) and not is_ramp(land)

    def test_expensive_commander_values_ramp_more(self):
        cheap = compute_synergy([self._cmdr(3), self.DORK], 'Big Boss')
        pricey = compute_synergy([self._cmdr(7), self.DORK], 'Big Boss')
        assert cheap['cards']['Llanowar Elves']['cmdr_fit'] == 0
        assert pricey['cards']['Llanowar Elves']['cmdr_fit'] > 0

    def test_high_curve_values_ramp_more(self):
        low = compute_synergy([self._cmdr(3), self.DORK, self.ROCK] + self._spells(2), 'Big Boss')
        high = compute_synergy([self._cmdr(3), self.DORK, self.ROCK] + self._spells(6), 'Big Boss')
        assert high['cards']['Mind Stone']['total'] > low['cards']['Mind Stone']['total']
        assert low['cards']['Mind Stone']['ramp_bonus'] == 0

    def test_ramp_is_not_a_combo_piece(self):
        r = compute_synergy([self._cmdr(7), self.DORK], 'Big Boss')
        assert not r['cards']['Llanowar Elves']['combo_piece']


class TestCuts:
    def test_low_synergy_high_cmc_first_and_roles_apart(self):
        filler = _card('Big Vanilla', 'Creature — Beast', '', power=5, cmc=7)
        removal = _card('Murder', 'Instant', 'Destroy target creature.', otags=['removal'], cmc=3)
        views = [MOTHMAN, PSYCHIC_CORROSION, FATHOM_MAGE, HARDENED_SCALES, filler, removal]
        r = compute_synergy(views, 'The Wise Mothman')
        candidates, roles = rank_cuts(r, views, 'The Wise Mothman')
        assert candidates[0]['name'] == 'Big Vanilla'
        assert [x['name'] for x in roles] == ['Murder']
        assert 'The Wise Mothman' not in [x['name'] for x in candidates]


DECK_JSON = os.path.join(os.path.dirname(__file__), 'decks', 'wise_mothman', 'deck.json')


@pytest.fixture(scope='module')
def result():
    views, cmdr = views_from_deck_json(DECK_JSON)
    return compute_synergy(views, cmdr)


@pytest.mark.skipif(not os.path.exists(DECK_JSON), reason='wise_mothman deck.json missing')
class TestRealDeck:
    def test_main_theme_is_counters(self, result):
        assert result['main_theme'] == 'counters_p1p1'

    def test_combo_b_pieces_pair(self, result):
        """Mothman + Fathom Mage + Psychic Corrosion (deck CLAUDE.md, combo B)."""
        assert _pair(result, 'The Wise Mothman', 'Fathom Mage')['score'] > 0
        assert _pair(result, 'Fathom Mage', 'Psychic Corrosion')['score'] > 0
        assert _pair(result, 'Psychic Corrosion', 'The Wise Mothman')['score'] > 0

    def test_combo_a_pieces_pair(self, result):
        """Triskelion + Vigor + counter doubler (deck CLAUDE.md, combo A)."""
        assert _pair(result, 'Triskelion', 'Vigor')['score'] > 0
        assert _pair(result, 'Triskelion', 'Hardened Scales')['score'] > 0

    def test_doubler_ranks_high(self, result):
        top = sorted(result['cards'], key=lambda n: -result['cards'][n]['total'])[:20]
        assert 'Hardened Scales' in top
