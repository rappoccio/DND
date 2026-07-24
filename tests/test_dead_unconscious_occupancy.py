#!/usr/bin/env python3
"""
Test the Dead-vs-Unconscious occupancy split (DIVINE_INTERVENTION_SPEC.md §10).

Two 0-HP states must now behave differently on the board:
  - Unconscious (hp<=0, NOT conditions.dead): the body still BLOCKS its square, like a
    living creature — a mover can't path through it and nothing can be placed on it.
  - Dead (conditions.dead): the corpse FREES its square — a living creature may move
    into / be placed on the cell (the corpse is trampled over).

Both the engine (BattleMap.agent_occupancy) and the Python placement helper
(helpers.can_place_agent) must agree on this — they key off conditions.dead, NOT hp<=0.
The dead/unconscious *rendering* split (red hatch vs grey-out) is verified manually.

See DIVINE_INTERVENTION_SPEC.md §10.3 / §10.6.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)


def _place(engine, bm, name, col, row, faction):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _set_dead(engine, bm, idx, dead):
    cond = engine.get_agent_conditions(bm, idx)
    cond.dead = dead
    engine.set_agent_conditions(bm, idx, cond)


def test_occupancy_split():
    """A downed (unconscious) body blocks its cell; flipping it to dead frees the cell."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    # Two ENEMIES (different factions) adjacent, so occupancy from the mover's view is the
    # impassable "enemy footprint" value (2) while the body is present.
    mover = _place(engine, bm, "Mover",  3, 3, faction=1)
    body  = _place(engine, bm, "Victim", 4, 3, faction=2)
    body_cell = rpg.Cell(4, 3)

    # Drop the victim to 0 HP and route it through the down chokepoint. It is a PC-style
    # agent (not is_npc), so it becomes Unconscious (rolling death saves), NOT dead.
    engine.damage_agent(bm, body, 999)
    engine.apply_unconscious(bm, body)
    cond = engine.get_agent_conditions(bm, body)
    assert not cond.dead, "a downed PC should be unconscious, not dead"

    # Unconscious → the square is BLOCKED for both the engine and the placement helper.
    assert bm.agent_occupancy(body_cell, 1, mover) == 2, \
        "an unconscious enemy body must block its cell (impassable == 2)"
    assert not helpers.can_place_agent(bm, body_cell, 1, exclude_idx=mover), \
        "can_place_agent must refuse a cell held by an unconscious body"

    # Flip to dead → the corpse FREES its square for both.
    _set_dead(engine, bm, body, True)
    assert bm.agent_occupancy(body_cell, 1, mover) == 0, \
        "a corpse must free its cell (occupancy == 0)"
    assert helpers.can_place_agent(bm, body_cell, 1, exclude_idx=mover), \
        "can_place_agent must allow a cell that holds only a corpse"

    print("✅ test_occupancy_split passed")


def test_spawn_lands_on_corpse_not_unconscious():
    """spawnAgent (the summon path) is rejected onto an unconscious body but allowed onto a corpse."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    body = _place(engine, bm, "Victim", 6, 6, faction=2)

    engine.damage_agent(bm, body, 999)
    engine.apply_unconscious(bm, body)

    cfg = rpg.AgentConfig()
    cfg.name, cfg.size, cfg.sprite_path = "Skeleton", 1, "test.png"
    cfg.start_col, cfg.start_row = 6, 6

    # Unconscious body occupies the cell → spawn is rejected (-1).
    assert bm.spawn_agent(cfg) == -1, "spawn must fail onto an unconscious body's cell"

    # Corpse frees the cell → spawn succeeds.
    _set_dead(engine, bm, body, True)
    new_idx = bm.spawn_agent(cfg)
    assert new_idx >= 0, "spawn must succeed onto a corpse's freed cell"

    print("✅ test_spawn_lands_on_corpse_not_unconscious passed")


if __name__ == "__main__":
    test_occupancy_split()
    test_spawn_lands_on_corpse_not_unconscious()
    print("\n✅ All dead/unconscious occupancy tests passed")
