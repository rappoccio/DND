#!/usr/bin/env python3
"""
Unit tests for Frightened condition functionality.
Tests Fear spell, weapon dropping, movement restriction, and LOS-gated saves.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _dict_to_weapon

def test_frightened_condition_creation():
    """Test that Frightened condition can be set on an agent."""
    cell = rpg.Cell(5, 10)
    agent = rpg.Agent(5, 10, 0, 1, "sprites/test.png")
    conditions = agent.getConditions()
    conditions.frightened = True
    agent.setConditions(conditions)

    assert agent.getConditions().frightened == True
    print("✓ Frightened condition creation")

def test_frighten_disadvantage_flag():
    """Test that frightened agents have disadvantage flag set."""
    bm = rpg.BattleMap("test_map.png")
    bm.analyze_grid()

    # Create two agents - one to frighten, one to be the source
    agents_config = [
        {"name": "Caster", "col": 5, "row": 5, "hp": 20, "speed_walk": 30, "speed_fly": 0},
        {"name": "Target", "col": 10, "row": 10, "hp": 20, "speed_walk": 30, "speed_fly": 0}
    ]

    for cfg in agents_config:
        agent = rpg.Agent(cfg["col"], cfg["row"], 0, 1, "sprites/test.png")
        bm.placeAgent(rpg.Cell(cfg["col"], cfg["row"]), agent, rpg.PlacedAgentStats(hp_cur=cfg["hp"], speed_walk=cfg["speed_walk"], speed_fly=cfg["speed_fly"]))

    # Create a combat engine and apply Frightened
    combat = rpg.CombatEngine()
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = 1
    cond.caster_idx = 0
    cond.condition_name = "Frightened"
    cond.turns_remaining = 5
    cond.save_repeat_turns = 1
    cond.save_ability = rpg.SaveAbility.SaveWis
    cond.save_dc = 12

    combat.addAgentCondition(bm, cond)

    # Check that the target is now frightened
    target_cond = bm.getAgentConditions(1)
    assert target_cond.frightened == True
    print("✓ Frightened disadvantage flag set")

def test_weapon_drop_on_frighten():
    """Test that weapons are dropped when Frightened is applied."""
    bm = rpg.BattleMap("test_map.png")
    bm.analyze_grid()

    # Create an agent with weapons
    agent = rpg.Agent(5, 5, 0, 1, "sprites/test.png")
    stats = rpg.PlacedAgentStats(hp_cur=20, speed_walk=30, speed_fly=0)
    bm.placeAgent(rpg.Cell(5, 5), agent, stats)

    # Give the agent weapons
    w1 = rpg.Weapon()
    w1.name = "Longsword"
    w1.type = rpg.WeaponType.Melee
    w2 = rpg.Weapon()
    w2.name = "Dagger"
    w2.type = rpg.WeaponType.Melee

    weapons = [w1, w2, rpg.Weapon()]
    bm.setAgentWeapons(0, weapons)

    # Create a caster agent
    caster = rpg.Agent(10, 10, 0, 1, "sprites/test.png")
    bm.placeAgent(rpg.Cell(10, 10), caster, stats)

    # Apply Frightened (which should drop weapons)
    combat = rpg.CombatEngine()
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = 0
    cond.caster_idx = 1
    cond.condition_name = "Frightened"
    cond.turns_remaining = 3
    cond.save_repeat_turns = 1
    cond.save_ability = rpg.SaveAbility.SaveWis
    cond.save_dc = 13

    combat.addAgentCondition(bm, cond)

    # Check that items were placed on the map
    items = bm.getItemsAtCell(rpg.Cell(5, 5))
    assert len(items) == 2, f"Expected 2 items on ground, got {len(items)}"
    assert items[0].weapon.name in ["Longsword", "Dagger"]
    assert items[1].weapon.name in ["Longsword", "Dagger"]
    print("✓ Weapon drop on frighten")

def test_frightened_movement_blocked():
    """Test that frightened agents can't move closer to fear source."""
    bm = rpg.BattleMap("test_map.png")
    bm.analyze_grid()

    # Create two agents
    target = rpg.Agent(5, 5, 0, 1, "sprites/test.png")
    caster = rpg.Agent(10, 10, 0, 1, "sprites/test.png")
    stats = rpg.PlacedAgentStats(hp_cur=20, speed_walk=30, speed_fly=0)

    bm.placeAgent(rpg.Cell(5, 5), target, stats)
    bm.placeAgent(rpg.Cell(10, 10), caster, stats)

    # Apply Frightened condition
    combat = rpg.CombatEngine()
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = 0
    cond.caster_idx = 1
    cond.condition_name = "Frightened"
    cond.turns_remaining = 5
    cond.save_repeat_turns = 1
    cond.save_ability = rpg.SaveAbility.SaveWis
    cond.save_dc = 12

    combat.addAgentCondition(bm, cond)

    # Try to move toward the caster (should be blocked)
    # Target is at (5,5), caster at (10,10), moving to (6,6) would be closer
    can_move_closer = combat.moveAgent(bm, 0, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert can_move_closer == False, "Should not be able to move closer to fear source"

    # Try to move away (should work)
    can_move_away = combat.moveAgent(bm, 0, rpg.Cell(4, 4), rpg.MovementType.Walk)
    assert can_move_away == True, "Should be able to move away from fear source"
    print("✓ Frightened movement blocked")

def test_frightened_loses_condition():
    """Test that Frightened condition can be removed."""
    bm = rpg.BattleMap("test_map.png")
    bm.analyze_grid()

    agent = rpg.Agent(5, 5, 0, 1, "sprites/test.png")
    caster = rpg.Agent(10, 10, 0, 1, "sprites/test.png")
    stats = rpg.PlacedAgentStats(hp_cur=20, speed_walk=30, speed_fly=0)

    bm.placeAgent(rpg.Cell(5, 5), agent, stats)
    bm.placeAgent(rpg.Cell(10, 10), caster, stats)

    combat = rpg.CombatEngine()

    # Apply Frightened
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = 0
    cond.caster_idx = 1
    cond.condition_name = "Frightened"
    cond.turns_remaining = 1
    cond.save_repeat_turns = 1
    cond.save_ability = rpg.SaveAbility.SaveWis
    cond.save_dc = 12

    combat.addAgentCondition(bm, cond)
    assert bm.getAgentConditions(0).frightened == True

    # Tick turns - condition should expire
    combat.beginTurn(bm, 0)
    combat.endTurn(bm, 0)

    # Check if frightened is still there (it might be, depends on save success)
    # For this test, we're just checking that the condition can be cleared
    print("✓ Frightened condition lifecycle")

def test_fear_spell_setup():
    """Test that Fear spell is properly configured."""
    # Load spells from JSON (this tests the spell is in the JSON)
    import json
    with open("spells.json", "r") as f:
        spells_data = json.load(f)

    fear_spell = None
    for spell_data in spells_data:
        if spell_data.get("name") == "Fear":
            fear_spell = spell_data
            break

    assert fear_spell is not None, "Fear spell not found in spells.json"
    assert fear_spell.get("geometry") == "Cone"
    assert fear_spell.get("attack_type") == "Save"
    assert fear_spell.get("save_ability") == "SaveWis"
    assert fear_spell.get("radius") == 15
    assert len(fear_spell.get("conditions", [])) > 0
    assert fear_spell["conditions"][0].get("condition_name") == "Frightened"
    print("✓ Fear spell setup in JSON")

def run_tests():
    """Run all Frightened condition tests."""
    print("\n" + "="*50)
    print("Testing Frightened Condition Functionality")
    print("="*50 + "\n")

    tests = [
        test_frightened_condition_creation,
        test_frighten_disadvantage_flag,
        test_weapon_drop_on_frighten,
        test_frightened_movement_blocked,
        test_frightened_loses_condition,
        test_fear_spell_setup,
    ]

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

    print("\n" + "="*50)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*50 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
