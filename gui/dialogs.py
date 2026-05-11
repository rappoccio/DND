# ─────────────────────────────────────────────────────────────────────────────
#  dialogs.py  –  Self-contained modal dialogs
# ─────────────────────────────────────────────────────────────────────────────

import os
import pygame
import rpg_battle_map as rpg
from constants import *
from widgets import Button, TextInput, IntStepper
from helpers import _dnd_mod, _mod_str

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

    def __init__(self, font_sm, font_md, font_lg, spells=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.font_lg = font_lg
        self.spells = spells or []
        self.active              = False
        self._agent_idx          = -1
        self._agent_name         = ""
        self._class_name         = "None"
        self._char_level         = 1
        self._cb                 = None
        self.steppers: dict      = {}   # populated in open()
        self.prof_flags: dict    = {}   # save_prof_<ability> -> bool
        self._prof_rects: dict   = {}   # same keys -> pygame.Rect
        self._class_rects: dict  = {}   # class cycle button rects
        self._char_level_stepper = None  # IntStepper for character level
        self._is_npc             = False
        self._npc_spell_groups   = {}    # {N: [spell_names]}
        self._npc_add_group_rect = None
        self._spell_selection_dialog = None

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, screen, agent_idx: int, agent_name: str, stats, class_name: str, char_level: int, callback, is_npc=False, npc_spell_groups=None):
        self.active             = True
        self._agent_idx         = agent_idx
        self._agent_name        = agent_name
        self._class_name        = class_name
        self._char_level        = char_level
        self._cb                = callback
        self._is_npc            = is_npc
        self._npc_spell_groups  = dict(npc_spell_groups) if npc_spell_groups else {}
        self._spell_selection_dialog = SpellSelectionDialog(self.spells, self.font_sm, self.font_md) if self.spells else None
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
                    return True
                if available and right_rect and right_rect.collidepoint(event.pos):
                    idx = available.index(self._class_name) if self._class_name in available else 0
                    self._class_name = available[(idx + 1) % len(available)]
                    return True

            # Proficiency checkboxes
            for flag_key, rect in self._prof_rects.items():
                if rect.collidepoint(event.pos):
                    self.prof_flags[flag_key] = not self.prof_flags[flag_key]
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
            self._cb(self._agent_idx, self.steppers, self.prof_flags, self._class_name, self._char_level, npc_data)
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
        else:
            self._class_rects = {}

        # ── NPC Spells Section ────────────────────────────────────────────
        npc_checkbox_y = class_y + 24 if self._char_level_stepper else dlg.y + self.HDR_H + self.PAD + 300
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




class SpellSelectionDialog:
    """Modal dialog for selecting a spell from spells.json."""
    ITEM_H = 24
    PAD = 12
    SEARCH_H = 32

    def __init__(self, spells: list, font_sm=None, font_md=None):
        self.all_spells = spells  # All available spells (dicts with "name")
        self.filtered_spells = spells  # Filtered by search
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.rect = None
        self.scroll_y = 0
        self._hover_idx = -1
        self.selected_callback = None
        self.search_text = ""
        self._frames_since_show = 0  # Prevent immediate dismissal on show click

    def show(self, callback):
        self.visible = True
        self.selected_callback = callback
        self.scroll_y = 0
        self._hover_idx = -1
        self.search_text = ""
        self._frames_since_show = 0  # Reset counter to prevent immediate dismissal
        self.filtered_spells = self.all_spells[:]
        # Center dialog on screen
        screen_w, screen_h = pygame.display.get_surface().get_size()
        dlg_w = 400
        dlg_h = 500
        self.rect = pygame.Rect((screen_w - dlg_w) // 2, (screen_h - dlg_h) // 2, dlg_w, dlg_h)

    def dismiss(self):
        self.visible = False

    def _update_filtered_spells(self):
        """Filter spells based on search text."""
        search_lower = self.search_text.lower()
        self.filtered_spells = [s for s in self.all_spells if search_lower in s.get("name", "").lower()]
        self.scroll_y = 0
        self._hover_idx = -1

    def handle(self, event) -> bool:
        if not self.visible or not self.rect:
            return False

        # Skip first click after show to prevent dismissal on the same click that showed the dialog
        if event.type == pygame.MOUSEBUTTONDOWN and self._frames_since_show == 0:
            self._frames_since_show += 1
            return True

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
                # Check if click is in search box area
                search_y = self.rect.y + 35
                search_box_rect = pygame.Rect(self.rect.x + self.PAD, search_y,
                                             self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
                if search_box_rect.collidepoint(*event.pos):
                    return True

                list_y = search_y + self.SEARCH_H
                list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
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
            search_y = self.rect.y + 35
            list_y = search_y + self.SEARCH_H
            list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
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
            max_scroll = max(0, len(self.filtered_spells) * self.ITEM_H - (self.rect.h - self.SEARCH_H - 20))
            self.scroll_y = min(self.scroll_y, max_scroll)
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

        # Search box
        search_y = self.rect.y + 35
        search_box = pygame.Rect(self.rect.x + self.PAD, search_y, self.rect.w - self.PAD * 2, self.SEARCH_H - 8)
        pygame.draw.rect(surf, (30, 30, 40), search_box)
        pygame.draw.rect(surf, (100, 100, 120), search_box, 1)
        search_label = self.font_sm.render(f"Search: {self.search_text}_" if self.visible else f"Search: {self.search_text}", True, (200, 200, 200))
        surf.blit(search_label, (search_box.x + 4, search_box.y + 4))

        # Spell list
        list_y = search_y + self.SEARCH_H
        list_h = self.rect.h - (list_y - self.rect.y) - self.PAD
        pygame.draw.rect(surf, (30, 30, 40), pygame.Rect(self.rect.x + self.PAD, list_y, self.rect.w - self.PAD * 2, list_h))

        for i, spell in enumerate(self.filtered_spells):
            item_y = list_y + i * self.ITEM_H - self.scroll_y
            if list_y <= item_y < list_y + list_h:
                item_rect = pygame.Rect(self.rect.x + self.PAD, item_y, self.rect.w - self.PAD * 2, self.ITEM_H)
                if i == self._hover_idx:
                    pygame.draw.rect(surf, (70, 70, 90), item_rect)
                spell_name = spell.get("name", "Unknown")
                text = self.font_sm.render(spell_name, True, (200, 200, 220))
                surf.blit(text, (item_rect.x + 4, item_rect.y + 2))
