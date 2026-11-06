#!/usr/bin/env python3
"""Dungeon releases on disk: step 2 of plans/DUNGEON_RELEASES_PLAN.md (D1, D2).

  · releases number themselves V0, V1, … and a number is never reused;
  · a release holds the dungeon's design, with a library map.json copied in and library art
    left out, plus the run's board and effects;
  · later edits to the live dungeon or run do not reach a release;
  · a failed create leaves nothing behind and a leftover temp folder never lists;
  · a release that cannot be read is skipped, not fatal.
"""

import os
import sys
import json
import shutil
import tempfile
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import releases
import run_state as rs
import save_layout as sl
from test_helpers import make_fixture_campaign, FIXTURE_MAP, FIXTURE_DUNGEON


def _setup():
    tmp = tempfile.mkdtemp(prefix="releases_")
    camp = make_fixture_campaign(os.path.join(tmp, "Camp"))
    return tmp, camp, camp.dungeon(FIXTURE_DUNGEON)


def _board(dl, *names):
    run = rs.new_run(FIXTURE_MAP)
    rs.set_creatures(run, FIXTURE_MAP, {"agents": [{"name": n} for n in names]})
    os.makedirs(dl.run_dir(), exist_ok=True)
    rs.save_run(dl.run_path(), run)


def _creatures(release):
    return [a["name"] for a in rs.creatures(release.start_run(), FIXTURE_MAP)["agents"]]


def test_numbering():
    tmp, _, dl = _setup()
    try:
        assert releases.list_releases(dl) == [] and releases.newest(dl) is None
        assert releases.next_name(dl) == "V0"
        v0 = releases.create(dl, note="first")
        v1 = releases.create(dl)
        assert (v0.name, v0.number, v0.note) == ("V0", 0, "first")
        assert v1.name == "V1"
        assert [r.name for r in releases.list_releases(dl)] == ["V1", "V0"]
        assert releases.newest(dl).name == "V1" and releases.get(dl, "V0").note == "first"
        assert releases.get(dl, "V9") is None
        assert "V0" in v0.label() and "first" in v0.label()

        # Numbers sort as numbers, and a gap is not filled.
        os.rename(v1.root, dl.release_dir("V10"))
        assert releases.next_name(dl) == "V11"
        assert [r.name for r in releases.list_releases(dl)] == ["V10", "V0"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ V0, V1, … newest first, numbers never reused")


def test_contents():
    tmp, camp, dl = _setup()
    try:
        _board(dl, "Aria", "Gnasher")
        enc = dl.encounter_path(FIXTURE_MAP, "k10")
        os.makedirs(os.path.dirname(enc))
        with open(enc, "w") as f:
            json.dump({"agents": [{"name": "Bat"}]}, f)
        effects = dl.effects_dir()
        os.makedirs(effects)
        with open(os.path.join(effects, FIXTURE_MAP + ".json"), "w") as f:
            json.dump({"spell": 1}, f)

        r = releases.create(dl)
        assert r.current_map == FIXTURE_MAP and r.run == sl.DEFAULT_RUN
        assert os.path.isfile(r.manifest_path)
        assert _creatures(r) == ["Aria", "Gnasher"]
        rel_map = os.path.join(r.maps_dir, FIXTURE_MAP)
        assert os.path.isfile(os.path.join(rel_map, sl.ENCOUNTERS_DIR, "k10.json"))
        assert os.path.isfile(os.path.join(r.start_effects_dir, FIXTURE_MAP + ".json"))
        # The library's map.json is copied in; its art stays referenced.
        assert os.path.isfile(os.path.join(rel_map, sl.MAP_FILE))
        assert sl.find_image(rel_map, FIXTURE_MAP) is None
        assert not os.path.exists(dl.write_path(FIXTURE_MAP, sl.MAP_FILE)), \
            "making a release wrote into the live dungeon"

        # A local image is the dungeon's own, so it is copied.
        os.makedirs(dl.map_dir(FIXTURE_MAP), exist_ok=True)
        shutil.copyfile(dl.image(FIXTURE_MAP),
                        os.path.join(dl.map_dir(FIXTURE_MAP), FIXTURE_MAP + ".png"))
        r2 = releases.create(dl)
        assert sl.find_image(os.path.join(r2.maps_dir, FIXTURE_MAP), FIXTURE_MAP)
    finally:
        shutil.rmtree(tmp)
    print("  ✅ design + board; a library map.json copied in, its art referenced")


def test_no_run_yet():
    tmp, _, dl = _setup()
    try:
        r = releases.create(dl)
        assert r.current_map == FIXTURE_MAP
        assert r.start_run()["maps"] == {}
        assert not os.path.exists(dl.run_path()), "making a release created a run"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a dungeon with no run releases an empty board")


def test_later_edits_do_not_reach_a_release():
    tmp, _, dl = _setup()
    try:
        _board(dl, "Aria")
        path = dl.write_path(FIXTURE_MAP, sl.MAP_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"walls_enabled": False}, f)
        r = releases.create(dl)

        _board(dl, "Somebody Else")
        with open(path, "w") as f:
            json.dump({"walls_enabled": True}, f)

        assert _creatures(releases.get(dl, r.name)) == ["Aria"]
        with open(os.path.join(r.maps_dir, FIXTURE_MAP, sl.MAP_FILE)) as f:
            assert json.load(f) == {"walls_enabled": False}
    finally:
        shutil.rmtree(tmp)
    print("  ✅ later edits to the dungeon and the run do not reach a release")


def test_failed_create_leaves_nothing():
    tmp, _, dl = _setup()
    try:
        with mock.patch.object(releases, "_copy_start", side_effect=OSError("disk full")):
            try:
                releases.create(dl)
                assert False, "the failure was swallowed"
            except OSError:
                pass
        assert os.listdir(dl.releases_dir) == [], os.listdir(dl.releases_dir)
        assert releases.next_name(dl) == "V0"

        # A crash leaves a hidden temp folder: it never lists and takes no number.
        os.makedirs(os.path.join(dl.releases_dir, ".V0.tmp.123", sl.MAPS_DIR))
        assert releases.list_releases(dl) == [] and releases.next_name(dl) == "V0"
        assert releases.create(dl).name == "V0"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a failed create leaves nothing; a crash's temp folder is ignored")


def test_unreadable_release_is_skipped():
    tmp, _, dl = _setup()
    try:
        v0 = releases.create(dl)
        v1 = releases.create(dl)
        with open(os.path.join(v1.root, sl.RELEASE_FILE), "w") as f:
            f.write("{trunc")
        os.makedirs(dl.release_dir("notes"))
        assert [r.name for r in releases.list_releases(dl)] == ["V0"]
        assert releases.next_name(dl) == "V2", "reused an unreadable release's number"
        with open(os.path.join(v0.root, sl.RELEASE_FILE), "w") as f:
            json.dump({"version": 99}, f)
        assert releases.list_releases(dl) == []
    finally:
        shutil.rmtree(tmp)
    print("  ✅ an unreadable or future release is skipped and keeps its number")


def main():
    tests = [test_numbering, test_contents, test_no_run_yet,
             test_later_edits_do_not_reach_a_release, test_failed_create_leaves_nothing,
             test_unreadable_release_is_skipped]
    print("Running release tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} release tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
