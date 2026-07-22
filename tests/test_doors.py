#!/usr/bin/env python3
"""
Test suite for lockable doors (DOORS_IMPLEMENTATION_PLAN).

A door is a doorway CELL whose blocking is expressed through its TerrainType
(Standard when open, Wall when closed/locked), so movement and LOS need no
door-specific logic. The Door struct is the source of truth for state.

Phase 3 adds the Sleight of Hand skill + CombatEngine.attempt_pick_lock:
roll(20) + sleight_of_hand() vs the door's lock_dc; on success the mundane lock
is removed (the door stays closed until opened).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── Phase 3a: the Sleight of Hand skill bonus ────────────────────────────────

def test_sleight_of_hand_bonus():
    """sleightOfHand() = DEX mod + prof (+ prof again with expertise)."""
    s = rpg.Stats()
    s.dex = 16          # +3
    s.prof_bonus = 3
    assert s.sleight_of_hand() == 3, "no proficiency → DEX mod only"

    s.sleight_of_hand_prof = True
    assert s.sleight_of_hand() == 6, "proficiency adds prof_bonus once"

    s.sleight_of_hand_expertise = True
    assert s.sleight_of_hand() == 9, "expertise adds prof_bonus a second time"
    print("✅ sleight_of_hand bonus calculation correct")


# ── Phase 1: door state ↔ terrain ────────────────────────────────────────────

def test_closed_door_blocks_open_door_clears():
    """A closed door cell is a Wall; opening it restores Standard terrain."""
    bm = setup_battle_map()
    cell = rpg.Cell(4, 4)

    did = bm.add_door(cell, False, False, 15, False)  # closed, unlocked
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Wall, "closed door cell should be a Wall"
    assert bm.door_at(cell) >= 0, "door_at should locate the door"

    assert bm.open_door(did), "an unlocked door should open"
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Standard, "open door cell should be Standard"
    print("✅ closed door blocks, open door clears terrain")


def test_locked_door_will_not_open():
    """open_door fails on a locked door; it stays a Wall."""
    bm = setup_battle_map()
    cell = rpg.Cell(5, 5)
    did = bm.add_door(cell, False, True, 15, False)  # closed, locked
    assert not bm.open_door(did), "a locked door must not open"
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Wall, "locked door stays a Wall"
    print("✅ locked door refuses to open")


# ── Phase 3b: pick the lock ──────────────────────────────────────────────────

def test_pick_lock_success():
    """A skilled rogue beats a DC 1 lock and unlocks the door (still closed)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 3, 3))
    s = engine.get_agent_stats(bm, idx)
    s.dex = 20
    s.sleight_of_hand_prof = True
    s.sleight_of_hand_expertise = True
    engine.set_agent_stats(bm, idx, s)

    cell = rpg.Cell(6, 6)
    did = bm.add_door(cell, False, True, 1, False)  # trivial DC

    res = engine.attempt_pick_lock(bm, idx, did)
    assert res.valid, "result should be valid"
    assert res.success, f"DC 1 lock should be picked: {res.log_message}"
    assert res.total >= res.dc

    # Lock removed but door still shut, so still a Wall until opened.
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Wall, "door stays closed after picking"
    assert bm.open_door(did), "now-unlocked door opens"
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Standard
    print("✅ pick lock success unlocks (door stays closed until opened)")


def test_pick_lock_failure():
    """An unskilled agent cannot beat a DC 30 lock; it stays locked."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Oaf", 3, 3))
    s = engine.get_agent_stats(bm, idx)
    s.dex = 6  # -2, no proficiency
    engine.set_agent_stats(bm, idx, s)

    cell = rpg.Cell(7, 7)
    did = bm.add_door(cell, False, True, 30, False)

    res = engine.attempt_pick_lock(bm, idx, did)
    assert res.valid
    assert not res.success, "DC 30 lock should be unpickable here"
    assert not bm.open_door(did), "door remains locked after a failed pick"
    print("✅ pick lock failure leaves the door locked")


def test_arcane_lock_cannot_be_picked():
    """An Arcane Lock blocks mundane lockpicking outright."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 3, 3))
    s = engine.get_agent_stats(bm, idx)
    s.dex = 20
    s.sleight_of_hand_prof = True
    engine.set_agent_stats(bm, idx, s)

    cell = rpg.Cell(8, 8)
    did = bm.add_door(cell, False, True, 1, True)  # arcane-locked, trivial DC

    res = engine.attempt_pick_lock(bm, idx, did)
    assert res.valid
    assert not res.success, "an Arcane Lock cannot be picked even at DC 1"
    print("✅ arcane lock cannot be picked")


def test_pick_unlocked_door_is_noop():
    """Picking an already-unlocked door reports valid but no success."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 3, 3))

    cell = rpg.Cell(9, 9)
    did = bm.add_door(cell, False, False, 15, False)  # unlocked
    res = engine.attempt_pick_lock(bm, idx, did)
    assert res.valid
    assert not res.success, "nothing to pick on an unlocked door"
    print("✅ picking an unlocked door is a no-op")


# ── Wide (multi-cell) doors ──────────────────────────────────────────────────

def test_wide_door_spans_all_cells():
    """A door spanning several cells blocks every cell when closed and clears them all
    when opened, and door_at locates it from any of its cells."""
    bm = setup_battle_map()
    cells = [rpg.Cell(2, 7), rpg.Cell(3, 7), rpg.Cell(4, 7), rpg.Cell(5, 7)]

    did = bm.add_door(cells, False, False, 15, False)  # closed, unlocked, 4 wide
    for c in cells:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Wall, "every closed cell is a Wall"
        assert bm.door_at(c) >= 0, "door_at finds the door from any of its cells"

    door = bm.doors[bm.door_at(cells[0])]
    assert len(door.cells) == 4, "door should record all 4 cells"
    assert door.cell.col == 2 and door.cell.row == 7, "anchor is the first cell"

    assert bm.open_door(did), "an unlocked wide door opens"
    for c in cells:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Standard, "every cell clears when open"
    print("✅ wide door spans and toggles all its cells")


def test_wide_door_removed_clears_all_cells():
    """Removing a wide door restores Standard terrain on every cell."""
    bm = setup_battle_map()
    cells = [rpg.Cell(6, 2), rpg.Cell(6, 3)]  # vertical double door
    did = bm.add_door(cells, False, False, 15, False)
    bm.remove_door(did)
    for c in cells:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Standard, "removed cells become Standard"
        assert bm.door_at(c) < 0, "no door remains at the cell"
    print("✅ removing a wide door clears all its cells")


def test_overlapping_door_replaces_previous():
    """add_door replaces any door overlapping the new cells (no stacking)."""
    bm = setup_battle_map()
    bm.add_door([rpg.Cell(1, 1), rpg.Cell(2, 1)], False, False, 15, False)
    bm.add_door([rpg.Cell(2, 1), rpg.Cell(3, 1)], False, False, 15, False)  # overlaps cell (2,1)
    assert len(bm.doors) == 1, "the overlapping door replaced the first"
    door = bm.doors[0]
    assert {(c.col, c.row) for c in door.cells} == {(2, 1), (3, 1)}
    print("✅ overlapping door placement replaces the previous door")


if __name__ == "__main__":
    tests = [
        test_sleight_of_hand_bonus,
        test_closed_door_blocks_open_door_clears,
        test_locked_door_will_not_open,
        test_pick_lock_success,
        test_pick_lock_failure,
        test_arcane_lock_cannot_be_picked,
        test_pick_unlocked_door_is_noop,
        test_wide_door_spans_all_cells,
        test_wide_door_removed_clears_all_cells,
        test_overlapping_door_replaces_previous,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} door tests passed")
    sys.exit(1 if failed else 0)
