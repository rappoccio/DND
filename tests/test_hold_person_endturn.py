#!/usr/bin/env python3
"""
Tests for end-of-turn repeat saves (Hold Person / Hold Monster).

RAW: a creature Paralyzed by Hold Person "repeats the save at the end of each of its
turns, ending the spell on itself on a success." The engine models this with the
ActiveAgentCondition.save_at_end_of_turn flag:

  • beginTurn does NOT roll the shrug-off save for a flagged condition — the creature is
    simply barred from acting (still Paralyzed / turn skipped).
  • endTurn rolls the save. A success ends the condition, so the creature can act again
    starting on its NEXT turn.

Contrast: a condition WITHOUT the flag (the engine default) re-saves at the START of the
turn (beginTurn), so a success frees the creature to act that same turn.

The tests drive the condition directly via add_agent_condition (deterministic — no initial
cast save to fight) and force the save outcome by stacking the target's WIS modifier
against the condition's save_dc.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _paralyze(engine, bm, caster, target, save_dc, *, at_end_of_turn):
    """Apply a Hold-Person-style Paralyzed condition to `target` with a fixed save DC."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx = target
    c.caster_idx = caster
    c.condition_name = "Paralyzed"
    c.save_ability = rpg.SaveAbility.Wisdom
    c.save_dc = save_dc
    c.save_repeat_turns = 1
    c.next_save_turn = 0
    c.turns_remaining = 10
    c.save_at_end_of_turn = at_end_of_turn
    return engine.add_agent_condition(bm, c)


def _set_wis(engine, bm, idx, wis):
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis
    engine.set_agent_stats(bm, idx, s)


def _is_paralyzed(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx).paralyzed


def test_end_of_turn_flag_defers_save_past_begin_turn():
    """With save_at_end_of_turn: beginTurn must NOT free the creature (save deferred)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    target = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 6))
    _set_wis(engine, bm, target, 30)           # +10 WIS → would trivially beat DC 8
    _paralyze(engine, bm, caster, target, save_dc=8, at_end_of_turn=True)

    assert _is_paralyzed(engine, bm, target), "target should start Paralyzed"

    res = engine.begin_turn(bm, target)
    # The save is NOT rolled at the start — the creature is still Paralyzed and its turn is skipped,
    # even though a +10 save would auto-beat DC 8 if it had been rolled here.
    assert _is_paralyzed(engine, bm, target), "beginTurn must not end an end-of-turn-save condition"
    assert res.turn_skipped, "a Paralyzed creature's turn is still skipped"
    print("✅ test_end_of_turn_flag_defers_save_past_begin_turn passed")


def test_end_of_turn_success_frees_creature():
    """With save_at_end_of_turn: a successful save at endTurn ends the condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    target = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 6))
    _set_wis(engine, bm, target, 30)           # +10 WIS vs DC 8 → auto-succeed
    _paralyze(engine, bm, caster, target, save_dc=8, at_end_of_turn=True)

    engine.begin_turn(bm, target)              # skipped, no save
    assert _is_paralyzed(engine, bm, target), "still Paralyzed after begin"
    engine.end_turn(bm, target)                # save rolled here → succeeds
    assert not _is_paralyzed(engine, bm, target), "successful end-of-turn save must end Paralyzed"
    print("✅ test_end_of_turn_success_frees_creature passed")


def test_end_of_turn_failure_stays_paralyzed():
    """With save_at_end_of_turn: a failed save at endTurn keeps the condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    target = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 6))
    _set_wis(engine, bm, target, 1)            # -5 WIS vs DC 30 → auto-fail
    _paralyze(engine, bm, caster, target, save_dc=30, at_end_of_turn=True)

    engine.begin_turn(bm, target)
    engine.end_turn(bm, target)                # save rolled here → fails
    assert _is_paralyzed(engine, bm, target), "failed end-of-turn save keeps Paralyzed"
    print("✅ test_end_of_turn_failure_stays_paralyzed passed")


def test_default_condition_saves_at_start():
    """Without the flag (default): the save is rolled at the START of the turn (beginTurn)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    target = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 6))
    _set_wis(engine, bm, target, 30)           # +10 WIS vs DC 8 → auto-succeed
    _paralyze(engine, bm, caster, target, save_dc=8, at_end_of_turn=False)

    res = engine.begin_turn(bm, target)        # start-of-turn save → succeeds immediately
    assert not _is_paralyzed(engine, bm, target), "default condition must save at start of turn"
    assert "SAVED" in (res.save_roll_message or ""), "beginTurn should surface the save result"
    print("✅ test_default_condition_saves_at_start passed")


def test_paralyzed_large_target_auto_crit_from_any_side():
    """Live play 2026-11-24: a melee hit on a Paralyzed Large creature is a Critical Hit from
    every adjacent side, not only its top/left edge (footprint-to-footprint distance)."""
    from test_weapon_mastery import _mk_weapon, _three, _NO_MASTERY
    for col, row in [(7, 5), (5, 7), (4, 4), (7, 7)]:   # right, below, top-left, bottom-right
        bm = setup_battle_map()
        engine = setup_combat_engine()
        cfg = create_test_agent("Hezrou", 5, 5); cfg.size = 2
        target = add_agent_to_battle(engine, bm, cfg)
        atk = add_agent_to_battle(engine, bm, create_test_agent("Fighter", col, row))
        s = engine.get_agent_stats(bm, atk); s.str = 30; s.prof_bonus = 6
        engine.set_agent_stats(bm, atk, s)
        engine.set_agent_weapons(bm, atk, _three([_mk_weapon("Axe", _NO_MASTERY)]))
        t = engine.get_agent_stats(bm, target); t.base_ac = 1; t.hp_max = t.hp_cur = 500
        engine.set_agent_stats(bm, target, t)
        _paralyze(engine, bm, atk, target, 30, at_end_of_turn=True)
        r = engine.execute_action(bm, rpg.Attack(atk, target, 0))
        assert r.hit and r.critical, f"attacker at {(col, row)}: hit={r.hit} crit={r.critical}"
    print("✅ test_paralyzed_large_target_auto_crit_from_any_side passed")


def _run_all():
    tests = [
        test_end_of_turn_flag_defers_save_past_begin_turn,
        test_end_of_turn_success_frees_creature,
        test_end_of_turn_failure_stays_paralyzed,
        test_default_condition_saves_at_start,
        test_paralyzed_large_target_auto_crit_from_any_side,
    ]
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} Hold Person end-of-turn tests passed")


if __name__ == "__main__":
    _run_all()
