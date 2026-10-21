#!/usr/bin/env python3
"""
Wall detection for drawn maps (plans/DUNGEON_LEVELS_PLAN.md, Phase 2B).

A drawn map puts thin walls on the grid lines. The dark-fraction mode reads them as edge
walls (and, at a low fraction, as wall cells), a flood from a seed on the paper outside
blocks everything it reaches, the DM's edge overrides close or open single edges, and
Floor regions reopen cells after all of that. A page with no "detection" block detects
exactly as before (C3).
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

from main import App

E, S = rpg.EdgeSide.East, rpg.EdgeSide.South
C = rpg.Cell

# A 10×8 page of 30 px cells. The building's outer wall is a 4 px grey-70 stroke centred on the
# grid lines round cols 2..7, rows 2..5, so the inside is 6×4 cells.
CELL = 30
COLS, ROWS = 10, 8
X0, X1, Y0, Y1 = 2, 8, 2, 6          # building spans grid lines X0..X1, Y0..Y1
INSIDE = {(c, r) for c in range(X0, X1) for r in range(Y0, Y1)}
WALL_GREY = (70, 70, 70)
PAPER = (200, 195, 185)


def _png(tmp, gap=False, name="drawn.png"):
    """The test page. With ``gap``, the west wall's stroke is missing beside row 3."""
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill(PAPER)
    for x in (X0 * CELL, X1 * CELL):
        for r in range(Y0, Y1):
            if gap and x == X0 * CELL and r == 3:
                continue
            surf.fill(WALL_GREY, pygame.Rect(x - 2, r * CELL, 4, CELL))
    for y in (Y0 * CELL, Y1 * CELL):
        surf.fill(WALL_GREY, pygame.Rect(X0 * CELL - 2, y - 2, (X1 - X0) * CELL + 4, 4))
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _outer_edges():
    edges = set()
    for r in range(Y0, Y1):
        edges.add((X0 - 1, r, E))
        edges.add((X1 - 1, r, E))
    for c in range(X0, X1):
        edges.add((c, Y0 - 1, S))
        edges.add((c, Y1 - 1, S))
    return edges


def _bm(png):
    bm = rpg.BattleMap(png)
    bm.set_uniform_grid(CELL, 0, 0)
    assert (bm.grid_cols, bm.grid_rows) == (COLS, ROWS)
    return bm


def _drawn(bm, seeds=(), fraction=0.6, add=(), remove=()):
    p = bm.params
    p.mode = rpg.DetectionMode.DarkFraction
    p.dark_level = 100
    p.dark_fraction = fraction
    p.edge_walls = True
    p.edge_fraction = 0.3
    p.edge_halfwidth_px = 4
    p.outside_seeds = [C(c, r) for c, r in seeds]
    p.edge_add = [rpg.Edge(C(c, r), s) for c, r, s in add]
    p.edge_remove = [rpg.Edge(C(c, r), s) for c, r, s in remove]
    bm.clear_walls()
    bm.detect_walls()


def _blocked(bm):
    return {(c.col, c.row) for c in bm.disallowed_cells}


def _edges(bm):
    return {(e.cell.col, e.cell.row, e.side) for e in bm.edge_walls}


# ── Engine ───────────────────────────────────────────────────────────────────
def test_mean_mode_misses_thin_walls():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        bm.clear_walls()
        bm.detect_walls()
        assert bm.params.mode == rpg.DetectionMode.Mean, "the default is today's detector"
        assert _blocked(bm) == set() and _edges(bm) == set()
    print("✅ test_mean_mode_misses_thin_walls passed")


def test_low_fraction_catches_thin_walls_as_cells():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm, fraction=0.06)
        ring = {(c, r) for (c, r) in INSIDE if c in (X0, X1 - 1) or r in (Y0, Y1 - 1)}
        assert ring <= _blocked(bm), "a stroke on the line darkens the cells beside it"
        assert (4, 3) not in _blocked(bm)
    print("✅ test_low_fraction_catches_thin_walls_as_cells passed")


def test_edges_follow_the_drawn_walls():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm)
        assert _blocked(bm) == set(), "at 0.6 a 4 px stroke blocks no whole cell"
        assert _edges(bm) == _outer_edges()
        # The rooms keep their full interior and the walls block a walk.
        reach = {(c.col, c.row) for c in bm.reachable_cells(C(4, 3), 1, 200, rpg.MovementType.Walk)}
        assert reach == INSIDE
    print("✅ test_edges_follow_the_drawn_walls passed")


def test_outside_seed_blocks_what_it_reaches():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm, seeds=[(0, 0)])
        everything = {(c, r) for c in range(COLS) for r in range(ROWS)}
        assert _blocked(bm) == everything - INSIDE
        # An inside seed blocks the inside instead.
        _drawn(bm, seeds=[(4, 3)])
        assert _blocked(bm) == INSIDE
        # No seed, no flood.
        _drawn(bm, seeds=[])
        assert _blocked(bm) == set()
    print("✅ test_outside_seed_blocks_what_it_reaches passed")


def test_a_seed_on_a_wall_cell_is_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm, seeds=[(X0, Y0)], fraction=0.06)
        assert (X0 + 2, Y0 + 2) not in _blocked(bm), "the seed sat on a wall cell; no flood"
        assert (0, 0) not in _blocked(bm)
    print("✅ test_a_seed_on_a_wall_cell_is_ignored passed")


def test_edge_overrides_close_a_leak_and_open_a_wall():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp, gap=True))
        _drawn(bm, seeds=[(0, 0)])
        assert (4, 3) in _blocked(bm), "the flood gets in through the gap"
        _drawn(bm, seeds=[(0, 0)], add=[(X0 - 1, 3, E)])
        assert not (_blocked(bm) & INSIDE), "the added edge closes the gap"
        assert (X0 - 1, 3, E) in _edges(bm)
        # Removing a detected edge reopens it, and the flood follows.
        bm2 = _bm(_png(tmp))
        _drawn(bm2, seeds=[(0, 0)], remove=[(X1 - 1, 4, E)])
        assert (X1 - 1, 4, E) not in _edges(bm2)
        assert INSIDE <= _blocked(bm2)
    print("✅ test_edge_overrides_close_a_leak_and_open_a_wall passed")


def test_flood_ignores_door_state():
    """An open edge door on the outer wall doesn't leak the flood: doors block it whatever their state."""
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm)
        bm.add_edge_door([rpg.Edge(C(X0 - 1, 3), E)], True)
        assert not bm.is_edge_wall(C(X0 - 1, 3), E), "the door is open"
        bm.params.outside_seeds = [C(0, 0)]
        bm.clear_walls()
        bm.detect_walls()
        assert not (_blocked(bm) & INSIDE)
    print("✅ test_flood_ignores_door_state passed")


def test_a_door_in_a_gap_stops_the_flood():
    """A doorway is a gap in the drawn wall; the door in it, open or shut, plugs the flood."""
    with tempfile.TemporaryDirectory() as tmp:
        png = _png(tmp, gap=True)
        for is_open in (False, True):
            bm = _bm(png)
            bm.add_edge_door([rpg.Edge(C(X0 - 1, 3), E)], is_open)
            _drawn(bm, seeds=[(0, 0)])
            assert not (_blocked(bm) & INSIDE), f"edge door (open={is_open}) leaked the flood"
            assert bm.edge_between(C(X0 - 1, 3), C(X0, 3)) != is_open
            bm = _bm(png)
            bm.add_door([C(X0 - 1, 3)], is_open)
            _drawn(bm, seeds=[(0, 0)])
            assert not (_blocked(bm) & INSIDE), f"cell door (open={is_open}) leaked the flood"
            assert (X0 - 1, 3) not in _blocked(bm), "the flood doesn't take the doorway"
            assert bm.is_blocked(C(X0 - 1, 3), 1) != is_open, "open, the doorway is walkable"
    print("✅ test_a_door_in_a_gap_stops_the_flood passed")


def test_allow_cell_reopens_a_detected_cell():
    with tempfile.TemporaryDirectory() as tmp:
        bm = _bm(_png(tmp))
        _drawn(bm, seeds=[(0, 0)])
        assert (0, 0) in _blocked(bm)
        bm.allow_cell(C(0, 0))
        assert (0, 0) not in _blocked(bm)
        assert not bm.is_blocked(C(0, 0), 1)
    print("✅ test_allow_cell_reopens_a_detected_cell passed")


# ── The page's terrain file ──────────────────────────────────────────────────
DETECTION = {"mode": "dark_fraction", "dark_level": 100, "dark_fraction": 0.6,
             "edge_walls": True, "edge_fraction": 0.3, "edge_halfwidth_px": 4,
             "outside_seeds": [[0, 0]]}


def _app(tmp, doc=None, gap=False):
    png = _png(tmp, gap=gap)
    terrain = os.path.join(tmp, "drawn_terrain.json")
    base = {"regions": [], "walls_enabled": True,
            "manual_grid": {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}}
    base.update(doc or {})
    with open(terrain, "w") as f:
        json.dump(base, f)
    app = App(png, seed=1)
    app._load_terrain(terrain)
    assert app.base_map_scale == 1.0, "regions below are in image px"
    return app, terrain


def _floor(c0, r0, c1, r1):
    """A Floor region covering cells c0..c1 × r0..r1 (fit-scale px = image px here)."""
    return {"type": "Floor", "x": c0 * CELL, "y": r0 * CELL,
            "width": (c1 - c0 + 1) * CELL, "height": (r1 - r0 + 1) * CELL}


def test_no_detection_block_detects_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp)
        ref = _bm(os.path.join(tmp, "drawn.png"))
        ref.clear_walls()
        ref.detect_walls()
        assert app.bm.params.mode == rpg.DetectionMode.Mean
        assert _blocked(app.bm) == _blocked(ref) and _edges(app.bm) == _edges(ref)
        app._save_terrain()
        with open(terrain) as f:
            doc = json.load(f)
        assert "detection" not in doc and "edge_overrides" not in doc
    print("✅ test_no_detection_block_detects_as_before passed")


def test_detection_block_applies_on_load():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp, {"detection": DETECTION})
        everything = {(c, r) for c in range(COLS) for r in range(ROWS)}
        assert _blocked(app.bm) == everything - INSIDE
        assert _edges(app.bm) == _outer_edges()
    print("✅ test_detection_block_applies_on_load passed")


def test_walls_off_keeps_the_block_unapplied():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp, {"detection": DETECTION, "walls_enabled": False})
        assert _blocked(app.bm) == set() and _edges(app.bm) == set()
        app._toggle_walls()
        assert app._walls_enabled and _edges(app.bm) == _outer_edges()
        with open(terrain) as f:
            assert json.load(f)["detection"] == DETECTION
    print("✅ test_walls_off_keeps_the_block_unapplied passed")


def test_floor_regions_survive_save_reload_and_redetect():
    with tempfile.TemporaryDirectory() as tmp:
        # Floor over outside cells (0,0)-(1,1), and over the building's west half including
        # the wall line between cols 1 and 2.
        regions = [_floor(0, 0, 1, 1), _floor(1, 3, 3, 3)]
        app, terrain = _app(tmp, {"detection": DETECTION, "regions": regions})

        def check():
            b = _blocked(app.bm)
            assert not ({(0, 0), (1, 0), (0, 1), (1, 1), (1, 3)} & b), "Floor cells stay open"
            assert (2, 0) in b, "the flood still blocks the rest of the outside"
            assert (X0 - 1, 3, E) not in _edges(app.bm), "an edge inside a Floor region goes"
            assert (X0 - 1, 2, E) in _edges(app.bm), "edges outside it stay"
            assert (0, 1, S) not in _edges(app.bm)

        check()
        app._save_terrain()
        app._load_terrain(terrain)
        check()
        app._toggle_walls()
        app._toggle_walls()
        check()
        assert app.bm.get_terrain_type(C(0, 0)) == rpg.TerrainType.Standard, \
            "Floor paints no terrain"
    print("✅ test_floor_regions_survive_save_reload_and_redetect passed")


def test_floor_region_does_not_leak_the_flood_inside():
    """Floor comes after the flood, so clearing an outer-wall cell can't flood the rooms."""
    with tempfile.TemporaryDirectory() as tmp:
        det = dict(DETECTION, dark_fraction=0.06)
        app, _ = _app(tmp, {"detection": det, "regions": [_floor(X0, 3, X0, 3)]})
        b = _blocked(app.bm)
        assert (X0, 3) not in b
        assert (X0 + 2, 3) not in b and (X0 + 1, 3) not in b
    print("✅ test_floor_region_does_not_leak_the_flood_inside passed")


def test_edge_overrides_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        ov = {"add": [[X0 - 1, 3, "E"]], "remove": []}
        app, terrain = _app(tmp, {"detection": DETECTION, "edge_overrides": ov}, gap=True)
        assert not (_blocked(app.bm) & INSIDE)
        app._save_terrain()
        with open(terrain) as f:
            assert json.load(f)["edge_overrides"] == ov
        app._load_terrain(terrain)
        assert not (_blocked(app.bm) & INSIDE)
    print("✅ test_edge_overrides_round_trip passed")


def test_set_grid_clears_seeds_and_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        ov = {"add": [[X0 - 1, 3, "E"]], "remove": []}
        app, terrain = _app(tmp, {"detection": DETECTION, "edge_overrides": ov})
        app._pending_grid_box = (0, 0, 2 * CELL, 2 * CELL)
        app._on_grid_span((2, 2, 5))
        with open(terrain) as f:
            doc = json.load(f)
        assert doc["detection"]["outside_seeds"] == []
        assert doc["detection"]["mode"] == "dark_fraction", "the rest of the block is kept"
        assert "edge_overrides" not in doc
    print("✅ test_set_grid_clears_seeds_and_overrides passed")


# ── Terrain… → Wall Detection… ───────────────────────────────────────────────
def _menu_items(app):
    from menus import dm
    seen = {}
    app._ask_dm = lambda kind, title, items, **kw: seen.setdefault("items", items)
    dm.show_terrain_menu(app)
    return [label for label, _fn in seen["items"]]


def _click(app, pos):
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)
    dlg = app._wall_detect_dialog
    if not dlg.handle(ev):
        app._handle_map_view_event(ev)


def _open_dialog(app):
    app._open_wall_detection()
    dlg = app._wall_detect_dialog
    assert dlg.visible
    dlg.draw(app.screen)            # past the swallowed opening click
    return dlg


def _chip(dlg, key, val):
    return next(r.center for r, k, v in dlg._chips if k == key and v == val)


def _cell_center(app, c, r):
    x, y = app._cell_to_screen(c, r)
    half = int(CELL * app.map_scale) // 2
    return (x + half, y + half)


def test_menu_offers_wall_detection_only_with_walls_on():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp)
        assert "Wall Detection…" in _menu_items(app)
        app._toggle_walls()
        assert not app._walls_enabled
        assert "Wall Detection…" not in _menu_items(app)
    print("✅ test_menu_offers_wall_detection_only_with_walls_on passed")


def test_dialog_redetects_live_and_ok_saves_the_block():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp)
        dlg = _open_dialog(app)
        assert dlg.settings["mode"] == "mean" and _edges(app.bm) == set()
        _click(app, _chip(dlg, "mode", "dark_fraction"))
        assert _edges(app.bm) == _outer_edges(), "switching to Drawn re-detects at once"
        _click(app, _cell_center(app, 0, 0))
        assert dlg.settings["outside_seeds"] == [[0, 0]]
        everything = {(c, r) for c in range(COLS) for r in range(ROWS)}
        assert _blocked(app.bm) == everything - INSIDE, "the seed floods the outside at once"
        _click(app, _cell_center(app, 0, 0))
        assert dlg.settings["outside_seeds"] == [] and _blocked(app.bm) == set(), "a second click removes it"
        _click(app, _cell_center(app, 0, 0))
        _click(app, dlg._ok_rect.center)
        assert not dlg.visible
        with open(terrain) as f:
            det = json.load(f)["detection"]
        assert det["mode"] == "dark_fraction" and det["outside_seeds"] == [[0, 0]]
        assert det["dark_fraction"] == 0.6 and det["edge_fraction"] == 0.3
        app._load_terrain(terrain)
        assert _blocked(app.bm) == everything - INSIDE
    print("✅ test_dialog_redetects_live_and_ok_saves_the_block passed")


def test_dialog_cancel_restores_the_page():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp, {"detection": DETECTION})
        before = (_blocked(app.bm), _edges(app.bm))
        dlg = _open_dialog(app)
        _click(app, _chip(dlg, "edge_walls", False))
        assert _edges(app.bm) == set()
        _click(app, dlg._cancel_rect.center)
        assert (_blocked(app.bm), _edges(app.bm)) == before
        assert app._detection == DETECTION
    print("✅ test_dialog_cancel_restores_the_page passed")


def test_ok_without_switching_on_leaves_the_file_alone():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp)
        dlg = _open_dialog(app)
        _click(app, dlg._ok_rect.center)
        with open(terrain) as f:
            assert "detection" not in json.load(f)
    print("✅ test_ok_without_switching_on_leaves_the_file_alone passed")


def test_stepper_changes_a_level():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp, {"detection": DETECTION})
        dlg = _open_dialog(app)
        st, _scale, _y = dlg._steppers["edge_fraction"]
        for _ in range(70):              # 30 % → 100 %: nothing on this map reaches it
            _click(app, st.btn_inc.center)
        assert dlg.settings["edge_fraction"] == 1.0
        assert _edges(app.bm) == set()
    print("✅ test_stepper_changes_a_level passed")


def test_floor_clears_its_rim_edges_against_wall_cells():
    """A Floor box clears an edge between a Floor cell and a wall cell (it only repeats the
    wall cell) but keeps one between a Floor cell and an open cell."""
    with tempfile.TemporaryDirectory() as tmp:
        det = dict(DETECTION, outside_seeds=[])
        app, _ = _app(tmp, {"detection": det})
        bm = app.bm
        bm.set_edge_wall(C(4, 3), E)          # (4,3)|(5,3): a stair edge, say
        bm.set_edge_wall(C(4, 3), S)          # (4,3)/(4,4)
        app._terrain_regions = [_floor(4, 3, 4, 3)]
        # Both neighbours, (5,3) and (4,4), are open floor: both edges stay.
        app._apply_floor_regions()
        assert (4, 3, E) in _edges(bm) and (4, 3, S) in _edges(bm)
        # A flood from inside makes every inside cell a wall cell; the Floor box then
        # reopens (4,3), and both its edges, now against wall cells, go.
        app._redetect_walls()
        bm.set_edge_wall(C(4, 3), E)
        bm.set_edge_wall(C(4, 3), S)
        app.bm.params.outside_seeds = [C(5, 3)]
        app.bm.detect_walls()
        assert (5, 3) in _blocked(bm)
        app._apply_floor_regions()
        assert (4, 3) not in _blocked(bm)
        assert (4, 3, E) not in _edges(bm) and (4, 3, S) not in _edges(bm)
    print("✅ test_floor_clears_its_rim_edges_against_wall_cells passed")


def test_editor_floor_box_previews_and_saves():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain = _app(tmp, {"detection": DETECTION})
        assert (0, 0) in _blocked(app.bm)
        app._open_terrain_editor()
        ed = app.terrain_editor
        ed.selected_type = "Floor"
        ed.selection_rect = pygame.Rect(0, 0, 2 * CELL - 4, 2 * CELL - 4)
        ed._apply_terrain_to_selection()
        ed.selection_rect = None
        ed._regions_changed()
        assert (0, 0) not in _blocked(app.bm) and (1, 1) not in _blocked(app.bm), \
            "the box clears while the editor is open"
        assert ed.terrain_regions[-1]["type"] == "Floor"
        assert app.bm.get_terrain_type(C(0, 0)) == rpg.TerrainType.Standard
        app._close_terrain_editor()
        with open(terrain) as f:
            assert [r["type"] for r in json.load(f)["regions"]] == ["Floor"]
        app._load_terrain(terrain)
        assert (0, 0) not in _blocked(app.bm)
        # Deleting the box in the editor brings the flood back.
        app._open_terrain_editor()
        ed.selected_region_idx = 0
        ed.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE, mod=0, unicode=""))
        assert (0, 0) in _blocked(app.bm)
        app._close_terrain_editor()
    print("✅ test_editor_floor_box_previews_and_saves passed")



# ── The terrain editor's Edge tool ───────────────────────────────────────────
def _edge_editor(tmp, doc=None, gap=False):
    app, terrain = _app(tmp, doc if doc is not None else {"detection": DETECTION}, gap=gap)
    app._open_terrain_editor()
    ed = app.terrain_editor
    ed.selected_type = "Edge"
    return app, terrain, ed


def _drag(ed, a, b, button=1):
    """Press at ``a``, move to ``b``, release (map px = screen px at zoom 1)."""
    ed.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=a, button=button))
    ed.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=b, rel=(0, 0), buttons=(1, 0, 0)))
    ed.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=b, button=button))


def _vx(i, j):
    """Grid crossing (i, j) in px, nudged off it as a hand would be."""
    return (i * CELL + 3, j * CELL - 2)


def test_edge_run_closes_a_leak_and_saves():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain, ed = _edge_editor(tmp, gap=True)
        assert _blocked(app.bm) & INSIDE, "the gap lets the flood in"
        _drag(ed, _vx(X0, 3), _vx(X0, 4))
        assert app._edge_overrides == {"add": [[X0 - 1, 3, "E"]], "remove": []}
        assert not (_blocked(app.bm) & INSIDE), "re-detected while the editor is open"
        app._close_terrain_editor()
        with open(terrain) as f:
            assert json.load(f)["edge_overrides"] == {"add": [[X0 - 1, 3, "E"]], "remove": []}
        app._load_terrain(terrain)
        assert not (_blocked(app.bm) & INSIDE)
    print("✅ test_edge_run_closes_a_leak_and_saves passed")


def test_edge_run_from_a_wall_removes_it():
    with tempfile.TemporaryDirectory() as tmp:
        app, _, ed = _edge_editor(tmp)
        # Right to left along the top wall: the run starts on a wall, so it removes.
        _drag(ed, _vx(X0 + 2, Y0), _vx(X0, Y0))
        assert app._edge_overrides["add"] == []
        assert sorted(map(tuple, app._edge_overrides["remove"])) == \
            [(X0, Y0 - 1, "S"), (X0 + 1, Y0 - 1, "S")]
        assert (X0, Y0 - 1, S) not in _edges(app.bm) and (X0 + 2, Y0 - 1, S) in _edges(app.bm)
        assert _blocked(app.bm) & INSIDE, "the opened wall lets the flood in"
    print("✅ test_edge_run_from_a_wall_removes_it passed")


def test_edge_click_toggles_one_edge():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain, ed = _edge_editor(tmp)
        p = (4 * CELL + CELL // 2, 3 * CELL + CELL - 3)       # near (4,3)'s south side
        _drag(ed, p, p)
        assert (4, 3, S) in _edges(app.bm)
        assert app._edge_overrides["add"] == [[4, 3, "S"]]
        _drag(ed, p, p)
        assert (4, 3, S) not in _edges(app.bm)
        assert app._edge_overrides == {"add": [], "remove": []}, "nothing left to record"
        app._close_terrain_editor()
        assert app._edge_overrides is None
        with open(terrain) as f:
            assert "edge_overrides" not in json.load(f)
    print("✅ test_edge_click_toggles_one_edge passed")


def test_edge_box_erase_and_undo():
    with tempfile.TemporaryDirectory() as tmp:
        app, _, ed = _edge_editor(tmp)
        before = _edges(app.bm)
        # A box round the west wall's middle two edges and a stretch of open floor.
        _drag(ed, (X0 * CELL - 10, 3 * CELL + 5), (X0 * CELL + 3 * CELL, 5 * CELL - 5), button=3)
        assert sorted(map(tuple, app._edge_overrides["remove"])) == \
            [(X0 - 1, 3, "E"), (X0 - 1, 4, "E")], "only edges that were walls are recorded"
        assert (X0 - 1, 3, E) not in _edges(app.bm) and (X0 - 1, 2, E) in _edges(app.bm)
        ed.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, mod=pygame.KMOD_CTRL,
                                     unicode=""))
        assert _edges(app.bm) == before and app._edge_overrides["remove"] == []
    print("✅ test_edge_box_erase_and_undo passed")


def test_edge_tool_is_off_outside_drawn_detection():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain, ed = _edge_editor(tmp, {})
        assert not ed.edges_enabled
        _drag(ed, _vx(X0, 3), _vx(X0, 5))
        assert app._edge_overrides == {"add": [], "remove": []}
        app._close_terrain_editor()
        with open(terrain) as f:
            assert "edge_overrides" not in json.load(f)
    print("✅ test_edge_tool_is_off_outside_drawn_detection passed")


def test_floor_keeps_a_hand_added_edge():
    with tempfile.TemporaryDirectory() as tmp:
        det = dict(DETECTION, outside_seeds=[])
        app, _ = _app(tmp, {"detection": det, "regions": [_floor(4, 3, 5, 3)],
                            "edge_overrides": {"add": [[4, 3, "E"]], "remove": []}})
        assert (4, 3, E) in _edges(app.bm), "Floor clears detected edges, not drawn ones"
    print("✅ test_floor_keeps_a_hand_added_edge passed")


# ── Edge doors (Door mode on a drawn page) ───────────────────────────────────
def _door_editor(tmp, doc=None):
    app, terrain, ed = _edge_editor(tmp, doc)
    ed.selected_type = "Door"
    return app, terrain, ed


def test_edge_door_drag_places_a_wide_door_that_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain, ed = _door_editor(tmp)
        _drag(ed, _vx(X0, 3), _vx(X0, 5))                 # down the west wall, two edges
        assert len(app.bm.doors) == 1
        d = app.bm.doors[0]
        assert list(d.cells) == [] and {(e.cell.col, e.cell.row, e.side) for e in d.edges} == \
            {(X0 - 1, 3, E), (X0 - 1, 4, E)}
        assert app.bm.edge_between(C(X0 - 1, 3), C(X0, 3)), "closed, it blocks"
        app.bm.lock_door(d.id, 17)
        app.bm.unlock_door(d.id)
        assert app.bm.open_door(d.id)
        app._close_terrain_editor()
        with open(terrain) as f:
            rec = json.load(f)["doors"][0]
        assert rec["edges"] == [[X0 - 1, 3, "E"], [X0 - 1, 4, "E"]]
        assert "cells" not in rec and "cell" not in rec and rec["link_target"] is None
        assert rec["open"] and not rec["locked"] and rec["lock_dc"] == 17
        app._load_terrain(terrain)
        d = app.bm.doors[0]
        assert len(app.bm.doors) == 1 and len(d.edges) == 2 and d.open and d.lock_dc == 17
        assert not app.bm.edge_between(C(X0 - 1, 3), C(X0, 3)), "open, it passes the wall"
        assert app.bm.edge_between(C(X0 - 1, 2), C(X0, 2)), "the wall beside it still blocks"
    print("✅ test_edge_door_drag_places_a_wide_door_that_round_trips passed")


def test_an_editor_door_in_a_gap_keeps_the_room_open_across_reload():
    with tempfile.TemporaryDirectory() as tmp:
        app, terrain, _ = _edge_editor(tmp, {"detection": DETECTION}, gap=True)
        ed = app.terrain_editor
        ed.selected_type = "Door"
        assert INSIDE <= _blocked(app.bm), "the gap leaks the flood"
        _drag(ed, _vx(X0, 3), _vx(X0, 4))                 # one edge door across the gap
        assert len(app.bm.doors) == 1
        assert not (_blocked(app.bm) & INSIDE), "the door re-detects live in the editor"
        app._close_terrain_editor()
        assert not (_blocked(app.bm) & INSIDE)
        app._load_terrain(terrain)
        assert len(app.bm.doors) == 1 and not (_blocked(app.bm) & INSIDE), "and after reload"
    print("✅ test_an_editor_door_in_a_gap_keeps_the_room_open_across_reload passed")


def test_edge_door_click_toggles_and_a_drag_stops_at_four():
    with tempfile.TemporaryDirectory() as tmp:
        app, _, ed = _door_editor(tmp)
        p = (4 * CELL + CELL // 2, 3 * CELL + CELL - 3)   # near (4,3)'s south side
        _drag(ed, p, p)
        assert [(e.cell.col, e.cell.row, e.side) for e in app.bm.doors[0].edges] == [(4, 3, S)]
        _drag(ed, p, p)
        assert len(app.bm.doors) == 0, "a click on the door removes it"
        _drag(ed, _vx(0, 4), _vx(9, 4))                    # nine edges along a grid line
        assert len(app.bm.doors[0].edges) == ed.MAX_DOOR_WIDTH
        app.bm.add_door([C(1, 1)])                          # an old cell door is still clearable
        _drag(ed, (CELL + CELL // 2, CELL + 4), (CELL + CELL // 2, CELL + 4))
        assert all(d.edges for d in app.bm.doors)
    print("✅ test_edge_door_click_toggles_and_a_drag_stops_at_four passed")


def test_door_mode_places_cell_doors_outside_drawn_detection():
    with tempfile.TemporaryDirectory() as tmp:
        app, _, ed = _door_editor(tmp, {})
        _drag(ed, (4 * CELL + 5, 3 * CELL + 5), (4 * CELL + 5, 3 * CELL + 5))
        assert [(c.col, c.row) for c in app.bm.doors[0].cells] == [(4, 3)]
    print("✅ test_door_mode_places_cell_doors_outside_drawn_detection passed")


def test_a_map_click_near_the_line_finds_an_edge_door():
    with tempfile.TemporaryDirectory() as tmp:
        app, _ = _app(tmp, {"detection": DETECTION})
        app.bm.add_edge_door([rpg.Edge(C(4, 3), E)])
        x, y = app._cell_to_screen(4, 3)
        cpx = int(CELL * app.map_scale)
        near = (x + cpx - 2, y + cpx // 2)
        assert app._door_index_at(C(4, 3), near) == 0
        assert app._door_index_at(C(5, 3), (x + cpx + 2, y + cpx // 2)) == 0, "from either side"
        assert app._door_index_at(C(4, 3), (x + cpx // 2, y + cpx // 2)) == -1, "not mid-cell"
        assert app._door_index_at(C(5, 3)) == 0 and app._door_index_at(C(6, 3)) == -1
        # The DM's menu needs the actor standing beside the line.
        from menus import dm
        seen = {}
        app._ask_actor = lambda *a, **kw: seen.setdefault("opts", a[3])
        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size = "Kira", 6, 3, 1
        app.combat.add_agent_config(app.bm, cfg)
        app.combat.apply_agent_configs(app.bm)
        idx = len(app.bm.placed_agents) - 1
        app.combat_active = True
        app._current_agent_idx = lambda: idx
        logs = []
        app._combat_log_add = lambda *a, **k: logs.append(a)
        dm.show_door_menu(app, C(4, 3), near)
        assert "opts" not in seen and logs, "two cells off the line is out of reach"
        app.bm.set_agent_position(idx, C(5, 3))
        dm.show_door_menu(app, C(4, 3), near)
        assert [label for label, _fn in seen["opts"]][0] == "Open door"
        app._draw_doors(cpx)                                # draws as a bar, no crash
    print("✅ test_a_map_click_near_the_line_finds_an_edge_door passed")


def test_editor_draws_edge_doors_and_the_drag_preview():
    with tempfile.TemporaryDirectory() as tmp:
        app, _, ed = _door_editor(tmp)
        app.bm.add_edge_door([rpg.Edge(C(4, 3), S)])
        ed.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=_vx(X0, 3), button=1))
        ed.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=_vx(X0, 5), rel=(0, 0),
                                     buttons=(1, 0, 0)))
        ed.draw(app.screen)
        assert ed._door_edge_keys(*ed.door_edge_drag) == [(X0 - 1, 3, "E"), (X0 - 1, 4, "E")]
    print("✅ test_editor_draws_edge_doors_and_the_drag_preview passed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__} failed: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
