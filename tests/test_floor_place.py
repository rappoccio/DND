#!/usr/bin/env python3
"""Placing a floor in a dungeon's stack (DUNGEON_WIZARD_PLAN W6, D17–D19):
gui/floor_place.py.

  · above / below a floor: the next level up / down, or a new level inserted there;
  · the entry's Z never moves (D17): the block away from the entry shifts instead;
  · a floor leaving a level it alone held closes the gap;
  · ladder and door-staple targets move with their floor's Z;
  · beside: the same level, just east of that floor's pages;
  · Skip (default_origin) and the landmark pair (landmark_origin);
  · faded_floor: the floor below / above, or (beside) the same floor plus the floor below.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import dungeon as dg
import floor_place as fp


def _dung(*pages):
    """``(id, [gx, gy, z], cols, rows)`` pages; the first is the entry."""
    d = dg.Dungeon(pages=[])
    for pid, origin, cols, rows in pages:
        d.add_page(dg.MapPage(id=pid, png=pid + ".png", encounter_base="",
                              origin=list(origin), cols=cols, rows=rows))
    return d


def _zs(d):
    return {p.id: p.z for p in d.pages}


def test_above_and_below_free_levels():
    d = _dung(("g", [0, 0, 0], 10, 8), ("new", [0, 0, 1], 6, 6))
    d.page_by_id("g").origin = [3, 4, 0]
    assert fp.place(d, "new", "g", fp.ABOVE) == [3, 4, 1]
    assert fp.place(d, "new", "g", fp.BELOW) == [3, 4, -1]
    assert _zs(d) == {"g": 0, "new": -1}
    print("  ✅ above / below a floor: the next level, at its corner (Skip)")


def test_insert_keeps_the_entry_at_zero():
    # entry g at 0, u at 1, b at -1; new written at 2 (one above the highest).
    d = _dung(("g", [0, 0, 0], 4, 4), ("u", [0, 0, 1], 4, 4), ("b", [0, 0, -1], 4, 4),
              ("new", [0, 0, 2], 4, 4))
    fp.place(d, "new", "g", fp.ABOVE)           # between g (0) and u (1): u moves up
    assert _zs(d) == {"g": 0, "new": 1, "u": 2, "b": -1}, _zs(d)
    fp.place(d, "new", "g", fp.BELOW)           # leaves 1 (gap closes), between b and g
    assert _zs(d) == {"g": 0, "u": 1, "new": -1, "b": -2}, _zs(d)
    fp.place(d, "new", "u", fp.ABOVE)           # free level 2; the gap at -1 closes
    assert _zs(d) == {"g": 0, "u": 1, "new": 2, "b": -1}, _zs(d)
    fp.place(d, "new", "b", fp.ABOVE)           # between b (-1) and g (0): b moves down
    assert _zs(d) == {"g": 0, "u": 1, "new": -1, "b": -2}, _zs(d)
    print("  ✅ an inserted level shifts the block away from the entry; gaps close")


def test_portals_follow_their_floor():
    d = _dung(("g", [0, 0, 0], 4, 4), ("u", [0, 0, 1], 4, 4), ("new", [0, 0, 2], 4, 4))
    d.page_by_id("g").ladders.append({"cells": [[1, 1]], "target": [1, 1, 1]})
    d.page_by_id("u").door_links.append({"cells": [[2, 2]], "target": [2, 2, 0]})
    fp.place(d, "new", "g", fp.ABOVE)
    assert _zs(d) == {"g": 0, "new": 1, "u": 2}
    assert d.page_by_id("g").ladders[0]["target"] == [1, 1, 2]
    assert d.page_by_id("u").door_links[0]["target"] == [2, 2, 0]
    print("  ✅ ladder / door-staple targets move with their floor")


def test_beside_and_faded_floor():
    d = _dung(("g", [0, 0, 0], 10, 8), ("g2", [10, 0, 0], 5, 8), ("u", [2, 1, 1], 6, 6),
              ("new", [0, 0, 2], 4, 4))
    assert fp.place(d, "new", "g", fp.BESIDE) == [15, 0, 0]
    faded, faint = fp.faded_floor(d, "new", fp.BESIDE)
    assert [p.id for p in faded] == ["g", "g2"] and faint == []
    fp.place(d, "new", "u", fp.BESIDE)
    assert d.page_by_id("new").origin == [8, 1, 1]
    faded, faint = fp.faded_floor(d, "new", fp.BESIDE)
    assert [p.id for p in faded] == ["u"] and [p.id for p in faint] == ["g", "g2"]
    fp.place(d, "new", "u", fp.ABOVE)
    assert [p.id for p in fp.faded_floor(d, "new", fp.ABOVE)[0]] == ["u"]
    fp.place(d, "new", "g", fp.BELOW)
    assert [p.id for p in fp.faded_floor(d, "new", fp.BELOW)[0]] == ["g", "g2"]
    assert fp.stack(d) == [(1, ["u"]), (0, ["g", "g2"]), (-1, ["new"])]
    print("  ✅ beside: east of that floor's pages; the faded / faint floors per relation")


def test_landmark_and_refusals():
    assert fp.landmark_origin([0, 0, 3], (2.4, 5.6), (10.2, -1.3)) == [8, -7, 3]
    d = _dung(("g", [0, 0, 0], 4, 4), ("new", [0, 0, 1], 4, 4))
    before = fp.preview(d, "new", "g", fp.BELOW)
    assert _zs(before) == {"g": 0, "new": -1} and _zs(d) == {"g": 0, "new": 1}
    for args in (("new", "new", fp.ABOVE), ("new", "gone", fp.ABOVE), ("new", "g", "under")):
        try:
            fp.place(d, *args)
        except ValueError:
            continue
        raise AssertionError(f"accepted {args}")
    print("  ✅ landmark pair → origin; preview leaves the dungeon alone; bad requests refused")


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
