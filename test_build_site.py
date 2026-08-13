"""Tests for the deck site data build (build_site.py)."""
import json

import pytest

import build_site
from deck_analyzer import count_pips, front_face_cost


def sf(type_line="Creature — Human", cmc=2.0, mana_cost="{1}{G}", **extra):
    """Minimal Scryfall-shaped card."""
    card = {"type_line": type_line, "cmc": cmc, "mana_cost": mana_cost,
            "oracle_text": "", "prices": {}, "produced_mana": [],
            "color_identity": ["G"],
            "image_uris": {"normal": "n.jpg", "small": "s.jpg"}}
    card.update(extra)
    return card


def row(name, count=1, tags=(), **extra):
    """A parser.py-shaped decklist row."""
    card = {"name": name, "count": count, "set": "pip", "number": "1",
            "foil": False, "tags": list(tags), "clean_tags": list(tags)}
    card.update(extra)
    return card


# --- category / type classification ---

@pytest.mark.parametrize("tags,expected", [
    (["Ramp", "Creature"], "Ramp"),          # functional tag wins over type
    (["Creature", "Removal"], "Removal"),    # ...whatever the export order
    (["Ramp", "Draw"], "Ramp"),              # two functional tags: first wins
    (["Creature"], "Creature"),
    ([], "Creature"),                        # untagged -> Scryfall type
])
def test_category_of(tags, expected):
    assert build_site.category_of(row("X", tags=tags), sf()) == expected


def test_category_of_type_only_tags_use_the_real_type():
    """A [Land]-tagged card is categorised from Scryfall, not from the tag."""
    land = sf(type_line="Land", mana_cost="")
    assert build_site.category_of(row("Bojuka Bog", tags=["Land"]), land) == "Land"


@pytest.mark.parametrize("type_line,expected", [
    ("Legendary Creature — Insect Mutant", "Creature"),
    ("Artifact Creature — Golem", "Creature"),
    ("Enchantment Creature — Aura", "Creature"),
    ("Kindred Sorcery — Elf", "Sorcery"),
    ("Land Creature — Forest Dryad", "Land"),        # Dryad Arbor files as Land
    ("Land // Sorcery", "Land"),
    ("Sorcery // Land", "Sorcery"),                  # front face decides
    ("Basic Land — Forest", "Land"),
    ("Legendary Planeswalker — Teferi", "Planeswalker"),
    ("Conspiracy", "Other"),
])
def test_primary_type(type_line, expected):
    assert build_site.primary_type(sf(type_line=type_line)) == expected


def test_primary_type_without_scryfall_data():
    assert build_site.primary_type(None) == "Other"


def test_build_card_survives_missing_scryfall_data():
    card = build_site.build_card(row("Nonexistent Card"), None)
    assert card["image"] is None and card["cmc"] == 0 and card["type"] == "Other"


# --- pip counting (shared with deck_analyzer) ---

@pytest.mark.parametrize("cost,expected", [
    ("{1}{G}", {"G": 1}),
    ("{B}{B}", {"B": 2}),
    ("{G/U}", {"G": 1, "U": 1}),          # hybrid: both halves
    ("{2/B}", {"B": 1}),                  # monocolour hybrid
    ("{B/P}", {"B": 1}),                  # phyrexian
    ("{G/W/P}", {"G": 1, "W": 1}),
    ("{X}{3}{S}", {}),                    # generic / X / snow score nothing
    ("{C}{C}", {"C": 2}),
])
def test_count_pips(cost, expected):
    assert dict(count_pips(cost)) == expected


def test_front_face_cost_only():
    # Murderous Rider is one card, so its {1}{B}{B} counts once, not twice.
    assert front_face_cost("{1}{B}{B} // {1}{B}{B}") == "{1}{B}{B}"
    assert front_face_cost("") == ""


def test_mana_stats_counts_pips_per_copy_and_filters_production():
    cards = [
        build_site.build_card(row("Swamp", count=3),
                              sf(type_line="Basic Land — Swamp", mana_cost="",
                                 produced_mana=["B"])),
        build_site.build_card(row("Birds of Paradise"),
                              sf(mana_cost="{G}",
                                 produced_mana=["W", "U", "B", "R", "G"])),
        build_site.build_card(row("Murderous Rider"),
                              sf(mana_cost="{1}{B}{B} // {1}{B}{B}")),
    ]
    symbols, production = build_site.mana_stats(cards, ["B", "G"])
    assert symbols == {"B": 2, "G": 1}
    # The any-colour dork only counts for colours the deck can actually use.
    assert production == {"B": 4, "G": 1}


# --- deck assembly ---

def test_build_deck_merges_duplicate_rows(monkeypatch, tmp_path):
    """parser.py emits one row per basic; the build merges them into a stack."""
    deck_dir = tmp_path / "decks" / "testdeck"
    deck_dir.mkdir(parents=True)
    (deck_dir / "decklist.txt").write_text(
        "1x Commander Card (pip) 1 [Commander]\n"
        "3x Forest\n"
        "1x Forest (one) 276 [Land]\n"
        "1x Llanowar Elves (pip) 2 [Ramp,Creature]\n"
    )
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path / "decks"))
    monkeypatch.setattr(build_site, "get_card", lambda name: sf(
        type_line="Basic Land — Forest", mana_cost="", produced_mana=["G"])
        if name == "Forest" else sf())

    deck, missing = build_site.build_deck("testdeck")

    assert missing == []
    assert deck["commander"]["category"] == "Commander"
    forests = [c for c in deck["cards"] if c["name"] == "Forest"]
    assert len(forests) == 1 and forests[0]["count"] == 4
    assert deck["total"] == 6  # 4 forests + 1 dork + commander


def test_build_deck_reports_cards_without_scryfall_data(monkeypatch, tmp_path):
    deck_dir = tmp_path / "decks" / "testdeck"
    deck_dir.mkdir(parents=True)
    (deck_dir / "decklist.txt").write_text("1x Typo Card (pip) 1 [Ramp]\n")
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path / "decks"))
    monkeypatch.setattr(build_site, "get_card", lambda name: None)

    _, missing = build_site.build_deck("testdeck")
    assert missing == ["Typo Card"]


# --- draft marker + index merge ---

def test_is_draft(monkeypatch, tmp_path):
    (tmp_path / "built").mkdir()
    (tmp_path / "marked").mkdir()
    (tmp_path / "marked" / "DRAFT").write_text("not sleeved yet\n")
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path))

    assert build_site.is_draft("marked") is True
    assert build_site.is_draft("built") is False
    assert build_site.is_draft("wip_anything") is True
    assert build_site.is_draft("test_anything") is True


def test_merge_index_keeps_other_decks_and_drops_gone_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path))
    previous = [
        {"slug": "a", "name": "A", "total": 100, "art": None, "draft": False},
        {"slug": "gone", "name": "Gone", "total": 100, "art": None, "draft": False},
    ]
    fresh = [{"slug": "b", "name": "B", "total": 100, "art": None, "draft": False}]

    merged = build_site.merge_index(fresh, previous, {"a", "b"})

    assert [e["slug"] for e in merged] == ["a", "b"]


def test_merge_index_recomputes_draft_flags(monkeypatch, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "DRAFT").write_text("")
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path))
    previous = [{"slug": "a", "name": "A", "total": 100, "art": None, "draft": False}]

    merged = build_site.merge_index([], previous, {"a"})

    assert merged[0]["draft"] is True


def test_main_rejects_unknown_deck(monkeypatch, capsys):
    monkeypatch.setattr(build_site.sys, "argv", ["build_site.py", "nope"])
    monkeypatch.setattr(build_site, "deck_slugs", lambda: ["wise_mothman"])

    assert build_site.main() == 2
    assert "Unknown deck" in capsys.readouterr().err


# --- the committed bundle stays consistent with the site's expectations ---

def test_committed_bundle_is_self_consistent():
    with open(f"{build_site.OUT_DIR}/index.json") as f:
        index = json.load(f)
    assert index["type_order"] == build_site.TYPE_ORDER
    assert {e["slug"] for e in index["decks"]} == set(build_site.deck_slugs())

    for entry in index["decks"]:
        with open(f"{build_site.OUT_DIR}/{entry['slug']}.json") as f:
            deck = json.load(f)
        assert deck["total"] == entry["total"]
        keys = [(c["name"], c["category"]) for c in deck["cards"]]
        assert len(keys) == len(set(keys)), f"{entry['slug']} has duplicate stacks"
        for card in deck["cards"]:
            assert card["type"] in build_site.TYPE_ORDER, card
            # A mangled decklist line would surface as a junk column heading.
            assert "[" not in card["category"] and "]" not in card["category"], card


def test_malformed_decklist_line_is_skipped_with_a_warning(tmp_path, capsys):
    """Two printings merged onto one line must not become a card or a category."""
    from parser import parse_decklist

    path = tmp_path / "decklist.txt"
    path.write_text("1x Gruul Turf (cmd) 280 [Land] (otj) 286 [Land]\n")
    parsed = parse_decklist(str(path))

    assert parsed["deck"] == []
    assert "Malformed line" in capsys.readouterr().err


def test_merged_stack_keeps_buy_and_foil_flags(monkeypatch, tmp_path):
    deck_dir = tmp_path / "decks" / "testdeck"
    deck_dir.mkdir(parents=True)
    (deck_dir / "decklist.txt").write_text(
        "1x Forest (pip) 1 [Land]\n"
        "1x Forest (pip) 2 *F* [Land,Buy]\n"
    )
    monkeypatch.setattr(build_site, "DECKS_DIR", str(tmp_path / "decks"))
    monkeypatch.setattr(build_site, "get_card",
                        lambda name: sf(type_line="Basic Land — Forest", mana_cost=""))

    deck, _ = build_site.build_deck("testdeck")

    stack = deck["cards"][0]
    assert stack["count"] == 2 and stack["buy"] is True and stack["foil"] is True


# --- stats tab data ---

def test_deck_stats_types_curve_and_average():
    cards = [
        build_site.build_card(row("Forest", count=3),
                              sf(type_line="Basic Land — Forest", mana_cost="", cmc=0.0)),
        build_site.build_card(row("Llanowar Elves"), sf(cmc=1.0), ["ramp", "mana-dork"]),
        build_site.build_card(row("Beast Within"),
                              sf(type_line="Instant", cmc=3.0), ["removal"]),
    ]
    stats = build_site.deck_stats(cards, {"ramp": 1})

    assert stats["types"] == {"Creature": 1, "Instant": 1, "Land": 3}
    assert stats["curve"] == {"1": 1, "3": 1}   # lands are excluded
    assert stats["avg_cmc"] == 2.0
    assert stats["otags"] == {"ramp": 1}


def test_deck_stats_template_counts_a_card_once_per_category():
    """A removal spell that also counters counts once toward disruption."""
    cards = [
        build_site.build_card(row("Repulsive Mutation"), sf(type_line="Instant"),
                              ["removal", "counterspell"]),
        build_site.build_card(row("Cultivate"), sf(type_line="Sorcery"), ["ramp"]),
        build_site.build_card(row("Forest", count=38),
                              sf(type_line="Basic Land — Forest", mana_cost="")),
    ]
    template = {t["label"]: t for t in build_site.deck_stats(cards, {})["template"]}

    assert template["Targeted disruption"]["count"] == 1
    assert template["Ramp"]["count"] == 1
    assert template["Lands"] == {"label": "Lands", "count": 38, "target": 38}


def test_committed_bundle_has_stats_for_every_deck():
    for slug in build_site.deck_slugs():
        with open(f"{build_site.OUT_DIR}/{slug}.json") as f:
            deck = json.load(f)
        stats = deck["stats"]
        assert stats["types"] and stats["curve"] and stats["template"]
        # otags come from cache/otags.json; every real deck should have some
        assert stats["otags"], slug


# --- split cards and modal lands ---

def test_front_face_cmc_uses_only_the_front_half_of_a_split_card():
    # Scryfall reports cmc 8 for Find // Finality: both halves added together.
    split = sf(mana_cost="{B/G}{B/G} // {4}{B}{G}", cmc=8.0)
    assert build_site.front_face_cmc(split) == 2.0

    # Anything that isn't split keeps Scryfall's value, back face and all.
    assert build_site.front_face_cmc(sf(mana_cost="{3}{G}{G}", cmc=5.0)) == 5.0


@pytest.mark.parametrize("cost,expected", [
    ("{2}{X} // {2}", 2.0),        # X is 0 when the spell is cast
    ("{2/B}{G} // {1}", 3.0),      # {2/B} costs 2 or B, so it counts as 2
    ("{G/W/P} // {1}", 1.0),
])
def test_front_face_cmc_symbol_values(cost, expected):
    assert build_site.front_face_cmc(sf(mana_cost=cost, cmc=99.0)) == expected


@pytest.mark.parametrize("type_line,land", [
    ("Creature — Goblin // Land", True),      # MDFC land back still makes a drop
    ("Sorcery // Land", True),
    ("Land // Land", True),
    ("Basic Land — Forest", True),
    ("Creature — Human", False),
    ("Sorcery", False),
])
def test_is_land_looks_at_every_face(type_line, land):
    assert build_site.is_land(sf(type_line=type_line)) is land


def test_land_template_row_counts_modal_land_backs():
    """An MDFC files under its front face in the columns but is still a land."""
    cards = [
        build_site.build_card(row("Boggart Trawler"),
                              sf(type_line="Creature — Goblin // Land", mana_cost="{2}{B}")),
        build_site.build_card(row("Forest", count=36),
                              sf(type_line="Basic Land — Forest", mana_cost="")),
    ]
    stats = build_site.deck_stats(cards, {})
    lands = {t["label"]: t["count"] for t in stats["template"]}["Lands"]

    assert stats["types"] == {"Creature": 1, "Land": 36}
    assert lands == 37


def test_committed_bundle_curve_has_no_split_card_inflation():
    """No deck should show a card at a mana value it can't be cast for."""
    for slug in build_site.deck_slugs():
        with open(f"{build_site.OUT_DIR}/{slug}.json") as f:
            deck = json.load(f)
        for card in deck["cards"]:
            if " // " in (card["mana_cost"] or ""):
                front = build_site.front_face_cost(card["mana_cost"])
                assert card["cmc"] <= 10, (slug, card["name"])
                assert card["cmc"] == build_site.front_face_cmc(
                    {"mana_cost": card["mana_cost"], "cmc": card["cmc"]}), (slug, card["name"], front)
