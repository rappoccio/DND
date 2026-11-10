#!/usr/bin/env python3
"""Spell scrolls SS1 — model + engine (plans/SPELL_SCROLLS_PLAN.md).

A made scroll is an items.json "Spell Scroll" holding one use of one spell at a fixed DC /
attack, defaulting from the 2024 DMG table (S1, S2). Casting it spends no slot and uses the
scroll's DC; once spent it is discarded, except while its spell is still live (held
concentration), and never refills on a long rest (S3). Only a creature with the spell on one
of its class lists (Eldritch Knight / Arcane Trickster read the Wizard list) can read it,
unless the DM ticks reads_any_scroll (S5). Use Item refuses a scroll; save → load keeps an
unused one and the DM tick.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_item, _item_to_dict, is_item_spell, sync_item_spells,
                     make_spell_scroll, can_read_scroll, scroll_spell_names, spell_classes,
                     is_blank_scroll)
from agent_loader import dict_to_stats

_GUI = os.path.join(_ROOT, "gui")
with open(os.path.join(_GUI, "spells.json")) as f:
    ALL_SPELLS = json.load(f)
CATALOG = {d["name"]: d for d in ALL_SPELLS}
with open(os.path.join(_GUI, "items.json")) as f:
    TEMPLATE = next(r for r in json.load(f) if r["name"] == "Spell Scroll")


def _scroll(spell, dc=None, attack=None):
    return make_spell_scroll(TEMPLATE, CATALOG[spell], dc, attack)


def _board(cls="Wizard", level=5):
    """A caster of ``cls`` with no spell slots at (5,5); a WIS-1 foe at (6,5)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Reader", 5, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), wis=1, hp=200)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, caster)
    if cls:
        s.set_class_level(getattr(rpg.CharacterClass, cls), level)
    s.can_cast_spell = True
    s.spellcasting_ability = 3          # INT 10 → +0; prof 2 ⇒ own DC 10
    s.prof_bonus = 2
    s.spell_slots_max = [0] * 9
    s.spell_slots_remaining = [0] * 9
    engine.set_agent_stats(bm, caster, s)
    return bm, engine, caster, foe


def _give(engine, bm, idx, *records):
    items = list(engine.get_agent_items(bm, idx)) + [_dict_to_item(r) for r in records]
    engine.set_agent_items(bm, idx, items)
    sync_item_spells(engine, bm, idx, CATALOG)


def _item_spells(engine, bm, idx):
    return [(j, sp) for j, sp in enumerate(engine.get_agent_spells(bm, idx)) if is_item_spell(sp)]


def _cast(engine, bm, caster, spell_idx, targets, aoe=None):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = caster, spell_idx, 0
    a.target_indices = list(targets)
    if aoe:
        a.aoe_col, a.aoe_row = aoe
    return engine.execute_spell(bm, a)


# ── S1 / S2: making a scroll ────────────────────────────────────────────────────
def test_make_scroll_defaults_from_dmg_table():
    fear = _scroll("Fear")
    assert fear["name"] == "Spell Scroll (Fear)" and fear["type"] == "Scroll"
    assert fear["item_spell_groups"] == {"1": ["Fear"]}
    assert (fear["spell_dc"], fear["spell_attack"]) == (15, 7), "level 3 → DC 15 / +7"
    bolt = _scroll("Fire Bolt")
    assert (bolt["spell_dc"], bolt["spell_attack"]) == (13, 5), "cantrip → DC 13 / +5"
    custom = _scroll("Fear", dc=17, attack=9)
    assert (custom["spell_dc"], custom["spell_attack"]) == (17, 9), "the DM's DC wins"
    assert is_blank_scroll(TEMPLATE) and not is_blank_scroll(fear)
    print("✅ test_make_scroll_defaults_from_dmg_table")


def test_scroll_spell_list_excludes_monster_abilities():
    names = scroll_spell_names(ALL_SPELLS)
    assert "Fireball" in names and "Toll the Dead" in names
    assert not any(n.startswith("Breath") for n in names), "no breath weapons on scrolls"
    assert spell_classes("Fear") >= {"Wizard", "Bard"}
    print("✅ test_scroll_spell_list_excludes_monster_abilities")


def test_scroll_round_trips():
    it = _dict_to_item(_scroll("Fear", dc=16))
    assert it.type == rpg.ItemType.Scroll and it.consumable
    assert it.item_spells.uses_remaining == {"Fear": 1} and it.item_spells.spell_dc == 16
    back = _dict_to_item(_item_to_dict(it))
    assert back.type == rpg.ItemType.Scroll and back.name == "Spell Scroll (Fear)"
    assert back.item_spells.uses_remaining == {"Fear": 1} and back.item_spells.spell_dc == 16
    st = dict_to_stats({"reads_any_scroll": True})
    assert st.reads_any_scroll, "the DM tick survives a load"
    print("✅ test_scroll_round_trips")


# ── S5: who can read it ─────────────────────────────────────────────────────────
def test_class_list_gate():
    bm, engine, wiz, _ = _board("Wizard")
    _give(engine, bm, wiz, _scroll("Fear"), _scroll("Cure Wounds"))
    names = [sp.name for _, sp in _item_spells(engine, bm, wiz)]
    assert names == ["Fear"], f"a Wizard reads Fear but not Cure Wounds (got {names})"
    assert len(engine.get_agent_items(bm, wiz)) == 2, "the unreadable scroll stays carried"

    bm, engine, brute, _ = _board(None)
    _give(engine, bm, brute, _scroll("Fear"))
    assert not _item_spells(engine, bm, brute), "a classless creature can't read it"
    s = engine.get_agent_stats(bm, brute)
    s.reads_any_scroll = True
    engine.set_agent_stats(bm, brute, s)
    sync_item_spells(engine, bm, brute, CATALOG)
    assert [sp.name for _, sp in _item_spells(engine, bm, brute)] == ["Fear"], "DM override"

    bm, engine, ek, _ = _board("Fighter", 3)
    s = engine.get_agent_stats(bm, ek)
    assert not can_read_scroll(s, "Fear"), "a plain Fighter can't"
    s.fighter_subclass = rpg.FighterSubclass.EldritchKnight
    assert can_read_scroll(s, "Fear"), "an Eldritch Knight reads the Wizard list"
    print("✅ test_class_list_gate")


# ── S3 / S6 / S7: casting spends it, then it's gone ─────────────────────────────
def test_cast_uses_scroll_dc_and_no_slot_then_discards():
    bm, engine, wiz, foe = _board("Wizard")
    potion = next(r for r in json.load(open(os.path.join(_GUI, "items.json")))
                  if r["name"] == "Potion of Healing")
    _give(engine, bm, wiz, _scroll("Magic Missile"), _scroll("Burning Hands"), potion)
    (j, sp), _ = _item_spells(engine, bm, wiz)
    assert sp.name == "Magic Missile"
    assert j in engine.available_castable_spells(bm, wiz), "the scroll pays: no slot needed"

    assert _cast(engine, bm, wiz, j, [foe]).valid
    st = engine.get_agent_stats(bm, wiz)
    assert list(st.spell_slots_remaining) == [0] * 9
    assert st.can_cast_leveled_spell(), "a scroll cast expends no slot (D2)"
    assert j not in engine.available_castable_spells(bm, wiz), "spent: no second cast"

    sync_item_spells(engine, bm, wiz, CATALOG)
    names = [it.name for it in engine.get_agent_items(bm, wiz)]
    assert names == ["Spell Scroll (Burning Hands)", "Potion of Healing"], names
    left = _item_spells(engine, bm, wiz)
    assert [(sp.name, sp.item_slot) for _, sp in left] == [("Burning Hands", 0)], \
        "the other scroll's tag follows its row"
    assert left[0][0] in engine.available_castable_spells(bm, wiz)
    print("✅ test_cast_uses_scroll_dc_and_no_slot_then_discards")


def test_concentration_scroll_kept_until_it_ends():
    bm, engine, wiz, foe = _board("Wizard")
    _give(engine, bm, wiz, _scroll("Fear", dc=17))
    (j, _), = _item_spells(engine, bm, wiz)
    res = _cast(engine, bm, wiz, j, [foe], aoe=(6, 5))
    assert res.valid
    by = {t.target_idx: t for t in res.target_results}
    assert by[foe].save_dc == 17, f"the scroll's DC, not the caster's 10 (got {by[foe].save_dc})"

    assert engine.discard_spent_scrolls(bm, wiz) == 0, "concentrating on it: kept"
    sync_item_spells(engine, bm, wiz, CATALOG)
    assert len(engine.get_agent_items(bm, wiz)) == 1
    frightened = [c for c in engine.active_agent_conditions
                  if c.agent_idx == foe and c.condition_name == "Frightened"]
    assert frightened and frightened[0].save_dc == 17, "repeat saves keep the scroll's DC"

    # A long rest never refills a scroll, even one still held.
    engine.apply_long_rest(bm)
    assert engine.get_agent_items(bm, wiz)[0].item_spells.uses_remaining == {"Fear": 0}

    engine.drop_concentration(bm, wiz)
    sync_item_spells(engine, bm, wiz, CATALOG)
    assert not engine.get_agent_items(bm, wiz), "concentration over: the scroll is gone"
    assert not _item_spells(engine, bm, wiz)
    print("✅ test_concentration_scroll_kept_until_it_ends")


def test_use_item_refuses_scroll():
    bm, engine, wiz, _ = _board("Wizard")
    _give(engine, bm, wiz, _scroll("Fear"))
    assert not engine.use_item(bm, wiz, 0, wiz).valid, "a scroll is cast, not 'used'"
    assert engine.get_agent_items(bm, wiz)[0].item_spells.uses_remaining == {"Fear": 1}
    print("✅ test_use_item_refuses_scroll")


def test_unused_scroll_never_discarded():
    bm, engine, wiz, _ = _board("Wizard")
    _give(engine, bm, wiz, _scroll("Fear"))
    assert engine.discard_spent_scrolls(bm, wiz) == 0
    blank = _dict_to_item(TEMPLATE)
    engine.set_agent_items(bm, wiz, list(engine.get_agent_items(bm, wiz)) + [blank])
    assert engine.discard_spent_scrolls(bm, wiz) == 0, "a blank scroll isn't a spent one"
    assert len(engine.get_agent_items(bm, wiz)) == 2
    print("✅ test_unused_scroll_never_discarded")


if __name__ == "__main__":
    test_make_scroll_defaults_from_dmg_table()
    test_scroll_spell_list_excludes_monster_abilities()
    test_scroll_round_trips()
    test_class_list_gate()
    test_cast_uses_scroll_dc_and_no_slot_then_discards()
    test_concentration_scroll_kept_until_it_ends()
    test_use_item_refuses_scroll()
    test_unused_scroll_never_discarded()
    print("\nAll spell scroll SS1 tests passed.")
