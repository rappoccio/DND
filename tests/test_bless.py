#!/usr/bin/env python3
"""
Test Bless (Phase 1):
  - Level 1, Concentration, up to 3 creatures (+1 per slot level above 1).
  - Each target adds 1d4 to every attack roll and saving throw while the spell lasts.
  - The buff is a Stats flag (`blessed`) applied via a "Blessed" AgentCondition; it dies with
    the caster's concentration and is torn down through the Phase-0.1 chokepoint.

Bless targets allies, so all agents share one faction here (a caster may bless itself too).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle, create_melee_weapon)

TEAM = 1


def _make_bless():
    """Build the Bless spell exactly as spells.json now defines it."""
    sp = rpg.Spell()
    sp.name = "Bless"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Multiple
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = 1
    sp.duration = 10
    sp.num_targets = 3
    sp.targets_per_upcast_level = 1
    sp.requires_concentration = True

    cond = rpg.AttackCondition()
    cond.condition_name = "Blessed"
    cond.requires_save = False
    cond.condition_duration = 0   # 0 → inherit the spell's duration
    sp.conditions = [cond]
    return sp


def _place(engine, bm, name, col, row, faction=TEAM):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, idx, s)


def test_three_targets_blessed():
    """A level-1 Bless flags all three targets with `blessed`."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    t1 = _place(engine, bm, "Ally1", 6, 5)
    t2 = _place(engine, bm, "Ally2", 7, 5)
    t3 = _place(engine, bm, "Ally3", 4, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_bless()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [t1, t2, t3]
    engine.execute_spell(bm, action)

    for idx in (t1, t2, t3):
        assert engine.get_agent_stats(bm, idx).blessed, f"target {idx} should be blessed"
    assert engine.get_agent_conditions(bm, caster).concentrating, "caster should be concentrating"
    print("✅ test_three_targets_blessed passed")


def test_save_gains_1d4():
    """A blessed creature's saving-throw modifier gains 1..4 over its unblessed value."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_bless()])

    base = engine.save_mod_for(bm, ally, rpg.SaveAbility.Dexterity)  # unblessed baseline (DEX 10 → 0)

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [ally]
    engine.execute_spell(bm, action)

    for _ in range(30):
        d = engine.save_mod_for(bm, ally, rpg.SaveAbility.Dexterity) - base
        assert 1 <= d <= 4, f"Bless should add 1..4 to a save, got {d}"
    print("✅ test_save_gains_1d4 passed")


def test_attack_gains_1d4():
    """A blessed attacker's to-hit total gains 1..4 (the Bless d4), reported outside attack_mod."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Fighter", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_bless()])
    weapon = create_melee_weapon()

    # Unblessed: total_roll == d20 + attack_mod exactly (Bless folds into neither).
    unblessed = engine.get_agent_stats(bm, ally)
    for _ in range(30):
        r = engine.roll_to_hit(weapon, unblessed, 10)
        assert r.total_roll - r.d20 - r.attack_mod == 0, "unblessed to-hit carries no extra"

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [ally]
    engine.execute_spell(bm, action)

    # Blessed: the d4 rides total_roll but NOT attack_mod, so it is exactly total-d20-mod.
    blessed = engine.get_agent_stats(bm, ally)
    for _ in range(30):
        r = engine.roll_to_hit(weapon, blessed, 10)
        d4 = r.total_roll - r.d20 - r.attack_mod
        assert 1 <= d4 <= 4, f"Bless should add 1..4 to an attack, got {d4}"
    print("✅ test_attack_gains_1d4 passed")


def test_buff_dies_with_concentration():
    """Dropping the caster's concentration clears `blessed` from every target."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    t1 = _place(engine, bm, "Ally1", 6, 5)
    t2 = _place(engine, bm, "Ally2", 7, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_bless()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [t1, t2]
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, t1).blessed and engine.get_agent_stats(bm, t2).blessed

    engine.drop_concentration(bm, caster)

    for idx in (t1, t2):
        assert not engine.get_agent_stats(bm, idx).blessed, f"target {idx} should no longer be blessed"
    assert not engine.get_agent_conditions(bm, caster).concentrating
    print("✅ test_buff_dies_with_concentration passed")


def test_upcast_adds_fourth_target():
    """Cast at level 2, Bless reaches a fourth creature."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    targets = [_place(engine, bm, f"Ally{i}", 6 + i, 5) for i in range(4)]
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_bless()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 2          # +1 target over the base 3
    action.target_indices = targets
    engine.execute_spell(bm, action)

    for idx in targets:
        assert engine.get_agent_stats(bm, idx).blessed, f"target {idx} should be blessed at slot 2"
    print("✅ test_upcast_adds_fourth_target passed")


def run_all():
    test_three_targets_blessed()
    test_save_gains_1d4()
    test_attack_gains_1d4()
    test_buff_dies_with_concentration()
    test_upcast_adds_fourth_target()
    print("\n✅ All Bless tests passed")


if __name__ == "__main__":
    run_all()
