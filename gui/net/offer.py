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
  · A, A*, C→A, X, C→X and S need a pick on the map, which the wire cannot carry until
    M5d and M5e, so they go out disabled, with a reason a player can read;
  · DM tools (`GROUP_SESSION`, `place_terrain`) are never sent at all.
An id this table does not know goes out disabled: a new action is unplayable remotely until
someone classifies it, never playable by accident.

The offer is posted with `render="remote"`, so the DM console draws nothing for it.
"""

from __future__ import annotations

from actions import GROUP_SESSION
from net.roster import DM_PRINCIPAL_ID
from prompts import Option

OFFER_KIND = "action"
OFFER_RENDER = "remote"

# Step 0.12's classes. The names are the plan's (C→I is "choice, then immediate").
I, C_I, A, A_MULTI, C_A, X, C_X, S, DM = (
    "I", "C→I", "A", "A*", "C→A", "X", "C→X", "S", "DM")

PLAYABLE = frozenset({I, C_I})

# Why a disabled row is disabled, in the player's words. The DM can still run any of these
# for them from the console (a take-over), which is what "ask the DM" means.
_REASON_AGENT = "Needs a target on the map — ask the DM for now"
_REASON_CELL = "Needs a spot on the map — ask the DM for now"
_REASON_SPELL = "Spells aren't playable remotely yet — ask the DM"
_REASON_UNKNOWN = "Not playable remotely yet — ask the DM"
REASONS = {A: _REASON_AGENT, A_MULTI: _REASON_AGENT, C_A: _REASON_AGENT,
           X: _REASON_CELL, C_X: _REASON_CELL, S: _REASON_SPELL}

# Every id `App._perform_action` dispatches, in dispatch order, with its Step 0.12 class.
# `tests/test_offer.py` holds this to the dispatch sites both ways.
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
    "haste_action": I,
    "place_terrain": DM,
    "pause_resume": DM,
    "end_turn": I,
    "end_combat": DM,
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
    """
    out: list[Option] = []
    for act in app._action_menu.values():
        # The one filter for DM tools. It is the group test, not the DM rows of `CLASS`,
        # so that a session tool added later is withheld whether or not anyone
        # classified it. `perform` refuses these for a player too; this keeps them off
        # the wire.
        if act.group == GROUP_SESSION or act.id == "place_terrain":
            continue
        cls = CLASS.get(act.id)
        if not act.enabled:
            out.append(Option(act.id, act.label, enabled=False,
                              disabled_reason=act.disabled_reason or None))
        elif cls in PLAYABLE:
            out.append(Option(act.id, act.label,
                              on_choose=lambda aid=act.id: app.perform(aid, owner)))
        else:
            out.append(Option(act.id, act.label, enabled=False,
                              disabled_reason=REASONS.get(cls, _REASON_UNKNOWN)))
    return out


def gate(app) -> tuple[int, str] | None:
    """`(actor, owner)` when a player's offer should be up right now, else None."""
    if not app.combat_active or app.combat_paused:
        return None
    if app._npc_anim is not None or app._npc_drive_idx >= 0:
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


def _projection(actor: int, owner: str, options: list[Option]) -> tuple:
    return (actor, owner,
            tuple((o.id, o.label, o.enabled, o.disabled_reason) for o in options))


def ensure(app) -> None:
    """Make the live offer agree with the state: post it, re-post it, or withdraw it.

    Runs once per frame, after `_draw_panel()`. It never touches a prompt that is not its
    own: while anything else is live (a reaction, a sub-prompt, a DM popup), it waits, and
    the next frame after that prompt resolves posts a fresh offer.
    """
    bus = app.prompts
    live = bus.live
    mine = live is not None and live is app._offer and live.is_live
    want = gate(app)
    if want is None:
        if mine:
            bus.withdraw(live.id)
        app._offer = None
        return
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
                         render=OFFER_RENDER)
    app._offer_key = key


def take_over(app) -> None:
    """The DM is about to act from the panel during a player's turn (D-M5-7).

    The live offer is cancelled as the DM before `perform` runs. The bus observer then
    logs the take-over, and the player's late submit for that offer gets `not_live`.
    """
    live = app.prompts.live
    if live is not None and live is app._offer and live.is_live:
        app.prompts.cancel(live.id, DM_PRINCIPAL_ID)
