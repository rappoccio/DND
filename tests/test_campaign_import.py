#!/usr/bin/env python3
"""
Tests for gui/campaign_import.py (plans/NEW_DUNGEON_PLAN.md D6, step 1). Pure Python.

Covers an old scene split into map / page / state / encounter / run section and rebuilt
unchanged (terrain and roster), the rebuild check catching a lost key, PC records taken
from the newest roster without placement keys, an encounter keeping its generator
metadata but not the PCs, and sessions merged by principal id. Also checks that
tools/migrate_layout.py still imports and uses these helpers rather than its own copies.

Step 2: ``new_dungeon`` on temp dirs. A loose scene into a new campaign (art, map.json,
page extras, encounter, run, PCs, session; the source untouched), a second dungeon reusing
the library art and keeping existing sheets unless asked, different art or map facts not
touching the library's, a library map into a new dungeon (D5), and bad calls refused.
"""

import os
import sys
import json
import shutil
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import campaign_import as ci
import releases
import run_state as rs
import save_layout as sl
from dungeon import Dungeon
from test_helpers import TERRAIN_CONFIG_PATH

PCS = ["Sabalath", "Java of the Indies"]


def _terrain():
    return {
        "regions": [{"type": "Wall", "cells": [[0, 0]]}],
        "walls_enabled": True,
        "manual_grid": {"cell_px": 50, "anchor": [3, 4]},
        "doors": [
            {"cells": [[5, 5]], "cell": [5, 5], "open": True, "locked": False,
             "lock_dc": 15, "arcane_lock": False, "break_dc": 15, "broken": False,
             "link_target": [40, 5, 0]},
            {"edges": [[3, 3, "E"]], "open": False, "locked": True, "lock_dc": 18,
             "arcane_lock": True, "break_dc": 20, "broken": True, "link_target": None},
        ],
        "ladders": [{"cells": [[7, 7]], "target": [7, 7, 1]}],
        "staging_cells": [[1, 1]],
        "explored": [[0, 0], [1, 0]],
    }


def _roster():
    return {
        "generator": {"difficulty": "hard", "seed": 7},
        "agents": [
            {"name": "Sabalath", "faction": 2, "cell": [1, 1], "page": "hall", "z": 0,
             "controller": "p1"},
            {"name": "Goblin", "faction": 1, "cell": [4, 4]},
            {"name": "Java of the Indies", "faction": 2, "cell": [1, 2]},
            {"name": "Goblin Boss", "faction": 1, "cell": [4, 5], "on_deck": True},
        ],
        "map_items": [{"name": "Chest", "cell": [2, 2]}],
        "active_conditions": [{"agent_idx": 1, "caster_idx": 0, "name": "Bless"}],
    }


def _write(path, doc, mtime=None):
    with open(path, "w") as f:
        json.dump(doc, f)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_terrain_split_rebuilds():
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "hall_terrain.json")
        _write(p, _terrain())
        m, x, s = ci.split_terrain_file(p)
        assert (m, x, s) == rs.split_terrain(_terrain())
        assert ci.rebuild_diff(_terrain(), m, x, s) == []
        with open(TERRAIN_CONFIG_PATH) as f:
            real = json.load(f)
        assert ci.rebuild_diff(real, *rs.split_terrain(real)) == []
        # A lost piece shows up as the key it lost.
        assert ci.rebuild_diff(_terrain(), m, x, {}) == ["doors", "explored"]
        assert ci.rebuild_diff(_terrain(), m, {**x, "ladders": []}, s) == ["ladders"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ terrain file → map / page / state, merged back unchanged; losses named")


def test_norm_terrain():
    t = _terrain()
    t.pop("ladders")
    t["staging_cells"] = []
    n = ci.norm_terrain(t)
    assert "ladders" not in n and "staging_cells" not in n
    assert n["doors"][0]["link_target"] == [40, 5, 0]
    print("  ✅ norm_terrain fills door defaults, drops empty ladders / staging")


def test_encounter_doc():
    r = _roster()
    enc = ci.encounter_doc(r, PCS)
    assert enc["generator"] == {"difficulty": "hard", "seed": 7}
    assert [a["name"] for a in enc["agents"]] == ["Goblin", "Goblin Boss"]
    assert enc["agents"][1]["on_deck"] is True
    assert enc["map_items"] == [] and enc["active_conditions"] == []
    enc["agents"][0]["name"] = "changed"
    assert r["agents"][1]["name"] == "Goblin"            # a copy, not the roster
    print("  ✅ encounter: non-PC creatures + metadata; items and conditions stay in the run")


def test_run_section_roundtrip():
    r, (_, _, state) = _roster(), rs.split_terrain(_terrain())
    run = rs.new_run("hall")
    ci.run_section_from(run, "hall", r, state, PCS, encounter="hall")
    back = rs.creatures(run, "hall")
    assert [a.get("encounter") for a in back["agents"]] == [None, "hall", None, "hall"]
    for a in back["agents"]:
        a.pop("encounter", None)
    assert back == {k: r[k] for k in ci.CREATURE_KEYS}
    assert rs.map_section(run, "hall")["state"] == state
    # No encounter: nobody is tagged.
    run2 = rs.new_run("hall")
    ci.run_section_from(run2, "hall", r, state, PCS)
    assert rs.creatures(run2, "hall") == {k: r[k] for k in ci.CREATURE_KEYS}
    # A run.json save / load keeps it.
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "runs", "main", "run.json")
        rs.save_run(path, run)
        assert rs.load_run(path) == run
    finally:
        shutil.rmtree(tmp)
    print("  ✅ roster → run section → roster unchanged; non-PCs tagged with the encounter")


def test_pc_records():
    tmp = tempfile.mkdtemp()
    try:
        old, new = os.path.join(tmp, "a_agents.json"), os.path.join(tmp, "b_agents.json")
        r_old = _roster()
        r_old["agents"][2]["hp"] = 5
        r_new = _roster()
        r_new["agents"] = [{"name": "Sabalath", "hp": 30, "page": "x", "z": 1,
                            "encounter": "e"},
                           {"name": "Sabalath", "hp": 1}]          # second match ignored
        _write(old, r_old, mtime=1000)
        _write(new, r_new, mtime=2000)
        found = ci.pc_records([old, new], PCS + ["Nobody"])
        assert set(found) == {"Sabalath", "Java of the Indies"}
        rec, src = found["Sabalath"]
        assert src == new and rec == {"name": "Sabalath", "hp": 30}
        rec, src = found["Java of the Indies"]
        assert src == old and rec["hp"] == 5
    finally:
        shutil.rmtree(tmp)
    print("  ✅ PC records from the newest roster, placement keys dropped")


def test_merged_session():
    tmp = tempfile.mkdtemp()
    try:
        a, b = os.path.join(tmp, "a_session.json"), os.path.join(tmp, "b_session.json")
        _write(a, {"join_code": "OLD", "principals": [{"id": "p1", "display_name": "A"},
                                                       {"id": "p2", "display_name": "B"}],
                   "revoked": ["x"]}, mtime=1000)
        _write(b, {"join_code": "NEW", "principals": [{"id": "p1", "display_name": "A2"}],
                   "revoked": ["x", "y"]}, mtime=2000)
        doc = ci.merged_session([a, b, os.path.join(tmp, "missing.json")])
        assert doc["join_code"] == "NEW"
        assert [p["display_name"] for p in doc["principals"]] == ["A2", "B"]
        assert doc["revoked"] == ["x", "y"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ sessions merged: newest settings, every principal once")


def test_tool_uses_shared_helpers():
    sys.path.insert(0, os.path.join(_ROOT, "tools"))
    import migrate_layout as ml
    assert ml.encounter_doc is ci.encounter_doc
    assert ml.run_section_from is ci.run_section_from
    assert ml._split is ci.split_terrain_file
    for gone in ("pc_records", "merged_session", "_norm_terrain", "_CREATURE_KEYS"):
        assert not hasattr(ml, gone), gone
    print("  ✅ tools/migrate_layout.py imports the helpers instead of its own copies")


# ── Step 2: new_dungeon ──────────────────────────────────────────────────────
def _scene(tmp, art=b"art-bytes", stem="Hall Map", lighting=None, session=None):
    img = os.path.join(tmp, "src", stem + ".png")
    os.makedirs(os.path.dirname(img), exist_ok=True)
    with open(img, "wb") as f:
        f.write(art)
    lpath = spath = None
    if lighting is not None:
        lpath = os.path.join(tmp, "src", stem + "_lighting.json")
        _write(lpath, lighting)
    if session is not None:
        spath = os.path.join(tmp, "src", stem + "_session.json")
        _write(spath, session)
    return ci.Scene(image=img, terrain=_terrain(), agents=_roster(), cols=30, rows=20,
                    lighting=lpath, session=spath)


def _snapshot(folder):
    out = {}
    for d, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[p] = fh.read()
    return out


def test_new_dungeon_from_scene():
    tmp = tempfile.mkdtemp()
    try:
        sc = _scene(tmp, lighting={"lights": [1]},
                    session={"join_code": "ABC", "principals": [{"id": "p1"}]})
        before = _snapshot(os.path.join(tmp, "src"))
        root = os.path.join(tmp, "Campaign")
        out = ci.new_dungeon(root, "The Hall!", sc, campaign_name="My Campaign")
        assert _snapshot(os.path.join(tmp, "src")) == before         # U1: copy, never move
        camp = sl.Campaign(root)
        assert camp.name == "My Campaign"
        assert out.layout.name == "the-hall" and out.map_name == "hall-map"
        assert camp.list_dungeons() == ["the-hall"]
        m = out.map_name
        # Art and map facts in the library; nothing in the dungeon's own map folder.
        lib = camp.library_map_dir(m)
        with open(os.path.join(lib, m + ".png"), "rb") as f:
            assert f.read() == b"art-bytes"
        map_doc, extras, state = rs.split_terrain(_terrain())
        assert ci.read_json(os.path.join(lib, sl.MAP_FILE)) == map_doc
        assert ci.read_json(os.path.join(lib, sl.LIGHTING_FILE)) == {"lights": [1]}
        assert not os.path.exists(out.layout.write_path(m, sl.MAP_FILE))
        # The page: one map at the origin with the grid size and the dungeon extras.
        dung = Dungeon.load(out.manifest_path)
        page = dung.entry_page()
        assert page.id == m and [page.gx, page.gy, page.z] == [0, 0, 0]
        assert (page.cols, page.rows) == (30, 20)
        assert page.staging_cells == [[1, 1]]
        assert len(page.ladders) == 1 and len(page.door_links) == 1
        # Encounter: non-PCs only. Run: every creature, non-PCs tagged, and the state.
        assert out.layout.list_encounters(m) == [ci.INITIAL_ENCOUNTER]
        enc = ci.read_json(out.layout.encounter_path(m, ci.INITIAL_ENCOUNTER))
        assert [a["name"] for a in enc["agents"]] == ["Goblin", "Goblin Boss"]
        run = rs.load_run(out.layout.run_path())
        assert run["current_map"] == m
        back = rs.creatures(run, m)
        assert [a.get("encounter") for a in back["agents"]] == [None, "initial", None,
                                                                "initial"]
        assert rs.map_section(run, m)["state"] == state
        assert ci.rebuild_diff(_terrain(), ci.read_json(os.path.join(lib, sl.MAP_FILE)),
                               extras, state) == []
        # PCs (faction 2) to pcs/, without placement keys.
        assert out.pcs_written == PCS and out.pcs_kept == []
        sab = ci.read_json(camp.pc_path("Sabalath"))
        assert "page" not in sab and "z" not in sab and sab["controller"] == "p1"
        # The scene's session became the campaign's.
        assert ci.read_json(camp.session_path)["join_code"] == "ABC"
        # Release V0 can be made from what was written.
        assert releases.create(out.layout, sl.DEFAULT_RUN, note="opened").name == "V0"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ loose scene → new campaign: art, map.json, page, encounter, run, PCs, session")


def test_new_dungeon_second_in_campaign():
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "Campaign")
        ci.new_dungeon(root, "Hall", _scene(tmp, session={"join_code": "ABC"}))
        camp = sl.Campaign(root)
        sab = camp.pc_path("Sabalath")
        _write(sab, {"name": "Sabalath", "level": 9})
        session_before = ci.read_json(camp.session_path)

        sc = _scene(tmp, session={"join_code": "ZZZ"})
        assert ci.pc_conflicts(root, sc.agents) == PCS
        out = ci.new_dungeon(root, "Hall", sc)
        assert out.layout.name == "hall-2"
        assert out.map_name == "hall-map"                     # same bytes: reused
        assert camp.list_library_maps() == ["hall-map"]
        assert not os.path.exists(out.layout.write_path("hall-map", sl.MAP_FILE))
        assert out.pcs_kept == PCS and out.pcs_written == []  # D4: the sheet wins
        assert ci.read_json(sab) == {"name": "Sabalath", "level": 9}
        assert ci.read_json(camp.session_path) == session_before

        out = ci.new_dungeon(root, "Hall", _scene(tmp), update_pcs=["Sabalath"])
        assert out.pcs_written == ["Sabalath"] and out.pcs_kept == ["Java of the Indies"]
        assert ci.read_json(sab)["faction"] == 2

        # Same name, other art → a new library map; the first one is untouched.
        out = ci.new_dungeon(root, "Hall", _scene(tmp, art=b"other"))
        assert out.map_name == "hall-map-2"
        assert camp.list_library_maps() == ["hall-map", "hall-map-2"]

        # Same art, other map facts → the dungeon's own map.json, the library's unchanged.
        lib_doc = ci.read_json(os.path.join(camp.library_map_dir("hall-map"), sl.MAP_FILE))
        sc = _scene(tmp)
        sc.terrain["walls_enabled"] = False
        out = ci.new_dungeon(root, "Hall", sc)
        assert out.map_name == "hall-map"
        assert ci.read_json(out.layout.write_path("hall-map", sl.MAP_FILE))[
            "walls_enabled"] is False
        assert ci.read_json(os.path.join(camp.library_map_dir("hall-map"),
                                         sl.MAP_FILE)) == lib_doc
        assert len(camp.list_dungeons()) == 5
    finally:
        shutil.rmtree(tmp)
    print("  ✅ second dungeon: art reused, sheets kept unless asked, library never changed")


def test_new_dungeon_no_creatures_no_session():
    tmp = tempfile.mkdtemp()
    try:
        sc = _scene(tmp)
        sc.agents = {"agents": [a for a in _roster()["agents"] if a["faction"] == 2]}
        root = os.path.join(tmp, "C")
        out = ci.new_dungeon(root, "Hall", sc)
        assert out.layout.list_encounters(out.map_name) == []
        run = rs.load_run(out.layout.run_path())
        assert all("encounter" not in a for a in rs.creatures(run, out.map_name)["agents"])
        doc = ci.read_json(sl.Campaign(root).session_path)
        assert doc["join_code"] and doc["principals"]            # a fresh table, with a DM
    finally:
        shutil.rmtree(tmp)
    print("  ✅ PCs only: no encounter file; no scene session: a fresh one")


def test_new_dungeon_from_library():
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "C")
        ci.new_dungeon(root, "Hall", _scene(tmp))
        camp = sl.Campaign(root)
        lib_before = _snapshot(camp.maps_dir)
        pcs_before = _snapshot(camp.pcs_dir)
        out = ci.new_dungeon(root, "Cellar", library_map="hall-map", cols=30, rows=20)
        assert out.layout.name == "cellar"
        assert sorted(os.listdir(out.layout.root)) == [sl.DUNGEON_FILE, sl.RUNS_DIR]
        page = Dungeon.load(out.manifest_path).entry_page()
        assert page.id == "hall-map" and (page.cols, page.rows) == (30, 20)
        assert page.staging_cells is None and page.ladders == []
        assert rs.load_run(out.layout.run_path()) == rs.new_run("hall-map")
        assert _snapshot(camp.maps_dir) == lib_before
        assert _snapshot(camp.pcs_dir) == pcs_before
        for bad in (dict(library_map="nope"), dict()):
            try:
                ci.new_dungeon(root, "X", **bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        try:
            ci.new_dungeon(root, "X", _scene(tmp), library_map="hall-map")
            raise AssertionError("accepted both")
        except ValueError:
            pass
        try:
            ci.new_dungeon(root, "!!!", library_map="hall-map")
            raise AssertionError("accepted an empty slug")
        except ValueError:
            pass
        assert camp.list_dungeons() == ["cellar", "hall"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ library map → dungeon.json + empty run only; bad calls refused, nothing written")


def main():
    tests = [
        test_terrain_split_rebuilds,
        test_norm_terrain,
        test_encounter_doc,
        test_run_section_roundtrip,
        test_pc_records,
        test_merged_session,
        test_tool_uses_shared_helpers,
        test_new_dungeon_from_scene,
        test_new_dungeon_second_in_campaign,
        test_new_dungeon_no_creatures_no_session,
        test_new_dungeon_from_library,
    ]
    print("Running campaign import tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} campaign import tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
