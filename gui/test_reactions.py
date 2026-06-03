#!/usr/bin/env python3
"""
Test suite for the reaction system (REACTION_SYSTEM_PLAN.md) — Opportunity Attacks.

The OA rule now lives in the C++ engine. These tests drive it headlessly via the
auto driver (resolve_move) with a scripted CombatDecider, plus a direct
begin_move/submit_decision loop to exercise the GUI suspend/resume path.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


# ── Scripted decider ─────────────────────────────────────────────────────────
class ScriptedDecider(rpg.CombatDecider):
    """Records each checkpoint and answers via a caller-supplied pick function.

    pick(ctx) -> int option index into ctx.options (-1 / a Skip index = no reaction).
    """
    def __init__(self, pick):
        super().__init__()
        self._pick = pick
        self.seen = []          # list of (reactor_idx, source_idx, [labels])

    def choose_reaction(self, ctx):
        self.seen.append((ctx.reactor_idx, ctx.source_idx,
                          [o.label for o in ctx.options]))
        resp = rpg.ReactionResponse()
        resp.option = self._pick(ctx)
        return resp


def pick_weapon(ctx):
    """Choose the first melee-weapon option (the OA)."""
    for i, o in enumerate(ctx.options):
        if o.kind == rpg.ReactionOptionKind.Weapon:
            return i
    return -1


def pick_skip(ctx):
    return -1


# ── Helpers ──────────────────────────────────────────────────────────────────
def equip_oa_weapon(engine, bm, idx, attack_bonus=20, num_dice=1, die_size=8, bonus=0):
    """Give an agent a guaranteed-hit melee weapon in slot 0 (others empty).

    Damage lives in physical_damage_types (PhysicalDamageRoll list) — the scalar
    damage_dice field is legacy/ignored after the per-type weapon-damage refactor.
    """
    w = rpg.Weapon()
    w.name = "Test Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.attack_bonus = attack_bonus
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = num_dice
    pr.die_size = die_size
    pr.bonus = bonus
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, idx, [w, rpg.Weapon(), rpg.Weapon()])


def ready_mover(engine, bm, idx, walk=60):
    """Give the mover a walk speed and start its turn so it has a movement budget.
    (Call before setting any per-turn condition like `disengaging`, which begin_turn resets.)"""
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = walk
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    # Seed the Agent's own movement budget — BattleMap::moveAgent reads pa.agent->getWalkRemaining(),
    # which begin_turn does NOT set (the GUI seeds it via _reset_movement -> init_movement).
    bm.placed_agents[idx].init_movement(walk, 0, 0, 0)


def set_cond(engine, bm, idx, **flags):
    c = engine.get_agent_conditions(bm, idx)
    for k, v in flags.items():
        setattr(c, k, v)
    engine.set_agent_conditions(bm, idx, c)


def reaction_used(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx).reaction_used


def hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def pos(bm, idx):
    o = bm.placed_agents[idx].origin
    return (o.col, o.row)


# ── Tests ────────────────────────────────────────────────────────────────────
def test_leaving_one_of_two_threats_provokes_only_that_one():
    """Baseline bug fixed: leaving A while staying adjacent to B provokes A only."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    b = add_agent_to_battle(engine, bm, create_test_agent("ThreatB", 6, 5))
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, a); equip_oa_weapon(engine, bm, b)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)  # leaves A, stays by B

    reactors = [s[0] for s in dec.seen]
    assert reactors == [a], f"expected only ThreatA to provoke, got reactors={reactors}"
    assert reaction_used(engine, bm, a) and not reaction_used(engine, bm, b)
    print("✅ test_leaving_one_of_two_threats_provokes_only_that_one passed")


def test_leaving_both_threats_provokes_both():
    """Per-creature: leaving both A and B provokes both (one OA each)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 5, 4))
    b = add_agent_to_battle(engine, bm, create_test_agent("ThreatB", 5, 6))
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, a); equip_oa_weapon(engine, bm, b)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)

    assert sorted(s[0] for s in dec.seen) == sorted([a, b]), f"got {dec.seen}"
    print("✅ test_leaving_both_threats_provokes_both passed")


def test_per_step_graze_provokes_even_when_destination_is_clear():
    """Per-step: enter then leave C mid-path; origin AND destination are out of C's reach."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 2, 5))
    c = add_agent_to_battle(engine, bm, create_test_agent("ThreatC", 5, 4))
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, c)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)

    assert [s[0] for s in dec.seen] == [c], f"expected ThreatC mid-path OA, got {dec.seen}"
    print("✅ test_per_step_graze_provokes_even_when_destination_is_clear passed")


def test_used_reaction_blocks_oa():
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    set_cond(engine, bm, a, reaction_used=True)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert dec.seen == [], f"reaction already used should block OA, got {dec.seen}"
    print("✅ test_used_reaction_blocks_oa passed")


def test_incapacitated_reactor_makes_no_oa():
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    set_cond(engine, bm, a, incapacitated=True)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert dec.seen == [], f"incapacitated reactor should not OA, got {dec.seen}"
    print("✅ test_incapacitated_reactor_makes_no_oa passed")


def test_disengage_suppresses_oa():
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    set_cond(engine, bm, m, disengaging=True)   # after begin_turn, which resets per-turn flags

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert dec.seen == [], f"Disengage should suppress OAs, got {dec.seen}"
    assert pos(bm, m) == (6, 6), "mover should still complete the move"
    print("✅ test_disengage_suppresses_oa passed")


def test_no_decider_skips_all_reactions():
    """Auto driver with no decider installed: every reaction is skipped; move completes."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)

    results = engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert len(results) == 0, "no decider → no OA results"
    assert not reaction_used(engine, bm, a), "skip must not consume the reaction"
    assert pos(bm, m) == (6, 6), "move should complete"
    print("✅ test_no_decider_skips_all_reactions passed")


def test_skip_choice_completes_move_without_consuming_reaction():
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)

    dec = ScriptedDecider(pick_skip)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert len(dec.seen) == 1, "the checkpoint should still be offered"
    assert not reaction_used(engine, bm, a), "an explicit Skip must not consume the reaction"
    assert pos(bm, m) == (6, 6), "move completes after a skip"
    print("✅ test_skip_choice_completes_move_without_consuming_reaction passed")


def test_stop_on_down_halts_movement():
    """An OA that drops the mover halts it where it fell (does not finish the path)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    # Set the mover frail + low-AC AFTER all adds: apply_agent_configs (run on every add) recreates
    # agents from configs and resets the earlier agent's stats. Low AC so the OA lands (the engine's
    # to-hit ignores weapon.attack_bonus); huge weapon damage so any hit is lethal.
    s = engine.get_agent_stats(bm, m); s.hp_max = 1; s.hp_cur = 1; s.base_ac = 1
    engine.set_agent_stats(bm, m, s)
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, a, num_dice=10, die_size=12, bonus=100)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(9, 5), rpg.MovementType.Walk)

    assert hp(engine, bm, m) <= 0, "mover should be downed by the OA"
    assert pos(bm, m) == (5, 5), f"downed mover must stop where it fell, got {pos(bm, m)}"
    print("✅ test_stop_on_down_halts_movement passed")


def test_begin_submit_suspend_resume_path():
    """GUI path: begin_move parks at a checkpoint; submit_decision resumes to completion."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)

    # No decider installed → begin_move must suspend at the OA checkpoint.
    status = engine.begin_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected suspend, got {status}"
    pd = engine.pending_decision()
    assert pd.active and pd.ctx.reactor_idx == a
    assert pd.ctx.window == rpg.ReactionWindow.LeftReach

    # Pick the weapon OA and resume.
    resp = rpg.ReactionResponse()
    resp.option = pick_weapon(pd.ctx)
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed, f"expected completion, got {status}"
    assert not engine.pending_decision().active
    assert reaction_used(engine, bm, a), "the OA should have consumed the reaction"
    assert pos(bm, m) == (6, 6), "move completes after the checkpoint resolves"
    print("✅ test_begin_submit_suspend_resume_path passed")


def run_all():
    test_leaving_one_of_two_threats_provokes_only_that_one()
    test_leaving_both_threats_provokes_both()
    test_per_step_graze_provokes_even_when_destination_is_clear()
    test_used_reaction_blocks_oa()
    test_incapacitated_reactor_makes_no_oa()
    test_disengage_suppresses_oa()
    test_no_decider_skips_all_reactions()
    test_skip_choice_completes_move_without_consuming_reaction()
    test_stop_on_down_halts_movement()
    test_begin_submit_suspend_resume_path()
    print("\nAll reaction-system tests passed ✅")


if __name__ == "__main__":
    run_all()
