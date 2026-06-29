#!/usr/bin/env python3
"""
Test suite for the Green Slaad's Chaos Staff on-hit rider.

Chaos Staff (2024 MM): "Melee or Ranged Attack Roll, +7, reach 10 feet or range
60 feet. Hit: 1d8+4 Force damage. Until the start of the Slaad's next turn, the
target has a condition determined by rolling 1d4: on a 1, Charmed; on a 2,
Frightened; on a 3, Poisoned; on a 4, Incapacitated."

The 1d4 condition pick lives in Python (main._apply_chaos_staff_rider); the C++
engine owns the rest — add_agent_condition fully sets the condition flag, and
tick_agent_conditions_for_caster expires it when the caster's next turn begins.
These tests guard the shipped JSON record and the engine-level apply/expire
behavior the Python rider depends on (turns_remaining=1, caster-scoped tick).
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

# The 1d4 → condition map, mirroring main._apply_chaos_staff_rider.
CHAOS_STAFF_CONDITIONS = {1: "Charmed", 2: "Frightened", 3: "Poisoned", 4: "Incapacitated"}


def _condition_flag(conds, name):
    """Read the boolean flag on an Agent.Conditions object for a condition name."""
    return {
        "Charmed":       conds.charmed,
        "Frightened":    conds.frightened,
        "Poisoned":      conds.poisoned,
        "Incapacitated": conds.incapacitated,
    }[name]


def test_chaos_staff_json_record():
    """Guard the data: Green Slaad's melee + ranged attacks are the Chaos Staff (+7, 1d8 Force)."""
    stats_path = os.path.join(os.path.dirname(__file__), "DND2024_MonsterStats.json")
    with open(stats_path) as f:
        data = json.load(f)

    weapons = data["Green Slaad"]["weapons"]
    melee = weapons["main_hand"]
    ranged = weapons["ranged"]

    assert melee["name"] == "Chaos Staff", "melee attack should be the Chaos Staff (Python detects by name)"
    assert ranged["name"] == "Chaos Staff", "ranged attack should be the Chaos Staff"

    assert melee["reach_ft"] == 10, "Chaos Staff melee reach is 10 ft"
    assert ranged["normal_range_ft"] == 60, "Chaos Staff range is 60 ft"

    # 1d8 Force base; the +4 comes from bonus_damage + the engine's auto ability mod.
    for w in (melee, ranged):
        dmg = w["magic_damage_types"][0]
        assert dmg["type"] == "Force" and dmg["num_dice"] == 1 and dmg["die_size"] == 8, \
            "Chaos Staff deals 1d8 Force"

    # +7 to hit: STR/DEX mod + PB(3) + bonus_hit. Melee STR16(+3)+3+1=7, ranged DEX14(+2)+3+2=7.
    assert melee["bonus_hit"] == 1, "melee bonus_hit should bring STR+PB to +7"
    assert ranged["bonus_hit"] == 2, "ranged bonus_hit should bring DEX+PB to +7"
    print("✅ test_chaos_staff_json_record passed")


def test_chaos_staff_d4_map_is_complete():
    """The 1d4 table covers exactly the four book conditions."""
    assert set(CHAOS_STAFF_CONDITIONS.keys()) == {1, 2, 3, 4}
    assert CHAOS_STAFF_CONDITIONS == {
        1: "Charmed", 2: "Frightened", 3: "Poisoned", 4: "Incapacitated"}
    print("✅ test_chaos_staff_d4_map_is_complete passed")


def test_chaos_staff_condition_applies_and_expires():
    """Each of the four conditions applies on the target and clears at the Slaad's next turn.

    Mirrors exactly what main._apply_chaos_staff_rider builds: an ActiveAgentCondition
    with caster=Slaad, turns_remaining=1. tick_agent_conditions_for_caster(Slaad) — run
    at the start of the Slaad's next turn — must decrement it to 0 and lift the flag.
    """
    for roll, name in CHAOS_STAFF_CONDITIONS.items():
        bm = setup_battle_map()
        engine = setup_combat_engine()
        slaad = add_agent_to_battle(engine, bm, create_test_agent("Green Slaad", 2, 5))
        tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

        cond = rpg.ActiveAgentCondition()
        cond.agent_idx = tgt
        cond.caster_idx = slaad
        cond.spell_idx = -1
        cond.condition_name = name
        cond.turns_remaining = 1
        engine.add_agent_condition(bm, cond)

        applied = engine.get_agent_conditions(bm, tgt)
        assert _condition_flag(applied, name), \
            f"1d4={roll}: target should be {name} after a Chaos Staff hit"

        # Start of the Slaad's next turn → its caster-scoped conditions tick down and expire.
        engine.tick_agent_conditions_for_caster(bm, slaad)

        after = engine.get_agent_conditions(bm, tgt)
        assert not _condition_flag(after, name), \
            f"1d4={roll}: {name} should clear at the start of the Slaad's next turn"
    print("✅ test_chaos_staff_condition_applies_and_expires passed")


def test_chaos_staff_persists_through_a_victim_turn():
    """The condition survives the victim's own turn — it is keyed to the Slaad, not the target.

    tick_agent_conditions_for_caster only ticks conditions cast by the agent whose turn is
    starting, so the victim taking a turn (and any unrelated creature) must NOT clear it.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()
    slaad = add_agent_to_battle(engine, bm, create_test_agent("Green Slaad", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = tgt
    cond.caster_idx = slaad
    cond.spell_idx = -1
    cond.condition_name = "Poisoned"
    cond.turns_remaining = 1
    engine.add_agent_condition(bm, cond)

    # The victim's own turn begins — its caster-scoped tick must not touch the Slaad's rider.
    engine.tick_agent_conditions_for_caster(bm, tgt)
    assert engine.get_agent_conditions(bm, tgt).poisoned, \
        "Poisoned should persist through the victim's turn (it expires on the SLAAD's turn)"

    engine.tick_agent_conditions_for_caster(bm, slaad)
    assert not engine.get_agent_conditions(bm, tgt).poisoned, \
        "Poisoned should clear once the Slaad's next turn starts"
    print("✅ test_chaos_staff_persists_through_a_victim_turn passed")


if __name__ == "__main__":
    test_chaos_staff_json_record()
    test_chaos_staff_d4_map_is_complete()
    test_chaos_staff_condition_applies_and_expires()
    test_chaos_staff_persists_through_a_victim_turn()
    print("\nAll Green Slaad Chaos Staff tests passed ✅")
