"""Initiative tracker mode's turn order (plans/INITIATIVE_TRACKER_PLAN.md T2).

Pure Python: no pygame, no rpg. The table rolls real dice and the DM types the totals in;
this model holds the order, whose turn it is and the round. main.py mirrors it into
initiative_order / turn_idx / round_num so the existing initiative drawing keeps working.

Entries are keyed by agent_idx (one entry per agent). A removed entry (D4) is tombstoned,
not deleted, as _clear_mob does to the agent, so it still round-trips through JSON. An
entry whose joins_round is later than the current round (D5) is in the order but skipped.
"""

PHASES = ("idle", "collecting", "running")


class Entry:
    __slots__ = ("agent_idx", "total", "joins_round", "removed")

    def __init__(self, agent_idx: int, total=None, joins_round: int = 1, removed=False):
        self.agent_idx   = int(agent_idx)
        self.total       = None if total is None else int(total)
        self.joins_round = int(joins_round)
        self.removed     = bool(removed)

    def to_json(self) -> dict:
        return {"agent_idx": self.agent_idx, "total": self.total,
                "joins_round": self.joins_round, "removed": self.removed}

    def __repr__(self):
        return (f"Entry({self.agent_idx}, {self.total}, joins={self.joins_round}"
                f"{', removed' if self.removed else ''})")


def _sort_key(e: Entry):
    """Highest total first; a blank total sinks to the bottom. Used with a stable sort, so
    ties keep entry order."""
    return (e.total is None, -(e.total or 0))


class Tracker:
    def __init__(self):
        self.entries: list[Entry] = []
        self.round = 1
        self.turn  = 0          # position in entries of the acting entry
        self.phase = "idle"

    # ── Queries ──────────────────────────────────────────────────────────────
    def index_of(self, agent_idx: int) -> int:
        for i, e in enumerate(self.entries):
            if e.agent_idx == agent_idx:
                return i
        return -1

    def entry(self, agent_idx: int):
        i = self.index_of(agent_idx)
        return self.entries[i] if i >= 0 else None

    def _acts(self, e: Entry) -> bool:
        """Takes a turn this round: not removed, and already joined (D5)."""
        return not e.removed and e.joins_round <= self.round

    def current(self):
        """The acting agent_idx, or None when nothing is running or nobody can act."""
        if self.phase != "running" or not (0 <= self.turn < len(self.entries)):
            return None
        e = self.entries[self.turn]
        return e.agent_idx if self._acts(e) else None

    # ── Building the order ───────────────────────────────────────────────────
    def set_total(self, agent_idx: int, total):
        e = self.entry(agent_idx)
        if e is None:
            raise KeyError(agent_idx)
        e.total = None if total is None else int(total)

    def sort(self):
        """Stable sort by total (blanks last). The acting entry stays the acting entry."""
        cur = self.entries[self.turn] if 0 <= self.turn < len(self.entries) else None
        self.entries.sort(key=_sort_key)
        if cur is not None:
            self.turn = self.entries.index(cur)

    def move(self, agent_idx: int, delta: int) -> bool:
        """Swap an entry with its neighbour (delta ±1): manual reorder or a delayed turn.
        `turn` is a position, so moving the acting entry down hands the turn to the one
        that was next. Returns False at either end."""
        i = self.index_of(agent_idx)
        j = i + delta
        if i < 0 or delta not in (-1, 1) or not (0 <= j < len(self.entries)):
            return False
        self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
        return True

    def add(self, agent_idxs, total=None, joins_round: int = 1) -> list:
        """Insert agents at `total`'s place in the order, after any entry with an equal or
        higher total (so existing ties keep precedence); blanks go to the bottom. Agents
        already in the order are skipped. Returns the agent_idxs actually added."""
        added = []
        for a in agent_idxs:
            if self.index_of(a) >= 0:
                continue
            new = Entry(a, total, joins_round)
            key = _sort_key(new)
            pos = len(self.entries)
            for i, e in enumerate(self.entries):
                if _sort_key(e) > key:
                    pos = i
                    break
            self.entries.insert(pos, new)
            if self.phase == "running" and pos <= self.turn:
                self.turn += 1          # keep the acting entry acting
            added.append(a)
        return added

    def remove(self, agent_idx: int) -> bool:
        """Tombstone an entry (D4). It stays in place; next/prev skip it. The caller
        advances the turn if the removed entry was acting."""
        e = self.entry(agent_idx)
        if e is None or e.removed:
            return False
        e.removed = True
        return True

    # ── Running ──────────────────────────────────────────────────────────────
    def start(self):
        """Sort, then hand the first turn of round 1 to the first entry that acts."""
        self.sort()
        self.phase = "running"
        self.round = 1
        self.turn  = -1
        return self.next()

    def next(self):
        """Advance to the next entry that acts, wrapping to round + 1 past the end.
        Returns the acting agent_idx, or None (state unchanged) if nobody can act."""
        n = len(self.entries)
        rnd, t = self.round, self.turn
        for _ in range(2 * n + 1):
            t += 1
            if t >= n:
                t, rnd = 0, rnd + 1
            e = self.entries[t] if n else None
            if e is not None and not e.removed and e.joins_round <= rnd:
                self.round, self.turn = rnd, t
                return e.agent_idx
        return None

    def jump(self, agent_idx: int) -> bool:
        """Hand the turn straight to `agent_idx` (the DM clicks a name in the order). The
        round is unchanged. False if it isn't running or the entry is missing or removed."""
        i = self.index_of(agent_idx)
        if self.phase != "running" or i < 0 or self.entries[i].removed:
            return False
        self.turn = i
        return True

    def prev(self):
        """Step back to the previous entry that acts, wrapping to round − 1 before the
        start. Never goes before round 1's first acting entry: returns None there."""
        n = len(self.entries)
        if n == 0:
            return None
        rnd, t = self.round, self.turn
        while True:
            t -= 1
            if t < 0:
                if rnd <= 1:
                    return None
                t, rnd = n - 1, rnd - 1
            e = self.entries[t]
            if not e.removed and e.joins_round <= rnd:
                self.round, self.turn = rnd, t
                return e.agent_idx

    # ── Persistence ──────────────────────────────────────────────────────────
    def to_json(self) -> dict:
        return {"round": self.round, "turn": self.turn, "phase": self.phase,
                "entries": [e.to_json() for e in self.entries]}

    @classmethod
    def from_json(cls, d: dict) -> "Tracker":
        t = cls()
        t.round = int(d.get("round", 1))
        t.turn  = int(d.get("turn", 0))
        phase = d.get("phase", "idle")
        t.phase = phase if phase in PHASES else "idle"
        t.entries = [Entry(e["agent_idx"], e.get("total"), e.get("joins_round", 1),
                           e.get("removed", False)) for e in d.get("entries", [])]
        return t
