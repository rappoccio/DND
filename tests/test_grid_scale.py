#!/usr/bin/env python3
"""Map scale on Set Grid…: "1 square = X ft".

The engine's cell is always 5 ft. A map drawn at 10 ft per square has to be gridded at
half the drawn square, so a sampled 10-ft square becomes 2×2 engine cells. This drives
the real `GridSpanDialog` with clicks (pick a scale chip, press OK) and the real
`App._on_grid_span`, then checks the cell size, the grid count and what was persisted.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import pygame

from dialogs import GridSpanDialog
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")

failures = 0


def check(cond, msg):
    global failures
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures += 1


def click(dlg, pos):
    dlg.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))


def run_dialog(app, square_ft, preset=5):
    """Open the dialog, click the `square_ft` chip, press OK; return the callback result."""
    got = []
    dlg = app._grid_span_dialog
    dlg.show(got.append, square_ft=preset)
    dlg.draw(app.screen)                 # lays out OK/Cancel and ends the swallow frame
    chip = next(r for r, ft in dlg._scale_rects if ft == square_ft)
    click(dlg, chip.center)
    check(dlg.visible, f"clicking the {square_ft}-ft chip keeps the dialog open")
    dlg.draw(app.screen)
    click(dlg, dlg._ok_rect.center)
    check(not dlg.visible and len(got) == 1, f"OK closes the dialog ({square_ft} ft)")
    return got[0] if got else None


def main():
    app = App(MAP_PATH, seed=1)
    tmp = tempfile.mkdtemp()
    app._terrain_path = os.path.join(tmp, "scale_terrain.json")   # don't touch maps/

    check(GridSpanDialog.SCALES == (5, 10, 15, 20), "scales offered are 5/10/15/20 ft")

    # Preset that isn't offered falls back to 5 ft.
    dlg = app._grid_span_dialog
    dlg.show(lambda r: None, square_ft=7)
    check(dlg._square_ft == 5, "an unknown preset falls back to 5 ft")
    dlg.visible = False

    # A 120×120 box spanning 1×1 drawn squares, at each scale.
    for ft, want_px in ((5, 120), (10, 60), (15, 40), (20, 30)):
        result = run_dialog(app, ft)
        check(result == (1, 1, ft), f"dialog returns (1, 1, {ft}) — got {result}")
        app._pending_grid_box = (0.0, 0.0, 120.0, 120.0)
        app._on_grid_span(result)
        check(app.bm.cell_pixel_size == want_px,
              f"{ft} ft/square → {want_px}px cells (got {app.bm.cell_pixel_size})")
        with open(app._terrain_path) as f:
            mg = json.load(f).get("manual_grid", {})
        check(mg.get("cell_px") == want_px and mg.get("square_ft") == ft,
              f"manual_grid persists cell_px={want_px}, square_ft={ft} (got {mg})")

    # A wide sample: 3 drawn 10-ft squares across 150px → 50px squares → 25px cells.
    app._pending_grid_box = (0.0, 0.0, 150.0, 150.0)
    app._on_grid_span((3, 3, 10))
    check(app.bm.cell_pixel_size == 25, f"3×3 squares of 10 ft in 150px → 25px "
                                        f"(got {app.bm.cell_pixel_size})")

    # The next Set Grid… pre-selects the scale last used.
    app._finalize_grid_sample((app.pan_x, app.pan_y),
                              (app.pan_x + 100 * app.map_scale, app.pan_y + 100 * app.map_scale))
    check(dlg.visible and dlg._square_ft == 10, "reopening pre-selects the last scale (10 ft)")
    dlg.visible = False

    # 5-ft cells halve the cell at 10 ft: twice the columns of a 5-ft grid on the same box.
    app._pending_grid_box = (0.0, 0.0, 100.0, 100.0)
    app._on_grid_span((1, 1, 5))
    cols5 = app.bm.grid_cols
    app._pending_grid_box = (0.0, 0.0, 100.0, 100.0)
    app._on_grid_span((1, 1, 10))
    check(abs(app.bm.grid_cols - 2 * cols5) <= 1,
          f"10 ft/square gives ~2× the columns of 5 ft ({cols5} → {app.bm.grid_cols})")

    print(f"\n{'OK' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
