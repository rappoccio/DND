#!/usr/bin/env python3
"""Movement from the browser (MULTIPLAYER_PLAN.md D-M5-4, slice M5c).

The offer's Move row opens a `kind:"cell"` prompt carrying the reachable set; a cell answer
runs `App.commit_move`, the function the DM's drag release runs. These checks pin:

  · commit_move refuses a creature whose Speed is 0          (test_commit_move_refuses_at_speed_zero)
  · the DM's drag runs commit_move and takes a turn over     (test_a_dm_drag_takes_the_turn_over)
  · Move is first, not an ActionMenu id, disabled with reasons (test_the_move_row)
  · the budget is the App's, so Steady Aim stops a remote move (test_steady_aim_stops_a_remote_move)
  · a cell outside the set is refused and the prompt stays live (test_a_cell_outside_reachable_is_refused)
  · a mode option re-posts, and App.move_type is untouched  (test_a_mode_option_reposts_and_leaves_move_type)
  · cancelling Move re-offers and spends nothing             (test_cancelling_move_reoffers_and_spends_nothing)
  · a pause or a turn change withdraws the Move prompt       (test_the_gate_withdraws_the_move_prompt)
  · with fog up, the set is cut to the explored mask         (test_reachable_is_cut_to_the_explored_mask)
  · you.reachable rides only with its prompt id              (test_reachable_rides_only_with_the_prompt)
  · a provoking move parks the OA and resumes                (test_a_provoking_move_parks_and_resumes)
  · a player's OA left to expire lets the move finish        (test_an_expired_oa_lets_the_move_finish)
  · end to end: move, Dodge, move again, over the socket     (test_move_dodge_move_over_the_wire)

The scene is `test_offer.py`'s: Aria (Fighter 5) at (3,3) with Skarn, a foe, at (4,3);
Kira controls Aria, Wen controls Cyra.
"""

import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from net import move as net_move, offer as net_offer, view as net_view
from net.roster import DM_PRINCIPAL_ID
from prompts import PromptState, Response

from gui_driver import cell_center
from test_action_menu import _app
from test_combat_panel import _goto, _idx, _preserve_cwd_logs, _restore_cwd_logs
from test_live import _auth_frame, _ws
from test_offer import _aria_turn, _frame, _log, _offer, _table, _action_prompt
from test_submit import _drain, _next, _submit


# ─────────────────────────────────────────────────────────────────────────────
#  Rig
# ─────────────────────────────────────────────────────────────────────────────

def _pos(app, idx):
    o = app.bm.placed_agents[idx].origin
    return (o.col, o.row)


def _open_move(app, kira):
    """Kira answers the offer with Move. Returns (offer, Move prompt)."""
    offer = _offer(app)
    assert offer is not None, "no offer is up"
    res = app.prompts.submit(offer.id, Response(option=net_move.MOVE_ID), kira.id)
    assert res.ok, res
    move = app.prompts.live
    assert move is not None and move.kind == "cell" and move.expects == "cell", move
    return offer, move


def _budgets(app):
    return (app.move_remaining_walk, app.move_remaining_fly,
            app.move_remaining_swim, app.move_remaining_burrow)


def _set_cond(app, idx, **flags):
    cond = app.combat.get_agent_conditions(app.bm, idx)
    for k, v in flags.items():
        setattr(cond, k, v)
    app.combat.set_agent_conditions(app.bm, idx, cond)


def _drag(app, frm, to):
    """The DM drags a token from cell `frm` to cell `to`: down, motion, up."""
    a, b = cell_center(app, *frm), cell_center(app, *to)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=a, button=1))
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=b, rel=(b[0] - a[0], b[1] - a[1]),
                                         buttons=(1, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=b, button=1))
    assert app._handle_events() is not False


# ─────────────────────────────────────────────────────────────────────────────
#  commit_move and the DM's drag
# ─────────────────────────────────────────────────────────────────────────────

def test_commit_move_refuses_at_speed_zero():
    """Restrained after her budget was set, Aria still has feet left on paper, but Speed 0
    is Speed 0: commit_move refuses, logs why, and nothing moves."""
    app = _app()
    aria = _goto(app, "Aria")
    _set_cond(app, aria, restrained=True)
    assert app.move_remaining_walk > 0
    ok = app.commit_move(aria, rpg.Cell(3, 4), rpg.MovementType.Walk, DM_PRINCIPAL_ID)
    assert ok is False, "a restrained creature's move was started"
    assert _pos(app, aria) == (3, 3), f"Aria moved to {_pos(app, aria)}"
    assert any("movement blocked" in line for line in app.combat_log), "no log line says why"
    print("✅ test_commit_move_refuses_at_speed_zero")


def test_a_dm_drag_takes_the_turn_over():
    """With nobody seated, the DM's drag moves Aria through commit_move. With Kira's Move
    prompt live, the same drag cancels it as the DM first: one `takeover` line, and Kira's
    late cell is `not_live`."""
    app = _app()
    aria = _goto(app, "Aria")
    app.selected_idx = aria
    app._update_reach()
    _drag(app, (3, 3), (3, 4))
    assert _pos(app, aria) == (3, 4), f"the drag left Aria at {_pos(app, aria)}"
    assert app.move_remaining_walk == 25, app.move_remaining_walk

    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        aria = _idx(app, "Aria")
        _, move = _open_move(app, kira)
        app.selected_idx = aria
        _drag(app, (3, 3), (3, 4))
        late = app.prompts.submit(move.id, Response(cell=(3, 4)), kira.id)
        lines = _log(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert _pos(app, aria) == (3, 4), "the DM's drag did not move Aria"
    assert not late.ok and late.error == "not_live", late
    assert [(l["event"], l["prompt"]) for l in lines] == [("takeover", move.id)], lines
    print("✅ test_a_dm_drag_takes_the_turn_over")


# ─────────────────────────────────────────────────────────────────────────────
#  The Move row
# ─────────────────────────────────────────────────────────────────────────────

def test_the_move_row():
    """Move is the offer's first row, enabled on a fresh turn. It is no ActionMenu id, so
    nothing in `perform` can reach it. At Speed 0, and with no budget left, it is offered
    disabled, with the reason."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    first = _offer(app).options[0]
    assert first.id == net_move.MOVE_ID and first.enabled, first
    assert net_move.MOVE_ID not in net_offer.CLASS
    assert net_move.MOVE_ID not in app._action_menu

    _set_cond(app, aria, restrained=True)
    _frame(app)
    row = _offer(app).options[0]
    assert not row.enabled and row.disabled_reason == net_move.REASON_SPEED_ZERO, row
    refused = app.prompts.submit(_offer(app).id, Response(option="move"), kira.id)
    assert not refused.ok and refused.error == "bad_option", refused

    _set_cond(app, aria, restrained=False)
    app.move_remaining_walk = 0
    _frame(app)
    row = _offer(app).options[0]
    assert not row.enabled and row.disabled_reason == net_move.REASON_NO_BUDGET, row
    print("✅ test_the_move_row")


def test_steady_aim_stops_a_remote_move():
    """Steady Aim zeroes the App's budgets and leaves the agent's own (`main.py`, the
    steady_aim handler). The Move row and the reachable set follow the App's."""
    app, _, _ = _aria_turn()
    aria = _idx(app, "Aria")
    for f in ("walk", "fly", "swim", "burrow"):
        setattr(app, f"move_remaining_{f}", 0)
    assert app.bm.placed_agents[aria].walk_remaining > 0, "the scene no longer shows the gap"
    _frame(app)
    row = _offer(app).options[0]
    assert not row.enabled, "Move was offered after Steady Aim"
    assert app.reachable_for(aria, rpg.MovementType.Walk) == []
    print("✅ test_steady_aim_stops_a_remote_move")


# ─────────────────────────────────────────────────────────────────────────────
#  The Move prompt
# ─────────────────────────────────────────────────────────────────────────────

def test_a_cell_outside_reachable_is_refused():
    """A cell the prompt did not list is `bad_option`, BEFORE the commit: the prompt stays
    live, Aria stays put, and a listed cell then works."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _, move = _open_move(app, kira)
    assert move.cells == frozenset(
        (c.col, c.row) for c in app.reachable_for(aria, rpg.MovementType.Walk))
    far = (3, 3 + 20)
    assert far not in move.cells
    res = app.prompts.submit(move.id, Response(cell=far), kira.id)
    assert not res.ok and res.error == "bad_option", res
    assert move.is_live, "a mis-tap resolved the Move prompt"
    assert _pos(app, aria) == (3, 3)
    assert (3, 4) in move.cells
    assert app.prompts.submit(move.id, Response(cell=(3, 4)), kira.id).ok
    assert _pos(app, aria) == (3, 4), f"Aria is at {_pos(app, aria)}"
    print("✅ test_a_cell_outside_reachable_is_refused")


def test_a_mode_option_reposts_and_leaves_move_type():
    """With fly budget, the walking prompt offers Fly. Choosing it posts a new prompt under
    the same offer with the fly set, and the DM's `move_type` is not touched (D-M5-4.4)."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    app.move_remaining_fly = 30
    offer, walking = _open_move(app, kira)
    assert app.move_type == rpg.MovementType.Walk
    assert [o.id for o in walking.options] == ["fly"], walking.options
    assert app.prompts.submit(walking.id, Response(option="fly"), kira.id).ok
    flying = app.prompts.live
    assert flying is not walking and flying.kind == "cell", flying
    assert flying.parent_id == offer.id, flying.parent_id
    assert app.move_type == rpg.MovementType.Walk, "the player's mode flipped the DM's move_type"
    assert flying.cells == frozenset(
        (c.col, c.row) for c in app.reachable_for(aria, rpg.MovementType.Fly))
    assert [o.id for o in flying.options] == ["walk"], flying.options
    assert flying.title.startswith("Move: flying"), flying.title
    print("✅ test_a_mode_option_reposts_and_leaves_move_type")


def test_cancelling_move_reoffers_and_spends_nothing():
    """Arming Move spends nothing, and a cancel brings the offer back on the next frame
    with Move still enabled."""
    app, kira, _ = _aria_turn()
    before = (_budgets(app), app.action_used, app.bonus_used)
    offer, move = _open_move(app, kira)
    assert app.prompts.cancel_as(move.id, kira.id).ok
    assert move.state is PromptState.CANCELLED
    _frame(app)
    again = _offer(app)
    assert again is not None and again is not offer, "the offer did not come back"
    assert again.options[0].id == "move" and again.options[0].enabled
    assert (_budgets(app), app.action_used, app.bonus_used) == before, "arming Move spent something"
    print("✅ test_cancelling_move_reoffers_and_spends_nothing")


def test_the_gate_withdraws_the_move_prompt():
    """The Move prompt is the offer's child: a pause takes it down with no log line, and
    so does the DM advancing the turn under it. A late cell is then `not_live`."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        _, move = _open_move(app, kira)
        app.combat_paused = True
        _frame(app)
        assert move.state is PromptState.SUPERSEDED, move.state
        assert _log(app) == [], _log(app)
        app.combat_paused = False
        _frame(app)
        _, move = _open_move(app, kira)
        app._advance_turn()
        _frame(app)
        assert move.state is PromptState.SUPERSEDED, move.state
        late = app.prompts.submit(move.id, Response(cell=(3, 4)), kira.id)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not late.ok and late.error == "not_live", late
    print("✅ test_the_gate_withdraws_the_move_prompt")


def test_reachable_is_cut_to_the_explored_mask():
    """D-M5-4.2, fix A. With fog up and only rows 0-4 explored, the Move prompt and the
    view hold just the explored part of Aria's reach, so no hidden wall is outlined; a
    truly reachable cell in the fog is refused. With fog down, the whole set is back."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    full = {(c.col, c.row) for c in app.reachable_for(aria, rpg.MovementType.Walk)}
    cols, rows = int(app.bm.grid_cols), int(app.bm.grid_rows)
    explored = {(c, r) for c in range(cols) for r in range(rows) if r <= 4}
    app.bm.set_explored_cells([rpg.Cell(c, r) for c, r in explored])
    app.show_fog = True
    assert app._fog_active()

    _, move = _open_move(app, kira)
    assert move.cells == frozenset(full & explored), "the set was not cut to the mask"
    fogged = sorted(full - explored)
    assert fogged and move.cells, "the scene no longer straddles the mask"
    assert all(r <= 4 for _, r in net_view.build_view(app, kira)["you"]["reachable"])
    res = app.prompts.submit(move.id, Response(cell=fogged[0]), kira.id)
    assert not res.ok and res.error == "bad_option", res
    assert move.is_live

    app.prompts.cancel_as(move.id, kira.id)
    app.show_fog = False
    _frame(app)
    _, move = _open_move(app, kira)
    assert move.cells == frozenset(full), "fog down still cut the set"

    # A Large token: a cell is kept only when its whole 2x2 footprint is explored. The
    # scene has no Large creature, so this half drives the filter with a stand-in App.
    from types import SimpleNamespace as NS
    cell = lambda c, r: NS(col=c, row=r)
    big = NS(_fog_active=lambda: True,
             reachable_for=lambda idx, mt: [cell(0, 0), cell(0, 3), cell(2, 2)],
             bm=NS(placed_agents=[NS(size=2)],
                   explored_cells=lambda: [cell(c, r) for c in range(4) for r in range(4)]))
    assert net_move.reachable_cells(big, 0, rpg.MovementType.Walk) == [(0, 0), (2, 2)], \
        "a Large footprint reaching into the fog was kept"
    print("✅ test_reachable_is_cut_to_the_explored_mask")


def test_reachable_rides_only_with_the_prompt():
    """`you.reachable` is the live prompt's own `cells`, for the viewers who get its id:
    Kira and the DM. Wen never sees it, and nobody does once the prompt is gone."""
    app, kira, wen = _aria_turn()
    roster = app.roster
    dm = roster.get(DM_PRINCIPAL_ID)
    assert "reachable" not in net_view.build_view(app, kira)["you"], "reachable without a Move"
    _, move = _open_move(app, kira)
    want = sorted([c, r] for c, r in move.cells)
    assert net_view.build_view(app, kira)["you"]["reachable"] == want
    assert net_view.build_view(app, dm)["you"]["reachable"] == want
    assert "reachable" not in net_view.build_view(app, wen)["you"], "Wen saw Kira's reach"
    app.prompts.cancel_as(move.id, kira.id)
    assert "reachable" not in net_view.build_view(app, kira)["you"]
    print("✅ test_reachable_rides_only_with_the_prompt")


def test_a_provoking_move_parks_and_resumes():
    """Aria walks away from Skarn. The engine parks on Skarn's opportunity attack, the DM
    answers it, and the move completes; the offer then comes back to Kira."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _, move = _open_move(app, kira)
    dest = (1, 3)
    assert dest in move.cells
    assert app.prompts.submit(move.id, Response(cell=dest), kira.id).ok
    assert app.combat.pending_decision().active, "walking out of Skarn's reach did not provoke"
    oa = app.prompts.live
    assert oa is not None and oa.kind == "reaction" and oa.owner == DM_PRINCIPAL_ID, oa
    _frame(app)
    assert app.prompts.live is oa, "the offer went up over a parked OA"
    skip = next(o for o in oa.options if "Skip" in o.label or "skip" in o.label.lower())
    assert app.prompts.submit(oa.id, Response(option=skip.id)).ok
    assert not app.combat.pending_decision().active
    assert _pos(app, aria) == dest, f"the move did not finish: Aria at {_pos(app, aria)}"
    _frame(app)
    assert _offer(app) is not None and _offer(app).owner == kira.id
    print("✅ test_a_provoking_move_parks_and_resumes")


def test_an_expired_oa_lets_the_move_finish():
    """The same move with Skarn seated to Wen: Wen's OA has a deadline, and when it passes
    the engine resumes as Skip and Aria arrives."""
    app, kira, wen = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    app.bm.set_agent_controller(skarn, wen.id)
    app._sync_roster_tokens()
    _, move = _open_move(app, kira)
    assert app.prompts.submit(move.id, Response(cell=(1, 3)), kira.id).ok
    oa = app.prompts.live
    assert oa is not None and oa.owner == wen.id and oa.deadline is not None, oa
    assert app.prompts.expire(now=oa.deadline + 1.0) is oa
    assert not app.combat.pending_decision().active
    assert _pos(app, aria) == (1, 3), f"Aria at {_pos(app, aria)}"
    print("✅ test_an_expired_oa_lets_the_move_finish")


# ─────────────────────────────────────────────────────────────────────────────
#  Over the wire
# ─────────────────────────────────────────────────────────────────────────────

def test_move_dodge_move_over_the_wire():
    """End to end from Kira's socket: Move to (3,4), Dodge, Move to (4,4). Each leg is
    one prompt, the view carries its reachable set, and the offer comes back between."""
    with _table() as t:
        app = t.app
        aria = _idx(app, "Aria")
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            seen = set()

            def leg(cell):
                offer = _action_prompt(kira, exclude=tuple(seen))
                seen.add(offer["id"])
                assert offer["options"][0]["id"] == "move" and offer["options"][0]["enabled"]
                kira.send_text(_submit(offer["id"], option="move"))
                assert _next(kira, "submit_ack")["ok"]
                mv = _next(kira, "prompt", match=lambda f: f["kind"] == "cell")
                assert mv["expects"] == "cell" and mv["parent_id"] == offer["id"], mv
                view = _next(kira, "view", match=lambda f: f["you"].get("prompt_id") == mv["id"])
                assert list(cell) in view["you"]["reachable"], "the target is not in the overlay"
                kira.send_text(_submit(mv["id"], cell=list(cell)))
                ack = _next(kira, "submit_ack")
                assert ack["ok"], ack

            leg((3, 4))
            offer = _action_prompt(kira, exclude=tuple(seen))
            seen.add(offer["id"])
            kira.send_text(_submit(offer["id"], option="dodge"))
            assert _next(kira, "submit_ack")["ok"]
            leg((4, 4))
            _drain(kira, 0.2)
        t.stop()
        assert _pos(app, aria) == (4, 4), f"Aria is at {_pos(app, aria)}"
        assert app.bm.placed_agents[aria].conditions.dodging, "the Dodge did not land"
        assert app.move_remaining_walk == 20, app.move_remaining_walk
    print("✅ test_move_dodge_move_over_the_wire")


if __name__ == "__main__":
    _saved = _preserve_cwd_logs()
    try:
        test_commit_move_refuses_at_speed_zero()
        test_a_dm_drag_takes_the_turn_over()
        test_the_move_row()
        test_steady_aim_stops_a_remote_move()
        test_a_cell_outside_reachable_is_refused()
        test_a_mode_option_reposts_and_leaves_move_type()
        test_cancelling_move_reoffers_and_spends_nothing()
        test_the_gate_withdraws_the_move_prompt()
        test_reachable_is_cut_to_the_explored_mask()
        test_reachable_rides_only_with_the_prompt()
        test_a_provoking_move_parks_and_resumes()
        test_an_expired_oa_lets_the_move_finish()
        test_move_dodge_move_over_the_wire()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All move tests passed!")
