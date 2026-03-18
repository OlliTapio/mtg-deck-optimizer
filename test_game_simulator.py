"""Tests for game_simulator.py — Commander game simulation engine."""
import random
import pytest
from game_simulator import (
    Permanent, Player, GameState, Opponent,
    make_card, make_land, make_spell,
    get_available_mana, can_cast, tap_mana_for,
    play_land, cast_spell, create_token,
    resolve_combat, opponent_turn, check_game_over,
    init_game_from_cards, format_state,
    evaluate_hand_for_mulligan,
)


# ---- Test helpers ----

def _forest():
    return make_land("Forest", produced_mana=["G"])


def _mountain():
    return make_land("Mountain", produced_mana=["R"])


def _plains():
    return make_land("Plains", produced_mana=["W"])


def _command_tower():
    return make_land("Command Tower", produced_mana=["W", "U", "B", "R", "G"])


def _sol_ring():
    return make_spell("Sol Ring", cmc=1, mana_cost="{1}", type_line="Artifact",
                      produced_mana=["C", "C"])


def _grizzly_bears():
    return make_spell("Grizzly Bears", cmc=2, mana_cost="{1}{G}",
                      type_line="Creature — Bear", power=2, toughness=2)


def _lightning_bolt():
    return make_spell("Lightning Bolt", cmc=1, mana_cost="{R}",
                      type_line="Instant")


def _wrath_of_god():
    return make_spell("Wrath of God", cmc=4, mana_cost="{2}{W}{W}",
                      type_line="Sorcery")


def _llanowar_elves():
    return make_spell("Llanowar Elves", cmc=1, mana_cost="{G}",
                      type_line="Creature — Elf Druid", power=1, toughness=1,
                      produced_mana=["G"])


def _commander():
    return make_spell("Test Commander", cmc=5, mana_cost="{3}{R}{G}",
                      type_line="Legendary Creature — Beast", power=4, toughness=4,
                      is_commander=True)


def _make_player(hand=None, battlefield=None, library=None, life=40):
    p = Player(name="Test", life=life)
    if hand:
        p.hand = list(hand)
    if battlefield:
        p.battlefield = [Permanent(card=c) for c in battlefield]
    if library:
        p.library = list(library)
    return p


# ---- Deck loading ----

class TestDeckLoading:
    def test_commander_in_command_zone(self):
        cmdr = _commander()
        cards = [cmdr] + [_forest() for _ in range(35)] + [_grizzly_bears() for _ in range(64)]
        gs = init_game_from_cards(cards, seed=42)
        assert gs.player.command_zone == [cmdr]
        assert cmdr not in gs.player.library

    def test_99_in_library(self):
        cmdr = _commander()
        cards = [cmdr] + [_forest() for _ in range(35)] + [_grizzly_bears() for _ in range(64)]
        gs = init_game_from_cards(cards, seed=42)
        # 99 in library, then 7 drawn to hand
        assert len(gs.player.library) + len(gs.player.hand) == 99

    def test_shuffle_is_randomized(self):
        cmdr = _commander()
        # Make each card distinguishable
        cards = [cmdr] + [make_land(f"Land_{i}", produced_mana=["G"]) for i in range(99)]
        gs1 = init_game_from_cards(cards, seed=1)
        gs2 = init_game_from_cards(cards, seed=2)
        # Different seeds should give different library orders
        lib1_names = [c['name'] for c in gs1.player.library]
        lib2_names = [c['name'] for c in gs2.player.library]
        assert lib1_names != lib2_names


# ---- Draw ----

class TestDraw:
    def test_draw_moves_card_to_hand(self):
        p = _make_player(library=[_forest(), _mountain()])
        top = p.library[-1]
        p.draw()
        assert top in p.hand
        assert top not in p.library

    def test_draw_from_empty_library(self):
        p = _make_player(library=[])
        p.draw()
        assert p.life <= 0  # loses the game


# ---- Mana calculation ----

class TestMana:
    def test_untapped_lands_produce_mana(self):
        p = _make_player(battlefield=[_forest(), _mountain(), _plains()])
        mana = get_available_mana(p)
        assert mana['G'] >= 1
        assert mana['R'] >= 1
        assert mana['W'] >= 1
        assert mana['total'] >= 3

    def test_tapped_lands_dont_produce(self):
        p = _make_player(battlefield=[_forest()])
        p.battlefield[0].tapped = True
        mana = get_available_mana(p)
        assert mana['total'] == 0

    def test_multicolor_land(self):
        p = _make_player(battlefield=[_command_tower()])
        mana = get_available_mana(p)
        assert mana['total'] >= 1
        assert mana['W'] >= 1
        assert mana['G'] >= 1

    def test_nonland_mana_source(self):
        p = _make_player(battlefield=[_sol_ring()])
        mana = get_available_mana(p)
        assert mana['C'] >= 2
        assert mana['total'] >= 2

    def test_creature_mana_source(self):
        p = _make_player(battlefield=[_llanowar_elves()])
        # Summoning sick creature can't tap for mana
        p.battlefield[0].summoning_sick = True
        mana = get_available_mana(p)
        assert mana['total'] == 0

        # Not summoning sick
        p.battlefield[0].summoning_sick = False
        mana = get_available_mana(p)
        assert mana['G'] >= 1


# ---- can_cast ----

class TestCanCast:
    def test_can_cast_with_enough_mana(self):
        p = _make_player(battlefield=[_forest(), _forest(), _mountain()])
        card = _grizzly_bears()  # {1}{G}
        assert can_cast(p, card) is True

    def test_cannot_cast_wrong_colors(self):
        p = _make_player(battlefield=[_mountain(), _mountain()])
        card = _grizzly_bears()  # {1}{G}
        assert can_cast(p, card) is False

    def test_cannot_cast_not_enough_mana(self):
        p = _make_player(battlefield=[_forest()])
        card = _grizzly_bears()  # {1}{G} = 2 total
        assert can_cast(p, card) is False

    def test_can_cast_colorless(self):
        p = _make_player(battlefield=[_mountain()])
        card = _sol_ring()  # {1}
        assert can_cast(p, card) is True

    def test_commander_tax(self):
        p = _make_player(battlefield=[_forest(), _forest(), _mountain(), _mountain(), _plains()])
        cmdr = _commander()  # {3}{R}{G} = 5 CMC
        assert can_cast(p, cmdr, commander_tax=0) is True
        assert can_cast(p, cmdr, commander_tax=2) is False  # would need 7


# ---- tap_mana_for ----

class TestTapManaFor:
    def test_taps_correct_lands(self):
        p = _make_player(battlefield=[_forest(), _forest(), _mountain()])
        card = _grizzly_bears()  # {1}{G}
        success = tap_mana_for(p, card)
        assert success
        tapped = [perm for perm in p.battlefield if perm.tapped]
        assert len(tapped) == 2

    def test_prefers_mono_for_pips(self):
        # Should tap Forest for {G} pip and Command Tower for {1}, not the other way
        p = _make_player(battlefield=[_forest(), _command_tower()])
        card = _grizzly_bears()  # {1}{G}
        tap_mana_for(p, card)
        forest_perm = next(perm for perm in p.battlefield if perm.card['name'] == 'Forest')
        assert forest_perm.tapped  # Forest should be tapped for the G pip

    def test_fails_if_not_enough_mana(self):
        p = _make_player(battlefield=[_forest()])
        card = _grizzly_bears()  # {1}{G}
        success = tap_mana_for(p, card)
        assert not success


# ---- play_land ----

class TestPlayLand:
    def test_play_land_moves_to_battlefield(self):
        land = _forest()
        p = _make_player(hand=[land])
        success = play_land(p, land)
        assert success
        assert land not in p.hand
        assert any(perm.card is land for perm in p.battlefield)

    def test_play_land_decrements_drops(self):
        p = _make_player(hand=[_forest()])
        assert p.land_drops_remaining == 1
        play_land(p, p.hand[0])
        assert p.land_drops_remaining == 0

    def test_cannot_play_second_land(self):
        p = _make_player(hand=[_forest(), _mountain()])
        play_land(p, p.hand[0])
        success = play_land(p, p.hand[0])
        assert not success

    def test_land_not_in_hand_fails(self):
        p = _make_player(hand=[])
        success = play_land(p, _forest())
        assert not success


# ---- cast_spell ----

class TestCastSpell:
    def test_cast_permanent_to_battlefield(self):
        card = _grizzly_bears()
        p = _make_player(hand=[card], battlefield=[_forest(), _forest()])
        success = cast_spell(p, card)
        assert success
        assert card not in p.hand
        assert any(perm.card is card for perm in p.battlefield)

    def test_cast_instant_to_graveyard(self):
        card = _lightning_bolt()
        p = _make_player(hand=[card], battlefield=[_mountain()])
        success = cast_spell(p, card)
        assert success
        assert card in p.graveyard

    def test_cast_sorcery_to_graveyard(self):
        card = _wrath_of_god()
        p = _make_player(hand=[card], battlefield=[_plains(), _plains(), _forest(), _mountain()])
        success = cast_spell(p, card)
        assert success
        assert card in p.graveyard

    def test_cast_fails_without_mana(self):
        card = _grizzly_bears()
        p = _make_player(hand=[card], battlefield=[])
        success = cast_spell(p, card)
        assert not success
        assert card in p.hand

    def test_creatures_have_summoning_sickness(self):
        card = _grizzly_bears()
        p = _make_player(hand=[card], battlefield=[_forest(), _forest()])
        cast_spell(p, card)
        perm = next(perm for perm in p.battlefield if perm.card is card)
        assert perm.summoning_sick


# ---- Combat ----

class TestCombat:
    def test_attackers_deal_damage(self):
        bear = _grizzly_bears()
        p = _make_player(battlefield=[bear])
        p.battlefield[0].summoning_sick = False
        opp = Opponent(name="Opp", archetype="midrange")
        attacks = [(p.battlefield[0], opp)]
        resolve_combat(p, attacks)
        assert opp.life == 40 - 2  # bear is 2/2

    def test_summoning_sick_cant_attack(self):
        bear = _grizzly_bears()
        p = _make_player(battlefield=[bear])
        p.battlefield[0].summoning_sick = True
        opp = Opponent(name="Opp", archetype="midrange")
        attacks = [(p.battlefield[0], opp)]
        resolve_combat(p, attacks)
        assert opp.life == 40  # no damage dealt

    def test_tapped_cant_attack(self):
        bear = _grizzly_bears()
        p = _make_player(battlefield=[bear])
        p.battlefield[0].tapped = True
        opp = Opponent(name="Opp", archetype="midrange")
        attacks = [(p.battlefield[0], opp)]
        resolve_combat(p, attacks)
        assert opp.life == 40


# ---- Opponent turn ----

class TestOpponentTurn:
    def test_board_power_grows(self):
        opp = Opponent(name="Aggro", archetype="aggro")
        initial = opp.board_power
        opponent_turn(opp, turn_number=3, player=_make_player(), rng=random.Random(42))
        assert opp.board_power > initial

    def test_opponent_attacks_player(self):
        p = _make_player(life=40)
        opp = Opponent(name="Aggro", archetype="aggro")
        opp.board_power = 5
        # Run enough turns to ensure at least some damage
        total_damage = 0
        for _ in range(20):
            opp_copy = Opponent(name="Aggro", archetype="aggro")
            opp_copy.board_power = 5
            p_copy = _make_player(life=40)
            opponent_turn(opp_copy, turn_number=5, player=p_copy, rng=random.Random(_))
            total_damage += (40 - p_copy.life)
        assert total_damage > 0  # over 20 runs, should deal some damage

    def test_opponent_evasion_increases_over_turns(self):
        # Late-game evasion should be possible
        rng = random.Random(42)
        opp = Opponent(name="Aggro", archetype="aggro")
        opp.board_power = 8
        p = _make_player(life=40)
        # Just verify no crash and damage can happen at high turns
        opponent_turn(opp, turn_number=12, player=p, rng=rng)
        # No assertion on exact value, just that it runs without error

    def test_removal_reduces_board(self):
        p = _make_player(battlefield=[_grizzly_bears()])
        p.battlefield[0].summoning_sick = False
        opp = Opponent(name="Control", archetype="control")
        opp.board_power = 3
        # Run many times, at least once removal should fire
        removed_count = 0
        for seed in range(50):
            p_copy = _make_player(battlefield=[_grizzly_bears()])
            p_copy.battlefield[0].summoning_sick = False
            opp_copy = Opponent(name="Control", archetype="control")
            opp_copy.board_power = 3
            opponent_turn(opp_copy, turn_number=5, player=p_copy, rng=random.Random(seed))
            if len(p_copy.battlefield) == 0:
                removed_count += 1
        assert removed_count > 0

    def test_ai_removal_reduces_board_power(self):
        opp = Opponent(name="Mid", archetype="midrange")
        opp.board_power = 10
        opp.apply_removal(3)  # 3 CMC removal spell
        assert opp.board_power < 10

    def test_combo_opponent_attempts_win(self):
        opp = Opponent(name="Combo", archetype="combo")
        opp.combo_turn = 8
        # Before combo turn, no attempt
        assert opp.should_attempt_combo(turn_number=5) is False
        assert opp.should_attempt_combo(turn_number=8) is True


# ---- Game over ----

class TestGameOver:
    def test_player_dies_at_zero_life(self):
        p = _make_player(life=0)
        opps = [Opponent(name="O", archetype="aggro")]
        assert check_game_over(p, opps) is True

    def test_one_opponent_dies_game_continues(self):
        p = _make_player(life=40)
        opp1 = Opponent(name="O1", archetype="aggro")
        opp1.life = 0
        opp2 = Opponent(name="O2", archetype="midrange")
        assert check_game_over(p, [opp1, opp2]) is False  # game continues, one opp still alive

    def test_all_opponents_dead(self):
        p = _make_player(life=40)
        opps = [Opponent(name=f"O{i}", archetype="aggro") for i in range(3)]
        for o in opps:
            o.life = 0
        assert check_game_over(p, opps) is True  # player wins

    def test_game_not_over(self):
        p = _make_player(life=40)
        opps = [Opponent(name="O", archetype="aggro")]
        assert check_game_over(p, opps) is False


# ---- State formatting ----

class TestFormatState:
    def test_format_includes_essential_info(self):
        cmdr = _commander()
        p = _make_player(hand=[_grizzly_bears()], battlefield=[_forest()], life=38)
        p.command_zone = [cmdr]
        opps = [Opponent(name="Aggro", archetype="aggro")]
        gs = GameState(player=p, opponents=opps, turn_number=3, phase="main1")
        output = format_state(gs)
        assert "Turn 3" in output
        assert "main1" in output
        assert "38" in output  # life
        assert "Forest" in output
        assert "Grizzly Bears" in output
        assert "Test Commander" in output
        assert "Aggro" in output


# ---- Mulligan ----

class TestMulligan:
    def test_keepable_hand(self):
        hand = [_forest(), _forest(), _mountain(), _grizzly_bears(),
                _lightning_bolt(), _llanowar_elves(), _wrath_of_god()]
        keepable, reason = evaluate_hand_for_mulligan(hand)
        assert keepable is True

    def test_too_few_lands_mulligans(self):
        hand = [_forest(), _grizzly_bears(), _grizzly_bears(), _grizzly_bears(),
                _lightning_bolt(), _llanowar_elves(), _wrath_of_god()]
        keepable, reason = evaluate_hand_for_mulligan(hand)
        assert keepable is False
        assert "too few" in reason

    def test_too_many_lands_mulligans(self):
        hand = [_forest(), _forest(), _mountain(), _plains(),
                _forest(), _mountain(), _grizzly_bears()]
        keepable, reason = evaluate_hand_for_mulligan(hand)
        assert keepable is False
        assert "too many" in reason

    def test_no_early_plays_mulligans(self):
        hand = [_forest(), _forest(), _wrath_of_god(),
                make_spell("Big Thing", cmc=7, mana_cost="{5}{G}{G}", type_line="Creature"),
                make_spell("Big Thing 2", cmc=6, mana_cost="{4}{G}{G}", type_line="Creature"),
                make_spell("Big Thing 3", cmc=5, mana_cost="{3}{G}{G}", type_line="Creature"),
                make_spell("Big Thing 4", cmc=8, mana_cost="{6}{G}{G}", type_line="Creature")]
        keepable, reason = evaluate_hand_for_mulligan(hand)
        assert keepable is False

    def test_mulligan_reduces_hand_size(self):
        cmdr = _commander()
        # All high-CMC nonlands + 0 lands = guaranteed mulligan
        cards = [cmdr] + [make_spell(f"Bomb_{i}", cmc=7, mana_cost="{5}{G}{G}",
                 type_line="Creature") for i in range(99)]
        gs = init_game_from_cards(cards, seed=42)
        # After 2 mulligans, hand should be 5 (7 - 2)
        assert len(gs.player.hand) == 5

    def test_init_keeps_good_hand(self):
        cmdr = _commander()
        # 35 lands + 64 bears = very likely to get a keepable hand
        cards = [cmdr] + [_forest() for _ in range(35)] + [_grizzly_bears() for _ in range(64)]
        gs = init_game_from_cards(cards, seed=42)
        assert len(gs.player.hand) == 7  # no mulligan needed


# ---- Opponent fights each other ----

class TestOpponentInteraction:
    def test_opponents_damage_each_other(self):
        p = _make_player(life=40)
        opps = [Opponent(name="Aggro", archetype="aggro"),
                Opponent(name="Mid", archetype="midrange"),
                Opponent(name="Control", archetype="control")]
        # Give them board power so they can deal damage
        for o in opps:
            o.board_power = 10

        total_opp_damage = 0
        for seed in range(50):
            opps_copy = [Opponent(name="Aggro", archetype="aggro"),
                         Opponent(name="Mid", archetype="midrange"),
                         Opponent(name="Control", archetype="control")]
            for o in opps_copy:
                o.board_power = 10
            p_copy = _make_player(life=40)
            for o in opps_copy:
                opponent_turn(o, turn_number=5, player=p_copy, rng=random.Random(seed),
                              other_opponents=opps_copy)
            # Check if any opponent took damage from another
            for o in opps_copy:
                total_opp_damage += (40 - o.life)
        assert total_opp_damage > 0  # opponents should damage each other

    def test_removal_skips_lands(self):
        # Battlefield with only lands should not get removed
        p = _make_player(battlefield=[_forest(), _mountain(), _plains()])
        opp = Opponent(name="Control", archetype="control")
        opp.board_power = 5
        for seed in range(50):
            p_copy = _make_player(battlefield=[_forest(), _mountain(), _plains()])
            opponent_turn(opp, turn_number=5, player=p_copy, rng=random.Random(seed))
            assert len(p_copy.battlefield) == 3  # lands never removed

    def test_board_power_caps(self):
        opp = Opponent(name="Aggro", archetype="aggro")
        for turn in range(1, 20):
            opponent_turn(opp, turn_number=turn, player=_make_player(), rng=random.Random(turn))
        assert opp.board_power <= opp.max_board_power
