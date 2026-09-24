#!/usr/bin/env python3
"""`_pump_net()` in the six blocking modals (MULTIPLAYER_PLAN.md M4d, D-M4-3/D-M4d-1..4).

`App.run()` is not the only event loop. Six methods run their own blocking `while True:` +
`pygame.event.get()`, and while any of them is open `run()` is stalled, the command queue
never drains, and `GET /state` parks for the full five seconds before answering 503.
`test_state.py::test_a_wedged_frame_loop_is_a_503` is that behaviour, tested on purpose —
it is D-M4c-2's deliberate wrong answer, and it stays green, because a wedged frame loop is
still a 503. What M4d changes is how often the loop is wedged.

So the headline check here is an end-to-end one: a real socket, a real modal open on this
thread, and a `200` where `main` answered `503` one commit ago.

The rest guard the three ways the one-line fix goes wrong:

  · the pump under an event drain (a queued QUIT would return before it ever ran),
  · a seventh modal added later without one,
  · a command that opens a modal, which re-enters `pygame.event.get()` at a depth the
    outer loop does not know about.

The last is D-M4d-4, and it is enforced rather than documented: `_pump_net` refuses to
reenter. Without that, the "test" could only assert that nobody had done it yet.

Every modal is driven by posting `pygame.QUIT` **before** entering it. That is not a
convenience — it is the placement assertion. The loop body is pump → drain → render, so a
QUIT already sitting in the queue returns out of the loop on the first drain; a command
that nevertheless ran is a command the pump reached first.

  · all six modals drain the queue                       (test_every_blocking_modal_pumps)
  · the pump sits above the event drain                  (test_the_pump_is_above_the_event_drain)
  · ...and without it the queue is stranded              (test_a_modal_without_the_pump_strands_the_queue)
  · every event-draining modal loop has one              (test_every_event_draining_loop_has_a_pump)
  · a view crosses while a modal is open, as a 200       (test_state_during_a_modal_is_answered)
  · the pump draws nothing                               (test_the_pump_draws_nothing)
  · a command may not open a modal                       (test_a_command_that_opens_a_modal_is_refused)
  · ...and refusing it does not kill the frame loop      (test_the_refusal_rides_the_future)
  · the guard clears, so one refusal is not permanent    (test_the_guard_clears_after_a_refusal)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import ast
import asyncio
import json
import threading
import time

import pygame

from dungeon import Dungeon, MapPage

from test_mapserver import _server


# ─────────────────────────────────────────────────────────────────────────────
#  Driving a blocking modal from a test
# ─────────────────────────────────────────────────────────────────────────────

def _dungeon(app):
    """The one page `_modal_dungeon_pages` needs to be enterable at all.

    Its caller guards on `self.dungeon is None` (`main.py:2794`) and the modal itself
    dereferences it immediately, so this is the modal's precondition rather than scene
    dressing.
    """
    page = MapPage(id="p1", png="p1.png", encounter_base="p1", origin=[0, 0, 0],
                   cols=int(app.bm.grid_cols or 12), rows=int(app.bm.grid_rows or 12))
    app.dungeon = Dungeon(pages=[page], entry_page_id=page.id)
    app.dungeon_page = page


def _modals(app):
    """The six, each as a zero-argument call. The table Step 0.11 verified, executable.

    `_modal_message` is listed with one line of text; `_modal_select_items` with one item
    and an empty selection. Neither shape matters — what is under test is the loop, and
    every one of these returns on the QUIT that is already queued when it starts.
    """
    _dungeon(app)
    return {
        "_modal_dungeon_pages":    app._modal_dungeon_pages,
        "_modal_text_prompt":      lambda: app._modal_text_prompt("t", "p"),
        "_modal_message":          lambda: app._modal_message(["hello"]),
        "_modal_generate_terrain": app._modal_generate_terrain,
        "_modal_select_items":     lambda: app._modal_select_items("t", ["one"], set()),
        "_modal_generate_dungeon": app._modal_generate_dungeon,
    }


def _run_modal(open_modal):
    """Open a modal with a QUIT already queued, so it runs exactly one iteration.

    One iteration is the whole point: the pump is the first statement of the body, so a
    modal that returns on its first drain has still pumped exactly once. A modal that
    pumped *after* draining would return having pumped zero times, which is the mutant
    every check in this file is arranged to catch.
    """
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    try:
        open_modal()
    finally:
        pygame.event.clear()


def _quit_queued():
    """A QUIT waiting in the queue, so a modal that *does* open closes on its first drain.

    Only the mutant path ever reaches it: with the D-M4d-4 guard in place the nested loop
    raises on its first line and never drains anything. It is here so that removing the
    guard makes this suite **fail** rather than **hang** — measured, not assumed: the first
    version of these three checks spun forever under that mutant, and a suite that hangs in
    `run_all_tests.py` is a worse regression than the one it was written to catch.
    """
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def _submit(s, fn, timeout=5.0):
    """Queue a command the way a handler does — on the net loop, from this thread.

    `CommandQueue.submit` calls `asyncio.get_running_loop()`, so it may only be called
    from inside the loop that will own the future. This is the shortest honest way to be
    there without standing up a route.

    It returns only once the command is **on the deque**, because scheduling a coroutine
    onto another loop is not the same as it having run: without the wait, a modal can
    complete its single iteration before the net loop has submitted anything, and the
    check that follows measures the scheduler rather than the pump.
    """
    async def _await_it():
        return await s.app._net_commands.submit(fn)

    before = s.app._net_commands.pending
    future = asyncio.run_coroutine_threadsafe(_await_it(), s.srv._loop)
    deadline = time.monotonic() + timeout
    while s.app._net_commands.pending <= before and time.monotonic() < deadline:
        time.sleep(0.001)
    assert s.app._net_commands.pending > before, "the command never reached the queue"
    return future


# ─────────────────────────────────────────────────────────────────────────────
#  The six sites
# ─────────────────────────────────────────────────────────────────────────────

def test_every_blocking_modal_pumps():
    """Each of the six drains the queue, on its first iteration, before it returns."""
    with _server(pump=False) as s:
        for name, open_modal in _modals(s.app).items():
            ran = []
            future = _submit(s, lambda app, _r=ran: _r.append(True) or "done")
            # Queued, with nothing pumping: `run()` is not looping in this test.
            assert s.app._net_commands.pending == 1, f"{name}: the command was not queued"
            _run_modal(open_modal)
            assert ran, f"{name} returned without draining the command queue"
            assert future.result(2.0) == "done", f"{name} ran the command but lost the answer"
    print("✅ test_every_blocking_modal_pumps")


def test_the_pump_is_above_the_event_drain():
    """Order, asserted directly rather than inferred from the QUIT trick.

    `pygame.event.get` is wrapped so the two are recorded in the order they happen. If the
    pump sat below the drain, a modal that returns on its first QUIT would record the
    drain alone — which is exactly what `main` did before M4d, and what a careless merge
    would restore.
    """
    with _server(pump=False) as s:
        order = []
        real_get, real_pump = pygame.event.get, type(s.app)._pump_net

        def spy_get(*a, **kw):
            order.append("drain")
            return real_get(*a, **kw)

        def spy_pump(self):
            order.append("pump")
            return real_pump(self)

        pygame.event.get = spy_get
        type(s.app)._pump_net = spy_pump
        try:
            _run_modal(lambda: s.app._modal_message(["hello"]))
        finally:
            pygame.event.get = real_get
            type(s.app)._pump_net = real_pump

        assert order[:2] == ["pump", "drain"], \
            f"the modal's first two acts were {order[:2]}, not a pump then a drain"
    print("✅ test_the_pump_is_above_the_event_drain")


def test_a_modal_without_the_pump_strands_the_queue():
    """The mutant: remove the pump and the command is still sitting there afterwards.

    Written as a check rather than left to inspection because it is the only thing that
    makes the one above mean anything — a queue that would have drained by itself proves
    nothing about who drained it.
    """
    with _server(pump=False) as s:
        real_pump = type(s.app)._pump_net
        type(s.app)._pump_net = lambda self: 0          # the mutant, exactly
        try:
            future = _submit(s, lambda app: "done")
            _run_modal(lambda: s.app._modal_message(["hello"]))
            assert s.app._net_commands.pending == 1, \
                "the queue drained with the pump removed — this suite proves nothing"
            assert not future.done(), "the future resolved without a pump"
        finally:
            type(s.app)._pump_net = real_pump
            s.app._net_commands.pump(s.app)             # tidy: let the future go
    print("✅ test_a_modal_without_the_pump_strands_the_queue")


def test_every_event_draining_loop_has_a_pump():
    """A seventh modal added later without a pump is a regression this catches.

    The rule is structural and is read off `main.py` itself: **a `while True:` whose body
    drains `pygame.event.get()` is a blocking modal**, and its first statement must be
    `self._pump_net()`. `_advance_npc_playback`'s `while True:` (`main.py:3119`) drains a
    recorded event list rather than pygame's queue, so the rule does not reach it — which
    is why the site count is six and not seven.
    """
    tree = ast.parse(open(os.path.join(_ROOT, "gui", "main.py")).read())

    def drains_pygame_events(node):
        for sub in ast.walk(node):
            if (isinstance(sub, ast.For) and isinstance(sub.iter, ast.Call)
                    and isinstance(sub.iter.func, ast.Attribute)
                    and sub.iter.func.attr == "get"
                    and isinstance(sub.iter.func.value, ast.Attribute)
                    and sub.iter.func.value.attr == "event"):
                return True
        return False

    loops = [n for n in ast.walk(tree)
             if isinstance(n, ast.While)
             and isinstance(n.test, ast.Constant) and n.test.value is True
             and drains_pygame_events(n)]

    assert len(loops) == 6, f"{len(loops)} event-draining modal loops, not the six Step 0.11 named"

    for loop in loops:
        first = loop.body[0]
        assert (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Attribute)
                and first.value.func.attr == "_pump_net"), \
            f"the modal loop at main.py:{loop.lineno} does not open with self._pump_net()"
    print("✅ test_every_event_draining_loop_has_a_pump")


# ─────────────────────────────────────────────────────────────────────────────
#  What it is for
# ─────────────────────────────────────────────────────────────────────────────

def test_state_during_a_modal_is_answered():
    """The headline, end to end: a real request, answered while a modal owns the screen.

    One commit ago this parked for `STATE_TIMEOUT_S` and came back `503`. The request has
    to be issued from another thread because this one is about to block in a modal — which
    is the arrangement the real app is in, with the roles of the two threads swapped.
    """
    with _server(pump=False) as s:
        s.publish()
        answer = {}

        def ask():
            answer["got"] = s.get("/state", credential=s.player)

        caller = threading.Thread(target=ask, daemon=True)
        caller.start()

        # Wait for the handler to have queued its command; without this the modal can run
        # its single iteration before the request has reached the server at all.
        for _ in range(500):
            if s.app._net_commands.pending:
                break
            pygame.time.wait(10)
        assert s.app._net_commands.pending, "the request never reached the command queue"

        _run_modal(lambda: s.app._modal_message(["Generating dungeon…"]))
        caller.join(10)

        status, _headers, raw = answer["got"]
        assert status == 200, f"/state during an open modal answered {status}, not 200"
        assert json.loads(raw)["t"] == "view", "the body was not a view envelope"
    print("✅ test_state_during_a_modal_is_answered")


def test_the_pump_draws_nothing():
    """D-M4-3's other half: it pumps the command queue and nothing that redraws.

    Asserted on the screen surface across a pump that definitely ran a command. The modal
    redraws every frame on its own account — what must not happen is the *pump* putting
    pixels under it.
    """
    with _server(pump=False) as s:
        before = s.app.screen.copy()
        future = _submit(s, lambda app: app.roster.join_code)
        assert s.app._pump_net() == 1, "the pump did not run the command"
        future.result(2.0)
        after = s.app.screen
        assert pygame.image.tostring(before, "RGB") == pygame.image.tostring(after, "RGB"), \
            "the pump changed the screen"
    print("✅ test_the_pump_draws_nothing")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M4d-4 — a command may not open a modal
# ─────────────────────────────────────────────────────────────────────────────

def test_a_command_that_opens_a_modal_is_refused():
    """Reentrancy is refused on the nested loop's first line, before it draws.

    Today every command is `build_view` and this is theoretical. It is enforced now
    because the next two callers — D-M4-3's own sites and M5's `submit` — are exactly
    where someone reaches for a confirmation dialog.
    """
    with _server(pump=False) as s:
        before = s.app.screen.copy()
        future = _submit(s, lambda app: app._modal_message(["this may not happen"]))
        _quit_queued()
        s.app._pump_net()

        try:
            future.result(2.0)
        except RuntimeError as exc:
            assert "D-M4d-4" in str(exc), f"refused, but not by the guard: {exc}"
        else:
            raise AssertionError("a command opened a modal and nothing stopped it")

        assert pygame.image.tostring(before, "RGB") == \
            pygame.image.tostring(s.app.screen, "RGB"), \
            "the refused modal drew before it was refused"
        pygame.event.clear()
    print("✅ test_a_command_that_opens_a_modal_is_refused")


def test_the_refusal_rides_the_future():
    """Rule 2 again, through the new guard: the exception is the caller's, not the loop's.

    A command that raises may not take the frame loop with it — so the pump that refused
    one must still report the command as run, and the next pump must still work.
    """
    with _server(pump=False) as s:
        bad = _submit(s, lambda app: app._modal_message(["no"]))
        _quit_queued()
        assert s.app._pump_net() == 1, "the refused command was not counted as run"
        try:
            bad.result(2.0)
        except RuntimeError:
            pass

        pygame.event.clear()
        good = _submit(s, lambda app: "still here")
        assert s.app._pump_net() == 1, "the frame loop stopped pumping after a refusal"
        assert good.result(2.0) == "still here"
    print("✅ test_the_refusal_rides_the_future")


def test_the_guard_clears_after_a_refusal():
    """The flag is released on the way out, or one bad command wedges every later one.

    `try`/`finally` around the pump is what makes this true; without it the refusal is
    permanent and the symptom is a frame loop that has silently stopped answering.
    """
    with _server(pump=False) as s:
        bad = _submit(s, lambda app: app._modal_message(["no"]))
        _quit_queued()
        s.app._pump_net()
        try:
            bad.result(2.0)
        except RuntimeError:
            pass
        pygame.event.clear()
        assert s.app._net_pumping is False, "the reentrancy guard stayed set"

        # And the modals work afterwards, which is the consequence that would be noticed.
        ran = []
        _submit(s, lambda app: ran.append(True))
        _run_modal(lambda: s.app._modal_message(["hello"]))
        assert ran, "a modal stopped pumping after an earlier command was refused"
    print("✅ test_the_guard_clears_after_a_refusal")


if __name__ == "__main__":
    test_every_blocking_modal_pumps()
    test_the_pump_is_above_the_event_drain()
    test_a_modal_without_the_pump_strands_the_queue()
    test_every_event_draining_loop_has_a_pump()
    test_state_during_a_modal_is_answered()
    test_the_pump_draws_nothing()
    test_a_command_that_opens_a_modal_is_refused()
    test_the_refusal_rides_the_future()
    test_the_guard_clears_after_a_refusal()
    print("\n✅ All modal-pump tests passed!")
