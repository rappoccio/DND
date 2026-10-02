#!/usr/bin/env python3
"""The action offer: a player's own turn, played from the browser (MULTIPLAYER_PLAN.md
D-M5-2, slice M5b).

`net/offer.py` posts a `kind:"action"` prompt on each step of a turn whose token a player
controls, derived once per frame from the menu the panel just built. These checks pin
what it offers, when, to whom, and that the DM console neither sees it nor loses it:

  · the class table is the dispatch, row for row            (test_the_class_table_is_the_dispatch)
  · the pick predicate covers the turn-boundary clear       (test_the_pick_predicate_covers_the_clear)
  · DM tools never reach the wire (D-M5-9's last row)       (test_the_wire_never_carries_dm_tools)
  · no offer on a DM-controlled or NPC turn                 (test_no_offer_on_a_dm_or_npc_turn)
  · the DM console is unchanged with the offer up           (test_the_dm_console_does_not_draw_the_offer)
  · a DM popup click-away does not cancel the offer         (test_a_dm_click_away_keeps_the_offer)
  · a remote Dodge, then a fresh offer without it           (test_a_remote_dodge_then_a_fresh_offer)
  · End Turn moves the offer to the next owner, or none     (test_end_turn_moves_the_offer)
  · A and X rows go out disabled, and are refused           (test_a_pick_row_is_offered_disabled)
  · a DM click takes the turn over, and is logged           (test_a_dm_click_takes_over)
  · a pause withdraws the offer, without a takeover line    (test_a_pause_withdraws_the_offer)

The scene is `test_combat_panel.py`'s, through `test_action_menu.py`'s `_app`: Aria is a
Fighter 5 with Skarn adjacent, and Kira, a player, controls her.
"""

import ast
import collections
import contextlib
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from menus import panel
from net import link as net_link, offer as net_offer
from net.roster import Role
from prompts import PromptState, Response

from gui_driver import post_click
from test_action_menu import _app, _draw
from test_combat_panel import (PanelCapture, _goto, _idx, _preserve_cwd_logs,
                               _restore_cwd_logs)
from test_live import _auth_frame, _faster_cadence, _ws
from test_submit import _Table, _drain, _next, _submit

_MAIN = os.path.join(_ROOT, "gui", "main.py")
_DM_TOOLS = ("pause_resume", "reaction_timer", "end_combat", "place_terrain")


# ─────────────────────────────────────────────────────────────────────────────
#  Rig
# ─────────────────────────────────────────────────────────────────────────────

def _seated(app):
    """Kira controls Aria and Wen controls Cyra, who acts after her; Brannor and Skarn
    stay the DM's."""
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    wen = app.roster.add_principal("Wen", role=Role.PLAYER)
    app.bm.set_agent_controller(_idx(app, "Aria"), kira.id)
    app.bm.set_agent_controller(_idx(app, "Cyra"), wen.id)
    app._sync_roster_tokens()
    return kira, wen


def _frame(app):
    """What `run()` does after its input half: the panel, then the offer."""
    app._draw_panel()
    net_offer.ensure(app)


def _aria_turn(tmp=None):
    app = _app()
    if tmp is not None:
        app.submit_log.path = os.path.join(tmp, "submit_log.jsonl")
    kira, wen = _seated(app)
    _goto(app, "Aria")
    _frame(app)
    return app, kira, wen


def _offer(app):
    live = app.prompts.live
    return live if live is not None and live.kind == "action" and live.is_live else None


def _log(app):
    path = app.submit_log.path
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


class _OfferTable(_Table):
    """`test_submit._Table`, with the frame tick's drawing half: `run()` rebuilds the menu
    and runs `ensure` every frame, and the offer is derived from nothing else."""

    def _tick(self, interval):
        import time
        while self._ticking:
            net_link.pump_submits(self.app)
            self.app._net_commands.pump(self.app)
            net_link.push_cycle(self.app)
            _frame(self.app)
            time.sleep(interval)


@contextlib.contextmanager
def _table():
    tmp = tempfile.mkdtemp()
    table = None
    try:
        app, kira, wen = _aria_turn()
        table = _OfferTable(app, tmp)
        table.kira, table.wen = kira, wen
        with _faster_cadence():
            yield table
    finally:
        if table is not None:
            table.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _action_prompt(sock, exclude=()):
    return _next(sock, "prompt",
                 match=lambda f: f["kind"] == "action" and f["id"] not in exclude)


# ─────────────────────────────────────────────────────────────────────────────
#  Static: the tables hold to the code they describe
# ─────────────────────────────────────────────────────────────────────────────

def _method(name):
    tree = ast.parse(open(_MAIN, encoding="utf-8").read())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_class_table_is_the_dispatch():
    """`CLASS` names exactly the ids `_perform_action` dispatches, with Step 0.12's counts.

    A row missing here would send that action disabled forever; an extra row would be a
    class for an action that no longer exists."""
    dispatched = set()
    for node in ast.walk(_method("_perform_action")):
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == "action_id"
                and isinstance(node.comparators[0], ast.Constant)):
            dispatched.add(node.comparators[0].value)
    assert len(dispatched) == 111, len(dispatched)
    assert set(net_offer.CLASS) == dispatched, (
        f"missing {sorted(dispatched - set(net_offer.CLASS))}, "
        f"extra {sorted(set(net_offer.CLASS) - dispatched)}")
    counts = collections.Counter(net_offer.CLASS.values())
    assert counts == {"I": 57, "C→I": 8, "A": 16, "A*": 1, "C→A": 7, "X": 12,
                      "C→X": 1, "S": 5, "DM": 4}, counts
    assert sorted(i for i, c in net_offer.CLASS.items() if c == "DM") == sorted(_DM_TOOLS)
    print("✅ test_the_class_table_is_the_dispatch")


def test_the_pick_predicate_covers_the_clear():
    """Every field the turn boundary resets is either an arm the offer waits on or a
    companion named as one. A new arm added to the clear and forgotten here would let the
    offer run another action over a pick in progress."""
    reset = set()
    for node in ast.walk(_method("_clear_pending_target_picks")):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "self"):
                    reset.add(t.attr)
    from main import App
    arms = {name for name, _ in App._TARGET_PICK_ARMS}
    companions = set(App._TARGET_PICK_COMPANIONS)
    assert not arms & companions, arms & companions
    assert reset <= arms | companions, f"unaccounted for: {sorted(reset - arms - companions)}"
    assert companions <= reset, f"not reset at all: {sorted(companions - reset)}"

    app, _, _ = _aria_turn()
    assert not app._target_pick_armed(), "a clean turn reads as a pick in progress"
    for name, idle in App._TARGET_PICK_ARMS:
        saved = getattr(app, name)
        setattr(app, name, True if idle in (False, None) else ("action" if idle == "" else 1))
        assert app._target_pick_armed(), f"{name} armed is not seen"
        setattr(app, name, saved)
    print("✅ test_the_pick_predicate_covers_the_clear")


# ─────────────────────────────────────────────────────────────────────────────
#  When there is an offer, and who sees it
# ─────────────────────────────────────────────────────────────────────────────

def test_no_offer_on_a_dm_or_npc_turn():
    """Skarn is the DM's: his turn posts nothing. Aria's, with an NPC drive pending, posts
    nothing either; it appears once the drive is done."""
    app, kira, _ = _aria_turn()
    assert _offer(app) is not None and _offer(app).owner == kira.id, "Aria's turn has no offer"

    app.prompts.withdraw(_offer(app).id)
    _goto(app, "Skarn")
    _frame(app)
    assert app.prompts.live is None, "the DM's own turn was offered"

    _goto(app, "Aria")
    app._npc_drive_idx = _idx(app, "Aria")
    _frame(app)
    assert app.prompts.live is None, "an offer went up under a pending NPC drive"
    app._npc_drive_idx = -1
    _frame(app)
    assert _offer(app) is not None
    print("✅ test_no_offer_on_a_dm_or_npc_turn")


def test_the_dm_console_does_not_draw_the_offer():
    """The panel capture with the offer live is the capture with nobody seated, and no
    popup is up: the offer exists only in the player's browser."""
    plain = _app()
    _goto(plain, "Aria")
    want = PanelCapture(plain).capture("Aria")

    app, _, _ = _aria_turn()
    assert _offer(app) is not None
    got = PanelCapture(app).capture("Aria")
    assert got == want, "seating a player changed the DM's panel"
    for widget in ("context_menu", "spell_grid_menu", "_element_dialog"):
        assert not getattr(app, widget).visible, f"the offer was drawn by {widget}"
    print("✅ test_the_dm_console_does_not_draw_the_offer")


def test_a_dm_click_away_keeps_the_offer():
    """The trap D-M5-2 names: a popup the DM opens and then clicks away from is reported
    with `renderer_dismissed()`, which cancels the live prompt unless its renderer says it
    is up. The offer's renderer must say so."""
    app, _, _ = _aria_turn()
    offer = _offer(app)
    app.context_menu.show((200, 200), [("Something", lambda: None)], app.screen.get_size())
    assert app.context_menu.visible
    post_click(app, (5, 5))                                   # away from the popup
    assert not app.context_menu.visible, "the click did not dismiss the popup"
    assert offer.is_live, f"the DM's click-away resolved the offer ({offer.state})"
    print("✅ test_a_dm_click_away_keeps_the_offer")


def test_a_pause_withdraws_the_offer():
    """When the gate closes under a live offer, the offer goes, and nothing is logged:
    nobody answered it and nobody took it over."""
    tmp = tempfile.mkdtemp()
    try:
        app, _, _ = _aria_turn(tmp)
        offer = _offer(app)
        app.combat_paused = True
        _frame(app)
        assert offer.state is PromptState.SUPERSEDED, offer.state
        assert app.prompts.live is None
        assert _log(app) == [], _log(app)
        app.combat_paused = False
        _frame(app)
        assert _offer(app) is not None and _offer(app) is not offer
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_a_pause_withdraws_the_offer")


def test_a_dm_click_takes_over():
    """D-M5-7: the DM's panel click on a player's turn cancels the offer as the DM before
    the action runs. That is a `takeover` line, and the player's late submit is `not_live`."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        offer = _offer(app)
        post_click(app, panel.cbt_btn(app, "dodge").rect.center)
        assert app.action_used, "the DM's Dodge did not run"
        late = app.prompts.submit(offer.id, Response(option="dash"), kira.id)
        lines = _log(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not late.ok and late.error == "not_live", late
    assert [(l["event"], l["prompt"], l["answer"]) for l in lines] == [
        ("takeover", offer.id, {"cancel": True})], lines
    print("✅ test_a_dm_click_takes_over")


# ─────────────────────────────────────────────────────────────────────────────
#  Over the wire
# ─────────────────────────────────────────────────────────────────────────────

def test_the_wire_never_carries_dm_tools():
    """Byte level: Kira's whole stream, over enough cycles that the offer went out many
    times, never names a DM tool, even though the DM's menu holds all of them."""
    with _table() as t:
        assert all(i in t.app._action_menu for i in ("pause_resume", "reaction_timer", "end_combat"))
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wire = _action_prompt(kira)
            raw = _drain(kira, 0.5)
    ids = [o["id"] for o in wire["options"]]
    assert "dodge" in ids and "end_turn" in ids, ids
    assert any('"kind":"action"' in r.replace(" ", "") for r in raw), "the offer was sent once"
    for tool in _DM_TOOLS:
        assert tool not in json.dumps(wire), f"{tool} is in the offer"
        assert not any(tool in r for r in raw), f"{tool} reached a player's socket"
    print("✅ test_the_wire_never_carries_dm_tools")


def test_a_pick_row_is_offered_disabled():
    """Attack (C→A), Shove (A) and the long jump (X) go out greyed with a reason, and a
    submit of one is refused before anything runs."""
    with _table() as t:
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            wire = _action_prompt(kira)
            rows = {o["id"]: o for o in wire["options"]}
            for aid in ("atk_action", "shove_push", "long_jump"):
                assert aid in rows, f"{aid} is not on Aria's offer: {sorted(rows)}"
                assert rows[aid]["enabled"] is False, f"{aid} was offered enabled"
                assert rows[aid].get("disabled_reason"), f"{aid} has no reason"
            assert rows["dodge"]["enabled"] is True
            kira.send_text(_submit(wire["id"], option="atk_action"))
            ack = _next(kira, "submit_ack")
        t.stop()
        assert ack["ok"] is False and ack["error"] == "bad_option", ack
        assert t.app.pending_attack_slot == "", "a refused attack armed its pick"
    print("✅ test_a_pick_row_is_offered_disabled")


def test_a_remote_dodge_then_a_fresh_offer():
    """End to end: Kira submits Dodge from the offer over a live socket. It runs as the DM's
    click would, and the next offer is a new prompt that no longer holds Dodge."""
    with _table() as t:
        aria = _idx(t.app, "Aria")
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            first = _action_prompt(kira)
            kira.send_text(_submit(first["id"], option="dodge"))
            ack = _next(kira, "submit_ack")
            assert ack["ok"] is True, ack
            second = _action_prompt(kira, exclude=(first["id"],))
        t.stop()
        assert t.app.action_used, "the remote Dodge did not spend the Action"
        assert t.app.bm.placed_agents[aria].conditions.dodging, "Aria is not dodging"
        enabled = {o["id"] for o in second["options"] if o["enabled"]}
        assert "dodge" not in enabled, "the fresh offer still holds Dodge"
        assert "end_turn" in enabled
    print("✅ test_a_remote_dodge_then_a_fresh_offer")


def test_end_turn_moves_the_offer():
    """Kira ends Aria's turn from the browser. The turn advances to Cyra, and the offer
    follows her controller: it is Wen's now, and Kira's socket hears no more of it.

    The second half is the DM advancing the turn directly, not through the panel, under a
    live offer. The offer must still not survive the turn change."""
    with _table() as t:
        app = t.app
        aria = _idx(app, "Aria")
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            first = _action_prompt(kira)
            kira.send_text(_submit(first["id"], option="end_turn"))
            ack = _next(kira, "submit_ack")
            assert ack["ok"] is True, ack
            _drain(kira, 0.3)
        t.stop()
        actor = app._current_agent_idx()
        assert actor == _idx(app, "Cyra"), "End Turn did not advance the turn to Cyra"
        offer = _offer(app)
        assert offer is not None and offer.owner == t.wen.id and offer.actor_idx == actor, \
            "the offer did not move to Wen"

    # The DM advances the turn with Kira's offer live, outside the panel.
    app, kira, _ = _aria_turn()
    offer = _offer(app)
    app._advance_turn()
    _frame(app)
    now = _offer(app)
    assert not offer.is_live, "Kira's offer outlived her turn"
    assert now is not None and now.owner != kira.id, "the offer did not follow the turn"

    # And onto a DM-controlled token, where it goes to nobody.
    _goto(app, "Skarn")
    _frame(app)
    assert _offer(app) is None, "the DM's turn carries an offer"
    print("✅ test_end_turn_moves_the_offer")


if __name__ == "__main__":
    # `_start_combat` truncates the live session's logs in the cwd; put them back.
    _saved = _preserve_cwd_logs()
    try:
        test_the_class_table_is_the_dispatch()
        test_the_pick_predicate_covers_the_clear()
        test_no_offer_on_a_dm_or_npc_turn()
        test_the_dm_console_does_not_draw_the_offer()
        test_a_dm_click_away_keeps_the_offer()
        test_a_pause_withdraws_the_offer()
        test_a_dm_click_takes_over()
        test_the_wire_never_carries_dm_tools()
        test_a_pick_row_is_offered_disabled()
        test_a_remote_dodge_then_a_fresh_offer()
        test_end_turn_moves_the_offer()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All offer tests passed!")
