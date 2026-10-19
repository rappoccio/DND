#!/usr/bin/env python3
"""Event delivery: `events` frames, the sent cursor and `GET /events?since=` (M4b.2, B-3).

`test_events.py` pins the stream, the projection and the filter with no socket. This pins
what carries them, in three parts:

  · **the frame-tick half** (`net.link.push_cycle`), against a stand-in transport that
    publishes exactly what `PlayerServer` publishes: a snapshot of viewers with their
    `sent_seq`, and the set of every connection id. No socket, so each cursor rule is
    checked one cycle at a time;
  · **the net-loop half** (`PlayerServer._send` and `_contiguous`), on a server that is
    built and never started, driven on a loop of this thread's own, as
    `test_live.test_never_two_in_flight` drives it;
  · **one pass over a real socket and the real route**, so the two halves are shown to
    meet.

The B-10 mutant this slice owns, and the checks that kill it:
  · a gap after a dropped send       test_a_dropped_send_is_resent_whole,
                                     test_sent_seq_moves_only_after_a_good_send
And this slice's own:
  · `view.seq` not the principal's   test_events_ride_before_the_view_and_end_at_its_seq
  · only connected principals kept   test_every_seated_principal_is_projected
  · a stream outliving its seat      test_a_seat_that_goes_away_forgets_its_stream
  · a socket mid-send detached       test_an_in_flight_socket_keeps_its_cursor
  · no `turn`, or one at startup     test_the_turn_boundary_is_an_event
  · a resent prefix not cut          test_contiguous_frames
  · a gap let through to a client    test_contiguous_frames
  · `since` outside the ring patched test_events_since_answers_or_resyncs
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import asyncio
import json

from net import events as ev, link as net_link, view as net_view
from net.roster import DM_PRINCIPAL_ID, PROTOCOL_VERSION
from net.server import LiveViewer, PlayerServer, _contiguous
from net.view import sight

import test_gameview as gv


# ─────────────────────────────────────────────────────────────────────────────
#  A stand-in transport for the frame-tick half
# ─────────────────────────────────────────────────────────────────────────────

class _FakeNet:
    """What `push_cycle` reads from and hands to `PlayerServer`, and nothing else.

    `live_viewers()` leaves out a connection mid-send, and `live_ids()` does not: the
    same two publications `_LiveConnections.republish` makes.
    """

    def __init__(self):
        self._viewers: dict[str, LiveViewer] = {}
        self._in_flight: set[str] = set()
        self.last: dict = {}
        self.dropped: list[str] = []

    # what the server publishes
    def live_viewers(self):
        return tuple(v for cid, v in self._viewers.items() if cid not in self._in_flight)

    def live_ids(self):
        return frozenset(self._viewers)

    def push_views(self, views):
        self.last = views

    def drop_viewer(self, conn_id, code=None):
        self.dropped.append(conn_id)

    # what a test does to it
    def connect(self, cid, principal, credential):
        self._viewers[cid] = LiveViewer(cid, principal, credential, None)

    def sent(self, cid, seq):
        """The net loop finished a send to `cid` that left it at `seq`."""
        v = self._viewers[cid]
        self._viewers[cid] = LiveViewer(v.id, v.principal, v.credential, seq)

    def in_flight(self, cid, on=True):
        (self._in_flight.add if on else self._in_flight.discard)(cid)

    def gone(self, cid):
        self._viewers.pop(cid, None)
        self._in_flight.discard(cid)


def _wire(app):
    app._net = _FakeNet()
    return app._net


def _cycle(app) -> dict:
    """One push cycle, past the cadence. Returns `{socket id: frames}` as pushed."""
    app._net.last = {}
    app._net_push_ms = -10 ** 9
    net_link.push_cycle(app)
    return app._net.last


def _kinds(frames):
    return [f["t"] for f in frames]


def _flash(app, name, text="Hit (7)"):
    app.events.append(ev.outcome(gv._idx(app, name), text, good=True))


def _seqs(frame):
    return [e["seq"] for e in frame["events"]]


# ─────────────────────────────────────────────────────────────────────────────
#  The frame-tick half
# ─────────────────────────────────────────────────────────────────────────────

def test_a_new_socket_starts_from_a_view():
    """A socket's first cycle is a `view` at the principal's seq, with no `events`: the
    view already shows everything before it."""
    def check(app, kira, _spectator):
        net = _wire(app)
        _cycle(app)                                   # opens every seated projection
        _flash(app, "Gnasher")
        net.connect("s1", kira, app.roster.mint_credential(kira.id))
        frames = _cycle(app)["s1"]
        assert _kinds(frames) == ["view"], _kinds(frames)
        assert frames[0]["seq"] == 1, "the view's seq is not the principal's seq"
        assert app.events.projection(kira.id).sent("s1") == 1

        # The usual order: the connect-time view lands before the first cycle sees the
        # socket. It starts from that view's seq, so what happened since still plays.
        net.connect("s2", kira, app.roster.mint_credential(kira.id))
        net.sent("s2", 1)
        _flash(app, "Gnasher", "Miss")
        frames = _cycle(app)["s2"]
        assert _kinds(frames) == ["events", "view"] and frames[0]["since"] == 1, \
            "a socket that already holds a view skipped the events after it"
        assert _seqs(frames[0]) == [2]
    gv._run(check)
    print("✅ test_a_new_socket_starts_from_a_view")


def test_events_ride_before_the_view_and_end_at_its_seq():
    def check(app, kira, _spectator):
        net = _wire(app)
        _cycle(app)
        net.connect("s1", kira, app.roster.mint_credential(kira.id))
        _cycle(app)
        net.sent("s1", 0)
        _flash(app, "Gnasher")
        _flash(app, "Skarn")                          # in the fog: dropped for Kira
        _flash(app, "Aria", "Hit (3)")
        frames = _cycle(app)["s1"]
        assert _kinds(frames) == ["events", "view"], _kinds(frames)
        events, view = frames
        assert events["v"] == PROTOCOL_VERSION and events["since"] == 0
        assert _seqs(events) == [1, 2], "Kira's seq is gapless around the hidden flash"
        assert events["seq"] == view["seq"] == 2, "the view does not end where the events do"
        assert "Skarn" not in json.dumps(frames)
    gv._run(check)
    print("✅ test_events_ride_before_the_view_and_end_at_its_seq")


def test_a_dropped_send_is_resent_whole():
    """B-10: a gap after a dropped send. Nothing published a `sent_seq`, so the next cycle
    starts from the same cursor, and the events of both cycles go out together."""
    def check(app, kira, _spectator):
        net = _wire(app)
        _cycle(app)
        net.connect("s1", kira, app.roster.mint_credential(kira.id))
        _cycle(app)
        net.sent("s1", 0)
        _flash(app, "Gnasher")
        assert _seqs(_cycle(app)["s1"][0]) == [1]
        # That send never landed: the net loop published nothing.
        _flash(app, "Gnasher", "Miss")
        again = _cycle(app)["s1"]
        assert again[0]["since"] == 0 and _seqs(again[0]) == [1, 2], \
            "a dropped send left a gap"
        net.sent("s1", 2)
        assert _kinds(_cycle(app)["s1"]) == ["view"], "an acked event was sent again"
    gv._run(check)
    print("✅ test_a_dropped_send_is_resent_whole")


def test_an_in_flight_socket_keeps_its_cursor():
    """A socket mid-send is missing from `live_viewers()` but is still connected. Its
    cursor stays, so the cycle after the send carries what happened during it."""
    def check(app, kira, _spectator):
        net = _wire(app)
        _cycle(app)
        net.connect("s1", kira, app.roster.mint_credential(kira.id))
        _cycle(app)
        net.sent("s1", 0)
        net.in_flight("s1")
        _flash(app, "Gnasher")
        assert "s1" not in _cycle(app), "a view was built for a socket mid-send"
        assert app.events.projection(kira.id).sent("s1") == 0, \
            "a socket mid-send lost its cursor"
        net.in_flight("s1", False)
        frames = _cycle(app)["s1"]
        assert _kinds(frames) == ["events", "view"] and _seqs(frames[0]) == [1]

        net.gone("s1")
        _cycle(app)
        assert app.events.projection(kira.id).sent("s1") is None, \
            "a closed socket kept its cursor"
    gv._run(check)
    print("✅ test_an_in_flight_socket_keeps_its_cursor")


def test_every_seated_principal_is_projected():
    """The user's decision: a seated player with no socket keeps a moving `seq`, so a
    reconnect within the ring resumes from it (M6). And the global list still drains."""
    def check(app, kira, spectator):
        net = _wire(app)
        _cycle(app)
        assert net.live_viewers() == ()
        _flash(app, "Gnasher")
        _flash(app, "Aria")
        _cycle(app)
        for who in (kira, spectator, app.roster.get(DM_PRINCIPAL_ID)):
            assert app.events.projection(who.id).seq == 2, \
                f"{who.display_name}'s stream stood still with nobody connected"
        assert len(app.events) == 0, "the global list held events every stream had filtered"
        frame = net_link.events_since(app, kira, 0)
        assert frame["t"] == "events" and _seqs(frame) == [1, 2]
    gv._run(check)
    print("✅ test_every_seated_principal_is_projected")


def test_a_seat_that_goes_away_forgets_its_stream():
    def check(app, kira, spectator):
        _wire(app)
        _cycle(app)
        assert spectator.id in app.events._views
        app.roster.remove_principal(spectator.id)
        _cycle(app)
        assert spectator.id not in app.events._views, "an unseated principal kept a stream"
        assert kira.id in app.events._views
    gv._run(check)
    print("✅ test_a_seat_that_goes_away_forgets_its_stream")


def test_the_turn_boundary_is_an_event():
    """`turn` at the boundary `push_cycle` already detects; not on the first cycle, whose
    boundary is only the server starting; and not on a cycle that crosses none."""
    def check(app, kira, _spectator):
        _wire(app)
        _cycle(app)                                   # opens the streams first, so a
        app._net_turn = None                          # startup `turn` would be seen
        _cycle(app)
        dm = DM_PRINCIPAL_ID
        assert app.events.projection(dm).seq == 0, "the server starting was sent as a turn"

        app._start_combat()
        _cycle(app)
        got = net_link.events_since(app, app.roster.get(dm), 0)["events"]
        turns = [e for e in got if e["kind"] == "turn"]
        assert len(turns) == 1, got
        idx = app.initiative_order[app.turn_idx].agent_idx
        assert turns[0] == {"seq": turns[0]["seq"], "kind": "turn", "round": app.round_num,
                            "turn_idx": app.turn_idx, "agent": idx}, turns[0]

        mine = net_link.events_since(app, kira, 0)["events"]
        assert [e for e in mine if e["kind"] == "turn"][0]["agent"] == \
            (idx if idx in sight(app, kira).shown else None)

        before = app.events.projection(dm).seq
        _cycle(app)
        assert app.events.projection(dm).seq == before, "a turn with no boundary"
    gv._run(check)
    print("✅ test_the_turn_boundary_is_an_event")


def test_a_cursor_past_the_ring_resyncs():
    """A socket that fell more than 512 events behind gets no `events` frame: it is
    re-attached at the head, and the `view` in the same cycle is the resync."""
    def check(app, kira, _spectator):
        net = _wire(app)
        _cycle(app)
        net.connect("s1", kira, app.roster.mint_credential(kira.id))
        _cycle(app)
        net.sent("s1", 0)
        for _ in range(ev.RING_SIZE + 5):
            _flash(app, "Gnasher")
        frames = _cycle(app)["s1"]
        p = app.events.projection(kira.id)
        assert _kinds(frames) == ["view"] and frames[0]["seq"] == p.seq == ev.RING_SIZE + 5
        assert p.sent("s1") == p.seq
    gv._run(check)
    print("✅ test_a_cursor_past_the_ring_resyncs")


def test_events_since_answers_or_resyncs():
    """`GET /events?since=`'s answer, and `GET /state`'s `seq`."""
    def check(app, kira, _spectator):
        _wire(app)
        _cycle(app)
        _flash(app, "Gnasher")
        _flash(app, "Gnasher", "Miss")
        assert _seqs(net_link.events_since(app, kira, 0)) == [1, 2]
        assert _seqs(net_link.events_since(app, kira, 1)) == [2]
        empty = net_link.events_since(app, kira, 2)
        assert empty["t"] == "events" and empty["events"] == [] and empty["seq"] == 2
        for bad in (-1, 3, 10 ** 9):
            out = net_link.events_since(app, kira, bad)
            assert out["t"] == "view" and out["seq"] == 2, f"since={bad} was not a resync"
        for _ in range(ev.RING_SIZE):
            _flash(app, "Gnasher")
        old = net_link.events_since(app, kira, 1)
        assert old["t"] == "view", "a since older than the ring was answered from it"
        assert net_link.view_at_seq(app, kira)["seq"] == ev.RING_SIZE + 2
    gv._run(check)
    print("✅ test_events_since_answers_or_resyncs")


# ─────────────────────────────────────────────────────────────────────────────
#  The net-loop half
# ─────────────────────────────────────────────────────────────────────────────

def _events_frame(since, seqs):
    return {"v": PROTOCOL_VERSION, "t": "events", "since": since,
            "seq": seqs[-1] if seqs else since,
            "events": [{"seq": n, "kind": "turn"} for n in seqs]}


def _view(seq):
    return {"v": PROTOCOL_VERSION, "t": "view", "seq": seq}


def test_contiguous_frames():
    """A client only ever sees an `events` frame whose `since` is the seq it holds."""
    cycle = [_events_frame(3, [4, 5, 6]), _view(6)]
    assert _contiguous(cycle, 3) == cycle, "a contiguous frame was altered"
    trimmed = _contiguous(cycle, 5)
    assert trimmed[0]["since"] == 5 and _seqs(trimmed[0]) == [6], \
        "events the socket already holds were sent again"
    assert _contiguous(cycle, 6) == [_view(6)], "an events frame with nothing new was sent"
    assert _contiguous(cycle, 2) == [_view(6)], "a gap was let through to the client"
    assert _contiguous(cycle, None) == [_view(6)], "events before the first view"
    assert cycle[0]["since"] == 3 and _seqs(cycle[0]) == [4, 5, 6], "the input was mutated"
    print("✅ test_contiguous_frames")


def test_sent_seq_moves_only_after_a_good_send():
    """B-10, the net loop's half: `sent_seq` is published after every frame of a cycle
    went out, and not on a failed send. The snapshot carries it; `live_ids()` keeps a
    connection mid-send that the snapshot leaves out."""
    class _ws:
        def __init__(self):
            self.sent, self.fail, self.gate = [], False, None

        async def send_json(self, data):
            if self.gate is not None:
                await self.gate.wait()
            if self.fail:
                raise ConnectionResetError("gone")
            self.sent.append(data)

    async def drive(srv):
        ws = _ws()
        conn = srv._live_conns.add(ws, object(), "cred")
        assert srv.live_viewers()[0].sent_seq is None

        await srv._send(conn, [_events_frame(0, [1]), _view(1)])
        assert [f["t"] for f in ws.sent] == ["view"], "events went out before any view"
        assert conn.sent_seq == 1 and srv.live_viewers()[0].sent_seq == 1

        ws.fail = True
        await srv._send(conn, [_events_frame(1, [2]), _view(2)])
        assert conn.sent_seq == 1, "a failed send moved the cursor: the next cycle has a gap"
        assert srv.live_viewers()[0].sent_seq == 1

        ws.fail, ws.gate = False, asyncio.Event()
        task = asyncio.ensure_future(srv._send(conn, [_events_frame(1, [2, 3]), _view(3)]))
        await asyncio.sleep(0)
        assert srv.live_viewers() == () and srv.live_ids() == frozenset({conn.id}), \
            "a connection mid-send must leave the snapshot and stay in the id set"
        ws.gate.set()
        await task
        assert _seqs(ws.sent[-2]) == [2, 3] and conn.sent_seq == 3
        srv._live_conns.remove(conn)
        assert srv.live_ids() == frozenset()

    srv = PlayerServer(None, None, None, lambda app, viewer: {})
    asyncio.run(drive(srv))
    print("✅ test_sent_seq_moves_only_after_a_good_send")


# ─────────────────────────────────────────────────────────────────────────────
#  Both halves, over a socket
# ─────────────────────────────────────────────────────────────────────────────

def test_events_cross_the_socket_and_the_route():
    from test_live import _auth_frame, _faster_cadence, _ws
    from test_mapserver import _server

    with _server(pump=True, push=True) as s, _faster_cadence():
        # `run()`'s wiring, which the rig's server predates.
        s.srv._build_view = net_link.view_at_seq
        s.srv._build_live = net_link.build_live
        s.srv._events_since = net_link.events_since

        with _ws(s.srv.port) as sock:
            sock.send_text(_auth_frame(s.player))
            assert sock.view(timeout=5.0)["seq"] == 0

            s.stop_pump()                           # the stream is frame-tick state
            _flash(s.app, "Gnasher")
            _flash(s.app, "Skarn")
            _flash(s.app, "Gnasher", "Miss")
            s.start_pump()

            frames = []
            for _ in range(200):
                frames.append(sock.view(timeout=5.0))
                if frames[-1]["t"] == "events":
                    frames.append(sock.view(timeout=5.0))
                    break
            events, view = frames[-2], frames[-1]
            assert events["t"] == "events", "no events frame ever crossed the socket"
            assert _seqs(events) == [1, 2] and events["since"] == 0
            assert view["t"] == "view" and view["seq"] == 2
            assert "Skarn" not in json.dumps(frames)
            # Views keep coming every 25 ms, so this reads a fixed number of them rather
            # than waiting for a silence that never comes.
            for _ in range(20):
                later = sock.view(timeout=5.0)
                assert later["t"] != "events", f"an acked event was sent again: {later}"

        code, _, body = s.get("/events?since=0", credential=s.player)
        assert code == 200, code
        got = json.loads(body)
        assert got["t"] == "events" and _seqs(got) == [1, 2]
        assert "Skarn" not in body.decode()
        code, _, body = s.get("/events?since=0", credential=s.dm)
        assert _seqs(json.loads(body)) == [1, 2, 3], "the DM's stream is unfiltered"
        assert json.loads(s.get("/events?since=99", credential=s.player)[2])["t"] == "view"
        assert s.get("/events?since=abc", credential=s.player)[0] == 400
        assert s.get("/events", credential=s.player)[0] == 400
        assert s.get("/events?since=0")[0] == 401
        assert json.loads(s.get("/state", credential=s.player)[2])["seq"] == 2
    print("✅ test_events_cross_the_socket_and_the_route")


if __name__ == "__main__":
    test_a_new_socket_starts_from_a_view()
    test_events_ride_before_the_view_and_end_at_its_seq()
    test_a_dropped_send_is_resent_whole()
    test_an_in_flight_socket_keeps_its_cursor()
    test_every_seated_principal_is_projected()
    test_a_seat_that_goes_away_forgets_its_stream()
    test_the_turn_boundary_is_an_event()
    test_a_cursor_past_the_ring_resyncs()
    test_events_since_answers_or_resyncs()
    test_contiguous_frames()
    test_sent_seq_moves_only_after_a_good_send()
    test_events_cross_the_socket_and_the_route()
    print("\nAll event delivery tests passed! 🎉")
