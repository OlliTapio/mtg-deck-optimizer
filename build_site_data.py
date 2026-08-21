"""Build the static data bundle consumed by the web SPA (issue #6 / #8).

Reads each deck's committed deck.json (the source of truth for card contents,
kept in sync by sync_decks.py / #7) plus cuts.txt, buy_list.txt and CLAUDE.md,
and writes one JSON per deck + an index.json to web/public/data/.

Analytics (type counts, mana curve, pips, Command Zone template check) are
precomputed here so the SPA numbers match deck_analyzer.py exactly. No Scryfall
calls: everything needed is already in deck.json.

Usage:
    python3 build_site_data.py            # -> web/public/data/
    python3 build_site_data.py -o <dir>
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

from deck_analyzer import MAIN_TYPES, COLOR_ORDER, count_pips
from otag_fetcher import OTAGS

ROOT = os.path.dirname(os.path.abspath(__file__))
DECKS_DIR = os.path.join(ROOT, "decks")
DEFAULT_OUT = os.path.join(ROOT, "web", "public", "data")

# Command Zone template targets (mirrors deck_analyzer.mode_full).
TEMPLATE = [
    ("targeted", "Targeted Disruption", ["removal", "counterspell"], 12),
    ("mass", "Mass Disruption", ["board-wipe"], 6),
    ("card_advantage", "Card Advantage", ["draw", "card-advantage"], 12),
    ("ramp", "Ramp", ["ramp"], 10),
]

CUT_LINE = re.compile(
    r"^\s*(\d+)x\s+(.+?)"           # count + out card name
    r"(?:\s+\((\w+)\)\s+(\S+))?"    # optional (set) number
    r"(?:\s+\[[^\]]*\])?"           # optional [tags]
    r"\s*->\s*(.+?)\s*$"            # -> right-hand side (in card + reason)
)
ROUND_HEADER = re.compile(r"^#\s*(Round.*)$", re.IGNORECASE)


def is_land(card):
    return "Land" in card.get("types", [])


def compute_analytics(all_cards):
    """Type counts, mana curve, color pips, otag groups, and template check."""
    type_counts = Counter()
    cmc_counts = Counter()
    pips = Counter()
    otag_groups = defaultdict(set)

    for c in all_cards:
        n = c.get("count", 1)
        for t in c.get("types", []):
            if t in MAIN_TYPES:
                type_counts[t] += n
        if not is_land(c):
            cmc_counts[int(c.get("cmc") or 0)] += n
            for color, cnt in count_pips(c.get("mana_cost", "")).items():
                pips[color] += cnt * n
        for tag in c.get("otags", []):
            otag_groups[tag].add(c["name"])
        if "proliferate" in (c.get("oracle_text") or "").lower():
            otag_groups["proliferate"].add(c["name"])

    curve = {str(k): cmc_counts.get(k, 0) for k in range(0, (max(cmc_counts) if cmc_counts else 0) + 1)}
    total_nonland = sum(cmc_counts.values())
    curve["avg"] = round(sum(k * v for k, v in cmc_counts.items()) / total_nonland, 2) if total_nonland else 0

    template = []
    for key, label, tags, target in TEMPLATE:
        have = set()
        for t in tags:
            have |= otag_groups.get(t, set())
        template.append({"key": key, "label": label, "have": len(have), "target": target})

    return {
        "type_counts": {t: type_counts[t] for t in MAIN_TYPES if type_counts[t]},
        "curve": curve,
        "pips": {c: pips[c] for c in COLOR_ORDER if pips[c]},
        "otag_groups": {k: sorted(v) for k, v in sorted(otag_groups.items())},
        "template": template,
    }


def parse_buy_list(deck_dir):
    path = os.path.join(deck_dir, "buy_list.txt")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+)x?\s+(.+)$", line)
        if m:
            out.append({"count": int(m.group(1)), "name": m.group(2).strip()})
        else:
            out.append({"count": 1, "name": line})
    return out


def parse_trade_wants(deck_dir):
    """Parse trade_wants.txt — cards to acquire by trade rather than purchase.

    Format mirrors buy_list.txt with an optional note after a pipe:
        <count> <card name> | <optional note>
    """
    path = os.path.join(deck_dir, "trade_wants.txt")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, note = line.partition("|")
        m = re.match(r"^(\d+)x?\s+(.+)$", body.strip())
        count, name = (int(m.group(1)), m.group(2).strip()) if m else (1, body.strip())
        out.append({"count": count, "name": name, "note": note.strip() or None})
    return out


def parse_cuts(deck_dir):
    """Parse cuts.txt into structured swaps (out card -> in card + reason)."""
    path = os.path.join(deck_dir, "cuts.txt")
    if not os.path.exists(path):
        return []
    swaps = []
    round_label = None
    for line in open(path):
        line = line.rstrip("\n")
        hm = ROUND_HEADER.match(line.strip())
        if hm:
            round_label = hm.group(1).strip()
            continue
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = CUT_LINE.match(line)
        if not m:
            continue
        count, out_name, out_set, out_num, rhs = m.groups()
        # Split the right side into an in-card name and a parenthetical reason.
        in_name, reason = rhs, ""
        pm = re.match(r"^(.+?)\s*\((.*)\)\s*$", rhs)
        if pm:
            in_name, reason = pm.group(1).strip(), pm.group(2).strip()
        swaps.append({
            "round": round_label,
            "out": {"name": out_name.strip(), "set": out_set, "number": out_num},
            "in_name": in_name.strip(),
            "reason": reason,
            "raw": line.strip(),
        })
    return swaps


def parse_claude_md(deck_dir):
    """Pull the deck title and bracket from CLAUDE.md (not derivable elsewhere)."""
    path = os.path.join(deck_dir, "CLAUDE.md")
    title, bracket = None, None
    if os.path.exists(path):
        text = open(path).read()
        h = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if h:
            title = h.group(1).strip()
        b = re.search(r"Bracket\s+(\d)", text)
        if b:
            bracket = int(b.group(1))
    return title, bracket


def build_deck(deck_dir):
    deck_json = os.path.join(deck_dir, "deck.json")
    if not os.path.exists(deck_json):
        return None
    data = json.load(open(deck_json))
    commander = data.get("commander")
    cards = data.get("deck", [])
    all_cards = ([commander] if commander else []) + cards

    deck_id = os.path.basename(deck_dir.rstrip("/"))
    title, bracket = parse_claude_md(deck_dir)

    return {
        "id": deck_id,
        "name": title or (commander["name"] if commander else deck_id),
        "bracket": bracket,
        "commander": commander,
        "total_cards": data.get("metadata", {}).get("total_cards", len(all_cards)),
        "cards": cards,
        "analytics": compute_analytics(all_cards),
        "buy_list": parse_buy_list(deck_dir),
        "trade_wants": parse_trade_wants(deck_dir),
        "cuts": parse_cuts(deck_dir),
    }


def main():
    out_dir = DEFAULT_OUT
    if "-o" in sys.argv:
        out_dir = sys.argv[sys.argv.index("-o") + 1]
    os.makedirs(out_dir, exist_ok=True)

    index = []
    for deck_json in sorted(glob.glob(os.path.join(DECKS_DIR, "*", "deck.json"))):
        deck_dir = os.path.dirname(deck_json)
        # Skip throwaway simulator decks; the site shows real decks only.
        if os.path.basename(deck_dir).startswith("test_"):
            continue
        deck = build_deck(deck_dir)
        if not deck:
            continue
        with open(os.path.join(out_dir, f"{deck['id']}.json"), "w") as f:
            json.dump(deck, f, indent=2)
        index.append({
            "id": deck["id"],
            "name": deck["name"],
            "bracket": deck["bracket"],
            "commander": deck["commander"]["name"] if deck["commander"] else None,
            "total_cards": deck["total_cards"],
            "colors": sorted(deck["commander"]["color_identity"]) if deck["commander"] else [],
            "buy_count": sum(b["count"] for b in deck["buy_list"]),
            "trade_count": sum(t["count"] for t in deck["trade_wants"]),
        })
        print(f"  wrote {deck['id']}.json", file=sys.stderr)

    # Cross-deck trade-wants view: one flat list so the SPA needs a single fetch.
    trades = []
    for entry in index:
        deck = json.load(open(os.path.join(out_dir, f"{entry['id']}.json")))
        for want in deck["trade_wants"]:
            trades.append({**want, "deck_id": entry["id"], "deck_name": entry["name"]})
    with open(os.path.join(out_dir, "trade_wants.json"), "w") as f:
        json.dump({"wants": trades}, f, indent=2)
    print(f"  wrote trade_wants.json ({len(trades)} wants)", file=sys.stderr)

    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump({"decks": index}, f, indent=2)
    print(f"  wrote index.json ({len(index)} decks) -> {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
