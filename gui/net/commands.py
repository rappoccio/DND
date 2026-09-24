"""The net thread → frame tick handoff (MULTIPLAYER_PLAN.md M4c, D-M4c-1).

`MapImageCache` carries a *picture* across the seam by publishing it ahead of time. That
works because a page image is party-scoped, cheap to re-render and safe to serve slightly
stale. A `view` is none of those things: it is per-viewer, it is the whole security model
(M3), and `build_view` reads `app.bm` — so it is a **pygame-thread reader by construction**
and NN1 puts it out of the net thread's reach.

So a request that wants one has to ask, and wait. That is this module: a queue the net
thread submits callables to and the frame tick drains, with the answer coming back on an
`asyncio.Future`. F1 measured the shape (0.76 s in flight against a game thread that was
not ticking, returned on the first pump) and F2 measured the steady state ("time to the
next pump" — ≤16 ms at 60 fps).

**Built once, for three callers.** `GET /state` is the first; D-M4-3's `_pump_net()` in the
six blocking modals is the second and pumps *this* and nothing that redraws; M5's `submit`
is the third, and F1 says so in as many words. A per-viewer view cache would have served
the first and left the other two with nothing to build on.

Import-safe without pygame, without the C++ extension and without `aiohttp`, the way
`roster.py` and `mapimg.py` are — it is neither thread's half. `server.py` holds no `App`
and `link.py` holds nothing else; a queue is the thing between them, which is why it lives
here rather than in either.

**Three rules, each of which the obvious implementation breaks.**

1. The pygame thread **schedules** a resolution and never performs one. F5's rule, for its
   reason: the future belongs to the net loop.
2. A command that raises may not take the frame loop with it. The exception rides the
   future and the route turns it into a status.
3. A command returns **freshly-built data the caller owns**. Returning a live `App`
   structure hands the net thread a reference into game state and makes NN1 a matter of
   what a handler happens not to read.

Nothing here knows what a command *is*. `server.py` never imports `net.view` — the builder
is handed to it by `link.py`, which is the half that may hold both.
"""

from __future__ import annotations

import asyncio
import collections
from typing import Any, Callable

# A bound, not a tuning knob. An unbounded drain turns a flood of requests into frame-time
# damage from the one route that has no authentication in front of it (`POST /join`), and
# 32 per frame is ~1,900 commands/s at 60 fps — past any real table by three orders of
# magnitude. The remainder waits exactly one frame.
DEFAULT_BUDGET = 32


class CommandQueue:
    """Callables submitted by the net thread and run by the frame tick.

    Lock-free on purpose: `append` and `popleft` on a `deque` are atomic under the GIL and
    this holds no invariant that spans two operations. A `queue.Queue` would add a lock to
    protect state that does not exist, on the one object the frame loop touches every tick.
    """

    def __init__(self) -> None:
        self._pending: collections.deque = collections.deque()
        self.ran = 0            # total commands executed — the frame tick's liveness probe

    # ── The net thread's half ───────────────────────────────────────────────

    def submit(self, fn: Callable[[Any], Any]) -> asyncio.Future:
        """Queue `fn(app)` for the next pump and return the future it will resolve.

        Called on the net thread, inside its running loop, which is where the future has
        to be created: a future belongs to one loop and only that loop may settle it.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending.append((fn, loop, future))
        return future

    @property
    def pending(self) -> int:
        return len(self._pending)

    # ── The pygame thread's half ────────────────────────────────────────────

    def pump(self, app, budget: int = DEFAULT_BUDGET) -> int:
        """Run up to `budget` queued commands against the live `App`. Returns how many.

        The return value distinguishes a drained queue from a capped one, which is the
        only thing a caller could act on and the only reason it is not `None`.
        """
        ran = 0
        while ran < budget:
            try:
                fn, loop, future = self._pending.popleft()
            except IndexError:
                break
            ran += 1
            try:
                result = fn(app)
            except Exception as exc:          # rule 2 — never the frame loop's problem
                _settle(loop, future, None, exc)
            else:
                _settle(loop, future, result, None)
        self.ran += ran
        return ran


def _settle(loop: asyncio.AbstractEventLoop, future: asyncio.Future,
            result: Any, exc: Exception | None) -> None:
    """Schedule the answer onto the loop that owns the future (rule 1).

    The `done()` check runs **on the net loop**, and that placement is the whole point: a
    client that timed out or disconnected has already cancelled its future, and a bare
    `set_result` on a cancelled one raises `InvalidStateError` — on the net loop, inside a
    callback, where nothing is waiting to catch it. Checking here, on the pygame thread,
    would be checking a value that can change before the callback runs.
    """
    def _resolve() -> None:
        if future.done():
            return
        if exc is not None:
            future.set_exception(exc)
        else:
            future.set_result(result)

    try:
        loop.call_soon_threadsafe(_resolve)
    except RuntimeError:
        # The loop closed while the command was running — the server is stopping and the
        # requester is already gone. Dropping the answer is the whole of the cleanup.
        pass
