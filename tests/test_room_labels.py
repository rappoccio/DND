#!/usr/bin/env python3
"""Room labels: the DM's room keys ("K10") as a toggleable layer on the DM screen.

  · a page's "rooms" round-trip through the manifest; a manifest without them is written
    back unchanged, and a malformed row drops that label, not the dungeon;
  · a headless App draws each key centred on its cell, only on the page that owns it;
  · hovering a key gives "K10. Dining Hall" (the bare key when unnamed), and a token on
    the cell keeps its own tooltip;
  · the Dungeon Configuration menu's Hide / Show Room Labels turns the layer off and on;
  · nothing of it reaches a player's view.
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
from dungeon import Dungeon, MapPage, RoomLabel
from menus import dm

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
    """An app on page M (two rooms) with U above it (none)."""
    pages = []
    for pid, z in (("M", 0), ("U", 1)):
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            f.write('{"regions": [], "walls_enabled": false, "manual_grid": %s}'
                    % json.dumps(GRID))
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    pages[0].rooms = [RoomLabel("K10", "Dining Hall", (2, 3)), RoomLabel("K12", "", (6, 5))]
    app = App(pages[0].png, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon_page = None
    assert app._switch_to_page(pages[0], force=True)
    return app


def _cpx(app):
    return int(app.bm.cell_pixel_size * app.map_scale)


def _centre(app, col, row):
    sx, sy = app._cell_to_screen(col, row)
    return sx + _cpx(app) // 2, sy + _cpx(app) // 2


def test_manifest_round_trip():
    page = MapPage("M", "m.png", "m_agents.json", [0, 0, 0], 10, 8,
                   rooms=[RoomLabel("K10", "Dining Hall", (2, 3)), RoomLabel("K12", "", (6, 5))])
    d = Dungeon(pages=[page], entry_page_id="M")
    raw = json.loads(json.dumps(d.to_dict()))
    assert raw["pages"][0]["rooms"] == [
        {"key": "K10", "name": "Dining Hall", "cell": [2, 3]},
        {"key": "K12", "name": "", "cell": [6, 5]}], raw["pages"][0]["rooms"]
    back = Dungeon.from_dict(raw).pages[0].rooms
    assert [(r.key, r.name, r.cell, r.title) for r in back] == [
        ("K10", "Dining Hall", (2, 3), "K10. Dining Hall"), ("K12", "", (6, 5), "K12")]

    bare = MapPage("U", "u.png", "u_agents.json", [0, 0, 1], 10, 8)
    assert "rooms" not in bare.to_dict()             # an old manifest is written back unchanged

    raw["pages"][0]["rooms"] += [{"key": "", "cell": [1, 1]}, {"key": "K9"},
                                 {"key": "K8", "cell": "x"}]
    assert [r.key for r in Dungeon.from_dict(raw).pages[0].rooms] == ["K10", "K12"]
    print("  ✅ rooms round-trip; absent stays absent; bad rows are dropped")


def test_drawn_on_their_page():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app._draw_room_labels(_cpx(app))
        hits = [(r.key, rect.center) for rect, r in app._room_label_hits]
        assert [k for k, _ in hits] == ["K10", "K12"], hits
        for (key, centre), cell in zip(hits, [(2, 3), (6, 5)]):
            want = _centre(app, *cell)
            assert abs(centre[0] - want[0]) <= 1 and abs(centre[1] - want[1]) <= 1, (key, centre, want)

        assert app._switch_to_page(app.dungeon.page_by_id("U"), force=True)
        app._draw_room_labels(_cpx(app))
        assert app._room_label_hits == []           # U has no rooms
    print("  ✅ each key is drawn centred on its cell, on its own page only")


def test_hover_tooltip():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        app._draw_room_labels(_cpx(app))
        assert app._room_label_tooltip(_centre(app, 2, 3)) == "K10. Dining Hall"
        assert app._room_label_tooltip(_centre(app, 6, 5)) == "K12"
        assert app._room_label_tooltip(_centre(app, 4, 1)) is None   # no key there

        cfg = rpg.AgentConfig()                       # a token on K10 keeps its own tooltip
        cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = "Ezmerelda", 2, 3, 1, ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
        app.combat.apply_agent_configs(app.bm)
        assert app._agent_at(rpg.Cell(2, 3)) >= 0
        assert app._room_label_tooltip(_centre(app, 2, 3)) is None
    print("  ✅ hover reads \"K10. Dining Hall\"; a token keeps its own tooltip")


def test_menu_toggle():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        assert app.show_room_labels                   # on by default
        dm.show_dungeon_menu(app)
        labels = [o.label for o in app.prompts.live.options]
        assert "Hide Room Labels" in labels, labels
        app.prompts.choose_label("Hide Room Labels")
        assert not app.show_room_labels
        app._draw_room_labels(_cpx(app))
        assert app._room_label_hits == []
        assert app._room_label_tooltip(_centre(app, 2, 3)) is None

        dm.show_dungeon_menu(app)
        labels = [o.label for o in app.prompts.live.options]
        assert "Show Room Labels" in labels, labels
        app.prompts.choose_label("Show Room Labels")
        assert app.show_room_labels
        app._draw_room_labels(_cpx(app))
        assert len(app._room_label_hits) == 2
    print("  ✅ Hide / Show Room Labels in the Dungeon menu turns the layer off and on")


def test_not_in_player_view():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        from net.view import build_view
        from net.roster import Role
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        blob = json.dumps(build_view(app, kira), default=str)
        assert "Dining Hall" not in blob and "K10" not in blob
    print("  ✅ no room key or name reaches a player's view")


def main():
    pygame.init()
    tests = [test_manifest_round_trip, test_drawn_on_their_page, test_hover_tooltip,
             test_menu_toggle, test_not_in_player_view]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:                               # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
