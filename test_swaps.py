"""Tests for swaps.py: proposed swaps vs the Archidekt decklist (no network)."""
import json

from swaps import deck_counts, parse_swaps, proposed_text, status, swaps_version

DECK = """1x The Wise Mothman (pip) 4 [Commander]
1x Sol Ring (cmm) 410 [Ramp]
1x Rampant Growth (m10) 1 [Ramp]
5x Forest (pip) 321 [Land]
"""
MAYBE = "1x Hardened Scales (ktk) 133 [Maybeboard{noDeck}{noPrice}]\n"
SWAPS = """# archidekt-version: v1
Rampant Growth -> Hardened Scales  # counters
- Sol Ring
+ Nature's Lore
2x Forest -> 2x Swamp
"""


def _setup(tmp_path, version='v1'):
    (tmp_path / 'decklist.txt').write_text(DECK)
    (tmp_path / 'maybelist.txt').write_text(MAYBE)
    (tmp_path / 'swaps.txt').write_text(SWAPS)
    (tmp_path / 'source.json').write_text(json.dumps({'updated_at': version}))
    return deck_counts(str(tmp_path / 'decklist.txt')), parse_swaps(str(tmp_path / 'swaps.txt'))


def test_parse_swaps(tmp_path):
    _, swaps = _setup(tmp_path)
    assert [(s['out'], s['in']) for s in swaps] == [
        (('Rampant Growth', 1), ('Hardened Scales', 1)),
        (('Sol Ring', 1), None),
        (None, ("Nature's Lore", 1)),
        (('Forest', 2), ('Swamp', 2)),
    ]
    assert swaps[0]['reason'] == 'counters'
    assert swaps_version(str(tmp_path / 'swaps.txt')) == 'v1'


def test_unchanged_archidekt_means_all_pending(tmp_path):
    counts, swaps = _setup(tmp_path)
    assert [status(s, counts, unchanged=True) for s in swaps] == ['pending'] * 4


def test_changed_archidekt_judged_by_cards(tmp_path):
    counts, swaps = _setup(tmp_path)
    counts['Rampant Growth'] = 0
    counts['Hardened Scales'] = 1
    counts['Sol Ring'] = 0
    assert [status(s, counts) for s in swaps] == ['done', 'done', 'pending', 'check']
    counts['Sol Ring'] = 1
    counts['Rampant Growth'] = 1
    assert status(swaps[0], counts) == 'stale'


def test_proposed_text_applies_swaps(tmp_path):
    counts, swaps = _setup(tmp_path)
    text = proposed_text(str(tmp_path / 'decklist.txt'), str(tmp_path / 'maybelist.txt'),
                         swaps, counts, unchanged=True)
    out = tmp_path / 'proposed.txt'
    out.write_text(text)
    new = deck_counts(str(out))
    assert new['Rampant Growth'] == 0 and new['Sol Ring'] == 0
    assert new['Hardened Scales'] == 1 and new["Nature's Lore"] == 1
    assert new['Forest'] == 3 and new['Swamp'] == 2
    assert '1x Hardened Scales (ktk) 133 [Proposed]' in text
    assert sum(new.values()) == sum(counts.values())


def test_buy_tag_and_stages(tmp_path):
    from swaps import end_counts, stage
    counts, _ = _setup(tmp_path)
    (tmp_path / 'swaps.txt').write_text("# archidekt-version: v1\n"
                                        "Rampant Growth -> Hardened Scales [buy]  # counters\n"
                                        "Sol Ring -> Nature's Lore\n")
    swaps = parse_swaps(str(tmp_path / 'swaps.txt'))
    assert swaps[0]['buy'] and swaps[0]['in'] == ('Hardened Scales', 1) and swaps[0]['reason'] == 'counters'
    assert not swaps[1]['buy']
    assert [stage(s, counts, unchanged=True) for s in swaps] == ['buy', 'ready']
    end = end_counts(counts, swaps, unchanged=True)
    assert end['Hardened Scales'] == 1 and end['Rampant Growth'] == 0
    assert sum(end.values()) == sum(counts.values())
    counts['Sol Ring'] = 0
    counts["Nature's Lore"] = 1
    assert stage(swaps[1], counts) == 'done'
