#!/usr/bin/env python3
"""
Tests for tools/ladders_to_staircases.py, step 4 of plans/STAIRCASES_PLAN.md. Pure
Python: no engine / GUI.

Covers: every ladder link survives as a staircase (each ladder's cell still leads to
the same landing), a ladder with no return partner stops the conversion without
writing anything, --keep leaves a real ladder pair alone, a same-page ladder is never
converted, non-adjacent floors are refused, and --apply writes the manifest and terrain
files with backups.
"""

import os
import sys
import json
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

from dungeon import Dungeon, MapPage
import ladders_to_staircases as l2s


def _page(pid, gx, gy, z):
    return MapPage(id=pid, png=f"{pid}.png", encounter_base=f"{pid}_agents.json",
                   origin=[gx, gy, z], cols=20, rows=20)


def _lad(cell, target):
    return {"cells": [list(cell)], "target": list(target)}


def _castle():
    """B (z=-1), M (z=0, offset origin), U (z=+1). Ladder pairs: a vertical one B↔M, a
    spiral B↔M on neighbouring cells, a sideways one M↔U, and a real ladder M↔U."""
    d = Dungeon(pages=[_page("B", 0, 0, -1), _page("M", 2, 3, 0), _page("U", 0, 0, 1)])
    ladders = {
        "B": [_lad((5, 5), (5, 5, 0)), _lad((8, 8), (9, 8, 0))],
        "M": [_lad((3, 2), (5, 5, -1)), _lad((7, 5), (8, 8, -1)),
              _lad((1, 1), (10, 11, 1)), _lad((12, 12), (14, 15, 1))],
        "U": [_lad((10, 11), (3, 4, 0)), _lad((14, 15), (14, 15, 0))],
    }
    return d, ladders


def _links(d, ladders):
    """Every ladder as (global cell, global landing)."""
    out = set()
    for pid, lads in ladders.items():
        p = d.page_by_id(pid)
        for lad in lads:
            for c in lad["cells"]:
                out.add((p.local_to_global(*c), tuple(lad["target"])))
    return out


def _stair_links(d):
    out = set()
    for st in d.staircases:
        for i in (0, 1):
            out.add((d.staircase_end_global(st.ends[i]),
                     d.staircase_end_global(st.other_end(i))))
    return out


def test_conversion_keeps_every_link():
    d, ladders = _castle()
    before = _links(d, ladders)
    pairs, kept = l2s.plan_conversion(d, ladders)
    assert len(pairs) == 4 and kept == set()
    l2s.apply_conversion(d, ladders, pairs)
    assert all(not v for v in ladders.values())
    assert _stair_links(d) == before
    assert [st.name for st in d.staircases] == [f"Staircase {i}" for i in (1, 2, 3, 4)]
    assert all(st.finished and not st.label for st in d.staircases)
    # Lower floor is end A, so every staircase ascends from end 0.
    assert all(d.staircase_direction(st, 0) == "up" for st in d.staircases)
    assert d.next_staircase_id == 5


def test_keep_leaves_a_real_ladder_pair():
    d, ladders = _castle()
    before = _links(d, ladders)
    pairs, kept = l2s.plan_conversion(d, ladders, keep=[("U", (14, 15))])
    assert kept == {("U", 1), ("M", 3)}
    l2s.apply_conversion(d, ladders, pairs)
    assert len(d.staircases) == 3
    assert ladders["U"] == [_lad((14, 15), (14, 15, 0))]
    assert ladders["M"] == [_lad((12, 12), (14, 15, 1))]
    assert _stair_links(d) | _links(d, ladders) == before


def test_unpaired_ladder_stops_it():
    d, ladders = _castle()
    ladders["B"].append(_lad((1, 1), (3, 3, 0)))          # one-way: nothing on M (1, 0)
    ladders["U"][0]["target"] = [4, 4, 0]                 # lands beside its partner
    try:
        l2s.plan_conversion(d, ladders)
    except l2s.ConversionError as e:
        text = "\n".join(e.problems)
        assert "B ladder at [[1, 1]]" in text and "no return ladder" in text
        assert "U ladder at [[10, 11]]" in text
    else:
        raise AssertionError("an unpaired ladder must stop the conversion")
    assert d.staircases == []


def test_bad_keep_and_far_floors_refused():
    d, ladders = _castle()
    try:
        l2s.plan_conversion(d, ladders, keep=[("M", (0, 0))])
    except l2s.ConversionError as e:
        assert any("no ladder there" in p for p in e.problems)
    else:
        raise AssertionError("a --keep that names no ladder must be refused")
    d.pages.append(_page("T", 0, 0, 3))
    ladders["B"].append(_lad((2, 2), (2, 2, 3)))
    ladders["T"] = [_lad((2, 2), (2, 2, -1))]
    try:
        l2s.plan_conversion(d, ladders)
    except l2s.ConversionError as e:
        assert any("not adjacent" in p for p in e.problems)
    else:
        raise AssertionError("a pair across non-adjacent floors must be refused")


def test_same_page_ladder_left_alone():
    d, ladders = _castle()
    ladders["M"].append(_lad((4, 4), (10, 10, 0)))        # lands on M itself
    pairs, kept = l2s.plan_conversion(d, ladders)
    assert ("M", 4) in kept and len(pairs) == 4


def _write_dungeon(tmp):
    d, ladders = _castle()
    mpath = os.path.join(tmp, "castle.dungeon.json")
    d.save(mpath)
    for pid, lads in ladders.items():
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            json.dump({"regions": [], "walls_enabled": True, "ladders": lads}, f)
    return mpath


def test_cli_dry_run_then_apply():
    with tempfile.TemporaryDirectory() as tmp:
        mpath = _write_dungeon(tmp)
        with open(mpath) as f:
            original = f.read()
        assert l2s.main([mpath, "--keep", "M:12,12"]) == 0
        with open(mpath) as f:
            assert f.read() == original                   # dry run writes nothing
        assert not os.path.exists(os.path.join(tmp, "pre_staircases"))

        assert l2s.main([mpath, "--keep", "M:12,12", "--apply"]) == 0
        d = Dungeon.load(mpath)
        assert len(d.staircases) == 3 and d.next_staircase_id == 4
        with open(os.path.join(tmp, "B_terrain.json")) as f:
            assert json.load(f)["ladders"] == []
        with open(os.path.join(tmp, "U_terrain.json")) as f:
            assert json.load(f)["ladders"] == [_lad((14, 15), (14, 15, 0))]
        backup = os.path.join(tmp, "pre_staircases")
        with open(os.path.join(backup, "castle.dungeon.json")) as f:
            assert f.read() == original
        assert sorted(os.listdir(backup)) == ["B_terrain.json", "M_terrain.json",
                                              "U_terrain.json", "castle.dungeon.json"]


def test_cli_unpaired_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        mpath = _write_dungeon(tmp)
        path = os.path.join(tmp, "B_terrain.json")
        with open(path) as f:
            doc = json.load(f)
        doc["ladders"].append(_lad((1, 1), (3, 3, 0)))
        with open(path, "w") as f:
            json.dump(doc, f)
        with open(mpath) as f:
            original = f.read()
        assert l2s.main([mpath, "--apply"]) == 1
        with open(mpath) as f:
            assert f.read() == original
        assert not os.path.exists(os.path.join(tmp, "pre_staircases"))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
