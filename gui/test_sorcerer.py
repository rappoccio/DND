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


def _auto_spell(num_dice=4, die_size=6, name="Empower Test"):
    """A free single-target Automatic-damage cantrip (no hit/save roll), so its
    dice_results are exactly the damage dice — ideal for exercising the damage roll."""
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 60
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Force
    roll.num_dice = num_dice
    roll.die_size = die_size
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
    assert rpg.CombatEngine.metamagic_sp_cost(rpg.MetamagicOption.Empowered) == 1
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


def test_metamagic_empowered_spends_sp():
    """Casting a damage spell with Empowered deducts 1 Sorcery Point."""
    bm, engine, sorc, tgt = _setup(5)  # 5 SP
    engine.set_agent_spells(bm, sorc, [_save_spell()])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Empowered
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Empowered should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_empowered_spends_sp passed")


def test_metamagic_empowered_no_damage_spell_not_applied():
    """Empowered on a spell that rolls no damage dice is ignored and spends no SP."""
    bm, engine, sorc, tgt = _setup(5)
    healonly = _save_spell()
    healonly.magic_damage_rolls = []  # no damage dice at all
    engine.set_agent_spells(bm, sorc, [healonly])
    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Empowered
    engine.execute_spell(bm, action)
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Empowered must not spend SP on a damageless spell"
    print("✅ test_metamagic_empowered_no_damage_spell_not_applied passed")


def test_metamagic_empowered_rerolls_low_dice():
    """Empowered raises average damage by rerolling the lowest below-average dice.
    Verified statistically on a fixed-seed engine, so the comparison is reproducible.
    Reads dice_results directly (the raw damage dice, before resistance multipliers)."""
    N = 300

    def total_dice(metamagic):
        bm, engine, sorc, tgt = _setup(20, cha=20)  # CHA 20 -> +5 reroll budget; plenty of SP
        # Bottomless target so 300 casts of 4d6 never drop it out of play.
        t = engine.get_agent_stats(bm, tgt)
        t.hp_max = 10 ** 8
        t.hp_cur = 10 ** 8
        engine.set_agent_stats(bm, tgt, t)
        engine.set_agent_spells(bm, sorc, [_auto_spell(num_dice=4, die_size=6)])
        running = 0
        for _ in range(N):
            st = engine.get_agent_stats(bm, sorc)
            sp = st.get_resource("Sorcery Points")
            sp.current = sp.max  # top up so every Empowered cast can pay its 1 SP
            st.resources["Sorcery Points"] = sp
            engine.set_agent_stats(bm, sorc, st)
            action = rpg.SpellAction()
            action.caster_idx = sorc
            action.spell_idx = 0
            action.target_indices = [tgt]
            action.metamagic = metamagic
            res = engine.execute_spell(bm, action)
            running += sum(res.target_results[0].dice_results)
        return running

    plain = total_dice(rpg.MetamagicOption.NONE)
    emp = total_dice(rpg.MetamagicOption.Empowered)
    assert emp > plain, \
        f"Empowered should raise total damage dice over {N} casts (got {emp} vs plain {plain})"
    print(f"✅ test_metamagic_empowered_rerolls_low_dice passed (emp {emp} > plain {plain})")


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


def test_metamagic_careful_shields_caster():
    """Careful Spell spares the CASTER from their own area, even standing in the blast.
    (A Careful caster never catches themselves — separate from the CHA-mod-capped ally set.)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    sorc = add_agent_to_battle(engine, bm, create_test_agent("Sorcerer", 5, 5), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5), hp=100)
    _sorcerer(engine, bm, sorc, 5)

    spell = rpg.Spell()
    spell.name = "Fireball"
    spell.level = 0
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Dexterity
    spell.geometry = rpg.SpellGeometry.Sphere
    spell.radius = 20
    spell.range = 120
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 8
    roll.die_size = 6
    spell.magic_damage_rolls = [roll]
    engine.set_agent_spells(bm, sorc, [spell])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.aoe_col = 5   # centered on the caster's OWN cell
    action.aoe_row = 5
    action.metamagic = rpg.MetamagicOption.Careful
    # NB: no careful_targets passed — caster protection is independent of the chosen-ally set.
    res = engine.execute_spell(bm, action)
    hit = {tr.target_idx for tr in res.target_results}
    assert sorc not in hit, "Careful should spare the caster from their own AoE"
    assert engine.get_agent_stats(bm, sorc).hp_cur == 100, "the caster should take no damage"
    assert enemy in hit, "enemies are still caught in the area"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Careful should spend 1 SP (5 -> 4)"
    print("✅ test_metamagic_careful_shields_caster passed")


# ── Metamagic Phase 3: Twinned Spell (the one engine change) ─────────────────

def test_twinned_num_targets_helper():
    """getNumTargetsForSpell honors the twinned flag: Single 1->2, and it is the single
    source of truth for the extra-target math (target COUNT only, no upcast damage change)."""
    bm, engine, sorc, tgt = _setup(5)
    single = _save_spell()
    assert engine.get_num_targets_for_spell(single, 0, 5, False) == 1, \
        "a Single-geometry spell targets one creature normally"
    assert engine.get_num_targets_for_spell(single, 0, 5, True) == 2, \
        "Twinned gives a Single-geometry spell one additional target"
    print("✅ test_twinned_num_targets_helper passed")


def test_twinned_single_target_hits_two():
    """Twinned Spell on a Single-geometry spell applies to BOTH clicked targets and spends 1 SP.
    Without Twinned, the engine authoritatively caps a Single spell to its first target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    sorc = add_agent_to_battle(engine, bm, create_test_agent("Sorcerer", 5, 5))
    t1 = add_agent_to_battle(engine, bm, create_test_agent("T1", 6, 5), hp=200)
    t2 = add_agent_to_battle(engine, bm, create_test_agent("T2", 7, 5), hp=200)
    _sorcerer(engine, bm, sorc, 5, cha=16)
    # Automatic damage (no save/attack roll) so both targets deterministically take damage.
    engine.set_agent_spells(bm, sorc, [_auto_spell(num_dice=4, die_size=6)])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [t1, t2]
    action.metamagic = rpg.MetamagicOption.Twinned
    res = engine.execute_spell(bm, action)
    assert res.valid, "the twinned spell should cast"
    hp1 = engine.get_agent_stats(bm, t1).hp_cur
    hp2 = engine.get_agent_stats(bm, t2).hp_cur
    assert hp1 < 200 and hp2 < 200, f"both twin targets should be damaged (got {hp1}, {hp2})"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "Twinned should spend 1 SP (5 -> 4)"

    # Same two targets passed WITHOUT Twinned: the engine trims to one (Single geometry).
    for t in (t1, t2):
        st = engine.get_agent_stats(bm, t); st.hp_cur = 200
        engine.set_agent_stats(bm, t, st)
    plain = rpg.SpellAction()
    plain.caster_idx = sorc
    plain.spell_idx = 0
    plain.target_indices = [t1, t2]
    engine.execute_spell(bm, plain)
    hp1b = engine.get_agent_stats(bm, t1).hp_cur
    hp2b = engine.get_agent_stats(bm, t2).hp_cur
    assert hp1b < 200 and hp2b == 200, \
        f"without Twinned only the first target is hit (got {hp1b}, {hp2b})"
    print("✅ test_twinned_single_target_hits_two passed")


def _incarnate_sorcerer(level=7, cha=16):
    """A Sorcerer + two 200-HP targets, for the two-option (Sorcery Incarnate) casts."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    sorc = add_agent_to_battle(engine, bm, create_test_agent("Sorcerer", 5, 5))
    t1 = add_agent_to_battle(engine, bm, create_test_agent("T1", 6, 5), hp=200)
    t2 = add_agent_to_battle(engine, bm, create_test_agent("T2", 7, 5), hp=200)
    _sorcerer(engine, bm, sorc, level, cha=cha)
    # Automatic damage (no save/attack roll) so every kept target deterministically takes damage.
    engine.set_agent_spells(bm, sorc, [_auto_spell(num_dice=4, die_size=6)])
    return bm, engine, sorc, t1, t2


def test_sorcery_incarnate_predicate():
    """Sorcery Incarnate is Sorcerer L7+ AND Innate Sorcery currently active."""
    bm, engine, sorc, _ = _setup(6)
    assert not rpg.CombatEngine.sorcery_incarnate_active(engine.get_agent_stats(bm, sorc)), \
        "inactive Innate Sorcery is not Sorcery Incarnate"
    engine.activate_innate_sorcery(bm, sorc)
    assert not rpg.CombatEngine.sorcery_incarnate_active(engine.get_agent_stats(bm, sorc)), \
        "Sorcery Incarnate needs level 7 (L6 with Innate Sorcery active does not qualify)"

    bm, engine, sorc, _ = _setup(7)
    assert not rpg.CombatEngine.sorcery_incarnate_active(engine.get_agent_stats(bm, sorc)), \
        "a L7 Sorcerer without Innate Sorcery running is not incarnate"
    engine.activate_innate_sorcery(bm, sorc)
    assert rpg.CombatEngine.sorcery_incarnate_active(engine.get_agent_stats(bm, sorc)), \
        "L7 + Innate Sorcery active = Sorcery Incarnate"
    print("✅ test_sorcery_incarnate_predicate passed")


def test_sorcery_incarnate_two_options():
    """Sorcery Incarnate: BOTH Metamagic options apply to one cast, each paying its own SP."""
    bm, engine, sorc, t1, t2 = _incarnate_sorcerer(7)
    engine.activate_innate_sorcery(bm, sorc)       # free use — spends no SP

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [t1, t2]
    action.metamagic = rpg.MetamagicOption.Quickened   # 2 SP
    action.metamagic2 = rpg.MetamagicOption.Twinned    # 1 SP
    res = engine.execute_spell(bm, action)

    assert res.valid, "the two-option spell should cast"
    assert res.cast_as_bonus_action, "Quickened (slot 1) should flag the cast as a Bonus Action"
    hp1 = engine.get_agent_stats(bm, t1).hp_cur
    hp2 = engine.get_agent_stats(bm, t2).hp_cur
    assert hp1 < 200 and hp2 < 200, \
        f"Twinned (slot 2) should give the Single-geometry spell a 2nd target (got {hp1}, {hp2})"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 4, \
        "both options should be paid for: 7 SP - 2 (Quickened) - 1 (Twinned) = 4"
    print("✅ test_sorcery_incarnate_two_options passed")


def test_sorcery_incarnate_gates_second_option():
    """Without Sorcery Incarnate, the 2nd option is dropped — unapplied AND unpaid."""
    bm, engine, sorc, t1, t2 = _incarnate_sorcerer(7)   # L7, but Innate Sorcery NOT active

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [t1, t2]
    action.metamagic = rpg.MetamagicOption.Quickened   # 2 SP — still applies
    action.metamagic2 = rpg.MetamagicOption.Twinned    # dropped: no Sorcery Incarnate
    res = engine.execute_spell(bm, action)

    assert res.cast_as_bonus_action, "the first option still applies"
    hp2 = engine.get_agent_stats(bm, t2).hp_cur
    assert hp2 == 200, "the dropped Twinned must not grant an extra target"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "only the first option is paid for: 7 SP - 2 (Quickened) = 5"
    print("✅ test_sorcery_incarnate_gates_second_option passed")


def test_metamagic_seeking_stacks_without_incarnate():
    """Seeking is the standing exception: it rides along with one other option at any level,
    with no Innate Sorcery needed (SRD p.66)."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_attack_spell()])   # Seeking needs a spell-attack roll

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Quickened   # 2 SP
    action.metamagic2 = rpg.MetamagicOption.Seeking    # 1 SP — stacks
    res = engine.execute_spell(bm, action)

    assert res.cast_as_bonus_action, "Quickened should still apply alongside Seeking"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 2, \
        "both should be paid for even without Sorcery Incarnate: 5 - 2 (Quickened) - 1 (Seeking) = 2"
    print("✅ test_metamagic_seeking_stacks_without_incarnate passed")


def test_metamagic_duplicate_option_charged_once():
    """The same option in both slots is applied (and paid for) exactly once."""
    bm, engine, sorc, tgt = _setup(5)
    engine.set_agent_spells(bm, sorc, [_save_spell()])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.metamagic = rpg.MetamagicOption.Quickened
    action.metamagic2 = rpg.MetamagicOption.Quickened
    res = engine.execute_spell(bm, action)

    assert res.cast_as_bonus_action
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 3, \
        "a duplicated option must be charged once (5 - 2 = 3)"
    print("✅ test_metamagic_duplicate_option_charged_once passed")


def test_innate_sorcery_sp_fallback_at_l7():
    """Sorcery Incarnate (L7): with the uses spent, 2 SP activate Innate Sorcery. Below L7 it
    just fails."""
    for level, expect_ok in ((6, False), (7, True)):
        bm, engine, sorc, _ = _setup(level)
        s = engine.get_agent_stats(bm, sorc)
        innate = s.get_resource("Innate Sorcery")
        innate.current = 0
        s.resources["Innate Sorcery"] = innate
        engine.set_agent_stats(bm, sorc, s)

        ok = engine.activate_innate_sorcery(bm, sorc)
        after = engine.get_agent_stats(bm, sorc)
        assert ok == expect_ok, f"L{level} with no uses left: expected activation {expect_ok}"
        assert after.innate_sorcery_turns == (10 if expect_ok else 0), \
            f"L{level}: buff should {'run' if expect_ok else 'not run'}"
        # SP = level; the L7 fallback costs 2 of them, the L6 failure costs none.
        assert after.get_resource("Sorcery Points").current == (level - 2 if expect_ok else level), \
            f"L{level}: the 2-SP fallback should only be charged when it activates"
    print("✅ test_innate_sorcery_sp_fallback_at_l7 passed")


def test_twinned_gating():
    """Twinned on an area spell (not single-target) is rejected before spending any SP."""
    bm, engine, sorc, tgt = _setup(5)
    aoe = _auto_spell(num_dice=2, die_size=6, name="Twinned Area Test")
    aoe.geometry = rpg.SpellGeometry.Sphere
    aoe.radius = 20
    engine.set_agent_spells(bm, sorc, [aoe])

    action = rpg.SpellAction()
    action.caster_idx = sorc
    action.spell_idx = 0
    action.target_indices = [tgt]
    action.aoe_col = 6
    action.aoe_row = 5
    action.metamagic = rpg.MetamagicOption.Twinned
    res = engine.execute_spell(bm, action)
    assert res.valid, "the spell should still cast without the (inapplicable) metamagic"
    assert engine.get_agent_stats(bm, sorc).get_resource("Sorcery Points").current == 5, \
        "Twinned must not spend SP on an area spell that can't be twinned"
    print("✅ test_twinned_gating passed")


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


def test_metamagic_learn_roundtrip():
    """Learned Metamagic options survive the save-dict → dict_to_stats reload cycle.
    (Save side mirrors main.py's stats block; load side is agent_loader.dict_to_stats.)"""
    from agent_loader import dict_to_stats
    chosen = [rpg.MetamagicOption.Careful, rpg.MetamagicOption.Twinned, rpg.MetamagicOption.Heightened]
    s = rpg.Stats()
    s.metamagic_options = chosen
    # Serialize exactly as main.py's save block does, then reload.
    stats_dict = {"metamagic_options": [int(m) for m in s.metamagic_options]}
    restored = dict_to_stats(stats_dict)
    got = [rpg.MetamagicOption(int(v)) for v in restored.metamagic_options]
    assert got == chosen, f"metamagic options changed across save/reload: {got} != {chosen}"
    # An empty/absent list must round-trip to empty, not error.
    assert list(dict_to_stats({}).metamagic_options) == [], "missing key should yield no options"
    print("✅ test_metamagic_learn_roundtrip passed")


def test_metamagic_known_count_cap():
    """SRD p.65 known-count rule: 0 below L2, 2 at L2, 4 at L10, 6 at L17 (max 6)."""
    from dialogs import metamagic_known_count
    assert metamagic_known_count(1) == 0
    assert metamagic_known_count(2) == 2
    assert metamagic_known_count(9) == 2
    assert metamagic_known_count(10) == 4
    assert metamagic_known_count(16) == 4
    assert metamagic_known_count(17) == 6
    assert metamagic_known_count(20) == 6
    print("✅ test_metamagic_known_count_cap passed")


def test_metamagic_offered_gate():
    """Sidebar gate (Phase 2): an option is offered only when LEARNED and AFFORDABLE.
    Not learned → hidden; learned but too few SP → hidden; learned + affordable → shown."""
    from dialogs import metamagic_offered
    learned = [rpg.MetamagicOption.Distant, rpg.MetamagicOption.Heightened]
    dist, heit = rpg.MetamagicOption.Distant, rpg.MetamagicOption.Heightened
    quick = rpg.MetamagicOption.Quickened  # not learned
    cost_dist = rpg.CombatEngine.metamagic_sp_cost(dist)   # 1
    cost_heit = rpg.CombatEngine.metamagic_sp_cost(heit)   # 2
    # Not learned → never offered, even with plenty of SP.
    assert not metamagic_offered(quick, learned, 5, rpg.CombatEngine.metamagic_sp_cost(quick))
    # Learned + affordable → offered.
    assert metamagic_offered(dist, learned, 1, cost_dist)
    assert metamagic_offered(heit, learned, 2, cost_heit)
    # Learned but can't afford → hidden (Heightened costs 2, only 1 SP).
    assert not metamagic_offered(heit, learned, 1, cost_heit)
    # Empty learned set → nothing offered.
    assert not metamagic_offered(dist, [], 5, cost_dist)
    print("✅ test_metamagic_offered_gate passed")


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


# ── Phase 4: Wild Magic Surge trigger + Tides of Chaos ───────────────────────

def test_tides_of_chaos_resource_granted():
    """Tides of Chaos: a 1-use resource for L3+ Wild Magic sorcerers; absent otherwise."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))

    s = _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)
    assert "Tides of Chaos" in s.resources, "L3 Wild Magic should have Tides of Chaos"
    assert s.resources["Tides of Chaos"].current == 1

    # Pre-L3 Wild Magic: not yet.
    s2 = _sorcerer(eng, bm, idx, 2, subclass=rpg.SorcererSubclass.WildMagic)
    assert "Tides of Chaos" not in s2.resources, "pre-L3 → no Tides of Chaos"

    # Wrong subclass: Draconic L3 has no Tides of Chaos.
    s3 = _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.Draconic)
    assert "Tides of Chaos" not in s3.resources, "Draconic → no Tides of Chaos"
    print("✅ test_tides_of_chaos_resource_granted passed")


def test_tides_of_chaos_grants_advantage():
    """Activating Tides of Chaos spends the use and makes the next d20 roll with Advantage."""
    # Twin seeded engines: activation consumes no RNG, so the d20 draws stay aligned.
    bm_c = setup_battle_map(); ctrl = setup_combat_engine()
    idx_c = add_agent_to_battle(ctrl, bm_c, create_test_agent("WildSorc", 5, 5))
    _sorcerer(ctrl, bm_c, idx_c, 3, subclass=rpg.SorcererSubclass.WildMagic)
    a, b = ctrl.roll(20), ctrl.roll(20)

    bm_t = setup_battle_map(); test = setup_combat_engine()
    idx_t = add_agent_to_battle(test, bm_t, create_test_agent("WildSorc", 5, 5))
    _sorcerer(test, bm_t, idx_t, 3, subclass=rpg.SorcererSubclass.WildMagic)

    assert test.activate_tides_of_chaos(bm_t, idx_t) is True, "activation should succeed"
    assert test.get_agent_stats(bm_t, idx_t).resources["Tides of Chaos"].current == 0, \
        "Tides of Chaos use should be spent"
    assert test.roll(20) == max(a, b), "next d20 should be rolled with Advantage"

    # Second activation fails: the use is gone (no recharge yet).
    assert test.activate_tides_of_chaos(bm_t, idx_t) is False, "no use left → activation fails"
    print("✅ test_tides_of_chaos_grants_advantage passed")


def test_tides_of_chaos_gating():
    """Tides of Chaos rejected for non-Wild-Magic and pre-L3 sorcerers."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("Sorc", 5, 5))

    _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.Draconic)
    assert eng.activate_tides_of_chaos(bm, idx) is False, "wrong subclass → no Tides of Chaos"

    _sorcerer(eng, bm, idx, 2, subclass=rpg.SorcererSubclass.WildMagic)
    assert eng.activate_tides_of_chaos(bm, idx) is False, "pre-L3 → no Tides of Chaos"
    print("✅ test_tides_of_chaos_gating passed")


def test_surge_forced_and_recharges_tides():
    """While Tides of Chaos is expended, the next slot-spell cast FORCES a surge (no nat-20
    needed), and the surge recharges Tides of Chaos."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)

    # Expend Tides of Chaos (its advantage is consumed by a roll we don't care about here).
    assert eng.activate_tides_of_chaos(bm, idx) is True
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 0

    res = eng.maybe_wild_magic_surge(bm, idx)
    assert 1 <= res.effect <= 10, f"expended Tides must force a surge, got effect {res.effect}"
    assert res.description == rpg.CombatEngine.wild_magic_surge_description(res.effect)
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 1, \
        "the forced surge should recharge Tides of Chaos"
    print("✅ test_surge_forced_and_recharges_tides passed")


def test_surge_unforced_tides_invariant():
    """With Tides of Chaos full, a surge check may or may not fire (natural 20), but a surge never
    spends Tides of Chaos, and every result is a valid band (0 = no surge, else 1-10)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)

    saw_no_surge = False
    for _ in range(60):
        res = eng.maybe_wild_magic_surge(bm, idx)
        assert res.effect == 0 or 1 <= res.effect <= 10, f"invalid band {res.effect}"
        if res.effect == 0:
            saw_no_surge = True
        # Tides stays full throughout: it was never expended, so nothing recharges/spends it.
        assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 1
    assert saw_no_surge, "across 60 checks at ~5% surge odds, expect at least one no-surge"
    print("✅ test_surge_unforced_tides_invariant passed")


def test_maybe_surge_gating():
    """maybe_wild_magic_surge is a no-op (effect 0) for non-Wild-Magic and pre-L3 sorcerers."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("Sorc", 5, 5))

    _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.Draconic)
    assert eng.maybe_wild_magic_surge(bm, idx).effect == 0, "wrong subclass → no surge"

    _sorcerer(eng, bm, idx, 2, subclass=rpg.SorcererSubclass.WildMagic)
    assert eng.maybe_wild_magic_surge(bm, idx).effect == 0, "pre-L3 → no surge"
    print("✅ test_maybe_surge_gating passed")


def test_tides_of_chaos_long_rest_restore():
    """Tides of Chaos returns to 1 use after a long rest."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)

    assert eng.activate_tides_of_chaos(bm, idx) is True
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 0
    eng.apply_long_rest(bm)
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 1, \
        "a long rest should restore Tides of Chaos"
    print("✅ test_tides_of_chaos_long_rest_restore passed")


# ── Wild Magic: Controlled Chaos (L14) + Tamed Surge (L18) via offer/resolve ─────────────────

def _wild_expended(eng, bm, level):
    """A Wild-Magic sorcerer of `level` with Tides of Chaos expended (so offers force a surge).
    Returns its index."""
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(eng, bm, idx, level, subclass=rpg.SorcererSubclass.WildMagic)
    assert eng.activate_tides_of_chaos(bm, idx) is True   # expend → forces surge on every offer
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 0
    return idx


def test_controlled_chaos_rolls_two_bands():
    """Controlled Chaos (L14): the surge OFFER rolls the table twice (1-2 distinct bands); a L13
    sorcerer's offer only ever yields one band."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = _wild_expended(eng, bm, 14)

    saw_two = False
    for _ in range(40):                          # offer doesn't resolve → Tides stays expended
        offer = eng.offer_wild_magic_surge(bm, idx)
        assert offer.surged is True, "expended Tides must force a surge"
        assert offer.tides_expended is True
        assert offer.can_choose_any is False, "Controlled Chaos is L14, Tamed Surge is L18"
        assert 1 <= len(offer.options) <= 2, f"expected 1-2 bands, got {list(offer.options)}"
        for b in offer.options:
            assert 1 <= b <= 10, f"band out of range: {b}"
        if len(offer.options) == 2:
            saw_two = True
    assert saw_two, "L14 should roll twice — across 40 forced surges expect ≥1 pair of distinct bands"

    # L13: a single band only (no Controlled Chaos).
    idx13 = _wild_expended(eng, bm, 13)
    for _ in range(20):
        offer = eng.offer_wild_magic_surge(bm, idx13)
        assert offer.surged is True
        assert len(offer.options) == 1, f"pre-L14 should roll once, got {list(offer.options)}"
    print("✅ test_controlled_chaos_rolls_two_bands passed")


def test_tamed_surge_can_choose_any():
    """Tamed Surge (L18): the offer flags can_choose_any so the caller may pick any band 1-10; a
    L17 sorcerer's offer does not."""
    bm = setup_battle_map(); eng = setup_combat_engine()

    idx18 = _wild_expended(eng, bm, 18)
    offer = eng.offer_wild_magic_surge(bm, idx18)
    assert offer.surged is True
    assert offer.can_choose_any is True, "L18 Tamed Surge → may choose any band"

    idx17 = _wild_expended(eng, bm, 17)
    offer = eng.offer_wild_magic_surge(bm, idx17)
    assert offer.surged is True
    assert offer.can_choose_any is False, "pre-L18 → no free choice of band"
    print("✅ test_tamed_surge_can_choose_any passed")


def test_resolve_wild_magic_surge_applies_chosen_band():
    """resolve_wild_magic_surge applies the chosen band's effect, recharges Tides only when
    tides_expended is passed True, and is a no-op for out-of-range bands."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = _wild_expended(eng, bm, 14)

    # Resolve a chosen band (2 = spectral shield) WITH the expended flag → effect applied + recharge.
    res = eng.resolve_wild_magic_surge(bm, idx, 2, True)
    assert res.effect == 2
    assert res.description == rpg.CombatEngine.wild_magic_surge_description(2)
    assert eng.get_agent_stats(bm, idx).wild_magic_shield_turns == 10, "band 2 grants the shield"
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 1, \
        "resolving with tides_expended=True recharges Tides of Chaos"

    # Re-expend, then resolve with tides_expended=False → effect applied, NO recharge.
    assert eng.activate_tides_of_chaos(bm, idx) is True
    res = eng.resolve_wild_magic_surge(bm, idx, 3, False)
    assert res.effect == 3
    assert eng.get_agent_stats(bm, idx).wild_magic_regen_turns == 10, "band 3 grants regen"
    assert eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current == 0, \
        "tides_expended=False must NOT recharge Tides of Chaos"

    # Out-of-range bands are no-ops.
    assert eng.resolve_wild_magic_surge(bm, idx, 0, False).effect == 0
    assert eng.resolve_wild_magic_surge(bm, idx, 11, False).effect == 0
    print("✅ test_resolve_wild_magic_surge_applies_chosen_band passed")


def test_offer_surge_gating():
    """offer_wild_magic_surge is a no-op (surged False) for non-Wild-Magic and pre-L3 sorcerers."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("Sorc", 5, 5))

    _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Draconic)
    assert eng.offer_wild_magic_surge(bm, idx).surged is False, "wrong subclass → no surge"

    _sorcerer(eng, bm, idx, 2, subclass=rpg.SorcererSubclass.WildMagic)
    assert eng.offer_wild_magic_surge(bm, idx).surged is False, "pre-L3 → no surge"
    print("✅ test_offer_surge_gating passed")


# ── Clockwork Soul: Clockwork Spells (data) + Restore Balance (OnD20Seen reaction) ───────────

def _clock_greataxe():
    w = rpg.Weapon(); w.name = "Greataxe"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Slashing; pr.num_dice = 1; pr.die_size = 12
    w.physical_damage_types = [pr]
    return w


def test_clockwork_spells_data():
    """Clockwork Soul Clockwork-spell table references spells that all exist in spells.json."""
    import json, pathlib
    spells_path = pathlib.Path(__file__).parent / "spells.json"
    with spells_path.open() as f:
        raw = json.load(f)
    spell_list = raw if isinstance(raw, list) else raw.get("spells", [])
    names_in_json = {s["name"] for s in spell_list}
    clockwork_spells = [
        "Aid", "Alarm", "Lesser Restoration", "Protection from Evil and Good",  # L3
        "Dispel Magic", "Protection from Energy",                               # L5
        "Freedom of Movement", "Summon Construct",                             # L7
        "Greater Restoration", "Wall of Force",                               # L9
    ]
    missing = [n for n in clockwork_spells if n not in names_in_json]
    assert not missing, f"Clockwork spells missing from spells.json: {missing}"
    print("✅ test_clockwork_spells_data passed")


def test_restore_balance_resource_granted():
    """Restore Balance: a PB-use resource for L3+ Clockwork sorcerers; absent otherwise."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))

    # L3 (PB 2) → 2 uses; L5 (PB 3) → 3 uses.
    s3 = _sorcerer(eng, bm, idx, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Restore Balance" in s3.resources, "L3 Clockwork should have Restore Balance"
    assert s3.resources["Restore Balance"].current == 2, \
        f"L3 (PB 2) → 2 uses, got {s3.resources['Restore Balance'].current}"
    s5 = _sorcerer(eng, bm, idx, 5, prof=3, subclass=rpg.SorcererSubclass.Clockwork)
    assert s5.resources["Restore Balance"].current == 3, \
        f"L5 (PB 3) → 3 uses, got {s5.resources['Restore Balance'].current}"

    # Pre-L3 Clockwork and wrong subclass: not granted.
    s2 = _sorcerer(eng, bm, idx, 2, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Restore Balance" not in s2.resources, "pre-L3 → no Restore Balance"
    sw = _sorcerer(eng, bm, idx, 3, subclass=rpg.SorcererSubclass.WildMagic)
    assert "Restore Balance" not in sw.resources, "Wild Magic → no Restore Balance"
    print("✅ test_restore_balance_resource_granted passed")


def test_restore_balance_long_rest_restore():
    """Spent Restore Balance uses come back on a long rest."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 5, prof=3, subclass=rpg.SorcererSubclass.Clockwork)
    s.resources["Restore Balance"].current = 0
    eng.set_agent_stats(bm, idx, s)
    eng.apply_long_rest(bm)
    assert eng.get_agent_stats(bm, idx).resources["Restore Balance"].current == 3, \
        "a long rest should restore Restore Balance to full (PB)"
    print("✅ test_restore_balance_long_rest_restore passed")


def _clock_rb_setup(eng, bm):
    """Attacker (STR 18) at (5,5) with a greataxe; prone target at (6,5) → attacker has advantage;
    Clockwork L3 sorcerer reactor at (5,7) (≈10 ft, clear LoS)."""
    atk = add_agent_to_battle(eng, bm, create_test_agent("Atk", 5, 5))
    tgt = add_agent_to_battle(eng, bm, create_test_agent("Def", 6, 5))
    rea = add_agent_to_battle(eng, bm, create_test_agent("Clock", 5, 7))

    a = eng.get_agent_stats(bm, atk); a.str = 18; a.prof_bonus = 3; a.hp_max = 30; a.hp_cur = 30
    eng.set_agent_stats(bm, atk, a)
    eng.set_agent_weapons(bm, atk, [_clock_greataxe(), rpg.Weapon(), rpg.Weapon()])

    t = eng.get_agent_stats(bm, tgt); t.base_ac = 15; t.hp_max = 60; t.hp_cur = 60
    eng.set_agent_stats(bm, tgt, t)

    _sorcerer(eng, bm, rea, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    r = eng.get_agent_stats(bm, rea); r.hp_max = 30; r.hp_cur = 30
    eng.set_agent_stats(bm, rea, r)
    return atk, tgt, rea


def _clock_reset(eng, bm, atk, tgt, rea):
    """Independent attempt: refill HP, set the target Prone (advantage source), clear reactions."""
    t = eng.get_agent_stats(bm, tgt); t.hp_cur = t.hp_max; eng.set_agent_stats(bm, tgt, t)
    tc = eng.get_agent_conditions(bm, tgt); tc.prone = True; tc.reaction_used = False
    eng.set_agent_conditions(bm, tgt, tc)
    s = _sorcerer(eng, bm, rea, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    s.hp_max = 30; s.hp_cur = 30; eng.set_agent_stats(bm, rea, s)
    rc = eng.get_agent_conditions(bm, rea); rc.reaction_used = False; rc.incapacitated = False
    eng.set_agent_conditions(bm, rea, rc)


def test_restore_balance_gate():
    """can_restore_balance: eligible only for an advantaged attack roll by an in-range Clockwork L3+
    sorcerer with a use + free reaction. A non-advantaged roll, drained resource, spent reaction, or
    wrong subclass each disqualify it. AttackResult is engine-constructed, so an advantaged result is
    obtained from execute_action (no decider installed → no reaction auto-fires)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    atk, tgt, rea = _clock_rb_setup(eng, bm)
    _clock_reset(eng, bm, atk, tgt, rea)

    # Prone target → the attack roll is made at advantage. execute_action returns that result.
    r = eng.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert r.advantage and not r.disadvantage, "prone target → the attack roll is at advantage"
    assert eng.can_restore_balance(bm, rea, atk, r), "in-range Clockwork w/ a use is eligible"

    # A non-advantaged result (target stands up) is never eligible, even for the same reactor.
    tc = eng.get_agent_conditions(bm, tgt); tc.prone = False; eng.set_agent_conditions(bm, tgt, tc)
    flat = eng.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert not flat.advantage, "with the target standing the roll is flat"
    assert not eng.can_restore_balance(bm, rea, atk, flat), "no advantage → Restore Balance ineligible"

    # Drain the resource → ineligible (on the advantaged result r).
    s = eng.get_agent_stats(bm, rea); s.resources["Restore Balance"].current = 0
    eng.set_agent_stats(bm, rea, s)
    assert not eng.can_restore_balance(bm, rea, atk, r), "no Restore Balance use → ineligible"

    # Refill but spend the reaction → ineligible.
    _sorcerer(eng, bm, rea, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    c = eng.get_agent_conditions(bm, rea); c.reaction_used = True
    eng.set_agent_conditions(bm, rea, c)
    assert not eng.can_restore_balance(bm, rea, atk, r), "spent reaction → ineligible"

    # Wrong subclass (Wild Magic) → ineligible even with a free reaction.
    _sorcerer(eng, bm, rea, 6, prof=3, subclass=rpg.SorcererSubclass.WildMagic)
    assert not eng.can_restore_balance(bm, rea, atk, r), "non-Clockwork subclass → ineligible"
    print("✅ test_restore_balance_gate passed")


def test_restore_balance_cancels_advantage_can_miss():
    """Driving begin_attack with an advantaged (prone-target) hit parks the OnD20Seen window; submitting
    Restore Balance reverts the kept die to the primary die (cancel advantage), spending one use + the
    reaction, and can flip the hit to a miss (no damage on a flipped miss)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    atk, tgt, rea = _clock_rb_setup(eng, bm)
    saw_window = saw_miss = False
    for _ in range(400):
        _clock_reset(eng, bm, atk, tgt, rea)
        status = eng.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status != rpg.FlowStatus.AwaitingDecision:
            continue
        ctx = eng.pending_decision().ctx
        assert ctx.window == rpg.ReactionWindow.OnD20Seen and ctx.reactor_idx == rea
        opt = next((i for i, o in enumerate(ctx.options)
                    if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "RestoreBalance"), None)
        if opt is None:
            continue
        saw_window = True
        resp = rpg.ReactionResponse(); resp.option = opt
        eng.submit_decision(bm, resp)
        assert eng.get_agent_conditions(bm, rea).reaction_used, "Restore Balance spends the reaction"
        assert eng.get_agent_stats(bm, rea).resources["Restore Balance"].current == 1, \
            "Restore Balance spends one use (2 → 1)"
        r = eng.last_attack_result()
        assert not r.advantage, "advantage flag cleared after Restore Balance"
        assert r.d20 == r.d20_primary, "kept die reverted to the primary die"
        if not r.hit:
            saw_miss = True
            assert eng.get_agent_stats(bm, tgt).hp_cur == 60, "a flipped-to-miss deals no damage"
        if saw_window and saw_miss:
            print("✅ test_restore_balance_cancels_advantage_can_miss passed")
            return
    assert False, "did not observe both a window and a flipped-to-miss in 400 advantaged attacks"


# ── Restore Balance — disadvantage-cancel (OnMiss raising) direction ──────────

def _clock_rb_miss_setup(eng, bm, target_ac=12):
    """Attacker (STR 18) at (5,5) w/ greataxe; ENEMY target at (6,5); Clockwork L3 ALLY reactor at
    (5,7). Attacker + reactor share a faction so Restore Balance may cancel Disadvantage to aid the
    attacker; the target is on an enemy faction. A low target AC makes a cancelled miss likely to hit."""
    atk = add_agent_to_battle(eng, bm, create_test_agent("Atk", 5, 5))
    tgt = add_agent_to_battle(eng, bm, create_test_agent("Def", 6, 5))
    rea = add_agent_to_battle(eng, bm, create_test_agent("Clock", 5, 7))

    a = eng.get_agent_stats(bm, atk); a.str = 18; a.prof_bonus = 3; a.hp_max = 30; a.hp_cur = 30
    eng.set_agent_stats(bm, atk, a)
    eng.set_agent_weapons(bm, atk, [_clock_greataxe(), rpg.Weapon(), rpg.Weapon()])

    t = eng.get_agent_stats(bm, tgt); t.base_ac = target_ac; t.hp_max = 200; t.hp_cur = 200
    eng.set_agent_stats(bm, tgt, t)

    _sorcerer(eng, bm, rea, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    r = eng.get_agent_stats(bm, rea); r.hp_max = 30; r.hp_cur = 30
    eng.set_agent_stats(bm, rea, r)

    bm.set_agent_faction(atk, 1); bm.set_agent_faction(rea, 1); bm.set_agent_faction(tgt, 2)
    return atk, tgt, rea


def _rb_miss_reset(eng, bm, atk, tgt, rea):
    """Independent attempt: refill target HP, refill the reactor's use + reaction, impose one-shot
    Disadvantage on the attacker's next roll."""
    t = eng.get_agent_stats(bm, tgt); t.hp_cur = t.hp_max; eng.set_agent_stats(bm, tgt, t)
    s = _sorcerer(eng, bm, rea, 3, prof=2, subclass=rpg.SorcererSubclass.Clockwork)
    s.hp_max = 30; s.hp_cur = 30; eng.set_agent_stats(bm, rea, s)
    rc = eng.get_agent_conditions(bm, rea); rc.reaction_used = False; rc.incapacitated = False
    eng.set_agent_conditions(bm, rea, rc)
    eng.grant_pending_advantage(False)             # next d20 (the attack roll) is made at Disadvantage


def test_restore_balance_miss_gate():
    """can_restore_balance_miss is eligible exactly when the roll was at Disadvantage, MISSED, and the
    primary (first) die was higher than the kept die (so cancelling raises). Hits, no-op cancels, and
    advantaged rolls are all ineligible; so are a non-ally reactor, a drained use, and the wrong subclass."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    atk, tgt, rea = _clock_rb_miss_setup(eng, bm, target_ac=14)

    saw_eligible = False
    captured = None                                 # a known-eligible result, for the negative checks
    for _ in range(600):
        _rb_miss_reset(eng, bm, atk, tgt, rea)
        r = eng.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if not r.disadvantage:
            continue
        expect = (not r.hit) and (r.d20_primary > r.d20)
        assert eng.can_restore_balance_miss(bm, rea, atk, r) == expect, \
            f"gate mismatch: hit={r.hit} d1={r.d20_primary} kept={r.d20}"
        if expect:
            saw_eligible = True
            captured = r
    assert saw_eligible, "expected at least one disadvantaged miss with primary > kept across 600 rolls"

    # An advantaged result is never eligible for the miss (raising) direction.
    eng.grant_pending_advantage(True)
    adv = eng.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert not eng.can_restore_balance_miss(bm, rea, atk, adv), "advantaged roll → miss-direction ineligible"

    # Negatives on the captured eligible result.
    bm.set_agent_faction(rea, 3)                    # reactor no longer the attacker's ally
    assert not eng.can_restore_balance_miss(bm, rea, atk, captured), "non-ally reactor → ineligible"
    bm.set_agent_faction(rea, 1)
    assert eng.can_restore_balance_miss(bm, rea, atk, captured), "restored as an ally → eligible again"

    s = eng.get_agent_stats(bm, rea); s.resources["Restore Balance"].current = 0
    eng.set_agent_stats(bm, rea, s)
    assert not eng.can_restore_balance_miss(bm, rea, atk, captured), "no use → ineligible"

    _sorcerer(eng, bm, rea, 6, prof=3, subclass=rpg.SorcererSubclass.WildMagic)
    bm.set_agent_faction(rea, 1)
    assert not eng.can_restore_balance_miss(bm, rea, atk, captured), "wrong subclass → ineligible"
    print("✅ test_restore_balance_miss_gate passed")


def test_restore_balance_miss_flips_to_hit():
    """Applying the disadvantage-cancel reverts the kept die to the primary die, spends one use + the
    reaction, and (with a low target AC) flips the miss to a hit that deals damage."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    atk, tgt, rea = _clock_rb_miss_setup(eng, bm, target_ac=12)

    saw_flip = False
    for _ in range(600):
        _rb_miss_reset(eng, bm, atk, tgt, rea)
        r = eng.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if not (r.disadvantage and not r.hit and r.d20_primary > r.d20):
            continue
        hp_before = eng.get_agent_stats(bm, tgt).hp_cur
        ok = eng.apply_restore_balance_miss_to_attack(bm, rpg.Attack(atk, tgt, 0), rea, r)
        assert ok, "apply should succeed on an eligible disadvantaged miss"
        assert r.d20 == r.d20_primary and not r.disadvantage, "kept die reverted; disadvantage cleared"
        assert eng.get_agent_conditions(bm, rea).reaction_used, "cancel spends the reaction"
        assert eng.get_agent_stats(bm, rea).resources["Restore Balance"].current == 1, \
            "cancel spends one use (2 → 1)"
        if r.hit:
            saw_flip = True
            assert eng.get_agent_stats(bm, tgt).hp_cur < hp_before, "a flipped-to-hit deals damage"
            break
    assert saw_flip, "expected at least one disadvantaged miss to flip to a hit across 600 rolls"
    print("✅ test_restore_balance_miss_flips_to_hit passed")


# ── Phase 6: Clockwork Soul L14 Trance of Order ──────────────────────────────

def test_trance_of_order_resource_and_gate():
    """Trance of Order: a 1/long-rest free use for L14+ Clockwork; activation sets a 10-round window.
    Pre-L14 and non-Clockwork are gated out (no resource, activation returns False)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))

    # L14 Clockwork: resource present (1 use), activation works and sets a 10-round window.
    s14 = _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Trance of Order" in s14.resources, "L14 Clockwork should have a Trance of Order use"
    assert s14.resources["Trance of Order"].current == 1, "Trance of Order is a single free use"
    assert eng.activate_trance_of_order(bm, idx), "L14 Clockwork should be able to enter the trance"
    s_active = eng.get_agent_stats(bm, idx)
    assert s_active.trance_of_order_turns == 10, \
        f"trance should run 10 rounds, got {s_active.trance_of_order_turns}"
    assert s_active.resources["Trance of Order"].current == 0, "the free use should be spent"

    # L13 Clockwork: no resource, activation gated.
    bm13 = setup_battle_map(); eng13 = setup_combat_engine()
    i13 = add_agent_to_battle(eng13, bm13, create_test_agent("Clock13", 5, 5))
    s13 = _sorcerer(eng13, bm13, i13, 13, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Trance of Order" not in s13.resources, "pre-L14 → no Trance of Order resource"
    assert not eng13.activate_trance_of_order(bm13, i13), "L13 must be gated out"

    # Wrong subclass (Draconic L14): gated.
    bm_d = setup_battle_map(); eng_d = setup_combat_engine()
    i_d = add_agent_to_battle(eng_d, bm_d, create_test_agent("Drac14", 5, 5))
    _sorcerer(eng_d, bm_d, i_d, 14, subclass=rpg.SorcererSubclass.Draconic)
    assert not eng_d.activate_trance_of_order(bm_d, i_d), "non-Clockwork must be gated out"
    print("✅ test_trance_of_order_resource_and_gate passed")


def test_trance_negates_advantage_against_self():
    """While in a trance, attacks against the sorcerer can't benefit from Advantage. A prone target is
    the advantage lever: without the trance the roll is at advantage; with it, advantage is negated."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    atk = add_agent_to_battle(eng, bm, create_test_agent("Atk", 5, 5))
    sorc = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 6, 5))
    eng.set_agent_weapons(bm, atk, [_clock_greataxe(), rpg.Weapon(), rpg.Weapon()])

    _sorcerer(eng, bm, sorc, 14, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, sorc); s.hp_max = 60; s.hp_cur = 60; eng.set_agent_stats(bm, sorc, s)
    # Prone target → attacker rolls with advantage.
    c = eng.get_agent_conditions(bm, sorc); c.prone = True; eng.set_agent_conditions(bm, sorc, c)

    r_no = eng.execute_action(bm, rpg.Attack(atk, sorc, 0))
    assert r_no.advantage, "a prone target without a trance is attacked at advantage"

    # Enter the trance (set the window directly so this is independent of bonus-action state).
    s2 = eng.get_agent_stats(bm, sorc); s2.trance_of_order_turns = 10; eng.set_agent_stats(bm, sorc, s2)
    c2 = eng.get_agent_conditions(bm, sorc); c2.prone = True; eng.set_agent_conditions(bm, sorc, c2)
    r_tr = eng.execute_action(bm, rpg.Attack(atk, sorc, 0))
    assert not r_tr.advantage, "Trance of Order negates Advantage on attacks against the sorcerer"
    print("✅ test_trance_negates_advantage_against_self passed")


def test_trance_floors_own_attack_d20():
    """While in a trance, the sorcerer treats its own d20 of 9-or-lower as a 10 on attack rolls: across
    many attacks the kept die is never below 10 and a floored low roll is never a fumble."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    tgt = add_agent_to_battle(eng, bm, create_test_agent("Tgt", 6, 5), hp=400, ac=12)
    eng.set_agent_weapons(bm, sorc, [_clock_greataxe(), rpg.Weapon(), rpg.Weapon()])
    _sorcerer(eng, bm, sorc, 14, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, sorc); s.trance_of_order_turns = 10; eng.set_agent_stats(bm, sorc, s)

    saw_floor = False
    for _ in range(300):
        r = eng.execute_action(bm, rpg.Attack(sorc, tgt, 0))
        assert r.d20 >= 10, f"trance must floor the kept d20 to ≥10, saw {r.d20}"
        assert not r.fumble, "a floored low roll (≥10) can never be a fumble"
        if r.d20 == 10:
            saw_floor = True
    assert saw_floor, "expected at least one floored (→10) roll across 300 attacks"
    print("✅ test_trance_floors_own_attack_d20 passed")


def test_trance_floors_own_save():
    """While in a trance, the sorcerer floors its own save d20 to 10 — but an automatic failure (a
    paralyzed STR/DEX save) is NOT floored and still fails."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    caster = add_agent_to_battle(eng, bm, create_test_agent("Caster", 5, 5))
    sorc = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 6, 5), hp=400)
    _sorcerer(eng, bm, sorc, 14, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, sorc); s.trance_of_order_turns = 10; eng.set_agent_stats(bm, sorc, s)
    eng.set_agent_spells(bm, caster, [_save_spell("Frostbite", rpg.SaveAbility.Dexterity)])

    def _cast():
        a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [sorc]
        return eng.execute_spell(bm, a).target_results[0].save_d20

    saw_floor = False
    for _ in range(200):
        d = _cast()
        assert d >= 10, f"trance must floor the saver's d20 to ≥10, saw {d}"
        if d == 10:
            saw_floor = True
    assert saw_floor, "expected at least one floored (→10) save across 200 casts"

    # Auto-fail bypasses the floor: a paralyzed creature auto-fails DEX saves at save_d20 == 1.
    pc = eng.get_agent_conditions(bm, sorc); pc.paralyzed = True; pc.incapacitated = True
    eng.set_agent_conditions(bm, sorc, pc)
    a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [sorc]
    tr = eng.execute_spell(bm, a).target_results[0]
    assert tr.save_d20 == 1, f"a paralyzed DEX save auto-fails at 1 (never floored), got {tr.save_d20}"
    assert not tr.saved, "an auto-failed save must still fail under a trance"
    print("✅ test_trance_floors_own_save passed")


def test_trance_duration_ticks():
    """The trance window decrements one round per beginTurn and switches off at 0."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, idx); s.trance_of_order_turns = 2; eng.set_agent_stats(bm, idx, s)

    eng.begin_turn(bm, idx)
    assert eng.get_agent_stats(bm, idx).trance_of_order_turns == 1, "first beginTurn → 1 round left"
    eng.begin_turn(bm, idx)
    assert eng.get_agent_stats(bm, idx).trance_of_order_turns == 0, "second beginTurn → trance ends"
    eng.begin_turn(bm, idx)
    assert eng.get_agent_stats(bm, idx).trance_of_order_turns == 0, "stays off (no underflow)"
    print("✅ test_trance_duration_ticks passed")


def test_trance_5sp_alt_cost():
    """Once the free use is spent, the trance can be re-entered for 5 Sorcery Points; with neither a
    free use nor 5 SP, activation fails."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Clockwork)
    # Free use already spent; SP available (L14 → 14 SP).
    s.resources["Trance of Order"].current = 0
    sp_before = s.resources["Sorcery Points"].current
    assert sp_before >= 5, "a L14 sorcerer has at least 5 Sorcery Points"
    eng.set_agent_stats(bm, idx, s)

    assert eng.activate_trance_of_order(bm, idx), "5 SP should pay for the trance once the free use is gone"
    s2 = eng.get_agent_stats(bm, idx)
    assert s2.resources["Sorcery Points"].current == sp_before - 5, "the alt cost spends exactly 5 SP"
    assert s2.trance_of_order_turns == 10, "the 5-SP trance still runs 10 rounds"

    # Drain SP below 5 with no free use → activation fails.
    s2.resources["Sorcery Points"].current = 4
    s2.trance_of_order_turns = 0
    eng.set_agent_stats(bm, idx, s2)
    assert not eng.activate_trance_of_order(bm, idx), "no free use and <5 SP → cannot enter the trance"
    print("✅ test_trance_5sp_alt_cost passed")


# ── Clockwork Soul L6 Bastion of Law ──────────────────────────────────────────
def test_bastion_of_law_spends_sp_and_gates():
    """Bastion of Law: a L6+ Clockwork Sorcerer spends 1-5 Sorcery Points to ward a target with a
    pre-rolled (sp)d8 pool. Pre-L6 and non-Clockwork are gated out (return -1, no SP spent)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 6, subclass=rpg.SorcererSubclass.Clockwork)
    sp0 = s.resources["Sorcery Points"].current

    ward = eng.activate_bastion_of_law(bm, idx, idx, 3)   # self-ward with 3 SP
    assert ward > 0, "3d8 ward should be a positive total"
    assert 3 <= ward <= 24, f"3d8 ward in [3,24], got {ward}"
    s_after = eng.get_agent_stats(bm, idx)
    assert s_after.bastion_ward == ward, "the rolled ward is stored on the target"
    assert s_after.resources["Sorcery Points"].current == sp0 - 3, "exactly 3 SP spent"

    # Re-warding overwrites the pool (does not stack).
    ward2 = eng.activate_bastion_of_law(bm, idx, idx, 1)
    assert eng.get_agent_stats(bm, idx).bastion_ward == ward2, "a new ward overwrites the old pool"

    # SP clamping: 9 SP requested → clamped to 5 SP spent. Top SP back up so the
    # 5-cap (not an insufficient-SP refusal) is what we're actually exercising.
    s2 = eng.get_agent_stats(bm, idx); s2.resources["Sorcery Points"].current = 10
    eng.set_agent_stats(bm, idx, s2)
    sp_before = 10
    eng.activate_bastion_of_law(bm, idx, idx, 9)
    assert eng.get_agent_stats(bm, idx).resources["Sorcery Points"].current == sp_before - 5, \
        "the request is clamped to a maximum of 5 SP"

    # L5 Clockwork: gated.
    bm5 = setup_battle_map(); eng5 = setup_combat_engine()
    i5 = add_agent_to_battle(eng5, bm5, create_test_agent("Clock5", 5, 5))
    _sorcerer(eng5, bm5, i5, 5, subclass=rpg.SorcererSubclass.Clockwork)
    assert eng5.activate_bastion_of_law(bm5, i5, i5, 2) == -1, "pre-L6 must be gated out"

    # Wrong subclass (Draconic L6): gated.
    bm_d = setup_battle_map(); eng_d = setup_combat_engine()
    i_d = add_agent_to_battle(eng_d, bm_d, create_test_agent("Drac6", 5, 5))
    _sorcerer(eng_d, bm_d, i_d, 6, subclass=rpg.SorcererSubclass.Draconic)
    assert eng_d.activate_bastion_of_law(bm_d, i_d, i_d, 2) == -1, "non-Clockwork must be gated out"
    print("✅ test_bastion_of_law_spends_sp_and_gates passed")


def test_bastion_of_law_absorbs_damage():
    """The ward soaks damage before HP: damage_agent (and therefore every site that routes through it)
    decrements the ward first, only the overflow reduces hp_cur, and the ward never goes negative."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("Warded", 5, 5))
    _sorcerer(eng, bm, idx, 6, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, idx)
    s.hp_max = 50; s.hp_cur = 50; s.bastion_ward = 10
    eng.set_agent_stats(bm, idx, s)

    # 7 damage: fully soaked by the ward (10 → 3), hp_cur unchanged.
    hp = eng.damage_agent(bm, idx, 7)
    assert hp == 50, f"ward should absorb all 7 damage, hp stays 50, got {hp}"
    assert eng.get_agent_stats(bm, idx).bastion_ward == 3, "ward decremented 10 → 3"

    # 8 damage: 3 soaked by the remaining ward, 5 overflow to hp_cur (50 → 45), ward → 0.
    hp = eng.damage_agent(bm, idx, 8)
    assert hp == 45, f"3 soaked, 5 to hp → 45, got {hp}"
    assert eng.get_agent_stats(bm, idx).bastion_ward == 0, "ward fully spent → 0 (no underflow)"

    # With no ward left, damage falls straight through.
    hp = eng.damage_agent(bm, idx, 5)
    assert hp == 40, f"no ward → 5 damage hits hp (45 → 40), got {hp}"
    print("✅ test_bastion_of_law_absorbs_damage passed")


def test_bastion_of_law_absorbs_spell_damage():
    """The ward also soaks spell damage (the Save branch). A paralyzed (auto-fail) target takes full
    spell damage, which a large ward fully absorbs, leaving hp_cur untouched and the ward reduced."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    caster = add_agent_to_battle(eng, bm, create_test_agent("Caster", 5, 5))
    sorc = add_agent_to_battle(eng, bm, create_test_agent("Warded", 6, 5))
    _sorcerer(eng, bm, sorc, 6, subclass=rpg.SorcererSubclass.Clockwork)
    s = eng.get_agent_stats(bm, sorc)
    s.hp_max = 80; s.hp_cur = 80; s.bastion_ward = 200
    eng.set_agent_stats(bm, sorc, s)
    eng.set_agent_spells(bm, caster, [_save_spell("Frostbite", rpg.SaveAbility.Dexterity)])

    # Paralyzed → auto-fails the DEX save → takes full damage, which the 200-point ward absorbs.
    pc = eng.get_agent_conditions(bm, sorc); pc.paralyzed = True; pc.incapacitated = True
    eng.set_agent_conditions(bm, sorc, pc)
    a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [sorc]
    eng.execute_spell(bm, a)

    s_after = eng.get_agent_stats(bm, sorc)
    assert s_after.hp_cur == 80, "a 200-point ward fully absorbs the cantrip; hp_cur untouched"
    assert s_after.bastion_ward < 200, "the ward soaked the spell damage and was reduced"
    print("✅ test_bastion_of_law_absorbs_spell_damage passed")


def test_bastion_of_law_range_gate_and_long_rest():
    """Warding an ally beyond 30 ft fails without spending SP; a long rest clears any standing ward."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    far  = add_agent_to_battle(eng, bm, create_test_agent("FarAlly", 20, 5))  # 15 cells = 75 ft
    bm.set_agent_faction(sorc, 1); bm.set_agent_faction(far, 1)
    s = _sorcerer(eng, bm, sorc, 6, subclass=rpg.SorcererSubclass.Clockwork)
    sp0 = s.resources["Sorcery Points"].current

    assert eng.activate_bastion_of_law(bm, sorc, far, 2) == -1, "target beyond 30 ft must fail"
    assert eng.get_agent_stats(bm, sorc).resources["Sorcery Points"].current == sp0, \
        "a range failure spends no Sorcery Points"

    # Stand up a ward, then a long rest clears it.
    eng.activate_bastion_of_law(bm, sorc, sorc, 3)
    assert eng.get_agent_stats(bm, sorc).bastion_ward > 0, "ward is up"
    eng.apply_long_rest(bm)
    assert eng.get_agent_stats(bm, sorc).bastion_ward == 0, "a long rest clears the ward"
    print("✅ test_bastion_of_law_range_gate_and_long_rest passed")


# ── Clockwork Soul L18 Clockwork Cavalcade ────────────────────────────────────
def test_clockwork_cavalcade_resource_and_gate():
    """Clockwork Cavalcade: a 1/long-rest free use for L18+ Clockwork. L17 and non-Clockwork gated."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    s18 = _sorcerer(eng, bm, idx, 18, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Clockwork Cavalcade" in s18.resources, "L18 Clockwork should have a Cavalcade use"
    assert s18.resources["Clockwork Cavalcade"].current == 1, "Cavalcade is a single free use"

    # L17 Clockwork: no resource, activation gated.
    bm17 = setup_battle_map(); eng17 = setup_combat_engine()
    i17 = add_agent_to_battle(eng17, bm17, create_test_agent("Clock17", 5, 5))
    s17 = _sorcerer(eng17, bm17, i17, 17, subclass=rpg.SorcererSubclass.Clockwork)
    assert "Clockwork Cavalcade" not in s17.resources, "pre-L18 → no Cavalcade resource"
    assert eng17.clockwork_cavalcade(bm17, i17) == -1, "L17 must be gated out"

    # Wrong subclass (Wild Magic L18): gated.
    bm_w = setup_battle_map(); eng_w = setup_combat_engine()
    i_w = add_agent_to_battle(eng_w, bm_w, create_test_agent("Wild18", 5, 5))
    _sorcerer(eng_w, bm_w, i_w, 18, subclass=rpg.SorcererSubclass.WildMagic)
    assert eng_w.clockwork_cavalcade(bm_w, i_w) == -1, "non-Clockwork must be gated out"
    print("✅ test_clockwork_cavalcade_resource_and_gate passed")


def test_clockwork_cavalcade_heals_and_cleanses():
    """Cavalcade heals the caster + each ally within 30 ft by 100 HP (capped at max) and ends their
    active spell conditions; an ally beyond 30 ft is untouched. Spends the free use."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    ally = add_agent_to_battle(eng, bm, create_test_agent("Ally", 6, 5))   # 1 cell = 5 ft
    far  = add_agent_to_battle(eng, bm, create_test_agent("FarAlly", 20, 5))  # 75 ft
    for a in (sorc, ally, far):
        bm.set_agent_faction(a, 1)
    _sorcerer(eng, bm, sorc, 18, subclass=rpg.SorcererSubclass.Clockwork)
    # Wound the caster and allies; give the ally a Paralyzed condition to be cleansed.
    for a in (sorc, ally, far):
        st = eng.get_agent_stats(bm, a); st.hp_max = 200; st.hp_cur = 10
        eng.set_agent_stats(bm, a, st)
    pc = rpg.ActiveAgentCondition()
    pc.agent_idx = ally; pc.caster_idx = sorc; pc.condition_name = "Paralyzed"; pc.turns_remaining = 10
    eng.add_agent_condition(bm, pc)
    assert eng.get_agent_conditions(bm, ally).paralyzed, "precondition: ally is paralyzed"

    affected = eng.clockwork_cavalcade(bm, sorc)
    assert affected == 2, f"caster + 1 nearby ally affected (far ally excluded), got {affected}"
    assert eng.get_agent_stats(bm, sorc).hp_cur == 110, "caster regains 100 HP (10 → 110)"
    assert eng.get_agent_stats(bm, ally).hp_cur == 110, "nearby ally regains 100 HP"
    assert not eng.get_agent_conditions(bm, ally).paralyzed, "Cavalcade ends the ally's Paralyzed"
    assert eng.get_agent_stats(bm, far).hp_cur == 10, "an ally beyond 30 ft is untouched"
    assert eng.get_agent_stats(bm, sorc).resources["Clockwork Cavalcade"].current == 0, \
        "the free use is spent"
    print("✅ test_clockwork_cavalcade_heals_and_cleanses passed")


def test_clockwork_cavalcade_7sp_alt_cost():
    """Once the free use is spent, Cavalcade can be used again for 7 Sorcery Points; with neither a
    free use nor 7 SP, it fails."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("ClockSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 18, subclass=rpg.SorcererSubclass.Clockwork)
    s.resources["Clockwork Cavalcade"].current = 0   # free use spent
    sp_before = s.resources["Sorcery Points"].current
    assert sp_before >= 7, "a L18 sorcerer has at least 7 Sorcery Points"
    eng.set_agent_stats(bm, idx, s)

    assert eng.clockwork_cavalcade(bm, idx) >= 0, "7 SP pays for Cavalcade once the free use is gone"
    s2 = eng.get_agent_stats(bm, idx)
    assert s2.resources["Sorcery Points"].current == sp_before - 7, "the alt cost spends exactly 7 SP"

    # Drain SP below 7 with no free use → fails.
    s2.resources["Sorcery Points"].current = 6
    eng.set_agent_stats(bm, idx, s2)
    assert eng.clockwork_cavalcade(bm, idx) == -1, "no free use and <7 SP → cannot use Cavalcade"
    print("✅ test_clockwork_cavalcade_7sp_alt_cost passed")


# ── Aberrant Mind L14 Revelation in Flesh + L18 Warping Implosion ─────────────

def test_revelation_in_flesh_activate_and_gate():
    """Revelation in Flesh: a L14+ Aberrant spends 1 SP to gain fly (=walk) + hover, swim (=walk), and
    truesight 60 ft for 100 rounds. Pre-L14, wrong subclass, no SP, and an already-active state all fail."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Aberrant)
    walk = s.speed_walk
    sp_before = s.resources["Sorcery Points"].current

    assert eng.activate_revelation_in_flesh(bm, idx), "L14 Aberrant should transform"
    a = eng.get_agent_stats(bm, idx)
    assert a.revelation_in_flesh_turns == 100, f"10 minutes = 100 rounds, got {a.revelation_in_flesh_turns}"
    assert a.speed_fly == walk and a.speed_swim == walk, "fly and swim equal the walking speed"
    assert a.truesight_range >= 60, "gains truesight 60 ft (see Invisible)"
    assert a.resources["Sorcery Points"].current == sp_before - 1, "spends exactly 1 Sorcery Point"

    # Already active → second activation fails (no extra SP spent).
    assert not eng.activate_revelation_in_flesh(bm, idx), "already active → cannot re-activate"
    assert eng.get_agent_stats(bm, idx).resources["Sorcery Points"].current == sp_before - 1

    # Pre-L14 gate.
    bm2 = setup_battle_map(); eng2 = setup_combat_engine()
    i2 = add_agent_to_battle(eng2, bm2, create_test_agent("AberSorc13", 5, 5))
    _sorcerer(eng2, bm2, i2, 13, subclass=rpg.SorcererSubclass.Aberrant)
    assert not eng2.activate_revelation_in_flesh(bm2, i2), "pre-L14 → ineligible"

    # Wrong subclass gate.
    i3 = add_agent_to_battle(eng2, bm2, create_test_agent("DracSorc14", 8, 8))
    _sorcerer(eng2, bm2, i3, 14, subclass=rpg.SorcererSubclass.Draconic)
    assert not eng2.activate_revelation_in_flesh(bm2, i3), "non-Aberrant → ineligible"

    # No Sorcery Points gate.
    s4 = eng.get_agent_stats(bm, idx); s4.revelation_in_flesh_turns = 0
    s4.resources["Sorcery Points"].current = 0
    eng.set_agent_stats(bm, idx, s4)
    assert not eng.activate_revelation_in_flesh(bm, idx), "no Sorcery Point → ineligible"
    print("✅ test_revelation_in_flesh_activate_and_gate passed")


def test_revelation_in_flesh_expiry_reverts():
    """When the window ticks to 0 in begin_turn, the granted fly/swim/truesight revert to the values
    snapshotted at activation."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    _sorcerer(eng, bm, idx, 14, subclass=rpg.SorcererSubclass.Aberrant)
    assert eng.activate_revelation_in_flesh(bm, idx)

    s = eng.get_agent_stats(bm, idx)
    assert s.speed_fly > 0 and s.truesight_range >= 60
    s.revelation_in_flesh_turns = 1                 # fast-forward to the last round
    eng.set_agent_stats(bm, idx, s)

    eng.begin_turn(bm, idx)
    s2 = eng.get_agent_stats(bm, idx)
    assert s2.revelation_in_flesh_turns == 0, "window ends"
    assert s2.speed_fly == 0, "fly speed reverts to the prior (0)"
    assert s2.speed_swim == 0, "swim speed reverts to the prior (0)"
    assert s2.truesight_range == 0, "truesight reverts to the prior (0)"
    print("✅ test_revelation_in_flesh_expiry_reverts passed")


def test_warping_implosion_resource_and_gate():
    """Warping Implosion: a 1/long-rest free use for L18+ Aberrant; absent for L17 / wrong subclass, and
    the engine call is gated the same way."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    s = _sorcerer(eng, bm, idx, 18, subclass=rpg.SorcererSubclass.Aberrant)
    assert "Warping Implosion" in s.resources and s.resources["Warping Implosion"].current == 1

    s17 = _sorcerer(eng, bm, idx, 17, subclass=rpg.SorcererSubclass.Aberrant)
    assert "Warping Implosion" not in s17.resources, "pre-L18 → no Warping Implosion"
    assert eng.warping_implosion(bm, idx, 6, 5) == -1, "pre-L18 → gated out"

    _sorcerer(eng, bm, idx, 18, subclass=rpg.SorcererSubclass.Draconic)
    assert eng.warping_implosion(bm, idx, 6, 5) == -1, "wrong subclass → gated out"
    print("✅ test_warping_implosion_resource_and_gate passed")


def test_warping_implosion_teleports_and_damages():
    """Warping Implosion teleports the caster up to 120 ft, then every other creature within 30 ft of
    the space it LEFT takes 3d10 Force (half on a DEX save). Creatures beyond 30 ft are untouched, and
    the free use is spent (then 5 SP for a second use)."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    near = add_agent_to_battle(eng, bm, create_test_agent("Near", 6, 5))    # 5 ft from origin
    far  = add_agent_to_battle(eng, bm, create_test_agent("Far", 20, 5))    # 75 ft from origin
    _sorcerer(eng, bm, sorc, 18, cha=18, prof=6, subclass=rpg.SorcererSubclass.Aberrant)
    for a in (near, far):
        t = eng.get_agent_stats(bm, a); t.hp_max = 200; t.hp_cur = 200; t.dex = 8
        eng.set_agent_stats(bm, a, t)
    bm.set_agent_faction(sorc, 1); bm.set_agent_faction(near, 2); bm.set_agent_faction(far, 2)

    affected = eng.warping_implosion(bm, sorc, 10, 5)   # teleport 25 ft to (10,5)
    assert affected == 1, f"only the creature within 30 ft of the origin is caught, got {affected}"
    moved = bm.placed_agents[sorc].origin
    assert (moved.col, moved.row) == (10, 5), "the caster teleported to the destination"
    assert eng.get_agent_stats(bm, near).hp_cur < 200, "the nearby creature takes Force damage"
    assert eng.get_agent_stats(bm, far).hp_cur == 200, "a creature beyond 30 ft is untouched"
    assert eng.get_agent_stats(bm, sorc).resources["Warping Implosion"].current == 0, "the free use is spent"

    # Second use costs 5 Sorcery Points (origin is now (10,5); use col 8 which is in bounds
    # and unoccupied — near is at (6,5), sorc is at (10,5), so (8,5) is free).
    s2 = eng.get_agent_stats(bm, sorc)
    sp_before = s2.resources["Sorcery Points"].current
    assert sp_before >= 5
    res = eng.warping_implosion(bm, sorc, 8, 5)
    assert res >= 0, "5 SP pays for a second Warping Implosion"
    assert eng.get_agent_stats(bm, sorc).resources["Sorcery Points"].current == sp_before - 5, \
        "the alt cost spends exactly 5 Sorcery Points"
    print("✅ test_warping_implosion_teleports_and_damages passed")


# ── Sonnet Task A: Draconic L6 Elemental Affinity — Resistance (bonus action) ──

def test_draconic_resistance_spends_sp_and_gates():
    """activate_draconic_resistance: spends 1 SP, sets 0.5× multiplier for chosen type,
    marks 600 rounds remaining. Various eligibility gates must return False."""
    fire_idx = int(rpg.MagicDamage.Fire)

    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("DracSorc", 5, 5))
    _sorcerer(eng, bm, sorc, 6, subclass=rpg.SorcererSubclass.Draconic)
    s = eng.get_agent_stats(bm, sorc)
    s.draconic_affinity_type = fire_idx
    eng.set_agent_stats(bm, sorc, s)
    sp0 = eng.get_agent_stats(bm, sorc).resources["Sorcery Points"].current

    ok = eng.activate_draconic_resistance(bm, sorc)
    assert ok, "Draconic L6 with affinity_type set and SP available must succeed"
    s2 = eng.get_agent_stats(bm, sorc)
    assert s2.draconic_affinity_resist_turns == 600, "600 rounds (1 hour) remaining"
    assert s2.resources["Sorcery Points"].current == sp0 - 1, "exactly 1 SP spent"
    assert abs(s2.get_magic_damage_multiplier(fire_idx) - 0.5) < 1e-6, "Fire resistance granted"

    # Already active: no double-spend.
    sp_mid = s2.resources["Sorcery Points"].current
    ok2 = eng.activate_draconic_resistance(bm, sorc)
    assert not ok2, "must not activate while resistance is already running"
    assert eng.get_agent_stats(bm, sorc).resources["Sorcery Points"].current == sp_mid, "no SP spent"

    # Level gate: L5 Draconic must fail.
    bm5 = setup_battle_map(); eng5 = setup_combat_engine()
    sorc5 = add_agent_to_battle(eng5, bm5, create_test_agent("Drac5", 5, 5))
    _sorcerer(eng5, bm5, sorc5, 5, subclass=rpg.SorcererSubclass.Draconic)
    s5 = eng5.get_agent_stats(bm5, sorc5); s5.draconic_affinity_type = fire_idx
    eng5.set_agent_stats(bm5, sorc5, s5)
    assert not eng5.activate_draconic_resistance(bm5, sorc5), "L5 must be gated"

    # Wrong subclass (WildMagic): gated.
    bm_w = setup_battle_map(); eng_w = setup_combat_engine()
    sorc_w = add_agent_to_battle(eng_w, bm_w, create_test_agent("Wild6", 5, 5))
    _sorcerer(eng_w, bm_w, sorc_w, 6, subclass=rpg.SorcererSubclass.WildMagic)
    sw = eng_w.get_agent_stats(bm_w, sorc_w); sw.draconic_affinity_type = fire_idx
    eng_w.set_agent_stats(bm_w, sorc_w, sw)
    assert not eng_w.activate_draconic_resistance(bm_w, sorc_w), "wrong subclass must be gated"

    # Affinity type not set (-1): gated.
    bm_n = setup_battle_map(); eng_n = setup_combat_engine()
    sorc_n = add_agent_to_battle(eng_n, bm_n, create_test_agent("DracNoType", 5, 5))
    _sorcerer(eng_n, bm_n, sorc_n, 6, subclass=rpg.SorcererSubclass.Draconic)
    assert not eng_n.activate_draconic_resistance(bm_n, sorc_n), "affinity_type=-1 must be gated"

    # Insufficient SP: gated.
    bm_sp = setup_battle_map(); eng_sp = setup_combat_engine()
    sorc_sp = add_agent_to_battle(eng_sp, bm_sp, create_test_agent("DracNoSP", 5, 5))
    _sorcerer(eng_sp, bm_sp, sorc_sp, 6, subclass=rpg.SorcererSubclass.Draconic)
    ssp = eng_sp.get_agent_stats(bm_sp, sorc_sp)
    ssp.draconic_affinity_type = fire_idx
    ssp.resources["Sorcery Points"].current = 0
    eng_sp.set_agent_stats(bm_sp, sorc_sp, ssp)
    assert not eng_sp.activate_draconic_resistance(bm_sp, sorc_sp), "0 SP must be gated"
    print("✅ test_draconic_resistance_spends_sp_and_gates passed")


def test_draconic_resistance_duration_ticks():
    """begin_turn decrements draconic_affinity_resist_turns; on expiry multiplier reverts to 1.0."""
    fire_idx = int(rpg.MagicDamage.Fire)

    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("DracSorc", 5, 5))
    _sorcerer(eng, bm, sorc, 6, subclass=rpg.SorcererSubclass.Draconic)
    # Manually prime the resistance state (skip activating via button so we can set a small timer).
    s = eng.get_agent_stats(bm, sorc)
    s.draconic_affinity_type = fire_idx
    s.draconic_affinity_resist_turns = 2
    t = fire_idx
    s.set_magic_damage_multiplier(t, 0.5)
    eng.set_agent_stats(bm, sorc, s)

    # First begin_turn: turns → 1, resistance still active.
    eng.begin_turn(bm, sorc)
    s1 = eng.get_agent_stats(bm, sorc)
    assert s1.draconic_affinity_resist_turns == 1, f"expected 1, got {s1.draconic_affinity_resist_turns}"
    assert abs(s1.get_magic_damage_multiplier(fire_idx) - 0.5) < 1e-6, "resistance still active"

    # Second begin_turn: turns → 0, multiplier reverts to 1.0.
    eng.begin_turn(bm, sorc)
    s2 = eng.get_agent_stats(bm, sorc)
    assert s2.draconic_affinity_resist_turns == 0, "timer must reach 0"
    assert abs(s2.get_magic_damage_multiplier(fire_idx) - 1.0) < 1e-6, "multiplier must revert to 1.0 on expiry"
    print("✅ test_draconic_resistance_duration_ticks passed")


# ── Sonnet Task B: Aberrant Mind L3+ Psionic Sorcery (SP → free cast) ──────────

def test_psionic_sorcery_spends_sp_not_slot():
    """spend_sorcery_points_for_spell: deducts SP equal to spell_level, leaves slots untouched."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    _sorcerer(eng, bm, sorc, 5, subclass=rpg.SorcererSubclass.Aberrant)
    s = eng.get_agent_stats(bm, sorc)
    sp0 = s.resources["Sorcery Points"].current
    slots_before = list(s.spell_slots_remaining)

    ok = eng.spend_sorcery_points_for_spell(bm, sorc, 2)
    assert ok, "L5 Aberrant with SP must succeed for a L2 psionic spell"
    s2 = eng.get_agent_stats(bm, sorc)
    assert s2.resources["Sorcery Points"].current == sp0 - 2, "exactly 2 SP spent"
    assert list(s2.spell_slots_remaining) == slots_before, "no spell slot consumed"
    print("✅ test_psionic_sorcery_spends_sp_not_slot passed")


def test_psionic_sorcery_gating():
    """spend_sorcery_points_for_spell: gated on Aberrant subclass, Sorcerer class, and L3+."""
    # Wrong subclass (Draconic L6): gated.
    bm_d = setup_battle_map(); eng_d = setup_combat_engine()
    sorc_d = add_agent_to_battle(eng_d, bm_d, create_test_agent("Drac6", 5, 5))
    _sorcerer(eng_d, bm_d, sorc_d, 6, subclass=rpg.SorcererSubclass.Draconic)
    assert not eng_d.spend_sorcery_points_for_spell(bm_d, sorc_d, 1), "non-Aberrant gated"

    # Level gate: L2 Aberrant.
    bm2 = setup_battle_map(); eng2 = setup_combat_engine()
    sorc2 = add_agent_to_battle(eng2, bm2, create_test_agent("Aber2", 5, 5))
    _sorcerer(eng2, bm2, sorc2, 2, subclass=rpg.SorcererSubclass.Aberrant)
    assert not eng2.spend_sorcery_points_for_spell(bm2, sorc2, 1), "L2 Aberrant gated"

    # spell_level == 0: gated (cantrips have no slot level).
    bm3 = setup_battle_map(); eng3 = setup_combat_engine()
    sorc3 = add_agent_to_battle(eng3, bm3, create_test_agent("Aber5", 5, 5))
    _sorcerer(eng3, bm3, sorc3, 5, subclass=rpg.SorcererSubclass.Aberrant)
    assert not eng3.spend_sorcery_points_for_spell(bm3, sorc3, 0), "spell_level=0 gated"
    print("✅ test_psionic_sorcery_gating passed")


def test_psionic_sorcery_insufficient_sp():
    """spend_sorcery_points_for_spell returns False when SP < spell_level; SP unchanged."""
    bm = setup_battle_map(); eng = setup_combat_engine()
    sorc = add_agent_to_battle(eng, bm, create_test_agent("AberSorc", 5, 5))
    _sorcerer(eng, bm, sorc, 3, subclass=rpg.SorcererSubclass.Aberrant)
    s = eng.get_agent_stats(bm, sorc)
    s.resources["Sorcery Points"].current = 2
    eng.set_agent_stats(bm, sorc, s)

    ok = eng.spend_sorcery_points_for_spell(bm, sorc, 3)  # need 3 SP, have 2
    assert not ok, "insufficient SP must return False"
    assert eng.get_agent_stats(bm, sorc).resources["Sorcery Points"].current == 2, "SP must not change"
    print("✅ test_psionic_sorcery_insufficient_sp passed")


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
    test_metamagic_empowered_spends_sp()
    test_metamagic_empowered_no_damage_spell_not_applied()
    test_metamagic_empowered_rerolls_low_dice()
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
    test_metamagic_careful_shields_caster()
    # Metamagic Phase 3: Twinned Spell (engine grants a real extra target)
    test_twinned_num_targets_helper()
    test_twinned_single_target_hits_two()
    test_twinned_gating()
    # Metamagic Phase 4: Sorcery Incarnate (L7) — two options on one cast
    test_sorcery_incarnate_predicate()
    test_sorcery_incarnate_two_options()
    test_sorcery_incarnate_gates_second_option()
    test_metamagic_seeking_stacks_without_incarnate()
    test_metamagic_duplicate_option_charged_once()
    test_innate_sorcery_sp_fallback_at_l7()
    # Phase 1: learned-options picker round-trip + known-count cap
    test_metamagic_learn_roundtrip()
    test_metamagic_known_count_cap()
    # Phase 2: sidebar arm-toggle gate predicate
    test_metamagic_offered_gate()
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
    # Phase 4: Wild Magic Surge trigger + Tides of Chaos
    test_tides_of_chaos_resource_granted()
    test_tides_of_chaos_grants_advantage()
    test_tides_of_chaos_gating()
    test_surge_forced_and_recharges_tides()
    test_surge_unforced_tides_invariant()
    test_maybe_surge_gating()
    test_tides_of_chaos_long_rest_restore()
    # Wild Magic: Controlled Chaos (L14) + Tamed Surge (L18)
    test_controlled_chaos_rolls_two_bands()
    test_tamed_surge_can_choose_any()
    test_resolve_wild_magic_surge_applies_chosen_band()
    test_offer_surge_gating()
    # Clockwork Soul: Clockwork Spells (data) + Restore Balance (OnD20Seen reaction)
    test_clockwork_spells_data()
    test_restore_balance_resource_granted()
    test_restore_balance_long_rest_restore()
    test_restore_balance_gate()
    test_restore_balance_cancels_advantage_can_miss()
    # Restore Balance — disadvantage-cancel (OnMiss raising) direction
    test_restore_balance_miss_gate()
    test_restore_balance_miss_flips_to_hit()
    # Phase 6: Clockwork Soul L14 Trance of Order
    test_trance_of_order_resource_and_gate()
    test_trance_negates_advantage_against_self()
    test_trance_floors_own_attack_d20()
    test_trance_floors_own_save()
    test_trance_duration_ticks()
    test_trance_5sp_alt_cost()
    # Clockwork Soul L6 Bastion of Law + L18 Clockwork Cavalcade
    test_bastion_of_law_spends_sp_and_gates()
    test_bastion_of_law_absorbs_damage()
    test_bastion_of_law_absorbs_spell_damage()
    test_bastion_of_law_range_gate_and_long_rest()
    test_clockwork_cavalcade_resource_and_gate()
    test_clockwork_cavalcade_heals_and_cleanses()
    test_clockwork_cavalcade_7sp_alt_cost()
    # Aberrant Mind L14 Revelation in Flesh + L18 Warping Implosion
    test_revelation_in_flesh_activate_and_gate()
    test_revelation_in_flesh_expiry_reverts()
    test_warping_implosion_resource_and_gate()
    test_warping_implosion_teleports_and_damages()
    # Sonnet Task A: Draconic L6 Elemental Affinity — Resistance (bonus action, 1 SP)
    test_draconic_resistance_spends_sp_and_gates()
    test_draconic_resistance_duration_ticks()
    # Sonnet Task B: Aberrant Mind L3+ Psionic Sorcery (SP → free-cast psionic spells)
    test_psionic_sorcery_spends_sp_not_slot()
    test_psionic_sorcery_gating()
    test_psionic_sorcery_insufficient_sp()
    print("\n✅ All Sorcerer tests passed!")
