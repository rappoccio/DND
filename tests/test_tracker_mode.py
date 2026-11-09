#!/usr/bin/env python3
"""Initiative tracker mode, step T1: the flag and the gate
(plans/INITIATIVE_TRACKER_PLAN.md).

  · with tracker mode on, an automated NPC's turn never runs;
  · the combat panel offers and draws no action rows, only the DM's session tools;
  · Begin Combat reads Begin Encounter;
  · the toggle is refused mid-combat;
  · the player server goes down on the way in and comes back on the way out, and only
    if the toggle stopped it.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import shutil
import tempfile

from constants import PC_FACTION
from main import App
from menus import dm
from net import link as net_link
from widgets import Button
from test_restore_oracle import MAP_PATH, SEED, FOE_FACTION, _place, _idx

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print(f"  ✗ {msg}")


def _board(tmp, *, tracker):
    """Two PCs and two foes, one of them automated; tracker mode set before the fight."""
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "tracker_agents.json"))
    for name, col, row in (("Aria", 2, 3), ("Brannor", 2, 5),
                           ("Gnasher", 8, 3), ("Skarn", 8, 8)):
        _place(app, name, col, row)
    app.combat.apply_agent_configs(app.bm)
    for name in ("Aria", "Brannor"):
        app.bm.set_agent_faction(_idx(app, name), PC_FACTION)
    for name in ("Gnasher", "Skarn"):
        app.bm.set_agent_faction(_idx(app, name), FOE_FACTION)
    app.bm.set_agent_npc_automated(_idx(app, "Gnasher"), True)
    if tracker:
        assert dm.set_tracker_mode(app, True)
    # T3 builds Begin Encounter; until then the gate is tested on an engine-rolled order.
    app._begin_combat()
    return app


def _to_turn_of(app, idx):
    for _ in range(2 * len(app.initiative_order) + 2):
        if app._current_agent_idx() == idx:
            return
        app._advance_turn()
    raise AssertionError("never reached the wanted turn")


def test_no_npc_turn():
    tmp = tempfile.mkdtemp()
    try:
        # The control: outside tracker mode the automated NPC's turn arms the drive.
        app = _board(tmp, tracker=False)
        gnasher = _idx(app, "Gnasher")
        _to_turn_of(app, gnasher)
        check(app._npc_drive_idx == gnasher, "control: the NPC drive was not armed")

        app = _board(tmp, tracker=True)
        gnasher = _idx(app, "Gnasher")
        _to_turn_of(app, gnasher)
        check(app._npc_drive_idx == -1, "tracker mode armed the NPC drive")
        # Armed anyway (the NPC automation dialog can set it): the drive still refuses.
        app._npc_drive_idx = gnasher
        turn = (app.round_num, app.turn_idx)
        app._drive_npc_turn_if_pending()
        check(app._npc_anim is None, "tracker mode played an NPC turn")
        check((app.round_num, app.turn_idx) == turn, "tracker mode advanced past the NPC")
        print("✅ test_no_npc_turn")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_action_rows():
    tmp = tempfile.mkdtemp()
    drawn = []
    real_draw = Button.draw

    def _hook(self, *a, **k):
        drawn.append(self.text)
        return real_draw(self, *a, **k)

    Button.draw = _hook
    try:
        app = _board(tmp, tracker=False)
        app._draw_combat_panel()
        check("end_turn" in app._action_menu, "control: no End Turn outside tracker mode")
        check("End Turn" in drawn, "control: End Turn not drawn outside tracker mode")

        app = _board(tmp, tracker=True)
        for idx in range(len(app.initiative_order)):     # every combatant's turn
            drawn.clear()
            app._draw_combat_panel()
            groups = {a.group for a in app._action_menu.values()}
            check(groups <= {"session"}, f"tracker mode offered {sorted(groups)}")
            check("End Combat" in drawn, "tracker mode lost End Combat")
            for label in ("End Turn", "Attack", "Dash", "Hide Terrain", "Show Terrain"):
                check(label not in drawn, f"tracker mode drew {label}")
            app._advance_turn()
        print("✅ test_no_action_rows")
    finally:
        Button.draw = real_draw
        shutil.rmtree(tmp, ignore_errors=True)


def test_begin_button_label():
    tmp = tempfile.mkdtemp()
    try:
        app = App(MAP_PATH, seed=SEED)
        app._set_encounter_base(os.path.join(tmp, "tracker_agents.json"))
        _place(app, "Aria", 2, 3)
        app.combat.apply_agent_configs(app.bm)
        app._draw_panel()
        check(app.btn_begin_combat.text == "Begin Combat", "label outside tracker mode")
        dm.set_tracker_mode(app, True)
        app._draw_panel()
        check(app.btn_begin_combat.text == "Begin Encounter", "label in tracker mode")
        app._begin_encounter()                            # T3's; today a status line
        check(not app.combat_active, "Begin Encounter started an engine fight")
        print("✅ test_begin_button_label")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_toggle_refused_mid_combat():
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=False)
        check(app.combat_active, "the fight did not start")
        check(not dm.set_tracker_mode(app, True), "the toggle was allowed mid-combat")
        check(not app.tracker_mode, "tracker mode turned on mid-combat")

        app = _board(tmp, tracker=True)
        check(not dm.set_tracker_mode(app, False), "the toggle off was allowed mid-combat")
        check(app.tracker_mode, "tracker mode turned off mid-combat")
        app._end_combat(award_xp=False)
        check(dm.set_tracker_mode(app, False), "the toggle off was refused out of combat")
        check(not app.tracker_mode, "tracker mode stayed on")
        print("✅ test_toggle_refused_mid_combat")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_mirror():
    """T2: _mirror_tracker copies the typed-in order into initiative_order / turn_idx /
    round_num, so the existing drawing and _current_agent_idx follow the tracker."""
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=True)
        a, b, g, s = (_idx(app, n) for n in ("Aria", "Brannor", "Gnasher", "Skarn"))
        t = app.tracker
        t.add([a, b, g, s])
        for idx, tot in ((a, 11), (b, None), (g, 17), (s, 11)):
            t.set_total(idx, tot)
        t.start()
        t.next()
        app._mirror_tracker()
        check([e.agent_idx for e in app.initiative_order] == [g, a, s, b],
              f"mirrored order {[e.agent_idx for e in app.initiative_order]}")
        check([e.total for e in app.initiative_order] == [17, 11, 11, 0], "mirrored totals")
        check(app._current_agent_idx() == a, "the acting agent did not follow the tracker")
        check(app.round_num == 0, f"round_num {app.round_num} for round 1")

        t.remove(a)                         # the acting entry leaves: the next one shows
        app._mirror_tracker()
        check(a not in [e.agent_idx for e in app.initiative_order], "removed entry mirrored")
        check(app._current_agent_idx() == s, "turn after removing the acting entry")
        for _ in range(3):                  # Skarn, Brannor, then round 2's Gnasher
            t.next()
        app._mirror_tracker()
        check(app._current_agent_idx() == g and app.round_num == 1, "wrap to round 2")
        app._draw_combat_panel()            # the existing drawing takes the mirrored order
        print("✅ test_mirror")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _FakeServer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_player_server_gate():
    """No joins in tracker mode: the server stops. It restarts on the way out only if the
    toggle stopped it, so a headless App never binds 6081 here."""
    app = App(MAP_PATH, seed=SEED)
    started = []
    real_start = net_link.start_player_server
    net_link.start_player_server = lambda a: started.append(a)
    try:
        dm.set_tracker_mode(app, True)
        dm.set_tracker_mode(app, False)
        check(not started, "a never-running server was started")

        fake = _FakeServer()
        app._net = fake
        dm.set_tracker_mode(app, True)
        check(fake.stopped and app._net is None, "the server kept running in tracker mode")
        dm.set_tracker_mode(app, False)
        check(started == [app], "the server did not come back")
        print("✅ test_player_server_gate")
    finally:
        net_link.start_player_server = real_start


if __name__ == "__main__":
    test_no_npc_turn()
    test_no_action_rows()
    test_begin_button_label()
    test_toggle_refused_mid_combat()
    test_mirror()
    test_player_server_gate()
    if FAILURES:
        print(f"\n❌ {len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nAll tracker-mode tests passed.")
