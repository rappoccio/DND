#!/usr/bin/env python3
"""
Random encounter + dungeon generator for the DND battle-map engine (standalone).

This is a self-contained command-line tool — it does NOT launch the GUI. It reads
the authoritative bestiary (gui/DND2024_MonsterStats.json) and, for the dungeon
mode, imports the built rpg_battle_map extension to read a map's grid + Wall
terrain. Everything it writes uses the exact schema BattleMapViewer._load_agents
reads, so the generated *_agents.json files load directly in the GUI.

Two sub-commands:

  encounter  Emit one random encounter of a chosen category (A-E) at a target
             challenge rating x, as a loadable *_agents.json.

  dungeon    Given a map image + its *_terrain.json, resolve the rooms in walk
             order (dungeon_from_png room metadata if present, else flood-fill +
             a distance heuristic), drop one random encounter into each with the
             category weights ramping from --difficulty-start up to --difficulty
             as the player goes deeper, force a boss (category E) into the last
             room, and write a combined *_agents.json plus a copied *_terrain.json.

Encounter categories (x = target CR):

  A: 4-5 x (CR x-4, Simple)
  B: 2-3 x (CR x-4, Simple)  + 1-2 x (CR x-2, PreferRange)
  C: 1-2 x (CR x-2, Simple)  + 1-2 x (CR x-2, PreferRange)
  D: 1-2 x (CR x-2, Simple)  + 1   x (CR x-2, PreferAOE)
  E: 2-3 x (CR x-2, Simple)  + 1-2 x (CR x-2, PreferRange) + 1 Dragon (CR <= x, PreferAOE)

Mob counts are drawn uniformly from the stated ranges.

Difficulty -> category weights (A:B:C:D:E):

  Easy    3:1:0:0:0
  Medium  3:2:1:1:1
  Hard    0:1:2:2:1

In dungeon mode these rows are the ENDPOINTS of a per-room ramp: room i of N
uses weights linearly blended from --difficulty-start (room 0) to --difficulty
(room N-1), so encounters skew harder deeper in. The deepest room is forced to a
category-E boss unless --no-boss is passed. CR stays uniform (single --cr).
"""

from __future__ import annotations

import argparse
import bisect
import copy
import datetime
import json
import os
import random
import struct
import sys
from collections import defaultdict

# ── Paths ────────────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_THIS_DIR)
_GUI_DIR = os.path.join(_REPO, "gui")
_SPRITES_DIR = os.path.join(_REPO, "sprites")

# ── Constants mirrored from the C++ engine ──────────────────────────────────
# NpcAutomationStrategy (battle_map.hpp). Kept as plain ints so the encounter
# builder needs no rpg import (only the dungeon mode imports the extension).
STRAT_SIMPLE = 0
STRAT_PREFER_AOE = 2
STRAT_PREFER_RANGE = 3

_STRAT_NAME = {STRAT_SIMPLE: "Simple", STRAT_PREFER_AOE: "PreferAOE",
               STRAT_PREFER_RANGE: "PreferRange"}

# D&D size category -> square footprint in cells (main.py _size_category_to_grid_size).
SIZE_MAP = {"Small": 1, "Tiny": 1, "Medium": 1, "Large": 2, "Huge": 3, "Gargantuan": 4}

# Faction assigned to every generated mob (all hostile to the party). 0 = neutral,
# 1+ = a team; the party is expected to be a different faction.
ENEMY_FACTION = 1

# ── Encounter category table ────────────────────────────────────────────────
# Each category is a list of "mob requests":
#   (cr_offset, strategy, kind, count_lo, count_hi)
# cr_offset is added to the target CR x (clamped at 0). kind constrains the
# candidate pool: 'any' = any monster at that CR; 'ranged' = must have a ranged
# weapon; 'aoe' = must have an area spell / breath weapon; 'dragon' = any dragon
# with CR <= x (cr_offset ignored).
CATEGORY_TABLE: dict[str, list[tuple[int, int, str, int, int]]] = {
    "A": [(-4, STRAT_SIMPLE, "any", 4, 5)],
    "B": [(-4, STRAT_SIMPLE, "any", 2, 3),
          (-2, STRAT_PREFER_RANGE, "ranged", 1, 2)],
    "C": [(-2, STRAT_SIMPLE, "any", 1, 2),
          (-2, STRAT_PREFER_RANGE, "ranged", 1, 2)],
    "D": [(-2, STRAT_SIMPLE, "any", 1, 2),
          (-2, STRAT_PREFER_AOE, "aoe", 1, 1)],
    "E": [(-2, STRAT_SIMPLE, "any", 2, 3),
          (-2, STRAT_PREFER_RANGE, "ranged", 1, 2),
          (0, STRAT_PREFER_AOE, "dragon", 1, 1)],
}

# Difficulty -> per-category integer weights.
DIFFICULTY_WEIGHTS: dict[str, dict[str, int]] = {
    "Easy":   {"A": 3, "B": 1, "C": 0, "D": 0, "E": 0},
    "Medium": {"A": 3, "B": 2, "C": 1, "D": 1, "E": 1},
    "Hard":   {"A": 0, "B": 1, "C": 2, "D": 2, "E": 1},
}


# ── Challenge-rating helpers ────────────────────────────────────────────────
def cr_to_float(cr) -> float | None:
    """Parse a bestiary CR string ('0', '1/8', '1/4', '1/2', '5', ...) to a float."""
    if cr is None:
        return None
    s = str(cr).strip()
    if not s or s.lower() == "none":
        return None
    if "/" in s:
        num, den = s.split("/", 1)
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Bestiary ────────────────────────────────────────────────────────────────
class Bestiary:
    """The monster records + a few cheap indexes for candidate selection."""

    def __init__(self, data_dir: str = _GUI_DIR):
        with open(os.path.join(data_dir, "DND2024_MonsterStats.json")) as f:
            self.mobs: dict[str, dict] = json.load(f)

        # Names of every non-single-target spell -> flags a monster as an AOE user.
        self.aoe_spell_names: set[str] = set()
        spells_path = os.path.join(data_dir, "spells.json")
        if os.path.exists(spells_path):
            with open(spells_path) as f:
                for sp in json.load(f):
                    if sp.get("geometry", "Single") != "Single":
                        self.aoe_spell_names.add(sp.get("name"))

        # cr_float -> [name, ...]; also stash _cr on each record.
        self.by_cr: dict[float, list[str]] = defaultdict(list)
        # Collect unique base types (without subtypes) and languages.
        self.all_types: set[str] = set()
        self.all_languages: set[str] = set()
        for name, rec in self.mobs.items():
            cr = cr_to_float(rec.get("meta", {}).get("cr"))
            rec["_cr"] = cr
            if cr is not None:
                self.by_cr[cr].append(name)
            meta = rec.get("meta", {})
            t = meta.get("type")
            if t:
                # Store only the base type (before parentheses)
                base_type = t.split("(")[0].strip()
                self.all_types.add(base_type)
            langs = meta.get("languages", [])
            for lang in langs:
                self.all_languages.add(lang)
        self._crs_sorted = sorted(self.by_cr.keys())

    # ── candidate predicates ────────────────────────────────────────────────
    @staticmethod
    def is_dragon(rec: dict) -> bool:
        return "Dragon" in (rec.get("meta", {}).get("type") or "")

    @staticmethod
    def has_ranged(rec: dict) -> bool:
        rng = rec.get("weapons", {}).get("ranged")
        return isinstance(rng, dict) and bool(rng.get("name"))

    def has_aoe(self, rec: dict) -> bool:
        if rec.get("npc_spell_recharge"):        # a recharge breath weapon
            return True
        return any(n in self.aoe_spell_names for n in rec.get("spell_indices", []))

    @staticmethod
    def _base_type(type_str: str) -> str:
        """Extract the base type (before parentheses). E.g., 'Dragon (Chromatic)' -> 'Dragon'."""
        if not type_str:
            return ""
        return type_str.split("(")[0].strip()

    def _matches_type_filter(self, mob_type: str, filter_types: str | list[str]) -> bool:
        """Check if mob_type matches any of the filter_types or has the same base type.

        filter_types can be a single string or a list of strings.
        """
        if not mob_type:
            return False
        if isinstance(filter_types, str):
            filter_types = [filter_types]
        if not filter_types:
            return False

        mob_base = self._base_type(mob_type)
        for ft in filter_types:
            # Exact match
            if mob_type == ft:
                return True
            # Base type match (e.g., "Aberration" matches "Aberration (Beholder)")
            if mob_base == ft:
                return True
        return False

    def _pool(self, cr: float, kind: str, x_float: float,
              filter_types: str | list[str] | None = None, filter_languages: list[str] | None = None) -> list[str]:
        """Names matching `kind` at exactly challenge rating `cr` (dragon ignores cr).

        If filter_types is set (string or list), only return mobs whose meta.type matches any of them.
        If filter_languages is set, only return mobs that have at least one of those languages.
        """
        if kind == "dragon":
            candidates = [n for n, r in self.mobs.items()
                         if r.get("_cr") is not None and r["_cr"] <= x_float
                         and self.is_dragon(r)]
        else:
            candidates = list(self.by_cr.get(cr, []))

        out = []
        for name in candidates:
            rec = self.mobs[name]
            if kind == "ranged" and not self.has_ranged(rec):
                continue
            if kind == "aoe" and not self.has_aoe(rec):
                continue
            if filter_types:
                mob_type = rec.get("meta", {}).get("type")
                if not self._matches_type_filter(mob_type, filter_types):
                    continue
            if filter_languages:
                mob_langs = rec.get("meta", {}).get("languages", [])
                if not any(lang in mob_langs for lang in filter_languages):
                    continue
            out.append(name)
        return out

    def pick(self, cr: float, kind: str, x_float: float,
             rng: random.Random, count: int,
             filter_types: str | list[str] | None = None, filter_languages: list[str] | None = None,
             avoid: set[str] | None = None) -> list[str]:
        """Pick `count` monster names, preferring VARIETY over a monoculture pack.

        Draws favour species not already used elsewhere (`avoid`, e.g. other rooms
        of the same dungeon) and not already drawn in this call, only repeating a
        species once the distinct options are exhausted — so the same mob no longer
        floods every room. Falls back to the nearest CR (or, for dragons, the
        lowest-CR dragon) when the exact CR has no monster that satisfies `kind`."""
        pool = self._pool(cr, kind, x_float, filter_types, filter_languages)
        if not pool:
            if kind == "dragon":
                dragons = [(r["_cr"], n) for n, r in self.mobs.items()
                           if r.get("_cr") is not None and self.is_dragon(r)]
                if filter_types:
                    dragons = [(cr_val, n) for cr_val, n in dragons
                              if self._matches_type_filter(self.mobs[n].get("meta", {}).get("type"), filter_types)]
                if filter_languages:
                    dragons = [(cr_val, n) for cr_val, n in dragons
                              if any(lang in self.mobs[n].get("meta", {}).get("languages", [])
                                    for lang in filter_languages)]
                if dragons:
                    pool = [min(dragons)[1]]        # lowest-CR dragon overall
            else:
                for near in sorted(self._crs_sorted, key=lambda c: (abs(c - cr), c)):
                    pool = self._pool(near, kind, x_float, filter_types, filter_languages)
                    if pool:
                        break
        if not pool:
            return []
        avoid = avoid or set()
        # Names not used in earlier rooms are the first-choice pool; the whole pool
        # is the fallback when every candidate has already appeared.
        preferred = [n for n in pool if n not in avoid]
        result: list[str] = []
        used_here: set[str] = set()
        for _ in range(count):
            # Prefer: unused elsewhere AND not yet drawn here -> unused elsewhere
            # -> not yet drawn here -> anything in the pool.
            choices = ([n for n in preferred if n not in used_here]
                       or preferred
                       or [n for n in pool if n not in used_here]
                       or pool)
            nm = rng.choice(choices)
            result.append(nm)
            used_here.add(nm)
        return result


# ── Sprite selection ─────────────────────────────────────────────────────────
def sprite_for_name(name: str) -> str:
    """Return the sprite FILENAME for a mob, mirroring the GUI's
    _get_mob_sprite_path: a specific '<name>.png' if one exists in sprites/, else
    the first-letter sprite '<L>.png' (e.g. 'Goblin' -> 'G.png'). Stored as a bare
    filename because _load_agents joins sprite_path with the GUI's sprites_dir."""
    if not name:
        return ""
    specific = f"{name}.png"
    if os.path.exists(os.path.join(_SPRITES_DIR, specific)):
        return specific
    return f"{name[0].upper()}.png"


# ── Agent record construction ───────────────────────────────────────────────
def make_agent(rec: dict, strategy: int, faction: int, automation_level: int) -> dict:
    """Build a save-format agent dict from a bestiary record (col/row set later).

    The bestiary stats/weapons/spell blocks are already in the exact shape
    _load_agents reads (dict_to_stats, _dict_to_weapon, spell_indices +
    npc_spell_groups), so they are copied verbatim."""
    return {
        "name": rec["name"],
        "sprite_path": sprite_for_name(rec["name"]),
        "size": SIZE_MAP.get(rec.get("size", "Medium"), 1),
        "col": 0,
        "row": 0,
        "faction": faction,
        "on_deck": True,
        "is_npc_automated": True,
        "npc_automation_difficulty_level": automation_level,
        "npc_automation_strategy": int(strategy),
        "stats": copy.deepcopy(rec["stats"]),
        "weapons": copy.deepcopy(rec.get("weapons", {})),
        "spell_indices": list(rec.get("spell_indices", [])),
        "is_npc": True,
        "npc_spell_groups": copy.deepcopy(rec.get("npc_spell_groups", {})),
        "npc_spell_recharge": copy.deepcopy(rec.get("npc_spell_recharge", {})),
    }


def build_encounter(category: str, x: int, bestiary: Bestiary, rng: random.Random,
                    faction: int = ENEMY_FACTION,
                    automation_level: int = 1,
                    filter_types: str | list[str] | None = None,
                    filter_languages: list[str] | None = None,
                    avoid: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Build the agent list for one encounter of `category` at target CR `x`.

    Returns (agents, detail) where detail describes each mob group for logging.
    If filter_types is set (string or list), all mobs will be of those types.
    If filter_languages is set, all mobs will speak at least one of those languages.
    `avoid` is a set of species names already used (e.g. earlier dungeon rooms);
    picks steer away from them and every newly chosen species is added to it so a
    multi-room caller keeps diversifying."""
    if category not in CATEGORY_TABLE:
        raise ValueError(f"Unknown category {category!r} (expected one of A-E)")
    x_float = float(x)
    agents: list[dict] = []
    detail: list[dict] = []
    for offset, strat, kind, lo, hi in CATEGORY_TABLE[category]:
        count = rng.randint(lo, hi)
        target_cr = None if kind == "dragon" else max(0.0, x_float + offset)
        names = bestiary.pick(target_cr if target_cr is not None else x_float,
                              kind, x_float, rng, count,
                              filter_types=filter_types, filter_languages=filter_languages,
                              avoid=avoid)
        if avoid is not None:
            avoid.update(names)
        for nm in names:
            agents.append(make_agent(bestiary.mobs[nm], strat, faction, automation_level))
        detail.append({
            "count": len(names),
            "requested": count,
            "cr": ("<=%g" % x_float) if kind == "dragon" else target_cr,
            "kind": kind,
            "strategy": _STRAT_NAME.get(strat, str(strat)),
            "monsters": names,
        })
    return agents, detail


# ── PNG size (dependency-free) ──────────────────────────────────────────────
def png_size(path: str) -> tuple[int, int] | None:
    """Return (width, height) of a PNG, or None if it can't be read as PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None


# ── Map / terrain loading (dungeon mode) ────────────────────────────────────
def load_battlemap(map_path: str, terrain_path: str | None):
    """Load a map through the C++ engine, apply the terrain file, and return
    (bm, terrain_dict, rpg_module)."""
    if _GUI_DIR not in sys.path:
        sys.path.insert(0, _GUI_DIR)
    import rpg_battle_map as rpg  # type: ignore

    bm = rpg.BattleMap(map_path)
    bm.analyze_grid()
    bm.detect_walls()

    terrain: dict = {}
    if terrain_path and os.path.exists(terrain_path):
        with open(terrain_path) as f:
            terrain = json.load(f)
        _apply_terrain(bm, terrain, map_path, rpg)
    return bm, terrain, rpg


def _apply_terrain(bm, terrain: dict, map_path: str, rpg) -> None:
    """Replicate main.py's terrain application for the blocking types that matter
    to room detection + placement (Wall/Chasm/Water + closed doors). Difficult
    Terrain multipliers are ignored (they don't block)."""
    mg = terrain.get("manual_grid")
    if mg:
        try:
            bm.set_uniform_grid(int(mg["cell_px"]), int(mg["anchor"][0]), int(mg["anchor"][1]))
        except Exception:
            pass

    size = png_size(map_path)
    if size:
        mw, mh = size
        scale = min((1860 - 340) / mw, 1040 / mh, 1.0)   # main.py auto-fit scale
    else:
        scale = 1.0

    raw_v = list(bm.v_line_positions)
    raw_h = list(bm.h_line_positions)

    def px_to_cells(px, py, pw, ph):
        if not raw_v or not raw_h or pw <= 0 or ph <= 0:
            return None
        ix, iy = px / scale, py / scale
        iw, ih = pw / scale, ph / scale
        c0 = max(0, bisect.bisect_right(raw_v, ix) - 1)
        r0 = max(0, bisect.bisect_right(raw_h, iy) - 1)
        c1 = min(bm.grid_cols - 1, bisect.bisect_right(raw_v, ix + iw) - 1)
        r1 = min(bm.grid_rows - 1, bisect.bisect_right(raw_h, iy + ih) - 1)
        return c0, r0, c1, r1

    type_map = {"Wall": rpg.TerrainType.Wall,
                "Chasm": rpg.TerrainType.Chasm,
                "Water": rpg.TerrainType.Water}
    for reg in terrain.get("regions", []):
        ttype = reg.get("type", "Difficult Terrain")
        if ttype not in type_map:
            continue
        rng = px_to_cells(reg.get("x", 0), reg.get("y", 0),
                          reg.get("width", 0), reg.get("height", 0))
        if not rng:
            continue
        c0, r0, c1, r1 = rng
        for c in range(c0, c1 + 1):
            for r in range(r0, r1 + 1):
                bm.set_terrain_type(rpg.Cell(c, r), type_map[ttype])

    # Closed doors read as Wall (matches the GUI's door-terrain behaviour).
    for d in terrain.get("doors", []):
        if d.get("open", False):
            continue
        cells = d.get("cells") or ([d["cell"]] if "cell" in d else [])
        for c in cells:
            try:
                bm.set_terrain_type(rpg.Cell(int(c[0]), int(c[1])), rpg.TerrainType.Wall)
            except Exception:
                continue


# ── Room detection ──────────────────────────────────────────────────────────
def detect_rooms(bm, rpg, min_floor_cells: int) -> list[list[tuple[int, int]]]:
    """Flood-fill floor into rooms. Boundaries are Wall cells only (painted Wall
    or auto-detected wall) — Water/Chasm do NOT split a room, but they aren't
    valid mob-placement cells either. Returns a list of rooms, each a list of the
    room's *placeable* (Standard floor) cells. Only rooms with at least
    `min_floor_cells` placeable cells are kept."""
    cols, rows = bm.grid_cols, bm.grid_rows
    water_chasm = (rpg.TerrainType.Water, rpg.TerrainType.Chasm)

    # Per-cell: (is_wall, placeable, connective). connective = not a wall.
    grid: list[list[tuple[bool, bool, bool]]] = [[(True, False, False)] * rows
                                                 for _ in range(cols)]
    for c in range(cols):
        for r in range(rows):
            cell = rpg.Cell(c, r)
            blocked = bm.is_blocked(cell, 1)             # Walk: Wall/Water/Chasm/detected
            is_wc = bm.get_terrain_type(cell) in water_chasm
            is_wall = blocked and not is_wc              # painted Wall or auto-detected
            grid[c][r] = (is_wall, not blocked, not is_wall)

    seen = [[False] * rows for _ in range(cols)]
    rooms: list[list[tuple[int, int]]] = []
    for sc in range(cols):
        for sr in range(rows):
            if seen[sc][sr]:
                continue
            if not grid[sc][sr][2]:      # a wall cell — nothing to flood
                seen[sc][sr] = True
                continue
            comp: list[tuple[int, int]] = []
            stack = [(sc, sr)]
            seen[sc][sr] = True
            while stack:
                cc, rr = stack.pop()
                comp.append((cc, rr))
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nc, nr = cc + dc, rr + dr
                    if 0 <= nc < cols and 0 <= nr < rows and not seen[nc][nr] \
                            and grid[nc][nr][2]:
                        seen[nc][nr] = True
                        stack.append((nc, nr))
            floor = [(cc, rr) for (cc, rr) in comp if grid[cc][rr][1]]
            if len(floor) >= min_floor_cells:
                rooms.append(floor)
    return rooms


# Symbols for the dry-run ASCII map: rooms are 0-9 then A-Z, then '*' if more.
_ROOM_SYMBOLS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def render_room_map(bm, rpg, rooms: list[list[tuple[int, int]]]) -> list[str]:
    """Render an ASCII picture of the grid for --dry-run calibration.

    Each kept room's floor prints as its index symbol (0-9, A-Z, then '*');
    '#' = wall (painted or auto-detected), '~' = water/chasm, '.' = floor that
    was too small to count as a room (below --min-room)."""
    cols, rows = bm.grid_cols, bm.grid_rows
    water_chasm = (rpg.TerrainType.Water, rpg.TerrainType.Chasm)
    room_of: dict[tuple[int, int], int] = {}
    for i, floor in enumerate(rooms):
        for cell in floor:
            room_of[cell] = i

    lines: list[str] = []
    for r in range(rows):
        chars: list[str] = []
        for c in range(cols):
            if (c, r) in room_of:
                idx = room_of[(c, r)]
                chars.append(_ROOM_SYMBOLS[idx] if idx < len(_ROOM_SYMBOLS) else "*")
                continue
            cell = rpg.Cell(c, r)
            if bm.get_terrain_type(cell) in water_chasm:
                chars.append("~")
            elif bm.is_blocked(cell, 1):
                chars.append("#")
            else:
                chars.append(".")
        lines.append("".join(chars))
    return lines


# ── Room ordering + difficulty ramp (dungeon mode) ──────────────────────────
def _room_centroid(floor: list[tuple[int, int]]) -> tuple[float, float]:
    n = len(floor) or 1
    return (sum(c for c, _ in floor) / n, sum(r for _, r in floor) / n)


def rooms_from_metadata(bm, rpg, terrain: dict,
                        min_floor_cells: int) -> list[list[tuple[int, int]]] | None:
    """Build ordered rooms straight from dungeon_from_png's room footprints.

    Each terrain["rooms"] entry has a path_index (walk order) and describes a room
    that may be a UNION of rectangles: it carries an explicit "cells" footprint
    (preferred) plus a "c,r,w,h" bounding box (fallback for older files). We
    collect the placeable (unblocked) floor cells of each room and return them
    sorted by path_index. Using "cells" keeps an L-shaped room from bleeding into a
    neighbour that shares its bounding box. This sidesteps flood-fill — whose doors
    would merge a generated dungeon into one blob — and yields an authoritative
    walk order. Returns None when the terrain carries no room metadata."""
    meta = terrain.get("rooms")
    if not meta:
        return None
    cols, rows = bm.grid_cols, bm.grid_rows
    rooms: list[list[tuple[int, int]]] = []
    for m in sorted(meta, key=lambda d: d.get("path_index", 0)):
        cells = m.get("cells")
        if cells:
            candidates = [(int(c), int(r)) for c, r in cells]
        else:
            c0, r0 = int(m.get("c", 0)), int(m.get("r", 0))
            w, h = int(m.get("w", 0)), int(m.get("h", 0))
            candidates = [(c, r)
                          for c in range(c0, c0 + w)
                          for r in range(r0, r0 + h)]
        floor = [(c, r) for (c, r) in candidates
                 if 0 <= c < cols and 0 <= r < rows
                 and not bm.is_blocked(rpg.Cell(c, r), 1)]
        if len(floor) >= min_floor_cells:
            rooms.append(floor)
    return rooms


def order_rooms_by_distance(rooms: list[list[tuple[int, int]]], bm,
                            entrance: tuple[int, int] | None
                            ) -> list[list[tuple[int, int]]]:
    """Fallback ordering for maps without room metadata (e.g. hand-drawn dungeons
    whose rooms are separate wall-bounded components). Orders rooms by the squared
    distance of their centroid from the entrance. The entrance is the given cell
    if provided, else the centroid of the room nearest any map border."""
    if not rooms:
        return []
    if entrance is None:
        def border_gap(floor):
            cx, cy = _room_centroid(floor)
            return min(cx, cy, (bm.grid_cols - 1) - cx, (bm.grid_rows - 1) - cy)
        ex, ey = _room_centroid(min(rooms, key=border_gap))
    else:
        ex, ey = float(entrance[0]), float(entrance[1])

    def dist2(floor):
        cx, cy = _room_centroid(floor)
        return (cx - ex) ** 2 + (cy - ey) ** 2

    return sorted(rooms, key=dist2)


def order_dungeon_rooms(bm, rpg, terrain: dict, min_room: int,
                        entrance: tuple[int, int] | None
                        ) -> tuple[list[list[tuple[int, int]]], str]:
    """Return (ordered_rooms, human description of how they were ordered)."""
    meta_rooms = rooms_from_metadata(bm, rpg, terrain, min_room)
    if meta_rooms is not None:
        return meta_rooms, "terrain room metadata (corridor-chain walk order)"
    rooms = detect_rooms(bm, rpg, min_room)
    if not rooms:
        return [], "no rooms detected"
    ordered = order_rooms_by_distance(rooms, bm, entrance)
    how = (f"distance from entrance {entrance}" if entrance
           else "distance-from-border heuristic (no metadata)")
    return ordered, how


def ramp_weights(start_row: dict[str, int], end_row: dict[str, int],
                 i: int, n: int) -> dict[str, int]:
    """Linearly blend two A:B:C:D:E weight rows: start_row at the entrance (i=0)
    to end_row at the deepest room (i=n-1). A single-room dungeon uses end_row."""
    t = 1.0 if n <= 1 else i / (n - 1)
    out = {k: max(0, round(start_row.get(k, 0)
                           + (end_row.get(k, 0) - start_row.get(k, 0)) * t))
           for k in end_row}
    if sum(out.values()) <= 0:          # degenerate blend — fall back to the peak row
        out = dict(end_row)
    return out


def build_dungeon(bm, rpg, terrain: dict, bestiary: Bestiary, *, cr: int,
                  difficulty_start: str, difficulty_end: str, min_room: int,
                  boss: bool, entrance: tuple[int, int] | None,
                  automation_level: int, rng: random.Random, place: bool,
                  filter_types: str | list[str] | None = None,
                  filter_languages: list[str] | None = None
                  ) -> tuple[list[list[tuple[int, int]]], list[dict], str]:
    """Order the rooms, ramp the category weights start->end along the walk order,
    force a boss (category E) into the last room, and build one encounter per room.

    Returns (ordered_rooms, results, order_note). Each result dict has:
      room, is_boss, category, weights (None for the boss), floor_cells,
      agents (placed if `place` else raw), requested, placed, detail.
    With place=True the rng also drives placement; pass place=False for a preview
    that leaves the layout untouched. Reusable directly from a GUI/DM-mode caller.
    If filter_types or filter_languages are set, all encounters will use those filters."""
    rooms, order_note = order_dungeon_rooms(bm, rpg, terrain, min_room, entrance)
    start_row = DIFFICULTY_WEIGHTS[difficulty_start]
    end_row = DIFFICULTY_WEIGHTS[difficulty_end]
    n = len(rooms)
    results: list[dict] = []
    # Species used so far across the whole dungeon — build_encounter steers picks
    # away from these so the same mob doesn't reappear in room after room.
    used_names: set[str] = set()
    for i, floor in enumerate(rooms):
        is_boss = boss and i == n - 1
        if is_boss:
            weights = None
            category = "E"
        else:
            weights = ramp_weights(start_row, end_row, i, n)
            cats = [k for k, w in weights.items() if w > 0]
            cat_w = [weights[k] for k in cats]
            category = rng.choices(cats, weights=cat_w, k=1)[0]
        agents, detail = build_encounter(category, cr, bestiary, rng,
                                         automation_level=automation_level,
                                         filter_types=filter_types,
                                         filter_languages=filter_languages,
                                         avoid=used_names)
        placed = place_agents_in_room(agents, floor, rng) if place else agents
        # Tag the toughest mob in the boss room (highest max HP — the dragon/big-bad)
        # so the GUI can flag the finale with a star.
        if is_boss and placed:
            boss_ag = max(placed, key=lambda a: a.get("stats", {}).get("hp_max", 0))
            boss_ag["is_boss"] = True
        results.append({
            "room": i, "is_boss": is_boss, "category": category,
            "weights": weights, "floor_cells": len(floor),
            "agents": placed, "requested": len(agents),
            "placed": len(placed) if place else None, "detail": detail,
        })
    return rooms, results, order_note


# ── Placement ───────────────────────────────────────────────────────────────
def place_agents_in_room(agents: list[dict], floor: list[tuple[int, int]],
                         rng: random.Random) -> list[dict]:
    """Assign non-overlapping origins to `agents` from the room's floor cells,
    respecting each agent's square footprint. Agents that don't fit are dropped."""
    floor_set = set(floor)
    taken: set[tuple[int, int]] = set()
    placed: list[dict] = []
    # Place larger footprints first — they're harder to fit.
    order = sorted(range(len(agents)), key=lambda i: -agents[i]["size"])
    for i in order:
        ag = agents[i]
        sz = ag["size"]
        candidates = list(floor)
        rng.shuffle(candidates)
        for (c, r) in candidates:
            cells = [(c + dc, r + dr) for dc in range(sz) for dr in range(sz)]
            if all(cell in floor_set and cell not in taken for cell in cells):
                ag = dict(ag)
                ag["col"], ag["row"] = c, r
                taken.update(cells)
                placed.append(ag)
                break
    return placed


# ── Output ──────────────────────────────────────────────────────────────────
def default_out_name(prefix: str, x: int, when: datetime.date | None = None) -> str:
    when = when or datetime.date.today()
    return f"{prefix}_encounter_generator_cr_{x}_date_{when.strftime('%m%d%Y')}"


def write_agents_file(path: str, agents: list[dict], *, difficulty: str | None,
                      target_cr: int, generator_meta: dict) -> None:
    doc = {
        "difficulty": difficulty,
        "target_cr": target_cr,
        "generator": generator_meta,
        "agents": agents,
        "map_items": [],
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)


# ── Sub-command: single encounter ───────────────────────────────────────────
def cmd_encounter(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    bestiary = Bestiary()
    agents, detail = build_encounter(args.category, args.cr, bestiary, rng,
                                     automation_level=args.automation_level,
                                     filter_types=args.type if hasattr(args, 'type') and args.type else None,
                                     filter_languages=args.languages if hasattr(args, 'languages') and args.languages else None)

    # No map: lay the mobs out in a simple block so the file is directly loadable.
    col0, row0 = 2, 2
    per_row = 6
    for i, ag in enumerate(agents):
        ag["col"] = col0 + (i % per_row) * 2
        ag["row"] = row0 + (i // per_row) * 2

    print(f"Category {args.category} @ CR {args.cr}: {len(agents)} mobs")
    for g in detail:
        print(f"  - {g['count']}x CR {g['cr']} {g['strategy']}: {', '.join(g['monsters']) or '(none found)'}")

    if args.dry_run:
        print("(dry run — no file written)")
        return 0

    base = args.out or default_out_name(args.prefix, args.cr)
    out_dir = args.out_dir or os.getcwd()
    agents_path = os.path.join(out_dir, base + "_agents.json")
    write_agents_file(agents_path, agents, difficulty=None, target_cr=args.cr,
                      generator_meta={"mode": "encounter", "category": args.category,
                                      "seed": args.seed, "groups": detail})
    print(f"Wrote {agents_path}")
    return 0


# ── Sub-command: dungeon ────────────────────────────────────────────────────
def _fmt_weights(w: dict[str, int] | None) -> str:
    """Render a room's ramped category weights (or the boss marker) for logging."""
    if w is None:
        return "boss=E"
    return ":".join(str(w.get(k, 0)) for k in ("A", "B", "C", "D", "E"))


def cmd_dungeon(args: argparse.Namespace) -> int:
    if args.difficulty not in DIFFICULTY_WEIGHTS:
        print(f"ERROR: --difficulty must be one of {list(DIFFICULTY_WEIGHTS)}", file=sys.stderr)
        return 2
    difficulty_start = args.difficulty_start or "Easy"
    if difficulty_start not in DIFFICULTY_WEIGHTS:
        print(f"ERROR: --difficulty-start must be one of {list(DIFFICULTY_WEIGHTS)}",
              file=sys.stderr)
        return 2

    entrance: tuple[int, int] | None = None
    if args.entrance:
        try:
            ec, er = args.entrance.split(",")
            entrance = (int(ec), int(er))
        except ValueError:
            print("ERROR: --entrance must be 'C,R' (two integers).", file=sys.stderr)
            return 2

    terrain_path = args.terrain
    if terrain_path is None:
        # Convention: <base>.png -> <base>_terrain.json
        base, _ = os.path.splitext(args.map)
        guess = base + "_terrain.json"
        terrain_path = guess if os.path.exists(guess) else None
    if terrain_path is None:
        print("WARNING: no terrain file found; every passable cell becomes one big room.",
              file=sys.stderr)

    rng = random.Random(args.seed)
    bestiary = Bestiary()
    bm, terrain, rpg = load_battlemap(args.map, terrain_path)

    rooms, results, order_note = build_dungeon(
        bm, rpg, terrain, bestiary, cr=args.cr,
        difficulty_start=difficulty_start, difficulty_end=args.difficulty,
        min_room=args.min_room, boss=args.boss, entrance=entrance,
        automation_level=args.automation_level, rng=rng, place=not args.dry_run,
        filter_types=args.type if hasattr(args, 'type') and args.type else None,
        filter_languages=args.languages if hasattr(args, 'languages') and args.languages else None)

    print(f"Grid {bm.grid_cols}x{bm.grid_rows}: detected {len(rooms)} room(s) "
          f"(min {args.min_room} floor cells).")
    print(f"Ordering   : {order_note}")
    print(f"Difficulty : {difficulty_start} -> {args.difficulty}"
          f"{'  (+ boss finale)' if args.boss else ''}")
    if not rooms:
        print("ERROR: no rooms detected — try lowering --min-room.", file=sys.stderr)
        return 1

    # ── Dry run: show the room map + what each room would roll, write nothing ──
    if args.dry_run:
        print("\nRoom map (symbols = room index in walk order, # wall, ~ water/chasm, "
              ". floor below --min-room):")
        for line in render_room_map(bm, rpg, rooms):
            print("  " + line)
        print(f"\nPreview (seed {args.seed}):")
        for res in results:
            sym = _ROOM_SYMBOLS[res["room"]] if res["room"] < len(_ROOM_SYMBOLS) else "*"
            names = [a["name"] for a in res["agents"]]
            tag = " [BOSS]" if res["is_boss"] else ""
            print(f"  Room {sym} [{res['floor_cells']} cells] "
                  f"w={_fmt_weights(res['weights'])} -> category {res['category']}{tag}: "
                  f"{len(res['agents'])} mobs: {', '.join(names) or '(none)'}")
        print("\n(dry run — no files written)")
        return 0

    all_agents: list[dict] = []
    room_log: list[dict] = []
    for res in results:
        all_agents.extend(res["agents"])
        dropped = res["requested"] - res["placed"]
        note = f"  (dropped {dropped}, room too small)" if dropped else ""
        tag = " [BOSS]" if res["is_boss"] else ""
        print(f"  Room {res['room']} [{res['floor_cells']} cells] "
              f"w={_fmt_weights(res['weights'])} -> category {res['category']}{tag}: "
              f"{res['placed']} mobs{note}")
        room_log.append({"room": res["room"], "is_boss": res["is_boss"],
                         "category": res["category"], "weights": res["weights"],
                         "floor_cells": res["floor_cells"], "floor_cell_coords": rooms[res["room"]],
                         "requested": res["requested"], "placed": res["placed"],
                         "groups": res["detail"]})

    base = args.out or default_out_name(args.prefix, args.cr)
    out_dir = args.out_dir or (os.path.dirname(os.path.abspath(args.map)))
    agents_path = os.path.join(out_dir, base + "_agents.json")
    write_agents_file(agents_path, all_agents, difficulty=args.difficulty,
                      target_cr=args.cr,
                      generator_meta={"mode": "dungeon", "seed": args.seed,
                                      "map": os.path.basename(args.map),
                                      "min_room": args.min_room,
                                      "difficulty_start": difficulty_start,
                                      "difficulty_end": args.difficulty,
                                      "boss": args.boss, "ordering": order_note,
                                      "rooms": room_log})

    # Copy the terrain verbatim so the encounter loads with the same walls.
    terrain_out = os.path.join(out_dir, base + "_terrain.json")
    with open(terrain_out, "w") as f:
        json.dump(terrain, f, indent=2)

    print(f"\nDifficulty {difficulty_start}->{args.difficulty}: placed "
          f"{len(all_agents)} mobs across {len(rooms)} rooms.")
    print(f"Wrote {agents_path}")
    print(f"Wrote {terrain_out}")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────
_TOP_EPILOG = """\
sub-commands:
  encounter   Generate ONE random encounter of a given category (A-E) at a
              target challenge rating, written as a loadable *_agents.json.
  dungeon     Auto-detect the rooms of a map and drop one weighted-random
              encounter into each, written as a combined *_agents.json plus a
              copied *_terrain.json.

examples:
  # one Category-E encounter at CR 5 (reproducible with a seed)
  python tools/encounter_generator.py encounter --cr 5 --category E --seed 42

  # fill every room of simplemap with a Medium-difficulty CR-5 dungeon
  python tools/encounter_generator.py dungeon \\
      --map encounters/simplemap.png --difficulty Medium --cr 5 \\
      --out-dir encounters

see 'encounter -h' or 'dungeon -h' for the full options of each sub-command.

notes:
  * The dungeon sub-command imports the built rpg_battle_map extension, so it
    must run in the environment the .so was built for (the rpg_map Docker /
    matching Python). The encounter sub-command is pure Python (bestiary only).
  * Generated *_agents.json files use the exact schema the GUI's _load_agents
    reads, so they load directly; every mob is is_npc_automated=True, faction=1.
"""

_ENCOUNTER_DESC = """\
Generate ONE random encounter of a single category (A-E) at target CR x.

Category compositions (mob counts are uniform over the stated ranges):
  A: 4-5 x (CR x-4, Simple)
  B: 2-3 x (CR x-4, Simple)  + 1-2 x (CR x-2, PreferRange)
  C: 1-2 x (CR x-2, Simple)  + 1-2 x (CR x-2, PreferRange)
  D: 1-2 x (CR x-2, Simple)  + 1   x (CR x-2, PreferAOE)
  E: 2-3 x (CR x-2, Simple)  + 1-2 x (CR x-2, PreferRange)
                             + 1 Dragon (CR <= x, PreferAOE)

Candidate pools: 'Simple' = any monster at the required CR; 'PreferRange' = a
monster with a ranged weapon; 'PreferAOE' = a monster with an area spell or a
recharge breath weapon; the Dragon slot = any monster whose meta.type contains
"Dragon" with CR <= x. If no monster satisfies a slot at the exact CR, the tool
falls back to the nearest available CR (nearest/lowest-CR dragon for the Dragon
slot). No map is loaded: the mobs are laid out in a simple block so the file is
still directly loadable.
"""

_ENCOUNTER_EPILOG = """\
examples:
  # a pack of Category-A goblins-and-friends around CR 5
  python tools/encounter_generator.py encounter --cr 5 --category A

  # reproducible Category-E (dragon boss) written to encounters/ with a custom name
  python tools/encounter_generator.py encounter --cr 8 --category E \\
      --seed 7 --out-dir encounters --out throne_room_ambush

output:
  <out-dir>/<name>_agents.json    where <name> defaults to
  '<prefix>_encounter_generator_cr_<x>_date_<MMDDYYYY>' (--out overrides <name>).
"""

_DUNGEON_DESC = """\
Resolve a map's rooms in walk order and drop one random encounter into each, with
difficulty ramping up as the player goes deeper.

Room order: if the *_terrain.json carries dungeon_from_png room metadata (a
"rooms" list with path_index), that corridor-chain order IS the walk order. Else
the map is loaded through the engine (analyze_grid + detect_walls), the terrain is
re-applied (Wall/Chasm/Water regions + closed doors), floor cells are flood-filled
into connected components (Wall cells split rooms; Water/Chasm do not but aren't
placeable), and rooms are ordered by distance from an entrance (--entrance, else
the room nearest a map border). A component counts as a room only if it has at
least --min-room placeable (floor) cells.

Difficulty ramp: each room's category is rolled from A:B:C:D:E weights blended
linearly from --difficulty-start (first room) to --difficulty (deepest room):
  Easy    3:1:0:0:0     (mostly weak mob packs)
  Medium  3:2:1:1:1     (a spread across all five categories)
  Hard    0:1:2:2:1     (ranged / AOE / dragon-heavy)
So early rooms skew to weak packs and later rooms to AOE/dragon fights. Unless
--no-boss is given, the deepest room is forced to a category-E boss encounter.
CR is uniform across the dungeon (single --cr); difficulty is carried entirely by
encounter composition.

Mobs are placed on non-overlapping footprints within the room; any that cannot
fit are dropped (reported per room). --difficulty (the peak) is recorded inside
the agents file, alongside difficulty_start, the ordering used, and a per-room
generation log (category + ramped weights).
"""

_DUNGEON_EPILOG = """\
examples:
  # Medium CR-5 dungeon over simplemap (terrain auto-found next to the map)
  python tools/encounter_generator.py dungeon \\
      --map encounters/simplemap.png --difficulty Medium --cr 5 \\
      --out-dir encounters

  # Hard CR-7, coarser rooms, reproducible, explicit terrain file
  python tools/encounter_generator.py dungeon \\
      --map maps/TestDNDMap.png --terrain maps/TestDNDMap_terrain.json \\
      --difficulty Hard --cr 7 --min-room 16 --seed 1

calibrating --min-room:
  Start at the default (9 = a 3x3 floor). If too many closets/corridors get mobs,
  raise it; if real rooms are being skipped, lower it. The run prints the grid
  size, room count, and each room's floor-cell count so you can tune.

output (both written to --out-dir, default = the map's directory):
  <name>_agents.json     the combined encounter (all rooms), difficulty embedded
  <name>_terrain.json    a verbatim copy of the input terrain
  where <name> defaults to
  '<prefix>_encounter_generator_cr_<x>_date_<MMDDYYYY>' (--out overrides <name>).
"""


def _all_arguments_text(parser: argparse.ArgumentParser) -> str:
    """Introspect the parser and render every sub-command's arguments as a compact
    reference block (option strings + value placeholder + required flag), appended
    to the top-level help so `-h` lists all arguments without drilling into each
    sub-command."""
    sub_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None)
    if sub_action is None:
        return ""
    lines = ["all arguments (by sub-command):"]
    for name, subp in sub_action.choices.items():
        lines.append(f"\n  {name}:")
        for act in subp._actions:
            if isinstance(act, argparse._HelpAction):
                continue
            opts = ", ".join(act.option_strings) if act.option_strings else act.dest
            if not act.option_strings or act.nargs == 0:
                placeholder = ""                       # positional / store_true/false
            elif act.metavar:
                placeholder = f" {act.metavar}"
            elif act.choices:
                placeholder = " {%s}" % ",".join(str(c) for c in act.choices)
            else:
                placeholder = f" {act.dest.upper()}"
            req = "  (required)" if getattr(act, "required", False) else ""
            lines.append(f"    {opts}{placeholder}{req}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="encounter_generator.py",
        description=__doc__,
        epilog=_TOP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", metavar="{encounter,dungeon}", required=True)

    # ── encounter ───────────────────────────────────────────────────────────
    e = sub.add_parser(
        "encounter",
        help="generate one encounter of a chosen category (A-E)",
        description=_ENCOUNTER_DESC,
        epilog=_ENCOUNTER_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    e.add_argument("--cr", type=int, required=True, metavar="X",
                   help="target challenge rating x (integer); mob CRs are derived "
                        "as x-1 / x-2 per the category and clamped at 0")
    e.add_argument("--category", required=True, choices=list(CATEGORY_TABLE),
                   help="which encounter category to build (A, B, C, D, or E); "
                        "see the description above for each composition")
    e.add_argument("--seed", type=int, default=None, metavar="N",
                   help="RNG seed for a reproducible roll (monster picks + counts); "
                        "omit for a fresh random encounter each run")
    e.add_argument("--automation-level", type=int, default=1, metavar="L",
                   help="npc_automation_difficulty_level written on every mob "
                        "(gates how aggressively NPC automation plays; default: 1)")
    e.add_argument("--prefix", default="simplemap", metavar="STR",
                   help="filename prefix used when --out is not given "
                        "(default: simplemap)")
    e.add_argument("--out", default=None, metavar="NAME",
                   help="output base name WITHOUT the _agents.json suffix; "
                        "overrides the auto '<prefix>_encounter_generator_cr_"
                        "<x>_date_<MMDDYYYY>' name")
    e.add_argument("--out-dir", default=None, metavar="DIR",
                   help="directory to write the *_agents.json into "
                        "(default: current working directory)")
    e.add_argument("--dry-run", action="store_true",
                   help="print the rolled encounter composition and write nothing")
    e.add_argument("--type", default=None, metavar="TYPE",
                   help="restrict mobs to a specific type (e.g. 'Monstrosity', 'Aberration', 'Beast'); "
                        "omit for any type")
    e.add_argument("--languages", nargs="+", default=None, metavar="LANG",
                   help="restrict mobs to those speaking at least one of these languages; "
                        "omit for any languages (e.g. --languages Common Goblin)")
    e.set_defaults(func=cmd_encounter)

    # ── dungeon ─────────────────────────────────────────────────────────────
    d = sub.add_parser(
        "dungeon",
        help="fill every detected room of a map with weighted-random encounters",
        description=_DUNGEON_DESC,
        epilog=_DUNGEON_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    d.add_argument("--map", required=True, metavar="PNG",
                   help="path to the map image (PNG); loaded through the engine "
                        "to get the grid + auto-detected walls")
    d.add_argument("--terrain", default=None, metavar="JSON",
                   help="path to the map's *_terrain.json (Wall/Chasm/Water regions "
                        "+ doors); default: <map-without-ext>_terrain.json if present")
    d.add_argument("--difficulty", required=True, choices=list(DIFFICULTY_WEIGHTS),
                   help="PEAK difficulty (the deepest room); the per-room A:B:C:D:E "
                        "category weights (Easy 3:1:0:0:0, Medium 3:2:1:1:1, Hard "
                        "0:1:2:2:1) ramp from --difficulty-start up to this along the "
                        "walk order, and this is recorded inside the agents file")
    d.add_argument("--difficulty-start", default="Easy", choices=list(DIFFICULTY_WEIGHTS),
                   help="difficulty profile for the FIRST room; category weights blend "
                        "linearly from this to --difficulty across the walk order so "
                        "encounters get harder deeper in (default: Easy)")
    d.add_argument("--no-boss", dest="boss", action="store_false",
                   help="do NOT force the deepest room to a boss (category E) finale; "
                        "by default the last room in walk order is always a boss")
    d.add_argument("--entrance", default=None, metavar="C,R",
                   help="entrance cell 'C,R' used only by the fallback distance "
                        "ordering (ignored when the terrain carries room metadata, "
                        "which already encodes the walk order)")
    d.add_argument("--cr", type=int, required=True, metavar="X",
                   help="target challenge rating x (integer) for every room's "
                        "encounter; mob CRs derive as x-1 / x-2, clamped at 0")
    d.add_argument("--min-room", type=int, default=9, metavar="N",
                   help="minimum number of placeable floor cells for a connected "
                        "blob to count as a room (default: 9 = a 3x3 area); raise to "
                        "ignore closets/corridors, lower if real rooms are skipped")
    d.add_argument("--seed", type=int, default=None, metavar="N",
                   help="RNG seed for a reproducible dungeon (category choice, "
                        "monster picks, and placement); omit for a fresh roll")
    d.add_argument("--automation-level", type=int, default=1, metavar="L",
                   help="npc_automation_difficulty_level written on every mob "
                        "(default: 1)")
    d.add_argument("--prefix", default="simplemap", metavar="STR",
                   help="filename prefix used when --out is not given "
                        "(default: simplemap)")
    d.add_argument("--out", default=None, metavar="NAME",
                   help="output base name WITHOUT the _agents.json / _terrain.json "
                        "suffix; overrides the auto '<prefix>_encounter_generator_cr_"
                        "<x>_date_<MMDDYYYY>' name")
    d.add_argument("--out-dir", default=None, metavar="DIR",
                   help="directory to write both output files into "
                        "(default: the directory containing --map)")
    d.add_argument("--dry-run", action="store_true",
                   help="detect rooms, print an ASCII room map + a per-room "
                        "category/mob preview, and write nothing (use to "
                        "calibrate --min-room before generating)")
    d.add_argument("--type", default=None, metavar="TYPE",
                   help="restrict mobs to a specific type (e.g. 'Monstrosity', 'Aberration', 'Beast'); "
                        "omit for any type")
    d.add_argument("--languages", nargs="+", default=None, metavar="LANG",
                   help="restrict mobs to those speaking at least one of these languages; "
                        "omit for any languages (e.g. --languages Common Goblin)")
    d.set_defaults(func=cmd_dungeon, boss=True)

    # Append the full argument listing (both sub-commands) to the top-level help.
    p.epilog = _TOP_EPILOG + "\n" + _all_arguments_text(p)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
