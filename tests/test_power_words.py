#!/usr/bin/env python3
"""
Test the four HP-threshold / HP-pool "advanced" spells wired data-first:

  - Power Word Kill   : a creature with <= 100 current HP dies outright (true death,
                        no death saves even for a PC). Above 100 HP it takes 12d12 Psychic.
  - Power Word Stun   : a creature with <= 150 current HP gains the Stunned condition
                        automatically (no initial save); above 150 HP it is not stunned.
  - Mass Heal         : a 700-HP pool restores every affected ally toward its HP maximum.
  - Power Word Fortify: a 700-HP pool is split evenly as Temporary HP among affected allies.

Every spell is loaded straight from spells.json through helpers._dict_to_spell, so this
also exercises the new Spell fields' JSON round-trip and the pybind11 bindings.
"""

import sys
import os
import json

GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
sys.path.insert(0, GUI_DIR)

import rpg_battle_map as rpg
from helpers import _dict_to_spell
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1
ENEMY = 2

with open(os.path.join(GUI_DIR, "spells.json")) as _f:
    ALL_SPELLS = {s["name"]: s for s in json.load(_f)}


def _spell(name):
    return _dict_to_spell(ALL_SPELLS[name])


def _place(engine, bm, name, col, row, faction=TEAM, hp=10):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    engine.set_agent_stats(bm, idx, s)
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5  # CHA
    s.cha = 20
    engine.set_agent_stats(bm, idx, s)


def _cast_single(engine, bm, caster, spell, target):
    engine.set_agent_spells(bm, caster, [spell])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = spell.level
    action.target_indices = [target]
    engine.execute_spell(bm, action)


def _cast_area(engine, bm, caster, spell, center_col, center_row):
    engine.set_agent_spells(bm, caster, [spell])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = spell.level
    action.aoe_col = center_col
    action.aoe_row = center_row
    engine.execute_spell(bm, action)


# ── Power Word Kill ──────────────────────────────────────────────────────────

def test_power_word_kill_below_threshold_dies():
    """A PC at 100 HP or fewer dies outright — no death saves."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    victim = _place(engine, bm, "Ogre", 6, 5, faction=ENEMY, hp=90)
    vs = engine.get_agent_stats(bm, victim)
    vs.is_npc = False  # a PC would normally make death saves; PW Kill must bypass them
    engine.set_agent_stats(bm, victim, vs)
    _make_caster(engine, bm, caster)

    _cast_single(engine, bm, caster, _spell("Power Word Kill"), victim)

    s = engine.get_agent_stats(bm, victim)
    c = engine.get_agent_conditions(bm, victim)
    assert s.hp_cur == 0, f"victim should be at 0 HP, got {s.hp_cur}"
    assert c.dead, "victim with <= 100 HP should die outright (dead flag set)"
    print("✅ test_power_word_kill_below_threshold_dies passed")


def test_power_word_kill_above_threshold_survives():
    """A creature above 100 HP takes 12d12 Psychic instead and survives."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    victim = _place(engine, bm, "Giant", 6, 5, faction=ENEMY, hp=200)
    _make_caster(engine, bm, caster)

    _cast_single(engine, bm, caster, _spell("Power Word Kill"), victim)

    s = engine.get_agent_stats(bm, victim)
    c = engine.get_agent_conditions(bm, victim)
    assert not c.dead, "a 200 HP creature must not die to Power Word Kill"
    assert s.hp_cur < 200, f"victim should take 12d12 Psychic, hp still {s.hp_cur}"
    assert s.hp_cur >= 200 - 144, f"12d12 can't exceed 144, got drop to {s.hp_cur}"
    print("✅ test_power_word_kill_above_threshold_survives passed")


# ── Power Word Stun ──────────────────────────────────────────────────────────

def _is_stunned(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx).stunned


def test_power_word_stun_below_threshold_stuns():
    """A creature at 150 HP or fewer is Stunned automatically (no initial save)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    victim = _place(engine, bm, "Knight", 6, 5, faction=ENEMY, hp=150)
    _make_caster(engine, bm, caster)

    _cast_single(engine, bm, caster, _spell("Power Word Stun"), victim)

    assert _is_stunned(engine, bm, victim), "a 150 HP creature should be Stunned"
    print("✅ test_power_word_stun_below_threshold_stuns passed")


def test_power_word_stun_above_threshold_no_stun():
    """A creature above 150 HP is not stunned."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    victim = _place(engine, bm, "Dragon", 6, 5, faction=ENEMY, hp=250)
    _make_caster(engine, bm, caster)

    _cast_single(engine, bm, caster, _spell("Power Word Stun"), victim)

    assert not _is_stunned(engine, bm, victim), "a 250 HP creature must not be Stunned"
    print("✅ test_power_word_stun_above_threshold_no_stun passed")


# ── Mass Heal ────────────────────────────────────────────────────────────────

def test_mass_heal_restores_allies_from_pool():
    """Mass Heal refills every wounded ally toward its HP maximum from the 700 pool."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5, hp=50)
    a1 = _place(engine, bm, "Ally1", 6, 5, hp=50)
    a2 = _place(engine, bm, "Ally2", 4, 5, hp=50)
    for idx in (a1, a2):
        s = engine.get_agent_stats(bm, idx)
        s.hp_cur = 10  # wounded: 40 HP missing each
        engine.set_agent_stats(bm, idx, s)
    _make_caster(engine, bm, caster)

    _cast_area(engine, bm, caster, _spell("Mass Heal"), 5, 5)

    for idx in (a1, a2):
        s = engine.get_agent_stats(bm, idx)
        assert s.hp_cur == s.hp_max, f"ally {idx} should be full ({s.hp_max}), got {s.hp_cur}"
    print("✅ test_mass_heal_restores_allies_from_pool passed")


# ── Power Word Fortify ───────────────────────────────────────────────────────

def test_power_word_fortify_grants_temp_hp():
    """Power Word Fortify hands out an even share of the 700 pool as Temporary HP."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Bard", 5, 5, hp=50)
    a1 = _place(engine, bm, "Ally1", 6, 5, hp=50)
    a2 = _place(engine, bm, "Ally2", 4, 5, hp=50)
    _make_caster(engine, bm, caster)

    _cast_area(engine, bm, caster, _spell("Power Word Fortify"), 5, 5)

    for idx in (a1, a2):
        s = engine.get_agent_stats(bm, idx)
        assert s.temp_hp > 0, f"ally {idx} should gain temporary HP, got {s.temp_hp}"
        assert s.hp_cur == s.hp_max, f"ally {idx} HP maximum must be untouched, got {s.hp_cur}"
    print("✅ test_power_word_fortify_grants_temp_hp passed")


# ── Power Word Heal ──────────────────────────────────────────────────────────

def test_power_word_heal_restores_and_cures():
    """Power Word Heal refills the target to full HP and ends its listed conditions."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Fighter", 6, 5, hp=120)
    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 12  # badly wounded
    engine.set_agent_stats(bm, ally, s)
    _make_caster(engine, bm, caster)

    # Power Word Stun applies a *tracked* Stunned condition (ally has <= 150 HP).
    _cast_single(engine, bm, caster, _spell("Power Word Stun"), ally)
    assert engine.get_agent_conditions(bm, ally).stunned, "setup: ally should be Stunned"

    _cast_single(engine, bm, caster, _spell("Power Word Heal"), ally)

    s = engine.get_agent_stats(bm, ally)
    c = engine.get_agent_conditions(bm, ally)
    assert s.hp_cur == s.hp_max, f"ally should be at full HP ({s.hp_max}), got {s.hp_cur}"
    assert not c.stunned, "Power Word Heal should end the Stunned condition"
    print("✅ test_power_word_heal_restores_and_cures passed")


def test_power_word_heal_revives_downed():
    """Power Word Heal on a downed (0 HP, unconscious) creature revives it at full HP."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Rogue", 6, 5, hp=60)
    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 0
    engine.set_agent_stats(bm, ally, s)
    c = engine.get_agent_conditions(bm, ally)
    c.unconscious = True
    engine.set_agent_conditions(bm, ally, c)
    _make_caster(engine, bm, caster)

    _cast_single(engine, bm, caster, _spell("Power Word Heal"), ally)

    s = engine.get_agent_stats(bm, ally)
    assert s.hp_cur == s.hp_max, f"downed ally should be full ({s.hp_max}), got {s.hp_cur}"
    assert not engine.get_agent_conditions(bm, ally).unconscious, "ally should be revived"
    print("✅ test_power_word_heal_revives_downed passed")


def run_all():
    test_power_word_kill_below_threshold_dies()
    test_power_word_kill_above_threshold_survives()
    test_power_word_stun_below_threshold_stuns()
    test_power_word_stun_above_threshold_no_stun()
    test_mass_heal_restores_allies_from_pool()
    test_power_word_fortify_grants_temp_hp()
    test_power_word_heal_restores_and_cures()
    test_power_word_heal_revives_downed()
    print("\n✅ All Power Word / Mass Heal tests passed")


if __name__ == "__main__":
    run_all()
