#!/usr/bin/env python3
"""
Test suite for Agent Conditions
Tests all condition mechanics: prone, charmed, blinded, hidden, restrained, etc.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_condition_initialization():
    """Test that conditions are properly initialized."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.prone
    assert not cond.charmed
    assert not cond.blinded
    assert not cond.hidden
    assert not cond.restrained
    print("✅ Conditions initialize to false")

def test_set_prone():
    """Test setting and clearing prone condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set prone
    cond = engine.get_agent_conditions(bm, idx)
    cond.prone = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.prone
    print("✅ Can set prone condition")

    # Clear prone
    cond.prone = False
    engine.set_agent_conditions(bm, idx, cond)
    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.prone
    print("✅ Can clear prone condition")

def test_set_charmed():
    """Test charmed condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.charmed = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.charmed
    print("✅ Can set charmed condition")

def test_set_blinded():
    """Test blinded condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.blinded = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.blinded
    print("✅ Can set blinded condition")

def test_set_hidden():
    """Test hidden condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.hidden = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.hidden
    print("✅ Can set hidden condition")

def test_set_restrained():
    """Test restrained condition."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.restrained = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.restrained
    print("✅ Can set restrained condition")

def test_multiple_conditions():
    """Test setting multiple conditions simultaneously."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.prone = True
    cond.charmed = True
    cond.blinded = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.prone
    assert cond.charmed
    assert cond.blinded
    assert not cond.hidden
    print("✅ Can set multiple conditions simultaneously")

def test_condition_clearing():
    """Test clearing individual conditions."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    cond.prone = True
    cond.charmed = True
    cond.blinded = True
    engine.set_agent_conditions(bm, idx, cond)

    # Clear one condition
    cond.prone = False
    engine.set_agent_conditions(bm, idx, cond)
    cond = engine.get_agent_conditions(bm, idx)

    assert not cond.prone
    assert cond.charmed
    assert cond.blinded
    print("✅ Can clear individual conditions without affecting others")

if __name__ == "__main__":
    tests = [
        test_condition_initialization,
        test_set_prone,
        test_set_charmed,
        test_set_blinded,
        test_set_hidden,
        test_set_restrained,
        test_multiple_conditions,
        test_condition_clearing,
    ]

    print("Running Agent Conditions Tests...")
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
