#!/usr/bin/env python3
"""
RPG Battle Map Viewer
─────────────────────
Usage:  python main.py <map_image.png>

Left panel  – the battle map with grid / wall / agent overlays
Right panel – agent configuration GUI (add / remove / place agents)
"""

import sys
import os
import json

os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pygame.gfxdraw

import textwrap
import copy
import read_stats_from_csv

# ── Import the C++ analysis core ──────────────────────────────────────────────
try:
    import rpg_battle_map as rpg
except ModuleNotFoundError:
    sys.exit(
        "ERROR: rpg_battle_map module not found.\n"
        "Build it first:  cmake --build build && cmake --install build"
    )

# ─────────────────────────────────────────────────────────────────────────────
#  Colour palette
# ─────────────────────────────────────────────────────────────────────────────
COL_BG          = (30,  30,  30)
COL_PANEL_BG    = (45,  45,  55)
COL_PANEL_BORDER= (80,  80, 100)
COL_GRID        = (255, 255, 255, 60)     # semi-transparent
COL_WALL        = (200,  60,  60, 220)
COL_BLOCKED     = (0,    0,   0, 100)
COL_AGENT_FILL  = (100, 149, 237, 210)    # cornflower blue placeholder
COL_AGENT_BORDER= (255, 255, 255, 255)
COL_TEXT        = (220, 220, 220)
COL_LABEL       = (170, 170, 200)
COL_BTN         = (70,  90, 130)
COL_BTN_HOVER   = (90, 115, 165)
COL_BTN_DANGER  = (130,  50,  50)
COL_INPUT_BG    = (35,  35,  45)
COL_INPUT_ACTIVE= (55,  55,  75)

# ── Combat panel colours ──────────────────────────────────────────────────────
COL_INITIATIVE_CUR  = (255, 210,  50)   # gold — current combatant row
COL_HP_HIGH         = ( 60, 200,  80)   # green  – > 66 % HP
COL_HP_MID          = (230, 180,  40)   # amber  – 33–66 % HP
COL_HP_LOW          = (220,  60,  60)   # red    – < 33 % HP
COL_BTN_COMBAT      = (140,  75,  15)   # orange-brown "Begin Combat"
COL_BTN_COMBAT_HOV  = (180, 100,  25)
COL_BTN_ATK         = ( 55, 140,  60)   # green attack button
COL_BTN_ATK_HOV     = ( 80, 170,  85)
COL_BTN_PASS        = ( 65,  65,  88)   # grey-blue pass button
COL_BTN_PASS_HOV    = ( 88,  88, 115)
COL_BTN_ENDTURN     = ( 45,  95, 150)   # blue end-turn
COL_BTN_ENDTURN_HOV = ( 65, 120, 185)
COL_BTN_DASH        = ( 50,  95, 160)   # blue – dash
COL_BTN_DASH_HOV    = ( 75, 120, 195)
COL_BTN_DODGE       = ( 35, 115, 105)   # teal – dodge
COL_BTN_DODGE_HOV   = ( 55, 145, 135)
COL_BTN_DISENG      = (130,  90,  20)   # amber – disengage
COL_BTN_DISENG_HOV  = (165, 120,  35)
COL_BTN_SPELL       = ( 90,  50, 145)   # purple – cast spell
COL_BTN_SPELL_HOV   = (120,  75, 180)

PANEL_W   = 340       # right-side config panel width
MAP_MARGIN = 0        # pixel margin around map inside left area
FONT_SM   = 14
FONT_MD   = 16
FONT_LG   = 20

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tga'}
JSON_EXTS  = {'.json'}

# ─────────────────────────────────────────────────────────────────────────────
#  File browser modal
# ─────────────────────────────────────────────────────────────────────────────
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
        self._title     = ""
        self._filename  = ""     # editable in save mode
        self._fn_active = False  # filename input focused

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, start_dir: str, callback, *,
             save_mode: bool = False,
             extensions=None,
             default_filename: str = ""):
        if not os.path.isdir(start_dir):
            start_dir = os.path.dirname(start_dir) or "/"
        self.cwd        = os.path.abspath(start_dir)
        self._cb        = callback
        self.active     = True
        self.save_mode  = save_mode
        self.extensions = extensions if extensions is not None else (
            JSON_EXTS if save_mode else IMAGE_EXTS)
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


class StatsDialog:
    """
    Modal dialog showing and editing D&D 5.5e stats for a placed agent.
    Right-click an agent on the map to open.
    Callback: callback(agent_idx, new_stats_obj) called on OK.
    """
    DLG_W = 610
    DLG_H = 560
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

    # Ordered ability-score fields
    ABILITIES = [
        ("STR", "str"),  ("DEX", "dex"), ("CON", "con"),
        ("INT", "intel"),("WIS", "wis"), ("CHA", "cha"),
    ]
    COMBAT = [
        ("Current HP",    "hp_cur",       0, 999),
        ("Max HP",        "hp_max",       1, 999),
        ("Armor Class",   "ac",           1,  30),
        ("Walk (ft)",     "speed_walk",   0, 120),
        ("Swim (ft)",     "speed_swim",   0, 120),
        ("Fly (ft)",      "speed_fly",    0, 120),
        ("Burrow (ft)",   "speed_burrow", 0, 120),
        ("Prof. Bonus",   "prof_bonus",   2,   6),
        ("# Attacks",     "num_attacks",  1,  10),
    ]

    def __init__(self, font_sm, font_md, font_lg):
        self.font_sm = font_sm
        self.font_md = font_md
        self.font_lg = font_lg
        self.active              = False
        self._agent_idx          = -1
        self._agent_name         = ""
        self._cb                 = None
        self.steppers: dict      = {}   # populated in open()
        self.prof_flags: dict    = {}   # save_prof_<ability> -> bool
        self._prof_rects: dict   = {}   # same keys -> pygame.Rect

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, screen, agent_idx: int, agent_name: str, stats, callback):
        self.active      = True
        self._agent_idx  = agent_idx
        self._agent_name = agent_name
        self._cb         = callback
        self._build_steppers(self._dlg(screen), stats)

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

    # ── events ───────────────────────────────────────────────────────────────
    def handle(self, event, screen) -> bool:
        if not self.active:
            return False
        dlg = self._dlg(screen)

        # Let steppers see every event first so a focused field can consume
        # Escape/Enter before the dialog itself acts on Escape.
        any_field_active = any(st._active for st in self.steppers.values())
        for st in self.steppers.values():
            st.handle(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and not any_field_active:
                self.active = False
                return True
            if event.key == pygame.K_RETURN and not any_field_active:
                self._confirm()
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Proficiency checkboxes
            for flag_key, rect in self._prof_rects.items():
                if rect.collidepoint(event.pos):
                    self.prof_flags[flag_key] = not self.prof_flags[flag_key]
            if self._ok_rect(dlg).collidepoint(event.pos):
                self._confirm()
            elif self._cancel_rect(dlg).collidepoint(event.pos):
                self.active = False
            return True
        return event.type in (pygame.MOUSEMOTION, pygame.MOUSEWHEEL)

    def _confirm(self):
        if self._cb and self._agent_idx >= 0:
            self._cb(self._agent_idx, self.steppers, self.prof_flags)
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

        # ── Combat Stats section ──────────────────────────────────────────
        half = (self.DLG_W - PAD * 3) // 2
        if "hp_cur" in self.steppers:
            cs_y = self.steppers["hp_cur"].rect.y - 18 - 10
            t = self.font_sm.render("COMBAT STATS", True, self.C_SECT)
            screen.blit(t, (dlg.x + PAD, cs_y))

        for lbl, key, _, _ in self.COMBAT:
            st = self.steppers.get(key)
            if st:
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

    def __init__(self, mobs: list[str], font_sm=None, font_md=None):
        self.mobs = mobs
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        # Center dialog on screen
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 400
        dlg_h = 500
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(*event.pos):
                list_y = self.rect.y + 40
                list_h = self.rect.h - 50
                for i, mob in enumerate(self.mobs):
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
            list_y = self.rect.y + 40
            list_h = self.rect.h - 50
            self._hover_idx = -1
            for i, mob in enumerate(self.mobs):
                item_y = list_y + i * self.ITEM_H - self.scroll_y
                if list_y <= item_y < list_y + list_h:
                    item_rect = pygame.Rect(self.rect.x + self.PAD, item_y,
                                          self.rect.w - self.PAD * 2, self.ITEM_H)
                    if item_rect.collidepoint(*event.pos):
                        self._hover_idx = i
                        break
        elif event.type == pygame.MOUSEWHEEL and self.visible and self.rect.collidepoint(*pygame.mouse.get_pos()):
            self.scroll_y = max(0, self.scroll_y - event.y * 30)
            max_scroll = max(0, len(self.mobs) * self.ITEM_H - (self.rect.h - 50))
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

        # List area
        list_y = self.rect.y + 40
        list_h = self.rect.h - 50
        list_rect = pygame.Rect(self.rect.x + self.PAD, list_y,
                               self.rect.w - self.PAD * 2, list_h)
        pygame.draw.rect(surf, (30, 30, 40), list_rect)

        # Draw mobs
        for i, mob in enumerate(self.mobs):
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


# ─────────────────────────────────────────────────────────────────────────────
#  Weapon dialog
# ─────────────────────────────────────────────────────────────────────────────

def _parse_physical_damage(v):
    """Accept a string name or int ordinal, return rpg.PhysicalDamage."""
    if isinstance(v, str):
        return getattr(rpg.PhysicalDamage, v)
    return rpg.PhysicalDamage(int(v))

def _parse_magic_damage(v):
    """Accept a string name or int ordinal, return rpg.MagicDamage."""
    if isinstance(v, str):
        return getattr(rpg.MagicDamage, v)
    return rpg.MagicDamage(int(v))


# Template for a freshly-created weapon (as a plain dict for the dialog).
_DEFAULT_WEAPON: dict = {
    "name":            "New Weapon",
    "type":            "melee",    # "melee" | "ranged"
    "reach_ft":        5,          # melee reach in feet (5 / 10 / 15)
    "normal_range_ft": 80,         # ranged: normal range in feet
    "long_range_ft":   320,        # ranged: long range in feet
    "finesse":         False,
    "thrown":          False,
    "proficient":      True,
    "num_dice":        1,          # e.g. 1d6 → num_dice=1, die_size=6
    "die_size":        6,
    "physical_damages": ["Slashing"],
    "magic_damages":    [],
}


def _weapon_to_dict(w) -> dict:
    """Convert an rpg.Weapon object to a plain dict for dialog editing."""
    return {
        "name":             w.name,
        "type":             "melee" if w.type == rpg.WeaponType.Melee else "ranged",
        "reach_ft":         w.reach_ft,
        "normal_range_ft":  w.normal_range_ft,
        "long_range_ft":    w.long_range_ft,
        "finesse":          w.finesse,
        "thrown":           w.thrown,
        "proficient":       w.proficient,
        "num_dice":         w.num_dice,
        "die_size":         w.die_size,
        "physical_damages": [v.name for v in w.physical_damages],
        "magic_damages":    [v.name for v in w.magic_damages],
    }


def _dict_to_weapon(d: dict):
    """Convert a plain dict to an rpg.Weapon object."""
    w = rpg.Weapon()
    w.name            = d.get("name",            "Unnamed")
    w.type            = (rpg.WeaponType.Melee
                         if d.get("type", "melee") == "melee"
                         else rpg.WeaponType.Ranged)
    w.reach_ft        = int(d.get("reach_ft",        5))
    w.normal_range_ft = int(d.get("normal_range_ft", 80))
    w.long_range_ft   = int(d.get("long_range_ft",   320))
    w.finesse         = bool(d.get("finesse",         False))
    w.thrown          = bool(d.get("thrown",          False))
    w.proficient      = bool(d.get("proficient",      True))
    w.num_dice        = int(d.get("num_dice",  1))
    w.die_size        = int(d.get("die_size",  6))
    w.physical_damages = [_parse_physical_damage(v)
                          for v in d.get("physical_damages", ["Slashing"])]
    w.magic_damages    = [_parse_magic_damage(v)
                          for v in d.get("magic_damages",    [])]
    return w


class WeaponDialog:
    """Modal dialog for editing an agent's weapon list."""

    DLG_W  = 510
    DLG_H  = 550
    HDR_H  = 36
    BTN_H  = 28
    PAD    = 14
    TAB_H  = 30
    ROW_H  = 32        # height of a form row
    FIELD_H= 24        # height of a text-input rect

    # Reach options for melee weapons (feet)
    REACH_OPTIONS = [5, 10, 15]

    def __init__(self, font_sm, font_md, font_lg):
        self.active      = False
        self._font_sm    = font_sm
        self._font_md    = font_md
        self._font_lg    = font_lg

        self._agent_idx  = -1
        self._agent_name = ""
        self._weapons: list[dict] = []
        self._sel        = -1       # currently selected weapon index
        self._cb         = None     # callback(agent_idx, weapons)

        self._rect: pygame.Rect | None = None

        # ── Per-field "active" text-input state ──────────────────────────
        # Each entry: field_key -> (rect, current_text)
        # We only allow one field active at a time.
        self._active_field: str | None = None

        # Live-editing copies of the selected weapon's fields:
        self._f: dict = {}          # populated by _load_form()

        # Rects computed in draw (so handle() can use them without re-drawing)
        self._rects: dict = {}      # key -> pygame.Rect

    # ── Public API ───────────────────────────────────────────────────────────
    def open(self, screen, agent_idx: int, agent_name: str,
             weapons: list[dict], callback):
        import copy
        self.active      = True
        self._agent_idx  = agent_idx
        self._agent_name = agent_name
        self._weapons    = copy.deepcopy(weapons)
        self._cb         = callback
        self._active_field = None
        self._rects      = {}

        sw, sh = screen.get_size()
        x = (sw - self.DLG_W) // 2
        y = (sh - self.DLG_H) // 2
        self._rect = pygame.Rect(x, y, self.DLG_W, self.DLG_H)

        if self._weapons:
            self._sel = 0
        else:
            self._sel = -1
        self._load_form()

    # ── Internal helpers ─────────────────────────────────────────────────────
    def _load_form(self):
        """Copy selected weapon into editable form dict."""
        import copy
        if 0 <= self._sel < len(self._weapons):
            self._f = copy.deepcopy(self._weapons[self._sel])
        else:
            self._f = {}
        self._active_field = None

    def _save_form(self):
        """Write form dict back into the weapon list."""
        if 0 <= self._sel < len(self._weapons):
            self._weapons[self._sel] = dict(self._f)

    def _add_weapon(self):
        import copy
        self._save_form()
        self._weapons.append(copy.deepcopy(_DEFAULT_WEAPON))
        self._sel = len(self._weapons) - 1
        self._load_form()

    def _remove_weapon(self):
        if 0 <= self._sel < len(self._weapons):
            self._weapons.pop(self._sel)
            self._sel = min(self._sel, len(self._weapons) - 1)
            self._load_form()

    def _confirm(self):
        self._save_form()
        if self._cb:
            self._cb(self._agent_idx, self._weapons)
        self.active = False

    # ── Event handling ───────────────────────────────────────────────────────
    def handle(self, event, screen) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            af = self._active_field
            if af == "name":
                if event.key == pygame.K_BACKSPACE:
                    self._f[af] = self._f.get(af, "")[:-1]
                elif event.key == pygame.K_RETURN:
                    self._active_field = None
                elif event.key == pygame.K_ESCAPE:
                    self._active_field = None
                elif event.unicode and event.unicode.isprintable():
                    self._f[af] = self._f.get(af, "") + event.unicode
                return True
            if af in ("normal_range_ft", "long_range_ft", "num_dice", "die_size"):
                cur = str(self._f.get(af, ""))
                if event.key == pygame.K_BACKSPACE:
                    cur = cur[:-1]
                    self._f[af] = int(cur) if cur.isdigit() else 0
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self._active_field = None
                elif event.unicode.isdigit():
                    cur += event.unicode
                    self._f[af] = int(cur)
                return True
            if event.key == pygame.K_ESCAPE:
                self._confirm()     # treat Escape as Done (saves)
                return True
            if event.key == pygame.K_RETURN:
                self._confirm()
                return True

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return True             # block all non-left-click events

        mx, my = event.pos
        r = self._rect
        if not r:
            return True

        # ── Click outside → Done ──────────────────────────────────────────
        if not r.collidepoint(mx, my):
            self._confirm()
            return True

        # Deactivate any text field by default; re-activate below if a
        # text-field rect is clicked.
        prev_active = self._active_field
        self._active_field = None

        # ── Weapon tabs ───────────────────────────────────────────────────
        if "tab" in self._rects:
            for i, tr in enumerate(self._rects["tab"]):
                if tr.collidepoint(mx, my):
                    self._save_form()
                    self._sel = i
                    self._load_form()
                    return True

        # "+ Add" button
        if "add" in self._rects and self._rects["add"].collidepoint(mx, my):
            self._add_weapon()
            return True

        # ── Form field clicks (only if a weapon is selected) ──────────────
        if self._f:
            # Type toggle: melee / ranged
            for k in ("type_melee", "type_ranged"):
                if k in self._rects and self._rects[k].collidepoint(mx, my):
                    self._f["type"] = "melee" if k == "type_melee" else "ranged"
                    return True

            # Reach buttons (melee)
            for ft in self.REACH_OPTIONS:
                key = f"reach_{ft}"
                if key in self._rects and self._rects[key].collidepoint(mx, my):
                    self._f["reach_ft"] = ft
                    return True

            # Checkbox flags
            for flag in ("finesse", "thrown", "proficient"):
                if flag in self._rects and self._rects[flag].collidepoint(mx, my):
                    self._f[flag] = not self._f.get(flag, False)
                    return True

            # Text / numeric input fields
            for field_key in ("name", "normal_range_ft", "long_range_ft",
                               "num_dice", "die_size"):
                if field_key in self._rects and \
                        self._rects[field_key].collidepoint(mx, my):
                    self._active_field = field_key
                    return True

            # Damage type multi-toggles (physical and magic)
            for key, enum_cls, attr in (
                    ("physical_damages", rpg.PhysicalDamage,
                     [rpg.PhysicalDamage.Bludgeoning, rpg.PhysicalDamage.Piercing, rpg.PhysicalDamage.Slashing]),
                    ("magic_damages", rpg.MagicDamage,
                     [rpg.MagicDamage.Acid, rpg.MagicDamage.Cold, rpg.MagicDamage.Fire,
                      rpg.MagicDamage.Force, rpg.MagicDamage.Lightning, rpg.MagicDamage.Necrotic,
                      rpg.MagicDamage.Poison, rpg.MagicDamage.Psychic, rpg.MagicDamage.Radiant,
                      rpg.MagicDamage.Thunder]),
            ):
                for val in attr:
                    rkey = f"{key}_{val.name}"
                    if rkey in self._rects and self._rects[rkey].collidepoint(mx, my):
                        cur = list(self._f.get(key, []))
                        if val.name in cur:
                            cur.remove(val.name)
                        else:
                            cur.append(val.name)
                        self._f[key] = cur
                        return True

        # REMOVE button
        if "remove" in self._rects and self._rects["remove"].collidepoint(mx, my):
            self._remove_weapon()
            return True

        # DONE button
        if "done" in self._rects and self._rects["done"].collidepoint(mx, my):
            self._confirm()
            return True

        return True   # consume all clicks inside the dialog

    # ── Drawing ──────────────────────────────────────────────────────────────
    def draw(self, screen):
        if not self.active or not self._rect:
            return

        r   = self._rect
        PAD = self.PAD
        W   = self.DLG_W

        # Darken background.
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        screen.blit(overlay, (0, 0))

        # Dialog body.
        pygame.draw.rect(screen, (40, 42, 54), r, border_radius=6)
        pygame.draw.rect(screen, (100, 100, 140), r, 2, border_radius=6)

        # ── Header ───────────────────────────────────────────────────────
        hdr = pygame.Rect(r.x, r.y, W, self.HDR_H)
        pygame.draw.rect(screen, (55, 58, 78), hdr,
                         border_top_left_radius=6, border_top_right_radius=6)
        title_s = self._font_lg.render(
            f"⚔ WEAPONS — {self._agent_name}", True, (220, 220, 235))
        screen.blit(title_s, (r.x + PAD, r.y + (self.HDR_H - title_s.get_height()) // 2))

        cy = r.y + self.HDR_H + PAD   # running vertical cursor

        # ── Weapon tabs + [+ Add] ─────────────────────────────────────────
        tab_rects = []
        tx        = r.x + PAD
        TAB_H     = self.TAB_H
        tab_max_w = W - PAD * 2 - 60   # leave room for [+ Add]
        tab_w     = min(120, max(60, tab_max_w // max(len(self._weapons), 1)))

        for i, w in enumerate(self._weapons):
            tr = pygame.Rect(tx + i * (tab_w + 3), cy, tab_w, TAB_H)
            tab_rects.append(tr)
            active = (i == self._sel)
            pygame.draw.rect(screen,
                             (70, 110, 170) if active else (55, 58, 78),
                             tr, border_radius=4)
            pygame.draw.rect(screen, (100, 130, 200) if active else (80, 80, 110),
                             tr, 1, border_radius=4)
            label = self._font_sm.render(
                w.get("name", "?")[:14], True,
                (230, 230, 255) if active else (170, 170, 200))
            screen.blit(label, (tr.x + 4, tr.centery - label.get_height() // 2))

        self._rects["tab"] = tab_rects

        # [+ Add] button
        add_r = pygame.Rect(r.right - PAD - 52, cy, 52, TAB_H)
        pygame.draw.rect(screen, (55, 85, 55), add_r, border_radius=4)
        pygame.draw.rect(screen, (80, 130, 80), add_r, 1, border_radius=4)
        add_lbl = self._font_md.render("+ Add", True, (180, 240, 180))
        screen.blit(add_lbl, (add_r.x + 6, add_r.centery - add_lbl.get_height() // 2))
        self._rects["add"] = add_r

        cy += TAB_H + PAD

        # Divider
        pygame.draw.line(screen, (80, 80, 110),
                         (r.x + PAD, cy), (r.right - PAD, cy))
        cy += 10

        # ── Form (only if a weapon is selected) ───────────────────────────
        if self._f:
            lx = r.x + PAD    # left edge of form content
            RW = W - PAD * 2  # row width
            FH = self.FIELD_H

            def label(text, x, y):
                s = self._font_sm.render(text, True, (150, 150, 180))
                screen.blit(s, (x, y))

            def text_field(key, x, y, w, h=FH):
                rect = pygame.Rect(x, y, w, h)
                active = self._active_field == key
                pygame.draw.rect(screen,
                                 (60, 62, 78) if active else (35, 36, 48),
                                 rect, border_radius=3)
                pygame.draw.rect(screen,
                                 (130, 160, 220) if active else (80, 80, 110),
                                 rect, 1, border_radius=3)
                val = str(self._f.get(key, ""))
                ts  = self._font_md.render(val, True, (220, 220, 235))
                screen.blit(ts, (rect.x + 4, rect.centery - ts.get_height() // 2))
                if active:          # cursor
                    cx_cur = rect.x + 4 + ts.get_width() + 1
                    pygame.draw.line(screen, (200, 200, 220),
                                     (cx_cur, rect.y + 3),
                                     (cx_cur, rect.bottom - 3))
                self._rects[key] = rect
                return rect

            def toggle_btn(key, value, label_text, x, y, w=80, h=FH):
                active = self._f.get(key) == value
                rect   = pygame.Rect(x, y, w, h)
                pygame.draw.rect(screen,
                                 (60, 100, 160) if active else (48, 48, 64),
                                 rect, border_radius=4)
                pygame.draw.rect(screen,
                                 (110, 150, 220) if active else (75, 75, 100),
                                 rect, 1, border_radius=4)
                ts = self._font_md.render(label_text, True,
                                          (230, 235, 255) if active else (150, 150, 180))
                screen.blit(ts, (rect.x + (w - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                # Store using a composite key so melee/ranged can share the "type" key
                self._rects[f"{key}_{value}"] = rect

            def checkbox(key, x, y, label_text, size=18):
                rect  = pygame.Rect(x, y, size, size)
                val   = self._f.get(key, False)
                pygame.draw.rect(screen,
                                 (45, 45, 60) if not val else (40, 90, 50),
                                 rect, border_radius=3)
                pygame.draw.rect(screen,
                                 (100, 150, 110) if val else (80, 80, 105),
                                 rect, 1, border_radius=3)
                if val:
                    pygame.draw.line(screen, (100, 240, 120),
                                     (rect.x + 3, rect.centery),
                                     (rect.x + size // 2 - 1, rect.bottom - 4), 2)
                    pygame.draw.line(screen, (100, 240, 120),
                                     (rect.x + size // 2 - 1, rect.bottom - 4),
                                     (rect.right - 3, rect.y + 3), 2)
                self._rects[key] = rect
                lbl = self._font_md.render(label_text, True, (200, 200, 220))
                screen.blit(lbl, (rect.right + 5,
                                  rect.centery - lbl.get_height() // 2))
                return rect

            # ── Name ───────────────────────────────────────────────────────
            label("Name", lx, cy)
            cy += 14
            text_field("name", lx, cy, RW)
            cy += FH + PAD

            # ── Type ───────────────────────────────────────────────────────
            label("Type", lx, cy)
            cy += 14
            toggle_btn("type", "melee",  "MELEE",  lx,           cy, 90)
            toggle_btn("type", "ranged", "RANGED", lx + 96,      cy, 90)
            cy += FH + PAD

            wtype = self._f.get("type", "melee")

            if wtype == "melee":
                # ── Reach ─────────────────────────────────────────────────
                label("Reach", lx, cy)
                cy += 14
                for i, ft in enumerate(self.REACH_OPTIONS):
                    lbl_text = f"{ft} ft"
                    bw = 70
                    bx = lx + i * (bw + 6)
                    rect = pygame.Rect(bx, cy, bw, FH)
                    active = self._f.get("reach_ft") == ft
                    pygame.draw.rect(screen,
                                     (60, 100, 160) if active else (48, 48, 64),
                                     rect, border_radius=4)
                    pygame.draw.rect(screen,
                                     (110, 150, 220) if active else (75, 75, 100),
                                     rect, 1, border_radius=4)
                    ts = self._font_md.render(lbl_text, True,
                                              (230, 235, 255) if active else (150, 150, 180))
                    screen.blit(ts, (rect.x + (bw - ts.get_width()) // 2,
                                     rect.centery - ts.get_height() // 2))
                    self._rects[f"reach_{ft}"] = rect
                cy += FH + PAD

            else:
                # ── Ranged distances ──────────────────────────────────────
                label("Normal range (ft)", lx, cy)
                label("Long range (ft)", lx + RW // 2 + 6, cy)
                cy += 14
                text_field("normal_range_ft", lx,              cy, RW // 2 - 4)
                text_field("long_range_ft",   lx + RW // 2 + 4, cy, RW // 2 - 4)
                cy += FH + PAD

            # ── Modifiers row (checkboxes) ─────────────────────────────────
            label("Modifiers", lx, cy)
            cy += 14
            CB_STRIDE = 140
            checkbox("finesse",   lx,                cy, "Finesse")
            checkbox("thrown",    lx + CB_STRIDE,    cy, "Thrown")
            checkbox("proficient",lx + CB_STRIDE * 2,cy, "Proficient")
            cy += 24 + PAD

            # ── Damage ─────────────────────────────────────────────────────
            label("Damage (NdX)", lx, cy)
            cy += 14
            text_field("num_dice", lx,      cy, 40)
            ds = self._font_md.render("d", True, (170, 170, 200))
            screen.blit(ds, (lx + 44, cy + (FH - ds.get_height()) // 2))
            text_field("die_size", lx + 54, cy, 50)
            cy += FH + 8

            # ── Physical damage types ───────────────────────────────────────
            label("Physical type", lx, cy)
            cy += 14
            phys_entries = [
                (rpg.PhysicalDamage.Bludgeoning, "Bludg."),
                (rpg.PhysicalDamage.Piercing,    "Pierc."),
                (rpg.PhysicalDamage.Slashing,    "Slash"),
            ]
            pbw = (RW - 2 * 4) // 3
            for i, (val, lbl_text) in enumerate(phys_entries):
                bx   = lx + i * (pbw + 4)
                rect = pygame.Rect(bx, cy, pbw, FH)
                active = val.name in self._f.get("physical_damages", [])
                pygame.draw.rect(screen, (80, 55, 120) if active else (48, 48, 64), rect, border_radius=4)
                pygame.draw.rect(screen, (140, 100, 200) if active else (75, 75, 100), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True, (230, 210, 255) if active else (150, 150, 180))
                screen.blit(ts, (rect.x + (pbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"physical_damages_{val.name}"] = rect
            cy += FH + 8

            # ── Magic damage types ──────────────────────────────────────────
            label("Magic type", lx, cy)
            cy += 14
            mag_entries = [
                (rpg.MagicDamage.Acid,      "Acid"),
                (rpg.MagicDamage.Cold,      "Cold"),
                (rpg.MagicDamage.Fire,      "Fire"),
                (rpg.MagicDamage.Force,     "Force"),
                (rpg.MagicDamage.Lightning, "Ltng."),
                (rpg.MagicDamage.Necrotic,  "Necr."),
                (rpg.MagicDamage.Poison,    "Psn."),
                (rpg.MagicDamage.Psychic,   "Psyc."),
                (rpg.MagicDamage.Radiant,   "Rad."),
                (rpg.MagicDamage.Thunder,   "Thnd."),
            ]
            mbw = (RW - 4 * 4) // 5
            for i, (val, lbl_text) in enumerate(mag_entries):
                row = i // 5
                col = i % 5
                bx   = lx + col * (mbw + 4)
                by   = cy + row * (FH + 4)
                rect = pygame.Rect(bx, by, mbw, FH)
                active = val.name in self._f.get("magic_damages", [])
                pygame.draw.rect(screen, (55, 100, 80) if active else (48, 48, 64), rect, border_radius=4)
                pygame.draw.rect(screen, (90, 160, 130) if active else (75, 75, 100), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True, (180, 240, 210) if active else (150, 150, 180))
                screen.blit(ts, (rect.x + (mbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"magic_damages_{val.name}"] = rect
            cy += 2 * (FH + 4) + PAD

        else:
            # No weapon — show hint
            hint = self._font_md.render(
                'Click "+ Add" to add a weapon.', True, (120, 120, 150))
            screen.blit(hint, (r.x + (W - hint.get_width()) // 2, cy + 20))

        # ── Bottom buttons ────────────────────────────────────────────────
        btn_y = r.bottom - self.BTN_H - PAD
        pygame.draw.line(screen, (80, 80, 110),
                         (r.x + PAD, btn_y - 8), (r.right - PAD, btn_y - 8))

        # REMOVE (left, red, only when a weapon exists)
        rem_r = pygame.Rect(r.x + PAD, btn_y, 100, self.BTN_H)
        if self._weapons and self._sel >= 0:
            pygame.draw.rect(screen, (110, 40, 40), rem_r, border_radius=4)
            pygame.draw.rect(screen, (170, 70, 70), rem_r, 1, border_radius=4)
            rs = self._font_md.render("Remove", True, (240, 180, 180))
            screen.blit(rs, (rem_r.x + (rem_r.w - rs.get_width()) // 2,
                              rem_r.centery - rs.get_height() // 2))
        self._rects["remove"] = rem_r

        # DONE (right, green)
        done_r = pygame.Rect(r.right - PAD - 100, btn_y, 100, self.BTN_H)
        pygame.draw.rect(screen, (40, 100, 55), done_r, border_radius=4)
        pygame.draw.rect(screen, (70, 160, 90), done_r, 1, border_radius=4)
        ds = self._font_md.render("Done", True, (180, 240, 190))
        screen.blit(ds, (done_r.x + (done_r.w - ds.get_width()) // 2,
                          done_r.centery - ds.get_height() // 2))
        self._rects["done"] = done_r


# ─────────────────────────────────────────────────────────────────────────────
#  Ability score helpers — derived from rpg.SaveAbility (SaveStr=0…SaveCha=5)
# ─────────────────────────────────────────────────────────────────────────────

_ABILITY_TO_INT: dict[str, int] = {
    name.removeprefix("Save").lower(): member.value
    for name, member in rpg.SaveAbility.__members__.items()
    if name.startswith("Save")
}
_INT_TO_ABILITY: dict[int, str] = {v: k for k, v in _ABILITY_TO_INT.items()}

# ─────────────────────────────────────────────────────────────────────────────
#  Spell serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_SPELL: dict = {
    "name":                  "New Spell",
    "type":                  "Harm",
    "geometry":              "Single",
    "attack_type":           "AttackRoll",
    "save_ability":          None,   # used by Save attack type only
    "range":                 30,
    "radius":                None,   # used by Sphere/Cone only
    "width":                 None,   # used by Line only
    "length":                None,   # used by Line only
    "duration":               1,
    "magic_damage_types":    ["Fire"],
    "physical_damage_types": [],
    "num_dice":               1,
    "die_size":               6,
}


def _spell_to_dict(s) -> dict:
    geo = s.geometry.name
    uses_radius = geo in ("Sphere", "Cone")
    uses_line   = geo == "Line"
    return {
        "name":                  s.name,
        "type":                  s.type.name,
        "geometry":              geo,
        "attack_type":           s.attack_type.name,
        "save_ability":          s.save_ability.name if s.attack_type == rpg.SpellAttack.Save else None,
        "range":                 s.range,
        "radius":                s.radius if uses_radius else None,
        "width":                 s.width  if uses_line   else None,
        "length":                s.length if uses_line   else None,
        "duration":              s.duration,
        "magic_damage_types":    [v.name for v in s.magic_damage_types],
        "physical_damage_types": [v.name for v in s.physical_damage_types],
        "num_dice":              s.num_dice,
        "die_size":              s.die_size,
    }


def _dict_to_spell(d: dict):
    s = rpg.Spell()
    s.name         = d.get("name",         "Unnamed Spell")
    s.type         = getattr(rpg.SpellType,     d.get("type",         "Harm"),     rpg.SpellType.Harm)
    s.geometry     = getattr(rpg.SpellGeometry, d.get("geometry",     "Single"),   rpg.SpellGeometry.Single)
    s.attack_type  = getattr(rpg.SpellAttack,   d.get("attack_type",  "AttackRoll"), rpg.SpellAttack.AttackRoll)
    s.save_ability = getattr(rpg.SaveAbility,   d.get("save_ability") or "SaveDex", rpg.SaveAbility.SaveDex)
    s.range        = int(d.get("range")  or 30)
    s.radius       = int(d.get("radius") or 10)
    s.width        = int(d.get("width")  or  5)
    s.length       = int(d.get("length") or 30)
    s.duration     = int(d.get("duration",   1))
    s.magic_damage_types    = [_parse_magic_damage(v)    for v in d.get("magic_damage_types",    [])]
    s.physical_damage_types = [_parse_physical_damage(v) for v in d.get("physical_damage_types", [])]
    s.num_dice     = int(d.get("num_dice",   1))
    s.die_size     = int(d.get("die_size",   6))
    return s


class SpellDialog:
    """Modal dialog for editing an agent's spell list."""

    DLG_W  = 510
    DLG_H  = 620
    HDR_H  = 36
    BTN_H  = 28
    PAD    = 14
    TAB_H  = 30
    ROW_H  = 32
    FIELD_H= 24

    def __init__(self, font_sm, font_md, font_lg):
        self.active      = False
        self._font_sm    = font_sm
        self._font_md    = font_md
        self._font_lg    = font_lg
        self._agent_idx  = -1
        self._agent_name = ""
        self._spells: list[dict] = []
        self._sel        = -1
        self._cb         = None
        self._rect: pygame.Rect | None = None
        self._active_field: str | None = None
        self._f: dict = {}
        self._rects: dict = {}

    def open(self, screen, agent_idx: int, agent_name: str,
             spells: list[dict], callback):
        import copy
        self.active      = True
        self._agent_idx  = agent_idx
        self._agent_name = agent_name
        self._spells     = copy.deepcopy(spells)
        self._cb         = callback
        self._active_field = None
        self._rects      = {}
        sw, sh = screen.get_size()
        x = (sw - self.DLG_W) // 2
        y = (sh - self.DLG_H) // 2
        self._rect = pygame.Rect(x, y, self.DLG_W, self.DLG_H)
        self._sel = 0 if self._spells else -1
        self._load_form()

    def _load_form(self):
        import copy
        if 0 <= self._sel < len(self._spells):
            self._f = copy.deepcopy(self._spells[self._sel])
        else:
            self._f = {}
        self._active_field = None

    def _save_form(self):
        if 0 <= self._sel < len(self._spells):
            self._spells[self._sel] = dict(self._f)

    def _add_spell(self):
        import copy
        self._save_form()
        self._spells.append(copy.deepcopy(_DEFAULT_SPELL))
        self._sel = len(self._spells) - 1
        self._load_form()

    def _remove_spell(self):
        if 0 <= self._sel < len(self._spells):
            self._spells.pop(self._sel)
            self._sel = min(self._sel, len(self._spells) - 1)
            self._load_form()

    def _confirm(self):
        self._save_form()
        if self._cb:
            self._cb(self._agent_idx, self._spells)
        self.active = False

    def handle(self, event, screen) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            af = self._active_field
            if af == "name":
                if event.key == pygame.K_BACKSPACE:
                    self._f[af] = self._f.get(af, "")[:-1]
                elif event.key == pygame.K_RETURN:
                    self._active_field = None
                elif event.key == pygame.K_ESCAPE:
                    self._active_field = None
                elif event.unicode and event.unicode.isprintable():
                    self._f[af] = self._f.get(af, "") + event.unicode
                return True
            if af in ("range", "radius", "width", "length", "duration",
                      "num_dice", "die_size"):
                cur = str(self._f.get(af, ""))
                if event.key == pygame.K_BACKSPACE:
                    cur = cur[:-1]
                    self._f[af] = int(cur) if cur.isdigit() else 0
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self._active_field = None
                elif event.unicode.isdigit():
                    cur += event.unicode
                    self._f[af] = int(cur)
                return True
            if event.key == pygame.K_ESCAPE:
                self._confirm()
                return True
            if event.key == pygame.K_RETURN:
                self._confirm()
                return True

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return True

        mx, my = event.pos
        r = self._rect
        if not r:
            return True

        if not r.collidepoint(mx, my):
            self._confirm()
            return True

        self._active_field = None

        # Spell tabs
        if "tab" in self._rects:
            for i, tr in enumerate(self._rects["tab"]):
                if tr.collidepoint(mx, my):
                    self._save_form()
                    self._sel = i
                    self._load_form()
                    return True

        if "add" in self._rects and self._rects["add"].collidepoint(mx, my):
            self._add_spell()
            return True

        if self._f:
            # Toggle buttons (single choice)
            for group_key, options in [
                ("type",        ["Harm", "Heal"]),
                ("geometry",    ["Single", "Line", "Cone", "Sphere"]),
                ("attack_type", ["AttackRoll", "Save", "Automatic"]),
                ("save_ability",["SaveStr","SaveDex","SaveCon","SaveInt","SaveWis","SaveCha"]),
            ]:
                for val in options:
                    rkey = f"{group_key}_{val}"
                    if rkey in self._rects and self._rects[rkey].collidepoint(mx, my):
                        self._f[group_key] = val
                        return True

            # Numeric / text fields
            for field_key in ("name", "range", "radius", "width", "length",
                              "duration", "num_dice", "die_size"):
                if field_key in self._rects and self._rects[field_key].collidepoint(mx, my):
                    self._active_field = field_key
                    return True

            # Damage type multi-toggles
            for key, enum_cls, vals in (
                ("magic_damage_types",
                 rpg.MagicDamage,
                 [rpg.MagicDamage.Acid, rpg.MagicDamage.Cold, rpg.MagicDamage.Fire,
                  rpg.MagicDamage.Force, rpg.MagicDamage.Lightning, rpg.MagicDamage.Necrotic,
                  rpg.MagicDamage.Poison, rpg.MagicDamage.Psychic, rpg.MagicDamage.Radiant,
                  rpg.MagicDamage.Thunder]),
                ("physical_damage_types",
                 rpg.PhysicalDamage,
                 [rpg.PhysicalDamage.Bludgeoning, rpg.PhysicalDamage.Piercing,
                  rpg.PhysicalDamage.Slashing]),
            ):
                for val in vals:
                    rkey = f"{key}_{val.name}"
                    if rkey in self._rects and self._rects[rkey].collidepoint(mx, my):
                        cur = list(self._f.get(key, []))
                        if val.name in cur:
                            cur.remove(val.name)
                        else:
                            cur.append(val.name)
                        self._f[key] = cur
                        return True

        if "remove" in self._rects and self._rects["remove"].collidepoint(mx, my):
            self._remove_spell()
            return True
        if "done" in self._rects and self._rects["done"].collidepoint(mx, my):
            self._confirm()
            return True
        return True

    def draw(self, screen):
        if not self.active or not self._rect:
            return

        r   = self._rect
        PAD = self.PAD
        W   = self.DLG_W
        FH  = self.FIELD_H

        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        screen.blit(overlay, (0, 0))

        pygame.draw.rect(screen, (40, 42, 54), r, border_radius=6)
        pygame.draw.rect(screen, (130, 80, 200), r, 2, border_radius=6)

        # Header
        hdr = pygame.Rect(r.x, r.y, W, self.HDR_H)
        pygame.draw.rect(screen, (60, 45, 90), hdr,
                         border_top_left_radius=6, border_top_right_radius=6)
        title_s = self._font_lg.render(
            f"✨ SPELLS — {self._agent_name}", True, (220, 200, 255))
        screen.blit(title_s, (r.x + PAD, r.y + (self.HDR_H - title_s.get_height()) // 2))

        cy = r.y + self.HDR_H + PAD

        # Spell tabs + [+ Add]
        tab_rects = []
        tab_max_w = W - PAD * 2 - 60
        tab_w     = min(120, max(60, tab_max_w // max(len(self._spells), 1)))
        for i, sp in enumerate(self._spells):
            tr = pygame.Rect(r.x + PAD + i * (tab_w + 3), cy, tab_w, self.TAB_H)
            tab_rects.append(tr)
            active = (i == self._sel)
            pygame.draw.rect(screen,
                             (90, 55, 140) if active else (55, 45, 78),
                             tr, border_radius=4)
            pygame.draw.rect(screen,
                             (150, 100, 220) if active else (90, 70, 120),
                             tr, 1, border_radius=4)
            label = self._font_sm.render(sp.get("name", "?")[:14], True,
                                         (230, 210, 255) if active else (170, 150, 200))
            screen.blit(label, (tr.x + 4, tr.centery - label.get_height() // 2))
        self._rects["tab"] = tab_rects

        add_r = pygame.Rect(r.right - PAD - 52, cy, 52, self.TAB_H)
        pygame.draw.rect(screen, (55, 85, 55), add_r, border_radius=4)
        pygame.draw.rect(screen, (80, 130, 80), add_r, 1, border_radius=4)
        screen.blit(self._font_md.render("+ Add", True, (180, 240, 180)),
                    (add_r.x + 6, add_r.centery - self._font_md.get_height() // 2))
        self._rects["add"] = add_r
        cy += self.TAB_H + PAD

        pygame.draw.line(screen, (90, 70, 120), (r.x + PAD, cy), (r.right - PAD, cy))
        cy += 10

        if self._f:
            lx = r.x + PAD
            RW = W - PAD * 2

            def label(text, x, y):
                s = self._font_sm.render(text, True, (160, 140, 195))
                screen.blit(s, (x, y))

            def text_field(key, x, y, w, h=FH):
                rect = pygame.Rect(x, y, w, h)
                active = self._active_field == key
                pygame.draw.rect(screen,
                                 (60, 55, 80) if active else (35, 32, 50), rect, border_radius=3)
                pygame.draw.rect(screen,
                                 (150, 100, 220) if active else (90, 70, 120), rect, 1, border_radius=3)
                val = str(self._f.get(key, ""))
                ts = self._font_md.render(val, True, (220, 210, 240))
                screen.blit(ts, (rect.x + 4, rect.centery - ts.get_height() // 2))
                if active:
                    cx_cur = rect.x + 4 + ts.get_width() + 1
                    pygame.draw.line(screen, (200, 180, 240),
                                     (cx_cur, rect.y + 3), (cx_cur, rect.bottom - 3))
                self._rects[key] = rect
                return rect

            def toggle_group(group_key, options, x, y, btn_w=None, h=FH):
                n = len(options)
                bw = btn_w or max(48, (RW - (n - 1) * 4) // n)
                for i, val in enumerate(options):
                    active = self._f.get(group_key) == val
                    rect   = pygame.Rect(x + i * (bw + 4), y, bw, h)
                    pygame.draw.rect(screen,
                                     (90, 55, 140) if active else (48, 44, 65),
                                     rect, border_radius=4)
                    pygame.draw.rect(screen,
                                     (150, 100, 220) if active else (80, 65, 105),
                                     rect, 1, border_radius=4)
                    ts = self._font_sm.render(val.replace("Save", "").replace("AttackRoll", "Roll"),
                                             True,
                                             (230, 210, 255) if active else (150, 135, 185))
                    screen.blit(ts, (rect.x + (bw - ts.get_width()) // 2,
                                     rect.centery - ts.get_height() // 2))
                    self._rects[f"{group_key}_{val}"] = rect

            # Name
            label("Name", lx, cy); cy += 14
            text_field("name", lx, cy, RW); cy += FH + PAD

            # Type
            label("Type", lx, cy); cy += 14
            toggle_group("type", ["Harm", "Heal"], lx, cy, btn_w=90); cy += FH + PAD

            # Geometry
            label("Geometry", lx, cy); cy += 14
            toggle_group("geometry", ["Single", "Line", "Cone", "Sphere"], lx, cy); cy += FH + PAD

            # Attack type
            label("Attack Type", lx, cy); cy += 14
            toggle_group("attack_type", ["AttackRoll", "Save", "Automatic"], lx, cy); cy += FH + 4

            # Save ability (only for Save attack type)
            if self._f.get("attack_type") == "Save":
                label("Save Ability", lx, cy); cy += 14
                toggle_group("save_ability",
                             ["SaveStr", "SaveDex", "SaveCon", "SaveInt", "SaveWis", "SaveCha"],
                             lx, cy); cy += FH + 4

            cy += PAD

            # Range / Duration row
            label("Range (ft)", lx, cy)
            label("Duration (turns)", lx + RW // 2 + 6, cy)
            cy += 14
            text_field("range",    lx,               cy, RW // 2 - 4)
            text_field("duration", lx + RW // 2 + 4, cy, RW // 2 - 4)
            cy += FH + PAD

            # Geometry-specific dimensions
            geo = self._f.get("geometry", "Single")
            if geo == "Sphere" or geo == "Cone":
                label("Radius (ft)", lx, cy); cy += 14
                text_field("radius", lx, cy, RW // 2 - 4); cy += FH + PAD
            elif geo == "Line":
                label("Width (ft)", lx, cy)
                label("Length (ft)", lx + RW // 2 + 6, cy)
                cy += 14
                text_field("width",  lx,               cy, RW // 2 - 4)
                text_field("length", lx + RW // 2 + 4, cy, RW // 2 - 4)
                cy += FH + PAD

            # Damage dice
            label("Damage / Heal (NdX)", lx, cy); cy += 14
            text_field("num_dice", lx,      cy, 40)
            ds = self._font_md.render("d", True, (170, 150, 210))
            screen.blit(ds, (lx + 44, cy + (FH - ds.get_height()) // 2))
            text_field("die_size", lx + 54, cy, 50); cy += FH + 8

            # Magic damage types (2 rows of 5)
            label("Magic type", lx, cy); cy += 14
            mag_entries = [
                (rpg.MagicDamage.Acid,      "Acid"),
                (rpg.MagicDamage.Cold,      "Cold"),
                (rpg.MagicDamage.Fire,      "Fire"),
                (rpg.MagicDamage.Force,     "Force"),
                (rpg.MagicDamage.Lightning, "Ltng."),
                (rpg.MagicDamage.Necrotic,  "Necr."),
                (rpg.MagicDamage.Poison,    "Psn."),
                (rpg.MagicDamage.Psychic,   "Psyc."),
                (rpg.MagicDamage.Radiant,   "Rad."),
                (rpg.MagicDamage.Thunder,   "Thnd."),
            ]
            mbw = (RW - 4 * 4) // 5
            for i, (val, lbl_text) in enumerate(mag_entries):
                row = i // 5; col = i % 5
                bx = lx + col * (mbw + 4)
                by = cy + row * (FH + 4)
                rect = pygame.Rect(bx, by, mbw, FH)
                active = val.name in self._f.get("magic_damage_types", [])
                pygame.draw.rect(screen, (55, 100, 80) if active else (48, 44, 65), rect, border_radius=4)
                pygame.draw.rect(screen, (90, 160, 130) if active else (80, 65, 105), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True,
                                          (180, 240, 210) if active else (150, 135, 185))
                screen.blit(ts, (rect.x + (mbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"magic_damage_types_{val.name}"] = rect
            cy += 2 * (FH + 4) + 8

            # Physical damage types
            label("Physical type", lx, cy); cy += 14
            phys_entries = [
                (rpg.PhysicalDamage.Bludgeoning, "Bludg."),
                (rpg.PhysicalDamage.Piercing,    "Pierc."),
                (rpg.PhysicalDamage.Slashing,    "Slash"),
            ]
            pbw = (RW - 2 * 4) // 3
            for i, (val, lbl_text) in enumerate(phys_entries):
                bx   = lx + i * (pbw + 4)
                rect = pygame.Rect(bx, cy, pbw, FH)
                active = val.name in self._f.get("physical_damage_types", [])
                pygame.draw.rect(screen, (80, 55, 120) if active else (48, 44, 65), rect, border_radius=4)
                pygame.draw.rect(screen, (140, 100, 200) if active else (80, 65, 105), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True,
                                          (230, 210, 255) if active else (150, 135, 185))
                screen.blit(ts, (rect.x + (pbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"physical_damage_types_{val.name}"] = rect

        else:
            hint = self._font_md.render('Click "+ Add" to add a spell.', True, (120, 110, 150))
            screen.blit(hint, (r.x + (W - hint.get_width()) // 2, cy + 20))

        # Bottom buttons
        btn_y = r.bottom - self.BTN_H - PAD
        pygame.draw.line(screen, (90, 70, 120),
                         (r.x + PAD, btn_y - 8), (r.right - PAD, btn_y - 8))

        rem_r = pygame.Rect(r.x + PAD, btn_y, 100, self.BTN_H)
        if self._spells and self._sel >= 0:
            pygame.draw.rect(screen, (110, 40, 40), rem_r, border_radius=4)
            pygame.draw.rect(screen, (170, 70, 70), rem_r, 1, border_radius=4)
            rs = self._font_md.render("Remove", True, (240, 180, 180))
            screen.blit(rs, (rem_r.x + (rem_r.w - rs.get_width()) // 2,
                              rem_r.centery - rs.get_height() // 2))
        self._rects["remove"] = rem_r

        done_r = pygame.Rect(r.right - PAD - 100, btn_y, 100, self.BTN_H)
        pygame.draw.rect(screen, (40, 100, 55), done_r, border_radius=4)
        pygame.draw.rect(screen, (70, 160, 90), done_r, 1, border_radius=4)
        ds = self._font_md.render("Done", True, (180, 240, 190))
        screen.blit(ds, (done_r.x + (done_r.w - ds.get_width()) // 2,
                          done_r.centery - ds.get_height() // 2))
        self._rects["done"] = done_r


# ─────────────────────────────────────────────────────────────────────────────
#  Terrain Editor Dialog
# ─────────────────────────────────────────────────────────────────────────────
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
    """Modal dialog for marking terrain on the map (walls, chasms, difficult terrain)."""

    def __init__(self, font_sm, font_md):
        self.font_sm = font_sm
        self.font_md = font_md
        self.active = False
        self.terrain_regions = []  # List of {type, col, row, width, height, multiplier}
        self.map_surf = None
        self.selection_start = None
        self.selection_rect = None
        self.selected_type = "Difficult Terrain"
        self.terrain_mult = 0.5
        self.bm = None  # Reference to BattleMap for grid coordinate conversion

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
                self.selection_start = event.pos
                self.selection_rect = None

        elif event.type == pygame.MOUSEMOTION:
            if self.selection_start:
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
                self.selected_type = "Difficult Terrain"
            elif event.key == pygame.K_z and event.mod & pygame.KMOD_CTRL:
                # Undo last region
                if self.terrain_regions:
                    self.terrain_regions.pop()

    def _apply_terrain_to_selection(self):
        """Convert screen rect to grid cells and add terrain region."""
        if not self.selection_rect or not self.map_surf:
            return

        region = {
            "type": self.selected_type,
            "x": self.selection_rect.x,
            "y": self.selection_rect.y,
            "width": self.selection_rect.w,
            "height": self.selection_rect.h,
            "multiplier": self.terrain_mult if self.selected_type == "Difficult Terrain" else 0.0
        }
        self.terrain_regions.append(region)

    def draw(self, screen):
        """Draw the terrain editor UI."""
        if not self.active or not self.map_surf:
            return

        # Draw map and overlays
        screen.blit(self.map_surf, (0, 0))

        # Draw terrain overlays
        for region in self.terrain_regions:
            rect = pygame.Rect(region["x"], region["y"], region["width"], region["height"])
            if region["type"] == "Wall":
                color = (50, 50, 50, 200)
            elif region["type"] == "Chasm":
                color = (140, 140, 140, 180)
            else:  # Difficult Terrain
                color = (255, 200, 100, 128)
            s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            s.fill(color)
            screen.blit(s, (rect.x, rect.y))

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
            f"[3] Difficult Terrain (orange)"
        ]
        y = 10
        for text in sel_texts:
            txt = self.font_sm.render(text, True, (255, 255, 255))
            screen.blit(txt, (10, y))
            y += 18

        # Current type highlight
        current_idx = {"Wall": 0, "Chasm": 1, "Difficult Terrain": 2}.get(self.selected_type, 2)
        pygame.draw.rect(screen, (255, 255, 100), pygame.Rect(8, 8 + current_idx*18, 160, 16), 2)

        # Instructions
        inst = self.font_sm.render("[ESC] Save & Close | [Ctrl+Z] Undo", True, (180, 180, 180))
        screen.blit(inst, (10, screen.get_height() - 25))


# ─────────────────────────────────────────────────────────────────────────────
#  Main application
# ─────────────────────────────────────────────────────────────────────────────
class App:
    def __init__(self, map_path: str):
        pygame.init()
        pygame.display.set_caption("RPG Battle Map")

        # ── Load json file containing all available mobs from a huge spreadsheet
        script_dir = os.path.dirname(os.path.abspath(__file__))
        map_dir = os.path.dirname(os.path.abspath(map_path))
        # Try multiple possible locations for the CSV file
        possible_paths = [
            os.path.join(script_dir, "sprites", "DND2024_MonsterStats.csv"),
            os.path.join(script_dir, "..", "sprites", "DND2024_MonsterStats.csv"),
            os.path.join(map_dir, "..", "sprites", "DND2024_MonsterStats.csv"),
            "sprites/DND2024_MonsterStats.csv",
        ]
        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break
        if not csv_path:
            sys.exit(f"ERROR: Could not find DND2024_MonsterStats.csv. Checked: {possible_paths}")

        # Create or load JSON file with mob stats
        json_path = os.path.splitext(csv_path)[0] + '.json'
        if not os.path.exists(json_path):
            json_path = read_stats_from_csv.save_stats_as_json(csv_path, json_path)
        self.mob_stats_json = read_stats_from_csv.load_stats_from_json(json_path)
        self.all_mobs = self.mob_stats_json
        self.sprites_dir = os.path.dirname(csv_path)  # Store for later use

        # Selected mob's stats (loaded when a mob is selected from dropdown)
        self.selected_mob_stats = None


        # ── Load C++ battle map ───────────────────────────────────────────
        self.bm = rpg.BattleMap(map_path)
        self.bm.analyze_grid()
        self.bm.detect_walls()

        # ── Load image to get size BEFORE creating the display ────────────
        # convert_alpha() requires a display surface to exist first, so we
        # load raw here, create the window, then convert/scale below.
        raw_map = pygame.image.load(map_path)
        mw, mh  = raw_map.get_size()

        # ── Auto-scale map to fit within a reasonable display area ────────
        # Leave room for the right-side config panel and keep some margin.
        MAX_MAP_W = 1860 - PANEL_W   # fits comfortably on a 1920-wide display
        MAX_MAP_H = 1040             # fits comfortably on a 1080-tall display
        scale = min(MAX_MAP_W / mw, MAX_MAP_H / mh, 1.0)  # never upscale
        disp_mw = int(mw * scale)
        disp_mh = int(mh * scale)
        self.map_scale = scale       # used to convert C++ pixel coords → screen

        # ── Window sizing ─────────────────────────────────────────────────
        win_w = disp_mw + PANEL_W
        win_h = max(disp_mh, 600)
        self.screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

        # ── Now safe to convert (display surface exists) ──────────────────
        converted = raw_map.convert_alpha()
        if scale < 1.0:
            self.map_surf = pygame.transform.smoothscale(converted, (disp_mw, disp_mh))
        else:
            self.map_surf = converted
        self.map_rect = pygame.Rect(0, 0, disp_mw, disp_mh)

        # ── Fonts ─────────────────────────────────────────────────────────
        self.font_sm = pygame.font.SysFont("sans", FONT_SM)
        self.font_md = pygame.font.SysFont("sans", FONT_MD)
        self.font_lg = pygame.font.SysFont("sans", FONT_LG, bold=True)

        # ── Overlay surfaces (alpha) – matches the displayed (scaled) size ──
        self.overlay = pygame.Surface((disp_mw, disp_mh), pygame.SRCALPHA)
        self._build_overlay()

        # ── Sprite cache  {sprite_path: pygame.Surface} ───────────────────
        self.sprites: dict[str, pygame.Surface] = {}

        # ── File browser (shared modal) ───────────────────────────────────
        self.file_browser   = FileBrowser(self.font_sm, self.font_md, self.font_lg)
        self.stats_dialog   = StatsDialog(self.font_sm, self.font_md, self.font_lg)
        self.weapon_dialog  = WeaponDialog(self.font_sm, self.font_md, self.font_lg)
        self.spell_dialog   = SpellDialog(self.font_sm, self.font_md, self.font_lg)
        mob_names = sorted(self.all_mobs.keys())
        self.mob_dialog = MobSelectionDialog(mob_names, self.font_sm, self.font_md)
        self.terrain_editor = TerrainEditorDialog(self.font_sm, self.font_md)
        self.terrain_placement_dialog = TemporaryTerrainPlacementDialog(self.font_sm, self.font_md)
        self.context_menu   = ContextMenu()

        self._map_dir  = os.path.dirname(os.path.abspath(map_path)) or "/"
        self._save_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_agents.json"
        )
        self._terrain_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_terrain.json"
        )
        self._terrain_regions = []  # List of {type, x, y, width, height, multiplier}

        # Load terrain data if it exists
        self._load_terrain()

        # ── Drag-and-drop state ───────────────────────────────────────────
        self.drag_idx     = -1         # index of agent being dragged
        self.drag_origin  = None       # Cell: original position (for cancel)
        self.drag_offset  = (0, 0)     # (dcol, drow) within agent where click landed
        self.drag_cell    = None       # Cell: current snapped target
        self.drag_valid   = False      # is current drag_cell a legal drop?

        # ── Selection state ───────────────────────────────────────────────
        self.selected_idx  = -1        # index of selected agent (-1 = none)
        self._reach_walk: list = []    # Cell list for walk range overlay
        self._reach_fly:  list = []    # Cell list for fly range overlay
        self._reach_set:  set  = set() # union of walk+fly as (col,row) tuples for O(1) lookup

        # ── Combat engine (C++ — seeded PRNG, RL-ready) ──────────────────
        self.combat = rpg.CombatEngine()

        # ── Attack-range overlay ──────────────────────────────────────────
        self._attack_cells_melee:  list = []   # cells attackable by active melee weapon
        self._attack_cells_rnorm:  list = []   # cells in ranged normal range
        self._attack_cells_rlong:  list = []   # cells only in ranged long range

        # ── Combat widget state ───────────────────────────────────────────
        self.combat_active        = False
        self.initiative_order     = []    # list[rpg.InitiativeEntry], high→low
        self.turn_idx             = 0     # index into initiative_order
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot  = ""    # "" | "action" | "bonus"
        self.pending_weapon_idx   = 0
        self.attacks_remaining    = 0     # attacks left in current pending slot
        self.pending_spell_slot   = ""    # "" | "action" | "bonus"
        self.pending_spell_idx    = 0
        self.pending_spell_is_aoe = False
        self.spell_hover_cell     = None  # cell under mouse during AoE targeting
        self.combat_log           = []    # list[str], newest first
        self.move_remaining_walk   = 0     # feet remaining this turn (walk)
        self.move_remaining_fly    = 0     # feet remaining this turn (fly)
        self.move_remaining_swim   = 0     # feet remaining this turn (swim)
        self.move_remaining_burrow = 0     # feet remaining this turn (burrow)
        self.move_type             = rpg.MovementType.Walk  # selected movement type
        self._move_type_btns: dict = {}    # MovementType -> pygame.Rect (built each draw)
        self.last_movement_dist    = 0     # distance of most recent movement (for running jump)
        self.jump_overlay_active   = False # whether jump overlay is showing
        self.jump_reachable_cells  = []    # cells reachable by jump

        # ── Temporary terrain effects (spells, items, etc. with duration) ───
        self.round_num              = 0     # current round number (incremented when turn_idx wraps)
        self._effect_meta: dict     = {}    # {effect_id: {"name": str, "color": tuple, "cells": [(col,row)]}}

        # ── Agent config GUI state ────────────────────────────────────────
        self._init_config_panel()
        self._init_combat_panel()
        self.scroll_y = 0         # scroll offset for agent list

        self.clock = pygame.time.Clock()

    # ─────────────────────────────────────────────────────────────────────
    #  Build the static grid / wall / blocked overlay (drawn once)
    # ─────────────────────────────────────────────────────────────────────
    def _build_overlay(self):
        self.overlay.fill((0, 0, 0, 0))
        bm  = self.bm
        s   = self.map_scale          # C++ coords → screen coords
        cpx = int(bm.cell_pixel_size * s)

        # Scale all C++ pixel positions to match the displayed map size.
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return
        hlines = [int(y * s) for y in raw_h]
        vlines = [int(x * s) for x in raw_v]

        ox = vlines[0]
        oy = hlines[0]

        # Blocked / wall cells – exact per-cell boundaries from the grid lines.
        for cell in bm.disallowed_cells:
            c, rw = cell.col, cell.row
            if c + 1 >= len(vlines) or rw + 1 >= len(hlines):
                continue
            rx  = vlines[c]
            ry  = hlines[rw]
            rw_ = vlines[c + 1] - rx
            rh_ = hlines[rw + 1] - ry
            pygame.draw.rect(self.overlay, COL_BLOCKED,
                             pygame.Rect(rx, ry, rw_, rh_))

        # Grid lines
        grid_color = (255, 255, 255, 55)
        span_x = vlines[-1] - vlines[0]
        span_y = hlines[-1] - hlines[0]
        for y in hlines:
            pygame.draw.line(self.overlay, grid_color, (ox, y), (ox + span_x, y))
        for x in vlines:
            pygame.draw.line(self.overlay, grid_color, (x, oy), (x, oy + span_y))

        # Edge-based walls (thick red lines between cells) – only when enabled.
        wall_color = (200, 60, 60, 220)
        for w in bm.walls:
            ax = ox + w.a.col * cpx
            ay = oy + w.a.row * cpx
            bx = ox + w.b.col * cpx
            by = oy + w.b.row * cpx
            if w.a.row != w.b.row:                   # horizontal wall (between rows)
                wy = max(ay, by)
                pygame.draw.line(self.overlay, wall_color,
                                 (ax, wy), (ax + cpx, wy), 4)
            else:                                    # vertical wall (between cols)
                wx = max(ax, bx)
                pygame.draw.line(self.overlay, wall_color,
                                 (wx, ay), (wx, ay + cpx), 4)

    # ─────────────────────────────────────────────────────────────────────
    #  Config panel widgets
    # ─────────────────────────────────────────────────────────────────────
    def _panel_x(self):
        return self.screen.get_width() - PANEL_W

    # Layout constants used by both init and reposition
    _PANEL_PAD    = 12   # left/right inset inside panel
    _LABEL_H      = 15   # height reserved for a label line
    _WIDGET_H     = 28   # height of inputs / steppers
    _LABEL_GAP    =  4   # gap between label and its widget
    _ROW_GAP      = 12   # gap between one row's widget and the next row's label
    _BTN_H        = 30   # button height
    _BTN_GAP      =  8   # gap between buttons
    _TITLE_H      = 26   # height of the bold title
    _BROWSE_W     = 34   # width of the "…" browse button

    def _panel_layout(self):
        """Return (px, W, list-of-y-positions) for a fresh layout pass."""
        px = self._panel_x() + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2

        # Row stride = label + gap + widget + row-gap
        RS = self._LABEL_H + self._LABEL_GAP + self._WIDGET_H + self._ROW_GAP

        # y of the INPUT/STEPPER for each row (label sits RS-_WIDGET_H-_ROW_GAP above it)
        title_y  = 10
        row0_y   = title_y + self._TITLE_H + 10           # Mob dropdown
        row1_y   = row0_y  + RS                            # Name widget
        row2_y   = row1_y  + RS                            # Sprite Path widget
        row3_y   = row2_y  + RS                            # Size widget
        row4_y   = row3_y  + RS                            # Col / Row widgets
        btn0_y   = row4_y  + self._WIDGET_H + self._ROW_GAP + 4   # Add Agent
        btn1_y   = btn0_y  + self._BTN_H + self._BTN_GAP  # Apply & Draw
        btn2_y   = btn1_y  + self._BTN_H + self._BTN_GAP  # Clear All
        btn3_y   = btn2_y  + self._BTN_H + self._BTN_GAP + 4  # Save (half-width)
        # btn4 (Load) is at same y as btn3, right half

        return px, W, title_y, row0_y, row1_y, row2_y, row3_y, row4_y, btn0_y, btn1_y, btn2_y, btn3_y

    def _init_config_panel(self):
        """Initialize config panel using layout from _panel_layout()."""
        px, W, title_y, r0, r1, r2, r3, r4, b0, b1, b2, b3 = self._panel_layout()
        H   = self._WIDGET_H
        HW  = W // 2 - 2
        BRW = self._BROWSE_W
        TW  = W - BRW - 4
        B   = self._BTN_H

        self.btn_select_mob = Button(pygame.Rect(px, r0, W, B), "Select Mob", font=self.font_md)
        self.inp_name = TextInput(pygame.Rect(px, r1, W, H), "Agent name", self.font_md)
        self.inp_sprite = TextInput(pygame.Rect(px, r2, TW, H), "Sprite path", self.font_md)
        self.btn_browse = Button(pygame.Rect(px + TW + 4, r2, BRW, H), "...", font=self.font_md)
        self.step_size = IntStepper(pygame.Rect(px, r3, W, H), 1, 1, 6, self.font_md)
        self.step_col = IntStepper(pygame.Rect(px,           r4, HW, H), 0, 0, 99, self.font_md)
        self.step_row = IntStepper(pygame.Rect(px + HW + 4,  r4, HW, H), 0, 0, 99, self.font_md)
        self.btn_add = Button(pygame.Rect(px, b0, W, B), "Add Agent", font=self.font_md)
        self.btn_apply = Button(pygame.Rect(px, b1, W, B), "Apply and Draw", font=self.font_md)
        self.btn_clear = Button(pygame.Rect(px, b2, W, B), "Clear All",
                               COL_BTN_DANGER, (180, 70, 70), font=self.font_md)
        SW = HW
        self.btn_save = Button(pygame.Rect(px,        b3, SW, B), "Save",
                              (50, 100, 60), (70, 130, 80), font=self.font_md)
        self.btn_load = Button(pygame.Rect(px + SW+4, b3, SW, B), "Load",
                              (50, 75, 120), (70, 100, 155), font=self.font_md)
        bc_y = b3 + B + self._BTN_GAP + 8
        self.btn_begin_combat = Button(pygame.Rect(px, bc_y, W, B),
                                      "Begin Combat",
                                      COL_BTN_COMBAT, COL_BTN_COMBAT_HOV, font=self.font_md)
        ter_y = bc_y + B + self._BTN_GAP
        self.btn_edit_terrain = Button(pygame.Rect(px, ter_y, W, B),
                                       "Edit Terrain",
                                       (80, 100, 120), (110, 130, 160), font=self.font_md)

        self.pending_configs: list[rpg.AgentConfig] = []
        self.pending_mob_stats: list[dict | None] = []  # Parallel list of mob stats for each config

    def _reposition_panel(self):
        """Re-anchor all widgets after a window resize."""
        px, W, _, r0, r1, r2, r3, r4, b0, b1, b2, b3 = self._panel_layout()
        HW  = W // 2 - 2
        BRW = self._BROWSE_W
        TW  = W - BRW - 4
        SW  = HW

        self.btn_select_mob.rect.update(px, r0, W, self._WIDGET_H)
        self.inp_name.rect.update(px, r1, W, self._WIDGET_H)
        self.inp_sprite.rect.update(px, r2, TW, self._WIDGET_H)
        self.btn_browse.rect.update(px + TW + 4, r2, BRW, self._WIDGET_H)
        self.step_size.rect.update(px, r3, W, self._WIDGET_H)
        self.step_col.rect.update(px,           r4, HW, self._WIDGET_H)
        self.step_row.rect.update(px + HW + 4,  r4, HW, self._WIDGET_H)
        # Re-init stepper sub-buttons after rect change
        for st in (self.step_size, self.step_col, self.step_row):
            bw = 26
            st.btn_dec = pygame.Rect(st.rect.x,           st.rect.y, bw, st.rect.h)
            st.btn_inc = pygame.Rect(st.rect.right - bw,  st.rect.y, bw, st.rect.h)
        self.btn_add.rect.update(px,   b0, W, self._BTN_H)
        self.btn_apply.rect.update(px, b1, W, self._BTN_H)
        self.btn_clear.rect.update(px, b2, W, self._BTN_H)
        self.btn_save.rect.update(px,        b3, SW, self._BTN_H)
        self.btn_load.rect.update(px + SW+4, b3, SW, self._BTN_H)
        bc_y = b3 + self._BTN_H + self._BTN_GAP + 8
        self.btn_begin_combat.rect.update(px, bc_y, W, self._BTN_H)
        ter_y = bc_y + self._BTN_H + self._BTN_GAP
        self.btn_edit_terrain.rect.update(px, ter_y, W, self._BTN_H)
        # Update combat panel button x-positions (y is fixed by _draw_combat_panel)
        HW2 = W // 2 - 2
        TW3 = (W - 8) // 3
        self.btn_cbt_atk_action.rect.update( px,           self.btn_cbt_atk_action.rect.y,  HW2, self._BTN_H)
        self.btn_cbt_pass_action.rect.update(px+HW2+4,     self.btn_cbt_pass_action.rect.y, HW2, self._BTN_H)
        self.btn_cbt_dash.rect.update(       px,           self.btn_cbt_dash.rect.y,       TW3, self._BTN_H)
        self.btn_cbt_dodge.rect.update(      px+TW3+4,     self.btn_cbt_dodge.rect.y,      TW3, self._BTN_H)
        self.btn_cbt_disengage.rect.update(  px+2*(TW3+4), self.btn_cbt_disengage.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_atk_bonus.rect.update(   px,           self.btn_cbt_atk_bonus.rect.y,   TW3, self._BTN_H)
        self.btn_cbt_spell_bonus.rect.update( px+TW3+4,    self.btn_cbt_spell_bonus.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_pass_bonus.rect.update(  px+2*(TW3+4),self.btn_cbt_pass_bonus.rect.y,   TW3, self._BTN_H)
        self.btn_cbt_spell_action.rect.update(px,          self.btn_cbt_spell_action.rect.y,  W,  self._BTN_H)
        self.btn_cbt_end_turn.rect.update(    px,          self.btn_cbt_end_turn.rect.y,       W,  self._BTN_H)
        self.btn_cbt_end_combat.rect.update(  px,          self.btn_cbt_end_combat.rect.y,     W,  self._BTN_H)

    def _init_combat_panel(self):
        """Create the buttons shown exclusively in the combat panel."""
        px  = self._panel_x() + self._PANEL_PAD
        W   = PANEL_W - self._PANEL_PAD * 2
        HW  = W // 2 - 2
        B   = self._BTN_H

        # Dummy Y (will be set in _draw_combat_panel)
        dummy_y = 0

        self.btn_cbt_atk_action  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Attack",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_action = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_dash        = Button(pygame.Rect(px,               dummy_y, HW, B),
                                          "Dash",
                                          COL_BTN_DASH, COL_BTN_DASH_HOV, self.font_md)
        self.btn_cbt_dodge       = Button(pygame.Rect(px+HW+4,         dummy_y, HW, B),
                                          "Dodge",
                                          COL_BTN_DODGE, COL_BTN_DODGE_HOV, self.font_md)
        self.btn_cbt_disengage   = Button(pygame.Rect(px,     dummy_y, HW, B),
                                          "Disengage",
                                          COL_BTN_DISENG, COL_BTN_DISENG_HOV, self.font_md)
        self.btn_cbt_atk_bonus   = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Bonus Atk",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_bonus  = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_spell_action= Button(pygame.Rect(px, dummy_y, W, B),
                                          "✨ Cast Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_spell_bonus = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "✨ Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_long_jump   = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Long Jump",
                                          (100, 150, 200), (120, 170, 220), self.font_md)
        self.btn_cbt_end_turn    = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Turn",
                                          COL_BTN_ENDTURN, COL_BTN_ENDTURN_HOV, self.font_md)
        self.btn_cbt_place_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "🌍 Place Terrain",
                                          (150, 120, 80), (180, 150, 110), self.font_md)
        self.btn_cbt_end_combat  = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Combat",
                                          COL_BTN_DANGER, (180, 70, 70), self.font_md)

    # ─────────────────────────────────────────────────────────────────────
    #  Sprite loading (cached)
    # ─────────────────────────────────────────────────────────────────────
    def _get_sprite(self, path: str, size_px: int) -> pygame.Surface | None:
        key = (path, size_px)
        if key not in self.sprites:
            if path and os.path.exists(path):
                try:
                    raw = pygame.image.load(path).convert_alpha()
                    self.sprites[key] = pygame.transform.smoothscale(
                        raw, (size_px, size_px))
                except Exception:
                    self.sprites[key] = None
            else:
                self.sprites[key] = None
        return self.sprites[key]

    def _get_mob_sprite_path(self, mob_name: str) -> str:
        """Determine sprite path for a mob: use specific sprite if it exists, otherwise use first letter."""
        specific_path = os.path.join(self.sprites_dir, f"{mob_name}.png")
        if os.path.exists(specific_path):
            return specific_path
        return os.path.join(self.sprites_dir, f"{mob_name[0].upper()}.png")

    def _on_mob_selected(self, mob_name: str):
        """Callback when a mob is selected from the dialog."""
        self.inp_name.text = mob_name
        self.inp_sprite.text = self._get_mob_sprite_path(mob_name)
        # Load stats from JSON
        if mob_name in self.mob_stats_json:
            self.selected_mob_stats = self.mob_stats_json[mob_name]
        else:
            self.selected_mob_stats = None

    def _mob_stats_to_d_d_stats(self, mob_data: dict):
        """Convert CSV mob stats to D&D 5e agent stats."""
        stats = rpg.Stats()

        # Convert ability modifiers to ability scores: score = (mod * 2) + 10
        def mod_to_score(mod_str):
            try:
                mod = int(mod_str) if mod_str else 0
                return (mod * 2) + 10
            except (ValueError, TypeError):
                return 10

        stats.str  = mod_to_score(mob_data.get('STR Mod'))
        stats.dex  = mod_to_score(mob_data.get('DEX Mod'))
        stats.con  = mod_to_score(mob_data.get('CON Mod'))
        stats.intel = mod_to_score(mob_data.get('INT Mod'))
        stats.wis  = mod_to_score(mob_data.get('WIS Mod'))
        stats.cha  = mod_to_score(mob_data.get('CHA Mod'))

        # HP, AC, and speeds
        try:
            stats.hp_max = int(mob_data.get('HP', '10'))
            stats.hp_cur = stats.hp_max
        except (ValueError, TypeError):
            stats.hp_max = stats.hp_cur = 10

        try:
            stats.ac = int(mob_data.get('AC', '10'))
        except (ValueError, TypeError):
            stats.ac = 10

        try:
            stats.speed_walk = int(mob_data.get('Walk', '30'))
        except (ValueError, TypeError):
            stats.speed_walk = 30

        try:
            stats.speed_fly = int(mob_data.get('Fly', '0'))
        except (ValueError, TypeError):
            stats.speed_fly = 0

        try:
            stats.speed_swim = int(mob_data.get('Swim', '0'))
        except (ValueError, TypeError):
            stats.speed_swim = 0

        try:
            stats.speed_burrow = int(mob_data.get('Burrow', '0'))
        except (ValueError, TypeError):
            stats.speed_burrow = 0

        return stats

    # ─────────────────────────────────────────────────────────────────────
    #  Grid coordinate helpers
    # ─────────────────────────────────────────────────────────────────────
    def _screen_to_cell(self, sx, sy):
        """Convert a screen pixel position to a grid Cell, or None if outside."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return None
        # Unscale back to original image space
        ix = sx / s
        iy = sy / s
        # Binary-search which column/row we're in
        import bisect
        c = bisect.bisect_right(raw_v, ix) - 1
        r = bisect.bisect_right(raw_h, iy) - 1
        if 0 <= c < self.bm.grid_cols and 0 <= r < self.bm.grid_rows:
            return rpg.Cell(c, r)
        return None

    def _cell_to_screen(self, col, row):
        """Return top-left screen pixel of a grid cell."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        return int(raw_v[col] * s), int(raw_h[row] * s)

    def _agent_at(self, cell):
        """Return index of the placed agent whose footprint contains cell, or -1."""
        for i, pt in enumerate(self.bm.placed_agents):
            oc, or_ = pt.origin.col, pt.origin.row
            if oc <= cell.col < oc + pt.size and or_ <= cell.row < or_ + pt.size:
                return i
        return -1

    def _can_place(self, cell, size, exclude_idx=-1):
        """Return True if a size×size agent can be placed with top-left at cell."""
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        if cell.col < 0 or cell.row < 0:
            return False
        if cell.col + size > cols or cell.row + size > rows:
            return False
        if self.bm.is_blocked(cell, size):
            return False
        # Check overlap with other agents
        for i, pt in enumerate(self.bm.placed_agents):
            if i == exclude_idx:
                continue
            if (cell.col < pt.origin.col + pt.size and
                    cell.col + size > pt.origin.col and
                    cell.row < pt.origin.row + pt.size and
                    cell.row + size > pt.origin.row):
                return False
        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Save / Load
    # ─────────────────────────────────────────────────────────────────────
    # ── Save / load callbacks called by the file browser ─────────────────────
    def _on_save_path_chosen(self, path: str):
        self._save_path = path
        self._save_agents(path)

    def _on_load_path_chosen(self, path: str):
        self._save_path = path
        self._load_agents(path)

    def _update_reach(self):
        """Recompute walk/fly reachable-cell overlays for the selected agent.

        In combat mode the budget comes from CombatEngine so it shrinks as the
        agent moves.  Outside combat the full stat speed is used.
        """
        self._reach_walk   = []
        self._reach_fly    = []
        self._reach_swim   = []
        self._reach_burrow = []
        self._reach_set    = set()
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        pt    = self.bm.placed_agents[idx]
        stats = self.bm.get_agent_stats(idx)

        if self.combat_active:
            walk_ft   = self.move_remaining_walk
            fly_ft    = self.move_remaining_fly
            swim_ft   = self.move_remaining_swim
            burrow_ft = self.move_remaining_burrow
        else:
            walk_ft   = stats.speed_walk
            fly_ft    = stats.speed_fly
            swim_ft   = stats.speed_swim
            burrow_ft = stats.speed_burrow

        if walk_ft > 0:
            self._reach_walk = self.bm.reachable_cells(
                pt.origin, pt.size, walk_ft, rpg.MovementType.Walk)
        if fly_ft > 0:
            self._reach_fly = self.bm.reachable_cells(
                pt.origin, pt.size, fly_ft, rpg.MovementType.Fly)
        if swim_ft > 0:
            self._reach_swim = self.bm.reachable_cells(
                pt.origin, pt.size, swim_ft, rpg.MovementType.Walk)
        if burrow_ft > 0:
            self._reach_burrow = self.bm.reachable_cells(
                pt.origin, pt.size, burrow_ft, rpg.MovementType.Walk)

        # Drag validity uses only the selected movement type's reach.
        _reach_by_type = {
            rpg.MovementType.Walk:   self._reach_walk,
            rpg.MovementType.Fly:    self._reach_fly,
            rpg.MovementType.Swim:   self._reach_swim,
            rpg.MovementType.Burrow: self._reach_burrow,
        }
        self._reach_set = {(c.col, c.row)
                           for c in _reach_by_type.get(self.move_type, [])}

    def _on_stats_ok(self, agent_idx: int, steppers: dict, prof_flags: dict):
        """Called by StatsDialog when the user clicks OK."""
        # Start from current stats so flags not shown in the dialog are preserved.
        stats = self.bm.get_agent_stats(agent_idx)
        stats.str        = steppers["str"].value
        stats.dex        = steppers["dex"].value
        stats.con        = steppers["con"].value
        stats.intel      = steppers["intel"].value
        stats.wis        = steppers["wis"].value
        stats.cha        = steppers["cha"].value
        stats.hp_cur     = steppers["hp_cur"].value
        stats.hp_max     = steppers["hp_max"].value
        stats.ac         = steppers["ac"].value
        stats.speed_walk   = steppers["speed_walk"].value
        stats.speed_swim   = steppers["speed_swim"].value
        stats.speed_fly    = steppers["speed_fly"].value
        stats.speed_burrow = steppers["speed_burrow"].value
        stats.prof_bonus   = steppers["prof_bonus"].value
        stats.num_attacks  = steppers["num_attacks"].value
        # Saving throw proficiency per ability
        stats.save_prof_str   = prof_flags.get("save_prof_str",   False)
        stats.save_prof_dex   = prof_flags.get("save_prof_dex",   False)
        stats.save_prof_con   = prof_flags.get("save_prof_con",   False)
        stats.save_prof_intel = prof_flags.get("save_prof_intel", False)
        stats.save_prof_wis   = prof_flags.get("save_prof_wis",   False)
        stats.save_prof_cha   = prof_flags.get("save_prof_cha",   False)
        self.bm.set_agent_stats(agent_idx, stats)
        if agent_idx == self.selected_idx:
            self._update_reach()

    # ── Weapon callbacks & overlays ───────────────────────────────────────────

    def _on_weapon_done(self, agent_idx: int, weapons: list[dict]):
        """Called by WeaponDialog when the user clicks Done.

        `weapons` is a list of plain dicts (the WeaponDialog's internal format).
        Convert each to an rpg.Weapon and push the list into the C++ layer.
        """
        cpp_weapons = [_dict_to_weapon(d) for d in weapons]
        self.bm.set_agent_weapons(agent_idx, cpp_weapons)
        # Refresh attack overlay if this is the currently selected agent.
        if agent_idx == self.selected_idx:
            self._update_attack_overlay()

    def _update_attack_overlay(self):
        """Recompute attack-range overlays for the selected agent's weapons."""
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        weapons = self.bm.get_agent_weapons(idx)   # list[rpg.Weapon] from C++
        if not weapons:
            return
        pt = self.bm.placed_agents[idx]
        melee_cells:  set[tuple[int, int]] = set()
        rnorm_cells:  set[tuple[int, int]] = set()
        rlongx_cells: set[tuple[int, int]] = set()  # long-range-only

        for w in weapons:
            if w.type == rpg.WeaponType.Melee:
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.reach_ft):
                    melee_cells.add((c.col, c.row))
            else:  # Ranged
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.normal_range_ft):
                    rnorm_cells.add((c.col, c.row))
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.long_range_ft):
                    if (c.col, c.row) not in rnorm_cells:
                        rlongx_cells.add((c.col, c.row))

        # Convert back to Cell-like objects (just store as (col,row) dicts
        # to avoid depending on rpg.Cell construction in a hot path).
        def _as_cells(s):
            return [rpg.Cell(c, r) for c, r in s]

        self._attack_cells_melee = _as_cells(melee_cells)
        self._attack_cells_rnorm = _as_cells(rnorm_cells)
        self._attack_cells_rlong = _as_cells(rlongx_cells)

    # ─────────────────────────────────────────────────────────────────────
    #  Combat widget helpers
    # ─────────────────────────────────────────────────────────────────────

    def _current_agent_idx(self) -> int:
        """Return the BattleMap index of the currently acting combatant, or -1."""
        if not self.combat_active or not self.initiative_order:
            return -1
        return self.initiative_order[self.turn_idx].agent_idx

    def _reset_movement(self, agent_idx: int):
        """Seed this turn's movement budgets from the agent's stats."""
        if 0 <= agent_idx < len(self.bm.placed_agents):
            stats  = self.bm.get_agent_stats(agent_idx)
            agent  = self.bm.placed_agents[agent_idx]
            walk   = stats.speed_walk
            fly    = stats.speed_fly
            swim   = stats.speed_swim
            burrow = stats.speed_burrow
            self.move_remaining_walk   = walk
            self.move_remaining_fly    = fly
            self.move_remaining_swim   = swim
            self.move_remaining_burrow = burrow
            agent.init_movement(walk, fly, swim, burrow)
        else:
            self.move_remaining_walk   = 0
            self.move_remaining_fly    = 0
            self.move_remaining_swim   = 0
            self.move_remaining_burrow = 0
        # Default to Walk; fall back to first available type if walk speed is 0.
        if self.move_remaining_walk > 0:
            self.move_type = rpg.MovementType.Walk
        elif self.move_remaining_fly > 0:
            self.move_type = rpg.MovementType.Fly
        elif self.move_remaining_swim > 0:
            self.move_type = rpg.MovementType.Swim
        else:
            self.move_type = rpg.MovementType.Burrow
        self.last_movement_dist = 0
        self.jump_overlay_active = False
        self.jump_reachable_cells = set()

    def _toggle_jump_overlay(self):
        """Toggle the jump overlay visibility and recalculate if needed."""
        if self.jump_overlay_active:
            self.jump_overlay_active = False
            self.jump_reachable_cells = []
        else:
            self._update_jump_reachable()
            self.jump_overlay_active = True

    def _update_jump_reachable(self):
        """Calculate cells reachable by long jump from current agent."""
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return

        agent = self.bm.placed_agents[idx]
        stats = self.bm.get_agent_stats(idx)
        strength = stats.str

        if strength <= 0:
            return

        # Determine if running or standing jump (based on most recent movement)
        is_running_jump = self.last_movement_dist >= 10
        max_jump_dist = strength if is_running_jump else (strength // 2)

        # Calculate reachable cells (Manhattan distance from current position, ignoring walls)
        origin = agent.origin
        for dr in range(-max_jump_dist, max_jump_dist + 1):
            for dc in range(-max_jump_dist, max_jump_dist + 1):
                manhattan_dist = abs(dc) + abs(dr)
                if manhattan_dist == 0:
                    continue  # Can't jump to current cell
                if manhattan_dist > max_jump_dist:
                    continue

                target_cell = rpg.Cell(origin.col + dc, origin.row + dr)
                # Add cells within Manhattan distance (visualization will skip invalid ones)
                self.jump_reachable_cells.append(target_cell)

    def _execute_jump(self, agent_idx: int, target_cell):
        """Execute a jump to the target cell, deducting movement."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return

        # Refresh agent reference to ensure we have current position
        agent = self.bm.placed_agents[agent_idx]
        stats = self.bm.get_agent_stats(agent_idx)

        # Calculate jump distance for logging (from current position to target)
        jump_dist = (abs(target_cell.col - agent.origin.col) +
                     abs(target_cell.row - agent.origin.row)) * 5

        # Determine if running or standing jump based on most recent movement
        is_running = self.last_movement_dist >= 10

        # Execute jump (C++ handles all budget deductions)
        if self.bm.jump_agent(agent_idx, target_cell, is_running):
            # Update remaining movement values
            ag = self.bm.placed_agents[agent_idx]
            self.move_remaining_walk = ag.walk_remaining
            self.move_remaining_fly = ag.fly_remaining
            self.move_remaining_swim = ag.swim_remaining
            self.move_remaining_burrow = ag.burrow_remaining
            self.last_movement_dist = 0  # Reset run-up after jump
            jump_type = "running" if is_running else "standing"
            self._combat_log_add(f"{agent.name}: {jump_type.capitalize()} long jump (+{jump_dist}ft)")
            self._update_reach()
            self._update_jump_reachable()
        else:
            # Jump failed - out of range or insufficient movement
            strength = stats.str
            max_dist = strength if is_running else (strength // 2)
            self._combat_log_add(f"{agent.name}: Jump out of range ({jump_dist}ft > {max_dist}ft)")

    def _start_combat(self):
        """Roll initiative and enter combat mode."""
        if not self.bm.placed_agents:
            return
        order = list(self.combat.roll_initiative(self.bm))
        if not order:
            return
        self.initiative_order    = order
        self.combat_active       = True
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot  = ""
        self.attacks_remaining    = 0
        self.pending_spell_slot   = ""
        self.pending_spell_is_aoe = False
        self.combat_log           = []
        self._effect_meta         = {}
        self.bm.clear_terrain_effects()
        first = self._current_agent_idx()
        self.selected_idx = first
        self._reset_movement(first)
        self._update_reach()
        self._update_attack_overlay()
        print(f"[COMBAT START] Initiative order: {[(e.total, self.bm.placed_agents[e.agent_idx].name) for e in order]}")
        print(f"[COMBAT START] First turn: agent_idx={first}, name={self.bm.placed_agents[first].name if 0 <= first < len(self.bm.placed_agents) else '?'}")

    def _end_combat(self):
        """Leave combat mode and clear all combat state."""
        self.move_remaining_walk   = 0
        self.move_remaining_fly    = 0
        self.move_remaining_swim   = 0
        self.move_remaining_burrow = 0
        self.move_type             = rpg.MovementType.Walk
        self.combat_active         = False
        self.initiative_order    = []
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot  = ""
        self.attacks_remaining    = 0
        self.pending_spell_slot   = ""
        self.pending_spell_is_aoe = False
        self.selected_idx         = -1
        self._reach_walk         = []
        self._reach_fly          = []
        self._reach_set          = set()
        self._effect_meta         = {}
        self.bm.clear_terrain_effects()
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _advance_turn(self):
        """Advance to the next living combatant in initiative order."""
        if not self.initiative_order:
            return
        n = len(self.initiative_order)
        prev_turn_idx = self.turn_idx
        for _ in range(n):
            self.turn_idx = (self.turn_idx + 1) % n
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                stats = self.bm.get_agent_stats(idx)
                if stats.hp_cur > 0:
                    break

        # Round advancement: when turn_idx wraps to 0
        if self.turn_idx < prev_turn_idx:
            self.round_num += 1
            # Tick DM-placed effects at round boundary
            expired_dm = self.bm.tick_dm_terrain_effects()
            for effect_id in expired_dm:
                if effect_id in self._effect_meta:
                    effect_name = self._effect_meta[effect_id].get("name", "Effect")
                    self._combat_log_add(f"{effect_name} fades.")
                    del self._effect_meta[effect_id]

        # Reset action economy and per-turn conditions for the new combatant.
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot  = ""
        self.attacks_remaining    = 0
        self.pending_spell_slot   = ""
        self.pending_spell_is_aoe = False
        new_idx = self._current_agent_idx()
        self.selected_idx = new_idx

        # Tick terrain effects for this agent's source
        if 0 <= new_idx < len(self.bm.placed_agents):
            self.bm.placed_agents[new_idx].turn()
            expired_agent = self.bm.tick_terrain_effects(new_idx)
            for effect_id in expired_agent:
                if effect_id in self._effect_meta:
                    effect_name = self._effect_meta[effect_id].get("name", "Effect")
                    self._combat_log_add(f"{effect_name} fades.")
                    del self._effect_meta[effect_id]

        self._reset_movement(new_idx)
        self._update_reach()
        self._update_attack_overlay()

    def _combat_log_add(self, msg: str):
        self.combat_log.insert(0, msg)
        if len(self.combat_log) > 10:
            self.combat_log.pop()

    def _start_attack(self, slot: str):
        """Begin target-selection for an attack in the given slot."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        # Don't re-enter while a multi-attack sequence is already in flight —
        # that would reset attacks_remaining and grant unlimited attacks.
        if self.pending_attack_slot:
            # print(f"[DEBUG _start_attack] ignored: attack already pending (slot={self.pending_attack_slot}, attacks_remaining={self.attacks_remaining})")
            return
        weapons = self.bm.get_agent_weapons(idx)
        if not weapons:
            self._combat_log_add("No weapons equipped!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return
        stats = self.bm.get_agent_stats(idx)
        n_atk = stats.num_attacks if slot == "action" else 1
        self.attacks_remaining = n_atk
        # print(f"[DEBUG _start_attack] idx={idx} slot={slot} stats.num_attacks={stats.num_attacks} n_atk={n_atk} attacks_remaining={self.attacks_remaining}")

        def _activate(s, wi_):
            self.pending_attack_slot = s
            self.pending_weapon_idx  = wi_
            rem = self.attacks_remaining
            # print(f"[DEBUG _activate] slot={s} weapon_idx={wi_} attacks_remaining={rem}")
            suffix = f" ({rem} attack{'s' if rem != 1 else ''} remaining)"
            self._combat_log_add(f"Click a target on the map.{suffix}")

        if len(weapons) == 1:
            _activate(slot, 0)
        else:
            options = []
            for wi, w in enumerate(weapons):
                def _pick(s=slot, wi_=wi):
                    _activate(s, wi_)
                options.append((w.name, _pick))
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _resolve_combat_attack(self, target_idx: int):
        """Resolve the pending attack against target_idx."""
        atk_idx = self._current_agent_idx()
        slot    = self.pending_attack_slot
        # print(f"[DEBUG _resolve_combat_attack ENTER] atk_idx={atk_idx} target_idx={target_idx} slot={slot} pending_weapon_idx={self.pending_weapon_idx} attacks_remaining={self.attacks_remaining}")
        if atk_idx < 0 or not slot:
            # print(f"[DEBUG _resolve_combat_attack] early return (atk_idx<0 or no slot)")
            return
        action = rpg.Attack(atk_idx, target_idx, self.pending_weapon_idx)
        result = self.combat.execute_action(self.bm, action)
        # print(f"[DEBUG _resolve_combat_attack] result.valid={result.valid} result.hit={getattr(result,'hit',None)} total_damage={getattr(result,'total_damage',None)} target_down={getattr(result,'target_down',None)}")

        agents   = self.bm.placed_agents
        atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
        tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

        if not result.valid:
            self._combat_log_add(f"{atk_name}: out of range")
            self.pending_attack_slot = ""
            self.attacks_remaining   = 0
            return

        if result.hit:
            dmg_parts = ([v.name for v in result.physical_damage_types] +
                         [v.name for v in result.magic_damage_types])
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            msg = (f"{atk_name}→{tgt_name}: "
                   f"HIT {result.total_damage} {dmg_type_str}"
                   f"{' CRIT!' if result.critical else ''}"
                   f"{' — DOWN' if result.target_down else ''}")
        else:
            msg = (f"{atk_name}→{tgt_name}: "
                   f"miss (roll {result.total_roll} vs AC {result.target_ac})")
        self._combat_log_add(msg)

        self.attacks_remaining -= 1
        # print(f"[DEBUG _resolve_combat_attack] decremented attacks_remaining -> {self.attacks_remaining}")
        if self.attacks_remaining > 0:
            rem = self.attacks_remaining
            # print(f"[DEBUG _resolve_combat_attack] more attacks left, keeping slot pending: {self.pending_attack_slot}")
            self._combat_log_add(
                f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — click another target.")
        else:
            # print(f"[DEBUG _resolve_combat_attack] attacks exhausted; clearing slot, marking {slot}_used")
            self.pending_attack_slot = ""
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
        # Refresh attack overlay (HP may have changed).
        self._update_attack_overlay()

    def _on_spell_done(self, agent_idx: int, spells: list[dict]):
        cpp_spells = [_dict_to_spell(d) for d in spells]
        self.bm.set_agent_spells(agent_idx, cpp_spells)

    def _start_cast_spell(self, slot: str):
        self.jump_overlay_active = False  # Close jump overlay when casting spell
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if idx < 0:
            return
        spells = self.bm.get_agent_spells(idx)
        if not spells:
            self._combat_log_add("No spells known!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return
        def _activate(s, si_):
            sp_ = spells[si_]
            is_aoe = sp_.geometry != rpg.SpellGeometry.Single
            self.pending_spell_slot   = s
            self.pending_spell_idx    = si_
            self.pending_spell_is_aoe = is_aoe
            hint = "click a map location" if is_aoe else "click a target"
            self._combat_log_add(f"Casting {sp_.name} — {hint}.")

        if len(spells) == 1:
            _activate(slot, 0)
        else:
            options = []
            for si, sp in enumerate(spells):
                def _pick(s=slot, si_=si):
                    _activate(s, si_)
                options.append((sp.name, _pick))
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _log_spell_results(self, result, cast_name: str):
        agents = self.bm.placed_agents
        for tr in result.target_results:
            tgt_name = agents[tr.target_idx].name if 0 <= tr.target_idx < len(agents) else "?"
            if result.attack_type == rpg.SpellAttack.AttackRoll:
                if tr.hit:
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"{'CRIT! ' if tr.critical else ''}"
                           f"{'HEAL' if tr.total_healing else 'HIT'} "
                           f"{tr.total_healing or tr.total_damage}"
                           f"{' — DOWN' if tr.target_down else ''}")
                else:
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"miss (roll {tr.total_roll} vs AC {tr.target_ac})")
            elif result.attack_type == rpg.SpellAttack.Save:
                saved_str = " (saved — half)" if tr.saved else ""
                if tr.total_healing:
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"HEAL {tr.total_healing}{saved_str}")
                else:
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"{tr.total_damage} dmg{saved_str}"
                           f"{' — DOWN' if tr.target_down else ''}")
            else:  # Automatic
                if tr.total_healing:
                    msg = f"{cast_name}→{tgt_name}: {result.spell_name} HEAL {tr.total_healing}"
                else:
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"{tr.total_damage} dmg"
                           f"{' — DOWN' if tr.target_down else ''}")
            self._combat_log_add(msg)

    def _resolve_spell_cast(self, target_idx: int):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return
        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.target_indices = [target_idx]
        result = self.combat.execute_spell(self.bm, action)
        self.pending_spell_slot   = ""
        self.pending_spell_is_aoe = False
        self.spell_hover_cell     = None

        agents    = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        if not result.valid:
            self._combat_log_add(f"{cast_name}: spell failed (invalid)")
            return
        self._log_spell_results(result, cast_name)
        if slot == "action":
            self.action_used = True
        else:
            self.bonus_used = True

    def _resolve_spell_cast_aoe(self, cell):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return
        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.target_indices = []
        action.aoe_col        = cell.col
        action.aoe_row        = cell.row
        result = self.combat.execute_spell(self.bm, action)
        self.pending_spell_slot   = ""
        self.pending_spell_is_aoe = False
        self.spell_hover_cell     = None

        agents    = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        if not result.valid:
            self._combat_log_add(f"{cast_name}: spell failed (invalid)")
            return
        if not result.target_results:
            self._combat_log_add(f"{cast_name}: {result.spell_name} — no targets in area")
        else:
            self._log_spell_results(result, cast_name)

        # Auto-place terrain effect if spell has one
        if 0 <= caster_idx < len(agents) and 0 <= self.pending_spell_idx < len(agents[caster_idx].spells):
            spell = agents[caster_idx].spells[self.pending_spell_idx]
            if spell.terrain_difficulty != rpg.TerrainDifficulty.Normal:
                aoe_cells = self._aoe_cells(cell, spell)
                if aoe_cells:
                    effect_id = self.bm.place_terrain_effect(
                        spell.name,
                        aoe_cells,
                        spell.terrain_difficulty,
                        spell.duration,
                        caster_idx
                    )
                    if effect_id >= 0:
                        # Store metadata for rendering
                        if spell.terrain_difficulty == rpg.TerrainDifficulty.Halved:
                            color = (80, 200, 80, 80)  # Green
                        elif spell.terrain_difficulty == rpg.TerrainDifficulty.Quartered:
                            color = (200, 60, 60, 80)  # Red
                        else:
                            color = (100, 180, 220, 80)  # Cyan
                        self._effect_meta[effect_id] = {
                            "name": spell.name,
                            "color": color,
                            "cells": [(c.col, c.row) for c in aoe_cells]
                        }
                        self._combat_log_add(f"{spell.name} terrain effect placed.")
        if slot == "action":
            self.action_used = True
        else:
            self.bonus_used = True

    def _aoe_cells(self, center_cell, spell) -> list:
        """Return list of rpg.Cell objects covered by the spell AoE (1 cell = 5 ft)."""
        import math
        geo   = spell.geometry
        cols  = self.bm.grid_cols
        rows  = self.bm.grid_rows
        cells = []
        ax = float(center_cell.col)
        ay = float(center_cell.row)

        if geo == rpg.SpellGeometry.Sphere:
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    dx, dy = c - ax, r - ay
                    if math.sqrt(dx*dx + dy*dy) <= r_cells:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Cone:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    plen = math.sqrt(px*px + py*py)
                    if plen < 0.001:
                        continue
                    dot = px*ux + py*uy
                    if dot > 0 and plen <= r_cells and (dot/plen) >= 0.866:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Line:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            l_cells = spell.length / 5.0
            w_cells = spell.width  / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    along = px*ux + py*uy
                    perp  = abs(-py*ux + px*uy)
                    if 0.0 <= along <= l_cells and perp <= w_cells / 2.0:
                        cells.append(rpg.Cell(c, r))

        return cells

    def _draw_spell_aoe_preview(self, cpx: int):
        """Translucent AoE highlight while the player is aiming a non-Single spell."""
        if not self.pending_spell_is_aoe or self.spell_hover_cell is None:
            return
        caster_idx = self._current_agent_idx()
        if caster_idx < 0:
            return
        spells = self.bm.get_agent_spells(caster_idx)
        if not (0 <= self.pending_spell_idx < len(spells)):
            return
        sp    = spells[self.pending_spell_idx]
        cells = self._aoe_cells(self.spell_hover_cell, sp)

        fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_s.fill((160, 80, 220, 60))
        border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_s, (200, 130, 255, 160), border_s.get_rect(), 1)

        cell_set = {(c.col, c.row) for c in cells}
        for c in cells:
            sx, sy = self._cell_to_screen(c.col, c.row)
            self.screen.blit(fill_s,   (sx, sy))
            self.screen.blit(border_s, (sx, sy))

        # Orange ring around each agent caught in the blast
        for pt in self.bm.placed_agents:
            if (pt.origin.col, pt.origin.row) in cell_set:
                size_px = cpx * pt.size
                sx, sy  = self._cell_to_screen(pt.origin.col, pt.origin.row)
                pygame.draw.rect(self.screen, (255, 140, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # Bright white outline on the aimed cell
        ax, ay = self._cell_to_screen(self.spell_hover_cell.col,
                                      self.spell_hover_cell.row)
        pygame.draw.rect(self.screen, (255, 255, 255),
                         pygame.Rect(ax, ay, cpx, cpx), 2)

    def _draw_attack_overlays(self, cpx: int):
        """Draw melee / ranged-normal / ranged-long attack-range overlays."""
        def _draw_zone(cells, fill_rgba, border_rgba):
            if not cells:
                return
            fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_s.fill(fill_rgba)
            border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_s, border_rgba, border_s.get_rect(), 1)
            for cell in cells:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(fill_s,   (sx, sy))
                self.screen.blit(border_s, (sx, sy))

        # Melee: warm red
        _draw_zone(self._attack_cells_melee, (200, 55, 55, 70), (255, 100, 100, 150))
        # Ranged normal: orange
        _draw_zone(self._attack_cells_rnorm, (200, 120, 40, 55), (255, 165, 60, 130))
        # Ranged long (disadvantage): dull yellow
        _draw_zone(self._attack_cells_rlong, (180, 165, 40, 35), (220, 200, 60, 90))

    def _save_agents(self, path: str | None = None):
        path = path or self._save_path
        data = []
        for i, pt in enumerate(self.bm.placed_agents):
            s = self.bm.get_agent_stats(i)
            data.append({
                "name":        pt.name,
                "sprite_path": pt.sprite_path,
                "size":        pt.size,
                "col":         pt.origin.col,
                "row":         pt.origin.row,
                "stats": {
                    "str": s.str, "dex": s.dex, "con": s.con,
                    "intel": s.intel, "wis": s.wis, "cha": s.cha,
                    "hp_max": s.hp_max, "hp_cur": s.hp_cur,
                    "ac": s.ac,
                    "speed_walk": s.speed_walk, "speed_swim": s.speed_swim,
                    "speed_fly":  s.speed_fly,  "speed_burrow": s.speed_burrow,
                    "prof_bonus": s.prof_bonus,
                    "save_prof_str":   s.save_prof_str,
                    "save_prof_dex":   s.save_prof_dex,
                    "save_prof_con":   s.save_prof_con,
                    "save_prof_intel": s.save_prof_intel,
                    "save_prof_wis":   s.save_prof_wis,
                    "save_prof_cha":      s.save_prof_cha,
                    "num_attacks":        s.num_attacks,
                    "has_cunning_action": s.has_cunning_action,
                    "has_offhand_attack": s.has_offhand_attack,
                    "can_cast_spell":     s.can_cast_spell,
                    "spellcasting_ability": _INT_TO_ABILITY.get(s.spellcasting_ability, "cha"),
                },
                "weapons": [_weapon_to_dict(w)
                            for w in self.bm.get_agent_weapons(i)],
                "spells":  [_spell_to_dict(s)
                            for s in self.bm.get_agent_spells(i)],
            })
        with open(path, "w") as f:
            json.dump({"agents": data}, f, indent=2)

    def _load_agents(self, path: str | None = None):
        path = path or self._save_path
        if not os.path.exists(path):
            return
        with open(path) as f:
            data = json.load(f)
        self.bm.clear_agents()
        self.pending_configs.clear()
        self.selected_idx = -1
        self.drag_idx     = -1
        agent_data = data.get("agents", [])
        for t in agent_data:
            cfg = rpg.AgentConfig()
            cfg.name        = t["name"]
            cfg.sprite_path = t.get("sprite_path", "")
            cfg.size        = t["size"]
            cfg.start_col   = t["col"]
            cfg.start_row   = t["row"]
            self.bm.add_agent_config(cfg)
            self.pending_configs.append(cfg)
        self.bm.apply_agent_configs()
        self.sprites.clear()
        # Restore stats for each placed agent
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            sd = t.get("stats")
            if not sd:
                continue
            s = rpg.Stats()
            s.str        = sd.get("str",        10)
            s.dex        = sd.get("dex",        10)
            s.con        = sd.get("con",        10)
            s.intel      = sd.get("intel",      10)
            s.wis        = sd.get("wis",        10)
            s.cha        = sd.get("cha",        10)
            s.hp_max     = sd.get("hp_max",     10)
            s.hp_cur     = sd.get("hp_cur",     10)
            s.ac         = sd.get("ac",         10)
            s.speed_walk   = sd.get("speed_walk",   30)
            s.speed_swim   = sd.get("speed_swim",    0)
            s.speed_fly    = sd.get("speed_fly",     0)
            s.speed_burrow = sd.get("speed_burrow",  0)
            s.prof_bonus       = sd.get("prof_bonus",      2)
            s.save_prof_str    = sd.get("save_prof_str",   False)
            s.save_prof_dex    = sd.get("save_prof_dex",   False)
            s.save_prof_con    = sd.get("save_prof_con",   False)
            s.save_prof_intel  = sd.get("save_prof_intel", False)
            s.save_prof_wis    = sd.get("save_prof_wis",   False)
            s.save_prof_cha       = sd.get("save_prof_cha",         False)
            s.num_attacks         = int(sd.get("num_attacks",        1))
            s.has_cunning_action  = sd.get("has_cunning_action",    False)
            s.has_offhand_attack  = sd.get("has_offhand_attack",    False)
            s.can_cast_spell      = sd.get("can_cast_spell",        False)
            s.spellcasting_ability = _ABILITY_TO_INT.get(sd.get("spellcasting_ability", "cha"), 5)
            self.bm.set_agent_stats(i, s)

        # Restore weapons — convert saved dicts → rpg.Weapon, push into C++.
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_weapons = [_dict_to_weapon(d) for d in t.get("weapons", [])]
            self.bm.set_agent_weapons(i, cpp_weapons)

        # Restore spells — convert saved dicts → rpg.Spell, push into C++.
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_spells = [_dict_to_spell(d) for d in t.get("spells", [])]
            self.bm.set_agent_spells(i, cpp_spells)

        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _load_terrain(self):
        """Load terrain data from JSON file if it exists.

        If the file doesn't exist on first load, terrain starts empty.
        User can manually label terrain using the terrain editor,
        or choose to auto-detect walls as a fallback.
        """
        if os.path.exists(self._terrain_path):
            try:
                with open(self._terrain_path, 'r') as f:
                    data = json.load(f)
                self._terrain_regions = data.get("regions", [])
                self._apply_terrain_to_battle_map()
            except Exception:
                self._terrain_regions = []
        else:
            # First load: start with empty terrain, user can manually label or auto-detect later
            self._terrain_regions = []

    def _save_terrain(self):
        """Save terrain data to JSON file."""
        data = {"regions": self._terrain_regions}
        with open(self._terrain_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _apply_terrain_to_battle_map(self):
        """Apply terrain regions to the C++ battle map multiplier system."""
        self.bm.reset_terrain_multipliers()
        for region in self._terrain_regions:
            terrain_type = region.get("type", "Difficult Terrain")
            if terrain_type == "Difficult Terrain":
                mult = region.get("multiplier", 0.5)
                px = region.get("x", 0)
                py = region.get("y", 0)
                pw = region.get("width", 0)
                ph = region.get("height", 0)
                if pw > 0 and ph > 0:
                    self._apply_pixel_terrain(px, py, pw, ph, mult)

    def _apply_pixel_terrain(self, px, py, pw, ph, mult):
        """Convert pixel coordinates to grid and apply multiplier."""
        import bisect
        s = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return

        # Convert pixel coords (scaled) to original image coords
        ix, iy = px / s, py / s
        iw, ih = pw / s, ph / s

        # Find grid cell range using binary search
        c_start = max(0, bisect.bisect_right(raw_v, ix) - 1)
        r_start = max(0, bisect.bisect_right(raw_h, iy) - 1)
        c_end = min(self.bm.grid_cols - 1, bisect.bisect_right(raw_v, ix + iw) - 1)
        r_end = min(self.bm.grid_rows - 1, bisect.bisect_right(raw_h, iy + ih) - 1)

        width = max(1, c_end - c_start + 1)
        height = max(1, r_end - r_start + 1)

        self.bm.set_terrain_multiplier_rect(rpg.Cell(c_start, r_start), width, height, mult)

    # ─────────────────────────────────────────────────────────────────────
    #  Drawing
    # ─────────────────────────────────────────────────────────────────────
    def _draw_map(self):
        self.screen.blit(self.map_surf, self.map_rect)
        self.screen.blit(self.overlay, self.map_rect)

    def _draw_one_agent(self, pt, screen_x, screen_y, cpx, alpha=255, tint=None):
        """Draw a single agent (sprite or placeholder) at the given screen coords."""
        size_px = cpx * pt.size
        sprite  = self._get_sprite(pt.sprite_path, size_px)
        if sprite:
            if alpha < 255 or tint:
                surf = sprite.copy()
                if tint:
                    surf.fill(tint, special_flags=pygame.BLEND_RGBA_MULT)
                surf.set_alpha(alpha)
                self.screen.blit(surf, (screen_x, screen_y))
            else:
                self.screen.blit(sprite, (screen_x, screen_y))
        else:
            r = pygame.Rect(screen_x+2, screen_y+2, size_px-4, size_px-4)
            placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            fill_col    = tint if tint else COL_AGENT_FILL
            placeholder.fill((*fill_col[:3], alpha))
            self.screen.blit(placeholder, r)
            pygame.draw.rect(self.screen, COL_AGENT_BORDER, r, 2, border_radius=3)
        # Name label
        lbl = self.font_sm.render(pt.name, True, (255, 255, 255))
        self.screen.blit(lbl, (screen_x + 3, screen_y + 3))

    def _draw_reach_overlays(self, cpx: int, raw_h=None, raw_v=None):
        """Draw walk (blue) and fly (gold) reachable-cell overlays."""
        # Get map dimensions if not provided
        if raw_h is None:
            raw_h = self.bm.h_line_positions
        if raw_v is None:
            raw_v = self.bm.v_line_positions

        # Walk range: semi-transparent cornflower blue
        if self._reach_walk:
            walk_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            walk_surf.fill((60, 120, 220, 55))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (80, 150, 255, 120),
                             border_surf.get_rect(), 1)
            for cell in self._reach_walk:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(walk_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Fly range: semi-transparent gold — drawn on top so overlapping
        # cells show both colours (fly usually extends beyond walk).
        if self._reach_fly:
            fly_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fly_surf.fill((220, 180, 0, 45))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (255, 210, 0, 110),
                             border_surf.get_rect(), 1)
            for cell in self._reach_fly:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(fly_surf,    (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Jump range: semi-transparent cyan (when overlay is active)
        if self.jump_overlay_active and self.jump_reachable_cells:
            jump_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            jump_surf.fill((100, 200, 255, 70))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (150, 230, 255, 150),
                             border_surf.get_rect(), 2)
            for cell in self.jump_reachable_cells:
                # Skip cells outside map bounds
                if (cell.col < 0 or cell.row < 0 or
                    cell.col >= len(raw_v) or cell.row >= len(raw_h)):
                    continue
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(jump_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

    def _draw_temp_terrain_overlays(self, cpx: int):
        """Draw temporary terrain effect overlays."""
        if not self.bm.has_active_terrain_effects():
            return

        s = self.map_scale
        raw_h = self.bm.h_line_positions
        raw_v = self.bm.v_line_positions

        for effect in self.bm.active_terrain_effects:
            # Get color from metadata, or use a default based on difficulty
            if effect.id in self._effect_meta:
                color = self._effect_meta[effect.id].get("color", (100, 180, 220, 80))
            else:
                # Default colors by difficulty
                if effect.difficulty == rpg.TerrainDifficulty.Halved:
                    color = (80, 200, 80, 80)  # Green
                elif effect.difficulty == rpg.TerrainDifficulty.Quartered:
                    color = (200, 60, 60, 80)  # Red
                else:
                    color = (100, 180, 220, 80)  # Cyan

            # Create surfaces for fill and border
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Render each cell of the effect
            for cell_idx in effect.cell_indices:
                # Convert flat index back to (col, row)
                col = cell_idx % self.bm.grid_cols
                row = cell_idx // self.bm.grid_cols
                if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                    continue
                sx, sy = self._cell_to_screen(col, row)
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

            # Draw turns_remaining as a small label in the first cell
            if effect.cell_indices and effect.turns_remaining >= 0:
                first_idx = effect.cell_indices[0]
                col = first_idx % self.bm.grid_cols
                row = first_idx // self.bm.grid_cols
                if col >= 0 and row >= 0 and col < len(raw_v) and row < len(raw_h):
                    sx, sy = self._cell_to_screen(col, row)
                    # Draw a small number in the top-left corner
                    txt = self.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                    self.screen.blit(txt, (sx + 2, sy + 2))

    def _draw_agents(self):
        bm    = self.bm
        s     = self.map_scale
        cpx   = int(bm.cell_pixel_size * s)
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return

        agents = bm.placed_agents

        # ── Movement reach overlays (beneath all agents) ──────────────────
        self._draw_reach_overlays(cpx, raw_h, raw_v)

        # ── Attack range overlays (beneath all agents) ────────────────────
        self._draw_attack_overlays(cpx)

        # ── Temporary terrain effects overlays (beneath all agents) ────────
        self._draw_temp_terrain_overlays(cpx)

        # ── Draw all settled agents ───────────────────────────────────────
        for i, pt in enumerate(agents):
            if i == self.drag_idx:
                continue    # skip the one being dragged (draw as ghost below)
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            self._draw_one_agent(pt, sx, sy, cpx)

            # Selection highlight (yellow border)
            if i == self.selected_idx:
                size_px = cpx * pt.size
                pygame.draw.rect(self.screen, (255, 215, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # ── Spell AoE preview (above agents, below drag ghost) ───────────
        self._draw_spell_aoe_preview(cpx)

        # ── Draw drag ghost ───────────────────────────────────────────────
        if self.drag_idx >= 0 and self.drag_cell is not None:
            pt  = agents[self.drag_idx]
            sx, sy = self._cell_to_screen(self.drag_cell.col, self.drag_cell.row)
            tint = (100, 255, 100) if self.drag_valid else (255, 80, 80)
            self._draw_one_agent(pt, sx, sy, cpx, alpha=180, tint=tint)
            # Outline
            size_px = cpx * pt.size
            border_col = (80, 220, 80) if self.drag_valid else (220, 60, 60)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

    def _draw_combat_panel(self):
        """Draw the right panel while combat is active."""
        sw, sh = self.screen.get_size()
        px = self._panel_x()
        lx = px + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2
        HW = W // 2 - 2
        B  = self._BTN_H
        gap = 4
        section_gap = 8

        # Background + border
        pygame.draw.rect(self.screen, COL_PANEL_BG, pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        def txt(s, x, y, col=COL_TEXT, fnt=None):
            surf = (fnt or self.font_sm).render(s, True, col)
            self.screen.blit(surf, (x, y))

        y = 10

        # ── Title ──────────────────────────────────────────────────────────
        txt("⚔  Combat", lx, y, COL_INITIATIVE_CUR, self.font_lg)
        y += 28

        # ── Initiative list ────────────────────────────────────────────────
        txt("Initiative Order", lx, y, COL_LABEL)
        y += 16
        agents = self.bm.placed_agents
        for i, entry in enumerate(self.initiative_order[:8]):
            aidx   = entry.agent_idx
            is_cur = (i == self.turn_idx)
            col    = COL_INITIATIVE_CUR if is_cur else COL_TEXT
            name   = agents[aidx].name if aidx < len(agents) else "?"
            alive  = True
            if aidx < len(agents):
                s = self.bm.get_agent_stats(aidx)
                alive = s.hp_cur > 0
            if not alive:
                col = (90, 90, 90)
            prefix = "▶ " if is_cur else "  "
            row_s  = f"{prefix}{entry.total:2d}  {name}"
            txt(row_s, lx, y, col)
            y += 16
        if len(self.initiative_order) > 8:
            txt(f"  …+{len(self.initiative_order)-8} more", lx, y, COL_LABEL)
            y += 16

        y += section_gap

        # ── Separator ──────────────────────────────────────────────────────
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (px + 6, y), (px + PANEL_W - 6, y))
        y += section_gap

        # ── Current combatant info ─────────────────────────────────────────
        cur_idx = self._current_agent_idx()
        if 0 <= cur_idx < len(agents):
            pt    = agents[cur_idx]
            stats = self.bm.get_agent_stats(cur_idx)
            frac  = stats.hp_cur / max(stats.hp_max, 1)
            hp_col = (COL_HP_HIGH if frac > 0.66 else
                      COL_HP_MID  if frac > 0.33 else
                      COL_HP_LOW)
            txt(f"Turn: {pt.name}", lx, y, COL_TEXT, self.font_md)
            y += 20
            pygame.draw.rect(self.screen, (50, 50, 50),
                             pygame.Rect(lx, y, W, 12), border_radius=3)
            pygame.draw.rect(self.screen, hp_col,
                             pygame.Rect(lx, y, int(W * frac), 12), border_radius=3)
            txt(f"HP {stats.hp_cur}/{stats.hp_max}", lx + W//2 - 22, y - 1)
            y += 12

        y += section_gap

        # ── Action section ─────────────────────────────────────────────────
        act_lbl = "Action" + (" ✓" if self.action_used else "")
        txt(act_lbl, lx, y, COL_LABEL)
        y += 16

        # Check weapon/spell capability for current agent.
        _cur_has_weapons = False
        _cur_can_spell   = False
        _cur_has_spells  = False
        if 0 <= cur_idx < len(agents):
            _cur_has_weapons = len(self.bm.get_agent_weapons(cur_idx)) > 0
            _cur_can_spell   = self.bm.get_agent_stats(cur_idx).can_cast_spell
            _cur_has_spells  = len(self.bm.get_agent_spells(cur_idx)) > 0

        if self.action_used:
            txt("[Action used]", lx, y, (100, 100, 120))
            y += B
        else:
            # Attack and Pass buttons
            self.btn_cbt_atk_action.rect.x  = lx
            self.btn_cbt_atk_action.rect.y  = y
            self.btn_cbt_atk_action.rect.w  = HW
            self.btn_cbt_pass_action.rect.x = lx + HW + gap
            self.btn_cbt_pass_action.rect.y = y
            self.btn_cbt_pass_action.rect.w = HW
            if _cur_has_weapons:
                self.btn_cbt_atk_action.draw(self.screen)
            self.btn_cbt_pass_action.draw(self.screen)
            y += B + gap

            # Dash, Dodge, Disengage buttons
            TW3 = (W - 8) // 3
            self.btn_cbt_dash.rect.x       = lx
            self.btn_cbt_dash.rect.y       = y
            self.btn_cbt_dash.rect.w       = TW3
            self.btn_cbt_dodge.rect.x      = lx + TW3 + gap
            self.btn_cbt_dodge.rect.y      = y
            self.btn_cbt_dodge.rect.w      = TW3
            self.btn_cbt_disengage.rect.x  = lx + 2 * (TW3 + gap)
            self.btn_cbt_disengage.rect.y  = y
            self.btn_cbt_disengage.rect.w  = TW3
            self.btn_cbt_dash.draw(self.screen)
            self.btn_cbt_dodge.draw(self.screen)
            self.btn_cbt_disengage.draw(self.screen)
            y += B + gap

            # Long Jump button
            self.btn_cbt_long_jump.rect.x = lx
            self.btn_cbt_long_jump.rect.y = y
            self.btn_cbt_long_jump.rect.w = W
            self.btn_cbt_long_jump.draw(self.screen)
            y += B + gap

            # Cast Spell button (if available)
            if _cur_can_spell and _cur_has_spells:
                self.btn_cbt_spell_action.rect.x = lx
                self.btn_cbt_spell_action.rect.y = y
                self.btn_cbt_spell_action.rect.w = W
                self.btn_cbt_spell_action.draw(self.screen)
                y += B + gap

        y += section_gap

        # ── Bonus Action section ───────────────────────────────────────────
        bon_lbl = "Bonus Action" + (" ✓" if self.bonus_used else "")
        txt(bon_lbl, lx, y, COL_LABEL)
        y += 16

        if self.bonus_used:
            txt("[Bonus used]", lx, y, (100, 100, 120))
            y += B
        else:
            # Layout depends on whether spells are available
            if _cur_can_spell and _cur_has_spells:
                TW3_bonus = (W - 8) // 3
                self.btn_cbt_atk_bonus.rect.x   = lx
                self.btn_cbt_atk_bonus.rect.y   = y
                self.btn_cbt_atk_bonus.rect.w   = TW3_bonus
                self.btn_cbt_spell_bonus.rect.x = lx + TW3_bonus + gap
                self.btn_cbt_spell_bonus.rect.y = y
                self.btn_cbt_spell_bonus.rect.w = TW3_bonus
                self.btn_cbt_pass_bonus.rect.x  = lx + 2 * (TW3_bonus + gap)
                self.btn_cbt_pass_bonus.rect.y  = y
                self.btn_cbt_pass_bonus.rect.w  = TW3_bonus
                if _cur_has_weapons:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_spell_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            else:
                self.btn_cbt_atk_bonus.rect.x  = lx
                self.btn_cbt_atk_bonus.rect.y  = y
                self.btn_cbt_atk_bonus.rect.w  = HW
                self.btn_cbt_pass_bonus.rect.x = lx + HW + gap
                self.btn_cbt_pass_bonus.rect.y = y
                self.btn_cbt_pass_bonus.rect.w = HW
                if _cur_has_weapons:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            y += B

        y += section_gap

        # ── Movement type toggles ──────────────────────────────────────────
        txt("Movement", lx, y, COL_LABEL)
        y += 16

        mv_stats = self.bm.get_agent_stats(cur_idx) if 0 <= cur_idx < len(self.bm.placed_agents) else None
        mv_entries = [
            (rpg.MovementType.Walk,   "Walk",   self.move_remaining_walk,
             mv_stats.speed_walk   if mv_stats else 0),
            (rpg.MovementType.Fly,    "Fly",    self.move_remaining_fly,
             mv_stats.speed_fly    if mv_stats else 0),
            (rpg.MovementType.Swim,   "Swim",   self.move_remaining_swim,
             mv_stats.speed_swim   if mv_stats else 0),
            (rpg.MovementType.Burrow, "Burrow", self.move_remaining_burrow,
             mv_stats.speed_burrow if mv_stats else 0),
        ]
        available_mv = [(mt, lbl, rem, spd) for mt, lbl, rem, spd in mv_entries if spd > 0]
        self._move_type_btns = {}
        HW = W // 2 - 2
        for i, (mt, lbl, rem, spd) in enumerate(available_mv):
            bx = lx + (i % 2) * (HW + gap)
            by = y + (i // 2) * (B + gap)
            r  = pygame.Rect(bx, by, HW, B)
            self._move_type_btns[mt] = r
            if rem == 0:
                bg = (40, 40, 55)
                fg = (80, 80, 95)
            elif mt == self.move_type:
                bg = COL_BTN_ENDTURN
                fg = (230, 230, 230)
            else:
                bg = COL_BTN_PASS
                fg = (190, 190, 210)
            pygame.draw.rect(self.screen, bg, r, border_radius=4)
            surf = self.font_sm.render(f"{lbl}  {rem}ft", True, fg)
            self.screen.blit(surf, (bx + 4, by + (B - surf.get_height()) // 2))
        rows_used = max(1, (len(available_mv) + 1) // 2)
        y += rows_used * (B + gap)

        # Pending action hints
        if self.pending_attack_slot:
            rem = self.attacks_remaining
            _atk_hint = "→ Click a target on the map" + (f" ({rem} left)" if rem > 1 else "")
            txt(_atk_hint, lx, y, COL_INITIATIVE_CUR)
            y += 14
        elif self.pending_spell_slot:
            hint = "Click a map location" if self.pending_spell_is_aoe else "Click a target"
            txt(f"→ {hint} to cast spell", lx, y, (190, 150, 255))
            y += 14

        y += section_gap

        # ── Place Terrain / End Turn ───────────────────────────────────────
        HW = (W - 4) // 2
        self.btn_cbt_place_terrain.rect.x = lx
        self.btn_cbt_place_terrain.rect.y = y
        self.btn_cbt_place_terrain.rect.w = HW
        self.btn_cbt_place_terrain.draw(self.screen)

        self.btn_cbt_end_turn.rect.x  = lx + HW + 4
        self.btn_cbt_end_turn.rect.y  = y
        self.btn_cbt_end_turn.rect.w  = HW
        self.btn_cbt_end_turn.draw(self.screen)
        y += B + gap

        self.btn_cbt_end_combat.rect.x = lx
        self.btn_cbt_end_combat.rect.y = y
        self.btn_cbt_end_combat.rect.w = W
        self.btn_cbt_end_combat.draw(self.screen)
        y += B + section_gap

        # ── Combat log ─────────────────────────────────────────────────────
        txt("Combat Log:", lx, y, COL_LABEL)
        y += 16

        max_log_w = W - 2

        def _wrap_draw(s, x, start_y, max_w, fnt, line_h=15):
            """Draw s word-wrapped within max_w pixels; return the new y after last line."""
            y_pos = start_y
            remaining = s
            while remaining:
                if y_pos + line_h > sh:
                    break
                if fnt.size(remaining)[0] <= max_w:
                    txt(remaining, x, y_pos)
                    y_pos += line_h
                    break
                lo, hi = 0, len(remaining)
                while lo < hi - 1:
                    mid = (lo + hi) // 2
                    if fnt.size(remaining[:mid])[0] <= max_w:
                        lo = mid
                    else:
                        hi = mid
                cut = lo
                space = remaining.rfind(" ", 0, lo)
                if space > 0:
                    cut = space
                txt(remaining[:cut], x, y_pos)
                y_pos += line_h
                remaining = remaining[cut:].lstrip(" ")
            return y_pos + 2

        for msg in self.combat_log[:5]:
            y = _wrap_draw(msg, lx, y, max_log_w, self.font_sm)


    def _draw_panel(self):
        if self.combat_active:
            self._draw_combat_panel()
            return

        sw, sh = self.screen.get_size()
        px  = self._panel_x()
        lx  = px + self._PANEL_PAD          # left edge for text
        loff = self._LABEL_H + self._LABEL_GAP   # how far above a widget its label sits

        # Panel background + left border
        pygame.draw.rect(self.screen, COL_PANEL_BG,
                         pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        # ── Title ─────────────────────────────────────────────────────────
        _, _, title_y, *_ = self._panel_layout()
        title = self.font_lg.render("⚔  Agent Config", True, COL_TEXT)
        self.screen.blit(title, (lx, title_y))

        # ── Field labels (sit loff px above their widget) ──────────────
        def label(text, x, widget_y):
            t = self.font_sm.render(text, True, COL_LABEL)
            self.screen.blit(t, (x, widget_y - loff))

        HW = (PANEL_W - self._PANEL_PAD * 2) // 2 - 2
        label("Mob",         lx,        self.btn_select_mob.rect.y)
        label("Name",        lx,        self.inp_name.rect.y)
        label("Sprite Path", lx,        self.inp_sprite.rect.y)
        label("Size (N×N)",  lx,        self.step_size.rect.y)
        label("Col",         lx,        self.step_col.rect.y)
        label("Row",         lx+HW+4,   self.step_row.rect.y)

        # ── Widgets ───────────────────────────────────────────────────────
        for w in [self.btn_select_mob, self.inp_name, self.inp_sprite, self.btn_browse,
                  self.step_size, self.step_col, self.step_row,
                  self.btn_add, self.btn_apply, self.btn_clear,
                  self.btn_save, self.btn_load]:
            w.draw(self.screen)

        # Current save-file hint (updates when user picks a different path)
        hint_txt = os.path.basename(self._save_path) if self._save_path else ""
        hint = self.font_sm.render(hint_txt, True, (100, 100, 130))
        self.screen.blit(hint, (lx, self.btn_begin_combat.rect.bottom + 4))

        # ── Begin Combat button (only when agents are placed) ─────────────
        if self.bm.placed_agents:
            self.btn_begin_combat.draw(self.screen)

        # ── Edit Terrain button ────────────────────────────────────────────
        self.btn_edit_terrain.draw(self.screen)

        # ── Pending config list ───────────────────────────────────────────
        def text(txt, x, y, color=COL_LABEL):
            """Plain text blit with no offset (unlike label() which is for widgets)."""
            t = self.font_sm.render(txt, True, color)
            self.screen.blit(t, (x, y))

        list_y = self.btn_begin_combat.rect.bottom + 16
        text(f"Pending  ({len(self.pending_configs)})", lx, list_y)
        list_y += 18
        for i, cfg in enumerate(self.pending_configs):
            txt = f"{cfg.name}  {cfg.size}×{cfg.size}  @({cfg.start_col},{cfg.start_row})"
            text(txt, lx, list_y + i * 18, COL_TEXT)
            # ✕ remove button
            rx = px + PANEL_W - 22
            rb = Button(pygame.Rect(rx, list_y + i*18 - 1, 16, 16), "✕",
                        COL_BTN_DANGER, (180, 70, 70), self.font_sm)
            rb.draw(self.screen)

        # ── Grid / map stats (bottom of panel) ───────────────────────────
        info_y = sh - 72
        text(f"Grid: {self.bm.grid_cols}×{self.bm.grid_rows}  "
             f"cell={self.bm.cell_pixel_size}px  scale={self.map_scale:.2f}",
             lx, info_y)
        text(f"Walls: {len(self.bm.walls)}   Blocked: {len(self.bm.disallowed_cells)}",
             lx, info_y + 18)
        text(f"Agents placed: {len(self.bm.placed_agents)}", lx, info_y + 36)

    # ─────────────────────────────────────────────────────────────────────
    #  Event handling
    # ─────────────────────────────────────────────────────────────────────
    def _panel_rect(self):
        return pygame.Rect(self._panel_x(), 0, PANEL_W, self.screen.get_height())

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # ── Terrain editor gets first pick when open ──────────────────
            if self.terrain_editor.active:
                self.terrain_editor.handle(event)
                # Handle close/save for terrain editor
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._terrain_regions = self.terrain_editor.terrain_regions
                    self._save_terrain()
                    self._apply_terrain_to_battle_map()
                    self.terrain_editor.close()
                    # Recalculate reach overlay if an agent is selected
                    if self.selected_idx >= 0:
                        self._update_reach()
                continue

            # ── Terrain placement dialog gets priority when open ────────────
            if self.terrain_placement_dialog.active:
                self.terrain_placement_dialog.handle(event)
                continue

            # ── Modals get first pick when open ───────────────────────────
            if self.file_browser.active:
                self.file_browser.handle(event, self.screen)
                continue
            if self.stats_dialog.active:
                self.stats_dialog.handle(event, self.screen)
                continue
            if self.weapon_dialog.active:
                self.weapon_dialog.handle(event, self.screen)
                continue
            if self.spell_dialog.active:
                self.spell_dialog.handle(event, self.screen)
                continue
            # Context menu sits above normal map events but below modals.
            if self.context_menu.visible:
                if self.context_menu.handle(event):
                    continue

            # ── Keyboard shortcuts ────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                # Delete / Backspace removes the selected placed agent,
                # but ONLY when no text-input field has keyboard focus.
                typing = self.inp_name.active or self.inp_sprite.active
                if event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) \
                        and not typing and not self.combat_active:
                    if self.selected_idx >= 0:
                        idx = self.selected_idx
                        self.bm.remove_agent(idx)
                        # Weapon data lives in C++ and is removed with the agent.
                        self.selected_idx        = -1
                        self.drag_idx            = -1
                        self._reach_walk         = []
                        self._reach_fly          = []
                        self._reach_set          = set()
                        self._attack_cells_melee = []
                        self._attack_cells_rnorm = []
                        self._attack_cells_rlong = []

            if event.type == pygame.VIDEORESIZE:
                self._reposition_panel()

            # ── Map area: drag-and-drop ───────────────────────────────────
            on_map = not self._panel_rect().collidepoint(
                *getattr(event, 'pos', (-1, -1)))

            # Right-click on a placed agent → context menu (disabled during combat)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.combat_active:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0:
                        pt = self.bm.placed_agents[hit]
                        # Capture hit by value for the lambdas.
                        def _open_stats(h=hit):
                            pt2   = self.bm.placed_agents[h]
                            stats = self.bm.get_agent_stats(h)
                            self.stats_dialog.open(
                                self.screen, h, pt2.name, stats,
                                self._on_stats_ok)
                        def _open_weapons(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            weapon_dicts = [_weapon_to_dict(w)
                                            for w in self.bm.get_agent_weapons(h)]
                            self.weapon_dialog.open(
                                self.screen, h, pt2.name,
                                weapon_dicts,
                                self._on_weapon_done)
                        def _open_spells(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            spell_dicts = [_spell_to_dict(s)
                                           for s in self.bm.get_agent_spells(h)]
                            self.spell_dialog.open(
                                self.screen, h, pt2.name,
                                spell_dicts,
                                self._on_spell_done)
                        self.context_menu.show(
                            event.pos,
                            [("Edit Stats",   _open_stats),
                             ("Edit Weapons", _open_weapons),
                             ("Edit Spells",  _open_spells)],
                            self.screen.get_size()
                        )

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if self.combat_active:
                        # Pending attack: resolve against the clicked agent.
                        if self.pending_attack_slot and hit >= 0:
                            self._resolve_combat_attack(hit)
                        elif self.pending_spell_slot:
                            if self.pending_spell_is_aoe:
                                self._resolve_spell_cast_aoe(cell)
                            elif hit >= 0:
                                self._resolve_spell_cast(hit)
                        else:
                            # Only allow dragging the current combatant.
                            cur = self._current_agent_idx()
                            if hit == cur and hit >= 0:
                                pt = self.bm.placed_agents[hit]
                                self.drag_idx    = hit
                                self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_offset = (cell.col - pt.origin.col,
                                                    cell.row - pt.origin.row)
                                self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_valid  = True
                                # Keep selected_idx on the current combatant.
                    else:
                        # Normal mode: drag any agent or deselect.
                        # But disable dragging if jump overlay is active (use jump instead)
                        if hit >= 0 and not self.jump_overlay_active:
                            pt = self.bm.placed_agents[hit]
                            self.drag_idx    = hit
                            self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_offset = (cell.col - pt.origin.col,
                                                cell.row - pt.origin.row)
                            self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_valid  = True
                            self.selected_idx = hit
                            self._update_reach()
                            self._update_attack_overlay()
                        else:
                            self.selected_idx        = -1
                            self._reach_walk         = []
                            self._reach_fly          = []
                            self._reach_set          = set()
                            self._attack_cells_melee = []
                            self._attack_cells_rnorm = []
                            self._attack_cells_rlong = []

            if event.type == pygame.MOUSEMOTION and self.pending_spell_is_aoe:
                if on_map:
                    self.spell_hover_cell = self._screen_to_cell(*event.pos)
                else:
                    self.spell_hover_cell = None

            if event.type == pygame.MOUSEMOTION and self.drag_idx >= 0:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    pt   = self.bm.placed_agents[self.drag_idx]
                    tcol = cell.col - self.drag_offset[0]
                    trow = cell.row - self.drag_offset[1]
                    self.drag_cell  = rpg.Cell(tcol, trow)
                    self.drag_valid = self._can_place(
                        self.drag_cell, pt.size, exclude_idx=self.drag_idx)
                    # Restrict to the computed reach (walk ∪ fly).
                    # Outside combat an empty reach means no speed → allow
                    # free repositioning.  Inside combat an empty reach means
                    # movement is exhausted → block the drag entirely.
                    if self.drag_valid:
                        if self._reach_set:
                            self.drag_valid = (
                                self.drag_cell.col, self.drag_cell.row
                            ) in self._reach_set
                        elif self.combat_active:
                            self.drag_valid = False   # no movement remaining

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.drag_idx >= 0:
                    if self.drag_valid and self.drag_cell is not None:
                        # Calculate Manhattan distance moved (for running jump qualification)
                        ag_old = self.bm.placed_agents[self.drag_idx]
                        dist_moved = abs(self.drag_cell.col - ag_old.origin.col) + abs(self.drag_cell.row - ag_old.origin.row)
                        dist_moved *= 5  # Each cell = 5 feet

                        # Compute Chebyshev distance (D&D 5e diagonal = 5 ft).
                        if self.bm.move_agent(self.drag_idx, self.drag_cell, self.move_type):
                            # Read back the shared-pool budgets from C++.
                            ag = self.bm.placed_agents[self.drag_idx]
                            self.move_remaining_walk   = ag.walk_remaining
                            self.move_remaining_fly    = ag.fly_remaining
                            self.move_remaining_swim   = ag.swim_remaining
                            self.move_remaining_burrow = ag.burrow_remaining
                            self.last_movement_dist = dist_moved  # Track most recent movement for running jump
                        # else: move failed, leave last_movement_dist unchanged
                        self.selected_idx = self.drag_idx
                        self._update_reach()
                        self._update_attack_overlay()
                    # else: agent stays at original position (C++ not updated)
                    self.drag_idx = -1
                    self.drag_cell = None

            # ── Handle jump clicks ────────────────────────────────────────────
            if self.jump_overlay_active and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if on_map:
                    cell = self._screen_to_cell(*event.pos)
                    # Check if clicked cell is in jump range (compare by coordinates)
                    is_jump_cell = any(c.col == cell.col and c.row == cell.row for c in self.jump_reachable_cells)
                    if is_jump_cell:
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._execute_jump(idx, cell)

            # ── Mob selection dialog ──────────────────────────────────────
            if not self.combat_active:
                if self.mob_dialog.handle(event):
                    pass  # Event was consumed by dialog

                # ── Panel widgets ─────────────────────────────────────────────
                # Select Mob button
                if self.btn_select_mob.clicked(event):
                    self.mob_dialog.show(lambda mob: self._on_mob_selected(mob))

                # Text inputs / steppers (config panel only)
                for w in [self.inp_name, self.inp_sprite]:
                    w.handle(event)
                for w in [self.step_size, self.step_col, self.step_row]:
                    w.handle(event)

                # Browse button
                if self.btn_browse.clicked(event):
                    start = (os.path.dirname(self.inp_sprite.text)
                             if self.inp_sprite.text else self._map_dir)
                    self.file_browser.open(
                        start,
                        lambda p: setattr(self.inp_sprite, "text", p)
                    )

                # Add / Apply & Draw / Clear All
                if self.btn_add.clicked(event):
                    cfg = rpg.AgentConfig()
                    cfg.name        = self.inp_name.text or "Agent"
                    cfg.sprite_path = self.inp_sprite.text
                    cfg.size        = self.step_size.value
                    cfg.start_col   = self.step_col.value
                    cfg.start_row   = self.step_row.value
                    self.pending_configs.append(cfg)
                    self.pending_mob_stats.append(self.selected_mob_stats)
                    self.inp_name.text   = ""
                    self.inp_sprite.text = ""

                if self.btn_apply.clicked(event):
                    self.bm.clear_agents()
                    self.selected_idx        = -1
                    self.drag_idx            = -1
                    self._attack_cells_melee = []
                    self._attack_cells_rnorm = []
                    self._attack_cells_rlong = []
                    for cfg in self.pending_configs:
                        self.bm.add_agent_config(cfg)
                    self.bm.apply_agent_configs()

                    # Apply mob stats to placed agents
                    for idx, mob_stats in enumerate(self.pending_mob_stats):
                        if idx < len(self.bm.placed_agents) and mob_stats:
                            d_d_stats = self._mob_stats_to_d_d_stats(mob_stats)
                            self.bm.set_agent_stats(idx, d_d_stats)

                    self.sprites.clear()

                if self.btn_clear.clicked(event):
                    self.pending_configs.clear()
                    self.pending_mob_stats.clear()
                    self.bm.clear_agents()
                    self.selected_idx        = -1
                    self.drag_idx            = -1
                    self._attack_cells_melee = []
                    self._attack_cells_rnorm = []
                    self._attack_cells_rlong = []

                # Save — open browser in save mode
                if self.btn_save.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_save_path_chosen,
                        save_mode=True,
                        extensions=JSON_EXTS,
                        default_filename=os.path.basename(self._save_path)
                    )

                # Load — open browser in load mode
                if self.btn_load.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_load_path_chosen,
                        save_mode=False,
                        extensions=JSON_EXTS
                    )

                # Remove pending agent by clicking ✕
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    list_y = self.btn_clear.rect.bottom + 20 + 18
                    px_rm = self._panel_x()
                    for i in range(len(self.pending_configs)):
                        rx = px_rm + PANEL_W - 22
                        rb = pygame.Rect(rx, list_y + i*18 - 1, 16, 16)
                        if rb.collidepoint(event.pos):
                            self.pending_configs.pop(i)
                            break

                # Begin Combat
                if self.btn_begin_combat.clicked(event):
                    self._start_combat()

                # Edit Terrain
                if self.btn_edit_terrain.clicked(event):
                    self.terrain_editor.open(self.map_surf, self._terrain_regions, self.bm)

            else:
                # ── Combat panel buttons ───────────────────────────────────
                _ev_idx = self._current_agent_idx()
                _has_wpn = (0 <= _ev_idx < len(self.bm.placed_agents) and
                            len(self.bm.get_agent_weapons(_ev_idx)) > 0)
                if not self.action_used:
                    if _has_wpn and self.btn_cbt_atk_action.clicked(event):
                        self._start_attack("action")
                    if self.btn_cbt_pass_action.clicked(event):
                        self.action_used = True
                    if self.btn_cbt_dash.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            agent = self.bm.placed_agents[idx]
                            self.bm.apply_dash(idx)
                            self.move_remaining_walk   = agent.walk_remaining
                            self.move_remaining_fly    = agent.fly_remaining
                            self.move_remaining_swim   = agent.swim_remaining
                            self.move_remaining_burrow = agent.burrow_remaining
                            self._combat_log_add(f"{agent.name}: Dashing (+{self.bm.get_agent_stats(idx).speed_walk}ft)")
                            self._update_reach()
                        self.action_used = True
                    if self.btn_cbt_dodge.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].dodge()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Dodging")
                        self.action_used = True
                    if self.btn_cbt_disengage.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].disengage()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging")
                        self.action_used = True
                    if self.btn_cbt_long_jump.clicked(event):
                        if not self.pending_spell_slot:  # Don't allow jump while casting spell
                            self._toggle_jump_overlay()
                    if self.btn_cbt_spell_action.clicked(event):
                        self._start_cast_spell("action")
                if not self.bonus_used:
                    if _has_wpn and self.btn_cbt_atk_bonus.clicked(event):
                        self._start_attack("bonus")
                    if self.btn_cbt_spell_bonus.clicked(event):
                        self._start_cast_spell("bonus")
                    if self.btn_cbt_pass_bonus.clicked(event):
                        self.bonus_used = True
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for mv_mt, mv_rect in self._move_type_btns.items():
                        if mv_rect.collidepoint(event.pos):
                            self.move_type = mv_mt
                            self._update_reach()
                            break
                if self.btn_cbt_place_terrain.clicked(event):
                    self.terrain_placement_dialog.open(self.map_surf, self.bm, self)
                if self.btn_cbt_end_turn.clicked(event):
                    self._advance_turn()
                if self.btn_cbt_end_combat.clicked(event):
                    self._end_combat()

        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────
    def run(self):
        running = True
        while running:
            running = self._handle_events()
            self.screen.fill(COL_BG)
            self._draw_map()
            self._draw_agents()
            self._draw_panel()
            self.terrain_editor.draw(self.screen)          # modal — always on top
            self.terrain_placement_dialog.draw(self.screen)  # modal — always on top
            self.file_browser.draw(self.screen)     # modal — always on top
            self.stats_dialog.draw(self.screen)    # modal — always on top
            self.weapon_dialog.draw(self.screen)   # modal — always on top
            self.spell_dialog.draw(self.screen)    # modal — always on top
            self.mob_dialog.draw(self.screen)      # modal — always on top
            self.context_menu.draw(self.screen)    # popup — topmost
            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python main.py <map_image.png>")
    App(sys.argv[1]).run()
