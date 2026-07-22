#!/usr/bin/env python3
"""
Infra B — on-damage condition behavior. A condition flagged:
  * OnDamage.End        ends the moment the creature takes any damage (Sleep, Hypnotic Pattern).
  * OnDamage.RepeatSave lets the creature repeat its save at Advantage when it takes damage,
                        ending the condition on a success (Tasha's Hideous Laughter).

Arm casters AFTER all agents are placed (add_agent_to_battle re-applies configs).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _add(engine, bm, name, col, row, hp=40, wis=10):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), wis=wis, hp=hp)


def _stunner(on_damage):
    """Automatic Single spell that applies Incapacitated (no save to resist), with the
    given on-damage behavior."""
    s = rpg.Spell()
    s.name = "Test Stunner"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 30
    s.level = 0
    s.duration = 10
    c = rpg.AttackCondition()
    c.condition_name = "Incapacitated"
    c.condition_duration = 10
    c.requires_save = False           # applies automatically
    c.save_ability = rpg.SaveAbility.Wisdom
    c.save_dc_ability = rpg.SaveAbility.SaveWis   # DC = 8 + caster prof + caster WIS mod
    c.on_damage = on_damage
    s.conditions = [c]
    return s


def _zap():
    s = rpg.Spell()
    s.name = "Zap"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 30
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Force
    roll.num_dice = 1
    roll.die_size = 4
    roll.bonus = 2
    s.magic_damage_rolls = [roll]
    return s


def _arm_caster(engine, bm, idx, spells, wis=16, prof=2):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Wizard
    s.char_level = 5
    s.wis = wis
    s.prof_bonus = prof
    s.hp_max = 40
    s.hp_cur = 40
    s.can_cast_spell = True
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, spells)


def _cast(engine, bm, caster, spell_idx, target):
    a = rpg.SpellAction()
    a.caster_idx = caster
    a.spell_idx = spell_idx
    a.target_indices = [target]
    return engine.execute_spell(bm, a)


def _incap(bm, idx):
    return bm.placed_agents[idx].conditions.incapacitated


def test_end_condition_ends_on_any_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _add(engine, bm, "Caster", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=50)
    _arm_caster(engine, bm, caster, [_stunner(rpg.OnDamage.End), _zap()])

    _cast(engine, bm, caster, 0, target)       # apply Incapacitated
    assert _incap(bm, target), "condition should be applied"

    _cast(engine, bm, caster, 1, target)       # deal damage
    assert not _incap(bm, target), "OnDamage.End condition must end when the target takes damage"
    print("✅ test_end_condition_ends_on_any_damage passed")


def test_repeat_save_ends_on_success():
    bm = setup_battle_map(); engine = setup_combat_engine()
    # caster WIS 8 -> save DC = 8 + 2 - 1 = 9; target WIS 30 (+10), advantage -> always >= 9.
    caster = _add(engine, bm, "Caster", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=50, wis=30)
    _arm_caster(engine, bm, caster, [_stunner(rpg.OnDamage.RepeatSave), _zap()], wis=8)

    _cast(engine, bm, caster, 0, target)
    assert _incap(bm, target), "condition should be applied"

    _cast(engine, bm, caster, 1, target)
    assert not _incap(bm, target), "a successful on-damage save should end the condition"
    print("✅ test_repeat_save_ends_on_success passed")


def test_repeat_save_persists_on_failure():
    bm = setup_battle_map(); engine = setup_combat_engine()
    # caster WIS 30 -> save DC = 8 + 2 + 10 = 20; target WIS 1 (-5), even a 20 -> 15 < 20.
    caster = _add(engine, bm, "Caster", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=50, wis=1)
    _arm_caster(engine, bm, caster, [_stunner(rpg.OnDamage.RepeatSave), _zap()], wis=30)

    _cast(engine, bm, caster, 0, target)
    assert _incap(bm, target), "condition should be applied"

    _cast(engine, bm, caster, 1, target)
    assert _incap(bm, target), "a failed on-damage save must leave the condition in place"
    print("✅ test_repeat_save_persists_on_failure passed")


def _maul(num_dice, die_size):
    # rollDamage reads physical_damage_types (not damage_dice/modifier).
    w = rpg.Weapon()
    w.name = "Maul"
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = num_dice
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    return w


def _set_concentrating(engine, bm, idx, con):
    c = engine.get_agent_conditions(bm, idx)
    c.concentrating = True
    c.concentrating_on = "Bless"
    engine.set_agent_conditions(bm, idx, c)
    s = engine.get_agent_stats(bm, idx)
    s.con = con
    engine.set_agent_stats(bm, idx, s)


def _land_one_hit(engine, bm, attacker, target):
    attack = rpg.Attack(attacker, target, 0)
    for _ in range(12):
        r = engine.execute_action(bm, attack)
        if r.hit:
            return True
    return False


def test_weapon_damage_breaks_concentration_on_failed_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    attacker = _add(engine, bm, "Fighter", 5, 5)
    target = _add(engine, bm, "Mage", 6, 5, hp=200)
    engine.set_agent_weapons(bm, attacker, [_maul(20, 12)] * 3)  # ~130 dmg -> DC ~65
    _set_concentrating(engine, bm, target, con=1)                # CON save tops out around 16
    assert engine.get_agent_conditions(bm, target).concentrating

    assert _land_one_hit(engine, bm, attacker, target), "attack should land"
    assert not engine.get_agent_conditions(bm, target).concentrating, \
        "weapon damage must force a concentration save and break it on a failure"
    print("✅ test_weapon_damage_breaks_concentration_on_failed_save passed")


def test_weapon_damage_holds_concentration_on_passed_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    attacker = _add(engine, bm, "Fighter", 5, 5)
    target = _add(engine, bm, "Mage", 6, 5, hp=200)
    engine.set_agent_weapons(bm, attacker, [_maul(1, 4)] * 3)    # ~1-4 dmg -> DC 10
    _set_concentrating(engine, bm, target, con=30)               # CON save bottoms out at 11
    assert engine.get_agent_conditions(bm, target).concentrating

    assert _land_one_hit(engine, bm, attacker, target), "attack should land"
    assert engine.get_agent_conditions(bm, target).concentrating, \
        "a passed concentration save must keep concentration"
    print("✅ test_weapon_damage_holds_concentration_on_passed_save passed")


if __name__ == "__main__":
    test_end_condition_ends_on_any_damage()
    test_repeat_save_ends_on_success()
    test_repeat_save_persists_on_failure()
    test_weapon_damage_breaks_concentration_on_failed_save()
    test_weapon_damage_holds_concentration_on_passed_save()
    print("\n✅ All on-damage condition tests passed!")
