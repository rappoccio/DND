#!/usr/bin/env python3
"""
Test suite for Deny Reactions (Balor Lightning Blade — 2024 MM).

Deny Reactions is a reusable engine feature: a creature under it can take NO
reaction — opportunity attacks, Shield, Uncanny Dodge, etc. — until the START of
the SOURCE's next turn. It rides on Agent.Conditions.reactions_denied, which is
deliberately DISTINCT from reaction_used: the target's own begin_turn resets
reaction_used, but must NOT restore a denied reaction early. The condition is
keyed to the source (caster_idx) with turns_remaining=1, so
tick_agent_conditions_for_caster(source) expires it at the source's next turn.

These tests exercise:
  · the central canTakeReaction gate (via the OA driver) honoring the flag,
  · add_agent_condition("DenyReactions") setting the flag,
  · the source-keyed expiry (and its survival through the target's own turn),
  · independence from reaction_used (no double-charge / no refund).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)

# Reuse the reaction-suite OA harness (scripted decider + move helpers).
from test_reactions import (ScriptedDecider, pick_weapon, equip_oa_weapon,
                            ready_mover, set_cond, reaction_used)


def _deny_condition(target, source, turns=1):
    """Build the ActiveAgentCondition main._apply_lightning_blade_rider will build:
    a DenyReactions lock keyed to the SOURCE, no save, one source-turn long."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx = target
    c.caster_idx = source
    c.spell_idx = -1
    c.condition_name = "DenyReactions"
    c.turns_remaining = turns
    c.save_repeat_turns = -1   # no periodic save; the target's own turn must not strip it
    c.next_save_turn = -1
    return c


# ── The gate: a denied reactor makes no opportunity attack ────────────────────
def test_denied_reactor_makes_no_oa():
    """A creature with reactions_denied set gets no OA when a mover leaves its reach."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    set_cond(engine, bm, a, reactions_denied=True)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert dec.seen == [], f"reactions_denied should block the OA, got {dec.seen}"
    assert not reaction_used(engine, bm, a), "a denied creature never spends its (still-unused) reaction"
    print("✅ test_denied_reactor_makes_no_oa passed")


def test_undenied_reactor_makes_the_oa():
    """Positive control: the same setup WITHOUT the flag provokes an OA."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert [s[0] for s in dec.seen] == [a], f"an un-denied threat should provoke, got {dec.seen}"
    print("✅ test_undenied_reactor_makes_the_oa passed")


# ── Application: the named condition sets the flag ────────────────────────────
def test_denyreactions_condition_sets_flag():
    """add_agent_condition('DenyReactions') sets reactions_denied via the name→flag map."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

    assert not engine.get_agent_conditions(bm, tgt).reactions_denied
    engine.add_agent_condition(bm, _deny_condition(tgt, src))
    assert engine.get_agent_conditions(bm, tgt).reactions_denied, \
        "DenyReactions condition should set reactions_denied"
    print("✅ test_denyreactions_condition_sets_flag passed")


# ── Expiry: lifts at the START of the SOURCE's next turn ──────────────────────
def test_denyreactions_expires_at_source_next_turn():
    """The lock clears when the source's next turn begins (tick_for_caster(source))."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

    engine.add_agent_condition(bm, _deny_condition(tgt, src))
    assert engine.get_agent_conditions(bm, tgt).reactions_denied

    engine.tick_agent_conditions_for_caster(bm, src)
    assert not engine.get_agent_conditions(bm, tgt).reactions_denied, \
        "reactions_denied should lift at the start of the source's next turn"
    print("✅ test_denyreactions_expires_at_source_next_turn passed")


def test_denyreactions_survives_targets_own_turn():
    """If the target acts BEFORE the source's next turn, the lock persists — it is
    keyed to the source, not the target. Guards the reaction_used-vs-reactions_denied split."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

    engine.add_agent_condition(bm, _deny_condition(tgt, src))

    # The target takes its own turn first: begin_turn resets reaction_used, and its
    # caster-scoped tick touches only conditions IT cast — the source's lock stays.
    engine.begin_turn(bm, tgt)
    engine.tick_agent_conditions_for_caster(bm, tgt)
    assert engine.get_agent_conditions(bm, tgt).reactions_denied, \
        "the lock must survive the target's own turn (it expires on the SOURCE's turn)"

    engine.tick_agent_conditions_for_caster(bm, src)
    assert not engine.get_agent_conditions(bm, tgt).reactions_denied, \
        "the lock clears once the source's next turn starts"
    print("✅ test_denyreactions_survives_targets_own_turn passed")


# ── End-to-end: gate reads the condition-driven flag, then releases it ────────
def _oa_scenario_with_condition(clear_before_move):
    """Build a mover+threat+source scene, apply DenyReactions to the threat via the
    named condition, optionally lift it at the source's turn, then move and return
    the reactor indices that got an OA window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Balor", 8, 8))
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("ThreatA", 4, 5))
    ready_mover(engine, bm, m); equip_oa_weapon(engine, bm, a)
    engine.add_agent_condition(bm, _deny_condition(a, src))
    if clear_before_move:
        engine.tick_agent_conditions_for_caster(bm, src)   # source's next turn lifts the lock
        assert not engine.get_agent_conditions(bm, a).reactions_denied

    dec = ScriptedDecider(pick_weapon)
    engine.set_decider(dec)
    engine.resolve_move(bm, m, rpg.Cell(6, 6), rpg.MovementType.Walk)
    return [s[0] for s in dec.seen], a


def test_denyreactions_blocks_then_releases_oa():
    """Condition-driven end-to-end: the flag blocks the OA; after the source's turn it fires again."""
    blocked, _ = _oa_scenario_with_condition(clear_before_move=False)
    assert blocked == [], f"condition-driven deny should block the OA, got {blocked}"

    fired, a = _oa_scenario_with_condition(clear_before_move=True)
    assert fired == [a], f"OA should fire once the source's-turn tick lifts the lock, got {fired}"
    print("✅ test_denyreactions_blocks_then_releases_oa passed")


# ── No double-charge: a spent reaction is independent of the deny flag ─────────
def test_denyreactions_independent_of_used_reaction():
    """Applying DenyReactions must not touch reaction_used, and lifting it must not
    refund a reaction the creature already spent (no double-charge either way)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 5), hp=50)

    # Creature already used its reaction this round.
    set_cond(engine, bm, tgt, reaction_used=True)
    engine.add_agent_condition(bm, _deny_condition(tgt, src))
    c = engine.get_agent_conditions(bm, tgt)
    assert c.reaction_used and c.reactions_denied, "deny sits alongside an already-spent reaction"

    # Lifting the deny at the source's turn clears ONLY reactions_denied — the spent
    # reaction stays spent (its own begin_turn is what refunds it).
    engine.tick_agent_conditions_for_caster(bm, src)
    c = engine.get_agent_conditions(bm, tgt)
    assert not c.reactions_denied, "deny lifted"
    assert c.reaction_used, "lifting the deny must not refund the already-used reaction"
    print("✅ test_denyreactions_independent_of_used_reaction passed")


if __name__ == "__main__":
    test_denied_reactor_makes_no_oa()
    test_undenied_reactor_makes_the_oa()
    test_denyreactions_condition_sets_flag()
    test_denyreactions_expires_at_source_next_turn()
    test_denyreactions_survives_targets_own_turn()
    test_denyreactions_blocks_then_releases_oa()
    test_denyreactions_independent_of_used_reaction()
    print("\nAll Deny Reactions tests passed ✅")
