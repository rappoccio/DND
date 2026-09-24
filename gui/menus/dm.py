"""The DM's authoring menus — the ones no player may ever answer.

Nine builders, and one rule that makes them a module: every one of them ends in
`_ask_dm`, which pins `owner` to `DM_PRINCIPAL_ID` rather than deriving it from whoever
holds the token (Step 0.2). Seating a player on a creature must never hand them the
scene-authoring tools, and that is a property of the SITE, not of the widget — so the
sites that have it live together.

They go on the bus all the same, because the bus is what `authorize()` reads and because
a scripted test drives an authoring menu exactly as it drives a combat prompt
(`test_prompts.test_dm_menu_submenu_chain_carries_parent`).

Not here: the right-click map menu itself, which is still built inline in
`App._handle_events` and is the largest single prompt site left in `main.py`.
"""

import rpg_battle_map as rpg


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
        ("Create PC…",  app._show_pc_class_menu),
        ("Clear",       app._clear_agents),
    ]
    app._ask_dm("action", "Agents", items,
                 anchor=(app.btn_agents.rect.x, app.btn_agents.rect.y))


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
    di = app.bm.door_at(cell)
    if di < 0:
        return
    door = app.bm.doors[di]
    actor = app._current_agent_idx() if app.combat_active else app.selected_idx

    if app.combat_active:
        if actor < 0:
            return
        agent = app.bm.placed_agents[actor]
        # A wide door is reachable from any of its cells, not just the clicked one.
        if not any(app._cell_adjacent_to_agent(agent, c) for c in door.cells):
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
