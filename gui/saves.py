"""Save files: one point in a run, kept by turn or by hand (plans/DUNGEON_RELEASES_PLAN.md
D5–D8).

    runs/<run>/saves/000042.save.json.gz
        {"version", "meta", "run", "combat", "effects"}

``meta`` says when and where: kind, seq, fight, round, turn index, actor, map, time.
``run`` is the whole run with the showing map's section taken from the live board, so a save
can return to any map. ``combat`` is the fight, or null. ``effects`` is each map's effects
file. Terrain and lighting are not saved: they are design, and a load always rests on the
current design (D7).

A save is one file, written to a hidden name and renamed, so it appears whole or not at all.
``index.jsonl`` only spares a listing from opening every file. The save files are the truth:
an entry with no file is dropped and a file with no entry is read, so the index can be lost.

Writing a save reads the live board and never touches the DM's run or scene files. Turn saves
past ``roster.save_limit`` are pruned, oldest first; manual and before-reset saves stay and do
not count (D8).
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import time

import autosave
import run_state as rs
from atomic_io import atomic_write_json
from scene_store import CampaignStore

SAVE_VERSION = 1
SAVE_EXT = ".save.json.gz"
INDEX_FILE = "index.jsonl"

TURN = "turn"
MANUAL = "manual"
BEFORE_RESET = "before reset"
BEFORE_UNDO = "before undo"           # Undo Reset's way back, as BEFORE_RESET is a reset's

# What a mid-turn Save Game keeps of the turn: the panel's own copy of the action economy.
# Half-finished picks are dropped. A turn save has these all fresh anyway.
_ECONOMY = ("action_used", "bonus_used", "attacks_remaining", "_attack_sequence_slot")


# ── The files ────────────────────────────────────────────────────────────────
def _save_path(directory: str, seq: int) -> str:
    return os.path.join(directory, f"{seq:06d}{SAVE_EXT}")


def _seq_of(filename: str) -> int | None:
    stem = filename[:-len(SAVE_EXT)]
    return int(stem) if filename.endswith(SAVE_EXT) and stem.isdigit() else None


def _read_doc(path: str) -> dict:
    """A save file's document. Raises ValueError or OSError for one that cannot be used."""
    try:
        with gzip.open(path, "rt") as f:
            doc = json.load(f)
    except EOFError as e:
        raise ValueError(f"truncated: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("meta"), dict):
        raise ValueError("not a save file")
    if int(doc.get("version", 0)) > SAVE_VERSION:
        raise ValueError("written by a newer version")
    return doc


def _write_doc(path: str, doc: dict) -> None:
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.tmp.{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(gzip.compress(json.dumps(doc).encode(), compresslevel=1))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_index(directory: str) -> dict[int, dict]:
    entries = {}
    try:
        with open(os.path.join(directory, INDEX_FILE)) as f:
            for line in f:
                try:
                    meta = json.loads(line)
                    entries[int(meta["seq"])] = meta
                except (ValueError, KeyError, TypeError):
                    continue          # a torn last line: its file is read instead
    except OSError:
        pass
    return entries


def _write_index(directory: str, metas: list[dict]) -> None:
    tmp = os.path.join(directory, f".{INDEX_FILE}.tmp.{os.getpid()}")
    with open(tmp, "w") as f:
        for meta in sorted(metas, key=lambda m: m["seq"]):
            f.write(json.dumps(meta) + "\n")
    os.replace(tmp, os.path.join(directory, INDEX_FILE))


def list_saves(directory: str) -> list[dict]:
    """Every readable save's meta, newest first. Repairs the index if it had to."""
    try:
        seqs = [s for s in map(_seq_of, os.listdir(directory)) if s is not None]
    except OSError:
        return []
    index = _read_index(directory)
    metas, stale = [], len(index) != len(seqs)
    for seq in seqs:
        meta = index.get(seq)
        if meta is None:
            stale = True
            try:
                meta = dict(_read_doc(_save_path(directory, seq))["meta"], seq=seq)
            except (OSError, ValueError):
                continue
        metas.append(meta)
    if stale:
        _write_index(directory, metas)
    return sorted(metas, key=lambda m: m["seq"], reverse=True)


def _prune(directory: str, metas: list[dict], limit: int) -> list[dict]:
    """Drop the oldest turn saves past ``limit``. ``metas`` is newest first."""
    keep, turns = [], 0
    for meta in metas:
        if meta.get("kind") == TURN:
            turns += 1
            if turns > limit:
                try:
                    os.remove(_save_path(directory, meta["seq"]))
                except FileNotFoundError:
                    pass
                continue
        keep.append(meta)
    return keep


# ── Writing ──────────────────────────────────────────────────────────────────
def _capture(app, store: CampaignStore) -> tuple[dict, dict | None]:
    """The whole run with the showing map's section from the live board, and the fight.
    The board's writers take a path, so they write to a temp folder, not the scene's files."""
    with tempfile.TemporaryDirectory(prefix="rpg_save_") as tmp:
        agents_path, terrain_path = os.path.join(tmp, "a.json"), os.path.join(tmp, "t.json")
        combat_path = os.path.join(tmp, "c.json")
        app._save_agents(agents_path, raw=bool(app.combat_active))
        app._save_terrain(terrain_path)
        with open(agents_path) as f:
            creatures = json.load(f)
        with open(terrain_path) as f:
            state = rs.split_terrain(json.load(f))[2]
        combat = None
        if app.combat_active:
            app._save_combat_state(combat_path)
            with open(combat_path) as f:
                combat = json.load(f)
    map_name = app.dungeon_page.id
    sections = dict(store.run.get("maps") or {})
    sections[map_name] = {**sections.get(map_name, {}), **creatures, "state": state}
    return {**store.run, "current_map": map_name, "maps": sections}, combat


def _read_effects(store: CampaignStore) -> dict:
    effects, folder = {}, store.layout.effects_dir(store.run_name)
    try:
        names = os.listdir(folder)
    except OSError:
        return effects
    for name in names:
        with open(os.path.join(folder, name)) as f:
            effects[name] = json.load(f)
    return effects


def write(app, kind: str) -> dict:
    """Write the live board as a new save and return its meta. Raises on failure."""
    store = app.store
    directory = store.layout.saves_dir(store.run_name)
    os.makedirs(directory, exist_ok=True)
    existing = list_saves(directory)
    seq = 1 + max((m["seq"] for m in existing), default=0)
    run, combat = _capture(app, store)
    idx = app._current_agent_idx() if app.combat_active else -1
    actor = (app.bm.placed_agents[idx].name
             if 0 <= idx < len(app.bm.placed_agents) else "")
    if app.combat_active and app._fight_started is None:
        app._fight_started = time.time()      # a fight resumed from before this session
    meta = {
        "seq":       seq,
        "kind":      kind,
        "fight":     app._fight_started,
        "round":     int(app.round_num),
        "turn_idx":  int(app.turn_idx),
        "actor":     actor,
        "map":       app.dungeon_page.id,
        "timestamp": time.time(),
    }
    economy = {k: getattr(app, k) for k in _ECONOMY} if app.combat_active else None
    _write_doc(_save_path(directory, seq),
               {"version": SAVE_VERSION, "meta": meta, "run": run, "combat": combat,
                "economy": economy, "effects": _read_effects(store)})
    metas = _prune(directory, [meta] + existing, app.roster.save_limit)
    _write_index(directory, metas)
    return meta


def save_turn(app) -> dict | None:
    """The turn hook. Never raises: a save that fails must not take the turn down with it."""
    if not (app.combat_active and isinstance(app.store, CampaignStore)):
        return None
    try:
        return write(app, TURN)
    except Exception as e:                       # noqa: BLE001 — see the docstring
        print(f"Warning: turn save failed: {e}")
        return None


def save_game(app) -> dict | None:
    """Save Game: in or out of a fight (D5). Refused while something is in flight, for the
    reasons a load would be."""
    if not isinstance(app.store, CampaignStore):
        app._flash_status("Only a campaign dungeon has save files.")
        return None
    why = autosave.restore_blocked(app)
    if why is not None:
        app._flash_status(f"Not saved: {why}")
        return None
    try:
        meta = write(app, MANUAL)
    except (OSError, ValueError) as e:
        app._flash_status(f"Could not save: {e}")
        return None
    app._flash_status(f"Saved: {label(meta)}")
    return meta


# ── Loading ──────────────────────────────────────────────────────────────────
def swap_run(app, run: dict, effects_dir: str | None, page, reload_map: bool = False) -> bool:
    """Make ``run`` the run and show ``page`` from it, on the current design. Any live fight
    ends without XP: it is being thrown away, not finished. The map being left is not
    written back, and the same map keeps its view unless ``reload_map`` (the design under it
    changed). The caller has checked ``page``'s image. Returns False with a flash when the
    disk refuses or the page will not load."""
    # A section for the map showing, even an empty one: with none, the load would leave the
    # old creatures on the board.
    rs.map_section(run, page.id)
    try:
        app.store.replace_run(run, effects_dir)
    except OSError as e:
        app._flash_status(f"Could not change the run: {e}")
        return False
    if app.combat_active:
        app._end_combat(award_xp=False)
    app._save_combat_state()              # no fight now, so this removes the sidecar
    from menus import dm                  # the run's tracker mode (INITIATIVE_TRACKER T6)
    dm.set_tracker_mode(app, bool(run.get("tracker_mode", False)))
    app.bm.clear_terrain_effects()
    app.bm.clear_spell_effects()
    app._effect_meta.clear()
    app._npc_drive_idx = -1
    app.selected_idx = -1
    if reload_map or (app.dungeon_page is not None and app.dungeon_page.id != page.id):
        app.dungeon_page = None
    return app._switch_to_page(page, force=True)


def _check(doc: dict, app) -> tuple[str | None, object]:
    """(why not, the page to show). Checks everything before the live scene is touched."""
    meta, run, combat = doc["meta"], doc.get("run"), doc.get("combat")
    if not isinstance(run, dict):
        return "it holds no run", None
    page = app.dungeon.page_by_id(meta.get("map"))
    if page is None:
        return f"this dungeon no longer has the map {meta.get('map')}", None
    if not app.store.image(page):
        return f"the map {page.id} has no image", None
    if combat is not None:
        names = [a.get("name") for a in rs.creatures(run, page.id)["agents"]]
        if combat.get("agent_basis") != names or not combat.get("initiative_order"):
            return "its creatures and its fight disagree", None
    return None, page


def _write_effects(effects: dict, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    for name, doc in effects.items():
        atomic_write_json(os.path.join(folder, os.path.basename(name)), doc)


def load(app, seq: int, reload_map: bool = False) -> bool:
    """Load save ``seq`` of the run into ``app``. Returns True when the save's board is up,
    with its fight running if it had one. A refusal flashes its reason and changes nothing,
    short of a fight the engine refuses after the load, which leaves the save's board with
    no fight (D7). ``reload_map`` re-reads the map from disk even when it is the one showing
    (Undo Reset has just changed the design under it)."""
    if not isinstance(app.store, CampaignStore):
        app._flash_status("Only a campaign dungeon has save files.")
        return False
    why = autosave.restore_blocked(app)
    doc, page = None, None
    if why is None:
        directory = app.store.layout.saves_dir(app.store.run_name)
        try:
            doc = _read_doc(_save_path(directory, seq))
            why, page = _check(doc, app)
        except (OSError, ValueError) as e:
            why = f"unreadable ({e})"
    if why is not None:
        app._flash_status(f"Save not loaded: {why}")
        return False

    meta, combat = doc["meta"], doc.get("combat")
    with tempfile.TemporaryDirectory(prefix="rpg_save_") as tmp:
        effects = os.path.join(tmp, "effects")
        _write_effects(doc.get("effects") or {}, effects)
        if not swap_run(app, doc["run"], effects, page, reload_map=reload_map):
            return False
        resumed = False
        if combat is not None:
            path = os.path.join(tmp, "combat.json")
            atomic_write_json(path, combat)
            resumed = app._load_combat_state(path, keep_design=True)
    if resumed:
        autosave.settle_turn(app)
        for k, v in (doc.get("economy") or {}).items():
            if k in _ECONOMY:
                setattr(app, k, v)
        app._fight_started = meta.get("fight")
        app._save_combat_state()          # the run on disk and its fight agree again
    autosave.resync_players(app)

    app._combat_log_add(f"[LOADED] save: {label(meta)}")
    app._flush_combat_log()
    # The table's line names no actor (D-M7-4), as a restore's does.
    where = f"round {meta.get('round', 0) + 1}" if combat is not None else "out of combat"
    app.session_log.add(f"The DM loaded a save from {where}.")
    if combat is not None and not resumed:
        return False                      # _load_combat_state has flashed why
    app._flash_status(f"Loaded: {label(meta)}")
    return True


def label(meta: dict) -> str:
    """One line for a save: where it is and when."""
    when = time.strftime("%H:%M:%S", time.localtime(meta.get("timestamp", 0)))
    if meta.get("actor"):
        text = f"Round {meta.get('round', 0) + 1} · {meta['actor']} · {when}"
    else:
        text = f"{meta.get('map', '?')} · {when}"
    kind = meta.get("kind")
    return f"{kind} · {text}" if kind in (BEFORE_RESET, BEFORE_UNDO) else text


def turn_label(meta: dict) -> str:
    """A turn's row inside its round: the round is already on the menu above it."""
    when = time.strftime("%H:%M:%S", time.localtime(meta.get("timestamp", 0)))
    return f"{meta.get('actor') or '?'} · {when}"


def fight_label(fight, turns: list[dict]) -> str:
    when = time.strftime("%b %-d %H:%M", time.localtime(fight or turns[-1].get("timestamp", 0)))
    return f"{when} · {len(turns)} turn{'' if len(turns) == 1 else 's'}"


def group(metas: list[dict]) -> tuple[list[dict], list[tuple[object, list[tuple[int, list[dict]]]]]]:
    """The picker's shape (D9), from ``list_saves``'s newest-first metas: the saves kept by
    hand, and the turn saves as ``[(fight, [(round, [meta, ...]), ...]), ...]``, each level
    newest first."""
    kept, fights = [], {}
    for meta in metas:
        if meta.get("kind") == TURN:
            fights.setdefault(meta.get("fight"), {}).setdefault(
                int(meta.get("round", 0)), []).append(meta)
        else:
            kept.append(meta)
    return kept, [(fight, sorted(rounds.items(), key=lambda kv: kv[0], reverse=True))
                  for fight, rounds in fights.items()]
