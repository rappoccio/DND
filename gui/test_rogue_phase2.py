#!/usr/bin/env python3
"""
Test Rogue Phase 2: Cunning Strike riders on Sneak Attack.

Covered: effect validation, dice spending, save resolution, condition application,
Improved Cunning Strike (L11+), Devious Strikes (L14+), level gating.

Sneak Attack + Cunning Strike riders are applied out of band, mirroring Brutal Strike:
execute_action only flags cunning_strike_available on a qualifying hit; the caller then
calls apply_cunning_strike_effect(effects) to roll (sneak dice − cost)d6 and apply riders.
An empty effects list means full Sneak Attack with no rider.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _rogue(engine, bm, idx, level, dex=16):
    """Configure agent idx as a Rogue of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    s.dex = dex
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _high_ac_target(engine, bm, idx):
    """Configure agent as a non-Rogue target with terrible saves."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.str = 1
    s.dex = 1
    s.con = 1
    s.intel = 10
    s.wis = 10
    s.cha = 10
    s.save_prof_str = False
    s.save_prof_dex = False
    s.save_prof_con = False
    s.save_prof_intel = False
    s.save_prof_wis = False
    s.save_prof_cha = False
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _finesse_weapon(attack_bonus=50):
    w = rpg.Weapon()
    w.name = "Test Dagger"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = attack_bonus
    w.bonus_damage = 100
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return w


def _three(primary):
    """set_agent_weapons expects exactly 3 weapons."""
    return [primary, rpg.Weapon(), rpg.Weapon()]


def _breakdown_value(result, label):
    """Return the breakdown amount for a label."""
    for entry in result.damage_breakdown:
        if entry[0] == label:
            return entry[1]
    return None


def _setup(level, dex=20, high_ac_target=True):
    """Build a battle with a Rogue attacker (finesse weapon) and a soft target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue(engine, bm, atk, level, dex=dex)
    if high_ac_target:
        _high_ac_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))
    return bm, engine, atk, tgt


def _sneak_hit(engine, bm, atk, tgt, effects):
    """Land an attack with advantage, then apply Sneak Attack + the given riders out of band.

    Returns the post-apply AttackResult. An empty effects list = full Sneak Attack, no rider.
    """
    for _ in range(60):
        c = engine.get_agent_conditions(bm, atk)
        c.has_advantage = True
        engine.set_agent_conditions(bm, atk, c)
        result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if result.hit:
            break
    else:
        raise AssertionError("attack never landed in 60 tries")

    assert engine.get_agent_conditions(bm, atk).cunning_strike_available, \
        "a qualifying Rogue hit should flag cunning_strike_available"
    engine.apply_cunning_strike_effect(bm, atk, tgt, effects, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Cunning Strike Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cunning_strike_poison():
    """Rogue L5, Poison (1 die cost) — target forced to fail CON save → poisoned."""
    bm, engine, atk, tgt = _setup(5)
    result = _sneak_hit(engine, bm, atk, tgt, [0])  # Poison

    # Sneak Attack: 3d6 - 1 cost = 2d6
    sneak_val = _breakdown_value(result, "sneak attack")
    assert sneak_val is not None, "Sneak Attack should be applied"
    assert 2 <= sneak_val <= 12, f"L5 Cunning Strike with 1 cost (2d6) should be 2..12, got {sneak_val}"
    assert engine.get_agent_conditions(bm, tgt).poisoned, "Target should be poisoned"
    print("✅ test_cunning_strike_poison passed")


def test_cunning_strike_trip():
    """Rogue L5, Trip (1 die cost) — target forced to fail DEX save → prone."""
    bm, engine, atk, tgt = _setup(5)
    result = _sneak_hit(engine, bm, atk, tgt, [1])  # Trip

    sneak_val = _breakdown_value(result, "sneak attack")
    assert 2 <= sneak_val <= 12, f"L5 Cunning Strike Trip (2d6) should be 2..12, got {sneak_val}"
    assert engine.get_agent_conditions(bm, tgt).prone, "Target should be prone"
    print("✅ test_cunning_strike_trip passed")


def test_cunning_strike_withdraw():
    """Rogue L5, Withdraw (1 die cost) — attacker gains disengaging, target unaffected."""
    bm, engine, atk, tgt = _setup(5)
    result = _sneak_hit(engine, bm, atk, tgt, [2])  # Withdraw

    sneak_val = _breakdown_value(result, "sneak attack")
    assert 2 <= sneak_val <= 12, f"L5 Cunning Strike Withdraw (2d6) should be 2..12, got {sneak_val}"
    assert engine.get_agent_conditions(bm, atk).disengaging, "Attacker should be disengaging"

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert not tgt_cond.poisoned and not tgt_cond.prone and not tgt_cond.blinded, \
        "Withdraw should not affect target"
    print("✅ test_cunning_strike_withdraw passed")


def test_cunning_strike_improved_l11():
    """Rogue L11, two effects [Poison, Trip] → both land, 6d6 - 2 = 4d6 damage."""
    bm, engine, atk, tgt = _setup(11)
    result = _sneak_hit(engine, bm, atk, tgt, [0, 1])  # Poison + Trip

    sneak_val = _breakdown_value(result, "sneak attack")
    # 6d6 at L11, minus 2 cost = 4d6 (4..24)
    assert 4 <= sneak_val <= 24, f"L11 Cunning Strike [0,1] (4d6) should be 4..24, got {sneak_val}"

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert tgt_cond.poisoned, "Target should be poisoned"
    assert tgt_cond.prone, "Target should be prone"
    print("✅ test_cunning_strike_improved_l11 passed")


def test_cunning_strike_too_many_effects_l5():
    """Rogue L5 with two effects → rejected (need L11+), full dice rolled, no effects apply."""
    bm, engine, atk, tgt = _setup(5)
    result = _sneak_hit(engine, bm, atk, tgt, [0, 1])  # Invalid at L5

    # Full 3d6, no effects
    sneak_val = _breakdown_value(result, "sneak attack")
    assert 3 <= sneak_val <= 18, f"Invalid effect set → full 3d6, got {sneak_val}"

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert not tgt_cond.poisoned and not tgt_cond.prone, \
        "Invalid effect set → no conditions applied"
    print("✅ test_cunning_strike_too_many_effects_l5 passed")


def test_cunning_strike_devious_knock_out_l14():
    """Rogue L14, Knock Out (6 dice cost) — target forced to fail CON save → unconscious."""
    bm, engine, atk, tgt = _setup(14)
    result = _sneak_hit(engine, bm, atk, tgt, [4])  # Knock Out

    # 7d6 at L14, minus 6 cost = 1d6 (1..6)
    sneak_val = _breakdown_value(result, "sneak attack")
    assert sneak_val is not None, f"Sneak Attack should be applied, breakdown: {result.damage_breakdown}"
    assert 1 <= sneak_val <= 6, f"L14 Cunning Strike KO (1d6) should be 1..6, got {sneak_val}"

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert tgt_cond.unconscious, "Target should be unconscious"
    assert tgt_cond.incapacitated, "Unconscious implies incapacitated"
    print("✅ test_cunning_strike_devious_knock_out_l14 passed")


def test_cunning_strike_devious_obscure_l14():
    """Rogue L14, Obscure (3 dice cost) — target forced to fail DEX save → blinded."""
    bm, engine, atk, tgt = _setup(14)
    result = _sneak_hit(engine, bm, atk, tgt, [5])  # Obscure

    # 7d6 at L14, minus 3 cost = 4d6 (4..24)
    sneak_val = _breakdown_value(result, "sneak attack")
    assert sneak_val is not None, "Sneak Attack should be applied"
    assert 4 <= sneak_val <= 24, f"L14 Cunning Strike Obscure (4d6) should be 4..24, got {sneak_val}"
    assert engine.get_agent_conditions(bm, tgt).blinded, "Target should be blinded"
    print("✅ test_cunning_strike_devious_obscure_l14 passed")


def test_cunning_strike_devious_rejected_l5():
    """Rogue L5 with Knock Out effect → rejected (need L14+), full dice, no effect."""
    bm, engine, atk, tgt = _setup(5)
    result = _sneak_hit(engine, bm, atk, tgt, [4])  # Knock Out (invalid at L5)

    # Full 3d6, no effects
    sneak_val = _breakdown_value(result, "sneak attack")
    assert 3 <= sneak_val <= 18, f"Invalid level → full 3d6, got {sneak_val}"
    assert not engine.get_agent_conditions(bm, tgt).unconscious, "Knock Out invalid at L5 → no effect"
    print("✅ test_cunning_strike_devious_rejected_l5 passed")


def test_l14_with_basic_poison():
    """L14 Rogue with a basic Poison rider: sneak attack applies and the target is poisoned."""
    bm, engine, atk, tgt = _setup(14)
    result = _sneak_hit(engine, bm, atk, tgt, [0])  # Poison (works at L5+)

    # 7d6 at L14, minus 1 cost = 6d6 (6..36)
    sneak_val = _breakdown_value(result, "sneak attack")
    assert sneak_val is not None, "Sneak Attack should be applied"
    assert 6 <= sneak_val <= 36, f"L14 Cunning Strike Poison (6d6) should be 6..36, got {sneak_val}"
    assert engine.get_agent_conditions(bm, tgt).poisoned, "Target should be poisoned"
    print("✅ test_l14_with_basic_poison passed")


if __name__ == "__main__":
    test_cunning_strike_poison()
    test_cunning_strike_trip()
    test_cunning_strike_withdraw()
    test_cunning_strike_improved_l11()
    test_cunning_strike_too_many_effects_l5()
    test_cunning_strike_devious_knock_out_l14()
    test_cunning_strike_devious_obscure_l14()
    test_cunning_strike_devious_rejected_l5()
    test_l14_with_basic_poison()
    print("\n✅ All Cunning Strike tests passed!")
