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
                     GROUP_ACTION, GROUP_BONUS, GROUP_PORTENT, GROUP_UTILITY,
                     ECONOMY, METAMAGIC_OPTIONS, METAMAGIC_ID_BY_VALUE)
import pygame
import rpg_battle_map as rpg

from menus import panel

from gui_driver import post_click
from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _idx, _goto,
                               _item, _reclass, _set_conditions, _set_res,
                               _snapshot_baseline, _spell, _weapon,
                               _preserve_cwd_logs, _restore_cwd_logs)


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
        assert "pause_resume" in ids and "reaction_timer" in ids and "end_combat" in ids, idx
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
    session group and Place Terrain survive; nothing that reads a creature does.

    Jump was the exception — **F13**, fixed in M2e. The Jump/Shove row's only
    per-creature test is the adjacency scan, which decides the row's WIDTH and not
    whether it exists, so out of range the band stood open over a Jump button for a
    creature that was not there. §4 had the same shape (F7) and M2b changed it; this is
    the same answer one section down, and the band flag no longer decides anything
    here."""
    app = _app()
    for idx in (-1, len(app.bm.placed_agents), 10_000):
        for spent in (False, True):
            app.bonus_used = spent
            ids = _ids(app, idx)
            assert ids == ["pause_resume", "reaction_timer", "end_combat", "table",
                           "end_turn", "place_terrain"], (idx, spent, ids)
        app.bonus_used = False
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
# `panel.draw_action_row` assigns columns by position, so the five-up posture row is
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
    """Arm 4, and the invariant `panel.draw_action_row` depends on. Aria has weapons and no
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
    post_click(app, panel.cbt_btn(app, action_id).rect.center)


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

    victim = panel.cbt_btn(app, "drop_concentration")
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

    victim = panel.cbt_btn(app, "standup")
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


# Bucket 7c's row shares the band with everything else in §7 and depends on where the
# other tokens are standing, not on the creature — so a check about SOMETHING ELSE in
# §7 subtracts it rather than asserting it away.
_SPATIAL = ("long_jump", "shove_push", "shove_prone", "grapple_esc")


def _bonus_but_the_row(app, idx):
    return [i for i in _bonus(app, idx) if i not in _SPATIAL]


def _place_duplicate(app, caster_idx, col=1, row=1):
    """One Invoke Duplicity illusion, spawned as `_resolve_invoke_duplicity` spawns it.

    Far from everybody, so it cannot perturb the adjacency scan the row above reads.
    """
    cfg = rpg.AgentConfig()
    cfg.name      = "Duplicate"
    cfg.size      = 1
    cfg.start_col = col
    cfg.start_row = row
    idx = app.bm.spawn_agent(cfg)
    app.bm.set_agent_summoner_idx(idx, caster_idx)
    app.bm.set_agent_summon_spell(idx, "Invoke Duplicity")
    return idx


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
        assert set(_bonus_but_the_row(app, skarn)) == {"use_item", "extinguish"}, \
            _bonus(app, skarn)
        app.bonus_used = True
        assert _bonus_but_the_row(app, skarn) == ["extinguish"], _bonus(app, skarn)

        # Add a flask and it comes back, with the Bonus Action still spent.
        app.combat.add_item_to_agent(app.bm, skarn, _item("Alchemist\'s Fire"))
        assert set(_bonus_but_the_row(app, skarn)) == {"use_item", "extinguish"}, \
            _bonus(app, skarn)

        # Extinguish is the one that answers to the Action.
        app.action_used = True
        assert "extinguish" not in _bonus(app, skarn), _bonus(app, skarn)

        # And the same two facts, said as data rather than as three assertions about
        # which flag hides what. This is the field the docstring above is about.
        app.action_used = False
        priced = _by_id(app, skarn)
        assert priced["use_item"].economy == "varies", priced["use_item"]
        assert priced["extinguish"].economy == "action", priced["extinguish"]
    finally:
        _set_conditions(app, skarn, burning=False)
        app.combat.set_agent_items(app.bm, skarn, [])
    print("✅ test_use_item_and_extinguish_are_outside_the_band passed")


def test_the_economy_band_headers_are_the_bands_own_two_buttons():
    """Bucket 7b, the half of F3 that was still open.

    The row is a fixed two-column band whose members are independent: the spell half
    follows the spell list, the attack half follows the off-hand, and a creature can
    be offered either, both or neither while the band stands open. The panel USED to
    set the attack half's rect and then not draw it, which is what made a click in
    that space fire on an option it was not offering; an id the menu does not build
    is not laid out at all.
    """
    app = _app()
    aria = _goto(app, "Aria")            # an off-hand, no spells
    got = _bonus(app, aria)
    assert "atk_bonus" in got and "spell_bonus" not in got, got

    cyra = _goto(app, "Cyra")            # spells, no off-hand
    got = _bonus(app, cyra)
    assert "spell_bonus" in got and "atk_bonus" not in got, got

    skarn = _goto(app, "Skarn")          # neither: the band is open over an empty row
    got = _bonus(app, skarn)
    assert "atk_bonus" not in got and "spell_bonus" not in got, got

    # Both, which is the arm checkpoint 64 had to be written to reach.
    aria = _goto(app, "Aria")
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Fire Bolt")])
    got = _bonus(app, aria)
    assert got[:2] == ["atk_bonus", "spell_bonus"], got
    app.combat.set_agent_spells(app.bm, aria, [])
    print("✅ test_the_economy_band_headers_are_the_bands_own_two_buttons passed")


def test_the_bonus_band_stays_open_for_a_bonus_slot_sequence():
    """§7's own `mid_sequence`, and the one gate in the section that is not the band.

    `bonus_used` goes True the moment an off-hand sequence starts, but the sequence
    still owes swings — so the header row survives it and takes the count into its
    LABEL, while the rest of §7 goes away with the band. That pairing is what made 7b
    its own bucket: the layout and the label come from the same two fields.
    """
    app = _app()
    aria = _goto(app, "Aria")
    assert _by_id(app, aria)["atk_bonus"].label == "⚔ Bonus Atk"

    app.bonus_used = True
    assert "atk_bonus" not in _bonus(app, aria), "spent, and no sequence running"
    assert "second_wind" not in _bonus(app, aria), "the rest of the band went with it"

    app.attacks_remaining = 2
    app._attack_sequence_slot = "bonus"
    got = _by_id(app, aria)
    assert got["atk_bonus"].label == "⚔ Bonus (2)", got["atk_bonus"]
    assert "second_wind" not in got, "only the header row comes back"

    # The ACTION slot's sequence is a different field and must not reopen this band.
    app._attack_sequence_slot = "action"
    assert "atk_bonus" not in _bonus(app, aria), _bonus(app, aria)
    print("✅ test_the_bonus_band_stays_open_for_a_bonus_slot_sequence passed")


def test_the_bonus_attack_header_is_clickable_mid_sequence():
    """F14, closed. The header the test above proves the menu KEEPS mid-sequence — the
    one whose label counts the swings still owed — could not be pressed: its handler sat
    inside `not self.bonus_used`, and `bonus_used` is True from the moment an off-hand or
    Flurry sequence starts. So the button that said "⚔ Bonus (2)" was drawn, offered, and
    dead.

    It is dispatched ungated now, exactly as `atk_action` is on the Action side, because
    the offer is the menu's to make and `_action_clicked` consults it. `_start_attack`
    re-arms the parked sequence rather than seeding a new one (`attacks_remaining != 0`
    skips the seed), which is what makes the click a RESUME and not a second sequence.

    `spell_bonus` is the other half and deliberately stays refused — see the check below.
    """
    app = _app()
    aria = _goto(app, "Aria")           # Fighter 5, longsword + off-hand shortsword
    app.bonus_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "bonus"
    app.pending_attack_slot = ""
    app.pending_weapon_idx = -1

    _draw(app)
    assert app._action_menu["atk_bonus"].label == "⚔ Bonus (2)", app._action_menu["atk_bonus"]

    _click_action(app, "atk_bonus")
    assert app.pending_attack_slot == "bonus", \
        "the header did not reach the handler — F14 has come back"
    assert app.attacks_remaining == 2, "the parked sequence was reseeded, not resumed"
    assert app._attack_sequence_slot == "bonus"

    # And with the Bonus Action merely spent — no sequence owed — the menu does not
    # offer it, so the newly ungated handler still has nothing to fire on.
    app.attacks_remaining = 0
    app._attack_sequence_slot = ""
    app.pending_attack_slot = ""
    _draw(app)
    assert "atk_bonus" not in app._action_menu, "offered with the Bonus Action spent"
    _click_action(app, "atk_bonus")
    assert app.pending_attack_slot == "", "a stale rect armed an attack that is not on offer"
    print("✅ test_the_bonus_attack_header_is_clickable_mid_sequence passed")


def test_the_bonus_spell_header_is_drawn_mid_sequence_but_refused():
    """The other half of F14, and the reason it did not become one fix.

    `spell_bonus` is `spell_action`'s mirror, not `atk_action`'s: a Bonus Action spell
    cannot be cast with the Bonus Action already spent on the sequence. So it keeps the
    D-M2-4 shape — drawn with the band that stays open, refused by the handler — which is
    the same pairing `test_dash_is_drawn_mid_sequence_but_the_click_is_refused` pins one
    section up.
    """
    app = _app()
    aria = _goto(app, "Aria")
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Fire Bolt")])
    app.bonus_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "bonus"

    _draw(app)
    assert "spell_bonus" in app._action_menu, "the band's header row stays open"
    before = app.combat_log[-1] if app.combat_log else None
    _click_action(app, "spell_bonus")
    assert not app.spell_grid_menu.visible, \
        "a Bonus Action spell was offered a target with the Bonus Action already spent"
    assert (app.combat_log[-1] if app.combat_log else None) == before, \
        "the refused click still reached the handler"

    app.combat.set_agent_spells(app.bm, aria, [])
    print("✅ test_the_bonus_spell_header_is_drawn_mid_sequence_but_refused passed")


def test_the_metamagic_toggles_answer_to_the_purse_and_not_the_band():
    """Bucket 7d's dict, and the reason `economy` exists.

    Arming a qualifier costs nothing — the Sorcery Points go with the CAST that carries
    it — so spending the Bonus Action must leave all nine standing. Quickened is the
    one exception, because it casts the spell AS a Bonus Action. What does take them
    away is the purse: an option whose cost is now more than the points in hand.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 7)
    s_ = app.combat.get_agent_stats(app.bm, cyra)
    s_.metamagic_options = [v for v, _n, _sp, _note in METAMAGIC_OPTIONS]
    app.combat.set_agent_stats(app.bm, cyra, s_)

    all_nine = [METAMAGIC_ID_BY_VALUE[int(v)] for v, _n, _sp, _note in METAMAGIC_OPTIONS]
    got = _bonus(app, cyra)
    assert [i for i in got if i.startswith("metamagic_")] == all_nine, got
    assert all(_by_id(app, cyra)[i].economy == "free" for i in all_nine)

    app.bonus_used = True
    got = [i for i in _bonus(app, cyra) if i.startswith("metamagic_")]
    assert got == [i for i in all_nine if i != "metamagic_quickened"], got
    assert "second_wind" not in _bonus(app, cyra), "the band did close"

    # One Sorcery Point buys the 1 SP options and nothing else.
    app.bonus_used = False
    _set_res(app, cyra, "Sorcery Points", 1)
    got = [i for i in _bonus(app, cyra) if i.startswith("metamagic_")]
    assert "metamagic_heightened" not in got and "metamagic_quickened" not in got, got
    assert "metamagic_careful" in got, got

    _set_res(app, cyra, "Sorcery Points", 0)
    assert not [i for i in _bonus(app, cyra) if i.startswith("metamagic_")]
    print("✅ test_the_metamagic_toggles_answer_to_the_purse_and_not_the_band passed")


def test_the_metamagic_tick_is_the_armed_state():
    """The tick in the label is the ONE statement of what is armed — the panel's
    highlight follows it — so the three arming flags have to reach it.

    `armed_metamagic` is radio-selected, `armed_seeking` stacks beside it, and
    `armed_metamagic2` is read only while Sorcery Incarnate is running.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 7)
    s_ = app.combat.get_agent_stats(app.bm, cyra)
    s_.metamagic_options = [v for v, _n, _sp, _note in METAMAGIC_OPTIONS]
    app.combat.set_agent_stats(app.bm, cyra, s_)

    def _ticked():
        return sorted(a.id for a in ActionMenu.build(app, cyra)
                      if a.id.startswith("metamagic_") and a.label.startswith("✓"))

    assert _ticked() == []
    app.armed_metamagic = rpg.MetamagicOption.Heightened
    app.armed_seeking = True
    assert _ticked() == ["metamagic_heightened", "metamagic_seeking"], _ticked()

    # Slot 2 is invisible until Sorcery Incarnate is actually running.
    app.armed_metamagic2 = rpg.MetamagicOption.Twinned
    assert "metamagic_twinned" not in _ticked(), _ticked()
    s_ = app.combat.get_agent_stats(app.bm, cyra)
    s_.innate_sorcery_turns = 10
    app.combat.set_agent_stats(app.bm, cyra, s_)
    assert "metamagic_twinned" in _ticked(), _ticked()

    app.armed_metamagic = rpg.MetamagicOption.NONE
    app.armed_metamagic2 = rpg.MetamagicOption.NONE
    app.armed_seeking = False
    print("✅ test_the_metamagic_tick_is_the_armed_state passed")


def test_haste_grants_an_action_the_bonus_action_cannot_take():
    """7d's other member: the flag is the whole guard, and the band is not in it."""
    app = _app()
    aria = _goto(app, "Aria")
    assert "haste_action" not in _bonus(app, aria)

    s_ = app.combat.get_agent_stats(app.bm, aria)
    s_.haste_action_available = True
    app.combat.set_agent_stats(app.bm, aria, s_)
    assert "haste_action" in _bonus(app, aria)
    assert _by_id(app, aria)["haste_action"].economy == "action"

    app.bonus_used = True
    assert "haste_action" in _bonus(app, aria), "an Action is not a Bonus Action"
    app.action_used = True
    assert "haste_action" in _bonus(app, aria), \
        "and it is the extra one, so a spent Action does not take it either"

    s_ = app.combat.get_agent_stats(app.bm, aria)
    s_.haste_action_available = False
    app.combat.set_agent_stats(app.bm, aria, s_)
    print("✅ test_haste_grants_an_action_the_bonus_action_cannot_take passed")


def test_the_bonus_runs_are_built_in_draw_order():
    """§7's analog of `test_the_open_band_is_built_in_column_order`.

    `panel.draw_action_stack` draws a run in the order the MENU emits it, and the
    `_BON_RUN_*` tuples in main.py are the panel's draw order written down. If the two
    ever disagree the panel still renders — it just renders Rage above Patient Defense,
    which no availability test would catch. So the invariant is: for every run, the
    ids the menu emits from it appear in the tuple's order.
    """
    import main
    runs = [v for k, v in vars(main).items() if k.startswith("_BON_RUN_")]
    # Six after M2c and thirteen after M2d — a run is a maximal stretch with no
    # still-fused button between its members, so converting the clusters that CUT the
    # column added runs rather than merging them. M2e converted the last of them and
    # the thirteen collapse to FOUR: Escape and the feat's shove between the two rows,
    # the five the Bonus Action does not own, the whole band, and the Metamagic tail.
    assert len(runs) == 4, sorted(vars(main)[k] and k for k in vars(main)
                                  if k.startswith("_BON_RUN_"))

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
             dict(ranger_subclass=rpg.RangerSubclass.BeastMaster)),
            # M2d's clusters, so the runs it added are ordered too
            ("Cyra", rpg.CharacterClass.Cleric, 6,
             dict(cleric_subclass=rpg.ClericSubclass.LightDomain)),
            ("Cyra", rpg.CharacterClass.Bard, 14,
             dict(bard_subclass=rpg.BardCollege.Glamour)),
            ("Cyra", rpg.CharacterClass.Rogue, 13,
             dict(rogue_subclass=rpg.RogueSubclass.Soulknife)),
            ("Cyra", rpg.CharacterClass.Monk, 17,
             dict(monk_subclass=rpg.MonkSubclass.WarriorOfShadow)),
            ("Cyra", rpg.CharacterClass.Warlock, 6,
             dict(warlock_subclass=rpg.WarlockSubclass.Archfey)),
            ("Cyra", rpg.CharacterClass.Monk, 6,
             dict(monk_subclass=rpg.MonkSubclass.WarriorOfFourElements))):
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


def test_the_fleet_step_arm_of_step_of_the_wind_is_reachable():
    """F11, closed — this check used to pin the opposite, and inverting it is the point.

    Step of the Wind has two arms. The ordinary one costs a Focus Point and the Bonus
    Action. The Open Hand L11 one, Fleet Step, is free precisely BECAUSE it rides
    alongside another Bonus Action — so its condition is `bonus_used`, and it used to be
    written inside the band block that had already required `not bonus_used`. The 2024
    feature the panel describes could never be offered.

    The arm now lives above the band's early return, where the state it needs is the
    state it gets. The two arms are mutually exclusive by construction — one runs only
    with the band open, the other only with it shut — so the option is never offered
    twice, which is what the last stanza checks.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 11,
                    monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    _set_conditions(app, cyra, fleet_step_used=False)
    assert "step_of_wind" in _bonus(app, cyra), "the normal arm should be offered"

    app.bonus_used = True
    assert "step_of_wind" in _bonus(app, cyra), \
        "Fleet Step is unreachable again — the arm is back inside the band"
    assert _bonus(app, cyra).count("step_of_wind") == 1, "the option is offered twice"
    assert "patient_defense" not in _bonus(app, cyra), \
        "the rest of the band came back with it — the early return has been lost"

    # Once per turn, and only for this subclass at this level.
    _set_conditions(app, cyra, fleet_step_used=True)
    assert "step_of_wind" not in _bonus(app, cyra), "Fleet Step is once per turn"
    _set_conditions(app, cyra, fleet_step_used=False)

    # `_reclass` puts the creature back on turn, which hands the Bonus Action back, so
    # each of the two negatives spends it again before it asks.
    ten = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 10,
                   monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    _set_conditions(app, ten, fleet_step_used=False)
    app.bonus_used = True
    assert "step_of_wind" not in _bonus(app, ten), "Fleet Step is an L11 feature"

    mercy = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 11,
                     monk_subclass=rpg.MonkSubclass.WarriorOfMercy)
    _set_conditions(app, mercy, fleet_step_used=False)
    app.bonus_used = True
    assert "step_of_wind" not in _bonus(app, mercy), "Fleet Step is Open Hand's"
    print("✅ test_the_fleet_step_arm_of_step_of_the_wind_is_reachable passed")


def test_the_fleet_step_click_is_free_and_once_per_turn():
    """The handler half of F11: the dispatch was inside `not self.bonus_used` too, so
    even an offered arm would have been a dead button (that is F14's shape, one item up).

    Fleet Step spends neither the Focus Point nor the Bonus Action, and the Step itself
    is a Disengage plus a Dash — so the observable is movement going UP with the purse
    untouched.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 11,
                    monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    _goto(app, "Cyra")
    _set_conditions(app, cyra, fleet_step_used=False)
    _set_res(app, cyra, "Focus Points", 3)
    app.bonus_used = True

    walk_before = app.bm.placed_agents[cyra].walk_remaining
    _draw(app)
    assert "step_of_wind" in app._action_menu, "the panel did not draw the Fleet Step arm"
    _click_action(app, "step_of_wind")

    assert app.bm.placed_agents[cyra].walk_remaining > walk_before, \
        "the click did not reach the handler — the Dash never happened"
    assert app.combat.get_agent_conditions(app.bm, cyra).fleet_step_used, \
        "the once-per-turn flag was not spent"
    assert app.combat.get_agent_stats(app.bm, cyra).get_resource("Focus Points").current == 3, \
        "Fleet Step is free — it must not spend a Focus Point"
    assert app.bonus_used, "and it does not un-spend the Bonus Action it rides alongside"

    # Spent, so the arm is gone and a second click finds nothing on offer.
    _draw(app)
    assert "step_of_wind" not in app._action_menu
    print("✅ test_the_fleet_step_click_is_free_and_once_per_turn passed")


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

    victim = panel.cbt_btn(app, "rage")
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


# ─────────────────────────────────────────────────────────────────────────────
#  §7 — the clusters and the spatial predicates (M2d)
# ─────────────────────────────────────────────────────────────────────────────
#
# A cluster is not a run: several of these are nested INSIDE another button's resource
# test, so no order of single-button extractions reaches them. That nesting is the rule
# each check below names.


def test_the_channel_divinity_cluster_shares_one_resource():
    """Turn Undead is the gate; the two domain options live inside its resource test.

    Spending the Channel Divinity use takes all three at once, which is what makes it
    one cluster and not three guards that happen to sit together.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
                    cleric_subclass=rpg.ClericSubclass.LifeDomain)
    got = _bonus(app, cyra)
    assert "turn_undead" in got and "preserve_life" in got, got
    assert "radiance" not in got, "Radiance is Light Domain's"

    _set_res(app, cyra, "Channel Divinity", 0)
    got = _bonus(app, cyra)
    assert "turn_undead" not in got and "preserve_life" not in got, got

    # The Action, not the Bonus Action, is what these cost.
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
                    cleric_subclass=rpg.ClericSubclass.LightDomain)
    assert "radiance" in _bonus(app, cyra)
    app.action_used = True
    assert "radiance" not in _bonus(app, cyra), "Channel Divinity costs the Action"
    print("✅ test_the_channel_divinity_cluster_shares_one_resource passed")


def test_path_to_the_grave_is_a_bonus_action_option():
    """Grave Domain Path to the Grave: a Bonus Action that spends a Channel Divinity use — so,
    unlike the cluster above, it survives a spent Action but not a spent Channel Divinity."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
                    cleric_subclass=rpg.ClericSubclass.GraveDomain)
    assert "path_to_the_grave" in _bonus(app, cyra)
    app.action_used = True
    assert "path_to_the_grave" in _bonus(app, cyra), "costs the Bonus Action, not the Action"
    _set_res(app, cyra, "Channel Divinity", 0)
    assert "path_to_the_grave" not in _bonus(app, cyra)
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
                    cleric_subclass=rpg.ClericSubclass.LifeDomain)
    assert "path_to_the_grave" not in _bonus(app, cyra), "Grave Domain only"
    print("✅ test_path_to_the_grave_is_a_bonus_action_option passed")


def test_the_duplicity_cluster_needs_an_illusion_on_the_map():
    """Invoke Duplicity is a resource; Move and Swap are a SCAN of the token list.

    `_my_duplicates` looks for a live summon flagged "Invoke Duplicity" belonging to
    this creature — so the two follow-ups appear only once one is standing there, and
    disappear again when it is tombstoned.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 6,
                    cleric_subclass=rpg.ClericSubclass.TrickeryDomain)
    got = _bonus(app, cyra)
    assert "invoke_duplicity" in got, got
    assert "move_duplicity" not in got and "swap_duplicity" not in got, got

    dup = _place_duplicate(app, cyra)
    got = _bonus(app, cyra)
    assert "move_duplicity" in got and "swap_duplicity" in got, got

    app.bm.set_agent_removed_from_play(dup, True)
    got = _bonus(app, cyra)
    assert "move_duplicity" not in got, "a tombstoned illusion is not on the map"
    print("✅ test_the_duplicity_cluster_needs_an_illusion_on_the_map passed")


def test_trickster_transposition_needs_level_six():
    """The one member of the cluster with a level of its own, nested two tests deep."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
                    cleric_subclass=rpg.ClericSubclass.TrickeryDomain)
    _place_duplicate(app, cyra)
    got = _bonus(app, cyra)
    assert "move_duplicity" in got and "swap_duplicity" not in got, got
    print("✅ test_trickster_transposition_needs_level_six passed")


def test_the_glamour_cluster_is_nested_inside_bardic_inspiration():
    """The nesting that made this a cluster: two of the four read `bi` themselves.

    Grant Inspiration and both Mantles come from the same Bardic Inspiration pool in
    the panel's layout, so emptying it takes three of the five with it — while Mantle
    of Majesty, which spends its own resource, stays.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                    bard_subclass=rpg.BardCollege.Glamour)
    _set_res(app, cyra, "Beguiling Magic", 0)
    got = _bonus(app, cyra)
    for want in ("grant_inspiration", "mantle", "mantle_majesty",
                 "unbreakable_majesty", "beguiling_restore"):
        assert want in got, (want, got)

    _set_res(app, cyra, "Bardic Inspiration", 0)
    got = _bonus(app, cyra)
    assert "grant_inspiration" not in got and "mantle" not in got, got
    assert "beguiling_restore" not in got, "Restore costs an Inspiration die"
    assert "mantle_majesty" in got, "Majesty spends its own resource, not the die"
    print("✅ test_the_glamour_cluster_is_nested_inside_bardic_inspiration passed")


def test_the_glamour_windows_are_the_second_arm():
    """Majesty and Unbreakable Majesty are "a use left OR the window already running".

    The second arm is how you re-cast Command for free, or keep negating melee attacks,
    after the use is gone — dropping it would leave a Bard mid-feature with no button.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                    bard_subclass=rpg.BardCollege.Glamour)
    _set_res(app, cyra, "Mantle of Majesty", 0)
    _set_res(app, cyra, "Unbreakable Majesty", 0)
    got = _bonus(app, cyra)
    assert "mantle_majesty" not in got and "unbreakable_majesty" not in got, got

    s = app.combat.get_agent_stats(app.bm, cyra)
    s.mantle_majesty_turns = 2
    s.majestic_presence_turns = 2
    app.combat.set_agent_stats(app.bm, cyra, s)
    got = _bonus(app, cyra)
    assert "mantle_majesty" in got and "unbreakable_majesty" in got, got
    print("✅ test_the_glamour_windows_are_the_second_arm passed")


def test_restore_beguiling_magic_asks_for_a_resource_that_is_not_full():
    """The only guard in §7 that reads a resource the other way round."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                    bard_subclass=rpg.BardCollege.Glamour)
    assert "beguiling_restore" not in _bonus(app, cyra), "nothing to restore yet"
    _set_res(app, cyra, "Beguiling Magic", 0)
    assert "beguiling_restore" in _bonus(app, cyra)
    print("✅ test_restore_beguiling_magic_asks_for_a_resource_that_is_not_full passed")


def test_the_soulknife_pair_can_be_paid_for_with_dice():
    """Psychic Veil is offered while its own resource is empty but dice remain, and
    both labels carry the count — the label IS the state here."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 13,
                    rogue_subclass=rpg.RogueSubclass.Soulknife)
    by_id = _by_id(app, cyra)
    assert "dice" in by_id["psychic_teleport"].label, by_id["psychic_teleport"].label

    _set_res(app, cyra, "Psychic Veil", 0)
    got = _bonus(app, cyra)
    assert "psychic_veil" in got, "the dice can still pay for it"

    _set_res(app, cyra, "Psionic Energy", 0)
    got = _bonus(app, cyra)
    assert "psychic_veil" not in got and "psychic_teleport" not in got, got
    print("✅ test_the_soulknife_pair_can_be_paid_for_with_dice passed")


def test_the_shadow_and_elemental_monks_split_action_from_bonus():
    """Three of these five cost the Action and two do not, inside one band.

    Spending the Action leaves the two Bonus Actions standing and takes the three
    Magic actions — which is the distinction the band gate flattens and `economy` will
    eventually carry as data.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
                    monk_subclass=rpg.MonkSubclass.WarriorOfShadow)
    got = _bonus(app, cyra)
    for want in ("shadow_step", "cloak_of_shadows", "shadow_arts_darkness"):
        assert want in got, (want, got)
    app.action_used = True
    got = _bonus(app, cyra)
    assert "shadow_arts_darkness" not in got, "Shadow Arts is a Magic action"
    assert "shadow_step" in got and "cloak_of_shadows" in got, got

    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 6,
                    monk_subclass=rpg.MonkSubclass.WarriorOfFourElements)
    got = _bonus(app, cyra)
    assert "elemental_attunement" in got and "elemental_burst" in got, got
    app.action_used = True
    assert _bonus(app, cyra) == [i for i in _bonus(app, cyra)
                                 if not i.startswith("elemental_")], \
        "both Elemental features cost the Action"
    print("✅ test_the_shadow_and_elemental_monks_split_action_from_bonus passed")


def test_elemental_attunement_ticks_once_it_is_running():
    """The label flips to a tick, and that flag lives on the conditions, not the stats."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 6,
                    monk_subclass=rpg.MonkSubclass.WarriorOfFourElements)
    assert "Focus" in _by_id(app, cyra)["elemental_attunement"].label
    _set_conditions(app, cyra, elemental_attunement_active=True)
    assert _by_id(app, cyra)["elemental_attunement"].label.endswith("✓")
    _set_conditions(app, cyra, elemental_attunement_active=False)
    print("✅ test_elemental_attunement_ticks_once_it_is_running passed")


def test_the_fey_rider_is_clamped_without_the_menu_writing_it_back():
    """`build` must not mutate the app, and the rider cycle is the one place §7 did.

    A selection made at L6 is out of range at L3 (three riders, not five). The menu
    LABELS the clamped value; the panel writes the clamp through, because the click
    handler and the engine call both read the raw field.
    """
    import main
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 3,
                    warlock_subclass=rpg.WarlockSubclass.Archfey)
    app.steps_of_fey_effect = 4
    label = _by_id(app, cyra)["fey_effect"].label
    assert label == "Fey Step: None", label
    assert app.steps_of_fey_effect == 4, "the MENU must not write the clamp back"

    _draw(app)
    assert app.steps_of_fey_effect == 0, "the PANEL must write it back"
    app.steps_of_fey_effect = 0
    print("✅ test_the_fey_rider_is_clamped_without_the_menu_writing_it_back passed")


def test_misty_escape_is_a_reaction_the_band_still_hides():
    """Recorded, not fixed: a Reaction drawn inside the Bonus Action band.

    Spending the bonus action hides it, exactly as the band gate hides Action Surge.
    Its own gate is the reaction, and that one is read off the placed agent's condition
    copy rather than through the engine — as the panel read it.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 6,
                    warlock_subclass=rpg.WarlockSubclass.Archfey)
    assert "misty_escape" in _bonus(app, cyra)
    assert _by_id(app, cyra)["misty_escape"].economy == "reaction", \
        "the menu says what it costs even where the band does not"
    _set_conditions(app, cyra, reaction_used=True)
    assert "misty_escape" not in _bonus(app, cyra), "the Reaction is spent"
    _set_conditions(app, cyra, reaction_used=False)
    app.bonus_used = True
    assert "misty_escape" not in _bonus(app, cyra), \
        "the band gate takes it too — that is the panel's behaviour, preserved"
    print("✅ test_misty_escape_is_a_reaction_the_band_still_hides passed")


def test_the_jump_row_narrows_when_something_is_adjacent():
    """Bucket 7c's shape rule: the row is Jump alone, or Jump + Shove + Trip.

    Aria has Skarn next to her; Brannor is standing on his own. Nothing else in §7
    changes its WIDTH according to where the other tokens are.
    """
    app = _app()
    aria = _goto(app, "Aria")
    got = _bonus(app, aria)
    # The row is the band's FIRST, but not the section's first ids: the economy-band
    # headers (bucket 7b) are built above it, in the order the panel draws them.
    at = got.index("long_jump")
    assert got[at:at + 3] == ["long_jump", "shove_push", "shove_prone"], got

    brannor = _goto(app, "Brannor")
    got = _bonus(app, brannor)
    assert "long_jump" in got, got
    assert "shove_push" not in got and "shove_prone" not in got, got
    print("✅ test_the_jump_row_narrows_when_something_is_adjacent passed")


def test_escape_needs_both_a_neighbour_and_a_grapple():
    """Two predicates, and the panel ANDs them: being held by someone far away offers
    nothing, because the escape is a contest with a creature you can reach."""
    app = _app()
    aria = _goto(app, "Aria")
    assert "grapple_esc" not in _bonus(app, aria)
    _set_conditions(app, aria, grappled=True)
    assert "grapple_esc" in _bonus(app, aria)
    _set_conditions(app, aria, grappled=False)

    brannor = _goto(app, "Brannor")
    _set_conditions(app, brannor, grappled=True)
    assert "grapple_esc" not in _bonus(app, brannor), "nobody within reach to escape"
    _set_conditions(app, brannor, grappled=False)
    print("✅ test_escape_needs_both_a_neighbour_and_a_grapple passed")


def test_drop_grapple_and_free_from_net_are_outside_the_band():
    """Both are the point of the `economy` field: neither costs the Bonus Action.

    Drop Grapple is free and Free from Net is an Action, so spending the bonus action
    must leave both standing — the dead-key trap the Haste button's comment names.
    """
    app = _app()
    aria = _goto(app, "Aria")
    skarn = _idx(app, "Skarn")
    _set_conditions(app, skarn, grappled=True, grappler_idx=aria)
    _set_conditions(app, aria, netted=True)

    got = _bonus(app, aria)
    assert "grapple_drop" in got and "escape_net" in got, got

    app.bonus_used = True
    got = _bonus(app, aria)
    assert "grapple_drop" in got and "escape_net" in got, \
        "neither costs the Bonus Action"

    app.bonus_used = False
    app.action_used = True
    got = _bonus(app, aria)
    assert "grapple_drop" in got, "Drop Grapple is free"
    assert "escape_net" not in got, "Free from Net costs the Action"

    app.action_used = False
    priced = _by_id(app, aria)
    assert priced["grapple_drop"].economy == "free", priced["grapple_drop"]
    assert priced["escape_net"].economy == "action", priced["escape_net"]

    _set_conditions(app, skarn, grappled=False, grappler_idx=-1)
    _set_conditions(app, aria, netted=False)
    print("✅ test_drop_grapple_and_free_from_net_are_outside_the_band passed")


def test_bite_grappled_asks_the_engine_for_the_pairing():
    """The offer is the engine's `pending_auto_grapple_strike`, not a guard of our own:
    a flagged weapon, a victim this creature is holding, and the victim in reach."""
    app = _app()
    aria = _goto(app, "Aria")
    skarn = _idx(app, "Skarn")
    assert "bite_grappled" not in _bonus(app, aria), "no flagged weapon yet"

    bite = _weapon(app, "Longsword")
    bite.auto_use_when_grappling = True
    app.combat.set_agent_weapons(app.bm, aria,
                                 [bite, _weapon(app, "Shortsword", off_hand=True)])
    assert "bite_grappled" not in _bonus(app, aria), "not holding anyone yet"

    _set_conditions(app, skarn, grappled=True, grappler_idx=aria)
    assert "bite_grappled" in _bonus(app, aria)

    app.action_used = True
    assert "bite_grappled" not in _bonus(app, aria), "the Attack action is spent"
    app.attacks_remaining = 1
    app._attack_sequence_slot = "action"
    assert "bite_grappled" in _bonus(app, aria), "mid-multiattack is the common case"

    assert _by_id(app, aria)["bite_grappled"].economy == "attack", \
        "the Bite is paid for out of the Attack action, which is why it survives here"

    app.attacks_remaining = 0
    app._attack_sequence_slot = ""
    _set_conditions(app, skarn, grappled=False, grappler_idx=-1)
    app.combat.set_agent_weapons(app.bm, aria,
                                 [_weapon(app, "Longsword"),
                                  _weapon(app, "Shortsword", off_hand=True)])
    print("✅ test_bite_grappled_asks_the_engine_for_the_pairing passed")


def test_horde_breaker_is_offered_from_the_engine_list_and_checks_the_click():
    """The row is the engine's `horde_breaker_targets`, offered once the Attack sequence has no
    swings left; arming it limits the next attack click to those creatures, and the swing spends
    the feature (RANGER_SUBCLASSES_PLAN.md R1)."""
    from net.roster import DM_PRINCIPAL_ID
    app = _app()
    aria = _goto(app, "Aria")
    skarn, cyra, brannor = _idx(app, "Skarn"), _idx(app, "Cyra"), _idx(app, "Brannor")
    home = app.bm.placed_agents[cyra].origin
    home = (home.col, home.row)
    fac = app.bm.get_agent_faction(cyra)
    assert "horde_breaker" not in _bonus(app, aria), "nothing armed"

    # Cyra joins Skarn's side next to him (and within Aria's reach); an attack on Skarn armed it.
    app.bm.set_agent_faction(cyra, app.bm.get_agent_faction(skarn))
    assert app.combat.teleport_agent(app.bm, cyra, 4, 4)
    _set_conditions(app, aria, horde_breaker_available=True, horde_breaker_origin=skarn,
                    horde_breaker_weapon=0, attacked_this_turn=[skarn])
    assert list(app.combat.horde_breaker_targets(app.bm, aria)) == [cyra]
    assert "horde_breaker" in _bonus(app, aria)
    assert _by_id(app, aria)["horde_breaker"].economy == "free"

    app.attacks_remaining = 1
    app._attack_sequence_slot = "action"
    assert "horde_breaker" not in _bonus(app, aria), "the Attack action still has a swing left"
    app.attacks_remaining = 0
    app._attack_sequence_slot = ""

    _draw(app)                                       # the panel draws the row; perform needs the offer
    assert "horde_breaker" in app._action_menu
    assert app.perform("horde_breaker", DM_PRINCIPAL_ID) is True
    assert app.pending_attack_slot == "action" and app.pending_horde_breaker_targets == [cyra]
    app._resolve_combat_attack(brannor)              # not a legal Horde Breaker target
    assert not app.combat.get_agent_conditions(app.bm, aria).horde_breaker_used
    assert app.pending_horde_breaker_targets == [cyra], "a refused click keeps the pick armed"
    app._resolve_combat_attack(cyra)
    c = app.combat.get_agent_conditions(app.bm, aria)
    assert c.horde_breaker_used and not c.horde_breaker_available
    assert app.pending_horde_breaker_targets == []

    app.pending_attack_slot = ""
    app.attacks_remaining = 0
    app._attack_sequence_slot = ""
    _set_conditions(app, aria, horde_breaker_available=False, horde_breaker_used=False,
                    horde_breaker_origin=-1, horde_breaker_weapon=-1, attacked_this_turn=[])
    app.combat.teleport_agent(app.bm, cyra, *home)
    app.bm.set_agent_faction(cyra, fac)
    print("✅ test_horde_breaker_is_offered_from_the_engine_list_and_checks_the_click passed")


def test_beast_master_command_and_beasts_strike():
    """Beast Master (RANGER_SUBCLASSES_PLAN.md R4, D9): Command is a band row that spends the
    Bonus Action; Beast's Strike is an attack-economy row that pays one attack and arms the
    companion's strikes (two at L11), each a checked click; the uncommanded companion's Action
    band is Dodge alone."""
    from net.roster import DM_PRINCIPAL_ID
    app = _app()
    aria = _reclass(app, "Aria", rpg.CharacterClass.Ranger, 11,
                    ranger_subclass=rpg.RangerSubclass.BeastMaster)
    skarn, brannor = _idx(app, "Skarn"), _idx(app, "Brannor")
    app._summon_companion(aria, "Land")
    comp = app.combat.primal_companion_of(app.bm, aria)
    assert comp >= 0
    sk = app.bm.placed_agents[skarn].origin
    assert any(app.combat.teleport_agent(app.bm, comp, sk.col + dc, sk.row + dr)
               for dc, dr in ((1, 0), (0, 1), (0, -1), (1, 1), (1, -1))), "no cell next to Skarn"
    assert list(app.combat.beasts_strike_targets(app.bm, aria)) == [skarn]

    assert "command_companion" in _bonus(app, aria)
    assert _by_id(app, aria)["beasts_strike"].economy == "attack"
    assert ActionMenu._action(app, comp) and \
        [a.id for a in ActionMenu._action(app, comp)] == ["dodge"], "uncommanded: Dodge only"

    _draw(app)
    assert app.perform("beasts_strike", DM_PRINCIPAL_ID) is True
    c = app.combat.get_agent_conditions(app.bm, aria)
    assert c.beast_strikes_left == 2, "Bestial Fury: twice"
    assert app.action_used, "the Attack action is under way"
    assert app.pending_attack_slot == "action" and app.pending_beasts_strike_targets == [skarn]
    app._resolve_combat_attack(brannor)                       # not one the companion can reach
    assert app.combat.get_agent_conditions(app.bm, aria).beast_strikes_left == 2
    app._resolve_combat_attack(skarn)
    assert app.combat.get_agent_conditions(app.bm, aria).beast_strikes_left == 1
    if app.combat.get_agent_stats(app.bm, skarn).hp_cur > 0:
        assert app.pending_beasts_strike_targets == [skarn], "the second strike re-arms"
        app._resolve_combat_attack(skarn)
        assert app.combat.get_agent_conditions(app.bm, aria).beast_strikes_left == 0
    app.pending_attack_slot = ""
    app.pending_beasts_strike_targets = []

    _draw(app)
    assert app.perform("command_companion", DM_PRINCIPAL_ID) is True
    assert app.bonus_used and app.combat.get_agent_conditions(app.bm, aria).companion_commanded
    assert "command_companion" not in _bonus(app, aria)
    assert "dodge" in [a.id for a in ActionMenu._action(app, comp)] and \
        len(ActionMenu._action(app, comp)) > 1, "commanded: the full band"
    print("✅ test_beast_master_command_and_beasts_strike passed")


def test_sudden_strike_is_offered_from_the_engine_list_and_checks_the_click():
    """Stalker's Flurry's Sudden Strike, once chosen, is a free row fed by the engine's
    `sudden_strike_targets`; arming it limits the next attack click to those creatures and the
    swing spends it (RANGER_SUBCLASSES_PLAN.md R2). Dread Ambusher no longer has a row: Dreadful
    Strike is offered on the hit."""
    from net.roster import DM_PRINCIPAL_ID
    app = _app()
    aria = _reclass(app, "Aria", rpg.CharacterClass.Ranger, 11,
                    ranger_subclass=rpg.RangerSubclass.GloomStalker)
    skarn, cyra, brannor = _idx(app, "Skarn"), _idx(app, "Cyra"), _idx(app, "Brannor")
    assert "dread_ambusher" not in _ids(app, aria), "Dreadful Strike is an on-hit rider now"
    assert "sudden_strike" not in _bonus(app, aria), "nothing armed"

    app.bm.set_agent_faction(cyra, app.bm.get_agent_faction(skarn))
    assert app.combat.teleport_agent(app.bm, cyra, 4, 4)
    _set_conditions(app, aria, sudden_strike_available=True, dreadful_strike_target=skarn,
                    dreadful_strike_weapon=0)
    assert list(app.combat.sudden_strike_targets(app.bm, aria)) == [cyra]
    assert "sudden_strike" in _bonus(app, aria)
    assert _by_id(app, aria)["sudden_strike"].economy == "free"
    app.attacks_remaining = 1
    assert "sudden_strike" not in _bonus(app, aria), "the Attack action still has a swing left"
    app.attacks_remaining = 0

    _draw(app)
    assert app.perform("sudden_strike", DM_PRINCIPAL_ID) is True
    assert app.pending_attack_slot == "action" and app.pending_sudden_strike_targets == [cyra]
    app._resolve_combat_attack(brannor)              # not a legal Sudden Strike target
    assert app.combat.get_agent_conditions(app.bm, aria).sudden_strike_available
    assert app.pending_sudden_strike_targets == [cyra], "a refused click keeps the pick armed"
    app._resolve_combat_attack(cyra)
    assert not app.combat.get_agent_conditions(app.bm, aria).sudden_strike_available
    assert app.pending_sudden_strike_targets == []
    print("✅ test_sudden_strike_is_offered_from_the_engine_list_and_checks_the_click passed")


def test_shadowy_dodge_cell_pick_submits_the_parked_window():
    """Shadowy Dodge's "pick a cell" option arms a map pick; an illegal cell keeps it armed and a
    legal one submits the parked AfterAttack window, which teleports the Ranger (R2, D6)."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Ranger, 15,
                    ranger_subclass=rpg.RangerSubclass.GloomStalker)
    skarn = _idx(app, "Skarn")
    app.bm.set_agent_faction(cyra, app.bm.get_agent_faction(skarn) + 1)
    sk = app.bm.placed_agents[skarn].origin
    assert app.combat.teleport_agent(app.bm, cyra, sk.col + 1, sk.row)
    w = rpg.Weapon(); w.name = "Club"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    w.range_short_feet = 5; w.range_long_feet = 5; w.proficient = True
    app.combat.set_agent_weapons(app.bm, skarn, [w, rpg.Weapon(), rpg.Weapon()])

    assert app.combat.begin_attack(app.bm, rpg.Attack(skarn, cyra, 0)) == rpg.FlowStatus.AwaitingDecision
    ctx = app.combat.pending_decision().ctx
    assert ctx.window == rpg.ReactionWindow.OnAttackDeclared
    resp = rpg.ReactionResponse()
    resp.option = next(i for i, o in enumerate(ctx.options) if o.feature == "ShadowyDodge")
    assert app.combat.submit_decision(app.bm, resp) == rpg.FlowStatus.AwaitingDecision
    ctx = app.combat.pending_decision().ctx
    assert ctx.window == rpg.ReactionWindow.AfterAttack
    app._begin_shadowy_dodge_pick(
        next(i for i, o in enumerate(ctx.options) if o.feature == "ShadowyDodgeTeleportPick"))
    assert app.pending_shadowy_dodge_cell

    app._resolve_shadowy_dodge_cell(rpg.Cell(sk.col, sk.row))       # occupied
    assert app.pending_shadowy_dodge_cell and app.combat.pending_decision().active
    me = app.bm.placed_agents[cyra].origin
    dest = next(rpg.Cell(me.col + dc, me.row + dr) for dr in range(-6, 7) for dc in range(-6, 7)
                if app.combat.is_shadowy_dodge_destination(app.bm, cyra, rpg.Cell(me.col + dc, me.row + dr)))
    app._resolve_shadowy_dodge_cell(dest)
    at = app.bm.placed_agents[cyra].origin
    assert (at.col, at.row) == (dest.col, dest.row)
    assert not app.pending_shadowy_dodge_cell and not app.combat.pending_decision().active
    print("✅ test_shadowy_dodge_cell_pick_submits_the_parked_window passed")


def _fey(app, name, level, **fields):
    """`name` re-classed as a Fey Wanderer of `level`, with Summon Fey known (R3)."""
    idx = _reclass(app, name, rpg.CharacterClass.Ranger, level,
                   ranger_subclass=rpg.RangerSubclass.FeyWanderer, wis=16, **fields)
    if not any(sp.name == "Summon Fey" for sp in app.combat.get_agent_spells(app.bm, idx)):
        app.combat.add_spell_to_agent(app.bm, idx, _spell(app, "Summon Fey"))
    return idx


def test_the_fey_wanderer_rows():
    """Fey Reinforcements (L11, an Action) and Misty Wanderer (L15, inside the band) are offered
    while a use is left (RANGER_SUBCLASSES_PLAN.md R3, D8)."""
    app = _app()
    aria = _fey(app, "Aria", 10)
    assert "fey_reinforcements" not in _bonus(app, aria), "Fey Reinforcements is L11"
    aria = _fey(app, "Aria", 15)
    got = _by_id(app, aria)
    assert got["fey_reinforcements"].economy == "action"
    assert "misty_wanderer" in got
    app.action_used = True
    assert "fey_reinforcements" not in _bonus(app, aria), "it is a cast: the Action is spent"
    app.action_used = False
    _set_res(app, aria, "Fey Reinforcements", 0)
    _set_res(app, aria, "Misty Wanderer", 0)
    ids = _bonus(app, aria)
    assert "fey_reinforcements" not in ids and "misty_wanderer" not in ids, "no uses left"
    print("✅ test_the_fey_wanderer_rows passed")


def test_fey_reinforcements_casts_a_one_minute_summon_without_a_slot():
    from net.roster import DM_PRINCIPAL_ID
    app = _app()
    aria = _fey(app, "Aria", 11)
    slots = list(app.combat.get_agent_stats(app.bm, aria).spell_slots_remaining)
    n = len(app.bm.placed_agents)
    _draw(app)
    assert app.perform("fey_reinforcements", DM_PRINCIPAL_ID) is True
    assert app.prompts.live is not None and "Concentration" in app.prompts.live.title
    app.prompts.choose_label("No Concentration (1 minute)")
    form = next(o.label for o in app.prompts.live.options if "Fuming" in o.label)
    app.prompts.choose_label(form)
    assert app.pending_summon_slot and app.pending_summon_no_conc and app.pending_summon_fey_reinforcements
    app._resolve_summon(rpg.Cell(3, 4))
    assert len(app.bm.placed_agents) == n + 1, "the spirit is on the map"
    spirit = app.bm.placed_agents[n]
    assert spirit.summon_spell == "Summon Fey" and spirit.summoner_idx == aria
    assert spirit.summon_rounds_left == 10, "1 minute"
    st = app.combat.get_agent_stats(app.bm, aria)
    assert st.get_resource("Fey Reinforcements").current == 0
    assert list(st.spell_slots_remaining) == slots, "no slot spent"
    assert not app.combat.get_agent_conditions(app.bm, aria).concentrating
    assert app.action_used
    assert [e.agent_idx for e in app.initiative_order].index(n) == \
        [e.agent_idx for e in app.initiative_order].index(aria) + 1, "acts right after the Ranger"
    print("✅ test_fey_reinforcements_casts_a_one_minute_summon_without_a_slot passed")


def test_misty_wanderer_pick_and_the_passenger_prompt():
    from net.roster import DM_PRINCIPAL_ID
    app = _app()
    aria = _fey(app, "Aria", 15)
    cyra = _idx(app, "Cyra")
    assert app.combat.teleport_agent(app.bm, cyra, 3, 2)          # a willing ally within 5 ft
    _draw(app)
    assert app.perform("misty_wanderer", DM_PRINCIPAL_ID) is True
    assert app.pending_misty_wanderer
    app._resolve_misty_wanderer(rpg.Cell(8, 3))
    assert app.prompts.live is not None, "an ally is within 5 ft: who comes along?"
    app.prompts.choose_label("Bring Cyra")
    at, ca = app.bm.placed_agents[aria].origin, app.bm.placed_agents[cyra].origin
    assert (at.col, at.row) == (8, 3)
    assert max(abs(ca.col - 8), abs(ca.row - 3)) == 1, "Cyra lands beside Aria"
    assert app.bonus_used and not app.pending_misty_wanderer
    print("✅ test_misty_wanderer_pick_and_the_passenger_prompt passed")


def test_automated_summon_fey():
    """The NpcDriver casts no summons, so `_auto_summon_fey` is the automated Fey Wanderer's cast:
    Fey Reinforcements first, no Concentration from L11, the spirit automated and next in order."""
    app = _app()
    aria = _fey(app, "Aria", 11)
    app.bm.set_agent_npc_automated(aria, True)
    n = len(app.bm.placed_agents)
    new = app._auto_summon_fey(aria)
    assert new == n
    pt = app.bm.placed_agents[new]
    assert pt.summon_spell == "Summon Fey" and pt.summon_rounds_left == 10
    assert app.bm.is_agent_npc_automated(new)
    assert pt.faction == app.bm.placed_agents[aria].faction
    assert app.combat.get_agent_stats(app.bm, aria).get_resource("Fey Reinforcements").current == 0
    assert not app.combat.get_agent_conditions(app.bm, aria).concentrating
    order = [e.agent_idx for e in app.initiative_order]
    assert order.index(new) == order.index(aria) + 1
    assert app._auto_summon_fey(aria) == -1, "one spirit at a time"
    app.bm.set_agent_removed_from_play(new, True)
    st = app.combat.get_agent_stats(app.bm, aria)
    st.spell_slots_remaining = [4, 3, 3] + [0] * (len(st.spell_slots_remaining) - 3)
    app.combat.set_agent_stats(app.bm, aria, st)
    slots = list(st.spell_slots_remaining)
    assert app._auto_summon_fey(aria) >= 0, "no Reinforcements left: it pays with a slot"
    after = list(app.combat.get_agent_stats(app.bm, aria).spell_slots_remaining)
    assert after[2] == slots[2] - 1 and after[:2] == slots[:2], "its highest slot of 3rd+ level"
    lvl8 = _fey(app, "Cyra", 8)
    assert app._auto_summon_fey(lvl8) == -1, "Summon Fey is L9"
    print("✅ test_automated_summon_fey passed")


def test_beguiling_twist_is_offered_to_a_human_ranger():
    app = _app()
    aria = _fey(app, "Aria", 7)
    brannor, skarn = _idx(app, "Brannor"), _idx(app, "Skarn")
    app.combat.charm_fear_save_succeeded(app.bm, brannor)
    app._offer_beguiling_twist_if_pending()
    live = app.prompts.live
    assert live is not None and "Beguiling Twist" in live.title
    labels = [o.label for o in live.options]
    assert "Frighten Skarn" in labels and "Charm Skarn" in labels
    assert not any("Brannor" in lb for lb in labels), "never the creature that saved"
    app.prompts.choose_label("Frighten Skarn")
    assert app.combat.get_agent_conditions(app.bm, aria).reaction_used
    print("✅ test_beguiling_twist_is_offered_to_a_human_ranger passed")


def test_cunning_action_is_all_three_or_none():
    """One flag offers the whole row; a row with two of three would be a layout bug no
    availability test could see, which is what the smoke suite's row check is for."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 3,
                    rogue_subclass=rpg.RogueSubclass.NONE)
    got = [i for i in _bonus(app, cyra) if i in ("dash_bonus", "disengage_bonus",
                                                 "hide_bonus")]
    assert got == ["dash_bonus", "disengage_bonus", "hide_bonus"], got

    aria = _goto(app, "Aria")
    assert not [i for i in _bonus(app, aria)
                if i in ("dash_bonus", "disengage_bonus", "hide_bonus")]
    print("✅ test_cunning_action_is_all_three_or_none passed")


def test_the_two_telekinetic_options_are_two_widgets(): 
    """F10, fixed and pinned so it stays fixed.

    The Telekinetic feat's 30 ft shove and Psi Warrior's Telekinetic Movement are two
    options. A creature can have both, and until M2e they shared one widget under one
    label, painted twice in a pass and clicked once — so the feat's own label had never
    been drawn by anything and one click armed both pending flags for anybody.
    """
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Fighter, 3,
                    fighter_subclass=rpg.FighterSubclass.PsiWarrior)
    got = _bonus(app, cyra)
    assert "telekinetic_psi" in got and "telekinetic_feat" not in got, got

    s = app.combat.get_agent_stats(app.bm, cyra)
    s.add_feat("Telekinetic")
    app.combat.set_agent_stats(app.bm, cyra, s)
    got = _bonus(app, cyra)
    assert "telekinetic_feat" in got and "telekinetic_psi" in got, got

    by_id = _by_id(app, cyra)
    assert panel.cbt_btn(app, "telekinetic_feat") is not panel.cbt_btn(app, "telekinetic_psi"), \
        "one widget for two options is F10; it cannot be laid out or clicked correctly"
    assert by_id["telekinetic_feat"].label == "🌀 Telekinetic Shove", by_id
    assert by_id["telekinetic_psi"].label == "Telekinetic Movement", by_id

    # And one click arms one of them. Both handlers used to run on either click,
    # because neither was gated on the feat or on the subclass.
    app.pending_shove_type = ""
    app.pending_telekinetic = False
    app._draw_combat_panel()
    post_click(app, panel.cbt_btn(app, "telekinetic_psi").rect.center)
    assert app.pending_telekinetic, "the Psi Warrior's own option did not arm"
    assert app.pending_shove_type != "telekinetic", "the feat's handler cross-fired"

    app.pending_telekinetic = False
    app._draw_combat_panel()
    post_click(app, panel.cbt_btn(app, "telekinetic_feat").rect.center)
    assert app.pending_shove_type == "telekinetic", "the feat's option did not arm"
    assert not app.pending_telekinetic, "the Psi Warrior's handler cross-fired"
    app.pending_shove_type = ""
    app.pending_telekinetic = False

    s = app.combat.get_agent_stats(app.bm, cyra)
    s.feats = []
    app.combat.set_agent_stats(app.bm, cyra, s)
    print("✅ test_the_two_telekinetic_options_are_two_widgets passed")


def test_every_action_carries_an_economy_from_the_vocabulary():
    """`economy` is a closed set, and the two groups whose answer is uniform say it.

    §1 and §3 are not turn actions at all — a DM pausing the fight spends nothing —
    and §4 IS the Action band, where the only exception is Nick, which is paid for out
    of the Attack action's attacks rather than out of the Action a second time.
    """
    app = _app()
    for who in ("Aria", "Skarn", "Brannor", "Cyra"):
        idx = _goto(app, who)
        for a in ActionMenu.build(app, idx):
            assert a.economy in ECONOMY, f"{a.id} has economy {a.economy!r}"
            if a.group in (GROUP_SESSION, GROUP_TURN):
                assert a.economy == "none", (a.id, a.economy)
            if a.group == GROUP_ACTION:
                assert a.economy == "action", (a.id, a.economy)

    # The Action group's one exception, in the arm that is the only way to reach it.
    aria = _goto(app, "Aria")
    _give_nick_offhand(app, aria)
    app.action_used = True
    nick = _by_id(app, aria)["nick"]
    assert nick.economy == "attack", nick
    print("✅ test_every_action_carries_an_economy_from_the_vocabulary passed")


def test_wild_magic_bonus_cast_offers_action_spells():
    """Surge band 6: for its minute, the Bonus Action spell menu also offers Action-cast spells
    (as Quickened does). It used to list only the Bonus-Action spells."""
    app = _app()
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 5,
                    sorcerer_subclass=rpg.SorcererSubclass.WildMagic)
    app.combat.set_agent_spells(app.bm, cyra, [_spell(app, "Fire Bolt"),
                                               _spell(app, "Fireball"),
                                               _spell(app, "Misty Step")])
    s = app.combat.get_agent_stats(app.bm, cyra)
    s.spell_slots_remaining = list(s.spell_slots_max)
    app.combat.set_agent_stats(app.bm, cyra, s)

    seen = []
    app._ask_actor = lambda idx, kind, title, pairs, **kw: seen.append([l for l, _ in pairs])

    def bonus_menu():
        seen.clear()
        app._start_cast_spell("bonus")
        assert len(seen) == 1, seen
        return " | ".join(seen[0])

    got = bonus_menu()
    assert "Misty Step" in got and "Fireball" not in got and "Fire Bolt" not in got, got

    s = app.combat.get_agent_stats(app.bm, cyra)
    s.wild_magic_bonus_cast_turns = 10
    app.combat.set_agent_stats(app.bm, cyra, s)
    got = bonus_menu()
    assert "Misty Step" in got and "Fireball" in got and "Fire Bolt" in got, got
    print("✅ test_wild_magic_bonus_cast_offers_action_spells passed")


def test_divine_smite_is_a_bonus_action_and_keeps_the_attack_action():
    """Divine Smite is a Bonus Action spell. With no casting_time in spells.json it defaulted to
    Action: Cast Spell listed it, and casting it spent the Action, so a Paladin with Extra Attack
    lost every swing. Now the Bonus band casts it and the whole Attack action stays."""
    app = _app()
    aria = _reclass(app, "Aria", rpg.CharacterClass.Paladin, 6)
    skarn = _idx(app, "Skarn")
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Bless"),
                                               _spell(app, "Divine Smite")])
    s = app.combat.get_agent_stats(app.bm, aria)
    s.spell_slots_remaining = [4, 2, 0, 0, 0, 0, 0, 0, 0]
    app.combat.set_agent_stats(app.bm, aria, s)

    seen = []
    app._ask_actor = lambda idx, kind, title, pairs, **kw: seen.append((title, pairs))

    app._start_cast_spell("action")
    assert len(seen) == 1 and "Bless" in seen[0][0], seen
    seen.clear()

    app._start_cast_spell("bonus")
    assert len(seen) == 1 and "Divine Smite" in seen[0][0], seen
    seen[0][1][0][1]()               # the 1st-level slot
    hp = app.combat.get_agent_stats(app.bm, skarn).hp_cur
    app._resolve_spell_cast(skarn)
    assert app.combat.get_agent_stats(app.bm, skarn).hp_cur < hp
    assert app.bonus_used and not app.action_used

    assert "atk_action" in _ids(app, aria)
    app._start_attack("action")
    assert app._attack_sequence_slot == "action" and app.attacks_remaining == 2, \
        (app._attack_sequence_slot, app.attacks_remaining)
    print("✅ test_divine_smite_is_a_bonus_action_and_keeps_the_attack_action passed")


def test_an_empty_spell_menu_spends_nothing():
    """Clicking a spell button with nothing castable used to burn that Action or Bonus Action,
    and an Extra Attack sequence with it. It only logs now."""
    app = _app()
    aria = _reclass(app, "Aria", rpg.CharacterClass.Paladin, 6)
    # Out of slots: the engine lists nothing castable (the early return).
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Bless")])
    s = app.combat.get_agent_stats(app.bm, aria)
    s.spell_slots_remaining = [0] * 9
    app.combat.set_agent_stats(app.bm, aria, s)
    app._start_cast_spell("action")
    app._start_cast_spell("bonus")
    assert not app.action_used and not app.bonus_used

    # Castable, but none for this button (the menu's own empty check).
    s = app.combat.get_agent_stats(app.bm, aria)
    s.spell_slots_remaining = [2, 0, 0, 0, 0, 0, 0, 0, 0]
    app.combat.set_agent_stats(app.bm, aria, s)
    app._start_cast_spell("bonus")
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Hunter's Mark")])
    app._start_cast_spell("action")
    assert not app.action_used and not app.bonus_used
    assert "atk_action" in _ids(app, aria)
    print("✅ test_an_empty_spell_menu_spends_nothing passed")


def test_shield_of_faith_and_spiritual_weapon_are_bonus_actions():
    """Both had no casting_time in spells.json and so defaulted to Action."""
    app = _app()
    for name in ("Shield of Faith", "Spiritual Weapon"):
        assert _spell(app, name).casting_time == rpg.CastingTime.BonusAction, name
    print("✅ test_shield_of_faith_and_spiritual_weapon_are_bonus_actions passed")


def test_searing_and_shining_smite_cost_the_action_and_the_bonus_action():
    """House rule: these smites take both, flagged `costs_action_and_bonus` in spells.json."""
    for name, slots in (("Searing Smite", [4, 0, 0, 0, 0, 0, 0, 0, 0]),
                        ("Shining Smite", [0, 2, 0, 0, 0, 0, 0, 0, 0])):
        app = _app()
        aria = _reclass(app, "Aria", rpg.CharacterClass.Paladin, 6)
        skarn = _idx(app, "Skarn")
        app.combat.set_agent_spells(app.bm, aria, [_spell(app, name)])
        s = app.combat.get_agent_stats(app.bm, aria)
        s.spell_slots_remaining = slots
        app.combat.set_agent_stats(app.bm, aria, s)

        # The Bonus band never offers it, even with the Action still free.
        app._start_cast_spell("bonus")
        assert not app.pending_spell_slot, name

        # With the Bonus Action spent, the Action band refuses it too, and nothing is charged.
        app.bonus_used = True
        app._start_cast_spell("action")
        assert not app.pending_spell_slot and not app.action_used, name
        app.bonus_used = False

        app._start_cast_spell("action")      # one castable row casts directly
        assert app.pending_spell_slot == "action", name
        app._resolve_spell_cast(skarn)
        assert app.action_used and app.bonus_used, name
    print("✅ test_searing_and_shining_smite_cost_the_action_and_the_bonus_action passed")


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
        test_the_economy_band_headers_are_the_bands_own_two_buttons()
        test_the_bonus_band_stays_open_for_a_bonus_slot_sequence()
        test_the_bonus_attack_header_is_clickable_mid_sequence()
        test_the_bonus_spell_header_is_drawn_mid_sequence_but_refused()
        test_the_metamagic_toggles_answer_to_the_purse_and_not_the_band()
        test_the_metamagic_tick_is_the_armed_state()
        test_haste_grants_an_action_the_bonus_action_cannot_take()
        test_the_bonus_runs_are_built_in_draw_order()
        test_the_fleet_step_arm_of_step_of_the_wind_is_reachable()
        test_the_fleet_step_click_is_free_and_once_per_turn()
        test_a_click_on_an_unoffered_bonus_action_does_nothing()
        test_click_reaches_the_handler_for_the_bonus_band()
        test_the_channel_divinity_cluster_shares_one_resource()
        test_path_to_the_grave_is_a_bonus_action_option()
        test_the_duplicity_cluster_needs_an_illusion_on_the_map()
        test_trickster_transposition_needs_level_six()
        test_the_glamour_cluster_is_nested_inside_bardic_inspiration()
        test_the_glamour_windows_are_the_second_arm()
        test_restore_beguiling_magic_asks_for_a_resource_that_is_not_full()
        test_the_soulknife_pair_can_be_paid_for_with_dice()
        test_the_shadow_and_elemental_monks_split_action_from_bonus()
        test_elemental_attunement_ticks_once_it_is_running()
        test_the_fey_rider_is_clamped_without_the_menu_writing_it_back()
        test_misty_escape_is_a_reaction_the_band_still_hides()
        test_the_jump_row_narrows_when_something_is_adjacent()
        test_escape_needs_both_a_neighbour_and_a_grapple()
        test_drop_grapple_and_free_from_net_are_outside_the_band()
        test_bite_grappled_asks_the_engine_for_the_pairing()
        test_horde_breaker_is_offered_from_the_engine_list_and_checks_the_click()
        test_sudden_strike_is_offered_from_the_engine_list_and_checks_the_click()
        test_beast_master_command_and_beasts_strike()
        test_shadowy_dodge_cell_pick_submits_the_parked_window()
        test_the_fey_wanderer_rows()
        test_fey_reinforcements_casts_a_one_minute_summon_without_a_slot()
        test_misty_wanderer_pick_and_the_passenger_prompt()
        test_automated_summon_fey()
        test_beguiling_twist_is_offered_to_a_human_ranger()
        test_cunning_action_is_all_three_or_none()
        test_the_two_telekinetic_options_are_two_widgets()
        test_every_action_carries_an_economy_from_the_vocabulary()
        test_wild_magic_bonus_cast_offers_action_spells()
        test_divine_smite_is_a_bonus_action_and_keeps_the_attack_action()
        test_an_empty_spell_menu_spends_nothing()
        test_shield_of_faith_and_spiritual_weapon_are_bonus_actions()
        test_searing_and_shining_smite_cost_the_action_and_the_bonus_action()
        test_ids_are_unique()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All ActionMenu tests passed!")
