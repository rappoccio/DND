#!/usr/bin/env python3
"""
Test Rogue Cunning Actions: Hide, Dash, Disengage as bonus actions (L2+).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _rogue(engine, bm, idx, level):
    """Configure agent idx as a Rogue of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    s.dex = 16
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def test_cunning_action_unavailable_l1():
    """Rogue L1 does not have cunning_action."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s = _rogue(engine, bm, idx, 1)
    assert not s.has_cunning_action, "Rogue L1 should not have cunning action"
    print("✅ test_cunning_action_unavailable_l1 passed")


def test_cunning_action_available_l2():
    """Rogue L2 has cunning_action."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s = _rogue(engine, bm, idx, 2)
    assert s.has_cunning_action, "Rogue L2 should have cunning action"
    print("✅ test_cunning_action_available_l2 passed")


def test_cunning_action_scales_to_l20():
    """Rogue at all levels 2-20 have cunning_action."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    for level in range(2, 21):
        s = _rogue(engine, bm, idx, level)
        assert s.has_cunning_action, f"Rogue L{level} should have cunning action"
    print("✅ test_cunning_action_scales_to_l20 passed")


def test_dash_bonus_action():
    """Rogue can use Dash as a bonus action (dashing condition works)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s = _rogue(engine, bm, idx, 5)
    agent = bm.placed_agents[idx]

    # Call dash on the agent (this is what the GUI button would call)
    agent.dash()

    # Check that the dashing condition is set
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.dashing, "Rogue should be dashing after calling dash()"
    print("✅ test_dash_bonus_action passed")


def test_disengage_bonus_action():
    """Rogue can use Disengage as a bonus action (disengaging condition works)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s = _rogue(engine, bm, idx, 5)
    agent = bm.placed_agents[idx]

    # Call disengage on the agent (this is what the GUI button would call)
    agent.disengage()

    # Check that the disengaging condition is set
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.disengaging, "Rogue should be disengaging after calling disengage()"
    print("✅ test_disengage_bonus_action passed")


def test_hide_bonus_action():
    """Rogue can use Hide as a bonus action (HideResult works)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s = _rogue(engine, bm, idx, 5)

    # Call check_hide (this is what the GUI button would call)
    result = engine.check_hide(bm, idx, in_combat=False)

    # Check that the result is valid (may be hidden or not depending on stealth roll)
    assert result.valid, "Hide check should be valid for a Rogue"
    assert result.stealth_d20 >= 1 and result.stealth_d20 <= 20, f"d20 should be 1-20, got {result.stealth_d20}"
    assert result.stealth_total > 0, "stealth total should be positive"
    print("✅ test_hide_bonus_action passed")


if __name__ == "__main__":
    test_cunning_action_unavailable_l1()
    test_cunning_action_available_l2()
    test_cunning_action_scales_to_l20()
    test_dash_bonus_action()
    test_disengage_bonus_action()
    test_hide_bonus_action()
    print("\n✅ All Rogue Cunning Actions tests passed!")
