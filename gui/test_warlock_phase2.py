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


def _attack_weapon(attack_bonus=50, num_dice=1, die_size=4):
    """A melee weapon with a big flat damage bonus (added directly in rollDamage, independent of
    dice or ability mod) and a huge to-hit bonus, so any landed hit deals lethal damage."""
    w = rpg.Weapon()
    w.name = "Test Blade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = attack_bonus
    w.bonus_damage = 100  # flat, always added: rollDamage does damage_mod = abilityMod + bonus_damage
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = num_dice
    roll.die_size = die_size
    w.physical_damage_types = [roll]
    return w


def _three(primary):
    """set_agent_weapons expects exactly 3 weapons; pad with unused fillers (attacks use idx 0)."""
    return [primary, rpg.Weapon(), rpg.Weapon()]


def _hit_once(engine, bm, atk, tgt, wpn=0, tries=40):
    """Attack until it lands. A natural-1 auto-misses regardless of bonus, so a single seeded
    roll can fumble; misses deal no damage, so retrying is safe and deterministic."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, wpn))
        if r.hit:
            return r
    raise AssertionError(f"attack never landed in {tries} tries")


# ─────────────────────────────────────────────────────────────────────────────
# TASK A: Dark One's Blessing (Fiend L3) — temp HP on kill
# ─────────────────────────────────────────────────────────────────────────────

def test_dark_ones_blessing_weapon():
    """Fiend Warlock L3 kills with a weapon → gains temp HP = chaMod + level."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add ALL agents first: each add_agent_to_battle re-applies every config (rebuilding agents
    # from their configs), which wipes stats/weapons set on previously-added agents. Configure
    # only AFTER the final add.
    fiend_idx = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=1)

    fiend_stats = _warlock_stats(3, rpg.WarlockSubclass.Fiend)
    fiend_stats.cha = 16  # mod +3
    fiend_stats.str = 14
    fiend_stats.hp_max = 30
    fiend_stats.hp_cur = 30
    engine.set_agent_stats(bm, fiend_idx, fiend_stats)
    engine.set_agent_weapons(bm, fiend_idx, _three(_attack_weapon()))

    ds = engine.get_agent_stats(bm, dummy_idx)
    ds.hp_max = 1
    ds.hp_cur = 1
    engine.set_agent_stats(bm, dummy_idx, ds)

    result = _hit_once(engine, bm, fiend_idx, dummy_idx)
    assert result.target_down, \
        f"a landed attack should kill the 1-HP dummy (dealt {result.total_damage}, hp_after {result.hp_after})"

    fiend_after = engine.get_agent_stats(bm, fiend_idx)
    expected_temp_hp = 6  # chaMod(+3) + level(3)
    assert fiend_after.temp_hp == expected_temp_hp, \
        f"Fiend should have {expected_temp_hp} temp HP from Dark One's Blessing, got {fiend_after.temp_hp}"
    print("✅ test_dark_ones_blessing_weapon passed")


def test_dark_ones_blessing_spell():
    """Fiend Warlock L3 kills with a spell → gains temp HP = chaMod + level."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add ALL agents first, then configure (see note in test_dark_ones_blessing_weapon).
    fiend_idx = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=10, hp=5)

    fiend_stats = _warlock_stats(3, rpg.WarlockSubclass.Fiend)
    fiend_stats.cha = 16
    fiend_stats.hp_max = 30
    fiend_stats.hp_cur = 30
    fiend_stats.can_cast_spell = True
    engine.set_agent_stats(bm, fiend_idx, fiend_stats)

    # Deterministic Automatic spell dealing 10 Force (die_size 1 → always 1).
    spell = rpg.Spell()
    spell.name = "Test Bolt"
    spell.level = 0
    spell.attack_type = rpg.SpellAttack.Automatic
    spell.geometry = rpg.SpellGeometry.Single
    spell.range = 60
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Force
    dmg.num_dice = 10
    dmg.die_size = 1
    spell.magic_damage_rolls = [dmg]
    engine.set_agent_spells(bm, fiend_idx, [spell])

    action = rpg.SpellAction()
    action.caster_idx = fiend_idx
    action.spell_idx = 0
    action.target_indices = [dummy_idx]
    result = engine.execute_spell(bm, action)
    assert result.valid, "spell cast should be valid"
    assert any(tr.target_down for tr in result.target_results), "spell should have killed the dummy"

    fiend_after = engine.get_agent_stats(bm, fiend_idx)
    assert fiend_after.temp_hp == 6, \
        f"Fiend should gain chaMod+level = 6 temp HP from a spell kill, got {fiend_after.temp_hp}"
    print("✅ test_dark_ones_blessing_spell passed")


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
    hl = s.get_resource("Healing Light")
    assert hl is not None, "Celestial Warlock should have Healing Light resource"
    assert hl.max == 6, f"L5 Celestial should have max=1+5=6, got {hl.max}"
    assert hl.current == 6, f"Healing Light should start at max, got {hl.current}"
    print("✅ test_healing_light_resource passed")


def test_healing_light_usage():
    """Celestial Warlock L5 uses Healing Light: spends dice, rolls, heals target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Add ALL agents first, then configure (see note in test_dark_ones_blessing_weapon).
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))

    celestial_stats = _warlock_stats(5, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 16  # mod +3
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

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
    hl_after = celestial_after.get_resource("Healing Light")
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

    # Add ALL agents first, then configure (see note in test_dark_ones_blessing_weapon).
    celestial_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    dummy_idx = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))

    celestial_stats = _warlock_stats(3, rpg.WarlockSubclass.Celestial)
    celestial_stats.cha = 14  # mod +2
    engine.set_agent_stats(bm, celestial_idx, celestial_stats)

    # Try to use 10 dice, but capped to min(10, 4 current, 2 CHA mod) = 2
    healed = engine.use_healing_light(bm, celestial_idx, dummy_idx, 10)

    # Check: resource was spent only 2
    celestial_after = engine.get_agent_stats(bm, celestial_idx)
    hl_after = celestial_after.get_resource("Healing Light")
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

    # Add ALL agents first, then configure (see note in test_dark_ones_blessing_weapon).
    caster_idx = add_agent_to_battle(engine, bm, create_test_agent("Celestial", 5, 5))
    t0 = add_agent_to_battle(engine, bm, create_test_agent("T0", 6, 5))
    t1 = add_agent_to_battle(engine, bm, create_test_agent("T1", 7, 5))

    cs = _warlock_stats(6, rpg.WarlockSubclass.Celestial)
    cs.cha = 16  # CHA mod +3
    cs.can_cast_spell = True
    engine.set_agent_stats(bm, caster_idx, cs)
    engine.set_agent_spells(bm, caster_idx, [_make_radiant_automatic_spell(10)])
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
