# ─────────────────────────────────────────────────────────────────────────────
#  weapon_dialog.py  –  Weapon editing dialog
# ─────────────────────────────────────────────────────────────────────────────

import pygame
import copy
import rpg_battle_map as rpg
from constants import *
from widgets import Button
from helpers import _parse_physical_damage, _parse_magic_damage, _DEFAULT_WEAPON, _weapon_to_dict, _dict_to_weapon

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
            if af and (af in ("normal_range_ft", "long_range_ft", "bonus_hit", "bonus_damage") or
                      af.startswith("phys_") or af.startswith("mag_")):
                # Handle per-type dice fields (phys_num_dice_X, phys_die_size_X, mag_num_dice_X, mag_die_size_X)
                if af.startswith("phys_") or af.startswith("mag_"):
                    prefix, field_type, type_name = af.split("_", 2)
                    key = f"{prefix}_damage_types"
                    rolls = self._f.get(key, [])
                    entry = next((r for r in rolls if r.get("type") == type_name), None)
                    if entry:
                        field_name = "num_dice" if field_type == "num" else "die_size"
                        cur = str(entry.get(field_name, ""))
                else:
                    cur = str(self._f.get(af, ""))
                    field_name = af

                if event.key == pygame.K_BACKSPACE:
                    cur = cur[:-1]
                    val = int(cur) if cur.isdigit() else 0
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self._active_field = None
                    return True
                elif event.unicode.isdigit():
                    cur += event.unicode
                    val = int(cur)
                else:
                    return True

                if af.startswith("phys_") or af.startswith("mag_"):
                    entry[field_name] = val
                else:
                    self._f[af] = val
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
            for flag in ("finesse", "thrown", "proficient", "off_hand"):
                if flag in self._rects and self._rects[flag].collidepoint(mx, my):
                    self._f[flag] = not self._f.get(flag, False)
                    return True

            # Text / numeric input fields (includes per-type dice)
            numeric_keys = ["name", "normal_range_ft", "long_range_ft"]
            numeric_keys += [k for k in self._rects.keys() if k.startswith("phys_") or k.startswith("mag_")]
            for field_key in numeric_keys:
                if field_key in self._rects and \
                        self._rects[field_key].collidepoint(mx, my):
                    self._active_field = field_key
                    return True

            # Physical damage type toggles
            phys_types = [
                (rpg.PhysicalDamage.Bludgeoning, "Bludg.", "Bludgeoning"),
                (rpg.PhysicalDamage.Piercing,    "Pierc.", "Piercing"),
                (rpg.PhysicalDamage.Slashing,    "Slash", "Slashing"),
            ]
            for val, lbl, type_name in phys_types:
                if f"phys_toggle_{val.name}" in self._rects and \
                        self._rects[f"phys_toggle_{val.name}"].collidepoint(mx, my):
                    rolls = self._f.get("physical_damage_types", [])
                    if any(r.get("type") == val.name for r in rolls):
                        self._f["physical_damage_types"] = [r for r in rolls if r.get("type") != val.name]
                    else:
                        new_roll = {"type": val.name, "num_dice": 1, "die_size": 6}
                        self._f["physical_damage_types"].append(new_roll)
                    return True

            # Magic damage type toggles
            mag_types = [
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
            for val, lbl in mag_types:
                if f"mag_toggle_{val.name}" in self._rects and \
                        self._rects[f"mag_toggle_{val.name}"].collidepoint(mx, my):
                    rolls = self._f.get("magic_damage_types", [])
                    if any(r.get("type") == val.name for r in rolls):
                        self._f["magic_damage_types"] = [r for r in rolls if r.get("type") != val.name]
                    else:
                        new_roll = {"type": val.name, "num_dice": 1, "die_size": 6}
                        self._f["magic_damage_types"].append(new_roll)
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
            checkbox("off_hand",  lx + CB_STRIDE * 3,cy, "Off-hand")
            cy += 24 + PAD

            # ── Bonuses ────────────────────────────────────────────────────
            label("Bonuses", lx, cy)
            label("+Dmg", lx + RW // 2, cy)
            cy += 14
            text_field("bonus_hit",    lx,              cy, RW // 2 - 4)
            text_field("bonus_damage", lx + RW // 2 + 4, cy, RW // 2 - 4)
            cy += FH + PAD

            # ── Physical Damage ────────────────────────────────────────────
            label("Physical Damage", lx, cy)
            cy += 14
            phys_types = [
                (rpg.PhysicalDamage.Bludgeoning, "Bludg."),
                (rpg.PhysicalDamage.Piercing,    "Pierc."),
                (rpg.PhysicalDamage.Slashing,    "Slash"),
            ]
            pbw = (RW - 2 * 4) // 3
            active_phys = self._f.get("physical_damage_types", [])
            for entry in active_phys:
                type_name = entry.get("type", "Slashing")
                btn_rect = pygame.Rect(lx, cy, pbw, FH)
                pygame.draw.rect(screen, (80, 55, 120), btn_rect, border_radius=4)
                pygame.draw.rect(screen, (140, 100, 200), btn_rect, 1, border_radius=4)
                ts = self._font_sm.render(type_name[:8], True, (230, 210, 255))
                screen.blit(ts, (btn_rect.x + 4, btn_rect.centery - ts.get_height() // 2))
                self._rects[f"phys_type_{type_name}"] = btn_rect
                nd_key = f"phys_num_dice_{type_name}"
                ds_key = f"phys_die_size_{type_name}"
                text_field(nd_key, lx + pbw + 4, cy, 35)
                ds_label = self._font_md.render("d", True, (170, 170, 200))
                screen.blit(ds_label, (lx + pbw + 40, cy + (FH - ds_label.get_height()) // 2))
                text_field(ds_key, lx + pbw + 48, cy, 40)
                cy += FH + 4
            for i, (val, lbl_text) in enumerate(phys_types):
                bx = lx + i * (pbw + 4)
                rect = pygame.Rect(bx, cy, pbw, FH)
                is_active = any(e.get("type") == val.name for e in active_phys)
                pygame.draw.rect(screen, (80, 55, 120) if is_active else (48, 48, 64), rect, border_radius=4)
                pygame.draw.rect(screen, (140, 100, 200) if is_active else (75, 75, 100), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True, (230, 210, 255) if is_active else (150, 150, 180))
                screen.blit(ts, (rect.x + (pbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"phys_toggle_{val.name}"] = rect
            cy += FH + 8

            # ── Magic Damage ───────────────────────────────────────────────
            label("Magic Damage", lx, cy)
            cy += 14
            mag_types = [
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
            active_mag = self._f.get("magic_damage_types", [])
            mbw = (RW - 2 * 4) // 3
            for entry in active_mag:
                type_name = entry.get("type", "Fire")
                btn_rect = pygame.Rect(lx, cy, mbw, FH)
                pygame.draw.rect(screen, (55, 100, 80), btn_rect, border_radius=4)
                pygame.draw.rect(screen, (90, 160, 130), btn_rect, 1, border_radius=4)
                ts = self._font_sm.render(type_name[:8], True, (180, 240, 210))
                screen.blit(ts, (btn_rect.x + 4, btn_rect.centery - ts.get_height() // 2))
                self._rects[f"mag_type_{type_name}"] = btn_rect
                nd_key = f"mag_num_dice_{type_name}"
                ds_key = f"mag_die_size_{type_name}"
                text_field(nd_key, lx + mbw + 4, cy, 35)
                ds_label = self._font_md.render("d", True, (170, 170, 200))
                screen.blit(ds_label, (lx + mbw + 40, cy + (FH - ds_label.get_height()) // 2))
                text_field(ds_key, lx + mbw + 48, cy, 40)
                cy += FH + 4
            mbw = (RW - 4 * 4) // 5
            for i, (val, lbl_text) in enumerate(mag_types):
                row = i // 5
                col = i % 5
                bx   = lx + col * (mbw + 4)
                by   = cy + row * (FH + 4)
                rect = pygame.Rect(bx, by, mbw, FH)
                is_active = any(e.get("type") == val.name for e in active_mag)
                pygame.draw.rect(screen, (55, 100, 80) if is_active else (48, 48, 64), rect, border_radius=4)
                pygame.draw.rect(screen, (90, 160, 130) if is_active else (75, 75, 100), rect, 1, border_radius=4)
                ts = self._font_md.render(lbl_text, True, (180, 240, 210) if is_active else (150, 150, 180))
                screen.blit(ts, (rect.x + (mbw - ts.get_width()) // 2,
                                 rect.centery - ts.get_height() // 2))
                self._rects[f"mag_toggle_{val.name}"] = rect
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

