#!/usr/bin/env python3
"""
Test Sorcerer: chassis + Sorcery Points (Phase 1), and Innate Sorcery, Font of
Magic (slot <-> SP conversion), and Metamagic (Heightened/Seeking) (Phase 2).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _sorcerer(engine, bm, idx, level, cha=16, prof=2):
    """Configure agent idx as a Sorcerer of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Sorcerer, level)
    s.cha = cha
    s.prof_bonus = prof
    s.can_cast_spell = True
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


def test_metamagic_unimplemented_no_spend():
    """An option without engine support is logged and ignored (no SP spent)."""
    bm, engine, sorc, tgt = _setup(5)  # 5 SP
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Twinned  # not yet implemented
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "unimplemented metamagic must not spend SP"
    print("✅ test_metamagic_unimplemented_no_spend passed")


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
    test_metamagic_unimplemented_no_spend()
    print("\n✅ All Sorcerer tests passed!")
