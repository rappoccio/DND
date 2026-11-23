"""The New Dungeon wizard's premade path without the panel (DUNGEON_WIZARD_PLAN W5,
D10–D16): a source sheet's grid, grid-snapped crops, and writing each floor.

Plain functions and two small classes, so the suites drive them directly:

* ``SheetGrid`` is a sheet's drawn grid: the exact square size in sheet pixels (a float,
  so a big sheet doesn't drift), the corner of one square, and the square's size in feet.
  ``measure_grid`` makes one from a box dragged over ``across`` × ``down`` squares (D13).
* A crop is a rectangle of whole drawn squares, ``(k0, j0, k1, j1)`` in square indices
  (D14). ``snap_squares`` turns a drag into one; ``whole_image`` is every whole square.
* ``plan_crop`` sizes the floor (D15): the sheet's resolution, shrunk when the longest
  side is over ``MAX_SIDE``, and always a whole number of pixels per 5-ft cell, so the
  floor's manual grid sits exactly on its drawn lines with its anchor at (0, 0).
* ``FloorWriter`` writes a dungeon's sheets and floors, in a campaign or loose (D9):

    campaign   <campaign>/maps/<sheet>/<sheet>.<ext> + map.json   source (D12)
               <campaign>/maps/<floor>/<floor>.png  + map.json   grid + crop
               <campaign>/<dungeon>/dungeon.json, runs/main/run.json
    loose      maps/<dungeon>/<sheet>.<ext> + <sheet>_terrain.json, in ``sources``
               maps/<dungeon>/<floor>.png + _terrain.json + _agents.json
               maps/<dungeon>/<dungeon>.dungeon.json

  A sheet is copied in when its first floor is written, so a wizard cancelled before
  any floor leaves nothing behind. Every write of a floor is a whole, openable dungeon.
"""

from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass, field

from PIL import Image

import dungeon as dg
import run_state as rs
import save_layout as sl
from atomic_io import atomic_write_json
from net.roster import SessionRoster

MAX_SIDE = 2048          # D15: a floor's longest side, in pixels
_EPS = 1e-6


# ── A sheet's grid (D13) ────────────────────────────────────────────────────

@dataclass(frozen=True)
class SheetGrid:
    square_px: float                    # one drawn square, in sheet pixels
    anchor: tuple[float, float]         # the corner of one drawn square
    square_ft: int = 5

    @property
    def per_side(self) -> int:
        """5-ft engine cells per side of a drawn square."""
        return max(1, int(self.square_ft) // 5)

    def line(self, k: float, axis: int) -> float:
        """Sheet coordinate of grid line ``k`` on ``axis`` (0 = x, 1 = y)."""
        return self.anchor[axis] + k * self.square_px

    def index_range(self, size: int, axis: int) -> tuple[int, int]:
        """The first and last grid line inside ``[0, size]`` on ``axis``."""
        a, s = self.anchor[axis], self.square_px
        return math.ceil((0 - a) / s - _EPS), math.floor((size - a) / s + _EPS)

    def nearest(self, v: float, axis: int, size: int) -> int:
        lo, hi = self.index_range(size, axis)
        return max(lo, min(hi, round((v - self.anchor[axis]) / self.square_px)))

    def manual_grid(self) -> dict:
        """The engine's whole-pixel grid for the sheet itself (``manual_grid``)."""
        return {"cell_px": max(1, round(self.square_px / self.per_side)),
                "anchor": [round(self.anchor[0]), round(self.anchor[1])],
                "square_ft": int(self.square_ft)}

    def source(self) -> dg.SourceSheet:
        return dg.SourceSheet(square_ft=int(self.square_ft), square_px=float(self.square_px))

    @classmethod
    def from_doc(cls, doc: dict | None) -> "SheetGrid | None":
        """A sheet's grid from its design document: ``manual_grid``, made exact by the
        source block's ``square_px`` when it has one. None without a manual grid."""
        mg = (doc or {}).get("manual_grid")
        if not isinstance(mg, dict):
            return None
        try:
            cell = int(mg["cell_px"])
            ax, ay = (float(v) for v in mg.get("anchor", [0, 0])[:2])
            src = dg.read_source(doc)
            ft = int(mg.get("square_ft") or (src.square_ft if src else 5))
        except (KeyError, TypeError, ValueError):
            return None
        if cell <= 0 or ft <= 0:
            return None
        sq = src.square_px if src is not None and src.square_px else cell * max(1, ft // 5)
        return cls(float(sq), (ax, ay), ft)


def measure_grid(box, across: int, down: int, square_ft: int) -> SheetGrid:
    """The grid from a box ``(x, y, w, h)`` in sheet pixels dragged over ``across`` ×
    ``down`` drawn squares, its corner on a grid line. ``ValueError`` says what's wrong."""
    x, y, w, h = box
    if across < 1 or down < 1:
        raise ValueError("A box covers at least one square each way.")
    if square_ft < 5 or square_ft % 5:
        raise ValueError("A square is 5 ft, or a multiple of 5 ft.")
    sq = (w / across + h / down) / 2.0
    if sq / max(1, square_ft // 5) < 2:
        raise ValueError("That box is too small for so many squares.")
    return SheetGrid(sq, (float(x), float(y)), int(square_ft))


# ── Crops (D14, D15) ────────────────────────────────────────────────────────

Squares = tuple[int, int, int, int]       # (k0, j0, k1, j1): grid lines, k1 > k0, j1 > j0


def snap_squares(grid: SheetGrid, size, p0, p1) -> Squares | None:
    """A drag from ``p0`` to ``p1`` (sheet pixels) snapped to the nearest grid lines
    inside the sheet; None when it covers no whole square."""
    k0, k1 = sorted((grid.nearest(p0[0], 0, size[0]), grid.nearest(p1[0], 0, size[0])))
    j0, j1 = sorted((grid.nearest(p0[1], 1, size[1]), grid.nearest(p1[1], 1, size[1])))
    if k1 <= k0 or j1 <= j0:
        return None
    return (k0, j0, k1, j1)


def whole_image(grid: SheetGrid, size) -> Squares | None:
    """Every whole drawn square of the sheet."""
    k0, k1 = grid.index_range(size[0], 0)
    j0, j1 = grid.index_range(size[1], 1)
    return (k0, j0, k1, j1) if k1 > k0 and j1 > j0 else None


@dataclass(frozen=True)
class CropPlan:
    squares: Squares
    box: tuple[float, float, float, float]     # (x0, y0, x1, y1), exact sheet pixels
    cols: int                                  # the floor in 5-ft cells
    rows: int
    cell_px: int                               # floor pixels per 5-ft cell
    scale: float                               # floor pixels per sheet pixel
    shrunk: bool

    @property
    def size(self) -> tuple[int, int]:
        return (self.cols * self.cell_px, self.rows * self.cell_px)

    def crop(self, sheet: str) -> dg.Crop:
        x0, y0, x1, y1 = self.box
        rect = (round(x0), round(y0), max(1, round(x1 - x0)), max(1, round(y1 - y0)))
        return dg.Crop(sheet=sheet, rect=rect, scale=self.scale)

    def manual_grid(self, square_ft: int) -> dict:
        return {"cell_px": self.cell_px, "anchor": [0, 0], "square_ft": int(square_ft)}


def plan_crop(grid: SheetGrid, squares: Squares, max_side: int = MAX_SIDE) -> CropPlan:
    """How a crop of ``squares`` becomes a floor (D15): kept at the sheet's resolution
    unless its longest side is over ``max_side``, then shrunk; either way rounded to a
    whole number of pixels per 5-ft cell."""
    k0, j0, k1, j1 = squares
    per = grid.per_side
    cols, rows = (k1 - k0) * per, (j1 - j0) * per
    natural = grid.square_px / per                       # sheet px per 5-ft cell
    cell = max(1, round(natural))
    shrunk = max(cols, rows) * cell > max_side
    if shrunk:
        cell = max(1, max_side // max(cols, rows))
    box = (grid.line(k0, 0), grid.line(j0, 1), grid.line(k1, 0), grid.line(j1, 1))
    return CropPlan(squares, box, cols, rows, cell, cell / natural, shrunk)


def render_floor(image_path: str, plan: CropPlan, grid: SheetGrid, blanks=()) -> Image.Image:
    """The floor's image: the crop box resampled to the plan's size, with every blanked
    drawn square (``(k, j)`` sheet square indices, the blank-outside brush) painted black."""
    with Image.open(image_path) as src:
        src.load()
        mode = "RGBA" if src.mode in ("RGBA", "LA", "P") else "RGB"
        w, h = src.size
        x0, y0, x1, y1 = plan.box
        box = (max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1))
        img = src.convert(mode).resize(plan.size, Image.LANCZOS, box=box)
    k0, j0, k1, j1 = plan.squares
    side = plan.cell_px * grid.per_side
    black = (0, 0, 0, 255) if img.mode == "RGBA" else (0, 0, 0)
    for k, j in blanks:
        if k0 <= k < k1 and j0 <= j < j1:
            x, y = (k - k0) * side, (j - j0) * side
            img.paste(black, (x, y, x + side, y + side))
    return img


def default_floor_name(dungeon_slug: str, n: int) -> str:
    """D16: ``<dungeon>-floor-<N>``."""
    return f"{dungeon_slug}-floor-{n}"


def floor_doc(plan: CropPlan, grid: SheetGrid, sheet_ref: str) -> dict:
    """A new floor's design document: its grid, and where it was cut from."""
    return dg.set_meta({"regions": [], "walls_enabled": False,
                        "manual_grid": plan.manual_grid(grid.square_ft)},
                       crop=plan.crop(sheet_ref))


# ── Sheets, as the wizard holds them ────────────────────────────────────────

@dataclass
class Sheet:
    """A picked image. ``name`` is its library map name (campaign) or file stem (loose),
    settled when it is placed; until then ``image`` is the picked file."""
    image: str
    size: tuple[int, int]
    grid: SheetGrid | None = None
    name: str | None = None
    library: bool = False          # an existing campaign library map: in place already
    grid_locked: bool = False      # that map's own grid, which other dungeons may use
    placed: bool = False

    @property
    def label(self) -> str:
        return self.name or os.path.basename(self.image)


def image_size(path: str) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def sheet_from_file(path: str) -> Sheet:
    return Sheet(image=os.path.abspath(path), size=image_size(path))


def sheet_from_library(camp: sl.Campaign, map_name: str) -> Sheet:
    """A campaign library map as a sheet. A map with a grid of its own keeps it: other
    dungeons may read that ``map.json``, so the wizard never re-grids it."""
    folder = camp.library_map_dir(map_name)
    image = sl.find_image(folder, map_name)
    if image is None:
        raise ValueError(f"maps/{map_name} has no image")
    grid = SheetGrid.from_doc(camp.library_map_doc(map_name))
    return Sheet(image=image, size=image_size(image), grid=grid, name=map_name,
                 library=True, grid_locked=grid is not None, placed=False)


# ── Writing (D7, D9, D12) ───────────────────────────────────────────────────

@dataclass
class FloorWriter:
    """Writes one dungeon's sheets and floors. ``target`` is the wizard's Target
    (``campaign``, ``campaign_name``, ``name``, ``slug``, ``root()``, ``manifest_path()``).
    ``created`` lists the campaign library folders this run made, which Discard archives
    with the dungeon."""
    target: object
    created: list[str] = field(default_factory=list)

    @property
    def loose(self) -> bool:
        return self.target.campaign is None

    # ── campaign plumbing ──
    def campaign(self, make: bool = False) -> sl.Campaign | None:
        root = self.target.campaign
        if root is None:
            return None
        if os.path.isfile(os.path.join(root, sl.CAMPAIGN_FILE)):
            return sl.Campaign(root)
        if not make:
            return None
        return sl.Campaign.create(root, self.target.campaign_name)

    def layout(self, make: bool = False) -> sl.DungeonLayout | None:
        camp = self.campaign(make)
        return camp.dungeon(self.target.slug) if camp is not None else None

    # ── names ──
    def floor_name_problem(self, name: str, own: str | None = None) -> str | None:
        """Why ``name`` can't name a new floor, else None. ``own`` is the floor's current
        name when it is being renamed or rewritten (its own files don't count)."""
        try:
            sl._check_name(name, "floor")
        except ValueError as e:
            return str(e)
        if name == own:
            return None
        if self.loose:
            root = self.target.root()
            for fn in (name + ".png", name + "_terrain.json", name + "_agents.json"):
                if os.path.exists(os.path.join(root, fn)):
                    return f"maps/{self.target.slug}/ already has {fn}."
            return None
        camp = self.campaign()
        if camp is not None and os.path.exists(camp.library_map_dir(name)):
            return f"The campaign's library already has a map '{name}'."
        return None

    def _sheet_name(self, sheet: Sheet) -> str:
        stem = sl.slugify(os.path.splitext(os.path.basename(sheet.image))[0])
        if self.loose:
            root = self.target.root()
            taken = os.listdir(root) if os.path.isdir(root) else []
            taken = {os.path.splitext(f)[0] for f in taken} | \
                {f[:-len("_terrain.json")] for f in taken if f.endswith("_terrain.json")}
            return sl.unique_slug(stem, taken)
        return sl.unique_slug(stem, self.campaign(make=True).list_library_maps())

    def sheet_ref(self, sheet: Sheet) -> str:
        """What a floor's ``crop.sheet`` names: the library map (campaign), the image's
        file name beside the manifest (loose)."""
        if self.loose:
            return sheet.name + os.path.splitext(sheet.image)[1].lower()
        return sheet.name

    # ── sheets ──
    def place_sheet(self, sheet: Sheet) -> None:
        """Copy a picked sheet into the dungeon (or mark a library map) and record its
        grid as a source (D12). Done once, when its first floor is written; a later call
        only rewrites the grid, unless the grid is the library map's own."""
        if sheet.grid is None:
            raise ValueError("Set the sheet's grid first.")
        if self.loose:
            root = self.target.root()
            os.makedirs(root, exist_ok=True)
            if not sheet.placed:
                sheet.name = self._sheet_name(sheet)
                dst = os.path.join(root, sheet.name + os.path.splitext(sheet.image)[1].lower())
                shutil.copy2(sheet.image, dst)
                sheet.image, sheet.placed = dst, True
            doc_path = os.path.join(root, sheet.name + "_terrain.json")
        else:
            camp = self.campaign(make=True)
            if not sheet.placed and not sheet.library:
                sheet.name = self._sheet_name(sheet)
                folder = camp.library_map_dir(sheet.name)
                os.makedirs(folder)
                self.created.append(folder)
                dst = os.path.join(folder, sheet.name + os.path.splitext(sheet.image)[1].lower())
                shutil.copy2(sheet.image, dst)
                sheet.image = dst
            sheet.placed = True
            doc_path = os.path.join(camp.library_map_dir(sheet.name), sl.MAP_FILE)
        doc = _read(doc_path) or {}
        if sheet.grid_locked:       # the map's own grid: only marked as a source
            source = dg.read_source(doc) or dg.SourceSheet(square_ft=sheet.grid.square_ft)
        else:
            doc = dict(doc, manual_grid=sheet.grid.manual_grid())
            source = sheet.grid.source()
        atomic_write_json(doc_path, dg.set_meta(doc, source=source))

    # ── floors ──
    def write_floor(self, name: str, sheet: Sheet, squares: Squares, blanks=(), *,
                    origin=None, old_name: str | None = None) -> dg.MapPage:
        """Write a floor cut from ``sheet``, and the dungeon around it: its image, its
        design document (grid + crop), its page in the manifest, its section of the run.
        Writing a floor that exists (``old_name``, the name it has now) overwrites its image
        and moves it to ``name`` when that changed; its place in the dungeon is kept.
        A new floor goes at ``origin`` ([gx, gy, z]). Returns its page."""
        problem = self.floor_name_problem(name, own=old_name)
        if problem:
            raise ValueError(problem)
        self.place_sheet(sheet)
        if old_name is not None and old_name != name:
            self.rename_floor(old_name, name)
        plan = plan_crop(sheet.grid, squares)
        img = render_floor(sheet.image, plan, sheet.grid, blanks)
        doc = floor_doc(plan, sheet.grid, self.sheet_ref(sheet))
        if self.loose:
            return self._write_loose(name, img, doc, plan, origin, sheet)
        return self._write_campaign(name, img, doc, plan, origin)

    def _write_campaign(self, name, img, doc, plan, origin) -> dg.MapPage:
        camp = self.campaign(make=True)
        layout = camp.dungeon(self.target.slug)
        folder = camp.library_map_dir(name)
        if not os.path.isdir(folder):
            os.makedirs(folder)
            self.created.append(folder)
        img.save(os.path.join(folder, name + ".png"))
        atomic_write_json(os.path.join(folder, sl.MAP_FILE), doc)
        stale = layout.write_path(name, sl.MAP_FILE)     # a re-crop replaces the design
        if os.path.isfile(stale):
            os.replace(stale, stale + ".pre-recrop")
        dung = _load_dungeon(layout.manifest_path) or \
            dg.Dungeon(pages=[], version=dg.DUNGEON_LAYOUT_VERSION)
        page = _put_page(dung, name, plan, origin, png="", agents="")
        run_path = layout.run_path()
        run = rs.load_run(run_path) if os.path.isfile(run_path) else rs.new_run(name)
        rs.map_section(run, name)["state"] = rs.split_terrain(doc)[2]
        if not run.get("current_map"):
            run["current_map"] = dung.entry_page_id
        os.makedirs(os.path.dirname(run_path), exist_ok=True)
        if not os.path.isfile(camp.session_path):
            SessionRoster().save(camp.session_path)
        rs.save_run(run_path, run)
        dung.save(layout.manifest_path)                  # last: the dungeon is whole
        return page

    def _write_loose(self, name, img, doc, plan, origin, sheet) -> dg.MapPage:
        root = self.target.root()
        os.makedirs(root, exist_ok=True)
        img.save(os.path.join(root, name + ".png"))
        atomic_write_json(os.path.join(root, name + "_terrain.json"), doc)
        agents = os.path.join(root, name + "_agents.json")
        if not os.path.exists(agents):
            atomic_write_json(agents, {"agents": [], "map_items": []})
        manifest = self.target.manifest_path()
        dung = _load_dungeon(manifest) or dg.Dungeon(pages=[])
        page = _put_page(dung, name, plan, origin, png=name + ".png",
                         agents=name + "_agents.json")
        ref = self.sheet_ref(sheet)
        if ref not in {e["png"] for e in dung.sources}:
            dung.sources.append({"png": ref, "terrain": sheet.name + "_terrain.json"})
        dung.save(manifest)
        return page

    def rename_floor(self, old: str, new: str) -> None:
        """Move a written floor's files to a new name, and its page, entry and run
        section with them."""
        if self.loose:
            root = self.target.root()
            for suffix in (".png", "_terrain.json", "_agents.json"):
                src = os.path.join(root, old + suffix)
                if os.path.exists(src):
                    os.replace(src, os.path.join(root, new + suffix))
            manifest = self.target.manifest_path()
            dung = _load_dungeon(manifest)
            if dung is None:
                return
            p = dung.page_by_id(old)
            if p is not None:
                p.id, p.png, p.encounter_base = new, new + ".png", new + "_agents.json"
            if dung.entry_page_id == old:
                dung.entry_page_id = new
            dung.save(manifest)
            return
        camp = self.campaign()
        layout = camp.dungeon(self.target.slug)
        lib_old, lib_new = camp.library_map_dir(old), camp.library_map_dir(new)
        if os.path.isdir(lib_old):
            os.rename(lib_old, lib_new)
            for f in os.listdir(lib_new):
                stem, ext = os.path.splitext(f)
                if stem == old:
                    os.rename(os.path.join(lib_new, f), os.path.join(lib_new, new + ext))
            self.created = [lib_new if c == lib_old else c for c in self.created]
        if os.path.isdir(layout.map_dir(old)):
            os.rename(layout.map_dir(old), layout.map_dir(new))
        dung = _load_dungeon(layout.manifest_path)
        if dung is not None:
            p = dung.page_by_id(old)
            if p is not None:
                p.id = new
            if dung.entry_page_id == old:
                dung.entry_page_id = new
            dung.save(layout.manifest_path)
        run_path = layout.run_path()
        if os.path.isfile(run_path):
            run = rs.load_run(run_path)
            maps = run.get("maps") or {}
            if old in maps:
                maps[new] = maps.pop(old)
            if run.get("current_map") == old:
                run["current_map"] = new
            rs.save_run(run_path, run)


def _read(path: str) -> dict | None:
    return sl._read_doc(path)


def _load_dungeon(path: str) -> dg.Dungeon | None:
    return dg.Dungeon.load(path) if os.path.isfile(path) else None


def _put_page(dung: dg.Dungeon, name: str, plan: CropPlan, origin, *, png: str,
              agents: str) -> dg.MapPage:
    """The floor's page, added (at ``origin``) or updated in place (its origin kept)."""
    page = dung.page_by_id(name)
    if page is None:
        page = dg.MapPage(id=name, png=png, encounter_base=agents,
                          origin=[int(v) for v in (origin or [0, 0, 0])])
        dung.add_page(page)
    page.cols, page.rows = plan.cols, plan.rows
    return page


def next_floor_origin(pages: list[dg.MapPage]) -> list[int]:
    """Where a floor goes until placement and alignment arrive (W6): one floor above the
    highest, at the same corner as the floor written last (D19's Skip)."""
    if not pages:
        return [0, 0, 0]
    last = pages[-1]
    return [last.gx, last.gy, max(p.z for p in pages) + 1]
