#!/usr/bin/env python3
"""
Tests for gui/save_layout.py, step 1 of plans/SAVE_LAYOUT_PLAN.md (D1–D12 paths).

Covers slugs, finding the campaign from anywhere inside it, the campaign's fixed paths,
listing dungeons / PCs / encounters / runs, the child-first lookup of a dungeon map's
files with writes going to the dungeon's copy (D3), the calibration warning, and names
that would escape their folder being refused.
"""

import os
import sys
import json
import shutil
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import save_layout as sl
from test_helpers import (make_fixture_campaign, FIXTURE_MAP, FIXTURE_DUNGEON,
                          TERRAIN_CONFIG_PATH)


def _tmp():
    return tempfile.mkdtemp(prefix="save_layout_")


def test_slugs():
    assert sl.slugify("Java of the Indies") == "java-of-the-indies"
    assert sl.slugify("Qilik (Ravenloft) ") == "qilik-ravenloft"
    assert sl.slugify("map-16-02.nedragaard-keep") == "map-16-02-nedragaard-keep"
    try:
        sl.slugify("  ()  ")
        assert False, "empty slug accepted"
    except ValueError:
        pass
    assert sl.unique_slug("Goblin Den", {"goblin-den", "goblin-den-2"}) == "goblin-den-3"
    assert sl.unique_slug("Goblin Den", set()) == "goblin-den"
    print("  ✅ slugs, and unique suffixes")


def test_create_and_find():
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(os.path.join(tmp, "Curse of Strahd"))
        assert camp.name == "Test Campaign"
        assert os.path.isdir(camp.pcs_dir) and os.path.isdir(camp.maps_dir)
        deep = camp.dungeon(FIXTURE_DUNGEON).encounter_path(FIXTURE_MAP, "k10")
        assert sl.find_campaign(deep) == camp.root          # a path that doesn't exist yet
        assert sl.find_campaign(camp.root) == camp.root
        assert sl.Campaign.open(camp.dungeon(FIXTURE_DUNGEON).root).root == camp.root
        assert sl.find_campaign(tmp) is None
        try:
            sl.Campaign.open(tmp)
            assert False, "opened a non-campaign"
        except ValueError:
            pass
        try:
            sl.Campaign.create(os.path.join(camp.root, "nested"))
            assert False, "nested campaign accepted"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)
    print("  ✅ create; found from any depth; refused outside or nested")


def test_fixed_paths():
    camp = sl.Campaign("/c")
    dun = camp.dungeon("castle-ravenloft")
    assert camp.session_path == "/c/session.json"
    assert camp.pc_path("Keef Girgo") == "/c/pcs/keef-girgo.json"
    assert camp.library_map_dir("main-floor") == "/c/maps/main-floor"
    assert dun.manifest_path == "/c/castle-ravenloft/dungeon.json"
    assert dun.map_dir("main-floor") == "/c/castle-ravenloft/maps/main-floor"
    assert (dun.encounter_path("main-floor", "k10-dining-hall")
            == "/c/castle-ravenloft/maps/main-floor/encounters/k10-dining-hall.json")
    assert dun.run_path() == "/c/castle-ravenloft/runs/main/run.json"
    assert dun.combat_path("second") == "/c/castle-ravenloft/runs/second/combat.json"
    assert dun.autosave_dir() == "/c/castle-ravenloft/runs/main/autosave"
    print("  ✅ every fixed path")


def test_bad_names_refused():
    camp = sl.Campaign("/c")
    dun = camp.dungeon("d")
    for bad in ("", ".", "..", "../x", "a/b", "a\\b", ".hidden"):
        for call in (lambda: camp.dungeon(bad), lambda: camp.library_map_dir(bad),
                     lambda: dun.map_dir(bad), lambda: dun.encounter_path("m", bad),
                     lambda: dun.run_dir(bad), lambda: dun.write_path("m", bad)):
            try:
                call()
                assert False, f"accepted {bad!r}"
            except ValueError:
                pass
    print("  ✅ names that would leave their folder are refused")


def test_listing():
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(tmp)
        dun = camp.dungeon(FIXTURE_DUNGEON)
        os.makedirs(os.path.join(tmp, "not-a-dungeon"))
        os.makedirs(os.path.join(tmp, "_archive", "old"))
        assert camp.list_dungeons() == [FIXTURE_DUNGEON]
        assert camp.list_library_maps() == [FIXTURE_MAP]
        for pc in ("Sabalath", "Java of the Indies"):
            with open(camp.pc_path(pc), "w") as f:
                json.dump({"name": pc}, f)
        assert [os.path.basename(p) for p in camp.list_pcs()] == [
            "java-of-the-indies.json", "sabalath.json"]
        assert dun.list_encounters(FIXTURE_MAP) == []
        os.makedirs(dun.encounters_dir(FIXTURE_MAP))
        for e in ("k2", "k1"):
            with open(dun.encounter_path(FIXTURE_MAP, e), "w") as f:
                json.dump({}, f)
        assert dun.list_encounters(FIXTURE_MAP) == ["k1", "k2"]
        assert dun.list_runs() == []
        os.makedirs(dun.run_dir("empty"))                 # a folder with no run.json
        os.makedirs(dun.run_dir())
        with open(dun.run_path(), "w") as f:
            json.dump({}, f)
        assert dun.list_runs() == [sl.DEFAULT_RUN]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ dungeons, library maps, PCs, encounters, runs listed")


def test_child_first_copy_on_write():
    tmp = _tmp()
    try:
        camp = make_fixture_campaign(tmp)
        dun = camp.dungeon(FIXTURE_DUNGEON)
        lib = camp.library_map_dir(FIXTURE_MAP)
        # Library only: reads come from the library, writes target the dungeon's copy.
        assert dun.resolve(FIXTURE_MAP, sl.MAP_FILE) == os.path.join(lib, sl.MAP_FILE)
        assert dun.resolve(FIXTURE_MAP, sl.LIGHTING_FILE) is None
        assert dun.image(FIXTURE_MAP) == os.path.join(lib, FIXTURE_MAP + ".png")
        assert not dun.image_is_local(FIXTURE_MAP)
        local = dun.write_path(FIXTURE_MAP, sl.MAP_FILE)
        assert local == os.path.join(dun.map_dir(FIXTURE_MAP), sl.MAP_FILE)
        assert dun.calibration_warning(FIXTURE_MAP) is None
        # A local image without its own map.json: read the local image, warn.
        os.makedirs(dun.map_dir(FIXTURE_MAP))
        shutil.copyfile(os.path.join(lib, FIXTURE_MAP + ".png"),
                        os.path.join(dun.map_dir(FIXTURE_MAP), FIXTURE_MAP + ".jpg"))
        assert dun.image(FIXTURE_MAP) == os.path.join(dun.map_dir(FIXTURE_MAP),
                                                      FIXTURE_MAP + ".jpg")
        assert dun.calibration_warning(FIXTURE_MAP)
        # Its own map.json: read it, no warning; the library file is untouched.
        with open(local, "w") as f:
            json.dump({"walls_enabled": False}, f)
        assert dun.resolve(FIXTURE_MAP, sl.MAP_FILE) == local
        assert dun.calibration_warning(FIXTURE_MAP) is None
        assert dun.list_maps() == [FIXTURE_MAP]
        with open(os.path.join(lib, sl.MAP_FILE), "rb") as a, open(TERRAIN_CONFIG_PATH, "rb") as b:
            assert a.read() == b.read()                   # library copy unchanged
    finally:
        shutil.rmtree(tmp)
    print("  ✅ child-first reads, writes to the dungeon's copy, calibration warning")


def test_image_extension_order():
    tmp = _tmp()
    try:
        for ext in (".jpg", ".png"):
            open(os.path.join(tmp, "m" + ext), "wb").close()
        assert sl.find_image(tmp, "m") == os.path.join(tmp, "m.png")
        assert sl.find_image(tmp, "other") is None
    finally:
        shutil.rmtree(tmp)
    print("  ✅ image lookup prefers .png, then .jpg")


def main():
    tests = [
        test_slugs,
        test_create_and_find,
        test_fixed_paths,
        test_bad_names_refused,
        test_listing,
        test_child_first_copy_on_write,
        test_image_extension_order,
    ]
    print("Running save layout tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} save layout tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
