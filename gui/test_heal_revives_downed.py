#!/usr/bin/env python3
"""
Regression test: healing a downed (unconscious, 0 HP) player character returns
them to consciousness and resets death saves, so they are NOT skipped in the
initiative order on their next turn.

Bug: healAgent (and the other heal sites) only restored HP — they left the
`unconscious` condition set, so begin_turn kept skipping the healed PC. Fixed by
CombatEngine::reviveOnHeal, called after every heal path.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


def _down_agent(engine, bm, idx, failures=1):
    """Put a PC into the downed state: 0 HP, unconscious, some death-save failures."""
    stats = engine.get_agent_stats(bm, idx)
    stats.hp_cur = 0
    engine.set_agent_stats(bm, idx, stats)
    cond = engine.get_agent_conditions(bm, idx)
    cond.unconscious = True
    cond.incapacitated = True
    cond.prone = True
    cond.death_save_failures = failures
    engine.set_agent_conditions(bm, idx, cond)


def test_heal_clears_downed_state():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5, hp=20))

    _down_agent(engine, bm, idx, failures=2)
    assert engine.get_agent_stats(bm, idx).hp_cur == 0
    assert engine.get_agent_conditions(bm, idx).unconscious
    print("✅ Hero is downed (0 HP, unconscious, 2 death-save failures)")

    new_hp = rpg.CombatEngine.heal_agent(bm, idx, 7)
    assert new_hp == 7, f"expected 7 HP, got {new_hp}"

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.unconscious is False, "still unconscious after heal"
    assert cond.incapacitated is False, "still incapacitated after heal"
    assert cond.death_save_failures == 0, "death-save failures not reset"
    assert cond.death_save_successes == 0
    print("✅ Healing cleared unconscious/incapacitated and reset death saves")


def test_healed_pc_not_skipped_on_turn():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5, hp=20))

    _down_agent(engine, bm, idx, failures=1)
    rpg.CombatEngine.heal_agent(bm, idx, 5)

    res = engine.begin_turn(bm, idx)
    assert not res.turn_skipped, f"healed PC should act, got skip: {res.skip_reason}"
    assert engine.get_agent_stats(bm, idx).hp_cur == 5
    print("✅ Healed PC takes their turn (not skipped in initiative)")


def test_heal_does_not_revive_the_truly_dead():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Corpse", 5, 5, hp=20))

    stats = engine.get_agent_stats(bm, idx)
    stats.hp_cur = 0
    engine.set_agent_stats(bm, idx, stats)
    cond = engine.get_agent_conditions(bm, idx)
    cond.unconscious = True
    cond.dead = True
    engine.set_agent_conditions(bm, idx, cond)

    rpg.CombatEngine.heal_agent(bm, idx, 10)
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.dead is True, "healing must not resurrect the truly dead"
    assert cond.unconscious is True, "dead creature should stay unconscious"
    print("✅ Plain healing does not revive a dead creature")


if __name__ == "__main__":
    test_heal_clears_downed_state()
    test_healed_pc_not_skipped_on_turn()
    test_heal_does_not_revive_the_truly_dead()
    print("\nAll heal-revives-downed tests passed ✅")
