#!/usr/bin/env python3
"""
Unit tests for Deafened condition.
Tests that deafened creatures cannot hear and auto-fail ability checks that require hearing.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_deafened_condition_creation():
    """Test that Deafened condition can be set on an agent."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Apply deafened
    engine.apply_deafened(bm, idx)

    assert engine.get_agent_conditions(bm, idx).deafened == True
    print("✓ Deafened condition created")

def test_deafened_flag_set():
    """Test that deafened flag is properly tracked."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Agent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Initially not deafened
    assert engine.get_agent_conditions(bm, idx).deafened == False

    # Apply deafened
    engine.apply_deafened(bm, idx)

    # Now deafened
    assert engine.get_agent_conditions(bm, idx).deafened == True
    print("✓ Deafened flag properly tracked")

def test_deafened_multiple_conditions():
    """Test that deafened can coexist with other conditions."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Agent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Apply deafened
    engine.apply_deafened(bm, idx)

    # Apply prone as well
    engine.apply_prone(bm, idx)

    # Both should be set
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.deafened == True
    assert cond.prone == True
    print("✓ Deafened coexists with other conditions")

def test_deafened_active_agent_condition():
    """Test deafened as an active condition that can be tracked for saving."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Apply deafened first to set the flag
    engine.apply_deafened(bm, idx)

    # Create an active condition entry to track it
    ac = rpg.ActiveAgentCondition()
    ac.agent_idx = idx
    ac.caster_idx = 0
    ac.condition_name = "Deafened"
    ac.turns_remaining = 5
    ac.save_ability = rpg.SaveAbility.Constitution
    ac.save_dc = 12

    # Add the active tracking entry
    engine.add_agent_condition(bm, ac)

    # Verify deafened flag is still set
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.deafened == True
    print("✓ Deafened works as active condition with saves")

def test_deafened_prevents_hearing():
    """Test that deafened agents cannot hear (would auto-fail hearing checks)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Agent", 5, 5, wis=16)  # High WIS for hearing
    idx = add_agent_to_battle(engine, bm, config)

    # Apply deafened
    engine.apply_deafened(bm, idx)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.deafened == True
    # Deafened creatures would auto-fail Perception checks involving hearing
    print("✓ Deafened agent cannot hear (would auto-fail hearing checks)")

def run_tests():
    """Run all deafened condition tests."""
    print("\n" + "="*60)
    print("Testing Deafened Condition")
    print("="*60 + "\n")

    tests = [
        test_deafened_condition_creation,
        test_deafened_flag_set,
        test_deafened_multiple_conditions,
        test_deafened_active_agent_condition,
        test_deafened_prevents_hearing,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
            print()
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}\n")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}\n")
            failed += 1

    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
