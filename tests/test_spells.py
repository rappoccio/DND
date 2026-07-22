#!/usr/bin/env python3
"""
Test suite for Spell Mechanics
Tests spell effects, spell properties, and spell interactions.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg

def test_spell_creation():
    """Test creating a basic spell."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 3
    assert spell.name == "Fireball"
    assert spell.level == 3
    print("✅ Spell created correctly")

def test_spell_range():
    """Test spell range property."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.range = 150
    assert spell.range == 150
    print("✅ Spell range property correct")

def test_spell_area_of_effect():
    """Test spell with area of effect."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.geometry = rpg.SpellGeometry.Sphere
    spell.radius = 20
    assert spell.geometry == rpg.SpellGeometry.Sphere
    assert spell.radius == 20
    print("✅ Area of effect properties correct")

def test_concentration_spell():
    """Test concentration requirement."""
    spell = rpg.Spell()
    spell.name = "Bless"
    spell.requires_concentration = True
    spell.duration = 10
    assert spell.requires_concentration
    assert spell.duration == 10
    print("✅ Concentration spell properties correct")

def test_cantrip():
    """Test cantrip (0-level spell)."""
    spell = rpg.Spell()
    spell.name = "Fire Bolt"
    spell.level = 0
    assert spell.level == 0
    print("✅ Cantrip created correctly")

def test_spell_upcast():
    """Test spell upcast bonus."""
    spell = rpg.Spell()
    spell.name = "Magic Missile"
    spell.level = 1
    spell.upcast_dice_bonus = 1  # +1d4 per upcast level
    assert spell.upcast_dice_bonus == 1
    print("✅ Upcast bonus property correct")

def test_spell_save_ability():
    """Test spell save ability."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.save_ability = rpg.SaveAbility.Dexterity
    assert spell.save_ability == rpg.SaveAbility.Dexterity
    print("✅ Save ability property correct")

def test_spell_requires_sight():
    """Test spell sight requirements."""
    spell = rpg.Spell()
    spell.name = "Magic Missile"
    spell.requires_sight = False  # Can target unseen enemies
    assert not spell.requires_sight

    spell2 = rpg.Spell()
    spell2.name = "Chromatic Orb"
    spell2.requires_sight = True
    assert spell2.requires_sight
    print("✅ Spell sight requirements correct")

def test_spell_requires_los():
    """Test line of sight requirement."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.requires_los = True
    assert spell.requires_los
    print("✅ LOS requirement property correct")

def test_spell_damage_rolls():
    """Test spell damage rolls."""
    spell = rpg.Spell()
    spell.name = "Magic Missile"
    spell.level = 1

    # Create a magic damage roll object
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Force
    dmg.num_dice = 1
    dmg.die_size = 4

    # Verify the damage roll can be created and configured
    assert dmg.type == rpg.MagicDamage.Force, f"Expected Force, got {dmg.type}"
    assert dmg.num_dice == 1, f"Expected 1 die, got {dmg.num_dice}"
    assert dmg.die_size == 4, f"Expected d4, got d{dmg.die_size}"
    print("✅ Magic damage rolls correct")

def test_physical_damage_rolls():
    """Test physical damage rolls."""
    spell = rpg.Spell()
    spell.name = "Shillelagh"

    # Create a physical damage roll object
    dmg = rpg.PhysicalDamageRoll()
    dmg.type = rpg.PhysicalDamage.Bludgeoning
    dmg.num_dice = 1
    dmg.die_size = 8

    # Verify the damage roll can be created and configured
    assert dmg.type == rpg.PhysicalDamage.Bludgeoning, f"Expected Bludgeoning, got {dmg.type}"
    assert dmg.num_dice == 1, f"Expected 1 die, got {dmg.num_dice}"
    assert dmg.die_size == 8, f"Expected d8, got d{dmg.die_size}"
    print("✅ Physical damage rolls correct")

def test_spell_duration():
    """Test spell duration in rounds."""
    spell = rpg.Spell()
    spell.name = "Bless"
    spell.duration = 600  # 10 minutes = 100 rounds
    assert spell.duration == 600
    print("✅ Spell duration property correct")

def test_spell_multiple_targets():
    """Test spell with multiple targets."""
    spell = rpg.Spell()
    spell.name = "Magic Missile"
    spell.num_targets = 3
    spell.targets_per_upcast_level = 1  # +1 missile per upcast
    assert spell.num_targets == 3
    assert spell.targets_per_upcast_level == 1
    print("✅ Multiple targets property correct")

def test_spell_nday_uses():
    """Test N/day spell uses."""
    spell = rpg.Spell()
    spell.name = "Healing Word"
    spell.uses_max = 3  # 3/day
    spell.uses_remaining = 2
    assert spell.uses_max == 3
    assert spell.uses_remaining == 2
    print("✅ N/day uses property correct")

def test_spell_turn_effects():
    """Test effects triggered on turn start/end."""
    spell = rpg.Spell()
    spell.name = "Spike Growth"
    spell.effects_on_begin_turn = False
    spell.effects_on_end_turn = False
    assert not spell.effects_on_begin_turn
    assert not spell.effects_on_end_turn
    print("✅ Turn effects property correct")

def test_spell_terrain_difficulty():
    """Test spell that creates terrain."""
    spell = rpg.Spell()
    spell.name = "Grease"
    spell.terrain_difficulty = rpg.TerrainDifficulty.Slipping
    spell.duration = 60  # 1 minute
    assert spell.terrain_difficulty == rpg.TerrainDifficulty.Slipping
    print("✅ Terrain difficulty property correct")

if __name__ == "__main__":
    tests = [
        test_spell_creation,
        test_spell_range,
        test_spell_area_of_effect,
        test_concentration_spell,
        test_cantrip,
        test_spell_upcast,
        test_spell_save_ability,
        test_spell_requires_sight,
        test_spell_requires_los,
        test_spell_damage_rolls,
        test_physical_damage_rolls,
        test_spell_duration,
        test_spell_multiple_targets,
        test_spell_nday_uses,
        test_spell_turn_effects,
        test_spell_terrain_difficulty,
    ]

    print("Running Spell Mechanics Tests...")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
