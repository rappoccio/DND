#!/usr/bin/env python3
"""
Tests for the Sanctuary spell (SpellType.Help).

Sanctuary is a warding buff — NOT a heal. Casting it:
  • does NOT restore HP to the target (regression: it used to be typed "Heal"),
  • marks the target with the Sanctuary ward (Conditions.sanctuary_active + DC).

While warded, any non-ally that targets the creature with an attack roll or a
damaging spell must make a WIS save (vs the caster's spell DC) or lose the
attack/spell. The ward ends when the warded creature attacks, casts, or deals
damage. Areas of effect are not blocked (not exercised here — Single/Multiple only).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── spell builders ────────────────────────────────────────────────────────────
def _sanctuary():
    """Sanctuary: a Help (buff) spell that applies the 'Sanctuary' condition to one ally."""
    s = rpg.Spell()
    s.name = "Sanctuary"
    s.level = 0  # avoid spell-slot bookkeeping in tests
    s.type = rpg.SpellType.Help
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.save_ability = rpg.SaveAbility.Wisdom
    s.range = 30
    s.duration = 10

    c = rpg.AttackCondition()
    c.condition_name = "Sanctuary"
    c.condition_duration = 0  # 0 → use the spell's duration
    c.requires_save = False   # auto-applies to the warded ally
    c.save_ability = rpg.SaveAbility.Wisdom
    c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod  # ward DC = caster's spell save DC
    s.conditions = [c]
    return s


def _harm_bolt():
    """A deterministic single-target damaging spell (no roll) for the spell-ward test."""
    s = rpg.Spell()
    s.name = "Test Bolt"
    s.level = 0
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 60
    s.duration = 1
    d = rpg.MagicDamageRoll()
    d.type = rpg.MagicDamage.Fire
    d.num_dice = 0
    d.die_size = 6
    d.bonus = 10  # flat 10 fire so a landed hit is unmistakable
    s.magic_damage_rolls = [d]
    return s


def _melee_weapon():
    w = rpg.Weapon()
    w.name = "Sword"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    return w


# ── helpers ───────────────────────────────────────────────────────────────────
def _arm_caster(engine, bm, caster, spell, ability=4):
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    s.spellcasting_ability = ability  # 4 = WIS → spell DC == spell_save_dc_wis
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [spell])


def _cast_on(engine, bm, caster, target):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = [target]
    return engine.execute_spell(bm, action)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _set_ward_dc(engine, bm, idx, dc):
    """Force the warded creature's ward DC (deterministic attacker fail/pass)."""
    c = _cond(engine, bm, idx)
    c.sanctuary_active = True
    c.sanctuary_dc = dc
    engine.set_agent_conditions(bm, idx, c)


def _attack(engine, bm, atk, tgt):
    return engine.execute_action(bm, rpg.Attack(atk, tgt, 0))


# ── tests ─────────────────────────────────────────────────────────────────────
def test_sanctuary_does_not_heal():
    """Regression: Sanctuary must NOT restore HP (it used to be typed 'Heal')."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), wis=18, hp=20)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 6), hp=20)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    _arm_caster(engine, bm, caster, _sanctuary())

    # Wound the ally so any healing would be visible.
    a = engine.get_agent_stats(bm, ally)
    a.hp_cur = 5
    engine.set_agent_stats(bm, ally, a)

    res = _cast_on(engine, bm, caster, ally)

    assert res.valid, "cast should be valid"
    assert engine.get_agent_stats(bm, ally).hp_cur == 5, "Sanctuary must not heal the target"
    assert sum(t.total_healing for t in res.target_results) == 0, "no healing should be rolled"
    assert _cond(engine, bm, ally).sanctuary_active, "ward should be applied"
    print("✅ test_sanctuary_does_not_heal passed")


def test_sanctuary_sets_ward_dc():
    """The ward DC stored on the target equals the caster's spell save DC."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), wis=18)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 6))
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    cs = engine.get_agent_stats(bm, caster)
    cs.prof_bonus = 3
    engine.set_agent_stats(bm, caster, cs)
    _arm_caster(engine, bm, caster, _sanctuary())

    _cast_on(engine, bm, caster, ally)

    # Spell save DC = 8 + prof_bonus + spellcasting_ability_mod.
    # spell_save_dc_wis is the *WIS saving throw DC* (needs save_prof_wis), NOT the spell save DC.
    final = engine.get_agent_stats(bm, caster)
    expected = 8 + final.prof_bonus + (final.wis - 10) // 2
    c = _cond(engine, bm, ally)
    assert c.sanctuary_active, "ward should be active"
    assert c.sanctuary_dc == expected, f"ward DC {c.sanctuary_dc} != caster spell DC {expected}"
    print("✅ test_sanctuary_sets_ward_dc passed")


def test_attacker_failing_save_loses_attack():
    """An enemy that fails the WIS save cannot attack the warded creature."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    warded = add_agent_to_battle(engine, bm, create_test_agent("Warded", 5, 5), hp=30)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))
    bm.set_agent_faction(warded, 1)
    bm.set_agent_faction(enemy, 2)
    engine.set_agent_weapons(bm, enemy, [_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    _set_ward_dc(engine, bm, warded, 99)  # unbeatable → always fails

    r = _attack(engine, bm, enemy, warded)

    assert not r.valid, "a failed Sanctuary save must block the attack (invalid result)"
    assert engine.get_agent_stats(bm, warded).hp_cur == 30, "warded creature takes no damage"
    print("✅ test_attacker_failing_save_loses_attack passed")


def test_attacker_succeeding_save_may_attack():
    """An enemy that succeeds the WIS save attacks normally."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    warded = add_agent_to_battle(engine, bm, create_test_agent("Warded", 5, 5), hp=30, ac=1)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))
    bm.set_agent_faction(warded, 1)
    bm.set_agent_faction(enemy, 2)
    engine.set_agent_weapons(bm, enemy, [_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    _set_ward_dc(engine, bm, warded, 1)  # trivially beaten → always succeeds

    r = _attack(engine, bm, enemy, warded)

    assert r.valid, "a succeeded Sanctuary save must let the attack proceed"
    print("✅ test_attacker_succeeding_save_may_attack passed")


def test_ally_attack_not_blocked():
    """Allies are exempt from the ward (they can target the warded creature freely)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    warded = add_agent_to_battle(engine, bm, create_test_agent("Warded", 5, 5), hp=30)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bm.set_agent_faction(warded, 1)
    bm.set_agent_faction(ally, 1)
    engine.set_agent_weapons(bm, ally, [_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    _set_ward_dc(engine, bm, warded, 99)  # unbeatable, but allies don't roll

    r = _attack(engine, bm, ally, warded)

    assert r.valid, "an ally must not be blocked by the ward"
    print("✅ test_ally_attack_not_blocked passed")


def test_ward_ends_when_warded_creature_attacks():
    """The ward ends as soon as the warded creature makes an attack."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    warded = add_agent_to_battle(engine, bm, create_test_agent("Warded", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5), hp=30)
    bm.set_agent_faction(warded, 1)
    bm.set_agent_faction(enemy, 2)
    engine.set_agent_weapons(bm, warded, [_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    _set_ward_dc(engine, bm, warded, 50)

    assert _cond(engine, bm, warded).sanctuary_active, "ward active before attacking"
    _attack(engine, bm, warded, enemy)
    assert not _cond(engine, bm, warded).sanctuary_active, "ward must end after the warded creature attacks"
    print("✅ test_ward_ends_when_warded_creature_attacks passed")


def test_damaging_spell_blocked_by_ward():
    """A damaging spell aimed at a warded enemy is lost when the caster fails the WIS save."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 5), wis=6)
    warded = add_agent_to_battle(engine, bm, create_test_agent("Warded", 7, 5), hp=30)
    bm.set_agent_faction(caster, 2)
    bm.set_agent_faction(warded, 1)
    _arm_caster(engine, bm, caster, _harm_bolt(), ability=5)  # CHA-cast so low WIS hurts the save
    _set_ward_dc(engine, bm, warded, 99)  # unbeatable → caster always fails

    res = _cast_on(engine, bm, caster, warded)

    assert res.valid, "cast itself is valid (the spell simply can't land on the warded target)"
    assert engine.get_agent_stats(bm, warded).hp_cur == 30, "warded creature takes no spell damage"
    assert sum(t.total_damage for t in res.target_results) == 0, "no damage should be dealt"
    print("✅ test_damaging_spell_blocked_by_ward passed")


def _run_all():
    tests = [
        test_sanctuary_does_not_heal,
        test_sanctuary_sets_ward_dc,
        test_attacker_failing_save_loses_attack,
        test_attacker_succeeding_save_may_attack,
        test_ally_attack_not_blocked,
        test_ward_ends_when_warded_creature_attacks,
        test_damaging_spell_blocked_by_ward,
    ]
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} Sanctuary tests passed")


if __name__ == "__main__":
    _run_all()
