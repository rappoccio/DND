"""The seam between the running `App` and the transport (MULTIPLAYER_PLAN.md M4/M4c).

Three entry points, all of which run on the **pygame thread** and all of which read a
live `App` — so they belong here for the same reason `view.py` does, and for the opposite
reason `server.py` does not. `server.py` is the net thread's half and may hold no `App` at
all (NN1); this is the frame tick's half, and holding one is its whole job.

It lives in `net/` rather than in `main.py` because NN3 says so — new subsystems go in new
modules, and `main.py`'s net line count trends down. What stays in `main.py` is the
rewiring these are called from: one line in `run()`, two in the frame loop, one on the way
out, and the attributes themselves.

This module imports no `aiohttp`. `net.server` does, at module scope, and the guarded
import here is D1's soft dependency: an absent module is a printed line and `app._net`
stays `None`, which is also the state every headless suite runs in.

It is also the module that hands `net.view.build_view` to the server (M4c). `server.py`
cannot import it — `net.view` imports the C++ extension, and a net-thread module that
requires the thing NN1 forbids it to touch is a contradiction. This half already holds a
live `App`, so holding the function that reads one costs it nothing.
"""

from __future__ import annotations

import pygame

from net import commands, events as net_events, submit as net_submit, view as net_view
from net.roster import PROTOCOL_VERSION


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
    server = PlayerServer(app.roster, app.map_images,
                          app._net_commands, view_at_seq,
                          submits=app._net_submits,
                          handle_submit=net_submit.handle_submit,
                          build_live=build_live,
                          events_since=events_since,
                          sprite_for=net_view.sprite_file)
    try:
        server.start()
    except Exception as exc:                       # a taken 6081 is the realistic one
        print(f"[net] player server did not start: {exc}")
        return
    app._net = server
    app.submit_log.path = net_submit.SUBMIT_LOG_PATH     # D-M5-6a: a table exists, so log
    print(f"[net] players join at {server.url}")
    print(f"[net] join code: {app.roster.join_code}")


def pump_commands(app, budget: int = commands.DEFAULT_BUDGET) -> int:
    """Run what the net thread has queued, on the frame tick (D-M4c-1).

    The queue exists whether or not a transport does, so this is unconditional and needs
    no `_net` guard: a headless suite with no `aiohttp` simply pumps an empty deque, which
    is one `popleft` raising `IndexError`.

    **This is what D-M4-3's `_pump_net()` pumps, and it is deliberately all it pumps.**
    Nothing here redraws. Pumping inside a blocking modal means a DM authoring modal stops
    being a quiescent point — state can advance while *Generate Dungeon* is open — and F3
    found that acceptable only for work that does not also touch the screen the modal owns.
    The six call sites are M4d's; this function is M4c's, and the split is exactly that
    line.
    """
    return app._net_commands.pump(app, budget)


def pump_submits(app, budget: int = commands.DEFAULT_BUDGET) -> int:
    """Decide the queued `submit`s, from `run()` only (M5a, `net.submit`).

    Not from `_pump_net()`, and not under its reentrancy guard. A submit is input: its
    callback is whatever the DM's click would run, and a click may open a modal, which
    D-M4d-4 forbids a command to do. So this sits in the frame loop beside
    `_handle_events`, and a blocking modal holds submits back rather than running them
    underneath itself.

    **The reaction deadline expires here too (D-M5-7), after the queue is drained.** Expiry
    runs a Skip, which is input in the same sense, so it needs the same quiet point and is
    held back by the same modals. Draining first means a submit that reached the queue
    before this frame wins over the deadline: the player who answered in time is not
    skipped because the frame tick was late.
    """
    done = app._net_submits.pump(app, budget)
    app.prompts.expire()
    return done


def _projection(app, viewer) -> net_events.Projection:
    """``viewer``'s event stream, filtered up to now (M4b.1's ``project``).

    Every ``seq`` that leaves the process is read after this, so a view never carries a
    ``seq`` older than the state it shows. Without it, the events after that ``seq`` would
    replay, on the client, moves the view already shows as done.
    """
    return app.events.project(viewer.id, lambda: net_view.sight(app, viewer))


def view_at_seq(app, viewer) -> dict:
    """``GET /state``'s answer: the view, at this principal's ``seq`` (B-3)."""
    return net_view.build_view(app, viewer, _projection(app, viewer).seq)


def build_live(app, viewer, socket_id: str | None = None) -> list[dict]:
    """What one socket is sent per cycle: its events, its `view`, then its prompt.

    **Events (M4b.2, B-3).** With a ``socket_id``, the `events` frame carries everything
    from that socket's cursor, which only ``ack`` advances. A send that was dropped is
    therefore sent again, whole, on the next cycle. A cursor that fell off the 512-event
    ring is re-attached at the head, and the `view` in the same cycle is the resync. With
    no ``socket_id``, as for the connect-time resync, there is no `events` frame: a
    newcomer starts from a view.

    `view.seq` is the principal's ``seq``, so the view and the `events` frame end at the
    same number.

    **The prompt** goes out **only when `you.prompt_id` names it**, and that id has already
    passed the `ANSWER_PROMPT` gate in `net.view._you` (D-M3-6). So the prompt body goes
    out behind the same check as its id, and a prompt the viewer may not answer is never
    sent, not even greyed out (F-M5-6). It is re-sent on every cycle while live. A client
    keys it by id, so a repeat costs a few hundred bytes and a dropped push cannot lose it.

    Built fresh on every call, so what crosses the seam is owned by the net thread
    (`CommandQueue` rule 3).
    """
    projection = _projection(app, viewer)
    frames = []
    if socket_id is not None:
        try:
            events = projection.socket_frame(socket_id)
        except net_events.Resync:
            projection.attach(socket_id)
            events = None
        if events is not None:
            frames.append(events)
    view = net_view.build_view(app, viewer, projection.seq)
    frames.append(view)
    prompt_id = view["you"]["prompt_id"]
    if prompt_id is not None:
        prompt = app.prompts.get(prompt_id)
        if prompt is not None and prompt.is_live:
            frames.append(prompt.to_wire(seq=view["seq"]))
    return frames


def events_since(app, viewer, since: int) -> dict:
    """`GET /events?since=`'s answer (B-3): an `events` frame from the ring, or a `view`.

    A ``since`` the ring cannot answer (older than its 512 events, ahead of the stream, or
    negative) gets a fresh `view` at the current ``seq`` instead. That is the resync
    contract M6 builds on: the client replaces its board and carries on from `view.seq`.
    Nothing new is an `events` frame with an empty list, so the answer's kind says only
    whether to resync.
    """
    projection = _projection(app, viewer)
    try:
        frame = projection.frame(since)
    except net_events.Resync:
        return net_view.build_view(app, viewer, projection.seq)
    if frame is None:
        frame = {"v": PROTOCOL_VERSION, "t": "events", "since": int(since),
                 "seq": projection.seq, "events": []}
    return frame


def push_cycle(app) -> None:
    """One push cycle, on the frame tick — the pygame half of the handoff (D-M4-2).

    Coalesced at `view.PUSH_INTERVAL_MS`, and forced at a turn boundary. The boundary is
    detected by comparing `(combat_active, round_num, turn_idx)` rather than by a hook in
    the turn machinery, because that tuple is already the whole answer and a hook is a
    thing that can be forgotten at the one call site that matters.

    Since M4e the cycle carries two things on that one cadence: the page image, which is
    party-scoped and published for whoever asks, and one `view` per connected socket, which
    is per-viewer and can only be built here. Called after `_refresh_fog` on purpose, so the
    mask published here is the one that frame draws.

    Since M4b.2 the boundary is also an event: `turn`, appended before anyone is projected,
    so it lands after the moves and flashes of the turn that just ended. Not on the first
    cycle, whose "boundary" is only the server starting.
    """
    if app._net is None:
        return
    now = pygame.time.get_ticks()
    turn = (app.combat_active, app.round_num, app.turn_idx)
    boundary = turn != app._net_turn
    if not boundary and (now - app._net_push_ms) < net_view.PUSH_INTERVAL_MS:
        return
    if boundary and app._net_turn is not None:
        app.events.append(net_events.turn(app.round_num, app.turn_idx, _turn_agent(app)))
    app._net_turn = turn
    app._net_push_ms = now
    # publish() decides whether the new snapshot actually replaces the published one: the
    # image key lags 3 s, but only while the lag is nothing worse than extra fog (D-M4-1).
    app.map_images.publish(net_view.page_image(app), boundary=boundary)
    _project_seated(app)
    _push_views(app)


def _turn_agent(app) -> int | None:
    """Whose turn it is, as an agent index, or ``None`` out of combat.

    The same reading as `net.view._combat`'s ``turn_agent``, before the filter: `visible`
    nulls it for a viewer who cannot see that creature."""
    if app.combat_active and 0 <= app.turn_idx < len(app.initiative_order):
        return int(app.initiative_order[app.turn_idx].agent_idx)
    return None


def _project_seated(app) -> None:
    """Project every **seated** principal's stream, connected or not (M4b.2).

    The user's decision, 2026-10-17: "Keep updating their stream". A player whose phone
    dropped off the wifi keeps a ``seq`` that moves, so a reconnect within the 512-event
    ring resumes from it (M6) instead of starting over from a view. The cost is one
    ``sight()`` board walk per principal, and only on a cycle with new events.

    A stream goes only when its seat does (``retain``), never on a disconnect. A socket's
    cursor goes when the socket does, and "the socket" means every connection the net loop
    still holds, including one mid-send: ``live_viewers()`` leaves that one out, and
    detaching it there would lose the events its next cycle has to re-send.
    """
    seated = app.roster.principals
    app.events.retain(p.id for p in seated)
    for principal in seated:
        _projection(app, principal)
    app.events.detach_gone(app._net.live_ids())


def _push_views(app) -> None:
    """One `view` per connected socket, built here because a view can only be built here.

    D-M4e-4's reverse handoff, on this side of it: read the snapshot the net loop published,
    build what it asked for, hand it back. One view per **connected socket** and not per
    seated principal — which is the arithmetic D-M4c-1 rejected for `GET /state` ("builds N
    views per cycle whether or not anyone is listening"), correct here for the reason that
    rejection turned on: a socket *is* a listener. With nobody connected this is one
    attribute read per frame and no view built at all. (The event streams are projected
    regardless, in `_project_seated`, and that costs a board walk only when there is
    something new.)

    Two sockets held by the same principal get two views rather than one shared object,
    because the thing being sent is per-connection state on the far side and `CommandQueue`'s
    rule 3 applies whoever the viewer is.

    **The credential is re-verified per viewer per cycle**, which is where A5's "the check
    runs on every request" lands on a connection that is one request an hour long: a revoked
    credential, or a seat the DM pulled, stops the next push and closes the socket instead of
    waiting for the player to reconnect. `verify_credential` is a signature, an expiry, the
    revoked set and a dict lookup — cheap enough to pay 4 times a second per player, and the
    roster is the one object both threads are allowed to read.

    **The cursor (M4b.2, B-3).** A socket's projection cursor is attached the first cycle
    the socket appears. If the net loop has already sent it a view (the connect-time
    resync usually lands first), the cursor starts at that view's `seq`, so what happened
    since plays. Otherwise it starts at the head, and this cycle's `view` shows the past.
    From then on it moves only by ``ack``, to the ``sent_seq`` the net loop published after a
    send that succeeded. A send that failed or was dropped published nothing, so the next
    cycle's `events` frame starts from the same place.
    """
    viewers = app._net.live_viewers()
    if not viewers:
        return
    views = {}
    for viewer in viewers:
        if app.roster.verify_credential(viewer.credential) is None:
            app._net.drop_viewer(viewer.id)
            continue
        projection = app.events.projection(viewer.principal.id)
        if projection.sent(viewer.id) is None:
            projection.attach(viewer.id, viewer.sent_seq)
        elif viewer.sent_seq is not None:
            projection.ack(viewer.id, viewer.sent_seq)
        try:
            views[viewer.id] = build_live(app, viewer.principal, viewer.id)
        except PermissionError:
            # A seat that went away between the snapshot and this build. The check above
            # catches it properly on the next cycle; this frame simply has nothing to send.
            continue
    app._net.push_views(views)
