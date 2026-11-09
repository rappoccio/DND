#!/usr/bin/env python3
"""Initiative tracker mode, steps T1 and T3: the flag and the gate, then Begin Encounter
and the typed-in order (plans/INITIATIVE_TRACKER_PLAN.md).

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

import pygame

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


# The default typed-in totals: Gnasher, Aria, Brannor, Skarn.
TOTALS = {"Aria": 15, "Brannor": 12, "Gnasher": 18, "Skarn": 9}


def _setup(tmp, *, tracker, foes=("Gnasher", "Skarn")):
    """Two PCs and the foes (same name = one mob group), Gnasher automated; tracker mode
    set before the fight. Nothing is begun."""
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "tracker_agents.json"))
    spots = [(8, 3), (8, 8), (9, 3), (9, 8)]
    for name, (col, row) in zip(("Aria", "Brannor"), ((2, 3), (2, 5))):
        _place(app, name, col, row)
    for name, (col, row) in zip(foes, spots):
        _place(app, name, col, row)
    app.combat.apply_agent_configs(app.bm)
    for i, pt in enumerate(app.bm.placed_agents):
        app.bm.set_agent_faction(i, PC_FACTION if pt.name in ("Aria", "Brannor")
                                 else FOE_FACTION)
    if "Gnasher" in foes:
        app.bm.set_agent_npc_automated(_idx(app, "Gnasher"), True)
    if tracker:
        assert dm.set_tracker_mode(app, True)
    return app


def _board(tmp, *, tracker):
    """The fight under way: engine-rolled outside tracker mode; in it, Begin Encounter,
    TOTALS typed in, Start."""
    app = _setup(tmp, tracker=tracker)
    if not tracker:
        app._begin_combat()
        return app
    app._begin_encounter()
    for name, tot in TOTALS.items():
        app.tracker.set_total(_idx(app, name), tot)
    app._tracker_start()
    return app


def _click(app, kind, arg=None):
    """Draw the panel, then click the sheet target of `kind` (and `arg`)."""
    app._draw_combat_panel()
    for rect, k, a in app._tracker_hits:
        if k == kind and (arg is None or a == arg):
            ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)
            assert app._tracker_handle_event(ev), f"the {kind} click was not taken"
            return
    raise AssertionError(f"no {kind} target {arg} on the sheet")


def _type(app, s, then=pygame.K_TAB):
    for ch in s:
        app._tracker_handle_event(pygame.event.Event(
            pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0))
    app._tracker_handle_event(pygame.event.Event(pygame.KEYDOWN, key=then, unicode="", mod=0))


def _order(app):
    return [app.bm.placed_agents[e.agent_idx].name for e in app.initiative_order]


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
            check("End Encounter" in drawn, "tracker mode lost End Encounter")
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
        app._begin_encounter()
        check(app.tracker.phase == "collecting", f"phase {app.tracker.phase}")
        check(app._current_agent_idx() == -1, "someone is acting before Start")
        check(app._npc_drive_idx == -1, "Begin Encounter armed the NPC drive")
        app._draw_combat_panel()
        check(any(k == "field" for _, k, _ in app._tracker_hits), "no initiative fields")
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


def test_totals_sort():
    """Totals typed into the sheet (click, digits, Tab to the next row) sort high to low."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True)
        app._begin_encounter()
        rows = [ix for _, ix, _ in app._tracker_rows()]
        check(len(rows) == 4, f"{len(rows)} rows for four tokens")
        _click(app, "field", tuple(rows[0]))
        # Rows follow placement: Aria, Brannor, Gnasher, Skarn. Tab walks down them.
        for name in ("Aria", "Brannor", "Gnasher", "Skarn"):
            _type(app, str(TOTALS[name]))
        for name, tot in TOTALS.items():
            got = app.tracker.entry(_idx(app, name)).total
            check(got == tot, f"{name} typed {tot}, holds {got}")
        _click(app, "start")
        check(_order(app) == ["Gnasher", "Aria", "Brannor", "Skarn"], f"order {_order(app)}")
        check(app._current_agent_idx() == _idx(app, "Gnasher"), "Gnasher does not act first")
        check(app.round_num == 0, f"round_num {app.round_num}")
        _click(app, "next")
        check(app._current_agent_idx() == _idx(app, "Aria"), "Next did not reach Aria")
        _click(app, "prev")
        check(app._current_agent_idx() == _idx(app, "Gnasher"), "Prev did not go back")
        _click(app, "down", _idx(app, "Aria"))
        check(_order(app) == ["Gnasher", "Brannor", "Aria", "Skarn"], f"↓ gave {_order(app)}")
        print("✅ test_totals_sort")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_start_with_blanks():
    """Start with totals left blank: the blanks sink to the bottom, the rest still sort."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True)
        app._begin_encounter()
        app.tracker.set_total(_idx(app, "Brannor"), 7)
        app.tracker.set_total(_idx(app, "Skarn"), 13)
        app._tracker_start()
        check(app.tracker.phase == "running", "Start refused with blanks")
        order = _order(app)
        check(order[:2] == ["Skarn", "Brannor"], f"filled totals first: {order}")
        check(set(order[2:]) == {"Aria", "Gnasher"}, f"blanks last: {order}")
        check(app._current_agent_idx() == _idx(app, "Skarn"), "the top total does not act")
        app._draw_combat_panel()
        print("✅ test_start_with_blanks")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_roll_for_monsters():
    """Roll for monsters: a mob group shares one row and one roll; a typed total is kept;
    PCs are never rolled for."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True, foes=("Ghoul", "Ghoul", "Ghoul", "Skarn"))
        app._begin_encounter()
        ghouls = [i for i, pt in enumerate(app.bm.placed_agents) if pt.name == "Ghoul"]
        labels = [lbl for lbl, _, _ in app._tracker_rows()]
        check("Ghoul ×3" in labels, f"the ghouls do not share a row: {labels}")
        app.tracker.set_total(_idx(app, "Skarn"), 4)
        rolled = []
        real = app._tracker_roll
        app._tracker_roll = lambda i: rolled.append(i) or real(i)
        _click(app, "roll")
        app._tracker_roll = real
        check(len(rolled) == 1 and rolled[0] in ghouls, f"rolls made for {rolled}")
        totals = {app.tracker.entry(i).total for i in ghouls}
        check(len(totals) == 1 and None not in totals, f"ghoul totals {totals}")
        check(app.tracker.entry(_idx(app, "Skarn")).total == 4, "the typed total was rolled over")
        for pc in ("Aria", "Brannor"):
            check(app.tracker.entry(_idx(app, pc)).total is None, f"{pc} was rolled for")
        _click(app, "roll")                     # nothing blank left among the monsters
        check({app.tracker.entry(i).total for i in ghouls} == totals, "a second roll changed it")
        print("✅ test_roll_for_monsters")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_revealed_group_joins_next_round():
    """D5: a group woken from On Deck mid-fight (the fog path) rolls once, is placed at its
    total, is skipped for the rest of this round and acts from the next."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True, foes=("Gnasher", "Ghoul", "Ghoul"))
        ghouls = [i for i, pt in enumerate(app.bm.placed_agents) if pt.name == "Ghoul"]
        for i in ghouls:
            app.bm.set_agent_on_deck(i, True)
        app._begin_encounter()
        check(all(app.tracker.entry(i) is None for i in ghouls), "benched ghouls in the order")
        for name, tot in (("Aria", 15), ("Brannor", 12), ("Gnasher", 18)):
            app.tracker.set_total(_idx(app, name), tot)
        app._tracker_start()
        app._advance_turn()                     # Aria's turn: End Turn's path reaches it too
        check(app._current_agent_idx() == _idx(app, "Aria"), "advance did not reach Aria")

        # The room is seen: the fog path wakes the On Deck group.
        app.show_fog = True
        app._agents_in_revealed_rooms = lambda idxs: list(idxs)
        rolls = []
        app._tracker_roll = lambda i: rolls.append(i) or 20    # beats everyone: the top
        app._deploy_fog_revealed_enemies()
        check(len(rolls) == 1, f"{len(rolls)} rolls for one group")
        check(all(app.tracker.entry(i).total == 20 for i in ghouls), "ghouls not at 20")
        check(app._current_agent_idx() == _idx(app, "Aria"), "the join moved the turn")
        check(any("Ghoul ×2 join at 20 next round" in m for m in app.combat_log),
              f"log {app.combat_log[:3]}")

        seen = []                               # the rest of round 1
        while app.round_num == 0:
            app._advance_turn()
            seen.append(app._current_agent_idx())
        check(not set(seen[:-1]) & set(ghouls), "a ghoul acted in the round it joined")
        check(seen[-1] == ghouls[0] and app.round_num == 1,
              "the ghouls do not open round 2")
        app._advance_turn()
        check(app._current_agent_idx() == ghouls[1], "the second ghoul does not follow")
        app._draw_combat_panel()
        print("✅ test_revealed_group_joins_next_round")
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
    test_totals_sort()
    test_start_with_blanks()
    test_roll_for_monsters()
    test_revealed_group_joins_next_round()
    if FAILURES:
        print(f"\n❌ {len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nAll tracker-mode tests passed.")
