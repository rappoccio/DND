#!/usr/bin/env python3
"""
Regression tests for LIVE_PLAY_BUGFIX_PLAN Phase 5 / L19:
"Incapacitated condition does not get movement speed restored after it clears."

applyIncapacitated (the shared side-effect of Paralyzed / Stunned / Incapacitated) sets the
creature's Speed to 0. The engine previously cleared the incapacitated FLAG when the condition
ended, but never gave the Speed back — so a creature whose movement budget had been zeroed
(e.g. an opportunity attack that inflicted the condition mid-move, per the Phase 3 L8 fix) was
left with a 0 budget even after shaking the condition off.

The fix (restoreMovementAfterIncapacitation, called from the onConditionEnded teardown) re-seeds
BOTH the Stats remaining-speed fields and the Agent's own budget (the one moveAgent /
reachableCells read, exposed here as PlacedAgent.walk_remaining) from the base speeds on EVERY
end path.

`speed_walk_remaining` is not bound on Stats, so these tests assert against the observable
Agent budget (`walk_remaining`) — exactly the value that gates real movement.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

WALK = 30


def _make_target(engine, bm, *, wis=10):
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    target = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 6))
    s = engine.get_agent_stats(bm, target)
    s.speed_walk = WALK
    s.wis = wis
    engine.set_agent_stats(bm, target, s)
    return caster, target


def _incapacitate(engine, bm, caster, target, name, *, save_dc, save_repeat=1):
    c = rpg.ActiveAgentCondition()
    c.agent_idx = target
    c.caster_idx = caster
    c.condition_name = name
    c.save_ability = rpg.SaveAbility.Wisdom
    c.save_dc = save_dc
    c.save_repeat_turns = save_repeat
    c.next_save_turn = 0
    c.turns_remaining = 10
    return engine.add_agent_condition(bm, c)


def test_remove_restores_zeroed_budget():
    """Removing an Incapacitated condition restores a budget that was zeroed while it was active."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster, target = _make_target(engine, bm)

    tok = bm.placed_agents[target]
    tok.init_movement(WALK)
    assert tok.walk_remaining == WALK, "sanity: budget seeded to base speed"

    cid = _incapacitate(engine, bm, caster, target, "Incapacitated", save_dc=8)
    # Simulate the mid-move OA state (Phase 3 L8): the halt zeroes the Agent budget.
    tok.init_movement(0, 0, 0, 0)
    assert tok.walk_remaining == 0, "budget zeroed while incapacitated"
    assert engine.get_agent_conditions(bm, target).incapacitated

    engine.remove_agent_condition(bm, cid)
    assert not engine.get_agent_conditions(bm, target).incapacitated, "condition cleared"
    assert tok.walk_remaining == WALK, "movement budget restored when Incapacitated clears"
    print("✅ test_remove_restores_zeroed_budget passed")


def test_stunned_start_of_turn_save_restores_budget():
    """A Stunned creature that saves at the start of its turn regains its full budget that turn."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster, target = _make_target(engine, bm, wis=30)   # +10 WIS auto-beats DC 8

    tok = bm.placed_agents[target]
    _incapacitate(engine, bm, caster, target, "Stunned", save_dc=8)
    tok.init_movement(0, 0, 0, 0)                         # zeroed while stunned
    assert tok.walk_remaining == 0

    res = engine.begin_turn(bm, target)
    assert not engine.get_agent_conditions(bm, target).stunned, "start-of-turn save frees the creature"
    assert not res.turn_skipped, "a freed creature's turn is not skipped"
    assert tok.walk_remaining == WALK, "budget restored the same turn the Stun clears"
    print("✅ test_stunned_start_of_turn_save_restores_budget passed")


def test_paralyzed_restores_budget_on_clear():
    """Paralyzed (also routed through applyIncapacitated) restores the budget on clear."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster, target = _make_target(engine, bm)

    tok = bm.placed_agents[target]
    cid = _incapacitate(engine, bm, caster, target, "Paralyzed", save_dc=8)
    tok.init_movement(0, 0, 0, 0)
    assert tok.walk_remaining == 0
    assert engine.get_agent_conditions(bm, target).paralyzed

    engine.remove_agent_condition(bm, cid)
    assert not engine.get_agent_conditions(bm, target).paralyzed
    assert tok.walk_remaining == WALK, "Paralyzed teardown restores movement"
    print("✅ test_paralyzed_restores_budget_on_clear passed")


def _run_all():
    tests = [
        test_remove_restores_zeroed_budget,
        test_stunned_start_of_turn_save_restores_budget,
        test_paralyzed_restores_budget_on_clear,
    ]
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} incapacitated-movement-restore tests passed")


if __name__ == "__main__":
    _run_all()
