#!/usr/bin/env python3
"""
Infra A — class-feature cast pipeline. A "spell" with a `resource_name` spends that
resource (e.g. Channel Divinity) instead of a spell slot: it is gated on the resource
in available_castable_spells and decrements it (not a slot) on cast.

NOTE: arm the cleric *after* all agents are placed — add_agent_to_battle calls
apply_agent_configs, which rebuilds every agent from its config and discards any
prior set_agent_stats.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _add(engine, bm, name, col, row, hp=40):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=hp)


def _divine_spark_harm(num_dice=2, bonus=3):
    s = rpg.Spell()
    s.name = "Divine Spark (Harm)"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.Constitution
    s.range = 30
    s.level = 0
    s.resource_name = "Channel Divinity"
    s.resource_cost = 1
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Radiant
    roll.num_dice = num_dice
    roll.die_size = 8
    roll.bonus = bonus
    s.magic_damage_rolls = [roll]
    return s


def _arm_cleric(engine, bm, idx, level=5):
    """Configure a placed agent as a Cleric with Channel Divinity + Divine Spark.
    Call AFTER all agents are added (see module note)."""
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.char_level = level
    s.wis = 16
    s.hp_max = 40
    s.hp_cur = 40
    s.can_cast_spell = True
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, [_divine_spark_harm()])


def _cd(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).resources["Channel Divinity"].current


def test_feature_castable_while_resource_remains():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    _arm_cleric(engine, bm, cleric)
    assert _cd(engine, bm, cleric) > 0, "Cleric should start with Channel Divinity"
    castable = list(engine.available_castable_spells(bm, cleric))
    assert castable == [0], f"feature should be castable while CD remains, got {castable}"
    print("✅ test_feature_castable_while_resource_remains passed")


def test_cast_spends_resource_and_deals_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    enemy = _add(engine, bm, "Zombie", 6, 5, hp=200)
    _arm_cleric(engine, bm, cleric)

    before = _cd(engine, bm, cleric)
    action = rpg.SpellAction()
    action.caster_idx = cleric
    action.spell_idx = 0
    action.target_indices = [enemy]
    res = engine.execute_spell(bm, action)

    assert res.valid, "cast should be valid"
    assert _cd(engine, bm, cleric) == before - 1, "casting must spend exactly 1 Channel Divinity"
    assert engine.get_agent_stats(bm, enemy).hp_cur < 200, "Divine Spark should damage the target"
    print("✅ test_cast_spends_resource_and_deals_damage passed")


def test_no_spell_slot_consumed():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    enemy = _add(engine, bm, "Zombie", 6, 5, hp=200)
    _arm_cleric(engine, bm, cleric)

    slots_before = list(engine.get_agent_stats(bm, cleric).spell_slots_remaining)
    action = rpg.SpellAction()
    action.caster_idx = cleric; action.spell_idx = 0; action.target_indices = [enemy]
    engine.execute_spell(bm, action)
    slots_after = list(engine.get_agent_stats(bm, cleric).spell_slots_remaining)
    assert slots_after == slots_before, "a class feature must not consume a spell slot"
    print("✅ test_no_spell_slot_consumed passed")


def test_unavailable_when_resource_exhausted():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    enemy = _add(engine, bm, "Zombie", 6, 5, hp=400)
    _arm_cleric(engine, bm, cleric)

    # Spend Channel Divinity down to zero through real casts.
    for _ in range(10):
        if not engine.available_castable_spells(bm, cleric):
            break
        action = rpg.SpellAction()
        action.caster_idx = cleric; action.spell_idx = 0; action.target_indices = [enemy]
        engine.execute_spell(bm, action)

    assert _cd(engine, bm, cleric) == 0, "Channel Divinity should be exhausted"
    assert list(engine.available_castable_spells(bm, cleric)) == [], \
        "feature must drop out of the castable list once its resource is gone"
    print("✅ test_unavailable_when_resource_exhausted passed")


if __name__ == "__main__":
    test_feature_castable_while_resource_remains()
    test_cast_spends_resource_and_deals_damage()
    test_no_spell_slot_consumed()
    test_unavailable_when_resource_exhausted()
    print("\n✅ All class-feature pipeline tests passed!")
