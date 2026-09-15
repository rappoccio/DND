#!/usr/bin/env python3
"""Snapshot / restore round-trip tests (COMBAT_REFACTOR_PLAN.md R5).

R5 gives CombatEngine `snapshot_json()` / `restore_json()` — a full serialization of
the engine's combat state, which is what MULTIPLAYER_PLAN.md's "Engine-state
serialization" TODO is blocked on and what mid-combat save/resume needs.

The interesting property is not "the JSON contains the right keys" — it is that a
restored engine is INDISTINGUISHABLE from the one the snapshot was taken from. Every
test below is therefore behavioral where it can be: snapshot, keep playing, restore,
replay the same script, and require the two runs to agree exactly. That catches the
failure modes a field-by-field comparison misses — an RNG restored from its seed
instead of its state, a cursor dropped from a parked reaction window, a condition
container rebuilt in a different order.

Covered here:
  · the RNG stream continues rather than restarts       (test_rng_state_continues)
  · a restored engine replays a scripted fight identically
                                                        (test_replay_after_restore)
  · snapshot → restore → snapshot is stable             (test_round_trip_is_stable)
  · active conditions + effects survive, and post-snapshot mutations are undone
                                                        (test_conditions_round_trip)
  · a SUSPENDED reaction window survives and still resumes
                                                        (test_parked_reaction_round_trips)
  · malformed / future-version payloads are refused rather than half-applied
                                                        (test_bad_payloads_refused)
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)
from test_reactions import equip_oa_weapon, ready_mover, pick_weapon


SEED = 20260915


# ── Scene ────────────────────────────────────────────────────────────────────
def _melee_weapon(name="Longsword", die_size=8):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    return w


def _build_scene():
    """Two adjacent duellists with plenty of HP, so a long scripted exchange runs
    without anyone dropping (a death mid-replay would end the script early and make
    the comparison vacuous)."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(SEED)

    hero = add_agent_to_battle(engine, bm, create_test_agent("Hero", 4, 4))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 5, 4))

    for idx, ac in ((hero, 14), (foe, 13)):
        s = engine.get_agent_stats(bm, idx)
        s.str, s.dex, s.con, s.intel, s.wis, s.cha = 16, 14, 16, 10, 10, 10
        s.hp_max = s.hp_cur = 400
        s.base_ac = ac
        s.speed_walk = 30
        engine.set_agent_stats(bm, idx, s)
        engine.set_agent_weapons(bm, idx, [_melee_weapon(), rpg.Weapon(), rpg.Weapon()])

    bm.set_agent_faction(hero, 1)
    bm.set_agent_faction(foe, 2)
    return bm, engine, hero, foe


def _script(engine, bm, hero, foe, rounds=4):
    """Play a fixed exchange and return a comparable transcript of every outcome."""
    out = []
    for _ in range(rounds):
        for attacker, defender in ((hero, foe), (foe, hero)):
            engine.begin_turn(bm, attacker)
            r = engine.execute_action(bm, rpg.Attack(attacker, defender, 0))
            out.append((r.d20, r.total_roll, r.hit, r.total_damage,
                        engine.get_agent_stats(bm, defender).hp_cur))
            engine.end_turn(bm, attacker)
    return out


def _canon(obj):
    """Order-insensitive view of a snapshot document.

    The engine's int-keyed state lives in unordered_maps, so the ARRAY ORDER of
    agent_turns / safe_targets / the visibility cache / … is an implementation detail
    that a rebuild after restore is free to change. Sorting every list makes the
    structural comparison in test_round_trip_is_stable check content rather than
    iteration order; the ordering that genuinely matters (condition order, cast stack
    depth, reactor cursors) is covered behaviorally by the replay tests instead."""
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return sorted((_canon(v) for v in obj), key=lambda v: json.dumps(v, sort_keys=True))
    return obj


# ── Tests ────────────────────────────────────────────────────────────────────
def test_rng_state_continues():
    """A restored engine must CONTINUE the mt19937 stream, not restart it.

    This is the single most important property of the whole phase: CombatContext
    serializes the generator's state rather than the seed precisely so that a resumed
    fight cannot reroll dice it already rolled. Rolling a few times before the snapshot
    is what makes state-vs-seed distinguishable."""
    engine = rpg.CombatEngine(SEED)
    for _ in range(7):
        engine.roll(20)

    snap = engine.snapshot_json()
    expected = [engine.roll(20) for _ in range(40)]

    assert engine.restore_json(snap), "restore_json rejected its own snapshot"
    actual = [engine.roll(20) for _ in range(40)]
    assert actual == expected, f"RNG stream diverged after restore:\n  {expected}\n  {actual}"

    # And a seed-restored engine must NOT match — otherwise the assertion above would
    # pass even if to_json had stored the seed.
    reseeded = rpg.CombatEngine(SEED)
    assert [reseeded.roll(20) for _ in range(40)] != expected, \
        "a freshly seeded engine reproduced the post-snapshot stream — snapshot is storing the seed"
    print("✅ test_rng_state_continues passed")


def test_replay_after_restore():
    """Snapshot mid-fight, play on, restore, replay: both runs must agree exactly."""
    bm, engine, hero, foe = _build_scene()
    _script(engine, bm, hero, foe, rounds=2)          # get some state on the board

    snap = engine.snapshot_json()
    hp_at_snapshot = (engine.get_agent_stats(bm, hero).hp_cur,
                      engine.get_agent_stats(bm, foe).hp_cur)
    first = _script(engine, bm, hero, foe, rounds=4)

    # Rewind BOTH halves of the world: the engine from its snapshot, the map by hand
    # (agent HP lives in BattleMap, which snapshot() deliberately does not cover).
    assert engine.restore_json(snap), "restore_json rejected its own snapshot"
    for idx, hp in zip((hero, foe), hp_at_snapshot):
        s = engine.get_agent_stats(bm, idx)
        s.hp_cur = hp
        engine.set_agent_stats(bm, idx, s)

    second = _script(engine, bm, hero, foe, rounds=4)
    assert first == second, (
        "replay after restore diverged\n"
        f"  before: {first}\n"
        f"  after:  {second}")
    print("✅ test_replay_after_restore passed")


def test_round_trip_is_stable():
    """snapshot → restore → snapshot must produce the same document.

    A field that serializes but does not deserialize (a typo'd key, a member left out
    of restore()) shows up here as a second snapshot that has lost it."""
    bm, engine, hero, foe = _build_scene()
    _script(engine, bm, hero, foe, rounds=3)

    first = engine.snapshot_json()
    assert engine.restore_json(first)
    second = engine.snapshot_json()

    a, b = _canon(json.loads(first)), _canon(json.loads(second))
    assert a == b, "snapshot is not idempotent across a restore"

    doc = json.loads(first)
    assert doc["version"] == 1
    # Every member group the plan's R4 table and MULTIPLAYER_PLAN.md's TODO name.
    for key in ("context", "movement", "conditions", "visibility", "agent_turns",
                "active_effects", "safe_targets", "zone_applied_turn",
                "death_burst_fired", "pending_decision", "in_flight_move",
                "in_flight_attack", "in_flight_turn", "cast_stack", "npc_turn"):
        assert key in doc, f"snapshot is missing '{key}'"
    print("✅ test_round_trip_is_stable passed")


def test_conditions_round_trip():
    """Active conditions survive, and a change made AFTER the snapshot is undone."""
    bm, engine, hero, foe = _build_scene()

    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = foe
    cond.caster_idx = hero
    cond.condition_name = "Paralyzed"
    cond.turns_remaining = 9
    cond.save_dc = 15
    cid = engine.add_agent_condition(bm, cond)

    snap = engine.snapshot_json()
    before = [(c.condition_id, c.agent_idx, c.condition_name, c.turns_remaining)
              for c in engine.active_agent_conditions]
    assert before, "setup failed — no condition was tracked"

    engine.remove_agent_condition(bm, cid)
    assert not [c for c in engine.active_agent_conditions if c.condition_id == cid]

    assert engine.restore_json(snap)
    after = [(c.condition_id, c.agent_idx, c.condition_name, c.turns_remaining)
             for c in engine.active_agent_conditions]
    assert after == before, f"conditions did not round-trip:\n  {before}\n  {after}"

    # The id counter has to come back too, or the next condition reuses a live id and
    # a later remove_agent_condition() ends the wrong one.
    nxt = rpg.ActiveAgentCondition()
    nxt.agent_idx = hero
    nxt.condition_name = "Blinded"
    nxt.turns_remaining = 2
    assert engine.add_agent_condition(bm, nxt) != cid, \
        "next_condition_id was not restored — a fresh condition reused a live id"
    print("✅ test_conditions_round_trip passed")


def test_parked_reaction_round_trips():
    """A suspended reaction window survives a snapshot and still resumes.

    MULTIPLAYER_PLAN.md asks for this by name ("plus any parked attack / reaction
    decision state, so a restore can resume a suspended reaction window"). The whole
    in-flight move — the provoke list, the cursor into it, and the pending decision the
    GUI polls — has to come back or submit_decision() resumes into nothing."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    mover = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    threat = add_agent_to_battle(engine, bm, create_test_agent("Threat", 4, 5))
    ready_mover(engine, bm, mover)
    equip_oa_weapon(engine, bm, threat)

    # No decider installed → begin_move parks at the OA checkpoint.
    status = engine.begin_move(bm, mover, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected a park, got {status}"

    snap = engine.snapshot_json()
    doc = json.loads(snap)
    assert doc["pending_decision"]["active"], "the parked decision was not captured"
    assert doc["in_flight_move"]["active"], "the in-flight move was not captured"

    parked = engine.pending_decision()
    reactor, window = parked.ctx.reactor_idx, parked.ctx.window
    labels = [o.label for o in parked.ctx.options]

    # Clobber the park (a full, legal resume), then rewind to the suspended state.
    resp = rpg.ReactionResponse()
    resp.option = pick_weapon(parked.ctx)
    engine.submit_decision(bm, resp)
    assert not engine.pending_decision().active

    # Rewind the map half by hand, as a real restore would (the threat's spent reaction
    # and the mover's position live in BattleMap, which snapshot() does not cover).
    tc = engine.get_agent_conditions(bm, threat)
    tc.reaction_used = False
    engine.set_agent_conditions(bm, threat, tc)

    assert engine.restore_json(snap)
    again = engine.pending_decision()
    assert again.active, "the decision did not come back parked"
    assert (again.ctx.reactor_idx, again.ctx.window) == (reactor, window)
    assert [o.label for o in again.ctx.options] == labels, "the vetted option list changed"

    # And it still drives to completion, which is what makes the restored park usable
    # rather than merely present.
    resp2 = rpg.ReactionResponse()
    resp2.option = pick_weapon(again.ctx)
    assert engine.submit_decision(bm, resp2) == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active
    print("✅ test_parked_reaction_round_trips passed")


def test_bad_payloads_refused():
    """Malformed, wrong-shaped and future-version payloads return False, not an
    exception crossing the pybind11 boundary."""
    engine = rpg.CombatEngine(SEED)
    for payload in ("", "   ", "not json at all", "[1, 2, 3]", "42", "null",
                    '{"version": 999999}'):
        assert engine.restore_json(payload) is False, f"accepted a bad payload: {payload!r}"

    # A well-formed document with the right version but a wrong-typed member must also
    # be refused rather than throwing out of get<T>().
    assert engine.restore_json('{"version": 1, "cast_stack": "nope"}') is False

    # An EMPTY object is legal: every member is optional, so it means "change nothing".
    assert engine.restore_json('{"version": 1}') is True
    print("✅ test_bad_payloads_refused passed")


def main():
    tests = [
        test_rng_state_continues,
        test_replay_after_restore,
        test_round_trip_is_stable,
        test_conditions_round_trip,
        test_parked_reaction_round_trips,
        test_bad_payloads_refused,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_snapshot: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_snapshot: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
