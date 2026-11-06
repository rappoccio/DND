#!/usr/bin/env python3
"""Ctrl+C / Ctrl+V carries team + automation; Generate Dungeon's "Mob groups/map" cap.

  · a pasted agent keeps its source's team (faction)        (test_paste_keeps_team)
  · ...and its NPC automation flags                         (test_paste_keeps_automation)
  · groups=N populates exactly N rooms, never room 0        (test_groups_caps_populated_rooms)
  · the boss room is always one of the N                    (test_groups_keeps_the_boss)
  · groups=None / >= rooms populates every room as before   (test_groups_unset_is_every_room)
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import rpg_battle_map as rpg
import encounter_generator as eg
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
GUI_DIR = os.path.join(_ROOT, "gui")


def _app_with_agent():
    app = App(MAP_PATH, seed=12345)
    cfg = rpg.AgentConfig()
    cfg.name, cfg.size, cfg.start_col, cfg.start_row = "Goblin", 1, 1, 1
    idx = app.bm.spawn_agent(cfg)
    assert idx >= 0
    return app, idx


def _copy_paste(app, idx):
    app._copy_agent(idx)
    before = len(app.bm.placed_agents)
    app._paste_agent(rpg.Cell(8, 8))
    assert len(app.bm.placed_agents) == before + 1
    return len(app.bm.placed_agents) - 1


def test_paste_keeps_team():
    app, idx = _app_with_agent()
    app.bm.set_agent_faction(idx, 3)
    new = _copy_paste(app, idx)
    assert app.bm.get_agent_faction(new) == 3


def test_paste_keeps_automation():
    app, idx = _app_with_agent()
    app.bm.set_agent_npc_automated(idx, True)
    app.bm.set_agent_npc_automation_difficulty(idx, 3)
    new = _copy_paste(app, idx)
    assert app.bm.is_agent_npc_automated(new)
    assert app.bm.get_agent_npc_automation_difficulty(new) == 3


# Six 2×2 rooms on the 12×12 grid, each its own room in walk order.
_ROOMS = [{"path_index": i, "cells": [[c + dc, r + dr] for dc in (0, 1) for dr in (0, 1)]}
          for i, (c, r) in enumerate([(0, 0), (4, 0), (8, 0), (0, 6), (4, 6), (8, 6)])]


def _build(groups, boss=True, seed=7):
    app = App(MAP_PATH, seed=12345)
    bestiary = eg.Bestiary(data_dir=GUI_DIR)
    return eg.build_dungeon(
        app.bm, rpg, {"rooms": _ROOMS}, bestiary, cr=3,
        difficulty_start="Easy", difficulty_end="Hard", min_room=1, boss=boss,
        entrance=None, automation_level=4, rng=random.Random(seed), place=False,
        groups=groups, reserve_entrance=True)


def _populated(results):
    return [r["room"] for r in results if r["requested"]]


def test_groups_caps_populated_rooms():
    for seed in range(5):
        rooms, results, _ = _build(2, boss=False, seed=seed)
        assert len(results) == len(rooms) == 6
        pop = _populated(results)
        assert len(pop) == 2, pop
        assert 0 not in pop, pop


def test_groups_keeps_the_boss():
    for seed in range(5):
        _, results, _ = _build(2, boss=True, seed=seed)
        assert results[-1]["is_boss"] and results[-1]["requested"]
        assert len(_populated(results)) == 2


def test_groups_unset_is_every_room():
    for groups in (None, 0, 5, 50):
        _, results, _ = _build(groups)
        assert all(r["requested"] for r in results), groups


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"{len(tests)} passed")
