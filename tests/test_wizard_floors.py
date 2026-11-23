#!/usr/bin/env python3
"""The New Dungeon wizard's premade path without the panel (DUNGEON_WIZARD_PLAN W5,
D10–D16): gui/wizard_floors.py.

  · Set Grid from a box over several squares; the source block keeps the exact square;
  · crops snap to whole drawn squares; Whole image is every whole square;
  · a floor keeps the sheet's resolution, shrunk over 2048 px, always whole pixels per
    5-ft cell, so its grid sits on the drawn lines at anchor (0, 0);
  · the floor image is the crop, with brushed squares black;
  · campaign: sheet and floors in the library, dungeon.json, run, session; a later floor
    one floor up at the same corner; a re-crop keeps the place; a rename moves it all;
  · loose: files beside the manifest, the sheet in ``sources``;
  · a library map with its own grid keeps it, and is only marked as a source.
"""

import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

from PIL import Image, ImageDraw

import dungeon as dg
import run_state as rs
import save_layout as sl
import wizard_floors as wf
from dungeon_wizard import Target, PREMADE

SQ = 20.0           # the synthetic sheet's drawn square
ANCHOR = (10, 6)


def _sheet(path, size=(410, 306), sq=SQ, anchor=ANCHOR):
    """A light sheet with dark grid lines; square (k, j) is tinted by k and j."""
    img = Image.new("RGB", size, (235, 230, 220))
    d = ImageDraw.Draw(img)
    k = 0
    while anchor[0] + (k + 1) * sq <= size[0]:
        j = 0
        while anchor[1] + (j + 1) * sq <= size[1]:
            x, y = anchor[0] + k * sq, anchor[1] + j * sq
            d.rectangle([x + 3, y + 3, x + sq - 4, y + sq - 4], fill=(40 + 10 * k, 200, 40 + 10 * j))
            j += 1
        k += 1
    img.save(path)
    return path


def test_grid_snap_and_plan():
    g = wf.measure_grid((10, 6, 60, 40), 3, 2, 5)
    assert g.square_px == 20.0 and g.anchor == (10.0, 6.0) and g.per_side == 1
    assert g.manual_grid() == {"cell_px": 20, "anchor": [10, 6], "square_ft": 5}
    assert g.source() == dg.SourceSheet(5, 20.0)
    for bad in (((0, 0, 3, 3), 3, 3, 5), ((0, 0, 60, 60), 0, 1, 5), ((0, 0, 60, 60), 3, 3, 7)):
        try:
            wf.measure_grid(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    size = (410, 306)
    assert g.index_range(410, 0) == (0, 20) and g.index_range(306, 1) == (0, 15)
    assert wf.snap_squares(g, size, (33, 20), (-50, 71)) == (0, 1, 1, 3)
    assert wf.snap_squares(g, size, (33, 20), (36, 22)) is None
    assert wf.whole_image(g, size) == (0, 0, 20, 15)

    p = wf.plan_crop(g, (2, 1, 7, 4))
    assert (p.cols, p.rows, p.cell_px, p.scale, p.shrunk) == (5, 3, 20, 1.0, False)
    assert p.size == (100, 60) and p.box == (50.0, 26.0, 150.0, 86.0)
    assert p.crop("s").rect == (50, 26, 100, 60)

    # A fractional square (Ravenloft's 11.276 px at 10 ft): whole pixels per cell, and
    # the scale records the difference; 10-ft squares are 2×2 cells.
    g = wf.SheetGrid(11.276, (3.2, 4.1), 10)
    p = wf.plan_crop(g, (0, 0, 10, 8))
    assert (p.cols, p.rows, p.cell_px) == (20, 16, 6), p
    assert abs(p.scale - 12 / 11.276) < 1e-9 and p.size == (120, 96)
    # Over 2048 px: shrunk, still whole pixels per cell.
    g = wf.SheetGrid(72.0, (26, 61), 10)
    p = wf.plan_crop(g, (0, 0, 63, 40))
    assert p.shrunk and p.cell_px == 2048 // 126 and max(p.size) <= 2048, p
    assert abs(p.scale - p.cell_px / 36.0) < 1e-12
    print("  ✅ Set Grid measures; crops snap; floors are whole pixels per cell, shrunk over 2048")


def test_render_floor_and_blanks():
    tmp = tempfile.mkdtemp(prefix="wizard_floors_")
    try:
        path = _sheet(os.path.join(tmp, "sheet.png"))
        g = wf.SheetGrid(SQ, ANCHOR, 5)
        p = wf.plan_crop(g, (2, 1, 5, 3))
        img = wf.render_floor(path, p, g, blanks={(3, 2), (9, 9)})
        assert img.size == (60, 40)
        # Square (2, 1) is the floor's (0, 0): its tint is k = 2, j = 1.
        assert img.getpixel((10, 10)) == (60, 200, 50), img.getpixel((10, 10))
        assert img.getpixel((50, 10)) == (80, 200, 50)
        assert img.getpixel((30, 30)) == (0, 0, 0)          # (3, 2) blanked
        assert img.getpixel((10, 30)) == (60, 200, 60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✅ the floor image is the crop, brushed squares black")


def _read(path):
    with open(path) as f:
        return json.load(f)


def test_campaign_floors_rename_and_recrop():
    tmp = tempfile.mkdtemp(prefix="wizard_floors_")
    try:
        src = _sheet(os.path.join(tmp, "Castle Sheet.png"))
        t = Target(os.path.join(tmp, "barovia"), "Barovia", "The Keep", PREMADE)
        w = wf.FloorWriter(t)
        sheet = wf.sheet_from_file(src)
        sheet.grid = wf.SheetGrid(SQ, ANCHOR, 10)
        assert w.floor_name_problem("keep-floor-1") is None
        w.write_floor("the-keep-floor-1", sheet, (0, 0, 4, 3), {(1, 1)}, origin=[0, 0, 0])

        camp = sl.Campaign(t.campaign)
        assert camp.name == "Barovia" and os.path.isfile(camp.session_path)
        assert sheet.name == "castle-sheet" and sheet.placed
        assert camp.list_sources() == ["castle-sheet"]
        sdoc = camp.library_map_doc("castle-sheet")
        assert sdoc["manual_grid"] == {"cell_px": 10, "anchor": [10, 6], "square_ft": 10}
        assert dg.read_source(sdoc) == dg.SourceSheet(10, 20.0)
        lay = camp.dungeon("the-keep")
        assert lay.image("the-keep-floor-1").startswith(camp.library_map_dir("the-keep-floor-1"))
        assert Image.open(lay.image("the-keep-floor-1")).size == (80, 60)
        assert lay.crop("the-keep-floor-1") == dg.Crop("castle-sheet", (10, 6, 80, 60), 1.0)
        assert lay.map_doc("the-keep-floor-1")["manual_grid"] == \
            {"cell_px": 10, "anchor": [0, 0], "square_ft": 10}
        dung = dg.Dungeon.load(lay.manifest_path)
        assert dung.version == 2 and dung.entry_page_id == "the-keep-floor-1"
        assert [(p.id, p.origin, p.cols, p.rows) for p in dung.pages] == \
            [("the-keep-floor-1", [0, 0, 0], 8, 6)]
        run = rs.load_run(lay.run_path())
        assert run["current_map"] == "the-keep-floor-1" and "the-keep-floor-1" in run["maps"]

        # A second floor from the same sheet: the sheet isn't copied again.
        origin = wf.next_floor_origin(dung.pages)
        assert origin == [0, 0, 1]
        w.write_floor("upper", sheet, (4, 0, 8, 3), origin=origin)
        assert camp.list_library_maps() == ["castle-sheet", "the-keep-floor-1", "upper"]
        assert w.floor_name_problem("upper") and "already has a map" in w.floor_name_problem("upper")
        dung = dg.Dungeon.load(lay.manifest_path)
        assert dung.page_by_id("upper").origin == [0, 0, 1]

        # Re-crop (Back): same place, new image and crop; then a rename moves it all.
        dung.page_by_id("upper").origin = [3, 2, 1]
        dung.save(lay.manifest_path)
        w.write_floor("upper", sheet, (4, 0, 6, 2), old_name="upper")
        dung = dg.Dungeon.load(lay.manifest_path)
        assert (dung.page_by_id("upper").origin, dung.page_by_id("upper").cols) == ([3, 2, 1], 4)
        w.write_floor("attic", sheet, (4, 0, 6, 2), old_name="upper")
        dung = dg.Dungeon.load(lay.manifest_path)
        assert [p.id for p in dung.pages] == ["the-keep-floor-1", "attic"]
        assert dung.page_by_id("attic").origin == [3, 2, 1]
        assert os.path.isfile(os.path.join(camp.library_map_dir("attic"), "attic.png"))
        assert not os.path.exists(camp.library_map_dir("upper"))
        assert set(rs.load_run(lay.run_path())["maps"]) == {"the-keep-floor-1", "attic"}
        assert sorted(os.path.basename(c) for c in w.created) == \
            ["attic", "castle-sheet", "the-keep-floor-1"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✅ campaign: sheet + floors in the library, dungeon whole after each floor; "
          "re-crop keeps the place, rename moves it")


def test_loose_floors():
    tmp = tempfile.mkdtemp(prefix="wizard_floors_")
    try:
        src = _sheet(os.path.join(tmp, "levels.png"))
        t = Target(None, None, "Pit", PREMADE)
        t.root = lambda: os.path.join(tmp, "maps", "pit")        # loose_root stand-in
        t.manifest_path = lambda: os.path.join(tmp, "maps", "pit", "pit.dungeon.json")
        w = wf.FloorWriter(t)
        sheet = wf.sheet_from_file(src)
        sheet.grid = wf.SheetGrid(SQ, ANCHOR, 5)
        w.write_floor("pit-floor-1", sheet, (0, 0, 3, 3), origin=[0, 0, 0])
        w.write_floor("pit-floor-2", sheet, (3, 0, 6, 3), origin=[0, 0, 1])
        root = t.root()
        assert sorted(os.listdir(root)) == [
            "levels.png", "levels_terrain.json", "pit-floor-1.png", "pit-floor-1_agents.json",
            "pit-floor-1_terrain.json", "pit-floor-2.png", "pit-floor-2_agents.json",
            "pit-floor-2_terrain.json", "pit.dungeon.json"], os.listdir(root)
        dung = dg.Dungeon.load(t.manifest_path())
        assert dung.version == 1 and dung.sources == [
            {"png": "levels.png", "terrain": "levels_terrain.json"}]
        assert [(p.id, p.png, p.encounter_base, p.origin, p.cols) for p in dung.pages] == [
            ("pit-floor-1", "pit-floor-1.png", "pit-floor-1_agents.json", [0, 0, 0], 3),
            ("pit-floor-2", "pit-floor-2.png", "pit-floor-2_agents.json", [0, 0, 1], 3)]
        doc = _read(os.path.join(root, "pit-floor-2_terrain.json"))
        assert dg.read_crop(doc) == dg.Crop("levels.png", (70, 6, 60, 60), 1.0)
        assert dg.read_source(_read(os.path.join(root, "levels_terrain.json"))) == \
            dg.SourceSheet(5, 20.0)
        assert w.floor_name_problem("pit-floor-1") is not None
        assert w.floor_name_problem("levels") is not None
        w.rename_floor("pit-floor-2", "roof")
        dung = dg.Dungeon.load(t.manifest_path())
        assert [(p.id, p.png) for p in dung.pages][1] == ("roof", "roof.png")
        assert os.path.isfile(os.path.join(root, "roof_agents.json"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✅ loose: floors beside the manifest, the sheet in sources")


def test_library_map_keeps_its_grid():
    tmp = tempfile.mkdtemp(prefix="wizard_floors_")
    try:
        camp = sl.Campaign.create(os.path.join(tmp, "camp"), "Camp")
        folder = camp.library_map_dir("hall")
        os.makedirs(folder)
        _sheet(os.path.join(folder, "hall.png"))
        own = {"regions": [], "walls_enabled": True,
               "manual_grid": {"cell_px": 20, "anchor": [10, 6], "square_ft": 5}}
        with open(os.path.join(folder, sl.MAP_FILE), "w") as f:
            json.dump(own, f)
        sheet = wf.sheet_from_library(camp, "hall")
        assert sheet.library and sheet.grid_locked and sheet.grid == wf.SheetGrid(20.0, (10.0, 6.0), 5)
        t = Target(camp.root, None, "Crypt", PREMADE)
        w = wf.FloorWriter(t)
        sheet.grid = wf.SheetGrid(19.0, (0, 0), 5)                  # never written over
        w.write_floor("crypt-floor-1", sheet, (0, 0, 2, 2), origin=[0, 0, 0])
        doc = camp.library_map_doc("hall")
        assert doc["manual_grid"] == own["manual_grid"] and doc["walls_enabled"] is True
        assert dg.read_source(doc).square_ft == 5
        assert w.created == [camp.library_map_dir("crypt-floor-1")], w.created
        assert camp.dungeon("crypt").crop("crypt-floor-1").sheet == "hall"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("  ✅ a library map with its own grid keeps it, and is only marked a source")


def test_source_square_px_round_trip():
    assert dg.read_source({"source": {"square_ft": 10, "square_px": 11.276}}) == \
        dg.SourceSheet(10, 11.276)
    assert dg.SourceSheet(10, 11.276).to_dict() == {"square_ft": 10, "square_px": 11.276}
    assert dg.read_source({"source": {"square_ft": 10, "square_px": -1}}) == dg.SourceSheet(10)
    assert wf.SheetGrid.from_doc({"manual_grid": {"cell_px": 6, "anchor": [3, 4], "square_ft": 10},
                                  "source": {"square_ft": 10, "square_px": 11.276}}) == \
        wf.SheetGrid(11.276, (3.0, 4.0), 10)
    assert wf.SheetGrid.from_doc({"manual_grid": {"cell_px": 6, "anchor": [3, 4],
                                                  "square_ft": 10}}).square_px == 12
    assert wf.SheetGrid.from_doc({}) is None
    print("  ✅ the source block's exact square reads back; without it, cell × cells per side")


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:                 # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"  ❌ {name}: {e}")
                failures += 1
    sys.exit(1 if failures else 0)
