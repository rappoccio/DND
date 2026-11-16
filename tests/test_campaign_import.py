#!/usr/bin/env python3
"""
Tests for gui/campaign_import.py (plans/NEW_DUNGEON_PLAN.md D6, step 1). Pure Python.

Covers an old scene split into map / page / state / encounter / run section and rebuilt
unchanged (terrain and roster), the rebuild check catching a lost key, PC records taken
from the newest roster without placement keys, an encounter keeping its generator
metadata but not the PCs, and sessions merged by principal id. Also checks that
tools/migrate_layout.py still imports and uses these helpers rather than its own copies.
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
import run_state as rs
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


def main():
    tests = [
        test_terrain_split_rebuilds,
        test_norm_terrain,
        test_encounter_doc,
        test_run_section_roundtrip,
        test_pc_records,
        test_merged_session,
        test_tool_uses_shared_helpers,
    ]
    print("Running campaign import tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} campaign import tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
