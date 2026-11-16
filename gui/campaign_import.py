"""Old-shape scene files → the campaign layout (plans/NEW_DUNGEON_PLAN.md, D6).

The conversion pieces ``tools/migrate_layout.py`` used for the three hand-run campaign
migrations, moved here so New Dungeon can use them too. Stdlib only, like ``run_state``
and ``save_layout``: headless, no GUI.

An old scene is a roster (``<map>_agents.json``) and a terrain (``<map>_terrain.json``).
The terrain splits into map facts, page extras and play state (``run_state.split_terrain``);
the roster splits into an encounter definition (its non-PC creatures), a run section
(every creature) and PC records.

``new_dungeon`` (step 2) is New Dungeon's writer: a loose map's art, terrain and roster
into a campaign dungeon (D2), or a map from the campaign's library into a new dungeon of
that campaign (D5). Copy, never move (U1): the source files are only read.
"""

from __future__ import annotations

import copy
import filecmp
import json
import os
import shutil
from dataclasses import dataclass, field

import run_state as rs
import save_layout as sl
from atomic_io import atomic_write_json
from constants import PC_FACTION
from dungeon import Dungeon
from net.roster import SessionRoster

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


def pc_record(agent: dict) -> dict:
    """A PC's record for ``pcs/``: the agent without its placement keys, since the record
    is who the PC is, not where it was saved."""
    rec = copy.deepcopy(agent)
    for k in PLACEMENT_KEYS:
        rec.pop(k, None)
    return rec


def pc_records(paths, pc_names) -> dict:
    """``{name: (agent record, source path)}``, each from the newest file that has that
    PC (first match within a file)."""
    found = {}
    for p in sorted(paths, key=os.path.getmtime, reverse=True):
        for a in read_json(p).get("agents", []) or []:
            n = a.get("name")
            if n in pc_names and n not in found:
                found[n] = (pc_record(a), p)
    return found


def pc_names_in(agents_doc: dict) -> list[str]:
    """The roster's PCs (U3: ``faction == PC_FACTION``), in roster order, each once."""
    out = []
    for a in agents_doc.get("agents", []) or []:
        n = a.get("name")
        if a.get("faction") == PC_FACTION and n and n not in out:
            out.append(n)
    return out


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


# ── New Dungeon (step 2) ─────────────────────────────────────────────────────
INITIAL_ENCOUNTER = "initial"


@dataclass
class Scene:
    """A loose map as New Dungeon finds it: the art, the terrain and roster documents (as
    the app holds them), the grid size, and the paths of its lighting and session sidecars
    when it has them."""
    image: str
    terrain: dict
    agents: dict
    cols: int = 0
    rows: int = 0
    lighting: str | None = None
    session: str | None = None


@dataclass
class NewDungeon:
    """What ``new_dungeon`` made. ``pcs_kept`` are PCs the campaign already had a sheet for
    and that were left alone (D4); ``pcs_written`` got a sheet from the map."""
    layout: sl.DungeonLayout
    map_name: str
    pcs_written: list[str] = field(default_factory=list)
    pcs_kept: list[str] = field(default_factory=list)

    @property
    def manifest_path(self) -> str:
        return self.layout.manifest_path


def pc_conflicts(campaign_root: str, agents_doc: dict) -> list[str]:
    """The roster's PCs that already have a sheet in the campaign's ``pcs/`` (D4: the
    dialog asks once whether to update them). Empty when the folder is no campaign yet."""
    if not os.path.isfile(os.path.join(campaign_root, sl.CAMPAIGN_FILE)):
        return []
    camp = sl.Campaign(os.path.abspath(campaign_root))
    return [n for n in pc_names_in(agents_doc) if os.path.isfile(camp.pc_path(n))]


def _library_slot(camp: sl.Campaign, image: str) -> tuple[str, bool]:
    """``(map name, reused)`` for a loose map's art in the campaign library (D2): the
    image's slug when that is free, the existing map when it holds the same bytes, else
    the first free ``-2``, ``-3``, …"""
    seed = os.path.splitext(os.path.basename(image))[0]
    taken = set()
    while True:
        name = sl.unique_slug(seed, taken)
        have = sl.find_image(camp.library_map_dir(name), name)
        if have is None and not os.path.exists(camp.library_map_dir(name)):
            return name, False
        if have is not None and filecmp.cmp(have, image, shallow=False):
            return name, True
        taken.add(name)


def _same_json(path: str, doc) -> bool:
    try:
        return read_json(path) == doc
    except (OSError, ValueError):
        return False


def _place_map_file(camp, layout, map_name, filename, doc=None, src=None) -> None:
    """Write a map's ``map.json`` / ``lighting.json`` (a document, or a file to copy) to
    the library when it has none, else to the dungeon's own copy when it differs from the
    library's (copy-on-write, save-layout D3), so another dungeon's map never changes."""
    if doc is None:
        doc = read_json(src)
    lib = os.path.join(camp.library_map_dir(map_name), filename)
    if not os.path.isfile(lib):
        atomic_write_json(lib, doc)
    elif not _same_json(lib, doc):
        atomic_write_json(layout.write_path(map_name, filename), doc)


def new_dungeon(campaign_root: str, name: str, scene: Scene | None = None, *,
                library_map: str | None = None, cols: int = 0, rows: int = 0,
                campaign_name: str | None = None, update_pcs=()) -> NewDungeon:
    """Make a campaign dungeon of one map (plans/NEW_DUNGEON_PLAN.md D2 / D5).

    ``campaign_root`` is made a campaign (named ``campaign_name``) when it is not one yet.
    The dungeon's folder is ``name`` slugified, ``-2``, ``-3`` when taken.

    * ``scene`` (D2): a loose map. Its art goes to the library (reused when the library
      has the same bytes), its map facts to ``map.json``, its staircases / door links /
      staging cells to the page, its fog and doors and every creature to ``runs/main``,
      its non-PC creatures also to ``encounters/initial.json``, and its PCs to ``pcs/``.
      A PC that already has a sheet keeps it unless named in ``update_pcs`` (D4).
    * ``library_map`` (D5): a map already in the library; the dungeon gets only its
      ``dungeon.json`` and an empty run. ``cols`` / ``rows`` size the page (0: filled in
      when the app first opens the map).

    The campaign's ``session.json`` is made when missing: the scene's own session when it
    has one (its seats are what the creatures' controllers name), else a fresh table.
    ``dungeon.json`` is written last, so a failure part way leaves no openable dungeon."""
    if (scene is None) == (library_map is None):
        raise ValueError("new_dungeon takes a scene or a library map, not both or neither")
    sl.slugify(name)                       # a bad name is refused before anything is made
    root = os.path.abspath(campaign_root)
    if os.path.isfile(os.path.join(root, sl.CAMPAIGN_FILE)):
        camp = sl.Campaign(root)
    else:
        camp = sl.Campaign.create(root, campaign_name)
    slug = sl.unique_slug(name, os.listdir(camp.root))
    layout = camp.dungeon(slug)

    if library_map is not None:
        if library_map not in camp.list_library_maps():
            raise ValueError(f"{camp.name} has no map {library_map!r} in its library")
        map_name, extras, run = library_map, {}, rs.new_run(library_map)
        out = NewDungeon(layout, map_name)
    else:
        map_name, reused = _library_slot(camp, scene.image)
        if not reused:
            dst = os.path.join(camp.library_map_dir(map_name),
                               map_name + os.path.splitext(scene.image)[1].lower())
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(scene.image, dst)
        map_doc, extras, state = rs.split_terrain(scene.terrain)
        _place_map_file(camp, layout, map_name, sl.MAP_FILE, doc=map_doc)
        if scene.lighting and os.path.isfile(scene.lighting):
            _place_map_file(camp, layout, map_name, sl.LIGHTING_FILE, src=scene.lighting)

        pcs = pc_names_in(scene.agents)
        enc = encounter_doc(scene.agents, pcs)
        if enc["agents"]:
            atomic_write_json(layout.encounter_path(map_name, INITIAL_ENCOUNTER), enc)
        run = rs.new_run(map_name)
        run_section_from(run, map_name, scene.agents, state, pcs,
                         encounter=INITIAL_ENCOUNTER if enc["agents"] else None)

        out = NewDungeon(layout, map_name)
        update = set(update_pcs or ())
        agents = {a.get("name"): a for a in reversed(scene.agents.get("agents", []) or [])}
        for n in pcs:
            path = camp.pc_path(n)
            if os.path.isfile(path) and n not in update:
                out.pcs_kept.append(n)
                continue
            atomic_write_json(path, pc_record(agents[n]))
            out.pcs_written.append(n)
        cols, rows = scene.cols, scene.rows

    if not os.path.isfile(camp.session_path):
        if scene is not None and scene.session and os.path.isfile(scene.session):
            atomic_write_json(camp.session_path, read_json(scene.session))
        else:
            SessionRoster().save(camp.session_path)

    rs.save_run(layout.run_path(), run)
    dung = Dungeon.single_map(map_name, cols, rows)
    page = dung.pages[0]
    page.ladders = copy.deepcopy(extras.get("ladders", []) or [])
    page.door_links = copy.deepcopy(extras.get("door_links", []) or [])
    page.staging_cells = copy.deepcopy(extras.get("staging_cells")) or None
    dung.save(layout.manifest_path)
    return out
