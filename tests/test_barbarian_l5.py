#!/usr/bin/env python3
"""
Test Barbarian L5 mechanics: Extra Attack, Fast Movement
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

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
    """Verify initialize_class_resources does NOT mutate speed_walk at L5.

    Fast Movement's +10 ft is expected to already be baked into the imported/configured
    speed_walk; the engine must not add it (doing so accumulated +10 every save/load)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian5", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 5
    idx = add_agent_to_battle(engine, bm, config)

    # Speed is whatever the imported stats provide; record it, then ensure initialize leaves it alone.
    base = engine.get_agent_stats(bm, idx).speed_walk

    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 5)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.speed_walk == base, f"initialize must not change speed_walk (was {base}, got {stats.speed_walk})"
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
    """Verify initialize_class_resources never mutates speed_walk at higher levels."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    for level in [10, 15, 20]:
        config = create_test_agent(f"Barbarian{level}", 5, 5)
        config.stats.character_class = rpg.CharacterClass.Barbarian
        config.stats.char_level = level
        idx = add_agent_to_battle(engine, bm, config)

        base = engine.get_agent_stats(bm, idx).speed_walk

        stats = engine.get_agent_stats(bm, idx)
        stats.initialize_class_resources(rpg.CharacterClass.Barbarian, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        assert stats.speed_walk == base, f"Barbarian L{level}: initialize must not change speed_walk (was {base}, got {stats.speed_walk})"

    print("✅ test_fast_movement_higher_levels passed")


if __name__ == "__main__":
    test_extra_attack_initialization()
    test_extra_attack_not_at_l4()
    test_fast_movement_initialization()
    test_fast_movement_not_at_l4()
    test_extra_attack_higher_levels()
    test_fast_movement_higher_levels()
    print("\n✅ All L5 feature tests passed!")
