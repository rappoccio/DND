#!/usr/bin/env python3
"""
Test suite for the simulation trace (NPC_LEARNING_PLAN.md Step 1, gui/sim_trace.py).

A trace is header + one record per turn (snapshot, visual events, log lines) + footer.
These tests record real engine turns, load the file back, and require the identical event
stream, field for field — Playback (Step 2) replays exactly what comes out of load_trace.
"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import sim_trace
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)

_FIELDS = ("kind", "agent_idx", "target_idx", "text", "good", "hp_after", "died")


def _fields(ev):
    """An event as a comparable tuple: the scalar fields plus the path as (col, row) pairs."""
    return tuple(getattr(ev, f) for f in _FIELDS) + (
        tuple((c.col, c.row) for c in ev.path),)


def _snapshot(bm):
    """The data App._npc_anim_snapshot takes (main.py), without an App."""
    return {i: {"pos": (float(pt.origin.col), float(pt.origin.row)),
                "hp": pt.stats.hp_cur, "was_alive": not pt.conditions.dead}
            for i, pt in enumerate(bm.placed_agents) if not pt.removed_from_play}


def _melee_duel():
    """Two automated melee NPCs on opposite sides, three cells apart."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5), hp=30)
    b = add_agent_to_battle(engine, bm, create_test_agent("Hero", 8, 5), hp=30)
    bm.set_agent_faction(a, 1)
    bm.set_agent_faction(b, 2)
    for i in (a, b):
        engine.set_agent_weapons(bm, i, [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
        bm.set_agent_npc_automated(i, True)
    return bm, engine, a, b


def _record_turns(path, bm, engine, order, rounds=2):
    """Run `rounds` rounds of automated turns into a trace at `path`; return what the engine
    emitted per turn, so the caller can compare it with what loads back."""
    w = sim_trace.TraceWriter(path, map_path="maps/test.png", agents={"agents": []},
                              seed=1234, npc_policy="level4", pc_mode="Heuristic",
                              initiative=[(i, bm.placed_agents[i].name, 10) for i in order])
    w.add_log("Combat begins.")          # before any turn: the prelude record
    emitted = []
    for r in range(1, rounds + 1):
        for idx in order:
            if bm.placed_agents[idx].conditions.dead:
                continue
            w.begin_turn(round_num=r, actor=idx, actor_name=bm.placed_agents[idx].name,
                         driver=sim_trace.DRIVER_NPC, snapshot=_snapshot(bm))
            engine.begin_turn(bm, idx)
            assert engine.run_npc_turn(bm, idx) == rpg.FlowStatus.Completed
            events = engine.take_npc_visual_events()
            w.add_events(events)
            w.add_log(f"turn {r}/{idx}")
            emitted.append([_fields(e) for e in events])
    return w, emitted


# ── Kind table ───────────────────────────────────────────────────────────────
def test_kind_table_matches_engine_enum():
    """The on-disk kind strings are pinned to NpcVisualEvent.Kind, so a reordered or grown C++
    enum fails here instead of replaying a move as an outcome."""
    K = rpg.NpcVisualEvent.Kind
    assert sim_trace._KIND_TO_STR == {int(K.Move): "move", int(K.Announce): "announce",
                                      int(K.Outcome): "outcome"}
    assert len(K.__members__) == 3, f"new NpcVisualEvent kind: {list(K.__members__)}"
    print("✅ test_kind_table_matches_engine_enum passed")


# ── Record → load → identical event stream ──────────────────────────────────
def test_round_trip_identical_event_stream():
    bm, engine, a, b = _melee_duel()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.jsonl")
        w, emitted = _record_turns(path, bm, engine, [a, b])
        w.close({"reason": "end", "winner": None})
        tr = sim_trace.load_trace(path)

    assert tr.complete and tr.footer == {"reason": "end", "winner": None}
    assert tr.header["seed"] == 1234 and tr.header["pc_mode"] == "Heuristic"
    assert tr.header["version"] == sim_trace.TRACE_VERSION
    prelude, turns = tr.turns[0], tr.turns[1:]
    assert prelude.actor == -1 and prelude.log == ["Combat begins."] and prelude.snapshot is None
    assert len(turns) == len(emitted)
    assert any(emitted), "the duel must have produced visual events"
    for t, ev in zip(turns, emitted):
        assert [_fields(e) for e in t.events] == ev, "event stream changed in the round trip"
        assert t.driver == sim_trace.DRIVER_NPC
        assert t.log == [f"turn {t.round}/{t.actor}"]
    kinds = {e.kind for t in turns for e in t.events}
    assert {0, 1, 2} <= kinds, f"expected move/announce/outcome in the duel, got {kinds}"
    print("✅ test_round_trip_identical_event_stream passed")


def test_snapshot_round_trip():
    """The snapshot comes back in _npc_anim_start's shape: int keys, tuple positions."""
    bm, engine, a, b = _melee_duel()
    snap = _snapshot(bm)
    assert sim_trace.snapshot_from_list(
        json.loads(json.dumps(sim_trace.snapshot_to_list(snap)))) == snap
    print("✅ test_snapshot_round_trip passed")


def test_loaded_events_have_engine_attributes():
    """TraceEvent answers every attribute the GUI playback reads off an engine event, so
    _npc_anim_start takes either."""
    bm, engine, a, b = _melee_duel()
    engine.begin_turn(bm, a)
    engine.run_npc_turn(bm, a)
    for ev in engine.take_npc_visual_events():
        back = sim_trace.event_from_dict(json.loads(json.dumps(sim_trace.event_to_dict(ev))))
        assert _fields(back) == _fields(ev)
        assert all(hasattr(c, "col") and hasattr(c, "row") for c in back.path)
    print("✅ test_loaded_events_have_engine_attributes passed")


# ── Cut short / refused ──────────────────────────────────────────────────────
def test_cut_short_trace_loads_without_footer():
    bm, engine, a, b = _melee_duel()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.jsonl")
        w, emitted = _record_turns(path, bm, engine, [a, b], rounds=1)
        # No close(): the turn in progress is lost, every finished one is on disk.
        tr = sim_trace.load_trace(path)
        w.close()
    assert not tr.complete
    assert len(tr.turns) == 1 + len(emitted) - 1   # prelude + all but the open turn
    print("✅ test_cut_short_trace_loads_without_footer passed")


def test_unknown_kind_and_newer_version_refused():
    try:
        sim_trace.event_from_dict({"kind": "teleport", "agent": 0, "target": -1, "path": [],
                                   "text": "", "good": False, "hp_after": -1, "died": False})
        assert False, "unknown kind accepted"
    except ValueError:
        pass
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "header", "version": sim_trace.TRACE_VERSION + 1}) + "\n")
        try:
            sim_trace.load_trace(path)
            assert False, "newer trace version accepted"
        except ValueError:
            pass
    print("✅ test_unknown_kind_and_newer_version_refused passed")


def test_close_is_idempotent_and_unwritable_path_is_harmless():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.jsonl")
        w = sim_trace.TraceWriter(path, map_path="", agents=None, seed=0,
                                  npc_policy="gui", pc_mode="Human")
        w.close({"reason": "end"})
        w.close({"reason": "again"})
        assert sim_trace.load_trace(path).footer == {"reason": "end"}
        bad = sim_trace.TraceWriter(os.path.join(d, "no", "such", "dir", "t.jsonl"),
                                    map_path="", agents=None, seed=0,
                                    npc_policy="gui", pc_mode="Human")
        assert not bad.active
        bad.add_log("ignored")
        bad.close()
    print("✅ test_close_is_idempotent_and_unwritable_path_is_harmless passed")


# ── The GUI writes one per fight ─────────────────────────────────────────────
def test_gui_fight_writes_a_trace():
    """A real App fight (the restore oracle's: two PCs, two foes, an automated Gnasher) writes
    a trace: the agents in the raw index basis, a record per turn with the right driver and a
    snapshot, Gnasher's turn carrying exactly the events the board played, and a footer."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import shutil
    from main import App
    from test_restore_oracle import _fight, _idx

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "sim_trace.jsonl")
    saved, App.SIM_TRACE_FILE = App.SIM_TRACE_FILE, path
    try:
        app = _fight(tmp, hard=True)
        gnasher = _idx(app, "Gnasher")
        app._drive_npc_turn_if_pending()
        assert app._npc_anim is not None, "Gnasher's turn played nothing"
        played = [_fields(e) for e in app._npc_anim["events"]]
        app._npc_anim_finish()                      # → _advance_turn: the next turn begins
        app._end_combat()
        tr = sim_trace.load_trace(path)
    finally:
        App.SIM_TRACE_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)

    h = tr.header
    assert not h["resumed"] and h["pc_mode"] == "Human"
    # _fight summons a Wolf and an Imp after combat starts: they arrive as `spawned`, and
    # header + spawned is the whole board in the raw index basis (the Imp is a tombstone).
    spawned = [a for t in tr.turns for a in t.spawned]
    roster = h["agents"]["agents"] + spawned
    assert [a["name"] for a in roster] == [pt.name for pt in app.bm.placed_agents], \
        "header + spawned is not the raw agent list"
    assert {a["name"] for a in spawned} == {"Wolf", "Imp"}
    assert h["map"].endswith("TestGrid12x12.png")
    assert tr.complete and tr.footer["reason"] == "end"
    mine = [t for t in tr.turns if t.actor == gnasher]
    assert mine and mine[-1].driver == sim_trace.DRIVER_NPC
    assert [_fields(e) for e in mine[-1].events] == played
    assert mine[-1].snapshot and gnasher in mine[-1].snapshot
    humans = [t for t in tr.turns if t.actor >= 0 and t.actor != gnasher]
    assert humans and all(t.driver == sim_trace.DRIVER_HUMAN for t in humans
                          if t.actor in (_idx(app, "Aria"), _idx(app, "Brannor")))
    assert any(t.log for t in tr.turns), "no combat-log lines were recorded"
    print("✅ test_gui_fight_writes_a_trace passed")


if __name__ == "__main__":
    test_kind_table_matches_engine_enum()
    test_round_trip_identical_event_stream()
    test_snapshot_round_trip()
    test_loaded_events_have_engine_attributes()
    test_cut_short_trace_loads_without_footer()
    test_unknown_kind_and_newer_version_refused()
    test_close_is_idempotent_and_unwritable_path_is_harmless()
    test_gui_fight_writes_a_trace()
    print("\nAll sim trace tests passed! 🎉")
