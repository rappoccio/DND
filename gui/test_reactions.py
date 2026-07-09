#!/usr/bin/env python3
"""
Test suite for the reaction system — Opportunity Attacks.

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
def equip_oa_weapon(engine, bm, idx, num_dice=1, die_size=8, bonus=0):
    """Give an agent a guaranteed-hit melee weapon in slot 0 (others empty).

    Damage lives in physical_damage_types (PhysicalDamageRoll list) — the scalar
    damage_dice field is legacy/ignored after the per-type weapon-damage refactor.
    """
    w = rpg.Weapon()
    w.name = "Test Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
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


def test_ally_does_not_provoke_oa():
    """A teammate (same non-zero faction) does not get an OA when an ally leaves its reach;
    an enemy on a different faction still does."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m     = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    ally  = add_agent_to_battle(engine, bm, create_test_agent("Ally",  4, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))
    bm.set_agent_faction(m, 1); bm.set_agent_faction(ally, 1)   # red team
    bm.set_agent_faction(enemy, 2)                              # blue team
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, ally); equip_oa_weapon(engine, bm, enemy)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(5, 8), rpg.MovementType.Walk)  # leaves both ally and enemy

    reactors = [s[0] for s in dec.seen]
    assert reactors == [enemy], f"only the enemy should provoke, got reactors={reactors}"
    assert not reaction_used(engine, bm, ally), "the ally must not spend a reaction on a teammate"
    print("✅ test_ally_does_not_provoke_oa passed")


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


def test_sentinel_provokes_oa_despite_disengage():
    """Sentinel feat (clause 2): a creature provokes an OA from a has_sentinel threatener even when it
    Disengages — the per-reactor exception in detectProvokes."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    s = engine.get_agent_stats(bm, a); s.has_sentinel = True
    engine.set_agent_stats(bm, a, s)
    set_cond(engine, bm, m, disengaging=True)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)  # leaves the Sentinel's reach
    assert len(dec.seen) == 1 and dec.seen[0][0] == a, \
        f"Sentinel should still get the OA despite Disengage, got {dec.seen}"
    assert reaction_used(engine, bm, a), "the Sentinel OA spends the reaction"
    print("✅ test_sentinel_provokes_oa_despite_disengage passed")


def test_sentinel_disengage_only_helps_the_sentinel():
    """A non-Sentinel threatener is still suppressed by Disengage even when a Sentinel is also present."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    plain = add_agent_to_battle(engine, bm, create_test_agent("Plain", 4, 5))
    sent  = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 5, 4))
    ready_mover(engine, bm, m)
    equip_oa_weapon(engine, bm, plain); equip_oa_weapon(engine, bm, sent)
    s = engine.get_agent_stats(bm, sent); s.has_sentinel = True
    engine.set_agent_stats(bm, sent, s)
    set_cond(engine, bm, m, disengaging=True)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(7, 7), rpg.MovementType.Walk)  # leaves both reaches
    reactors = [seen[0] for seen in dec.seen]
    assert sent in reactors and plain not in reactors, \
        f"only the Sentinel should provoke through Disengage, got {reactors}"
    print("✅ test_sentinel_disengage_only_helps_the_sentinel passed")


def test_sentinel_oa_hit_halts_mover_speed_zero():
    """Sentinel feat (clause 1): a Sentinel-feated reactor that HITS with its OA stops the mover at the
    provoke cell and zeroes its movement for the rest of the turn (speed → 0)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    # Survive the OA (→ halted, not down) but make the hit reliable by giving the
    # target base_ac = 1 (same idiom as the stop-on-down test).
    s = engine.get_agent_stats(bm, m); s.hp_max = 50; s.hp_cur = 50; s.base_ac = 1
    engine.set_agent_stats(bm, m, s)
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    sa = engine.get_agent_stats(bm, a); sa.has_sentinel = True
    engine.set_agent_stats(bm, a, sa)

    dec = ScriptedDecider(pick_weapon); engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)  # tries to flee past the Sentinel
    assert pos(bm, m) == (5, 5), \
        f"a Sentinel OA hit should stop the mover at the provoke cell, got {pos(bm, m)}"
    assert bm.placed_agents[m].walk_remaining == 0, "Sentinel hit → speed 0 for the rest of the turn"
    print("✅ test_sentinel_oa_hit_halts_mover_speed_zero passed")


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
    # agents from configs and resets the earlier agent's stats. Low AC so the OA lands;
    # huge weapon damage so any hit is lethal.
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


# ── Sentinel Guardian (OnAllyAttacked bystander reaction) ─────────────────────
def pick_sentinel_guard(ctx):
    """Choose the SentinelGuard Feature option (the Guardian counter-attack)."""
    for i, o in enumerate(ctx.options):
        if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "SentinelGuard":
            return i
    return -1


def _make_sentinel(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.has_sentinel = True
    engine.set_agent_stats(bm, idx, s)


def test_sentinel_guardian_counterattacks_adjacent_attacker():
    """Guardian: an attacker (5,5) hits an ally (6,5); a Sentinel (4,5) adjacent to the attacker spends
    its reaction to make a melee attack back. The window opens on OnAllyAttacked; the attacker takes the
    counter-attack damage and the Sentinel's reaction is spent."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    sent = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    # Make the attacker frail/low-AC so the Sentinel's counter-attack reliably lands;
    # equip both attacker and Sentinel with a melee weapon.
    s = engine.get_agent_stats(bm, atk); s.hp_max = 50; s.hp_cur = 50; s.base_ac = 1
    engine.set_agent_stats(bm, atk, s)
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, sent)
    _make_sentinel(engine, bm, sent)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    hp_before = hp(engine, bm, atk)
    engine.execute_action(bm, rpg.Attack(atk, ally, 0))

    windows = [seen for seen in dec.seen if sent == seen[0]]
    assert windows and windows[0][1] == atk, f"Sentinel should be offered a guard vs the attacker, got {dec.seen}"
    assert reaction_used(engine, bm, sent), "the guard spends the Sentinel's reaction"
    assert hp(engine, bm, atk) < hp_before, "the counter-attack should damage the attacker"
    print("✅ test_sentinel_guardian_counterattacks_adjacent_attacker passed")


def test_sentinel_guardian_not_offered_when_attack_targets_the_sentinel():
    """RAW: Guardian only triggers for an attack against a target OTHER than the Sentinel. An attack
    aimed at the Sentinel itself opens no guard window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    sent = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, sent)
    _make_sentinel(engine, bm, sent)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    engine.execute_action(bm, rpg.Attack(atk, sent, 0))   # attack hits the Sentinel directly
    assert not any(seen[0] == sent for seen in dec.seen), \
        f"no guard when the attack targets the Sentinel, got {dec.seen}"
    print("✅ test_sentinel_guardian_not_offered_when_attack_targets_the_sentinel passed")


def test_sentinel_guardian_requires_adjacency_to_attacker():
    """Guardian needs the attacker within the Sentinel's 5 ft reach. A distant Sentinel gets no window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    sent = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 1, 1))  # far from the attacker
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, sent)
    _make_sentinel(engine, bm, sent)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    engine.execute_action(bm, rpg.Attack(atk, ally, 0))
    assert not any(seen[0] == sent for seen in dec.seen), \
        f"a non-adjacent Sentinel should not guard, got {dec.seen}"
    assert not reaction_used(engine, bm, sent)
    print("✅ test_sentinel_guardian_requires_adjacency_to_attacker passed")


def test_sentinel_guardian_fires_on_a_miss():
    """Guardian keys on the attack being MADE, not its outcome: it fires even when the triggering attack
    misses. (Give the ally a sky-high AC so the attack misses; the guard window still opens.)"""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    sent = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    sa = engine.get_agent_stats(bm, ally); sa.base_ac = 99
    engine.set_agent_stats(bm, ally, sa)
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, sent)
    _make_sentinel(engine, bm, sent)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    r = engine.execute_action(bm, rpg.Attack(atk, ally, 0))
    assert not r.hit, "the triggering attack should miss (AC 99)"
    assert any(seen[0] == sent for seen in dec.seen), \
        f"Guardian should fire even on a miss, got {dec.seen}"
    assert reaction_used(engine, bm, sent)
    print("✅ test_sentinel_guardian_fires_on_a_miss passed")


def test_sentinel_guardian_used_reaction_blocks_guard():
    """A Sentinel whose reaction is already spent gets no guard window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    sent = add_agent_to_battle(engine, bm, create_test_agent("Sentinel", 4, 5))
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, sent)
    _make_sentinel(engine, bm, sent)
    set_cond(engine, bm, sent, reaction_used=True)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    engine.execute_action(bm, rpg.Attack(atk, ally, 0))
    assert not any(seen[0] == sent for seen in dec.seen), \
        f"a spent reaction blocks the guard, got {dec.seen}"
    print("✅ test_sentinel_guardian_used_reaction_blocks_guard passed")


def test_sentinel_guardian_no_guard_of_a_guard():
    """Two adjacent Sentinels don't recurse: the first Sentinel's counter-attack must not itself open a
    Guardian window (resolving_sentinel_guard_ suppresses it). Exactly one guard fires per attack."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk   = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally  = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    # Two Sentinels, each adjacent to the attacker AND to each other.
    sentA = add_agent_to_battle(engine, bm, create_test_agent("SentinelA", 4, 5))
    sentB = add_agent_to_battle(engine, bm, create_test_agent("SentinelB", 4, 4))
    for s in (atk, sentA, sentB):
        equip_oa_weapon(engine, bm, s)
    _make_sentinel(engine, bm, sentA); _make_sentinel(engine, bm, sentB)

    dec = ScriptedDecider(pick_sentinel_guard); engine.set_decider(dec)
    engine.execute_action(bm, rpg.Attack(atk, ally, 0))
    # The original attack provokes one guard (sentA, the lower index). sentA's counter-attack strikes the
    # attacker — which, were it not suppressed, would re-provoke sentB. It must NOT: exactly one guard window.
    guard_windows = [seen for seen in dec.seen
                     if any("Sentinel Guardian" in label for label in seen[2])]
    assert len(guard_windows) == 1, f"exactly one guard window (no guard-of-a-guard), got {dec.seen}"
    print("✅ test_sentinel_guardian_no_guard_of_a_guard passed")


# ── Interception fighting style (OnAllyAttacked damage-reduction bystander) ───────────────────
def pick_interception(ctx):
    """Choose the Interception Feature option (the damage-reduction reaction)."""
    for i, o in enumerate(ctx.options):
        if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Interception":
            return i
    return -1


def _make_interceptor(engine, bm, idx):
    """Give an agent the Interception fighting style + a weapon (satisfies the Shield/weapon clause)."""
    s = engine.get_agent_stats(bm, idx)
    s.add_feat("Interception")
    engine.set_agent_stats(bm, idx, s)
    equip_oa_weapon(engine, bm, idx)


def _frail_target(engine, bm, idx, hp_val=100, ac=1):
    """A high-HP, low-AC creature: reliably hit, and never dropped to 0 (so v1 Interception applies)."""
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp_val; s.hp_cur = hp_val; s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _attack_until_hit(engine, bm, atk, tgt, tries=25):
    """Resolve the attack until it lands damage (avoids a flaky nat-1 fumble vs AC 1). A miss changes
    no HP and spends no interceptor reaction, so retrying is safe and any inline interception fires
    only on the landing hit."""
    r = None
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if r.hit and r.total_damage > 0:
            return r
    raise AssertionError("attack never landed damage")


def test_interception_reduces_ally_damage():
    """An attacker (5,5) hits an ally (6,5); an interceptor (7,5) within 5 ft of the ally spends its
    reaction to reduce the damage. Net HP loss is less than the rolled damage, and the reaction is spent."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    itc = add_agent_to_battle(engine, bm, create_test_agent("Interceptor", 7, 5))
    equip_oa_weapon(engine, bm, atk, num_dice=2, die_size=8)
    _frail_target(engine, bm, ally)
    _make_interceptor(engine, bm, itc)

    dec = ScriptedDecider(pick_interception); engine.set_decider(dec)
    hp_before = hp(engine, bm, ally)
    r = _attack_until_hit(engine, bm, atk, ally)
    net = hp_before - hp(engine, bm, ally)
    assert net < r.total_damage, f"Interception should reduce net damage ({net}) below the rolled damage ({r.total_damage})"
    assert reaction_used(engine, bm, itc), "Interception spends the interceptor's reaction"
    windows = [seen for seen in dec.seen if seen[0] == itc and seen[1] == atk]
    assert windows, f"the interceptor should be offered an OnAllyAttacked window vs the attacker, got {dec.seen}"
    print("✅ test_interception_reduces_ally_damage passed")


def test_interception_requires_adjacency_to_target():
    """The interceptor must be within 5 ft of the TARGET. A distant interceptor gets no window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    itc = add_agent_to_battle(engine, bm, create_test_agent("Interceptor", 1, 1))  # far from the ally
    equip_oa_weapon(engine, bm, atk)
    _frail_target(engine, bm, ally)
    _make_interceptor(engine, bm, itc)

    dec = ScriptedDecider(pick_interception); engine.set_decider(dec)
    hp_before = hp(engine, bm, ally)
    r = _attack_until_hit(engine, bm, atk, ally)
    assert hp_before - hp(engine, bm, ally) == r.total_damage, "a distant interceptor must not reduce damage"
    assert not reaction_used(engine, bm, itc)
    assert not any(seen[0] == itc for seen in dec.seen), f"no window for a non-adjacent interceptor, got {dec.seen}"
    print("✅ test_interception_requires_adjacency_to_target passed")


def test_interception_requires_the_feat():
    """Without the Interception fighting style, an adjacent ally gets no reduction window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    itc = add_agent_to_battle(engine, bm, create_test_agent("Bystander", 7, 5))
    equip_oa_weapon(engine, bm, atk); equip_oa_weapon(engine, bm, itc)  # armed, but NO feat
    _frail_target(engine, bm, ally)

    dec = ScriptedDecider(pick_interception); engine.set_decider(dec)
    hp_before = hp(engine, bm, ally)
    r = _attack_until_hit(engine, bm, atk, ally)
    assert hp_before - hp(engine, bm, ally) == r.total_damage, "no feat → no reduction"
    assert not reaction_used(engine, bm, itc)
    print("✅ test_interception_requires_the_feat passed")


def test_interception_apply_heals_target_directly():
    """apply_interception heals the target back by min(1d10+PB, damage) and spends the reaction."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    itc = add_agent_to_battle(engine, bm, create_test_agent("Interceptor", 7, 5))
    _frail_target(engine, bm, ally)
    _make_interceptor(engine, bm, itc)
    # Manually apply 20 damage's worth of HP loss, then intercept 20.
    s = engine.get_agent_stats(bm, ally); s.hp_cur = s.hp_max - 20; engine.set_agent_stats(bm, ally, s)
    hp_before = hp(engine, bm, ally)
    prevented = engine.apply_interception(bm, itc, ally, 20)
    assert prevented > 0, "apply_interception should prevent some damage"
    assert hp(engine, bm, ally) == hp_before + prevented, "the prevented amount is healed back"
    assert reaction_used(engine, bm, itc), "apply_interception spends the reaction"
    # A second attempt fails: the reaction is gone.
    assert engine.apply_interception(bm, itc, ally, 20) == -1, "no second interception without a reaction"
    print("✅ test_interception_apply_heals_target_directly passed")


def run_all():
    test_leaving_one_of_two_threats_provokes_only_that_one()
    test_leaving_both_threats_provokes_both()
    test_per_step_graze_provokes_even_when_destination_is_clear()
    test_used_reaction_blocks_oa()
    test_ally_does_not_provoke_oa()
    test_incapacitated_reactor_makes_no_oa()
    test_disengage_suppresses_oa()
    test_sentinel_provokes_oa_despite_disengage()
    test_sentinel_disengage_only_helps_the_sentinel()
    test_sentinel_oa_hit_halts_mover_speed_zero()
    test_sentinel_guardian_counterattacks_adjacent_attacker()
    test_sentinel_guardian_not_offered_when_attack_targets_the_sentinel()
    test_sentinel_guardian_requires_adjacency_to_attacker()
    test_sentinel_guardian_fires_on_a_miss()
    test_sentinel_guardian_used_reaction_blocks_guard()
    test_sentinel_guardian_no_guard_of_a_guard()
    test_interception_reduces_ally_damage()
    test_interception_requires_adjacency_to_target()
    test_interception_requires_the_feat()
    test_interception_apply_heals_target_directly()
    test_no_decider_skips_all_reactions()
    test_skip_choice_completes_move_without_consuming_reaction()
    test_stop_on_down_halts_movement()
    test_begin_submit_suspend_resume_path()
    print("\nAll reaction-system tests passed ✅")


if __name__ == "__main__":
    run_all()
