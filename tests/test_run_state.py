#!/usr/bin/env python3
"""
Tests for gui/run_state.py (plans/SAVE_LAYOUT_PLAN.md D3–D6). Pure Python.

Covers terrain split into map / page / state and merged back unchanged (cell doors, edge
doors, staples, ladders, staging, fog), doors matched by key across a map edit, a fresh
run's doors at their designed state, the run's per-map creature sections, encounters
added with their tags, on-deck flags and shifted condition indices, and run.json saved
and loaded.
"""

import os
import sys
import json
import shutil
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import run_state as rs
from test_helpers import TERRAIN_CONFIG_PATH


def _terrain():
    return {
        "regions": [{"type": "Wall", "cells": [[0, 0]]}],
        "walls_enabled": True,
        "manual_grid": {"cell_px": 50, "anchor": [3, 4]},
        "detection": {"method": "edges"},
        "edge_overrides": {"add": [[1, 1, "E"]], "remove": []},
        "rooms": [{"cells": [[2, 2]]}],
        "doors": [
            {"cells": [[5, 5], [5, 6]], "cell": [5, 5], "open": True, "locked": False,
             "lock_dc": 15, "arcane_lock": False, "break_dc": 15, "broken": False,
             "link_target": [40, 5, 0]},
            {"edges": [[3, 3, "E"]], "open": False, "locked": True, "lock_dc": 18,
             "arcane_lock": True, "break_dc": 20, "broken": True, "link_target": None},
        ],
        "ladders": [{"cells": [[7, 7]], "target": [7, 7, 1]}],
        "staging_cells": [[1, 1]],
        "explored": [[0, 0], [1, 0]],
    }


def test_split_parts():
    m, x, s = rs.split_terrain(_terrain())
    assert set(m) == {"regions", "walls_enabled", "manual_grid", "detection",
                      "edge_overrides", "rooms", "doors"}
    assert m["doors"][1] == {"edges": [[3, 3, "E"]], "open": False, "locked": True,
                             "lock_dc": 18, "arcane_lock": True, "break_dc": 20}
    assert "broken" not in m["doors"][0] and "link_target" not in m["doors"][0]
    assert x == {"ladders": [{"cells": [[7, 7]], "target": [7, 7, 1]}],
                 "door_links": [{"cells": [[5, 5], [5, 6]], "target": [40, 5, 0]}],
                 "staging_cells": [[1, 1]]}
    assert s["explored"] == [[0, 0], [1, 0]]
    assert s["doors"][1] == {"edges": [[3, 3, "E"]], "open": False, "locked": True,
                             "broken": True}
    print("  ✅ split: drawing → map, links/ladders/staging → page, fog/doors → state")


def test_roundtrip():
    t = _terrain()
    assert rs.merge_terrain(*rs.split_terrain(t)) == t
    with open(TERRAIN_CONFIG_PATH) as f:
        real = json.load(f)
    back = rs.merge_terrain(*rs.split_terrain(real))
    for k in real:
        if k != "doors":
            assert back[k] == real[k], k
    assert [rs.door_key(d) for d in back["doors"]] == [rs.door_key(d) for d in real.get("doors", [])]
    print("  ✅ merge(split(t)) == t")


def test_doors_by_key():
    m, x, s = rs.split_terrain(_terrain())
    m["doors"].insert(0, {"cells": [[9, 9]], "cell": [9, 9], "open": False})  # map edit
    s["doors"].append({"cells": [[1, 2]], "open": True})                      # door gone
    t = rs.merge_terrain(m, x, s)
    assert [rs.door_key(d) for d in t["doors"]] == [
        ("cells", (9, 9)), ("cells", (5, 5), (5, 6)), ("edges", (3, 3, "E"))]
    new, cell_door, edge_door = t["doors"]
    assert new["open"] is False and new["broken"] is False and new["link_target"] is None
    assert cell_door["open"] is True and cell_door["link_target"] == [40, 5, 0]
    assert edge_door["broken"] is True and edge_door["lock_dc"] == 18
    print("  ✅ doors matched by key across a map edit; stale state dropped")


def test_fresh_run_uses_design():
    m, x, _ = rs.split_terrain(_terrain())
    t = rs.merge_terrain(m, x, None)
    assert "explored" not in t
    assert t["doors"][0]["open"] is True                # designed open
    assert t["doors"][1]["broken"] is False             # broken only through play
    assert t["doors"][1]["locked"] is True
    print("  ✅ no state: fogged, doors as designed, none broken")


def test_run_sections_and_encounters():
    run = rs.new_run("hall")
    assert rs.creatures(run, "hall") == {"agents": [], "map_items": [],
                                         "active_conditions": []}
    rs.set_creatures(run, "hall", {"agents": [{"name": "Sabalath"}],
                                   "active_conditions": [{"agent_idx": 0}]})
    enc = {"agents": [{"name": "Goblin", "on_deck": False}, {"name": "Goblin Boss", "on_deck": True}],
           "map_items": [{"name": "Chest"}],
           "active_conditions": [{"agent_idx": 1, "caster_idx": 0, "condition": "x"},
                                 {"agent_idx": 0, "caster_idx": -1}]}
    assert rs.add_encounter(run, "hall", enc, "k10-dining-hall") == 2
    c = rs.creatures(run, "hall")
    assert [a["name"] for a in c["agents"]] == ["Sabalath", "Goblin", "Goblin Boss"]
    assert [a.get("encounter") for a in c["agents"]] == [None, "k10-dining-hall",
                                                         "k10-dining-hall"]
    assert [a.get("on_deck") for a in c["agents"]] == [None, False, True]
    assert [(d["agent_idx"], d.get("caster_idx")) for d in c["active_conditions"]] == [
        (0, None), (2, 1), (1, -1)]
    assert c["map_items"] == [{"name": "Chest"}]
    assert "encounter" not in enc["agents"][0]           # the definition is untouched
    c["agents"].clear()                                  # a copy, not the run
    assert len(rs.creatures(run, "hall")["agents"]) == 3
    print("  ✅ per-map sections; encounters tagged, on-deck kept, conditions shifted")


def test_save_load():
    tmp = tempfile.mkdtemp(prefix="run_state_")
    try:
        path = os.path.join(tmp, "runs", "main", "run.json")
        run = rs.new_run("a")
        rs.map_section(run, "a")["state"] = {"explored": [[1, 1]]}
        rs.save_run(path, run)
        assert rs.load_run(path) == run
        with open(path, "w") as f:
            json.dump({"version": 99}, f)
        try:
            rs.load_run(path)
            assert False, "loaded an unknown version"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp)
    print("  ✅ run.json saved (creating runs/<run>/) and loaded; unknown version refused")


def main():
    tests = [
        test_split_parts,
        test_roundtrip,
        test_doors_by_key,
        test_fresh_run_uses_design,
        test_run_sections_and_encounters,
        test_save_load,
    ]
    print("Running run state tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} run state tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
