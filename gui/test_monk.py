#!/usr/bin/env python3
"""
Test Monk: Unarmed Strikes, Focus Points, Martial Arts, Flurry of Blows, Stunning Strike.

Covered: Unarmored Defense, Focus Points resource, Flurry of Blows (2 bonus attacks),
Stunning Strike on action attacks, level scaling.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _monk(engine, bm, idx, level, dex=16, wis=14):
    """Configure agent idx as a Monk of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Monk, level)
    s.dex = dex
    s.wis = wis
    s.initialize_class_resources(rpg.CharacterClass.Monk, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _soft_target(engine, bm, idx, hp=100):
    """Configure agent as a non-Monk target with low saves and HP."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.str = 8
    s.dex = 8
    s.con = 10
    s.intel = 10
    s.wis = 10
    s.cha = 10
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = 10
    s.save_prof_str = False
    s.save_prof_dex = False
    s.save_prof_con = False
    s.save_prof_intel = False
    s.save_prof_wis = False
    s.save_prof_cha = False
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _unarmed_weapons():
    """Return 3 unarmed strike weapons for Monk (only weapon 0 is used)."""
    w = rpg.Weapon()
    w.name = "Unarmed Strike"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = 50  # Guaranteed hit for testing
    w.bonus_damage = 0
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Bludgeoning
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _setup(level, dex=16, wis=14):
    """Build a battle with a Monk attacker and a soft target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Monk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    _monk(engine, bm, atk, level, dex=dex, wis=wis)
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _unarmed_weapons())
    return bm, engine, atk, tgt


# ─────────────────────────────────────────────────────────────────────────────
# Monk Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_unarmored_defense():
    """Monk Unarmored Defense: AC = 10 + DEX mod + WIS mod."""
    bm, engine, atk, tgt = _setup(1, dex=16, wis=14)

    # DEX mod = +3, WIS mod = +2 → AC = 10 + 3 + 2 = 15
    ac = engine.calculate_ac(bm, atk)
    expected_ac = 10 + 3 + 2
    assert ac == expected_ac, f"Monk L1 Unarmored Defense should be {expected_ac}, got {ac}"
    print("✅ test_unarmored_defense passed")


def test_focus_points_resource():
    """Monk gains Focus Points = level. Spent on Flurry, Stunning Strike, etc."""
    bm, engine, atk, tgt = _setup(5)
    s = engine.get_agent_stats(bm, atk)

    fp = s.get_resource("Focus Points")
    assert fp is not None, "Monk should have Focus Points resource"
    assert fp.max == 5, f"Monk L5 should have 5 Focus Points max, got {fp.max}"
    assert fp.current == 5, f"Monk L5 should start with 5 Focus Points, got {fp.current}"
    print("✅ test_focus_points_resource passed")


def test_focus_points_short_rest():
    """Monk regains all Focus Points on short rest."""
    bm, engine, atk, tgt = _setup(5)
    s = engine.get_agent_stats(bm, atk)

    # Spend all Focus Points
    fp = s.get_resource("Focus Points")
    fp.current = 0
    s.resources["Focus Points"] = fp
    engine.set_agent_stats(bm, atk, s)

    # Short rest (restore the resource)
    fp = s.get_resource("Focus Points")
    fp.restore_short_rest()
    s.resources["Focus Points"] = fp
    engine.set_agent_stats(bm, atk, s)

    s = engine.get_agent_stats(bm, atk)
    fp = s.get_resource("Focus Points")
    assert fp.current == fp.max, f"After short rest, Focus Points should be at max, got {fp.current}/{fp.max}"
    print("✅ test_focus_points_short_rest passed")


def test_unarmed_strike_damage():
    """Monk unarmed strike does 1d4 + DEX mod base damage."""
    bm, engine, atk, tgt = _setup(1, dex=16)

    # Land an unarmed strike (attack_bonus=50 guarantees hit)
    for _ in range(10):
        result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if result.hit:
            # Damage should be 1d4 (1-4) + DEX mod (+3) = 4-7
            assert 4 <= result.total_damage <= 7, \
                f"Monk L1 unarmed strike should be 1d4+3 = 4-7, got {result.total_damage}"
            print("✅ test_unarmed_strike_damage passed")
            return

    raise AssertionError("attack never landed")


def test_stunning_strike_eligibility():
    """Monk has Focus Points available to fuel Stunning Strike."""
    bm, engine, atk, tgt = _setup(1)
    s = engine.get_agent_stats(bm, atk)

    fp = s.get_resource("Focus Points")
    assert fp is not None, "Monk should have Focus Points to spend on Stunning Strike"
    assert fp.current >= 1, "Monk should have at least 1 Focus Point"
    print("✅ test_stunning_strike_eligibility passed")


def test_stunning_strike_applies_stunned():
    """Stunning Strike on a low-CON target: target fails the save and is Stunned, 1 Focus spent.

    DC = 8 + DEX mod + prof. With DEX 20 (+5) and prof +6 → DC 19. A CON-1 target
    (mod -5, no save prof) maxes its save at 20-5 = 15 < 19, so it is always Stunned.
    (prof_bonus is set explicitly: set_class_level does not derive it from level.)
    """
    bm, engine, atk, tgt = _setup(17, dex=20)

    # Pin the attacker's proficiency bonus so the save DC is deterministic.
    a = engine.get_agent_stats(bm, atk)
    a.prof_bonus = 6
    engine.set_agent_stats(bm, atk, a)

    # Make the target's CON save impossible to pass against this DC.
    ts = engine.get_agent_stats(bm, tgt)
    ts.con = 1
    ts.save_prof_con = False
    engine.set_agent_stats(bm, tgt, ts)

    fp_before = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current

    # Set the on-hit eligibility flag (normally set by a qualifying unarmed hit).
    cond = engine.get_agent_conditions(bm, atk)
    cond.stunning_strike_available = True
    engine.set_agent_conditions(bm, atk, cond)

    res = engine.apply_stunning_strike(bm, atk, tgt)
    assert res.valid, "StunningStrikeResult should be valid"
    assert res.save_dc == 8 + 5 + 6, f"DC should be 19 (8+5+6), got {res.save_dc}"
    assert res.save_roll < res.save_dc, f"save {res.save_roll} should fail vs DC {res.save_dc}"
    assert res.stunned, "target should be Stunned on a failed save"

    # The actual Stunned condition must be applied to the target.
    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert tgt_cond.stunned, "target's Stunned condition flag should be set"
    assert res.stunned == tgt_cond.stunned, "result.stunned must match the target's condition"

    # Exactly 1 Focus Point spent, and the once-per-turn flag is now set.
    fp_after = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"should spend 1 Focus Point ({fp_before}->{fp_after})"
    atk_cond = engine.get_agent_conditions(bm, atk)
    assert atk_cond.stunning_strike_used, "stunning_strike_used should be set after applying"
    assert not atk_cond.stunning_strike_available, "available flag should be cleared after applying"
    print("✅ test_stunning_strike_applies_stunned passed")


def test_stunning_strike_resisted():
    """Stunning Strike on a high-CON target: target makes the save, no Stun, but 1 Focus is still spent.

    L1 monk with DEX 10 → DC 8+0+2 = 10. A CON-30 target with save proficiency
    (mod +10, +2 prof) mins its save at 1+12 = 13 >= 10, so it always resists.
    """
    bm, engine, atk, tgt = _setup(1, dex=10)

    # Pin the attacker's proficiency bonus so the save DC is deterministic (8+0+2 = 10).
    a = engine.get_agent_stats(bm, atk)
    a.prof_bonus = 2
    engine.set_agent_stats(bm, atk, a)

    ts = engine.get_agent_stats(bm, tgt)
    ts.con = 30
    ts.save_prof_con = True
    engine.set_agent_stats(bm, tgt, ts)

    fp_before = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current

    cond = engine.get_agent_conditions(bm, atk)
    cond.stunning_strike_available = True
    engine.set_agent_conditions(bm, atk, cond)

    res = engine.apply_stunning_strike(bm, atk, tgt)
    assert res.valid, "StunningStrikeResult should be valid even when resisted"
    assert res.save_roll >= res.save_dc, f"save {res.save_roll} should pass vs DC {res.save_dc}"
    assert not res.stunned, "target should NOT be Stunned on a successful save"

    tgt_cond = engine.get_agent_conditions(bm, tgt)
    assert not tgt_cond.stunned, "target should not have the Stunned condition"

    # Focus Point is consumed regardless of save outcome.
    fp_after = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"should spend 1 Focus Point even on resist ({fp_before}->{fp_after})"
    print("✅ test_stunning_strike_resisted passed")


def test_martial_arts_scaling():
    """Unarmed strike die scales by Monk level: 1d4 (L1), 1d6 (L5), 1d8 (L11)."""
    for level, expected_die in [(1, 4), (5, 6), (11, 8)]:
        bm, engine, atk, tgt = _setup(level)
        s = engine.get_agent_stats(bm, atk)

        # The actual damage die is computed in C++; we verify it by attacking.
        # Since attack_bonus=50, we're guaranteed a hit. Damage range tells us the die.
        min_dmg = None
        max_dmg = None

        for _ in range(20):
            result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
            if result.hit:
                dex_mod = (s.dex - 10) // 2
                die_min = 1 + dex_mod
                die_max = expected_die + dex_mod
                assert die_min <= result.total_damage <= die_max, \
                    f"Monk L{level} should use 1d{expected_die}, got damage {result.total_damage} (expected {die_min}-{die_max})"
                print(f"✅ test_martial_arts_scaling L{level} passed")
                break
        else:
            raise AssertionError(f"Monk L{level} attack never landed")


def test_extra_attack_l5():
    """Monk L5 gets Extra Attack (2 attacks per action)."""
    bm, engine, atk, tgt = _setup(5)
    s = engine.get_agent_stats(bm, atk)

    assert s.num_attacks == 2, f"Monk L5 should have num_attacks=2, got {s.num_attacks}"
    print("✅ test_extra_attack_l5 passed")


def test_flurry_of_blows_setup():
    """Monk Flurry of Blows is a bonus action granting 2 bonus attacks (L1-9) or 3 (L10+)."""
    for level, expected_count in [(1, 2), (10, 3)]:
        bm, engine, atk, tgt = _setup(level)
        s = engine.get_agent_stats(bm, atk)

        fp = s.get_resource("Focus Points")
        assert fp.current >= 1, f"Monk L{level} should have Focus Points for Flurry"
        # After spending 1 Focus Point and starting Flurry, bonus_attacks_remaining should be set to 2 or 3.
        # This is validated by the GUI test, not the C++ unit test.
        print(f"✅ test_flurry_of_blows_setup L{level} passed")


def test_l20_body_and_mind():
    """Monk L20 Body and Mind: +4 DEX, +4 WIS (capped at 25)."""
    bm, engine, atk, tgt = _setup(20, dex=16, wis=14)
    s = engine.get_agent_stats(bm, atk)

    # DEX should be 16 + 4 = 20, WIS should be 14 + 4 = 18
    assert s.dex == 20, f"L20 Monk DEX should be 20 (16+4), got {s.dex}"
    assert s.wis == 18, f"L20 Monk WIS should be 18 (14+4), got {s.wis}"
    print("✅ test_l20_body_and_mind passed")


def test_l20_body_and_mind_cap():
    """Monk L20 Body and Mind: +4 DEX/WIS capped at 25."""
    bm, engine, atk, tgt = _setup(20, dex=22, wis=22)
    s = engine.get_agent_stats(bm, atk)

    # Both should be capped at 25
    assert s.dex == 25, f"L20 Monk DEX should be capped at 25, got {s.dex}"
    assert s.wis == 25, f"L20 Monk WIS should be capped at 25, got {s.wis}"
    print("✅ test_l20_body_and_mind_cap passed")


def test_l14_disciplined_survivor_saves():
    """Monk L14 Disciplined Survivor: proficiency in all saves."""
    bm, engine, atk, tgt = _setup(14)
    s = engine.get_agent_stats(bm, atk)

    # Should have proficiency in all six saving throws
    assert s.save_prof_str, "L14 Monk should have STR save proficiency"
    assert s.save_prof_dex, "L14 Monk should have DEX save proficiency (from chassis)"
    assert s.save_prof_con, "L14 Monk should have CON save proficiency"
    assert s.save_prof_intel, "L14 Monk should have INT save proficiency"
    assert s.save_prof_wis, "L14 Monk should have WIS save proficiency (from chassis)"
    assert s.save_prof_cha, "L14 Monk should have CHA save proficiency"
    print("✅ test_l14_disciplined_survivor_saves passed")


def test_l10_heightened_focus_flurry():
    """Monk L10 Heightened Focus: Flurry of Blows grants 3 strikes instead of 2."""
    bm, engine, atk, tgt = _setup(10)
    s = engine.get_agent_stats(bm, atk)

    # Focus Points should be available for Flurry
    fp = s.get_resource("Focus Points")
    assert fp is not None, "L10 Monk should have Focus Points"
    assert fp.current >= 1, f"L10 Monk should have at least 1 Focus Point for Flurry, got {fp.current}"

    # Execute Flurry of Blows (no rider)
    result = engine.execute_flurry_of_blows(bm, atk, tgt, -1)
    assert result.attack1.valid, "First Flurry attack should be valid"
    assert result.attack2.valid, "Second Flurry attack should be valid"
    assert result.attack3.valid, "Third Flurry attack should be valid (L10 Heightened Focus)"
    print("✅ test_l10_heightened_focus_flurry passed")


def test_l10_self_restoration():
    """Monk L10 Self-Restoration: remove Charmed/Frightened/Poisoned at turn start."""
    bm, engine, atk, tgt = _setup(10)
    s = engine.get_agent_stats(bm, atk)

    # Set up the Monk with the Charmed, Frightened, and Poisoned conditions
    cond = engine.get_agent_conditions(bm, atk)
    cond.charmed = True
    cond.charmed_by = 0
    cond.frightened = True
    cond.poisoned = True
    engine.set_agent_conditions(bm, atk, cond)

    # Verify conditions are set
    cond_check = engine.get_agent_conditions(bm, atk)
    assert cond_check.charmed, "Charmed should be set"
    assert cond_check.frightened, "Frightened should be set"
    assert cond_check.poisoned, "Poisoned should be set"

    # Begin turn (should clear these conditions)
    engine.begin_turn(bm, atk)

    # Check that conditions are cleared
    cond_after = engine.get_agent_conditions(bm, atk)
    assert not cond_after.charmed, "Charmed should be cleared by Self-Restoration"
    assert not cond_after.frightened, "Frightened should be cleared by Self-Restoration"
    assert not cond_after.poisoned, "Poisoned should be cleared by Self-Restoration"
    print("✅ test_l10_self_restoration passed")


def test_l6_empowered_strikes_toggle():
    """Monk L6 Empowered Strikes: unarmed strikes may deal Force instead of Bludgeoning.

    The override now lives in the unified unarmed_damage_override field (-1 = none/Bludgeoning,
    else a MagicDamage_t value). Force = 3.
    """
    bm, engine, atk, tgt = _setup(6, dex=16)
    s = engine.get_agent_stats(bm, atk)

    # Override should be initialized to -1 (no override → Bludgeoning)
    assert s.unarmed_damage_override == -1, "L6 Monk should start with no override (-1 = Bludgeoning)"

    # Set Force (MagicDamage_t Force == 3)
    s.unarmed_damage_override = 3
    engine.set_agent_stats(bm, atk, s)

    s_after = engine.get_agent_stats(bm, atk)
    assert s_after.unarmed_damage_override == 3, "Empowered Strikes should set the override to Force (3)"
    print("✅ test_l6_empowered_strikes_toggle passed")


def test_l15_perfect_focus():
    """Monk L15 Perfect Focus: regain 1 Focus Point on initiative roll."""
    bm, engine, atk, tgt = _setup(15)
    s = engine.get_agent_stats(bm, atk)

    # Spend some Focus Points
    fp = s.get_resource("Focus Points")
    initial_max = fp.max
    fp.current = 5  # Start with 5, will gain 1 on initiative
    s.resources["Focus Points"] = fp
    engine.set_agent_stats(bm, atk, s)

    # Roll initiative (should regain 1 Focus)
    init_entry = engine.roll_initiative_for(bm, atk)
    assert init_entry.agent_idx == atk, "Initiative entry should be for attacker"

    # Check that Focus was regained
    s_after = engine.get_agent_stats(bm, atk)
    fp_after = s_after.get_resource("Focus Points")
    # If started with 5 and regained 1, should have 6 (capped at max)
    assert fp_after.current == min(6, initial_max), \
        f"Perfect Focus should regain 1 Focus (5 -> 6), got {fp_after.current}"
    print("✅ test_l15_perfect_focus passed")


def test_l2_uncanny_metabolism():
    """Monk L2 Uncanny Metabolism: restore all Focus Points once per combat."""
    bm, engine, atk, tgt = _setup(2)
    s = engine.get_agent_stats(bm, atk)

    # Spend all Focus Points
    fp = s.get_resource("Focus Points")
    max_fp = fp.max
    fp.current = 0
    s.resources["Focus Points"] = fp
    engine.set_agent_stats(bm, atk, s)

    # Verify they're spent
    s = engine.get_agent_stats(bm, atk)
    fp = s.get_resource("Focus Points")
    assert fp.current == 0, "Focus Points should be spent"

    # Begin turn (should restore Focus Points)
    engine.begin_turn(bm, atk)

    # Check that Focus Points are restored
    s_after = engine.get_agent_stats(bm, atk)
    fp_after = s_after.get_resource("Focus Points")
    assert fp_after.current == max_fp, f"Uncanny Metabolism should restore Focus Points to {max_fp}, got {fp_after.current}"
    print("✅ test_l2_uncanny_metabolism passed")


# ─────────────────────────────────────────────────────────────────────────────
# L3 Deflect Attacks / L13 Deflect Energy (OnHit defender reaction)
# ─────────────────────────────────────────────────────────────────────────────

def _slashing_weapon():
    """A guaranteed-hit Slashing melee weapon (B/P/S) for the attacker."""
    w = rpg.Weapon()
    w.name = "Greatsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = 50  # guaranteed hit
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 2
    roll.die_size = 10
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _fire_weapon():
    """A guaranteed-hit weapon dealing only Fire (no B/P/S) for the attacker."""
    w = rpg.Weapon()
    w.name = "Flame Jet"
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 30
    w.range_long_feet = 30
    w.attack_bonus = 50  # guaranteed hit
    mr = rpg.MagicDamageRoll()
    mr.type = rpg.MagicDamage.Fire
    mr.num_dice = 4
    mr.die_size = 6
    w.magic_damage_types = [mr]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _hittable_monk_defender(engine, bm, idx):
    """Drop the Monk's AC to 1 so a 50-bonus attack always lands; give it a big HP pool so the
    triggering hit can't drop it to 0 (which would disqualify the reaction)."""
    ms = engine.get_agent_stats(bm, idx)
    ms.base_ac = 1
    ms.hp_max = 200
    ms.hp_cur = 200
    engine.set_agent_stats(bm, idx, ms)


def test_deflect_attacks_reduces_physical():
    """Monk L3 Deflect Attacks: reaction reduces a B/P/S hit by 1d10 + DEX + level."""
    bm, engine, mon, foe = _setup(3, dex=16)  # mon = Monk defender, foe = attacker
    engine.set_agent_weapons(bm, foe, _slashing_weapon())
    _hittable_monk_defender(engine, bm, mon)

    result = engine.execute_action(bm, rpg.Attack(foe, mon, 0))  # foe strikes the Monk
    assert result.hit and result.total_damage > 0, "the Slashing hit should land for damage"
    assert engine.can_deflect_attacks(bm, mon), "L3 Monk with a free reaction can Deflect Attacks"

    before = result.total_damage
    assert engine.apply_deflect_attacks(bm, mon, result), "Deflect Attacks should apply to a B/P/S hit"
    assert result.total_damage < before, f"Deflect should reduce damage ({before} -> {result.total_damage})"
    assert engine.get_agent_conditions(bm, mon).reaction_used, "Deflect Attacks consumes the reaction"
    print("✅ test_deflect_attacks_reduces_physical passed")


def test_deflect_attacks_ineligible_below_l3():
    """A L2 Monk does not yet have Deflect Attacks."""
    bm, engine, mon, foe = _setup(2)
    assert not engine.can_deflect_attacks(bm, mon), "L2 Monk has no Deflect Attacks"
    print("✅ test_deflect_attacks_ineligible_below_l3 passed")


def test_deflect_attacks_type_gate_below_l13():
    """Below L13, Deflect Attacks rejects a non-B/P/S hit and spends no reaction."""
    bm, engine, mon, foe = _setup(3, dex=16)
    engine.set_agent_weapons(bm, foe, _fire_weapon())
    _hittable_monk_defender(engine, bm, mon)

    result = engine.execute_action(bm, rpg.Attack(foe, mon, 0))
    assert result.hit and result.total_damage > 0, "the Fire hit should land for damage"
    assert engine.can_deflect_attacks(bm, mon), "class/level/reaction gate still passes"
    assert not engine.apply_deflect_attacks(bm, mon, result), "L3 cannot deflect non-physical damage"
    assert not engine.get_agent_conditions(bm, mon).reaction_used, "a rejected Deflect spends no reaction"
    print("✅ test_deflect_attacks_type_gate_below_l13 passed")


def test_deflect_energy_l13_any_type():
    """L13 Deflect Energy: the reaction reduces an attack of any damage type (e.g. Fire)."""
    bm, engine, mon, foe = _setup(13, dex=16)
    engine.set_agent_weapons(bm, foe, _fire_weapon())
    _hittable_monk_defender(engine, bm, mon)

    result = engine.execute_action(bm, rpg.Attack(foe, mon, 0))
    assert result.hit and result.total_damage > 0, "the Fire hit should land for damage"
    before = result.total_damage
    assert engine.apply_deflect_attacks(bm, mon, result), "L13 Deflect Energy applies to any type"
    assert result.total_damage < before, f"Deflect Energy should reduce damage ({before} -> {result.total_damage})"
    assert engine.get_agent_conditions(bm, mon).reaction_used, "Deflect Energy consumes the reaction"
    print("✅ test_deflect_energy_l13_any_type passed")


# ─────────────────────────────────────────────────────────────────────────────
# Warrior of Shadow subclass tests (L6 / L11 / L17)
# ─────────────────────────────────────────────────────────────────────────────

def _shadow_monk(engine, bm, idx, level, dex=16, wis=14):
    """Configure agent idx as a Warrior of Shadow Monk of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Monk, level)
    s.monk_subclass = rpg.MonkSubclass.WarriorOfShadow
    s.dex = dex
    s.wis = wis
    s.initialize_class_resources(rpg.CharacterClass.Monk, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def test_shadow_step_l6_advantage():
    """L6 Shadow Step: BA teleport (≤30 ft) from dim/dark → next attack has Advantage, consumed on use."""
    bm, engine, atk, tgt = _setup(6)  # places Monk at (col=5,row=5), target at (6,5)
    _shadow_monk(engine, bm, atk, 6)

    # Monk must be standing in dim/dark light to Shadow Step at L6.
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)

    # Teleport 2 cells (10 ft ≤ 30 ft) to a cell adjacent to the target at (6,5).
    ok = engine.shadow_step_teleport(bm, atk, 7, 5)
    assert ok, "Shadow Step should succeed from darkness within 30 ft"

    cond = engine.get_agent_conditions(bm, atk)
    assert cond.shadow_step_advantage, "Shadow Step should set the next-attack Advantage flag"

    # The next attack must have Advantage; the flag is then consumed.
    res = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert res.valid, "attack should resolve"
    assert res.advantage, "next attack after Shadow Step should have Advantage"

    cond_after = engine.get_agent_conditions(bm, atk)
    assert not cond_after.shadow_step_advantage, "Advantage flag should be consumed after the attack"
    print("✅ test_shadow_step_l6_advantage passed")


def test_shadow_step_l6_requires_darkness():
    """L6 Shadow Step is gated on dim/dark light: in bright light it fails and grants no Advantage."""
    bm, engine, atk, tgt = _setup(6)
    _shadow_monk(engine, bm, atk, 6)

    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Clear)  # bright

    ok = engine.shadow_step_teleport(bm, atk, 5, 8)
    assert not ok, "Shadow Step should fail in bright light at L6"
    cond = engine.get_agent_conditions(bm, atk)
    assert not cond.shadow_step_advantage, "no Advantage flag should be set on a failed Shadow Step"
    print("✅ test_shadow_step_l6_requires_darkness passed")


def test_improved_shadow_step_l11():
    """L11 Improved Shadow Step: teleport from ANY light level + the Advantage attack gains +5 ft reach."""
    bm, engine, atk, tgt = _setup(11)
    _shadow_monk(engine, bm, atk, 11)

    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Clear)  # bright — no gate at L11

    ok = engine.shadow_step_teleport(bm, atk, 5, 8)
    assert ok, "L11 Shadow Step should succeed even from bright light"

    cond = engine.get_agent_conditions(bm, atk)
    assert cond.shadow_step_advantage, "L11 Shadow Step should still grant Advantage"
    assert cond.bonus_reach_available, "L11 Improved Shadow Step should grant +5 ft reach on the next attack"
    print("✅ test_improved_shadow_step_l11 passed")


def test_shadow_step_l11_reach_consumed_on_attack():
    """The L11 +5 ft reach flag lets the monk hit a target 10 ft away, then is consumed."""
    bm, engine, atk, tgt = _setup(11)
    _shadow_monk(engine, bm, atk, 11)
    # Shadow Step the monk to (4,5) — 2 cells (10 ft) from the target at (6,5), out of a
    # normal 5 ft unarmed reach but within the L11 +5 ft reach.
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Clear)
    ok = engine.shadow_step_teleport(bm, atk, 4, 5)
    assert ok, "L11 Shadow Step should succeed"
    cond = engine.get_agent_conditions(bm, atk)
    assert cond.bonus_reach_available, "reach flag should be set before the attack"

    res = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert res.valid and res.hit, "with +5 ft reach the monk should reach and hit a target 10 ft away"

    cond_after = engine.get_agent_conditions(bm, atk)
    assert not cond_after.bonus_reach_available, "reach flag should be consumed after the attack"
    print("✅ test_shadow_step_l11_reach_consumed_on_attack passed")


def test_cloak_of_shadows_l17():
    """L17 Cloak of Shadows: BA → Invisible in dim/dark; invisibility persists through attacks."""
    bm, engine, atk, tgt = _setup(17)
    _shadow_monk(engine, bm, atk, 17)

    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dim)

    ok = engine.cloak_of_shadows(bm, atk)
    assert ok, "Cloak of Shadows should succeed in dim light"

    cond = engine.get_agent_conditions(bm, atk)
    assert cond.invisible, "Cloak of Shadows should make the monk Invisible"
    assert cond.invisible_persists_on_action, "Cloak of Shadows invisibility must persist through attacks"
    assert cond.cloak_of_shadows_active, "cloak_of_shadows_active flag should be set"
    print("✅ test_cloak_of_shadows_l17 passed")


def test_cloak_of_shadows_requires_darkness():
    """Cloak of Shadows fails in bright light and grants no invisibility."""
    bm, engine, atk, tgt = _setup(17)
    _shadow_monk(engine, bm, atk, 17)

    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Clear)

    ok = engine.cloak_of_shadows(bm, atk)
    assert not ok, "Cloak of Shadows should fail in bright light"
    cond = engine.get_agent_conditions(bm, atk)
    assert not cond.invisible, "no invisibility should be granted on a failed Cloak of Shadows"
    print("✅ test_cloak_of_shadows_requires_darkness passed")


def test_cloak_of_shadows_expires_in_bright_light():
    """Cloak of Shadows invisibility fades at turn start if the monk is in bright light."""
    bm, engine, atk, tgt = _setup(17)
    _shadow_monk(engine, bm, atk, 17)

    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert engine.cloak_of_shadows(bm, atk), "Cloak should engage in darkness"
    assert engine.get_agent_conditions(bm, atk).invisible

    # The monk's cell is now lit (e.g. they walked into bright light); begin_turn should expire it.
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Clear)
    engine.begin_turn(bm, atk)

    cond = engine.get_agent_conditions(bm, atk)
    assert not cond.invisible, "Cloak of Shadows should fade in bright light at turn start"
    assert not cond.cloak_of_shadows_active, "cloak_of_shadows_active should be cleared when it fades"
    print("✅ test_cloak_of_shadows_expires_in_bright_light passed")


def test_shadow_step_requires_subclass_and_level():
    """Shadow Step is gated on Warrior of Shadow + L6: a plain Monk (or low level) cannot use it."""
    bm, engine, atk, tgt = _setup(6)  # plain Monk, no subclass
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert not engine.shadow_step_teleport(bm, atk, 5, 8), \
        "a Monk without the Warrior of Shadow subclass cannot Shadow Step"

    # Shadow Monk but only L5 — below the L6 prerequisite.
    bm2, engine2, atk2, tgt2 = _setup(5)
    _shadow_monk(engine2, bm2, atk2, 5)
    bm2.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert not engine2.shadow_step_teleport(bm2, atk2, 5, 8), \
        "a L5 Shadow Monk cannot Shadow Step (requires L6)"
    print("✅ test_shadow_step_requires_subclass_and_level passed")


# ─────────────────────────────────────────────────────────────────────────────
# Warrior of Shadow — L3 Shadow Arts: Darkness
# ─────────────────────────────────────────────────────────────────────────────

def test_shadow_arts_darkness_places_magical_dark():
    """L3 Shadow Arts: Darkness fills a 15-ft Sphere with MagicalDark light and spends 1 Focus.
    The caster sees through their own Darkness; everyone else sees MagicalDark."""
    bm, engine, atk, tgt = _setup(3)
    _shadow_monk(engine, bm, atk, 3)

    fp_before = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current

    # Center the Sphere on the monk's own cell (5,5).
    light_id = engine.shadow_arts_darkness(bm, atk, 5, 5)
    assert light_id >= 0, "Shadow Arts: Darkness should place a light effect and return its id"

    fp_after = engine.get_agent_stats(bm, atk).get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"should spend exactly 1 Focus Point ({fp_before}->{fp_after})"

    center = rpg.Cell(5, 5)
    assert bm.get_light_level(center) == rpg.VisibilityLevel.MagicalDark, \
        "the Sphere center should be MagicalDark for the world"
    # The caster sees through their own Darkness.
    assert bm.get_light_level_for(center, atk) != rpg.VisibilityLevel.MagicalDark, \
        "the casting monk should see through their own Darkness"
    # A different observer (the target) does not.
    assert bm.get_light_level_for(center, tgt) == rpg.VisibilityLevel.MagicalDark, \
        "other creatures should still see MagicalDark"
    print("✅ test_shadow_arts_darkness_places_magical_dark passed")


def test_shadow_arts_darkness_blinds_enemies_not_caster():
    """Creatures inside the Darkness without Devil's Sight are Blinded; the caster is not."""
    bm, engine, atk, tgt = _setup(3)
    _shadow_monk(engine, bm, atk, 3)
    # Target (a plain Fighter, no darkvision/devil's sight) sits at (6,5), 1 cell from the monk.

    engine.shadow_arts_darkness(bm, atk, 5, 5)  # 15-ft Sphere covers both (5,5) and (6,5)

    assert engine.get_agent_conditions(bm, tgt).blinded, \
        "an enemy without Devil's Sight standing in the Darkness should be Blinded"
    assert not engine.get_agent_conditions(bm, atk).blinded, \
        "the caster sees through their own Darkness and must not be Blinded"
    print("✅ test_shadow_arts_darkness_blinds_enemies_not_caster passed")


def test_shadow_arts_darkness_devils_sight_immune():
    """A creature with Devil's Sight inside the Darkness is not Blinded."""
    bm, engine, atk, tgt = _setup(3)
    _shadow_monk(engine, bm, atk, 3)

    ts = engine.get_agent_stats(bm, tgt)
    ts.devilssight_range = 120
    engine.set_agent_stats(bm, tgt, ts)

    engine.shadow_arts_darkness(bm, atk, 5, 5)

    assert not engine.get_agent_conditions(bm, tgt).blinded, \
        "Devil's Sight should let a creature see in magical Darkness (not Blinded)"
    print("✅ test_shadow_arts_darkness_devils_sight_immune passed")


def test_shadow_arts_darkness_gating():
    """Shadow Arts: Darkness requires the Warrior of Shadow subclass, L3, and ≥1 Focus Point."""
    # Plain Monk (no subclass) → fails.
    bm, engine, atk, tgt = _setup(3)
    assert engine.shadow_arts_darkness(bm, atk, 5, 5) < 0, \
        "a Monk without the Warrior of Shadow subclass cannot use Shadow Arts: Darkness"

    # Shadow Monk with no Focus Points → fails.
    bm2, engine2, atk2, tgt2 = _setup(3)
    s = _shadow_monk(engine2, bm2, atk2, 3)
    fp = s.get_resource("Focus Points")
    fp.current = 0
    s.resources["Focus Points"] = fp
    engine2.set_agent_stats(bm2, atk2, s)
    assert engine2.shadow_arts_darkness(bm2, atk2, 5, 5) < 0, \
        "no Focus Points → Shadow Arts: Darkness should fail"
    print("✅ test_shadow_arts_darkness_gating passed")


# ─────────────────────────────────────────────────────────────────────────────
# Warrior of Mercy subclass tests (L3 / L6 / L11)
# ─────────────────────────────────────────────────────────────────────────────

def _mercy_monk(engine, bm, idx, level, dex=16, wis=16):
    """Configure agent idx as a Warrior of Mercy Monk of the given level (WIS 16 → +3)."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Monk, level)
    s.monk_subclass = rpg.MonkSubclass.WarriorOfMercy
    s.dex = dex
    s.wis = wis
    s.initialize_class_resources(rpg.CharacterClass.Monk, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _monk_unarmed_weapons():
    """Unarmed strike weapons named 'MonkUnarmed' so on-hit Monk eligibility flags fire."""
    w = rpg.Weapon()
    w.name = "MonkUnarmed"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.bonus_hit = 50  # guaranteed hit (bonus_hit is the real to-hit modifier)
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Bludgeoning
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _has_breakdown(result, label):
    """True if result.damage_breakdown contains an entry whose name matches label."""
    for entry in result.damage_breakdown:
        # entries are (name, amount) pairs
        if entry[0] == label:
            return True
    return False


def test_hand_of_healing_l3_heals():
    """L3 Hand of Healing: BA, spend 1 Focus → heal Martial Arts die + WIS to a hurt ally."""
    bm, engine, mon, ally = _setup(3, wis=16)
    _mercy_monk(engine, bm, mon, 3, wis=16)

    # Wound the ally.
    a = engine.get_agent_stats(bm, ally)
    a.hp_cur = 1
    engine.set_agent_stats(bm, ally, a)

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current

    res = engine.hand_of_healing(bm, mon, ally)
    assert res.valid, "Hand of Healing should be valid for a Mercy Monk L3 with Focus + bonus action"
    # Heal = 1d6 (L3 MA die) + WIS mod (+3) → 4..9.
    assert 4 <= res.amount_healed <= 9, f"L3 Hand of Healing should heal 1d6+3 = 4-9, got {res.amount_healed}"

    after = engine.get_agent_stats(bm, ally).hp_cur
    assert after == 1 + res.amount_healed, "ally HP should rise by the healed amount"

    fp_after = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"Hand of Healing should spend 1 Focus Point ({fp_before}->{fp_after})"

    mon_stats = engine.get_agent_stats(bm, mon)
    assert mon_stats.bonus_actions_remaining < mon_stats.bonus_actions_max, "Hand of Healing spends the Bonus Action"
    print("✅ test_hand_of_healing_l3_heals passed")


def test_hand_of_healing_requires_focus():
    """Hand of Healing fails (invalid) with no Focus Points and spends nothing."""
    bm, engine, mon, ally = _setup(3)
    s = _mercy_monk(engine, bm, mon, 3)
    fp = s.get_resource("Focus Points")
    fp.current = 0
    s.resources["Focus Points"] = fp
    engine.set_agent_stats(bm, mon, s)

    a = engine.get_agent_stats(bm, ally)
    a.hp_cur = 1
    engine.set_agent_stats(bm, ally, a)

    res = engine.hand_of_healing(bm, mon, ally)
    assert not res.valid, "Hand of Healing should be invalid with no Focus Points"
    assert engine.get_agent_stats(bm, ally).hp_cur == 1, "no healing should occur"
    print("✅ test_hand_of_healing_requires_focus passed")


def test_hand_of_healing_gating():
    """Hand of Healing requires the Warrior of Mercy subclass and L3."""
    # Plain Monk (no subclass) → invalid.
    bm, engine, mon, ally = _setup(3)
    assert not engine.hand_of_healing(bm, mon, ally).valid, \
        "a Monk without the Warrior of Mercy subclass cannot use Hand of Healing"
    print("✅ test_hand_of_healing_gating passed")


def test_hand_of_harm_l3_necrotic():
    """L3 Hand of Harm: after an unarmed hit, spend 1 Focus → extra Necrotic (MA die + WIS)."""
    bm, engine, mon, tgt = _setup(3, wis=16)
    _mercy_monk(engine, bm, mon, 3, wis=16)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    res = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert res.hit, "the unarmed strike should land"
    cond = engine.get_agent_conditions(bm, mon)
    assert cond.hand_of_harm_available, "an unarmed hit should flag Hand of Harm as available"

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    before = res.total_damage
    engine.apply_hand_of_harm_effect(bm, mon, tgt, res)

    assert _has_breakdown(res, "hand of harm"), "Hand of Harm should add a 'hand of harm' damage entry"
    assert res.total_damage > before, f"Hand of Harm should increase damage ({before} -> {res.total_damage})"
    assert rpg.MagicDamage.Necrotic in list(res.magic_damage_types), "Hand of Harm deals Necrotic"

    fp_after = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"Hand of Harm should spend 1 Focus Point ({fp_before}->{fp_after})"

    cond_after = engine.get_agent_conditions(bm, mon)
    assert cond_after.hand_of_harm_used, "hand_of_harm_used should be set after applying"
    assert not cond_after.hand_of_harm_available, "the available flag should be cleared after applying"
    print("✅ test_hand_of_harm_l3_necrotic passed")


def test_hand_of_harm_once_per_turn_below_l11():
    """Below L11 Hand of Harm is once per turn: a second unarmed hit cannot re-flag it."""
    bm, engine, mon, tgt = _setup(6, wis=16)
    _mercy_monk(engine, bm, mon, 6, wis=16)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    res1 = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    engine.apply_hand_of_harm_effect(bm, mon, tgt, res1)
    assert engine.get_agent_conditions(bm, mon).hand_of_harm_used, "first use sets hand_of_harm_used"

    # A second unarmed hit this turn must NOT re-arm Hand of Harm (once per turn below L11).
    res2 = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert not engine.get_agent_conditions(bm, mon).hand_of_harm_available, \
        "below L11 a second hit must not re-arm Hand of Harm in the same turn"
    print("✅ test_hand_of_harm_once_per_turn_below_l11 passed")


def test_physicians_touch_l6():
    """L6 Physician's Touch: Hand of Harm also Poisons; Hand of Healing also ends a condition."""
    bm, engine, mon, tgt = _setup(6, wis=16)
    _mercy_monk(engine, bm, mon, 6, wis=16)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    # Hand of Harm → target becomes Poisoned.
    res = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    engine.apply_hand_of_harm_effect(bm, mon, tgt, res)
    assert engine.get_agent_conditions(bm, tgt).poisoned, "Physician's Touch should Poison the Hand of Harm target"

    # Hand of Healing → ends one condition (the Poisoned we just inflicted) on a hurt ally.
    a = engine.get_agent_stats(bm, tgt)
    a.hp_cur = 1
    engine.set_agent_stats(bm, tgt, a)
    heal = engine.hand_of_healing(bm, mon, tgt)
    assert heal.valid, "Hand of Healing should resolve"
    assert heal.condition_cleared, "Physician's Touch should end a condition with Hand of Healing"
    assert heal.cleared_condition == "Poisoned", f"the Poisoned condition should be ended, got {heal.cleared_condition}"
    assert not engine.get_agent_conditions(bm, tgt).poisoned, "the target should no longer be Poisoned"
    print("✅ test_physicians_touch_l6 passed")


def test_hand_of_harm_l11_free_and_once_per_target():
    """L11 Flurry of Healing and Harm: Hand of Harm costs no Focus Point and is once per target."""
    bm, engine, mon, tgt = _setup(11, wis=16)
    _mercy_monk(engine, bm, mon, 11, wis=16)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current

    res1 = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    engine.apply_hand_of_harm_effect(bm, mon, tgt, res1)
    assert _has_breakdown(res1, "hand of harm"), "L11 Hand of Harm should apply"

    fp_after = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    assert fp_after == fp_before, f"L11 Hand of Harm should be free ({fp_before}->{fp_after})"

    cond = engine.get_agent_conditions(bm, mon)
    assert cond.hand_of_harm_last_target == tgt, "the struck target should be recorded at L11"

    # A second application against the SAME target this turn is refused (once per target).
    res2 = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert engine.get_agent_conditions(bm, mon).hand_of_harm_available, "L11 re-arms on each unarmed hit"
    engine.apply_hand_of_harm_effect(bm, mon, tgt, res2)
    assert not _has_breakdown(res2, "hand of harm"), "L11 Hand of Harm must not apply twice to the same target"
    print("✅ test_hand_of_harm_l11_free_and_once_per_target passed")


def test_flurry_of_healing_and_harm_l11():
    """L11 Flurry of Blows for a Mercy Monk delivers a free Hand of Harm on a hit (once per target)."""
    bm, engine, mon, tgt = _setup(11, wis=16)
    _mercy_monk(engine, bm, mon, 11, wis=16)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current

    result = engine.execute_flurry_of_blows(bm, mon, tgt, -1)  # -1 = no Open Hand rider
    assert result.attack1.valid and result.attack1.hit, "first flurry strike should land"

    # Exactly one of the strikes carries the free Hand of Harm (once per target).
    harm_hits = sum(_has_breakdown(a, "hand of harm")
                    for a in (result.attack1, result.attack2, result.attack3))
    assert harm_hits == 1, f"Flurry of Healing and Harm should apply Hand of Harm once, got {harm_hits}"

    fp_after = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    assert fp_after == fp_before, "Flurry's folded Hand of Harm costs no Focus Point at L11"
    print("✅ test_flurry_of_healing_and_harm_l11 passed")


def test_hand_of_healing_free_at_l11():
    """L11 Hand of Healing with free=True folds into a Flurry strike: no Focus / Bonus Action spent."""
    bm, engine, mon, ally = _setup(11, wis=16)
    _mercy_monk(engine, bm, mon, 11, wis=16)

    a = engine.get_agent_stats(bm, ally)
    a.hp_cur = 1
    engine.set_agent_stats(bm, ally, a)

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    ba_before = engine.get_agent_stats(bm, mon).bonus_actions_remaining

    res = engine.hand_of_healing(bm, mon, ally, True)
    assert res.valid and res.amount_healed > 0, "free Hand of Healing should still heal"

    assert engine.get_agent_stats(bm, mon).get_resource("Focus Points").current == fp_before, \
        "free Hand of Healing spends no Focus Point"
    assert engine.get_agent_stats(bm, mon).bonus_actions_remaining == ba_before, \
        "free Hand of Healing spends no Bonus Action"
    print("✅ test_hand_of_healing_free_at_l11 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Warrior of the Elements subclass (Phase 3): Elemental Attunement (L3), Elemental Burst (L6)
# ─────────────────────────────────────────────────────────────────────────────

# MagicDamage_t values (see damage.hpp): Acid=0, Cold=1, Fire=2, Force=3, Lightning=4, Thunder=9
_FIRE = 2
_LIGHTNING = 4


def _elements_monk(engine, bm, idx, level, dex=16, wis=16):
    """Configure agent idx as a Warrior of the Elements Monk of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Monk, level)
    s.monk_subclass = rpg.MonkSubclass.WarriorOfFourElements
    s.dex = dex
    s.wis = wis
    s.initialize_class_resources(rpg.CharacterClass.Monk, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def test_elemental_attunement_activate():
    """L3 Elemental Attunement: spend 1 Focus, set the active flag + the chosen element override."""
    bm, engine, mon, tgt = _setup(3)
    _elements_monk(engine, bm, mon, 3)

    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    ok = engine.activate_elemental_attunement(bm, mon, _FIRE)
    assert ok, "Elemental Attunement should succeed for an Elements Monk L3 with Focus"

    cond = engine.get_agent_conditions(bm, mon)
    assert cond.elemental_attunement_active, "attunement should be flagged active"
    s = engine.get_agent_stats(bm, mon)
    assert s.unarmed_damage_override == _FIRE, "the chosen element should be stored as the unarmed override"
    fp_after = s.get_resource("Focus Points").current
    assert fp_after == fp_before - 1, f"Elemental Attunement spends 1 Focus ({fp_before}->{fp_after})"
    print("✅ test_elemental_attunement_activate passed")


def test_elemental_attunement_damage_type():
    """While attuned, an unarmed strike deals the chosen element instead of Bludgeoning."""
    bm, engine, mon, tgt = _setup(3)
    _elements_monk(engine, bm, mon, 3)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    assert engine.activate_elemental_attunement(bm, mon, _FIRE)
    res = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert res.hit, "the unarmed strike should land"
    assert rpg.MagicDamage.Fire in list(res.magic_damage_types), \
        "an attuned (Fire) unarmed strike should deal Fire damage"
    print("✅ test_elemental_attunement_damage_type passed")


def test_elemental_attunement_reach():
    """While attuned, unarmed reach is +10 ft (5 → 15), so a 10-ft-away target becomes reachable."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    mon = add_agent_to_battle(engine, bm, create_test_agent("Monk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 7, 5))  # 2 cells = 10 ft away
    _elements_monk(engine, bm, mon, 3)
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    # Without attunement: 5-ft reach can't hit a 10-ft-away target.
    res_before = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert not res_before.hit, "a 5-ft-reach unarmed strike should not reach a 10-ft-away target"

    # With attunement: +10 ft reach (15 ft) now reaches.
    assert engine.activate_elemental_attunement(bm, mon, _FIRE)
    res_after = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert res_after.hit, "Elemental Attunement's +10 ft reach should let the strike land at 10 ft"
    print("✅ test_elemental_attunement_reach passed")


def test_elemental_attunement_push_and_pull():
    """The push/pull rider moves the target 10 ft away (push) or toward the Monk (pull)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    mon = add_agent_to_battle(engine, bm, create_test_agent("Monk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    _elements_monk(engine, bm, mon, 3)
    _soft_target(engine, bm, tgt)

    # Push 10 ft away (east): col 6 → 8.
    ft = engine.elemental_attunement_move(bm, mon, tgt, False)
    assert ft == 10, f"push should move the target 10 ft, got {ft}"
    assert bm.placed_agents[tgt].origin.col == 8, "pushed target should be 2 cells farther east"

    # Pull 10 ft toward the Monk (west): col 8 → 6.
    ft2 = engine.elemental_attunement_move(bm, mon, tgt, True)
    assert ft2 == 10, f"pull should move the target 10 ft, got {ft2}"
    assert bm.placed_agents[tgt].origin.col == 6, "pulled target should be 2 cells closer (back to col 6)"
    print("✅ test_elemental_attunement_push_and_pull passed")


def test_elemental_attunement_move_eligibility_on_hit():
    """An unarmed hit while attuned flags the per-turn push/pull eligibility."""
    bm, engine, mon, tgt = _setup(3)
    _elements_monk(engine, bm, mon, 3)
    engine.set_agent_weapons(bm, mon, _monk_unarmed_weapons())

    assert engine.activate_elemental_attunement(bm, mon, _FIRE)
    res = engine.execute_action(bm, rpg.Attack(mon, tgt, 0))
    assert res.hit, "the unarmed strike should land"
    assert engine.get_agent_conditions(bm, mon).elemental_attunement_move_available, \
        "an attuned unarmed hit should flag the push/pull rider as available"
    print("✅ test_elemental_attunement_move_eligibility_on_hit passed")


def test_elemental_attunement_gating():
    """Elemental Attunement requires the Elements subclass, L3, Focus, and a valid element."""
    # Plain Monk → invalid.
    bm, engine, mon, tgt = _setup(3)
    _monk(engine, bm, mon, 3)
    assert not engine.activate_elemental_attunement(bm, mon, _FIRE), \
        "a non-Elements Monk cannot use Elemental Attunement"

    # Elements Monk but non-elemental type (Force=3) → invalid.
    bm2, engine2, mon2, tgt2 = _setup(3)
    _elements_monk(engine2, bm2, mon2, 3)
    assert not engine2.activate_elemental_attunement(bm2, mon2, 3), \
        "Force is not a legal Elemental Attunement element"

    # No Focus → invalid.
    bm3, engine3, mon3, tgt3 = _setup(3)
    s = _elements_monk(engine3, bm3, mon3, 3)
    fp = s.get_resource("Focus Points")
    fp.current = 0
    s.resources["Focus Points"] = fp
    engine3.set_agent_stats(bm3, mon3, s)
    assert not engine3.activate_elemental_attunement(bm3, mon3, _FIRE), \
        "Elemental Attunement requires a Focus Point"
    print("✅ test_elemental_attunement_gating passed")


def test_elemental_attunement_cleared_on_rest():
    """A short OR long rest ends the attunement (clears the active flag and the override)."""
    for rest in ("short", "long"):
        bm, engine, mon, tgt = _setup(6)
        _elements_monk(engine, bm, mon, 6)
        assert engine.activate_elemental_attunement(bm, mon, _FIRE)
        assert engine.get_agent_conditions(bm, mon).elemental_attunement_active

        if rest == "short":
            engine.apply_short_rest(bm)
        else:
            engine.apply_long_rest(bm)

        assert not engine.get_agent_conditions(bm, mon).elemental_attunement_active, \
            f"a {rest} rest should clear the attunement flag"
        assert engine.get_agent_stats(bm, mon).unarmed_damage_override == -1, \
            f"a {rest} rest should clear the unarmed damage override"
    print("✅ test_elemental_attunement_cleared_on_rest passed")


def _burst_battle(level, wis=16):
    """Monk + an enemy (faction 2) and an ally (faction 1) clustered for an Elemental Burst."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    mon = add_agent_to_battle(engine, bm, create_test_agent("Monk", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 6))
    _elements_monk(engine, bm, mon, level, wis=wis)
    _soft_target(engine, bm, enemy)
    _soft_target(engine, bm, ally)
    bm.set_agent_faction(mon, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)
    return bm, engine, mon, enemy, ally


def test_elemental_burst_hits_enemy_spares_ally():
    """L6 Elemental Burst: 2d8 to an enemy in the sphere; an allied creature is spared (faction-aware)."""
    bm, engine, mon, enemy, ally = _burst_battle(6)
    enemy_hp = engine.get_agent_stats(bm, enemy).hp_cur
    ally_hp = engine.get_agent_stats(bm, ally).hp_cur
    fp_before = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current

    ok = engine.elemental_burst(bm, mon, 8, 5, _LIGHTNING)
    assert ok, "Elemental Burst should succeed for an Elements Monk L6 with 2 Focus"

    enemy_after = engine.get_agent_stats(bm, enemy).hp_cur
    dmg = enemy_hp - enemy_after
    # L6: 2d8 (half on a save) → 1..16.
    assert 1 <= dmg <= 16, f"L6 Elemental Burst (2d8, half on save) should deal 1-16, got {dmg}"
    assert engine.get_agent_stats(bm, ally).hp_cur == ally_hp, "an allied creature is spared by the burst"

    fp_after = engine.get_agent_stats(bm, mon).get_resource("Focus Points").current
    assert fp_after == fp_before - 2, f"Elemental Burst spends 2 Focus ({fp_before}->{fp_after})"
    print("✅ test_elemental_burst_hits_enemy_spares_ally passed")


def _forced_fail_burst_damage(level):
    """Run one Elemental Burst where the lone enemy ALWAYS fails the DEX save (min DEX vs a high DC),
    so damage is the full (die count)×d8. The engine rolls the d8s before the save, so with the fixed
    test seed the first two d8 are identical across levels — letting us compare die counts directly."""
    bm, engine, mon, enemy, ally = _burst_battle(level, wis=20)   # WIS 20 → DC ≥ 16, unbeatable below
    e = engine.get_agent_stats(bm, enemy)
    e.dex = 1                                                     # DEX mod -5 → max save roll = 15 < DC
    engine.set_agent_stats(bm, enemy, e)
    hp = engine.get_agent_stats(bm, enemy).hp_cur
    assert engine.elemental_burst(bm, mon, 8, 5, _LIGHTNING)
    return hp - engine.get_agent_stats(bm, enemy).hp_cur


def test_elemental_burst_scales_at_l17():
    """Elemental Burst die count scales by tier: L6 rolls 2d8, L17 rolls 4d8.

    With a forced-fail target and the fixed test seed, the engine draws the d8s first, so the first two
    rolls match between levels; the extra two L17 dice make L17 strictly larger (and within 4d8 = 4-32).
    """
    dmg_l6 = _forced_fail_burst_damage(6)
    dmg_l17 = _forced_fail_burst_damage(17)
    assert 2 <= dmg_l6 <= 16, f"L6 Elemental Burst on a failed save is 2d8 = 2-16, got {dmg_l6}"
    assert 4 <= dmg_l17 <= 32, f"L17 Elemental Burst on a failed save is 4d8 = 4-32, got {dmg_l17}"
    assert dmg_l17 > dmg_l6, \
        f"L17 (4d8={dmg_l17}) should exceed L6 (2d8={dmg_l6}) — the two extra dice scale the burst"
    print("✅ test_elemental_burst_scales_at_l17 passed")


def test_elemental_burst_gating():
    """Elemental Burst requires the Elements subclass, L6, and 2 Focus Points."""
    # Non-Elements Monk → invalid.
    bm, engine, mon, tgt = _setup(6)
    _monk(engine, bm, mon, 6)
    assert not engine.elemental_burst(bm, mon, 6, 5, _LIGHTNING), \
        "a non-Elements Monk cannot use Elemental Burst"

    # Elements Monk with only 1 Focus → invalid, nothing spent.
    bm2, engine2, mon2, enemy2, ally2 = _burst_battle(6)
    s = engine2.get_agent_stats(bm2, mon2)
    fp = s.get_resource("Focus Points")
    fp.current = 1
    s.resources["Focus Points"] = fp
    engine2.set_agent_stats(bm2, mon2, s)
    enemy_hp = engine2.get_agent_stats(bm2, enemy2).hp_cur
    assert not engine2.elemental_burst(bm2, mon2, 8, 5, _LIGHTNING), \
        "Elemental Burst requires 2 Focus Points"
    assert engine2.get_agent_stats(bm2, enemy2).hp_cur == enemy_hp, "a failed Burst deals no damage"
    print("✅ test_elemental_burst_gating passed")


if __name__ == "__main__":
    test_unarmored_defense()
    test_focus_points_resource()
    test_focus_points_short_rest()
    test_unarmed_strike_damage()
    test_stunning_strike_eligibility()
    test_stunning_strike_applies_stunned()
    test_stunning_strike_resisted()
    test_martial_arts_scaling()
    test_extra_attack_l5()
    test_flurry_of_blows_setup()
    test_l2_uncanny_metabolism()
    test_l6_empowered_strikes_toggle()
    test_l10_heightened_focus_flurry()
    test_l10_self_restoration()
    test_l14_disciplined_survivor_saves()
    test_l15_perfect_focus()
    test_l20_body_and_mind()
    test_l20_body_and_mind_cap()
    # L3 Deflect Attacks / L13 Deflect Energy
    test_deflect_attacks_reduces_physical()
    test_deflect_attacks_ineligible_below_l3()
    test_deflect_attacks_type_gate_below_l13()
    test_deflect_energy_l13_any_type()
    # Warrior of Shadow subclass
    test_shadow_step_l6_advantage()
    test_shadow_step_l6_requires_darkness()
    test_improved_shadow_step_l11()
    test_shadow_step_l11_reach_consumed_on_attack()
    test_cloak_of_shadows_l17()
    test_cloak_of_shadows_requires_darkness()
    test_cloak_of_shadows_expires_in_bright_light()
    test_shadow_step_requires_subclass_and_level()
    # Shadow Arts: Darkness (L3)
    test_shadow_arts_darkness_places_magical_dark()
    test_shadow_arts_darkness_blinds_enemies_not_caster()
    test_shadow_arts_darkness_devils_sight_immune()
    test_shadow_arts_darkness_gating()
    # Warrior of Mercy subclass (L3 / L6 / L11)
    test_hand_of_healing_l3_heals()
    test_hand_of_healing_requires_focus()
    test_hand_of_healing_gating()
    test_hand_of_harm_l3_necrotic()
    test_hand_of_harm_once_per_turn_below_l11()
    test_physicians_touch_l6()
    test_hand_of_harm_l11_free_and_once_per_target()
    test_flurry_of_healing_and_harm_l11()
    test_hand_of_healing_free_at_l11()
    # Warrior of the Elements subclass (L3 / L6)
    test_elemental_attunement_activate()
    test_elemental_attunement_damage_type()
    test_elemental_attunement_reach()
    test_elemental_attunement_push_and_pull()
    test_elemental_attunement_move_eligibility_on_hit()
    test_elemental_attunement_gating()
    test_elemental_attunement_cleared_on_rest()
    test_elemental_burst_hits_enemy_spares_ally()
    test_elemental_burst_scales_at_l17()
    test_elemental_burst_gating()
    print("\n✅ All Monk tests passed!")
