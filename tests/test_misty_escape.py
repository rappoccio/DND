#!/usr/bin/env python3
"""
Test: the vampire "Misty Escape" action (a Gaseous Form self-buff).

A vampire uses its action to cast "Misty Escape", a self-targeted Gaseous Form variant. While
gaseous the creature:
  · is IMMUNE to Bludgeoning/Piercing/Slashing damage (a NON-vampire caster is only RESISTANT —
    the Immunity-vs-Resistance split is driven by stats.is_vampire, not the spell name),
  · has a Fly Speed of 20 ft and no walk speed,
  · can't attack or cast spells, and
  · is immune to the Prone condition,
and reverts (restoring its real speeds + physical multipliers) when the duration runs out.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)

B = int(rpg.PhysicalDamage.Bludgeoning)
P = int(rpg.PhysicalDamage.Piercing)
S = int(rpg.PhysicalDamage.Slashing)


def _misty_escape_spell():
    """Mirror the spells.json 'Misty Escape' entry: a self-target Help spell whose only effect is
    the 'Gaseous' condition (which the engine turns into the gaseous-form self-buff)."""
    sp = rpg.Spell()
    sp.name = "Misty Escape"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.level = 0
    sp.range = 5
    sp.duration = 10
    sp.requires_concentration = False
    c = rpg.AttackCondition()
    c.condition_name = "Gaseous"
    c.condition_duration = 10
    c.save_repeat_turns = -1   # a self-buff is never "saved off"
    sp.conditions = [c]
    return sp


def _add_caster(engine, bm, name, col, row, is_vampire):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    s = engine.get_agent_stats(bm, idx)
    s.is_vampire = is_vampire
    s.speed_walk = 30
    s.speed_fly = 0
    s.can_cast_spell = True
    s.hp_max = 100
    s.hp_cur = 100
    engine.set_agent_stats(bm, idx, s)
    return idx


def _cast_misty(engine, bm, caster):
    engine.set_agent_spells(bm, caster, [_misty_escape_spell()])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = [caster]   # self-buff
    return engine.execute_spell(bm, action)


def test_vampire_misty_escape_grants_physical_immunity():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    v = _add_caster(engine, bm, "Strahd", 5, 5, is_vampire=True)

    _cast_misty(engine, bm, v)

    cond = engine.get_agent_conditions(bm, v)
    assert cond.gaseous_form, "vampire should be gaseous after casting Misty Escape"

    s = engine.get_agent_stats(bm, v)
    for t in (B, P, S):
        assert s.get_physical_damage_multiplier(t) == 0.0, \
            f"vampire gaseous form must be IMMUNE (0.0x) to physical type {t}"
    assert s.speed_fly == 20, "gaseous Fly Speed should be 20 ft"
    assert s.speed_walk == 0, "gaseous form has no walk speed"
    print("✅ vampire Misty Escape → immune to B/P/S, Fly 20 / walk 0")


def test_nonvampire_gaseous_form_is_only_resistant():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    m = _add_caster(engine, bm, "Mist Mage", 5, 5, is_vampire=False)

    _cast_misty(engine, bm, m)

    s = engine.get_agent_stats(bm, m)
    for t in (B, P, S):
        assert s.get_physical_damage_multiplier(t) == 0.5, \
            f"non-vampire gaseous form must be RESISTANT (0.5x) to physical type {t}"
    print("✅ non-vampire gaseous form → resistance (0.5x), not immunity")


def test_gaseous_form_blocks_attacks_and_further_casts():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    v = _add_caster(engine, bm, "Strahd", 5, 5, is_vampire=True)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5))
    ts = engine.get_agent_stats(bm, tgt)
    ts.hp_max = 60
    ts.hp_cur = 60
    engine.set_agent_stats(bm, tgt, ts)

    _cast_misty(engine, bm, v)   # v is now gaseous (and its spell list is [Misty Escape])

    # A gaseous creature can't attack: arm it, swing at the adjacent victim, expect no damage.
    w = rpg.Weapon()
    w.name = "Slam"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 2
    pr.die_size = 8
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, v, [w, rpg.Weapon(), rpg.Weapon()])

    hp_before = engine.get_agent_stats(bm, tgt).hp_cur
    engine.execute_action(bm, rpg.Attack(v, tgt, 0))
    hp_after = engine.get_agent_stats(bm, tgt).hp_cur
    assert hp_after == hp_before, "gaseous creature must deal no damage (its attack is blocked)"

    # A gaseous creature can't cast: a second cast is refused (result is invalid).
    res2 = _cast_misty(engine, bm, v)
    assert not res2.valid, "gaseous creature must not be able to cast another spell"
    print("✅ gaseous form → can't attack, can't cast")


def test_gaseous_form_reverts_and_restores_stats_on_expiry():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    v = _add_caster(engine, bm, "Strahd", 5, 5, is_vampire=True)

    base = engine.get_agent_stats(bm, v)
    base_walk, base_fly = base.speed_walk, base.speed_fly
    base_mult = base.get_physical_damage_multiplier(S)

    _cast_misty(engine, bm, v)
    assert engine.get_agent_conditions(bm, v).gaseous_form

    # Run out the 10-round duration.
    for _ in range(10):
        engine.tick_agent_conditions(bm)

    cond = engine.get_agent_conditions(bm, v)
    assert not cond.gaseous_form, "gaseous form should end when its duration expires"
    s = engine.get_agent_stats(bm, v)
    assert s.speed_walk == base_walk and s.speed_fly == base_fly, \
        "reverting must restore the pre-form speeds"
    for t in (B, P, S):
        assert s.get_physical_damage_multiplier(t) == base_mult, \
            "reverting must restore the pre-form physical multipliers"
    print("✅ gaseous form reverts on expiry and restores speeds + multipliers")


def test_gaseous_form_ends_when_dropped_to_zero_hp():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    # Not an NPC, so applyUnconscious downs (not deletes) the agent and we can inspect it afterwards.
    v = _add_caster(engine, bm, "Vampiric PC", 5, 5, is_vampire=True)

    _cast_misty(engine, bm, v)
    assert engine.get_agent_conditions(bm, v).gaseous_form

    s = engine.get_agent_stats(bm, v)
    s.hp_cur = 0
    engine.set_agent_stats(bm, v, s)
    engine.apply_unconscious(bm, v)

    cond = engine.get_agent_conditions(bm, v)
    assert not cond.gaseous_form, "dropping to 0 HP must end gaseous form (RAW)"
    print("✅ gaseous form ends when the creature drops to 0 HP")


if __name__ == "__main__":
    test_vampire_misty_escape_grants_physical_immunity()
    test_nonvampire_gaseous_form_is_only_resistant()
    test_gaseous_form_blocks_attacks_and_further_casts()
    test_gaseous_form_reverts_and_restores_stats_on_expiry()
    test_gaseous_form_ends_when_dropped_to_zero_hp()
    print("\n✅ All Misty Escape tests passed")
