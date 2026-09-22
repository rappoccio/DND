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

from actions import (ActionMenu, Action, BUILT_GROUPS, GROUP_SESSION, GROUP_TURN,
                     GROUP_ACTION, GROUP_BONUS, GROUP_PORTENT, GROUP_UTILITY)
import pygame
import rpg_battle_map as rpg

from gui_driver import post_click
from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _idx, _goto,
                               _item, _reclass, _set_conditions, _snapshot_baseline,
                               _weapon, _preserve_cwd_logs, _restore_cwd_logs)


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)      # `_reclass` restores this; see test_combat_panel.py
    return app


def _ids(app, idx):
    return [a.id for a in ActionMenu.build(app, idx)]


def _by_id(app, idx):
    return {a.id: a for a in ActionMenu.build(app, idx)}


def _group(app, idx, group):
    """The ids of one group, in build order — which for §4 IS the column order."""
    return [a.id for a in ActionMenu.build(app, idx) if a.group == group]


def _give_nick_offhand(app, idx):
    """A Dagger in the off-hand: its mastery is Nick, and Aria (Fighter) already has
    the "Weapon Mastery" feat from `initialize_class_resources` (class_resources.cpp:866)."""
    ws = app.combat.get_agent_weapons(app.bm, idx)
    ws[1] = _weapon(app, "Dagger", off_hand=True)
    app.combat.set_agent_weapons(app.bm, idx, ws)
    _set_conditions(app, idx, offhand_attack_used=False)


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
#  §4 — the Action economy band (M2b)
# ─────────────────────────────────────────────────────────────────────────────
#
# The five-way branch is the first real branch structure in this module, so each arm
# gets a check that names it. Build ORDER matters here in a way it did not for §1/§3:
# `_draw_action_row` assigns columns by position, so the five-up posture row is
# correct only if the menu emits those five in column order.


def test_the_band_collapses_when_the_creature_cannot_act():
    """Arm 1. Incapacitated and unconscious are separate flags and either one does it;
    the panel replaces the whole band with "[Cannot act — …]"."""
    app = _app()
    aria = _goto(app, "Aria")
    assert _group(app, aria, GROUP_ACTION), "the band should be open to start with"
    for flag in ("incapacitated", "unconscious"):
        _set_conditions(app, aria, **{flag: True})
        assert _group(app, aria, GROUP_ACTION) == [], flag
        _set_conditions(app, aria, **{flag: False})
    print("✅ test_the_band_collapses_when_the_creature_cannot_act passed")


def test_the_spent_action_arm_offers_nick_or_nothing():
    """Arm 2. "[Action used]" is not necessarily an empty arm: Nick relocates the
    off-hand attack into the Attack action that was just spent, and it is the one
    thing that can still appear there."""
    app = _app()
    aria = _goto(app, "Aria")
    app.action_used = True
    assert _group(app, aria, GROUP_ACTION) == [], "a Shortsword off-hand has no Nick"

    _give_nick_offhand(app, aria)
    assert _group(app, aria, GROUP_ACTION) == ["nick"]

    # Spending the off-hand attack takes it away again — the same three-part guard
    # `_nick_offhand_idx` has always applied, now asked without drawing a frame.
    _set_conditions(app, aria, offhand_attack_used=True)
    assert _group(app, aria, GROUP_ACTION) == []
    print("✅ test_the_spent_action_arm_offers_nick_or_nothing passed")


def test_frightened_offers_dash_and_nothing_else():
    """Arm 3. Not "Dash is highlighted" — Dash is the entire band."""
    app = _app()
    aria = _goto(app, "Aria")
    _set_conditions(app, aria, frightened=True)
    assert _group(app, aria, GROUP_ACTION) == ["dash"]
    _set_conditions(app, aria, frightened=False)
    assert len(_group(app, aria, GROUP_ACTION)) > 1
    print("✅ test_frightened_offers_dash_and_nothing_else passed")


def test_the_open_band_is_built_in_column_order():
    """Arm 4, and the invariant `_draw_action_row` depends on. Aria has weapons and no
    spells; Brannor has both, and Cast Spell is appended after the posture row."""
    app = _app()
    aria = _goto(app, "Aria")
    assert _group(app, aria, GROUP_ACTION) == [
        "atk_action", "unarmed",
        "dash", "dodge", "disengage", "hide", "prone",
    ]
    brannor = _goto(app, "Brannor")
    assert _group(app, brannor, GROUP_ACTION)[-1] == "spell_action"
    assert "spell_action" not in _group(app, aria, GROUP_ACTION)
    print("✅ test_the_open_band_is_built_in_column_order passed")


def test_prone_swaps_stand_up_into_the_last_column():
    """Arm 5. The fifth column is "change your posture" and is never empty — which is
    why the row's width is the same whichever way it points."""
    app = _app()
    aria = _goto(app, "Aria")
    _set_conditions(app, aria, prone=True)
    ids = _group(app, aria, GROUP_ACTION)
    assert ids[-1] == "standup" and "prone" not in ids, ids
    _set_conditions(app, aria, prone=False)
    ids = _group(app, aria, GROUP_ACTION)
    assert ids[-1] == "prone" and "standup" not in ids, ids
    print("✅ test_prone_swaps_stand_up_into_the_last_column passed")


def test_mid_sequence_keeps_the_band_open_and_counts_the_attacks():
    """`action_used` goes True the moment an Attack action starts, but Extra Attack
    still owes swings. The band must stay open for them, and the Attack label carries
    the count — the one piece of §4 that is state rather than a constant."""
    app = _app()
    aria = _goto(app, "Aria")
    assert _by_id(app, aria)["atk_action"].label == "⚔ Attack"

    app.action_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "action"
    ids = _group(app, aria, GROUP_ACTION)
    assert "atk_action" in ids and "unarmed" in ids, ids
    assert _by_id(app, aria)["atk_action"].label == "⚔ Attack (2)"

    # A sequence parked in the BONUS band is not this one, and does not reopen §4.
    app._attack_sequence_slot = "bonus"
    assert _group(app, aria, GROUP_ACTION) == [], "the bonus slot reopened the Action band"
    print("✅ test_mid_sequence_keeps_the_band_open_and_counts_the_attacks passed")


# ─────────────────────────────────────────────────────────────────────────────
#  §6 — Portent dice (M2b)
# ─────────────────────────────────────────────────────────────────────────────


def test_portent_needs_a_diviner_and_an_unspent_die():
    """§6 is the section whose heading IS its predicate: the panel prints "Portent
    Dice:" and the readout exactly when this action is on offer, so all three of the
    guards below also decide whether the section exists at all."""
    app = _app()
    cyra = _goto(app, "Cyra")
    assert _group(app, cyra, GROUP_PORTENT) == [], "a Sorcerer has no Portent"

    st = app.combat.get_agent_stats(app.bm, cyra)
    st.set_class_level(rpg.CharacterClass.Wizard, 3)
    st.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    app.combat.set_agent_stats(app.bm, cyra, st)
    assert _group(app, cyra, GROUP_PORTENT) == [], "a non-Diviner Wizard has no Portent"

    st = app.combat.get_agent_stats(app.bm, cyra)
    st.wizard_subclass = rpg.WizardSubclass.Diviner
    app.combat.set_agent_stats(app.bm, cyra, st)
    assert _group(app, cyra, GROUP_PORTENT) == [], "a Diviner holding no dice has none to spend"

    st = app.combat.get_agent_stats(app.bm, cyra)
    st.portent_dice = [17, 3]
    app.combat.set_agent_stats(app.bm, cyra, st)
    assert _group(app, cyra, GROUP_PORTENT) == ["use_portent"]

    # Portent is deliberately NOT gated on the Action band: it is a reroll, not an
    # action, and the panel has always drawn §6 while §4 is collapsed.
    _set_conditions(app, cyra, incapacitated=True)
    assert _group(app, cyra, GROUP_ACTION) == []
    assert _group(app, cyra, GROUP_PORTENT) == ["use_portent"]
    _set_conditions(app, cyra, incapacitated=False)
    print("✅ test_portent_needs_a_diviner_and_an_unspent_die passed")


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


def test_click_reaches_the_handler_for_the_action_band():
    """§4's dispatch, end to end. Dodge and the posture pair are picked because each
    lands a state change no other button could have made."""
    app = _app()
    aria = _goto(app, "Aria")

    _draw(app)
    _click_action(app, "dodge")
    assert app.action_used, "Dodge did not reach the handler"

    _goto(app, "Aria")
    _draw(app)
    _click_action(app, "prone")
    assert app.bm.placed_agents[aria].conditions.prone, "Go Prone did not reach the handler"

    _goto(app, "Aria")
    _draw(app)
    assert "standup" in app._action_menu, "the prone creature was not offered Stand Up"
    _click_action(app, "standup")
    assert not app.bm.placed_agents[aria].conditions.prone, \
        "Stand Up did not reach the handler"
    print("✅ test_click_reaches_the_handler_for_the_action_band passed")


def test_dash_is_drawn_mid_sequence_but_the_click_is_refused():
    """D-M2-4, the M2b sibling of `test_end_turn_click_is_refused_while_paused`.

    Mid-sequence the band stays open for the swings still owed, so Dash IS drawn and
    IS on offer — and the handler's `not self.action_used` gate refuses it anyway.
    That gate looks like availability and is not; moving it into `ActionMenu` would
    make the whole row vanish in the middle of an Extra Attack.
    """
    app = _app()
    aria = _goto(app, "Aria")
    app.action_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "action"

    _draw(app)
    assert "dash" in app._action_menu, "the mid-sequence band should still draw Dash"
    before = app.bm.placed_agents[aria].walk_remaining
    _click_action(app, "dash")
    assert app.bm.placed_agents[aria].walk_remaining == before, \
        "Dash was honoured with the Action already spent"
    print("✅ test_dash_is_drawn_mid_sequence_but_the_click_is_refused passed")


def test_stand_up_from_a_stale_rect_does_nothing():
    """M2b's copy of the M2a regression, on a button whose handler has NO gate of its
    own: `btn_cbt_standup` is dispatched on availability alone, so if the ActionMenu
    were not consulted a stale rect would stand a creature up that is not prone.

    Verified the way the M2a note insists on: with `_action_clicked("standup", …)`
    swapped back to `self.btn_cbt_standup.clicked(event)`, this fails — the log gains
    "Aria: Standing up".
    """
    app = _app()
    aria = _goto(app, "Aria")
    _draw(app)
    assert "standup" not in app._action_menu, "Aria is not prone and must not be offered it"

    victim = app._cbt_btn("standup")
    victim.rect = _free_point(app)              # a live-looking, unclaimed spot
    turn_before = (app.turn_idx, app.round_num)
    post_click(app, victim.rect.center)
    assert not any("Standing up" in line for line in app.combat_log), \
        "an unoffered Stand Up fired from a stale rect"
    assert (app.turn_idx, app.round_num) == turn_before, \
        "the probe point was not free after all — something else consumed the click"
    print("✅ test_stand_up_from_a_stale_rect_does_nothing passed")


# ─────────────────────────────────────────────────────────────────────────────
#  §7 — the Bonus Action mega-section, bucket 7a (M2c)
# ─────────────────────────────────────────────────────────────────────────────
#
# 56 buttons, and what they mostly have in common is the band gate: one
# `if not incapacitated and not bonus_used:` wrapping the great majority of the
# section, whatever an individual feature's real action cost is. These checks are
# about the gate and the ordering contract, not about re-asserting fifty class
# predicates one at a time — the panel golden already pins each of those at a
# checkpoint, which is what M2c's first commit was for.


def _bonus(app, idx):
    return _group(app, idx, GROUP_BONUS)


def test_the_bonus_section_collapses_when_the_creature_cannot_act():
    """Same rule as §4's arm 1, and the panel prints "[Cannot act]" once for both."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
                    monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    assert _bonus(app, cyra), "a Monk 17 should have a band to start with"
    for flag in ("incapacitated", "unconscious"):
        _set_conditions(app, cyra, **{flag: True})
        assert _bonus(app, cyra) == [], flag
        _set_conditions(app, cyra, **{flag: False})
    print("✅ test_the_bonus_section_collapses_when_the_creature_cannot_act passed")


def test_spending_the_bonus_action_takes_action_surge_with_it():
    """The band gate, stated on the button that most looks like an exception.

    `btn_cbt_action_surge`'s own comment says "available anytime" and Action Surge
    costs no bonus action — but it is written inside the band block, so spending the
    Bonus Action hides it. Checkpoint 03 is the golden's record of that. M2 preserves
    behaviour, so this pins it rather than fixing it; whether the panel is RIGHT here
    is a separate item.
    """
    app = _app()
    aria = _goto(app, "Aria")                      # Fighter 5
    assert "action_surge" in _bonus(app, aria)
    assert "second_wind" in _bonus(app, aria)
    app.bonus_used = True
    assert _bonus(app, aria) == [], _bonus(app, aria)
    print("✅ test_spending_the_bonus_action_takes_action_surge_with_it passed")


def test_use_item_and_extinguish_are_outside_the_band():
    """The two 7a guards that are NOT band-gated — which is why the plan's `economy`
    field cannot be a boolean.

    Extinguish costs an Action, so a spent Bonus Action leaves it alone and a spent
    Action removes it. Use Item is finer than either: it asks each carried item what
    THAT item costs. A potion is a Bonus Action and drops out with the band; a thrown
    flask replaces one attack of the Attack action and does not.
    """
    app = _app()
    skarn = _goto(app, "Skarn")
    _set_conditions(app, skarn, burning=True)
    try:
        # A potion alone: Use Item is band-gated after all, for this inventory.
        app.combat.set_agent_items(app.bm, skarn, [])
        app.combat.add_item_to_agent(app.bm, skarn, _item("Potion of Healing"))
        assert set(_bonus(app, skarn)) == {"use_item", "extinguish"}, _bonus(app, skarn)
        app.bonus_used = True
        assert _bonus(app, skarn) == ["extinguish"], _bonus(app, skarn)

        # Add a flask and it comes back, with the Bonus Action still spent.
        app.combat.add_item_to_agent(app.bm, skarn, _item("Alchemist\'s Fire"))
        assert set(_bonus(app, skarn)) == {"use_item", "extinguish"}, _bonus(app, skarn)

        # Extinguish is the one that answers to the Action.
        app.action_used = True
        assert "extinguish" not in _bonus(app, skarn), _bonus(app, skarn)
    finally:
        _set_conditions(app, skarn, burning=False)
        app.combat.set_agent_items(app.bm, skarn, [])
    print("✅ test_use_item_and_extinguish_are_outside_the_band passed")


def test_the_bonus_runs_are_built_in_draw_order():
    """§7's analog of `test_the_open_band_is_built_in_column_order`.

    `_draw_action_stack` draws a run in the order the MENU emits it, and the
    `_BON_RUN_*` tuples in main.py are the panel's draw order written down. If the two
    ever disagree the panel still renders — it just renders Rage above Patient Defense,
    which no availability test would catch. So the invariant is: for every run, the
    ids the menu emits from it appear in the tuple's order.
    """
    import main
    runs = [v for k, v in vars(main).items() if k.startswith("_BON_RUN_")]
    assert len(runs) == 6, runs

    app = _app()
    seen = 0
    for who, cls, lvl, fields in (
            ("Cyra", rpg.CharacterClass.Monk, 17,
             dict(monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)),
            ("Cyra", rpg.CharacterClass.Paladin, 20,
             dict(paladin_oath=rpg.PaladinOath.OathOfVengeance)),
            ("Cyra", rpg.CharacterClass.Sorcerer, 18,
             dict(sorcerer_subclass=rpg.SorcererSubclass.Clockwork)),
            ("Cyra", rpg.CharacterClass.Ranger, 14,
             dict(ranger_subclass=rpg.RangerSubclass.BeastMaster))):
        idx = _reclass(app, who, cls, lvl, **fields)
        built = _bonus(app, idx)
        for run in runs:
            got = [i for i in built if i in run]
            if len(got) < 2:
                continue                       # nothing to be out of order
            seen += 1
            want = [i for i in run if i in got]
            assert got == want, (cls, run, got, want)
    assert seen >= 4, f"only {seen} runs were exercised with 2+ members"
    print("✅ test_the_bonus_runs_are_built_in_draw_order passed")


def test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable():
    """F11, pinned so nobody "fixes" the conversion into changing behaviour.

    The panel's Step of the Wind guard has a second arm — Open Hand L11 Fleet Step, a
    free Step of the Wind explicitly "when the bonus action is already spent" — written
    INSIDE the band block that has already required `not bonus_used`. It can therefore
    never fire. `ActionMenu._bonus` reproduces it in that shape, so the arm stays dead
    and the panel is unchanged. Making it live is a behaviour change and its own item.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 11,
                    monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    _set_conditions(app, cyra, fleet_step_used=False)
    assert "step_of_wind" in _bonus(app, cyra), "the normal arm should be offered"
    app.bonus_used = True
    assert "step_of_wind" not in _bonus(app, cyra), \
        "the Fleet Step arm became reachable — that is a behaviour change, not a tidy-up"
    print("✅ test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable passed")


def test_a_click_on_an_unoffered_bonus_action_does_nothing():
    """The M2a/M2b regression again, on §7 — where it matters most, because this is
    the section with 56 widgets fighting over one column of pixels and the stale-rect
    guard is the only thing that ever separated them.

    Rage is the probe: its handler spends the Bonus Action unconditionally, whatever
    `activate_rage` does with a Fighter, so `app.bonus_used` is a clean observable.

    Verified the way the M2a note insists on: with `_action_clicked("rage", …)` swapped
    back to `self.btn_cbt_rage.clicked(event)`, this fails — Aria's Bonus Action is
    spent by a button she was never offered.
    """
    app = _app()
    aria = _goto(app, "Aria")                       # Fighter: no Rage, ever
    _draw(app)
    assert "rage" not in app._action_menu, "Aria must not be offered Rage"

    victim = app._cbt_btn("rage")
    victim.rect = _free_point(app)                  # a live-looking, unclaimed spot
    turn_before = (app.turn_idx, app.round_num)
    post_click(app, victim.rect.center)
    assert not app.bonus_used, "an unoffered Rage spent the Bonus Action from a stale rect"
    assert (app.turn_idx, app.round_num) == turn_before, \
        "the probe point was not free after all — something else consumed the click"
    print("✅ test_a_click_on_an_unoffered_bonus_action_does_nothing passed")


def test_click_reaches_the_handler_for_the_bonus_band():
    """Dispatch, end to end, on a converted §7 button. Second Wind is picked because
    it lands a state change nothing else in the frame could have made: HP goes up and
    the resource goes down."""
    app = _app()
    aria = _goto(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria)
    s.hp_cur = 10
    app.combat.set_agent_stats(app.bm, aria, s)
    before = app.combat.get_agent_stats(app.bm, aria).get_resource("Second Wind").current

    _draw(app)
    assert "second_wind" in app._action_menu
    _click_action(app, "second_wind")

    after = app.combat.get_agent_stats(app.bm, aria)
    assert after.hp_cur > 10, "Second Wind did not reach the handler"
    assert after.get_resource("Second Wind").current == before - 1, "no use was spent"
    assert app.bonus_used, "the Bonus Action was not spent"
    print("✅ test_click_reaches_the_handler_for_the_bonus_band passed")


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
        test_the_band_collapses_when_the_creature_cannot_act()
        test_the_spent_action_arm_offers_nick_or_nothing()
        test_frightened_offers_dash_and_nothing_else()
        test_the_open_band_is_built_in_column_order()
        test_prone_swaps_stand_up_into_the_last_column()
        test_mid_sequence_keeps_the_band_open_and_counts_the_attacks()
        test_portent_needs_a_diviner_and_an_unspent_die()
        test_click_reaches_the_handler_for_the_action_band()
        test_dash_is_drawn_mid_sequence_but_the_click_is_refused()
        test_stand_up_from_a_stale_rect_does_nothing()
        test_the_bonus_section_collapses_when_the_creature_cannot_act()
        test_spending_the_bonus_action_takes_action_surge_with_it()
        test_use_item_and_extinguish_are_outside_the_band()
        test_the_bonus_runs_are_built_in_draw_order()
        test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable()
        test_a_click_on_an_unoffered_bonus_action_does_nothing()
        test_click_reaches_the_handler_for_the_bonus_band()
        test_ids_are_unique()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All ActionMenu tests passed!")
