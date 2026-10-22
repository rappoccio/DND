#!/usr/bin/env python3
"""M7, hardening (MULTIPLAYER_PLAN.md, M7 Step 0).

Covered here:
  · D-M7-2: the roster survives a join racing the DM       (test_the_roster_survives_racing_threads)
  · D-M7-2: the lock is not held across the bus hook       (test_the_bus_hook_runs_outside_the_lock)
  · D-M7-2: a command nobody waits for is never run        (test_a_cancelled_command_is_skipped)
"""

import asyncio
import os
import sys
import threading

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from net.commands import CommandQueue
from net.roster import (Action, DM_PRINCIPAL_ID, PromptTarget, Role, SessionRoster,
                        TokenInfo)


# ─────────────────────────────────────────────────────────────────────────────
#  D-M7-2 — the roster lock and the queue
# ─────────────────────────────────────────────────────────────────────────────

def test_the_roster_survives_racing_threads():
    """One thread seats players the way `POST /join` does; this one reads the roster the
    way a request and the frame tick do. Before the lock, `players()` iterating
    `_principals` while it grew could raise "dictionary changed size during iteration"."""
    roster = SessionRoster()
    roster.sync_tokens([TokenInfo(agent_idx=i, controller=DM_PRINCIPAL_ID, faction=2)
                        for i in range(8)])
    errors, done = [], threading.Event()

    def seat():
        try:
            for n in range(3000):
                p = roster.add_principal(f"P{n}")
                if n % 3 == 0:
                    roster.remove_principal(p.id)
                if n % 50 == 0:
                    roster.sync_tokens([TokenInfo(agent_idx=i, controller=p.id, faction=2)
                                        for i in range(8)])
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    writer = threading.Thread(target=seat, daemon=True)
    writer.start()
    dm = roster.get(DM_PRINCIPAL_ID)
    reads = 0
    try:
        while not done.is_set():
            for p in roster.players():
                roster.controlled_by(p.id)
            roster.to_dict()
            assert roster.authorize(dm, Action.VIEW_DM_CHANNEL)
            reads += 1
    except Exception as exc:
        errors.append(exc)
    writer.join(10)
    assert not errors, f"the roster tore under two threads: {errors[0]!r}"
    assert reads > 0
    print("✅ test_the_roster_survives_racing_threads")


def test_the_bus_hook_runs_outside_the_lock():
    """`authorize(ANSWER_PROMPT)` asks the prompt bus through `prompt_lookup`, which is a
    call out of the roster. It must not run under the lock, or a bus that ever touched a
    roster from another thread would deadlock. The hook here makes another thread take
    the lock and waits for it."""
    roster = SessionRoster()
    kira = roster.add_principal("Kira", role=Role.PLAYER)
    took = threading.Event()

    def lookup(_prompt_id):
        t = threading.Thread(target=lambda: (roster.players(), took.set()), daemon=True)
        t.start()
        t.join(2.0)
        return kira.id, True

    roster.prompt_lookup = lookup
    assert roster.authorize(kira, Action.ANSWER_PROMPT, PromptTarget("p1"))
    assert took.is_set(), "the bus hook ran with the roster lock held"
    print("✅ test_the_bus_hook_runs_outside_the_lock")


def test_a_cancelled_command_is_skipped():
    """A `GET /state` that timed out cancelled its future. Running its view anyway would
    spend a frame on an answer nobody reads, which is the cheapest way to load the frame
    tick from the network (F-M7-5)."""
    queue = CommandQueue(skip_abandoned=True)
    ran = []

    async def submit_two():
        stale = queue.submit(lambda app: ran.append("stale"))
        live = queue.submit(lambda app: ran.append("live") or "ok")
        stale.cancel()
        return live

    loop = asyncio.new_event_loop()
    try:
        live = loop.run_until_complete(submit_two())
        assert queue.pump(app=None) == 1, "the cancelled command counted as work"
        loop.run_until_complete(asyncio.sleep(0))
        assert live.result() == "ok"
    finally:
        loop.close()
    assert ran == ["live"], f"a cancelled command ran: {ran}"
    assert queue.skipped == 1 and queue.pending == 0
    # Only the read queue skips. A submit that timed out is still decided later, which is
    # what Step 0.5's `timeout` promises (test_submit.test_a_stalled_frame_loop_is_a_timeout).
    src = open(os.path.join(_ROOT, "gui", "main.py"), encoding="utf-8").read()
    assert "self._net_commands = CommandQueue(skip_abandoned=True)" in src
    assert "self._net_submits = CommandQueue()" in src, "the submit queue must not skip"
    print("✅ test_a_cancelled_command_is_skipped")


if __name__ == "__main__":
    test_the_roster_survives_racing_threads()
    test_the_bus_hook_runs_outside_the_lock()
    test_a_cancelled_command_is_skipped()
    print("\n✅ All hardening tests passed!")
