#!/usr/bin/env python3
"""
Fighting Style feat tests (2024 PHB). Fighting Styles are modeled as feats
(`has_feat("<Name>")`), granted by the Fighting Style feature.

Currently covered:
  · Blind Fighting — Blindsight 10 ft. Queried from has_feat (not blindsight_range)
    so it round-trips through save/load, which does not serialize raw sense ranges.
    Two halves:
      offense — within 10 ft you perceive (and can target) an invisible creature;
      defense — an invisible attacker within 10 ft of you gains no advantage,
                because you can still perceive it.

The passive damage/AC batch (Archery, Defense, Dueling, Thrown, Great Weapon
Fighting, Unarmed Fighting) lands here as those styles are implemented.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_feats import _place, _target, _land_hit, _land_noncrit_hit
from test_general_feats import _wpn, _breakdown


# ── local weapon/loadout builders ────────────────────────────────────────────

def _ranged(name="Bow", die=8, bonus_hit=0):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.bonus_hit = bonus_hit
    w.range_short_feet = 80
    w.range_long_feet = 320
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _thrown(name="Javelin", die=6):
    w = _wpn(name, rpg.PhysicalDamage.Piercing, die=die)   # Melee type, bonus_hit=50
    w.thrown = True
    return w


def _two_hander(name="Greatsword", die=6, num=2):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.bonus_hit = 50
    w.two_handed = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = num
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _shield():
    w = rpg.Weapon()
    w.name = "Shield"
    w.is_shield = True
    w.ac_bonus = 2
    w.off_hand = True
    return w


def _fist():
    w = rpg.Weapon()          # default name "Unarmed", no damage dice
    w.proficient = True
    w.bonus_hit = 50
    return w


def _empty():
    return rpg.Weapon()       # default "Unarmed", no damage dice → not a "real" weapon


def _solo_arm(engine, bm, idx, weapons, feats=None, strv=14, prof=2):
    """Arm an agent with EXACTLY the given slots (no dice-bearing filler padding,
    unlike test_feats._arm — Dueling's 'one weapon only' check needs true empties)."""
    s = engine.get_agent_stats(bm, idx)
    s.str = strv
    s.dex = 10
    s.prof_bonus = prof
    s.hp_max = 80
    s.hp_cur = 80
    for f in (feats or []):
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, weapons)


def _set_invisible(engine, bm, idx, value=True):
    cond = engine.get_agent_conditions(bm, idx)
    cond.invisible = value
    engine.set_agent_conditions(bm, idx, cond)


def _give_feat(engine, bm, idx, name):
    s = engine.get_agent_stats(bm, idx)
    s.add_feat(name)
    engine.set_agent_stats(bm, idx, s)


# ─────────────────────────────────────────────────────────────────────────────
#  Blind Fighting — offense: perceive/target invisible creatures within 10 ft
# ─────────────────────────────────────────────────────────────────────────────

def test_blind_fighting_perceives_invisible_within_10ft():
    """A Blind Fighting creature perceives an invisible target at ≤10 ft, not beyond."""
    # Distances on a 5 ft/cell grid: col 6 = 5 ft, col 7 = 10 ft, col 8 = 15 ft.
    for col, dist, expect in ((6, "5 ft", True), (7, "10 ft", True), (8, "15 ft", False)):
        bm = setup_battle_map()
        engine = setup_combat_engine()
        atk = add_agent_to_battle(engine, bm, create_test_agent("Blindfighter", 5, 5))
        tgt = add_agent_to_battle(engine, bm, create_test_agent("Ghost", col, 5))
        _give_feat(engine, bm, atk, "Blind Fighting")
        _set_invisible(engine, bm, tgt, True)
        got = engine.can_perceive_target(bm, atk, tgt)
        assert got == expect, f"Blind Fighting at {dist}: expected perceive={expect}, got {got}"
    print("✅ test_blind_fighting_perceives_invisible_within_10ft")


def test_blind_fighting_targets_invisible_in_available_attacks():
    """The invisible enemy a Blind Fighter perceives re-enters its action space (available_attacks)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Blindfighter", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Ghost", 6, 5))
    engine.set_agent_weapons(bm, atk, [_wpn("Sword", rpg.PhysicalDamage.Slashing), rpg.Weapon(), rpg.Weapon()])
    _set_invisible(engine, bm, tgt, True)
    # Without the feat the invisible adjacent target is excluded.
    assert not any(a.target_idx == tgt for a in engine.available_attacks(bm, atk)), \
        "invisible target must be excluded without Blind Fighting"
    # With the feat it is targetable again.
    _give_feat(engine, bm, atk, "Blind Fighting")
    assert any(a.target_idx == tgt for a in engine.available_attacks(bm, atk)), \
        "Blind Fighting viewer should be able to attack an invisible target within 10 ft"
    print("✅ test_blind_fighting_targets_invisible_in_available_attacks")


def test_blind_fighting_does_not_pierce_at_range():
    """Beyond 10 ft, Blind Fighting confers no perception (it is Blindsight 10 ft, not unlimited)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Blindfighter", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Ghost", 9, 5))  # 20 ft
    _give_feat(engine, bm, atk, "Blind Fighting")
    _set_invisible(engine, bm, tgt, True)
    assert not engine.can_perceive_target(bm, atk, tgt), "Blind Fighting must not perceive past 10 ft"
    print("✅ test_blind_fighting_does_not_pierce_at_range")


# ─────────────────────────────────────────────────────────────────────────────
#  Blind Fighting — defense: an invisible attacker gains no advantage vs you
# ─────────────────────────────────────────────────────────────────────────────

def test_blind_fighting_defender_denies_invisible_advantage():
    """An invisible attacker gets no advantage attacking a Blind Fighting defender within 10 ft."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Sneak", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Blindfighter", 6, 5))
    engine.set_agent_weapons(bm, atk, [_wpn("Sword", rpg.PhysicalDamage.Slashing), rpg.Weapon(), rpg.Weapon()])
    _set_invisible(engine, bm, atk, True)

    # Control: an ordinary defender cannot see the invisible attacker → advantage stands.
    engine.begin_turn(bm, atk)
    base = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert base.advantage, "invisible attacker should have advantage vs a sighted (non-Blind-Fighting) defender"

    # Give the defender Blind Fighting → it perceives the attacker → no advantage.
    _give_feat(engine, bm, tgt, "Blind Fighting")
    _set_invisible(engine, bm, atk, True)  # re-apply: the control attack ended the attacker's invisibility
    engine.begin_turn(bm, atk)
    res = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert not res.advantage, "invisible attacker should NOT have advantage vs a Blind Fighting defender within 10 ft"
    print("✅ test_blind_fighting_defender_denies_invisible_advantage")


# ─────────────────────────────────────────────────────────────────────────────
#  Archery — +2 to attack rolls with Ranged weapons
# ─────────────────────────────────────────────────────────────────────────────

def test_archery_plus_two_to_hit_with_ranged():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Archer", 5, 5)
    t = _place(engine, bm, "Tgt", 7, 5)   # 10 ft — within a bow's range
    _solo_arm(engine, bm, a, [_ranged(), _empty(), _empty()])
    _target(engine, bm, t)
    base = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert base.valid, "ranged attack should be valid in range"
    s = engine.get_agent_stats(bm, a); s.add_feat("Archery"); engine.set_agent_stats(bm, a, s)
    withf = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert withf.attack_mod == base.attack_mod + 2, \
        f"Archery should add +2 to-hit ({base.attack_mod} → {withf.attack_mod})"
    print("✅ test_archery_plus_two_to_hit_with_ranged")


def test_archery_not_on_thrown_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Thrower", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_thrown(), _empty(), _empty()])
    _target(engine, bm, t)
    base = engine.execute_action(bm, rpg.Attack(a, t, 0))
    s = engine.get_agent_stats(bm, a); s.add_feat("Archery"); engine.set_agent_stats(bm, a, s)
    withf = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert withf.attack_mod == base.attack_mod, \
        "Archery must NOT apply to a thrown (Melee-type) weapon"
    print("✅ test_archery_not_on_thrown_weapon")


# ─────────────────────────────────────────────────────────────────────────────
#  Defense — +1 AC while wearing armor
# ─────────────────────────────────────────────────────────────────────────────

def _armor_set(name="Chain Shirt", ac_bonus=3):
    """A fixed-size-6 armor array [helmet, chest, leggings, boots, gloves, cloak]
    with one named chest piece (an equipped, non-empty piece → has_armor)."""
    arr = [rpg.Armor() for _ in range(6)]
    arr[1].name = name
    arr[1].ac_bonus = ac_bonus
    return arr


def test_defense_plus_one_ac_with_armor():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Guard", 5, 5)
    engine.set_agent_armor(bm, a, _armor_set())
    ac0 = engine.calculate_ac(bm, a)
    s = engine.get_agent_stats(bm, a); s.add_feat("Defense"); engine.set_agent_stats(bm, a, s)
    ac1 = engine.calculate_ac(bm, a)
    assert ac1 == ac0 + 1, f"Defense should add +1 AC with armor ({ac0} → {ac1})"
    print("✅ test_defense_plus_one_ac_with_armor")


def test_defense_nothing_without_armor():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "DefNoArmor", 5, 5)   # Defense feat, no armor
    s = engine.get_agent_stats(bm, a); s.add_feat("Defense"); engine.set_agent_stats(bm, a, s)
    b = _place(engine, bm, "Plain", 9, 5)         # no feat, no armor (identical defaults)
    assert engine.calculate_ac(bm, a) == engine.calculate_ac(bm, b), \
        "Defense grants no AC while unarmored"
    print("✅ test_defense_nothing_without_armor")


# ─────────────────────────────────────────────────────────────────────────────
#  Dueling — +2 damage with a one-handed melee weapon and no other weapon
# ─────────────────────────────────────────────────────────────────────────────

def _rapier():
    return _wpn("Rapier", rpg.PhysicalDamage.Piercing, die=8)


def test_dueling_one_handed_plus_two():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Duelist", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_rapier(), _empty(), _empty()], feats=["Dueling"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert ("Dueling", 2) in _breakdown(r), f"expected Dueling +2, got {_breakdown(r)}"
    print("✅ test_dueling_one_handed_plus_two")


def test_dueling_shield_is_allowed():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Duelist", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_rapier(), _shield(), _empty()], feats=["Dueling"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert ("Dueling", 2) in _breakdown(r), "a Shield does not disqualify Dueling"
    print("✅ test_dueling_shield_is_allowed")


def test_dueling_blocked_by_second_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Duelist", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    second = _wpn("Shortsword", rpg.PhysicalDamage.Slashing, die=6)
    _solo_arm(engine, bm, a, [_rapier(), second, _empty()], feats=["Dueling"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert all(k != "Dueling" for k, _ in _breakdown(r)), \
        "a second real weapon disqualifies Dueling"
    print("✅ test_dueling_blocked_by_second_weapon")


def test_dueling_blocked_two_handed():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Duelist", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_two_hander(), _empty(), _empty()], feats=["Dueling"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert all(k != "Dueling" for k, _ in _breakdown(r)), \
        "a two-handed weapon disqualifies Dueling"
    print("✅ test_dueling_blocked_two_handed")


# ─────────────────────────────────────────────────────────────────────────────
#  Thrown Weapon Fighting — +2 damage with a thrown weapon
# ─────────────────────────────────────────────────────────────────────────────

def test_thrown_weapon_fighting_plus_two():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Thrower", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_thrown(), _empty(), _empty()], feats=["Thrown Weapon Fighting"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert ("Thrown Weapon Fighting", 2) in _breakdown(r), \
        f"expected Thrown Weapon Fighting +2, got {_breakdown(r)}"
    print("✅ test_thrown_weapon_fighting_plus_two")


def test_thrown_weapon_fighting_not_on_non_thrown():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Swordsman", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_rapier(), _empty(), _empty()], feats=["Thrown Weapon Fighting"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert all(k != "Thrown Weapon Fighting" for k, _ in _breakdown(r)), \
        "Thrown Weapon Fighting must not apply to a non-thrown weapon"
    print("✅ test_thrown_weapon_fighting_not_on_non_thrown")


# ─────────────────────────────────────────────────────────────────────────────
#  Great Weapon Fighting — 1s/2s on two-handed weapon dice become 3s
# ─────────────────────────────────────────────────────────────────────────────

def test_great_weapon_fighting_floors_dice_at_three():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brute", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_two_hander(), _empty(), _empty()],
              feats=["Great Weapon Fighting"], strv=10)
    _target(engine, bm, t, hp=10_000_000)
    for _ in range(25):
        r = _land_hit(engine, bm, a, t)
        assert all(d >= 3 for d in r.dice_results), \
            f"Great Weapon Fighting must floor every 2H weapon die at 3, got {list(r.dice_results)}"
    print("✅ test_great_weapon_fighting_floors_dice_at_three")


def test_great_weapon_fighting_not_one_handed():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brute", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    onehand = _wpn("Scimitar", rpg.PhysicalDamage.Slashing, die=4)  # one-handed d4
    _solo_arm(engine, bm, a, [onehand, _empty(), _empty()],
              feats=["Great Weapon Fighting"], strv=10)
    _target(engine, bm, t, hp=10_000_000)
    saw_low = False
    for _ in range(80):
        r = _land_hit(engine, bm, a, t)
        if any(d < 3 for d in r.dice_results):
            saw_low = True
            break
    assert saw_low, "Great Weapon Fighting must not floor dice for a one-handed weapon"
    print("✅ test_great_weapon_fighting_not_one_handed")


# ─────────────────────────────────────────────────────────────────────────────
#  Unarmed Fighting — bare Unarmed Strike deals 1d6
# ─────────────────────────────────────────────────────────────────────────────

def test_unarmed_fighting_adds_1d6():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brawler", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    # No feat → a bare Unarmed Strike rolls no weapon dice.
    _solo_arm(engine, bm, a, [_fist(), _empty(), _empty()])
    _target(engine, bm, t, hp=10_000_000)
    r0 = _land_noncrit_hit(engine, bm, a, t)
    assert len(r0.dice_results) == 0, f"bare Unarmed has no dice, got {list(r0.dice_results)}"
    # With Unarmed Fighting → exactly one die in 1..6.
    s = engine.get_agent_stats(bm, a); s.add_feat("Unarmed Fighting"); engine.set_agent_stats(bm, a, s)
    for _ in range(25):
        r = _land_noncrit_hit(engine, bm, a, t)
        assert len(r.dice_results) == 1, f"Unarmed Fighting adds exactly one die, got {list(r.dice_results)}"
        assert 1 <= r.dice_results[0] <= 6, f"die must be a d6, got {r.dice_results[0]}"
    print("✅ test_unarmed_fighting_adds_1d6")


def test_unarmed_fighting_supersedes_tavern_brawler():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brawler", 5, 5); t = _place(engine, bm, "Tgt", 6, 5)
    _solo_arm(engine, bm, a, [_fist(), _empty(), _empty()],
              feats=["Tavern Brawler", "Unarmed Fighting"])
    _target(engine, bm, t, hp=10_000_000)
    # Suppress Tavern Brawler's once-per-turn Push (we never begin_turn, so set the flag once)
    # — otherwise the first hit shoves the target out of the Unarmed weapon's 5 ft reach.
    c = engine.get_agent_conditions(bm, a)
    c.tavern_brawler_push_used_this_turn = True
    engine.set_agent_conditions(bm, a, c)
    saw_high = False
    for _ in range(60):
        r = _land_noncrit_hit(engine, bm, a, t)
        assert len(r.dice_results) == 1, \
            f"with both feats, only ONE die should be added (1d6, not 1d4+1d6), got {list(r.dice_results)}"
        if r.dice_results[0] >= 5:
            saw_high = True
    assert saw_high, "Unarmed Fighting's 1d6 should sometimes roll 5 or 6 (proving it supersedes Tavern Brawler's 1d4)"
    print("✅ test_unarmed_fighting_supersedes_tavern_brawler")


# ─────────────────────────────────────────────────────────────────────────────
#  Two-Weapon Fighting — the off-hand ability-mod behaviour lives in test_dual_wield.py
#  (this style lifts the "no ability mod on off-hand damage" restriction). Here we only
#  confirm the feat is storable; the damage assertions are in the dual-wield suite.
# ─────────────────────────────────────────────────────────────────────────────

def test_two_weapon_fighting_is_storable():
    s = rpg.Stats()
    s.add_feat("Two-Weapon Fighting")
    assert s.has_feat("Two-Weapon Fighting")
    print("✅ test_two_weapon_fighting_is_storable")


if __name__ == "__main__":
    tests = [
        test_blind_fighting_perceives_invisible_within_10ft,
        test_blind_fighting_targets_invisible_in_available_attacks,
        test_blind_fighting_does_not_pierce_at_range,
        test_blind_fighting_defender_denies_invisible_advantage,
        test_archery_plus_two_to_hit_with_ranged,
        test_archery_not_on_thrown_weapon,
        test_defense_plus_one_ac_with_armor,
        test_defense_nothing_without_armor,
        test_dueling_one_handed_plus_two,
        test_dueling_shield_is_allowed,
        test_dueling_blocked_by_second_weapon,
        test_dueling_blocked_two_handed,
        test_thrown_weapon_fighting_plus_two,
        test_thrown_weapon_fighting_not_on_non_thrown,
        test_great_weapon_fighting_floors_dice_at_three,
        test_great_weapon_fighting_not_one_handed,
        test_unarmed_fighting_adds_1d6,
        test_unarmed_fighting_supersedes_tavern_brawler,
        test_two_weapon_fighting_is_storable,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failures += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} fighting-style tests passed")
    sys.exit(1 if failures else 0)
