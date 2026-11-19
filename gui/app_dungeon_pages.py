"""Dungeon pages & navigation: campaigns, multi-page dungeons, page/floor switching,
staircases and Send to page.

Moved out of `App` in APP_REFACTOR_PLAN.md A1.3. Module-level functions taking the app,
the pattern `menus/*.py` and `app_board_render.py` already use. `bm`, `dungeon`,
`dungeon_page` and the rest of the state stay on `app` (D3).

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`menus/dm.py`, `menus/board.py`, `scene_store.py`, `saves.py`,
`floor_overlay.py`, `run_control.py`, tests) or passed as a bound callback. `_draw_panel`
still calls `app._draw_panel_floor_nav`, because `test_dungeon_pages` wraps it on the
instance. main.py otherwise calls this module directly.

Stayed on `App`: `_staircase_ends_here` / `_staircase_cells_here` (see app_board_render),
`_clear_page_mobs` (a staticmethod), `_nearest_unoccupied`, ladders and door links, and
the dungeon generator (`app_dungeon_gen.py`, A5) and the
edge-carry review (`_maybe_carry_edges`, …), which are their own seams.
"""

import json
import os
import re

import pygame

import rpg_battle_map as rpg

import campaign_import
import run_control
import save_layout
from atomic_io import atomic_write_json
from constants import IMAGE_EXTS, JSON_EXTS, PC_FACTION, _ROOM_FLOOD_CAP
from dungeon import Dungeon, MapPage, dungeon_path_for
from menus import dm
from scene_store import CampaignStore, LegacyStore
from widgets import Button, IntStepper


# ── Multi-floor encounter files (a dungeon's Save As / Load) ──────────────
# One encounter file can hold creatures for many pages: each agent and map item
# carries "page" (the page id) and "z" (its floor, for reading the file). Conditions
# carry "page" too, with agent_idx / caster_idx indexing the file's whole agent list.
# The pages' own *_agents.json files stay the live state; this file is an export
# that Load distributes back. An agent without "page" (any single-map encounter)
# goes to the page that is showing.

def page_agents_path(app, page: MapPage) -> str:
    """A dungeon page's own ``_agents.json``, resolved like _switch_to_page does."""
    enc = page.encounter_base
    return enc if (not enc or os.path.isabs(enc)) else os.path.join(dungeon_dir(app), enc)


def save_dungeon_encounter(app, path: str):
    """Save Encounter As on a dungeon: write every page's creatures, map items and
    conditions to ``path``, each tagged with its page. Nothing is re-pointed, and no
    terrain / lighting / effects sidecar is written beside ``path``. Refused when
    ``path`` is one of the pages' own files or the manifest."""
    target = os.path.abspath(path)
    own = {os.path.abspath(page_agents_path(app, p)) for p in app.dungeon.pages}
    if app._dungeon_manifest_path:
        own.add(os.path.abspath(app._dungeon_manifest_path))
    if target in own:
        app._flash_status(f"{os.path.basename(path)} belongs to the dungeon; "
                           "save the encounter under another name")
        return
    app._save_agents()                          # the page that is showing, up to date
    out_agents, out_items, out_conds = [], [], []
    pages_used = 0
    for page in app.dungeon.pages:
        try:
            doc = app.store.creatures(page)
        except ValueError:
            continue
        if doc is None:
            continue
        agents = [a for a in (doc.get("agents") or []) if isinstance(a, dict)]
        base = len(out_agents)
        for a in agents:
            rec = dict(a)
            rec["page"], rec["z"] = page.id, int(page.z)
            out_agents.append(rec)
        for m in doc.get("map_items") or []:
            if isinstance(m, dict):
                rec = dict(m)
                rec["page"], rec["z"] = page.id, int(page.z)
                out_items.append(rec)
        for cd in doc.get("active_conditions") or []:
            if not isinstance(cd, dict):
                continue
            rec = dict(cd)
            rec["page"] = page.id
            rec["agent_idx"] = int(rec.get("agent_idx", -1)) + base
            caster = int(rec.get("caster_idx", -1))
            rec["caster_idx"] = caster + base if caster >= 0 else -1
            out_conds.append(rec)
        if agents:
            pages_used += 1
    atomic_write_json(path, {"agents": out_agents, "map_items": out_items,
                             "active_conditions": out_conds})
    app._flash_status(f"Saved {len(out_agents)} creature(s) on {pages_used} page(s) "
                       f"to {os.path.basename(path)}")


def import_encounter_onto_page(app, path: str):
    """Load Encounter on a dungeon: replace the pages' mobs with the file's creatures,
    and add its map items and conditions. A record tagged with a page goes to that
    page; an untagged one (a single-map encounter) goes to the page that is showing;
    one tagged with a page this dungeon lacks is skipped. On each page that receives
    creatures, its NPCs and any same-named creature are cleared first
    (_clear_page_mobs), so loading an encounter twice doesn't double it. Every page
    keeps its terrain, grid, lighting, effects and file names, and the chosen file is
    never written.

    On the page that is showing, each creature keeps its saved cell when it is free,
    else takes the nearest free cell (an off-grid cell is pulled onto the grid
    first), like Load PCs; one that fits nowhere is dropped. On other pages, whose
    terrain is not loaded, a creature keeps its cell unless another creature holds
    it, then takes the nearest unoccupied cell on that page's grid."""
    if app.combat_active:
        app._flash_status("Finish combat before loading an encounter")
        return
    try:
        with open(path) as f:
            src = json.load(f)
    except Exception as e:                       # noqa: BLE001 — surface read/parse errors
        app._flash_status(f"Could not read {os.path.basename(path)}: {e}")
        return
    incoming = [a for a in (src.get("agents") or []) if isinstance(a, dict)]
    items = [m for m in (src.get("map_items") or []) if isinstance(m, dict)]
    conds = [c for c in (src.get("active_conditions") or []) if isinstance(c, dict)]
    if not incoming and not items:
        app._flash_status(f"No creatures in {os.path.basename(path)}")
        return

    here = app.dungeon_page.id
    pages = {p.id: p for p in app.dungeon.pages}

    def page_of(rec):
        pid = rec.get("page")
        return here if pid in (None, "") else (pid if pid in pages else None)

    def clean(rec):
        rec = dict(rec)
        rec.pop("page", None)
        rec.pop("z", None)
        return rec

    # Group by page, remembering each agent's index in the source file.
    by_page: dict[str, list[tuple[int, dict]]] = {}
    unknown = 0
    for i, a in enumerate(incoming):
        pid = page_of(a)
        if pid is None:
            unknown += 1
            continue
        by_page.setdefault(pid, []).append((i, a))
    items_by_page: dict[str, list[dict]] = {}
    for m in items:
        pid = page_of(m)
        if pid is not None:
            items_by_page.setdefault(pid, []).append(clean(m))

    new_index: dict[int, tuple[str, int]] = {}  # source index -> (page, index there)
    added = dropped = cleared = 0
    docs: dict[str, dict] = {}

    # The page that is showing: persist it, merge with live terrain, reload below.
    if here in by_page or here in items_by_page:
        app._save_agents()
    for pid in set(by_page) | set(items_by_page):
        try:
            doc = app.store.creatures(pages[pid]) or {"agents": [], "map_items": []}
        except ValueError:
            doc = {"agents": [], "map_items": []}
        doc.setdefault("agents", [])
        doc.setdefault("map_items", [])
        docs[pid] = doc
        if pid in by_page:
            n = app._clear_page_mobs(doc, {a.get("name") for _, a in by_page[pid]})
            cleared += n
            if n and pid == here:
                # The showing page places against the live map: take the cleared mobs
                # off it first, or they still hold their cells.
                app.store.write_creatures(doc, pages[pid])
                app._load_agents()
        agents = doc["agents"]
        if pid == here:
            reserved: set[tuple[int, int]] = set()
            cols, rows = app.bm.grid_cols, app.bm.grid_rows
        else:
            page = pages[pid]
            cols, rows = int(page.cols or 0), int(page.rows or 0)
            occupied = set()
            for a in agents:
                sz = max(1, int(a.get("size", 1)))
                for dc in range(sz):
                    for dr in range(sz):
                        occupied.add((int(a.get("col", 0)) + dc, int(a.get("row", 0)) + dr))
        for i, a in by_page.get(pid, []):
            rec = clean(a)
            size = max(1, int(rec.get("size", 1)))
            col, row = int(rec.get("col", 0)), int(rec.get("row", 0))
            if pid == here:
                col = min(max(col, 0), max(0, cols - size))
                row = min(max(row, 0), max(0, rows - size))
                spot = app._merge_free_cell(col, row, size, reserved)
                spot = None if spot is None else (spot.col, spot.row)
                claim = reserved
            else:
                spot = app._nearest_unoccupied(col, row, size, occupied, cols, rows)
                claim = occupied
            if spot is None:
                dropped += 1
                continue
            rec["col"], rec["row"] = spot
            for dc in range(size):
                for dr in range(size):
                    claim.add((spot[0] + dc, spot[1] + dr))
            new_index[i] = (pid, len(agents))
            agents.append(rec)
            added += 1
        doc["map_items"].extend(items_by_page.get(pid, []))

    # Conditions follow their creature; one whose caster landed elsewhere is dropped,
    # as _save_agents drops a condition whose caster is off the map.
    for cd in conds:
        target = new_index.get(int(cd.get("agent_idx", -1)))
        if target is None:
            continue
        caster = int(cd.get("caster_idx", -1))
        rec = clean(cd)
        rec["agent_idx"] = target[1]
        if caster >= 0:
            c = new_index.get(caster)
            if c is None or c[0] != target[0]:
                continue
            rec["caster_idx"] = c[1]
        docs[target[0]].setdefault("active_conditions", []).append(rec)

    for pid, doc in docs.items():
        app.store.write_creatures(doc, pages[pid])
    if here in docs:
        app._load_agents()

    hit = sorted({pid for pid, _ in new_index.values()})
    msg = f"Added {added} creature(s) from {os.path.basename(path)}"
    msg += f" to {hit[0]}" if len(hit) == 1 else f" on {len(hit)} pages"
    if cleared:
        msg += f", replacing {cleared}"
    if dropped:
        msg += f" ({dropped} didn't fit)"
    if unknown:
        msg += f" ({unknown} for pages this dungeon lacks, skipped)"
    app._flash_status(msg)


# ─────────────────────────────────────────────────────────────────────
#  Multi-map dungeons — active-map switching & paging (Phase 3)
#  FLOORS_IMPLEMENTATION_PLAN.md. The engine simulates one BattleMap at a
#  time; a "page" is one PNG placed on a shared global (X, Y, Z) grid.
# ─────────────────────────────────────────────────────────────────────
def apply_page_origin(app, page: MapPage):
    """Stamp the engine map's global placement from ``page`` (Phase 1 fields).
    Defensive: skips silently if the extension predates the origin/z_level
    bindings so the app still runs on an un-rebuilt engine."""
    try:
        app.bm.origin_col = int(page.gx)
        app.bm.origin_row = int(page.gy)
        app.bm.z_level    = int(page.z)
    except AttributeError:
        pass  # engine not yet rebuilt with Phase 1 bindings — global coords stay 0


def switch_to_page(app, page: MapPage, drop_cell=None, carry=None, force=False):
    """Save the current scene, make ``page`` the active map, and reload its scene.

    - ``drop_cell``  : (col,row) on the target where carried agents land (else a
                       free spot near the top-left is chosen).
    - ``carry``      : list of agent indices on the CURRENT page to move onto the
                       target (a portal crossing). They are removed from the source
                       encounter and injected onto the target (incremental spawn,
                       never apply_agent_configs — see [[agent_dual_list_gotcha]]).
    - ``force``      : bypass the out-of-combat guard (used for the initial load).

    Returns True on success. Cross-page switching is out-of-combat only for the
    MVP (see Known Limitations); in combat it refuses with a flash unless forced.
    """
    if app.combat_active and not force:
        app._flash_status("Finish combat before changing maps.")
        return False
    if app.floor_align.active:
        app.floor_align.finish(app, keep=False)   # the nudge belonged to the page we leave

    already_here = (app.dungeon_page is not None and page.id == app.dungeon_page.id)

    # The page's image, from the store (the manifest's relative path, or the
    # campaign's map art). One that has been moved/renamed would take the app down
    # inside _load_map_png — refuse the switch (nothing has changed yet) and say so.
    png = app.store.image(page)
    if not already_here and not (png and os.path.exists(png)):
        app._flash_status(f"Page '{page.id}': map image not found ({page.png or page.id})")
        return False

    # ── 1. Serialize carried agents, then persist the current scene ────────
    carried_records = read_agent_records(app, carry) if carry else []
    if app.dungeon_page is not None and not already_here:
        # Save the source scene WITHOUT the carried agents — they have left it.
        app._save_agents(exclude_indices=set(carry) if carry else None)
        app._save_terrain()
        # Lighting / effects have no GUI re-serializer; they were written when
        # last edited and travel with their encounter base, so nothing to do.

    # ── 2. Swap the PNG + engine map (skip if we're re-entering the same page) ─
    # A load resets the view to Fit; remember the on-screen cell size and pan so the
    # new floor opens at the same zoom (restored in step 5).
    keep_view = None
    if not already_here and app.dungeon_page is not None:
        keep_view = (app.bm.cell_pixel_size * app.map_scale, app.pan_x, app.pan_y)
    if not already_here:
        app._load_map_png(png)
    apply_page_origin(app, page)

    # ── 3. Re-point the sidecars and reload the target scene ───────────────
    app._point_scene_at(page)
    app._load_terrain()
    app._load_lighting()
    app._load_spell_effects()
    app._load_agents()

    app.dungeon_page = page
    # A map the dungeon has never measured (a migrated one-map dungeon), or measured
    # under an older grid, learns its size from the grid it just loaded with.
    app._sync_page_size()

    # ── 4. Inject carried agents onto the target (incremental) ─────────────
    if carried_records:
        inject_carried_agents(app, carried_records, drop_cell)

    # ── 5. Same zoom as the floor we left: match the on-screen cell size (floors
    #       may differ in PNG size, so the fit scale alone would not), then centre
    #       the arrival cell, or keep the old pan when there is none ─────────────
    if keep_view is not None:
        old_cell_px, old_pan_x, old_pan_y = keep_view
        new_cell_px = app.bm.cell_pixel_size * app.base_map_scale
        if old_cell_px > 0 and new_cell_px > 0:
            app._apply_zoom(old_cell_px / new_cell_px)
        if drop_cell is not None:
            c, r = drop_cell
            x0, y0 = app._cell_to_screen(c, r)
            x1, y1 = app._cell_to_screen(c + 1, r + 1)
            app.pan_x += app._panel_x() // 2 - (x0 + x1) // 2
            app.pan_y += app.screen.get_height() // 2 - (y0 + y1) // 2
        else:
            app.pan_x, app.pan_y = old_pan_x, old_pan_y
        app._clamp_pan()

    app._mark_fog_dirty()
    return True


def read_agent_records(app, indices):
    """Return full serialized agent records (the same shape ``_save_agents``
    writes) for ``indices`` on the CURRENT engine map, by round-tripping through a
    temporary encounter file. Reusing the canonical serializer keeps carried agents
    lossless (stats/weapons/spells/armor) without duplicating its logic."""
    if not indices:
        return []
    want = set(indices)
    all_idx = set(range(len(app.bm.placed_agents)))
    tmp = os.path.join(app._map_dir, f".carry_{os.getpid()}.json")
    try:
        app._save_agents(tmp, exclude_indices=(all_idx - want))
        with open(tmp) as f:
            doc = json.load(f)
    except Exception as e:                       # noqa: BLE001 — carry is best-effort
        print(f"Warning: could not serialize carried agents: {e}")
        return []
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return doc.get("agents", [])


def inject_carried_agents(app, records, drop_cell):
    """Persist ``records`` onto the freshly loaded target page and reload so the
    carried party appears there. Agents are repositioned to free cells at/around
    ``drop_cell`` (or the top-left) so they don't collide with the target's own
    residents. This writes them into the target's encounter file — after a crossing
    the party belongs to that page."""
    if not records:
        return
    try:
        doc = app.store.creatures() or {"agents": [], "map_items": []}
    except ValueError:
        doc = {"agents": [], "map_items": []}
    agents = doc.setdefault("agents", [])

    def _footprint(c, r, size):
        return {(c + dc, r + dr) for dc in range(size) for dr in range(size)}

    occupied = set()
    for a in agents:
        occupied |= _footprint(a.get("col"), a.get("row"), a.get("size", 1) or 1)
    cols, rows = app.bm.grid_cols, app.bm.grid_rows
    start_c, start_r = (drop_cell if drop_cell is not None else (0, 0))

    # The landing's room, in flood order (nearest first): the engine's room flood
    # stops at wall cells, edge walls and doors, so the party lands together on the
    # staircase's side of every wall. A landing drawn on dark stair art is often a
    # wall cell itself, which the flood does not pass; seed it from the first open
    # neighbour instead (orthogonal before diagonal, across no edge wall).
    def _room_floor():
        if drop_cell is None:
            return []
        seed = rpg.Cell(start_c, start_r)
        if app.bm.is_blocked(seed, 1):
            seed = None
            for dc, dr in ((0, 1), (1, 0), (0, -1), (-1, 0),
                           (1, 1), (-1, 1), (1, -1), (-1, -1)):
                c, r = start_c + dc, start_r + dr
                if 0 <= c < cols and 0 <= r < rows and not app.bm.is_blocked(rpg.Cell(c, r), 1):
                    seed = rpg.Cell(c, r)
                    break
            if seed is None:
                return []
        return [(c.col, c.row) for c in app.bm.room_cells(seed, _ROOM_FLOOD_CAP)
                if app.bm.door_at(c) < 0 and not app.bm.is_blocked(c, 1)]

    room = _room_floor()
    room_set = set(room)

    def _free_spot(size):
        for c, r in room:
            fp = _footprint(c, r, size)
            if (fp <= room_set and not (fp & occupied)
                    and not app.bm.is_blocked(rpg.Cell(c, r), size)):
                return c, r
        return _any_spot(size)

    def _any_spot(size):
        # Last resort, when the landing's room is full (or there is no landing):
        # spiral-ish scan outward from the drop cell for the first cell the engine
        # will actually place on. _load_agents silently skips a blocked agent —
        # which, since the source page was already saved without it, would lose the
        # creature — so a spot past a wall beats no spot at all.
        for radius in range(0, max(cols, rows) + 1):
            for r in range(max(0, start_r - radius), min(rows - size + 1, start_r + radius + 1)):
                for c in range(max(0, start_c - radius), min(cols - size + 1, start_c + radius + 1)):
                    if (not (_footprint(c, r, size) & occupied)
                            and not app.bm.is_blocked(rpg.Cell(c, r), size)):
                        return c, r
        return start_c, start_r

    for rec in records:
        size = rec.get("size", 1) or 1
        c, r = _free_spot(size)
        rec["col"], rec["row"] = c, r
        occupied |= _footprint(c, r, size)
        agents.append(rec)
    doc.setdefault("map_items", [])
    app.store.write_creatures(doc)
    app._load_agents()


def page_step(app, direction: str):
    """Page to the neighbouring same-floor map (view switch, no carry)."""
    if app.dungeon is None or app.dungeon_page is None:
        return
    nxt = app.dungeon.neighbor(app.dungeon_page, direction)
    if nxt is None:
        app._flash_status(f"No map to the {direction}.")
        return
    if switch_to_page(app, nxt):
        app._flash_status(f"Map: {nxt.id}")


def floor_step(app, delta: int):
    """Change floors (Z ± delta), landing on the page at the party's current
    global (X, Y) if one exists there, else the first page on that floor."""
    if app.dungeon is None or app.dungeon_page is None:
        return
    cur = app.dungeon_page
    target_z = cur.z + delta
    if target_z not in app.dungeon.floors():
        app._flash_status("No floor there.")
        return
    # Prefer the page directly above/below the current view's top-left corner.
    below = app.dungeon.page_at_global(cur.gx, cur.gy, target_z)
    if below is None:
        on_floor = app.dungeon.pages_on_floor(target_z)
        below = on_floor[0] if on_floor else None
    if below is None:
        app._flash_status("No floor there.")
        return
    if switch_to_page(app, below):
        app._flash_status(f"Floor {target_z}: {below.id}")


def dungeon_dir(app) -> str:
    """The folder a page's relative ``png`` / ``encounter_base`` resolves against: the
    manifest's own folder (so a dungeon and its files travel together), falling back to
    the map dir before a manifest exists."""
    if app._dungeon_manifest_path:
        return os.path.dirname(os.path.abspath(app._dungeon_manifest_path)) or app._map_dir
    return app._map_dir


def dungeon_path_ref(app, path: str) -> str:
    """How a page references a file in the manifest: a bare basename when the file sits
    beside the manifest (portable), else an absolute path. ``_switch_to_page`` resolves
    both."""
    if not path:
        return ""
    ap = os.path.abspath(path)
    if os.path.dirname(ap) == os.path.abspath(dungeon_dir(app)):
        return os.path.basename(ap)
    return ap


def dungeon_stem(app) -> str:
    """The manifest's name without the ``.dungeon.json`` suffix — the prefix new
    pages' encounter files are named after."""
    path = app._dungeon_manifest_path or app._save_path
    fn = os.path.basename(path)
    for suffix in (".dungeon.json", "_agents.json", ".json"):
        if fn.endswith(suffix):
            return fn[: -len(suffix)]
    return os.path.splitext(fn)[0]


def unique_page_id(app, seed: str) -> str:
    """``seed``, suffixed with a counter until it is unused in the manifest."""
    seed = re.sub(r"[^\w.-]+", "_", seed).strip("_") or "page"
    cand, n = seed, 2
    while app.dungeon is not None and app.dungeon.page_by_id(cand) is not None:
        cand, n = f"{seed}_{n}", n + 1
    return cand


def campaigns_root(app) -> str:
    """Where New Dungeon lists and makes campaigns: the folder holding the campaign the
    map lives in (encounters/<campaign>/maps/…), else the encounters/ folder beside maps/."""
    camp = save_layout.find_campaign(app._map_dir)
    if camp is not None:
        return os.path.dirname(camp)
    return os.path.join(os.path.dirname(app._map_dir), save_layout.ENCOUNTERS_DIR)


def dungeon_new(app, anchor=None):
    """New Dungeon (plans/NEW_DUNGEON_PLAN.md D1): campaign, then dungeon name, then
    start map. Inside a campaign the campaign is fixed (U4) and the start map comes
    from its library (D5). Otherwise the list is every campaign under encounters/,
    "New campaign…", and "No campaign (loose)" for a version-1 dungeon (D7)."""
    if app.combat_active:
        app._flash_status("Finish combat before starting a dungeon.")
        return
    anchor = anchor or pygame.mouse.get_pos()
    if isinstance(app.store, CampaignStore):
        new_dungeon_named(app, app.store.campaign.root, None, anchor)
        return
    if app.dungeon is not None:
        app._flash_status("Close the dungeon first.")
        return
    cols, rows = app._grid_size()
    if not cols or not rows:
        app._modal_message(["New Dungeon",
                             "This map has no grid — Set Grid… first, so the page",
                             "has a footprint on the global (X, Y, Z) grid."])
        return
    camps = list_campaigns(app)
    items = [(save_layout.Campaign(p).name,
              lambda p=p: new_dungeon_named(app, p, None, anchor)) for p in camps]
    items += [("New campaign…", lambda: new_dungeon_new_campaign(app, anchor)),
              ("No campaign (loose)", app._dungeon_new_loose)]
    app._ask_dm("action", "New Dungeon: campaign", items, anchor=anchor)


def list_campaigns(app) -> list[str]:
    root = campaigns_root(app)
    return [os.path.join(root, d) for d in sorted(os.listdir(root) if os.path.isdir(root) else ())
            if os.path.isfile(os.path.join(root, d, save_layout.CAMPAIGN_FILE))]


def open_campaign(app, anchor=None):
    """Open Campaign…: pick a campaign, then one of its dungeons or New Dungeon… on a
    map from its library — no dungeon of it needs to be open first."""
    if app.combat_active:
        app._flash_status("Finish combat before opening a campaign.")
        return
    anchor = anchor or pygame.mouse.get_pos()
    camps = list_campaigns(app)
    if not camps:
        app._flash_status("No campaigns found.")
        return
    items = [(save_layout.Campaign(p).name,
              lambda p=p: open_campaign_menu(app, p, anchor)) for p in camps]
    app._ask_dm("action", "Open Campaign", items, anchor=anchor)


def open_campaign_menu(app, camp_root, anchor):
    try:
        camp = save_layout.Campaign(camp_root)
        dungeons = camp.list_dungeons()
    except (OSError, ValueError) as e:
        app._flash_status(f"Open Campaign: {e}")
        return
    items = [(d, lambda d=d: open_campaign_dungeon(app, camp.dungeon(d).manifest_path))
             for d in dungeons]
    items.append(("New Dungeon…", lambda: open_campaign_new_dungeon(app, camp, anchor)))
    app._ask_dm("action", camp.name, items, anchor=anchor)


def open_campaign_new_dungeon(app, camp, anchor):
    name = app._modal_text_prompt("New Dungeon", "Dungeon name:", ok_label="Next")
    if not name:
        return
    try:
        save_layout.slugify(name)
    except ValueError as e:
        app._flash_status(f"New Dungeon: {e}")
        return
    if app.dungeon is not None:
        new_dungeon_pick_map(app, name, anchor, camp=camp)
        return
    # A loose map showing: it comes first (brought in as New Dungeon's D2 does),
    # then the campaign's library maps.
    def this_map():
        if not all(app._grid_size()):
            app._modal_message(["New Dungeon",
                                 "This map has no grid — Set Grid… first, so the page",
                                 "has a footprint on the global (X, Y, Z) grid."])
            return
        new_dungeon_from_scene(app, camp.root, None, name, anchor)
    items = [(f"{os.path.basename(app._map_path)} (this map)", this_map)]
    items += [(m, lambda m=m: new_dungeon_write(app, camp.root, None, name, library_map=m))
              for m in camp.list_library_maps()]
    app._ask_dm("action", f"New Dungeon '{name}': start map", items, anchor=anchor)


def new_dungeon_new_campaign(app, anchor):
    """"New campaign…": a typed name; the folder is its slug, -2, -3 when taken."""
    name = app._modal_text_prompt("New campaign", "Campaign name:", ok_label="Next")
    if not name:
        return
    root = campaigns_root(app)
    try:
        slug = save_layout.unique_slug(name, os.listdir(root) if os.path.isdir(root) else ())
    except ValueError as e:
        app._flash_status(f"New campaign: {e}")
        return
    new_dungeon_named(app, os.path.join(root, slug), name, anchor)


def new_dungeon_named(app, camp_root, camp_name, anchor):
    """Ask the dungeon's name, then where its map comes from."""
    name = app._modal_text_prompt("New Dungeon", "Dungeon name:", ok_label="Next")
    if not name:
        return
    try:
        save_layout.slugify(name)
    except ValueError as e:
        app._flash_status(f"New Dungeon: {e}")
        return
    if isinstance(app.store, CampaignStore):
        new_dungeon_pick_map(app, name, anchor)
    else:
        new_dungeon_from_scene(app, camp_root, camp_name, name, anchor)


def new_dungeon_pick_map(app, name, anchor, camp=None):
    """D1 / D5: the start map, from the campaign's library (the open one unless
    ``camp`` is given); the map showing comes first. A library of one map asks nothing."""
    if camp is None:
        camp = app.store.campaign
    maps = camp.list_library_maps()
    showing = (isinstance(app.store, CampaignStore)
               and os.path.samefile(app.store.campaign.root, camp.root))
    cur = app.dungeon_page.id if showing and app.dungeon_page is not None else None
    if cur in maps:
        maps.remove(cur)
        maps.insert(0, cur)
    if not maps:
        app._flash_status(f"{camp.name} has no maps in its library.")
        return

    def write(m):
        cols, rows = app._grid_size() if m == cur else (0, 0)
        new_dungeon_write(app, camp.root, None, name, library_map=m, cols=cols, rows=rows)
    if len(maps) == 1:
        write(maps[0])
        return
    items = [(f"{m} (this map)" if m == cur else m, lambda m=m: write(m)) for m in maps]
    app._ask_dm("action", f"New Dungeon '{name}': start map", items, anchor=anchor)


def new_dungeon_scene(app) -> campaign_import.Scene:
    """The loose map as it stands, for ``campaign_import.new_dungeon``: roster and
    terrain round-tripped through the canonical serializers into temp files, so the
    map's own sidecars are only read (U1)."""
    tmp = os.path.join(app._map_dir, f".new_dungeon_{os.getpid()}")
    docs = {}
    try:
        for key, save in (("agents", app._save_agents), ("terrain", app._save_terrain)):
            save(f"{tmp}_{key}.json")
            with open(f"{tmp}_{key}.json") as f:
                docs[key] = json.load(f)
    finally:
        for key in ("agents", "terrain"):
            try:
                os.remove(f"{tmp}_{key}.json")
            except OSError:
                pass
    cols, rows = app._grid_size()
    session = getattr(app, "_session_path", None)
    return campaign_import.Scene(
        image=app._map_path, terrain=docs["terrain"], agents=docs["agents"],
        cols=cols, rows=rows,
        lighting=app._lighting_path if os.path.isfile(app._lighting_path) else None,
        session=session if session and os.path.isfile(session) else None)


def new_dungeon_from_scene(app, camp_root, camp_name, name, anchor):
    """D2 / D4: the loose map into the campaign. PCs that already have a sheet there
    keep it unless the DM says to update them, asked once."""
    try:
        scene = new_dungeon_scene(app)
    except (OSError, ValueError) as e:
        app._flash_status(f"New Dungeon: could not read the map: {e}")
        return
    conflicts = campaign_import.pc_conflicts(camp_root, scene.agents)

    def write(update):
        return lambda: new_dungeon_write(app, camp_root, camp_name, name, scene=scene,
                                               update_pcs=update)
    if not conflicts:
        write(())()
        return
    app._ask_dm("action", f"Update sheets from the map: {', '.join(conflicts)}?",
                 [("Update", write(conflicts)), ("Keep", write(()))], anchor=anchor,
                 render="titled")


def new_dungeon_write(app, camp_root, camp_name, name, *, scene=None,
                       library_map=None, cols=0, rows=0, update_pcs=()):
    """Write the dungeon (``campaign_import.new_dungeon``) and open it. Inside a
    campaign the scene showing is saved first, so the sheets the new dungeon's party
    is built from are current."""
    if isinstance(app.store, CampaignStore):
        app._save_agents()
        app._save_terrain()
    try:
        made = campaign_import.new_dungeon(
            camp_root, name, scene, library_map=library_map, cols=cols, rows=rows,
            campaign_name=camp_name, update_pcs=update_pcs)
    except (OSError, ValueError) as e:            # noqa: BLE001 — report, keep the scene
        app._flash_status(f"New Dungeon: {e}")
        return
    if made.pcs_kept:
        print(f"New Dungeon: kept the campaign's sheets for {', '.join(made.pcs_kept)}")
    open_campaign_dungeon(app, made.manifest_path)


def dungeon_new_loose(app):
    """"No campaign (loose)" (D7): a version-1 manifest beside the map, with the
    CURRENT map + encounter as its (entry) first page at global origin (0, 0, 0).
    Further pages come from Add Page…."""
    cols, rows = app._grid_size()
    app._confirm_overwrite([dungeon_path_for(app._save_path)], "New Dungeon",
                            lambda: dungeon_new_write(app, cols, rows))


def dungeon_new_write(app, cols, rows):
    # Set the manifest path first: page refs are stored relative to its folder.
    app._dungeon_manifest_path = dungeon_path_for(app._save_path)
    page = MapPage(id=unique_page_id(app, dungeon_stem(app)),
                   png=dungeon_path_ref(app, app._map_path),
                   encounter_base=dungeon_path_ref(app, app._save_path),
                   origin=[0, 0, 0], cols=cols, rows=rows)
    app.dungeon = Dungeon(pages=[page], entry_page_id=page.id)
    app.dungeon_page = page          # already loaded — no page switch needed
    apply_page_origin(app, page)
    dungeon_save(app)


def dungeon_save_confirmed(app, anchor=None):
    """Dungeon → Save Dungeon: _dungeon_save, after asking before overwriting."""
    if app.dungeon is None:
        dungeon_save(app)
        return
    path = app._dungeon_manifest_path or dungeon_path_for(app._save_path)
    app._confirm_overwrite([path, app._save_path, app._terrain_path], "Save Dungeon",
                            app._dungeon_save, anchor=anchor)


def dungeon_save(app):
    """Write the manifest, plus the active page's scene (agents + terrain) so the
    dungeon on disk matches what's on screen."""
    if app.dungeon is None:
        app._flash_status("No dungeon open — New Dungeon first.")
        return
    path = app._dungeon_manifest_path or dungeon_path_for(app._save_path)
    try:
        app.dungeon.save(path)
    except OSError as e:                          # noqa: BLE001 — report, don't crash
        app._flash_status(f"Could not save dungeon: {e}")
        return
    app._dungeon_manifest_path = path
    app._save_agents()
    app._save_terrain()
    app._flash_status(f"Saved {os.path.basename(path)} ({len(app.dungeon.pages)} pages)")


def dungeon_save_manifest(app) -> bool:
    """Write the manifest alone, for staircase edits: the active page's scene is not
    touched (the terrain editor's close saves it on its own)."""
    if app.dungeon is None:
        return False
    path = app._dungeon_manifest_path or dungeon_path_for(app._save_path)
    try:
        app.dungeon.save(path)
    except OSError as e:                          # noqa: BLE001 — report, don't crash
        app._flash_status(f"Could not save dungeon: {e}")
        return False
    app._dungeon_manifest_path = path
    return True


def dungeon_open_browser(app):
    start = os.path.dirname(app._dungeon_manifest_path or app._save_path) or app._map_dir
    app.file_browser.open(
        start, app._on_open_dungeon_chosen,
        save_mode=False,
        extensions=JSON_EXTS,
        name_pattern=".dungeon.json",
        title="Open Dungeon",
    )


def on_open_dungeon_chosen(app, path: str):
    """Open a ``.dungeon.json`` and load its entry page."""
    if app.combat_active:
        app._flash_status("Finish combat before opening a dungeon.")
        return
    try:
        dungeon = Dungeon.load(path)
    except Exception as e:                       # noqa: BLE001 — bad file ⇒ keep the scene
        app._flash_status(f"Not a dungeon manifest: {os.path.basename(path)} ({e})")
        return
    if dungeon.version >= 2:
        open_campaign_dungeon(app, path)
        return
    entry = dungeon.entry_page()
    if entry is None:
        app._flash_status("Dungeon manifest has no pages.")
        return
    leave_campaign(app)
    app.dungeon = dungeon
    app._dungeon_manifest_path = path
    app.dungeon_page = None      # initial load: don't write the outgoing scene back
    if not switch_to_page(app, entry, force=True):
        # Entry page unusable (its PNG is gone) — stay where we were.
        app.dungeon = None
        app._dungeon_manifest_path = None
        return
    app._flash_status(f"Dungeon: {os.path.basename(path)} — {entry.id}")


def open_campaign_dungeon(app, manifest: str, run_name: str = save_layout.DEFAULT_RUN):
    """Open a dungeon of a campaign (plans/SAVE_LAYOUT_PLAN.md D4/D6) on the map its
    run was last on, else its entry map. Everything the scene reads and writes then
    goes through a CampaignStore: map.json, dungeon.json and the run."""
    try:
        camp = save_layout.Campaign.open(manifest)
        layout = camp.dungeon(os.path.basename(os.path.dirname(os.path.abspath(manifest))))
        dungeon = Dungeon.load(layout.manifest_path)
        store = CampaignStore(app, layout, run_name)
    except Exception as e:                       # noqa: BLE001 — bad file ⇒ keep the scene
        app._flash_status(f"Could not open dungeon {manifest}: {e}")
        return False
    page = dungeon.page_by_id(store.run.get("current_map")) or dungeon.entry_page()
    if page is None:
        app._flash_status("Dungeon has no maps.")
        return False
    old = (app.store, app.dungeon, app.dungeon_page, app._dungeon_manifest_path)
    app.store = store
    app.dungeon = dungeon
    app._dungeon_manifest_path = layout.manifest_path
    app.dungeon_page = None      # initial load: don't write the outgoing scene back
    if not switch_to_page(app, page, force=True):
        app.store, app.dungeon, app.dungeon_page, app._dungeon_manifest_path = old
        return False
    party_arrives(app)
    run_control.ensure_first_release(app)    # Reset Dungeon always has a V0
    dm.set_tracker_mode(app, bool(store.run.get("tracker_mode", False)))   # T6
    dm.set_players_map_only(app, bool(store.run.get("players_map_only", False)))
    for w in filter(None, (layout.calibration_warning(p.id) for p in dungeon.pages)):
        print(f"Warning: {w}")
    app._flash_status(f"{camp.name} / {layout.name} — {page.id}")
    return True


def party_arrives(app):
    """Party PCs the run has on no map yet join it (plans/NEW_DUNGEON_PLAN.md D3): on
    the showing page's staging cells, else the entry page's, else on deck. A PC
    already somewhere in the run stays where it is."""
    missing = app.store.missing_party(app.dungeon)
    if not missing:
        return
    page = app.dungeon_page
    if not page.staging_cells:
        page = app.dungeon.entry_page() or page
    if page is app.dungeon_page:
        added, _, _ = app._merge_pcs_here(app.store.arrivals(missing, page),
                                        page.staging_cells, on_deck=True)
    else:
        doc = app.store.creatures(page) or {"agents": [], "map_items": []}
        occupied = [(a.get("col"), a.get("row")) for a in doc.get("agents", [])]
        recs = app.store.arrivals(missing, page, occupied)
        doc.setdefault("agents", []).extend(recs)
        doc.setdefault("map_items", [])
        app.store.write_creatures(doc, page)
        added = len(recs)
    if added:
        print(f"Party: {added} PC(s) joined on {page.id}")


def leave_campaign(app):
    """Back to per-encounter sidecars (opening a loose map or a version 1 dungeon)."""
    if isinstance(app.store, CampaignStore):
        app.store = LegacyStore(app)


def dungeon_close(app):
    """Leave dungeon mode. The manifest stays on disk; the active page's map and
    encounter stay loaded as an ordinary single map."""
    if app.dungeon is None:
        return
    if app.combat_active:
        app._flash_status("Finish combat before closing the dungeon.")
        return
    if isinstance(app.store, CampaignStore):
        app._flash_status("A campaign's maps always belong to a dungeon.")
        return
    app._save_agents()
    app._save_terrain()
    app.dungeon = None
    app.dungeon_page = None
    app._dungeon_manifest_path = None
    app._flash_status("Dungeon closed — single-map mode.")


def dungeon_add_page_browser(app):
    if app.dungeon is None:
        app._flash_status("No dungeon open — New Dungeon first.")
        return
    app.file_browser.open(
        dungeon_dir(app), app._on_add_page_png_chosen,
        save_mode=False,
        extensions=IMAGE_EXTS,
        title="Add Page — Select Map Image",
    )


def on_add_page_png_chosen(app, png_path: str):
    """Add ``png_path`` as a new page, east of the current floor's rightmost page,
    with a fresh empty encounter, and switch to it. The page's footprint
    (cols × rows) is only known once its grid is analyzed, so it is recorded after
    the switch; the origin can then be moved in the Pages overview."""
    if app.dungeon is None:
        return
    if app.combat_active:
        app._flash_status("Finish combat before adding a page.")
        return
    cur = app.dungeon_page
    z  = cur.z  if cur else 0
    gy = cur.gy if cur else 0
    on_floor = app.dungeon.pages_on_floor(z)
    gx = max((p.gx + p.cols for p in on_floor), default=0)

    page_id = unique_page_id(app, os.path.splitext(os.path.basename(png_path))[0])
    # Each page owns its own encounter sidecars: <manifest stem>_<page id>_agents.json,
    # written beside the manifest.
    agents_path = os.path.join(dungeon_dir(app),
                               f"{dungeon_stem(app)}_{page_id}_agents.json")
    if not os.path.exists(agents_path):
        try:
            with open(agents_path, "w") as f:
                json.dump({"agents": [], "map_items": []}, f, indent=2)
        except OSError as e:                     # noqa: BLE001
            app._flash_status(f"Could not create {os.path.basename(agents_path)}: {e}")
            return

    page = MapPage(id=page_id, png=dungeon_path_ref(app, png_path),
                   encounter_base=dungeon_path_ref(app, agents_path),
                   origin=[gx, gy, z], cols=0, rows=0)
    app.dungeon.add_page(page)
    if not switch_to_page(app, page):
        app.dungeon.remove_page(page_id)        # switch refused — don't keep a page we can't open
        return
    page.cols = int(getattr(app.bm, "grid_cols", 0) or 0)
    page.rows = int(getattr(app.bm, "grid_rows", 0) or 0)
    apply_page_origin(app, page)
    dungeon_save(app)
    if not page.cols or not page.rows:
        app._modal_message(["Page added — but it has no grid",
                             f"'{page_id}' has no detected grid, so it has no footprint",
                             "on the global map. Use Set Grid…, then re-save the dungeon",
                             "(Dungeon… → Save Dungeon) to record its size."])
    else:
        app._flash_status(f"Added page '{page_id}' at ({gx}, {gy}, {z})")


def dungeon_pages_overview(app):
    """Run the Pages overview modal, then apply what it asked for: persist the
    manifest, re-stamp the engine's origin if the ACTIVE page moved, and switch
    pages on a Go To (done out here — a page switch resizes the window, so it must
    not happen inside the modal's own draw loop)."""
    if app.dungeon is None:
        app._flash_status("No dungeon open — New Dungeon first.")
        return
    goto = modal_dungeon_pages(app)
    # The overview edits the manifest in place (origins / entry / removals), so it is
    # always written back on exit.
    dungeon_save(app)
    if app.dungeon_page is not None and app.dungeon.page_by_id(app.dungeon_page.id) is None:
        # The active page was removed — fall back to the entry page.
        entry = app.dungeon.entry_page()
        app.dungeon_page = None
        if entry is None:
            app._flash_status("Dungeon has no pages left.")
            return
        switch_to_page(app, entry, force=True)
        return
    if goto is not None and (app.dungeon_page is None or goto.id != app.dungeon_page.id):
        if switch_to_page(app, goto):
            app._flash_status(f"Page: {goto.id} (floor {goto.z})")
        return
    if app.dungeon_page is not None:
        apply_page_origin(app, app.dungeon_page)   # its origin may have moved


def modal_dungeon_pages(app) -> "MapPage | None":
    """Blocking Pages / Overview dialog: the manifest's page list, a map of the
    selected page's floor (drawn from the origins), and the selected page's global
    origin (X/Y/Z steppers). Edits apply to the manifest immediately; the caller
    persists them. Returns the page to switch to (Go To), else None."""
    dung = app.dungeon
    sw, sh = app.screen.get_size()
    W, H = min(820, sw - 60), min(560, sh - 60)
    box = pygame.Rect((sw - W) // 2, (sh - H) // 2, W, H)
    lx  = box.x + 20
    list_w = 300
    list_rect = pygame.Rect(lx, box.y + 56, list_w, H - 160)
    ov_rect   = pygame.Rect(list_rect.right + 16, list_rect.y,
                            box.right - 20 - (list_rect.right + 16), list_rect.h - 46)
    ROW_H = 22

    sel = dung.page_by_id(app.dungeon_page.id) if app.dungeon_page else dung.entry_page()
    sel_id = sel.id if sel else None

    # Origin steppers for the selected page (re-seeded whenever the selection changes).
    st_y = ov_rect.bottom + 12
    sx = IntStepper(pygame.Rect(ov_rect.x + 26,       st_y, 92, 30), 0, -999, 999, font=app.font_sm)
    sy = IntStepper(pygame.Rect(ov_rect.x + 26 + 108, st_y, 92, 30), 0, -999, 999, font=app.font_sm)
    sz = IntStepper(pygame.Rect(ov_rect.x + 26 + 216, st_y, 92, 30), 0, -99,   99, font=app.font_sm)

    def seed_steppers():
        p = dung.page_by_id(sel_id)
        if p is None:
            return
        sx.value, sy.value, sz.value = p.gx, p.gy, p.z

    seed_steppers()

    by = box.bottom - 46
    btn_entry  = Button(pygame.Rect(lx,             by, 96, 32), "Set Entry",
                        (70, 90, 120), (95, 115, 150), font=app.font_sm)
    btn_goto   = Button(pygame.Rect(lx + 104,       by, 96, 32), "Go To Page",
                        (60, 110, 70), (80, 140, 90), font=app.font_sm)
    btn_remove = Button(pygame.Rect(lx + 208,       by, 96, 32), "Remove",
                        (110, 60, 60), (150, 80, 80), font=app.font_sm)
    btn_close  = Button(pygame.Rect(box.right - 115, by, 95, 32), "Close",
                        (70, 80, 100), (95, 105, 130), font=app.font_sm)

    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    ov_hits: dict = {}          # page id → rect, rebuilt by the overview each frame

    while True:
        app._pump_net()      # D-M4-3: a modal is not a quiescent point, and must not stall the queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                return None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Pick a page from the list…
                if list_rect.collidepoint(event.pos):
                    idx = (event.pos[1] - list_rect.y - 4) // ROW_H
                    if 0 <= idx < len(dung.pages):
                        sel_id = dung.pages[idx].id
                        seed_steppers()
                # …or straight off the floor map.
                for pid, r in ov_hits.items():
                    if r.collidepoint(event.pos):
                        sel_id = pid
                        seed_steppers()
                        break
            sx.handle(event)
            sy.handle(event)
            sz.handle(event)
            if btn_close.clicked(event):
                return None
            p = dung.page_by_id(sel_id)
            if btn_entry.clicked(event) and p is not None:
                dung.entry_page_id = p.id
            if btn_goto.clicked(event) and p is not None:
                return p
            if btn_remove.clicked(event) and p is not None:
                dung.remove_page(p.id)
                nxt = dung.entry_page()
                sel_id = nxt.id if nxt else None
                seed_steppers()

        # Live-apply the steppers to the selected page so the overview shows the move
        # as it happens (the caller writes the manifest when the dialog closes).
        p = dung.page_by_id(sel_id)
        if p is not None:
            p.origin = [sx.value, sy.value, sz.value]

        # ── Render ─────────────────────────────────────────────────────
        app.screen.blit(overlay, (0, 0))
        pygame.draw.rect(app.screen, (35, 35, 50), box, border_radius=8)
        pygame.draw.rect(app.screen, (90, 90, 110), box, 1, border_radius=8)
        name = os.path.basename(app._dungeon_manifest_path or "dungeon.json")
        app.screen.blit(app.font_lg.render(f"Dungeon — {name}", True, (235, 235, 245)),
                         (lx, box.y + 16))

        # Page list: ★ = entry page, ● = the page loaded in the engine.
        pygame.draw.rect(app.screen, (24, 24, 36), list_rect, border_radius=6)
        pygame.draw.rect(app.screen, (90, 90, 115), list_rect, 1, border_radius=6)
        for i, pg in enumerate(dung.pages):
            ry = list_rect.y + 4 + i * ROW_H
            if ry + ROW_H > list_rect.bottom:
                break
            row = pygame.Rect(list_rect.x + 2, ry, list_rect.w - 4, ROW_H - 2)
            if pg.id == sel_id:
                pygame.draw.rect(app.screen, (55, 75, 120), row, border_radius=3)
            marks = ("★" if pg.id == dung.entry_page_id else " ") + \
                    ("●" if (app.dungeon_page and pg.id == app.dungeon_page.id) else " ")
            txt = f"{marks} {pg.id}  z={pg.z} ({pg.gx},{pg.gy}) {pg.cols}×{pg.rows}"
            app.screen.blit(app.font_sm.render(txt, True, (222, 222, 236)),
                             (row.x + 6, row.y + 3))

        # Floor map of the selected page's floor.
        floor_z = p.z if p is not None else 0
        ov_hits = draw_floor_overview(app, ov_rect, floor_z, sel_id)

        # Origin row.
        app.screen.blit(app.font_sm.render(f"Origin of '{sel_id or '—'}' (global cells)",
                                             True, (185, 185, 200)),
                         (ov_rect.x, st_y - 16))
        for label, st in (("X", sx), ("Y", sy), ("Z", sz)):
            app.screen.blit(app.font_sm.render(label, True, (185, 185, 200)),
                             (st.rect.x - 16, st.rect.y + 8))
            st.draw(app.screen)

        btn_entry.draw(app.screen)
        btn_goto.draw(app.screen)
        btn_remove.draw(app.screen)
        btn_close.draw(app.screen)
        pygame.display.flip()
        app.clock.tick(60)


def draw_floor_overview(app, rect: pygame.Rect, z: int, sel_id=None) -> dict:
    """Draw floor ``z``'s page layout (straight from the manifest origins) inside
    ``rect``: one box per page, scaled to fit, gold = the page loaded in the engine,
    white outline = ``sel_id``. Returns {page id: rect} for hit-testing."""
    pygame.draw.rect(app.screen, (24, 24, 36), rect, border_radius=6)
    pygame.draw.rect(app.screen, (90, 90, 115), rect, 1, border_radius=6)
    hits: dict = {}
    if app.dungeon is None:
        return hits
    # A page with no grid has no footprint — it can't be drawn on the global map.
    pages = [p for p in app.dungeon.pages_on_floor(z) if p.cols > 0 and p.rows > 0]
    if not pages:
        app.screen.blit(app.font_sm.render(f"No sized pages on floor {z}", True, (140, 140, 160)),
                         (rect.x + 12, rect.y + 12))
        return hits

    min_x = min(p.gx for p in pages)
    min_y = min(p.gy for p in pages)
    span_x = max(1, max(p.gx + p.cols for p in pages) - min_x)
    span_y = max(1, max(p.gy + p.rows for p in pages) - min_y)
    pad = 12
    s = min((rect.w - 2 * pad) / span_x, (rect.h - 2 * pad) / span_y)
    ox = rect.x + pad + ((rect.w - 2 * pad) - span_x * s) / 2
    oy = rect.y + pad + ((rect.h - 2 * pad) - span_y * s) / 2

    app.screen.blit(app.font_sm.render(f"Floor {z}", True, (170, 170, 190)),
                     (rect.x + 8, rect.y + 4))
    for p in pages:
        r = pygame.Rect(int(ox + (p.gx - min_x) * s), int(oy + (p.gy - min_y) * s),
                        max(6, int(p.cols * s)), max(6, int(p.rows * s)))
        active = app.dungeon_page is not None and p.id == app.dungeon_page.id
        pygame.draw.rect(app.screen, (86, 72, 42) if active else (44, 50, 66), r, border_radius=3)
        if p.id == sel_id:
            pygame.draw.rect(app.screen, (240, 240, 250), r, 2, border_radius=3)
        else:
            pygame.draw.rect(app.screen, (110, 110, 140), r, 1, border_radius=3)
        tag = ("★ " if p.id == app.dungeon.entry_page_id else "") + p.id
        t = app.font_sm.render(tag, True, (230, 230, 240))
        if t.get_width() <= r.w - 6 and t.get_height() <= r.h - 4:
            app.screen.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
        hits[p.id] = r
    return hits


def staircases_at(app, cell):
    """Every ``(staircase, end_index)`` whose end on the active page is ``cell`` (an
    rpg.Cell). A shared landing (D2) returns several."""
    if app.dungeon is None or app.dungeon_page is None:
        return []
    return app.dungeon.staircase_ends_at(app.dungeon_page.id, (cell.col, cell.row))


def staircase_option_label(app, st, end_index) -> str | None:
    """"Ascend Staircase 7 (K21) to larders", or None when it cannot be used."""
    direction = app.dungeon.staircase_direction(st, end_index)
    if direction is None:
        return None
    verb = "Ascend" if direction == "up" else "Descend"
    label = f" ({st.label})" if st.label else ""
    return f"{verb} {st.name}{label} to {st.other_end(end_index).page}"


def party_carry(app, actor_idx: int) -> list[int]:
    """The whole party on this page, for a group portal crossing: every party-faction
    token still in play, plus the acting creature if it is not one of them."""
    out = [i for i, pt in enumerate(app.bm.placed_agents)
           if pt.faction == PC_FACTION and not pt.removed_from_play]
    if actor_idx is not None and actor_idx >= 0 and actor_idx not in out:
        out.append(actor_idx)
    return out


def use_staircase(app, sid: int, end_index: int, actor_idx: int, party: bool = False):
    """Carry the acting creature (``party``: the whole party, ``_party_carry``) from end
    ``end_index`` of staircase ``sid`` to its other end, through _switch_to_page (which
    refuses in combat, D3). Refused with a flash when the end is not on this page or
    the staircase is unfinished or broken."""
    if app.dungeon is None or app.dungeon_page is None:
        app._flash_status("Staircases need a dungeon manifest (open a .dungeon.json).")
        return False
    st = app.dungeon.staircase_by_id(sid)
    if (st is None or end_index not in (0, 1) or end_index >= len(st.ends)
            or st.ends[end_index].page != app.dungeon_page.id):
        return False
    direction = app.dungeon.staircase_direction(st, end_index)
    if direction is None:
        app._flash_status(f"{st.name} is unfinished; it leads nowhere yet.")
        return False
    other = st.other_end(end_index)
    page = app.dungeon.page_by_id(other.page)
    if party:
        carry = party_carry(app, actor_idx) or None
    else:
        carry = [actor_idx] if actor_idx is not None and actor_idx >= 0 else None
    if switch_to_page(app, page, drop_cell=other.cell, carry=carry):
        verb = "Ascended" if direction == "up" else "Descended"
        who = "The party " + verb.lower() if party else verb
        app._flash_status(f"{who} {st.name} to floor {page.z}: {page.id}")
        return True
    return False


def staircases_snapshot(app):
    """The manifest's staircases as plain data, to tell whether an edit changed them."""
    if app.dungeon is None:
        return None
    return ([st.to_dict() for st in app.dungeon.staircases],
            app.dungeon.next_staircase_id)


# ── The Staircases… list (Dungeon Configuration) ─────────────────────────
def staircase_summary(app, st) -> str:
    """"Staircase 7 (K21): M (2, 2) floor 0 ↔ U (6, 5) floor 1", or "…, unfinished"."""
    ends = []
    for e in st.ends:
        p = app.dungeon.page_by_id(e.page)
        ends.append(f"{e.page} {tuple(e.cell)}" + (f" floor {p.z}" if p else " (missing)"))
    head = st.name + (f" ({st.label})" if st.label else "")
    if not st.finished:
        return f"{head}: {ends[0]}, unfinished"
    broken = "" if app.dungeon.staircase_direction(st, 0) else ", broken"
    return f"{head}: {ends[0]} ↔ {ends[1]}{broken}"


def staircase_goto(app, sid: int, end_index: int) -> bool:
    """Show end ``end_index`` of staircase ``sid``: switch to its page (refused in
    combat, like any page change) and pan its cell to the middle of the map view."""
    st = app.dungeon.staircase_by_id(sid) if app.dungeon is not None else None
    if st is None or not 0 <= end_index < len(st.ends):
        return False
    end = st.ends[end_index]
    page = app.dungeon.page_by_id(end.page)
    if page is None:
        app._flash_status(f"{st.name}: page '{end.page}' is gone.")
        return False
    if app.dungeon_page is None or app.dungeon_page.id != page.id:
        if not switch_to_page(app, page):
            return False
    c, r = end.cell
    x0, y0 = app._cell_to_screen(c, r)
    x1, y1 = app._cell_to_screen(c + 1, r + 1)
    app.pan_x += app._panel_x() // 2 - (x0 + x1) // 2
    app.pan_y += app.screen.get_height() // 2 - (y0 + y1) // 2
    app._flash_status(f"{st.name}, end {'AB'[end_index]}: {page.id} {tuple(end.cell)}, "
                       f"floor {page.z}")
    return True


def staircase_set_text(app, sid: int, field: str, text: str) -> bool:
    """Rename (``field`` "name") or relabel ("label") a staircase and write the
    manifest. A blank name falls back to "Staircase {id}"; a blank label clears it."""
    st = app.dungeon.staircase_by_id(sid) if app.dungeon is not None else None
    if st is None or field not in ("name", "label"):
        return False
    text = (text or "").strip()
    if field == "name" and not text:
        text = f"Staircase {st.id}"
    setattr(st, field, text)
    return dungeon_save_manifest(app)


def staircase_prompt(app, sid: int, field: str):
    st = app.dungeon.staircase_by_id(sid) if app.dungeon is not None else None
    if st is None:
        return
    title = f"Rename {st.name}" if field == "name" else f"Label for {st.name} (empty clears)"
    app.name_prompt.show(getattr(st, field),
                          lambda text: staircase_set_text(app, sid, field, text),
                          title=title, allow_empty=(field == "label"))


def staircase_delete(app, sid: int) -> bool:
    """Delete a staircase and both its ends, and write the manifest."""
    st = app.dungeon.staircase_by_id(sid) if app.dungeon is not None else None
    if st is None:
        return False
    app.dungeon.remove_staircase(sid)
    if dungeon_save_manifest(app):
        app._flash_status(f"Deleted {st.name} (both ends).")
    return True


def page_png_path(app, page: MapPage) -> str:
    """A dungeon page's PNG, resolved like _switch_to_page does."""
    png = page.png
    return png if (not png or os.path.isabs(png)) else os.path.join(dungeon_dir(app), png)


def page_terrain_path(app, page: MapPage) -> str:
    """The ``_terrain.json`` a dungeon page loads, resolved like _switch_to_page does."""
    enc = page.encounter_base
    if not os.path.isabs(enc):
        enc = os.path.join(dungeon_dir(app), enc)
    d, base = app._sidecar_base(enc)
    return os.path.join(d, base + "_terrain.json")


def send_pages(app) -> list:
    """The dungeon pages a creature can be sent to: every page but the one showing."""
    if app.dungeon is None or app.dungeon_page is None:
        return []
    return [p for p in app.dungeon.pages if p.id != app.dungeon_page.id]


def send_to_page(app, idx: int, page) -> bool:
    """The DM's "Send to floor…": move creature idx to another page of the dungeon
    without following it. It lands at the same global (X, Y) on that page when the page
    covers it (else the page's top-left), off other creatures; a wall there is resolved
    when the page loads (the record's land_near flag → _open_cell_near). Out of combat it leaves this page outright; in
    combat it is tombstoned here, like a cleared mob, and its turn passes if it was acting.
    Phasing through ceilings and floors (Strahd's lair) is this plus the DM's call."""
    if not (0 <= idx < len(app.bm.placed_agents)) or app.dungeon_page is None:
        return False
    pt = app.bm.placed_agents[idx]
    name, size = pt.name, pt.size
    X, Y, _ = app.dungeon_page.local_to_global(pt.origin.col, pt.origin.row)
    land = page.global_to_local(X, Y, page.z) or (0, 0)
    recs = read_agent_records(app, [idx])
    if not recs:
        app._flash_status(f"Could not send {name}: it could not be saved.")
        return False
    try:
        doc = app.store.creatures(page) or {"agents": [], "map_items": []}
    except (ValueError, OSError):
        doc = {"agents": [], "map_items": []}
    agents = doc.setdefault("agents", [])
    taken = set()
    for a in agents:
        n = int(a.get("size", 1) or 1)
        taken |= {(int(a["col"]) + dc, int(a["row"]) + dr) for dc in range(n) for dr in range(n)}
    cols = page.cols or (land[0] + size)
    rows = page.rows or (land[1] + size)
    spot = land
    for ring in range(0, max(cols, rows) + 1):
        cands = [(c, r) for r in range(land[1] - ring, land[1] + ring + 1)
                 for c in range(land[0] - ring, land[0] + ring + 1)
                 if max(abs(c - land[0]), abs(r - land[1])) == ring
                 and 0 <= c <= cols - size and 0 <= r <= rows - size
                 and not any((c + dc, r + dr) in taken
                             for dc in range(size) for dr in range(size))]
        if cands:
            spot = cands[0]
            break
    rec = recs[0]
    rec["col"], rec["row"] = int(spot[0]), int(spot[1])
    rec["land_near"] = True          # _load_agents moves it off a wall on that page
    agents.append(rec)
    app.store.write_creatures(doc, page)

    if app.combat_active:
        is_cur = idx == app._current_agent_idx()
        app._drop_concentration_for_agent(idx)
        app.bm.set_agent_removed_from_play(idx, True)
        if app.tracker_mode and app.tracker.remove(idx):
            app._mirror_tracker()
        if app.selected_idx == idx:
            app.selected_idx = -1
        app._combat_log_add(f"{name} leaves for floor {page.z} ({page.id}).")
        app._mark_fog_dirty()
        if is_cur and not app.tracker_mode:
            app._advance_turn()
        app._flush_combat_log()
    else:
        app._delete_placed_agent(idx)
        app._save_agents()
    app._flash_status(f"{name} sent to floor {page.z} ({page.id}).")
    return True


def panel_has_floor_nav(app) -> bool:
    """The Floor-nav block only appears for a live multi-map dungeon in the setup
    panel (floors aren't changed mid-combat)."""
    return (app.dungeon is not None and app.dungeon_page is not None
            and not app.combat_active)


def floor_nav_height(app) -> int:
    """Total pixel height of the Floor-nav block: header + two button rows."""
    return (app._FLOOR_NAV_HDR + app._FLOOR_NAV_VGAP
            + app._FLOOR_NAV_BH + app._FLOOR_NAV_VGAP + app._FLOOR_NAV_BH)


def draw_panel_floor_nav(app, px, lx, W):
    """Render the Floor-nav block inside the config panel at the cached scroll-adjusted
    top. Row 1 pages between abutting maps (West/North/South/East); row 2 changes floors
    (Floor ±). Inert buttons (no neighbour / no floor) are greyed. Clickable rects are
    cached in ``app._dungeon_nav_rects`` for the shared event handler."""
    top = app._panel_floor_nav_top
    if top is None or app.dungeon_page is None:
        return
    page   = app.dungeon_page
    floors = app.dungeon.floors()

    # Header
    lbl = app.font_sm.render(f"Floor {page.z} — {page.id}", True, (222, 222, 236))
    app.screen.blit(lbl, (lx, top))

    gap = 4
    bh  = app._FLOOR_NAV_BH
    row1_y = top + app._FLOOR_NAV_HDR + app._FLOOR_NAV_VGAP
    row2_y = row1_y + bh + app._FLOOR_NAV_VGAP

    def button(text, key, enabled, x, y, w):
        rect = pygame.Rect(x, y, w, bh)
        fill = (58, 82, 116) if enabled else (44, 46, 56)
        tcol = (236, 236, 246) if enabled else (108, 108, 120)
        pygame.draw.rect(app.screen, fill, rect, border_radius=5)
        pygame.draw.rect(app.screen, (102, 102, 128), rect, 1, border_radius=5)
        t = app.font_sm.render(text, True, tcol)
        app.screen.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))
        if enabled:
            app._dungeon_nav_rects[key] = rect

    # Row 1: paging (4 columns)
    row1 = [
        ("West",  "left",  app.dungeon.neighbor(page, "left")  is not None),
        ("North", "up",    app.dungeon.neighbor(page, "up")    is not None),
        ("South", "down",  app.dungeon.neighbor(page, "down")  is not None),
        ("East",  "right", app.dungeon.neighbor(page, "right") is not None),
    ]
    bw4 = (W - 3 * gap) // 4
    for i, (text, key, enabled) in enumerate(row1):
        button(text, key, enabled, lx + i * (bw4 + gap), row1_y, bw4)

    # Row 2: floors (2 columns)
    bw2 = (W - gap) // 2
    button("Floor +", "floor_up",   (page.z + 1) in floors, lx,               row2_y, bw2)
    button("Floor -", "floor_down", (page.z - 1) in floors, lx + bw2 + gap,   row2_y, bw2)
