#!/usr/bin/env python3
"""Using a staircase: step 2 of plans/STAIRCASES_PLAN.md.

A headless App on a three-floor dungeon (B at z=-1, M at z=0, U at z=+1):

  · Ascend and Descend carry the acting creature to the staircase's other end, both ways;
  · ends on neighbouring cells, and two staircases sharing one landing (D2), each go
    where their own staircase goes, and a shared landing offers both Ascend and Descend;
  · a page change is refused in combat (D3), and an unfinished staircase is unusable;
  · the player view lists ends under the ladders' fog rule, with the label and the page it
    lands on kept to the DM;
  · a player's answer to the Ascend / Descend prompt is checked by the bus: only the
    creature's controller can take it.
"""

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
from menus import dm
from net import submit as net_submit
from net.roster import DM_PRINCIPAL_ID, PC_FACTION, Role
from net.view import build_view

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
PAGES = (("B", -1), ("M", 0), ("U", 1))


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    for x in range(0, COLS * CELL + 1, CELL):                # grid lines for analyze_grid
        pygame.draw.line(surf, (60, 60, 60), (x, 0), (x, ROWS * CELL), 1)
    for y in range(0, ROWS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (0, y), (COLS * CELL, y), 1)
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _dungeon(tmp):
    """An app on page M, with B below and U above. Every page is open floor."""
    pages = []
    for pid, z in PAGES:
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            f.write('{"regions": [], "walls_enabled": false, "manual_grid": %s}'
                    % str(GRID).replace("'", '"'))
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    app = App(pages[1].png, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon_page = None
    assert app._switch_to_page(pages[1], force=True)
    return app


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    return _idx(app, name)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    return -1


def _where(app, name):
    i = _idx(app, name)
    assert i >= 0, f"{name} is not on page {app.dungeon_page.id}"
    pt = app.bm.placed_agents[i]
    return app.dungeon_page.id, (pt.origin.col, pt.origin.row)


def _menu_labels(app, col, row):
    app.prompts.cancel()                                    # a stale menu would read as this one
    dm.show_staircase_menu(app, rpg.Cell(col, row), (0, 0))
    p = app.prompts.live
    return [] if p is None else [o.label for o in p.options]


def test_carries_both_ways():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        st = app.dungeon.new_staircase("M", (2, 2), label="K21")
        app.dungeon.finish_staircase(st.id, "U", (6, 5))
        idx = _place(app, "Aria", 2, 3)
        assert app._use_staircase(st.id, 0, idx)
        assert _where(app, "Aria") == ("U", (6, 5))
        # Back down from the other end.
        assert app._use_staircase(st.id, 1, _idx(app, "Aria"))
        assert _where(app, "Aria") == ("M", (2, 2))
        # An end that is not on this page is not this page's to use.
        assert not app._use_staircase(st.id, 1, _idx(app, "Aria"))
        assert app.dungeon_page.id == "M"
    print("  ✅ Ascend and Descend carry the creature to the other end, both ways")


def test_neighbouring_and_shared_ends():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        d = app.dungeon
        up = d.new_staircase("M", (4, 4))
        d.finish_staircase(up.id, "U", (1, 1))
        side = d.new_staircase("M", (5, 4))                 # the neighbouring cell
        d.finish_staircase(side.id, "U", (8, 6))
        down = d.new_staircase("M", (4, 4))                 # shares up's landing
        d.finish_staircase(down.id, "B", (3, 6))

        labels = _menu_labels(app, 4, 4)
        assert labels == [f"Ascend Staircase {up.id} to U",
                          f"Descend Staircase {down.id} to B"], labels
        assert _menu_labels(app, 5, 4) == [f"Ascend Staircase {side.id} to U"]
        app._draw_staircases(CELL)                          # the shared glyph draws both arrows
        assert set(app._staircase_cells_here()) == {(4, 4), (5, 4)}

        idx = _place(app, "Aria", 4, 5)
        assert app._use_staircase(down.id, 0, idx)
        assert _where(app, "Aria") == ("B", (3, 6))
        assert app._use_staircase(down.id, 1, _idx(app, "Aria"))
        assert app._use_staircase(side.id, 0, _idx(app, "Aria"))
        assert _where(app, "Aria") == ("U", (8, 6))
    print("  ✅ neighbouring and shared ends each go where their own staircase goes")


def test_refused_in_combat_and_unfinished():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        st = app.dungeon.new_staircase("M", (2, 2))
        idx = _place(app, "Aria", 2, 3)
        assert not app._use_staircase(st.id, 0, idx)        # unfinished
        assert _menu_labels(app, 2, 2) == []                # and offers nothing
        assert _where(app, "Aria") == ("M", (2, 3))

        app.dungeon.finish_staircase(st.id, "B", (0, 0))
        app.combat_active = True
        assert not app._use_staircase(st.id, 0, idx)        # D3
        assert _where(app, "Aria") == ("M", (2, 3))
        app.combat_active = False
        assert app._use_staircase(st.id, 0, idx)
        assert _where(app, "Aria") == ("B", (0, 0))
    print("  ✅ refused in combat; an unfinished staircase is unusable")


def test_player_view_under_fog():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        seen = app.dungeon.new_staircase("M", (1, 1), label="K83")
        app.dungeon.finish_staircase(seen.id, "U", (2, 2))
        hidden = app.dungeon.new_staircase("M", (8, 6), label="K64")
        app.dungeon.finish_staircase(hidden.id, "B", (2, 2))
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        app._set_fog(True)
        app.bm.set_explored_cells([rpg.Cell(c, r) for c in range(4) for r in range(4)])

        view = build_view(app, kira)["terrain"]["staircases"]
        assert view == [{"id": seen.id, "name": seen.name, "cell": [1, 1],
                         "direction": "up"}], view
        blob = str(build_view(app, kira))
        assert "K83" not in blob and "K64" not in blob

        dm_view = build_view(app, app.roster.get(DM_PRINCIPAL_ID))["terrain"]["staircases"]
        assert {s["id"] for s in dm_view} == {seen.id, hidden.id}
        assert next(s for s in dm_view if s["id"] == seen.id)["target_page"] == "U"
        assert next(s for s in dm_view if s["id"] == hidden.id)["label"] == "K64"
    print("  ✅ player view lists seen ends only; label and destination stay with the DM")


def test_player_submit_validated():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        st = app.dungeon.new_staircase("M", (2, 2))
        app.dungeon.finish_staircase(st.id, "U", (5, 5))
        idx = _place(app, "Aria", 2, 3)
        app.bm.set_agent_faction(idx, PC_FACTION)
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        wen = app.roster.add_principal("Wen", role=Role.PLAYER)
        app.bm.set_agent_controller(idx, kira.id)
        app._sync_roster_tokens()
        app.selected_idx = idx

        dm.show_staircase_menu(app, rpg.Cell(2, 2), (0, 0))
        p = app.prompts.live
        assert p is not None and p.owner == kira.id
        ack = net_submit.handle_submit(app, wen, {"id": p.id, "option": "opt_0"})
        assert ack["ok"] is False, ack
        assert _where(app, "Aria") == ("M", (2, 3))
        ack = net_submit.handle_submit(app, kira, {"id": p.id, "option": "opt_0"})
        assert ack["ok"] is True, ack
        assert _where(app, "Aria") == ("U", (5, 5))
    print("  ✅ only the creature's controller can answer Ascend / Descend")


def main():
    pygame.init()
    tests = [test_carries_both_ways, test_neighbouring_and_shared_ends,
             test_refused_in_combat_and_unfinished, test_player_view_under_fog,
             test_player_submit_validated]
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
