#!/usr/bin/env python3
"""A PC's NPC flag through delete, the stats dialog, save and reload.

Sabalath, a PC, kept coming back as an NPC (spells/day instead of slots):

  · deleting a creature left _agent_meta on the old indices, so a monster's entry landed on
    the PC that slid into its slot, and the save wrote that PC out with is_npc at the top;
  · a reload believed the top-level flag over the stats one;
  · unticking NPC in the stats dialog never cleared the engine flag, so saving put it back.
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

MAP = os.path.join(_ROOT, "maps", "TestDNDMap.png")


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = name, col, row, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    return len(app.bm.placed_agents) - 1


def _save(app):
    """Save to a temp file; returns the agents as written."""
    fd, path = tempfile.mkstemp(suffix="_agents.json")
    os.close(fd)
    app._save_agents(path)
    with open(path) as f:
        agents = json.load(f)["agents"]
    os.unlink(path)
    return agents


def _stats_ok(app, idx, npc_data):
    """Press OK in the stats dialog with the NPC box as npc_data says."""
    st = app.combat.get_agent_stats(app.bm, idx)
    class _V:
        def __init__(self, value):
            self.value = value
    steppers = {k: _V(getattr(st, k)) for k in
                ("str", "dex", "con", "intel", "wis", "cha", "hp_cur", "hp_max", "base_ac",
                 "speed_walk", "speed_swim", "speed_fly", "speed_burrow", "prof_bonus",
                 "num_attacks")}
    app._on_stats_ok(idx, steppers, {}, "Cleric", 3, npc_data)


def test_delete_rekeys_meta():
    app = App(MAP, seed=1)
    gob = _place(app, "Goblin", 1, 1)
    pc = _place(app, "Sabalath", 2, 1)
    other = _place(app, "Ogre", 3, 1)
    app._agent_meta[gob] = {"is_npc": True, "npc_spell_groups": {}}
    app._agent_meta[pc + 0] = {"is_boss": True}
    app._agent_meta[other] = {"is_npc": True, "npc_spell_groups": {}}
    app._spell_metadata[(other, 0)] = {"level": 1}
    app._spell_metadata[(gob, 0)] = {"level": 2}

    app._remove_placed_agent(gob)
    assert [p.name for p in app.bm.placed_agents] == ["Sabalath", "Ogre"]
    assert app._agent_meta == {0: {"is_boss": True},
                               1: {"is_npc": True, "npc_spell_groups": {}}}
    assert app._spell_metadata == {(1, 0): {"level": 1}}
    print("  ✓ deleting a creature re-keys the metadata past it")


def test_saved_flag():
    saved = App._saved_is_npc
    assert saved({"is_npc": True, "stats": {"is_npc": False}}) is False   # the stale flag
    assert saved({"is_npc": False, "stats": {"is_npc": True}}) is True
    assert saved({"is_npc": True, "stats": {"str": 10}}) is True          # the older format
    assert saved({"is_npc": True}) is True
    assert saved({"stats": {}}) is False
    print("  ✓ a saved stats flag wins over the top-level one")


def test_untick_survives_save():
    app = App(MAP, seed=1)
    idx = _place(app, "Sabalath", 2, 1)
    _stats_ok(app, idx, {"is_npc": True, "npc_spell_groups": {}})
    assert app.combat.get_agent_stats(app.bm, idx).is_npc
    assert _save(app)[idx]["is_npc"] is True

    _stats_ok(app, idx, None)
    assert not app.combat.get_agent_stats(app.bm, idx).is_npc
    assert idx not in app._agent_meta
    saved = _save(app)[idx]
    assert saved["stats"]["is_npc"] is False and not saved.get("is_npc")
    print("  ✓ unticking NPC clears the flag and the save keeps it cleared")


def test_stale_flag_heals_on_reload():
    """Java's save: a stale top-level flag over a stats flag saying PC."""
    app = App(MAP, seed=1)
    idx = _place(app, "Java", 2, 1)
    agents = _save(app)
    agents[idx]["is_npc"] = True
    agents[idx]["npc_spell_groups"] = {}
    assert agents[idx]["stats"]["is_npc"] is False
    fd, path = tempfile.mkstemp(suffix="_agents.json")
    with os.fdopen(fd, "w") as f:
        json.dump({"agents": agents}, f)
    app._load_agents(path)
    os.unlink(path)
    assert not app.combat.get_agent_stats(app.bm, idx).is_npc
    assert idx not in app._agent_meta
    assert not _save(app)[idx].get("is_npc")
    print("  ✓ a stale top-level flag does not turn a PC into an NPC on reload")


def main():
    pygame.init()
    tests = [test_delete_rekeys_meta, test_saved_flag, test_untick_survives_save,
             test_stale_flag_heals_on_reload]
    print("Running NPC flag round-trip tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} NPC flag round-trip tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
