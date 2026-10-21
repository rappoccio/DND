"""Agent and cell picks from the browser (MULTIPLAYER_PLAN.md D-M5-3, slice M5d).

An action that needs a creature or a place arms a `pending_*` flag, and the DM's next map
click resolves it through `App.resolve_pick`. Those flags stay the state. When one is armed
for a token a player controls, `offer.ensure` posts this module's prompt as its projection:

  · `kind:"target"` when a creature is wanted and `kind:"cell"` for a place, both with
    `expects:"cell"`, owned by the controller, with the offer as parent (M5d Step 0.5);
  · `cells` is every cell the viewer may hear about: the explored mask with fog up, the
    grid with fog down (Step 0.2). It does not depend on where anyone stands, so it cannot
    leak a hidden creature, and a guess at one stays possible: the engine's perception
    rules decide what the guess finds, exactly as for the DM's click;
  · a submitted cell runs `App.resolve_pick`, the DM's click, so the two cannot disagree.
    When no branch takes the cell (an empty square for a creature pick), the arm stays
    armed and the prompt is posted again on the next frame;
  · a cancel runs the arm's own cancel, which is also what Esc runs on the DM console.
    A cancel by the DM is a take-over (Step 0.6): it leaves the pick armed, so the DM's
    click that caused it resolves the pick instead;
  · an area spell is aimed, then confirmed (M5e E-8). The DM sees the template follow the
    mouse, but a client never says where it is hovering, so a tap only aims: it is held
    in `app._aoe_aim`, and the same slot then posts a `kind:"confirm"` choice (Cast here /
    Re-aim) whose `aoe` is the template, cut to the cells above. Cast here runs
    `resolve_pick` on the held cell. The DM console never aims: its click still resolves.

`ARMS` lists every arm the click chain knows, in the chain's order, so that the arm this
module projects is the arm a click would resolve. `tests/test_picks.py` holds the order to
`resolve_pick`. Only arms in `WIRED` are projected; while any other arm is armed, the offer
is held back exactly as it was in M5b, and the DM resolves the pick on the map.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import rpg_battle_map as rpg

from net import move as net_move
from net.roster import DM_PRINCIPAL_ID
from prompts import Option

TARGET, CELL = "target", "cell"
PICK_RENDER = "remote"
DONE_ID = "done"
CONFIRM = "confirm"
CAST_ID, REAIM_ID = "cast", "reaim"
NOT_TAKEN = "Nothing there to pick. Choose again, or cancel."


# ─────────────────────────────────────────────────────────────────────────────
#  Cancels. Each restores what its arm changed and nothing else (M5d Step 0).
# ─────────────────────────────────────────────────────────────────────────────

def _say(app, line: str) -> None:
    app._combat_log_add(line)
    app._flush_combat_log()


def _flag(attr: str, idle, label: str, *companions: tuple[str, object]):
    """The plain cancel: the flag and its companions back to idle, and a log line."""
    def cancel(app) -> None:
        setattr(app, attr, idle)
        for name, value in companions:
            setattr(app, name, value)
        _say(app, f"{label} cancelled.")
    return cancel


def cancel_duplicity(app) -> None:
    """Invoke / Move / Swap Duplicity. Channel Divinity is spent on the first placement, not
    on arming, so a cancel before it costs nothing and one after it ends the placements."""
    app.pending_invoke_duplicity    = False
    app.pending_duplicity_remaining = 0
    app._duplicity_cd_pending       = False
    app.pending_move_duplicity      = False
    app.move_duplicity_idx          = -1
    app.pending_swap_duplicity      = False
    app._combat_log_add("Invoke Duplicity cancelled.")


def cancel_clairvoyant(app) -> None:
    app.pending_clairvoyant = False
    app._combat_log_add("Clairvoyant Combatant cancelled.")


def cancel_vow_of_enmity(app) -> None:
    app.pending_vow_of_enmity = False
    app._combat_log_add("Vow of Enmity cancelled.")


def cancel_inspiring_smite(app) -> None:
    app.pending_inspiring_smite = False
    app._combat_log_add("Inspiring Smite cancelled.")


def cancel_sweep(app) -> None:
    """The die is spent when the sweep resolves, so nothing is refunded. The attack
    sequence the sweep interrupted continues, as it does after a refused pick."""
    info = app.pending_sweep
    app.pending_sweep = None
    _say(app, "Sweeping Attack declined.")
    if info:
        app._continue_attack_sequence_after_rider(info["attacker"])


def cancel_attack(app) -> None:
    """Disarm a weapon attack, and undo what arming it did.

    `perform` snapshots the attack-sequence fields before an action runs, and a resolved
    pick drops the snapshot. So while it is still held, no swing has happened since the
    arm, and putting the fields back is exact: a fresh Attack leaves no seeded count
    behind, and a resumed one keeps its count. Hew's flag, cleared when Hew arms, comes back
    with them. A punch that was armed swaps its weapon back."""
    app.pending_attack_slot = ""
    snap = app._attack_arm_snapshot
    app._attack_arm_snapshot = None
    if snap is not None:
        (actor, app.attacks_remaining, app._attack_sequence_slot, app.pending_attack_offhand,
         app.pending_attack_resource, app.pending_weapon_idx, hew) = snap
        if hew and 0 <= actor < len(app.bm.placed_agents):
            cond = app.combat.get_agent_conditions(app.bm, actor)
            if not cond.gwm_hew_available:
                cond.gwm_hew_available = True
                app.combat.set_agent_conditions(app.bm, actor, cond)
    if app._unarmed_strike_original_weapons:
        idx, weapons = app._unarmed_strike_original_weapons
        app.combat.set_agent_weapons(app.bm, idx, weapons)
        app._unarmed_strike_original_weapons = None
    _say(app, "Attack cancelled.")
    app._update_attack_overlay()


def cancel_vitality(app) -> None:
    """The window is parked until the pick submits, so a cancel must submit its Skip, or
    the engine waits forever (M5d Step 0)."""
    app.pending_vitality_target = False
    app._vitality_option_index  = -1
    _say(app, "Vitality of the Tree not used.")
    app._submit_reaction_skip()


def cancel_summon(app) -> None:
    """Nothing is spent until the creature is placed, so a cancel only disarms. It is also
    what a cancelled form menu runs: the summon is armed before its form is chosen."""
    app.pending_summon_slot       = ""
    app.pending_summon_idx        = 0
    app.pending_summon_slot_level = 0
    app.pending_summon_monster    = ""
    app.pending_summon_spirit     = None
    app.pending_summon_free_cast  = False
    app.summon_hover_cell         = None
    app._combat_log_add("Summon cancelled.")


def cancel_spell(app) -> None:
    """The spell's Esc body, lifted (M5e E-2). On a wall with an anchor it clears the anchor
    and keeps the arm, so the next pick is the start point again. Otherwise it disarms.
    Nothing is refunded: a normal cast spends at resolution, and the four casts that spend
    before the pick (F-M5e-2) lose it, as Esc always has."""
    app._aoe_aim = None
    if app._pending_spell_is_wall() and app.spell_anchor_cell is not None:
        app.spell_anchor_cell = None
        app._combat_log_add("Wall anchor cleared — click a new start point.")
        return
    app.pending_spell_slot   = ""
    app.pending_spell_is_aoe = False
    app.spell_anchor_cell    = None
    app.spell_hover_cell     = None
    app._combat_log_add("Spell cast cancelled.")


def cancel_jump(app) -> None:
    app.jump_overlay_active = False
    app.jump_reachable_cells = []
    _say(app, "Long Jump cancelled.")


# ─────────────────────────────────────────────────────────────────────────────
#  The arms
# ─────────────────────────────────────────────────────────────────────────────

def _current(app) -> int:
    return app._current_agent_idx()


def _key(field: str, key: str) -> Callable:
    return lambda app: (getattr(app, field) or {}).get(key, -1)


def _reactor(app) -> int:
    pd = app.combat.pending_decision()
    return pd.ctx.reactor_idx if pd.active else -1


@dataclass(frozen=True)
class Arm:
    """One arm of the click chain.

    `name` is the attribute the chain tests first, `idle` the value it rests at. `title`
    is a function so a multi-pick can count. `kind` is a string, or a function of the app
    where one arm takes more than one shape (the spell arm, M5e E-1); read it through
    `kind_for`. `in_window` is the one arm armed inside a
    parked reaction window, which the offer's gate would otherwise wait out forever.
    `cells` and `resolve` are set only by the long jump, which is not in the chain: it
    has its own landing set and its own click handler."""
    name: str
    idle: object
    kind: str | Callable[[object], str]
    title: Callable[[object], str]
    cancel: Callable[[object], None] | None
    actor: Callable[[object], int] = _current
    in_window: bool = False
    done: Callable[[object], bool] | None = None      # when a "done" option is offered
    finish: Callable[[object], None] | None = None    # what "done" runs
    cells: Callable[[object, int], list] | None = None
    resolve: Callable[[object, int, object], bool] | None = None

    def armed(self, app) -> bool:
        return getattr(app, self.name, self.idle) != self.idle

    def kind_for(self, app) -> str:
        return self.kind(app) if callable(self.kind) else self.kind


def _t(text: str) -> Callable[[object], str]:
    return lambda app: text


def _attack_title(app) -> str:
    rem = app.attacks_remaining
    return f"Attack: choose a target ({rem} left)" if rem > 0 else "Attack: choose a target"


def _mantle_title(app) -> str:
    return f"Mantle of Inspiration: choose recipients ({len(app.pending_mantle_targets)} chosen)"


def _jump_cells(app, actor: int) -> list:
    return net_move.explored_footprints(
        app, actor, [(c.col, c.row) for c in app.jump_reachable_cells])


def _jump(app, actor: int, cell) -> bool:
    if not any(c.col == cell.col and c.row == cell.row for c in app.jump_reachable_cells):
        return False
    app._execute_jump(actor, cell)
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  The spell arm: one flag, nine shapes (F-M5e-1)
# ─────────────────────────────────────────────────────────────────────────────

SINGLE, MULTI, AREA, WALL, CORPSE, BINDING, DOOR, DISPEL, TELEPORT = (
    "single", "multi", "area", "wall", "corpse", "binding", "door", "dispel", "teleport")

# Each shape's prompt kind. Dispel takes a creature or a spot; the chain accepts either,
# and the picker that follows is a bus prompt (E-1).
SHAPE_KIND = {SINGLE: TARGET, MULTI: TARGET, BINDING: TARGET, DISPEL: TARGET,
              AREA: CELL, WALL: CELL, CORPSE: CELL, DOOR: CELL, TELEPORT: CELL}


def _multi_target(app, sp) -> bool:
    """`_resolve_spell_cast`'s own test for a cast that collects several clicks."""
    return (sp.geometry == rpg.SpellGeometry.Multiple
            or app._twinned_single_armed(sp, app._current_agent_idx()))


def spell_shape(app) -> str:
    """The shape the armed spell takes, tested in `resolve_pick`'s spell-branch order, so
    the prompt names what the click will actually do."""
    if app._pending_spell_targets_corpse():
        return CORPSE
    if app._pending_spell_binds_creature():
        return BINDING
    if app._pending_spell_opens_doors():
        return DOOR
    if app._pending_spell_dispels_magic():
        return DISPEL
    sp = app._pending_spell()
    if app.pending_spell_is_aoe:
        if app._pending_spell_is_wall():
            return WALL
        if sp is not None and getattr(sp, "teleportation_spell", False):
            return TELEPORT
        return AREA
    if sp is not None and _multi_target(app, sp):
        return MULTI
    return SINGLE


def _spell_kind(app) -> str:
    return SHAPE_KIND[spell_shape(app)]


def _spell_title(app) -> str:
    sp = app._pending_spell()
    name = sp.name if sp is not None else "Spell"
    shape = spell_shape(app)
    if shape == MULTI:
        n = app.pending_spell_num_targets
        k = len(app.pending_spell_targets) + 1
        return f"{name}: choose a target ({k} of {n})" if n > 0 else f"{name}: choose a target"
    if shape == WALL:
        step = "start" if app.spell_anchor_cell is None else "end"
        return f"{name}: choose the {step} point"
    if shape == AREA:
        centred = sp is not None and sp.geometry in (rpg.SpellGeometry.Sphere,
                                                     rpg.SpellGeometry.Square)
        return f"{name}: choose the center" if centred else f"{name}: choose where to aim"
    return f"{name}: " + {
        SINGLE: "choose a target",
        CORPSE: "choose a body",
        BINDING: "choose a creature to bind",
        DOOR: "choose a door",
        DISPEL: "choose a creature or a spot",
        TELEPORT: "choose a destination",
    }[shape]


def _chromatic_title(app) -> str:
    return f"Chromatic Orb: choose the next leap ({len(app.pending_chromatic_chain)} chosen)"


def _summon_title(app) -> str:
    what = app.pending_summon_monster or "the creature"
    return f"Summon: choose where to place {what}"


ARMS: tuple[Arm, ...] = (
    Arm("arcane_charge_pending", False, CELL, _t("Arcane Charge: choose where to teleport"),
        _flag("arcane_charge_pending", False, "Arcane Charge")),
    Arm("blink_steps_pending", False, CELL, _t("Blink Steps: choose where to teleport"),
        _flag("blink_steps_pending", False, "Blink Steps")),
    Arm("pending_psychic_teleport", False, CELL, _t("Psychic Teleportation: choose a destination"),
        _flag("pending_psychic_teleport", False, "Psychic Teleportation")),
    Arm("pending_shadow_step", False, CELL, _t("Shadow Step: choose a destination"),
        _flag("pending_shadow_step", False, "Shadow Step")),
    Arm("pending_steps_of_fey", False, CELL, _t("Steps of the Fey: choose a destination"),
        _flag("pending_steps_of_fey", False, "Steps of the Fey")),
    Arm("pending_misty_escape", False, CELL, _t("Misty Escape: choose a destination"),
        _flag("pending_misty_escape", False, "Misty Escape")),
    Arm("pending_bewitching_misty", False, CELL, _t("Bewitching Magic: choose a destination"),
        lambda app: app._decline_bewitching_offer()),
    Arm("pending_wild_magic_teleport", False, CELL, _t("Wild Magic: choose where to teleport"),
        _flag("pending_wild_magic_teleport", False, "Wild Magic Teleport")),
    Arm("pending_warping_implosion", False, CELL, _t("Warping Implosion: choose a destination"),
        _flag("pending_warping_implosion", False, "Warping Implosion")),
    Arm("pending_shadow_darkness", False, CELL, _t("Shadow Arts: choose the Darkness's center"),
        _flag("pending_shadow_darkness", False, "Shadow Arts: Darkness")),
    Arm("pending_elemental_burst", -1, CELL, _t("Elemental Burst: choose the center"),
        _flag("pending_elemental_burst", -1, "Elemental Burst")),
    Arm("pending_invoke_duplicity", False, CELL, _t("Invoke Duplicity: place the duplicate"),
        cancel_duplicity,
        done=lambda app: not app._duplicity_cd_pending, finish=cancel_duplicity),
    Arm("pending_move_duplicity", False, CELL,
        lambda app: ("Move Duplicity: choose the destination" if app.move_duplicity_idx >= 0
                     else "Move Duplicity: choose a duplicate"), cancel_duplicity),
    Arm("pending_swap_duplicity", False, TARGET, _t("Swap Duplicity: choose a duplicate"),
        cancel_duplicity),
    Arm("pending_cleave", None, TARGET, _t("Cleave: choose a second creature"),
        lambda app: app._cancel_cleave(), actor=_key("pending_cleave", "attacker")),
    Arm("pending_sweep", None, TARGET, _t("Sweeping Attack: choose a second creature"),
        cancel_sweep, actor=_key("pending_sweep", "attacker")),
    Arm("pending_rally", None, TARGET, _t("Rally: choose a creature"),
        _flag("pending_rally", None, "Rally"),
        actor=lambda app: -1 if app.pending_rally is None else app.pending_rally),
    Arm("pending_feint", None, TARGET, _t("Feinting Attack: choose a creature"),
        _flag("pending_feint", None, "Feinting Attack"),
        actor=lambda app: -1 if app.pending_feint is None else app.pending_feint),
    Arm("pending_mantle_active", False, TARGET, _mantle_title,
        lambda app: app._cancel_mantle(),
        done=lambda app: True, finish=lambda app: app._finalize_mantle()),
    Arm("pending_beguiling", False, TARGET, _t("Beguiling Magic: choose a creature"),
        lambda app: app._cancel_beguiling(), actor=lambda app: app.pending_beguiling_bard),
    Arm("pending_clairvoyant", False, TARGET, _t("Clairvoyant Combatant: choose an enemy"),
        cancel_clairvoyant),
    Arm("pending_vow_of_enmity", False, TARGET, _t("Vow of Enmity: choose an enemy"),
        cancel_vow_of_enmity),
    Arm("pending_inspiring_smite", False, TARGET, _t("Inspiring Smite: choose a creature"),
        cancel_inspiring_smite),
    Arm("_legendary_target_pick", False, TARGET, _t("Legendary action: choose a target"),
        None, actor=lambda app: app._legendary_actor),
    Arm("pending_attack_slot", "", TARGET, _attack_title, cancel_attack),
    Arm("pending_summon_slot", "", CELL, _summon_title, cancel_summon),
    Arm("pending_chromatic_active", False, TARGET, _chromatic_title,
        lambda app: app._cancel_chromatic_chain(),
        done=lambda app: True, finish=lambda app: app._finalize_chromatic_cast()),
    Arm("pending_spell_slot", "", _spell_kind, _spell_title, cancel_spell),
    Arm("pending_shove_slot", "", TARGET, _t("Shove: choose a creature"),
        _flag("pending_shove_slot", "", "Shove", ("pending_shove_type", ""))),
    Arm("pending_unarmed_type", "", TARGET, _t("Unarmed Strike: choose a creature"),
        _flag("pending_unarmed_type", "", "Unarmed Strike")),
    Arm("pending_heal_light", False, TARGET, _t("Healing Light: choose a creature"),
        _flag("pending_heal_light", False, "Healing Light")),
    Arm("pending_lay_on_hands", False, TARGET, _t("Lay on Hands: choose a creature"),
        _flag("pending_lay_on_hands", False, "Lay on Hands")),
    Arm("pending_bastion_of_law", False, TARGET, _t("Bastion of Law: choose a creature"),
        _flag("pending_bastion_of_law", False, "Bastion of Law", ("pending_bastion_sp", 0))),
    Arm("pending_hand_of_healing", False, TARGET, _t("Hand of Healing: choose a creature"),
        _flag("pending_hand_of_healing", False, "Hand of Healing")),
    Arm("pending_use_item", -1, TARGET, _t("Use Item: choose a creature"),
        _flag("pending_use_item", -1, "Use Item")),
    Arm("pending_escape_net", False, TARGET, _t("Free from Net: choose the netted creature"),
        _flag("pending_escape_net", False, "Free from Net")),
    Arm("pending_grant_inspiration", False, TARGET, _t("Bardic Inspiration: choose an ally"),
        _flag("pending_grant_inspiration", False, "Bardic Inspiration")),
    Arm("pending_telekinetic", False, TARGET, _t("Telekinetic Movement: choose a creature"),
        _flag("pending_telekinetic", False, "Telekinetic Movement")),
    Arm("pending_flurry_target", False, TARGET, _t("Flurry of Blows: choose a target"),
        _flag("pending_flurry_target", False, "Flurry of Blows",
              ("pending_flurry_atk_idx", -1), ("pending_flurry_rider_option", -1)),
        actor=lambda app: app.pending_flurry_atk_idx),
    Arm("pending_vitality_target", False, TARGET,
        _t("Vitality of the Tree: choose a creature within 10 ft"), cancel_vitality,
        actor=_reactor, in_window=True),
    # Not in the chain: the jump has its own landing set and its own click handler.
    Arm("jump_overlay_active", False, CELL, _t("Long Jump: choose where to land"), cancel_jump,
        cells=_jump_cells, resolve=_jump),
)

BY_NAME = {a.name: a for a in ARMS}

# Projected to the player. The rest hold the offer back, as in M5b, and the DM resolves
# them on the map. `_legendary_target_pick` is NPC-only.
WIRED = frozenset({
    # M5d.1 — weapon attacks and the picks that follow them
    "pending_attack_slot", "pending_cleave", "pending_sweep", "pending_rally",
    "pending_feint", "pending_shove_slot", "pending_unarmed_type", "pending_flurry_target",
    # M5d.2 — single-creature picks
    "pending_heal_light", "pending_lay_on_hands", "pending_bastion_of_law",
    "pending_hand_of_healing", "pending_use_item", "pending_escape_net",
    "pending_grant_inspiration", "pending_telekinetic", "pending_clairvoyant",
    "pending_vow_of_enmity", "pending_inspiring_smite", "pending_vitality_target",
    # M5d.3 — place picks
    "arcane_charge_pending", "blink_steps_pending", "pending_psychic_teleport",
    "pending_shadow_step", "pending_steps_of_fey", "pending_misty_escape",
    "pending_wild_magic_teleport", "pending_warping_implosion", "pending_shadow_darkness",
    "pending_elemental_burst", "jump_overlay_active",
    # M5d.4 — multi-picks
    "pending_mantle_active", "pending_invoke_duplicity", "pending_move_duplicity",
    "pending_swap_duplicity",
    # M5e.1 — the spell pipeline, and the two riders a player's own spell can arm
    "pending_spell_slot", "pending_chromatic_active", "pending_summon_slot",
    "pending_beguiling", "pending_bewitching_misty",
})


# ─────────────────────────────────────────────────────────────────────────────
#  What is armed, and for whom
# ─────────────────────────────────────────────────────────────────────────────

def armed(app) -> Arm | None:
    """The arm a click would resolve now: the first armed one, in the chain's order."""
    return next((a for a in ARMS if a.armed(app)), None)


def wanted(app) -> tuple[Arm, int, str] | None:
    """`(arm, actor, owner)` when a player's target prompt should be up, else None."""
    if not app.combat_active or app.combat_paused:
        return None
    if app._npc_anim_defers() or app._npc_drive_idx >= 0:
        return None
    arm = armed(app)
    if arm is None or arm.name not in WIRED:
        return None
    if app.combat.pending_decision().active and not arm.in_window:
        return None
    actor = arm.actor(app)
    if not 0 <= actor < len(app.bm.placed_agents):
        return None
    owner = app.roster.controller_of(actor)
    if owner == DM_PRINCIPAL_ID:
        return None
    return arm, actor, owner


def cells(app, arm: Arm, actor: int) -> list[tuple[int, int]]:
    """M5d Step 0.2: what the viewer may hear about, or the jump's own landing set."""
    if arm.cells is not None:
        return arm.cells(app, actor)
    if app._fog_active():
        return sorted((c.col, c.row) for c in app.bm.explored_cells())
    return [(c, r) for r in range(app.bm.grid_rows) for c in range(app.bm.grid_cols)]


def projection(app, arm: Arm, actor: int, owner: str) -> tuple:
    """What the prompt shows. `ensure` re-posts when this changes, and not otherwise."""
    done = arm.done is not None and arm.done(app)
    return (arm.name, actor, owner, arm.kind_for(app), arm.title(app), done,
            tuple(cells(app, arm, actor)), aim(app, arm))


def post(app, arm: Arm, actor: int, owner: str, parent):
    """Post the target prompt for `arm`, or its confirm while an aim is held, and remember
    it as the live pick prompt."""
    center = aim(app, arm)
    if center is not None:
        return _post_confirm(app, arm, actor, owner, parent, center)
    holder: dict = {}

    def _answer(response):
        col, row = response.cell
        if aiming(app, arm):
            app._aoe_aim = (col, row)    # the next frame posts the confirm
            return
        cell = rpg.Cell(col, row)
        taken = (arm.resolve(app, actor, cell) if arm.resolve is not None
                 else app.resolve_pick(cell))
        if not taken:
            _say(app, NOT_TAKEN)

    def _cancel():
        # A cancel by the DM is a take-over: the pick stays armed for the DM's own click.
        if holder["p"].resolved_by != DM_PRINCIPAL_ID and arm.armed(app):
            arm.cancel(app)

    options = []
    if arm.done is not None and arm.done(app):
        options.append(Option(DONE_ID, "Done", on_choose=lambda: arm.finish(app)))
    prompt = app.prompts.ask(actor, owner, arm.kind_for(app), arm.title(app), options,
                             expects="cell", parent=parent, render=PICK_RENDER,
                             cells=cells(app, arm, actor), on_answer=_answer,
                             on_cancel=_cancel)
    holder["p"] = prompt
    app._pick_prompt = prompt
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
#  Aim, then confirm (M5e E-8)
# ─────────────────────────────────────────────────────────────────────────────

def aiming(app, arm: Arm) -> bool:
    """True when a tap on this arm aims rather than resolves: the spell arm, in its area
    shape. A wall, a teleport and a door resolve on the tap, as before."""
    return arm.name == "pending_spell_slot" and spell_shape(app) == AREA


def aim(app, arm: Arm) -> tuple[int, int] | None:
    """The held aim for `arm`, or None. An aim left over from another shape is not one."""
    return app._aoe_aim if aiming(app, arm) else None


def template(app, arm: Arm, actor: int, center: tuple[int, int]) -> list[tuple[int, int]]:
    """The cells the spell would cover from `center`, as the hover preview draws them, cut
    to what the viewer may hear about (`cells`), so the overlay outlines nothing in fog."""
    sp = app._pending_spell()
    if sp is None:
        return []
    shown = set(cells(app, arm, actor))
    return sorted(p for p in ((c.col, c.row) for c in
                              app._area_template(actor, sp, rpg.Cell(*center)))
                  if p in shown)


def _post_confirm(app, arm: Arm, actor: int, owner: str, parent, center):
    holder: dict = {}

    def _cast():
        app._aoe_aim = None
        if arm.armed(app) and not app.resolve_pick(rpg.Cell(*center)):
            _say(app, NOT_TAKEN)

    def _reaim():
        app._aoe_aim = None

    def _cancel():
        # As for the pick: a cancel by the DM is a take-over, and leaves the spell armed.
        app._aoe_aim = None
        if holder["p"].resolved_by != DM_PRINCIPAL_ID and arm.armed(app):
            arm.cancel(app)

    sp = app._pending_spell()
    name = sp.name if sp is not None else "Spell"
    options = [Option(CAST_ID, "Cast here", on_choose=_cast),
               Option(REAIM_ID, "Re-aim", on_choose=_reaim)]
    prompt = app.prompts.ask(actor, owner, CONFIRM, f"{name}: cast here?", options,
                             parent=parent, render=PICK_RENDER,
                             aoe=template(app, arm, actor, center), on_cancel=_cancel)
    holder["p"] = prompt
    app._pick_prompt = prompt
    return prompt


def is_pick_prompt(app, prompt) -> bool:
    return prompt is not None and prompt is getattr(app, "_pick_prompt", None)


def cancel(app) -> bool:
    """Esc on the DM console: run the armed arm's cancel, the same one a remote cancel runs.
    False when nothing cancellable is armed, so the key falls through as it did before."""
    arm = armed(app)
    if arm is None or arm.cancel is None:
        return False
    arm.cancel(app)
    return True
