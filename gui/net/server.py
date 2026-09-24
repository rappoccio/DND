"""The player-facing HTTP server (MULTIPLAYER_PLAN.md M4).

One `aiohttp` application on an asyncio loop of its own, on a thread of its own, inside
the pygame process. The skeleton — the thread, the single middleware point A9 requires,
and `GET /map.png` — landed in M4; `POST /join` and `GET /state` (M4c) added two routes,
one pre-auth exemption and one shared queue, and `WS /live` and the client are still owed.

**`GET /state` is not a call to `build_view`.** That function reads `app.bm`, so it is a
pygame-thread reader and NN1 puts it out of this thread's reach (D-M4c-1). The route
submits a command to `net.commands.CommandQueue` and parks on the future the frame tick
resolves. This module therefore never imports `net.view` — the builder is handed in by
`net.link`, which is the half that may hold both.

**What it may touch, and why that is not NN1.** NN1 says the net thread never touches the
`CombatEngine`, the `BattleMap` or `App` — read or write. So this holds neither an `App`
nor anything reachable from the map. It holds exactly two objects, both handed to it by
the pygame thread:

  · a `SessionRoster`, which is plain Python and holds no `BattleMap` by construction —
    `TokenInfo` exists precisely so ownership can be answered off-thread (Step 0.4), and
    steps 2-5 of the request order cannot be answered anywhere else;
  · a `MapImageCache`, which is explicitly the handoff: the frame tick publishes an
    immutable snapshot and the net thread renders from it, holding no lock across the
    encode.

Named honestly: the roster is mutated on the pygame thread (`sync_tokens`,
`add_principal`) while this thread reads it — and, since M4c, `POST /join` mutates it from
*here* as well, because a join that needed the frame tick would be a join that hangs
behind whichever modal the DM has open. No read can tear: these are dict and dataclass
reads under the GIL, not C++ invariants mid-mutation, which is the distinction NN1's
tightening draws, and `sync_tokens` rebinds `_tokens` rather than mutating it, so a
concurrent `_rebuild_ownership()` here iterates a dict nothing will touch again.

Two costs, both liveness and neither safety. A request can see a **stale ownership answer**
for the one frame between a `Controller ▸` reassignment and the next `sync_tokens` — the
same window the DM's own screen has. And a DM seating a principal by hand in the same
instant as a join can make `players()` iterate a dict that grew under it, which is a 500 on
that one join and a retry. Hardening the roster against that needs a lock it does not have
and is written down rather than bundled here.

**F6, tested rather than assumed**: `web.run_app` installs signal handlers and dies off the
main thread with `set_wakeup_fd only works in main thread of the main interpreter`. The
runner form is not a style preference (D-M4-5).

`aiohttp` is imported at module scope on purpose, so `main.py`'s guarded import either
gets a working server or gets `ImportError` and says so once (D1/F7). There is no
half-initialized middle state.
"""

from __future__ import annotations

import asyncio
import collections
import os
import socket
import threading
import time

from aiohttp import web

from .roster import PROTOCOL_VERSION, Action

# D2: the player port, and the only one that ever faces the LAN. 6080 is the DM console
# and is bound to loopback in run.sh / interactive.sh (S2, A10) — these are two trust
# domains and the port numbers are where that becomes a fact.
PLAYER_PORT = 6081
PLAYER_HOST = "0.0.0.0"       # A6/A7: listens plain on the LAN; TLS is a proxy's job

# D-M4c-2: F1's number. A wedged frame loop becomes a visible failed request rather than
# a silent stall, which F1 recorded as strictly the better of the two.
STATE_TIMEOUT_S = 5.0

# D-M4c-5. The join code is 6 characters of a 31-symbol alphabet — 887,503,681 of them.
# Unthrottled, an attacker already on the LAN at 100 req/s has an even chance inside 51
# days, which is a long weekend rather than a lifetime. At 10 failures a minute it is 168
# years. A SUCCESSFUL join does not count, so a table typing the code correctly never
# meets this and one player fat-fingering it cannot lock out another.
JOIN_FAILURE_LIMIT = 10
JOIN_FAILURE_WINDOW_S = 60.0

# D-M4c-3. Exact `(method, path)` pairs, matched against the *registered* route rather
# than the requested string — never a prefix and never a path alone. `GET /join` is not a
# member, and a prefix is how `/join/../state` becomes one. M4d adds `GET /` and whatever
# shape its static files need; that shape is M4d's decision and is not generalized here.
PRE_AUTH_ROUTES = frozenset({("POST", "/join")})


# ── Origin (A6, D-M4-6) ─────────────────────────────────────────────────────

def _origin_host(origin: str) -> str | None:
    """The ``host:port`` inside an ``Origin``, or None if it is not one.

    Compared against the request's own ``Host``, never against a configured list: a phone
    at the table sends ``Origin: http://<lan-ip>:6081`` and the address varies with the
    network, so an allowlist is a thing that cannot be written down correctly in advance.
    """
    if not origin or origin == "null":
        return None
    scheme, sep, rest = origin.partition("://")
    if not sep or "/" in rest or not rest:
        return None                          # not an origin; treat as absent-and-hostile
    return rest


def _is_pre_auth(request) -> bool:
    """Is this request for one of the routes that runs without a credential (D-M4c-3)?

    Matched against the **registered** route's canonical path, not against
    `request.path`: the router has already decided which handler this is, so asking it
    cannot be fooled by anything a client can put in a URL. An unmatched path resolves to
    a `SystemRoute` with no resource and is therefore never exempt — which also means an
    unknown path still answers 401 rather than 404 to an anonymous caller, and that is the
    pre-existing behaviour, kept.
    """
    resource = getattr(request.match_info.route, "resource", None)
    canonical = getattr(resource, "canonical", None)
    return canonical is not None and (request.method, canonical) in PRE_AUTH_ROUTES


def _same_origin(request) -> bool:
    """D-M4-6, in full: present ⇒ must match `Host`; absent ⇒ allow.

    Absent is allowed because native clients and `curl` send none and a strict deny breaks
    the tooling. That is safe *because* A3 forbids cookies — a credential is a bearer token
    a cross-origin page can neither read nor cause to be sent, so this is defense in depth
    and never the primary CSRF defense.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    host = request.headers.get("Host")
    return bool(host) and _origin_host(origin) == host


# ── Rate limiting (A9's first implementation, D-M4c-5) ──────────────────────

class _JoinLimiter:
    """Failed joins per source address, in a rolling window.

    `POST /join` is the one route with nothing in front of it, so it is where A9's owed
    rate limiting comes due. Scoped to *failures* because the thing being rationed is
    guesses at the join code, not joining.

    `request.remote` is the peer address and **`X-Forwarded-For` is never consulted**:
    A6/A7 put any proxy outside this process, and trusting a header the client writes
    converts this from a per-attacker bucket into a per-attacker-per-forged-header one.
    The documented consequence is that behind a reverse proxy this degrades to a single
    global bucket. M7 revisits it; M4c states it.

    No lock: every caller is a handler on the one net loop.
    """

    def __init__(self, limit: int = JOIN_FAILURE_LIMIT,
                 window: float = JOIN_FAILURE_WINDOW_S) -> None:
        self._limit = limit
        self._window = window
        self._failures: dict[str, collections.deque] = {}

    def allowed(self, addr: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._prune(now)
        return len(self._failures.get(addr, ())) < self._limit

    def record_failure(self, addr: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._failures.setdefault(addr, collections.deque()).append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        """Drop expired hits, and the addresses left with none.

        Pruning every address rather than only the one being asked about is what bounds
        the dict to *currently failing* addresses — otherwise a scan from a rotating
        source leaves an entry per address it ever used.
        """
        cutoff = now - self._window
        for addr in list(self._failures):
            hits = self._failures[addr]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._failures[addr]


# ── The server ──────────────────────────────────────────────────────────────

class PlayerServer:
    """The thread, the middleware, and M4's routes.

    Built and started by the pygame thread; every attribute it then reads is either
    immutable or swapped whole (`set_roster`), because a partially-updated reference is
    the one thing a bare attribute read cannot survive.
    """

    def __init__(self, roster, map_images, commands, build_view, *,
                 host: str = PLAYER_HOST, port: int = PLAYER_PORT) -> None:
        """`commands` and `build_view` are the seam, and both are handed in (D-M4c-1).

        `build_view` is injected rather than imported because `net.view` imports the C++
        extension — importing it here would make the net thread's module require the thing
        NN1 forbids it to touch, which is a contradiction worth not writing down. `net.link`
        supplies it; that module holds a live `App` already and is the half allowed to.
        """
        self._roster = roster
        self._images = map_images
        self._commands = commands
        self._build_view = build_view
        self._joins = _JoinLimiter()
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self.denials = 0          # A9's audit log, in the form M4 actually needs: a count

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self, timeout: float = 5.0) -> None:
        """Start the thread and block until the socket is accepting, or raise.

        Blocking is deliberate: the frozen user procedure prints the URL at startup, and a
        URL printed before the bind is a URL that may never work. Five seconds is a bind,
        not a network round trip.
        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._serve, name="player-server",
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError(f"player server did not bind {self._host}:{self._port}")
        if self._error is not None:
            raise self._error

    def stop(self, timeout: float = 5.0) -> None:
        """Stop accepting and join the thread. Safe to call twice, and on a failed start."""
        loop, thread = self._loop, self._thread
        self._thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout)
        self._loop = None

    def set_roster(self, roster) -> None:
        """Re-point at the roster a new encounter loaded.

        `_set_encounter_base` **replaces** `App.roster` rather than mutating it, so without
        this the server would authenticate against the previous table forever. One
        attribute store, which is atomic; a request in flight uses one roster or the other
        and never a mixture.

        Note for M6: the new roster generates a new in-memory signing key, so every
        credential minted against the old one stops verifying. Loading a different
        encounter is a re-join for everybody, which is R3's case arriving early.
        """
        self._roster = roster

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        """The address to read out at the table (user procedure, step 2)."""
        return f"http://{_lan_ip()}:{self._port}/"

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        runner = None
        try:
            runner = web.AppRunner(self._build(), access_log=None)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, self._host, self._port)
            loop.run_until_complete(site.start())
            self._runner = runner
        except BaseException as exc:          # a taken port is the realistic one
            self._error = exc
            self._ready.set()
            loop.close()
            self._loop = None
            return
        self._ready.set()
        try:
            loop.run_forever()                # F6/D-M4-5: never web.run_app
        finally:
            try:
                loop.run_until_complete(runner.cleanup())
            finally:
                loop.close()

    # ── The one middleware point (A9) ───────────────────────────────────────

    def _build(self) -> web.Application:
        app = web.Application(middlewares=[self._authenticate])
        app.router.add_get("/map.png", self._map_png)
        app.router.add_post("/join", self._join)
        app.router.add_get("/state", self._state)
        return app

    @web.middleware
    async def _authenticate(self, request, handler):
        """Steps 1-5 of the frozen request order (A6 → A5 → A3), for every route alike.

        Step 6 — `authorize()` — is the only step a route parameterizes, so it is not here.
        M8 replaces steps 2-5 inside this one function and touches nothing else.

        `POST /join` is the one pre-auth route (it is what *mints* a credential), and its
        exemption is narrower than skipping this function (D-M4c-3): **it suppresses the
        401 and nothing else.** The `Origin` check still runs, because a cross-origin page
        that can mint principals is a defacement vector even though A3 stops it reading the
        response. And `verify_credential` still runs, because its answer *is* D-M4-4's step
        1 — "a live, unrevoked credential re-attaches to its own principal" is exactly what
        a successful verification of this request's own header says. So an exempt route
        reads `request["principal"]` where `None` means *not authenticated* rather than
        *denied*, and it may not call `_authorize()`; `authorize()` enforces the other half
        by denying a `None` principal everything, without exception.
        """
        if not _same_origin(request):
            self.denials += 1
            return web.Response(status=403, text="origin")

        credential = ""
        header = request.headers.get("Authorization", "")
        scheme, _, rest = header.partition(" ")
        if scheme.lower() == "bearer":
            credential = rest.strip()

        # verify_credential is steps 3, 4 and 5 in one call — signature, expiry, the
        # revocation list (A5, which runs even while empty), then the principal id. It
        # returns None on any of them, and the caller never learns which.
        principal = self._roster.verify_credential(credential) if credential else None
        if principal is None and not _is_pre_auth(request):
            self.denials += 1
            return web.Response(status=401, text="unauthenticated",
                                headers={"WWW-Authenticate": "Bearer"})

        request["principal"] = principal
        return await handler(request)

    def _authorize(self, request, action: Action, target=None) -> bool:
        """NN6's chokepoint, reached through the one helper so no route grows its own."""
        ok = self._roster.authorize(request["principal"], action, target)
        if not ok:
            self.denials += 1
        return ok

    # ── GET /map.png (D-M4-1) ───────────────────────────────────────────────

    async def _map_png(self, request):
        """The page image, masked for a player and verbatim for the DM.

        Which of the two is a **policy** question, so it is asked of `authorize()` and not
        of `Role`: `VIEW_DM_CHANNEL` is the entitlement whose description is literally
        "whole map" (A8 — no `if viewer == "dm"` branches anywhere).

        `?v=` is not read. The cache always serves the newest published mask, which can
        only ever reveal cells the party has already earned; honouring an older `?v=` would
        mean retaining every mask a client might still be holding, to show it *more* fog
        than it is entitled to. So the query string is a cache-buster for the client's
        benefit, and the **ETag is the key actually served** — which is what makes a
        conditional request correct even when the two disagree.
        """
        if not self._authorize(request, Action.VIEW_SESSION):
            return web.Response(status=403, text="forbidden")
        is_dm = self._authorize(request, Action.VIEW_DM_CHANNEL)

        # Up to 95 ms of PNG encode on the largest page in the tree. Off the loop, or one
        # player's fetch stalls every other player's socket — and, from M4b, the pushes.
        got = await asyncio.get_running_loop().run_in_executor(
            None, self._images.png, is_dm)
        if got is None:
            # Nothing published: no page loaded, or the frame tick has not run a push
            # cycle yet. A 404 is the honest answer and the client retries on its next view.
            return web.Response(status=404, text="no page published")

        key, data = got
        etag = f'"{key}"'
        if _etag_matches(request.headers.get("If-None-Match"), etag):
            # The whole point of the 3 s key lag: a re-key costs a player 0.8-2.5 MB, and
            # between re-keys this is what they pay instead.
            return web.Response(status=304, headers={"ETag": etag,
                                                     "Cache-Control": _CACHE_CONTROL})
        return web.Response(body=data, content_type="image/png",
                            headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL})

    # ── POST /join (Envelope 1, D-M4-4 as amended, D-M4c-3/4/5) ─────────────

    async def _join(self, request):
        """The one pre-auth route: a join code in, a bearer credential out (A3).

        Never a cookie, and never an identity — the code is an *invite* that mints a
        credential, which is why one table-wide code is safe (A2): each join resolves to a
        distinct principal and the DM can reassign every seat (NN4).
        """
        try:
            body = await request.json()
        except Exception:
            return _auth_error(400, "protocol")
        if (not isinstance(body, dict) or body.get("v") != PROTOCOL_VERSION
                or body.get("t") != "auth"):
            return _auth_error(400, "protocol")

        # The address, before the code is even looked at: a guesser must not be able to
        # spend a bucket-free attempt by sending a malformed body, and a well-formed one
        # must not be cheaper than a wrong code.
        addr = request.remote or "?"
        if not self._joins.allowed(addr):
            self.denials += 1
            return _auth_error(429, "denied")

        roster = self._roster
        if not roster.check_join_code(str(body.get("join_code") or "")):
            self._joins.record_failure(addr)
            self.denials += 1
            return _auth_error(403, "denied")

        principal = self._claim_seat(roster, request["principal"], body)
        credential = roster.mint_credential(principal.id)
        if credential is None:
            # The seat went away between the match and the mint — the DM unseated them in
            # that window. Indistinguishable from a bad code on the wire, deliberately.
            return _auth_error(403, "denied")

        return web.json_response(status=202, data={
            "v": PROTOCOL_VERSION,
            "t": "auth",
            "ok": True,
            "credential": credential,
            "principal": {"id": principal.id,
                          "display_name": principal.display_name,
                          # A label the client picks a layout with, never a permission —
                          # Envelope 1 says so, and every real decision was already made
                          # server-side by authorize(). Serialized, never branched on (A8).
                          "role": principal.role.value},
            # Answerable here rather than on the frame tick precisely because `TokenInfo`
            # exists so ownership can be (Step 0.4). A seated player owning zero tokens is
            # a spectator, which is legal and is what `false` means.
            "seated": bool(roster.controlled_by(principal.id)),
            # 0 until `EventStream` (seam S3) exists. D-M3-1 froze the caller as the
            # supplier of `seq`, and M4c has nothing to supply.
            "server_seq": 0,
        }, headers={"Cache-Control": "no-store"})

    def _claim_seat(self, roster, authenticated, body):
        """D-M4-4, as amended 2026-09-24. The order is the whole decision.

        1. A live credential re-attaches to **its own principal**. Names are not consulted,
           and neither is the body: this is the holder proving which seat is theirs.
        2. An explicit `principal_id` claims that seat — R3's case, where the process
           restarted and took every credential with it — but only if it names an existing
           **player**. The DM's seat is not claimable with a join code: R2 accepts that a
           code-holder can claim to be Kira, not that they can become the DM.
        3. Otherwise `display_name`, case-insensitively, against player principals.
        4. Otherwise a new seat.

        An id that names nothing falls through to 3 rather than failing, because an error
        distinguishing "no such seat" from "not your seat" is an oracle for which ids
        exist, and Step 0.5's `error` set is closed for exactly that reason.

        **Nothing here renames anything it matches** (D-M4c-4). Accepting the body's
        `display_name` as an update is the obvious implementation, and through path 2 it
        hands anyone holding the join code the ability to relabel a seat they otherwise
        never touched. Renaming is the DM's (NN4). `display_name` is a matching hint, which
        is all "never a key" (`roster.py:73`) has ever allowed it to be.

        `Role` is never read here: `players()` is the roster answering the same question
        through its own vocabulary, which is what A8 asks for.
        """
        if authenticated is not None:
            return authenticated                                        # 1

        players = {p.id: p for p in roster.players()}

        wanted = str(body.get("principal_id") or "").strip()
        if wanted in players:
            return players[wanted]                                      # 2

        name = str(body.get("display_name") or "").strip()
        if name:
            folded = name.casefold()
            for player in players.values():
                if player.display_name.casefold() == folded:
                    return player                                       # 3

        # An empty name is the roster's fallback to make, not this route's: it substitutes
        # the opaque id, so the DM sees an unnamed seat rather than a second "Player".
        return roster.add_principal(name)                               # 4

    # ── GET /state (Envelope 2, D-M4c-1 / D-M4c-2) ──────────────────────────

    async def _state(self, request):
        """The caller's whole view, built on the frame tick because it has to be.

        `build_view` reads the `BattleMap`, so NN1 forbids this thread from calling it.
        The command runs on the pygame thread and hands back a dict it built fresh; the
        JSON encoding happens here, which is the same division `GET /map.png` makes when
        it runs the PNG encode in an executor. The frame tick pays for the projection and
        never for the transport.
        """
        if not self._authorize(request, Action.VIEW_SESSION):
            return web.Response(status=403, text="forbidden")
        viewer = request["principal"]

        try:
            view = await asyncio.wait_for(
                self._commands.submit(lambda app: self._build_view(app, viewer)),
                STATE_TIMEOUT_S)
        except asyncio.TimeoutError:
            # The frame loop is not pumping — a DM modal is open (until M4d puts
            # `_pump_net()` in the six of them), or the app is wedged. F1: a hung request
            # is strictly better than a silent stall, and this is the bounded form of it.
            # Envelope 2 has no error shape and is not given one; `"timeout"` in Step 0.5
            # belongs to `submit_ack`, and inventing a second `view` shape would put an
            # untested variant beside the one envelope with a byte-level test.
            return web.Response(status=503, text="timeout",
                                headers={"Retry-After": "1"})
        except PermissionError:
            # `build_view` raises it for a viewer who may not receive a view at all — a
            # seat pulled between the middleware and the pump. A flow, not a bug, once
            # there are two threads.
            self.denials += 1
            return web.Response(status=403, text="forbidden")

        # A view is per-viewer live state that changes every tick. The conditional-request
        # machinery `GET /map.png` earned is exactly wrong here, where nothing repeats.
        return web.json_response(view, headers={"Cache-Control": "no-store"})


def _auth_error(status: int, error: str):
    """Envelope 1's failure shape — one shape for every failure, deliberately.

    It never says *which* check failed and never echoes anything the client sent. The
    reason lives in A9's audit log, exactly as Step 0.4 decided for `authorize()`'s bool.
    """
    return web.json_response(status=status, data={"v": PROTOCOL_VERSION, "t": "auth",
                                                  "ok": False, "error": error},
                             headers={"Cache-Control": "no-store"})


# `no-cache` means "revalidate", not "do not store" — the client keeps the bytes and
# spends one conditional request to learn they are still current. `immutable` would be
# wrong however tempting the `?v=` makes it look: the same URL serves whatever mask is
# newest, so its body genuinely changes. `private` because a masked page is scoped to the
# party and the DM's copy is not scoped at all.
_CACHE_CONTROL = "private, no-cache"


def _etag_matches(header: str | None, etag: str) -> bool:
    """RFC 9110 `If-None-Match`: a list, and possibly weak. `*` matches anything we hold."""
    if not header:
        return False
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return True
    return False


# run.sh sets this to the HOST's LAN address before it starts the container.
ADVERTISE_ENV = "PLAYER_ADVERTISE_HOST"


def _lan_ip() -> str:
    """The address a phone on the same wifi can reach.

    **Inside the container, this process cannot work that out.** The routing-table trick
    below answers correctly for a bare `python gui/main.py`, but under Docker it returns
    the bridge address — `172.17.0.2` — which is reachable from nothing a player owns. The
    port is *published* to the host (`-p 6081:6081`), so the address to read out at the
    table belongs to the host, and only the host knows it. `run.sh` measures it and passes
    it in; this prefers it whenever it is set.

    This matters more than it looks: the frozen user procedure is *read the URL printed at
    startup and give it to your players*, so a URL that only resolves inside the container
    does not make the procedure longer — it makes it wrong.
    """
    advertised = os.environ.get(ADVERTISE_ENV, "").strip()
    if advertised:
        return advertised
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))      # unroutable: picks an interface, sends nothing
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
