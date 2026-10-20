#!/usr/bin/env python3
"""
Edge walls (plans/DUNGEON_LEVELS_PLAN.md, Phase 2A).

A wall on the grid line between two cells blocks movement, line of sight and melee reach.
A diagonal step or sight line through a corner is open when either L-shaped route round the
corner is clear. Edge doors own their edges: closed they block, open they pass.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)

E, S = rpg.EdgeSide.East, rpg.EdgeSide.South
C = rpg.Cell


def open_map():
    bm = setup_battle_map()
    bm.clear_walls()
    return bm


def east_wall(bm, col, rows):
    """A wall along the line between column `col` and `col + 1`, for each row in `rows`."""
    for r in rows:
        bm.set_edge_wall(C(col, r), E)


def cells(cs):
    return {(c.col, c.row) for c in cs}


def ready(engine, bm, idx, walk=60, strength=10):
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = walk
    s.str = strength
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(walk, 0, 0, 0)


def pos(bm, idx):
    o = bm.placed_agents[idx].origin
    return (o.col, o.row)


# ── The store ────────────────────────────────────────────────────────────────
def test_store_round_trip():
    bm = open_map()
    assert not bm.has_edge_walls
    bm.set_edge_wall(C(5, 5), E)
    bm.set_edge_wall(C(2, 3), S)
    assert bm.has_edge_walls
    assert [(e.cell.col, e.cell.row, e.side) for e in bm.edge_walls] == [(2, 3, S), (5, 5, E)]
    assert bm.edge_between(C(5, 5), C(6, 5)) and bm.edge_between(C(6, 5), C(5, 5))
    assert bm.edge_between(C(2, 3), C(2, 4)) and bm.edge_between(C(2, 4), C(2, 3))
    assert not bm.edge_between(C(5, 5), C(5, 6))
    assert not bm.edge_between(C(5, 5), C(6, 6)), "edge_between is for orthogonal pairs only"
    bm.set_edge_wall(C(5, 5), E, False)
    assert not bm.edge_between(C(5, 5), C(6, 5))
    bm.clear_walls()
    assert bm.edge_walls == [] and not bm.has_edge_walls
    print("✅ test_store_round_trip passed")


# ── Movement ─────────────────────────────────────────────────────────────────
def test_walk_stops_at_a_full_wall():
    bm = open_map()
    before = cells(bm.reachable_cells(C(3, 5), 1, 60, rpg.MovementType.Walk))
    assert (6, 5) in before
    east_wall(bm, 5, range(12))
    after = cells(bm.reachable_cells(C(3, 5), 1, 60, rpg.MovementType.Walk))
    assert (5, 5) in after
    assert not any(c >= 6 for c, _ in after), "nothing east of a full-height wall is reachable"
    print("✅ test_walk_stops_at_a_full_wall passed")


def test_walk_goes_round_a_short_wall():
    bm = open_map()
    east_wall(bm, 5, range(3, 8))
    assert (6, 5) not in cells(bm.reachable_cells(C(5, 5), 1, 10, rpg.MovementType.Walk))
    assert (6, 5) in cells(bm.reachable_cells(C(5, 5), 1, 60, rpg.MovementType.Walk))

    engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    ready(engine, bm, m)
    assert bm.move_agent(m, C(6, 5), rpg.MovementType.Walk)
    path = bm.last_move_path
    assert len(path) > 2, f"the route must go round the wall, got {path}"
    for a, b in zip(path, path[1:]):
        assert not bm.step_crosses_wall(a, b, 1), f"route crosses the wall at {a}->{b}"
    print("✅ test_walk_goes_round_a_short_wall passed")


def test_fly_respects_edges_and_burrow_does_not():
    bm = open_map()
    east_wall(bm, 5, range(12))
    fly = cells(bm.reachable_cells(C(3, 5), 1, 60, rpg.MovementType.Fly))
    assert not any(c >= 6 for c, _ in fly)
    burrow = cells(bm.reachable_cells(C(3, 5), 1, 60, rpg.MovementType.Burrow))
    assert (6, 5) in burrow
    print("✅ test_fly_respects_edges_and_burrow_does_not passed")


def test_diagonal_corner_rule():
    bm = open_map()
    # A straight wall through the corner stops the diagonal.
    east_wall(bm, 5, [4, 5])
    assert bm.step_crosses_wall(C(5, 4), C(6, 5), 1)
    assert bm.step_crosses_wall(C(6, 5), C(5, 4), 1), "symmetric"
    # A wall that ends at the corner lets it past.
    bm.clear_edge_walls()
    east_wall(bm, 5, [4])
    assert not bm.step_crosses_wall(C(5, 4), C(6, 5), 1)
    # A wall that turns at the corner lets it past.
    bm.set_edge_wall(C(6, 4), S)
    assert not bm.step_crosses_wall(C(5, 4), C(6, 5), 1)
    # A wall wrapped round the start cell's corner stops it.
    bm.clear_edge_walls()
    bm.set_edge_wall(C(5, 4), E)
    bm.set_edge_wall(C(5, 4), S)
    assert bm.step_crosses_wall(C(5, 4), C(6, 5), 1)
    # Orthogonal steps cross exactly their own edge.
    assert bm.step_crosses_wall(C(5, 4), C(6, 4), 1)
    assert bm.step_crosses_wall(C(5, 4), C(5, 5), 1)
    assert not bm.step_crosses_wall(C(5, 4), C(4, 4), 1)
    print("✅ test_diagonal_corner_rule passed")


def test_large_creature():
    bm = open_map()
    bm.set_edge_wall(C(5, 5), E)
    assert bm.is_blocked(C(5, 5), 2), "a Large creature can't stand across a wall"
    assert bm.is_blocked(C(5, 4), 2)
    assert not bm.is_blocked(C(5, 5), 1)
    assert not bm.is_blocked(C(5, 5), 2, rpg.MovementType.Burrow)

    # A gap one cell wide: Medium gets through, Large doesn't.
    bm.clear_edge_walls()
    east_wall(bm, 5, [r for r in range(12) if r != 5])
    medium = cells(bm.reachable_cells(C(3, 5), 1, 60, rpg.MovementType.Walk))
    assert (6, 5) in medium
    large = cells(bm.reachable_cells(C(3, 4), 2, 120, rpg.MovementType.Walk))
    assert not any(c >= 5 for c, _ in large), f"Large squeezed through a 5-ft gap: {sorted(large)}"
    # ... but walks along the wall.
    assert (4, 0) in large and (4, 9) in large
    print("✅ test_large_creature passed")


def test_jump_stops_at_an_edge():
    for walled in (False, True):
        bm = open_map(); engine = setup_combat_engine()
        j = add_agent_to_battle(engine, bm, create_test_agent("Jumper", 4, 5))
        ready(engine, bm, j, walk=60, strength=20)
        if walled:
            east_wall(bm, 5, [5])
        ok = bm.jump_agent(j, C(7, 5), True)
        assert ok == (not walled), f"walled={walled}: jump returned {ok}"
    print("✅ test_jump_stops_at_an_edge passed")


def test_push_stops_at_an_edge():
    for walled, expect in ((False, 2), (True, 0)):
        bm = open_map(); engine = setup_combat_engine()
        v = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 5))
        if walled:
            east_wall(bm, 5, [5])
        moved = bm.force_move_agent(v, C(4, 5), 10)
        assert moved == expect, f"walled={walled}: pushed {moved} cells"
    print("✅ test_push_stops_at_an_edge passed")


# ── Sight and reach ──────────────────────────────────────────────────────────
def test_line_of_sight():
    bm = open_map()
    east_wall(bm, 5, range(12))
    assert not bm.has_line_of_sight(C(3, 5), 1, C(8, 5), 1)
    assert not bm.has_line_of_sight(C(3, 5), 1, C(8, 9), 1)
    assert not bm.has_line_of_sight(C(5, 5), 1, C(6, 5), 1), "adjacent across the wall"
    assert bm.has_line_of_sight(C(3, 2), 1, C(5, 9), 1), "along the wall, same side"
    # Through a corner: centres (4.5, 3.5) → (7.5, 6.5) pass exactly over grid point (5, 4).
    bm.clear_edge_walls()
    east_wall(bm, 4, [3, 4])          # straight wall through (5, 4)
    assert not bm.has_line_of_sight(C(4, 3), 1, C(7, 6), 1)
    assert not bm.has_line_of_sight(C(7, 6), 1, C(4, 3), 1), "symmetric"
    bm.clear_edge_walls()
    east_wall(bm, 4, [3])             # wall ends at (5, 4)
    assert bm.has_line_of_sight(C(4, 3), 1, C(7, 6), 1)
    assert bm.has_line_of_sight(C(7, 6), 1, C(4, 3), 1)
    print("✅ test_line_of_sight passed")


def test_line_of_sight_is_symmetric():
    bm = open_map()
    east_wall(bm, 5, [2, 3, 4])
    bm.set_edge_wall(C(7, 6), S)
    bm.set_edge_wall(C(8, 6), S)
    for a in [(1, 1), (3, 5), (4, 0), (6, 2), (9, 9)]:
        for b in [(8, 3), (7, 8), (10, 1), (6, 6), (2, 10)]:
            ab = bm.has_line_of_sight(C(*a), 1, C(*b), 1)
            ba = bm.has_line_of_sight(C(*b), 1, C(*a), 1)
            assert ab == ba, f"LOS {a}->{b} = {ab} but {b}->{a} = {ba}"
    print("✅ test_line_of_sight_is_symmetric passed")


def test_large_footprint_sees_round_its_own_edges():
    """An edge inside a footprint never blocks that creature's own sight."""
    bm = open_map()
    bm.set_edge_wall(C(4, 4), E)      # inside a 2×2 at (4, 4)
    assert bm.has_line_of_sight(C(4, 4), 2, C(8, 4), 1)
    print("✅ test_large_footprint_sees_round_its_own_edges passed")


def test_melee_and_ranged_attacks():
    w = create_melee_weapon()
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    bm = open_map()
    assert rpg.CombatEngine.can_attack(w, bm, C(5, 5), 1, C(6, 5), 1)
    bm.set_edge_wall(C(5, 5), E)
    assert not rpg.CombatEngine.can_attack(w, bm, C(5, 5), 1, C(6, 5), 1), "melee across a wall"
    assert rpg.CombatEngine.can_attack(w, bm, C(5, 5), 1, C(5, 6), 1)
    # Diagonal neighbours across a straight wall through the corner.
    east_wall(bm, 5, [4])
    assert not rpg.CombatEngine.can_attack(w, bm, C(5, 4), 1, C(6, 5), 1)
    print("✅ test_melee_and_ranged_attacks passed")


def test_area_and_vision():
    bm = open_map()
    bm.set_edge_wall(C(5, 5), E)
    kept = cells(bm.prune_blocked_cells([C(6, 5), C(4, 5)], rpg.Spell(), C(0, 0), 1, C(5, 5)))
    assert kept == {(4, 5)}, f"an area stops at the wall, got {kept}"
    east_wall(bm, 5, range(12))
    assert not bm.can_see(C(3, 5), 1, 0, 0, 0, C(8, 5), 1)
    assert bm.can_see(C(3, 5), 1, 0, 0, 0, C(1, 5), 1)
    print("✅ test_area_and_vision passed")


def test_no_opportunity_attack_across_a_wall():
    from test_reactions import ScriptedDecider, pick_weapon, equip_oa_weapon, ready_mover
    for walled in (False, True):
        bm = open_map(); engine = setup_combat_engine()
        m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
        t = add_agent_to_battle(engine, bm, create_test_agent("Threat", 4, 5))
        ready_mover(engine, bm, m)
        equip_oa_weapon(engine, bm, t)
        if walled:
            east_wall(bm, 4, range(12))
        dec = ScriptedDecider(pick_weapon)
        engine.set_decider(dec)
        engine.resolve_move(bm, m, C(7, 5), rpg.MovementType.Walk)
        reactors = [s[0] for s in dec.seen]
        assert reactors == ([] if walled else [t]), f"walled={walled}: reactors={reactors}"
    print("✅ test_no_opportunity_attack_across_a_wall passed")


def test_grapple_shove_and_net_need_a_clear_reach():
    for walled in (False, True):
        bm = open_map(); engine = setup_combat_engine()
        a = add_agent_to_battle(engine, bm, create_test_agent("Wrestler", 5, 5))
        t = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
        if walled:
            bm.set_edge_wall(C(5, 5), E)
        wall_msg = "A wall is in the way."
        c = engine.get_agent_conditions(bm, t)
        c.netted = True
        c.net_escape_dc = 10
        engine.set_agent_conditions(bm, t, c)
        assert engine.escape_net(bm, a, t).valid == (not walled), f"escape_net walled={walled}"

        g = rpg.GrappleAction(); g.attacker_idx = a; g.target_idx = t
        assert (engine.execute_grapple(bm, g).log_message == wall_msg) == walled, f"grapple walled={walled}"
        sh = rpg.ShoveAction(); sh.attacker_idx = a; sh.target_idx = t
        assert (engine.execute_shove(bm, sh).log_message == wall_msg) == walled, f"shove walled={walled}"

    print("✅ test_grapple_shove_and_net_need_a_clear_reach passed")


# ── Doors on edges ───────────────────────────────────────────────────────────
def test_edge_door():
    bm = open_map()
    did = bm.add_edge_door([rpg.Edge(C(5, 5), E)])
    door = bm.doors[bm.door_at_edge(C(5, 5), E)]
    assert door.id == did and door.cells == [] and (door.cell.col, door.cell.row) == (5, 5)
    assert bm.edge_between(C(5, 5), C(6, 5)), "a closed edge door blocks"
    assert not bm.has_line_of_sight(C(5, 5), 1, C(6, 5), 1)
    assert bm.open_door(did)
    assert not bm.edge_between(C(5, 5), C(6, 5)), "an open edge door passes"
    assert bm.has_line_of_sight(C(5, 5), 1, C(6, 5), 1)
    assert bm.close_door(did)
    assert bm.edge_between(C(5, 5), C(6, 5))
    assert bm.open_door(did)
    assert not bm.edge_between(C(5, 5), C(6, 5)), "open → close → open"
    print("✅ test_edge_door passed")


def test_edge_door_overrides_the_detected_wall():
    bm = open_map()
    bm.set_edge_wall(C(5, 5), E)                 # the door icon, detected as wall
    did = bm.add_edge_door([rpg.Edge(C(5, 5), E)], open=True)
    assert not bm.edge_between(C(5, 5), C(6, 5)), "the open door wins over the wall under it"
    bm.clear_edge_walls()                        # a re-detect keeps the door
    bm.close_door(did)
    assert bm.edge_between(C(5, 5), C(6, 5))
    bm.set_edge_wall(C(5, 5), E)
    bm.remove_door(did)
    assert bm.edge_between(C(5, 5), C(6, 5)), "removing the door leaves the static wall"
    assert bm.door_at_edge(C(5, 5), E) == -1
    print("✅ test_edge_door_overrides_the_detected_wall passed")


def test_wide_edge_door_and_replacement():
    bm = open_map()
    edges = [rpg.Edge(C(5, r), E) for r in (4, 5)]
    a = bm.add_edge_door(edges)
    assert all(bm.edge_between(C(5, r), C(6, r)) for r in (4, 5))
    b = bm.add_edge_door([rpg.Edge(C(5, 5), E)], open=True)   # replaces the wide door
    assert [d.id for d in bm.doors] == [b]
    assert not bm.edge_between(C(5, 4), C(6, 4)), "the replaced door's edges are released"
    assert a != b
    print("✅ test_wide_edge_door_and_replacement passed")


def test_cell_doors_unchanged():
    bm = open_map()
    did = bm.add_door(C(3, 3))
    assert bm.is_blocked(C(3, 3), 1) and not bm.has_edge_walls
    bm.open_door(did)
    assert not bm.is_blocked(C(3, 3), 1)
    assert bm.doors[0].edges == []
    print("✅ test_cell_doors_unchanged passed")


def test_regrid_drops_walls_and_keeps_doors():
    bm = open_map()
    bm.set_edge_wall(C(2, 2), E)
    bm.add_edge_door([rpg.Edge(C(5, 5), E)])
    bm.analyze_grid()
    assert bm.edge_walls == []
    assert bm.edge_between(C(5, 5), C(6, 5)), "the closed edge door re-applies on the new grid"
    print("✅ test_regrid_drops_walls_and_keeps_doors passed")


# ── NPC automation ───────────────────────────────────────────────────────────
def test_npc_does_not_fight_through_a_wall():
    bm = open_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    engine.set_agent_weapons(bm, npc, [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    bm.set_agent_npc_automated(npc, True)
    east_wall(bm, 6, range(2, 9))      # between the two, rows 2..8

    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t, pos(bm, a))))
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    path = bm.last_move_path
    for a, b in zip(path, path[1:]):
        assert not bm.step_crosses_wall(a, b, 1), f"NPC route crosses the wall at {a}->{b}"
    for a, t, at in calls:
        assert bm.has_line_of_sight(C(*at), 1, C(7, 5), 1), f"NPC attacked through the wall from {at}"
    print("✅ test_npc_does_not_fight_through_a_wall passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    print("Running Edge Wall Tests...")
    print("=" * 60)
    passed = failed = 0
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
