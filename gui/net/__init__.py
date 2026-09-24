"""Multiplayer server-side subsystem (MULTIPLAYER_PLAN.md).

Everything the player-facing server needs lives under this package, never in
``main.py`` (constraint NN3). ``roster.py`` is M0's, ``view.py`` is M3's,
``mapimg.py`` / ``server.py`` / ``link.py`` are M4's, and ``commands.py`` is
M4c's. ``static/`` is the browser client (M4e), which is served by three explicit
routes rather than a static mount — D-M4e-1, because an ``add_static`` prefix
resource would exempt its whole subtree from authentication. The prompt bus is
``gui/prompts.py`` (M1) — it renders on the pygame thread and is not a net module.

Two handoffs cross the thread seam, in opposite directions, and both are a
published immutable snapshot rather than a lock. ``mapimg.MapImageCache`` carries
a picture *to* the net thread; ``server.PlayerServer.live_viewers()`` carries the
list of connected sockets *back*, because a push is built on the frame tick and
only the net thread knows who is listening (D-M4e-4). ``commands.CommandQueue`` is
the third crossing and the only one that is a request.

Nothing in here may touch the ``CombatEngine`` or the ``BattleMap`` off the
pygame thread (constraint NN1) — read or write.

``roster.py`` is import-safe without pygame and without the C++ extension, which
is what lets the M0 tests run headless. ``mapimg.py`` (M4) is too, deliberately:
it renders the masked page from a plain snapshot of cells and line positions, so
the encode can happen on the net thread. So is ``commands.py`` (M4c), which is
neither thread's half — it is the queue between them and knows nothing about what
a command does. ``view.py`` (M3) is not, and cannot be: its subject *is* the
``BattleMap``, so it imports the extension and must run on the pygame thread like
every other reader of the map. That is why ``server.py`` never imports it and
``link.py`` hands ``build_view`` across instead. None of them imports ``main``.
"""
