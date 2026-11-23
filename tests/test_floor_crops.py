#!/usr/bin/env python3
"""
Tests for W1 of plans/DUNGEON_WIZARD_PLAN.md: source sheets and floor crop metadata.

Covers the ``source`` / ``crop`` blocks of a map's design document (read, written,
malformed values ignored), the loose manifest's optional ``sources`` list, both terrain
writers keeping the blocks across a save, the campaign's source-sheet listing, and older
files reading and writing back unchanged (D26).
"""

import os
import sys
import json
import shutil
import tempfile
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import dungeon as dg
import run_state as rs
import save_layout as sl
import scene_store
from test_helpers import make_fixture_campaign, FIXTURE_MAP, FIXTURE_DUNGEON


def _tmp():
    return tempfile.mkdtemp(prefix="floor_crops_")


CROP = {"sheet": "spires-of-ravenloft", "rect": [10, 20, 300, 200], "scale": 2.0}


def test_crop_round_trip():
    c = dg.Crop.from_value(CROP)
    assert c == dg.Crop("spires-of-ravenloft", (10, 20, 300, 200), 2.0)
    assert c.to_dict() == CROP
    assert c.floor_size == (600, 400)
    assert dg.Crop("s", (0, 0, 4800, 6600), 0.31).floor_size == (1488, 2046)
    assert dg.read_crop({"crop": CROP}) == c
    assert dg.read_crop({}) is None and dg.read_crop(None) is None
    print("  ✅ crop reads, writes and gives the floor size")


def test_bad_crops_ignored():
    for bad in ({"rect": [0, 0, 1, 1]},                         # no sheet
                {**CROP, "sheet": ""},
                {**CROP, "rect": [0, 0, 1]},
                {**CROP, "rect": [0, 0, 0, 5]},                  # empty
                {**CROP, "rect": [-1, 0, 5, 5]},
                {**CROP, "rect": "nope"},
                {**CROP, "scale": 0},
                {**CROP, "scale": -1},
                {**CROP, "scale": "x"},
                {**CROP, "scale": float("nan")},
                "crop", 3, None):
        assert dg.Crop.from_value(bad) is None, bad
    assert dg.Crop.from_value({"sheet": "s", "rect": [0, 0, 5, 5]}).scale == 1.0
    print("  ✅ a malformed crop reads as none")


def test_source_values():
    assert dg.read_source({"source": True}) == dg.SourceSheet(5)
    assert dg.read_source({"source": {"square_ft": 10}}) == dg.SourceSheet(10)
    assert dg.read_source({"source": {}}).square_ft == 5
    for bad in (False, None, 0, "yes", {"square_ft": 0}, {"square_ft": "x"}):
        assert dg.read_source({"source": bad}) is None, bad
    assert dg.read_source({}) is None
    assert dg.SourceSheet(10).to_dict() == {"square_ft": 10}
    print("  ✅ source marks read, true meaning 5 ft")


def test_set_and_carry():
    doc = {"regions": [], "manual_grid": {"cell_px": 50, "anchor": [0, 0]}}
    d = dg.set_meta(doc, source=dg.SourceSheet(10), crop=dg.Crop.from_value(CROP))
    assert d["source"] == {"square_ft": 10} and d["crop"] == CROP
    assert "source" not in doc, "set_meta changed its argument"
    assert dg.set_meta(d, crop=None).get("crop") is None
    assert dg.set_meta(d, crop=None)["source"] == {"square_ft": 10}   # left out ⇒ kept
    carried = dg.carry_meta({"regions": [1]}, d)
    assert carried == {"regions": [1], "source": {"square_ft": 10}, "crop": CROP}
    # The new document's own block wins.
    own = {"crop": {**CROP, "scale": 3.0}}
    assert dg.carry_meta(own, d)["crop"]["scale"] == 3.0
    assert dg.carry_meta({"a": 1}, None) == {"a": 1}
    assert dg.carry_meta({"a": 1}, {"regions": []}) == {"a": 1}
    print("  ✅ set_meta sets and removes; carry_meta fills only what is missing")


def test_split_terrain_keeps_meta():
    design = {"regions": [], "doors": [], "source": True, "crop": CROP}
    terrain = {"regions": [[1, 2]], "doors": [], "walls_enabled": True}
    map_doc = rs.split_terrain(terrain, design)[0]
    assert map_doc["crop"] == CROP and map_doc["source"] is True
    assert map_doc["regions"] == [[1, 2]]
    # No design on disk, no blocks: the map.json is what it always was.
    assert "crop" not in rs.split_terrain(terrain, None)[0]
    assert "source" not in rs.split_terrain(terrain, {"doors": []})[0]
    print("  ✅ split_terrain keeps the map.json's source and crop")


def test_campaign_store_keeps_crop():
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(os.path.join(tmp, "camp"))
        layout = camp.dungeon(FIXTURE_DUNGEON)
        lib = os.path.join(camp.library_map_dir(FIXTURE_MAP), sl.MAP_FILE)
        with open(lib) as f:
            doc = json.load(f)
        with open(lib, "w") as f:
            json.dump(dg.set_meta(doc, crop=dg.Crop.from_value(CROP)), f)
        assert layout.crop(FIXTURE_MAP) == dg.Crop.from_value(CROP)
        assert camp.list_sources() == []

        dung = dg.Dungeon.load(layout.manifest_path)
        app = types.SimpleNamespace(dungeon=dung)
        store = scene_store.CampaignStore(app, layout)
        store.point_at(dung.entry_page())
        t = store.terrain()
        assert "crop" not in t, "crop leaked into the terrain document"
        t["regions"] = [[0, 0]]
        store.write_terrain(t)
        local = layout.write_path(FIXTURE_MAP, sl.MAP_FILE)
        with open(local) as f:
            written = json.load(f)
        assert written["regions"] == [[0, 0]]
        assert written["crop"] == CROP, "a terrain save dropped the crop"
        assert layout.crop(FIXTURE_MAP) == dg.Crop.from_value(CROP)
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a campaign terrain save keeps the floor's crop")


def test_list_sources():
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(os.path.join(tmp, "camp"))
        for name, doc in (("sheet", {"source": {"square_ft": 10}}),
                          ("single", {"source": True, "crop": None}),
                          ("plain", {"regions": []}),
                          ("broken", None)):
            d = camp.library_map_dir(name)
            os.makedirs(d)
            with open(os.path.join(d, sl.MAP_FILE), "w") as f:
                f.write("{not json" if doc is None else json.dumps(doc))
        os.makedirs(camp.library_map_dir("no-map-json"))
        assert sorted(camp.list_sources()) == ["sheet", "single"]
        assert camp.source_sheet("sheet").square_ft == 10
        assert camp.source_sheet("plain") is None
        assert camp.source_sheet("broken") is None
        assert camp.library_map_doc("no-map-json") is None
        layout = camp.dungeon(FIXTURE_DUNGEON)
        assert layout.crop("single") is None and layout.crop(FIXTURE_MAP) is None
    finally:
        shutil.rmtree(tmp)
    print("  ✅ the library lists its source sheets")


def test_legacy_store_keeps_meta():
    tmp = _tmp()
    try:
        path = os.path.join(tmp, "floor_terrain.json")
        with open(path, "w") as f:
            json.dump({"regions": [], "source": True, "crop": CROP}, f)
        app = types.SimpleNamespace(_terrain_path=path, dungeon_page=None)
        store = scene_store.LegacyStore(app)
        store.write_terrain({"regions": [[3, 4]], "walls_enabled": False})
        with open(path) as f:
            doc = json.load(f)
        assert doc == {"regions": [[3, 4]], "walls_enabled": False,
                       "source": True, "crop": CROP}
        # A fresh file, and an unreadable one, are written as given.
        fresh = os.path.join(tmp, "new_terrain.json")
        app._terrain_path = fresh
        store.write_terrain({"regions": []})
        with open(fresh) as f:
            assert json.load(f) == {"regions": []}
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a loose terrain save keeps the floor's crop")


def test_loose_manifest_sources():
    page = dg.MapPage(id="p0", png="f0.png", encounter_base="f0_agents.json")
    plain = dg.Dungeon(pages=[page], entry_page_id="p0")
    assert "sources" not in plain.to_dict(), "an old manifest grew a sources key"
    src = {"png": "sheet.png", "terrain": "sheet_terrain.json"}
    d = dg.Dungeon(pages=[page], entry_page_id="p0", sources=[src])
    back = dg.Dungeon.from_dict(json.loads(json.dumps(d.to_dict())))
    assert back.sources == [src]
    assert back.to_dict() == d.to_dict()
    # Entries without a png are dropped; a missing terrain reads as "".
    mixed = {**d.to_dict(), "sources": [{"terrain": "x"}, {"png": "a.png"}, "junk"]}
    assert dg.Dungeon.from_dict(mixed).sources == [{"png": "a.png", "terrain": ""}]
    # Version 2 never carries it: its sheets are library maps.
    v2 = dg.Dungeon.single_map("hall")
    v2.sources = [src]
    assert "sources" not in v2.to_dict()
    assert dg.Dungeon.from_dict({**v2.to_dict(), "sources": [src]}).sources == []
    print("  ✅ a loose manifest's sources round-trip, absent by default")


def test_old_manifests_unchanged():
    for name in ("maps/TestDNDMap.dungeon.json", "maps/Blank.dungeon.json"):
        p = os.path.join(_ROOT, name)
        if not os.path.isfile(p):
            continue
        with open(p) as f:
            raw = json.load(f)
        assert dg.Dungeon.from_dict(raw).sources == []
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(os.path.join(tmp, "camp"))
        path = camp.dungeon(FIXTURE_DUNGEON).manifest_path
        with open(path) as f:
            raw = json.load(f)
        assert dg.Dungeon.from_dict(raw).to_dict() == raw
    finally:
        shutil.rmtree(tmp)
    print("  ✅ older manifests read and write back unchanged")


def main():
    tests = [
        test_crop_round_trip,
        test_bad_crops_ignored,
        test_source_values,
        test_set_and_carry,
        test_split_terrain_keeps_meta,
        test_campaign_store_keeps_crop,
        test_list_sources,
        test_legacy_store_keeps_meta,
        test_loose_manifest_sources,
        test_old_manifests_unchanged,
    ]
    print("Running floor crop tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} floor crop tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
