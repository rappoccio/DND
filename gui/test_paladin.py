#!/usr/bin/env python3
"""
Test Paladin: Lay on Hands resource and healing mechanics.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _paladin(engine, bm, idx, level, cha=16):
    """Configure agent idx as a Paladin of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Paladin, level)
    s.cha = cha
    s.initialize_class_resources(rpg.CharacterClass.Paladin, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _soft_target(engine, bm, idx, hp=100):
    """Configure agent as a soft target with low HP."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.hp_max = hp
    s.hp_cur = hp // 2  # Start damaged
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _setup(level):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    paladin_idx = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _paladin(engine, bm, paladin_idx, level)
    _soft_target(engine, bm, target_idx)
    return bm, engine, paladin_idx, target_idx


def test_lay_on_hands_resource():
    """Paladin L1: Lay on Hands resource exists with 5 × level HP pool."""
    for level in [1, 5, 10, 20]:
        bm, engine, paladin_idx, _ = _setup(level)
        s = engine.get_agent_stats(bm, paladin_idx)
        loh = s.get_resource("Lay on Hands")
        assert loh is not None, f"Paladin L{level} should have Lay on Hands resource"
        expected_pool = 5 * level
        assert loh.current == expected_pool, f"L{level} should have {expected_pool} HP pool, got {loh.current}"
        assert loh.max == expected_pool, f"L{level} pool max should be {expected_pool}, got {loh.max}"
    print("✅ test_lay_on_hands_resource passed")


def test_lay_on_hands_partial_spend():
    """Lay on Hands: partial heal decrements pool correctly."""
    bm, engine, paladin_idx, target_idx = _setup(5)
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 25, f"L5 should have 25 HP pool, got {loh.current}"

    # Heal for 10 HP
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 10)
    assert actual_healed == 10, f"Should heal 10 HP, got {actual_healed}"

    # Check pool was decremented
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 15, f"Pool should be 15 after 10 HP spend, got {loh.current}"
    print("✅ test_lay_on_hands_partial_spend passed")


def test_lay_on_hands_no_overheal():
    """Lay on Hands: clamped to min(pool, hp_deficit)."""
    bm, engine, paladin_idx, target_idx = _setup(10)  # L10 has 50 HP pool

    # Target has 50 HP, max 100, so needs 50 HP to be full
    target_s = engine.get_agent_stats(bm, target_idx)
    assert target_s.hp_cur == 50, f"Target should be at 50 HP, got {target_s.hp_cur}"
    assert target_s.hp_max == 100, f"Target max should be 100, got {target_s.hp_max}"

    # Paladin L10 has 50 HP pool, so try to heal for 60 HP
    # Should clamp to min(pool=50, heal_needed=50) = 50
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 60)
    assert actual_healed == 50, f"Should clamp to 50 HP (to full), got {actual_healed}"

    # Check target is now full
    target_s = engine.get_agent_stats(bm, target_idx)
    assert target_s.hp_cur == 100, f"Target should be at 100 HP, got {target_s.hp_cur}"

    # Check pool spent exactly 50
    paladin_s = engine.get_agent_stats(bm, paladin_idx)
    loh = paladin_s.get_resource("Lay on Hands")
    assert loh.current == 0, f"Pool should be 0 after spending 50 (50-50), got {loh.current}"
    print("✅ test_lay_on_hands_no_overheal passed")


def test_lay_on_hands_depleted_pool():
    """Lay on Hands: fails when pool is empty."""
    bm, engine, paladin_idx, target_idx = _setup(1)  # L1 has 5 HP pool

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.current = 0  # Deplete pool
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    # Try to heal
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 5)
    assert actual_healed == -1, f"Should return -1 when pool empty, got {actual_healed}"
    print("✅ test_lay_on_hands_depleted_pool passed")


def test_lay_on_hands_long_rest_restore():
    """Lay on Hands: pool restores on long rest."""
    bm, engine, paladin_idx, _ = _setup(3)  # L3 has 15 HP pool

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.current = 0  # Deplete
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    # Long rest restores
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.restore_long_rest()
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 15, f"Pool should be 15 after long rest, got {loh.current}"
    print("✅ test_lay_on_hands_long_rest_restore passed")


if __name__ == "__main__":
    test_lay_on_hands_resource()
    test_lay_on_hands_partial_spend()
    test_lay_on_hands_no_overheal()
    test_lay_on_hands_depleted_pool()
    test_lay_on_hands_long_rest_restore()
    print("\n✅ All Paladin tests passed!")
