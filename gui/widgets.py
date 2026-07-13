# ─────────────────────────────────────────────────────────────────────────────
#  widgets.py  –  Reusable pygame UI widgets
# ─────────────────────────────────────────────────────────────────────────────

import pygame
from constants import (
    COL_BTN, COL_BTN_HOVER, COL_PANEL_BORDER, COL_TEXT, COL_LABEL,
    COL_INPUT_BG, COL_INPUT_ACTIVE
)


class Button:
    def __init__(self, rect: pygame.Rect, label: str, color=COL_BTN,
                 hover_color=COL_BTN_HOVER, font=None):
        self.rect   = rect
        self.text   = label  # renamed from label to match usage in main.py
        self.label  = label  # keep for compatibility
        self.color  = color
        self.hcolor = hover_color
        self.font   = font

    def draw(self, surf: pygame.Surface):
        hovered = self.rect.collidepoint(pygame.mouse.get_pos())
        col = self.hcolor if hovered else self.color
        pygame.draw.rect(surf, col, self.rect, border_radius=4)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.rect, 1, border_radius=4)
        txt = self.font.render(self.text, True, COL_TEXT)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def clicked(self, event) -> bool:
        return (event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and self.rect.collidepoint(event.pos))


class TextInput:
    def __init__(self, rect: pygame.Rect, placeholder: str = "", font=None):
        self.rect        = rect
        self.placeholder = placeholder
        self.font        = font
        self.text        = ""
        self.active      = False

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key not in (pygame.K_RETURN, pygame.K_TAB):
                self.text += event.unicode

    def draw(self, surf: pygame.Surface):
        bg = COL_INPUT_ACTIVE if self.active else COL_INPUT_BG
        pygame.draw.rect(surf, bg, self.rect, border_radius=3)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.rect, 1, border_radius=3)
        display = self.text or self.placeholder
        color   = COL_TEXT if self.text else COL_LABEL
        txt = self.font.render(display, True, color)
        surf.blit(txt, (self.rect.x + 6, self.rect.centery - txt.get_height() // 2))
        if self.active:  # caret
            cx = self.rect.x + 6 + self.font.size(self.text)[0] + 1
            pygame.draw.line(surf, COL_TEXT,
                             (cx, self.rect.y+4), (cx, self.rect.bottom-4))


class IntStepper:
    """
    Integer input: click the centre field to type a number directly,
    or use the − / + buttons on either side to nudge by 1.
    The public interface (self.value, handle, draw) is unchanged so
    StatsDialog and any other caller needs no modifications.
    """
    BW = 24   # width of each nudge button

    def __init__(self, rect: pygame.Rect, value: int, lo: int, hi: int, font=None):
        self.rect        = rect
        self.lo, self.hi = lo, hi
        self.font        = font
        self._active     = False   # True while the text field has keyboard focus
        self._raw        = str(value)   # what the user has typed so far
        # Last committed number. A field cleared for typing holds no number of its own; it
        # reads back as this rather than as `lo`, so clearing a field and clicking away
        # can't silently snap it to the minimum.
        self._last       = max(lo, min(hi, value))

        bw = self.BW
        self.btn_dec  = pygame.Rect(rect.x,          rect.y, bw, rect.h)
        self.btn_inc  = pygame.Rect(rect.right - bw, rect.y, bw, rect.h)
        self.field    = pygame.Rect(rect.x + bw, rect.y,
                                    rect.w - bw * 2, rect.h)

    # ── committed integer value ───────────────────────────────────────────────
    @property
    def value(self) -> int:
        try:
            return max(self.lo, min(self.hi, int(self._raw)))
        except ValueError:
            return self._last

    @value.setter
    def value(self, v: int):
        self._last = max(self.lo, min(self.hi, v))
        self._raw  = str(self._last)

    # ── event handling ────────────────────────────────────────────────────────
    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.btn_dec.collidepoint(event.pos):
                self.value = self.value - 1
                self._active = False
            elif self.btn_inc.collidepoint(event.pos):
                self.value = self.value + 1
                self._active = False
            elif self.field.collidepoint(event.pos):
                self._active = True
                self._raw = ""   # clear so the user can type fresh
            else:
                self._commit()
                self._active = False

        if self._active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self._commit()
                self._active = False
            elif event.key == pygame.K_ESCAPE:
                self._raw    = str(self.value)   # revert
                self._active = False
            elif event.key == pygame.K_BACKSPACE:
                self._raw = self._raw[:-1]
            elif event.unicode.lstrip('-').isdigit() or \
                 (event.unicode == '-' and not self._raw):
                self._raw += event.unicode

    def _commit(self):
        """Clamp whatever the user typed and store it (an empty field keeps its last
        committed value rather than collapsing to `lo`)."""
        self._last = self.value       # value property already clamps / falls back
        self._raw  = str(self._last)

    # ── drawing ───────────────────────────────────────────────────────────────
    def draw(self, surf: pygame.Surface):
        mouse = pygame.mouse.get_pos()

        # Nudge buttons
        for btn, lbl in ((self.btn_dec, "−"), (self.btn_inc, "+")):
            hov = btn.collidepoint(mouse)
            pygame.draw.rect(surf, COL_BTN_HOVER if hov else COL_BTN,
                             btn, border_radius=3)
            t = self.font.render(lbl, True, COL_TEXT)
            surf.blit(t, t.get_rect(center=btn.center))

        # Text field
        field_col = COL_INPUT_ACTIVE if self._active else COL_INPUT_BG
        pygame.draw.rect(surf, field_col, self.field, border_radius=3)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.field, 1, border_radius=3)

        display = self._raw if self._active else str(self.value)
        vt = self.font.render(display, True, COL_TEXT)
        surf.blit(vt, vt.get_rect(center=self.field.center))

        # Blinking caret when active
        if self._active:
            cx = self.field.x + (self.field.w - vt.get_width()) // 2 \
                 + vt.get_width() + 2
            pygame.draw.line(surf, COL_TEXT,
                             (cx, self.field.y + 4),
                             (cx, self.field.bottom - 4))
