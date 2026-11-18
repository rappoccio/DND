"""Agent and cell picks from the browser (MULTIPLAYER_PLAN.md D-M5-3, slice M5d).

An action that needs a creature or a place arms a pick (`app.pick`, pending.py) or a
base mode (`app.pending`: an attack, a spell, a summon, …), and the DM's next map click resolves it through `App.resolve_pick`.
Those stay the state. When one is armed
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

import pending

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


def _disarm(mode: type, label: str):
    """The plain cancel of a base mode (pending.py): disarm it, and a log line."""
    def cancel(app) -> None:
        app._disarm(mode)
        _say(app, f"{label} cancelled.")
    return cancel


def _drop(kind: str, label: str, *companions: tuple[str, object]):
    """The plain cancel of a click pick (pending.py): the pick and its companions back to
    idle, and a log line."""
    def cancel(app) -> None:
        app._drop_pick(kind)
        for name, value in companions:
            setattr(app, name, value)
        _say(app, f"{label} cancelled.")
    return cancel


def cancel_duplicity(app) -> None:
    """Invoke / Move / Swap Duplicity. Channel Divinity is spent on the first placement, not
    on arming, so a cancel before it costs nothing and one after it ends the placements."""
    app._drop_pick("invoke_duplicity")
    app.pending_duplicity_remaining = 0
    app._duplicity_cd_pending       = False
    app._drop_pick("move_duplicity")
    app.move_duplicity_idx          = -1
    app._drop_pick("swap_duplicity")
    app._combat_log_add("Invoke Duplicity cancelled.")


def cancel_clairvoyant(app) -> None:
    app._drop_pick("clairvoyant")
    app._combat_log_add("Clairvoyant Combatant cancelled.")


def cancel_vow_of_enmity(app) -> None:
    app._drop_pick("vow_of_enmity")
    app._combat_log_add("Vow of Enmity cancelled.")


def cancel_path_to_the_grave(app) -> None:
    app._drop_pick("path_to_the_grave")
    app._combat_log_add("Path to the Grave cancelled.")


def cancel_move_hunters_mark(app) -> None:
    app._drop_pick("move_hunters_mark")
    app._combat_log_add("Move Hunter's Mark cancelled.")


def cancel_inspiring_smite(app) -> None:
    app._drop_pick("inspiring_smite")
    app._combat_log_add("Inspiring Smite cancelled.")


def cancel_sweep(app) -> None:
    """The die is spent when the sweep resolves, so nothing is refunded. The attack
    sequence the sweep interrupted continues, as it does after a refused pick."""
    info = app._pick_data("sweep")
    app._drop_pick("sweep")
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
    app._disarm(pending.Attack)
    app.pending_horde_breaker_targets = []
    app.pending_sudden_strike_targets = []
    ranger = app._current_agent_idx()
    if (app.pending_beasts_strike_targets and app._beasts_strike_paid_now
            and app._attack_arm_snapshot is not None and ranger >= 0):
        # The attack this arm paid comes back with the snapshot below, so the strikes it bought go.
        cond = app.combat.get_agent_conditions(app.bm, ranger)
        cond.beast_strikes_left = 0
        app.combat.set_agent_conditions(app.bm, ranger, cond)
    app.pending_beasts_strike_targets = []
    app._beasts_strike_paid_now = False
    snap = app._attack_arm_snapshot
    app._attack_arm_snapshot = None
    if snap is not None:
        (actor, app.attack_seq.remaining, app.attack_seq.slot, app.attack_seq.offhand,
         app.attack_seq.resource, app.attack_seq.weapon_idx, hew) = snap
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
    app._drop_pick("vitality_target")
    app._vitality_option_index  = -1
    _say(app, "Vitality of the Tree not used.")
    app._submit_reaction_skip()


def cancel_shadowy_dodge(app) -> None:
    """Shadowy Dodge's cell pick sits inside a parked AfterAttack window: a cancel stays put by
    submitting the window's Skip, as Vitality's does."""
    app._drop_pick("shadowy_dodge_cell")
    app._shadowy_dodge_option_index = -1
    _say(app, "Shadowy Dodge: staying put.")
    app._submit_reaction_skip()


def cancel_summon(app) -> None:
    """Nothing is spent until the creature is placed, so a cancel only disarms. It is also
    what a cancelled form menu runs: the summon is armed before its form is chosen."""
    app._disarm(pending.Summon)
    app.cast_setup.fey_reinforcements = False
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
    app._disarm(pending.Spell)
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


# `Arm.idle` for an arm that is a click pick (pending.py) rather than an attribute.
PICK = object()


def _key(kind: str, key: str) -> Callable:
    return lambda app: (app._pick_data(kind) or {}).get(key, -1)


def _reactor(app) -> int:
    pd = app.combat.pending_decision()
    return pd.ctx.reactor_idx if pd.active else -1


@dataclass(frozen=True)
class Arm:
    """One arm of the click chain.

    `name` is what the chain tests first: a click pick's kind (`app.pick`, pending.py) when
    `idle` is `PICK`; a base mode (`app.pending`) when `idle` is its class (pending.Attack,
    …); else an attribute of the app and `idle` the value it rests at. `title`
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
        if self.idle is PICK:
            return app._picking(self.name)
        if isinstance(self.idle, type):
            return app._armed(self.idle) is not None
        return getattr(app, self.name, self.idle) != self.idle

    def kind_for(self, app) -> str:
        return self.kind(app) if callable(self.kind) else self.kind


def _t(text: str) -> Callable[[object], str]:
    return lambda app: text


def _attack_title(app) -> str:
    rem = app.attack_seq.remaining
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
    if app.pending.is_aoe:
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
        n = app.pending.num_targets
        k = len(app.pending.targets) + 1
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
    what = app.pending.monster or "the creature"
    return f"Summon: choose where to place {what}"


ARMS: tuple[Arm, ...] = (
    Arm("arcane_charge", PICK, CELL, _t("Arcane Charge: choose where to teleport"),
        _drop("arcane_charge", "Arcane Charge")),
    Arm("shadowy_dodge_cell", PICK, CELL,
        _t("Shadowy Dodge: choose where to teleport (30 ft)"), cancel_shadowy_dodge,
        actor=_reactor, in_window=True),
    Arm("blink_steps", PICK, CELL, _t("Blink Steps: choose where to teleport"),
        _drop("blink_steps", "Blink Steps")),
    Arm("psychic_teleport", PICK, CELL, _t("Psychic Teleportation: choose a destination"),
        _drop("psychic_teleport", "Psychic Teleportation")),
    Arm("shadow_step", PICK, CELL, _t("Shadow Step: choose a destination"),
        _drop("shadow_step", "Shadow Step")),
    Arm("misty_wanderer", PICK, CELL, _t("Misty Wanderer: choose a destination"),
        _drop("misty_wanderer", "Misty Wanderer")),
    Arm("steps_of_fey", PICK, CELL, _t("Steps of the Fey: choose a destination"),
        _drop("steps_of_fey", "Steps of the Fey")),
    Arm("misty_escape", PICK, CELL, _t("Misty Escape: choose a destination"),
        _drop("misty_escape", "Misty Escape")),
    Arm("bewitching_misty", PICK, CELL, _t("Bewitching Magic: choose a destination"),
        lambda app: app._decline_bewitching_offer()),
    Arm("wild_magic_teleport", PICK, CELL, _t("Wild Magic: choose where to teleport"),
        _drop("wild_magic_teleport", "Wild Magic Teleport")),
    Arm("warping_implosion", PICK, CELL, _t("Warping Implosion: choose a destination"),
        _drop("warping_implosion", "Warping Implosion")),
    Arm("shadow_darkness", PICK, CELL, _t("Shadow Arts: choose the Darkness's center"),
        _drop("shadow_darkness", "Shadow Arts: Darkness")),
    Arm("elemental_burst", PICK, CELL, _t("Elemental Burst: choose the center"),
        _drop("elemental_burst", "Elemental Burst")),
    Arm("invoke_duplicity", PICK, CELL, _t("Invoke Duplicity: place the duplicate"),
        cancel_duplicity,
        done=lambda app: not app._duplicity_cd_pending, finish=cancel_duplicity),
    Arm("move_duplicity", PICK, CELL,
        lambda app: ("Move Duplicity: choose the destination" if app.move_duplicity_idx >= 0
                     else "Move Duplicity: choose a duplicate"), cancel_duplicity),
    Arm("swap_duplicity", PICK, TARGET, _t("Swap Duplicity: choose a duplicate"),
        cancel_duplicity),
    Arm("cleave", PICK, TARGET, _t("Cleave: choose a second creature"),
        lambda app: app._cancel_cleave(), actor=_key("cleave", "attacker")),
    Arm("sweep", PICK, TARGET, _t("Sweeping Attack: choose a second creature"),
        cancel_sweep, actor=_key("sweep", "attacker")),
    Arm("rally", PICK, TARGET, _t("Rally: choose a creature"),
        _drop("rally", "Rally"),
        actor=lambda app: -1 if app._pick_data("rally") is None else app._pick_data("rally")),
    Arm("feint", PICK, TARGET, _t("Feinting Attack: choose a creature"),
        _drop("feint", "Feinting Attack"),
        actor=lambda app: -1 if app._pick_data("feint") is None else app._pick_data("feint")),
    Arm("mantle", PICK, TARGET, _mantle_title,
        lambda app: app._cancel_mantle(),
        done=lambda app: True, finish=lambda app: app._finalize_mantle()),
    Arm("beguiling", PICK, TARGET, _t("Beguiling Magic: choose a creature"),
        lambda app: app._cancel_beguiling(), actor=lambda app: app.pending_beguiling_bard),
    Arm("clairvoyant", PICK, TARGET, _t("Clairvoyant Combatant: choose an enemy"),
        cancel_clairvoyant),
    Arm("vow_of_enmity", PICK, TARGET, _t("Vow of Enmity: choose an enemy"),
        cancel_vow_of_enmity),
    Arm("path_to_the_grave", PICK, TARGET, _t("Path to the Grave: choose a creature"),
        cancel_path_to_the_grave),
    Arm("move_hunters_mark", PICK, TARGET, _t("Move Hunter's Mark: choose a creature"),
        cancel_move_hunters_mark),
    Arm("inspiring_smite", PICK, TARGET, _t("Inspiring Smite: choose a creature"),
        cancel_inspiring_smite),
    Arm("legendary_target", PICK, TARGET, _t("Legendary action: choose a target"),
        None, actor=lambda app: app._legendary_actor),
    Arm("legendary_spell", PICK,
        lambda app: TARGET if app._pick_data("legendary_spell") == "creature" else CELL,
        lambda app: f"Legendary {app._legendary_spell_label}: "
                    + ("choose a target" if app._pick_data("legendary_spell") == "creature"
                       else "choose a cell"),
        None, actor=lambda app: app._legendary_actor),
    Arm("lair", PICK,
        lambda app: CELL if app._pick_data("lair") == "doors" else TARGET,
        lambda app: {"doors": "Lair Doors: choose doors",
                     "apparition": "Lair Apparition: choose a hostile creature",
                     "shadow": "Lair Shadow Theft: choose a creature"}.get(app._pick_data("lair"), "Lair"),
        None, actor=lambda app: app._lair_actor),
    Arm("attack", pending.Attack, TARGET, _attack_title, cancel_attack),
    Arm("summon", pending.Summon, CELL, _summon_title, cancel_summon),
    Arm("chromatic", PICK, TARGET, _chromatic_title,
        lambda app: app._cancel_chromatic_chain(),
        done=lambda app: True, finish=lambda app: app._finalize_chromatic_cast()),
    Arm("spell", pending.Spell, _spell_kind, _spell_title, cancel_spell,
        done=lambda app: spell_shape(app) == MULTI and app._multi_target_finishable(),
        finish=lambda app: app._finish_multi_target_spell()),
    Arm("shove", pending.Shove, TARGET, _t("Shove: choose a creature"),
        _disarm(pending.Shove, "Shove")),
    Arm("unarmed", pending.Unarmed, TARGET, _t("Unarmed Strike: choose a creature"),
        _disarm(pending.Unarmed, "Unarmed Strike")),
    Arm("heal_light", PICK, TARGET, _t("Healing Light: choose a creature"),
        _drop("heal_light", "Healing Light")),
    Arm("lay_on_hands", PICK, TARGET, _t("Lay on Hands: choose a creature"),
        _drop("lay_on_hands", "Lay on Hands")),
    Arm("bastion_of_law", PICK, TARGET, _t("Bastion of Law: choose a creature"),
        _drop("bastion_of_law", "Bastion of Law", ("pending_bastion_sp", 0))),
    Arm("hand_of_healing", PICK, TARGET, _t("Hand of Healing: choose a creature"),
        _drop("hand_of_healing", "Hand of Healing")),
    Arm("use_item", PICK, TARGET, _t("Use Item: choose a creature"),
        _drop("use_item", "Use Item")),
    Arm("escape_net", PICK, TARGET, _t("Free from Net: choose the netted creature"),
        _drop("escape_net", "Free from Net")),
    Arm("grant_inspiration", PICK, TARGET, _t("Bardic Inspiration: choose an ally"),
        _drop("grant_inspiration", "Bardic Inspiration")),
    Arm("telekinetic", PICK, TARGET, _t("Telekinetic Movement: choose a creature"),
        _drop("telekinetic", "Telekinetic Movement")),
    Arm("flurry_target", PICK, TARGET, _t("Flurry of Blows: choose a target"),
        _drop("flurry_target", "Flurry of Blows",
              ("pending_flurry_atk_idx", -1), ("pending_flurry_rider_option", -1)),
        actor=lambda app: app.pending_flurry_atk_idx),
    Arm("vitality_target", PICK, TARGET,
        _t("Vitality of the Tree: choose a creature within 10 ft"), cancel_vitality,
        actor=_reactor, in_window=True),
    # Not in the chain: the jump has its own landing set and its own click handler.
    Arm("jump_overlay_active", False, CELL, _t("Long Jump: choose where to land"), cancel_jump,
        cells=_jump_cells, resolve=_jump),
)

BY_NAME = {a.name: a for a in ARMS}

# Projected to the player. The rest hold the offer back, as in M5b, and the DM resolves
# them on the map. The `legendary_target`, `legendary_spell` and `lair` picks are NPC-only.
WIRED = frozenset({
    # M5d.1 — weapon attacks and the picks that follow them
    "attack", "cleave", "sweep", "rally",
    "feint", "shove", "unarmed", "flurry_target",
    # M5d.2 — single-creature picks
    "heal_light", "lay_on_hands", "bastion_of_law",
    "hand_of_healing", "use_item", "escape_net",
    "grant_inspiration", "telekinetic", "clairvoyant",
    "vow_of_enmity", "inspiring_smite", "vitality_target",
    "path_to_the_grave", "move_hunters_mark",
    # M5d.3 — place picks
    "arcane_charge", "blink_steps", "psychic_teleport",
    "shadow_step", "steps_of_fey", "misty_escape",
    "wild_magic_teleport", "warping_implosion", "shadow_darkness",
    "elemental_burst", "jump_overlay_active",
    # Ranger R2 — Shadowy Dodge's teleport, inside its parked AfterAttack window
    "shadowy_dodge_cell",
    # Ranger R3 — Misty Wanderer's destination (the passenger question is a bus prompt)
    "misty_wanderer",
    # M5d.4 — multi-picks
    "mantle", "invoke_duplicity", "move_duplicity",
    "swap_duplicity",
    # M5e.1 — the spell pipeline, and the two riders a player's own spell can arm
    "spell", "chromatic", "summon",
    "beguiling", "bewitching_misty",
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
    owner = app._prompt_owner(actor)
    if owner == DM_PRINCIPAL_ID:
        return None
    return arm, actor, owner


def cells(app, arm: Arm, actor: int) -> list[tuple[int, int]]:
    """M5d Step 0.2: what the viewer may hear about, or the jump's own landing set."""
    if arm.cells is not None:
        return arm.cells(app, actor)
    if app._party_fog_active():
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
    return arm.name == "spell" and spell_shape(app) == AREA


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
