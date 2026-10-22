#!/usr/bin/env python3
"""Restoring an autosave (MULTIPLAYER_PLAN.md M6.4, D-M6-5).

  · the restore loads the slot by path: the encounter base, the session file and the
    roster stay where they were, so no player is logged out and the next autosave lands
    in the same ring, not in a ring nested inside the slot;
  · a restore into the running App (a rewind) lands on the slot's fingerprint exactly;
  · a restored automated NPC's turn runs on the next frame (F-M6-4);
  · every refusal leaves the live fight untouched;
  · every seated player is resynced: nothing from the abandoned board replays;
  · the DM reaches it from its own panel button, Restore Autosave…, one row per slot,
    newest first; Agents… no longer carries it.

The oracle (`test_restore_oracle.py`) is the restore's full-fingerprint check into a fresh
App; this suite is everything around it.
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

import autosave
from main import App
from menus import dm
from net import events as net_events
from net.events import Resync, Sight
from gui_driver import post_click
from test_restore_oracle import MAP_PATH, SEED, _fight, diff, fingerprint, _report


def _fresh(app):
    """A relaunched DM: a new App, pointed at the same encounter."""
    app2 = App(MAP_PATH, seed=SEED)
    app2.autosave_enabled = False
    app2._set_encounter_base(app._save_path)
    return app2


def _without_door_ids(fp):
    """A terrain reload in a running App renumbers its doors, because the door id counter
    only ever counts up. Nothing holds a door id across a turn (neither snapshot names
    one, and a pick-lock reads it at click time), so a rewind compares doors without it."""
    fp = dict(fp)
    fp["board.doors"] = [{k: v for k, v in d.items() if k != "id"}
                         for d in fp["board.doors"]]
    return fp


def _newest(app):
    return autosave.list_slots(app)[0]["slot"]


def test_restore_keeps_the_base_and_the_roster():
    """The trap the M6.3 handoff named: loading a slot as an encounter re-points the base
    at the slot. The restore must not. A credential minted before it still verifies after
    it, and the next autosave goes into the same ring."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        k = _newest(app)
        app2 = _fresh(app)
        pid = app2.roster.add_principal("Kira").id
        cred = app2.roster.mint_credential(pid)
        keep = {a: getattr(app2, a) for a in ("_save_path", "_terrain_path", "_effects_path",
                                              "_lighting_path", "_combat_path", "_session_path")}
        roster = app2.roster
        ring = autosave.ring_dir(app2)

        assert autosave.restore(app2, k)
        for a, v in keep.items():
            assert getattr(app2, a) == v, f"the restore moved {a} to {getattr(app2, a)}"
        assert app2.roster is roster, "the restore replaced the roster"
        assert app2.roster.verify_credential(cred) is not None, "the restore logged a player out"
        # The DM never saved this fight, and a restore writes no scene file.
        for a in ("_save_path", "_terrain_path", "_combat_path"):
            assert not os.path.exists(keep[a]), f"the restore wrote {os.path.basename(keep[a])}"

        app2.autosave_enabled = True
        app2._advance_turn()
        assert autosave.ring_dir(app2) == ring
        nested = [d for d, _, _ in os.walk(ring) if d != ring and d.endswith("_autosave")]
        assert not nested, f"a ring nested inside a slot: {nested}"
        print("✅ test_restore_keeps_the_base_and_the_roster")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rewind_in_place():
    """The DM rewinds a running fight: two turns later, the slot restored into the same
    App gives back the slot's fingerprint, the armed NPC drive and a fresh economy
    included. The turns in between armed things (the advance re-arms the drive, then
    clears it) that a fresh App never has."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=True)
        app.autosave_enabled = False
        k = autosave.save(app)
        before = fingerprint(app)
        app._advance_turn()
        app._advance_turn()
        app.action_used = True
        app.pending_attack_slot = "action"
        app.pending_shadow_step = True
        assert fingerprint(app) != before, "the two turns changed nothing to rewind"
        assert autosave.restore(app, k)
        gaps = diff(_without_door_ids(before), _without_door_ids(fingerprint(app)))
        _report(gaps)
        assert not gaps, f"the rewind lost: {sorted(gaps)}"
        assert app.pending_attack_slot == "" and not app.pending_shadow_step
        assert app.selected_idx == app._current_agent_idx()
        print("✅ test_rewind_in_place")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_restored_npc_turn_runs():
    """F-M6-4: the restore re-arms the drive, so the next frame runs the automated turn
    instead of sitting on it."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=True)
        gnasher = app._current_agent_idx()
        app2 = _fresh(app)
        assert autosave.restore(app2, _newest(app))
        assert app2._npc_drive_idx == gnasher
        turn = (app2.round_num, app2.turn_idx)
        app2._drive_npc_turn_if_pending()
        assert app2._npc_drive_idx == -1, "the drive did not run"
        assert app2._npc_anim is not None or (app2.round_num, app2.turn_idx) != turn, \
            "the automated turn neither played nor ended"

        # A PC's turn arms nothing.
        plain = _fight(tempfile.mkdtemp(dir=tmp), hard=False)
        app3 = _fresh(plain)
        assert autosave.restore(app3, _newest(plain))
        assert app3._npc_drive_idx == -1
        print("✅ test_restored_npc_turn_runs")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_refusals_change_nothing():
    """Every refusal is decided before the live scene is touched: the fight goes on
    exactly as it was, and the DM is told why."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=True)
        app.autosave_enabled = False
        app.roster.autosave_slots = 3
        shutil.rmtree(autosave.ring_dir(app))
        k = autosave.save(app)
        paths = autosave.slot_paths(app, k)
        app._advance_turn()                       # live state now differs from the slot
        live = fingerprint(app)

        def refused(why, slot=k):
            app._status_msg = ""
            assert not autosave.restore(app, slot), f"{why}: the restore ran"
            assert app._status_msg.startswith("Autosave not restored"), (why, app._status_msg)
            gaps = diff(live, fingerprint(app))
            assert not gaps, f"{why}: the refusal changed {sorted(gaps)}"

        refused("an empty slot", slot=k + 1)

        app._npc_anim = object()
        refused("an automated turn playing")
        app._npc_anim = None
        app._legendary_queue = [0]
        refused("the legendary phase")
        app._legendary_queue = []

        agents = open(paths["agents"]).read()
        doc = json.loads(agents)
        doc["agents"][0]["name"] = "Somebody Else"
        with open(paths["agents"], "w") as f:
            json.dump(doc, f)
        refused("a basis mismatch")
        with open(paths["agents"], "w") as f:
            f.write(agents)

        combat = open(paths["combat"]).read()
        doc = json.loads(combat)
        doc["combat_active"] = False
        with open(paths["combat"], "w") as f:
            json.dump(doc, f)
        refused("no running fight")
        with open(paths["combat"], "w") as f:
            f.write(combat[:len(combat) // 2])
        refused("a truncated combat file")
        with open(paths["combat"], "w") as f:
            f.write(combat)

        os.remove(paths["meta"])
        refused("a torn slot")
        print("✅ test_refusals_change_nothing")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_players_are_resynced():
    """D-M6-5 / D-M6-6: after a restore no socket is owed an events frame, a `since`
    from before it answers with a fresh view, and the events nobody had filtered yet
    (moves on the abandoned board) are dropped. The next frame is a forced push."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        k = _newest(app)
        sight = Sight(shown=frozenset(range(len(app.bm.placed_agents))))
        app.events.projection("kira")           # seated before anything happens
        app.events.append(net_events.turn(0, 0, 0))
        p = app.events.project("kira", sight)
        p.attach("sock", at=0)                  # it holds a view from before that turn
        assert p.socket_frame("sock") is not None
        seq = p.seq
        app.events.append(net_events.turn(0, 1, 1))   # not yet filtered for anyone
        app._net_turn = (True, app.round_num, app.turn_idx)

        assert autosave.restore(app, k)
        assert len(app.events) == 0, "the abandoned board's events survived"
        p = app.events.project("kira", sight)
        assert p.seq == seq, "seq must never move backwards"
        assert p.socket_frame("sock") is None, "the socket is still owed old events"
        try:
            p.since(0)
            raise AssertionError("a since from before the restore was answered from the ring")
        except Resync:
            pass
        assert p.since(seq) == []
        assert app._net_turn is None, "the next push is not forced"
        print("✅ test_players_are_resynced")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_menu_lists_and_restores():
    """The panel button opens the list; it lists each slot newest first, with round,
    actor and time, and a pick restores that slot. An empty ring opens nothing. Agents…
    no longer carries the entry."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        dm.show_agents_menu(app)
        labels = [o.label for o in app.prompts.live.options]
        assert not any("autosave" in l.lower() for l in labels), labels
        app.prompts.cancel()
        dm.show_restore_autosave_menu(app)
        sub = app.prompts.live
        slots = autosave.list_slots(app)
        assert sub is not None and [o.label for o in sub.options] == \
            [autosave.slot_label(m) for m in slots], "rows are not the slots, newest first"
        assert sub.options[0].label.startswith(f"Round {slots[0]['round'] + 1} · ")

        before = fingerprint(app)
        app._advance_turn()
        app._advance_turn()
        # The newest slot is now two turns on; the row for the slot this test captured
        # is the one picked.
        dm.show_restore_autosave_menu(app)
        want = next(m for m in autosave.list_slots(app) if m["seq"] == slots[0]["seq"])
        assert app.prompts.choose_label(autosave.slot_label(want)).ok
        gaps = diff(_without_door_ids(before), _without_door_ids(fingerprint(app)))
        _report(gaps)
        assert not gaps, f"the menu's restore lost: {sorted(gaps)}"

        shutil.rmtree(autosave.ring_dir(app))
        app.prompts.cancel()
        dm.show_restore_autosave_menu(app)
        assert app.prompts.live is None, "an empty ring opened a menu"
        assert "No autosaves" in app._status_msg
        print("✅ test_menu_lists_and_restores")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_panel_button_opens_the_list():
    """After a crash the relaunched DM is on the setup panel, not in a fight. A real click
    on Restore Autosave… opens the slot list, and picking a row resumes the fight. The
    button has its own row: it overlaps neither Begin Combat above nor Terrain… below."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        app2 = _fresh(app)
        assert not app2.combat_active
        app2._reposition_panel()
        btn = app2.btn_restore_autosave
        for other in (app2.btn_begin_combat, app2.btn_terrain, app2.btn_agents):
            assert not btn.rect.colliderect(other.rect), f"{btn.rect} overlaps {other.text}"
        assert app2.btn_begin_combat.rect.bottom <= btn.rect.top < app2.btn_terrain.rect.top
        post_click(app2, btn.rect.center)
        live = app2.prompts.live
        assert live is not None and live.title == "Restore autosave", \
            f"the click opened {live.title if live else None}"
        assert app2.prompts.choose_label(live.options[0].label).ok
        assert app2.combat_active, "picking a slot did not resume the fight"
        print("✅ test_the_panel_button_opens_the_list")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [test_restore_keeps_the_base_and_the_roster, test_rewind_in_place,
             test_restored_npc_turn_runs, test_refusals_change_nothing,
             test_players_are_resynced, test_menu_lists_and_restores,
             test_the_panel_button_opens_the_list]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
