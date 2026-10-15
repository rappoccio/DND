#!/usr/bin/env python3
"""Agent and cell picks from the browser (MULTIPLAYER_PLAN.md D-M5-3, slice M5d).

An armed `pending_*` pick for a player's token reaches that player as a target prompt
(`net/picks.py`), and the answer runs `App.resolve_pick`, the chain the DM's map click
runs. These checks pin:

  · the arm table is the click chain, in its order          (test_the_arm_table_is_the_chain)
  · an attack from the offer, picked over the bus           (test_an_attack_picked_over_the_bus)
  · an empty square leaves the pick armed and re-posts       (test_an_empty_square_keeps_the_pick)
  · cancelling a fresh attack undoes the arm                 (test_cancelling_a_fresh_attack_undoes_it)
  · cancelling mid-sequence keeps the count                  (test_cancelling_mid_sequence_keeps_the_count)
  · Esc and the remote cancel leave the same state           (test_esc_and_the_remote_cancel_agree)
  · a resolved pick ends the undo                          (test_a_resolved_pick_ends_the_undo)
  · a cancelled punch gives the weapon back                  (test_a_cancelled_punch_restores_the_weapons)
  · a cancelled Hew gives the Hew back                       (test_a_cancelled_hew_is_refunded)
  · a cancelled Sweep continues the sequence                 (test_a_cancelled_sweep_continues_the_sequence)
  · a cancelled Vitality submits its Skip                    (test_a_cancelled_vitality_submits_its_skip)
  · every wired arm projects, and its cancel disarms         (test_every_wired_arm_projects_and_cancels)
  · an unwired arm still holds the offer back                (test_an_unwired_arm_holds_the_offer)
  · a parked window holds every pick but Vitality          (test_a_parked_window_holds_every_pick_but_vitality)
  · no prompt for the DM's own token                       (test_no_pick_prompt_for_the_dms_token)
  · a multi-pick carries Done                                (test_a_multi_pick_carries_done)
  · cells do not depend on where creatures stand             (test_cells_do_not_leak_positions)
  · a DM map click takes over and resolves the pick          (test_a_dm_click_takes_over_the_pick)
  · the long jump, picked over the bus                       (test_a_long_jump_picked_over_the_bus)
  · Lay on Hands refuses a full-HP creature, keeps the pick  (test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick)
  · Rally, Misty Escape, Shadow Step, Elemental Burst, Invoke Duplicity at 17 and
    Arcane Charge, each from the offer to resolution          (test_*_picked_over_the_bus)
  · Rally and Feint refuse an out-of-reach or own-token tap, and keep the pick
                                   (test_rally_out_of_range_keeps_the_pick, test_feint_*)
  · Dash after an unswung Attack undoes the arm; Attack after a Dash is refused; a Bite
    is one of the Attack's swings; a player's Cancel then Dash, and the DM's takeover
    then Dash, leave no attack           (test_dash_after_an_unswung_attack_undoes_the_arm,
    test_attack_after_a_dash_is_refused, test_a_bite_after_an_unswung_attack_is_one_of_its_swings,
    test_a_player_cancels_then_dashes, test_a_dm_takeover_then_dash_leaves_no_attack)
  · M5e.0: an unplaced summon is cleared at the turn boundary, holds the offer, and a
    cancelled form menu disarms it (test_a_summon_does_not_outlive_its_turn,
    test_an_armed_summon_holds_the_offer, test_a_cancelled_summon_form_disarms)
  · end to end: an attack over the socket                    (test_an_attack_over_the_wire)

The scene is `test_offer.py`'s: Aria (Fighter 5) at (3,3) with Skarn, a foe, at (4,3);
Kira controls Aria, Wen controls Cyra.
"""

import ast
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from net import offer as net_offer, picks as net_picks
from net.roster import DM_PRINCIPAL_ID
from prompts import Response

from gui_driver import cell_center, post_click
from test_combat_panel import _idx, _preserve_cwd_logs, _restore_cwd_logs
from test_live import _auth_frame, _ws
from test_offer import _aria_turn, _frame, _log, _offer, _table, _action_prompt
from test_submit import _drain, _next, _submit

_MAIN = os.path.join(_ROOT, "gui", "main.py")


# ─────────────────────────────────────────────────────────────────────────────
#  Rig
# ─────────────────────────────────────────────────────────────────────────────

def _pos(app, idx):
    o = app.bm.placed_agents[idx].origin
    return (o.col, o.row)


def _pick(app):
    live = app.prompts.live
    return live if live is not None and live.is_live and net_picks.is_pick_prompt(app, live) else None


def _choose(app, who, option_id):
    offer = _offer(app)
    assert offer is not None, "no offer is up"
    res = app.prompts.submit(offer.id, Response(option=option_id), who.id)
    assert res.ok, res
    return offer


def _until_pick(app, who, first=0):
    """Answer the choice sub-prompts an action opens (a weapon, Damage / Grapple / Shove)
    with option `first` of the first one, then the first option after, until the target
    prompt is up. Returns it."""
    for _ in range(6):
        _frame(app)
        pick = _pick(app)
        if pick is not None:
            return pick
        live = app.prompts.live
        assert live is not None and live.is_live, "nothing is asking anything"
        assert live.owner == who.id, f"{live.title!r} is owned by {live.owner}"
        enabled = [o for o in live.options if o.enabled]
        res = app.prompts.submit(live.id, Response(option=enabled[first].id), who.id)
        assert res.ok, res
        first = 0
    raise AssertionError("no target prompt was posted")


def _make(app, idx, cls, level, **subclass):
    """Re-class agent `idx` in place, single-class. `subclass` fields (`fighter_subclass`,
    `monk_subclass`, …) are set BEFORE `initialize_class_resources`, so the resources
    that depend on them are granted. The turn does not move."""
    s = app.combat.get_agent_stats(app.bm, idx)
    s.set_class_level(cls, level)
    for k, v in subclass.items():
        setattr(s, k, v)
    s.initialize_class_resources(cls, level)
    app.combat.set_agent_stats(app.bm, idx, s)
    return s


def _free_cell(app, near, within, beyond=0, size=1):
    """The first cell, nearest first, more than `beyond` and at most `within` cells
    (Chebyshev) from agent `near`, where a `size` token can stand (`_can_place`, the
    check Invoke Duplicity makes). Asserts one exists, so a changed map fails loudly."""
    c0, r0 = _pos(app, near)
    found = sorted(
        (max(abs(c - c0), abs(r - r0)), r, c)
        for r in range(max(0, r0 - within), min(app.bm.grid_rows, r0 + within + 1))
        for c in range(max(0, c0 - within), min(app.bm.grid_cols, c0 + within + 1))
        if beyond < max(abs(c - c0), abs(r - r0))
        and app._can_place(rpg.Cell(c, r), size))
    assert found, f"no free cell within {within} (beyond {beyond}) of agent {near}"
    _, r, c = found[0]
    return (c, r)


def _res(app, idx, name):
    r = app.combat.get_agent_stats(app.bm, idx).get_resource(name)
    return r.current if r else 0


def _record(app):
    """Every combat-log line from here on, oldest first. `combat_log` itself is newest
    first and keeps ten, so a test cannot slice it."""
    lines = []
    real = app._combat_log_add
    app._combat_log_add = lambda msg: (lines.append(msg), real(msg))
    return lines


def _attack_fields(app):
    return (app.pending_attack_slot, app.attacks_remaining, app._attack_sequence_slot,
            app.pending_attack_offhand, app.pending_attack_resource, app.action_used)


def _esc(app):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0,
                                         unicode="\x1b", scancode=41))
    assert app._handle_events() is not False


def _armed_value(app, arm, aria, skarn):
    if arm.name in ("pending_cleave", "pending_sweep"):
        return {"action": None, "result": None, "first": skarn, "attacker": aria}
    if arm.name in ("pending_rally", "pending_feint"):
        return aria
    if arm.idle is False:
        return True
    if arm.idle == -1:
        return 0
    if arm.idle == "":
        return "action"
    raise AssertionError(arm.name)


# ─────────────────────────────────────────────────────────────────────────────
#  The table holds to the chain
# ─────────────────────────────────────────────────────────────────────────────

def test_the_arm_table_is_the_chain():
    """`ARMS` is `resolve_pick`'s if/elif chain, in its order, plus the jump. The order
    matters: the arm the prompt is posted for must be the arm the answer resolves."""
    tree = ast.parse(open(_MAIN, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "resolve_pick")
    node = next(n for n in fn.body if isinstance(n, ast.If))
    chain = []
    while isinstance(node, ast.If):
        first = next(n for n in ast.walk(node.test)
                     if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                     and n.value.id == "self")
        chain.append(first.attr)
        node = node.orelse[0] if len(node.orelse) == 1 else None
    names = [a.name for a in net_picks.ARMS]
    assert names[-1] == "jump_overlay_active", names[-1]
    assert names[:-1] == chain, (names, chain)

    # Every field the offer waits on is an arm here. `pending_beguiling_bard` is the one
    # exception: it is armed beside `pending_beguiling`, which the chain tests instead.
    from main import App
    waits = {n for n, _ in App._TARGET_PICK_ARMS} - {"pending_beguiling_bard"}
    assert waits <= set(names), sorted(waits - set(names))
    for arm in net_picks.ARMS:
        if arm.name in net_picks.WIRED:
            assert arm.cancel is not None, f"{arm.name} is wired with no cancel"
    print("✅ test_the_arm_table_is_the_chain")


# ─────────────────────────────────────────────────────────────────────────────
#  Weapon attacks (M5d.1)
# ─────────────────────────────────────────────────────────────────────────────

def test_an_attack_picked_over_the_bus():
    """Kira chooses Attack. The target prompt is hers, `kind:"target"`, expects a cell,
    hangs from the offer, and accepts Skarn's square. Her cell resolves the swing against
    Skarn, exactly as the DM's click would, and the offer comes back with a swing owed."""
    app, kira, _ = _aria_turn()
    skarn = _idx(app, "Skarn")
    offer = _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    assert pick.owner == kira.id and pick.kind == "target" and pick.expects == "cell", pick
    assert pick.parent_id == offer.id, (pick.parent_id, offer.id)
    assert pick.render == net_picks.PICK_RENDER
    assert _pos(app, skarn) in pick.cells
    new = _record(app)
    res = app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id)
    assert res.ok, res
    assert any("Aria→Skarn" in line for line in new), new
    assert app.action_used and app.attacks_remaining == 1, _attack_fields(app)
    assert app.pending_attack_slot == "", "the swing left the map armed"
    _frame(app)
    again = _offer(app)
    assert again is not None and again.id != offer.id, "no fresh offer after the swing"
    assert any(o.id == "atk_action" and o.enabled for o in again.options), "no swing owed"
    print("✅ test_an_attack_picked_over_the_bus")


def test_an_empty_square_keeps_the_pick():
    """A cell with nobody on it is accepted on the wire (it is a square she may see), but
    no branch takes it: one log line, the attack stays armed, and the next frame posts the
    prompt again. Nothing is spent."""
    app, kira, _ = _aria_turn()
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    res = app.prompts.submit(pick.id, Response(cell=(0, 0)), kira.id)
    assert res.ok, res
    assert app.combat_log[0] == net_picks.NOT_TAKEN, app.combat_log[0]
    assert app.pending_attack_slot == "action" and not app.action_used, _attack_fields(app)
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "the pick was not posted again"
    print("✅ test_an_empty_square_keeps_the_pick")


def test_cancelling_a_fresh_attack_undoes_it():
    """No swing yet: the cancel leaves the attack fields as they were before Attack, so no
    seeded count survives, and the offer comes back."""
    app, kira, _ = _aria_turn()
    before = _attack_fields(app)
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    assert app.attacks_remaining > 0, "Attack did not seed its count"
    res = app.prompts.cancel_as(pick.id, kira.id)
    assert res.ok, res
    assert _attack_fields(app) == before, (_attack_fields(app), before)
    _frame(app)
    assert _offer(app) is not None, "the offer did not come back"
    print("✅ test_cancelling_a_fresh_attack_undoes_it")


def test_cancelling_mid_sequence_keeps_the_count():
    """After one swing of two, Attack (1) re-arms. A cancel then only disarms: the count and
    the Action already spent stay, and Attack (1) is still on the offer."""
    app, kira, _ = _aria_turn()
    skarn = _idx(app, "Skarn")
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id).ok
    _frame(app)
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    mid = _attack_fields(app)
    assert mid[0] == "action" and mid[1] == 1, mid
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    assert _attack_fields(app) == ("",) + mid[1:], (_attack_fields(app), mid)
    _frame(app)
    assert any(o.id == "atk_action" and o.enabled for o in _offer(app).options)
    print("✅ test_cancelling_mid_sequence_keeps_the_count")


def test_esc_and_the_remote_cancel_agree():
    """D-M5-9's cancel row: the DM's Esc and Kira's cancel run the same function, so they
    leave the same state behind. Before M5d an armed attack had no Esc at all."""
    def remote():
        app, kira, _ = _aria_turn()
        _choose(app, kira, "atk_action")
        pick = _until_pick(app, kira)
        assert app.prompts.cancel_as(pick.id, kira.id).ok
        return _attack_fields(app), app.combat_log[0]

    def esc():
        app, kira, _ = _aria_turn()
        _choose(app, kira, "atk_action")
        pick = _until_pick(app, kira)
        _esc(app)
        fields, line = _attack_fields(app), app.combat_log[0]
        # The DM's Esc does not go through the bus: the frame after it withdraws Kira's
        # prompt, which no longer has a pick behind it, and posts her offer again.
        _frame(app)
        assert not pick.is_live, "Kira's prompt outlived the pick"
        assert _offer(app) is not None, "the offer did not come back after Esc"
        return fields, line

    a, b = remote(), esc()
    assert a == b, (a, b)
    assert a[1] == "Attack cancelled.", a
    print("✅ test_esc_and_the_remote_cancel_agree")


def test_a_resolved_pick_ends_the_undo():
    """`perform`'s snapshot is good only until a pick resolves. A sequence that re-arms on
    its own after a swing (a bonus sequence, a rider's continuation) is not undone back
    past that swing: its cancel only disarms."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    app._snapshot_attack_arm(aria)
    app._start_extra_attack(weapon_idx=0, label="Extra attack", slot="action")
    _frame(app)
    assert app.prompts.submit(_pick(app).id, Response(cell=_pos(app, skarn)), kira.id).ok
    app._start_extra_attack(weapon_idx=0, label="Extra attack", slot="action")
    seq = app._attack_sequence_slot
    _frame(app)
    assert app.prompts.cancel_as(_pick(app).id, kira.id).ok
    assert app._attack_sequence_slot == seq == "action", (app._attack_sequence_slot, seq)
    print("✅ test_a_resolved_pick_ends_the_undo")


def test_a_cancelled_punch_restores_the_weapons():
    """Unarmed Strike → Damage swaps a punch into slot 0 when it arms. Cancelling puts the
    weapons back, by name and order."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    names = [w.name for w in app.combat.get_agent_weapons(app.bm, aria)]
    _choose(app, kira, "unarmed")
    pick = _until_pick(app, kira)            # the first option is Damage
    assert app.pending_attack_slot == "action", "Damage did not arm the attack"
    assert [w.name for w in app.combat.get_agent_weapons(app.bm, aria)] != names
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    assert [w.name for w in app.combat.get_agent_weapons(app.bm, aria)] == names
    assert app._unarmed_strike_original_weapons is None
    print("✅ test_a_cancelled_punch_restores_the_weapons")


def test_a_cancelled_hew_is_refunded():
    """Hew clears `gwm_hew_available` when it arms. `perform`'s snapshot holds it, so a
    cancel before the swing hands it back."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    cond = app.combat.get_agent_conditions(app.bm, aria)
    cond.gwm_hew_available = True
    app.combat.set_agent_conditions(app.bm, aria, cond)
    app._snapshot_attack_arm(aria)             # what `perform` does before any action
    cond = app.combat.get_agent_conditions(app.bm, aria)
    cond.gwm_hew_available = False             # what `_start_gwm_hew` does when it arms
    app.combat.set_agent_conditions(app.bm, aria, cond)
    app._start_extra_attack(weapon_idx=0, label="Great Weapon Master: Hew")
    _frame(app)
    pick = _pick(app)
    assert pick is not None and pick.owner == kira.id
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    assert app.combat.get_agent_conditions(app.bm, aria).gwm_hew_available, "Hew not refunded"
    assert app.attacks_remaining == 0 and app._attack_sequence_slot == ""
    print("✅ test_a_cancelled_hew_is_refunded")


def test_a_cancelled_sweep_continues_the_sequence():
    """Sweeping Attack interrupts an Extra Attack sequence. Declining the second target must
    continue it, as a refused pick does; a flag reset alone would leave it stalled."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    calls = []
    real = app._continue_attack_sequence_after_rider
    app._continue_attack_sequence_after_rider = lambda i: (calls.append(i), real(i))
    app.pending_sweep = {"action": None, "result": None, "first": skarn, "attacker": aria}
    _frame(app)
    pick = _pick(app)
    assert pick is not None and pick.kind == "target", pick
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    assert app.pending_sweep is None
    assert calls == [aria], calls
    print("✅ test_a_cancelled_sweep_continues_the_sequence")


def test_a_cancelled_vitality_submits_its_skip():
    """Vitality of the Tree arms inside a parked reaction window. Its cancel submits the
    window's Skip; a flag reset alone would leave the engine waiting forever."""
    app, kira, _ = _aria_turn()
    skips = []
    app._submit_reaction_skip = lambda: skips.append(True)
    app.pending_vitality_target = True
    app._vitality_option_index = 0
    _esc(app)
    assert skips == [True], "the Skip was not submitted"
    assert not app.pending_vitality_target and app._vitality_option_index == -1
    print("✅ test_a_cancelled_vitality_submits_its_skip")


# ─────────────────────────────────────────────────────────────────────────────
#  Every arm (M5d.2 – M5d.4)
# ─────────────────────────────────────────────────────────────────────────────

def test_every_wired_arm_projects_and_cancels():
    """Each wired arm, armed on Aria's turn, is posted to Kira with its own kind and title;
    her cancel runs its cancel, which leaves it idle, and the offer comes back. Vitality
    needs a live window, and the jump its own landing set: both are checked on their own."""
    skip = {"pending_vitality_target", "jump_overlay_active"}
    for arm in net_picks.ARMS:
        if arm.name not in net_picks.WIRED or arm.name in skip:
            continue
        app, kira, _ = _aria_turn()
        aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
        app.pending_flurry_atk_idx = aria
        setattr(app, arm.name, _armed_value(app, arm, aria, skarn))
        _frame(app)
        pick = _pick(app)
        assert pick is not None, f"{arm.name}: no target prompt"
        assert (pick.owner, pick.kind, pick.title) == (kira.id, arm.kind, arm.title(app)), (
            arm.name, pick.owner, pick.kind, pick.title)
        assert app.prompts.cancel_as(pick.id, kira.id).ok
        assert not arm.armed(app), f"{arm.name}: the cancel left it armed"
        _frame(app)
        assert _offer(app) is not None, f"{arm.name}: the offer did not come back"
    print("✅ test_every_wired_arm_projects_and_cancels")


def test_an_unwired_arm_holds_the_offer():
    """A spell pick is M5e's. While one is armed the offer is held back, as in M5b, and no
    target prompt is posted: the DM resolves it."""
    app, kira, _ = _aria_turn()
    app.pending_spell_slot = "action"
    _frame(app)
    assert _offer(app) is None and _pick(app) is None, app.prompts.live
    print("✅ test_an_unwired_arm_holds_the_offer")


class _ParkedWindow:
    """`app.combat`, except that a reaction window reads as parked, with `reactor` to
    answer it. Everything else is the real engine."""

    def __init__(self, real, reactor):
        from types import SimpleNamespace
        self._real = real
        self._pd = SimpleNamespace(active=True, ctx=SimpleNamespace(reactor_idx=reactor))

    def pending_decision(self):
        return self._pd

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_a_parked_window_holds_every_pick_but_vitality():
    """While a reaction window is parked, an armed attack waits: its prompt would race the
    reaction. Vitality of the Tree is armed inside that window, so it alone is posted."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    real = app.combat
    app.combat = _ParkedWindow(real, aria)
    try:
        app.pending_attack_slot = "action"
        assert net_picks.wanted(app) is None, "an attack pick was wanted over a parked window"
        app.pending_attack_slot = ""
        app.pending_vitality_target = True
        want = net_picks.wanted(app)
        assert want is not None and want[0].name == "pending_vitality_target", want
        assert want[1:] == (aria, kira.id), want
    finally:
        app.combat = real
    print("✅ test_a_parked_window_holds_every_pick_but_vitality")


def test_no_pick_prompt_for_the_dms_token():
    """Brannor is the DM's. An attack armed on his turn is the DM's to click: no prompt is
    posted for anyone."""
    from test_combat_panel import _goto
    app, kira, _ = _aria_turn()
    _goto(app, "Brannor")
    app.pending_attack_slot = "action"
    _frame(app)
    assert _pick(app) is None and _offer(app) is None, app.prompts.live
    print("✅ test_no_pick_prompt_for_the_dms_token")


def test_a_multi_pick_carries_done():
    """Mantle of Inspiration collects recipients one pick at a time. Its prompt carries
    Done, and Done runs the Enter branch: the collection is finalised and the arm is idle."""
    app, kira, _ = _aria_turn()
    app.pending_mantle_active = True
    app.pending_mantle_targets = []
    _frame(app)
    pick = _pick(app)
    assert [o.id for o in pick.options] == [net_picks.DONE_ID], pick.options
    assert app.prompts.submit(pick.id, Response(option=net_picks.DONE_ID), kira.id).ok
    assert not app.pending_mantle_active
    assert app.combat_log[0] == "Mantle of Inspiration cancelled (no targets).", app.combat_log[0]
    print("✅ test_a_multi_pick_carries_done")


def test_cells_do_not_leak_positions():
    """With fog down the set is the grid. With fog up it is the explored mask, and moving
    a creature leaves it unchanged: the set says nothing about where anyone stands."""
    app, kira, _ = _aria_turn()
    skarn = _idx(app, "Skarn")
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    assert len(pick.cells) == app.bm.grid_cols * app.bm.grid_rows, len(pick.cells)
    app.show_fog = True
    _frame(app)
    fogged = _pick(app)
    explored = {(c.col, c.row) for c in app.bm.explored_cells()}
    assert fogged.cells == frozenset(explored), "the fogged set is not the explored mask"
    app.bm.set_agent_position(skarn, rpg.Cell(5, 3))
    assert net_picks.cells(app, net_picks.BY_NAME["pending_attack_slot"], 0) == sorted(explored)
    print("✅ test_cells_do_not_leak_positions")


def test_a_dm_click_takes_over_the_pick():
    """Step 0.6: with Kira's target prompt up, the DM clicks Skarn on the map. The prompt is
    cancelled as the DM (one `takeover` line), the pick stays armed for that click, and the
    click resolves it. Kira's late cell is `not_live`."""
    tmp = tempfile.mkdtemp()
    try:
        app, kira, _ = _aria_turn(tmp)
        skarn = _idx(app, "Skarn")
        _choose(app, kira, "atk_action")
        pick = _until_pick(app, kira)
        new = _record(app)
        post_click(app, cell_center(app, *_pos(app, skarn)))
        late = app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id)
        lines = _log(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert any("Aria→Skarn" in line for line in new), "the DM's click did not swing"
    assert not late.ok and late.error == "not_live", late
    assert ("takeover", pick.id) in [(l["event"], l["prompt"]) for l in lines], lines
    print("✅ test_a_dm_click_takes_over_the_pick")


def test_a_long_jump_picked_over_the_bus():
    """The jump is not in the chain. Its prompt carries the landing set, a `kind:"cell"`,
    and a cell from it runs the jump; a cell outside it is refused on the wire."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _choose(app, kira, "long_jump")
    _frame(app)
    pick = _pick(app)
    assert pick is not None and pick.kind == "cell", pick
    land = {(c.col, c.row) for c in app.jump_reachable_cells}
    assert pick.cells == frozenset(land), "the prompt is not the landing set"
    assert land, "Aria can jump nowhere"
    outside = next((c, r) for r in range(app.bm.grid_rows) for c in range(app.bm.grid_cols)
                   if (c, r) not in land)
    bad = app.prompts.submit(pick.id, Response(cell=outside), kira.id)
    assert not bad.ok and bad.error == "bad_option", bad
    dest = sorted(land)[0]
    assert app.prompts.submit(pick.id, Response(cell=dest), kira.id).ok
    assert _pos(app, aria) == dest, (_pos(app, aria), dest)
    print("✅ test_a_long_jump_picked_over_the_bus")


def test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick():
    """A creature at full HP is refused the way an empty square is: nothing is spent, the
    pick stays armed and Kira is asked again. A hurt creature then takes the heal. (Found
    in the M5d manual pass: the full-HP tap used to disarm the pick silently.)"""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    s = _make(app, aria, rpg.CharacterClass.Paladin, 3)
    pool = s.get_resource("Lay on Hands").current
    _frame(app)
    _choose(app, kira, "lay_on_hands")
    pick = _until_pick(app, kira)
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id).ok
    assert app.pending_lay_on_hands, "a full-HP target disarmed the pick"
    assert not app.action_used
    assert app.combat.get_agent_stats(app.bm, aria).get_resource("Lay on Hands").current == pool
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "Kira was not asked again"
    t = app.combat.get_agent_stats(app.bm, skarn)
    t.hp_cur = t.hp_max - 5
    app.combat.set_agent_stats(app.bm, skarn, t)
    assert app.prompts.submit(again.id, Response(cell=_pos(app, skarn)), kira.id).ok
    assert not app.pending_lay_on_hands and app.action_used
    t = app.combat.get_agent_stats(app.bm, skarn)
    assert t.hp_cur == t.hp_max, (t.hp_cur, t.hp_max)
    print("✅ test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick")


def test_rally_picked_over_the_bus():
    """Battle Master Rally, from the offer: the maneuver prompt, then a creature. The die is
    spent, the Bonus Action is used, and the creature has temporary HP."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    _make(app, aria, rpg.CharacterClass.Fighter, 3,
          fighter_subclass=rpg.FighterSubclass.BattleMaster)
    dice = _res(app, aria, "Superiority Dice")
    _frame(app)
    _choose(app, kira, "bm_maneuver")
    pick = _until_pick(app, kira)
    assert pick.title == "Rally: choose a creature", pick.title
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id).ok
    assert app.pending_rally is None and app.bonus_used
    assert app.combat.get_agent_stats(app.bm, skarn).temp_hp > 0
    assert _res(app, aria, "Superiority Dice") == dice - 1
    print("✅ test_rally_picked_over_the_bus")


def _maneuver_out_of_reach(option, flag, beyond):
    """Arm a maneuver (option `option` of the maneuver prompt), move Skarn more than
    `beyond` cells away, tap him. Returns (app, kira, pick, dice before)."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    _make(app, aria, rpg.CharacterClass.Fighter, 3,
          fighter_subclass=rpg.FighterSubclass.BattleMaster)
    dice = _res(app, aria, "Superiority Dice")
    app.bm.set_agent_position(skarn, rpg.Cell(*_free_cell(app, aria, 12, beyond=beyond)))
    _frame(app)
    _choose(app, kira, "bm_maneuver")
    pick = _until_pick(app, kira, first=option)
    assert getattr(app, flag) is not None
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id).ok
    return app, kira, pick, dice


def test_rally_out_of_range_keeps_the_pick():
    """A creature beyond 30 ft is refused the way an empty square is: nothing is spent,
    the pick stays armed and Kira is asked again (the Lay on Hands 7(a) pattern)."""
    app, kira, pick, dice = _maneuver_out_of_reach(0, "pending_rally", 6)
    assert app.pending_rally is not None, "a far creature disarmed Rally"
    assert not app.bonus_used and _res(app, _idx(app, "Aria"), "Superiority Dice") == dice
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "Kira was not asked again"
    print("✅ test_rally_out_of_range_keeps_the_pick")


def test_feint_out_of_reach_keeps_the_pick():
    """The same for Feinting Attack, whose reach is 5 ft."""
    app, kira, pick, dice = _maneuver_out_of_reach(1, "pending_feint", 1)
    assert app.pending_feint is not None, "a far creature disarmed Feinting Attack"
    assert not app.bonus_used and _res(app, _idx(app, "Aria"), "Superiority Dice") == dice
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "Kira was not asked again"
    print("✅ test_feint_out_of_reach_keeps_the_pick")


def test_dash_after_an_unswung_attack_undoes_the_arm():
    """The arm-then-Dash question, on the DM console. Skarn is the DM's, so no prompt is
    involved. Attack arms the pick and seeds the sequence with the Action still unspent;
    Dash then spends the Action. Nothing has swung, so nothing of the attack may survive:
    no armed pick, no swings owed, and no Attack row on the menu."""
    from test_combat_panel import _goto
    app, _, _ = _aria_turn()
    _goto(app, "Skarn")
    _frame(app)
    assert app.perform("atk_action", DM_PRINCIPAL_ID), "Attack was refused"
    weapon = app.prompts.live          # Greataxe or a fist: the DM picks the axe
    assert app.prompts.submit(weapon.id, Response(option=weapon.options[0].id),
                              DM_PRINCIPAL_ID).ok
    _frame(app)
    armed = _attack_fields(app)
    assert app.pending_attack_slot == "action", armed
    assert app.perform("dash", DM_PRINCIPAL_ID), "Dash was refused"
    _frame(app)
    after = _attack_fields(app)
    assert app.action_used, after
    assert (app.pending_attack_slot, app.attacks_remaining, app._attack_sequence_slot) \
        == ("", 0, ""), f"armed {armed}, after the Dash {after}"
    atk = app._action_menu.get("atk_action")
    assert atk is None or not atk.enabled, "Attack is still on offer after the Dash"
    print("✅ test_dash_after_an_unswung_attack_undoes_the_arm")


def test_a_bite_after_an_unswung_attack_is_one_of_its_swings():
    """Bite (grappled) spends the Action by swinging inside its own handler. It is paid out
    of the Attack's swings, so it does not abandon the Attack: Aria (Fighter 5, DM-run
    here, no seats) still owes her second swing after it."""
    from test_action_menu import _app
    from test_combat_panel import _goto, _set_conditions, _weapon
    app = _app()
    aria, skarn = _goto(app, "Aria"), _idx(app, "Skarn")
    bite = _weapon(app, "Longsword")
    bite.auto_use_when_grappling = True
    app.combat.set_agent_weapons(app.bm, aria, [bite])
    _set_conditions(app, skarn, grappled=True, grappler_idx=aria)
    _frame(app)
    assert app.perform("atk_action", DM_PRINCIPAL_ID), "Attack was refused"
    weapon = app.prompts.live
    if weapon is not None and weapon.is_live:
        assert app.prompts.submit(weapon.id, Response(option=weapon.options[0].id),
                                  DM_PRINCIPAL_ID).ok
    _frame(app)
    assert app.pending_attack_slot == "action" and app.attacks_remaining == 2, _attack_fields(app)
    assert app.perform("bite_grappled", DM_PRINCIPAL_ID), "the Bite was refused"
    assert app.action_used
    assert (app.attacks_remaining, app._attack_sequence_slot) == (1, "action"), _attack_fields(app)
    print("✅ test_a_bite_after_an_unswung_attack_is_one_of_its_swings")


def test_attack_after_a_dash_is_refused():
    """The other order: Dash spends the Action at once, so the Attack row is gone and a
    stale click on it is refused."""
    from test_combat_panel import _goto
    app, _, _ = _aria_turn()
    _goto(app, "Skarn")
    _frame(app)
    assert app.perform("dash", DM_PRINCIPAL_ID), "Dash was refused"
    _frame(app)
    atk = app._action_menu.get("atk_action")
    assert atk is None or not atk.enabled, "Attack is on offer after the Dash"
    assert not app.perform("atk_action", DM_PRINCIPAL_ID), "Attack ran after the Dash"
    assert (app.pending_attack_slot, app.attacks_remaining) == ("", 0), _attack_fields(app)
    print("✅ test_attack_after_a_dash_is_refused")


def test_feint_on_yourself_keeps_the_pick():
    """Feinting Attack on the fighter's own token is refused, not silently dropped."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _make(app, aria, rpg.CharacterClass.Fighter, 3,
          fighter_subclass=rpg.FighterSubclass.BattleMaster)
    _frame(app)
    _choose(app, kira, "bm_maneuver")
    pick = _until_pick(app, kira, first=1)
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, aria)), kira.id).ok
    assert app.pending_feint == aria and not app.bonus_used
    print("✅ test_feint_on_yourself_keeps_the_pick")


def test_a_player_cancels_then_dashes():
    """Kira alone cannot reach Dash while her attack pick is up: the offer is gated. Her
    Cancel undoes the arm from the snapshot, so a Dash after it leaves no attack behind."""
    app, kira, _ = _aria_turn()
    _choose(app, kira, "atk_action")
    pick = _until_pick(app, kira)
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    _frame(app)
    _choose(app, kira, "dash")
    _frame(app)
    assert app.action_used
    assert (app.pending_attack_slot, app.attacks_remaining, app._attack_sequence_slot) \
        == ("", 0, ""), _attack_fields(app)
    offer = _offer(app)
    assert offer is None or not any(o.id == "atk_action" and o.enabled
                                    for o in offer.options), offer.options
    print("✅ test_a_player_cancels_then_dashes")


def test_a_dm_takeover_then_dash_leaves_no_attack():
    """The DM takes Kira's attack pick over from the panel (which leaves the arm armed for
    the DM's click) and clicks Dash instead. That is the DM-console state above, on a
    player's token: Kira's next offer must not carry an enabled Attack."""
    app, kira, _ = _aria_turn()
    _choose(app, kira, "atk_action")
    _until_pick(app, kira)
    net_offer.take_over(app)
    assert app.perform("dash", DM_PRINCIPAL_ID), "Dash was refused"
    _frame(app)
    assert (app.pending_attack_slot, app.attacks_remaining, app._attack_sequence_slot) \
        == ("", 0, ""), _attack_fields(app)
    offer = _offer(app)
    assert offer is None or not any(o.id == "atk_action" and o.enabled
                                    for o in offer.options), (
        "Kira's offer carries an enabled Attack", app.prompts.live)
    print("✅ test_a_dm_takeover_then_dash_leaves_no_attack")


# ─────────────────────────────────────────────────────────────────────────────
#  M5e.0 — the summon arm (F-M5e-4) and Attack → Spell (F-M5e-5)
# ─────────────────────────────────────────────────────────────────────────────

def _summon_beast(app, caster):
    """Give `caster` Summon Beast and a 2nd-level slot, and start the cast through
    `_activate_spell`, the menu's own entry point. That arms the summon and posts the
    form menu, owned by the caster's controller. Returns the form prompt."""
    from test_combat_panel import _spell
    app.combat.set_agent_spells(app.bm, caster, [_spell(app, "Summon Beast")])
    spells = app.combat.get_agent_spells(app.bm, caster)
    stats = app.combat.get_agent_stats(app.bm, caster)
    app._activate_spell("action", 0, 2, caster, spells, stats)
    form = app.prompts.live
    assert form is not None and form.is_live and "choose a form" in form.title, form
    return form


def test_a_summon_does_not_outlive_its_turn():
    """F-M5e-4.1: an unplaced summon is a pick like any other, so the turn boundary clears
    it. Left armed, the next combatant's click would spawn it, with them as the caster."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    form = _summon_beast(app, aria)
    assert app.prompts.submit(form.id, Response(option=form.options[0].id), kira.id).ok
    assert app.pending_summon_slot == "action" and app.pending_summon_monster, \
        (app.pending_summon_slot, app.pending_summon_monster)
    app._advance_turn()
    _frame(app)
    assert (app.pending_summon_slot, app.pending_summon_monster, app.pending_summon_spirit) \
        == ("", "", None), (app.pending_summon_slot, app.pending_summon_monster)
    print("✅ test_a_summon_does_not_outlive_its_turn")


def test_an_armed_summon_holds_the_offer():
    """F-M5e-4.2: while Aria's summon waits for a cell, Kira is not offered her turn as if
    nothing were pending. Until M5e.1 wires it, the DM places it, as for any unwired arm."""
    app, kira, _ = _aria_turn()
    form = _summon_beast(app, _idx(app, "Aria"))
    assert app.prompts.submit(form.id, Response(option=form.options[0].id), kira.id).ok
    _frame(app)
    assert app._target_pick_armed()
    assert _offer(app) is None, app.prompts.live
    print("✅ test_an_armed_summon_holds_the_offer")


def test_a_cancelled_summon_form_disarms():
    """F-M5e-4.3: the summon arms before its form menu. Cancelling the menu used to leave it
    armed with no creature, swallowing every map click."""
    app, kira, _ = _aria_turn()
    form = _summon_beast(app, _idx(app, "Aria"))
    assert app.prompts.cancel_as(form.id, kira.id).ok
    assert app.pending_summon_slot == "", app.pending_summon_slot
    assert not app.resolve_pick(rpg.Cell(*_pos(app, _idx(app, "Aria")))), \
        "a map click is still swallowed"
    _frame(app)
    assert _offer(app) is not None, app.prompts.live
    print("✅ test_a_cancelled_summon_form_disarms")


def test_misty_escape_picked_over_the_bus():
    """Archfey Misty Escape spends the Reaction, not the Bonus Action. A cell beyond 30 ft
    keeps the pick and asks again; a near one teleports Aria and brings the offer back."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _make(app, aria, rpg.CharacterClass.Warlock, 6,
          warlock_subclass=rpg.WarlockSubclass.Archfey)
    steps = _res(app, aria, "Steps of the Fey")
    assert steps > 0
    _frame(app)
    _choose(app, kira, "misty_escape")
    pick = _until_pick(app, kira)
    far = _free_cell(app, aria, 12, beyond=6)
    assert app.prompts.submit(pick.id, Response(cell=far), kira.id).ok
    assert app.pending_misty_escape, "a far cell disarmed the pick"
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "Kira was not asked again"
    dest = _free_cell(app, aria, 6)
    assert app.prompts.submit(again.id, Response(cell=dest), kira.id).ok
    assert _pos(app, aria) == dest, (_pos(app, aria), dest)
    assert not app.pending_misty_escape
    assert app.combat.get_agent_conditions(app.bm, aria).reaction_used
    assert _res(app, aria, "Steps of the Fey") == steps - 1
    assert not app.bonus_used, "Misty Escape spent the Bonus Action"
    _frame(app)
    assert _offer(app) is not None, "the offer did not come back"
    print("✅ test_misty_escape_picked_over_the_bus")


def test_shadow_step_picked_over_the_bus():
    """Shadow Step at Monk 11, so the dim-light gate of level 6 does not apply on this lit
    map. Kira's own cell cancels and spends nothing, like the Cancel button; a free cell
    then teleports her and spends the Bonus Action."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _make(app, aria, rpg.CharacterClass.Monk, 11,
          monk_subclass=rpg.MonkSubclass.WarriorOfShadow)
    _frame(app)
    _choose(app, kira, "shadow_step")
    pick = _until_pick(app, kira)
    new = _record(app)
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, aria)), kira.id).ok
    assert not app.pending_shadow_step and not app.bonus_used
    assert "Shadow Step cancelled." in new, new
    _frame(app)
    _choose(app, kira, "shadow_step")
    pick = _until_pick(app, kira)
    dest = _free_cell(app, aria, 6)
    assert app.prompts.submit(pick.id, Response(cell=dest), kira.id).ok
    assert _pos(app, aria) == dest, (_pos(app, aria), dest)
    assert not app.pending_shadow_step and app.bonus_used
    print("✅ test_shadow_step_picked_over_the_bus")


def test_elemental_burst_picked_over_the_bus():
    """Elemental Burst: the element picker (a `render="picker"` prompt) takes an option id
    over the bus, then the center cell. 2 Focus and the Action are spent, Skarn inside
    the sphere is hit or saves, and the arm is idle."""
    app, kira, _ = _aria_turn()
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    _make(app, aria, rpg.CharacterClass.Monk, 6,
          monk_subclass=rpg.MonkSubclass.WarriorOfFourElements)
    focus = _res(app, aria, "Focus Points")
    assert focus >= 2, focus
    _frame(app)
    _choose(app, kira, "elemental_burst")
    pick = _until_pick(app, kira)
    assert app.pending_elemental_burst >= 0
    new = _record(app)
    assert app.prompts.submit(pick.id, Response(cell=_pos(app, skarn)), kira.id).ok
    assert app.pending_elemental_burst == -1 and app.action_used
    assert _res(app, aria, "Focus Points") == focus - 2
    assert any("Skarn" in line for line in new), new
    print("✅ test_elemental_burst_picked_over_the_bus")


def test_invoke_duplicity_at_17_picked_over_the_bus():
    """Improved Duplicity places up to four. Before the first placement there is no Done,
    and a cancel spends nothing. The first placement spends Channel Divinity and the Bonus
    Action, and the re-posted pick then carries Done; a second placement spends nothing
    more, and Done ends the activation with two duplicates."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _make(app, aria, rpg.CharacterClass.Cleric, 17,
          cleric_subclass=rpg.ClericSubclass.TrickeryDomain)
    cd = _res(app, aria, "Channel Divinity")
    assert cd > 0
    _frame(app)
    _choose(app, kira, "invoke_duplicity")
    pick = _until_pick(app, kira)
    assert net_picks.DONE_ID not in [o.id for o in pick.options], pick.options
    assert app.prompts.cancel_as(pick.id, kira.id).ok
    assert not app.pending_invoke_duplicity
    assert _res(app, aria, "Channel Divinity") == cd and not app.bonus_used
    _frame(app)
    _choose(app, kira, "invoke_duplicity")
    pick = _until_pick(app, kira)
    assert app.prompts.submit(pick.id, Response(cell=_free_cell(app, aria, 2)), kira.id).ok
    assert _res(app, aria, "Channel Divinity") == cd - 1 and app.bonus_used
    assert len(app._my_duplicates(aria)) == 1
    _frame(app)
    second = _pick(app)
    assert second is not None and second.id != pick.id
    assert second.title == pick.title, (second.title, pick.title)
    assert net_picks.DONE_ID in [o.id for o in second.options], second.options
    assert app.prompts.submit(second.id, Response(cell=_free_cell(app, aria, 2)), kira.id).ok
    assert _res(app, aria, "Channel Divinity") == cd - 1, "the second placement spent again"
    assert len(app._my_duplicates(aria)) == 2
    _frame(app)
    third = _pick(app)
    assert app.prompts.submit(third.id, Response(option=net_picks.DONE_ID), kira.id).ok
    assert not app.pending_invoke_duplicity
    assert len(app._my_duplicates(aria)) == 2
    _frame(app)
    assert _offer(app) is not None, "the offer did not come back"
    print("✅ test_invoke_duplicity_at_17_picked_over_the_bus")


def test_arcane_charge_picked_over_the_bus():
    """EK 15 has attacked; Action Surge gives the Action back and arms Arcane Charge. A
    cell beyond 30 ft keeps the pick, a near one teleports Aria, and the offer comes back
    with Attack enabled: the surge's fresh Action survives the pick."""
    app, kira, _ = _aria_turn()
    aria = _idx(app, "Aria")
    _make(app, aria, rpg.CharacterClass.Fighter, 15,
          fighter_subclass=rpg.FighterSubclass.EldritchKnight)
    surges = _res(app, aria, "Action Surge")
    app.action_used = True
    _frame(app)
    _choose(app, kira, "action_surge")
    pick = _until_pick(app, kira)
    assert pick.title.startswith("Arcane Charge: "), pick.title
    assert _res(app, aria, "Action Surge") == surges - 1 and not app.action_used
    far = _free_cell(app, aria, 12, beyond=6)
    assert app.prompts.submit(pick.id, Response(cell=far), kira.id).ok
    assert app.arcane_charge_pending, "a far cell disarmed the pick"
    _frame(app)
    again = _pick(app)
    assert again is not None and again.id != pick.id, "Kira was not asked again"
    dest = _free_cell(app, aria, 6)
    assert app.prompts.submit(again.id, Response(cell=dest), kira.id).ok
    assert _pos(app, aria) == dest and not app.arcane_charge_pending
    _frame(app)
    offer = _offer(app)
    assert offer is not None, "the offer did not come back"
    assert any(o.id == "atk_action" and o.enabled for o in offer.options), offer.options
    print("✅ test_arcane_charge_picked_over_the_bus")


# ─────────────────────────────────────────────────────────────────────────────
#  Over the wire
# ─────────────────────────────────────────────────────────────────────────────

def test_an_attack_over_the_wire():
    """End to end from Kira's socket: Attack, a weapon if asked, then a `target` prompt
    whose parent is the offer, a cell, and a fresh offer."""
    with _table() as t:
        app = t.app
        skarn = _idx(app, "Skarn")
        t.start()
        with _ws(t.srv.port) as kira:
            kira.send_text(_auth_frame(t.credential(t.kira.id)))
            offer = _action_prompt(kira)
            kira.send_text(_submit(offer["id"], option="atk_action"))
            assert _next(kira, "submit_ack")["ok"]
            while True:
                frame = _next(kira, "prompt", match=lambda f: f["id"] != offer["id"])
                if frame["kind"] == "target":
                    break
                kira.send_text(_submit(frame["id"], option=frame["options"][0]["id"]))
                assert _next(kira, "submit_ack")["ok"]
            assert frame["expects"] == "cell" and frame["parent_id"] == offer["id"], frame
            kira.send_text(_submit(frame["id"], cell=list(_pos(app, skarn))))
            ack = _next(kira, "submit_ack")
            assert ack["ok"], ack
            again = _action_prompt(kira, exclude=(offer["id"],))
            _drain(kira, 0.2)
        t.stop()
        assert app.action_used and app.attacks_remaining == 1, _attack_fields(app)
        assert any(o["id"] == "atk_action" and o["enabled"] for o in again["options"])
    print("✅ test_an_attack_over_the_wire")


if __name__ == "__main__":
    _saved = _preserve_cwd_logs()
    try:
        test_the_arm_table_is_the_chain()
        test_an_attack_picked_over_the_bus()
        test_an_empty_square_keeps_the_pick()
        test_cancelling_a_fresh_attack_undoes_it()
        test_cancelling_mid_sequence_keeps_the_count()
        test_esc_and_the_remote_cancel_agree()
        test_a_resolved_pick_ends_the_undo()
        test_a_cancelled_punch_restores_the_weapons()
        test_a_cancelled_hew_is_refunded()
        test_a_cancelled_sweep_continues_the_sequence()
        test_a_cancelled_vitality_submits_its_skip()
        test_every_wired_arm_projects_and_cancels()
        test_an_unwired_arm_holds_the_offer()
        test_a_parked_window_holds_every_pick_but_vitality()
        test_no_pick_prompt_for_the_dms_token()
        test_a_multi_pick_carries_done()
        test_cells_do_not_leak_positions()
        test_a_dm_click_takes_over_the_pick()
        test_a_long_jump_picked_over_the_bus()
        test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick()
        test_rally_picked_over_the_bus()
        test_misty_escape_picked_over_the_bus()
        test_shadow_step_picked_over_the_bus()
        test_elemental_burst_picked_over_the_bus()
        test_invoke_duplicity_at_17_picked_over_the_bus()
        test_arcane_charge_picked_over_the_bus()
        test_rally_out_of_range_keeps_the_pick()
        test_feint_out_of_reach_keeps_the_pick()
        test_feint_on_yourself_keeps_the_pick()
        test_dash_after_an_unswung_attack_undoes_the_arm()
        test_a_bite_after_an_unswung_attack_is_one_of_its_swings()
        test_attack_after_a_dash_is_refused()
        test_a_player_cancels_then_dashes()
        test_a_dm_takeover_then_dash_leaves_no_attack()
        test_a_summon_does_not_outlive_its_turn()
        test_an_armed_summon_holds_the_offer()
        test_a_cancelled_summon_form_disarms()
        test_an_attack_over_the_wire()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All pick tests passed!")
