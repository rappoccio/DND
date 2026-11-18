#!/usr/bin/env python3
"""Dungeon-page open/navigate structural golden (APP_REFACTOR_PLAN.md A0).

The oracle for A1's "Dungeon Pages & Navigation" cut. A headless App opens a fixture
campaign dungeon through the DM's own entry point (`_on_open_dungeon_chosen` → the
version 2 `_open_campaign_dungeon` path), then pages, changes floors, takes a staircase
and closes the overview, and after every step dumps:

  · `state` — the page on show, its origin and floor, the engine map's grid and global
    placement, view zoom/pan, the flash status, the run's current map, and every token
    (name, cell, faction) on the live board;
  · `store` — every page's creatures as the run has them saved (name and cell);
  · `nav`   — the Floor-nav block's draw calls, recorded while the real `_draw_panel`
    runs (so it also proves the panel still calls it), plus the hit rects it cached;
  · `overview` at the checkpoints that show it — `_draw_floor_overview`'s draw calls
    and the hit rects it returns.

Nothing here reads a temp-dir path into the golden; every path is reported relative
to the campaign folder.

The fixture (every map 10 × 8 cells, open floor):

    floor  0:  hall  (0,0)   annex (10,0)     — abut, so East/West page between them
    floor -1:  cellar (0,0)                   — under hall
    staircase 0: hall (2,2)  ↔  cellar (6,5)

Regenerate after an INTENTIONAL change (inspect the diff first!):
    python test_dungeon_pages.py --update
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

import main as app_main
import save_layout as sl
from main import App
from dungeon import Dungeon, MapPage
from draw_capture import DrawRecorder, FakeClock, golden_main

SEED = 20261118
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_dungeon_pages.golden.txt")

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
MAPS = (("hall", [0, 0, 0]), ("annex", [COLS, 0, 0]), ("cellar", [0, 0, -1]))
PC_TEAM = 2      # constants.PC_FACTION
FOE_TEAM = 1


# ─────────────────────────────────────────────────────────────────────────────
#  Fixture
# ─────────────────────────────────────────────────────────────────────────────

def _png(path, shade):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill(shade)
    for x in range(0, COLS * CELL + 1, CELL):                # grid lines for analyze_grid
        pygame.draw.line(surf, (60, 60, 60), (x, 0), (x, ROWS * CELL), 1)
    for y in range(0, ROWS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (0, y), (COLS * CELL, y), 1)
    pygame.image.save(surf, path)


def _campaign(tmp):
    camp = sl.Campaign.create(os.path.join(tmp, "Golden Campaign"))
    for i, (m, _) in enumerate(MAPS):
        d = camp.library_map_dir(m)
        os.makedirs(d)
        _png(os.path.join(d, m + ".png"), (200 - 20 * i, 195, 185))
        with open(os.path.join(d, sl.MAP_FILE), "w") as f:
            json.dump({"regions": [], "walls_enabled": False, "manual_grid": GRID,
                       "doors": []}, f)
    dl = camp.dungeon("keep")
    os.makedirs(dl.root)
    pages = [MapPage(m, "", "", origin, COLS, ROWS) for m, origin in MAPS]
    d = Dungeon(pages=pages, entry_page_id="hall", version=2)
    st = d.new_staircase("hall", (2, 2), name="Cellar Stair")
    d.finish_staircase(st.id, "cellar", (6, 5))
    d.save(dl.manifest_path)
    return camp, dl


def _place(app, name, col, row, faction):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = name, col, row, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    i = _idx(app, name)
    app.bm.set_agent_faction(i, faction)
    return i


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    return -1


# ─────────────────────────────────────────────────────────────────────────────
#  Capture
# ─────────────────────────────────────────────────────────────────────────────

def _r(rect):
    return f"{rect.x},{rect.y},{rect.w},{rect.h}"


def _state(app, clock):
    out = []
    page = app.dungeon_page
    if page is None:
        out.append("state | page=None")
    else:
        out.append(f"state | page={page.id} z={page.z} origin={list(page.origin)} "
                   f"size={page.cols}x{page.rows}")
    bm = app.bm
    out.append(f"state | grid={bm.grid_cols}x{bm.grid_rows} "
               f"bm_origin={bm.origin_col},{bm.origin_row},{bm.z_level} "
               f"cell_px={bm.cell_pixel_size}")
    out.append(f"state | map_rect={_r(app.map_rect)} zoom={app.view_zoom:.3f} "
               f"pan={app.pan_x},{app.pan_y} map_scale={app.map_scale:.4f}")
    msg = app._status_msg if clock.ticks < app._status_msg_until else ""
    out.append(f"state | status={msg!r}")
    run = getattr(app.store, "run", None)
    cur = run.get("current_map") if isinstance(run, dict) else None
    out.append(f"state | dungeon={'yes' if app.dungeon is not None else 'no'} "
               f"store={type(app.store).__name__} run.current_map={cur}")
    for pt in sorted(app.bm.placed_agents, key=lambda p: p.name):
        out.append(f"state | token {pt.name} @ {pt.origin.col},{pt.origin.row} "
                   f"faction={pt.faction}")
    return out


def _store(app):
    out = []
    if app.dungeon is None:
        return out
    for page in app.dungeon.pages:
        doc = app.store.creatures(page) or {}
        recs = sorted(doc.get("agents", []), key=lambda a: a.get("name", ""))
        names = ", ".join(f"{a.get('name')}@{a.get('col')},{a.get('row')}" for a in recs)
        out.append(f"store | {page.id}: [{names}]")
    return out


def _nav(app):
    """Run the real `_draw_panel`, recording only what its Floor-nav block draws."""
    real = app._draw_panel_floor_nav
    with DrawRecorder(app) as rec:
        rec.section("off")

        def nav(*a, **k):
            rec.section("nav")
            try:
                return real(*a, **k)
            finally:
                rec.section("off")
        app._draw_panel_floor_nav = nav
        try:
            app._draw_panel()
        finally:
            del app._draw_panel_floor_nav
    out = [ln for ln in rec.lines if ln.startswith("nav | ")]
    if not out:
        out.append("nav | (not drawn)")
    for key in sorted(app._dungeon_nav_rects):
        out.append(f"nav | hit {key} {_r(app._dungeon_nav_rects[key])}")
    return out


def _overview(app, z):
    rect = pygame.Rect(40, 40, 400, 240)
    with DrawRecorder(app) as rec:
        rec.section(f"overview z={z}")
        hits = app._draw_floor_overview(rect, z)
    out = list(rec.lines)
    for pid in sorted(hits):
        out.append(f"overview z={z} | hit {pid} {_r(hits[pid])}")
    return out


def capture(app, clock, title, overview=False):
    out = [f"=== {title} ==="]
    out += _state(app, clock)
    out += _store(app)
    out += _nav(app)
    if overview and app.dungeon is not None:
        for z in app.dungeon.floors():
            out += _overview(app, z)
    out.append("")
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Checkpoints
# ─────────────────────────────────────────────────────────────────────────────

def build_output():
    pygame.init()
    clock = FakeClock()
    clock.install()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            return _run(tmp, clock)
    finally:
        clock.uninstall()


def _step(clock):
    """Each step starts on a fresh second, so one step's flash never reads as the next's."""
    clock.ticks += 1000


def _run(tmp, clock):
    camp, dl = _campaign(tmp)
    png, manifest = app_main.resolve_start_path(dl.manifest_path)
    app = App(png, seed=SEED)
    out = []

    _step(clock)
    app._on_open_dungeon_chosen(manifest)
    out += capture(app, clock, "01 open the campaign dungeon — entry map hall",
                   overview=True)

    _step(clock)
    _place(app, "Aria", 2, 3, PC_TEAM)
    _place(app, "Skarn", 7, 6, FOE_TEAM)
    app.bm.set_agent_faction(_idx(app, "Aria"), PC_TEAM)    # re-applying configs reset it
    out += capture(app, clock, "02 Aria and Skarn placed on hall (not yet saved)")

    _step(clock)
    app._page_step("right")
    out += capture(app, clock, "03 East — page to annex (hall saved on the way out)")

    _step(clock)
    _place(app, "Wisp", 4, 4, FOE_TEAM)
    app._page_step("up")
    out += capture(app, clock, "04 North from annex — no map there, refused")

    _step(clock)
    app._page_step("left")
    out += capture(app, clock, "05 West — back to hall, its tokens reloaded")

    _step(clock)
    app._zoom_by(app.ZOOM_BTN_STEP)
    app._floor_step(-1)
    out += capture(app, clock, "06 Floor - — down to cellar, zoom kept", overview=True)

    _step(clock)
    app._floor_step(-1)
    out += capture(app, clock, "07 Floor - from cellar — no floor there, refused")

    _step(clock)
    app._floor_step(+1)
    out += capture(app, clock, "08 Floor + — back up to hall")

    _step(clock)
    st = app.dungeon.staircases[0]
    app._use_staircase(st.id, 0, _idx(app, "Aria"))
    out += capture(app, clock, "09 Aria descends the Cellar Stair, carried to cellar")

    _step(clock)
    app._start_combat()
    app.combat.stop_recording()
    app._floor_step(+1)
    out += capture(app, clock, "10 in combat — Floor + refused, Floor-nav hidden")

    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(golden_main(build_output, GOLDEN_PATH, "test_dungeon_pages",
                         "dungeon-page checkpoints"))
