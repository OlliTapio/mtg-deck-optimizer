"""Tests for archidekt.py: deck JSON -> decklist.txt conversion (no network)."""
import pytest

from archidekt import parse_deck_id, summarize_changes, to_decklist
from parser import parse_decklist


def _entry(name, cats, qty=1, foil=False, edition='pip', number='4'):
    return {'quantity': qty, 'categories': cats, 'modifier': 'Foil' if foil else 'Normal', 'deletedAt': None,
            'card': {'oracleCard': {'name': name}, 'edition': {'editioncode': edition}, 'collectorNumber': number}}


DECK = {
    'name': 'Test Deck',
    'categories': [
        {'name': 'Commander', 'isPremier': True, 'includedInDeck': True, 'includedInPrice': True},
        {'name': 'Ramp', 'isPremier': False, 'includedInDeck': True, 'includedInPrice': True},
        {'name': 'Land', 'isPremier': False, 'includedInDeck': True, 'includedInPrice': True},
        {'name': 'Maybeboard', 'isPremier': False, 'includedInDeck': False, 'includedInPrice': False},
    ],
    'cards': [
        _entry('Sol Ring', ['Ramp'], edition='cmm', number='410'),
        _entry('The Wise Mothman', ['Commander'], foil=True),
        _entry('Forest', ['Land'], qty=5, edition='pip', number='321'),
        _entry('Hardened Scales', ['Maybeboard'], edition='ktk', number='133'),
        _entry('Boggart Trawler // Boggart Bog', ['Ramp', 'Land'], edition='mh3', number='80'),
    ],
}


def test_round_trip_through_parser(tmp_path):
    path = tmp_path / 'decklist.txt'
    path.write_text(to_decklist(DECK))
    lines = path.read_text().splitlines()
    assert lines[0] == '1x The Wise Mothman (pip) 4 *F* [Commander]'
    assert '1x Hardened Scales (ktk) 133 [Maybeboard{noDeck}{noPrice}]' in lines
    parsed = parse_decklist(str(path))
    assert parsed['commander']['name'] == 'The Wise Mothman'
    names = [c['name'] for c in parsed['deck']]
    assert 'Hardened Scales' not in names
    assert names.count('Forest') == 5 or sum(c['count'] for c in parsed['deck'] if c['name'] == 'Forest') == 5
    assert 'Boggart Trawler // Boggart Bog' in names


@pytest.mark.parametrize('ref', ['25455075', 'https://archidekt.com/decks/25455075/the_wise_mothman',
                                 'archidekt.com/decks/25455075'])
def test_parse_deck_id(ref):
    assert parse_deck_id(ref) == 25455075


def test_parse_deck_id_rejects_junk():
    with pytest.raises(ValueError):
        parse_deck_id('moxfield.com/decks/abc')


def test_change_summary_ignores_maybeboard():
    old = '1x A (s) 1 [Ramp]\n1x B (s) 2 [Ramp]\n'
    new = '1x A (s) 1 [Ramp]\n1x C (s) 3 [Ramp]\n1x D (s) 4 [Maybeboard{noDeck}{noPrice}]\n'
    added, removed = summarize_changes(old, new)
    assert added == [('C', 1)] and removed == [('B', 1)]
