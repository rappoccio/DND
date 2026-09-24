"""The player-facing HTTP server (MULTIPLAYER_PLAN.md M4).

One `aiohttp` application on an asyncio loop of its own, on a thread of its own, inside
the pygame process. This module is the **transport skeleton**: the thread, the single
middleware point A9 requires, and `GET /map.png`. `POST /join`, `GET /state`, `WS /live`
and the client land on top of it and add no new machinery — that is what makes it a
skeleton rather than a first draft.

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

Named honestly: the roster is *mutated* on the pygame thread (`sync_tokens`,
`add_principal`) while this thread reads it. No read here can tear — these are dict and
dataclass reads under the GIL, not C++ invariants mid-mutation, which is the distinction
NN1's tightening draws. What a request can see is a *stale* ownership answer, for the one
frame between a `Controller ▸` reassignment and the next `sync_tokens`. That is a
liveness cost, not a safety one, and it is the same window the DM's own screen has.

**F6, tested rather than assumed**: `web.run_app` installs signal handlers and dies off the
main thread with `set_wakeup_fd only works in main thread of the main interpreter`. The
runner form is not a style preference (D-M4-5).

`aiohttp` is imported at module scope on purpose, so `main.py`'s guarded import either
gets a working server or gets `ImportError` and says so once (D1/F7). There is no
half-initialized middle state.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading

from aiohttp import web

from .roster import Action

# D2: the player port, and the only one that ever faces the LAN. 6080 is the DM console
# and is bound to loopback in run.sh / interactive.sh (S2, A10) — these are two trust
# domains and the port numbers are where that becomes a fact.
PLAYER_PORT = 6081
PLAYER_HOST = "0.0.0.0"       # A6/A7: listens plain on the LAN; TLS is a proxy's job


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


# ── The server ──────────────────────────────────────────────────────────────

class PlayerServer:
    """The thread, the middleware, and M4's routes.

    Built and started by the pygame thread; every attribute it then reads is either
    immutable or swapped whole (`set_roster`), because a partially-updated reference is
    the one thing a bare attribute read cannot survive.
    """

    def __init__(self, roster, map_images, *,
                 host: str = PLAYER_HOST, port: int = PLAYER_PORT) -> None:
        self._roster = roster
        self._images = map_images
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
        return app

    @web.middleware
    async def _authenticate(self, request, handler):
        """Steps 1-5 of the frozen request order (A6 → A5 → A3), for every route alike.

        Step 6 — `authorize()` — is the only step a route parameterizes, so it is not here.
        M8 replaces steps 2-5 inside this one function and touches nothing else.

        `POST /join` will be the one pre-auth route (it is what *mints* a credential) and
        earns an exemption when it lands. Until then there is nothing to exempt, and an
        exemption list with no members is a hole waiting for a typo.
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
        if principal is None:
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
