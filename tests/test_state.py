#!/usr/bin/env python3
"""`GET /state` and the command queue under it (MULTIPLAYER_PLAN.md M4c, D-M4c-1/2).

`test_gameview.py` proves the projection and `test_mapserver.py` proves that routes hand
bytes only to callers who authenticated. Neither can prove the thing M4c actually added:
that the view crossing this route was **built on the pygame thread**. `build_view` reads
`app.bm`, so a handler that called it directly would pass every field-level check here and
violate NN1 on every request — which is why the headline check in this file asserts about a
thread identity rather than about a payload.

The rest is what a parked request does when the game thread does not come back, which F1
measured and F2 explained: submit latency is exactly "time to the next pump", and unbounded
whenever `run()` is not looping.

Rig, scene and transport are `test_mapserver.py`'s, with its frame-tick stand-in running.

  · the body is byte-identical to the projection's own output  (test_state_is_the_projection_verbatim)
  · ...and the DM's view is a different one                    (test_the_dm_gets_the_dm_view)
  · the view is built on the pumping thread, never the net one (test_the_view_is_built_on_the_pumping_thread)
  · no credential and a revoked one are both 401               (test_state_requires_a_credential)
  · a frame loop that never pumps is a bounded 503             (test_a_wedged_frame_loop_is_a_503)
  · ...and the late pump that follows kills nothing            (test_a_late_pump_is_dropped_not_crashed)
  · a command that raises is a status, not a dead frame loop   (test_a_raising_command_does_not_kill_the_pump)
  · build_view refusing a viewer is a 403                      (test_permission_error_is_403)
  · a command hands back data the caller owns                  (test_the_command_returns_data_the_caller_owns)
  · a flood is capped per frame rather than drained            (test_the_pump_is_bounded)
  · a view is never cached                                     (test_a_view_is_never_cached)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import logging
import threading
import time

from net import server as net_server
from net.commands import DEFAULT_BUDGET
from net.view import build_view

from test_mapserver import _server


# ─────────────────────────────────────────────────────────────────────────────
#  What comes back
# ─────────────────────────────────────────────────────────────────────────────

def test_state_is_the_projection_verbatim():
    """The route adds nothing to the view and removes nothing from it.

    Compared against `build_view`'s own output rather than against a hand-written shape,
    because M3's acceptance criterion is a byte-level one and a route that re-assembled the
    dict would be a second, untested projection sitting in front of the tested one. The
    `map` block is left out: its `image` key is the published snapshot's hash, which is a
    property of what the frame tick last published rather than of the projection.
    """
    with _server(pump=True) as s:
        s.publish()
        status, _headers, raw = s.get("/state", credential=s.player)
        assert status == 200, f"an authenticated /state returned {status}"
        served = json.loads(raw)
        direct = build_view(s.app, s.kira)

        assert served["v"] == direct["v"] and served["t"] == "view"
        assert served["seq"] == 0, "seq is 0 until EventStream (S3) exists"
        for block in ("you", "fog", "combat", "agents", "terrain", "lighting",
                      "effects", "log"):
            assert served[block] == direct[block], f"the route altered the {block} block"

        # The projection's own guarantee, re-checked through the socket: the creature in
        # the fog is not in the bytes that left the process.
        assert "Skarn" not in raw.decode(), \
            "an unexplored enemy crossed the wire — the route is not serving the projection"
        print("✅ test_state_is_the_projection_verbatim")


def test_the_dm_gets_the_dm_view():
    """Which view is a policy question, and it is asked of `authorize()` inside the
    projection (A8). The route does not choose — it passes the principal and gets whatever
    that principal is entitled to, which is the property that keeps `if viewer == "dm"` out
    of the transport."""
    with _server(pump=True) as s:
        s.publish()
        player = json.loads(s.get("/state", credential=s.player)[2])
        dm = json.loads(s.get("/state", credential=s.dm)[2])
        assert {a["name"] for a in dm["agents"]} > {a["name"] for a in player["agents"]}, \
            "the DM's view was no wider than the player's"
        assert "Skarn" in {a["name"] for a in dm["agents"]}
        print("✅ test_the_dm_gets_the_dm_view")


# ─────────────────────────────────────────────────────────────────────────────
#  The headline: which thread built it (NN1, D-M4c-1)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_view_is_built_on_the_pumping_thread():
    """NN1's witness, and the whole reason this route is not a function call.

    A handler that called `build_view` itself would serve a correct-looking view and read
    the `BattleMap` off the pygame thread on every request. No assertion about the payload
    can see that, so this one asks the command which thread ran it and compares against the
    thread that pumped — which is also, deliberately, not the thread the test is on.
    """
    with _server(pump=True) as s:
        s.publish()
        seen = {}

        def spy(app, viewer):
            seen["builder"] = threading.get_ident()
            return build_view(app, viewer)

        s.srv._build_view = spy
        assert s.get("/state", credential=s.player)[0] == 200

        assert "builder" in seen, "the route never ran the injected builder"
        assert seen["builder"] == s._ticker.ident, \
            "the view was not built on the thread that pumps the queue — NN1"
        assert seen["builder"] != threading.get_ident(), \
            "the view was built on the requesting thread, which proves nothing"
        print("✅ test_the_view_is_built_on_the_pumping_thread")


def test_state_requires_a_credential():
    """`/state` is not exempt, and it is the one route where forgetting that would hand
    the whole session to anyone who can reach the port."""
    with _server(pump=True) as s:
        s.publish()
        status, headers, _ = s.get("/state")
        assert status == 401, f"an anonymous /state returned {status}"
        assert headers.get("WWW-Authenticate") == "Bearer"

        s.app.roster.revoke_credential(s.player)
        assert s.get("/state", credential=s.player)[0] == 401, \
            "a revoked credential was still served a view"
        print("✅ test_state_requires_a_credential")


# ─────────────────────────────────────────────────────────────────────────────
#  When the frame tick does not come back — F1, F2
# ─────────────────────────────────────────────────────────────────────────────

def test_a_wedged_frame_loop_is_a_503():
    """F1's finding, in the form a client sees it.

    Until M4d puts `_pump_net()` in the six blocking modals, this is also what a `/state`
    issued while *Generate Dungeon* is open does. A bounded wrong answer beats a hang, and
    it beats a made-up `{"t": "view", "ok": false}` — Envelope 2 has no error shape and is
    not given one here.

    The constant is monkeypatched down so the suite does not spend five seconds proving a
    timeout works, and asserted separately so the patch cannot hide a changed freeze.
    """
    assert net_server.STATE_TIMEOUT_S == 5.0, \
        f"D-M4c-2 froze the timeout at 5 s; it is {net_server.STATE_TIMEOUT_S}"

    with _server() as s:                      # no pump: nothing will ever answer
        s.publish()
        original, net_server.STATE_TIMEOUT_S = net_server.STATE_TIMEOUT_S, 0.4
        try:
            began = time.monotonic()
            status, headers, _ = s.get("/state", credential=s.player)
        finally:
            net_server.STATE_TIMEOUT_S = original
        elapsed = time.monotonic() - began

        assert status == 503, f"a wedged frame loop returned {status}, not 503"
        assert headers.get("Retry-After") == "1", "the 503 did not say when to come back"
        assert elapsed < 3.0, f"the request was not bounded by the timeout ({elapsed:.1f}s)"
        print("✅ test_a_wedged_frame_loop_is_a_503")


def test_a_late_pump_is_dropped_not_crashed():
    """The timeout cancelled a future the frame tick is still going to resolve.

    `wait_for` cancels on expiry, and a bare `set_result` on a cancelled future raises
    `InvalidStateError` — on the net loop, inside a `call_soon_threadsafe` callback, where
    nothing is waiting to catch it. The check is therefore not that the late answer is
    dropped but that the *server is still alive afterwards*, since that is the only way the
    damage would show.
    """
    with _server() as s:
        s.publish()
        original, net_server.STATE_TIMEOUT_S = net_server.STATE_TIMEOUT_S, 0.4
        try:
            assert s.get("/state", credential=s.player)[0] == 503
        finally:
            net_server.STATE_TIMEOUT_S = original

        assert s.app._net_commands.pending == 1, "the abandoned command left the queue"
        s.start_pump()                               # the frame loop comes back
        time.sleep(0.1)
        assert s.app._net_commands.pending == 0, "the late command never ran"

        status, _, raw = s.get("/state", credential=s.player)
        assert status == 200, f"the loop died resolving a cancelled future — {status}"
        assert json.loads(raw)["t"] == "view"
        print("✅ test_a_late_pump_is_dropped_not_crashed")


def test_a_raising_command_does_not_kill_the_pump():
    """Rule 2: an exception rides the future, and the next frame still happens.

    A `pump` that let `fn(app)` propagate would take down the frame loop — the one thread
    the whole app is — on behalf of one bad request. So the failure is asserted *and* the
    recovery is: a second request after it must still be served.
    """
    with _server(pump=True) as s:
        s.publish()

        def explode(_app, _viewer):
            raise RuntimeError("a command that should not take the app with it")

        s.srv._build_view = explode
        # aiohttp logs the 500's traceback, and a deliberate one in the middle of a green
        # suite reads exactly like a real failure. Silenced for this call and restored
        # immediately, so a traceback in this file's output still means something.
        noisy = logging.getLogger("aiohttp.server")
        was, noisy.disabled = noisy.disabled, True
        try:
            status, _, _ = s.get("/state", credential=s.player)
        finally:
            noisy.disabled = was
        assert status >= 500, f"a raising command returned {status}, not a server error"

        s.srv._build_view = build_view
        assert s.get("/state", credential=s.player)[0] == 200, \
            "the pump stopped after a command raised"
        print("✅ test_a_raising_command_does_not_kill_the_pump")


def test_permission_error_is_403():
    """`build_view` raises `PermissionError` for a viewer who may not receive a view at all.

    Unreachable in one thread — the route authorizes first — and perfectly reachable in
    two, for a seat pulled between the middleware and the pump. A flow, not a bug, and a
    403 rather than the 500 an unhandled raise would produce.
    """
    with _server(pump=True) as s:
        s.publish()

        def refuse(_app, _viewer):
            raise PermissionError("viewer is not seated")

        s.srv._build_view = refuse
        status, _, _ = s.get("/state", credential=s.player)
        assert status == 403, f"a refused viewer got {status}, not 403"
        print("✅ test_permission_error_is_403")


# ─────────────────────────────────────────────────────────────────────────────
#  The queue's own invariants
# ─────────────────────────────────────────────────────────────────────────────

def test_the_command_returns_data_the_caller_owns():
    """Rule 3, and the one the type system cannot state.

    A command that returned a live `App` structure would hand the net thread a reference
    into game state and make NN1 a question of what a handler happens not to read. `log` is
    the field where the obvious implementation gets it wrong: `app.combat_log` is a list
    sitting right there, and `build_view` copies it.
    """
    with _server(pump=True) as s:
        s.publish()
        view = build_view(s.app, s.kira)
        before = list(view["log"])
        s.app.combat_log.append("a line written after the view was built")
        assert view["log"] == before, \
            "the view aliased app.combat_log — the net thread is holding game state"
        print("✅ test_the_command_returns_data_the_caller_owns")


def test_the_pump_is_bounded():
    """A bound, not a tuning knob: an unbounded drain makes a flood of requests frame-time
    damage from the one route with no authentication in front of it."""
    class _sink:
        """A loop that accepts a scheduled resolution and does nothing with it. These
        commands have no requester, and the count is what this check is about."""
        def call_soon_threadsafe(self, fn):
            pass

    with _server() as s:
        queue = s.app._net_commands
        for _ in range(DEFAULT_BUDGET + 17):
            queue._pending.append((lambda _app: None, _sink(), None))

        ran = queue.pump(s.app)
        assert ran == DEFAULT_BUDGET, f"one pump ran {ran} commands, not {DEFAULT_BUDGET}"
        assert queue.pending == 17, f"{queue.pending} left, not the 17 over budget"
        assert queue.pump(s.app) == 17, "the remainder did not run on the next frame"
        print("✅ test_the_pump_is_bounded")


def test_a_view_is_never_cached():
    """Per-viewer live state that changes every tick. The conditional-request machinery
    `GET /map.png` earned is exactly wrong here, where nothing repeats."""
    with _server(pump=True) as s:
        s.publish()
        _status, headers, _ = s.get("/state", credential=s.player)
        assert headers.get("Cache-Control") == "no-store", \
            f"a view was served as {headers.get('Cache-Control')!r}"
        assert "ETag" not in headers, "a view carried a validator"
        print("✅ test_a_view_is_never_cached")


if __name__ == "__main__":
    test_state_is_the_projection_verbatim()
    test_the_dm_gets_the_dm_view()
    test_the_view_is_built_on_the_pumping_thread()
    test_state_requires_a_credential()
    test_a_wedged_frame_loop_is_a_503()
    test_a_late_pump_is_dropped_not_crashed()
    test_a_raising_command_does_not_kill_the_pump()
    test_permission_error_is_403()
    test_the_command_returns_data_the_caller_owns()
    test_the_pump_is_bounded()
    test_a_view_is_never_cached()
    print("\n✅ All state-route tests passed!")
