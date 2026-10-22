#!/usr/bin/env python3
"""M7, hardening (MULTIPLAYER_PLAN.md, M7 Step 0).

Covered here:
  · D-M7-2: the roster survives a join racing the DM       (test_the_roster_survives_racing_threads)
  · D-M7-2: the lock is not held across the bus hook       (test_the_bus_hook_runs_outside_the_lock)
  · D-M7-2: a command nobody waits for is never run        (test_a_cancelled_command_is_skipped)
  · D-M7-3: a bad first frame spends the address's guesses (test_a_bad_first_frame_spends_the_bucket)
  · D-M7-3: a fifth screen evicts the oldest, with 4408     (test_a_fifth_screen_evicts_the_oldest)
  · D-M7-3: a full table and a crowd of silent sockets      (test_the_socket_caps)
  · D-M7-3: a flood of frames closes the socket, 1008       (test_a_frame_flood_closes_the_socket)
  · D-M7-3: a third submit in flight never queues           (test_a_third_submit_is_refused)
  · D-M7-3: a fifth frame-tick read waiting is a 429        (test_frame_tick_reads_are_capped)
  · the client stops on 4408 and shows the join card on 4403 (test_the_client_knows_the_new_close_codes)
"""

import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from net import server as net_server
from net.commands import CommandQueue
from net.roster import (Action, DM_PRINCIPAL_ID, PromptTarget, Role, SessionRoster,
                        TokenInfo)


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-2 — the roster lock and the queue
# ─────────────────────────────────────────────────────────────────────────────

def test_the_roster_survives_racing_threads():
    """One thread seats players the way `POST /join` does; this one reads the roster the
    way a request and the frame tick do. Before the lock, `players()` iterating
    `_principals` while it grew could raise "dictionary changed size during iteration"."""
    roster = SessionRoster()
    roster.sync_tokens([TokenInfo(agent_idx=i, controller=DM_PRINCIPAL_ID, faction=2)
                        for i in range(8)])
    errors, done = [], threading.Event()

    def seat():
        try:
            for n in range(3000):
                p = roster.add_principal(f"P{n}")
                if n % 3 == 0:
                    roster.remove_principal(p.id)
                if n % 50 == 0:
                    roster.sync_tokens([TokenInfo(agent_idx=i, controller=p.id, faction=2)
                                        for i in range(8)])
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    writer = threading.Thread(target=seat, daemon=True)
    writer.start()
    dm = roster.get(DM_PRINCIPAL_ID)
    reads = 0
    try:
        while not done.is_set():
            for p in roster.players():
                roster.controlled_by(p.id)
            roster.to_dict()
            assert roster.authorize(dm, Action.VIEW_DM_CHANNEL)
            reads += 1
    except Exception as exc:
        errors.append(exc)
    writer.join(10)
    assert not errors, f"the roster tore under two threads: {errors[0]!r}"
    assert reads > 0
    print("✅ test_the_roster_survives_racing_threads")


def test_the_bus_hook_runs_outside_the_lock():
    """`authorize(ANSWER_PROMPT)` asks the prompt bus through `prompt_lookup`, which is a
    call out of the roster. It must not run under the lock, or a bus that ever touched a
    roster from another thread would deadlock. The hook here makes another thread take
    the lock and waits for it."""
    roster = SessionRoster()
    kira = roster.add_principal("Kira", role=Role.PLAYER)
    took = threading.Event()

    def lookup(_prompt_id):
        t = threading.Thread(target=lambda: (roster.players(), took.set()), daemon=True)
        t.start()
        t.join(2.0)
        return kira.id, True

    roster.prompt_lookup = lookup
    assert roster.authorize(kira, Action.ANSWER_PROMPT, PromptTarget("p1"))
    assert took.is_set(), "the bus hook ran with the roster lock held"
    print("✅ test_the_bus_hook_runs_outside_the_lock")


def test_a_cancelled_command_is_skipped():
    """A `GET /state` that timed out cancelled its future. Running its view anyway would
    spend a frame on an answer nobody reads, which is the cheapest way to load the frame
    tick from the network (F-M7-5)."""
    queue = CommandQueue(skip_abandoned=True)
    ran = []

    async def submit_two():
        stale = queue.submit(lambda app: ran.append("stale"))
        live = queue.submit(lambda app: ran.append("live") or "ok")
        stale.cancel()
        return live

    loop = asyncio.new_event_loop()
    try:
        live = loop.run_until_complete(submit_two())
        assert queue.pump(app=None) == 1, "the cancelled command counted as work"
        loop.run_until_complete(asyncio.sleep(0))
        assert live.result() == "ok"
    finally:
        loop.close()
    assert ran == ["live"], f"a cancelled command ran: {ran}"
    assert queue.skipped == 1 and queue.pending == 0
    # Only the read queue skips. A submit that timed out is still decided later, which is
    # what Step 0.5's `timeout` promises (test_submit.test_a_stalled_frame_loop_is_a_timeout).
    src = open(os.path.join(_ROOT, "gui", "main.py"), encoding="utf-8").read()
    assert "self._net_commands = CommandQueue(skip_abandoned=True)" in src
    assert "self._net_submits = CommandQueue()" in src, "the submit queue must not skip"
    print("✅ test_a_cancelled_command_is_skipped")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-3 — the limits, through the real server and a real socket
# ─────────────────────────────────────────────────────────────────────────────

from test_live import _auth_frame, _ws
from test_mapserver import _server


@contextlib.contextmanager
def _patched(**values):
    """Lower a limit for one check, and put it back."""
    original = {k: getattr(net_server, k) for k in values}
    for k, v in values.items():
        setattr(net_server, k, v)
    try:
        yield
    finally:
        for k, v in original.items():
            setattr(net_server, k, v)


def _closed_with(sock, timeout=5.0):
    """Read until the socket closes; return its close code."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        kind, data = sock.recv(timeout=max(0.1, deadline - time.monotonic()))
        if kind == "close":
            return data
    raise AssertionError("the socket did not close")


def _opened(port, credential):
    """A socket that has authenticated and received its first view."""
    sock = _ws(port)
    sock.connect()
    sock.send_text(_auth_frame(credential))
    first = sock.view(timeout=5.0)
    assert first["t"] == "view", first
    return sock


def test_a_bad_first_frame_spends_the_bucket():
    """A garbage first frame on `/live` is a guess at a credential. Before M7 it cost
    nothing; now it spends the same bucket a wrong join code does, and a spent address
    is refused on the socket and on `POST /join` alike."""
    with _server(pump=True) as s:
        lines = []
        s.srv.audit = lambda text, dm_only: lines.append((text, dm_only))
        for _ in range(net_server.JOIN_FAILURE_LIMIT):
            with _ws(s.srv.port) as sock:
                sock.send_text(_auth_frame("not-a-credential"))
                assert _closed_with(sock) == net_server.WS_CLOSE_UNAUTHENTICATED
        # Spent: even a GOOD credential is refused before its frame is read.
        with _ws(s.srv.port) as sock:
            sock.send_text(_auth_frame(s.player))
            assert _closed_with(sock) == net_server.WS_CLOSE_UNAUTHENTICATED
        status, _, _ = s.post("/join", {"v": 1, "t": "auth",
                                        "join_code": s.app.roster.join_code})
        assert status == 429, f"a join from a spent address returned {status}"
    refused = [t for t, dm in lines if t.startswith("Refused")]
    assert len(refused) == net_server.JOIN_FAILURE_LIMIT, lines
    assert any(t.startswith("Throttled 127.0.0.1") for t, _ in lines), lines
    assert all(dm for _, dm in lines), "an address reached a public log line"
    print("✅ test_a_bad_first_frame_spends_the_bucket")


def test_a_fifth_screen_evicts_the_oldest():
    """Four screens per seat. The fifth takes the oldest one's place, and the oldest is
    told why with 4408 rather than the auth failure's 4401."""
    with _server(pump=True) as s:
        socks = [_opened(s.srv.port, s.player)
                 for _ in range(net_server.LIVE_MAX_PER_PRINCIPAL)]
        try:
            newest = _opened(s.srv.port, s.player)
            try:
                assert _closed_with(socks[0]) == net_server.WS_CLOSE_REPLACED
                assert len(s.srv._live_conns.of(s.kira.id)) == net_server.LIVE_MAX_PER_PRINCIPAL
                # The DM's sockets are another principal's and are not counted against Kira.
                dm = _opened(s.srv.port, s.dm)
                dm.close()
            finally:
                newest.close()
        finally:
            for sock in socks:
                sock.close()
    print("✅ test_a_fifth_screen_evicts_the_oldest")


def test_the_socket_caps():
    """A full table, and a crowd of sockets that have proved nothing, are both "try later"
    (1013), answered before a frame is read."""
    with _patched(LIVE_MAX_SOCKETS=2):
        with _server(pump=True) as s:
            a, b = _opened(s.srv.port, s.player), _opened(s.srv.port, s.dm)
            try:
                with _ws(s.srv.port) as c:
                    c.send_text(_auth_frame(s.player))
                    assert _closed_with(c) == net_server.WS_CLOSE_TRY_LATER
            finally:
                a.close()
                b.close()
    with _patched(LIVE_MAX_PENDING=1):
        with _server(pump=True) as s:
            with _ws(s.srv.port) as silent:
                time.sleep(0.2)            # it is waiting on its first frame
                with _ws(s.srv.port) as late:
                    late.send_text(_auth_frame(s.player))
                    assert _closed_with(late) == net_server.WS_CLOSE_TRY_LATER
                silent.send_text(_auth_frame(s.player))
                assert silent.view()["t"] == "view", "the waiting socket was harmed"
    print("✅ test_the_socket_caps")


def test_a_frame_flood_closes_the_socket():
    """Frames past the bucket close the socket with 1008. The bucket is far above the
    client's rate: one auth frame, then one submit per answer."""
    with _server(pump=True) as s:
        sock = _opened(s.srv.port, s.player)
        try:
            for _ in range(net_server.LIVE_FRAME_BURST + 20):
                sock.send_text("{}")
            assert _closed_with(sock) == net_server.WS_CLOSE_POLICY
        finally:
            sock.close()
    print("✅ test_a_frame_flood_closes_the_socket")


def test_a_third_submit_is_refused():
    """Two submits in flight per socket. Nobody decides these (no submit pump), so the
    first two wait; the third is acked `protocol` at once and never reaches the queue."""
    with _server(pump=True) as s:
        s.srv._submits = CommandQueue()
        s.srv._handle_submit = lambda app, principal, frame: {"t": "submit_ack", "ok": True}
        sock = _opened(s.srv.port, s.player)
        try:
            for n in range(3):
                sock.send_text(json.dumps({"v": 1, "t": "submit", "id": f"p{n}",
                                           "option": "x"}))
            deadline = time.monotonic() + 3.0
            while True:
                assert time.monotonic() < deadline, "no ack for the third submit"
                kind, data = sock.recv(timeout=3.0)
                frame = json.loads(data) if kind == "text" else {}
                if frame.get("t") == "submit_ack":
                    break
            assert frame == {"v": 1, "t": "submit_ack", "id": "p2", "ok": False,
                             "error": "protocol"}, frame
            assert s.srv._submits.pending == 2, s.srv._submits.pending
        finally:
            sock.close()
    print("✅ test_a_third_submit_is_refused")


def test_frame_tick_reads_are_capped():
    """Four frame-tick reads waiting per principal. With no frame tick running, four park
    and the fifth is a 429 at once, without queueing anything. Another principal is not
    affected."""
    with _patched(STATE_TIMEOUT_S=2.0):
        with _server() as s:
            results = []
            threads = [threading.Thread(target=lambda: results.append(
                           s.get("/state", credential=s.player)[0]), daemon=True)
                       for _ in range(net_server.TICK_MAX_PER_PRINCIPAL)]
            for t in threads:
                t.start()
            deadline = time.monotonic() + 2.0
            while s.app._net_commands.pending < net_server.TICK_MAX_PER_PRINCIPAL:
                assert time.monotonic() < deadline, "the four reads never queued"
                time.sleep(0.01)
            status, _, body = s.get("/state", credential=s.player)
            assert status == 429 and body == b"busy", (status, body)
            assert s.app._net_commands.pending == net_server.TICK_MAX_PER_PRINCIPAL
            for path in ("/events?since=0", "/sprite?name=x.png"):
                assert s.get(path, credential=s.player)[0] == 429, path
            # The DM's own reads are counted separately.
            dm = []
            t = threading.Thread(target=lambda: dm.append(
                s.get("/state", credential=s.dm)[0]), daemon=True)
            t.start()
            for th in threads:
                th.join(5.0)
            t.join(5.0)
            assert results == [503] * net_server.TICK_MAX_PER_PRINCIPAL, results
            assert dm == [503], f"the DM was capped by Kira's reads: {dm}"
            # The count drains: the next read queues again rather than being refused.
            s.start_pump()
            assert s.get("/state", credential=s.player)[0] == 200
    print("✅ test_frame_tick_reads_are_capped")


def test_the_client_knows_the_new_close_codes():
    """The client stops reconnecting on 4408, and forgets its credential and shows the join
    card on 4403. Read from the file; `test_reclaim` is what runs the client."""
    js = open(os.path.join(_ROOT, "gui", "net", "static", "app.js"), encoding="utf-8").read()
    assert f"const WS_REPLACED = {net_server.WS_CLOSE_REPLACED};" in js
    assert f"const WS_REMOVED = {net_server.WS_CLOSE_REMOVED};" in js
    removed = js[js.index("event.code === WS_REMOVED"):]
    removed = removed[:removed.index("return;")]
    assert "forget(CRED_KEY)" in removed and "showJoin(" in removed
    replaced = js[js.index("event.code === WS_REPLACED"):]
    replaced = replaced[:replaced.index("return;")]
    assert "setTimeout" not in replaced, "a replaced screen reconnects and evicts in turn"
    print("✅ test_the_client_knows_the_new_close_codes")


if __name__ == "__main__":
    test_the_roster_survives_racing_threads()
    test_the_bus_hook_runs_outside_the_lock()
    test_a_cancelled_command_is_skipped()
    test_a_bad_first_frame_spends_the_bucket()
    test_a_fifth_screen_evicts_the_oldest()
    test_the_socket_caps()
    test_a_frame_flood_closes_the_socket()
    test_a_third_submit_is_refused()
    test_frame_tick_reads_are_capped()
    test_the_client_knows_the_new_close_codes()
    print("\n✅ All hardening tests passed!")
