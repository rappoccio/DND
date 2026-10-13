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
    s = app.combat.get_agent_stats(app.bm, aria)
    s.set_class_level(rpg.CharacterClass.Paladin, 3)
    s.initialize_class_resources(rpg.CharacterClass.Paladin, 3)
    app.combat.set_agent_stats(app.bm, aria, s)
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
        test_an_attack_over_the_wire()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All pick tests passed!")
