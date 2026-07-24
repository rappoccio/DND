#!/usr/bin/env python3
"""
Test Bane — the mirror of Bless:
  - Level 1, Concentration, up to 3 creatures (+1 per slot level above 1).
  - Each target must make a Charisma save; a target that FAILS subtracts 1d4 from every attack
    roll and saving throw while the spell lasts. A target that SUCCEEDS is unaffected.
  - The debuff is a Stats flag (`baned`) applied via a "Baned" AgentCondition; it dies with the
    caster's concentration and is torn down through the shared condition-teardown chokepoint.

Bane targets enemies and is gated on a failed save, so saves are made deterministic here by
pitting a high-DC caster against CHA-1 victims (always fail) or a low-DC caster against a
CHA-24 target (always saves).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle, create_melee_weapon)

TEAM = 1


def _make_bane():
    """Build the Bane spell exactly as spells.json now defines it."""
    sp = rpg.Spell()
    sp.name = "Bane"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Multiple
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Charisma
    sp.range = 30
    sp.level = 1
    sp.duration = 10
    sp.num_targets = 3
    sp.targets_per_upcast_level = 1
    sp.requires_concentration = True

    cond = rpg.AttackCondition()
    cond.condition_name = "Baned"
    cond.requires_save = True          # only a failed save applies the debuff
    cond.save_ability = rpg.SaveAbility.Charisma
    cond.condition_duration = 0        # 0 → inherit the spell's duration
    cond.save_repeat_turns = -1        # RAW: no repeated save to shrug it off
    sp.conditions = [cond]
    return sp


def _place(engine, bm, name, col, row, faction=TEAM):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_strong_caster(engine, bm, idx):
    """A caster whose CHA-based save DC no CHA-1 victim can ever beat (DC 24)."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5    # CHA
    s.cha = 30                    # +10 mod
    s.prof_bonus = 6             # DC = 8 + 6 + 10 = 24
    engine.set_agent_stats(bm, idx, s)


def _make_weak_caster(engine, bm, idx):
    """A caster whose save DC (8) a strong-willed target always beats."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5    # CHA
    s.cha = 10                    # +0 mod
    s.prof_bonus = 0             # DC = 8 + 0 + 0 = 8
    engine.set_agent_stats(bm, idx, s)


def _weaken_will(engine, bm, idx):
    """CHA 1 → −5 save mod, so a d20 tops out at 15 (fails DC 24)."""
    s = engine.get_agent_stats(bm, idx)
    s.cha = 1
    engine.set_agent_stats(bm, idx, s)


def test_three_targets_baned():
    """A level-1 Bane flags all three failing targets with `baned` and holds concentration."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    t1 = _place(engine, bm, "Foe1", 6, 5)
    t2 = _place(engine, bm, "Foe2", 7, 5)
    t3 = _place(engine, bm, "Foe3", 4, 5)
    _make_strong_caster(engine, bm, caster)
    for t in (t1, t2, t3):
        _weaken_will(engine, bm, t)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [t1, t2, t3]
    engine.execute_spell(bm, action)

    for idx in (t1, t2, t3):
        assert engine.get_agent_stats(bm, idx).baned, f"target {idx} should be baned"
    assert engine.get_agent_conditions(bm, caster).concentrating, "caster should be concentrating"
    print("✅ test_three_targets_baned passed")


def test_save_loses_1d4():
    """A baned creature's saving-throw modifier drops 1..4 below its unbaned value."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5)
    _make_strong_caster(engine, bm, caster)
    _weaken_will(engine, bm, foe)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    base = engine.save_mod_for(bm, foe, rpg.SaveAbility.Dexterity)  # unbaned baseline (DEX 10 → 0)

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [foe]
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, foe).baned, "setup: foe should be baned"

    for _ in range(30):
        d = engine.save_mod_for(bm, foe, rpg.SaveAbility.Dexterity) - base
        assert -4 <= d <= -1, f"Bane should subtract 1..4 from a save, got {d}"
    print("✅ test_save_loses_1d4 passed")


def test_attack_loses_1d4():
    """A baned attacker's to-hit total drops 1..4 (the Bane d4), reported outside attack_mod."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5)
    _make_strong_caster(engine, bm, caster)
    _weaken_will(engine, bm, foe)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    # Unbaned: total_roll == d20 + attack_mod exactly (Bane folds into neither).
    unbaned = engine.get_agent_stats(bm, foe)
    for _ in range(30):
        r = engine.roll_to_hit(create_melee_weapon(), unbaned, 10)
        assert r.total_roll - r.d20 - r.attack_mod == 0, "unbaned to-hit carries no extra"

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [foe]
    engine.execute_spell(bm, action)

    # Baned: the d4 rides total_roll but NOT attack_mod, so it is exactly total-d20-mod (negative).
    baned = engine.get_agent_stats(bm, foe)
    for _ in range(30):
        r = engine.roll_to_hit(create_melee_weapon(), baned, 10)
        d4 = r.total_roll - r.d20 - r.attack_mod
        assert -4 <= d4 <= -1, f"Bane should subtract 1..4 from an attack, got {d4}"
    print("✅ test_attack_loses_1d4 passed")


def test_successful_save_no_bane():
    """A target that succeeds its Charisma save is NOT baned."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    stalwart = _place(engine, bm, "Stalwart", 6, 5)
    _make_weak_caster(engine, bm, caster)          # DC 8
    s = engine.get_agent_stats(bm, stalwart)
    s.cha = 24                                     # +7 save mod → min d20 total 8 ≥ DC 8, always saves
    engine.set_agent_stats(bm, stalwart, s)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [stalwart]
    engine.execute_spell(bm, action)

    assert not engine.get_agent_stats(bm, stalwart).baned, "a successful save must not be baned"
    print("✅ test_successful_save_no_bane passed")


def test_debuff_dies_with_concentration():
    """Dropping the caster's concentration clears `baned` from every target."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    t1 = _place(engine, bm, "Foe1", 6, 5)
    t2 = _place(engine, bm, "Foe2", 7, 5)
    _make_strong_caster(engine, bm, caster)
    for t in (t1, t2):
        _weaken_will(engine, bm, t)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 1
    action.target_indices = [t1, t2]
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, t1).baned and engine.get_agent_stats(bm, t2).baned

    engine.drop_concentration(bm, caster)

    for idx in (t1, t2):
        assert not engine.get_agent_stats(bm, idx).baned, f"target {idx} should no longer be baned"
    assert not engine.get_agent_conditions(bm, caster).concentrating
    print("✅ test_debuff_dies_with_concentration passed")


def test_upcast_adds_fourth_target():
    """Cast at level 2, Bane reaches a fourth creature."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    targets = [_place(engine, bm, f"Foe{i}", 6 + i, 5) for i in range(4)]
    _make_strong_caster(engine, bm, caster)
    for t in targets:
        _weaken_will(engine, bm, t)
    engine.set_agent_spells(bm, caster, [_make_bane()])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 2          # +1 target over the base 3
    action.target_indices = targets
    engine.execute_spell(bm, action)

    for idx in targets:
        assert engine.get_agent_stats(bm, idx).baned, f"target {idx} should be baned at slot 2"
    print("✅ test_upcast_adds_fourth_target passed")


def run_all():
    test_three_targets_baned()
    test_save_loses_1d4()
    test_attack_loses_1d4()
    test_successful_save_no_bane()
    test_debuff_dies_with_concentration()
    test_upcast_adds_fourth_target()
    print("\n✅ All Bane tests passed")


if __name__ == "__main__":
    run_all()
