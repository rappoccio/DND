#!/usr/bin/env python3
"""Ravenloft items RI2 — M1 passive item bonuses (plans/RAVENLOFT_ITEMS_PLAN.md).

`item_bonuses` on a carried item adds to AC, Initiative, saving throws, spell attack rolls
and spell save DCs while the item is carried and, when it requires attunement, attuned:
the Shield of Initiative's +2 Initiative, the Staff of Power's +2 AC / saves / spell attack,
the Luck Blade's +1 saves, and the Rod of the Pact Keeper's +N Warlock spell attack and DC
(Warlocks only, and not on a spell cast from another item). Bonuses round-trip through the
save dicts, and an attunement-only item (the Sunsword) keeps its Attuned tick too.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_item, _dict_to_spell, _dict_to_weapon, _item_to_dict,
                     _weapon_to_dict, item_spell_entries, item_spells_summary)

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return {r["name"]: r for r in json.load(f)}


WEAPONS, ITEMS, SPELLS = _load("weapons.json"), _load("items.json"), _load("spells.json")


def _board():
    """Holder at (5,5) (PC, all scores 10, prof 2: own DC 10, spell attack +2) and a foe at
    (6,5) with the same numbers."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    h = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=200)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), hp=200)
    bm.set_agent_faction(h, 1)
    bm.set_agent_faction(foe, 2)
    for i in (h, foe):
        s = engine.get_agent_stats(bm, i)
        s.can_cast_spell = True
        s.spellcasting_ability = 5          # CHA 10 → +0
        s.prof_bonus = 2
        engine.set_agent_stats(bm, i, s)
    return bm, engine, h, foe


def _make_warlock(engine, bm, idx, level=5):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    s.spellcasting_ability = 5
    s.prof_bonus = 2
    engine.set_agent_stats(bm, idx, s)


def _wield(engine, bm, idx, name, slot=0, attuned=True):
    w = _dict_to_weapon(WEAPONS[name])
    w.item_spells.attuned = attuned
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[slot] = w
    engine.set_agent_weapons(bm, idx, weapons)


def _carry(engine, bm, idx, name, attuned=True):
    it = _dict_to_item(ITEMS[name])
    it.item_spells.attuned = attuned
    engine.set_agent_items(bm, idx, list(engine.get_agent_items(bm, idx)) + [it])


def _set_spells(engine, bm, idx, names):
    engine.set_agent_spells(bm, idx, [_dict_to_spell(SPELLS[n]) for n in names])


def _cast_at(engine, bm, caster, spell_idx, target):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = caster, spell_idx, 0
    a.target_indices = [target]
    res = engine.execute_spell(bm, a)
    assert res.valid
    return {t.target_idx: t for t in res.target_results}[target]


def _init_mod(engine, bm, idx):
    return next(e.modifier for e in engine.roll_initiative(bm) if e.agent_idx == idx)


# ── Shield of Initiative ──────────────────────────────────────────────────────
def test_shield_of_initiative():
    bm, engine, h, _ = _board()
    assert engine.calculate_ac(bm, h) == 10 and _init_mod(engine, bm, h) == 0
    _wield(engine, bm, h, "Shield of Initiative +2", slot=1)
    assert engine.calculate_ac(bm, h) == 14, "the shield's +2 and its own +2"
    assert _init_mod(engine, bm, h) == 2
    assert engine.carried_item_bonuses(bm, h).initiative == 2
    print("✅ test_shield_of_initiative")


# ── Staff of Power ────────────────────────────────────────────────────────────
def test_staff_of_power_ac_saves_spell_attack():
    bm, engine, h, foe = _board()
    _set_spells(engine, bm, h, ["Fire Bolt"])
    _set_spells(engine, bm, foe, ["Toll the Dead"])
    base_ac = engine.calculate_ac(bm, h)
    base_save = engine.save_mod_for(bm, h, rpg.SaveAbility.SaveWis)
    assert _cast_at(engine, bm, h, 0, foe).attack_mod == 2

    _wield(engine, bm, h, "Staff of Power")
    b = engine.carried_item_bonuses(bm, h)
    assert (b.ac, b.saves, b.spell_attack, b.spell_dc) == (2, 2, 2, 0)
    assert engine.calculate_ac(bm, h) == base_ac + 2
    assert engine.save_mod_for(bm, h, rpg.SaveAbility.SaveWis) == base_save + 2
    assert _cast_at(engine, bm, h, 0, foe).attack_mod == 4, "own +2, staff +2"
    assert _cast_at(engine, bm, foe, 0, h).save_mod == base_save + 2, "a spell save takes it"
    print("✅ test_staff_of_power_ac_saves_spell_attack")


def test_unattuned_staff_gives_nothing():
    bm, engine, h, _ = _board()
    base_ac = engine.calculate_ac(bm, h)
    _wield(engine, bm, h, "Staff of Power", attuned=False)
    assert not engine.carried_item_bonuses(bm, h).any()
    assert engine.calculate_ac(bm, h) == base_ac
    print("✅ test_unattuned_staff_gives_nothing")


def test_npc_ac_takes_item_bonus():
    bm, engine, h, _ = _board()
    s = engine.get_agent_stats(bm, h)
    s.is_npc, s.base_ac = True, 15
    engine.set_agent_stats(bm, h, s)
    _wield(engine, bm, h, "Staff of Power")
    assert engine.calculate_ac(bm, h) == 17, "published AC 15 + the staff's +2"
    print("✅ test_npc_ac_takes_item_bonus")


# ── Luck Blade ────────────────────────────────────────────────────────────────
def test_luck_blade_saves():
    bm, engine, h, _ = _board()
    base = engine.save_mod_for(bm, h, rpg.SaveAbility.SaveDex)
    _wield(engine, bm, h, "Luck Blade (Longsword)", attuned=False)
    assert engine.save_mod_for(bm, h, rpg.SaveAbility.SaveDex) == base
    _wield(engine, bm, h, "Luck Blade (Longsword)")
    assert engine.save_mod_for(bm, h, rpg.SaveAbility.SaveDex) == base + 1
    print("✅ test_luck_blade_saves")


def test_bonuses_from_two_items_add_up():
    bm, engine, h, _ = _board()
    base = engine.save_mod_for(bm, h, rpg.SaveAbility.SaveCon)
    _wield(engine, bm, h, "Luck Blade (Longsword)", slot=0)
    _wield(engine, bm, h, "Staff of Power", slot=2)
    assert engine.save_mod_for(bm, h, rpg.SaveAbility.SaveCon) == base + 3
    print("✅ test_bonuses_from_two_items_add_up")


# ── Rod of the Pact Keeper ────────────────────────────────────────────────────
def test_rod_boosts_warlock_spells():
    for n in (1, 2, 3):
        bm, engine, h, foe = _board()
        _make_warlock(engine, bm, h)
        _set_spells(engine, bm, h, ["Toll the Dead", "Fire Bolt"])
        own_dc = _cast_at(engine, bm, h, 0, foe).save_dc
        own_atk = _cast_at(engine, bm, h, 1, foe).attack_mod
        _carry(engine, bm, h, f"Rod of the Pact Keeper +{n}")
        assert _cast_at(engine, bm, h, 0, foe).save_dc == own_dc + n
        assert _cast_at(engine, bm, h, 1, foe).attack_mod == own_atk + n
    print("✅ test_rod_boosts_warlock_spells")


def test_rod_needs_a_warlock_and_attunement():
    bm, engine, h, foe = _board()
    _set_spells(engine, bm, h, ["Toll the Dead"])
    own_dc = _cast_at(engine, bm, h, 0, foe).save_dc
    _carry(engine, bm, h, "Rod of the Pact Keeper +2")
    assert _cast_at(engine, bm, h, 0, foe).save_dc == own_dc, "not a Warlock"

    bm, engine, h, foe = _board()
    _make_warlock(engine, bm, h)
    _set_spells(engine, bm, h, ["Toll the Dead"])
    own_dc = _cast_at(engine, bm, h, 0, foe).save_dc
    _carry(engine, bm, h, "Rod of the Pact Keeper +2", attuned=False)
    assert _cast_at(engine, bm, h, 0, foe).save_dc == own_dc, "not attuned"
    print("✅ test_rod_needs_a_warlock_and_attunement")


def test_rod_skips_spells_cast_from_another_item():
    """The Staff's Hold Monster uses the holder's DC, but it is the staff's spell, not "your
    Warlock spell": the Rod's +2 stays out of it."""
    bm, engine, h, foe = _board()
    _make_warlock(engine, bm, h)
    _set_spells(engine, bm, h, ["Toll the Dead"])
    own_dc = _cast_at(engine, bm, h, 0, foe).save_dc
    _carry(engine, bm, h, "Rod of the Pact Keeper +2")
    _wield(engine, bm, h, "Staff of Power")
    spells = [_dict_to_spell(SPELLS["Toll the Dead"])] + item_spell_entries(engine, bm, h, SPELLS)
    engine.set_agent_spells(bm, h, spells)
    hm = next(i for i, sp in enumerate(spells) if sp.name == "Hold Monster")
    assert _cast_at(engine, bm, h, hm, foe).save_dc == own_dc
    assert _cast_at(engine, bm, h, 0, foe).save_dc == own_dc + 2
    print("✅ test_rod_skips_spells_cast_from_another_item")


# ── Round trip and display ────────────────────────────────────────────────────
def test_bonuses_and_attunement_round_trip():
    staff = _dict_to_weapon(WEAPONS["Staff of Power"])
    staff.item_spells.attuned = True
    back = _dict_to_weapon(_weapon_to_dict(staff))
    b = back.item_spells.bonuses
    assert (b.ac, b.saves, b.spell_attack) == (2, 2, 2) and back.item_spells.attuned

    sun = _dict_to_weapon(WEAPONS["Sunsword"])
    sun.item_spells.attuned = True
    assert _dict_to_weapon(_weapon_to_dict(sun)).item_spells.attuned, \
        "an attunement-only item keeps its tick"

    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +3"])
    d = _item_to_dict(rod)
    assert d["item_bonuses"] == {"spell_attack": 3, "spell_dc": 3, "spell_class": "Warlock"}
    assert _dict_to_item(d).item_spells.bonuses.spell_class == int(rpg.CharacterClass.Warlock)

    plain = _dict_to_weapon(WEAPONS["Longsword"])
    assert "item_bonuses" not in _weapon_to_dict(plain)
    assert "requires_attunement" not in _weapon_to_dict(plain), "a plain weapon stays plain"
    print("✅ test_bonuses_and_attunement_round_trip")


def test_summary_lines():
    staff = _dict_to_weapon(WEAPONS["Staff of Power"])
    lines = item_spells_summary(staff.item_spells)
    assert lines[0] == "+2 AC, +2 saves, +2 spell attack", lines
    assert any(l.startswith("charges 10/10") for l in lines)
    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +2"])
    assert item_spells_summary(rod.item_spells) == \
        ["+2 spell attack, +2 spell save DC (Warlock spells)", "slot regain ready"]
    shield = _dict_to_weapon(WEAPONS["Shield of Initiative +2"])
    assert item_spells_summary(shield.item_spells) == ["+2 Initiative"]
    print("✅ test_summary_lines")


if __name__ == "__main__":
    test_shield_of_initiative()
    test_staff_of_power_ac_saves_spell_attack()
    test_unattuned_staff_gives_nothing()
    test_npc_ac_takes_item_bonus()
    test_luck_blade_saves()
    test_bonuses_from_two_items_add_up()
    test_rod_boosts_warlock_spells()
    test_rod_needs_a_warlock_and_attunement()
    test_rod_skips_spells_cast_from_another_item()
    test_bonuses_and_attunement_round_trip()
    test_summary_lines()
    print("\nAll Ravenloft items RI2 tests passed!")
