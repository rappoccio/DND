#!/usr/bin/env python3
"""Paired ladders: a ladder placed in the terrain editor gets its other end.

A ladder is a one-way portal stored in its own page's _terrain.json. Placing one on
floor 0 used to leave floor 1 without a way back down — the DM had to open floor 1 and
place the return ladder on the matching cell by hand, and remove it by hand too.

Closing the terrain editor (Esc → App._close_terrain_editor) now pairs what that session
changed:

  · an added ladder writes a return ladder onto the landing cell of the page it leads
    to, targeting the ladder's own global cell;
  · the landing is found by global (X, Y), so pages with offset origins pair correctly;
  · a removed ladder takes its return ladder with it — but only one that points back;
  · a landing cell that already holds a ladder is left alone;
  · no page under the target → the ladder stays one-way, and the DM is told;
  · ladders that existed before the editor opened are not touched;
  · the other page's terrain (regions etc.) survives the edit.
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

import rpg_battle_map as rpg

from main import App
from dungeon import Dungeon, MapPage

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261019


def _dungeon_app(tmp, upper_origin=(0, 0, 1), floors=2):
    """An app on page f0 of a dungeon in ``tmp``; f1 (if any) sits at ``upper_origin``.
    Every sidecar lands in ``tmp``, so nothing is written into maps/."""
    app = App(MAP_PATH, seed=SEED)
    app._dungeon_manifest_path = os.path.join(tmp, "crypt.dungeon.json")
    cols, rows = app.bm.grid_cols, app.bm.grid_rows
    pages = [MapPage("f0", MAP_PATH, "f0_agents.json", [0, 0, 0], cols, rows)]
    if floors > 1:
        pages.append(MapPage("f1", MAP_PATH, "f1_agents.json", list(upper_origin), cols, rows))
    app.dungeon = Dungeon(pages=pages, entry_page_id="f0")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _edit(app, *cells, up=True):
    """Open the terrain editor, click each cell in Ladder mode, close with Esc."""
    app._open_terrain_editor()
    ed = app.terrain_editor
    ed.ladder_up = up
    for c in cells:
        ed._place_ladder(rpg.Cell(*c))
    app._close_terrain_editor()


def _terrain(tmp, page_id):
    path = os.path.join(tmp, f"{page_id}_terrain.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _write_terrain(tmp, page_id, doc):
    with open(os.path.join(tmp, f"{page_id}_terrain.json"), "w") as f:
        json.dump(doc, f)


def test_a_placed_ladder_gets_a_return_ladder():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        _edit(app, (3, 5))
        assert app._ladders == [{"cells": [(3, 5)], "target": [3, 5, 1]}]
        assert _terrain(tmp, "f1")["ladders"] == [{"cells": [[3, 5]], "target": [3, 5, 0]}], \
            f"no return ladder on f1: {_terrain(tmp, 'f1')}"
        # And it works both ways in play: up to f1, then back down to f0.
        app._use_ladder(0, None)
        assert app.dungeon_page.id == "f1" and app._ladder_at(rpg.Cell(3, 5)) == 0
        app._use_ladder(0, None)
        assert app.dungeon_page.id == "f0"
    print("✅ test_a_placed_ladder_gets_a_return_ladder passed")


def test_a_down_ladder_pairs_too():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        app._switch_to_page(app.dungeon.page_by_id("f1"))
        _edit(app, (7, 2), up=False)
        assert _terrain(tmp, "f0")["ladders"] == [{"cells": [[7, 2]], "target": [7, 2, 1]}]
    print("✅ test_a_down_ladder_pairs_too passed")


def test_offset_pages_pair_by_global_cell():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp, upper_origin=(2, 1, 1))
        _edit(app, (3, 5))
        # Global (3, 5, 1) is f1's local (3-2, 5-1).
        assert _terrain(tmp, "f1")["ladders"] == [{"cells": [[1, 4]], "target": [3, 5, 0]}]
    print("✅ test_offset_pages_pair_by_global_cell passed")


def test_removing_a_ladder_removes_its_return():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        _edit(app, (3, 5), (6, 6))
        _edit(app, (3, 5))              # click an existing ladder: removes it
        assert app._ladders == [{"cells": [(6, 6)], "target": [6, 6, 1]}]
        assert _terrain(tmp, "f1")["ladders"] == [{"cells": [[6, 6]], "target": [6, 6, 0]}], \
            f"f1 kept the removed ladder's return: {_terrain(tmp, 'f1')['ladders']}"
    print("✅ test_removing_a_ladder_removes_its_return passed")


def test_an_occupied_landing_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        theirs = {"cells": [[3, 5]], "target": [3, 5, 2]}     # f1's own ladder, going up
        region = {"type": "Wall", "x": 0, "y": 0, "width": 50, "height": 50,
                  "multiplier": 0.0}
        _write_terrain(tmp, "f1", {"regions": [region], "ladders": [theirs]})
        app = _dungeon_app(tmp)
        _edit(app, (3, 5))
        assert "already has a ladder" in app._status_msg, app._status_msg
        assert _terrain(tmp, "f1") == {"regions": [region], "ladders": [theirs]}
        _edit(app, (3, 5))              # removing ours must not take f1's
        assert _terrain(tmp, "f1")["ladders"] == [theirs]
    print("✅ test_an_occupied_landing_is_left_alone passed")


def test_the_other_pages_terrain_survives():
    with tempfile.TemporaryDirectory() as tmp:
        region = {"type": "Chasm", "x": 10, "y": 10, "width": 40, "height": 40,
                  "multiplier": 0.0}
        _write_terrain(tmp, "f1", {"regions": [region], "walls_enabled": False,
                                   "explored": [[1, 1]]})
        app = _dungeon_app(tmp)
        _edit(app, (3, 5))
        doc = _terrain(tmp, "f1")
        assert doc["regions"] == [region] and doc["walls_enabled"] is False \
            and doc["explored"] == [[1, 1]], f"f1's terrain was disturbed: {doc}"
        assert doc["ladders"] == [{"cells": [[3, 5]], "target": [3, 5, 0]}]
    print("✅ test_the_other_pages_terrain_survives passed")


def test_no_floor_there_leaves_it_one_way():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp, floors=1)
        _edit(app, (3, 5))
        assert app._ladders == [{"cells": [(3, 5)], "target": [3, 5, 1]}]
        assert "one-way" in app._status_msg, app._status_msg
        assert sorted(f for f in os.listdir(tmp) if f.endswith("_terrain.json")) \
            == ["f0_terrain.json"], os.listdir(tmp)
    print("✅ test_no_floor_there_leaves_it_one_way passed")


def test_ladders_from_before_the_edit_are_not_repaired():
    """A return ladder the DM deleted on purpose stays deleted: only this session's
    placements and removals are paired."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_terrain(tmp, "f0", {"regions": [],
                                   "ladders": [{"cells": [[3, 5]], "target": [3, 5, 1]}]})
        app = _dungeon_app(tmp)
        assert len(app._ladders) == 1
        _edit(app)                      # open and close, no clicks
        assert _terrain(tmp, "f1") is None
    print("✅ test_ladders_from_before_the_edit_are_not_repaired passed")


def main():
    tests = [test_a_placed_ladder_gets_a_return_ladder,
             test_a_down_ladder_pairs_too,
             test_offset_pages_pair_by_global_cell,
             test_removing_a_ladder_removes_its_return,
             test_an_occupied_landing_is_left_alone,
             test_the_other_pages_terrain_survives,
             test_no_floor_there_leaves_it_one_way,
             test_ladders_from_before_the_edit_are_not_repaired]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:          # a missing sidecar fails as a TypeError, not an assert
            failed += 1
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n❌ test_ladder_pairing: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_ladder_pairing: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
