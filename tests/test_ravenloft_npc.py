#!/usr/bin/env python3
"""Ravenloft items RI7 — NPC automation (plans/RAVENLOFT_ITEMS_PLAN.md).

Automated creatures use the Ravenloft items through the existing chooser: Hold Vampires and
Disruption sit on the control priority list, so a PreferControl holder of the Holy Symbol
paralyzes the vampire beside it and a Thighbone-wielder disrupts the zombie, not the living
bandit standing closer (single-target control respects `affects_creature_types`). With only
the living in reach the use is kept. Passive bonuses need nothing: they are in the numbers.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_item, _dict_to_weapon, sync_item_spells

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return {r["name"]: r for r in json.load(f)}


SPELLS, WEAPONS, ITEMS = _load("spells.json"), _load("weapons.json"), _load("items.json")


def _board(*foes):
    """An automated NPC holder at (5,5) with no slots; foes as (name, col, row, flags)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = add_agent_to_battle(engine, bm, create_test_agent("Priest", 5, 5), hp=60)
    idx = [add_agent_to_battle(engine, bm, create_test_agent(n, c, r), wis=1, hp=300)
           for n, c, r, _ in foes]
    for i, (_, _, _, flags) in zip(idx, foes):
        s = engine.get_agent_stats(bm, i)
        for k, v in flags.items():
            setattr(s, k, v)
        engine.set_agent_stats(bm, i, s)
        bm.set_agent_faction(i, 2)
    bm.set_agent_faction(me, 1)
    s = engine.get_agent_stats(bm, me)
    s.is_npc = True
    s.spell_slots_max = [0] * 9
    s.spell_slots_remaining = [0] * 9
    engine.set_agent_stats(bm, me, s)
    bm.set_agent_npc_automated(me, True)
    bm.set_agent_npc_automation_strategy(me, rpg.NpcAutomationStrategy.PreferControl)
    return bm, engine, me, idx


def _run(engine, bm, me):
    engine.begin_turn(bm, me)
    assert engine.run_npc_turn(bm, me) == rpg.FlowStatus.Completed


def test_new_spells_are_control_spells():
    pri = list(setup_combat_engine().npc_control_priority())
    assert "Hold Vampires" in pri and "Disruption" in pri
    print("✅ test_new_spells_are_control_spells")


def test_npc_holds_the_vampire():
    bm, engine, me, (vamp, zombie) = _board(
        ("Spawn", 6, 5, {"is_undead": True, "is_vampire": True}),
        ("Zombie", 5, 6, {"is_undead": True}))
    sym = _dict_to_item(ITEMS["Holy Symbol of Ravenkind"])
    sym.item_spells.attuned = True
    engine.set_agent_items(bm, me, [sym])
    sync_item_spells(engine, bm, me, SPELLS)
    _run(engine, bm, me)
    assert engine.get_agent_conditions(bm, vamp).paralyzed
    assert not engine.get_agent_conditions(bm, zombie).paralyzed
    assert engine.get_agent_items(bm, me)[0].item_spells.charges == 9
    print("✅ test_npc_holds_the_vampire")


def _thighbone(engine, bm, me):
    bone = _dict_to_weapon(WEAPONS["Saint Markovia's Thighbone"])
    bone.item_spells.attuned = True
    weapons = engine.get_agent_weapons(bm, me)
    weapons[0] = bone
    engine.set_agent_weapons(bm, me, weapons)
    sync_item_spells(engine, bm, me, SPELLS)


def test_npc_disrupts_only_the_undead():
    bm, engine, me, (bandit, zombie) = _board(
        ("Bandit", 6, 5, {}), ("Zombie", 4, 4, {"is_undead": True}))
    _thighbone(engine, bm, me)
    _run(engine, bm, me)
    assert engine.get_agent_weapons(bm, me)[0].item_spells.uses_remaining == {"Disruption": 0}
    assert engine.get_agent_stats(bm, zombie).hp_cur <= 275, "the zombie took the 25 Radiant"
    print("✅ test_npc_disrupts_only_the_undead")


def test_npc_keeps_disruption_with_only_the_living_near():
    bm, engine, me, (bandit,) = _board(("Bandit", 6, 5, {}))
    _thighbone(engine, bm, me)
    _run(engine, bm, me)
    assert engine.get_agent_weapons(bm, me)[0].item_spells.uses_remaining == {"Disruption": 1}
    print("✅ test_npc_keeps_disruption_with_only_the_living_near")


if __name__ == "__main__":
    test_new_spells_are_control_spells()
    test_npc_holds_the_vampire()
    test_npc_disrupts_only_the_undead()
    test_npc_keeps_disruption_with_only_the_living_near()
    print("\nAll Ravenloft items RI7 tests passed!")
