"""Simulation traces: what a combat looked like, turn by turn (NPC_LEARNING_PLAN.md Step 1).

A trace is a JSONL file. Line one is the **header**: the map, the agents (inline, in the
raw index basis the events are keyed by), the seed, the policy per side and the PC mode.
Then one **turn** record per turn: the actor, the round, the display snapshot taken before
the turn (``App._npc_anim_snapshot``'s data), the turn's visual events, its combat-log
lines, and ``spawned``: the agent records of anything placed since the last record (summons,
reinforcements), which continue the header's raw index basis. An automated turn also carries
``decision``: the archetype, the fallback rung and the strategy the engine resolved
(``CombatEngine.last_npc_decision``, Step 4). A **footer** with the outcome closes the file;
a trace without one was cut short.

Playback (Step 2) replays the recorded events over the recorded snapshots. It never
re-executes the engine, so nothing here has to be deterministic beyond what it stores.

Ground rules for this module:
  · It imports neither the extension nor pygame. Events go in as anything with the
    ``rpg.NpcVisualEvent`` attributes and come out as ``TraceEvent``, which has the same
    attributes, so ``_npc_anim_start`` takes either.
  · A write failure disables the writer with one console line. A trace never breaks a fight.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple

TRACE_VERSION = 1

# `NpcVisualEvent.kind` crosses the binding as a plain int (combat_types.hpp). On disk it is
# a string, as on the M4b wire (net/events.py), so a reordered C++ enum fails a load
# instead of replaying a move as an outcome. tests/test_sim_trace.py pins the table.
_KIND_TO_STR = {0: "move", 1: "announce", 2: "outcome"}
_STR_TO_KIND = {v: k for k, v in _KIND_TO_STR.items()}

# Who drove a turn record.
DRIVER_NPC, DRIVER_HUMAN, DRIVER_NONE = "npc", "human", "none"


class TraceCell(NamedTuple):
    """A path cell, with the ``col`` / ``row`` attributes of ``rpg.Cell``."""
    col: int
    row: int


@dataclass
class TraceEvent:
    """One visual event loaded from a trace: the ``rpg.NpcVisualEvent`` fields, by name."""
    kind: int
    agent_idx: int = -1
    target_idx: int = -1
    path: list[TraceCell] = field(default_factory=list)
    text: str = ""
    good: bool = False
    hp_after: int = -1
    died: bool = False


def decision_to_dict(d) -> dict | None:
    """An ``rpg.NpcDecision`` as a trace dict, names as strings like the event kinds. None
    when the turn made no decision (``agent_idx`` -1: a corpse, Command Flee, Forcecage)."""
    if d is None or d.agent_idx < 0:
        return None
    return {"level": int(d.level), "archetype": d.archetype.name, "rung": d.rung.name,
            "strategy": d.strategy.name}


def event_to_dict(ev) -> dict:
    """One visual event (engine or ``TraceEvent``) as JSON-ready data. Every field is kept,
    so ``event_from_dict(event_to_dict(ev))`` matches ``ev`` field for field."""
    kind = _KIND_TO_STR.get(int(ev.kind))
    if kind is None:
        raise ValueError(f"unknown NpcVisualEvent kind {ev.kind!r}")
    return {"kind": kind, "agent": int(ev.agent_idx), "target": int(ev.target_idx),
            "path": [[int(c.col), int(c.row)] for c in ev.path],
            "text": str(ev.text), "good": bool(ev.good),
            "hp_after": int(ev.hp_after), "died": bool(ev.died)}


def event_from_dict(d: dict) -> TraceEvent:
    kind = _STR_TO_KIND.get(d["kind"])
    if kind is None:
        raise ValueError(f"unknown trace event kind {d['kind']!r}")
    return TraceEvent(kind=kind, agent_idx=int(d["agent"]), target_idx=int(d["target"]),
                      path=[TraceCell(int(c), int(r)) for c, r in d["path"]],
                      text=str(d["text"]), good=bool(d["good"]),
                      hp_after=int(d["hp_after"]), died=bool(d["died"]))


def snapshot_to_list(snapshot: dict | None) -> list | None:
    """``{idx: {"pos", "hp", "was_alive"}}`` → a list, since JSON keys are strings."""
    if snapshot is None:
        return None
    return [{"idx": int(i), "pos": [float(s["pos"][0]), float(s["pos"][1])],
             "hp": int(s["hp"]), "was_alive": bool(s["was_alive"])}
            for i, s in sorted(snapshot.items())]


def snapshot_from_list(items: list | None) -> dict | None:
    if items is None:
        return None
    return {int(s["idx"]): {"pos": (float(s["pos"][0]), float(s["pos"][1])),
                            "hp": int(s["hp"]), "was_alive": bool(s["was_alive"])}
            for s in items}


# ── The party makeup (header ``party``; Playback's party box) ──────────────────

PC_FACTION = 2


def char_level(t: dict) -> int:
    """A saved agent's character level, 1–20."""
    lv = t.get("agent_char_level")
    if lv is None:
        lv = sum(int(v) for v in (t.get("agent_class_levels") or {}).values()) or 1
    return max(1, min(20, int(lv)))


def class_text(t: dict) -> str:
    """``Warlock (Fiend) 9``, or each class of a multiclass: ``Fighter 5 / Wizard (Evoker) 4``.
    A creature with no class is ``-``."""
    def one(cls, lv):
        sub = t.get(f"agent_{cls.lower()}_subclass")
        sub = f" ({sub})" if sub and sub not in ("NONE", "None") else ""
        return f"{cls}{sub} {lv}"
    levels = t.get("agent_class_levels") or {}
    if isinstance(levels, dict) and len(levels) > 1:
        return " / ".join(one(c, lv) for c, lv in levels.items())
    cls = t.get("agent_class") or "None"
    return "-" if cls == "None" else one(cls, char_level(t))


def _is_npc(t: dict) -> bool:
    sd = t.get("stats") or {}
    return bool(sd["is_npc"] if "is_npc" in sd else t.get("is_npc", False))


def party_makeup(agents: list) -> list[dict]:
    """The PCs (PC side, not NPC allies) as name, class text and level."""
    return [{"name": a["name"], "class": class_text(a), "level": char_level(a)}
            for a in agents or []
            if int(a.get("faction", 0)) == PC_FACTION and not _is_npc(a)]


def trace_party(header: dict) -> list[dict]:
    """The header's ``party`` (arena traces), else one derived from its agents (GUI traces)."""
    if header.get("party") is not None:
        return list(header["party"])
    return party_makeup((header.get("agents") or {}).get("agents"))


# ── Writing ─────────────────────────────────────────────────────────────────

class TraceWriter:
    """Appends one combat's trace to ``path``. The header goes out on construction; each
    turn record goes out when the next turn begins (or on ``close``), so a crash loses at
    most the turn in progress."""

    def __init__(self, path: str, *, map_path: str, agents: Any, seed: int,
                 npc_policy: str, pc_mode: str, initiative: Iterable = (),
                 resumed: bool = False, extra: dict | None = None):
        self.path = path
        self._turn: dict | None = None
        self._f = None
        header = {"type": "header", "version": TRACE_VERSION, "map": map_path,
                  "agents": agents, "seed": int(seed), "npc_policy": npc_policy,
                  "pc_mode": pc_mode, "initiative": list(initiative), "resumed": resumed}
        if extra:
            header.update(extra)
        try:
            self._f = open(path, "w")
        except OSError as e:
            print(f"[SIM TRACE] cannot open {path}: {e}; not recording this combat")
            return
        self._write(header)

    @property
    def active(self) -> bool:
        return self._f is not None

    def begin_turn(self, *, round_num: int, actor: int, actor_name: str, driver: str,
                   snapshot: dict | None, spawned: list | None = None) -> None:
        """Close the open turn record and start the next one. ``spawned``: agent records
        appended to the board since the last record, in index order."""
        self._flush_turn()
        self._turn = {"type": "turn", "round": int(round_num), "actor": int(actor),
                      "actor_name": actor_name, "driver": driver,
                      "snapshot": snapshot_to_list(snapshot), "spawned": list(spawned or []),
                      "events": [], "log": []}

    def add_events(self, events: Iterable) -> None:
        self._open_turn()["events"].extend(event_to_dict(ev) for ev in events)

    def set_decision(self, decision) -> None:
        """Record the open turn's strategy decision (an ``rpg.NpcDecision``). A parked
        turn's resume reports the same decision again, so the last call wins."""
        d = decision_to_dict(decision)
        if d is not None:
            self._open_turn()["decision"] = d

    def add_log(self, line: str) -> None:
        self._open_turn()["log"].append(str(line))

    def close(self, outcome: dict | None = None) -> None:
        """Write the open turn and the footer, and close the file. Idempotent."""
        if self._f is None:
            return
        self._flush_turn()
        self._write({"type": "footer", "outcome": outcome or {}})
        if self._f is not None:
            self._f.close()
            self._f = None

    # ── internals ──
    def _open_turn(self) -> dict:
        # Anything before the first turn (combat-start log lines) lands in a prelude record.
        if self._turn is None:
            self.begin_turn(round_num=0, actor=-1, actor_name="", driver=DRIVER_NONE,
                            snapshot=None)
        return self._turn

    def _flush_turn(self) -> None:
        if self._turn is not None:
            self._write(self._turn)
            self._turn = None

    def _write(self, rec: dict) -> None:
        if self._f is None:
            return
        try:
            self._f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            self._f.flush()
        except (OSError, TypeError, ValueError) as e:
            print(f"[SIM TRACE] write to {self.path} failed: {e}; trace disabled")
            try:
                self._f.close()
            except OSError:
                pass
            self._f = None


# ── Reading ─────────────────────────────────────────────────────────────────

@dataclass
class TraceTurn:
    round: int
    actor: int
    actor_name: str
    driver: str
    snapshot: dict | None          # {idx: {"pos": (fcol, frow), "hp": int, "was_alive": bool}}
    events: list[TraceEvent]
    log: list[str]
    spawned: list = field(default_factory=list)   # agent records new since the last turn
    decision: dict | None = None   # {level, archetype, rung, strategy}; None = no decision


@dataclass
class Trace:
    header: dict
    turns: list[TraceTurn]
    footer: dict | None            # None: the trace was cut short (no footer line)

    @property
    def complete(self) -> bool:
        return self.footer is not None


def load_trace(path: str) -> Trace:
    """Read a trace file. A missing footer is allowed (a cut-short trace); a missing or
    newer-version header is refused."""
    header, turns, footer = None, [], None
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            t = rec.get("type")
            if n == 1:
                if t != "header":
                    raise ValueError(f"{path}: first line is not a trace header")
                if int(rec.get("version", 0)) > TRACE_VERSION:
                    raise ValueError(f"{path}: trace version {rec['version']} is newer "
                                     f"than this reader ({TRACE_VERSION})")
                header = rec
            elif t == "turn":
                turns.append(TraceTurn(
                    round=int(rec["round"]), actor=int(rec["actor"]),
                    actor_name=rec.get("actor_name", ""), driver=rec["driver"],
                    snapshot=snapshot_from_list(rec.get("snapshot")),
                    events=[event_from_dict(e) for e in rec["events"]],
                    log=list(rec["log"]), spawned=list(rec.get("spawned", [])),
                    decision=rec.get("decision")))
            elif t == "footer":
                footer = rec.get("outcome", {})
            else:
                raise ValueError(f"{path}:{n}: unknown trace record type {t!r}")
    if header is None:
        raise ValueError(f"{path}: empty trace")
    return Trace(header=header, turns=turns, footer=footer)
