#!/usr/bin/env python3
"""Ravenloft items RI3 — M2 weapon damage vs a creature type (plans/RAVENLOFT_ITEMS_PLAN.md).

A weapon damage entry may carry `vs_creature_types`: it is rolled only against those types.
The Sunsword deals 1d8 Radiant (instead of Slashing) and +1d8 Radiant against Undead; Saint
Markovia's Thighbone deals 1d6 Bludgeoning and +2d6 Radiant against Fiends and Undead. The
limit round-trips through the weapon dicts, and a plain weapon's entries stay unlimited.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_weapon, _weapon_to_dict

_GUI = os.path.join(_ROOT, "gui")
with open(os.path.join(_GUI, "weapons.json")) as f:
    WEAPONS = {r["name"]: r for r in json.load(f)}


def _hits(weapon_name, undead=False, fiend=False, tries=60):
    """Swing `weapon_name` at an AC-1 target until it lands non-critical hits; the results."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 5, 5), hp=40)
    t = add_agent_to_battle(engine, bm, create_test_agent("T", 6, 5), hp=5000, ac=1)
    s = engine.get_agent_stats(bm, t)
    s.is_undead, s.is_fiend = undead, fiend
    engine.set_agent_stats(bm, t, s)
    w = _dict_to_weapon(WEAPONS[weapon_name])
    w.item_spells.attuned = True
    weapons = engine.get_agent_weapons(bm, a)
    weapons[0] = w
    engine.set_agent_weapons(bm, a, weapons)
    out = []
    for _ in range(tries):
        engine.begin_turn(bm, a)
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit and not r.critical:
            out.append(r)
    assert out, "never hit"
    return out


def test_sunsword_extra_radiant_vs_undead():
    for r in _hits("Sunsword"):
        assert len(r.dice_results) == 1, "1d8 Radiant vs a living target"
        assert list(r.physical_damage_types) == []
        assert set(r.magic_damage_types) == {rpg.MagicDamage.Radiant}
    for r in _hits("Sunsword", undead=True):
        assert len(r.dice_results) == 2, "1d8 + 1d8 Radiant vs Undead"
        assert set(r.magic_damage_types) == {rpg.MagicDamage.Radiant}
        assert 4 <= r.total_damage <= 18, "2d8 + 2"
    print("✅ test_sunsword_extra_radiant_vs_undead")


def test_thighbone_extra_radiant_vs_fiend_or_undead():
    for r in _hits("Saint Markovia's Thighbone"):
        assert len(r.dice_results) == 1 and list(r.magic_damage_types) == []
    for kw in ({"undead": True}, {"fiend": True}):
        for r in _hits("Saint Markovia's Thighbone", **kw):
            assert len(r.dice_results) == 3, f"1d6 + 2d6 vs {kw}"
            assert rpg.MagicDamage.Radiant in list(r.magic_damage_types)
    print("✅ test_thighbone_extra_radiant_vs_fiend_or_undead")


def test_vs_creature_types_round_trip():
    sun = _dict_to_weapon(WEAPONS["Sunsword"])
    assert [r.vs_creature_mask for r in sun.magic_damage_types] == \
        [0, int(rpg.CreatureType.Undead)]
    d = _weapon_to_dict(sun)
    assert d["magic_damage_types"][1]["vs_creature_types"] == ["Undead"]
    assert "vs_creature_types" not in d["magic_damage_types"][0]

    bone = _weapon_to_dict(_dict_to_weapon(WEAPONS["Saint Markovia's Thighbone"]))
    assert sorted(bone["magic_damage_types"][0]["vs_creature_types"]) == ["Fiend", "Undead"]
    back = _dict_to_weapon(bone)
    assert back.magic_damage_types[0].vs_creature_mask == \
        int(rpg.CreatureType.Fiend) | int(rpg.CreatureType.Undead)

    plain = _weapon_to_dict(_dict_to_weapon(WEAPONS["Mace"]))
    assert all("vs_creature_types" not in e for e in plain["physical_damage_types"])
    print("✅ test_vs_creature_types_round_trip")


if __name__ == "__main__":
    test_sunsword_extra_radiant_vs_undead()
    test_thighbone_extra_radiant_vs_fiend_or_undead()
    test_vs_creature_types_round_trip()
    print("\nAll Ravenloft items RI3 tests passed!")
