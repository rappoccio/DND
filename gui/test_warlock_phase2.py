#!/usr/bin/env python3
"""
Test Warlock Phase 2: Patron Combat Features
Tasks A–F: Dark One's Blessing, Fiendish Resilience, Healing Light,
Radiant Soul, Celestial Resilience, Thought Shield.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _warlock_stats(level, subclass=None):
    """Create a Warlock with optional subclass."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    if subclass is not None:
        s.warlock_subclass = subclass
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# TASK A: Dark One's Blessing (Fiend L3) — temp HP on kill
# ─────────────────────────────────────────────────────────────────────────────

def test_dark_ones_blessing_weapon():
    """Fiend Warlock L3 kills with a weapon → gains temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Fiend Warlock L3 with CHA 16 (mod +3)
    fiend_stats = _warlock_stats(3, rpg.WarlockSubclass.Fiend)
    fiend_stats.cha = 16
    fiend_stats.str = 14
    fiend_idx = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    engine.set_agent_stats(bm, fiend_idx, fiend_stats)

    # Create dummy target with 1 HP at (6, 5)
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    dummy_stats = engine.get_agent_stats(bm, dummy_idx)
    dummy_stats.hp_cur = 1
    dummy_stats.hp_max = 1
    engine.set_agent_stats(bm, dummy_idx, dummy_stats)

    # Fiend attacks with first weapon (should be melee dagger)
    atk = rpg.Attack()
    atk.attacker_idx = fiend_idx
    atk.target_idx = dummy_idx
    atk.weapon_idx = 0
    result = engine.execute_action(bm, atk)

    # Check: attacker killed target
    assert result.target_down, "attack should have killed the dummy"

    # Check: attacker gained temp HP = 3 (CHA mod) + 3 (level) = 6
    fiend_after = engine.get_agent_stats(bm, fiend_idx)
    expected_temp_hp = 6
    assert fiend_after.temp_hp == expected_temp_hp, \
        f"Fiend should have {expected_temp_hp} temp HP from Dark One's Blessing, got {fiend_after.temp_hp}"
    print("✅ test_dark_ones_blessing_weapon passed")


def test_dark_ones_blessing_spell():
    """Fiend Warlock L3 kills with a spell (Eldritch Blast) → gains temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Fiend Warlock L3 with CHA 16 (mod +3)
    fiend_stats = _warlock_stats(3, rpg.WarlockSubclass.Fiend)
    fiend_stats.cha = 16
    fiend_idx = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    engine.set_agent_stats(bm, fiend_idx, fiend_stats)

    # Create dummy target with 5 HP at (6, 5)
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    dummy_stats = engine.get_agent_stats(bm, dummy_idx)
    dummy_stats.hp_cur = 5
    dummy_stats.hp_max = 5
    engine.set_agent_stats(bm, dummy_idx, dummy_stats)

    # Cast Eldritch Blast (spell 0, assuming it's available)
    spell_action = rpg.SpellAction()
    spell_action.caster_idx = fiend_idx
    spell_action.spell_idx = 0
    spell_action.target_indices = [dummy_idx]
    result = engine.execute_spell(bm, spell_action)

    # If the spell killed the target
    if result.valid and any(tr.target_down for tr in result.target_results):
        fiend_after = engine.get_agent_stats(bm, fiend_idx)
        assert fiend_after.temp_hp >= 6, \
            f"Fiend should have temp HP from Dark One's Blessing (spell), got {fiend_after.temp_hp}"
    print("✅ test_dark_ones_blessing_spell passed (or spell didn't kill)")


# ─────────────────────────────────────────────────────────────────────────────
# TASK B: Fiendish Resilience (Fiend L10) — chosen damage resistance
# ─────────────────────────────────────────────────────────────────────────────

def test_fiendish_resilience():
    """Fiend Warlock L10 with Fiendish Resilience type 5 (Necrotic) → 0.5x Necrotic damage."""
    s = _warlock_stats(10, rpg.WarlockSubclass.Fiend)
    s.fiendish_resilience_type = 5  # Necrotic
    s.initialize_class_resources(rpg.CharacterClass.Warlock, 10)

    # Check: Necrotic damage multiplier is 0.5
    mult = s.get_magic_damage_multiplier(5)
    assert mult == 0.5, f"Expected Necrotic (5) multiplier 0.5, got {mult}"

    # Check: other damage types are still 1.0
    assert s.get_magic_damage_multiplier(2) == 1.0, "Fire should still be 1.0"
    assert s.get_magic_damage_multiplier(8) == 1.0, "Radiant should still be 1.0"
    print("✅ test_fiendish_resilience passed")


# ─────────────────────────────────────────────────────────────────────────────
# TASK C: Healing Light (Celestial L3) — d6 heal pool
# ─────────────────────────────────────────────────────────────────────────────

def test_healing_light_resource():
    """Celestial Warlock L5 has Healing Light resource with max = 1 + level."""
    s = _warlock_stats(5, rpg.WarlockSubclass.Celestial)
    hl = s.getResource("Healing Light")
    assert hl is not None, "Celestial Warlock should have Healing Light resource"
    assert hl.max == 6, f"L5 Celestial should have max=1+5=6, got {hl.max}"
    assert hl.current == 6, f"Healing Light should start at max, got {hl.current}"
    print("✅ test_healing_light_resource passed")


def test_healing_light_usage():
    """Celestial Warlock L5 uses Healing Light: spends dice, rolls, heals target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Celestial Warlock L5 with CHA 16 (mod +3)
    celestial_stats = _warlock_stats(5, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 16
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Create dummy target at (6, 5) with 10/20 HP
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    dummy_stats = engine.get_agent_stats(bm, dummy_idx)
    dummy_stats.hp_cur = 10
    dummy_stats.hp_max = 20
    engine.set_agent_stats(bm, dummy_idx, dummy_stats)

    # Use Healing Light: 3 dice (default CHA mod for L5)
    healed = engine.use_healing_light(bm, celestial_idx, dummy_idx, 3)

    # Check: healed > 0 and <= 18 (3d6 max)
    assert healed > 0, f"Healing Light should heal some HP, got {healed}"
    assert healed <= 18, f"3d6 should heal at most 18 HP, got {healed}"

    # Check: resource was spent
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    hl_after = celestial_after.getResource("Healing Light")
    assert hl_after.current == 3, f"Healing Light should have 3 remaining, got {hl_after.current}"

    # Check: target HP increased
    dummy_after = engine.get_agent_stats(bm, dummy_idx)
    expected_hp = min(20, 10 + healed)
    assert dummy_after.hp_cur == expected_hp, \
        f"Target should have {expected_hp} HP, got {dummy_after.hp_cur}"
    print("✅ test_healing_light_usage passed")


def test_healing_light_clamped():
    """Healing Light num_dice is clamped to min(num_dice, current, CHA mod)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Celestial Warlock L3 with CHA 14 (mod +2)
    celestial_stats = _warlock_stats(3, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 14
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))

    # Try to use 10 dice, but capped to min(10, 4 current, 2 CHA mod) = 2
    healed = engine.use_healing_light(bm, celestial_idx, dummy_idx, 10)

    # Check: resource was spent only 2
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    hl_after = celestial_after.getResource("Healing Light")
    assert hl_after.current == 2, f"Should have spent only 2 dice (CHA mod cap), got {4 - hl_after.current} spent"
    print("✅ test_healing_light_clamped passed")


# ─────────────────────────────────────────────────────────────────────────────
# TASK D: Radiant Soul (Celestial L6) — Radiant resistance + once/turn +CHA damage
# ─────────────────────────────────────────────────────────────────────────────

def test_radiant_soul_resistance():
    """Celestial Warlock L6+ has Radiant resistance."""
    s = _warlock_stats(6, rpg.WarlockSubclass.Celestial)
    radiant_mult = s.get_magic_damage_multiplier(8)  # 8 = Radiant
    assert radiant_mult == 0.5, f"Celestial L6 should have Radiant resistance 0.5, got {radiant_mult}"
    print("✅ test_radiant_soul_resistance passed")


def _make_radiant_automatic_spell(base_damage):
    """An Automatic (no-roll) Radiant spell dealing exactly base_damage (die_size=1 → always 1)."""
    spell = rpg.Spell()
    spell.name = "Radiant Test Bolt"
    spell.level = 1
    spell.attack_type = rpg.SpellAttack.Automatic
    spell.geometry = rpg.SpellGeometry.Multiple
    spell.range = 60
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Radiant
    dmg.num_dice = base_damage
    dmg.die_size = 1  # d1 always rolls 1 → deterministic base_damage
    spell.magic_damage_rolls = [dmg]
    return spell


def _set_hp(engine, bm, idx, hp_cur, hp_max):
    st = engine.get_agent_stats(bm, idx)
    st.hp_max = hp_max
    st.hp_cur = hp_cur
    engine.set_agent_stats(bm, idx, st)


def test_radiant_soul_damage_bonus():
    """Celestial L6 Radiant spell at 2 targets: exactly one takes +chaMod, once per turn.

    This is the real test for TASK D — it exercises the Automatic damage path, which the
    original Save-only implementation never reached.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    cs = _warlock_stats(6, rpg.WarlockSubclass.Celestial)
    cs.cha = 16  # CHA mod +3
    cs.can_cast_spell = True
    engine.set_agent_spells(bm, caster_idx, [_make_radiant_automatic_spell(10)])
    engine.set_agent_stats(bm, caster_idx, cs)

    t0 = add_agent_to_battle(engine, bm, create_test_agent("T0", 6, 5))
    t1 = add_agent_to_battle(engine, bm, create_test_agent("T1", 7, 5))
    _set_hp(engine, bm, t0, 50, 50)
    _set_hp(engine, bm, t1, 50, 50)

    action = rpg.SpellAction()
    action.caster_idx = caster_idx
    action.spell_idx = 0
    action.target_indices = [t0, t1]

    result = engine.execute_spell(bm, action)
    assert result.valid, "spell cast should be valid"

    dealt = sorted([50 - engine.get_agent_stats(bm, t0).hp_cur,
                    50 - engine.get_agent_stats(bm, t1).hp_cur])
    assert dealt == [10, 13], f"exactly one target should take +3 (chaMod), got {dealt}"

    # Second cast same turn: flag already used → both take base 10, no bonus.
    _set_hp(engine, bm, t0, 50, 50)
    _set_hp(engine, bm, t1, 50, 50)
    engine.execute_spell(bm, action)
    dealt2 = sorted([50 - engine.get_agent_stats(bm, t0).hp_cur,
                     50 - engine.get_agent_stats(bm, t1).hp_cur])
    assert dealt2 == [10, 10], f"second cast same turn should add no bonus, got {dealt2}"

    # After the per-turn flag resets (start of next turn), the bonus returns.
    cond = engine.get_agent_conditions(bm, caster_idx)
    cond.radiant_soul_used = False
    engine.set_agent_conditions(bm, caster_idx, cond)
    _set_hp(engine, bm, t0, 50, 50)
    _set_hp(engine, bm, t1, 50, 50)
    engine.execute_spell(bm, action)
    dealt3 = sorted([50 - engine.get_agent_stats(bm, t0).hp_cur,
                     50 - engine.get_agent_stats(bm, t1).hp_cur])
    assert dealt3 == [10, 13], f"after flag reset the bonus should reapply, got {dealt3}"
    print("✅ test_radiant_soul_damage_bonus passed")


# ─────────────────────────────────────────────────────────────────────────────
# TASK E: Celestial Resilience (Celestial L10) — self temp HP on rest / Magical Cunning
# ─────────────────────────────────────────────────────────────────────────────

def test_celestial_resilience_short_rest():
    """Celestial Warlock L10 on short rest: gains char_level + CHA mod temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Celestial Warlock L10 with CHA 16 (mod +3)
    celestial_stats = _warlock_stats(10, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 16
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Apply short rest
    engine.apply_short_rest(bm)

    # Check: temp HP = 10 + 3 = 13
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    expected_temp_hp = 13
    assert celestial_after.temp_hp == expected_temp_hp, \
        f"L10 Celestial after short rest should have {expected_temp_hp} temp HP, got {celestial_after.temp_hp}"
    print("✅ test_celestial_resilience_short_rest passed")


def test_celestial_resilience_long_rest():
    """Celestial Warlock L10 on long rest: gains char_level + CHA mod temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Celestial Warlock L10 with CHA 16 (mod +3)
    celestial_stats = _warlock_stats(10, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 16
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Apply long rest
    engine.apply_long_rest(bm)

    # Check: temp HP = 10 + 3 = 13
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    expected_temp_hp = 13
    assert celestial_after.temp_hp == expected_temp_hp, \
        f"L10 Celestial after long rest should have {expected_temp_hp} temp HP, got {celestial_after.temp_hp}"
    print("✅ test_celestial_resilience_long_rest passed")


def test_celestial_resilience_magical_cunning():
    """Celestial Warlock L10 uses Magical Cunning: gains temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Celestial Warlock L10 with CHA 16 (mod +3)
    celestial_stats = _warlock_stats(10, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 16
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Expend all pact slots first
    celestial_stats = engine.get_agent_stats(bm, celestial_idx)
    lvl = celestial_stats.pact_slot_level()
    rem = list(celestial_stats.spell_slots_remaining)
    rem[lvl - 1] = 0
    celestial_stats.spell_slots_remaining = rem
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Use Magical Cunning
    used = engine.use_magical_cunning(bm, celestial_idx)
    assert used, "Magical Cunning should be usable"

    # Check: temp HP = 10 + 3 = 13
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    expected_temp_hp = 13
    assert celestial_after.temp_hp == expected_temp_hp, \
        f"L10 Celestial after Magical Cunning should have {expected_temp_hp} temp HP, got {celestial_after.temp_hp}"
    print("✅ test_celestial_resilience_magical_cunning passed")


# ─────────────────────────────────────────────────────────────────────────────
# TASK F: Thought Shield (GOO L10) — Psychic resistance
# ─────────────────────────────────────────────────────────────────────────────

def test_thought_shield():
    """Great Old One Warlock L10 has Psychic resistance."""
    s = _warlock_stats(10, rpg.WarlockSubclass.GreatOldOne)
    psychic_mult = s.get_magic_damage_multiplier(7)  # 7 = Psychic
    assert psychic_mult == 0.5, f"GOO L10 should have Psychic resistance 0.5, got {psychic_mult}"

    # Check: other damage types are still 1.0
    assert s.get_magic_damage_multiplier(2) == 1.0, "Fire should still be 1.0"
    assert s.get_magic_damage_multiplier(5) == 1.0, "Necrotic should still be 1.0"
    print("✅ test_thought_shield passed")


if __name__ == "__main__":
    # TASK A
    test_dark_ones_blessing_weapon()
    test_dark_ones_blessing_spell()

    # TASK B
    test_fiendish_resilience()

    # TASK C
    test_healing_light_resource()
    test_healing_light_usage()
    test_healing_light_clamped()

    # TASK D
    test_radiant_soul_resistance()
    test_radiant_soul_damage_bonus()

    # TASK E
    test_celestial_resilience_short_rest()
    test_celestial_resilience_long_rest()
    test_celestial_resilience_magical_cunning()

    # TASK F
    test_thought_shield()

    print("\n✅ All Warlock Phase 2 tests passed!")
