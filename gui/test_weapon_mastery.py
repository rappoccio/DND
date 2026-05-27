#!/usr/bin/env python3
"""
Weapon Mastery (2024) — phase 2a/2b: framework + the auto-applied properties.

A creature with the Weapon Mastery feature (stats.weapon_mastery > 0) applies the
mastery property of the *proficient* weapon it attacks with:

  Auto:
    Sap   — on hit, the target has disadvantage on its next attack
    Slow  — on hit + damage, the target's Speed drops 10 ft on its next turn
    Vex   — on hit + damage, the attacker has advantage on its next attack vs that target
    Graze — on a (non-fumble) miss, the target still takes ability-modifier damage
  Prompted (engine only sets an availability flag; the GUI offers the choice in 2c):
    Push / Topple / Cleave

Arm stats AFTER all agents are placed (add_agent_to_battle re-applies configs, which
wipes earlier set_agent_stats calls).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

# The enum value is named "None" (a Python keyword) — reach it via getattr.
_NO_MASTERY = getattr(rpg.WeaponMastery, "None")


def _mk_weapon(name, mastery, attack_bonus=30, finesse=False, proficient=True, die=8):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.finesse = finesse
    w.proficient = proficient
    w.mastery = mastery
    w.attack_bonus = attack_bonus
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _place(engine, bm, name, col, row, size=1):
    cfg = create_test_agent(name, col, row)
    cfg.size = size
    return add_agent_to_battle(engine, bm, cfg)


def _three(weapons):
    """set_agent_weapons requires exactly 3 weapons [main, off, ranged]; pad with fillers."""
    weapons = list(weapons)
    while len(weapons) < 3:
        weapons.append(_mk_weapon("Filler", _NO_MASTERY))
    return weapons[:3]


def _arm_attacker(engine, bm, idx, weapons, weapon_mastery=1, strv=16):
    s = engine.get_agent_stats(bm, idx)
    s.str = strv
    s.dex = 10
    s.prof_bonus = 2
    s.hp_max = 60
    s.hp_cur = 60
    s.weapon_mastery = weapon_mastery
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, _three(weapons))


def _set_target(engine, bm, idx, hp=200, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _land_hit(engine, bm, attacker, target, weapon_idx=0, tries=20):
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(attacker, target, weapon_idx))
        if r.hit:
            return r
    raise AssertionError("attack never landed")


# ─────────────────────────────────────────────────────────────────────────────
#  Auto properties
# ─────────────────────────────────────────────────────────────────────────────

def test_vex_sets_then_consumes_advantage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    # weapon 0 = Vex, weapon 1 = plain (no mastery) to verify the flag is consumed.
    _arm_attacker(engine, bm, a, [_mk_weapon("Vexer", rpg.WeaponMastery.Vex),
                                  _mk_weapon("Plain", _NO_MASTERY)])
    _set_target(engine, bm, t)

    r = _land_hit(engine, bm, a, t, weapon_idx=0)
    assert r.total_damage > 0
    assert _cond(engine, bm, a).vex_target_idx == t, "Vex should grant advantage vs the hit target"

    # Attacking again (with the no-mastery weapon) must consume Vex and not re-set it.
    engine.execute_action(bm, rpg.Attack(a, t, 1))
    assert _cond(engine, bm, a).vex_target_idx == -1, "Vex advantage must be consumed by the next attack"
    print("✅ test_vex_sets_then_consumes_advantage passed")


def test_sap_imposes_then_consumes_disadvantage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    b = _place(engine, bm, "Bystander", 7, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Sapper", rpg.WeaponMastery.Sap)])
    _set_target(engine, bm, t)
    _set_target(engine, bm, b)
    # Give the (sapped) target a plain weapon so it can make an attack.
    engine.set_agent_weapons(bm, t, _three([_mk_weapon("Stick", _NO_MASTERY)]))

    _land_hit(engine, bm, a, t)
    assert _cond(engine, bm, t).sapped, "a Sap hit should leave the target Sapped"

    # When the sapped creature attacks, the disadvantage is consumed.
    engine.execute_action(bm, rpg.Attack(t, b, 0))
    assert not _cond(engine, bm, t).sapped, "Sap must be consumed by the target's next attack"
    print("✅ test_sap_imposes_then_consumes_disadvantage passed")


def test_slow_reduces_speed_one_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Slower", rpg.WeaponMastery.Slow)])
    _set_target(engine, bm, t)

    r = _land_hit(engine, bm, a, t)
    assert r.total_damage > 0
    assert _cond(engine, bm, t).slowed, "a Slow hit that deals damage should leave the target Slowed"

    # The target's next turn: Speed is reduced by 10 ft (30 -> 20), then the flag clears.
    engine.begin_turn(bm, t)
    assert engine.get_walk_remaining(t) == 20, "Slow should cut the target's Speed by 10 ft for one turn"
    assert not _cond(engine, bm, t).slowed, "Slow expires after the affected turn"
    print("✅ test_slow_reduces_speed_one_turn passed")


def test_graze_deals_modifier_damage_on_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    # attack_bonus 0 vs AC 40 -> nearly every roll is a clean miss (only nat-20 hits, nat-1 fumbles).
    _arm_attacker(engine, bm, a, [_mk_weapon("Grazer", rpg.WeaponMastery.Graze, attack_bonus=0)], strv=16)
    _set_target(engine, bm, t, ac=40)
    expected = 3  # STR 16 -> +3 attack ability modifier

    for _ in range(60):
        hp_before = engine.get_agent_stats(bm, t).hp_cur
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if not r.hit and not r.fumble:
            hp_after = engine.get_agent_stats(bm, t).hp_cur
            assert r.total_damage == expected, f"Graze should deal {expected}, got {r.total_damage}"
            assert hp_before - hp_after == expected, "Graze damage must actually reduce the target's HP"
            print("✅ test_graze_deals_modifier_damage_on_miss passed")
            return
    raise AssertionError("never produced a clean (non-fumble) miss to test Graze")


# ─────────────────────────────────────────────────────────────────────────────
#  Prompted properties — engine only flags availability (resolved by the GUI in 2c)
# ─────────────────────────────────────────────────────────────────────────────

def test_push_flags_only_large_or_smaller():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    med = _place(engine, bm, "Medium", 6, 5, size=1)
    _arm_attacker(engine, bm, a, [_mk_weapon("Pusher", rpg.WeaponMastery.Push)])
    _set_target(engine, bm, med)
    _land_hit(engine, bm, a, med)
    assert _cond(engine, bm, a).push_available, "Push should be offered against a Medium target"

    # A Huge (size 3) target cannot be pushed — no prompt offered.
    bm2 = setup_battle_map(); engine2 = setup_combat_engine()
    a2 = _place(engine2, bm2, "Atk", 5, 5)
    huge = _place(engine2, bm2, "Huge", 6, 5, size=3)
    _arm_attacker(engine2, bm2, a2, [_mk_weapon("Pusher", rpg.WeaponMastery.Push)])
    _set_target(engine2, bm2, huge)
    _land_hit(engine2, bm2, a2, huge)
    assert not _cond(engine2, bm2, a2).push_available, "Push must not be offered against a Huge target"
    print("✅ test_push_flags_only_large_or_smaller passed")


def test_topple_and_cleave_flag_for_prompt():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Toppler", rpg.WeaponMastery.Topple),
                                  _mk_weapon("Cleaver", rpg.WeaponMastery.Cleave)])
    _set_target(engine, bm, t)

    _land_hit(engine, bm, a, t, weapon_idx=0)
    assert _cond(engine, bm, a).topple_available, "Topple should flag for a prompt on a hit"

    _land_hit(engine, bm, a, t, weapon_idx=1)
    assert _cond(engine, bm, a).cleave_available, "Cleave should flag for a prompt on a hit"
    print("✅ test_topple_and_cleave_flag_for_prompt passed")


def test_cleave_respects_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Cleaver", rpg.WeaponMastery.Cleave)])
    _set_target(engine, bm, t)
    # Pretend Cleave was already used this turn.
    c = engine.get_agent_conditions(bm, a)
    c.cleave_used_this_turn = True
    engine.set_agent_conditions(bm, a, c)

    _land_hit(engine, bm, a, t)
    assert not _cond(engine, bm, a).cleave_available, "Cleave is once per turn — no second prompt"
    print("✅ test_cleave_respects_once_per_turn passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Gating — no mastery without the feature or weapon proficiency
# ─────────────────────────────────────────────────────────────────────────────

def test_no_feature_no_mastery():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Vexer", rpg.WeaponMastery.Vex)], weapon_mastery=0)
    _set_target(engine, bm, t)
    _land_hit(engine, bm, a, t)
    assert _cond(engine, bm, a).vex_target_idx == -1, "no Weapon Mastery feature -> no mastery effect"
    print("✅ test_no_feature_no_mastery passed")


def test_not_proficient_no_mastery():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Atk", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm_attacker(engine, bm, a, [_mk_weapon("Vexer", rpg.WeaponMastery.Vex, proficient=False)])
    _set_target(engine, bm, t)
    _land_hit(engine, bm, a, t)
    assert _cond(engine, bm, a).vex_target_idx == -1, "mastery requires proficiency with the weapon"
    print("✅ test_not_proficient_no_mastery passed")


if __name__ == "__main__":
    test_vex_sets_then_consumes_advantage()
    test_sap_imposes_then_consumes_disadvantage()
    test_slow_reduces_speed_one_turn()
    test_graze_deals_modifier_damage_on_miss()
    test_push_flags_only_large_or_smaller()
    test_topple_and_cleave_flag_for_prompt()
    test_cleave_respects_once_per_turn()
    test_no_feature_no_mastery()
    test_not_proficient_no_mastery()
    print("\n✅ All Weapon Mastery (2a/2b) tests passed!")
