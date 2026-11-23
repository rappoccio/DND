"""The New Dungeon wizard (plans/DUNGEON_WIZARD_PLAN.md D4–D16; W4 the shell, W5 the
premade steps).

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

The premade path (D10–D16, W5): pick an image (a file, or a campaign library map), Set
Grid on it, crop a floor (grid-snapped, with a blank-outside brush), name it, then
another floor from the same sheet or another image, or Finish. The sheet is drawn over
the map view by ``sheet_canvas.SheetCanvas``; ``wizard_floors`` does the geometry and the
writing. Naming a floor writes it, and the dungeon around it, so from the first floor on
the dungeon opens.

Placement and alignment (D17–D19, W6): the first floor is floor 0 and the entry. Each
later floor, once named, is placed above / below / beside a floor already written
(``floor_place``), then aligned on ``align_canvas.AlignCanvas``: a landmark pair, arrow
keys a cell at a time, Enter accepts, Skip keeps the default corner.

The model (``Target``, ``resolve_target``, ``discard``) is plain functions, so the
suites drive it without the panel; ``DungeonWizard`` is the panel.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field

import pygame

import app_dungeon_gen
import app_dungeon_pages
import dungeon as dg
import floor_place as fp
import save_layout
import wizard_floors as wf
from align_canvas import COL_FADED, COL_FAINT, COL_MARK_A, COL_MARK_B, COL_NEW, AlignCanvas, Layer
from dialogs import _wrap_words
from scene_store import CampaignStore
from sheet_canvas import SheetCanvas
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


def discard(app, target: Target, library=()) -> str | None:
    """Discard dungeon (D7): move the dungeon's folder to ``_archive/<slug>-<stamp>``
    beside it, never deleting anything, with the campaign library folders this wizard
    made for it (``library``: its floors and copied sheets) under ``library/`` there.
    If it is the dungeon showing, the app goes back to the blank map first, so nothing
    writes into the archived folder afterwards. Returns where it went, or None when
    there was nothing to move."""
    root = target.root()
    library = [d for d in library if os.path.isdir(d)]
    if not os.path.isdir(root) and not library:
        return None
    if app.dungeon is not None and app._dungeon_manifest_path and \
            os.path.abspath(app._dungeon_manifest_path).startswith(os.path.abspath(root) + os.sep):
        app_dungeon_gen.load_blank_scene(app)
    arch = os.path.join(os.path.dirname(root), "_archive")
    os.makedirs(arch, exist_ok=True)
    stem = f"{target.slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    dst = os.path.join(arch, save_layout.unique_slug(stem, os.listdir(arch)))
    if os.path.isdir(root):
        shutil.move(root, dst)
    for d in library:
        os.makedirs(os.path.join(dst, "library"), exist_ok=True)
        shutil.move(d, os.path.join(dst, "library", os.path.basename(d)))
    return dst


@dataclass(eq=False)
class Floor:
    """A floor being made: its sheet, its crop (drawn-square indices on the sheet), the
    squares the brush blanked, and the name it is written under once named."""
    sheet: wf.Sheet
    squares: tuple | None = None
    blanks: set = field(default_factory=set)
    written: str | None = None
    ref: str | None = None                 # W6: the floor it is placed against
    relation: str = fp.ABOVE


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


class DungeonWizard:
    """The docked step panel. ``app.dungeon_wizard``; ``start(app)`` opens it.

    Steps are names on a stack (``history``, with the floor and sheet each was about):
    Back pops one and reopens it for editing. ``saved`` turns true when a floor has been
    written, which is what offers Discard and what Cancel reports."""
    PAD = 12
    HDR_H = 30
    ROW_H = 30
    BTN_H = 30

    TITLES = {"start": "1. Start", "source": "2. Pick an image", "grid": "3. Set Grid",
              "crop": "4. Crop a floor", "name": "5. Name the floor",
              "place": "6. Place the floor", "align": "7. Align the floor",
              "more": "8. Another floor?"}
    CANVAS_STEPS = ("grid", "crop", "name", "more")
    ALIGN_STEPS = ("place", "align")
    FT_CHOICES = (5, 10)

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.app = None
        self.rect = None
        self.canvas = SheetCanvas()
        self.align = AlignCanvas()
        self._reset()

    def _reset(self):
        self.step = "start"
        self.history: list[tuple] = []
        self.target: Target | None = None
        self.saved = False
        self.error = ""
        self.choices: list[tuple[str, str]] = []
        self.choice = None
        self.start_from = PREMADE
        self.camp_input = TextInput(pygame.Rect(0, 0, 10, 10), "campaign name", self.font_md)
        self.name_input = TextInput(pygame.Rect(0, 0, 10, 10), "dungeon name", self.font_md)
        # The premade path (W5).
        self.writer: wf.FloorWriter | None = None
        self.sheets: list[wf.Sheet] = []
        self.sheet: wf.Sheet | None = None
        self.floors: list[Floor] = []          # written, in order
        self.cur: Floor | None = None          # the floor the crop / name steps edit
        self.across, self.down = 1, 1
        self.square_ft = 5                     # D13: the last sheet's, by default
        self.ft_other = False
        self.ft_input = TextInput(pygame.Rect(0, 0, 10, 10), "feet", self.font_md)
        self.floor_input = TextInput(pygame.Rect(0, 0, 10, 10), "floor name", self.font_md)
        self.grid_box = None                   # (x, y, w, h) in sheet px, the last Set Grid drag
        self.brush = None                      # None, "paint" or "erase"
        self._drag = None                      # ("box" | "pan" | "brush", start, current)
        self.canvas.clear()
        # Placement and alignment (W6).
        self.align.clear()
        self.place_preview: dg.Dungeon | None = None
        self.align_dung: dg.Dungeon | None = None
        self.align_page: dg.MapPage | None = None
        self.skip_origin: list[int] | None = None
        self.mark_a = None                     # the landmark on the new floor, cells from its origin
        self.mark_b = None                     # the same point on the faded floor, global cells
        self._refs: dict[str, int] = {}       # Place's floors to place against: id → z
        self._hit: list[tuple[pygame.Rect, str, object]] = []    # (rect, kind, value)
        self._labels = []
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
        for t in self._all_inputs():
            t.active = False
        self.canvas.clear()
        self.align.clear()

    def _all_inputs(self):
        return (self.camp_input, self.name_input, self.ft_input, self.floor_input)

    def _inputs(self):
        """The text fields the current step shows."""
        if self.step == "start":
            return [self.name_input] + ([self.camp_input] if self.choice == NEW_CAMPAIGN else [])
        if self.step == "grid" and self.ft_other and not self._grid_locked():
            return [self.ft_input]
        if self.step == "name":
            return [self.floor_input]
        return []

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
            self.writer = wf.FloorWriter(target)
            self._goto("source")
        elif self.step == "source":
            if self.sheet is not None:
                self._goto("grid")
        elif self.step == "grid":
            if self.sheet is None or self.sheet.grid is None:
                self.error = "Drag a box over whole squares on the map first."
                return
            self.square_ft = self.sheet.grid.square_ft
            if self.cur is None or self.cur.sheet is not self.sheet:
                self.cur = Floor(self.sheet)
            self._goto("crop")
        elif self.step == "crop":
            if self.cur is None or self.cur.squares is None:
                self.error = "Drag a rectangle on the map, or Whole image."
                return
            self.floor_input.text = self.cur.written or self._default_name()
            self.floor_input.active = True
            self._goto("name")
        elif self.step == "name":
            self._write_floor()
        elif self.step == "place":
            self._place()
        elif self.step == "align":
            self.accept_align()
        elif self.step == "more":
            self.finish()

    def back(self):
        self.error = ""
        if self._enabled("back"):
            self.step, self.cur, self.sheet = self.history.pop()
            self._drag = None
            if self.step == "name" and self.cur is not None:
                self.floor_input.text = self.cur.written or self._default_name()
            if self.step == "align":
                self._load_align()
            if self.step in self.ALIGN_STEPS:
                self._refresh_align()
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
            dst = discard(self.app, self.target,
                          self.writer.created if self.writer is not None else ())
        except OSError as e:
            self.error = f"Could not discard: {e}"
            return
        self.close()
        self.app._flash_status(
            f"Discarded {self.target.name}" + (f" (moved to {os.path.relpath(dst)})" if dst
                                               else "; nothing had been saved."), secs=5)

    def mark_saved(self):
        """A floor was written: Discard is offered from now on."""
        self.saved = True
        self._layout()

    def finish(self):
        """Close, open the dungeon on its entry floor, and show its checklist (D21)."""
        app, t = self.app, self.target
        if not self.floors:
            self.error = "Write at least one floor first."
            return
        self.close()
        if app.dungeon_page is not None:          # leave the page showing as a switch would
            app._save_agents()
            app._save_terrain()
        if t.campaign is not None:
            app_dungeon_pages.open_campaign_dungeon(app, t.manifest_path())
        else:
            app_dungeon_pages.on_open_dungeon_chosen(app, t.manifest_path())
        n = len(self.floors)
        app._flash_status(f"{t.name}: {n} floor{'s' if n != 1 else ''}. "
                          "Click a floor's walls, doors or staircases to work on them.",
                          secs=6)
        if app.dungeon is not None:
            app.floor_checklist.open(app)

    def _goto(self, step):
        self.history.append((self.step, self.cur, self.sheet))
        self.step = step
        self._drag = None
        self._layout()

    # ── The premade steps (W5) ────────────────────────────────────────────

    def pick_file(self):
        """Pick an image from a file (D11)."""
        start = (self.target.campaign if self.target and self.target.campaign
                 and os.path.isdir(self.target.campaign) else self.app._map_dir)
        self.app.file_browser.open(start, self.on_file_chosen, save_mode=False,
                                   extensions=set(save_layout.IMAGE_EXTS),
                                   title="New Dungeon — Pick an Image")

    def library(self) -> list[str]:
        """The campaign library's maps that have an image, sources first."""
        camp = self.writer.campaign() if self.writer else None
        if camp is None:
            return []
        maps = [m for m in camp.list_library_maps()
                if save_layout.find_image(camp.library_map_dir(m), m)]
        src = set(camp.list_sources())
        return sorted(maps, key=lambda m: (m not in src, m))

    def pick_library(self):
        maps = self.library()
        if not maps:
            self.error = "The campaign's library has no maps."
            return
        src = set(self.writer.campaign().list_sources())
        self.app._ask_dm("action", "Pick a library map",
                         [((f"{m}  (sheet)" if m in src else m),
                           (lambda m=m: self.on_library_chosen(m))) for m in maps],
                         anchor=self.rect.center, render="titled")

    def on_file_chosen(self, path: str):
        if not path:
            return
        ap = os.path.abspath(path)
        camp = self.writer.campaign() if self.writer else None
        if camp is not None:      # a file that is a library map's image is that map
            folder = os.path.dirname(ap)
            name = os.path.basename(folder)
            if _same_dir(os.path.dirname(folder), camp.maps_dir) and \
                    os.path.splitext(os.path.basename(ap))[0] == name:
                self.on_library_chosen(name)
                return
        sheet = next((s for s in self.sheets if not s.library and
                      os.path.abspath(s.image) == ap), None)
        if sheet is None:
            try:
                sheet = wf.sheet_from_file(ap)
            except OSError as e:
                self.error = f"Could not read {os.path.basename(ap)}: {e}"
                return
            self.sheets.append(sheet)
        self._use_sheet(sheet)

    def on_library_chosen(self, map_name: str):
        sheet = next((s for s in self.sheets if s.library and s.name == map_name), None)
        if sheet is None:
            try:
                sheet = wf.sheet_from_library(self.writer.campaign(), map_name)
            except (OSError, ValueError) as e:
                self.error = str(e)
                return
            self.sheets.append(sheet)
        self._use_sheet(sheet)

    def _use_sheet(self, sheet):
        """Go on to Set Grid with ``sheet``. One with a grid (a sheet already used in
        this run, or a library source) shows it, and Next keeps it (D12)."""
        self.error = ""
        self.sheet = sheet
        self.cur = None
        self.grid_box = None
        self.across = self.down = 1
        if sheet.grid is not None:
            self._set_ft(sheet.grid.square_ft)
        else:
            self._set_ft(self.square_ft)
        if self.step == "source":
            self._goto("grid")
        else:
            self._layout()

    def _set_ft(self, ft):
        self.ft_other = ft not in self.FT_CHOICES
        self.ft_input.text = str(ft) if self.ft_other else ""
        self.square_ft = ft

    def _grid_locked(self) -> bool:
        return bool(self.sheet and self.sheet.grid_locked)

    def _chosen_ft(self) -> int | None:
        if not self.ft_other:
            return self.square_ft
        try:
            return int(self.ft_input.text.strip())
        except ValueError:
            return None

    def _regrid(self):
        """Measure the sheet's grid again from the last box and the step's settings."""
        if self.sheet is None or self._grid_locked() or self.grid_box is None:
            return
        ft = self._chosen_ft()
        if ft is None:
            self.error = "Type the square's size in feet."
            return
        try:
            self.sheet.grid = wf.measure_grid(self.grid_box, self.across, self.down, ft)
            self.error = ""
        except ValueError as e:
            self.error = str(e)

    def set_grid_box(self, p0, p1):
        """A Set Grid drag from ``p0`` to ``p1``, sheet pixels."""
        x0, x1 = sorted((p0[0], p1[0]))
        y0, y1 = sorted((p0[1], p1[1]))
        if x1 - x0 < 3 or y1 - y0 < 3:
            return
        self.grid_box = (x0, y0, x1 - x0, y1 - y0)
        self._regrid()

    def set_crop(self, p0, p1):
        """A crop drag from ``p0`` to ``p1``, sheet pixels, snapped to the grid (D14)."""
        sq = wf.snap_squares(self.sheet.grid, self.sheet.size, p0, p1)
        if sq is None:
            self.error = "That covers no whole square."
            return
        self.error = ""
        self.cur.squares = sq

    def whole_image(self):
        sq = wf.whole_image(self.sheet.grid, self.sheet.size)
        if sq is None:
            self.error = "The grid has no whole square on this image."
            return
        self.error = ""
        self.cur.squares = sq

    def brush_at(self, pt):
        """The blank-outside brush (D14) at ``pt`` (sheet pixels): paint or erase the
        drawn square there, inside the crop."""
        if self.cur is None or self.cur.squares is None or self.brush is None:
            return
        g = self.sheet.grid
        k = int((pt[0] - g.anchor[0]) // g.square_px)
        j = int((pt[1] - g.anchor[1]) // g.square_px)
        k0, j0, k1, j1 = self.cur.squares
        if not (k0 <= k < k1 and j0 <= j < j1):
            return
        if self.brush == "paint":
            self.cur.blanks.add((k, j))
        else:
            self.cur.blanks.discard((k, j))

    def _default_name(self) -> str:
        names = {f.written for f in self.floors}
        n = len(self.floors) + 1
        while True:
            name = wf.default_floor_name(self.target.slug, n)
            if name not in names and self.writer.floor_name_problem(name) is None:
                return name
            n += 1

    def _write_floor(self):
        name = self.floor_input.text.strip()
        if not name:
            self.error = "Name the floor."
            return
        f = self.cur
        others = {g.written for g in self.floors if g is not f}
        if name in others:
            self.error = f"This dungeon already has a floor '{name}'."
            return
        origin = None
        if f.written is None:
            path = self.target.manifest_path()
            pages = dg.Dungeon.load(path).pages if os.path.isfile(path) else []
            origin = wf.next_floor_origin(pages)
        try:
            self.writer.write_floor(name, f.sheet, f.squares, f.blanks, origin=origin,
                                    old_name=f.written)
        except (OSError, ValueError) as e:
            self.error = str(e)
            return
        f.written = name
        if f not in self.floors:
            self.floors.append(f)
        self.floor_input.active = False
        self.mark_saved()
        if f is self.floors[0]:                # D17: floor 0, the entry; nothing to place
            self._goto("more")
            return
        self._goto("place")
        self._refresh_align()

    # ── Placement and alignment (W6, D17–D19) ─────────────────────────────

    def place_refs(self) -> list[tuple[str, int]]:
        """``(page id, z)`` of every floor the current one can be placed against, top
        floor first."""
        dung = self.writer.load_dungeon()
        if dung is None or self.cur is None:
            return []
        return [(p.id, p.z) for p in sorted(dung.pages, key=lambda p: -p.z)
                if p.id != self.cur.written]

    def _default_ref(self) -> str | None:
        """The floor written before this one, else the entry."""
        refs = [pid for pid, _z in self.place_refs()]
        if self.cur.ref in refs:
            return self.cur.ref
        i = self.floors.index(self.cur) if self.cur in self.floors else len(self.floors)
        for g in reversed(self.floors[:i]):
            if g.written in refs:
                return g.written
        return refs[0] if refs else None

    def set_place(self, ref=None, relation=None):
        """Choose what the floor is placed against, and how (a chip click)."""
        if ref is not None:
            self.cur.ref = ref
        if relation is not None:
            self.cur.relation = relation
        self._refresh_align()

    def _refresh_align(self, fit: bool = True):
        """Rebuild the Place preview or the Align view: the floor opaque, the floor it
        is placed against faded over it (beside: the floor below faint, under it)."""
        f = self.cur
        self.error = ""
        if self.step == "place":
            f.ref = self._default_ref()
            dung = self.writer.load_dungeon()
            try:
                d = fp.preview(dung, f.written, f.ref, f.relation)
            except (ValueError, AttributeError) as e:
                self.error = str(e)
                self.place_preview = None
                self.align.clear()
                self._layout()
                return
            self.place_preview = d
            page = d.page_by_id(f.written)
        else:
            d, page = self.align_dung, self.align_page
        faded, faint = fp.faded_floor(d, page.id, f.relation)
        rows = ([(q, 70, COL_FAINT) for q in faint] + [(page, 255, COL_NEW)]
                + [(q, 130, COL_FADED) for q in faded])
        layers = []
        for p, alpha, col in rows:
            art = self.writer.page_art(p)
            if art is not None:
                layers.append(Layer(p.id, art[0], p.origin, art[1], art[2], alpha, col))
        self.align.set_layers(layers, self.map_area(), fit=fit)
        self._layout()

    def _place(self):
        """Next on Place: move the floor in the stack and save (D7, D18), then Align."""
        f = self.cur
        dung = self.writer.load_dungeon()
        try:
            fp.place(dung, f.written, f.ref, f.relation)
            dung.page_by_id(f.written).aligned = False     # until Align accepts (W7)
            self.writer.save_dungeon(dung)
        except (OSError, ValueError) as e:
            self.error = str(e)
            return
        self._goto("align")
        self._load_align()
        self._refresh_align()

    def _load_align(self):
        f = self.cur
        self.align_dung = self.writer.load_dungeon()
        self.align_page = self.align_dung.page_by_id(f.written)
        self.skip_origin = fp.default_origin(self.align_dung, f.written, f.ref, f.relation)
        self.mark_a = self.mark_b = None

    def nudge(self, dx: int, dy: int):
        """Move the floor a cell at a time (D19 step 2)."""
        o = self.align_page.origin
        o[0] += dx
        o[1] += dy

    def landmark(self, world):
        """A landmark click (D19 step 1), ``world`` in global cells: first a point on the
        new floor, then the same point on the faded floor, which moves the floor so the
        two meet. A third click starts a new pair."""
        p = self.align_page
        if self.mark_a is None or self.mark_b is not None:
            ly = next((ly for ly in self.align.layers if ly.page_id == p.id), None)
            if ly is not None:
                x, y, w, h = ly.world_rect(self.align._image(ly.image)[2])
                if not (x <= world[0] <= x + w and y <= world[1] <= y + h):
                    self.error = f"First click a point on {p.id} (outlined in gold)."
                    return
            self.error = ""
            self.mark_a = (world[0] - p.gx, world[1] - p.gy)
            self.mark_b = None
            return
        self.mark_b = tuple(world)
        p.origin[:] = fp.landmark_origin(p.origin, self.mark_a, world)

    def accept_align(self, origin=None):
        """Enter / Next: save the floor where it is (D19 step 2). ``origin`` overrides it
        (Skip)."""
        if origin is not None:
            self.align_page.origin[:] = list(origin)
        self.align_page.aligned = origin is None       # Skip is not an alignment (W7)
        try:
            self.writer.save_dungeon(self.align_dung)
        except OSError as e:
            self.error = str(e)
            return
        self._goto("more")

    def skip_align(self):
        """D19 step 3: the default corner, saved."""
        self.accept_align(self.skip_origin)

    def another_from_sheet(self):
        """Back to Crop on the same sheet, its grid kept (D10 step 5)."""
        self._goto("crop")
        self.cur = Floor(self.sheet)

    def another_image(self):
        """Back to Pick an image (D10 step 5)."""
        self._goto("source")
        self.cur = None
        self.sheet = None
        self._layout()

    # ── Layout, events, drawing ───────────────────────────────────────────

    def map_area(self) -> pygame.Rect:
        """The map view beside the panel: the canvas's area."""
        return pygame.Rect(0, 0, self.app._panel_rect().x, self.app.screen.get_height())

    def _layout(self):
        """Place this step's widgets and record their hit rects."""
        app = self.app
        panel = app._panel_rect()
        # The whole panel's width, so none of its buttons show (or take a click) beside it.
        self.rect = pygame.Rect(panel.x + 4, panel.y + 40, panel.w - 8, max(320, panel.h - 80))
        ix, iw = self.rect.x + self.PAD, self.rect.w - 2 * self.PAD
        y = self.rect.y + self.HDR_H + self.PAD
        rh = self.ROW_H - 4
        self._hit = []
        self._labels = []       # (text, (x, y)) drawn as field labels
        half = (iw - 6) // 2
        if self.step == "start":
            self._labels.append(("Campaign", (ix, y)))
            y += 22
            for key, label in self.choices:
                self._hit.append((pygame.Rect(ix, y, iw, rh), "choice", key))
                y += self.ROW_H
            if self.choice == NEW_CAMPAIGN:
                self.camp_input.rect = pygame.Rect(ix, y, iw, rh)
                y += self.ROW_H
            y += 6
            self._labels.append(("Dungeon name", (ix, y)))
            y += 22
            self.name_input.rect = pygame.Rect(ix, y, iw, rh)
            y += self.ROW_H + 6
            self._labels.append(("Start from", (ix, y)))
            y += 22
            for i, (val, _lbl) in enumerate(((PREMADE, "Premade maps"), (GENERATE, "Generate"))):
                self._hit.append((pygame.Rect(ix + i * (half + 6), y, half, rh), "start", val))
            y += self.ROW_H
        elif self.step == "source":
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "file"))
            y += self.ROW_H
            if self.library():
                self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "library"))
                y += self.ROW_H
            if self.sheets:
                y += 6
                self._labels.append(("Sheets picked so far", (ix, y)))
                y += 22
                for i, _s in enumerate(self.sheets):
                    self._hit.append((pygame.Rect(ix, y, iw, rh), "sheet", i))
                    y += self.ROW_H
        elif self.step == "grid":
            self._labels.append(("Squares inside the box", (ix, y)))
            y += 22
            for key, lbl in (("across", "Across"), ("down", "Down")):
                self._labels.append((lbl, (ix, y + 4)))
                bx = ix + 90
                self._hit.append((pygame.Rect(bx, y, 28, rh), "step", (key, -1)))
                self._hit.append((pygame.Rect(bx + 78, y, 28, rh), "step", (key, +1)))
                y += self.ROW_H
            y += 6
            self._labels.append(("One square is", (ix, y)))
            y += 22
            cw = (iw - 12) // 3
            for i, v in enumerate(self.FT_CHOICES + ("other",)):
                self._hit.append((pygame.Rect(ix + i * (cw + 6), y, cw, rh), "ft", v))
            y += self.ROW_H
            if self.ft_other:
                self.ft_input.rect = pygame.Rect(ix, y, cw, rh)
                y += self.ROW_H
        elif self.step == "crop":
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "whole"))
            y += self.ROW_H + 6
            self._labels.append(("Blank-outside brush", (ix, y)))
            y += 22
            cw = (iw - 12) // 3
            for i, v in enumerate((None, "paint", "erase")):
                self._hit.append((pygame.Rect(ix + i * (cw + 6), y, cw, rh), "brush", v))
            y += self.ROW_H
        elif self.step == "name":
            self._labels.append(("Floor name", (ix, y)))
            y += 22
            self.floor_input.rect = pygame.Rect(ix, y, iw, rh)
            y += self.ROW_H
        elif self.step == "place" and self.cur is not None:
            self._labels.append((f"Place {self.cur.written}", (ix, y)))
            y += 22
            cw = (iw - 12) // 3
            for i, v in enumerate(fp.RELATIONS):
                self._hit.append((pygame.Rect(ix + i * (cw + 6), y, cw, rh), "rel", v))
            y += self.ROW_H + 6
            self._labels.append(("Against", (ix, y)))
            y += 22
            self._refs = dict(self.place_refs())
            for pid in self._refs:
                self._hit.append((pygame.Rect(ix, y, iw, rh), "ref", pid))
                y += self.ROW_H
            if self.place_preview is not None:
                y += 6
                self._labels.append(("The stack, top first", (ix, y)))
                y += 22
                entry = self.place_preview.entry_page_id
                for z, ids in fp.stack(self.place_preview):
                    for n, i in enumerate(ids):
                        lead = f"  {z:+d}: " if n == 0 else "        "
                        tail = " ★" if i == entry else "  ← new" if i == self.cur.written else ""
                        self._labels.append((f"{lead}{i}{tail}", (ix, y)))
                        y += 22
        elif self.step == "align":
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "skip"))
            y += self.ROW_H
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "fit"))
            y += self.ROW_H + 6
            if self.align_page is not None:
                p = self.align_page
                self._labels.append((f"{p.id} at ({p.gx}, {p.gy}), floor {p.z:+d}", (ix, y)))
                y += 22
        elif self.step == "more":
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "same"))
            y += self.ROW_H
            self._hit.append((pygame.Rect(ix, y, iw, rh), "act", "another"))
            y += self.ROW_H + 6
            self._labels.append(("Floors", (ix, y)))
            y += 22
            for f in self.floors:
                self._labels.append(("  " + f.written, (ix, y)))
                y += 22
        self._body_bottom = y
        bw, bh = 84, self.BTN_H
        by = self.rect.bottom - self.PAD - bh
        self._hit.append((pygame.Rect(self.rect.x + self.PAD, by, bw, bh), "button", "back"))
        self._hit.append((pygame.Rect(self.rect.centerx - bw // 2, by, bw, bh), "button", "cancel"))
        self._hit.append((pygame.Rect(self.rect.right - self.PAD - bw, by, bw, bh), "button", "next"))
        if self.saved:
            self._hit.append((pygame.Rect(ix, by - bh - 8, iw, bh), "button", "discard"))
        if self.step in self.CANVAS_STEPS and self.sheet is not None:
            self.canvas.set_sheet(self.sheet.image, self.map_area())
        if self.step in self.ALIGN_STEPS:
            self.align.set_area(self.map_area())

    def button_rect(self, which) -> pygame.Rect | None:
        """The hit rect of a button (back / cancel / next / discard), a chip, or an
        action (file / library / whole / same / another), for tests and the driver."""
        return next((r for r, _k, v in self._hit if v == which), None)

    def _enabled(self, which: str) -> bool:
        if which == "back":
            # Once a floor is written the first screen's answers are fixed.
            return bool(self.history) and not (self.saved and self.history[-1][0] == "start")
        if which == "next":
            if self.step == "source":
                return self.sheet is not None
            if self.step == "grid":
                return self.sheet is not None and self.sheet.grid is not None
            if self.step == "crop":
                return self.cur is not None and self.cur.squares is not None
            if self.step == "place":
                return self.place_preview is not None
            return True
        return True

    def handle(self, event) -> bool:
        """True when the panel used the event. On the first two steps map-view events
        are left to the app; from Set Grid on, the map view is the sheet's canvas."""
        if not self.visible or not self.rect:
            return False
        inputs = self._inputs()
        on_canvas = self.step in self.CANVAS_STEPS and self.sheet is not None
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.cancel()
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.step == "grid" and self.ft_input.active:
                    self.ft_input.active = False
                    self._regrid()
                elif self._enabled("next"):
                    self.next()
                return True
            if event.key == pygame.K_TAB and inputs:
                cur = next((i for i, t in enumerate(inputs) if t.active), -1)
                for t in inputs:
                    t.active = False
                inputs[(cur + 1) % len(inputs)].active = True
                return True
            active = next((t for t in inputs if t.active), None)
            if active is not None:
                active.handle(event)
                if active is self.ft_input:
                    self._regrid()
                return True
            if on_canvas:
                return self._canvas_key(event)
            if self.step in self.ALIGN_STEPS:
                return self._align_key(event)
            return False               # arrows / +/- reach the map's pan and zoom
        if on_canvas and self._canvas_mouse(event):
            return True
        if self.step in self.ALIGN_STEPS and self._align_mouse(event):
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.rect.collidepoint(*event.pos):
                return False
            for t in inputs:
                t.handle(event)
            hit = next(((k, v) for r, k, v in self._hit if r.collidepoint(*event.pos)), None)
            if hit is None:
                return True
            self._click(*hit)
            return True
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and \
                self.rect.collidepoint(*event.pos):
            return True
        return False

    def _click(self, kind, val):
        if kind == "choice":
            self.choice = val
            if val == NEW_CAMPAIGN:
                self.name_input.active = False
                self.camp_input.active = True
            self._layout()
        elif kind == "start":
            self.start_from = val
        elif kind == "act":
            self.error = ""
            {"file": self.pick_file, "library": self.pick_library,
             "whole": self.whole_image, "same": self.another_from_sheet,
             "another": self.another_image, "skip": self.skip_align,
             "fit": self.align.fit}[val]()
        elif kind == "sheet":
            self._use_sheet(self.sheets[val])
        elif kind == "step" and not self._grid_locked():
            key, d = val
            setattr(self, key, max(1, min(999, getattr(self, key) + d)))
            self._regrid()
        elif kind == "ft" and not self._grid_locked():
            if val == "other":
                self.ft_other = True
                self.ft_input.active = True
            else:
                self.ft_other = False
                self.square_ft = val
            self._layout()
            self._regrid()
        elif kind == "brush":
            self.brush = val
        elif kind == "rel":
            self.set_place(relation=val)
        elif kind == "ref":
            self.set_place(ref=val)
        elif kind == "button" and self._enabled(val):
            {"back": self.back, "cancel": self.cancel, "next": self.next,
             "discard": self.ask_discard}[val]()

    def _canvas_key(self, event) -> bool:
        c = self.canvas
        pans = {pygame.K_UP: (0, 40), pygame.K_DOWN: (0, -40),
                pygame.K_LEFT: (40, 0), pygame.K_RIGHT: (-40, 0)}
        if event.key in pans:
            c.pan(*pans[event.key])
        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            c.zoom_at(1.25, c.area.center)
        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            c.zoom_at(0.8, c.area.center)
        elif event.key in (pygame.K_0, pygame.K_KP0):
            c.fit()
        else:
            return False
        return True

    def _align_key(self, event) -> bool:
        """Place / Align keys: on Align arrows move the floor a cell (D19); elsewhere
        they pan. + / − zoom, 0 fits."""
        a = self.align
        steps = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0),
                 pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}
        if event.key in steps:
            dx, dy = steps[event.key]
            if self.step == "align" and self.align_page is not None:
                self.nudge(dx, dy)
                self._layout()
            else:
                a.pan(-40 * dx, -40 * dy)
        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            a.zoom_at(1.25, a.area.center)
        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            a.zoom_at(0.8, a.area.center)
        elif event.key in (pygame.K_0, pygame.K_KP0):
            a.fit()
        else:
            return False
        return True

    def _align_mouse(self, event) -> bool:
        """Place / Align mouse: wheel zooms, right or middle drag pans; on Align a left
        click is a landmark (D19)."""
        a = self.align
        area = self.map_area()
        if hasattr(pygame, "MOUSEWHEEL") and event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if not area.collidepoint(pos):
                return False
            a.zoom_at(1.15 ** event.y, pos)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and area.collidepoint(*event.pos):
            if event.button in (4, 5):
                a.zoom_at(1.15 if event.button == 4 else 1 / 1.15, event.pos)
            elif event.button in (2, 3):
                self._drag = ("pan", event.pos, event.pos)
            elif event.button == 1 and self.step == "align" and self.align_page is not None:
                self.landmark(a.to_world(event.pos))
                self._layout()
            return True
        if event.type == pygame.MOUSEMOTION and self._drag is not None:
            _kind, start, last = self._drag
            a.pan(event.pos[0] - last[0], event.pos[1] - last[1])
            self._drag = ("pan", start, event.pos)
            return True
        if event.type == pygame.MOUSEBUTTONUP and (self._drag is not None
                                                  or area.collidepoint(*event.pos)):
            self._drag = None
            return True
        return False

    def _canvas_mouse(self, event) -> bool:
        """The canvas's mouse: wheel zooms, right or middle drag pans; a left drag sets
        the grid (Set Grid), the crop or the brush (Crop). True when used."""
        c = self.canvas
        area = self.map_area()
        if hasattr(pygame, "MOUSEWHEEL") and event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if not area.collidepoint(pos):
                return False
            c.zoom_at(1.15 ** event.y, pos)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and area.collidepoint(*event.pos):
            if event.button in (4, 5):
                c.zoom_at(1.15 if event.button == 4 else 1 / 1.15, event.pos)
            elif event.button in (2, 3):
                self._drag = ("pan", event.pos, event.pos)
            elif event.button == 1:
                pt = c.to_sheet(event.pos)
                if self.step == "grid" and not self._grid_locked():
                    self._drag = ("box", pt, pt)
                elif self.step == "crop" and self.brush is not None:
                    self._drag = ("brush", pt, pt)
                    self.brush_at(pt)
                elif self.step == "crop":
                    self._drag = ("box", pt, pt)
            return True
        if event.type == pygame.MOUSEMOTION and self._drag is not None:
            kind, start, last = self._drag
            if kind == "pan":
                c.pan(event.pos[0] - last[0], event.pos[1] - last[1])
                self._drag = ("pan", start, event.pos)
            else:
                pt = c.to_sheet(event.pos)
                self._drag = (kind, start, pt)
                if kind == "brush":
                    self.brush_at(pt)
            return True
        if event.type == pygame.MOUSEBUTTONUP and self._drag is not None:
            kind, start, _last = self._drag
            self._drag = None
            if kind == "box":
                end = c.to_sheet(event.pos)
                if self.step == "grid":
                    self.set_grid_box(start, end)
                else:
                    self.set_crop(start, end)
            return True
        return False

    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        self._frames_since_show += 1
        if self.step in self.CANVAS_STEPS and self.sheet is not None:
            self._draw_canvas(surf)
        elif self.step in self.ALIGN_STEPS:
            self.align.draw(surf, marks=self._marks(), font=self.font_sm)
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)
        hdr = f"New Dungeon — {self.TITLES.get(self.step, self.step)}"
        surf.blit(self.font_md.render(hdr, True, (220, 220, 235)),
                  (self.rect.x + self.PAD, self.rect.y + 7))
        lab = (185, 185, 200)
        for text, pos in self._labels:
            surf.blit(self.font_md.render(text, True, lab), pos)
        labels = dict(self.choices)
        acts = {"file": "From a file…", "library": "From the campaign library…",
                "whole": "Whole image", "same": "Another floor from this sheet",
                "another": "Another image", "skip": "Skip (default corner)",
                "fit": "Fit the view (0)"}
        locked = self._grid_locked()
        for r, kind, val in self._hit:
            if kind == "choice":
                self._chip(surf, r, labels[val], self.choice == val)
            elif kind == "start":
                self._chip(surf, r, "Premade maps" if val == PREMADE else "Generate",
                           self.start_from == val)
            elif kind == "act":
                self._chip(surf, r, acts[val], False)
            elif kind == "sheet":
                s = self.sheets[val]
                self._chip(surf, r, s.label, s is self.sheet)
            elif kind == "step":
                self._chip(surf, r, "−" if val[1] < 0 else "+", False, dim=locked)
                if val[1] > 0:
                    n = str(getattr(self, val[0]))
                    t = self.font_md.render(n, True, (235, 235, 245))
                    surf.blit(t, t.get_rect(center=(r.x - 25, r.centery)))
            elif kind == "ft":
                on = (self.ft_other if val == "other"
                      else not self.ft_other and self.square_ft == val)
                self._chip(surf, r, "Other" if val == "other" else f"{val} ft", on, dim=locked)
            elif kind == "brush":
                self._chip(surf, r, {None: "Off", "paint": "Paint", "erase": "Erase"}[val],
                           self.brush == val)
            elif kind == "rel":
                self._chip(surf, r, val.capitalize(), self.cur.relation == val)
            elif kind == "ref":
                z = self._refs.get(val, 0)
                self._chip(surf, r, f"{val}  (floor {z:+d})", self.cur.ref == val)
        for t in self._inputs():
            t.draw(surf)
        y = self._body_bottom + 8
        for line in self._hint_lines():
            for part in _wrap_words(line, self.font_sm, self.rect.w - 2 * self.PAD):
                surf.blit(self.font_sm.render(part, True, (170, 170, 185)),
                          (self.rect.x + self.PAD, y))
                y += self.font_sm.get_linesize()
            y += 4
        if self.error:
            y += 6
            for line in _wrap_words(self.error, self.font_sm, self.rect.w - 2 * self.PAD):
                surf.blit(self.font_sm.render(line, True, (235, 120, 110)),
                          (self.rect.x + self.PAD, y))
                y += self.font_sm.get_linesize()
        colors = {"back": (55, 55, 75), "cancel": (90, 45, 45), "next": (35, 90, 45),
                  "discard": (110, 40, 40)}
        names = {"back": "Back", "cancel": "Cancel",
                 "next": "Finish" if self.step == "more" else "Next",
                 "discard": "Discard dungeon"}
        for r, kind, val in self._hit:
            if kind != "button":
                continue
            on = self._enabled(val)
            pygame.draw.rect(surf, colors[val] if on else (45, 45, 55), r, border_radius=6)
            t = self.font_md.render(names[val], True, (225, 225, 225) if on else (120, 120, 130))
            surf.blit(t, t.get_rect(center=r.center))

    def _hint_lines(self) -> list[str]:
        s = self.step
        if s == "start":
            return ["Next opens the generator's settings; the dungeon is built on the blank map."
                    if self.start_from == GENERATE else
                    "Next picks the first image: a sheet of several levels, or one level."]
        if s == "source":
            out = ["A sheet holding several levels, or one level's map."]
            if self.sheet is not None:
                out.append(f"Picked: {self.sheet.label}. Next sets its grid.")
            return out
        g = self.sheet.grid if self.sheet else None
        if s == "grid":
            if self._grid_locked():
                return [f"{self.sheet.label} has its own grid, which other dungeons may "
                        f"use, so it is kept: one square is {g.square_ft} ft, "
                        f"{g.square_px:.2f} px.", "Next crops the first floor."]
            out = ["Drag a box over whole squares on the map, its corner on a grid line, "
                   "and say how many squares it covers. The more squares, the more exact. "
                   "Wheel zooms; right-drag pans."]
            if g is not None:
                per = g.per_side
                cells = f" → {per}×{per} cells" if per > 1 else ""
                out.append(f"One square: {g.square_px:.2f} px ({g.square_ft} ft{cells}). "
                           "Check the blue lines against the drawn ones.")
            return out
        if s == "crop":
            out = ["Drag a rectangle around one level; it snaps to the grid. "
                   "Paint blanks stray art from a neighbouring level (black squares)."]
            if self.cur is not None and self.cur.squares is not None and g is not None:
                p = wf.plan_crop(g, self.cur.squares)
                k0, j0, k1, j1 = self.cur.squares
                w, h = p.size
                out.append(f"{k1 - k0}×{j1 - j0} squares → {p.cols}×{p.rows} cells, "
                           f"floor image {w}×{h} px" + (" (shrunk)" if p.shrunk else " (enlarged)" if p.enlarged
                                                     else "") + ".")
            return out
        if s == "name":
            out = ["Next writes this floor; from then on the dungeon opens."]
            if self.cur is not None and self.cur.written:
                out = [f"Written as {self.cur.written}. Next writes it again (a new name "
                       "renames it)."]
            if self.target and self.target.campaign is not None:
                out.append("The name is also its folder in the campaign's maps/.")
            return out
        if s == "place":
            return ["Pick the floor this one sits above, below or beside. Nobody types a "
                    "floor number: the stack shows where it goes, and the entry (★) stays "
                    "floor 0. Next saves it and goes on to align it."]
        if s == "align" and self.align_page is not None:
            p = self.align_page
            faded = ("the other maps of its floor" if self.cur.relation == fp.BESIDE
                     else "the floor " + ("below" if self.cur.relation == fp.ABOVE else "above"))
            out = [f"Click a landmark on {p.id} (gold), then the same point on {faded} "
                   "(blue); the floor moves so they meet. Arrows move it a cell; Enter "
                   "accepts. Right-drag pans, wheel zooms."]
            if self.mark_a is not None and self.mark_b is None:
                out.append("Now click the same point on the faded floor.")
            if self.skip_origin is not None:
                out.append(f"Skip puts it at ({self.skip_origin[0]}, {self.skip_origin[1]}).")
            return out
        if s == "more":
            return ["Finish opens the dungeon on its entry floor."]
        return []

    def _marks(self):
        p = self.align_page
        if self.step != "align" or p is None:
            return ()
        out = []
        if self.mark_a is not None:
            out.append(((p.gx + self.mark_a[0], p.gy + self.mark_a[1]), COL_MARK_A))
        if self.mark_b is not None:
            out.append((self.mark_b, COL_MARK_B))
        return out

    def _draw_canvas(self, surf):
        c = self.canvas
        c.set_sheet(self.sheet.image, self.map_area())
        g = self.sheet.grid
        drag = None
        if self._drag is not None and self._drag[0] == "box":
            drag = (self._drag[1], self._drag[2])
        squares = self.cur.squares if (self.cur is not None and self.step != "grid") else None
        others = [(f.squares, f.written) for f in self.floors
                  if f.sheet is self.sheet and f is not self.cur and f.squares]
        blanks = self.cur.blanks if (self.cur is not None and self.step != "grid") else ()
        c.draw(surf, grid=g, squares=squares, others=others if g else (), blanks=blanks,
               drag_box=drag, font=self.font_sm)

    def _chip(self, surf, r, text, on, dim=False):
        pygame.draw.rect(surf, (70, 60, 130) if on else (45, 45, 62), r, border_radius=4)
        pygame.draw.rect(surf, (150, 130, 220) if on else (80, 80, 100), r, 1, border_radius=4)
        t = self.font_md.render(text, True, (140, 140, 150) if dim else (235, 235, 245))
        surf.blit(t, t.get_rect(midleft=(r.x + 8, r.centery)))
