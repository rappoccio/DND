#!/usr/bin/env python3
"""Align Floor (DUNGEON_LEVELS_PLAN.md Phase 1): the floor below, ghosted onto this page.

  · a ghost page's cell (c, r) is drawn over the current page's cell for the same global
    (X, Y), for pages with different cell sizes and offset origins — by the placement
    math and by the pixels actually blitted;
  · an arrow key moves the current page's origin by exactly one cell;
  · Enter persists the nudged origin to the manifest; Esc restores the starting origin;
  · Tab switches to the floor above;
  · a ghost page with no usable grid is skipped and named, not drawn wrong.
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
from floor_overlay import Ghost, draw_ghosts, ghost_placement, load_ghost_lines

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261019

# The ghost page: a drawn grid at a different pixel scale from the current page, with
# its grid anchored off the image corner, saved with a manual_grid as Set Grid… would.
GHOST_CELL = 45
GHOST_ANCHOR = (7, 5)
GHOST_COLS, GHOST_ROWS = 6, 5
MARK = (2, 3)                  # the ghost cell painted red
RED = (255, 0, 0)


def _ghost_png(tmp, name="below.png"):
    w = GHOST_ANCHOR[0] + GHOST_COLS * GHOST_CELL + 3
    h = GHOST_ANCHOR[1] + GHOST_ROWS * GHOST_CELL + 3
    surf = pygame.Surface((w, h))
    surf.fill((235, 230, 215))
    for c in range(GHOST_COLS + 1):
        x = GHOST_ANCHOR[0] + c * GHOST_CELL
        pygame.draw.line(surf, (0, 0, 0), (x, 0), (x, h), 1)
    for r in range(GHOST_ROWS + 1):
        y = GHOST_ANCHOR[1] + r * GHOST_CELL
        pygame.draw.line(surf, (0, 0, 0), (0, y), (w, y), 1)
    mc, mr = MARK
    surf.fill(RED, pygame.Rect(GHOST_ANCHOR[0] + mc * GHOST_CELL + 1,
                               GHOST_ANCHOR[1] + mr * GHOST_CELL + 1,
                               GHOST_CELL - 1, GHOST_CELL - 1))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _write_manual_grid(tmp, page_id):
    with open(os.path.join(tmp, f"{page_id}_terrain.json"), "w") as f:
        json.dump({"manual_grid": {"cell_px": GHOST_CELL, "anchor": list(GHOST_ANCHOR),
                                   "square_ft": 5}}, f)


def _dungeon_app(tmp, ghost_origin=(3, 2, -1), above=False, broken=False):
    """An app on page f0 at (0, 0, 0); the ghost page 'b1' sits at ``ghost_origin``."""
    app = App(MAP_PATH, seed=SEED)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    cols, rows = app.bm.grid_cols, app.bm.grid_rows
    png = _ghost_png(tmp)
    _write_manual_grid(tmp, "b1")
    pages = [MapPage("f0", MAP_PATH, "f0_agents.json", [0, 0, 0], cols, rows),
             MapPage("b1", png, "b1_agents.json", list(ghost_origin), GHOST_COLS, GHOST_ROWS)]
    if above:
        pages.append(MapPage("u1", MAP_PATH, "u1_agents.json", [0, 0, 1], cols, rows))
    if broken:
        pages.append(MapPage("gone", os.path.join(tmp, "missing.png"), "gone_agents.json",
                             [20, 0, -1], 4, 4))
    app.dungeon = Dungeon(pages=pages, entry_page_id="f0")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _center(v, h, c, r):
    return ((v[c] + v[c + 1]) / 2.0, (h[r] + h[r + 1]) / 2.0)


def _key(app, key):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))
    assert app._handle_events() is not False


def test_ghost_cells_map_onto_the_same_global_cells():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        cur_v, cur_h = app.bm.v_line_positions, app.bm.h_line_positions
        gv, gh = load_ghost_lines(_ghost_png(tmp), os.path.join(tmp, "b1_terrain.json"))
        assert len(gv) == GHOST_COLS + 1 and gv[0] == GHOST_ANCHOR[0], gv
        cur_cell = (cur_v[-1] - cur_v[0]) / (len(cur_v) - 1)
        assert abs(cur_cell - GHOST_CELL) > 5, "the two pages must differ in pixel scale"
        cur_origin, g_origin = (1, -1, 0), (3, 2, -1)
        sx, sy, ox, oy = ghost_placement((cur_v, cur_h), cur_origin, (gv, gh), g_origin)
        for gc in range(GHOST_COLS):
            for gr in range(GHOST_ROWS):
                # Ghost local (gc, gr) is global (3+gc, 2+gr); on the current page that
                # is local (3+gc-1, 2+gr+1).
                c, r = gc + 2, gr + 3
                if c + 1 >= len(cur_v) or r + 1 >= len(cur_h):
                    continue
                gx, gy = _center(gv, gh, gc, gr)
                want = _center(cur_v, cur_h, c, r)
                got = (ox + sx * gx, oy + sy * gy)
                assert abs(got[0] - want[0]) < 1.0 and abs(got[1] - want[1]) < 1.0, \
                    f"ghost ({gc},{gr}) lands at {got}, current ({c},{r}) is at {want}"
    print("✅ test_ghost_cells_map_onto_the_same_global_cells passed")


def test_the_blitted_ghost_lands_on_the_right_cell():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        lines = load_ghost_lines(_ghost_png(tmp), os.path.join(tmp, "b1_terrain.json"))
        g = Ghost("b1", (3, 2, -1), lines, pygame.image.load(_ghost_png(tmp)).convert())
        cur = (app.bm.v_line_positions, app.bm.h_line_positions)
        canvas = pygame.Surface(app.screen.get_size())
        canvas.fill((0, 0, 0))
        scale, pan = 0.8, (13, -4)
        draw_ghosts(canvas, [g], cur, (0, 0, 0), scale, pan, canvas.get_rect(), alpha=255)
        # The red ghost cell (2, 3) is global (5, 5): current-page cell (5, 5).
        cx, cy = _center(*cur, 5, 5)
        px = (int(cx * scale + pan[0]), int(cy * scale + pan[1]))
        assert tuple(canvas.get_at(px))[:3] == RED, f"pixel {px} is {canvas.get_at(px)}"
        # Its neighbour, current cell (4, 5), is not red.
        nx, ny = _center(*cur, 4, 5)
        npx = (int(nx * scale + pan[0]), int(ny * scale + pan[1]))
        assert tuple(canvas.get_at(npx))[:3] != RED
    print("✅ test_the_blitted_ghost_lands_on_the_right_cell passed")


def test_arrows_nudge_one_cell_and_enter_saves():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        assert app.floor_align.start(app)
        assert [g.page_id for g in app.floor_align.ghosts] == ["b1"]
        pan0 = app.pan_x
        _key(app, pygame.K_RIGHT)
        assert app.dungeon_page.origin == [1, 0, 0]
        assert app.pan_x > pan0, "the page should move on screen with its origin"
        _key(app, pygame.K_DOWN)
        _key(app, pygame.K_DOWN)
        _key(app, pygame.K_LEFT)
        _key(app, pygame.K_LEFT)
        assert app.dungeon_page.origin == [-1, 2, 0]
        app.screen.fill((0, 0, 0))
        app.floor_align.draw(app)           # draws without error mid-mode
        _key(app, pygame.K_RETURN)
        assert not app.floor_align.active
        with open(app._dungeon_manifest_path) as f:
            saved = {p["id"]: p["origin"] for p in json.load(f)["pages"]}
        assert saved["f0"] == [-1, 2, 0], saved
        assert (app.bm.origin_col, app.bm.origin_row) == (-1, 2)
    print("✅ test_arrows_nudge_one_cell_and_enter_saves passed")


def test_escape_restores_the_starting_origin():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        app.dungeon_page.origin = [4, 4, 0]
        pan0 = (app.pan_x, app.pan_y)
        assert app.floor_align.start(app)
        for k in (pygame.K_RIGHT, pygame.K_RIGHT, pygame.K_UP):
            _key(app, k)
        assert app.dungeon_page.origin == [6, 3, 0]
        _key(app, pygame.K_ESCAPE)
        assert not app.floor_align.active
        assert app.dungeon_page.origin == [4, 4, 0]
        assert (app.pan_x, app.pan_y) == pan0
        assert not os.path.exists(app._dungeon_manifest_path), "Esc must not save"
    print("✅ test_escape_restores_the_starting_origin passed")


def test_tab_shows_the_floor_above():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp, above=True)
        assert app.floor_align.start(app)
        assert app.floor_align.direction == -1
        _key(app, pygame.K_TAB)
        assert app.floor_align.direction == 1
        assert [g.page_id for g in app.floor_align.ghosts] == ["u1"]
        _key(app, pygame.K_ESCAPE)
    print("✅ test_tab_shows_the_floor_above passed")


def test_no_floor_below_falls_back_to_above():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp, ghost_origin=(0, 0, 2), above=True)   # floors 0, 1, 2
        assert app.floor_align.start(app)
        assert app.floor_align.direction == 1
        assert [g.page_id for g in app.floor_align.ghosts] == ["u1"]
    print("✅ test_no_floor_below_falls_back_to_above passed")


def test_a_ghost_without_a_grid_is_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp, broken=True)
        assert app.floor_align.start(app)
        assert [g.page_id for g in app.floor_align.ghosts] == ["b1"]
        assert app.floor_align.skipped == ["gone"]
    print("✅ test_a_ghost_without_a_grid_is_skipped passed")


def test_switching_pages_cancels_the_nudge():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon_app(tmp)
        assert app.floor_align.start(app)
        _key(app, pygame.K_RIGHT)
        f0 = app.dungeon_page
        assert app._switch_to_page(app.dungeon.page_by_id("b1"))
        assert not app.floor_align.active
        assert f0.origin == [0, 0, 0]
    print("✅ test_switching_pages_cancels_the_nudge passed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__} failed: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
