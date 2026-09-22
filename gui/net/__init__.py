"""Multiplayer server-side subsystem (MULTIPLAYER_PLAN.md).

Everything the player-facing server needs lives under this package, never in
``main.py`` (constraint NN3). M0 adds only the session roster; the prompt bus,
the ``GameView`` projection and the transport arrive in M1/M3/M4.

Nothing in here may touch the ``CombatEngine`` or the ``BattleMap`` off the
pygame thread (constraint NN1) — read or write. This package is import-safe
without pygame and without the C++ extension, which is what lets the M0 tests
run headless.
"""
