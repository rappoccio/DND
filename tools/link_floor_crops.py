#!/usr/bin/env python3
"""Link a campaign dungeon's existing floors to the sheets they were cut from.

W2 of plans/DUNGEON_WIZARD_PLAN.md (D24, "link, don't re-crop"). Floor images are never
touched. For every floor of the dungeon the tool finds where its art sits on one of the
given source sheets, searching over scale (the floors were enlarged or shrunk when they
were cut), and records the result as the floor's ``crop`` block. A floor that matches no
sheet is marked as its own source. The sheets themselves are marked as sources in the
campaign library, with their grid when the floors' grid maps to whole pixels on the sheet.

Without ``--apply`` nothing in the campaign is written: the tool prints rect and scale per
floor and writes overlays to ``--out`` for checking by eye.

  * ``<floor>_match.png``: the floor in red over the matched sheet region in cyan. Where
    they line up the picture is grey; any misalignment shows as coloured fringes.
  * ``<sheet>_rects.png``: the sheet with each matched floor's rectangle drawn on it.

With ``--apply`` it writes the blocks, backing up every file it changes to
``<file>.pre-link-crops`` (once; an existing backup is kept). Run it in the container
(numpy, scipy and PIL), with the game closed.

    python3 tools/link_floor_crops.py "encounters/Curse of Strahd/castle-ravenloft" \\
        --sheet spires-of-ravenloft --out /tmp/links
    python3 tools/link_floor_crops.py "encounters/Curse of Strahd/argynvostholt" \\
        --sheet "maps/map-07.01-argynvostholt-lower-player.jpg=argynvostholt-lower" \\
        --sheet "maps/map-07.02-argynvolstholt-upper-player.jpg=argynvostholt-upper" \\
        --out /tmp/links [--apply]

A ``--sheet`` is a library map name, or ``<image path>=<name>`` for an image outside the
library (relative paths are taken from the campaign root). ``--apply`` copies such an
image into ``maps/<name>/``; the original stays where it is.
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, optimize
from scipy.signal import fftconvolve

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import dungeon as dg  # noqa: E402
import save_layout as sl  # noqa: E402
from atomic_io import atomic_write_json  # noqa: E402

BACKUP_SUFFIX = ".pre-link-crops"
MIN_SCORE = 0.9          # NCC below this is "no match": the floor is its own source.
                         # Real crops score 0.95+; a floor pieced together from two
                         # places on a sheet scores ~0.7 and must not become one rect.
COARSE_SIDE = 640        # sheet's longest side, in pixels, for the coarse scale sweep
MEDIUM_SIDE = 1600       # ... for the scale refinement
SCALE_RANGE = (0.08, 8.0)
GRID_TOLERANCE = 0.02    # a sheet grid is written only when its cell is this close to whole


# ── Images ───────────────────────────────────────────────────────────────────

def load_gray(path: str) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=np.float32)


def content_mask(path: str) -> np.ndarray:
    """True where the image holds art, False on a flat padding border.

    Some floors were pasted onto a larger flat canvas (Castle Ravenloft's are 1216×992).
    The padding is the colour of the corners, connected to the image edge; it has no
    counterpart on the sheet, so it is left out of the match."""
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.int16)
    h, w, _ = rgb.shape
    corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    if np.abs(corners - corners[0]).max() > 3:
        return np.ones((h, w), bool)
    flat = np.abs(rgb - corners[0]).max(axis=2) <= 3
    labels, _ = ndimage.label(flat)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    pad = np.isin(labels, edge[edge > 0])
    # Ignore a thin padding border: an all-art image whose corners agree by chance.
    if pad.mean() < 0.02:
        return np.ones((h, w), bool)
    return ~pad


def resize(a: np.ndarray, size: tuple[int, int], box=None) -> np.ndarray:
    """``a`` (float or bool) resampled to ``size`` = (w, h), from ``box`` in its pixels."""
    if a.dtype == bool:
        im = Image.fromarray(a.astype(np.uint8) * 255)
        return np.asarray(im.resize(size, Image.NEAREST, box=box)) > 127
    return np.asarray(Image.fromarray(a).resize(size, Image.BILINEAR, box=box),
                      dtype=np.float32)


# ── Matching ─────────────────────────────────────────────────────────────────

def _corr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return fftconvolve(a, b[::-1, ::-1], mode="full")


def masked_ncc(fixed: np.ndarray, moving: np.ndarray, mmask: np.ndarray,
               min_overlap: float = 0.95):
    """Masked normalised cross-correlation of ``moving`` (with ``mmask``) slid over
    ``fixed`` (Padfield 2012). Returns (score, x, y): the best score and the top-left of
    ``moving`` in ``fixed``'s pixels. Positions where less than ``min_overlap`` of the
    moving mask lies on ``fixed`` don't count: the art must be on the sheet."""
    fmask = np.ones_like(fixed)
    m = mmask.astype(np.float32)
    t = moving * m
    overlap = np.rint(_corr(fmask, m))
    s_f = _corr(fixed, m)
    s_t = _corr(fmask, t)
    s_ff = _corr(fixed * fixed, m)
    s_tt = _corr(fmask, t * moving)
    s_ft = _corr(fixed, t)
    with np.errstate(divide="ignore", invalid="ignore"):
        num = s_ft - s_f * s_t / overlap
        var_f = s_ff - s_f ** 2 / overlap
        var_t = s_tt - s_t ** 2 / overlap
        ncc = num / np.sqrt(np.maximum(var_f * var_t, 1e-6))
    # A flat stretch of sheet (or template) has no variance to correlate: rounding there
    # can give any value, so it never counts as a match.
    ncc[(var_f < overlap) | (var_t < overlap)] = -1.0
    ncc[overlap < min_overlap * m.sum()] = -1.0
    ncc[~np.isfinite(ncc)] = -1.0
    iy, ix = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    th, tw = moving.shape
    return float(ncc[iy, ix]), ix - (tw - 1), iy - (th - 1)


@dataclass
class Match:
    """Floor pixel (u, v) shows sheet pixel (x + u/scale, y + v/scale)."""
    score: float
    x: float
    y: float
    scale: float


def _sweep(sheet: np.ndarray, floor: np.ndarray, fmask: np.ndarray, d: float,
           scales) -> Match:
    """Best match over ``scales`` with the sheet resampled by ``d`` (work px / sheet px)."""
    sh, sw = sheet.shape
    work = resize(sheet, (max(1, round(sw * d)), max(1, round(sh * d))))
    best = Match(-2.0, 0, 0, 1.0)
    fh, fw = floor.shape
    for s in scales:
        size = (round(fw * d / s), round(fh * d / s))
        if min(size) < 16 or size[0] > 2 * work.shape[1] or size[1] > 2 * work.shape[0]:
            continue
        mask = resize(fmask, size)
        if mask.sum() < 256:
            continue
        score, x, y = masked_ncc(work, resize(floor, size), mask)
        if score > best.score:
            best = Match(score, x / d, y / d, float(s))
    return best


def sample(sheet: np.ndarray, x: float, y: float, scale: float,
           fsize: tuple[int, int], out: tuple[int, int]) -> np.ndarray:
    """The sheet as the floor at (x, y, scale) would show it, at size ``out`` (w, h).

    Floor pixels that fall off the sheet come back NaN (a padded floor reaches past it)."""
    fw, fh = fsize
    ow, oh = out
    u = (np.arange(ow) + 0.5) * fw / ow
    v = (np.arange(oh) + 0.5) * fh / oh
    xs = x + u / scale - 0.5
    ys = y + v / scale - 0.5
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    return ndimage.map_coordinates(sheet, [yy, xx], order=1, cval=np.nan)


class _Sampler:
    """Samples the sheet for an ``out``-sized view of a floor near ``scale``, from a copy
    of the sheet pre-shrunk to that view's resolution so shrinking doesn't alias."""

    def __init__(self, sheet: np.ndarray, scale: float, fsize, out):
        self.z = min(1.0, scale * out[0] / fsize[0])     # view px per sheet px
        h, w = sheet.shape
        self.sheet = (resize(sheet, (max(1, round(w * self.z)), max(1, round(h * self.z))))
                      if self.z < 1.0 else sheet)
        self.fsize, self.out = fsize, out

    def __call__(self, x: float, y: float, scale: float) -> np.ndarray:
        z = self.z
        return sample(self.sheet, x * z, y * z, scale / z, self.fsize, self.out)


def _ncc(region: np.ndarray, floor_small: np.ndarray, mask_small: np.ndarray) -> float:
    ok = mask_small & np.isfinite(region)
    if ok.sum() < 0.95 * mask_small.sum():
        return -1.0
    a, b = region[ok], floor_small[ok]
    a, b = a - a.mean(), b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 0 else -1.0


def match_floor(sheet: np.ndarray, floor: np.ndarray, fmask: np.ndarray) -> Match:
    """Where ``floor`` sits on ``sheet``: a coarse sweep over scale, a finer one, then a
    sub-pixel polish at (near) full resolution."""
    sh, sw = sheet.shape
    d = min(1.0, COARSE_SIDE / max(sh, sw))
    coarse = _sweep(sheet, floor, fmask, d, np.geomspace(*SCALE_RANGE, 96))
    if coarse.score < 0.2:
        return coarse
    d2 = min(1.0, MEDIUM_SIDE / max(sh, sw))
    fine = _sweep(sheet, floor, fmask, d2, coarse.scale * np.linspace(0.95, 1.05, 21))
    best = fine if fine.score >= coarse.score else coarse
    # Polish (x, y, scale) by maximising the direct NCC, compared at <= 800 px.
    fh, fw = floor.shape
    k = min(1.0, 800 / max(fh, fw))
    small = (max(1, round(fw * k)), max(1, round(fh * k)))
    floor_small, mask_small = resize(floor, small), resize(fmask, small)

    sampler = _Sampler(sheet, best.scale, (fw, fh), small)

    def cost(p):
        return -_ncc(sampler(p[0], p[1], p[2]), floor_small, mask_small)

    p0 = np.array([best.x, best.y, best.scale])
    res = optimize.minimize(cost, p0, method="Powell",
                            options={"xtol": 1e-3, "ftol": 1e-6, "maxfev": 600})
    if -res.fun > -cost(p0):
        return Match(float(-res.fun), *(float(v) for v in res.x))
    return Match(float(-cost(p0)), best.x, best.y, best.scale)


def to_crop(sheet_name: str, m: Match, fsize: tuple[int, int]) -> dg.Crop:
    """The match as a whole-pixel crop rectangle whose ``floor_size`` is the image's.

    The rectangle may reach past the sheet's edge when the floor was padded: those floor
    pixels are blank canvas, not sheet."""
    fw, fh = fsize
    w = max(1, round(fw / m.scale))
    scale = fw / w
    h = max(1, round(fh / scale))
    return dg.Crop(sheet=sheet_name, rect=(round(m.x), round(m.y), w, h), scale=scale)


# ── The dungeon ──────────────────────────────────────────────────────────────

@dataclass
class Sheet:
    name: str
    image: str                     # where the image is read from now
    external: bool                 # outside the library: --apply copies it in
    pixels: np.ndarray = field(repr=False, default=None)


@dataclass
class FloorLink:
    floor: str
    image: str
    doc_path: str                  # the map.json the dungeon reads for this floor
    size: tuple[int, int]
    sheet: Optional[str] = None
    match: Optional[Match] = None
    crop: Optional[dg.Crop] = None
    scores: dict = field(default_factory=dict)


def dungeon_floors(layout: sl.DungeonLayout) -> list[str]:
    with open(layout.manifest_path) as f:
        man = json.load(f)
    return [str(e["map"]) for e in man.get("maps", []) if isinstance(e, dict) and e.get("map")]


def parse_sheet(arg: str, campaign: sl.Campaign) -> Sheet:
    if "=" in arg:
        path, name = arg.rsplit("=", 1)
        path = path if os.path.isabs(path) else os.path.join(campaign.root, path)
        if not os.path.isfile(path):
            raise SystemExit(f"sheet image not found: {path}")
        sl._check_name(name, "map")
        lib = sl.find_image(campaign.library_map_dir(name), name)
        if lib is not None:
            raise SystemExit(f"maps/{name} already holds an image ({lib}); "
                             f"name the sheet by its library name instead")
        return Sheet(name, path, True)
    img = sl.find_image(campaign.library_map_dir(arg), arg)
    if img is None:
        raise SystemExit(f"no library map named {arg!r} with an image")
    return Sheet(arg, img, False)


def plan(layout: sl.DungeonLayout, sheets: list[Sheet], floors: list[str],
         min_score: float = MIN_SCORE, log=print) -> list[FloorLink]:
    for s in sheets:
        s.pixels = load_gray(s.image)
    links = []
    for name in floors:
        img = layout.image(name)
        if img is None:
            log(f"  {name}: no image, skipped")
            continue
        doc_path = layout.resolve(name, sl.MAP_FILE) or layout.write_path(name, sl.MAP_FILE)
        floor = load_gray(img)
        mask = content_mask(img)
        link = FloorLink(name, img, doc_path, (floor.shape[1], floor.shape[0]))
        for s in sheets:
            m = match_floor(s.pixels, floor, mask)
            link.scores[s.name] = m.score
            if m.score >= min_score and (link.match is None or m.score > link.match.score):
                link.sheet, link.match = s.name, m
        if link.match is not None:
            link.crop = to_crop(link.sheet, link.match, link.size)
        links.append(link)
    return links


def sheet_grid(layout: sl.DungeonLayout, links: list[FloorLink], sheet: str):
    """The sheet's ``manual_grid`` and square size from the floors cut from it.

    Returns (grid or None, square_ft, note). The grid is None when the floors disagree or
    a cell isn't a whole number of sheet pixels (the engine's grid is integral)."""
    cells, anchors, squares = [], [], []
    for ln in links:
        if ln.sheet != sheet:
            continue
        mg = (sl._read_doc(ln.doc_path) or {}).get("manual_grid") or {}
        if not mg.get("cell_px"):
            continue
        c = ln.crop
        cell = float(mg["cell_px"]) / c.scale
        ax, ay = (float(v) for v in mg.get("anchor", [0, 0]))
        cells.append(cell)
        anchors.append(((c.rect[0] + ax / c.scale) % cell, (c.rect[1] + ay / c.scale) % cell))
        squares.append(int(mg.get("square_ft", 5)))
    square = max(set(squares), key=squares.count) if squares else 5
    if not cells:
        return None, square, "no floor has a grid"
    cell = float(np.median(cells))
    note = (f"cell {cell:.3f} px (floors: {', '.join(f'{c:.3f}' for c in cells)}), "
            f"anchors {', '.join(f'({a:.1f}, {b:.1f})' for a, b in anchors)}")
    if max(cells) - min(cells) > 2 * GRID_TOLERANCE * cell or \
            abs(cell - round(cell)) > GRID_TOLERANCE * max(1.0, cell / 10):
        return None, square, note + "; not whole pixels, the wizard will ask"
    c = round(cell)
    ax = round(float(np.median([a[0] for a in anchors]))) % c
    ay = round(float(np.median([a[1] for a in anchors]))) % c
    return {"cell_px": c, "anchor": [ax, ay], "square_ft": square}, square, note


def own_square_ft(doc_path: str) -> int:
    mg = (sl._read_doc(doc_path) or {}).get("manual_grid") or {}
    return int(mg.get("square_ft", 5)) if mg else 5


# ── Output ───────────────────────────────────────────────────────────────────

def write_overlays(out: str, sheets: list[Sheet], links: list[FloorLink]) -> None:
    os.makedirs(out, exist_ok=True)
    by_name = {s.name: s for s in sheets}
    for ln in links:
        if ln.crop is None:
            continue
        fw, fh = ln.size
        x, y, w, h = ln.crop.rect
        region = _Sampler(by_name[ln.sheet].pixels, ln.crop.scale, (fw, fh), (fw, fh))(
            x, y, ln.crop.scale)
        region = np.nan_to_num(region, nan=0.0)
        floor = load_gray(ln.image)
        # Padding shows the sheet alone, dimmed, so only the floor's art is in colour.
        red = np.where(content_mask(ln.image), floor, region * 0.6)
        g = np.where(content_mask(ln.image), region, region * 0.6)
        rgb = np.stack([red, g, g], axis=2).clip(0, 255).astype(np.uint8)
        Image.fromarray(rgb).save(os.path.join(out, f"{ln.floor}_match.png"))
    for s in sheets:
        mine = [ln for ln in links if ln.sheet == s.name]
        if not mine:
            continue
        with Image.open(s.image) as im:
            im = im.convert("RGB")
        k = min(1.0, 2000 / max(im.size))
        im = im.resize((round(im.width * k), round(im.height * k)))
        dr = ImageDraw.Draw(im)
        for ln in mine:
            x, y, w, h = (v * k for v in ln.crop.rect)
            dr.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=3)
            dr.text((x + 6, y + 6), ln.floor, fill=(255, 0, 0))
        im.save(os.path.join(out, f"{s.name}_rects.png"))


def report(links: list[FloorLink], sheets: list[Sheet], grids: dict, log=print) -> None:
    for ln in links:
        scores = ", ".join(f"{k} {v:.3f}" for k, v in ln.scores.items())
        if ln.crop is None:
            log(f"  {ln.floor:26s} own source  (scores: {scores})")
            continue
        x, y, w, h = ln.crop.rect
        sh, sw = next(s.pixels.shape for s in sheets if s.name == ln.sheet)
        past = x < 0 or y < 0 or x + w > sw or y + h > sh
        log(f"  {ln.floor:26s} {ln.sheet}  rect [{x}, {y}, {w}, {h}]  "
            f"scale {ln.crop.scale:.4f}  score {ln.match.score:.3f}"
            + ("  (reaches past the sheet: padded floor)" if past else ""))
    for name, (grid, square, note) in grids.items():
        log(f"  sheet {name}: {square} ft squares, grid "
            f"{grid if grid else 'not written'}; {note}")


# ── Apply ────────────────────────────────────────────────────────────────────

def _backup(path: str) -> None:
    if os.path.isfile(path) and not os.path.exists(path + BACKUP_SUFFIX):
        shutil.copy2(path, path + BACKUP_SUFFIX)


def _write_doc(path: str, doc: dict) -> None:
    _backup(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_json(path, doc)


def apply(campaign: sl.Campaign, sheets: list[Sheet], links: list[FloorLink],
          grids: dict, log=print) -> None:
    used = {ln.sheet for ln in links if ln.sheet}
    for s in sheets:
        if s.name not in used:
            continue
        lib_dir = campaign.library_map_dir(s.name)
        if s.external:
            os.makedirs(lib_dir, exist_ok=True)
            ext = os.path.splitext(s.image)[1].lower()
            dest = os.path.join(lib_dir, s.name + ext)
            shutil.copy2(s.image, dest)
            log(f"  copied {s.image} -> {dest}")
        path = os.path.join(lib_dir, sl.MAP_FILE)
        doc = sl._read_doc(path) or {}
        grid, square, _ = grids[s.name]
        doc = dg.set_meta(doc, source=dg.SourceSheet(square_ft=square))
        if grid and "manual_grid" not in doc:
            doc["manual_grid"] = grid
        _write_doc(path, doc)
        log(f"  marked {path} as a source sheet")
    for ln in links:
        doc = sl._read_doc(ln.doc_path) or {}
        if ln.crop is not None:
            doc = dg.set_meta(doc, crop=ln.crop)
        else:
            doc = dg.set_meta(doc, source=dg.SourceSheet(square_ft=own_square_ft(ln.doc_path)))
        _write_doc(ln.doc_path, doc)
        log(f"  wrote {ln.doc_path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dungeon", help="the campaign dungeon's folder (holds dungeon.json)")
    ap.add_argument("--sheet", action="append", default=[],
                    help="library map name, or <image path>=<name>; repeatable")
    ap.add_argument("--floors", nargs="*", help="only these floors (default: all)")
    ap.add_argument("--out", help="folder for the overlay PNGs")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--apply", action="store_true", help="write the metadata")
    a = ap.parse_args(argv)

    droot = os.path.abspath(a.dungeon)
    campaign = sl.Campaign.open(droot)
    layout = campaign.dungeon(os.path.basename(droot.rstrip("/")))
    if not os.path.isfile(layout.manifest_path):
        raise SystemExit(f"{layout.manifest_path} not found")
    sheets = [parse_sheet(s, campaign) for s in a.sheet]
    floors = a.floors or dungeon_floors(layout)
    print(f"{layout.name}: {len(floors)} floors, sheets: {', '.join(s.name for s in sheets) or 'none'}")
    links = plan(layout, sheets, floors, a.min_score)
    grids = {s.name: sheet_grid(layout, links, s.name) for s in sheets
             if any(ln.sheet == s.name for ln in links)}
    report(links, sheets, grids)
    if a.out:
        write_overlays(a.out, sheets, links)
        print(f"overlays in {a.out}")
    if a.apply:
        apply(campaign, sheets, links, grids)
    else:
        print("dry run: nothing written (pass --apply after checking the overlays)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
