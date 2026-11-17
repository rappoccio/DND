#!/usr/bin/env python3
"""Creatures saved off the current grid.

Set Grid… on a map that already had creatures shrank its grid (a 16 px default to a
91 px drawn square: 67×85 cells → 11×11) and left every creature at its old cell, far
off the new map. They drew clamped into a corner, couldn't be moved, and combat
wouldn't start; loading the PCs again only added a second copy of each.

  · a save with off-grid records loads every creature onto the grid, on distinct open
    cells, in record order (a skipped record would shift stats onto the wrong body);
  · Set Grid… brings creatures the new grid no longer covers back onto it;
  · loading a PC already in the scene doesn't add a second copy.
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

SEED = 20261117
SIDE = 1000         # image px
CELL = 100          # image px → a 10×10 grid

_tmp = tempfile.mkdtemp(prefix="off_grid_")


def _map():
    path = os.path.join(_tmp, "plain.png")
    if not os.path.exists(path):
        surf = pygame.Surface((SIDE, SIDE))
        surf.fill((255, 255, 255))
        pygame.image.save(surf, path)
    return path


def _rec(name, col, row, size=1):
    return {"name": name, "size": size, "col": col, "row": row, "faction": 2}


def _write(name, agents):
    path = os.path.join(_tmp, name)
    with open(path, "w") as f:
        json.dump({"agents": agents, "map_items": []}, f)
    return path


def _cells(app):
    return [(pt.origin.col, pt.origin.row) for pt in app.bm.placed_agents]


def _on_grid(app, col, row, size=1):
    return 0 <= col <= app.bm.grid_cols - size and 0 <= row <= app.bm.grid_rows - size


def test_off_grid_records_load_onto_the_grid():
    app = App(_map(), seed=SEED)
    app.bm.set_uniform_grid(CELL, 0, 0)
    recs = [_rec("Aodhan", 18, 19), _rec("Hilaria", 9, 9), _rec("Keef", 30, 32),
            _rec("Seungho", 30, 33), _rec("Ogre", 40, 2, size=2)]
    app._load_agents(_write("stale.json", recs))
    names = [pt.name for pt in app.bm.placed_agents]
    assert names == [r["name"] for r in recs], f"records dropped or reordered: {names}"
    cells = _cells(app)
    assert cells[1] == (9, 9), "an on-grid creature moved"
    for (c, r), rec in zip(cells, recs):
        assert _on_grid(app, c, r, rec["size"]), f"{rec['name']} still off grid at {(c, r)}"
    taken = set()
    for (c, r), rec in zip(cells, recs):
        foot = {(c + dc, r + dr) for dc in range(rec["size"]) for dr in range(rec["size"])}
        assert not foot & taken, f"{rec['name']} stacked on another creature"
        taken |= foot
    assert any("moved onto it" in m for m in app.combat_log), "no log of the move"
    print("✅ test_off_grid_records_load_onto_the_grid passed")


def test_set_grid_brings_creatures_back_on():
    app = App(_map(), seed=SEED)
    app.bm.set_uniform_grid(CELL // 2, 0, 0)                  # 20×20
    app._load_agents(_write("fine.json", [_rec("Aodhan", 18, 18), _rec("Hilaria", 2, 2)]))
    assert _cells(app) == [(18, 18), (2, 2)]
    app._apply_grid_span(CELL, 0, 0, 5, float(CELL), 1)      # → 10×10
    assert (app.bm.grid_cols, app.bm.grid_rows) == (10, 10)
    assert [pt.name for pt in app.bm.placed_agents] == ["Aodhan", "Hilaria"]
    for c, r in _cells(app):
        assert _on_grid(app, c, r), f"stranded at {(c, r)} after Set Grid"
    with open(app._save_path) as f:
        saved = [(a["col"], a["row"]) for a in json.load(f)["agents"]]
    assert saved == _cells(app), f"the save still holds the old cells: {saved}"
    print("✅ test_set_grid_brings_creatures_back_on passed")


def test_loading_a_pc_already_here_adds_no_copy():
    app = App(_map(), seed=SEED)
    app.bm.set_uniform_grid(CELL, 0, 0)
    app._load_agents(_write("party.json", [_rec("Aodhan", 1, 1)]))
    app._save_agents()
    added, dropped, skipped = app._merge_pcs_here([_rec("Aodhan", 3, 3), _rec("Keef", 4, 4)])
    names = [pt.name for pt in app.bm.placed_agents]
    assert names.count("Aodhan") == 1, f"a second Aodhan was added: {names}"
    assert "Keef" in names
    assert (added, dropped, skipped) == (1, 0, ["Aodhan"])
    print("✅ test_loading_a_pc_already_here_adds_no_copy passed")


def main():
    tests = [test_off_grid_records_load_onto_the_grid,
             test_set_grid_brings_creatures_back_on,
             test_loading_a_pc_already_here_adds_no_copy]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_off_grid_agents: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_off_grid_agents: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
