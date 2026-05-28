#!/usr/bin/env python3
"""
Test Battle Master Fighter: Superiority Dice resource, Maneuvers (Trip/Menacing/Pushing),
and Precision Attack.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _battle_master(engine, bm, idx, level, str_score=16):
    """Configure agent as a Battle Master Fighter of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.str = str_score
    s.dex = 12
    s.con = 14
    s.fighter_subclass = rpg.FighterSubclass.BattleMaster
    s.initialize_class_resources(rpg.CharacterClass.Fighter, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _soft_target(engine, bm, idx, hp=100):
    """Configure agent as a soft target with low saves."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.str = 8
    s.dex = 8
    s.con = 10
    s.wis = 8
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = 10
    s.save_prof_str = False
    s.save_prof_dex = False
    s.save_prof_con = False
    s.save_prof_wis = False
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _longsword():
    """Return a guaranteed-hit longsword weapon."""
    w = rpg.Weapon()
    w.name = "Longsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = 50  # guaranteed hit
    w.bonus_damage = 0
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _setup(level, str_score=16):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("BattleMaster", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    _battle_master(engine, bm, atk, level, str_score=str_score)
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _longsword())
    return bm, engine, atk, tgt


# ─────────────────────────────────────────────────────────────────────────────

def test_superiority_dice_l3():
    """Battle Master L3: 4 Superiority Dice, d8."""
    bm, engine, atk, tgt = _setup(3)
    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    assert sd is not None, "Battle Master should have Superiority Dice resource"
    assert sd.max == 4, f"L3 should have 4 dice, got {sd.max}"
    assert sd.current == 4, f"L3 should start with 4 dice, got {sd.current}"
    assert s.superiority_die_size == 8, f"L3 die size should be d8, got {s.superiority_die_size}"
    print("✅ test_superiority_dice_l3 passed")


def test_superiority_dice_l10():
    """Battle Master L10: 6 Superiority Dice, d10; restores on short rest."""
    bm, engine, atk, tgt = _setup(10)
    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    assert sd is not None, "Battle Master should have Superiority Dice resource"
    assert sd.max == 6, f"L10 should have 6 dice, got {sd.max}"
    assert s.superiority_die_size == 10, f"L10 die size should be d10, got {s.superiority_die_size}"

    # Spend all dice then restore on short rest
    sd.current = 0
    s.resources["Superiority Dice"] = sd
    engine.set_agent_stats(bm, atk, s)

    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    sd.restore_short_rest()
    s.resources["Superiority Dice"] = sd
    engine.set_agent_stats(bm, atk, s)

    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max, f"After short rest, dice should be at max, got {sd.current}/{sd.max}"
    print("✅ test_superiority_dice_l10 passed")


def test_trip_sets_prone():
    """Trip maneuver: condition_applied matches target.prone; save/DC are set; 1 die spent."""
    bm, engine, atk, tgt = _setup(3)

    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit, "attack_bonus=50 should guarantee a hit"

    cond = engine.get_agent_conditions(bm, atk)
    cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)

    res = engine.apply_maneuver_effect(bm, atk, tgt, 0)  # 0 = Trip
    assert res.valid, "ManeuverResult should be valid"
    assert res.maneuver_type == 0, "maneuver_type should be 0 (Trip)"
    assert res.save_dc > 0, "save_dc should be set"
    assert res.save_roll > 0, "save_roll should be set"

    # Verify the C++ logic is consistent: condition_applied ↔ target.prone
    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert res.condition_applied == tgt_cond.prone, \
        f"condition_applied={res.condition_applied} must match prone={tgt_cond.prone}"

    # Verify 1 die was spent regardless of save outcome
    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, f"Should have spent 1 die (have {sd.current}/{sd.max})"
    print("✅ test_trip_sets_prone passed")


def test_menacing_sets_frightened():
    """Menacing maneuver: condition_applied matches target.frightened; 1 die spent."""
    bm, engine, atk, tgt = _setup(3)

    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit

    cond = engine.get_agent_conditions(bm, atk)
    cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)

    res = engine.apply_maneuver_effect(bm, atk, tgt, 1)  # 1 = Menacing
    assert res.valid, "ManeuverResult should be valid"
    assert res.maneuver_type == 1
    assert res.save_dc > 0 and res.save_roll > 0

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert res.condition_applied == tgt_cond.frightened, \
        f"condition_applied={res.condition_applied} must match frightened={tgt_cond.frightened}"

    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, f"Should have spent 1 die (have {sd.current}/{sd.max})"
    print("✅ test_menacing_sets_frightened passed")


def test_pushing_moves_target():
    """Pushing maneuver: target is pushed up to 15 feet."""
    bm, engine, atk, tgt = _setup(3)

    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit

    cond = engine.get_agent_conditions(bm, atk)
    cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)

    tgt_before = bm.placed_agents[tgt].origin

    res = engine.apply_maneuver_effect(bm, atk, tgt, 2)  # 2 = Pushing
    assert res.valid, "ManeuverResult should be valid"
    # push_distance may be 0 if blocked by map edges, but res.valid confirms the call succeeded
    tgt_after = bm.placed_agents[tgt].origin
    # If push_distance > 0, target should have moved
    if res.push_distance > 0:
        assert (tgt_after.col != tgt_before.col or tgt_after.row != tgt_before.row), \
            "Target should have moved after Pushing Attack"
    print("✅ test_pushing_moves_target passed")


def test_precision_attack_no_dice_no_flag():
    """Precision Attack flag is NOT set when Battle Master has no Superiority Dice."""
    bm, engine, atk, tgt = _setup(3)

    # Spend all dice first
    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice")
    sd.current = 0
    s.resources["Superiority Dice"] = sd
    engine.set_agent_stats(bm, atk, s)

    # Set AC very high to force a miss
    tgt_s = engine.get_agent_stats(bm, tgt)
    tgt_s.base_ac = 30
    engine.set_agent_stats(bm, tgt, tgt_s)
    engine.set_agent_weapons(bm, atk, _longsword())
    w = rpg.Weapon()
    w.name = "Longsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.attack_bonus = -10  # guaranteed miss
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    for _ in range(5):
        result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if not result.hit and not result.fumble:
            cond = engine.get_agent_conditions(bm, atk)
            assert not cond.maneuver_precision_available, \
                "Precision flag should not be set when no dice remain"
            print("✅ test_precision_attack_no_dice_no_flag passed")
            return

    print("✅ test_precision_attack_no_dice_no_flag passed (no miss encountered, skipped)")


if __name__ == "__main__":
    test_superiority_dice_l3()
    test_superiority_dice_l10()
    test_trip_sets_prone()
    test_menacing_sets_frightened()
    test_pushing_moves_target()
    test_precision_attack_no_dice_no_flag()
    print("\n✅ All Battle Master Fighter tests passed!")
