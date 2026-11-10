#!/usr/bin/env python3
"""Ravenloft items RI1 — the data-only catalog entries (plans/RAVENLOFT_ITEMS_PLAN.md).

Every new weapons.json / armor.json / items.json record parses into its engine object; each
base weapon has a `<Weapon> (Vicious)` variant carrying an extra 2d6 of its own damage type
(Q8); the Staff of Power's pool of 10 gates each spell by its charge cost; the Helm of
Brilliance grants its four spells at 3/day and 1/day, cast at DC 18 without a slot.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_armor, _dict_to_item, _dict_to_weapon, item_spell_entries

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return json.load(f)


WEAPONS = {r["name"]: r for r in _load("weapons.json")}
ARMOR = {r["name"]: r for r in _load("armor.json")}
ITEMS = {r["name"]: r for r in _load("items.json")}
SPELLS = {r["name"]: r for r in _load("spells.json")}

_NON_BASE = {"Shield", "Mace of Terror", "UnarmedFire", "UnarmedStunningFire", "MonkUnarmed",
             "BrownBearBite", "GiantSpiderBite"}
_NEW_WEAPONS = ["Shield of Initiative +2", "Saint Markovia's Thighbone", "Staff of Power",
                "Luck Blade (Longsword)", "Sunsword", "Yarik's Shortsword"]


def _base_weapons():
    return [n for n in WEAPONS
            if "+" not in n and "(" not in n and n not in _NON_BASE and n not in _NEW_WEAPONS]


def _board(slots=None):
    """Caster at (5,5): own DC 10. A WIS/DEX-1 foe at (6,5)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 8, 5), wis=1, dex=1, hp=500)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    s.spellcasting_ability = 4
    s.prof_bonus = 2
    s.spell_slots_max = list(slots or [0] * 9)
    s.spell_slots_remaining = list(slots or [0] * 9)
    engine.set_agent_stats(bm, caster, s)
    return bm, engine, caster, foe


def _grant(engine, bm, idx):
    entries = item_spell_entries(engine, bm, idx, SPELLS)
    engine.set_agent_spells(bm, idx, entries)
    return entries


def _castable(engine, bm, idx):
    spells = engine.get_agent_spells(bm, idx)
    return sorted(spells[i].name for i in engine.available_castable_spells(bm, idx))


# ── Parsing ───────────────────────────────────────────────────────────────────
def test_new_weapons_parse():
    for name in _NEW_WEAPONS:
        assert name in WEAPONS, f"{name} missing from weapons.json"
        assert WEAPONS[name].get("description"), f"{name} has no description"
        w = _dict_to_weapon(WEAPONS[name])
        assert w.name == name

    shield = _dict_to_weapon(WEAPONS["Shield of Initiative +2"])
    assert shield.is_shield and shield.ac_bonus == 4, "+2 on top of the shield's own +2"

    bone = _dict_to_weapon(WEAPONS["Saint Markovia's Thighbone"])
    assert bone.mastery == rpg.WeaponMastery.Sap
    assert bone.item_spells.requires_attunement
    assert [(r.type, r.num_dice, r.die_size) for r in bone.physical_damage_types] == \
        [(rpg.PhysicalDamage.Bludgeoning, 1, 6)]

    staff = _dict_to_weapon(WEAPONS["Staff of Power"])
    assert (staff.bonus_hit, staff.bonus_damage) == (2, 2)
    assert staff.mastery == rpg.WeaponMastery.Topple
    assert staff.item_spells.charges_max == 10 and staff.item_spells.charges == 10
    assert staff.item_spells.requires_attunement

    luck = _dict_to_weapon(WEAPONS["Luck Blade (Longsword)"])
    assert (luck.bonus_hit, luck.bonus_damage) == (1, 1)
    assert luck.item_spells.requires_attunement

    sun = _dict_to_weapon(WEAPONS["Sunsword"])
    assert (sun.bonus_hit, sun.bonus_damage) == (2, 2) and sun.finesse
    assert sun.mastery == rpg.WeaponMastery.Sap
    assert list(sun.physical_damage_types) == [], "Radiant instead of Slashing"
    r0 = sun.magic_damage_types[0]
    assert (r0.type, r0.num_dice, r0.die_size) == (rpg.MagicDamage.Radiant, 1, 8)
    assert sun.item_spells.requires_attunement

    yarik = _dict_to_weapon(WEAPONS["Yarik's Shortsword"])
    assert (yarik.bonus_hit, yarik.bonus_damage) == (1, 1) and yarik.finesse and yarik.light
    print("✅ test_new_weapons_parse")


def test_every_base_weapon_has_a_vicious_variant():
    base = _base_weapons()
    assert len(base) == 38, base
    for name in base:
        vname = f"{name} (Vicious)"
        assert vname in WEAPONS, f"no {vname}"
        rec, vrec = WEAPONS[name], WEAPONS[vname]
        own = rec["physical_damage_types"][0]["type"]
        assert vrec["physical_damage_types"] == rec["physical_damage_types"] + \
            [{"type": own, "num_dice": 2, "die_size": 6}], vname
        for k in ("mastery", "finesse", "light", "heavy", "thrown", "reach_ft",
                  "normal_range_ft", "long_range_ft", "bonus_hit", "bonus_damage"):
            assert vrec.get(k) == rec.get(k), f"{vname}.{k} differs from {name}"
        w = _dict_to_weapon(vrec)
        assert len(w.physical_damage_types) == len(rec["physical_damage_types"]) + 1
    print("✅ test_every_base_weapon_has_a_vicious_variant")


def test_vicious_hit_rolls_the_extra_dice():
    bm, engine = setup_battle_map(), setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 5, 5), str=10, hp=40)
    t = add_agent_to_battle(engine, bm, create_test_agent("T", 6, 5), hp=500, ac=1)
    weapons = engine.get_agent_weapons(bm, a)
    weapons[0] = _dict_to_weapon(WEAPONS["Longsword (Vicious)"])
    engine.set_agent_weapons(bm, a, weapons)
    hits = 0
    for _ in range(40):
        engine.begin_turn(bm, a)
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit and not r.critical:
            hits += 1
            assert len(r.dice_results) == 3, "1d8 + 2d6"
            assert 3 <= r.total_damage <= 20
    assert hits > 0
    print("✅ test_vicious_hit_rolls_the_extra_dice")


def test_helm_and_holy_symbol_parse():
    helm = _dict_to_armor(ARMOR["Helm of Brilliance"])
    assert helm.description
    assert helm.magic_damage_multipliers[int(rpg.MagicDamage.Fire)] == 0.5, "Fire resistance"
    s = helm.item_spells
    assert s.requires_attunement and s.spell_dc == 18
    assert {n: s.uses_per_day(n) for n in s.spell_names()} == \
        {"Daylight": 3, "Fireball": 3, "Prismatic Spray": 1, "Wall of Fire": 1}

    sym = _dict_to_item(ITEMS["Holy Symbol of Ravenkind"])
    assert sym.type == rpg.ItemType.Wondrous and not sym.consumable
    assert sym.item_spells.requires_attunement and sym.item_spells.charges_max == 10
    assert sym.description
    print("✅ test_helm_and_holy_symbol_parse")


# ── Staff of Power: the pool gates by cost ────────────────────────────────────
def test_staff_pool_costs_gate():
    bm, engine, caster, foe = _board()
    staff = _dict_to_weapon(WEAPONS["Staff of Power"])
    staff.item_spells.attuned = True
    weapons = engine.get_agent_weapons(bm, caster)
    weapons[0] = staff
    engine.set_agent_weapons(bm, caster, weapons)
    entries = _grant(engine, bm, caster)
    costs = {sp.name: sp.item_charge_cost for sp in entries}
    assert costs == {"Magic Missile": 1, "Ray of Enfeeblement": 1, "Levitate": 2,
                     "Cone of Cold": 5, "Fireball": 5, "Hold Monster": 5, "Lightning Bolt": 5,
                     "Wall of Force": 5, "Globe of Invulnerability": 6}, costs
    assert len(_castable(engine, bm, caster)) == 9, "10 charges pay for everything"

    for charges, expect in ((5, 8), (4, 3), (1, 2), (0, 0)):
        weapons = engine.get_agent_weapons(bm, caster)
        weapons[0].item_spells.charges = charges
        engine.set_agent_weapons(bm, caster, weapons)
        got = _castable(engine, bm, caster)
        assert len(got) == expect, f"{charges} charges → {got}"
    print("✅ test_staff_pool_costs_gate")


def test_staff_unattuned_grants_nothing():
    bm, engine, caster, _ = _board()
    weapons = engine.get_agent_weapons(bm, caster)
    weapons[0] = _dict_to_weapon(WEAPONS["Staff of Power"])
    engine.set_agent_weapons(bm, caster, weapons)
    assert _grant(engine, bm, caster) == []
    print("✅ test_staff_unattuned_grants_nothing")


# ── Helm of Brilliance: uses/day and DC 18 ────────────────────────────────────
def test_helm_uses_per_day_and_dc():
    bm, engine, caster, foe = _board()
    armor = list(engine.get_agent_armor(bm, caster))
    helm = _dict_to_armor(ARMOR["Helm of Brilliance"])
    helm.item_spells.attuned = True
    armor[0] = helm
    engine.set_agent_armor(bm, caster, armor)
    _grant(engine, bm, caster)
    assert _castable(engine, bm, caster) == ["Daylight", "Fireball", "Prismatic Spray",
                                             "Wall of Fire"], "no slots needed"

    spells = engine.get_agent_spells(bm, caster)
    fb = next(i for i, sp in enumerate(spells) if sp.name == "Fireball")
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = caster, fb, 0
    a.target_indices = [foe]
    a.aoe_col, a.aoe_row = 8, 5
    res = engine.execute_spell(bm, a)
    assert res.valid
    by = {t.target_idx: t for t in res.target_results}
    assert by[foe].save_dc == 18, f"the helm's DC 18, not the holder's 10 ({by[foe].save_dc})"
    uses = engine.get_agent_armor(bm, caster)[0].item_spells.uses_remaining
    assert uses["Fireball"] == 2 and uses["Daylight"] == 3 and uses["Wall of Fire"] == 1
    st = engine.get_agent_stats(bm, caster)
    assert list(st.spell_slots_remaining) == [0] * 9
    print("✅ test_helm_uses_per_day_and_dc")


if __name__ == "__main__":
    test_new_weapons_parse()
    test_every_base_weapon_has_a_vicious_variant()
    test_vicious_hit_rolls_the_extra_dice()
    test_helm_and_holy_symbol_parse()
    test_staff_pool_costs_gate()
    test_staff_unattuned_grants_nothing()
    test_helm_uses_per_day_and_dc()
    print("\nAll Ravenloft items RI1 tests passed!")
