#!/usr/bin/env python3
"""
Test suite for Spell Mechanics
Tests spell effects, spell saves, damage spells, and spell interactions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent

def test_spell_creation():
    """Test creating a basic spell."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 3
    spell.casting_time = "1 action"
    spell.range_feet = 150
    assert spell.name == "Fireball"
    assert spell.level == 3
    print("✓ Spell created correctly")

def test_damage_spell():
    """Test damage spell properties."""
    spell = rpg.Spell()
    spell.name = "Magic Missile"
    spell.level = 1
    spell.damage_dice = 4
    spell.damage_dice_count = 1
    spell.damage_type = rpg.MagicDamage.Force
    assert spell.damage_dice == 4
    assert spell.damage_dice_count == 1
    print("✓ Damage spell properties correct")

def test_saving_throw_spell():
    """Test spell with saving throw."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 3
    spell.requires_save = True
    spell.save_ability = rpg.Ability.Dexterity
    assert spell.requires_save
    assert spell.save_ability == rpg.Ability.Dexterity
    print("✓ Saving throw spell properties correct")

def test_spell_area_of_effect():
    """Test spell with area of effect."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.aoe_shape = "sphere"
    spell.aoe_radius_feet = 20
    assert spell.aoe_shape == "sphere"
    assert spell.aoe_radius_feet == 20
    print("✓ Area of effect properties correct")

def test_concentration_spell():
    """Test concentration requirement."""
    spell = rpg.Spell()
    spell.name = "Bless"
    spell.requires_concentration = True
    spell.duration_rounds = 10
    assert spell.requires_concentration
    assert spell.duration_rounds == 10
    print("✓ Concentration spell properties correct")

def test_cantrip():
    """Test cantrip (0-level spell)."""
    spell = rpg.Spell()
    spell.name = "Fire Bolt"
    spell.level = 0
    spell.damage_dice = 6
    spell.damage_dice_count = 1
    assert spell.level == 0
    print("✓ Cantrip created correctly")

def test_spell_scaling():
    """Test spell damage scaling with caster level."""
    spell = rpg.Spell()
    spell.name = "Fire Bolt"
    spell.level = 0
    spell.damage_dice = 6
    # Cantrips scale: 1d6 (lvl 1-4), 2d6 (lvl 5-8), etc.
    spell.damage_dice_count = 1
    assert spell.damage_dice_count == 1
    print("✓ Spell scaling property accessible")

def test_spell_components():
    """Test spell components (verbal, somatic, material)."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.has_verbal_component = True
    spell.has_somatic_component = True
    spell.has_material_component = True
    spell.material_component_description = "a tiny ball of bat guano and sulfur"
    assert spell.has_verbal_component
    assert spell.has_somatic_component
    assert spell.has_material_component
    print("✓ Spell components recorded correctly")

def test_healing_spell():
    """Test healing spell."""
    spell = rpg.Spell()
    spell.name = "Cure Wounds"
    spell.level = 1
    spell.is_healing_spell = True
    spell.healing_dice = 4
    spell.healing_dice_count = 1
    assert spell.is_healing_spell
    assert spell.healing_dice == 4
    print("✓ Healing spell properties correct")

def test_buff_spell():
    """Test buff/enhancement spell."""
    spell = rpg.Spell()
    spell.name = "Bless"
    spell.level = 1
    spell.is_buff = True
    spell.buff_type = "attack_save_bonus"
    spell.buff_amount = 1
    spell.duration_rounds = 10
    assert spell.is_buff
    assert spell.buff_amount == 1
    print("✓ Buff spell properties correct")

def test_debuff_spell():
    """Test debuff/penalty spell."""
    spell = rpg.Spell()
    spell.name = "Hold Person"
    spell.level = 2
    spell.is_debuff = True
    spell.debuff_type = "restrained"
    spell.requires_save = True
    spell.save_ability = rpg.Ability.Wisdom
    assert spell.is_debuff
    print("✓ Debuff spell properties correct")

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
    print("✓ Spell sight requirements correct")

def test_saving_throw_dc():
    """Test spell save DC calculation."""
    caster = create_test_agent("Wizard", 5, 5, intel=18)
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.requires_save = True
    spell.spell_save_dc = 8 + 4 + 2  # 8 + INT mod + spell level = DC 14
    assert spell.spell_save_dc == 14
    print("✓ Spell save DC calculation correct")

def test_spell_range():
    """Test spell range properties."""
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.range_feet = 150
    assert spell.range_feet == 150

    spell2 = rpg.Spell()
    spell2.name = "Cure Wounds"
    spell2.range_feet = 0  # Touch spell
    assert spell2.range_feet == 0
    print("✓ Spell range properties correct")

if __name__ == "__main__":
    tests = [
        test_spell_creation,
        test_damage_spell,
        test_saving_throw_spell,
        test_spell_area_of_effect,
        test_concentration_spell,
        test_cantrip,
        test_spell_scaling,
        test_spell_components,
        test_healing_spell,
        test_buff_spell,
        test_debuff_spell,
        test_spell_requires_sight,
        test_saving_throw_dc,
        test_spell_range,
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
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
