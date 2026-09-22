"""Drive a headless `App` with real pygame events.

Not a test suite — a harness the GUI suites share. It exists because of the gap M0 and
M1 both had to record: everything between the *click* and the callback was unexercised.
`test_prompts.py` proves the prompt bus resolves a window; this proves the mouse reaches
the bus at all, through `App._handle_events` and `ContextMenu.handle` exactly as the DM's
own click does.

Why this is possible at all: `_handle_events` reads `pygame.event.get()`, so an event
posted onto the real queue is indistinguishable from one SDL put there. Under
`SDL_VIDEODRIVER=dummy` the display surface is a plain in-memory surface, which draws and
saves normally — so a check can also *look* at the result (`screenshot`).

Only MOUSEBUTTONDOWN is posted. Popups resolve on the button-down edge
(`ContextMenu.handle`), and posting a matching UP would hand a second event to the
drag/placement handlers that a menu click never involves.
"""

import os
import sys

# Must precede the first pygame import anywhere in the process.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import pygame

from constants import COL_BG
from dialogs import ContextMenu
import main  # noqa: F401 — imports pygame and builds the App class under the dummy driver


def cell_center(app, col: int, row: int) -> tuple[int, int]:
    """The screen pixel at the centre of a grid cell — the inverse of
    `App._screen_to_cell`, including pan and scale, so a posted click lands where a real
    one would."""
    v, h = app.bm.v_line_positions, app.bm.h_line_positions
    assert v and h, "the map has no detected grid"
    c = max(0, min(col, len(v) - 2))
    r = max(0, min(row, len(h) - 2))
    ix = (v[c] + v[c + 1]) / 2.0
    iy = (h[r] + h[r + 1]) / 2.0
    return (int(ix * app.map_scale + app.pan_x), int(iy * app.map_scale + app.pan_y))


def post_click(app, pos: tuple[int, int], button: int = 1) -> None:
    """Post one mouse-down at `pos` and let the app drain its queue."""
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                         pos=(int(pos[0]), int(pos[1])), button=button))
    alive = app._handle_events()
    assert alive is not False, "the app quit while handling a synthesized click"


def menu_labels(app) -> list[str]:
    return [label for label, _ in app.context_menu.items]


def menu_row_pos(app, label: str) -> tuple[int, int]:
    """The centre of the popup row carrying `label`. Geometry comes from `ContextMenu`'s
    own constants, so a change to the widget moves the click with it."""
    menu = app.context_menu
    assert menu.visible and menu.rect is not None, "no popup is open"
    labels = menu_labels(app)
    assert label in labels, f"no row {label!r} in {labels}"
    i = labels.index(label)
    return (menu.rect.x + menu.rect.width // 2,
            menu.rect.y + ContextMenu.PAD + i * ContextMenu.ITEM_H + ContextMenu.ITEM_H // 2)


def click_menu(app, label: str) -> None:
    """Click a popup row by its visible text."""
    post_click(app, menu_row_pos(app, label))


def click_away(app) -> None:
    """Click outside the popup — the dismissal path. The point is chosen off the menu
    rect and inside the window, which is all `ContextMenu.handle` inspects before it
    dismisses and consumes the event."""
    menu = app.context_menu
    assert menu.visible and menu.rect is not None, "no popup is open"
    w, h = app.screen.get_size()
    x = menu.rect.right + 40 if menu.rect.right + 40 < w else max(0, menu.rect.left - 40)
    y = menu.rect.bottom + 40 if menu.rect.bottom + 40 < h else max(0, menu.rect.top - 40)
    post_click(app, (x, y))


def screenshot(app, path: str) -> str:
    """Render the board, the panel and any popup, and write a PNG.

    A *subset* of `run()`'s draw sequence, deliberately: the frame is composed inline in
    the main loop and has no extractable `_draw_frame()`, and reproducing all 25 calls
    here would be a second copy of it to keep in sync. What is drawn is what a popup
    check needs to see — modals and overlays are not included.
    """
    app.screen.fill(COL_BG)
    app._draw_map()
    app._draw_agents()
    app._draw_panel()
    app.context_menu.draw(app.screen)
    pygame.image.save(app.screen, path)
    return path
