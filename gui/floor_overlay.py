"""Align Floor: see the floor below (or above) through the current page.

DUNGEON_LEVELS_PLAN.md, Phase 1. A dungeon's pages sit on a shared global (X, Y, Z)
grid, but nothing used to show two floors together, so lining a basement up meant
guessing an origin. This module draws the pages of floor z - 1 (or z + 1) as
semi-transparent "ghosts" over the current page, each placed at its own global origin
and scaled so its cells land on the current page's cells for the same global (X, Y).

Pages drawn at different pixel scales still line up cell for cell: the placement is an
affine map from ghost-native pixels to current-native pixels, built from each page's
mean cell size and its grid's first line.

    x_cur = ox + sx * x_ghost        sx = cur_cell_w / ghost_cell_w
    y_cur = oy + sy * y_ghost        ox = cur_v[0] + (ghost_gx - cur_gx) * cur_cell_w
                                          - ghost_v[0] * sx

The renderer (``draw_ghosts``) is kept separate from the mode (``FloorAlign``) because
Phase 4's exit picker reuses it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import pygame

GHOST_ALPHA = 120          # 0–255; the current page's art stays readable underneath
GHOST_OUTLINE = (90, 200, 255)


def grid_extent(v_lines, h_lines) -> Optional[tuple[float, float, float, float]]:
    """(x0, y0, cell_w, cell_h) of a grid, from its line positions in native pixels.

    Cell size is the mean over the whole grid, so an auto-detected grid with a pixel
    of jitter per line still maps evenly. None when the grid has no cells."""
    if not v_lines or not h_lines or len(v_lines) < 2 or len(h_lines) < 2:
        return None
    cols, rows = len(v_lines) - 1, len(h_lines) - 1
    cw = (v_lines[-1] - v_lines[0]) / cols
    ch = (h_lines[-1] - h_lines[0]) / rows
    if cw <= 0 or ch <= 0:
        return None
    return (float(v_lines[0]), float(h_lines[0]), float(cw), float(ch))


def ghost_placement(cur_lines, cur_origin, ghost_lines, ghost_origin):
    """The affine map (sx, sy, ox, oy) from ghost-native to current-native pixels.

    ``*_lines`` are (v_line_positions, h_line_positions); ``*_origin`` are the pages'
    global origins (only X and Y are read). None if either grid is unusable."""
    cur = grid_extent(*cur_lines)
    gho = grid_extent(*ghost_lines)
    if cur is None or gho is None:
        return None
    cx0, cy0, cw, ch = cur
    gx0, gy0, gw, gh = gho
    sx, sy = cw / gw, ch / gh
    dcol = int(ghost_origin[0]) - int(cur_origin[0])
    drow = int(ghost_origin[1]) - int(cur_origin[1])
    ox = cx0 + dcol * cw - gx0 * sx
    oy = cy0 + drow * ch - gy0 * sy
    return (sx, sy, ox, oy)


def load_ghost_lines(png_path: str, terrain_path: Optional[str]):
    """A page's grid lines (v, h) in native pixels, or None if it has no usable grid.

    A saved ``manual_grid`` in the page's ``_terrain.json`` wins (as it does when the
    page is loaded for play); otherwise a headless ``BattleMap`` analyses the PNG."""
    import rpg_battle_map as rpg
    try:
        bm = rpg.BattleMap(png_path)
    except Exception:
        return None
    mg = None
    if terrain_path and os.path.exists(terrain_path):
        try:
            with open(terrain_path) as f:
                mg = json.load(f).get("manual_grid")
        except (OSError, ValueError):
            mg = None
    try:
        if mg:
            bm.set_uniform_grid(int(mg["cell_px"]), int(mg["anchor"][0]), int(mg["anchor"][1]))
        else:
            bm.analyze_grid()
    except Exception:
        return None
    v, h = list(bm.v_line_positions), list(bm.h_line_positions)
    if grid_extent(v, h) is None:
        return None
    return (v, h)


@dataclass
class Ghost:
    """One page of the other floor, ready to draw."""
    page_id: str
    origin: tuple[int, int, int]
    lines: tuple[list, list]
    image: pygame.Surface           # native resolution
    _cache_key: tuple = ()
    _cache_surf: Optional[pygame.Surface] = None
    _cache_pos: tuple[int, int] = (0, 0)


def draw_ghosts(screen, ghosts, cur_lines, cur_origin, map_scale, pan, viewport,
                alpha=GHOST_ALPHA, font=None):
    """Blit each ghost over the map, placed by global origin and scaled cell for cell.

    Only the part of a ghost inside ``viewport`` (a screen Rect) is scaled, so a zoomed
    map never allocates a ghost bigger than the screen. The scaled piece is cached on
    the ghost until its placement, the zoom or the pan changes."""
    for g in ghosts:
        pl = ghost_placement(cur_lines, cur_origin, g.lines, g.origin)
        if pl is None:
            continue
        sx, sy, ox, oy = pl
        iw, ih = g.image.get_size()
        # The ghost's full rectangle, in screen pixels.
        sx_s, sy_s = sx * map_scale, sy * map_scale
        left = ox * map_scale + pan[0]
        top = oy * map_scale + pan[1]
        full = pygame.Rect(int(round(left)), int(round(top)),
                           max(1, int(round(iw * sx_s))), max(1, int(round(ih * sy_s))))
        vis = full.clip(viewport)
        if vis.width <= 0 or vis.height <= 0:
            continue
        key = (vis.x, vis.y, vis.w, vis.h, round(left, 2), round(top, 2),
               round(sx_s, 6), round(sy_s, 6), alpha)
        if key != g._cache_key:
            # The visible screen rect, back in ghost-native pixels.
            nx0 = max(0, int((vis.x - left) / sx_s))
            ny0 = max(0, int((vis.y - top) / sy_s))
            nx1 = min(iw, int((vis.right - left) / sx_s + 1))
            ny1 = min(ih, int((vis.bottom - top) / sy_s + 1))
            if nx1 <= nx0 or ny1 <= ny0:
                continue
            piece = g.image.subsurface(pygame.Rect(nx0, ny0, nx1 - nx0, ny1 - ny0))
            dw = max(1, int(round((nx1 - nx0) * sx_s)))
            dh = max(1, int(round((ny1 - ny0) * sy_s)))
            surf = pygame.transform.smoothscale(piece, (dw, dh))
            surf.set_alpha(alpha)
            g._cache_key = key
            g._cache_surf = surf
            g._cache_pos = (int(round(left + nx0 * sx_s)), int(round(top + ny0 * sy_s)))
        prev_clip = screen.get_clip()
        screen.set_clip(viewport)
        screen.blit(g._cache_surf, g._cache_pos)
        pygame.draw.rect(screen, GHOST_OUTLINE, full, 2)
        if font is not None:
            screen.blit(font.render(g.page_id, True, GHOST_OUTLINE),
                        (max(viewport.x, full.x) + 4, max(viewport.y, full.y) + 4))
        screen.set_clip(prev_clip)


class FloorAlign:
    """The Align Floor mode: ghost the floor below (Tab: above) and nudge the current
    page's origin one cell per arrow key. Enter saves the manifest; Esc restores the
    origin the mode started with.

    The current page moves on screen with its origin (the pan follows the nudge), so the
    ghost floor stays put and the page slides over it, which is what the DM is lining
    up by eye."""

    def __init__(self):
        self.active = False
        self.direction = -1             # -1: the floor below, +1: the floor above
        self.start_origin: Optional[list[int]] = None
        self.ghosts: list[Ghost] = []
        self.skipped: list[str] = []    # pages of the ghost floor with no usable grid
        self._pan_acc = [0.0, 0.0]      # unrounded pan the nudges have applied
        self._font = None

    # ── Mode lifecycle ──────────────────────────────────────────────────────
    def start(self, app) -> bool:
        page = app.dungeon_page
        if app.dungeon is None or page is None:
            app._flash_status("No dungeon open — New Dungeon first.")
            return False
        if app.combat_active:
            app._flash_status("Finish combat before aligning floors.")
            return False
        self.start_origin = list(page.origin)
        self._pan_acc = [0.0, 0.0]
        self.active = True
        if not self._load(app, self.direction) and not self._load(app, -self.direction):
            self.active = False
            self.start_origin = None
            app._flash_status(f"No other floor next to floor {page.z} to align against.")
            return False
        self._announce(app)
        return True

    def finish(self, app, keep: bool):
        """Leave the mode, saving the nudged origin (keep) or restoring the start."""
        page = app.dungeon_page
        if page is not None and self.start_origin is not None:
            if keep:
                app._apply_page_origin(page)
                app._dungeon_save()
            else:
                self.nudge(app, self.start_origin[0] - page.gx, self.start_origin[1] - page.gy)
                app._flash_status(f"Align cancelled: {page.id} back at "
                                  f"({page.gx}, {page.gy}, {page.z}).")
        self.active = False
        self.start_origin = None
        self.ghosts = []
        self.skipped = []

    # ── Ghost floor ─────────────────────────────────────────────────────────
    def _load(self, app, direction: int) -> bool:
        """Load the ghosts for floor z + direction; False if that floor has no pages."""
        page = app.dungeon_page
        z = page.z + direction
        pages = app.dungeon.pages_on_floor(z)
        if not pages:
            return False
        ghosts, skipped = [], []
        for p in pages:
            png = app._page_png_path(p)
            lines = load_ghost_lines(png, app._page_terrain_path(p)) if os.path.exists(png) else None
            if lines is None:
                skipped.append(p.id)
                continue
            try:
                img = pygame.image.load(png).convert()
            except pygame.error:
                skipped.append(p.id)
                continue
            ghosts.append(Ghost(p.id, (p.gx, p.gy, p.z), lines, img))
        self.direction = direction
        self.ghosts = ghosts
        self.skipped = skipped
        return True

    def toggle_floor(self, app):
        if not self._load(app, -self.direction):
            app._flash_status(f"No floor {app.dungeon_page.z - self.direction} to show.")
            return
        self._announce(app)

    def _announce(self, app):
        z = app.dungeon_page.z + self.direction
        msg = f"Align: showing floor {z} ({len(self.ghosts)} page(s))."
        if self.skipped:
            msg += f" Skipped, no usable grid: {', '.join(self.skipped)}."
        app._flash_status(msg)

    # ── Nudging ─────────────────────────────────────────────────────────────
    def nudge(self, app, dx: int, dy: int):
        """Move the current page's origin by (dx, dy) cells, panning the map with it."""
        if dx == 0 and dy == 0:
            return
        page = app.dungeon_page
        page.origin = [page.gx + dx, page.gy + dy, page.z]
        ext = grid_extent(app.bm.v_line_positions, app.bm.h_line_positions)
        if ext is not None:
            # Pan by the unrounded running total, so nudging there and back nets to zero.
            ax, ay = self._pan_acc
            nx, ny = ax + dx * ext[2] * app.map_scale, ay + dy * ext[3] * app.map_scale
            app.pan_x += int(round(nx)) - int(round(ax))
            app.pan_y += int(round(ny)) - int(round(ay))
            self._pan_acc = [nx, ny]

    def handle_key(self, app, event) -> bool:
        """Consume a key while the mode is on. True if the key was the mode's."""
        if event.type != pygame.KEYDOWN:
            return False
        steps = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0),
                 pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}
        if event.key in steps:
            self.nudge(app, *steps[event.key])
            return True
        if event.key == pygame.K_TAB:
            self.toggle_floor(app)
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.finish(app, keep=True)
            return True
        if event.key == pygame.K_ESCAPE:
            self.finish(app, keep=False)
            return True
        return False

    # ── Drawing ─────────────────────────────────────────────────────────────
    def draw(self, app):
        if not self.active:
            return
        if app.dungeon is None or app.dungeon_page is None:     # dungeon closed under us
            self.active = False
            return
        if self._font is None:
            self._font = pygame.font.SysFont("sans", 14, bold=True)
        page = app.dungeon_page
        bar_h = self._font.get_height() + 8
        # Below the instruction bar, so a ghost's page label is never hidden under it.
        viewport = pygame.Rect(0, bar_h, app._panel_x(), app.screen.get_height() - bar_h)
        draw_ghosts(app.screen, self.ghosts,
                    (app.bm.v_line_positions, app.bm.h_line_positions),
                    page.origin, app.map_scale, (app.pan_x, app.pan_y), viewport,
                    font=self._font)
        z = page.z + self.direction
        text = (f"ALIGN {page.id} at ({page.gx}, {page.gy}, {page.z}) over floor {z}   "
                f"arrows: move 1 cell · Tab: floor {'above' if self.direction < 0 else 'below'}"
                f" · Enter: save · Esc: cancel")
        label = self._font.render(text, True, (255, 255, 255))
        bar = pygame.Rect(0, 0, min(viewport.width, label.get_width() + 16), bar_h)
        pygame.draw.rect(app.screen, (20, 40, 60), bar)
        app.screen.blit(label, (8, 4))
