# ─────────────────────────────────────────────────────────────────────────────
#  terrain_dialogs.py  –  Terrain editing dialogs
# ─────────────────────────────────────────────────────────────────────────────

import pygame
import rpg_battle_map as rpg
from constants import *
from widgets import Button

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
        # Mapping from terrain type names to rpg.TerrainType enum values
        self.terrain_type_map = {
            "Standard": rpg.TerrainType.Standard,
            "Water": rpg.TerrainType.Water,
            "Wall": rpg.TerrainType.Wall,
            "Chasm": rpg.TerrainType.Chasm,
        }

    def open(self, map_surf, terrain_regions, bm=None):
        """Open the terrain editor with existing terrain data."""
        self.active = True
        self.map_surf = map_surf
        self.terrain_regions = [r.copy() for r in terrain_regions] if terrain_regions else []
        self.selection_start = None
        self.selection_rect = None
        self.bm = bm

    def close(self):
        """Close the terrain editor."""
        self.active = False

    def handle(self, event):
        """Handle mouse/keyboard events."""
        if not self.active:
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
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
            if self.selection_start and self.selected_region_idx < 0:
                x0, y0 = self.selection_start
                x1, y1 = event.pos
                self.selection_rect = pygame.Rect(
                    min(x0, x1), min(y0, y1),
                    abs(x1 - x0), abs(y1 - y0)
                )

        elif event.type == pygame.MOUSEBUTTONUP:
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
                color = (0, 0, 0, 255)
            elif region["type"] == "Chasm":
                color = (140, 140, 140, 180)
            elif region["type"] == "Water":
                color = (100, 150, 255, 255)
            else:  # Difficult Terrain
                color = (255, 200, 100, 128)
            s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            s.fill(color)
            screen.blit(s, (rect.x, rect.y))

            # Highlight selected region with border
            if i == self.selected_region_idx:
                pygame.draw.rect(screen, (255, 255, 0), rect, 3)

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
            f"[4] Difficult Terrain (orange)"
        ]
        y = 10
        for text in sel_texts:
            txt = self.font_sm.render(text, True, (255, 255, 255))
            screen.blit(txt, (10, y))
            y += 18

        # Current type highlight
        current_idx = {"Wall": 0, "Chasm": 1, "Water": 2, "Difficult Terrain": 3}.get(self.selected_type, 3)
        pygame.draw.rect(screen, (255, 255, 100), pygame.Rect(8, 8 + current_idx*18, 160, 16), 2)

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
