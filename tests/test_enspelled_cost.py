#!/usr/bin/env python3
"""Enspelled items E2 — engine cost path (plans/ENSPELLED_ITEMS_PLAN.md).

A spell tagged with its source item is paid for by that item's ItemSpells state, never by a
slot, for PCs and NPCs alike: a PC with no slots casts Fear from the Mace of Terror; its 2/day
run out; a charge pool gates each spell by its cost; at will never runs out; the item's DC 15 /
spell attack +7 replace the holder's (D1); item casts ignore the one-leveled-spell-per-turn rule
(D2) and cast at base level (D6); a long rest refills every carried item; and a Bard who knows
Fear keeps her own Fear and the mace's Fear independent.

E3 (the grant/revoke lifecycle) does not exist yet, so the tagged spells are built by hand here
the way that helper will build them.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_item, _dict_to_spell, _dict_to_weapon, _spell_to_dict

_GUI = os.path.join(_ROOT, "gui")
_catalogs = {}


def _catalog(fname, name):
    if fname not in _catalogs:
        with open(os.path.join(_GUI, fname)) as f:
            _catalogs[fname] = json.load(f)
    return next(r for r in _catalogs[fname] if r["name"] == name)


# A pool item (D4) plus an at-will attack spell for the D1 spell_attack check.
WAND = {
    "name": "Test Wand of Fire", "type": "Wondrous", "action_type": "NoAction",
    "range": 0, "quantity": 1, "consumable": False,
    "requires_attunement": True, "spell_attack": 7,
    "item_spell_groups": {"99": ["Fire Bolt"]},
    "charges": {"max": 4, "regain": "long_rest"},
    "charge_spells": {"1": ["Burning Hands"], "3": ["Fireball"]},
}


def _tagged(spell_name, source, slot, item_name, cost=0):
    """The Spell E3 will grant: the catalog record, tagged with the item that pays for it."""
    sp = _dict_to_spell(_catalog("spells.json", spell_name))
    sp.item_source, sp.item_slot, sp.item_name, sp.item_charge_cost = source, slot, item_name, cost
    return sp


def _board(npc=False, slots=None):
    """Caster at (5,5) whose own DC is 10 and spell attack +2; a WIS-1 foe at (6,5) who always
    fails a DC-15 WIS save (d20 − 5 ≤ 15) and a sturdy ally at (4,5)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), wis=1, hp=200)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 4, 5), hp=40)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    s.is_npc = npc
    s.spellcasting_ability = 4          # WIS 10 → +0; prof 2 ⇒ own DC 10, attack +2
    s.prof_bonus = 2
    s.spell_slots_max = list(slots or [0] * 9)
    s.spell_slots_remaining = list(slots or [0] * 9)
    engine.set_agent_stats(bm, caster, s)
    return bm, engine, caster, foe, ally


def _give_mace(engine, bm, idx, attuned=True):
    mace = _dict_to_weapon(_catalog("weapons.json", "Mace of Terror"))
    mace.item_spells.attuned = attuned
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[0] = mace
    engine.set_agent_weapons(bm, idx, weapons)


def _mace_state(engine, bm, idx):
    return engine.get_agent_weapons(bm, idx)[0].item_spells


def _give_item(engine, bm, idx, record, attuned=True):
    it = _dict_to_item(record)
    it.item_spells.attuned = attuned
    items = list(engine.get_agent_items(bm, idx)) + [it]
    engine.set_agent_items(bm, idx, items)
    return len(items) - 1


def _item_state(engine, bm, idx, slot):
    return engine.get_agent_items(bm, idx)[slot].item_spells


def _cast(engine, bm, caster, spell_idx, targets, slot_level=0, aoe=None):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = caster, spell_idx, slot_level
    a.target_indices = list(targets)
    if aoe:
        a.aoe_col, a.aoe_row = aoe
    return engine.execute_spell(bm, a)


# ── Mace of Terror: N/day, PC with no slots ────────────────────────────────────
def test_pc_casts_fear_from_mace_without_slots():
    bm, engine, caster, foe, _ = _board()
    _give_mace(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromWeapon, 0,
                                                 "Mace of Terror")])
    assert engine.available_castable_spells(bm, caster) == [0], "the mace pays: no slot needed"

    res = _cast(engine, bm, caster, 0, [foe], aoe=(6, 5))
    assert res.valid
    by = {t.target_idx: t for t in res.target_results}
    assert by[foe].save_dc == 15, f"the mace's DC 15, not the holder's 10 (got {by[foe].save_dc})"
    frightened = [c for c in engine.active_agent_conditions
                  if c.agent_idx == foe and c.condition_name == "Frightened"]
    assert frightened and frightened[0].save_dc == 15, "the repeat save uses the mace's DC too"

    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 1}
    st = engine.get_agent_stats(bm, caster)
    assert list(st.spell_slots_remaining) == [0] * 9
    assert st.can_cast_leveled_spell(), "an item cast expends no slot, so D2 doesn't mark it"
    print("✅ test_pc_casts_fear_from_mace_without_slots")


def test_uses_run_out():
    bm, engine, caster, foe, _ = _board()
    _give_mace(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromWeapon, 0,
                                                 "Mace of Terror")])
    assert _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid
    assert _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 0}
    assert engine.available_castable_spells(bm, caster) == []
    assert not _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid, "a third cast is refused"
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 0}
    print("✅ test_uses_run_out")


def test_unattuned_or_missing_item_grants_nothing():
    bm, engine, caster, foe, _ = _board()
    _give_mace(engine, bm, caster, attuned=False)
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromWeapon, 0,
                                                 "Mace of Terror")])
    assert engine.available_castable_spells(bm, caster) == [], "D5: attunement required"
    assert not _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 2}

    # A stale tag (the slot holds a different weapon now) can't be cast either.
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromWeapon, 1,
                                                 "Mace of Terror")])
    assert engine.available_castable_spells(bm, caster) == []
    print("✅ test_unattuned_or_missing_item_grants_nothing")


# ── Charge pool + at will (wand) ───────────────────────────────────────────────
def test_pool_costs_gate():
    bm, engine, caster, foe, _ = _board()
    slot = _give_item(engine, bm, caster, WAND)
    src = rpg.SpellItemSource.FromItem
    engine.set_agent_spells(bm, caster, [
        _tagged("Burning Hands", src, slot, WAND["name"], cost=1),
        _tagged("Fireball", src, slot, WAND["name"], cost=3),
    ])
    assert _item_state(engine, bm, caster, slot).charges == 4
    assert engine.available_castable_spells(bm, caster) == [0, 1]

    assert _cast(engine, bm, caster, 1, [foe], aoe=(8, 8)).valid           # Fireball: 4 → 1
    assert _item_state(engine, bm, caster, slot).charges == 1
    assert engine.available_castable_spells(bm, caster) == [0], "1 charge: Burning Hands only"
    assert not _cast(engine, bm, caster, 1, [foe], aoe=(8, 8)).valid

    assert _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid           # Burning Hands: 1 → 0
    assert _item_state(engine, bm, caster, slot).charges == 0
    assert engine.available_castable_spells(bm, caster) == []
    print("✅ test_pool_costs_gate")


def test_at_will_never_runs_out_and_uses_item_attack():
    bm, engine, caster, foe, ally = _board()
    slot = _give_item(engine, bm, caster, WAND)
    icon = _give_item(engine, bm, caster, _catalog("items.json", "Icon of Ravenloft"))
    engine.set_agent_spells(bm, caster, [
        _tagged("Fire Bolt", rpg.SpellItemSource.FromItem, slot, WAND["name"]),
        _tagged("Protection from Evil and Good", rpg.SpellItemSource.FromItem, icon,
                "Icon of Ravenloft"),
    ])
    for _ in range(4):
        res = _cast(engine, bm, caster, 0, [foe])
        assert res.valid
        assert res.target_results[0].attack_mod == 7, "the wand's spell_attack, not the holder's +2"
        # A leveled at-will spell (D3) on a caster with no slots, repeatedly.
        assert _cast(engine, bm, caster, 1, [ally]).valid
    assert engine.available_castable_spells(bm, caster) == [0, 1]
    assert _item_state(engine, bm, caster, icon).uses_remaining == {"Cure Wounds": 1}
    assert _item_state(engine, bm, caster, slot).charges == 4, "at will touches no pool"
    print("✅ test_at_will_never_runs_out_and_uses_item_attack")


# ── D2 / D6 ───────────────────────────────────────────────────────────────────
def test_item_cast_ignores_per_turn_rule_and_casts_at_base_level():
    bm, engine, caster, foe, _ = _board(slots=[1, 0, 0, 0, 1, 0, 0, 0, 0])
    _give_mace(engine, bm, caster)
    bane = _dict_to_spell(_catalog("spells.json", "Bane"))
    engine.set_agent_spells(bm, caster, [
        bane, _tagged("Fear", rpg.SpellItemSource.FromWeapon, 0, "Mace of Terror")])

    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level, a.target_indices = caster, 0, 1, [foe]
    assert engine.execute_spell(bm, a).valid                                 # slot cast: Bane
    assert not engine.get_agent_stats(bm, caster).can_cast_leveled_spell()
    assert 1 in engine.available_castable_spells(bm, caster), "D2: the mace still works"

    # Asking for a 5th-level cast of the mace's Fear casts it at 3rd and spends no slot (D6).
    res = _cast(engine, bm, caster, 1, [foe], slot_level=5, aoe=(6, 5))
    assert res.valid
    assert list(engine.get_agent_stats(bm, caster).spell_slots_remaining)[4] == 1
    frightened = [c for c in engine.active_agent_conditions
                  if c.agent_idx == foe and c.condition_name == "Frightened"]
    assert frightened and frightened[0].cast_level == 3
    print("✅ test_item_cast_ignores_per_turn_rule_and_casts_at_base_level")


# ── Long rest ─────────────────────────────────────────────────────────────────
def test_long_rest_refills():
    bm, engine, caster, foe, _ = _board()
    _give_mace(engine, bm, caster)
    slot = _give_item(engine, bm, caster, WAND, attuned=False)   # refills even unattuned
    src = rpg.SpellItemSource.FromItem
    engine.set_agent_spells(bm, caster, [
        _tagged("Fear", rpg.SpellItemSource.FromWeapon, 0, "Mace of Terror"),
        _tagged("Fireball", src, slot, WAND["name"], cost=3)])
    assert _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid
    items = engine.get_agent_items(bm, caster)
    items[slot].item_spells.charges = 0
    engine.set_agent_items(bm, caster, items)

    engine.apply_long_rest(bm)
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 2}
    assert _item_state(engine, bm, caster, slot).charges == 4
    assert not _item_state(engine, bm, caster, slot).attuned, "a rest doesn't attune anything"
    print("✅ test_long_rest_refills")


def test_worn_armor_pays():
    bm, engine, caster, foe, _ = _board()
    armor = engine.get_agent_armor(bm, caster)
    cloak = armor[5]
    cloak.name = "Test Cloak of Fear"
    cloak.item_spells.spell_groups = {1: ["Fear"]}
    cloak.item_spells.spell_dc = 13
    cloak.item_spells.refill()
    armor[5] = cloak
    engine.set_agent_armor(bm, caster, armor)
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromArmor, 5,
                                                 "Test Cloak of Fear")])
    res = _cast(engine, bm, caster, 0, [foe], aoe=(6, 5))
    assert res.valid and res.target_results[0].save_dc == 13
    assert engine.get_agent_armor(bm, caster)[5].item_spells.uses_remaining == {"Fear": 0}
    print("✅ test_worn_armor_pays")


# ── NPCs pay the same way ─────────────────────────────────────────────────────
def test_npc_pays_from_item():
    bm, engine, caster, foe, _ = _board(npc=True)
    _give_mace(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_tagged("Fear", rpg.SpellItemSource.FromWeapon, 0,
                                                 "Mace of Terror")])
    assert engine.available_castable_spells(bm, caster) == [0], "no uses_max on the Spell needed"
    assert _cast(engine, bm, caster, 0, [foe], aoe=(6, 5)).valid
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 1}
    assert engine.get_agent_spells(bm, caster)[0].uses_remaining == 0, "the Spell holds no state"
    print("✅ test_npc_pays_from_item")


# ── A Bard who also knows Fear ────────────────────────────────────────────────
def test_bard_keeps_both_fears_independent():
    bm, engine, caster, foe, _ = _board(slots=[0, 0, 1, 0, 0, 0, 0, 0, 0])
    _give_mace(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [
        _dict_to_spell(_catalog("spells.json", "Fear")),
        _tagged("Fear", rpg.SpellItemSource.FromWeapon, 0, "Mace of Terror")])

    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level, a.target_indices = caster, 0, 3, [foe]
    a.aoe_col, a.aoe_row = 6, 5
    res = engine.execute_spell(bm, a)                                         # her own Fear
    assert res.valid and res.target_results[0].save_dc == 10, "her own DC"
    assert list(engine.get_agent_stats(bm, caster).spell_slots_remaining)[2] == 0
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 2}, "the mace is untouched"
    assert engine.available_castable_spells(bm, caster) == [1], "no slot left; the mace remains"

    res = _cast(engine, bm, caster, 1, [foe], aoe=(6, 5))                    # the mace's Fear
    assert res.valid and res.target_results[0].save_dc == 15
    assert _mace_state(engine, bm, caster).uses_remaining == {"Fear": 1}
    print("✅ test_bard_keeps_both_fears_independent")


def test_tag_round_trips_through_spell_dict():
    sp = _tagged("Fireball", rpg.SpellItemSource.FromItem, 2, "Test Wand of Fire", cost=3)
    back = _dict_to_spell(_spell_to_dict(sp))
    assert back.item_source == rpg.SpellItemSource.FromItem
    assert (back.item_slot, back.item_name, back.item_charge_cost) == (2, "Test Wand of Fire", 3)
    plain = _dict_to_spell(_catalog("spells.json", "Fear"))
    assert plain.item_source == rpg.SpellItemSource.NoItem and plain.item_slot == -1
    print("✅ test_tag_round_trips_through_spell_dict")


if __name__ == "__main__":
    test_pc_casts_fear_from_mace_without_slots()
    test_uses_run_out()
    test_unattuned_or_missing_item_grants_nothing()
    test_pool_costs_gate()
    test_at_will_never_runs_out_and_uses_item_attack()
    test_item_cast_ignores_per_turn_rule_and_casts_at_base_level()
    test_long_rest_refills()
    test_worn_armor_pays()
    test_npc_pays_from_item()
    test_bard_keeps_both_fears_independent()
    test_tag_round_trips_through_spell_dict()
    print("\nAll enspelled-items E2 tests passed.")
