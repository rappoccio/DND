"""The legal-action model: what this creature may do, as data.

Seam **S3** of ``plans/MULTIPLAYER_PLAN.md`` (phase M2). Today ``_draw_combat_panel``
fuses legality and layout — a button is legal exactly when the branch that positions it
runs — and it needs a stale-rect hack (every ``btn_cbt_*`` parked at ``x = -10000`` each
frame) to stop an undrawn button from capturing a click. ``ActionMenu.build`` is the
other half of that split: it answers *what is offered* with no pygame in the room, and
the panel is left holding only *where it goes*.

Two consequences, in the order they pay off:

  · the panel's availability rules become testable without a screen — and, unlike the
    rects, they are the half that encodes the rules;
  · M3's ``GameView`` can put a remote player's legal options on the wire without
    re-deriving them from a widget tree, which is the whole reason this seam exists.

**Scope, stated so a later phase does not have to guess.** This module is built group
by group, following the panel's existing visual sections (the M2a–M2e work order in the
plan). Only the groups listed in ``BUILT_GROUPS`` are here; every other ``btn_cbt_*``
is still drawn by the old fused code and is still protected by the stale-rect guard.
A caller must therefore treat a missing id as "not yet converted", never as "illegal".

**What this module deliberately does not do.** It does not import pygame, it holds no
state, and it never mutates ``app``. ``build`` is a pure read of the app + engine at the
instant it is called, cheap enough to run once per frame, and every field it returns is
JSON-primitive so that M3 can serialize it unchanged.

**Name collision, on purpose.** ``net.roster.Action`` is the *authorization verb* enum
("may this principal control a token"). This ``Action`` is a *game option* ("Dash is on
offer"). They are unrelated, and the plan names both; import one or the other, never
both unqualified.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# The engine, for the class/subclass enums §6 compares against. `actions.py` is allowed
# to read the engine — it is the *panel* half of the seam that must not leak in here.
import rpg_battle_map as rpg

# The panel's visual sections, as Step 0.3 numbered them. `group` is the projection a
# renderer batches by — the DM panel draws a section per group, and M4's client will
# too — so it is part of the model and not a comment.
GROUP_SESSION = "session"    # §1  DM tools: pause, end combat
GROUP_TURN    = "turn"       # §3  turn control: end turn
GROUP_ACTION  = "action"     # §4  the Action economy band          (M2b)
GROUP_PORTENT = "portent"    # §6  Portent dice                     (M2b)
GROUP_BONUS   = "bonus"      # §7  the Bonus Action mega-section    (M2c-e)
GROUP_UTILITY = "utility"    # §9  visibility + drops

# Which groups `build` actually populates today. See "Scope" above.
BUILT_GROUPS = (GROUP_SESSION, GROUP_TURN, GROUP_ACTION, GROUP_PORTENT, GROUP_BONUS,
                GROUP_UTILITY)

# `GROUP_BONUS` is in that tuple from M2c on, but §7 is the one group that is only
# PARTLY converted until M2e: M2c takes bucket 7a, M2d the clusters and the spatial
# predicates, M2e the economy-band headers and the metamagic dict. Until then the
# rule at the top holds with extra force for this group — a missing id means "still
# fused", never "illegal".

# Step 0.5's `expects` vocabulary, repeated rather than imported: `prompts.py` owns the
# wire and must not grow a dependency on the panel model. Keep the two in step.
EXPECTS = ("choice", "cell", "agent", "none")

# What clicking an option SPENDS. Step 0.3 sized bucket 7d as "the cases that prove
# `ActionMenu` needs an explicit `economy` field rather than a boolean", and §7 is the
# proof: the whole section is drawn under one `if not bonus_used:` band, and a handful
# of its members do not answer to the Bonus Action at all — a potion is a Bonus Action
# but the flask beside it in the same pack replaces an attack, Free from Net costs the
# Action, Drop Grapple costs nothing, and the metamagic toggles are not actions.
#
# This is a vocabulary, not a rules audit: an option is `bonus` unless the panel's own
# guard, or its own comment, says otherwise. See `_BONUS_ECONOMY`.
ECONOMY_NONE     = "none"      # not a turn action at all — a DM tool, or turn control
ECONOMY_FREE     = "free"      # costs no part of the economy
ECONOMY_BONUS    = "bonus"     # the Bonus Action
ECONOMY_ACTION   = "action"    # the Action
ECONOMY_ATTACK   = "attack"    # paid out of the Attack action's attacks, not the Action
ECONOMY_REACTION = "reaction"  # the Reaction
ECONOMY_VARIES   = "varies"    # depends which thing is picked — see `use_item`
ECONOMY = (ECONOMY_NONE, ECONOMY_FREE, ECONOMY_BONUS, ECONOMY_ACTION,
           ECONOMY_ATTACK, ECONOMY_REACTION, ECONOMY_VARIES)

# §7's economy: one entry per member whose cost is NOT the Bonus Action. Every other id
# `_bonus` builds is `bonus`, and this is the only place the exceptions are written
# down — the way `main.py`'s `_BON_RUN_*` tuples are the only place its rows are.
#
# The first group is the one the PANEL already distinguishes: it draws these outside
# the `not bonus_used` band on purpose, which is what bucket 7d is. The second group is
# inside that band and pays the Action as well — each has its own `not action_used`
# guard a few lines from its `Action(...)` — so the band hides an Action-cost feature
# whenever the Bonus Action is spent. That is the band-gate note in `_bonus`, recorded
# and preserved; `economy` is what a later item will fix it with.
_BONUS_ECONOMY = {
    # ── drawn outside the band (bucket 7d) ──
    "use_item":              ECONOMY_VARIES,   # per item: potion / flask / Net
    "extinguish":            ECONOMY_ACTION,
    "escape_net":            ECONOMY_ACTION,
    "grapple_drop":          ECONOMY_FREE,
    "bite_grappled":         ECONOMY_ATTACK,   # or a mid-multiattack slot
    "haste_action":          ECONOMY_ACTION,   # Haste's extra Action IS the option

    # ── inside the band, and Action-costing with it ──
    "turn_undead":           ECONOMY_ACTION,
    "radiance":              ECONOMY_ACTION,
    "preserve_life":         ECONOMY_ACTION,
    "divine_intervention":   ECONOMY_ACTION,
    "bastion_of_law":        ECONOMY_ACTION,
    "clockwork_cavalcade":   ECONOMY_ACTION,
    "warping_implosion":     ECONOMY_ACTION,
    "tireless":              ECONOMY_ACTION,
    "psychic_veil":          ECONOMY_ACTION,
    "shadow_arts_darkness":  ECONOMY_ACTION,
    "elemental_attunement":  ECONOMY_ACTION,
    "elemental_burst":       ECONOMY_ACTION,
    "quivering_palm":        ECONOMY_ACTION,
    "corona":                ECONOMY_ACTION,

    # ── inside the band, and costing nothing: the band is the only thing in their way ──
    "blink_steps":           ECONOMY_FREE,     # armed by the Attack/Magic action
    "swap_duplicity":        ECONOMY_FREE,     # Trickster's Transposition
    "fey_effect":            ECONOMY_FREE,     # picks the rider; spends nothing
    "misty_escape":          ECONOMY_REACTION,
}

# The Steps of the Fey riders, in cycle order. `main.py` holds the same list as
# `App._FEY_EFFECT_NAMES` for the click handler's log line; this is the label's copy.
_FEY_EFFECT_NAMES = ["None", "Refreshing", "Taunting", "Disappearing", "Dreadful"]


# ─────────────────────────────────────────────────────────────────────────────
#  Sorcerer Metamagic (SRD_CC_v5.2 p.65-66). A Sorcerer learns a limited number of
#  options and applies one to a spell at cast time (see METAMAGIC_IMPLEMENTATION_PLAN.md).
#  Subtle Spell is intentionally omitted — it is a deliberate no-op in this combat sim
#  (V/S/M components aren't simulated), so offering it would be a dead pick.
#  Rows: (MetamagicOption value, display name, SP cost, note).
#
#  Moved here from `dialogs.py` by M2e: the table is data and the gate below is a pure
#  predicate, and §7 needs both while this module may not import pygame. `dialogs.py`
#  re-exports them, so the dialog and `test_sorcerer.py` are unchanged.
# ─────────────────────────────────────────────────────────────────────────────
METAMAGIC_OPTIONS = [
    (rpg.MetamagicOption.Careful,    "Careful Spell",    1, "Allies auto-excluded from your AoE saves"),
    (rpg.MetamagicOption.Distant,    "Distant Spell",    1, "Double the spell's range (touch → 30 ft)"),
    (rpg.MetamagicOption.Empowered,  "Empowered Spell",  1, "Reroll up to CHA-mod low damage dice"),
    (rpg.MetamagicOption.Extended,   "Extended Spell",   1, "Double the duration (needs ≥ 2 rounds)"),
    (rpg.MetamagicOption.Heightened, "Heightened Spell", 2, "One target has Disadvantage on its save"),
    (rpg.MetamagicOption.Quickened,  "Quickened Spell",  2, "Cast a 1-action spell as a Bonus Action"),
    (rpg.MetamagicOption.Seeking,    "Seeking Spell",    1, "Reroll a missed spell attack (stacks)"),
    (rpg.MetamagicOption.Transmuted, "Transmuted Spell", 1, "Change the spell's damage type"),
    (rpg.MetamagicOption.Twinned,    "Twinned Spell",    1, "Target one additional creature"),
]

# One action id per option — `metamagic_careful`, `metamagic_distant`, … Every name in
# the table is "<Word> Spell", so the id is that word, lowercased. Nine ids means nine
# ordinary widgets, which is what retires the `btn_cbt_metamagic` DICT: Step 0.3's F4
# was that the dict slipped past the panel's stale-rect guard, and a dict cannot be
# dispatched by id.
METAMAGIC_ID_BY_VALUE = {int(v): "metamagic_" + n.split()[0].lower()
                         for v, n, sp, note in METAMAGIC_OPTIONS}
METAMAGIC_VALUE_BY_ID = {i: rpg.MetamagicOption(v)
                         for v, i in METAMAGIC_ID_BY_VALUE.items()}

# Arming a Metamagic option is not an action of any kind: the Sorcery Points are spent
# by the CAST that carries it. That is why the panel draws all nine outside the band —
# and why Quickened, which casts the spell AS a Bonus Action, is the one the band can
# still take.
_BONUS_ECONOMY.update({i: ECONOMY_FREE for i in METAMAGIC_ID_BY_VALUE.values()})


def metamagic_offered(option, learned_values, sp_available: int, sp_cost: int) -> bool:
    """Combat-sidebar gate for a Metamagic arm-toggle: offer it only when the option
    is LEARNED (in the caster's metamagic_options) and the caster can currently AFFORD
    its Sorcery-Point cost. Factored out as a pure predicate so it can be tested and
    reused by the sidebar draw pass (Phase 2).

    Step 0.3's **F5** named this as the shape `ActionMenu.build` generalizes — the one
    pure availability predicate the panel already had. M2e is where it stops being a
    precedent and becomes an ordinary member of this module.
    """
    learned = {int(v) for v in (learned_values or [])}
    return int(option) in learned and sp_available >= sp_cost


def _res(stats, name: str) -> int:
    """`stats`'s remaining uses of a named resource, or 0 when it has none at all.

    §7 asks this about forty times, always in the shape `r and r.current > N`. Missing
    and exhausted are the same answer to the panel, so they are the same answer here.
    """
    r = stats.get_resource(name)
    return r.current if r else 0


def _has_adjacent(app, agent_idx: int) -> bool:
    """True when any other token stands within one cell (5 ft) of `agent_idx`.

    The panel ran this scan inline on every frame to decide whether the Jump/Shove row
    was a three-up or Jump alone. It compares ORIGINS, not footprints, so a Large
    creature counts as adjacent by its top-left cell only — preserved as written, not
    corrected, and it is why the row's shape is bucket 7c rather than 7a.
    """
    agents = app.bm.placed_agents
    if not (0 <= agent_idx < len(agents)):
        return False
    me = agents[agent_idx].origin
    for i, other in enumerate(agents):
        if i == agent_idx:
            continue
        if max(abs(other.origin.col - me.col),
               abs(other.origin.row - me.row)) <= 1:
            return True
    return False


def _grappling_anyone(app, agent_idx: int) -> bool:
    """True when `agent_idx` is holding another creature in a Grapple.

    A scan of every other token's conditions, read LIVE from the engine rather than
    from `placed_agents[i].conditions` — the panel's comment is explicit that the
    cached copy can be a stale pybind snapshot, and the Escape button next to it reads
    the same way.
    """
    for i in range(len(app.bm.placed_agents)):
        if i == agent_idx:
            continue
        c = app.combat.get_agent_conditions(app.bm, i)
        if c.grappled and c.grappler_idx == agent_idx:
            return True
    return False


def fey_rider_index(app, stats) -> int:
    """The Steps of the Fey rider the panel will label its button with.

    `app.steps_of_fey_effect` is a cycle the player advances by clicking, and the
    cycle is shorter below Warlock 6 (three riders, not five) — so a selection made at
    L6 and then read at L3 is out of range. The panel CLAMPS it back to 0 and writes
    the clamp through, because the click handler and the engine call both read the raw
    field. This module never mutates `app`, so it computes the clamped value and
    `main.py` does the writing; both call this, so there is one rule and not two.
    """
    n_effects = 5 if stats.char_level >= 6 else 3
    return 0 if app.steps_of_fey_effect >= n_effects else app.steps_of_fey_effect


@dataclass(frozen=True)
class Action:
    """One option the panel is offering this frame.

    ``id`` is the stable dispatch key — the panel looks its widget up by it and
    ``_handle_events`` branches on it, so it is an API and not a label. It matches the
    ``btn_cbt_`` suffix wherever a single button backs the option, which keeps the M2
    diffs greppable; nothing depends on that beyond convenience.

    ``enabled``/``disabled_reason`` are carried from day one because the wire format
    wants them (a remote client greys an option out rather than hiding it, so a player
    can see *why* they cannot act). **The DM panel has no disabled rendering** —
    ``widgets.Button`` draws one way only — so every action built here is enabled, and
    an unavailable option is simply absent. The first renderer to grow a grey state is
    M4's client, not this panel.

    ``economy`` is what clicking it spends — one of ``ECONOMY`` — and it is the field
    bucket 7d exists to force. Nothing reads it in M2: the panel's band gate is still
    the panel's, preserved as it is. It is here because a remote client cannot lay out
    an action economy it has to infer from which section a button arrived in, and
    because the band-gate finding needs somewhere to be fixed FROM.
    """
    id: str
    label: str
    group: str
    enabled: bool = True
    disabled_reason: str = ""
    expects: str = "none"
    economy: str = ECONOMY_NONE


class ActionMenu:
    """``build(app, agent_idx) -> list[Action]`` — the panel's offer, as data."""

    @staticmethod
    def build(app, agent_idx: int) -> list[Action]:
        """Every option the converted sections offer for ``agent_idx`` right now.

        ``agent_idx`` may be out of range (no combat, or a turn between agents); the
        per-creature groups then contribute nothing and the session group still does,
        which mirrors what the panel draws in that state.
        """
        out: list[Action] = []
        out += ActionMenu._session(app)
        out += ActionMenu._turn(app, agent_idx)
        out += ActionMenu._action(app, agent_idx)
        out += ActionMenu._portent(app, agent_idx)
        out += ActionMenu._bonus(app, agent_idx)
        out += ActionMenu._utility(app, agent_idx)
        return out

    # ── §1 — DM tools ──────────────────────────────────────────────────────────
    @staticmethod
    def _session(app) -> list[Action]:
        # Both are DM tools standing outside the fiction, so neither has an economy.
        return [
            Action("pause_resume",
                   "▶ Resume" if app.combat_paused else "⏸ Pause",
                   GROUP_SESSION),
            Action("end_combat", "End Combat", GROUP_SESSION),
        ]

    # ── §3 — turn control ──────────────────────────────────────────────────────
    @staticmethod
    def _turn(app, agent_idx: int) -> list[Action]:
        # Unconditional today, including while paused: the panel draws End Turn in
        # every branch and the click handler is what refuses a paused advance. Moving
        # that refusal here would change what the panel renders, which M2's
        # no-behaviour-change rule forbids — it is an `enabled=False` waiting for a
        # renderer that can show it.
        return [Action("end_turn", "End Turn", GROUP_TURN)]

    # ── §4 — the Action economy band ───────────────────────────────────────────
    @staticmethod
    def _action(app, agent_idx: int) -> list[Action]:
        """The five-way branch, as five returns.

        The panel still computes `incapacitated` / `mid_sequence` / `frightened` for
        itself, because each arm prints a *line of text* ("[Action used]", "Frightened
        — must Dash") that is display, not an option, and because two of the three are
        read again by sections this phase has not reached. The duplication is one
        expression per arm and is the price of converting §4 without also converting
        §7; it goes away when the last group does.
        """
        agents = app.bm.placed_agents
        if not (0 <= agent_idx < len(agents)):
            return []

        cond = app.combat.get_agent_conditions(app.bm, agent_idx)
        if cond.incapacitated or cond.unconscious:
            return []                       # arm 1 — the band collapses to a message

        # `action_used` goes True the moment an Attack action starts, but an Extra
        # Attack sequence still owes swings; `mid_sequence` is what keeps the band
        # open for them, and it is why "[Action used]" and `action_used` are not the
        # same question.
        mid_sequence = (app.attacks_remaining > 0 and
                        app._attack_sequence_slot == "action")

        if app.action_used and not mid_sequence:
            # arm 2 — spent. Exactly one thing can still be offered: Nick relocating
            # the off-hand attack into the Attack action that was just taken.
            if app._nick_offhand_idx(agent_idx) >= 0:
                # Nick relocates the off-hand swing INTO the Attack action, which is
                # why it survives `action_used`: it is paid for out of that action's
                # attacks and not out of the Action again.
                return [Action("nick", "🗡 Nick: Off-hand Atk", GROUP_ACTION,
                               economy=ECONOMY_ATTACK)]
            return []

        if cond.frightened:
            return [Action("dash", "Dash", GROUP_ACTION,        # arm 3 — Dash or nothing
                           economy=ECONOMY_ACTION)]

        # arms 4 and 5 — the full band; `prone` chooses between the last two.
        out: list[Action] = []
        # `BattleMap::getAgentWeapons` pads every slot list to three
        # (`battle_map.hpp:302`, `setAgentWeapons`), so no creature can fail this test
        # today. It is kept because it states the rule the panel meant to state, and
        # dropped from the widget row rather than left invisible-but-live — which is
        # Step 0.3's **F3**, deleted here by construction.
        if len(app.combat.get_agent_weapons(app.bm, agent_idx)) > 0:
            out.append(Action("atk_action",
                              f"⚔ Attack ({app.attacks_remaining})" if mid_sequence
                              else "⚔ Attack",
                              GROUP_ACTION, economy=ECONOMY_ACTION))
        out.append(Action("unarmed", "👊 Unarmed", GROUP_ACTION,
                          economy=ECONOMY_ACTION))

        out += [Action("dash",      "Dash",      GROUP_ACTION, economy=ECONOMY_ACTION),
                Action("dodge",     "Dodge",     GROUP_ACTION, economy=ECONOMY_ACTION),
                Action("disengage", "Disengage", GROUP_ACTION, economy=ECONOMY_ACTION),
                Action("hide",      "Hide",      GROUP_ACTION, economy=ECONOMY_ACTION)]
        # Always exactly one of these two: the fifth column of that row is "change
        # your posture", and `prone` only decides which way it points. Build order is
        # what puts it in that column, so it is appended last of the five.
        out.append(Action("standup", "Stand Up", GROUP_ACTION, economy=ECONOMY_ACTION)
                   if cond.prone
                   else Action("prone", "Go Prone", GROUP_ACTION,
                               economy=ECONOMY_ACTION))

        if len(app.combat.get_agent_spells(app.bm, agent_idx)) > 0:
            out.append(Action("spell_action", "✨ Cast Spell", GROUP_ACTION,
                              economy=ECONOMY_ACTION))
        return out

    # ── §6 — Portent dice ──────────────────────────────────────────────────────
    @staticmethod
    def _portent(app, agent_idx: int) -> list[Action]:
        """Diviner Wizards, while any die is left unspent.

        §6 is the one section whose *heading* is the same predicate as its button —
        the panel prints "Portent Dice:" and the readout exactly when Use Portent Die
        is on offer — so converting the one button converts the whole section, and
        the panel's remaining job there is the dice readout's text.

        Note what is NOT here: the incapacitated gate. §4 collapses when a creature
        cannot act and §6 does not, which is the panel's behaviour today; Portent is
        a no-action reroll, so that is arguably right, but either way M2 preserves it.
        """
        if not (0 <= agent_idx < len(app.bm.placed_agents)):
            return []
        stats = app.combat.get_agent_stats(app.bm, agent_idx)
        if stats.character_class != rpg.CharacterClass.Wizard:
            return []
        if stats.wizard_subclass != rpg.WizardSubclass.Diviner:
            return []
        if not stats.get_resource("Portent Dice") or len(stats.portent_dice) == 0:
            return []
        # A Portent die is spent on somebody else's roll; it costs no economy, which
        # is the same reason the section survives the incapacitated gate above.
        return [Action("use_portent", "Use Portent Die", GROUP_PORTENT,
                       economy=ECONOMY_FREE)]

    # ── §7 — the Bonus Action mega-section ─────────────────────────────────────
    @staticmethod
    def _priced(out: list[Action]) -> list[Action]:
        """§7's actions with `economy` filled in from `_BONUS_ECONOMY`.

        Stamped on the way out rather than passed at each of the ninety-odd
        construction sites, because the rule is "the Bonus Action, unless this table
        says otherwise" and a rule reads better in one place than in ninety.
        """
        return [replace(a, economy=_BONUS_ECONOMY.get(a.id, ECONOMY_BONUS))
                for a in out]

    @staticmethod
    def _metamagic(app, stats) -> list[Action]:
        """§7's tail: the Sorcerer's arm-toggles, drawn after everything else.

        Not a Bonus Action, not an Action, not gated on the band — arming a qualifier
        costs nothing, and the Sorcery Points go with the cast that carries it. That is
        bucket 7d's whole argument, and it is why this is built at BOTH of `_bonus`'s
        exits: the band closing must not take it.

        Quickened is the one exception, because it casts the spell AS a Bonus Action,
        and it is the only option the spent band removes.

        Sorcery Incarnate (Sorcerer 7, while Innate Sorcery runs) lets a SECOND option
        be armed alongside the first; `armed_metamagic2` is only read while it does.
        Seeking is not radio-selected at all — it stacks — so it has its own flag.
        """
        if (stats.character_class != rpg.CharacterClass.Sorcerer
                or stats.char_level < 2 or len(stats.metamagic_options) == 0):
            return []
        sp_have = _res(stats, "Sorcery Points")
        learned = list(stats.metamagic_options)
        incarnate = rpg.CombatEngine.sorcery_incarnate_active(stats)
        out: list[Action] = []
        for mm_val, mm_name, _mm_sp, _mm_note in METAMAGIC_OPTIONS:
            if mm_val == rpg.MetamagicOption.Quickened and app.bonus_used:
                continue
            cost = rpg.CombatEngine.metamagic_sp_cost(mm_val)
            if not metamagic_offered(mm_val, learned, sp_have, cost):
                continue
            armed = (app.armed_seeking if mm_val == rpg.MetamagicOption.Seeking
                     else (app.armed_metamagic == mm_val
                           or (incarnate and app.armed_metamagic2 == mm_val)))
            out.append(Action(METAMAGIC_ID_BY_VALUE[int(mm_val)],
                              f"{'✓ ' if armed else ''}✨ {mm_name} ({cost} SP)",
                              GROUP_BONUS))
        return out

    @staticmethod
    def _bonus(app, agent_idx: int) -> list[Action]:
        """Bucket 7a: §7's flat, independent guards (M2c).

        Built in the panel's DRAW ORDER, because `main.py` lays each converted run out
        positionally — the same contract `_action`'s column order has, and the same
        test pins it.

        Two things this method is deliberately not allowed to tidy:

        · the **band gate**. Most of §7 sits inside one `if not incapacitated and not
          bonus_used:` block, including several buttons whose own comments say they are
          not Bonus Actions at all (`action_surge` "available anytime", `corona`, the
          Paladin capstones). Spending the Bonus Action hides them today; checkpoint 03
          records exactly that, and M2 preserves it. Whether it is *right* is a separate
          item.
        · the guards that are **outside** it — `use_item`, `extinguish` — which are
          action-gated or per-item instead. They are not an oversight; they are why the
          `economy` field the plan wants cannot be a boolean.
        """
        agents = app.bm.placed_agents
        if not (0 <= agent_idx < len(agents)):
            # F13, fixed — F7's shape, one section down, and the same answer M2b gave
            # it. With NOBODY on turn the panel drew a Jump button for a creature that
            # does not exist: out of range `_is_incapacitated` is False and `bonus_used`
            # falls back to a plain flag, so the band stood open, and the Jump/Shove
            # row's only per-creature test is the adjacency scan, which decides the
            # row's WIDTH and not whether it exists. A section that cannot read a
            # creature offers nothing. Checkpoint 99 is the record of both states.
            return []
        cond = app.combat.get_agent_conditions(app.bm, agent_idx)
        if cond.incapacitated or cond.unconscious:
            return []               # the whole section collapses to "[Cannot act]"

        stats = app.combat.get_agent_stats(app.bm, agent_idx)
        out: list[Action] = []

        # ── the economy-band header row (bucket 7b, M2e) ──
        # The band's own two buttons, and the one place in §7 whose gate is not plain
        # `not bonus_used`: an Extra Attack sequence parked in the BONUS slot still owes
        # swings, and `mid_sequence_bonus` is what keeps the row open with the flag
        # already set — the same distinction `_action` draws one section up. Both the
        # LABEL and the column count follow from it, which is what made this its own
        # bucket rather than part of 7a.
        #
        # **F3's second half closes here.** The panel set `btn_cbt_atk_bonus`'s rect and
        # then drew the widget only `if _cur_has_offhand or mid_sequence_bonus`, so a
        # click in that space fired the handler on an option it was deliberately not
        # offering. An action the menu does not build gets no rect at all.
        mid_sequence_bonus = (app.attacks_remaining > 0
                              and app._attack_sequence_slot == "bonus")
        if not app.bonus_used or mid_sequence_bonus:
            if app._offhand_bonus_available(agent_idx) or mid_sequence_bonus:
                out.append(Action("atk_bonus",
                                  f"⚔ Bonus ({app.attacks_remaining})"
                                  if mid_sequence_bonus else "⚔ Bonus Atk",
                                  GROUP_BONUS))
            if len(app.combat.get_agent_spells(app.bm, agent_idx)) > 0:
                out.append(Action("spell_bonus", "✨ Spell", GROUP_BONUS))

        # ── ahead of the Jump/Shove row (each band-gated on its own) ──
        if not app.bonus_used:
            if (stats.character_class == rpg.CharacterClass.Wizard and
                    stats.wizard_subclass == rpg.WizardSubclass.Abjurer and
                    stats.char_level >= 3 and stats.temp_hp > 0):
                # The ward IS the temp HP pool, which is why there is no separate
                # "ward active" flag to read.
                out.append(Action("charge_arcane_ward", "🔮 Ward", GROUP_BONUS))

            if (stats.character_class == rpg.CharacterClass.Druid and
                    stats.char_level >= 2):
                out.append(Action("wild_shape",
                                  "Exit Wild Shape" if stats.wild_shape_active
                                  else "🐺 Wild Shape",
                                  GROUP_BONUS))

        # ── outside the band ──
        # A potion is a Bonus Action; a thrown flask or a Net replaces one attack of
        # the Attack action. So the offer is "can any carried item still be paid for",
        # per item, and not a single economy test.
        if any(app._can_replace_attack(agent_idx)
               if it.action_type == rpg.ItemAction.AttackReplacement
               else (not app.bonus_used) if it.action_type == rpg.ItemAction.BonusAction
               else (not app.action_used) if it.action_type == rpg.ItemAction.Action
               else True
               for it in app.combat.get_agent_items(app.bm, agent_idx)):
            out.append(Action("use_item", "🧪 Use Item", GROUP_BONUS))

        if not app.action_used and cond.burning:
            out.append(Action("extinguish", "🔥 Extinguish (Prone)", GROUP_BONUS))

        # Drop Grapple is a FREE action — the panel draws it outside the band on
        # purpose, so spending the Bonus Action cannot strand a creature holding one.
        if _grappling_anyone(app, agent_idx):
            out.append(Action("grapple_drop", "🔓 Drop", GROUP_BONUS))

        # Free from Net costs an Action, and is offered to a netted creature or to one
        # standing within 5 ft of a netted neighbour (the target is then a click).
        if not app.action_used and app._netted_within_reach(agent_idx):
            out.append(Action("escape_net", "🕸 Free from Net", GROUP_BONUS))

        # Haste's extra limited action, refilled at the top of each of the hasted
        # creature's turns. Outside the band because it IS an Action: spending the Bonus
        # Action first must not dead-key it. The flag is the whole guard — the engine
        # sets and clears it — which is what keeps it out of the trap its own comment
        # in the panel warns about.
        if stats.haste_action_available:
            out.append(Action("haste_action", "⚡ Haste Action", GROUP_BONUS))

        # ── the band block ──
        # Everything past this point is inside the panel's one big
        # `if not _is_incapacitated and not self.bonus_used:`, whatever an individual
        # feature's action cost actually is. Checkpoint 03 is the record of that.
        if app.bonus_used:
            return ActionMenu._priced(out + ActionMenu._metamagic(app, stats))

        cls = stats.character_class
        lvl = stats.char_level
        CC = rpg.CharacterClass

        # ── the spatial predicates (bucket 7c, M2d) ──
        # The band's first row. Jump is always offered; Shove and Trip need something
        # to shove, and Escape needs that something to be holding you. One scan of the
        # token list answers all three, where the panel ran it per frame per button.
        adjacent = _has_adjacent(app, agent_idx)
        out.append(Action("long_jump", "Jump", GROUP_BONUS))
        if adjacent:
            out.append(Action("shove_push", "🔨 Shove", GROUP_BONUS))
            out.append(Action("shove_prone", "⬇ Trip", GROUP_BONUS))
            if cond.grappled:
                out.append(Action("grapple_esc", "💨 Escape", GROUP_BONUS))

        # ── Telekinetic Shove — the FEAT's option (F10, fixed) ──
        # The feat's 30 ft shove, and Psi Warrior's Telekinetic Movement further down,
        # are two options with two widgets and two handlers. They shared one widget
        # until M2e: a creature satisfying both had it painted twice in one pass, and
        # the single handler armed both pending flags on one click, whoever clicked it.
        if stats.has_feat("Telekinetic"):
            out.append(Action("telekinetic_feat", "🌀 Telekinetic Shove", GROUP_BONUS))

        # ── Cunning Action (M2d) ──
        # A three-up row in the same column order as §4's, and a cluster in the only
        # sense that matters here: one flag offers all three or none.
        if stats.has_cunning_action:
            out += [Action("dash_bonus",      "Dash",      GROUP_BONUS),
                    Action("disengage_bonus", "Disengage", GROUP_BONUS),
                    Action("hide_bonus",      "Hide",      GROUP_BONUS)]

        # ── Monk ──
        if cls == CC.Monk:
            focus = _res(stats, "Focus Points")
            if focus > 0:
                out.append(Action("patient_defense", "Patient Defense", GROUP_BONUS))
            # The panel's Fleet Step arm (Open Hand L11: a free Step of the Wind with
            # the Bonus Action already spent) is unreachable — it is written inside the
            # band gate, which has already required `not bonus_used`. Kept in that shape
            # so the conversion changes nothing; see F11.
            fleet_step_ready = (stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand
                                and lvl >= 11 and not cond.fleet_step_used
                                and app.bonus_used)
            if focus > 0 or fleet_step_ready:
                out.append(Action("step_of_wind", "Step of the Wind", GROUP_BONUS))
            if (stats.monk_subclass == rpg.MonkSubclass.WarriorOfMercy and lvl >= 3
                    and focus > 0):
                out.append(Action("hand_of_healing", "Hand of Healing", GROUP_BONUS))
            if (stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand and lvl >= 6
                    and _res(stats, "Wholeness of Body") > 0):
                out.append(Action("wholeness_of_body", "Wholeness of Body", GROUP_BONUS))

        # ── Barbarian ──
        if cls == CC.Barbarian:
            if not cond.raging and _res(stats, "Rage") > 0:
                out.append(Action("rage", "Rage (Bonus)", GROUP_BONUS))
            # The panel says level 10 and the engine grants the resource at 14, so
            # 10-13 can never reach the draw. Preserved, and recorded as F9.
            ip = _res(stats, "Intimidating Presence")
            if (stats.barbarian_subclass == rpg.BarbianSubclass.Berserker and lvl >= 10
                    and ip > 0):
                out.append(Action("intimidating_presence",
                                  f"Intimidating Presence ({ip})", GROUP_BONUS))
            zp = _res(stats, "Zealous Presence")
            if (stats.barbarian_subclass == rpg.BarbianSubclass.Zealot and lvl >= 10
                    and zp > 0):
                out.append(Action("zealous_presence",
                                  f"Zealous Presence ({zp})", GROUP_BONUS))

        # ── Warlock ──
        if cls == CC.Warlock:
            if (stats.warlock_subclass == rpg.WarlockSubclass.GreatOldOne and lvl >= 6):
                uses = _res(stats, "Clairvoyant Combatant")
                psl = stats.pact_slot_level()
                has_pact_slot = psl >= 1 and stats.spell_slots_remaining[psl - 1] > 0
                if uses > 0 or has_pact_slot:
                    out.append(Action("clairvoyant_combatant",
                                      f"Clairvoyant Combatant ({uses})" if uses > 0
                                      else "Clairvoyant Combatant (Pact slot)",
                                      GROUP_BONUS))
            if _res(stats, "Magical Cunning") > 0:
                out.append(Action("magical_cunning", "Magical Cunning", GROUP_BONUS))
            if (stats.warlock_subclass == rpg.WarlockSubclass.Celestial and lvl >= 3
                    and _res(stats, "Healing Light") > 0):
                out.append(Action("healing_light", "Healing Light", GROUP_BONUS))

        # ── Cleric: the Channel Divinity cluster (M2d) ──
        # One resource, three buttons. Turn Undead is every Cleric's from L2; the two
        # domain options are nested INSIDE its resource test, which is what makes this
        # a cluster rather than a run — there is no order of single-button extractions
        # that reaches them. All three cost the Action (`not app.action_used`), and all
        # three sit inside the Bonus Action band anyway; see the band-gate note above.
        if (not app.action_used and cls == CC.Cleric and lvl >= 2
                and _res(stats, "Channel Divinity") > 0):
            out.append(Action("turn_undead", "Turn Undead", GROUP_BONUS))
            sub_c = stats.cleric_subclass
            if sub_c == rpg.ClericSubclass.LightDomain and lvl >= 3:
                out.append(Action("radiance", "Radiance of the Dawn", GROUP_BONUS))
            if sub_c == rpg.ClericSubclass.LifeDomain and lvl >= 3:
                out.append(Action("preserve_life", "Preserve Life", GROUP_BONUS))

        # ── Cleric: Divine Intervention ──
        # Keyed on the resource rather than on class+level, which is what keeps it out
        # of the dead-key trap the Haste button's comment names.
        if not app.action_used and app.combat.can_use_divine_intervention(app.bm, agent_idx):
            out.append(Action("divine_intervention", "Divine Intervention", GROUP_BONUS))

        # ── Trickery Cleric: the Invoke Duplicity cluster (M2d) ──
        # The activation spends a Channel Divinity use; the other two exist only while
        # an illusion is standing on the map, which is a scan of every placed agent
        # (`_my_duplicates`) and not a resource at all. The panel repeats
        # `not self.bonus_used` around the first two inside the band that has already
        # required it; dropped here, as M2c dropped the same repeats.
        if (cls == CC.Cleric
                and stats.cleric_subclass == rpg.ClericSubclass.TrickeryDomain
                and lvl >= 3):
            if _res(stats, "Channel Divinity") > 0:
                out.append(Action("invoke_duplicity", "Invoke Duplicity", GROUP_BONUS))
            if app._my_duplicates(agent_idx):
                out.append(Action("move_duplicity", "Move Duplicate", GROUP_BONUS))
                # Trickster's Transposition is free and the panel still draws it inside
                # the band, like everything else here.
                if lvl >= 6:
                    out.append(Action("swap_duplicity", "Swap w/ Duplicate", GROUP_BONUS))

        # ── the Sorcerer run, plus the two guards drawn inside it ──
        # In DRAW order, not class order: `boon_of_fate` (a feat) and `steady_aim` /
        # `war_priest` (Rogue, Cleric) sit inside this stretch, and the panel's column
        # is what the order has to match.
        #
        # Several of these repeat `not self.bonus_used` inside the band that has already
        # required it. The band gate above answers it once; the repeats are dropped here
        # rather than carried as always-true expressions.
        sp = _res(stats, "Sorcery Points")
        if cls == CC.Sorcerer:
            SS = rpg.SorcererSubclass
            sub = stats.sorcerer_subclass
            if sub == SS.Draconic and lvl >= 14:
                out.append(Action("dragon_wings",
                                  "Dismiss Dragon Wings" if stats.dragon_wings_active
                                  else "Dragon Wings (extend)", GROUP_BONUS))
            if (sub == SS.Draconic and lvl >= 6 and stats.draconic_affinity_type >= 0
                    and stats.draconic_affinity_resist_turns == 0 and sp >= 1):
                out.append(Action("draconic_resistance",
                                  "Draconic Resistance (1 SP)", GROUP_BONUS))
            if sub == SS.WildMagic and lvl >= 6 and sp > 0:
                out.append(Action("bend_luck", "Bend Luck (1 SP)", GROUP_BONUS))

        if stats.has_feat("Boon of Fate") and not stats.boon_of_fate_used:
            out.append(Action("boon_of_fate", "Boon of Fate (2d4)", GROUP_BONUS))

        if cls == CC.Sorcerer:
            if (sub == SS.WildMagic and lvl >= 3
                    and _res(stats, "Tides of Chaos") > 0):
                out.append(Action("tides_of_chaos", "Tides of Chaos", GROUP_BONUS))

            if stats.innate_sorcery_turns == 0:
                free_use = _res(stats, "Innate Sorcery") > 0
                if free_use or (lvl >= 7 and sp >= 2):
                    out.append(Action("innate_sorcery",
                                      "Innate Sorcery" if free_use
                                      else "Innate Sorcery (2 SP)", GROUP_BONUS))

            if sub == SS.Clockwork:
                if lvl >= 14 and stats.trance_of_order_turns == 0:
                    free_use = _res(stats, "Trance of Order") > 0
                    if free_use or sp >= 5:
                        out.append(Action("trance_of_order",
                                          "Trance of Order" if free_use
                                          else "Trance of Order (5 SP)", GROUP_BONUS))
                if not app.action_used and lvl >= 6 and sp >= 1:
                    out.append(Action("bastion_of_law", "Bastion of Law", GROUP_BONUS))
                if not app.action_used and lvl >= 18:
                    free_use = _res(stats, "Clockwork Cavalcade") > 0
                    if free_use or sp >= 7:
                        out.append(Action("clockwork_cavalcade",
                                          "Clockwork Cavalcade" if free_use
                                          else "Clockwork Cavalcade (7 SP)", GROUP_BONUS))

            if sub == SS.Aberrant:
                if (lvl >= 14 and stats.revelation_in_flesh_turns == 0 and sp >= 1):
                    out.append(Action("revelation_in_flesh",
                                      "Revelation in Flesh (1 SP)", GROUP_BONUS))
                if not app.action_used and lvl >= 18:
                    free_use = _res(stats, "Warping Implosion") > 0
                    if free_use or sp >= 5:
                        out.append(Action("warping_implosion",
                                          "Warping Implosion" if free_use
                                          else "Warping Implosion (5 SP)", GROUP_BONUS))

        # The three Wild Magic surge affordances are bare flags with no class guard —
        # a surge sets them, and they are read exactly as written.
        if stats.wild_magic_extra_action:
            out.append(Action("wild_magic_extra_action",
                              "Wild Magic: Extra Action", GROUP_BONUS))
        if stats.wild_magic_bonus_cast_turns > 0:
            out.append(Action("wild_magic_bonus_cast",
                              "Wild Magic: Cast as Bonus", GROUP_BONUS))
        if stats.wild_magic_teleport_bonus_turns > 0:
            out.append(Action("wild_magic_teleport",
                              "Wild Magic: Teleport 20ft", GROUP_BONUS))

        if cls == CC.Rogue and lvl >= 3 and not cond.steady_aim:
            out.append(Action("steady_aim", "Steady Aim", GROUP_BONUS))

        if (cls == CC.Cleric and stats.cleric_subclass == rpg.ClericSubclass.WarDomain
                and lvl >= 3 and _res(stats, "War Priest") > 0):
            out.append(Action("war_priest", "War Priest (Bonus Attack)", GROUP_BONUS))


        # ── Bite (grappled) (bucket 7c, M2d) ──
        # A weapon flagged `auto_use_when_grappling` (a Vampire's Bite) whose wielder is
        # currently holding a legal victim: the engine finds the pair, and the button is
        # the one-click version of picking that weapon and that target by hand. Offered
        # while the Attack action is unspent OR mid-multiattack, which is the common
        # case — a claw grapples, and the trailing Bite fires.
        mid_sequence_action = (app.attacks_remaining > 0
                               and app._attack_sequence_slot == "action")
        if not app.action_used or mid_sequence_action:
            wslot, victim = app.combat.pending_auto_grapple_strike(app.bm, agent_idx)
            if wslot >= 0 and victim >= 0:
                out.append(Action("bite_grappled", "🧛 Bite (grappled)", GROUP_BONUS))

        # ── the run the panel draws after Bite (grappled) ──
        if cond.gwm_hew_available:
            out.append(Action("gwm_hew", "Hew (Bonus Attack)", GROUP_BONUS))
        # Blink Steps is armed by taking the Attack/Magic action, and costs nothing —
        # so it has no economy test of its own, only the band it happens to sit in.
        if app._blink_steps_ready(agent_idx):
            out.append(Action("blink_steps", "✦ Blink Steps (30 ft)", GROUP_BONUS))

        if cls == CC.Monk:
            out.append(Action("martial_arts", "Martial Arts (Bonus Attack)", GROUP_BONUS))
            if _res(stats, "Focus Points") > 0:
                # L10 Heightened Focus makes Flurry three strikes instead of two.
                out.append(Action("flurry_of_blows",
                                  f"Flurry of Blows ({3 if lvl >= 10 else 2} Attacks)",
                                  GROUP_BONUS))

        if cls == CC.Fighter and _res(stats, "Second Wind") > 0:
            out.append(Action("second_wind", "Second Wind (Bonus Action)", GROUP_BONUS))
        if (cls == CC.Fighter
                and stats.fighter_subclass == rpg.FighterSubclass.BattleMaster
                and _res(stats, "Superiority Dice") > 0):
            out.append(Action("bm_maneuver", "Maneuver (Bonus Action)", GROUP_BONUS))

        # Both of these are free Invisibility in Dim Light/Darkness; the lighting gate
        # is enforced by the click, not by the offer, which is why neither reads it.
        if cls == CC.Warlock and stats.has_invocation(8):
            out.append(Action("one_with_shadows",
                              "One with Shadows (Invisible)", GROUP_BONUS))
        if stats.has_feat("Boon of the Night Spirit"):
            out.append(Action("merge_shadows",
                              "Merge with Shadows (Invisible)", GROUP_BONUS))

        if cls == CC.Fighter and _res(stats, "Action Surge") > 0:
            out.append(Action("action_surge", "Action Surge", GROUP_BONUS))
        if cls == CC.Paladin and _res(stats, "Lay on Hands") > 0:
            out.append(Action("lay_on_hands", "Lay on Hands", GROUP_BONUS))

        # ── Bard: Grant Inspiration, and the College of Glamour cluster (M2d) ──
        # The four Glamour buttons are nested inside `grant_inspiration`'s own Bardic
        # Inspiration test in the panel — two of them read `bi` themselves — which is
        # what makes this a cluster and why M2c left the wrapper standing. Mantle of
        # Majesty and Unbreakable Majesty are each "a use remaining OR the window is
        # already running", the second arm being how you re-cast Command for free or
        # keep negating melee attacks after the use is gone.
        if cls == CC.Bard:
            bi = _res(stats, "Bardic Inspiration")
            glamour = stats.bard_subclass == rpg.BardCollege.Glamour
            if bi > 0:
                out.append(Action("grant_inspiration",
                                  "Grant Inspiration (Bonus Action)", GROUP_BONUS))
            if bi > 0 and lvl >= 3 and glamour:
                out.append(Action("mantle",
                                  "Mantle of Inspiration (Bonus Action)", GROUP_BONUS))
            if (lvl >= 6 and glamour
                    and (_res(stats, "Mantle of Majesty") > 0
                         or stats.mantle_majesty_turns > 0)):
                out.append(Action("mantle_majesty",
                                  "Mantle of Majesty (Bonus Action)", GROUP_BONUS))
            if (lvl >= 14 and glamour
                    and (_res(stats, "Unbreakable Majesty") > 0
                         or stats.majestic_presence_turns > 0)):
                out.append(Action("unbreakable_majesty",
                                  "Unbreakable Majesty (Bonus Action)", GROUP_BONUS))
            if bi > 0 and lvl >= 3 and glamour:
                # The only guard in §7 that asks whether a resource is NOT FULL: the
                # button exists to buy the spent Beguiling Magic use back.
                beg = stats.get_resource("Beguiling Magic")
                if beg and beg.current < beg.max:
                    out.append(Action("beguiling_restore",
                                      "Restore Beguiling Magic (1 Inspiration)",
                                      GROUP_BONUS))


        # ── Use Inspiration, then the Paladin oaths ──
        # The die a Bard hands out is held by the RECIPIENT, so this one has no class
        # guard at all — any creature holding a die is offered it.
        if stats.bardic_inspiration_die > 0:
            out.append(Action("use_inspiration", "Use Inspiration Die", GROUP_BONUS))

        if cls == CC.Paladin:
            PO = rpg.PaladinOath
            oath = stats.paladin_oath
            co = _res(stats, "Channel Oath")
            has_l5_slot = stats.spell_slots_remaining[4] > 0
            if oath == PO.OathOfDevotion and co > 0 and stats.sacred_weapon_turns == 0:
                out.append(Action("sacred_weapon",
                                  "Sacred Weapon (Bonus Action)", GROUP_BONUS))
            if oath == PO.OathOfVengeance and co > 0:
                out.append(Action("vow_of_enmity", f"Vow of Enmity ({co})", GROUP_BONUS))
            if (oath == PO.OathOfGlory and cond.divine_smite_used
                    and not cond.inspiring_smite_used and co > 0):
                out.append(Action("inspiring_smite",
                                  f"Inspiring Smite ({co})", GROUP_BONUS))

            # The three L20 capstones are the same rule three times: a free use, or a
            # level-5 slot spent instead, and not already running.
            for oath_want, turns, res_name, aid, label in (
                    (PO.OathOfVengeance, stats.avenging_angel_turns,
                     "Avenging Angel", "avenging_angel", "Avenging Angel"),
                    (PO.OathOfAncients, stats.elder_champion_turns,
                     "Elder Champion", "elder_champion", "Elder Champion"),
                    (PO.OathOfGlory, stats.living_legend_turns,
                     "Living Legend", "living_legend", "Living Legend")):
                if oath != oath_want or lvl < 20 or turns != 0:
                    continue
                uses = _res(stats, res_name)
                if uses > 0 or has_l5_slot:
                    out.append(Action(aid,
                                      f"{label} ({uses})" if uses > 0
                                      else f"{label} (L5 slot)", GROUP_BONUS))

        if (not app.action_used and cls == CC.Cleric
                and stats.cleric_subclass == rpg.ClericSubclass.LightDomain
                and lvl >= 17 and stats.corona_of_light_turns == 0):
            out.append(Action("corona", "Corona of Light (Action)", GROUP_BONUS))

        # ── Telekinetic Movement — the PSI WARRIOR's option (F10, fixed) ──
        # The second half of the pair above. A Psi Warrior who has also taken the feat
        # is offered both; checkpoint 63 is the block where both are drawn.
        if (cls == CC.Fighter
                and stats.fighter_subclass == rpg.FighterSubclass.PsiWarrior
                and _res(stats, "Telekinetic Movement") > 0):
            out.append(Action("telekinetic_psi", "Telekinetic Movement", GROUP_BONUS))

        # ── Ranger ──
        if cls == CC.Ranger:
            da = _res(stats, "Dread Ambusher")
            if (stats.ranger_subclass == rpg.RangerSubclass.GloomStalker and lvl >= 3
                    and da > 0 and not cond.dread_ambusher_used
                    and not cond.dreadful_strike_armed):
                out.append(Action("dread_ambusher",
                                  f"Dread Ambusher ({da})", GROUP_BONUS))
            tl = _res(stats, "Tireless")
            if not app.action_used and lvl >= 10 and tl > 0:
                out.append(Action("tireless", f"Tireless ({tl})", GROUP_BONUS))
            nv = _res(stats, "Nature's Veil")
            if lvl >= 14 and nv > 0:
                out.append(Action("natures_veil", f"Nature's Veil ({nv})", GROUP_BONUS))

        # ── Soulknife Rogue (M2d) ──
        # Both labels carry the Psionic Energy count, and both features can be paid for
        # with either their own use or a die — which is why the Veil is offered while
        # its resource is empty but dice remain.
        if cls == CC.Rogue and stats.rogue_subclass == rpg.RogueSubclass.Soulknife:
            ped_n = _res(stats, "Psionic Energy")
            if lvl >= 9 and ped_n > 0:
                out.append(Action("psychic_teleport",
                                  f"Psychic Teleport ({ped_n} dice)", GROUP_BONUS))
            if lvl >= 13 and not app.action_used:
                pv = _res(stats, "Psychic Veil")
                if pv > 0 or ped_n > 0:
                    out.append(Action("psychic_veil",
                                      f"Psychic Veil ({pv}+{ped_n}d)", GROUP_BONUS))

        # ── Warrior of Shadow Monk (M2d) ──
        # Two Bonus Actions with no resource of their own, and one Magic action that
        # costs Focus — which is why spending the Bonus Action does not take all three
        # (the band gate above does, but that is the band's doing, not the feature's).
        if cls == CC.Monk and stats.monk_subclass == rpg.MonkSubclass.WarriorOfShadow:
            if lvl >= 6:
                out.append(Action("shadow_step", "Shadow Step (Bonus)", GROUP_BONUS))
            if lvl >= 17:
                out.append(Action("cloak_of_shadows",
                                  "Cloak of Shadows (Bonus)", GROUP_BONUS))
            fp_d = _res(stats, "Focus Points")
            if lvl >= 3 and not app.action_used and fp_d > 0:
                out.append(Action("shadow_arts_darkness",
                                  f"Shadow Arts: Darkness ({fp_d} Focus)", GROUP_BONUS))

        # ── Archfey Warlock (M2d) ──
        # The rider selector is always offered once the subclass qualifies — it spends
        # nothing, it only says which effect the next Step carries — and its label is
        # the clamped selection (see `fey_rider_index`). Misty Escape is a REACTION
        # drawn inside the Bonus Action band, so spending the bonus action hides it
        # today; that is the band gate, recorded and preserved, not a rule of its own.
        if (cls == CC.Warlock and stats.warlock_subclass == rpg.WarlockSubclass.Archfey
                and lvl >= 3):
            sof = _res(stats, "Steps of the Fey")
            out.append(Action("fey_effect",
                              f"Fey Step: {_FEY_EFFECT_NAMES[fey_rider_index(app, stats)]}",
                              GROUP_BONUS))
            if sof > 0:
                out.append(Action("steps_of_fey",
                                  f"Steps of the Fey ({sof}) (Bonus)", GROUP_BONUS))
            # The panel reads `reaction_used` off the PLACED AGENT's condition copy
            # here, not through the engine, and `_utility` reads `concentrating` the
            # same way. Kept as written.
            if (lvl >= 6 and sof > 0
                    and not agents[agent_idx].conditions.reaction_used):
                out.append(Action("misty_escape",
                                  f"Misty Escape ({sof}) (React)", GROUP_BONUS))

        # ── Warrior of the Elements Monk (M2d) ──
        # Both are Magic actions, so both read `action_used` rather than the band, and
        # Attunement's label is a tick once the effect is running.
        if (cls == CC.Monk
                and stats.monk_subclass == rpg.MonkSubclass.WarriorOfFourElements):
            fp_n = _res(stats, "Focus Points")
            if lvl >= 3 and not app.action_used and fp_n >= 1:
                out.append(Action("elemental_attunement",
                                  "Elemental Attunement ✓"
                                  if cond.elemental_attunement_active
                                  else f"Elemental Attunement ({fp_n} Focus)",
                                  GROUP_BONUS))
            if lvl >= 6 and not app.action_used and fp_n >= 2:
                out.append(Action("elemental_burst",
                                  f"Elemental Burst ({fp_n} Focus)", GROUP_BONUS))

        # ── the tail: detonate, and the two summons whose label is a toggle ──
        if (cls == CC.Monk
                and stats.monk_subclass == rpg.MonkSubclass.WarriorOfTheOpenHand
                and lvl >= 17 and not app.action_used
                and app._quivering_palm_id_for(agent_idx) >= 0):
            out.append(Action("quivering_palm",
                              "💥 Detonate Quivering Palm", GROUP_BONUS))

        if (cls == CC.Ranger
                and stats.ranger_subclass == rpg.RangerSubclass.BeastMaster
                and lvl >= 3):
            out.append(Action("companion",
                              "🐾 Dismiss Companion"
                              if app._find_companion_idx(agent_idx) >= 0
                              else "🐾 Primal Companion", GROUP_BONUS))
        if cls == CC.Warlock and stats.has_invocation(18):
            out.append(Action("familiar",
                              "😈 Dismiss Familiar"
                              if app._find_familiar_idx(agent_idx) >= 0
                              else "😈 Pact Familiar", GROUP_BONUS))

        return ActionMenu._priced(out + ActionMenu._metamagic(app, stats))

    # ── §9 — visibility + drops ────────────────────────────────────────────────
    @staticmethod
    def _utility(app, agent_idx: int) -> list[Action]:
        out = [Action("place_terrain", "🌍 Place Terrain", GROUP_UTILITY)]

        agents = app.bm.placed_agents
        if not (0 <= agent_idx < len(agents)):
            return out

        if agents[agent_idx].conditions.concentrating:
            out.append(Action("drop_concentration", "Drop Concentration", GROUP_UTILITY,
                              economy=ECONOMY_FREE))

        # One drop per weapon slot that actually holds a droppable weapon. The engine
        # returns all three slots always, so "empty" is a name test, and a permanently
        # armed natural weapon (claws, a monster's bite) is not droppable at all.
        weapons = app.combat.get_agent_weapons(app.bm, agent_idx)
        for slot, (aid, label) in enumerate((("drop_weapon_main", "Drop Main"),
                                             ("drop_weapon_off",  "Drop Off"),
                                             ("drop_weapon_rng",  "Drop Rng"))):
            wpn = weapons[slot]
            if wpn.name and wpn.name != "Unnamed" and not wpn.permanently_armed:
                out.append(Action(aid, label, GROUP_UTILITY, economy=ECONOMY_FREE))
        return out
