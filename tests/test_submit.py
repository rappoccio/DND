#!/usr/bin/env python3
"""The submit path, end to end (MULTIPLAYER_PLAN.md M5a; D-M5-3, D-M5-6a, D-M5-9).

M4e made the socket push. M5a makes it answer. A `prompt` reaches the player who may answer
it and no one else, their `submit` crosses to the frame tick, `PromptBus` decides it with
`authorize()` in front, and a `submit_ack` comes back. Everything the answer *did* reaches
every viewer as the next `view`. These checks drive that loop through a real socket, with
the hand-rolled client `test_live.py` uses, against a real `App`:

  · the prompt body reaches only who may answer it (F-M5-6)    (test_the_prompt_reaches_only_who_may_answer)
  · a submit is decided on the frame tick, and acked            (test_a_submit_is_decided_on_the_frame_tick)
  · the wrong player is denied and the prompt stays live        (test_the_wrong_player_is_denied)
  · the first valid submission wins (NN4)                       (test_the_first_submission_wins)
  · cancel runs the prompt's own on_cancel (D-M5-3)              (test_cancel_over_the_wire)
  · a malformed submit is `protocol` and runs nothing           (test_a_malformed_submit_runs_nothing)
  · a frame loop that does not answer is `timeout`, not a loss  (test_a_stalled_frame_loop_is_a_timeout)
  · a modal's pump never decides a submit                       (test_a_modal_never_decides_a_submit)
  · the log keeps principal ids, never names (D-M5-6a)          (test_the_log_keeps_ids_not_names)
  · the DM's browser is one line, not a submit and a takeover   (test_the_dms_browser_is_logged_once)
  · the DM taking a prompt over is a log line (D-M5-7)          (test_a_takeover_is_logged)
  · an opportunity attack, taken from the browser               (test_an_opportunity_attack_from_the_browser)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import asyncio
import contextlib
import json
import shutil
import tempfile
import threading
import time

import rpg_battle_map as rpg

from main import App
from net import link as net_link, server as net_server, submit as net_submit, \
    view as net_view
from net.roster import DM_PRINCIPAL_ID, PROTOCOL_VERSION, Role
from net.server import PlayerServer
from prompts import Option, PromptState

from test_gameview import _scene, _idx
from test_live import _auth_frame, _faster_cadence, _ws
from test_mapserver import _free_port
from test_prompts import (FOE_TEAM, MAP_PATH, PC_TEAM, SEED, _oa_weapon, _place)


# ─────────────────────────────────────────────────────────────────────────────
#  Rig: a real App, a real server, and a stand-in frame loop that does what run() does
# ─────────────────────────────────────────────────────────────────────────────

class _Table:
    """`test_mapserver._server`, grown the two M5a seams `start_player_server` passes.

    The stand-in frame tick runs, per iteration, the three net calls `run()` makes: the
    submit pump (beside `_handle_events`), the command pump and the push cycle. They share
    one thread because in `run()` they are one thread, and the check that a submit ran
    "on the frame tick" compares against this thread's ident.
    """

    def __init__(self, app, tmp):
        self.app, self.tmp = app, tmp
        app.submit_log.path = os.path.join(tmp, "submit_log.jsonl")
        self.srv = PlayerServer(app.roster, app.map_images, app._net_commands,
                                net_view.build_view,
                                submits=app._net_submits,
                                handle_submit=net_submit.handle_submit,
                                build_live=net_link.build_live,
                                host="127.0.0.1", port=_free_port())
        self.srv.start()
        app._net = self.srv
        self.ticker = None
        self._ticking = False

    def credential(self, principal_id):
        return self.app.roster.mint_credential(principal_id)

    def start(self, interval=0.002):
        self._ticking = True
        self.ticker = threading.Thread(target=self._tick, args=(interval,), daemon=True,
                                       name="fake-frame-tick")
        self.ticker.start()

    def stop(self):
        self._ticking = False
        t, self.ticker = self.ticker, None
        if t is not None:
            t.join(2.0)

    def _tick(self, interval):
        while self._ticking:
            net_link.pump_submits(self.app)
            self.app._net_commands.pump(self.app)
            net_link.push_cycle(self.app)
            time.sleep(interval)

    def close(self):
        self.stop()
        self.srv.stop()

    def log(self):
        path = self.app.submit_log.path
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]


@contextlib.contextmanager
def _table(build=None):
    tmp = tempfile.mkdtemp()
    table = None
    try:
        app, kira, spectator = (build or _scene)(tmp)
        table = _Table(app, tmp)
        table.kira, table.spectator = kira, spectator
        with _faster_cadence():
            yield table
    finally:
        if table is not None:
            table.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _submit(prompt_id, **answer) -> str:
    return json.dumps(dict({"v": PROTOCOL_VERSION, "t": "submit", "id": prompt_id}, **answer))


def _next(sock, kind, timeout=5.0, match=None):
    """The next frame of type `kind` (and matching `match`, if given), skipping the rest."""
    end = time.monotonic() + timeout
    while True:
        left = end - time.monotonic()
        assert left > 0, f"no {kind} frame arrived within {timeout}s"
        got = sock.recv(timeout=left)
        assert got[0] == "text", f"the socket closed ({got[1]}) waiting for a {kind}"
        frame = json.loads(got[1])
        if frame.get("t") == kind and (match is None or match(frame)):
            return frame


def _drain(sock, seconds):
    """Every text frame for `seconds`, as raw strings — the byte-level checks search these."""
    out, end = [], time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return out
        try:
            got = sock.recv(timeout=left)
        except Exception:
            return out
        if got[0] != "text":
            return out
        out.append(got[1])


def _ask(app, owner, title="Kira's question", on_cancel=None):
    """A two-option prompt owned by `owner`. Returns (prompt, record of what ran, and where)."""
    ran = {}

    def choose(label):
        def cb():
            ran["option"] = label
            ran["thread"] = threading.get_ident()
        return cb

    p = app.prompts.ask(actor_idx=_idx(app, "Aria"), owner=owner, kind="reaction",
                        title=title,
                        options=[Option("opt_0", "Strike", on_choose=choose("Strike")),
                                 Option("opt_1", "Hold", enabled=False,
                                        disabled_reason="Reaction already used",
                                        on_choose=choose("Hold"))],
                        on_cancel=on_cancel)
    return p, ran


# ─────────────────────────────────────────────────────────────────────────────
#  The prompt envelope's gate (F-M5-6)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_prompt_reaches_only_who_may_answer():
    """A prompt a viewer may not answer is never sent — not greyed, not at all (Step 0.5).

    Byte-level, like M3's fog checks: the spectator's whole stream is searched for the
    prompt's id and its title, over enough cycles that "it happened not to be sent yet"
    is not the reason it is absent. The DM gets it, because NN4 lets the DM answer anything.
    """
    with _table() as t:
        p, _ = _ask(t.app, t.kira.id, title="Only-Kira-sees-this")
        t.start()
        with _ws(t.srv.port) as kira, _ws(t.srv.port) as wen, _ws(t.srv.port) as dm:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wen.send_text(_auth_frame(t.credential(t.spectator.id)))
            dm.send_text(_auth_frame(t.credential(DM_PRINCIPAL_ID)))

            got = _next(kira, "prompt")
            assert got == p.to_wire(), "the prompt frame is not the bus's own projection"
            assert got["options"][1]["enabled"] is False
            assert got["options"][1]["disabled_reason"] == "Reaction already used"
            assert _next(dm, "prompt")["id"] == p.id, "the DM was not sent the prompt"

            stream = _drain(wen, 0.6)
            assert len(stream) >= 3, f"only {len(stream)} frames in 0.6 s — the check is vacuous"
            assert not any(p.id in f or "Only-Kira-sees-this" in f for f in stream), \
                "a prompt crossed to a viewer who may not answer it"
    print("✅ test_the_prompt_reaches_only_who_may_answer")


# ─────────────────────────────────────────────────────────────────────────────
#  Submitting
# ─────────────────────────────────────────────────────────────────────────────

def test_a_submit_is_decided_on_the_frame_tick():
    """The callback runs on the thread that runs the frame loop, never on the net thread
    (F1, NN1), and the ack reaches the submitter."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            _next(kira, "prompt")
            kira.send_text(_submit(p.id, option="opt_0"))
            ack = _next(kira, "submit_ack")
        assert ack == {"v": 1, "t": "submit_ack", "id": p.id, "ok": True}, ack
        assert ran.get("option") == "Strike", f"the option's callback did not run: {ran}"
        assert ran["thread"] == t.ticker.ident, "the submit was decided off the frame tick"
        assert p.state is PromptState.ANSWERED and p.resolved_by == t.kira.id
    print("✅ test_a_submit_is_decided_on_the_frame_tick")


def test_the_wrong_player_is_denied():
    """`authorize()` is asked on the frame tick with the socket's own principal. A prompt id
    is not a secret — ids are sequential — so knowing one must buy nothing."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as wen:
            wen.send_text(_auth_frame(t.credential(t.spectator.id)))
            _next(wen, "view")
            wen.send_text(_submit(p.id, option="opt_0"))
            ack = _next(wen, "submit_ack")
        assert ack["ok"] is False and ack["error"] == "denied", ack
        assert not ran, "a denied submit ran the callback"
        assert p.is_live, "a denied submit resolved the prompt"
    print("✅ test_the_wrong_player_is_denied")


def test_the_first_submission_wins():
    """NN4. The second answer to one prompt is `not_live`, and a disabled option is
    `bad_option` — the two refusals a player can actually meet."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            _next(kira, "prompt")
            kira.send_text(_submit(p.id, option="opt_1"))
            assert _next(kira, "submit_ack")["error"] == "bad_option"
            kira.send_text(_submit(p.id, option="opt_0"))
            assert _next(kira, "submit_ack")["ok"] is True
            kira.send_text(_submit(p.id, option="opt_0"))
            again = _next(kira, "submit_ack")
        assert again["ok"] is False and again["error"] == "not_live", again
        assert ran["option"] == "Strike"
    print("✅ test_the_first_submission_wins")


def test_cancel_over_the_wire():
    """D-M5-3: `{"cancel": true}` is a remote Esc. It runs the prompt's own `on_cancel` —
    for a reaction, the Skip — and is refused, like an answer, to anyone else."""
    with _table() as t:
        cancelled = []
        p, ran = _ask(t.app, t.kira.id, on_cancel=lambda: cancelled.append(True))
        t.start()
        with _ws(t.srv.port) as kira, _ws(t.srv.port) as wen:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wen.send_text(_auth_frame(t.credential(t.spectator.id)))
            _next(kira, "prompt")
            _next(wen, "view")
            wen.send_text(_submit(p.id, cancel=True))
            assert _next(wen, "submit_ack")["error"] == "denied"
            assert p.is_live and not cancelled, "someone else's cancel dismissed the prompt"
            kira.send_text(_submit(p.id, cancel=True))
            ack = _next(kira, "submit_ack")
        assert ack["ok"] is True, ack
        assert cancelled == [True], "on_cancel did not run"
        assert p.state is PromptState.CANCELLED and not ran
    print("✅ test_cancel_over_the_wire")


def test_a_malformed_submit_runs_nothing():
    """Shape is checked before the bus is asked, and every wrong shape is `protocol`.

    Each frame here is one a hostile or buggy client could send with a *valid* prompt id,
    so the prompt must still be live and untouched after all of them."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        bad = [
            {"option": "opt_0", "cancel": True},       # two answers
            {"cell": [1]},                             # not a cell
            {"cell": [1, "2"]},
            {"agent": True},                           # a bool is not an agent index
            {"cancel": False},                         # cancel is `true` or absent
            {},                                        # no answer at all
            {"option": 7},                             # an option id is a string
        ]
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            _next(kira, "prompt")
            for answer in bad:
                kira.send_text(_submit(p.id, **answer))
                ack = _next(kira, "submit_ack")
                assert ack["error"] == "protocol", f"{answer} was answered {ack}"
            kira.send_text(json.dumps({"v": 1, "t": "submit", "option": "opt_0"}))
            assert _next(kira, "submit_ack") == {"v": 1, "t": "submit_ack", "id": "",
                                                 "ok": False, "error": "protocol"}
            kira.send_text(_submit("pr_99999", option="opt_0"))
            assert _next(kira, "submit_ack")["error"] == "protocol", "an unknown id"
        assert p.is_live and not ran, "a malformed submit touched the prompt"
    print("✅ test_a_malformed_submit_runs_nothing")


def test_a_stalled_frame_loop_is_a_timeout():
    """Step 0.5's `timeout`: the one error the net thread raises, meaning *queued and not
    yet decided*. It is not a loss — the submit is still in the queue, and when the frame
    loop comes back it is decided. That is why the client may never resubmit blindly."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            _next(kira, "prompt")
            t.stop()                                       # the DM opened a modal
            assert net_server.STATE_TIMEOUT_S == 5.0, \
                f"D-M4c-2 froze the timeout at 5 s; it is {net_server.STATE_TIMEOUT_S}"
            original, net_server.STATE_TIMEOUT_S = net_server.STATE_TIMEOUT_S, 0.3
            try:
                kira.send_text(_submit(p.id, option="opt_0"))
                ack = _next(kira, "submit_ack")
            finally:
                net_server.STATE_TIMEOUT_S = original
            assert ack["error"] == "timeout", ack
            assert p.is_live and not ran, "a timed-out submit was decided off the frame tick"
            t.start()                                      # the modal closes
            deadline = time.monotonic() + 3.0
            while p.is_live and time.monotonic() < deadline:
                time.sleep(0.01)
        assert ran.get("option") == "Strike", "the queued submit was lost, not deferred"
    print("✅ test_a_stalled_frame_loop_is_a_timeout")


def test_a_modal_never_decides_a_submit():
    """A submit is input, not a command: `_pump_net()` — which the six blocking modals call —
    leaves it queued, and only `run()`'s `pump_submits` decides it. A submit decided inside a
    modal would run an opportunity attack underneath a dialog the DM is reading."""
    tmp = tempfile.mkdtemp()
    loop = asyncio.new_event_loop()
    try:
        app, _kira, _ = _scene(tmp)
        ran = []
        future = loop.create_future()
        app._net_submits._pending.append((lambda a: ran.append(True), loop, future))
        app._pump_net()
        assert not ran and app._net_submits.pending == 1, "a modal's pump decided a submit"
        assert net_link.pump_submits(app) == 1 and ran == [True]
    finally:
        loop.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_a_modal_never_decides_a_submit")


# ─────────────────────────────────────────────────────────────────────────────
#  The submit log (D-M5-6a)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_log_keeps_ids_not_names():
    """One line per submit — accepted, refused, malformed, cancelled — keyed by principal
    id. A display name is what a player typed at the join card (A2/A4), and it never
    reaches the log."""
    with _table() as t:
        p, _ = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as kira, _ws(t.srv.port) as wen:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wen.send_text(_auth_frame(t.credential(t.spectator.id)))
            _next(kira, "prompt")
            _next(wen, "view")
            wen.send_text(_submit(p.id, option="opt_0"))
            _next(wen, "submit_ack")
            kira.send_text(_submit(p.id, cell=[1]))
            _next(kira, "submit_ack")
            kira.send_text(_submit(p.id, option="opt_0"))
            _next(kira, "submit_ack")
        t.stop()
        lines = t.log()
        raw = open(t.app.submit_log.path, encoding="utf-8").read()
    assert [l["principal"] for l in lines] == [t.spectator.id, t.kira.id, t.kira.id], lines
    assert [(l["ok"], l.get("error")) for l in lines] == \
        [(False, "denied"), (False, "protocol"), (True, None)], lines
    assert lines[2]["prompt"] == p.id and lines[2]["answer"] == {"option": "opt_0"}
    assert lines[2]["kind"] == "reaction" and lines[2]["event"] == "submit"
    assert "Kira" not in raw and "Wen" not in raw, "a display name reached the submit log"
    print("✅ test_the_log_keeps_ids_not_names")


def test_the_dms_browser_is_logged_once():
    """The DM's own browser is a remote submitter like any other. Its answer to a player's
    prompt is one `submit` line — the bus observer that logs console takeovers must not log
    it a second time as a `takeover`."""
    with _table() as t:
        p, ran = _ask(t.app, t.kira.id)
        t.start()
        with _ws(t.srv.port) as dm:
            dm.send_text(_auth_frame(t.credential(DM_PRINCIPAL_ID)))
            _next(dm, "prompt")
            dm.send_text(_submit(p.id, option="opt_0"))
            assert _next(dm, "submit_ack")["ok"] is True
        t.stop()
        lines = t.log()
    assert ran.get("option") == "Strike"
    assert [(l["event"], l["principal"]) for l in lines] == [("submit", DM_PRINCIPAL_ID)], lines
    print("✅ test_the_dms_browser_is_logged_once")


def test_a_takeover_is_logged():
    """D-M5-7: the DM answering or dismissing a player's prompt on the console is a line,
    because "why did my character do that" is exactly the bug report the log is for. The
    DM answering the DM's own prompt is not, and nothing is logged with no table."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _scene(tmp)
        p, _ = _ask(app, kira.id)
        app.prompts.choose("opt_0")                   # no transport: nothing written
        assert app.submit_log.lines == 0

        app.submit_log.path = os.path.join(tmp, "submit_log.jsonl")
        p, _ = _ask(app, kira.id)
        app.prompts.choose("opt_0")                   # the DM's click, on Kira's prompt
        q, _ = _ask(app, kira.id)
        app.prompts.cancel()                          # the DM's Esc
        r, _ = _ask(app, DM_PRINCIPAL_ID)
        app.prompts.choose("opt_0")                   # the DM's own prompt: not a takeover
        with open(app.submit_log.path, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert [(l["event"], l["prompt"], l["answer"]) for l in lines] == [
        ("takeover", p.id, {"option": "opt_0"}),
        ("takeover", q.id, {"cancel": True}),
    ], lines
    assert all(l["principal"] == DM_PRINCIPAL_ID for l in lines)
    print("✅ test_a_takeover_is_logged")


# ─────────────────────────────────────────────────────────────────────────────
#  The slice's reason for existing: a reaction, taken from a phone
# ─────────────────────────────────────────────────────────────────────────────

def _oa_scene(tmp):
    """`test_prompts._parked_app`, with the reactor seated to a player *before* the move,
    so the reaction prompt is born owned by them — which is how it happens at a table."""
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmp, "submit_oa_agents.json"))
    _place(app, "Mover", 5, 5)
    _place(app, "Threat", 4, 5)
    app.combat.apply_agent_configs(app.bm)
    mover, threat = _idx(app, "Mover"), _idx(app, "Threat")
    app.bm.set_agent_faction(mover, FOE_TEAM)
    app.bm.set_agent_faction(threat, PC_TEAM)

    s = app.combat.get_agent_stats(app.bm, mover)
    s.speed_walk = 60
    app.combat.set_agent_stats(app.bm, mover, s)
    app.combat.begin_turn(app.bm, mover)
    app.bm.placed_agents[mover].init_movement(60, 0, 0, 0)
    app.combat.set_agent_weapons(app.bm, threat, [_oa_weapon(), rpg.Weapon(), rpg.Weapon()])

    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    wen = app.roster.add_principal("Wen", role=Role.PLAYER)
    app.bm.set_agent_controller(threat, kira.id)
    app._sync_roster_tokens()

    status = app.combat.begin_move(app.bm, mover, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected a parked OA, got {status}"
    app._show_pending_reaction_menu()
    return app, kira, wen


def test_an_opportunity_attack_from_the_browser():
    """M5a's acceptance: the engine parks on a real opportunity attack, the prompt reaches
    the reactor's player, their submit crosses the socket, and the engine resumes exactly
    as it does for the DM's click (`test_prompts.test_answer_resumes_the_move`)."""
    with _table(_oa_scene) as t:
        app = t.app
        mover, threat = _idx(app, "Mover"), _idx(app, "Threat")
        p = app.prompts.live
        assert p is not None and p.owner == t.kira.id, "the OA prompt is not the player's"
        weapon_label = next(o.label for o in app.combat.pending_decision().ctx.options
                            if o.kind == rpg.ReactionOptionKind.Weapon)
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wire = _next(kira, "prompt")
            view = _next(kira, "view")
            assert view["you"]["prompt_id"] == wire["id"] == p.id
            assert "opportunity attack" in wire["title"]
            weapon = next(o for o in wire["options"] if o["label"] == weapon_label)
            kira.send_text(_submit(p.id, option=weapon["id"]))
            ack = _next(kira, "submit_ack")
            assert ack["ok"] is True, ack
            after = _next(kira, "view", match=lambda v: v["you"]["prompt_id"] is None)
        t.stop()
        assert not app.combat.pending_decision().active, "the parked window did not resolve"
        assert app.combat.get_agent_conditions(app.bm, threat).reaction_used, \
            "the opportunity attack did not consume the reaction"
        o = app.bm.placed_agents[mover].origin
        assert (o.col, o.row) == (6, 6), "the move did not complete once the window resolved"
        assert not app.context_menu.visible, "the DM's popup outlived the remote answer"
        assert after["you"]["prompt_id"] is None
    print("✅ test_an_opportunity_attack_from_the_browser")


if __name__ == "__main__":
    test_the_prompt_reaches_only_who_may_answer()
    test_a_submit_is_decided_on_the_frame_tick()
    test_the_wrong_player_is_denied()
    test_the_first_submission_wins()
    test_cancel_over_the_wire()
    test_a_malformed_submit_runs_nothing()
    test_a_stalled_frame_loop_is_a_timeout()
    test_a_modal_never_decides_a_submit()
    test_the_log_keeps_ids_not_names()
    test_the_dms_browser_is_logged_once()
    test_a_takeover_is_logged()
    test_an_opportunity_attack_from_the_browser()
    print("\n✅ All submit tests passed!")
