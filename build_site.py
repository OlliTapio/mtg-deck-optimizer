"""Build the static data bundle for the deck site (web/public/data/).

Reads every decks/*/decklist.txt (source of truth) and bakes the Scryfall bits
the browser needs — image URL, type line, mana cost, pip/production counts —
into JSON. cache/ is gitignored, so this runs locally and the generated JSON is
committed, the same way property-bot commits public/listings.json.

Scryfall field access and pip counting come from deck_analyzer, so the site and
`deck_analyzer.py` report the same pips. The other Stats-tab numbers are the
site's own reading and deliberately differ from the CLI's: a card counts once,
under its primary type, and the template rows count copies (not distinct names)
and include mana-dork/card-advantage otags.

Usage:
    python3 build_site.py                 # all decks
    python3 build_site.py wise_mothman    # one or more deck folders
"""
import json
import os
import re
import sys
from collections import Counter

from card_cache import get_card
from deck_analyzer import (
    MAIN_TYPES, count_pips, front_face_cost, get_color_identity, get_cmc,
    get_mana_cost, get_oracle_text, get_price_eur, get_produced_mana,
    get_type_line,
)
from otag_fetcher import OTAGS, fetch_otags_for_cards
from parser import parse_decklist

ROOT = os.path.dirname(os.path.abspath(__file__))
DECKS_DIR = os.path.join(ROOT, "decks")
OUT_DIR = os.path.join(ROOT, "web", "public", "data")

TYPE_TAGS = set(MAIN_TYPES)
# Column order in the site's type grouping.
TYPE_ORDER = ["Commander", "Creature", "Planeswalker", "Instant", "Sorcery",
              "Artifact", "Enchantment", "Battle", "Other", "Land"]
COLORS = ["W", "U", "B", "R", "G", "C"]

# Command Zone template (2025 New Era), see command_zone_template.md. Each row
# is (label, target, otags that count toward it).
TEMPLATE = [
    ("Lands", 38, None),
    ("Ramp", 10, ["ramp", "mana-dork"]),
    ("Card advantage", 12, ["draw", "card-advantage"]),
    ("Targeted disruption", 12, ["removal", "counterspell"]),
    ("Mass disruption", 6, ["board-wipe"]),
]


def image_url(sf, size="normal"):
    """Scryfall image for a card, falling back to the front face of a DFC."""
    if not sf:
        return None
    if sf.get("image_uris"):
        return sf["image_uris"].get(size)
    for face in sf.get("card_faces", []):
        if face.get("image_uris"):
            return face["image_uris"].get(size)
    return None


def primary_type(sf):
    """The card's main type, used for the site's type grouping.

    Land wins over other types so that a land creature files under Land, and
    the front face decides for split/modal cards.
    """
    line = get_type_line(sf).split("//")[0]
    if "Land" in line:
        return "Land"
    for t in TYPE_ORDER:
        if t in MAIN_TYPES and t in line:
            return t
    return "Other"


def full_type_line(sf):
    """Every face's type line — Scryfall's top-level one for a DFC is "A // B"."""
    if not sf:
        return ""
    return sf.get("type_line") or " // ".join(
        f.get("type_line", "") for f in sf.get("card_faces", []))


def is_land(sf):
    """True if any face is a land: an MDFC land back still makes a land drop."""
    return "Land" in full_type_line(sf)


def front_face_cmc(sf):
    """Mana value of the front face.

    Scryfall's top-level cmc adds both halves of a split card (Find // Finality
    is 8), which would file it in a bucket nobody can ever pay.
    """
    cost = get_mana_cost(sf)
    if " // " not in cost:
        return get_cmc(sf)
    value = 0
    for symbol in re.findall(r"\{([^}]+)\}", front_face_cost(cost)):
        # {2/B} costs 2 or B, so it's worth 2; {X} is 0 on the stack.
        parts = [int(p) if p.isdigit() else (0 if p == "X" else 1)
                 for p in symbol.split("/")]
        value += max(parts)
    return float(value)


def category_of(card, sf):
    """The card's Archidekt category: its functional tag, else its type.

    The [...] tags in decklist.txt are Archidekt categories; a functional tag
    (Ramp, Removal, ...) is preferred over a bare type tag regardless of the
    order they were exported in. Multiple functional tags: first one wins.
    """
    for tag in card.get("clean_tags") or []:
        if tag not in TYPE_TAGS:
            return tag
    return primary_type(sf)


def is_draft(slug):
    """Decks not yet physically built: a DRAFT marker file, or a wip_/test_ slug."""
    return slug.startswith(("wip_", "test_")) or os.path.exists(
        os.path.join(DECKS_DIR, slug, "DRAFT")
    )


def build_card(card, sf, otags=()):
    return {
        "name": card["name"],
        "count": card["count"],
        "otags": list(otags),
        "category": category_of(card, sf),
        "type": primary_type(sf),
        "set": card.get("set") or (sf or {}).get("set"),
        "number": card.get("number"),
        "foil": card.get("foil", False),
        "buy": any(t == "Buy" for t in card.get("tags", [])),
        "cmc": front_face_cmc(sf),
        "is_land": is_land(sf),
        "mana_cost": get_mana_cost(sf),
        "produced_mana": get_produced_mana(sf),
        "type_line": get_type_line(sf),
        "oracle_text": get_oracle_text(sf),
        "image": image_url(sf, "normal"),
        "price_eur": get_price_eur(sf),
    }


def mana_stats(cards, identity):
    """Archidekt's bottom bar: coloured pips in costs, and sources per colour.

    Production is limited to the deck's colour identity (+ colourless) so that
    any-colour dorks don't report red/white sources in a Sultai deck.
    """
    allowed = set(identity) | {"C"}
    symbols = Counter()
    production = Counter()
    for card in cards:
        for color, n in count_pips(front_face_cost(card["mana_cost"])).items():
            if color in COLORS:
                symbols[color] += n * card["count"]
        for m in card["produced_mana"]:
            if m in COLORS and m in allowed:
                production[m] += card["count"]
    return (
        {c: symbols[c] for c in COLORS if symbols[c]},
        {c: production[c] for c in COLORS if production[c]},
    )


def deck_stats(cards, otag_counts):
    """The numbers behind the site's Stats tab.

    Curve and type counts exclude nothing — a card counts once for its primary
    type — while the template check follows command_zone_template.md, where one
    card can serve several categories.
    """
    types = Counter()
    curve = Counter()
    lands = 0
    for card in cards:
        types[card["type"]] += card["count"]
        # An MDFC with a land back counts as a land drop even though its front
        # face files it under Creature/Sorcery in the card columns.
        if card.get("is_land"):
            lands += card["count"]
        if card["type"] != "Land":
            curve[int(card["cmc"] or 0)] += card["count"]

    nonland = sum(n for cmc, n in curve.items())
    avg_cmc = (sum(cmc * n for cmc, n in curve.items()) / nonland) if nonland else 0

    template = []
    for label, target, otags in TEMPLATE:
        if otags is None:
            count = lands
        else:
            # A card with both "removal" and "counterspell" counts once.
            count = sum(c["count"] for c in cards
                        if any(t in c["otags"] for t in otags))
        template.append({"label": label, "count": count, "target": target})

    return {
        "types": {t: types[t] for t in TYPE_ORDER if types[t]},
        "curve": {str(cmc): curve[cmc] for cmc in sorted(curve)},
        "avg_cmc": round(avg_cmc, 2),
        "otags": otag_counts,
        "template": template,
    }


def build_deck(slug, otags_by_name=None):
    """Build one deck's JSON payload from its decklist.txt.

    Returns (deck, missing) where missing lists cards with no Scryfall data.
    """
    otags_by_name = otags_by_name or {}
    path = os.path.join(DECKS_DIR, slug, "decklist.txt")
    parsed = parse_decklist(path)
    missing = []

    deck_identity = set()

    def card_data(card):
        sf = get_card(card["name"])
        if sf is None:
            missing.append(card["name"])
        deck_identity.update(get_color_identity(sf))
        return sf

    commander = None
    identity = []
    if parsed["commander"]:
        c = parsed["commander"]
        sf = card_data(c)
        commander = build_card(c, sf, otags_by_name.get(c["name"], []))
        commander["category"] = "Commander"
        commander["image_small"] = image_url(sf, "small")
        identity = get_color_identity(sf)

    # parser.py emits one row per copy for basics ("7x Forest") and for exports
    # that list each copy with its own set/number; merge them into one stack.
    cards = []
    by_key = {}
    for card in parsed["deck"]:
        built = build_card(card, card_data(card),
                           otags_by_name.get(card["name"], []))
        key = (built["name"], built["category"])
        if key in by_key:
            stack = by_key[key]
            stack["count"] += built["count"]
            # A stack is "buy"/foil if any of its copies is.
            stack["buy"] = stack["buy"] or built["buy"]
            stack["foil"] = stack["foil"] or built["foil"]
            continue
        by_key[key] = built
        cards.append(built)

    total = sum(c["count"] for c in cards) + (1 if commander else 0)
    name = commander["name"] if commander else slug.replace("_", " ").title()
    if not identity:  # no commander row: fall back to the cards' own identity
        identity = sorted(deck_identity)
    all_cards = ([commander] if commander else []) + cards
    symbols, production = mana_stats(all_cards, identity)

    otag_counts = Counter()
    for card in all_cards:
        for tag in card["otags"]:
            otag_counts[tag] += card["count"]

    return {
        "slug": slug,
        "name": name,
        "commander": commander,
        "cards": cards,
        "total": total,
        "color_identity": identity,
        "mana_symbols": symbols,
        "mana_production": production,
        "stats": deck_stats(all_cards,
                            {t: otag_counts[t] for t in OTAGS if otag_counts[t]}),
    }, missing


def deck_slugs():
    return sorted(
        d for d in os.listdir(DECKS_DIR)
        if os.path.isfile(os.path.join(DECKS_DIR, d, "decklist.txt"))
    )


def index_entry(deck):
    return {
        "slug": deck["slug"],
        "name": deck["name"],
        "total": deck["total"],
        "art": (deck["commander"] or {}).get("image_small"),
        "draft": is_draft(deck["slug"]),
    }


def merge_index(entries, previous, known):
    """Fold freshly built entries into a previous index, dropping gone decks.

    draft flags are recomputed for carried-over decks so adding a DRAFT marker
    takes effect without a full rebuild.
    """
    by_slug = {e["slug"]: e for e in previous if e["slug"] in known}
    for entry in by_slug.values():
        entry["draft"] = is_draft(entry["slug"])
    for entry in entries:
        by_slug[entry["slug"]] = entry
    return [by_slug[s] for s in sorted(by_slug)]


def main():
    requested = sys.argv[1:]
    known = deck_slugs()

    unknown = [s for s in requested if s not in known]
    if unknown:
        print(f"Unknown deck(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Known: {', '.join(known)}", file=sys.stderr)
        return 2

    slugs = requested or known
    os.makedirs(OUT_DIR, exist_ok=True)

    # One otag pass for every card in the build: uncached names cost a batch of
    # Scryfall searches, so doing it per deck would repeat the work.
    names = set()
    for slug in slugs:
        parsed = parse_decklist(os.path.join(DECKS_DIR, slug, "decklist.txt"))
        cards = parsed["deck"] + ([parsed["commander"]] if parsed["commander"] else [])
        names.update(c["name"] for c in cards)
    otags_by_name = fetch_otags_for_cards(sorted(names))

    entries = []
    missing = {}
    for slug in slugs:
        print(f"Building {slug}...", file=sys.stderr)
        deck, deck_missing = build_deck(slug, otags_by_name)
        if deck_missing:
            missing[slug] = deck_missing
        if deck["total"] != 100:
            print(f"  WARNING: {slug} has {deck['total']} cards, not 100", file=sys.stderr)
        with open(os.path.join(OUT_DIR, f"{slug}.json"), "w") as f:
            json.dump(deck, f, ensure_ascii=False, separators=(",", ":"))
        entries.append(index_entry(deck))

    index_path = os.path.join(OUT_DIR, "index.json")
    if requested and os.path.exists(index_path):
        with open(index_path) as f:
            previous = json.load(f).get("decks", [])
        entries = merge_index(entries, previous, set(known))

    with open(index_path, "w") as f:
        json.dump({"type_order": TYPE_ORDER, "decks": entries}, f,
                  ensure_ascii=False, indent=1)

    print(f"Wrote {len(entries)} decks to {OUT_DIR}", file=sys.stderr)
    if missing:
        for slug, names in missing.items():
            print(f"  NO SCRYFALL DATA in {slug}: {', '.join(names)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
