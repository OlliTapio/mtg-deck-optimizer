"""Build the static data bundle for the deck site (web/public/data/).

Reads every decks/*/decklist.txt (source of truth) and bakes the Scryfall bits
the browser needs — image URL, type line, mana cost, cmc, price — into JSON.
cache/ is gitignored, so this runs locally and the generated JSON is committed,
the same way property-bot commits public/listings.json.

Usage:
    python3 build_site.py                 # all decks
    python3 build_site.py wise_mothman    # one or more deck folders
"""
import json
import os
import sys

from card_cache import get_card
from parser import parse_decklist

ROOT = os.path.dirname(os.path.abspath(__file__))
DECKS_DIR = os.path.join(ROOT, "decks")
OUT_DIR = os.path.join(ROOT, "web", "public", "data")

TYPE_TAGS = {"Creature", "Sorcery", "Instant", "Enchantment", "Artifact", "Planeswalker", "Battle"}
TYPE_ORDER = ["Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Battle", "Land"]


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
    """The main card type, used as a fallback category for untagged cards."""
    line = (sf or {}).get("type_line", "")
    if "//" in line:
        line = line.split("//")[0]
    for t in TYPE_ORDER:
        if t in line:
            return t
    return "Other"


def category_of(card, sf):
    """Archidekt exports the primary category first in the [..] bracket list."""
    tags = card.get("clean_tags") or []
    if tags:
        # Prefer a functional tag over a bare type tag when both are present.
        for tag in tags:
            if tag not in TYPE_TAGS:
                return tag
        return tags[0]
    return primary_type(sf)


def is_draft(slug):
    """Decks not yet physically built: a DRAFT marker file, or a wip_/test_ slug."""
    return slug.startswith(("wip_", "test_")) or os.path.exists(
        os.path.join(DECKS_DIR, slug, "DRAFT")
    )


def build_card(card, sf):
    return {
        "name": card["name"],
        "count": card["count"],
        "category": category_of(card, sf),
        "type": primary_type(sf),
        "tags": card.get("clean_tags") or [],
        "set": card.get("set") or (sf or {}).get("set"),
        "number": card.get("number"),
        "foil": card.get("foil", False),
        "buy": any(t == "Buy" for t in card.get("tags", [])),
        "cmc": (sf or {}).get("cmc"),
        # mana_cost drives the pip count, produced_mana the production count
        # (the site's bottom bar, like Archidekt's).
        "mana_cost": (sf or {}).get("mana_cost") or " // ".join(
            f.get("mana_cost", "") for f in (sf or {}).get("card_faces", [])
        ),
        "produced_mana": (sf or {}).get("produced_mana") or sorted({
            m for f in (sf or {}).get("card_faces", []) for m in f.get("produced_mana", [])
        }),
        "type_line": (sf or {}).get("type_line"),
        "oracle_text": (sf or {}).get("oracle_text"),
        "image": image_url(sf, "normal"),
        "image_small": image_url(sf, "small"),
        "scryfall_uri": (sf or {}).get("scryfall_uri"),
        "price_eur": ((sf or {}).get("prices") or {}).get("eur"),
    }


def build_deck(slug):
    """Build one deck's JSON payload from its decklist.txt."""
    path = os.path.join(DECKS_DIR, slug, "decklist.txt")
    parsed = parse_decklist(path)

    commander = None
    if parsed["commander"]:
        c = parsed["commander"]
        commander = build_card(c, get_card(c["name"]))
        commander["category"] = "Commander"

    # parser.py emits basics as one entry per copy ("7x Forest" -> 7 rows);
    # merge same name+category back into a single stack with a count.
    cards = []
    by_key = {}
    for card in parsed["deck"]:
        built = build_card(card, get_card(card["name"]))
        key = (built["name"], built["category"])
        if key in by_key:
            by_key[key]["count"] += built["count"]
            continue
        by_key[key] = built
        cards.append(built)

    total = sum(c["count"] for c in cards) + (1 if commander else 0)
    name = commander["name"] if commander else slug.replace("_", " ").title()

    return {
        "slug": slug,
        "name": name,
        "commander": commander,
        "cards": cards,
        "total": total,
    }


def deck_slugs():
    return sorted(
        d for d in os.listdir(DECKS_DIR)
        if os.path.isfile(os.path.join(DECKS_DIR, d, "decklist.txt"))
    )


def main():
    slugs = sys.argv[1:] or deck_slugs()
    os.makedirs(OUT_DIR, exist_ok=True)

    index = []
    for slug in slugs:
        print(f"Building {slug}...", file=sys.stderr)
        deck = build_deck(slug)
        with open(os.path.join(OUT_DIR, f"{slug}.json"), "w") as f:
            json.dump(deck, f, ensure_ascii=False, separators=(",", ":"))
        index.append({
            "slug": slug,
            "name": deck["name"],
            "total": deck["total"],
            "art": (deck["commander"] or {}).get("image_small"),
            "draft": is_draft(slug),
        })

    # Rebuilding a subset must not drop the other decks from the index.
    index_path = os.path.join(OUT_DIR, "index.json")
    if len(slugs) < len(deck_slugs()) and os.path.exists(index_path):
        with open(index_path) as f:
            existing = json.load(f).get("decks", [])
        by_slug = {d["slug"]: d for d in existing}
        for entry in index:
            by_slug[entry["slug"]] = entry
        index = [by_slug[s] for s in sorted(by_slug)]

    with open(index_path, "w") as f:
        json.dump({"decks": index}, f, ensure_ascii=False, indent=1)

    print(f"Wrote {len(index)} decks to {OUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
