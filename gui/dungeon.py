"""Dungeon manifest model — the "keep track of multiple maps at once" layer.

See ``FLOORS_IMPLEMENTATION_PLAN.md`` (Phase 2). The engine still simulates exactly
one ``BattleMap`` at a time; this module is the out-of-engine bookkeeping that knows
where every page sits on a shared global ``(X, Y, Z)`` grid so the app can page
between neighbours and switch floors.

Coordinate model (mirrors the plan):

    global = (origin_x + col, origin_y + row, z)     # a page's local (0,0) is at its origin
    local  = (X - origin_x, Y - origin_y)            # valid only when Z == page.z and in-bounds

A page occupies the half-open global rectangle
    [origin_x, origin_x + cols) x [origin_y, origin_y + rows)   at floor z.

``+Y`` is *down* / ``+row`` (screen convention), so ``neighbor(page, "down")`` is the
page abutting the bottom edge. ``+Z`` is *up* a floor.

────────────────────────────────────────────────────────────────────────────────────
``<name>.dungeon.json`` schema (the fifth sidecar family, at the dungeon level):

    {
      "version": 1,
      "entry_page_id": "<page id>",
      "pages": [
        {
          "id":             "<unique string>",
          "png":            "<path to the map PNG>",
          "encounter_base": "<path to the _agents.json base>",
          "origin":         [gx, gy, z],
          "cols":           <int>,          # page width  in cells (bm.grid_cols)
          "rows":           <int>           # page height in cells (bm.grid_rows)
        },
        ...
      ],
      "staircases": [                       # optional; absent in older manifests
        {
          "id":    <int>,                   # unique, never reused after a delete
          "name":  "Staircase <id>",        # DM-renamable
          "label": "<optional note>",
          "ends":  [{"page": "<page id>", "cell": [col, row]}, ...]   # 1 or 2 ends
        },
        ...
      ],
      "next_staircase_id": <int>            # the id the next staircase gets
    }

Ladders and inter-map door staples live in the per-encounter ``_terrain.json`` files
(Phases 4–5), NOT here, and door-staple adjacency is derived from page origins.
Staircases are the exception (``plans/STAIRCASES_PLAN.md``): each one spans two pages,
so the manifest owns both ends. An end is page-local (a page id and a local cell), so a
page can move on its floor without breaking it. A staircase with one end is unfinished:
the DM has placed end A and not yet end B on the floor above or below.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

DUNGEON_SCHEMA_VERSION = 1

# Direction vectors in global (X, Y) space. +Y is down (screen/row convention).
_DIR_DELTAS = {
    "left":  (-1, 0),
    "right": (+1, 0),
    "up":    (0, -1),
    "down":  (0, +1),
}


@dataclass
class MapPage:
    """One PNG "page" placed on the shared dungeon grid.

    ``origin`` is ``[gx, gy, z]`` — the global coordinate of the page's local
    ``(0, 0)`` cell. ``cols``/``rows`` are the page's grid dimensions in cells
    (from ``bm.grid_cols`` / ``bm.grid_rows``), defining its footprint.
    """

    id: str
    png: str
    encounter_base: str
    origin: list[int] = field(default_factory=lambda: [0, 0, 0])
    cols: int = 0
    rows: int = 0

    # ── Global-grid geometry ────────────────────────────────────────────────
    @property
    def gx(self) -> int:
        return self.origin[0]

    @property
    def gy(self) -> int:
        return self.origin[1]

    @property
    def z(self) -> int:
        return self.origin[2]

    def contains_global(self, X: int, Y: int, Z: int) -> bool:
        """True if global cell ``(X, Y, Z)`` falls inside this page's footprint."""
        return (
            Z == self.z
            and self.gx <= X < self.gx + self.cols
            and self.gy <= Y < self.gy + self.rows
        )

    def global_to_local(self, X: int, Y: int, Z: int) -> Optional[tuple[int, int]]:
        """Global ``(X, Y, Z)`` → local ``(col, row)`` on this page, or ``None`` if
        the cell is on another floor or outside this page's footprint.

        Mirrors ``BattleMap::globalToLocal`` but works purely from the manifest so
        the caller need not have the page loaded into the engine.
        """
        if not self.contains_global(X, Y, Z):
            return None
        return (X - self.gx, Y - self.gy)

    def local_to_global(self, col: int, row: int) -> tuple[int, int, int]:
        """Local ``(col, row)`` → global ``(X, Y, Z)``."""
        return (self.gx + col, self.gy + row, self.z)

    # ── Serialization ───────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "png": self.png,
            "encounter_base": self.encounter_base,
            "origin": [int(self.origin[0]), int(self.origin[1]), int(self.origin[2])],
            "cols": int(self.cols),
            "rows": int(self.rows),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MapPage":
        origin = list(d.get("origin", [0, 0, 0]))
        # Pad/truncate defensively so a malformed origin can't crash a load.
        origin = (origin + [0, 0, 0])[:3]
        return cls(
            id=str(d["id"]),
            png=str(d["png"]),
            encounter_base=str(d.get("encounter_base", "")),
            origin=[int(origin[0]), int(origin[1]), int(origin[2])],
            cols=int(d.get("cols", 0)),
            rows=int(d.get("rows", 0)),
        )


@dataclass
class StaircaseEnd:
    """One end of a staircase: a local cell on one page."""

    page: str
    cell: tuple[int, int]

    def to_dict(self) -> dict:
        return {"page": self.page, "cell": [int(self.cell[0]), int(self.cell[1])]}

    @classmethod
    def from_dict(cls, d: dict) -> "StaircaseEnd":
        c = list(d.get("cell", [0, 0]))
        c = (c + [0, 0])[:2]
        return cls(page=str(d["page"]), cell=(int(c[0]), int(c[1])))


@dataclass
class Staircase:
    """A two-page portal between adjacent floors, owning both of its ends."""

    id: int
    ends: list[StaircaseEnd] = field(default_factory=list)
    name: str = ""
    label: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = f"Staircase {self.id}"

    @property
    def finished(self) -> bool:
        return len(self.ends) == 2

    def other_end(self, end_index: int) -> Optional[StaircaseEnd]:
        """The end opposite ``end_index``, or ``None`` while unfinished."""
        if not self.finished or end_index not in (0, 1):
            return None
        return self.ends[1 - end_index]

    def to_dict(self) -> dict:
        d = {"id": int(self.id), "name": self.name}
        if self.label:
            d["label"] = self.label
        d["ends"] = [e.to_dict() for e in self.ends]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Staircase":
        return cls(id=int(d["id"]),
                   ends=[StaircaseEnd.from_dict(e) for e in d.get("ends", [])][:2],
                   name=str(d.get("name", "")),
                   label=str(d.get("label", "")))


@dataclass
class Dungeon:
    """An ordered collection of :class:`MapPage` sharing one global grid."""

    pages: list[MapPage] = field(default_factory=list)
    entry_page_id: Optional[str] = None
    staircases: list[Staircase] = field(default_factory=list)
    next_staircase_id: int = 1

    # ── Lookup helpers ──────────────────────────────────────────────────────
    def page_by_id(self, page_id: Optional[str]) -> Optional[MapPage]:
        if page_id is None:
            return None
        for p in self.pages:
            if p.id == page_id:
                return p
        return None

    def entry_page(self) -> Optional[MapPage]:
        """The page the dungeon opens on: the declared entry, else the first page."""
        p = self.page_by_id(self.entry_page_id)
        if p is not None:
            return p
        return self.pages[0] if self.pages else None

    def page_at_global(self, X: int, Y: int, Z: int) -> Optional[MapPage]:
        """The page whose footprint contains global cell ``(X, Y, Z)``, or ``None``.

        Pages are assumed non-overlapping on a floor; the first match wins.
        """
        for p in self.pages:
            if p.contains_global(X, Y, Z):
                return p
        return None

    def neighbor(self, page: MapPage, direction: str) -> Optional[MapPage]:
        """The page abutting ``page`` on the given side (same floor), or ``None``.

        ``direction`` ∈ {"left", "right", "up", "down"}. Adjacency is pure origin
        arithmetic: a right neighbour starts exactly where ``page`` ends in X and
        overlaps its Y-span (and symmetrically for the other sides). If several
        pages abut the same edge, the one with the largest overlap is returned.
        """
        dx, dy = _DIR_DELTAS.get(direction, (0, 0))
        if dx == 0 and dy == 0:
            return None

        best: Optional[MapPage] = None
        best_overlap = 0
        for cand in self.pages:
            if cand is page or cand.z != page.z:
                continue
            if dx > 0:  # right: cand's left edge touches page's right edge
                if cand.gx != page.gx + page.cols:
                    continue
                overlap = _span_overlap(page.gy, page.rows, cand.gy, cand.rows)
            elif dx < 0:  # left
                if cand.gx + cand.cols != page.gx:
                    continue
                overlap = _span_overlap(page.gy, page.rows, cand.gy, cand.rows)
            elif dy > 0:  # down: cand's top edge touches page's bottom edge
                if cand.gy != page.gy + page.rows:
                    continue
                overlap = _span_overlap(page.gx, page.cols, cand.gx, cand.cols)
            else:  # up
                if cand.gy + cand.rows != page.gy:
                    continue
                overlap = _span_overlap(page.gx, page.cols, cand.gx, cand.cols)

            if overlap > best_overlap:
                best_overlap = overlap
                best = cand
        return best

    def floors(self) -> list[int]:
        """Sorted unique floor ``z`` levels present in the dungeon."""
        return sorted({p.z for p in self.pages})

    def pages_on_floor(self, z: int) -> list[MapPage]:
        """All pages on floor ``z``, in manifest order."""
        return [p for p in self.pages if p.z == z]

    # ── Mutation helpers ────────────────────────────────────────────────────
    def add_page(self, page: MapPage) -> None:
        """Append ``page``; sets it as the entry page if the dungeon was empty."""
        if self.page_by_id(page.id) is not None:
            raise ValueError(f"duplicate page id: {page.id!r}")
        self.pages.append(page)
        if self.entry_page_id is None:
            self.entry_page_id = page.id

    def remove_page(self, page_id: str) -> None:
        """Remove a page. A staircase loses its end on that page: a finished one becomes
        unfinished (its other end stays placed), an unfinished one is deleted."""
        self.pages = [p for p in self.pages if p.id != page_id]
        if self.entry_page_id == page_id:
            self.entry_page_id = self.pages[0].id if self.pages else None
        kept = []
        for st in self.staircases:
            st.ends = [e for e in st.ends if e.page != page_id]
            if st.ends:
                kept.append(st)
        self.staircases = kept

    # ── Staircases ──────────────────────────────────────────────────────────
    def staircase_by_id(self, sid: int) -> Optional[Staircase]:
        for st in self.staircases:
            if st.id == sid:
                return st
        return None

    def new_staircase(self, page_id: str, cell, name: str = "", label: str = "") -> Staircase:
        """Place end A of a new, unfinished staircase and give it the next id."""
        if self.page_by_id(page_id) is None:
            raise ValueError(f"no page {page_id!r}")
        st = Staircase(id=self.next_staircase_id,
                       ends=[StaircaseEnd(page_id, (int(cell[0]), int(cell[1])))],
                       name=name, label=label)
        self.next_staircase_id += 1
        self.staircases.append(st)
        return st

    def finish_staircase(self, sid: int, page_id: str, cell) -> Staircase:
        """Place end B of an unfinished staircase. Refused (ValueError) unless the page
        is on the floor directly above or below end A's page."""
        st = self.staircase_by_id(sid)
        if st is None:
            raise ValueError(f"no staircase {sid}")
        if st.finished:
            raise ValueError(f"{st.name} already has both ends")
        a_page = self.page_by_id(st.ends[0].page)
        b_page = self.page_by_id(page_id)
        if a_page is None or b_page is None:
            raise ValueError("staircase end on a missing page")
        if abs(b_page.z - a_page.z) != 1:
            raise ValueError(f"{st.name} must end on floor {a_page.z - 1} or {a_page.z + 1}")
        st.ends.append(StaircaseEnd(page_id, (int(cell[0]), int(cell[1]))))
        return st

    def remove_staircase(self, sid: int) -> None:
        """Delete a staircase and both its ends. Its id is not reused."""
        self.staircases = [st for st in self.staircases if st.id != sid]

    def staircase_ends_on(self, page_id: str) -> list[tuple[Staircase, int]]:
        """Every ``(staircase, end_index)`` with an end on ``page_id``."""
        return [(st, i) for st in self.staircases
                for i, e in enumerate(st.ends) if e.page == page_id]

    def staircase_ends_at(self, page_id: str, cell) -> list[tuple[Staircase, int]]:
        """Every ``(staircase, end_index)`` whose end is ``cell`` on ``page_id``. Several
        staircases may share a cell (a landing that goes both up and down)."""
        c = (int(cell[0]), int(cell[1]))
        return [(st, i) for st, i in self.staircase_ends_on(page_id)
                if st.ends[i].cell == c]

    def staircase_direction(self, st: Staircase, end_index: int) -> Optional[str]:
        """"up" or "down": which way the other end lies from ``end_index``. ``None`` if
        the staircase is unfinished or broken (a missing page, or the floors are not
        adjacent, e.g. after a page was moved to another Z)."""
        other = st.other_end(end_index)
        if other is None:
            return None
        here = self.page_by_id(st.ends[end_index].page)
        there = self.page_by_id(other.page)
        if here is None or there is None:
            return None
        dz = there.z - here.z
        if dz == 1:
            return "up"
        if dz == -1:
            return "down"
        return None

    def staircase_end_global(self, end: StaircaseEnd) -> Optional[tuple[int, int, int]]:
        """An end's global ``(X, Y, Z)``, derived from its page; ``None`` if the page is gone."""
        p = self.page_by_id(end.page)
        return p.local_to_global(*end.cell) if p is not None else None

    # ── Serialization ───────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        d = {
            "version": DUNGEON_SCHEMA_VERSION,
            "entry_page_id": self.entry_page_id,
            "pages": [p.to_dict() for p in self.pages],
        }
        # Staircase keys only once the dungeon has had one, so a manifest that never
        # used them is written back unchanged.
        if self.staircases or self.next_staircase_id > 1:
            d["staircases"] = [st.to_dict() for st in self.staircases]
            d["next_staircase_id"] = int(self.next_staircase_id)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Dungeon":
        pages = [MapPage.from_dict(pd) for pd in d.get("pages", [])]
        entry = d.get("entry_page_id")
        stairs = [Staircase.from_dict(sd) for sd in d.get("staircases", [])]
        stairs = [st for st in stairs if st.ends]
        # The stored counter wins, but never below max(id) + 1, so a hand-edited or
        # truncated manifest still can't hand out a live id twice.
        nxt = max([int(d.get("next_staircase_id", 1))] + [st.id + 1 for st in stairs])
        dung = cls(pages=pages, entry_page_id=entry, staircases=stairs,
                   next_staircase_id=nxt)
        # Repair a dangling/missing entry pointer so entry_page() is always valid.
        if dung.page_by_id(entry) is None:
            dung.entry_page_id = pages[0].id if pages else None
        return dung

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Dungeon":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def _span_overlap(a0: int, a_len: int, b0: int, b_len: int) -> int:
    """Length of the 1-D overlap of ``[a0, a0+a_len)`` and ``[b0, b0+b_len)``."""
    return max(0, min(a0 + a_len, b0 + b_len) - max(a0, b0))


def dungeon_path_for(base: str) -> str:
    """The ``<name>.dungeon.json`` path for a given base name or map/agents path.

    Accepts a bare name, a ``*_agents.json`` encounter base, or a PNG path and
    returns the sibling dungeon manifest path.
    """
    d = os.path.dirname(base)
    fn = os.path.basename(base)
    if fn.endswith("_agents.json"):
        stem = fn[: -len("_agents.json")]
    else:
        stem = os.path.splitext(fn)[0]
    return os.path.join(d, stem + ".dungeon.json")
