"""The seam between the running `App` and the transport (MULTIPLAYER_PLAN.md M4).

Two functions, both of which run on the **pygame thread** and both of which read a live
`App` — so they belong here for the same reason `view.py` does, and for the opposite
reason `server.py` does not. `server.py` is the net thread's half and may hold no `App` at
all (NN1); this is the frame tick's half, and holding one is its whole job.

It lives in `net/` rather than in `main.py` because NN3 says so — new subsystems go in new
modules, and `main.py`'s net line count trends down. What stays in `main.py` is the
rewiring these two are called from: one line in `run()`, one in the frame loop, one on the
way out, and the attributes themselves.

This module imports no `aiohttp`. `net.server` does, at module scope, and the guarded
import here is D1's soft dependency: an absent module is a printed line and `app._net`
stays `None`, which is also the state every headless suite runs in.
"""

from __future__ import annotations

import pygame

from net import view as net_view


def start_player_server(app) -> None:
    """Stand the transport up, or say once why there is none (D1/F7).

    Called from `run()`, never from `__init__`: a constructed `App` must not bind a port.
    Every headless suite in `tests/` builds an `App` and never runs one, and a constructor
    that binds 6081 makes two of them a port conflict — which is what the first run of
    `test_mapserver.py` reported, four times over.

    `run()` is also where the frozen user procedure wants the printing to happen: step 2 is
    *read the join code and URL printed at startup*, and startup is a running app.
    """
    try:
        from net.server import PlayerServer
    except ImportError as exc:
        print(f"[net] player server unavailable: {exc}")
        return
    server = PlayerServer(app.roster, app.map_images)
    try:
        server.start()
    except Exception as exc:                       # a taken 6081 is the realistic one
        print(f"[net] player server did not start: {exc}")
        return
    app._net = server
    print(f"[net] players join at {server.url}")
    print(f"[net] join code: {app.roster.join_code}")


def push_cycle(app) -> None:
    """One push cycle, on the frame tick — the pygame half of the handoff (D-M4-2).

    Coalesced at `view.PUSH_INTERVAL_MS`, and forced at a turn boundary. The boundary is
    detected by comparing `(combat_active, round_num, turn_idx)` rather than by a hook in
    the turn machinery, because that tuple is already the whole answer and a hook is a
    thing that can be forgotten at the one call site that matters.

    In M4 the cycle carries the page image and nothing else; the `view` snapshot joins it
    when the socket does, on this same cadence and this same boundary. Called after
    `_refresh_fog` on purpose, so the mask published here is the one that frame draws.
    """
    if app._net is None:
        return
    now = pygame.time.get_ticks()
    turn = (app.combat_active, app.round_num, app.turn_idx)
    boundary = turn != app._net_turn
    if not boundary and (now - app._net_push_ms) < net_view.PUSH_INTERVAL_MS:
        return
    app._net_turn = turn
    app._net_push_ms = now
    # publish() decides whether the new snapshot actually replaces the published one: the
    # image key lags 3 s, but only while the lag is nothing worse than extra fog (D-M4-1).
    app.map_images.publish(net_view.page_image(app), boundary=boundary)
