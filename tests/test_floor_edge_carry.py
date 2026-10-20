#!/usr/bin/env python3
"""Carrying edge walls from one floor of a dungeon to the next.

The floors of one dungeon are drawn alike and share a global grid, so the first time the
terrain editor opens on a floor (App._maybe_carry_edges) it starts from the nearest edited
floor's final edges, moved through the page origins:

  · the page keeps its own grid and runs its own detection; the carried edges become its
    edge overrides, so its final edges are the reference floor's;
  · edges where the two disagree are listed in "edge_review" (drawn blue);
  · a floor with no detection borrows the reference's settings and turns walls on;
  · offset origins move the edges by the origin difference;
  · it runs once per page ("edges_carried_from"), never on the entry floor, and never
    on a floor that already has edits of its own;
  · editing a blue edge, or [Y], takes it off the review list, and an edge with a
    blocked cell on both sides is never on it;
  · nothing already on a floor is overwritten: its own detection settings and Walls
    choice stand, the reference floor's file is only read, and the page's file is
    copied to <file>.before_carry before the first write.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

from main import App
from dungeon import Dungeon, MapPage

# Same page as test_drawn_wall_detection: 10×8 cells of 30 px, a building whose outer
# wall is a 4 px stroke on grid lines X0..X1 × Y0..Y1.
CELL = 30
COLS, ROWS = 10, 8
X0, X1, Y0, Y1 = 2, 8, 2, 6
WALL_GREY = (70, 70, 70)
PAPER = (200, 195, 185)
DETECTION = {"mode": "dark_fraction", "dark_level": 100, "dark_fraction": 0.6,
             "edge_walls": True, "edge_fraction": 0.3, "edge_halfwidth_px": 4,
             "outside_seeds": [[0, 0]]}
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
HAND_EDGE = (4, 3, "E")          # added by hand on floor 0; not drawn on either image
GAP_EDGE = (X0 - 1, 3, "E")      # drawn on floor 0, missing from floor 1's image


def _png(tmp, name, gap=False):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill(PAPER)
    for x in (X0 * CELL, X1 * CELL):
        for r in range(Y0, Y1):
            if gap and x == X0 * CELL and r == 3:
                continue
            surf.fill(WALL_GREY, pygame.Rect(x - 2, r * CELL, 4, CELL))
    for y in (Y0 * CELL, Y1 * CELL):
        surf.fill(WALL_GREY, pygame.Rect(X0 * CELL - 2, y - 2, (X1 - X0) * CELL + 4, 4))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _outer_edges():
    edges = set()
    for r in range(Y0, Y1):
        edges.add((X0 - 1, r, "E"))
        edges.add((X1 - 1, r, "E"))
    for c in range(X0, X1):
        edges.add((c, Y0 - 1, "S"))
        edges.add((c, Y1 - 1, "S"))
    return edges


def _write(tmp, page_id, doc):
    with open(os.path.join(tmp, f"{page_id}_terrain.json"), "w") as f:
        json.dump(doc, f)


def _read(tmp, page_id):
    with open(os.path.join(tmp, f"{page_id}_terrain.json")) as f:
        return json.load(f)


def _dungeon(tmp, f0_doc, f1_doc=None, f1_origin=(0, 0, 1)):
    """An app on page f0 (drawn.png) with f1 (drawn_gap.png) at ``f1_origin``."""
    p0 = _png(tmp, "drawn.png")
    p1 = _png(tmp, "drawn_gap.png", gap=True)
    _write(tmp, "f0", f0_doc)
    _write(tmp, "f1", f1_doc if f1_doc is not None
           else {"regions": [], "walls_enabled": False, "manual_grid": GRID})
    app = App(p0, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    pages = [MapPage("f0", p0, "f0_agents.json", [0, 0, 0], COLS, ROWS),
             MapPage("f1", p1, "f1_agents.json", list(f1_origin), COLS, ROWS)]
    app.dungeon = Dungeon(pages=pages, entry_page_id="f0")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _f0_edited():
    return {"regions": [], "walls_enabled": True, "manual_grid": GRID,
            "detection": DETECTION, "edge_overrides": {"add": [list(HAND_EDGE)], "remove": []}}


def _go(app, page_id):
    assert app._switch_to_page(app.dungeon.page_by_id(page_id))


def test_first_edit_carries_the_floor_below():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, _f0_edited())
        _go(app, "f1")
        app._open_terrain_editor()
        final = app._edge_set(app.bm)
        assert final == _outer_edges() | {HAND_EDGE}, "f1 starts with f0's final edges"
        review = {tuple(e) for e in app._edge_review}
        assert review == {HAND_EDGE, GAP_EDGE}, review
        assert app._walls_enabled and app._detection["mode"] == "dark_fraction"
        app._close_terrain_editor()
        doc = _read(tmp, "f1")
        assert doc["edges_carried_from"] == ["f0"]
        assert {tuple(e) for e in doc["edge_review"]} == {HAND_EDGE, GAP_EDGE}
        assert {tuple(e) for e in doc["edge_overrides"]["add"]} == {HAND_EDGE, GAP_EDGE}
    print("✅ test_first_edit_carries_the_floor_below passed")


def test_it_runs_once():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, _f0_edited())
        _go(app, "f1")
        app._open_terrain_editor()
        app.terrain_editor._set_edges([HAND_EDGE], False)     # the DM removes one
        app._close_terrain_editor()
        app._open_terrain_editor()
        assert HAND_EDGE not in app._edge_set(app.bm), "a second open doesn't re-carry"
        app._close_terrain_editor()
    print("✅ test_it_runs_once passed")


def test_editing_and_accepting_clear_blue():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, _f0_edited())
        _go(app, "f1")
        app._open_terrain_editor()
        ed = app.terrain_editor
        ed._set_edges([HAND_EDGE], False)
        assert {tuple(e) for e in app._edge_review} == {GAP_EDGE}, "edited ⇒ decided"
        ed._undo_edges()
        assert {tuple(e) for e in app._edge_review} == {HAND_EDGE, GAP_EDGE}, "undo restores"
        ed._accept_review()
        assert app._edge_review == []
        assert app._edge_set(app.bm) == _outer_edges() | {HAND_EDGE}, "[Y] keeps the edges"
        app._close_terrain_editor()
        assert "edge_review" not in _read(tmp, "f1")
    print("✅ test_editing_and_accepting_clear_blue passed")


def test_offset_origins_move_the_edges():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, _f0_edited(), f1_origin=(1, 0, 1))
        _go(app, "f1")
        app._open_terrain_editor()
        final = app._edge_set(app.bm)
        moved = {(c - 1, r, s) for (c, r, s) in _outer_edges() | {HAND_EDGE}}
        assert final == {k for k in moved if app._edge_in_grid(k, COLS, ROWS)}, final
        app._close_terrain_editor()
    print("✅ test_offset_origins_move_the_edges passed")


def test_no_carry_on_the_entry_floor_or_an_edited_floor():
    with tempfile.TemporaryDirectory() as tmp:
        f0 = {"regions": [], "walls_enabled": True, "manual_grid": GRID, "detection": DETECTION}
        f1 = dict(_f0_edited())
        app = _dungeon(tmp, f0, f1)
        app._open_terrain_editor()                         # f0 is the entry floor
        assert not app._edge_review and not app._edges_carried_from
        app._close_terrain_editor()
        _go(app, "f1")
        app._open_terrain_editor()                         # f1 has edits of its own
        assert not app._edges_carried_from
        app._close_terrain_editor()
    print("✅ test_no_carry_on_the_entry_floor_or_an_edited_floor passed")


def test_no_carry_without_a_grid():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, _f0_edited(), {"regions": [], "walls_enabled": False})
        _go(app, "f1")
        app._open_terrain_editor()
        assert not app._edges_carried_from, "cells aren't fixed until Set Grid"
        app._close_terrain_editor()
    print("✅ test_no_carry_without_a_grid passed")


def test_existing_work_is_not_overwritten():
    with tempfile.TemporaryDirectory() as tmp:
        own = dict(DETECTION, dark_fraction=0.5, outside_seeds=[[9, 7]])
        f1 = {"regions": [], "walls_enabled": True, "manual_grid": GRID, "detection": own}
        app = _dungeon(tmp, _f0_edited(), f1)
        _go(app, "f1")                       # leaving f0 saves it: snapshot after that
        f0_before = _read(tmp, "f0")
        f1_before = _read(tmp, "f1")
        app._open_terrain_editor()
        assert app._edges_carried_from == ["f0"]
        assert app._detection == own, "the floor's own settings stand"
        app._close_terrain_editor()
        with open(os.path.join(tmp, "f1_terrain.json.before_carry")) as f:
            assert json.load(f) == f1_before, "a copy of the page from before the carry"
        assert _read(tmp, "f0") == f0_before, "the reference floor is only read"
    print("✅ test_existing_work_is_not_overwritten passed")


def test_a_floor_with_walls_off_by_choice_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        f1 = {"regions": [], "walls_enabled": False, "manual_grid": GRID, "detection": DETECTION}
        app = _dungeon(tmp, _f0_edited(), f1)
        _go(app, "f1")
        app._open_terrain_editor()
        assert not app._edges_carried_from and not app._walls_enabled
        app._close_terrain_editor()
        assert not os.path.exists(os.path.join(tmp, "f1_terrain.json.before_carry"))
    print("✅ test_a_floor_with_walls_off_by_choice_is_left_alone passed")


def test_edges_between_two_blocked_cells_are_not_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        f0 = _f0_edited()
        f0["edge_overrides"]["add"].append([0, 0, "E"])     # outside, flooded on both sides
        app = _dungeon(tmp, f0)
        _go(app, "f1")
        app._open_terrain_editor()
        assert (0, 0, "E") in app._edge_set(app.bm), "carried all the same"
        assert {tuple(e) for e in app._edge_review} == {HAND_EDGE, GAP_EDGE}
        app._close_terrain_editor()
    print("✅ test_edges_between_two_blocked_cells_are_not_flagged passed")


def test_a_right_drag_box_clears_the_blue_in_it():
    with tempfile.TemporaryDirectory() as tmp:
        f0 = _f0_edited()
        f0["edge_overrides"]["remove"] = [[X1 - 1, 3, "E"]]   # f0 opens its east wall at row 3
        # No outside seed on f1, so the opening doesn't flood the inside (that would block
        # both sides and take the edge off the blue list before the drag).
        f1 = {"regions": [], "walls_enabled": True, "manual_grid": GRID,
              "detection": dict(DETECTION, outside_seeds=[])}
        app = _dungeon(tmp, f0, f1)
        _go(app, "f1")
        app._open_terrain_editor()
        ed = app.terrain_editor
        east = (X1 - 1, 3, "E")                               # dashed: detected, carried open
        assert east in {tuple(e) for e in app._edge_review}
        assert east not in app._edge_set(app.bm)
        x = X1 * CELL
        ed.edge_drag = (3, (x - 5, 3 * CELL + 5), (x + 5, 4 * CELL - 5))
        ed._finish_edge_drag()
        assert east not in {tuple(e) for e in app._edge_review}, "box clears its blue"
        assert east not in app._edge_set(app.bm), "and the edge stays open"
        ed._undo_edges()
        assert east in {tuple(e) for e in app._edge_review}, "undo brings it back"
        app._close_terrain_editor()
    print("✅ test_a_right_drag_box_clears_the_blue_in_it passed")


def main():
    tests = [test_first_edit_carries_the_floor_below,
             test_it_runs_once,
             test_editing_and_accepting_clear_blue,
             test_offset_origins_move_the_edges,
             test_no_carry_on_the_entry_floor_or_an_edited_floor,
             test_no_carry_without_a_grid,
             test_existing_work_is_not_overwritten,
             test_a_floor_with_walls_off_by_choice_is_left_alone,
             test_edges_between_two_blocked_cells_are_not_flagged,
             test_a_right_drag_box_clears_the_blue_in_it]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n❌ test_floor_edge_carry: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_floor_edge_carry: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
