"""The session log: one log of the table, for everyone at it (MULTIPLAYER_PLAN.md D-M7-4).

The combat log says what happened in the fight. This says what happened at the *table*:
who joined, who dropped, when the DM took a turn over, paused, rewound or changed the join
code. The user asked for one joint log that everyone can read, so every seated viewer
gets it in their `view`, as the `session` block, and the DM reads it in the Table menu.

**Two audiences, one log.** Most lines are public. A few are the DM's alone: a refused
join, a throttled address, a closed connection. Those carry addresses, and they are A9's
audit log, which until M7 was a counter. A DM-only line is **omitted** from a player's
view, never sent and hidden (wire ground rule 3). Which viewer is the DM is
`authorize(VIEW_DM_CHANNEL)`'s answer, asked by `net.view`, not by this module.

**Both threads write here.** `POST /join` and the sockets log from the net thread; the
prompt bus, pause and restore log from the pygame thread. So the ring sits behind a lock,
and `tail` hands out fresh dicts (`CommandQueue` rule 3).

**Names are labels here, and ids are kept beside them.** A line's text is for people, so
it says "Kira", as the screen does. The file keeps the principal id with each line, so a
line still says whose seat it was after a rename (A1/A2: a display name is never a key).
The file is gitignored, as the Identity section asks for anything holding real names.

Import-safe without pygame, without the C++ extension and without `aiohttp`, like
`roster.py` and `commands.py`: it is neither thread's half.
"""

from __future__ import annotations

import collections
import json
import os
import threading
import time

SESSION_LOG_PATH = "session_log.jsonl"

# The ring is what a viewer can be sent; the file keeps everything.
RING_SIZE = 200
WIRE_TAIL = 50


class SessionLog:
    """The table's log: a ring for the wire, and an append-only file once a server runs."""

    def __init__(self, path: str | None = None) -> None:
        # None until a transport exists, as `SubmitLog`'s is: a constructed `App` in a
        # headless suite keeps the ring and writes no file into the tree.
        self.path = path
        self._lock = threading.Lock()
        self._ring: collections.deque = collections.deque(maxlen=RING_SIZE)
        self._n = 0

    def add(self, text: str, dm_only: bool = False, principal: str | None = None) -> dict:
        """Record one line, and return a copy of it. Never raises."""
        now = time.time()
        with self._lock:
            self._n += 1
            entry = {"n": self._n, "at": time.strftime("%H:%M", time.localtime(now)),
                     "text": str(text)}
            if dm_only:
                entry["dm"] = True
            self._ring.append(entry)
            self._append({**entry,
                          "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                          "principal": principal})
            return dict(entry)

    def tail(self, include_dm: bool, limit: int = WIRE_TAIL) -> list[dict]:
        """The newest ``limit`` lines this reader may see, oldest first, as fresh dicts.

        ``include_dm`` is the caller's `authorize(VIEW_DM_CHANNEL)`. A DM-only line is
        left out for everyone else, and is not counted against their ``limit``.
        """
        with self._lock:
            lines = [dict(e) for e in self._ring if include_dm or not e.get("dm")]
        return lines[-limit:] if limit else []

    def __len__(self) -> int:
        with self._lock:
            return len(self._ring)

    def _append(self, entry: dict) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError as exc:
            print(f"[net] session log not written ({os.path.basename(self.path)}): {exc}")


# ── The prompt bus's lines ──────────────────────────────────────────────────

def prompt_noun(prompt) -> str:
    """What a player would call this prompt: their turn, a reaction, or a choice."""
    kind = getattr(prompt, "kind", "")
    if kind == "action":
        return "turn"
    if kind == "reaction":
        return "reaction"
    return "choice"


def announce_prompt(app, event: str, prompt) -> None:
    """`SubmitLog`'s two table-facing lines, said to the table (D-M7-4).

    ``event`` is `takeover` (the DM answered or dismissed a player's prompt) or `expired`
    (its deadline did). The submit log has already decided that it is one of those, so
    the rules for when the DM's click counts as taking over live in one place.
    """
    owner = getattr(prompt, "owner", None)
    name = app.roster.display_name(owner) if owner else "a player"
    noun = prompt_noun(prompt)
    if event == "takeover":
        app.session_log.add(f"The DM took over {name}'s {noun}.", principal=owner)
    elif event == "expired":
        app.session_log.add(f"{name}'s {noun} timed out.", principal=owner)
