#!/usr/bin/env python3
"""``GameView`` — the per-viewer read projection (MULTIPLAYER_PLAN.md M3, seam S1).

M3's acceptance criterion is stated in the plan as a *byte-level* assertion, and the
reason is worth keeping in front of whoever edits this file: a client that cheats does
not read the screen, it reads its own network traffic. A field-level check
(``assert skarn not in [a["agent"] for a in view["agents"]]``) passes happily while the
creature's name sits in a log line, its cell sits in a terrain list, and its initiative
total sits in a combat block. So the headline checks here serialize the whole view and
search the bytes.

The scene every check shares (12×12 grid, fog up, explored = the 7×7 block at the
top-left):

    Aria      PC     (2, 3)   owned by Kira      — the viewer's own token
    Brannor   PC     (4, 3)   DM-controlled      — an ally she does not own
    Gnasher   enemy  (5, 3)   explored           — an enemy she can see
    Skarn     enemy  (9, 9)   UNEXPLORED         — the creature that must not exist

Covered here:
  · an unexplored enemy is absent from the serialized bytes  (test_unexplored_enemy_absent_from_bytes)
  · …including out of the initiative order                   (test_initiative_never_names_a_hidden_creature)
  · the DM sees the same scene unfiltered                    (test_dm_view_is_unfiltered)
  · a visible enemy's HP is a band, never a number           (test_enemy_hp_is_a_band)
  · party vitals are table information; sheets are not       (test_vitals_and_sheet_tiers)
  · D-M3-3: a concealed automated enemy is omitted too       (test_concealed_automated_enemy_omitted)
  · D-M3-5: unexplored terrain, doors and ladders are omitted (test_unexplored_map_structure_omitted)
  · DM-channel FIELDS never reach a player, seen or not      (test_dm_only_fields_never_reach_a_player)
  · fog down shows a player what the DM's screen shows       (test_fog_down_matches_the_dm_screen)
  · D-M3-6: prompt_id is gated by ANSWER_PROMPT              (test_prompt_id_only_for_its_owner)
  · D-M4-2: the fog mask crosses as row runs, not pairs      (test_fog_crosses_as_row_runs)
  · ...and a run closes on a gap rather than walking past it (test_row_runs_split_on_a_gap)
  · D-M4-1: the map image is keyed per viewer                (test_map_names_an_image_keyed_per_viewer)
  · a spectator gets a view and controls nothing             (test_spectator_gets_a_view)
  · an unseated principal is refused outright                (test_unseated_principal_refused)
"""

import os
import sys

# Headless SDL: set before pygame is imported anywhere (main.py imports it at module
# scope), same pair as test_session_roster.py.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json
import shutil
import tempfile

import rpg_battle_map as rpg

from net.roster import DM_PRINCIPAL_ID, PC_FACTION, Role
from net.view import build_view, explored_runs
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260922
FOE_FACTION = 1

# The explored block: everything else on the 12×12 grid has never been seen.
EXPLORED = [(c, r) for c in range(7) for r in range(7)]

# Distinctive numbers, so a byte search for one of them means something. A DC of 15 would
# collide with half the integers in a view; 4271 collides with nothing.
#
# The ladder targets were two-digit until 2026-09-23, when M4's `map.image` put a 16-char
# hex cache key in every view and `61` started matching it by luck. That is what the comment
# above was always warning about, so the fix is a more distinctive probe rather than a
# narrower search: the byte-level checks keep reading the WHOLE blob.
SECRET_LOCK_DC = 4271
SEEN_LOCK_DC   = 4272
SECRET_LADDER_TARGET = [4281, 4282, 4283]
SEEN_LADDER_TARGET   = [4284, 4285, 4286]


# ─────────────────────────────────────────────────────────────────────────────
#  Scene
# ─────────────────────────────────────────────────────────────────────────────

def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    raise KeyError(name)


def _scene(tmpdir):
    """The shared scene, plus the two seated players.

    Returns ``(app, kira, spectator)``. The DM principal is always seated and is reached
    through ``app.roster.get(DM_PRINCIPAL_ID)``.
    """
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "gameview_test_agents.json"))

    for name, col, row in (("Aria", 2, 3), ("Brannor", 4, 3),
                           ("Gnasher", 5, 3), ("Skarn", 9, 9)):
        _place(app, name, col, row)
    app.combat.apply_agent_configs(app.bm)

    for name in ("Aria", "Brannor"):
        app.bm.set_agent_faction(_idx(app, name), PC_FACTION)
    for name in ("Gnasher", "Skarn"):
        app.bm.set_agent_faction(_idx(app, name), FOE_FACTION)

    kira      = app.roster.add_principal("Kira", role=Role.PLAYER)
    spectator = app.roster.add_principal("Wen", role=Role.PLAYER)
    app.bm.set_agent_controller(_idx(app, "Aria"), kira.id)
    app._sync_roster_tokens()

    # Fog up, and exactly the top-left block seen. `_refresh_fog` is a frame-tick concern
    # and never runs here, so this mask is the one every check reads.
    app._set_fog(True)
    app.bm.set_explored_cells([rpg.Cell(c, r) for c, r in EXPLORED])

    # Map structure, half of it behind the fog (D-M3-5).
    app.bm.set_terrain_type(rpg.Cell(1, 1), rpg.TerrainType.Water)     # seen
    app.bm.set_terrain_type(rpg.Cell(9, 9), rpg.TerrainType.Wall)      # unseen
    app.bm.add_door(cells=[rpg.Cell(3, 1)], locked=True, lock_dc=SEEN_LOCK_DC)
    app.bm.add_door(cells=[rpg.Cell(10, 9)], locked=True, lock_dc=SECRET_LOCK_DC)
    app._ladders = [
        {"cells": [[2, 2]],   "target": SEEN_LADDER_TARGET},
        {"cells": [[10, 10]], "target": SECRET_LADDER_TARGET},
    ]
    return app, kira, spectator


def _blob(view) -> str:
    """The view as it would cross the wire. Every byte-level check searches this."""
    return json.dumps(view)


def _agent_names(view):
    return {a["name"] for a in view["agents"]}


def _by_name(view, name):
    for a in view["agents"]:
        if a["name"] == name:
            return a
    raise KeyError(f"{name} — not in this view")


def _run(fn):
    tmp = tempfile.mkdtemp()
    try:
        fn(*_scene(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
#  The headline assertion
# ─────────────────────────────────────────────────────────────────────────────

def test_unexplored_enemy_absent_from_bytes():
    """M3's acceptance criterion: a player's view of a scene containing an unexplored
    enemy carries no reference to that creature *anywhere* in the serialized bytes."""
    def check(app, kira, _spectator):
        view = build_view(app, kira)
        blob = _blob(view)

        assert "Skarn" not in blob, "the creature's name reached a player's wire"
        # Its cell, in the one encoding a cell takes on the wire ([col, row] pairs).
        assert "[9, 9]" not in blob, "the creature's cell reached a player's wire"
        assert _idx(app, "Skarn") not in {a["agent"] for a in view["agents"]}

        # And the check that a field-level test would have been happy with — kept, because
        # it names the failure precisely when the byte search trips.
        assert _agent_names(view) == {"Aria", "Brannor", "Gnasher"}, _agent_names(view)
    _run(check)
    print("✅ test_unexplored_enemy_absent_from_bytes")


def test_initiative_never_names_a_hidden_creature():
    """An initiative order is a list of integers, and a creature the agent list does not
    explain is an ambusher announced by arithmetic."""
    def check(app, kira, _spectator):
        app._start_combat()
        app.combat.stop_recording()

        view = build_view(app, kira)
        shown = {a["agent"] for a in view["agents"]}
        listed = {e["agent"] for e in view["combat"]["initiative"]}
        assert listed <= shown, f"initiative names {listed - shown}, which no token explains"
        assert _idx(app, "Skarn") not in listed
        assert "Skarn" not in _blob(view)
        assert view["combat"]["active"] is True

        # The DM's own order is complete — the filtering is the viewer's, not the engine's.
        dm = build_view(app, app.roster.get(DM_PRINCIPAL_ID))
        assert _idx(app, "Skarn") in {e["agent"] for e in dm["combat"]["initiative"]}
    _run(check)
    print("✅ test_initiative_never_names_a_hidden_creature")


def test_dm_view_is_unfiltered():
    def check(app, _kira, _spectator):
        dm = build_view(app, app.roster.get(DM_PRINCIPAL_ID))
        assert _agent_names(dm) == {"Aria", "Brannor", "Gnasher", "Skarn"}
        skarn = _by_name(dm, "Skarn")
        assert "cur" in skarn["hp"], "the DM reads numbers, not bands"
        assert "sheet" in skarn
        assert skarn["controller"] == DM_PRINCIPAL_ID
    _run(check)
    print("✅ test_dm_view_is_unfiltered")


# ─────────────────────────────────────────────────────────────────────────────
#  The three entitlement tiers
# ─────────────────────────────────────────────────────────────────────────────

def test_enemy_hp_is_a_band():
    """A visible enemy: position and name, a band, and no stat block."""
    def check(app, kira, _spectator):
        g = _by_name(build_view(app, kira), "Gnasher")
        assert set(g["hp"]) == {"band"}, g["hp"]
        assert g["hp"]["band"] in ("Healthy", "Bloodied", "Down")
        assert "sheet" not in g, "an enemy stat block reached a player"
        assert "controller" not in g, "who drives a token is DM-channel"
    _run(check)
    print("✅ test_enemy_hp_is_a_band")


def test_vitals_and_sheet_tiers():
    """Party hit points are table information; a party member's sheet is not.

    The rule lives in ``authorize()`` and this asserts the projection honours it, rather
    than re-deriving ownership — which is the split D-M3 keeps insisting on.
    """
    def check(app, kira, _spectator):
        view = build_view(app, kira)

        aria = _by_name(view, "Aria")           # owned
        assert aria.get("yours") is True
        assert {"cur", "max"} == set(aria["hp"])
        assert "sheet" in aria and "ac" in aria["sheet"]

        brannor = _by_name(view, "Brannor")     # an ally she does not own
        assert "yours" not in brannor
        assert {"cur", "max"} == set(brannor["hp"]), "party vitals are table information"
        assert "sheet" not in brannor, "an ally's sheet is not"

        assert view["you"]["principal_id"] == kira.id
        assert view["you"]["controls"] == [_idx(app, "Aria")]
    _run(check)
    print("✅ test_vitals_and_sheet_tiers")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M3-3 — the second gate the plan's filter table omitted
# ─────────────────────────────────────────────────────────────────────────────

def test_concealed_automated_enemy_omitted():
    """Gnasher stands in an explored cell and passes the fog gate. Hidden, and automated,
    the DM's own screen stops drawing it — so this view must stop too."""
    def check(app, kira, _spectator):
        g = _idx(app, "Gnasher")
        assert "Gnasher" in _agent_names(build_view(app, kira)), "precondition"

        app.bm.set_agent_npc_automated(g, True)
        cond = app.combat.get_agent_conditions(app.bm, g)
        cond.hidden = True
        app.combat.set_agent_conditions(app.bm, g, cond)
        assert app._npc_concealed_from_party(g, app.bm.placed_agents[g]), "precondition"

        view = build_view(app, kira)
        assert "Gnasher" not in _agent_names(view)
        assert "Gnasher" not in _blob(view), "a concealed ambusher reached a player's wire"
        # Unchanged for the DM, who has to run the creature.
        assert "Gnasher" in _agent_names(build_view(app, app.roster.get(DM_PRINCIPAL_ID)))
    _run(check)
    print("✅ test_concealed_automated_enemy_omitted")


# ─────────────────────────────────────────────────────────────────────────────
#  D-M3-5 — map structure
# ─────────────────────────────────────────────────────────────────────────────

def test_unexplored_map_structure_omitted():
    """The floor plan of a wing the party has not entered is the same leak as the enemy
    token, arriving by a quieter route."""
    def check(app, kira, _spectator):
        view = build_view(app, kira)
        blob = _blob(view)

        cells = {(c, r) for c, r, *_ in view["terrain"]["cells"]}
        assert (1, 1) in cells, "seen water should be on the wire"
        assert (9, 9) not in cells, "unseen wall reached a player"
        assert all((c, r) in set(EXPLORED) for c, r in cells), cells

        door_cells = {tuple(c) for d in view["terrain"]["doors"] for c in d["cells"]}
        assert [3, 1] in [list(c) for c in door_cells]
        assert (10, 9) not in door_cells, "a door behind the fog reached a player"

        lad_cells = {tuple(c) for l in view["terrain"]["ladders"] for c in l["cells"]}
        assert (2, 2) in lad_cells and (10, 10) not in lad_cells

        assert "[10, 9]" not in blob and "[10, 10]" not in blob

        # The DM keeps the authoring shape.
        dm = build_view(app, app.roster.get(DM_PRINCIPAL_ID))
        assert "regions" in dm["terrain"] and "cells" not in dm["terrain"]
        assert len(dm["terrain"]["doors"]) == 2
        assert len(dm["terrain"]["ladders"]) == 2
    _run(check)
    print("✅ test_unexplored_map_structure_omitted")


def test_dm_only_fields_never_reach_a_player():
    """Fog decides which cells; the DM channel decides which fields. A lock DC and a
    ladder's destination are withheld even on a feature standing in plain sight."""
    def check(app, kira, _spectator):
        view = build_view(app, kira)
        blob = _blob(view)

        for n in (SECRET_LOCK_DC, SEEN_LOCK_DC, *SECRET_LADDER_TARGET, *SEEN_LADDER_TARGET):
            assert str(n) not in blob, f"{n} reached a player's wire"
        assert "lock_dc" not in blob and "break_dc" not in blob
        assert "link_target" not in blob
        assert all("target" not in l for l in view["terrain"]["ladders"])

        seen_door = next(d for d in view["terrain"]["doors"] if d["cells"] == [[3, 1]])
        assert seen_door["locked"] is True, "that it is locked is visible; the DC is not"

        dm = build_view(app, app.roster.get(DM_PRINCIPAL_ID))
        assert str(SEEN_LOCK_DC) in _blob(dm), "the DM does get the DC"
    _run(check)
    print("✅ test_dm_only_fields_never_reach_a_player")


# ─────────────────────────────────────────────────────────────────────────────
#  Fog down, prompts, spectators, refusal
# ─────────────────────────────────────────────────────────────────────────────

def test_fog_down_matches_the_dm_screen():
    """M3's rule is that a client never sees MORE than the DM's console — not that it
    always sees less. With fog off the console draws the whole board, so this does too."""
    def check(app, kira, _spectator):
        assert "Skarn" not in _agent_names(build_view(app, kira)), "precondition"
        app._set_fog(False)
        view = build_view(app, kira)
        assert view["fog"]["active"] is False
        assert "Skarn" in _agent_names(view)
        # Entitlement is untouched by fog: still a band, still no sheet.
        assert set(_by_name(view, "Skarn")["hp"]) == {"band"}
        assert str(SEEN_LOCK_DC) not in _blob(view), "fog is not an entitlement"
    _run(check)
    print("✅ test_fog_down_matches_the_dm_screen")


def test_prompt_id_only_for_its_owner():
    """D-M3-6. The gate is ownership through ``authorize()``, not the widget drawing it."""
    def check(app, kira, spectator):
        assert build_view(app, kira)["you"]["prompt_id"] is None

        p = app.prompts.ask(actor_idx=_idx(app, "Aria"), owner=kira.id,
                            kind="action", title="Aria's move",
                            options=[], expects="none")
        assert build_view(app, kira)["you"]["prompt_id"] == p.id
        assert build_view(app, spectator)["you"]["prompt_id"] is None, \
            "a prompt addressed to someone else was announced"
        # NN4: the DM may answer any prompt at any time.
        assert build_view(app, app.roster.get(DM_PRINCIPAL_ID))["you"]["prompt_id"] == p.id
    _run(check)
    print("✅ test_prompt_id_only_for_its_owner")


def test_spectator_gets_a_view():
    """A seated player owning zero tokens is a spectator: a view, and nothing of their
    own in it."""
    def check(app, _kira, spectator):
        view = build_view(app, spectator)
        assert view["you"]["controls"] == []
        assert _agent_names(view) == {"Aria", "Brannor", "Gnasher"}
        # Party vitals are table information for a spectator too — the rule is the
        # faction, not ownership.
        assert {"cur", "max"} == set(_by_name(view, "Aria")["hp"])
        assert "sheet" not in _by_name(view, "Aria")
    _run(check)
    print("✅ test_spectator_gets_a_view")


def test_unseated_principal_refused():
    def check(app, kira, _spectator):
        app.roster.remove_principal(kira.id)
        try:
            build_view(app, kira)
        except PermissionError:
            pass
        else:
            raise AssertionError("an unseated principal was handed a view")
    _run(check)
    print("✅ test_unseated_principal_refused")


def test_fog_crosses_as_row_runs():
    """D-M4-2 as amended 2026-09-23: the mask is ``[row, col_start, col_end]`` spans.

    Measured: cell pairs are 8918 of them — 85 KB of JSON — on a fully-explored
    ``wachterhaus``, paid on *every* push. The 7×7 block here is 7 runs instead of 49 pairs.
    The field is renamed as well as reshaped, because a client written against pairs would
    misread runs in silence; the ``"explored" not in`` assertion is that rename.

    The expansion check matters more than the encoding: a run that reached one cell too far
    would hand a player a cell the party has not earned, which is the leak D-M3-5 spent a
    filter table on.
    """
    def check(app, kira, _spectator):
        fog = build_view(app, kira)["fog"]
        assert "explored" not in fog, "the pair-shaped field is still on the wire"
        runs = fog["explored_runs"]
        assert runs == [[r, 0, 6] for r in range(7)], runs
        expanded = {(c, r) for r, c0, c1 in runs for c in range(c0, c1 + 1)}
        assert expanded == set(EXPLORED), "the runs do not expand to the party's mask"
        assert runs == sorted(runs), "the encoding is not canonical"
    _run(check)
    print("✅ test_fog_crosses_as_row_runs")


def test_row_runs_split_on_a_gap():
    """The encoder itself, on a mask the shared scene cannot produce.

    The 7x7 block is contiguous in every row, so a view built from it never exercises the
    branch that *closes* a run mid-row — and a mutant that walked that run one cell too far
    passed the whole suite. A leak needs one gap to show itself, so here is the gap: two
    runs in one row, a single-cell run, and a row with nothing in it at all.
    """
    mask = {(0, 0), (1, 0), (3, 0), (4, 0), (9, 2)}
    assert explored_runs(mask) == [[0, 0, 1], [0, 3, 4], [2, 9, 9]], explored_runs(mask)
    for run in explored_runs(mask):
        row, c0, c1 = run
        assert all((c, row) in mask for c in range(c0, c1 + 1)), \
            f"run {run} covers a cell the party has not earned"
    assert explored_runs(set()) == []
    print("✅ test_row_runs_split_on_a_gap")


def test_map_names_an_image_keyed_per_viewer():
    """D-M4-1: a player's ``?v=`` is the mask hash and the DM's is the content hash, so the
    same page is two URLs — which is the point, because it is two pictures. A shared key
    would mean one of them is being served the other's image."""
    def check(app, kira, spectator):
        player = build_view(app, kira)["map"]["image"]
        crowd  = build_view(app, spectator)["map"]["image"]
        dm     = build_view(app, app.roster.get(DM_PRINCIPAL_ID))["map"]["image"]
        assert player.startswith("/map.png?v="), player
        assert player == crowd, "fog is party-scoped; two players must share one image"
        assert player != dm, "a player and the DM were handed the same picture"
    _run(check)
    print("✅ test_map_names_an_image_keyed_per_viewer")


def test_view_envelope_shape():
    """Ground rules 1 and 5: every frame carries a `v` and a `t`, and `seq` is the
    caller's (D-M3-1) rather than something this module invents."""
    def check(app, kira, _spectator):
        view = build_view(app, kira, seq=1284)
        assert view["v"] == 1 and view["t"] == "view"
        assert view["seq"] == 1284
        assert build_view(app, kira)["seq"] == 0
        assert view["map"]["cols"] == app.bm.grid_cols
        assert view["map"]["rows"] == app.bm.grid_rows
    _run(check)
    print("✅ test_view_envelope_shape")


if __name__ == "__main__":
    test_unexplored_enemy_absent_from_bytes()
    test_initiative_never_names_a_hidden_creature()
    test_dm_view_is_unfiltered()
    test_enemy_hp_is_a_band()
    test_vitals_and_sheet_tiers()
    test_concealed_automated_enemy_omitted()
    test_unexplored_map_structure_omitted()
    test_dm_only_fields_never_reach_a_player()
    test_fog_down_matches_the_dm_screen()
    test_prompt_id_only_for_its_owner()
    test_spectator_gets_a_view()
    test_unseated_principal_refused()
    test_fog_crosses_as_row_runs()
    test_row_runs_split_on_a_gap()
    test_map_names_an_image_keyed_per_viewer()
    test_view_envelope_shape()
    print("\nAll GameView tests passed! 🎉")
