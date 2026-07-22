#!/usr/bin/env python3
"""
Test the general bonus-action budget (action economy).

The engine tracks bonus_actions_max / bonus_actions_remaining per agent. Every Bonus
Action feature (off-hand attack, Cunning Action, Rage, Healing Word, Divine Smite, ...)
goes through has_bonus_action / spend_bonus_action, and the budget refills to max at the
start of each turn via both code paths: begin_turn (GUI) and run_round (RL/headless).
A feat that grants an extra bonus action simply raises bonus_actions_max.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


def _fresh_agent():
    """A live agent placed on the map; returns (engine, bm, idx)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cfg = create_test_agent("BA Tester", 2, 2)
    idx = add_agent_to_battle(engine, bm, cfg, hp=20)
    return engine, bm, idx


def test_default_budget():
    """A fresh agent has one bonus action available."""
    engine, bm, idx = _fresh_agent()
    s = engine.get_agent_stats(bm, idx)
    assert s.bonus_actions_max == 1, f"Expected max 1, got {s.bonus_actions_max}"
    assert s.bonus_actions_remaining == 1, f"Expected remaining 1, got {s.bonus_actions_remaining}"
    assert engine.has_bonus_action(bm, idx) is True, "Fresh agent should have a bonus action"
    print("✅ test_default_budget passed")


def test_spend_and_exhaust():
    """Spending the bonus action consumes it; a second spend fails."""
    engine, bm, idx = _fresh_agent()
    assert engine.spend_bonus_action(bm, idx) is True, "First spend should succeed"
    s = engine.get_agent_stats(bm, idx)
    assert s.bonus_actions_remaining == 0, f"Expected 0 after spend, got {s.bonus_actions_remaining}"
    assert engine.has_bonus_action(bm, idx) is False, "No bonus action should remain"
    assert engine.spend_bonus_action(bm, idx) is False, "Second spend should fail"
    print("✅ test_spend_and_exhaust passed")


def test_reset_refills():
    """reset_bonus_actions refills remaining to max."""
    engine, bm, idx = _fresh_agent()
    engine.spend_bonus_action(bm, idx)
    engine.reset_bonus_actions(bm, idx)
    s = engine.get_agent_stats(bm, idx)
    assert s.bonus_actions_remaining == s.bonus_actions_max, \
        f"Reset should refill to max, got {s.bonus_actions_remaining}/{s.bonus_actions_max}"
    assert engine.has_bonus_action(bm, idx) is True
    print("✅ test_reset_refills passed")


def test_begin_turn_refills():
    """begin_turn refills the budget (GUI/interactive path)."""
    engine, bm, idx = _fresh_agent()
    engine.spend_bonus_action(bm, idx)
    assert engine.has_bonus_action(bm, idx) is False
    engine.begin_turn(bm, idx)
    assert engine.has_bonus_action(bm, idx) is True, "begin_turn should refill the bonus action"
    s = engine.get_agent_stats(bm, idx)
    assert s.bonus_actions_remaining == s.bonus_actions_max
    print("✅ test_begin_turn_refills passed")


def test_run_round_refills():
    """run_round refills the budget at the start of the round (RL/headless path)."""
    engine, bm, idx = _fresh_agent()
    engine.spend_bonus_action(bm, idx)
    assert engine.has_bonus_action(bm, idx) is False
    ta = rpg.TurnActions()
    ta.agent_idx = idx
    engine.run_round(bm, [ta])
    assert engine.has_bonus_action(bm, idx) is True, "run_round should refill the bonus action"
    print("✅ test_run_round_refills passed")


def test_feat_extra_bonus_action():
    """A feat granting an extra bonus action (max = 2) allows two spends per turn."""
    engine, bm, idx = _fresh_agent()
    s = engine.get_agent_stats(bm, idx)
    s.bonus_actions_max = 2
    engine.set_agent_stats(bm, idx, s)
    engine.reset_bonus_actions(bm, idx)  # refill to the new max
    assert engine.spend_bonus_action(bm, idx) is True, "First of two spends should succeed"
    assert engine.spend_bonus_action(bm, idx) is True, "Second of two spends should succeed"
    assert engine.has_bonus_action(bm, idx) is False, "Both bonus actions now spent"
    assert engine.spend_bonus_action(bm, idx) is False, "Third spend should fail"
    # A new turn restores both.
    engine.begin_turn(bm, idx)
    s = engine.get_agent_stats(bm, idx)
    assert s.bonus_actions_remaining == 2, f"begin_turn should restore 2, got {s.bonus_actions_remaining}"
    print("✅ test_feat_extra_bonus_action passed")


def main():
    print("Running Bonus Action budget tests...")
    print()
    test_default_budget()
    test_spend_and_exhaust()
    test_reset_refills()
    test_begin_turn_refills()
    test_run_round_refills()
    test_feat_extra_bonus_action()
    print()
    print("=" * 60)
    print("✅ All Bonus Action budget tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
