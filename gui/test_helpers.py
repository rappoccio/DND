"""
Helper functions for Python test suite
Provides common setup, utilities, and test data
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg

# Test map and configuration paths
TEST_MAP_PATH = "/Users/rappoccio/Documents/Claude/Projects/DNDGui/DND/maps/TestGrid12x12.png"
TERRAIN_CONFIG_PATH = "/Users/rappoccio/Documents/Claude/Projects/DNDGui/DND/maps/TestGrid12x12_terrain.json"
STATS_PATH = "/Users/rappoccio/Documents/Claude/Projects/DNDGui/DND/sprites/DND2024_MonsterStats.json"

def setup_battle_map():
    """Initialize and analyze a battle map for testing."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()
    bm.detect_walls()
    return bm

def create_test_agent(name, col, row,
                      str=10, dex=10, con=10, intel=10, wis=10, cha=10,
                      hp=10, ac=10):
    """Create a test AgentConfig with sensible defaults."""
    config = rpg.AgentConfig()
    config.name = name
    config.origin = rpg.Cell(col, row)
    config.size = 1
    config.stats.str = str
    config.stats.dex = dex
    config.stats.con = con
    config.stats.intel = intel
    config.stats.wis = wis
    config.stats.cha = cha
    config.stats.max_hp = hp
    config.stats.current_hp = hp
    config.stats.ac = ac
    return config

def assert_within(actual, expected, tolerance, msg=""):
    """Assert that actual is within tolerance of expected."""
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{msg}: expected {expected} ± {tolerance}, got {actual}")

def create_melee_weapon():
    """Create a test melee weapon (longsword equivalent)."""
    weapon = rpg.Weapon()
    weapon.name = "Longsword"
    weapon.damage_dice = 8
    weapon.damage_dice_count = 1
    weapon.damage_modifier = 0
    weapon.attack_bonus = 0
    weapon.range_short_feet = 5
    weapon.range_long_feet = 5
    return weapon

def create_ranged_weapon():
    """Create a test ranged weapon (shortbow equivalent)."""
    weapon = rpg.Weapon()
    weapon.name = "Shortbow"
    weapon.damage_dice = 6
    weapon.damage_dice_count = 1
    weapon.damage_modifier = 0
    weapon.attack_bonus = 0
    weapon.range_short_feet = 80
    weapon.range_long_feet = 320
    return weapon

def create_armor(ac_base=10):
    """Create test armor."""
    armor = rpg.Armor()
    armor.name = "Leather Armor"
    armor.ac_base = ac_base
    armor.grants_disadvantage = False
    return armor
