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

**Restoring a slot (M6.4, D-M6-5)** loads the slot's files by path, in the order
``_on_load_path_chosen`` loads an encounter, and never through it: that would point the
encounter base at the slot, so the DM's next save would land in the ring and the next
autosave would nest a ring inside a slot, and a moved base re-points the roster, which logs
every player out. The base, the roster and the DM's scene files stay exactly as they were.
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


# ── Restore (M6.4) ──────────────────────────────────────────────────────────

def restore_blocked(app) -> str | None:
    """Why a restore cannot run right now, or None. A restore replaces the board under
    whatever is in flight, and these are the things whose continuation would then run
    against the wrong fight: an automated turn mid-playback, an open reaction window, and
    the legendary-action phase between two turns."""
    if app._npc_anim is not None:
        return "an automated turn is still playing"
    if app.combat.pending_decision().active:
        return "a reaction is waiting for an answer"
    if app._legendary_queue or app._legendary_actor >= 0 or app._legendary_move_active:
        return "the legendary-action phase is running"
    return None


def _read_slot(paths: dict[str, str]) -> str | None:
    """Check the slot is one fight before the live scene is touched. Returns why not."""
    try:
        with open(paths["agents"]) as f:
            agents = json.load(f)["agents"]
        with open(paths["combat"]) as f:
            combat = json.load(f)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return f"unreadable ({e})"
    if not isinstance(agents, list) or not isinstance(combat, dict):
        return "unreadable"
    if not combat.get("combat_active") or not combat.get("initiative_order"):
        return "it holds no running fight"
    if combat.get("agent_basis") != [a.get("name") for a in agents if isinstance(a, dict)]:
        return "its agents and its fight disagree"
    return None


def _settle_turn(app) -> None:
    """Land on the top of the restored turn, the state ``_finish_turn_start`` leaves.

    The slot was written there, where the action economy is fresh and no pick is armed;
    a restore into a running App resets its own copies to match. The NPC drive is re-armed
    from the restored turn (F-M6-4): the save point is before an automated turn runs, so
    the turn on the slot has not run yet."""
    app._reset_turn_economy()
    app._clear_pending_target_picks()
    app.pending_dispel_selection = None
    app._reaction_finish = lambda: None
    app.combat_panel_scroll = 0
    cur = app._current_agent_idx()
    app.selected_idx = cur
    app._turn_start_idx = cur
    app._npc_drive_idx = (cur if 0 <= cur < len(app.bm.placed_agents)
                          and app.bm.is_agent_npc_automated(cur)
                          and not app.bm.is_agent_on_deck(cur) else -1)
    # The board snapshot replaced the spell effects, so their render metadata is rebuilt
    # from what is on the board now rather than from the scene's configuration file.
    app._effect_meta.clear()
    app._build_spell_effect_metadata()
    app._update_reach()
    app._update_attack_overlay()
    app._mark_fog_dirty()


def _resync_players(app) -> None:
    """Every seated player gets a fresh ``view`` and nothing replays (D-M6-5, D-M6-6).
    The forced boundary pushes on the next frame even when the restored turn is the one
    the push cycle last saw, and it publishes the page image without the lag."""
    app.events.resync_all()
    app._net_turn = None


def restore(app, k: int) -> bool:
    """Restore slot ``k`` of the active encounter's ring into ``app``. Returns True when
    the fight resumed. A refusal flashes its reason and, short of the engine refusing its
    own snapshot after the load, leaves the live scene untouched."""
    why = restore_blocked(app)
    if why is None:
        meta = read_meta(app, k)
        if meta is None:
            why = "that slot is empty or torn"
        else:
            paths = slot_paths(app, k)
            why = _read_slot(paths)
    if why is not None:
        app._flash_status(f"Autosave not restored: {why}")
        return False
    app._load_agents(paths["agents"])
    app._load_terrain(paths["terrain"])
    app._load_lighting(paths["lighting"])
    app._load_spell_effects(paths["effects"])
    if not app._load_combat_state(paths["combat"]):
        return False                   # _load_combat_state has flashed why
    _settle_turn(app)
    _resync_players(app)
    app._combat_log_add(f"[RESTORED] autosave: round {meta.get('round', 0) + 1}, "
                        f"{meta.get('actor') or '?'}'s turn")
    app._flush_combat_log()
    # The table's line names the round only: the actor may be a creature the party cannot
    # see, and the session log goes to every seat unfiltered by fog (D-M7-4).
    app.session_log.add(f"The DM restored an autosave from round {meta.get('round', 0) + 1}.")
    app._flash_status(f"Restored: round {meta.get('round', 0) + 1}, "
                      f"{meta.get('actor') or '?'}'s turn")
    return True


def slot_label(meta: dict) -> str:
    """One menu row: round, actor and wall-clock time."""
    when = time.strftime("%H:%M:%S", time.localtime(meta.get("timestamp", 0)))
    return f"Round {meta.get('round', 0) + 1} · {meta.get('actor') or '?'} · {when}"
