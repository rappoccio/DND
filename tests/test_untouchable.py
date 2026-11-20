#!/usr/bin/env python3
"""
Test suite for the Untouchable condition (Agent.Conditions.untouchable).

Untouchable is a DM-set, two-way seal for a creature that is still in the fight but out of
everyone's reach: Etherealness, or Strahd after phasing into a wall or the floor. It reuses the
Forcecage-Box seal (rules::sealedApart): exactly one of a pair being untouchable means nothing
passes between them.

  · no attack either way, and available_attacks drops the target   (test_attacks_*)
  · no perception across the seal                                    (test_no_perception_across)
  · a spell / an AoE does nothing across it                          (test_spell_*, test_aoe_*)
  · no opportunity attack either way                                 (test_no_oa_*)
  · it blocks no movement and is blocked by none                     (test_movement_*)
  · it keeps its initiative slot                                     (test_keeps_initiative)
  · two untouchable creatures interact normally                     (test_two_untouchables_*)
  · it survives a snapshot / restore                                 (test_survives_snapshot)
  · the right-click condition toggles set it; player screens drop it (test_right_click_*,
    test_player_screens_*)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_reactions import (ScriptedDecider, pick_weapon, equip_oa_weapon,
                            ready_mover, set_cond)
from test_spells_tier2 import _place, _strong_caster, _cast, _cast_aoe, _load_spell, _hp, _reach


def _duel(untouch_a=False, untouch_b=False):
    """Two adjacent enemies with guaranteed-hit melee weapons."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    a = _place(engine, bm, "Strahd", 5, 5, faction=2)
    b = _place(engine, bm, "Hero", 6, 5, faction=1)
    for i in (a, b):
        s = engine.get_agent_stats(bm, i)
        s.hp_max = s.hp_cur = 100
        engine.set_agent_stats(bm, i, s)
        equip_oa_weapon(engine, bm, i)
    if untouch_a: set_cond(engine, bm, a, untouchable=True)
    if untouch_b: set_cond(engine, bm, b, untouchable=True)
    return bm, engine, a, b


def _targets(engine, bm, idx):
    return {x.target_idx for x in engine.available_attacks(bm, idx)}


def test_attacks_blocked_both_ways():
    bm, engine, a, b = _duel(untouch_a=True)
    assert b not in _targets(engine, bm, a), "the untouchable creature can't pick the Hero"
    assert a not in _targets(engine, bm, b), "the Hero can't pick the untouchable creature"
    for atk, tgt in ((a, b), (b, a)):
        engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        assert _hp(engine, bm, tgt) == 100, "an attack never crosses the seal"
    print("✅ test_attacks_blocked_both_ways passed")


def test_attacks_control_without_untouchable():
    bm, engine, a, b = _duel()
    assert b in _targets(engine, bm, a) and a in _targets(engine, bm, b), "positive control"
    print("✅ test_attacks_control_without_untouchable passed")


def test_no_perception_across():
    bm, engine, a, b = _duel(untouch_a=True)
    assert not engine.can_perceive_target(bm, a, b)
    assert not engine.can_perceive_target(bm, b, a)
    print("✅ test_no_perception_across passed")


def test_spell_does_nothing_across():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    s = engine.get_agent_stats(bm, foe); s.hp_max = s.hp_cur = 200; s.dex = 1
    engine.set_agent_stats(bm, foe, s)
    set_cond(engine, bm, foe, untouchable=True)
    _cast(engine, bm, caster, _load_spell("Sacred Flame"), [foe])
    assert _hp(engine, bm, foe) == 200, "a spell never reaches an untouchable target"
    print("✅ test_spell_does_nothing_across passed")


def test_aoe_spares_only_the_untouchable():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 1, 1)
    ghost = _place(engine, bm, "Ghost", 6, 5, faction=2)
    grunt = _place(engine, bm, "Grunt", 6, 6, faction=2)
    _strong_caster(engine, bm, caster)
    for i in (ghost, grunt):
        s = engine.get_agent_stats(bm, i); s.hp_max = s.hp_cur = 200; s.dex = 1
        engine.set_agent_stats(bm, i, s)
    set_cond(engine, bm, ghost, untouchable=True)
    _cast_aoe(engine, bm, caster, _load_spell("Fireball"), ghost)
    assert _hp(engine, bm, ghost) == 200, "the untouchable creature is spared by the Fireball"
    assert _hp(engine, bm, grunt) < 200, "the creature beside it still burns (control)"
    print("✅ test_aoe_spares_only_the_untouchable passed")


def _oa_seen(untouch_mover, untouch_reactor):
    bm, engine = setup_battle_map(), setup_combat_engine()
    m = _place(engine, bm, "Mover", 5, 5, faction=2)
    r = _place(engine, bm, "Reactor", 4, 5, faction=1)
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, r)
    if untouch_mover:   set_cond(engine, bm, m, untouchable=True)
    if untouch_reactor: set_cond(engine, bm, r, untouchable=True)
    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(7, 5), rpg.MovementType.Walk)
    return dec.seen


def test_no_oa_either_way():
    assert _oa_seen(True, False) == [], "leaving reach while untouchable provokes nothing"
    assert _oa_seen(False, True) == [], "an untouchable creature makes no OA"
    assert _oa_seen(False, False), "positive control: the same move provokes"
    print("✅ test_no_oa_either_way passed")


def test_movement_through_and_into_untouchable_square():
    bm, engine = setup_battle_map(), setup_combat_engine()
    hero = _place(engine, bm, "Hero", 5, 5, faction=1)
    strahd = _place(engine, bm, "Strahd", 6, 5, faction=2)
    assert (6, 5) not in _reach(bm, hero), "control: an enemy square can't be entered"
    set_cond(engine, bm, strahd, untouchable=True)
    assert (6, 5) in _reach(bm, hero), "an untouchable creature blocks no one"
    assert (5, 5) in _reach(bm, strahd), "and is blocked by no one"
    print("✅ test_movement_through_and_into_untouchable_square passed")


def test_keeps_initiative():
    bm, engine, a, b = _duel(untouch_a=True)
    order = {e.agent_idx for e in engine.roll_initiative(bm)}
    assert a in order, "an untouchable creature keeps its place in initiative"
    print("✅ test_keeps_initiative passed")


def test_two_untouchables_interact():
    bm, engine, a, b = _duel(untouch_a=True, untouch_b=True)
    assert b in _targets(engine, bm, a) and a in _targets(engine, bm, b), \
        "two untouchable creatures share the same side of the seal"
    print("✅ test_two_untouchables_interact passed")


def test_survives_snapshot():
    bm, engine, a, b = _duel(untouch_a=True)
    text = bm.snapshot_json()
    set_cond(engine, bm, a, untouchable=False)
    bm.restore_json(text)
    assert engine.get_agent_conditions(bm, a).untouchable, "untouchable round-trips through a save"
    assert not engine.get_agent_conditions(bm, b).untouchable
    print("✅ test_survives_snapshot passed")


# ── GUI: the Conditions dialog checkbox, and player screens drop the token ──────
def _gui_app():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from test_strahd_lair import _app
    return _app()


def test_right_click_menu_toggles_untouchable():
    from test_combat_panel import _idx
    from menus import board
    app = _gui_app()
    skarn = _idx(app, "Skarn")
    assert ("Untouchable", "untouchable") in board.DM_CONDITIONS, "listed with the DM's condition toggles"
    assert board.toggle_condition(app, skarn, "untouchable") is True
    assert app.combat.get_agent_conditions(app.bm, skarn).untouchable, "one toggle turns it on"
    assert board.toggle_condition(app, skarn, "untouchable") is False
    assert not app.combat.get_agent_conditions(app.bm, skarn).untouchable, "a second turns it off"
    print("✅ test_right_click_menu_toggles_untouchable passed")


def test_player_screens_drop_untouchable_enemy():
    from test_combat_panel import _idx
    app = _gui_app()
    skarn = _idx(app, "Skarn")
    app.bm.set_agent_faction(skarn, 1)       # an enemy of the party (PC_FACTION is 2)
    pt = app.bm.placed_agents[skarn]
    assert not app._npc_concealed_from_party(skarn, pt), "control: a plain enemy is shown"
    set_cond(app.combat, app.bm, skarn, untouchable=True)
    pt = app.bm.placed_agents[skarn]
    assert app._npc_concealed_from_party(skarn, pt), "an untouchable enemy is hidden from players"
    print("✅ test_player_screens_drop_untouchable_enemy passed")


if __name__ == "__main__":
    test_attacks_blocked_both_ways()
    test_attacks_control_without_untouchable()
    test_no_perception_across()
    test_spell_does_nothing_across()
    test_aoe_spares_only_the_untouchable()
    test_no_oa_either_way()
    test_movement_through_and_into_untouchable_square()
    test_keeps_initiative()
    test_two_untouchables_interact()
    test_survives_snapshot()
    test_right_click_menu_toggles_untouchable()
    test_player_screens_drop_untouchable_enemy()
    print("\nAll Untouchable tests passed.")
