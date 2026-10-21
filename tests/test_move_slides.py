#!/usr/bin/env python3
"""Human-move slides on the DM screen (MULTIPLAYER_PLAN.md M4b.4, B-2 / B-6 / B-7).

The GUI turns the engine's `record_moves` on, so a committed human move leaves its route in
the visual-event buffer. `_after_move_committed` drains it into the players' stream and
plays it as an `_npc_anim` with no continuation. These checks pin:

  · the GUI switches record_moves on, and back on after a resume (test_record_moves_is_on)
  · a DM move slides, holds only the mover, and streams       (test_a_dm_move_slides_and_streams)
  · a slide defers nothing: the player's offer stays up       (test_the_offer_stays_up_through_a_slide)
  · ...and so does a target pick                              (test_a_pick_stays_up_through_a_slide)
  · a move parked at an OA slides once the OA resolves        (test_a_parked_move_slides_after_the_oa)
  · a move joins a running playback, keeping its continuation (test_a_move_joins_a_running_playback)
  · Animate: OFF lands the move in one frame                  (test_animate_off_lands_the_move)
  · a parked NPC turn's move stays with the NPC playback (B-2) (test_a_parked_npc_turn_keeps_its_move)

The scene is `test_offer.py`'s: Aria (Fighter 5) at (3,3) with Skarn, a foe, at (4,3);
Kira controls Aria.
"""

import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from net import picks as net_picks
from net.roster import DM_PRINCIPAL_ID
from net.view import sight
from prompts import Response

from test_action_menu import _app
from test_combat_panel import _goto, _idx, _preserve_cwd_logs, _restore_cwd_logs
from test_move import _open_move, _pos
from test_offer import _aria_turn, _frame, _offer
from test_picks import _choose, _until_pick


WALK = rpg.MovementType.Walk


def _streamed(app):
    """Every event the DM's projection has numbered so far."""
    dm = app.roster.get(DM_PRINCIPAL_ID)
    return app.events.project(DM_PRINCIPAL_ID, lambda: sight(app, dm)).since(0)


def test_record_moves_is_on():
    """The engine's switch is off by default (RL, headless); the GUI turns it on at
    start-up, on the engine itself rather than on the replay wrapper, and again after a
    resume, whose restore rebuilds the engine's context."""
    assert not rpg.CombatEngine(1).record_moves, "record_moves is on by default"
    app = _app()
    assert app.combat._engine.record_moves, "the GUI did not switch record_moves on"

    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "slides_combat.json")
        app._save_combat_state(path)
        assert app._load_combat_state(path), "the resume did not happen"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert app.combat._engine.record_moves, "a resume left record_moves off"
    print("✅ test_record_moves_is_on")


def test_a_dm_move_slides_and_streams():
    """The DM walks Aria (3,3) → (3,4). The move is committed at once; the board holds only
    Aria, at her route's start, with no continuation and no HP held. The players' stream
    gets one `move`. A fast-forward lands her, and the turn does not change."""
    app = _app()
    aria = _goto(app, "Aria")
    app.events.projection(DM_PRINCIPAL_ID)
    turn = app.turn_idx

    assert app.commit_move(aria, rpg.Cell(3, 4), WALK, DM_PRINCIPAL_ID)
    assert _pos(app, aria) == (3, 4), "the move is not committed before the slide"
    a = app._npc_anim
    assert a is not None, "the move did not slide"
    assert a["on_done"] is None, a["on_done"]
    assert a["pos"] == {aria: (3.0, 3.0)}, a["pos"]
    assert a["hp"] == {} and a["draw_dead"] == set(), (a["hp"], a["draw_dead"])
    assert app._npc_anim_display_pos(aria) == (3.0, 3.0)

    got = _streamed(app)
    assert [(e["kind"], e["agent"]) for e in got] == [("move", aria)], got
    assert got[0]["path"] == [[3, 3], [3, 4]], got[0]["path"]
    assert app.combat.take_npc_visual_events() == [], "the move was left in the buffer"

    app._npc_anim_fast_forward()
    assert app._npc_anim is None and app._npc_anim_display_pos(aria) is None
    assert app.turn_idx == turn, "the slide advanced the turn"
    print("✅ test_a_dm_move_slides_and_streams")


def test_the_offer_stays_up_through_a_slide():
    """An NPC playback holds a continuation, so the offer waits for it. A human slide holds
    none, so Kira's offer comes back while her own move is still sliding."""
    app, kira, _ = _aria_turn()
    _, move = _open_move(app, kira)
    assert app.prompts.submit(move.id, Response(cell=(3, 4)), kira.id).ok
    assert app._npc_anim is not None, "the move did not slide"
    assert not app._npc_anim_defers()
    _frame(app)
    assert _offer(app) is not None and _offer(app).owner == kira.id, \
        "the offer did not come back during the slide"

    app._npc_anim = {"on_done": lambda: None}       # an NPC playback still defers
    assert app._npc_anim_defers()
    app._npc_anim = None
    print("✅ test_the_offer_stays_up_through_a_slide")


def test_a_pick_stays_up_through_a_slide():
    """Kira's attack is waiting on a target. A slide on the board (here, a DM move being
    played) does not take the pick down; an NPC playback, which defers, does."""
    app, kira, _ = _aria_turn()
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    app._npc_anim_start([], {}, on_done=None)
    assert net_picks.wanted(app) is not None, "a slide took the target pick down"
    app._npc_anim["on_done"] = lambda: None
    assert net_picks.wanted(app) is None, "an NPC playback left the pick up"
    app._npc_anim = None
    assert pick.is_live
    print("✅ test_a_pick_stays_up_through_a_slide")


def test_a_parked_move_slides_after_the_oa():
    """Aria walks away from Skarn and parks on his opportunity attack. The park moves
    nothing, so nothing slides or streams; once the DM skips the OA the move commits, and
    it slides from (3,3) and reaches the stream once."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    app.events.projection(DM_PRINCIPAL_ID)
    _, move = _open_move(app, kira)
    assert app.prompts.submit(move.id, Response(cell=(1, 3)), kira.id).ok
    assert app.combat.pending_decision().active, "walking out of Skarn's reach did not provoke"
    assert app._npc_anim is None, "the park slid a move that has not happened"
    assert not any(e["kind"] == "move" for e in _streamed(app))

    oa = app.prompts.live
    skip = next(o for o in oa.options if "skip" in o.label.lower())
    assert app.prompts.submit(oa.id, Response(option=skip.id)).ok
    assert _pos(app, aria) == (1, 3), f"the move did not finish: Aria at {_pos(app, aria)}"
    a = app._npc_anim
    assert a is not None and a["on_done"] is None, "the resumed move did not slide"
    assert a["pos"] == {aria: (3.0, 3.0)}, a["pos"]
    moves = [e for e in _streamed(app) if e["kind"] == "move"]
    assert [(e["agent"], e["path"][-1]) for e in moves] == [(aria, [1, 3])], moves
    print("✅ test_a_parked_move_slides_after_the_oa")


def test_a_move_joins_a_running_playback():
    """A move committed while another playback runs joins its queue: that playback's
    continuation stays, and runs once, when the whole queue has drained."""
    app = _app()
    aria = _goto(app, "Aria")
    done = []
    app._npc_anim_start([], {}, on_done=lambda: done.append(1))
    assert app.commit_move(aria, rpg.Cell(3, 4), WALK, DM_PRINCIPAL_ID)
    a = app._npc_anim
    assert a["on_done"] is not None, "the move replaced the running playback's continuation"
    assert len(a["events"]) == 1 and a["pos"] == {aria: (3.0, 3.0)}, (a["events"], a["pos"])
    app._npc_anim_fast_forward()
    assert done == [1], done
    print("✅ test_a_move_joins_a_running_playback")


def test_animate_off_lands_the_move():
    """Animate: OFF (B-7) skips only the slide: the move lands on the first frame."""
    app = _app()
    aria = _goto(app, "Aria")
    assert app.animate_moves and app.btn_toggle_animate.text == "Animate: ON"
    app._set_animate_moves(False)
    assert app.btn_toggle_animate.text == "Animate: OFF"
    assert app.commit_move(aria, rpg.Cell(3, 4), WALK, DM_PRINCIPAL_ID)
    assert app._npc_anim is not None
    app._advance_npc_playback()
    assert app._npc_anim is None, "the move still slides with Animate: OFF"

    app._set_animate_moves(True)
    assert app.commit_move(aria, rpg.Cell(3, 3), WALK, DM_PRINCIPAL_ID)
    assert _pos(app, aria) == (3, 3), f"the move back did not commit: Aria at {_pos(app, aria)}"
    app._advance_npc_playback()
    assert app._npc_anim is not None, "Animate: ON did not slide"
    print("✅ test_animate_off_lands_the_move")


def test_a_parked_npc_turn_keeps_its_move():
    """The B-2 trap. Skarn, automated and commanded to flee Aria, walks out of her reach and
    the turn parks on her opportunity attack. Skipping it resumes the move inside
    submit_decision, which records Skarn's Move into the buffer. That Move belongs to the
    NPC turn's own drain, after _resume_npc_turn, so it plays inside the NPC playback that
    advances the turn, and reaches the stream once. A human-move drain straight after
    submit_decision would take it."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    app.events.projection(DM_PRINCIPAL_ID)
    c = rpg.ActiveAgentCondition()
    c.agent_idx, c.caster_idx, c.condition_name = skarn, aria, "CommandFlee"
    c.turns_remaining, c.save_repeat_turns = 1, -1
    app.combat.add_agent_condition(app.bm, c)
    app.bm.set_agent_npc_automated(skarn, True)
    _goto(app, "Skarn")
    app.combat.begin_turn(app.bm, skarn)

    app._npc_drive_idx = skarn
    app._drive_npc_turn_if_pending()
    assert app.combat.pending_decision().active, "Skarn's flee did not provoke Aria"
    app._npc_anim_fast_forward()                  # what played before the park; opens the OA
    oa = app.prompts.live
    assert oa is not None and oa.kind == "reaction", oa
    skip = next(o for o in oa.options if "skip" in o.label.lower())
    assert app.prompts.submit(oa.id, Response(option=skip.id), kira.id).ok
    assert not app.combat.pending_decision().active
    assert _pos(app, skarn) != (4, 3), "the resumed flee did not move Skarn"
    assert app._npc_anim is None, "a human-move drain took the NPC turn's Move"

    app._drive_npc_turn_if_pending()              # the resumed turn's own drain
    a = app._npc_anim
    assert a is not None and a["on_done"] == app._advance_turn, a and a["on_done"]
    moves = [e for e in a["events"] if e.kind == app._NPC_EV_MOVE]
    assert [e.agent_idx for e in moves] == [skarn], moves
    streamed = [e for e in _streamed(app) if e["kind"] == "move"]
    assert [e["agent"] for e in streamed] == [skarn], streamed
    print("✅ test_a_parked_npc_turn_keeps_its_move")


if __name__ == "__main__":
    _saved = _preserve_cwd_logs()
    try:
        test_record_moves_is_on()
        test_a_dm_move_slides_and_streams()
        test_the_offer_stays_up_through_a_slide()
        test_a_pick_stays_up_through_a_slide()
        test_a_parked_move_slides_after_the_oa()
        test_a_move_joins_a_running_playback()
        test_animate_off_lands_the_move()
        test_a_parked_npc_turn_keeps_its_move()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All move-slide tests passed!")
