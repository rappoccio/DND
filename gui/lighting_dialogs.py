# ─────────────────────────────────────────────────────────────────────────────
#  lighting_dialogs.py  –  Lighting editor dialog
# ─────────────────────────────────────────────────────────────────────────────

import pygame
import rpg_battle_map as rpg
from constants import *
from widgets import Button

class LightingEditorDialog:
    """Modal dialog for editing light sources on the map."""

    def __init__(self, font_sm, font_md):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.map_surf = None
        self.bm = None
        self.app = None

        # Lighting configuration
        self.default_light = rpg.VisibilityLevel.Dark
        self.light_sources = []  # list of {"name": str, "level": VisibilityLevel, "cells": [...]}
        self.selected_source_idx = -1
        self.placing_light = False
        self.pending_light_level = rpg.VisibilityLevel.Sunlight  # Default to Sunlight
        self.light_level_choices = [
            (rpg.VisibilityLevel.Clear, "Clear/BrightLight"),
            (rpg.VisibilityLevel.Dim, "Dim Light"),
            (rpg.VisibilityLevel.Dark, "Dark"),
            (rpg.VisibilityLevel.MagicalDark, "Magical Darkness"),
            (rpg.VisibilityLevel.Sunlight, "Sunlight"),
        ]
        self.show_overlay = True  # Toggle for lighting visualization

        # UI elements
        self.buttons = {}
        self._init_buttons()

    def _init_buttons(self):
        """Initialize dialog buttons."""
        self.buttons['add'] = Button(pygame.Rect(10, 10, 100, 30), "Add Light", font=self.font_sm)
        self.buttons['remove'] = Button(pygame.Rect(120, 10, 80, 30), "Remove", font=self.font_sm)
        self.buttons['cycle_level'] = Button(pygame.Rect(10, 50, 190, 30), "Light Level: Sunlight", font=self.font_sm)
        self.buttons['done'] = Button(pygame.Rect(10, 90, 100, 30), "Done", font=self.font_sm)
        self.buttons['cancel'] = Button(pygame.Rect(120, 90, 80, 30), "Cancel", font=self.font_sm)

    def open(self, map_surf, bm, app, light_sources):
        """Open the dialog for editing lighting."""
        self.active = True
        self.map_surf = map_surf
        self.bm = bm
        self.app = app
        self.light_sources = [s.copy() for s in light_sources]  # Deep copy
        self.selected_source_idx = -1
        self.placing_light = False
        self.pending_light_pos = None

    def close(self):
        """Close the dialog without saving."""
        self.active = False

    def handle(self, event):
        """Handle mouse/keyboard events."""
        if not self.active:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                # Check buttons first
                for name, btn in self.buttons.items():
                    if btn.rect.collidepoint(event.pos):
                        self._handle_button(name)
                        return True

                # If placing a light, record the position
                if self.placing_light:
                    cell = self.app._screen_to_cell(event.pos[0], event.pos[1]) if self.app else None
                    if cell and cell.col >= 0 and cell.row >= 0:
                        col, row = cell.col, cell.row
                        # Convert grid to pixel coords (approximate center of cell)
                        h_lines = self.bm.h_line_positions
                        v_lines = self.bm.v_line_positions
                        if col < len(v_lines) - 1 and row < len(h_lines) - 1:
                            px = (v_lines[col] + v_lines[col + 1]) // 2
                            py = (h_lines[row] + h_lines[row + 1]) // 2

                            # Show simple input dialog for light properties
                            self._add_light_at(px, py)
                            self.placing_light = False
                            return True

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True
            elif event.key == pygame.K_t:  # 'T' to toggle overlay visibility
                self.show_overlay = not self.show_overlay
                return True

        return False

    def _handle_button(self, button_name):
        """Handle button presses."""
        if button_name == 'add':
            self.placing_light = True
        elif button_name == 'remove':
            if self.selected_source_idx >= 0:
                self.light_sources.pop(self.selected_source_idx)
                self.selected_source_idx = -1
        elif button_name == 'cycle_level':
            # Cycle through light levels
            current_idx = next((i for i, (lvl, _) in enumerate(self.light_level_choices)
                               if lvl == self.pending_light_level), 4)  # Default to Sunlight (idx 4)
            next_idx = (current_idx + 1) % len(self.light_level_choices)
            self.pending_light_level, _ = self.light_level_choices[next_idx]
            self._update_level_button()
        elif button_name == 'done':
            self.active = False
            if self.app:
                self.app._apply_light_effects(self.light_sources)
        elif button_name == 'cancel':
            self.close()

    def _update_level_button(self):
        """Update the level button text."""
        level_name = next((name for lvl, name in self.light_level_choices
                          if lvl == self.pending_light_level), "Unknown")
        self.buttons['cycle_level'].text = f"Light Level: {level_name}"

    def _add_light_at(self, px, py):
        """Add a light source at the given pixel coordinates."""
        light = {
            "name": f"Light {len(self.light_sources) + 1}",
            "level": self.pending_light_level,
            "x": px,
            "y": py,
            "radius": 5  # Default 5-cell radius for editor-placed lights
        }
        self.light_sources.append(light)

    def draw(self, screen):
        """Draw the dialog UI."""
        if not self.active:
            return

        # Draw semi-transparent overlay
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 100))
        screen.blit(overlay, (0, 0))

        # Draw instruction text
        if self.placing_light:
            text = self.font_md.render("Click on map to place light source", True, (255, 255, 0))
            screen.blit(text, (200, 100))
        else:
            text = self.font_md.render("Lighting Editor", True, (255, 255, 255))
            screen.blit(text, (200, 50))

            # Show toggle status
            toggle_color = (100, 255, 100) if self.show_overlay else (255, 100, 100)
            toggle_text = "ON" if self.show_overlay else "OFF"
            text = self.font_sm.render(f"Lighting Overlay: {toggle_text} (Press T to toggle)", True, toggle_color)
            screen.blit(text, (200, 85))

            # Draw list of light sources
            y = 130
            for i, light in enumerate(self.light_sources):
                color = (255, 255, 0) if i == self.selected_source_idx else (200, 200, 200)
                level_name = next((name for lvl, name in self.light_level_choices
                                  if lvl == light.get("level", rpg.VisibilityLevel.Sunlight)), "Unknown")
                text = self.font_sm.render(
                    f"{light['name']}: {level_name} (r:{light.get('radius', 5)})",
                    True, color
                )
                text_rect = screen.blit(text, (220, y))
                if text_rect.collidepoint(pygame.mouse.get_pos()):
                    self.selected_source_idx = i
                y += 25

        # Draw buttons
        for btn in self.buttons.values():
            btn.draw(screen)
