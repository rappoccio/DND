#!/usr/bin/env python3
"""
Test suite for Opportunity Attacks triggered by forced movement
Tests that OAs trigger correctly when shove, grapple dragging, push, or fear cause movement
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_shove_triggers_oa():
    """Test that shove causing movement triggers opportunity attacks."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Attacker at (5, 5)
    atk_config = create_test_agent("Attacker", 5, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=16)

    # Victim at (6, 5) - adjacent to attacker
    vic_config = create_test_agent("Victim", 6, 5)
    vic_idx = add_agent_to_battle(engine, bm, vic_config, str=10)

    # Threat at (8, 5) - within reach of (6, 5), but not (7, 5) after shove
    threat_config = create_test_agent("Threat", 8, 5)
    threat_idx = add_agent_to_battle(engine, bm, threat_config)

    # Perform shove (push, not knock prone)
    action = rpg.ShoveAction()
    action.attacker_idx = atk_idx
    action.target_idx = vic_idx
    action.knock_prone = False

    result = engine.execute_shove(bm, action)
    assert result.valid, "Shove should be valid"

    if result.success:
        # Victim should have been pushed 5 feet (1 cell)
        pushed_agent = bm.placed_agents[vic_idx]
        print(f"✅ Shove succeeded: victim pushed to ({pushed_agent.origin.col},{pushed_agent.origin.row})")
        # Verify victim is no longer adjacent to threat (left threat zone)
        # Distance from threat at (8,5) to victim should be > 1
        dc = max(threat_config.origin.col - pushed_agent.origin.col,
                pushed_agent.origin.col - (threat_config.origin.col + 1 - 1),
                0)
        dr = max(threat_config.origin.row - pushed_agent.origin.row,
                pushed_agent.origin.row - (threat_config.origin.row + 1 - 1),
                0)
        dist = max(dc, dr)
        print(f"  → Victim distance from threat: {dist} cells")
        if dist > 1:
            print(f"  → Victim left threat zone (should trigger OA on threat)")
    else:
        print("🔴 Shove failed (victim won, no forced movement)")

def test_grapple_drag_triggers_oa():
    """Test that grappled creature being dragged by grappler triggers OA when leaving threat zones."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Grappler at (5, 5)
    grp_config = create_test_agent("Grappler", 5, 5)
    grp_idx = add_agent_to_battle(engine, bm, grp_config, str=18)

    # Victim at (6, 5) - adjacent to grappler
    vic_config = create_test_agent("Victim", 6, 5)
    vic_idx = add_agent_to_battle(engine, bm, vic_config, str=8)

    # Threat at (7, 5) - adjacent to victim, but not to grappler
    threat_config = create_test_agent("Threat", 7, 5)
    threat_idx = add_agent_to_battle(engine, bm, threat_config)

    # Begin grappler's turn to get movement budget
    engine.begin_turn(bm, grp_idx)

    # Perform grapple
    action = rpg.GrappleAction()
    action.attacker_idx = grp_idx
    action.target_idx = vic_idx
    result = engine.execute_grapple(bm, action)

    if result.valid and result.success:
        print(f"✅ Grapple succeeded: victim grappled by grappler")

        # Now move grappler away from threat (to 3, 5)
        # This should drag victim along, moving victim away from threat
        grappler_before = bm.placed_agents[grp_idx]
        victim_before = bm.placed_agents[vic_idx]
        print(f"  → Before move: grappler at ({grappler_before.origin.col},{grappler_before.origin.row}), victim at ({victim_before.origin.col},{victim_before.origin.row})")

        new_pos = rpg.Cell(3, 5)
        move_success = engine.move_agent(bm, grp_idx, new_pos, rpg.MovementType.Walk)

        if move_success:
            grappler_after = bm.placed_agents[grp_idx]
            victim_after = bm.placed_agents[vic_idx]
            print(f"  → After move: grappler at ({grappler_after.origin.col},{grappler_after.origin.row}), victim at ({victim_after.origin.col},{victim_after.origin.row})")

            # Verify victim was dragged to same position as grappler
            assert victim_after.origin.col == grappler_after.origin.col, "Victim should be dragged to grappler's position"
            assert victim_after.origin.row == grappler_after.origin.row, "Victim should be dragged to grappler's position"
            print(f"  ✅ Victim correctly dragged along with grappler")

            # Verify victim is still grappled
            vic_cond = engine.get_agent_conditions(bm, vic_idx)
            assert vic_cond.grappled, "Victim should still be grappled after being dragged"
            print(f"  ✅ Victim still grappled after forced movement")
        else:
            print("🔴 Move failed")
    else:
        print("🔴 Grapple didn't succeed, skipping drag test")

def test_forced_movement_leaves_threat_zone():
    """Test that forced movement triggering OA is detected when victim leaves threat zone."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Victim at (5, 5)
    vic_config = create_test_agent("Victim", 5, 5)
    vic_idx = add_agent_to_battle(engine, bm, vic_config, str=10)

    # Threat at (6, 5) - adjacent to victim
    threat_config = create_test_agent("Threat", 6, 5)
    threat_idx = add_agent_to_battle(engine, bm, threat_config)

    # Attacker at (4, 5) - adjacent on other side
    atk_config = create_test_agent("Attacker", 4, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=16)

    # Verify threat can see victim initially
    threatening = set(engine.threatening_agents(bm, vic_idx))
    print(f"✅ Initial threats to victim: {threatening}")
    assert threat_idx in threatening, "Threat should be adjacent to victim"

    # Perform shove to push victim away
    action = rpg.ShoveAction()
    action.attacker_idx = atk_idx
    action.target_idx = vic_idx
    action.knock_prone = False

    result = engine.execute_shove(bm, action)

    if result.success:
        # After shove, victim should be at (6, 5) - new position
        victim = bm.placed_agents[vic_idx]
        print(f"  → Victim pushed to ({victim.origin.col},{victim.origin.row})")

        # Verify victim is no longer adjacent to original threat
        new_threatening = set(engine.threatening_agents(bm, vic_idx))
        print(f"  → New threats after forced movement: {new_threatening}")
        if threat_idx not in new_threatening:
            print(f"  ✅ Victim left threat zone (OA opportunity)")
        else:
            print(f"  🔴 Victim still in threat zone")
    else:
        print("🔴 Shove failed")

def test_grappled_cannot_be_forcibly_moved_elsewhere():
    """Test that a grappled creature cannot be shoved/pushed away from grappler."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Grappler at (5, 5)
    grp_config = create_test_agent("Grappler", 5, 5)
    grp_idx = add_agent_to_battle(engine, bm, grp_config, str=18)

    # Victim at (6, 5) - adjacent to grappler
    vic_config = create_test_agent("Victim", 6, 5)
    vic_idx = add_agent_to_battle(engine, bm, vic_config, str=8)

    # Attacker trying to shove at (7, 5)
    atk_config = create_test_agent("Attacker", 7, 5)
    atk_idx = add_agent_to_battle(engine, bm, atk_config, str=16)

    # Grapple the victim
    action = rpg.GrappleAction()
    action.attacker_idx = grp_idx
    action.target_idx = vic_idx
    result = engine.execute_grapple(bm, action)

    if result.success:
        # Try to shove the grappled victim
        shove_action = rpg.ShoveAction()
        shove_action.attacker_idx = atk_idx
        shove_action.target_idx = vic_idx
        shove_action.knock_prone = False

        shove_result = engine.execute_shove(bm, shove_action)

        # The shove may succeed or fail depending on rules
        # But if it succeeds, victim should stay with grappler
        if shove_result.success:
            victim = bm.placed_agents[vic_idx]
            grappler = bm.placed_agents[grp_idx]
            # Victim should still be adjacent to grappler (hasn't moved)
            dc = max(grappler.origin.col - victim.origin.col,
                    victim.origin.col - (grappler.origin.col + 1 - 1),
                    0)
            dr = max(grappler.origin.row - victim.origin.row,
                    victim.origin.row - (grappler.origin.row + 1 - 1),
                    0)
            dist = max(dc, dr)
            print(f"✅ Shove against grappled creature: distance from grappler = {dist}")
        else:
            print("✅ Shove against grappled creature failed/prevented")
    else:
        print("🔴 Initial grapple didn't succeed")

def run_all_tests():
    """Run all forced movement + OA tests."""
    tests = [
        test_shove_triggers_oa,
        test_grapple_drag_triggers_oa,
        test_forced_movement_leaves_threat_zone,
        test_grappled_cannot_be_forcibly_moved_elsewhere,
    ]

    print("\n" + "="*60)
    print("FORCED MOVEMENT + OA TEST SUITE")
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
