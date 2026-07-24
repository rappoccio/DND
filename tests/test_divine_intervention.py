#!/usr/bin/env python3
"""
Test Divine Intervention — Phase D0 (the headline feature; reuses the Wish free-cast machinery).

Engine-level coverage (the GUI picker flow is exercised manually):
  - Gate: a Cleric L9 has no DI resource and can_use is False; L10 gains the resource and can_use True.
  - Spend: use_divine_intervention succeeds once and drops the "Divine Intervention" resource to 0.
  - Once per Long Rest: a second use the same day is refused (can_use / use both False).
  - Recharge: apply_long_rest refills the resource; the Greater-DI lock stays 0.
  - Greater DI (L20): choosing Wish sets divine_intervention_lock to 2d4 (2..8) and keeps DI
    unavailable across the locked Long Rests, returning on the Nth.
  - Field round-trips as a plain Stats attribute (serializer coverage lives in agent_loader / main.py).

See DIVINE_INTERVENTION_SPEC.md §3, §8.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

CLERIC = rpg.CharacterClass.Cleric
TEAM = 1


def _make_cleric(engine, bm, level, col=5, row=5, name="Cleric"):
    """Place a single-class Cleric of the given level with its class resources initialized."""
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, TEAM)
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(CLERIC, level)
    s.initialize_class_resources(CLERIC, level)   # creates "Channel Divinity" + (L10+) "Divine Intervention"
    s.can_cast_spell = True
    engine.set_agent_stats(bm, idx, s)
    return idx


def test_gate_l9_vs_l10():
    """L9 Cleric: no DI resource, can_use False. L10 Cleric: resource present, can_use True."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    c9 = _make_cleric(engine, bm, 9, col=4)
    c10 = _make_cleric(engine, bm, 10, col=6)

    assert engine.get_agent_stats(bm, c9).get_resource("Divine Intervention") is None, \
        "L9 Cleric should not have a Divine Intervention resource"
    assert not engine.can_use_divine_intervention(bm, c9), "L9 Cleric cannot use Divine Intervention"

    assert engine.get_agent_stats(bm, c10).get_resource("Divine Intervention") is not None, \
        "L10 Cleric should have a Divine Intervention resource"
    assert engine.can_use_divine_intervention(bm, c10), "L10 Cleric can use Divine Intervention"
    print("✅ test_gate_l9_vs_l10 passed")


def test_spend_once_per_long_rest():
    """A single use succeeds and empties the resource; a second use the same day is refused."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    c = _make_cleric(engine, bm, 10)

    assert engine.use_divine_intervention(bm, c, False), "first DI use should succeed"
    di = engine.get_agent_stats(bm, c).get_resource("Divine Intervention")
    assert di.current == 0, f"DI resource should be spent to 0, got {di.current}"
    assert not engine.can_use_divine_intervention(bm, c), "DI is unavailable after one use"
    assert not engine.use_divine_intervention(bm, c, False), "a second same-day use is refused"
    print("✅ test_spend_once_per_long_rest passed")


def test_recharge_on_long_rest():
    """A Long Rest refills the DI resource (no Greater-DI lock in play)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    c = _make_cleric(engine, bm, 10)

    engine.use_divine_intervention(bm, c, False)
    assert not engine.can_use_divine_intervention(bm, c)

    engine.apply_long_rest(bm)

    s = engine.get_agent_stats(bm, c)
    assert s.divine_intervention_lock == 0, "the recharge lock should be 0 for a normal DI use"
    assert s.get_resource("Divine Intervention").current == 1, "DI should refill on a Long Rest"
    assert engine.can_use_divine_intervention(bm, c), "DI is available again after a Long Rest"
    print("✅ test_recharge_on_long_rest passed")


def test_greater_di_wish_locks_2d4():
    """L20 Wish sets a 2d4 lock; DI stays unavailable for N-1 rests, returns on the Nth."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    c = _make_cleric(engine, bm, 20)

    assert engine.use_divine_intervention(bm, c, True), "Greater-DI Wish use should succeed"
    lock = engine.get_agent_stats(bm, c).divine_intervention_lock
    assert 2 <= lock <= 8, f"Greater-DI lock should be 2d4 (2..8), got {lock}"

    # For each of the first lock-1 Long Rests, DI stays locked (resource held at 0).
    for n in range(lock - 1):
        engine.apply_long_rest(bm)
        s = engine.get_agent_stats(bm, c)
        assert s.divine_intervention_lock == lock - 1 - n, \
            f"lock should count down: expected {lock - 1 - n}, got {s.divine_intervention_lock}"
        assert not engine.can_use_divine_intervention(bm, c), \
            f"DI should stay locked after long rest {n + 1} of {lock}"

    # The final Long Rest clears the lock and refills the resource.
    engine.apply_long_rest(bm)
    s = engine.get_agent_stats(bm, c)
    assert s.divine_intervention_lock == 0, "lock should reach 0 on the final rest"
    assert engine.can_use_divine_intervention(bm, c), "DI returns on the Nth Long Rest"
    print("✅ test_greater_di_wish_locks_2d4 passed")


def test_lock_field_round_trips():
    """divine_intervention_lock is a readable/writable Stats field (serializer wires it in save/load)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    c = _make_cleric(engine, bm, 20)

    s = engine.get_agent_stats(bm, c)
    s.divine_intervention_lock = 5
    engine.set_agent_stats(bm, c, s)

    assert engine.get_agent_stats(bm, c).divine_intervention_lock == 5, \
        "divine_intervention_lock should persist on the agent's Stats"
    print("✅ test_lock_field_round_trips passed")


def run_all():
    test_gate_l9_vs_l10()
    test_spend_once_per_long_rest()
    test_recharge_on_long_rest()
    test_greater_di_wish_locks_2d4()
    test_lock_field_round_trips()
    print("\n✅ All Divine Intervention (D0) tests passed")


if __name__ == "__main__":
    run_all()
