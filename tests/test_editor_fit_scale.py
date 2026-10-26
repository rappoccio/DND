#!/usr/bin/env python3
"""The terrain editor on a map too big for the window.

The app shrinks a large map to fit (``base_map_scale`` < 1) and the terrain editor
draws on that fit-scale copy. The engine's grid lines are in image px, and the editor
used them unscaled: on a 3000×4072 page (fit ≈ 0.255) its detected edge walls were
drawn ~4× too far out, and clicks for cells, edges, doors and ladders hit the wrong
cells. Every grid position the editor uses now goes through ``_grid``, which scales
by the fit scale the app hands it.

  · the editor gets the app's fit scale;
  · a detected edge wall is drawn on its grid line in fit-scale px, not at its image px;
  · a door click on a cell centre lands on that cell;
  · the edge picked under the pointer is the edge drawn there.
"""

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

SEED = 20261026
CELL = 100          # image px
SIDE = 2400         # image px: well past the 1040px fit height
RED = (200, 60, 60)

_tmp = tempfile.mkdtemp(prefix="fit_scale_")


def _big_map():
    """A white SIDE×SIDE page with a black line every CELL px."""
    path = os.path.join(_tmp, "big_grid.png")
    if not os.path.exists(path):
        surf = pygame.Surface((SIDE, SIDE))
        surf.fill((255, 255, 255))
        for k in range(0, SIDE + 1, CELL):
            pygame.draw.line(surf, (0, 0, 0), (k, 0), (k, SIDE), 2)
            pygame.draw.line(surf, (0, 0, 0), (0, k), (SIDE, k), 2)
        pygame.image.save(surf, path)
    return path


def _terrain_app():
    app = App(_big_map(), seed=SEED)
    app.bm.set_uniform_grid(CELL, 0, 0)
    app._open_terrain_editor()
    ed = app.terrain_editor
    ed.draw(app.screen)          # establishes the viewport
    return app, ed


def _ev(kind, **kw):
    return pygame.event.Event(kind, **kw)


def _click(ed, pos):
    ed.handle(_ev(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    ed.handle(_ev(pygame.MOUSEBUTTONUP, pos=pos, button=1))


def _fit_centre(app, col, row):
    """Centre of (col, row) in fit-scale px."""
    s = app.base_map_scale
    v, h = app.bm.v_line_positions, app.bm.h_line_positions
    return (int((v[col] + v[col + 1]) / 2 * s), int((h[row] + h[row + 1]) / 2 * s))


def test_the_editor_gets_the_fit_scale():
    app, ed = _terrain_app()
    assert app.base_map_scale < 0.5, f"test map isn't shrunk: {app.base_map_scale}"
    assert ed.grid_scale == app.base_map_scale, \
        f"editor grid_scale {ed.grid_scale}, app fit scale {app.base_map_scale}"
    print("✅ test_the_editor_gets_the_fit_scale passed")


def test_a_detected_edge_wall_is_drawn_on_its_grid_line():
    app, ed = _terrain_app()
    col, row = 3, 4
    app.bm.set_edge_wall(rpg.Cell(col, row), rpg.EdgeSide.East, True)
    ed.draw(app.screen)
    s = app.base_map_scale
    v, h = app.bm.v_line_positions, app.bm.h_line_positions
    mid_y = (h[row] + h[row + 1]) / 2
    on_line = (int(v[col + 1] * s), int(mid_y * s))
    assert ed._canvas.get_at(on_line)[:3] == RED, \
        f"no wall at its fit-scale line {on_line}: {ed._canvas.get_at(on_line)}"
    unscaled = (int(v[col + 1]), int(mid_y))     # where the old code drew it
    assert ed._canvas.get_at(unscaled)[:3] != RED, \
        f"wall drawn at its image px {unscaled}"
    print("✅ test_a_detected_edge_wall_is_drawn_on_its_grid_line passed")


def test_a_door_click_lands_on_the_cell_under_the_pointer():
    app, ed = _terrain_app()
    ed.selected_type = "Door"
    target = rpg.Cell(5, 7)
    _click(ed, ed._to_screen(_fit_centre(app, target.col, target.row)))
    assert app.bm.door_at(target) >= 0, \
        f"no door at {target.col},{target.row}; doors: " \
        f"{[[(c.col, c.row) for c in d.cells] for d in app.bm.doors]}"
    assert len(app.bm.doors) == 1, f"expected exactly one door, got {len(app.bm.doors)}"
    print("✅ test_a_door_click_lands_on_the_cell_under_the_pointer passed")


def test_the_edge_under_the_pointer_is_picked():
    app, ed = _terrain_app()
    col, row = 6, 2
    s = app.base_map_scale
    v, h = app.bm.v_line_positions, app.bm.h_line_positions
    # Just inside (col, row), near its east line.
    pos = (int(v[col + 1] * s) - 2, int((h[row] + h[row + 1]) / 2 * s))
    assert ed._nearest_edge(pos) == (col, row, "E"), \
        f"picked {ed._nearest_edge(pos)}, want {(col, row, 'E')}"
    a, b = ed._edge_segment((col, row, "E"))
    assert a[0] == b[0] == int(v[col + 1] * s), f"edge segment {a}-{b} not on the fit line"
    print("✅ test_the_edge_under_the_pointer_is_picked passed")


def main():
    tests = [test_the_editor_gets_the_fit_scale,
             test_a_detected_edge_wall_is_drawn_on_its_grid_line,
             test_a_door_click_lands_on_the_cell_under_the_pointer,
             test_the_edge_under_the_pointer_is_picked]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_editor_fit_scale: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_editor_fit_scale: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
