"""Old-shape scene files → the campaign layout (plans/NEW_DUNGEON_PLAN.md, D6).

The conversion pieces ``tools/migrate_layout.py`` used for the three hand-run campaign
migrations, moved here so New Dungeon can use them too. Stdlib only, like ``run_state``
and ``save_layout``: headless, no GUI.

An old scene is a roster (``<map>_agents.json``) and a terrain (``<map>_terrain.json``).
The terrain splits into map facts, page extras and play state (``run_state.split_terrain``);
the roster splits into an encounter definition (its non-PC creatures), a run section
(every creature) and PC records.
"""

from __future__ import annotations

import copy
import json
import os

import run_state as rs

# Top-level keys of an agents file that are creatures, not encounter metadata.
CREATURE_KEYS = ("agents", "map_items", "active_conditions")
# Keys an agent record picks up from where it was saved, not who it is.
PLACEMENT_KEYS = ("encounter", "page", "z")


def read_json(path: str):
    with open(path) as f:
        return json.load(f)


def split_terrain_file(terrain_path: str) -> tuple[dict, dict, dict]:
    """``(map_doc, page_extras, state)`` from a terrain file on disk."""
    return rs.split_terrain(read_json(terrain_path))


def norm_terrain(t: dict) -> dict:
    """A terrain doc with door defaults filled, for comparing old against rebuilt."""
    m, x, s = rs.split_terrain(t)
    out = rs.merge_terrain(m, x, s)
    for k in ("ladders", "staging_cells"):
        if not out.get(k):
            out.pop(k, None)
    return out


def rebuild_diff(old_terrain: dict, map_doc: dict, extras: dict, state: dict) -> list[str]:
    """The terrain keys on which the three parts, merged back, differ from the old
    terrain. Empty ⇒ the split lost nothing."""
    old = norm_terrain(old_terrain)
    new = norm_terrain(rs.merge_terrain(map_doc, extras, state))
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


def pc_records(paths, pc_names) -> dict:
    """``{name: (agent record, source path)}``, each from the newest file that has that
    PC (first match within a file). Placement keys are dropped: the record is who the PC
    is, not where it was saved."""
    found = {}
    for p in sorted(paths, key=os.path.getmtime, reverse=True):
        for a in read_json(p).get("agents", []) or []:
            n = a.get("name")
            if n in pc_names and n not in found:
                rec = copy.deepcopy(a)
                for k in PLACEMENT_KEYS:
                    rec.pop(k, None)
                found[n] = (rec, p)
    return found


def encounter_doc(agents_doc: dict, pc_names) -> dict:
    """An encounter definition from a roster: its non-PC creatures and its generator
    metadata. Map items and conditions are play state; they stay in the run."""
    doc = {k: copy.deepcopy(v) for k, v in agents_doc.items() if k not in CREATURE_KEYS}
    doc["agents"] = [copy.deepcopy(a) for a in agents_doc.get("agents", []) or []
                     if a.get("name") not in pc_names]
    doc["map_items"], doc["active_conditions"] = [], []
    return doc


def run_section_from(run: dict, map_name: str, agents_doc: dict, state: dict, pc_names,
                     encounter: str | None = None) -> None:
    """A run's section for a map from an old roster + terrain state. Non-PC creatures
    are tagged with ``encounter`` when the map got one from this roster."""
    doc = {k: copy.deepcopy(agents_doc.get(k, []) or []) for k in CREATURE_KEYS}
    if encounter:
        for a in doc["agents"]:
            if a.get("name") not in pc_names:
                a["encounter"] = encounter
    rs.set_creatures(run, map_name, doc)
    rs.map_section(run, map_name)["state"] = state


def merged_session(paths) -> dict:
    """One campaign session from several per-encounter ones (save-layout D9): the newest
    file's join code and settings, and every principal any of them seated (by id, newest
    first), so the creatures' controllers all still name a seat."""
    paths = sorted((p for p in paths if os.path.isfile(p)), key=os.path.getmtime,
                   reverse=True)
    doc = copy.deepcopy(read_json(paths[0]))
    seen, principals, revoked = set(), [], []
    for p in paths:
        d = read_json(p)
        for pr in d.get("principals", []) or []:
            if pr.get("id") not in seen:
                seen.add(pr.get("id"))
                principals.append(pr)
        revoked += [r for r in d.get("revoked", []) or [] if r not in revoked]
    doc["principals"], doc["revoked"] = principals, revoked
    return doc
