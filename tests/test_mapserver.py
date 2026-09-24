#!/usr/bin/env python3
"""`GET /map.png` over a real socket (MULTIPLAYER_PLAN.md M4, D-M4-1 / D-M4-6).

`test_mapimg.py` proves the *render* — pixel by pixel, that unexplored art is not in the
bytes. This proves the **route**: that the bytes only leave the process for a caller who
authenticated, that which of the two renders they get is a policy decision and not a role
check, and that a conditional request is answered against the key actually served.

Everything here goes through a real `aiohttp` server on a real port, driven by stdlib
`urllib` rather than `aiohttp`'s own client — deliberately, the way the Step 0.7 spike
did it: the exercised path should be the browser's, not the library talking to itself.

The scene is `test_gameview.py`'s, so the mask under test is the one the byte-level view
checks already read.

  · no credential, a forged one and a revoked one are each 401  (test_unauthenticated_is_401)
  · a cross-origin request is refused before authentication     (test_cross_origin_is_refused)
  · no Origin at all is allowed; a matching one is allowed      (test_absent_and_matching_origin)
  · a player is served the MASKED page, the DM the file itself  (test_player_is_masked_dm_is_raw)
  · the two viewers never share a cache key                     (test_dm_and_player_keys_differ)
  · nothing published yet is a 404, not an empty 200            (test_nothing_published_is_404)
  · If-None-Match on the served key is a 304 with no body       (test_conditional_request_is_304)
  · a stale `?v=` is served the current mask, and says so       (test_stale_v_is_served_the_current_key)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import shutil
import socket
import tempfile
import urllib.error
import urllib.request

from net import mapimg, view as net_view
from net.server import PlayerServer
from net.roster import DM_PRINCIPAL_ID

from test_gameview import _scene


# ─────────────────────────────────────────────────────────────────────────────
#  Rig
# ─────────────────────────────────────────────────────────────────────────────

def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class _server:
    """A scene, a server bound to loopback, and the credentials to reach it.

    Bound to 127.0.0.1 rather than `PLAYER_HOST`: the suite has no business publishing a
    port to the LAN, and the bind address is not what any of these checks are about.
    """

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.app, self.kira, _spectator = _scene(self.tmp)
        self.srv = PlayerServer(self.app.roster, self.app.map_images,
                                host="127.0.0.1", port=_free_port())
        self.srv.start()
        self.base = f"http://127.0.0.1:{self.srv.port}"
        self.player = self.app.roster.mint_credential(self.kira.id)
        self.dm = self.app.roster.mint_credential(DM_PRINCIPAL_ID)
        return self

    def __exit__(self, *exc):
        self.srv.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def publish(self, boundary=True):
        """One push cycle's worth, by hand — `_push_cycle` is the frame tick's caller and
        there is no frame tick here."""
        return self.app.map_images.publish(net_view.page_image(self.app),
                                           boundary=boundary)

    def get(self, path="/map.png", credential=None, origin=None, inm=None):
        """`(status, headers, body)`. A 4xx is a result here, never an exception."""
        req = urllib.request.Request(self.base + path)
        if credential is not None:
            req.add_header("Authorization", f"Bearer {credential}")
        if origin is not None:
            req.add_header("Origin", origin)
        if inm is not None:
            req.add_header("If-None-Match", inm)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


# ─────────────────────────────────────────────────────────────────────────────
#  Authentication — steps 1-5 of the frozen request order
# ─────────────────────────────────────────────────────────────────────────────

def test_unauthenticated_is_401():
    """Three ways to arrive without a usable credential, and the route must not be able to
    tell the caller which one it was."""
    with _server() as s:
        s.publish()

        status, headers, _ = s.get()
        assert status == 401, f"an anonymous fetch of the page returned {status}"
        assert headers.get("WWW-Authenticate") == "Bearer"

        forged = s.player[:-4] + ("aaaa" if not s.player.endswith("aaaa") else "bbbb")
        status, _, _ = s.get(credential=forged)
        assert status == 401, f"a tampered signature returned {status}"

        # A5: the revocation check runs on every request, and this is the one that proves
        # a credential that WAS valid stops being so without the process restarting.
        s.app.roster.revoke_credential(s.player)
        status, _, _ = s.get(credential=s.player)
        assert status == 401, f"a revoked credential returned {status}"

        assert s.srv.denials >= 3, "the middleware did not count its refusals"
        print("✅ test_unauthenticated_is_401")


def test_cross_origin_is_refused():
    """D-M4-6, and the order matters: a VALID credential with a foreign `Origin` is still
    refused, because the Origin check is step 1 and authentication is steps 2-5."""
    with _server() as s:
        s.publish()
        status, _, _ = s.get(credential=s.player, origin="http://evil.example")
        assert status == 403, f"a cross-origin fetch with a good token returned {status}"

        # And an `Origin` whose host matches but whose SCHEME differs is still the same
        # host:port — the check is scheme-less on purpose, because the DM may front this
        # with a proxy that terminates TLS (A7) and the page would then be https.
        host = f"127.0.0.1:{s.srv.port}"
        status, _, _ = s.get(credential=s.player, origin=f"https://{host}")
        assert status == 200, f"a same-host https Origin was refused with {status}"
        print("✅ test_cross_origin_is_refused")


def test_absent_and_matching_origin():
    """Absent ⇒ allow (curl, native clients). Matching ⇒ allow. Both spelled out, because
    'allow when absent' is the branch a tightening would quietly delete."""
    with _server() as s:
        s.publish()
        status, _, body = s.get(credential=s.player)          # urllib sends no Origin
        assert status == 200 and body, f"a no-Origin fetch returned {status}"
        status, _, _ = s.get(credential=s.player,
                             origin=f"http://127.0.0.1:{s.srv.port}")
        assert status == 200, f"a same-origin fetch returned {status}"
        print("✅ test_absent_and_matching_origin")


# ─────────────────────────────────────────────────────────────────────────────
#  What each viewer is served
# ─────────────────────────────────────────────────────────────────────────────

def test_player_is_masked_dm_is_raw():
    """The route's whole reason to exist: the player's bytes are the composite, and the
    DM's are the file — not a re-encode of it, which is why this compares to disk."""
    with _server() as s:
        page = s.publish()
        with open(page.path, "rb") as fh:
            on_disk = fh.read()

        _st, _h, player_body = s.get(credential=s.player)
        _st, _h, dm_body = s.get(credential=s.dm)

        assert dm_body == on_disk, "the DM was served something other than the page file"
        assert player_body != on_disk, \
            "the player was served the page file — the route is not masking"
        assert player_body == mapimg.render(page, is_dm=False), \
            "the player's bytes are not the masked render of the published page"
        print("✅ test_player_is_masked_dm_is_raw")


def test_dm_and_player_keys_differ():
    """Two cache entries, never one. If these ever collide, a warmed DM entry can be
    handed to a player by a cache that thinks they asked the same question."""
    with _server() as s:
        s.publish()
        _st, ph, _b = s.get(credential=s.player)
        _st, dh, _b = s.get(credential=s.dm)
        assert ph["ETag"] and dh["ETag"]
        assert ph["ETag"] != dh["ETag"], \
            f"the DM and a player share a key: {ph['ETag']}"
        assert "no-cache" in ph["Cache-Control"] and "private" in ph["Cache-Control"]
        print("✅ test_dm_and_player_keys_differ")


def test_nothing_published_is_404():
    """Before the first push cycle there is no snapshot. A 404 is a state the client
    retries out of; a 200 with an empty body is one it caches."""
    with _server() as s:
        status, _, _ = s.get(credential=s.player)
        assert status == 404, f"an unpublished page returned {status}"
        s.publish()
        status, _, _ = s.get(credential=s.player)
        assert status == 200, f"a published page returned {status}"
        print("✅ test_nothing_published_is_404")


# ─────────────────────────────────────────────────────────────────────────────
#  Conditional requests — the half of the lag that saves the megabytes
# ─────────────────────────────────────────────────────────────────────────────

def test_conditional_request_is_304():
    """The 3 s key lag is only half the saving; this is the other half. Between re-keys a
    player spends one conditional request instead of 0.8-2.5 MB."""
    with _server() as s:
        s.publish()
        _st, headers, body = s.get(credential=s.player)
        etag = headers["ETag"]
        assert body

        status, h2, b2 = s.get(credential=s.player, inm=etag)
        assert status == 304, f"a matching If-None-Match returned {status}"
        assert b2 == b"", "a 304 carried a body"
        assert h2["ETag"] == etag, "the 304 did not name the key it was answering about"

        status, _, b3 = s.get(credential=s.player, inm='"not-the-key"')
        assert status == 200 and b3 == body, "a non-matching If-None-Match was not served"

        # Weak validators and lists are both legal on the wire.
        status, _, _ = s.get(credential=s.player, inm=f'"other", W/{etag}')
        assert status == 304, "a weak validator in a list was not matched"
        print("✅ test_conditional_request_is_304")


def test_stale_v_is_served_the_current_key():
    """`?v=` is a cache-buster, not a request for a specific picture.

    The cache serves the newest published mask however old the `?v=` is — which can only
    reveal cells the party has already earned — so the ETag must be the key *served*. A
    handler that echoed the requested `?v=` would hand the client a label for bytes it did
    not receive, and every conditional request after it would be answered wrongly.
    """
    with _server() as s:
        page = s.publish()
        stale = "0" * 16
        _st, headers, body = s.get(path=f"/map.png?v={stale}", credential=s.player)
        assert headers["ETag"] == f'"{page.key(False)}"', \
            f"the route echoed the requested ?v= instead of the key it served: {headers['ETag']}"
        assert body == mapimg.render(page, is_dm=False)

        # And the client that asks conditionally with that stale key gets the real bytes.
        status, _, b2 = s.get(path=f"/map.png?v={stale}", credential=s.player,
                              inm=f'"{stale}"')
        assert status == 200 and b2 == body, \
            "a stale validator was answered 304 — the client would never see the new mask"
        print("✅ test_stale_v_is_served_the_current_key")


if __name__ == "__main__":
    test_unauthenticated_is_401()
    test_cross_origin_is_refused()
    test_absent_and_matching_origin()
    test_player_is_masked_dm_is_raw()
    test_dm_and_player_keys_differ()
    test_nothing_published_is_404()
    test_conditional_request_is_304()
    test_stale_v_is_served_the_current_key()
    print("\n✅ All map-server tests passed!")
