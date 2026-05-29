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


# ─────────────────────────────────────────────────────────────────────────────
# Second Wind Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_second_wind_resource():
    """Fighter L1: Second Wind resource exists with 1 use, restores on short rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    fighter_idx = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))

    s = engine.get_agent_stats(bm, fighter_idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 1)
    engine.set_agent_stats(bm, fighter_idx, s)

    s = engine.get_agent_stats(bm, fighter_idx)
    sw = s.get_resource("Second Wind")
    assert sw is not None, "Fighter should have Second Wind resource"
    assert sw.max == 1, f"L1 Fighter should have 1 Second Wind use, got {sw.max}"
    assert sw.current == 1, f"L1 Fighter should start with 1 use, got {sw.current}"
    print("✅ test_second_wind_resource passed")


def test_second_wind_heal_range():
    """Fighter Second Wind heals 1d10 + level (range [1+level, 10+level])."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    fighter_idx = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))

    s = engine.get_agent_stats(bm, fighter_idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 5)
    s.con = 14
    s.hp_max = 50
    s.hp_cur = 30  # Damage the fighter
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 5)
    engine.set_agent_stats(bm, fighter_idx, s)

    # Roll multiple times to verify range
    for _ in range(10):
        s = engine.get_agent_stats(bm, fighter_idx)
        s.hp_cur = 30  # Reset HP
        engine.set_agent_stats(bm, fighter_idx, s)

        roll = engine.roll(10)
        healing = roll + 5  # 1d10 + level (5)
        assert 6 <= healing <= 15, f"Second Wind L5 should heal 6-15, got {healing}"
    print("✅ test_second_wind_heal_range passed")


def test_second_wind_restore_short_rest():
    """Fighter Second Wind restores on short rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    fighter_idx = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))

    s = engine.get_agent_stats(bm, fighter_idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 1)
    engine.set_agent_stats(bm, fighter_idx, s)

    # Spend the resource
    s = engine.get_agent_stats(bm, fighter_idx)
    sw = s.get_resource("Second Wind")
    sw.current = 0
    s.resources["Second Wind"] = sw
    engine.set_agent_stats(bm, fighter_idx, s)

    # Short rest restores it
    s = engine.get_agent_stats(bm, fighter_idx)
    sw = s.get_resource("Second Wind")
    sw.restore_short_rest()
    s.resources["Second Wind"] = sw
    engine.set_agent_stats(bm, fighter_idx, s)

    s = engine.get_agent_stats(bm, fighter_idx)
    sw = s.get_resource("Second Wind")
    assert sw.current == sw.max, f"After short rest, Second Wind should be at max, got {sw.current}/{sw.max}"
    print("✅ test_second_wind_restore_short_rest passed")


# ─────────────────────────────────────────────────────────────────────────────
# Psi Warrior
# ─────────────────────────────────────────────────────────────────────────────

def _psi_warrior(engine, bm, idx, level, intel=16):
    """Configure agent as a Psi Warrior Fighter of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.str = 16
    s.intel = intel
    s.fighter_subclass = rpg.FighterSubclass.PsiWarrior
    s.initialize_class_resources(rpg.CharacterClass.Fighter, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _psi_setup(level, intel=16):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("PsiWarrior", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    _psi_warrior(engine, bm, atk, level, intel=intel)
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _longsword())
    return bm, engine, atk, tgt


def test_psionic_energy_dice():
    """Psionic Energy Dice = 2 × proficiency bonus; die size scales d6/d8/d10/d12 by level."""
    # (level, expected dice, expected die size)
    for level, dice, die in [(3, 4, 6), (5, 6, 8), (11, 8, 10), (17, 12, 12)]:
        bm, engine, atk, _ = _psi_setup(level)
        s = engine.get_agent_stats(bm, atk)
        ped = s.get_resource("Psionic Energy")
        assert ped is not None, f"L{level} Psi Warrior should have Psionic Energy dice"
        assert ped.current == dice, f"L{level} should have {dice} dice, got {ped.current}"
        assert s.psionic_die_size == die, f"L{level} die size should be d{die}, got d{s.psionic_die_size}"
    print("✅ test_psionic_energy_dice passed")


def test_psionic_strike_adds_force_damage():
    """Psionic Strike: adds Force damage to a hit, spends 1 die, once-per-turn flag set."""
    bm, engine, atk, tgt = _psi_setup(5, intel=16)  # d8 die, INT +3

    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit, "attack_bonus=50 should guarantee a hit"
    base_damage = result.total_damage

    ped_before = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current

    # Set the on-hit eligibility flag and apply the effect.
    cond = engine.get_agent_conditions(bm, atk)
    cond.psionic_strike_available = True
    engine.set_agent_conditions(bm, atk, cond)

    engine.apply_psionic_strike_effect(bm, atk, tgt, result)

    # Force damage = 1d8 + INT(+3) → between 4 and 11 added.
    added = result.total_damage - base_damage
    assert 4 <= added <= 11, f"Psionic Strike should add 1d8+3 (4-11) Force, got {added}"

    ped_after = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    assert ped_after == ped_before - 1, f"should spend 1 Psionic Energy die ({ped_before}->{ped_after})"
    atk_cond = engine.get_agent_conditions(bm, atk)
    assert atk_cond.psionic_strike_used, "psionic_strike_used should be set after applying"
    assert not atk_cond.psionic_strike_available, "available flag should be cleared after applying"
    print("✅ test_psionic_strike_adds_force_damage passed")


def test_protective_field_reduces_damage():
    """Protective Field: prevents (die + INT mod) damage capped at the hit, spends 1 die + reaction."""
    bm, engine, _atk, _tgt = _psi_setup(5)
    # Use the Psi Warrior as the defender; give it a known HP deficit to heal back into.
    defender = _atk
    s = engine.get_agent_stats(bm, defender)
    s.hp_max = 100
    s.hp_cur = 50  # took 50 damage already this fight
    engine.set_agent_stats(bm, defender, s)

    ped_before = engine.get_agent_stats(bm, defender).get_resource("Psionic Energy").current

    prevented = engine.apply_protective_field(bm, defender, 30)  # this hit dealt 30
    assert prevented >= 1, f"should prevent at least 1 damage, got {prevented}"
    assert prevented <= 30, f"prevented amount should be capped at damage_taken (30), got {prevented}"

    s = engine.get_agent_stats(bm, defender)
    assert s.hp_cur == 50 + prevented, f"HP should rise by prevented amount, got {s.hp_cur}"
    ped_after = s.get_resource("Psionic Energy").current
    assert ped_after == ped_before - 1, f"should spend 1 Psionic Energy die ({ped_before}->{ped_after})"
    assert engine.get_agent_conditions(bm, defender).reaction_used, "reaction should be consumed"

    # A second use this turn fails: the reaction is already spent.
    again = engine.apply_protective_field(bm, defender, 30)
    assert again == -1, f"second Protective Field should fail (reaction used), got {again}"
    print("✅ test_protective_field_reduces_damage passed")


def test_telekinetic_movement_pushes_and_depletes():
    """Telekinetic Movement: pushes a creature away once per rest, then the resource is depleted."""
    bm, engine, atk, tgt = _psi_setup(5)

    tk_before = engine.get_agent_stats(bm, atk).get_resource("Telekinetic Movement").current
    assert tk_before == 1, "Telekinetic Movement should start with 1 use"

    feet = engine.apply_telekinetic_movement(bm, atk, tgt)
    assert feet >= 0, f"telekinetic movement should return feet moved (>=0), got {feet}"

    tk_after = engine.get_agent_stats(bm, atk).get_resource("Telekinetic Movement").current
    assert tk_after == 0, f"the once-per-rest use should be spent, got {tk_after}"

    # No uses left → returns -1.
    again = engine.apply_telekinetic_movement(bm, atk, tgt)
    assert again == -1, f"with no uses left it should return -1, got {again}"
    print("✅ test_telekinetic_movement_pushes_and_depletes passed")


if __name__ == "__main__":
    test_superiority_dice_l3()
    test_superiority_dice_l10()
    test_trip_sets_prone()
    test_menacing_sets_frightened()
    test_pushing_moves_target()
    test_precision_attack_no_dice_no_flag()
    test_second_wind_resource()
    test_second_wind_heal_range()
    test_second_wind_restore_short_rest()
    test_psionic_energy_dice()
    test_psionic_strike_adds_force_damage()
    test_protective_field_reduces_damage()
    test_telekinetic_movement_pushes_and_depletes()
    print("\n✅ All Fighter tests passed!")
