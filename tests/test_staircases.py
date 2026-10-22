#!/usr/bin/env python3
"""
Tests for staircases in the dungeon manifest (gui/dungeon.py), step 1 of
plans/STAIRCASES_PLAN.md. Pure Python: no engine / GUI.

Covers two-phase placement (end A, then end B on the floor directly above or below),
ids that are unique and never reused after a delete, page-local ends surviving a page
move, ends on neighbouring and shared cells, Ascend/Descend direction, page removal
unfinishing or dropping a staircase, and old manifests loading and saving unchanged.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

from dungeon import Dungeon, MapPage, Staircase


def _page(pid, gx, gy, z, cols=10, rows=10):
    return MapPage(id=pid, png=f"{pid}.png", encounter_base=f"{pid}_agents.json",
                   origin=[gx, gy, z], cols=cols, rows=rows)


def _three_floors():
    """B (z=-1), M (z=0), U (z=+1), plus T (z=+2) for the gap check."""
    return Dungeon(pages=[_page("B", 0, 0, -1), _page("M", 0, 0, 0),
                          _page("U", 5, 5, 1), _page("T", 0, 0, 2)])


def test_two_phase_placement():
    d = _three_floors()
    st = d.new_staircase("M", (3, 4))
    assert st.id == 1 and st.name == "Staircase 1"
    assert not st.finished
    assert st.other_end(0) is None
    assert d.staircase_direction(st, 0) is None        # unfinished → unusable
    d.finish_staircase(st.id, "U", (7, 2))
    assert st.finished
    assert st.other_end(0).page == "U" and st.other_end(0).cell == (7, 2)
    assert st.other_end(1).page == "M" and st.other_end(1).cell == (3, 4)
    assert d.staircase_direction(st, 0) == "up"
    assert d.staircase_direction(st, 1) == "down"
    print("  ✅ two-phase placement; Ascend/Descend from either end")


def test_finish_refused_off_adjacent_floor():
    d = _three_floors()
    st = d.new_staircase("M", (1, 1))
    for bad in ("M", "T"):                              # same floor; two floors up
        try:
            d.finish_staircase(st.id, bad, (0, 0))
        except ValueError:
            pass
        else:
            raise AssertionError(f"finish on {bad} should be refused")
    assert not st.finished
    d.finish_staircase(st.id, "B", (0, 0))              # one floor down is fine
    try:
        d.finish_staircase(st.id, "U", (0, 0))          # already finished
    except ValueError:
        pass
    else:
        raise AssertionError("a third end should be refused")
    assert d.staircase_direction(st, 0) == "down"
    print("  ✅ end B refused unless on Z ± 1; no third end")


def test_ids_unique_and_not_reused():
    d = _three_floors()
    a = d.new_staircase("M", (0, 0))
    b = d.new_staircase("M", (1, 0))
    assert (a.id, b.id) == (1, 2)
    d.remove_staircase(b.id)                            # delete the newest
    c = d.new_staircase("M", (2, 0))
    assert c.id == 3, c.id                              # 2 is not handed out again
    # …and the counter survives a save/load.
    d2 = Dungeon.from_dict(json.loads(json.dumps(d.to_dict())))
    assert d2.new_staircase("M", (3, 0)).id == 4
    print("  ✅ ids unique, not reused after a delete, counter persists")


def test_delete_removes_both_ends():
    d = _three_floors()
    st = d.new_staircase("M", (3, 4))
    d.finish_staircase(st.id, "U", (7, 2))
    d.remove_staircase(st.id)
    assert d.staircase_ends_on("M") == [] and d.staircase_ends_on("U") == []
    print("  ✅ deleting a staircase removes both ends")


def test_neighbouring_and_shared_cells():
    d = _three_floors()
    # A spiral landing on M: one stair down from (4, 4), one up from the next cell…
    down = d.new_staircase("M", (4, 4)); d.finish_staircase(down.id, "B", (9, 9))
    up = d.new_staircase("M", (5, 4)); d.finish_staircase(up.id, "U", (0, 0))
    # …and a third that shares (4, 4) and goes up.
    shared = d.new_staircase("M", (4, 4)); d.finish_staircase(shared.id, "U", (1, 1))
    at = d.staircase_ends_at("M", (4, 4))
    assert sorted(st.id for st, _ in at) == [down.id, shared.id]
    assert {d.staircase_direction(st, i) for st, i in at} == {"up", "down"}
    at5 = d.staircase_ends_at("M", (5, 4))
    assert [st.id for st, _ in at5] == [up.id]
    assert d.staircase_direction(*at5[0]) == "up"
    assert len(d.staircase_ends_on("M")) == 3
    print("  ✅ neighbouring and shared ends don't interfere")


def test_page_move_keeps_ends():
    d = _three_floors()
    st = d.new_staircase("M", (3, 4)); d.finish_staircase(st.id, "U", (7, 2))
    assert d.staircase_end_global(st.ends[1]) == (12, 7, 1)
    d.page_by_id("U").origin = [20, 30, 1]              # moved on its floor
    assert st.ends[1].cell == (7, 2)                    # still the same local cell
    assert d.staircase_end_global(st.ends[1]) == (27, 32, 1)
    assert d.staircase_direction(st, 0) == "up"
    # Moved off the adjacent floor: kept, but unusable until it's fixed.
    d.page_by_id("U").origin = [20, 30, 2]
    assert d.staircase_direction(st, 0) is None
    print("  ✅ page-local ends survive a page move; a broken floor gap is unusable")


def test_remove_page_unfinishes_or_drops():
    d = _three_floors()
    full = d.new_staircase("M", (3, 4)); d.finish_staircase(full.id, "U", (7, 2))
    half = d.new_staircase("U", (1, 1))                 # unfinished, only on U
    d.remove_page("U")
    assert d.staircase_by_id(half.id) is None           # nothing left of it
    kept = d.staircase_by_id(full.id)
    assert kept is not None and not kept.finished
    assert kept.ends[0].page == "M" and kept.ends[0].cell == (3, 4)
    print("  ✅ removing a page unfinishes or drops its staircases")


def test_json_roundtrip():
    d = _three_floors()
    st = d.new_staircase("M", (3, 4), label="K21 Main → Court")
    d.finish_staircase(st.id, "U", (7, 2))
    st.name = "Grand stair"
    d.new_staircase("B", (0, 9))                        # unfinished survives too
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.dungeon.json")
        d.save(path)
        raw = json.load(open(path))
        assert raw["staircases"][0] == {
            "id": 1, "name": "Grand stair", "label": "K21 Main → Court",
            "ends": [{"page": "M", "cell": [3, 4]}, {"page": "U", "cell": [7, 2]}]}
        assert raw["next_staircase_id"] == 3
        d2 = Dungeon.load(path)
    assert [s.to_dict() for s in d2.staircases] == [s.to_dict() for s in d.staircases]
    assert d2.next_staircase_id == 3
    print("  ✅ save/load round-trip (names, labels, unfinished)")


def test_old_manifest_loads_unchanged():
    old = {"version": 1, "entry_page_id": "M",
           "pages": [_page("M", 0, 0, 0).to_dict(), _page("U", 0, 0, 1).to_dict()]}
    d = Dungeon.from_dict(old)
    assert d.staircases == [] and d.next_staircase_id == 1
    assert d.to_dict() == old                           # no staircase keys added
    print("  ✅ old manifest loads and writes back unchanged")


def test_counter_never_below_live_ids():
    # A hand-edited manifest whose counter lags its staircases.
    raw = {"pages": [_page("M", 0, 0, 0).to_dict()],
           "staircases": [{"id": 7, "ends": [{"page": "M", "cell": [1, 1]}]},
                          {"id": 9, "ends": []}],        # no ends → dropped
           "next_staircase_id": 2}
    d = Dungeon.from_dict(raw)
    assert [s.id for s in d.staircases] == [7]
    assert d.staircases[0].name == "Staircase 7"
    assert d.next_staircase_id == 8
    assert d.new_staircase("M", (0, 0)).id == 8
    print("  ✅ counter repaired to stay above every live id")


def main():
    tests = [
        test_two_phase_placement,
        test_finish_refused_off_adjacent_floor,
        test_ids_unique_and_not_reused,
        test_delete_removes_both_ends,
        test_neighbouring_and_shared_cells,
        test_page_move_keeps_ends,
        test_remove_page_unfinishes_or_drops,
        test_json_roundtrip,
        test_old_manifest_loads_unchanged,
        test_counter_never_below_live_ids,
    ]
    print("Running staircase manifest tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} staircase tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
