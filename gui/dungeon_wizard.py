"""The New Dungeon wizard (plans/DUNGEON_WIZARD_PLAN.md D4–D8, step W4: the shell).

A step panel docked over the right-hand panel, like Wall Detection, with Back / Next /
Cancel and, once something is saved, Discard dungeon. The map view stays live beside
it: it is the working area the premade steps (W5, W6) crop and align on.

* **D4.** It needs no map open.
* **D6.** It is refused during combat, and while it is open connected players see
  "The DM is preparing the dungeon…" instead of the map (``net.view.players_held``).
* **D7.** Every step saves as it goes. Back reopens an earlier step; Cancel keeps what
  is saved and says where to carry on; Discard dungeon is a separate, explicit button
  that archives the dungeon's folder (moved to ``_archive/``, never deleted).
* **D8.** The first screen is the campaign (an existing one, New campaign…, or No
  campaign (loose)), the dungeon name, and Start from: Premade maps / Generate.
  Generate opens today's generator settings and builds into the dungeon just named.

Where a dungeon lives (D9): ``<campaign>/<slug>/`` in a campaign, else
``maps/<slug>/<slug>.dungeon.json`` (``app_dungeon_gen.loose_root``).

The model (``Target``, ``resolve_target``, ``discard``) is plain functions, so the
suites drive it without the panel; ``DungeonWizard`` is the panel.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass

import pygame

import app_dungeon_gen
import app_dungeon_pages
import save_layout
from dialogs import _wrap_words
from scene_store import CampaignStore
from widgets import TextInput

NEW_CAMPAIGN = "\0new"      # campaign-choice keys that are not a campaign's root
LOOSE = "\0loose"

PREMADE, GENERATE = "premade", "generate"

CONTINUE_HINT = "Continue with Dungeon → Floors… → Add."


@dataclass
class Target:
    """The dungeon the wizard is building, once the first screen is accepted."""
    campaign: str | None          # campaign root (made on first save if new); None: loose
    campaign_name: str | None     # a new campaign's display name, else None
    name: str                     # the dungeon's display name
    start: str                    # PREMADE or GENERATE

    @property
    def slug(self) -> str:
        return save_layout.slugify(self.name)

    def root(self) -> str:
        """The dungeon's folder: archived whole by Discard."""
        parent = self.campaign if self.campaign is not None else app_dungeon_gen.loose_root()
        return os.path.join(parent, self.slug)

    def manifest_path(self) -> str:
        if self.campaign is not None:
            return os.path.join(self.root(), save_layout.DUNGEON_FILE)
        return os.path.join(self.root(), f"{self.slug}.dungeon.json")


def campaign_choices(app) -> list[tuple[str, str]]:
    """``(key, label)`` rows of the first screen's campaign list: every campaign, then
    New campaign…, then No campaign (loose). A campaign's key is its root folder."""
    rows = [(p, save_layout.Campaign(p).name) for p in app_dungeon_pages.list_campaigns(app)]
    return rows + [(NEW_CAMPAIGN, "New campaign…"), (LOOSE, "No campaign (loose)")]


def resolve_target(app, choice, campaign_name: str, name: str, start: str) -> Target:
    """The first screen's answers as a ``Target``; ``ValueError`` says what is wrong.

    Nothing is written: a new campaign's folder is only chosen here (its name's slug,
    ``-2``, ``-3`` when taken) and made when the dungeon is first saved. A dungeon name
    already taken where it would go is refused, never replaced."""
    if choice is None:
        raise ValueError("Pick a campaign, or No campaign (loose).")
    name = (name or "").strip()
    if not name:
        raise ValueError("Name the dungeon.")
    save_layout.slugify(name)                 # ValueError names a bad name
    if start not in (PREMADE, GENERATE):
        raise ValueError("Pick Premade maps or Generate.")
    camp_root, camp_name = None, None
    if choice == NEW_CAMPAIGN:
        camp_name = (campaign_name or "").strip()
        if not camp_name:
            raise ValueError("Name the new campaign.")
        root = app_dungeon_pages.campaigns_root(app)
        taken = os.listdir(root) if os.path.isdir(root) else ()
        camp_root = os.path.join(root, save_layout.unique_slug(camp_name, taken))
    elif choice != LOOSE:
        camp_root = choice
    target = Target(camp_root, camp_name, name, start)
    if os.path.exists(target.root()):
        where = (save_layout.Campaign(camp_root).name if camp_root and choice != NEW_CAMPAIGN
                 else "maps/")
        raise ValueError(f"{where} already has a dungeon '{target.slug}'.")
    return target


def discard(app, target: Target) -> str | None:
    """Discard dungeon (D7): move the dungeon's folder to ``_archive/<slug>-<stamp>``
    beside it, never deleting anything. If it is the dungeon showing, the app goes back
    to the blank map first, so nothing writes into the archived folder afterwards.
    Returns where it went, or None when there was nothing to move."""
    root = target.root()
    if not os.path.isdir(root):
        return None
    if app.dungeon is not None and app._dungeon_manifest_path and \
            os.path.abspath(app._dungeon_manifest_path).startswith(os.path.abspath(root) + os.sep):
        app_dungeon_gen.load_blank_scene(app)
    arch = os.path.join(os.path.dirname(root), "_archive")
    os.makedirs(arch, exist_ok=True)
    stem = f"{target.slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    dst = os.path.join(arch, save_layout.unique_slug(stem, os.listdir(arch)))
    shutil.move(root, dst)
    return dst


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


class DungeonWizard:
    """The docked step panel. ``app.dungeon_wizard``; ``start(app)`` opens it.

    Steps are names on a stack (``history``): Back pops one. ``saved`` turns true when
    a step has written the dungeon (W5 onward), which is what offers Discard and what
    Cancel reports."""
    PAD = 12
    HDR_H = 30
    ROW_H = 30
    BTN_H = 30

    TITLES = {"start": "1. Start", "source": "2. Pick an image"}

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.app = None
        self.rect = None
        self._reset()

    def _reset(self):
        self.step = "start"
        self.history: list[str] = []
        self.target: Target | None = None
        self.saved = False
        self.error = ""
        self.choices: list[tuple[str, str]] = []
        self.choice = None
        self.start_from = PREMADE
        self.camp_input = TextInput(pygame.Rect(0, 0, 10, 10), "campaign name", self.font_md)
        self.name_input = TextInput(pygame.Rect(0, 0, 10, 10), "dungeon name", self.font_md)
        self._hit: list[tuple[pygame.Rect, str, object]] = []    # (rect, kind, value)
        self._frames_since_show = 0

    # ── Opening and closing ───────────────────────────────────────────────

    def start(self, app, campaign: str | None = None) -> bool:
        """Open on the first screen. ``campaign`` (a root) is preselected, else the
        campaign of the dungeon showing. Refused during combat (D6)."""
        if app.combat_active:
            app._flash_status("Finish combat before starting a dungeon.")
            return False
        if self.visible:
            return True
        self.app = app
        self._reset()
        self.choices = campaign_choices(app)
        if campaign is None and isinstance(app.store, CampaignStore):
            campaign = app.store.campaign.root
        if campaign is not None:
            self.choice = next((k for k, _ in self.choices
                                if k not in (NEW_CAMPAIGN, LOOSE)
                                and _same_dir(k, campaign)), None)
        self.name_input.active = True
        self.visible = True
        self._layout()
        return True

    def close(self):
        self.visible = False
        for t in (self.camp_input, self.name_input):
            t.active = False

    # ── Buttons ───────────────────────────────────────────────────────────

    def next(self):
        app = self.app
        self.error = ""
        if self.step == "start":
            try:
                target = resolve_target(app, self.choice, self.camp_input.text,
                                        self.name_input.text, self.start_from)
            except ValueError as e:
                self.error = str(e)
                return
            self.target = target
            if target.start == GENERATE:
                if app_dungeon_gen.wizard_generate(app, target):
                    self.close()
                return
            self._goto("source")
            return
        # "source" and later: W5.

    def back(self):
        self.error = ""
        if self.history:
            self.step = self.history.pop()
            self._layout()

    def cancel(self):
        """Close, keeping everything saved (D7)."""
        self.close()
        if self.saved:
            self.app._flash_status(f"{self.target.name} is saved. {CONTINUE_HINT}", secs=5)
        else:
            self.app._flash_status("New Dungeon cancelled; nothing was saved.")

    def ask_discard(self):
        """Discard dungeon, after asking: its folder goes to ``_archive/``."""
        if not (self.saved and self.target):
            return
        t = self.target
        self.app._ask_dm("action", f"Discard dungeon {t.name}? It is moved to _archive/.",
                         [("Discard", self.discard), ("Keep", lambda: None)],
                         anchor=self.rect.center, render="titled")

    def discard(self):
        try:
            dst = discard(self.app, self.target)
        except OSError as e:
            self.error = f"Could not discard: {e}"
            return
        self.close()
        self.app._flash_status(
            f"Discarded {self.target.name}" + (f" (moved to {os.path.relpath(dst)})" if dst
                                               else "; nothing had been saved."), secs=5)

    def mark_saved(self):
        """A step wrote the dungeon (W5 onward): Discard is offered from now on."""
        self.saved = True
        self._layout()

    def _goto(self, step):
        self.history.append(self.step)
        self.step = step
        self._layout()

    # ── Layout, events, drawing ───────────────────────────────────────────

    def _layout(self):
        """Place this step's widgets and record their hit rects."""
        app = self.app
        panel = app._panel_rect()
        # The whole panel's width, so none of its buttons show (or take a click) beside it.
        self.rect = pygame.Rect(panel.x + 4, panel.y + 40, panel.w - 8, max(320, panel.h - 80))
        ix, iw = self.rect.x + self.PAD, self.rect.w - 2 * self.PAD
        y = self.rect.y + self.HDR_H + self.PAD
        self._hit = []
        self._labels = []       # (text, (x, y)) drawn as field labels
        if self.step == "start":
            self._labels.append(("Campaign", (ix, y)))
            y += 22
            for key, label in self.choices:
                self._hit.append((pygame.Rect(ix, y, iw, self.ROW_H - 4), "choice", key))
                y += self.ROW_H
            if self.choice == NEW_CAMPAIGN:
                self.camp_input.rect = pygame.Rect(ix, y, iw, self.ROW_H - 4)
                y += self.ROW_H
            y += 6
            self._labels.append(("Dungeon name", (ix, y)))
            y += 22
            self.name_input.rect = pygame.Rect(ix, y, iw, self.ROW_H - 4)
            y += self.ROW_H + 6
            self._labels.append(("Start from", (ix, y)))
            y += 22
            cw = (iw - 6) // 2
            for i, (val, _lbl) in enumerate(((PREMADE, "Premade maps"), (GENERATE, "Generate"))):
                self._hit.append((pygame.Rect(ix + i * (cw + 6), y, cw, self.ROW_H - 4),
                                  "start", val))
            y += self.ROW_H
        self._body_bottom = y
        bw, bh = 84, self.BTN_H
        by = self.rect.bottom - self.PAD - bh
        self._hit.append((pygame.Rect(self.rect.x + self.PAD, by, bw, bh), "button", "back"))
        self._hit.append((pygame.Rect(self.rect.centerx - bw // 2, by, bw, bh), "button", "cancel"))
        self._hit.append((pygame.Rect(self.rect.right - self.PAD - bw, by, bw, bh), "button", "next"))
        if self.saved:
            self._hit.append((pygame.Rect(ix, by - bh - 8, iw, bh), "button", "discard"))

    def button_rect(self, which: str) -> pygame.Rect | None:
        """The hit rect of a button (back / cancel / next / discard) or a chip, for tests
        and the headless driver."""
        return next((r for r, _k, v in self._hit if v == which), None)

    def _enabled(self, which: str) -> bool:
        if which == "back":
            return bool(self.history)
        if which == "next":
            return self.step == "start"
        return True

    def handle(self, event) -> bool:
        """True when the panel used the event; map-view events (wheel, pan, clicks off
        the panel) are left to the app."""
        if not self.visible or not self.rect:
            return False
        inputs = (self.camp_input, self.name_input) if self.step == "start" else ()
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.cancel()
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self._enabled("next"):
                    self.next()
                return True
            if event.key == pygame.K_TAB and self.step == "start":
                both = [t for t in inputs if t is self.name_input or self.choice == NEW_CAMPAIGN]
                cur = next((i for i, t in enumerate(both) if t.active), -1)
                for t in inputs:
                    t.active = False
                both[(cur + 1) % len(both)].active = True
                return True
            active = next((t for t in inputs if t.active), None)
            if active is not None:
                active.handle(event)
                return True
            return False               # arrows / +/- reach the map's pan and zoom
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.rect.collidepoint(*event.pos):
                return False
            for t in inputs:
                if t is self.camp_input and self.choice != NEW_CAMPAIGN:
                    continue
                t.handle(event)
            hit = next(((k, v) for r, k, v in self._hit if r.collidepoint(*event.pos)), None)
            if hit is None:
                return True
            kind, val = hit
            if kind == "choice":
                self.choice = val
                if val == NEW_CAMPAIGN:
                    self.name_input.active = False
                    self.camp_input.active = True
                self._layout()
            elif kind == "start":
                self.start_from = val
            elif kind == "button" and self._enabled(val):
                {"back": self.back, "cancel": self.cancel, "next": self.next,
                 "discard": self.ask_discard}[val]()
            return True
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and \
                self.rect.collidepoint(*event.pos):
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)
        hdr = f"New Dungeon — {self.TITLES.get(self.step, self.step)}"
        surf.blit(self.font_md.render(hdr, True, (220, 220, 235)),
                  (self.rect.x + self.PAD, self.rect.y + 7))
        lab = (185, 185, 200)
        for text, pos in self._labels:
            surf.blit(self.font_md.render(text, True, lab), pos)
        labels = dict(self.choices)
        for r, kind, val in self._hit:
            if kind == "choice":
                self._chip(surf, r, labels[val], self.choice == val)
            elif kind == "start":
                self._chip(surf, r, "Premade maps" if val == PREMADE else "Generate",
                           self.start_from == val)
        if self.step == "start":
            if self.choice == NEW_CAMPAIGN:
                self.camp_input.draw(surf)
            self.name_input.draw(surf)
            hint = ("Next opens the generator's settings; the dungeon is built on the blank map."
                    if self.start_from == GENERATE else
                    "Next picks the first image: a sheet of several levels, or one level.")
        else:
            hint = ("Picking an image, setting its grid and cropping floors arrive in the "
                    "next update (W5). Back to choose Generate, or Cancel.")
        y = self._body_bottom + 8
        for line in _wrap_words(hint, self.font_sm, self.rect.w - 2 * self.PAD):
            surf.blit(self.font_sm.render(line, True, (170, 170, 185)), (self.rect.x + self.PAD, y))
            y += self.font_sm.get_linesize()
        if self.error:
            y += 6
            for line in _wrap_words(self.error, self.font_sm, self.rect.w - 2 * self.PAD):
                surf.blit(self.font_sm.render(line, True, (235, 120, 110)),
                          (self.rect.x + self.PAD, y))
                y += self.font_sm.get_linesize()
        colors = {"back": (55, 55, 75), "cancel": (90, 45, 45), "next": (35, 90, 45),
                  "discard": (110, 40, 40)}
        names = {"back": "Back", "cancel": "Cancel", "next": "Next",
                 "discard": "Discard dungeon"}
        for r, kind, val in self._hit:
            if kind != "button":
                continue
            on = self._enabled(val)
            pygame.draw.rect(surf, colors[val] if on else (45, 45, 55), r, border_radius=6)
            t = self.font_md.render(names[val], True, (225, 225, 225) if on else (120, 120, 130))
            surf.blit(t, t.get_rect(center=r.center))

    def _chip(self, surf, r, text, on):
        pygame.draw.rect(surf, (70, 60, 130) if on else (45, 45, 62), r, border_radius=4)
        pygame.draw.rect(surf, (150, 130, 220) if on else (80, 80, 100), r, 1, border_radius=4)
        t = self.font_md.render(text, True, (235, 235, 245))
        surf.blit(t, t.get_rect(midleft=(r.x + 8, r.centery)))
