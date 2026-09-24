#!/usr/bin/env python3
"""`WS /live` and the client it serves (MULTIPLAYER_PLAN.md M4e, D-M4e-1 through D-M4e-4).

`test_state.py` proves that a view built on the frame tick can cross a request. This proves
the other direction — the frame tick pushing to sockets nobody asked on behalf of — and the
three things that only exist once the transport can push:

  · **the socket authenticates itself.** A browser cannot put a header on a WebSocket
    handshake (A3), so `GET /live` is pre-auth in the middleware and validates its own first
    frame. Every way of getting that frame wrong has to end in a closed socket, because the
    alternative is a route that serves the whole session to anyone who can reach the port.
  · **the client is three files, not a directory.** `add_static` registers a *prefix*
    resource whose canonical is the prefix, so a single `PRE_AUTH_ROUTES` test against it
    would exempt everything under it (D-M4e-1). The checks here are what stops that being
    reintroduced as a convenience.
  · **the push costs a projection per connected socket.** Which means "nobody connected"
    has to cost nothing, "never two in flight" has to hold per connection, and a credential
    that stops verifying has to close a socket that is one request an hour long (A5).

Driven by a **hand-rolled WebSocket client** over a raw socket, for the reason
`test_mapserver.py` drives HTTP with stdlib `urllib`: `aiohttp`'s own client would be the
library talking to itself. What a browser does — the upgrade handshake, the mask bit on
every client frame, the close code — is what these read.

Rig, scene and transport are `test_mapserver.py`'s, with `push=True` so that `push_cycle`
runs on the stand-in frame tick.

  · the client's three files are served with no credential            (test_the_client_is_served_without_a_credential)
  · a fourth path is not, because the exemption is not a prefix       (test_only_the_three_named_files_are_served)
  · ...and no route on this server is a prefix in the first place      (test_no_route_is_a_prefix)
  · HEAD / is not GET / — the exemption is a pair, on the real table  (test_head_is_not_the_pair_that_was_exempted)
  · a socket that has said nothing is sent nothing                    (test_the_socket_sends_nothing_before_the_first_frame)
  · every way of getting the first frame wrong closes it              (test_a_bad_first_frame_closes_the_socket)
  · ...including never sending one                                    (test_no_first_frame_is_a_closed_socket)
  · a good first frame is answered with the whole view (F5)           (test_the_socket_opens_with_the_whole_view)
  · pushes keep arriving, built on the frame tick and not the net one (test_the_push_is_built_on_the_frame_tick)
  · one view per connected SOCKET, not per seated principal           (test_every_connected_socket_gets_its_own_view)
  · nobody connected costs no projection at all                       (test_nothing_connected_costs_no_projection)
  · a send outstanding is skipped, not queued behind                  (test_never_two_in_flight)
  · a revoked credential closes the socket on the next cycle (A5)     (test_a_revoked_credential_closes_the_socket)
  · the exemption does not skip the Origin check                      (test_a_cross_origin_socket_is_refused)
  · the client keeps its credential in sessionStorage (D-M4e-2)       (test_the_client_keeps_the_credential_in_session_storage)
  · the client has no input surface in M4e (D-M4e-3)                  (test_the_client_has_no_input_surface)
  · it fetches the page art with its credential, since an <img> cannot (test_the_client_fetches_the_map_with_its_credential)
  · ...and it parses, which nothing else in the suite would notice    (test_the_client_parses)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import asyncio
import base64
import contextlib
import json
import re
import secrets
import shutil
import socket as socketlib
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request

from net import server as net_server, view as net_view
from net.roster import DM_PRINCIPAL_ID, PROTOCOL_VERSION
from net.view import build_view

from test_mapserver import _server

_STATIC = os.path.join(_ROOT, "gui", "net", "static")


# ─────────────────────────────────────────────────────────────────────────────
#  A WebSocket client, because the browser's path is the one under test
# ─────────────────────────────────────────────────────────────────────────────

class _ws:
    """RFC 6455 client enough for this protocol: one text frame out, text frames in.

    Hand-rolled on purpose. `aiohttp` is in the tree and its client would be five lines —
    and would be `aiohttp` talking to `aiohttp`, which is exactly what `test_mapserver.py`
    declined for the HTTP routes. A browser masks every frame it sends, reads the close
    code, and never sees a `WSMessage`; so does this.

    `connect()` returns the handshake status, so a refused upgrade (403 from the `Origin`
    check) is a *result* here rather than an exception — the same shape `_server.get` uses.
    """

    def __init__(self, base_port: int, path: str = "/live", origin: str | None = None,
                 timeout: float = 5.0):
        self._port = base_port
        self._path = path
        self._origin = origin
        self._timeout = timeout
        self._sock = None
        self._buf = b""
        self.status = 0

    # ── Handshake ───────────────────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def connect(self) -> int:
        self._sock = socketlib.create_connection(("127.0.0.1", self._port), self._timeout)
        self._sock.settimeout(self._timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        lines = [f"GET {self._path} HTTP/1.1",
                 f"Host: 127.0.0.1:{self._port}",
                 "Upgrade: websocket",
                 "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}",
                 "Sec-WebSocket-Version: 13"]
        if self._origin is not None:
            lines.append(f"Origin: {self._origin}")
        self._sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

        head = self._read_until(b"\r\n\r\n")
        self.status = int(head.split(b" ", 2)[1])
        return self.status

    # ── Frames ──────────────────────────────────────────────────────────────

    def send_text(self, text: str) -> None:
        """A masked text frame, the way a browser always sends one."""
        payload = text.encode()
        header = bytes([0x81])
        if len(payload) < 126:
            header += bytes([0x80 | len(payload)])
        else:
            header += bytes([0x80 | 126]) + struct.pack("!H", len(payload))
        mask = secrets.token_bytes(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def recv(self, timeout: float | None = None):
        """`("text", str)` or `("close", code)`. A ping is answered and skipped.

        `socket.timeout` is left to propagate: a check that wants "nothing arrives" catches
        it deliberately, and every other check wants a timeout to be a failure.
        """
        if timeout is not None:
            self._sock.settimeout(timeout)
        while True:
            b0, b1 = self._read_exact(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            payload = self._read_exact(length) if length else b""
            if opcode == 0x9:                       # ping — pong it and keep reading
                self._sock.sendall(bytes([0x8A, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == 0x8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                return "close", code
            if opcode in (0x1, 0x0):
                return "text", payload.decode()
            if opcode == 0xA:                       # our own pong echoed back; ignore
                continue

    def view(self, timeout: float | None = None) -> dict:
        kind, data = self.recv(timeout)
        assert kind == "text", f"expected a view frame, got a {kind} ({data})"
        return json.loads(data)

    def close(self) -> None:
        if self._sock is None:
            return
        if self.status == 101:
            # Only on a socket that actually upgraded. A refused handshake (403) leaves an
            # ordinary HTTP connection, and a close FRAME sent down one is an invalid
            # request line — which aiohttp logs as a traceback that reads exactly like a
            # real failure in the middle of a green suite.
            try:
                self._sock.sendall(bytes([0x88, 0x80]) + secrets.token_bytes(4))
            except OSError:
                pass
        try:
            self._sock.close()
        finally:
            self._sock = None

    # ── Buffered reads ──────────────────────────────────────────────────────

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise AssertionError("the socket closed mid-frame")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_until(self, sep: bytes) -> bytes:
        while sep not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise AssertionError("the socket closed during the handshake")
            self._buf += chunk
        out, _, self._buf = self._buf.partition(sep)
        return out


def _auth_frame(credential: str) -> str:
    return json.dumps({"v": PROTOCOL_VERSION, "t": "auth", "credential": credential})


@contextlib.contextmanager
def _faster_cadence(interval_ms: int = 25):
    """Push at 40 Hz instead of 4, so a check measures the mechanism and not the clock.

    The frozen value is asserted here rather than trusted, for the reason
    `test_a_wedged_frame_loop_is_a_503` asserts `STATE_TIMEOUT_S`: a patch that also hid a
    changed freeze would make every one of these checks pass against the wrong protocol.
    """
    assert net_view.PUSH_INTERVAL_MS == 250, \
        f"D-M4-2 froze the push cadence at 250 ms; it is {net_view.PUSH_INTERVAL_MS}"
    original, net_view.PUSH_INTERVAL_MS = net_view.PUSH_INTERVAL_MS, interval_ms
    try:
        yield
    finally:
        net_view.PUSH_INTERVAL_MS = original


# ─────────────────────────────────────────────────────────────────────────────
#  The client's files (D-M4e-1)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_client_is_served_without_a_credential():
    """A player types the URL before they have anything to authenticate with, so these
    three are the only routes on this server that answer an anonymous caller with a body."""
    with _server() as s:
        for path, content_type in (("/", "text/html"),
                                   ("/app.js", "application/javascript"),
                                   ("/app.css", "text/css")):
            status, headers, body = s.get(path)
            assert status == 200, f"anonymous {path} returned {status}"
            assert content_type in headers.get("Content-Type", ""), \
                f"{path} was served as {headers.get('Content-Type')!r}"
            assert headers.get("Cache-Control") == "no-store", \
                f"{path} was cacheable — a player can end up running a stale client"
            assert body, f"{path} was empty"

        page = s.get("/")[2].decode()
        assert "/app.js" in page and "/app.css" in page, \
            "the page does not reference the two files the route table exists for"
        print("✅ test_the_client_is_served_without_a_credential")


def test_only_the_three_named_files_are_served():
    """D-M4e-1's whole point: three exact pairs, and no subtree.

    Every path here would be served by an `add_static` mount and is not served by three
    routes — and, because an unmatched path is never exempt, each one is a 401 rather than a
    404, which is the pre-existing behaviour `_is_pre_auth` documents.
    """
    with _server() as s:
        for path in ("/index.html", "/static/app.js", "/app.js/", "/./app.js",
                     "/static/../app.js"):
            status, _headers, body = s.get(path)
            assert status in (401, 404), f"{path} answered {status} to an anonymous caller"
            assert b"sessionStorage" not in body, f"{path} served the client's source"

        # `/live` over plain HTTP is a protocol error, not a view: the exemption lets the
        # request past the 401 and the handler refuses it for not being an upgrade.
        assert s.get("/live")[0] == 400, "GET /live without an upgrade was not a 400"
        print("✅ test_only_the_three_named_files_are_served")


def test_no_route_is_a_prefix():
    """D-M4e-1 as a property of the router, and not of any one response.

    Every other check here asks what a path answers — and an `add_static` mount answers 401
    for exactly as long as nobody puts its prefix in `PRE_AUTH_ROUTES`, so the *harmless*
    half of that mutant survives all of them while leaving the dangerous half one line away.
    The rule is simpler than its symptoms: **this server registers no prefix resource at
    all**, so there is no `canonical` for a pair test to match that is not a whole path.

    The canonical list is pinned as well, because the route table is the security surface: a
    route added without a line here is a route nobody decided to expose.
    """
    with _server() as s:
        # A second, never-started Application off the same builder: the router is what is
        # under test and standing one up costs nothing.
        router = s.srv._build().router
        kinds = {type(r).__name__ for r in router.resources()}
        assert kinds == {"PlainResource"}, \
            f"the router holds {sorted(kinds)} — a prefix resource is a whole subtree"
        assert sorted(r.canonical for r in router.resources()) == [
            "/", "/app.css", "/app.js", "/join", "/live", "/map.png", "/state"], \
            f"the route table changed: {sorted(r.canonical for r in router.resources())}"
        print("✅ test_no_route_is_a_prefix")


def test_head_is_not_the_pair_that_was_exempted():
    """The exemption is a `(method, path)` pair, observable on the real route table.

    `test_join.py` had to stand up a subclass to show this, because for a method with no
    route the router answers before the pair is ever compared. `add_get` changes that: it
    registers HEAD on the **same resource**, whose canonical is the same path — so `HEAD /`
    is a second method on an exempt path, and a mutant collapsing the pair to a path alone
    serves it. The 401 is deliberate and the direction is the safe one; nothing in the
    client issues a HEAD.
    """
    with _server() as s:
        assert s.get("/")[0] == 200
        req = urllib.request.Request(f"{s.base}/", method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 401, \
            f"HEAD / answered {status} — the exemption collapsed to a path alone"
        print("✅ test_head_is_not_the_pair_that_was_exempted")


# ─────────────────────────────────────────────────────────────────────────────
#  First-frame authentication (A3)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_socket_sends_nothing_before_the_first_frame():
    """The exemption suppresses the 401 and nothing else.

    A socket that has proved nothing is prepared and is not a viewer: it is not in the
    connection table, no view is built for it, and nothing is sent to it. The check is that
    *silence* is met with silence, which is the one property a handler that authenticated
    after its first push would still fail.
    """
    with _server(pump=True, push=True) as s, _faster_cadence():
        with _ws(s.srv.port) as sock:
            assert sock.status == 101, f"the upgrade was refused with {sock.status}"
            time.sleep(0.3)                      # a dozen push cycles at this cadence
            try:
                kind, data = sock.recv(timeout=0.4)
            except (socketlib.timeout, TimeoutError):
                kind, data = "nothing", ""
            assert kind == "nothing", \
                f"an unauthenticated socket was sent a {kind} ({str(data)[:80]})"
            assert s.srv._live_conns.connected == 0, \
                "an unauthenticated socket was registered as a viewer"
        print("✅ test_the_socket_sends_nothing_before_the_first_frame")


def test_a_bad_first_frame_closes_the_socket():
    """Four ways to get it wrong, one answer, and the count going up each time (A9)."""
    with _server(pump=True) as s:
        forged = s.player[:-4] + "aaaa"
        revoked = s.app.roster.mint_credential(s.kira.id)
        s.app.roster.revoke_credential(revoked)
        frames = {
            "a forged credential":   _auth_frame(forged),
            "a revoked credential":  _auth_frame(revoked),
            "the wrong envelope":    json.dumps({"v": PROTOCOL_VERSION, "t": "view",
                                                 "credential": s.player}),
            "not JSON at all":       "hello",
        }
        for label, frame in frames.items():
            before = s.srv.denials
            with _ws(s.srv.port) as sock:
                sock.send_text(frame)
                kind, code = sock.recv(timeout=5.0)
                assert kind == "close", f"{label}: the socket was sent a {kind}"
                assert code == net_server.WS_CLOSE_UNAUTHENTICATED, \
                    f"{label}: closed with {code}"
            assert s.srv.denials > before, f"{label}: A9's counter did not move"
        print("✅ test_a_bad_first_frame_closes_the_socket")


def test_no_first_frame_is_a_closed_socket():
    """A connected socket that never speaks is a file descriptor A3 puts a clock on."""
    assert net_server.LIVE_AUTH_TIMEOUT_S == 5.0, \
        f"A3's window is ~5 s; it is {net_server.LIVE_AUTH_TIMEOUT_S}"
    with _server() as s:
        original, net_server.LIVE_AUTH_TIMEOUT_S = net_server.LIVE_AUTH_TIMEOUT_S, 0.4
        try:
            with _ws(s.srv.port) as sock:
                began = time.monotonic()
                kind, code = sock.recv(timeout=5.0)
                elapsed = time.monotonic() - began
        finally:
            net_server.LIVE_AUTH_TIMEOUT_S = original
        assert kind == "close", f"a silent socket was sent a {kind}"
        assert code == net_server.WS_CLOSE_UNAUTHENTICATED
        assert elapsed < 3.0, f"the window is not bounded ({elapsed:.1f}s)"
        print("✅ test_no_first_frame_is_a_closed_socket")


# ─────────────────────────────────────────────────────────────────────────────
#  The push (D-M4e-4, F5)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_socket_opens_with_the_whole_view():
    """F5's free late-joiner resync: the current view on `prepare`, not at the next cycle.

    Compared against `build_view`'s own output rather than a hand-written shape, for M3's
    reason — a push that re-assembled the dict would be a second, untested projection in
    front of the tested one. And the byte-level guarantee is re-checked through the socket,
    because a push is a second way for the creature in the fog to leave the process.
    """
    with _server(pump=True) as s:
        with _ws(s.srv.port) as sock:
            sock.send_text(_auth_frame(s.player))
            raw = sock.recv(timeout=5.0)
        assert raw[0] == "text", f"the socket answered a good credential with {raw[0]}"
        pushed, direct = json.loads(raw[1]), build_view(s.app, s.kira)
        assert pushed["v"] == PROTOCOL_VERSION and pushed["t"] == "view"
        assert pushed["seq"] == 0, "seq is 0 until EventStream (S3) exists"
        for block in ("you", "fog", "combat", "agents", "terrain", "lighting",
                      "effects", "log"):
            assert pushed[block] == direct[block], f"the push altered the {block} block"
        assert "Skarn" not in raw[1], \
            "an unexplored enemy crossed the socket — the push is not sending the projection"
        print("✅ test_the_socket_opens_with_the_whole_view")


def test_the_push_is_built_on_the_frame_tick():
    """NN1's witness for the push path, and the cadence behind it.

    `build_view` reads `app.bm`. A push built on the net loop would look identical on the
    wire and violate NN1 four times a second, so the assertion is about a thread identity
    rather than a payload — the same shape `test_state.py` uses for the request path.
    """
    with _server(pump=True, push=True) as s, _faster_cadence():
        seen = {}
        original = net_view.build_view

        def spy(app, viewer, seq=0):
            seen["builder"] = threading.get_ident()
            return original(app, viewer, seq)

        net_view.build_view = spy
        try:
            with _ws(s.srv.port) as sock:
                sock.send_text(_auth_frame(s.player))
                first = sock.view(timeout=5.0)        # the resync, through the queue
                second = sock.view(timeout=5.0)       # a push, through push_cycle
        finally:
            net_view.build_view = original

        assert first["t"] == "view" and second["t"] == "view"
        assert "builder" in seen, "no push was ever built — push_cycle never ran"
        assert seen["builder"] == s._ticker.ident, \
            "the push was not built on the thread that runs the frame tick — NN1"
        assert seen["builder"] != threading.get_ident(), \
            "the push was built on the requesting thread, which proves nothing"
        print("✅ test_the_push_is_built_on_the_frame_tick")


def test_every_connected_socket_gets_its_own_view():
    """One view per connected **socket**, and each one filtered for its own holder.

    D-M4c-1 rejected per-principal fan-out for `GET /state` because it builds views nobody
    is listening to; a socket is the case where that objection turns around. Two sockets is
    also the shape that catches a registry keyed by principal, which would drop one of two
    tabs and would look like a flaky client.
    """
    with _server(pump=True, push=True) as s, _faster_cadence():
        with _ws(s.srv.port) as player, _ws(s.srv.port) as dm, _ws(s.srv.port) as twin:
            player.send_text(_auth_frame(s.player))
            dm.send_text(_auth_frame(s.dm))
            twin.send_text(_auth_frame(s.player))      # the same player, a second tab
            first = {"player": player.view(timeout=5.0),
                     "dm": dm.view(timeout=5.0),
                     "twin": twin.view(timeout=5.0)}
            assert s.srv._live_conns.connected == 3, \
                f"{s.srv._live_conns.connected} sockets registered, not 3"

            names = {k: {a["name"] for a in v["agents"]} for k, v in first.items()}
            assert "Skarn" not in names["player"] and "Skarn" in names["dm"], \
                "the socket served the wrong projection for its holder"
            assert names["twin"] == names["player"], \
                "two sockets for one principal disagreed about what it may see"

            # And the push itself reaches all three, not only the one that connected last.
            for label, sock in (("player", player), ("dm", dm), ("twin", twin)):
                assert sock.view(timeout=5.0)["t"] == "view", f"{label} got no push"
        print("✅ test_every_connected_socket_gets_its_own_view")


def test_nothing_connected_costs_no_projection():
    """The other half of "a socket is a listener": with nobody listening, no view is built.

    A push loop written over `roster.players()` instead of over the published snapshot would
    pass every other check in this file and pay for N projections four times a second at an
    empty table.
    """
    from net import link as net_link

    with _server() as s, _faster_cadence():
        s.app._net = s.srv
        built = []
        original = net_view.build_view
        net_view.build_view = lambda app, viewer, seq=0: built.append(viewer) or {}
        try:
            for _ in range(5):
                s.app._net_turn = None            # force the boundary, skip the cadence
                net_link.push_cycle(s.app)
        finally:
            net_view.build_view = original
        assert built == [], f"{len(built)} views were built for nobody"
        assert s.srv.live_viewers() == (), "the snapshot named a viewer that never connected"
        print("✅ test_nothing_connected_costs_no_projection")


def test_never_two_in_flight():
    """D-M4e-4's per-connection rule, at the level it is actually enforced.

    The guarantee cannot live in the snapshot: a snapshot read and a schedule are two
    operations with a whole cycle between them. So it lives in `_send`, on the loop that
    owns the flag — and the snapshot's exclusion of an in-flight connection is the economy
    that keeps the frame tick from building a view that is about to be dropped.

    A blocked send is what a phone on bad wifi looks like from here.

    **The second send is bounded on purpose.** With the guard gone it does not return a
    wrong answer — it blocks on the same gate the first one is holding, and an unbounded
    `await` would hang the suite for the full container timeout instead of failing it. That
    is the lesson D-M4d-4's mutant pass paid ten minutes for, arriving in a second place.
    """
    class _blocked_ws:
        def __init__(self):
            self.sent = []
            self.gate = asyncio.Event()

        async def send_json(self, data):
            self.sent.append(data)
            await self.gate.wait()

    async def drive(srv, principal, credential):
        ws = _blocked_ws()
        conn = srv._live_conns.add(ws, principal, credential)
        assert len(srv._live_conns.snapshot) == 1, "a new socket was not published"

        first = asyncio.ensure_future(srv._send(conn, {"t": "view", "n": 1}))
        await asyncio.sleep(0)
        assert conn.in_flight, "a send in progress was not marked in flight"
        assert srv._live_conns.snapshot == (), \
            "an in-flight connection stayed in the snapshot — the frame tick will build for it"

        try:
            await asyncio.wait_for(srv._send(conn, {"t": "view", "n": 2}), 0.5)
        except asyncio.TimeoutError:
            raise AssertionError(
                "a second send started while one was in flight — the guard is gone") from None
        assert [m["n"] for m in ws.sent] == [1], \
            "a second view was queued behind the first instead of dropped"

        ws.gate.set()
        await first
        assert not conn.in_flight
        assert len(srv._live_conns.snapshot) == 1, "the connection never came back"
        srv._live_conns.remove(conn)

    with _server() as s:
        # Run on a loop of this thread's own: `_send` and the registry touch nothing the
        # server's loop owns, and driving them directly is what makes the ordering visible.
        asyncio.run(drive(s.srv, s.kira, s.player))
        print("✅ test_never_two_in_flight")


def test_a_revoked_credential_closes_the_socket():
    """A5 on a connection that is one request an hour long.

    The revocation check runs on every request, and a socket is not a stream of them — so
    without a re-check on the push cycle, revoking a credential or unseating a player would
    be a kick that takes effect whenever the player next chooses to reconnect. The socket
    has to go, and nothing may be pushed to it after it does.
    """
    with _server(pump=True, push=True) as s, _faster_cadence():
        with _ws(s.srv.port) as sock:
            sock.send_text(_auth_frame(s.player))
            assert sock.view(timeout=5.0)["t"] == "view"

            s.app.roster.revoke_credential(s.player)
            deadline = time.monotonic() + 5.0
            closed = None
            while time.monotonic() < deadline:
                kind, data = sock.recv(timeout=5.0)
                if kind == "close":
                    closed = data
                    break
                assert json.loads(data) if isinstance(data, str) else True
            assert closed == net_server.WS_CLOSE_UNAUTHENTICATED, \
                f"a revoked credential kept its socket (closed with {closed})"
        print("✅ test_a_revoked_credential_closes_the_socket")


def test_a_cross_origin_socket_is_refused():
    """The pre-auth exemption suppresses the 401 and not the `Origin` check (D-M4c-3).

    This is the route where that check is load-bearing rather than defense in depth: a
    browser applies same-origin to `fetch` by itself and does **not** apply it to a
    WebSocket, so a malicious page in a player's browser can open this socket. It cannot
    forge a credential — but it must not get as far as the handshake either.
    """
    with _server() as s:
        sock = _ws(s.srv.port, origin="http://evil.example")
        try:
            assert sock.connect() == 403, \
                f"a cross-origin upgrade was answered with {sock.status}"
        finally:
            sock.close()

        ok = _ws(s.srv.port, origin=f"http://127.0.0.1:{s.srv.port}")
        try:
            assert ok.connect() == 101, f"a same-origin upgrade was refused ({ok.status})"
        finally:
            ok.close()
        print("✅ test_a_cross_origin_socket_is_refused")


# ─────────────────────────────────────────────────────────────────────────────
#  The client's two frozen decisions, read off the client (D-M4e-2 / D-M4e-3)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_client_keeps_the_credential_in_session_storage():
    """D-M4e-2, checked where it is decided: in the file the browser runs.

    A reload keeps the seat and closing the tab drops it, which matches the credential's own
    lifetime — the signing key is minted in memory at process start (A5). `localStorage`
    would store a longer-lived secret that is usually already dead, so the check is for
    *access*, not for the word: a comment naming the rejected option is exactly what this
    file should contain.
    """
    js = open(os.path.join(_STATIC, "app.js"), encoding="utf-8").read()
    assert "sessionStorage" in js, "the client stores its credential somewhere else"
    assert not re.search(r"localStorage\s*[.\[]", js), \
        "the client reaches for localStorage — D-M4e-2 rejected it"
    assert "document.cookie" not in js, "A3: the credential is never a cookie"
    print("✅ test_the_client_keeps_the_credential_in_session_storage")


def test_the_client_has_no_input_surface():
    """D-M4e-3: M4e's client is read-only, and the socket carries one frame outbound.

    The frame is the auth frame. A second `send` would be a game action arriving before the
    gate that authorizes it, and the whole of M5 is that gate — so the count is the cheapest
    true statement about this phase's scope, and it fails the moment someone wires a button.
    """
    js = open(os.path.join(_STATIC, "app.js"), encoding="utf-8").read()
    sends = re.findall(r"\.send\s*\(", js)
    assert len(sends) == 1, f"the client sends {len(sends)} kinds of frame, not 1"
    posts = re.findall(r'method:\s*"(\w+)"', js)
    assert posts == ["POST"], f"the client issues {posts} — M4e joins and reads, nothing else"
    assert '"/join"' in js, "the one POST is not the join"
    print("✅ test_the_client_has_no_input_surface")


def test_the_client_fetches_the_map_with_its_credential():
    """The bug the first manual pass found, and the reason it could hide.

    `GET /map.png` is authenticated like every other route — a bearer, never a cookie (A3)
    — and a browser cannot put a header on an image request, exactly as it cannot on the
    socket handshake. The client assigned the URL straight to an `Image`, so the request
    went out unauthenticated, came back 401, fired no `onload`, and left the canvas with
    nothing over its MASK fill: a uniformly dark board on every phone, fog or no fog, for
    the life of M4e.

    Nothing could catch it. `test_mapserver.py` drives the route with `Authorization` set,
    which is what a *test* does and not what an `<img>` does; and nothing in the suite
    renders this file. So the check is static and names the shape directly: the image goes
    through `fetch` with the credential, and no bare assignment of the server's URL to an
    image source is left anywhere in the file.

    The 401 itself is correct and is asserted where it belongs
    (`test_mapserver.test_unauthenticated_is_401`). This is about the caller.
    """
    js = open(os.path.join(_STATIC, "app.js"), encoding="utf-8").read()
    assert re.search(r"fetch\(\s*url\s*,\s*\{\s*headers:\s*\{\s*Authorization",  js), \
        "the page art is not fetched with the credential"
    assert not re.search(r"img\.src\s*=\s*(url|map\.image)\b", js), \
        "the client assigns the server's URL to an image source — that request carries no header"
    assert "createObjectURL" in js and "revokeObjectURL" in js, \
        "the fetched blob is not turned into an image, or not released again"
    print("✅ test_the_client_fetches_the_map_with_its_credential")


def test_the_client_parses():
    """`node --check` on `app.js`, because nothing else in the suite executes it.

    The two checks above read the file for decisions; neither would notice a missing brace,
    and a client that does not parse is a blank page with a console message no DM will see.
    The image carries node (noVNC's), so this is free — and it is *skipped rather than
    failed* if it ever stops carrying it, because a syntax check is not worth making the
    suite depend on a tool the plan never asked for.
    """
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_client_parses SKIPPED — no node in this image")
        return
    done = subprocess.run([node, "--check", os.path.join(_STATIC, "app.js")],
                          capture_output=True, text=True)
    assert done.returncode == 0, f"app.js does not parse:\n{done.stderr.strip()[:400]}"
    print("✅ test_the_client_parses")


if __name__ == "__main__":
    test_the_client_is_served_without_a_credential()
    test_only_the_three_named_files_are_served()
    test_no_route_is_a_prefix()
    test_head_is_not_the_pair_that_was_exempted()
    test_the_socket_sends_nothing_before_the_first_frame()
    test_a_bad_first_frame_closes_the_socket()
    test_no_first_frame_is_a_closed_socket()
    test_the_socket_opens_with_the_whole_view()
    test_the_push_is_built_on_the_frame_tick()
    test_every_connected_socket_gets_its_own_view()
    test_nothing_connected_costs_no_projection()
    test_never_two_in_flight()
    test_a_revoked_credential_closes_the_socket()
    test_a_cross_origin_socket_is_refused()
    test_the_client_keeps_the_credential_in_session_storage()
    test_the_client_has_no_input_surface()
    test_the_client_fetches_the_map_with_its_credential()
    test_the_client_parses()
    print("\n✅ All live-socket tests passed!")
