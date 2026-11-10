"""Placed items and chests: records ⇄ engine objects (plans/ITEMS_AND_CHESTS_PLAN.md).

The DM places catalog items (weapons.json / armor.json / items.json) on the floor or in
chests. Like doors, each has a **design** (map.json, restored by Reset / Release) and a
**play state** (run.json):

  * design floor item / chest content — ``{"pid", "kind", "record", "label", "cell"}``:
    ``kind`` is "weapon" | "armor" | "item", ``record`` the whole catalog entry (so a
    later catalog edit doesn't change it; a key's ``opens`` lives there), ``label`` the
    DM's name for it ("" = catalog name), ``cell`` [c, r] on the floor only. ``pid`` is
    unique on the map across floor items and chest contents.
  * design chest — ``{"id", "cell", "name", "locked", "lock_dc", "break_dc",
    "arcane_lock", "trap": {...}, "contents": [design item, ...]}``.
  * floor state — ``[{"pid", "cell"}, ...]``: the design items still on the floor and
    where (a DM drag moves one). Absent ⇒ every design item is where it was placed.
  * chest state — ``[{"id", "open", "locked", "broken", "arcane_suppressed_turns",
    "trap": {"found", "disarmed", "fired"}, "contents": [pid, ...]}, ...]``.
    A chest with no state entry is as designed.

A design item taken in play leaves the map for good (it is in someone's pack); dropped
weapons stay the creatures document's ``map_items`` as before.
"""

from __future__ import annotations

import copy

import rpg_battle_map as rpg
from helpers import _dict_to_weapon, _dict_to_armor, _dict_to_item

KINDS = ("weapon", "armor", "item")
_KIND_ENUM = {"weapon": "Weapon", "armor": "Armor", "item": "Consumable"}

SAVES = ("Str", "Dex", "Con", "Int", "Wis", "Cha")
MAGIC_TYPES = ("Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison",
               "Psychic", "Radiant", "Thunder")
PHYSICAL_TYPES = ("Bludgeoning", "Piercing", "Slashing")
DAMAGE_TYPES = PHYSICAL_TYPES + MAGIC_TYPES

TRAP_DEFAULTS = {"armed": False, "detect_dc": 15, "disarm_dc": 15, "save": "Dex",
                 "save_dc": 13, "num_dice": 2, "die_size": 10, "bonus": 0,
                 "damage_type": "Poison", "half_on_save": True, "poisons": False}
CHEST_DEFAULTS = {"locked": False, "lock_dc": 15, "break_dc": 15, "arcane_lock": False}


# ── Items ────────────────────────────────────────────────────────────────────
def is_key(rec: dict) -> bool:
    return rec.get("kind") == "item" and (rec.get("record") or {}).get("type") == "Key"


def display_name(rec: dict) -> str:
    return rec.get("label") or (rec.get("record") or {}).get("name") or "item"


def make_item(kind: str, record: dict, pid: int, cell=None, label: str = "") -> dict:
    """A design item record for a catalog entry."""
    if kind not in KINDS:
        raise ValueError(f"unknown item kind {kind!r}")
    rec = {"pid": int(pid), "kind": kind, "record": copy.deepcopy(record), "label": label or ""}
    if cell is not None:
        rec["cell"] = [int(cell[0]), int(cell[1])]
    return rec


def to_map_item(rec: dict, cell=None):
    """An rpg.MapItem for a design item record (on ``cell``, else the record's cell)."""
    m = rpg.MapItem()
    kind = rec.get("kind", "weapon")
    m.kind = getattr(rpg.MapItemKind, _KIND_ENUM.get(kind, "Weapon"))
    body = rec.get("record") or {}
    if kind == "weapon":
        m.weapon = _dict_to_weapon(body)
        m.sprite_path = body.get("sprite_path", "") or ""
    elif kind == "armor":
        m.armor = _dict_to_armor(body)
    else:
        it = _dict_to_item(body)
        it.quantity = max(1, int(body.get("quantity", 1)))
        m.item = it
        m.sprite_path = body.get("sprite_path", "") or ""
    m.pid = int(rec.get("pid", -1))
    m.label = rec.get("label", "") or ""
    c = cell if cell is not None else rec.get("cell")
    if c is not None:
        m.cell = rpg.Cell(int(c[0]), int(c[1]))
    return m


def next_pid(design_items: list, design_chests: list) -> int:
    pids = [int(r.get("pid", -1)) for r in design_items]
    for ch in design_chests:
        pids += [int(r.get("pid", -1)) for r in ch.get("contents", []) or []]
    return max(pids, default=0) + 1


def floor_state(bm) -> list:
    """The design items on the floor now, as ``[{"pid", "cell"}]``."""
    return [{"pid": int(m.pid), "cell": [m.cell.col, m.cell.row]}
            for m in bm.get_all_items() if m.pid >= 0]


def design_floor_items(bm) -> list:
    return [m for m in bm.get_all_items() if m.pid >= 0]


def remove_design_floor_items(bm) -> None:
    for m in design_floor_items(bm):
        bm.remove_item(m.id)


def place_floor_items(bm, design_items: list, state: list | None) -> None:
    """Put the design floor items on the map: every one when ``state`` is None (a fresh
    run), else only those the state still has, on the state's cells. Any design item
    already on the map is removed first."""
    remove_design_floor_items(bm)
    by_pid = {int(r["pid"]): r for r in design_items if "pid" in r}
    if state is None:
        for rec in design_items:
            if rec.get("cell") is not None:
                bm.place_map_item(to_map_item(rec))
        return
    for s in state:
        rec = by_pid.get(int(s.get("pid", -1)))
        if rec is not None:
            bm.place_map_item(to_map_item(rec, s.get("cell") or rec.get("cell")))


def keep_design_items(bm):
    """Snapshot the design floor items so a caller can wipe the map's items (a scene's
    agents reload clears dropped weapons) and put these back. Returns a restore()."""
    kept = design_floor_items(bm)

    def restore():
        have = {m.pid for m in bm.get_all_items()}
        for m in kept:
            if m.pid not in have:
                bm.place_map_item(m)
    return restore


# ── Chests ───────────────────────────────────────────────────────────────────
def make_chest(cid: int, cell, **kw) -> dict:
    rec = {"id": int(cid), "cell": [int(cell[0]), int(cell[1])], "name": f"Chest {cid}",
           **CHEST_DEFAULTS, "trap": dict(TRAP_DEFAULTS), "contents": []}
    rec.update(kw)
    return rec


def next_chest_id(design_chests: list) -> int:
    return max((int(c.get("id", 0)) for c in design_chests), default=0) + 1


def _trap_from(design: dict):
    t = rpg.ChestTrap()
    d = {**TRAP_DEFAULTS, **(design or {})}
    t.armed = bool(d["armed"])
    t.detect_dc = int(d["detect_dc"])
    t.disarm_dc = int(d["disarm_dc"])
    save = d["save"] if d["save"] in SAVES else "Dex"
    t.save_ability = getattr(rpg.SaveAbility, "Save" + save)
    t.save_dc = int(d["save_dc"])
    t.num_dice = int(d["num_dice"])
    t.die_size = int(d["die_size"])
    t.bonus = int(d["bonus"])
    dtype = d["damage_type"] if d["damage_type"] in DAMAGE_TYPES else "Poison"
    t.physical = dtype in PHYSICAL_TYPES
    t.damage_type = (PHYSICAL_TYPES.index(dtype) if t.physical else MAGIC_TYPES.index(dtype))
    t.half_on_save = bool(d["half_on_save"])
    t.poisons = bool(d["poisons"])
    return t


def to_chest(design: dict, state: dict | None = None):
    """An rpg.Chest from its design and (optionally) its play state."""
    c = rpg.Chest()
    c.id = int(design["id"])
    c.cell = rpg.Cell(int(design["cell"][0]), int(design["cell"][1]))
    c.name = design.get("name") or f"Chest {c.id}"
    c.locked = bool(design.get("locked", False))
    c.lock_dc = int(design.get("lock_dc", 15))
    c.break_dc = int(design.get("break_dc", 15))
    c.arcane_lock = bool(design.get("arcane_lock", False))
    trap = _trap_from(design.get("trap"))
    contents = list(design.get("contents", []) or [])
    if state is not None:
        c.open = bool(state.get("open", False))
        c.locked = bool(state.get("locked", c.locked))
        c.broken = bool(state.get("broken", False))
        c.arcane_suppressed_turns = int(state.get("arcane_suppressed_turns", 0))
        ts = state.get("trap") or {}
        trap.found = bool(ts.get("found", False))
        trap.disarmed = bool(ts.get("disarmed", False))
        trap.fired = bool(ts.get("fired", False))
        if "contents" in state:
            left = {int(p) for p in state.get("contents") or []}
            contents = [r for r in contents if int(r.get("pid", -1)) in left]
    c.trap = trap
    c.contents = [to_map_item(r, design["cell"]) for r in contents]
    return c


def chest_state(chest) -> dict:
    return {"id": chest.id, "open": chest.open, "locked": chest.locked,
            "broken": chest.broken, "arcane_suppressed_turns": chest.arcane_suppressed_turns,
            "trap": {"found": chest.trap.found, "disarmed": chest.trap.disarmed,
                     "fired": chest.trap.fired},
            "contents": [m.pid for m in chest.contents if m.pid >= 0]}


def place_chests(bm, design_chests: list, state: list | None) -> None:
    """Rebuild the map's chests from their designs and play state."""
    bm.clear_chests()
    by_id = {int(s["id"]): s for s in state or [] if "id" in s}
    for d in design_chests:
        try:
            bm.add_chest(to_chest(d, by_id.get(int(d["id"]))))
        except (KeyError, TypeError, ValueError):
            continue


def chests_state(bm) -> list:
    return [chest_state(c) for c in bm.chests]


# ── Keys ─────────────────────────────────────────────────────────────────────
def key_opens(item) -> list:
    """What an rpg.Item key unlocks ("chest:<id>" / "door:<key>")."""
    if item.type != rpg.ItemType.Key:
        return []
    return list(item.opens)


def door_ref(door_key_tuple) -> str:
    """The ``opens`` token for a door, from run_state.door_key."""
    kind, *parts = door_key_tuple
    return "door:" + kind + ":" + ";".join(",".join(str(v) for v in p) for p in parts)
