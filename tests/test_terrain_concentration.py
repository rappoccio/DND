#!/usr/bin/env python3
"""
Test C++ terrain/concentration logic moved into the engine (terrain migration Task 4-7):
- drop_concentration cascade + targeting only the concentration spell's terrain
- tick_terrain_for_turn clearing concentration when a concentration terrain expires
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _set_concentrating(engine, bm, idx, spell_name):
    cond = engine.get_agent_conditions(bm, idx)
    cond.concentrating = True
    cond.concentrating_on = spell_name
    engine.set_agent_conditions(bm, idx, cond)


def test_terrain_concentration_bindings_present():
    """New types/methods are exposed to Python."""
    for name in ["TerrainTickResult", "DropConcentrationResult", "CombatDecider",
                 "BrutalStrikeCtx", "RecklessCtx", "ReactionCtx", "ReactionResponse"]:
        assert hasattr(rpg, name), f"missing binding: {name}"
    engine = setup_combat_engine()
    assert hasattr(engine, "drop_concentration"), "missing combat.drop_concentration"
    assert hasattr(engine, "tick_terrain_for_turn"), "missing combat.tick_terrain_for_turn"
    print("✅ test_terrain_concentration_bindings_present passed")


def test_drop_concentration_noop_when_not_concentrating():
    """drop_concentration on a non-concentrating agent returns dropped=False."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("A", 5, 5))
    res = engine.drop_concentration(bm, idx)
    assert not res.dropped, "should be a no-op when not concentrating"
    print("✅ test_drop_concentration_noop_when_not_concentrating passed")


def test_tick_keeps_concentration_until_expiry():
    """A concentration terrain with >1 turn left does not drop concentration on tick."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    eid = bm.place_terrain_effect("Spike Growth", [rpg.Cell(5, 5)],
                                  rpg.TerrainDifficulty.Quartered, 2, idx,
                                  10, 5, 0, requires_concentration=True)
    assert eid >= 0
    _set_concentrating(engine, bm, idx, "Spike Growth")

    res = engine.tick_terrain_for_turn(bm, idx)
    assert list(res.expired_terrain_ids) == [], "terrain should not expire yet"
    assert not res.concentration.dropped
    assert engine.get_agent_conditions(bm, idx).concentrating, "concentration lost too early"
    print("✅ test_tick_keeps_concentration_until_expiry passed")


def test_tick_clears_concentration_on_expiry():
    """When a concentration terrain expires, the caster's concentration is cleared (C++)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    eid = bm.place_terrain_effect("Spike Growth", [rpg.Cell(5, 5), rpg.Cell(6, 5)],
                                  rpg.TerrainDifficulty.Quartered, 1, idx,
                                  10, 5, 0, requires_concentration=True)
    assert eid >= 0
    _set_concentrating(engine, bm, idx, "Spike Growth")

    res = engine.tick_terrain_for_turn(bm, idx)
    assert eid in list(res.expired_terrain_ids), "terrain should have expired"
    assert res.concentration.dropped, "concentration should drop when its terrain expires"
    assert not engine.get_agent_conditions(bm, idx).concentrating, "concentration flag still set"
    assert not bm.has_active_terrain_effects(), "expired terrain not removed"
    print("✅ test_tick_clears_concentration_on_expiry passed")


def test_tick_nonconcentration_terrain_keeps_concentration():
    """Expiry of a NON-concentration terrain must not drop unrelated concentration."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    # Non-concentration timed terrain (e.g. Grease) sourced by the same agent.
    eid = bm.place_terrain_effect("Grease", [rpg.Cell(5, 5)],
                                  rpg.TerrainDifficulty.Slipping, 1, idx,
                                  10, 5, 0, requires_concentration=False)
    assert eid >= 0
    _set_concentrating(engine, bm, idx, "Some Other Spell")

    res = engine.tick_terrain_for_turn(bm, idx)
    assert eid in list(res.expired_terrain_ids), "non-concentration terrain should expire"
    assert not res.concentration.dropped, "must not drop concentration for non-concentration terrain"
    assert engine.get_agent_conditions(bm, idx).concentrating, "concentration wrongly cleared"
    print("✅ test_tick_nonconcentration_terrain_keeps_concentration passed")


def test_drop_concentration_leaves_nonconcentration_terrain():
    """drop_concentration removes only the concentration spell's terrain, not unrelated terrain."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    eid_conc = bm.place_terrain_effect("Spike Growth", [rpg.Cell(5, 5)],
                                       rpg.TerrainDifficulty.Quartered, 5, idx,
                                       10, 5, 0, requires_concentration=True)
    eid_noconc = bm.place_terrain_effect("Grease", [rpg.Cell(7, 7)],
                                         rpg.TerrainDifficulty.Slipping, 5, idx,
                                         10, 5, 0, requires_concentration=False)
    assert eid_conc >= 0 and eid_noconc >= 0
    _set_concentrating(engine, bm, idx, "Spike Growth")

    res = engine.drop_concentration(bm, idx)
    assert res.dropped
    assert eid_conc in list(res.removed_terrain_ids), "concentration terrain should be removed"
    remaining = [e.id for e in bm.active_terrain_effects]
    assert eid_noconc in remaining, "non-concentration terrain should remain"
    assert eid_conc not in remaining, "concentration terrain should be gone"
    print("✅ test_drop_concentration_leaves_nonconcentration_terrain passed")


def _make_condition_spell(name, geometry):
    spell = rpg.Spell()
    spell.name = name
    spell.level = 0  # avoid slot requirements
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Strength
    spell.geometry = geometry
    spell.range = 90
    spell.width = 10
    spell.length = 10
    spell.duration = 10
    spell.requires_concentration = True
    cond = rpg.AttackCondition()
    cond.condition_name = "Restrained"
    cond.requires_save = True
    cond.save_ability = rpg.SaveAbility.Strength
    cond.condition_duration = 0
    spell.conditions = [cond]
    return spell


def test_aoe_concentration_holds_with_no_targets():
    """An AoE condition spell cast on empty ground still establishes concentration:
    the area persists even with no creatures currently caught."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    stats = engine.get_agent_stats(bm, caster_idx)
    stats.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, stats)

    engine.set_agent_spells(bm, caster_idx, [_make_condition_spell("Black Tentacles", rpg.SpellGeometry.Square)])

    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.aoe_col = 9  # far from the caster — no creature in the area
    action.aoe_row = 9
    result = engine.execute_spell(bm, action)
    assert result.valid, "AoE cast on empty ground should be a valid cast"
    assert engine.get_agent_conditions(bm, caster_idx).concentrating, \
        "AoE concentration spell must hold concentration even with no targets in area"
    print("✅ test_aoe_concentration_holds_with_no_targets passed")


def test_multiple_target_concentration_drops_with_no_targets():
    """A Multiple-target condition spell with no targets affected does NOT concentrate."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    stats = engine.get_agent_stats(bm, caster_idx)
    stats.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, stats)

    engine.set_agent_spells(bm, caster_idx, [_make_condition_spell("Hold Monster", rpg.SpellGeometry.Multiple)])

    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.target_indices = []  # no targets selected
    result = engine.execute_spell(bm, action)
    # No condition could land with zero targets -> concentration should not be established.
    assert not engine.get_agent_conditions(bm, caster_idx).concentrating, \
        "Multiple-target spell with no affected targets must not hold concentration"
    print("✅ test_multiple_target_concentration_drops_with_no_targets passed")


def test_clear_all_concentration():
    """clear_all_concentration (End Combat) drops concentration + cascades for every agent."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("CasterA", 5, 5))
    b = add_agent_to_battle(engine, bm, create_test_agent("CasterB", 7, 7))
    for idx, name, cell in [(a, "Spike Growth", rpg.Cell(5, 5)), (b, "Web", rpg.Cell(7, 7))]:
        bm.place_terrain_effect(name, [cell], rpg.TerrainDifficulty.Quartered, 5, idx, 10, 5, 0,
                                requires_concentration=True)
        c = engine.get_agent_conditions(bm, idx)
        c.concentrating = True
        c.concentrating_on = name
        engine.set_agent_conditions(bm, idx, c)
    assert bm.has_active_terrain_effects()

    engine.clear_all_concentration(bm)
    assert not engine.get_agent_conditions(bm, a).concentrating, "A's concentration should be cleared"
    assert not engine.get_agent_conditions(bm, b).concentrating, "B's concentration should be cleared"
    assert not bm.has_active_terrain_effects(), "concentration terrain should be cleared too"
    print("✅ test_clear_all_concentration passed")


if __name__ == "__main__":
    test_terrain_concentration_bindings_present()
    test_drop_concentration_noop_when_not_concentrating()
    test_tick_keeps_concentration_until_expiry()
    test_tick_clears_concentration_on_expiry()
    test_tick_nonconcentration_terrain_keeps_concentration()
    test_drop_concentration_leaves_nonconcentration_terrain()
    test_aoe_concentration_holds_with_no_targets()
    test_multiple_target_concentration_drops_with_no_targets()
    test_clear_all_concentration()
    print("\n✅ All terrain/concentration tests passed!")
