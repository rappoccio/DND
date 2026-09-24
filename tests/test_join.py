#!/usr/bin/env python3
"""`POST /join` — the one pre-auth route (MULTIPLAYER_PLAN.md M4c, D-M4-4 / D-M4c-3/4/5).

Everything else on this server answers "may this credential see this?". This route answers
"is there a credential at all?", which makes it the only place where a wrong decision is
reachable by someone who has proved nothing. Three separate rules meet here and each of
them has an obvious implementation that is wrong:

  · **the exemption** suppresses the 401 and *nothing else* — the `Origin` check still
    runs, and so does `verify_credential`, because its answer IS D-M4-4's step 1;
  · **the matching order** is credential → `principal_id` → `display_name` → new. Name
    matching first is the version where two players called "Kira" race for one seat;
  · **the limiter** rations guesses at the join code, which 31^6 makes a 51-day search
    without one.

Driven the way `test_mapserver.py` is: a real `aiohttp` server on a real port through
stdlib `urllib`, sharing that file's rig and `test_gameview.py`'s scene.

  · a good code mints a credential the middleware then accepts (test_join_mints_a_working_credential)
  · a wrong code is one opaque 403, and GET /join is not exempt (test_wrong_code_is_denied)
  · the exemption is a (method, path) pair, not a path         (test_the_exemption_is_a_method_and_a_path)
  · a malformed body, a wrong `v` and a wrong `t` are 400s     (test_protocol_errors_are_400)
  · the exemption does not skip the Origin check               (test_cross_origin_join_is_refused)
  · a live credential wins over both hints, and renames nothing (test_live_credential_reattaches_by_kid)
  · `principal_id` claims a seat, but never the DM's           (test_principal_id_claims_a_player_seat_only)
  · an unknown id falls through instead of saying it is unknown (test_unknown_principal_id_falls_through)
  · names match case-insensitively; no match is a new seat     (test_display_name_matches_case_insensitively)
  · `seated` is false for a player who owns no tokens          (test_spectator_is_seated_false)
  · failed joins are rationed; successes are not               (test_failed_joins_are_rate_limited)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import urllib.error
import urllib.request

from aiohttp import web

from net import view as net_view
from net.roster import DM_PRINCIPAL_ID, PROTOCOL_VERSION
from net.server import PlayerServer

from test_mapserver import _free_port, _server


def _body(status_headers_body):
    """The envelope of a join that was supposed to succeed.

    The status is asserted before the parse so that a mutant turning a join into a 500
    reports *that* rather than a `JSONDecodeError` on aiohttp's HTML error page.
    """
    status, _headers, body = status_headers_body
    assert status == 202, f"the join returned {status}, not 202: {body[:120]!r}"
    return json.loads(body)


def _join(s, **fields):
    """A well-formed envelope with `fields` merged in, so a check names only its subject."""
    return s.post("/join", data={"v": PROTOCOL_VERSION, "t": "auth", **fields})


# ─────────────────────────────────────────────────────────────────────────────
#  The happy path, and what it is worth
# ─────────────────────────────────────────────────────────────────────────────

def test_join_mints_a_working_credential():
    """A join is worth nothing unless the thing it mints is the thing the middleware takes.

    So this does not stop at the envelope: it spends the credential on `GET /map.png`,
    which is the route that already refuses everything unverified. A `/join` that minted a
    well-formed string the middleware rejects would pass every field-level check here.
    """
    with _server() as s:
        s.publish()
        status, headers, raw = s.post("/join", data={
            "v": PROTOCOL_VERSION, "t": "auth",
            "join_code": s.app.roster.join_code, "display_name": "Nym"})
        assert status == 202, f"a correct join code returned {status}"
        doc = json.loads(raw)
        assert doc["ok"] is True and doc["t"] == "auth" and doc["v"] == PROTOCOL_VERSION
        assert doc["principal"]["display_name"] == "Nym"
        assert doc["principal"]["role"] == "player"
        assert doc["seated"] is False, "a brand-new seat owns no tokens"
        assert doc["server_seq"] == 0, "seq is 0 until EventStream (S3) exists"
        assert "no-store" in headers.get("Cache-Control", "")

        status, _, _ = s.get("/map.png", credential=doc["credential"])
        assert status == 200, \
            f"the credential /join minted was refused by the middleware with {status}"

        # The code is an invite, not an identity (A2): a second join on the same code is a
        # second principal, not a collision.
        second = _body(s.post("/join", data={"v": PROTOCOL_VERSION, "t": "auth",
                                             "join_code": s.app.roster.join_code,
                                             "display_name": "Oro"}))
        assert second["principal"]["id"] != doc["principal"]["id"]
        print("✅ test_join_mints_a_working_credential")


# ─────────────────────────────────────────────────────────────────────────────
#  The exemption is narrow — D-M4c-3
# ─────────────────────────────────────────────────────────────────────────────

def test_wrong_code_is_denied():
    """One opaque shape for every failure, and the exemption is a `(method, path)` pair.

    `GET /join` is the mutant this second half exists for: an exemption keyed on the path
    alone hands an unauthenticated caller whatever a future `GET` on that path does.
    """
    with _server() as s:
        before = len(s.app.roster.players())
        status, _, raw = s.post("/join", data={"v": PROTOCOL_VERSION, "t": "auth",
                                               "join_code": "ZZZZZZ",
                                               "display_name": "Mallory"})
        assert status == 403, f"a wrong join code returned {status}"
        doc = json.loads(raw)
        assert doc == {"v": PROTOCOL_VERSION, "t": "auth", "ok": False, "error": "denied"}, \
            f"the failure envelope said more than 'denied': {doc}"
        assert len(s.app.roster.players()) == before, \
            "a refused join seated a principal anyway"

        # No code at all is the same answer, and says nothing about which was missing.
        status, _, raw = s.post("/join", data={"v": PROTOCOL_VERSION, "t": "auth"})
        assert status == 403 and json.loads(raw)["error"] == "denied"

        status, _, _ = s.get("/join")
        assert status == 401, f"GET /join was exempt from authentication — {status}"
        print("✅ test_wrong_code_is_denied")


def test_the_exemption_is_a_method_and_a_path():
    """`GET /join` must not be exempt — and today's route table cannot show that.

    `_is_pre_auth` asks the *router* which resource matched, and for a method with no
    route the router answers "none" before the pair is ever compared. So an exemption
    keyed on the path alone behaves identically on this server, and the obvious check —
    `GET /join` is a 401 — passes either way. That is a real mutant surviving for a
    reason which stops being true the moment M4d adds `GET /` and its static files.

    So the route table is what this puts under test: a server carrying a `GET /join` must
    still refuse an anonymous caller. Path-only matching hands them the handler.
    """
    class _AlsoGet(PlayerServer):
        def _build(self):
            app = super()._build()
            app.router.add_get("/join", self._probe)
            return app

        async def _probe(self, _request):
            return web.Response(text="reached the handler")

    with _server() as s:
        probe = _AlsoGet(s.app.roster, s.app.map_images, s.app._net_commands,
                         net_view.build_view, host="127.0.0.1", port=_free_port())
        probe.start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{probe.port}/join")
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    status, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read()
        finally:
            probe.stop()

        assert status == 401, \
            f"GET /join was exempt — the pair collapsed to a path ({status}, {body[:60]!r})"
        print("\u2705 test_the_exemption_is_a_method_and_a_path")


def test_cross_origin_join_is_refused():
    """The exemption suppresses the 401, not the `Origin` check (D-M4c-3).

    A cross-origin page cannot read this response (A3 forbids cookies, so it never gets
    the credential), but it can still *create seats*, which is defacement the DM then has
    to clean up. The check is step 1 and applies to `/join` most of all.
    """
    with _server() as s:
        status, _, _ = s.post("/join", origin="http://evil.example",
                              data={"v": PROTOCOL_VERSION, "t": "auth",
                                    "join_code": s.app.roster.join_code,
                                    "display_name": "Mallory"})
        assert status == 403, f"a cross-origin join with a good code returned {status}"
        assert not any(p.display_name == "Mallory" for p in s.app.roster.players()), \
            "a cross-origin join seated someone"
        print("✅ test_cross_origin_join_is_refused")


def test_protocol_errors_are_400():
    """`protocol` is a different answer from `denied`, and it is safe to distinguish.

    A malformed envelope tells an attacker nothing they did not already write, so the
    client gets to learn it. A wrong *code* never does.
    """
    with _server() as s:
        before = len(s.app.roster.players())
        for label, kwargs in (
            ("not JSON at all",  dict(raw=b"{{{")),
            ("a bare list",      dict(raw=b"[]")),
            ("the wrong v",      dict(data={"v": 99, "t": "auth",
                                            "join_code": s.app.roster.join_code})),
            ("the wrong t",      dict(data={"v": PROTOCOL_VERSION, "t": "view",
                                            "join_code": s.app.roster.join_code})),
        ):
            status, _, raw = s.post("/join", **kwargs)
            assert status == 400, f"{label} returned {status}"
            assert json.loads(raw)["error"] == "protocol", label
        assert len(s.app.roster.players()) == before, "a malformed join seated someone"
        print("✅ test_protocol_errors_are_400")


# ─────────────────────────────────────────────────────────────────────────────
#  The matching order — D-M4-4, as amended 2026-09-24
# ─────────────────────────────────────────────────────────────────────────────

def test_live_credential_reattaches_by_kid():
    """Step 1 beats both hints, and it beats them in the way that matters.

    The body here is actively hostile: it names somebody else's `principal_id` AND a
    different `display_name`. A live credential is the holder proving which seat is theirs,
    so neither is consulted — and, per D-M4c-4, neither is applied. A join that accepted
    `display_name` as an update would rename Kira to "Zed" on her own re-join, and through
    the `principal_id` path would let a code-holder relabel a seat they never owned.
    """
    with _server() as s:
        before = len(s.app.roster.players())
        doc = _body(s.post("/join", credential=s.player,
                           data={"v": PROTOCOL_VERSION, "t": "auth",
                                 "join_code": s.app.roster.join_code,
                                 "display_name": "Zed",
                                 "principal_id": s.spectator.id}))
        assert doc["principal"]["id"] == s.kira.id, \
            f"a live credential did not re-attach to its own principal: {doc['principal']}"
        assert doc["principal"]["display_name"] == "Kira", \
            "the join renamed the seat it matched"
        assert s.app.roster.get(s.kira.id).display_name == "Kira", \
            "the join renamed the principal in the roster"
        assert doc["seated"] is True, "Kira controls Aria and should be seated"
        assert len(s.app.roster.players()) == before, "a re-join minted a second seat"

        # And the new credential works, while the old one still does — /join issues, it
        # does not revoke. (M6 owns whatever eviction policy there turns out to be.)
        s.publish()
        assert s.get("/map.png", credential=doc["credential"])[0] == 200
        print("✅ test_live_credential_reattaches_by_kid")


def test_principal_id_claims_a_player_seat_only():
    """Step 2 is R3's case — the process restarted and took every credential with it.

    The DM's seat is the line: R2 accepts that anyone holding the code can claim to be
    Kira, and does not accept that they can become the DM. A `principal_id` of `dm` falls
    through to the name rule like any other unmatched id, which is also why it cannot be
    used to find out that the DM's id is what it is.
    """
    with _server() as s:
        doc = _body(_join(s, join_code=s.app.roster.join_code,
                          principal_id=s.kira.id, display_name="ignored"))
        assert doc["principal"]["id"] == s.kira.id, \
            f"principal_id did not claim its seat: {doc['principal']}"
        assert doc["principal"]["display_name"] == "Kira", "step 2 renamed the seat"

        doc = _body(_join(s, join_code=s.app.roster.join_code,
                          principal_id=DM_PRINCIPAL_ID, display_name="Mallory"))
        assert doc["principal"]["id"] != DM_PRINCIPAL_ID, \
            "a join code claimed the DM's seat"
        assert doc["principal"]["role"] == "player", \
            f"a join minted a non-player seat: {doc['principal']}"
        print("✅ test_principal_id_claims_a_player_seat_only")


def test_unknown_principal_id_falls_through():
    """An id that names nothing is not an error, and that is a security decision.

    An error distinguishing "no such seat" from "not your seat" is an oracle for which ids
    exist; Step 0.5's `error` set is closed for exactly that reason. So it falls through to
    the name rule — and lands on Kira's seat here, which is the proof it fell rather than
    stopped.
    """
    with _server() as s:
        doc = _body(_join(s, join_code=s.app.roster.join_code,
                          principal_id="p_nosuchseat", display_name="Kira"))
        assert doc["principal"]["id"] == s.kira.id, \
            f"an unknown principal_id did not fall through to the name: {doc['principal']}"
        print("✅ test_unknown_principal_id_falls_through")


def test_display_name_matches_case_insensitively():
    """Step 3 — the fallback, and the reason it is only the fallback.

    Case-insensitive because a player typing their own name on a phone keyboard is not
    performing an identity check; R2 already accepts that whoever holds the code can claim
    to be Kira, and NN4 leaves the DM able to reassign it.
    """
    with _server() as s:
        for typed in ("kira", "KIRA", "  Kira  "):
            doc = _body(_join(s, join_code=s.app.roster.join_code, display_name=typed))
            assert doc["principal"]["id"] == s.kira.id, \
                f"{typed!r} did not match Kira — a second player would take her seat"
            assert doc["principal"]["display_name"] == "Kira", f"{typed!r} renamed the seat"

        before = {p.id for p in s.app.roster.players()}
        doc = _body(_join(s, join_code=s.app.roster.join_code, display_name="Thorn"))
        assert doc["principal"]["id"] not in before, "an unmatched name reused a seat"
        assert doc["principal"]["display_name"] == "Thorn"
        print("✅ test_display_name_matches_case_insensitively")


def test_spectator_is_seated_false():
    """`seated: false` is legal and means "owns zero tokens" — a spectator, not a failure.

    Answerable on the net thread at all only because `TokenInfo` exists so ownership can
    be (Step 0.4); a `seated` hardcoded true would pass every other check in this file.
    """
    with _server() as s:
        doc = _body(_join(s, join_code=s.app.roster.join_code, display_name="Wen"))
        assert doc["principal"]["id"] == s.spectator.id
        assert doc["seated"] is False, "a player controlling no tokens reported as seated"

        doc = _body(_join(s, join_code=s.app.roster.join_code, display_name="Kira"))
        assert doc["seated"] is True, "Kira controls Aria and reported as unseated"
        print("✅ test_spectator_is_seated_false")


# ─────────────────────────────────────────────────────────────────────────────
#  The limiter — D-M4c-5
# ─────────────────────────────────────────────────────────────────────────────

def test_failed_joins_are_rate_limited():
    """887,503,681 codes is 51 days at 100 guesses a second, and 168 years at 10 a minute.

    Scoped to *failures*: a table typing the code correctly never meets this, and one
    player fat-fingering it cannot lock another out — which is the property that makes a
    limiter on a join route acceptable at all.
    """
    from net import server as net_server

    with _server() as s:
        good = s.app.roster.join_code
        for n in range(net_server.JOIN_FAILURE_LIMIT):
            status, _, _ = _join(s, join_code="ZZZZZZ", display_name="Mallory")
            assert status == 403, f"guess {n} returned {status} before the limit"

        status, _, raw = _join(s, join_code="ZZZZZZ", display_name="Mallory")
        assert status == 429, f"guess {net_server.JOIN_FAILURE_LIMIT} returned {status}"
        assert json.loads(raw)["error"] == "denied", "the 429 named a new error"

        # The limiter is in front of the code check, so even the RIGHT code is refused
        # while the bucket is full — otherwise a guesser learns they found it by the
        # status changing, which is the whole thing being rationed.
        assert _join(s, join_code=good, display_name="Nym")[0] == 429

        # Winding the window back is how a rolling window is tested without sleeping 60 s.
        for hits in s.srv._joins._failures.values():
            for i in range(len(hits)):
                hits[i] -= net_server.JOIN_FAILURE_WINDOW_S + 1
        assert _join(s, join_code=good, display_name="Nym")[0] == 202, \
            "the window did not roll"

        # And a success does not spend the bucket: a whole table can join at once.
        for n in range(net_server.JOIN_FAILURE_LIMIT + 5):
            status = _join(s, join_code=good, display_name="Kira")[0]
            assert status == 202, \
                f"successful join {n} returned {status} — a success spent the bucket"
        print("✅ test_failed_joins_are_rate_limited")


if __name__ == "__main__":
    test_join_mints_a_working_credential()
    test_wrong_code_is_denied()
    test_the_exemption_is_a_method_and_a_path()
    test_cross_origin_join_is_refused()
    test_protocol_errors_are_400()
    test_live_credential_reattaches_by_kid()
    test_principal_id_claims_a_player_seat_only()
    test_unknown_principal_id_falls_through()
    test_display_name_matches_case_insensitively()
    test_spectator_is_seated_false()
    test_failed_joins_are_rate_limited()
    print("\n✅ All join-route tests passed!")
