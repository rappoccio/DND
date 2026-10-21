"""The autosave ring (MULTIPLAYER_PLAN.md NN7, M6.3).

A fight is saved at every turn boundary (D-M6-1: the tail of ``App._finish_turn_start``)
into a rotating ring of ``roster.autosave_slots`` slots (1-5, default 3), never over the
DM's own scene files (D-M6-4):

    <dir>/<base>_autosave/slot_<k>/<base>_agents.json     raw basis (D-M6-2)
                                   <base>_combat.json     engine + turn loop + board
                                   <base>_terrain.json
                                   <base>_lighting.json   copied, if the scene has one
                                   <base>_effects.json    copied, if the scene has one
                                   meta.json              the commit marker, written last

**``meta.json`` is the commit marker.** A write removes the slot's marker first and writes
it again, atomically, only after every other file is in place, so a crash mid-write leaves
a slot without one and that slot is ignored. With two or more slots a complete earlier
save always survives. The slot written is the empty one, else the oldest (lowest ``seq``).

Restoring a slot is M6.4. This module only writes and lists the ring.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from atomic_io import atomic_write_json

META_FILE = "meta.json"
META_VERSION = 1


def ring_dir(app) -> str:
    """``<dir>/<base>_autosave``, beside the active encounter's sidecars."""
    d, base = app._sidecar_base(app._save_path)
    return os.path.join(d, base + "_autosave")


def slot_dir(app, k: int) -> str:
    return os.path.join(ring_dir(app), f"slot_{k}")


def slot_paths(app, k: int) -> dict[str, str]:
    """The slot's files, named like the encounter's own sidecars, so a slot reads as an
    encounter under ``_sidecar_base``."""
    _, base = app._sidecar_base(app._save_path)
    d = slot_dir(app, k)
    paths = {kind: os.path.join(d, f"{base}_{kind}.json")
             for kind in ("agents", "combat", "terrain", "lighting", "effects")}
    paths["meta"] = os.path.join(d, META_FILE)
    return paths


def read_meta(app, k: int) -> dict | None:
    """The slot's committed meta, or None if the slot is empty, torn or unreadable."""
    try:
        with open(slot_paths(app, k)["meta"]) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get("seq"), int):
        return None
    if meta.get("version", 0) > META_VERSION:
        return None
    return meta


def list_slots(app) -> list[dict]:
    """Every committed slot in the ring, newest first, each meta with its ``slot`` index."""
    out = []
    for k in range(app.roster.autosave_slots):
        meta = read_meta(app, k)
        if meta is not None:
            out.append(dict(meta, slot=k))
    out.sort(key=lambda m: m["seq"], reverse=True)
    return out


def _next_slot(app) -> tuple[int, int]:
    """(slot to write, seq to give it): the first empty slot, else the oldest."""
    metas = [read_meta(app, k) for k in range(app.roster.autosave_slots)]
    seq = 1 + max((m["seq"] for m in metas if m is not None), default=0)
    for k, m in enumerate(metas):
        if m is None:
            return k, seq
    oldest = min(range(len(metas)), key=lambda k: metas[k]["seq"])
    return oldest, seq


def _copy_or_clear(src: str, dst: str):
    """Copy a scene file into the slot atomically, or remove the slot's stale copy when
    the scene has none (a restore must not pick up a previous scene's lights)."""
    if os.path.exists(src):
        tmp = f"{dst}.tmp.{os.getpid()}"
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    else:
        try:
            os.remove(dst)
        except FileNotFoundError:
            pass


def save(app) -> int | None:
    """Write the live fight into the next slot of the ring. Returns the slot written, or
    None when there is nothing to save or the write failed. Never raises: an autosave
    that fails must not take the turn down with it."""
    if not app.combat_active:
        return None
    try:
        k, seq = _next_slot(app)
        paths = slot_paths(app, k)
        os.makedirs(slot_dir(app, k), exist_ok=True)
        # Un-commit first: from here until the new marker lands, the slot is torn.
        try:
            os.remove(paths["meta"])
        except FileNotFoundError:
            pass
        app._save_agents(paths["agents"], raw=True)
        # _save_agents writes the combat sidecar only for the DM's own file, so the slot
        # writes its own.
        app._save_combat_state(paths["combat"])
        app._save_terrain(paths["terrain"])
        _copy_or_clear(app._lighting_path, paths["lighting"])
        _copy_or_clear(app._effects_path, paths["effects"])
        idx = app._current_agent_idx()
        actor = (app.bm.placed_agents[idx].name
                 if 0 <= idx < len(app.bm.placed_agents) else "")
        atomic_write_json(paths["meta"], {
            "version":   META_VERSION,
            "seq":       seq,
            "round":     int(app.round_num),
            "turn_idx":  int(app.turn_idx),
            "actor":     actor,
            "timestamp": time.time(),
        })
        return k
    except Exception as e:                       # noqa: BLE001 — see the docstring
        print(f"Warning: autosave failed: {e}")
        return None
