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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

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


def _rect_blast(width_ft=5, length_ft=30, range_ft=120):
    """A damaging Rectangle Harm spell (mini Wall of Fire). NPC casts aim it with the single-point form,
    which resolveAoeTargets evaluates as a width×length box centered on the aim."""
    s = rpg.Spell()
    s.name = "Test Wall"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Rectangle
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = range_ft
    s.width = width_ft
    s.length = length_ft
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 2
    roll.die_size = 6
    s.magic_damage_rolls = [roll]
    return s


def test_aoe_includes_damaging_rectangle():
    """ALL damaging area geometries are AoE blasts (not just Sphere/Cone/Line/Square): a PreferAOE NPC with
    only a Rectangle wall spell (Wall of Fire-like) casts it onto the enemy line — both foes inside the
    centered box take damage."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Efreeti", 1, 1))
    a   = add_agent_to_battle(engine, bm, create_test_agent("FoeA", 6, 5), hp=30)
    b   = add_agent_to_battle(engine, bm, create_test_agent("FoeB", 6, 7), hp=30)   # 10ft below FoeA
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(b, 2)
    engine.set_agent_spells(bm, npc, [_rect_blast()])   # 5ft × 30ft box → covers both when aimed at either
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, a) < 30, "FoeA should be caught in the rectangle blast"
    assert _hp(engine, bm, b) < 30, "FoeB should be caught in the rectangle blast"
    print("✅ test_aoe_includes_damaging_rectangle passed")


def test_aoe_skips_condition_only_area():
    """An area spell with NO damage (a Hypnotic-Pattern-like Harm Sphere that only imposes a condition) is
    NOT an AoE blast: a PreferAOE NPC skips it (control spells belong to PreferControl's priority list) and
    falls back to a weapon attack instead of wasting the action on a zero-damage 'blast'."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    engine.set_agent_spells(bm, npc,
        [_control_spell("Test Pattern", rpg.SpellGeometry.Sphere, "Incapacitated",
                        radius_ft=10, concentration=False)])   # Harm Sphere, condition only, zero damage
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    calls = []
    engine.set_render_attack_hook(lambda at, t: calls.append((at, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "zero-damage area → weapon fallback, not a blast"
    assert not _cond(engine, bm, foe).incapacitated, "the condition-only area must NOT have been cast"
    print("✅ test_aoe_skips_condition_only_area passed")


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


# ── Command (Flee): a commanded creature runs away and takes no action ───────────
def _command_flee(engine, bm, victim, fear_source):
    """Plant a 1-turn CommandFlee condition on `victim` keyed to `fear_source` (the caster it must flee)."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx       = victim
    c.caster_idx      = fear_source
    c.condition_name  = "CommandFlee"
    c.turns_remaining = 1
    c.save_repeat_turns = -1   # mirror the real Command path (combat_conditions.cpp): without this the
                               # struct default (repeat every turn, DC 0) auto-passes at begin_turn and
                               # strips CommandFlee before run_npc_turn can flee.
    engine.add_agent_condition(bm, c)


def _drive_npc_turn(engine, bm, idx):
    """Run run_npc_turn to a terminal Completed, auto-Skipping any reaction the turn provokes.

    A commanded flee out of an adjacent enemy's reach provokes that enemy's opportunity attack;
    runFleeTurn uses the interactive begin_move (like runWeaponTurn), so it parks at the OA
    checkpoint and returns AwaitingDecision. Mirror the GUI resume: Skip the OA and re-enter
    run_npc_turn, whose flee_move_launched guard then ends the turn (no re-flee)."""
    status = engine.run_npc_turn(bm, idx)
    while status == rpg.FlowStatus.AwaitingDecision:
        resp = rpg.ReactionResponse()
        resp.option = -1                       # Skip the offered reaction
        engine.submit_decision(bm, resp)
        status = engine.run_npc_turn(bm, idx)
    return status


def test_command_flee_runs_away_no_attack():
    """An NPC commanded to Flee spends its whole turn moving AWAY from the fear source and does NOT
    attack, even though it is adjacent to an enemy it could otherwise strike."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)                       # armed + adjacent: would attack if not fleeing
    s = engine.get_agent_stats(bm, npc); s.speed_walk = 30; engine.set_agent_stats(bm, npc, s)
    _automate(bm, npc)
    _command_flee(engine, bm, npc, foe)              # flee from the Hero

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    dist_before = _fp_dist(bm, npc, foe)
    assert dist_before == 1, "fleer starts adjacent to the fear source"

    engine.begin_turn(bm, npc)
    status = _drive_npc_turn(engine, bm, npc)        # resolves the OA the flee-out-of-reach provokes

    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active
    assert _fp_dist(bm, npc, foe) > dist_before, "a commanded creature must move away from the fear source"
    assert calls == [], "Command (Flee) grants no action — the fleer never attacks"
    print("✅ test_command_flee_runs_away_no_attack passed")


def test_command_flee_overrides_strategy():
    """The flee override applies regardless of the NPC's strategy (here a ranged kiter): it runs away
    from the fear source instead of engaging."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 7), hp=30)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    _arm_ranged(engine, bm, npc)
    s = engine.get_agent_stats(bm, npc); s.speed_walk = 30; engine.set_agent_stats(bm, npc, s)
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferRange)
    _command_flee(engine, bm, npc, foe)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    dist_before = _fp_dist(bm, npc, foe)

    engine.begin_turn(bm, npc)
    status = _drive_npc_turn(engine, bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _fp_dist(bm, npc, foe) > dist_before, "flee overrides PreferRange: it retreats from the fear source"
    assert calls == [], "no action on a flee turn"
    print("✅ test_command_flee_overrides_strategy passed")


# ── Steps 8–10 shared foundation — the caster executor ──────────────────────────
# The three caster strategies (PreferControl/Heal/Support) share one executor (runCasterTurn) + one planner
# each. The foundation ships the executor + plumbing with STUB planners (each step fills in its planner), so
# until then a caster-strategy NPC simply falls back to a weapon turn via the shared executor. These tests
# pin the enum round-trip, the resolveStrategy seam, and that fallback wiring.
def test_caster_strategy_flags_round_trip():
    """The three new caster strategies set/get through the accessors and resolve unchanged (Step 8-10
    foundation: enum + binding + resolveStrategy seam)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    for strat in (rpg.NpcAutomationStrategy.PreferControl,
                  rpg.NpcAutomationStrategy.PreferHeal,
                  rpg.NpcAutomationStrategy.PreferSupport):
        bm.set_agent_npc_automation_strategy(idx, strat)
        assert bm.get_agent_npc_automation_strategy(idx) == strat
        assert engine.resolve_strategy(bm, idx) == strat, "resolveStrategy passes caster strategies through"
    print("✅ test_caster_strategy_flags_round_trip passed")


def test_caster_strategies_fall_back_to_weapon():
    """With the foundation's stub planners (spell_idx < 0, no approach target), a Control/Heal/Support NPC is
    never idle: runCasterTurn falls back to the shared weapon turn, so the agent engages and attacks. Proves
    the dispatch + weapon-fallback wiring before any real planner lands."""
    for strat in (rpg.NpcAutomationStrategy.PreferControl,
                  rpg.NpcAutomationStrategy.PreferHeal,
                  rpg.NpcAutomationStrategy.PreferSupport):
        bm = setup_battle_map(); engine = setup_combat_engine()
        npc = add_agent_to_battle(engine, bm, create_test_agent("Acolyte", 5, 5))
        foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
        bm.set_agent_faction(npc, 1)
        bm.set_agent_faction(foe, 2)
        _arm_melee(engine, bm, npc)
        _make_caster(engine, bm, npc)          # a known spell, but no planner yet → stub returns "no cast"
        _automate(bm, npc, strat)

        calls = []
        engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
        engine.begin_turn(bm, npc)
        status = engine.run_npc_turn(bm, npc)

        assert status == rpg.FlowStatus.Completed
        assert (npc, foe) in calls, f"{strat}: stub planner → fall back to a weapon turn and still attack"
    print("✅ test_caster_strategies_fall_back_to_weapon passed")


# ── Step 8: PreferControl ────────────────────────────────────────────────────
def _find_npc_config():
    """The DM config, IF the engine can see it — probing the SAME relative paths npcLoadConfig tries, so
    this test agrees with the loader regardless of the CWD the suite runs from (gui/ finds the file and
    loads the DM-authored values; a build dir doesn't and the baked-in defaults rule)."""
    import json
    for p in ("npc_automation_config.json",
              os.path.join("..", "gui", "npc_automation_config.json"),
              os.path.join("gui", "npc_automation_config.json")):
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return None


def test_control_priority_config_loaded():
    """The config loader (npcLoadConfig) exposes npc_automation_config.json read-only through the bindings.
    When the JSON is visible from the CWD the loaded values must MATCH the file (the DM-authored config
    actually drives the planners); with no file, the baked-in defaults back everything. Pins the config
    contract the PreferControl (Step 8) / PreferHeal (Step 9) planners and the difficulty resolver read."""
    engine = setup_combat_engine()
    priority  = list(engine.npc_control_priority())
    threshold = engine.npc_heal_threshold()
    ignore    = set(engine.npc_classification_ignore())
    assert priority and all(isinstance(nm, str) for nm in priority), "priority list loads non-empty"
    assert 0.0 < threshold <= 1.0, threshold
    assert ignore, "classification ignore list loads non-empty"

    cfg = _find_npc_config()
    if cfg is not None:
        assert priority == cfg["control_priority"], \
            "the loaded priority must be the DM-authored file order, verbatim"
        assert threshold == cfg["heal_threshold_fraction"]
        assert ignore == {nm.lower() for nm in cfg["classification_ignore_spells"]}, \
            "the ignore list loads lowercased from the file"
    else:
        assert priority == ["Hold Monster", "Hold Person", "Hypnotic Pattern",
                            "Slow", "Command", "Tasha's Hideous Laughter"], priority
        assert threshold == 0.5
    # present in BOTH the baked-in defaults and the shipped file — the names other tests rely on
    assert "Hold Person" in priority and "Hypnotic Pattern" in priority
    assert "speak with animals" in ignore
    print("✅ test_control_priority_config_loaded passed")


def _control_spell(name, geometry, condition, range_ft=60, radius_ft=10, concentration=True):
    """A control spell that applies `condition` AUTOMATICALLY (requires_save=False) so a cast lands
    deterministically in-test. Level 0 → always castable (no slot/use bookkeeping). Named exactly so it
    matches an entry in the DM control_priority list the planner walks."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Harm
    s.geometry = geometry
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = range_ft
    s.radius = radius_ft
    s.level = 0
    s.requires_concentration = concentration
    c = rpg.AttackCondition()
    c.condition_name = condition
    c.requires_save = False
    c.condition_duration = 3
    s.conditions = [c]
    return s


def test_control_casts_single_target_on_nearest():
    """A PreferControl NPC casts its single-target control spell (Hold Person) on the nearest enemy, which
    is paralyzed — and the render hook fires toward that target."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 3, 3), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    engine.set_agent_spells(bm, npc, [_control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed")])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _cond(engine, bm, foe).paralyzed, "the single-target control spell should paralyze the enemy"
    assert (npc, foe) in calls, "the control cast should fire the render hook toward the target"
    print("✅ test_control_casts_single_target_on_nearest passed")


def test_control_respects_priority_order():
    """The planner walks control_priority IN ORDER: with both Hold Person (higher) and Slow (lower) castable,
    it casts Hold Person — the enemy is paralyzed, NOT merely slowed."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 3, 3), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    engine.set_agent_spells(bm, npc, [
        _control_spell("Slow",        rpg.SpellGeometry.Single, "Slowed"),      # lower priority
        _control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed"),   # higher priority
    ])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _cond(engine, bm, foe).paralyzed, "the higher-priority Hold Person should be the cast"
    assert not _cond(engine, bm, foe).slowed, "the lower-priority Slow must NOT have been cast"
    print("✅ test_control_respects_priority_order passed")


def test_control_area_targets_cluster():
    """An area control spell (Hypnotic Pattern) lands on the enemy cluster: two adjacent foes are both
    incapacitated by one cast."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    a   = add_agent_to_battle(engine, bm, create_test_agent("FoeA", 6, 5), hp=30)
    b   = add_agent_to_battle(engine, bm, create_test_agent("FoeB", 6, 6), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(b, 2)
    engine.set_agent_spells(bm, npc,
        [_control_spell("Hypnotic Pattern", rpg.SpellGeometry.Sphere, "Incapacitated", radius_ft=10)])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert _cond(engine, bm, a).incapacitated, "FoeA should be caught in the area control"
    assert _cond(engine, bm, b).incapacitated, "FoeB should be caught in the area control"
    print("✅ test_control_area_targets_cluster passed")


def test_control_moves_into_range_before_casting():
    """A PreferControl NPC with a short-range control spell approaches an out-of-range enemy, then casts it
    — it does NOT fall back to a melee swing just because it has one (control is prioritised, like AoE)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 9), hp=30)  # 4 cells = 20ft away
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)                            # HAS a melee weapon …
    engine.set_agent_spells(bm, npc,
        [_control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed", range_ft=5)])  # … 5ft control
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    engine.begin_turn(bm, npc)
    start = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    status = engine.run_npc_turn(bm, npc)
    end = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)

    assert status == rpg.FlowStatus.Completed
    assert end != start, "the control caster should move to bring the enemy into range"
    assert _cond(engine, bm, foe).paralyzed, "after closing distance it casts the control (not a melee attack)"
    print("✅ test_control_moves_into_range_before_casting passed")


def test_control_falls_back_to_weapon_without_control_spell():
    """A PreferControl NPC whose spells are NOT in the control_priority list is not idle: it falls back to a
    Simple weapon turn — engage the nearest enemy and attack."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    engine.set_agent_spells(bm, npc,
        [_control_spell("Firebolt", rpg.SpellGeometry.Single, "Paralyzed")])  # not a control_priority name
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert (npc, foe) in calls, "no control spell → fall back to a weapon attack"
    assert not _cond(engine, bm, foe).paralyzed, "a non-priority spell must not be cast as control"
    print("✅ test_control_falls_back_to_weapon_without_control_spell passed")


def test_control_skips_concentration_spell_when_already_concentrating():
    """The concentration guard: a PreferControl NPC already concentrating on a spell does NOT drop it to
    recast a concentration control spell — it falls back to a weapon turn instead (enemy stays un-paralyzed)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 2, 2), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    engine.set_agent_spells(bm, npc,
        [_control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed", concentration=True)])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferControl)

    engine.begin_turn(bm, npc)
    cond = engine.get_agent_conditions(bm, npc)          # mark the caster as already concentrating
    cond.concentrating = True
    engine.set_agent_conditions(bm, npc, cond)
    status = engine.run_npc_turn(bm, npc)

    assert status == rpg.FlowStatus.Completed
    assert not _cond(engine, bm, foe).paralyzed, "must not drop live concentration to recast a control spell"
    print("✅ test_control_skips_concentration_spell_when_already_concentrating passed")


# ── Step 9: PreferHeal ───────────────────────────────────────────────────────
def _heal_spell(name, geometry=None, num_dice=2, die_size=8, bonus=0, range_ft=60, num_targets=1):
    """An HP-restoring Heal spell. Automatic (no attack roll), level 0 → always castable. healing_type dice
    drive reviveOnHeal so a downed ally is brought back. Multiple geometry (Mass Healing Word) sets
    num_targets so target_indices fills up to N."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Heal
    s.geometry = geometry if geometry is not None else rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = range_ft
    s.level = 0
    s.num_targets = num_targets
    h = rpg.HealingRoll()
    h.num_dice = num_dice
    h.die_size = die_size
    h.bonus = bonus
    s.healing_type = h
    return s


def _set_hp(engine, bm, idx, hp_cur):
    s = engine.get_agent_stats(bm, idx); s.hp_cur = hp_cur; engine.set_agent_stats(bm, idx, s)


def test_heal_targets_most_wounded_ally():
    """A PreferHeal NPC casts a single-target heal on the most-wounded ally (below the 0.5 threshold), not on
    a lightly-scratched one — and the render hook fires toward the healed ally."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    healer = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 1, 1), hp=30)
    hurt   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 2, 2), hp=40)
    fine   = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 3, 3), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 8, 8), hp=30)
    for a in (healer, hurt, fine): bm.set_agent_faction(a, 1)
    bm.set_agent_faction(foe, 2)
    _set_hp(engine, bm, hurt, 8)    # 8/40 = 0.2 → below threshold
    _set_hp(engine, bm, fine, 38)   # 38/40 → healthy, must be skipped
    engine.set_agent_spells(bm, healer, [_heal_spell("Cure Wounds")])
    _automate(bm, healer, rpg.NpcAutomationStrategy.PreferHeal)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, healer)
    status = engine.run_npc_turn(bm, healer)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, hurt) > 8, "the most-wounded ally should be healed"
    assert _hp(engine, bm, fine) == 38, "a healthy ally must NOT be healed"
    assert (healer, hurt) in calls, "the heal cast should fire the render hook toward the healed ally"
    print("✅ test_heal_targets_most_wounded_ally passed")


def test_heal_revives_downed_ally_first():
    """A downed ally (hp 0) outranks a merely-wounded one: the heal lands on the downed ally, reviving it
    (hp back above 0), even though another ally is also below threshold."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    healer = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 1, 1), hp=30)
    downed = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 2, 2), hp=40)
    hurt   = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 3, 3), hp=40)
    for a in (healer, downed, hurt): bm.set_agent_faction(a, 1)
    _set_hp(engine, bm, downed, 0)   # downed → highest priority
    _set_hp(engine, bm, hurt, 10)    # wounded but conscious
    engine.set_agent_spells(bm, healer, [_heal_spell("Healing Word", num_dice=2, die_size=4)])
    _automate(bm, healer, rpg.NpcAutomationStrategy.PreferHeal)

    engine.begin_turn(bm, healer)
    status = engine.run_npc_turn(bm, healer)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, downed) > 0, "the downed ally should be revived by the heal"
    assert _hp(engine, bm, hurt) == 10, "the single-target heal must go to the downed ally, not the wounded one"
    print("✅ test_heal_revives_downed_ally_first passed")


def test_heal_multiple_fills_wounded_allies():
    """A Multiple heal (Mass Healing Word) fills target_indices with several wounded allies — two hurt allies
    are both healed by one cast."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    healer = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 1, 1), hp=30)
    a      = add_agent_to_battle(engine, bm, create_test_agent("AllyA", 2, 2), hp=40)
    b      = add_agent_to_battle(engine, bm, create_test_agent("AllyB", 3, 3), hp=40)
    for x in (healer, a, b): bm.set_agent_faction(x, 1)
    _set_hp(engine, bm, a, 8)
    _set_hp(engine, bm, b, 12)
    engine.set_agent_spells(bm, healer,
        [_heal_spell("Mass Healing Word", geometry=rpg.SpellGeometry.Multiple, num_dice=2, die_size=4,
                     num_targets=6)])
    _automate(bm, healer, rpg.NpcAutomationStrategy.PreferHeal)

    engine.begin_turn(bm, healer)
    status = engine.run_npc_turn(bm, healer)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, a) > 8, "AllyA should be healed by the Multiple heal"
    assert _hp(engine, bm, b) > 12, "AllyB should also be healed by the same cast"
    print("✅ test_heal_multiple_fills_wounded_allies passed")


def test_heal_moves_into_range_before_casting():
    """A PreferHeal NPC with a short-range heal approaches an out-of-range wounded ally, then heals it — it
    does NOT idle or swing a weapon while an ally needs healing (heal is prioritised, like AoE/Control)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    healer = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    hurt   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 9), hp=40)  # 4 cells = 20ft away
    bm.set_agent_faction(healer, 1); bm.set_agent_faction(hurt, 1)
    _arm_melee(engine, bm, healer)                       # HAS a melee weapon …
    _set_hp(engine, bm, hurt, 8)
    engine.set_agent_spells(bm, healer, [_heal_spell("Cure Wounds", range_ft=5)])  # … 5ft heal
    _automate(bm, healer, rpg.NpcAutomationStrategy.PreferHeal)

    engine.begin_turn(bm, healer)
    start = (bm.placed_agents[healer].origin.col, bm.placed_agents[healer].origin.row)
    status = engine.run_npc_turn(bm, healer)
    end = (bm.placed_agents[healer].origin.col, bm.placed_agents[healer].origin.row)

    assert status == rpg.FlowStatus.Completed
    assert end != start, "the healer should move to bring the wounded ally into range"
    assert _hp(engine, bm, hurt) > 8, "after closing distance it heals the ally (not a melee attack)"
    print("✅ test_heal_moves_into_range_before_casting passed")


def test_heal_falls_back_to_weapon_when_allies_healthy():
    """The threshold gate: with every ally healthy (above heal_threshold_fraction), a PreferHeal NPC does NOT
    waste its heal — it falls back to a Simple weapon turn and attacks the nearest enemy."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    healer = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 4, 4), hp=40)  # full HP
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 6, 5), hp=30)
    bm.set_agent_faction(healer, 1); bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, healer)
    engine.set_agent_spells(bm, healer, [_heal_spell("Cure Wounds")])
    _automate(bm, healer, rpg.NpcAutomationStrategy.PreferHeal)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, healer)
    status = engine.run_npc_turn(bm, healer)

    assert status == rpg.FlowStatus.Completed
    assert (healer, foe) in calls, "no ally worth healing → fall back to a weapon attack on the enemy"
    print("✅ test_heal_falls_back_to_weapon_when_allies_healthy passed")


# ── Step 10: PreferSupport ───────────────────────────────────────────────────
def _buff_spell(name="Bless", condition="Blessed", geometry=None, range_ft=60, num_targets=1,
                concentration=False):
    """A Help buff spell that applies `condition` AUTOMATICALLY (requires_save=False). Uses the real
    "Blessed" condition by default so the engine sets Stats.blessed on each target — the test can verify a
    buff actually landed. Level 0 → always castable; duration > 1 so it persists. Multiple geometry
    (num_targets > 1) lets target_indices fill several allies."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Help
    s.geometry = geometry if geometry is not None else rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = range_ft
    s.level = 0
    s.duration = 10
    s.num_targets = num_targets
    s.requires_concentration = concentration
    c = rpg.AttackCondition()
    c.condition_name = condition
    c.requires_save = False
    c.condition_duration = 0   # 0 → inherit the spell's duration
    s.conditions = [c]
    return s


def _plant_buff(engine, bm, ally, condition="Blessed"):
    """Mark `ally` as already carrying `condition` (a live tracked ActiveAgentCondition) so the Support
    planner treats it as already-buffed and skips it. save_repeat_turns = -1 so no begin_turn save strips it."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx        = ally
    c.condition_name   = condition
    c.turns_remaining  = 10
    c.save_repeat_turns = -1
    engine.add_agent_condition(bm, c)


def test_support_buffs_unbuffed_allies():
    """A PreferSupport NPC casts a Help buff on an unbuffed ally (which becomes blessed), firing the render
    hook toward it. The ally sits at a lower index than the caster so — with nobody engaged — it is picked
    ahead of the self-buff."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 6), hp=40)  # index 0
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)   # index 1
    bm.set_agent_faction(ally, 1); bm.set_agent_faction(caster, 1)
    engine.set_agent_spells(bm, caster, [_buff_spell()])
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, caster)
    status = engine.run_npc_turn(bm, caster)

    assert status == rpg.FlowStatus.Completed
    assert engine.get_agent_stats(bm, ally).blessed, "the unbuffed ally should be buffed"
    assert (caster, ally) in calls, "the buff cast should fire the render hook toward the buffed ally"
    print("✅ test_support_buffs_unbuffed_allies passed")


def test_support_skips_already_buffed_ally():
    """The already-buffed check: with one ally already carrying the buff (and the caster self-buffed), the
    Support planner buffs the OTHER, unbuffed ally — never re-buffing the one that already has it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster   = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    buffed   = add_agent_to_battle(engine, bm, create_test_agent("AllyA", 5, 6), hp=40)
    unbuffed = add_agent_to_battle(engine, bm, create_test_agent("AllyB", 5, 7), hp=40)
    for a in (caster, buffed, unbuffed): bm.set_agent_faction(a, 1)
    engine.set_agent_spells(bm, caster, [_buff_spell()])
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, caster)
    _plant_buff(engine, bm, caster)    # caster already blessed itself → excluded from candidates
    _plant_buff(engine, bm, buffed)    # this ally already carries the buff → must be skipped
    status = engine.run_npc_turn(bm, caster)

    assert status == rpg.FlowStatus.Completed
    assert engine.get_agent_stats(bm, unbuffed).blessed, "the unbuffed ally should be buffed"
    assert (caster, unbuffed) in calls and (caster, buffed) not in calls, "must buff only the unbuffed ally"
    print("✅ test_support_skips_already_buffed_ally passed")


def test_support_multiple_fills_allies_preferring_engaged():
    """A Multiple buff fills several allies in one cast, and among candidates it PREFERS allies engaged with
    an enemy: the ally adjacent to a foe is the render representative (front of target_indices), and both
    allies end up buffed."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster  = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    far     = add_agent_to_battle(engine, bm, create_test_agent("AllyFar", 5, 6), hp=40)   # not engaged
    engaged = add_agent_to_battle(engine, bm, create_test_agent("AllyEng", 9, 9), hp=40)   # adjacent to a foe
    foe     = add_agent_to_battle(engine, bm, create_test_agent("Orc", 9, 10), hp=30)
    for a in (caster, far, engaged): bm.set_agent_faction(a, 1)
    bm.set_agent_faction(foe, 2)
    _plant_buff(engine, bm, caster)    # keep the focus on the two allies, not the self-buff
    engine.set_agent_spells(bm, caster,
        [_buff_spell("Bless", geometry=rpg.SpellGeometry.Multiple, num_targets=6, range_ft=120)])
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, caster)
    status = engine.run_npc_turn(bm, caster)

    assert status == rpg.FlowStatus.Completed
    assert engine.get_agent_stats(bm, engaged).blessed, "the engaged ally should be buffed"
    assert engine.get_agent_stats(bm, far).blessed, "the Multiple buff should also fill the other ally"
    assert (caster, engaged) in calls, "the engaged ally is preferred as the cast's representative target"
    print("✅ test_support_multiple_fills_allies_preferring_engaged passed")


def test_support_moves_into_range_before_casting():
    """A PreferSupport NPC with a short-range buff approaches an out-of-range unbuffed ally, then buffs it —
    it does NOT idle or swing a weapon (support is prioritised, like AoE/Control/Heal). The caster is already
    self-buffed so the far ally is the only candidate driving the approach."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 9), hp=40)  # 4 cells = 20ft away
    bm.set_agent_faction(caster, 1); bm.set_agent_faction(ally, 1)
    _arm_melee(engine, bm, caster)                         # HAS a melee weapon …
    engine.set_agent_spells(bm, caster, [_buff_spell(range_ft=5)])  # … 5ft buff
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    engine.begin_turn(bm, caster)
    _plant_buff(engine, bm, caster)    # self already buffed → the far ally is the only candidate
    start = (bm.placed_agents[caster].origin.col, bm.placed_agents[caster].origin.row)
    status = engine.run_npc_turn(bm, caster)
    end = (bm.placed_agents[caster].origin.col, bm.placed_agents[caster].origin.row)

    assert status == rpg.FlowStatus.Completed
    assert end != start, "the caster should move to bring the ally into range"
    assert engine.get_agent_stats(bm, ally).blessed, "after closing distance it buffs the ally (not a melee attack)"
    print("✅ test_support_moves_into_range_before_casting passed")


def test_support_skips_concentration_buff_when_already_concentrating():
    """The concentration guard: a PreferSupport NPC already concentrating does NOT drop it to recast a
    concentration buff — it falls back to a weapon turn and attacks the enemy instead (ally stays unbuffed)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 6), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 6, 5), hp=30)
    bm.set_agent_faction(caster, 1); bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_buff_spell(concentration=True)])
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, caster)
    cond = engine.get_agent_conditions(bm, caster)       # mark the caster as already concentrating
    cond.concentrating = True
    engine.set_agent_conditions(bm, caster, cond)
    status = engine.run_npc_turn(bm, caster)

    assert status == rpg.FlowStatus.Completed
    assert not engine.get_agent_stats(bm, ally).blessed, "must not drop live concentration to recast a buff"
    assert (caster, foe) in calls, "with the buff guarded, fall back to a weapon attack on the enemy"
    print("✅ test_support_skips_concentration_buff_when_already_concentrating passed")


def test_support_falls_back_to_weapon_when_all_buffed():
    """With every ally (and the caster) already buffed, a PreferSupport NPC does NOT waste its cast — it
    falls back to a Simple weapon turn and attacks the nearest enemy."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 6), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 6, 5), hp=30)
    bm.set_agent_faction(caster, 1); bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_buff_spell()])
    _automate(bm, caster, rpg.NpcAutomationStrategy.PreferSupport)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, caster)
    _plant_buff(engine, bm, caster); _plant_buff(engine, bm, ally)   # everyone already buffed
    status = engine.run_npc_turn(bm, caster)

    assert status == rpg.FlowStatus.Completed
    assert (caster, foe) in calls, "nobody left to buff → fall back to a weapon attack on the enemy"
    print("✅ test_support_falls_back_to_weapon_when_all_buffed passed")


# ── Difficulty resolver: level → role → strategy override ────────────────────────
# resolveStrategy incorporates Steps 3-10 into the difficulty levels (NPC_AUTOMATION_PLAN.md
# "Difficulty-level → strategy mapping"): L1 all Simple; L2 splits by role; L3 casters blast; L4 adds the
# specialists (PreferHide for stealthy ranged, dynamic Heal→Control→Support planner-probing for casters);
# L5/6 clamp to L4 until the NN policies exist. Level 0 keeps the per-agent strategy field (all earlier
# tests run at level 0, pinning that the override changes nothing unless a level is dialed).

def _flavor_spell(name="Speak with Animals"):
    """A known spell that is combat-IRRELEVANT (on classification_ignore_spells): it must NOT make its
    owner a caster."""
    s = rpg.Spell()
    s.name = name
    return s


def _set_difficulty(bm, idx, level):
    bm.set_agent_npc_automation_difficulty(idx, level)


def test_role_classification():
    """npcClassifyRole: combat spells ⇒ Caster; else a ranged weapon ⇒ Ranged; else Melee."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    brute  = add_agent_to_battle(engine, bm, create_test_agent("Brute", 1, 1))
    archer = add_agent_to_battle(engine, bm, create_test_agent("Archer", 3, 3))
    mage   = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    _arm_melee(engine, bm, brute)
    _arm_ranged(engine, bm, archer)
    _make_caster(engine, bm, mage)             # knows Firebolt (combat-relevant)
    _arm_melee(engine, bm, mage)               # a caster with a dagger is still a Caster

    assert engine.npc_classify_role(bm, brute)  == rpg.NpcRole.Melee
    assert engine.npc_classify_role(bm, archer) == rpg.NpcRole.Ranged
    assert engine.npc_classify_role(bm, mage)   == rpg.NpcRole.Caster
    print("✅ test_role_classification passed")


def test_classification_ignores_flavor_spells():
    """The Centaur Warden case: an agent whose only spells are flavor/utility (Speak with Animals,
    Thaumaturgy) is NOT a caster — its role falls through to its weapons. One combat spell added to the
    same list flips it back to Caster. The loaded ignore list is queryable (lowercased)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    warden = add_agent_to_battle(engine, bm, create_test_agent("Centaur Warden", 1, 1))
    _arm_melee(engine, bm, warden)
    engine.set_agent_spells(bm, warden, [_flavor_spell("Speak with Animals"),
                                         _flavor_spell("Thaumaturgy")])
    assert engine.npc_classify_role(bm, warden) == rpg.NpcRole.Melee, \
        "flavor-only spell list must not classify as Caster"

    engine.set_agent_spells(bm, warden, [_flavor_spell("Speak with Animals"),
                                         _heal_spell("Cure Wounds")])
    assert engine.npc_classify_role(bm, warden) == rpg.NpcRole.Caster, \
        "one combat-relevant spell among the flavor makes it a Caster"

    ignore = engine.npc_classification_ignore()
    assert "speak with animals" in ignore and "mage armor" in ignore, \
        "the ignore list loads (lowercased) from config/baked-in defaults"
    print("✅ test_classification_ignores_flavor_spells passed")


def test_difficulty_level1_everyone_simple():
    """Level 1 resolves Simple for every role and OVERRIDES the per-agent strategy field."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    brute  = add_agent_to_battle(engine, bm, create_test_agent("Brute", 1, 1))
    archer = add_agent_to_battle(engine, bm, create_test_agent("Archer", 3, 3))
    mage   = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    _arm_melee(engine, bm, brute); _arm_ranged(engine, bm, archer); _make_caster(engine, bm, mage)
    for idx in (brute, archer, mage):
        bm.set_agent_npc_automation_strategy(idx, rpg.NpcAutomationStrategy.PreferAOE)  # must be ignored
        _set_difficulty(bm, idx, 1)
        assert engine.resolve_strategy(bm, idx) == rpg.NpcAutomationStrategy.Simple, \
            "Level 1: everyone Simple, regardless of the per-agent strategy field"
    print("✅ test_difficulty_level1_everyone_simple passed")


def test_difficulty_level2_role_split():
    """Level 2: melee stays Simple; ranged and casters kite (PreferRange)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    brute  = add_agent_to_battle(engine, bm, create_test_agent("Brute", 1, 1))
    archer = add_agent_to_battle(engine, bm, create_test_agent("Archer", 3, 3))
    mage   = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5))
    _arm_melee(engine, bm, brute); _arm_ranged(engine, bm, archer); _make_caster(engine, bm, mage)
    for idx in (brute, archer, mage):
        _set_difficulty(bm, idx, 2)
    assert engine.resolve_strategy(bm, brute)  == rpg.NpcAutomationStrategy.Simple
    assert engine.resolve_strategy(bm, archer) == rpg.NpcAutomationStrategy.PreferRange
    assert engine.resolve_strategy(bm, mage)   == rpg.NpcAutomationStrategy.PreferRange, \
        "a caster with no AoE kites at Level 2"
    print("✅ test_difficulty_level2_role_split passed")


def test_difficulty_level3_caster_blasts():
    """Level 3: a caster holding a castable AoE blast upgrades to PreferAOE (at Level 2 it still kites)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    mage = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    foe  = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 6), hp=30)
    bm.set_agent_faction(mage, 1); bm.set_agent_faction(foe, 2)
    engine.set_agent_spells(bm, mage, [_aoe_cantrip()])

    _set_difficulty(bm, mage, 2)
    assert engine.resolve_strategy(bm, mage) == rpg.NpcAutomationStrategy.PreferRange, \
        "Level 2 casters don't blast yet"
    _set_difficulty(bm, mage, 3)
    assert engine.resolve_strategy(bm, mage) == rpg.NpcAutomationStrategy.PreferAOE, \
        "Level 3 caster with a castable AoE → PreferAOE"

    # Every damaging area geometry counts as an AoE blast — a wall-caster (Rectangle, Wall of Fire-like)
    # resolves PreferAOE too.
    waller = add_agent_to_battle(engine, bm, create_test_agent("Waller", 3, 1))
    bm.set_agent_faction(waller, 1)
    engine.set_agent_spells(bm, waller, [_rect_blast()])
    _set_difficulty(bm, waller, 3)
    assert engine.resolve_strategy(bm, waller) == rpg.NpcAutomationStrategy.PreferAOE, \
        "a damaging Rectangle wall is an AoE blast for the resolver"
    print("✅ test_difficulty_level3_caster_blasts passed")


def test_difficulty_level4_ranged_stealth_hide():
    """Level 4: a ranged agent WITH stealth tools (Cunning Action) becomes the ambusher (PreferHide);
    a plain archer keeps kiting (PreferRange)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    rogue  = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 1, 1))
    archer = add_agent_to_battle(engine, bm, create_test_agent("Archer", 3, 3))
    _arm_ranged(engine, bm, rogue); _arm_ranged(engine, bm, archer)
    s = engine.get_agent_stats(bm, rogue); s.has_cunning_action = True; engine.set_agent_stats(bm, rogue, s)
    _set_difficulty(bm, rogue, 4); _set_difficulty(bm, archer, 4)

    assert engine.resolve_strategy(bm, rogue)  == rpg.NpcAutomationStrategy.PreferHide, \
        "Level 4 ranged + Cunning Action → PreferHide"
    assert engine.resolve_strategy(bm, archer) == rpg.NpcAutomationStrategy.PreferRange, \
        "Level 4 ranged without stealth tools stays PreferRange"
    print("✅ test_difficulty_level4_ranged_stealth_hide passed")


def test_difficulty_level4_caster_dynamic():
    """Level 4 casters resolve DYNAMICALLY by probing the live planners (Heal → Control → Support → AoE):
    the same cleric resolves PreferHeal while an ally is badly hurt, PreferSupport once everyone is healthy
    but unbuffed, and falls through to PreferRange when there is nothing left to cast."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 1, 1), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 2, 2), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 8, 8), hp=30)
    bm.set_agent_faction(cleric, 1); bm.set_agent_faction(ally, 1); bm.set_agent_faction(foe, 2)
    engine.set_agent_spells(bm, cleric, [_heal_spell("Cure Wounds"), _buff_spell("Bless")])
    _set_difficulty(bm, cleric, 4)

    _set_hp(engine, bm, ally, 8)      # 8/40 → below the 0.5 heal threshold
    assert engine.resolve_strategy(bm, cleric) == rpg.NpcAutomationStrategy.PreferHeal, \
        "a badly-hurt ally makes the Heal planner actionable → PreferHeal wins"

    _set_hp(engine, bm, ally, 40)     # everyone healthy → Heal not actionable, Support is (nobody Blessed)
    assert engine.resolve_strategy(bm, cleric) == rpg.NpcAutomationStrategy.PreferSupport, \
        "healthy allies + an unbuffed ally → PreferSupport"

    _plant_buff(engine, bm, ally)     # everyone (incl. the cleric itself) carries the buff → nothing to cast
    _plant_buff(engine, bm, cleric)
    assert engine.resolve_strategy(bm, cleric) == rpg.NpcAutomationStrategy.PreferRange, \
        "nothing to heal/control/support and no AoE → the L3/L2 caster fallback (kite)"
    print("✅ test_difficulty_level4_caster_dynamic passed")


def test_difficulty_level4_heal_outranks_control():
    """The dynamic probe order is Heal → Control: a caster holding BOTH a control spell and a heal resolves
    PreferHeal while an ally is down, and PreferControl once nobody needs healing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    priest = add_agent_to_battle(engine, bm, create_test_agent("Priest", 1, 1), hp=30)
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 2, 2), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 4), hp=30)
    bm.set_agent_faction(priest, 1); bm.set_agent_faction(ally, 1); bm.set_agent_faction(foe, 2)
    engine.set_agent_spells(bm, priest, [
        _heal_spell("Cure Wounds"),
        _control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed"),
    ])
    _set_difficulty(bm, priest, 4)

    _set_hp(engine, bm, ally, 0)      # downed ally
    assert engine.resolve_strategy(bm, priest) == rpg.NpcAutomationStrategy.PreferHeal, \
        "a downed ally outranks the castable control spell"

    _set_hp(engine, bm, ally, 40)
    assert engine.resolve_strategy(bm, priest) == rpg.NpcAutomationStrategy.PreferControl, \
        "nobody to heal → the control spell (on the priority list) resolves PreferControl"
    print("✅ test_difficulty_level4_heal_outranks_control passed")


def test_difficulty_level5_clamps_to_level4():
    """Levels 5/6 (NN policies, Steps 11-13) are not trained yet: they resolve exactly as Level 4."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    rogue = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 1, 1))
    _arm_ranged(engine, bm, rogue)
    s = engine.get_agent_stats(bm, rogue); s.has_cunning_action = True; engine.set_agent_stats(bm, rogue, s)
    for level in (5, 6):
        _set_difficulty(bm, rogue, level)
        assert engine.resolve_strategy(bm, rogue) == rpg.NpcAutomationStrategy.PreferHide, \
            f"Level {level} clamps to the Level-4 heuristics"
    print("✅ test_difficulty_level5_clamps_to_level4 passed")


def test_difficulty_level4_turn_actually_heals():
    """End-to-end: an automated Level-4 cleric (strategy field left at Simple — the override drives) runs
    its turn through run_npc_turn and HEALS the wounded ally instead of attacking."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 1, 1), hp=30)
    hurt   = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 2, 2), hp=40)
    foe    = add_agent_to_battle(engine, bm, create_test_agent("Orc", 3, 3), hp=30)
    bm.set_agent_faction(cleric, 1); bm.set_agent_faction(hurt, 1); bm.set_agent_faction(foe, 2)
    _set_hp(engine, bm, hurt, 8)
    engine.set_agent_spells(bm, cleric, [_heal_spell("Cure Wounds")])
    _arm_melee(engine, bm, cleric)                      # has a weapon, but the resolver must pick Heal
    _automate(bm, cleric)                               # strategy field stays Simple
    _set_difficulty(bm, cleric, 4)

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, cleric)
    status = engine.run_npc_turn(bm, cleric)

    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, hurt) > 8, "the Level-4 override must drive a heal onto the wounded ally"
    assert (cleric, hurt) in calls, "the render hook fires toward the healed ally, not the enemy"
    print("✅ test_difficulty_level4_turn_actually_heals passed")


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
    test_aoe_includes_damaging_rectangle()
    test_aoe_skips_condition_only_area()
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
    test_command_flee_runs_away_no_attack()
    test_command_flee_overrides_strategy()
    test_caster_strategy_flags_round_trip()
    test_caster_strategies_fall_back_to_weapon()
    test_control_priority_config_loaded()
    test_control_casts_single_target_on_nearest()
    test_control_respects_priority_order()
    test_control_area_targets_cluster()
    test_control_moves_into_range_before_casting()
    test_control_falls_back_to_weapon_without_control_spell()
    test_control_skips_concentration_spell_when_already_concentrating()
    test_heal_targets_most_wounded_ally()
    test_heal_revives_downed_ally_first()
    test_heal_multiple_fills_wounded_allies()
    test_heal_moves_into_range_before_casting()
    test_heal_falls_back_to_weapon_when_allies_healthy()
    test_support_buffs_unbuffed_allies()
    test_support_skips_already_buffed_ally()
    test_support_multiple_fills_allies_preferring_engaged()
    test_support_moves_into_range_before_casting()
    test_support_skips_concentration_buff_when_already_concentrating()
    test_support_falls_back_to_weapon_when_all_buffed()
    test_role_classification()
    test_classification_ignores_flavor_spells()
    test_difficulty_level1_everyone_simple()
    test_difficulty_level2_role_split()
    test_difficulty_level3_caster_blasts()
    test_difficulty_level4_ranged_stealth_hide()
    test_difficulty_level4_caster_dynamic()
    test_difficulty_level4_heal_outranks_control()
    test_difficulty_level5_clamps_to_level4()
    test_difficulty_level4_turn_actually_heals()
    print("\nAll NPC automation (Steps 1–10 + Bucket D + difficulty resolver) tests passed ✅")


if __name__ == "__main__":
    run_all()
