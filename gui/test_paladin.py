#!/usr/bin/env python3
"""
Test Paladin: Lay on Hands resource/healing and Oath of Devotion Sacred Weapon.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _paladin(engine, bm, idx, level, cha=16, oath=None):
    """Configure agent idx as a Paladin of the given level (optionally with an oath)."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Paladin, level)
    s.cha = cha
    if oath is not None:
        s.paladin_oath = oath
    s.initialize_class_resources(rpg.CharacterClass.Paladin, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _melee_weapon():
    """A simple proficient STR melee weapon (1d8 slashing)."""
    w = rpg.Weapon()
    w.name = "Longsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = 0
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _soft_target(engine, bm, idx, hp=100):
    """Configure agent as a soft target with low HP."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.hp_max = hp
    s.hp_cur = hp // 2  # Start damaged
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _setup(level):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    paladin_idx = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _paladin(engine, bm, paladin_idx, level)
    _soft_target(engine, bm, target_idx)
    return bm, engine, paladin_idx, target_idx


def test_lay_on_hands_resource():
    """Paladin L1: Lay on Hands resource exists with 5 × level HP pool."""
    for level in [1, 5, 10, 20]:
        bm, engine, paladin_idx, _ = _setup(level)
        s = engine.get_agent_stats(bm, paladin_idx)
        loh = s.get_resource("Lay on Hands")
        assert loh is not None, f"Paladin L{level} should have Lay on Hands resource"
        expected_pool = 5 * level
        assert loh.current == expected_pool, f"L{level} should have {expected_pool} HP pool, got {loh.current}"
        assert loh.max == expected_pool, f"L{level} pool max should be {expected_pool}, got {loh.max}"
    print("✅ test_lay_on_hands_resource passed")


def test_lay_on_hands_partial_spend():
    """Lay on Hands: partial heal decrements pool correctly."""
    bm, engine, paladin_idx, target_idx = _setup(5)
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 25, f"L5 should have 25 HP pool, got {loh.current}"

    # Heal for 10 HP
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 10)
    assert actual_healed == 10, f"Should heal 10 HP, got {actual_healed}"

    # Check pool was decremented
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 15, f"Pool should be 15 after 10 HP spend, got {loh.current}"
    print("✅ test_lay_on_hands_partial_spend passed")


def test_lay_on_hands_no_overheal():
    """Lay on Hands: clamped to min(pool, hp_deficit)."""
    bm, engine, paladin_idx, target_idx = _setup(10)  # L10 has 50 HP pool

    # Target has 50 HP, max 100, so needs 50 HP to be full
    target_s = engine.get_agent_stats(bm, target_idx)
    assert target_s.hp_cur == 50, f"Target should be at 50 HP, got {target_s.hp_cur}"
    assert target_s.hp_max == 100, f"Target max should be 100, got {target_s.hp_max}"

    # Paladin L10 has 50 HP pool, so try to heal for 60 HP
    # Should clamp to min(pool=50, heal_needed=50) = 50
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 60)
    assert actual_healed == 50, f"Should clamp to 50 HP (to full), got {actual_healed}"

    # Check target is now full
    target_s = engine.get_agent_stats(bm, target_idx)
    assert target_s.hp_cur == 100, f"Target should be at 100 HP, got {target_s.hp_cur}"

    # Check pool spent exactly 50
    paladin_s = engine.get_agent_stats(bm, paladin_idx)
    loh = paladin_s.get_resource("Lay on Hands")
    assert loh.current == 0, f"Pool should be 0 after spending 50 (50-50), got {loh.current}"
    print("✅ test_lay_on_hands_no_overheal passed")


def test_lay_on_hands_depleted_pool():
    """Lay on Hands: fails when pool is empty."""
    bm, engine, paladin_idx, target_idx = _setup(1)  # L1 has 5 HP pool

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.current = 0  # Deplete pool
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    # Try to heal
    actual_healed = engine.lay_on_hands(bm, paladin_idx, target_idx, 5)
    assert actual_healed == -1, f"Should return -1 when pool empty, got {actual_healed}"
    print("✅ test_lay_on_hands_depleted_pool passed")


def test_lay_on_hands_long_rest_restore():
    """Lay on Hands: pool restores on long rest."""
    bm, engine, paladin_idx, _ = _setup(3)  # L3 has 15 HP pool

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.current = 0  # Deplete
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    # Long rest restores
    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    loh.restore_long_rest()
    s.resources["Lay on Hands"] = loh
    engine.set_agent_stats(bm, paladin_idx, s)

    s = engine.get_agent_stats(bm, paladin_idx)
    loh = s.get_resource("Lay on Hands")
    assert loh.current == 15, f"Pool should be 15 after long rest, got {loh.current}"
    print("✅ test_lay_on_hands_long_rest_restore passed")


# ─────────────────────────────────────────────────────────────────────────────
# Sacred Weapon (Oath of Devotion)
# ─────────────────────────────────────────────────────────────────────────────

def _devotion_setup(level, cha=16):
    """A Paladin of the Oath of Devotion with a melee weapon and a dummy target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _paladin(engine, bm, pal, level, cha=cha, oath=rpg.PaladinOath.OathOfDevotion)
    _soft_target(engine, bm, tgt, hp=100)
    engine.set_agent_weapons(bm, pal, _melee_weapon())
    return bm, engine, pal, tgt


def test_sacred_weapon_activation():
    """Sacred Weapon: spends 1 Channel Oath, grants +CHA mod (min 1), sets a 10-round duration."""
    bm, engine, pal, _ = _devotion_setup(3, cha=16)  # CHA 16 → +3

    co_before = engine.get_agent_stats(bm, pal).get_resource("Channel Oath").current
    bonus = engine.activate_sacred_weapon(bm, pal)
    assert bonus == 3, f"CHA 16 should grant +3, got {bonus}"

    s = engine.get_agent_stats(bm, pal)
    assert s.sacred_weapon_bonus == 3, f"sacred_weapon_bonus should be 3, got {s.sacred_weapon_bonus}"
    assert s.sacred_weapon_turns == 10, f"duration should be 10 rounds, got {s.sacred_weapon_turns}"
    co_after = s.get_resource("Channel Oath").current
    assert co_after == co_before - 1, f"should spend 1 Channel Oath ({co_before}->{co_after})"
    print("✅ test_sacred_weapon_activation passed")


def test_sacred_weapon_min_bonus():
    """Sacred Weapon: low CHA still grants a minimum +1 bonus."""
    bm, engine, pal, _ = _devotion_setup(3, cha=8)  # CHA 8 → -1, clamped to +1
    bonus = engine.activate_sacred_weapon(bm, pal)
    assert bonus == 1, f"low CHA should clamp to +1, got {bonus}"
    print("✅ test_sacred_weapon_min_bonus passed")


def test_sacred_weapon_wrong_oath():
    """Sacred Weapon: a non-Devotion oath cannot activate it (returns -1, no buff, no spend)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    _paladin(engine, bm, pal, 3, cha=16, oath=rpg.PaladinOath.OathOfVengeance)

    co_before = engine.get_agent_stats(bm, pal).get_resource("Channel Oath").current
    bonus = engine.activate_sacred_weapon(bm, pal)
    assert bonus == -1, f"wrong oath should return -1, got {bonus}"

    s = engine.get_agent_stats(bm, pal)
    assert s.sacred_weapon_turns == 0, "no buff should be applied for the wrong oath"
    assert s.get_resource("Channel Oath").current == co_before, "no Channel Oath should be spent"
    print("✅ test_sacred_weapon_wrong_oath passed")


def test_sacred_weapon_no_resource():
    """Sacred Weapon: fails (returns -1) when no Channel Oath uses remain."""
    bm, engine, pal, _ = _devotion_setup(3)

    s = engine.get_agent_stats(bm, pal)
    co = s.get_resource("Channel Oath")
    co.current = 0
    s.resources["Channel Oath"] = co
    engine.set_agent_stats(bm, pal, s)

    bonus = engine.activate_sacred_weapon(bm, pal)
    assert bonus == -1, f"depleted Channel Oath should return -1, got {bonus}"
    assert engine.get_agent_stats(bm, pal).sacred_weapon_turns == 0, "no buff when resource depleted"
    print("✅ test_sacred_weapon_no_resource passed")


def test_sacred_weapon_attack_bonus_applied():
    """Sacred Weapon: the attack-roll modifier increases by the bonus while active."""
    bm, engine, pal, tgt = _devotion_setup(3, cha=16)

    # Baseline attack modifier with Sacred Weapon inactive.
    base = engine.execute_action(bm, rpg.Attack(pal, tgt, 0))
    base_mod = base.attack_mod

    bonus = engine.activate_sacred_weapon(bm, pal)
    buffed = engine.execute_action(bm, rpg.Attack(pal, tgt, 0))
    assert buffed.attack_mod == base_mod + bonus, \
        f"attack_mod should rise by {bonus} ({base_mod} -> {base_mod + bonus}), got {buffed.attack_mod}"
    print("✅ test_sacred_weapon_attack_bonus_applied passed")


def test_sacred_weapon_duration_expires():
    """Sacred Weapon: duration ticks down at the start of each of the Paladin's turns and clears."""
    bm, engine, pal, _ = _devotion_setup(3)
    engine.activate_sacred_weapon(bm, pal)

    # One begin_turn → 10 becomes 9.
    engine.begin_turn(bm, pal)
    assert engine.get_agent_stats(bm, pal).sacred_weapon_turns == 9, "first turn start should tick to 9"

    # Nine more begin_turns → reaches 0 and the bonus is cleared.
    for _ in range(9):
        engine.begin_turn(bm, pal)
    s = engine.get_agent_stats(bm, pal)
    assert s.sacred_weapon_turns == 0, f"duration should be 0 after 10 turns, got {s.sacred_weapon_turns}"
    assert s.sacred_weapon_bonus == 0, "bonus should clear when the duration expires"
    print("✅ test_sacred_weapon_duration_expires passed")


# ── Divine Smite ─────────────────────────────────────────────────────────────

def _smite_weapon():
    """Guaranteed-hit proficient melee weapon (1d8 slashing) for Divine Smite tests."""
    w = rpg.Weapon()
    w.name = "Longsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.attack_bonus = 50  # guaranteed hit
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _smite_ranged_weapon():
    """Guaranteed-hit ranged weapon — Divine Smite must NOT trigger on this."""
    w = rpg.Weapon()
    w.name = "Longbow"
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.range_short_feet = 150
    w.range_long_feet = 600
    w.attack_bonus = 50
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _smite_setup(level=5, slots=None, ranged=False, undead=False, fiend=False, tgt_hp=500):
    """Paladin (guaranteed-hit weapon) + a tanky target that survives many smites.
    `slots` overrides spell_slots_remaining directly for deterministic slot-level tests."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _paladin(engine, bm, pal, level)
    s = engine.get_agent_stats(bm, tgt)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.hp_max = tgt_hp
    s.hp_cur = tgt_hp
    s.is_undead = undead
    s.is_fiend = fiend
    engine.set_agent_stats(bm, tgt, s)
    ps = engine.get_agent_stats(bm, pal)
    if slots is not None:
        ps.spell_slots_remaining = slots
    engine.set_agent_stats(bm, pal, ps)
    engine.set_agent_weapons(bm, pal, _smite_ranged_weapon() if ranged else _smite_weapon())
    return bm, engine, pal, tgt


def _land_smite_hit(engine, bm, pal, tgt):
    attack = rpg.Attack(pal, tgt, 0)
    for _ in range(12):
        r = engine.execute_action(bm, attack)
        if r.hit:
            return r
    return None


def _has_smite_breakdown(result):
    return any(name == "divine smite" for name, _ in result.damage_breakdown)


def test_divine_smite_base_damage():
    """1st-level slot → 2d8 Radiant; spends the slot, the bonus action, and the leveled-spell interlock."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0])
    r = _land_smite_hit(engine, bm, pal, tgt)
    assert r is not None and r.hit, "attack should land"
    assert engine.get_agent_conditions(bm, pal).divine_smite_available, \
        "Divine Smite should be available after a melee hit"
    assert engine.has_bonus_action(bm, pal), "bonus action should be available before smiting"
    base = r.total_damage
    hp_before = engine.get_agent_stats(bm, tgt).hp_cur
    dmg = engine.apply_divine_smite_effect(bm, pal, tgt, 1, r)
    assert 2 <= dmg <= 16, f"1st-level Divine Smite should be 2d8 (2-16), got {dmg}"
    assert r.total_damage - base == dmg, "result total should rise by exactly the smite damage"
    assert hp_before - engine.get_agent_stats(bm, tgt).hp_cur == dmg, "target HP should drop by the smite damage"
    assert rpg.MagicDamage.Radiant in list(r.magic_damage_types), "Divine Smite deals Radiant"
    assert _has_smite_breakdown(r), "damage_breakdown should include a 'divine smite' entry"
    ps = engine.get_agent_stats(bm, pal)
    assert ps.spell_slots_remaining[0] == 1, "one 1st-level slot consumed"
    assert ps.leveled_spell_cast_this_turn, "leveled-spell interlock should be set"
    assert not engine.has_bonus_action(bm, pal), "bonus action should be consumed"
    assert engine.get_agent_conditions(bm, pal).divine_smite_used, "Divine Smite marked used this turn"
    print("✅ test_divine_smite_base_damage passed")


def test_divine_smite_upcast_scaling():
    """Each slot level above 1st adds 1d8, capped at a 5th-level slot (6d8)."""
    for slot_level, lo, hi in [(2, 3, 24), (3, 4, 32), (5, 6, 48)]:
        slots = [0] * 9
        slots[slot_level - 1] = 1
        bm, engine, pal, tgt = _smite_setup(level=17, slots=slots)
        r = _land_smite_hit(engine, bm, pal, tgt)
        assert r is not None and r.hit
        dmg = engine.apply_divine_smite_effect(bm, pal, tgt, slot_level, r)
        assert lo <= dmg <= hi, f"level-{slot_level} slot should be {lo//1}..{hi} ({lo}d8 band), got {dmg}"
        assert engine.get_agent_stats(bm, pal).spell_slots_remaining[slot_level - 1] == 0, \
            f"the level-{slot_level} slot should be consumed"
    print("✅ test_divine_smite_upcast_scaling passed")


def test_divine_smite_undead_fiend_bonus():
    """+1d8 against an Undead or a Fiend (1st-level slot → 3d8)."""
    for kind in ("undead", "fiend"):
        bm, engine, pal, tgt = _smite_setup(level=5, slots=[1, 0, 0, 0, 0, 0, 0, 0, 0],
                                            undead=(kind == "undead"), fiend=(kind == "fiend"))
        r = _land_smite_hit(engine, bm, pal, tgt)
        assert r is not None and r.hit
        dmg = engine.apply_divine_smite_effect(bm, pal, tgt, 1, r)
        assert 3 <= dmg <= 24, f"1st-level smite vs {kind} should be 3d8 (3-24), got {dmg}"
    print("✅ test_divine_smite_undead_fiend_bonus passed")


def test_divine_smite_once_per_turn():
    """A second smite the same turn is rejected (returns -1, no extra damage)."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[3, 0, 0, 0, 0, 0, 0, 0, 0])
    r = _land_smite_hit(engine, bm, pal, tgt)
    engine.apply_divine_smite_effect(bm, pal, tgt, 1, r)
    total_after_first = r.total_damage
    slots_after_first = engine.get_agent_stats(bm, pal).spell_slots_remaining[0]
    again = engine.apply_divine_smite_effect(bm, pal, tgt, 1, r)
    assert again == -1, f"second smite this turn should be rejected, got {again}"
    assert r.total_damage == total_after_first, "no extra damage on the rejected second smite"
    assert engine.get_agent_stats(bm, pal).spell_slots_remaining[0] == slots_after_first, "no extra slot spent"
    print("✅ test_divine_smite_once_per_turn passed")


def test_divine_smite_blocked_without_slot():
    """With no spell slots, the hit grants no Divine Smite availability and apply is rejected."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[0] * 9)
    r = _land_smite_hit(engine, bm, pal, tgt)
    assert r is not None and r.hit
    assert not engine.get_agent_conditions(bm, pal).divine_smite_available, \
        "no slot → Divine Smite must not be offered"
    assert engine.apply_divine_smite_effect(bm, pal, tgt, 1, r) == -1, "apply should fail with no slot"
    print("✅ test_divine_smite_blocked_without_slot passed")


def test_divine_smite_blocked_without_bonus_action():
    """A spent bonus action means a fresh melee hit does not offer Divine Smite."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0])
    engine.spend_bonus_action(bm, pal)  # e.g. already used the bonus action this turn
    r = _land_smite_hit(engine, bm, pal, tgt)
    assert r is not None and r.hit
    assert not engine.get_agent_conditions(bm, pal).divine_smite_available, \
        "no bonus action → Divine Smite must not be offered"
    print("✅ test_divine_smite_blocked_without_bonus_action passed")


def test_divine_smite_ranged_excluded():
    """Divine Smite requires a melee/unarmed hit — a ranged hit does not qualify."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0], ranged=True)
    r = _land_smite_hit(engine, bm, pal, tgt)
    assert r is not None and r.hit, "ranged attack should land"
    assert not engine.get_agent_conditions(bm, pal).divine_smite_available, \
        "a ranged hit must not enable Divine Smite"
    print("✅ test_divine_smite_ranged_excluded passed")


def test_divine_smite_leveled_spell_interlock():
    """If a leveled spell was already cast this turn, the bonus-action smite is not offered."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0])
    ps = engine.get_agent_stats(bm, pal)
    ps.leveled_spell_cast_this_turn = True
    engine.set_agent_stats(bm, pal, ps)
    r = _land_smite_hit(engine, bm, pal, tgt)
    assert r is not None and r.hit
    assert not engine.get_agent_conditions(bm, pal).divine_smite_available, \
        "leveled spell already cast → no bonus-action Divine Smite"
    print("✅ test_divine_smite_leveled_spell_interlock passed")


def test_divine_smite_resets_next_turn():
    """divine_smite_used clears at the start of the Paladin's next turn (begin_turn)."""
    bm, engine, pal, tgt = _smite_setup(level=5, slots=[3, 0, 0, 0, 0, 0, 0, 0, 0])
    r = _land_smite_hit(engine, bm, pal, tgt)
    engine.apply_divine_smite_effect(bm, pal, tgt, 1, r)
    assert engine.get_agent_conditions(bm, pal).divine_smite_used, "used this turn"
    engine.begin_turn(bm, pal)
    cond = engine.get_agent_conditions(bm, pal)
    assert not cond.divine_smite_used, "begin_turn should clear divine_smite_used"
    assert not cond.divine_smite_available, "availability is set fresh on the next qualifying hit, not carried"
    assert engine.has_bonus_action(bm, pal), "begin_turn should refill the bonus action"
    print("✅ test_divine_smite_resets_next_turn passed")


if __name__ == "__main__":
    test_lay_on_hands_resource()
    test_lay_on_hands_partial_spend()
    test_lay_on_hands_no_overheal()
    test_lay_on_hands_depleted_pool()
    test_lay_on_hands_long_rest_restore()
    test_sacred_weapon_activation()
    test_sacred_weapon_min_bonus()
    test_sacred_weapon_wrong_oath()
    test_sacred_weapon_no_resource()
    test_sacred_weapon_attack_bonus_applied()
    test_sacred_weapon_duration_expires()
    test_divine_smite_base_damage()
    test_divine_smite_upcast_scaling()
    test_divine_smite_undead_fiend_bonus()
    test_divine_smite_once_per_turn()
    test_divine_smite_blocked_without_slot()
    test_divine_smite_blocked_without_bonus_action()
    test_divine_smite_ranged_excluded()
    test_divine_smite_leveled_spell_interlock()
    test_divine_smite_resets_next_turn()
    print("\n✅ All Paladin tests passed!")
