# ─────────────────────────────────────────────────────────────────────────────
#  spell_dialog.py  –  Spell editing dialog
# ─────────────────────────────────────────────────────────────────────────────

import pygame
import copy
import rpg_battle_map as rpg
from constants import *
from widgets import Button
from helpers import _ABILITY_TO_INT, _INT_TO_ABILITY, _DEFAULT_SPELL

class SpellDialog:
    """Modal dialog for editing an agent's spell list."""

    DLG_W  = 580
    DLG_H  = 750
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
        # Scrolling state for the (tabs + form) region between the header and
        # the fixed bottom buttons. content_h/view_h are recomputed each draw.
        self._scroll_y = 0
        self._content_h = 0
        self._view_h = 0
        self._view_rect: pygame.Rect | None = None

    def open(self, screen, agent_idx: int, agent_name: str,
             spells: list[dict], callback, add_spell_callback=None):
        import copy
        self.active      = True
        self._agent_idx  = agent_idx
        self._agent_name = agent_name
        self._spells     = copy.deepcopy(spells)
        self._cb         = callback
        self._add_spell_cb = add_spell_callback
        self._active_field = None
        self._rects      = {}
        sw, sh = screen.get_size()
        x = (sw - self.DLG_W) // 2
        y = (sh - self.DLG_H) // 2
        self._rect = pygame.Rect(x, y, self.DLG_W, self.DLG_H)
        self._sel = 0 if self._spells else -1
        self._scroll_y = 0
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
        # Handled by callback from spell selection dialog
        pass

    def _on_spell_selected(self, spell_dict: dict):
        """Called when user selects a spell from the selection dialog."""
        import copy
        self._save_form()
        # Add a copy of the selected spell dict
        self._spells.append(copy.deepcopy(spell_dict))
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

    TAB_W   = 108   # fixed width of a single spell tab
    TAB_GAP = 4     # gap between tabs (both axes)
    ADD_W   = 56    # width of the trailing "+ Add" cell

    def _layout_tabs(self, base_y=None):
        """Compute wrapping multi-row layout for the spell tabs + [+ Add].

        Returns (tab_rects, add_rect, content_y) where content_y is the first
        y below the tab block (where the editing form / divider should start).
        The tabs flow left-to-right and wrap onto new rows so they never run
        past the right edge of the dialog. The [+ Add] button is the cell that
        immediately follows the last tab in this same flow.

        ``base_y`` is the y where the first tab row starts; callers pass a
        scroll-adjusted value so the tabs scroll with the rest of the form.
        Defaults to the unscrolled position just below the header.
        """
        r   = self._rect
        PAD = self.PAD
        W   = self.DLG_W
        gap = self.TAB_GAP
        tw  = self.TAB_W
        start_x = r.x + PAD
        start_y = base_y if base_y is not None else (r.y + self.HDR_H + PAD - self._scroll_y)
        avail_w = W - PAD * 2
        cols = max(1, (avail_w + gap) // (tw + gap))

        n = len(self._spells)
        tab_rects = []
        for i in range(n):
            col = i % cols
            row = i // cols
            tab_rects.append(pygame.Rect(
                start_x + col * (tw + gap),
                start_y + row * (self.TAB_H + gap),
                tw, self.TAB_H))

        # [+ Add] occupies the next cell in the flow.
        col = n % cols
        row = n // cols
        add_r = pygame.Rect(
            start_x + col * (tw + gap),
            start_y + row * (self.TAB_H + gap),
            self.ADD_W, self.TAB_H)

        rows = (n + cols) // cols  # ceil((n + 1) / cols)
        content_y = start_y + rows * (self.TAB_H + gap)
        return tab_rects, add_r, content_y

    def _update_rects(self, screen):
        """Recalculate button and field rects based on current dialog position."""
        if not self._rect:
            return
        # Keep tab + add rects in sync for collision detection between draws.
        tab_rects, add_r, _ = self._layout_tabs()
        self._rects["tab"] = tab_rects
        self._rects["add"] = add_r

    def handle(self, event, screen) -> bool:
        if not self.active:
            return False

        # Ensure rects are up to date for collision detection
        self._update_rects(screen)

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
            if af in ("range", "radius", "width", "length", "duration", "level", "upcast_dice_bonus"):
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

        # Mouse wheel scrolls the tabs + form region.
        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, self._content_h - self._view_h)
            self._scroll_y = max(0, min(self._scroll_y - event.y * 30, max_scroll))
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

        # Whether the click landed inside the scrollable viewport. Clicks that
        # fall on the fixed header or button strip must not hit scrolled-out
        # tab/field rects that happen to sit at those coordinates.
        in_view = (self._view_rect is None) or self._view_rect.collidepoint(mx, my)

        # Check Add button first
        if in_view and "add" in self._rects and self._rects["add"].collidepoint(mx, my):
            if self._add_spell_cb:
                self._add_spell_cb()  # Open spell selection dialog
            else:
                self._add_spell()     # Fallback (shouldn't happen)
            return True

        self._active_field = None

        # Spell tabs
        if in_view and "tab" in self._rects:
            for i, tr in enumerate(self._rects["tab"]):
                if tr.collidepoint(mx, my):
                    self._save_form()
                    self._sel = i
                    self._load_form()
                    return True

        if in_view and self._f:
            # Toggle buttons (single choice)
            for group_key, options in [
                ("type",        ["Harm", "Heal", "Help"]),
                ("geometry",    ["Single", "Line", "Cone", "Sphere", "Square", "Rectangle"]),
                ("attack_type", ["AttackRoll", "Save", "Automatic"]),
                ("save_ability",["SaveStr","SaveDex","SaveCon","SaveInt","SaveWis","SaveCha"]),
            ]:
                for val in options:
                    rkey = f"{group_key}_{val}"
                    if rkey in self._rects and self._rects[rkey].collidepoint(mx, my):
                        self._f[group_key] = val
                        return True

            # Numeric / text fields
            for field_key in ("name", "range", "radius", "width", "length", "duration", "level", "upcast_dice_bonus"):
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

        # Ensure rects are up to date
        self._update_rects(screen)

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

        # Scrollable region: everything between the fixed header and the fixed
        # bottom buttons (tabs + editing form). Clip drawing to this viewport
        # and offset all content by -scroll_y so a tall form / many spell tabs
        # scroll instead of spilling off the bottom of the dialog.
        btn_y     = r.bottom - self.BTN_H - PAD
        view_top  = r.y + self.HDR_H
        view_bot  = btn_y - 10
        view_rect = pygame.Rect(r.x + 2, view_top, W - 4, max(0, view_bot - view_top))
        self._view_rect = view_rect
        base_y   = view_top + PAD - self._scroll_y   # top of first tab row
        self._view_h = max(0, view_bot - (view_top + PAD))

        prev_clip = screen.get_clip()
        screen.set_clip(view_rect)

        # Spell tabs + [+ Add] — wrapping multi-row layout so a long spell
        # list never overflows the dialog width.
        tab_rects, add_r, content_y = self._layout_tabs(base_y=base_y)
        for i, sp in enumerate(self._spells):
            tr = tab_rects[i]
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

        pygame.draw.rect(screen, (55, 85, 55), add_r, border_radius=4)
        pygame.draw.rect(screen, (80, 130, 80), add_r, 1, border_radius=4)
        screen.blit(self._font_md.render("+ Add", True, (180, 240, 180)),
                    (add_r.x + 6, add_r.centery - self._font_md.get_height() // 2))
        self._rects["add"] = add_r
        cy = content_y + PAD

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
            toggle_group("type", ["Harm", "Heal", "Help"], lx, cy, btn_w=90); cy += FH + PAD

            # Level and Upcast Dice Bonus (on same row)
            label("Spell Level", lx, cy)
            label("Upcast Dice", lx + RW // 2 + 6, cy)
            cy += 14
            text_field("level",    lx,               cy, RW // 2 - 4)
            text_field("upcast_dice_bonus", lx + RW // 2 + 4, cy, RW // 2 - 4)
            cy += FH + PAD

            # Geometry
            label("Geometry", lx, cy); cy += 14
            toggle_group("geometry", ["Single", "Line", "Cone", "Sphere", "Square"], lx, cy); cy += FH + PAD

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

        # Done with the scrolled region: measure content, un-clip, draw scrollbar.
        content_bottom = cy + FH
        self._content_h = max(0, content_bottom - base_y)
        screen.set_clip(prev_clip)

        max_scroll = max(0, self._content_h - self._view_h)
        if max_scroll > 0 and self._view_h > 0:
            track_top = view_top + PAD
            thumb_h = max(24, int(self._view_h * self._view_h / self._content_h))
            thumb_y = track_top + int((self._view_h - thumb_h) * self._scroll_y / max_scroll)
            pygame.draw.rect(screen, (60, 50, 85),
                             pygame.Rect(r.right - 9, track_top, 4, self._view_h),
                             border_radius=2)
            pygame.draw.rect(screen, (150, 110, 210),
                             pygame.Rect(r.right - 9, thumb_y, 4, thumb_h),
                             border_radius=2)

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
