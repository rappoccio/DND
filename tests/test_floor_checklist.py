#!/usr/bin/env python3
"""The Floors… checklist (plans/DUNGEON_WIZARD_PLAN.md W7, D21).

  · one row per floor, top floor first: grid · aligned · walls (none / detected /
    edited) · doors N · staircases N · creatures N, read from the saved files, and from
    the live scene for the floor showing;
  · a page records whether it was aligned (``aligned``, optional, both manifest shapes);
    Align Floor's Enter sets it;
  · Dungeon → Floors… opens the checklist; each item, clicked, goes to that floor with
    its tool open; Overview… / Add… / Close / Esc.
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

import floor_checklist as fc
import gui_driver
from dungeon import Dungeon, MapPage
from main import App
from menus import dm

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _dungeon(tmp, creatures=0):
    """An app on page M (floor 0, the entry) with U above it (floor 1). U has walls off,
    two doors and ``creatures`` placeholder records on file (only counted, never
    loaded), and one end of a staircase."""
    docs = {
        "M": {"regions": [], "walls_enabled": True, "manual_grid": GRID},
        "U": {"regions": [], "walls_enabled": False, "manual_grid": GRID,
              "doors": [{"cells": [[1, 1]], "cell": [1, 1]},
                        {"cells": [[3, 3]], "cell": [3, 3]}]},
    }
    pages = []
    for pid, z in (("M", 0), ("U", 1)):
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            json.dump(docs[pid], f)
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    with open(os.path.join(tmp, "U_agents.json"), "w") as f:
        json.dump({"agents": [{}] * creatures, "map_items": []}, f)
    pages[1].aligned = True
    app = App(pages[0].png, seed=1)
    app.confirm_overwrites = False
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon.new_staircase("U", (2, 2), name="Up")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def test_walls_state():
    assert fc.walls_state(False, None, []) == "none"
    assert fc.walls_state(True, None, []) == "detected"
    assert fc.walls_state(True, {"add": [], "remove": []}, []) == "detected"
    assert fc.walls_state(True, {"add": [[1, 1, "E"]], "remove": []}, []) == "edited"
    assert fc.walls_state(False, None, [{"type": "Wall"}]) == "edited"
    assert fc.walls_state(True, None, [{"type": "Water"}]) == "detected"
    print("  ✅ walls: none / detected / edited")


def test_aligned_round_trips():
    for version in (1, 2):
        pages = [MapPage("A", "A.png", "A_agents.json", [0, 0, 0], 4, 4),
                 MapPage("B", "B.png", "B_agents.json", [0, 0, 1], 4, 4, aligned=True),
                 MapPage("C", "C.png", "C_agents.json", [0, 0, 2], 4, 4, aligned=False)]
        d = Dungeon(pages=pages, entry_page_id="A", version=version)
        doc = d.to_dict()
        key = "maps" if version == 2 else "pages"
        assert "aligned" not in doc[key][0]                 # unrecorded: not written
        back = Dungeon.from_dict(json.loads(json.dumps(doc)))
        assert [p.aligned for p in back.pages] == [None, True, False], version
    print("  ✅ aligned: optional, both manifest shapes")


def test_rows():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp, creatures=3)
        rows = fc.floor_rows(app)
        assert [r.page_id for r in rows] == ["U", "M"]      # top floor first
        u, m = rows
        assert (u.entry, u.grid, u.aligned, u.walls, u.doors, u.stairs, u.creatures) == \
            (False, True, True, "none", 2, 1, 3), u
        assert m.entry and m.grid and m.walls == "detected" and m.stairs == 0
        assert m.creatures == len(app.bm.placed_agents)
        assert [u.label(c) for c in fc.COLUMNS] == \
            ["Grid ✓", "Aligned ✓", "Walls: none", "Doors 2", "Stairs 1", "Creatures 3"]
        assert m.label("aligned") == "Entry" and m.done("aligned")
        assert not u.done("walls") and u.done("doors")
        app.dungeon.page_by_id("U").aligned = None
        assert fc.floor_rows(app)[0].label("aligned") == "Aligned ?"
    print("  ✅ rows: top floor first, files for other floors, the live scene for this one")


def _chip(ck, page_id, col):
    return next(r for r, kind, val in ck._hit if kind == "chip" and val == (page_id, col))


def _btn(ck, key):
    return next(r for r, kind, val in ck._hit if kind == "btn" and val == key)


def _reopen(app):
    if app.terrain_editor.active:
        app._close_terrain_editor()
    dm.show_dungeon_menu(app)
    assert app.prompts.choose_label("Floors…").ok
    assert app.floor_checklist.visible
    return app.floor_checklist


def test_clicks_jump_with_the_tool_open():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        ck = _reopen(app)
        assert {val[0] for _r, kind, val in ck._hit if kind == "chip"} == {"U", "M"}

        gui_driver.post_click(app, _chip(ck, "U", "doors").center)
        assert not ck.visible and app.dungeon_page.id == "U"
        assert app.terrain_editor.active and app.terrain_editor.selected_type == "Door"

        ck = _reopen(app)
        gui_driver.post_click(app, _chip(ck, "U", "stairs").center)
        assert app.terrain_editor.active and app.terrain_editor.selected_type == "Staircase"

        ck = _reopen(app)
        gui_driver.post_click(app, _chip(ck, "U", "walls").center)     # off: turned on first
        assert app._walls_enabled and app._wall_detect_dialog.visible
        app._wall_detect_dialog.visible = False

        ck = _reopen(app)
        gui_driver.post_click(app, _chip(ck, "M", "grid").center)
        assert app.dungeon_page.id == "M" and app._grid_sample_mode
        app._toggle_grid_sample_mode()

        ck = _reopen(app)
        gui_driver.post_click(app, _chip(ck, "M", "aligned").center)
        assert app.floor_align.active
        app.floor_align.finish(app, keep=True)              # Enter records the alignment
        assert app.dungeon.page_by_id("M").aligned is True
        assert Dungeon.load(app._dungeon_manifest_path).page_by_id("M").aligned is True

        seen = []
        app._modal_generate_dungeon = lambda populate=False: (seen.append(populate), None)[1]
        ck = _reopen(app)
        gui_driver.post_click(app, _chip(ck, "U", "creatures").center)
        assert app.dungeon_page.id == "U" and seen == [True]        # Populate Floor…
    print("  ✅ each item goes to its floor with its tool open")


def test_buttons_and_escape():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        calls = []
        app._dungeon_pages_overview = lambda: calls.append("overview")
        app.dungeon_wizard.start_add = lambda _app: calls.append("add")
        for key in ("overview", "add"):
            ck = _reopen(app)
            gui_driver.post_click(app, _btn(ck, key).center)
            assert not ck.visible
        assert calls == ["overview", "add"]
        ck = _reopen(app)
        gui_driver.post_click(app, _btn(ck, "close").center)
        assert not ck.visible
        ck = _reopen(app)
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0,
                                             unicode="\x1b", scancode=0))
        app._handle_events()
        assert not ck.visible
    print("  ✅ Overview… / Add… / Close / Esc")


if __name__ == "__main__":
    pygame.init()
    tests = [test_walls_state, test_aligned_round_trips, test_rows,
             test_clicks_jump_with_the_tool_open, test_buttons_and_escape]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:      # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
