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

from dataclasses import dataclass

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
BUILT_GROUPS = (GROUP_SESSION, GROUP_TURN, GROUP_ACTION, GROUP_PORTENT, GROUP_UTILITY)

# Step 0.5's `expects` vocabulary, repeated rather than imported: `prompts.py` owns the
# wire and must not grow a dependency on the panel model. Keep the two in step.
EXPECTS = ("choice", "cell", "agent", "none")


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
    """
    id: str
    label: str
    group: str
    enabled: bool = True
    disabled_reason: str = ""
    expects: str = "none"


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
        out += ActionMenu._utility(app, agent_idx)
        return out

    # ── §1 — DM tools ──────────────────────────────────────────────────────────
    @staticmethod
    def _session(app) -> list[Action]:
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
                return [Action("nick", "🗡 Nick: Off-hand Atk", GROUP_ACTION)]
            return []

        if cond.frightened:
            return [Action("dash", "Dash", GROUP_ACTION)]   # arm 3 — Dash or nothing

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
                              GROUP_ACTION))
        out.append(Action("unarmed", "👊 Unarmed", GROUP_ACTION))

        out += [Action("dash",      "Dash",      GROUP_ACTION),
                Action("dodge",     "Dodge",     GROUP_ACTION),
                Action("disengage", "Disengage", GROUP_ACTION),
                Action("hide",      "Hide",      GROUP_ACTION)]
        # Always exactly one of these two: the fifth column of that row is "change
        # your posture", and `prone` only decides which way it points. Build order is
        # what puts it in that column, so it is appended last of the five.
        out.append(Action("standup", "Stand Up", GROUP_ACTION) if cond.prone
                   else Action("prone", "Go Prone", GROUP_ACTION))

        if len(app.combat.get_agent_spells(app.bm, agent_idx)) > 0:
            out.append(Action("spell_action", "✨ Cast Spell", GROUP_ACTION))
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
        return [Action("use_portent", "Use Portent Die", GROUP_PORTENT)]

    # ── §9 — visibility + drops ────────────────────────────────────────────────
    @staticmethod
    def _utility(app, agent_idx: int) -> list[Action]:
        out = [Action("place_terrain", "🌍 Place Terrain", GROUP_UTILITY)]

        agents = app.bm.placed_agents
        if not (0 <= agent_idx < len(agents)):
            return out

        if agents[agent_idx].conditions.concentrating:
            out.append(Action("drop_concentration", "Drop Concentration", GROUP_UTILITY))

        # One drop per weapon slot that actually holds a droppable weapon. The engine
        # returns all three slots always, so "empty" is a name test, and a permanently
        # armed natural weapon (claws, a monster's bite) is not droppable at all.
        weapons = app.combat.get_agent_weapons(app.bm, agent_idx)
        for slot, (aid, label) in enumerate((("drop_weapon_main", "Drop Main"),
                                             ("drop_weapon_off",  "Drop Off"),
                                             ("drop_weapon_rng",  "Drop Rng"))):
            wpn = weapons[slot]
            if wpn.name and wpn.name != "Unnamed" and not wpn.permanently_armed:
                out.append(Action(aid, label, GROUP_UTILITY))
        return out
