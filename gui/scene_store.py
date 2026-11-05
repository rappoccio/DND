"""Where a scene's terrain and creatures are read and written (SAVE_LAYOUT_PLAN.md step 5).

The app reads and writes a scene as two documents: **terrain** (the old
``_terrain.json`` shape: grid, walls, doors, ladders, fog, …) and **creatures** (the
old ``_agents.json`` shape: ``agents``, ``map_items``, ``active_conditions``). Everything
in ``main.py`` that loads or saves either goes through ``app.store``, so where they live
on disk is decided here, once:

  * ``CampaignStore``: the new layout (D3–D6). Terrain is put together from the map's
    ``map.json`` (the dungeon's copy, else the library's), its entry in ``dungeon.json``
    (ladders, door staples, staging room) and its section of the run (fog, door state),
    and taken apart again on a write. Creatures are the map's section of ``run.json``.
  * ``LegacyStore``: today's per-encounter sidecars, ``<base>_terrain.json`` and
    ``<base>_agents.json`` beside the map, one pair per dungeon page. Kept only until the
    suite moves to the fixture campaign (D11).

A ``page`` argument names a dungeon page other than the one showing; ``None`` (or the
page showing) means the current scene.

``terrain`` / ``creatures`` return ``None`` when the scene has no saved document, and
raise ``ValueError`` for one that cannot be read.
"""

from __future__ import annotations

import json
import os

import run_state as rs
import save_layout as sl
from atomic_io import atomic_write_json


def _read_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except OSError as e:
        raise ValueError(f"could not read {os.path.basename(path)}: {e}") from e


class LegacyStore:
    """Per-encounter sidecar files (the layout being retired)."""

    def __init__(self, app):
        self.app = app

    def _current(self, page) -> bool:
        cur = self.app.dungeon_page
        return page is None or (cur is not None and page.id == cur.id)

    def terrain_path(self, page=None) -> str:
        return (self.app._terrain_path if self._current(page)
                else self.app._page_terrain_path(page))

    def agents_path(self, page=None) -> str:
        return (self.app._save_path if self._current(page)
                else self.app._page_agents_path(page))

    # ── Terrain ───────────────────────────────────────────────────────────
    def has_terrain(self, page=None) -> bool:
        return os.path.exists(self.terrain_path(page))

    def terrain(self, page=None):
        return _read_json(self.terrain_path(page))

    def write_terrain(self, doc, page=None) -> None:
        atomic_write_json(self.terrain_path(page), doc)

    # ── Creatures ─────────────────────────────────────────────────────────
    def has_creatures(self, page=None) -> bool:
        return os.path.exists(self.agents_path(page))

    def creatures(self, page=None):
        return _read_json(self.agents_path(page))

    def write_creatures(self, doc, page=None) -> None:
        atomic_write_json(self.agents_path(page), doc)

    # ── Art and other per-map files ───────────────────────────────────────
    def image(self, page) -> str:
        return self.app._page_png_path(page)

    def lighting_read_path(self, page=None) -> str:
        return self.app._lighting_path


class CampaignStore:
    """A run of a dungeon in a campaign (plans/SAVE_LAYOUT_PLAN.md D3–D6).

    The run document is held in memory and written whole on every change; ``map.json``
    is written to the dungeon's copy (D3) only when its content changed, and
    ``dungeon.json`` only when a map's ladders, staples or staging room changed."""

    def __init__(self, app, layout: "sl.DungeonLayout", run_name: str = sl.DEFAULT_RUN):
        self.app = app
        self.layout = layout
        self.run_name = run_name
        path = layout.run_path(run_name)
        self.run = rs.load_run(path) if os.path.exists(path) else rs.new_run()
        # The map the app's scene paths point at (``point_at``). It changes before the
        # app's ``dungeon_page`` does: a page switch loads the new scene first.
        self.page = None

    @property
    def campaign(self) -> "sl.Campaign":
        return self.layout.campaign

    def _page(self, page):
        if page is not None:
            return page
        if self.page is None:
            raise ValueError("no map is showing")
        return self.page

    def point_at(self, page) -> dict:
        """Make ``page`` the current scene; returns the App's paths for it."""
        self.page = page
        self.set_current_map(page.id)
        return self.scene_paths(page)

    def save_run(self) -> None:
        rs.save_run(self.layout.run_path(self.run_name), self.run)

    def set_current_map(self, map_name: str) -> None:
        if self.run.get("current_map") != map_name:
            self.run["current_map"] = map_name
            self.save_run()

    # ── Terrain ───────────────────────────────────────────────────────────
    def _map_doc(self, map_name):
        return _read_json(self.layout.resolve(map_name, sl.MAP_FILE))

    def has_terrain(self, page=None) -> bool:
        p = self._page(page)
        return (self.layout.resolve(p.id, sl.MAP_FILE) is not None
                or bool((self.run.get("maps") or {}).get(p.id, {}).get("state")))

    def terrain(self, page=None):
        p = self._page(page)
        extras = {"ladders": p.ladders, "door_links": p.door_links,
                  "staging_cells": p.staging_cells}
        state = (self.run.get("maps") or {}).get(p.id, {}).get("state")
        map_doc = self._map_doc(p.id)
        if map_doc is None and not state and not p.ladders and not p.door_links:
            return None
        return rs.merge_terrain(map_doc or {}, extras, state)

    def write_terrain(self, doc, page=None) -> None:
        p = self._page(page)
        old_map = self._map_doc(p.id)
        map_doc, extras, state = rs.split_terrain(doc, old_map)
        if map_doc != old_map:
            atomic_write_json(self.layout.write_path(p.id, sl.MAP_FILE), map_doc)
        if (extras["ladders"], extras["door_links"], extras["staging_cells"]) != \
                (p.ladders, p.door_links, p.staging_cells):
            p.ladders = extras["ladders"]
            p.door_links = extras["door_links"]
            p.staging_cells = extras["staging_cells"]
            self.app.dungeon.save(self.layout.manifest_path)
        rs.map_section(self.run, p.id)["state"] = state
        self.save_run()

    # ── Creatures ─────────────────────────────────────────────────────────
    def has_creatures(self, page=None) -> bool:
        return self._page(page).id in (self.run.get("maps") or {})

    def creatures(self, page=None):
        p = self._page(page)
        if p.id not in (self.run.get("maps") or {}):
            return None
        return rs.creatures(self.run, p.id)

    def write_creatures(self, doc, page=None) -> None:
        rs.set_creatures(self.run, self._page(page).id, doc)
        self.save_run()

    # ── Art and other per-map files ───────────────────────────────────────
    def image(self, page) -> str:
        return self.layout.image(page.id) or ""

    def lighting_read_path(self, page=None) -> str:
        """The lighting to read: the dungeon's copy, else the library's (or the write
        path, which does not exist yet)."""
        p = self._page(page)
        return (self.layout.resolve(p.id, sl.LIGHTING_FILE)
                or self.layout.write_path(p.id, sl.LIGHTING_FILE))

    def scene_paths(self, page) -> dict:
        """The App's per-scene paths for ``page`` in this run. ``agents`` / ``terrain``
        name no file: they are the identities the app compares against to mean "this
        scene", and the store intercepts every read and write of them. ``lighting`` is
        where a lighting save goes (the dungeon's copy); the rest are real files."""
        run_dir = self.layout.run_dir(self.run_name)
        return {
            "agents":   os.path.join(run_dir, f"{page.id}_agents.json"),
            "terrain":  os.path.join(run_dir, f"{page.id}_terrain.json"),
            "lighting": self.layout.write_path(page.id, sl.LIGHTING_FILE),
            "effects":  os.path.join(run_dir, "effects", f"{page.id}.json"),
            "combat":   self.layout.combat_path(self.run_name),
            "session":  self.campaign.session_path,
        }
