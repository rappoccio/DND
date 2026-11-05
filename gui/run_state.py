"""Map facts, dungeon facts and play state (plans/SAVE_LAYOUT_PLAN.md D3–D6).

Stdlib only. The app today keeps one ``_terrain.json`` per scene that mixes three kinds
of data; the new layout stores each where it belongs:

  * **map** (``maps/<map>/map.json``, D2/D3): what the drawing is. Grid, detection,
    walls, edge overrides, painted regions, the generator's room plan, and the doors:
    where each one is and its designed state (open, locked, DCs).
  * **page** (the map's entry in ``dungeon.json``, D4): what spans maps or is dungeon
    design. Ladders, door staples (a door's cells and its global landing) and the
    staging room.
  * **state** (the map's section of ``run.json``, D6): what happened in play. Fog, and
    each door's open / locked / broken now.

``split_terrain`` takes a terrain document in the old ``_terrain.json`` shape apart, and
``merge_terrain`` puts one back together, so the app's terrain load/save keeps working on
the same dict while the files change underneath it.

A door is matched between map and state by its **key**, its edges or its cells, never by
its index, so a map edit that adds or removes a door leaves the other doors' state alone.

The run (``runs/<run>/run.json``) holds every map's creatures and state:

    {"version": 1, "current_map": "<map>",
     "maps": {"<map>": {"agents": [...], "map_items": [...], "active_conditions": [...],
                        "state": {"explored": [[c, r], ...], "doors": [...]},
                        "effects": {...}}}}

``agents`` / ``map_items`` / ``active_conditions`` are exactly what ``_agents.json`` holds,
so a map's section is read and written by the existing agent code. An encounter file
(``maps/<map>/encounters/<name>.json``, D5) has that same shape; adding one to a run
appends its creatures, each tagged ``"encounter": <name>``.
"""

from __future__ import annotations

import copy
import json

from atomic_io import atomic_write_json

RUN_VERSION = 1

# Terrain keys that describe the drawing, copied to map.json as they are.
MAP_KEYS = ("regions", "walls_enabled", "manual_grid", "detection", "edge_overrides",
            "edge_review", "edges_carried_from", "rooms")
# Door fields: the designed door (map.json) and what play changes (run.json).
DOOR_DESIGN = ("open", "locked", "lock_dc", "arcane_lock", "break_dc")
DOOR_STATE = ("open", "locked", "broken")
_DOOR_DEFAULTS = {"open": False, "locked": False, "lock_dc": 15, "arcane_lock": False,
                  "break_dc": 15, "broken": False}


# ── Doors ────────────────────────────────────────────────────────────────────
def _door_geometry(door: dict) -> dict:
    """The fields that say where a door is: ``edges`` for an edge door, else ``cells``
    (plus the legacy single ``cell``)."""
    if door.get("edges"):
        return {"edges": [[int(e[0]), int(e[1]), str(e[2])] for e in door["edges"]]}
    cells = door.get("cells") or ([door["cell"]] if door.get("cell") else [])
    cells = [[int(c[0]), int(c[1])] for c in cells]
    return {"cells": cells, "cell": cells[0]} if cells else {"cells": []}


def door_key(door: dict) -> tuple:
    """A door's identity: its sorted edges, else its sorted cells."""
    g = _door_geometry(door)
    if "edges" in g:
        return ("edges",) + tuple(sorted(tuple(e) for e in g["edges"]))
    return ("cells",) + tuple(sorted(tuple(c) for c in g["cells"]))


def _cells_key(cells) -> tuple:
    return ("cells",) + tuple(sorted((int(c[0]), int(c[1])) for c in cells))


# ── Terrain ⇄ map / page / state ─────────────────────────────────────────────
def split_terrain(terrain: dict, design: dict | None = None) -> tuple[dict, dict, dict]:
    """``(map_doc, page_extras, state)`` from an old-shape terrain document.

    ``page_extras`` is ``{"ladders", "door_links", "staging_cells"}`` for the map's
    ``dungeon.json`` entry. ``design`` is the map.json already on disk, if any: a door it
    has keeps its designed open/locked/DCs there, so opening a door in play changes the
    run and never the map. A door it lacks (a new one) takes its current state as its
    design."""
    t = terrain or {}
    map_doc = {k: copy.deepcopy(t[k]) for k in MAP_KEYS if k in t}
    designed = {door_key(d): d for d in (design or {}).get("doors", []) or []}
    doors, door_state, door_links = [], [], []
    for d in t.get("doors", []) or []:
        geom = _door_geometry(d)
        src = designed.get(door_key(d), d)
        doors.append({**geom, **{f: src.get(f, _DOOR_DEFAULTS[f]) for f in DOOR_DESIGN}})
        door_state.append({**geom, **{f: d.get(f, _DOOR_DEFAULTS[f]) for f in DOOR_STATE}})
        lt = d.get("link_target")
        if lt and "cells" in geom:
            door_links.append({"cells": geom["cells"], "target": [int(v) for v in lt[:3]]})
    map_doc["doors"] = doors
    extras = {
        "ladders": copy.deepcopy(t.get("ladders", []) or []),
        "door_links": door_links,
        "staging_cells": copy.deepcopy(t.get("staging_cells")) or None,
    }
    state = {"doors": door_state}
    if t.get("explored") is not None:
        state["explored"] = copy.deepcopy(t["explored"])
    return map_doc, extras, state


def merge_terrain(map_doc: dict | None, extras: dict | None = None,
                  state: dict | None = None) -> dict:
    """An old-shape terrain document from the three parts. A door takes its play state
    when the run has one for it, else its designed state; a state entry for a door the map
    no longer has is dropped. No ``explored`` in the state ⇒ no key ⇒ fully fogged."""
    m, x, s = map_doc or {}, extras or {}, state or {}
    t = {k: copy.deepcopy(m[k]) for k in MAP_KEYS if k in m}
    played = {door_key(d): d for d in s.get("doors", []) or []}
    links = {_cells_key(dl["cells"]): dl["target"] for dl in x.get("door_links", []) or []}
    doors = []
    for d in m.get("doors", []) or []:
        geom = _door_geometry(d)
        rec = {**geom, **{f: d.get(f, _DOOR_DEFAULTS[f]) for f in DOOR_DESIGN},
               "broken": False}
        now = played.get(door_key(d))
        if now is not None:
            rec.update({f: now.get(f, rec[f]) for f in DOOR_STATE})
        rec["link_target"] = (list(links[door_key(d)])
                              if "cells" in geom and door_key(d) in links else None)
        doors.append(rec)
    t["doors"] = doors
    t["ladders"] = copy.deepcopy(x.get("ladders", []) or [])
    if x.get("staging_cells"):
        t["staging_cells"] = copy.deepcopy(x["staging_cells"])
    if s.get("explored") is not None:
        t["explored"] = copy.deepcopy(s["explored"])
    return t


# ── Runs ─────────────────────────────────────────────────────────────────────
def new_run(current_map: str | None = None) -> dict:
    return {"version": RUN_VERSION, "current_map": current_map, "maps": {}}


def map_section(run: dict, map_name: str) -> dict:
    """The run's section for a map, created empty on first use."""
    sec = run.setdefault("maps", {}).setdefault(map_name, {})
    sec.setdefault("agents", [])
    sec.setdefault("map_items", [])
    sec.setdefault("active_conditions", [])
    sec.setdefault("state", {})
    return sec


def creatures(run: dict, map_name: str) -> dict:
    """A map's creatures in ``_agents.json`` shape (a deep copy)."""
    sec = (run.get("maps") or {}).get(map_name) or {}
    return {"agents": copy.deepcopy(sec.get("agents", [])),
            "map_items": copy.deepcopy(sec.get("map_items", [])),
            "active_conditions": copy.deepcopy(sec.get("active_conditions", []))}


def set_creatures(run: dict, map_name: str, doc: dict) -> None:
    """Replace a map's creatures with an ``_agents.json``-shape document."""
    sec = map_section(run, map_name)
    for k in ("agents", "map_items", "active_conditions"):
        sec[k] = copy.deepcopy(doc.get(k, []) or [])


def add_encounter(run: dict, map_name: str, encounter: dict, name: str) -> int:
    """Append an encounter's creatures, map items and conditions to a map's section,
    tagging each creature with ``encounter`` = ``name``. Each creature keeps its own
    ``on_deck``. A condition's ``agent_idx`` / ``caster_idx`` index the encounter's list,
    so they are shifted past the creatures already there. Returns the creatures added."""
    sec = map_section(run, map_name)
    base = len(sec["agents"])
    added = [a for a in encounter.get("agents", []) or [] if isinstance(a, dict)]
    for a in added:
        rec = copy.deepcopy(a)
        rec["encounter"] = name
        sec["agents"].append(rec)
    sec["map_items"] += [copy.deepcopy(m) for m in encounter.get("map_items", []) or []
                         if isinstance(m, dict)]
    for cd in encounter.get("active_conditions", []) or []:
        if not isinstance(cd, dict):
            continue
        rec = copy.deepcopy(cd)
        rec["agent_idx"] = int(rec.get("agent_idx", -1)) + base
        caster = int(rec.get("caster_idx", -1))
        rec["caster_idx"] = caster + base if caster >= 0 else -1
        sec["active_conditions"].append(rec)
    return len(added)


def load_run(path: str) -> dict:
    with open(path) as f:
        run = json.load(f)
    if int(run.get("version", 0)) != RUN_VERSION:
        raise ValueError(f"{path}: unsupported run version {run.get('version')!r}")
    run.setdefault("maps", {})
    run.setdefault("current_map", None)
    return run


def save_run(path: str, run: dict) -> None:
    atomic_write_json(path, run)
