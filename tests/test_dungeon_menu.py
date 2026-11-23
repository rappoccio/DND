#!/usr/bin/env python3
"""The Dungeon… panel button and its menu (plans/DUNGEON_WIZARD_PLAN.md W3, D1–D3).

  · one Dungeon… button replaces Generate Dungeon and Dungeon Configuration;
  · with no dungeon open the menu offers New Dungeon… (the W4 wizard) / Open Campaign /
    Open Dungeon;
  · with a dungeon open it offers Floors…, Staircases…, Populate Floor… and the rest,
    and no longer lists Pages / Overview…, Add Page… or Align Floor at the top level;
  · Floors… holds Overview…, Add… and Align Floor;
  · Populate Floor… opens the generator in its populate shape and never carves.
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
from menus import dm
import app_dungeon_gen

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _dungeon(tmp):
    """An app on page M (floor 0) with U above it (floor 1)."""
    pages = []
    for pid, z in (("M", 0), ("U", 1)):
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            f.write('{"regions": [], "walls_enabled": false, "manual_grid": %s}'
                    % json.dumps(GRID))
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    app = App(pages[0].png, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _labels(app):
    return [o.label for o in app.prompts.live.options]


def test_one_button():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "loose.png"), seed=1)
        assert not hasattr(app, "btn_generate_dungeon")
        assert app.btn_dungeon.text == "Dungeon…"
        app._reposition_panel()
        # Dungeon… sits straight under the Lighting/Items row, where Generate was.
        assert app.btn_dungeon.rect.y == (app.btn_lighting.rect.bottom + app._BTN_GAP), \
            (app.btn_dungeon.rect, app.btn_lighting.rect)
    print("  ✅ one Dungeon… button, under Lighting…")


def test_menu_without_dungeon():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "loose.png"), seed=1)
        dm.show_dungeon_menu(app)
        assert app.prompts.live.title == "Dungeon"
        assert _labels(app) == ["New Dungeon…", "Open Campaign…", "Open Dungeon…"], \
            _labels(app)
        assert app.prompts.choose_label("New Dungeon…").ok
        assert app.dungeon_wizard.visible          # W4: New Dungeon… is the wizard
    print("  ✅ no dungeon: New Dungeon… (the wizard) / Open Campaign / Open Dungeon")


def test_open_dungeon_starts_in_encounters():
    with tempfile.TemporaryDirectory() as tmp:
        maps = os.path.join(tmp, "maps")
        os.makedirs(maps)
        os.makedirs(os.path.join(tmp, "encounters"))
        app = App(_png(maps, "loose.png"), seed=1)
        seen = []
        app.file_browser.open = lambda start, *a, **k: seen.append(start)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Open Dungeon…").ok
        assert seen == [os.path.join(tmp, "encounters")], seen
    print("  ✅ Open Dungeon… starts in encounters/")


def test_open_dungeon_lists_both_manifests():
    """A campaign dungeon's manifest is plain dungeon.json; a loose one is
    <name>.dungeon.json. The browser shows both, and not backups or sidecars."""
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "loose.png"), seed=1)
        d = os.path.join(tmp, "castle")
        os.makedirs(os.path.join(d, "maps"))
        for name in ("dungeon.json", "dungeon.json.pre-pc-sheets", "keep.dungeon.json",
                     "dungeon_TestGrid12x12_agents.json", "keep_agents.json"):
            open(os.path.join(d, name), "w").close()
        app._dungeon_manifest_path = os.path.join(d, "keep.dungeon.json")
        app._map_dir = os.path.join(tmp, "nowhere", "maps")    # no encounters/: start at d
        app._dungeon_open_browser()
        assert app.file_browser.cwd == d, app.file_browser.cwd
        files = sorted(n for n, is_dir in app.file_browser._raw if not is_dir)
        assert files == ["dungeon.json", "keep.dungeon.json"], files
        app.file_browser.active = False
    print("  ✅ Open Dungeon… lists dungeon.json and <name>.dungeon.json, nothing else")


def test_menu_with_dungeon():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        dm.show_dungeon_menu(app)
        labels = _labels(app)
        assert labels[:3] == ["Floors…", "Staircases…", "Populate Floor…"], labels
        for gone in ("Pages / Overview…", "Add Page…", "Align Floor", "Generate Dungeon…"):
            assert gone not in labels, (gone, labels)
        for kept in ("Hide Room Labels", "Save Dungeon", "Save Game", "Release",
                     "Releases…", "Reset Dungeon", "Undo Reset", "Open Campaign…",
                     "Open Dungeon…", "Close Dungeon"):
            assert kept in labels, (kept, labels)
        assert labels[-1] == "Close Dungeon"
    print("  ✅ dungeon open: Floors… / Staircases… / Populate Floor… lead the menu")


def test_floors_submenu():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Floors…").ok
        assert app.prompts.live.title == "Floors"
        assert _labels(app) == ["Overview…", "Add…", "Align Floor"], _labels(app)
        assert app.prompts.choose_label("Align Floor").ok
        assert app.floor_align.active
    print("  ✅ Floors… holds Overview… / Add… / Align Floor, and Align Floor starts")


def test_populate_floor_routes():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        seen, ran = [], []
        app._modal_generate_dungeon = lambda populate=False: (seen.append(populate), None)[1]
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Populate Floor…").ok
        assert seen == [True]                      # the populate shape, and Cancel does nothing

        params = {"carve": True, "cr": 3}
        app._modal_generate_dungeon = lambda populate=False: dict(params)
        real = app_dungeon_gen.generate_dungeon_with
        app_dungeon_gen.generate_dungeon_with = lambda a, p: ran.append(p)
        try:
            app.confirm_overwrites = False
            dm.show_dungeon_menu(app)
            assert app.prompts.choose_label("Populate Floor…").ok
        finally:
            app_dungeon_gen.generate_dungeon_with = real
        assert len(ran) == 1 and ran[0]["carve"] is False, ran
    print("  ✅ Populate Floor… asks in the populate shape and never carves")


def test_populate_needs_dungeon():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "loose.png"), seed=1)
        app._modal_generate_dungeon = lambda populate=False: (_ for _ in ()).throw(
            AssertionError("no dialog without a dungeon"))
        app_dungeon_gen.on_populate_floor(app)
        assert "needs an open dungeon" in app._status_msg, app._status_msg
    print("  ✅ Populate Floor without a dungeon says so")


def test_populate_dialog_shape():
    """The dialog itself, driven by a click on its Populate button: carve is off, and
    Populate Floor returns before the generator's multi-floor fields matter."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app._modal_pick_mobs = lambda *a, **k: {"allowed_mobs": None, "boss_mob": None}
        sw, sh = app.screen.get_size()
        W, H = min(500, sw - 80), min(720, sh - 80)
        box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
        gen = pygame.Rect(box.right - 220, box.bottom - 46, 95, 32)
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                             pos=gen.center))
        try:
            params = app._modal_generate_dungeon(populate=True)
        finally:
            pygame.event.clear()
        assert params is not None and params["carve"] is False, params
        assert params["floors"] == 1 and params["maps_x"] == 1 and params["maps_y"] == 1
    print("  ✅ the populate dialog returns carve off, one floor, one map")


if __name__ == "__main__":
    pygame.init()
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:                 # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"  ❌ {name}: {e}")
                failures += 1
    sys.exit(1 if failures else 0)
