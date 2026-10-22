#!/usr/bin/env python3
"""Reconnect and restart, end to end (MULTIPLAYER_PLAN.md M6.5, D-M6-7).

  · the client remembers the seat and not the secret, and sends `principal_id` only while
    the name still matches (`reclaim_checks.js`, the real `app.js` under node);
  · a socket that drops without a close frame leaves the server's table, and the same
    credential opens a new one onto the same seat;
  · a restart — a new App and a new server, the slot restored — refuses the old credential,
    and a join carrying `principal_id` puts the player back in the seat that controls their
    token, even after the DM renamed it.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
# The runner turns the ring off for every suite; the restart restores from it.
os.environ["RPG_AUTOSAVE"] = "1"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import contextlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import autosave
from net import link as net_link, view as net_view
from net.roster import PROTOCOL_VERSION
from net.server import PlayerServer, WS_CLOSE_UNAUTHENTICATED

from test_autosave_restore import _fresh
from test_live import _auth_frame, _faster_cadence, _ws
from test_mapserver import _free_port, _server
from test_restore_oracle import _fight, _idx

_CHECKS = os.path.join(_ROOT, "tests", "reclaim_checks.js")


@contextlib.contextmanager
def _serving(app):
    """`test_mapserver._server`'s rig around an App this suite built: a loopback server,
    and a stand-in frame tick that pumps commands and pushes views."""
    srv = PlayerServer(app.roster, app.map_images, app._net_commands, net_view.build_view,
                       host="127.0.0.1", port=_free_port())
    srv.start()
    app._net = srv
    running = [True]

    def tick():
        while running[0]:
            app._net_commands.pump(app)
            net_link.push_cycle(app)
            time.sleep(0.002)

    ticker = threading.Thread(target=tick, daemon=True, name="fake-frame-tick")
    ticker.start()
    try:
        yield srv
    finally:
        running[0] = False
        ticker.join(2.0)
        srv.stop()
        app._net = None


def _join(srv, **fields):
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/join", method="POST",
        data=json.dumps({"v": PROTOCOL_VERSION, "t": "auth", "join_code": None,
                         **fields}).encode())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def _live_view(srv, credential):
    """The first frame a socket opened with `credential` gets: a view, or a close code."""
    with _ws(srv.port) as sock:
        sock.send_text(_auth_frame(credential))
        kind, data = sock.recv(timeout=5.0)
        return json.loads(data) if kind == "text" else data


def test_the_client_in_node():
    """`reclaim_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_client_in_node SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the re-claim checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_client_in_node")


def test_a_dropped_socket_reconnects_to_its_seat():
    """Closed laptop, wifi drop: the TCP connection dies with no close frame. The server
    has to notice and drop it from the push table, and the credential — still valid, the
    process never restarted — opens a new socket onto the same seat with a fresh view."""
    with _server(pump=True, push=True) as s, _faster_cadence():
        aria = _idx(s.app, "Aria")
        sock = _ws(s.srv.port)
        sock.connect()
        sock.send_text(_auth_frame(s.player))
        first = sock.view(timeout=5.0)
        assert first["you"]["principal_id"] == s.kira.id
        assert len(s.srv.live_ids()) == 1

        sock._sock.close()                     # no close frame: the wire just went away
        sock._sock = None
        deadline = time.monotonic() + 5.0
        while s.srv.live_ids() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not s.srv.live_ids(), "the dead socket is still in the push table"

        again = _live_view(s.srv, s.player)
        assert isinstance(again, dict) and again["t"] == "view", f"the reconnect got {again}"
        assert again["you"]["principal_id"] == s.kira.id, "the reconnect landed in another seat"
        assert aria in again["you"]["controls"], "the reconnect lost Kira's token"
        assert again["seq"] >= first["seq"], "seq went backwards across a reconnect"
        print("✅ test_a_dropped_socket_reconnects_to_its_seat")


def test_a_restart_reclaims_the_seat():
    """R3/R4: the process dies mid-fight. The relaunched DM restores the autosave; every
    credential died with the signing key (A5), and the player re-joins with the code and
    the `principal_id` their device kept, landing in the seat that controls their token."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        aria = _idx(app, "Aria")
        kira = app.roster.add_principal("Kira")
        app.bm.set_agent_controller(aria, kira.id)
        app._sync_roster_tokens()
        app._save_session()
        k = autosave.save(app)
        turn = (app.round_num, app.turn_idx)
        code = app.roster.join_code

        with _serving(app) as srv1:
            status, doc = _join(srv1, join_code=code, display_name="Kira")
            assert status == 202 and doc["principal"]["id"] == kira.id, doc
            old = doc["credential"]
            assert _live_view(srv1, old)["you"]["principal_id"] == kira.id

        # The relaunch: a new App on the same encounter, a new server, the slot restored.
        app2 = _fresh(app)
        assert app2.roster is not app.roster
        assert app2.roster.get(kira.id) is not None, "Kira's seat did not survive the restart"
        assert app2.roster.verify_credential(old) is None, "a credential outlived its key"
        assert autosave.restore(app2, k)
        assert (app2.round_num, app2.turn_idx) == turn
        # The DM tidies the seat's label after the restart; the device still has the old one.
        app2.roster.rename_principal(kira.id, "Kira the Bold")

        with _serving(app2) as srv2:
            assert _live_view(srv2, old) == WS_CLOSE_UNAUTHENTICATED, \
                "the dead credential was not refused with 4401, so the client would retry it"
            status, doc = _join(srv2, join_code=code, display_name="Kira",
                                principal_id=kira.id)
            assert status == 202, f"the re-join was refused ({status})"
            assert doc["principal"]["id"] == kira.id, f"re-claimed {doc['principal']}"
            assert doc["seated"] is True, "the re-claimed seat owns no token"
            assert doc["principal"]["display_name"] == "Kira the Bold", "the join renamed the seat"
            view = _live_view(srv2, doc["credential"])
            assert view["you"]["principal_id"] == kira.id
            assert aria in view["you"]["controls"], "Kira is back but does not control Aria"
            assert view["combat"]["round"] == turn[0]
            assert len(app2.roster.players()) == 1, "the re-join minted a second seat"
        print("✅ test_a_restart_reclaims_the_seat")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [test_the_client_in_node, test_a_dropped_socket_reconnects_to_its_seat,
             test_a_restart_reclaims_the_seat]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
