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


# ── Oath of Vengeance ────────────────────────────────────────────────────────

def _vengeance_setup(level, cha=16):
    """A Paladin of the Oath of Vengeance with a melee weapon and two adjacent enemy targets."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    t1  = add_agent_to_battle(engine, bm, create_test_agent("Foe1", 6, 5))
    t2  = add_agent_to_battle(engine, bm, create_test_agent("Foe2", 5, 6))
    _paladin(engine, bm, pal, level, cha=cha, oath=rpg.PaladinOath.OathOfVengeance)
    engine.set_agent_weapons(bm, pal, _melee_weapon())
    for t in (t1, t2):
        s = engine.get_agent_stats(bm, t)
        s.hp_max = 100
        s.hp_cur = 100
        engine.set_agent_stats(bm, t, s)
    return bm, engine, pal, t1, t2


def test_vow_of_enmity_activation():
    """Vow of Enmity: spends 1 Channel Oath and sets the sworn target + a 10-round duration."""
    bm, engine, pal, t1, _ = _vengeance_setup(3)
    co_before = engine.get_agent_stats(bm, pal).get_resource("Channel Oath").current
    ok = engine.activate_vow_of_enmity(bm, pal, t1)
    assert ok, "Vow of Enmity should activate for a Vengeance paladin with a Channel Oath use"
    s = engine.get_agent_stats(bm, pal)
    assert s.vow_of_enmity_target == t1, f"sworn target should be {t1}, got {s.vow_of_enmity_target}"
    assert s.vow_of_enmity_turns == 10, f"duration should be 10 rounds, got {s.vow_of_enmity_turns}"
    assert s.get_resource("Channel Oath").current == co_before - 1, "should spend 1 Channel Oath"
    print("✅ test_vow_of_enmity_activation passed")


def test_vow_of_enmity_advantage():
    """Vow of Enmity: attacks against the sworn foe have Advantage; others do not."""
    bm, engine, pal, t1, t2 = _vengeance_setup(3)
    engine.activate_vow_of_enmity(bm, pal, t1)
    r1 = engine.execute_action(bm, rpg.Attack(pal, t1, 0))
    assert r1.advantage, "attacks vs the sworn foe should have Advantage"
    r2 = engine.execute_action(bm, rpg.Attack(pal, t2, 0))
    assert not r2.advantage, "attacks vs a non-sworn creature should have no Advantage from the vow"
    print("✅ test_vow_of_enmity_advantage passed")


def test_vow_of_enmity_wrong_oath():
    """Vow of Enmity: fails (no fields set, no resource spent) for a non-Vengeance paladin."""
    bm, engine, pal, t1, _ = _vengeance_setup(3)
    s = engine.get_agent_stats(bm, pal)
    s.paladin_oath = rpg.PaladinOath.OathOfDevotion
    engine.set_agent_stats(bm, pal, s)
    co_before = engine.get_agent_stats(bm, pal).get_resource("Channel Oath").current
    ok = engine.activate_vow_of_enmity(bm, pal, t1)
    assert not ok, "wrong oath should not activate Vow of Enmity"
    s = engine.get_agent_stats(bm, pal)
    assert s.vow_of_enmity_turns == 0, "no vow should be set for the wrong oath"
    assert s.get_resource("Channel Oath").current == co_before, "no Channel Oath should be spent"
    print("✅ test_vow_of_enmity_wrong_oath passed")


def test_vow_of_enmity_transfer_on_death():
    """Vow of Enmity: when the sworn foe drops, the vow transfers to another enemy within 30 ft."""
    bm, engine, pal, t1, t2 = _vengeance_setup(3)
    engine.activate_vow_of_enmity(bm, pal, t1)
    ts = engine.get_agent_stats(bm, t1)
    ts.hp_cur = 0
    engine.set_agent_stats(bm, t1, ts)
    engine.apply_unconscious(bm, t1)   # routes through the death chokepoint (vow transfer)
    s = engine.get_agent_stats(bm, pal)
    assert s.vow_of_enmity_target == t2, f"vow should transfer to the remaining enemy, got {s.vow_of_enmity_target}"
    assert s.vow_of_enmity_turns > 0, "the transferred vow should still be active"
    print("✅ test_vow_of_enmity_transfer_on_death passed")


def test_vow_of_enmity_duration_expires():
    """Vow of Enmity: the duration ticks down at the paladin's turn start and clears the target."""
    bm, engine, pal, t1, _ = _vengeance_setup(3)
    engine.activate_vow_of_enmity(bm, pal, t1)
    for _ in range(10):
        engine.begin_turn(bm, pal)
    s = engine.get_agent_stats(bm, pal)
    assert s.vow_of_enmity_turns == 0, f"duration should reach 0 after 10 turns, got {s.vow_of_enmity_turns}"
    assert s.vow_of_enmity_target == -1, "the sworn target should clear when the vow lapses"
    print("✅ test_vow_of_enmity_duration_expires passed")


def test_soul_of_vengeance_gate_and_apply():
    """Soul of Vengeance (L15): the paladin may counter-strike its sworn foe's attack (hit or miss)."""
    bm, engine, pal, t1, _ = _vengeance_setup(15)
    engine.activate_vow_of_enmity(bm, pal, t1)
    engine.set_agent_weapons(bm, t1, _melee_weapon())
    action = rpg.Attack(t1, pal, 0)                 # the sworn foe attacks the paladin
    assert engine.can_soul_of_vengeance(bm, action, pal), "paladin should be able to counter its sworn foe"
    r = engine.apply_soul_of_vengeance(bm, pal, t1, 0)
    assert r.valid, "the Soul of Vengeance counter-strike should resolve"
    assert engine.get_agent_conditions(bm, pal).reaction_used, "the reaction should be spent"
    print("✅ test_soul_of_vengeance_gate_and_apply passed")


def test_soul_of_vengeance_requires_vow():
    """Soul of Vengeance: no counter without an active Vow of Enmity on the attacker."""
    bm, engine, pal, t1, _ = _vengeance_setup(15)
    engine.set_agent_weapons(bm, t1, _melee_weapon())
    action = rpg.Attack(t1, pal, 0)
    assert not engine.can_soul_of_vengeance(bm, action, pal), "no vow → no Soul of Vengeance"
    print("✅ test_soul_of_vengeance_requires_vow passed")


def test_avenging_angel_activation():
    """Avenging Angel (L20): bonus action grants Fly 60 + a 100-round duration and spends a use."""
    bm, engine, pal, _, _ = _vengeance_setup(20, cha=20)
    engine.begin_turn(bm, pal)                       # refill the bonus action
    uses_before = engine.get_agent_stats(bm, pal).get_resource("Avenging Angel").current
    assert uses_before == 1, "a L20 Vengeance paladin should start with 1 Avenging Angel use"
    ok = engine.activate_avenging_angel(bm, pal)
    assert ok, "Avenging Angel should activate"
    s = engine.get_agent_stats(bm, pal)
    assert s.avenging_angel_turns == 100, f"duration should be 100 rounds, got {s.avenging_angel_turns}"
    assert s.speed_fly >= 60, f"should grant Fly 60, got {s.speed_fly}"
    assert s.get_resource("Avenging Angel").current == 0, "should spend the Avenging Angel use"
    print("✅ test_avenging_angel_activation passed")


def test_avenging_angel_frightful_aura():
    """Avenging Angel: an enemy starting its turn in the aura fails a WIS save and is Frightened."""
    bm, engine, pal, t1, _ = _vengeance_setup(20, cha=30)   # DC 8+6+10 = 24, unbeatable below
    ts = engine.get_agent_stats(bm, t1)
    ts.wis = 1
    engine.set_agent_stats(bm, t1, ts)
    engine.begin_turn(bm, pal)
    engine.activate_avenging_angel(bm, pal)
    engine.begin_turn(bm, t1)                        # foe starts its turn inside the Aura of Protection
    assert engine.get_agent_conditions(bm, t1).frightened, "the foe should be Frightened by the Frightful Aura"
    print("✅ test_avenging_angel_frightful_aura passed")


# ── Oath of the Ancients ──────────────────────────────────────────────────────

def _ancients_setup(level, cha=16):
    """A Paladin of the Oath of the Ancients with a melee weapon and an adjacent enemy target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    _paladin(engine, bm, pal, level, cha=cha, oath=rpg.PaladinOath.OathOfAncients)
    engine.set_agent_weapons(bm, pal, _melee_weapon())
    s = engine.get_agent_stats(bm, foe)
    s.hp_max = 100
    s.hp_cur = 100
    engine.set_agent_stats(bm, foe, s)
    return bm, engine, pal, foe


def test_aura_of_warding_self():
    """Aura of Warding: a L7+ Ancients paladin benefits from its own aura; L6 / wrong oath do not."""
    bm, engine, pal, _ = _ancients_setup(7)
    assert engine.has_aura_of_warding(bm, pal), "L7 Ancients paladin should have Aura of Warding"
    bm, engine, pal, _ = _ancients_setup(6)
    assert not engine.has_aura_of_warding(bm, pal), "L6 is below the L7 threshold"
    bm, engine, pal, _ = _ancients_setup(7)
    s = engine.get_agent_stats(bm, pal)
    s.paladin_oath = rpg.PaladinOath.OathOfDevotion
    engine.set_agent_stats(bm, pal, s)
    assert not engine.has_aura_of_warding(bm, pal), "a Devotion paladin has no Aura of Warding"
    print("✅ test_aura_of_warding_self passed")


def test_undying_sentinel_survives_once():
    """Undying Sentinel: lethal damage drops the paladin to 1+3×level HP once, then kills on reuse."""
    bm, engine, pal, _ = _ancients_setup(15)
    s = engine.get_agent_stats(bm, pal)
    s.hp_max = 200
    s.hp_cur = 30
    engine.set_agent_stats(bm, pal, s)
    hp = engine.damage_agent(bm, pal, 100)   # would drop to 0 → Undying Sentinel intervenes
    assert hp == 1 + 3 * 15, f"should survive at 1+3×15={1 + 3 * 15} HP, got {hp}"
    assert engine.get_agent_stats(bm, pal).undying_sentinel_used, "the once-per-rest use should be spent"
    # Second lethal hit: no save left → drops to 0.
    hp2 = engine.damage_agent(bm, pal, 500)
    assert hp2 == 0, f"second lethal hit should drop to 0 (used up), got {hp2}"
    print("✅ test_undying_sentinel_survives_once passed")


def test_undying_sentinel_long_rest_recharge():
    """Undying Sentinel: the use recharges on a long rest."""
    bm, engine, pal, _ = _ancients_setup(15)
    s = engine.get_agent_stats(bm, pal)
    s.undying_sentinel_used = True
    engine.set_agent_stats(bm, pal, s)
    engine.apply_long_rest(bm)
    assert not engine.get_agent_stats(bm, pal).undying_sentinel_used, "long rest should recharge Undying Sentinel"
    print("✅ test_undying_sentinel_long_rest_recharge passed")


def test_elder_champion_activation_and_regen():
    """Elder Champion: bonus action sets a 10-round duration, spends a use, and regens 10 HP/turn."""
    bm, engine, pal, _ = _ancients_setup(20)
    engine.begin_turn(bm, pal)               # refill the bonus action
    ok = engine.activate_elder_champion(bm, pal)
    assert ok, "Elder Champion should activate for a L20 Ancients paladin"
    s = engine.get_agent_stats(bm, pal)
    assert s.elder_champion_turns == 10, f"duration should be 10 rounds, got {s.elder_champion_turns}"
    assert s.get_resource("Elder Champion").current == 0, "should spend the Elder Champion use"
    # Damage the paladin, then a fresh turn start should heal 10 (Regeneration).
    s.hp_max = 200
    s.hp_cur = 50
    engine.set_agent_stats(bm, pal, s)
    engine.begin_turn(bm, pal)
    assert engine.get_agent_stats(bm, pal).hp_cur == 60, "Elder Champion should regen 10 HP at turn start"
    print("✅ test_elder_champion_activation_and_regen passed")


def test_restrained_blocks_movement_and_grants_advantage():
    """Restrained (as applied by Nature's Wrath): Speed 0 and attackers have Advantage against it."""
    bm, engine, pal, foe = _ancients_setup(3)
    fc = engine.get_agent_conditions(bm, foe)
    fc.restrained = True
    engine.set_agent_conditions(bm, foe, fc)
    assert not engine.can_agent_move(bm, foe), "a Restrained creature has Speed 0"
    r = engine.execute_action(bm, rpg.Attack(pal, foe, 0))
    assert r.advantage, "attacks against a Restrained creature have Advantage"
    print("✅ test_restrained_blocks_movement_and_grants_advantage passed")


# ── Oath of Glory ─────────────────────────────────────────────────────────────

def _glory_setup(level, cha=16):
    """A Paladin of the Oath of Glory with a melee weapon and an adjacent enemy target."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    _paladin(engine, bm, pal, level, cha=cha, oath=rpg.PaladinOath.OathOfGlory)
    engine.set_agent_weapons(bm, pal, _melee_weapon())
    s = engine.get_agent_stats(bm, foe)
    s.hp_max = 100
    s.hp_cur = 100
    engine.set_agent_stats(bm, foe, s)
    return bm, engine, pal, foe


def test_aura_of_alacrity_self():
    """Aura of Alacrity: a L7+ Glory paladin benefits from its own aura; L6 / wrong oath do not."""
    bm, engine, pal, _ = _glory_setup(7)
    assert engine.has_aura_of_alacrity(bm, pal), "L7 Glory paladin should have Aura of Alacrity"
    bm, engine, pal, _ = _glory_setup(6)
    assert not engine.has_aura_of_alacrity(bm, pal), "L6 is below the L7 threshold"
    bm, engine, pal, _ = _glory_setup(7)
    s = engine.get_agent_stats(bm, pal)
    s.paladin_oath = rpg.PaladinOath.OathOfDevotion
    engine.set_agent_stats(bm, pal, s)
    assert not engine.has_aura_of_alacrity(bm, pal), "a Devotion paladin has no Aura of Alacrity"
    print("✅ test_aura_of_alacrity_self passed")


def test_inspiring_smite():
    """Inspiring Smite: after a Divine Smite this turn, spend a Channel Oath to grant temp HP; once/turn."""
    bm, engine, pal, foe = _glory_setup(6)
    # Without a Divine Smite this turn, it is not available.
    assert engine.activate_inspiring_smite(bm, pal, pal) < 0, "no smite this turn → unavailable"
    # Mark that a Divine Smite happened this turn, then grant temp HP to the foe's-adjacent paladin (self).
    cond = engine.get_agent_conditions(bm, pal)
    cond.divine_smite_used = True
    engine.set_agent_conditions(bm, pal, cond)
    co_before = engine.get_agent_stats(bm, pal).get_resource("Channel Oath").current
    thp = engine.activate_inspiring_smite(bm, pal, pal)
    assert thp >= 2 + 6, f"pool should be 2d8 + level (>= {2 + 6}), got {thp}"
    s = engine.get_agent_stats(bm, pal)
    assert s.temp_hp == thp, f"paladin should have {thp} temp HP, got {s.temp_hp}"
    assert s.get_resource("Channel Oath").current == co_before - 1, "should spend 1 Channel Oath"
    # Once per turn: a second attempt fails.
    assert engine.activate_inspiring_smite(bm, pal, pal) < 0, "Inspiring Smite is once per turn"
    print("✅ test_inspiring_smite passed")


def test_glorious_defense_resource():
    """Glorious Defense: a L15 Glory paladin has CHA-modifier (min 1) uses per long rest."""
    bm, engine, pal, _ = _glory_setup(15, cha=18)   # CHA 18 → +4
    gd = engine.get_agent_stats(bm, pal).get_resource("Glorious Defense")
    assert gd is not None and gd.current == 4, f"expected 4 uses (CHA +4), got {gd.current if gd else None}"
    print("✅ test_glorious_defense_resource passed")


def _guaranteed_miss_weapon():
    """A melee weapon with a huge negative attack bonus — always misses a normal AC."""
    w = rpg.Weapon()
    w.name = "Clumsy Sword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.bonus_hit = -50           # the field the to-hit roll actually consults (attack_bonus is unused by the engine)
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_living_legend_activation_and_unerring_strike():
    """Living Legend: activation sets a 100-round duration; Unerring Strike promotes the first weapon miss."""
    bm, engine, pal, foe = _glory_setup(20, cha=18)
    engine.set_agent_weapons(bm, pal, _guaranteed_miss_weapon())
    engine.begin_turn(bm, pal)                        # refill bonus action + reset per-turn flags
    ok = engine.activate_living_legend(bm, pal)
    assert ok, "Living Legend should activate for a L20 Glory paladin"
    s = engine.get_agent_stats(bm, pal)
    assert s.living_legend_turns == 100, f"duration should be 100 rounds, got {s.living_legend_turns}"
    assert s.get_resource("Living Legend").current == 0, "should spend the Living Legend use"
    # Unerring Strike promotes a NON-crit weapon miss to a hit and marks itself used for the turn.
    # (A natural 20 auto-hits regardless of the -50 bonus and does NOT consume the feature, since it
    # isn't a miss — so assert on the flag, which only Unerring Strike sets.)
    r1 = engine.execute_action(bm, rpg.Attack(pal, foe, 0))
    cond = engine.get_agent_conditions(bm, pal)
    if r1.critical:
        assert not cond.unerring_strike_used, "a natural 20 auto-hits without consuming Unerring Strike"
    else:
        assert r1.hit, "Unerring Strike should promote a non-crit weapon miss to a hit"
        assert cond.unerring_strike_used, "Unerring Strike should mark itself used for the turn"
        # Once used, a later non-crit miss this turn is NOT promoted (catches any persistence bug).
        r2 = engine.execute_action(bm, rpg.Attack(pal, foe, 0))
        assert r2.critical or not r2.hit, "Unerring Strike is once per turn — a later non-crit miss stands"
    print("✅ test_living_legend_activation_and_unerring_strike passed")


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
    test_vow_of_enmity_activation()
    test_vow_of_enmity_advantage()
    test_vow_of_enmity_wrong_oath()
    test_vow_of_enmity_transfer_on_death()
    test_vow_of_enmity_duration_expires()
    test_soul_of_vengeance_gate_and_apply()
    test_soul_of_vengeance_requires_vow()
    test_avenging_angel_activation()
    test_avenging_angel_frightful_aura()
    test_aura_of_warding_self()
    test_undying_sentinel_survives_once()
    test_undying_sentinel_long_rest_recharge()
    test_elder_champion_activation_and_regen()
    test_restrained_blocks_movement_and_grants_advantage()
    test_aura_of_alacrity_self()
    test_inspiring_smite()
    test_glorious_defense_resource()
    test_living_legend_activation_and_unerring_strike()
    print("\n✅ All Paladin tests passed!")
