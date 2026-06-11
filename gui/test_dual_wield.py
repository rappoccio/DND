#!/usr/bin/env python3
"""
Two-Weapon Fighting / dual-wielding (2024 PHB) — the engine-level pieces.

The single Light-property off-hand extra attack is one resource per turn. It lands in the
Bonus Action by default; the Nick mastery (on the off-hand weapon, with the Weapon Mastery
feature) relocates it into the Attack action, freeing the bonus; Dual Wielder grants an
additional bonus-action off-hand attack (the 3-attack turn = main + Nick-in-action + DW-in-bonus).

Covered here (the bits that live in C++):
  · off-hand attacks add NO ability modifier to damage, unless the Two-Weapon Fighting style
    is taken — and a NEGATIVE modifier always applies (RAW "unless that modifier is negative")
  · the off-hand-attack-used per-turn flag is set on a genuine off-hand strike and resets each turn
  · Weapon Mastery is auto-granted to the five martial classes (and not to others)

The GUI economy (Nick button availability, Dual Wielder gating of the bonus-action off-hand
attack) is driven by main.py helpers _offhand_bonus_available / _nick_offhand_idx and is not
exercised here (no headless GUI driver); see those helpers + known_limitations.md.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _place(engine, bm, name, col, row):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row))


def _weapon(name="Dagger", die=6, off_hand=False, mastery=None):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = 50          # land vs AC 10 even with the off-hand proficiency drop
    w.light = True
    w.off_hand = off_hand
    if mastery is not None:
        w.mastery = mastery
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _arm(engine, bm, idx, main, off, feats=None, strv=14):
    s = engine.get_agent_stats(bm, idx)
    s.str = strv
    s.dex = 10
    s.prof_bonus = 2
    s.hp_max = 80
    s.hp_cur = 80
    for f in (feats or []):
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [main, off, rpg.Weapon()])


def _target(engine, bm, idx, hp=400, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _land(engine, bm, a, t, weapon_idx, offhand, tries=40):
    for _ in range(tries):
        action = rpg.Attack(a, t, weapon_idx)
        action.is_offhand = offhand
        r = engine.execute_action(bm, action)
        if r.hit:
            return r
    raise AssertionError("attack never landed")


def _fresh():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = _place(engine, bm, "Rogue", 5, 5)
    t = _place(engine, bm, "Dummy", 5, 6)
    _target(engine, bm, t)
    return bm, engine, a, t


# ─────────────────────────────────────────────────────────────────────────────
#  Off-hand damage modifier
# ─────────────────────────────────────────────────────────────────────────────

def test_main_hand_gets_ability_mod():
    bm, engine, a, t = _fresh()
    _arm(engine, bm, a, _weapon("Dagger"), _weapon("Dagger", off_hand=True), strv=14)  # STR mod +2
    r = _land(engine, bm, a, t, weapon_idx=0, offhand=False)
    assert r.damage_mod == 2, f"main-hand attack adds the +2 STR mod, got {r.damage_mod}"
    print("✅ test_main_hand_gets_ability_mod")


def test_offhand_no_mod_without_twf():
    bm, engine, a, t = _fresh()
    _arm(engine, bm, a, _weapon("Dagger"), _weapon("Dagger", off_hand=True), strv=14)  # +2 mod
    r = _land(engine, bm, a, t, weapon_idx=1, offhand=True)
    assert r.damage_mod == 0, f"off-hand attack drops the positive ability mod, got {r.damage_mod}"
    print("✅ test_offhand_no_mod_without_twf")


def test_offhand_gets_mod_with_twf():
    bm, engine, a, t = _fresh()
    _arm(engine, bm, a, _weapon("Dagger"), _weapon("Dagger", off_hand=True),
         feats=["Two-Weapon Fighting"], strv=14)  # +2 mod
    r = _land(engine, bm, a, t, weapon_idx=1, offhand=True)
    assert r.damage_mod == 2, f"Two-Weapon Fighting restores the +2 mod on off-hand damage, got {r.damage_mod}"
    print("✅ test_offhand_gets_mod_with_twf")


def test_offhand_negative_mod_still_applies():
    # STR 6 → -2 mod. RAW: the off-hand attack adds the modifier "unless that modifier is negative",
    # i.e. a negative modifier is always applied even without Two-Weapon Fighting.
    bm, engine, a, t = _fresh()
    _arm(engine, bm, a, _weapon("Dagger"), _weapon("Dagger", off_hand=True), strv=6)
    r = _land(engine, bm, a, t, weapon_idx=1, offhand=True)
    assert r.damage_mod == -2, f"a negative ability mod still applies to off-hand damage, got {r.damage_mod}"
    print("✅ test_offhand_negative_mod_still_applies")


# ─────────────────────────────────────────────────────────────────────────────
#  Per-turn off-hand-attack flag
# ─────────────────────────────────────────────────────────────────────────────

def test_offhand_attack_used_flag_resets_each_turn():
    bm, engine, a, t = _fresh()
    c = engine.get_agent_conditions(bm, a)
    assert not c.offhand_attack_used, "fresh agent has not spent its off-hand attack"
    c.offhand_attack_used = True
    engine.set_agent_conditions(bm, a, c)
    # begin_turn → Agent::turn() resets per-turn flags.
    bm.placed_agents[a].turn()
    c2 = engine.get_agent_conditions(bm, a)
    assert not c2.offhand_attack_used, "offhand_attack_used must reset at the start of the turn"
    print("✅ test_offhand_attack_used_flag_resets_each_turn")


# ─────────────────────────────────────────────────────────────────────────────
#  Weapon Mastery auto-grant (gates the Nick relocation in the GUI)
# ─────────────────────────────────────────────────────────────────────────────

def test_weapon_mastery_granted_to_martials():
    for cls in (rpg.CharacterClass.Barbarian, rpg.CharacterClass.Fighter,
                rpg.CharacterClass.Paladin, rpg.CharacterClass.Ranger,
                rpg.CharacterClass.Rogue):
        s = rpg.Stats()
        s.initialize_class_resources(cls, 1)
        assert s.has_feat("Weapon Mastery"), f"{cls} should gain Weapon Mastery at L1"
    print("✅ test_weapon_mastery_granted_to_martials")


def test_weapon_mastery_not_granted_to_nonmartials():
    for cls in (rpg.CharacterClass.Monk, rpg.CharacterClass.Wizard,
                rpg.CharacterClass.Cleric):
        s = rpg.Stats()
        s.initialize_class_resources(cls, 5)
        assert not s.has_feat("Weapon Mastery"), f"{cls} should NOT gain Weapon Mastery"
    print("✅ test_weapon_mastery_not_granted_to_nonmartials")


def test_weapon_mastery_not_duplicated_on_reinit():
    s = rpg.Stats()
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 1)
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 5)
    assert list(s.feats).count("Weapon Mastery") == 1, "Weapon Mastery must not duplicate on re-init"
    print("✅ test_weapon_mastery_not_duplicated_on_reinit")


if __name__ == "__main__":
    tests = [
        test_main_hand_gets_ability_mod,
        test_offhand_no_mod_without_twf,
        test_offhand_gets_mod_with_twf,
        test_offhand_negative_mod_still_applies,
        test_offhand_attack_used_flag_resets_each_turn,
        test_weapon_mastery_granted_to_martials,
        test_weapon_mastery_not_granted_to_nonmartials,
        test_weapon_mastery_not_duplicated_on_reinit,
    ]
    for fn in tests:
        fn()
    print(f"\n✅ All {len(tests)} dual-wield tests passed")
