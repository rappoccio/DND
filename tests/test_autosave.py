#!/usr/bin/env python3
"""The autosave ring (MULTIPLAYER_PLAN.md NN7, M6.3: D-M6-1, D-M6-4, D-M6-8).

  · every turn start of a running fight writes one slot, at the tail of
    ``_finish_turn_start``;
  · the ring fills its empty slots, then overwrites the oldest, and holds
    ``roster.autosave_slots`` of them;
  · ``meta.json`` is the commit marker: a slot without one is ignored and written first;
  · the DM's own scene files are never touched;
  · a slot holds the whole fight: loaded as an encounter, it restores to the oracle's
    fingerprint with only the oracle's known gaps (M6.4 swaps the oracle onto the ring);
  · an autosave that fails returns None and never raises into the turn;
  · it is timed (D-M6-8).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
# The runner turns the ring off for every suite; this one is about the ring.
os.environ["RPG_AUTOSAVE"] = "1"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile
import time

import autosave
from main import App
from test_restore_oracle import (MAP_PATH, SEED, KNOWN_GAPS, KNOWN_PLAIN_GAPS, _fight,
                                 _advance_to, _ratchet, diff, fingerprint)


def _metas(app):
    return {m["slot"]: m for m in autosave.list_slots(app)}


def test_turn_start_writes_a_slot():
    """D-M6-1: a turn start saves, and the slot names the turn it saved."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        assert app.autosave_enabled
        newest = autosave.list_slots(app)[0]
        actor = app._current_agent_idx()
        assert newest["actor"] == app.bm.placed_agents[actor].name, newest
        assert (newest["round"], newest["turn_idx"]) == (app.round_num, app.turn_idx), newest
        assert newest["timestamp"] <= time.time()
        paths = autosave.slot_paths(app, newest["slot"])
        for kind in ("agents", "combat", "terrain", "meta"):
            assert os.path.exists(paths[kind]), f"slot is missing its {kind} file"
        assert paths["agents"].startswith(autosave.ring_dir(app) + os.sep)

        # The switch: off, a turn start writes nothing.
        app.autosave_enabled = False
        before = autosave.list_slots(app)
        app._advance_turn()
        assert autosave.list_slots(app) == before, "a disabled ring still wrote"
        print("✅ test_turn_start_writes_a_slot")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ring_rotates_oldest_first():
    """D-M6-4: empty slots first, then the oldest; never more than the roster's depth."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        shutil.rmtree(autosave.ring_dir(app))
        app.roster.autosave_slots = 3
        written = [autosave.save(app) for _ in range(5)]
        assert written == [0, 1, 2, 0, 1], written
        metas = _metas(app)
        assert sorted(metas) == [0, 1, 2]
        assert [m["seq"] for m in autosave.list_slots(app)] == [5, 4, 3]
        assert not os.path.exists(autosave.slot_dir(app, 3)), "the ring outgrew its depth"

        # A torn slot (no marker) is ignored and is the next one written.
        os.remove(autosave.slot_paths(app, 2)["meta"])
        assert sorted(_metas(app)) == [0, 1]
        assert autosave.save(app) == 2
        assert _metas(app)[2]["seq"] == 6

        # An unreadable or future marker counts as no marker.
        with open(autosave.slot_paths(app, 0)["meta"], "w") as f:
            f.write("{trunc")
        with open(autosave.slot_paths(app, 1)["meta"], "w") as f:
            json.dump({"version": 99, "seq": 50}, f)
        assert sorted(_metas(app)) == [2]
        print("✅ test_ring_rotates_oldest_first")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scene_files_untouched():
    """NN7: never over the DM's scene file. A fight that only autosaves leaves the
    encounter's own files exactly as the DM last wrote them."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        app._save_agents()
        app._save_terrain()
        scene = {p: open(p, "rb").read()
                 for p in (app._save_path, app._combat_path, app._terrain_path)}
        for _ in range(4):
            app._advance_turn()
        assert len(autosave.list_slots(app)) == app.roster.autosave_slots
        for p, data in scene.items():
            assert open(p, "rb").read() == data, f"the autosave rewrote {os.path.basename(p)}"
        print("✅ test_scene_files_untouched")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lighting_and_effects_copied_or_cleared():
    """The scene's lighting and effects files ride in the slot; a scene without one
    clears the slot's stale copy."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        for p, doc in ((app._lighting_path, {"default_light": "DimLight", "light_sources": []}),
                       (app._effects_path, {"effects": []})):
            with open(p, "w") as f:
                json.dump(doc, f)
        shutil.rmtree(autosave.ring_dir(app))
        app.roster.autosave_slots = 1          # both saves below land in slot 0
        assert autosave.save(app) == 0
        paths = autosave.slot_paths(app, 0)
        assert json.load(open(paths["lighting"]))["default_light"] == "DimLight"
        assert os.path.exists(paths["effects"])

        os.remove(app._lighting_path)
        os.remove(app._effects_path)
        assert autosave.save(app) == 0
        assert not os.path.exists(paths["lighting"]) and not os.path.exists(paths["effects"])
        print("✅ test_lighting_and_effects_copied_or_cleared")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _restore_slot(app, k):
    app2 = App(MAP_PATH, seed=SEED)
    app2.autosave_enabled = False
    app2._on_load_path_chosen(autosave.slot_paths(app, k)["agents"])
    return app2


def test_slot_restores_the_fight():
    """A slot is the whole fight: both oracle scenes, restored from their newest slot,
    lose exactly the oracle's known gaps. The hard scene's raw-basis agents (summon,
    tombstone) are what lets its resume run at all."""
    for hard, known, name in ((False, KNOWN_PLAIN_GAPS, "KNOWN_PLAIN_GAPS"),
                              (True, KNOWN_GAPS, "KNOWN_GAPS")):
        tmp = tempfile.mkdtemp()
        try:
            app = _fight(tmp, hard=hard)
            before = fingerprint(app)
            newest = autosave.list_slots(app)[0]
            after = fingerprint(_restore_slot(app, newest["slot"]))
            _ratchet(diff(before, after), known, name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_slot_restores_the_fight")


def test_failure_never_raises():
    """Out of combat there is nothing to save; a write that fails returns None and leaves
    the turn running."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        shutil.rmtree(autosave.ring_dir(app))
        with open(autosave.ring_dir(app), "w") as f:     # a file where the ring dir goes
            f.write("in the way")
        assert autosave.save(app) is None
        app._advance_turn()                              # the hook must swallow it too
        assert app.combat_active
        os.remove(autosave.ring_dir(app))

        app.combat_active = False
        assert autosave.save(app) is None
        assert not os.path.exists(autosave.ring_dir(app))
        print("✅ test_failure_never_raises")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_autosave_is_cheap():
    """D-M6-8: an autosave runs on the pygame thread every turn start. If it hitches,
    the escape hatch is serializing on the frame tick and writing on a thread."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=True)
        n = 10
        t0 = time.perf_counter()
        for _ in range(n):
            autosave.save(app)
        ms = (time.perf_counter() - t0) * 1000 / n
        print(f"   autosave: {ms:.1f} ms per save (hard scene, 12x12)")
        assert ms < 250, f"an autosave took {ms:.0f} ms"
        print("✅ test_autosave_is_cheap")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [test_turn_start_writes_a_slot, test_ring_rotates_oldest_first,
             test_scene_files_untouched, test_lighting_and_effects_copied_or_cleared,
             test_slot_restores_the_fight, test_failure_never_raises,
             test_autosave_is_cheap]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
