"""Simple dialog to show agent conditions."""

import pygame
from constants import *

class ConditionsDialog:
    """Modal dialog showing an agent's active conditions with exhaustion controls."""
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
        self._exh_slider_rect = None
        self.agent_idx = None

    def open(self, agent_name: str, conditions, agent_idx=None):
        """Open the dialog with agent conditions."""
        print(f"[ConditionsDialog.open] Opening for {agent_name} (idx={agent_idx}), exhaustion_level={conditions.exhaustion_level if conditions else 'None'}")
        self.agent_name = agent_name
        self.conditions = conditions
        self.agent_idx = agent_idx
        self.active = True

        # Center the dialog on screen
        sw, sh = pygame.display.get_surface().get_size()
        self.rect = pygame.Rect((sw - self.DLG_W) // 2, (sh - self.DLG_H) // 2,
                                self.DLG_W, self.DLG_H)
        self._close_btn_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)
        print(f"[ConditionsDialog.open] Dialog rect: {self.rect}, slider will be at y={self.rect.y + 50}")

    def close(self):
        """Close the dialog. Conditions are kept until main.py processes them."""
        self.active = False
        self.rect = None
        # Keep agent_idx and conditions until main.py has processed them

    def handle(self, event):
        """Handle input events. Returns True if consumed."""
        if not self.active or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._close_btn_rect and self._close_btn_rect.collidepoint(event.pos):
                print(f"[ConditionsDialog] Close button clicked")
                self.close()
                return True
            # Exhaustion slider click
            if self._exh_slider_rect and self._exh_slider_rect.collidepoint(event.pos):
                # Calculate exhaustion level from click position on slider
                rel_x = event.pos[0] - self._exh_slider_rect.x
                level = min(6, max(0, int((rel_x / self._exh_slider_rect.width) * 6)))
                print(f"[ConditionsDialog] Exhaustion slider clicked: rel_x={rel_x}, slider_width={self._exh_slider_rect.width}, new_level={level}")
                self.conditions.exhaustion_level = level
                print(f"[ConditionsDialog] Exhaustion set to {self.conditions.exhaustion_level}")
                return True
            # Close on click outside
            if not self.rect.collidepoint(event.pos):
                print(f"[ConditionsDialog] Clicked outside dialog, closing")
                self.close()
                return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            print(f"[ConditionsDialog] ESC pressed, closing")
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

        # Exhaustion slider (always shown)
        lx = self.rect.x + self.PAD
        w = self.DLG_W - self.PAD * 2
        y = self.rect.y + 50

        exh_label = self.font_sm.render("Exhaustion:", True, self.C_LABEL)
        surf.blit(exh_label, (lx, y))
        y += 16

        # Draw slider track
        slider_w = w - 30  # Leave room for level display
        slider_h = 20
        self._exh_slider_rect = pygame.Rect(lx, y, slider_w, slider_h)
        pygame.draw.rect(surf, (40, 40, 60), self._exh_slider_rect, border_radius=3)
        pygame.draw.rect(surf, (80, 80, 120), self._exh_slider_rect, 1, border_radius=3)

        # Draw filled portion based on exhaustion level
        if self.conditions and self.conditions.exhaustion_level > 0:
            filled_w = int(slider_w * (self.conditions.exhaustion_level / 6))
            pygame.draw.rect(surf, (200, 100, 50), pygame.Rect(lx, y, filled_w, slider_h), border_radius=3)

        # Draw level labels (0-6)
        for i in range(7):
            label_x = lx + int(slider_w * (i / 6)) - 4
            label_surf = self.font_sm.render(str(i), True, (150, 150, 150))
            surf.blit(label_surf, (label_x, y + slider_h + 2))

        # Current level display
        level_text = self.font_sm.render(f"L{self.conditions.exhaustion_level if self.conditions else 0}", True, self.C_TEXT)
        surf.blit(level_text, (lx + slider_w + 4, y + 2))

        y += slider_h + 24
        max_y = self.rect.bottom - self.PAD

        # Check if there are any other active conditions
        has_other_conditions = False
        if self.conditions:
            cond_dict = self.conditions
            has_other_conditions = (cond_dict.blinded or cond_dict.charmed or cond_dict.deafened or
                                   cond_dict.frightened or cond_dict.grappled or
                                   cond_dict.incapacitated or cond_dict.invisible or cond_dict.paralyzed or
                                   cond_dict.petrified or cond_dict.poisoned or cond_dict.prone or
                                   cond_dict.restrained or cond_dict.stunned or cond_dict.unconscious)

        if not has_other_conditions:
            no_cond = self.font_sm.render("No other active conditions", True, (100, 100, 120))
            surf.blit(no_cond, (self.rect.x + self.PAD, y))
        else:
            # Format condition names nicely
            condition_names = []
            cond_dict = self.conditions

            # Check various conditions (exhaustion handled by slider above)
            if cond_dict.blinded:
                condition_names.append("Blinded")
            if cond_dict.charmed:
                condition_names.append("Charmed")
            if cond_dict.deafened:
                condition_names.append("Deafened")
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
