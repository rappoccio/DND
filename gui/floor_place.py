"""Placing a floor in a dungeon's stack, without the panel (DUNGEON_WIZARD_PLAN W6,
D17–D19).

* **D17.** The first floor is floor 0 and the entry. Placing other floors never moves
  the entry's Z: a floor inserted between two others shifts the block of floors on the
  side away from the entry.
* **D18.** A floor is placed **above**, **below** or **beside** an existing floor (a
  page of it); nobody types a Z. A floor moved off a level that it alone held closes
  the gap, so the stack stays contiguous (staircases join adjacent floors).
* **D19.** Its X/Y comes from a **landmark pair** (a point on the new floor, then the
  same point on the faded floor: ``landmark_origin``), fine-tuned a cell at a time.
  **Skip** is ``default_origin``: the same corner as the floor it was placed against,
  or, beside, just east of that floor's pages.

Ladder and door-staple targets are global ``[X, Y, Z]``: every renumbering of Z here
moves them with their floor. Staircases are page-local and need nothing.
"""

from __future__ import annotations

import copy

import dungeon as dg

ABOVE, BELOW, BESIDE = "above", "below", "beside"
RELATIONS = (ABOVE, BELOW, BESIDE)


def _shift(dung: dg.Dungeon, pred, dz: int, skip: str | None) -> None:
    """Every page but ``skip`` whose Z satisfies ``pred`` moves ``dz`` floors, and every
    ladder / door-staple target on such a floor with it."""
    for p in dung.pages:
        for portal in list(p.ladders) + list(p.door_links):
            t = portal.get("target")
            if isinstance(t, list) and len(t) >= 3 and pred(int(t[2])):
                t[2] = int(t[2]) + dz
    for p in dung.pages:
        if p.id != skip and pred(p.z):
            p.origin = [p.gx, p.gy, p.z + dz]


def _entry_z(dung: dg.Dungeon, skip: str) -> int | None:
    e = dung.entry_page()
    return e.z if e is not None and e.id != skip else None


def _insert_level(dung: dg.Dungeon, lower: int, skip: str) -> int:
    """Make room for a new level between ``lower`` and ``lower + 1`` and return its Z.
    The block of floors not holding the entry moves (D17)."""
    entry = _entry_z(dung, skip)
    if entry is not None and entry > lower:
        _shift(dung, lambda z: z <= lower, -1, skip)
        return lower
    _shift(dung, lambda z: z > lower, +1, skip)
    return lower + 1


def _close_gap(dung: dg.Dungeon, z: int, skip: str) -> None:
    """Level ``z`` is empty once ``skip`` leaves it: close it up, toward the entry."""
    if any(p.z == z for p in dung.pages if p.id != skip):
        return
    entry = _entry_z(dung, skip)
    if entry is not None and entry > z:
        _shift(dung, lambda v: v < z, +1, skip)
    else:
        _shift(dung, lambda v: v > z, -1, skip)


def default_origin(dung: dg.Dungeon, page_id: str, ref_id: str, relation: str) -> list[int]:
    """D19's Skip, once the page's Z is set: above or below, the reference page's corner;
    beside, just east of the pages already on that floor, level with the reference."""
    page, ref = dung.page_by_id(page_id), dung.page_by_id(ref_id)
    if relation != BESIDE:
        return [ref.gx, ref.gy, page.z]
    others = [p for p in dung.pages_on_floor(ref.z) if p.id != page_id]
    return [max(p.gx + p.cols for p in others), ref.gy, page.z]


def place(dung: dg.Dungeon, page_id: str, ref_id: str, relation: str) -> list[int]:
    """Move ``page_id`` above / below / beside ``ref_id`` (D18), at ``default_origin``.
    Mutates ``dung``; returns the page's new origin. ``ValueError`` on a bad request."""
    page, ref = dung.page_by_id(page_id), dung.page_by_id(ref_id)
    if page is None or ref is None:
        raise ValueError("No such floor.")
    if page is ref:
        raise ValueError("A floor can't be placed against itself.")
    if relation not in RELATIONS:
        raise ValueError(f"Above, below or beside, not {relation!r}.")
    _close_gap(dung, page.z, page_id)
    if relation == BESIDE:
        z = ref.z
    else:
        want = ref.z + 1 if relation == ABOVE else ref.z - 1
        lower = ref.z if relation == ABOVE else ref.z - 1
        if any(p.z == want for p in dung.pages if p.id != page_id):
            z = _insert_level(dung, lower, page_id)
        else:
            z = want
    page.origin = [page.gx, page.gy, z]
    page.origin = default_origin(dung, page_id, ref_id, relation)
    return list(page.origin)


def preview(dung: dg.Dungeon, page_id: str, ref_id: str, relation: str) -> dg.Dungeon:
    """``place`` on a copy: the stack as it would be."""
    d = copy.deepcopy(dung)
    place(d, page_id, ref_id, relation)
    return d


def faded_floor(dung: dg.Dungeon, page_id: str, relation: str) -> tuple[list, list]:
    """What the Align step shows behind the page: ``(faded, faint)`` page lists. Above:
    the floor below; below: the floor above; beside: the other pages of its floor, with
    the floor below faint for context (D18)."""
    page = dung.page_by_id(page_id)
    if relation == BESIDE:
        same = [p for p in dung.pages_on_floor(page.z) if p.id != page_id]
        return same, dung.pages_on_floor(page.z - 1)
    z = page.z - 1 if relation == ABOVE else page.z + 1
    return dung.pages_on_floor(z), []


def landmark_origin(origin, a_local, b_world) -> list[int]:
    """D19's landmark pair: ``a_local`` is the clicked point on the new floor, in cells
    from its origin; ``b_world`` the same point on the faded floor, in global cells. The
    origin that puts the one on the other, to the nearest cell (Z kept)."""
    return [round(b_world[0] - a_local[0]), round(b_world[1] - a_local[1]), int(origin[2])]


def stack(dung: dg.Dungeon) -> list[tuple[int, list[str]]]:
    """``(z, [page ids])`` per floor, top floor first."""
    return [(z, [p.id for p in dung.pages_on_floor(z)]) for z in reversed(dung.floors())]
