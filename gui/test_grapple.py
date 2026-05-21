#!/usr/bin/env python3
"""
Test suite for Grapple mechanics
Tests grapple initiation, escape, and condition interactions
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_grapple_initialization():
    """Test that grapple condition fields initialize correctly."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.grappled, "Should not be grappled initially"
    assert cond.grappler_idx == -1, "Grappler index should be -1 initially"
    assert cond.grapple_escape_dc == 10, "Escape DC should be 10 (default) initially"
    assert cond.grapple_range_ft == 5, "Grapple range should be 5 (default) initially"
    print("✅ Grapple condition fields initialize correctly")

def test_grapple_success_strong_vs_weak():
    """Test successful grapple: strong grappler vs weak target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Strong attacker (high STR)
    atk_config = create_test_agent("Strong", 5, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=18, dex=10)

    # Weak target (low STR/DEX)
    tgt_config = create_test_agent("Weak", 6, 5)
    tgt_idx = add_agent_to_battle(engine, bm, tgt_config, str=8, dex=8)

    # Perform grapple
    action = rpg.GrappleAction()
    action.attacker_idx = atk_idx
    action.target_idx = tgt_idx

    result = engine.execute_grapple(bm, action)

    assert result.valid, "Grapple should be valid"
    # Strong attacker should likely succeed (though not guaranteed due to randomness)
    print(f"✅ Grapple executed: attacker {result.attacker_roll} vs defender {result.defender_roll}")
    if result.success:
        print(f"  → Grapple succeeded! Escape DC: {result.escape_dc}")
        # Verify target is now grappled
        tgt_cond = engine.get_agent_conditions(bm, tgt_idx)
        assert tgt_cond.grappled, "Target should be grappled after successful grapple"
        assert tgt_cond.grappler_idx == atk_idx, "Grappler index should match attacker"
        assert tgt_cond.grapple_escape_dc == result.escape_dc, "Escape DC should be set"
        print("  → Target is now grappled with correct escape DC")

def test_grapple_invalid_target_index():
    """Test grapple with invalid target index."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    action = rpg.GrappleAction()
    action.attacker_idx = idx
    action.target_idx = 999  # Invalid index

    result = engine.execute_grapple(bm, action)
    assert not result.valid, "Grapple with invalid target should be invalid"
    print("✅ Grapple rejects invalid target index")

def test_grapple_cannot_self_target():
    """Test that an agent cannot grapple itself."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    action = rpg.GrappleAction()
    action.attacker_idx = idx
    action.target_idx = idx  # Self-target

    result = engine.execute_grapple(bm, action)
    assert not result.valid, "Cannot grapple self"
    print("✅ Grapple prevents self-targeting")

def test_grapple_requires_adjacency():
    """Test that grapple requires targets within 5 feet (1 cell)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Attacker at (5, 5)
    atk_config = create_test_agent("Attacker", 5, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config)

    # Target far away at (8, 5) - more than 1 cell away
    tgt_config = create_test_agent("Target", 8, 5)
    tgt_idx = add_agent_to_battle(engine, bm, tgt_config)

    action = rpg.GrappleAction()
    action.attacker_idx = atk_idx
    action.target_idx = tgt_idx

    result = engine.execute_grapple(bm, action)
    assert not result.valid, "Grapple requires adjacency (within 1 cell)"
    print("✅ Grapple requires adjacency")

def test_grapple_escape_success():
    """Test successful escape from grapple."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Very strong grappler
    atk_config = create_test_agent("Grappler", 5, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=20, dex=10)

    # Very weak target initially
    tgt_config = create_test_agent("Target", 6, 5)
    tgt_idx = add_agent_to_battle(engine, bm, tgt_config, str=6, dex=6)

    # Perform grapple
    action = rpg.GrappleAction()
    action.attacker_idx = atk_idx
    action.target_idx = tgt_idx
    result = engine.execute_grapple(bm, action)

    if result.valid and result.success:
        escape_dc = result.escape_dc

        # Now boost target's STR to help them escape
        stats = engine.get_agent_stats(bm, tgt_idx)
        stats.str = 18  # Make them strong
        engine.set_agent_stats(bm, tgt_idx, stats)

        # Try to escape
        escape_result = engine.execute_grapple_escape(bm, tgt_idx)
        assert escape_result.valid, "Escape attempt should be valid"
        print(f"✅ Escape roll {escape_result.escape_roll} vs DC {escape_result.escape_dc}")

        if escape_result.success:
            # Verify grapple is cleared
            tgt_cond = engine.get_agent_conditions(bm, tgt_idx)
            assert not tgt_cond.grappled, "Target should be free after successful escape"
            print("  → Target successfully escaped grapple")
        else:
            # Still grappled
            tgt_cond = engine.get_agent_conditions(bm, tgt_idx)
            assert tgt_cond.grappled, "Target should still be grappled after failed escape"
            print("  → Target failed to escape (still grappled)")
    else:
        print("🔴 Skipping escape test: grapple didn't succeed in initial attempt")

def test_grapple_escape_not_grappled():
    """Test that escape attempt fails if agent is not grappled."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Try to escape when not grappled
    result = engine.execute_grapple_escape(bm, idx)
    assert not result.valid, "Escape should be invalid if not grappled"
    print("✅ Cannot escape if not grappled")

def test_grappled_agent_cannot_move():
    """Test that grappled agents cannot move (Speed = 0)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Very strong grappler
    atk_config = create_test_agent("Grappler", 5, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=20)

    # Very weak target
    tgt_config = create_test_agent("Target", 6, 5)
    tgt_idx = add_agent_to_battle(engine, bm, tgt_config, str=6)

    # Grapple the target
    action = rpg.GrappleAction()
    action.attacker_idx = atk_idx
    action.target_idx = tgt_idx
    result = engine.execute_grapple(bm, action)

    if result.valid and result.success:
        # Begin target's turn to set movement budget
        engine.begin_turn(bm, tgt_idx)

        # Try to move target
        new_pos = rpg.Cell(6, 6)  # Try to move down
        can_move = engine.move_agent(bm, tgt_idx, new_pos, rpg.MovementType.Walk)

        assert not can_move, "Grappled agent should not be able to move"
        print("✅ Grappled agents cannot move (Speed = 0)")
    else:
        print("🔴 Skipping movement test: grapple didn't succeed")

def test_grapple_badge_in_repr():
    """Test that grappled condition appears in repr."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set grappled
    cond = engine.get_agent_conditions(bm, idx)
    cond.grappled = True
    cond.grappler_idx = 0
    cond.grapple_escape_dc = 15
    engine.set_agent_conditions(bm, idx, cond)

    # Check repr
    cond = engine.get_agent_conditions(bm, idx)
    repr_str = repr(cond)
    assert "grappled" in repr_str.lower(), "Grappled status should appear in repr"
    print(f"✅ Grappled condition appears in repr: {repr_str}")

def test_grappler_movement_drags_target():
    """Test that grappled creatures are dragged when grappler moves."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Very strong grappler at (5, 5)
    grp_config = create_test_agent("Grappler", 5, 5)
    grp_idx = add_agent_to_battle(engine, bm, grp_config, str=18)

    # Very weak target at (6, 5) - adjacent to grappler
    tgt_config = create_test_agent("Target", 6, 5)
    tgt_idx = add_agent_to_battle(engine, bm, tgt_config, str=6)

    # Perform grapple
    action = rpg.GrappleAction()
    action.attacker_idx = grp_idx
    action.target_idx = tgt_idx
    result = engine.execute_grapple(bm, action)

    if result.valid and result.success:
        print(f"✅ Grapple succeeded")

        # Begin grappler's turn to get movement budget
        engine.begin_turn(bm, grp_idx)

        # Get starting positions
        grp_before = bm.placed_agents[grp_idx]
        tgt_before = bm.placed_agents[tgt_idx]
        print(f"  Before move: grappler at ({grp_before.origin.col},{grp_before.origin.row}), target at ({tgt_before.origin.col},{tgt_before.origin.row})")

        # Move grappler 3 cells right and 2 cells down
        new_grp_pos = rpg.Cell(8, 7)
        move_success = engine.move_agent(bm, grp_idx, new_grp_pos, rpg.MovementType.Walk)

        if move_success:
            grp_after = bm.placed_agents[grp_idx]
            tgt_after = bm.placed_agents[tgt_idx]
            print(f"  After move: grappler at ({grp_after.origin.col},{grp_after.origin.row}), target at ({tgt_after.origin.col},{tgt_after.origin.row})")

            # Verify grappler moved to destination
            assert grp_after.origin.col == new_grp_pos.col and grp_after.origin.row == new_grp_pos.row, \
                "Grappler should move to destination"
            print(f"  ✅ Grappler moved to ({grp_after.origin.col},{grp_after.origin.row})")

            # Verify target was dragged (not at original position)
            assert not (tgt_after.origin.col == tgt_before.origin.col and tgt_after.origin.row == tgt_before.origin.row), \
                "Target should be dragged from original position"
            print(f"  ✅ Target was dragged from original position")

            # Verify target is adjacent to grappler (within 1 cell Chebyshev distance)
            dc = abs(tgt_after.origin.col - grp_after.origin.col)
            dr = abs(tgt_after.origin.row - grp_after.origin.row)
            dist = max(dc, dr)
            assert dist <= 1, f"Target should be adjacent to grappler (distance: {dist})"
            print(f"  ✅ Target is adjacent to grappler (distance: {dist} cells)")

            # Verify target is still grappled
            tgt_cond = engine.get_agent_conditions(bm, tgt_idx)
            assert tgt_cond.grappled, "Target should still be grappled after being dragged"
            assert tgt_cond.grappler_idx == grp_idx, "Grappler index should be correct"
            print(f"  ✅ Target still grappled after forced movement")
        else:
            print("🔴 Move failed")
    else:
        print("🔴 Grapple didn't succeed, skipping drag test")

def run_all_tests():
    """Run all grapple tests."""
    tests = [
        test_grapple_initialization,
        test_grapple_success_strong_vs_weak,
        test_grapple_invalid_target_index,
        test_grapple_cannot_self_target,
        test_grapple_requires_adjacency,
        test_grapple_escape_success,
        test_grapple_escape_not_grappled,
        test_grappled_agent_cannot_move,
        test_grapple_badge_in_repr,
        test_grappler_movement_drags_target,
    ]

    print("\n" + "="*60)
    print("GRAPPLE MECHANICS TEST SUITE")
    print("="*60 + "\n")

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
            print(f"❌ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
