"""Dungeon generation and character import. The DM-mode Generate Terrain / Generate Dungeon
dialogs and their runs (the BSP carve on the current map, the multi-floor / multi-map
generator that staples floor tiles together and writes each page's terrain and encounter
sidecars, the mob picker and the item selector they open) and the D&D Beyond character
import with its click-to-place.

Moved out of `App` in APP_REFACTOR_PLAN.md A5, the same way as `app_summons.py` (A4b):
module-level functions taking the app; `bm`, `store`, `dungeon` and the placement state
stay on `app` (D3).

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`menus/dm.py`, tests). Calls between those go through the forwarder
(`app._modal_select_items(...)`), so a test that wraps one on the instance still sees every
call; the rest are called directly. `main.py` calls `place_imported_agent` and
`on_generate_dungeon` as `app_dungeon_gen.*(self, ...)`.
"""

import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import textwrap
import time

import pygame

import rpg_battle_map as rpg

import app_dungeon_pages
import campaign_import
import save_layout
from dungeon import Dungeon, MapPage
from scene_store import CampaignStore
from widgets import Button, IntStepper, TextInput


# FLAG: Move to C++
# ── D&D Beyond import ─────────────────────────────────────────────────────
def import_ddb_character(app):
    """Fetch a public D&D Beyond character, derive our agent record via
    tools/import_character.py, append it to the current encounter file and
    reload. Thin GUI wrapper around the standalone importer."""
    url = app._modal_text_prompt(
        "Import D&D Beyond Character",
        "Paste a character URL or ID (the sheet must be publicly shared):")
    if not url:
        return
    # lazy-import the standalone tool from the repo tools/ dir
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import import_character as ic
    except Exception as e:                       # noqa: BLE001 — surface any import error
        app._modal_message(["Importer unavailable:", str(e)])
        return

    app._modal_message(["Importing from D&D Beyond…"], blocking=False)
    try:
        data = ic.fetch_character(url)
        ic._WARN = []                            # capture this character's warnings
        agent = ic.build_agent(data, ic.load_catalogs(), faction=0)
        warnings = list(ic._WARN)
    except Exception as e:                       # noqa: BLE001 — network/parse/derive errors
        app._modal_message(["Import failed:", str(e)])
        return

    # lossless sidecar (raw DDB JSON), best-effort
    try:
        cid = re.search(r"(\d{4,})", str(url))
        side_dir = os.path.join(tools_dir, "ddb_sources")
        os.makedirs(side_dir, exist_ok=True)
        slug = ic.slugify(data.get("name", ""))
        fn = f"{cid.group(1) if cid else slug}_{slug}.ddb.json"
        with open(os.path.join(side_dir, fn), "w") as f:
            json.dump({"data": data}, f, indent=2)
    except Exception:                            # noqa: BLE001 — sidecar is best-effort
        pass

    sub = ""
    for k, v in agent.items():
        if k.startswith("agent_") and k.endswith(("subclass", "circle", "oath")) and v != "NONE":
            sub = f" / {v}"
            break
    lines = [f"Imported {agent['name']}",
             f"{agent['agent_class']} {agent['agent_char_level']}{sub}   "
             f"HP {agent['stats']['hp_max']}   spells {len(agent['spell_indices'])}",
             "Click on the map to place it (Esc cancels); set its team via right-click."]
    if warnings:
        lines.append(f"{len(warnings)} note(s) (best-effort import):")
        lines.extend("• " + w[:70] for w in warnings[:8])
        if len(warnings) > 8:
            lines.append(f"  …and {len(warnings) - 8} more (see console).")
    app._modal_message(lines)

    # Float it at the cursor through the ordinary placement mode; the click lands in
    # place_imported_agent, which writes the full record.
    cfg = rpg.AgentConfig()
    cfg.name        = agent["name"]
    cfg.sprite_path = ""
    cfg.size        = agent.get("size", 1) or 1
    app.selected_mob_stats = None
    app._pending_pc_class = None
    app._pending_import_agent = agent
    app.placement_mode_active = True
    app.placement_config = cfg
    app.placement_cell = None
    app.placement_valid = False


def place_imported_agent(app, agent: dict, cell) -> None:
    """Drop an imported D&D Beyond record at ``cell``: persist the current placements,
    append the record to the scene's creatures and reload, so every field the importer
    derived goes through the one loader."""
    app._save_agents()
    try:
        doc = app.store.creatures() or {"agents": [], "map_items": []}
    except ValueError:
        doc = {"agents": [], "map_items": []}
    agent["col"], agent["row"] = cell.col, cell.row
    doc.setdefault("agents", []).append(agent)
    doc.setdefault("map_items", [])
    app.store.write_creatures(doc)
    app._load_agents()


def modal_generate_terrain(app) -> dict | None:
    """Blocking dialog for the Generate Terrain (DM-mode) parameters.

    Returns {rooms, min_room, margin, seed} or None on cancel. These feed the
    BSP room/corridor carver in tools/dungeon_from_png (rooms = target room
    count, min_room = smallest room side in cells, margin = wall padding around
    each room)."""
    sw, sh = app.screen.get_size()
    W, H = min(500, sw - 80), min(400, sh - 80)
    box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
    lx = box.x + 20
    fx = box.right - 200       # field column
    fw = 180
    row_h = 40
    y0 = box.y + 60

    rooms_step  = IntStepper(pygame.Rect(fx, y0 + 0 * row_h, fw, 30), 4, 3, 12, font=app.font_md)
    room_step   = IntStepper(pygame.Rect(fx, y0 + 1 * row_h, fw, 30), 3, 2, 20, font=app.font_md)
    margin_step = IntStepper(pygame.Rect(fx, y0 + 2 * row_h, fw, 30), 1, 0, 5, font=app.font_md)
    seed_inp    = TextInput(pygame.Rect(fx, y0 + 3 * row_h, fw, 30), placeholder="random", font=app.font_md)
    # Floors > 1 builds a stacked multi-floor dungeon (each floor a fresh layout,
    # linked by ladders) instead of carving the single active map.
    floors_step = IntStepper(pygame.Rect(fx, y0 + 4 * row_h, fw, 30), 1, 1, 8, font=app.font_md)
    # "Each floor: N×M" — each floor is tiled with N (across) by M (down) maps,
    # laid out edge-to-edge and reachable via the map-paging HUD (both 1 = single map).
    nm_y = y0 + 5 * row_h
    mapsx_step = IntStepper(pygame.Rect(fx,          nm_y, 82, 30), 1, 1, 4, font=app.font_md)
    mapsy_step = IntStepper(pygame.Rect(fx + fw - 82, nm_y, 82, 30), 1, 1, 4, font=app.font_md)

    gen    = Button(pygame.Rect(box.right - 220, box.bottom - 46, 95, 32), "Generate",
                    (60, 110, 70), (80, 140, 90), font=app.font_md)
    cancel = Button(pygame.Rect(box.right - 115, box.bottom - 46, 95, 32), "Cancel",
                    (110, 60, 60), (150, 80, 80), font=app.font_md)

    labels = ["Room count", "Min room side", "Wall margin", "Seed", "Floors",
              "Each floor (N×M)"]
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    while True:
        app._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return None
            rooms_step.handle(event)
            room_step.handle(event)
            margin_step.handle(event)
            seed_inp.handle(event)
            floors_step.handle(event)
            mapsx_step.handle(event)
            mapsy_step.handle(event)
            if cancel.clicked(event):
                return None
            if gen.clicked(event):
                seed = None
                s = seed_inp.text.strip()
                if s:
                    try:
                        seed = int(s)
                    except ValueError:
                        seed = None
                return {"rooms": rooms_step.value, "min_room": room_step.value,
                        "margin": margin_step.value, "seed": seed,
                        "floors": floors_step.value,
                        "maps_x": mapsx_step.value, "maps_y": mapsy_step.value}
        app.screen.blit(overlay, (0, 0))
        pygame.draw.rect(app.screen, (35, 35, 50), box, border_radius=8)
        pygame.draw.rect(app.screen, (90, 90, 110), box, 1, border_radius=8)
        app.screen.blit(app.font_lg.render("Generate Terrain", True, (235, 235, 245)),
                         (lx, box.y + 18))
        for i, lab in enumerate(labels):
            app.screen.blit(app.font_md.render(lab, True, (185, 185, 200)),
                             (lx, y0 + i * row_h + 6))
        # "×" separator between the two N×M steppers.
        xt = app.font_md.render("×", True, (185, 185, 200))
        app.screen.blit(xt, (fx + fw // 2 - xt.get_width() // 2, nm_y + 6))
        for w in (rooms_step, room_step, margin_step, seed_inp, floors_step,
                  mapsx_step, mapsy_step, gen, cancel):
            w.draw(app.screen)
        pygame.display.flip()
        app.clock.tick(60)


def carve_dungeon_layout(app, dfp, cols, rows, raw_v, raw_h, blocked, params, rng,
                          force_floor=None):
    """Carve one BSP layout on the current grid and return
    ``(grid, regions, rooms_meta, door_cells)``:

    - ``grid``       the carver's FLOOR/WALL cell grid. Callers may open further
                     cells in it (the multi-floor generator tunnels cross-map
                     doorways through it) and then rebuild ``regions`` with
                     ``regions_from_grid``.
    - ``regions``    pixel-space Wall rects for the terrain JSON / engine.
    - ``rooms_meta`` walk-order room records (with exact ``cells``) that
                     Generate Dungeon populates.
    - ``door_cells`` (c,r) cells where the carver punched doors.

    ``force_floor`` is an optional iterable of (c,r) cells opened to FLOOR after
    carving (portal landings), so a ladder never drops a creature into rock.
    Raises ``ValueError`` from ``dfp.carve`` on a too-tight layout. Shared by the
    single-map Generate Terrain path and the multi-floor generator."""
    grid, rooms, doors = dfp.carve(cols, rows, params["rooms"], params["min_room"],
                                   params["margin"], rng, blocked=blocked)
    for (c, r) in (force_floor or ()):
        if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
            grid[r][c] = dfp.FLOOR

    regions = regions_from_grid(dfp, grid, raw_v, raw_h, app.base_map_scale)
    rooms_meta = [
        {"path_index": i, "c": rm["c"], "r": rm["r"], "w": rm["w"], "h": rm["h"],
         "cells": [[c, r] for (c, r) in rm["cells"]]}
        for i, rm in enumerate(rooms)
    ]
    return grid, regions, rooms_meta, doors


def regions_from_grid(dfp, grid, raw_v, raw_h, scale=1.0):
    """The carve grid's WALL cells as pixel-space Wall terrain rects. Recomputed
    whenever the grid is reopened (e.g. after tunnelling a cross-map doorway), so
    the terrain the engine sees always matches the grid.

    Terrain regions live in fit-scale px (the draw code, ``_pixel_rect_to_cells`` and
    the terrain editor all read them that way), but ``raw_v``/``raw_h`` are image px.
    ``scale`` is the app's ``base_map_scale``: on a map too big for the window
    (fit < 1) unscaled rects drew and blocked ~1/fit too far out."""
    def cell_to_px(c, r, w, h):
        c2 = min(c + w, len(raw_v) - 1)
        r2 = min(r + h, len(raw_h) - 1)
        x, y = round(raw_v[c] * scale), round(raw_h[r] * scale)
        return x, y, round(raw_v[c2] * scale) - x, round(raw_h[r2] * scale) - y

    regions = []
    for (c, r, w, h) in dfp.wall_rects(grid):
        x, y, pw, ph = cell_to_px(c, r, w, h)
        if pw <= 0 or ph <= 0:
            continue
        regions.append({"type": "Wall", "x": x, "y": y,
                        "width": pw, "height": ph, "multiplier": 0.0})
    return regions


def staple_floor_tiles(app, dfp, tiles, maps_x, maps_y, cols, rows, z, rng):
    """Punch a **linked doorway** through every shared edge between abutting tiles on
    one floor, so a generated multi-map floor is walkable — not just page-able.

    For each abutting pair this picks the crossing line (a row for a left/right pair,
    a column for a top/bottom pair) that needs the least tunnelling, opens the carve
    grids from the first floor cell out to the edge on both sides, and returns one
    door per tile facing the other. Each door's ``link_target`` is the cell **one step
    inside** the neighbour, past its own edge door — targeting the neighbour's door
    cell itself would drop the traveller onto a closed door (i.e. into Wall terrain).

    Mutates the tiles' grids in place (callers must rebuild their regions with
    ``regions_from_grid`` afterwards). Returns {(mx, my): [door records]}."""
    links = {key: [] for key in tiles}
    if cols < 3 or rows < 3:
        return links      # no room for an edge cell plus a landing cell

    def first_floor(grid, line, axis, from_far_edge):
        """Depth (in cells) from the tile's edge inward to the first FLOOR cell on
        ``line``, or None if that line is solid rock all the way across."""
        n = cols if axis == "h" else rows
        for d in range(n):
            i = (n - 1 - d) if from_far_edge else d
            cell = grid[line][i] if axis == "h" else grid[i][line]
            if cell == dfp.FLOOR:
                return d
        return None

    def open_to_edge(grid, line, axis, from_far_edge, depth):
        """Carve FLOOR from the first floor cell out to the edge, plus the cell just
        inside the edge — that is where a creature arriving from the other page lands,
        so it must be open even when the edge cell was already floor."""
        n = cols if axis == "h" else rows
        for d in range(max(depth, 1) + 1):
            i = (n - 1 - d) if from_far_edge else d
            if axis == "h":
                grid[line][i] = dfp.FLOOR
            else:
                grid[i][line] = dfp.FLOOR

    def staple(a_key, b_key, axis):
        ga, gb = tiles[a_key]["grid"], tiles[b_key]["grid"]
        span = rows if axis == "h" else cols
        best, best_cost = [], None
        for line in range(span):
            da = first_floor(ga, line, axis, from_far_edge=True)    # A's far edge
            db = first_floor(gb, line, axis, from_far_edge=False)   # B's near edge
            if da is None or db is None:
                continue
            cost = da + db
            if best_cost is None or cost < best_cost:
                best, best_cost = [line], cost
            elif cost == best_cost:
                best.append(line)
        if not best:
            return            # nothing walkable on either side of this edge
        line = rng.choice(best)
        da = first_floor(ga, line, axis, from_far_edge=True)
        db = first_floor(gb, line, axis, from_far_edge=False)
        open_to_edge(ga, line, axis, True, da)
        open_to_edge(gb, line, axis, False, db)

        (amx, amy), (bmx, bmy) = a_key, b_key
        a_ox, a_oy = amx * cols, amy * rows      # tiles tessellate: origin = index × size
        b_ox, b_oy = bmx * cols, bmy * rows
        if axis == "h":
            a_cell, b_cell = (cols - 1, line), (0, line)
            a_target = [b_ox + 1,        b_oy + line, z]   # one step into B
            b_target = [a_ox + cols - 2, a_oy + line, z]   # one step back into A
        else:
            a_cell, b_cell = (line, rows - 1), (line, 0)
            a_target = [b_ox + line, b_oy + 1,        z]
            b_target = [a_ox + line, a_oy + rows - 2, z]
        links[a_key].append({"cell": a_cell, "target": a_target})
        links[b_key].append({"cell": b_cell, "target": b_target})

    for my in range(maps_y):
        for mx in range(maps_x):
            if mx + 1 < maps_x:
                staple((mx, my), (mx + 1, my), "h")
            if my + 1 < maps_y:
                staple((mx, my), (mx, my + 1), "v")
    return links


def write_generated_terrain(app, path, regions, rooms_meta, door_cells, ladders,
                             staging_cells=None, linked_doors=None):
    """Write a page's ``_terrain.json`` directly (bypassing the live-scene
    serializer) for the multi-floor generator. Mirrors ``_save_terrain``'s schema:
    carved Wall regions, walk-order room metadata, closed inter-room doors, and
    vertical ``ladders`` (global targets). Walls are explicit, so ``walls_enabled``
    is False (no auto-detect). No ``explored`` key ⇒ the floor starts fully fogged.

    ``staging_cells`` (floor 0 only) records the exact room the generator left empty
    so Load PCs drops the party into that same room, not a re-derived 'room 0'.

    ``linked_doors`` are the cross-map staples on this page's edges ({"cell", "target"}
    from staple_floor_tiles); they are written as ordinary closed doors carrying a
    ``link_target``, and win over any interior door the carver happened to punch in the
    same cell."""
    linked_doors = list(linked_doors or ())
    linked_cells = {tuple(ld["cell"]) for ld in linked_doors}
    doors = [
        {"cells": [[c, r]], "cell": [c, r], "open": False, "locked": False,
         "lock_dc": 15, "arcane_lock": False, "break_dc": 15, "broken": False,
         "link_target": None}
        for (c, r) in door_cells if (c, r) not in linked_cells
    ]
    doors += [
        {"cells": [[ld["cell"][0], ld["cell"][1]]],
         "cell": [ld["cell"][0], ld["cell"][1]],
         "open": False, "locked": False, "lock_dc": 15, "arcane_lock": False,
         "break_dc": 15, "broken": False,
         "link_target": [int(v) for v in ld["target"]]}
        for ld in linked_doors
    ]
    data = {
        "regions": regions,
        "walls_enabled": False,
        "rooms": rooms_meta,
        "doors": doors,
        "ladders": ladders,
    }
    if staging_cells:
        data["staging_cells"] = [[int(c), int(r)] for (c, r) in staging_cells]
    if app._manual_grid:
        data["manual_grid"] = app._manual_grid
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_room_cell(rooms_meta, rng, avoid=None):
    """A random floor cell drawn from a random substantial room (largest rooms
    favoured), avoiding cells in ``avoid``. Returns (c, r) or None. Used to seat a
    ladder somewhere walkable rather than in a corridor or wall pocket."""
    avoid = set(avoid or ())
    # Largest rooms first, so a ladder tends to land in an open chamber; fall through
    # to smaller rooms rather than fail to place one.
    for m in sorted(rooms_meta, key=lambda m: -len(m.get("cells", []))):
        cells = [(int(c), int(r)) for c, r in m.get("cells", [])
                 if (int(c), int(r)) not in avoid]
        if cells:
            return rng.choice(cells)
    return None


def generate_multifloor(app, num_floors, terrain_params, encounter_params, base,
                         maps_x=1, maps_y=1, out_dir=None, activate=True):
    """Generate an ``num_floors``-floor dungeon on the current map's PNG, each floor
    a freshly carved random layout (plus a populated encounter when
    ``encounter_params`` is given), wired into a ``<base>.dungeon.json`` with
    inter-floor ladders, then activate the entry floor.

    Each floor is tiled with ``maps_x`` × ``maps_y`` maps laid out edge-to-edge on
    the global grid: the tile at grid position (mx, my) takes origin
    ``[mx*cols, my*rows, z]``, so the same-floor paging HUD (West/North/South/East)
    walks between abutting tiles. The (0, 0) tile of every floor is the "spine" that
    carries the inter-floor ladders.

    All pages share the active PNG and grid. Floors stack on the global Z axis, so a
    ladder up from the spine's local (c,r) lands at the same (c,r) one floor higher —
    that cell is force-opened to FLOOR on the upper spine so the climb never ends in
    rock. Returns a summary list of strings; raises ValueError if a tile can't be
    carved.

    ``out_dir`` (default: the map's folder) is where the page files and the manifest
    go. ``activate=False`` leaves the manifest unopened: the blank-map path writes to a
    scratch folder and converts it into a campaign dungeon instead."""
    out_dir = out_dir or app._map_dir
    maps_x = max(1, min(4, int(maps_x)))
    maps_y = max(1, min(4, int(maps_y)))
    cols = int(getattr(app.bm, "grid_cols", 0) or 0)
    rows = int(getattr(app.bm, "grid_rows", 0) or 0)
    raw_v = list(app.bm.v_line_positions)
    raw_h = list(app.bm.h_line_positions)
    # Capture the source map's own walls ONCE — they are the exterior shell for
    # every floor (each floor is carved into the same free area).
    blocked = {(c.col, c.row) for c in app.bm.disallowed_cells}
    png_name = os.path.basename(getattr(app, "_map_path", "") or "simplemap.png")

    # Lazy import: repo/tools is not on sys.path for the GUI process.
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import dungeon_from_png as dfp

    bestiary = None
    eg = None
    if encounter_params is not None:
        import encounter_generator as eg  # noqa: F401
        bestiary = eg.Bestiary(data_dir=gui_dir)
    seed0 = terrain_params.get("seed")
    base_seed = seed0 if seed0 is not None else random.randrange(1 << 30)

    pages = []
    down_cell = None      # spine cell this floor's DOWN-ladder occupies (set by floor below)
    total_mobs = 0
    total_staples = 0
    boss_dropped = False
    for z in range(num_floors):
        up_cell = None    # spine cell this floor's UP-ladder occupies (picked below)

        # ── Pass 1: carve every tile of this floor ─────────────────────────────
        # All of them must exist before they can be stapled together, since a
        # cross-map doorway is tunnelled through BOTH abutting grids at once.
        tiles = {}
        for my in range(maps_y):
            for mx in range(maps_x):
                is_spine = (mx == 0 and my == 0)   # (0,0) tile carries the ladders
                # Only the spine force-opens the down-ladder landing; other tiles carve free.
                tile_force = [down_cell] if (is_spine and down_cell is not None) else None
                tile_idx = my * maps_x + mx
                # Retry with a bumped seed if a tile's layout is too tight to carve, so one
                # unlucky RNG doesn't abort the whole dungeon. The rng that succeeds is reused
                # for that tile's ladder pick + encounter, keeping it deterministic.
                rng = None
                grid = rooms_meta = door_cells = None
                for attempt in range(6):
                    rng = random.Random(base_seed + z * 7919 + tile_idx * 104729 + attempt * 131)
                    try:
                        grid, _regions, rooms_meta, door_cells = carve_dungeon_layout(app, 
                            dfp, cols, rows, raw_v, raw_h, blocked, terrain_params, rng,
                            force_floor=tile_force)
                        break
                    except ValueError:
                        grid = None
                if grid is None:
                    raise ValueError(f"Floor {z} map ({mx},{my}): could not carve a layout "
                                     "after 6 tries. Try fewer/smaller rooms.")
                tiles[(mx, my)] = {"grid": grid, "rooms": rooms_meta,
                                   "doors": door_cells, "rng": rng, "is_spine": is_spine}

        # ── Ladders: the spine tile (0,0) carries the inter-floor links ────────
        spine = tiles[(0, 0)]
        ladders_of = {key: [] for key in tiles}
        if down_cell is not None:                 # link back down to floor z-1
            dc, dr = down_cell
            ladders_of[(0, 0)].append({"cells": [[dc, dr]], "target": [dc, dr, z - 1]})
        if z < num_floors - 1:                    # link up to floor z+1
            up_cell = pick_room_cell(spine["rooms"], spine["rng"],
                                           avoid=[down_cell] if down_cell else None)
            if up_cell is not None:
                uc, ur = up_cell
                ladders_of[(0, 0)].append({"cells": [[uc, ur]], "target": [uc, ur, z + 1]})

        # ── Staple abutting tiles: a linked door through each shared edge, tunnelled
        #    into both grids (so the floor is walkable, not just page-able) ───────
        links_of = staple_floor_tiles(app, 
            dfp, tiles, maps_x, maps_y, cols, rows, z,
            random.Random(base_seed + z * 31337))
        total_staples += sum(len(v) for v in links_of.values()) // 2

        # ── Pass 2: regions (now including the tunnels), encounter, files ──────
        for my in range(maps_y):
            for mx in range(maps_x):
                t = tiles[(mx, my)]
                is_spine, rng, rooms_meta = t["is_spine"], t["rng"], t["rooms"]
                # Rebuild the wall rects from the stapled grid, so the doorways the
                # staples tunnelled are open terrain in both the engine and the file.
                regions = regions_from_grid(dfp, t["grid"], raw_v, raw_h,
                                           app.base_map_scale)

                # Populate this tile's rooms (optional). Placement reads bm.is_blocked, so
                # apply the carved walls to the engine first (mirrors Generate Terrain →
                # Generate Dungeon). The live scene is transient; we reload floor 0 at the end.
                agents = []
                staging_cells = None
                if encounter_params is not None:
                    app._terrain_regions = regions
                    app._walls_enabled = False
                    app._apply_terrain_to_battle_map()
                    app.bm.clear_walls()
                    # The boss finale goes in the top floor's spine tile.
                    is_boss_tile = (z == num_floors - 1 and is_spine)
                    is_entry = (z == 0 and is_spine)
                    ordered_rooms, results, _ = eg.build_dungeon(
                        app.bm, rpg, {"rooms": rooms_meta}, bestiary,
                        cr=encounter_params["cr"],
                        difficulty_start=encounter_params["start"],
                        difficulty_end=encounter_params["end"],
                        min_room=encounter_params["min_room"],
                        boss=encounter_params["boss"] and is_boss_tile,
                        entrance=None,
                        automation_level=encounter_params.get("automation", 4),
                        rng=rng, place=True,
                        filter_types=encounter_params.get("types"),
                        filter_languages=encounter_params.get("languages"),
                        groups=encounter_params.get("groups") or None,
                        reserve_entrance=is_entry,
                        allowed=encounter_params.get("allowed_mobs"),
                        boss_name=encounter_params.get("boss_mob"))
                    boss_dropped = boss_dropped or any(r.get("boss_dropped") for r in results)
                    # Leave the ENTRY tile's entrance (floor 0 spine, room 0) empty so the
                    # party has a clear staging room to Load PCs into. build_dungeon returns
                    # results in room order, so results[0] is that entrance room;
                    # ordered_rooms[0] is its exact (post-filter) cells — recorded so Load
                    # PCs matches it. Every other tile is fully populated.
                    keep = results[1:] if (is_entry and len(results) > 1) else results
                    if is_entry and ordered_rooms:
                        staging_cells = ordered_rooms[0]
                    agents = [a for res in keep for a in res["agents"]]
                    total_mobs += len(agents)

                page_base = multifloor_page_base(app, base, z, mx, my, out_dir)
                ter_path = page_base + "_terrain.json"
                agt_path = page_base + "_agents.json"
                write_generated_terrain(app, ter_path, regions, rooms_meta, t["doors"],
                                              ladders_of[(mx, my)],
                                              staging_cells=staging_cells,
                                              linked_doors=links_of.get((mx, my)))
                if encounter_params is not None:
                    eg.write_agents_file(
                        agt_path, agents, difficulty=encounter_params["end"],
                        target_cr=encounter_params["cr"],
                        generator_meta={"mode": "multifloor-gui", "floor": z,
                                        "map": [mx, my], "seed": base_seed})
                else:
                    # Terrain-only tile: an empty roster so the page loads cleanly.
                    with open(agt_path, "w") as f:
                        json.dump({"agents": [], "map_items": []}, f, indent=2)

                page_id = f"floor{z}" if is_spine else f"floor{z}_{mx}_{my}"
                pages.append(MapPage(id=page_id, png=png_name,
                                     encounter_base=os.path.basename(agt_path),
                                     origin=[mx * cols, my * rows, z],
                                     cols=cols, rows=rows))
        down_cell = up_cell   # the next floor gets a down-ladder where we climbed up

    dungeon = Dungeon(pages=pages, entry_page_id="floor0")
    manifest = os.path.join(out_dir, f"{base}.dungeon.json")
    dungeon.save(manifest)

    per_floor = maps_x * maps_y
    if not activate:
        return multifloor_summary(num_floors, maps_x, maps_y, png_name, encounter_params,
                                  total_mobs, boss_dropped, total_staples, manifest=None)

    # Activate: drop any stale page pointer so _switch_to_page treats this as an
    # initial load (no save-back of the transient generation scene), then open floor 0.
    app.dungeon = dungeon
    app._dungeon_manifest_path = manifest
    app.dungeon_page = None
    app_dungeon_pages.switch_to_page(app, dungeon.entry_page(), force=True)

    return multifloor_summary(num_floors, maps_x, maps_y, png_name, encounter_params,
                              total_mobs, boss_dropped, total_staples, manifest=manifest)


def multifloor_summary(num_floors, maps_x, maps_y, png_name, encounter_params,
                       total_mobs, boss_dropped, total_staples, manifest=None):
    """The closing message of a multi-floor generation. ``manifest`` names the saved
    file; None leaves that line for the caller (the blank-map path saves elsewhere)."""
    per_floor = maps_x * maps_y
    layout = f"{maps_x}×{maps_y} maps/floor" if per_floor > 1 else "1 map/floor"
    summary = [f"Dungeon generated: {num_floors} floors, {layout} on {png_name}"]
    if encounter_params is not None:
        summary.append(f"{total_mobs} mobs total; ladders link every floor")
        if boss_dropped:
            summary.append(f"{encounter_params['boss_mob']} did not fit in the finale room, "
                           "so its toughest mob is the boss.")
    else:
        summary.append("terrain only; ladders link every floor")
    if manifest:
        summary.append(f"Saved manifest: {os.path.basename(manifest)}")
    if per_floor > 1:
        summary.append(f"{total_staples} linked doors join the abutting maps on each floor.")
        summary.append("Open one and 'Go through door' to walk to the next map "
                       "(or page the view with West/North/South/East).")
    summary.append("Use Floor +/- (top-left) or a ladder to move between floors.")
    return summary


def carve_current_map(app, dfp, params, rng):
    """Carve one BSP layout into the CURRENT map and make it the live scene:
    replaces the terrain regions with the carved Wall layout, records the
    walk-order rooms (``_terrain_rooms``), swaps in the carver's doors (closed),
    and saves the terrain sidecar. Returns ``(regions, rooms_meta, doors)``.
    Raises ValueError on a too-tight layout or a missing grid. Shared by
    Generate Terrain and the carve-first Generate Dungeon path."""
    cols = getattr(app.bm, "grid_cols", 0)
    rows = getattr(app.bm, "grid_rows", 0)
    raw_v = list(app.bm.v_line_positions)
    raw_h = list(app.bm.h_line_positions)
    if not cols or not rows or len(raw_v) < 2 or len(raw_h) < 2:
        raise ValueError("No grid on this map — set a grid first.")

    # Use the map's own detected walls as the exterior boundary: the rooms are
    # tessellated inside the free (non-blocked) area and never carve floor into
    # a wall, so the PNG's walls become the dungeon's outer shell.
    blocked = {(c.col, c.row) for c in app.bm.disallowed_cells}
    _grid, regions, rooms_meta, doors = carve_dungeon_layout(app, 
        dfp, cols, rows, raw_v, raw_h, blocked, params, rng)

    # Replace the scene's terrain with the carved layout and record walk-order rooms
    # (cell coords) for Generate Dungeon. Walls are explicit here, so drop auto-detect.
    app._terrain_regions = regions
    app._terrain_rooms = rooms_meta
    app._walls_enabled = False
    app.btn_toggle_walls.text = app._walls_label()
    app._apply_terrain_to_battle_map()
    app.bm.clear_walls()

    # Punch the generated doors through the shared walls. Drop any doors left
    # over from a previous scene first, then add ours closed (a closed door is
    # Wall terrain, so it blocks until opened and keeps rooms separate). Door
    # cells are FLOOR in the carve grid, so they're excluded from wall_rects
    # above and the door owns the cell. _save_terrain reads bm.doors.
    for d in list(app.bm.doors):
        app.bm.remove_door(d.id)
    for (c, r) in doors:
        app.bm.add_door([rpg.Cell(c, r)], False, False, 15, False)

    app._save_terrain()
    return regions, rooms_meta, doors


def on_generate_terrain(app):
    """DM-mode: carve a BSP room/corridor dungeon into the CURRENT map's grid,
    replacing the terrain regions with the resulting Wall layout and recording the
    rooms in walk order so Generate Dungeon can populate them. Reuses the standalone
    carver in tools/dungeon_from_png (cell-space BSP + greedy wall rects)."""
    cols = getattr(app.bm, "grid_cols", 0)
    rows = getattr(app.bm, "grid_rows", 0)
    if not cols or not rows:
        app._modal_message(["Generate Terrain",
                             "No grid on this map — set a grid first."])
        return
    raw_v = list(app.bm.v_line_positions)
    raw_h = list(app.bm.h_line_positions)
    if len(raw_v) < 2 or len(raw_h) < 2:
        app._modal_message(["Generate Terrain",
                             "Grid lines unavailable — set a grid first."])
        return

    params = app._modal_generate_terrain()
    if not params:
        return
    multi = (params.get("floors", 1) > 1 or params.get("maps_x", 1) > 1
             or params.get("maps_y", 1) > 1)
    app._confirm_overwrite(app._generation_targets(params, multi=multi),
                            "Generate Terrain",
                            lambda: generate_terrain_with(app, params, cols, rows))


def generate_terrain_with(app, params, cols, rows):
    """_on_generate_terrain once any overwrite is confirmed."""

    # Lazy import: repo/tools is not on sys.path for the GUI process.
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import dungeon_from_png as dfp
    except Exception as e:
        app._modal_message(["Generate Terrain failed", f"Could not load carver: {e}"])
        return

    # Multi-floor or multi-map-per-floor: hand off to the stacked/tiled dungeon
    # generator (terrain only, no mobs).
    if params.get("floors", 1) > 1 or params.get("maps_x", 1) > 1 or params.get("maps_y", 1) > 1:
        app._modal_message(["Generating maps…"], blocking=False)
        try:
            summary = generate_multifloor(app, 
                params["floors"], params, encounter_params=None, base=app._generated_base(),
                maps_x=params.get("maps_x", 1), maps_y=params.get("maps_y", 1))
        except ValueError as e:
            app._modal_message(["Generate Terrain failed", str(e),
                                 "Try fewer/smaller rooms or a bigger grid."])
            return
        app._modal_message(summary)
        return

    rng = random.Random(params["seed"])
    try:
        regions, rooms_meta, doors = carve_current_map(app, dfp, params, rng)
    except ValueError as e:
        app._modal_message(["Generate Terrain failed", str(e),
                             "Try fewer/smaller rooms or a bigger grid."])
        return

    app._modal_message([
        f"Terrain generated: {len(rooms_meta)} rooms, {len(doors)} doors",
        f"{len(regions)} wall rects on a {cols}×{rows} grid",
        "Now press Generate Dungeon to populate the rooms.",
    ])


def multifloor_page_base(app, base, z, mx, my, out_dir=None) -> str:
    """'<map dir>/<base>_f<z>[_<mx>_<my>]': one generated page's file stem. The (0, 0)
    tile of a floor is its spine and carries no tile suffix."""
    suffix = "" if (mx, my) == (0, 0) else f"_{mx}_{my}"
    return os.path.join(out_dir or app._map_dir, f"{base}_f{z}{suffix}")


def generation_targets(app, params, *, multi: bool, agents_path=None) -> list:
    """The files a generator run will write, for _confirm_overwrite: every page's
    terrain + agents and the manifest for a multi-map run, else this map's terrain
    (plus ``agents_path`` when the run writes an encounter)."""
    if not multi:
        return [app._terrain_path, agents_path]
    base = app._generated_base()
    maps_x = max(1, min(4, int(params.get("maps_x", 1))))
    maps_y = max(1, min(4, int(params.get("maps_y", 1))))
    out = [os.path.join(app._map_dir, f"{base}.dungeon.json")]
    for z in range(int(params.get("floors", 1))):
        for my in range(maps_y):
            for mx in range(maps_x):
                stem = multifloor_page_base(app, base, z, mx, my)
                out += [stem + "_terrain.json", stem + "_agents.json"]
    return out


def dungeon_out_path(app) -> str:
    """Where Generate Dungeon writes a single map's encounter: the page's own file in
    an open dungeon, else '<base>_dungeon_agents.json' beside the map."""
    if app.dungeon is not None and app._save_path:
        return app._save_path
    base = os.path.splitext(os.path.basename(app._save_path or "generated"))[0]
    if base.endswith("_agents"):
        base = base[:-len("_agents")]
    return os.path.join(app._map_dir, base + "_dungeon_agents.json")


def generated_base(app) -> str:
    """Base filename stem for generator output next to the map (strips a trailing
    ``_agents``). Shared by the single-map and multi-floor generators."""
    base = os.path.splitext(os.path.basename(app._save_path or "generated"))[0]
    if base.endswith("_agents"):
        base = base[:-len("_agents")]
    return base


def modal_select_items(app, title: str, items: list[str], selection: set[str] | list,
                        multi_select: bool = True) -> None:
    """Generic scrollable modal for selecting items (single or multi-select).

    For multi_select=True, modifies selection (set) in-place.
    For multi_select=False, modifies selection (list with single element) in-place."""
    if not items:
        return
    sw, sh = app.screen.get_size()
    W, H = min(450, sw - 80), min(600, sh - 100)
    box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
    lx = box.x + 20
    item_h = 32
    scroll_offset = [0]
    content_height = len(items) * item_h
    max_visible = (H - 120) // item_h
    max_scroll = max(0, content_height - (max_visible * item_h))

    btn_ok = Button(pygame.Rect(box.right - 110, box.bottom - 46, 90, 32), "OK",
                   (60, 110, 70), (80, 140, 90), font=app.font_md)
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    content_rect = pygame.Rect(lx, box.y + 60, W - 40, H - 120)

    while True:
        app._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return
            if event.type == pygame.MOUSEWHEEL:
                scroll_offset[0] -= event.y * item_h
                scroll_offset[0] = max(0, min(scroll_offset[0], max_scroll))
            if btn_ok.clicked(event):
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_y = event.pos[1] - (content_rect.y)
                if 0 <= mouse_y < max_visible * item_h and content_rect.collidepoint(event.pos):
                    item_idx = (mouse_y + scroll_offset[0]) // item_h
                    if item_idx < len(items):
                        item = items[item_idx]
                        if multi_select:
                            if item in selection:
                                selection.discard(item)
                            else:
                                selection.add(item)
                        else:
                            selection.clear()
                            selection.append(item)

        app.screen.blit(overlay, (0, 0))
        pygame.draw.rect(app.screen, (35, 35, 50), box, border_radius=8)
        pygame.draw.rect(app.screen, (90, 90, 110), box, 1, border_radius=8)
        app.screen.blit(app.font_lg.render(title, True, (235, 235, 245)),
                         (lx, box.y + 18))

        # Draw scrollable content area
        pygame.draw.rect(app.screen, (25, 25, 40), content_rect, border_radius=4)
        pygame.draw.rect(app.screen, (70, 70, 85), content_rect, 1, border_radius=4)

        visible_start = scroll_offset[0] // item_h
        visible_end = visible_start + max_visible + 1

        for i in range(visible_start, min(visible_end, len(items))):
            item = items[i]
            y_pos = content_rect.y + (i - visible_start) * item_h
            item_rect = pygame.Rect(content_rect.x, y_pos, content_rect.width, item_h)

            is_selected = item in selection
            bg_color = (60, 110, 70) if is_selected else (45, 45, 65)
            pygame.draw.rect(app.screen, bg_color, item_rect)
            pygame.draw.rect(app.screen, (85, 85, 105) if is_selected else (65, 65, 85),
                            item_rect, 1)

            checkbox_x = content_rect.x + 8
            checkbox_y = y_pos + (item_h - 16) // 2
            if multi_select:
                pygame.draw.rect(app.screen, (255, 255, 255) if is_selected else (150, 150, 150),
                                (checkbox_x, checkbox_y, 16, 16), 1 if not is_selected else 0)

            text_x = checkbox_x + 25 if multi_select else content_rect.x + 8
            app.screen.blit(app.font_sm.render(item, True, (220, 220, 220)),
                            (text_x, y_pos + 8))

        # Draw scrollbar
        if max_scroll > 0:
            scrollbar_x = box.right - 12
            scrollbar_y = content_rect.y
            scrollbar_h = content_rect.height
            scroll_thumb_h = max(20, (scrollbar_h * scrollbar_h) // (scrollbar_h + max_scroll))
            scroll_thumb_y = scrollbar_y + (scroll_offset[0] * (scrollbar_h - scroll_thumb_h)) // max_scroll
            pygame.draw.rect(app.screen, (70, 70, 85), (scrollbar_x, scrollbar_y, 8, scrollbar_h))
            pygame.draw.rect(app.screen, (120, 120, 140), (scrollbar_x, scroll_thumb_y, 8, scroll_thumb_h))

        btn_ok.draw(app.screen)
        pygame.display.flip()
        app.clock.tick(60)


def modal_generate_dungeon(app, populate: bool = False, generate: bool = False) -> dict | None:
    """Blocking dialog for the Generate Dungeon (DM-mode) parameters.

    ``populate`` is Dungeon → Populate Floor… (plans/DUNGEON_WIZARD_PLAN.md D3): the
    same dialog, titled for it, with the carve rows (Floors, Rooms/map, N×M, Terrain)
    left out and carve forced off.

    ``generate`` is the New Dungeon wizard's Generate path (D8): the Terrain row is left
    out and carve forced on, since a new dungeon always carves.

    Returns {cr, min_room, start, end, boss, seed, carve, ...} or None on
    cancel. The start/peak difficulties are the endpoints of the per-room
    category-weight ramp; boss forces a category-E encounter into the deepest
    room. carve=True (the default) carves a fresh terrain floor plan first and
    populates exactly those rooms; "Keep (mobs only)" populates the map's existing terrain
    (the old Generate Terrain -> Generate Dungeon two-step)."""
    DIFFS = ["Easy", "Medium", "Hard"]

    # Build type and language lists from bestiary
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import encounter_generator as eg
        bestiary = eg.Bestiary(data_dir=gui_dir)
        all_types = sorted(bestiary.all_types)
        all_languages = sorted(bestiary.all_languages)
    except Exception:
        bestiary = None
        all_types = []
        all_languages = []

    sw, sh = app.screen.get_size()
    W, H = min(500, sw - 80), min(720, sh - 80)
    box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
    lx = box.x + 20
    fx = box.right - 200       # field column
    fw = 180
    row_h = 40
    y0 = box.y + 60
    # Rows by name; Populate Floor leaves the carve rows out and closes the gaps, and a
    # row it leaves out is parked off-screen (never drawn or handled).
    labels = ["Target CR", "Min room cells", "Start difficulty",
              "Peak difficulty", "Boss finale", "Seed", "Mob type", "Languages",
              "Floors", "Rooms/map", "Mob groups/map (0=all)", "Each floor (N×M)",
              "NPC automation",
              "Terrain"]
    all_rows = list(labels)
    if populate:
        labels = [lab for lab in labels
                  if lab not in ("Floors", "Rooms/map", "Each floor (N×M)", "Terrain")]
    elif generate:
        labels = [lab for lab in labels if lab != "Terrain"]
    row_y = {lab: y0 + i * row_h for i, lab in enumerate(labels)}

    def ry(i):
        return row_y.get(all_rows[i], -1000)

    cr_step   = IntStepper(pygame.Rect(fx, ry(0), fw, 30), 5, 0, 30, font=app.font_md)
    room_step = IntStepper(pygame.Rect(fx, ry(1), fw, 30), 9, 1, 99, font=app.font_md)
    seed_inp  = TextInput(pygame.Rect(fx, ry(5), fw, 30), placeholder="random", font=app.font_md)
    # Floors > 1 builds a stacked multi-floor dungeon (fresh layout + encounter per
    # floor, linked by ladders); Rooms/floor is the carver's per-floor room count.
    floors_step = IntStepper(pygame.Rect(fx, ry(8), fw, 30), 1, 1, 8, font=app.font_md)
    roomsfloor_step = IntStepper(pygame.Rect(fx, ry(9), fw, 30), 4, 3, 12, font=app.font_md)
    # "Each floor: N×M" — tile each floor with N (across) by M (down) maps, laid out
    # edge-to-edge and reachable via the map-paging HUD (both 1 = single map/floor).
    nm_y = ry(11)
    mapsx_step = IntStepper(pygame.Rect(fx,           nm_y, 82, 30), 1, 1, 4, font=app.font_md)
    mapsy_step = IntStepper(pygame.Rect(fx + fw - 82, nm_y, 82, 30), 1, 1, 4, font=app.font_md)
    # npc_automation_difficulty_level written on every mob. Level 1+ hands the strategy choice to the
    # engine's difficulty resolver (role + level at turn time; 4 = best heuristics — casters pick
    # Heal/Control/Support/AoE dynamically). Level 0 keeps the generator's fixed per-category
    # strategies (the legacy Simple/PreferRange/PreferAOE table in encounter_generator.py).
    auto_step = IntStepper(pygame.Rect(fx, ry(12), fw, 30), 4, 0, 6, font=app.font_md)
    # How many rooms per map get a mob group (0 = every room). The entrance stays
    # empty regardless, and a boss finale always counts as one of the groups.
    groups_step = IntStepper(pygame.Rect(fx, ry(10), fw, 30), 0, 0, 99, font=app.font_md)
    start_i, end_i, boss_on = [0], [2], [True]     # Easy -> Hard, boss on
    # Carve a fresh floor plan, or keep the map's terrain and generate mobs only.
    # A premade dungeon (manifest open) defaults to mobs only: its floors are drawn.
    carve_on = [generate or (app.dungeon is None and not populate)]
    CARVE_TXT = {True: "New", False: "Keep (mobs only)"}
    type_selection, lang_selection = set(), set()  # multi-select for both
    # The mob picker's choices, kept across Back so a tweak here doesn't lose them.
    mob_excluded, mob_boss = set(), [None]

    btn_start = Button(pygame.Rect(fx, ry(2), fw, 30), DIFFS[start_i[0]],
                       (70, 90, 120), (95, 115, 150), font=app.font_md)
    btn_end   = Button(pygame.Rect(fx, ry(3), fw, 30), DIFFS[end_i[0]],
                       (70, 90, 120), (95, 115, 150), font=app.font_md)
    btn_boss  = Button(pygame.Rect(fx, ry(4), fw, 30), "ON",
                       (60, 110, 70), (80, 140, 90), font=app.font_md)
    btn_carve = Button(pygame.Rect(fx, ry(13), fw, 30), CARVE_TXT[carve_on[0]],
                       (60, 110, 70), (80, 140, 90), font=app.font_md)
    type_label = ["Any type"]
    btn_type = Button(pygame.Rect(fx, ry(6), fw, 30), type_label[0],
                      (70, 90, 120), (95, 115, 150), font=app.font_md)
    lang_label = ["Any language"]
    btn_lang = Button(pygame.Rect(fx, ry(7), fw, 30), lang_label[0],
                      (70, 90, 120), (95, 115, 150), font=app.font_md)
    gen    = Button(pygame.Rect(box.right - 220, box.bottom - 46, 95, 32),
                    "Populate" if populate else "Generate",
                    (60, 110, 70), (80, 140, 90), font=app.font_md)
    cancel = Button(pygame.Rect(box.right - 115, box.bottom - 46, 95, 32), "Cancel",
                    (110, 60, 60), (150, 80, 80), font=app.font_md)

    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    while True:
        app._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return None
            cr_step.handle(event)
            room_step.handle(event)
            seed_inp.handle(event)
            if not populate:
                floors_step.handle(event)
                roomsfloor_step.handle(event)
                mapsx_step.handle(event)
                mapsy_step.handle(event)
            auto_step.handle(event)
            groups_step.handle(event)
            if btn_start.clicked(event):
                start_i[0] = (start_i[0] + 1) % len(DIFFS)
                btn_start.text = DIFFS[start_i[0]]
            if btn_end.clicked(event):
                end_i[0] = (end_i[0] + 1) % len(DIFFS)
                btn_end.text = DIFFS[end_i[0]]
            if btn_boss.clicked(event):
                boss_on[0] = not boss_on[0]
                btn_boss.text = "ON" if boss_on[0] else "OFF"
            if not (populate or generate) and btn_carve.clicked(event):
                carve_on[0] = not carve_on[0]
                btn_carve.text = CARVE_TXT[carve_on[0]]
            if btn_type.clicked(event):
                app._modal_select_items("Select Mob Types", all_types, type_selection, multi_select=True)
                if type_selection:
                    if len(type_selection) == 1:
                        type_label[0] = list(type_selection)[0]
                    else:
                        type_label[0] = f"{len(type_selection)} types"
                else:
                    type_label[0] = "Any type"
                btn_type.text = type_label[0]
            if btn_lang.clicked(event):
                app._modal_select_items("Select Languages", all_languages, lang_selection, multi_select=True)
                if lang_selection:
                    if len(lang_selection) == 1:
                        lang_label[0] = list(lang_selection)[0]
                    else:
                        lang_label[0] = f"{len(lang_selection)} languages"
                else:
                    lang_label[0] = "Any language"
                btn_lang.text = lang_label[0]
            if cancel.clicked(event):
                return None
            if gen.clicked(event):
                seed = None
                s = seed_inp.text.strip()
                if s:
                    try:
                        seed = int(s)
                    except ValueError:
                        seed = None
                picks = {"allowed_mobs": None, "boss_mob": None}
                if bestiary is not None:
                    picks = app._modal_pick_mobs(
                        bestiary, cr_step.value, list(type_selection) or None,
                        list(lang_selection) or None, boss_on[0], mob_excluded, mob_boss)
                    if picks is None:     # Back: stay here with the settings intact
                        continue
                return {**picks, "cr": cr_step.value, "min_room": room_step.value,
                        "start": DIFFS[start_i[0]], "end": DIFFS[end_i[0]],
                        "boss": boss_on[0], "seed": seed, "carve": carve_on[0],
                        "types": list(type_selection) if type_selection else None,
                        "languages": list(lang_selection) if lang_selection else None,
                        "floors": floors_step.value,
                        "rooms_per_floor": roomsfloor_step.value,
                        "maps_x": mapsx_step.value, "maps_y": mapsy_step.value,
                        "automation": auto_step.value,
                        "groups": groups_step.value}
        app.screen.blit(overlay, (0, 0))
        pygame.draw.rect(app.screen, (35, 35, 50), box, border_radius=8)
        pygame.draw.rect(app.screen, (90, 90, 110), box, 1, border_radius=8)
        app.screen.blit(app.font_lg.render("Populate Floor" if populate else "Generate Dungeon",
                                           True, (235, 235, 245)),
                         (lx, box.y + 18))
        for i, lab in enumerate(labels):
            # Floors / Rooms/map / N×M only shape a carve; dim them when mobs only.
            dim = not carve_on[0] and lab in ("Floors", "Rooms/map", "Each floor (N×M)")
            app.screen.blit(app.font_md.render(lab, True,
                                                 (110, 110, 125) if dim else (185, 185, 200)),
                             (lx, row_y[lab] + 6))
        # "×" separator between the two N×M steppers.
        xt = app.font_md.render("×", True, (185, 185, 200))
        if not populate:
            app.screen.blit(xt, (fx + fw // 2 - xt.get_width() // 2, nm_y + 6))
        shown = [cr_step, room_step, seed_inp, btn_start, btn_end, btn_boss, btn_type,
                 btn_lang, auto_step, groups_step, gen, cancel]
        if not populate:
            shown += [floors_step, roomsfloor_step, mapsx_step, mapsy_step]
            if not generate:
                shown.append(btn_carve)
        for w in shown:
            w.draw(app.screen)
        pygame.display.flip()
        app.clock.tick(60)


def mob_picker_layout(app) -> dict:
    """The mob picker's rects, in one place for the modal and its test."""
    sw, sh = app.screen.get_size()
    W, H = min(960, sw - 60), min(720, sh - 60)
    box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
    preview_w = min(340, W // 3)
    lx = box.x + 20
    list_w = W - preview_w - 50
    crs_x = lx + list_w - 90       # the toolbar sits right-aligned over the list
    all_x = crs_x - 2 * 60 - 12
    return {
        "box": box,
        "search": pygame.Rect(lx + 50, box.y + 54, all_x - lx - 58, 28),
        "all": pygame.Rect(all_x, box.y + 54, 60, 28),
        "none": pygame.Rect(all_x + 66, box.y + 54, 60, 28),
        "crs": pygame.Rect(crs_x, box.y + 54, 90, 28),
        "list": pygame.Rect(lx, box.y + 92, list_w, H - 92 - 60),
        "preview": pygame.Rect(box.right - preview_w - 20, box.y + 54,
                               preview_w, H - 54 - 60),
        "generate": pygame.Rect(box.right - 220, box.bottom - 46, 95, 32),
        "back": pygame.Rect(box.right - 115, box.bottom - 46, 95, 32),
        "row_h": 28,
    }


def modal_pick_mobs(app, bestiary, cr, types, languages, boss_on,
                     excluded: set, boss: list) -> dict | None:
    """Blocking picker between the Generate Dungeon settings and the generation.

    Lists every monster the generator could draw at this CR and filter set. Clicking a
    row ticks or unticks it, clicking its star makes it the boss, and hovering shows
    its stat block. "All CRs" adds the rest of the bestiary, as boss-only rows: a
    regular room's CR band would never draw them, so a tick there would mean nothing.

    Returns {allowed_mobs, boss_mob} or None for Back. allowed_mobs is None when
    nothing was unticked, so an untouched picker generates exactly what it always did.
    excluded and boss[0] are updated in place to survive a Back."""
    import encounter_generator as eg
    band = bestiary.candidates(cr, types, languages)
    if not band:
        app._modal_message(["Generate Dungeon",
                             "No monster matches the Mob type and Languages filters."])
        return None
    band_set = set(band)
    everything = bestiary.candidates(cr, types, languages, all_crs=True)
    if boss[0] not in everything:
        boss[0] = None

    ui = app._mob_picker_layout()
    box, list_rect, row_h = ui["box"], ui["list"], ui["row_h"]
    search = TextInput(ui["search"], placeholder="name or type", font=app.font_md)
    btn_all = Button(ui["all"], "All", (70, 90, 120), (95, 115, 150), font=app.font_md)
    btn_none = Button(ui["none"], "None", (70, 90, 120), (95, 115, 150), font=app.font_md)
    btn_crs = Button(ui["crs"], "All CRs", (70, 90, 120), (95, 115, 150), font=app.font_md)
    btn_gen = Button(ui["generate"], "Generate", (60, 110, 70), (80, 140, 90), font=app.font_md)
    btn_back = Button(ui["back"], "Back", (110, 60, 60), (150, 80, 80), font=app.font_md)
    show_all = [False]
    scroll = [0]
    preview_name = [boss[0] or band[0]]
    star_x = list_rect.x + 34      # the star's column; left of it is the tick box
    overlay = pygame.Surface(app.screen.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))

    def mob_type(name):
        return bestiary.mobs[name].get("meta", {}).get("type", "")

    def visible():
        needle = search.text.strip().lower()
        names = everything if show_all[0] else band
        return [n for n in names
                if not needle or needle in n.lower() or needle in mob_type(n).lower()]

    def row_at(pos, names):
        if not list_rect.collidepoint(pos):
            return None
        i = (pos[1] - list_rect.y + scroll[0]) // row_h
        return names[i] if 0 <= i < len(names) else None

    def clamp_scroll(names):
        limit = max(0, len(names) * row_h - list_rect.height)
        scroll[0] = max(0, min(scroll[0], limit))

    def chosen():
        """Ticked names that regular rooms can draw: the boss is never an ordinary mob."""
        return [n for n in band if n not in excluded and n != boss[0]]

    def draw_star(cx, cy, lit):
        points = [(cx + (8 if k % 2 == 0 else 3) * math.sin(k * math.pi / 5),
                   cy - (8 if k % 2 == 0 else 3) * math.cos(k * math.pi / 5))
                  for k in range(10)]
        if lit:
            pygame.draw.polygon(app.screen, (240, 200, 70), points)
        else:
            pygame.draw.polygon(app.screen, (120, 120, 135), points, 1)

    while True:
        app._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return None
            search.handle(event)
            names = visible()
            clamp_scroll(names)
            if event.type == pygame.MOUSEWHEEL:
                scroll[0] -= event.y * row_h
                clamp_scroll(names)
            if event.type == pygame.MOUSEMOTION:
                hovered = row_at(event.pos, names)
                if hovered:
                    preview_name[0] = hovered
            if btn_all.clicked(event):         # All/None act on the rows the search shows
                excluded.difference_update(names)
            if btn_none.clicked(event):
                excluded.update(n for n in names if n in band_set)
            if btn_crs.clicked(event):
                show_all[0] = not show_all[0]
                btn_crs.text = "This CR" if show_all[0] else "All CRs"
                scroll[0] = 0
            if btn_back.clicked(event):
                return None
            if btn_gen.clicked(event) and chosen():
                picked = chosen()
                untouched = boss[0] is None and len(picked) == len(band)
                return {"allowed_mobs": None if untouched else picked, "boss_mob": boss[0]}
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                name = row_at(event.pos, names)
                if name:
                    preview_name[0] = name
                    if boss_on and star_x - 12 <= event.pos[0] < star_x + 12:
                        boss[0] = None if boss[0] == name else name
                    elif name in band_set:
                        excluded.symmetric_difference_update({name})

        app.screen.blit(overlay, (0, 0))
        pygame.draw.rect(app.screen, (35, 35, 50), box, border_radius=8)
        pygame.draw.rect(app.screen, (90, 90, 110), box, 1, border_radius=8)
        app.screen.blit(app.font_lg.render(f"Choose the mobs (target CR {cr})", True,
                                             (235, 235, 245)), (box.x + 20, box.y + 18))
        app.screen.blit(app.font_md.render("Find", True, (185, 185, 200)),
                         (box.x + 20, ui["search"].y + 4))
        for w in (search, btn_all, btn_none, btn_crs, btn_gen, btn_back):
            w.draw(app.screen)

        # ── The list ──────────────────────────────────────────────────────
        names = visible()
        clamp_scroll(names)
        pygame.draw.rect(app.screen, (25, 25, 40), list_rect, border_radius=4)
        app.screen.set_clip(list_rect)
        first = scroll[0] // row_h
        for i in range(first, min(len(names), first + list_rect.height // row_h + 2)):
            name = names[i]
            y = list_rect.y + i * row_h - scroll[0]
            ticked = name in band_set and name not in excluded
            row = pygame.Rect(list_rect.x, y, list_rect.width, row_h)
            pygame.draw.rect(app.screen, (60, 110, 70) if ticked else (45, 45, 65), row)
            pygame.draw.rect(app.screen, (65, 65, 85), row, 1)
            if name in band_set:
                pygame.draw.rect(app.screen, (255, 255, 255) if ticked else (150, 150, 150),
                                 (list_rect.x + 8, y + 6, 16, 16), 0 if ticked else 1)
            if boss_on:
                draw_star(star_x, y + row_h // 2, boss[0] == name)
            col = (235, 235, 235) if name in band_set else (160, 160, 175)
            app.screen.blit(app.font_sm.render(name, True, col), (star_x + 16, y + 6))
            info = app.font_sm.render(
                f"CR {bestiary.mobs[name]['meta'].get('cr', '?')}  "
                f"{eg.Bestiary._base_type(mob_type(name))}", True, (185, 185, 200))
            app.screen.blit(info, (list_rect.right - info.get_width() - 8, y + 6))
        app.screen.set_clip(None)
        pygame.draw.rect(app.screen, (70, 70, 85), list_rect, 1, border_radius=4)

        # ── The preview ───────────────────────────────────────────────────
        pv = ui["preview"]
        pygame.draw.rect(app.screen, (25, 25, 40), pv, border_radius=4)
        pygame.draw.rect(app.screen, (70, 70, 85), pv, 1, border_radius=4)
        app.screen.set_clip(pv)
        rec = bestiary.mobs[preview_name[0]]
        sprite = app._get_sprite(app._get_mob_sprite_path(preview_name[0]), 64)
        if sprite:
            app.screen.blit(sprite, (pv.right - 74, pv.y + 10))
        app.screen.blit(app.font_md.render(preview_name[0], True, (235, 235, 245)),
                         (pv.x + 10, pv.y + 10))
        line_y = pv.y + 84
        wrap_at = max(20, (pv.width - 20) // max(1, app.font_sm.size("n")[0]))
        for line in eg.mob_preview_lines(rec):
            for part in textwrap.wrap(line, wrap_at, subsequent_indent="    ") or [""]:
                app.screen.blit(app.font_sm.render(part, True, (205, 205, 215)),
                                 (pv.x + 10, line_y))
                line_y += app.font_sm.get_linesize()
        app.screen.set_clip(None)

        # ── The tally ─────────────────────────────────────────────────────
        count = len(chosen())
        boss_text = ("Boss finale off" if not boss_on
                     else f"Boss: {boss[0]}" if boss[0] else "Boss: automatic")
        tally = f"{count} of {len(band)} mobs in the draw. {boss_text}"
        if not count:
            tally = "Tick at least one mob besides the boss."
        app.screen.blit(app.font_md.render(tally, True,
                                             (185, 185, 200) if count else (235, 140, 120)),
                         (box.x + 20, box.bottom - 40))
        pygame.display.flip()
        app.clock.tick(60)


def on_generate_dungeon(app):
    """DM-mode: carve a fresh terrain floor plan (unless "Terrain" is "Keep (mobs only)"),
    then fill its rooms with one progressive-difficulty encounter — category
    weights ramp from the start to the peak difficulty as the party goes
    deeper, with a boss in the last room — and load it into the scene. One RNG
    drives both the carve and the populate, so a seed reproduces the whole
    dungeon. Delegates to tools/encounter_generator.build_dungeon."""
    if not getattr(app.bm, "grid_cols", 0):
        app._modal_message(["Generate Dungeon",
                             "No grid on this map — set a grid first."])
        return
    params = app._modal_generate_dungeon()
    if not params:
        return
    if on_blank_map(app):
        ask_generated_dungeon_name(app, params)
        return
    multi = params.get("carve", True) and (params.get("floors", 1) > 1
                                           or params.get("maps_x", 1) > 1
                                           or params.get("maps_y", 1) > 1)
    app._confirm_overwrite(
        app._generation_targets(params, multi=multi, agents_path=dungeon_out_path(app)),
        "Generate Dungeon", lambda: generate_dungeon_with(app, params))


def on_populate_floor(app):
    """Dungeon → Populate Floor… (plans/DUNGEON_WIZARD_PLAN.md D3): fill the current
    floor's map of the open dungeon with a progressive encounter, keeping its terrain.
    This is the generator's old "Terrain: Keep (mobs only)"."""
    if app.dungeon is None:
        app._flash_status("Populate Floor needs an open dungeon.")
        return
    if not getattr(app.bm, "grid_cols", 0):
        app._modal_message(["Populate Floor",
                             "No grid on this map — set a grid first."])
        return
    params = app._modal_generate_dungeon(populate=True)
    if not params:
        return
    params["carve"] = False
    app._confirm_overwrite(
        app._generation_targets(params, multi=False, agents_path=dungeon_out_path(app)),
        "Populate Floor", lambda: generate_dungeon_with(app, params))


def generate_dungeon_with(app, params):
    """on_generate_dungeon once any overwrite is confirmed."""
    # A generated dungeon is meant to be explored, so fog starts ON (both the
    # single-map and multi-floor paths below). The DM can still flip it off.
    app._set_fog(True)

    # Lazy import: repo/tools is not on sys.path for the GUI process.
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import encounter_generator as eg
    except Exception as e:
        app._modal_message(["Generate Dungeon failed", f"Could not load generator: {e}"])
        return

    # Multi-floor or multi-map-per-floor: carve + populate a fresh layout per tile and
    # wire up the manifest. Terrain params for the carver are derived from the dungeon
    # modal (Rooms/floor + a min room side inferred from "Min room cells"); floors stack
    # with ladders and each floor tiles into maps_x × maps_y maps. "Terrain: Keep
    # (mobs only)" never takes this branch: it populates the current map's terrain.
    if params.get("carve", True) and (params.get("floors", 1) > 1 or params.get("maps_x", 1) > 1
                                      or params.get("maps_y", 1) > 1):
        terrain_params = {
            "rooms": params["rooms_per_floor"],
            "min_room": max(2, int(round(params["min_room"] ** 0.5))),
            "margin": 1, "seed": params["seed"], "floors": params["floors"],
        }
        app._modal_message(["Generating maps…"], blocking=False)
        try:
            summary = generate_multifloor(app, 
                params["floors"], terrain_params, encounter_params=params,
                base=app._generated_base(),
                maps_x=params.get("maps_x", 1), maps_y=params.get("maps_y", 1))
        except ValueError as e:
            app._modal_message(["Generate Dungeon failed", str(e),
                                 "Try fewer/smaller rooms or a bigger grid."])
            return
        app._modal_message(summary)
        return

    app._modal_message(["Generating dungeon…"], blocking=False)
    rng = random.Random(params["seed"])

    # Carve a fresh floor plan first (default), then populate exactly those rooms
    # below — the same rng drives both, so one seed reproduces terrain + encounter
    # together. Terrain params mirror the multi-floor branch: Rooms/map is the
    # carver's room count and the min room side is inferred from "Min room cells".
    # "Terrain: Keep (mobs only)" keeps the old behavior (populate the existing terrain).
    if params.get("carve", True):
        try:
            import dungeon_from_png as dfp
        except Exception as e:
            app._modal_message(["Generate Dungeon failed",
                                 f"Could not load carver: {e}"])
            return
        terrain_params = {
            "rooms": params["rooms_per_floor"],
            "min_room": max(2, int(round(params["min_room"] ** 0.5))),
            "margin": 1,
        }
        try:
            carve_current_map(app, dfp, terrain_params, rng)
        except ValueError as e:
            app._modal_message(["Generate Dungeon failed", str(e),
                                 "Try fewer/smaller rooms or a bigger grid."])
            return

    lines = populate_current_map(app, params, eg, rng, dungeon_out_path(app))
    if lines:
        app._modal_message(lines)


def populate_current_map(app, params, eg, rng, out_path):
    """Fill the live map's rooms with the generated encounter, write it to ``out_path``
    and load it as the scene's roster. Returns the closing message's lines, or None
    after reporting why nothing was placed."""
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        bestiary = eg.Bestiary(data_dir=gui_dir)
        # Prefer dungeon_from_png walk-order room metadata if the terrain carries it
        # (always the case after the carve above); otherwise build_dungeon
        # flood-fills the live map and orders by distance.
        terrain = {"rooms": getattr(app, "_terrain_rooms", []) or []}
        rooms, results, note = eg.build_dungeon(
            app.bm, rpg, terrain, bestiary, cr=params["cr"],
            difficulty_start=params["start"], difficulty_end=params["end"],
            min_room=params["min_room"], boss=params["boss"], entrance=None,
            automation_level=params.get("automation", 4), rng=rng, place=True,
            filter_types=params.get("types"), filter_languages=params.get("languages"),
            groups=params.get("groups") or None, reserve_entrance=True,
            allowed=params.get("allowed_mobs"), boss_name=params.get("boss_mob"))
    except Exception as e:
        app._modal_message(["Generate Dungeon failed", str(e)])
        return None

    if not rooms:
        app._modal_message(["Generate Dungeon", "No rooms detected on this map.",
                             "Load/paint terrain with walls, or lower Min room cells."])
        return None
    # Leave the walk-order entrance (room 0) empty so Load PCs has a clear staging
    # room to drop the party into. results are in walk order, so results[0] is that
    # entrance; the boss (if any) is forced into the LAST room, so this never drops it.
    keep = results[1:] if len(results) > 1 else results
    all_agents = [a for res in keep for a in res["agents"]]
    if not all_agents:
        app._modal_message(["Generate Dungeon",
                             "Rooms were too small to place any mobs."])
        return None
    # Record the exact (post-filter) room the generator left empty — rooms[0], matching
    # results[0] — so Load PCs drops the party there rather than re-deriving "room 0".
    # Persist it into the terrain sidecar so it survives the _load_agents reload below.
    app._staging_cells = [[int(c), int(r)] for (c, r) in rooms[0]] if rooms else None
    app._save_terrain()

    # Write an encounter file next to the map, make it the active base, and load it
    # through the normal path (reuses all agent-instantiation logic). On a page of an
    # open dungeon, the mobs go into that page's own encounter file instead: a new
    # base would re-point the terrain sidecar and leave the manifest page pointing at
    # the old roster, so the mobs would vanish on the next page switch.
    meta = {"mode": "dungeon-gui", "seed": params["seed"],
            "difficulty_start": params["start"],
            "difficulty_end": params["end"], "boss": params["boss"],
            "ordering": note}
    if params.get("types"):
        meta["filter_types"] = params["types"]
    if params.get("languages"):
        meta["filter_languages"] = params["languages"]
    if params.get("allowed_mobs"):
        meta["allowed_mobs"] = params["allowed_mobs"]
    if params.get("boss_mob"):
        meta["boss_mob"] = params["boss_mob"]
    if isinstance(app.store, CampaignStore) and out_path == app._save_path:
        # A campaign run: the scene's agents path is the store's identity, not a file
        # (scene_store.scene_paths), and _load_agents reads the run. Writing a file
        # there would leave the run's old roster on the map.
        app.store.write_creatures({"agents": all_agents, "map_items": [],
                                   "active_conditions": []})
        app._load_agents()
    else:
        eg.write_agents_file(
            out_path, all_agents, difficulty=params["end"], target_cr=params["cr"],
            generator_meta=meta)
        app._set_encounter_base(out_path)
        app._load_agents(out_path)

    boss_line = "  + boss finale" if params["boss"] else ""
    if params["boss"] and params.get("boss_mob"):
        boss_line = f"  + boss: {params['boss_mob']}"
    lines = [
        f"Dungeon generated: {len(all_agents)} mobs",
        f"{len(rooms)} rooms, {params['start']} -> {params['end']}{boss_line}",
        f"Room 0 left empty -> click Load PCs to drop the party there",
        f"Ordering: {note}",
        f"Saved: {os.path.basename(out_path)}",
    ]
    if any(r.get("boss_dropped") for r in results):
        lines.insert(2, f"{params['boss_mob']} did not fit in the finale room, "
                        "so its toughest mob is the boss.")
    return lines


# ── Generate Dungeon on the blank map: a named dungeon in "random_encounters" ──
RANDOM_CAMPAIGN = "random_encounters"
BLANK_MAP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "maps", "Blank.png"))


def on_blank_map(app) -> bool:
    """True when the scene is the bundled blank map, loose: no dungeon or campaign open.
    Generating there names a new dungeon instead of writing ``Blank_*`` sidecars."""
    if app.dungeon is not None or isinstance(getattr(app, "store", None), CampaignStore):
        return False
    try:
        return os.path.samefile(app._map_path, BLANK_MAP)
    except (OSError, TypeError):
        return False


def random_campaign_root(app) -> str:
    return os.path.join(app_dungeon_pages.campaigns_root(app), RANDOM_CAMPAIGN)


def ask_generated_dungeon_name(app, params):
    """Ask what the dungeon is called; confirm before replacing one of that name."""
    name = app._modal_text_prompt("Generate Dungeon", "Dungeon name:", ok_label="Generate")
    if not name or not name.strip():
        return
    try:
        target = campaign_import.generated_dungeon_dir(random_campaign_root(app), name)
    except ValueError as e:
        app._flash_status(f"Generate Dungeon: {e}")
        return
    app._confirm_overwrite([target], "Generate Dungeon",
                           lambda: generate_named_dungeon(app, params, name))


def _scratch_pages(app, scratch, slug, params, eg) -> tuple[list, str, list] | None:
    """Generate into ``scratch`` (old-shape files) and read the pages back:
    ``(pages, entry map, summary lines)``, or None after reporting a failure."""
    image = app._map_path
    cols, rows = app._grid_size()
    if params.get("carve", True):
        terrain_params = {
            "rooms": params["rooms_per_floor"],
            "min_room": max(2, int(round(params["min_room"] ** 0.5))),
            "margin": 1, "seed": params["seed"], "floors": params["floors"],
        }
        app._modal_message(["Generating maps…"], blocking=False)
        try:
            summary = generate_multifloor(
                app, params["floors"], terrain_params, encounter_params=params, base=slug,
                maps_x=params.get("maps_x", 1), maps_y=params.get("maps_y", 1),
                out_dir=scratch, activate=False)
        except ValueError as e:
            app._modal_message(["Generate Dungeon failed", str(e),
                                 "Try fewer/smaller rooms or a bigger grid."])
            return None
        v1 = Dungeon.load(os.path.join(scratch, f"{slug}.dungeon.json"))
        pages = []
        for p in v1.pages:
            agents = os.path.join(scratch, p.encounter_base)
            terrain = agents[:-len("_agents.json")] + "_terrain.json"
            pages.append(campaign_import.GeneratedPage(
                map=p.id, image=image, terrain=campaign_import.read_json(terrain),
                agents=campaign_import.read_json(agents), origin=list(p.origin),
                cols=p.cols, rows=p.rows))
        if params["floors"] <= 1:
            summary = [l for l in summary if not l.startswith("Use Floor +/-")]
        return pages, v1.entry_page_id, summary

    # "Terrain: Keep (mobs only)": populate the map as it stands, saved to scratch.
    app._modal_message(["Generating dungeon…"], blocking=False)
    app._set_encounter_base(os.path.join(scratch, f"{slug}_agents.json"))
    summary = populate_current_map(app, params, eg, random.Random(params["seed"]),
                                   app._save_path)
    if not summary:
        return None
    summary = [l for l in summary if not l.startswith("Saved:")]
    page = campaign_import.GeneratedPage(
        map="floor0", image=image,
        terrain=campaign_import.read_json(app._terrain_path),
        agents=campaign_import.read_json(app._save_path), cols=cols, rows=rows)
    return [page], "floor0", summary


def generate_named_dungeon(app, params, name, *, camp_root=None,
                           camp_name=RANDOM_CAMPAIGN, replace=True) -> bool:
    """Generate on the blank map, then file the result as the dungeon ``name`` of a
    campaign (``camp_root``, default the random_encounters campaign; made, named
    ``camp_name``, when it does not exist yet) and open it. The generator writes to a
    scratch folder, so no ``Blank_*`` file is touched. With ``replace`` a dungeon already
    called ``name`` is archived (the overwrite was confirmed before this runs); without
    it, it is refused. True when the dungeon was made and opened."""
    camp_root = camp_root or random_campaign_root(app)
    app._set_fog(True)
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import encounter_generator as eg
    except Exception as e:
        app._modal_message(["Generate Dungeon failed", f"Could not load generator: {e}"])
        return False

    slug = save_layout.slugify(name)
    old_save = app._save_path
    scratch = tempfile.mkdtemp(prefix="gen_dungeon_")
    made = None
    try:
        got = _scratch_pages(app, scratch, slug, params, eg)
        if got is not None:
            pages, entry, summary = got
            made = campaign_import.new_generated_dungeon(
                camp_root, name, pages, entry_map=entry,
                campaign_name=camp_name, replace=replace,
                stamp=time.strftime("%Y%m%d-%H%M%S"))
    except (OSError, ValueError) as e:
        app._modal_message(["Generate Dungeon failed", str(e)])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if made is None:
        if app._save_path != old_save:     # Keep-terrain path re-pointed it at scratch
            app._set_encounter_base(old_save)
        return False
    if not app_dungeon_pages.open_campaign_dungeon(app, made.manifest_path):
        return False
    app._modal_message(summary + [f"Saved: {os.path.basename(camp_root)}/{slug}"])
    return True


# ── The New Dungeon wizard's Generate path (plans/DUNGEON_WIZARD_PLAN.md D8) ──

def loose_root() -> str:
    """Where a loose (no campaign) wizard dungeon gets its folder: the maps/ folder
    holding the blank map. Each dungeon is ``<loose_root>/<slug>/<slug>.dungeon.json``."""
    return os.path.dirname(BLANK_MAP)


def load_blank_scene(app) -> None:
    """Leave whatever is open for the bundled blank map, loose: the generator carves on
    the scene's map and grid. A dungeon page showing is saved first, as a page switch
    would; a loose map is left as it is on disk, as opening a dungeon leaves it."""
    if app.dungeon_page is not None:
        app._save_agents()
        app._save_terrain()
    app_dungeon_pages.leave_campaign(app)
    app.dungeon = None
    app.dungeon_page = None
    app._dungeon_manifest_path = None
    app._load_map_png(BLANK_MAP)
    app._set_encounter_base(os.path.splitext(BLANK_MAP)[0] + "_agents.json")
    app._load_terrain()
    app._load_lighting()
    app._load_spell_effects()
    app._load_agents()
    app._mark_fog_dirty()


def generate_loose_dungeon(app, params, name) -> bool:
    """Generate on the blank map into a loose (version 1) dungeon of its own folder,
    ``<loose_root>/<slug>/``, holding the manifest, every page's sidecars and a copy of
    the blank image they all draw on, then open it. Built in a scratch folder and moved
    into place whole, so a failure leaves nothing behind. A taken folder is refused."""
    slug = save_layout.slugify(name)
    out = os.path.join(loose_root(), slug)
    if os.path.exists(out):
        app._modal_message(["Generate Dungeon", f"maps/{slug}/ already exists."])
        return False
    app._set_fog(True)
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.join(os.path.dirname(gui_dir), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    terrain_params = {
        "rooms": params["rooms_per_floor"],
        "min_room": max(2, int(round(params["min_room"] ** 0.5))),
        "margin": 1, "seed": params["seed"], "floors": params["floors"],
    }
    scratch = tempfile.mkdtemp(prefix="gen_dungeon_", dir=loose_root())
    try:
        app._modal_message(["Generating maps…"], blocking=False)
        summary = generate_multifloor(
            app, params["floors"], terrain_params, encounter_params=params, base=slug,
            maps_x=params.get("maps_x", 1), maps_y=params.get("maps_y", 1),
            out_dir=scratch, activate=False)
        # Pages name their image by basename, relative to the manifest.
        shutil.copy2(app._map_path, os.path.join(scratch, os.path.basename(app._map_path)))
        os.rename(scratch, out)
    except (OSError, ValueError) as e:
        shutil.rmtree(scratch, ignore_errors=True)
        app._modal_message(["Generate Dungeon failed", str(e),
                             "Try fewer/smaller rooms or a bigger grid."])
        return False
    manifest = os.path.join(out, f"{slug}.dungeon.json")
    app_dungeon_pages.on_open_dungeon_chosen(app, manifest)
    if app.dungeon is None:
        return False
    if params["floors"] <= 1:
        summary = [l for l in summary if not l.startswith("Use Floor +/-")]
    app._modal_message(summary + [f"Saved: maps/{slug}/{slug}.dungeon.json"])
    return True


def wizard_generate(app, target) -> bool:
    """The wizard's Generate path: today's generator settings (Terrain left out, since a
    new dungeon always carves), then the blank map, then the dungeon ``target`` names,
    in its campaign or loose. True when the dungeon was made and opened; False when the
    settings were cancelled or the build failed (the wizard stays open)."""
    params = app._modal_generate_dungeon(generate=True)
    if not params:
        return False
    params["carve"] = True
    if not on_blank_map(app):
        load_blank_scene(app)
    if target.campaign is None:
        return generate_loose_dungeon(app, params, target.name)
    return generate_named_dungeon(app, params, target.name, camp_root=target.campaign,
                                  camp_name=target.campaign_name, replace=False)
