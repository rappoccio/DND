#!/usr/bin/env python3
"""
General feat tests — phase G5b (2024 PHB): resistance-ignore caster feats.

  · Elemental Adept — the caster's SPELLS ignore the target's Resistance to a chosen element
    (acid/cold/fire/lightning/thunder), and treat a 1 on that element's damage dice as a 2. Does NOT
    bypass Immunity, does NOT help other elements, and does NOT apply to weapon attacks (spells only).
  · Poisoner (Potent Poison) — Poison damage from ANY source (spell or weapon) ignores the target's
    Poison Resistance. Does NOT bypass Poison Immunity.

Both route through the shared helpers effectiveMagicDamageMult / rollSpellTypeDamage, applied at every
spell magic-damage site and the weapon magic-damage site (Poisoner only there).

MagicDamage_t indices: Acid=0, Cold=1, Fire=2, Force=3, Lightning=4, Necrotic=5, Poison=6,
Psychic=7, Radiant=8, Thunder=9.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target

FIRE, COLD, POISON = 2, 1, 6   # MagicDamage_t indices (for resistance arrays + elemental_adept_types)
_ENUM = {FIRE: rpg.MagicDamage.Fire, COLD: rpg.MagicDamage.Cold, POISON: rpg.MagicDamage.Poison}


# ─────────────────────────────────────────────────────────────────────────────
#  Builders
# ─────────────────────────────────────────────────────────────────────────────

def _dmg_spell(dtype, num_dice, die_size, bonus=0, name="TestBolt"):
    """An Automatic (no attack roll, no save) cantrip dealing one magic damage type."""
    sp = rpg.Spell()
    sp.name = name
    sp.level = 0
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Single
    sp.range = 120
    sp.num_targets = 1
    d = rpg.MagicDamageRoll(); d.type = _ENUM[dtype]; d.num_dice = num_dice; d.die_size = die_size; d.bonus = bonus
    sp.magic_damage_rolls = [d]
    return sp


def _caster(engine, bm, idx, feats=None, ea_types=None):
    s = engine.get_agent_stats(bm, idx)
    s.intel = 16; s.spellcasting_ability = 3; s.prof_bonus = 3
    s.spell_slots_remaining = [9, 9, 9, 9, 9, 0, 0, 0, 0]
    s.feats = list(feats or [])
    s.elemental_adept_types = list(ea_types or [])
    engine.set_agent_stats(bm, idx, s)


def _set_magic_mult(engine, bm, idx, type_idx, mult):
    s = engine.get_agent_stats(bm, idx)
    arr = list(s.magic_damage_multipliers)
    arr[type_idx] = mult
    s.magic_damage_multipliers = arr
    engine.set_agent_stats(bm, idx, s)


def _cast_dmg(engine, bm, caster, tgt, spell):
    engine.set_agent_spells(bm, caster, [spell])
    act = rpg.SpellAction(); act.caster_idx = caster; act.spell_idx = 0; act.target_indices = [tgt]
    res = engine.execute_spell(bm, act)
    return res.target_results[0].total_damage


def _magic_weapon(dtype, num_dice=10, die_size=1, name="EnchantedBlade"):
    """A weapon dealing ONLY magic damage of `dtype` (no physical, no ability mod muddle)."""
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = 50
    d = rpg.MagicDamageRoll(); d.type = _ENUM[dtype]; d.num_dice = num_dice; d.die_size = die_size
    w.magic_damage_types = [d]
    return w


def _arm_magic_weapon(engine, bm, idx, weapon, feats=None):
    s = engine.get_agent_stats(bm, idx)
    s.str = 10; s.prof_bonus = 3; s.hp_max = 80; s.hp_cur = 80
    s.feats = list(feats or [])
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [weapon, rpg.Weapon(), rpg.Weapon()])


def _weapon_dmg(engine, bm, a, t):
    return engine.execute_action(bm, rpg.Attack(a, t, 0)).total_damage


# ─────────────────────────────────────────────────────────────────────────────
#  Binding sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_elemental_adept_type_binding():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Mage", 5, 5)
    s = engine.get_agent_stats(bm, a)
    assert not s.has_elemental_adept_type(FIRE), "no feat → not covered"
    s.feats = ["Elemental Adept"]; s.elemental_adept_types = [FIRE]
    assert s.has_elemental_adept_type(FIRE) and not s.has_elemental_adept_type(COLD)
    engine.set_agent_stats(bm, a, s)
    assert list(engine.get_agent_stats(bm, a).elemental_adept_types) == [FIRE], "round-trips through the engine"
    print("✅ test_elemental_adept_type_binding passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Elemental Adept
# ─────────────────────────────────────────────────────────────────────────────

def test_elemental_adept_ignores_resistance():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Evoker", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, FIRE, 0.5)                    # Fire resistance
    spell = _dmg_spell(FIRE, num_dice=0, die_size=6, bonus=10)   # flat 10 fire, no dice (isolates resistance)

    _caster(engine, bm, a)                                       # no feat
    assert _cast_dmg(engine, bm, a, t, spell) == 5, "Fire resistance halves 10 → 5"
    _caster(engine, bm, a, feats=["Elemental Adept"], ea_types=[FIRE])
    assert _cast_dmg(engine, bm, a, t, spell) == 10, "Elemental Adept (Fire) ignores the Resistance → 10"
    print("✅ test_elemental_adept_ignores_resistance passed")


def test_elemental_adept_does_not_bypass_immunity():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Evoker", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, FIRE, 0.0)                    # Fire IMMUNITY
    spell = _dmg_spell(FIRE, num_dice=0, die_size=6, bonus=10)
    _caster(engine, bm, a, feats=["Elemental Adept"], ea_types=[FIRE])
    assert _cast_dmg(engine, bm, a, t, spell) == 0, "Elemental Adept ignores Resistance only, not Immunity"
    print("✅ test_elemental_adept_does_not_bypass_immunity passed")


def test_elemental_adept_treats_1_as_2():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Evoker", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    spell = _dmg_spell(FIRE, num_dice=10, die_size=1)            # 10 dice of d1 → every die is a 1

    _caster(engine, bm, a)
    assert _cast_dmg(engine, bm, a, t, spell) == 10, "no feat → ten 1s = 10"
    _caster(engine, bm, a, feats=["Elemental Adept"], ea_types=[FIRE])
    assert _cast_dmg(engine, bm, a, t, spell) == 20, "Elemental Adept treats each 1 as a 2 → 20"
    print("✅ test_elemental_adept_treats_1_as_2 passed")


def test_elemental_adept_only_chosen_element():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Evoker", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, COLD, 0.5)                    # Cold resistance
    spell = _dmg_spell(COLD, num_dice=0, die_size=6, bonus=10)
    _caster(engine, bm, a, feats=["Elemental Adept"], ea_types=[FIRE])   # took it for FIRE, not COLD
    assert _cast_dmg(engine, bm, a, t, spell) == 5, "Elemental Adept (Fire) does not help Cold damage"
    print("✅ test_elemental_adept_only_chosen_element passed")


def test_elemental_adept_is_spells_only():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Gish", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, FIRE, 0.5)
    _arm_magic_weapon(engine, bm, a, _magic_weapon(FIRE, num_dice=10, die_size=1),
                      feats=["Elemental Adept"])
    s = engine.get_agent_stats(bm, a); s.elemental_adept_types = [FIRE]; engine.set_agent_stats(bm, a, s)
    # Weapon fire damage (10) is still halved to 5 — Elemental Adept applies to spells, not weapons.
    assert _weapon_dmg(engine, bm, a, t) == 5, "Elemental Adept does not lift Resistance for a weapon's Fire damage"
    print("✅ test_elemental_adept_is_spells_only passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Poisoner — Potent Poison
# ─────────────────────────────────────────────────────────────────────────────

def test_poisoner_ignores_poison_resistance_spell():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Alchemist", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, POISON, 0.5)
    spell = _dmg_spell(POISON, num_dice=0, die_size=6, bonus=10)

    _caster(engine, bm, a)
    assert _cast_dmg(engine, bm, a, t, spell) == 5, "Poison resistance halves 10 → 5"
    _caster(engine, bm, a, feats=["Poisoner"])
    assert _cast_dmg(engine, bm, a, t, spell) == 10, "Potent Poison ignores Poison Resistance → 10"
    print("✅ test_poisoner_ignores_poison_resistance_spell passed")


def test_poisoner_ignores_poison_resistance_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Assassin", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, POISON, 0.5)

    _arm_magic_weapon(engine, bm, a, _magic_weapon(POISON, num_dice=10, die_size=1))   # no feat
    assert _weapon_dmg(engine, bm, a, t) == 5, "Poison resistance halves the weapon's 10 poison → 5"
    _arm_magic_weapon(engine, bm, a, _magic_weapon(POISON, num_dice=10, die_size=1), feats=["Poisoner"])
    assert _weapon_dmg(engine, bm, a, t) == 10, "Potent Poison ignores resistance for a WEAPON's Poison damage too"
    print("✅ test_poisoner_ignores_poison_resistance_weapon passed")


def test_poisoner_does_not_bypass_poison_immunity():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Alchemist", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    _set_magic_mult(engine, bm, t, POISON, 0.0)                  # Poison IMMUNITY
    spell = _dmg_spell(POISON, num_dice=0, die_size=6, bonus=10)
    _caster(engine, bm, a, feats=["Poisoner"])
    assert _cast_dmg(engine, bm, a, t, spell) == 0, "Potent Poison ignores Resistance only, not Immunity"
    print("✅ test_poisoner_does_not_bypass_poison_immunity passed")


def main():
    print("Running General feat tests (G5b — Elemental Adept + Poisoner resistance-ignore)...\n")
    test_elemental_adept_type_binding()
    test_elemental_adept_ignores_resistance()
    test_elemental_adept_does_not_bypass_immunity()
    test_elemental_adept_treats_1_as_2()
    test_elemental_adept_only_chosen_element()
    test_elemental_adept_is_spells_only()
    test_poisoner_ignores_poison_resistance_spell()
    test_poisoner_ignores_poison_resistance_weapon()
    test_poisoner_does_not_bypass_poison_immunity()
    print("\n" + "=" * 60)
    print("✅ All General feat (G5b) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
