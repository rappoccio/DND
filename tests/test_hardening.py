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
  · D-M7-4: the ring, its tail and the DM-only filter       (test_the_session_log_ring)
  · D-M7-4: a DM-only line never reaches a player's bytes   (test_dm_lines_never_reach_a_player)
  · D-M7-4: joins, re-joins, connects and drops are said    (test_the_table_hears_who_comes_and_goes)
  · D-M7-4: a takeover, an expiry and a pause are said      (test_the_table_hears_the_dm)
  · D-M7-4: the Table panel and the close codes, in node    (test_the_table_panel_in_the_client)
  · D-M7-5: Table… on the setup panel opens the menu         (test_the_setup_button_opens_the_table_menu)
  · D-M7-5: the combat tool opens it and takes nothing over  (test_the_combat_tool_opens_it_mid_fight)
  · D-M7-5: removing a player, end to end                    (test_removing_a_player)
  · D-M7-5: a new code keeps seats; a lock signs everyone out (test_new_code_and_lock)
  · D-M7-5: rename, and the session log viewer               (test_rename_and_the_log_viewer)
  · D-M7-6: the room flood stops at walls, doors and edges    (test_room_cells_stop_at_the_room)
  · D-M7-6: Reveal / Fog this room, through the fog menu      (test_reveal_and_fog_a_room)
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
from net import sessionlog as net_sessionlog
from prompts import PromptState
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
        s.srv.audit = lambda text, dm_only=True, principal=None: lines.append((text, dm_only))
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


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-4 — the session log
# ─────────────────────────────────────────────────────────────────────────────

def test_the_session_log_ring():
    log = net_sessionlog.SessionLog()
    for n in range(net_sessionlog.RING_SIZE + 10):
        log.add(f"line {n}", dm_only=(n % 2 == 1))
    assert len(log) == net_sessionlog.RING_SIZE, "the ring is not bounded"
    public = log.tail(include_dm=False)
    assert len(public) == net_sessionlog.WIRE_TAIL
    assert all("dm" not in e for e in public), "a DM line in the public tail"
    assert public[-1]["text"] == f"line {net_sessionlog.RING_SIZE + 8}"
    dm = log.tail(include_dm=True)
    assert dm[-1] == {"n": net_sessionlog.RING_SIZE + 10, "at": dm[-1]["at"],
                      "text": f"line {net_sessionlog.RING_SIZE + 9}", "dm": True}, dm[-1]
    assert [e["n"] for e in dm] == sorted(e["n"] for e in dm), "the tail is not in order"
    # Fresh dicts: a caller that edits its copy edits nothing else (CommandQueue rule 3).
    dm[-1]["text"] = "edited"
    assert log.tail(include_dm=True)[-1]["text"] != "edited"
    # No path, no file: a headless App writes nothing into the tree.
    assert log.path is None
    print("✅ test_the_session_log_ring")


def test_dm_lines_never_reach_a_player():
    """Byte level, like every fog check: an address in a DM-only line is omitted from a
    player's view, not marked hidden. The DM's view carries it, marked `dm`."""
    import shutil
    import tempfile
    from net.view import build_view
    from test_gameview import _scene
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _scene(tmp)
        app.session_log.add("Kira joined the table.", principal=kira.id)
        app.session_log.add("Refused a join with a wrong code from 10.9.8.7.", dm_only=True)
        player = json.dumps(build_view(app, kira))
        dm = build_view(app, app.roster.get(DM_PRINCIPAL_ID))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert "Kira joined the table." in player
    assert "10.9.8.7" not in player and '"dm"' not in player, "a DM line reached a player"
    assert [e.get("dm", False) for e in dm["session"]] == [False, True], dm["session"]
    assert "principal" not in json.dumps(dm["session"]), "the wire carries the file's ids"
    print("✅ test_dm_lines_never_reach_a_player")


def _wait_for(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def test_the_table_hears_who_comes_and_goes():
    """The server's public lines: a new seat, a seat taken back, a first screen and a
    last one. A second screen and its close say nothing."""
    with _server(pump=True) as s:
        log = s.app.session_log
        s.srv.audit = log.add
        texts = lambda: [e["text"] for e in log.tail(include_dm=False)]
        code = s.app.roster.join_code
        status, _, body = s.post("/join", {"v": 1, "t": "auth", "join_code": code,
                                          "display_name": "Mira"})
        assert status == 202, status
        mira = json.loads(body)["principal"]["id"]
        status, _, _ = s.post("/join", {"v": 1, "t": "auth", "join_code": code,
                                       "principal_id": mira})
        assert status == 202
        assert texts() == ["Mira joined the table.", "Mira took back their seat."], texts()

        a = _opened(s.srv.port, s.player)
        b = _opened(s.srv.port, s.player)
        _wait_for(lambda: "Kira connected." in texts())
        b.close()
        time.sleep(0.3)
        assert "Kira disconnected." not in texts(), "a second screen's close was a drop"
        a.close()
        _wait_for(lambda: "Kira disconnected." in texts())
        assert texts().count("Kira connected.") == 1, texts()
    print("✅ test_the_table_hears_who_comes_and_goes")


def test_the_table_hears_the_dm():
    """The bus's lines, said to the table: the DM taking a player's turn over, a prompt
    that ran out of time, and a pause and resume."""
    import shutil
    import tempfile
    from types import SimpleNamespace as NS
    from gui_driver import post_click
    from menus import panel
    from prompts import CLOCK_PRINCIPAL_ID
    from test_offer import _aria_turn, _frame, _offer
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        assert _offer(app) is not None, "precondition: Kira's offer is up"
        post_click(app, panel.cbt_btn(app, "dodge").rect.center)
        texts = [e["text"] for e in app.session_log.tail(include_dm=False)]
        assert texts == ["The DM took over Kira's turn."], texts

        app.submit_log.observe("cancelled", NS(id="p9", kind="reaction", owner=kira.id,
                                               resolved_by=CLOCK_PRINCIPAL_ID,
                                               actor_idx=0, response=None))
        _frame(app)
        post_click(app, panel.cbt_btn(app, "pause_resume").rect.center)
        _frame(app)
        post_click(app, panel.cbt_btn(app, "pause_resume").rect.center)
        texts = [e["text"] for e in app.session_log.tail(include_dm=False)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert texts[1:] == ["Kira's reaction timed out.", "The DM paused the game.",
                         "The DM resumed the game."], texts
    print("✅ test_the_table_hears_the_dm")


def test_the_table_panel_in_the_client():
    """`session_checks.js`, run against the real `app.js`; skipped without node."""
    import shutil
    import subprocess
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_table_panel_in_the_client SKIPPED — no node in this image")
        return
    checks = os.path.join(_ROOT, "tests", "session_checks.js")
    done = subprocess.run([node, checks], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the session checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    html = open(os.path.join(_ROOT, "gui", "net", "static", "index.html"),
                encoding="utf-8").read()
    assert html.count('id="table-log"') == 1 and html.count('id="session"') == 1
    print("✅ test_the_table_panel_in_the_client")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-5 — the Table menu
# ─────────────────────────────────────────────────────────────────────────────

def _choose(app, label_start):
    """Pick the live menu's row that starts with ``label_start``, as the DM."""
    live = app.prompts.live
    assert live is not None, f"no menu is open to pick {label_start!r} from"
    opt = next((o for o in live.options if o.label.startswith(label_start)), None)
    assert opt is not None, (label_start, [o.label for o in live.options])
    assert app.prompts.choose(opt.id).ok
    return app.prompts.live


def test_the_setup_button_opens_the_table_menu():
    import shutil
    import tempfile
    from gui_driver import post_click
    from test_gameview import _scene
    tmp = tempfile.mkdtemp()
    try:
        app, _, _ = _scene(tmp)
        app._reposition_panel()
        btn = app.btn_table
        assert btn.rect.top == app.btn_restore_autosave.rect.top, "not on the restore row"
        for other in (app.btn_restore_autosave, app.btn_begin_combat, app.btn_terrain):
            assert not btn.rect.colliderect(other.rect), f"{btn.rect} overlaps {other.text}"
        post_click(app, btn.rect.center)
        live = app.prompts.live
        assert live is not None and live.title == "Table", live and live.title
        labels = [o.label for o in live.options]
        assert labels[0] == f"Join code {app.roster.join_code} · no player server", labels
        assert labels[1] == "Players (2) ▸", labels
        assert live.owner == DM_PRINCIPAL_ID
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_the_setup_button_opens_the_table_menu")


def test_the_combat_tool_opens_it_mid_fight():
    """In a fight the setup panel is gone, so the Table menu is a DM tool in the combat
    panel. Opening it on Kira's turn is not acting on her turn (NOT_A_TAKEOVER)."""
    import shutil
    import tempfile
    from gui_driver import post_click
    from menus import panel
    from test_offer import _aria_turn, _frame, _offer, _log
    tmp = tempfile.mkdtemp()
    try:
        app, _, _ = _aria_turn(tmp)
        offer = _offer(app)
        assert offer is not None
        post_click(app, panel.cbt_btn(app, "table").rect.center)
        live = app.prompts.live
        assert live is not None and live.title == "Table", live and live.title
        labels = [o.label for o in live.options]
        assert "Restore autosave…" in labels, labels
        # The bus holds one live prompt, so the menu supersedes the offer, as any DM menu
        # does. That is not a takeover: nothing is logged, and once the menu is answered
        # the offer comes back.
        assert offer.state is PromptState.SUPERSEDED, offer.state
        assert _log(app) == [], _log(app)
        assert not [e for e in app.session_log.tail(include_dm=True) if "took over" in e["text"]]
        _choose(app, "Join code")
        _frame(app)
        assert _offer(app) is not None, "Kira's offer did not come back"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_the_combat_tool_opens_it_mid_fight")


def test_removing_a_player():
    """Players ▸ Kira ▸ Remove: her screen closes with 4403, her seat and credential are
    gone, Aria is the DM's again in the record and in the session file, and the table
    is told. With the same code she can join again, as a new seat with nothing."""
    with _server(push=True) as s:
        s.app.session_log.path = os.path.join(s.tmp, "session_log.jsonl")
        s.srv.audit = s.app.session_log.add
        aria = next(i for i, pt in enumerate(s.app.bm.placed_agents) if pt.name == "Aria")
        sock = _opened(s.srv.port, s.player)
        try:
            from menus import dm as dm_menus
            dm_menus.show_table_menu(s.app)
            _choose(s.app, "Players")
            _choose(s.app, "Kira ▸")
            _choose(s.app, "Remove Kira")
            assert _closed_with(sock) == net_server.WS_CLOSE_REMOVED
        finally:
            sock.close()
        assert s.app.roster.get(s.kira.id) is None
        assert s.app.bm.placed_agents[aria].controller == DM_PRINCIPAL_ID
        assert s.app.roster.controller_of(aria) == DM_PRINCIPAL_ID
        with open(s.app._session_path, encoding="utf-8") as fh:
            assert s.kira.id not in fh.read(), "the session file still seats Kira"
        assert s.get("/state", credential=s.player)[0] == 401
        status, _, body = s.post("/join", {"v": 1, "t": "auth",
                                          "join_code": s.app.roster.join_code,
                                          "display_name": "Kira", "principal_id": s.kira.id})
        assert status == 202, status
        again = json.loads(body)
        assert again["principal"]["id"] != s.kira.id and again["seated"] is False, again
        texts = [e["text"] for e in s.app.session_log.tail(include_dm=False)]
        assert texts.index("The DM removed Kira from the table.") \
            < texts.index("Kira joined the table."), texts
        with open(s.app.session_log.path, encoding="utf-8") as fh:
            logged = [json.loads(line) for line in fh]
        removed = next(e for e in logged if e["text"].startswith("The DM removed"))
        assert removed["principal"] == s.kira.id, "the file lost whose seat it was"
    print("✅ test_removing_a_player")


def test_new_code_and_lock():
    """A new code stops the old one inviting anyone, and signs nobody out. Locking the
    table also revokes every credential; a seat survives it, and joining again with the
    new code takes it back, tokens and all."""
    from menus import dm as dm_menus
    with _server(push=True) as s:
        s.srv.audit = s.app.session_log.add
        old = s.app.roster.join_code
        sock = _opened(s.srv.port, s.player)
        try:
            dm_menus.new_join_code(s.app)
            new = s.app.roster.join_code
            assert new != old
            assert s.post("/join", {"v": 1, "t": "auth", "join_code": old})[0] == 403
            assert sock.view(timeout=3.0)["t"] in ("view", "events"), "the code change dropped a screen"
            assert s.get("/state", credential=s.player)[0] == 200

            dm_menus.lock_table(s.app)
            assert s.app.roster.join_code != new
            assert _closed_with(sock) == net_server.WS_CLOSE_UNAUTHENTICATED
        finally:
            sock.close()
        assert s.get("/state", credential=s.player)[0] == 401
        status, _, body = s.post("/join", {"v": 1, "t": "auth",
                                          "join_code": s.app.roster.join_code,
                                          "display_name": "Kira", "principal_id": s.kira.id})
        assert status == 202, status
        back = json.loads(body)
        assert back["principal"]["id"] == s.kira.id and back["seated"] is True, back
        public = " ".join(e["text"] for e in s.app.session_log.tail(include_dm=False))
        assert "The DM changed the join code." in public
        assert "The DM locked the table." in public
        assert old not in public and new not in public, "a join code reached the table's log"
        assert s.app.roster.join_code not in public
    print("✅ test_new_code_and_lock")


def test_rename_and_the_log_viewer():
    import shutil
    import tempfile
    from menus import dm as dm_menus
    from test_gameview import _scene
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _scene(tmp)
        dm_menus.show_table_menu(app)
        _choose(app, "Players")
        _choose(app, "Kira ▸")
        _choose(app, "Rename")
        assert app.name_prompt.visible
        app.name_prompt._callback("Kira the Bold")
        assert app.roster.display_name(kira.id) == "Kira the Bold"
        app.session_log.add("Refused a join from 10.1.1.1.", dm_only=True)
        dm_menus.show_table_menu(app)
        log = _choose(app, "Session log")
        labels = [o.label for o in log.options]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert labels[0].endswith("The DM renamed Kira to Kira the Bold."), labels
    assert labels[1].endswith("[DM] Refused a join from 10.1.1.1."), labels
    print("✅ test_rename_and_the_log_viewer")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-6 — reveal a region
# ─────────────────────────────────────────────────────────────────────────────

def _blank_map(tmp):
    from test_gameview import _scene
    app, kira, _ = _scene(tmp)
    bm = app.bm
    # The scene's own structure would muddy the counts: clear it to an open 11×11 floor.
    import rpg_battle_map as rpg
    for d in list(bm.doors):
        bm.remove_door(d.id)
    for c in range(bm.grid_cols):
        for r in range(bm.grid_rows):
            bm.set_terrain_type(rpg.Cell(c, r), rpg.TerrainType.Standard)
    return app, kira, bm, rpg


def test_room_cells_stop_at_the_room():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        app, _, bm, rpg = _blank_map(tmp)
        cols, rows = int(bm.grid_cols), int(bm.grid_rows)
        cell = lambda c, r: rpg.Cell(c, r)
        as_set = lambda cells: {(c.col, c.row) for c in cells}

        # Open floor: the whole map, start first.
        whole = bm.room_cells(cell(1, 1), 4000)
        assert (whole[0].col, whole[0].row) == (1, 1)
        assert len(whole) == cols * rows

        # A wall of Wall terrain down column 5, with a door cell in it at row 3. The room
        # west of it is columns 0-4, plus the wall and the door it touches, and nothing
        # east of them: an open door is still the room's edge.
        for r in range(rows):
            if r != 3:
                bm.set_terrain_type(cell(5, r), rpg.TerrainType.Wall)
        bm.add_door(cells=[cell(5, 3)], open=True)
        west = as_set(bm.room_cells(cell(1, 1), 4000))
        assert west == {(c, r) for c in range(6) for r in range(rows)}, sorted(west)

        # Starting on the wall is the wall alone.
        assert as_set(bm.room_cells(cell(5, 0), 4000)) == {(5, 0)}

        # An edge wall east of column 7, then an open edge door on one of its edges: the
        # room between the two walls is columns 6-7, and the door does not let it out.
        for r in range(rows):
            bm.set_edge_wall(cell(7, r), rpg.EdgeSide.East, True)
        between = as_set(bm.room_cells(cell(6, 6), 4000))
        assert between == {(c, r) for c in (6, 7) for r in range(rows)} \
            | {(5, r) for r in range(rows)}, sorted(between)
        edge = rpg.Edge()
        edge.cell, edge.side = cell(7, 6), rpg.EdgeSide.East
        bm.add_edge_door(edges=[edge], open=True)
        assert as_set(bm.room_cells(cell(6, 6), 4000)) == between, "an open edge door leaked"

        # The cap, and a start off the grid.
        capped = bm.room_cells(cell(1, 1), 5)
        assert len(capped) == 5 and (capped[0].col, capped[0].row) == (1, 1)
        assert bm.room_cells(cell(-1, 0), 4000) == []
        assert bm.room_cells(cell(1, 1), 0) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_room_cells_stop_at_the_room")


def test_reveal_and_fog_a_room():
    """The fog menu's two new rows, end to end: right-click a cell, Reveal this room, and
    a player's view now carries that room; Fog this room puts it back. The table hears it."""
    import shutil
    import tempfile
    from menus import board
    from net.view import build_view
    tmp = tempfile.mkdtemp()
    try:
        app, kira, bm, rpg = _blank_map(tmp)
        rows = int(bm.grid_rows)
        for r in range(rows):
            bm.set_terrain_type(rpg.Cell(8, r), rpg.TerrainType.Wall)
        bm.set_explored_cells([])
        app._mark_fog_dirty = lambda: None       # the party's sight is not under test here
        x, y = app._cell_to_screen(10, 2)
        pos = (int(x) + 3, int(y) + 3)
        assert (lambda c: (c.col, c.row))(app._screen_to_cell(*pos)) == (10, 2)
        board.show_fog_menu(app, pos)
        labels = [o.label for o in app.prompts.live.options]
        assert labels[:2] == ["Reveal this room", "Fog this room"], labels
        _choose(app, "Reveal this room")
        explored = {(c.col, c.row) for c in bm.explored_cells()}
        assert explored == {(c, r) for c in (8, 9, 10) for r in range(rows)}, sorted(explored)
        runs = build_view(app, kira)["fog"]["explored_runs"]
        assert runs == [[r, 8, 10] for r in range(rows)], runs

        board.show_fog_menu(app, pos)
        _choose(app, "Fog this room")
        assert bm.explored_cells() == []
        texts = [e["text"] for e in app.session_log.tail(include_dm=False)]
        assert texts == ["The DM revealed part of the map.", "The DM fogged part of the map."]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_reveal_and_fog_a_room")


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
    test_the_session_log_ring()
    test_dm_lines_never_reach_a_player()
    test_the_table_hears_who_comes_and_goes()
    test_the_table_hears_the_dm()
    test_the_table_panel_in_the_client()
    test_the_setup_button_opens_the_table_menu()
    test_the_combat_tool_opens_it_mid_fight()
    test_removing_a_player()
    test_new_code_and_lock()
    test_rename_and_the_log_viewer()
    test_room_cells_stop_at_the_room()
    test_reveal_and_fog_a_room()
    print("\n✅ All hardening tests passed!")
