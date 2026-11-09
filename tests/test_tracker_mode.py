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
from gui_driver import cell_center
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


def test_revealed_group_joins():
    """D5, as amended: a group woken from On Deck mid-fight (the fog path) rolls once and
    goes straight into the order at its total, with no wait for the next round."""
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
        app._tracker_roll = lambda i: rolls.append(i) or 13    # between Aria and Brannor
        app._deploy_fog_revealed_enemies()
        check(len(rolls) == 1, f"{len(rolls)} rolls for one group")
        check(all(app.tracker.entry(i).total == 13 for i in ghouls), "ghouls not at 13")
        check(_order(app) == ["Gnasher", "Aria", "Ghoul", "Ghoul", "Brannor"],
              f"order {_order(app)}")
        check(app._current_agent_idx() == _idx(app, "Aria"), "the join moved the turn")
        check(any("Ghoul ×2 join at 13." in m for m in app.combat_log),
              f"log {app.combat_log[:3]}")
        for want in (ghouls[0], ghouls[1], _idx(app, "Brannor")):   # this round, in place
            app._advance_turn()
            check(app._current_agent_idx() == want and app.round_num == 0,
                  f"round 1 went to {app._current_agent_idx()}, not {want}")
        app._draw_combat_panel()
        print("✅ test_revealed_group_joins")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _drag(app, frm, to):
    """The DM drags a token from cell `frm` to cell `to` through real events."""
    a, b = cell_center(app, *frm), cell_center(app, *to)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=a, button=1))
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=b, rel=(b[0] - a[0], b[1] - a[1]),
                                         buttons=(1, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=b, button=1))
    assert app._handle_events() is not False


def _pos(app, idx):
    o = app.bm.placed_agents[idx].origin
    return (o.col, o.row)


def test_drag_any_token():
    """T5: the DM drags any token at any time, while the totals are collected and on
    someone else's turn, with no movement budget and no opportunity attack."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True)
        app._begin_encounter()
        aria, skarn, gnasher = (_idx(app, n) for n in ("Aria", "Skarn", "Gnasher"))
        _drag(app, (2, 3), (3, 3))                      # nobody is acting yet
        check(_pos(app, aria) == (3, 3), f"collecting: Aria at {_pos(app, aria)}")
        check(app._current_agent_idx() == -1, "a click before Start made someone act")

        for name, tot in TOTALS.items():
            app.tracker.set_total(_idx(app, name), tot)
        app._tracker_start()
        check(app._current_agent_idx() == gnasher, "Gnasher does not act first")
        hp = {i: app.combat.get_agent_stats(app.bm, i).hp_cur
              for i in range(len(app.bm.placed_agents))}
        _drag(app, (8, 8), (6, 8))                      # Skarn, on Gnasher's turn, 10 ft
        check(_pos(app, skarn) == (6, 8), f"Skarn's drag left him at {_pos(app, skarn)}")
        check(app._current_agent_idx() == skarn, "a token click did not make Skarn active")
        check(app.round_num == 0, f"a token click changed the round to {app.round_num}")
        _drag(app, (3, 3), (7, 3))                      # Aria runs past Gnasher's reach
        _drag(app, (7, 3), (2, 6))                      # and away from it again
        check(_pos(app, aria) == (2, 6), f"Aria's drags left her at {_pos(app, aria)}")
        after = {i: app.combat.get_agent_stats(app.bm, i).hp_cur for i in hp}
        check(after == hp, f"a drag cost HP (an opportunity attack?): {hp} → {after}")
        check(app._current_agent_idx() == aria, "the ▶ did not follow the last token clicked")
        check(app._tracker_hp == aria, "the token click did not open Aria's HP box")
        check(app._fog_dirty, "the drop did not mark the fog dirty")
        print("✅ test_drag_any_token")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_drag_wakes_on_deck():
    """T5: a drag that sees into a room reveals it and wakes its On Deck mobs, which join
    at one roll (D5)."""
    tmp = tempfile.mkdtemp()
    try:
        app = _setup(tmp, tracker=True, foes=("Gnasher", "Ghoul", "Ghoul"))
        ghouls = [i for i, pt in enumerate(app.bm.placed_agents) if pt.name == "Ghoul"]
        for i in ghouls:
            app.bm.set_agent_on_deck(i, True)
        app._begin_encounter()
        for name, tot in (("Aria", 15), ("Brannor", 12), ("Gnasher", 18)):
            app.tracker.set_total(_idx(app, name), tot)
        app._tracker_start()
        aria = _idx(app, "Aria")
        # The ghouls' room is in view only from (4, 5): the drag there is what wakes them.
        app.show_fog = True
        app._agents_in_revealed_rooms = (
            lambda idxs: list(idxs) if _pos(app, aria) == (4, 5) else [])
        app._tracker_roll = lambda i: 11
        app._refresh_fog()
        check(all(app.bm.is_agent_on_deck(i) for i in ghouls), "the ghouls woke before the drag")
        _drag(app, (2, 3), (4, 5))
        app._refresh_fog()                              # the frame's reveal
        check(not any(app.bm.is_agent_on_deck(i) for i in ghouls), "the drag woke no ghoul")
        check(all(app.tracker.entry(i).total == 11 and app.tracker.entry(i).joins_round == 1
                  for i in ghouls), "the ghouls did not join at 11 this round")
        print("✅ test_drag_wakes_on_deck")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _hp(app, op, amount):
    """Type `amount` into the open HP box, then click its `op` button."""
    for ch in str(amount):
        app._tracker_handle_event(pygame.event.Event(
            pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0))
    _click(app, "hp", op)


def _stats(app, idx):
    s = app.combat.get_agent_stats(app.bm, idx)
    return s.hp_cur, s.hp_max, s.temp_hp


def test_hp_box():
    """T4: a row click opens the HP box. Temp HP absorbs damage first; heal stops at max;
    a lower max clamps current HP. Each change is one log line."""
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=True)
        aria = _idx(app, "Aria")
        _click(app, "row", aria)
        check(app._tracker_hp == aria, "the row click opened no HP box")
        cur, mx, _ = _stats(app, aria)
        log0 = len(app.combat_log)
        _hp(app, "temp", 5)
        _hp(app, "dmg", 8)
        check(_stats(app, aria) == (cur - 3, mx, 0), f"temp first: {_stats(app, aria)}")
        _hp(app, "heal", 999)
        check(_stats(app, aria) == (mx, mx, 0), f"heal clamp: {_stats(app, aria)}")
        _hp(app, "max", mx - 2)
        check(_stats(app, aria) == (mx - 2, mx - 2, 0), f"max clamp: {_stats(app, aria)}")
        check(len(app.combat_log) - log0 == 4, f"{len(app.combat_log) - log0} log lines for 4")
        check(f"{mx - 2}/{mx - 2} HP" in app.combat_log[0], f"PC line {app.combat_log[0]}")
        _click(app, "row", _idx(app, "Brannor"))     # another row: a fresh box
        check(app._tracker_hp == _idx(app, "Brannor") and app._tracker_hp_text == "",
              "a second row did not open its own box")
        app._tracker_handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                                     unicode="", mod=0))
        check(app._tracker_hp == -1, "Esc did not close the box")
        print("✅ test_hp_box")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_row_click_moves_turn():
    """A click on a name in the order moves the ▶ there (the round stays), opens its HP
    box, and Next goes on from it."""
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=True)                 # Gnasher, Aria, Brannor, Skarn
        brannor = _idx(app, "Brannor")
        _click(app, "row", brannor)
        check(app._current_agent_idx() == brannor, "the click did not move the ▶")
        check(app.round_num == 0, f"the click changed the round to {app.round_num}")
        check(app._tracker_hp == brannor, "the click opened no HP box")
        _click(app, "next")
        check(app._current_agent_idx() == _idx(app, "Skarn"), "Next did not go on from it")
        print("✅ test_row_click_moves_turn")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hp_zero():
    """T4/D4: a monster at 0 leaves the board and the order (the acting one hands the turn
    on); a PC at 0 stays in the order and keeps its turn. A token click opens the box."""
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=True)
        aria, skarn, gnasher = (_idx(app, n) for n in ("Aria", "Skarn", "Gnasher"))
        _drag(app, _pos(app, skarn), _pos(app, skarn))   # a click on Skarn's token
        check(app._tracker_hp == skarn, "the token click opened no HP box")
        _hp(app, "dmg", 999)
        check(app.bm.is_agent_removed_from_play(skarn), "Skarn at 0 is still on the board")
        check("Skarn" not in _order(app), f"Skarn at 0 is still in the order {_order(app)}")
        check(app._current_agent_idx() == gnasher, "clearing Skarn moved the turn")
        check(app._tracker_hp == -1, "the box stayed open on a cleared token")

        _click(app, "row", gnasher)                 # the acting monster drops
        _hp(app, "dmg", 999)
        check(app._current_agent_idx() == aria, "the turn did not pass from Gnasher to Aria")
        check(_order(app) == ["Aria", "Brannor"], f"order {_order(app)}")

        _click(app, "row", aria)
        _hp(app, "dmg", 999)
        check(_stats(app, aria)[0] == 0, "Aria not at 0")
        check(not app.bm.is_agent_removed_from_play(aria), "a PC at 0 left the board")
        check(app._current_agent_idx() == aria, "a PC at 0 lost her turn")
        app._advance_turn()
        app._advance_turn()
        check(app._current_agent_idx() == aria, "a PC at 0 was skipped next round")
        app._draw_combat_panel()
        print("✅ test_hp_zero")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hp_display_d1():
    """D1: the table view shows party HP only, on the sheet and in the log; DM view shows
    every number."""
    tmp = tempfile.mkdtemp()
    try:
        app = _board(tmp, tracker=True)
        skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
        check(app._tracker_hp_shown(aria), "party HP hidden in the table view")
        check(not app._tracker_hp_shown(skarn), "monster HP shown in the table view")
        _click(app, "row", skarn)
        _hp(app, "dmg", 1)
        check("/" not in app.combat_log[0], f"monster HP in the log: {app.combat_log[0]}")
        app.dm_view = True
        check(app._tracker_hp_shown(skarn), "DM view hides monster HP")
        _hp(app, "dmg", 1)
        check("HP" in app.combat_log[0] and "/" in app.combat_log[0],
              f"DM view log line {app.combat_log[0]}")
        app._draw_combat_panel()
        app._draw_agents()                      # the token HP bars follow D1 too
        app.dm_view = False
        app._draw_agents()
        print("✅ test_hp_display_d1")
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
    test_revealed_group_joins()
    test_drag_any_token()
    test_drag_wakes_on_deck()
    test_hp_box()
    test_row_click_moves_turn()
    test_hp_zero()
    test_hp_display_d1()
    if FAILURES:
        print(f"\n❌ {len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nAll tracker-mode tests passed.")
