"""
Helper functions for Python test suite
Provides common setup, utilities, and test data
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg

# Test map and configuration paths (relative to project root, one level up from gui/)
import os
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)  # Go up from gui/ to project root
TEST_MAP_PATH = os.path.join(_project_root, "maps", "TestGrid12x12.png")
TERRAIN_CONFIG_PATH = os.path.join(_project_root, "maps", "TestGrid12x12_terrain.json")
STATS_PATH = os.path.join(_project_root, "gui", "DND2024_MonsterStats.json")

def setup_battle_map():
    """Initialize and analyze a battle map for testing."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()
    bm.detect_walls()
    return bm

def setup_combat_engine():
    """Create a new CombatEngine with a fixed seed."""
    return rpg.CombatEngine(42)  # Fixed seed for reproducibility

def create_test_agent(name, col, row,
                      str=10, dex=10, con=10, intel=10, wis=10, cha=10,
                      hp=10, ac=10):
    """Create a test AgentConfig with sensible defaults."""
    config = rpg.AgentConfig()
    config.name = name
    config.start_col = col
    config.start_row = row
    config.size = 1
    config.sprite_path = "test.png"
    return config

def add_agent_to_battle(engine, bm, config,
                       str=10, dex=10, con=10, intel=10, wis=10, cha=10,
                       hp=10, ac=10):
    """Add an agent to the battle map with stats."""
    # apply_agent_configs is destructive — it rebuilds ALL placed agents from
    # scratch, wiping any stats/conditions set on previously-added agents.
    # Save them so we can restore after.
    prior_count = len(bm.placed_agents)
    saved_stats = [engine.get_agent_stats(bm, i) for i in range(prior_count)]
    saved_conds = [engine.get_agent_conditions(bm, i) for i in range(prior_count)]

    engine.add_agent_config(bm, config)
    engine.apply_agent_configs(bm)

    # Restore previously-customised stats/conditions.
    for i in range(prior_count):
        engine.set_agent_stats(bm, i, saved_stats[i])
        engine.set_agent_conditions(bm, i, saved_conds[i])

    # Find the newly added agent index
    agents = bm.placed_agents
    idx = len(agents) - 1

    # Create and set stats
    stats = rpg.Stats()
    stats.str = str
    stats.dex = dex
    stats.con = con
    stats.intel = intel
    stats.wis = wis
    stats.cha = cha
    stats.hp_max = hp
    stats.hp_cur = hp
    stats.base_ac = ac
    engine.set_agent_stats(bm, idx, stats)

    return idx

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
