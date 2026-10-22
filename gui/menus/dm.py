"""The DM's authoring menus — the ones no player may ever answer.

Nine builders, and one rule that makes them a module: every one of them ends in
`_ask_dm`, which pins `owner` to `DM_PRINCIPAL_ID` rather than deriving it from whoever
holds the token (Step 0.2). Seating a player on a creature must never hand them the
scene-authoring tools, and that is a property of the SITE, not of the widget — so the
sites that have it live together.

They go on the bus all the same, because the bus is what `authorize()` reads and because
a scripted test drives an authoring menu exactly as it drives a combat prompt
(`test_prompts.test_dm_menu_submenu_chain_carries_parent`).

Not here: the right-click map menus (the agent's DM menu, the On Deck recall, fog of
war), which are `board.py`'s. They end in `_ask_dm` too, but they are what a click on
the board opens, not a panel button.
"""

import rpg_battle_map as rpg
import autosave
from helpers import door_touch_cells
from net.roster import DM_PRINCIPAL_ID


# ─────────────────────────────────────────────────────────────────────
#  Grouped panel menus: the Agents… / Terrain… / Lighting… buttons each
#  pop a ContextMenu of that group's actions (replacing the old wall of
#  per-action buttons in the setup panel).
# ─────────────────────────────────────────────────────────────────────
def show_agents_menu(app):
    """Popup for the "Agents…" panel button: encounter save/load plus the ways
    to add individual agents (Create Mob/PC replace the old Select Mob/PC)."""
    items = [
        ("Load…",       app._open_load_agents_browser),
        ("Import DDB…", app._import_ddb_character),
        ("Save…",       app._open_save_agents_browser),
        ("Load PCs…",   app._open_load_pcs_browser),
        ("Create Mob…", lambda: app.mob_dialog.show(
                            lambda mob: app._on_mob_selected(mob))),
        # A bare method reference, not a call: it has to become a bound lambda here,
        # because the function it names is now this module's and takes `app`.
        ("Create PC…",  lambda: show_pc_class_menu(app)),
        ("Clear",       app._clear_agents),
    ]
    app._ask_dm("action", "Agents", items,
                 anchor=(app.btn_agents.rect.x, app.btn_agents.rect.y))


def show_restore_autosave_menu(app, anchor=None, parent=None):
    """The active encounter's autosave ring, newest first: round, actor and time per slot
    (D-M6-5). Picking one restores it; an empty ring opens nothing and says so.

    ``anchor`` and ``parent`` are the Table menu's (D-M7-5), which opens this mid-fight,
    when the setup panel's button is not drawn."""
    slots = autosave.list_slots(app)
    if not slots:
        app._flash_status("No autosaves for this encounter yet")
        return
    options = [(autosave.slot_label(m), lambda k=m["slot"]: autosave.restore(app, k))
               for m in slots]
    if anchor is None:
        anchor = (app.btn_restore_autosave.rect.x, app.btn_restore_autosave.rect.y)
    app._ask_dm("action", "Restore autosave", options, anchor=anchor, parent=parent)


# ─────────────────────────────────────────────────────────────────────
#  The Table menu (MULTIPLAYER_PLAN.md D-M7-5): the join code and URL,
#  the seats, a new code, locking the table, a rewind, the session log.
#  Reached from the setup panel's Table… and the combat panel's `table`
#  tool, so it works mid-fight.
# ─────────────────────────────────────────────────────────────────────
SESSION_LOG_ROWS = 20


def show_table_menu(app, anchor=None):
    if anchor is None:
        anchor = (app.btn_table.rect.x, app.btn_table.rect.y)
    roster = app.roster
    net = getattr(app, "_net", None)
    where = f" · {net.url}" if net is not None else " · no player server"
    players = roster.players()
    items = [
        # A header row. It is a row only because a context menu has no other kind; picking
        # it does nothing.
        (f"Join code {roster.join_code}{where}", lambda: None),
        (f"Players ({len(players)}) ▸", lambda: _players_menu(app, anchor)),
        ("New join code", lambda: new_join_code(app)),
        ("Lock the table (new code, everyone rejoins)", lambda: lock_table(app)),
        ("Restore autosave…", lambda: show_restore_autosave_menu(
            app, anchor=anchor, parent=app.prompts.answering)),
        ("Session log…", lambda: _session_log_menu(app, anchor)),
    ]
    app._ask_dm("action", "Table", items, anchor=anchor)


def _players_menu(app, anchor):
    players = app.roster.players()
    if not players:
        app._flash_status("Nobody is seated yet")
        return
    items = [(f"{p.display_name} ▸", lambda pid=p.id: _player_menu(app, pid, anchor))
             for p in players]
    app._ask_dm("action", "Players", items, anchor=anchor, parent=app.prompts.answering)


def _player_menu(app, principal_id, anchor):
    name = app.roster.display_name(principal_id)
    owned = len(app.roster.controlled_by(principal_id))
    items = [
        (f"Remove {name} from the table", lambda: remove_player(app, principal_id)),
        ("Rename…", lambda: _rename_player(app, principal_id)),
    ]
    app._ask_dm("action", f"{name} · {owned} token{'s' if owned != 1 else ''}", items,
                 anchor=anchor, parent=app.prompts.answering)


def _session_log_menu(app, anchor):
    lines = app.session_log.tail(include_dm=True, limit=SESSION_LOG_ROWS)
    if not lines:
        app._flash_status("The session log is empty")
        return
    items = [(f"{e['at']}  {'[DM] ' if e.get('dm') else ''}{e['text']}", lambda: None)
             for e in lines]
    app._ask_dm("action", "Session log", items, anchor=anchor,
                 parent=app.prompts.answering)


def remove_player(app, principal_id) -> None:
    """Unseat a player (D-M7-5). Their tokens go back to the DM, their seat goes, and
    their screens close with 4403, so the client can say the DM removed them.

    With the join code unchanged they can join again, as a new seat with no tokens. The
    controller fields are rewritten rather than left orphaned: A1 would fold an unknown
    controller to the DM anyway, but the save should say so plainly."""
    if principal_id == DM_PRINCIPAL_ID or app.roster.get(principal_id) is None:
        return
    name = app.roster.display_name(principal_id)
    app._sync_roster_tokens()
    for idx in app.roster.controlled_by(principal_id):
        app.bm.set_agent_controller(idx, DM_PRINCIPAL_ID)
    app.roster.remove_principal(principal_id)
    app._sync_roster_tokens()
    app._save_session()
    if getattr(app, "_net", None) is not None:
        app._net.close_principal(principal_id)
    app.session_log.add(f"The DM removed {name} from the table.", principal=principal_id)
    app._flash_status(f"Removed {name}. Their tokens are the DM's.")


def _rename_player(app, principal_id) -> None:
    old = app.roster.display_name(principal_id)

    def _commit(name):
        name = (name or "").strip()
        if not name or name == old or app.roster.get(principal_id) is None:
            return
        app.roster.rename_principal(principal_id, name)
        app._save_session()
        app.session_log.add(f"The DM renamed {old} to {name}.", principal=principal_id)
    app.name_prompt.show(old, _commit, title="Rename player")


def new_join_code(app) -> None:
    """A fresh code. Everyone already seated keeps their seat and their screen: a code is
    an invite, and this only stops the old one inviting anybody new."""
    code = app.roster.rotate_join_code()
    app._save_session()
    app.session_log.add("The DM changed the join code.")
    print(f"[net] join code: {code}")
    app._flash_status(f"New join code: {code}")


def lock_table(app) -> None:
    """A new code, and every credential revoked at once (A5's panic button). Each seat is
    kept, so a player who joins again with the new code takes back their own seat and
    tokens; anyone who only had the old code is out."""
    code = app.roster.rotate_join_code()
    app.roster.revoke_all()
    app._save_session()
    app.session_log.add("The DM locked the table. Everyone joins again with the new code.")
    print(f"[net] join code: {code}")
    app._flash_status(f"Table locked. New join code: {code}")


def show_pc_class_menu(app):
    pc_classes = ["Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk",
                  "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard"]
    options = [(cls, lambda c=cls: app._on_pc_class_selected(c)) for cls in pc_classes]
    app._ask_dm("action", "Create PC — class", options,
                 anchor=(app._panel_x() + app._PANEL_PAD, 100))


def show_terrain_menu(app):
    """Popup for the "Terrain…" panel button."""
    items = [
        ("Edit…",     app._open_terrain_editor),
        ("Load…",     app._open_load_terrain_browser),
        ("Save…",     app._open_save_terrain_browser),
        ("Generate…", app._on_generate_terrain),
        ("Hide" if app.show_terrain else "Show", app._toggle_show_terrain),
        ("Clear",     app._clear_terrain),
    ]
    if app._walls_enabled:
        items.insert(4, ("Wall Detection…", app._open_wall_detection))
    if app._manual_grid:
        # Re-render the map so its drawn squares are whole pixels (gui/grid_rescale.py).
        items.insert(-1, ("Rescale Image to Grid…", app._rescale_image_to_grid))
    app._ask_dm("action", "Terrain", items,
                 anchor=(app.btn_terrain.rect.x, app.btn_terrain.rect.y))


def show_lighting_menu(app):
    """Popup for the "Lighting…" panel button."""
    items = [
        ("Edit…", app._open_lighting_editor),
        ("Load…", app._open_load_lighting_browser),
        ("Hide" if app.show_lighting_overlay else "Show",
         app._toggle_lighting_overlay),
    ]
    app._ask_dm("action", "Lighting", items,
                 anchor=(app.btn_lighting.rect.x, app.btn_lighting.rect.y))


# ─────────────────────────────────────────────────────────────────────
#  Dungeon manifest management (Phase 6): New / Open / Save / Add Page,
#  plus the Pages overview that places pages on the global grid.
#  The manifest is placement-only; each page's scene lives in its own
#  encounter sidecars (agents/terrain/lighting/effects).
# ─────────────────────────────────────────────────────────────────────
def show_dungeon_menu(app):
    """Popup for the "Dungeon Configuration" panel button. The item set depends
    on whether a manifest is currently open."""
    if app.dungeon is None:
        items = [
            ("New Dungeon (this map)", app._dungeon_new),
            ("Open Dungeon…",          app._dungeon_open_browser),
        ]
    else:
        items = [
            ("Pages / Overview…", app._dungeon_pages_overview),
            ("Add Page…",         app._dungeon_add_page_browser),
            ("Align Floor",       lambda: app.floor_align.start(app)),
            ("Save Dungeon",      app._dungeon_save),
            ("Open Dungeon…",     app._dungeon_open_browser),
            ("Close Dungeon",     app._dungeon_close),
        ]
    app._ask_dm("action", "Dungeon configuration", items,
                 anchor=(app.btn_dungeon.rect.x, app.btn_dungeon.rect.y))


def show_door_menu(app, cell, pos):
    """Context menu for a door cell: Open/Close (object interaction) and Pick Lock
    (an action). Knock is cast as a normal spell at the cell, not from here.

    During combat the acting creature must be adjacent; out of combat the DM acts
    freely (pick-lock uses the currently selected agent)."""
    di = app._door_index_at(cell, pos)
    if di < 0:
        return
    door = app.bm.doors[di]
    actor = app._current_agent_idx() if app.combat_active else app.selected_idx

    if app.combat_active:
        if actor < 0:
            return
        agent = app.bm.placed_agents[actor]
        # A wide door is reachable from any of its cells, not just the clicked one; an
        # edge door from standing in a cell either side of it.
        if door.edges:
            o, n = agent.origin, agent.size
            near = any(o.col <= c.col < o.col + n and o.row <= c.row < o.row + n
                       for c in door_touch_cells(door))
        else:
            near = any(app._cell_adjacent_to_agent(agent, c) for c in door.cells)
        if not near:
            app._combat_log_add("Move adjacent to the door to interact with it.")
            return

    options = []
    door_id = door.id
    if door.broken:
        # Smashed off its frame — nothing left to open, close, or lock.
        options.append(("Door broken (smashed off its frame)",
                        lambda: app._combat_log_add(
                            "The door has been smashed off its frame; it can't be closed.")))
    elif door.open:
        options.append(("Close door", lambda d=door_id: app._door_close(d)))
    else:
        if door.arcane_lock:
            options.append(("Locked (Arcane Lock — needs Knock/Dispel)",
                            lambda: app._combat_log_add(
                                "The door is held by an Arcane Lock; only Knock or Dispel Magic opens it.")))
        elif door.locked:
            options.append((f"Pick Lock (DC {door.lock_dc})",
                            lambda a=actor, d=door_id: app._door_pick_lock(a, d)))
        else:
            options.append(("Open door", lambda d=door_id: app._door_open(d)))

        # Force it (Strength/Athletics) — available on any closed door, even a locked
        # or arcane-locked one (you're smashing the door, not defeating the magic). An
        # active Arcane Lock stiffens the door by +10 to the break DC.
        break_dc = door.break_dc + (10 if (door.arcane_lock and
                                           door.arcane_suppressed_turns <= 0) else 0)
        options.append((f"Break Down (DC {break_dc})",
                        lambda a=actor, d=door_id: app._door_break_down(a, d)))

    # Cross-map staple (Floors Phase 5): an open, linked door offers passage to the
    # abutting page. A locked/arcane-locked (thus closed) door blocks it — the option
    # only appears once the door is open. Explicit action, matching the ladder menu.
    link = app._door_link_at(door)
    if link is not None and door.open:
        options.append((f"Go through door (to floor {link[2]})",
                        lambda a=actor, d=door_id: app._use_door_link(d, a)))

    if options:
        # Out of combat `actor` is the selected token (or -1), and controller_of folds
        # an unknown index to the DM — which is the right owner for DM-side authoring.
        app._ask_actor(actor, "action", "Door", options, anchor=pos)


def show_ladder_menu(app, cell, pos):
    """Context menu for a ladder cell: a "Use Ladder" action that carries the acting
    (or selected) creature to the target floor via the dungeon manifest.

    Out-of-combat only for the MVP (see Floors plan Known Limitations); the actual
    page switch is gated by _switch_to_page's combat guard, which flashes if in combat."""
    li = app._ladder_at(cell)
    if li < 0:
        return
    lad = app._ladders[li]
    X, Y, Z = lad["target"]
    actor = app._current_agent_idx() if app.combat_active else app.selected_idx

    if app.combat_active:
        agent = app.bm.placed_agents[actor] if actor >= 0 else None
        if agent is not None and not any(
                app._cell_adjacent_to_agent(agent, rpg.Cell(c[0], c[1])) for c in lad["cells"]):
            app._combat_log_add("Move adjacent to the ladder to use it.")
            return

    label = f"Use Ladder (to floor {Z})"
    options = [(label, lambda a=actor, l=li: app._use_ladder(l, a))]
    app._ask_actor(actor, "action", f"Ladder to floor {Z}", options, anchor=pos)


# FLAG: Move to C++
def show_item_pickup_menu(app, cell, items, agent_idx, pos):
    """Show context menu to pick up one of the items at this cell."""
    menu_items = []
    for item in items:
        def _pickup(i=item, a=agent_idx):
            app._pickup_item(i, a)
        menu_items.append((f"Pick up {item.weapon.name}", _pickup))
    if menu_items:
        app._ask_actor(agent_idx, "action",
                        f"{app._agent_name(agent_idx)}: pick up an item", menu_items,
                        anchor=pos)


# FLAG: Move to C++
def show_item_context_menu(app, cell, items, pos):
    """DM right-click menu for dropped weapons on a cell: remove each item.
    (Relocation is done by left-click dragging the item — see the drag handlers.)"""
    menu_items = []
    for item in items:
        nm = item.weapon.name or "item"
        menu_items.append((f"Delete {nm}", lambda i=item: app._delete_item(i)))
    if menu_items:
        app._ask_dm("action", "Dropped items on this cell", menu_items, anchor=pos)
