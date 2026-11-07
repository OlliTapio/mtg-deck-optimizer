#!/usr/bin/env python3
"""Proposed swaps for a deck, kept apart from the Archidekt list.

Each deck has three lists:
  decklist.txt   the deck on Archidekt (source of truth, written only by archidekt.py pull)
  maybelist.txt  the Archidekt maybeboard (written only by archidekt.py pull)
  swaps.txt      swaps proposed here, waiting to be made on Archidekt

swaps.txt, one swap per line, '#' starts a comment (the reason):
  Watchful Radstag -> Shadowspear   # protection for the commander
  - Rampant Growth                  # cut only
  + Nature's Lore                   # add only
Counts are optional ("2x Forest -> 2x Swamp") and mean how many to cut or add.
The header line '# archidekt-version: <updated_at>' records which Archidekt version
the swaps were written against: while Archidekt is unchanged every swap is pending;
after it changes, swaps are judged by which cards are in the deck.

Usage:
  python3 swaps.py decks/<deck> --init                   # start a swaps.txt for the deck
  python3 swaps.py decks/<deck>                          # status of each swap against the Archidekt list
  python3 swaps.py decks/<deck> --write                  # decks/<deck>/proposed.txt: Archidekt + open swaps
  python3 swaps.py decks/<deck> --prune                  # drop swaps that are done on Archidekt

Analyse the proposed deck by pointing the tools at proposed.txt (kept in the deck folder
so they still find its CLAUDE.md, source.json and combos.json; it is gitignored):
  python3 swaps.py decks/<deck> --write && python3 synergy.py decks/<deck>/proposed.txt
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

from parser import parse_decklist

COUNT_RE = re.compile(r'^(\d+)x?\s+(.+)$')


def _card(text):
    """'2x Forest' -> ('Forest', 2); '' -> None."""
    text = text.strip()
    if not text:
        return None
    m = COUNT_RE.match(text)
    if m:
        return m.group(2).strip(), int(m.group(1))
    return text, 1


def parse_swaps(path):
    """swaps.txt -> list of dicts: out, in (each (name, count) or None), reason, line."""
    swaps = []
    if not os.path.exists(path):
        return swaps
    with open(path) as f:
        for raw in f:
            body, _, reason = raw.partition('#')
            body = body.strip()
            if not body:
                continue
            if '->' in body:
                out, _, inn = body.partition('->')
                out, inn = _card(out), _card(inn)
            elif body.startswith('-'):
                out, inn = _card(body[1:]), None
            elif body.startswith('+'):
                out, inn = None, _card(body[1:])
            else:
                print(f"WARN: not a swap (use 'Out -> In', '- Out' or '+ In'): {raw.rstrip()}",
                      file=sys.stderr)
                continue
            if out is None and inn is None:
                continue
            swaps.append({'out': out, 'in': inn, 'reason': reason.strip(), 'line': raw.rstrip('\n')})
    return swaps


def deck_counts(decklist):
    parsed = parse_decklist(decklist)
    counts = Counter()
    for c in parsed['deck'] + ([parsed['commander']] if parsed['commander'] else []):
        counts[c['name']] += c['count']
    return counts


BASICS = {'Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes'}
VERSION_RE = re.compile(r'^#\s*archidekt-version:\s*(\S+)', re.M)
HEADER = """# Proposed swaps, not yet made on Archidekt. Archidekt (decklist.txt) is the source of truth.
# Format: Out -> In  # reason   |   - Out  (cut only)   |   + In  (add only)
# archidekt-version: {version}
"""


def is_basic(name):
    return name.replace('Snow-Covered ', '') in BASICS


def archidekt_version(folder):
    """updated_at of the Archidekt deck as last pulled (source.json), or None."""
    path = os.path.join(folder, 'source.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f).get('updated_at')


def swaps_version(path):
    """The Archidekt version the swaps were written against (header line), or None."""
    if not os.path.exists(path):
        return None
    m = VERSION_RE.search(open(path).read())
    return m.group(1) if m else None


def status(swap, counts, unchanged=False):
    """Where a swap stands against the Archidekt list.

    unchanged: Archidekt has not changed since the swaps were written, so every
    swap whose cut is still in the deck is pending. Otherwise the swap is judged
    by which cards are there: 'done', 'pending', 'stale' (neither) or 'check'
    (basic lands or counts above one: a count is a change, which presence can't show).
    """
    out, inn = swap['out'], swap['in']
    out_there = out is not None and counts[out[0]] >= out[1]
    in_there = inn is not None and counts[inn[0]] >= inn[1]
    if unchanged:
        ok_out = out is None or out_there
        ok_in = inn is None or is_basic(inn[0]) or inn[1] > 1 or not in_there
        return 'pending' if ok_out and ok_in else 'stale'
    if any(c is not None and (is_basic(c[0]) or c[1] > 1) for c in (out, inn)):
        return 'check'
    if (out is None or not out_there) and (inn is None or in_there):
        return 'done'
    if (out is None or out_there) and (inn is None or not in_there):
        return 'pending'
    return 'stale'


def _fmt(card):
    if card is None:
        return ''
    name, n = card
    return f'{n}x {name}' if n > 1 else name


def describe(swap):
    out, inn = _fmt(swap['out']), _fmt(swap['in'])
    s = f'{out} -> {inn}' if out and inn else (f'- {out}' if out else f'+ {inn}')
    return s + (f'   # {swap["reason"]}' if swap['reason'] else '')


def proposed_text(decklist, maybelist, swaps, counts, unchanged=False):
    """Archidekt decklist with every pending swap applied, in the same export format."""
    maybe_lines = {}
    if os.path.exists(maybelist):
        for line in open(maybelist):
            m = re.match(r'^\d+x\s+(.+?)\s+\(', line)
            if m:
                maybe_lines[m.group(1)] = re.sub(r'\[[^\]]*\]\s*$', '[Proposed]', line.strip())
    lines = [l.rstrip('\n') for l in open(decklist) if l.strip()]
    for swap in swaps:
        if status(swap, counts, unchanged) not in ('pending', 'check'):
            continue
        if swap['out']:
            name, n = swap['out']
            for _ in range(n):
                for i, line in enumerate(lines):
                    m = re.match(r'^(\d+)x\s+(.+?)(\s+\(.*|\s*)$', line)
                    if m and m.group(2) == name:
                        k = int(m.group(1))
                        if k > 1:
                            lines[i] = f'{k - 1}x {name}{m.group(3)}'
                        else:
                            del lines[i]
                        break
        if swap['in']:
            name, n = swap['in']
            base = maybe_lines.get(name, f'1x {name} () 0 [Proposed]')
            lines.append(re.sub(r'^\d+x', f'{n}x', base))
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description='Proposed swaps vs the Archidekt decklist')
    ap.add_argument('deck', help='decks/<deck> folder (or its decklist.txt)')
    ap.add_argument('--init', action='store_true', help='Create an empty swaps.txt for the deck')
    ap.add_argument('--write', metavar='PATH', nargs='?', const='',
                    help='Write the decklist with open swaps applied (default: decks/<deck>/proposed.txt, '
                         'next to the deck CLAUDE.md so the other tools find its bracket and plans)')
    ap.add_argument('--prune', action='store_true',
                    help='Remove swaps done on Archidekt; when the rest are all pending, '
                         'mark them as written against the current Archidekt version')
    args = ap.parse_args()

    folder = args.deck if os.path.isdir(args.deck) else os.path.dirname(args.deck)
    decklist = os.path.join(folder, 'decklist.txt')
    maybelist = os.path.join(folder, 'maybelist.txt')
    swaps_path = os.path.join(folder, 'swaps.txt')
    current = archidekt_version(folder)

    if args.init:
        if os.path.exists(swaps_path):
            print(f'{swaps_path} already exists')
        else:
            with open(swaps_path, 'w') as f:
                f.write(HEADER.format(version=current or 'unknown') + '\n')
            print(f'Created {swaps_path}')
        return

    swaps = parse_swaps(swaps_path)
    if not swaps:
        print(f'No swaps in {swaps_path}')
        return
    counts = deck_counts(decklist)
    maybe = deck_counts_maybe(maybelist)
    written = swaps_version(swaps_path)
    unchanged = bool(current) and written == current
    if not unchanged:
        print(f'Archidekt changed since these swaps were written ({written or "unknown"} -> '
              f'{current or "unknown"}): judging each swap by the cards in the deck.\n')

    by_status = {'pending': [], 'check': [], 'done': [], 'stale': []}
    for s in swaps:
        by_status[status(s, counts, unchanged)].append(s)
    labels = {'pending': 'Pending (make these on Archidekt)',
              'check': 'Check by hand (basic lands or counts: compare with the Archidekt list)',
              'done': 'Done on Archidekt (remove with --prune)',
              'stale': 'Stale (Archidekt list no longer matches: rethink or remove)'}
    for key in ('pending', 'check', 'done', 'stale'):
        if not by_status[key]:
            continue
        print(f'{labels[key]}: {len(by_status[key])}')
        for s in by_status[key]:
            note = '   [on maybeboard]' if s['in'] and s['in'][0] in maybe else ''
            print(f'  {describe(s)}{note}')
        print()
    todo = by_status['pending'] + by_status['check']
    outs = sum(s['out'][1] for s in todo if s['out'])
    ins = sum(s['in'][1] for s in todo if s['in'])
    if outs != ins:
        print(f'WARN: open swaps cut {outs} and add {ins}: deck size changes by {ins - outs:+d}')

    if args.write is not None:
        out = args.write or os.path.join(folder, 'proposed.txt')
        with open(out, 'w') as f:
            f.write(proposed_text(decklist, maybelist, swaps, counts, unchanged))
        print(f'Wrote decklist with open swaps applied -> {out}')

    if args.prune:
        drop = {s['line'] for s in by_status['done']}
        text = ''.join(l for l in open(swaps_path) if l.rstrip('\n') not in drop)
        if current and not by_status['check'] and not by_status['stale']:
            if VERSION_RE.search(text):
                text = VERSION_RE.sub(f'# archidekt-version: {current}', text)
            else:
                text = HEADER.format(version=current) + text
        with open(swaps_path, 'w') as f:
            f.write(text)
        print(f'Pruned {len(drop)} done swap(s) from {swaps_path}')


def deck_counts_maybe(maybelist):
    if not os.path.exists(maybelist):
        return Counter()
    names = Counter()
    for line in open(maybelist):
        m = re.match(r'^(\d+)x\s+(.+?)\s+\(', line)
        if m:
            names[m.group(2)] += int(m.group(1))
    return names


if __name__ == '__main__':
    main()
