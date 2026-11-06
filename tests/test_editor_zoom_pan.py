#!/usr/bin/env python3
"""Zoom and pan inside the map editors (Terrain → Edit…, Lighting → Edit…).

Both editors opened at fit scale and offered no way to get closer to a small map
feature. The terrain editor now carries a view of its own (it draws its own copy of
the map, in fit-scale px, and stores everything it authors in those px); the lighting
editor draws over the live map and lets the app's zoom/pan through.

What matters is that a click still lands on the cell under the pointer however the
view moved, and that what gets stored is unchanged by the view:

  · zooming keeps the map point under the cursor fixed on screen;
  · a drag at 2x, panned, stores the same region a fit-scale drag over the same
    map px would;
  · a door click on a zoomed, panned view lands on the cell under the pointer;
  · a press over the config panel does nothing, even with the map zoomed under it;
  · the wheel (a pinch) and +/- zoom, arrows / middle-drag / a plain left drag pan,
    0 resets; +/- keep their Door-mode meaning (lock DC); authoring drags take Ctrl;
  · the editor opens on the map's zoom and pan, and hands its own back on close;
  · drawing at high zoom works and paints the viewport only;
  · the lighting editor passes the wheel (zoom), zoom keys and arrows through to the
    app's map, and its overlay follows the zoom.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from main import App
from constants import PANEL_W

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261019


def _terrain_app():
    app = App(MAP_PATH, seed=SEED)
    app._open_terrain_editor()
    ed = app.terrain_editor
    ed.draw(app.screen)          # establishes the viewport
    return app, ed


def _ev(kind, **kw):
    return pygame.event.Event(kind, **kw)


def _key(k, mod=0):
    return _ev(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0)


def _wheel(x=0, y=0):
    return _ev(pygame.MOUSEWHEEL, x=x, y=y, flipped=False, precise_x=float(x),
               precise_y=float(y))


def _drag(ed, a, b, button=1, mods=pygame.KMOD_CTRL):
    """Press at ``a``, move to ``b``, release. Ctrl (the default) makes it an authoring
    drag; ``mods=0`` is a plain drag, which pans."""
    pygame.key.set_mods(mods)
    try:
        ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=a, button=button))
        ed.handle(_ev(pygame.MOUSEMOTION, pos=b, rel=(0, 0), buttons=(1, 0, 0)))
        ed.handle(_ev(pygame.MOUSEBUTTONUP, pos=b, button=button))
    finally:
        pygame.key.set_mods(0)


def _cell_center(bm, col, row):
    v, h = bm.v_line_positions, bm.h_line_positions
    return ((v[col] + v[col + 1]) / 2, (h[row] + h[row + 1]) / 2)


def test_zoom_keeps_the_point_under_the_cursor():
    app, ed = _terrain_app()
    cursor = (137, 91)
    before = ed._to_map(cursor)
    ed.zoom_by(2.0, center=cursor)
    ed.zoom_by(1.3, center=cursor)
    after = ed._to_map(cursor)
    assert abs(after[0] - before[0]) <= 1 and abs(after[1] - before[1]) <= 1, \
        f"zoom moved the map point under the cursor: {before} -> {after}"
    assert abs(ed.view_zoom - 2.6) < 1e-6, ed.view_zoom
    print("✅ test_zoom_keeps_the_point_under_the_cursor passed")


def test_a_zoomed_drag_stores_the_same_region_as_a_fit_drag():
    app, ed = _terrain_app()
    bm = ed.bm
    ed.selected_type = "Water"
    a_map = _cell_center(bm, 2, 3)
    b_map = _cell_center(bm, 4, 5)
    _drag(ed, a_map, b_map)
    assert len(ed.terrain_regions) == 1
    fit_region = dict(ed.terrain_regions[0])

    ed.terrain_regions.clear()
    ed.zoom_by(2.0, center=(0, 0))
    ed.view_pan[0] -= 40
    ed.view_pan[1] -= 25
    _drag(ed, ed._to_screen(a_map), ed._to_screen(b_map))
    assert len(ed.terrain_regions) == 1
    zoomed_region = ed.terrain_regions[0]
    for k in ("x", "y", "width", "height", "type"):
        assert zoomed_region[k] == fit_region[k], \
            f"{k}: zoomed drag stored {zoomed_region[k]!r}, fit drag {fit_region[k]!r}"
    print("✅ test_a_zoomed_drag_stores_the_same_region_as_a_fit_drag passed")


def test_a_zoomed_door_click_lands_on_the_cell_under_the_pointer():
    app, ed = _terrain_app()
    bm = ed.bm
    ed.selected_type = "Door"
    ed.zoom_by(3.0, center=(100, 100))
    ed.view_pan[0] -= 70
    target = rpg.Cell(1, 2)      # stays inside the viewport at 3x
    screen_pos = ed._to_screen(_cell_center(bm, target.col, target.row))
    _drag(ed, screen_pos, screen_pos)
    assert bm.door_at(target) >= 0, "no door at the cell under the pointer"
    assert len(bm.doors) == 1, f"expected exactly one door, got {len(bm.doors)}"
    print("✅ test_a_zoomed_door_click_lands_on_the_cell_under_the_pointer passed")


def test_a_press_over_the_panel_does_nothing():
    app, ed = _terrain_app()
    ed.selected_type = "Wall"
    ed.zoom_by(ed.ZOOM_MAX)          # map now extends far under the panel
    px = app.screen.get_width() - PANEL_W + 20
    _drag(ed, (px, 40), (px + 60, 120))
    assert ed.terrain_regions == [], f"a panel drag painted terrain: {ed.terrain_regions}"
    print("✅ test_a_press_over_the_panel_does_nothing passed")


def test_wheel_keys_pan_and_zoom():
    """The main map's gestures: the wheel (a trackpad pinch) zooms at the cursor, with
    or without a modifier; arrows and middle-drag pan; +/- zoom, 0 resets."""
    app, ed = _terrain_app()
    ed.handle(_wheel(y=1))
    assert ed.view_zoom > 1.0, "the wheel did not zoom"
    z = ed.view_zoom
    ed.handle(_wheel(y=-1))
    assert ed.view_zoom < z, "the wheel did not zoom out"
    ed.handle(_key(pygame.K_0))
    ed.zoom_by(2.0, center=(0, 0))
    ed.handle(_key(pygame.K_LEFT))
    ed.handle(_key(pygame.K_UP))
    assert ed.view_pan == [30, 30], ed.view_pan
    z = ed.view_zoom
    ed.handle(_key(pygame.K_EQUALS))
    assert ed.view_zoom > z, "+ did not zoom outside Door mode"

    ed.selected_type = "Door"
    z, dc = ed.view_zoom, ed.door_lock_dc
    ed.handle(_key(pygame.K_EQUALS))
    assert ed.view_zoom == z and ed.door_lock_dc == dc + 1, \
        "+ in Door mode should raise the lock DC, not zoom"
    ed.handle(_key(pygame.K_KP_PLUS))
    assert ed.view_zoom > z, "keypad + should zoom in any mode"

    ed.handle(_key(pygame.K_0))
    assert ed.view_zoom == 1.0 and ed.view_pan == [0, 0], "0 did not reset the view"

    # Middle-drag pans (the clamp lets the fit map move up / left of the origin).
    ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=(80, 80), button=2))
    ed.handle(_ev(pygame.MOUSEMOTION, pos=(50, 60), rel=(-30, -20), buttons=(0, 1, 0)))
    ed.handle(_ev(pygame.MOUSEBUTTONUP, pos=(50, 60), button=2))
    assert ed.view_pan == [-30, -20], ed.view_pan
    print("✅ test_wheel_keys_pan_and_zoom passed")


def test_a_plain_drag_pans_and_authors_nothing():
    app, ed = _terrain_app()
    bm = ed.bm
    ed.selected_type = "Water"
    a = _cell_center(bm, 4, 4)
    b = (a[0] - 40, a[1] - 25)
    _drag(ed, a, b, mods=0)
    assert ed.terrain_regions == [], f"a plain drag painted terrain: {ed.terrain_regions}"
    assert ed.view_pan == [-40, -25], f"a plain drag did not pan: {ed.view_pan}"
    # A plain click (no movement past the slop) is still a click: Ladder places one.
    ed.selected_type = "Ladder"
    at = ed._to_screen(_cell_center(bm, 2, 2))
    _drag(ed, at, (at[0] + 2, at[1] + 1), mods=0)
    assert [tuple(l["cells"][0]) for l in ed.ladders] == [(2, 2)], ed.ladders
    print("✅ test_a_plain_drag_pans_and_authors_nothing passed")


def test_the_editor_opens_and_closes_on_the_map_view():
    app = App(MAP_PATH, seed=SEED)
    app._zoom_by(2.0, center=(0, 0))
    app.pan_x -= 23
    app.pan_y -= 17
    z, pan = app.view_zoom, (app.pan_x, app.pan_y)
    sx, sy = app._cell_to_screen(3, 3)
    app._open_terrain_editor()
    ed = app.terrain_editor
    assert abs(ed.view_zoom - z) < 1e-9 and tuple(ed.view_pan) == pan, \
        f"editor opened at {ed.view_zoom}, {ed.view_pan}; the map was at {z}, {pan}"
    # Same cell under the same screen point in both views.
    v, h, _ = ed._grid()
    ex, ey = ed._to_screen((v[3], h[3]))
    assert abs(ex - sx) <= 1 and abs(ey - sy) <= 1, ((sx, sy), (ex, ey))
    ed.draw(app.screen)
    ed.zoom_by(1.5, center=(100, 100))
    ed._pan_by(-10, -5)
    z2, pan2 = ed.view_zoom, tuple(ed.view_pan)
    app._close_terrain_editor()
    assert abs(app.view_zoom - z2) < 1e-6 and (app.pan_x, app.pan_y) == pan2, \
        f"map came back at {app.view_zoom}, {(app.pan_x, app.pan_y)}; editor left {z2}, {pan2}"
    print("✅ test_the_editor_opens_and_closes_on_the_map_view passed")


def test_drawing_at_high_zoom_paints_the_viewport_only():
    app, ed = _terrain_app()
    screen = app.screen
    panel_x = screen.get_width() - PANEL_W
    marker = (1, 2, 3)
    screen.fill(marker)
    ed.zoom_by(ed.ZOOM_MAX, center=(10, 10))
    ed.draw(screen)
    assert screen.get_at((panel_x + 5, screen.get_height() // 2))[:3] == marker, \
        "the zoomed map was drawn over the config panel"
    # Panned entirely off the map: the viewport is cleared, nothing raises.
    ed.view_pan = [10 ** 6, 10 ** 6]
    ed.draw(screen)
    print("✅ test_drawing_at_high_zoom_paints_the_viewport_only passed")


def test_the_lighting_editor_lets_zoom_and_pan_through():
    app = App(MAP_PATH, seed=SEED)
    app._lighting_path = os.path.join("/nonexistent", "probe_lighting.json")
    app._open_lighting_editor()
    assert app.lighting_editor.active
    z = app.view_zoom
    pygame.event.clear()
    pygame.event.post(_key(pygame.K_EQUALS))
    app._handle_events()
    assert app.view_zoom > z, "+ did not zoom the map under the lighting editor"
    z = app.view_zoom
    pygame.event.post(_wheel(y=1))
    app._handle_events()
    assert app.view_zoom > z, "wheel did not zoom the map under the lighting editor"
    pan_before = app.pan_y
    pygame.event.post(_key(pygame.K_DOWN))
    app._handle_events()
    assert app.pan_y == pan_before - 30, \
        f"arrow did not pan under the lighting editor: {pan_before} -> {app.pan_y}"
    assert app.lighting_editor.active, "a view event closed the lighting editor"

    # Placing a light at 2x lands on the cell under the pointer.
    ed = app.lighting_editor
    ed.placing_light = True
    target = (3, 4)
    sx, sy = app._cell_to_screen(*target)
    ex, ey = app._cell_to_screen(target[0] + 1, target[1] + 1)
    ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=((sx + ex) // 2, (sy + ey) // 2), button=1))
    assert ed.light_sources and (ed.light_sources[-1]["col"], ed.light_sources[-1]["row"]) == target, \
        f"zoomed light placement missed: {ed.light_sources}"
    app._draw_map()   # overlay + markers follow the zoom without raising
    print("✅ test_the_lighting_editor_lets_zoom_and_pan_through passed")


def _wall_region_on(app, col, row):
    """A one-cell Wall region over (col, row), in fit-scale px as the editor stores it."""
    s = app.base_map_scale
    v, h = app.bm.v_line_positions, app.bm.h_line_positions
    return {"type": "Wall", "x": v[col] * s, "y": h[row] * s,
            "width": (v[col + 1] - v[col]) * s, "height": (h[row + 1] - h[row]) * s,
            "multiplier": 0.0}


def test_painted_terrain_follows_the_main_map_zoom():
    """Outside the editor, a painted wall stayed at its fit-scale spot when the map zoomed."""
    app = App(MAP_PATH, seed=SEED)
    app.show_terrain = True
    col, row = 3, 3
    app._terrain_regions = [_wall_region_on(app, col, row)]
    app._zoom_by(2.0, center=(0, 0))
    app.pan_x -= 23
    app.pan_y -= 17
    cpx = int(app.bm.cell_pixel_size * app.map_scale)
    app.screen.fill((255, 255, 255))
    app._draw_concentration_terrain(cpx)
    sx, sy = app._cell_to_screen(col, row)
    centre = (sx + cpx // 2, sy + cpx // 2)
    assert app.screen.get_at(centre)[:3] == (0, 0, 0), \
        f"the wall is not drawn on its cell at 2x zoom: {centre} is {app.screen.get_at(centre)}"
    # One cell further on is clear — the wall grew with the zoom, but no further.
    nxt = (sx + cpx + cpx // 2, sy + cpx // 2)
    assert app.screen.get_at(nxt)[:3] == (255, 255, 255), \
        f"the wall spills past its cell at 2x zoom: {nxt} is {app.screen.get_at(nxt)}"
    print("✅ test_painted_terrain_follows_the_main_map_zoom passed")


def test_applying_terrain_while_zoomed_blocks_the_right_cells():
    """Regions → cells divided by the zoomed scale, so a terrain load while zoomed
    painted the wrong cells into the engine."""
    app = App(MAP_PATH, seed=SEED)
    col, row = 4, 2
    app._terrain_regions = [_wall_region_on(app, col, row)]
    app._zoom_by(2.0)
    app._apply_terrain_to_battle_map()
    walls = {(c, r) for c in range(app.bm.grid_cols) for r in range(app.bm.grid_rows)
             if app.bm.get_terrain_type(rpg.Cell(c, r)) == rpg.TerrainType.Wall}
    assert walls == {(col, row)}, f"zoomed apply painted {sorted(walls)}, not {(col, row)}"
    print("✅ test_applying_terrain_while_zoomed_blocks_the_right_cells passed")


def main():
    tests = [test_painted_terrain_follows_the_main_map_zoom,
             test_applying_terrain_while_zoomed_blocks_the_right_cells,
             test_zoom_keeps_the_point_under_the_cursor,
             test_a_zoomed_drag_stores_the_same_region_as_a_fit_drag,
             test_a_zoomed_door_click_lands_on_the_cell_under_the_pointer,
             test_a_press_over_the_panel_does_nothing,
             test_wheel_keys_pan_and_zoom,
             test_a_plain_drag_pans_and_authors_nothing,
             test_the_editor_opens_and_closes_on_the_map_view,
             test_drawing_at_high_zoom_paints_the_viewport_only,
             test_the_lighting_editor_lets_zoom_and_pan_through]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_editor_zoom_pan: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_editor_zoom_pan: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
