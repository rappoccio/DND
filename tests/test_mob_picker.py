#!/usr/bin/env python3
"""Generate Dungeon's mob picker, and the allow-list + named boss behind it.

Generator:
  · nothing chosen generates what it always did            (test_no_choice_changes_nothing)
  · only ticked mobs appear, ranged/AoE slots included     (test_only_allowed_mobs_appear)
  · the named boss is the boss, in the last room only      (test_named_boss_is_the_boss)
  · a boss from above the band still works                 (test_boss_may_be_out_of_band)
  · a boss too big for its room is reported                (test_boss_that_does_not_fit_is_reported)
  · the list covers the band, under the filters            (test_candidates_cover_the_band)
  · a band with no match falls back to the nearest CR      (test_candidates_fall_back_to_nearest)
  · every bestiary record renders a preview                (test_every_mob_previews)

Picker, driven by synthesized clicks:
  · untouched, it asks for no restriction                  (test_untouched_picker_restricts_nothing)
  · clicking a row unticks; the star makes a boss          (test_untick_and_star)
  · None then a search then All keeps just those           (test_none_search_all)
  · an out-of-band row can be boss but cannot be ticked    (test_all_crs_rows_are_boss_only)
  · Generate refuses an empty list                         (test_generate_refuses_empty_list)
  · Back returns None and keeps the choices                (test_back_keeps_choices)
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

import pygame

import rpg_battle_map as rpg
import encounter_generator as eg
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
GUI_DIR = os.path.join(_ROOT, "gui")
BESTIARY = eg.Bestiary(data_dir=GUI_DIR)

# Six 3×3 rooms on the 12×12 grid, each its own room in walk order.
_ROOMS = [{"path_index": i, "cells": [[c + dc, r + dr] for dc in range(3) for dr in range(3)]}
          for i, (c, r) in enumerate([(0, 0), (4, 0), (8, 0), (0, 6), (4, 6), (8, 6)])]

_APP = App(MAP_PATH, seed=12345)


def _build(seed=7, cr=5, place=False, **kw):
    return eg.build_dungeon(
        _APP.bm, rpg, {"rooms": _ROOMS}, BESTIARY, cr=cr,
        difficulty_start="Easy", difficulty_end="Hard", min_room=1, boss=True,
        entrance=None, automation_level=4, rng=random.Random(seed), place=place, **kw)


def _names(results, skip_boss_room=False):
    rows = results[:-1] if skip_boss_room else results
    return [a["name"] for r in rows for a in r["agents"]]


# ── Generator ────────────────────────────────────────────────────────────────

def test_no_choice_changes_nothing():
    _, plain, _ = _build()
    _, explicit, _ = _build(allowed=None, boss_name=None)
    assert _names(plain) == _names(explicit)


def test_only_allowed_mobs_appear():
    allowed = ["Goblin Warrior", "Bugbear Warrior"]
    for seed in range(5):
        _, results, _ = _build(seed=seed, allowed=allowed)
        names = set(_names(results))
        assert names and names <= set(allowed), names
        # No room came up empty because a ranged or AoE slot found nothing ticked.
        assert all(r["agents"] for r in results)


def test_named_boss_is_the_boss():
    boss = "Bugbear Warrior"
    for seed in range(5):
        _, results, _ = _build(seed=seed, allowed=["Goblin Warrior", boss], boss_name=boss)
        tagged = [a["name"] for r in results for a in r["agents"] if a.get("is_boss")]
        assert tagged == [boss], tagged
        assert boss not in _names(results, skip_boss_room=True)
        assert _names(results).count(boss) == 1


def test_boss_may_be_out_of_band():
    high = max(BESTIARY.mobs, key=lambda n: BESTIARY.mobs[n]["_cr"] or 0)
    _, results, _ = _build(cr=3, place=False, allowed=["Goblin Warrior"], boss_name=high)
    assert [a["name"] for a in results[-1]["agents"] if a.get("is_boss")] == [high]


def test_boss_that_does_not_fit_is_reported():
    huge = next(n for n, r in BESTIARY.mobs.items() if r.get("size") == "Gargantuan")
    _, results, _ = _build(place=True, allowed=["Goblin Warrior"], boss_name=huge)
    assert results[-1]["boss_dropped"]
    assert huge not in _names(results)
    # The finale still has a boss: the toughest mob that did fit.
    assert sum(1 for a in results[-1]["agents"] if a.get("is_boss")) == 1


def test_candidates_cover_the_band():
    names = BESTIARY.candidates(5)
    assert all(0 <= BESTIARY.mobs[n]["_cr"] <= 5 for n in names)
    crs = [BESTIARY.mobs[n]["_cr"] for n in names]
    assert crs == sorted(crs, reverse=True)
    assert set(BESTIARY.candidates(5, "Undead")) < set(names)
    assert len(BESTIARY.candidates(5, all_crs=True)) > len(names)


def test_candidates_fall_back_to_nearest():
    # Every Dragon in the bestiary, then a CR far below the weakest of them.
    dragons = BESTIARY.candidates(0, "Dragon", all_crs=True)
    weakest = min(BESTIARY.mobs[n]["_cr"] for n in dragons)
    assert weakest > 0
    names = BESTIARY.candidates(0, "Dragon")
    assert names and all(BESTIARY.mobs[n]["_cr"] == weakest for n in names)


def test_every_mob_previews():
    for name, rec in BESTIARY.mobs.items():
        lines = eg.mob_preview_lines(rec)
        assert lines[0].startswith("CR "), name
        assert all(isinstance(line, str) for line in lines), name


# ── The picker ───────────────────────────────────────────────────────────────

def _layout():
    return _APP._mob_picker_layout()


def _click(pos):
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))


def _row_pos(i, star=False):
    ui = _layout()
    x = ui["list"].x + 34 if star else ui["list"].x + 200
    return (x, ui["list"].y + i * ui["row_h"] + ui["row_h"] // 2)


def _type(text):
    _click(_layout()["search"].center)
    for ch in text:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0))


def _run(cr=5, excluded=None, boss=None, boss_on=True):
    """Run the queued events through the picker, ending on a queued close."""
    excluded = set() if excluded is None else excluded
    boss = [None] if boss is None else boss
    result = _APP._modal_pick_mobs(BESTIARY, cr, None, None, boss_on, excluded, boss)
    pygame.event.clear()
    return result, excluded, boss


def _generate():
    _click(_layout()["generate"].center)
    # Reached only if Generate refuses: closes the modal instead of hanging the suite.
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def test_untouched_picker_restricts_nothing():
    pygame.event.clear()
    _generate()
    result, _, _ = _run()
    assert result == {"allowed_mobs": None, "boss_mob": None}


def test_untick_and_star():
    band = BESTIARY.candidates(5)
    pygame.event.clear()
    _click(_row_pos(0))              # untick the first row
    _click(_row_pos(1, star=True))   # star the second
    _generate()
    result, excluded, boss = _run()
    assert excluded == {band[0]}
    assert result["boss_mob"] == band[1] == boss[0]
    assert band[0] not in result["allowed_mobs"]
    assert band[1] not in result["allowed_mobs"]     # the boss is never an ordinary mob
    assert band[2] in result["allowed_mobs"]


def test_none_search_all():
    pygame.event.clear()
    _click(_layout()["none"].center)
    _type("goblin")
    _click(_layout()["all"].center)
    _generate()
    result, _, _ = _run()
    expected = [n for n in BESTIARY.candidates(5)
                if "goblin" in n.lower() or "goblin" in BESTIARY.mobs[n]["meta"]["type"].lower()]
    assert expected and sorted(result["allowed_mobs"]) == sorted(expected)


def test_all_crs_rows_are_boss_only():
    everything = BESTIARY.candidates(5, all_crs=True)
    band = set(BESTIARY.candidates(5))
    top = everything[0]
    assert top not in band
    pygame.event.clear()
    _click(_layout()["crs"].center)
    _click(_row_pos(0))              # a tick here does nothing
    _click(_row_pos(0, star=True))
    _generate()
    result, excluded, _ = _run()
    assert top not in excluded
    assert result["boss_mob"] == top
    assert top not in result["allowed_mobs"]


def test_generate_refuses_empty_list():
    pygame.event.clear()
    _click(_layout()["none"].center)
    _generate()
    result, excluded, _ = _run()
    assert result is None                # the queued QUIT, not Generate, closed it
    assert excluded == set(BESTIARY.candidates(5))


def test_back_keeps_choices():
    band = BESTIARY.candidates(5)
    pygame.event.clear()
    _click(_row_pos(0))
    _click(_row_pos(1, star=True))
    _click(_layout()["back"].center)
    result, excluded, boss = _run()
    assert result is None
    assert excluded == {band[0]} and boss[0] == band[1]
    pygame.event.clear()
    _generate()
    again, _, _ = _run(excluded=excluded, boss=boss)
    assert again["boss_mob"] == band[1] and band[0] not in again["allowed_mobs"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"{len(tests)} passed")
