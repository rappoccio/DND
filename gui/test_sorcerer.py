#!/usr/bin/env python3
"""
Test Sorcerer: chassis + Sorcery Points (Phase 1), and Innate Sorcery, Font of
Magic (slot <-> SP conversion), and Metamagic (Heightened/Seeking) (Phase 2).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle, create_melee_weapon)


def _sorcerer(engine, bm, idx, level, cha=16, prof=2, subclass=None, dex=10):
    """Configure agent idx as a Sorcerer of the given level/subclass."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Sorcerer, level)
    s.cha = cha
    s.dex = dex
    s.prof_bonus = prof
    s.can_cast_spell = True
    if subclass is not None:
        s.sorcerer_subclass = subclass  # set BEFORE init so subclass level-gates apply
    s.initialize_class_resources(rpg.CharacterClass.Sorcerer, level)
    s.restore_spell_slots()
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _save_spell(name="Frostbite", save=None):
    """A free (no resource) single-target Save spell dealing a little cold damage."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = save if save is not None else rpg.SaveAbility.Dexterity
    s.range = 60
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Cold
    roll.num_dice = 1
    roll.die_size = 6
    s.magic_damage_rolls = [roll]
    return s


def _attack_spell(name="Fire Bolt"):
    """A free single-target spell-attack-roll cantrip."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.AttackRoll
    s.range = 120
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 1
    roll.die_size = 10
    s.magic_damage_rolls = [roll]
    return s


def _setup(level, cha=16, prof=2):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    sorc = add_agent_to_battle(engine, bm, create_test_agent("Sorcerer", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _sorcerer(engine, bm, sorc, level, cha=cha, prof=prof)
    t = engine.get_agent_stats(bm, tgt)
    t.hp_max = 200
    t.hp_cur = 200
    engine.set_agent_stats(bm, tgt, t)
    return bm, engine, sorc, tgt


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: chassis + resources
# ─────────────────────────────────────────────────────────────────────────────

def test_sorcerer_spell_slots():
    """Sorcerer is a full caster, table B: 2 first-level slots at L1."""
    bm, engine, sorc, _ = _setup(1)
    s = engine.get_agent_stats(bm, sorc)
    assert s.spell_slots_max[0] == 2, f"L1 Sorcerer should have 2 first-level slots, got {s.spell_slots_max[0]}"
    print("✅ test_sorcerer_spell_slots passed")


def test_sorcery_points_allocation():
    """Sorcery Points equal the Sorcerer's level and regain on a long rest."""
    for level in [1, 5, 11, 20]:
        bm, engine, sorc, _ = _setup(level)
        s = engine.get_agent_stats(bm, sorc)
        sp = s.get_resource("Sorcery Points")
        assert sp is not None, f"L{level} Sorcerer should have Sorcery Points"
        assert sp.current == level and sp.max == level, \
            f"L{level} should have {level} SP, got {sp.current}/{sp.max}"
    print("✅ test_sorcery_points_allocation passed")


def test_sorcery_points_long_rest():
    """Spent Sorcery Points come back on a long rest."""
    bm, engine, sorc, _ = _setup(5)
    s = engine.get_agent_stats(bm, sorc)
    sp = s.get_resource("Sorcery Points")
    sp.current = 1
    s.resources["Sorcery Points"] = sp
    s.restore_resources_long_rest()
    engine.set_agent_stats(bm, sorc, s)
    s2 = engine.get_agent_stats(bm, sorc)
    assert s2.get_resource("Sorcery Points").current == 5, \
        f"SP should restore to 5 on long rest, got {s2.get_resource('Sorcery Points').current}"
    print("✅ test_sorcery_points_long_rest passed")


def test_chassis_saves():
    """Sorcerer chassis grants Constitution + Charisma save proficiency."""
    bm, engine, sorc, _ = _setup(1)
    s = engine.get_agent_stats(bm, sorc)
    assert s.save_prof_con, "Sorcerer should have CON save proficiency"
    assert s.save_prof_cha, "Sorcerer should have CHA save proficiency"
    print("✅ test_chassis_saves passed")


def test_enums_bound():
    """Subclass and metamagic enums are exposed to Python."""
    assert rpg.SorcererSubclass.Draconic is not None
    assert rpg.SorcererSubclass.WildMagic is not None
    assert rpg.MetamagicOption.Twinned is not None
    assert rpg.MetamagicOption.Heightened is not None
    print("✅ test_enums_bound passed")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Innate Sorcery
# ─────────────────────────────────────────────────────────────────────────────

def test_innate_sorcery_resource():
    """Innate Sorcery has 2 uses and regains on a long rest."""
    bm, engine, sorc, _ = _setup(1)
    s = engine.get_agent_stats(bm, sorc)
    innate = s.get_resource("Innate Sorcery")
    assert innate is not None and innate.current == 2 and innate.max == 2, \
        "Innate Sorcery should start with 2 uses"
    print("✅ test_innate_sorcery_resource passed")


def test_innate_sorcery_activation():
    """Activating Innate Sorcery spends a use and sets a 10-round duration."""
    bm, engine, sorc, _ = _setup(1)
    ok = engine.activate_innate_sorcery(bm, sorc)
    assert ok, "activation should succeed for a Sorcerer with uses left"
    s = engine.get_agent_stats(bm, sorc)
    assert s.innate_sorcery_turns == 10, f"duration should be 10, got {s.innate_sorcery_turns}"
    assert s.get_resource("Innate Sorcery").current == 1, "should spend one use"
    print("✅ test_innate_sorcery_activation passed")


def test_innate_sorcery_dc_bonus():
    """Innate Sorcery raises the spell save DC by 1 while active."""
    bm, engine, sorc, tgt = _setup(1)
    engine.set_agent_spells(bm, sorc, [_save_spell()])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]

    base = engine.execute_spell(bm, action)
    base_dc = base.target_results[0].save_dc

    engine.activate_innate_sorcery(bm, sorc)
    buffed = engine.execute_spell(bm, action)
    buffed_dc = buffed.target_results[0].save_dc

    assert buffed_dc == base_dc + 1, \
        f"Innate Sorcery should add +1 to spell save DC ({base_dc} -> {base_dc + 1}), got {buffed_dc}"
    print("✅ test_innate_sorcery_dc_bonus passed")


def test_innate_sorcery_no_uses():
    """Innate Sorcery fails when no uses remain, leaving the caster unbuffed."""
    bm, engine, sorc, _ = _setup(1)
    s = engine.get_agent_stats(bm, sorc)
    innate = s.get_resource("Innate Sorcery")
    innate.current = 0
    s.resources["Innate Sorcery"] = innate
    engine.set_agent_stats(bm, sorc, s)

    ok = engine.activate_innate_sorcery(bm, sorc)
    assert not ok, "activation should fail with no uses"
    assert engine.get_agent_stats(bm, sorc).innate_sorcery_turns == 0, "no buff when depleted"
    print("✅ test_innate_sorcery_no_uses passed")


def test_innate_sorcery_wrong_class():
    """A non-Sorcerer cannot activate Innate Sorcery."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wiz = add_agent_to_battle(engine, bm, create_test_agent("Wizard", 5, 5))
    s = engine.get_agent_stats(bm, wiz)
    s.set_class_level(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, wiz, s)
    assert not engine.activate_innate_sorcery(bm, wiz), "non-Sorcerer should not activate Innate Sorcery"
    print("✅ test_innate_sorcery_wrong_class passed")


def test_innate_sorcery_duration_expires():
    """Innate Sorcery ticks down at the start of each of the caster's turns."""
    bm, engine, sorc, _ = _setup(1)
    engine.activate_innate_sorcery(bm, sorc)
    engine.begin_turn(bm, sorc)
    assert engine.get_agent_stats(bm, sorc).innate_sorcery_turns == 9, "first turn start ticks to 9"
    for _ in range(9):
        engine.begin_turn(bm, sorc)
    assert engine.get_agent_stats(bm, sorc).innate_sorcery_turns == 0, "expires after 10 turns"
    print("✅ test_innate_sorcery_duration_expires passed")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Font of Magic
# ─────────────────────────────────────────────────────────────────────────────

def test_convert_slot_to_sp():
    """Converting a level-N slot yields N Sorcery Points and consumes the slot."""
    bm, engine, sorc, _ = _setup(5)  # L5: L1-L3 slots, max 5 SP
    s = engine.get_agent_stats(bm, sorc)
    sp = s.get_resource("Sorcery Points")
    sp.current = 1                       # spend down so the gain is not capped
    s.resources["Sorcery Points"] = sp
    engine.set_agent_stats(bm, sorc, s)

    s = engine.get_agent_stats(bm, sorc)
    l2_before = s.spell_slots_remaining[1]
    new_sp = engine.convert_slot_to_sorcery_points(bm, sorc, 2)
    assert new_sp == 3, f"1 SP + 2 from a L2 slot = 3, got {new_sp}"
    s2 = engine.get_agent_stats(bm, sorc)
    assert s2.spell_slots_remaining[1] == l2_before - 1, "one L2 slot should be consumed"
    print("✅ test_convert_slot_to_sp passed")


def test_convert_slot_capped_at_max():
    """Sorcery Points from a slot conversion are capped at the maximum."""
    bm, engine, sorc, _ = _setup(3)  # max 3 SP
    new_sp = engine.convert_slot_to_sorcery_points(bm, sorc, 2)  # 3 + 2 would be 5, capped to 3
    assert new_sp == 3, f"SP should cap at max 3, got {new_sp}"
    print("✅ test_convert_slot_capped_at_max passed")


def test_convert_slot_none_available():
    """Converting a slot level you have none of fails with -1."""
    bm, engine, sorc, _ = _setup(1)  # only L1 slots
    assert engine.convert_slot_to_sorcery_points(bm, sorc, 3) == -1, "no L3 slot -> -1"
    print("✅ test_convert_slot_none_available passed")


def test_create_spell_slot():
    """Creating a slot spends the right SP and grants one slot of that level."""
    bm, engine, sorc, _ = _setup(5)  # 5 SP
    s = engine.get_agent_stats(bm, sorc)
    l1_before = s.spell_slots_remaining[0]
    remaining = engine.create_spell_slot(bm, sorc, 1)  # L1 costs 2 SP
    assert remaining == 3, f"5 - 2 = 3 SP, got {remaining}"
    s2 = engine.get_agent_stats(bm, sorc)
    assert s2.spell_slots_remaining[0] == l1_before + 1, "should gain one L1 slot"
    print("✅ test_create_spell_slot passed")


def test_create_spell_slot_insufficient_sp():
    """Creating a slot fails (-1) without enough Sorcery Points."""
    bm, engine, sorc, _ = _setup(1)  # 1 SP, L1 slot costs 2
    assert engine.create_spell_slot(bm, sorc, 1) == -1, "1 SP cannot create a 2-SP slot"
    print("✅ test_create_spell_slot_insufficient_sp passed")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Metamagic
# ─────────────────────────────────────────────────────────────────────────────

def test_metamagic_costs():
    """Metamagic SP costs match the 2024 PHB."""
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.Heightened) == 2
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.Quickened) == 2
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.Seeking) == 1
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.Twinned) == 1
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.NONE) == 0
    print("✅ test_metamagic_costs passed")


def test_metamagic_heightened_spends_sp():
    """Casting with Heightened deducts 2 Sorcery Points."""
    bm, engine, sorc, tgt = _setup(5)  # 5 SP
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Heightened
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 3, \
        "Heightened should spend 2 SP (5 -> 3)"
    print("✅ test_metamagic_heightened_spends_sp passed")


def test_metamagic_seeking_spends_sp():
    """Casting an attack spell with Seeking deducts 1 Sorcery Point."""
    bm, engine, sorc, tgt = _setup(5)  # 5 SP
    engine.set_agent_spells(bm, sorc, [_attack_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Seeking
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Seeking should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_seeking_spends_sp passed")


def test_metamagic_insufficient_sp_not_applied():
    """A metamagic the caster cannot afford is ignored and no SP is spent."""
    bm, engine, sorc, tgt = _setup(1)  # 1 SP; Heightened costs 2
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Heightened
    res = engine.execute_spell(bm, action)
    assert res.valid, "spell should still cast without the metamagic"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 1, \
        "no SP should be spent when the metamagic is unaffordable"
    print("✅ test_metamagic_insufficient_sp_not_applied passed")


def test_metamagic_empowered_deferred_no_spend():
    """Empowered is deferred: it is logged and ignored, spending no SP."""
    bm, engine, sorc, tgt = _setup(5)  # 5 SP
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Empowered  # deferred
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "deferred metamagic must not spend SP"
    print("✅ test_metamagic_empowered_deferred_no_spend passed")


def test_metamagic_subtle_no_spend():
    """Subtle is flavor only: no engine effect, no SP spent."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Subtle
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Subtle Spell must not spend SP"
    print("✅ test_metamagic_subtle_no_spend passed")


def test_metamagic_distant_spends_sp():
    """Distant spends 1 SP (it temporarily doubles the spell's range)."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Distant
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Distant should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_distant_spends_sp passed")


def test_metamagic_twinned_spends_sp():
    """Twinned spends 1 SP (it bumps the spell's targets-per-upcast-level)."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Twinned
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Twinned should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_twinned_spends_sp passed")


def test_metamagic_extended_spends_sp():
    """Extended spends 1 SP on a lasting spell (it doubles the duration)."""
    bm, engine, sorc, tgt = _setup(5)
    sp = _save_spell()
    sp.duration = 10  # 1 minute
    engine.set_agent_spells(bm, sorc, [sp])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Extended
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Extended should spend 1 SP on a lasting spell (5 -> 4)"
    print("✅ test_metamagic_extended_spends_sp passed")


def test_metamagic_extended_instantaneous_no_spend():
    """Extended is inapplicable to an instantaneous spell, so no SP is spent."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])  # duration defaults to 1
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Extended
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Extended on an instantaneous spell must not spend SP"
    print("✅ test_metamagic_extended_instantaneous_no_spend passed")


def test_metamagic_quickened_casts_as_bonus_action():
    """Quickened makes an Action-cast spell a Bonus Action and spends 2 SP."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])  # casting_time defaults to Action
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Quickened
    res = engine.execute_spell(bm, action)
    assert res.cast_as_bonus_action, "Quickened should flag the cast as a Bonus Action"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 3, \
        "Quickened should spend 2 SP (5 -> 3)"
    print("✅ test_metamagic_quickened_casts_as_bonus_action passed")


def test_metamagic_quickened_already_bonus_no_spend():
    """Quickened is inapplicable to a spell already cast as a Bonus Action."""
    bm, engine, sorc, tgt = _setup(5)
    sp = _save_spell()
    sp.casting_time = rpg.CastingTime.BonusAction
    engine.set_agent_spells(bm, sorc, [sp])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Quickened
    res = engine.execute_spell(bm, action)
    assert not res.cast_as_bonus_action
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Quickened on a bonus-action spell must not spend SP"
    print("✅ test_metamagic_quickened_already_bonus_no_spend passed")


def test_metamagic_transmuted_changes_damage_type():
    """Transmuted retypes the spell's elemental damage (Cold -> Fire here)."""
    bm, engine, sorc, tgt = _setup(5)
    sp = rpg.Spell()
    sp.name = "Cold Snap"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic  # no save: isolate the damage-type effect
    sp.range = 60
    sp.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Cold
    roll.num_dice = 4
    roll.die_size = 6
    sp.magic_damage_rolls = [roll]
    engine.set_agent_spells(bm, sorc, [sp])

    # Target is immune to Cold but takes Fire normally.
    t = engine.get_agent_stats(bm, tgt)
    mult = list(t.magic_damage_multipliers)
    mult[int(rpg.MagicDamage.Cold)] = 0.0
    mult[int(rpg.MagicDamage.Fire)] = 1.0
    t.magic_damage_multipliers = mult
    engine.set_agent_stats(bm, tgt, t)

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]

    base = engine.execute_spell(bm, action)
    assert base.target_results[0].total_damage == 0, "cold immunity should null the base damage"

    action.metamagic = rpg.MetamagicOption.Transmuted
    action.transmuted_damage_type = int(rpg.MagicDamage.Fire)
    res = engine.execute_spell(bm, action)
    assert res.target_results[0].total_damage > 0, "transmuted fire damage should land"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Transmuted should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_transmuted_changes_damage_type passed")


def test_metamagic_transmuted_non_elemental_no_spend():
    """Transmuted is inapplicable to a spell with no elemental damage; no SP spent."""
    bm, engine, sorc, tgt = _setup(5)
    sp = _save_spell()
    sp.magic_damage_rolls[0].type = rpg.MagicDamage.Force  # not in the elemental list
    engine.set_agent_spells(bm, sorc, [sp])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Transmuted
    action.transmuted_damage_type = int(rpg.MagicDamage.Fire)
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Transmuted on a non-elemental spell must not spend SP"
    print("✅ test_metamagic_transmuted_non_elemental_no_spend passed")


def test_metamagic_careful_shields_ally():
    """Careful excludes chosen allies from the spell's area, just like Evoker safe targets."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    sorc = add_agent_to_battle(engine, bm, create_test_agent("Sorcerer", 2, 2))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 8), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 9), hp=100)
    _sorcerer(engine, bm, sorc, 5)

    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 0
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Dexterity
    spell.geometry = rpg.SpellGeometry.Sphere
    spell.radius = 20
    spell.range = 120
    engine.set_agent_spells(bm, sorc, [spell])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.aoe_col = 8
    action.aoe_row = 8
    action.metamagic = rpg.MetamagicOption.Careful
    action.careful_targets = [ally]
    res = engine.execute_spell(bm, action)
    hit = {tr.target_idx for tr in res.target_results}
    assert enemy in hit, "enemy should still be caught in the AoE"
    assert ally not in hit, "Careful should shield the chosen ally from the area"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Careful should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_careful_shields_ally passed")


# ── Phase 3: subclass features (combat-core slice) ───────────────────────────

def test_draconic_resilience_ac():
    """Draconic Sorcerer (L3+): unarmored AC = 10 + DEX + CHA; not before L3."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("DracSorc", 5, 5))

    _sorcerer(engine, bm, idx, 3, cha=14, dex=16, subclass=rpg.SorcererSubclass.Draconic)
    ac = engine.calculate_ac(bm, idx)
    assert ac == 10 + 3 + 2, f"Draconic Resilience AC should be 15, got {ac}"

    _sorcerer(engine, bm, idx, 2, cha=14, dex=16, subclass=rpg.SorcererSubclass.Draconic)
    ac2 = engine.calculate_ac(bm, idx)
    assert ac2 == 10 + 3, f"pre-L3 Draconic sorc should be 13 (no Resilience AC), got {ac2}"
    print("✅ test_draconic_resilience_ac passed")


def test_bend_luck_bonus_and_penalty():
    """Wild Magic Bend Luck adds (+) or subtracts (-) 1d4 from the next D20 Test.

    Twin seeded engines: Bend Luck's internal 1d4 consumes the same draw as the control's
    explicit roll(4), keeping the subsequent d20 aligned.
    """
    for boost, sign in [(True, +1), (False, -1)]:
        bm_c = setup_battle_map(); ctrl = setup_combat_engine()
        idx_c = add_agent_to_battle(ctrl, bm_c, create_test_agent("WildSorc", 5, 5))
        _sorcerer(ctrl, bm_c, idx_c, 6, subclass=rpg.SorcererSubclass.WildMagic)
        die = ctrl.roll(4)
        base = ctrl.roll(20)

        bm_t = setup_battle_map(); test = setup_combat_engine()
        idx_t = add_agent_to_battle(test, bm_t, create_test_agent("WildSorc", 5, 5))
        _sorcerer(test, bm_t, idx_t, 6, subclass=rpg.SorcererSubclass.WildMagic)
        sp_before = test.get_agent_stats(bm_t, idx_t).resources["Sorcery Points"].current

        v = test.sorcerer_bend_luck(bm_t, idx_t, boost)
        assert v == die, f"internal 1d4 diverged: {v} != {die}"
        sp_after = test.get_agent_stats(bm_t, idx_t).resources["Sorcery Points"].current
        assert sp_after == sp_before - 1, "Bend Luck should spend 1 Sorcery Point"

        rolled = test.roll(20)
        assert rolled == base + sign * v, f"boost={boost}: expected {base}+{sign*v}, got {rolled}"
    print("✅ test_bend_luck_bonus_and_penalty passed")


def test_bend_luck_gating():
    """Bend Luck rejected for non-Wild-Magic, pre-L6, and with no Sorcery Points."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Sorc", 5, 5))

    _sorcerer(engine, bm, idx, 6, subclass=rpg.SorcererSubclass.Draconic)
    assert engine.sorcerer_bend_luck(bm, idx, True) == 0, "wrong subclass → no Bend Luck"

    _sorcerer(engine, bm, idx, 5, subclass=rpg.SorcererSubclass.WildMagic)
    assert engine.sorcerer_bend_luck(bm, idx, True) == 0, "pre-L6 → no Bend Luck"

    _sorcerer(engine, bm, idx, 6, subclass=rpg.SorcererSubclass.WildMagic)
    cur = engine.get_agent_stats(bm, idx).resources["Sorcery Points"].current
    engine.spend_resource(bm, idx, "Sorcery Points", cur)
    assert engine.sorcerer_bend_luck(bm, idx, True) == 0, "no Sorcery Point → no Bend Luck"
    print("✅ test_bend_luck_gating passed")


def test_wild_magic_surge_description_table():
    """The curated surge table has text for every band 1-10 and nothing outside it."""
    for effect in range(1, 11):
        desc = rpg.CombatEngine.wild_magic_surge_description(effect)
        assert desc, f"band {effect} should have description text"
    assert rpg.CombatEngine.wild_magic_surge_description(0) == ""
    assert rpg.CombatEngine.wild_magic_surge_description(11) == ""
    print("✅ test_wild_magic_surge_description_table passed")


def test_wild_magic_surge_roll_classification():
    """A L3+ Wild Magic Sorcerer rolls d100 → an effect band 1-10 matching the band math."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(engine, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)

    for _ in range(40):  # sample the RNG across many surges
        res = engine.roll_wild_magic_surge(bm, idx)
        assert 1 <= res.d100_roll <= 100, f"d100 out of range: {res.d100_roll}"
        assert res.effect == (res.d100_roll - 1) // 10 + 1, \
            f"band math: d100={res.d100_roll} → effect {res.effect}"
        assert 1 <= res.effect <= 10
        assert res.description == rpg.CombatEngine.wild_magic_surge_description(res.effect)
    print("✅ test_wild_magic_surge_roll_classification passed")


def _magic_missile():
    """A minimal Magic Missile (name-matched for immunity), auto-hit Force damage, cantrip-level
    so the test caster needs no spell slot."""
    s = rpg.Spell()
    s.name = "Magic Missile"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 120
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Force
    roll.num_dice = 1
    roll.die_size = 4
    roll.bonus = 1
    s.magic_damage_rolls = [roll]
    return s


def test_wild_magic_surge_band2_shield():
    """Band 2 spectral shield: +2 AC + Magic Missile immunity for 1 minute, then expires."""
    bm, engine, sorc, tgt = _setup(3)
    s = engine.get_agent_stats(bm, sorc)
    s.hp_max = 100; s.hp_cur = 100
    engine.set_agent_stats(bm, sorc, s)

    ac_before = engine.calculate_ac(bm, sorc)
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 2) is True
    assert engine.calculate_ac(bm, sorc) == ac_before + 2, "spectral shield grants +2 AC"
    assert engine.get_agent_stats(bm, sorc).wild_magic_shield_turns == 10

    # Magic Missile does nothing to the shielded sorcerer.
    engine.set_agent_spells(bm, tgt, [_magic_missile()])
    action = rpg.SpellAction()
    action.caster_idx = tgt
    action.spell_idx = 0
    action.target_indices = [sorc]
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).hp_cur == 100, "shield grants Magic Missile immunity"

    # Expires after 10 turn-starts: AC returns to base.
    for _ in range(10):
        engine.begin_turn(bm, sorc)
    assert engine.get_agent_stats(bm, sorc).wild_magic_shield_turns == 0
    assert engine.calculate_ac(bm, sorc) == ac_before, "AC returns to base after the shield expires"

    # Non-vacuous: with the shield gone, Magic Missile now deals damage.
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).hp_cur < 100, "Magic Missile hits once the shield is gone"
    print("✅ test_wild_magic_surge_band2_shield passed")


def test_wild_magic_surge_band3_regen():
    """Band 3: regain 5 HP at the start of each turn for 1 minute."""
    bm, engine, sorc, tgt = _setup(3)
    s = engine.get_agent_stats(bm, sorc)
    s.hp_max = 100; s.hp_cur = 50
    engine.set_agent_stats(bm, sorc, s)

    assert engine.apply_wild_magic_surge_effect(bm, sorc, 3) is True
    assert engine.get_agent_stats(bm, sorc).wild_magic_regen_turns == 10

    engine.begin_turn(bm, sorc)
    s2 = engine.get_agent_stats(bm, sorc)
    assert s2.hp_cur == 55, f"should regain 5 HP at turn start, got {s2.hp_cur}"
    assert s2.wild_magic_regen_turns == 9
    print("✅ test_wild_magic_surge_band3_regen passed")


def test_wild_magic_surge_band7_skip_turn():
    """Band 7: the surge skips the agent's next turn (once)."""
    bm, engine, sorc, tgt = _setup(3)
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 7) is True
    assert engine.get_agent_stats(bm, sorc).wild_magic_skip_next_turn is True

    res = engine.begin_turn(bm, sorc)
    assert res.turn_skipped is True and "Wild Magic" in res.skip_reason
    assert engine.get_agent_stats(bm, sorc).wild_magic_skip_next_turn is False, "skip is one-shot"

    res2 = engine.begin_turn(bm, sorc)
    assert res2.turn_skipped is False, "the following turn proceeds normally"
    print("✅ test_wild_magic_surge_band7_skip_turn passed")


def test_wild_magic_surge_band8_extra_action():
    """Band 8: sets the extra-action flag (GUI turn economy enforces the actual extra action)."""
    bm, engine, sorc, tgt = _setup(3)
    assert engine.get_agent_stats(bm, sorc).wild_magic_extra_action is False
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 8) is True
    assert engine.get_agent_stats(bm, sorc).wild_magic_extra_action is True
    print("✅ test_wild_magic_surge_band8_extra_action passed")


def test_wild_magic_surge_band6_bonus_casting():
    """Band 6: a 1-minute window for action-cast spells as a Bonus Action (ticks down each turn)."""
    bm, engine, sorc, tgt = _setup(3)
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 6) is True
    assert engine.get_agent_stats(bm, sorc).wild_magic_bonus_cast_turns == 10
    engine.begin_turn(bm, sorc)
    assert engine.get_agent_stats(bm, sorc).wild_magic_bonus_cast_turns == 9
    print("✅ test_wild_magic_surge_band6_bonus_casting passed")


def test_wild_magic_surge_band10_teleport_bonus():
    """Band 10: a 1-minute window to teleport 20 ft as a Bonus Action (ticks down each turn)."""
    bm, engine, sorc, tgt = _setup(3)
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 10) is True
    assert engine.get_agent_stats(bm, sorc).wild_magic_teleport_bonus_turns == 10
    engine.begin_turn(bm, sorc)
    assert engine.get_agent_stats(bm, sorc).wild_magic_teleport_bonus_turns == 9
    print("✅ test_wild_magic_surge_band10_teleport_bonus passed")


def test_wild_magic_surge_band9_drop_weapons():
    """Band 9 drops the caster's equipped weapons onto the ground."""
    bm, engine, sorc, tgt = _setup(3)
    weapons = list(engine.get_agent_weapons(bm, sorc))
    weapons[0] = create_melee_weapon()
    engine.set_agent_weapons(bm, sorc, weapons)
    assert engine.get_agent_weapons(bm, sorc)[0].name == "Longsword"

    items_before = len(bm.get_all_items())
    assert engine.apply_wild_magic_surge_effect(bm, sorc, 9) is True

    after = engine.get_agent_weapons(bm, sorc)
    assert after[0].name == "Unarmed", "weapon slot should be cleared back to the default (Unarmed)"
    assert len(bm.get_all_items()) == items_before + 1, "a weapon should be on the ground"
    print("✅ test_wild_magic_surge_band9_drop_weapons passed")


def test_wild_magic_surge_band1_plant_growth():
    """Band 1 application casts Plant Growth — difficult terrain around the caster."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(engine, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)

    assert not bm.has_active_terrain_effects()
    assert engine.apply_wild_magic_surge_effect(bm, idx, 1) is True
    assert bm.has_active_terrain_effects(), "Plant Growth should place difficult terrain"

    # The caster's own cell sits in the sphere → its movement cost is no longer normal.
    origin = bm.placed_agents[idx].origin
    assert bm.get_terrain_multiplier(origin) != 1.0, "caster's cell should be difficult terrain"

    # An unhandled band (band 4 not yet wired) is not engine-applied (caller handles it).
    assert engine.apply_wild_magic_surge_effect(bm, idx, 4) is False
    print("✅ test_wild_magic_surge_band1_plant_growth passed")


def test_wild_magic_surge_gating():
    """Surge yields effect 0 for non-Wild-Magic and pre-L3 sorcerers."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Sorc", 5, 5))

    _sorcerer(engine, bm, idx, 3, subclass=rpg.SorcererSubclass.Draconic)
    assert engine.roll_wild_magic_surge(bm, idx).effect == 0, "wrong subclass → no surge"

    _sorcerer(engine, bm, idx, 2, subclass=rpg.SorcererSubclass.WildMagic)
    res = engine.roll_wild_magic_surge(bm, idx)
    assert res.effect == 0 and res.d100_roll == 0, "pre-L3 → no surge"
    print("✅ test_wild_magic_surge_gating passed")


def test_sorcerer_subclass_save_load_roundtrip():
    """A saved Sorcerer's subclass + chassis restore via restore_class_resources."""
    from agent_loader import restore_class_resources
    saved = {
        "agent_class": "Sorcerer",
        "agent_char_level": 6,
        "agent_sorcerer_subclass": "WildMagic",
    }
    s = rpg.Stats()
    s.cha = 16
    restore_class_resources(s, saved, rpg)
    assert s.character_class == rpg.CharacterClass.Sorcerer
    assert s.sorcerer_subclass == rpg.SorcererSubclass.WildMagic, f"got {s.sorcerer_subclass}"
    assert "Sorcery Points" in s.resources, "chassis resource should be restored"
    print("✅ test_sorcerer_subclass_save_load_roundtrip passed")


# ── Pending-advantage (one-shot; foundation for Tides of Chaos) ──────────────

def test_pending_advantage_on_d20():
    """grant_pending_advantage makes the next d20 roll with advantage (max) / disadvantage (min)."""
    ctrl = rpg.CombatEngine(42); a, b = ctrl.roll(20), ctrl.roll(20)
    eng = rpg.CombatEngine(42); eng.grant_pending_advantage(True)
    assert eng.roll(20) == max(a, b), "advantage should keep the higher of two d20s"

    ctrl = rpg.CombatEngine(42); a, b = ctrl.roll(20), ctrl.roll(20)
    eng = rpg.CombatEngine(42); eng.grant_pending_advantage(False)
    assert eng.roll(20) == min(a, b), "disadvantage should keep the lower of two d20s"
    print("✅ test_pending_advantage_on_d20 passed")


def test_pending_advantage_one_shot_and_d20_only():
    """The pending advantage applies to exactly the next d20, and damage dice don't consume it."""
    ctrl = rpg.CombatEngine(42)
    d1, d2, d3 = ctrl.roll(20), ctrl.roll(20), ctrl.roll(20)
    eng = rpg.CombatEngine(42); eng.grant_pending_advantage(True)
    assert eng.roll(20) == max(d1, d2), "advantage on the first d20"
    assert eng.roll(20) == d3, "cleared after one roll"

    # A non-d20 (damage) roll must NOT consume the pending advantage.
    ctrl = rpg.CombatEngine(42)
    dmg, e1, e2 = ctrl.roll(8), ctrl.roll(20), ctrl.roll(20)
    eng = rpg.CombatEngine(42); eng.grant_pending_advantage(True)
    assert eng.roll(8) == dmg, "damage roll is unaffected"
    assert eng.roll(20) == max(e1, e2), "advantage still applies to the next d20"
    print("✅ test_pending_advantage_one_shot_and_d20_only passed")


# ── Task 1: Draconic L3 Resilience HP bonus ──────────────────────────────────

def test_draconic_hp_bonus():
    """Draconic L3+: hp_max += (3 + level - 3) = level extra HP. Idempotent guard prevents double-apply."""
    base_hp = 10  # default from add_agent_to_battle

    # L3: bonus = 3
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("DracSorc3", 5, 5))
    drac3 = _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.Draconic)
    assert drac3.hp_max == base_hp + 3, f"L3 Draconic: expected +3 HP, got {drac3.hp_max - base_hp}"
    assert drac3.draconic_hp_applied, "draconic_hp_applied flag must be set"

    # Idempotency: second initialize_class_resources must not add another +3.
    drac3.initialize_class_resources(rpg.CharacterClass.Sorcerer, 3)
    eng.set_agent_stats(bm, idx, drac3)
    drac3b = eng.get_agent_stats(bm, idx)
    assert drac3b.hp_max == base_hp + 3, "idempotency: second init must not grow hp_max"

    # L7: bonus = 7
    bm7 = setup_battle_map(); eng7 = setup_combat_engine()
    idx7 = add_agent_to_battle(eng7, bm7, create_test_agent("DracSorc7", 5, 5))
    drac7 = _sorcerer(eng7, bm7, idx7, 7, subclass=rpg.SorcererSubclass.Draconic)
    assert drac7.hp_max == base_hp + 7, f"L7 Draconic: expected +7 HP, got {drac7.hp_max - base_hp}"

    # L2 gate: no bonus below L3
    bm2 = setup_battle_map(); eng2 = setup_combat_engine()
    idx2 = add_agent_to_battle(eng2, bm2, create_test_agent("DracSorc2", 5, 5))
    drac2 = _sorcerer(eng2, bm2, idx2, 2, subclass=rpg.SorcererSubclass.Draconic)
    assert drac2.hp_max == base_hp, f"L2 Draconic: no HP bonus before L3, got {drac2.hp_max}"
    assert not drac2.draconic_hp_applied, "flag must stay False at L2"
    print("✅ test_draconic_hp_bonus passed")


# ── Task 2: Draconic L6 Elemental Affinity ───────────────────────────────────

def _make_fire_attack_spell():
    s = rpg.Spell()
    s.name = "Fire Bolt"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.AttackRoll
    s.range = 120
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 1
    roll.die_size = 10
    s.magic_damage_rolls = [roll]
    return s


def test_draconic_elemental_affinity():
    """Draconic L6 Elemental Affinity: CHA mod added to first matching-type damage roll per turn.
    Tests: flag set on type match, not set on type mismatch, seeded damage comparison."""
    fire_type = int(rpg.MagicDamage.Fire)
    cha = 16  # mod = +3
    cha_mod = (cha - 10) // 2

    def _setup_drac(affinity_type):
        bm = setup_battle_map(); eng = setup_combat_engine()
        sorc = add_agent_to_battle(eng, bm, create_test_agent("Sorc", 5, 5))
        tgt = add_agent_to_battle(eng, bm, create_test_agent("Tgt", 7, 5), hp=200, ac=1)
        _sorcerer(eng, bm, sorc, 6, cha=cha, subclass=rpg.SorcererSubclass.Draconic)
        s = eng.get_agent_stats(bm, sorc)
        s.draconic_affinity_type = affinity_type
        eng.set_agent_stats(bm, sorc, s)
        eng.set_agent_spells(bm, sorc, [_make_fire_attack_spell()])
        return bm, eng, sorc, tgt

    # ── Seeded damage comparison (ctrl vs test, same seed) ───────────────────
    bm_c, ctrl, sorc_c, tgt_c = _setup_drac(-1)   # no affinity
    bm_t, test, sorc_t, tgt_t = _setup_drac(fire_type)  # Fire affinity

    action_c = rpg.SpellAction(); action_c.caster_idx = sorc_c; action_c.spell_idx = 0
    action_c.target_indices = [tgt_c]
    action_t = rpg.SpellAction(); action_t.caster_idx = sorc_t; action_t.spell_idx = 0
    action_t.target_indices = [tgt_t]

    res_c = ctrl.execute_spell(bm_c, action_c)
    res_t = test.execute_spell(bm_t, action_t)
    ctrl_dmg = res_c.target_results[0].total_damage
    test_dmg = res_t.target_results[0].total_damage

    # Both use the same seed; if both hit (ctrl_dmg > 0), test engine gets +cha_mod.
    # d20=1 is a nat-1 auto-miss; with AC=1 and seed 42, if it misses we skip the damage
    # comparison but still verify the flag state.
    if ctrl_dmg > 0:
        assert test_dmg == ctrl_dmg + cha_mod, \
            f"Elemental Affinity: expected ctrl+{cha_mod}, got ctrl={ctrl_dmg} test={test_dmg}"
    else:
        # Both missed; confirm symmetry.
        assert test_dmg == 0, "both engines must produce the same miss (same seed)"

    # ── Flag behaviour: set on type match, cleared by beginTurn ──────────────
    # Fresh engine: cast a fire spell and confirm the affinity flag is set on hit.
    bm_f = setup_battle_map(); feng = setup_combat_engine()
    sorc_f = add_agent_to_battle(feng, bm_f, create_test_agent("Sorc", 5, 5))
    tgt_f = add_agent_to_battle(feng, bm_f, create_test_agent("Tgt", 7, 5), hp=200, ac=1)
    _sorcerer(feng, bm_f, sorc_f, 6, cha=cha, subclass=rpg.SorcererSubclass.Draconic)
    sf = feng.get_agent_stats(bm_f, sorc_f)
    sf.draconic_affinity_type = fire_type
    feng.set_agent_stats(bm_f, sorc_f, sf)
    feng.set_agent_spells(bm_f, sorc_f, [_make_fire_attack_spell()])
    act_f = rpg.SpellAction(); act_f.caster_idx = sorc_f; act_f.spell_idx = 0
    act_f.target_indices = [tgt_f]
    res_f = feng.execute_spell(bm_f, act_f)
    sf2 = feng.get_agent_stats(bm_f, sorc_f)
    if res_f.target_results[0].total_damage > 0:
        assert sf2.draconic_affinity_used_this_turn, "flag must be set after affinity triggers on a hit"

        # beginTurn resets the flag.
        feng.begin_turn(bm_f, sorc_f)
        sf3 = feng.get_agent_stats(bm_f, sorc_f)
        assert not sf3.draconic_affinity_used_this_turn, "beginTurn must clear the affinity flag"

    # ── Type mismatch: Cold spell must NOT trigger Fire affinity ─────────────
    bm_m = setup_battle_map(); meng = setup_combat_engine()
    sorc_m = add_agent_to_battle(meng, bm_m, create_test_agent("Sorc", 5, 5))
    tgt_m = add_agent_to_battle(meng, bm_m, create_test_agent("Tgt", 7, 5), hp=200, ac=1)
    _sorcerer(meng, bm_m, sorc_m, 6, cha=cha, subclass=rpg.SorcererSubclass.Draconic)
    sm = meng.get_agent_stats(bm_m, sorc_m)
    sm.draconic_affinity_type = fire_type
    meng.set_agent_stats(bm_m, sorc_m, sm)
    cold_spell = _save_spell("Ray of Frost")  # Cold damage, not Fire
    meng.set_agent_spells(bm_m, sorc_m, [cold_spell])
    act_m = rpg.SpellAction(); act_m.caster_idx = sorc_m; act_m.spell_idx = 0
    act_m.target_indices = [tgt_m]
    meng.execute_spell(bm_m, act_m)
    sm2 = meng.get_agent_stats(bm_m, sorc_m)
    assert not sm2.draconic_affinity_used_this_turn, "Cold spell must not trigger Fire elemental affinity"
    print("✅ test_draconic_elemental_affinity passed")


# ── Task 3: Draconic L14 Dragon Wings ────────────────────────────────────────

def test_dragon_wings():
    """Draconic L14 Dragon Wings: activate grants fly speed = walk speed; toggle removes it; L13 gated."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("DracSorc14", 5, 5))
    s = _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Draconic)
    walk = s.speed_walk
    assert walk > 0, "walk speed must be > 0"

    # Activate: fly speed should equal walk speed.
    ok = eng.activate_dragon_wings(bm, idx)
    assert ok, "activate_dragon_wings should return True for a valid Draconic L14 sorcerer"
    s2 = eng.get_agent_stats(bm, idx)
    assert s2.dragon_wings_active, "dragon_wings_active must be set after activation"
    assert s2.speed_fly == walk, f"fly speed should equal walk speed ({walk}), got {s2.speed_fly}"

    # Toggle off: fly speed removed.
    ok2 = eng.activate_dragon_wings(bm, idx)
    assert ok2, "toggle should return True"
    s3 = eng.get_agent_stats(bm, idx)
    assert not s3.dragon_wings_active, "dragon_wings_active must be cleared after toggle-off"
    assert s3.speed_fly == 0, f"fly speed must be 0 after wings dismissed, got {s3.speed_fly}"

    # Level gate: Draconic L13 must not grant Dragon Wings.
    bm13 = setup_battle_map(); eng13 = setup_combat_engine()
    idx13 = add_agent_to_battle(eng13, bm13, create_test_agent("DracSorc13", 5, 5))
    _sorcerer(eng13, bm13, idx13, 13, subclass=rpg.SorcererSubclass.Draconic)
    gated = eng13.activate_dragon_wings(bm13, idx13)
    assert not gated, "activate_dragon_wings must return False for L13 (level gate)"

    # Wrong subclass: Wild Magic L14 must not grant Dragon Wings.
    bm_w = setup_battle_map(); eng_w = setup_combat_engine()
    idx_w = add_agent_to_battle(eng_w, bm_w, create_test_agent("WildSorc14", 5, 5))
    _sorcerer(eng_w, bm_w, idx_w, 14, subclass=rpg.SorcererSubclass.WildMagic)
    gated_w = eng_w.activate_dragon_wings(bm_w, idx_w)
    assert not gated_w, "activate_dragon_wings must return False for non-Draconic subclass"
    print("✅ test_dragon_wings passed")


# ── Task 4: Aberrant Mind Psionic Spells (data-only) ─────────────────────────

def test_aberrant_psionic_spells_data():
    """Aberrant Mind psionic spell table references spells that exist in spells.json."""
    import json, pathlib
    spells_path = pathlib.Path(__file__).parent / "spells.json"
    with spells_path.open() as f:
        raw = json.load(f)
    spell_list = raw if isinstance(raw, list) else raw.get("spells", [])
    names_in_json = {s["name"] for s in spell_list}

    # The Aberrant psionic spell table (from main.py _SORCERER_SUBCLASS_SPELLS)
    psionic_spells = [
        "Arms of Hadar", "Dissonant Whispers", "Mind Sliver",     # L1
        "Hunger of Hadar", "Phantasmal Force",                    # L3
        "Clairvoyance", "Slow",                                   # L5
        "Dominate Beast", "Black Tentacles",                      # L7
        "Dominate Person", "Telekinesis",                         # L9
    ]
    missing = [n for n in psionic_spells if n not in names_in_json]
    assert not missing, f"Aberrant psionic spells missing from spells.json: {missing}"
    print("✅ test_aberrant_psionic_spells_data passed")


# ── Task 5: Aberrant L6 Psychic Defenses ─────────────────────────────────────

def test_aberrant_psychic_defenses():
    """Aberrant L6: Psychic damage resistance (0.5×). Resistance must not apply before L6."""
    psychic_idx = int(rpg.MagicDamage.Psychic)

    # L6: Psychic resistance granted.
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("AberSorc6", 5, 5))
    _sorcerer(eng, bm, idx, 6, subclass=rpg.SorcererSubclass.Aberrant)
    s = eng.get_agent_stats(bm, idx)
    mult = s.get_magic_damage_multiplier(psychic_idx)
    assert abs(mult - 0.5) < 1e-6, f"L6 Aberrant: Psychic resistance (0.5) expected, got {mult}"

    # L5 gate: resistance must NOT be granted below L6.
    bm5 = setup_battle_map(); eng5 = setup_combat_engine()
    idx5 = add_agent_to_battle(eng5, bm5, create_test_agent("AberSorc5", 5, 5))
    _sorcerer(eng5, bm5, idx5, 5, subclass=rpg.SorcererSubclass.Aberrant)
    s5 = eng5.get_agent_stats(bm5, idx5)
    mult5 = s5.get_magic_damage_multiplier(psychic_idx)
    assert abs(mult5 - 1.0) < 1e-6, f"L5 Aberrant: no Psychic resistance expected, got {mult5}"

    # Sanity: non-Psychic type unaffected (Aberrant has no Fire resistance).
    fire_idx = int(rpg.MagicDamage.Fire)
    mult_fire = s.get_magic_damage_multiplier(fire_idx)
    assert abs(mult_fire - 1.0) < 1e-6, "Aberrant should not grant Fire resistance"
    print("✅ test_aberrant_psychic_defenses passed")


if __name__ == "__main__":
    test_sorcerer_spell_slots()
    test_sorcery_points_allocation()
    test_sorcery_points_long_rest()
    test_chassis_saves()
    test_enums_bound()
    test_innate_sorcery_resource()
    test_innate_sorcery_activation()
    test_innate_sorcery_dc_bonus()
    test_innate_sorcery_no_uses()
    test_innate_sorcery_wrong_class()
    test_innate_sorcery_duration_expires()
    test_convert_slot_to_sp()
    test_convert_slot_capped_at_max()
    test_convert_slot_none_available()
    test_create_spell_slot()
    test_create_spell_slot_insufficient_sp()
    test_metamagic_costs()
    test_metamagic_heightened_spends_sp()
    test_metamagic_seeking_spends_sp()
    test_metamagic_insufficient_sp_not_applied()
    test_metamagic_empowered_deferred_no_spend()
    test_metamagic_subtle_no_spend()
    test_metamagic_distant_spends_sp()
    test_metamagic_twinned_spends_sp()
    test_metamagic_extended_spends_sp()
    test_metamagic_extended_instantaneous_no_spend()
    test_metamagic_quickened_casts_as_bonus_action()
    test_metamagic_quickened_already_bonus_no_spend()
    test_metamagic_transmuted_changes_damage_type()
    test_metamagic_transmuted_non_elemental_no_spend()
    test_metamagic_careful_shields_ally()
    test_draconic_resilience_ac()
    test_bend_luck_bonus_and_penalty()
    test_bend_luck_gating()
    test_wild_magic_surge_description_table()
    test_wild_magic_surge_roll_classification()
    test_wild_magic_surge_band1_plant_growth()
    test_wild_magic_surge_band2_shield()
    test_wild_magic_surge_band3_regen()
    test_wild_magic_surge_band7_skip_turn()
    test_wild_magic_surge_band8_extra_action()
    test_wild_magic_surge_band6_bonus_casting()
    test_wild_magic_surge_band10_teleport_bonus()
    test_wild_magic_surge_band9_drop_weapons()
    test_wild_magic_surge_gating()
    test_pending_advantage_on_d20()
    test_pending_advantage_one_shot_and_d20_only()
    test_sorcerer_subclass_save_load_roundtrip()
    # Phase 3 subclass tasks (Tasks 1–5)
    test_draconic_hp_bonus()
    test_draconic_elemental_affinity()
    test_dragon_wings()
    test_aberrant_psionic_spells_data()
    test_aberrant_psychic_defenses()
    print("\n✅ All Sorcerer tests passed!")
