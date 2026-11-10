#!/usr/bin/env python3
"""GUI Playback mode (NPC_LEARNING_PLAN.md Step 2, gui/playback.py). Not the M4b.3 browser
playback, which is test_playback.py.

A real App fight writes a trace (Step 1), then Playback opens it: the board is seeded from
each turn's snapshot, a turn replays its recorded events through `_npc_anim_start`, Step /
Step back / the scrubber land on the right snapshots, every event is the mode's own, and
leaving puts back the DM's scene, the same objects, with no file written.
"""

import os
import sys
import shutil
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first
import pygame

import sim_trace
import playback
from constants import COL_BG
from main import App
from test_restore_oracle import _fight, _idx
from test_sim_trace import _fields


# ── Pure helpers ─────────────────────────────────────────────────────────────
def _ev(kind, agent, path=(), hp_after=-1, died=False):
    return sim_trace.TraceEvent(kind=kind, agent_idx=agent,
                                path=[sim_trace.TraceCell(c, r) for c, r in path],
                                hp_after=hp_after, died=died)


def test_fold_events():
    snap = {0: {"pos": (1.0, 1.0), "hp": 10, "was_alive": True},
            1: {"pos": (5.0, 5.0), "hp": 7, "was_alive": True}}
    out = playback.fold_events(snap, [
        _ev(0, 0, path=[(1, 1), (2, 1), (3, 2)]),     # move: lands on the route's end
        _ev(1, 0),                                     # announce: no state
        _ev(2, 1, hp_after=0, died=True),              # outcome: HP and death
        _ev(2, 9, hp_after=3)])                        # an agent not in the snapshot: ignored
    assert out[0]["pos"] == (3.0, 2.0) and out[0]["hp"] == 10
    assert out[1] == {"pos": (5.0, 5.0), "hp": 0, "was_alive": False}
    assert snap[0]["pos"] == (1.0, 1.0), "fold_events changed its input"
    print("✅ test_fold_events passed")


def test_roster_and_playable_turns():
    turn = lambda actor, snap, spawned=(): sim_trace.TraceTurn(
        round=0, actor=actor, actor_name="", driver="npc", snapshot=snap, events=[], log=[],
        spawned=list(spawned))
    tr = sim_trace.Trace(
        header={"agents": {"agents": [{"name": "A"}, {"name": "B"}]}},
        turns=[turn(-1, None), turn(0, {}), turn(1, {}, [{"name": "Wolf"}])], footer=None)
    assert [a["name"] for a in playback.roster(tr)] == ["A", "B", "Wolf"]
    assert [t.actor for t in playback.playable_turns(tr)] == [0, 1], "the prelude is not a turn"
    assert playback.roster(sim_trace.Trace(header={"agents": None}, turns=[],
                                           footer=None)) is None
    assert playback.outcome_text(tr) == "cut short (no footer)"
    print("✅ test_roster_and_playable_turns passed")


# ── A recorded fight, played back ────────────────────────────────────────────
def _board(app):
    """What the board shows, per agent: in play, cell, HP, dead."""
    out = []
    for i, pt in enumerate(app.bm.placed_agents):
        st = app.combat.get_agent_stats(app.bm, i)
        out.append((pt.name, pt.removed_from_play, pt.origin.col, pt.origin.row,
                    st.hp_cur, bool(app.combat.get_agent_conditions(app.bm, i).dead)))
    return out


def _expect(app, snap):
    """The board shows `snap`: those agents in play at their cells and HP, the rest out."""
    for i, (name, removed, col, row, hp, dead) in enumerate(_board(app)):
        s = snap.get(i)
        if s is None:
            assert removed, f"{name} should be out of play"
            continue
        assert not removed, f"{name} should be in play"
        assert (col, row) == (round(s["pos"][0]), round(s["pos"][1])), f"{name} cell"
        assert hp == s["hp"], f"{name} HP {hp} != {s['hp']}"
        assert dead == (not s["was_alive"]), f"{name} dead flag"


def _files(root, skip):
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            if p != skip:
                st = os.stat(p)
                out[p] = (st.st_size, st.st_mtime_ns)
    return out


def _frame(app, pb, path):
    app.screen.fill(COL_BG)
    app._draw_map()
    app._draw_agents()
    app._draw_floating_texts()
    app._draw_npc_announcement()
    pb.draw_map_layer()
    pb.draw_panel()
    pygame.image.save(app.screen, path)
    return path


def test_playback_of_a_recorded_fight():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "sim_trace.jsonl")
    saved, App.SIM_TRACE_FILE = App.SIM_TRACE_FILE, path
    try:
        app = _fight(tmp, hard=True)
        gnasher = _idx(app, "Gnasher")
        app._drive_npc_turn_if_pending()
        played = [_fields(e) for e in app._npc_anim["events"]]
        app._npc_anim_finish()

        # Refused mid-combat, and the scene is untouched.
        bm0 = app.bm
        assert playback.enter(app, path) is None and app.playback is None and app.bm is bm0

        app._end_combat()
        tr = sim_trace.load_trace(path)
        turns = playback.playable_turns(tr)

        dm_bm, dm_combat, dm_board = app.bm, app.combat, _board(app)
        dm_size = app.screen.get_size()
        app._sync_roster_tokens()        # _fight places its agents without syncing the roster
        dm_owned = app.roster.controlled_by("dm")
        assert dm_owned
        before = _files(tmp, path)

        pb = playback.enter(app, path)
        assert pb is not None and app.playback is pb
        assert app.bm is not dm_bm and app.combat is not dm_combat
        assert len(app.bm.placed_agents) == len(playback.roster(tr))
        assert app.roster.controlled_by("dm") == dm_owned, "seats followed the trace's board"
        _expect(app, turns[0].snapshot)
        # A GUI trace has no `party` field: the HUD's party box derives it from the agents.
        names = [txt.split(" — ")[0] for txt, st in pb.party_lines() if st != "title"]
        assert {"Aria", "Brannor"} <= set(names), names
        assert not {"Gnasher", "Skarn"} & set(names), names
        imp = _idx(app, "Imp")
        assert app.bm.placed_agents[imp].removed_from_play, "a tombstone in the trace shows"

        # Gnasher's turn replays exactly the events the live board played.
        k = max(i for i, t in enumerate(turns) if t.actor == gnasher)
        pb.goto(k)
        _expect(app, turns[k].snapshot)
        pb.step()
        assert app._npc_anim is not None
        assert [_fields(e) for e in app._npc_anim["events"]] == played
        _frame(app, pb, os.path.join(tmp, "mid_turn.png"))
        pb.step()                                    # finishes it: the board moves on
        assert app._npc_anim is None and pb.ti == k + 1
        _expect(app, turns[k + 1].snapshot if k + 1 < len(turns)
                else playback.fold_events(turns[k].snapshot, turns[k].events))

        # Step back: to the start of the turn just played; mid-turn, to its own start.
        pb.step_back()
        assert pb.ti == k
        _expect(app, turns[k].snapshot)
        pb.step()
        pb.step_back()
        assert pb.ti == k and app._npc_anim is None
        _expect(app, turns[k].snapshot)

        # Speed scales the animation clock; the scrubber jumps; the end folds the last turn.
        pb.set_speed(playback.SPEEDS.index(4.0))
        assert app._npc_anim_speed == 4.0
        pb.goto(len(turns))
        _expect(app, playback.fold_events(turns[-1].snapshot, turns[-1].events))
        out = _frame(app, pb, os.path.join(tmp, "playback.png"))
        assert os.path.getsize(out) > 0
        pb._scrub(pb._scrub_rect.x)                  # the scrubber's left end: turn 1
        assert pb.ti == 0
        _expect(app, turns[0].snapshot)

        # Playing runs turn after turn on its own.
        pb.toggle_play()
        pb.tick()
        assert app._npc_anim is not None and pb.playing
        app._npc_anim_fast_forward()
        assert pb.ti == 1

        # Every event is Playback's: a map click selects nothing, a key steps.
        sel = app.selected_idx
        gui_driver.post_click(app, gui_driver.cell_center(app, 2, 3))
        assert app.selected_idx == sel and not app.context_menu.visible
        pb.goto(0)
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0,
                                             unicode=""))
        app._handle_events()
        assert app._npc_anim is not None and pb.ti == 0

        # Exit Playback: the DM's own objects, unchanged, and no file written.
        gui_driver.post_click(app, pb._buttons["exit"].rect.center)
        assert app.playback is None and app._npc_anim is None
        assert app.bm is dm_bm and app.combat is dm_combat
        assert _board(app) == dm_board
        assert app.screen.get_size() == dm_size
        assert app._npc_anim_speed == 1.0
        assert app.roster.controlled_by("dm") == dm_owned
        after = {p: v for p, v in _files(tmp, path).items() if not p.endswith(".png")}
        assert after == before, "Playback wrote or changed a file"

        # A missing or broken trace is refused, and the scene stays.
        assert playback.enter(app, os.path.join(tmp, "nope.jsonl")) is None
        assert app.playback is None and app.bm is dm_bm
    finally:
        App.SIM_TRACE_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_playback_of_a_recorded_fight passed")


if __name__ == "__main__":
    test_fold_events()
    test_roster_and_playable_turns()
    test_playback_of_a_recorded_fight()
    print("\nAll playback tests passed! 🎉")
