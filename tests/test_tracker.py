#!/usr/bin/env python3
"""Initiative tracker mode, step T2: the turn-order model, gui/tracker.py
(plans/INITIATIVE_TRACKER_PLAN.md). Pure Python, no engine.

  · totals sort high→low, blanks sink, ties keep entry order;
  · move() reorders by one, and refuses past either end;
  · next/prev skip removed entries (D4) and entries not yet joined (D5), and wrap rounds;
  · add() mid-fight lands at its total and keeps the acting entry acting;
  · to_json / from_json round-trip.
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

from tracker import Tracker

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print(f"  ✗ {msg}")


def _order(t):
    return [e.agent_idx for e in t.entries]


def _tracker(totals):
    """A tracker collecting `totals`, a list of (agent_idx, total)."""
    t = Tracker()
    t.phase = "collecting"
    t.add([a for a, _ in totals])
    for a, tot in totals:
        t.set_total(a, tot)
    return t


def test_sort():
    t = _tracker([(0, 12), (1, None), (2, 19), (3, 5)])
    t.sort()
    check(_order(t) == [2, 0, 3, 1], f"sort: {_order(t)}")
    print("✅ test_sort")


def test_ties():
    t = _tracker([(4, 15), (1, 15), (7, 20), (2, 15), (3, None), (0, None)])
    t.sort()
    check(_order(t) == [7, 4, 1, 2, 3, 0], f"ties: {_order(t)}")
    t.sort()
    check(_order(t) == [7, 4, 1, 2, 3, 0], "a second sort changed the order")
    print("✅ test_ties")


def test_reorder():
    t = _tracker([(0, 20), (1, 15), (2, 10)])
    t.sort()
    check(t.move(1, -1) and _order(t) == [1, 0, 2], f"move up: {_order(t)}")
    check(t.move(1, +1) and _order(t) == [0, 1, 2], f"move down: {_order(t)}")
    check(not t.move(0, -1), "moved past the top")
    check(not t.move(2, +1), "moved past the bottom")
    check(not t.move(9, +1), "moved an agent that is not in the order")
    check(_order(t) == [0, 1, 2], "a refused move changed the order")

    # A delayed turn: the acting entry steps down and the next one acts.
    check(t.start() == 0, "start did not hand the turn to the top")
    t.move(0, +1)
    check(t.current() == 1, f"delay: current is {t.current()}")
    check(t.next() == 0, "the delayer did not act right after")
    print("✅ test_reorder")


def test_skip_dead():
    t = _tracker([(0, 20), (1, 15), (2, 10), (3, 5)])
    check(t.start() == 0, "start")
    check(t.remove(1), "remove refused")
    check(not t.remove(1), "removed twice")
    check(t.next() == 2, "next did not skip the removed entry")
    check(t.prev() == 0, "prev did not skip the removed entry")
    check(t.remove(0) and t.next() == 2, "removing the acting entry, then next")
    check(_order(t) == [0, 1, 2, 3], "remove deleted rather than tombstoned")
    for a in (2, 3):
        t.remove(a)
    check(t.next() is None, "next found an actor among only removed entries")
    check(t.prev() is None, "prev found an actor among only removed entries")
    print("✅ test_skip_dead")


def test_wrap():
    t = _tracker([(0, 20), (1, 15), (2, 10)])
    check(t.prev() is None, "prev before start")
    check(t.start() == 0 and t.round == 1, "start")
    check(t.prev() is None and t.round == 1 and t.turn == 0, "prev before round 1's start")
    t.next(); t.next()
    check(t.current() == 2 and t.round == 1, "last turn of round 1")
    check(t.next() == 0 and t.round == 2, f"wrap: round {t.round}")
    check(t.prev() == 2 and t.round == 1, f"prev wrap: round {t.round}")
    # A removed last entry: the wrap goes straight round 2's top, and back.
    t.next()
    t.remove(2)
    t.next()
    check(t.current() == 1, "next")
    check(t.next() == 0 and t.round == 3, f"wrap past a removed tail: round {t.round}")
    check(t.prev() == 1 and t.round == 2, "prev wrap past a removed tail")
    print("✅ test_wrap")


def test_add_mid_fight():
    t = _tracker([(0, 20), (1, 15), (2, 10)])
    t.start()
    t.next()
    check(t.current() == 1 and t.round == 1, "setup")
    # A revealed group joins at 18, next round (D5): above the acting entry.
    added = t.add([5, 6], 18, joins_round=t.round + 1)
    check(added == [5, 6], f"add returned {added}")
    check(_order(t) == [0, 5, 6, 1, 2], f"insert position: {_order(t)}")
    check(t.current() == 1, f"add moved the turn to {t.current()}")
    check(t.add([5], 3) == [], "an agent was added twice")
    # Rest of round 1 skips them; round 2 has them in place.
    check(t.next() == 2, "next after the add")
    seq = [t.next() for _ in range(5)]
    check(seq == [0, 5, 6, 1, 2] and t.round == 2, f"round 2: {seq}, round {t.round}")
    # prev back into round 1 still skips them.
    for _ in range(4):
        t.prev()
    check(t.current() == 0 and t.round == 2, "prev to round 2's top")
    check(t.prev() == 2 and t.round == 1, "prev into round 1")
    check(t.prev() == 1, "prev in round 1")
    check(t.prev() == 0, "prev in round 1 did not skip the newcomers")
    # A tie with an existing total goes after it; a blank goes to the bottom.
    t.next()
    t.add([7], 15)
    t.add([8])
    check(_order(t) == [0, 5, 6, 1, 7, 2, 8], f"tie / blank insert: {_order(t)}")
    check(t.current() == 1, "a later insert moved the turn")
    print("✅ test_add_mid_fight")


def test_json_round_trip():
    t = _tracker([(0, 20), (1, None), (2, 10)])
    t.start()
    t.add([4], 12, joins_round=2)
    t.remove(2)
    t.next()
    d = json.loads(json.dumps(t.to_json()))
    u = Tracker.from_json(d)
    check(u.to_json() == t.to_json(), f"round trip: {u.to_json()} != {t.to_json()}")
    check((u.round, u.turn, u.phase, u.current()) == (t.round, t.turn, t.phase, t.current()),
          "state lost in the round trip")
    check(u.next() == t.next() and u.round == t.round, "the copy steps differently")
    check(Tracker.from_json({}).to_json() == Tracker().to_json(), "empty dict")
    print("✅ test_json_round_trip")


if __name__ == "__main__":
    test_sort()
    test_ties()
    test_reorder()
    test_skip_dead()
    test_wrap()
    test_add_mid_fight()
    test_json_round_trip()
    if FAILURES:
        print(f"\n❌ {len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nAll tracker model tests passed.")
