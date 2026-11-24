#!/usr/bin/env python3
"""Doors on a page's border (plans/DUNGEON_WIZARD_PLAN.md, after W9).

An edge door may sit on a page's outer grid line. It leads to the cell just past that line
on the same floor, which the abutting page holds; the link is derived from where the door
is, so nothing extra is saved. Opened, it offers "Go through door", which carries the
creature to the neighbouring page.
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
import rpg_battle_map as rpg

from main import App
from dungeon import Dungeon, MapPage
from helpers import border_side, border_link_target

CELL, COLS, ROWS = 30, 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
C, E, S = rpg.Cell, rpg.EdgeSide.East, rpg.EdgeSide.South


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


def _rec(name, col, row, faction=2):
    return {"name": name, "sprite_path": "", "size": 1, "col": col, "row": row,
            "faction": faction}


def _terrain(doors):
    return {"regions": [], "walls_enabled": False, "manual_grid": GRID, "doors": doors}


def _dungeon(tmp):
    """West page "w" at global (0, 0) and east page "e" at (COLS, 0), same floor. Each has
    an open door on the line they share; Aria stands by the west page's."""
    pw, pe = _png(tmp, "w.png"), _png(tmp, "e.png")
    _write(tmp, "w_terrain.json", _terrain([{"edges": [[COLS - 1, 3, "E"]], "open": True}]))
    _write(tmp, "e_terrain.json", _terrain([{"edges": [[-1, 3, "E"]], "open": True}]))
    _write(tmp, "w_agents.json", {"agents": [_rec("Aria", COLS - 1, 3), _rec("Bram", 2, 2)]})
    _write(tmp, "e_agents.json", {"agents": []})
    app = App(pw, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    pages = [MapPage("w", pw, "w_agents.json", [0, 0, 0], COLS, ROWS),
             MapPage("e", pe, "e_agents.json", [COLS, 0, 0], COLS, ROWS)]
    app.dungeon = Dungeon(pages=pages, entry_page_id="w")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _names(app):
    return [pt.name for pt in app.bm.placed_agents if not pt.removed_from_play]


def _menu(app, idx):
    """The door menu's labels for the door Aria stands by, and its options."""
    from menus import dm
    seen = {}
    app._ask_actor = lambda *a, **kw: seen.setdefault("opts", a[3])
    app.combat_active = True
    app._current_agent_idx = lambda: idx
    door = app.bm.doors[0]
    x, y, w, h = __import__("terrain_dialogs").edge_door_rect(
        door, app._cell_to_screen, int(CELL * app.map_scale),
        grid=(app.bm.grid_cols, app.bm.grid_rows))
    dm.show_door_menu(app, C(COLS - 1, 3), (x + w // 2, y + h // 2))
    return seen.get("opts", [])


def test_border_side_and_target():
    assert border_side((-1, 3, "E"), COLS, ROWS) == "west"
    assert border_side((COLS - 1, 3, "E"), COLS, ROWS) == "east"
    assert border_side((4, -1, "S"), COLS, ROWS) == "north"
    assert border_side((4, ROWS - 1, "S"), COLS, ROWS) == "south"
    assert border_side((4, 3, "E"), COLS, ROWS) is None
    assert border_side((-1, -1, "E"), COLS, ROWS) is None, "off the page's rows"
    assert border_link_target([(COLS - 1, 3, "E")], COLS, ROWS, 20, 5, 2) == [20 + COLS, 8, 2]
    assert border_link_target([(-1, 3, "E")], COLS, ROWS, 20, 5, 2) == [19, 8, 2]
    assert border_link_target([(4, -1, "S")], COLS, ROWS, 20, 5, 2) == [24, 4, 2]
    assert border_link_target([(4, ROWS - 1, "S")], COLS, ROWS, 0, 0, 0) == [4, ROWS, 0]
    wide = [(-1, 2, "E"), (-1, 3, "E"), (-1, 4, "E")]
    assert border_link_target(wide, COLS, ROWS, 0, 0, 0) == [-1, 3, 0], "the middle edge"
    assert border_link_target([(4, 3, "E")], COLS, ROWS, 0, 0, 0) is None
    assert border_link_target([], COLS, ROWS, 0, 0, 0) is None
    print("✅ test_border_side_and_target passed")


def test_go_through_a_border_door_and_back():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        door = app.bm.doors[0]
        assert app._door_link_at(door) == [COLS, 3, 0]
        labels = [label for label, _fn in _menu(app, 0)]
        assert "Go through door (to floor 0)" in labels, labels
        app.combat_active = False
        app._use_door_link(door.id, 0)
        assert app.dungeon_page.id == "e", "the view follows the creature"
        assert _names(app) == ["Aria"]
        o = app.bm.placed_agents[0].origin
        assert (o.col, o.row) == (0, 3), "just inside the east page, across from the door"
        assert [a["name"] for a in _read(tmp, "w_agents.json")["agents"]] == ["Bram"]
        # And back through the east page's own door on the shared line.
        back = app.bm.doors[0]
        assert app._door_link_at(back) == [COLS - 1, 3, 0]
        app._use_door_link(back.id, 0)
        assert app.dungeon_page.id == "w"
        assert sorted(_names(app)) == ["Aria", "Bram"]
    print("✅ test_go_through_a_border_door_and_back passed")


def test_a_shut_border_door_offers_no_passage():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app.bm.close_door(app.bm.doors[0].id)
        labels = [label for label, _fn in _menu(app, 0)]
        assert "Open door" in labels and not any(l.startswith("Go through") for l in labels)
    print("✅ test_a_shut_border_door_offers_no_passage passed")


def test_a_border_door_with_no_page_beyond_goes_nowhere():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app.dungeon.pages = [p for p in app.dungeon.pages if p.id != "e"]
        flashes = []
        app._flash_status = lambda msg, *a, **k: flashes.append(msg)
        app._use_door_link(app.bm.doors[0].id, 0)
        assert app.dungeon_page.id == "w" and "Aria" in _names(app)
        assert flashes and "nowhere" in flashes[-1]
    print("✅ test_a_border_door_with_no_page_beyond_goes_nowhere passed")


if __name__ == "__main__":
    test_border_side_and_target()
    test_go_through_a_border_door_and_back()
    test_a_shut_border_door_offers_no_passage()
    test_a_border_door_with_no_page_beyond_goes_nowhere()
    print("\nAll border-door tests passed.")
