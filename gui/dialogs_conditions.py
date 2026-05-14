"""Simple dialog to show agent conditions."""

import pygame
from constants import *

class ConditionsDialog:
    """Modal dialog showing an agent's active conditions."""
    DLG_W = 400
    DLG_H = 300
    PAD = 12
    LINE_H = 24

    C_BG = (24, 24, 36)
    C_BORDER = (80, 80, 120)
    C_LABEL = (160, 200, 255)
    C_TEXT = (210, 210, 210)
    C_CONDITION = (200, 150, 100)
    C_BUTTON = (60, 80, 120)
    C_BUTTON_H = (80, 100, 150)

    def __init__(self, font_sm, font_md, font_lg):
        self.font_sm = font_sm
        self.font_md = font_md
        self.font_lg = font_lg
        self.active = False
        self.rect = None
        self.agent_name = ""
        self.conditions = {}
        self._close_btn_rect = None

    def open(self, agent_name: str, conditions):
        """Open the dialog with agent conditions."""
        self.agent_name = agent_name
        self.conditions = conditions
        self.active = True

        # Center the dialog on screen
        sw, sh = pygame.display.get_surface().get_size()
        self.rect = pygame.Rect((sw - self.DLG_W) // 2, (sh - self.DLG_H) // 2,
                                self.DLG_W, self.DLG_H)
        self._close_btn_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)

    def close(self):
        """Close the dialog."""
        self.active = False
        self.rect = None
        self.conditions = {}

    def handle(self, event):
        """Handle input events. Returns True if consumed."""
        if not self.active or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._close_btn_rect and self._close_btn_rect.collidepoint(event.pos):
                self.close()
                return True
            # Close on click outside
            if not self.rect.collidepoint(event.pos):
                self.close()
                return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True

        return False

    def draw(self, surf):
        """Draw the dialog."""
        if not self.active or not self.rect:
            return

        # Background
        pygame.draw.rect(surf, self.C_BG, self.rect, border_radius=8)
        pygame.draw.rect(surf, self.C_BORDER, self.rect, 2, border_radius=8)

        # Title
        title = self.font_md.render(f"{self.agent_name} - Conditions", True, self.C_LABEL)
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 10)
        surf.blit(title, title_rect)

        # Close button
        pygame.draw.rect(surf, self.C_BUTTON, self._close_btn_rect)
        close_text = self.font_sm.render("✕", True, (220, 220, 220))
        surf.blit(close_text, close_text.get_rect(center=self._close_btn_rect.center))

        # Conditions list
        y = self.rect.y + 50
        max_y = self.rect.bottom - self.PAD

        if not self.conditions or not any(self.conditions.values()):
            no_cond = self.font_sm.render("No active conditions", True, (100, 100, 120))
            surf.blit(no_cond, (self.rect.x + self.PAD, y))
        else:
            # Format condition names nicely
            condition_names = []
            cond_dict = self.conditions

            # Check various conditions
            if cond_dict.blinded:
                condition_names.append("Blinded")
            if cond_dict.charmed:
                condition_names.append("Charmed")
            if cond_dict.deafened:
                condition_names.append("Deafened")
            if cond_dict.exhaustion > 0:
                condition_names.append(f"Exhaustion (level {cond_dict.exhaustion})")
            if cond_dict.frightened:
                condition_names.append("Frightened")
            if cond_dict.grappled:
                condition_names.append("Grappled")
            if cond_dict.incapacitated:
                condition_names.append("Incapacitated")
            if cond_dict.invisible:
                condition_names.append("Invisible")
            if cond_dict.paralyzed:
                condition_names.append("Paralyzed")
            if cond_dict.petrified:
                condition_names.append("Petrified")
            if cond_dict.poisoned:
                condition_names.append("Poisoned")
            if cond_dict.prone:
                condition_names.append("Prone")
            if cond_dict.restrained:
                condition_names.append("Restrained")
            if cond_dict.stunned:
                condition_names.append("Stunned")
            if cond_dict.unconscious:
                condition_names.append("Unconscious")

            if condition_names:
                for cond_name in condition_names:
                    if y > max_y:
                        break
                    cond_text = self.font_sm.render(f"• {cond_name}", True, self.C_CONDITION)
                    surf.blit(cond_text, (self.rect.x + self.PAD + 10, y))
                    y += self.LINE_H
            else:
                no_cond = self.font_sm.render("No active conditions", True, (100, 100, 120))
                surf.blit(no_cond, (self.rect.x + self.PAD, y))
