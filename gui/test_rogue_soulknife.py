#!/usr/bin/env python3
"""
Test Rogue — Soulknife subclass (2024).

Engine-side coverage:
  · Psionic Power (L3): Psionic Energy Dice resource counts + die size by level.
  · Soul Blades — Homing Strikes (L9): a missed Psychic-Blade attack + a Psionic Energy Die can
    convert to a hit; the die is spent ONLY when it converts.
  · Soul Blades — Psychic Teleportation (L9): spend 1 die, teleport up to 10×roll ft.
  · Psychic Veil (L13): Magic action → Invisible; free use, then by 1 Psionic Energy Die.
  · Rend Mind (L17): Psychic-Blade Sneak Attack → WIS save or Stunned; free use, then by 3 dice.

Psychic Blades weapon manifesting + the bonus second blade are GUI-side (manual verification).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_rogue_phase2 import _high_ac_target


def _soulknife(engine, bm, idx, level, dex=20):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    s.rogue_subclass = rpg.RogueSubclass.Soulknife
    s.dex = dex
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _psychic_blade():
    """A Psychic Blade: finesse, psychic_blade flag, 1d6 (Piercing here for deterministic test damage)."""
    w = rpg.Weapon()
    w.name = "PsychicBlade"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.psychic_blade = True
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 6
    w.physical_damage_types = [roll]
    return w


def _three(primary):
    return [primary, rpg.Weapon(), rpg.Weapon()]


# ─────────────────────────────────────────────────────────────────────────────
# Psionic Power chassis
# ─────────────────────────────────────────────────────────────────────────────

def test_psionic_energy_dice_table():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    expected = {3: (4, 6), 5: (6, 8), 9: (8, 8), 11: (8, 10), 13: (10, 10), 17: (12, 12)}
    for level, (count, die) in expected.items():
        s = _soulknife(engine, bm, idx, level)
        ped = s.get_resource("Psionic Energy")
        assert ped is not None, f"L{level} Soulknife should have Psionic Energy"
        assert ped.current == count, f"L{level}: expected {count} dice, got {ped.current}"
        assert s.psionic_die_size == die, f"L{level}: expected d{die}, got d{s.psionic_die_size}"
    # Non-Soulknife rogue has no Psionic Energy.
    s = engine.get_agent_stats(bm, idx)
    s.rogue_subclass = rpg.RogueSubclass.Thief
    s.initialize_class_resources(rpg.CharacterClass.Rogue, 9)
    assert s.get_resource("Psionic Energy") is None, "Thief should not have Psionic Energy"
    print("✅ test_psionic_energy_dice_table passed")


def test_veil_and_rend_resources_gated_by_level():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    s9 = _soulknife(engine, bm, idx, 9)
    assert s9.get_resource("Psychic Veil") is None and s9.get_resource("Rend Mind") is None
    s13 = _soulknife(engine, bm, idx, 13)
    assert s13.get_resource("Psychic Veil") is not None and s13.get_resource("Rend Mind") is None
    s17 = _soulknife(engine, bm, idx, 17)
    assert s17.get_resource("Psychic Veil") is not None and s17.get_resource("Rend Mind") is not None
    print("✅ test_veil_and_rend_resources_gated_by_level passed")


# ─────────────────────────────────────────────────────────────────────────────
# Soul Blades — Homing Strikes
# ─────────────────────────────────────────────────────────────────────────────

def _setup_attacker(level, target_ac):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=target_ac, hp=500)
    _soulknife(engine, bm, atk, level)
    t = engine.get_agent_stats(bm, tgt)
    t.base_ac = target_ac
    engine.set_agent_stats(bm, tgt, t)
    engine.set_agent_weapons(bm, atk, _three(_psychic_blade()))
    return bm, engine, atk, tgt


def _attack_until(engine, bm, atk, tgt, predicate, tries=400):
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if predicate(r):
            return r
    raise AssertionError("predicate never satisfied")


def test_homing_strike_converts_and_spends_die():
    # AC high enough that most rolls miss. Find a miss that missed by exactly 1 (and not a nat 1),
    # so ANY die (>=1) converts it to a hit.
    bm, engine, atk, tgt = _setup_attacker(9, target_ac=24)
    r = _attack_until(engine, bm, atk, tgt,
                      lambda r: (not r.hit) and r.d20 != 1 and (r.target_ac - r.total_roll) == 1)
    ped_before = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    converted = engine.apply_homing_strike(bm, atk, tgt, 0, r)
    assert converted is True and r.hit, "missed-by-1 + die should convert to a hit"
    assert r.total_damage > 0, "a converted hit should deal damage"
    ped_after = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    assert ped_after == ped_before - 1, f"a converting Homing Strike spends 1 die ({ped_before}->{ped_after})"
    print("✅ test_homing_strike_converts_and_spends_die passed")


def test_homing_strike_no_convert_keeps_die():
    # A natural 1 is always a miss and can never convert → the die must NOT be spent.
    bm, engine, atk, tgt = _setup_attacker(9, target_ac=24)
    r = _attack_until(engine, bm, atk, tgt, lambda r: r.d20 == 1)
    ped_before = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    converted = engine.apply_homing_strike(bm, atk, tgt, 0, r)
    assert converted is False and not r.hit, "a nat-1 miss cannot be homed to a hit"
    ped_after = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    assert ped_after == ped_before, "a non-converting Homing Strike does NOT spend the die"
    print("✅ test_homing_strike_no_convert_keeps_die passed")


def test_homing_strike_requires_psychic_blade_and_level():
    # Below L9: rejected.
    bm, engine, atk, tgt = _setup_attacker(5, target_ac=24)
    r = _attack_until(engine, bm, atk, tgt, lambda r: not r.hit and r.d20 != 1)
    assert engine.apply_homing_strike(bm, atk, tgt, 0, r) is False, "Homing Strikes needs L9+"
    # L9 but non-psychic weapon: rejected.
    bm2, engine2, atk2, tgt2 = _setup_attacker(9, target_ac=24)
    plain = _psychic_blade()
    plain.psychic_blade = False
    engine2.set_agent_weapons(bm2, atk2, _three(plain))
    r2 = _attack_until(engine2, bm2, atk2, tgt2, lambda r: not r.hit and r.d20 != 1)
    assert engine2.apply_homing_strike(bm2, atk2, tgt2, 0, r2) is False, "Homing needs a Psychic Blade"
    print("✅ test_homing_strike_requires_psychic_blade_and_level passed")


# ─────────────────────────────────────────────────────────────────────────────
# Soul Blades — Psychic Teleportation
# ─────────────────────────────────────────────────────────────────────────────

def test_psychic_teleportation_moves_and_spends_die():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    _soulknife(engine, bm, idx, 9)
    ped_before = engine.get_agent_stats(bm, idx).get_resource("Psionic Energy").current
    # Adjacent cell = 5 ft <= 10*die for any die >= 1 → always succeeds.
    ok = engine.psychic_teleportation(bm, idx, 5, 6)
    assert ok is True, "an adjacent teleport (5 ft) should always be in range"
    pos = bm.placed_agents[idx].origin
    assert (pos.col, pos.row) == (5, 6), f"should have teleported to (5,6), at ({pos.col},{pos.row})"
    ped_after = engine.get_agent_stats(bm, idx).get_resource("Psionic Energy").current
    assert ped_after == ped_before - 1, "a successful teleport spends 1 die"
    print("✅ test_psychic_teleportation_moves_and_spends_die passed")


def test_psychic_teleportation_requires_die():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    s = _soulknife(engine, bm, idx, 9)
    s.get_resource("Psionic Energy").current = 0
    engine.set_agent_stats(bm, idx, s)
    assert engine.psychic_teleportation(bm, idx, 5, 6) is False, "no dice → cannot teleport"
    print("✅ test_psychic_teleportation_requires_die passed")


# ─────────────────────────────────────────────────────────────────────────────
# Psychic Veil
# ─────────────────────────────────────────────────────────────────────────────

def test_psychic_veil_uses_then_dice():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    _soulknife(engine, bm, idx, 13)
    ped0 = engine.get_agent_stats(bm, idx).get_resource("Psionic Energy").current
    # First use: spends the free Psychic Veil use, not a die.
    assert engine.activate_psychic_veil(bm, idx) is True
    assert engine.get_agent_conditions(bm, idx).invisible, "Psychic Veil grants Invisible"
    s = engine.get_agent_stats(bm, idx)
    assert s.get_resource("Psychic Veil").current == 0
    assert s.get_resource("Psionic Energy").current == ped0, "first use does not spend a die"
    # Clear invisibility, use again: now it must spend 1 Psionic Energy Die.
    c = engine.get_agent_conditions(bm, idx); c.invisible = False
    engine.set_agent_conditions(bm, idx, c)
    assert engine.activate_psychic_veil(bm, idx) is True
    assert engine.get_agent_stats(bm, idx).get_resource("Psionic Energy").current == ped0 - 1
    print("✅ test_psychic_veil_uses_then_dice passed")


def test_psychic_veil_gated_below_l13():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    _soulknife(engine, bm, idx, 11)
    assert engine.activate_psychic_veil(bm, idx) is False, "Psychic Veil needs L13+"
    print("✅ test_psychic_veil_gated_below_l13 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Rend Mind
# ─────────────────────────────────────────────────────────────────────────────

def test_rend_mind_stuns_and_spends_use():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), hp=500)
    _soulknife(engine, bm, atk, 17)
    _high_ac_target(engine, bm, tgt)   # terrible saves → fails the WIS save
    assert engine.can_rend_mind(bm, atk) is True
    assert engine.apply_rend_mind(bm, atk, tgt) is True, "bad-WIS target should fail and be Stunned"
    assert engine.get_agent_conditions(bm, tgt).stunned, "Rend Mind applies Stunned"
    assert engine.get_agent_stats(bm, atk).get_resource("Rend Mind").current == 0, "spends the free use"
    print("✅ test_rend_mind_stuns_and_spends_use passed")


def test_rend_mind_falls_back_to_three_dice():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), hp=500)
    s = _soulknife(engine, bm, atk, 17)
    s.get_resource("Rend Mind").current = 0       # free use already spent
    engine.set_agent_stats(bm, atk, s)
    _high_ac_target(engine, bm, tgt)
    ped_before = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    assert engine.can_rend_mind(bm, atk) is True, "still usable via 3 Psionic Energy Dice"
    assert engine.apply_rend_mind(bm, atk, tgt) is True
    ped_after = engine.get_agent_stats(bm, atk).get_resource("Psionic Energy").current
    assert ped_after == ped_before - 3, f"fallback spends 3 dice ({ped_before}->{ped_after})"
    print("✅ test_rend_mind_falls_back_to_three_dice passed")


def test_rend_mind_gated_below_l17():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("SK", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), hp=500)
    _soulknife(engine, bm, atk, 13)
    assert engine.can_rend_mind(bm, atk) is False, "Rend Mind needs L17+"
    assert engine.apply_rend_mind(bm, atk, tgt) is False
    print("✅ test_rend_mind_gated_below_l17 passed")


if __name__ == "__main__":
    test_psionic_energy_dice_table()
    test_veil_and_rend_resources_gated_by_level()
    test_homing_strike_converts_and_spends_die()
    test_homing_strike_no_convert_keeps_die()
    test_homing_strike_requires_psychic_blade_and_level()
    test_psychic_teleportation_moves_and_spends_die()
    test_psychic_teleportation_requires_die()
    test_psychic_veil_uses_then_dice()
    test_psychic_veil_gated_below_l13()
    test_rend_mind_stuns_and_spends_use()
    test_rend_mind_falls_back_to_three_dice()
    test_rend_mind_gated_below_l17()
    print("\n✅ All Soulknife subclass tests passed")
