#!/usr/bin/env python3
"""
Test Divine Intervention — Phase D4 (Magic Circle / the creature-type movement ward).

D4 adds an emanation that forbids chosen creature types (Fiend, Fey, …) from crossing its
boundary — a wall that only the warded species can't pass. Two directions: keep-out (the RAW
default) and trap-inside (the "reverse direction" clause).

Engine coverage here:
  - creates_movement_ward round-trips through the spell serializers (JSON → Spell → dict → Spell).
  - A ward placed via place_terrain_effect blocks a warded creature (is_fiend) from ENTERING its
    cells, while a typeless creature (Humanoid) walks in freely. (keep-out mode)
  - Reverse mode traps a warded creature INSIDE: it may move cell-to-cell within the zone but can't
    step out; a typeless creature leaves freely.
  - Casting Magic Circle (execute_spell) lays a terrain ward carrying the chosen creature mask,
    and a warded creature can't reach the circle's interior.
  - A creature whose type is NOT in the ward mask crosses freely (selectivity).

See DIVINE_INTERVENTION_SPEC.md §7 (D4).
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1
_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")

# A solid 3×3 ward footprint centered on (5,5): cols 4-6 × rows 4-6.
WARD_CELLS = [rpg.Cell(c, r) for c in (4, 5, 6) for r in (4, 5, 6)]


def _load_spell(name):
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry)
    raise AssertionError(f"{name} not found in spells.json")


def _place(engine, bm, name, col, row, faction=TEAM, **flags):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = 60
    for k, v in flags.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)
    return idx


def _reach(bm, idx, speed=60):
    """Set of (col,row) tuples this agent can reach on foot (Dijkstra, ward-aware)."""
    origin = bm.placed_agents[idx].origin
    return {(c.col, c.row)
            for c in bm.reachable_cells(origin, 1, speed, rpg.MovementType.Walk, idx)}


def _try_walk(engine, bm, idx, col, row):
    """Seed the agent's budget and attempt a real walk; return whether it committed."""
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(60)
    return engine.move_agent(bm, idx, rpg.Cell(col, row), rpg.MovementType.Walk)


def test_creates_movement_ward_round_trips():
    """creates_movement_ward survives JSON load and a dict round-trip."""
    sp = _load_spell("Magic Circle")
    assert getattr(sp, "creates_movement_ward", False), \
        "Magic Circle should load with creates_movement_ward=True"
    again = helpers._dict_to_spell(helpers._spell_to_dict(sp))
    assert again.creates_movement_ward, "creates_movement_ward should survive a serializer round-trip"
    print("✅ test_creates_movement_ward_round_trips passed")


def test_ward_blocks_warded_type_from_entering():
    """A Fiend can't walk into a Fiend ward; a typeless Humanoid walks in freely (keep-out)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    bm.place_terrain_effect("Magic Circle", WARD_CELLS, rpg.TerrainDifficulty.Normal, 100, -1,
                            ward_creature_mask=int(rpg.CreatureType.Fiend), ward_traps=False)

    fiend = _place(engine, bm, "Balor", 5, 1, is_fiend=True)   # north of the zone
    human = _place(engine, bm, "Fighter", 5, 9)               # south of the zone, typeless

    # The zone is not difficult terrain — it imposes no speed penalty on anyone.
    assert bm.get_terrain_multiplier(rpg.Cell(5, 5)) == 1.0, "ward must not slow movement"

    freach = _reach(bm, fiend)
    assert (5, 3) in freach, "the fiend can approach up to the ward's edge"
    for cell in ((5, 4), (5, 5), (5, 6)):
        assert cell not in freach, f"the fiend must not be able to enter ward cell {cell}"
    assert not _try_walk(engine, bm, fiend, 5, 5), "the fiend can't commit a move into the circle"

    hreach = _reach(bm, human)
    assert (5, 5) in hreach, "a typeless creature is not warded — it can enter the circle"
    assert _try_walk(engine, bm, human, 5, 5), "a typeless creature walks into the circle"
    print("✅ test_ward_blocks_warded_type_from_entering passed")


def test_reverse_ward_traps_warded_type_inside():
    """Reverse Magic Circle: a Fiend inside can move within the zone but can't leave; a typeless
    creature inside leaves freely."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    bm.place_terrain_effect("Magic Circle", WARD_CELLS, rpg.TerrainDifficulty.Normal, 100, -1,
                            ward_creature_mask=int(rpg.CreatureType.Fiend), ward_traps=True)

    fiend = _place(engine, bm, "Balor", 5, 5, is_fiend=True)   # inside the zone

    freach = _reach(bm, fiend)
    assert freach and all(cell in {(c.col, c.row) for c in WARD_CELLS} for cell in freach), \
        "a trapped fiend can only reach cells inside the ward"
    assert _try_walk(engine, bm, fiend, 4, 5), "the fiend may still move within the zone"

    # Reset it inside and confirm it cannot step out.
    bm.set_agent_position(fiend, rpg.Cell(5, 5))
    assert not _try_walk(engine, bm, fiend, 5, 1), "the trapped fiend can't leave the zone"

    # A typeless creature placed inside is not trapped.
    human = _place(engine, bm, "Fighter", 6, 6)
    assert _try_walk(engine, bm, human, 6, 9), "a typeless creature leaves the reverse ward freely"
    print("✅ test_reverse_ward_traps_warded_type_inside passed")


def test_ward_is_selective_by_type():
    """A ward against Fey does not block a Fiend (only the chosen types are warded)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    bm.place_terrain_effect("Magic Circle", WARD_CELLS, rpg.TerrainDifficulty.Normal, 100, -1,
                            ward_creature_mask=int(rpg.CreatureType.Fey), ward_traps=False)
    fiend = _place(engine, bm, "Balor", 5, 1, is_fiend=True)
    assert (5, 5) in _reach(bm, fiend), "a Fiend is not warded by a Fey-only circle"
    assert _try_walk(engine, bm, fiend, 5, 5), "the Fiend walks through a Fey ward"
    print("✅ test_ward_is_selective_by_type passed")


def test_cast_magic_circle_places_ward():
    """Casting Magic Circle lays a terrain ward carrying the chosen creature mask, and a warded
    creature can't reach the circle's interior."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    fiend = _place(engine, bm, "Pit Fiend", 10, 5, is_fiend=True)

    # Arm the caster AFTER every agent is placed: add_agent_to_battle rebuilds all agents and
    # restores stats/conditions but NOT spells, so a spell set before the last placement is wiped.
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [_load_spell("Magic Circle")])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 3
    action.aoe_col, action.aoe_row = 5, 5
    action.ward_creature_mask = int(rpg.CreatureType.Fiend)
    action.ward_traps = False
    engine.execute_spell(bm, action)

    wards = [t for t in bm.active_terrain_effects if t.ward_creature_mask != 0]
    assert wards, "casting Magic Circle should create a movement-ward terrain effect"
    assert wards[0].ward_creature_mask & int(rpg.CreatureType.Fiend), \
        "the ward must carry the chosen Fiend bit"
    assert not wards[0].ward_traps, "default cast is keep-out, not trap-inside"

    # The circle center is warded ground the Pit Fiend can't reach.
    assert (5, 5) not in _reach(bm, fiend), "the summoned Fiend is blocked from the magic circle"
    print("✅ test_cast_magic_circle_places_ward passed")


if __name__ == "__main__":
    test_creates_movement_ward_round_trips()
    test_ward_blocks_warded_type_from_entering()
    test_reverse_ward_traps_warded_type_inside()
    test_ward_is_selective_by_type()
    test_cast_magic_circle_places_ward()
    print("\n✅ All Magic Circle (D4) tests passed")
