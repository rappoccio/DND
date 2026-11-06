#!/usr/bin/env python3
"""Release and Reset Dungeon in the App: step 3 of plans/DUNGEON_RELEASES_PLAN.md (D2–D4, D10).

  · a release saves the live board first and is refused during a fight;
  · a reset puts back creatures, fog, doors and effects, and keeps map fixes;
  · it ends a live fight without awarding XP and removes the combat sidecar;
  · it returns to the release's map and does not write back the map it left;
  · what blocks a restore blocks a reset, and a refusal changes nothing;
  · a released creature on a cell a map fix has blocked is named;
  · seated players are resynced, and the menu rows reach all of it;
  · outside a campaign the actions say so.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile
from unittest import mock

import pygame
import rpg_battle_map as rpg

import releases
import run_control
import run_state as rs
import save_layout as sl
from main import App
from menus import dm
from test_campaign_open import _campaign, _names, _open, _place, _run
from test_helpers import TEST_MAP_PATH

PC_FACTION, FOE_FACTION = 0, 1


class _Scene:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="dungeon_reset_")
        self.camp, self.dl = _campaign(self.tmp)
        self.app = _open(self.camp.root)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp)


def _idx(app, name):
    return next(i for i, pt in enumerate(app.bm.placed_agents) if pt.name == name)


def _released_board(s):
    """Aria on hall with the door shut and no fog cleared, released as V0."""
    _place(s.app, "Aria", 1, 1)
    r = run_control.make_release(s.app)
    assert r is not None and r.name == "V0", s.app._status_msg
    return r


def _start_fight(app):
    _place(app, "Gnasher", 8, 1)
    app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
    app.bm.set_agent_faction(_idx(app, "Gnasher"), FOE_FACTION)
    app._start_combat()
    assert app.combat_active


def test_release_saves_the_board_and_refuses_a_fight():
    with _Scene() as s:
        r = _released_board(s)
        assert [a["name"] for a in rs.creatures(r.start_run(), "hall")["agents"]] == ["Aria"], \
            "the release did not save the live board"
        assert s.app._status_msg == "Released V0"
        _start_fight(s.app)
        assert run_control.make_release(s.app) is None
        assert "Finish combat" in s.app._status_msg
        assert releases.next_name(s.dl) == "V1", "a release was made during a fight"
    print("  ✅ a release saves the board first and is refused during a fight")


def test_reset_restores_play_state():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        _place(app, "Gnasher", 8, 1)
        stats = app.combat.get_agent_stats(app.bm, _idx(app, "Aria"))
        hp = stats.hp_cur
        stats.hp_cur = hp + 7
        app.combat.set_agent_stats(app.bm, _idx(app, "Aria"), stats)
        app.bm.open_door(app.bm.doors[0].id)
        effects = os.path.join(s.dl.effects_dir(), "hall.json")
        os.makedirs(os.path.dirname(effects))
        with open(effects, "w") as f:
            json.dump({}, f)
        app._save_agents()
        app._save_terrain()

        assert run_control.reset_to(app, r), app._status_msg
        assert _names(app) == ["Aria"]
        assert app.combat.get_agent_stats(app.bm, 0).hp_cur == hp, "HP was not restored"
        assert not app.bm.doors[0].open, "the door stayed open"
        assert not os.path.exists(effects), "a later effects file survived"
        assert _run(s.dl)["maps"]["hall"]["agents"][0]["name"] == "Aria"
        assert len(_run(s.dl)["maps"]["hall"]["agents"]) == 1

        # Reloading from disk gives the same board.
        again = _open(s.dl.root)
        assert _names(again) == ["Aria"] and not again.bm.doors[0].open
    print("  ✅ a reset puts creatures, HP, doors and effects back, on disk too")


def test_reset_clears_fog():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        before = sorted((c.col, c.row) for c in app.bm.explored_cells())
        app._save_terrain()
        run = _run(s.dl)
        rs.map_section(run, "hall")["state"]["explored"] = [[5, 5], [6, 6]]
        rs.save_run(s.dl.run_path(), run)
        s.app.store.run = run
        app._load_terrain()
        assert (5, 5) in {(c.col, c.row) for c in app.bm.explored_cells()}

        assert run_control.reset_to(app, r), app._status_msg
        assert sorted((c.col, c.row) for c in app.bm.explored_cells()) == before
    print("  ✅ a reset puts the fog back")


def test_reset_keeps_map_fixes():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        app.bm.add_door(cells=[rpg.Cell(7, 2)])
        app._walls_enabled = True
        app._save_terrain()
        path = s.dl.write_path("hall", sl.MAP_FILE)
        with open(path) as f:
            fixed = f.read()
        manifest_mtime = os.path.getmtime(s.dl.manifest_path)

        assert run_control.reset_to(app, r), app._status_msg
        assert app._walls_enabled is True, "a map fix was rolled back"
        assert sorted(d.cell.col for d in app.bm.doors) == [4, 7], "a door fix was rolled back"
        with open(path) as f:
            assert f.read() == fixed, "a reset rewrote map.json"
        assert os.path.getmtime(s.dl.manifest_path) == manifest_mtime, "rewrote dungeon.json"
        app._save_terrain()
        with open(path) as f:
            assert len(json.load(f)["doors"]) == 2, "the next save lost the door fix"
    print("  ✅ a reset keeps map fixes, and writes no design file")


def test_reset_ends_a_fight_without_xp():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        _start_fight(app)
        app._save_combat_state()
        combat = s.dl.combat_path()
        assert os.path.exists(combat)
        with mock.patch.object(app, "_award_encounter_xp") as award:
            assert run_control.reset_to(app, r), app._status_msg
        assert not award.called, "a thrown-away fight awarded XP"
        assert not app.combat_active and app.initiative_order == [] and app._npc_drive_idx == -1
        assert not os.path.exists(combat), "the combat sidecar survived"
        assert _names(app) == ["Aria"]
        _start_fight(app)                   # the next fight starts cleanly
    print("  ✅ a reset ends a live fight, awards no XP and removes the sidecar")


def test_reset_returns_to_the_released_map():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        assert app._switch_to_page(app.dungeon.page_by_id("tower"))
        _place(app, "Bat", 2, 2)            # never saved: must not be written back

        assert run_control.reset_to(app, r), app._status_msg
        assert app.dungeon_page.id == "hall" and _names(app) == ["Aria"]
        run = _run(s.dl)
        assert run["current_map"] == "hall"
        assert not run["maps"].get("tower", {}).get("agents"), "the map left was written back"
        assert app._switch_to_page(app.dungeon.page_by_id("tower"))
        assert _names(app) == [], "the tower kept play from after the release"
    print("  ✅ a reset returns to the release's map; the map it left is not written back")


def test_empty_release_clears_the_board():
    with _Scene() as s:
        r = releases.create(s.dl)           # a run with no section for this map
        _place(s.app, "Aria", 1, 1)
        assert run_control.reset_to(s.app, r), s.app._status_msg
        assert _names(s.app) == [], "the old creatures stayed on the board"
    print("  ✅ a release with no creatures clears the board")


def test_refusals_change_nothing():
    with _Scene() as s:
        app = s.app
        run_control.ask_reset(app)
        assert app._status_msg == "Make a Release first."
        assert app.prompts.live is None

        r = _released_board(s)
        _place(app, "Gnasher", 8, 1)
        app._legendary_queue = [1]
        assert not run_control.reset_to(app, r)
        assert "legendary" in app._status_msg
        assert _names(app) == ["Aria", "Gnasher"]
        app._legendary_queue = []

        os.remove(r.start_run_path)
        assert not run_control.reset_to(app, r)
        assert "unreadable" in app._status_msg
        assert _names(app) == ["Aria", "Gnasher"]
    print("  ✅ no release, a blocked state or an unreadable release change nothing")


def test_blocked_creature_is_named():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        app.bm.add_door(cells=[rpg.Cell(1, 1)])      # the map fix lands on Aria's cell
        app._save_terrain()
        assert run_control.reset_to(app, r), app._status_msg
        assert _names(app) == []
        assert "Aria" in app._status_msg and "Blocked" in app._status_msg, app._status_msg
    print("  ✅ a released creature on a newly blocked cell is named")


def test_seats_stay_and_players_resync():
    with _Scene() as s:
        app = s.app
        r = _released_board(s)
        code = app.roster.join_code
        with mock.patch.object(app.events, "resync_all") as resync:
            assert run_control.reset_to(app, r), app._status_msg
        assert resync.called, "seated players were not resynced"
        assert app.roster.join_code == code
        assert app._net_turn is None
        assert app.session_log.tail(True)[-1]["text"] == "The DM reset the dungeon to V0."
    print("  ✅ seats stay and every player gets a fresh view")


def test_menu_rows():
    with _Scene() as s:
        app = s.app
        _place(app, "Aria", 1, 1)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Release").ok
        assert releases.next_name(s.dl) == "V1"
        _place(app, "Gnasher", 8, 1)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Release").ok      # V1 has both

        # Reset Dungeon goes to the newest, after a confirm that can be cancelled.
        _place(app, "Bat", 2, 2)
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Reset Dungeon").ok
        assert app.prompts.live.title == "Reset the dungeon to V1?"
        assert app.prompts.choose_label("Cancel").ok
        assert _names(app) == ["Aria", "Bat", "Gnasher"]

        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Reset Dungeon").ok
        assert app.prompts.choose_label("Reset to V1").ok
        assert _names(app) == ["Aria", "Gnasher"]

        # Releases… reaches an older one.
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("Releases…").ok
        labels = [o.label for o in app.prompts.live.options]
        assert labels[0].startswith("V1") and labels[1].startswith("V0"), labels
        assert app.prompts.choose_label(labels[1]).ok
        assert app.prompts.choose_label("Reset to V0").ok
        assert _names(app) == ["Aria"]
    print("  ✅ the Dungeon menu reaches Release, Releases… and Reset Dungeon")


def test_outside_a_campaign():
    app = App(TEST_MAP_PATH, seed=1)
    for act in (run_control.make_release, run_control.ask_reset,
                run_control.show_releases_menu):
        app._status_msg = ""
        act(app)
        assert "campaign" in app._status_msg, act
    print("  ✅ outside a campaign the actions say so")


def main():
    pygame.init()
    tests = [test_release_saves_the_board_and_refuses_a_fight, test_reset_restores_play_state,
             test_reset_clears_fog, test_reset_keeps_map_fixes,
             test_reset_ends_a_fight_without_xp, test_reset_returns_to_the_released_map,
             test_empty_release_clears_the_board, test_refusals_change_nothing,
             test_blocked_creature_is_named, test_seats_stay_and_players_resync,
             test_menu_rows, test_outside_a_campaign]
    print("Running dungeon reset tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} dungeon reset tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
