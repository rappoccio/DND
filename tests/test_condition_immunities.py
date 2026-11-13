#!/usr/bin/env python3
"""
Stat-block Condition Immunities, enforced in the engine.

A creature's `condition_immunities` (loaded from the bestiary's meta.immunities_conditions)
stops the engine applying those conditions on every automatic path — addAgentCondition, spell
and weapon riders, grapples, and the direct-apply helpers. Damage and saves still resolve; only
the condition is refused. The DM's manual set_agent_conditions toggles bypass it on purpose.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
import agent_loader
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

_GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
_STATS_JSON = os.path.join(_GUI, "DND2024_MonsterStats.json")
_SPELLS_JSON = os.path.join(_GUI, "spells.json")


def _immune(engine, bm, idx, names):
    s = engine.get_agent_stats(bm, idx)
    s.condition_immunities = list(names)
    engine.set_agent_stats(bm, idx, s)


def _cond(idx, name, turns=10):
    c = rpg.ActiveAgentCondition()
    c.agent_idx = idx
    c.condition_name = name
    c.turns_remaining = turns
    c.save_repeat_turns = -1
    return c


def _tracked(engine, idx):
    return sorted(c.condition_name for c in engine.active_agent_conditions if c.agent_idx == idx)


def test_binding_and_lookup():
    s = rpg.Stats()
    assert list(s.condition_immunities) == []
    assert not s.immune_to_condition("Poisoned")
    s.condition_immunities = ["Charmed", "Poisoned"]
    assert s.immune_to_condition("Poisoned") and s.immune_to_condition("Charmed")
    assert not s.immune_to_condition("Blinded")
    print("✅ test_binding_and_lookup passed")


def test_add_agent_condition_refuses_immune():
    """addAgentCondition returns -1, sets no flag and tracks nothing for an immune creature."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    t = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    _immune(engine, bm, t, ["Poisoned", "Frightened"])

    assert engine.add_agent_condition(bm, _cond(t, "Poisoned")) == -1
    assert engine.add_agent_condition(bm, _cond(t, "Frightened")) == -1
    c = engine.get_agent_conditions(bm, t)
    assert not c.poisoned and not c.frightened
    assert _tracked(engine, t) == []

    # A condition it isn't immune to still lands.
    assert engine.add_agent_condition(bm, _cond(t, "Blinded")) >= 0
    assert engine.get_agent_conditions(bm, t).blinded
    assert _tracked(engine, t) == ["Blinded"]
    print("✅ test_add_agent_condition_refuses_immune passed")


def test_dm_manual_toggle_bypasses():
    """set_agent_conditions (the DM's Conditions menu) is a manual override and is not gated."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    t = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    _immune(engine, bm, t, ["Poisoned"])
    c = engine.get_agent_conditions(bm, t)
    c.poisoned = True
    engine.set_agent_conditions(bm, t, c)
    assert engine.get_agent_conditions(bm, t).poisoned
    print("✅ test_dm_manual_toggle_bypasses passed")


def _spell(name):
    d = next(s for s in json.load(open(_SPELLS_JSON)) if s["name"] == name)
    return helpers._dict_to_spell(d)


def test_spell_rider_damage_lands_condition_does_not():
    """Horrid Touch on a Poisoned-immune target: necrotic damage lands, Poisoned doesn't, but the
    Blinded/Deafened riders (not immune) still do."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Zariel", 5, 5))
    t = add_agent_to_battle(engine, bm, create_test_agent("Golem", 6, 5), con=1, hp=500)
    cs = engine.get_agent_stats(bm, caster)
    cs.cha = 30; cs.prof_bonus = 8   # CON-1 target can never reach the DC
    engine.set_agent_stats(bm, caster, cs)
    _immune(engine, bm, t, ["Poisoned"])

    engine.set_agent_spells(bm, caster, [_spell("ZarielHorridTouch")])
    act = rpg.SpellAction(); act.caster_idx = caster; act.spell_idx = 0; act.target_indices = [t]
    engine.execute_spell(bm, act)

    assert engine.get_agent_stats(bm, t).hp_cur < 500, "the save-failed damage still lands"
    c = engine.get_agent_conditions(bm, t)
    assert not c.poisoned, "Poisoned is refused"
    assert c.blinded and c.deafened, "non-immune riders still apply"
    assert _tracked(engine, t) == ["Blinded", "Deafened"]
    print("✅ test_spell_rider_damage_lands_condition_does_not passed")


def test_weapon_rider_refused():
    """The Pit Fiend's poisoning Bite hits a Poisoned-immune target without poisoning it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    pf = add_agent_to_battle(engine, bm, create_test_agent("Pit Fiend", 5, 5), con=24)
    t = add_agent_to_battle(engine, bm, create_test_agent("Golem", 6, 5), con=1, hp=200, ac=10)
    s = engine.get_agent_stats(bm, pf); s.prof_bonus = 6; engine.set_agent_stats(bm, pf, s)
    bite = helpers._dict_to_weapon(json.load(open(_STATS_JSON))["Pit Fiend"]["weapons"][0])
    bite.bonus_hit = 50
    engine.set_agent_weapons(bm, pf, [bite, rpg.Weapon(), rpg.Weapon()])
    _immune(engine, bm, t, ["Poisoned"])

    res = engine.execute_action(bm, rpg.Attack(pf, t, 0))
    assert res.hit
    assert engine.get_agent_stats(bm, t).hp_cur < 200, "the Bite's damage still lands"
    assert not engine.get_agent_conditions(bm, t).poisoned
    assert not engine.get_agent_stats(bm, t).cant_heal, "the no-heal rider rides the refused condition"
    assert _tracked(engine, t) == []
    print("✅ test_weapon_rider_refused passed")


def test_grapple_refused():
    """A grapple-on-hit weapon can't grapple a Grappled-immune creature."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Strahd", 5, 5))
    t = add_agent_to_battle(engine, bm, create_test_agent("Ooze", 6, 5), hp=200, ac=10)
    claw = helpers._dict_to_weapon(json.load(open(_STATS_JSON))["Strahd von Zarovich"]["weapons"]["main_hand"])
    claw.bonus_hit = 50
    engine.set_agent_weapons(bm, a, [claw, rpg.Weapon(), rpg.Weapon()])

    # Control: a non-immune target is grappled by the same hit.
    res = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert res.hit and engine.get_agent_conditions(bm, t).grappled, "control: the hit grapples"

    bm = setup_battle_map(); engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Strahd", 5, 5))
    t = add_agent_to_battle(engine, bm, create_test_agent("Ooze", 6, 5), hp=200, ac=10)
    engine.set_agent_weapons(bm, a, [claw, rpg.Weapon(), rpg.Weapon()])
    _immune(engine, bm, t, ["Grappled"])
    res = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert res.hit
    assert not engine.get_agent_conditions(bm, t).grappled
    print("✅ test_grapple_refused passed")


def test_direct_apply_helper_refused():
    """The standalone helpers (apply_prone, apply_poisoned) honor immunity too."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    t = add_agent_to_battle(engine, bm, create_test_agent("Elemental", 5, 5))
    _immune(engine, bm, t, ["Prone", "Poisoned"])
    engine.apply_prone(bm, t)
    engine.apply_poisoned(bm, t)
    c = engine.get_agent_conditions(bm, t)
    assert not c.prone and not c.poisoned
    print("✅ test_direct_apply_helper_refused passed")


def test_loader_and_save_round_trip():
    """dict_to_stats reads condition_immunities, and the board snapshot round-trips them."""
    st = agent_loader.dict_to_stats({"condition_immunities": ["Charmed", "Exhaustion"]})
    assert list(st.condition_immunities) == ["Charmed", "Exhaustion"]

    bm = setup_battle_map(); engine = setup_combat_engine()
    t = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 5, 5))
    _immune(engine, bm, t, ["Frightened"])
    snap = bm.snapshot_json()
    _immune(engine, bm, t, [])
    bm.restore_json(snap)
    assert list(engine.get_agent_stats(bm, t).condition_immunities) == ["Frightened"]
    print("✅ test_loader_and_save_round_trip passed")


def test_zariel_record():
    z = json.load(open(_STATS_JSON))["Zariel"]
    assert sorted(z["meta"]["immunities_conditions"]) == ["Charmed", "Exhaustion", "Frightened", "Poisoned"]
    print("✅ test_zariel_record passed")


if __name__ == "__main__":
    test_binding_and_lookup()
    test_add_agent_condition_refuses_immune()
    test_dm_manual_toggle_bypasses()
    test_spell_rider_damage_lands_condition_does_not()
    test_weapon_rider_refused()
    test_grapple_refused()
    test_direct_apply_helper_refused()
    test_loader_and_save_round_trip()
    test_zariel_record()
    print("\nAll condition-immunity tests passed ✅")
