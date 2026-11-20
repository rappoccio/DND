#!/usr/bin/env python3
"""Generate Dungeon on the blank map makes a named dungeon in "random_encounters".

On the bundled blank map (loose, nothing open) Generate Dungeon asks for a name and
files the result as ``<campaign root>/random_encounters/<slug>/``, instead of writing
``Blank_terrain.json`` / ``Blank_dungeon_agents.json`` beside the map. A taken name
asks before replacing; the old dungeon is archived, never deleted.

  · the writer: pages that share one image get their own map folder, map.json, run
    section and encounter; the manifest lists them all; a taken name is refused unless
    replacing, and replacing archives the old folder;
  · only the blank map, loose, takes the named path;
  · one floor: the dungeon opens, its walls are in the engine, its mobs are placed,
    and no Blank_* file is written;
  · several floors × maps: every page is a map of the dungeon, linked by ladders;
  · the same name again replaces the dungeon and archives the old one;
  · Terrain: Keep (mobs only) files the map as it stands, as one page.
"""

import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: F401  (initialises SDL for App)
import rpg_battle_map as rpg

import app_dungeon_gen as gen
import campaign_import as ci
import save_layout as sl
from main import App

BLANK = os.path.join(_ROOT, "maps", "Blank.png")


def _params(**kw):
    p = {"allowed_mobs": None, "boss_mob": None, "cr": 3, "min_room": 9,
         "start": "Easy", "end": "Hard", "boss": True, "seed": 4242, "carve": True,
         "types": None, "languages": None, "floors": 1, "rooms_per_floor": 4,
         "maps_x": 1, "maps_y": 1, "automation": 4, "groups": 0}
    p.update(kw)
    return p


class _Sandbox:
    """A copy of Blank.png in a temp maps/ folder, treated as THE blank map, with the
    campaigns root beside it — so nothing in the repo's maps/ or encounters/ is touched."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="named_dungeon_")
        maps = os.path.join(self.tmp, "maps")
        os.makedirs(maps)
        self.png = os.path.join(maps, "Blank.png")
        shutil.copy(BLANK, self.png)
        self._old = gen.BLANK_MAP
        gen.BLANK_MAP = self.png
        self.root = os.path.join(self.tmp, "encounters", gen.RANDOM_CAMPAIGN)
        return self

    def __exit__(self, *exc):
        gen.BLANK_MAP = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self):
        app = App(self.png, seed=7)
        app._modal_message = lambda lines, blocking=True: setattr(app, "_last_msg", lines)
        return app

    def map_files(self):
        return sorted(f for f in os.listdir(os.path.dirname(self.png)) if f != "Blank.png")


def _page(tmp, name, image, walls, agents):
    terrain = {"regions": [{"type": "Wall", "x": 0, "y": 0, "width": 10, "height": 10,
                            "multiplier": 0.0}] * walls,
               "doors": [], "ladders": [{"cells": [[1, 1]], "target": [1, 1, 1]}],
               "explored": [[0, 0]]}
    return ci.GeneratedPage(map=name, image=image, terrain=terrain,
                            agents={"agents": [{"name": f"Orc {i}"} for i in range(agents)],
                                    "map_items": [], "active_conditions": []},
                            origin=[0, 0, int(name[-1])], cols=30, rows=20)


def _walls(app):
    return sum(1 for r in range(app.bm.grid_rows) for c in range(app.bm.grid_cols)
               if app.bm.get_terrain_type(rpg.Cell(c, r)) == rpg.TerrainType.Wall)


def test_writer_lays_out_the_pages():
    tmp = tempfile.mkdtemp(prefix="gen_writer_")
    try:
        root = os.path.join(tmp, "random_encounters")
        pages = [_page(tmp, "floor0", BLANK, 1, 2), _page(tmp, "floor1", BLANK, 2, 3)]
        made = ci.new_generated_dungeon(root, "The Crypt", pages, entry_map="floor0",
                                        campaign_name="random_encounters")
        layout = made.layout
        assert layout.name == "the-crypt", layout.name
        assert sl.Campaign(root).name == "random_encounters"
        man = json.load(open(layout.manifest_path))
        assert man["version"] == 2 and man["entry_map"] == "floor0", man
        assert [m["map"] for m in man["maps"]] == ["floor0", "floor1"], man["maps"]
        assert man["maps"][1]["origin"] == [0, 0, 1], man["maps"][1]
        assert man["maps"][0]["ladders"], "the page lost its ladder"
        for m, walls, n in (("floor0", 1, 2), ("floor1", 2, 3)):
            assert layout.image_is_local(m), f"{m}: no image of its own"
            md = json.load(open(layout.write_path(m, sl.MAP_FILE)))
            assert len(md["regions"]) == walls, (m, md["regions"])
            enc = json.load(open(layout.encounter_path(m, ci.INITIAL_ENCOUNTER)))
            assert len(enc["agents"]) == n, (m, enc)
        run = json.load(open(layout.run_path()))
        assert run["current_map"] == "floor0", run
        assert set(run["maps"]) == {"floor0", "floor1"}, run["maps"].keys()
        assert sl.Campaign(root).list_library_maps() == [], "art went to the library"

        try:
            ci.new_generated_dungeon(root, "the crypt", pages, entry_map="floor0")
        except ValueError:
            pass
        else:
            raise AssertionError("a taken name was overwritten without replace")

        ci.new_generated_dungeon(root, "the crypt", pages[:1], entry_map="floor0",
                                 replace=True, stamp="T1")
        man = json.load(open(layout.manifest_path))
        assert [m["map"] for m in man["maps"]] == ["floor0"], man["maps"]
        arch = os.path.join(root, "_archive", "the-crypt-t1")
        assert os.path.isfile(os.path.join(arch, sl.DUNGEON_FILE)), os.listdir(root)
        assert sl.Campaign(root).list_dungeons() == ["the-crypt"], \
            sl.Campaign(root).list_dungeons()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_writer_lays_out_the_pages passed")


def test_only_the_loose_blank_map_is_named():
    with _Sandbox() as sb:
        app = sb.app()
        assert gen.on_blank_map(app), "the blank map isn't recognised"
        other = os.path.join(os.path.dirname(sb.png), "Other.png")
        shutil.copy(sb.png, other)
        assert not gen.on_blank_map(App(other, seed=7)), "any map took the named path"
    print("✅ test_only_the_loose_blank_map_is_named passed")


def test_one_floor_opens_as_a_campaign_dungeon():
    with _Sandbox() as sb:
        app = sb.app()
        before = sb.map_files()
        gen.generate_named_dungeon(app, _params(), "Crypt")
        msg = getattr(app, "_last_msg", [])
        assert any("random_encounters/crypt" in l for l in msg), msg
        assert sb.map_files() == before, f"wrote beside the map: {sb.map_files()}"
        layout = sl.Campaign(sb.root).dungeon("crypt")
        assert app._dungeon_manifest_path == layout.manifest_path, \
            app._dungeon_manifest_path
        assert app.dungeon_page is not None and app.dungeon_page.id == "floor0"
        assert _walls(app) > 0, "no walls in the engine after opening"
        assert len(app.bm.placed_agents) > 0, "no mobs placed"
    print("✅ test_one_floor_opens_as_a_campaign_dungeon passed")


def test_floors_and_maps_become_pages():
    with _Sandbox() as sb:
        app = sb.app()
        gen.generate_named_dungeon(app, _params(floors=2, maps_x=2), "Deep Halls")
        man = json.load(open(sl.Campaign(sb.root).dungeon("deep-halls").manifest_path))
        names = sorted(m["map"] for m in man["maps"])
        assert names == ["floor0", "floor0_1_0", "floor1", "floor1_1_0"], names
        spine0 = next(m for m in man["maps"] if m["map"] == "floor0")
        assert spine0.get("ladders"), "floor 0 has no ladder up"
        assert any(m.get("door_links") for m in man["maps"]), "abutting maps not linked"
        assert sb.map_files() == [], f"wrote beside the map: {sb.map_files()}"
    print("✅ test_floors_and_maps_become_pages passed")


def test_the_same_name_replaces_and_archives():
    with _Sandbox() as sb:
        app = sb.app()
        gen.generate_named_dungeon(app, _params(), "Crypt")
        app = sb.app()
        gen.generate_named_dungeon(app, _params(seed=99), "Crypt")
        camp = sl.Campaign(sb.root)
        assert camp.list_dungeons() == ["crypt"], camp.list_dungeons()
        arch = os.listdir(os.path.join(sb.root, "_archive"))
        assert len(arch) == 1 and arch[0].startswith("crypt-"), arch
    print("✅ test_the_same_name_replaces_and_archives passed")


def test_keep_terrain_files_the_map_as_it_stands():
    """Terrain: Keep (mobs only) populates the blank map as painted, into one page."""
    with _Sandbox() as sb:
        app = sb.app()
        painted = [{"type": "Wall", "x": 0, "y": 0, "width": 30, "height": 30,
                    "multiplier": 0.0}]
        app._terrain_regions = [dict(r) for r in painted]
        app._apply_terrain_to_battle_map()
        before = sb.map_files()
        gen.generate_named_dungeon(app, _params(carve=False), "Open Field")
        layout = sl.Campaign(sb.root).dungeon("open-field")
        man = json.load(open(layout.manifest_path))
        assert [m["map"] for m in man["maps"]] == ["floor0"], man["maps"]
        md = json.load(open(layout.write_path("floor0", sl.MAP_FILE)))
        assert md.get("regions") == painted, md.get("regions")
        assert sb.map_files() == before, f"wrote beside the map: {sb.map_files()}"
        assert app._dungeon_manifest_path == layout.manifest_path
        assert len(app.bm.placed_agents) > 0, "no mobs placed"
    print("✅ test_keep_terrain_files_the_map_as_it_stands passed")


def _run_agents(layout, page_id):
    run = json.load(open(layout.run_path()))
    return (run.get("maps") or {}).get(page_id, {}).get("agents", [])


def test_regenerate_in_an_open_campaign_dungeon_places_mobs():
    """Generate Dungeon on a map of an open campaign dungeon: the mobs reach the
    engine and the run (the scene's agents path is the store's, not a file)."""
    with _Sandbox() as sb:
        app = sb.app()
        gen.generate_named_dungeon(app, _params(), "Crypt")
        layout = sl.Campaign(sb.root).dungeon("crypt")
        app.bm.clear_agents()
        app.store.write_creatures({"agents": [], "map_items": [],
                                   "active_conditions": []})
        gen.generate_dungeon_with(app, _params(seed=99))
        msg = getattr(app, "_last_msg", [])
        assert len(app.bm.placed_agents) > 0, f"no mobs placed: {msg}"
        assert len(_run_agents(layout, "floor0")) == len(app.bm.placed_agents), \
            "the run did not get the mobs"
        assert app._dungeon_manifest_path == layout.manifest_path
        assert not os.path.exists(os.path.join(layout.run_dir(sl.DEFAULT_RUN),
                                               "floor0_agents.json")), \
            "wrote a stray file at the store's identity path"
    print("✅ test_regenerate_in_an_open_campaign_dungeon_places_mobs passed")


def main():
    tests = [test_regenerate_in_an_open_campaign_dungeon_places_mobs,
             test_writer_lays_out_the_pages,
             test_only_the_loose_blank_map_is_named,
             test_one_floor_opens_as_a_campaign_dungeon,
             test_floors_and_maps_become_pages,
             test_the_same_name_replaces_and_archives,
             test_keep_terrain_files_the_map_as_it_stands]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_generate_named_dungeon: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_generate_named_dungeon: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
