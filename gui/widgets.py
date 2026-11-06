# ─────────────────────────────────────────────────────────────────────────────
#  widgets.py  –  Reusable pygame UI widgets
# ─────────────────────────────────────────────────────────────────────────────

import re
import pygame
from constants import (
    COL_BTN, COL_BTN_HOVER, COL_PANEL_BORDER, COL_TEXT, COL_LABEL,
    COL_INPUT_BG, COL_INPUT_ACTIVE
)


# ── single-line text editing (shared by every typed field) ────────────────────
# The system clipboard goes through pygame.scrap (SDL's clipboard, which x11vnc syncs to
# the noVNC client). If scrap is unavailable — headless tests, no display yet — copy and
# paste still work inside the app through this fallback.
_clipboard_fallback = ""
# pygame 2 on SDL2 publishes the text clipboard under this type; pygame.SCRAP_TEXT
# ("text/plain") reads back None there, which silently left paste on the fallback.
_SCRAP_UTF8 = "text/plain;charset=utf-8"
_INT_TEXT = re.compile(r"-?\d*")   # what an integer field may hold mid-edit


def clipboard_get() -> str:
    try:
        import pygame.scrap as scrap
        if not scrap.get_init():
            scrap.init()
        for kind in (_SCRAP_UTF8, pygame.SCRAP_TEXT):
            raw = scrap.get(kind)
            if raw:
                return raw.decode("utf-8", "ignore").replace("\x00", "")
    except Exception:
        pass
    return _clipboard_fallback


def clipboard_put(text: str):
    global _clipboard_fallback
    _clipboard_fallback = text
    try:
        import pygame.scrap as scrap
        if not scrap.get_init():
            scrap.init()
        scrap.put(_SCRAP_UTF8, text.encode("utf-8"))
    except Exception:
        pass


def edit_line(text: str, caret, event, accept=None):
    """Apply one KEYDOWN to a single-line field with a caret.

    ``caret`` is an index into ``text`` (None means the end). ← / → move it, Home / End
    jump, Backspace / Delete erase around it, typed characters insert at it, and
    Ctrl/Cmd+C copies the field, Ctrl/Cmd+X cuts it, Ctrl/Cmd+V pastes at the caret.
    ``accept(new_text)`` may veto an edit (e.g. digits only). Returns
    ``(text, caret, handled)``; Enter, Esc and Tab are left to the caller."""
    n = len(text)
    c = n if caret is None else max(0, min(n, caret))
    if event.type != pygame.KEYDOWN:
        return text, c, False
    k = event.key
    if event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META):
        if k == pygame.K_c:
            clipboard_put(text)
            return text, c, True
        if k == pygame.K_x:
            if accept is None or accept(""):
                clipboard_put(text)
                return "", 0, True
            return text, c, True
        if k == pygame.K_v:
            ins = "".join(ch for ch in clipboard_get().replace("\n", " ").replace("\t", " ")
                          if ch.isprintable())
            new = text[:c] + ins + text[c:]
            if ins and (accept is None or accept(new)):
                return new, c + len(ins), True
            return text, c, True
        return text, c, k not in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_TAB)
    if k == pygame.K_LEFT:
        return text, max(0, c - 1), True
    if k == pygame.K_RIGHT:
        return text, min(n, c + 1), True
    if k == pygame.K_HOME:
        return text, 0, True
    if k == pygame.K_END:
        return text, n, True
    if k == pygame.K_BACKSPACE:
        new = text[:c - 1] + text[c:] if c else text
        if c and (accept is None or accept(new)):
            return new, c - 1, True
        return text, c, True
    if k == pygame.K_DELETE:
        new = text[:c] + text[c + 1:]
        if c < n and (accept is None or accept(new)):
            return new, c, True
        return text, c, True
    if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
        return text, c, False
    ch = event.unicode
    if ch and ch.isprintable():
        new = text[:c] + ch + text[c:]
        if accept is None or accept(new):
            return new, c + len(ch), True
        return text, c, True
    return text, c, False


def caret_x(font, text: str, caret, x0: int) -> int:
    """Screen x of the caret for ``text`` drawn starting at ``x0``."""
    c = len(text) if caret is None else max(0, min(len(text), caret))
    return x0 + font.size(text[:c])[0] + 1


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
        self.caret       = None   # index into text; None = end

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            was = self.active
            self.active = self.rect.collidepoint(event.pos)
            if self.active and not was:
                self.caret = None
        if self.active and event.type == pygame.KEYDOWN:
            self.text, self.caret, _ = edit_line(self.text, self.caret, event)

    def draw(self, surf: pygame.Surface):
        bg = COL_INPUT_ACTIVE if self.active else COL_INPUT_BG
        pygame.draw.rect(surf, bg, self.rect, border_radius=3)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.rect, 1, border_radius=3)
        display = self.text or self.placeholder
        color   = COL_TEXT if self.text else COL_LABEL
        txt = self.font.render(display, True, color)
        surf.blit(txt, (self.rect.x + 6, self.rect.centery - txt.get_height() // 2))
        if self.active:  # caret
            cx = caret_x(self.font, self.text, self.caret, self.rect.x + 6)
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
        self._caret      = None         # caret index into _raw; None = end
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
                self._caret = None
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
            else:
                self._raw, self._caret, _ = edit_line(
                    self._raw, self._caret, event, accept=_INT_TEXT.fullmatch)

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
            cx = caret_x(self.font, self._raw, self._caret,
                         self.field.x + (self.field.w - vt.get_width()) // 2) + 1
            pygame.draw.line(surf, COL_TEXT,
                             (cx, self.field.y + 4),
                             (cx, self.field.bottom - 4))


class IntSlider:
    """
    A horizontal slider over discrete integer stops ``lo``..``hi``: click a stop or drag
    the knob, and ← / → step it while ``focused``. ``label(v)`` names the value drawn to
    the right of the track (default: the number). Same interface as IntStepper
    (``value``, ``handle``, ``draw``); ``handle`` returns True when the value changed.
    """
    KNOB_R  = 8
    LABEL_W = 64   # room at the right of the rect for the value label

    def __init__(self, rect: pygame.Rect, value: int, lo: int, hi: int, font=None,
                 label=None):
        self.rect        = rect
        self.lo, self.hi = lo, hi
        self.font        = font
        self.label       = label or str
        self.focused     = True
        self._dragging   = False
        self._value      = max(lo, min(hi, int(value)))
        self.track = pygame.Rect(rect.x + self.KNOB_R, rect.y,
                                 rect.w - self.LABEL_W - 2 * self.KNOB_R, rect.h)

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, v: int):
        self._value = max(self.lo, min(self.hi, int(v)))

    def stop_x(self, v: int) -> int:
        """Screen x of stop ``v`` on the track."""
        span = max(1, self.hi - self.lo)
        return self.track.x + round(self.track.w * (v - self.lo) / span)

    def _value_at(self, x: int) -> int:
        span = max(1, self.hi - self.lo)
        frac = (x - self.track.x) / max(1, self.track.w)
        return max(self.lo, min(self.hi, self.lo + round(frac * span)))

    def _hit(self, pos) -> bool:
        grab = self.track.inflate(2 * self.KNOB_R, 0)
        return grab.collidepoint(pos)

    def handle(self, event) -> bool:
        before = self._value
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self._hit(event.pos):
            self._dragging = True
            self.value = self._value_at(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            self.value = self._value_at(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        elif event.type == pygame.KEYDOWN and self.focused:
            if event.key == pygame.K_LEFT:
                self.value = self._value - 1
            elif event.key == pygame.K_RIGHT:
                self.value = self._value + 1
        return self._value != before

    def draw(self, surf: pygame.Surface):
        cy = self.rect.centery
        pygame.draw.line(surf, COL_PANEL_BORDER, (self.track.x, cy), (self.track.right, cy), 4)
        for v in range(self.lo, self.hi + 1):
            x = self.stop_x(v)
            pygame.draw.line(surf, COL_LABEL, (x, cy - 5), (x, cy + 5), 1)
        kx = self.stop_x(self._value)
        pygame.draw.line(surf, COL_TEXT, (self.track.x, cy), (kx, cy), 4)
        pygame.draw.circle(surf, COL_BTN_HOVER if self._dragging else COL_TEXT, (kx, cy),
                           self.KNOB_R)
        pygame.draw.circle(surf, COL_PANEL_BORDER, (kx, cy), self.KNOB_R, 1)
        t = self.font.render(self.label(self._value), True, COL_TEXT)
        surf.blit(t, t.get_rect(midleft=(self.track.right + self.KNOB_R + 8, cy)))
