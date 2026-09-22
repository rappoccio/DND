#!/usr/bin/env python3
"""The prompt bus (MULTIPLAYER_PLAN.md M1, seam S2).

M1's acceptance criterion, in the plan's words: *"drives a scripted combat by submitting
prompt responses with **no pygame events at all**."* That is what the second half of this
file does — it parks the C++ engine on a real opportunity-attack window through a real
`App`, then answers the window by calling `bus.choose_label(...)`. No mouse, no
`pygame.event`, no `ContextMenu.handle`. Before M1 there was no way to do that, which is
why `memory/feedback_gui_not_tested.md` exists.

Two halves, mirroring `test_session_roster.py`:

  · the bus itself — ids, liveness, authorization, the stack, the wire projection —
    which needs neither the engine nor a real widget;
  · the reaction window driven end to end through `App`, which is the only thing that
    proves the conversion preserved the flow.

Covered here:
  · every Step 0.5 `prompt` field, and NO callables, reach the wire  (test_wire_projection)
  · an unknown id, a disabled option and a stale id each get their own closed-set error
                                                                    (test_submit_errors)
  · first valid submission wins; the second is `not_live`           (test_first_submission_wins)
  · authorization runs even for the DM's own click, and a player who
    does not own the prompt is refused                              (test_authorization)
  · the bus fills SessionRoster.prompt_lookup (M0's D-M0-3 hook)    (test_prompt_lookup_hook)
  · a re-ask supersedes the live prompt and runs NO callback        (test_supersede_runs_no_callback)
  · dismissal cancels and runs on_cancel                            (test_cancel_and_dismissal)
  · a submenu carries parent_id; answering the leaf ends the stack  (test_prompt_stack)
  · an OA parks the engine and opens a reaction prompt whose owner
    is the REACTOR's controller, not the actor's                    (test_oa_opens_reaction_prompt)
  · answering that prompt through the bus resumes the move          (test_answer_resumes_the_move)
  · a seated player may answer their own creature's window, and
    another player may not                                          (test_player_answers_own_reaction)
  · dismissing the window submits its Skip, so the flow advances    (test_dismissal_skips_the_window)

And the click path itself — a real `MOUSEBUTTONDOWN` through `App._handle_events` and
`ContextMenu.handle`, which is the one thing neither M0 nor M1 Step 2 could check:
  · clicking the popup row takes the opportunity attack               (test_click_takes_the_opportunity_attack)
  · clicking away from it submits the Skip                            (test_click_away_skips_the_window)

Step 3 then moved the remaining 79 sites onto the bus. Its three per-site judgements —
`owner`, `parent`, and which of the three widgets draws the prompt — get one check each:
  · a post-hit rider is owned by the ATTACKER's controller (G2)      (test_rider_prompt_owned_by_the_attacker)
  · a defender reaction is owned by the DEFENDER's, and the
    attacker's player is refused (G3)                                (test_defender_reaction_is_owned_by_the_defender)
  · the nested DM menus chain parent_id and stay DM-owned even when
    a player holds the token (G9)                                    (test_dm_menu_submenu_chain_carries_parent)
  · the value picker answers, and its empty commit is a cancel       (test_picker_renderer_answers_and_cancels)
  · the spell grid answers, and dismissing it chooses nothing        (test_spell_grid_renderer_answers_and_dismisses)
"""

import os
import sys

# Headless SDL: set before pygame is imported anywhere (main.py imports it at module
# scope), same pair as test_combat_panel.py and test_session_roster.py.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import rpg_battle_map as rpg

from prompts import (PromptBus, Prompt, Option, Response, PromptState,
                     options_from_pairs, ERR_NOT_LIVE, ERR_DENIED, ERR_BAD_OPTION,
                     ERR_PROTOCOL)
from net.roster import SessionRoster, Role, DM_PRINCIPAL_ID
from main import App
from gui_driver import (click_menu, click_away, menu_labels, screenshot,
                        cell_center, post_click,
                        picker_labels, click_picker, dismiss_picker,
                        grid_labels, click_grid, click_grid_away)

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260921
PC_TEAM = 2
FOE_TEAM = 1


# ─────────────────────────────────────────────────────────────────────────────
#  A renderer that records instead of drawing
# ─────────────────────────────────────────────────────────────────────────────

class RecordingRenderer:
    """Stands in for `ContextMenuRenderer`. The bus is duck-typed on exactly these
    three methods, which is the whole point of keeping pygame out of `prompts.py`."""

    def __init__(self):
        self.shown: list[Prompt] = []
        self.dismissed = 0
        self._submit = None
        self.current: Prompt | None = None

    def show(self, prompt, submit):
        self.shown.append(prompt)
        self.current = prompt
        self._submit = submit

    def dismiss(self):
        self.dismissed += 1
        self.current = None

    def is_showing(self):
        return self.current is not None

    def click(self, label):
        """What a mouse click on a menu row does: call the callback the renderer was
        handed. The bus must not care that the caller was a test."""
        opt = next(o for o in self.current.options if o.label == label)
        self._submit(opt.id)

    def click_away(self):
        self.current = None       # ContextMenu.dismiss()es itself before the app looks


def _bus(roster=None):
    r = RecordingRenderer()
    return PromptBus(roster=roster, renderer=r), r


# ─────────────────────────────────────────────────────────────────────────────
#  The bus, standalone
# ─────────────────────────────────────────────────────────────────────────────

def test_wire_projection():
    bus, _ = _bus()
    fired = []
    p = bus.ask(actor_idx=4, owner="p_abc", kind="reaction",
                title="Kira may react to Ghoul's attack",
                options=[Option("opt_0", "Shield (1st-level slot)",
                                on_choose=lambda: fired.append("shield")),
                         Option("opt_1", "Uncanny Dodge", enabled=False,
                                disabled_reason="Reaction already used"),
                         Option("opt_2", "Skip")],
                anchor=(120, 80))

    w = p.to_wire(seq=1291)
    assert w["t"] == "prompt" and w["v"] == 1
    assert w["id"] == "pr_00001" and w["parent_id"] is None and w["seq"] == 1291
    assert w["actor"] == 4 and w["kind"] == "reaction" and w["expects"] == "choice"
    assert w["title"] == "Kira may react to Ghoul's attack"
    assert w["deadline_ms"] is None
    assert w["options"][1] == {"id": "opt_1", "label": "Uncanny Dodge",
                               "enabled": False,
                               "disabled_reason": "Reaction already used"}
    # F4: the Prompt the bus holds is not the object on the wire. Nothing callable, and
    # no local-only render hint, may appear anywhere in the projection.
    def _scan(v):
        if callable(v):
            raise AssertionError("a callable reached the wire projection")
        if isinstance(v, dict):
            for k, x in v.items():
                assert k != "anchor", "the local render anchor is not wire data"
                _scan(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _scan(x)
    _scan(w)
    assert fired == [], "projecting a prompt must not run anything"
    print("✅ test_wire_projection passed")


def test_submit_errors():
    bus, r = _bus()
    p = bus.ask(0, DM_PRINCIPAL_ID, "action", "Attack with…",
                options=[Option("opt_0", "Longsword"),
                         Option("opt_1", "Shortsword", enabled=False,
                                disabled_reason="Off-hand already used")])

    assert bus.submit("pr_99999", Response(option="opt_0")).error == ERR_PROTOCOL
    assert bus.submit(p.id, Response(option="opt_7")).error == ERR_BAD_OPTION
    assert bus.submit(p.id, Response(option="opt_1")).error == ERR_BAD_OPTION, \
        "a disabled option is not answerable"
    assert p.is_live, "a refused submission leaves the prompt live"
    assert bus.submit(p.id, Response(option="opt_0")).ok
    assert bus.submit(p.id, Response(option="opt_0")).error == ERR_NOT_LIVE

    # expects="cell" wants a cell, not an option id.
    q = bus.ask(0, DM_PRINCIPAL_ID, "cell", "Click a square", expects="cell")
    assert bus.submit(q.id, Response(option="opt_0")).error == ERR_PROTOCOL
    assert bus.submit(q.id, Response(cell=(3, 4))).ok
    assert q.response.cell == (3, 4)
    print("✅ test_submit_errors passed")


def test_first_submission_wins():
    """NN4's race, resolved the way the plan says: by liveness, and by the bus marking
    the prompt answered BEFORE the callback runs — the callback is where a chained
    prompt (and, in M5, a second network submission) gets its chance to interleave."""
    bus, _ = _bus()
    seen = []

    def take_over():
        # Runs inside the first submission's callback, as a chained reaction would.
        seen.append(bus.submit(p.id, Response(option="opt_1")).error)

    p = bus.ask(0, DM_PRINCIPAL_ID, "reaction", "React?",
                options=[Option("opt_0", "Riposte", on_choose=take_over),
                         Option("opt_1", "Skip")])
    assert bus.submit(p.id, Response(option="opt_0")).ok
    assert seen == [ERR_NOT_LIVE], f"second submission should be refused, got {seen}"
    assert p.state is PromptState.ANSWERED and p.response.option == "opt_0"
    print("✅ test_first_submission_wins passed")


def test_authorization():
    roster = SessionRoster()
    kira = roster.add_principal("Kira", role=Role.PLAYER)
    theo = roster.add_principal("Theo", role=Role.PLAYER)
    bus, _ = _bus(roster)
    fired = []
    p = bus.ask(4, kira.id, "reaction", "Kira may react",
                options=[Option("opt_0", "Shield", on_choose=lambda: fired.append(1))])

    assert bus.submit(p.id, Response(option="opt_0"), theo.id).error == ERR_DENIED
    assert bus.submit(p.id, Response(option="opt_0"), "p_nobody").error == ERR_DENIED
    assert fired == [], "a denied submission must not reach the callback"
    assert p.is_live
    # NN4: the DM may answer any prompt at any time, including one owned by a player.
    assert bus.submit(p.id, Response(option="opt_0"), DM_PRINCIPAL_ID).ok
    assert fired == [1]
    print("✅ test_authorization passed")


def test_prompt_lookup_hook():
    """M0 left `SessionRoster.prompt_lookup` empty and denied every player (D-M0-3).
    Binding a bus is what fills it — and re-binding on a new encounter must re-fill it."""
    roster = SessionRoster()
    kira = roster.add_principal("Kira", role=Role.PLAYER)
    assert roster.prompt_lookup is None
    bus, _ = _bus(roster)
    assert roster.prompt_lookup is not None

    p = bus.ask(4, kira.id, "reaction", "Kira may react",
                options=[Option("opt_0", "Shield")])
    assert bus.lookup(p.id) == (kira.id, True)
    assert bus.lookup("pr_99999") == (None, False)
    bus.cancel(p.id)
    assert bus.lookup(p.id) == (kira.id, False)

    reloaded = SessionRoster()
    bus.bind_roster(reloaded)
    assert reloaded.prompt_lookup is not None
    print("✅ test_prompt_lookup_hook passed")


def test_supersede_runs_no_callback():
    """A call site that re-`show()`s over a live menu destroys it without resolving —
    Step 0.2's single-ContextMenu reality. The bus records that as `superseded`, and
    inventing a cancel there would fire a Skip nobody asked for."""
    bus, r = _bus()
    fired = []
    first = bus.ask(0, DM_PRINCIPAL_ID, "action", "First",
                    options=[Option("opt_0", "A", on_choose=lambda: fired.append("a"))],
                    on_cancel=lambda: fired.append("cancel"))
    second = bus.ask(1, DM_PRINCIPAL_ID, "action", "Second",
                     options=[Option("opt_0", "B")])

    assert first.state is PromptState.SUPERSEDED and fired == []
    assert bus.live is second
    assert bus.submit(first.id, Response(option="opt_0")).error == ERR_NOT_LIVE
    assert r.shown == [first, second]
    print("✅ test_supersede_runs_no_callback passed")


def test_cancel_and_dismissal():
    bus, r = _bus()
    fired = []
    p = bus.ask(0, DM_PRINCIPAL_ID, "reaction", "React?",
                options=[Option("opt_0", "Riposte",
                                on_choose=lambda: fired.append("riposte"))],
                on_cancel=lambda: fired.append("skip"))
    r.click_away()                         # the widget closed itself
    assert bus.renderer_dismissed() is True
    assert fired == ["skip"] and p.state is PromptState.CANCELLED
    assert bus.live is None
    assert bus.renderer_dismissed() is False, "nothing live ⇒ nothing to cancel"

    # A click that chose an option is NOT a dismissal: the prompt is already answered by
    # the time the event loop asks, so no cancel path runs.
    q = bus.ask(0, DM_PRINCIPAL_ID, "reaction", "React?",
                options=[Option("opt_0", "Riposte",
                                on_choose=lambda: fired.append("riposte"))],
                on_cancel=lambda: fired.append("skip"))
    r.click("Riposte")
    assert bus.renderer_dismissed() is False
    assert fired == ["skip", "riposte"] and q.state is PromptState.ANSWERED
    print("✅ test_cancel_and_dismissal passed")


def test_prompt_stack():
    """Step 0.2's fact 2: a submenu destroys its parent, so a flat slot would lose the
    back path. The stack is explicit — `parent_id` rides the wire — while the LOCAL
    renderer keeps today's behavior (answering or dismissing a submenu ends it all)."""
    bus, r = _bus()
    fired = []
    root = bus.ask(0, DM_PRINCIPAL_ID, "action", "NPC Automation",
                   options=[Option("opt_0", "Difficulty ▸")])
    child = bus.ask(0, DM_PRINCIPAL_ID, "action", "Difficulty",
                    options=[Option("opt_0", "Hard",
                                    on_choose=lambda: fired.append("hard"))],
                    parent=root)

    assert child.parent_id == root.id and child.to_wire()["parent_id"] == root.id
    assert root.is_live, "the parent stays live while its submenu is up"
    assert bus.live is child

    assert bus.submit(child.id, Response(option="opt_0")).ok
    assert fired == ["hard"]
    assert root.state is PromptState.SUPERSEDED, "answering the leaf ends the stack"
    assert bus.live is None and r.is_showing() is False
    print("✅ test_prompt_stack passed")


# ─────────────────────────────────────────────────────────────────────────────
#  A real reaction window, through a real App, with no pygame events
# ─────────────────────────────────────────────────────────────────────────────

def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    raise KeyError(name)


def _oa_weapon():
    """A plain 5 ft melee weapon, enough for the engine to offer a weapon OA."""
    w = rpg.Weapon()
    w.name = "Test Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice, pr.die_size, pr.bonus = 1, 8, 0
    w.physical_damage_types = [pr]
    return w


def _parked_app():
    """An `App` whose engine is parked on a genuine LeftReach (opportunity-attack)
    window, with the reaction prompt open on the bus.

    Mover walks out of Threat's reach; the engine suspends at the checkpoint exactly as
    it does when the DM drags a token on the real screen (`main.py`'s drag handler calls
    `begin_move` and then this same `_show_pending_reaction_menu`)."""
    app = App(MAP_PATH, seed=SEED)
    _place(app, "Mover", 5, 5)
    _place(app, "Threat", 4, 5)
    app.combat.apply_agent_configs(app.bm)
    mover, threat = _idx(app, "Mover"), _idx(app, "Threat")
    app.bm.set_agent_faction(mover, PC_TEAM)
    app.bm.set_agent_faction(threat, FOE_TEAM)

    s = app.combat.get_agent_stats(app.bm, mover)
    s.speed_walk = 60
    app.combat.set_agent_stats(app.bm, mover, s)
    app.combat.begin_turn(app.bm, mover)
    app.bm.placed_agents[mover].init_movement(60, 0, 0, 0)
    app.combat.set_agent_weapons(app.bm, threat, [_oa_weapon(), rpg.Weapon(), rpg.Weapon()])
    app._sync_roster_tokens()

    status = app.combat.begin_move(app.bm, mover, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected a parked OA, got {status}"
    app._show_pending_reaction_menu()
    return app, mover, threat


def _pos(app, idx):
    o = app.bm.placed_agents[idx].origin
    return (o.col, o.row)


def test_oa_opens_reaction_prompt():
    app, mover, threat = _parked_app()
    p = app.prompts.live
    assert p is not None and p.is_live and p.kind == "reaction"
    assert p.actor_idx == threat, "the prompt belongs to the reactor, not the mover"
    assert p.expects == "choice"
    assert "opportunity attack" in p.title
    # The options are the engine's, in the engine's order, with positional ids.
    ctx = app.combat.pending_decision().ctx
    assert [o.label for o in p.options] == [o.label for o in ctx.options]
    assert [o.id for o in p.options] == [f"opt_{i}" for i in range(len(ctx.options))]
    # The DM's own popup really is on screen — the local renderer is unchanged.
    assert app.context_menu.visible and len(app.context_menu.items) == len(ctx.options)
    print("✅ test_oa_opens_reaction_prompt passed")


def test_answer_resumes_the_move():
    """The M1 acceptance criterion: a combat flow driven to completion by answering a
    prompt, with no pygame event anywhere in the call stack."""
    app, mover, threat = _parked_app()
    weapon_label = next(o.label for o in app.combat.pending_decision().ctx.options
                        if o.kind == rpg.ReactionOptionKind.Weapon)

    assert app.prompts.choose_label(weapon_label).ok
    assert not app.combat.pending_decision().active, "the parked window resolved"
    assert app.combat.get_agent_conditions(app.bm, threat).reaction_used, \
        "the opportunity attack consumed the reactor's reaction"
    assert _pos(app, mover) == (6, 6), "the move completes once the window resolves"
    assert app.prompts.live is None and not app.context_menu.visible
    print("✅ test_answer_resumes_the_move passed")


def test_player_answers_own_reaction():
    """Step 0.2: `Prompt.owner` is load-bearing from the first conversion, because an
    opportunity attack is owned by the creature taking it — not by whoever is on turn."""
    app, mover, threat = _parked_app()
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    theo = app.roster.add_principal("Theo", role=Role.PLAYER)
    app.bm.set_agent_controller(threat, kira.id)
    app._sync_roster_tokens()

    # Re-open the window now that the reactor has an owner.
    app.prompts.cancel()
    assert not app.combat.pending_decision().active, "dismissal submitted the Skip"

    app.combat.begin_turn(app.bm, mover)
    app.bm.placed_agents[mover].init_movement(60, 0, 0, 0)
    app.bm.move_agent(mover, rpg.Cell(5, 5))
    c = app.combat.get_agent_conditions(app.bm, threat)
    c.reaction_used = False
    app.combat.set_agent_conditions(app.bm, threat, c)
    assert app.combat.begin_move(app.bm, mover, rpg.Cell(6, 6),
                                 rpg.MovementType.Walk) == rpg.FlowStatus.AwaitingDecision
    app._show_pending_reaction_menu()

    p = app.prompts.live
    assert p.owner == kira.id, f"owner should be the reactor's controller, got {p.owner}"
    label = next(o.label for o in app.combat.pending_decision().ctx.options
                 if o.kind == rpg.ReactionOptionKind.Weapon)
    assert app.prompts.choose_label(label, theo.id).error == ERR_DENIED
    assert app.combat.pending_decision().active, "a denied submit must not touch the engine"
    assert app.prompts.choose_label(label, kira.id).ok
    assert not app.combat.pending_decision().active
    print("✅ test_player_answers_own_reaction passed")


def test_dismissal_skips_the_window():
    """Clicking away from a reaction popup must still resolve the parked window, or a
    queued following reactor never gets its own popup and the turn freezes."""
    app, mover, threat = _parked_app()
    app.context_menu.dismiss()               # what ContextMenu.handle does on a click-away
    assert app.prompts.renderer_dismissed() is True
    assert not app.combat.pending_decision().active, "the Skip option was submitted"
    assert not app.combat.get_agent_conditions(app.bm, threat).reaction_used, \
        "declining must not spend the reaction"
    assert _pos(app, mover) == (6, 6), "the move still completes"
    print("✅ test_dismissal_skips_the_window passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The click path: a real pygame event, through the real event loop
# ─────────────────────────────────────────────────────────────────────────────

def test_click_takes_the_opportunity_attack():
    """The DM's actual mouse. Everything above enters through `bus.submit`; this enters
    through `pygame.event.post` and arrives at the same place — `_handle_events` →
    `ContextMenu.handle` → the bus's submit closure → the engine."""
    app, mover, threat = _parked_app()
    weapon_label = next(o.label for o in app.combat.pending_decision().ctx.options
                        if o.kind == rpg.ReactionOptionKind.Weapon)
    assert weapon_label in menu_labels(app), "the popup rows are the engine's options"

    click_menu(app, weapon_label)

    assert not app.combat.pending_decision().active
    assert app.combat.get_agent_conditions(app.bm, threat).reaction_used
    assert _pos(app, mover) == (6, 6)
    assert app.prompts.live is None and not app.context_menu.visible
    p = app.prompts.get("pr_00001")
    assert p.state is PromptState.ANSWERED and p.response.option == "opt_0"
    print("✅ test_click_takes_the_opportunity_attack passed")


def test_click_away_skips_the_window():
    """Dismissal, by clicking off the popup rather than by calling the bus. This is the
    path that used to depend on two flags read at the call site, and the one that freezes
    a turn if it regresses."""
    app, mover, threat = _parked_app()
    click_away(app)

    assert not app.context_menu.visible
    assert not app.combat.pending_decision().active, "the Skip option was submitted"
    assert not app.combat.get_agent_conditions(app.bm, threat).reaction_used
    assert _pos(app, mover) == (6, 6)
    assert app.prompts.get("pr_00001").state is PromptState.CANCELLED
    print("✅ test_click_away_skips_the_window passed")


# ─────────────────────────────────────────────────────────────────────────────
#  M1 Step 3 — the converted call sites
#
#  Step 3 moved 79 option lists onto the bus. The mechanical half (`options_from_pairs`)
#  is already covered above; what is NOT mechanical is the three judgements each site
#  makes, so there is one check per judgement rather than one per site:
#
#    · `owner` — the actor's controller almost everywhere (G2), the DEFENDER's at G3's
#      five reactions, and pinned to the DM at the authoring menus whatever the token
#      says (G9/G10);
#    · `parent` — named explicitly, and only by a row that really opens a submenu;
#    · the renderer — three widgets now draw prompts, and each has to answer and to
#      report its own dismissal.
# ─────────────────────────────────────────────────────────────────────────────

def _two_agents():
    """A striker and its victim, adjacent, on opposite sides. Enough for any rider."""
    app = App(MAP_PATH, seed=SEED)
    _place(app, "Striker", 5, 5)
    _place(app, "Victim", 6, 5)
    app.combat.apply_agent_configs(app.bm)
    atk, tgt = _idx(app, "Striker"), _idx(app, "Victim")
    app.bm.set_agent_faction(atk, PC_TEAM)
    app.bm.set_agent_faction(tgt, FOE_TEAM)
    app._sync_roster_tokens()
    return app, atk, tgt


def test_rider_prompt_owned_by_the_attacker():
    """G2 — the 24 post-hit riders. The rider is the attacker's own choice, so the owner
    follows the attacker's controller and nobody else may answer it."""
    app, atk, tgt = _two_agents()
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    theo = app.roster.add_principal("Theo", role=Role.PLAYER)
    app.bm.set_agent_controller(atk, kira.id)
    app._sync_roster_tokens()

    app._offer_rend_mind(atk, tgt, "Victim")
    p = app.prompts.live
    assert p is not None and p.kind == "action"
    assert p.actor_idx == atk and p.owner == kira.id
    assert "Rend Mind" in p.title and "Victim" in p.title
    assert app.context_menu.visible, "the DM's popup is the same widget it always was"
    assert menu_labels(app) == [o.label for o in p.options]

    assert app.prompts.submit(p.id, Response(option="opt_0"), theo.id).error == ERR_DENIED
    assert p.is_live, "a denied submission leaves the rider open"

    click_menu(app, "Skip")
    assert p.state is PromptState.ANSWERED
    assert app.prompts.live is None and not app.context_menu.visible
    print("✅ test_rider_prompt_owned_by_the_attacker passed")


def test_defender_reaction_is_owned_by_the_defender():
    """G3 — the five defender/third-party reactions, and the reason `owner` is a
    judgement at every site rather than a formula: here the creature that answers is
    not the creature acting, and the attacker's player must be refused."""
    app, atk, tgt = _two_agents()
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)   # the attacker's
    theo = app.roster.add_principal("Theo", role=Role.PLAYER)   # the defender's
    app.bm.set_agent_controller(atk, kira.id)
    app.bm.set_agent_controller(tgt, theo.id)
    app._sync_roster_tokens()

    app._offer_protective_field(atk, tgt, "Striker", "Victim",
                                rpg.AttackResult(), "Striker→Victim: HIT 7")
    p = app.prompts.live
    assert p is not None and p.kind == "reaction"
    assert p.actor_idx == tgt, "the reactor is the DEFENDER"
    assert p.owner == theo.id, "the defender's player answers it, not the attacker's"
    assert app.prompts.submit(p.id, Response(option="opt_0"), kira.id).error == ERR_DENIED

    click_menu(app, "Skip")
    assert p.state is PromptState.ANSWERED and app.prompts.live is None
    print("✅ test_defender_reaction_is_owned_by_the_defender passed")


def test_dm_menu_submenu_chain_carries_parent():
    """G9 — the nested authoring menus, through the real mouse.

    Two things at once: each submenu names the prompt whose row opened it (which is what
    `PromptBus.answering` exists for), and the owner stays the DM even though a player
    holds this token — `_ask_dm` pins it rather than deriving it, so seating a player can
    never hand them the authoring tools.
    """
    app, atk, tgt = _two_agents()
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    app.bm.set_agent_controller(atk, kira.id)
    app._sync_roster_tokens()
    o = app.bm.placed_agents[atk].origin

    assert not app.combat_active, "the agent menu is an out-of-combat right-click"
    post_click(app, cell_center(app, o.col, o.row), button=3)
    root = app.prompts.live
    assert root is not None and root.parent_id is None
    assert root.owner == DM_PRINCIPAL_ID, "an authoring menu never follows the token"
    assert "NPC Automation ▸" in menu_labels(app)

    click_menu(app, "NPC Automation ▸")
    auto = app.prompts.live
    assert auto is not None and auto.parent_id == root.id
    assert auto.to_wire()["parent_id"] == root.id

    click_menu(app, "Difficulty ▸")
    diff = app.prompts.live
    assert diff is not None and diff.parent_id == auto.id

    click_menu(app, "Level 3")
    assert app.bm.get_agent_npc_automation_difficulty(atk) == 3
    assert diff.state is PromptState.ANSWERED
    assert app.prompts.live is None and not app.context_menu.visible
    print("✅ test_dm_menu_submenu_chain_carries_parent passed")


def test_picker_renderer_answers_and_cancels():
    """The modal value picker, the bus's second renderer (10 sites, 9 of them single
    select). It commits on dismiss with an empty selection, which is not an answer — the
    renderer drops it and the event loop's `renderer_dismissed()` turns it into the
    cancel the call sites were already written against."""
    app, atk, _ = _two_agents()
    seen = []
    app._ask_actor(atk, "action", "Chromatic Orb: damage type",
                   [("Acid", lambda: seen.append("Acid")),
                    ("Fire", lambda: seen.append("Fire"))],
                   render="picker", on_cancel=lambda: seen.append("cancel"))
    p = app.prompts.live
    assert app._element_dialog.visible and not app.context_menu.visible
    assert picker_labels(app) == ["Acid", "Fire"]
    assert app._element_dialog._title == "Chromatic Orb: damage type", \
        "the widget keeps the exact title it had before the conversion"

    click_picker(app, "Fire")
    assert seen == ["Fire"] and p.state is PromptState.ANSWERED
    assert not app._element_dialog.visible and app.prompts.live is None

    seen.clear()
    app._ask_actor(atk, "action", "Chromatic Orb: damage type",
                   [("Acid", lambda: seen.append("Acid"))],
                   render="picker", on_cancel=lambda: seen.append("cancel"))
    q = app.prompts.live
    dismiss_picker(app)
    assert seen == ["cancel"], f"an empty commit must reach on_cancel, got {seen}"
    assert q.state is PromptState.CANCELLED and app.prompts.live is None
    print("✅ test_picker_renderer_answers_and_cancels passed")


def test_spell_grid_renderer_answers_and_dismisses():
    """The multi-column grid — Step 0.2 called the in-combat spell list the single
    most-used prompt in the game, and it is the reason the renderer mapping is
    one-to-many. Dismissing it runs no callback, exactly as before."""
    app, atk, _ = _two_agents()
    picked = []
    def _ask():
        app._ask_actor(atk, "action", "Cast a spell",
                       [("Magic Missile", lambda: picked.append("mm")),
                        ("Shield", lambda: picked.append("shield"))],
                       render="grid")
        return app.prompts.live

    p = _ask()
    assert app.spell_grid_menu.visible and not app.context_menu.visible
    assert app.spell_grid_menu.title == "Cast a spell"
    assert grid_labels(app) == ["Magic Missile", "Shield"]

    click_grid(app, "Shield")
    assert picked == ["shield"] and p.state is PromptState.ANSWERED
    assert not app.spell_grid_menu.visible and app.prompts.live is None

    q = _ask()
    click_grid_away(app)
    assert picked == ["shield"], "dismissing the grid chooses nothing"
    assert q.state is PromptState.CANCELLED and not app.spell_grid_menu.visible
    print("✅ test_spell_grid_renderer_answers_and_dismisses passed")


def main():
    tests = [
        test_wire_projection,
        test_submit_errors,
        test_first_submission_wins,
        test_authorization,
        test_prompt_lookup_hook,
        test_supersede_runs_no_callback,
        test_cancel_and_dismissal,
        test_prompt_stack,
        test_oa_opens_reaction_prompt,
        test_answer_resumes_the_move,
        test_player_answers_own_reaction,
        test_dismissal_skips_the_window,
        test_click_takes_the_opportunity_attack,
        test_click_away_skips_the_window,
        # M1 Step 3 — the converted call sites
        test_rider_prompt_owned_by_the_attacker,
        test_defender_reaction_is_owned_by_the_defender,
        test_dm_menu_submenu_chain_carries_parent,
        test_picker_renderer_answers_and_cancels,
        test_spell_grid_renderer_answers_and_dismisses,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_prompts: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_prompts: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    # `--shot <path>` renders the parked reaction popup to a PNG instead of running the
    # suite. Not an assertion — a way to LOOK at the widget, since the headless driver
    # draws to a real surface. The popup's appearance is otherwise unverifiable without
    # a display, and M1 changed what feeds it.
    if "--shot" in sys.argv:
        out = sys.argv[sys.argv.index("--shot") + 1]
        _app, _m, _t = _parked_app()
        print(screenshot(_app, out))
        sys.exit(0)
    sys.exit(main())
