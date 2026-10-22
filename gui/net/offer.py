"""The action offer: a player's own turn, as one prompt (MULTIPLAYER_PLAN.md D-M5-2).

M5a let a player answer a prompt the game asked them. This lets them act. On each step of
a turn whose token a player controls, the bus carries a `kind:"action"`,
`expects:"choice"` prompt owned by that player, with one option per action id on offer.
Choosing one runs `App.perform(id, owner)`, which re-checks the offer and `authorize()`
exactly as it does for the DM's click (D-M5-1).

**The offer is derived, never patched.** `ensure` runs once per frame, right after the
panel has rebuilt `_action_menu`, and asks one question: given the state right now, what
should the player be offered? If the answer differs from the live offer, the offer is
re-posted. If no offer should be up, the live one is withdrawn. Turn start, "after every
step" and "after a cancel" are all that one rule, so no action needs an "it changed" hook.

**What a player is offered** follows Step 0.12's walk of the 110 dispatch sites (`CLASS`):
  · I and C→I resolve on the choice, or through choice sub-prompts the bus already sends
    to the controller, so they are enabled;
  · A, A*, C→A, X, C→X and S need a pick on the map. A row in `WIRED` is enabled: its
    pick reaches the player as a target prompt (`net/picks.py`, M5d and M5e). The rest
    go out disabled, with a reason a player can read;
  · DM tools (`GROUP_SESSION`, `place_terrain`) are never sent at all.
An id this table does not know goes out disabled: a new action is unplayable remotely until
someone classifies it, never playable by accident.

The offer is posted with `render="remote"`, so the DM console draws nothing for it.
"""

from __future__ import annotations

from dataclasses import replace

from actions import GROUP_BONUS, GROUP_SESSION, METAMAGIC_VALUE_BY_ID
from net import move as net_move, picks as net_picks
from net.roster import DM_PRINCIPAL_ID
from prompts import Option

OFFER_KIND = "action"
OFFER_RENDER = "remote"

# Step 0.12's classes. The names are the plan's (C→I is "choice, then immediate").
I, C_I, A, A_MULTI, C_A, X, C_X, S, DM = (
    "I", "C→I", "A", "A*", "C→A", "X", "C→X", "S", "DM")

PLAYABLE = frozenset({I, C_I})

# The offer's Move row's section. Move is not an `ActionMenu` id, so it has no
# `Action.group`; the player's screen draws it under its own "Movement" heading (QOL Q4).
GROUP_MOVEMENT = "movement"

# The pick rows whose arms `net/picks.WIRED` projects (M5d). `CLASS` keeps their class;
# this is what makes them playable. A row goes in only with every arm it can reach.
WIRED = frozenset({
    # M5d.1 — weapon attacks and the picks that follow them
    "atk_action", "atk_bonus", "unarmed", "nick", "flurry_of_blows", "martial_arts",
    "gwm_hew", "war_priest", "shove_push", "shove_prone", "telekinetic_feat", "bm_maneuver",
    # M5d.2 — single-creature picks
    "escape_net", "hand_of_healing", "clairvoyant_combatant", "vow_of_enmity",
    "inspiring_smite", "healing_light", "lay_on_hands", "grant_inspiration",
    "telekinetic_psi", "use_item", "bastion_of_law",
    # M5d.3 — place picks
    "long_jump", "blink_steps", "psychic_teleport", "shadow_step", "shadow_arts_darkness",
    "steps_of_fey", "misty_escape", "warping_implosion", "wild_magic_teleport",
    "elemental_burst",
    # M5d.4 — multi-picks
    "mantle", "invoke_duplicity", "move_duplicity", "swap_duplicity",
    # M5e.1 — the spell pipeline
    "spell_action", "spell_bonus", "mantle_majesty", "wild_magic_bonus_cast",
    # M5e.2 — its spell list is a bus prompt now (E-5)
    "divine_intervention",
})

# Why a disabled row is disabled, in the player's words. The DM can still run any of these
# for them from the console (a take-over), which is what "ask the DM" means.
_REASON_AGENT = "Needs a target on the map — ask the DM for now"
_REASON_CELL = "Needs a spot on the map — ask the DM for now"
_REASON_SPELL = "Spells aren't playable remotely yet — ask the DM"
_REASON_UNKNOWN = "Not playable remotely yet — ask the DM"
REASONS = {A: _REASON_AGENT, A_MULTI: _REASON_AGENT, C_A: _REASON_AGENT,
           X: _REASON_CELL, C_X: _REASON_CELL, S: _REASON_SPELL}

# Every id `App._perform_action` dispatches, in dispatch order, with its Step 0.12 class
# (the Metamagic rows are M5e's E-7). `tests/test_offer.py` holds this to the dispatch
# sites both ways, the loop over the Metamagic ids included.
CLASS: dict[str, str] = {
    "atk_action": C_A,
    "nick": A,
    "unarmed": C_A,
    "dash": I,
    "dodge": I,
    "disengage": I,
    "hide": I,
    "prone": I,
    "spell_action": S,
    "long_jump": X,
    "standup": I,
    "use_portent": C_I,
    "grapple_drop": I,
    "use_item": C_A,
    "extinguish": I,
    "escape_net": A,
    "atk_bonus": C_A,
    "spell_bonus": S,
    "shove_push": A,
    "shove_prone": A,
    "grapple_esc": I,
    "telekinetic_feat": A,
    "hide_bonus": I,
    "dash_bonus": I,
    "disengage_bonus": I,
    "patient_defense": I,
    "wholeness_of_body": I,
    "hand_of_healing": A,
    "rage": I,
    "intimidating_presence": I,
    "zealous_presence": I,
    "clairvoyant_combatant": A,
    "vow_of_enmity": A,
    "inspiring_smite": A,
    "avenging_angel": I,
    "elder_champion": I,
    "living_legend": I,
    "magical_cunning": I,
    "healing_light": A,
    "turn_undead": I,
    "divine_intervention": S,
    "radiance": I,
    "preserve_life": I,
    "invoke_duplicity": X,
    "move_duplicity": X,
    "swap_duplicity": X,
    "steady_aim": I,
    "war_priest": A,
    "bite_grappled": I,
    "gwm_hew": A,
    "blink_steps": X,
    "martial_arts": A,
    "flurry_of_blows": C_A,
    "second_wind": I,
    "bm_maneuver": C_A,
    "one_with_shadows": I,
    "merge_shadows": I,
    "action_surge": I,
    "lay_on_hands": A,
    "grant_inspiration": A,
    "mantle": A_MULTI,
    "mantle_majesty": S,
    "unbreakable_majesty": I,
    "beguiling_restore": I,
    "use_inspiration": I,
    "sacred_weapon": I,
    "corona": I,
    "telekinetic_psi": A,
    "dread_ambusher": I,
    "tireless": I,
    "natures_veil": I,
    "psychic_veil": I,
    "psychic_teleport": X,
    "shadow_step": X,
    "cloak_of_shadows": I,
    "shadow_arts_darkness": X,
    "fey_effect": I,
    "steps_of_fey": X,
    "misty_escape": X,
    "elemental_attunement": C_I,
    "elemental_burst": C_X,
    "quivering_palm": I,
    "dragon_wings": I,
    "draconic_resistance": I,
    "bend_luck": C_I,
    "boon_of_fate": C_I,
    "tides_of_chaos": I,
    "innate_sorcery": I,
    "trance_of_order": I,
    "bastion_of_law": C_A,
    "clockwork_cavalcade": I,
    "revelation_in_flesh": I,
    "warping_implosion": X,
    "wild_magic_extra_action": I,
    "wild_magic_bonus_cast": S,
    "wild_magic_teleport": X,
    "companion": C_I,
    "familiar": C_I,
    "charge_arcane_ward": C_I,
    "wild_shape": C_I,
    "step_of_wind": I,
    # The nine Metamagic toggles, dispatched by one loop over `METAMAGIC_VALUE_BY_ID`.
    # Arming costs nothing; the Sorcery Points go with the cast that carries it (E-7).
    **{mm_id: I for mm_id in METAMAGIC_VALUE_BY_ID},
    "haste_action": I,
    "place_terrain": DM,
    "pause_resume": DM,
    "reaction_timer": DM,
    "end_turn": I,
    "end_combat": DM,
    "table": DM,                 # D-M7-5: the Table menu
    "drop_concentration": I,
    "drop_weapon_main": I,
    "drop_weapon_off": I,
    "drop_weapon_rng": I,
}


def offered(app, actor: int, owner: str) -> list[Option]:
    """The options for `owner`, from the `_action_menu` the panel drew this frame.

    Built from the same dict `perform` checks, so the offer can never name an id that
    `perform` would refuse for not being on the menu. Disabled rows carry no callback: the
    bus refuses a disabled option before any callback could run, and a row that cannot run
    should not hold a reference that could.

    Move comes first (D-M5-4). It is not an `ActionMenu` id and its callback is not
    `perform`: it opens the Move prompt, which `net/move.py` owns.

    Each row carries the DM panel's section and colour (QOL Q4), and the rows come in the
    order the panel draws them, so the player's screen lays the turn out as the DM's does.
    """
    out: list[Option] = [replace(net_move.option(app, actor, owner), group=GROUP_MOVEMENT)]
    for act in app._action_menu.values():
        # The one filter for DM tools. It is the group test, not the DM rows of `CLASS`,
        # so that a session tool added later is withheld whether or not anyone
        # classified it. `perform` refuses these for a player too; this keeps them off
        # the wire.
        if act.group == GROUP_SESSION or act.id == "place_terrain":
            continue
        look = {"group": act.group, "color": _color(app, act.id)}
        cls = CLASS.get(act.id)
        if not act.enabled:
            out.append(Option(act.id, act.label, enabled=False,
                              disabled_reason=act.disabled_reason or None, **look))
        elif cls in PLAYABLE or act.id in WIRED:
            out.append(Option(act.id, act.label,
                              on_choose=lambda aid=act.id: app.perform(aid, owner), **look))
        else:
            out.append(Option(act.id, act.label, enabled=False,
                              disabled_reason=REASONS.get(cls, _REASON_UNKNOWN), **look))
    return _dm_order(app, out)


def _color(app, action_id: str) -> str | None:
    """The DM's button colour for `action_id`, as "#rrggbb", read off the `btn_cbt_<id>`
    widget the panel draws: one source, so the two screens cannot drift apart. The draw
    pass has already run this frame, so a colour the panel sets as it draws (a Metamagic
    toggle's armed shade) is the one read here. No widget, no colour."""
    btn = getattr(app, "btn_cbt_" + action_id, None)
    if btn is None:
        return None
    r, g, b = (int(c) for c in tuple(btn.color)[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _dm_order(app, options: list[Option]) -> list[Option]:
    """`options` in the DM panel's draw order. Every group but §7 is built in the order it
    is drawn; §7 is drawn run by run (`App._BON_DRAW_RUNS`), so its rows are sorted by run.
    The sort is stable, so each run keeps the build order the panel draws it in."""
    run = {aid: i for i, ids in enumerate(app._BON_DRAW_RUNS) for aid in ids}
    last = len(app._BON_DRAW_RUNS)
    bonus = sorted((o for o in options if o.group == GROUP_BONUS),
                   key=lambda o: run.get(o.id, last))
    it = iter(bonus)
    return [next(it) if o.group == GROUP_BONUS else o for o in options]


def _projection(actor: int, owner: str, options: list[Option]) -> tuple:
    return (actor, owner,
            tuple((o.id, o.label, o.enabled, o.disabled_reason, o.group, o.color)
                  for o in options))


def gate(app) -> tuple[int, str] | None:
    """`(actor, owner)` when a player's offer should be up right now, else None."""
    if not app.combat_active or app.combat_paused:
        return None
    if app._npc_anim_defers() or app._npc_drive_idx >= 0:
        return None
    actor = app._current_agent_idx()
    if not 0 <= actor < len(app.bm.placed_agents):
        return None
    owner = app.roster.controller_of(actor)
    if owner == DM_PRINCIPAL_ID:
        return None
    if app.combat.pending_decision().active or app._target_pick_armed():
        return None
    return actor, owner


def ensure(app) -> None:
    """Make the live offer agree with the state: post it, re-post it, or withdraw it.

    Runs once per frame, after `_draw_panel()`. It never touches a prompt that is not its
    own: while anything else is live (a reaction, a sub-prompt, a DM popup), it waits, and
    the next frame after that prompt resolves posts a fresh offer. The Move prompt and the
    target prompt count as its own: they are the offer's children, so they are withdrawn
    when the state that asked for them has gone, and left alone while it holds.

    An armed pick comes first (M5d Step 0.1). While one is armed for a player, its target
    prompt is what that player is offered; the gate below stays closed until it resolves
    or is cancelled, and the frame after that posts the offer again.
    """
    bus = app.prompts
    live = bus.live
    live_ok = live is not None and live.is_live
    mine = live_ok and live is app._offer
    moving = live_ok and net_move.is_move_prompt(app, live)
    picking = live_ok and net_picks.is_pick_prompt(app, live)

    pick = net_picks.wanted(app)
    if pick is not None:
        arm, actor, owner = pick
        key = net_picks.projection(app, arm, actor, owner)
        if picking and key == app._pick_key:
            return
        if live_ok and not (mine or moving or picking):
            return
        if mine or moving or picking:
            bus.withdraw(live.id)
        app._pick_key = key
        net_picks.post(app, arm, actor, owner, app._offer)
        return
    if picking:
        bus.withdraw(live.id)
        live, live_ok = None, False
    app._pick_key = None

    want = gate(app)
    if want is None:
        if mine or moving:
            bus.withdraw(live.id)
        app._offer = None
        return
    if moving:
        if (live.actor_idx, live.owner) == want:
            return
        bus.withdraw(live.id)
        live, mine = None, False
    if live is not None and not mine:
        return
    actor, owner = want
    options = offered(app, actor, owner)
    key = _projection(actor, owner, options)
    if mine and key == app._offer_key:
        return
    # No parent: a re-post supersedes the stale offer, and no callback of the old one runs.
    app._offer = bus.ask(actor, owner, OFFER_KIND,
                         f"{app.bm.placed_agents[actor].name}'s turn", options,
                         render=OFFER_RENDER, cancellable=False)
    app._offer_key = key


# The DM's panel tools that do not act on the turn, so clicking one is not a takeover
# (D-M5-7, amended by M7). `table` is D-M7-5's Table menu.
NOT_A_TAKEOVER = frozenset({"reaction_timer", "pause_resume", "table"})


def take_over(app) -> None:
    """The DM is about to act from the panel, drag a token, or click the map during a
    player's turn (D-M5-7, D-M5-4.6, M5d Step 0.6).

    The live offer, or the Move or target prompt under it, is cancelled as the DM before
    the DM's action runs. The bus observer then logs the take-over, and the player's late
    submit gets `not_live`. A target prompt cancelled by the DM leaves its pick armed
    (`net/picks.post`), so the DM's click resolves it.
    """
    live = app.prompts.live
    if (live is not None and live.is_live
            and (live is app._offer or net_move.is_move_prompt(app, live)
                 or net_picks.is_pick_prompt(app, live))):
        app.prompts.cancel(live.id, DM_PRINCIPAL_ID)
