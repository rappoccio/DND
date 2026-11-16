"""Lair actions on initiative count 20: Strahd's Castle Ravenloft lair (plans/STRAHD_LAIR_PLAN.md).

A creature whose stat block lists ``legendary.lair_actions`` (Stats.lair_action_names) gets a
Lair entry in initiative at count 20, after every combatant tied at 20 (a lair action loses
ties). The entry's ``agent_idx`` is -1, so ``_current_agent_idx`` reads -1 on the Lair turn: no
creature is acting, nothing searches the order by index and finds it, and the turn that
follows skips ``end_turn`` and the legendary-action phase. The lair turn offers the DM a menu
of the owner's lair actions, then advances the turn.

The four lair actions are named handlers, not a general language:
  * Phase: walls, wall edges and closed doors don't block the owner (BattleMap phasing)
    until the next Lair turn. Other floors are reached with the DM's "Send to floor…".
  * Doors: click doors the owner can see to cycle each through open / close / close + lock,
    then Enter. Using it again ends the previous locks first; the menu can also end them.
  * Apparition: a Strahd Specter appears next to a hostile creature the owner can see, makes
    one attack against it, and vanishes.
  * Shadow Theft: a Medium-or-smaller creature within 30 ft that the owner can see makes a
    DC 17 Cha save. On a failure a Strahd Shadow appears next to it, attacks it once, and
    vanishes (the D6/D7 amendment: no lasting shadow, no restoration bookkeeping).
"""

import rpg_battle_map as rpg

from helpers import can_place_agent

LAIR_INIT = 20
SPECTER = ("Strahd Specter", "Specter")    # (bestiary name, base sprite)
SHADOW = ("Strahd Shadow", "Shadow")
SHADOW_THEFT_DC = 17
SHADOW_THEFT_RANGE_FT = 30
DOOR_CYCLE = ("open", "close", "lock")     # then back to "unchanged"


# ── The Lair entry ───────────────────────────────────────────────────────────

def is_lair_entry(entry) -> bool:
    return entry.agent_idx < 0


def owner(app) -> int:
    """The creature whose lair actions the Lair turn offers: the first living combatant in
    play (not On Deck) with lair actions, or -1."""
    bm = app.bm
    for i in range(len(bm.placed_agents)):
        if bm.is_agent_removed_from_play(i) or bm.is_agent_on_deck(i):
            continue
        st = app.combat.get_agent_stats(bm, i)
        if st.hp_cur > 0 and list(st.lair_action_names):
            return i
    return -1


def ensure_entry(app, shift: bool = True):
    """Insert the Lair entry at count 20 if a lair creature is fighting and there is none.
    `shift` keeps turn_idx on the same combatant (mid-combat); at combat start it stays 0, so
    a Lair entry at the top of the order acts first."""
    order = app.initiative_order
    if app.tracker_mode or not order or any(is_lair_entry(e) for e in order):
        return
    if owner(app) < 0:
        return
    pos = next((p for p, e in enumerate(order) if e.total < LAIR_INIT), len(order))
    ne = rpg.InitiativeEntry()
    ne.agent_idx = -1
    ne.total = LAIR_INIT
    order.insert(pos, ne)
    if shift and pos <= app.turn_idx:
        app.turn_idx += 1


def ensure_tracker_entry(app):
    """Tracker mode (real dice): a "Lair" reminder row at 20, after the ties, that does
    nothing. The DM steps past it with Next. Added once the order runs, or when a lair
    creature joins a running order."""
    t = app.tracker
    if t.phase != "running" or t.index_of(-1) >= 0 or owner(app) < 0:
        return
    t.add([-1], LAIR_INIT, joins_round=t.round)


def tracker_name(app, agent_idx: int) -> str:
    """A tracker row's name: the Lair label for the reminder row, else the token's."""
    if agent_idx < 0:
        return entry_label(app)
    agents = app.bm.placed_agents
    return agents[agent_idx].name if agent_idx < len(agents) else "?"


def on_lair_turn(app) -> bool:
    order = app.initiative_order
    return (app.combat_active and not app.tracker_mode and 0 <= app.turn_idx < len(order)
            and is_lair_entry(order[app.turn_idx]))


def entry_label(app) -> str:
    o = owner(app)
    return f"Lair ({app.bm.placed_agents[o].name})" if o >= 0 else "Lair"


# ── The Lair turn ────────────────────────────────────────────────────────────

def begin_turn(app):
    """Start the Lair turn: Phase from the last one ends, then the owner's menu."""
    own = owner(app)
    reset(app)
    end_phase(app)
    if own < 0:
        app._advance_turn()
        return
    app._lair_actor = own
    app.selected_idx = own
    app._combat_log_add(f"[LAIR] Initiative {LAIR_INIT}: {app.bm.placed_agents[own].name}'s lair acts.")
    app._flush_combat_log()
    show_menu(app)


def show_menu(app):
    own = app._lair_actor
    if own < 0:
        return
    name = app.bm.placed_agents[own].name
    st = app.combat.get_agent_stats(app.bm, own)
    options = [(a, (lambda a=a: choose(app, a))) for a in st.lair_action_names]
    n_locked = sum(1 for d in app.bm.doors if d.lair_lock)
    if n_locked:
        options.append((f"End door locks ({n_locked})", lambda: end_door_locks(app)))
    options.append(("Pass", lambda: finish(app)))
    app._ask_actor(own, "action", f"{name}: lair action (initiative {LAIR_INIT})", options)


def reset(app):
    app._lair_actor = -1
    app._lair_pick = ""
    app._lair_doors = {}


def finish(app):
    """The lair action is done (or passed): on to the next combatant."""
    reset(app)
    app._flush_combat_log()
    app._update_attack_overlay()
    app._advance_turn()


def choose(app, action: str):
    own = app._lair_actor
    if own < 0:
        return
    name = app.bm.placed_agents[own].name
    key = action.strip().lower()
    if key == "phase":
        app.bm.set_agent_phasing(own, True)
        app._combat_log_add(f"{name} can pass through walls, doors, ceilings and floors "
                            f"until initiative {LAIR_INIT} of the next round.")
        finish(app)
    elif key == "doors":
        app._lair_pick = "doors"
        app._lair_doors = {}
        app._combat_log_add(f"{name}: click doors he can see to cycle open → close → close + "
                            "lock → unchanged. Enter applies, Esc goes back.")
        app._flush_combat_log()
    elif key == "apparition":
        app._lair_pick = "apparition"
        app._combat_log_add(f"{name}: click a hostile creature he can see for the apparition "
                            "to attack. Esc goes back.")
        app._flush_combat_log()
    elif key == "shadow theft":
        app._lair_pick = "shadow"
        app._combat_log_add(f"{name}: click a Medium or smaller creature within "
                            f"{SHADOW_THEFT_RANGE_FT} ft he can see. Esc goes back.")
        app._flush_combat_log()
    else:
        app._combat_log_add(f"{name}: no handler for lair action '{action}'.")
        app._flush_combat_log()
        show_menu(app)


def cancel_pick(app):
    """Esc during a lair pick: back to the menu, nothing spent."""
    app._lair_pick = ""
    app._lair_doors = {}
    show_menu(app)


def resolve_click(app, hit: int, cell, anchor=None):
    """A map click while a lair pick is armed. An invalid click keeps the pick armed."""
    mode = app._lair_pick
    if mode == "doors":
        _click_door(app, cell, anchor)
    elif mode == "apparition":
        _apparition(app, hit)
    elif mode == "shadow":
        _shadow_theft(app, hit)


# ── Phase ────────────────────────────────────────────────────────────────────

def end_phase(app):
    """Phase lasts until count 20 of the next round, and no longer than the fight."""
    for i, pt in enumerate(app.bm.placed_agents):
        if app.bm.is_agent_phasing(i):
            app.bm.set_agent_phasing(i, False)
            app._combat_log_add(f"{pt.name} can no longer pass through walls.")


# ── Doors ────────────────────────────────────────────────────────────────────

def can_see_door(app, own: int, door) -> bool:
    """Line of sight from the owner to any cell of the door, or (an edge door) to either
    cell it separates."""
    from menus.dm import door_touch_cells
    pt = app.bm.placed_agents[own]
    cells = list(door.cells) if door.cells else list(door_touch_cells(door))
    return any(app.bm.has_line_of_sight(pt.origin, pt.size, c, 1) for c in cells)


def _click_door(app, cell, anchor):
    if cell is None:
        return
    di = app._door_index_at(cell, anchor)
    if di < 0:
        return
    door = app.bm.doors[di]
    own = app._lair_actor
    if door.hidden:
        return                                   # a secret door nobody found is wall
    if not can_see_door(app, own, door):
        app._combat_log_add("Strahd can't see that door.")
        app._flush_combat_log()
        return
    cur = app._lair_doors.get(door.id)
    nxt = DOOR_CYCLE[0] if cur is None else (
        DOOR_CYCLE[DOOR_CYCLE.index(cur) + 1] if cur != DOOR_CYCLE[-1] else None)
    if door.broken and nxt in ("close", "lock"):
        nxt = None                               # a smashed door can only stay open
    if nxt is None:
        app._lair_doors.pop(door.id, None)
    else:
        app._lair_doors[door.id] = nxt
    label = {"open": "open", "close": "close", "lock": "close + lock", None: "unchanged"}[nxt]
    app._combat_log_add(f"Door #{door.id}: {label} ({len(app._lair_doors)} door(s) chosen).")
    app._flush_combat_log()


def apply_doors(app):
    """Enter: carry out the chosen door changes. Using Doors ends the earlier locks first."""
    if app._lair_pick != "doors":
        return
    bm = app.bm
    ended = bm.clear_lair_locks()
    if ended:
        app._combat_log_add(f"Strahd's earlier door locks end ({ended}).")
    for door_id, what in app._lair_doors.items():
        if what == "open":
            bm.unlock_door(door_id)
            ok = bm.open_door(door_id)
            app._combat_log_add(f"Door #{door_id} swings open." if ok else
                                f"Door #{door_id} is held by other magic and stays shut.")
        elif what == "close":
            bm.close_door(door_id)
            app._combat_log_add(f"Door #{door_id} slams shut.")
        elif what == "lock":
            bm.set_door_lair_lock(door_id, True)
            app._combat_log_add(f"Door #{door_id} slams shut and is magically locked "
                                "(DC 20 Strength to force).")
    app._mark_fog_dirty()
    finish(app)


def end_door_locks(app):
    """End the effect (free): every lair lock lifts. Back to the menu."""
    n = app.bm.clear_lair_locks()
    app._combat_log_add(f"Strahd releases his hold on {n} door(s).")
    app._flush_combat_log()
    show_menu(app)


# ── Apparition / Shadow Theft ────────────────────────────────────────────────

def _free_cell_next_to(app, target: int, own: int):
    """A free cell touching the target's footprint, the one nearest the owner, or None."""
    pt = app.bm.placed_agents[target]
    o, n = pt.origin, pt.size
    oo = app.bm.placed_agents[own].origin
    ring = [rpg.Cell(c, r)
            for r in range(o.row - 1, o.row + n + 1)
            for c in range(o.col - 1, o.col + n + 1)
            if not (o.col <= c < o.col + n and o.row <= r < o.row + n)]
    ring = [c for c in ring if can_place_agent(app.bm, c, 1)]
    if not ring:
        return None
    return min(ring, key=lambda c: (max(abs(c.col - oo.col), abs(c.row - oo.row)), c.row, c.col))


def _spawn(app, monster, cell, own: int) -> int:
    """Spawn a lair minion from the bestiary on the owner's side. Returns its index or -1."""
    import os
    name, base = monster
    rec = app.mob_stats_json.get(name)
    if not rec:
        return -1
    cfg = rpg.AgentConfig()
    cfg.name = name
    specific = os.path.join(app.sprites_dir, f"{name}.png")
    cfg.sprite_path = specific if os.path.exists(specific) else app._get_mob_sprite_path(base)
    cfg.size = 1
    cfg.start_col, cfg.start_row = cell.col, cell.row
    new = app.bm.spawn_agent(cfg)
    if new < 0:
        return -1
    app.combat.set_agent_stats(app.bm, new, app._mob_stats_to_d_d_stats(rec))
    app.combat.set_agent_weapons(app.bm, new, app._auto_weapons_from_mob_stats(rec))
    app.bm.set_agent_faction(new, app.bm.get_agent_faction(own))
    return new


def _strike_and_vanish(app, monster, target: int, own: int, verb: str):
    """Spawn the minion next to the target, make its one attack, then remove it."""
    cell = _free_cell_next_to(app, target, own)
    tname = app.bm.placed_agents[target].name
    if cell is None:
        app._combat_log_add(f"No room next to {tname} for the {monster[0]}.")
        finish(app)
        return
    new = _spawn(app, monster, cell, own)
    if new < 0:
        app._combat_log_add(f"{monster[0]} is missing from the bestiary.")
        finish(app)
        return
    app._combat_log_add(f"{verb} {tname}!")
    a = rpg.Attack(new, target, 0)
    a.attack_slot = "legendary"          # out of turn: no action economy
    app._reaction_finish = lambda: _vanish(app, new)
    status = app.combat.begin_attack(app.bm, a)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision:
        app._show_pending_reaction_menu()   # Shield etc.; resumes via _reaction_finish
    else:
        _vanish(app, new)


def _vanish(app, new: int):
    app.bm.set_agent_removed_from_play(new, True)
    app._combat_log_add(f"The {app.bm.placed_agents[new].name} vanishes.")
    app._sync_spell_effect_cache()
    finish(app)


def _visible(app, own: int, target: int) -> bool:
    a, b = app.bm.placed_agents[own], app.bm.placed_agents[target]
    return app.bm.has_line_of_sight(a.origin, a.size, b.origin, b.size)


def _valid_target(app, own: int, hit: int) -> bool:
    agents = app.bm.placed_agents
    if not (0 <= hit < len(agents)) or hit == own or app.bm.is_agent_removed_from_play(hit):
        return False
    return app.combat.get_agent_stats(app.bm, hit).hp_cur > 0


def _apparition(app, hit: int):
    own = app._lair_actor
    if not _valid_target(app, own, hit) or app._are_allies(own, hit):
        app._combat_log_add("Pick a living hostile creature.")
        app._flush_combat_log()
        return
    if not _visible(app, own, hit):
        app._combat_log_add("Strahd can't see that creature.")
        app._flush_combat_log()
        return
    app._lair_pick = ""
    _strike_and_vanish(app, SPECTER, hit, own,
                       "The angry spirit of one who died in the castle rises beside")


def shadow_theft_refusal(app, own: int, hit: int) -> str:
    """Why `hit` can't be targeted by Shadow Theft, or "" if it can."""
    if not _valid_target(app, own, hit):
        return "Pick a living creature."
    if app.bm.placed_agents[hit].size > 1:
        return "Only a Medium or smaller creature."
    if app.combat.get_agent_stats(app.bm, hit).is_vampire:
        return "A vampire casts no shadow."
    if app._footprint_dist_ft(own, hit) > SHADOW_THEFT_RANGE_FT:
        return f"Out of range ({SHADOW_THEFT_RANGE_FT} ft)."
    if not _visible(app, own, hit):
        return "Strahd can't see that creature's shadow."
    return ""


def _shadow_theft(app, hit: int):
    own = app._lair_actor
    why = shadow_theft_refusal(app, own, hit)
    if why:
        app._combat_log_add(why)
        app._flush_combat_log()
        return
    app._lair_pick = ""
    saved = app.combat.roll_fixed_dc_save(app.bm, hit, rpg.SaveAbility.SaveCha,
                                          SHADOW_THEFT_DC, "Shadow Theft")
    app._flush_combat_log()
    if saved:
        app._combat_log_add(f"{app.bm.placed_agents[hit].name}'s shadow stays put.")
        finish(app)
        return
    _strike_and_vanish(app, SHADOW, hit, own, "The shadow tears loose and turns on")
