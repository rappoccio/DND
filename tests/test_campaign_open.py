#!/usr/bin/env python3
"""Opening and playing a campaign dungeon: step 5b of plans/SAVE_LAYOUT_PLAN.md.

A headless App on a fixture campaign with a two-map dungeon (``hall`` on z=0, ``tower``
on z=1), both maps' art and map.json in the campaign library:

  · a campaign folder, a dungeon folder and a dungeon.json all resolve to the dungeon,
    opening on the run's current map (else the entry map);
  · the scene loads from map.json (its grid and door) through a CampaignStore;
  · creatures are saved into run.json, never into ``*_agents.json`` files;
  · opening a door changes the run's door state and never map.json; editing the map
    writes the dungeon's copy of map.json and leaves the library's alone (D3);
  · a page switch keeps each map's creatures and moves the run's current map, and a map
    the dungeon had not measured learns its size;
  · a fresh App reopens the run where it was left.
"""

import os
import sys
import json
import shutil
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

import main as app_main
import run_state as rs
import save_layout as sl
from main import App
from dungeon import Dungeon, MapPage
from scene_store import CampaignStore

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
DOOR = {"cells": [[4, 4]], "cell": [4, 4], "open": False, "locked": False,
        "lock_dc": 15, "arcane_lock": False, "break_dc": 15}


def _png(path):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    for x in range(0, COLS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (x, 0), (x, ROWS * CELL), 1)
    for y in range(0, ROWS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (0, y), (COLS * CELL, y), 1)
    pygame.image.save(surf, path)


def _campaign(tmp):
    camp = sl.Campaign.create(os.path.join(tmp, "Test Campaign"))
    for m in ("hall", "tower"):
        d = camp.library_map_dir(m)
        os.makedirs(d)
        _png(os.path.join(d, m + ".png"))
        with open(os.path.join(d, sl.MAP_FILE), "w") as f:
            json.dump({"regions": [], "walls_enabled": False, "manual_grid": GRID,
                       "doors": [DOOR] if m == "hall" else []}, f)
    dl = camp.dungeon("keep")
    os.makedirs(dl.root)
    hall = MapPage("hall", "", "", [0, 0, 0], 0, 0)          # unmeasured, as migrated
    tower = MapPage("tower", "", "", [0, 0, 1], COLS, ROWS)
    Dungeon(pages=[hall, tower], entry_page_id="hall", version=2).save(dl.manifest_path)
    return camp, dl


def _open(path):
    png, manifest = app_main.resolve_start_path(path)
    app = App(png, seed=1)
    app._on_open_dungeon_chosen(manifest)
    return app


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = name, col, row, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)


def _names(app):
    return sorted(pt.name for pt in app.bm.placed_agents)


def _run(dl):
    return rs.load_run(dl.run_path())


def _stray_sidecars(root):
    return [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs
            if f.endswith(("_agents.json", "_terrain.json"))]


def test_start_paths():
    tmp = tempfile.mkdtemp(prefix="campaign_open_")
    try:
        camp, dl = _campaign(tmp)
        want = (os.path.join(camp.library_map_dir("hall"), "hall.png"), dl.manifest_path)
        os.makedirs(os.path.join(dl.root, "maps"))
        for p in (camp.root, dl.root, dl.manifest_path, os.path.join(dl.root, "maps")):
            assert app_main.resolve_start_path(p) == want, p
        os.makedirs(os.path.join(camp.root, "other"))
        Dungeon.single_map("tower").save(os.path.join(camp.root, "other", sl.DUNGEON_FILE))
        try:
            app_main.resolve_start_path(camp.root)
            assert False, "picked one of two dungeons"
        except ValueError as e:
            assert "keep" in str(e) and "other" in str(e)
        rs.save_run(dl.run_path(), {**rs.new_run("tower")})
        assert app_main.resolve_start_path(dl.root)[0].endswith("tower.png")
    finally:
        shutil.rmtree(tmp)
    print("  ✅ campaign / dungeon folder / dungeon.json resolve; run's map first")


def test_play_and_reopen():
    tmp = tempfile.mkdtemp(prefix="campaign_open_")
    try:
        camp, dl = _campaign(tmp)
        lib_hall = os.path.join(camp.library_map_dir("hall"), sl.MAP_FILE)
        with open(lib_hall) as f:
            lib_before = f.read()

        app = _open(camp.root)
        assert isinstance(app.store, CampaignStore)
        assert app.dungeon_page.id == "hall" and app.dungeon.version == 2
        assert (app.bm.grid_cols, app.bm.grid_rows) == (COLS, ROWS)
        assert len(app.bm.doors) == 1 and not app.bm.doors[0].open
        assert (app.dungeon_page.cols, app.dungeon_page.rows) == (COLS, ROWS)
        assert Dungeon.load(dl.manifest_path).page_by_id("hall").cols == COLS

        _place(app, "Sabalath", 1, 1)
        app._save_agents()
        assert [a["name"] for a in _run(dl)["maps"]["hall"]["agents"]] == ["Sabalath"]

        app.bm.open_door(app.bm.doors[0].id)
        app._save_terrain()
        run = _run(dl)
        assert run["maps"]["hall"]["state"]["doors"][0]["open"] is True
        assert not os.path.exists(dl.write_path("hall", sl.MAP_FILE))     # map untouched
        with open(lib_hall) as f:
            assert f.read() == lib_before

        app._walls_enabled = True                                         # a map edit
        app._save_terrain()
        with open(dl.write_path("hall", sl.MAP_FILE)) as f:
            local = json.load(f)
        assert local["walls_enabled"] is True and local["doors"][0]["open"] is False
        with open(lib_hall) as f:
            assert f.read() == lib_before                                 # library kept

        assert app._switch_to_page(app.dungeon.page_by_id("tower"))
        assert app.dungeon_page.id == "tower" and _names(app) == []
        _place(app, "Bat", 2, 2)
        app._save_agents()
        run = _run(dl)
        assert run["current_map"] == "tower"
        assert [a["name"] for a in run["maps"]["hall"]["agents"]] == ["Sabalath"]
        assert [a["name"] for a in run["maps"]["tower"]["agents"]] == ["Bat"]
        assert _stray_sidecars(camp.root) == []

        again = _open(dl.root)
        assert again.dungeon_page.id == "tower" and _names(again) == ["Bat"]
        assert again._switch_to_page(again.dungeon.page_by_id("hall"))
        assert _names(again) == ["Sabalath"]
        assert again.bm.doors[0].open and again._walls_enabled
    finally:
        shutil.rmtree(tmp)
    print("  ✅ play saves to run.json / the dungeon's map.json; a fresh App reopens it")


def test_version_1_leaves_campaign():
    tmp = tempfile.mkdtemp(prefix="campaign_open_")
    try:
        camp, dl = _campaign(tmp)
        app = _open(dl.manifest_path)
        old = os.path.join(tmp, "old")
        os.makedirs(old)
        _png(os.path.join(old, "p.png"))
        Dungeon(pages=[MapPage("p", "p.png", "p_agents.json", [0, 0, 0], COLS, ROWS)],
                entry_page_id="p").save(os.path.join(old, "p.dungeon.json"))
        app._on_open_dungeon_chosen(os.path.join(old, "p.dungeon.json"))
        assert not isinstance(app.store, CampaignStore)
        assert app.dungeon.version == 1 and app.dungeon_page.id == "p"
        app._save_agents()
        assert os.path.exists(os.path.join(old, "p_agents.json"))
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a version 1 dungeon opened from a campaign goes back to sidecar files")


def main():
    pygame.init()
    tests = [test_start_paths, test_play_and_reopen, test_version_1_leaves_campaign]
    print("Running campaign open tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} campaign open tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
