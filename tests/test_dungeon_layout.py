#!/usr/bin/env python3
"""
Tests for dungeon.json version 2 (plans/SAVE_LAYOUT_PLAN.md D4) in gui/dungeon.py.
Pure Python: no engine / GUI.

Covers a lone map opened as a one-map dungeon, the v2 round trip (maps named by their
map, entry map, rooms, staging cells, ladders, door staples, staircases), optional keys
left out, map names that would leave their folder or repeat refused, and version 1
manifests still reading and writing as version 1.
"""

import os
import sys
import json
import shutil
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from dungeon import Dungeon, MapPage, RoomLabel, DUNGEON_LAYOUT_VERSION
from test_helpers import make_fixture_campaign, FIXTURE_MAP, FIXTURE_DUNGEON


def test_single_map():
    d = Dungeon.single_map("nedragaard-keep", 40, 30)
    assert d.version == DUNGEON_LAYOUT_VERSION
    assert [p.id for p in d.pages] == ["nedragaard-keep"]
    assert d.entry_page().id == "nedragaard-keep"
    assert d.to_dict() == {"version": 2, "entry_map": "nedragaard-keep",
                           "maps": [{"map": "nedragaard-keep", "origin": [0, 0, 0],
                                     "cols": 40, "rows": 30}]}
    print("  ✅ a lone map is a one-map dungeon; optional keys left out")


def _ravenloftish():
    d = Dungeon.from_dict({
        "version": 2, "entry_map": "main-floor",
        "maps": [
            {"map": "dungeons", "origin": [0, 0, -1], "cols": 30, "rows": 20},
            {"map": "main-floor", "origin": [0, 0, 0], "cols": 30, "rows": 20,
             "rooms": [{"key": "K10", "name": "Dining Hall", "cell": [4, 5]}],
             "staging_cells": [[1, 1], [1, 2]],
             "ladders": [{"cells": [[3, 3]], "target": [3, 3, -1]}],
             "door_links": [{"cells": [[29, 7], [29, 8]], "target": [30, 7, 0]}]},
        ],
    })
    d.finish_staircase(d.new_staircase("dungeons", (2, 2)).id, "main-floor", (2, 2))
    return d


def test_v2_roundtrip():
    d = _ravenloftish()
    raw = d.to_dict()
    assert raw["version"] == 2 and raw["entry_map"] == "main-floor"
    assert "pages" not in raw and "entry_page_id" not in raw
    assert all("png" not in m and "encounter_base" not in m for m in raw["maps"])
    back = Dungeon.from_dict(json.loads(json.dumps(raw)))
    assert back.to_dict() == raw
    mf = back.page_by_id("main-floor")
    assert mf.rooms == [RoomLabel("K10", "Dining Hall", (4, 5))]
    assert mf.staging_cells == [[1, 1], [1, 2]]
    assert mf.ladders == [{"cells": [[3, 3]], "target": [3, 3, -1]}]
    assert mf.door_links[0]["target"] == [30, 7, 0]
    assert back.staircase_direction(back.staircases[0], 0) == "up"
    assert back.page_by_id("dungeons").ladders == []
    print("  ✅ v2 round trip: maps, entry, rooms, staging, ladders, staples, stairs")


def test_bad_maps_refused():
    for bad in ("", "..", "../x", "a/b", ".hidden", None):
        try:
            Dungeon.from_dict({"version": 2, "maps": [{"map": bad}]})
            assert False, f"accepted {bad!r}"
        except (ValueError, TypeError):
            pass
    try:
        Dungeon.from_dict({"version": 2, "maps": [{"map": "a"}, {"map": "a"}]})
        assert False, "accepted a repeated map"
    except ValueError:
        pass
    print("  ✅ map names that leave their folder, or repeat, are refused")


def test_entry_repaired():
    d = Dungeon.from_dict({"version": 2, "entry_map": "gone",
                           "maps": [{"map": "a"}, {"map": "b"}]})
    assert d.entry_page().id == "a" and d.to_dict()["entry_map"] == "a"
    print("  ✅ a dangling entry map falls back to the first map")


def test_v1_still_v1():
    raw = {"version": 1, "entry_page_id": "p",
           "pages": [{"id": "p", "png": "p.png", "encounter_base": "p_agents.json",
                      "origin": [0, 0, 0], "cols": 5, "rows": 5}]}
    d = Dungeon.from_dict(raw)
    assert d.version == 1
    assert d.to_dict() == raw
    built = Dungeon(pages=[MapPage(id="p", png="p.png", encounter_base="p_agents.json",
                                   cols=5, rows=5)], entry_page_id="p")
    assert built.to_dict() == raw
    print("  ✅ version 1 manifests read and write as version 1")


def test_saved_in_fixture_campaign():
    tmp = tempfile.mkdtemp(prefix="dungeon_layout_")
    try:
        camp = make_fixture_campaign(tmp)
        dl = camp.dungeon(FIXTURE_DUNGEON)
        d = Dungeon.load(dl.manifest_path)
        assert [p.id for p in d.pages] == [FIXTURE_MAP] and d.version == 2
        d.pages[0].cols, d.pages[0].rows = 12, 12
        d.save(dl.manifest_path)
        assert not [f for f in os.listdir(dl.root) if ".tmp." in f]
        assert Dungeon.load(dl.manifest_path).pages[0].cols == 12
    finally:
        shutil.rmtree(tmp)
    print("  ✅ the fixture campaign's dungeon.json loads and saves atomically")


def main():
    tests = [
        test_single_map,
        test_v2_roundtrip,
        test_bad_maps_refused,
        test_entry_repaired,
        test_v1_still_v1,
        test_saved_in_fixture_campaign,
    ]
    print("Running dungeon.json v2 tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} dungeon.json v2 tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
