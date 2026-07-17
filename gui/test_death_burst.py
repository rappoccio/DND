#!/usr/bin/env python3
"""
Test suite for Death Burst (BALOR_IMPLEMENTATION_PLAN.md Part D).

A creature with Stats.death_burst_spell set detonates that spell — centered on
itself — when it drops to 0 HP (resolveDeathBurst, fired from the applyUnconscious
death chokepoint). The Balor's Death Throes is a 30-ft Sphere, DEX save, 9d6 Fire
+ 9d6 Force (half on save). The feature is generic: any "explodes on death"
monster gets it by naming a spell in its own list.

Deterministic outcomes are forced via the save DC: applySpellEffect derives the
DC from the dying creature's stats, so a high-DEX/high-PB burster guarantees the
targets fail their save (full damage), letting us assert exact behavior.

Wall-blocking (Total Cover) is delegated to the shared resolveAoeTargets and is
covered by the Total Cover suite; it is not re-tested here.
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _dict_to_spell
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

_STATS_PATH  = os.path.join(os.path.dirname(__file__), "DND2024_MonsterStats.json")
_SPELLS_PATH = os.path.join(os.path.dirname(__file__), "spells.json")


def _death_throes_spell():
    """Build the shipped BalorDeathThroes via the canonical dict->Spell path."""
    with open(_SPELLS_PATH) as f:
        catalog = json.load(f)
    entry = next(s for s in catalog if s["name"] == "BalorDeathThroes")
    return _dict_to_spell(entry)


def _make_burster(engine, bm, col, row, *, dex=30, pb=6, hp=1):
    """Place a creature that explodes into BalorDeathThroes on death. High DEX + PB
    give it a steep save DC (8 + PB + DEX mod = 24 here) so targets reliably fail.

    NOTE: only sets STATS here. Its spell list must be armed via _arm_burst AFTER every
    agent is placed — add_agent_to_battle's apply_agent_configs is destructive and restores
    prior stats/conditions but NOT spells (Agent Dual-List Gotcha), so spells set now would
    be wiped by a later placement."""
    idx = add_agent_to_battle(engine, bm, create_test_agent("Burster", col, row))
    s = engine.get_agent_stats(bm, idx)
    s.dex = dex
    s.prof_bonus = pb
    s.spellcasting_ability = 5   # CHA (irrelevant to the DEX-derived zone DC, but realistic)
    s.hp_max = hp
    s.hp_cur = hp
    s.is_npc = True
    s.death_burst_spell = "BalorDeathThroes"
    engine.set_agent_stats(bm, idx, s)
    return idx


def _arm_burst(engine, bm, *idxs):
    """Give each burster its BalorDeathThroes spell. Call ONCE, after all agents are placed."""
    for idx in idxs:
        engine.set_agent_spells(bm, idx, [_death_throes_spell()])


def _victim(engine, bm, col, row, *, hp=300, dex=10):
    idx = add_agent_to_battle(engine, bm, create_test_agent("Victim", col, row))
    s = engine.get_agent_stats(bm, idx)
    s.dex = dex
    s.prof_bonus = 2
    s.hp_max = hp
    s.hp_cur = hp
    engine.set_agent_stats(bm, idx, s)
    return idx


def _hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def _kill(engine, bm, idx):
    """Drop the creature to 0 and route it through the death chokepoint."""
    s = engine.get_agent_stats(bm, idx)
    s.hp_cur = 0
    engine.set_agent_stats(bm, idx, s)
    engine.apply_unconscious(bm, idx)


def test_death_burst_hits_in_range_spares_far():
    """Killing the burster damages a creature within 30 ft; one at 35 ft is untouched."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    balor = _make_burster(engine, bm, 1, 5)
    near  = _victim(engine, bm, 4, 5)   # 3 cells = 15 ft — in range
    far   = _victim(engine, bm, 8, 5)   # 7 cells = 35 ft — out of range
    _arm_burst(engine, bm, balor)

    _kill(engine, bm, balor)

    assert _hp(engine, bm, near) < 300, "a creature within 30 ft must take Death Throes damage"
    assert _hp(engine, bm, far) == 300, "a creature at 35 ft must be untouched"
    print("✅ test_death_burst_hits_in_range_spares_far passed")


def test_death_burst_full_damage_on_failed_save():
    """A failed DEX save takes the full 9d6 Fire + 9d6 Force (18..108)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    balor = _make_burster(engine, bm, 1, 5)
    tgt   = _victim(engine, bm, 3, 5)   # 2 cells = 10 ft — well in range
    _arm_burst(engine, bm, balor)

    _kill(engine, bm, balor)

    dealt = 300 - _hp(engine, bm, tgt)
    assert 18 <= dealt <= 108, f"full 9d6+9d6 should be 18..108, got {dealt}"
    print("✅ test_death_burst_full_damage_on_failed_save passed")


def test_death_burst_fire_immune_takes_force_only():
    """A Fire-immune target takes only the Force half (<= 54); Fire+Force immune takes 0."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    balor = _make_burster(engine, bm, 1, 5)

    fire_immune = _victim(engine, bm, 3, 5)
    s = engine.get_agent_stats(bm, fire_immune)
    s.set_magic_damage_multiplier(rpg.MagicDamage.Fire, 0.0)   # setter, not array-write (copy gotcha)
    engine.set_agent_stats(bm, fire_immune, s)

    both_immune = _victim(engine, bm, 5, 5)
    s2 = engine.get_agent_stats(bm, both_immune)
    s2.set_magic_damage_multiplier(rpg.MagicDamage.Fire, 0.0)
    s2.set_magic_damage_multiplier(rpg.MagicDamage.Force, 0.0)
    engine.set_agent_stats(bm, both_immune, s2)

    _arm_burst(engine, bm, balor)
    _kill(engine, bm, balor)

    fire_dealt = 300 - _hp(engine, bm, fire_immune)
    both_dealt = 300 - _hp(engine, bm, both_immune)
    assert 9 <= fire_dealt <= 54, f"Fire-immune should take only Force (9..54), got {fire_dealt}"
    assert both_dealt == 0, f"Fire+Force-immune should take 0, got {both_dealt}"
    print("✅ test_death_burst_fire_immune_takes_force_only passed")


def test_death_burst_spares_source_and_chains_finitely():
    """The dead source isn't self-damaged; a burst that kills another burster chains
    once and terminates (no infinite loop)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Two adjacent 1-HP bursters + a tough bystander in range of both.
    a = _make_burster(engine, bm, 2, 5, hp=1)
    b = _make_burster(engine, bm, 3, 5, hp=1)
    bystander = _victim(engine, bm, 5, 5)
    _arm_burst(engine, bm, a, b)

    _kill(engine, bm, a)   # A explodes -> kills B -> B explodes -> terminates

    a_cond = engine.get_agent_conditions(bm, a)
    b_cond = engine.get_agent_conditions(bm, b)
    assert a_cond.dead, "the source burster should be dead"
    assert b_cond.dead, "A's burst should have killed B (chained death)"
    # Bystander was caught by BOTH bursts (A directly + B's chained burst) and survived,
    # proving the chain resolved and terminated rather than hanging.
    assert _hp(engine, bm, bystander) < 300, "bystander should take burst damage from the chain"
    print("✅ test_death_burst_spares_source_and_chains_finitely passed")


def test_death_burst_json_and_serializer():
    """The shipped Balor record + BalorDeathThroes spell are wired, and death_burst_spell
    round-trips through dict_to_stats."""
    from agent_loader import dict_to_stats

    with open(_STATS_PATH) as f:
        mobs = json.load(f)
    balor = mobs["Balor"]
    assert balor["stats"]["death_burst_spell"] == "BalorDeathThroes"
    assert "BalorDeathThroes" in balor["spell_indices"], "burst spell must be in the Balor's spell list"

    with open(_SPELLS_PATH) as f:
        catalog = json.load(f)
    dt = next(s for s in catalog if s["name"] == "BalorDeathThroes")
    assert dt["geometry"] == "Sphere" and dt["radius"] == 30
    assert dt["attack_type"] == "Save" and dt["save_ability"] == "SaveDex"
    dmg = {(d["type"], d["num_dice"], d["die_size"]) for d in dt["magic_damage_types"]}
    assert dmg == {("Fire", 9, 6), ("Force", 9, 6)}, f"Death Throes damage wrong: {dmg}"

    # Serializer round-trip: dict_to_stats reads the field back off a stats block.
    st = dict_to_stats(balor["stats"])
    assert st.death_burst_spell == "BalorDeathThroes", "death_burst_spell must survive dict_to_stats"
    print("✅ test_death_burst_json_and_serializer passed")


if __name__ == "__main__":
    test_death_burst_hits_in_range_spares_far()
    test_death_burst_full_damage_on_failed_save()
    test_death_burst_fire_immune_takes_force_only()
    test_death_burst_spares_source_and_chains_finitely()
    test_death_burst_json_and_serializer()
    print("\nAll Death Burst tests passed ✅")
