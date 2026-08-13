"""Tests for the deck site data build (build_site.py)."""
import json

import pytest

import build_site
from deck_analyzer import count_pips


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
    assert build_site.front_face_cost("{1}{B}{B} // {1}{B}{B}") == "{1}{B}{B}"
    assert build_site.front_face_cost("") == ""


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
