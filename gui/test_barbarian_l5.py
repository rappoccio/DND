#!/usr/bin/env python3
"""
Test Barbarian L5 mechanics: Extra Attack, Fast Movement
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_extra_attack_initialization():
    """Verify Extra Attack (num_attacks = 2) is set at L5"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian5", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 5
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.num_attacks == 2, f"Barbarian L5 should have num_attacks = 2, got {stats.num_attacks}"
    print("✅ test_extra_attack_initialization passed")


def test_extra_attack_not_at_l4():
    """Verify Extra Attack (num_attacks) is NOT set at L4"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian4", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 4
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 4)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.num_attacks == 1, f"Barbarian L4 should have num_attacks = 1, got {stats.num_attacks}"
    print("✅ test_extra_attack_not_at_l4 passed")


def test_fast_movement_initialization():
    """Verify Fast Movement (+10 speed_walk) is set at L5"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian5", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 5
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.speed_walk == 40, f"Barbarian L5 should have speed_walk = 40 (30 + 10), got {stats.speed_walk}"
    print("✅ test_fast_movement_initialization passed")


def test_fast_movement_not_at_l4():
    """Verify Fast Movement is NOT applied at L4"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian4", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 4
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 4)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.speed_walk == 30, f"Barbarian L4 should have speed_walk = 30 (base), got {stats.speed_walk}"
    print("✅ test_fast_movement_not_at_l4 passed")


def test_extra_attack_higher_levels():
    """Verify Extra Attack persists at higher levels (L10, L15, L20)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    for level in [10, 15, 20]:
        config = create_test_agent(f"Barbarian{level}", 5, 5)
        config.stats.character_class = rpg.CharacterClass.Barbarian
        config.stats.char_level = level
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.initialize_class_resources(rpg.CharacterClass.Barbarian, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        assert stats.num_attacks == 2, f"Barbarian L{level} should have num_attacks = 2, got {stats.num_attacks}"

    print("✅ test_extra_attack_higher_levels passed")


def test_fast_movement_higher_levels():
    """Verify Fast Movement persists at higher levels"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    for level in [10, 15, 20]:
        config = create_test_agent(f"Barbarian{level}", 5, 5)
        config.stats.character_class = rpg.CharacterClass.Barbarian
        config.stats.char_level = level
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.initialize_class_resources(rpg.CharacterClass.Barbarian, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        assert stats.speed_walk == 40, f"Barbarian L{level} should have speed_walk = 40, got {stats.speed_walk}"

    print("✅ test_fast_movement_higher_levels passed")


if __name__ == "__main__":
    test_extra_attack_initialization()
    test_extra_attack_not_at_l4()
    test_fast_movement_initialization()
    test_fast_movement_not_at_l4()
    test_extra_attack_higher_levels()
    test_fast_movement_higher_levels()
    print("\n✅ All L5 feature tests passed!")
