#!/usr/bin/env python3
"""The DM's right-click "Send to floor…" (plans/STRAHD_LAIR_PLAN.md L6b).

Any creature can be sent to another page of the dungeon, in or out of combat, without the
DM's view following it. It lands at the same global (X, Y) on the target page, off the
creatures already there; a wall there is resolved when the page loads (App._open_cell_near).
Out of combat it leaves this page's file; in combat it is tombstoned here, like a cleared mob.
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

CELL, COLS, ROWS = 30, 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _write(tmp, name, doc):
    with open(os.path.join(tmp, name), "w") as f:
        json.dump(doc, f)


def _read(tmp, name):
    with open(os.path.join(tmp, name)) as f:
        return json.load(f)


def _rec(name, col, row, faction):
    return {"name": name, "sprite_path": "", "size": 1, "col": col, "row": row,
            "faction": faction}


def _dungeon(tmp, f1_terrain=None, f1_agents=()):
    """An app on page f0 (Strahd at (3,3), Aria at (6,3)) with page f1 one floor up."""
    p0, p1 = _png(tmp, "f0.png"), _png(tmp, "f1.png")
    _write(tmp, "f0_terrain.json", {"regions": [], "walls_enabled": False, "manual_grid": GRID})
    _write(tmp, "f1_terrain.json", f1_terrain or
           {"regions": [], "walls_enabled": False, "manual_grid": GRID})
    _write(tmp, "f0_agents.json", {"agents": [_rec("Strahd", 3, 3, 1), _rec("Aria", 6, 3, 2)]})
    _write(tmp, "f1_agents.json", {"agents": list(f1_agents)})
    app = App(p0, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    pages = [MapPage("f0", p0, "f0_agents.json", [0, 0, 0], COLS, ROWS),
             MapPage("f1", p1, "f1_agents.json", [0, 0, 1], COLS, ROWS)]
    app.dungeon = Dungeon(pages=pages, entry_page_id="f0")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    assert [pt.name for pt in app.bm.placed_agents] == ["Strahd", "Aria"]
    return app


def _names(app):
    return [pt.name for pt in app.bm.placed_agents if not pt.removed_from_play]


def test_send_out_of_combat():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, f1_agents=[_rec("Guard", 3, 3, 1)])
        assert [p.id for p in app._send_pages()] == ["f1"]
        assert app._send_to_page(0, app.dungeon.page_by_id("f1"))
        assert _names(app) == ["Aria"], "he leaves this page"
        assert app.dungeon_page.id == "f0", "the DM's view stays put"
        assert [a["name"] for a in _read(tmp, "f0_agents.json")["agents"]] == ["Aria"]
        up = {a["name"]: (a["col"], a["row"]) for a in _read(tmp, "f1_agents.json")["agents"]}
        assert up["Guard"] == (3, 3)
        assert up["Strahd"] != (3, 3) and max(abs(up["Strahd"][0] - 3),
                                               abs(up["Strahd"][1] - 3)) == 1, up
        assert app._switch_to_page(app.dungeon.page_by_id("f1"))
        assert sorted(_names(app)) == ["Guard", "Strahd"]
    print("✅ test_send_out_of_combat passed")


def test_send_into_a_wall_lands_beside_it():
    wall = {"regions": [], "walls_enabled": False, "manual_grid": GRID,
            "doors": [{"cells": [[3, 3]], "open": False}]}
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, f1_terrain=wall)
        assert app._send_to_page(0, app.dungeon.page_by_id("f1"))
        assert app._switch_to_page(app.dungeon.page_by_id("f1"))
        assert _names(app) == ["Strahd"], "not skipped by the load"
        o = app.bm.placed_agents[0].origin
        assert (o.col, o.row) != (3, 3) and max(abs(o.col - 3), abs(o.row - 3)) == 1
    print("✅ test_send_into_a_wall_lands_beside_it passed")


def test_send_in_combat():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app._start_combat()
        assert app.combat_active
        strahd = 0
        assert app._send_to_page(strahd, app.dungeon.page_by_id("f1"))
        assert app.combat_active, "the fight goes on"
        assert app.bm.is_agent_removed_from_play(strahd)
        assert app._current_agent_idx() != strahd
        assert [a["name"] for a in _read(tmp, "f1_agents.json")["agents"]] == ["Strahd"]
        app._end_combat(award_xp=False)
        app._save_agents()
        assert [a["name"] for a in _read(tmp, "f0_agents.json")["agents"]] == ["Aria"]
    print("✅ test_send_in_combat passed")


def test_no_dungeon_no_send():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "solo.png"), seed=1)
        assert app._send_pages() == []
    print("✅ test_no_dungeon_no_send passed")


if __name__ == "__main__":
    test_send_out_of_combat()
    test_send_into_a_wall_lands_beside_it()
    test_send_in_combat()
    test_no_dungeon_no_send()
    print("\nAll send-to-floor tests passed.")
