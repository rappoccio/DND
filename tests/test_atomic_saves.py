#!/usr/bin/env python3
"""Atomic encounter saves (MULTIPLAYER_PLAN.md standalone item S1).

`open(path, "w")` truncates before it writes. On the deliberate menu save that window was
narrow enough to live with; NN7's per-turn autosave ring opens it a hundred times a
session, and the file it tears is the one a crash recovery reads. So `_save_agents` and
`_save_combat_state` go through `atomic_io.atomic_write_json`: temp sibling, fsync,
`os.replace`.

An atomicity fix is only worth the name if a failed write can be OBSERVED to leave the
old file whole, so every check here forces a failure rather than asserting a happy path:

  · a JSON round-trip through the helper, and no temp litter   (test_round_trip_and_no_litter)
  · os.replace failing leaves the previous file byte-identical (test_failed_replace_keeps_old_file)
  · a doc that will not serialize leaves it byte-identical too (test_unserializable_doc_keeps_old_file)
  · `_save_agents` routes through the helper — proven by the
    same forced failure through a real App                     (test_save_agents_is_atomic)
  · `_save_combat_state` likewise, and it still swallows the
    OSError it always swallowed                                (test_save_combat_state_is_atomic)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json
import shutil
import tempfile

import rpg_battle_map as rpg

import atomic_io
from atomic_io import atomic_write_json
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260922

SENTINEL = b'{"agents": ["the bytes that were already on disk"]}'


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _replace_fails:
    """Break the one syscall that makes the swap visible. Everything before it — the temp
    file, the serialization, the fsync — still runs, so what the assertion then reads is
    the state a crash at the worst possible moment would have left behind."""

    def __enter__(self):
        self._real = atomic_io.os.replace

        def boom(src, dst):
            raise OSError(28, "No space left on device")

        atomic_io.os.replace = boom
        return self

    def __exit__(self, *exc):
        atomic_io.os.replace = self._real
        return False


def _litter(d):
    return sorted(f for f in os.listdir(d) if ".tmp." in f)


def _app_in(tmpdir, names=("Aria", "Skarn")):
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "atomic_test_agents.json"))
    for i, nm in enumerate(names):
        cfg = rpg.AgentConfig()
        cfg.name = nm
        cfg.start_col = 2 + i * 2
        cfg.start_row = 3
        cfg.size = 1
        cfg.sprite_path = ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    return app


# ─────────────────────────────────────────────────────────────────────────────
#  The helper itself
# ─────────────────────────────────────────────────────────────────────────────

def test_round_trip_and_no_litter():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "doc.json")
        atomic_write_json(path, {"a": [1, 2], "b": None})
        with open(path) as f:
            assert json.load(f) == {"a": [1, 2], "b": None}
        assert _litter(tmp) == [], f"temp file survived a successful write: {_litter(tmp)}"
        print("✅ test_round_trip_and_no_litter passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_failed_replace_keeps_old_file():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "doc.json")
        with open(path, "wb") as f:
            f.write(SENTINEL)

        raised = False
        try:
            with _replace_fails():
                atomic_write_json(path, {"new": "content"})
        except OSError:
            raised = True
        assert raised, "a failed replace must not be swallowed by the helper"

        with open(path, "rb") as f:
            assert f.read() == SENTINEL, "the previous save was not left intact"
        assert _litter(tmp) == [], f"temp file survived a failed write: {_litter(tmp)}"
        print("✅ test_failed_replace_keeps_old_file passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unserializable_doc_keeps_old_file():
    """json.dump writes as it walks, so it has already put bytes in the temp file by the
    time it meets the set. The target must never have been opened at all."""
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "doc.json")
        with open(path, "wb") as f:
            f.write(SENTINEL)

        raised = False
        try:
            atomic_write_json(path, {"ok": [1, 2, 3], "bad": {1, 2}})
        except TypeError:
            raised = True
        assert raised, "a doc that cannot serialize must still raise"

        with open(path, "rb") as f:
            assert f.read() == SENTINEL, "the previous save was not left intact"
        assert _litter(tmp) == [], f"temp file survived a failed serialization: {_litter(tmp)}"
        print("✅ test_unserializable_doc_keeps_old_file passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
#  The two save paths S1 names
# ─────────────────────────────────────────────────────────────────────────────

def test_save_agents_is_atomic():
    tmp = tempfile.mkdtemp()
    try:
        app = _app_in(tmp)
        path = app._save_path
        with open(path, "wb") as f:
            f.write(SENTINEL)

        try:
            with _replace_fails():
                app._save_agents()
        except OSError:
            pass

        with open(path, "rb") as f:
            assert f.read() == SENTINEL, \
                "_save_agents truncated the previous save — it is not going through atomic_io"
        assert _litter(tmp) == [], f"_save_agents left a temp file behind: {_litter(tmp)}"

        # And the ordinary save still works, end to end.
        app._save_agents()
        with open(path) as f:
            doc = json.load(f)
        assert [a["name"] for a in doc["agents"]] == ["Aria", "Skarn"]
        assert _litter(tmp) == [], f"a successful _save_agents left litter: {_litter(tmp)}"
        print("✅ test_save_agents_is_atomic passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_combat_state_is_atomic():
    tmp = tempfile.mkdtemp()
    try:
        app = _app_in(tmp)
        path = app._combat_path
        # A snapshot is only written while a fight is live; without one the method
        # deletes the sidecar instead, which is a different (and correct) path.
        app.combat_active = True
        app.round_num = 3
        app.turn_idx = 1
        with open(path, "wb") as f:
            f.write(SENTINEL)

        with _replace_fails():
            app._save_combat_state()          # swallows OSError, by design, as before
        with open(path, "rb") as f:
            assert f.read() == SENTINEL, \
                "_save_combat_state truncated the sidecar — it is not going through atomic_io"
        assert _litter(tmp) == [], f"_save_combat_state left a temp file behind: {_litter(tmp)}"

        app._save_combat_state()
        with open(path) as f:
            doc = json.load(f)
        assert doc["round_num"] == 3 and doc["combat_active"] is True
        assert _litter(tmp) == [], f"a successful _save_combat_state left litter: {_litter(tmp)}"
        print("✅ test_save_combat_state_is_atomic passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_round_trip_and_no_litter()
    test_failed_replace_keeps_old_file()
    test_unserializable_doc_keeps_old_file()
    test_save_agents_is_atomic()
    test_save_combat_state_is_atomic()
    print("\n✅ All atomic-save tests passed!")
