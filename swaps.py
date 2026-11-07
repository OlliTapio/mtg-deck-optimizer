#!/usr/bin/env python3
"""Proposed swaps for a deck, kept apart from the Archidekt list, and their progress
through the physical world.

Design: desired-state reconciliation. Archidekt mirrors the physical deck (observed
state, only ever read by pulling). Archidekt + every swap in swaps.txt is the end
status (desired state). Each swap moves through stages the physical world drives:
  to buy   the incoming card still has to be acquired        (marked [buy])
  ready    the card is in hand: swap it in the box, then on Archidekt
  done     a pull shows the change on Archidekt              (detected, never set by hand)

Each deck has three lists:
  decklist.txt   the deck on Archidekt (source of truth, written only by archidekt.py pull)
  maybelist.txt  the Archidekt maybeboard (written only by archidekt.py pull)
  swaps.txt      swaps proposed here, waiting to be made on Archidekt

swaps.txt, one swap per line, '#' starts a comment (the reason):
  Watchful Radstag -> Shadowspear   # protection for the commander
  - Rampant Growth                  # cut only
  + Nature's Lore [buy]             # add only, card still to be bought
Counts are optional ("2x Forest -> 2x Swamp") and mean how many to cut or add.
The header line '# archidekt-version: <updated_at>' records which Archidekt version
the swaps were written against: while Archidekt is unchanged every swap is pending;
after it changes, swaps are judged by which cards are in the deck.

Usage:
  python3 swaps.py decks/<deck> --init                   # start a swaps.txt for the deck
  python3 swaps.py decks/<deck>                          # physical vs end status, swaps by stage
  python3 swaps.py --all                                 # overview of every deck with swaps
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
STAGE_RE = re.compile(r'\s*\[(buy|have)\]', re.I)


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
            buy = bool(STAGE_RE.search(body)) and STAGE_RE.search(body).group(1).lower() == 'buy'
            body = STAGE_RE.sub('', body).strip()
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
            swaps.append({'out': out, 'in': inn, 'buy': buy and inn is not None,
                          'reason': reason.strip(), 'line': raw.rstrip('\n')})
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
# Mark [buy] after a swap whose incoming card still has to be acquired: Out -> In [buy]
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
    if swap.get('buy'):
        s += ' [buy]'
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


STAGES = ('buy', 'ready', 'check', 'done', 'stale')
STAGE_LABELS = {
    'buy': 'To buy (acquire the card first)',
    'ready': 'Ready to swap (card in hand: swap it in the box, then on Archidekt)',
    'check': 'Check by hand (basic lands or counts: compare with the Archidekt list)',
    'done': 'Done on Archidekt (remove with --prune)',
    'stale': 'Stale (Archidekt list no longer matches: rethink or remove)',
}


def stage(swap, counts, unchanged=False):
    st = status(swap, counts, unchanged)
    if st == 'pending':
        return 'buy' if swap.get('buy') else 'ready'
    return st


def end_counts(counts, swaps, unchanged=False):
    """Card counts once every open swap is made: the end status."""
    end = Counter(counts)
    for s in swaps:
        if stage(s, counts, unchanged) in ('done', 'stale'):
            continue
        if s['out']:
            end[s['out'][0]] -= s['out'][1]
        if s['in']:
            end[s['in'][0]] += s['in'][1]
    return +end


def deck_stats(counts):
    """Cards, lands, average mana value of nonland cards, and count per card type."""
    from card_cache import get_card
    from deck_analyzer import MAIN_TYPES, classify_type, get_cmc, get_type_line
    stats = {'Cards': sum(counts.values()), 'Lands': 0}
    types = Counter()
    mv, nonland = 0.0, 0
    for name, n in counts.items():
        sf = get_card(name)
        tl = get_type_line(sf) if sf else ''
        ts = classify_type(tl)
        if 'Land' in ts:
            stats['Lands'] += n
        else:
            mv += get_cmc(sf) * n
            nonland += n
        for t in ts - {'Land'}:
            types[t] += n
    stats['Avg MV (nonland)'] = round(mv / nonland, 2) if nonland else 0
    for t in MAIN_TYPES:
        if t != 'Land' and types[t]:
            stats[t] = types[t]
    return stats


def buy_price(swap):
    from card_cache import get_card
    from deck_analyzer import get_price_eur
    sf = get_card(swap['in'][0])
    p = get_price_eur(sf) if sf else None
    return p * swap['in'][1] if p else None


def load(folder):
    """Everything about one deck's swaps: counts, stages, versions."""
    decklist = os.path.join(folder, 'decklist.txt')
    swaps_path = os.path.join(folder, 'swaps.txt')
    current = archidekt_version(folder)
    written = swaps_version(swaps_path)
    unchanged = bool(current) and written == current
    counts = deck_counts(decklist)
    swaps = parse_swaps(swaps_path)
    by_stage = {k: [] for k in STAGES}
    for s in swaps:
        by_stage[stage(s, counts, unchanged)].append(s)
    name = None
    src = os.path.join(folder, 'source.json')
    if os.path.exists(src):
        name = json.load(open(src)).get('name')
    return {'folder': folder, 'name': name, 'current': current, 'written': written,
            'unchanged': unchanged, 'counts': counts, 'swaps': swaps, 'by_stage': by_stage,
            'end': end_counts(counts, swaps, unchanged)}


def report(d):
    """Physical status next to end status, then every swap by stage."""
    deck = os.path.basename(os.path.normpath(d['folder']))
    print(f"=== {deck}" + (f" · {d['name']}" if d['name'] else '')
          + f"   (Archidekt {(d['current'] or 'unknown')[:10]})")
    if not d['unchanged']:
        print(f"Archidekt changed since the swaps were written ({(d['written'] or 'unknown')[:10]}): "
              f"stages judged by the cards in the deck.")
    phys, end = deck_stats(d['counts']), deck_stats(d['end'])
    rows = list(dict.fromkeys(list(phys) + list(end)))
    print(f"  {'':18} {'Physical':>9} {'End':>7}")
    for r in rows:
        a, b = phys.get(r, 0), end.get(r, 0)
        mark = '' if a == b else f'  ({b - a:+.2f})' if isinstance(a, float) or isinstance(b, float) \
            else f'  ({b - a:+d})'
        print(f"  {r:18} {a:>9} {b:>7}{mark}")
    bs = d['by_stage']
    cost = sum(p for p in (buy_price(s) for s in bs['buy']) if p)
    print(f"  Swaps: {len(bs['done'])} done · {len(bs['ready'])} ready to swap · "
          f"{len(bs['buy'])} to buy (EUR {cost:.2f})"
          + (f" · {len(bs['check'])} to check" if bs['check'] else '')
          + (f" · {len(bs['stale'])} stale" if bs['stale'] else ''))
    print()
    for key in STAGES:
        if not bs[key]:
            continue
        print(f"  {STAGE_LABELS[key]}: {len(bs[key])}")
        for s in bs[key]:
            price = ''
            if key == 'buy':
                p = buy_price(s)
                price = f'   EUR {p:.2f}' if p else '   EUR ?'
            print(f"    {describe(s)}{price}")
        print()


def overview(folders):
    rows = []
    for f in folders:
        d = load(f)
        bs = d['by_stage']
        cost = sum(p for p in (buy_price(s) for s in bs['buy']) if p)
        rows.append((os.path.basename(f), sum(d['counts'].values()), sum(d['end'].values()),
                     len(bs['done']), len(bs['ready']), len(bs['buy']), cost,
                     len(bs['check']) + len(bs['stale'])))
    print(f"{'Deck':18} {'Physical':>8} {'End':>5} {'Done':>5} {'Ready':>6} {'Buy':>4} {'EUR buy':>8} {'Check':>6}")
    for r in rows:
        print(f"{r[0]:18} {r[1]:>8} {r[2]:>5} {r[3]:>5} {r[4]:>6} {r[5]:>4} {r[6]:>8.2f} {r[7]:>6}")
    print("\nPhysical = Archidekt (the deck in the box). End = Archidekt + every open swap.")


def main():
    ap = argparse.ArgumentParser(description='Proposed swaps vs the Archidekt decklist')
    ap.add_argument('deck', nargs='?', help='decks/<deck> folder (or its decklist.txt)')
    ap.add_argument('--all', action='store_true', help='Overview of every deck that has a swaps.txt')
    ap.add_argument('--init', action='store_true', help='Create an empty swaps.txt for the deck')
    ap.add_argument('--write', metavar='PATH', nargs='?', const='',
                    help='Write the decklist with open swaps applied (default: decks/<deck>/proposed.txt, '
                         'next to the deck CLAUDE.md so the other tools find its bracket and plans)')
    ap.add_argument('--prune', action='store_true',
                    help='Remove swaps done on Archidekt; when the rest are all pending, '
                         'mark them as written against the current Archidekt version')
    args = ap.parse_args()

    if args.all:
        decks_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decks')
        folders = sorted(os.path.join(decks_dir, x) for x in os.listdir(decks_dir)
                         if parse_swaps(os.path.join(decks_dir, x, 'swaps.txt')))
        overview(folders)
        return
    if not args.deck:
        ap.error('give a deck folder, or --all')

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
    d = load(folder)
    counts, unchanged, by_status = d['counts'], d['unchanged'], d['by_stage']
    report(d)
    todo = by_status['buy'] + by_status['ready'] + by_status['check']
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
        current = d['current']
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
