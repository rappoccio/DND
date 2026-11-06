#!/usr/bin/env python3
"""Restoring an autosave in a campaign dungeon keeps the current design
(plans/DUNGEON_RELEASES_PLAN.md step 1, D3 and D7).

A slot is play state. A map edit made after the slot was written must survive the restore
and the saves that follow it:

  · a door added since the slot stays in map.json, a door removed stays gone, and a door
    the slot knows gets its open state from the slot;
  · a wall region and a whole-map switch edited since the slot stay as edited, live and in
    map.json.

Per-cell terrain and light in a resumed fight come from the board snapshot; step 4 covers
those.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
# The runner turns the ring off for every suite; this one is about the ring.
os.environ["RPG_AUTOSAVE"] = "1"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile
import traceback

import pygame
import rpg_battle_map as rpg

import autosave
import save_layout as sl
from test_campaign_open import _campaign, _open, _place

PC_FACTION, FOE_FACTION = 0, 1
EDIT_DOOR = (7, 2)
EDIT_REGION = {"name": "fixed wall", "type": "Wall", "cells": [[8, 6]]}


def _map_doc(dl):
    with open(dl.resolve("hall", sl.MAP_FILE)) as f:
        return json.load(f)


def _door_cells(doc):
    return sorted(tuple(d["cells"][0]) for d in doc.get("doors", []))


def _idx(app, name):
    return next(i for i, pt in enumerate(app.bm.placed_agents) if pt.name == name)


def _fight_with_a_slot(app):
    """A running fight on ``hall`` with a slot from its first turn. The slot's door (4,4)
    is open and the design's is shut."""
    _place(app, "Aria", 1, 1)
    _place(app, "Gnasher", 8, 1)
    app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
    app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
    app.bm.open_door(app.bm.doors[0].id)
    app._save_terrain()
    app._start_combat()
    slots = autosave.list_slots(app)
    assert slots, "the fight's first turn wrote no slot"
    return slots[0]["slot"]


def test_restore_keeps_map_edits():
    tmp = tempfile.mkdtemp(prefix="autosave_design_")
    try:
        camp, dl = _campaign(tmp)
        app = _open(camp.root)
        k = _fight_with_a_slot(app)

        # The DM fixes the map after the slot was written.
        app.bm.close_door(app.bm.doors[0].id)
        app.bm.add_door(cells=[rpg.Cell(*EDIT_DOOR)])
        app._walls_enabled = True
        app._terrain_regions.append(dict(EDIT_REGION))
        app._save_terrain()
        fixed = _map_doc(dl)
        assert _door_cells(fixed) == [(4, 4), EDIT_DOOR]
        assert fixed["walls_enabled"] is True and len(fixed["regions"]) == 1

        assert autosave.restore(app, k), "the restore was refused"
        assert app.combat_active

        # Live: the design is the fixed one, the door the slot knows has the slot's state.
        assert sorted((d.cell.col, d.cell.row) for d in app.bm.doors) == [(4, 4), EDIT_DOOR]
        assert app._walls_enabled is True
        assert [r["name"] for r in app._terrain_regions] == ["fixed wall"]
        assert next(d for d in app.bm.doors if d.cell.col == 4).open, "lost the slot's door"

        # On disk: the next save leaves the fixed design alone.
        app._save_terrain()
        after = _map_doc(dl)
        assert _door_cells(after) == [(4, 4), EDIT_DOOR], "a door fix was undone"
        assert after["walls_enabled"] is True, "a whole-map fix was undone"
        assert len(after["regions"]) == 1, "a wall fix was undone"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a restore keeps doors, walls and switches edited after the slot")


def test_restore_keeps_a_door_removed_since():
    tmp = tempfile.mkdtemp(prefix="autosave_design_")
    try:
        camp, dl = _campaign(tmp)
        app = _open(camp.root)
        k = _fight_with_a_slot(app)
        app.bm.remove_door(app.bm.doors[0].id)
        app._save_terrain()
        assert _door_cells(_map_doc(dl)) == []

        assert autosave.restore(app, k), "the restore was refused"
        assert not app.bm.doors, "a removed door came back"
        app._save_terrain()
        assert _door_cells(_map_doc(dl)) == [], "a removed door came back in map.json"
    finally:
        shutil.rmtree(tmp)
    print("  ✅ a restore does not bring back a door removed after the slot")


def main():
    pygame.init()
    tests = [test_restore_keeps_map_edits, test_restore_keeps_a_door_removed_since]
    print("Running autosave design tests…")
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError:
            failed += 1
            print(f"  ❌ {t.__name__}")
            traceback.print_exc()
    if failed:
        print(f"\n❌ {failed}/{len(tests)} autosave design tests failed")
        return 1
    print(f"\n✅ All {len(tests)} autosave design tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
