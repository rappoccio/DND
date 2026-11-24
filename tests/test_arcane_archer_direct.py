#!/usr/bin/env python3
"""
Arcane Archer: direct engine calls for the two bindings no other suite names.

Written as the baseline before the riders/resources class-family split moves their bodies
(plans/COMBAT_REFACTOR_PLAN.md, R4 follow-on), so a move that changes them shows up here.

  · piercing_shot_cells: the 30-ft line toward the aim cell, pinned for straight, diagonal and
    backward aims; a bad archer index gives no cells                     (test_piercing_cells_*)
  · apply_masterful_shots, called directly (no reaction window):
      - default (-1,-1) moves to the engine's cell, spends the Reaction, shoots, and clears the
        Arcane Shot / Curving Shot offers                                (test_masterful_direct_default)
      - an explicit legal cell is used as given                          (test_masterful_direct_explicit)
      - an illegal cell, or no Reaction, does nothing                    (test_masterful_direct_refused)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gui'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import rpg_battle_map as rpg
from test_arcane_archer_high import _scene


def _cells(engine, bm, arc, col, row):
    return [(c.col, c.row) for c in engine.piercing_shot_cells(bm, arc, col, row)]


def test_piercing_cells_straight():
    bm, engine, arc, orc = _scene()            # archer at (10,10)
    assert _cells(engine, bm, arc, 16, 10) == [(c, 10) for c in range(11, 17)], "east, 6 squares"
    assert _cells(engine, bm, arc, 10, 16) == [(10, r) for r in range(11, 17)], "south, 6 squares"
    assert _cells(engine, bm, arc, 4, 10) == [(c, 10) for c in range(4, 10)], "west, 6 squares"
    print("✅ test_piercing_cells_straight")


def test_piercing_cells_diagonal():
    bm, engine, arc, orc = _scene()
    assert _cells(engine, bm, arc, 20, 20) == [(11, 11), (12, 12), (13, 13), (14, 14)]
    print("✅ test_piercing_cells_diagonal")


def test_piercing_cells_bad_index():
    bm, engine, arc, orc = _scene()
    assert _cells(engine, bm, 99, 16, 10) == []
    assert _cells(engine, bm, -1, 16, 10) == []
    print("✅ test_piercing_cells_bad_index")


def _offers_on(engine, bm, arc):
    c = engine.get_agent_conditions(bm, arc)
    c.arcane_shot_available = True
    c.curving_shot_available = True
    engine.set_agent_conditions(bm, arc, c)


def test_masterful_direct_default():
    bm, engine, arc, orc = _scene()
    _offers_on(engine, bm, arc)
    expect = engine.masterful_shots_destination(bm, arc, orc)
    r = engine.apply_masterful_shots(bm, arc, orc)
    assert r.valid, "a legal Masterful Shots makes an attack"
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (expect.col, expect.row), "moved to the engine's cell"
    c = engine.get_agent_conditions(bm, arc)
    assert c.reaction_used, "spends the Reaction"
    assert not c.arcane_shot_available and not c.curving_shot_available, "offers cleared"
    print("✅ test_masterful_direct_default")


def test_masterful_direct_explicit():
    bm, engine, arc, orc = _scene()
    assert engine.is_masterful_shots_destination(bm, arc, orc, rpg.Cell(8, 10))
    r = engine.apply_masterful_shots(bm, arc, orc, 8, 10)
    assert r.valid
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (8, 10), "the given cell"
    print("✅ test_masterful_direct_explicit")


def test_masterful_direct_refused():
    bm, engine, arc, orc = _scene()
    r = engine.apply_masterful_shots(bm, arc, orc, 6, 10)      # 20 ft: beyond half Speed
    assert not r.valid
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (10, 10), "did not move"
    assert not engine.get_agent_conditions(bm, arc).reaction_used, "Reaction kept"

    c = engine.get_agent_conditions(bm, arc); c.reaction_used = True
    engine.set_agent_conditions(bm, arc, c)
    hp0 = engine.get_agent_stats(bm, orc).hp_cur
    r = engine.apply_masterful_shots(bm, arc, orc)
    assert not r.valid, "no Reaction, no shot"
    assert engine.get_agent_stats(bm, orc).hp_cur == hp0
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (10, 10)
    print("✅ test_masterful_direct_refused")


if __name__ == "__main__":
    test_piercing_cells_straight()
    test_piercing_cells_diagonal()
    test_piercing_cells_bad_index()
    test_masterful_direct_default()
    test_masterful_direct_explicit()
    test_masterful_direct_refused()
    print("\nAll Arcane Archer direct-call tests passed ✅")
