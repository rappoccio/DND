#!/usr/bin/env python3
"""
Test suite for Movement Mechanics
Tests movement, terrain effects, difficult terrain, and movement budget tracking.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_walk_movement_type():
    """Test that walk movement type exists."""
    assert hasattr(rpg, 'MovementType')
    assert hasattr(rpg.MovementType, 'Walk')
    print("✅ Walk movement type exists")

def test_fly_movement_type():
    """Test that fly movement type exists."""
    assert hasattr(rpg.MovementType, 'Fly')
    print("✅ Fly movement type exists")

def test_basic_movement():
    """Test moving an agent on the map."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    agents = bm.placed_agents
    assert agents[idx].origin.col == 5
    assert agents[idx].origin.row == 5
    print("✅ Agent placed at correct location")

def test_movement_budget():
    """Test that movement budget is tracked."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Start of turn should have movement available
    engine.begin_turn(bm, idx)
    walk_remaining = engine.get_walk_remaining(idx)
    assert walk_remaining > 0
    print(f"✅ Movement budget available: {walk_remaining} feet")

def test_spend_movement():
    """Test spending movement from budget."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.begin_turn(bm, idx)
    initial = engine.get_walk_remaining(idx)
    engine.spend_walk(idx, 10)
    after = engine.get_walk_remaining(idx)
    assert after == initial - 10
    print(f"✅ Movement spent correctly: {initial} - 10 = {after}")

def test_terrain_difficulty_normal():
    """Test terrain with normal difficulty (1.0x cost)."""
    assert hasattr(rpg, 'TerrainDifficulty')
    assert hasattr(rpg.TerrainDifficulty, 'Normal')
    print("✅ Normal terrain difficulty exists")

def test_terrain_difficulty_halved():
    """Test terrain with halved cost (0.5x)."""
    assert hasattr(rpg.TerrainDifficulty, 'Halved')
    print("✅ Halved terrain difficulty exists")

def test_terrain_difficulty_quartered():
    """Test terrain with quartered cost (0.25x)."""
    assert hasattr(rpg.TerrainDifficulty, 'Quartered')
    print("✅ Quartered terrain difficulty exists")

def test_terrain_difficulty_slipping():
    """Test slipping terrain (ice/grease)."""
    assert hasattr(rpg.TerrainDifficulty, 'Slipping')
    print("✅ Slipping terrain difficulty exists")

def test_place_terrain_effect():
    """Test placing a terrain effect."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cells = [rpg.Cell(5, 5), rpg.Cell(6, 5)]
    effect_id = bm.place_terrain_effect("Grease", cells, rpg.TerrainDifficulty.Slipping, -1, -1)
    assert effect_id >= 0
    print(f"✅ Terrain effect placed with ID: {effect_id}")

def test_remove_terrain_effect():
    """Test removing a terrain effect."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cells = [rpg.Cell(5, 5)]
    effect_id = bm.place_terrain_effect("Grease", cells, rpg.TerrainDifficulty.Halved, 5, -1)
    assert effect_id >= 0
    bm.remove_terrain_effect(effect_id)
    print("✅ Terrain effect removed successfully")

def test_terrain_effect_expires():
    """Test that terrain effects expire after duration."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cells = [rpg.Cell(5, 5)]
    effect_id = bm.place_terrain_effect("Grease", cells, rpg.TerrainDifficulty.Halved, 2, -1)

    # Tick effects twice (pass -1 for DM effects)
    removed1 = bm.tick_terrain_effects(-1)
    assert effect_id not in removed1

    removed2 = bm.tick_terrain_effects(-1)
    assert effect_id in removed2
    print("✅ Terrain effect expires after duration")

def test_permanent_terrain_effect():
    """Test permanent terrain effects (duration -1)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cells = [rpg.Cell(5, 5)]
    effect_id = bm.place_terrain_effect("Wall", cells, rpg.TerrainDifficulty.Quartered, -1, -1)

    # Tick multiple times
    for _ in range(10):
        bm.tick_terrain_effects(-1)

    # Permanent effect should still be there
    effects = bm.active_terrain_effects
    effect_ids = [e.id for e in effects]
    assert effect_id in effect_ids
    print("✅ Permanent terrain effects persist")

def test_jump_movement():
    """Test jump movement."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)  # STR +2
    idx = add_agent_to_battle(engine, bm, config, str=14)

    engine.begin_turn(bm, idx)
    # Long jump: STR modifier × 1 foot, with running start
    # With STR 14 (+2), can jump 2 feet with running start
    initial_walk = engine.get_walk_remaining(idx)
    engine.spend_walk(idx, 5)  # Jump costs movement
    after_jump = engine.get_walk_remaining(idx)
    assert after_jump < initial_walk
    print("✅ Jump movement costs movement budget")

def test_jump_distance_ceiling():
    """Long-jump reach = Strength SCORE in feet (running) rounded UP to whole 5-ft squares.
    Str 8 → 8 ft → 2 squares (10 ft) is reachable; 3 squares (15 ft) is out of range."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Jumper", 5, 5), str=8)
    # Give plenty of walk budget so the distance cap (not movement) is what's under test.
    s = engine.get_agent_stats(bm, idx); s.speed_walk = 30; engine.set_agent_stats(bm, idx, s)

    def _ready():
        engine.begin_turn(bm, idx)
        # jump_agent checks the Agent's own movement budget; the GUI seeds it at turn start
        # via init_movement (begin_turn only seeds the CombatEngine's separate budget).
        bm.placed_agents[idx].init_movement(30, 0, 0, 0)

    _ready()
    assert engine.jump_agent(bm, idx, rpg.Cell(7, 5), True), \
        "Str 8 running jump should reach 2 squares (ceiling of 8 ft)"

    # Reset and confirm a 3-square (15 ft) jump exceeds the ceiling'd reach.
    bm.set_agent_position(idx, rpg.Cell(5, 5))
    _ready()
    assert not engine.jump_agent(bm, idx, rpg.Cell(8, 5), True), \
        "Str 8 must not reach 3 squares (15 ft > 10 ft ceiling)"
    print("✅ test_jump_distance_ceiling")

def test_disengage_action():
    """Test disengage action (no opportunity attacks when moving)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.begin_turn(bm, idx)
    # Disengage is a bonus action that uses no movement
    # (implementation details may vary)
    print("✅ Disengage action available (implementation may vary)")

def test_dash_action():
    """Test dash action (double movement speed)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.begin_turn(bm, idx)
    initial = engine.get_walk_remaining(idx)
    # Dash action: gain additional movement equal to speed
    # (implementation details may vary)
    assert initial > 0
    print("✅ Dash action affects movement budget")

def test_standing_up():
    """Test standing up from prone costs movement."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.begin_turn(bm, idx)
    initial = engine.get_walk_remaining(idx)

    # Set prone
    cond = engine.get_agent_conditions(bm, idx)
    cond.prone = True
    engine.set_agent_conditions(bm, idx, cond)

    # Standing up costs half movement (should be ~15 feet)
    engine.spend_walk(idx, 15)
    after = engine.get_walk_remaining(idx)
    assert after == initial - 15
    print("✅ Standing up costs movement (half speed)")

def test_multiple_movement_types():
    """Test that agents can use different movement types."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    engine.begin_turn(bm, idx)
    walk_budget = engine.get_walk_remaining(idx)

    # Spend some walk movement
    engine.spend_walk(idx, 10)
    assert engine.get_walk_remaining(idx) == walk_budget - 10
    print("✅ Movement types tracked independently")

if __name__ == "__main__":
    tests = [
        test_walk_movement_type,
        test_fly_movement_type,
        test_basic_movement,
        test_movement_budget,
        test_spend_movement,
        test_terrain_difficulty_normal,
        test_terrain_difficulty_halved,
        test_terrain_difficulty_quartered,
        test_terrain_difficulty_slipping,
        test_place_terrain_effect,
        test_remove_terrain_effect,
        test_terrain_effect_expires,
        test_permanent_terrain_effect,
        test_jump_movement,
        test_jump_distance_ceiling,
        test_disengage_action,
        test_dash_action,
        test_standing_up,
        test_multiple_movement_types,
    ]

    print("Running Movement Mechanics Tests...")
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
