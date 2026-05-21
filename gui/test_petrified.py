#!/usr/bin/env python3
"""
Unit tests for Petrified condition.
Tests that petrified agents are incapacitated, have 0 speed, 0.5x damage resistance,
and are immune to poison.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_petrified_condition_creation():
    """Test that Petrified condition can be set on an agent."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Apply petrified
    engine.apply_petrified(bm, idx)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.petrified == True
    print("✅ Petrified condition created")

def test_petrified_applies_incapacitated():
    """Test that Petrified sets incapacitated flag."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.apply_petrified(bm, idx)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.incapacitated == True
    print("✅ Petrified sets incapacitated flag")

def test_petrified_sets_speed_zero():
    """Test that Petrified sets all movement speeds to 0."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Get initial stats
    stats_before = engine.get_agent_stats(bm, idx)
    assert stats_before.speed_walk > 0, "Agent should have walk speed initially"

    # Apply petrified
    engine.apply_petrified(bm, idx)

    # Check speed is now 0
    stats_after = engine.get_agent_stats(bm, idx)
    assert stats_after.speed_walk == 0
    assert stats_after.speed_fly == 0
    assert stats_after.speed_swim == 0
    assert stats_after.speed_burrow == 0
    print("✅ Petrified sets all speeds to 0")

def test_petrified_resistance_to_all_damage():
    """Test that Petrified sets 0.5x resistance to all damage types."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.apply_petrified(bm, idx)

    stats = engine.get_agent_stats(bm, idx)
    
    # Check all magic damage multipliers are 0.5
    for multiplier in stats.magic_damage_multipliers:
        assert multiplier == 0.5, f"Expected 0.5 resistance, got {multiplier}"
    
    # Check all physical damage multipliers are 0.5
    for multiplier in stats.physical_damage_multipliers:
        assert multiplier == 0.5, f"Expected 0.5 resistance, got {multiplier}"
    
    print("✅ Petrified has 0.5x resistance to all damage")

def test_petrified_immune_to_poison():
    """Test that Petrified agents cannot be poisoned."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Petrify the agent
    engine.apply_petrified(bm, idx)

    # Try to poison it
    engine.apply_poisoned(bm, idx)

    # Should still not be poisoned (immunity works)
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.poisoned == False, "Petrified agent should be immune to poison"
    assert cond.petrified == True
    print("✅ Petrified immune to poison")

def test_poisoned_then_petrified():
    """Test that petrifying a poisoned agent keeps poison (applied before immunity)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Poison first
    engine.apply_poisoned(bm, idx)
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.poisoned == True

    # Then petrify
    engine.apply_petrified(bm, idx)

    # Poison should still be there (it was applied before petrification)
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.poisoned == True
    assert cond.petrified == True
    print("✅ Pre-existing poison persists when petrified")

def run_tests():
    """Run all petrified condition tests."""
    print("\n" + "="*60)
    print("Testing Petrified Condition")
    print("="*60 + "\n")

    tests = [
        test_petrified_condition_creation,
        test_petrified_applies_incapacitated,
        test_petrified_sets_speed_zero,
        test_petrified_resistance_to_all_damage,
        test_petrified_immune_to_poison,
        test_poisoned_then_petrified,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
            print()
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}\n")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}\n")
            failed += 1

    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
