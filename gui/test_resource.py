#!/usr/bin/env python3
"""
Test Resource system for class abilities (Rage, Ki, Sorcery Points, Channel Divinity, etc.)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_resource_spend():
    """Test spending a resource"""
    res = rpg.Resource("Rage", 2)
    assert res.current == 2, f"Expected current=2, got {res.current}"
    assert res.spend(1) == True, "Failed to spend 1 Rage"
    assert res.current == 1, f"Expected current=1 after spend, got {res.current}"
    assert res.spend(2) == False, "Incorrectly spent more than available"
    assert res.current == 1, f"Current should still be 1, got {res.current}"
    print("✅ test_resource_spend passed")

def test_resource_gain():
    """Test gaining a resource"""
    res = rpg.Resource("Ki", 10, 0)
    res.short_rest_regen = 5
    res.spend(3)
    assert res.current == 7, f"Expected 7 after spending 3, got {res.current}"
    res.gain(2)
    assert res.current == 9, f"Expected 9 after gaining 2, got {res.current}"
    res.gain(2)  # Should cap at max
    assert res.current == 10, f"Expected 10 (capped at max), got {res.current}"
    print("✅ test_resource_gain passed")

def test_resource_long_rest():
    """Test resource restoration on long rest"""
    res = rpg.Resource("Rage", 2)
    res.long_rest_regen = 2
    res.spend(1)
    assert res.current == 1, f"Expected 1 after spend, got {res.current}"
    res.restore_long_rest()
    assert res.current == 2, f"Expected 2 after long rest, got {res.current}"
    print("✅ test_resource_long_rest passed")

def test_resource_short_rest():
    """Test partial restoration on short rest"""
    res = rpg.Resource("Ki", 10, 0)
    res.short_rest_regen = 4
    res.spend(6)
    assert res.current == 4, f"Expected 4 after spend, got {res.current}"
    res.restore_short_rest()
    assert res.current == 8, f"Expected 8 (4+4), got {res.current}"
    print("✅ test_resource_short_rest passed")

def test_resource_duration():
    """Test duration-based resource (Rage)"""
    res = rpg.Resource("Rage", 2, 10)  # 10-turn duration
    assert res.is_active() == False, "Rage should not be active initially"
    res.reset_duration()
    assert res.is_active() == True, "Rage should be active after reset_duration()"
    assert res.duration_remaining == 10, f"Expected duration_remaining=10, got {res.duration_remaining}"

    for i in range(10):
        res.tick_duration()
    assert res.is_active() == False, f"Rage should no longer be active after 10 ticks"
    assert res.duration_remaining == 0, f"Expected duration_remaining=0, got {res.duration_remaining}"
    print("✅ test_resource_duration passed")

def test_resource_queries():
    """Test resource query methods"""
    res = rpg.Resource("Sorcery Points", 5)
    assert res.is_full() == True, "Should be full initially"
    assert res.is_empty() == False, "Should not be empty"

    res.spend(5)
    assert res.is_empty() == True, "Should be empty after spending all"
    assert res.is_full() == False, "Should not be full"
    print("✅ test_resource_queries passed")

def test_barbarian_resources_level_1():
    """Test Barbarian resource setup at level 1"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Barbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.set_class_level(rpg.CharacterClass.Barbarian, 1)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, idx, stats)

    rage = stats.get_resource("Rage")
    assert rage is not None, "Rage resource not found"
    assert rage.current == 2, f"Expected current=2, got {rage.current}"
    assert rage.max == 2, f"Expected max=2, got {rage.max}"
    assert rage.duration == 10, f"Expected duration=10, got {rage.duration}"
    assert rage.short_rest_regen == 0, f"Expected short_rest_regen=0, got {rage.short_rest_regen}"
    assert rage.long_rest_regen == 2, f"Expected long_rest_regen=2, got {rage.long_rest_regen}"
    print("✅ test_barbarian_resources_level_1 passed")

def test_barbarian_resources_level_17():
    """Test Barbarian resource setup at level 17"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Barbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.set_class_level(rpg.CharacterClass.Barbarian, 17)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 17)
    engine.set_agent_stats(bm, idx, stats)

    rage = stats.get_resource("Rage")
    assert rage is not None, "Rage resource not found"
    assert rage.max == 6, f"Expected max=6 at level 17, got {rage.max}"
    print("✅ test_barbarian_resources_level_17 passed")

def test_monk_resources():
    """Test Monk Ki resources"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Monk", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.set_class_level(rpg.CharacterClass.Monk, 5)
    stats.initialize_class_resources(rpg.CharacterClass.Monk, 5)
    engine.set_agent_stats(bm, idx, stats)

    ki = stats.get_resource("Ki")
    assert ki is not None, "Ki resource not found"
    assert ki.current == 5, f"Expected current=5, got {ki.current}"
    assert ki.max == 5, f"Expected max=5, got {ki.max}"
    assert ki.short_rest_regen == 5, f"Expected short_rest_regen=5, got {ki.short_rest_regen}"
    print("✅ test_monk_resources passed")

def test_sorcerer_resources():
    """Test Sorcerer Sorcery Points"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Sorcerer", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.set_class_level(rpg.CharacterClass.Sorcerer, 10)
    stats.initialize_class_resources(rpg.CharacterClass.Sorcerer, 10)
    engine.set_agent_stats(bm, idx, stats)

    sp = stats.get_resource("Sorcery Points")
    assert sp is not None, "Sorcery Points resource not found"
    assert sp.current == 10, f"Expected current=10, got {sp.current}"
    assert sp.max == 10, f"Expected max=10, got {sp.max}"
    assert sp.short_rest_regen == 0, f"Expected short_rest_regen=0, got {sp.short_rest_regen}"
    print("✅ test_sorcerer_resources passed")

def test_tick_resource_durations():
    """Test ticking multiple resource durations"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Barbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.set_class_level(rpg.CharacterClass.Barbarian, 1)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, idx, stats)

    rage = stats.get_resource("Rage")
    rage.reset_duration()
    assert rage.is_active() == True, "Rage should be active"

    # Tick 5 times
    for _ in range(5):
        stats.tick_resource_durations()

    assert rage.duration_remaining == 5, f"Expected 5 ticks remaining, got {rage.duration_remaining}"
    assert rage.is_active() == True, "Rage should still be active"

    # Tick remaining 5 times
    for _ in range(5):
        stats.tick_resource_durations()

    assert rage.duration_remaining == 0, f"Expected 0 ticks remaining, got {rage.duration_remaining}"
    assert rage.is_active() == False, "Rage should no longer be active"
    print("✅ test_tick_resource_durations passed")

def main():
    print("Running Resource system tests...")
    print()

    test_resource_spend()
    test_resource_gain()
    test_resource_long_rest()
    test_resource_short_rest()
    test_resource_duration()
    test_resource_queries()
    test_barbarian_resources_level_1()
    test_barbarian_resources_level_17()
    test_monk_resources()
    test_sorcerer_resources()
    test_tick_resource_durations()

    print()
    print("=" * 60)
    print("✅ All Resource tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
