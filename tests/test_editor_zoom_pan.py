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
  · wheel / arrows pan, Ctrl+wheel and +/- zoom, 0 resets; +/- keep their Door-mode
    meaning (lock DC);
  · drawing at high zoom works and paints the viewport only;
  · the lighting editor passes wheel / zoom keys through to the app's map, and its
    overlay follows the zoom.
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


def _drag(ed, a, b, button=1):
    ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=a, button=button))
    ed.handle(_ev(pygame.MOUSEMOTION, pos=b, rel=(0, 0), buttons=(1, 0, 0)))
    ed.handle(_ev(pygame.MOUSEBUTTONUP, pos=b, button=button))


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
    app, ed = _terrain_app()
    ed.handle(_wheel(y=-2))
    assert ed.view_pan == [0, -60], ed.view_pan
    ed.handle(_key(pygame.K_LEFT))
    assert ed.view_pan == [30, -60], ed.view_pan
    pygame.key.set_mods(pygame.KMOD_CTRL)
    try:
        ed.handle(_wheel(y=1))
    finally:
        pygame.key.set_mods(0)
    assert ed.view_zoom > 1.0, "Ctrl+wheel did not zoom"
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

    # Middle-drag pans.
    ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=(50, 50), button=2))
    ed.handle(_ev(pygame.MOUSEMOTION, pos=(80, 30), rel=(30, -20), buttons=(0, 1, 0)))
    ed.handle(_ev(pygame.MOUSEBUTTONUP, pos=(80, 30), button=2))
    assert ed.view_pan == [30, -20], ed.view_pan
    print("✅ test_wheel_keys_pan_and_zoom passed")


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
    pygame.event.post(_wheel(y=-1))
    app._handle_events()
    assert app.view_zoom > z, "+ did not zoom the map under the lighting editor"
    pan_before = app.pan_y
    pygame.event.post(_wheel(y=-1))
    app._handle_events()
    assert app.pan_y == pan_before - 30, \
        f"wheel did not pan under the lighting editor: {pan_before} -> {app.pan_y}"
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


def main():
    tests = [test_zoom_keeps_the_point_under_the_cursor,
             test_a_zoomed_drag_stores_the_same_region_as_a_fit_drag,
             test_a_zoomed_door_click_lands_on_the_cell_under_the_pointer,
             test_a_press_over_the_panel_does_nothing,
             test_wheel_keys_pan_and_zoom,
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
