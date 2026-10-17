"""``EventStream`` — what happened, per viewer, in order (MULTIPLAYER_PLAN.md M4b, seam S3).

A ``view`` says where everything *is*; this says how it got there. The DM screen plays an
automated turn as a slide, a typewriter bubble and a flash per outcome, and Envelope 3 is
that playback on the wire. M4b.1 is this module: the stream, the projection and the filter.
Delivery (M4b.2) and the browser playback (M4b.3) read it.

**One global stream, projected per principal (B-1).** Everything the session does is
appended once, to a global list whose position never leaves the process. A principal's
projection filters each new global event against what that principal can see *at
projection time* and numbers the survivors itself, so its ``seq`` has no holes. A shared
global cursor with holes in it would tell a player how much is happening out of sight,
which is the same class of leak as sending the hidden creature with a flag (Envelope 3).

**Drop, never redact (B-4).** An event the viewer may not see is absent, as a token the
viewer may not see is absent from ``view.agents``. The filter's inputs are a ``Sight``,
built by ``net.view.sight`` from the same gates ``_agents`` applies, so an event can never
name a creature the viewer's own ``view`` does not carry.

**Ground rules for this module.**
  · It runs on the pygame thread: ``append`` from the sources, ``project`` from the push
    cycle. The net thread is handed frames, never the stream (NN1).
  · It imports neither the extension nor pygame. Everything it needs about the board
    arrives in a ``Sight``, which is what lets the filter be tested with no ``App``.
  · Kinds are strings on the wire (``move``, ``announce``, ``outcome``, ``turn``). An
    integer would let a client silently mis-render if the C++ enum ever grew a member, and
    an unknown C++ kind is refused here rather than guessed at.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Union

from net.roster import PROTOCOL_VERSION

# B-3: each principal keeps the last 512 projected events for `GET /events?since=`. A
# `since` older than that answers with a fresh `view` instead (the M6 resync contract).
RING_SIZE = 512

MOVE, ANNOUNCE, OUTCOME, TURN = "move", "announce", "outcome", "turn"
KINDS = (MOVE, ANNOUNCE, OUTCOME, TURN)

# `NpcVisualEvent.kind` is a plain C++ `int` (`combat_types.hpp:814`), so it crosses the
# binding as `0|1|2` and never as the enum. This table is where that integer stops: past
# here it is a string. `tests/test_events.py` pins it against `NpcVisualEvent.Kind`, so a
# member added or reordered in C++ fails a test instead of mis-rendering in a browser.
_NPC_KINDS = {0: MOVE, 1: ANNOUNCE, 2: OUTCOME}


class Resync(Exception):
    """A ``since`` this projection cannot answer from its ring: older than the ring, or
    newer than the stream. The answer is a fresh ``view``, never a patch (Envelope 3)."""


# ── Sources ─────────────────────────────────────────────────────────────────

def from_npc(ev) -> dict:
    """One ``rpg.NpcVisualEvent`` as a global event, field for field.

    The engine's ``-1`` for "no target" becomes ``None`` here, so the filter has one
    spelling of "nobody" to test.
    """
    kind = _NPC_KINDS.get(int(ev.kind))
    if kind is None:
        raise ValueError(f"unknown NpcVisualEvent kind {ev.kind!r}")
    agent = int(ev.agent_idx)
    if kind == MOVE:
        return {"kind": MOVE, "agent": agent,
                "path": [(int(c.col), int(c.row)) for c in ev.path]}
    if kind == ANNOUNCE:
        target = int(ev.target_idx)
        return {"kind": ANNOUNCE, "agent": agent,
                "target": target if target >= 0 else None, "text": str(ev.text)}
    return outcome(agent, str(ev.text), good=bool(ev.good),
                   hp_after=int(ev.hp_after), died=bool(ev.died))


def outcome(agent: int, text: str, *, good: bool, hp_after: int = -1,
            died: bool = False, crit: bool = False) -> dict:
    """An ``outcome``: a flash over ``agent``, and maybe the HP its bar drops to.

    ``hp_after`` is ``-1`` for a flash the GUI spawned itself (F-M4b-3): the human-driven
    path changes the state before it flashes, so there is no timed drop to play. ``crit``
    is the third colour the DM screen draws (``FLASH_CRIT``); ``good`` alone would turn a
    critical hit's gold into green on the player's screen.
    """
    ev = {"kind": OUTCOME, "agent": int(agent), "text": text, "good": bool(good),
          "hp_after": int(hp_after), "died": bool(died)}
    if crit:
        ev["crit"] = True
    return ev


def turn(round_num: int, turn_idx: int, agent: int | None) -> dict:
    """A ``turn`` boundary. ``agent`` is whose turn it is, or ``None`` out of combat."""
    return {"kind": TURN, "round": int(round_num), "turn_idx": int(turn_idx),
            "agent": None if agent is None else int(agent)}


# ── What a viewer can see ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Sight:
    """Everything the filter needs to know about one viewer, at one moment.

    Built by ``net.view.sight`` from the gates ``net.view._agents`` applies, and from
    nothing else, so the stream and the view cannot disagree about who is on the board.

      · ``shown`` — the live indices this viewer's ``view.agents`` carries.
      · ``hide_map`` — fog is up and the viewer is not the DM. False means no path is cut.
      · ``explored`` — the party's mask, as ``(col, row)``. Read only when ``hide_map``.
      · ``party`` — ``PC_FACTION`` tokens. The fog never hides one (``_agent_fogged``), so
        a party token's path is never cut either.
      · ``sizes`` — footprint edge per shown agent, for the same "any cell seen" rule.
      · ``vitals`` — the agents whose HP this viewer may read as numbers
        (``VIEW_TOKEN_VITALS``). Everyone else's ``hp_after`` becomes a band.
      · ``hp_max`` — maximum HP for the shown agents outside ``vitals``, for the band.
    """
    shown: frozenset[int]
    hide_map: bool = False
    explored: frozenset[tuple[int, int]] = frozenset()
    party: frozenset[int] = frozenset()
    sizes: Mapping[int, int] = field(default_factory=dict)
    vitals: frozenset[int] = frozenset()
    hp_max: Mapping[int, int] = field(default_factory=dict)


def band(hp_cur: int, hp_max: int, down: bool = False) -> str:
    """The only hit-point information an unentitled viewer gets. ``net.view._band`` calls
    this too, so a view's band and an event's band are the same function."""
    if down or hp_cur <= 0:
        return "Down"
    if hp_cur * 2 <= hp_max:
        return "Bloodied"
    return "Healthy"


def visible(ev: dict, sight: Sight) -> dict | None:
    """``ev`` as this viewer may receive it, without its ``seq``; or ``None`` to drop it.

    B-4, kind by kind:
      · ``move`` — dropped when its agent is not shown. Under fog, the path is cut to its
        longest suffix of seen cells ending at the destination, so a slide never draws an
        unexplored corridor. A hidden destination drops the event (the token's *final*
        cell may be seen while this move's end was not, on a two-move turn). One cell left
        is a jump: the client lands it.
      · ``announce`` — dropped when its actor, or its target, is not shown. A concealed
        actor is not in ``shown``, which is the DM screen's own suppression
        (``_npc_concealed_from_party``).
      · ``outcome`` — dropped when the creature it flashes over is not shown. The text
        goes word for word. ``hp_after`` rides as a number only for ``vitals``; anyone else
        gets ``band``. ``-1`` (no timed drop) sends neither, so "no field" is the client's
        one test for "leave the bar alone".
      · ``turn`` — always delivered; the view already says whose turn it is, by
        ``turn_idx``. ``agent`` is nulled when that creature is not shown (D-M5-5).
    """
    kind = ev["kind"]
    if kind == TURN:
        agent = ev["agent"]
        return {"kind": TURN, "round": ev["round"], "turn_idx": ev["turn_idx"],
                "agent": agent if agent in sight.shown else None}

    agent = ev["agent"]
    if agent not in sight.shown:
        return None

    if kind == MOVE:
        path = list(ev["path"])
        if sight.hide_map and agent not in sight.party:
            size = sight.sizes.get(agent, 1)
            keep = 0
            for cell in reversed(path):
                if not _seen(cell, size, sight.explored):
                    break
                keep += 1
            if keep == 0:
                return None
            path = path[len(path) - keep:]
        return {"kind": MOVE, "agent": agent, "path": [[c, r] for c, r in path]}

    if kind == ANNOUNCE:
        target = ev["target"]
        if target is not None and target not in sight.shown:
            return None
        return {"kind": ANNOUNCE, "agent": agent, "target": target, "text": ev["text"]}

    if kind == OUTCOME:
        out = {"kind": OUTCOME, "agent": agent, "text": ev["text"], "good": ev["good"],
               "died": ev["died"]}
        if ev.get("crit"):
            out["crit"] = True
        hp_after = ev["hp_after"]
        if hp_after >= 0:
            if agent in sight.vitals:
                out["hp_after"] = hp_after
            else:
                out["band"] = band(hp_after, sight.hp_max.get(agent, 1), ev["died"])
        return out

    raise ValueError(f"unknown event kind {kind!r}")


def _seen(origin, size: int, explored) -> bool:
    """The footprint at ``origin`` has a seen cell: the inverse of ``App._agent_fogged``."""
    col, row = origin
    return any((col + dc, row + dr) in explored
               for dc in range(size) for dr in range(size))


# ── One principal's stream ──────────────────────────────────────────────────

class Projection:
    """One principal's filtered stream: gapless ``seq``, the ring, and per-socket cursors.

    ``seq`` is the cursor *after* the newest event: 0 before any, and the ``seq`` of the
    last one after. A socket's cursor is the ``seq`` it has been sent up to. It advances
    only through ``ack``, which M4b.2 calls with what the net loop published after a send
    that succeeded (B-3), so a dropped send re-sends rather than leaving a hole.
    """

    def __init__(self, start: int):
        self._next = start                     # global position: never on the wire
        self.seq = 0
        self._ring: deque[dict] = deque(maxlen=RING_SIZE)
        self._sent: dict[str, int] = {}

    def _push(self, ev: dict) -> None:
        self.seq += 1
        self._ring.append({"seq": self.seq, **ev})

    def since(self, seq: int) -> list[dict]:
        """The events after ``seq``, oldest first. Raises ``Resync`` when the ring cannot
        answer: ``seq`` fell off its front, or is ahead of the stream."""
        seq = int(seq)
        if seq > self.seq or seq < 0:
            raise Resync(seq)
        oldest = self._ring[0]["seq"] if self._ring else self.seq + 1
        if seq < oldest - 1:
            raise Resync(seq)
        return [dict(e) for e in self._ring if e["seq"] > seq]

    def frame(self, since: int) -> dict | None:
        """An Envelope 3 ``events`` frame from ``since``, or ``None`` when there is nothing
        new. Raises ``Resync`` as ``since()`` does."""
        events = self.since(since)
        if not events:
            return None
        return {"v": PROTOCOL_VERSION, "t": "events", "since": int(since),
                "seq": self.seq, "events": events}

    # ── Sockets ─────────────────────────────────────────────────────────────
    def attach(self, socket_id: str) -> int:
        """Start a socket at the current cursor: it is about to be sent a ``view`` at this
        ``seq``, which already shows everything before it."""
        self._sent[socket_id] = self.seq
        return self.seq

    def detach(self, socket_id: str) -> None:
        self._sent.pop(socket_id, None)

    def sent(self, socket_id: str) -> int | None:
        return self._sent.get(socket_id)

    def ack(self, socket_id: str, seq: int) -> None:
        """The net loop sent ``socket_id`` everything up to ``seq``. Never moves a cursor
        backwards, past the stream, or for a socket that is not attached."""
        cur = self._sent.get(socket_id)
        if cur is None:
            return
        self._sent[socket_id] = max(cur, min(int(seq), self.seq))

    def socket_frame(self, socket_id: str) -> dict | None:
        """What ``socket_id`` is owed: a frame from its cursor, or ``None``."""
        cur = self._sent.get(socket_id)
        if cur is None:
            return None
        return self.frame(cur)


SightSource = Union[Sight, Callable[[], Sight]]


class EventStream:
    """The global stream (B-1), and every principal's projection of it."""

    def __init__(self):
        self._events: list[dict] = []
        self._base = 0                         # global position of _events[0]
        self._views: dict[str, Projection] = {}

    @property
    def _end(self) -> int:
        return self._base + len(self._events)

    def append(self, ev: dict) -> None:
        if ev.get("kind") not in KINDS:
            raise ValueError(f"unknown event kind {ev.get('kind')!r}")
        self._events.append(dict(ev))
        if not self._views:
            self._trim()

    def extend_npc(self, npc_events) -> None:
        """What ``take_npc_visual_events()`` returned, in order."""
        for ev in npc_events:
            self.append(from_npc(ev))

    def projection(self, principal_id: str) -> Projection:
        """``principal_id``'s projection, opened at the head of the stream if it is new.
        A new principal starts from a ``view``, which already shows the past."""
        p = self._views.get(principal_id)
        if p is None:
            p = self._views[principal_id] = Projection(self._end)
        return p

    def project(self, principal_id: str, sight: SightSource) -> Projection:
        """Filter what ``principal_id`` has not seen yet, and number the survivors.

        ``sight`` may be a callable, so a cycle with nothing new never pays for the
        board walk that builds one.
        """
        p = self.projection(principal_id)
        if p._next < self._end:
            s = sight() if callable(sight) else sight
            for ev in self._events[p._next - self._base:]:
                wire = visible(ev, s)
                if wire is not None:
                    p._push(wire)
            p._next = self._end
            self._trim()
        return p

    def forget(self, principal_id: str) -> None:
        self._views.pop(principal_id, None)
        self._trim()

    def _trim(self) -> None:
        """Drop the global events every projection has already filtered."""
        low = min((p._next for p in self._views.values()), default=self._end)
        if low > self._base:
            del self._events[:low - self._base]
            self._base = low

    def __len__(self) -> int:
        """Global events still held: the ones some projection has not filtered."""
        return len(self._events)
