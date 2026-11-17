#!/usr/bin/env python3
"""The New Dungeon dialog (plans/NEW_DUNGEON_PLAN.md D1, D4, D5, D7; step 4).

A headless App on a loose map, with the dialog's menus and typed names scripted:

* the campaign list holds every campaign under encounters/, "New campaign…" and
  "No campaign (loose)";
* "New campaign…" makes the campaign and the dungeon from the map showing, opens it, and
  leaves the map's own files untouched (U1);
* New Dungeon inside that campaign asks only the name (its library has one map) and opens
  a second dungeon the party follows into (D5, U4);
* a campaign that already has the PC's sheet asks once, Keep / Update (D4);
* "No campaign (loose)" still writes a version-1 manifest beside the map (D7).
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

import run_state as rs
import save_layout as sl
from dungeon import Dungeon, dungeon_path_for
from main import App
from scene_store import CampaignStore

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _pc(name, hp=20, col=2, row=2):
    return {"name": name, "faction": 2, "size": 1, "col": col, "row": row,
            "controller": "dm", "on_deck": False, "sprite_path": "",
            "stats": {"str": 10, "dex": 14, "con": 12, "intel": 10, "wis": 10, "cha": 10,
                      "hp_max": hp, "hp_cur": hp, "ac": 14, "speed_walk": 30},
            "weapons": [], "items": []}


def _monster(name, col=6, row=5):
    rec = _pc(name, hp=7, col=col, row=row)
    rec["faction"] = 1
    return rec


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _loose_map(tmp, pc_hp=20):
    """tmp/maps/room.png with its roster (one PC, one monster) and terrain."""
    maps = os.path.join(tmp, "maps")
    os.makedirs(maps, exist_ok=True)
    png = os.path.join(maps, "room.png")
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    pygame.image.save(surf, png)
    _write(os.path.join(maps, "room_agents.json"),
           {"agents": [_pc("Rasha", hp=pc_hp), _monster("Goblin")], "map_items": []})
    _write(os.path.join(maps, "room_terrain.json"),
           {"regions": [], "walls_enabled": False, "manual_grid": GRID, "doors": []})
    return png


def _app(png):
    app = App(png, seed=1)
    app._load_agents()                   # main() loads the roster; App() alone does not
    return app


class Script:
    """Scripted answers: menus by label (in order), typed names (in order)."""

    def __init__(self, app, picks=(), names=()):
        self.picks, self.names, self.menus = list(picks), list(names), []
        app._ask_dm = self.ask
        app._modal_text_prompt = lambda title, prompt, **kw: self.names.pop(0)
        app._modal_message = lambda lines, **kw: self.menus.append(("message", lines))

    def ask(self, kind, title, items, **kw):
        self.menus.append((title, [label for label, _ in items]))
        want = self.picks.pop(0)
        dict(items)[want]()


def _snapshot(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), "rb") as f:
            out[name] = f.read()
    return out


def test_new_campaign_then_second_dungeon():
    tmp = tempfile.mkdtemp(prefix="new_dungeon_dialog_")
    try:
        png = _loose_map(tmp)
        other = sl.Campaign.create(os.path.join(tmp, "encounters", "Other"), "Other Camp")
        before = _snapshot(os.path.join(tmp, "maps"))
        app = _app(png)
        script = Script(app, picks=["New campaign…"], names=["My Campaign", "The Crypt"])
        app._dungeon_new(anchor=(10, 10))
        title, labels = script.menus[0]
        assert labels == ["Other Camp", "New campaign…", "No campaign (loose)"], labels

        assert isinstance(app.store, CampaignStore)
        camp = sl.Campaign(os.path.join(tmp, "encounters", "my-campaign"))
        assert camp.name == "My Campaign"
        assert camp.list_dungeons() == ["the-crypt"] and camp.list_library_maps() == ["room"]
        assert os.path.isfile(camp.pc_path("Rasha"))
        layout = camp.dungeon("the-crypt")
        assert layout.list_encounters("room") == ["initial"]
        names = sorted(pt.name for pt in app.bm.placed_agents)
        assert names == ["Goblin", "Rasha"], names
        assert _snapshot(os.path.join(tmp, "maps")) == before          # U1: only read
        assert other.list_dungeons() == []

        # A second dungeon in the open campaign: one library map, so only the name.
        script = Script(app, names=["Crypt Annex"])
        app._dungeon_new(anchor=(10, 10))
        assert script.menus == [], script.menus
        assert camp.list_dungeons() == ["crypt-annex", "the-crypt"]
        annex = camp.dungeon("crypt-annex")
        assert app._dungeon_manifest_path == annex.manifest_path
        assert Dungeon.load(annex.manifest_path).pages[0].cols == COLS
        assert [pt.name for pt in app.bm.placed_agents] == ["Rasha"]   # the party followed
        assert rs.load_run(annex.run_path())["maps"]["room"]["agents"][0]["name"] == "Rasha"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ New campaign → dungeon from the map; a second dungeon the party follows into")


def test_existing_sheet_keep_or_update():
    tmp = tempfile.mkdtemp(prefix="new_dungeon_dialog_")
    try:
        png = _loose_map(tmp, pc_hp=33)
        camp = sl.Campaign.create(os.path.join(tmp, "encounters", "Camp"), "Camp")
        _write(camp.pc_path("Rasha"), _pc("Rasha", hp=20))

        app = _app(png)
        script = Script(app, picks=["Camp", "Keep"], names=["Keep Dungeon"])
        app._dungeon_new(anchor=(10, 10))
        assert script.menus[1][0] == "Update sheets from the map: Rasha?", script.menus
        assert _read(camp.pc_path("Rasha"))["stats"]["hp_max"] == 20

        app = _app(png)
        Script(app, picks=["Camp", "Update"], names=["Update Dungeon"])
        app._dungeon_new(anchor=(10, 10))
        assert _read(camp.pc_path("Rasha"))["stats"]["hp_max"] == 33
        assert camp.list_dungeons() == ["keep-dungeon", "update-dungeon"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ A PC with a sheet already: Keep leaves it, Update writes the map's")


def test_loose_and_refusals():
    tmp = tempfile.mkdtemp(prefix="new_dungeon_dialog_")
    try:
        png = _loose_map(tmp)
        app = _app(png)
        app.confirm_overwrites = False
        Script(app, picks=["No campaign (loose)"])
        app._dungeon_new(anchor=(10, 10))
        path = dungeon_path_for(app._save_path)
        assert os.path.isfile(path) and Dungeon.load(path).version < 2
        assert not isinstance(app.store, CampaignStore)
        assert not os.path.isdir(os.path.join(tmp, "encounters"))

        # A dungeon already open (version 1): no New Dungeon until it is closed.
        script = Script(app)
        app._dungeon_new(anchor=(10, 10))
        assert script.menus == []

        # A blank name writes nothing.
        app = _app(png)
        Script(app, picks=["New campaign…"], names=["Blank", None])
        app._dungeon_new(anchor=(10, 10))
        assert not os.path.isdir(os.path.join(tmp, "encounters", "blank"))
    finally:
        shutil.rmtree(tmp)
    print("  ✅ No campaign (loose) writes version 1; an open dungeon and a blank name refuse")


def test_open_campaign():
    tmp = tempfile.mkdtemp(prefix="new_dungeon_dialog_")
    try:
        png = _loose_map(tmp)
        app = _app(png)
        Script(app, picks=["New campaign…"], names=["My Campaign", "The Crypt"])
        app._dungeon_new(anchor=(10, 10))
        camp = sl.Campaign(os.path.join(tmp, "encounters", "my-campaign"))

        # From a loose map, no dungeon open: Open Campaign → New Dungeon… on its library.
        app = _app(png)
        script = Script(app, picks=["My Campaign", "New Dungeon…", "room"], names=["Annex"])
        app._open_campaign(anchor=(10, 10))
        assert script.menus[0] == ("Open Campaign", ["My Campaign"]), script.menus
        assert script.menus[1] == ("My Campaign", ["the-crypt", "New Dungeon…"]), script.menus
        assert script.menus[2] == ("New Dungeon 'Annex': start map",
                                   ["room.png (this map)", "room"]), script.menus
        assert camp.list_dungeons() == ["annex", "the-crypt"]
        assert isinstance(app.store, CampaignStore)
        assert app._dungeon_manifest_path == camp.dungeon("annex").manifest_path

        # …or one of its dungeons, opened directly.
        app = _app(png)
        Script(app, picks=["My Campaign", "the-crypt"])
        app._open_campaign(anchor=(10, 10))
        assert app._dungeon_manifest_path == camp.dungeon("the-crypt").manifest_path
    finally:
        shutil.rmtree(tmp)
    print("  ✅ Open Campaign lists its dungeons and makes a new one from its library")


def test_map_inside_a_campaign():
    """A loose image sitting in encounters/<campaign>/maps/ finds the campaigns beside
    its own, not an encounters/ folder inside the campaign."""
    tmp = tempfile.mkdtemp(prefix="new_dungeon_dialog_")
    try:
        camp = sl.Campaign.create(os.path.join(tmp, "encounters", "Camp"), "Camp")
        png = _loose_map(camp.root)                  # encounters/Camp/maps/room.png
        app = _app(png)
        script = Script(app, picks=["Camp"], names=["Hut"])
        app._dungeon_new(anchor=(10, 10))
        assert script.menus[0][1] == ["Camp", "New campaign…", "No campaign (loose)"], script.menus
        assert camp.list_dungeons() == ["hut"]
        assert isinstance(app.store, CampaignStore)

        app = _app(png)
        script = Script(app, picks=["Camp", "hut"])
        app._open_campaign(anchor=(10, 10))
        assert script.menus[0] == ("Open Campaign", ["Camp"]), script.menus

        # Open Campaign → New Dungeon… → the loose map showing, brought into the campaign.
        app = _app(png)
        Script(app, picks=["Camp", "New Dungeon…", "room.png (this map)", "Keep"], names=["Hut Two"])
        app._open_campaign(anchor=(10, 10))
        assert camp.list_dungeons() == ["hut", "hut-two"]
        assert isinstance(app.store, CampaignStore)
        assert app._dungeon_manifest_path == camp.dungeon("hut-two").manifest_path
    finally:
        shutil.rmtree(tmp)
    print("  ✅ A map inside a campaign's maps/ folder lists the campaigns beside it")


def main():
    pygame.init()
    tests = [test_new_campaign_then_second_dungeon, test_existing_sheet_keep_or_update,
             test_loose_and_refusals, test_open_campaign, test_map_inside_a_campaign]
    print("Running New Dungeon dialog tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} New Dungeon dialog tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
