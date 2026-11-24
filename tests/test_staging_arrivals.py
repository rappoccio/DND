#!/usr/bin/env python3
"""New PCs arrive in a generated dungeon's staging room, as Load PCs does.

  · New PC: confirming the name drops the PC straight onto a staging cell instead of
    floating it for a click;
  · D&D Beyond import: the imported record lands on a staging cell, on the blue team;
  · with no staging room, both still float for a click, as before.
"""

import os
import sys
import shutil
import tempfile
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

import main as app_main
import app_dungeon_gen
from main import App, PC_FACTION
from test_helpers import make_fixture_campaign


def _open(tmp):
    camp = make_fixture_campaign(os.path.join(tmp, "Test Campaign"))
    png, manifest = app_main.resolve_start_path(camp.root)
    app = App(png, seed=1)
    app._on_open_dungeon_chosen(manifest)
    app._clear_agents()
    app._save_agents()
    return app


def _free_cells(app, n):
    out = []
    for r in range(app.bm.grid_rows):
        for c in range(app.bm.grid_cols):
            if app._can_place(rpg.Cell(c, r), 1):
                out.append([c, r])
                if len(out) == n:
                    return out
    return out


def _at(app, name):
    for pt in app.bm.placed_agents:
        if pt.name == name:
            return [pt.origin.col, pt.origin.row]
    return None


def _new_pc(app, name):
    app._on_pc_class_selected("Fighter")
    app.placement_config.name = name           # what Enter does with the typed name
    app._pc_name_input = None
    app.placement_mode_active = True
    return app._place_in_staging()


def test_new_pc_lands_in_staging():
    tmp = tempfile.mkdtemp(prefix="staging_newpc_")
    try:
        app = _open(tmp)
        assert app.dungeon_page is not None
        app.dungeon_page.staging_cells = None
        app._staging_cells = None
        app._terrain_rooms = []
        assert not _new_pc(app, "Nobody")      # no staging room: still floats
        assert app.placement_mode_active and _at(app, "Nobody") is None
        app.placement_mode_active = False
        app.placement_config = None

        staging = _free_cells(app, 4)
        app.dungeon_page.staging_cells = staging
        assert _new_pc(app, "Brakka")
        assert _at(app, "Brakka") in staging, _at(app, "Brakka")
        assert not app.placement_mode_active and app.placement_config is None
    finally:
        shutil.rmtree(tmp)
    print("  ✅ New PC drops into the staging room (and floats when there is none)")


def test_ddb_import_lands_in_staging():
    tmp = tempfile.mkdtemp(prefix="staging_ddb_")
    try:
        app = _open(tmp)
        # A real record, as the app writes one, stands in for the importer's output.
        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = \
            "Imported Ilse", 0, 0, 1, ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
        app.combat.apply_agent_configs(app.bm)
        app._save_agents()
        rec = next(a for a in app.store.creatures()["agents"] if a["name"] == "Imported Ilse")
        rec.update(faction=0, agent_class="Fighter", agent_char_level=1,
                   spell_indices=[])
        rec.setdefault("stats", {}).setdefault("hp_max", 10)
        app._clear_agents()
        app._save_agents()

        stub = types.ModuleType("import_character")
        stub._WARN = []
        stub.fetch_character = lambda url: {"name": "Imported Ilse"}
        stub.load_catalogs = lambda: None
        stub.build_agent = lambda data, cats, faction=0: dict(rec)
        stub.slugify = lambda s: "imported_ilse"
        sys.modules["import_character"] = stub
        app._modal_text_prompt = lambda *a, **k: "imported-ilse"
        app._modal_message = lambda *a, **k: None

        def _no_sidecar(*a, **k):                  # keep the test out of tools/ddb_sources
            raise OSError("test")
        app_dungeon_gen.open = _no_sidecar
        try:
            staging = _free_cells(app, 3)
            app.dungeon_page.staging_cells = staging
            app_dungeon_gen.import_ddb_character(app)
        finally:
            del app_dungeon_gen.open
        assert _at(app, "Imported Ilse") in staging, _at(app, "Imported Ilse")
        assert not app.placement_mode_active and app._pending_import_agent is None
        idx = next(i for i, pt in enumerate(app.bm.placed_agents)
                   if pt.name == "Imported Ilse")
        assert app.bm.placed_agents[idx].faction == PC_FACTION

        # No staging room: the record floats for a click, as before.
        app._clear_agents()
        app._save_agents()
        app.dungeon_page.staging_cells = None
        app._staging_cells = None
        app._terrain_rooms = []
        app_dungeon_gen.open = _no_sidecar
        try:
            app_dungeon_gen.import_ddb_character(app)
        finally:
            del app_dungeon_gen.open
        assert app.placement_mode_active and app._pending_import_agent is not None
        assert _at(app, "Imported Ilse") is None
    finally:
        sys.modules.pop("import_character", None)
        shutil.rmtree(tmp)
    print("  ✅ D&D Beyond import drops into the staging room on the blue team")


if __name__ == "__main__":
    test_new_pc_lands_in_staging()
    test_ddb_import_lands_in_staging()
    print("All staging-arrival tests passed.")
