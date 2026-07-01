#!/usr/bin/env python3
"""
Turn a bare battle-map PNG into a 3-5 room dungeon terrain file (standalone).

This is a self-contained command-line tool — it does NOT launch the GUI and does
NOT import the compiled engine. Given only a PNG, it:

  1. Reads the image dimensions.
  2. Figures out the grid: how many x (cols) by y (rows) cells the map is.
     By default the cell size is auto-detected from the image's own grid lines
     (falling back to the project-standard 50 px/cell); override with --cell-px.
  3. Tessellates the map into 3-5 packed rooms via binary space partitioning:
     the space is over-split into leaves, then adjacent leaves are merged so each
     room is a UNION of rectangles (L / T / plus shapes, not just rectangles).
     Adjacent rooms share a single wall and are linked by doors punched through
     those shared walls (no winding corridors). Rooms tessellate edge-to-edge —
     there is no forced rock border; the map's own detected walls (when passed as
     `blocked`) are the only exterior. Everything that is not floor is Wall.

The output is a `*_terrain.json` in the exact schema the GUI's
BattleMapViewer._load_terrain reads and that tools/encounter_generator.py's
`dungeon` mode then reads for room detection + encounter placement:

    {
      "regions": [ {"type":"Wall","x","y","width","height","multiplier":0.0}, ... ],
      "walls_enabled": false,
      "manual_grid": {"cell_px": <int>, "anchor": [<x>, <y>]},
      "doors": [ {"cells":[[c,r]], "cell":[c,r], "open":false, ...}, ... ],
      "rooms": [ {"path_index":<i>, "c","r","w","h", "cells":[[c,r],...]}, ... ]
    }

The `rooms` list records each room in walk order (path_index 0 = first room, a
top-left-to-bottom-right proxy). Because rooms are now unions of rectangles, each
entry carries an explicit `cells` list (its exact floor footprint) alongside a
`c,r,w,h` bounding box; tools/encounter_generator.py places mobs on `cells` so an
L-shaped room never bleeds into a neighbour that shares its bounding box. All
coords are in CELLS. Doors start closed (they read as Wall), so the encounter
generator still sees each room separately.

Wall rectangles are emitted in *pixel* coordinates, snapped to cell boundaries
(x = anchor_x + col*cell_px, width = ncols*cell_px), so they line up exactly
with the uniform grid recorded in manual_grid.

Examples:

    # Auto-detect grid, random 3-5 rooms, write <map>_terrain.json next to it
    python3 tools/dungeon_from_png.py encounters/mymap.png

    # Force a 50 px grid, exactly 4 rooms, reproducible, and print an ASCII map
    python3 tools/dungeon_from_png.py encounters/mymap.png \
        --cell-px 50 --rooms 4 --seed 7 --print
"""
from __future__ import annotations

import argparse
import json
import os
import random
import struct
import sys

# Floor / wall codes for the working cell grid.
FLOOR = 0
WALL = 1


# --------------------------------------------------------------------------- #
# Image size + grid detection
# --------------------------------------------------------------------------- #
def png_size_stdlib(path: str) -> tuple[int, int]:
    """Read a PNG's (width, height) straight from its IHDR chunk — no PIL."""
    with open(path, "rb") as fh:
        header = fh.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path!r} is not a PNG (bad signature)")
    # IHDR is the first chunk; width/height are big-endian uint32 at bytes 16-24.
    w, h = struct.unpack(">II", header[16:24])
    return int(w), int(h)


def image_size(path: str) -> tuple[int, int]:
    """(width, height) in pixels, via PIL if present else the PNG header."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except ImportError:
        return png_size_stdlib(path)


def detect_cell_px(path: str, lo: int = 20, hi: int = 200) -> tuple[int, float]:
    """Guess the grid pitch (px/cell) from the image's own grid lines.

    Builds 1-D gradient-magnitude projections down the columns and across the
    rows (grid lines show up as evenly spaced peaks), then picks the lag in
    [lo, hi] that maximises the normalised autocorrelation of those profiles.
    Returns (cell_px, confidence in 0..1). Needs PIL; raises ImportError without.
    """
    from PIL import Image

    with Image.open(path) as im:
        g = im.convert("L")
        # Cap work: shrink very large maps, we only need the periodicity.
        maxdim = 1600
        if max(g.size) > maxdim:
            scale = maxdim / max(g.size)
            g = g.resize((max(1, int(g.width * scale)),
                          max(1, int(g.height * scale))))
        else:
            scale = 1.0
        W, H = g.size
        px = g.load()

    # Column profile: sum of |horizontal gradient| over each column.
    col_prof = [0.0] * W
    for y in range(H):
        prev = px[0, y]
        for x in range(1, W):
            cur = px[x, y]
            col_prof[x] += abs(cur - prev)
            prev = cur
    # Row profile: sum of |vertical gradient| over each row.
    row_prof = [0.0] * H
    for x in range(W):
        prev = px[x, 0]
        for y in range(1, H):
            cur = px[x, y]
            row_prof[y] += abs(cur - prev)
            prev = cur

    def best_lag(prof: list[float]) -> tuple[int, float]:
        n = len(prof)
        mean = sum(prof) / n if n else 0.0
        cen = [v - mean for v in prof]
        denom = sum(v * v for v in cen) or 1.0
        best_k, best_v = 0, 0.0
        for k in range(lo, min(hi, n - 1) + 1):
            s = 0.0
            for i in range(n - k):
                s += cen[i] * cen[i + k]
            v = s / denom
            if v > best_v:
                best_v, best_k = v, k
        return best_k, best_v

    ck, cv = best_lag(col_prof)
    rk, rv = best_lag(row_prof)
    # Confidence-weighted blend of the two axis estimates.
    if cv <= 0 and rv <= 0:
        return 50, 0.0
    cell = round((ck * cv + rk * rv) / (cv + rv))
    cell = int(cell) / scale
    return max(1, round(cell)), max(cv, rv)


# --------------------------------------------------------------------------- #
# Dungeon carving (BSP leaves -> merged unions of rectangles on a cell grid)
# --------------------------------------------------------------------------- #
class Leaf:
    __slots__ = ("c", "r", "w", "h", "room")

    def __init__(self, c: int, r: int, w: int, h: int):
        self.c, self.r, self.w, self.h = c, r, w, h
        self.room: tuple[int, int, int, int] | None = None  # (c, r, w, h) in cells


def bsp_split(root: Leaf, n_target: int, min_leaf: int,
              rng: random.Random) -> list[Leaf]:
    """Split `root` until we have `n_target` leaves (or can't split further).

    Always splits the largest leaf, along its longer axis, at a random position
    that leaves both halves >= min_leaf. Returns the list of leaves.
    """
    leaves = [root]
    while len(leaves) < n_target:
        # Pick the largest splittable leaf.
        leaves.sort(key=lambda lf: lf.w * lf.h, reverse=True)
        split_done = False
        for lf in leaves:
            horiz = lf.w >= lf.h  # split vertical line (into left/right) if wider
            if horiz and lf.w >= 2 * min_leaf:
                cut = rng.randint(min_leaf, lf.w - min_leaf)
                a = Leaf(lf.c, lf.r, cut, lf.h)
                b = Leaf(lf.c + cut, lf.r, lf.w - cut, lf.h)
            elif not horiz and lf.h >= 2 * min_leaf:
                cut = rng.randint(min_leaf, lf.h - min_leaf)
                a = Leaf(lf.c, lf.r, lf.w, cut)
                b = Leaf(lf.c, lf.r + cut, lf.w, lf.h - cut)
            elif lf.w >= 2 * min_leaf:  # too tall to split by height, try width
                cut = rng.randint(min_leaf, lf.w - min_leaf)
                a = Leaf(lf.c, lf.r, cut, lf.h)
                b = Leaf(lf.c + cut, lf.r, lf.w - cut, lf.h)
            elif lf.h >= 2 * min_leaf:
                cut = rng.randint(min_leaf, lf.h - min_leaf)
                a = Leaf(lf.c, lf.r, lf.w, cut)
                b = Leaf(lf.c, lf.r + cut, lf.w, lf.h - cut)
            else:
                continue  # this leaf can't be split; try the next
            leaves.remove(lf)
            leaves.extend((a, b))
            split_done = True
            break
        if not split_done:
            break  # nothing left is big enough to split
    return leaves


def _leaves_adjacent(a: Leaf, b: Leaf) -> bool:
    """True if leaf rects a and b share an edge of length >= 1 cell."""
    if a.c + a.w == b.c or b.c + b.w == a.c:                  # vertical shared edge
        return min(a.r + a.h, b.r + b.h) - max(a.r, b.r) >= 1
    if a.r + a.h == b.r or b.r + b.h == a.r:                  # horizontal shared edge
        return min(a.c + a.w, b.c + b.w) - max(a.c, b.c) >= 1
    return False


def _merge_leaves(leaves: list[Leaf], n_rooms: int,
                  rng: random.Random) -> list[list[Leaf]]:
    """Group BSP leaves into `n_rooms` connected clusters, each a union of leaves.

    Repeatedly merges the smallest cluster into a random edge-adjacent neighbour
    until only `n_rooms` remain, so rooms come out as L / T / plus unions of
    rectangles rather than plain rectangles. With <= n_rooms leaves each leaf is
    its own (rectangular) room.
    """
    n = len(leaves)
    parent = list(range(n))

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:            # path-compress
            parent[i], i = root, parent[i]
        return root

    adj: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _leaves_adjacent(leaves[i], leaves[j]):
                adj[i].add(j)
                adj[j].add(i)

    def clusters() -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i in range(n):
            out.setdefault(find(i), []).append(i)
        return out

    def area(members: list[int]) -> int:
        return sum(leaves[m].w * leaves[m].h for m in members)

    while True:
        cl = clusters()
        if len(cl) <= n_rooms:
            break
        merged = False
        # Grow the smallest cluster that still has a differently-rooted neighbour;
        # this keeps room sizes even and avoids one cluster swallowing the map.
        for root, members in sorted(cl.items(), key=lambda kv: area(kv[1])):
            nbrs = {find(nb) for m in members for nb in adj[m]}
            nbrs.discard(root)
            if nbrs:
                parent[root] = rng.choice(sorted(nbrs))
                merged = True
                break
        if not merged:
            break                            # disjoint leaves (not a BSP partition)

    return [[leaves[m] for m in members] for members in clusters().values()]


def carve(cols: int, rows: int, n_rooms: int, min_room: int, margin: int,
          rng: random.Random, blocked: set[tuple[int, int]] | None = None
          ) -> tuple[list[list[int]], list[dict], list[tuple[int, int]]]:
    """Tessellate the free area into packed rooms (unions of rectangles) sharing
    single walls, linked by doors. Returns (grid, rooms, doors):

      grid   grid[r][c] is FLOOR/WALL.
      rooms  list of room dicts {"c","r","w","h","cells"} in walk order; "cells"
             is the room's exact floor footprint (list of (c,r)), "c,r,w,h" its
             bounding box.
      doors  list of (c,r) door cells.

    `blocked` is an optional set of (col,row) cells that are already wall/rock in
    the source map (e.g. the PNG's detected walls). Rooms are laid out inside the
    bounding box of the *free* (non-blocked) cells and floor is never carved into a
    blocked cell, so the map's existing walls become the dungeon's exterior. When
    `blocked` is empty the whole grid is tessellated edge-to-edge — there is no
    forced rock border, so rooms run right up to the image edge.

    `margin` is accepted for call-compatibility but ignored: packed rooms share one
    wall rather than sitting inside padded BSP leaves.
    """
    del margin  # packed rooms don't pad; kept only so callers need not change
    blocked = set(blocked or ())
    grid = [[WALL] * cols for _ in range(rows)]

    # Bounding box to tessellate. With no blocked cells use the whole grid (the
    # image edge is the only boundary — no rock border). Otherwise the blocked
    # cells (the map's own walls) are the exterior and we pack rooms up to them.
    if blocked:
        free = [(c, r) for r in range(rows) for c in range(cols)
                if (c, r) not in blocked]
        if not free:
            raise ValueError("No free cells to place rooms in (map is all walls).")
        xs = [c for c, _ in free]
        ys = [r for _, r in free]
        bc, br = min(xs), min(ys)
        bw, bh = max(xs) - bc + 1, max(ys) - br + 1
    else:
        bc, br, bw, bh = 0, 0, cols, rows

    min_leaf = min_room + 1  # a room plus the one wall it reserves on shared sides
    if bw < min_leaf or bh < min_leaf:
        raise ValueError(
            f"Free area is {bw}x{bh} cells but a room needs >= {min_leaf}. "
            f"Use a bigger image or a smaller --cell-px / --min-room.")

    # Over-split into more leaves than rooms, then merge adjacent leaves back down
    # to n_rooms clusters so each room is a union of rectangles (not a rectangle).
    n_leaves = n_rooms + rng.randint(n_rooms, 2 * n_rooms)
    leaves = bsp_split(Leaf(bc, br, bw, bh), n_leaves, min_leaf, rng)
    clusters = _merge_leaves(leaves, n_rooms, rng)

    # Walk-order proxy: top-left first, then left-to-right / top-to-bottom.
    clusters.sort(key=lambda grp: (min(lf.r for lf in grp),
                                   min(lf.c for lf in grp)))

    # Assign a room id to every free cell (-1 = blocked / outside the bbox).
    roomid = [[-1] * cols for _ in range(rows)]
    for gi, grp in enumerate(clusters):
        for lf in grp:
            for y in range(lf.r, lf.r + lf.h):
                for x in range(lf.c, lf.c + lf.w):
                    if (x, y) not in blocked:
                        roomid[y][x] = gi

    # Carve floor. A cell becomes the single shared WALL between two rooms when a
    # DIFFERENT room lies directly to its left or above (that room donates its left
    # column / top row as the shared wall). A cell whose left/top neighbour is
    # outside the bbox or blocked gets no wall, so rooms run flush to the edge.
    for y in range(rows):
        for x in range(cols):
            gi = roomid[y][x]
            if gi < 0:
                continue                     # blocked / outside stays WALL
            shared = ((x > 0 and roomid[y][x - 1] >= 0 and roomid[y][x - 1] != gi)
                      or (y > 0 and roomid[y - 1][x] >= 0 and roomid[y - 1][x] != gi))
            grid[y][x] = WALL if shared else FLOOR

    def is_floor(x: int, y: int) -> bool:
        return 0 <= y < rows and 0 <= x < cols and grid[y][x] == FLOOR

    # Door candidates: a WALL cell that touches the floor of two different rooms
    # among its 4 orthogonal neighbours can host a door joining them. One door per
    # adjacent room pair connects the whole dungeon (the room graph is a connected
    # quotient of the BSP partition); extra shared-wall pairs just add loops.
    from itertools import combinations
    cand: dict[frozenset[int], list[tuple[int, int]]] = {}
    for y in range(rows):
        for x in range(cols):
            if grid[y][x] != WALL:
                continue
            touch: set[int] = set()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if is_floor(x + dx, y + dy):
                    touch.add(roomid[y + dy][x + dx])
            touch.discard(-1)
            for a, b in combinations(sorted(touch), 2):
                cand.setdefault(frozenset((a, b)), []).append((x, y))

    # Punch each chosen door to FLOOR (so it's excluded from the wall rects); the
    # door object itself starts closed, which re-blocks the cell until opened.
    doors: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for cells in cand.values():
        c = rng.choice(cells)
        if c in seen:
            continue
        grid[c[1]][c[0]] = FLOOR
        doors.append(c)
        seen.add(c)

    # Room footprints: exact floor cells (minus donated walls) + a bounding box.
    rooms: list[dict] = []
    substantial = 0
    for gi in range(len(clusters)):
        cells = [(x, y) for y in range(rows) for x in range(cols)
                 if roomid[y][x] == gi and grid[y][x] == FLOOR]
        if not cells:
            continue
        xs = [c for c, _ in cells]
        ys = [r for _, r in cells]
        c0, r0 = min(xs), min(ys)
        rooms.append({"c": c0, "r": r0,
                      "w": max(xs) - c0 + 1, "h": max(ys) - r0 + 1,
                      "cells": cells})
        if len(cells) >= max(1, min_room * min_room // 2):
            substantial += 1

    if substantial < 3:
        raise ValueError(
            f"Only laid out {substantial} sizeable room(s); need at least 3. Try a "
            f"bigger image, a smaller --cell-px / --min-room, or fewer blocked cells.")

    return grid, rooms, doors


# --------------------------------------------------------------------------- #
# Wall mask -> minimal-ish set of rectangles
# --------------------------------------------------------------------------- #
def wall_rects(grid: list[list[int]]) -> list[tuple[int, int, int, int]]:
    """Greedily cover all WALL cells with axis-aligned rectangles (in cells)."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    used = [[False] * cols for _ in range(rows)]
    rects: list[tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] != WALL or used[r][c]:
                continue
            # Extend as far right as possible on this row.
            w = 0
            while c + w < cols and grid[r][c + w] == WALL and not used[r][c + w]:
                w += 1
            # Extend down as far as every row across [c, c+w) stays wall/free.
            h = 1
            while r + h < rows:
                ok = all(grid[r + h][c + k] == WALL and not used[r + h][c + k]
                         for k in range(w))
                if not ok:
                    break
                h += 1
            for y in range(r, r + h):
                for x in range(c, c + w):
                    used[y][x] = True
            rects.append((c, r, w, h))
    return rects


# --------------------------------------------------------------------------- #
# Rendering / output
# --------------------------------------------------------------------------- #
def render_ascii(grid: list[list[int]], rooms, doors=()) -> str:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    syms = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    door_of = set(doors)
    room_of: dict[tuple[int, int], str] = {}
    for i, room in enumerate(rooms):
        s = syms[i] if i < len(syms) else "*"
        for (x, y) in room["cells"]:
            room_of[(x, y)] = s
    lines = []
    for r in range(rows):
        row = []
        for c in range(cols):
            if (c, r) in door_of:
                row.append("+")  # door in a shared wall
            elif grid[r][c] == WALL:
                row.append("#")
            elif (c, r) in room_of:
                row.append(room_of[(c, r)])
            else:
                row.append(".")  # floor not claimed by a room rect
        lines.append("".join(row))
    return "\n".join(lines)


def parse_rooms_arg(val: str, rng: random.Random) -> int:
    """--rooms accepts an int (exact) or 'A-B' (inclusive random range)."""
    val = val.strip()
    if "-" in val:
        a, b = val.split("-", 1)
        return rng.randint(int(a), int(b))
    return int(val)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a 3-5 room dungeon terrain.json from a PNG map.")
    ap.add_argument("png", help="input battle-map PNG")
    ap.add_argument("--out", help="output terrain json "
                    "(default: <png-without-ext>_terrain.json)")
    ap.add_argument("--cell-px", type=int, default=None,
                    help="pixels per cell (default: auto-detect, fallback 50)")
    ap.add_argument("--anchor", type=int, nargs=2, metavar=("X", "Y"),
                    default=(0, 0), help="grid origin in pixels (default 0 0)")
    ap.add_argument("--rooms", default="3-5",
                    help="room count: an int or 'MIN-MAX' range (default 3-5)")
    ap.add_argument("--min-room", type=int, default=3,
                    help="minimum room side in cells (default 3)")
    ap.add_argument("--margin", type=int, default=1,
                    help="wall cells between a room and its BSP cell edge (default 1)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed")
    ap.add_argument("--force", action="store_true",
                    help="overwrite the output file if it already exists")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print an ASCII preview of the dungeon")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.png):
        ap.error(f"no such file: {args.png}")

    rng = random.Random(args.seed)
    W, H = image_size(args.png)

    # ---- grid ----
    if args.cell_px:
        cell_px, note = args.cell_px, "from --cell-px"
    else:
        try:
            cell_px, conf = detect_cell_px(args.png)
            if conf < 0.02:  # weak signal — fall back to the project default
                cell_px, note = 50, f"auto-detect weak (conf={conf:.3f}), using 50"
            else:
                note = f"auto-detected (conf={conf:.3f})"
        except ImportError:
            cell_px, note = 50, "PIL unavailable, using default 50"

    ax, ay = int(args.anchor[0]), int(args.anchor[1])
    cols = (W - ax) // cell_px
    rows = (H - ay) // cell_px
    if cols < 5 or rows < 5:
        ap.error(f"grid too small: {cols}x{cols} cells at {cell_px}px "
                 f"(image {W}x{H}). Try a smaller --cell-px.")

    n_rooms = parse_rooms_arg(args.rooms, rng)
    try:
        grid, rooms, doors = carve(cols, rows, n_rooms, args.min_room,
                                   args.margin, rng)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # ---- wall rects -> pixel-space regions ----
    regions = []
    for (c, r, w, h) in wall_rects(grid):
        regions.append({
            "type": "Wall",
            "x": ax + c * cell_px,
            "y": ay + r * cell_px,
            "width": w * cell_px,
            "height": h * cell_px,
            "multiplier": 0.0,
        })

    terrain = {
        "regions": regions,
        "walls_enabled": False,
        "manual_grid": {"cell_px": cell_px, "anchor": [ax, ay]},
        # Doors start closed so the encounter generator's flood fill still sees each
        # room separately. "cells" (a list) round-trips wide doors; "cell" is kept
        # for backward readability. These are single-cell doorways.
        "doors": [
            {"cells": [[c, r]], "cell": [c, r], "open": False,
             "locked": False, "lock_dc": 15, "arcane_lock": False}
            for (c, r) in doors
        ],
        # Rooms in walk order (top-left-to-bottom-right proxy). The encounter
        # generator reads "cells" (the exact footprint) to place mobs and ramps
        # difficulty deeper into the dungeon; the GUI ignores the key. Rooms are
        # unions of rectangles, so "c,r,w,h" is only the bounding box. CELL coords.
        "rooms": [
            {"path_index": i, "c": rm["c"], "r": rm["r"], "w": rm["w"], "h": rm["h"],
             "cells": [[c, r] for (c, r) in rm["cells"]]}
            for i, rm in enumerate(rooms)
        ],
    }

    out = args.out or (os.path.splitext(args.png)[0] + "_terrain.json")
    if os.path.exists(out) and not args.force:
        print(f"error: {out} already exists; pass --force to overwrite "
              f"or --out to write elsewhere", file=sys.stderr)
        return 1
    with open(out, "w") as fh:
        json.dump(terrain, fh, indent=2)

    print(f"image      : {args.png}  ({W}x{H} px)")
    print(f"grid       : {cols} x {rows} cells @ {cell_px}px/cell ({note})")
    print(f"rooms      : {len(rooms)}  (requested {n_rooms})")
    print(f"doors      : {len(doors)}")
    print(f"wall rects : {len(regions)}")
    print(f"wrote      : {out}")
    if args.show:
        print()
        print(render_ascii(grid, rooms, doors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
