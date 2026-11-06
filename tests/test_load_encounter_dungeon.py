#!/usr/bin/env python3
"""Load Encounter on a dungeon page brings in creatures only.

Castle Ravenloft, 2026-10-23: loading encounters/simplemap_strahd_agents.json on a floor
re-pointed the page at the encounter's base, so the page took that file's grid and wall
regions, and its next save would have gone to the encounter's files. On a dungeon page,
Load Encounter now:

  · adds the file's creatures (and map items) to the page's own encounter, keeping the
    PCs already there but replacing its NPCs and any creature the file also brings
    (Nedragaard Keep, 2026-11-05: loading the mobs twice doubled every one of them);
  · leaves the page's grid, terrain regions, sidecar paths and the chosen file alone;
  · keeps a creature's saved cell when free, else the nearest free one (off-grid cells
    are pulled onto the grid);
  · and the creatures are still there after leaving the page and coming back.

Multi-floor encounter files (Save Encounter As / Load on a dungeon):

  · Save As writes every page's creatures to one file, each tagged with its page and z,
    re-points nothing, writes no sidecars beside it, and refuses a page's own file;
  · Load sends each tagged creature to its own page (a page that is not showing keeps the
    saved cell unless another creature holds it), skips pages the dungeon lacks, and moves
    a condition with its creature, re-indexed for that page's file.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from main import App
from dungeon import Dungeon, MapPage

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    for x in range(0, COLS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (x, 0), (x, ROWS * CELL), 1)
    for y in range(0, ROWS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (0, y), (COLS * CELL, y), 1)
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _dungeon(tmp):
    pages = []
    for pid, z in (("M", 0), ("U", 1)):
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            json.dump({"regions": [], "walls_enabled": False, "manual_grid": GRID}, f)
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    app = App(pages[0].png, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app, pages


def _encounter(tmp):
    """A stand-alone encounter with its own, different grid and a wall region."""
    d = os.path.join(tmp, "elsewhere")
    os.makedirs(d)
    agents = [{"name": "Hilaria", "size": 1, "col": 2, "row": 3, "faction": 2},
              {"name": "Keef", "size": 1, "col": 2, "row": 3, "faction": 2},     # same cell
              {"name": "Far Away", "size": 1, "col": 40, "row": 30, "faction": 2}]  # off-grid
    path = os.path.join(d, "strahd_agents.json")
    with open(path, "w") as f:
        json.dump({"agents": agents, "map_items": []}, f)
    terrain = {"regions": [{"type": "Wall", "x": 0, "y": 0, "width": 90, "height": 240,
                            "multiplier": 0.0}],
               "walls_enabled": True,
               "manual_grid": {"cell_px": 51, "anchor": [7, 9], "square_ft": 5}}
    with open(os.path.join(d, "strahd_terrain.json"), "w") as f:
        json.dump(terrain, f)
    return path


def _cells(app):
    return {pt.name: (pt.origin.col, pt.origin.row) for pt in app.bm.placed_agents}


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = name, col, row, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)


def test_creatures_only():
    with tempfile.TemporaryDirectory() as tmp:
        app, pages = _dungeon(tmp)
        _place(app, "Resident", 5, 5)
        paths = (app._save_path, app._terrain_path, app._lighting_path, app._effects_path)
        grid = (app.bm.grid_cols, app.bm.grid_rows, app.bm.cell_pixel_size)
        regions = json.dumps(app._terrain_regions, sort_keys=True)
        enc = _encounter(tmp)
        enc_before = {n: open(os.path.join(os.path.dirname(enc), n)).read()
                      for n in os.listdir(os.path.dirname(enc))}

        app._on_load_path_chosen(enc)

        assert (app._save_path, app._terrain_path, app._lighting_path,
                app._effects_path) == paths, "the page was re-pointed at the encounter"
        assert (app.bm.grid_cols, app.bm.grid_rows, app.bm.cell_pixel_size) == grid
        assert json.dumps(app._terrain_regions, sort_keys=True) == regions
        enc_after = {n: open(os.path.join(os.path.dirname(enc), n)).read()
                     for n in os.listdir(os.path.dirname(enc))}
        assert enc_after == enc_before, "the chosen encounter's files were written"

        cells = _cells(app)
        assert cells["Resident"] == (5, 5), "the page's own creature was lost or moved"
        assert cells["Hilaria"] == (2, 3)
        assert cells["Keef"] != (2, 3) and max(abs(cells["Keef"][0] - 2),
                                               abs(cells["Keef"][1] - 3)) == 1
        c, r = cells["Far Away"]
        assert 0 <= c < COLS and 0 <= r < ROWS
        assert len(set(cells.values())) == len(cells), "two creatures share a cell"
    print("  ✅ Load Encounter on a page adds creatures; grid, terrain and files untouched")


def test_survives_page_change():
    with tempfile.TemporaryDirectory() as tmp:
        app, pages = _dungeon(tmp)
        app._on_load_path_chosen(_encounter(tmp))
        before = _cells(app)
        assert app._switch_to_page(pages[1])
        assert "Hilaria" not in _cells(app)
        assert app._switch_to_page(pages[0])
        assert _cells(app) == before
        with open(os.path.join(tmp, "M_agents.json")) as f:
            names = {a["name"] for a in json.load(f)["agents"]}
        assert {"Hilaria", "Keef", "Far Away"} <= names
    print("  ✅ The loaded creatures are saved with the page and come back with it")


def _page_doc(tmp, pid):
    with open(os.path.join(tmp, f"{pid}_agents.json")) as f:
        return json.load(f)


def test_save_as_bundles_every_page():
    with tempfile.TemporaryDirectory() as tmp:
        app, pages = _dungeon(tmp)
        _place(app, "Strahd", 1, 1)
        assert app._switch_to_page(pages[1])
        _place(app, "Rahadin", 4, 2)
        paths = (app._save_path, app._terrain_path)
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        bundle = os.path.join(out, "castle_agents.json")
        app._on_save_path_chosen(bundle)
        assert (app._save_path, app._terrain_path) == paths, "Save As re-pointed the page"
        assert os.listdir(out) == ["castle_agents.json"], os.listdir(out)
        with open(bundle) as f:
            doc = json.load(f)
        got = {(a["name"], a["page"], a["z"], a["col"], a["row"]) for a in doc["agents"]}
        assert got == {("Strahd", "M", 0, 1, 1), ("Rahadin", "U", 1, 4, 2)}, got

        # A page's own file is refused, and left as it was.
        own = os.path.join(tmp, "M_agents.json")
        before = open(own).read()
        app._on_save_path_chosen(own)
        assert open(own).read() == before
    print("  ✅ Save As on a dungeon writes every page, tagged; refuses a page's own file")


def test_load_bundle_distributes():
    with tempfile.TemporaryDirectory() as tmp:
        app, pages = _dungeon(tmp)
        with open(os.path.join(tmp, "U_agents.json"), "w") as f:     # U already has someone
            json.dump({"agents": [{"name": "Guard", "size": 1, "col": 4, "row": 2}],
                       "map_items": []}, f)
        bundle = os.path.join(tmp, "castle_agents.json")
        with open(bundle, "w") as f:
            json.dump({"agents": [
                {"name": "Strahd", "size": 1, "col": 1, "row": 1, "page": "M", "z": 0},
                {"name": "Rahadin", "size": 1, "col": 4, "row": 2, "page": "U", "z": 1},
                {"name": "Escher", "size": 1, "col": 6, "row": 6, "page": "U", "z": 1},
                {"name": "Lost", "size": 1, "col": 2, "row": 2, "page": "Nowhere", "z": 9}],
                "map_items": [],
                "active_conditions": [{"agent_idx": 2, "caster_idx": 1, "page": "U",
                                       "name": "marker"}]}, f)
        app._on_load_path_chosen(bundle)

        assert app.dungeon_page.id == "M"
        assert set(_cells(app)) == {"Strahd"}, _cells(app)
        u = _page_doc(tmp, "U")
        cells = {a["name"]: (a["col"], a["row"]) for a in u["agents"]}
        assert cells["Guard"] == (4, 2)
        assert cells["Escher"] == (6, 6)
        assert cells["Rahadin"] != (4, 2) and max(abs(cells["Rahadin"][0] - 4),
                                                  abs(cells["Rahadin"][1] - 2)) == 1
        assert all("page" not in a and "z" not in a for a in u["agents"])
        names = [a["name"] for a in u["agents"]]
        cond = u["active_conditions"]
        assert len(cond) == 1 and "page" not in cond[0]
        assert names[cond[0]["agent_idx"]] == "Escher"
        assert names[cond[0]["caster_idx"]] == "Rahadin"
        assert app._switch_to_page(pages[1])
        assert {"Guard", "Rahadin", "Escher"} <= set(_cells(app))
    print("  ✅ Load sends each creature to its page; conditions follow; unknown pages skipped")


def test_load_replaces_mobs():
    with tempfile.TemporaryDirectory() as tmp:
        app, pages = _dungeon(tmp)
        with open(os.path.join(tmp, "M_agents.json"), "w") as f:
            json.dump({"agents": [
                {"name": "Old Goblin", "size": 1, "col": 2, "row": 3, "is_npc": True},
                {"name": "Resident", "size": 1, "col": 5, "row": 5},
                {"name": "Hilaria", "size": 1, "col": 7, "row": 1}],
                "map_items": []}, f)
        app._load_agents()
        enc = _encounter(tmp)
        app._on_load_path_chosen(enc)
        cells = _cells(app)
        assert set(cells) == {"Resident", "Hilaria", "Keef", "Far Away"}, cells
        assert cells["Resident"] == (5, 5), "a PC the file lacks was lost or moved"
        assert cells["Hilaria"] == (2, 3), "the cleared mob still held the cell"
        app._on_load_path_chosen(enc)                     # load the same file again
        names = [pt.name for pt in app.bm.placed_agents]
        assert sorted(names) == ["Far Away", "Hilaria", "Keef", "Resident"], names

        # A page that is not showing: its NPCs go, its conditions are re-indexed.
        with open(os.path.join(tmp, "U_agents.json"), "w") as f:
            json.dump({"agents": [
                {"name": "Guard", "size": 1, "col": 4, "row": 2, "is_npc": True},
                {"name": "Ally", "size": 1, "col": 0, "row": 0},
                {"name": "Hero", "size": 1, "col": 1, "row": 0}],
                "map_items": [],
                "active_conditions": [
                    {"agent_idx": 2, "caster_idx": 1, "name": "kept"},
                    {"agent_idx": 2, "caster_idx": 0, "name": "guard's"},
                    {"agent_idx": 0, "caster_idx": -1, "name": "on guard"}]}, f)
        bundle = os.path.join(tmp, "castle_agents.json")
        with open(bundle, "w") as f:
            json.dump({"agents": [{"name": "Rahadin", "size": 1, "col": 4, "row": 2,
                                   "page": "U", "z": 1, "is_npc": True}],
                       "map_items": []}, f)
        app._on_load_path_chosen(bundle)
        u = _page_doc(tmp, "U")
        cells = {a["name"]: (a["col"], a["row"]) for a in u["agents"]}
        assert cells == {"Ally": (0, 0), "Hero": (1, 0), "Rahadin": (4, 2)}, cells
        names = [a["name"] for a in u["agents"]]
        assert [c["name"] for c in u["active_conditions"]] == ["kept"]
        assert names[u["active_conditions"][0]["agent_idx"]] == "Hero"
        assert names[u["active_conditions"][0]["caster_idx"]] == "Ally"
    print("  ✅ Load replaces a page's mobs and same-named creatures; other PCs stay")


if __name__ == "__main__":
    pygame.init()
    test_creatures_only()
    test_survives_page_change()
    test_save_as_bundles_every_page()
    test_load_bundle_distributes()
    test_load_replaces_mobs()
    print("All load-encounter-on-a-page tests passed.")
