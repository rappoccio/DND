#!/usr/bin/env python3
"""
Epic Boon tests — Phase E3 (SRD 5.2 p.88). See EPIC_BOONS_PLAN.md.

  · Boon of Spell Recall (Free Casting) — when a boon-holder spends a level 1-4 slot, roll 1d4;
      on a match with the slot level the slot is NOT expended. Wired into the single
      spend_spell_slot chokepoint (NPCs use the N/day system, so they never reach it).
  · Boon of the Night Spirit:
      - Merge with Shadows — a Bonus Action grants the Invisible condition while the holder stands
        in Dim Light/Darkness (apply_merge_with_shadows; ends when it next acts).
      - Shadowy Form — while in Dim/Dark, Resistance to all damage except Psychic and Radiant.
        Evaluated at damage time on the DEFENDER's current cell light, folded into the effective
        physical/magic damage multipliers.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target


# ─────────────────────────────────────────────────────────────────────────────
#  helpers
# ─────────────────────────────────────────────────────────────────────────────

def _phys_weapon(dtype=rpg.PhysicalDamage.Slashing, total=10):
    """A melee weapon that always lands (bonus_hit 50) and deals `total` physical damage of `dtype`
    deterministically (`total` × d1)."""
    w = rpg.Weapon()
    w.name = "Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = 50
    pr = rpg.PhysicalDamageRoll()
    pr.type = dtype
    pr.num_dice = total
    pr.die_size = 1
    w.physical_damage_types = [pr]
    return w


def _magic_weapon(dtype, total=10):
    """A melee weapon that always lands and deals `total` magic damage of `dtype` (`total` × d1)."""
    w = rpg.Weapon()
    w.name = "Beam"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = 50
    mr = rpg.MagicDamageRoll()
    mr.type = dtype
    mr.num_dice = total
    mr.die_size = 1
    w.magic_damage_types = [mr]
    return w


def _plain_attacker(engine, bm, idx, feats=None):
    """A STR-10 (no damage mod) attacker so a hit's damage is exactly the weapon dice."""
    s = engine.get_agent_stats(bm, idx)
    s.str = 10; s.dex = 10; s.prof_bonus = 2
    s.hp_max = 80; s.hp_cur = 80
    s.is_npc = False
    for f in (feats or []):
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)


def _night_spirit_target(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = 1_000_000; s.hp_cur = 1_000_000
    s.base_ac = 10
    s.add_feat("Boon of the Night Spirit")
    engine.set_agent_stats(bm, idx, s)


def _dim(bm, col, row):
    """Make the given cell Dim Light. set_light_level writes the base light layer that get_light_level
    reads directly (place_light_effect only drives that layer for MagicalDark/HeavilyObscured)."""
    bm.set_light_level(rpg.Cell(col, row), rpg.VisibilityLevel.Dim)


def _noncrit_damage(engine, bm, a, t, tries=80):
    """Land a non-critical hit and return its total_damage (crits double the dice → skip them so the
    deterministic d1 dice stay exact)."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit and not r.critical:
            return r.total_damage
    raise AssertionError("no non-crit hit landed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Spell Recall — Free Casting
# ─────────────────────────────────────────────────────────────────────────────

def test_spell_recall_retains_some_low_slots():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sage", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.is_npc = False
    s.add_feat("Boon of Spell Recall")
    slots = list(s.spell_slots_remaining)
    slots[1] = 100_000                                   # a huge stack of level-2 slots
    s.spell_slots_remaining = slots
    engine.set_agent_stats(bm, a, s)

    N = 2000
    for _ in range(N):
        assert engine.spend_spell_slot(bm, a, 2), "a slot is available, so the cast always resolves"
    remaining = engine.get_agent_stats(bm, a).spell_slots_remaining[1]
    retained = remaining - (100_000 - N)                 # calls that did NOT decrement the slot
    # 1d4 == 2 lands ~1/4 of the time; a wide band keeps the statistical test from flaking.
    assert 0.15 * N < retained < 0.35 * N, \
        f"Free Casting should retain ~1/4 of level-2 casts, got {retained}/{N}"
    print(f"✅ test_spell_recall_retains_some_low_slots passed (retained {retained}/{N})")


def test_spell_recall_high_slot_never_retained():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sage", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.is_npc = False
    s.add_feat("Boon of Spell Recall")
    slots = list(s.spell_slots_remaining)
    slots[4] = 1000                                      # level-5 slots (outside the 1-4 window)
    s.spell_slots_remaining = slots
    engine.set_agent_stats(bm, a, s)

    for _ in range(500):
        engine.spend_spell_slot(bm, a, 5)
    remaining = engine.get_agent_stats(bm, a).spell_slots_remaining[4]
    assert remaining == 500, f"level-5 slots are never retained (Free Casting is 1-4 only), got {remaining}"
    print("✅ test_spell_recall_high_slot_never_retained passed")


def test_spell_recall_requires_boon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sage", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.is_npc = False                                     # no boon
    slots = list(s.spell_slots_remaining)
    slots[0] = 1000
    s.spell_slots_remaining = slots
    engine.set_agent_stats(bm, a, s)

    for _ in range(500):
        engine.spend_spell_slot(bm, a, 1)
    remaining = engine.get_agent_stats(bm, a).spell_slots_remaining[0]
    assert remaining == 500, f"without the boon every slot is spent, got {remaining}"
    print("✅ test_spell_recall_requires_boon passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of the Night Spirit — Merge with Shadows
# ─────────────────────────────────────────────────────────────────────────────

def test_merge_with_shadows_grants_invisible_in_dim():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Nightwalker", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.add_feat("Boon of the Night Spirit")
    engine.set_agent_stats(bm, a, s)
    _dim(bm, 5, 5)

    assert engine.apply_merge_with_shadows(bm, a), "Merge with Shadows applies while in Dim Light"
    c = engine.get_agent_conditions(bm, a)
    assert c.invisible, "the holder gains the Invisible condition"
    assert not c.invisible_persists_on_action, "the Invisibility ends when the holder next acts"
    print("✅ test_merge_with_shadows_grants_invisible_in_dim passed")


def test_merge_with_shadows_requires_dim_or_dark():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Nightwalker", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.add_feat("Boon of the Night Spirit")
    engine.set_agent_stats(bm, a, s)
    # No dim/dark light placed → the cell is bright.
    assert not engine.apply_merge_with_shadows(bm, a), "Merge with Shadows fails in bright light"
    assert not engine.get_agent_conditions(bm, a).invisible
    print("✅ test_merge_with_shadows_requires_dim_or_dark passed")


def test_merge_with_shadows_requires_boon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Nightwalker", 5, 5)
    _dim(bm, 5, 5)
    assert not engine.apply_merge_with_shadows(bm, a), "a non-boon-holder can't Merge with Shadows"
    assert not engine.get_agent_conditions(bm, a).invisible
    print("✅ test_merge_with_shadows_requires_boon passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of the Night Spirit — Shadowy Form
# ─────────────────────────────────────────────────────────────────────────────

def test_shadowy_form_halves_physical_in_dim():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Striker", 5, 5)
    t = _place(engine, bm, "Shade", 6, 5)
    _plain_attacker(engine, bm, a)
    engine.set_agent_weapons(bm, a, [_phys_weapon(rpg.PhysicalDamage.Slashing, total=10)])
    _night_spirit_target(engine, bm, t)

    bright = _noncrit_damage(engine, bm, a, t)
    assert bright == 10, f"in bright light the boon-holder takes full damage, got {bright}"

    _dim(bm, 6, 5)                                       # the DEFENDER's cell is now Dim
    dim = _noncrit_damage(engine, bm, a, t)
    assert dim == 5, f"Shadowy Form halves B/P/S damage in Dim Light (10 → 5), got {dim}"
    print("✅ test_shadowy_form_halves_physical_in_dim passed")


def test_shadowy_form_halves_necrotic_but_not_radiant():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Striker", 5, 5)
    t = _place(engine, bm, "Shade", 6, 5)
    _plain_attacker(engine, bm, a)
    _night_spirit_target(engine, bm, t)
    _dim(bm, 6, 5)

    engine.set_agent_weapons(bm, a, [_magic_weapon(rpg.MagicDamage.Necrotic, total=10)])
    necrotic = _noncrit_damage(engine, bm, a, t)
    assert necrotic == 5, f"Shadowy Form halves Necrotic in Dim (10 → 5), got {necrotic}"

    engine.set_agent_weapons(bm, a, [_magic_weapon(rpg.MagicDamage.Radiant, total=10)])
    radiant = _noncrit_damage(engine, bm, a, t)
    assert radiant == 10, f"Shadowy Form does NOT resist Radiant, got {radiant}"
    print("✅ test_shadowy_form_halves_necrotic_but_not_radiant passed")


def test_shadowy_form_yields_to_irresistible_offense():
    """Overcome Defenses (attacker) beats Shadowy Form (defender): the attacker's B/P/S ignores the
    Resistance the boon would otherwise grant."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Striker", 5, 5)
    t = _place(engine, bm, "Shade", 6, 5)
    _plain_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"])
    engine.set_agent_weapons(bm, a, [_phys_weapon(rpg.PhysicalDamage.Slashing, total=10)])
    _night_spirit_target(engine, bm, t)
    _dim(bm, 6, 5)

    dmg = _noncrit_damage(engine, bm, a, t)
    assert dmg == 10, f"Overcome Defenses lifts the Shadowy-Form Resistance (full 10), got {dmg}"
    print("✅ test_shadowy_form_yields_to_irresistible_offense passed")


def test_shadowy_form_requires_the_boon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Striker", 5, 5)
    t = _place(engine, bm, "Mook", 6, 5)
    _plain_attacker(engine, bm, a)
    engine.set_agent_weapons(bm, a, [_phys_weapon(rpg.PhysicalDamage.Slashing, total=10)])
    _target(engine, bm, t, hp=1_000_000, ac=10)          # no boon
    _dim(bm, 6, 5)

    dmg = _noncrit_damage(engine, bm, a, t)
    assert dmg == 10, f"a non-boon-holder in Dim takes full damage, got {dmg}"
    print("✅ test_shadowy_form_requires_the_boon passed")


def main():
    print("Running Epic Boon (E3 — Spell Recall + Night Spirit) tests...\n")
    test_spell_recall_retains_some_low_slots()
    test_spell_recall_high_slot_never_retained()
    test_spell_recall_requires_boon()
    test_merge_with_shadows_grants_invisible_in_dim()
    test_merge_with_shadows_requires_dim_or_dark()
    test_merge_with_shadows_requires_boon()
    test_shadowy_form_halves_physical_in_dim()
    test_shadowy_form_halves_necrotic_but_not_radiant()
    test_shadowy_form_yields_to_irresistible_offense()
    test_shadowy_form_requires_the_boon()
    print("\n" + "=" * 60)
    print("✅ All Epic Boon (E3) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
