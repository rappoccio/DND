#!/usr/bin/env python3
"""
Summoning system — engine-level tests (SUMMONING_PLAN.md, Phases 1-3).

Covers the C++ pieces that the GUI summon flow relies on:
- bm.spawn_agent appends a single agent WITHOUT clearing existing agents/state.
- PlacedAgent summon fields (summoner_idx / summon_spell / removed_from_play) + accessors.
- drop_concentration tombstones the caster's summons and reports them in dismissed_summons,
  WITHOUT erasing them (indices stay valid).
- Losing concentration to damage also cascades the dismissal.

The GUI placement dialog / initiative insertion are pygame-driven and not unit-tested here.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from helpers import can_place_agent, summon_cell_placeable


def _spawn_summon(bm, name, col, row, summoner_idx, spell="Summon Dragon"):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = "test.png"
    idx = bm.spawn_agent(cfg)
    assert idx >= 0, "spawn_agent should succeed on an open cell"
    bm.set_agent_summoner_idx(idx, summoner_idx)
    bm.set_agent_summon_spell(idx, spell)
    return idx


def _set_concentrating(engine, bm, idx, spell_name):
    cond = engine.get_agent_conditions(bm, idx)
    cond.concentrating = True
    cond.concentrating_on = spell_name
    engine.set_agent_conditions(bm, idx, cond)


def test_summon_bindings_present():
    """New summon bindings are exposed to Python."""
    bm = setup_battle_map()
    for m in ["spawn_agent", "get_agent_summoner_idx", "set_agent_summoner_idx",
              "get_agent_summon_spell", "set_agent_summon_spell",
              "is_agent_removed_from_play", "set_agent_removed_from_play"]:
        assert hasattr(bm, m), f"missing BattleMap binding: {m}"
    assert hasattr(rpg.DropConcentrationResult, "dismissed_summons"), \
        "DropConcentrationResult.dismissed_summons missing"
    print("✅ test_summon_bindings_present passed")


def test_spawn_agent_is_non_destructive():
    """spawn_agent appends one agent and preserves existing agents' runtime state."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5), hp=40)
    # Mutate the caster's runtime HP so we can prove it survives a spawn.
    st = engine.get_agent_stats(bm, caster)
    st.hp_cur = 17
    engine.set_agent_stats(bm, caster, st)

    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert summon == len(bm.placed_agents) - 1, "summon should be the last placed agent"
    assert len(bm.placed_agents) == 2
    # Existing caster state is untouched (apply_agent_configs would have wiped it).
    assert engine.get_agent_stats(bm, caster).hp_cur == 17, "spawn clobbered caster HP"
    assert bm.get_agent_summoner_idx(summon) == caster
    assert bm.get_agent_summon_spell(summon) == "Summon Dragon"
    assert not bm.is_agent_removed_from_play(summon)
    print("✅ test_spawn_agent_is_non_destructive passed")


def test_spawn_agent_blocked_cell_returns_negative():
    """spawn_agent onto an occupied/blocked cell returns -1 (no agent added)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    _spawn_summon(bm, "First", 6, 6, caster)
    before = len(bm.placed_agents)
    # Same cell as the first summon → blocked.
    cfg = rpg.AgentConfig()
    cfg.name = "Second"
    cfg.start_col = 6
    cfg.start_row = 6
    cfg.size = 1
    cfg.sprite_path = "test.png"
    assert bm.spawn_agent(cfg) == -1, "expected -1 on a blocked cell"
    assert len(bm.placed_agents) == before, "no agent should have been added"
    print("✅ test_spawn_agent_blocked_cell_returns_negative passed")


def test_drop_concentration_dismisses_summon():
    """Losing concentration tombstones the caster's summons and reports them."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    res = engine.drop_concentration(bm, caster)
    assert res.dropped
    assert summon in list(res.dismissed_summons), "summon not reported as dismissed"
    assert bm.is_agent_removed_from_play(summon), "summon should be tombstoned"
    # Tombstone, NOT erase: the agent is still in the vector so indices stay valid.
    assert len(bm.placed_agents) == 2, "summon must not be erased"
    print("✅ test_drop_concentration_dismisses_summon passed")


def test_dismissed_summon_moved_off_map():
    """A dismissed summon is banished to (-1,-1) so its old cell no longer collides
    with movement/placement on the real grid (while its index stays valid)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert bm.placed_agents[summon].origin.col == 6
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    engine.drop_concentration(bm, caster)
    off = bm.placed_agents[summon].origin
    assert (off.col, off.row) == (-1, -1), f"summon should be off-map, got ({off.col},{off.row})"
    assert len(bm.placed_agents) == 2, "summon must not be erased"
    assert can_place_agent(bm, rpg.Cell(6, 6), 1), "the freed cell should be placeable again"
    print("✅ test_dismissed_summon_moved_off_map passed")


def test_unrelated_summon_not_dismissed():
    """Dropping caster A's concentration leaves caster B's summon alone."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 2, 2))
    b = add_agent_to_battle(engine, bm, create_test_agent("B", 8, 8))
    sa = _spawn_summon(bm, "A-Summon", 3, 3, a)
    sb = _spawn_summon(bm, "B-Summon", 9, 9, b)
    _set_concentrating(engine, bm, a, "Summon Dragon")
    _set_concentrating(engine, bm, b, "Summon Dragon")

    res = engine.drop_concentration(bm, a)
    assert sa in list(res.dismissed_summons)
    assert sb not in list(res.dismissed_summons)
    assert bm.is_agent_removed_from_play(sa)
    assert not bm.is_agent_removed_from_play(sb), "B's summon wrongly dismissed"
    print("✅ test_unrelated_summon_not_dismissed passed")


def test_damage_breaking_concentration_dismisses_summon():
    """A failed concentration save from damage also cascades the summon dismissal."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5, con=10), hp=40)
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    # concentration_save rolls a CON save (DC = max(10, damage/2)); a high damage value makes
    # a failure very likely. On a failed save the engine routes through dropConcentration, which
    # must tombstone the summon via the same cascade.
    res = engine.concentration_save(bm, caster, 60)
    assert res.checked, "a concentrating agent should have to save"

    if res.concentration_lost:
        assert bm.is_agent_removed_from_play(summon), \
            "concentration broke but summon was not dismissed"
        print("✅ test_damage_breaking_concentration_dismisses_summon passed (broke + dismissed)")
    else:
        # Save succeeded (RNG): concentration held, so the summon must remain in play.
        assert not bm.is_agent_removed_from_play(summon)
        print("✅ test_damage_breaking_concentration_dismisses_summon passed (held)")


def test_placement_in_range_and_empty_is_valid():
    """A nearby empty cell with line of sight is a legal summon spot."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    origin = bm.placed_agents[caster].origin
    assert summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 60), \
        "adjacent empty cell within range should be valid"
    print("✅ test_placement_in_range_and_empty_is_valid passed")


def test_placement_out_of_range_is_invalid():
    """Beyond the spell's range the cell is rejected, but a closer one is allowed."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    origin = bm.placed_agents[caster].origin
    # range 5 ft = one cell: three cells away is out of range, adjacent is in range.
    assert not summon_cell_placeable(bm, origin, 1, rpg.Cell(8, 5), 1, 5), "should be out of range"
    assert summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 5), "adjacent should be in range"
    print("✅ test_placement_out_of_range_is_invalid passed")


def test_placement_on_occupied_cell_is_invalid():
    """A cell occupied by another live agent is not a legal summon spot."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    origin = bm.placed_agents[caster].origin
    assert not summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 60), \
        "occupied cell should be rejected"
    print("✅ test_placement_on_occupied_cell_is_invalid passed")


def test_can_place_ignores_tombstoned_summon():
    """A dismissed (tombstoned) summon frees its cell for placement again."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert not can_place_agent(bm, rpg.Cell(6, 6), 1), "live summon should block its cell"
    bm.set_agent_removed_from_play(summon, True)
    assert can_place_agent(bm, rpg.Cell(6, 6), 1), "tombstoned summon should free its cell"
    print("✅ test_can_place_ignores_tombstoned_summon passed")


def test_can_place_out_of_bounds_is_invalid():
    """Cells off the grid (negative or past the edge) are rejected."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    assert not can_place_agent(bm, rpg.Cell(-1, 5), 1), "negative cell should be rejected"
    assert not can_place_agent(bm, rpg.Cell(bm.grid_cols, 5), 1), "past-edge cell should be rejected"
    print("✅ test_can_place_out_of_bounds_is_invalid passed")


if __name__ == "__main__":
    test_summon_bindings_present()
    test_spawn_agent_is_non_destructive()
    test_spawn_agent_blocked_cell_returns_negative()
    test_drop_concentration_dismisses_summon()
    test_dismissed_summon_moved_off_map()
    test_unrelated_summon_not_dismissed()
    test_damage_breaking_concentration_dismisses_summon()
    test_placement_in_range_and_empty_is_valid()
    test_placement_out_of_range_is_invalid()
    test_placement_on_occupied_cell_is_invalid()
    test_can_place_ignores_tombstoned_summon()
    test_can_place_out_of_bounds_is_invalid()
    print("\nAll summoning tests passed!")
