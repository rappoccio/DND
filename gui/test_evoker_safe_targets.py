#!/usr/bin/env python3
"""
Test Evoker "safe targets": creatures fully excluded from a caster's AoE spells
(manually selected for now; later auto-populated from the player's party).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _aoe_spell():
    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 0  # cantrip-level avoids spell-slot requirements in the test
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Dexterity
    spell.geometry = rpg.SpellGeometry.Sphere
    spell.radius = 20
    spell.range = 120
    return spell


def _setup():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Evoker", 2, 2))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 8), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 9), hp=100)
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [_aoe_spell()])
    return bm, engine, caster, ally, enemy


def _cast(engine, bm, caster):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.aoe_col = 8
    action.aoe_row = 8
    return engine.execute_spell(bm, action)


def test_safe_targets_get_set_roundtrip():
    bm, engine, caster, ally, enemy = _setup()
    assert list(engine.get_safe_targets(caster)) == [], "should default to empty"
    engine.set_safe_targets(caster, [ally, enemy])
    assert sorted(engine.get_safe_targets(caster)) == sorted([ally, enemy])
    print("✅ test_safe_targets_get_set_roundtrip passed")


def test_aoe_hits_all_without_safe_list():
    bm, engine, caster, ally, enemy = _setup()
    hit = {tr.target_idx for tr in _cast(engine, bm, caster).target_results}
    assert ally in hit and enemy in hit, f"baseline: both should be in the AoE, got {hit}"
    print("✅ test_aoe_hits_all_without_safe_list passed")


def test_safe_target_excluded_from_aoe():
    bm, engine, caster, ally, enemy = _setup()
    engine.set_safe_targets(caster, [ally])
    hit = {tr.target_idx for tr in _cast(engine, bm, caster).target_results}
    assert enemy in hit, "enemy should still be hit by the AoE"
    assert ally not in hit, "safe ally must be fully excluded from the AoE"
    print("✅ test_safe_target_excluded_from_aoe passed")


def test_safe_list_does_not_affect_other_casters():
    bm, engine, caster, ally, enemy = _setup()
    # ally itself casts the same AoE; caster's safe list must not protect anyone for the ally.
    engine.set_agent_spells(bm, ally, [_aoe_spell()])
    s = engine.get_agent_stats(bm, ally); s.can_cast_spell = True
    engine.set_agent_stats(bm, ally, s)
    engine.set_safe_targets(caster, [ally, enemy])  # only the caster's list

    action = rpg.SpellAction()
    action.caster_idx = ally
    action.spell_idx = 0
    action.aoe_col = 8
    action.aoe_row = 8
    hit = {tr.target_idx for tr in engine.execute_spell(bm, action).target_results}
    assert enemy in hit, "ally's own AoE should not honor the caster's safe list"
    print("✅ test_safe_list_does_not_affect_other_casters passed")


if __name__ == "__main__":
    test_safe_targets_get_set_roundtrip()
    test_aoe_hits_all_without_safe_list()
    test_safe_target_excluded_from_aoe()
    test_safe_list_does_not_affect_other_casters()
    print("\n✅ All Evoker safe-target tests passed!")
