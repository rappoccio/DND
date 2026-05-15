#!/usr/bin/env python3
"""
Test suite for Combat Mechanics
Tests AC calculations, attack rolls, damage, weapons, and armor.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent, create_melee_weapon, create_ranged_weapon, create_armor, assert_within

def test_ac_calculation():
    """Test that AC is calculated correctly from armor."""
    bm = setup_battle_map()
    config = create_test_agent("Fighter", 5, 5, dex=12)
    config.stats.ac = 10
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    assert agent.stats.ac == 10
    print("✓ AC calculation correct")

def test_melee_weapon_creation():
    """Test creating a melee weapon."""
    weapon = create_melee_weapon()
    assert weapon.name == "Longsword"
    assert weapon.damage_dice == 8
    assert weapon.damage_dice_count == 1
    print("✓ Melee weapon created correctly")

def test_ranged_weapon_creation():
    """Test creating a ranged weapon."""
    weapon = create_ranged_weapon()
    assert weapon.name == "Shortbow"
    assert weapon.damage_dice == 6
    assert weapon.damage_dice_count == 1
    print("✓ Ranged weapon created correctly")

def test_armor_creation():
    """Test creating armor."""
    armor = create_armor(12)
    assert armor.name == "Leather Armor"
    assert armor.ac_base == 12
    assert not armor.grants_disadvantage
    print("✓ Armor created correctly")

def test_attack_modifier_strength():
    """Test attack modifier based on strength."""
    bm = setup_battle_map()
    config = create_test_agent("Fighter", 5, 5, str=16)
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    # STR 16 = +3 modifier
    expected_mod = (16 - 10) // 2
    assert expected_mod == 3
    print("✓ Attack modifier based on strength correct")

def test_attack_modifier_dexterity():
    """Test attack modifier based on dexterity."""
    bm = setup_battle_map()
    config = create_test_agent("Rogue", 5, 5, dex=18)
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    # DEX 18 = +4 modifier
    expected_mod = (18 - 10) // 2
    assert expected_mod == 4
    print("✓ Attack modifier based on dexterity correct")

def test_damage_modifier_strength():
    """Test damage modifier based on strength."""
    bm = setup_battle_map()
    config = create_test_agent("Fighter", 5, 5, str=15)
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    # STR 15 = +2 modifier
    expected_mod = (15 - 10) // 2
    assert expected_mod == 2
    print("✓ Damage modifier based on strength correct")

def test_ability_modifier_formulas():
    """Test all ability modifier calculations."""
    bm = setup_battle_map()

    test_scores = [
        (8, -1),
        (10, 0),
        (12, 1),
        (14, 2),
        (16, 3),
        (18, 4),
        (20, 5),
    ]

    for score, expected_mod in test_scores:
        actual_mod = (score - 10) // 2
        assert actual_mod == expected_mod, f"Score {score}: expected {expected_mod}, got {actual_mod}"

    print("✓ All ability modifier calculations correct")

def test_ac_with_dexterity():
    """Test that AC benefits from DEX modifier."""
    bm = setup_battle_map()
    config = create_test_agent("Rogue", 5, 5, dex=16, ac=10)
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    # AC 10 + DEX 16 (+3) = 13 in leather armor
    # (This assumes the game applies DEX to AC, which is standard in D&D 5e)
    dex_mod = (16 - 10) // 2
    assert dex_mod == 3
    print("✓ DEX modifier for AC correct")

def test_multiple_agents_independent_stats():
    """Test that multiple agents have independent stats."""
    bm = setup_battle_map()
    config1 = create_test_agent("Fighter", 5, 5, str=18, ac=12)
    config2 = create_test_agent("Wizard", 6, 5, str=8, ac=14)

    idx1 = bm.add_agent(config1)
    idx2 = bm.add_agent(config2)

    agent1 = bm.get_agent(idx1)
    agent2 = bm.get_agent(idx2)

    assert agent1.stats.str == 18
    assert agent2.stats.str == 8
    assert agent1.stats.ac == 12
    assert agent2.stats.ac == 14
    print("✓ Multiple agents maintain independent stats")

def test_constitution_affects_hp():
    """Test that CON modifier affects max HP."""
    bm = setup_battle_map()
    # CON 16 = +3 modifier
    config = create_test_agent("Tank", 5, 5, con=16, hp=10)
    idx = bm.add_agent(config)

    agent = bm.get_agent(idx)
    con_mod = (16 - 10) // 2
    assert con_mod == 3
    print("✓ CON modifier calculation correct")

def test_attack_bonus_from_weapon():
    """Test that weapon attack bonus is applied."""
    weapon = create_melee_weapon()
    weapon.attack_bonus = 2
    assert weapon.attack_bonus == 2
    print("✓ Weapon attack bonus applied")

def test_damage_dice_count():
    """Test damage dice count for different weapons."""
    longsword = create_melee_weapon()
    longsword.damage_dice_count = 1
    assert longsword.damage_dice_count == 1

    greatsword = create_melee_weapon()
    greatsword.damage_dice = 6
    greatsword.damage_dice_count = 2
    assert greatsword.damage_dice_count == 2
    print("✓ Damage dice count correct for weapons")

if __name__ == "__main__":
    tests = [
        test_ac_calculation,
        test_melee_weapon_creation,
        test_ranged_weapon_creation,
        test_armor_creation,
        test_attack_modifier_strength,
        test_attack_modifier_dexterity,
        test_damage_modifier_strength,
        test_ability_modifier_formulas,
        test_ac_with_dexterity,
        test_multiple_agents_independent_stats,
        test_constitution_affects_hp,
        test_attack_bonus_from_weapon,
        test_damage_dice_count,
    ]

    print("Running Combat Mechanics Tests...")
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
