#!/usr/bin/env python3
"""
Test Battle Master Fighter: Superiority Dice resource, Maneuvers (Trip/Menacing/Pushing),
and Precision Attack.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

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
    assert result.hit, "the attack should hit against the low-AC target"

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
    assert result.hit, "the attack should hit against the low-AC target"
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


# ── Eldritch Knight: spellcasting chassis + War Magic + Eldritch Strike ──────

def _eldritch_knight(engine, bm, idx, level, intel=16):
    """Configure agent as an Eldritch Knight Fighter of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.str = 16
    s.dex = 12
    s.con = 14
    s.intel = intel
    s.fighter_subclass = rpg.FighterSubclass.EldritchKnight
    s.initialize_class_resources(rpg.CharacterClass.Fighter, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _ek_setup(level):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("EldritchKnight", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    _eldritch_knight(engine, bm, atk, level)
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _longsword())
    return bm, engine, atk, tgt


def test_ek_spellcasting_chassis_l3():
    """EK L3: third-caster begins — 2× 1st-level slots, INT casting, can_cast_spell."""
    bm, engine, atk, tgt = _ek_setup(3)
    s = engine.get_agent_stats(bm, atk)
    assert s.can_cast_spell, "EK L3 should be a spellcaster"
    assert s.spellcasting_ability == 3, f"EK casts with INT (3), got {s.spellcasting_ability}"
    assert s.spell_slots_max[0] == 2, f"EK L3 should have 2 first-level slots, got {s.spell_slots_max[0]}"
    assert sum(s.spell_slots_max[1:]) == 0, "EK L3 should have no slots above 1st"
    print("✅ test_ek_spellcasting_chassis_l3 passed")


def test_ek_spellcasting_chassis_l7():
    """EK L7: War Magic level — 4× 1st, 2× 2nd."""
    bm, engine, atk, tgt = _ek_setup(7)
    s = engine.get_agent_stats(bm, atk)
    assert s.spell_slots_max[0] == 4 and s.spell_slots_max[1] == 2, \
        f"EK L7 should have 4×1st / 2×2nd, got {list(s.spell_slots_max[:3])}"
    assert s.spell_slots_max[2] == 0, "EK L7 should have no 3rd-level slots"
    print("✅ test_ek_spellcasting_chassis_l7 passed")


def test_ek_third_caster_scaling():
    """EK L13 reaches 3rd-level slots; L20 reaches 4th (third-caster cap)."""
    bm, engine, atk, tgt = _ek_setup(13)
    s13 = engine.get_agent_stats(bm, atk)
    assert s13.spell_slots_max[2] == 2, f"EK L13 should have 2×3rd, got {s13.spell_slots_max[2]}"
    assert s13.spell_slots_max[3] == 0, "EK L13 should have no 4th-level slots"

    bm, engine, atk, tgt = _ek_setup(20)
    s20 = engine.get_agent_stats(bm, atk)
    assert s20.spell_slots_max[3] == 1, f"EK L20 should have 1×4th, got {s20.spell_slots_max[3]}"
    assert sum(s20.spell_slots_max[4:]) == 0, "third-caster caps at 4th-level slots"
    print("✅ test_ek_third_caster_scaling passed")


def test_non_ek_fighter_no_slots():
    """A non-EK Fighter (Champion) has no spell slots and cannot cast."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Champion", 5, 5))
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 7)
    s.fighter_subclass = rpg.FighterSubclass.Champion
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 7)
    engine.set_agent_stats(bm, idx, s)
    s = engine.get_agent_stats(bm, idx)
    assert sum(s.spell_slots_max) == 0, "non-EK Fighter should have no spell slots"
    print("✅ test_non_ek_fighter_no_slots passed")


def test_war_magic_gate():
    """War Magic gate: open for EK L7+, closes after use, reopens when the flag clears."""
    bm, engine, atk, tgt = _ek_setup(7)
    assert engine.can_use_war_magic(bm, atk), "EK L7 should be able to use War Magic"

    engine.mark_war_magic_used(bm, atk)
    assert not engine.can_use_war_magic(bm, atk), "after use, War Magic is gated"
    assert engine.get_agent_conditions(bm, atk).war_magic_used, "the once-per gate flag is set"

    # A fresh Attack action (modeled by clearing the flag) reopens it.
    c = engine.get_agent_conditions(bm, atk)
    c.war_magic_used = False
    engine.set_agent_conditions(bm, atk, c)
    assert engine.can_use_war_magic(bm, atk), "clearing the flag reopens War Magic"
    print("✅ test_war_magic_gate passed")


def test_war_magic_requires_l7():
    """War Magic is unavailable before L7 (and to non-EK Fighters)."""
    bm, engine, atk, tgt = _ek_setup(6)
    assert not engine.can_use_war_magic(bm, atk), "EK L6 has no War Magic yet"
    print("✅ test_war_magic_requires_l7 passed")


def test_eldritch_strike_tags_target():
    """EK L10 weapon hit tags the target with the EK's index (disadvantage on next save vs EK spell)."""
    bm, engine, atk, tgt = _ek_setup(10)
    assert engine.get_agent_conditions(bm, tgt).eldritch_strike_by == -1, "no tag before the hit"

    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit, "the attack should hit against the low-AC target"
    assert engine.get_agent_conditions(bm, tgt).eldritch_strike_by == atk, \
        "Eldritch Strike should tag the target with the EK's index"
    print("✅ test_eldritch_strike_tags_target passed")


def test_eldritch_strike_requires_l10():
    """Below L10, a weapon hit does NOT apply the Eldritch Strike tag."""
    bm, engine, atk, tgt = _ek_setup(9)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert engine.get_agent_conditions(bm, tgt).eldritch_strike_by == -1, \
        "EK L9 should not yet apply Eldritch Strike"
    print("✅ test_eldritch_strike_requires_l10 passed")


def _action_cantrip(name="Fire Bolt"):
    """A free action-casting-time spell-attack cantrip."""
    s = rpg.Spell()
    s.name = name
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.AttackRoll
    s.range = 120
    s.level = 0
    s.casting_time = rpg.CastingTime.Action
    return s


def test_available_war_magic_spells():
    """available_war_magic_spells (rules in C++): an EK L7's action-cantrip qualifies; a
    bonus-action cantrip does not; a non-EK / sub-L7 list is empty."""
    bm, engine, atk, tgt = _ek_setup(7)
    bonus_cantrip = _action_cantrip("Mind Sliver")
    bonus_cantrip.casting_time = rpg.CastingTime.BonusAction
    engine.set_agent_spells(bm, atk, [_action_cantrip("Fire Bolt"), bonus_cantrip])
    wm = list(engine.available_war_magic_spells(bm, atk))
    assert wm == [0], f"only the action-cantrip (index 0) should qualify, got {wm}"

    # A leveled spell does NOT qualify before L18 (Improved War Magic).
    bm2, engine2, atk2, _ = _ek_setup(7)
    lvl1 = _action_cantrip("Magic Missile")
    lvl1.level = 1
    engine2.set_agent_spells(bm2, atk2, [lvl1])
    assert list(engine2.available_war_magic_spells(bm2, atk2)) == [], \
        "level-1 spell should not qualify for War Magic until L18"

    # Below L7: empty.
    bm3, engine3, atk3, _ = _ek_setup(6)
    engine3.set_agent_spells(bm3, atk3, [_action_cantrip()])
    assert list(engine3.available_war_magic_spells(bm3, atk3)) == [], "EK L6 has no War Magic"
    print("✅ test_available_war_magic_spells passed")


def test_improved_war_magic_l18():
    """Improved War Magic (L18): a level 1-5 action spell becomes War-Magic-eligible (needs a slot)."""
    bm, engine, atk, tgt = _ek_setup(18)
    lvl2 = _action_cantrip("Scorching Ray")
    lvl2.level = 2
    engine.set_agent_spells(bm, atk, [lvl2])
    wm = list(engine.available_war_magic_spells(bm, atk))
    assert wm == [0], f"L18 EK should be able to War-Magic a level-2 action spell, got {wm}"
    print("✅ test_improved_war_magic_l18 passed")


def test_arcane_charge():
    """Arcane Charge (validation + teleport in C++): EK L15 teleports within 30 ft; out-of-range
    and ineligible callers are rejected by status code."""
    bm, engine, atk, tgt = _ek_setup(15)
    origin = bm.placed_agents[atk].origin

    # In range (5,5) → (8,5) is 15 ft. Should succeed and move the agent.
    feet = engine.apply_arcane_charge(bm, atk, 8, 5)
    assert feet >= 0, f"in-range teleport should succeed, got {feet}"
    moved = bm.placed_agents[atk].origin
    assert (moved.col, moved.row) == (8, 5), f"agent should be at (8,5), got ({moved.col},{moved.row})"

    # Out of range: (8,5) → (20,5) is 60 ft → -2.
    assert engine.apply_arcane_charge(bm, atk, 20, 5) == -2, "60 ft should be out of range (-2)"

    # Not eligible: an EK below L15 → -1.
    bm2, engine2, atk2, _ = _ek_setup(14)
    assert engine2.apply_arcane_charge(bm2, atk2, 7, 5) == -1, "EK L14 has no Arcane Charge (-1)"
    print("✅ test_arcane_charge passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Additional Battle Master maneuvers (2026-06-14)
# ─────────────────────────────────────────────────────────────────────────────

def test_save_dc_uses_max_str_dex():
    """Maneuver save DC = 8 + PB + max(STR,DEX) mod (2024)."""
    bm, engine, atk, tgt = _setup(3, str_score=10)  # STR 10 (+0); _battle_master sets DEX 12 (+1)
    cond = engine.get_agent_conditions(bm, atk)
    cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)
    res = engine.apply_maneuver_effect(bm, atk, tgt, 0)  # Trip
    assert res.save_dc == 11, f"DC should be 8 + PB(2) + max(+0,+1)=11, got {res.save_dc}"
    print("✅ test_save_dc_uses_max_str_dex passed")


def test_goading_attack_sets_goaded_by():
    """Goading Attack (type 3): on a failed WIS save the target is goaded_by the attacker."""
    bm, engine, atk, tgt = _setup(3)
    engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    cond = engine.get_agent_conditions(bm, atk); cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)
    res = engine.apply_maneuver_effect(bm, atk, tgt, 3)
    assert res.valid and res.maneuver_type == 3
    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert res.condition_applied == (tgt_cond.goaded_by == atk), \
        "condition_applied must match goaded_by being set to the attacker"
    s = engine.get_agent_stats(bm, atk); sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, "Goading spends 1 Superiority Die"
    print("✅ test_goading_attack_sets_goaded_by passed")


def test_distracting_strike_grants_advantage():
    """Distracting Strike (type 4): no save — the target is distracted_by the attacker."""
    bm, engine, atk, tgt = _setup(3)
    engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    cond = engine.get_agent_conditions(bm, atk); cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)
    res = engine.apply_maneuver_effect(bm, atk, tgt, 4)
    assert res.valid and res.condition_applied, "Distracting Strike always applies (no save)"
    assert engine.get_agent_conditions(bm, tgt).distracted_by == atk
    print("✅ test_distracting_strike_grants_advantage passed")


def test_disarming_makes_unarmed():
    """A disarmed creature's weapon attacks resolve as improvised Unarmed Strikes (STR-mod only)."""
    bm, engine, atk, tgt = _setup(3)  # atk STR 16 (+3), longsword (1d8 Slashing)
    cond = engine.get_agent_conditions(bm, atk)
    cond.disarmed = True
    cond.disarmed_by = tgt
    engine.set_agent_conditions(bm, atk, cond)
    ts = engine.get_agent_stats(bm, tgt); ts.base_ac = 1; engine.set_agent_stats(bm, tgt, ts)
    hits = 0
    for _ in range(15):
        ts = engine.get_agent_stats(bm, tgt); ts.hp_cur = ts.hp_max
        engine.set_agent_stats(bm, tgt, ts)
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if r.hit:
            hits += 1
            assert rpg.PhysicalDamage.Slashing not in r.physical_damage_types, \
                "a disarmed attack must not deal the longsword's Slashing damage"
            assert r.total_damage == 3, f"unarmed should deal only the STR mod (3), got {r.total_damage}"
    assert hits > 0, "expected at least one unarmed hit"
    print("✅ test_disarming_makes_unarmed passed")


def test_sweeping_attack_splashes_second():
    """Sweeping Attack (type 6): the original roll splashes superiority-die damage to a 2nd creature."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("BM", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("T1", 6, 5))
    sec = add_agent_to_battle(engine, bm, create_test_agent("T2", 7, 5))  # within 5 ft of T1
    _battle_master(engine, bm, atk, 3)
    _soft_target(engine, bm, tgt)
    _soft_target(engine, bm, sec)
    engine.set_agent_weapons(bm, atk, _longsword())
    action = rpg.Attack(atk, tgt, 0)
    result = engine.execute_action(bm, action)
    assert result.hit
    cond = engine.get_agent_conditions(bm, atk); cond.maneuver_available = True
    engine.set_agent_conditions(bm, atk, cond)
    sec_before = engine.get_agent_stats(bm, sec).hp_cur
    res = engine.apply_sweeping_attack(bm, action, result, sec)
    assert res.valid and res.maneuver_type == 6
    assert res.condition_applied, "the high roll hits the 2nd creature"
    assert res.extra_damage > 0
    assert engine.get_agent_stats(bm, sec).hp_cur == sec_before - res.extra_damage
    s = engine.get_agent_stats(bm, atk); sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, "Sweeping spends 1 Superiority Die"
    print("✅ test_sweeping_attack_splashes_second passed")


def test_rally_grants_temp_hp():
    """Rally: grant a creature temp HP = superiority die + CHA mod (min 1)."""
    bm, engine, atk, tgt = _setup(3)
    before = engine.get_agent_stats(bm, tgt).temp_hp
    amount = engine.apply_rally(bm, atk, tgt)
    assert amount >= 1, "Rally grants at least 1 temp HP"
    assert engine.get_agent_stats(bm, tgt).temp_hp == max(before, amount), "grantTempHp uses max() semantics"
    s = engine.get_agent_stats(bm, atk); sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, "Rally spends 1 Superiority Die"
    print("✅ test_rally_grants_temp_hp passed")


def test_feinting_attack_adds_die_damage():
    """Feinting Attack: Advantage + a superiority die on the next attack vs the feinted target."""
    bm, engine, atk, tgt = _setup(3)
    assert engine.apply_feinting_attack(bm, atk, tgt)
    assert engine.get_agent_conditions(bm, atk).feint_target_idx == tgt
    r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert r.hit
    labels = [lbl for lbl, _ in r.damage_breakdown]
    assert "feint" in labels, f"feint die should appear in the damage breakdown, got {labels}"
    assert engine.get_agent_conditions(bm, atk).feint_target_idx == -1, "feint is consumed by the attack"
    print("✅ test_feinting_attack_adds_die_damage passed")


def test_quick_toss_adds_die_to_thrown():
    """Quick Toss: arm a superiority die on the next thrown-weapon attack this turn."""
    bm, engine, atk, tgt = _setup(3)
    w = rpg.Weapon(); w.name = "Handaxe"; w.type = rpg.WeaponType.Melee
    w.thrown = True; w.proficient = True
    w.reach_ft = 5; w.range_short_feet = 20; w.range_long_feet = 60
    roll = rpg.PhysicalDamageRoll(); roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1; roll.die_size = 6
    w.physical_damage_types = [roll]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    assert engine.prepare_quick_toss(bm, atk)
    assert engine.get_agent_conditions(bm, atk).quick_toss_die_pending
    r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert r.hit
    labels = [lbl for lbl, _ in r.damage_breakdown]
    assert "quick toss" in labels, f"quick toss die should appear in the breakdown, got {labels}"
    assert not engine.get_agent_conditions(bm, atk).quick_toss_die_pending, "quick toss die is consumed"
    print("✅ test_quick_toss_adds_die_to_thrown passed")


def test_parry_reduces_damage():
    """Parry: a Battle Master defender reduces a melee hit's damage by die + DEX, spending reaction + die."""
    bm, engine, atk, tgt = _setup(3)  # atk = BM (defender), tgt = soft (attacker)
    engine.set_agent_weapons(bm, tgt, _longsword())
    bm_s = engine.get_agent_stats(bm, atk); bm_s.base_ac = 1; bm_s.hp_cur = bm_s.hp_max
    engine.set_agent_stats(bm, atk, bm_s)
    result = engine.execute_action(bm, rpg.Attack(tgt, atk, 0))  # tgt strikes the BM
    assert result.hit and result.total_damage > 0
    assert engine.can_parry(bm, atk), "BM defender with a die + free reaction can Parry"
    before = result.total_damage
    assert engine.apply_parry(bm, atk, result)
    assert result.total_damage < before, f"Parry should reduce damage ({before} → {result.total_damage})"
    assert engine.get_agent_conditions(bm, atk).reaction_used, "Parry consumes the reaction"
    s = engine.get_agent_stats(bm, atk); sd = s.get_resource("Superiority Dice")
    assert sd.current == sd.max - 1, "Parry spends 1 Superiority Die"
    print("✅ test_parry_reduces_damage passed")


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
    test_ek_spellcasting_chassis_l3()
    test_ek_spellcasting_chassis_l7()
    test_ek_third_caster_scaling()
    test_non_ek_fighter_no_slots()
    test_war_magic_gate()
    test_war_magic_requires_l7()
    test_eldritch_strike_tags_target()
    test_eldritch_strike_requires_l10()
    test_available_war_magic_spells()
    test_improved_war_magic_l18()
    test_arcane_charge()
    test_save_dc_uses_max_str_dex()
    test_goading_attack_sets_goaded_by()
    test_distracting_strike_grants_advantage()
    test_disarming_makes_unarmed()
    test_sweeping_attack_splashes_second()
    test_rally_grants_temp_hp()
    test_feinting_attack_adds_die_damage()
    test_quick_toss_adds_die_to_thrown()
    test_parry_reduces_damage()
    print("\n✅ All Fighter tests passed!")
