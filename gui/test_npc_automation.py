#!/usr/bin/env python3
"""
Test suite for NPC automation — NPC_AUTOMATION_PLAN.md Steps 1–5.

Step 1 added the per-agent flags (is_npc_automated / difficulty / strategy) + accessors. Step 2 added the
dedicated turn-driver seam: CombatEngine::run_npc_turn (NOT CombatDecider, a mid-flow oracle), the
resolve_strategy resolver seam (the single place the later difficulty→role→strategy override will live),
and the set_render_attack_hook visualization seam.

Step 3 implements the `Simple` strategy (== "preferMelee"): engage the nearest enemy (footprint distance,
faction-aware), move into melee reach, and make a full Attack action (num_attacks swings); if no enemy is
reachable to strike, Dash and advance toward the nearest. run_npc_turn is the headless RL entry point, so
these tests drive it with NO GUI — they ARE the headless-pass-through proof (Step 2f).

Step 4 adds the `PreferTargetCaster` strategy: the same Simple executor, but target selection prioritises
enemy spellcasters (any enemy with a non-empty known-spell list), falling back to nearest-enemy when no
caster is on the field.

Step 5 adds the `PreferRange` strategy: pick the best ranged weapon, focus-fire the lowest-HP enemy, and
KITE — position to maximise distance from the nearest enemy among cells that keep the target in weapon
range. Steps 3-5 are now ONE shared executor (runWeaponTurn) driven by an NpcStrategyPolicy.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _fp_dist(bm, a, b):
    pa, pb = bm.placed_agents[a], bm.placed_agents[b]
    return rpg.footprint_distance(pa.origin, pa.size, pb.origin, pb.size)


def _arm_melee(engine, bm, idx):
    """Give an agent an explicit melee weapon in the main hand (slot 0)."""
    weapons = [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()]
    engine.set_agent_weapons(bm, idx, weapons)


def _arm_ranged(engine, bm, idx, range_ft=80):
    """Give an agent an explicit RANGED weapon (slot 0). The shared create_ranged_weapon helper does not
    set the engine fields runWeaponTurn reads (type / normal_range_ft), so build one explicitly here."""
    w = rpg.Weapon()
    w.name = "Shortbow"
    w.type = rpg.WeaponType.Ranged
    w.normal_range_ft = range_ft
    w.damage_dice = 6
    w.damage_dice_count = 1
    engine.set_agent_weapons(bm, idx, [w, rpg.Weapon(), rpg.Weapon()])


def _automate(bm, idx, strategy=None):
    bm.set_agent_npc_automated(idx, True)
    if strategy is not None:
        bm.set_agent_npc_automation_strategy(idx, strategy)


def _make_caster(engine, bm, idx):
    """Give an agent a (single, otherwise-empty) known spell so npcIsCaster treats it as a spellcaster."""
    sp = rpg.Spell()
    sp.name = "Firebolt"
    engine.set_agent_spells(bm, idx, [sp])


# ── Step 1 flag round-trip (sanity) ─────────────────────────────────────────────
def test_flags_round_trip():
    """The per-agent automation flags set/get through the BattleMap accessors."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))

    assert not bm.is_agent_npc_automated(idx), "agents default to NOT automated"
    assert bm.get_agent_npc_automation_difficulty(idx) == 0
    assert bm.get_agent_npc_automation_strategy(idx) == rpg.NpcAutomationStrategy.Simple

    bm.set_agent_npc_automated(idx, True)
    bm.set_agent_npc_automation_difficulty(idx, 4)
    bm.set_agent_npc_automation_strategy(idx, rpg.NpcAutomationStrategy.PreferRange)
    assert bm.is_agent_npc_automated(idx)
    assert bm.get_agent_npc_automation_difficulty(idx) == 4
    assert bm.get_agent_npc_automation_strategy(idx) == rpg.NpcAutomationStrategy.PreferRange
    print("✅ test_flags_round_trip passed")


# ── Step 2c: resolveStrategy seam ───────────────────────────────────────────────
def test_resolve_strategy_returns_agent_field():
    """Today resolve_strategy returns the per-agent strategy unchanged (the difficulty override layers
    on top later). It is the single seam run_npc_turn dispatches through."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    for strat in (rpg.NpcAutomationStrategy.Simple,
                  rpg.NpcAutomationStrategy.PreferTargetCaster,
                  rpg.NpcAutomationStrategy.PreferAOE,
                  rpg.NpcAutomationStrategy.PreferRange,
                  rpg.NpcAutomationStrategy.PreferHide):
        bm.set_agent_npc_automation_strategy(idx, strat)
        assert engine.resolve_strategy(bm, idx) == strat
    print("✅ test_resolve_strategy_returns_agent_field passed")


def test_run_npc_turn_bad_index_is_safe():
    """run_npc_turn on an out-of-range index Completes without crashing (bounds-checked)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    assert engine.run_npc_turn(bm, -1) == rpg.FlowStatus.Completed
    assert engine.run_npc_turn(bm, 999) == rpg.FlowStatus.Completed
    print("✅ test_run_npc_turn_bad_index_is_safe passed")


# ── Step 3: Simple (preferMelee) ────────────────────────────────────────────────
def test_simple_no_target_passes():
    """A lone automated NPC with no enemies on the field passes: Completes, no parked window, no
    movement, no Dash, and the render-attack hook never fires."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    _automate(bm, npc)
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))

    engine.begin_turn(bm, npc)
    origin_before = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active, "nothing attempted → no parked reaction window"
    assert calls == [], "no target → no attack"
    assert not _cond(engine, bm, npc).dashing, "no target in this map is empty → no need to Dash"
    after = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    assert after == origin_before, "with no target the NPC should not move"
    print("✅ test_simple_no_target_passes passed")


def test_simple_engages_and_attacks():
    """An automated melee NPC two cells from an enemy moves into melee reach and attacks it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    assert _fp_dist(bm, npc, foe) == 2, "NPC starts out of melee reach"

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active
    assert _fp_dist(bm, npc, foe) == 1, "NPC should have moved into melee reach"
    assert (npc, foe) in calls, "NPC should have attacked the foe (render hook fired)"
    print("✅ test_simple_engages_and_attacks passed")


def test_simple_makes_full_multiattack():
    """A Simple turn makes the agent's full Attack action: num_attacks swings against the same target
    (the per-attack loop honoring Extra Attack / multiattack)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Ogre", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=60)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    s = engine.get_agent_stats(bm, npc); s.num_attacks = 2; engine.set_agent_stats(bm, npc, s)
    _automate(bm, npc)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    assert _fp_dist(bm, npc, foe) == 1, "already adjacent — no move needed"

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert calls == [(npc, foe), (npc, foe)], f"expected 2 swings vs the foe, got {calls}"
    print("✅ test_simple_makes_full_multiattack passed")


def test_simple_dashes_when_unreachable():
    """When no enemy is reachable to strike this turn, a Simple NPC Dashes and advances toward the
    nearest enemy without attacking."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 1, 1))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 11, 11), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    # Short legs so even a Dash (2× speed) cannot close the gap → a genuine advance, no attack.
    s = engine.get_agent_stats(bm, npc); s.speed_walk = 10; engine.set_agent_stats(bm, npc, s)
    _automate(bm, npc)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    dist_before = _fp_dist(bm, npc, foe)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert calls == [], "out of reach even after Dash → no attack"
    assert _cond(engine, bm, npc).dashing, "an unreachable enemy should trigger Dash"
    assert _fp_dist(bm, npc, foe) < dist_before, "the NPC should have advanced toward the enemy"
    print("✅ test_simple_dashes_when_unreachable passed")


def test_simple_ignores_allies():
    """Target selection is faction-aware: a same-faction ally is never chosen as the target, so a lone
    automated NPC standing next to an ally just passes."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc  = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Goblin2", 6, 5))
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(ally, 1)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert calls == [], "an ally must never be attacked"
    print("✅ test_simple_ignores_allies passed")


# ── Step 4: PreferTargetCaster ──────────────────────────────────────────────────
def test_prefer_caster_bypasses_closer_noncaster():
    """A PreferTargetCaster NPC walks PAST an adjacent non-caster to engage a farther enemy spellcaster:
    target selection prioritises casters even when a non-caster is closer."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc      = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    grunt    = add_agent_to_battle(engine, bm, create_test_agent("Grunt", 6, 5), hp=30)   # dist 1 (closer)
    caster   = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 7),  hp=30)   # dist 2 (farther)
    for a, f in ((npc, 1), (grunt, 2), (caster, 2)):
        bm.set_agent_faction(a, f)
    _arm_melee(engine, bm, npc)
    _make_caster(engine, bm, caster)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferTargetCaster)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    assert _fp_dist(bm, npc, grunt) == 1 and _fp_dist(bm, npc, caster) == 2

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, caster) in calls, "should attack the spellcaster"
    assert (npc, grunt) not in calls, "should NOT attack the closer non-caster"
    assert _fp_dist(bm, npc, caster) == 1, "should have moved into reach of the caster"
    print("✅ test_prefer_caster_bypasses_closer_noncaster passed")


def test_prefer_caster_falls_back_to_nearest():
    """With no enemy spellcaster on the field, PreferTargetCaster falls back to Simple: attack the
    nearest enemy."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc  = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    near = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)   # dist 1
    far  = add_agent_to_battle(engine, bm, create_test_agent("Bard", 9, 5), hp=30)   # dist 4
    for a, f in ((npc, 1), (near, 2), (far, 2)):
        bm.set_agent_faction(a, f)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferTargetCaster)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, near) in calls, "no caster present → fall back to attacking the nearest enemy"
    assert (npc, far) not in calls
    print("✅ test_prefer_caster_falls_back_to_nearest passed")


# ── Step 5: PreferRange ──────────────────────────────────────────────────────────
def test_range_attacks_without_closing():
    """A PreferRange NPC with a bow, already in weapon range of its target, attacks from distance and
    does NOT close to melee — it kites (keeps at least its starting distance)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 8), hp=30)   # 3 cells away, in range
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_ranged(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferRange)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    dist_before = _fp_dist(bm, npc, foe)
    assert dist_before == 3

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "ranged NPC should attack from distance"
    assert _fp_dist(bm, npc, foe) >= dist_before, "kiter must not close the gap (stays at/extends range)"
    print("✅ test_range_attacks_without_closing passed")


def test_range_focus_fires_lowest_hp():
    """PreferRange targets the lowest-current-HP enemy, not the nearest: with a closer healthy foe and a
    farther wounded foe both in range, it shoots the wounded one."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    # Keep both enemies out of melee adjacency so the archer's kite never provokes an OA (which would park
    # the flow waiting on a human reaction and never Complete in this headless test).
    npc     = add_agent_to_battle(engine, bm, create_test_agent("Archer", 5, 5))
    tank    = add_agent_to_battle(engine, bm, create_test_agent("Tank", 5, 7),  hp=60)   # closer, healthy
    wounded = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 9),  hp=20)   # farther, low HP
    for a, f in ((npc, 1), (tank, 2), (wounded, 2)):
        bm.set_agent_faction(a, f)
    _arm_ranged(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferRange)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, wounded) in calls, "should focus-fire the lowest-HP enemy"
    assert (npc, tank) not in calls, "should NOT shoot the closer healthy enemy"
    print("✅ test_range_focus_fires_lowest_hp passed")


def test_range_falls_back_to_melee_when_no_bow():
    """PreferRange on a creature with no ranged weapon still acts: it falls back to its melee weapon,
    engages, and attacks (a ranged-less brute is not paralysed by the strategy)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Brute", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferRange)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "no ranged weapon → fall back to melee and still attack"
    print("✅ test_range_falls_back_to_melee_when_no_bow passed")


# ── Step 6: PreferAOE ────────────────────────────────────────────────────────
def _aoe_cantrip(radius_ft=5, range_ft=60):
    """A Sphere Harm cantrip with Automatic (no-roll) damage, so an AoE cast deterministically damages
    every enemy in its area. Level 0 → always castable (no slot/use bookkeeping needed for the test)."""
    s = rpg.Spell()
    s.name = "Test Blast"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Sphere
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = range_ft
    s.radius = radius_ft
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 2
    roll.die_size = 6
    s.magic_damage_rolls = [roll]
    return s


def _hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def test_aoe_blasts_enemy_cluster():
    """A PreferAOE NPC casts its area spell on the cluster that catches the most enemies — here two
    adjacent foes both take damage from one Sphere."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    a   = add_agent_to_battle(engine, bm, create_test_agent("FoeA", 6, 5), hp=30)
    b   = add_agent_to_battle(engine, bm, create_test_agent("FoeB", 6, 6), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(b, 2)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    calls = []
    engine.set_render_attack_hook(lambda at, t: calls.append((at, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active
    assert _hp(engine, bm, a) < 30, "FoeA should be caught in the blast"
    assert _hp(engine, bm, b) < 30, "FoeB should be caught in the blast"
    assert calls, "the AoE cast should fire the render hook"
    print("✅ test_aoe_blasts_enemy_cluster passed")


def test_aoe_avoids_friendly_fire():
    """The aim that maximizes NET enemies is chosen: a lone enemy (net +1) is preferred over a cluster of
    one enemy beside an ally (net 0), so the ally is never blasted."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc  = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    lone = add_agent_to_battle(engine, bm, create_test_agent("Lone", 9, 2), hp=30)
    foe  = add_agent_to_battle(engine, bm, create_test_agent("Foe",  5, 8), hp=30)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 9), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(lone, 2)
    bm.set_agent_faction(foe, 2)
    bm.set_agent_faction(ally, 1)            # same team as the caster
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, lone) < 30, "the lone enemy (net +1) should be the chosen target"
    assert _hp(engine, bm, foe)  == 30, "the clustered enemy was NOT blasted (net 0 aim avoided)"
    assert _hp(engine, bm, ally) == 30, "the ally must never be caught in friendly fire"
    print("✅ test_aoe_avoids_friendly_fire passed")


def test_aoe_moves_into_range_before_meleeing():
    """A PreferAOE NPC with a short-range blast and a melee weapon MUST prioritise the AoE: when the enemy
    starts out of the spell's range, it walks into range and casts — it does NOT fall back to a melee swing
    just because it has one. (Fall back to melee only when NO castable AoE spell exists.)"""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 9), hp=30)  # 4 cells = 20ft away
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)                           # HAS a melee weapon …
    engine.set_agent_spells(bm, npc, [_aoe_cantrip(range_ft=5)])  # … but a 5ft-range AoE (enemy out of range)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    calls = []
    engine.set_render_attack_hook(lambda at, t: calls.append((at, t)))
    engine.begin_turn(bm, npc)
    start = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    status = engine.run_npc_turn(bm, npc)
    end = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)

    assert status == rpg.FlowStatus.Completed
    assert end != start, "the AoE caster should move to bring the enemy into range"
    assert _hp(engine, bm, foe) < 30, "after closing distance it casts the AoE (not a melee attack)"
    print("✅ test_aoe_moves_into_range_before_meleeing passed")


def test_aoe_falls_back_to_weapon_without_aoe_spell():
    """A PreferAOE NPC with no area spell is not idle: it falls back to a Simple weapon turn — engage the
    nearest enemy and attack."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Brute", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)              # melee weapon, NO spells
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    calls = []
    engine.set_render_attack_hook(lambda at, t: calls.append((at, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "no AoE spell → fall back to a weapon attack"
    print("✅ test_aoe_falls_back_to_weapon_without_aoe_spell passed")


# ── Bucket D: rechargeable features (breath weapons) ─────────────────────────
# A monster with an AVAILABLE recharge AoE feature spends it as often as it recharges, whatever its base
# strategy — runNpcTurn routes through the AoE executor. An expended breath is not "available", so a
# monster on cooldown falls through to its normal (weapon) turn. Determinism: recharge_min=99 can never be
# met by a d6 (stays expended); a spell built with expended=True starts on cooldown.
def _recharge_breath(radius_ft=5, range_ft=60, recharge_min=5, expended=False):
    """A level-0 Sphere Harm breath weapon modelled exactly like the derived catalog spells: uses_max=1 +
    a recharge threshold. Automatic damage so a cast deterministically damages every enemy in the area."""
    s = _aoe_cantrip(radius_ft=radius_ft, range_ft=range_ft)
    s.name = "Fire Breath"
    s.uses_max = 1
    s.uses_remaining = 0 if expended else 1
    s.recharge_min = recharge_min
    s.expended = expended
    return s


def _make_npc(engine, bm, idx):
    """Flag an agent is_npc so the NPC uses/recharge gate in available_castable_spells applies."""
    cs = engine.get_agent_stats(bm, idx)
    cs.is_npc = True
    engine.set_agent_stats(bm, idx, cs)


def test_recharge_breath_gating_respects_expended():
    """The C++ gate fix: a level-0 NPC breath is NOT an at-will cantrip. It is offered while it has a use
    and is not expended, and withheld once expended (previously level-0 bypassed the uses/recharge check)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 5, 5))
    _make_npc(engine, bm, npc)

    engine.set_agent_spells(bm, npc, [_recharge_breath()])
    assert 0 in engine.available_castable_spells(bm, npc), "an available breath must be castable"

    engine.set_agent_spells(bm, npc, [_recharge_breath(expended=True)])
    assert engine.available_castable_spells(bm, npc) == [], "an expended breath must NOT be castable"
    print("✅ test_recharge_breath_gating_respects_expended passed")


def test_recharge_breath_used_regardless_of_strategy():
    """A Simple (preferMelee) dragon with an available recharge breath uses it anyway — Bucket D routes any
    strategy through the AoE executor when a recharge AoE is up, catching the whole cluster."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 1, 1))
    a   = add_agent_to_battle(engine, bm, create_test_agent("FoeA", 6, 5), hp=30)
    b   = add_agent_to_battle(engine, bm, create_test_agent("FoeB", 6, 6), hp=30)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(a, 2); bm.set_agent_faction(b, 2)
    _make_npc(engine, bm, npc)
    _arm_melee(engine, bm, npc)                                    # HAS a melee option …
    engine.set_agent_spells(bm, npc, [_recharge_breath()])         # … but breathes instead
    _automate(bm, npc, rpg.NpcAutomationStrategy.Simple)           # NOT PreferAOE

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, a) < 30 and _hp(engine, bm, b) < 30, "both foes caught by the breath"
    assert engine.get_agent_spells(bm, npc)[0].expended, "the breath is spent (expended) after use"
    print("✅ test_recharge_breath_used_regardless_of_strategy passed")


def test_recharge_breath_on_cooldown_falls_back_to_weapon():
    """When the breath is expended (on cooldown), a Simple dragon does NOT try to re-cast it — it falls
    through to a normal weapon turn and bites the adjacent foe."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    _make_npc(engine, bm, npc)
    _arm_melee(engine, bm, npc)
    # recharge_min=99 can never be met by a begin_turn d6, so the expended breath stays on cooldown.
    engine.set_agent_spells(bm, npc, [_recharge_breath(recharge_min=99, expended=True)])
    _automate(bm, npc, rpg.NpcAutomationStrategy.Simple)

    calls = []
    engine.set_render_attack_hook(lambda at, t: calls.append((at, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    # An expended breath is not castable at all (see the gating test), so the ONLY way the foe can be
    # attacked is the weapon fallback — the render hook firing a swing at it proves the Simple weapon turn
    # ran instead of a breath. (HP isn't asserted: the attack roll may miss on the seeded RNG, exactly as
    # the other Simple-turn tests only check the render hook.)
    assert (npc, foe) in calls, "breath on cooldown → fall back to a weapon attack"
    assert engine.get_agent_spells(bm, npc)[0].expended, "the breath stays expended (was never re-cast)"
    print("✅ test_recharge_breath_on_cooldown_falls_back_to_weapon passed")


# ── Step 7: PreferHide ───────────────────────────────────────────────────────
def test_hide_focus_fires_lowest_hp():
    """CP0 — PreferHide is (for now) a non-kiting focused ranged attacker: with a closer healthy foe and a
    farther wounded foe both in range, it shoots the wounded one and ends its turn. (The Conceal tail is a
    no-op at CP0, so this mirrors PreferRange's focus-fire minus the kite.)"""
    bm = setup_battle_map(); engine = setup_combat_engine()
    # Keep both enemies out of melee adjacency so the shot never provokes an OA (which would park the flow
    # waiting on a human reaction and never Complete in this headless test).
    npc     = add_agent_to_battle(engine, bm, create_test_agent("Sniper", 5, 5))
    tank    = add_agent_to_battle(engine, bm, create_test_agent("Tank", 5, 7),  hp=60)   # closer, healthy
    wounded = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 9),  hp=20)   # farther, low HP
    for a, f in ((npc, 1), (tank, 2), (wounded, 2)):
        bm.set_agent_faction(a, f)
    _arm_ranged(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, wounded) in calls, "should focus-fire the lowest-HP enemy"
    assert (npc, tank) not in calls, "should NOT shoot the closer healthy enemy"
    print("✅ test_hide_focus_fires_lowest_hp passed")


# ── Step 7 CP1: conceal pure helpers (cover finder + invis-spell finder) ─────────
def _invis_spell(name, casting_time, condition_name, level=0):
    """A self-Invisibility spell as the finder recognises it: a Help buff whose condition list carries
    the Invisible / GreaterInvisible condition. Level 0 keeps it castable without slot bookkeeping."""
    sp = rpg.Spell()
    sp.name = name
    sp.type = rpg.SpellType.Help
    sp.casting_time = casting_time
    sp.level = level
    ac = rpg.AttackCondition()
    ac.condition_name = condition_name
    sp.conditions = [ac]
    return sp


def test_hide_cover_cell_found():
    """CP1 — npc_find_cover_cell returns a reachable cell with no enemy LoS when a wall casts a shadow the
    NPC can step into, and None when it is fully exposed on open ground."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Sniper", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Watcher", 1, 5))
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    # Seed the walk budget the finder reads (headless: no GUI _reset_movement seeds it).
    bm.placed_agents[npc].init_movement(30)   # 6 cells

    npc_o = bm.placed_agents[npc].origin
    enemy_o = bm.placed_agents[enemy].origin

    # Wall one cell EAST of the sniper, in line with the watcher → the cells directly behind it (still
    # reachable by going around) fall in the watcher's shadow. The sniper's own cell stays exposed.
    bm.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Wall)
    assert bm.has_line_of_sight(enemy_o, 1, npc_o, 1), "sniper's current cell should be exposed"

    cover = engine.npc_find_cover_cell(bm, npc)
    assert cover is not None, "a no-LoS cover cell should be reachable behind the wall"
    assert not bm.has_line_of_sight(cover, 1, enemy_o, 1), "the chosen cover cell must have no enemy LoS"

    # Fully exposed: remove the wall → every reachable cell is in the open → no cover.
    bm.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Standard)
    assert engine.npc_find_cover_cell(bm, npc) is None, "open ground offers no cover"
    print("✅ test_hide_cover_cell_found passed")


def test_hide_invis_finder():
    """CP1 — npc_find_self_invis_spell matches by casting time, and prefers Greater Invisibility."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    action_invis = _invis_spell("Invisibility", rpg.CastingTime.Action, "Invisible")
    engine.set_agent_spells(bm, idx, [action_invis])
    assert engine.npc_find_self_invis_spell(bm, idx, rpg.CastingTime.Action) == 0
    assert engine.npc_find_self_invis_spell(bm, idx, rpg.CastingTime.BonusAction) == -1, \
        "an Action-cast invis must not satisfy a BonusAction query"

    # A bonus-action copy → the BonusAction query now hits it.
    bonus_invis = _invis_spell("Invisibility (Swift)", rpg.CastingTime.BonusAction, "Invisible")
    engine.set_agent_spells(bm, idx, [action_invis, bonus_invis])
    assert engine.npc_find_self_invis_spell(bm, idx, rpg.CastingTime.BonusAction) == 1

    # Greater Invisibility present → preferred among the Action-cast matches over plain Invisibility.
    greater = _invis_spell("Greater Invisibility", rpg.CastingTime.Action, "GreaterInvisible")
    engine.set_agent_spells(bm, idx, [action_invis, bonus_invis, greater])
    assert engine.npc_find_self_invis_spell(bm, idx, rpg.CastingTime.Action) == 2, \
        "the finder should prefer Greater Invisibility"
    print("✅ test_hide_invis_finder passed")


# ── Step 7 CP2: Route B (cunning-action cover Hide) ──────────────────────────────
def _grant_cunning_action(engine, bm, idx):
    """Flag the agent as having Cunning Action (the bonus-action Hide that route B leans on)."""
    s = engine.get_agent_stats(bm, idx)
    s.has_cunning_action = True
    engine.set_agent_stats(bm, idx, s)


def _wall_cover_setup():
    """A PreferHide sniper at (5,5) with a Cunning Action, a west-side enemy at (1,5), and a wall at (6,5).
    The sniper's own cell is exposed (it can shoot), but the cells east of the wall sit in the enemy's
    shadow — reachable no-LoS cover to retreat into. Mirrors the proven geometry of test_hide_cover_cell_found."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Guard", 1, 5), hp=60)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    _arm_ranged(engine, bm, npc)
    _grant_cunning_action(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    bm.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Wall)
    return bm, engine, npc, enemy


def test_hide_route_b_attacks_then_hides():
    """CP2 — a Cunning-Action ranged NPC with reachable cover shoots the enemy, retreats behind the wall,
    and bonus-action Hides, ending its turn Hidden."""
    bm, engine, npc, enemy = _wall_cover_setup()

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, enemy) in calls, "route B still spends its Action attacking"
    assert _cond(engine, bm, npc).hidden, "route B ends its turn Hidden behind cover"
    print("✅ test_hide_route_b_attacks_then_hides passed")


def test_hide_route_b_advantage_when_prehidden():
    """CP2 — entering the turn already Hidden, the route-B attack rolls with advantage (the swing reveals
    the attacker), then it re-hides behind cover for next round."""
    bm, engine, npc, enemy = _wall_cover_setup()

    c = engine.get_agent_conditions(bm, npc)
    c.hidden = True
    engine.set_agent_conditions(bm, npc, c)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert engine.last_attack_result().advantage, "a pre-hidden attacker's shot should roll with advantage"
    assert _cond(engine, bm, npc).hidden, "route B re-hides after revealing itself with the attack"
    print("✅ test_hide_route_b_advantage_when_prehidden passed")


def test_hide_route_b_no_cover_ends_exposed():
    """CP2 — a Cunning-Action ranged NPC with NO reachable no-LoS cell attacks and ends its turn NOT
    hidden, with its bonus action still unspent (it re-tries the hide next round). No crash."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Guard", 1, 5), hp=60)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    _arm_ranged(engine, bm, npc)
    _grant_cunning_action(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    # No wall anywhere → open ground → every reachable cell keeps the enemy's line of sight → no cover.

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, enemy) in calls, "still attacks even with nowhere to hide"
    assert not _cond(engine, bm, npc).hidden, "exposed on open ground → not hidden"
    assert engine.has_bonus_action(bm, npc), "no hide attempted → bonus action left unspent"
    print("✅ test_hide_route_b_no_cover_ends_exposed passed")


# ── Step 7 CP3: Route C (action-cast Invisibility, alternating) ──────────────────
def test_hide_route_c_alternates():
    """CP3 — Route C: an NPC that knows self-Invisibility as an ACTION cast but has NO Cunning Action
    alternates cast/attack across rounds. Turn 1 (visible) casts Invisibility and makes NO attack (the
    target takes no damage), ending Invisible. Turn 2 (still Invisible at start) attacks WITH advantage,
    revealing itself."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Assassin", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Guard", 3, 5), hp=60)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    _arm_ranged(engine, bm, npc)

    # An ACTION-cast self-Invisibility, no Cunning Action → npcClassifyConceal returns Route C. attack_type
    # Automatic makes the Help buff auto-apply to the caster (no attack roll / save gate), like real Invisibility.
    invis = _invis_spell("Invisibility", rpg.CastingTime.Action, "Invisible")
    invis.attack_type = rpg.SpellAttack.Automatic
    engine.set_agent_spells(bm, npc, [invis])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    assert engine.npc_classify_conceal(bm, npc) == rpg.NpcConcealRoute.RouteC

    hp0 = engine.get_agent_stats(bm, enemy).hp_cur

    # Turn 1 — visible: cast Invisibility instead of attacking.
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    assert (npc, enemy) not in calls, "route C turn 1 casts instead of attacking — no swing"
    assert engine.get_agent_stats(bm, enemy).hp_cur == hp0, "no attack → target unharmed on the cast round"
    assert _cond(engine, bm, npc).invisible, "route C turn 1 ends Invisible"

    # Turn 2 — still Invisible at start: attack with advantage, revealing.
    calls.clear()
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    assert (npc, enemy) in calls, "route C turn 2 spends its Action attacking"
    assert engine.last_attack_result().advantage, "attacking from Invisibility rolls with advantage"
    assert not _cond(engine, bm, npc).invisible, "the attack reveals the attacker (Invisibility ends)"
    print("✅ test_hide_route_c_alternates passed")


# ── Step 7 CP4: Route A (bonus-action Invisibility after a full-damage attack) ────
def _arm_ranged_sure_hit(engine, bm, idx, range_ft=80):
    """A ranged weapon with a huge to-hit bonus so the shot lands on the seeded RNG (target AC 10),
    letting Route A's 'attack deals damage' be asserted deterministically."""
    w = rpg.Weapon()
    w.name = "Shortbow"
    w.type = rpg.WeaponType.Ranged
    w.normal_range_ft = range_ft
    # rollDamage reads physical_damage_types (not the legacy damage_dice fields), so build an explicit roll.
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    w.bonus_hit = 20          # AC 10 enemy → never misses (short of a natural 1)
    engine.set_agent_weapons(bm, idx, [w, rpg.Weapon(), rpg.Weapon()])


def test_hide_route_a_attack_and_bonus_invis():
    """CP4 — Route A: an NPC with a BONUS-ACTION self-Invisibility spell attacks with its Action (target
    takes damage) AND bonus-casts Invisibility in the same turn, ending Invisible."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Fey Scout", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Guard", 3, 5), hp=60)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    _arm_ranged_sure_hit(engine, bm, npc)

    # A BONUS-ACTION self-Invisibility, auto-applied to the caster → npcClassifyConceal returns Route A.
    invis = _invis_spell("Invisibility (Swift)", rpg.CastingTime.BonusAction, "Invisible")
    invis.attack_type = rpg.SpellAttack.Automatic
    engine.set_agent_spells(bm, npc, [invis])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    assert engine.npc_classify_conceal(bm, npc) == rpg.NpcConcealRoute.RouteA

    hp0 = engine.get_agent_stats(bm, enemy).hp_cur

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed

    assert (npc, enemy) in calls, "route A spends its Action attacking (full damage)"
    assert engine.get_agent_stats(bm, enemy).hp_cur < hp0, "the attack should deal damage"
    assert _cond(engine, bm, npc).invisible, "route A bonus-casts Invisibility, ending the turn Invisible"
    print("✅ test_hide_route_a_attack_and_bonus_invis passed")


def test_hide_route_a_beats_route_b():
    """CP4 — when an NPC has BOTH a BonusAction invis spell AND a Cunning Action, Route A outranks Route B:
    it ends Invisible (spell), not merely Hidden."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc   = add_agent_to_battle(engine, bm, create_test_agent("Fey Rogue", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Guard", 1, 5), hp=60)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(enemy, 2)
    _arm_ranged_sure_hit(engine, bm, npc)
    _grant_cunning_action(engine, bm, npc)
    # Cover is available too (Route B could fire) — Route A must still win.
    bm.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Wall)

    invis = _invis_spell("Invisibility (Swift)", rpg.CastingTime.BonusAction, "Invisible")
    invis.attack_type = rpg.SpellAttack.Automatic
    engine.set_agent_spells(bm, npc, [invis])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    assert engine.npc_classify_conceal(bm, npc) == rpg.NpcConcealRoute.RouteA, \
        "a BonusAction invis spell must outrank Cunning-Action Hide"

    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    assert _cond(engine, bm, npc).invisible, "route A ends Invisible (the spell), not merely Hidden"
    print("✅ test_hide_route_a_beats_route_b passed")


# ── Step 7 CP5: no-target ambush + Route D (plain kite fallback) ─────────────────
def test_hide_no_target_ambush():
    """CP5 — a lone PreferHide NPC with no attackable target does not idle: it Hides as an Action (moving to
    cover first if any is reachable) and ends its turn Hidden, making no attack."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Scout", 5, 5))
    bm.set_agent_faction(npc, 1)
    _arm_ranged(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert calls == [], "no target → no attack in a pure ambush"
    assert _cond(engine, bm, npc).hidden, "the ambusher ends its turn Hidden"

    # Already concealed with still no target → hold, stay Hidden, no crash.
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    assert _cond(engine, bm, npc).hidden, "already hidden with no target → holds in concealment"
    print("✅ test_hide_no_target_ambush passed")


def test_hide_route_d_falls_back_to_kite():
    """CP5 — Route D: a PreferHide NPC with NO Cunning Action and NO invis spell has no way to conceal, so it
    falls back to a plain PreferRange kite — it attacks from range without closing the gap and does not hide."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Slinger", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 8), hp=30)   # 3 cells away, in range
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    _arm_ranged(engine, bm, npc)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferHide)
    assert engine.npc_classify_conceal(bm, npc) == rpg.NpcConcealRoute.RouteD, \
        "no cunning action + no invis spell → Route D"

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    dist_before = _fp_dist(bm, npc, foe)
    assert dist_before == 3
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "Route D still attacks from range"
    assert _fp_dist(bm, npc, foe) >= dist_before, "Route D kites like PreferRange (does not close the gap)"
    assert not _cond(engine, bm, npc).hidden, "Route D has no stealth tools → does not end Hidden"
    print("✅ test_hide_route_d_falls_back_to_kite passed")


def run_all():
    test_flags_round_trip()
    test_resolve_strategy_returns_agent_field()
    test_run_npc_turn_bad_index_is_safe()
    test_simple_no_target_passes()
    test_simple_engages_and_attacks()
    test_simple_makes_full_multiattack()
    test_simple_dashes_when_unreachable()
    test_simple_ignores_allies()
    test_prefer_caster_bypasses_closer_noncaster()
    test_prefer_caster_falls_back_to_nearest()
    test_range_attacks_without_closing()
    test_range_focus_fires_lowest_hp()
    test_range_falls_back_to_melee_when_no_bow()
    test_aoe_blasts_enemy_cluster()
    test_aoe_avoids_friendly_fire()
    test_aoe_moves_into_range_before_meleeing()
    test_aoe_falls_back_to_weapon_without_aoe_spell()
    test_recharge_breath_gating_respects_expended()
    test_recharge_breath_used_regardless_of_strategy()
    test_recharge_breath_on_cooldown_falls_back_to_weapon()
    test_hide_focus_fires_lowest_hp()
    test_hide_cover_cell_found()
    test_hide_invis_finder()
    test_hide_route_b_attacks_then_hides()
    test_hide_route_b_advantage_when_prehidden()
    test_hide_route_b_no_cover_ends_exposed()
    test_hide_route_c_alternates()
    test_hide_route_a_attack_and_bonus_invis()
    test_hide_route_a_beats_route_b()
    test_hide_no_target_ambush()
    test_hide_route_d_falls_back_to_kite()
    print("\nAll NPC automation (Steps 1–7 + Bucket D) tests passed ✅")


if __name__ == "__main__":
    run_all()
