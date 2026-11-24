#!/usr/bin/env python3
"""A creature saved on a cell that is blocked when the page loads keeps its own stats,
and so does everyone after it.

The engine (BattleMap::applyAgentConfigs) skips a blocked placement, and _load_agents
restores stats by position: one skip used to hand every later creature the stats,
class and spells of the one before it (seen when a party crossed a door into a page
and was later reloaded with a door closed on one of them). _load_agents now moves a
blocked record to the nearest open cell, as it does an off-grid one.
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

from main import App

CELL, COLS, ROWS = 30, 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
HP = {"Aria": 11, "Bram": 22, "Cole": 33}


def _write(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f)


def _terrain(regions):
    return {"regions": regions, "walls_enabled": False, "manual_grid": GRID, "doors": []}


def _hp_by_name(app):
    return {pt.name: app.combat.get_agent_stats(app.bm, i).hp_max
            for i, pt in enumerate(app.bm.placed_agents)}


def test_a_blocked_record_does_not_shift_the_others():
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "m.png")
        surf = pygame.Surface((COLS * CELL, ROWS * CELL))
        surf.fill((200, 195, 185))
        pygame.image.save(surf, png)
        _write(os.path.join(tmp, "m_terrain.json"), _terrain([]))
        _write(os.path.join(tmp, "m_agents.json"), {"agents": [
            {"name": n, "sprite_path": "", "size": 1, "col": c, "row": 3, "faction": 2}
            for n, c in (("Aria", 1), ("Bram", 2), ("Cole", 3))]})
        agents = os.path.join(tmp, "m_agents.json")
        app = App(png, seed=1)
        app._load_agents(agents)
        for i, pt in enumerate(app.bm.placed_agents):
            s = app.combat.get_agent_stats(app.bm, i)
            s.hp_max = s.hp_cur = HP[pt.name]
            app.combat.set_agent_stats(app.bm, i, s)
        app._save_agents(agents)
        assert _hp_by_name(app) == HP, _hp_by_name(app)

        # A wall now stands on Aria's cell (as a door closed on it would).
        _write(os.path.join(tmp, "m_terrain.json"), _terrain(
            [{"type": "Wall", "x": CELL, "y": 3 * CELL, "width": CELL, "height": CELL,
              "multiplier": 0.0}]))
        app = App(png, seed=1)
        app._load_terrain(os.path.join(tmp, "m_terrain.json"))
        app._load_agents(agents)
        assert app.bm.is_blocked(__import__("rpg_battle_map").Cell(1, 3), 1), "precondition"
        assert _hp_by_name(app) == HP, _hp_by_name(app)
        aria = next(pt for pt in app.bm.placed_agents if pt.name == "Aria")
        assert (aria.origin.col, aria.origin.row) != (1, 3), "moved off the wall"
    print("✅ test_a_blocked_record_does_not_shift_the_others passed")


if __name__ == "__main__":
    test_a_blocked_record_does_not_shift_the_others()
    print("\nAll blocked-load alignment tests passed.")
