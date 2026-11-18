"""Initiative & lair turns: combat start and end, the DM's initiative tracker, Tides of
Chaos on Initiative, encounter XP, On Deck reserves and mob clearing, Thief's Reflexes,
turn advance and turn start, and the legendary-action phase between turns.

Moved out of `App` in APP_REFACTOR_PLAN.md A1.4. Module-level functions taking the app,
the pattern `menus/*.py`, `app_board_render.py` and `app_dungeon_pages.py` already use.
`combat`, `bm`, `tracker`, `initiative_order` and the rest of the turn state stay on
`app` (D3). The lair's own turn lives in `lair.py`, the tracker's sheet in `tracker.py`.

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`menus/panel.py`, `menus/board.py`, `menus/features.py`, `lair.py`,
`tracker.py`, `arena.py`, `autosave.py`, `saves.py`, `replay.py`, `app_dungeon_pages.py`,
tests) or passed as a bound callback (`_advance_turn`, `_finish_turn_start`,
`_tracker_total_ok`). Calls between those go through the forwarder (`app._advance_turn()`),
so a test that wraps one on the instance still sees every call; the rest are called
directly.

Stayed on `App`: `_reset_turn_economy` (shared with the autosave restore, and A3's
territory), `_clear_pending_target_picks` and the pick machine (A2), the NPC driver.
"""

import time

import pygame

import rpg_battle_map as rpg

import autosave
import lair
import saves
from constants import PC_FACTION
from menus import features
from tracker import Tracker
from widgets import edit_line
from xp import compute_encounter_xp, level_for_xp, xp_for_level


def start_combat(app):
    """Begin Combat: ask each eligible Wild Magic Sorcerer whether to spend Tides of
    Chaos on Initiative, then roll initiative and enter combat mode.

    The asks are prompts, so they are answered later (a remote player answers in the
    browser); combat begins from the last answer's callback. With no one to ask it
    begins at once, exactly as before. The asks go one at a time because a prompt with
    no parent supersedes whatever is live. A Start click while asks are pending does
    not start a second combat: it re-asks the current question if something else on
    the console superseded it, and is otherwise ignored."""
    if not app.bm.placed_agents:
        return
    pending = getattr(app, "_tides_start", None)
    if pending is not None:
        if not pending["prompt"].is_live:
            # Re-asked against today's board: an agent who has since left it, or lost
            # the use, is skipped rather than asked about.
            still = set(tides_initiative_candidates(app))
            ask_tides_initiative(app, [i for i in pending["queue"] if i in still])
        return
    app._tides_initiative_armed = []
    queue = tides_initiative_candidates(app)
    if queue:
        ask_tides_initiative(app, queue)
    else:
        app._begin_combat()


def begin_encounter(app):
    """Tracker mode's Begin Encounter (plans/INITIATIVE_TRACKER_PLAN.md T3). Reveal and
    bench as _begin_combat does, then open the initiative sheet: every in-play token
    gets an entry with a blank total for the DM to type in.

    combat_active goes on, so the combat panel (which holds the sheet) is drawn and the
    setup tools are put away, but the engine's turn loop never starts: no roll, no
    recording, no _proceed_to_new_turn. initiative_order stays empty until Start, so
    _current_agent_idx() is -1 while the totals are collected."""
    if not app.bm.placed_agents:
        return
    app._mark_fog_dirty()
    app._refresh_fog()
    app._bench_unrevealed_enemies()
    bm = app.bm
    in_play = [i for i, pt in enumerate(bm.placed_agents)
               if not pt.removed_from_play and not bm.is_agent_on_deck(i)
               and (pt.faction == PC_FACTION
                    or app.combat.get_agent_stats(bm, i).hp_cur > 0)]
    if not in_play:
        app._flash_status("Nothing in play to track")
        return
    app.tracker = Tracker()
    app.tracker.add(in_play)
    app.tracker.phase = "collecting"
    app._tracker_edit = None
    app._tracker_hp = -1
    app.combat_active       = True
    app._open_sim_trace(resumed=False)
    app._fight_started      = time.time()
    app._seen_armed         = set()
    app.combat_paused       = False
    app.initiative_scroll_offset = 0
    app.combat_panel_scroll = 0
    app._initiative_autopaged_turn = -1
    app.combat_log          = []
    app.combat_log_wire.clear()
    app._combat_log_file    = "combat_log.txt"
    with open(app._combat_log_file, "w") as f:
        f.write("=== ENCOUNTER LOG (tracker mode) ===\n")
    app._mirror_tracker()
    app._combat_log_add(f"Encounter begins with {len(in_play)} in play: enter initiative.")


def tracker_rows(app) -> list:
    """The initiative sheet's rows while collecting: (label, [agent_idx…], is_pc). A PC
    is a row of its own; non-party tokens sharing a name are one row and one roll (D3),
    labelled "Ghoul ×3". Removed entries are left out. Rows follow entry order."""
    rows, by_name = [], {}
    agents = app.bm.placed_agents
    for e in app.tracker.entries:
        if e.removed or e.agent_idx < 0:     # the Lair reminder row has no total to type
            continue
        pt = agents[e.agent_idx]
        if pt.faction == PC_FACTION:
            rows.append([pt.name, [e.agent_idx], True])
        elif pt.name in by_name:
            by_name[pt.name][1].append(e.agent_idx)
        else:
            by_name[pt.name] = [pt.name, [e.agent_idx], False]
            rows.append(by_name[pt.name])
    return [(f"{n} ×{len(ix)}" if len(ix) > 1 else n, ix, pc) for n, ix, pc in rows]


def tracker_roll(app, agent_idx: int) -> int:
    """One initiative roll for `agent_idx`'s group: its d20 + modifier."""
    return app.combat.roll_initiative_for(app.bm, agent_idx).total


def tracker_roll_monsters(app):
    """Roll for monsters (D3): one roll_initiative_for per non-party row, filling only
    the blank totals in it. A total the DM typed is never overwritten."""
    t = app.tracker
    if t.phase != "collecting":
        return
    for label, idxs, pc in app._tracker_rows():
        blanks = [i for i in idxs if t.entry(i).total is None]
        if pc or not blanks:
            continue
        total = app._tracker_roll(idxs[0])
        for i in blanks:
            t.set_total(i, total)
        app._combat_log_add(f"{label} rolls initiative {total}.")


def tracker_start(app):
    """Start: sort the typed-in totals (blanks sink to the bottom) and hand round 1 to
    the top of the order."""
    t = app.tracker
    if t.phase != "collecting":
        return
    app._tracker_edit = None
    first = t.start()
    lair.ensure_tracker_entry(app)   # the "Lair" reminder row at 20 (does nothing)
    first = t.current()
    app._mirror_tracker()
    if first is not None:
        app._combat_log_add(f"Round 1: {lair.tracker_name(app, first)} acts first.")
    tracker_save_turn(app)


def tracker_save_turn(app):
    """T6: the turn-boundary saves a running fight writes in _finish_turn_start (the
    autosave ring and the run's turn save), which tracker mode never reaches. A
    restore lands on the top of this turn: the order, the ▶, the round and the HP."""
    if app.autosave_enabled:
        autosave.save(app)
        saves.save_turn(app)


def tracker_step(app, delta: int):
    """Next (+1) / Prev (−1). Tokens tombstoned off the board (_clear_mob) leave the
    order first, so the turn never lands on one."""
    t = app.tracker
    if t.phase != "running":
        return
    for e in t.entries:
        if not e.removed and e.agent_idx >= 0 \
                and app.bm.is_agent_removed_from_play(e.agent_idx):
            t.remove(e.agent_idx)
    rnd = t.round
    idx = t.next() if delta > 0 else t.prev()
    if idx is None:
        return
    app._mirror_tracker()
    app._mark_fog_dirty()
    if t.round > rnd:
        app._combat_log_add(f"Round {t.round}: {lair.tracker_name(app, idx)} is up.")
    tracker_save_turn(app)


def tracker_move(app, agent_idx: int, delta: int):
    """↑ / ↓ on a row: swap it with its neighbour (a manual fix or a delayed turn)."""
    if app.tracker.move(agent_idx, delta):
        app._mirror_tracker()


def tracker_join(app, idxs, label):
    """On Deck tokens joining a tracked encounter. While the totals are collected they
    join with blank totals, to be typed in with everyone else. Once it runs (D5, as
    amended) the group rolls once and goes straight into the order at that total."""
    t = app.tracker
    n = len(idxs)
    who = f"{label} ×{n} join" if n > 1 else f"{label} joins"
    if t.phase == "running":
        total = app._tracker_roll(idxs[0])
        t.add(idxs, total, joins_round=t.round)
        lair.ensure_tracker_entry(app)   # a lair creature joining brings its Lair row
        app._mirror_tracker()
        app._combat_log_add(f"{who} at {total}.")
    else:
        t.add(idxs)
        app._combat_log_add(f"{who} the encounter: enter initiative.")


def tracker_total_ok(s: str) -> bool:
    """What an initiative field accepts: blank, or an optional minus and two digits."""
    d = s[1:] if s.startswith("-") else s
    return len(d) <= 2 and (d == "" or d.isdigit())


def tracker_handle_event(app, event) -> bool:
    """The initiative sheet's clicks and typing. Returns True when the event was the
    sheet's. A click anywhere else closes the field being typed into and passes on."""
    if not (app.tracker_mode and app.combat_active):
        return False
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        hit = next(((k, a) for r, k, a in app._tracker_hits
                    if r.collidepoint(event.pos)), None)
        app._tracker_edit = None
        if hit is None:
            return False
        kind, arg = hit
        if kind == "field":
            tracker_open_field(app, arg)
        elif kind == "roll":
            tracker_roll_monsters(app)
        elif kind == "start":
            app._tracker_start()
        elif kind in ("next", "prev"):
            app._tracker_step(1 if kind == "next" else -1)
        elif kind in ("up", "down"):
            tracker_move(app, arg, -1 if kind == "up" else 1)
        elif kind == "row":
            tracker_select(app, arg)
        elif kind == "dm_view":
            app._set_dm_view(not app.dm_view)
        elif kind == "hp_close":
            app._tracker_hp = -1
        elif kind == "hp":
            tracker_hp_apply(app, arg)
        return True
    if event.type == pygame.KEYDOWN and app._tracker_edit is None and app._tracker_hp >= 0:
        if event.key == pygame.K_ESCAPE:
            app._tracker_hp = -1
            return True
        text, _, handled = edit_line(app._tracker_hp_text, None, event,
                                     accept=lambda s: len(s) <= 3 and (s == "" or s.isdigit()))
        app._tracker_hp_text = text
        return handled
    if event.type == pygame.KEYDOWN and app._tracker_edit is not None:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
            keys = [tuple(ix) for _, ix, _ in app._tracker_rows()]
            pos = keys.index(app._tracker_edit) if app._tracker_edit in keys else -1
            app._tracker_edit = None
            if 0 <= pos < len(keys) - 1:
                tracker_open_field(app, keys[pos + 1])
        elif event.key == pygame.K_ESCAPE:
            app._tracker_edit = None
        else:
            text, _, _ = edit_line(app._tracker_edit_text, None, event,
                                   accept=app._tracker_total_ok)
            app._tracker_edit_text = text
            total = int(text) if text not in ("", "-") else None
            for i in app._tracker_edit:
                app.tracker.set_total(i, total)
        return True
    return False


def tracker_select(app, agent_idx: int):
    """The DM clicks a name in the order or a token on the map: the ▶ goes to it (once
    the order is running and it is in it) and its HP box opens. A box already open on
    it keeps its typed amount."""
    was = app.tracker.current()
    if app.tracker.jump(agent_idx) and app.tracker.current() != was:
        app._mirror_tracker()
        app._mark_fog_dirty()
        tracker_save_turn(app)
    if app._tracker_hp != agent_idx and agent_idx >= 0:
        tracker_hp_open(app, agent_idx)


def tracker_hp_open(app, agent_idx: int):
    """Open the HP box (T4) on `agent_idx`, with an empty amount."""
    app._tracker_edit = None
    app._tracker_hp = agent_idx
    app._tracker_hp_text = ""


def tracker_hp_shown(app, agent_idx: int) -> bool:
    """D1: the table view shows party HP only; DM view shows every number."""
    return app.dm_view or app.bm.placed_agents[agent_idx].faction == PC_FACTION


def tracker_hp_apply(app, op: str):
    """Apply the HP box's typed amount to its token: "dmg" (temp HP absorbs it first,
    then HP, down to 0), "heal" (up to max), "temp" (set temp HP), "max" (set max HP,
    current clamped to it). One log line per change. A monster at 0 leaves the board
    and the order (D4, through _clear_mob); a PC at 0 stays and keeps its turn."""
    idx, text = app._tracker_hp, app._tracker_hp_text
    if idx < 0 or not text.isdigit():
        return
    n = int(text)
    bm = app.bm
    pt = bm.placed_agents[idx]
    s = app.combat.get_agent_stats(bm, idx)
    if op == "dmg":
        soak = min(s.temp_hp, n)
        s.temp_hp -= soak
        s.hp_cur = max(0, s.hp_cur - (n - soak))
        msg = f"{pt.name} takes {n} damage" + (f" ({soak} to temp HP)" if soak else "")
    elif op == "heal":
        s.hp_cur = min(s.hp_max, s.hp_cur + n)
        msg = f"{pt.name} heals {n}"
    elif op == "temp":
        s.temp_hp = n
        msg = f"{pt.name} has {n} temp HP"
    elif op == "max":
        s.hp_max = max(1, n)
        s.hp_cur = min(s.hp_cur, s.hp_max)
        msg = f"{pt.name}'s max HP changes"
    else:
        return
    app.combat.set_agent_stats(bm, idx, s)
    app._tracker_hp_text = ""
    if app._tracker_hp_shown(idx):
        msg += f": {s.hp_cur}/{s.hp_max} HP" + (f" +{s.temp_hp} temp" if s.temp_hp else "")
    app._combat_log_add(msg + ".")
    if s.hp_cur <= 0 and pt.faction != PC_FACTION:
        app._tracker_hp = -1
        app._clear_mob(idx)
        if app.tracker.remove(idx):     # _clear_mob already stepped past it if it acted
            app._mirror_tracker()
    app._flush_combat_log()


def tracker_open_field(app, key):
    """Start typing into the row keyed by `key` (its agent idxs), showing its total."""
    e = app.tracker.entry(key[0])
    app._tracker_edit = key
    app._tracker_edit_text = "" if e is None or e.total is None else str(e.total)


def mirror_tracker(app):
    """Copy app.tracker into initiative_order / turn_idx / round_num, so the existing
    initiative drawing shows the typed-in order. Removed entries (D4) are left out; a
    blank total reads 0. round_num is 0-based here, the tracker's round 1-based. Until
    Start the order is empty, so nobody is acting while the totals are collected."""
    t = app.tracker
    order, turn = [], None
    for i, e in enumerate(t.entries if t.phase == "running" else []):
        if e.removed:
            continue
        if turn is None and i >= t.turn:
            turn = len(order)       # the acting entry, or the first live one after it
        ie = rpg.InitiativeEntry()
        ie.agent_idx = e.agent_idx
        ie.total     = e.total if e.total is not None else 0
        order.append(ie)
    app.initiative_order = order
    app.turn_idx         = turn or 0
    app.round_num      = max(0, t.round - 1)


def tides_initiative_candidates(app) -> list:
    """PCs who may spend Tides of Chaos on Initiative: a living, deployed L3+ Wild Magic
    Sorcerer with a use left (the engine's `arm_tides_for_initiative` check). NPCs are
    never asked."""
    CC, SS = rpg.CharacterClass, rpg.SorcererSubclass
    out = []
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.faction != PC_FACTION or app.bm.is_agent_on_deck(i):
            continue
        s = app.combat.get_agent_stats(app.bm, i)
        if s.hp_cur <= 0 or not s.has_class(CC.Sorcerer):
            continue
        if s.sorcerer_subclass != SS.WildMagic or s.class_level(CC.Sorcerer) < 3:
            continue
        tides = s.get_resource("Tides of Chaos")
        if tides is not None and tides.current >= 1:
            out.append(i)
    return out


def ask_tides_initiative(app, queue: list):
    """Ask ``queue[0]`` about Tides of Chaos on Initiative, then the rest; begin combat
    after the last answer. A reaction prompt, so a seated player's question carries the
    table's reaction timer and expiry counts as No: an absent player cannot hold up the
    start of combat. Cancel is No too."""
    if not queue:
        app._tides_start = None
        app._begin_combat()
        return
    idx, rest = queue[0], queue[1:]
    answered = []

    def answer(use: bool):
        if answered:
            return
        answered.append(use)
        if use and app.combat.arm_tides_for_initiative(app.bm, idx):
            app._tides_initiative_armed.append(idx)
        ask_tides_initiative(app, rest)

    prompt = app._ask_actor(
        idx, "reaction",
        "Use Tides of Chaos for Initiative?",
        [("Yes", lambda: answer(True)), ("No", lambda: answer(False))],
        render="titled", on_cancel=lambda: answer(False))
    app._tides_start = {"queue": queue, "prompt": prompt}


def begin_combat(app):
    """Roll initiative and enter combat mode."""
    if not app.bm.placed_agents:
        return
    app._mark_fog_dirty()   # combat start: reveal from the party's opening positions
    # Reveal now, not next frame, so the bench below reads the party's opening sight;
    # then creatures in rooms nobody has seen sit On Deck until their room is revealed.
    app._refresh_fog()
    app._bench_unrevealed_enemies()
    order = list(app.combat.roll_initiative(app.bm))
    if not order:
        return
    # Superior Inspiration (Bard L18+): top up Bardic Inspiration to 2 at combat start.
    # RNG-free, so it doesn't perturb the dice stream; applied before recording begins
    # (replay.py mirrors this) so checked replays stay in sync.
    app.combat.apply_superior_inspiration(app.bm)
    app.initiative_order    = order
    app.combat_active       = True
    app._open_sim_trace(resumed=False)          # before anything logs (sim_trace.py)
    app._fight_started      = time.time()      # names this fight's saves (gui/saves.py)
    app._seen_armed         = set()
    app.combat_paused       = False
    app.show_terrain        = True   # always show terrain during combat
    app.safe_target_edit_idx = -1  # exit any safe-target editing when combat starts
    app.turn_idx            = 0
    app.round_num           = 0
    app.initiative_scroll_offset = 0  # reset initiative scroll when combat starts
    app.combat_panel_scroll = 0       # combat panel opens at the top
    app._initiative_autopaged_turn = -1  # re-arm auto-paging for the new combat
    # Thief's Reflexes (Rogue Thief L17): a second turn during the first round at Initiative-10.
    apply_thief_reflexes(app)
    app.action_used          = False
    app.bonus_used           = False
    app.attack_seq.remaining      = 0
    app._clear_pending_target_picks()   # all armed target-pick flags (L36)
    app.pending                   = None   # and whichever base mode is armed
    app.pending_dispel_selection  = None
    app.combat_log                = []
    app.combat_log_wire.clear()
    # Initialize combat log file
    app._combat_log_file = "combat_log.txt"
    # Initialize replay log file. Header carries the seed; the RecordingCombat
    # wrapper then appends one JSON event per engine call (with a state snapshot)
    # for deterministic checked replay (see replay.py / replay_record.py).
    app.replay_log_file = "replay_log.txt"
    with open(app.replay_log_file, "w") as f:
        f.write(f"=== COMBAT REPLAY LOG ===\n")
        f.write(f"Checked replay:  python3 replay.py <map_image> [replay_log.txt]\n")
        f.write(f"\nSEED: {app.combat_seed}\n")
        # Tides of Chaos spent on Initiative, armed before the roll: replay.py re-arms
        # them so its initiative draws the same extra d20s.
        f.write(f"TIDES_INITIATIVE: {list(getattr(app, '_tides_initiative_armed', []))}\n")
        f.write(f"INITIATIVE: {[(app.bm.placed_agents[e.agent_idx].name, e.total) for e in order]}\n")
        f.write(f"\n=== EVENTS (JSON) ===\n")
    # Begin recording every engine mutation through the wrapper.
    app.combat.start_recording(app.replay_log_file, app.bm)
    with open(app._combat_log_file, "w") as f:
        f.write("=== COMBAT LOG ===\n")
        f.write(f"Seed: {app.combat_seed}\n")
    app._effect_meta         = {}
    app.bm.clear_terrain_effects()
    # Apply armor multipliers for all agents at combat start
    for i in range(len(app.bm.placed_agents)):
        app.combat.apply_armor_multipliers(app.bm, i)
        # Clear the per-combat "has taken a turn" marker (drives Assassin's Assassinate
        # Advantage vs creatures that haven't acted yet). beginTurn re-sets it each turn.
        cond = app.combat.get_agent_conditions(app.bm, i)
        # Also clear Warrior of the Elements' Elemental Attunement (a per-encounter marker; the
        # unarmed damage override it sets is reset in initializeClassResources). Re-activate each combat.
        if cond.has_taken_turn_this_combat or cond.elemental_attunement_active:
            cond.has_taken_turn_this_combat = False
            cond.elemental_attunement_active = False
            app.combat.set_agent_conditions(app.bm, i, cond)
    # A lair creature's Lair entry at count 20 (lair.py): turn_idx stays 0, so it can act first.
    lair.ensure_entry(app, shift=False)
    first = app._current_agent_idx()
    print(f"[COMBAT START] Initiative order: {[(e.total, app.bm.placed_agents[e.agent_idx].name if e.agent_idx >= 0 else 'Lair') for e in order]}")
    print(f"[COMBAT START] First turn: agent_idx={first}, name={app.bm.placed_agents[first].name if 0 <= first < len(app.bm.placed_agents) else '?'}")
    # Begin the first combatant's turn through the SAME path as every later turn
    # (_proceed_to_new_turn → begin_turn_flow → _finish_turn_start). This runs C++ beginTurn
    # (condition reset + movement-budget seed + turn-start reaction window) and, crucially, arms
    # the NPC-automation driver (_npc_drive_idx) for the first combatant. Hand-rolling the first
    # turn here used to skip all of that, so an automated NPC acting first would sit idle until
    # initiative wrapped back to it ("waited a round before acting").
    app._proceed_to_new_turn()


def agent_cr(app, idx: int):
    """Challenge Rating string for a placed agent, or None if unknown (PCs,
    custom-named tokens). Looks up the bestiary by name, stripping a trailing
    copy number ("Goblin 2" → "Goblin") added by _unique_agent_name."""
    if not (0 <= idx < len(app.bm.placed_agents)):
        return None
    name = app.bm.placed_agents[idx].name
    cr = app._cr_by_name.get(name)
    if cr is None:
        base = name.rsplit(" ", 1)
        if len(base) == 2 and base[1].isdigit():
            cr = app._cr_by_name.get(base[0])
    return cr


def award_encounter_xp(app):
    """Tally XP for enemies of the party defeated since the last tally, log the
    award, and roll it into the session's cumulative party total. Called when
    combat ends. Awards are per-corpse-once (see _xp_awarded_agents)."""
    newly_crs = []          # CRs of enemies defeated this combat
    for i, pt in enumerate(app.bm.placed_agents):
        if i in app._xp_awarded_agents:
            continue
        if pt.faction == PC_FACTION:
            continue        # party members / their summons never grant XP
        # Defeated = dead corpse or dropped to 0 HP.
        down = pt.conditions.dead or \
            app.combat.get_agent_stats(app.bm, i).hp_cur <= 0
        if not down:
            continue
        cr = agent_cr(app, i)
        if cr is None:
            continue        # no CR on record → not a rated monster, skip
        newly_crs.append(cr)
        app._xp_awarded_agents.add(i)

    if not newly_crs:
        return
    old_total = party_xp_total(app)
    result = compute_encounter_xp(newly_crs)
    app.party_xp_earned += result["total_xp"]
    new_total = party_xp_total(app)
    mult = result["multiplier"]
    mult_str = "" if abs(mult - 1.0) < 1e-6 else f" ×{mult:g}"
    app._combat_log_add(
        f"⚔ XP earned: {result['total_xp']} "
        f"({result['count']} defeated, {result['base_xp']} base{mult_str}) "
        f"— party total {new_total}")
    announce_level_ups(app, old_total, new_total)


def ensure_xp_baseline(app) -> int:
    """Lock the XP tracker's starting point to the party's current level the
    first time a party is known, so the running total begins at the characters'
    level — the XP already required to reach it — rather than 0. Frozen once
    set, so later manual level-ups don't re-inflate it. Uses the lowest PC
    level so no member is overstated and no spurious level-up is announced for
    a higher-level member."""
    if app.party_xp_baseline is None:
        levels = []
        for i, pt in enumerate(app.bm.placed_agents):
            if pt.faction != PC_FACTION:
                continue
            stats = app.combat.get_agent_stats(app.bm, i)
            if getattr(stats, "is_npc", False):
                continue        # PC-faction summons/pets are not characters
            levels.append(stats.char_level)
        if levels:
            app.party_xp_baseline = xp_for_level(min(levels))
    return app.party_xp_baseline or 0


def party_xp_total(app) -> int:
    """Cumulative party XP shown by the tracker: the level-baseline (the party's
    starting level) plus XP earned from enemies defeated this session."""
    return ensure_xp_baseline(app) + app.party_xp_earned


def announce_level_ups(app, old_total: int, new_total: int):
    """If the party's cumulative XP just crossed one or more Character
    Advancement thresholds (SRD 5.2), pop up a message naming every party
    member (PC) who is now eligible to gain a level. A PC can advance when
    the party's XP total reaches the threshold for the level above their
    current char_level. Purely advisory — leveling itself stays manual."""
    # No new tier crossed → nothing to announce (avoids repeat popups).
    if level_for_xp(new_total) <= level_for_xp(old_total):
        return
    eligible = []          # (name, current_level, attainable_level)
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.faction != PC_FACTION:
            continue        # only actual party members level up
        stats = app.combat.get_agent_stats(app.bm, i)
        if getattr(stats, "is_npc", False):
            continue        # PC-faction summons/pets are not characters
        cur = stats.char_level
        attainable = level_for_xp(new_total)
        if attainable > cur:
            eligible.append((pt.name, cur, attainable))

    if not eligible:
        return
    lines = ["⭐ Level Up!",
             f"Party XP total {new_total:,} reached a new tier."]
    for name, cur, attainable in eligible:
        need = xp_for_level(attainable)
        lines.append(f"{name}: level {cur} → {attainable}  (needs {need:,} XP)")
        app._combat_log_add(
            f"⭐ {name} can advance to level {attainable} "
            f"(party XP {new_total:,} ≥ {need:,}).")
    app._modal_message(lines)


def end_combat(app, award_xp: bool = True):
    """Leave combat mode and clear all combat state. ``award_xp`` is False when the
    fight is being thrown away (Reset Dungeon), not finished."""
    # Award XP for enemies defeated this combat before combat state is cleared.
    if award_xp:
        app._award_encounter_xp()
    app._close_sim_trace("end" if award_xp else "discarded")
    app.move_remaining_walk   = 0
    app.move_remaining_fly    = 0
    app.move_remaining_swim   = 0
    app.move_remaining_burrow = 0
    app.move_type             = rpg.MovementType.Walk
    app.combat_active         = False
    lair.end_phase(app)                 # Phase never outlasts the fight
    lair.reset(app)
    app._fight_started        = None
    app._seen_armed           = set()
    app.combat_paused         = False
    app.initiative_order    = []
    app.tracker             = Tracker()       # tracker mode's sheet goes with it
    app._tracker_hits       = []
    app._tracker_hp         = -1
    app.dm_view             = False           # its toggle lives on the sheet
    app._tracker_edit       = None
    app.initiative_scroll_offset = 0  # reset scroll when combat ends
    app.combat_panel_scroll = 0
    app.turn_idx            = 0
    app.round_num           = 0
    app.action_used          = False
    app.bonus_used           = False
    app.attack_seq.remaining      = 0
    app._clear_pending_target_picks()   # all armed target-pick flags (L36)
    app.pending                   = None   # and whichever base mode is armed
    app.pending_dispel_selection  = None
    app.selected_idx              = -1
    app._reach_walk         = []
    app._reach_fly          = []
    app._reach_set          = set()
    app._effect_meta         = {}
    app._spell_metadata      = {}
    app.combat.clear_all_concentration(app.bm)  # drop lingering concentration on all agents
    app.combat.clear_wild_magic_surge_effects(app.bm)  # 1-minute surge bands end with the fight
    app.combat.stop_recording()                  # finish the replay event log
    app.bm.clear_terrain_effects()
    app.bm.clear_spell_effects()
    app._attack_cells_melee = []
    app._attack_cells_rnorm = []
    app._attack_cells_rlong = []


# ── On Deck (phased-battle reinforcements) ─────────────────────────────
def on_deck_groups(app):
    """Reserves grouped by name, in first-placed order: list of (name, count).
    Tombstoned (dismissed) agents are excluded."""
    groups = {}          # name -> count
    order  = []          # names in first-seen order
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.removed_from_play or not app.bm.is_agent_on_deck(i):
            continue
        if pt.name not in groups:
            order.append(pt.name)
            groups[pt.name] = 0
        groups[pt.name] += 1
    return [(nm, groups[nm]) for nm in order]


def deploy_on_deck_group(app, name):
    """Bring an on-deck reinforcement group (all reserves sharing `name`) into the
    battle. Clears their on-deck flag; if combat is live, every member shares ONE
    freshly-rolled Initiative (the 'same type → same roll' rule) and is inserted into
    the order without disturbing the current actor or existing summon adjacencies."""
    idxs = [i for i, pt in enumerate(app.bm.placed_agents)
            if not pt.removed_from_play and app.bm.is_agent_on_deck(i)
            and pt.name == name]
    app._deploy_on_deck_idxs(idxs, name)


def deploy_on_deck_idxs(app, idxs, label):
    """Bring a specific set of on-deck reserve agents into the battle (the shared core
    of group Deploy and per-mob Recall). Clears their on-deck flag; if combat is live,
    the whole set shares ONE freshly-rolled Initiative and is inserted into the order
    without disturbing the current actor or existing summon adjacencies. `label` is the
    display name used only in the combat log."""
    idxs = [i for i in idxs
            if 0 <= i < len(app.bm.placed_agents)
            and not app.bm.placed_agents[i].removed_from_play
            and app.bm.is_agent_on_deck(i)]
    if not idxs:
        return
    name = label
    for i in idxs:
        app.bm.set_agent_on_deck(i, False)

    if app.tracker_mode and app.combat_active:
        tracker_join(app, idxs, name)
    elif app.combat_active and app.initiative_order:
        cur_aidx = app._current_agent_idx()   # preserve whose turn it is
        base = app.combat.roll_initiative_for(app.bm, idxs[0])
        total = base.total
        # Insert just before the first existing entry with a strictly lower total,
        # so the group acts after equal-or-higher combatants (a partial sorted insert
        # that leaves summon-after-summoner adjacencies intact).
        pos = len(app.initiative_order)
        for p, e in enumerate(app.initiative_order):
            if e.total < total:
                pos = p
                break
        new_entries = []
        for i in idxs:
            e = rpg.InitiativeEntry()
            e.agent_idx = i
            e.d20       = base.d20
            e.modifier  = base.modifier
            e.total     = total
            new_entries.append(e)
        app.initiative_order[pos:pos] = new_entries
        # Re-point turn_idx at the same actor (its list position may have shifted).
        app.turn_idx = next((p for p, e in enumerate(app.initiative_order)
                              if e.agent_idx == cur_aidx), app.turn_idx)
        app._combat_log_add(
            f"⚔ Reinforcements deploy: {name} ×{len(idxs)} (Initiative {total}).")
        lair.ensure_entry(app)    # a deployed lair creature brings its Lair entry with it
    else:
        app._combat_log_add(
            f"{name} ×{len(idxs)} removed from On Deck — will roll Initiative at combat start.")


def mob_clearable(app, idx: int) -> bool:
    """Whether the DM may clear `idx` off the board: a non-party creature that is down
    (0 HP, dying or dead), still in play and not an On Deck reserve."""
    if not (0 <= idx < len(app.bm.placed_agents)):
        return False
    pt = app.bm.placed_agents[idx]
    if pt.removed_from_play or pt.faction == PC_FACTION or app.bm.is_agent_on_deck(idx):
        return False
    return pt.conditions.dead or app.combat.get_agent_stats(app.bm, idx).hp_cur <= 0


def clear_mob(app, idx: int):
    """Clear a downed mob from the board at the DM's discretion, so others can take its
    square. Tombstoned (removed_from_play) like a dismissed summon: it stays in
    placedAgents_ and the initiative list so indices stay valid, but no longer occupies
    its cell, takes a turn or renders."""
    if not app._mob_clearable(idx):
        return
    is_cur = idx == app._current_agent_idx()
    if is_cur and app.combat_paused:
        app._combat_log_add("Resume combat to clear the acting creature.")
        app._flush_combat_log()
        return
    app._drop_concentration_for_agent(idx)
    app.bm.set_agent_removed_from_play(idx, True)
    app._combat_log_add(f"The DM clears {app.bm.placed_agents[idx].name} from the board.")
    if app.selected_idx == idx:
        app.selected_idx = -1
    app._mark_fog_dirty()
    if is_cur:
        app._advance_turn()
    app._flush_combat_log()


# ── Thief's Reflexes (Rogue Thief L17) ─────────────────────────────────
def apply_thief_reflexes(app):
    """Insert a second initiative entry at (Initiative - 10) for each Thief L17+ so it takes
    two turns during the first round. The bonus entries are removed once round 1 ends
    (_remove_thief_reflexes, called from _advance_turn). Pure GUI initiative manipulation —
    no engine call, so it does not affect checked replay."""
    app._thief_reflexes_extra = {}   # agent_idx -> reduced total (the bonus entry to drop)
    if not app.initiative_order:
        return
    pending = []
    for e in list(app.initiative_order):
        if e.agent_idx in app._thief_reflexes_extra:
            continue
        st = app.combat.get_agent_stats(app.bm, e.agent_idx)
        if (st.character_class == rpg.CharacterClass.Rogue
                and st.rogue_subclass == rpg.RogueSubclass.Thief
                and st.char_level >= 17):
            reduced = e.total - 10
            app._thief_reflexes_extra[e.agent_idx] = reduced
            pending.append((e.agent_idx, e.d20, e.modifier, reduced))
    for aidx, d20, mod, total in pending:
        ne = rpg.InitiativeEntry()
        ne.agent_idx = aidx
        ne.d20       = d20
        ne.modifier  = mod
        ne.total     = total
        # Sorted insert: just before the first entry with a strictly lower total.
        pos = len(app.initiative_order)
        for p, x in enumerate(app.initiative_order):
            if x.total < total:
                pos = p
                break
        app.initiative_order[pos:pos] = [ne]
        nm = app.bm.placed_agents[aidx].name if 0 <= aidx < len(app.bm.placed_agents) else "?"
        app._combat_log_add(f"{nm}: Thief's Reflexes — extra turn this round at Initiative {total}.")


def remove_thief_reflexes(app):
    """Drop the bonus first-round turns and re-point turn_idx at the current actor."""
    if not getattr(app, "_thief_reflexes_extra", None):
        return
    cur_aidx = app._current_agent_idx()
    to_drop = dict(app._thief_reflexes_extra)   # agent_idx -> reduced total (drop one each)
    new_order = []
    for e in app.initiative_order:
        if e.agent_idx in to_drop and e.total == to_drop[e.agent_idx]:
            del to_drop[e.agent_idx]   # remove exactly the one bonus (reduced-total) entry
            continue
        new_order.append(e)
    app.initiative_order = new_order
    app._thief_reflexes_extra = {}
    if app.initiative_order:
        app.turn_idx = next((p for p, e in enumerate(app.initiative_order)
                              if e.agent_idx == cur_aidx), 0)
    else:
        app.turn_idx = 0


def advance_turn(app):
    """Advance to the next living combatant in initiative order."""
    if app.tracker_mode:
        # The table plays the turns: no effect ticks, no NPC drive, just the order.
        app._tracker_step(1)
        return
    if not app.initiative_order:
        return
    app._mark_fog_dirty()   # lights tick + positions settle at each turn boundary
    # The new combatant's action buttons are at the top of the panel, and their panel
    # may be far shorter than the outgoing one — start each turn at the top.
    app.combat_panel_scroll = 0
    n = len(app.initiative_order)
    prev_turn_idx = app.turn_idx
    prev_idx = app._current_agent_idx()

    # FLAG: Move to C++
    # Find next living agent (skip only if actually dead, not just unconscious at 0 HP)
    for _ in range(n):
        app.turn_idx = (app.turn_idx + 1) % n
        idx = app._current_agent_idx()
        # The Lair entry (count 20) takes a turn while its owner is fighting (lair.py).
        if lair.is_lair_entry(app.initiative_order[app.turn_idx]):
            if lair.owner(app) >= 0:
                break
            continue
        if 0 <= idx < len(app.bm.placed_agents):
            # Tombstoned summons (dismissed on concentration loss) never take a turn.
            if app.bm.is_agent_removed_from_play(idx):
                continue
            stats = app.combat.get_agent_stats(app.bm, idx)
            cond = app.combat.get_agent_conditions(app.bm, idx)
            # Skip only if dead; unconscious agents at 0 HP still get a turn for death saves
            if stats.hp_cur > 0 or (stats.hp_cur <= 0 and not cond.dead):
                break
            else:
                # Agent is dead, drop concentration if any
                app._drop_concentration_for_agent(idx)

    # FLAG: Move to C++
    # Round advancement: when turn_idx wraps to 0
    if app.turn_idx < prev_turn_idx:
        app.round_num += 1
        # Thief's Reflexes: the bonus first-round turns expire once round 1 ends.
        if app.round_num == 1 and getattr(app, "_thief_reflexes_extra", None):
            remove_thief_reflexes(app)
        # Tick DM-placed effects at round boundary
        expired_dm = app.bm.tick_dm_terrain_effects()
        for effect_id in expired_dm:
            if effect_id in app._effect_meta:
                effect_name = app._effect_meta[effect_id].get("name", "Effect")
                app._combat_log_add(f"{effect_name} fades.")
                del app._effect_meta[effect_id]

    # End previous agent's turn
    if prev_idx >= 0:
        prev_name = app.bm.placed_agents[prev_idx].name if prev_idx < len(app.bm.placed_agents) else "Unknown"
        app._combat_log_add(f"[END TURN] {prev_name}")
        app.combat.end_turn(app.bm, prev_idx)

    # Legendary Actions: after an (enemy) creature's turn ends, every eligible legendary
    # creature may spend a legendary action (or pass). This phase is interactive — it may park
    # on modal menus / target picks / a Dash move — so the new turn only begins once the phase
    # completes, via _proceed_to_new_turn (the queue-drain continuation).
    begin_legendary_phase(app, prev_idx)


def proceed_to_new_turn(app):
    """Begin the next combatant's turn. Runs after _advance_turn ends the previous turn and the
    legendary-action phase (if any) finishes draining."""
    # Reset action economy and per-turn conditions for the new combatant.
    app._reset_turn_economy()
    # World Tree Vitality of the Tree: diagnostic for a stale turn-start target-pick (the actual
    # clear now lives in _clear_pending_target_picks, called just below).
    if app._picking("vitality_target") or app._vitality_option_index != -1:
        print(f"[VITALITY] turn-start clearing stale state "
              f"(pending={app._picking('vitality_target')}, opt={app._vitality_option_index})")
    # One defensive clear of every armed target-pick flag so none leaks into this new turn.
    app._clear_pending_target_picks()
    # Initiative count 20: the lair acts (lair.py), and no creature's turn begins.
    if lair.on_lair_turn(app):
        lair.begin_turn(app)
        return

    # Begin new agent's turn (conditions reset + movement seed now happen in C++). The turn start
    # opens the OnTurnStartNearby reaction window (Branches of the Tree) via the
    # flow-checkpoint API; the rest of the turn-start work runs in _finish_turn_start once any
    # reactions resolve (parked windows resume through _submit_reaction → _reaction_finish).
    new_idx = app._current_agent_idx()
    app.selected_idx = new_idx
    if new_idx < 0:
        app._update_reach()
        app._update_attack_overlay()
        return
    app._turn_start_idx  = new_idx
    # Engine-side inventory changes (a throw, a disarm, a used-up row shifting the rest) can
    # leave an item spell's tag pointing at the wrong slot; re-derive before the turn.
    app._sync_item_spells(new_idx)
    app._trace_begin_turn(new_idx)   # before begin_turn_flow, whose log lines are this turn's
    app._reaction_finish = app._finish_turn_start
    status = app.combat.begin_turn_flow(app.bm, new_idx, True)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision and app.combat.pending_decision().active:
        app._show_pending_reaction_menu()   # _submit_reaction → _finish_turn_start on completion
        return
    app._finish_turn_start()


# ── Legendary Actions ──────────────────────────────────────────────────────
# After a creature's turn ends, each legendary creature that is its enemy and still has
# legendary actions left may spend one (or pass), repeatedly, until it passes or runs out.
# Actions are driven entirely from the GUI: an attack-named option reuses begin_attack (with the
# legendary creature as the explicit attacker), and Dash/DashHalf seed an out-of-turn movement
# budget and reuse the normal drag-to-move flow. The budget resets at the creature's own turn
# start (C++ beginTurn). The phase is a continuation of _advance_turn → _proceed_to_new_turn.

def legendary_action_names_for(app, idx: int, st) -> list:
    """The list of legendary-action option names to offer creature idx. Uses the explicit
    bestiary action_names when present; otherwise falls back to a sensible default so any
    creature with legendary actions is still usable: each distinct named weapon (resolved as an
    attack) plus a half-speed move."""
    names = [n for n in st.legendary_action_names if str(n).strip()]
    if names:
        return names
    out, seen = [], set()
    for w in app.combat.get_agent_weapons(app.bm, idx):
        nm = (w.name or "").strip()
        if nm and nm.lower() not in seen:
            seen.add(nm.lower()); out.append(nm)
    out.append("DashHalf")
    return out


def legendary_eligible(app, idx: int, prev_idx: int) -> bool:
    """True if creature idx may take a legendary action after prev_idx's turn ended."""
    agents = app.bm.placed_agents
    if not (0 <= idx < len(agents)) or idx == prev_idx:
        return False
    if app.bm.is_agent_removed_from_play(idx):
        return False
    # On-deck reserves are out of the fight (not in initiative) → no legendary
    # actions until the DM deploys them.
    if app.bm.is_agent_on_deck(idx):
        return False
    try:
        st = app.combat.get_agent_stats(app.bm, idx)
    except Exception:
        return False
    if not getattr(st, "has_legendary_actions", False):
        return False
    if st.legendary_actions_current <= 0 or st.hp_cur <= 0:
        return False
    # Legendary actions fire after an *enemy's* turn (not an ally's).
    return not app._are_allies(idx, prev_idx)


def begin_legendary_phase(app, prev_idx: int):
    """Build the queue of legendary creatures eligible after prev_idx's turn, then drain it.
    Falls straight through to the new turn when nothing is eligible (the common case)."""
    app._legendary_queue = []
    app._legendary_actor = -1
    app._drop_pick("legendary_target")
    app._drop_pick("legendary_spell")
    app._legendary_move_active = False
    if app.combat_active and prev_idx >= 0:
        for i in range(len(app.bm.placed_agents)):
            if legendary_eligible(app, i, prev_idx):
                app._legendary_queue.append(i)
    offer_next_legendary(app)


def offer_next_legendary(app):
    """Show the front-of-queue legendary creature its action menu, skipping any that are no
    longer eligible. When the queue empties, begin the next combatant's turn."""
    while app._legendary_queue:
        idx = app._legendary_queue[0]
        agents = app.bm.placed_agents
        if not (0 <= idx < len(agents)) or app.bm.is_agent_removed_from_play(idx):
            app._legendary_queue.pop(0); continue
        st = app.combat.get_agent_stats(app.bm, idx)
        if st.hp_cur <= 0 or st.legendary_actions_current <= 0:
            app._legendary_queue.pop(0); continue
        app._legendary_actor = idx
        features.show_legendary_action_menu(app, idx, st)
        return
    app._legendary_actor = -1
    app._proceed_to_new_turn()


def pass_legendary(app):
    """The current legendary creature declines further actions; move to the next in the queue."""
    if app._legendary_queue:
        app._legendary_queue.pop(0)
    app._legendary_actor = -1
    offer_next_legendary(app)


def legendary_cost(app, idx: int, action_name: str) -> int:
    """Legendary actions the named option costs creature idx (bestiary action_costs; default 1)."""
    st = app.combat.get_agent_stats(app.bm, idx)
    return max(1, int(dict(st.legendary_action_costs).get(action_name, 1)))


def spend_legendary_action(app, idx: int, cost: int = 1) -> int:
    """Decrement the creature's per-round legendary-action budget by cost; return what's left."""
    st = app.combat.get_agent_stats(app.bm, idx)
    st.legendary_actions_current = max(0, st.legendary_actions_current - cost)
    app.combat.set_agent_stats(app.bm, idx, st)
    return st.legendary_actions_current


def after_legendary_action(app, idx: int):
    """A creature may take only ONE legendary action per turn-end window. Drop it from the queue
    after it acts and move on to the next eligible creature (or the new turn). Its remaining
    budget (legendary_actions_current) still lets it act again after the NEXT creature's turn,
    since the queue is rebuilt at every turn end (_begin_legendary_phase)."""
    if app._legendary_queue and app._legendary_queue[0] == idx:
        app._legendary_queue.pop(0)
    app._legendary_actor = -1
    offer_next_legendary(app)


def choose_legendary_action(app, action_name: str):
    """Dispatch a chosen legendary action: Dash/DashHalf → movement; otherwise treat the name as
    a weapon attack (matched by weapon name) and enter target-pick mode."""
    idx = app._legendary_actor
    if idx < 0 or idx >= len(app.bm.placed_agents):
        offer_next_legendary(app); return
    cost = legendary_cost(app, idx, action_name)
    st = app.combat.get_agent_stats(app.bm, idx)
    if cost > st.legendary_actions_current:
        app._combat_log_add(
            f"{app.bm.placed_agents[idx].name}: {action_name} costs {cost} legendary actions "
            f"({st.legendary_actions_current} left) — pick another or pass.")
        app._flush_combat_log()
        offer_next_legendary(app)   # re-show the menu; nothing is spent
        return
    app._legendary_cost_pending = cost
    spell_name = dict(st.legendary_action_spells).get(action_name)
    if spell_name:
        begin_legendary_spell(app, idx, action_name, spell_name)
        return
    key = action_name.strip().lower()
    if key in ("dash", "dashhalf", "dash half"):
        begin_legendary_dash(app, idx, half=(key != "dash"))
        return
    # Attack-type: find the matching weapon by (case-insensitive) name.
    weapons = app.combat.get_agent_weapons(app.bm, idx)
    widx = next((i for i, w in enumerate(weapons)
                 if w.name.strip().lower() == key), -1)
    if widx < 0:
        app._combat_log_add(
            f"{app.bm.placed_agents[idx].name}: no weapon matches legendary action "
            f"'{action_name}' — pick another or pass.")
        app._flush_combat_log()
        offer_next_legendary(app)   # re-show the menu; the action isn't consumed
        return
    if not app._weapon_usable(weapons[widx]):
        why = "recharging" if weapons[widx].expended else "out of uses"
        app._combat_log_add(
            f"{app.bm.placed_agents[idx].name}: {action_name} is {why} — pick another or pass.")
        app._flush_combat_log()
        offer_next_legendary(app)   # re-show the menu; the action isn't consumed
        return
    app._legendary_attack_name = action_name
    app._legendary_attack_widx = widx
    app._arm_pick("legendary_target")
    app._combat_log_add(
        f"{app.bm.placed_agents[idx].name}: click a target for legendary {action_name}.")
    app._flush_combat_log()


def resolve_legendary_attack(app, target_idx: int):
    """Resolve the pending legendary attack against target_idx via begin_attack (explicit
    attacker), reusing the full to-hit / Shield / on-hit pipeline. Spends one legendary action."""
    idx = app._legendary_actor
    agents = app.bm.placed_agents
    if idx < 0 or idx >= len(agents):
        app._drop_pick("legendary_target")
        offer_next_legendary(app); return
    if not (0 <= target_idx < len(agents)) or target_idx == idx:
        app._combat_log_add("Pick a valid target.")
        app._flush_combat_log()
        return  # keep target-pick armed
    if app.combat.get_agent_stats(app.bm, target_idx).hp_cur <= 0:
        app._combat_log_add("Target is already down — pick another.")
        app._flush_combat_log()
        return
    app._drop_pick("legendary_target")
    widx = app._legendary_attack_widx
    action = rpg.Attack(idx, target_idx, widx)
    action.attack_slot = "legendary"   # resolves like a normal attack; no turn-economy cost
    # The attempt costs its legendary actions regardless of hit/miss.
    spend_legendary_action(app, idx, app._legendary_cost_pending)
    app._reaction_finish = lambda i=idx: finish_legendary_attack(app, i)
    status = app.combat.begin_attack(app.bm, action)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision:
        app._show_pending_reaction_menu()   # target's Shield etc.; resumes via _reaction_finish
    else:
        finish_legendary_attack(app, idx)


def finish_legendary_attack(app, idx: int):
    """Post-resolution of a legendary attack (immediate or after a defender reaction window).
    The hit/miss, damage and on-hit riders were applied in C++; just refresh and re-offer."""
    app._flush_combat_log()
    app._sync_spell_effect_cache()
    app._update_attack_overlay()
    after_legendary_action(app, idx)


def begin_legendary_spell(app, idx: int, action_name: str, spell_name: str):
    """A legendary action that casts a spell from the creature's own list (bestiary
    action_spells: Zariel's Immolating Gaze / Teleport). Arms a pick: a creature for a
    Single-target spell, otherwise a cell (teleport destination or area centre). Cast for
    free — no slot, no turn economy — as the legendary creature, not the turn's actor."""
    spells = app.combat.get_agent_spells(app.bm, idx)
    si = next((i for i, sp in enumerate(spells) if sp.name == spell_name), -1)
    name = app.bm.placed_agents[idx].name
    if si < 0:
        app._combat_log_add(f"{name}: legendary {action_name} needs the spell '{spell_name}', "
                             "which it doesn't know — pick another or pass.")
        app._flush_combat_log()
        offer_next_legendary(app)
        return
    sp = spells[si]
    if getattr(sp, "expended", False):
        app._combat_log_add(f"{name}: {action_name} is recharging — pick another or pass.")
        app._flush_combat_log()
        offer_next_legendary(app)
        return
    app._legendary_spell_idx = si
    app._legendary_spell_label = action_name
    if getattr(sp, "teleportation_spell", False):
        app._set_pick("legendary_spell", "cell")
        hint = f"click a destination within {sp.teleport_range_ft} ft"
    elif sp.geometry == rpg.SpellGeometry.Single:
        app._set_pick("legendary_spell", "creature")
        hint = f"click a target within {sp.range} ft"
    else:
        app._set_pick("legendary_spell", "cell")
        hint = "click where to centre it"
    app._combat_log_add(f"{name}: legendary {action_name} — {hint}.")
    app._flush_combat_log()


def resolve_legendary_spell(app, hit: int, cell):
    """Resolve the armed legendary spell at the clicked creature / cell, spend its cost and
    move on. An invalid click (out of range, no creature) keeps the pick armed."""
    idx = app._legendary_actor
    mode = app._pick_data("legendary_spell")
    agents = app.bm.placed_agents
    if idx < 0 or idx >= len(agents):
        app._drop_pick("legendary_spell")
        offer_next_legendary(app); return
    spells = app.combat.get_agent_spells(app.bm, idx)
    si = app._legendary_spell_idx
    sp = spells[si]
    name, label = agents[idx].name, app._legendary_spell_label

    if getattr(sp, "teleportation_spell", False):
        if cell is None:
            return
        o = agents[idx].origin
        dist_ft = max(abs(cell.col - o.col), abs(cell.row - o.row)) * 5
        if dist_ft > sp.teleport_range_ft or not app.combat.is_valid_teleport_destination(
                app.bm, cell.col, cell.row):
            app._combat_log_add(f"{name}: can't teleport there — blocked or beyond "
                                 f"{sp.teleport_range_ft} ft.")
            app._flush_combat_log()
            return
        if app.combat.place_teleported_agents(app.bm, [idx], cell.col, cell.row) == 0:
            app._combat_log_add(f"{name}: failed to teleport — no valid destination.")
            app._flush_combat_log()
            return
        app._drop_pick("legendary_spell")
        spend_legendary_action(app, idx, app._legendary_cost_pending)
        app._combat_log_add(f"{name} uses legendary {label} and teleports to "
                             f"({cell.col}, {cell.row}).")
        finish_legendary_spell(app, idx)
        return

    action = rpg.SpellAction()
    action.caster_idx = idx
    action.spell_idx  = si
    action.slot_level = sp.level
    action.free_cast  = True
    if mode == "creature":
        if not (0 <= hit < len(agents)) or hit == idx:
            app._combat_log_add("Pick a valid target."); app._flush_combat_log()
            return
        dist_ft = app._footprint_dist_ft(idx, hit)
        if dist_ft < 0 or dist_ft > sp.range:
            app._combat_log_add(f"{agents[hit].name} is out of range ({sp.range} ft).")
            app._flush_combat_log()
            return
        action.target_indices = [hit]
    else:
        if cell is None:
            return
        action.target_indices = []
        action.aoe_col, action.aoe_row = cell.col, cell.row
    app._drop_pick("legendary_spell")
    spend_legendary_action(app, idx, app._legendary_cost_pending)
    app._combat_log_add(f"{name} uses legendary {label}.")
    app.combat.execute_spell(app.bm, action)
    finish_legendary_spell(app, idx)


def finish_legendary_spell(app, idx: int):
    app._flush_combat_log()
    app._sync_spell_effect_cache()
    app._update_attack_overlay()
    app._update_reach()
    after_legendary_action(app, idx)


def begin_legendary_dash(app, idx: int, half: bool):
    """Seed an out-of-turn movement budget for a legendary Dash (full Speed) or DashHalf (half
    Speed) and enter a legendary-move mode that reuses the normal drag-to-move flow. One
    committed move resolves the action; the creature is then re-offered."""
    st = app.combat.get_agent_stats(app.bm, idx)
    div = 2 if half else 1
    walk   = st.speed_walk   // div
    fly    = st.speed_fly    // div
    swim   = st.speed_swim   // div
    burrow = st.speed_burrow // div
    # Seed BOTH budgets: agent-side init_movement drives the reachable-cell overlay; the
    # engine-side seed_move_budgets drives begin_move's spend/clamp. beginTurn was not called
    # for this out-of-turn creature, so neither would otherwise be set.
    app.bm.placed_agents[idx].init_movement(walk, fly, swim, burrow)
    app.combat.seed_move_budgets(idx, walk, fly, swim, burrow)
    app.selected_idx          = idx
    app.move_remaining_walk   = walk
    app.move_remaining_fly    = fly
    app.move_remaining_swim   = swim
    app.move_remaining_burrow = burrow
    app.move_type = (rpg.MovementType.Walk if walk > 0 else
                      rpg.MovementType.Fly if fly > 0 else
                      rpg.MovementType.Swim if swim > 0 else
                      rpg.MovementType.Burrow)
    app._legendary_move_active = True
    spend_legendary_action(app, idx, app._legendary_cost_pending)   # the Dash's cost (1 unless authored)
    label = "DashHalf (move up to half Speed)" if half else "Dash (move up to full Speed)"
    app._combat_log_add(f"{app.bm.placed_agents[idx].name}: {label} — drag it to move.")
    app._flush_combat_log()
    app._update_reach()
    app._update_attack_overlay()


def finish_turn_start(app):
    """Continuation of _advance_turn after the OnTurnStartNearby reaction window closes
    (begin_turn_flow). Reads the stored TurnStartResult and runs the rest of the turn-start work."""
    new_idx = app._turn_start_idx
    if new_idx < 0 or new_idx >= len(app.bm.placed_agents):
        app._update_reach()
        app._update_attack_overlay()
        return
    turn_result = app.combat.last_turn_start_result()

    # Tick conditions cast by this agent (duration counted in this agent's turns, not absolute turns)
    app.combat.tick_agent_conditions_for_caster(app.bm, new_idx)

    # Log any save rolls (e.g., paralyzed escape attempt)
    if turn_result.save_roll_message:
        app._combat_log_add(f"{app.bm.placed_agents[new_idx].name}: {turn_result.save_roll_message}")

    # If turn was skipped (e.g., paralyzed save failed), advance to next turn
    if turn_result.turn_skipped:
        app._advance_turn()
        return

    # Initialize Python-side movement tracking (C++ also seeds in beginTurn)
    app._reset_movement(new_idx)

    # Tick this agent's terrain in C++ (also clears concentration if a concentration terrain expired)
    tick = app.combat.tick_terrain_for_turn(app.bm, new_idx)
    for effect_id in tick.expired_terrain_ids:
        if effect_id in app._effect_meta:
            effect_name = app._effect_meta[effect_id].get("name", "Effect")
            app._combat_log_add(f"{effect_name} fades.")
            del app._effect_meta[effect_id]
    if tick.concentration.dropped:
        app._sync_spell_effect_cache()
        conc_name = app.bm.placed_agents[new_idx].name
        app._combat_log_add(f"{conc_name}'s {tick.concentration.spell_name or 'spell'} effect expired.")

    # Phase 3: Tick light effects (Darkness, fog spells) at turn start
    app.combat.tick_light_effects_for_turn(app.bm, new_idx)

    app._update_reach()
    app._update_attack_overlay()

    # NPC automation: if this agent is engine-driven (and actually in initiative, not an On Deck
    # reserve), arm the per-frame driver rather than recursing here. The main loop drives ONE
    # automated turn next frame so the board renders between automated turns.
    if (app.combat_active and not app.tracker_mode
            and app.bm.is_agent_npc_automated(new_idx)
            and not app.bm.is_agent_on_deck(new_idx)):
        app._npc_drive_idx = new_idx
        app._npc_fresh_turn = True

    # The autosave ring (MULTIPLAYER_PLAN.md D-M6-1): the turn-start reactions have
    # resolved, the action economy is reset and an NPC's turn has not run yet, so this
    # is the top of the turn a restore lands on.
    if app.autosave_enabled:
        autosave.save(app)
        saves.save_turn(app)
