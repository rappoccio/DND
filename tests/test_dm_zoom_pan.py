#!/usr/bin/env python3
"""The DM screen zooms and pans the way the player screen does (net/static/app.js).

  · the wheel zooms at the cursor, no modifier needed, keeping the map point under it;
  · a press on empty map that moves past the slop pans; one that doesn't is a click;
  · the pan is clamped so the viewport's centre stays over the map;
  · the on-map control's + / − zoom about the viewport centre and Fit returns to the
    fit scale with the map at the top-left.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261021


def _ev(kind, **kw):
    return pygame.event.Event(kind, **kw)


def _run(app, *events):
    pygame.event.clear()
    for e in events:
        pygame.event.post(e)
    app._handle_events()


def _press(pos):
    return _ev(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


def _move(pos):
    return _ev(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0))


def _release(pos):
    return _ev(pygame.MOUSEBUTTONUP, pos=pos, button=1)


def _world_at(app, sx, sy):
    return ((sx - app.pan_x) / app.map_scale, (sy - app.pan_y) / app.map_scale)


def _empty_point(app):
    """A screen point on an empty cell, well inside the map."""
    assert not app.bm.placed_agents
    return (app.map_rect.w // 3, app.map_rect.h // 3)


def test_the_wheel_zooms_at_the_cursor():
    app = App(MAP_PATH, seed=SEED)
    mouse = pygame.mouse.get_pos()
    before = _world_at(app, *mouse)
    z = app.view_zoom
    _run(app, _ev(pygame.MOUSEWHEEL, x=0, y=1, flipped=False, precise_x=0.0, precise_y=1.0))
    assert app.view_zoom > z, "the wheel did not zoom in"
    after = _world_at(app, *mouse)
    assert abs(after[0] - before[0]) < 2 and abs(after[1] - before[1]) < 2, \
        f"the point under the cursor moved: {before} -> {after}"
    z = app.view_zoom
    _run(app, _ev(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False, precise_x=0.0, precise_y=-1.0))
    assert app.view_zoom < z, "the wheel did not zoom out"
    print("✅ test_the_wheel_zooms_at_the_cursor passed")


def test_dragging_empty_map_pans():
    app = App(MAP_PATH, seed=SEED)
    x, y = _empty_point(app)
    _run(app, _press((x, y)), _move((x - 20, y - 15)), _move((x - 40, y - 30)),
         _release((x - 40, y - 30)))
    assert (app.pan_x, app.pan_y) == (-40, -30), (app.pan_x, app.pan_y)
    assert app._pan_drag is None
    print("✅ test_dragging_empty_map_pans passed")


def test_a_press_inside_the_slop_does_not_pan():
    app = App(MAP_PATH, seed=SEED)
    x, y = _empty_point(app)
    _run(app, _press((x, y)), _move((x + 2, y + 2)), _release((x + 2, y + 2)))
    assert (app.pan_x, app.pan_y) == (0, 0), (app.pan_x, app.pan_y)
    print("✅ test_a_press_inside_the_slop_does_not_pan passed")


def test_the_pan_stops_with_the_map_in_sight():
    app = App(MAP_PATH, seed=SEED)
    x, y = _empty_point(app)
    _run(app, _press((x, y)), _move((x - 10, y)), _move((x - 100000, y - 100000)),
         _release((x - 100000, y - 100000)))
    vx, vy = app._panel_x() // 2, app.screen.get_height() // 2
    assert (app.pan_x, app.pan_y) == (vx - app.map_rect.w, vy - app.map_rect.h), \
        (app.pan_x, app.pan_y)
    print("✅ test_the_pan_stops_with_the_map_in_sight passed")


def test_the_zoom_control():
    app = App(MAP_PATH, seed=SEED)
    rects = app._zoom_control_rects()
    _run(app, _press(rects["in"].center))
    assert abs(app.view_zoom - App.ZOOM_BTN_STEP) < 1e-6, app.view_zoom
    _run(app, _press(rects["out"].center), _press(rects["out"].center))
    assert app.view_zoom < 1.0, app.view_zoom
    _run(app, _press(rects["in"].center), _press(rects["in"].center))
    x, y = _empty_point(app)
    _run(app, _press((x, y)), _move((x - 30, y - 30)), _release((x - 30, y - 30)))
    assert (app.pan_x, app.pan_y) != (0, 0)
    _run(app, _press(rects["fit"].center))
    assert app.view_zoom == 1.0 and (app.pan_x, app.pan_y) == (0, 0), \
        (app.view_zoom, app.pan_x, app.pan_y)
    app._draw_zoom_control()      # draws without raising
    print("✅ test_the_zoom_control passed")


def main():
    pygame.init()
    tests = [test_the_wheel_zooms_at_the_cursor,
             test_dragging_empty_map_pans,
             test_a_press_inside_the_slop_does_not_pan,
             test_the_pan_stops_with_the_map_in_sight,
             test_the_zoom_control]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
