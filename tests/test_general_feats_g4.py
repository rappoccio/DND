#!/usr/bin/env python3
"""
General feat tests — phase G4 (2024 PHB): bonus-attack + ranged-penalty feats.

Ranged-penalty (gating in determineAdvantage / rollSpellAttack / effectiveSpellRange):
  · Sharpshooter   — no Disadvantage at long range; no Disadvantage firing in melee (any ranged weapon).
  · Crossbow Expert — no Disadvantage firing in melee (Crossbows only); does NOT remove long-range.
  · Spell Sniper   — no Disadvantage casting a spell in melee; +60 ft range on attack-roll spells.

Bonus-attack:
  · Great Weapon Master — Hew: a melee crit/kill with a Heavy weapon arms a bonus-action attack
    (gwm_hew_available, consumed via the shared extra-attack flow in the GUI).
  · Dual Wielder — +1 AC while wielding a melee weapon in each hand.

Deferred (known_limitations.md): Polearm Master (Pole Strike butt-end weapon + Reactive Strike window);
Crossbow Expert Ignore-Loading / off-hand damage mod (already free in this engine); GWM Hew mid-action
sequencing.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_feats import _place, _target, _land_hit, _arm


# ─────────────────────────────────────────────────────────────────────────────
#  Weapon builders
# ─────────────────────────────────────────────────────────────────────────────

def _ranged(name="Shortbow", normal=10, long=120, die=6):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Ranged
    w.normal_range_ft = normal
    w.long_range_ft = long
    w.proficient = True
    w.bonus_hit = 50            # always lands (we only inspect r.disadvantage)
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _melee(name="Greatsword", dmg=rpg.PhysicalDamage.Slashing, die=12, heavy=True, bonus_hit=50):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.heavy = heavy
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = dmg
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _arm_ranged(engine, bm, idx, weapon, feats=None):
    s = engine.get_agent_stats(bm, idx)
    s.dex = 14
    s.prof_bonus = 2
    s.hp_max = 80; s.hp_cur = 80
    for f in (feats or []):
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [weapon, rpg.Weapon(), rpg.Weapon()])


def _disadvantage(engine, bm, a, t, weapon_idx=0):
    """Fire once and report whether the resolved attack had Disadvantage."""
    r = engine.execute_action(bm, rpg.Attack(a, t, weapon_idx))
    return r.disadvantage


# ─────────────────────────────────────────────────────────────────────────────
#  Sharpshooter
# ─────────────────────────────────────────────────────────────────────────────

def test_sharpshooter_ignores_long_range_disadvantage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Archer", 2, 5)
    t = _place(engine, bm, "Tgt", 7, 5)               # 5 cells = 25 ft, beyond the 10 ft normal range
    _target(engine, bm, t)

    _arm_ranged(engine, bm, a, _ranged(normal=10, long=120))   # no feat
    assert _disadvantage(engine, bm, a, t), "long-range shot is normally at Disadvantage"

    _arm_ranged(engine, bm, a, _ranged(normal=10, long=120), feats=["Sharpshooter"])
    assert not _disadvantage(engine, bm, a, t), "Sharpshooter removes long-range Disadvantage"
    print("✅ test_sharpshooter_ignores_long_range_disadvantage passed")


def test_sharpshooter_firing_in_melee():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Archer", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)               # adjacent → within range AND threatens the archer
    _target(engine, bm, t)

    _arm_ranged(engine, bm, a, _ranged(normal=80, long=320))   # no feat, well within normal range
    assert _disadvantage(engine, bm, a, t), "a ranged attack with an enemy in melee is at Disadvantage"

    _arm_ranged(engine, bm, a, _ranged(normal=80, long=320), feats=["Sharpshooter"])
    assert not _disadvantage(engine, bm, a, t), "Sharpshooter ignores the firing-in-melee Disadvantage"
    print("✅ test_sharpshooter_firing_in_melee passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Crossbow Expert
# ─────────────────────────────────────────────────────────────────────────────

def test_crossbow_expert_firing_in_melee_with_crossbow():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Shooter", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _target(engine, bm, t)

    _arm_ranged(engine, bm, a, _ranged("Light Crossbow", normal=80, long=320))
    assert _disadvantage(engine, bm, a, t), "no feat → firing in melee is at Disadvantage"

    _arm_ranged(engine, bm, a, _ranged("Light Crossbow", normal=80, long=320), feats=["Crossbow Expert"])
    assert not _disadvantage(engine, bm, a, t), "Crossbow Expert removes firing-in-melee Disadvantage with a Crossbow"
    print("✅ test_crossbow_expert_firing_in_melee_with_crossbow passed")


def test_crossbow_expert_only_helps_crossbows():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Shooter", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _target(engine, bm, t)

    # Crossbow Expert with a NON-crossbow ranged weapon → no firing-in-melee benefit.
    _arm_ranged(engine, bm, a, _ranged("Shortbow", normal=80, long=320), feats=["Crossbow Expert"])
    assert _disadvantage(engine, bm, a, t), "Crossbow Expert does not help a Shortbow"
    print("✅ test_crossbow_expert_only_helps_crossbows passed")


def test_crossbow_expert_does_not_remove_long_range():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Shooter", 2, 5)
    t = _place(engine, bm, "Tgt", 7, 5)               # 25 ft, beyond normal 10 ft, no melee threat
    _target(engine, bm, t)

    _arm_ranged(engine, bm, a, _ranged("Hand Crossbow", normal=10, long=120), feats=["Crossbow Expert"])
    assert _disadvantage(engine, bm, a, t), "Crossbow Expert does NOT remove long-range Disadvantage (Sharpshooter only)"
    print("✅ test_crossbow_expert_does_not_remove_long_range passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Spell Sniper
# ─────────────────────────────────────────────────────────────────────────────

def _firebolt(rng=120):
    sp = rpg.Spell()
    sp.name = "Fire Bolt"
    sp.level = 0
    sp.attack_type = rpg.SpellAttack.AttackRoll
    sp.geometry = rpg.SpellGeometry.Single
    sp.range = rng
    sp.num_targets = 1
    d = rpg.MagicDamageRoll(); d.type = rpg.MagicDamage.Fire; d.num_dice = 1; d.die_size = 10; d.bonus = 0
    sp.magic_damage_rolls = [d]
    return sp


def test_spell_sniper_extends_attack_spell_range():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Caster", 5, 5)
    sp = _firebolt(rng=120)

    s = engine.get_agent_stats(bm, a)
    base = engine.effective_spell_range(bm, a, sp)
    assert base == 120, f"no feat → range unchanged, got {base}"

    s.add_feat("Spell Sniper"); engine.set_agent_stats(bm, a, s)
    assert engine.effective_spell_range(bm, a, sp) == 180, "Spell Sniper adds +60 ft to an attack-roll spell"
    print("✅ test_spell_sniper_extends_attack_spell_range passed")


def test_spell_sniper_no_range_bonus_for_save_or_touch_spells():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Caster", 5, 5)
    s = engine.get_agent_stats(bm, a); s.add_feat("Spell Sniper"); engine.set_agent_stats(bm, a, s)

    save_spell = _firebolt(rng=120); save_spell.attack_type = rpg.SpellAttack.Save
    assert engine.effective_spell_range(bm, a, save_spell) == 120, "no bonus for a save spell"

    touch = _firebolt(rng=5)        # below the 10 ft floor (Touch/Self)
    assert engine.effective_spell_range(bm, a, touch) == 5, "no bonus for a Touch/Self spell"
    print("✅ test_spell_sniper_no_range_bonus_for_save_or_touch_spells passed")


def test_spell_sniper_firing_in_melee_raises_mean_d20():
    """Statistical: casting Fire Bolt at an adjacent enemy is normally at Disadvantage (mean d20 ≈ 7.2).
    Spell Sniper removes it (mean d20 ≈ 10.5). Compare sample means — the gap dwarfs sampling noise."""
    N = 300

    def mean_d20(feat):
        bm = setup_battle_map(); engine = setup_combat_engine()
        a = _place(engine, bm, "Caster", 5, 5)
        t = _place(engine, bm, "Tgt", 6, 5)            # adjacent → threatens the caster
        engine.set_agent_spells(bm, a, [_firebolt()])
        s = engine.get_agent_stats(bm, a)
        s.intel = 16; s.spellcasting_ability = 3; s.prof_bonus = 2
        s.spell_slots_remaining = [9, 9, 9, 9, 9, 0, 0, 0, 0]
        if feat:
            s.add_feat(feat)
        engine.set_agent_stats(bm, a, s)
        ts = engine.get_agent_stats(bm, t); ts.base_ac = 30; ts.hp_max = ts.hp_cur = 10_000
        engine.set_agent_stats(bm, t, ts)
        act = rpg.SpellAction(); act.caster_idx = a; act.spell_idx = 0; act.target_indices = [t]
        tot = 0
        for _ in range(N):
            res = engine.execute_spell(bm, act)
            tot += res.target_results[0].d20
        return tot / N

    without = mean_d20(None)
    with_feat = mean_d20("Spell Sniper")
    assert with_feat > without + 1.5, \
        f"Spell Sniper should raise mean d20 (no disadvantage): without={without:.2f}, with={with_feat:.2f}"
    print(f"✅ test_spell_sniper_firing_in_melee_raises_mean_d20 passed (without={without:.2f}, with={with_feat:.2f})")


# ─────────────────────────────────────────────────────────────────────────────
#  Great Weapon Master — Hew (bonus-attack arming flag)
# ─────────────────────────────────────────────────────────────────────────────

def _force_crit(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx); s.crit_threshold = 1; engine.set_agent_stats(bm, idx, s)


def test_gwm_hew_armed_on_crit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Greatsword", die=12, heavy=True)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=10_000)
    _force_crit(engine, bm, a)

    engine.execute_action(bm, rpg.Attack(a, t, 0))     # guaranteed crit
    assert engine.get_agent_conditions(bm, a).gwm_hew_available, "a Heavy-weapon crit arms GWM Hew"
    print("✅ test_gwm_hew_armed_on_crit passed")


def test_gwm_hew_armed_on_kill():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Greataxe", die=12, heavy=True)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=1)                        # any hit drops it to 0
    _land_hit(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).gwm_hew_available, "reducing a creature to 0 HP arms GWM Hew"
    print("✅ test_gwm_hew_armed_on_kill passed")


def test_gwm_hew_not_armed_on_plain_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Greatsword", die=12, heavy=True)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=10_000)                  # survives, no crit
    s = engine.get_agent_stats(bm, a); s.crit_threshold = 20; engine.set_agent_stats(bm, a, s)
    # A normal (non-crit, non-kill) hit must not arm Hew.
    for _ in range(30):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit and not r.critical:
            assert not engine.get_agent_conditions(bm, a).gwm_hew_available, \
                "a plain hit (no crit, no kill) does not arm Hew"
            print("✅ test_gwm_hew_not_armed_on_plain_hit passed")
            return
    raise AssertionError("no non-crit hit landed")


def test_gwm_hew_not_armed_without_heavy():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Longsword", die=8, heavy=False)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=10_000)
    _force_crit(engine, bm, a)
    engine.execute_action(bm, rpg.Attack(a, t, 0))     # crit, but non-Heavy weapon
    assert not engine.get_agent_conditions(bm, a).gwm_hew_available, "Hew requires a Heavy weapon"
    print("✅ test_gwm_hew_not_armed_without_heavy passed")


def test_gwm_hew_not_armed_on_bonus_action():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Greatsword", die=12, heavy=True)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=10_000)
    _force_crit(engine, bm, a)
    atk = rpg.Attack(a, t, 0); atk.attack_slot = "bonus"
    engine.execute_action(bm, atk)                     # crit, but a bonus-action attack
    assert not engine.get_agent_conditions(bm, a).gwm_hew_available, \
        "Hew triggers only as part of the Attack action, not a bonus-action attack"
    print("✅ test_gwm_hew_not_armed_on_bonus_action passed")


def test_gwm_hew_clears_at_turn_start():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_melee("Greatsword", die=12, heavy=True)], feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t, hp=10_000)
    _force_crit(engine, bm, a)
    engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert engine.get_agent_conditions(bm, a).gwm_hew_available
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, a).gwm_hew_available, "Hew availability resets at turn start"
    print("✅ test_gwm_hew_clears_at_turn_start passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Dual Wielder — +1 AC with two melee weapons
# ─────────────────────────────────────────────────────────────────────────────

def _shield_item():
    w = rpg.Weapon()
    w.name = "Shield"
    w.type = rpg.WeaponType.Melee
    w.is_shield = True
    w.ac_bonus = 2
    return w


def test_dual_wielder_ac_with_two_melee_weapons():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fighter", 5, 5)
    s = engine.get_agent_stats(bm, a); s.base_ac = 12; engine.set_agent_stats(bm, a, s)
    twin = [_melee("Shortsword", die=6, heavy=False), _melee("Shortsword", die=6, heavy=False), rpg.Weapon()]
    engine.set_agent_weapons(bm, a, twin)

    base = engine.calculate_ac(bm, a)
    s = engine.get_agent_stats(bm, a); s.add_feat("Dual Wielder"); engine.set_agent_stats(bm, a, s)
    assert engine.calculate_ac(bm, a) == base + 1, "Dual Wielder grants +1 AC while wielding two melee weapons"
    print("✅ test_dual_wielder_ac_with_two_melee_weapons passed")


def test_dual_wielder_no_ac_with_single_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fighter", 5, 5)
    s = engine.get_agent_stats(bm, a); s.base_ac = 12; s.add_feat("Dual Wielder")
    engine.set_agent_stats(bm, a, s)
    # One melee weapon + empty off-hand → no bonus.
    engine.set_agent_weapons(bm, a, [_melee("Greatsword", die=12), rpg.Weapon(), rpg.Weapon()])
    base = engine.calculate_ac(bm, a)
    s2 = engine.get_agent_stats(bm, a)
    # Compare against the same loadout without the feat by removing it.
    s2.feats = [f for f in s2.feats if f != "Dual Wielder"]
    engine.set_agent_stats(bm, a, s2)
    assert engine.calculate_ac(bm, a) == base, "Dual Wielder gives no AC with only one melee weapon"
    print("✅ test_dual_wielder_no_ac_with_single_weapon passed")


def test_dual_wielder_no_ac_with_shield_offhand():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fighter", 5, 5)
    s = engine.get_agent_stats(bm, a); s.base_ac = 12; s.add_feat("Dual Wielder")
    engine.set_agent_stats(bm, a, s)
    # Weapon + Shield in the off-hand → the off-hand is not a melee weapon, so no Dual Wielder +1
    # (the Shield's own +2 AC still applies via calculateAC's shield scan).
    engine.set_agent_weapons(bm, a, [_melee("Longsword", die=8), _shield_item(), rpg.Weapon()])
    with_shield = engine.calculate_ac(bm, a)
    s2 = engine.get_agent_stats(bm, a); s2.feats = [f for f in s2.feats if f != "Dual Wielder"]
    engine.set_agent_stats(bm, a, s2)
    assert engine.calculate_ac(bm, a) == with_shield, "a Shield in the off-hand does not grant the Dual Wielder bonus"
    print("✅ test_dual_wielder_no_ac_with_shield_offhand passed")


def main():
    print("Running General feat tests (G4 — bonus-attack + ranged-penalty)...\n")
    test_sharpshooter_ignores_long_range_disadvantage()
    test_sharpshooter_firing_in_melee()
    test_crossbow_expert_firing_in_melee_with_crossbow()
    test_crossbow_expert_only_helps_crossbows()
    test_crossbow_expert_does_not_remove_long_range()
    test_spell_sniper_extends_attack_spell_range()
    test_spell_sniper_no_range_bonus_for_save_or_touch_spells()
    test_spell_sniper_firing_in_melee_raises_mean_d20()
    test_gwm_hew_armed_on_crit()
    test_gwm_hew_armed_on_kill()
    test_gwm_hew_not_armed_on_plain_hit()
    test_gwm_hew_not_armed_without_heavy()
    test_gwm_hew_not_armed_on_bonus_action()
    test_gwm_hew_clears_at_turn_start()
    test_dual_wielder_ac_with_two_melee_weapons()
    test_dual_wielder_no_ac_with_single_weapon()
    test_dual_wielder_no_ac_with_shield_offhand()
    print("\n" + "=" * 60)
    print("✅ All General feat (G4) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
