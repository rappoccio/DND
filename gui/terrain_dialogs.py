# ─────────────────────────────────────────────────────────────────────────────
#  terrain_dialogs.py  –  Terrain editing dialogs
# ─────────────────────────────────────────────────────────────────────────────

import math
import pygame
import rpg_battle_map as rpg
from constants import *
from widgets import Button


def door_link_key(cells):
    """Canonical, order-independent key for a door's cell footprint.

    A door lives in the C++ ``BattleMap`` and cannot itself hold the Python-only
    cross-map ``link_target`` (Floors Phase 5). We therefore key links by the door's
    cells, which are stable across save/reload (doors are re-added with the same
    cells). Accepts ``rpg.Cell`` objects or ``(col, row)`` tuples."""
    out = []
    for c in cells:
        if hasattr(c, "col"):
            out.append((int(c.col), int(c.row)))
        else:
            out.append((int(c[0]), int(c[1])))
    return tuple(sorted(out))


def draw_door_glyph(screen, x, y, size, door, font_sm=None, w=None, h=None, linked=False):
    """Draw a door over screen rect (x, y, w, h) — defaults to a single cell (size×size).

    `door` is an rpg.Door. Closed doors are a filled wooden slab; open doors are an
    ajar frame. A locked door shows a gold padlock; an Arcane Lock shows a purple one.
    Used by both the in-game render loop (main.py) and the terrain editor below so the
    door looks identical wherever it is drawn. A wide (multi-cell) door is drawn as one
    elongated slab over its full bounding rect: pass w/h covering all of its cells.
    `linked` marks a cross-map door staple (leads to an abutting page) with a small
    teal corner chevron so a DM can tell a portal door from an ordinary one.
    """
    if w is None:
        w = size
    if h is None:
        h = size
    short = min(w, h)
    pad = max(2, short // 8)
    if door.open:
        # Open: faint green frame plus a thin ajar slab hinged on the left edge.
        frame = pygame.Rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad)
        pygame.draw.rect(screen, (120, 200, 120), frame, 2)
        slab = pygame.Rect(x + pad, y + pad, max(3, short // 4), h - 2 * pad)
        s = pygame.Surface((slab.w, slab.h), pygame.SRCALPHA)
        s.fill((139, 90, 43, 130))
        screen.blit(s, (slab.x, slab.y))
    else:
        # Closed: solid wooden slab with a centre plank line and a knob.
        slab = pygame.Rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad)
        pygame.draw.rect(screen, (110, 70, 35), slab)
        pygame.draw.rect(screen, (70, 45, 20), slab, 2)
        midx = slab.x + slab.w // 2
        pygame.draw.line(screen, (70, 45, 20), (midx, slab.y), (midx, slab.y + slab.h), 1)
        knob_r = max(2, short // 14)
        pygame.draw.circle(screen, (210, 180, 60),
                           (slab.x + slab.w - knob_r * 3, slab.y + slab.h // 2), knob_r)

    if door.locked or door.arcane_lock:
        lock_col = (180, 80, 220) if door.arcane_lock else (230, 200, 60)
        cx = x + w // 2
        cy = y + h // 2
        body_w = max(6, short // 4)
        body_h = max(5, short // 5)
        body = pygame.Rect(cx - body_w // 2, cy, body_w, body_h)
        pygame.draw.rect(screen, lock_col, body)
        pygame.draw.rect(screen, (30, 30, 30), body, 1)
        sh_r = body_w // 2
        pygame.draw.arc(screen, lock_col,
                        pygame.Rect(cx - sh_r, cy - sh_r, sh_r * 2, sh_r * 2),
                        0.0, math.pi, 2)

    if linked:
        # Cross-map staple marker: a small teal chevron ">>" in the top-right corner.
        m = max(3, short // 6)
        tx, ty = x + w - m - 2, y + 3
        teal = (90, 210, 210)
        pygame.draw.lines(screen, teal, False,
                          [(tx, ty), (tx + m, ty + m // 2), (tx, ty + m)], 2)
        pygame.draw.lines(screen, teal, False,
                          [(tx + m // 2, ty), (tx + m + m // 2, ty + m // 2),
                           (tx + m // 2, ty + m)], 2)


def draw_ladder_glyph(screen, x, y, size, going_up=True, font_sm=None, w=None, h=None):
    """Draw a ladder (vertical portal to another floor) over screen rect (x, y, w, h).

    Two side rails with rungs, plus a small arrow showing travel direction: `going_up`
    ascends a floor (z+1), else descends (z-1). Used by both the in-game render loop
    (main.py) and the terrain editor so a ladder looks identical wherever it is drawn.
    Wide (multi-cell) ladders pass w/h covering all of their cells.
    """
    if w is None:
        w = size
    if h is None:
        h = size
    short = min(w, h)
    pad = max(2, short // 6)
    rail_col = (170, 130, 70)
    # Translucent backing so the ladder reads over any terrain colour.
    back = pygame.Surface((max(1, w - 2 * pad), max(1, h - 2 * pad)), pygame.SRCALPHA)
    back.fill((90, 60, 30, 90))
    screen.blit(back, (x + pad, y + pad))
    # Two side rails.
    rail_gap = max(4, (w - 2 * pad) // 3)
    lx = x + (w - rail_gap) // 2
    rx = x + (w + rail_gap) // 2
    top = y + pad
    bot = y + h - pad
    pygame.draw.line(screen, rail_col, (lx, top), (lx, bot), 2)
    pygame.draw.line(screen, rail_col, (rx, top), (rx, bot), 2)
    # Rungs.
    n_rungs = max(2, (h - 2 * pad) // max(4, short // 4))
    for i in range(n_rungs + 1):
        ry = top + (bot - top) * i // max(1, n_rungs)
        pygame.draw.line(screen, rail_col, (lx, ry), (rx, ry), 2)
    # Direction arrow (up = ascends, down = descends).
    cx = x + w // 2
    arr = max(3, short // 6)
    arr_col = (230, 220, 120)
    if going_up:
        pygame.draw.polygon(screen, arr_col,
                            [(cx, top - 1), (cx - arr, top + arr), (cx + arr, top + arr)])
    else:
        pygame.draw.polygon(screen, arr_col,
                            [(cx, bot + 1), (cx - arr, bot - arr), (cx + arr, bot - arr)])


class TemporaryTerrainPlacementDialog:
    """Modal dialog for placing temporary terrain effects during combat."""

    def __init__(self, font_sm, font_md):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.selected_cells = set()  # set of (col, row) tuples
        self.map_surf = None
        self.bm = None
        self.app = None  # Reference to App for callbacks
        self.terrain_type = rpg.TerrainDifficulty.Halved
        self.effect_name = "Terrain Effect"
        self.duration_rounds = 5
        self.source_agent_idx = -1  # -1 = DM-placed

    def open(self, map_surf, bm, app):
        """Open the dialog for placing terrain effects."""
        self.active = True
        self.map_surf = map_surf
        self.bm = bm
        self.app = app
        self.selected_cells = set()
        self.terrain_type = rpg.TerrainDifficulty.Halved
        self.effect_name = "Terrain Effect"
        self.duration_rounds = 5
        self.source_agent_idx = -1

    def close(self):
        """Close the dialog."""
        self.active = False
        self.selected_cells = set()

    def handle(self, event):
        """Handle mouse/keyboard events."""
        if not self.active or not self.bm:
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click on map
                col, row = self._screen_to_cell(event.pos)
                if 0 <= col < self.bm.grid_cols and 0 <= row < self.bm.grid_rows:
                    cell_tuple = (col, row)
                    if cell_tuple in self.selected_cells:
                        self.selected_cells.discard(cell_tuple)
                    else:
                        self.selected_cells.add(cell_tuple)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_1:
                self.terrain_type = rpg.TerrainDifficulty.Halved
            elif event.key == pygame.K_2:
                self.terrain_type = rpg.TerrainDifficulty.Quartered
            elif event.key == pygame.K_RETURN:
                self._confirm()
            elif event.key == pygame.K_ESCAPE:
                self.close()

    def _screen_to_cell(self, screen_pos):
        """Convert screen coordinates to grid (col, row)."""
        if not self.app:
            return -1, -1
        sx, sy = screen_pos
        cell = self.app._screen_to_cell(sx, sy)
        if cell:
            return cell.col, cell.row
        return -1, -1

    def _confirm(self):
        """Apply the selected terrain effect and close."""
        if not self.selected_cells or not self.bm or not self.app:
            return

        cells = [rpg.Cell(col, row) for col, row in sorted(self.selected_cells)]
        effect_id = self.bm.place_terrain_effect(
            self.effect_name,
            cells,
            self.terrain_type,
            self.duration_rounds,
            self.source_agent_idx
        )

        if effect_id >= 0:
            # Store metadata for rendering
            if self.terrain_type == rpg.TerrainDifficulty.Halved:
                color = (80, 200, 80, 80)  # Green
            elif self.terrain_type == rpg.TerrainDifficulty.Quartered:
                color = (200, 60, 60, 80)  # Red
            else:
                color = (100, 180, 220, 80)  # Cyan

            self.app._effect_meta[effect_id] = {
                "name": self.effect_name,
                "color": color,
                "cells": list(self.selected_cells)
            }

        self.close()

    def draw(self, screen):
        """Draw the dialog UI."""
        if not self.active or not self.map_surf:
            return

        # Draw semi-transparent overlay
        overlay = pygame.Surface(screen.get_size())
        overlay.set_alpha(128)
        overlay.fill((0, 0, 0))
        screen.blit(overlay, (0, 0))

        # Draw map
        screen.blit(self.map_surf, (0, 0))

        # Draw selected cells with highlight
        if self.bm and self.selected_cells:
            s = self.app.map_scale if self.app else 1.0
            cpx = int(self.bm.cell_pixel_size * s)
            for col, row in self.selected_cells:
                sx, sy = self.app._cell_to_screen(col, row) if self.app else (0, 0)
                color = (200, 255, 100, 150) if self.terrain_type == rpg.TerrainDifficulty.Halved else (255, 100, 100, 150)
                pygame.draw.rect(screen, color, pygame.Rect(sx, sy, cpx, cpx), 3)

        # Draw right panel with options
        panel_x = screen.get_width() - 300
        panel_y = 20
        panel_w = 280
        panel_h = 300

        pygame.draw.rect(screen, (50, 50, 50), (panel_x, panel_y, panel_w, panel_h))
        pygame.draw.rect(screen, (200, 200, 200), (panel_x, panel_y, panel_w, panel_h), 2)

        # Draw panel content
        y = panel_y + 10
        txt = self.font_md.render("Place Terrain Effect", True, (255, 255, 255))
        screen.blit(txt, (panel_x + 10, y))
        y += 35

        # Terrain type selector
        txt = self.font_sm.render("Type (1=Halved, 2=Quartered):", True, (200, 200, 200))
        screen.blit(txt, (panel_x + 10, y))
        y += 25
        type_str = "Halved (0.5x)" if self.terrain_type == rpg.TerrainDifficulty.Halved else "Quartered (0.25x)"
        txt = self.font_sm.render(type_str, True, (150, 255, 150))
        screen.blit(txt, (panel_x + 10, y))
        y += 25

        # Effect name (static for now)
        txt = self.font_sm.render(f"Name: {self.effect_name}", True, (200, 200, 200))
        screen.blit(txt, (panel_x + 10, y))
        y += 25

        # Duration
        txt = self.font_sm.render(f"Duration: {self.duration_rounds} rounds", True, (200, 200, 200))
        screen.blit(txt, (panel_x + 10, y))
        y += 30

        # Instructions
        txt = self.font_sm.render("Click cells to select/deselect", True, (150, 200, 255))
        screen.blit(txt, (panel_x + 10, y))
        y += 20
        txt = self.font_sm.render("Press ENTER to confirm", True, (150, 200, 255))
        screen.blit(txt, (panel_x + 10, y))
        y += 20
        txt = self.font_sm.render("Press ESC to cancel", True, (150, 150, 150))
        screen.blit(txt, (panel_x + 10, y))


class TerrainEditorDialog:
    """Modal dialog for marking terrain on the map (walls, chasms, water, difficult terrain)."""

    def __init__(self, font_sm, font_md):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.terrain_regions = []  # List of {type, col, row, width, height, multiplier}
        self.map_surf = None
        self.selection_start = None
        self.selection_rect = None
        self.selected_type = "Difficult Terrain"
        self.difficulty_mult = 0.5  # 0.5 for Halved, 0.25 for Quartered
        self.bm = None  # Reference to BattleMap for grid coordinate conversion
        self.selected_region_idx = -1  # Index of selected region for editing/deletion
        # Door-placement settings (applied to the next door clicked while "Door" is selected).
        # Doors live in BattleMap.doors (bm is the source of truth), not in terrain_regions.
        self.door_locked = False
        self.door_lock_dc = 15
        self.door_arcane = False
        # Drag-to-span door placement: start/end cells while the mouse is held.
        self.door_drag_start = None
        self.door_drag_end = None
        # Cross-map door staples (Floors Phase 5). When ``door_link`` is on, a door
        # placed on a page edge is auto-targeted to the abutting page's matching global
        # cell. ``door_links`` is app-owned (key -> [X,Y,Z]); the editor mutates the
        # reference passed to open() in place, like ``ladders``.
        self.door_link = False
        self.door_links = {}
        # Ladder placement (vertical portals). Ladders are Python-only cell objects —
        # the app owns the list; the editor mutates the reference passed to open().
        # Each entry is {"cells": [(col,row),...], "target": [X, Y, Z]} in GLOBAL coords.
        self.ladders = []
        self.ladder_up = False  # direction the next placed ladder travels (True = z+1)
        # Mapping from terrain type names to rpg.TerrainType enum values
        self.terrain_type_map = {
            "Standard": rpg.TerrainType.Standard,
            "Water": rpg.TerrainType.Water,
            "Wall": rpg.TerrainType.Wall,
            "Chasm": rpg.TerrainType.Chasm,
        }

    def open(self, map_surf, terrain_regions, bm=None, ladders=None, door_links=None):
        """Open the terrain editor with existing terrain data.

        ``ladders`` is the app's live ladder list (Python-only cell objects); the editor
        mutates it in place, so the caller sees placements/removals without a copy-back.
        ``door_links`` is the app's live door-link table (key -> [X,Y,Z]), mutated the
        same way for cross-map door staples."""
        self.active = True
        self.map_surf = map_surf
        self.terrain_regions = [r.copy() for r in terrain_regions] if terrain_regions else []
        self.selection_start = None
        self.selection_rect = None
        self.bm = bm
        self.ladders = ladders if ladders is not None else []
        self.door_links = door_links if door_links is not None else {}

    def close(self):
        """Close the terrain editor."""
        self.active = False

    def handle(self, event):
        """Handle mouse/keyboard events."""
        if not self.active:
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.selected_type == "Ladder":
                # A ladder is a single-cell portal: click places one (target auto-filled
                # to the same global X,Y one floor up/down); clicking an existing one
                # removes it (toggle, like a single-cell door).
                cell = self._pos_to_cell(event.pos)
                if cell is not None:
                    self._place_ladder(cell)
                return
            if event.button == 1 and self.selected_type == "Door":
                # A door spans 1..4 cells: press starts the span, drag sizes it, release
                # places it. (A press-and-release on one cell is the single-cell toggle.)
                self.door_drag_start = self._pos_to_cell(event.pos)
                self.door_drag_end = self.door_drag_start
                self.selection_start = None
                self.selection_rect = None
                return
            if event.button == 1:  # Left click
                # Check if clicking on existing region
                clicked_idx = self._get_region_at_pos(event.pos)
                if clicked_idx >= 0:
                    self.selected_region_idx = clicked_idx
                    self.selection_start = None
                    self.selection_rect = None
                else:
                    # Start new terrain selection
                    self.selection_start = event.pos
                    self.selection_rect = None
            elif event.button == 3:  # Right click to deselect
                self.selected_region_idx = -1

        elif event.type == pygame.MOUSEMOTION:
            if self.selected_type == "Door" and self.door_drag_start is not None:
                end = self._pos_to_cell(event.pos)
                if end is not None:
                    self.door_drag_end = end
            elif self.selection_start and self.selected_region_idx < 0:
                x0, y0 = self.selection_start
                x1, y1 = event.pos
                self.selection_rect = pygame.Rect(
                    min(x0, x1), min(y0, y1),
                    abs(x1 - x0), abs(y1 - y0)
                )

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.selected_type == "Door" and self.door_drag_start is not None:
                end = self._pos_to_cell(event.pos) or self.door_drag_end or self.door_drag_start
                self._place_door_span(self.door_drag_start, end)
                self.door_drag_start = None
                self.door_drag_end = None
                return
            if event.button == 1 and self.selection_rect and self.selection_rect.w > 0 and self.selection_rect.h > 0:
                self._apply_terrain_to_selection()
                self.selection_start = None
                self.selection_rect = None

        # Keyboard shortcuts
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_1:
                self.selected_type = "Wall"
            elif event.key == pygame.K_2:
                self.selected_type = "Chasm"
            elif event.key == pygame.K_3:
                self.selected_type = "Water"
            elif event.key == pygame.K_4:
                self.selected_type = "Difficult Terrain"
            elif event.key == pygame.K_5:
                self.selected_type = "Door"
            elif event.key == pygame.K_6:
                self.selected_type = "Ladder"
            elif event.key == pygame.K_u and self.selected_type == "Ladder":
                self.ladder_up = not self.ladder_up
            elif event.key == pygame.K_l and self.selected_type == "Door":
                self.door_locked = not self.door_locked
            elif event.key == pygame.K_a and self.selected_type == "Door":
                self.door_arcane = not self.door_arcane
            elif event.key == pygame.K_k and self.selected_type == "Door":
                self.door_link = not self.door_link
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS) and self.selected_type == "Door":
                self.door_lock_dc = min(30, self.door_lock_dc + 1)
            elif event.key == pygame.K_MINUS and self.selected_type == "Door":
                self.door_lock_dc = max(1, self.door_lock_dc - 1)
            elif event.key == pygame.K_h:
                # Switch to Halved (0.5) difficulty
                self.difficulty_mult = 0.5
            elif event.key == pygame.K_q:
                # Switch to Quartered (0.25) difficulty
                self.difficulty_mult = 0.25
            elif event.key == pygame.K_DELETE or event.key == pygame.K_BACKSPACE:
                # Delete selected region
                if self.selected_region_idx >= 0:
                    self.terrain_regions.pop(self.selected_region_idx)
                    self.selected_region_idx = -1
            elif event.key == pygame.K_c and self.selected_region_idx >= 0:
                # Change type of selected region to current selected_type
                self.terrain_regions[self.selected_region_idx]["type"] = self.selected_type
                if self.selected_type == "Difficult Terrain":
                    self.terrain_regions[self.selected_region_idx]["multiplier"] = self.difficulty_mult
            elif event.key == pygame.K_z and event.mod & pygame.KMOD_CTRL:
                # Undo last region
                if self.terrain_regions:
                    self.terrain_regions.pop()
                self.selected_region_idx = -1

    def _get_region_at_pos(self, pos):
        """Return the index of the terrain region at the given position, or -1."""
        x, y = pos
        for i, region in enumerate(self.terrain_regions):
            if "x" not in region or "y" not in region:
                continue
            rect = pygame.Rect(region["x"], region["y"], region["width"], region["height"])
            if rect.collidepoint(x, y):
                return i
        return -1

    def _pos_to_cell(self, pos):
        """Convert an editor screen position to a grid Cell (or None).

        The editor blits the map at (0,0) with no scale, so screen px == image px and
        the BattleMap grid-line positions map directly (same assumption the terrain
        selection snapping makes)."""
        import bisect
        if not self.bm or not self.bm.v_line_positions or not self.bm.h_line_positions:
            return None
        x, y = pos
        v = self.bm.v_line_positions
        h = self.bm.h_line_positions
        col = bisect.bisect_right(v, x) - 1
        row = bisect.bisect_right(h, y) - 1
        if 0 <= col < self.bm.grid_cols and 0 <= row < self.bm.grid_rows:
            return rpg.Cell(col, row)
        return None

    MAX_DOOR_WIDTH = 4

    def _door_span_cells(self, start_cell, end_cell):
        """Cells of a door dragged from start_cell to end_cell.

        The span follows the dominant axis (horizontal or vertical) and is clamped to
        MAX_DOOR_WIDTH cells, so a door is at most 4 squares across."""
        if start_cell is None:
            return []
        if end_cell is None:
            end_cell = start_cell
        dcol = end_cell.col - start_cell.col
        drow = end_cell.row - start_cell.row
        if abs(dcol) >= abs(drow):
            step = 1 if dcol >= 0 else -1
            cells = [rpg.Cell(c, start_cell.row)
                     for c in range(start_cell.col, end_cell.col + step, step)]
        else:
            step = 1 if drow >= 0 else -1
            cells = [rpg.Cell(start_cell.col, r)
                     for r in range(start_cell.row, end_cell.row + step, step)]
        return cells[:self.MAX_DOOR_WIDTH]

    def _place_door_span(self, start_cell, end_cell):
        """Place a (possibly wide) door from the current lock settings, or remove an
        existing single-cell door when the drag was just a click on it (toggle)."""
        if start_cell is None or not self.bm:
            return
        cells = self._door_span_cells(start_cell, end_cell)
        if not cells:
            return
        # A single-cell click on an existing door removes it (preserves toggle behaviour).
        if len(cells) == 1:
            di = self.bm.door_at(cells[0])
            if di >= 0:
                self.door_links.pop(door_link_key(self.bm.doors[di].cells), None)
                self.bm.remove_door(self.bm.doors[di].id)
                return
        self.bm.add_door(cells, False, self.door_locked,
                         self.door_lock_dc, self.door_arcane)
        # Cross-map staple: if link mode is on and this door sits on a page edge, target
        # the abutting page's matching global cell (resolved to a page at use time).
        key = door_link_key(cells)
        if self.door_link:
            tgt = self._door_link_target(cells)
            if tgt is not None:
                self.door_links[key] = tgt
            else:
                self.door_links.pop(key, None)
        else:
            self.door_links.pop(key, None)

    def _door_link_target(self, cells):
        """Global ``[X, Y, Z]`` one cell beyond the page edge a door touches, for a
        cross-map staple. Returns None if the door isn't on a page edge (nothing to link
        to). Derived from the active map's origin/z_level (Phase 1 fields), so no manifest
        access is needed here — the target page is resolved at use time. A wide door uses
        its middle cell as the representative crossing point."""
        rep = cells[len(cells) // 2]
        c, r = int(rep.col), int(rep.row)
        ox = int(getattr(self.bm, "origin_col", 0) or 0)
        oy = int(getattr(self.bm, "origin_row", 0) or 0)
        z = int(getattr(self.bm, "z_level", 0) or 0)
        ncols = int(getattr(self.bm, "grid_cols", 0) or 0)
        nrows = int(getattr(self.bm, "grid_rows", 0) or 0)
        if c <= 0:
            return [ox + c - 1, oy + r, z]
        if ncols and c >= ncols - 1:
            return [ox + c + 1, oy + r, z]
        if r <= 0:
            return [ox + c, oy + r - 1, z]
        if nrows and r >= nrows - 1:
            return [ox + c, oy + r + 1, z]
        return None

    def _ladder_index_at(self, col, row):
        """Index of the ladder occupying cell (col, row), or -1."""
        for i, lad in enumerate(self.ladders):
            if any(int(c[0]) == col and int(c[1]) == row for c in lad.get("cells", [])):
                return i
        return -1

    def _place_ladder(self, cell):
        """Place a single-cell ladder at ``cell`` (or remove one already there).

        The target auto-fills to the same GLOBAL (X, Y) one floor up or down, derived
        from the active map's origin/z_level (Phase 1 fields). If the engine predates
        those bindings the global coords fall back to the local cell on z±1."""
        col, row = cell.col, cell.row
        existing = self._ladder_index_at(col, row)
        if existing >= 0:
            self.ladders.pop(existing)   # toggle: click an existing ladder to remove it
            return
        ox = int(getattr(self.bm, "origin_col", 0) or 0)
        oy = int(getattr(self.bm, "origin_row", 0) or 0)
        z = int(getattr(self.bm, "z_level", 0) or 0)
        dz = 1 if self.ladder_up else -1
        self.ladders.append({"cells": [(col, row)],
                             "target": [ox + col, oy + row, z + dz]})

    def _apply_terrain_to_selection(self):
        """Convert screen rect to grid cells and add terrain region, snapped to grid."""
        if not self.selection_rect or not self.map_surf:
            return

        # Snap to grid if BattleMap is available
        x = self.selection_rect.x
        y = self.selection_rect.y
        w = self.selection_rect.w
        h = self.selection_rect.h

        if self.bm and self.bm.v_line_positions and self.bm.h_line_positions:
            # Snap to actual grid lines from BattleMap
            v_lines = self.bm.v_line_positions
            h_lines = self.bm.h_line_positions

            # Find snapped X: grid line at or before x, and after x+w
            snapped_x = 0
            for vline in v_lines:
                if vline <= x:
                    snapped_x = vline
                else:
                    break

            snapped_end_x = snapped_x
            for vline in v_lines:
                if vline >= x + w:
                    snapped_end_x = vline
                    break
                snapped_end_x = vline

            # Find snapped Y: grid line at or before y, and after y+h
            snapped_y = 0
            for hline in h_lines:
                if hline <= y:
                    snapped_y = hline
                else:
                    break

            snapped_end_y = snapped_y
            for hline in h_lines:
                if hline >= y + h:
                    snapped_end_y = hline
                    break
                snapped_end_y = hline

            x = snapped_x
            y = snapped_y
            w = snapped_end_x - snapped_x
            h = snapped_end_y - snapped_y

        # Apply terrain type to actual grid cells in BattleMap
        if self.bm and self.selected_type in self.terrain_type_map:
            terrain_type = self.terrain_type_map[self.selected_type]
            v_lines = self.bm.v_line_positions
            h_lines = self.bm.h_line_positions

            if v_lines and h_lines:
                # Find grid cells within the selection using binary search
                import bisect
                # Find starting column: grid line at or before x
                start_col = max(0, bisect.bisect_right(v_lines, x) - 1)
                # Find ending column: grid line at or after x+w
                end_col = min(self.bm.grid_cols, bisect.bisect_left(v_lines, x + w))

                # Find starting row: grid line at or before y
                start_row = max(0, bisect.bisect_right(h_lines, y) - 1)
                # Find ending row: grid line at or after y+h
                end_row = min(self.bm.grid_rows, bisect.bisect_left(h_lines, y + h))

                # Set terrain type for each cell
                print(f"[TerrainEditor] Setting {self.selected_type} terrain from ({start_col},{start_row}) to ({end_col-1},{end_row-1})")
                for col in range(start_col, end_col):
                    for row in range(start_row, end_row):
                        self.bm.set_terrain_type(rpg.Cell(col, row), terrain_type)
                        # Verify it was set
                        check_type = self.bm.get_terrain_type(rpg.Cell(col, row))
                        print(f"[TerrainEditor] Set terrain at ({col},{row}) to {self.selected_type} (verified: {check_type})")

        region = {
            "type": self.selected_type,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "multiplier": self.difficulty_mult if self.selected_type == "Difficult Terrain" else 0.0
        }
        self.terrain_regions.append(region)

    def draw(self, screen):
        """Draw the terrain editor UI."""
        if not self.active or not self.map_surf:
            return

        # Draw map and overlays
        screen.blit(self.map_surf, (0, 0))

        # Draw terrain overlays
        for i, region in enumerate(self.terrain_regions):
            # Handle both old structure (x,y,width,height) and new structure (cells)
            if "cells" in region:
                # Concentration terrain - skip in editor (only show permanent terrain)
                continue

            # Old structure for permanent terrain
            if "x" not in region or "y" not in region:
                continue
            rect = pygame.Rect(region["x"], region["y"], region["width"], region["height"])
            if region["type"] == "Wall":
                color = (0, 0, 0, 255)           # opaque black
            elif region["type"] == "Chasm":
                color = (128, 128, 128, 255)     # opaque grey
            elif region["type"] == "Water":
                color = (50, 100, 230, 128)      # blue, 50% transparent
            else:  # Difficult Terrain
                color = (139, 90, 43, 128)       # brown, 50% transparent
            s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            s.fill(color)
            screen.blit(s, (rect.x, rect.y))

            # Highlight selected region with border
            if i == self.selected_region_idx:
                pygame.draw.rect(screen, (255, 255, 0), rect, 3)

        # Draw doors (source of truth is BattleMap.doors; editor mutates bm directly)
        if self.bm:
            v = self.bm.v_line_positions
            h = self.bm.h_line_positions
            size = self.bm.cell_pixel_size
            for door in self.bm.doors:
                cols = [c.col for c in door.cells]
                rows = [c.row for c in door.cells]
                if not cols or not v or not h:
                    continue
                min_col, max_col = min(cols), max(cols)
                min_row, max_row = min(rows), max(rows)
                if min_col < len(v) and min_row < len(h):
                    linked = door_link_key(door.cells) in self.door_links
                    draw_door_glyph(screen, v[min_col], h[min_row], size, door, self.font_sm,
                                    w=(max_col - min_col + 1) * size,
                                    h=(max_row - min_row + 1) * size, linked=linked)
            # Draw ladders (Python-only cell objects; editor mutates self.ladders).
            for lad in self.ladders:
                cells = lad.get("cells", [])
                if not cells or not v or not h:
                    continue
                c, r = int(cells[0][0]), int(cells[0][1])
                if c < len(v) and r < len(h):
                    tz = lad.get("target", [0, 0, 0])[2]
                    z_here = int(getattr(self.bm, "z_level", 0) or 0)
                    draw_ladder_glyph(screen, v[c], h[r], size,
                                      going_up=(tz > z_here), font_sm=self.font_sm)
            # Preview the in-progress door span while dragging.
            if self.door_drag_start is not None and self.door_drag_end is not None:
                for cell in self._door_span_cells(self.door_drag_start, self.door_drag_end):
                    c, r = cell.col, cell.row
                    if v and h and c < len(v) and r < len(h):
                        prev = pygame.Surface((size, size), pygame.SRCALPHA)
                        prev.fill((210, 180, 90, 110))
                        screen.blit(prev, (v[c], h[r]))
                        pygame.draw.rect(screen, (210, 180, 90),
                                         pygame.Rect(v[c], h[r], size, size), 2)

        # Draw current selection preview
        if self.selection_rect:
            s = pygame.Surface((self.selection_rect.w, self.selection_rect.h), pygame.SRCALPHA)
            s.fill((200, 200, 200, 80))
            screen.blit(s, (self.selection_rect.x, self.selection_rect.y))
            pygame.draw.rect(screen, (200, 200, 200), self.selection_rect, 2)

        # Draw type selector UI
        sel_texts = [
            f"[1] Wall (black)",
            f"[2] Chasm (grey)",
            f"[3] Water (blue)",
            f"[4] Difficult Terrain (brown)",
            f"[5] Door (click a cell)",
            f"[6] Ladder (click a cell)"
        ]
        y = 10
        for text in sel_texts:
            txt = self.font_sm.render(text, True, (255, 255, 255))
            screen.blit(txt, (10, y))
            y += 18

        # Current type highlight
        current_idx = {"Wall": 0, "Chasm": 1, "Water": 2,
                       "Difficult Terrain": 3, "Door": 4, "Ladder": 5}.get(self.selected_type, 3)
        pygame.draw.rect(screen, (255, 255, 100), pygame.Rect(8, 8 + current_idx*18, 175, 16), 2)

        if self.selected_type == "Ladder":
            dir_str = "UP (z+1)" if self.ladder_up else "DOWN (z-1)"
            lad_surf = self.font_sm.render(f"Ladder travels: {dir_str}", True, (220, 200, 120))
            screen.blit(lad_surf, (10, y + 10))
            keys_surf = self.font_sm.render(
                "[U] toggle up/down  (click places; click again removes)",
                True, (170, 170, 170))
            screen.blit(keys_surf, (10, y + 28))
        elif self.selected_type == "Door":
            # Door placement settings (toggled with keyboard while Door is selected).
            lock_str = "Locked" if self.door_locked else "Unlocked"
            arc_str = " + Arcane Lock" if self.door_arcane else ""
            link_str = "  + Link→neighbor" if self.door_link else ""
            door_text = f"Door: [{lock_str}{arc_str}]  DC {self.door_lock_dc}{link_str}"
            door_surf = self.font_sm.render(door_text, True, (220, 200, 120))
            screen.blit(door_surf, (10, y + 10))
            keys_surf = self.font_sm.render(
                "[L] lock  [A] arcane  [K] link  [+/-] DC  (click toggles; drag for a wide door, max 4)",
                True, (170, 170, 170))
            screen.blit(keys_surf, (10, y + 28))
        else:
            # Difficulty multiplier indicator
            diff_text = f"Difficulty: {'[H]alved (0.5)' if self.difficulty_mult == 0.5 else '[Q]uartered (0.25)'}"
            diff_surf = self.font_sm.render(diff_text, True, (200, 200, 200))
            screen.blit(diff_surf, (10, y + 10))

        # Instructions
        if self.selected_region_idx >= 0:
            inst_texts = [
                "[DEL] Delete | [C] Change Type | [Right Click] Deselect",
                "[ESC] Save & Close | [Ctrl+Z] Undo"
            ]
        else:
            inst_texts = [
                "Click terrain to select, [ESC] Save & Close, [Ctrl+Z] Undo",
            ]
        y_inst = screen.get_height() - 25 - len(inst_texts) * 20
        for text in inst_texts:
            inst = self.font_sm.render(text, True, (180, 180, 180))
            screen.blit(inst, (10, y_inst))
            y_inst += 20


# ─────────────────────────────────────────────────────────────────────────────
#  Main application
# ─────────────────────────────────────────────────────────────────────────────
