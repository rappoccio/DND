#!/usr/bin/env python3
"""Enspelled items E5 — NPC automation (plans/ENSPELLED_ITEMS_PLAN.md).

Item spells reach the automated chooser as ordinary castable spells (E3 grants them, E2 makes
them castable). E5 closes the gaps on the automation side: Fear is on the control priority list,
so a PreferControl mace-wielder casts it from the Mace of Terror and the mace pays; with no uses
left it swings the mace instead; a spent item no longer makes its holder a "caster" for the
difficulty resolver; and the teleport escape pays an item's teleport from the item, not a slot.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_weapon, _dict_to_item, sync_item_spells

_GUI = os.path.join(_ROOT, "gui")
with open(os.path.join(_GUI, "spells.json")) as f:
    CATALOG = {r["name"]: r for r in json.load(f)}
with open(os.path.join(_GUI, "weapons.json")) as f:
    MACE = next(r for r in json.load(f) if r["name"] == "Mace of Terror")


def _board(npc=True):
    """An automated mace-wielder at (5,5) with no spell slots, and a WIS-1 foe adjacent at (6,5)
    who fails the mace's DC-15 save on any roll."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = add_agent_to_battle(engine, bm, create_test_agent("Knight", 5, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), wis=1, hp=200)
    bm.set_agent_faction(me, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, me)
    s.is_npc = npc
    s.spell_slots_max = [0] * 9
    s.spell_slots_remaining = [0] * 9
    engine.set_agent_stats(bm, me, s)
    mace = _dict_to_weapon(MACE)
    mace.item_spells.attuned = True
    weapons = engine.get_agent_weapons(bm, me)
    weapons[0] = mace
    engine.set_agent_weapons(bm, me, weapons)
    sync_item_spells(engine, bm, me, CATALOG)
    bm.set_agent_npc_automated(me, True)
    return bm, engine, me, foe


def _mace(engine, bm, idx):
    return engine.get_agent_weapons(bm, idx)[0].item_spells


def _frightened(engine, foe):
    return [c for c in engine.active_agent_conditions
            if c.agent_idx == foe and c.condition_name == "Frightened"]


def _spend_mace(engine, bm, idx):
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[0].item_spells.uses_remaining = {"Fear": 0}
    engine.set_agent_weapons(bm, idx, weapons)


def test_fear_is_a_control_spell():
    assert "Fear" in list(setup_combat_engine().npc_control_priority())
    print("✅ test_fear_is_a_control_spell")


def test_automated_mace_wielder_casts_fear():
    for npc in (True, False):                     # an automated NPC and an automated PC alike
        bm, engine, me, foe = _board(npc=npc)
        bm.set_agent_npc_automation_strategy(me, rpg.NpcAutomationStrategy.PreferControl)
        engine.begin_turn(bm, me)
        assert engine.run_npc_turn(bm, me) == rpg.FlowStatus.Completed
        fr = _frightened(engine, foe)
        assert fr and fr[0].save_dc == 15, f"Fear from the mace at its DC 15 (npc={npc})"
        assert _mace(engine, bm, me).uses_remaining == {"Fear": 1}, "the mace paid"
        assert list(engine.get_agent_stats(bm, me).spell_slots_remaining) == [0] * 9
    print("✅ test_automated_mace_wielder_casts_fear")


def test_no_uses_left_swings_instead():
    bm, engine, me, foe = _board()
    _spend_mace(engine, bm, me)
    bm.set_agent_npc_automation_strategy(me, rpg.NpcAutomationStrategy.PreferControl)
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, me)
    assert engine.run_npc_turn(bm, me) == rpg.FlowStatus.Completed
    assert not _frightened(engine, foe), "no uses left: no Fear"
    assert _mace(engine, bm, me).uses_remaining == {"Fear": 0}
    assert (me, foe) in calls, "the weapon fallback attacks the adjacent foe"
    print("✅ test_no_uses_left_swings_instead")


def test_spent_item_is_not_a_caster():
    bm, engine, me, _ = _board()
    bm.set_agent_npc_automation_difficulty(me, 4)
    assert engine.npc_classify_role(bm, me) == rpg.NpcRole.Caster
    assert engine.resolve_strategy(bm, me) == rpg.NpcAutomationStrategy.PreferControl, \
        "L4 probes the control planner, which finds the mace's Fear"
    _spend_mace(engine, bm, me)
    assert engine.npc_classify_role(bm, me) == rpg.NpcRole.Melee, "a spent mace is just a mace"
    assert engine.resolve_strategy(bm, me) == rpg.NpcAutomationStrategy.Simple
    print("✅ test_spent_item_is_not_a_caster")


def test_teleport_escape_pays_from_item():
    """A Forcecaged NPC whose only teleport is an item's Misty Step (1/day) escapes with it: the
    item's use is spent, no slot, and the one-leveled-spell rule (D2) isn't touched."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = add_agent_to_battle(engine, bm, create_test_agent("Cambion", 3, 3), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 3, 10), hp=30)
    bm.set_agent_faction(me, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, me)
    s.is_npc = True
    s.spell_slots_max = [0, 1, 0, 0, 0, 0, 0, 0, 0]
    s.spell_slots_remaining = [0, 1, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, me, s)
    cloak = _dict_to_item({"name": "Test Cloak of Stepping", "type": "Wondrous",
                           "action_type": "NoAction", "range": 0, "quantity": 1,
                           "consumable": False, "item_spell_groups": {"1": ["Misty Step"]}})
    engine.set_agent_items(bm, me, list(engine.get_agent_items(bm, me)) + [cloak])
    sync_item_spells(engine, bm, me, CATALOG)
    assert [sp.name for sp in engine.get_agent_spells(bm, me)] == ["Misty Step"]
    c = engine.get_agent_conditions(bm, me)
    c.forcecaged = c.forcecage_sealed = True
    c.forcecage_dc = 1
    engine.set_agent_conditions(bm, me, c)
    bm.set_agent_npc_automated(me, True)
    bm.set_agent_npc_automation_strategy(me, rpg.NpcAutomationStrategy.Simple)

    before = bm.placed_agents[me].origin
    engine.begin_turn(bm, me)
    assert engine.run_npc_turn(bm, me) == rpg.FlowStatus.Completed
    assert bm.placed_agents[me].origin != before, "it teleported"
    assert engine.get_agent_items(bm, me)[-1].item_spells.uses_remaining == {"Misty Step": 0}
    st = engine.get_agent_stats(bm, me)
    assert list(st.spell_slots_remaining)[1] == 1, "no slot spent"
    assert st.can_cast_leveled_spell(), "D2: an item cast doesn't mark the leveled-spell rule"
    print("✅ test_teleport_escape_pays_from_item")


if __name__ == "__main__":
    test_fear_is_a_control_spell()
    test_automated_mace_wielder_casts_fear()
    test_no_uses_left_swings_instead()
    test_spent_item_is_not_a_caster()
    test_teleport_escape_pays_from_item()
    print("\nAll enspelled-items E5 tests passed.")
