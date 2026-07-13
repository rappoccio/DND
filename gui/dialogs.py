# ─────────────────────────────────────────────────────────────────────────────
#  dialogs.py  –  Self-contained modal dialogs
# ─────────────────────────────────────────────────────────────────────────────

import os
import pygame
import rpg_battle_map as rpg
from constants import *
from widgets import Button, TextInput, IntStepper
from helpers import _dnd_mod, _mod_str, _calculate_total_ac

class FileBrowser:
    """
    A general-purpose in-pygame file browser modal.

    open(start_dir, callback, ...)  – show the dialog.

    Modes
    -----
    save_mode=False (default / load):
        Shows only files whose extension is in `extensions`.
        Clicking a file calls callback(path) and closes.

    save_mode=True:
        Shows folders and files matching `extensions`.
        Clicking a file copies its name into the filename input.
        A "Save" button confirms; callback(path) receives the full path.
    """

    DLG_W   = 580
    ITEM_H  = 22
    HDR_H   = 36
    BTN_H   = 32
    FNAME_H = 30    # height of the filename-input row (save mode)
    PAD     = 10
    SB_W    = 10

    C_BG      = (24,  24,  36)
    C_BORDER  = (80,  80, 120)
    C_HDR     = (36,  36,  58)
    C_LIST    = (18,  18,  28)
    C_DIR     = (120, 170, 255)
    C_FILE    = (210, 210, 210)
    C_HOVER   = (55,  75, 120)
    C_SB_TR   = (35,  35,  50)
    C_SB_TH   = (90,  90, 120)
    C_PATH    = (140, 140, 175)
    C_CANCEL  = (90,  40,  40)
    C_CANCEL_H= (120, 55,  55)
    C_SAVE    = (40,  90,  50)
    C_SAVE_H  = (55, 120,  70)
    C_FN_BG   = (30,  30,  46)
    C_FN_ACT  = (45,  45,  70)

    def __init__(self, font_sm, font_md, font_lg):
        self.font_sm   = font_sm
        self.font_md   = font_md
        self.font_lg   = font_lg
        self.active    = False
        self.cwd       = "/"
        self.entries: list[str]             = []
        self._raw:    list[tuple[str,bool]] = []   # (real_name, is_dir)
        self.scroll    = 0
        self._hover    = -1
        self._cb       = None
        # mode state
        self.save_mode  = False
        self.extensions = IMAGE_EXTS
        self.name_pattern = ""
        self._title     = ""
        self._filename  = ""     # editable in save mode
        self._fn_active = False  # filename input focused

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, start_dir: str, callback, *,
             save_mode: bool = False,
             extensions=None,
             default_filename: str = "",
             name_pattern: str = ""):
        if not os.path.isdir(start_dir):
            start_dir = os.path.dirname(start_dir) or "/"
        self.cwd        = os.path.abspath(start_dir)
        self._cb        = callback
        self.active     = True
        self.save_mode  = save_mode
        self.extensions = extensions if extensions is not None else (
            JSON_EXTS if save_mode else IMAGE_EXTS)
        self.name_pattern = name_pattern
        self._title     = "Save Layout As" if save_mode else "Open Layout / Select Sprite"
        self._filename  = default_filename
        self._fn_active = save_mode   # auto-focus filename in save mode
        self.scroll     = 0
        self._hover     = -1
        self._load()

    # ── internals ────────────────────────────────────────────────────────────
    def _load(self):
        entries, raw = [], []
        parent = os.path.dirname(self.cwd)
        if parent != self.cwd:
            entries.append(".. (up)")
            raw.append(("..", True))
        try:
            names = sorted(
                os.listdir(self.cwd),
                key=lambda n: (not os.path.isdir(os.path.join(self.cwd, n)),
                               n.lower())
            )
            for name in names:
                full = os.path.join(self.cwd, name)
                if os.path.isdir(full):
                    entries.append("[/] " + name)
                    raw.append((name, True))
                elif os.path.splitext(name)[1].lower() in self.extensions:
                    # If name_pattern is specified, only show files matching the pattern
                    if self.name_pattern and self.name_pattern not in name:
                        continue
                    entries.append("    " + name)
                    raw.append((name, False))
        except PermissionError:
            pass
        self.entries = entries
        self._raw    = raw
        self.scroll  = 0

    def _dlg_h(self) -> int:
        base = 460
        return base + (self.FNAME_H + self.PAD) if self.save_mode else base

    def _dlg(self, screen) -> pygame.Rect:
        sw, sh = screen.get_size()
        h = self._dlg_h()
        return pygame.Rect((sw - self.DLG_W) // 2, (sh - h) // 2,
                           self.DLG_W, h)

    def _list_rect(self, dlg: pygame.Rect) -> pygame.Rect:
        top = dlg.y + self.HDR_H + self.PAD + 20   # 20 = path label height
        # reserve space for: (optional filename row) + button row + padding
        reserve = self.BTN_H + self.PAD * 2
        if self.save_mode:
            reserve += self.FNAME_H + self.PAD
        bot = dlg.bottom - reserve
        return pygame.Rect(dlg.x + self.PAD, top,
                           self.DLG_W - self.PAD * 2 - self.SB_W - 2,
                           bot - top)

    def _fn_rect(self, dlg: pygame.Rect) -> pygame.Rect:
        """Filename input rect (save mode only)."""
        lrect = self._list_rect(dlg)
        return pygame.Rect(dlg.x + self.PAD,
                           lrect.bottom + self.PAD,
                           self.DLG_W - self.PAD * 2,
                           self.FNAME_H)

    def _cancel_rect(self, dlg) -> pygame.Rect:
        return pygame.Rect(dlg.x + self.PAD,
                           dlg.bottom - self.BTN_H - self.PAD,
                           100, self.BTN_H)

    def _save_rect(self, dlg) -> pygame.Rect:
        cr = self._cancel_rect(dlg)
        return pygame.Rect(cr.right + self.PAD,
                           cr.y, 100, self.BTN_H)

    def _visible(self, lrect) -> int:
        return max(1, lrect.height // self.ITEM_H)

    # ── event handling ───────────────────────────────────────────────────────
    def handle(self, event, screen) -> bool:
        if not self.active:
            return False

        dlg   = self._dlg(screen)
        lrect = self._list_rect(dlg)
        vis   = self._visible(lrect)
        max_s = max(0, len(self.entries) - vis)

        # ── Keyboard ─────────────────────────────────────────────────────
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.active = False
                return True
            if self._fn_active and self.save_mode:
                # Filename text editing
                if event.key == pygame.K_BACKSPACE:
                    self._filename = self._filename[:-1]
                elif event.key == pygame.K_RETURN:
                    self._confirm_save()
                elif event.unicode and event.unicode.isprintable():
                    self._filename += event.unicode
            else:
                if event.key == pygame.K_UP:
                    self.scroll = max(0, self.scroll - 1)
                elif event.key == pygame.K_DOWN:
                    self.scroll = min(max_s, self.scroll + 1)
            return True

        # ── Mouse wheel (scroll list) ─────────────────────────────────────
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(max_s, self.scroll - event.y))
            return True

        # ── Mouse motion (hover) ──────────────────────────────────────────
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self._hover = (
                (my - lrect.y) // self.ITEM_H + self.scroll
                if lrect.collidepoint(mx, my) else -1
            )
            return True

        # ── Mouse click ───────────────────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # Cancel
            if self._cancel_rect(dlg).collidepoint(mx, my):
                self.active = False
                return True

            # Save button (save mode)
            if self.save_mode and self._save_rect(dlg).collidepoint(mx, my):
                self._confirm_save()
                return True

            # Filename input focus (save mode)
            if self.save_mode:
                fn_r = self._fn_rect(dlg)
                self._fn_active = fn_r.collidepoint(mx, my)

            # List entries
            if lrect.collidepoint(mx, my):
                idx = (my - lrect.y) // self.ITEM_H + self.scroll
                if 0 <= idx < len(self._raw):
                    name, is_dir = self._raw[idx]
                    if is_dir:
                        self.cwd = os.path.normpath(
                            os.path.join(self.cwd, name))
                        self._load()
                    elif self.save_mode:
                        # Populate the filename box; don't close yet
                        self._filename  = name
                        self._fn_active = True
                    else:
                        # Load mode: selecting a file is the final action
                        if self._cb:
                            self._cb(os.path.join(self.cwd, name))
                        self.active = False
            return True

        return False

    def _confirm_save(self):
        fn = self._filename.strip()
        if not fn:
            return
        # Ensure correct extension
        if self.extensions and not any(fn.lower().endswith(e) for e in self.extensions):
            fn += next(iter(self.extensions))   # append the first allowed ext
        if self._cb:
            self._cb(os.path.join(self.cwd, fn))
        self.active = False

    # ── drawing ──────────────────────────────────────────────────────────────
    def draw(self, screen):
        if not self.active:
            return

        # Dim veil
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 160))
        screen.blit(veil, (0, 0))

        dlg   = self._dlg(screen)
        lrect = self._list_rect(dlg)
        vis   = self._visible(lrect)

        # Dialog box
        pygame.draw.rect(screen, self.C_BG,    dlg, border_radius=8)
        pygame.draw.rect(screen, self.C_BORDER, dlg, 2, border_radius=8)

        # Header
        hdr = pygame.Rect(dlg.x, dlg.y, dlg.w, self.HDR_H)
        pygame.draw.rect(screen, self.C_HDR, hdr,
                         border_top_left_radius=8, border_top_right_radius=8)
        t = self.font_lg.render(self._title, True, (220, 220, 235))
        screen.blit(t, t.get_rect(centery=hdr.centery, x=hdr.x + self.PAD))

        # Current path (right-clipped so the end is always visible)
        max_pw    = dlg.w - self.PAD * 2
        path_surf = self.font_sm.render(self.cwd, True, self.C_PATH)
        if path_surf.get_width() > max_pw:
            path_surf = path_surf.subsurface(
                path_surf.get_width() - max_pw, 0, max_pw, path_surf.get_height())
        screen.blit(path_surf, (dlg.x + self.PAD, dlg.y + self.HDR_H + self.PAD))

        # List area background
        pygame.draw.rect(screen, self.C_LIST,
                         pygame.Rect(lrect.x, lrect.y,
                                     lrect.w + self.SB_W + 2, lrect.h),
                         border_radius=4)

        # Entries (clipped)
        old_clip = screen.get_clip()
        screen.set_clip(lrect)
        for i in range(vis):
            idx = i + self.scroll
            if idx >= len(self.entries):
                break
            iy = lrect.y + i * self.ITEM_H
            _, is_dir = self._raw[idx]
            if idx == self._hover:
                pygame.draw.rect(screen, self.C_HOVER,
                                 pygame.Rect(lrect.x, iy, lrect.w, self.ITEM_H))
            col = self.C_DIR if is_dir else self.C_FILE
            t   = self.font_sm.render(self.entries[idx], True, col)
            screen.blit(t, (lrect.x + 4, iy + (self.ITEM_H - t.get_height()) // 2))
        screen.set_clip(old_clip)

        # Scrollbar
        total = len(self.entries)
        if total > vis:
            sb_x = lrect.right + 2
            sb_h = lrect.h
            th_h = max(16, sb_h * vis // total)
            th_y = lrect.y + (sb_h - th_h) * self.scroll // max(1, total - vis)
            pygame.draw.rect(screen, self.C_SB_TR,
                             pygame.Rect(sb_x, lrect.y, self.SB_W, sb_h),
                             border_radius=4)
            pygame.draw.rect(screen, self.C_SB_TH,
                             pygame.Rect(sb_x, th_y, self.SB_W, th_h),
                             border_radius=4)

        # ── Filename input (save mode) ────────────────────────────────────
        if self.save_mode:
            fn_r   = self._fn_rect(dlg)
            fn_bg  = self.C_FN_ACT if self._fn_active else self.C_FN_BG
            pygame.draw.rect(screen, fn_bg,     fn_r, border_radius=4)
            pygame.draw.rect(screen, self.C_BORDER, fn_r, 1, border_radius=4)

            # Label to the left of the box
            lbl = self.font_sm.render("Filename:", True, self.C_PATH)
            screen.blit(lbl, lbl.get_rect(
                midleft=(dlg.x + self.PAD, fn_r.centery)))

            # Text value
            fn_text  = self._filename or ("enter filename…" if not self._fn_active else "")
            fn_color = (210, 210, 210) if self._filename else (100, 100, 130)
            fn_surf  = self.font_md.render(fn_text, True, fn_color)
            lbl_w    = lbl.get_width() + 6
            text_x   = fn_r.x + lbl_w
            old_clip = screen.get_clip()
            screen.set_clip(pygame.Rect(text_x, fn_r.y,
                                        fn_r.right - text_x - 4, fn_r.h))
            screen.blit(fn_surf, (text_x + 4,
                                  fn_r.centery - fn_surf.get_height() // 2))
            screen.set_clip(old_clip)

            # Caret
            if self._fn_active:
                cx = text_x + 4 + self.font_md.size(self._filename)[0] + 1
                pygame.draw.line(screen, (200, 200, 200),
                                 (cx, fn_r.y + 4), (cx, fn_r.bottom - 4))

        # ── Buttons ───────────────────────────────────────────────────────
        mouse = pygame.mouse.get_pos()

        cancel = self._cancel_rect(dlg)
        hov = cancel.collidepoint(mouse)
        pygame.draw.rect(screen, self.C_CANCEL_H if hov else self.C_CANCEL,
                         cancel, border_radius=4)
        pygame.draw.rect(screen, self.C_BORDER, cancel, 1, border_radius=4)
        t = self.font_md.render("Cancel", True, (220, 220, 220))
        screen.blit(t, t.get_rect(center=cancel.center))

        if self.save_mode:
            save_r = self._save_rect(dlg)
            hov    = save_r.collidepoint(mouse)
            pygame.draw.rect(screen, self.C_SAVE_H if hov else self.C_SAVE,
                             save_r, border_radius=4)
            pygame.draw.rect(screen, self.C_BORDER, save_r, 1, border_radius=4)
            t = self.font_md.render("Save", True, (220, 220, 220))
            screen.blit(t, t.get_rect(center=save_r.center))


# ─────────────────────────────────────────────────────────────────────────────
#  D&D 5.5e Stats dialog
# ─────────────────────────────────────────────────────────────────────────────
def _dnd_mod(score: int) -> int:
    """Return the D&D ability modifier for a given score (floor((score-10)/2))."""
    return (score - 10) // 2

def _mod_str(score: int) -> str:
    m = _dnd_mod(score)
    return f"+{m}" if m >= 0 else str(m)


# ─────────────────────────────────────────────────────────────────────────────
#  Eldritch Invocation registry — shared by StatsDialog + InvocationDialog.
#
#  code        : stable integer persisted in Agent.Stats.eldritch_invocations.
#                DO NOT renumber existing codes (breaks save files).
#  name        : display name.
#  min_level   : minimum Warlock level (spec "Prerequisite: Level N+"; 1 = no level req).
#  implemented : True once the C++ engine has a real combat effect (checked via
#                hasInvocation(code)); False entries render greyed/non-selectable
#                in the picker so the GUI never offers a no-op selection.
#  note        : short status / prerequisite shown in the picker.
#
#  Flip `implemented` to True (and add the hasInvocation check in C++) as each
#  invocation's engine effect lands. See warlock_invocation_roadmap memory.
# ─────────────────────────────────────────────────────────────────────────────
INVOCATIONS = [
    # code, name,                          min_level, implemented, note
    (0,  "Agonizing Blast",                 2, True,  "EB: +CHA damage"),
    (1,  "Repelling Blast",                 2, True,  "EB: push 10 ft"),
    (3,  "Eldritch Mind",                   1, True,  "Adv. on concentration saves"),
    (2,  "Eldritch Spear",                  2, True,  "EB range +30 ft/level"),
    (4,  "Devil's Sight",                   2, True,  "See in dim light/darkness 120 ft"),
    (5,  "Armor of Shadows",                1, True,  "Free Mage Armor (AC)"),
    (6,  "Fiendish Vigor",                  2, True,  "Free max-roll False Life (temp HP)"),
    (8,  "One with Shadows",                5, True,  "Free Invisibility in dim/dark"),
    (7,  "Witch Sight",                    15, True,  "Truesight 30 ft"),
    (10, "Otherworldly Leap",               2, True,  "Free Jump (x3 distance)"),
    (11, "Gift of the Depths",              5, True,  "Swim speed = Speed"),
    (12, "Master of Myriad Forms",          5, True,  "Free Alter Self (natural weapons)"),
    (9,  "Gift of the Protectors",          9, False, "Death Ward (drop to 1 HP) — needs Death Ward"),
    (13, "Pact of the Blade",               1, True,  "Conjure pact weapon (CHA atk/dmg)"),
    (14, "Thirsting Blade",                 5, True,  "Extra Attack — needs Pact of the Blade"),
    (15, "Eldritch Smite",                  5, True,  "Slot: +force/prone — needs Pact of the Blade"),
    (16, "Lifedrinker",                     9, True,  "+necrotic & temp HP — needs Pact of the Blade"),
    (17, "Devouring Blade",                12, True,  "2 extra attacks — needs Thirsting Blade"),
    (18, "Pact of the Chain",               1, True,  "Attacking familiar (6 forms)"),
    (19, "Investment of the Chain Master",  5, True,  "Familiar buffs — needs Pact of the Chain"),
    (20, "Pact of the Tome",                1, False, "Bonus cantrips/rituals"),
    (21, "Lessons of the First Ones",       2, False, "Origin feat — needs feats system"),
]

# Quick lookup: code -> (name, min_level, implemented, note)
INVOCATIONS_BY_CODE = {row[0]: row[1:] for row in INVOCATIONS}


class InvocationDialog:
    """Scrollable modal multi-select picker for Warlock Eldritch Invocations.

    Mirrors SpellSelectionDialog's overlay/scroll pattern but toggles a set of
    invocation codes (checkboxes). Unimplemented, level-locked, or feat-deferred
    rows render greyed and are not selectable. Commits the chosen codes to the
    callback when dismissed (Escape / Done / click-outside)."""
    ITEM_H = 30
    PAD    = 12
    HDR_H  = 36
    BTN_H  = 28

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self._selected = set()       # codes currently chosen
        self._eff_level = 1          # live Warlock level for gating
        self._callback = None        # called with sorted list of codes on dismiss
        self._done_rect = None
        self._frames_since_show = 0  # ignore the click that opened the dialog

    def show(self, callback, current_codes, eff_level):
        self.visible = True
        self._callback = callback
        self._selected = set(current_codes or [])
        self._eff_level = eff_level
        self.scroll_y = 0
        self._hover_idx = -1
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w, dlg_h = 440, 540
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def _commit_and_dismiss(self):
        if self._callback:
            self._callback(sorted(self._selected))
        self.visible = False

    def _row_enabled(self, code, min_level, implemented):
        """A row can be toggled only if its effect exists and the level allows it.
        A code already selected can always be toggled OFF (so a now-locked pick
        is removable)."""
        return (implemented and self._eff_level >= min_level) or (code in self._selected)

    def _list_geom(self):
        list_y = self.rect.y + self.HDR_H
        list_h = self.rect.h - self.HDR_H - self.BTN_H - self.PAD * 2
        return list_y, list_h

    def _max_scroll(self, list_h):
        return max(0, len(INVOCATIONS) * self.ITEM_H - list_h)

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        # Ignore the very click that opened us (same frame as show()).
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self._commit_and_dismiss()
                return True

        elif event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(*pygame.mouse.get_pos()):
            _list_y, list_h = self._list_geom()
            self.scroll_y = max(0, min(self.scroll_y - event.y * 30, self._max_scroll(list_h)))
            return True

        elif event.type == pygame.MOUSEMOTION:
            list_y, list_h = self._list_geom()
            self._hover_idx = -1
            for i in range(len(INVOCATIONS)):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= iy < list_y + list_h:
                    r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                    if r.collidepoint(*event.pos):
                        self._hover_idx = i
                        break

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._done_rect and self._done_rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            if not self.rect.collidepoint(*event.pos):
                self._commit_and_dismiss()   # click outside = accept current
                return True
            list_y, list_h = self._list_geom()
            for i, (code, name, min_level, implemented, note) in enumerate(INVOCATIONS):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if not (list_y <= iy < list_y + list_h):
                    continue
                r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos) and self._row_enabled(code, min_level, implemented):
                    if code in self._selected:
                        self._selected.discard(code)
                    else:
                        self._selected.add(code)
                    return True
            return True

        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1

        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))

        pygame.draw.rect(surf, (40, 40, 54), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)

        title = self.font_md.render(f"Eldritch Invocations  (Lv {self._eff_level})", True, (220, 220, 235))
        surf.blit(title, (self.rect.x + self.PAD, self.rect.y + 9))

        list_y, list_h = self._list_geom()
        list_rect = pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h)
        prev_clip = surf.get_clip()
        surf.set_clip(list_rect)
        cb = 14
        for i, (code, name, min_level, implemented, note) in enumerate(INVOCATIONS):
            iy = list_y + i * self.ITEM_H - self.scroll_y
            if iy + self.ITEM_H < list_y or iy > list_y + list_h:
                continue
            row = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
            level_ok = self._eff_level >= min_level
            enabled  = implemented and level_ok
            selected = code in self._selected
            if i == self._hover_idx and (enabled or selected):
                pygame.draw.rect(surf, (62, 62, 84), row)

            # Checkbox
            cb_r = pygame.Rect(row.x + 4, row.y + (self.ITEM_H - cb) // 2, cb, cb)
            box_col = (45, 110, 55) if selected else (50, 50, 66)
            bdr_col = (80, 200, 90) if selected else (90, 90, 120)
            if not enabled and not selected:
                box_col = (38, 38, 48)
            pygame.draw.rect(surf, box_col, cb_r, border_radius=2)
            pygame.draw.rect(surf, bdr_col, cb_r, 1, border_radius=2)
            if selected:
                pts = [(cb_r.x + 2, cb_r.centery), (cb_r.centerx - 1, cb_r.bottom - 2), (cb_r.right - 2, cb_r.y + 2)]
                pygame.draw.lines(surf, (120, 240, 120), False, pts, 2)

            name_col = (225, 225, 240) if enabled or selected else (120, 120, 140)
            nm = self.font_sm.render(name, True, name_col)
            surf.blit(nm, (cb_r.right + 8, row.y + 2))
            note_col = (140, 140, 165) if enabled or selected else (95, 95, 115)
            nt = self.font_sm.render(note, True, note_col)
            surf.blit(nt, (cb_r.right + 8, row.y + 15))

            # Right-side status tag
            if not level_ok:
                tag, tcol = f"Lv {min_level}", (210, 170, 70)
            elif not implemented:
                tag, tcol = "soon", (140, 130, 90)
            else:
                tag, tcol = "", (0, 0, 0)
            if tag:
                ts = self.font_sm.render(tag, True, tcol)
                surf.blit(ts, (row.right - ts.get_width() - 6, row.y + (self.ITEM_H - ts.get_height()) // 2))
        surf.set_clip(prev_clip)

        # Scrollbar
        max_scroll = self._max_scroll(list_h)
        if max_scroll > 0:
            track = pygame.Rect(list_rect.right - 6, list_y, 6, list_h)
            pygame.draw.rect(surf, (30, 30, 42), track)
            frac = list_h / (len(INVOCATIONS) * self.ITEM_H)
            th_h = max(20, int(list_h * frac))
            th_y = list_y + int((list_h - th_h) * (self.scroll_y / max_scroll))
            pygame.draw.rect(surf, (110, 110, 150), pygame.Rect(track.x, th_y, track.w, th_h))

        # Done button
        self._done_rect = pygame.Rect(self.rect.right - 90 - self.PAD,
                                      self.rect.bottom - self.BTN_H - self.PAD, 90, self.BTN_H)
        hov = self._done_rect.collidepoint(*pygame.mouse.get_pos())
        pygame.draw.rect(surf, (50, 125, 65) if hov else (35, 90, 45), self._done_rect, border_radius=4)
        pygame.draw.rect(surf, (90, 90, 120), self._done_rect, 1, border_radius=4)
        dt = self.font_md.render(f"Done ({len(self._selected)})", True, (220, 220, 220))
        surf.blit(dt, dt.get_rect(center=self._done_rect.center))


# ─────────────────────────────────────────────────────────────────────────────
#  Sorcerer Metamagic (SRD_CC_v5.2 p.65-66). A Sorcerer learns a limited number of
#  options and applies one to a spell at cast time (see METAMAGIC_IMPLEMENTATION_PLAN.md).
#  Subtle Spell is intentionally omitted — it is a deliberate no-op in this combat sim
#  (V/S/M components aren't simulated), so offering it would be a dead pick.
#  Rows: (MetamagicOption value, display name, SP cost, note).
# ─────────────────────────────────────────────────────────────────────────────
METAMAGIC_OPTIONS = [
    (rpg.MetamagicOption.Careful,    "Careful Spell",    1, "Allies auto-excluded from your AoE saves"),
    (rpg.MetamagicOption.Distant,    "Distant Spell",    1, "Double the spell's range (touch → 30 ft)"),
    (rpg.MetamagicOption.Empowered,  "Empowered Spell",  1, "Reroll up to CHA-mod low damage dice"),
    (rpg.MetamagicOption.Extended,   "Extended Spell",   1, "Double the duration (needs ≥ 2 rounds)"),
    (rpg.MetamagicOption.Heightened, "Heightened Spell", 2, "One target has Disadvantage on its save"),
    (rpg.MetamagicOption.Quickened,  "Quickened Spell",  2, "Cast a 1-action spell as a Bonus Action"),
    (rpg.MetamagicOption.Seeking,    "Seeking Spell",    1, "Reroll a missed spell attack (stacks)"),
    (rpg.MetamagicOption.Transmuted, "Transmuted Spell", 1, "Change the spell's damage type"),
    (rpg.MetamagicOption.Twinned,    "Twinned Spell",    1, "Target one additional creature"),
]


def metamagic_offered(option, learned_values, sp_available: int, sp_cost: int) -> bool:
    """Combat-sidebar gate for a Metamagic arm-toggle: offer it only when the option
    is LEARNED (in the caster's metamagic_options) and the caster can currently AFFORD
    its Sorcery-Point cost. Factored out as a pure predicate so it can be tested and
    reused by the sidebar draw pass (Phase 2)."""
    learned = {int(v) for v in (learned_values or [])}
    return int(option) in learned and sp_available >= sp_cost


def metamagic_known_count(level: int) -> int:
    """How many Metamagic options a Sorcerer knows at a given level (SRD p.65):
    2 at L2, +2 at L10, +2 at L17 (max 6). Below L2 the class has none."""
    if level >= 17:
        return 6
    if level >= 10:
        return 4
    if level >= 2:
        return 2
    return 0


class MetamagicDialog:
    """Scrollable multi-select picker for Sorcerer Metamagic options. A Sorcerer
    knows a level-capped number of options (see metamagic_known_count); once the cap
    is reached, un-selected rows render greyed and can't be toggled on (an already-
    selected row can always be toggled OFF so a now-illegal pick is removable).
    Commits the chosen MetamagicOption int values to the callback on dismiss."""
    ITEM_H = 34
    PAD    = 12
    HDR_H  = 36
    BTN_H  = 28

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self._selected = set()       # int enum values currently chosen
        self._eff_level = 1          # live Sorcerer level for the cap
        self._callback = None        # called with sorted list of int values on dismiss
        self._done_rect = None
        self._frames_since_show = 0

    def show(self, callback, current_values, eff_level):
        self.visible = True
        self._callback = callback
        self._selected = set(int(v) for v in (current_values or []))
        self._eff_level = eff_level
        self.scroll_y = 0
        self._hover_idx = -1
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w, dlg_h = 460, 480
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    @property
    def _cap(self):
        return metamagic_known_count(self._eff_level)

    def _commit_and_dismiss(self):
        if self._callback:
            self._callback(sorted(self._selected))
        self.visible = False

    def _row_enabled(self, value):
        """A row can be toggled ON only at L2+ and while under the known-count cap.
        A selected row can always be toggled OFF."""
        v = int(value)
        if v in self._selected:
            return True
        return self._eff_level >= 2 and len(self._selected) < self._cap

    def _list_geom(self):
        list_y = self.rect.y + self.HDR_H
        list_h = self.rect.h - self.HDR_H - self.BTN_H - self.PAD * 2
        return list_y, list_h

    def _max_scroll(self, list_h):
        return max(0, len(METAMAGIC_OPTIONS) * self.ITEM_H - list_h)

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        # Ignore the very click that opened us (same frame as show()).
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self._commit_and_dismiss()
                return True

        elif event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(*pygame.mouse.get_pos()):
            _list_y, list_h = self._list_geom()
            self.scroll_y = max(0, min(self.scroll_y - event.y * 30, self._max_scroll(list_h)))
            return True

        elif event.type == pygame.MOUSEMOTION:
            list_y, list_h = self._list_geom()
            self._hover_idx = -1
            for i in range(len(METAMAGIC_OPTIONS)):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= iy < list_y + list_h:
                    r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                    if r.collidepoint(*event.pos):
                        self._hover_idx = i
                        break

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._done_rect and self._done_rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            if not self.rect.collidepoint(*event.pos):
                self._commit_and_dismiss()   # click outside = accept current
                return True
            list_y, list_h = self._list_geom()
            for i, (value, name, sp, note) in enumerate(METAMAGIC_OPTIONS):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if not (list_y <= iy < list_y + list_h):
                    continue
                r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos) and self._row_enabled(value):
                    v = int(value)
                    if v in self._selected:
                        self._selected.discard(v)
                    else:
                        self._selected.add(v)
                    return True
            return True

        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1

        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))

        pygame.draw.rect(surf, (40, 40, 54), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)

        title = self.font_md.render(
            f"Metamagic  (Lv {self._eff_level}  —  {len(self._selected)}/{self._cap} known)",
            True, (220, 220, 235))
        surf.blit(title, (self.rect.x + self.PAD, self.rect.y + 9))

        list_y, list_h = self._list_geom()
        list_rect = pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h)
        prev_clip = surf.get_clip()
        surf.set_clip(list_rect)
        cb = 14
        at_cap = len(self._selected) >= self._cap
        for i, (value, name, sp, note) in enumerate(METAMAGIC_OPTIONS):
            iy = list_y + i * self.ITEM_H - self.scroll_y
            if iy + self.ITEM_H < list_y or iy > list_y + list_h:
                continue
            row = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
            selected = int(value) in self._selected
            enabled  = self._row_enabled(value)
            if i == self._hover_idx and enabled:
                pygame.draw.rect(surf, (62, 62, 84), row)

            # Checkbox
            cb_r = pygame.Rect(row.x + 4, row.y + (self.ITEM_H - cb) // 2, cb, cb)
            box_col = (45, 110, 55) if selected else (50, 50, 66)
            bdr_col = (80, 200, 90) if selected else (90, 90, 120)
            if not enabled and not selected:
                box_col = (38, 38, 48)
            pygame.draw.rect(surf, box_col, cb_r, border_radius=2)
            pygame.draw.rect(surf, bdr_col, cb_r, 1, border_radius=2)
            if selected:
                pts = [(cb_r.x + 2, cb_r.centery), (cb_r.centerx - 1, cb_r.bottom - 2), (cb_r.right - 2, cb_r.y + 2)]
                pygame.draw.lines(surf, (120, 240, 120), False, pts, 2)

            name_col = (225, 225, 240) if enabled or selected else (120, 120, 140)
            nm = self.font_sm.render(name, True, name_col)
            surf.blit(nm, (cb_r.right + 8, row.y + 3))
            note_col = (140, 140, 165) if enabled or selected else (95, 95, 115)
            nt = self.font_sm.render(note, True, note_col)
            surf.blit(nt, (cb_r.right + 8, row.y + 17))

            # Right-side SP-cost tag
            tag = f"{sp} SP"
            tcol = (170, 200, 240) if enabled or selected else (95, 95, 115)
            ts = self.font_sm.render(tag, True, tcol)
            surf.blit(ts, (row.right - ts.get_width() - 6, row.y + (self.ITEM_H - ts.get_height()) // 2))
        surf.set_clip(prev_clip)

        # Scrollbar
        max_scroll = self._max_scroll(list_h)
        if max_scroll > 0:
            track = pygame.Rect(list_rect.right - 6, list_y, 6, list_h)
            pygame.draw.rect(surf, (30, 30, 42), track)
            frac = list_h / (len(METAMAGIC_OPTIONS) * self.ITEM_H)
            th_h = max(20, int(list_h * frac))
            th_y = list_y + int((list_h - th_h) * (self.scroll_y / max_scroll))
            pygame.draw.rect(surf, (110, 110, 150), pygame.Rect(track.x, th_y, track.w, th_h))

        # Done button
        self._done_rect = pygame.Rect(self.rect.right - 90 - self.PAD,
                                      self.rect.bottom - self.BTN_H - self.PAD, 90, self.BTN_H)
        hov = self._done_rect.collidepoint(*pygame.mouse.get_pos())
        pygame.draw.rect(surf, (50, 125, 65) if hov else (35, 90, 45), self._done_rect, border_radius=4)
        pygame.draw.rect(surf, (90, 90, 120), self._done_rect, 1, border_radius=4)
        dt = self.font_md.render(f"Done ({len(self._selected)})", True, (220, 220, 220))
        surf.blit(dt, dt.get_rect(center=self._done_rect.center))


# ─────────────────────────────────────────────────────────────────────────────
#  General feats (2024 PHB). A PC may take several (unlike the single origin feat).
#  status: "in"   = combat effect wired into the engine now
#          "soon" = planned combat effect, not yet implemented
#          "note" = out-of-combat / no engine effect (selectable for record-keeping)
#  All rows are selectable; the tag just communicates whether it does anything in
#  combat yet. Names are the canonical strings stored in Agent.Stats.feats.
#  See GENERAL_FEATS_PLAN.md and known_limitations.md.
# ─────────────────────────────────────────────────────────────────────────────
GENERAL_FEATS = [
    # name,                    status, note
    ("Crusher",                "in",   "Bludgeoning hit: push 5 ft (crit-adv soon)"),
    ("Piercer",                "in",   "Piercing: reroll a die; +die on crit"),
    ("Slasher",                "in",   "Slashing hit: -10 ft Speed (crit-disadv soon)"),
    ("Great Weapon Master",    "in",   "Heavy hit: +PB damage; crit/kill: Hew bonus attack"),
    ("Grappler",               "in",   "Unarmed hit: also Grapple; adv vs grappled"),
    ("Sentinel",               "in",   "OA on Disengage; Halt speed 0; Guardian"),
    ("Defensive Duelist",      "in",   "Reaction: +PB AC vs melee (finesse)"),
    ("Shield Master",          "in",   "Shield Bash (bonus shove); Interpose soon"),
    ("Dual Wielder",           "in",   "+1 AC two melee weapons; extra bonus-action off-hand attack"),
    ("Polearm Master",         "soon", "Bonus d4 butt-end; reach reaction"),
    ("Crossbow Expert",        "in",   "Crossbows: no melee disadvantage (firing in melee)"),
    ("Sharpshooter",           "in",   "No long-range / firing-in-melee disadvantage"),
    ("Spell Sniper",           "in",   "Spell attacks: no melee disadv; +60 ft range"),
    ("Heavy Armor Master",     "in",   "-PB to B/P/S in Heavy armor"),
    ("Elemental Adept",        "in",   "Spells ignore resistance to a chosen element; treat 1 as 2"),
    ("Mage Slayer",            "in",   "Conc-breaker: disadv on conc save (Guarded Mind soon)"),
    ("War Caster",             "in",   "Adv on concentration saves"),
    ("Durable",                "in",   "Advantage on Death Saves"),
    ("Resilient",              "note", "Set the save proficiency via the checkboxes"),
    ("Medium Armor Master",    "in",   "+3 (not +2) Dex to AC in Medium armor"),
    ("Speedy",                 "in",   "+10 ft Speed; OA disadvantage vs you"),
    ("Athlete",                "in",   "Stand from prone for 5 ft (climb/jump unmodelled)"),
    ("Skulker",                "in",   "Blindsight 10 ft"),
    ("Telekinetic",            "in",   "Bonus-action shove 5 ft (STR save, 30 ft)"),
    ("Weapon Master",          "in",   "Use one weapon's Mastery property (Nick)"),
    ("Poisoner",               "in",   "Poison damage ignores resistance (Potent Poison)"),
    ("Charger",                "soon", "+10 ft Dash; charge bonus"),
    ("Fey Touched",            "soon", "Misty Step + 1 spell (grant)"),
    ("Shadow Touched",         "soon", "Invisibility + 1 spell (grant)"),
    ("Mounted Combatant",      "note", "No mount system modelled"),
    ("Ability Score Improvement","note","Edit ability scores directly"),
    ("Actor",                  "note", "Cha checks / mimicry"),
    ("Chef",                   "note", "Rest food / treats (rest-based)"),
    ("Inspiring Leader",       "note", "Rest temp HP to allies"),
    ("Keen Mind",              "note", "Skill/Expertise; bonus-action Study"),
    ("Observant",              "note", "Skill/Expertise; bonus-action Search"),
    ("Skill Expert",           "note", "Skill prof + Expertise"),
    ("Ritual Caster",          "note", "Ritual spells (out of combat)"),
    ("Telepathic",             "note", "Detect Thoughts / telepathy"),
    ("Heavily Armored",        "note", "Heavy-armor training (not enforced)"),
    ("Lightly Armored",        "note", "Light-armor training (not enforced)"),
    ("Moderately Armored",     "note", "Medium-armor training (not enforced)"),
    ("Martial Weapon Training","note", "Weapon proficiency (not enforced)"),
    # ── Fighting Styles (granted by the Fighting Style feature; prereqs not enforced) ──
    ("Archery",                "in",   "Fighting Style: +2 to-hit with Ranged weapons"),
    ("Defense",                "in",   "Fighting Style: +1 AC while wearing armor"),
    ("Dueling",                "in",   "Fighting Style: +2 dmg, one-handed melee, no other weapon"),
    ("Great Weapon Fighting",  "in",   "Fighting Style: reroll 1/2 as 3 (two-handed melee)"),
    ("Thrown Weapon Fighting", "in",   "Fighting Style: +2 dmg with thrown weapons"),
    ("Unarmed Fighting",       "in",   "Fighting Style: Unarmed Strike deals 1d6"),
    ("Blind Fighting",         "in",   "Fighting Style: Blindsight 10 ft (see invisible)"),
    ("Two-Weapon Fighting",    "in",   "Fighting Style: add ability mod to off-hand attack damage"),
    ("Interception",           "in",   "Fighting Style: reaction, reduce ally damage 1d10+PB"),
    ("Protection",             "soon", "Fighting Style: reaction, impose Disadvantage"),
]


class FeatDialog:
    """Scrollable modal multi-select picker for General feats (one PC may take several).

    Mirrors InvocationDialog's overlay/scroll/checkbox pattern but toggles a set of
    feat NAMES. Every row is selectable (feats are recorded in Agent.Stats.feats); the
    right-side tag shows whether the feat has a combat effect yet ('combat'), is planned
    ('soon'), or is out-of-combat ('note'). Commits chosen names on dismiss."""
    ITEM_H = 30
    PAD    = 12
    HDR_H  = 36
    BTN_H  = 28

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self._selected = set()       # feat names currently chosen
        self._callback = None        # called with sorted list of names on dismiss
        self._done_rect = None
        self._frames_since_show = 0

    def show(self, callback, current_names):
        self.visible = True
        self._callback = callback
        self._selected = set(current_names or [])
        self.scroll_y = 0
        self._hover_idx = -1
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w, dlg_h = 460, 560
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def _commit_and_dismiss(self):
        if self._callback:
            self._callback(sorted(self._selected))
        self.visible = False

    def _list_geom(self):
        list_y = self.rect.y + self.HDR_H
        list_h = self.rect.h - self.HDR_H - self.BTN_H - self.PAD * 2
        return list_y, list_h

    def _max_scroll(self, list_h):
        return max(0, len(GENERAL_FEATS) * self.ITEM_H - list_h)

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self._commit_and_dismiss()
                return True
        elif event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(*pygame.mouse.get_pos()):
            _list_y, list_h = self._list_geom()
            self.scroll_y = max(0, min(self.scroll_y - event.y * 30, self._max_scroll(list_h)))
            return True
        elif event.type == pygame.MOUSEMOTION:
            list_y, list_h = self._list_geom()
            self._hover_idx = -1
            for i in range(len(GENERAL_FEATS)):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= iy < list_y + list_h:
                    r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                    if r.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._done_rect and self._done_rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            if not self.rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            list_y, list_h = self._list_geom()
            for i, (name, status, note) in enumerate(GENERAL_FEATS):
                iy = list_y + i * self.ITEM_H - self.scroll_y
                if not (list_y <= iy < list_y + list_h):
                    continue
                r = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos):
                    if name in self._selected:
                        self._selected.discard(name)
                    else:
                        self._selected.add(name)
                    return True
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        pygame.draw.rect(surf, (40, 40, 54), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)
        title = self.font_md.render("General Feats", True, (220, 220, 235))
        surf.blit(title, (self.rect.x + self.PAD, self.rect.y + 9))

        list_y, list_h = self._list_geom()
        list_rect = pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h)
        prev_clip = surf.get_clip()
        surf.set_clip(list_rect)
        cb = 14
        _TAGS = {"in": ("combat", (90, 200, 110)), "soon": ("soon", (210, 170, 70)),
                 "note": ("note", (130, 130, 150))}
        for i, (name, status, note) in enumerate(GENERAL_FEATS):
            iy = list_y + i * self.ITEM_H - self.scroll_y
            if iy + self.ITEM_H < list_y or iy > list_y + list_h:
                continue
            row = pygame.Rect(self.rect.x + self.PAD, iy, self.rect.w - self.PAD * 2, self.ITEM_H)
            selected = name in self._selected
            if i == self._hover_idx:
                pygame.draw.rect(surf, (62, 62, 84), row)
            cb_r = pygame.Rect(row.x + 4, row.y + (self.ITEM_H - cb) // 2, cb, cb)
            box_col = (45, 110, 55) if selected else (50, 50, 66)
            bdr_col = (80, 200, 90) if selected else (90, 90, 120)
            pygame.draw.rect(surf, box_col, cb_r, border_radius=2)
            pygame.draw.rect(surf, bdr_col, cb_r, 1, border_radius=2)
            if selected:
                pts = [(cb_r.x + 2, cb_r.centery), (cb_r.centerx - 1, cb_r.bottom - 2), (cb_r.right - 2, cb_r.y + 2)]
                pygame.draw.lines(surf, (120, 240, 120), False, pts, 2)
            nm = self.font_sm.render(name, True, (225, 225, 240))
            surf.blit(nm, (cb_r.right + 8, row.y + 2))
            nt = self.font_sm.render(note, True, (140, 140, 165))
            surf.blit(nt, (cb_r.right + 8, row.y + 15))
            tag, tcol = _TAGS.get(status, ("", (0, 0, 0)))
            if tag:
                ts = self.font_sm.render(tag, True, tcol)
                surf.blit(ts, (row.right - ts.get_width() - 6, row.y + (self.ITEM_H - ts.get_height()) // 2))
        surf.set_clip(prev_clip)

        max_scroll = self._max_scroll(list_h)
        if max_scroll > 0:
            track = pygame.Rect(list_rect.right - 6, list_y, 6, list_h)
            pygame.draw.rect(surf, (30, 30, 42), track)
            frac = list_h / (len(GENERAL_FEATS) * self.ITEM_H)
            th_h = max(20, int(list_h * frac))
            th_y = list_y + int((list_h - th_h) * (self.scroll_y / max_scroll))
            pygame.draw.rect(surf, (110, 110, 150), pygame.Rect(track.x, th_y, track.w, th_h))

        self._done_rect = pygame.Rect(self.rect.right - 90 - self.PAD,
                                      self.rect.bottom - self.BTN_H - self.PAD, 90, self.BTN_H)
        hov = self._done_rect.collidepoint(*pygame.mouse.get_pos())
        pygame.draw.rect(surf, (50, 125, 65) if hov else (35, 90, 45), self._done_rect, border_radius=4)
        pygame.draw.rect(surf, (90, 90, 120), self._done_rect, 1, border_radius=4)
        dt = self.font_md.render(f"Done ({len(self._selected)})", True, (220, 220, 220))
        surf.blit(dt, dt.get_rect(center=self._done_rect.center))


# ─────────────────────────────────────────────────────────────────────────────
#  Reusable element picker (damage-type chooser). A small modal that lists a
#  caller-supplied set of damage types and returns the chosen value(s). Used now
#  by Elemental Adept (multi-select: one entry per element the feat was taken for)
#  and intended for cast-time element choices like Chromatic Orb / Sorcerous Burst
#  (single-select). Values are MagicDamage_t indices (Acid=0,Cold=1,Fire=2,
#  Lightning=4,Thunder=9, etc.). Modelled on FeatDialog's overlay/checkbox pattern.
# ─────────────────────────────────────────────────────────────────────────────

# The five elements Elemental Adept may choose (label, MagicDamage_t index).
ELEMENTAL_ADEPT_OPTIONS = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Thunder", 9)]

# Dragon ancestry types for Draconic Sorcerer L6 Elemental Affinity (single-select).
# Excludes Force, Necrotic, Radiant, Thunder — not standard dragon types.
DRACONIC_AFFINITY_OPTIONS = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6)]

# Quick int-to-name lookup for displaying the current choice.
_DRACONIC_AFFINITY_NAMES = {v: lbl for lbl, v in DRACONIC_AFFINITY_OPTIONS}


class ElementPickerDialog:
    """Modal (multi- or single-select) damage-type picker. Commits chosen values on dismiss."""
    ITEM_H = 32
    PAD    = 12
    HDR_H  = 36
    BTN_H  = 28

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self._hover_idx = -1
        self._options = []          # list of (label, value)
        self._selected = set()      # chosen values
        self._multi = True
        self._title = "Choose Element"
        self._callback = None       # called with a sorted list of chosen values on dismiss
        self._done_rect = None
        self._frames_since_show = 0

    def show(self, callback, options, current_values=None, multi=True, title="Choose Element"):
        self.visible = True
        self._callback = callback
        self._options = list(options)
        self._selected = set(current_values or [])
        self._multi = multi
        self._title = title
        self._hover_idx = -1
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 320
        dlg_h = self.HDR_H + len(self._options) * self.ITEM_H + self.BTN_H + self.PAD * 3
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def _commit_and_dismiss(self):
        if self._callback:
            self._callback(sorted(self._selected))
        self.visible = False

    def _list_y(self):
        return self.rect.y + self.HDR_H + self.PAD

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False
        # Swallow the click that opened this dialog (one frame), like FeatDialog.
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self._commit_and_dismiss()
                return True
        elif event.type == pygame.MOUSEMOTION:
            list_y = self._list_y()
            self._hover_idx = -1
            for i in range(len(self._options)):
                r = pygame.Rect(self.rect.x + self.PAD, list_y + i * self.ITEM_H,
                                self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos):
                    self._hover_idx = i
                    break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._done_rect and self._done_rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            if not self.rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            list_y = self._list_y()
            for i, (_label, value) in enumerate(self._options):
                r = pygame.Rect(self.rect.x + self.PAD, list_y + i * self.ITEM_H,
                                self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos):
                    if value in self._selected:
                        self._selected.discard(value)
                    elif self._multi:
                        self._selected.add(value)
                    else:
                        self._selected = {value}   # single-select replaces
                    return True
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)

        hdr = self.font_md.render(self._title, True, (220, 220, 235))
        surf.blit(hdr, (self.rect.x + self.PAD, self.rect.y + 9))

        list_y = self._list_y()
        for i, (label, value) in enumerate(self._options):
            r = pygame.Rect(self.rect.x + self.PAD, list_y + i * self.ITEM_H,
                            self.rect.w - self.PAD * 2, self.ITEM_H)
            if i == self._hover_idx:
                pygame.draw.rect(surf, (44, 44, 66), r, border_radius=4)
            box = pygame.Rect(r.x + 4, r.y + (self.ITEM_H - 18) // 2, 18, 18)
            pygame.draw.rect(surf, (150, 150, 180), box, width=2, border_radius=3)
            if value in self._selected:
                inner = box.inflate(-6, -6)
                pygame.draw.rect(surf, (120, 200, 120), inner, border_radius=2)
            lbl = self.font_md.render(label, True, (220, 220, 235))
            surf.blit(lbl, (box.right + 10, r.y + (self.ITEM_H - lbl.get_height()) // 2))

        bw, bh = 110, self.BTN_H
        self._done_rect = pygame.Rect(self.rect.centerx - bw // 2,
                                      self.rect.bottom - self.PAD - bh, bw, bh)
        pygame.draw.rect(surf, (35, 90, 45), self._done_rect, border_radius=6)
        dt = self.font_md.render(f"Done ({len(self._selected)})", True, (220, 220, 220))
        surf.blit(dt, dt.get_rect(center=self._done_rect.center))


class GridSpanDialog:
    """Small modal asking how many cells the sampled box spanned (cols × rows).

    Lets the user drag any rectangle — a single tile or a wider patch — then divide
    the box by the spanned cell count to recover a precise per-cell size (a 5-cell
    drag cuts per-tile drag error 5×). Defaults to 1×1 (a single tile). Calls back
    with (cols, rows) on OK, or None on cancel/escape.
    """
    PAD   = 14
    HDR_H = 34
    ROW_H = 34
    BTN_H = 30

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self._callback = None
        self._cols = None
        self._rows = None
        self._ok_rect = None
        self._cancel_rect = None
        self._frames_since_show = 0

    def show(self, callback):
        self.visible = True
        self._callback = callback
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 300
        dlg_h = self.HDR_H + self.ROW_H * 2 + self.BTN_H + self.PAD * 4
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)
        fld_w = 130
        fx = self.rect.right - self.PAD - fld_w
        y0 = self.rect.y + self.HDR_H + self.PAD
        self._cols = IntStepper(pygame.Rect(fx, y0, fld_w, self.ROW_H - 6), 1, 1, 500, self.font_md)
        self._rows = IntStepper(pygame.Rect(fx, y0 + self.ROW_H, fld_w, self.ROW_H - 6), 1, 1, 500, self.font_md)

    def _dismiss(self, result):
        cb = self._callback
        self.visible = False
        self._callback = None
        if cb:
            cb(result)

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False
        # Swallow the click that opened this dialog (one frame), like the other modals.
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True
        self._cols.handle(event)
        self._rows.handle(event)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self._dismiss((self._cols.value, self._rows.value))
            elif event.key == pygame.K_ESCAPE:
                self._dismiss(None)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._ok_rect and self._ok_rect.collidepoint(*event.pos):
                self._dismiss((self._cols.value, self._rows.value))
            elif self._cancel_rect and self._cancel_rect.collidepoint(*event.pos):
                self._dismiss(None)
            elif not self.rect.collidepoint(*event.pos):
                self._dismiss(None)
            return True
        return True

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)

        hdr = self.font_md.render("Cells in sampled box", True, (220, 220, 235))
        surf.blit(hdr, (self.rect.x + self.PAD, self.rect.y + 8))

        y0 = self.rect.y + self.HDR_H + self.PAD
        cl = self.font_md.render("Columns wide", True, (210, 210, 225))
        surf.blit(cl, (self.rect.x + self.PAD, y0 + 6))
        rl = self.font_md.render("Rows tall", True, (210, 210, 225))
        surf.blit(rl, (self.rect.x + self.PAD, y0 + self.ROW_H + 6))
        self._cols.draw(surf)
        self._rows.draw(surf)

        bw, bh = 96, self.BTN_H
        by = self.rect.bottom - self.PAD - bh
        self._ok_rect     = pygame.Rect(self.rect.right - self.PAD - bw, by, bw, bh)
        self._cancel_rect = pygame.Rect(self.rect.x + self.PAD, by, bw, bh)
        pygame.draw.rect(surf, (35, 90, 45), self._ok_rect, border_radius=6)
        pygame.draw.rect(surf, (90, 45, 45), self._cancel_rect, border_radius=6)
        ot = self.font_md.render("OK", True, (225, 225, 225))
        ct = self.font_md.render("Cancel", True, (225, 225, 225))
        surf.blit(ot, ot.get_rect(center=self._ok_rect.center))
        surf.blit(ct, ct.get_rect(center=self._cancel_rect.center))


class TeamPickerDialog:
    """Modal team/faction assignment. Lists every placed agent with a coloured team
    chip; clicking a row cycles its team (neutral → red → blue → …). Commits the
    {agent_idx: faction} map on dismiss. Scrolls if there are many agents."""
    ITEM_H   = 30
    PAD      = 12
    HDR_H    = 40
    BTN_H    = 28
    MAX_ROWS = 16

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self._hover_idx = -1
        self._rows = []            # list of (agent_idx, name)
        self._assign = {}          # agent_idx -> faction
        self._callback = None
        self._done_rect = None
        self._scroll = 0
        self._frames_since_show = 0

    def show(self, callback, agents):
        """agents: iterable of (agent_idx, name, faction)."""
        self.visible = True
        self._callback = callback
        self._rows   = [(idx, name) for (idx, name, _f) in agents]
        self._assign = {idx: f for (idx, _n, f) in agents}
        self._hover_idx = -1
        self._scroll = 0
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 360
        nrows = max(1, min(len(self._rows), self.MAX_ROWS))
        dlg_h = self.HDR_H + nrows * self.ITEM_H + self.BTN_H + self.PAD * 3
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def _commit_and_dismiss(self):
        if self._callback:
            self._callback(dict(self._assign))
        self.visible = False

    def _list_y(self):
        return self.rect.y + self.HDR_H + self.PAD

    def _visible_rows(self):
        return min(len(self._rows), self.MAX_ROWS)

    def _cycle(self, agent_idx):
        cur = self._assign.get(agent_idx, 0)
        i = FACTION_CHOICES.index(cur) if cur in FACTION_CHOICES else 0
        self._assign[agent_idx] = FACTION_CHOICES[(i + 1) % len(FACTION_CHOICES)]

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False
        # Swallow the click that opened this dialog (one frame), like ElementPickerDialog.
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self._commit_and_dismiss()
                return True
        elif event.type == pygame.MOUSEWHEEL:
            maxscroll = max(0, len(self._rows) - self.MAX_ROWS)
            self._scroll = max(0, min(maxscroll, self._scroll - event.y))
            return True
        elif event.type == pygame.MOUSEMOTION:
            list_y = self._list_y()
            self._hover_idx = -1
            for vi in range(self._visible_rows()):
                r = pygame.Rect(self.rect.x + self.PAD, list_y + vi * self.ITEM_H,
                                self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos):
                    self._hover_idx = vi + self._scroll
                    break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._done_rect and self._done_rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            if not self.rect.collidepoint(*event.pos):
                self._commit_and_dismiss()
                return True
            list_y = self._list_y()
            for vi in range(self._visible_rows()):
                r = pygame.Rect(self.rect.x + self.PAD, list_y + vi * self.ITEM_H,
                                self.rect.w - self.PAD * 2, self.ITEM_H)
                if r.collidepoint(*event.pos):
                    self._cycle(self._rows[vi + self._scroll][0])
                    return True
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)

        hdr = self.font_md.render("Assign Teams (click to cycle)", True, (220, 220, 235))
        surf.blit(hdr, (self.rect.x + self.PAD, self.rect.y + 11))

        list_y = self._list_y()
        for vi in range(self._visible_rows()):
            ridx = vi + self._scroll
            agent_idx, name = self._rows[ridx]
            fac = self._assign.get(agent_idx, 0)
            r = pygame.Rect(self.rect.x + self.PAD, list_y + vi * self.ITEM_H,
                            self.rect.w - self.PAD * 2, self.ITEM_H)
            if ridx == self._hover_idx:
                pygame.draw.rect(surf, (44, 44, 66), r, border_radius=4)
            chip = pygame.Rect(r.x + 4, r.y + (self.ITEM_H - 18) // 2, 56, 18)
            pygame.draw.rect(surf, faction_color(fac), chip, border_radius=4)
            ct = self.font_sm.render(faction_name(fac), True, (20, 20, 20))
            surf.blit(ct, ct.get_rect(center=chip.center))
            lbl = self.font_md.render(name, True, (220, 220, 235))
            surf.blit(lbl, (chip.right + 12, r.y + (self.ITEM_H - lbl.get_height()) // 2))

        bw, bh = 110, self.BTN_H
        self._done_rect = pygame.Rect(self.rect.centerx - bw // 2,
                                      self.rect.bottom - self.PAD - bh, bw, bh)
        pygame.draw.rect(surf, (35, 90, 45), self._done_rect, border_radius=6)
        dt = self.font_md.render("Done", True, (220, 220, 220))
        surf.blit(dt, dt.get_rect(center=self._done_rect.center))


class NamePromptDialog:
    """Tiny modal text prompt: a single editable line + OK/Cancel. Used by the
    agent right-click menu to rename a placed agent. Commits `callback(new_name)`
    on OK/Enter (only when non-empty); Esc/Cancel/click-outside dismisses."""
    PAD   = 14
    BTN_H = 28
    INP_H = 30

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self._text = ""
        self._title = ""
        self._callback = None
        self._ok_rect = None
        self._cancel_rect = None
        self._frames_since_show = 0

    def show(self, current_text, callback, title="Rename Agent"):
        self.visible = True
        self._text = current_text or ""
        self._title = title
        self._callback = callback
        self._frames_since_show = 0
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 380
        dlg_h = self.PAD * 4 + 22 + self.INP_H + self.BTN_H
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def _commit(self):
        new = self._text.strip()
        if new and self._callback:
            self._callback(new)
        self.visible = False

    def _dismiss(self):
        self.visible = False

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False
        # Swallow the click that opened this dialog (one frame), like TeamPickerDialog.
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._dismiss()
            elif event.key == pygame.K_RETURN:
                self._commit()
            elif event.key == pygame.K_BACKSPACE:
                self._text = self._text[:-1]
            elif event.unicode and event.unicode.isprintable():
                self._text += event.unicode
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._ok_rect and self._ok_rect.collidepoint(*event.pos):
                self._commit()
            elif self._cancel_rect and self._cancel_rect.collidepoint(*event.pos):
                self._dismiss()
            elif not self.rect.collidepoint(*event.pos):
                self._dismiss()
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        surf.blit(overlay, (0, 0))
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)

        hdr = self.font_md.render(self._title, True, (220, 220, 235))
        surf.blit(hdr, (self.rect.x + self.PAD, self.rect.y + self.PAD))

        inp = pygame.Rect(self.rect.x + self.PAD, self.rect.y + self.PAD + 24,
                          self.rect.w - self.PAD * 2, self.INP_H)
        pygame.draw.rect(surf, (18, 18, 28), inp, border_radius=4)
        pygame.draw.rect(surf, (140, 140, 170), inp, width=1, border_radius=4)
        txt = self.font_md.render(self._text, True, (235, 235, 245))
        surf.blit(txt, (inp.x + 6, inp.centery - txt.get_height() // 2))
        cx = inp.x + 6 + self.font_md.size(self._text)[0] + 1  # caret
        pygame.draw.line(surf, (235, 235, 245), (cx, inp.y + 4), (cx, inp.bottom - 4))

        bw, bh = 90, self.BTN_H
        by = self.rect.bottom - self.PAD - bh
        self._ok_rect = pygame.Rect(self.rect.right - self.PAD - bw, by, bw, bh)
        self._cancel_rect = pygame.Rect(self._ok_rect.x - self.PAD - bw, by, bw, bh)
        pygame.draw.rect(surf, (35, 90, 45), self._ok_rect, border_radius=6)
        pygame.draw.rect(surf, (90, 45, 45), self._cancel_rect, border_radius=6)
        ot = self.font_md.render("OK", True, (220, 220, 220))
        ct = self.font_md.render("Cancel", True, (220, 220, 220))
        surf.blit(ot, ot.get_rect(center=self._ok_rect.center))
        surf.blit(ct, ct.get_rect(center=self._cancel_rect.center))


# Set of general-feat names (for splitting feats vector between origin + general pickers).
GENERAL_FEAT_NAMES = {row[0] for row in GENERAL_FEATS}


class StatsDialog:
    """
    Modal dialog showing and editing D&D 5.5e stats for a placed agent.
    Right-click an agent on the map to open.
    Callback: callback(agent_idx, new_stats_obj) called on OK.
    """
    DLG_W = 610
    DLG_H = 700
    HDR_H = 36
    BTN_H = 32
    PAD   = 14

    C_BG      = (22,  22,  34)
    C_BORDER  = (80,  80, 120)
    C_HDR     = (34,  34,  56)
    C_SECT    = (110, 110, 160)
    C_LABEL   = (160, 160, 200)
    C_MOD_POS = ( 90, 200,  90)
    C_MOD_NEG = (200,  80,  80)
    C_MOD_ZRO = (150, 150, 180)
    C_HP_GOOD = ( 60, 185,  60)
    C_HP_WARN = (220, 160,  30)
    C_HP_CRIT = (200,  50,  50)
    C_HP_BG   = ( 35,  35,  50)
    C_CANCEL  = ( 90,  40,  40)
    C_CANCEL_H= (120,  55,  55)
    C_OK      = ( 35,  90,  45)
    C_OK_H    = ( 50, 125,  65)

    # Origin feats (2024 PHB). One per PC; "NONE" = no feat. The combat-relevant feats
    # (Tough/Alert/Savage Attacker/Tavern Brawler/Lucky) are wired into the engine; the
    # rest are stored for completeness (effects out of combat — see known_limitations.md).
    ORIGIN_FEATS = ["NONE", "Alert", "Crafter", "Healer", "Lucky", "Magic Initiate",
                    "Musician", "Savage Attacker", "Skilled", "Tavern Brawler", "Tough"]

    # Ordered ability-score fields
    ABILITIES = [
        ("STR", "str"),  ("DEX", "dex"), ("CON", "con"),
        ("INT", "intel"),("WIS", "wis"), ("CHA", "cha"),
    ]
    COMBAT = [
        ("Current HP",    "hp_cur",       0, 999),
        ("Max HP",        "hp_max",       1, 999),
        ("Armor Class",   "base_ac",      1,  30),
        ("Walk (ft)",     "speed_walk",   0, 120),
        ("Swim (ft)",     "speed_swim",   0, 120),
        ("Fly (ft)",      "speed_fly",    0, 120),
        ("Burrow (ft)",   "speed_burrow", 0, 120),
        ("Prof. Bonus",   "prof_bonus",   2,   6),
        ("# Attacks",     "num_attacks",  1,  10),
    ]

    def __init__(self, font_sm, font_md, font_lg, spells=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.font_lg = font_lg
        self.spells = spells or []
        self.active              = False
        self._agent_idx          = -1
        self._agent_name         = ""
        self._class_name         = "None"
        self._subclass_name      = "None"
        self._blessed_strike_name = "NONE"   # Cleric L7 Blessed Strikes choice
        self._blessed_strike_rects: dict = {}
        self._hunter_prey_name = "NONE"          # Hunter L3 Hunter's Prey choice
        self._hunter_prey_rects: dict = {}
        self._defensive_tactics_name = "NONE"    # Hunter L7 Defensive Tactics choice
        self._defensive_tactics_rects: dict = {}
        self._char_level         = 1
        self._cb                 = None
        self.steppers: dict      = {}   # populated in open()
        self.prof_flags: dict    = {}   # save_prof_<ability> -> bool
        self._prof_rects: dict   = {}   # same keys -> pygame.Rect
        self._class_rects: dict  = {}   # class cycle button rects
        self._subclass_rects: dict = {}  # subclass cycle button rects
        self._char_level_stepper = None  # IntStepper for character level
        self._is_npc             = False
        self._npc_spell_groups   = {}    # {N: [spell_names]}
        self._npc_add_group_rect = None
        self._spell_selection_dialog = None
        self._eldritch_invocations = []  # Warlock eldritch invocations (list of int codes)
        self._invocation_rects = {}      # invocation code -> pygame.Rect for checkboxes
        self._invocation_dialog = None   # scrollable picker (Warlock only)
        self._invocation_btn_rect = None # "Invocations..." launch button
        self._origin_feat        = "NONE"  # one origin feat per PC (cycle picker)
        self._origin_feat_rects: dict = {}
        self._feat_dialog        = None    # General Feats multi-select picker (PCs)
        self._feat_btn_rect      = None    # "Feats..." launch button
        self._general_feats      = set()   # selected general feat names
        self._element_dialog     = None    # Elemental Adept element picker (opened from the feat picker)
        self._elemental_adept_types = []   # MagicDamage_t indices chosen for Elemental Adept
        self._draconic_affinity_type = -1  # Draconic L6: chosen ancestry element (-1 = not set)
        self._draconic_affinity_btn_rect = None  # "Dragon Ancestry" button rect in draw()
        self._metamagic_options    = []    # Sorcerer Metamagic (list of int MetamagicOption values)
        self._metamagic_dialog     = None  # scrollable picker (Sorcerer L2+)
        self._metamagic_btn_rect   = None  # "Metamagic..." launch button

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, screen, agent_idx: int, agent_name: str, stats, class_name: str, char_level: int, callback, is_npc=False, npc_spell_groups=None, armor_list=None, subclass_name: str = "NONE", blessed_strike_name: str = "NONE", hunter_prey_name: str = "NONE", defensive_tactics_name: str = "NONE"):
        self.active             = True
        self._agent_idx         = agent_idx
        self._agent_name        = agent_name
        self._class_name        = class_name
        self._subclass_name     = subclass_name
        self._blessed_strike_name = blessed_strike_name
        self._hunter_prey_name  = hunter_prey_name
        self._defensive_tactics_name = defensive_tactics_name
        self._char_level        = char_level
        self._cb                = callback
        self._is_npc            = is_npc
        self._npc_spell_groups  = dict(npc_spell_groups) if npc_spell_groups else {}
        self._armor_list        = armor_list or []
        self._eldritch_invocations = list(stats.eldritch_invocations) if hasattr(stats, 'eldritch_invocations') else []
        self._metamagic_options = [int(m) for m in stats.metamagic_options] if hasattr(stats, 'metamagic_options') else []
        # Origin feat: show the one currently on the agent (first that's an origin feat), else NONE.
        cur_feats = list(stats.feats) if hasattr(stats, 'feats') else []
        self._origin_feat = next((f for f in cur_feats if f in self.ORIGIN_FEATS), "NONE")
        self._general_feats = {f for f in cur_feats if f in GENERAL_FEAT_NAMES}
        self._elemental_adept_types = list(stats.elemental_adept_types) if hasattr(stats, 'elemental_adept_types') else []
        self._draconic_affinity_type = int(stats.draconic_affinity_type) if hasattr(stats, 'draconic_affinity_type') else -1
        self._feat_dialog = FeatDialog(self.font_sm, self.font_md)
        self._element_dialog = ElementPickerDialog(self.font_sm, self.font_md)
        self._spell_selection_dialog = SpellSelectionDialog(self.spells, self.font_sm, self.font_md) if self.spells else None
        self._invocation_dialog = InvocationDialog(self.font_sm, self.font_md)
        self._metamagic_dialog = MetamagicDialog(self.font_sm, self.font_md)
        self._build_steppers(self._dlg(screen), stats)

    def _get_available_subclasses(self, class_name: str) -> list[str]:
        """Return list of available subclasses for a given class (using enum names)."""
        subclasses = {
            "Barbarian": ["NONE", "Berserker", "WildHeart", "WorldTree", "Zealot"],
            "Fighter": ["NONE", "Champion", "BattleMaster", "PsiWarrior", "EldritchKnight"],
            "Druid": ["NONE", "CircleOfMoon", "CircleOfLand", "CircleOfSea", "CircleOfStars", "CircleOfSpores", "CircleOfWildfire"],
            "Monk": ["NONE", "WarriorOfTheOpenHand", "WarriorOfMercy", "WarriorOfShadow", "WarriorOfFourElements"],
            "Paladin": ["NONE", "OathOfDevotion", "OathOftheMountedWarrior", "OathOfRedemption", "OathOfVengeance", "OathOfAncients", "OathOfGlory"],
            "Wizard": ["NONE", "Abjurer", "Diviner", "Evoker", "Illusionist"],
            "Warlock": ["NONE", "Archfey", "Celestial", "Fiend", "GreatOldOne"],
            "Rogue": ["NONE", "ArcaneTrickster", "Assassin", "Soulknife", "Thief"],
            "Cleric": ["NONE", "LifeDomain", "LightDomain", "TrickeryDomain", "WarDomain"],
            "Bard": ["NONE", "Dance", "Glamour", "Lore", "Valor"],
            "Sorcerer": ["NONE", "Aberrant", "Clockwork", "Draconic", "WildMagic"],
            "Ranger": ["NONE", "Hunter", "BeastMaster", "FeyWanderer", "GloomStalker"],
        }
        return subclasses.get(class_name, ["NONE"])

    def _display_subclass_name(self, enum_name: str) -> str:
        """Convert enum name to display name for UI."""
        if enum_name == "NONE":
            return "None"
        return enum_name

    # ── geometry ─────────────────────────────────────────────────────────────
    def _dlg(self, screen) -> pygame.Rect:
        sw, sh = screen.get_size()
        return pygame.Rect((sw - self.DLG_W) // 2, (sh - self.DLG_H) // 2,
                           self.DLG_W, self.DLG_H)

    def _cancel_rect(self, dlg) -> pygame.Rect:
        return pygame.Rect(dlg.right - 220,
                           dlg.bottom - self.BTN_H - self.PAD,
                           100, self.BTN_H)

    def _ok_rect(self, dlg) -> pygame.Rect:
        return pygame.Rect(dlg.right - 110,
                           dlg.bottom - self.BTN_H - self.PAD,
                           100, self.BTN_H)

    # ── stepper layout ───────────────────────────────────────────────────────
    def _build_steppers(self, dlg, stats):
        """Create / reset all IntStepper widgets from a Stats object."""
        from types import SimpleNamespace
        # import here to avoid circular; IntStepper is defined below this class
        # (they both exist in the same module, so this is fine at runtime)

        PAD, W = self.PAD, self.DLG_W
        y = dlg.y + self.HDR_H + PAD + 18 + 16  # after header + sect label + col labels

        # ── Ability scores (6 in a row) ───────────────────────────────────
        col_w  = (W - PAD * 2) // 6
        step_h = 28
        CB_H   = 16   # height (and width) of each proficiency checkbox
        for i, (lbl, key) in enumerate(self.ABILITIES):
            x = dlg.x + PAD + i * col_w
            val = getattr(stats, key, 10)
            r = pygame.Rect(x, y, col_w - 4, step_h)
            self.steppers[key] = IntStepper(r, val, 1, 30, self.font_md)

        # ── Saving throw proficiency checkboxes (one per ability column) ──
        # Sit below the modifier text: step_h + 2 (mod gap) + 14 (mod h) + 6 (gap)
        cb_y = y + step_h + 2 + 14 + 6
        self._prof_rects = {}
        self.prof_flags  = {}
        for i, (lbl, key) in enumerate(self.ABILITIES):
            flag_key = f"save_prof_{key}"
            cx = dlg.x + PAD + i * col_w + (col_w - CB_H) // 2
            self._prof_rects[flag_key] = pygame.Rect(cx, cb_y, CB_H, CB_H)
            self.prof_flags[flag_key]  = getattr(stats, flag_key, False)

        # ── Sleight of Hand skill checkbox (picks door locks) ─────────────
        # Sits at the right edge of the SAVE PROF. label row (first checkbox y - 16).
        self._sleight_rect = pygame.Rect(dlg.x + W - PAD - CB_H, cb_y - 16, CB_H, CB_H)
        self.prof_flags["sleight_of_hand_prof"] = getattr(stats, "sleight_of_hand_prof", False)

        # ── Combat stats (4 rows × 2 cols) ───────────────────────────────
        # Row starts below the checkbox row: cb_y + CB_H + gap + sect label + pad
        cy = cb_y + CB_H + 8 + 18 + 10
        half = (W - PAD * 3) // 2
        ROW = 52   # vertical stride per row
        # Build positions for 8 entries: pairs fill left/right, last row centred if odd
        positions = []
        for i, _ in enumerate(self.COMBAT):
            row_idx = i // 2
            col_idx = i  % 2
            cx  = dlg.x + PAD + col_idx * (half + PAD)
            ccy = cy + row_idx * ROW
            positions.append((cx, ccy))
        for (lbl, key, lo, hi), (cx, ccy) in zip(self.COMBAT, positions):
            r = pygame.Rect(cx, ccy, half, step_h)
            self.steppers[key] = IntStepper(r, getattr(stats, key, lo), lo, hi,
                                            self.font_md)

        # ── Character level stepper (Python-only, not in C++ stats) ────────
        # Create it at the bottom-left, below the combat stats
        last_row_idx = (len(self.COMBAT) - 1) // 2
        char_level_y = cy + (last_row_idx + 1) * ROW + 10
        char_level_rect = pygame.Rect(dlg.x + PAD, char_level_y, half, step_h)
        self._char_level_stepper = IntStepper(char_level_rect, self._char_level, 1, 20, self.font_md)

    # ── events ───────────────────────────────────────────────────────────────
    def handle(self, event, screen) -> bool:
        if not self.active:
            return False
        dlg = self._dlg(screen)

        # Invocation picker is modal-on-top: it consumes all events while open.
        if self._invocation_dialog and self._invocation_dialog.visible:
            self._invocation_dialog.handle(event)
            return True

        # Metamagic picker is modal-on-top too.
        if self._metamagic_dialog and self._metamagic_dialog.visible:
            self._metamagic_dialog.handle(event)
            return True

        # General Feats picker is modal-on-top too.
        if self._feat_dialog and self._feat_dialog.visible:
            self._feat_dialog.handle(event)
            return True

        # Element picker (Elemental Adept) is modal-on-top, above the feat picker.
        if self._element_dialog and self._element_dialog.visible:
            self._element_dialog.handle(event)
            return True

        # Let steppers see every event first so a focused field can consume
        # Escape/Enter before the dialog itself acts on Escape.
        any_field_active = any(st._active for st in self.steppers.values())
        if self._char_level_stepper:
            any_field_active = any_field_active or self._char_level_stepper._active
        for st in self.steppers.values():
            st.handle(event)
        if self._char_level_stepper:
            self._char_level_stepper.handle(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and not any_field_active:
                self.active = False
                return True
            if event.key == pygame.K_RETURN and not any_field_active:
                self._confirm()
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Invocations "Choose..." button → open the scrollable picker.
            if self._invocation_btn_rect and self._invocation_btn_rect.collidepoint(event.pos):
                if self._invocation_dialog:
                    eff_level = self._char_level_stepper.value if self._char_level_stepper else self._char_level
                    self._invocation_dialog.show(self._on_invocations_chosen,
                                                 self._eldritch_invocations, eff_level)
                return True

            # Metamagic "Choose..." button → open the scrollable picker (Sorcerer L2+).
            if self._metamagic_btn_rect and self._metamagic_btn_rect.collidepoint(event.pos):
                if self._metamagic_dialog:
                    eff_level = self._char_level_stepper.value if self._char_level_stepper else self._char_level
                    self._metamagic_dialog.show(self._on_metamagic_chosen,
                                                self._metamagic_options, eff_level)
                return True

            # General Feats "Choose..." button → open the multi-select picker.
            if self._feat_btn_rect and self._feat_btn_rect.collidepoint(event.pos):
                if self._feat_dialog:
                    self._feat_dialog.show(self._on_feats_chosen, self._general_feats)
                return True

            # Dragon Ancestry picker (Draconic Sorcerer L6+): single-select element type.
            if self._draconic_affinity_btn_rect and self._draconic_affinity_btn_rect.collidepoint(event.pos):
                if self._element_dialog:
                    cur = [self._draconic_affinity_type] if self._draconic_affinity_type >= 0 else []
                    self._element_dialog.show(self._on_draconic_elem_chosen, DRACONIC_AFFINITY_OPTIONS,
                                              current_values=cur, multi=False,
                                              title="Dragon Ancestry — element")
                return True

            # NPC checkbox and spell group interactions
            if hasattr(self, '_npc_checkbox_rect') and self._npc_checkbox_rect:
                if self._npc_checkbox_rect.collidepoint(event.pos):
                    self._is_npc = not self._is_npc
                    if not self._is_npc:
                        self._npc_spell_groups = {}
                    return True

            # NPC spell add/remove buttons
            if self._is_npc and hasattr(self, '_npc_spell_rects'):
                for (group_n, spell_name), btn_rect in self._npc_spell_rects.get('remove', {}).items():
                    if btn_rect.collidepoint(event.pos):
                        if str(group_n) in self._npc_spell_groups:
                            self._npc_spell_groups[str(group_n)].remove(spell_name)
                        return True

                for group_n, btn_rect in self._npc_spell_rects.get('add', {}).items():
                    if btn_rect.collidepoint(event.pos):
                        if self._spell_selection_dialog:
                            self._spell_selection_dialog.show(lambda spell: self._add_npc_spell(group_n, spell))
                        return True

            # Add Group button
            if self._is_npc and self._npc_add_group_rect and self._npc_add_group_rect.collidepoint(event.pos):
                # For simplicity, just add perDay3 with next available N
                max_n = max([int(k) for k in self._npc_spell_groups.keys()], default=0)
                self._npc_spell_groups[str(max_n + 1)] = []
                return True

            # Class cycle buttons
            if self._class_rects:
                available = self._class_rects.get("available", [])
                left_rect = self._class_rects.get("left")
                right_rect = self._class_rects.get("right")
                if available and left_rect and left_rect.collidepoint(event.pos):
                    idx = available.index(self._class_name) if self._class_name in available else 0
                    self._class_name = available[(idx - 1) % len(available)]
                    self._subclass_name = "NONE"  # Reset subclass when class changes
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(self._class_name) if self._class_name in available else 0
                    self._class_name = available[(idx + 1) % len(available)]
                    self._subclass_name = "NONE"  # Reset subclass when class changes
                    return True

            # Subclass cycle buttons
            if self._subclass_rects:
                available = self._subclass_rects.get("available", [])
                left_rect = self._subclass_rects.get("left")
                right_rect = self._subclass_rects.get("right")
                if available and left_rect and left_rect.collidepoint(event.pos):
                    idx = available.index(self._subclass_name) if self._subclass_name in available else 0
                    self._subclass_name = available[(idx - 1) % len(available)]
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(self._subclass_name) if self._subclass_name in available else 0
                    self._subclass_name = available[(idx + 1) % len(available)]
                    return True

            # Blessed Strikes cycle buttons (Cleric L7+)
            if self._blessed_strike_rects:
                available = self._blessed_strike_rects.get("available", [])
                left_rect = self._blessed_strike_rects.get("left")
                right_rect = self._blessed_strike_rects.get("right")
                if available and left_rect and left_rect.collidepoint(event.pos):
                    idx = available.index(self._blessed_strike_name) if self._blessed_strike_name in available else 0
                    self._blessed_strike_name = available[(idx - 1) % len(available)]
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(self._blessed_strike_name) if self._blessed_strike_name in available else 0
                    self._blessed_strike_name = available[(idx + 1) % len(available)]
                    return True

            # Hunter's Prey / Defensive Tactics cycle buttons (Hunter Ranger). Each picker stores its
            # current name in an attribute; cycle it left/right within the available list.
            for rects, attr in ((self._hunter_prey_rects, "_hunter_prey_name"),
                                (self._defensive_tactics_rects, "_defensive_tactics_name")):
                if not rects:
                    continue
                available = rects.get("available", [])
                left_rect = rects.get("left")
                right_rect = rects.get("right")
                cur = getattr(self, attr)
                if available and left_rect and left_rect.collidepoint(event.pos):
                    idx = available.index(cur) if cur in available else 0
                    setattr(self, attr, available[(idx - 1) % len(available)])
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(cur) if cur in available else 0
                    setattr(self, attr, available[(idx + 1) % len(available)])
                    return True

            # Origin feat cycle buttons (PCs only)
            if self._origin_feat_rects:
                available = self._origin_feat_rects.get("available", [])
                left_rect = self._origin_feat_rects.get("left")
                right_rect = self._origin_feat_rects.get("right")
                if available and left_rect and left_rect.collidepoint(event.pos):
                    idx = available.index(self._origin_feat) if self._origin_feat in available else 0
                    self._origin_feat = available[(idx - 1) % len(available)]
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(self._origin_feat) if self._origin_feat in available else 0
                    self._origin_feat = available[(idx + 1) % len(available)]
                    return True

            # Proficiency checkboxes
            for flag_key, rect in self._prof_rects.items():
                if rect.collidepoint(event.pos):
                    self.prof_flags[flag_key] = not self.prof_flags[flag_key]

            # Sleight of Hand skill checkbox
            if getattr(self, "_sleight_rect", None) and self._sleight_rect.collidepoint(event.pos):
                self.prof_flags["sleight_of_hand_prof"] = not self.prof_flags.get("sleight_of_hand_prof", False)

            # Invocation checkboxes (Warlock only)
            for invocation_code, rect in self._invocation_rects.items():
                if rect.collidepoint(event.pos):
                    if invocation_code in self._eldritch_invocations:
                        self._eldritch_invocations.remove(invocation_code)
                    else:
                        self._eldritch_invocations.append(invocation_code)
                    return True

            if self._ok_rect(dlg).collidepoint(event.pos):
                # Update character level from stepper before confirming
                if self._char_level_stepper:
                    self._char_level = self._char_level_stepper.value
                self._confirm()
            elif self._cancel_rect(dlg).collidepoint(event.pos):
                self.active = False
            return True

        # Handle spell selection dialog events
        if self._is_npc and self._spell_selection_dialog:
            if self._spell_selection_dialog.handle(event):
                return True

        return event.type in (pygame.MOUSEMOTION, pygame.MOUSEWHEEL)

    def _on_invocations_chosen(self, codes):
        """Callback from InvocationDialog: store the chosen invocation codes."""
        self._eldritch_invocations = list(codes)

    def _on_metamagic_chosen(self, values):
        """Callback from MetamagicDialog: store the chosen MetamagicOption int values."""
        self._metamagic_options = list(values)

    def _on_feats_chosen(self, names):
        """Callback from FeatDialog: store the chosen general-feat names.

        If Elemental Adept is among them, immediately pop the reusable element picker so the player
        chooses which element(s) it applies to. Deselecting the feat clears the stored elements."""
        self._general_feats = set(names)
        if "Elemental Adept" in self._general_feats:
            if self._element_dialog:
                self._element_dialog.show(self._on_elements_chosen, ELEMENTAL_ADEPT_OPTIONS,
                                          current_values=self._elemental_adept_types, multi=True,
                                          title="Elemental Adept — element(s)")
        else:
            self._elemental_adept_types = []

    def _on_elements_chosen(self, values):
        """Callback from the element picker: store the chosen MagicDamage_t indices."""
        self._elemental_adept_types = list(values)

    def _on_draconic_elem_chosen(self, values):
        """Callback from the Dragon Ancestry element picker (single-select)."""
        self._draconic_affinity_type = values[0] if values else -1

    def _add_npc_spell(self, group_n, spell):
        """Add a spell to an NPC spell group."""
        spell_name = spell.get("name", "Unknown")
        if str(group_n) not in self._npc_spell_groups:
            self._npc_spell_groups[str(group_n)] = []
        if spell_name not in self._npc_spell_groups[str(group_n)]:
            self._npc_spell_groups[str(group_n)].append(spell_name)

    def _confirm(self):
        if self._cb and self._agent_idx >= 0:
            npc_data = {"is_npc": self._is_npc, "npc_spell_groups": self._npc_spell_groups} if self._is_npc else None
            self._cb(self._agent_idx, self.steppers, self.prof_flags, self._class_name, self._char_level, npc_data, self._subclass_name, self._eldritch_invocations, self._blessed_strike_name, self._origin_feat, sorted(self._general_feats), sorted(self._elemental_adept_types), self._hunter_prey_name, self._defensive_tactics_name, self._draconic_affinity_type, list(self._metamagic_options))
        self.active = False

    # ── drawing ──────────────────────────────────────────────────────────────
    def draw(self, screen):
        if not self.active:
            return
        dlg = self._dlg(screen)

        # Veil
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 160))
        screen.blit(veil, (0, 0))

        # Box
        pygame.draw.rect(screen, self.C_BG,     dlg, border_radius=8)
        pygame.draw.rect(screen, self.C_BORDER,  dlg, 2, border_radius=8)

        # Header
        hdr = pygame.Rect(dlg.x, dlg.y, dlg.w, self.HDR_H)
        pygame.draw.rect(screen, self.C_HDR, hdr,
                         border_top_left_radius=8, border_top_right_radius=8)
        title = self.font_lg.render(
            f"{self._agent_name}  —  Character Stats", True, (220, 220, 235))
        screen.blit(title, title.get_rect(centery=hdr.centery, x=hdr.x + self.PAD))

        PAD = self.PAD
        col_w = (self.DLG_W - PAD * 2) // 6
        step_h = 28

        # ── Ability Scores section ────────────────────────────────────────
        sect_y = dlg.y + self.HDR_H + PAD
        t = self.font_sm.render("ABILITY SCORES", True, self.C_SECT)
        screen.blit(t, (dlg.x + PAD, sect_y))

        lbl_y = sect_y + 18
        for i, (lbl, key) in enumerate(self.ABILITIES):
            cx = dlg.x + PAD + i * col_w + col_w // 2
            # Column header
            lt = self.font_sm.render(lbl, True, self.C_LABEL)
            screen.blit(lt, lt.get_rect(centerx=cx, y=lbl_y))
            # Stepper
            st = self.steppers.get(key)
            if st:
                st.draw(screen)
                # Modifier below stepper
                m   = _dnd_mod(st.value)
                col = (self.C_MOD_POS if m > 0
                       else self.C_MOD_NEG if m < 0
                       else self.C_MOD_ZRO)
                mt  = self.font_sm.render(_mod_str(st.value), True, col)
                screen.blit(mt, mt.get_rect(centerx=cx, y=st.rect.bottom + 2))

        # ── Saving throw proficiency checkboxes ──────────────────────────
        if self._prof_rects:
            first_r = next(iter(self._prof_rects.values()))
            t = self.font_sm.render("SAVE PROF.", True, self.C_SECT)
            screen.blit(t, (dlg.x + PAD, first_r.y - 16))
        for flag_key, rect in self._prof_rects.items():
            checked  = self.prof_flags.get(flag_key, False)
            box_col  = (45, 110, 55) if checked else self.C_HDR
            bdr_col  = (80, 200, 90) if checked else self.C_BORDER
            pygame.draw.rect(screen, box_col, rect, border_radius=3)
            pygame.draw.rect(screen, bdr_col,  rect, 1, border_radius=3)
            if checked:
                pts = [
                    (rect.x + 3,              rect.centery),
                    (rect.centerx - 1,         rect.bottom - 3),
                    (rect.right - 3,           rect.y + 3),
                ]
                pygame.draw.lines(screen, (110, 240, 110), False, pts, 2)

        # ── Sleight of Hand skill checkbox ───────────────────────────────
        if getattr(self, "_sleight_rect", None):
            rect = self._sleight_rect
            checked = self.prof_flags.get("sleight_of_hand_prof", False)
            lbl = self.font_sm.render("Sleight of Hand", True, self.C_SECT)
            screen.blit(lbl, (rect.x - lbl.get_width() - 6, rect.centery - lbl.get_height() // 2))
            box_col = (45, 110, 55) if checked else self.C_HDR
            bdr_col = (80, 200, 90) if checked else self.C_BORDER
            pygame.draw.rect(screen, box_col, rect, border_radius=3)
            pygame.draw.rect(screen, bdr_col,  rect, 1, border_radius=3)
            if checked:
                pts = [
                    (rect.x + 3,       rect.centery),
                    (rect.centerx - 1, rect.bottom - 3),
                    (rect.right - 3,   rect.y + 3),
                ]
                pygame.draw.lines(screen, (110, 240, 110), False, pts, 2)

        # ── Combat Stats section ──────────────────────────────────────────
        half = (self.DLG_W - PAD * 3) // 2
        if "hp_cur" in self.steppers:
            cs_y = self.steppers["hp_cur"].rect.y - 18 - 10
            t = self.font_sm.render("COMBAT STATS", True, self.C_SECT)
            screen.blit(t, (dlg.x + PAD, cs_y))

        for lbl, key, _, _ in self.COMBAT:
            st = self.steppers.get(key)
            if st:
                # For AC, show total calculated AC including armor bonuses
                if key == "base_ac" and hasattr(self, '_armor_list'):
                    dex = self.steppers.get("dex", None)
                    dex_val = dex.value if dex else 10
                    total_ac = _calculate_total_ac(st.value, dex_val, self._armor_list)
                    display_lbl = f"{lbl} ({total_ac})"  # Show total AC in label
                    lt = self.font_sm.render(display_lbl, True, (100, 200, 100))
                else:
                    lt = self.font_sm.render(lbl, True, self.C_LABEL)
                screen.blit(lt, (st.rect.x, st.rect.y - 14))
                st.draw(screen)

        # ── HP bar ────────────────────────────────────────────────────────
        st_cur = self.steppers.get("hp_cur")
        st_max = self.steppers.get("hp_max")
        if st_cur and st_max:
            cur   = st_cur.value
            mx    = max(1, st_max.value)
            ratio = max(0.0, min(1.0, cur / mx))
            last_bottom = max(
                (self.steppers[key].rect.bottom for _, key, _, _ in self.COMBAT
                 if key in self.steppers),
                default=st_cur.rect.bottom)
            bar_y = last_bottom + 10
            bar_w = self.DLG_W - PAD * 2
            bar_r = pygame.Rect(dlg.x + PAD, bar_y, bar_w, 18)
            pygame.draw.rect(screen, self.C_HP_BG, bar_r, border_radius=4)
            if ratio > 0:
                hp_col = (self.C_HP_GOOD if ratio > 0.5
                          else self.C_HP_WARN if ratio > 0.25
                          else self.C_HP_CRIT)
                fill = pygame.Rect(bar_r.x, bar_r.y,
                                   max(4, int(bar_w * ratio)), 18)
                pygame.draw.rect(screen, hp_col, fill, border_radius=4)
            pygame.draw.rect(screen, self.C_BORDER, bar_r, 1, border_radius=4)
            hp_txt = self.font_sm.render(f"HP  {cur} / {mx}", True, (210, 210, 210))
            screen.blit(hp_txt, hp_txt.get_rect(center=bar_r.center))

        # ── Character Level and Class ─────────────────────────────────────
        if self._char_level_stepper:
            cs_y_label = self._char_level_stepper.rect.y - 14
            t = self.font_sm.render("Character Level", True, self.C_LABEL)
            screen.blit(t, (self._char_level_stepper.rect.x, cs_y_label))
            self._char_level_stepper.draw(screen)

            # Class cycle buttons (compact, on same row)
            class_y = self._char_level_stepper.rect.bottom + 8
            available_classes = ["None", "Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk", "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard"]
            class_lbl = self.font_sm.render("Class:", True, self.C_LABEL)
            screen.blit(class_lbl, (dlg.x + PAD, class_y))

            left_btn_r = pygame.Rect(dlg.x + PAD + 50, class_y, 20, 16)
            right_btn_r = pygame.Rect(dlg.right - PAD - 20, class_y, 20, 16)
            class_txt_r = pygame.Rect(left_btn_r.right + 4, class_y, right_btn_r.left - left_btn_r.right - 8, 16)

            pygame.draw.rect(screen, (60, 55, 80), left_btn_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), left_btn_r, 1, border_radius=2)
            left_txt = self.font_sm.render("<", True, (220, 210, 240))
            screen.blit(left_txt, left_txt.get_rect(center=left_btn_r.center))

            pygame.draw.rect(screen, (60, 55, 80), class_txt_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), class_txt_r, 1, border_radius=2)
            class_txt = self.font_sm.render(self._class_name, True, (220, 210, 240))
            screen.blit(class_txt, class_txt.get_rect(center=class_txt_r.center))

            pygame.draw.rect(screen, (60, 55, 80), right_btn_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), right_btn_r, 1, border_radius=2)
            right_txt = self.font_sm.render(">", True, (220, 210, 240))
            screen.blit(right_txt, right_txt.get_rect(center=right_btn_r.center))

            self._class_rects = {"left": left_btn_r, "right": right_btn_r, "available": available_classes}

            # Subclass cycle buttons (below class, if class has subclasses)
            available_subclasses = self._get_available_subclasses(self._class_name)
            if len(available_subclasses) > 1:  # Only show if there are subclass options
                subclass_y = class_y + 24
                subclass_lbl = self.font_sm.render("Subclass:", True, self.C_LABEL)
                screen.blit(subclass_lbl, (dlg.x + PAD, subclass_y))

                left_sub_r = pygame.Rect(dlg.x + PAD + 75, subclass_y, 20, 16)
                right_sub_r = pygame.Rect(dlg.right - PAD - 20, subclass_y, 20, 16)
                subclass_txt_r = pygame.Rect(left_sub_r.right + 4, subclass_y, right_sub_r.left - left_sub_r.right - 8, 16)

                pygame.draw.rect(screen, (60, 55, 80), left_sub_r, border_radius=2)
                pygame.draw.rect(screen, (120, 100, 150), left_sub_r, 1, border_radius=2)
                left_sub_txt = self.font_sm.render("<", True, (220, 210, 240))
                screen.blit(left_sub_txt, left_sub_txt.get_rect(center=left_sub_r.center))

                pygame.draw.rect(screen, (60, 55, 80), subclass_txt_r, border_radius=2)
                pygame.draw.rect(screen, (120, 100, 150), subclass_txt_r, 1, border_radius=2)
                subclass_txt = self.font_sm.render(self._display_subclass_name(self._subclass_name), True, (220, 210, 240))
                screen.blit(subclass_txt, subclass_txt.get_rect(center=subclass_txt_r.center))

                pygame.draw.rect(screen, (60, 55, 80), right_sub_r, border_radius=2)
                pygame.draw.rect(screen, (120, 100, 150), right_sub_r, 1, border_radius=2)
                right_sub_txt = self.font_sm.render(">", True, (220, 210, 240))
                screen.blit(right_sub_txt, right_sub_txt.get_rect(center=right_sub_r.center))

                self._subclass_rects = {"left": left_sub_r, "right": right_sub_r, "available": available_subclasses}

                # Blessed Strikes picker (Cleric L7+): Divine Strike vs Potent Spellcasting
                lvl = self._char_level_stepper.value if self._char_level_stepper else self._char_level
                if self._class_name == "Cleric" and lvl >= 7:
                    bs_y = subclass_y + 24
                    screen.blit(self.font_sm.render("Blessed:", True, self.C_LABEL), (dlg.x + PAD, bs_y))
                    left_bs_r = pygame.Rect(dlg.x + PAD + 75, bs_y, 20, 16)
                    right_bs_r = pygame.Rect(dlg.right - PAD - 20, bs_y, 20, 16)
                    bs_txt_r = pygame.Rect(left_bs_r.right + 4, bs_y, right_bs_r.left - left_bs_r.right - 8, 16)
                    pygame.draw.rect(screen, (60, 55, 80), left_bs_r, border_radius=2)
                    pygame.draw.rect(screen, (120, 100, 150), left_bs_r, 1, border_radius=2)
                    _lt = self.font_sm.render("<", True, (220, 210, 240)); screen.blit(_lt, _lt.get_rect(center=left_bs_r.center))
                    pygame.draw.rect(screen, (60, 55, 80), bs_txt_r, border_radius=2)
                    pygame.draw.rect(screen, (120, 100, 150), bs_txt_r, 1, border_radius=2)
                    _bs_disp = "None" if self._blessed_strike_name == "NONE" else self._blessed_strike_name
                    _bt = self.font_sm.render(_bs_disp, True, (220, 210, 240)); screen.blit(_bt, _bt.get_rect(center=bs_txt_r.center))
                    pygame.draw.rect(screen, (60, 55, 80), right_bs_r, border_radius=2)
                    pygame.draw.rect(screen, (120, 100, 150), right_bs_r, 1, border_radius=2)
                    _rt = self.font_sm.render(">", True, (220, 210, 240)); screen.blit(_rt, _rt.get_rect(center=right_bs_r.center))
                    self._blessed_strike_rects = {"left": left_bs_r, "right": right_bs_r,
                                                  "available": ["NONE", "DivineStrike", "PotentSpellcasting"]}
                    npc_checkbox_y = bs_y + 24
                # Hunter's Prey (L3) + Defensive Tactics (L7) pickers (Hunter Ranger only). Each is a
                # left/right cycle picker like Blessed Strikes; the chosen enum names round-trip to the
                # engine (which already honors hunter_prey / defensive_tactics).
                elif self._class_name == "Ranger" and self._subclass_name == "Hunter" and lvl >= 3:
                    def _picker(name, label, available, y):
                        screen.blit(self.font_sm.render(label, True, self.C_LABEL), (dlg.x + PAD, y))
                        l_r = pygame.Rect(dlg.x + PAD + 75, y, 20, 16)
                        r_r = pygame.Rect(dlg.right - PAD - 20, y, 20, 16)
                        t_r = pygame.Rect(l_r.right + 4, y, r_r.left - l_r.right - 8, 16)
                        for rr, txt in ((l_r, "<"), (t_r, "None" if name == "NONE" else name), (r_r, ">")):
                            pygame.draw.rect(screen, (60, 55, 80), rr, border_radius=2)
                            pygame.draw.rect(screen, (120, 100, 150), rr, 1, border_radius=2)
                            _s = self.font_sm.render(txt, True, (220, 210, 240))
                            screen.blit(_s, _s.get_rect(center=rr.center))
                        return {"left": l_r, "right": r_r, "available": available}
                    hp_y = subclass_y + 24
                    self._hunter_prey_rects = _picker(
                        self._hunter_prey_name, "Prey:",
                        ["NONE", "ColossusSlayer", "HordeBreaker"], hp_y)
                    if lvl >= 7:
                        dt_y = hp_y + 24
                        self._defensive_tactics_rects = _picker(
                            self._defensive_tactics_name, "Defense:",
                            ["NONE", "EscapeTheHorde", "MultiattackDefense"], dt_y)
                        npc_checkbox_y = dt_y + 24
                    else:
                        self._defensive_tactics_rects = {}
                        npc_checkbox_y = hp_y + 24
                    self._blessed_strike_rects = {}
                elif self._class_name == "Sorcerer" and self._subclass_name == "Draconic" and lvl >= 6:
                    # Dragon Ancestry picker: single-select button showing current choice (or "None").
                    btn_y = subclass_y + 24
                    elem_name = _DRACONIC_AFFINITY_NAMES.get(self._draconic_affinity_type, "None")
                    btn_label = f"Dragon Ancestry: {elem_name}"
                    btn_r = pygame.Rect(dlg.x + PAD, btn_y, dlg.w - 2 * PAD, 22)
                    pygame.draw.rect(screen, (60, 40, 80), btn_r, border_radius=4)
                    pygame.draw.rect(screen, (140, 100, 180), btn_r, 1, border_radius=4)
                    _bt = self.font_sm.render(btn_label, True, (220, 210, 240))
                    screen.blit(_bt, _bt.get_rect(center=btn_r.center))
                    self._draconic_affinity_btn_rect = btn_r
                    self._blessed_strike_rects = {}
                    self._hunter_prey_rects = {}
                    self._defensive_tactics_rects = {}
                    npc_checkbox_y = btn_y + 28
                else:
                    self._blessed_strike_rects = {}
                    self._hunter_prey_rects = {}
                    self._defensive_tactics_rects = {}
                    self._draconic_affinity_btn_rect = None
                    npc_checkbox_y = subclass_y + 24
            else:
                self._subclass_rects = {}
                self._blessed_strike_rects = {}
                self._hunter_prey_rects = {}
                self._defensive_tactics_rects = {}
                npc_checkbox_y = class_y + 24
        else:
            self._class_rects = {}
            self._subclass_rects = {}
            self._blessed_strike_rects = {}
            self._hunter_prey_rects = {}
            self._defensive_tactics_rects = {}
            npc_checkbox_y = dlg.y + self.HDR_H + self.PAD + 300

        # ── Warlock Eldritch Invocations ──────────────────────────────────
        # The full list is large, so it lives in a scrollable popup (InvocationDialog)
        # launched by this button; selected codes round-trip through _eldritch_invocations.
        self._invocation_rects = {}
        self._invocation_btn_rect = None
        if self._class_name == "Warlock":
            inv_y = (subclass_y + 24 if 'subclass_y' in locals() else class_y + 24) if self._char_level_stepper else dlg.y + self.HDR_H + self.PAD + 300
            inv_lbl = self.font_sm.render("Invocations:", True, self.C_LABEL)
            screen.blit(inv_lbl, (dlg.x + self.PAD, inv_y))
            n_sel = len(self._eldritch_invocations)
            self._invocation_btn_rect = pygame.Rect(dlg.x + self.PAD + 80, inv_y - 2, 150, 18)
            hov = self._invocation_btn_rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (70, 90, 130) if hov else (55, 60, 95), self._invocation_btn_rect, border_radius=3)
            pygame.draw.rect(screen, (120, 150, 180), self._invocation_btn_rect, 1, border_radius=3)
            btn_txt = self.font_sm.render(f"Choose... ({n_sel} selected)", True, (210, 220, 240))
            screen.blit(btn_txt, btn_txt.get_rect(center=self._invocation_btn_rect.center))
            npc_checkbox_y = inv_y + 24

        # ── Sorcerer Metamagic ────────────────────────────────────────────
        # Learned options round-trip through _metamagic_options; the actual arm/cast
        # happens on the combat sidebar. Gated on Sorcerer L2+ (SRD p.65). Flows at the
        # running npc_checkbox_y cursor so it sits below the subclass / Dragon Ancestry row.
        self._metamagic_btn_rect = None
        if self._class_name == "Sorcerer":
            eff_lvl = self._char_level_stepper.value if self._char_level_stepper else self._char_level
            if eff_lvl >= 2:
                mm_y = npc_checkbox_y
                mm_lbl = self.font_sm.render("Metamagic:", True, self.C_LABEL)
                screen.blit(mm_lbl, (dlg.x + self.PAD, mm_y))
                n_mm = len(self._metamagic_options)
                self._metamagic_btn_rect = pygame.Rect(dlg.x + self.PAD + 80, mm_y - 2, 150, 18)
                hov = self._metamagic_btn_rect.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(screen, (70, 90, 130) if hov else (55, 60, 95), self._metamagic_btn_rect, border_radius=3)
                pygame.draw.rect(screen, (120, 150, 180), self._metamagic_btn_rect, 1, border_radius=3)
                mm_txt = self.font_sm.render(f"Choose... ({n_mm} selected)", True, (210, 220, 240))
                screen.blit(mm_txt, mm_txt.get_rect(center=self._metamagic_btn_rect.center))
                npc_checkbox_y = mm_y + 24

        # ── Origin Feat (PCs only): one origin feat per character ──────────
        self._origin_feat_rects = {}
        if self._char_level_stepper and not self._is_npc:
            feat_y = npc_checkbox_y
            screen.blit(self.font_sm.render("Origin Feat:", True, self.C_LABEL), (dlg.x + self.PAD, feat_y))
            left_f_r  = pygame.Rect(dlg.x + self.PAD + 75, feat_y, 20, 16)
            right_f_r = pygame.Rect(dlg.right - self.PAD - 20, feat_y, 20, 16)
            feat_txt_r = pygame.Rect(left_f_r.right + 4, feat_y, right_f_r.left - left_f_r.right - 8, 16)
            pygame.draw.rect(screen, (60, 55, 80), left_f_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), left_f_r, 1, border_radius=2)
            _lt = self.font_sm.render("<", True, (220, 210, 240)); screen.blit(_lt, _lt.get_rect(center=left_f_r.center))
            pygame.draw.rect(screen, (60, 55, 80), feat_txt_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), feat_txt_r, 1, border_radius=2)
            _disp = "None" if self._origin_feat == "NONE" else self._origin_feat
            _ft = self.font_sm.render(_disp, True, (220, 210, 240)); screen.blit(_ft, _ft.get_rect(center=feat_txt_r.center))
            pygame.draw.rect(screen, (60, 55, 80), right_f_r, border_radius=2)
            pygame.draw.rect(screen, (120, 100, 150), right_f_r, 1, border_radius=2)
            _rt = self.font_sm.render(">", True, (220, 210, 240)); screen.blit(_rt, _rt.get_rect(center=right_f_r.center))
            self._origin_feat_rects = {"left": left_f_r, "right": right_f_r, "available": self.ORIGIN_FEATS}
            npc_checkbox_y = feat_y + 24

        # ── General Feats button (PCs only): launch the multi-select picker ──
        self._feat_btn_rect = None
        if self._char_level_stepper and not self._is_npc:
            gf_y = npc_checkbox_y
            screen.blit(self.font_sm.render("Feats:", True, self.C_LABEL), (dlg.x + self.PAD, gf_y))
            n_sel = len(self._general_feats)
            self._feat_btn_rect = pygame.Rect(dlg.x + self.PAD + 80, gf_y - 2, 150, 18)
            hov = self._feat_btn_rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (70, 90, 130) if hov else (55, 60, 95), self._feat_btn_rect, border_radius=3)
            pygame.draw.rect(screen, (120, 150, 180), self._feat_btn_rect, 1, border_radius=3)
            btn_txt = self.font_sm.render(f"Choose... ({n_sel} selected)", True, (210, 220, 240))
            screen.blit(btn_txt, btn_txt.get_rect(center=self._feat_btn_rect.center))
            npc_checkbox_y = gf_y + 24

        # ── NPC Spells Section ────────────────────────────────────────────
        npc_checkbox_y = npc_checkbox_y if self._char_level_stepper else dlg.y + self.HDR_H + self.PAD + 300
        npc_checkbox_h = 16
        self._npc_checkbox_rect = pygame.Rect(dlg.x + self.PAD, npc_checkbox_y, npc_checkbox_h, npc_checkbox_h)

        # Draw NPC checkbox
        box_col = (45, 110, 55) if self._is_npc else (60, 60, 80)
        bdr_col = (80, 200, 90) if self._is_npc else self.C_BORDER
        pygame.draw.rect(screen, box_col, self._npc_checkbox_rect, border_radius=3)
        pygame.draw.rect(screen, bdr_col, self._npc_checkbox_rect, 1, border_radius=3)
        if self._is_npc:
            pts = [(self._npc_checkbox_rect.x + 3, self._npc_checkbox_rect.centery),
                   (self._npc_checkbox_rect.centerx - 1, self._npc_checkbox_rect.bottom - 3),
                   (self._npc_checkbox_rect.right - 3, self._npc_checkbox_rect.y + 3)]
            pygame.draw.lines(screen, (110, 240, 110), False, pts, 2)

        # NPC label
        npc_txt = self.font_sm.render("NPC (N/day spells)", True, self.C_LABEL)
        screen.blit(npc_txt, (self._npc_checkbox_rect.right + 8, npc_checkbox_y))

        # Draw NPC spell groups if enabled
        if self._is_npc:
            self._npc_spell_rects = {'remove': {}, 'add': {}}
            spell_y = npc_checkbox_y + 28
            half = (self.DLG_W - self.PAD * 3) // 2

            for group_n_str in sorted(self._npc_spell_groups.keys(), key=lambda x: int(x)):
                group_n = int(group_n_str)
                spells = self._npc_spell_groups[group_n_str]
                label = self.font_sm.render(f"{group_n}/day:", True, self.C_LABEL)
                screen.blit(label, (dlg.x + self.PAD, spell_y))

                spell_x = dlg.x + self.PAD + 80
                for spell_name in spells:
                    spell_txt = self.font_sm.render(spell_name, True, (200, 200, 220))
                    spell_txt_rect = spell_txt.get_rect()
                    spell_txt_rect.topleft = (spell_x, spell_y)
                    screen.blit(spell_txt, spell_txt_rect)

                    # Remove button
                    remove_btn_rect = pygame.Rect(spell_txt_rect.right + 4, spell_y, 16, 16)
                    pygame.draw.rect(screen, (130, 50, 50), remove_btn_rect, border_radius=2)
                    pygame.draw.rect(screen, (180, 100, 100), remove_btn_rect, 1, border_radius=2)
                    rm_txt = self.font_sm.render("−", True, (220, 100, 100))
                    screen.blit(rm_txt, rm_txt.get_rect(center=remove_btn_rect.center))
                    self._npc_spell_rects['remove'][(group_n, spell_name)] = remove_btn_rect
                    spell_x = remove_btn_rect.right + 8

                # Add button for this group
                add_btn_rect = pygame.Rect(spell_x, spell_y, 20, 16)
                pygame.draw.rect(screen, (60, 130, 80), add_btn_rect, border_radius=2)
                pygame.draw.rect(screen, (100, 180, 120), add_btn_rect, 1, border_radius=2)
                add_txt = self.font_sm.render("+", True, (150, 240, 150))
                screen.blit(add_txt, add_txt.get_rect(center=add_btn_rect.center))
                self._npc_spell_rects['add'][group_n] = add_btn_rect

                spell_y += 24

            # Add Group button
            self._npc_add_group_rect = pygame.Rect(dlg.x + self.PAD, spell_y + 4, 120, 20)
            pygame.draw.rect(screen, (70, 90, 130), self._npc_add_group_rect, border_radius=3)
            pygame.draw.rect(screen, (120, 150, 180), self._npc_add_group_rect, 1, border_radius=3)
            ag_txt = self.font_sm.render("[Add Group]", True, (200, 220, 240))
            screen.blit(ag_txt, ag_txt.get_rect(center=self._npc_add_group_rect.center))

            # Draw spell selection dialog if open
            if self._spell_selection_dialog:
                self._spell_selection_dialog.draw(screen)

        # ── Buttons ───────────────────────────────────────────────────────
        mouse = pygame.mouse.get_pos()
        for rect, label, cc, ch in [
            (self._cancel_rect(dlg), "Cancel", self.C_CANCEL,  self.C_CANCEL_H),
            (self._ok_rect(dlg),     "OK",     self.C_OK,      self.C_OK_H),
        ]:
            hov = rect.collidepoint(mouse)
            pygame.draw.rect(screen, ch if hov else cc, rect, border_radius=4)
            pygame.draw.rect(screen, self.C_BORDER, rect, 1, border_radius=4)
            t = self.font_md.render(label, True, (220, 220, 220))
            screen.blit(t, t.get_rect(center=rect.center))

        # Invocation picker draws last so it overlays the whole stats dialog.
        if self._invocation_dialog:
            self._invocation_dialog.draw(screen)
        # Metamagic picker overlays on top as well.
        if self._metamagic_dialog:
            self._metamagic_dialog.draw(screen)
        # General Feats picker overlays on top as well.
        if self._feat_dialog:
            self._feat_dialog.draw(screen)
        # Element picker overlays above the feat picker (Elemental Adept).
        if self._element_dialog:
            self._element_dialog.draw(screen)


# ─────────────────────────────────────────────────────────────────────────────
#  Tiny UI helpers
# ─────────────────────────────────────────────────────────────────────────────
class Button:
    def __init__(self, rect: pygame.Rect, label: str, color=COL_BTN,
                 hover_color=COL_BTN_HOVER, font=None):
        self.rect   = rect
        self.label  = label
        self.color  = color
        self.hcolor = hover_color
        self.font   = font

    def draw(self, surf: pygame.Surface):
        hovered = self.rect.collidepoint(pygame.mouse.get_pos())
        col = self.hcolor if hovered else self.color
        pygame.draw.rect(surf, col, self.rect, border_radius=4)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.rect, 1, border_radius=4)
        txt = self.font.render(self.label, True, COL_TEXT)
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
            return self.lo

    @value.setter
    def value(self, v: int):
        self._raw = str(max(self.lo, min(self.hi, v)))

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
        """Clamp whatever the user typed and store it."""
        self._raw = str(self.value)   # value property already clamps

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


class MobSelectionDialog:
    """Modal dialog for selecting a mob from a scrollable list."""
    ITEM_H = 24
    PAD = 12
    SEARCH_H = 32

    def __init__(self, mobs: list[str], font_sm=None, font_md=None):
        self.all_mobs = mobs  # All available mobs
        self.filtered_mobs = mobs  # Filtered by search
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None
        self.search_text = ""
        self.search_active = False

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        self.search_text = ""
        self.search_active = True
        self.filtered_mobs = self.all_mobs[:]
        # Center dialog on screen
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 400
        dlg_h = 500
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def _update_filtered_mobs(self):
        """Filter mobs based on search text."""
        search_lower = self.search_text.lower()
        self.filtered_mobs = [m for m in self.all_mobs if search_lower in m.lower()]
        self.scroll_y = 0
        self._hover_idx = -1

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dismiss()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.search_text = self.search_text[:-1]
                self._update_filtered_mobs()
                return True
            elif event.key == pygame.K_RETURN:
                # Select first filtered mob if only one matches
                if len(self.filtered_mobs) == 1:
                    if self.selected_callback:
                        self.selected_callback(self.filtered_mobs[0])
                    self.dismiss()
                    return True
            elif event.unicode.isprintable():
                self.search_text += event.unicode
                self._update_filtered_mobs()
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(*event.pos):
                # Check if click is in search box area
                search_y = self.rect.y + 35
                search_box_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                             self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
                if search_box_rect.collidepoint(*event.pos):
                    self.search_active = True
                    return True

                list_y = search_y + self.SEARCH_H
                list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
                for i, mob in enumerate(self.filtered_mobs):
                    item_y = list_y + i * self.ITEM_H - self.scroll_y
                    if list_y <= item_y < list_y + list_h:
                        item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                              self.rect.w - self.PAD * 2, self.ITEM_H)
                        if item_rect.collidepoint(*event.pos):
                            if self.selected_callback:
                                self.selected_callback(mob)
                            self.dismiss()
                            return True
            else:
                self.dismiss()
            return True
        elif event.type == pygame.MOUSEMOTION and self.visible:
            search_y = self.rect.y + 35
            list_y = search_y + self.SEARCH_H
            list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
            self._hover_idx = -1
            for i, mob in enumerate(self.filtered_mobs):
                item_y = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= item_y < list_y + list_h:
                    item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                          self.rect.w - self.PAD * 2, self.ITEM_H)
                    if item_rect.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEWHEEL and self.visible and self.rect.collidepoint(*pygame.mouse.get_pos()):
            self.scroll_y = max(0, self.scroll_y - event.y * 30)
            max_scroll = max(0, len(self.filtered_mobs) * self.ITEM_H - (self.rect.h - self.SEARCH_H - 20))
            self.scroll_y = min(self.scroll_y, max_scroll)
            return True

        return False

    def draw(self, surf: pygame.Surface):
        if not self.visible or not self.rect:
            return

        # Semi-transparent overlay
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surf.blit(overlay, (0, 0))

        # Dialog background
        pygame.draw.rect(surf, COL_PANEL_BG, self.rect, border_radius=8)
        pygame.draw.rect(surf, COL_PANEL_BORDER, self.rect, 2, border_radius=8)

        # Title
        title = self.font_md.render("Select Mob", True, COL_TEXT)
        surf.blit(title, (self.rect.x + self.PAD, self.rect.y + self.PAD))

        # Search box (positioned below title with padding)
        search_y = self.rect.y + 35
        search_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                 self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
        search_bg = (60, 60, 80) if self.search_active else (40, 40, 60)
        pygame.draw.rect(surf, search_bg, search_rect, border_radius=4)
        pygame.draw.rect(surf, COL_PANEL_BORDER, search_rect, 1, border_radius=4)
        search_txt = self.font_sm.render(self.search_text if self.search_text else "Search mobs...",
                                        True, COL_TEXT if self.search_text else (120, 120, 120))
        surf.blit(search_txt, (search_rect.x + 6, search_rect.centery - search_txt.get_height() // 2))

        # List area (below search box)
        list_y = search_y + self.SEARCH_H
        list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
        list_rect = pygame.Rect(self.rect.x + self.PAD, list_y,
                               self.rect.w - self.PAD * 2, list_h)
        pygame.draw.rect(surf, (30, 30, 40), list_rect)

        # Draw filtered mobs
        for i, mob in enumerate(self.filtered_mobs):
            item_y = list_y + i * self.ITEM_H - self.scroll_y
            if list_y <= item_y < list_y + list_h:
                item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                      self.rect.w - self.PAD * 2, self.ITEM_H)
                item_bg = (80, 80, 120) if i == self._hover_idx else (40, 40, 60)
                pygame.draw.rect(surf, item_bg, item_rect)
                txt = self.font_sm.render(mob, True, COL_TEXT)
                surf.blit(txt, (item_rect.x + 6, item_rect.centery - txt.get_height() // 2))


# ─────────────────────────────────────────────────────────────────────────────
#  Context menu (right-click popup)
# ─────────────────────────────────────────────────────────────────────────────
class ContextMenu:
    """Tiny right-click popup menu.  Items are (label, callback) pairs."""
    ITEM_H = 28
    PAD    = 6
    MIN_W  = 130

    def __init__(self):
        self.items:      list  = []
        self.rect:       pygame.Rect | None = None
        self._hover_idx: int   = -1
        self.visible:    bool  = False
        self._font:      pygame.font.Font | None = None

    def show(self, pos: tuple[int, int], items: list[tuple[str, object]],
             screen_size: tuple[int, int] = (9999, 9999)):
        self._font   = pygame.font.SysFont(None, 16)
        self.items   = list(items)
        self._hover_idx = -1
        self.visible = True
        w = max(self.MIN_W,
                max((len(t) * 7 + self.PAD * 2) for t, _ in items))
        h = self.ITEM_H * len(items) + self.PAD * 2
        # Flip left / up if the menu would go off-screen.
        x = min(pos[0], screen_size[0] - w - 2)
        y = min(pos[1], screen_size[1] - h - 2)
        self.rect = pygame.Rect(x, y, w, h)

    def dismiss(self):
        self.visible = False
        self.items   = []
        self.rect    = None

    def handle(self, event) -> bool:
        """Returns True if the event was consumed (menu was visible)."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect and self.rect.collidepoint(*event.pos):
                idx = (event.pos[1] - self.rect.y - self.PAD) // self.ITEM_H
                if 0 <= idx < len(self.items):
                    _, cb = self.items[idx]
                    self.dismiss()
                    cb()
                    return True
            self.dismiss()
            return True   # click outside = dismiss, still consumed
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self.dismiss()
            return True
        if event.type == pygame.MOUSEMOTION and self.visible:
            if self.rect and self.rect.collidepoint(*event.pos):
                self._hover_idx = (
                    event.pos[1] - self.rect.y - self.PAD) // self.ITEM_H
            else:
                self._hover_idx = -1
        return False      # don't block other events while just moving

    def draw(self, screen):
        if not self.visible or not self.rect:
            return
        pygame.draw.rect(screen, (48, 48, 62), self.rect, border_radius=4)
        pygame.draw.rect(screen, (110, 110, 150), self.rect, 1, border_radius=4)
        for i, (text, _) in enumerate(self.items):
            ir = pygame.Rect(self.rect.x + 2,
                             self.rect.y + self.PAD + i * self.ITEM_H,
                             self.rect.width - 4, self.ITEM_H)
            if i == self._hover_idx:
                pygame.draw.rect(screen, (75, 100, 145), ir, border_radius=3)
            lbl = self._font.render(text, True, (225, 225, 225))
            screen.blit(lbl, (ir.x + self.PAD,
                               ir.centery - lbl.get_height() // 2))


class SpellGridMenu:
    """Multi-column grid of clickable buttons.  Items are (label, callback) pairs.

    Used for the in-combat spell list, which can hold dozens of spells — far more
    than the single-column ContextMenu can show without running off the bottom of
    the screen.  Buttons flow column-major (fill down a column, then start the next)
    so the list still reads top-to-bottom, and the whole grid is centred and sized
    to always fit inside the current screen.
    """
    BTN_H     = 30    # button height
    GAP       = 4     # gap between buttons
    PAD       = 12    # padding inside the popup frame
    TITLE_H   = 26    # header strip height
    MARGIN    = 24    # min gap between popup and screen edge
    MIN_COL_W = 150
    MAX_COL_W = 260

    def __init__(self, font=None):
        self._font   = font
        self.items:  list = []
        self.visible = False
        self.title   = ""
        self.rect:   pygame.Rect | None = None
        self._btn_rects: list = []   # (rect, item_index)
        self._hover_idx  = -1
        self._cols = 1
        self._rows = 1

    def show(self, items, screen_size=(9999, 9999), title="Cast a spell"):
        if self._font is None:
            self._font = pygame.font.SysFont(None, 18)
        self.items   = list(items)
        self.title   = title
        self.visible = True
        self._hover_idx = -1

        n = len(self.items)
        screen_w, screen_h = screen_size

        # Column width driven by the widest label (clamped to a sane range).
        widest = max((self._font.size(t)[0] for t, _ in self.items), default=0)
        col_w  = max(self.MIN_COL_W, min(self.MAX_COL_W, widest + 24))

        # How many rows fit vertically, and how many columns fit horizontally.
        avail_h  = screen_h - 2 * self.MARGIN - self.TITLE_H - 2 * self.PAD
        rows_max = max(1, (avail_h + self.GAP) // (self.BTN_H + self.GAP))
        avail_w  = screen_w - 2 * self.MARGIN - 2 * self.PAD
        cols_max = max(1, (avail_w + self.GAP) // (col_w + self.GAP))

        cols = min(cols_max, max(1, (n + rows_max - 1) // rows_max))
        rows = (n + cols - 1) // cols
        self._cols, self._rows = cols, rows

        grid_w = cols * col_w + (cols - 1) * self.GAP
        grid_h = rows * self.BTN_H + (rows - 1) * self.GAP
        w = grid_w + 2 * self.PAD
        h = grid_h + 2 * self.PAD + self.TITLE_H
        x = max(self.MARGIN, (screen_w - w) // 2)
        y = max(self.MARGIN, (screen_h - h) // 2)
        self.rect = pygame.Rect(x, y, w, h)

        # Pre-compute a rect for every button (column-major layout).
        self._btn_rects = []
        gx = x + self.PAD
        gy = y + self.PAD + self.TITLE_H
        for i in range(n):
            c = i // rows
            r = i % rows
            bx = gx + c * (col_w + self.GAP)
            by = gy + r * (self.BTN_H + self.GAP)
            self._btn_rects.append((pygame.Rect(bx, by, col_w, self.BTN_H), i))

    def dismiss(self):
        self.visible = False
        self.items   = []
        self.rect    = None
        self._btn_rects = []
        self._hover_idx = -1

    def handle(self, event) -> bool:
        """Returns True if the event was consumed (menu was visible)."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, i in self._btn_rects:
                if rect.collidepoint(*event.pos):
                    _, cb = self.items[i]
                    self.dismiss()
                    cb()
                    return True
            self.dismiss()   # click outside any button = dismiss
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self.dismiss()
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.dismiss()
            return True
        if event.type == pygame.MOUSEMOTION:
            self._hover_idx = -1
            for rect, i in self._btn_rects:
                if rect.collidepoint(*event.pos):
                    self._hover_idx = i
                    break
        return False

    def draw(self, screen):
        if not self.visible or not self.rect:
            return
        pygame.draw.rect(screen, (40, 40, 54), self.rect, border_radius=6)
        pygame.draw.rect(screen, (120, 120, 165), self.rect, 1, border_radius=6)
        # Title strip.
        if self.title:
            tlbl = self._font.render(self.title, True, (235, 220, 140))
            screen.blit(tlbl, (self.rect.x + self.PAD,
                               self.rect.y + (self.TITLE_H - tlbl.get_height()) // 2 + 2))
        # Buttons.
        for rect, i in self._btn_rects:
            hovered = (i == self._hover_idx)
            bg = (78, 104, 150) if hovered else (58, 58, 74)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            pygame.draw.rect(screen, (100, 100, 135), rect, 1, border_radius=4)
            text = self.items[i][0]
            lbl  = self._font.render(text, True, (232, 232, 232))
            # Clip overly long labels to the button width.
            if lbl.get_width() > rect.width - 12:
                lbl = lbl.subsurface((0, 0, rect.width - 12, lbl.get_height()))
            screen.blit(lbl, (rect.x + 8, rect.centery - lbl.get_height() // 2))


class SpellSelectionDialog:
    """Modal dialog for selecting a spell from spells.json.

    Spells are organized into per-level tabs (All / Cantrip / 1st-9th) so the
    full 350+ spell list never overflows the box. A search box filters across
    *all* levels when non-empty (the active tab is ignored while searching).
    """
    ITEM_H = 24
    PAD = 12
    SEARCH_H = 32
    TAB_H = 26
    # Tab definitions: (label, level-key). level None == "All".
    TABS = [("All", None), ("C", 0), ("1", 1), ("2", 2), ("3", 3),
            ("4", 4), ("5", 5), ("6", 6), ("7", 7), ("8", 8), ("9", 9)]

    def __init__(self, spells: list, font_sm=None, font_md=None):
        self.all_spells = spells  # All available spells (dicts with "name")
        self.filtered_spells = spells  # Filtered by search + active tab
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None
        self.search_text = ""
        self.active_level = None  # None == "All" tab
        self._tab_rects = []      # cached (rect, level) for hit-testing
        self._frames_since_show = 0  # Prevent immediate dismissal on show click

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        self.search_text = ""
        self.active_level = None
        self._frames_since_show = 0  # Reset counter to prevent immediate dismissal
        self._update_filtered_spells()
        # Center dialog on screen
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 460
        dlg_h = 520
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def _update_filtered_spells(self):
        """Filter spells based on search text and the active level tab.

        When a search is active it spans every level (tab is ignored) so the
        user can always find a spell by name. Otherwise the active tab decides.
        """
        search_lower = self.search_text.strip().lower()
        if search_lower:
            self.filtered_spells = [s for s in self.all_spells
                                    if search_lower in s.get("name", "").lower()]
        elif self.active_level is None:
            self.filtered_spells = self.all_spells[:]
        else:
            self.filtered_spells = [s for s in self.all_spells
                                    if s.get("level", 0) == self.active_level]
        self.scroll_y = 0
        self._hover_idx = -1

    def _layout(self):
        """Return (tabs_y, list_y, list_h) for the current rect."""
        tabs_y = self.rect.y + 32
        search_y = tabs_y + self.TAB_H + 4
        list_y = search_y + self.SEARCH_H
        list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
        return tabs_y, search_y, list_y, list_h

    def _max_scroll(self, list_h):
        return max(0, len(self.filtered_spells) * self.ITEM_H - list_h)

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        # Skip first click after show to prevent dismissal on the same click that showed the dialog
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

        _, search_y, list_y, list_h = self._layout()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dismiss()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.search_text = self.search_text[:-1]
                self._update_filtered_spells()
                return True
            elif event.key == pygame.K_RETURN:
                # Select first filtered spell if only one matches
                if len(self.filtered_spells) == 1:
                    if self.selected_callback:
                        self.selected_callback(self.filtered_spells[0])
                    self.dismiss()
                    return True
            elif event.unicode.isprintable():
                self.search_text += event.unicode
                self._update_filtered_spells()
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(*event.pos):
                # Tab clicks
                for tab_rect, level in self._tab_rects:
                    if tab_rect.collidepoint(*event.pos):
                        self.active_level = level
                        self.search_text = ""  # tab switch clears search
                        self._update_filtered_spells()
                        return True

                # Search box clicks are absorbed (typing handled via KEYDOWN)
                search_box_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                             self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
                if search_box_rect.collidepoint(*event.pos):
                    return True

                for i, spell in enumerate(self.filtered_spells):
                    item_y = list_y + i * self.ITEM_H - self.scroll_y
                    if list_y <= item_y < list_y + list_h:
                        item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                              self.rect.w - self.PAD * 2, self.ITEM_H)
                        if item_rect.collidepoint(*event.pos):
                            if self.selected_callback:
                                self.selected_callback(spell)
                            self.dismiss()
                            return True
            else:
                self.dismiss()
            return True
        elif event.type == pygame.MOUSEMOTION and self.visible:
            self._hover_idx = -1
            for i, spell in enumerate(self.filtered_spells):
                item_y = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= item_y < list_y + list_h:
                    item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                          self.rect.w - self.PAD * 2, self.ITEM_H)
                    if item_rect.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEWHEEL and self.visible and self.rect.collidepoint(*pygame.mouse.get_pos()):
            self.scroll_y = max(0, self.scroll_y - event.y * 30)
            self.scroll_y = min(self.scroll_y, self._max_scroll(list_h))
            return True

        return False

    def draw(self, surf: pygame.Surface):
        if not self.visible or not self.rect:
            return

        # Increment frame counter (allows us to ignore first click after show)
        self._frames_since_show += 1

        # Semi-transparent overlay
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surf.blit(overlay, (0, 0))

        # Dialog box
        pygame.draw.rect(surf, (50, 50, 60), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)

        # Title
        title = self.font_md.render("Select a Spell", True, (220, 220, 235))
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 8)
        surf.blit(title, title_rect)

        tabs_y, search_y, list_y, list_h = self._layout()

        # Level tabs
        searching = bool(self.search_text.strip())
        tab_area_w = self.rect.w - self.PAD * 2
        tab_w = tab_area_w / len(self.TABS)
        self._tab_rects = []
        for idx, (label, level) in enumerate(self.TABS):
            tx = self.rect.x + self.PAD + int(idx * tab_w)
            tw = int((idx + 1) * tab_w) - int(idx * tab_w) - 2
            tab_rect = pygame.Rect(tx, tabs_y, tw, self.TAB_H)
            self._tab_rects.append((tab_rect, level))
            active = (not searching) and (level == self.active_level)
            bg = (90, 90, 130) if active else (40, 40, 52)
            pygame.draw.rect(surf, bg, tab_rect, border_radius=4)
            pygame.draw.rect(surf, (110, 110, 140), tab_rect, 1, border_radius=4)
            col = (235, 235, 245) if active else (170, 170, 190)
            lbl = self.font_sm.render(label, True, col)
            surf.blit(lbl, lbl.get_rect(center=tab_rect.center))

        # Search box
        search_box = pygame.Rect(self.rect.x + self.PAD, search_y, self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
        pygame.draw.rect(surf, (30, 30, 40), search_box)
        pygame.draw.rect(surf, (140, 140, 90) if searching else (100, 100, 120), search_box, 1)
        search_label = self.font_sm.render(f"Search: {self.search_text}_", True, (200, 200, 200))
        surf.blit(search_label, (search_box.x + 4, search_box.y + 4))

        # Spell list background
        list_bg = pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h)
        pygame.draw.rect(surf, (30, 30, 40), list_bg)

        if not self.filtered_spells:
            empty = self.font_sm.render("(no spells)", True, (130, 130, 145))
            surf.blit(empty, (list_bg.x + 8, list_y + 6))

        for i, spell in enumerate(self.filtered_spells):
            item_y = list_y + i * self.ITEM_H - self.scroll_y
            if list_y <= item_y < list_y + list_h:
                item_rect = pygame.Rect(self.rect.x + self.PAD, item_y, self.rect.w - self.PAD * 2, self.ITEM_H)
                if i == self._hover_idx:
                    pygame.draw.rect(surf, (70, 70, 90), item_rect)
                spell_name = spell.get("name", "Unknown")
                text = self.font_sm.render(spell_name, True, (200, 200, 220))
                surf.blit(text, (item_rect.x + 4, item_rect.y + 2))
                # When searching across levels, show the spell level as a hint
                if searching:
                    lv = spell.get("level", 0)
                    lv_txt = "C" if lv == 0 else str(lv)
                    hint = self.font_sm.render(lv_txt, True, (140, 140, 170))
                    surf.blit(hint, (item_rect.right - 18, item_rect.y + 2))

        # Scrollbar (only when content overflows)
        max_scroll = self._max_scroll(list_h)
        if max_scroll > 0:
            track_x = list_bg.right - 5
            thumb_h = max(20, int(list_h * list_h / (len(self.filtered_spells) * self.ITEM_H)))
            thumb_y = list_y + int((list_h - thumb_h) * self.scroll_y / max_scroll)
            pygame.draw.rect(surf, (80, 80, 100), pygame.Rect(track_x, thumb_y, 4, thumb_h), border_radius=2)


class ArmorSelectionDialog:
    """Modal dialog for selecting armor pieces from armor.json."""
    ITEM_H = 24
    PAD = 12
    SEARCH_H = 32

    def __init__(self, armors: list, font_sm=None, font_md=None):
        self.all_armors = armors
        self.filtered_armors = armors
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None
        self.search_text = ""
        self._frames_since_show = 0

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        self.search_text = ""
        self._frames_since_show = 0
        self.filtered_armors = self.all_armors[:]
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 400
        dlg_h = 500
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def _update_filtered_armors(self):
        search_lower = self.search_text.lower()
        self.filtered_armors = [a for a in self.all_armors if search_lower in a.get("name", "").lower()]
        self.scroll_y = 0
        self._hover_idx = -1

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dismiss()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.search_text = self.search_text[:-1]
                self._update_filtered_armors()
                return True
            elif event.key == pygame.K_RETURN:
                if len(self.filtered_armors) == 1:
                    if self.selected_callback:
                        self.selected_callback(self.filtered_armors[0])
                    self.dismiss()
                    return True
            elif event.unicode.isprintable():
                self.search_text += event.unicode
                self._update_filtered_armors()
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(*event.pos):
                search_y = self.rect.y + 35
                search_box_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                             self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
                if search_box_rect.collidepoint(*event.pos):
                    return True

                list_y = search_y + self.SEARCH_H
                list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
                for i, armor in enumerate(self.filtered_armors):
                    item_y = list_y + i * self.ITEM_H - self.scroll_y
                    if list_y <= item_y < list_y + list_h:
                        item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                              self.rect.w - self.PAD * 2, self.ITEM_H)
                        if item_rect.collidepoint(*event.pos):
                            if self.selected_callback:
                                self.selected_callback(armor)
                            self.dismiss()
                            return True
            else:
                self.dismiss()
            return True
        elif event.type == pygame.MOUSEMOTION and self.visible:
            search_y = self.rect.y + 35
            list_y = search_y + self.SEARCH_H
            list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
            self._hover_idx = -1
            for i, armor in enumerate(self.filtered_armors):
                item_y = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= item_y < list_y + list_h:
                    item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                          self.rect.w - self.PAD * 2, self.ITEM_H)
                    if item_rect.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEWHEEL and self.visible and self.rect.collidepoint(*pygame.mouse.get_pos()):
            self.scroll_y = max(0, self.scroll_y - event.y * 30)
            max_scroll = max(0, len(self.filtered_armors) * self.ITEM_H - (self.rect.h - self.SEARCH_H - 20))
            self.scroll_y = min(self.scroll_y, max_scroll)
            return True

        return False

    def draw(self, surf: pygame.Surface):
        if not self.visible or not self.rect:
            return

        self._frames_since_show += 1

        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surf.blit(overlay, (0, 0))

        pygame.draw.rect(surf, (50, 50, 60), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)

        title = self.font_md.render("Select Armor", True, (220, 220, 235))
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 8)
        surf.blit(title, title_rect)

        search_y = self.rect.y + 35
        search_box = pygame.Rect(self.rect.x + self.PAD, search_y, self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
        pygame.draw.rect(surf, (30, 30, 40), search_box)
        pygame.draw.rect(surf, (100, 100, 120), search_box, 1)
        search_label = self.font_sm.render(f"Search: {self.search_text}_" if self.visible else f"Search: {self.search_text}", True, (200, 200, 200))
        surf.blit(search_label, (search_box.x + 4, search_box.y + 4))

        list_y = search_y + self.SEARCH_H
        list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
        pygame.draw.rect(surf, (30, 30, 40), pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h))

        for i, armor in enumerate(self.filtered_armors):
            item_y = list_y + i * self.ITEM_H - self.scroll_y
            if list_y <= item_y < list_y + list_h:
                item_rect = pygame.Rect(self.rect.x + self.PAD, item_y, self.rect.w - self.PAD * 2, self.ITEM_H)
                if i == self._hover_idx:
                    pygame.draw.rect(surf, (70, 70, 90), item_rect)
                armor_name = armor.get("name", "Unknown")
                text = self.font_sm.render(armor_name, True, (200, 200, 220))
                surf.blit(text, (item_rect.x + 4, item_rect.y + 2))


class WeaponSelectionDialog:
    """Modal dialog for selecting weapons from weapons.json."""
    ITEM_H = 24
    PAD = 12
    SEARCH_H = 32

    def __init__(self, weapons: list, font_sm=None, font_md=None):
        self.all_weapons = weapons
        self.filtered_weapons = weapons
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None
        self.search_text = ""
        self._frames_since_show = 0

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        self.search_text = ""
        self._frames_since_show = 0
        self.filtered_weapons = self.all_weapons[:]
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 400
        dlg_h = 500
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def _update_filtered_weapons(self):
        search_lower = self.search_text.lower()
        self.filtered_weapons = [w for w in self.all_weapons if search_lower in w.get("name", "").lower()]
        self.scroll_y = 0
        self._hover_idx = -1

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.dismiss()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.search_text = self.search_text[:-1]
                self._update_filtered_weapons()
                return True
            elif event.key == pygame.K_RETURN:
                if len(self.filtered_weapons) == 1:
                    if self.selected_callback:
                        self.selected_callback(self.filtered_weapons[0])
                    self.dismiss()
                    return True
            elif event.unicode.isprintable():
                self.search_text += event.unicode
                self._update_filtered_weapons()
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(*event.pos):
                search_y = self.rect.y + 35
                search_box_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                             self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
                if search_box_rect.collidepoint(*event.pos):
                    return True

                list_y = search_y + self.SEARCH_H
                list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
                for i, weapon in enumerate(self.filtered_weapons):
                    item_y = list_y + i * self.ITEM_H - self.scroll_y
                    if list_y <= item_y < list_y + list_h:
                        item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                              self.rect.w - self.PAD * 2, self.ITEM_H)
                        if item_rect.collidepoint(*event.pos):
                            if self.selected_callback:
                                self.selected_callback(weapon)
                            self.dismiss()
                            return True
            else:
                self.dismiss()
            return True
        elif event.type == pygame.MOUSEMOTION and self.visible:
            search_y = self.rect.y + 35
            list_y = search_y + self.SEARCH_H
            list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
            self._hover_idx = -1
            for i, weapon in enumerate(self.filtered_weapons):
                item_y = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= item_y < list_y + list_h:
                    item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                          self.rect.w - self.PAD * 2, self.ITEM_H)
                    if item_rect.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEWHEEL and self.visible and self.rect.collidepoint(*pygame.mouse.get_pos()):
            self.scroll_y = max(0, self.scroll_y - event.y * 30)
            max_scroll = max(0, len(self.filtered_weapons) * self.ITEM_H - (self.rect.h - self.SEARCH_H - 20))
            self.scroll_y = min(self.scroll_y, max_scroll)
            return True

        return False

    def draw(self, surf: pygame.Surface):
        if not self.visible or not self.rect:
            return

        self._frames_since_show += 1

        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        surf.blit(overlay, (0, 0))

        pygame.draw.rect(surf, (50, 50, 60), self.rect, border_radius=8)
        pygame.draw.rect(surf, (150, 150, 200), self.rect, 2, border_radius=8)

        title = self.font_md.render("Select Weapon", True, (220, 220, 235))
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 8)
        surf.blit(title, title_rect)

        search_y = self.rect.y + 35
        search_box = pygame.Rect(self.rect.x + self.PAD, search_y, self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
        pygame.draw.rect(surf, (30, 30, 40), search_box)
        pygame.draw.rect(surf, (100, 100, 120), search_box, 1)
        search_label = self.font_sm.render(f"Search: {self.search_text}_" if self.visible else f"Search: {self.search_text}", True, (200, 200, 200))
        surf.blit(search_label, (search_box.x + 4, search_box.y + 4))

        list_y = search_y + self.SEARCH_H
        list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
        pygame.draw.rect(surf, (30, 30, 40), pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h))

        for i, weapon in enumerate(self.filtered_weapons):
            item_y = list_y + i * self.ITEM_H - self.scroll_y
            if list_y <= item_y < list_y + list_h:
                item_rect = pygame.Rect(self.rect.x + self.PAD, item_y, self.rect.w - self.PAD * 2, self.ITEM_H)
                if i == self._hover_idx:
                    pygame.draw.rect(surf, (70, 70, 90), item_rect)
                weapon_name = weapon.get("name", "Unknown")
                text = self.font_sm.render(weapon_name, True, (200, 200, 220))
                surf.blit(text, (item_rect.x + 4, item_rect.y + 2))


class ArmorDialog:
    """Dialog for managing armor equipment across all 6 slots."""
    DLG_W = 500
    DLG_H = 450
    PAD = 15
    ITEM_H = 32
    BTN_W = 100
    BTN_H = 28

    C_BG = (35, 35, 50)
    C_BORDER = (120, 120, 160)
    C_LABEL = (180, 180, 200)
    C_SLOT_BG = (25, 25, 40)
    C_SLOT_BORDER = (80, 80, 120)
    C_BUTTON = (70, 70, 100)
    C_BUTTON_H = (90, 90, 130)

    SLOT_NAMES = ["Helmet", "Chest", "Leggings", "Boots", "Gloves", "Cloak"]

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.rect = None
        self.agent_idx = -1
        self.agent_name = ""
        self.current_armor = [{"name": ""} for _ in range(6)]
        self.callback = None
        self._hover_slot = -1
        self.armor_selection_dialog = None

    def open(self, screen, agent_idx: int, agent_name: str, armor_array, armor_selection_dialog, callback):
        self.active = True
        self.agent_idx = agent_idx
        self.agent_name = agent_name
        self.callback = callback
        self.armor_selection_dialog = armor_selection_dialog
        # Convert armor objects to dicts for display
        self.current_armor = [{"name": a.name, "description": a.description} if a.name else {"name": "", "description": ""} 
                              for a in armor_array]
        sw, sh = screen.get_size()
        self.rect = pygame.Rect((sw - self.DLG_W) // 2, (sh - self.DLG_H) // 2, self.DLG_W, self.DLG_H)

    def dismiss(self):
        self.active = False
        if self.callback:
            self.callback()

    def _slot_rect(self, slot_idx: int) -> pygame.Rect:
        y = self.rect.y + 45 + slot_idx * (self.ITEM_H + 5)
        return pygame.Rect(self.rect.x + self.PAD, y, self.DLG_W - self.PAD * 2, self.ITEM_H)

    def handle(self, event, screen) -> bool:
        if not self.active or not self.rect:
            return False

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.dismiss()
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # If armor selection dialog is open, let it handle the event
            if self.armor_selection_dialog.visible:
                return False

            if self.rect.collidepoint(*event.pos):
                # Check close button
                close_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)
                if close_rect.collidepoint(*event.pos):
                    self.dismiss()
                    return True

                # Check slot clicks
                for i in range(6):
                    slot_rect = self._slot_rect(i)
                    if slot_rect.collidepoint(*event.pos):
                        def _on_armor_selected(armor_dict, slot_idx=i):
                            self.current_armor[slot_idx] = armor_dict
                        self.armor_selection_dialog.show(_on_armor_selected)
                        return True
            else:
                self.dismiss()
            return True

        if event.type == pygame.MOUSEMOTION and self.active:
            self._hover_slot = -1
            for i in range(6):
                if self._slot_rect(i).collidepoint(*event.pos):
                    self._hover_slot = i
                    break

        return False

    def draw(self, surf: pygame.Surface):
        if not self.active or not self.rect:
            return

        pygame.draw.rect(surf, self.C_BG, self.rect, border_radius=8)
        pygame.draw.rect(surf, self.C_BORDER, self.rect, 2, border_radius=8)

        # Title
        title = self.font_md.render(f"Armor - {self.agent_name}", True, self.C_LABEL)
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 10)
        surf.blit(title, title_rect)

        # Close button
        close_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)
        pygame.draw.rect(surf, self.C_BUTTON, close_rect)
        close_text = self.font_sm.render("✕", True, (220, 220, 220))
        surf.blit(close_text, close_text.get_rect(center=close_rect.center))

        # Slots
        for i, slot_name in enumerate(self.SLOT_NAMES):
            slot_rect = self._slot_rect(i)
            color = self.C_BUTTON_H if i == self._hover_slot else self.C_SLOT_BG
            pygame.draw.rect(surf, color, slot_rect, border_radius=4)
            pygame.draw.rect(surf, self.C_SLOT_BORDER, slot_rect, 1, border_radius=4)

            # Slot label
            label = self.font_sm.render(f"{slot_name}:", True, self.C_LABEL)
            surf.blit(label, (slot_rect.x + 8, slot_rect.y + 4))

            # Current armor name
            armor_name = self.current_armor[i].get("name", "—")
            armor_text = self.font_sm.render(armor_name if armor_name else "—", True, (200, 200, 220))
            surf.blit(armor_text, (slot_rect.x + 120, slot_rect.y + 4))


class WeaponsDialog:
    """Dialog for managing a variable-length weapon / "Attack N" list.

    By convention index 0 = Main Hand, 1 = Off Hand, 2 = Ranged (labelled as hints on
    the first three rows for PC clarity); rows 4+ are extra attacks a monster's
    multiattack recipe can reference. Rows can be added (＋ Add Attack) and removed (✕).
    On save the caller drops trailing empties and the engine pads back to >=3."""
    DLG_W = 560
    PAD = 15
    ITEM_H = 32
    ROW_GAP = 5
    BTN_H = 28

    C_BG = (35, 35, 50)
    C_BORDER = (120, 120, 160)
    C_LABEL = (180, 180, 200)
    C_SLOT_BG = (25, 25, 40)
    C_SLOT_BORDER = (80, 80, 120)
    C_BUTTON = (70, 70, 100)
    C_BUTTON_H = (90, 90, 130)
    C_REMOVE = (150, 70, 70)
    C_REMOVE_H = (190, 90, 90)
    C_ADD = (70, 120, 90)
    C_ADD_H = (90, 150, 110)

    # First three rows carry the PC main/off/ranged convention as a hint.
    SLOT_HINTS = ["Main Hand", "Off Hand", "Ranged"]

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.rect = None
        self.agent_idx = -1
        self.agent_name = ""
        self.current_weapons = [{"name": ""}, {"name": ""}, {"name": ""}]  # >=3 slots
        self.callback = None
        self._hover_slot = -1
        self.weapon_selection_dialog = None

    def _row_label(self, i: int) -> str:
        base = f"Attack {i + 1}"
        if i < len(self.SLOT_HINTS):
            return f"{base} ({self.SLOT_HINTS[i]})"
        return base

    def _recompute_rect(self, screen):
        # Height grows with the row count + header + add button.
        n = len(self.current_weapons)
        body = 45 + n * (self.ITEM_H + self.ROW_GAP) + self.BTN_H + self.PAD * 2
        h = max(body, 160)
        sw, sh = screen.get_size()
        self.rect = pygame.Rect((sw - self.DLG_W) // 2, max(20, (sh - h) // 2), self.DLG_W, h)

    def open(self, screen, agent_idx: int, agent_name: str, weapon_array, weapon_selection_dialog, callback, combat_engine=None, battle_map=None):
        self.active = True
        self.agent_idx = agent_idx
        self.agent_name = agent_name
        self.callback = callback
        self.weapon_selection_dialog = weapon_selection_dialog
        # Store full weapon dicts (including mastery, bonus_hit, conditions, etc.)
        # so that weapon properties survive the dialog round-trip.
        from helpers import _weapon_to_dict
        self.current_weapons = [_weapon_to_dict(w) for w in weapon_array]
        while len(self.current_weapons) < 3:
            self.current_weapons.append({"name": ""})
        self._recompute_rect(screen)

    def dismiss(self):
        self.active = False
        if self.callback:
            self.callback()

    def _slot_rect(self, slot_idx: int) -> pygame.Rect:
        # Name area: leaves room on the right for the [off] toggle + [✕] remove button.
        y = self.rect.y + 45 + slot_idx * (self.ITEM_H + self.ROW_GAP)
        return pygame.Rect(self.rect.x + self.PAD, y, self.DLG_W - self.PAD * 2 - 120, self.ITEM_H)

    def _offhand_rect(self, slot_idx: int) -> pygame.Rect:
        sr = self._slot_rect(slot_idx)
        return pygame.Rect(sr.right + 6, sr.y, 78, self.ITEM_H)

    def _remove_rect(self, slot_idx: int) -> pygame.Rect:
        sr = self._slot_rect(slot_idx)
        return pygame.Rect(self.rect.right - self.PAD - 28, sr.y, 28, self.ITEM_H)

    def _add_rect(self) -> pygame.Rect:
        n = len(self.current_weapons)
        y = self.rect.y + 45 + n * (self.ITEM_H + self.ROW_GAP)
        return pygame.Rect(self.rect.x + self.PAD, y, 140, self.BTN_H)

    def handle(self, event, screen) -> bool:
        if not self.active or not self.rect:
            return False

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.dismiss()
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # If weapon selection dialog is open, let it handle the event
            if self.weapon_selection_dialog.visible:
                return False

            if self.rect.collidepoint(*event.pos):
                # Check close button
                close_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)
                if close_rect.collidepoint(*event.pos):
                    self.dismiss()
                    return True

                # Add-attack button
                if self._add_rect().collidepoint(*event.pos):
                    self.current_weapons.append({"name": ""})
                    self._recompute_rect(screen)
                    return True

                # Per-row controls
                for i in range(len(self.current_weapons)):
                    # Remove button
                    if self._remove_rect(i).collidepoint(*event.pos):
                        del self.current_weapons[i]
                        while len(self.current_weapons) < 3:
                            self.current_weapons.append({"name": ""})
                        self._recompute_rect(screen)
                        return True
                    # Off-hand toggle (not meaningful for the ranged hint row, but allowed)
                    if self._offhand_rect(i).collidepoint(*event.pos):
                        cur = bool(self.current_weapons[i].get("off_hand", False))
                        self.current_weapons[i]["off_hand"] = not cur
                        return True
                    # Name area → weapon selection
                    if self._slot_rect(i).collidepoint(*event.pos):
                        if i == 1 and self.current_weapons[0].get("two_handed", False):
                            # Off-hand disabled when main hand is two-handed
                            return True

                        def _on_weapon_selected(weapon_dict, slot_idx=i):
                            self.current_weapons[slot_idx] = weapon_dict

                        self.weapon_selection_dialog.show(_on_weapon_selected)
                        return True
            else:
                self.dismiss()
            return True

        if event.type == pygame.MOUSEMOTION and self.active:
            self._hover_slot = -1
            for i in range(len(self.current_weapons)):
                if self._slot_rect(i).collidepoint(*event.pos):
                    if i == 1 and self.current_weapons[0].get("two_handed", False):
                        continue
                    self._hover_slot = i
                    break

        return False

    def draw(self, surf: pygame.Surface):
        if not self.active or not self.rect:
            return

        pygame.draw.rect(surf, self.C_BG, self.rect, border_radius=8)
        pygame.draw.rect(surf, self.C_BORDER, self.rect, 2, border_radius=8)

        # Title
        title = self.font_md.render(f"Weapons - {self.agent_name}", True, self.C_LABEL)
        title_rect = title.get_rect(x=self.rect.x + self.PAD, y=self.rect.y + 10)
        surf.blit(title, title_rect)

        # Close button
        close_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 10, 20, 20)
        pygame.draw.rect(surf, self.C_BUTTON, close_rect)
        close_text = self.font_sm.render("✕", True, (220, 220, 220))
        surf.blit(close_text, close_text.get_rect(center=close_rect.center))

        # Rows
        for i in range(len(self.current_weapons)):
            slot_rect = self._slot_rect(i)

            # If this is the off-hand row and main hand is two-handed, disable it
            disabled = (i == 1 and self.current_weapons[0].get("two_handed", False))

            if disabled:
                color = (45, 45, 60)  # Dimmed
                border_color = (60, 60, 80)
            else:
                color = self.C_BUTTON_H if i == self._hover_slot else self.C_SLOT_BG
                border_color = self.C_SLOT_BORDER

            pygame.draw.rect(surf, color, slot_rect, border_radius=4)
            pygame.draw.rect(surf, border_color, slot_rect, 1, border_radius=4)

            # Row label
            label = self.font_sm.render(f"{self._row_label(i)}:", True, self.C_LABEL)
            surf.blit(label, (slot_rect.x + 8, slot_rect.y + 4))

            # Current weapon name
            weapon_name = self.current_weapons[i].get("name", "")
            weapon_text = self.font_sm.render(weapon_name if weapon_name else "—", True, (200, 200, 220))
            surf.blit(weapon_text, (slot_rect.x + 160, slot_rect.y + 4))

            # Off-hand toggle
            off_rect = self._offhand_rect(i)
            is_off = bool(self.current_weapons[i].get("off_hand", False))
            pygame.draw.rect(surf, (60, 90, 60) if is_off else (50, 50, 65), off_rect, border_radius=4)
            pygame.draw.rect(surf, self.C_SLOT_BORDER, off_rect, 1, border_radius=4)
            off_txt = self.font_sm.render("off ✓" if is_off else "off", True,
                                          (200, 220, 200) if is_off else (150, 150, 170))
            surf.blit(off_txt, off_txt.get_rect(center=off_rect.center))

            # Remove button
            rm_rect = self._remove_rect(i)
            pygame.draw.rect(surf, self.C_REMOVE, rm_rect, border_radius=4)
            rm_txt = self.font_sm.render("✕", True, (230, 220, 220))
            surf.blit(rm_txt, rm_txt.get_rect(center=rm_rect.center))

        # Add-attack button
        add_rect = self._add_rect()
        pygame.draw.rect(surf, self.C_ADD, add_rect, border_radius=4)
        add_txt = self.font_sm.render("＋ Add Attack", True, (220, 240, 220))
        surf.blit(add_txt, add_txt.get_rect(center=add_rect.center))
