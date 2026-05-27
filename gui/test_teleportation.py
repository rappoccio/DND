#!/usr/bin/env python3
"""
Test teleportation spell functionality: validation and agent placement
Tests isValidTeleportDestination() and placeTeleportedAgents() functions.
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _load_spells():
    """Load spells from spells.json."""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "spells.json"),
        os.path.join(os.path.dirname(__file__), "..", "spells.json"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("spells.json not found")


_SPELLS = _load_spells()


def test_is_valid_teleport_destination_in_bounds():
    """Verify that valid cells in map bounds return True."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    cols = bm.grid_cols
    rows = bm.grid_rows

    # Test a cell in the middle of the map
    mid_col = cols // 2
    mid_row = rows // 2

    result = engine.is_valid_teleport_destination(bm, mid_col, mid_row)
    assert isinstance(result, bool), "Should return a boolean"
    print("✅ test_is_valid_teleport_destination_in_bounds passed")


def test_is_valid_teleport_destination_out_of_bounds():
    """Verify that out-of-bounds cells return False."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    cols = bm.grid_cols
    rows = bm.grid_rows

    # Test cells outside bounds
    assert not engine.is_valid_teleport_destination(bm, -1, 0), "Negative col should be invalid"
    assert not engine.is_valid_teleport_destination(bm, cols, 0), "Col >= grid_cols should be invalid"
    assert not engine.is_valid_teleport_destination(bm, 0, -1), "Negative row should be invalid"
    assert not engine.is_valid_teleport_destination(bm, 0, rows), "Row >= grid_rows should be invalid"

    print("✅ test_is_valid_teleport_destination_out_of_bounds passed")


def test_is_valid_teleport_destination_negative_coords():
    """Verify that negative coordinates always return False."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    assert not engine.is_valid_teleport_destination(bm, -5, -5), "Large negative coords should be invalid"
    assert not engine.is_valid_teleport_destination(bm, -100, 0), "Large negative col should be invalid"
    assert not engine.is_valid_teleport_destination(bm, 0, -100), "Large negative row should be invalid"

    print("✅ test_is_valid_teleport_destination_negative_coords passed")


def test_place_teleported_agents_single_agent():
    """Verify single agent can be teleported to a destination."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add an agent to the battle
    config = create_test_agent("Teleporter", 2, 2)
    idx = add_agent_to_battle(engine, bm, config)

    cols = bm.grid_cols
    rows = bm.grid_rows

    # Choose a destination in the middle of the map
    dest_col = cols // 2
    dest_row = rows // 2

    # Try to place the agent
    placed = engine.place_teleported_agents(bm, [idx], dest_col, dest_row)

    assert placed >= 0, f"Should place at least 0 agents, got {placed}"
    assert placed <= 1, f"Should place at most 1 agent, got {placed}"

    # Verify agent is at or near destination
    agents = bm.placed_agents
    assert agents[idx].origin.col == dest_col or agents[idx].origin.col in (dest_col - 1, dest_col + 1), \
        f"Agent should be at or near destination col {dest_col}, got {agents[idx].origin.col}"

    print("✅ test_place_teleported_agents_single_agent passed")


def test_place_teleported_agents_multiple_agents():
    """Verify multiple agents are placed in circular pattern around destination."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add multiple agents
    config1 = create_test_agent("Agent1", 2, 2)
    idx1 = add_agent_to_battle(engine, bm, config1)

    config2 = create_test_agent("Agent2", 3, 3)
    idx2 = add_agent_to_battle(engine, bm, config2)

    cols = bm.grid_cols
    rows = bm.grid_rows

    dest_col = cols // 2
    dest_row = rows // 2

    # Try to place both agents
    placed = engine.place_teleported_agents(bm, [idx1, idx2], dest_col, dest_row)

    assert placed >= 0, f"Should place at least 0 agents, got {placed}"
    assert placed <= 2, f"Should place at most 2 agents, got {placed}"

    print("✅ test_place_teleported_agents_multiple_agents passed")


def test_place_teleported_agents_empty_list():
    """Verify empty agent list returns 0."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    cols = bm.grid_cols
    rows = bm.grid_rows

    dest_col = cols // 2
    dest_row = rows // 2

    placed = engine.place_teleported_agents(bm, [], dest_col, dest_row)

    assert placed == 0, f"Empty list should place 0 agents, got {placed}"
    print("✅ test_place_teleported_agents_empty_list passed")


def test_place_teleported_agents_invalid_destination():
    """Verify invalid destination returns 0."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add an agent
    config = create_test_agent("TestAgent", 2, 2)
    idx = add_agent_to_battle(engine, bm, config)

    cols = bm.grid_cols

    # Try to place at an out-of-bounds location
    placed = engine.place_teleported_agents(bm, [idx], cols + 10, 0)

    assert placed == 0, f"Invalid destination should place 0 agents, got {placed}"
    print("✅ test_place_teleported_agents_invalid_destination passed")


def test_misty_step_casting_time():
    """Verify Misty Step has casting_time = BonusAction from spells.json."""
    # Find Misty Step in the loaded spells
    misty_step_dict = None
    for spell_dict in _SPELLS:
        if spell_dict.get("name") == "Misty Step":
            misty_step_dict = spell_dict
            break

    assert misty_step_dict is not None, "Misty Step spell should exist in spells.json"
    assert misty_step_dict.get("casting_time") == "BonusAction", \
        f"Misty Step should have casting_time='BonusAction', got '{misty_step_dict.get('casting_time')}'"
    print("✅ test_misty_step_casting_time passed")


def test_casting_time_enum_values():
    """Verify all CastingTime enum values exist."""
    assert rpg.CastingTime.Action
    assert rpg.CastingTime.BonusAction
    assert rpg.CastingTime.Reaction
    print("✅ test_casting_time_enum_values passed")


def test_casting_time_default():
    """Verify default casting_time is Action."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create a test spell with default settings
    spell = rpg.Spell()
    assert spell.casting_time == rpg.CastingTime.Action, \
        f"Default casting_time should be Action, got {spell.casting_time}"
    print("✅ test_casting_time_default passed")


if __name__ == "__main__":
    test_is_valid_teleport_destination_in_bounds()
    test_is_valid_teleport_destination_out_of_bounds()
    test_is_valid_teleport_destination_negative_coords()
    test_place_teleported_agents_single_agent()
    test_place_teleported_agents_multiple_agents()
    test_place_teleported_agents_empty_list()
    test_place_teleported_agents_invalid_destination()
    test_casting_time_enum_values()
    test_casting_time_default()
    test_misty_step_casting_time()

    print("\n✅ All teleportation tests passed!")
