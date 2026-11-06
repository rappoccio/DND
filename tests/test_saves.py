#!/usr/bin/env python3
"""Save files: step 4 of plans/DUNGEON_RELEASES_PLAN.md (D5–D8).

  · every turn start writes a save, under the autosave switch, in a campaign only;
  · turn saves past the limit are pruned, oldest first; manual ones stay and do not count;
  · writing a save never touches the run or scene files;
  · a load lands on the save's exact fingerprint, on any map;
  · a load keeps map fixes: live, in the resumed fight and on disk;
  · a load with no fight in it ends the live fight without XP;
  · a mid-turn Save Game keeps the turn's action economy;
  · a refusal changes nothing; a lost index or a bad file is not fatal;
  · the turn hook's failure never reaches the turn;
  · the picker shows saved games, then fight ▸ round ▸ turn;
  · a reset writes a before-reset save first, so it can be undone.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
# The runner turns the turn saves off for every suite; this one is about them.
os.environ["RPG_AUTOSAVE"] = "1"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile
from unittest import mock

import pygame
import rpg_battle_map as rpg

import run_control
import saves
import save_layout as sl
from main import App
from menus import dm
from net.roster import SessionRoster
from test_autosave_design import EDIT_CELL, EDIT_REGION
from test_autosave_restore import _without_door_ids
from test_campaign_open import _campaign, _names, _open, _place, _run
from test_helpers import TEST_MAP_PATH
from test_restore_oracle import _report, diff, fingerprint

PC_FACTION, FOE_FACTION = 0, 1


class _Scene:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="saves_")
        self.camp, self.dl = _campaign(self.tmp)
        self.app = _open(self.camp.root)
        self.dir = self.dl.saves_dir()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp)


def _idx(app, name):
    return next(i for i, pt in enumerate(app.bm.placed_agents) if pt.name == name)


def _fight(app):
    _place(app, "Aria", 1, 1)
    _place(app, "Gnasher", 8, 1)
    app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
    app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
    app._start_combat()
    assert app.combat_active


def _hurt(app, name, by=3):
    i = _idx(app, name)
    s = app.combat.get_agent_stats(app.bm, i)
    s.hp_cur = max(1, s.hp_cur - by)
    app.combat.set_agent_stats(app.bm, i, s)
    return s.hp_cur


def _map_doc(dl):
    with open(dl.resolve("hall", sl.MAP_FILE)) as f:
        return json.load(f)


def test_turn_start_writes_a_save():
    with _Scene() as s:
        app = s.app
        assert saves.list_saves(s.dir) == []
        _fight(app)
        first = saves.list_saves(s.dir)
        assert len(first) == 1
        m = first[0]
        assert m["kind"] == saves.TURN and m["map"] == "hall" and m["fight"] is not None
        assert m["actor"] == app.bm.placed_agents[app._current_agent_idx()].name
        assert (m["round"], m["turn_idx"]) == (app.round_num, app.turn_idx)
        app._advance_turn()
        second = saves.list_saves(s.dir)
        assert [x["seq"] for x in second] == [2, 1] and second[0]["fight"] == m["fight"]

        app.autosave_enabled = False
        app._advance_turn()
        assert len(saves.list_saves(s.dir)) == 2, "a disabled hook still wrote"
    print("  ✅ a turn start writes a save, under the switch")


def test_only_in_a_campaign():
    app = App(TEST_MAP_PATH, seed=1)
    assert saves.save_turn(app) is None
    assert saves.save_game(app) is None and "campaign" in app._status_msg
    app._status_msg = ""
    assert not saves.load(app, 1) and "campaign" in app._status_msg
    print("  ✅ outside a campaign there are no save files")


def test_limit_and_pruning():
    with _Scene() as s:
        app = s.app
        assert app.roster.save_limit == 10, "the default limit is 10"
        app.roster.save_limit = 3
        _fight(app)
        manual = saves.save_game(app)
        for _ in range(5):
            app._advance_turn()
        metas = saves.list_saves(s.dir)
        turns = [m for m in metas if m["kind"] == saves.TURN]
        assert len(turns) == 3, [m["seq"] for m in turns]
        assert turns[0]["seq"] == max(m["seq"] for m in metas), "the newest was pruned"
        assert manual["seq"] in [m["seq"] for m in metas], "a manual save was pruned"
        files = [f for f in os.listdir(s.dir) if f.endswith(saves.SAVE_EXT)]
        assert len(files) == 4, files

        # Lowering the limit prunes on the next write.
        app.roster.save_limit = 1
        app._advance_turn()
        metas = saves.list_saves(s.dir)
        assert sorted(m["kind"] for m in metas) == [saves.MANUAL, saves.TURN]
    print("  ✅ turn saves stop at the limit; manual saves stay and do not count")


def test_limit_setting():
    r = SessionRoster()
    assert r.save_limit == 10
    assert SessionRoster.from_dict({**r.to_dict(), "save_limit": 25}).save_limit == 25
    assert SessionRoster.from_dict(r.to_dict()).save_limit == 10
    doc = r.to_dict()
    del doc["save_limit"]
    assert SessionRoster.from_dict(doc).save_limit == 10, "an old session.json"
    assert SessionRoster(save_limit=0).save_limit == 1
    assert SessionRoster(save_limit="many").save_limit == 10
    print("  ✅ the limit persists, defaults to 10 and is clamped")


def test_scene_files_untouched():
    with _Scene() as s:
        app = s.app
        _fight(app)
        app._save_agents()
        app._save_terrain()
        with open(s.dl.run_path(), "rb") as f:
            run_before = f.read()
        with open(s.dl.combat_path(), "rb") as f:
            combat_before = f.read()
        _hurt(app, "Aria")
        saves.save_game(app)
        with open(s.dl.run_path(), "rb") as f:
            assert f.read() == run_before, "a save wrote the run"
        with open(s.dl.combat_path(), "rb") as f:
            assert f.read() == combat_before, "a save wrote the combat sidecar"
        assert not os.path.exists(s.dl.write_path("hall", sl.MAP_FILE)), "a save wrote map.json"
    print("  ✅ writing a save touches no run or scene file")


def test_load_lands_on_the_fingerprint():
    with _Scene() as s:
        app = s.app
        _fight(app)
        app._advance_turn()
        saved = saves.list_saves(s.dir)[0]
        want = _without_door_ids(fingerprint(app))

        _hurt(app, "Aria")
        app._advance_turn()
        app._advance_turn()
        assert saves.load(app, saved["seq"]), app._status_msg
        gaps = diff(want, _without_door_ids(fingerprint(app)))
        if gaps:
            _report(gaps)
        assert not gaps, f"{len(gaps)} fields did not survive"
        assert app.combat_active and app._fight_started == saved["fight"]
        # What is on disk agrees, so a relaunch resumes the same fight.
        again = _open(s.dl.root)
        again._load_combat_state()
        assert again.combat_active and again.round_num == saved["round"]
    print("  ✅ a load lands on the save's exact fingerprint, and on disk")


def test_load_returns_to_another_map():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        assert app._switch_to_page(app.dungeon.page_by_id("tower"))
        _place(app, "Bat", 2, 2)
        saved = saves.save_game(app)
        assert saved["map"] == "tower"

        assert app._switch_to_page(app.dungeon.page_by_id("hall"))
        _place(app, "Gnasher", 8, 1)
        app._save_agents()
        assert saves.load(app, saved["seq"]), app._status_msg
        assert app.dungeon_page.id == "tower" and _names(app) == ["Bat"]
        run = _run(s.dl)
        assert run["current_map"] == "tower"
        assert [a["name"] for a in run["maps"]["hall"]["agents"]] == ["Aria"], \
            "the other map's section is not the save's"
    print("  ✅ a save holds every map, and a load returns to the save's map")


def test_load_keeps_map_fixes():
    with _Scene() as s:
        app = s.app
        _fight(app)
        saved = saves.list_saves(s.dir)[0]
        app.bm.add_door(cells=[rpg.Cell(7, 2)])
        app._terrain_regions.append(dict(EDIT_REGION))
        app._save_terrain()
        fixed = _map_doc(s.dl)

        assert saves.load(app, saved["seq"]), app._status_msg
        assert app.combat_active
        assert app.bm.is_blocked(rpg.Cell(*EDIT_CELL), 1), "the resumed fight lost the wall fix"
        assert len(app.bm.doors) == 2, "the load lost the door fix"
        assert _map_doc(s.dl) == fixed, "the load rewrote map.json"
        app._save_terrain()
        assert _map_doc(s.dl) == fixed, "the next save rewrote map.json"
    print("  ✅ a load keeps map fixes, live, in the fight and on disk")


def test_load_with_no_fight_ends_the_live_one():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        saved = saves.save_game(app)
        assert saved["actor"] == "" and saved["fight"] is None
        _place(app, "Gnasher", 8, 1)
        app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
        app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
        app._start_combat()
        with mock.patch.object(app, "_award_encounter_xp") as award:
            assert saves.load(app, saved["seq"]), app._status_msg
        assert not award.called and not app.combat_active
        assert _names(app) == ["Aria"]
        assert not os.path.exists(s.dl.combat_path()), "the combat sidecar survived"
    print("  ✅ a save with no fight ends the live fight without XP")


def test_mid_turn_economy():
    with _Scene() as s:
        app = s.app
        _fight(app)
        app.action_used = True
        app.attacks_remaining = 1
        saved = saves.save_game(app)
        app._advance_turn()
        assert not app.action_used
        assert saves.load(app, saved["seq"]), app._status_msg
        assert app.action_used and app.attacks_remaining == 1 and not app.bonus_used
    print("  ✅ a mid-turn Save Game keeps the turn's action economy")


def test_refusals_change_nothing():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        saved = saves.save_game(app)
        _place(app, "Gnasher", 8, 1)
        path = saves._save_path(s.dir, saved["seq"])

        app._legendary_queue = [1]
        assert saves.save_game(app) is None and "legendary" in app._status_msg
        assert not saves.load(app, saved["seq"]) and "legendary" in app._status_msg
        app._legendary_queue = []

        assert not saves.load(app, 999) and "unreadable" in app._status_msg

        doc = saves._read_doc(path)
        doc["meta"]["map"] = "gone"
        saves._write_doc(path, doc)
        assert not saves.load(app, saved["seq"]) and "gone" in app._status_msg

        doc["meta"]["map"] = "hall"
        doc["combat"] = {"agent_basis": ["Somebody"], "initiative_order": [{}]}
        saves._write_doc(path, doc)
        assert not saves.load(app, saved["seq"]) and "disagree" in app._status_msg

        doc["version"] = 99
        saves._write_doc(path, doc)
        assert not saves.load(app, saved["seq"]) and "newer" in app._status_msg

        with open(path, "wb") as f:
            f.write(b"\x1f\x8b trunc")
        assert not saves.load(app, saved["seq"]) and "unreadable" in app._status_msg
        assert _names(app) == ["Aria", "Gnasher"], "a refusal changed the board"
    print("  ✅ a refused load or save changes nothing")


def test_index_is_only_a_cache():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        a = saves.save_game(app)
        b = saves.save_game(app)
        index = os.path.join(s.dir, saves.INDEX_FILE)

        os.remove(index)
        assert [m["seq"] for m in saves.list_saves(s.dir)] == [b["seq"], a["seq"]]
        assert os.path.exists(index), "the index was not rebuilt"

        with open(index, "a") as f:
            f.write('{"seq": 2, "kin')                       # a torn last line
        assert len(saves.list_saves(s.dir)) == 2

        os.remove(saves._save_path(s.dir, a["seq"]))         # an entry with no file
        assert [m["seq"] for m in saves.list_saves(s.dir)] == [b["seq"]]

        with open(saves._save_path(s.dir, 50), "wb") as f:   # a file nothing can read
            f.write(b"junk")
        assert [m["seq"] for m in saves.list_saves(s.dir)] == [b["seq"]]
        with open(os.path.join(s.dir, ".000060.save.json.gz.tmp.1"), "wb") as f:
            f.write(b"junk")                                 # a crash's temp file
        assert [m["seq"] for m in saves.list_saves(s.dir)] == [b["seq"]]
    print("  ✅ a lost or torn index, a missing file and a bad file are not fatal")


def test_turn_hook_never_raises():
    with _Scene() as s:
        app = s.app
        _fight(app)
        with mock.patch.object(saves, "write", side_effect=RuntimeError("disk gone")):
            assert saves.save_turn(app) is None
            app._advance_turn()
        assert app.combat_active
    print("  ✅ a failed turn save never reaches the turn")


def test_save_game_row():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Save Game").ok
        assert [m["kind"] for m in saves.list_saves(s.dir)] == [saves.MANUAL]
        assert app._status_msg.startswith("Saved: hall")
    print("  ✅ the Dungeon menu reaches Save Game")


def test_picker_shape():
    with _Scene() as s:
        app = s.app
        app.btn_load_save = mock.Mock(rect=pygame.Rect(0, 0, 10, 10))
        dm.show_load_save_menu(app)
        assert app._status_msg == "No saves yet." and app.prompts.live is None

        _place(app, "Aria", 1, 1)
        kept = saves.save_game(app)
        _place(app, "Gnasher", 8, 1)
        app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
        app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
        app._start_combat()
        for _ in range(3):
            app._advance_turn()              # one fight, into a second round
        app._end_combat()
        app._start_combat()                  # a second fight

        dm.show_load_save_menu(app)
        rows = [o.label for o in app.prompts.live.options]
        assert rows[0] == "Saved games (1) ▸", rows
        assert len(rows) == 3, rows
        assert rows[1].endswith("· 1 turn ▸"), rows      # the newest fight first
        assert rows[2].endswith("· 4 turns ▸"), rows

        assert app.prompts.choose_label(rows[2]).ok
        rounds = [o.label for o in app.prompts.live.options]
        assert rounds == ["Round 2 ▸", "Round 1 ▸"], rounds
        assert app.prompts.choose_label("Round 1 ▸").ok
        turns = [o.label for o in app.prompts.live.options]
        assert len(turns) == 2 and any(t.startswith("Gnasher · ") for t in turns), turns

        # A turn row loads that turn.
        assert app.prompts.choose_label(turns[0]).ok
        assert app.combat_active and app.round_num == 0

        # Saved games loads the out-of-combat board.
        dm.show_load_save_menu(app)
        assert app.prompts.choose_label("Saved games (1) ▸").ok
        assert app.prompts.choose_label(saves.label(kept)).ok
        assert not app.combat_active and _names(app) == ["Aria"]
    print("  ✅ the picker goes saved games, then fight ▸ round ▸ turn, newest first")


def test_reset_can_be_undone():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        release = run_control.make_release(app)
        _place(app, "Gnasher", 8, 1)
        assert run_control.reset_to(app, release), app._status_msg
        assert _names(app) == ["Aria"]

        metas = saves.list_saves(s.dir)
        assert [m["kind"] for m in metas] == [saves.BEFORE_RESET]
        assert saves.label(metas[0]).startswith("before reset · hall")
        assert saves.load(app, metas[0]["seq"]), app._status_msg
        assert _names(app) == ["Aria", "Gnasher"], "the reset could not be undone"

        # Mid-fight too.
        app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
        app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
        app._start_combat()
        turn = (app.round_num, app.turn_idx)
        assert run_control.reset_to(app, release), app._status_msg
        assert not app.combat_active
        undo = saves.list_saves(s.dir)
        undo = next(m for m in undo if m["kind"] == saves.BEFORE_RESET)
        assert saves.load(app, undo["seq"]), app._status_msg
        assert app.combat_active and (app.round_num, app.turn_idx) == turn

        # With no way back there is no reset.
        with mock.patch.object(saves, "write", side_effect=OSError("disk full")):
            assert not run_control.reset_to(app, release)
        assert "could not save" in app._status_msg and app.combat_active
    print("  ✅ a reset can be undone from its before-reset save, or does not happen")


def main():
    pygame.init()
    tests = [test_turn_start_writes_a_save, test_only_in_a_campaign, test_limit_and_pruning,
             test_limit_setting, test_scene_files_untouched, test_load_lands_on_the_fingerprint,
             test_load_returns_to_another_map, test_load_keeps_map_fixes,
             test_load_with_no_fight_ends_the_live_one, test_mid_turn_economy,
             test_refusals_change_nothing, test_index_is_only_a_cache,
             test_turn_hook_never_raises, test_save_game_row, test_picker_shape,
             test_reset_can_be_undone]
    print("Running save file tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} save file tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
