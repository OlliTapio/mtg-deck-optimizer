"""Tests for combos.py: parsing Commander Spellbook results and bracket flags (no network)."""
import json

from combos import _compact, bracket_flag, deck_key, local_combos, merge_local


def _variant(cards, produces, tag='E'):
    return {'id': '1-2', 'uses': [{'card': {'name': c}} for c in cards],
            'produces': [{'feature': {'name': p}} for p in produces], 'requires': [],
            'bracketTag': tag, 'popularity': 10, 'description': 'Step 1.\nStep 2.',
            'easyPrerequisites': 'A has a counter.\nB is on the battlefield.', 'notablePrerequisites': ''}


def test_compact_marks_missing_cards_and_infinite():
    c = _compact(_variant(['Fathom Mage', 'Wizard Class'], ['Infinite card draw']), ['Fathom Mage'])
    assert c['missing'] == ['Wizard Class']
    assert c['infinite']
    assert '\n' not in c['prerequisites']


def test_mdfc_front_face_counts_as_in_deck():
    c = _compact(_variant(['Boggart Trawler', 'X'], ['Infinite mill']), ['Boggart Trawler // Boggart Bog', 'X'])
    assert c['missing'] == []


def test_bracket_flags():
    two = _compact(_variant(['A', 'B'], ['Infinite damage']), ['A', 'B'])
    three = _compact(_variant(['A', 'B', 'C'], ['Infinite damage']), ['A', 'B', 'C'])
    assert 'not allowed' in bracket_flag(two, 2)
    assert 'bracket 3' in bracket_flag(two, 3)
    assert bracket_flag(two, 4) == ''
    assert bracket_flag(three, 3) == ''
    assert bracket_flag(three, None) == ''
    ruthless = _compact(_variant(['A', 'B', 'C'], ['Win the game'], tag='R'), ['A', 'B', 'C'])
    assert 'Ruthless' in bracket_flag(ruthless, 3)


def test_deck_key_ignores_order():
    assert deck_key(['A', 'B'], ['C']) == deck_key(['B', 'A'], ['C'])
    assert deck_key(['A', 'B'], ['C']) != deck_key(['A', 'B', 'D'], ['C'])


def test_local_combos_merge(tmp_path):
    (tmp_path / 'combos.json').write_text(json.dumps([
        {'cards': ['A', 'B', 'C'], 'produces': ['Near-infinite mill']},
        {'cards': ['A', 'Z'], 'produces': ['Infinite damage']},
    ]))
    local = local_combos(str(tmp_path / 'decklist.txt'))
    assert local[0]['infinite'] and local[0]['source'] == 'deck combos.json'
    merged = merge_local({'included': [], 'almost': []}, local, ['A', 'B', 'C'])
    assert [c['cards'] for c in merged['included']] == [['A', 'B', 'C']]
    assert merged['almost'][0]['missing'] == ['Z']


def test_no_local_combos_file(tmp_path):
    assert local_combos(str(tmp_path / 'decklist.txt')) == []
