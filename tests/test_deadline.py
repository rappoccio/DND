#!/usr/bin/env python3
"""The reaction deadline (MULTIPLAYER_PLAN.md D-M5-7, slice M5b).

A player who does not answer a reaction must not hold the table. A reaction prompt a player
owns carries a deadline, the DM's session setting (default 60 s). When it passes, the frame
tick skips it, through the prompt's own `on_cancel`, exactly as the DM's click-away does.
Action and target prompts never carry one: expiry must never end a player's turn.

  · `deadline_ms` is the time left, not a clock reading        (test_deadline_ms_is_the_time_left)
  · a player's opportunity attack expires on the tick          (test_a_players_oa_expires_on_the_tick)
  · an expiry is one `expired` line, never a takeover          (test_an_expiry_is_logged_as_an_expiry)
  · a late submit after expiry is `not_live`                   (test_a_late_submit_after_expiry_is_not_live)
  · only a player's reaction gets a deadline                   (test_only_a_players_reaction_gets_a_deadline)
  · a menus/reactions.py prompt expires to its Skip            (test_riposte_expires_to_its_skip)
  · every reaction in menus/reactions.py has a Skip to run     (test_every_gui_reaction_carries_its_skip)
  · the DM's timer: cycles, only the DM sets it, survives a resume
                                                               (test_the_dm_sets_the_timer)
  · end to end: the phone sees the countdown, then the skip    (test_an_unanswered_oa_in_the_browser)

Expiry is driven by moving a prompt's deadline into the past and running one tick, never by
sleeping.
"""

import ast
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from gui_driver import post_click
from menus import panel, reactions
from net import link as net_link, offer as net_offer
from net.roster import DM_PRINCIPAL_ID
from prompts import CLOCK_PRINCIPAL_ID, Option, PromptBus, PromptState, Response

from test_gameview import _idx
from test_live import _auth_frame, _ws
from test_offer import _aria_turn, _offer
from test_prompts import _parked_app
from test_submit import _next, _oa_scene, _table

_REACTIONS = os.path.join(_ROOT, "gui", "menus", "reactions.py")


def _oa(tmp):
    """`test_submit._oa_scene`, logging to `tmp`: Kira's Threat is parked on an OA."""
    app, kira, _ = _oa_scene(tmp)
    app.submit_log.path = os.path.join(tmp, "submit_log.jsonl")
    return app, kira, app.prompts.live


def _lines(app):
    path = app.submit_log.path
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _lapse(prompt):
    """Move the deadline into the past, so the next tick expires it."""
    assert prompt.deadline is not None, "the prompt has no deadline to lapse"
    prompt.deadline = time.monotonic() - 1.0


def _pos(app, name):
    o = app.bm.placed_agents[_idx(app, name)].origin
    return (o.col, o.row)


# ─────────────────────────────────────────────────────────────────────────────
#  The wire
# ─────────────────────────────────────────────────────────────────────────────

def test_deadline_ms_is_the_time_left():
    """Envelope 4: `deadline_ms` is what is left, in ms, or null. `deadline` itself is a
    `time.monotonic()` reading, which means nothing on a phone."""
    bus = PromptBus()
    p = bus.ask(0, "p_kira", "reaction", "OA", [Option("opt_0", "Skip")],
                deadline=time.monotonic() + 5.0, on_cancel=lambda: None)
    ms = p.to_wire()["deadline_ms"]
    assert isinstance(ms, int) and 0 < ms <= 5000, ms
    assert p.deadline_ms(now=p.deadline + 3.0) == 0, "an overdue prompt has 0 left, not less"
    q = bus.ask(0, "p_kira", "action", "Turn", [Option("opt_0", "Dodge")])
    assert q.to_wire()["deadline_ms"] is None
    print("✅ test_deadline_ms_is_the_time_left")


# ─────────────────────────────────────────────────────────────────────────────
#  Expiry, on the frame tick
# ─────────────────────────────────────────────────────────────────────────────

def test_a_players_oa_expires_on_the_tick():
    """Kira does not answer her opportunity attack. One tick past the deadline, the engine
    resumes as Skip: the reaction is not spent and the move completes."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, p = _oa(tmp)
        threat = _idx(app, "Threat")
        assert p.kind == "reaction" and p.owner == kira.id
        net_link.pump_submits(app)
        assert p.is_live, "the prompt expired before its deadline"
        _lapse(p)
        net_link.pump_submits(app)                     # what run() calls once per frame
        assert p.state is PromptState.CANCELLED and p.resolved_by == CLOCK_PRINCIPAL_ID
        assert not app.combat.pending_decision().active, "the parked window did not resolve"
        assert not app.combat.get_agent_conditions(app.bm, threat).reaction_used, \
            "the expiry spent the reaction: it took the attack instead of skipping it"
        assert _pos(app, "Mover") == (6, 6), "the move did not complete after the skip"
        assert not app.context_menu.visible, "the DM's popup outlived the expiry"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_a_players_oa_expires_on_the_tick")


def test_an_expiry_is_logged_as_an_expiry():
    """The log says the clock skipped it. The DM chose nothing, so it is not a takeover."""
    tmp = tempfile.mkdtemp()
    try:
        app, _, p = _oa(tmp)
        _lapse(p)
        net_link.pump_submits(app)
        lines = _lines(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert [(l["event"], l["principal"], l["prompt"], l["kind"]) for l in lines] == [
        ("expired", CLOCK_PRINCIPAL_ID, p.id, "reaction")], lines
    print("✅ test_an_expiry_is_logged_as_an_expiry")


def test_a_late_submit_after_expiry_is_not_live():
    """NN4: the clock answered first, so Kira's answer after it is refused and runs nothing."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, p = _oa(tmp)
        threat = _idx(app, "Threat")
        wlabel = next(o.label for o in app.combat.pending_decision().ctx.options
                      if o.kind == rpg.ReactionOptionKind.Weapon)
        weapon = next(o.id for o in p.options if o.label == wlabel)
        _lapse(p)
        net_link.pump_submits(app)
        late = app.prompts.submit(p.id, Response(option=weapon), kira.id)
        used = app.combat.get_agent_conditions(app.bm, threat).reaction_used
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not late.ok and late.error == "not_live", late
    assert not used, "the late answer ran its attack after the skip"
    print("✅ test_a_late_submit_after_expiry_is_not_live")


# ─────────────────────────────────────────────────────────────────────────────
#  Who gets a deadline
# ─────────────────────────────────────────────────────────────────────────────

def test_only_a_players_reaction_gets_a_deadline():
    """A player's reaction: yes, the DM's setting. The action offer, a player's action or
    target prompt, the DM's own reaction, or any prompt with the timer off: no."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, p = _oa(tmp)
        left = p.deadline - time.monotonic()
        assert 55.0 < left <= 60.0, f"the OA's deadline is {left:.1f} s away, not the default 60"

        offer_app, offer_kira, _ = _aria_turn()
        offer = _offer(offer_app)
        assert offer is not None and offer.owner == offer_kira.id
        assert offer.deadline is None and offer.to_wire()["deadline_ms"] is None, \
            "the action offer has a deadline: expiry would end a player's turn"
        aria = _idx(offer_app, "Aria")
        for kind in ("action", "target"):
            q = offer_app._ask_actor(aria, kind, "Pick", [("A", lambda: None)],
                                     on_cancel=lambda: None)
            assert q.owner == offer_kira.id and q.deadline is None, kind
        q = offer_app._ask_actor(aria, "reaction", "React", [("Skip", lambda: None)],
                                 on_cancel=lambda: None)
        assert q.deadline is not None, "a player's GUI reaction got no deadline"

        dm_app, _, _ = _parked_app()                   # nobody seated: the DM's OA
        dm_p = dm_app.prompts.live
        assert dm_p.kind == "reaction" and dm_p.owner == DM_PRINCIPAL_ID
        assert dm_p.deadline is None, "the DM's own reaction would time out on the DM"

        app.reaction_timeout_s = None
        assert app._reaction_deadline("reaction", kira.id, lambda: None) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_only_a_players_reaction_gets_a_deadline")


def test_riposte_expires_to_its_skip():
    """A reaction built in `menus/reactions.py` carries an explicit Skip row. Expiry must run
    it: the original miss is logged and the attack sequence continues, as a click on Skip
    would. Cancelling a prompt with nothing to run would leave the attack parked."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, p = _oa(tmp)
        app.prompts.cancel(p.id)                       # clear the OA; this test is the Riposte
        atk, tgt = _idx(app, "Mover"), _idx(app, "Threat")   # Threat is Kira's
        continued = []
        app._continue_attack_sequence_after_rider = lambda idx: continued.append(idx)
        logged = []
        app._combat_log_add = lambda msg: logged.append(msg)
        reactions.offer_riposte(app, None, atk, tgt, "Mover", "Threat", None,
                                "Mover→Threat: misses")
        r = app.prompts.live
        assert r is not None and r.kind == "reaction" and r.owner == kira.id
        _lapse(r)
        net_link.pump_submits(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert r.state is PromptState.CANCELLED and r.resolved_by == CLOCK_PRINCIPAL_ID
    assert continued == [atk], "the expiry did not run Riposte's Skip"
    assert logged == ["Mover→Threat: misses"], logged
    print("✅ test_riposte_expires_to_its_skip")


def test_every_gui_reaction_carries_its_skip():
    """Static, over `menus/reactions.py`: every `_ask_actor(…, "reaction", …)` passes
    `on_cancel`. A site without one gets no deadline (`_reaction_deadline`), so forgetting it
    is a player who can stall the table, which is exactly what D-M5-7 exists to stop."""
    tree = ast.parse(open(_REACTIONS, encoding="utf-8").read())
    sites = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_ask_actor" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "reaction"):
            kw = {k.arg: k.value for k in node.keywords}
            sites.append((node.lineno, kw.get("on_cancel")))
    assert len(sites) == 5, f"{len(sites)} reaction sites, expected 5"
    missing = [line for line, cb in sites if not (isinstance(cb, ast.Name) and cb.id == "_skip")]
    assert not missing, f"reaction prompts with no Skip as on_cancel at lines {missing}"
    print("✅ test_every_gui_reaction_carries_its_skip")


# ─────────────────────────────────────────────────────────────────────────────
#  The DM's setting
# ─────────────────────────────────────────────────────────────────────────────

def test_the_dm_sets_the_timer():
    """The session row's button cycles the value and labels it. Only the DM may press it,
    pressing it does not take a player's turn from them, and a resumed fight keeps it."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        offer = _offer(app)
        assert app.reaction_timeout_s == 60
        assert app._action_menu["reaction_timer"].label == "React 60s"
        assert app.perform("reaction_timer", kira.id) is False, "a player set the DM's timer"
        assert app.reaction_timeout_s == 60

        seen = []
        for _ in range(5):
            assert app.perform("reaction_timer", DM_PRINCIPAL_ID) is True
            seen.append(app.reaction_timeout_s)
            app._draw_panel()
        assert seen == [120, None, 15, 30, 60], seen
        app.perform("reaction_timer", DM_PRINCIPAL_ID)
        app._draw_panel()
        # The DM's real click, on Kira's turn: it sets the timer and takes nothing over.
        post_click(app, panel.cbt_btn(app, "reaction_timer").rect.center)
        app._draw_panel()
        net_offer.ensure(app)
        assert app.reaction_timeout_s is None
        assert app._action_menu["reaction_timer"].label == "React untimed"
        assert _offer(app) is offer and offer.is_live, "setting the timer took Kira's turn over"
        assert _lines(app) == [], _lines(app)

        path = os.path.join(tmp, "t_combat.json")
        app.combat_active = True
        app._save_combat_state(path)
        app.reaction_timeout_s = 30
        assert app._load_combat_state(path)
        assert app.reaction_timeout_s is None, "the resumed fight lost the DM's timer"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_the_dm_sets_the_timer")


# ─────────────────────────────────────────────────────────────────────────────
#  End to end
# ─────────────────────────────────────────────────────────────────────────────

def test_an_unanswered_oa_in_the_browser():
    """`test_submit.test_an_opportunity_attack_from_the_browser`, with a player who never
    answers. Their phone is told how long they have, and then the prompt goes away with the
    move completed and the reaction unspent."""
    with _table(_oa_scene) as t:
        app = t.app
        p = app.prompts.live
        assert p is not None and p.owner == t.kira.id
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wire = _next(kira, "prompt")
            assert wire["id"] == p.id
            assert 0 < wire["deadline_ms"] <= 60_000, wire["deadline_ms"]
            p.deadline = time.monotonic() - 1.0        # the minute passes; the tick sees it
            after = _next(kira, "view", match=lambda v: v["you"]["prompt_id"] is None)
        t.stop()
        lines = t.log()
        threat = _idx(app, "Threat")
        assert after["you"]["prompt_id"] is None
        assert p.state is PromptState.CANCELLED and p.resolved_by == CLOCK_PRINCIPAL_ID
        assert not app.combat.pending_decision().active, "the parked window did not resolve"
        assert not app.combat.get_agent_conditions(app.bm, threat).reaction_used
        assert _pos(app, "Mover") == (6, 6), "the move did not complete after the skip"
    assert [(l["event"], l["principal"]) for l in lines] == [("expired", CLOCK_PRINCIPAL_ID)], \
        lines
    print("✅ test_an_unanswered_oa_in_the_browser")


if __name__ == "__main__":
    test_deadline_ms_is_the_time_left()
    test_a_players_oa_expires_on_the_tick()
    test_an_expiry_is_logged_as_an_expiry()
    test_a_late_submit_after_expiry_is_not_live()
    test_only_a_players_reaction_gets_a_deadline()
    test_riposte_expires_to_its_skip()
    test_every_gui_reaction_carries_its_skip()
    test_the_dm_sets_the_timer()
    test_an_unanswered_oa_in_the_browser()
    print("\n✅ All deadline tests passed!")
