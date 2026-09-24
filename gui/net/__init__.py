"""Multiplayer server-side subsystem (MULTIPLAYER_PLAN.md).

Everything the player-facing server needs lives under this package, never in
``main.py`` (constraint NN3). M0 adds only the session roster; the prompt bus,
the ``GameView`` projection and the transport arrive in M1/M3/M4.

Nothing in here may touch the ``CombatEngine`` or the ``BattleMap`` off the
pygame thread (constraint NN1) — read or write.

``roster.py`` is import-safe without pygame and without the C++ extension, which
is what lets the M0 tests run headless. ``mapimg.py`` (M4) is too, deliberately:
it renders the masked page from a plain snapshot of cells and line positions, so
the encode can happen on the net thread. ``view.py`` (M3) is not, and cannot be:
its subject *is* the ``BattleMap``, so it imports the extension and must run on
the pygame thread like every other reader of the map. None of them imports
``main``.
"""
