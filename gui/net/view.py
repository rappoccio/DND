"""``GameView`` — the per-viewer read projection (MULTIPLAYER_PLAN.md M3, seam S1).

One pure function, ``build_view(app, viewer, seq=0) -> dict``: everything a single
viewer is allowed to know about the session right now, and nothing else. It is the only
thing a remote client is ever sent, so it is also the whole security model of a spectator
client — which is why ``tests/test_gameview.py`` asserts against the *serialized bytes*
rather than against fields.

**Two filters, kept apart.** The Identity section is emphatic that entitlement and
visibility are different questions and that smearing them together is the most likely way
this module leaks state:

  · **entitlement** — may this principal know a thing *if* they could perceive it at all?
    Answered by ``SessionRoster.authorize()`` and nowhere else (NN6). This module never
    reads ``Role``, never compares a principal id to ``"dm"``, and never re-derives
    ownership; it asks.
  · **visibility** — can they perceive it? That is game state, it changes every turn, and
    it is read from the same predicates the DM's own screen draws with.

Both must pass. Neither substitutes for the other: a player is entitled to a party
member's vitals and still learns nothing about an ally standing in an unexplored room.

**Omit, never send-and-hide** (wire ground rule 3). A field the viewer may not see is
absent from the dict. There is no ``"visible": false``, because a client that reads its
own network traffic must learn nothing that its screen does not already show.

**Live indices** (wire ground rule 5). Agent indices here are live ``BattleMap`` indices
and are meaningful only at the ``seq`` that carried them. D-M3-4: this is why the
projection is written out rather than lifted from ``App._save_agents`` — the save drops
summons and tombstoned agents and renumbers the survivors, so its numbering addresses a
different creature than the map does the moment a summon is out.

**Why this module imports the extension when ``roster.py`` refuses to.** The roster is
pure policy and stays importable with no pygame and no C++ so the net thread and the M0
tests can hold it. A projection of a live ``App`` has no such option: its subject *is* the
``BattleMap``. Like every other reader of the map it must run on the pygame thread (NN1).
"""

from __future__ import annotations

import os

import rpg_battle_map as rpg

from net.roster import (Action, PC_FACTION, PROTOCOL_VERSION, Principal,
                        PromptTarget, TokenTarget)

# ── What counts as a "condition" on the wire ────────────────────────────────
# `Agent::Conditions` carries ~180 fields, most of them per-turn bookkeeping for one
# class feature ("horde_breaker_used", "piercer_reroll_used_this_turn"). A client renders
# *statuses*, so this is the curated set: the SRD conditions plus the handful of states a
# token visibly is in. Anything not named here stays off the wire — a shorter list is a
# smaller leak, and a flag nobody draws is a flag nobody needs.
_WIRE_CONDITIONS = (
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated",
    "invisible", "paralyzed", "petrified", "poisoned", "prone", "restrained",
    "stunned", "unconscious", "dead", "stabilized", "hidden", "burning", "netted",
    "forcecaged", "gaseous_form", "raging", "concentrating", "dashing", "dodging",
    "disengaging",
)


def build_view(app, viewer: Principal, seq: int = 0) -> dict:
    """Project the live session as ``viewer`` is entitled and able to see it.

    ``seq`` is supplied by the caller and defaults to 0 (D-M3-1). ``EventStream`` is seam
    S3 and does not exist yet; when it lands, M4 passes its cursor through. M3 inventing a
    counter here would have created a one-field ``EventStream`` that S3 then had to
    dislodge, and ``Prompt.to_wire(seq=0)`` had already set the precedent.

    Raises ``PermissionError`` if ``viewer`` may not receive a view at all. That is a bug
    rather than a flow: the transport's middleware authorizes before it ever calls here,
    and a seated player who owns no tokens is a spectator, who passes.
    """
    roster = app.roster
    if not roster.authorize(viewer, Action.VIEW_SESSION):
        raise PermissionError("viewer is not seated")

    # The DM channel *is* the "see everything" entitlement, so it is asked for through the
    # chokepoint instead of read off `viewer.role` — A8: `Role` is read inside authorize()
    # and nowhere else, this module included.
    is_dm = roster.authorize(viewer, Action.VIEW_DM_CHANNEL)

    bm = app.bm
    # `_fog_active()` is False while a map-authoring modal is open and whenever the DM has
    # fog switched off — in both cases the DM's own screen is drawing the whole map, so
    # nothing here may hide more than it does.
    fog_on = bool(app._fog_active())
    hide_map = fog_on and not is_dm
    explored = {(c.col, c.row) for c in bm.explored_cells()}

    agents, shown = _agents(app, roster, viewer, is_dm)

    return {
        "v":       PROTOCOL_VERSION,
        "t":       "view",
        "seq":     int(seq),
        "you":     _you(app, roster, viewer, shown),
        "map":     _map(app),
        "fog":     {"active": fog_on,
                    "explored": sorted([c, r] for (c, r) in explored)},
        "combat":  _combat(app, shown),
        "agents":  agents,
        "terrain": _terrain(app, is_dm, hide_map, explored),
        "lighting": _lighting(app, is_dm, hide_map, explored),
        "effects": _effects(app, is_dm, hide_map, explored),
        "log":     list(app.combat_log),
    }


# ── Agents ──────────────────────────────────────────────────────────────────

def _agents(app, roster, viewer, is_dm: bool) -> tuple[list[dict], set[int]]:
    """The visible tokens, and the set of live indices they cover.

    The index set is returned because two other blocks have to agree with it exactly.
    Initiative is the one that matters: an order listing a creature that no token in
    ``agents`` accounts for announces an ambusher by arithmetic, which is the same leak
    the fog gate just prevented, arriving through a list of integers.

    Three gates, in the draw pass's own order:

      1. ``removed_from_play`` — a tombstoned summon is not rendered and not selectable.
      2. ``App._agent_fogged`` — D-M3-2's single home for the fog reveal rule, shared with
         ``_draw_agents``, ``_draw_agent_hover_name`` and NPC playback.
      3. ``App._npc_concealed_from_party`` — D-M3-3. An automated enemy that is Hidden, or
         Invisible with nothing in the party piercing it, is not drawn on the DM's screen
         either. The M3 filter table named only the fog gate; a view that applied only fog
         would paint, on a player's canvas, an ambusher the DM's console is deliberately
         withholding.

    A DM viewer skips gates 2 and 3: the DM sees the board.
    """
    out: list[dict] = []
    shown: set[int] = set()
    for i, pt in enumerate(bm_agents(app)):
        if pt.removed_from_play:
            continue
        if not is_dm and (app._agent_fogged(i, pt) or app._npc_concealed_from_party(i, pt)):
            continue
        out.append(_agent(app, roster, viewer, i, pt, is_dm))
        shown.add(i)
    return out, shown


def bm_agents(app):
    """``bm.placed_agents`` is a pybind11 accessor that *copies* the vector on each read.
    Bound once so a projection walking it does not rebuild it per helper."""
    return app.bm.placed_agents


def _agent(app, roster, viewer, idx: int, pt, is_dm: bool) -> dict:
    """One token, cut to what this viewer is entitled to know about it.

    Three tiers, and the roster decides which applies — not this module:

      · **sheet** (``VIEW_TOKEN_SHEET``) — owned, or the DM. AC, speeds, slots, resources.
      · **vitals** (``VIEW_TOKEN_VITALS``) — owned, any ``PC_FACTION`` token, or the DM.
        Party hit points are table information; that rule lives in ``authorize()``.
      · **neither** — an enemy the party can currently see. Position, name and a *band*.
        Never a number, never a stat block. A band is what a character at the table can
        actually tell by looking, and it is the whole reason this tier exists rather than
        simply omitting the token.

    The name rides at every tier. It has to: a token with no label cannot be drawn, and the
    DM's own screen gives it up on hover (``_draw_agent_hover_name``) under exactly the two
    gates ``_agents`` just applied.
    """
    stats = app.combat.get_agent_stats(app.bm, idx)
    sheet  = roster.authorize(viewer, Action.VIEW_TOKEN_SHEET,  TokenTarget(idx))
    vitals = roster.authorize(viewer, Action.VIEW_TOKEN_VITALS, TokenTarget(idx))

    rec = {
        "agent":   idx,
        "name":    pt.name,
        "col":     pt.origin.col,
        "row":     pt.origin.row,
        "size":    pt.size,
        "faction": pt.faction,
        "sprite":  os.path.basename(pt.sprite_path) if pt.sprite_path else "",
    }
    if roster.owns(viewer.id, idx):
        rec["yours"] = True
    if is_dm:
        # Who drives a token is DM-channel information: on an enemy it would say which
        # creatures are automated, and the party is not entitled to that.
        rec["controller"] = roster.controller_of(idx)
        rec["npc_automated"] = bool(app.bm.is_agent_npc_automated(idx))

    if vitals:
        rec["hp"] = {"cur": int(stats.hp_cur), "max": int(stats.hp_max)}
        rec["conditions"] = _conditions(pt.conditions)
    else:
        rec["hp"] = {"band": _band(stats, pt.conditions)}
        rec["conditions"] = _conditions(pt.conditions, visible_only=True)

    if sheet:
        rec["sheet"] = {
            "ac":        int(stats.base_ac),
            "speed":     {"walk":   int(stats.speed_walk),
                          "swim":   int(stats.speed_swim),
                          "fly":    int(stats.speed_fly),
                          "burrow": int(stats.speed_burrow)},
            "slots":     {"max":       [int(n) for n in stats.spell_slots_max],
                          "remaining": [int(n) for n in stats.spell_slots_remaining]},
            "resources": [{"name": r.name, "current": int(r.current), "max": int(r.max)}
                          for r in stats.resources],
        }
    return rec


def _band(stats, cond) -> str:
    """The only hit-point information an unentitled viewer gets.

    Three values, because three is what a character can read off a body across a room:
    ``"Down"`` (dead, unconscious, or at 0), ``"Bloodied"`` (at or below half) and
    ``"Healthy"``. Deliberately coarse — a four-band scale would let a client binary-search
    a creature's maximum over a few rounds of damage, which is the stat block arriving
    slowly.
    """
    if cond.dead or cond.unconscious or stats.hp_cur <= 0:
        return "Down"
    if stats.hp_cur * 2 <= stats.hp_max:
        return "Bloodied"
    return "Healthy"


def _conditions(cond, visible_only: bool = False) -> list[str]:
    """The curated condition set, as a sorted list of the ones that are set.

    ``visible_only`` is the unentitled tier: a condition you could see by looking. What it
    withholds is ``concentrating`` — knowing an enemy is holding a spell together is the
    difference between guessing and knowing where to aim, and it is not something a
    creature wears on its face.
    """
    hidden_from_strangers = {"concentrating"}
    names = [n for n in _WIRE_CONDITIONS
             if getattr(cond, n, False)
             and not (visible_only and n in hidden_from_strangers)]
    if getattr(cond, "exhaustion_level", 0):
        names.append(f"exhaustion_{int(cond.exhaustion_level)}")
    return sorted(names)


# ── You, map, combat ────────────────────────────────────────────────────────

def _you(app, roster, viewer, shown: set[int]) -> dict:
    """The viewer's own handle on the session.

    ``controls`` is intersected with the tokens actually in this view: a player whose
    character is standing in fog gets an empty list rather than an index the ``agents``
    block does not explain. The roster is still the source of ownership — this only
    declines to mention what the view does not carry.

    ``prompt_id`` is gated by ``ANSWER_PROMPT`` (D-M3-6), which is strictly stronger than
    the renderer blocklist M2 expected M3 to owe: it is scoped to the prompt's *owner*
    rather than to the widget drawing it, and it runs through the NN6 chokepoint. The
    prompt's body never rides in this envelope — only its id — so M4 owes the same gate
    again on the ``prompt`` envelope, where the body actually crosses.
    """
    live = app.prompts.live
    prompt_id = None
    if live is not None and roster.authorize(viewer, Action.ANSWER_PROMPT,
                                             PromptTarget(live.id)):
        prompt_id = live.id
    return {"principal_id": viewer.id,
            "controls": sorted(i for i in roster.controlled_by(viewer.id) if i in shown),
            "prompt_id": prompt_id}


def _map(app) -> dict:
    """Page identity and grid geometry. The image is named, never inlined: M4 serves it
    from ``GET /map.png`` so it caches by content hash instead of riding every view."""
    page = getattr(app, "dungeon_page", None)
    name = getattr(page, "id", None) or os.path.splitext(
        os.path.basename(getattr(app, "_map_path", "") or ""))[0]
    return {"page":     name,
            "cell_px":  int(app.bm.cell_pixel_size),
            "cols":     int(app.bm.grid_cols),
            "rows":     int(app.bm.grid_rows)}


def _combat(app, shown: set[int]) -> dict:
    """Turn state, with initiative cut to the tokens this view explains.

    ``turn_idx`` is deliberately *not* remapped to the filtered list. It indexes
    ``app.initiative_order``, the same basis the engine and the DM console use, and a view
    that quietly renumbered it would hand the client a number that means something else
    everywhere else in the protocol. A client shows the whose-turn marker by matching the
    agent index, not by counting rows.
    """
    return {
        "active": bool(app.combat_active),
        "paused": bool(app.combat_paused),
        "round":  int(app.round_num),
        "turn_idx": int(app.turn_idx),
        "initiative": [{"agent": e.agent_idx, "total": e.total}
                       for e in app.initiative_order if e.agent_idx in shown],
    }


# ── Map structure: terrain, lighting, effects ───────────────────────────────
#
# D-M3-5. The plan's shape said these ride "verbatim"; its filter table said unexplored
# cells are "omitted entirely". Both cannot hold. `_save_terrain` writes every region,
# every door with its lock DC and its cross-map staple target, and every ladder with the
# global coordinate it lands on — which, sent verbatim, is the floor plan of the wing the
# party has not entered. That is the same leak as sending the enemy token, arriving by a
# quieter route, so omission wins.
#
# Two independent cuts, and they are not the same cut:
#   · fog decides which CELLS a viewer hears about;
#   · the DM channel decides which FIELDS. A lock DC and a staple's destination are DM
#     information whether or not the door has been seen — the party discovers those by
#     picking the lock and by climbing the ladder.

def _visible(explored: set[tuple[int, int]], hide_map: bool, col: int, row: int) -> bool:
    return (not hide_map) or (col, row) in explored


def _terrain(app, is_dm: bool, hide_map: bool, explored) -> dict:
    """Static map structure.

    A DM viewer gets the authoring shape — the region rectangles ``_save_terrain`` writes,
    unchanged, because that is what the DM's editors round-trip.

    Everyone else gets the same information rasterized per cell and clipped to what they
    have seen. A rectangle cannot be clipped to an arbitrary explored mask without either
    leaking its true extent or lying about it, and a cell list can. Only cells that differ
    from open floor are emitted, so an ordinary room costs nothing.
    """
    out: dict = {"walls_enabled": bool(app._walls_enabled)}

    if is_dm:
        out["regions"] = list(app._terrain_regions)
    else:
        cells = []
        for col, row in _cells(app, hide_map, explored):
            cell = rpg.Cell(col, row)
            ttype = app.bm.get_terrain_type(cell)
            mult  = float(app.bm.get_terrain_multiplier(cell))
            if ttype == rpg.TerrainType.Standard and abs(mult - 1.0) < 1e-9:
                continue
            cells.append([col, row, _name(ttype), round(mult, 3)])
        out["cells"] = cells

    doors = []
    for d in app.bm.doors:
        dc = [[c.col, c.row] for c in d.cells]
        # "Any cell seen" reveals the door: a doorway is one feature, and a party that has
        # stood in half of it has seen it.
        if not any(_visible(explored, hide_map, c, r) for c, r in dc):
            continue
        rec = {"id": d.id, "cells": dc, "open": bool(d.open),
               "locked": bool(d.locked), "broken": bool(d.broken)}
        if is_dm:
            rec.update(lock_dc=d.lock_dc, break_dc=d.break_dc,
                       arcane_lock=bool(d.arcane_lock),
                       link_target=app._door_link_at(d))
        doors.append(rec)
    out["doors"] = doors

    ladders = []
    for lad in getattr(app, "_ladders", []):
        lc = [[int(c[0]), int(c[1])] for c in lad.get("cells", [])]
        if not any(_visible(explored, hide_map, c, r) for c, r in lc):
            continue
        rec = {"cells": lc}
        if is_dm:
            # Where it goes is not visible from the top of it.
            rec["target"] = [int(v) for v in lad.get("target", (0, 0, 0))]
        ladders.append(rec)
    out["ladders"] = ladders
    return out


def _lighting(app, is_dm: bool, hide_map: bool, explored) -> dict:
    """Per-cell light level, plus the active dynamic lights.

    Light is emitted only where it is not ``Clear``, and a client defaults the rest: a lit
    room is the common case and should cost nothing. ``turns_remaining`` is DM-channel —
    a player sees a torch burning, not the round it gutters out on.
    """
    cells = []
    for col, row in _cells(app, hide_map, explored):
        lvl = app.bm.get_light_level(rpg.Cell(col, row))
        if lvl == rpg.VisibilityLevel.Clear:
            continue
        cells.append([col, row, _name(lvl)])

    effects = []
    for eff in app.bm.active_light_effects:
        ec = _effect_cells(app, eff, hide_map, explored)
        if not ec:
            continue
        rec = {"id": eff.id, "name": eff.name, "cells": ec,
               "level": _name(eff.light_level)}
        if is_dm:
            rec["turns_remaining"] = eff.turns_remaining
            rec["source"] = eff.source_agent_idx
        effects.append(rec)

    return {"cells": cells, "effects": effects}


def _effects(app, is_dm: bool, hide_map: bool, explored) -> dict:
    """The temporary overlays: spell areas and terrain effects.

    Both are clipped to visible cells and dropped when nothing of them is visible. The
    spell's *name* rides, because a wall of fire looks like a wall of fire; its caster and
    its remaining duration do not, because those are read off the DM's screen and not off
    the map.
    """
    spells = []
    for eff in app.bm.active_spell_effects:
        ec = [[c.col, c.row] for c in eff.cells
              if _visible(explored, hide_map, c.col, c.row)]
        if not ec:
            continue
        rec = {"id": eff.effect_id, "name": eff.spell.name, "cells": ec}
        if is_dm:
            rec.update(caster=eff.caster_idx, turns_remaining=eff.turns_remaining,
                       cast_level=eff.cast_level)
        spells.append(rec)

    terrain = []
    for eff in app.bm.active_terrain_effects:
        ec = _effect_cells(app, eff, hide_map, explored)
        if not ec:
            continue
        rec = {"id": eff.id, "name": eff.name, "cells": ec,
               "difficulty": _name(eff.difficulty)}
        if is_dm:
            rec.update(turns_remaining=eff.turns_remaining,
                       source=eff.source_agent_idx,
                       requires_concentration=bool(eff.requires_concentration))
        terrain.append(rec)

    return {"spells": spells, "terrain": terrain}


# ── Small shared pieces ─────────────────────────────────────────────────────

def _cells(app, hide_map: bool, explored):
    """The cells this viewer may hear about, as ``(col, row)`` pairs.

    With fog up that is exactly the explored mask. With fog down it is the grid, because
    the DM's own screen is then drawing all of it and M3's rule is that a client never
    sees *more* than the console — not that it always sees less.
    """
    if hide_map:
        return sorted(explored)
    return [(c, r) for r in range(app.bm.grid_rows) for c in range(app.bm.grid_cols)]


def _effect_cells(app, eff, hide_map: bool, explored) -> list[list[int]]:
    """Decode a ``cell_indices`` footprint to visible ``[col, row]`` pairs. The engine
    stores these flat, row-major over ``grid_cols`` — the same decode ``_draw_light_effects``
    does."""
    cols = app.bm.grid_cols
    out = []
    for idx in eff.cell_indices:
        col, row = idx % cols, idx // cols
        if _visible(explored, hide_map, col, row):
            out.append([col, row])
    return out


def _name(enum_value) -> str:
    """A pybind11 enum as the bare member name — ``"Water"``, not ``"TerrainType.Water"``.
    Ground rule 4: the client treats it as an opaque string and never parses it."""
    return getattr(enum_value, "name", str(enum_value))
