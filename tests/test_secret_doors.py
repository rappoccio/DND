#!/usr/bin/env python3
"""Secret doors, and the Walls: ON / HIDDEN / OFF toggle.

A secret door is a door whose design says ``secret``; until the DM reveals it, it is
``hidden``: a wall to everyone. It stays shut and opening, Knock, picking and forcing all
fail; the player view leaves it out; no creature's door menu offers it. Revealing it is
play state (the map keeps it secret, so a reset hides it again).

Walls: HIDDEN keeps the walls exactly as ON does, so they block and the fog respects
them, but the DM console draws no red wall lines.
"""

import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import run_state as rs
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
C = rpg.Cell


# ── Engine ───────────────────────────────────────────────────────────────────

def test_hidden_door_is_a_wall_nobody_can_open():
    bm = setup_battle_map()
    cell = C(4, 4)
    did = bm.add_door(cell, True, False, 15, False)          # an open door
    assert bm.set_door_secret(did, True)
    d = bm.doors[bm.door_at(cell)]
    assert d.secret and d.hidden and not d.open, "making it secret hides and shuts it"
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Wall
    assert not bm.open_door(did), "a hidden door won't open"
    assert not bm.knock_door(did), "Knock doesn't find a hidden door"
    assert not bm.break_door(did), "a hidden door can't be forced"
    d = bm.doors[bm.door_at(cell)]
    assert d.hidden and not d.open and not d.broken

    assert bm.set_door_hidden(did, False)
    d = bm.doors[bm.door_at(cell)]
    assert d.secret and not d.hidden and not d.open, "revealed: an ordinary closed door"
    assert bm.open_door(did)
    assert bm.get_terrain_type(cell) == rpg.TerrainType.Standard

    assert bm.set_door_hidden(did, True), "the DM can hide it again"
    assert not bm.doors[bm.door_at(cell)].open
    assert bm.set_door_secret(did, False)
    d = bm.doors[bm.door_at(cell)]
    assert not d.secret and not d.hidden
    print("✅ test_hidden_door_is_a_wall_nobody_can_open")


def test_broken_door_cannot_be_made_secret():
    bm = setup_battle_map()
    did = bm.add_door(C(5, 5), False, False, 15, False)
    bm.break_door(did)
    assert not bm.set_door_secret(did, True)
    assert not bm.doors[bm.door_at(C(5, 5))].hidden
    print("✅ test_broken_door_cannot_be_made_secret")


def test_hidden_edge_door_blocks_its_edge():
    bm = setup_battle_map()
    edge = rpg.Edge(C(3, 3), rpg.EdgeSide.East)
    did = bm.add_edge_door([edge], True, False, 15, False, 15)
    assert not bm.is_edge_wall(C(3, 3), rpg.EdgeSide.East), "open: it passes"
    bm.set_door_secret(did, True)
    assert bm.is_edge_wall(C(3, 3), rpg.EdgeSide.East), "hidden: wall"
    assert not bm.open_door(did)
    print("✅ test_hidden_edge_door_blocks_its_edge")


def test_pick_and_force_refuse_a_hidden_door():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 6))
    did = bm.add_door(C(6, 6), False, True, 1, False)
    bm.set_door_secret(did, True)
    assert not engine.attempt_pick_lock(bm, idx, did).valid
    assert not engine.attempt_break_door(bm, idx, did).valid
    bm.set_door_hidden(did, False)
    assert engine.attempt_pick_lock(bm, idx, did).valid, "found, it is an ordinary door"
    print("✅ test_pick_and_force_refuse_a_hidden_door")


# ── Map design vs play state ─────────────────────────────────────────────────

def _terrain(doors):
    return {"regions": [], "doors": doors}


def test_secret_is_design_and_hidden_is_play_state():
    plain = {"cells": [[1, 1]], "open": False}
    found = {"cells": [[2, 2]], "open": False, "secret": True, "hidden": False}
    map_doc, extras, state = rs.split_terrain(_terrain([plain, found]))
    assert "secret" not in map_doc["doors"][0], "an ordinary door's record is unchanged"
    assert map_doc["doors"][1]["secret"] is True
    assert "hidden" not in map_doc["doors"][1], "hidden is not design"
    assert state["doors"][1]["hidden"] is False

    back = rs.merge_terrain(map_doc, extras, state)
    assert back["doors"][1]["secret"] and back["doors"][1]["hidden"] is False, \
        "a revealed door stays revealed in the run"
    assert "secret" not in back["doors"][0]

    fresh = rs.merge_terrain(map_doc, extras, None)
    assert fresh["doors"][1]["hidden"] is True, "a reset hides the secret door again"
    print("✅ test_secret_is_design_and_hidden_is_play_state")


def test_making_a_door_secret_reaches_the_design():
    """Unlike open/locked, which play changes, secret is only ever a design edit, so the
    document's word beats the map already on disk."""
    old_map = {"doors": [{"cells": [[1, 1]], "open": False}]}
    doc = _terrain([{"cells": [[1, 1]], "open": False, "secret": True, "hidden": True}])
    map_doc, _, _ = rs.split_terrain(doc, old_map)
    assert map_doc["doors"][0].get("secret") is True
    doc = _terrain([{"cells": [[1, 1]], "open": False}])
    map_doc, _, _ = rs.split_terrain(doc, {"doors": [{"cells": [[1, 1]], "secret": True}]})
    assert "secret" not in map_doc["doors"][0], "making it ordinary reaches the design too"
    print("✅ test_making_a_door_secret_reaches_the_design")


def test_walls_shown_is_map_data():
    map_doc, _, _ = rs.split_terrain({"walls_enabled": True, "walls_shown": False})
    assert map_doc["walls_shown"] is False
    assert rs.merge_terrain(map_doc)["walls_shown"] is False
    print("✅ test_walls_shown_is_map_data")


# ── The app ──────────────────────────────────────────────────────────────────

def _app(tmp):
    from main import App
    png = os.path.join(tmp, "grid.png")
    shutil.copy(MAP_PATH, png)
    return App(png, seed=7)


def _door(app, cell):
    return app.bm.doors[app.bm.door_at(cell)]


def test_app_round_trips_a_secret_door():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        hidden_id = app.bm.add_door(C(3, 3), False, False, 15, False)
        found_id = app.bm.add_door(C(6, 6), False, False, 15, False)
        app.bm.add_door(C(8, 8), False, False, 15, False)
        app._door_set_secret(hidden_id, True)
        app._door_set_secret(found_id, True)
        app._door_set_hidden(found_id, False)
        app._draw_doors(int(app.bm.cell_pixel_size * app.map_scale))   # ghost + found "S"
        app._save_terrain()
        app._load_terrain(app._terrain_path)
        assert _door(app, C(3, 3)).hidden
        d = _door(app, C(6, 6))
        assert d.secret and not d.hidden
        d = _door(app, C(8, 8))
        assert not d.secret and not d.hidden
    print("✅ test_app_round_trips_a_secret_door")


def test_player_view_and_menus_leave_a_hidden_door_out():
    from menus import dm as dm_menus
    from net.roster import DM_PRINCIPAL_ID, Role
    from net.view import build_view
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        app._set_fog(False)
        did = app.bm.add_door(C(3, 3), False, False, 15, False)
        app._door_set_secret(did, True)
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)

        mine = build_view(app, kira)["terrain"]["doors"]
        assert all(d["id"] != did for d in mine), "a hidden door reached a player"
        dms = build_view(app, app.roster.get(DM_PRINCIPAL_ID))["terrain"]["doors"]
        rec = next(d for d in dms if d["id"] == did)
        assert rec["hidden"] and rec["secret"]

        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = "Scout", 3, 4, 1, ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
        app.combat.apply_agent_configs(app.bm)
        scout = next(i for i, pt in enumerate(app.bm.placed_agents) if pt.name == "Scout")
        assert dm_menus.doors_near(app, scout) == [], "nobody stands next to a wall's door"

        # The DM's menu on the hidden door: reveal it, owned by the DM.
        dm_menus.show_door_menu(app, C(3, 3), (10, 10))
        live = app.prompts.live
        assert live is not None and live.owner == DM_PRINCIPAL_ID
        assert [o.label for o in live.options] == ["Reveal secret door", "Make ordinary door"]
        assert app.prompts.choose_label("Reveal secret door").ok
        assert not _door(app, C(3, 3)).hidden
        assert [d.id for d in dm_menus.doors_near(app, scout)] == [did]
        mine = build_view(app, kira)["terrain"]["doors"]
        assert any(d["id"] == did for d in mine), "found, the players see it"
        assert "hidden" not in next(d for d in mine if d["id"] == did)
    print("✅ test_player_view_and_menus_leave_a_hidden_door_out")


def test_walls_cycle_on_hidden_off():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        assert app._walls_label() == "Walls: ON"
        cell, side = C(4, 4), rpg.EdgeSide.East
        app.bm.set_edge_wall(cell, side, True)
        app._build_overlay()
        s = app.map_scale
        x = int(app.bm.v_line_positions[5] * s)
        y = (int(app.bm.h_line_positions[4] * s) + int(app.bm.h_line_positions[5] * s)) // 2
        red = (200, 60, 60, 220)
        assert tuple(app.overlay.get_at((x, y))) == red, "ON draws the wall line"
        blocked = set((c.col, c.row) for c in app.bm.disallowed_cells)

        app._toggle_walls()
        assert app._walls_label() == "Walls: HIDDEN" and app.btn_toggle_walls.text == "Walls: HIDDEN"
        assert app._walls_enabled
        assert app.bm.is_edge_wall(cell, side), "HIDDEN walls still block"
        assert set((c.col, c.row) for c in app.bm.disallowed_cells) == blocked
        assert tuple(app.overlay.get_at((x, y))) != red, "HIDDEN draws no wall line"

        app._load_terrain(app._terrain_path)
        assert app._walls_label() == "Walls: HIDDEN", "HIDDEN survives a reload"

        app._toggle_walls()
        assert app._walls_label() == "Walls: OFF" and not app._walls_enabled
        app._toggle_walls()
        assert app._walls_label() == "Walls: ON" and app._walls_shown
    print("✅ test_walls_cycle_on_hidden_off")


if __name__ == "__main__":
    test_hidden_door_is_a_wall_nobody_can_open()
    test_broken_door_cannot_be_made_secret()
    test_hidden_edge_door_blocks_its_edge()
    test_pick_and_force_refuse_a_hidden_door()
    test_secret_is_design_and_hidden_is_play_state()
    test_making_a_door_secret_reaches_the_design()
    test_walls_shown_is_map_data()
    test_app_round_trips_a_secret_door()
    test_player_view_and_menus_leave_a_hidden_door_out()
    test_walls_cycle_on_hidden_off()
    print("\nAll secret-door tests passed.")
