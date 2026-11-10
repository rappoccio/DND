"""The Items menu and chests in play (plans/ITEMS_AND_CHESTS_PLAN.md I4–I5).

Functions take the app, the way ``menus/*`` do. The DM side (place items and chests,
edit a chest's lock / trap / contents, delete) changes the **design** lists
``app._design_items`` / ``app._design_chests`` and the live board together; the play
side (open, pick, break, search, disarm, unlock with a key, take) changes only the live
board, which ``_save_terrain`` writes as play state.

Action costs (P4): opening a chest and taking an item are free, as opening a door is;
Pick Lock, Break Open, Search and Disarm take the action in combat.
"""

from __future__ import annotations

import copy

import rpg_battle_map as rpg
import placed_items as pi
from helpers import (edge_key, is_blank_scroll, make_spell_scroll, parse_scroll_dc,
                     scroll_spell_names, SCROLL_DC_TABLE)
from run_state import door_key

ARMOR_SLOTS = ("Helmet", "Chest", "Leggings", "Boots", "Gloves", "Cloak")
KEY_RECORD = {"name": "Key", "description": "Unlocks the chests and doors it was made for.",
              "type": "Key", "action_type": "NoAction", "rarity": "Common", "range": 0,
              "quantity": 1, "consumable": False, "opens": [], "sprite_path": ""}


# ── Lookups ──────────────────────────────────────────────────────────────────
def design_chest(app, cid: int) -> dict | None:
    return next((c for c in app._design_chests if int(c.get("id", -1)) == cid), None)


def live_chest(app, cid: int):
    i = app.bm.chest_index(cid)
    return app.bm.chests[i] if i >= 0 else None


def chest_at(app, cell):
    i = app.bm.chest_at(cell)
    return app.bm.chests[i] if i >= 0 else None


def _cell_t(cell):
    return (cell.col, cell.row) if hasattr(cell, "col") else (int(cell[0]), int(cell[1]))


def door_ref(door) -> str:
    """The ``opens`` token of an rpg.Door (its geometry key, as run_state keys doors)."""
    if door.edges:
        rec = {"edges": [list(edge_key(e)) for e in door.edges]}
    else:
        rec = {"cells": [[c.col, c.row] for c in door.cells]}
    return pi.door_ref(door_key(rec))


def _next_pid(app) -> int:
    return pi.next_pid(app._design_items, app._design_chests)


def _save(app):
    """Design edits are map data: write them now, as the terrain editor does on close."""
    try:
        app._save_terrain()
    except Exception as e:                       # noqa: BLE001 — report, don't crash
        app._flash_status(f"Could not save the map: {e}")


# ── DM: floor items ──────────────────────────────────────────────────────────
def add_floor_item(app, kind: str, record: dict, cell, label: str = "", save=True) -> int:
    """Place a design item on the floor; returns its pid."""
    pid = _next_pid(app)
    rec = pi.make_item(kind, record, pid, _cell_t(cell), label)
    app._design_items.append(rec)
    app.bm.place_map_item(pi.to_map_item(rec))
    if save:
        _save(app)
    return pid


def remove_design_item(app, pid: int, save=True):
    """Take a design item off the map for good (floor and design)."""
    app._design_items[:] = [r for r in app._design_items if int(r.get("pid", -1)) != pid]
    for m in app.bm.get_all_items():
        if m.pid == pid:
            app.bm.remove_item(m.id)
    if save:
        _save(app)


def move_design_item(app, pid: int, cell, save=True):
    """A DM drag of a design item: its designed cell moves with it."""
    for r in app._design_items:
        if int(r.get("pid", -1)) == pid:
            r["cell"] = list(_cell_t(cell))
    if save:
        _save(app)


def floor_item_into_chest(app, pid: int, cid: int) -> bool:
    """A design floor item dragged onto a chest becomes one of its contents."""
    rec = next((r for r in app._design_items if int(r.get("pid", -1)) == pid), None)
    ch = design_chest(app, cid)
    if rec is None or ch is None:
        return False
    remove_design_item(app, pid, save=False)
    rec = {k: v for k, v in rec.items() if k != "cell"}
    ch.setdefault("contents", []).append(rec)
    _sync_chest(app, cid, new_pids=[pid])
    _save(app)
    return True


# ── DM: chests ───────────────────────────────────────────────────────────────
def add_chest(app, cell, save=True) -> int:
    cell = rpg.Cell(*_cell_t(cell))
    if app.bm.chest_at(cell) >= 0:
        return app.bm.chests[app.bm.chest_at(cell)].id
    cid = pi.next_chest_id(app._design_chests)
    rec = pi.make_chest(cid, _cell_t(cell))
    app._design_chests.append(rec)
    app.bm.add_chest(pi.to_chest(rec))
    if save:
        _save(app)
    return cid


def remove_chest(app, cid: int, save=True):
    app._design_chests[:] = [c for c in app._design_chests if int(c.get("id", -1)) != cid]
    app.bm.remove_chest(cid)
    if save:
        _save(app)


def _sync_chest(app, cid: int, new_pids=(), override=None):
    """Rebuild the live chest from its (edited) design, keeping what play did to it.
    ``new_pids`` are contents just added to the design; ``override`` sets state fields
    the DM just edited (a lock the DM turned on is on now, too)."""
    d = design_chest(app, cid)
    live = live_chest(app, cid)
    if d is None:
        return
    st = pi.chest_state(live) if live is not None else None
    if st is not None:
        st["contents"] = list(st["contents"]) + [int(p) for p in new_pids]
        st.update(override or {})
    if live is None:
        app.bm.add_chest(pi.to_chest(d, st))
    else:
        app.bm.set_chest(pi.to_chest(d, st))


def edit_chest(app, cid: int, save=True, **fields):
    """Change a chest's design fields (name, locked, lock_dc, break_dc, arcane_lock)."""
    d = design_chest(app, cid)
    if d is None:
        return
    d.update(fields)
    override = {k: fields[k] for k in ("locked",) if k in fields}
    if "arcane_lock" in fields and fields["arcane_lock"]:
        override["arcane_suppressed_turns"] = 0
    _sync_chest(app, cid, override=override)
    if save:
        _save(app)


def edit_trap(app, cid: int, save=True, **fields):
    """Change a chest's trap design. Arming it (again) resets found / disarmed / fired."""
    d = design_chest(app, cid)
    if d is None:
        return
    trap = {**pi.TRAP_DEFAULTS, **(d.get("trap") or {})}
    trap.update(fields)
    d["trap"] = trap
    override = None
    if fields.get("armed"):
        override = {"trap": {"found": False, "disarmed": False, "fired": False}}
    _sync_chest(app, cid, override=override)
    if save:
        _save(app)


def add_chest_content(app, cid: int, kind: str, record: dict, label: str = "", save=True) -> int:
    d = design_chest(app, cid)
    if d is None:
        return -1
    pid = _next_pid(app)
    d.setdefault("contents", []).append(pi.make_item(kind, record, pid, None, label))
    _sync_chest(app, cid, new_pids=[pid])
    if save:
        _save(app)
    return pid


def remove_chest_content(app, cid: int, pid: int, save=True):
    d = design_chest(app, cid)
    if d is None:
        return
    d["contents"] = [r for r in d.get("contents", []) or [] if int(r.get("pid", -1)) != pid]
    _sync_chest(app, cid)
    if save:
        _save(app)


def all_design_keys(app) -> list:
    """Every design key on this map, floor or chest: (record, where-text)."""
    out = [(r, "floor") for r in app._design_items if pi.is_key(r)]
    for c in app._design_chests:
        out += [(r, c.get("name", "chest")) for r in c.get("contents", []) or [] if pi.is_key(r)]
    return out


def set_key_opens(app, pid: int, ref: str, on: bool, save=True):
    """Add / remove ``ref`` ("chest:<id>" / "door:…") to the design key with ``pid``."""
    def _edit(rec):
        opens = list(rec["record"].get("opens", []) or [])
        if on and ref not in opens:
            opens.append(ref)
        if not on and ref in opens:
            opens.remove(ref)
        rec["record"]["opens"] = opens

    for r in app._design_items:
        if int(r.get("pid", -1)) == pid:
            _edit(r)
            pi.place_floor_items(app.bm, app._design_items, pi.floor_state(app.bm))
    for c in app._design_chests:
        for r in c.get("contents", []) or []:
            if int(r.get("pid", -1)) == pid:
                _edit(r)
                _sync_chest(app, int(c["id"]))
    if save:
        _save(app)


def key_opens(app, pid: int) -> list:
    for r in app._design_items:
        if int(r.get("pid", -1)) == pid:
            return list(r["record"].get("opens", []) or [])
    for c in app._design_chests:
        for r in c.get("contents", []) or []:
            if int(r.get("pid", -1)) == pid:
                return list(r["record"].get("opens", []) or [])
    return []


# ── Play: taking items ───────────────────────────────────────────────────────
def give_item(app, actor: int, m, armor_slot: int | None = None) -> bool:
    """Hand MapItem ``m`` (already off the floor / out of the chest) to ``actor``.

    Weapon: through the existing pickup path (slot choice, thrown bundles). Armor: into
    ``armor_slot`` (P2 as amended: armor has no slot of its own, so the taker picks one);
    anything worn there is dropped on the taker's cell. Consumable / key: into the
    inventory, merging with a carried stack of the same name. Returns False (and puts
    nothing anywhere) when it can't."""
    if not (0 <= actor < len(app.bm.placed_agents)):
        return False
    pt = app.bm.placed_agents[actor]
    name = app._agent_name(actor)
    if m.kind == rpg.MapItemKind.Weapon:
        m.cell = rpg.Cell(pt.origin.col, pt.origin.row)
        m.pid = -1
        iid = app.bm.place_map_item(m)
        placed = next((x for x in app.bm.get_all_items() if x.id == iid), None)
        if placed is not None:
            app._pickup_item(placed, actor)
        return True
    if m.kind == rpg.MapItemKind.Armor:
        if armor_slot is None:
            return False
        armor = list(app.combat.get_agent_armor(app.bm, actor))
        worn = armor[armor_slot]
        if worn.name:
            drop = rpg.MapItem()
            drop.kind = rpg.MapItemKind.Armor
            drop.armor = worn
            drop.cell = rpg.Cell(pt.origin.col, pt.origin.row)
            app.bm.place_map_item(drop)
            app._combat_log_add(f"{name} takes off {worn.name} and drops it.")
        armor[armor_slot] = m.armor
        app.combat.set_agent_armor(app.bm, actor, armor)
        app._sync_item_spells(actor)
        app._combat_log_add(f"{name} puts on {m.name} ({ARMOR_SLOTS[armor_slot]}).")
        return True
    it = m.item
    if m.label:
        it.name = m.label
    inv = list(app.combat.get_agent_items(app.bm, actor))
    # An enspelled item never stacks: its uses and attunement are its own (D0).
    for row in ([] if not it.item_spells.empty() else inv):
        if row.name == it.name and row.type == it.type and row.item_spells.empty():
            row.quantity += max(1, it.quantity)
            if it.type == rpg.ItemType.Key:
                row.opens = sorted(set(row.opens) | set(it.opens))
            break
    else:
        inv.append(it)
    app.combat.set_agent_items(app.bm, actor, inv)
    app._sync_item_spells(actor)
    app._combat_log_add(f"{name} takes {it.name}.")
    return True


def _armor_menu(app, actor: int, title: str, on_slot, anchor=None):
    armor = list(app.combat.get_agent_armor(app.bm, actor))
    rows = []
    for i, slot in enumerate(ARMOR_SLOTS):
        worn = armor[i].name if i < len(armor) else ""
        txt = f"Wear as {slot}" + (f" (swap for {worn})" if worn else "")
        rows.append((txt, lambda s=i: on_slot(s)))
    app._ask_actor(actor, "action", title, rows, anchor=anchor)


def pick_up_floor_item(app, item, actor: int, anchor=None):
    """Pick up a floor item of any kind (the floor pickup menu's row)."""
    if item.kind == rpg.MapItemKind.Weapon:
        app._pickup_item(item, actor)
        return

    def _take(slot=None):
        live = next((x for x in app.bm.get_all_items() if x.id == item.id), None)
        if live is None:
            return
        app.bm.remove_item(live.id)
        if not give_item(app, actor, live, slot):
            app.bm.place_map_item(live)

    if item.kind == rpg.MapItemKind.Armor:
        _armor_menu(app, actor, f"{app._agent_name(actor)}: wear {item.name}", _take, anchor)
    else:
        _take()


def take_from_chest(app, actor: int, cid: int, item_id: int, anchor=None):
    ch = live_chest(app, cid)
    if ch is None or not ch.open:
        return
    m = next((x for x in ch.contents if x.id == item_id), None)
    if m is None:
        return

    def _take(slot=None):
        got = app.bm.take_from_chest(cid, item_id)
        if got is None:
            return
        if not give_item(app, actor, got, slot):
            app.bm.add_to_chest(cid, got)

    if m.kind == rpg.MapItemKind.Armor:
        _armor_menu(app, actor, f"{app._agent_name(actor)}: wear {m.name}", _take, anchor)
    else:
        _take()


def take_all(app, actor: int, cid: int, anchor=None):
    """Everything but armor (which needs a slot choice each)."""
    ch = live_chest(app, cid)
    if ch is None or not ch.open:
        return
    for m in ch.contents:
        if m.kind != rpg.MapItemKind.Armor:
            take_from_chest(app, actor, cid, m.id)


# ── Play: the chest menu ─────────────────────────────────────────────────────
def carried_keys(app, actor: int) -> list:
    if not (0 <= actor < len(app.bm.placed_agents)):
        return []
    return [it for it in app.combat.get_agent_items(app.bm, actor) if it.type == rpg.ItemType.Key]


def key_for(app, actor: int, ref: str):
    return next((k for k in carried_keys(app, actor) if ref in k.opens), None)


def _spend_action(app, what: str) -> bool:
    """In combat, the action; refuse when it's gone. True = go ahead."""
    if app.combat_active and app.action_used:
        app._combat_log_add(f"Action already used this turn — cannot {what}.")
        return False
    return True


def _after_check(app, res):
    if not res.valid:
        app._combat_log_add(res.log_message or "Nothing to do.")
        return
    app._combat_log_add(res.log_message)
    if res.trap.fired:
        app._combat_log_add(res.trap.log_message)
    if app.combat_active and res.roll > 0:
        app.action_used = True
    _after_chest_change(app)


def _after_chest_change(app):
    if hasattr(app, "_after_door_change"):
        app._after_door_change()


def open_chest(app, actor: int, cid: int, anchor=None):
    if actor < 0:
        app._combat_log_add("Select a creature to open the chest.")
        return
    if not app.bm.open_chest(cid):
        app._combat_log_add("The chest is locked.")
        return
    ch = live_chest(app, cid)
    app._combat_log_add(f"{app._agent_name(actor)} opens {ch.name}.")
    res = app.combat.trigger_chest_trap(app.bm, actor, cid)
    if res.fired:
        app._combat_log_add(res.log_message)
    _after_chest_change(app)
    show_contents_menu(app, actor, cid, anchor)


def close_chest(app, cid: int):
    if app.bm.close_chest(cid):
        app._combat_log_add(f"{live_chest(app, cid).name} is closed.")
        _after_chest_change(app)


def pick_lock(app, actor: int, cid: int):
    if actor < 0:
        app._combat_log_add("No creature selected to pick the lock.")
        return
    if _spend_action(app, "pick the lock"):
        _after_check(app, app.combat.attempt_pick_chest_lock(app.bm, actor, cid))


def break_open(app, actor: int, cid: int):
    if actor < 0:
        app._combat_log_add("No creature selected to force the chest.")
        return
    if _spend_action(app, "force the chest"):
        _after_check(app, app.combat.attempt_break_chest(app.bm, actor, cid))


def search(app, actor: int, cid: int):
    if actor < 0:
        app._combat_log_add("No creature selected to search the chest.")
        return
    if _spend_action(app, "search the chest"):
        _after_check(app, app.combat.attempt_find_chest_trap(app.bm, actor, cid))


def disarm(app, actor: int, cid: int):
    if actor < 0:
        app._combat_log_add("No creature selected to disarm the trap.")
        return
    if _spend_action(app, "disarm the trap"):
        _after_check(app, app.combat.attempt_disarm_chest_trap(app.bm, actor, cid))


def unlock_with_key(app, actor: int, cid: int):
    key = key_for(app, actor, f"chest:{cid}")
    if key is None:
        return
    app.bm.unlock_chest(cid)
    app._combat_log_add(f"{app._agent_name(actor)} unlocks {live_chest(app, cid).name} "
                        f"with {key.name}.")
    _after_chest_change(app)


def unlock_door_with_key(app, actor: int, door_id: int):
    door = next((d for d in app.bm.doors if d.id == door_id), None)
    if door is None:
        return
    key = key_for(app, actor, door_ref(door))
    if key is None:
        return
    app.bm.unlock_door(door_id)
    app._combat_log_add(f"{app._agent_name(actor)} unlocks the door with {key.name}.")
    app._after_door_change()


def chest_options(app, actor: int, ch) -> list:
    """The (label, callback) rows of the chest menu for ``actor``."""
    cid = ch.id
    rows = []
    trap = ch.trap
    trap_known = trap.armed and trap.found and not trap.disarmed and not trap.fired
    if ch.open:
        n = len(ch.contents)
        rows.append((f"Look inside ({n} item{'s' if n != 1 else ''})",
                     lambda: show_contents_menu(app, actor, cid)))
        if not ch.broken:
            rows.append(("Close chest", lambda: close_chest(app, cid)))
    else:
        arcane = ch.arcane_lock and ch.arcane_suppressed_turns <= 0
        if arcane:
            rows.append(("Locked (Arcane Lock — needs Knock/Dispel)",
                         lambda: app._combat_log_add(
                             "The chest is held by an Arcane Lock; only Knock or Dispel Magic opens it.")))
        elif ch.locked:
            if key_for(app, actor, f"chest:{cid}") is not None:
                rows.append(("Unlock with key", lambda: unlock_with_key(app, actor, cid)))
            rows.append((f"Pick Lock (DC {ch.lock_dc})", lambda: pick_lock(app, actor, cid)))
        else:
            rows.append(("Open chest", lambda: open_chest(app, actor, cid)))
        bdc = ch.break_dc + (10 if arcane else 0)
        rows.append((f"Break Open (DC {bdc})", lambda: break_open(app, actor, cid)))
    if not ch.open or ch.contents:
        rows.append(("Search for traps", lambda: search(app, actor, cid)))
    if trap_known:
        rows.append((f"Disarm trap (DC {trap.disarm_dc})", lambda: disarm(app, actor, cid)))
    return rows


def chest_is_near(app, actor: int, ch) -> bool:
    if actor < 0:
        return False
    return app._cell_adjacent_to_agent(app.bm.placed_agents[actor], ch.cell)


def show_chest_menu(app, cell, pos):
    """A click on a chest in play: the acting (or selected) creature's options."""
    ch = chest_at(app, cell)
    if ch is None:
        return
    actor = app._current_agent_idx() if app.combat_active else app.selected_idx
    if app.combat_active:
        if actor < 0:
            return
        if not chest_is_near(app, actor, ch):
            app._combat_log_add("Move next to the chest to interact with it.")
            return
    rows = chest_options(app, actor, ch)
    if rows:
        app._ask_actor(actor, "action", ch.name, rows, anchor=pos)


def show_contents_menu(app, actor: int, cid: int, anchor=None):
    ch = live_chest(app, cid)
    if ch is None or not ch.open:
        return
    if not ch.contents:
        app._combat_log_add(f"{ch.name} is empty.")
        return
    rows = []
    if actor >= 0:
        for m in ch.contents:
            rows.append((f"Take {m.name}",
                         lambda i=m.id: take_from_chest(app, actor, cid, i, anchor)))
        if sum(1 for m in ch.contents if m.kind != rpg.MapItemKind.Armor) > 1:
            rows.append(("Take all", lambda: take_all(app, actor, cid, anchor)))
    else:
        rows = [(m.name, lambda: None) for m in ch.contents]
    app._ask_actor(actor, "action", f"{ch.name}: contents", rows, anchor=anchor)


# ── DM: the Items menu ───────────────────────────────────────────────────────
def show_items_menu(app, anchor=None):
    rows = [
        ("Place weapon…", lambda: _pick_catalog(app, "weapon", anchor)),
        ("Place armor…", lambda: _pick_catalog(app, "armor", anchor)),
        ("Place item…", lambda: _pick_catalog(app, "item", anchor)),
        ("Place key", lambda: arm_placement(app, ("item", copy.deepcopy(KEY_RECORD)))),
        ("Place chest", lambda: arm_placement(app, ("chest", None))),
        (f"Chests ({len(app._design_chests)})…", lambda: show_chests_list(app, anchor)),
        (f"Placed items ({len(app._design_items)})…", lambda: show_floor_list(app, anchor)),
        (f"Keys ({len(all_design_keys(app))})…", lambda: show_keys_list(app, anchor)),
    ]
    app._ask_dm("action", "Items", rows, anchor=anchor)


def finish_spell_scroll(app, record, done):
    """SS2 (SPELL_SCROLLS_PLAN.md): the item picker's finish hook. A blank catalog Spell Scroll
    asks for its spell, then its save DC and attack (prefilled from the DMG table, S2), and
    ``done`` gets the made scroll. Anything else passes straight through. Esc at either step
    adds nothing."""
    if not is_blank_scroll(record):
        done(record)
        return
    names = set(scroll_spell_names(app.all_spells))

    def _spell(sp):
        if not isinstance(sp, dict) or sp.get("name") not in names:
            return
        level = max(0, min(9, int(sp.get("level", 0) or 0)))
        dc, atk = SCROLL_DC_TABLE[level]

        def _dc(text):
            parsed = parse_scroll_dc(text)
            if parsed is None:
                app._flash_status(f"Not a DC: {text!r} — want e.g. \"15\" or \"15 +7\".")
                return
            done(make_spell_scroll(record, sp, *parsed))

        app.name_prompt.show(f"{dc} +{atk}", _dc,
                             title=f"Spell Scroll ({sp['name']}): save DC and attack bonus")

    app.spell_selection_dialog.show(_spell, title="Spell Scroll: choose its spell",
                                    allow_names=names)


def _catalog_dialog(app, kind):
    return {"weapon": app.weapon_selection_dialog, "armor": app.armor_selection_dialog,
            "item": app.item_selection_dialog}[kind]


def _pick_catalog(app, kind, anchor=None, then=None):
    """Open the catalog picker; ``then(kind, record)`` or else arm floor placement."""
    def _chosen(record):
        if not isinstance(record, dict):
            return
        if then is not None:
            then(kind, record)
        else:
            arm_placement(app, (kind, copy.deepcopy(record)))
    _catalog_dialog(app, kind).show(_chosen)


def arm_placement(app, what):
    """Arm click-to-place: ``("weapon"|"armor"|"item", record)`` or ``("chest", None)``.
    Each left click on the map places one; Esc or a right click stops."""
    app._item_placing = what
    kind, rec = what
    label = "a chest" if kind == "chest" else (rec or {}).get("name", "item")
    app._flash_status(f"Placing {label}: click cells; Esc or right-click to stop.", 4.0)


def disarm_placement(app):
    app._item_placing = None


def place_at(app, cell) -> bool:
    """A left click while placement is armed. True when it placed something."""
    what = getattr(app, "_item_placing", None)
    if what is None or cell is None:
        return False
    kind, rec = what
    if kind == "chest":
        if app.bm.is_blocked(cell, 1) or app._agent_at(cell) >= 0:
            app._flash_status("A chest needs an empty floor cell.")
            return True
        cid = add_chest(app, cell)
        app._combat_log_add(f"Placed Chest {cid} at ({cell.col}, {cell.row}).")
        return True
    if app.bm.chest_at(cell) >= 0:
        cid = app.bm.chests[app.bm.chest_at(cell)].id
        add_chest_content(app, cid, kind, rec)
        app._combat_log_add(f"Put {rec.get('name', 'item')} in Chest {cid}.")
        return True
    add_floor_item(app, kind, rec, cell)
    app._combat_log_add(f"Placed {rec.get('name', 'item')} at ({cell.col}, {cell.row}).")
    return True


def _rename(app, title, current, done):
    app.name_prompt.show(current, done, title=title, allow_empty=True)


def show_floor_list(app, anchor=None):
    rows = []
    on_floor = {m.pid for m in app.bm.get_all_items() if m.pid >= 0}
    for r in app._design_items:
        pid = int(r["pid"])
        c = r.get("cell") or ["?", "?"]
        gone = "" if pid in on_floor else " — taken"
        rows.append((f"{pi.display_name(r)} at ({c[0]}, {c[1]}){gone}",
                     lambda p=pid: _floor_item_menu(app, p, anchor)))
    if not rows:
        app._flash_status("No placed items on this map.")
        return
    app._ask_dm("action", "Placed items", rows, anchor=anchor)


def _floor_item_menu(app, pid, anchor=None):
    rec = next((r for r in app._design_items if int(r["pid"]) == pid), None)
    if rec is None:
        return

    def _relabel(text):
        rec["label"] = (text or "").strip()
        pi.place_floor_items(app.bm, app._design_items, pi.floor_state(app.bm))
        _save(app)

    rows = [("Rename…", lambda: _rename(app, "Item name (empty = catalog name)",
                                         pi.display_name(rec), _relabel)),
            ("Delete", lambda: remove_design_item(app, pid))]
    if pi.is_key(rec):
        rows.insert(1, ("Opens…", lambda: show_key_opens_menu(app, pid, anchor)))
    app._ask_dm("action", pi.display_name(rec), rows, anchor=anchor)


def show_chests_list(app, anchor=None):
    rows = [(f"{c.get('name')} at ({c['cell'][0]}, {c['cell'][1]})",
             lambda i=int(c["id"]): show_chest_edit_menu(app, i, anchor))
            for c in app._design_chests]
    if not rows:
        app._flash_status("No chests on this map. Items… → Place chest.")
        return
    app._ask_dm("action", "Chests", rows, anchor=anchor)


def _on_off(b):
    return "ON" if b else "OFF"


def _dc_menu(app, title, current, on_pick, anchor=None):
    rows = [(f"DC {dc}" + ("  ✓" if dc == current else ""), lambda v=dc: on_pick(v))
            for dc in (5, 10, 12, 13, 15, 17, 18, 20, 22, 25, 30)]
    app._ask_dm("action", title, rows, anchor=anchor)


def show_chest_edit_menu(app, cid, anchor=None):
    """The DM's chest editor: lock, DCs, Arcane Lock, trap, contents, delete."""
    d = design_chest(app, cid)
    if d is None:
        return
    again = lambda: show_chest_edit_menu(app, cid, anchor)   # noqa: E731

    def _set(**kw):
        edit_chest(app, cid, **kw)
        again()

    def _rename_chest(text):
        edit_chest(app, cid, name=(text or "").strip() or f"Chest {cid}")

    trap = {**pi.TRAP_DEFAULTS, **(d.get("trap") or {})}
    live = live_chest(app, cid)
    state = ""
    if live is not None:
        state = (" (now: " + ("broken" if live.broken else "open" if live.open else "shut")
                 + (", locked" if live.locked else "") + ")")
    rows = [
        (f"Name: {d.get('name')}…", lambda: _rename(app, "Chest name", d.get("name", ""),
                                                    _rename_chest)),
        (f"Locked: {_on_off(d.get('locked'))}{state}",
         lambda: _set(locked=not d.get("locked"))),
        (f"Lock DC {d.get('lock_dc', 15)}…",
         lambda: _dc_menu(app, "Lock DC", d.get("lock_dc", 15), lambda v: _set(lock_dc=v), anchor)),
        (f"Break DC {d.get('break_dc', 15)}…",
         lambda: _dc_menu(app, "Break DC", d.get("break_dc", 15), lambda v: _set(break_dc=v), anchor)),
        (f"Arcane Lock: {_on_off(d.get('arcane_lock'))}",
         lambda: _set(arcane_lock=not d.get("arcane_lock"))),
        (f"Trap: {trap_summary(trap)}…", lambda: show_trap_menu(app, cid, anchor)),
        (f"Contents ({len(d.get('contents', []) or [])})…",
         lambda: show_contents_edit_menu(app, cid, anchor)),
        ("Keys that open it…", lambda: show_keys_for_menu(app, f"chest:{cid}", anchor)),
    ]
    if live is not None and (live.open or live.broken or live.trap.fired
                             or live.trap.found or live.trap.disarmed):
        rows.append(("Reset to design (shut, trap re-armed)",
                     lambda: (_reset_chest(app, cid), again())))
    rows.append(("Delete chest", lambda: remove_chest(app, cid)))
    app._ask_dm("action", d.get("name", f"Chest {cid}"), rows, anchor=anchor)


def _reset_chest(app, cid):
    d = design_chest(app, cid)
    if d is not None:
        app.bm.set_chest(pi.to_chest(d))
        _save(app)


def trap_summary(trap: dict) -> str:
    if not trap.get("armed"):
        return "none"
    dice = f"{trap['num_dice']}d{trap['die_size']}" + (f"+{trap['bonus']}" if trap.get("bonus") else "")
    return (f"{dice} {trap['damage_type']}, {trap['save']} DC {trap['save_dc']}"
            + (", Poisoned" if trap.get("poisons") else ""))


def show_trap_menu(app, cid, anchor=None):
    d = design_chest(app, cid)
    if d is None:
        return
    trap = {**pi.TRAP_DEFAULTS, **(d.get("trap") or {})}
    again = lambda: show_trap_menu(app, cid, anchor)   # noqa: E731

    def _set(**kw):
        edit_trap(app, cid, **kw)
        again()

    def _choose(title, values, cur, key):
        rows = [(str(v) + ("  ✓" if v == cur else ""), lambda x=v: _set(**{key: x}))
                for v in values]
        app._ask_dm("action", title, rows, anchor=anchor)

    rows = [(f"Trapped: {_on_off(trap['armed'])}", lambda: _set(armed=not trap["armed"]))]
    if trap["armed"]:
        rows += [
            (f"Find DC {trap['detect_dc']}…",
             lambda: _dc_menu(app, "Find DC", trap["detect_dc"], lambda v: _set(detect_dc=v), anchor)),
            (f"Disarm DC {trap['disarm_dc']}…",
             lambda: _dc_menu(app, "Disarm DC", trap["disarm_dc"], lambda v: _set(disarm_dc=v), anchor)),
            (f"Save: {trap['save']}…", lambda: _choose("Save", pi.SAVES, trap["save"], "save")),
            (f"Save DC {trap['save_dc']}…",
             lambda: _dc_menu(app, "Save DC", trap["save_dc"], lambda v: _set(save_dc=v), anchor)),
            (f"Dice: {trap['num_dice']}…",
             lambda: _choose("Number of dice", list(range(1, 11)), trap["num_dice"], "num_dice")),
            (f"Die: d{trap['die_size']}…",
             lambda: _choose("Die size", [4, 6, 8, 10, 12], trap["die_size"], "die_size")),
            (f"Bonus: +{trap['bonus']}…",
             lambda: _choose("Bonus", list(range(0, 11)), trap["bonus"], "bonus")),
            (f"Damage type: {trap['damage_type']}…",
             lambda: _choose("Damage type", pi.DAMAGE_TYPES, trap["damage_type"], "damage_type")),
            (f"Half on a save: {_on_off(trap['half_on_save'])}",
             lambda: _set(half_on_save=not trap["half_on_save"])),
            (f"Poisons on a failed save: {_on_off(trap['poisons'])}",
             lambda: _set(poisons=not trap["poisons"])),
        ]
    rows.append(("Back", lambda: show_chest_edit_menu(app, cid, anchor)))
    app._ask_dm("action", f"{d.get('name')}: trap", rows, anchor=anchor)


def show_contents_edit_menu(app, cid, anchor=None):
    d = design_chest(app, cid)
    if d is None:
        return
    again = lambda: show_contents_edit_menu(app, cid, anchor)   # noqa: E731

    def _added(kind, record):
        add_chest_content(app, cid, kind, record)
        again()

    rows = [("Add weapon…", lambda: _pick_catalog(app, "weapon", anchor, _added)),
            ("Add armor…", lambda: _pick_catalog(app, "armor", anchor, _added)),
            ("Add item…", lambda: _pick_catalog(app, "item", anchor, _added)),
            ("Add key", lambda: _added("item", copy.deepcopy(KEY_RECORD)))]
    live = live_chest(app, cid)
    inside = {m.pid for m in live.contents} if live is not None else set()
    for r in d.get("contents", []) or []:
        pid = int(r["pid"])
        gone = "" if pid in inside else " — taken"
        rows.append((f"{pi.display_name(r)}{gone}…",
                     lambda p=pid: _content_menu(app, cid, p, anchor)))
    rows.append(("Back", lambda: show_chest_edit_menu(app, cid, anchor)))
    app._ask_dm("action", f"{d.get('name')}: contents", rows, anchor=anchor)


def _content_menu(app, cid, pid, anchor=None):
    d = design_chest(app, cid)
    rec = next((r for r in (d or {}).get("contents", []) or [] if int(r["pid"]) == pid), None)
    if rec is None:
        return

    def _relabel(text):
        rec["label"] = (text or "").strip()
        _sync_chest(app, cid)
        _save(app)

    rows = [("Rename…", lambda: _rename(app, "Item name (empty = catalog name)",
                                         pi.display_name(rec), _relabel))]
    if pi.is_key(rec):
        rows.append(("Opens…", lambda: show_key_opens_menu(app, pid, anchor)))
    rows += [("Remove", lambda: (remove_chest_content(app, cid, pid),
                                 show_contents_edit_menu(app, cid, anchor))),
             ("Back", lambda: show_contents_edit_menu(app, cid, anchor))]
    app._ask_dm("action", pi.display_name(rec), rows, anchor=anchor)


def _key_targets(app) -> list:
    """(ref, text) for everything on this map a key can open: chests and locked-able doors."""
    out = [(f"chest:{int(c['id'])}", c.get("name", f"Chest {c['id']}")) for c in app._design_chests]
    for d in app.bm.doors:
        a = d.cell
        out.append((door_ref(d), f"Door at ({a.col}, {a.row})" + (" (locked)" if d.locked else "")))
    return out


def show_key_opens_menu(app, pid, anchor=None):
    opens = set(key_opens(app, pid))
    rows = []
    for ref, text in _key_targets(app):
        on = ref in opens
        rows.append((("✓ " if on else "   ") + text,
                     lambda r=ref, o=on: (set_key_opens(app, pid, r, not o),
                                          show_key_opens_menu(app, pid, anchor))))
    if not rows:
        app._flash_status("Nothing on this map to unlock: place a chest or a door first.")
        return
    app._ask_dm("action", "This key opens", rows, anchor=anchor)


def show_keys_list(app, anchor=None):
    rows = [(f"{pi.display_name(r)} ({where})",
             lambda p=int(r["pid"]): show_key_opens_menu(app, p, anchor))
            for r, where in all_design_keys(app)]
    if not rows:
        app._flash_status("No keys on this map. Items… → Place key.")
        return
    app._ask_dm("action", "Keys", rows, anchor=anchor)


def show_keys_for_menu(app, ref, anchor=None):
    """Which of this map's keys open ``ref`` (a chest or a door); toggle each."""
    rows = []
    for r, where in all_design_keys(app):
        pid = int(r["pid"])
        on = ref in (r["record"].get("opens") or [])
        rows.append((("✓ " if on else "   ") + f"{pi.display_name(r)} ({where})",
                     lambda p=pid, o=on: (set_key_opens(app, p, ref, not o),
                                          show_keys_for_menu(app, ref, anchor))))
    if not rows:
        app._flash_status("No keys on this map. Items… → Place key, or add one to a chest.")
        return
    app._ask_dm("action", "Keys that open it", rows, anchor=anchor)


def show_chest_dm_menu(app, cell, pos):
    """DM right-click on a chest outside combat: edit it."""
    ch = chest_at(app, cell)
    if ch is not None:
        show_chest_edit_menu(app, ch.id, anchor=pos)
