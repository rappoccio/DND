#!/usr/bin/env python3
"""
Tests for tools/link_floor_crops.py, W2 of plans/DUNGEON_WIZARD_PLAN.md (D24).

A synthetic campaign: two textured sheets (one in the library, one loose), and four
floors cut from them the ways the real floors were: enlarged, shrunk, pasted onto a
padded canvas so the rect reaches past the sheet, and one unrelated image. Covers the
match (rect and scale recovered), the sheet grid derived from the floors, a dry run
writing nothing, and --apply writing the blocks, copying the loose sheet into the
library and backing up only what existed, once.
"""

import os
import sys
import json
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import dungeon as dg
import save_layout as sl
import link_floor_crops as lfc

PAD = 211   # the flat canvas colour of a padded floor


def _texture(w, h, seed):
    rng = np.random.default_rng(seed)
    a = ndimage.gaussian_filter(rng.random((h, w)), 2.5)
    a = (a - a.min()) / (a.max() - a.min()) * 200 + 20
    return Image.fromarray(np.dstack([a, a * 0.9, a * 0.8]).astype(np.uint8))


def _cut(sheet, rect, scale):
    x, y, w, h = rect
    return sheet.crop((x, y, x + w, y + h)).resize(
        (round(w * scale), round(h * scale)), Image.BILINEAR)


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f)


def _fixture():
    """(campaign, layout, loose sheet path, truth) with four floors in dungeon ``keep``."""
    root = tempfile.mkdtemp(prefix="link_crops_")
    camp = sl.Campaign.create(root, "Test")
    sheet_a = _texture(600, 420, 1)
    sheet_b = _texture(500, 380, 2)
    os.makedirs(camp.library_map_dir("sheet-a"))
    sheet_a.save(os.path.join(camp.library_map_dir("sheet-a"), "sheet-a.png"))
    loose = os.path.join(root, "loose", "big-sheet.png")
    os.makedirs(os.path.dirname(loose))
    sheet_b.save(loose)

    lay = camp.dungeon("keep")
    floors = ["enlarged", "padded", "shrunk", "other"]
    _write_json(lay.manifest_path, {
        "version": 2, "entry_map": "enlarged",
        "maps": [{"map": m, "origin": [0, 0, i], "cols": 10, "rows": 10}
                 for i, m in enumerate(floors)]})

    def lib_image(name, im):
        os.makedirs(camp.library_map_dir(name), exist_ok=True)
        im.save(os.path.join(camp.library_map_dir(name), name + ".png"))

    # Enlarged ×1.5 from the library sheet, with a grid whose sheet cell is 10 px.
    lib_image("enlarged", _cut(sheet_a, (100, 60, 200, 150), 1.5))
    _write_json(lay.write_path("enlarged", sl.MAP_FILE),
                {"regions": [], "manual_grid": {"cell_px": 15, "anchor": [0, 0],
                                                "square_ft": 10}})
    # ×2 from the sheet's top-left corner, pasted at (40, 50) on a flat canvas: the
    # dungeon's own copy of the image, so the rect starts at (10 - 20, 10 - 25).
    art = _cut(sheet_a, (10, 10, 160, 120), 2.0)
    canvas = Image.new("RGB", (420, 360), (PAD, PAD, PAD))
    canvas.paste(art, (40, 50))
    os.makedirs(lay.map_dir("padded"), exist_ok=True)
    canvas.save(os.path.join(lay.map_dir("padded"), "padded.png"))
    _write_json(lay.write_path("padded", sl.MAP_FILE),
                {"regions": [], "manual_grid": {"cell_px": 20, "anchor": [0, 10],
                                                "square_ft": 10}})
    # Shrunk ×0.5 from the loose sheet; no map.json anywhere yet.
    lib_image("shrunk", _cut(sheet_b, (50, 40, 300, 200), 0.5))
    # Unrelated art: its own source.
    lib_image("other", _texture(200, 150, 99))
    _write_json(lay.write_path("other", sl.MAP_FILE),
                {"regions": [], "manual_grid": {"cell_px": 16, "anchor": [0, 0],
                                                "square_ft": 10}})
    truth = {"enlarged": ("sheet-a", (100, 60, 200, 150), 1.5),
             "padded": ("sheet-a", (-10, -15, 210, 180), 2.0),
             "shrunk": ("big-sheet", (50, 40, 300, 200), 0.5)}
    return camp, lay, loose, truth


def _run(camp, lay, loose, apply=False, out=None):
    sheets = [lfc.parse_sheet("sheet-a", camp),
              lfc.parse_sheet(f"{loose}=big-sheet", camp)]
    links = lfc.plan(lay, sheets, lfc.dungeon_floors(lay), log=lambda *_: None)
    grids = {s.name: lfc.sheet_grid(lay, links, s.name) for s in sheets
             if any(ln.sheet == s.name for ln in links)}
    if out:
        lfc.write_overlays(out, sheets, links)
    if apply:
        lfc.apply(camp, sheets, links, grids, log=lambda *_: None)
    return {ln.floor: ln for ln in links}, grids


def _snapshot(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[p] = fh.read()
    return out


def test_match_and_dry_run():
    camp, lay, loose, truth = _fixture()
    before = _snapshot(camp.root)
    out = tempfile.mkdtemp(prefix="link_out_")
    links, grids = _run(camp, lay, loose, out=out)
    for floor, (sheet, rect, scale) in truth.items():
        ln = links[floor]
        assert ln.sheet == sheet, (floor, ln.scores)
        assert ln.match.score > 0.95, (floor, ln.match)
        assert all(abs(a - b) <= 1 for a, b in zip(ln.crop.rect, rect)), (floor, ln.crop)
        assert abs(ln.crop.scale / scale - 1) < 0.01, (floor, ln.crop)
        assert ln.crop.floor_size == ln.size, (floor, ln.crop.floor_size, ln.size)
    assert links["other"].crop is None and links["other"].sheet is None
    grid, square, _ = grids["sheet-a"]
    assert square == 10 and grid == {"cell_px": 10, "anchor": [0, 0], "square_ft": 10}, grid
    assert grids["big-sheet"][0] is None          # its floor has no grid
    assert _snapshot(camp.root) == before         # the dry run wrote nothing
    assert sorted(os.listdir(out)) == ["big-sheet_rects.png", "enlarged_match.png",
                                       "padded_match.png", "sheet-a_rects.png",
                                       "shrunk_match.png"]
    print("  ✅ rect and scale recovered (enlarged, shrunk, padded); dry run writes nothing")


def test_composite_floor_is_its_own_source():
    """A floor pieced together from two places on a sheet can't be one rect."""
    camp, lay, loose, _ = _fixture()
    sheet = Image.open(os.path.join(camp.library_map_dir("sheet-a"), "sheet-a.png"))
    canvas = Image.new("RGB", (400, 200), (PAD, PAD, PAD))
    canvas.paste(_cut(sheet, (20, 20, 90, 90), 1.5), (20, 30))
    canvas.paste(_cut(sheet, (400, 250, 90, 90), 1.5), (230, 30))
    os.makedirs(lay.map_dir("other"), exist_ok=True)
    canvas.save(os.path.join(lay.map_dir("other"), "other.png"))
    links, _ = _run(camp, lay, loose)
    assert links["other"].crop is None, links["other"].scores
    print("  ✅ a floor pieced from two places on a sheet is its own source")


def test_apply():
    camp, lay, loose, truth = _fixture()
    enlarged_doc = lay.write_path("enlarged", sl.MAP_FILE)
    with open(enlarged_doc) as f:
        original = f.read()
    _run(camp, lay, loose, apply=True)

    for floor, (sheet, rect, _) in truth.items():
        c = lay.crop(floor)
        assert c is not None and c.sheet == sheet, (floor, c)
        assert all(abs(a - b) <= 1 for a, b in zip(c.rect, rect)), (floor, c)
    assert lay.crop("other") is None
    assert dg.read_source(lay.map_doc("other")) == dg.SourceSheet(10)
    # The floor's own document keeps everything else.
    assert lay.map_doc("enlarged")["manual_grid"]["cell_px"] == 15
    # A floor whose map.json was only in the library... had none: written to the dungeon.
    assert os.path.isfile(lay.write_path("shrunk", sl.MAP_FILE))

    assert sorted(camp.list_sources()) == ["big-sheet", "sheet-a"]
    assert camp.source_sheet("sheet-a") == dg.SourceSheet(10)
    assert camp.library_map_doc("sheet-a")["manual_grid"] == \
        {"cell_px": 10, "anchor": [0, 0], "square_ft": 10}
    assert "manual_grid" not in camp.library_map_doc("big-sheet")
    assert os.path.isfile(os.path.join(camp.library_map_dir("big-sheet"), "big-sheet.png"))
    assert os.path.isfile(loose)                  # the original stays

    # Backups: only files that existed, and the first one is kept on a rerun.
    assert open(enlarged_doc + lfc.BACKUP_SUFFIX).read() == original
    assert not os.path.exists(lay.write_path("shrunk", sl.MAP_FILE) + lfc.BACKUP_SUFFIX)
    sheets = [lfc.parse_sheet("sheet-a", camp)]   # big-sheet is now a library map
    links = lfc.plan(lay, sheets + [lfc.parse_sheet("big-sheet", camp)],
                     lfc.dungeon_floors(lay), log=lambda *_: None)
    lfc.apply(camp, sheets, links, {"sheet-a": lfc.sheet_grid(lay, links, "sheet-a"),
                                    "big-sheet": (None, 5, "")}, log=lambda *_: None)
    assert open(enlarged_doc + lfc.BACKUP_SUFFIX).read() == original
    assert lay.crop("enlarged") is not None
    print("  ✅ --apply writes crops, source marks and the sheet grid, backing up once")


def test_loose_sheet_name_taken():
    camp, lay, loose, _ = _fixture()
    try:
        lfc.parse_sheet(f"{loose}=sheet-a", camp)
    except SystemExit as e:
        assert "already holds an image" in str(e)
    else:
        raise AssertionError("a loose sheet may not take a library map's name")
    print("  ✅ a loose sheet can't take an existing library map's name")


def main():
    tests = [
        test_match_and_dry_run,
        test_composite_floor_is_its_own_source,
        test_apply,
        test_loose_sheet_name_taken,
    ]
    print("Running link_floor_crops tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} link_floor_crops tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
