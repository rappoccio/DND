#!/usr/bin/env python3
"""Unit tests for `actions.ActionMenu` (MULTIPLAYER_PLAN.md M2, seam S3).

`test_combat_panel.py` proves the *panel* did not change. This suite proves the thing
the panel now asks — availability, with no screen in the room at all. That split is
the point of M2: until now the only way to ask "may this creature drop its off-hand?"
was to render a frame and look at a rect.

Scope tracks the M2a–M2e work order. Only the sections `actions.BUILT_GROUPS` names
are converted; every other `btn_cbt_*` is still drawn by the old fused code, so a
missing id here means "not yet converted", never "illegal".

The scene is `test_combat_panel.py`'s — imported rather than copied, so the two
suites can never drift into testing different worlds.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from actions import ActionMenu, Action, BUILT_GROUPS, GROUP_SESSION, GROUP_TURN, GROUP_UTILITY
import pygame

from gui_driver import post_click
from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _idx, _goto,
                               _set_conditions, _preserve_cwd_logs, _restore_cwd_logs)


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    return app


def _ids(app, idx):
    return [a.id for a in ActionMenu.build(app, idx)]


def _by_id(app, idx):
    return {a.id: a for a in ActionMenu.build(app, idx)}


def test_build_returns_only_converted_groups():
    """Nothing from an unconverted section leaks in early — M2b would silently
    double-draw its buttons if it did."""
    app = _app()
    aria = _goto(app, "Aria")
    for a in ActionMenu.build(app, aria):
        assert isinstance(a, Action), a
        assert a.group in BUILT_GROUPS, f"{a.id} is in unconverted group {a.group!r}"
    print("✅ test_build_returns_only_converted_groups passed")


def test_every_action_has_a_widget_and_is_enabled():
    """Two invariants the panel relies on: an id names a real `btn_cbt_*`, and — for
    as long as `widgets.Button` has no grey state — nothing is built disabled."""
    app = _app()
    aria = _goto(app, "Aria")
    for a in ActionMenu.build(app, aria):
        assert hasattr(app, "btn_cbt_" + a.id), f"no widget for action {a.id!r}"
        assert a.enabled and not a.disabled_reason, f"{a.id} built disabled"
        assert a.label, f"{a.id} has no label"
        assert a.expects == "none", f"{a.id} expects {a.expects!r}"
    print("✅ test_every_action_has_a_widget_and_is_enabled passed")


def test_session_group_is_unconditional_and_labels_the_pause_state():
    """§1 is two DM tools that are always on offer; only the label is state."""
    app = _app()
    aria = _goto(app, "Aria")

    app.combat_paused = False
    assert _by_id(app, aria)["pause_resume"].label == "⏸ Pause"
    app.combat_paused = True
    assert _by_id(app, aria)["pause_resume"].label == "▶ Resume"
    app.combat_paused = False

    for idx in (aria, -1, 999):
        ids = _ids(app, idx)
        assert "pause_resume" in ids and "end_combat" in ids, idx
    print("✅ test_session_group_is_unconditional_and_labels_the_pause_state passed")


def test_end_turn_is_offered_even_while_paused():
    """Deliberate, and load-bearing: the panel draws End Turn in every branch and the
    CLICK HANDLER is what refuses a paused advance. Turning this into an availability
    rule would change what the panel renders, which M2 forbids."""
    app = _app()
    aria = _goto(app, "Aria")
    assert "end_turn" in _ids(app, aria)
    app.combat_paused = True
    assert "end_turn" in _ids(app, aria)
    app.combat_paused = False
    print("✅ test_end_turn_is_offered_even_while_paused passed")


def test_drop_concentration_follows_the_condition():
    app = _app()
    brannor = _goto(app, "Brannor")
    assert "drop_concentration" not in _ids(app, brannor)
    _set_conditions(app, brannor, concentrating=True)
    assert "drop_concentration" in _ids(app, brannor)
    _set_conditions(app, brannor, concentrating=False)
    assert "drop_concentration" not in _ids(app, brannor)
    print("✅ test_drop_concentration_follows_the_condition passed")


def test_drop_weapon_offers_one_action_per_droppable_slot():
    """A slot is droppable when it holds a named weapon that is not permanently armed.
    The engine always returns three slots, so "empty" is a name test — and the panel's
    row width is a function of how many survive it."""
    app = _app()
    skarn = _goto(app, "Skarn")
    drops = [i for i in _ids(app, skarn) if i.startswith("drop_weapon_")]
    assert drops == ["drop_weapon_main", "drop_weapon_off", "drop_weapon_rng"], drops

    ws = app.combat.get_agent_weapons(app.bm, skarn)
    ws[1].permanently_armed = True          # a natural weapon cannot be dropped
    app.combat.set_agent_weapons(app.bm, skarn, ws)
    drops = [i for i in _ids(app, skarn) if i.startswith("drop_weapon_")]
    assert drops == ["drop_weapon_main", "drop_weapon_rng"], drops

    # Order is slot order, never "the surviving ones renumbered" — the panel packs
    # them left to right, so a renumber would move Drop Rng under Drop Off's label.
    labels = [a.label for a in ActionMenu.build(app, skarn)
              if a.id.startswith("drop_weapon_")]
    assert labels == ["Drop Main", "Drop Rng"], labels
    print("✅ test_drop_weapon_offers_one_action_per_droppable_slot passed")


def test_out_of_range_agent_yields_only_the_creature_free_groups():
    """Between turns, or with combat over, `_current_agent_idx()` is out of range. The
    session group and Place Terrain survive; nothing that reads a creature does."""
    app = _app()
    for idx in (-1, len(app.bm.placed_agents), 10_000):
        ids = _ids(app, idx)
        assert ids == ["pause_resume", "end_combat", "end_turn", "place_terrain"], (idx, ids)
    print("✅ test_out_of_range_agent_yields_only_the_creature_free_groups passed")


def test_build_does_not_mutate_the_app():
    """`build` runs once per frame and M3 will run it per viewer; a hidden write would
    be a per-frame side effect that nothing in the codebase expects."""
    app = _app()
    aria = _goto(app, "Aria")
    before = (app.action_used, app.bonus_used, app.turn_idx,
              app.combat_paused, app.attacks_remaining,
              [a.name for a in app.bm.placed_agents])
    first = [(a.id, a.label) for a in ActionMenu.build(app, aria)]
    second = [(a.id, a.label) for a in ActionMenu.build(app, aria)]
    after = (app.action_used, app.bonus_used, app.turn_idx,
             app.combat_paused, app.attacks_remaining,
             [a.name for a in app.bm.placed_agents])
    assert first == second, "build is not idempotent"
    assert before == after, "build mutated the app"
    print("✅ test_build_does_not_mutate_the_app passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The click path
# ─────────────────────────────────────────────────────────────────────────────
#
# `ActionMenu` decides and `_draw_combat_panel` lays out; what follows checks that a
# real mouse-down on the result reaches the handler, through `App._handle_events`
# exactly as the DM's own click does. This is the half of M2 acceptance the plan says
# the headless suite cannot reach — it reaches most of it. What stays manual is how
# the panel LOOKS, which no assertion here claims to cover.


def _draw(app):
    """One panel frame: positions every widget and refreshes `app._action_menu`."""
    app._draw_combat_panel()


def _click_action(app, action_id):
    post_click(app, app._cbt_btn(action_id).rect.center)


def test_click_reaches_the_handler_for_each_converted_action():
    app = _app()
    aria = _goto(app, "Aria")

    _draw(app)
    _click_action(app, "pause_resume")
    assert app.combat_paused, "Pause did not reach the handler"
    _draw(app)
    assert app._action_menu["pause_resume"].label == "▶ Resume"
    _click_action(app, "pause_resume")
    assert not app.combat_paused, "Resume did not reach the handler"

    _goto(app, "Brannor")
    brannor = _idx(app, "Brannor")
    _set_conditions(app, brannor, concentrating=True)
    _draw(app)
    _click_action(app, "drop_concentration")
    assert not app.bm.placed_agents[brannor].conditions.concentrating, \
        "Drop Concentration did not reach the handler"

    skarn = _goto(app, "Skarn")
    assert app.combat.get_agent_weapons(app.bm, skarn)[0].name == "Greataxe"
    _draw(app)
    _click_action(app, "drop_weapon_main")
    # The slot falls back to Unarmed rather than emptying — a creature always has fists.
    assert app.combat.get_agent_weapons(app.bm, skarn)[0].name == "Unarmed", \
        "Drop Main did not reach the handler"

    before = app.turn_idx
    _goto(app, "Aria")
    _draw(app)
    _click_action(app, "end_turn")
    assert app.turn_idx != before or app.round_num > 1, "End Turn did not advance the turn"
    print("✅ test_click_reaches_the_handler_for_each_converted_action passed")


def test_end_turn_click_is_refused_while_paused():
    """The paused refusal lives in the handler, not in availability (see
    `test_end_turn_is_offered_even_while_paused`). Prove it still bites."""
    app = _app()
    _goto(app, "Aria")
    app.combat_paused = True
    _draw(app)
    before = (app.turn_idx, app.round_num)
    _click_action(app, "end_turn")
    assert (app.turn_idx, app.round_num) == before, "End Turn advanced a paused combat"
    app.combat_paused = False
    print("✅ test_end_turn_click_is_refused_while_paused passed")


def _free_point(app):
    """A panel pixel no drawn widget occupies, so a click there is attributable.

    Without this the test is vacuous: planting the stale rect on top of End Turn made
    the click fire End Turn too, which advanced the turn — and `_drop_concentration`
    then acted on a different creature, so the assertion held even with the gate
    removed. The point must belong to the victim and to nothing else.
    """
    from widgets import Button
    rects = [b.rect for b in vars(app).values() if isinstance(b, Button)]
    px, w = app._panel_x() + app._PANEL_PAD, 200
    for y in range(40, app.screen.get_height() - 40, 6):
        probe = pygame.Rect(px, y, w, app._BTN_H)
        if not any(probe.colliderect(r) for r in rects):
            return probe
    raise AssertionError("no free strip in the panel")


def test_a_click_on_an_unoffered_action_does_nothing():
    """The regression M2a exists to make impossible.

    Until now an undrawn button was kept harmless by the stale-rect guard parking it at
    x = -10000 — a hack, and one Step 0.3's F4 found a hole in. Dispatch is gated on
    the ActionMenu now, so a widget sitting at a perfectly clickable location whose
    action is NOT on offer must still do nothing. The rect is planted deliberately:
    it is exactly the stale position the guard used to have to clean up.

    Checked against the pre-M2a call site — with `_action_clicked` swapped back for
    `btn_cbt_drop_concentration.clicked(event)`, this fails.
    """
    app = _app()
    brannor = _goto(app, "Brannor")
    _draw(app)
    assert "drop_concentration" not in app._action_menu, "Brannor should not be concentrating"

    victim = app._cbt_btn("drop_concentration")
    victim.rect = _free_point(app)                     # a live-looking, unclaimed spot
    _set_conditions(app, brannor, concentrating=True)  # something to lose
    turn_before = (app.turn_idx, app.round_num)
    post_click(app, victim.rect.center)
    assert app.bm.placed_agents[brannor].conditions.concentrating, \
        "an unoffered action fired from a stale rect"
    assert (app.turn_idx, app.round_num) == turn_before, \
        "the probe point was not free after all — something else consumed the click"
    _set_conditions(app, brannor, concentrating=False)
    print("✅ test_a_click_on_an_unoffered_action_does_nothing passed")


def test_ids_are_unique():
    """The panel keys widgets by id and `_handle_events` dispatches on it; a duplicate
    would make one of the two unreachable in a way no golden could show."""
    app = _app()
    for who in ("Aria", "Skarn", "Brannor", "Cyra"):
        idx = _goto(app, who)
        ids = _ids(app, idx)
        assert len(ids) == len(set(ids)), (who, ids)
    print("✅ test_ids_are_unique passed")


if __name__ == "__main__":
    # `_start_combat` truncates replay_log.txt / combat_log.txt in the cwd (gui/, per
    # the runner). Those are the live session's logs, not test artifacts — same
    # courtesy test_combat_panel.py extends, and this suite calls it nine times.
    _saved = _preserve_cwd_logs()
    try:
        test_build_returns_only_converted_groups()
        test_every_action_has_a_widget_and_is_enabled()
        test_session_group_is_unconditional_and_labels_the_pause_state()
        test_end_turn_is_offered_even_while_paused()
        test_drop_concentration_follows_the_condition()
        test_drop_weapon_offers_one_action_per_droppable_slot()
        test_out_of_range_agent_yields_only_the_creature_free_groups()
        test_build_does_not_mutate_the_app()
        test_click_reaches_the_handler_for_each_converted_action()
        test_end_turn_click_is_refused_while_paused()
        test_a_click_on_an_unoffered_action_does_nothing()
        test_ids_are_unique()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All ActionMenu tests passed!")
