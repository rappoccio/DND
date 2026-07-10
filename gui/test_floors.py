#!/usr/bin/env python3
"""
Tests for the multi-map dungeon manifest (gui/dungeon.py) — the placement layer the
Phase 3 paging UI drives (FLOORS_IMPLEMENTATION_PLAN.md). Pure Python: no engine / GUI.

Covers global<->local conversion, footprint containment, same-floor neighbour adjacency
(with largest-overlap tie-break), floor enumeration, page lookup by global cell, the
entry-page fallback/repair, and a save/load round-trip. Phase 4 adds ladder (vertical
portal) target resolution + JSON round-trip; Phase 5 adds cross-map door staples
(horizontal links) — auto-target derivation, neighbour resolution, and JSON round-trip.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from dungeon import Dungeon, MapPage, dungeon_path_for


def _page(pid, gx, gy, z, cols=10, rows=10):
    return MapPage(id=pid, png=f"{pid}.png", encounter_base=f"{pid}_agents.json",
                   origin=[gx, gy, z], cols=cols, rows=rows)


def test_local_global_roundtrip():
    p = _page("A", gx=5, gy=7, z=0, cols=10, rows=10)
    # local (0,0) sits at the origin.
    assert p.local_to_global(0, 0) == (5, 7, 0)
    assert p.local_to_global(3, 4) == (8, 11, 0)
    # global -> local is the inverse inside the footprint.
    assert p.global_to_local(8, 11, 0) == (3, 4)
    # Out of footprint / wrong floor -> None.
    assert p.global_to_local(4, 7, 0) is None     # left of origin
    assert p.global_to_local(15, 7, 0) is None    # == gx+cols, half-open upper bound
    assert p.global_to_local(8, 11, 1) is None     # wrong floor
    assert p.contains_global(5, 7, 0) is True
    assert p.contains_global(14, 16, 0) is True    # last in-bounds cell
    assert p.contains_global(15, 16, 0) is False
    print("  ✅ local/global conversion + containment")


def test_neighbor_adjacency():
    #  A | B   on floor 0; C sits directly below A on floor 0.
    A = _page("A", 0, 0, 0, cols=10, rows=10)
    B = _page("B", 10, 0, 0, cols=10, rows=10)     # abuts A's right edge
    C = _page("C", 0, 10, 0, cols=10, rows=10)     # abuts A's bottom edge
    d = Dungeon(pages=[A, B, C])
    assert d.neighbor(A, "right") is B
    assert d.neighbor(B, "left") is A
    assert d.neighbor(A, "down") is C
    assert d.neighbor(C, "up") is A
    assert d.neighbor(A, "up") is None
    assert d.neighbor(A, "left") is None
    assert d.neighbor(B, "right") is None
    print("  ✅ neighbour adjacency (left/right/up/down)")


def test_neighbor_largest_overlap():
    # A spans rows [0,10). Two right-neighbours abut its right edge: B1 overlaps rows
    # [0,3) (3 cells), B2 overlaps rows [3,10) (7 cells). The larger overlap wins.
    A = _page("A", 0, 0, 0, cols=10, rows=10)
    B1 = _page("B1", 10, 0, 0, cols=10, rows=3)
    B2 = _page("B2", 10, 3, 0, cols=10, rows=7)
    d = Dungeon(pages=[A, B1, B2])
    assert d.neighbor(A, "right") is B2
    print("  ✅ neighbour tie-break by largest edge overlap")


def test_neighbor_ignores_other_floors():
    A = _page("A", 0, 0, 0)
    B_up = _page("Bup", 10, 0, 1)     # abuts in (X,Y) but a different floor
    d = Dungeon(pages=[A, B_up])
    assert d.neighbor(A, "right") is None
    print("  ✅ neighbour ignores pages on other floors")


def test_floors_and_page_lookup():
    A = _page("A", 0, 0, 0)
    B = _page("B", 0, 0, 1)
    C = _page("C", 0, 0, -1)
    d = Dungeon(pages=[A, B, C])
    assert d.floors() == [-1, 0, 1]
    assert d.pages_on_floor(1) == [B]
    # A ladder up from A's (5,5) resolves to B (same global X,Y, z+1).
    assert d.page_at_global(5, 5, 1) is B
    assert d.page_at_global(5, 5, 0) is A
    assert d.page_at_global(99, 99, 0) is None
    print("  ✅ floor enumeration + page_at_global")


def test_entry_page_fallback_and_repair():
    A = _page("A", 0, 0, 0)
    B = _page("B", 10, 0, 0)
    d = Dungeon(pages=[A, B], entry_page_id="B")
    assert d.entry_page() is B
    # A dangling entry pointer falls back to the first page.
    d2 = Dungeon(pages=[A, B], entry_page_id="nonexistent")
    assert d2.entry_page() is A
    # Empty dungeon: no entry.
    assert Dungeon().entry_page() is None
    print("  ✅ entry-page fallback + dangling-pointer repair")


def test_add_remove_page_keeps_entry_valid():
    d = Dungeon()
    d.add_page(_page("A", 0, 0, 0))
    assert d.entry_page_id == "A"          # first page becomes the entry
    d.add_page(_page("B", 10, 0, 0))
    d.remove_page("A")                     # removing the entry re-points it
    assert d.entry_page_id == "B"
    d.remove_page("B")
    assert d.entry_page_id is None         # empty again
    print("  ✅ add/remove page keeps entry pointer valid")


def test_save_load_roundtrip():
    A = _page("A", 3, 4, 0, cols=12, rows=8)
    B = _page("B", 15, 4, 1, cols=6, rows=9)
    d = Dungeon(pages=[A, B], entry_page_id="B")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "crypt.dungeon.json")
        d.save(path)
        loaded = Dungeon.load(path)
    assert loaded.entry_page_id == "B"
    assert [p.id for p in loaded.pages] == ["A", "B"]
    pa = loaded.page_by_id("A")
    assert pa.origin == [3, 4, 0] and pa.cols == 12 and pa.rows == 8
    assert loaded.page_by_id("B").origin == [15, 4, 1]
    print("  ✅ save/load round-trip preserves pages + entry")


def _auto_ladder_target(page, col, row, going_up):
    """Mirror the editor's ladder auto-target: same global (X,Y), one floor up/down.
    (gui/terrain_dialogs.py TerrainEditorDialog._place_ladder does exactly this.)"""
    gx, gy, z = page.local_to_global(col, row)
    return [gx, gy, z + (1 if going_up else -1)]


def _resolve_ladder(dungeon, target):
    """Mirror main.py _use_ladder's resolution chain: global target -> (page, local)."""
    X, Y, Z = target
    page = dungeon.page_at_global(X, Y, Z)
    if page is None:
        return None
    local = page.global_to_local(X, Y, Z)
    if local is None:
        return None
    return (page, local)


def test_ladder_resolves_to_page_and_cell():
    # A (floor 0) has B directly above it (floor 1) sharing the same global origin.
    A = _page("A", gx=4, gy=2, z=0, cols=10, rows=10)
    B = _page("B", gx=4, gy=2, z=1, cols=10, rows=10)
    d = Dungeon(pages=[A, B])
    # A ladder placed on A's local (3, 5) going up targets the same global X,Y on z+1.
    target = _auto_ladder_target(A, 3, 5, going_up=True)
    assert target == [7, 7, 1]                       # (4+3, 2+5, 0+1)
    page, local = _resolve_ladder(d, target)
    assert page is B
    assert local == (3, 5)                           # lands on B's matching local cell
    print("  ✅ ladder resolves to the right page + cell (up)")


def test_ladder_down_resolves():
    # C sits below A on floor -1, offset so global coords still line up.
    A = _page("A", gx=0, gy=0, z=0, cols=10, rows=10)
    C = _page("C", gx=0, gy=0, z=-1, cols=10, rows=10)
    d = Dungeon(pages=[A, C])
    target = _auto_ladder_target(A, 8, 1, going_up=False)
    assert target == [8, 1, -1]
    page, local = _resolve_ladder(d, target)
    assert page is C and local == (8, 1)
    print("  ✅ ladder resolves downward to a lower floor")


def test_ladder_target_off_map():
    A = _page("A", gx=0, gy=0, z=0, cols=10, rows=10)
    B = _page("B", gx=0, gy=0, z=1, cols=4, rows=4)   # smaller page on floor 1
    d = Dungeon(pages=[A, B])
    # A ladder over A's (8,8) going up targets (8,8,1) — outside B's 4x4 footprint.
    off = _auto_ladder_target(A, 8, 8, going_up=True)
    assert _resolve_ladder(d, off) is None            # no page covers that global cell
    # Its (2,2) counterpart lands inside B.
    on = _auto_ladder_target(A, 2, 2, going_up=True)
    page, local = _resolve_ladder(d, on)
    assert page is B and local == (2, 2)
    print("  ✅ ladder target off the destination footprint resolves to nothing")


def test_ladder_json_roundtrip():
    # The _terrain.json ladder shape survives a JSON dump/load unchanged (main.py
    # _normalize_ladders re-coerces cells to tuples; here we assert the on-disk shape).
    ladders = [{"cells": [[3, 5]], "target": [7, 7, 1]},
               {"cells": [[8, 1]], "target": [8, 1, -1]}]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "crypt_terrain.json")
        with open(path, "w") as f:
            json.dump({"ladders": ladders}, f)
        with open(path) as f:
            loaded = json.load(f)["ladders"]
    assert loaded == ladders
    print("  ✅ ladder JSON round-trip preserves cells + target")


def _auto_door_link_target(page, col, row):
    """Mirror the editor's cross-map door auto-target (terrain_dialogs.py
    TerrainEditorDialog._door_link_target): the global cell one step beyond whichever
    page edge the door cell touches, or None if the cell is interior (nothing to link)."""
    ox, oy, z = page.origin
    if col <= 0:
        return [ox + col - 1, oy + row, z]
    if col >= page.cols - 1:
        return [ox + col + 1, oy + row, z]
    if row <= 0:
        return [ox + col, oy + row - 1, z]
    if row >= page.rows - 1:
        return [ox + col, oy + row + 1, z]
    return None


def test_door_link_resolves_to_neighbor():
    # A | B abut on floor 0. A door on A's right edge staples to B's matching cell.
    A = _page("A", gx=0, gy=0, z=0, cols=10, rows=10)
    B = _page("B", gx=10, gy=0, z=0, cols=10, rows=10)
    d = Dungeon(pages=[A, B])
    target = _auto_door_link_target(A, 9, 4)          # A's right-edge local (9,4)
    assert target == [10, 4, 0]                       # (0+9+1, 0+4, 0)
    page, local = _resolve_ladder(d, target)          # same global->page+local chain
    assert page is B
    assert local == (0, 4)                            # B's matching left-edge cell
    print("  ✅ linked door resolves to the neighbour page's matching cell")


def test_door_link_left_edge_resolves():
    # A door on B's left edge (col 0) staples back to A across the shared boundary.
    A = _page("A", gx=0, gy=0, z=0, cols=10, rows=10)
    B = _page("B", gx=10, gy=0, z=0, cols=10, rows=10)
    d = Dungeon(pages=[A, B])
    target = _auto_door_link_target(B, 0, 6)          # B local (0,6) -> global (10,6)
    assert target == [9, 6, 0]                        # one cell left -> into A
    page, local = _resolve_ladder(d, target)
    assert page is A and local == (9, 6)
    print("  ✅ linked door resolves leftward to the abutting page")


def test_door_link_interior_has_no_target():
    A = _page("A", gx=0, gy=0, z=0, cols=10, rows=10)
    assert _auto_door_link_target(A, 5, 5) is None    # interior cell: nothing to link
    print("  ✅ interior door has no cross-map link target")


def test_door_link_json_roundtrip():
    # A door terrain record carries link_target (null for ordinary doors); it survives a
    # JSON dump/load unchanged (main.py _save_terrain / _load_terrain shape).
    doors = [
        {"cells": [[9, 4]], "cell": [9, 4], "open": False, "locked": False,
         "lock_dc": 15, "arcane_lock": False, "link_target": [10, 4, 0]},
        {"cells": [[2, 2]], "cell": [2, 2], "open": True, "locked": False,
         "lock_dc": 15, "arcane_lock": False, "link_target": None},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "crypt_terrain.json")
        with open(path, "w") as f:
            json.dump({"doors": doors}, f)
        with open(path) as f:
            loaded = json.load(f)["doors"]
    assert loaded == doors
    assert loaded[0]["link_target"] == [10, 4, 0]
    assert loaded[1]["link_target"] is None
    print("  ✅ door link_target JSON round-trip (staple + ordinary)")


def test_dungeon_path_for():
    # Derives the sibling manifest from an encounter base, a PNG, or a bare name.
    assert dungeon_path_for("/maps/crypt_agents.json") == "/maps/crypt.dungeon.json"
    assert dungeon_path_for("/maps/crypt.png") == "/maps/crypt.dungeon.json"
    assert dungeon_path_for("/maps/crypt") == "/maps/crypt.dungeon.json"
    print("  ✅ dungeon_path_for derivation")


def main():
    tests = [
        test_local_global_roundtrip,
        test_neighbor_adjacency,
        test_neighbor_largest_overlap,
        test_neighbor_ignores_other_floors,
        test_floors_and_page_lookup,
        test_entry_page_fallback_and_repair,
        test_add_remove_page_keeps_entry_valid,
        test_save_load_roundtrip,
        test_ladder_resolves_to_page_and_cell,
        test_ladder_down_resolves,
        test_ladder_target_off_map,
        test_ladder_json_roundtrip,
        test_door_link_resolves_to_neighbor,
        test_door_link_left_edge_resolves,
        test_door_link_interior_has_no_target,
        test_door_link_json_roundtrip,
        test_dungeon_path_for,
    ]
    print("Running dungeon-manifest (floors) tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} floors tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
