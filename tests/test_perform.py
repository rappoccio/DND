#!/usr/bin/env python3
"""`App.perform` — id-only dispatch (MULTIPLAYER_PLAN.md D-M5-1, slice M5b).

Until M5b the 110 combat-panel actions ran only as a side effect of a pygame click:
each body sat under `if self._action_clicked("<id>", event):` in `_handle_events`. A
remote player has no click, so D-M5-1 moves every body under
`perform(action_id, principal, anchor=None)` and leaves the click site one line long.

`test_combat_panel.py` and `test_determinism.py` prove the move changed nothing. This
suite proves the half they cannot see:

  · the click and `perform` are the SAME path — a sample of no-target actions, each
    run once by a synthesized click and once by `perform` with no event at all, leaves
    the two apps in identical engine state;
  · `perform` refuses what the offer does not name, including an id that is drawn but
    disabled, which the click path can never reach because `_action_clicked` checks
    `enabled` first;
  · `perform` asks `authorize()` — a player may act only for the token they control,
    and never with the DM's session tools;
  · the handler guards came with their bodies: Dash is still refused mid-sequence,
    and Haste's extra Action is still outside the Bonus band.

The scene is `test_combat_panel.py`'s, through `test_action_menu.py`'s `_app`.
"""

import os
import sys
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from menus import panel
from net.roster import DM_PRINCIPAL_ID, Role

from gui_driver import post_click
from test_action_menu import _app, _draw
from test_combat_panel import _goto, _idx, _preserve_cwd_logs, _restore_cwd_logs


_PLAIN = (bool, int, float, str, type(None))


def _plain(obj):
    """Every primitive attribute of a bound engine object, as a dict. Anything that is
    not a primitive (or a list of them) is skipped: a pybind object's repr carries its
    address, which differs between two apps even when their state does not."""
    out = {}
    for n in dir(obj):
        if n.startswith("_"):
            continue
        try:
            v = getattr(obj, n)
        except Exception:
            continue
        if callable(v):
            continue
        if isinstance(v, _PLAIN):
            out[n] = v
        elif hasattr(v, "__len__") and not isinstance(v, (str, bytes)):
            try:
                seq = list(v)
            except Exception:
                continue
            if all(isinstance(x, _PLAIN) for x in seq):
                out[n] = seq
    return out


_APP_FIELDS = ("action_used", "bonus_used", "attacks_remaining", "_attack_sequence_slot",
               "move_remaining_walk", "move_remaining_fly", "move_remaining_swim",
               "move_remaining_burrow", "turn_idx", "round_num", "combat_paused",
               "combat_active", "pending_spell_slot", "hint")


def _state(app):
    """What an action can change: every combatant's stats, conditions, weapons,
    position and movement, the app's turn economy, and the combat log."""
    out = {k: getattr(app, k) for k in _APP_FIELDS}
    for i, a in enumerate(app.bm.placed_agents):
        out[f"agent {i}"] = (
            a.name, a.origin.col, a.origin.row,
            a.walk_remaining, a.fly_remaining,
            _plain(app.combat.get_agent_stats(app.bm, i)),
            _plain(app.combat.get_agent_conditions(app.bm, i)),
            [w.name for w in app.combat.get_agent_weapons(app.bm, i)],
        )
    out["log"] = list(app.combat_log)
    return out


def _diff(a, b):
    return [k for k in a if a[k] != b.get(k)]


# Actions Aria (Fighter 5, a foe adjacent) is offered at the top of a clean turn that
# need no target: the I rows of Step 0.12's walk, plus the session and turn controls.
# `standup` is exercised from `prone` below, since it is only offered to the prone.
_SAMPLE = ("dodge", "dash", "disengage", "hide", "prone", "second_wind",
           "action_surge", "drop_weapon_main", "end_turn", "pause_resume")


def test_perform_is_the_click():
    """The oracle D-M5-1 names: for each sampled id, the click path and `perform` with no
    pygame event leave two same-seed apps byte-identical. Each action must also have done
    something, or the comparison would be two no-ops agreeing."""
    for action_id in _SAMPLE:
        clicked, performed = _app(), _app()
        for app in (clicked, performed):
            _goto(app, "Aria")
            _draw(app)
            assert action_id in app._action_menu, f"{action_id} is not on offer to Aria"
        before = _state(clicked)

        post_click(clicked, panel.cbt_btn(clicked, action_id).rect.center)
        assert performed.perform(action_id, DM_PRINCIPAL_ID) is True, action_id

        after_click, after_perform = _state(clicked), _state(performed)
        assert after_click != before, f"the {action_id} click changed nothing"
        assert after_click == after_perform, \
            f"{action_id}: click and perform disagree on {_diff(after_click, after_perform)}"

    # Stand Up, from the prone state the sample's `prone` leaves behind.
    clicked, performed = _app(), _app()
    for app in (clicked, performed):
        _goto(app, "Aria")
        _draw(app)
        app.perform("prone", DM_PRINCIPAL_ID)
        _goto(app, "Aria")          # going prone spent the Action; a fresh economy
        _draw(app)
        assert "standup" in app._action_menu
    post_click(clicked, panel.cbt_btn(clicked, "standup").rect.center)
    performed.perform("standup", DM_PRINCIPAL_ID)
    aria = _idx(clicked, "Aria")
    assert not clicked.bm.placed_agents[aria].conditions.prone
    assert _state(clicked) == _state(performed)
    print("✅ test_perform_is_the_click passed")


def test_perform_refuses_what_the_offer_does_not_name():
    """`perform` re-checks the offer itself. The disabled case is the one that matters:
    `_action_clicked` already refuses it for a click, so only a direct `perform` — a
    remote submit — can reach it, and only this re-check stands in the way."""
    app = _app()
    _goto(app, "Aria")
    _draw(app)
    before = _state(app)

    app._action_menu["dodge"] = replace(app._action_menu["dodge"], enabled=False,
                                        disabled_reason="a test says no")
    assert app.perform("dodge", DM_PRINCIPAL_ID) is False
    assert not app.action_used, "a disabled action ran"

    del app._action_menu["dash"]
    assert app.perform("dash", DM_PRINCIPAL_ID) is False
    assert app.perform("no_such_action", DM_PRINCIPAL_ID) is False
    assert _state(app) == before, "a refused perform changed the game"
    print("✅ test_perform_refuses_what_the_offer_does_not_name passed")


def _seated(app):
    """Kira controls Aria; Wen is seated and controls nothing."""
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    wen = app.roster.add_principal("Wen", role=Role.PLAYER)
    app.bm.set_agent_controller(_idx(app, "Aria"), kira.id)
    app._sync_roster_tokens()
    return kira, wen


def test_perform_asks_authorize():
    """A player acts for their own token and no other; the DM tools are the DM's even on
    that player's turn; an unknown principal is nobody."""
    app = _app()
    kira, wen = _seated(app)
    _goto(app, "Aria")
    _draw(app)
    before = _state(app)

    assert app.perform("dodge", wen.id) is False, "Wen does not control Aria"
    assert app.perform("dodge", "no-such-principal") is False
    for dm_tool in ("pause_resume", "reaction_timer", "end_combat"):
        assert dm_tool in app._action_menu
        assert app.perform(dm_tool, kira.id) is False, f"a player ran {dm_tool}"
    assert _state(app) == before, "a refused perform changed the game"

    assert app.perform("dodge", kira.id) is True
    assert app.action_used, "Kira's Dodge did not run"
    print("✅ test_perform_asks_authorize passed")


def test_the_handler_guards_moved_with_their_bodies():
    """The two guards Step 0.12 names, driven through `perform` with no click.

    Dash mid-sequence is D-M2-4: drawn, offered, and refused by `not action_used`.
    Haste's extra Action stands outside the `not bonus_used` band on purpose; inside it,
    a creature that spent its Bonus Action first would lose the hasted Action."""
    app = _app()
    aria = _goto(app, "Aria")
    app.action_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "action"
    _draw(app)
    assert "dash" in app._action_menu
    walk = app.bm.placed_agents[aria].walk_remaining
    app.perform("dash", DM_PRINCIPAL_ID)
    assert app.bm.placed_agents[aria].walk_remaining == walk, \
        "Dash ran with the Action already spent"

    app = _app()
    aria = _goto(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria)
    s.haste_action_available = True
    app.combat.set_agent_stats(app.bm, aria, s)
    app.bonus_used = True
    app.action_used = True
    _draw(app)
    assert "haste_action" in app._action_menu
    app.perform("haste_action", DM_PRINCIPAL_ID)
    assert not app.action_used, "Haste's Action was withheld because the Bonus Action is spent"
    assert not app.combat.get_agent_stats(app.bm, aria).haste_action_available
    print("✅ test_the_handler_guards_moved_with_their_bodies passed")


if __name__ == "__main__":
    # `_start_combat` truncates the live session's logs in the cwd; put them back.
    _saved = _preserve_cwd_logs()
    try:
        test_perform_is_the_click()
        test_perform_refuses_what_the_offer_does_not_name()
        test_perform_asks_authorize()
        test_the_handler_guards_moved_with_their_bodies()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All perform tests passed!")
