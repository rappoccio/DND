#!/usr/bin/env python3
"""
Chests and placed items, engine side (plans/ITEMS_AND_CHESTS_PLAN.md I1 + I2).

I1: MapItem kinds (weapon / armor / consumable), the Key item type, the Chest model on
BattleMap (add / replace / remove, open / close / break / knock, contents), and a chest
blocking its cell to walkers but not to fliers.

I2: the chest checks on CombatEngine — Pick Lock (Sleight of Hand), Break Open
(Athletics, +10 under Arcane Lock), Search (Perception / Investigation), Disarm — and the
trap: it fires once, on opening / breaking / a pick or disarm failed by 5+, and Knock
unlocks a chest without opening it.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _free_cell(bm, near=(6, 6)):
    """A cell walkers can stand on, scanning outward from ``near``."""
    for r in range(near[1], bm.grid_rows):
        for c in range(near[0], bm.grid_cols):
            cell = rpg.Cell(c, r)
            if not bm.is_blocked(cell, 1):
                return cell
    raise AssertionError("no free cell on the test map")


def _chest(cell, **kw):
    ch = rpg.Chest()
    ch.cell = cell
    for k, v in kw.items():
        setattr(ch, k, v)
    return ch


def _agent(bm, engine, name="Rogue", col=3, row=3, **stats):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    s = engine.get_agent_stats(bm, idx)
    for k, v in stats.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)
    return idx


def _trap(**kw):
    t = rpg.ChestTrap()
    t.armed = True
    for k, v in kw.items():
        setattr(t, k, v)
    return t


# ── I1: model ────────────────────────────────────────────────────────────────

def test_map_item_kinds_and_names():
    """A MapItem's name is its label, else its weapon / armor / item name."""
    m = rpg.MapItem()
    assert m.kind == rpg.MapItemKind.Weapon, "default kind is Weapon (dropped weapons)"
    m.weapon.name = "Dagger"
    assert m.name == "Dagger"
    m.kind = rpg.MapItemKind.Armor
    m.armor.name = "Chain Mail"
    assert m.name == "Chain Mail"
    m.kind = rpg.MapItemKind.Consumable
    m.item.name = "Key"
    m.item.type = rpg.ItemType.Key
    m.item.opens = ["chest:1"]
    assert m.name == "Key" and list(m.item.opens) == ["chest:1"]
    m.label = "Crypt key"
    assert m.name == "Crypt key", "a label overrides the catalog name"
    print("✅ MapItem kinds, Key type and labels")


def test_place_map_item_and_weapon_only_pickup():
    """place_map_item keeps the kind; pick_up_item refuses a non-weapon item."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine)
    m = rpg.MapItem()
    m.kind = rpg.MapItemKind.Consumable
    m.item.name = "Potion of Healing"
    m.cell = rpg.Cell(3, 3)
    m.pid = 7
    iid = bm.place_map_item(m)
    items = bm.get_items_at_cell(rpg.Cell(3, 3))
    assert len(items) == 1 and items[0].id == iid and items[0].pid == 7
    assert items[0].kind == rpg.MapItemKind.Consumable
    assert not bm.pick_up_item(iid, idx), "only weapons go through pick_up_item"
    assert len(bm.get_all_items()) == 1, "a refused pickup leaves the item on the map"
    print("✅ place_map_item + weapon-only pick_up_item")


def test_chest_add_replace_remove():
    bm = setup_battle_map()
    cell = _free_cell(bm)
    cid = bm.add_chest(_chest(cell))
    assert cid == 1 and bm.chests[0].name == "Chest 1", "ids start at 1 with a default name"
    assert bm.chest_at(cell) == 0 and bm.chest_index(cid) == 0
    cid2 = bm.add_chest(_chest(cell, locked=True))
    assert len(bm.chests) == 1 and cid2 == 2, "a chest on the same cell replaces the old one"
    kept = bm.add_chest(_chest(rpg.Cell(cell.col + 1, cell.row), id=9))
    assert kept == 9, "a free given id is kept (save reload)"
    assert bm.add_chest(_chest(rpg.Cell(cell.col + 2, cell.row))) == 10, "ids move past it"
    bm.remove_chest(cid2)
    assert bm.chest_at(cell) == -1
    bm.clear_chests()
    assert not bm.chests
    print("✅ chest add / replace / remove")


def test_chest_blocks_walkers_not_fliers():
    bm = setup_battle_map()
    cell = _free_cell(bm)
    assert not bm.is_blocked(cell, 1)
    bm.add_chest(_chest(cell))
    assert bm.is_blocked(cell, 1), "a chest blocks its cell"
    assert bm.is_blocked(cell, 1, rpg.MovementType.Walk)
    assert not bm.is_blocked(cell, 1, rpg.MovementType.Fly), "a flier passes over a chest"
    print("✅ chest blocks walkers, not fliers")


def test_chest_open_close_break_knock():
    bm = setup_battle_map()
    cid = bm.add_chest(_chest(_free_cell(bm), locked=True))
    assert not bm.open_chest(cid), "a locked chest won't open"
    bm.unlock_chest(cid)
    assert bm.open_chest(cid) and bm.chests[0].open
    assert bm.close_chest(cid) and not bm.chests[0].open
    assert bm.break_chest(cid)
    c = bm.chests[0]
    assert c.broken and c.open and not c.locked
    assert not bm.close_chest(cid), "a broken chest can't be closed"

    cid = bm.add_chest(_chest(rpg.Cell(1, 1), locked=True, arcane_lock=True))
    i = bm.chest_index(cid)
    assert bm.knock_chest(cid)
    c = bm.chests[i]
    assert not c.locked and c.arcane_suppressed_turns > 0 and not c.open, \
        "Knock unlocks and suppresses, but doesn't lift the lid"
    assert bm.open_chest(cid)
    print("✅ chest open / close / break / knock")


def test_chest_contents():
    bm = setup_battle_map()
    cell = _free_cell(bm)
    m = rpg.MapItem()
    m.kind = rpg.MapItemKind.Armor
    m.armor.name = "Shield"
    ch = _chest(cell)
    ch.contents = [m]
    cid = bm.add_chest(ch)
    contents = bm.chests[0].contents
    assert len(contents) == 1 and contents[0].id >= 0, "contents get item ids"
    assert contents[0].cell.col == cell.col and contents[0].cell.row == cell.row
    d = rpg.MapItem()
    d.weapon.name = "Dagger"
    bm.add_to_chest(cid, d)
    assert [x.name for x in bm.chests[0].contents] == ["Shield", "Dagger"]
    took = bm.take_from_chest(cid, contents[0].id)
    assert took is not None and took.name == "Shield"
    assert bm.take_from_chest(cid, 9999) is None
    assert [x.name for x in bm.chests[0].contents] == ["Dagger"]
    assert not bm.get_all_items(), "contents are not floor items"
    print("✅ chest contents add / take")


# ── I2: checks and traps ─────────────────────────────────────────────────────

def test_pick_chest_lock():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine, dex=20, sleight_of_hand_prof=True, sleight_of_hand_expertise=True)
    cid = bm.add_chest(_chest(_free_cell(bm), locked=True, lock_dc=1))
    r = engine.attempt_pick_chest_lock(bm, idx, cid)
    assert r.valid and r.success and r.roll > 0
    assert not bm.chests[0].locked and not bm.chests[0].open, "picked: unlocked, still shut"

    cid = bm.add_chest(_chest(rpg.Cell(1, 1), locked=True, arcane_lock=True, lock_dc=1))
    r = engine.attempt_pick_chest_lock(bm, idx, cid)
    assert r.valid and not r.success and r.roll == 0, "an Arcane Lock can't be picked"
    print("✅ pick a chest's lock")


def test_pick_fail_by_five_fires_trap():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine, dex=1)
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    cid = bm.add_chest(_chest(_free_cell(bm), locked=True, lock_dc=40))
    bm.set_chest_trap(cid, _trap(num_dice=1, die_size=1, bonus=4, save_dc=40, half_on_save=False))
    r = engine.attempt_pick_chest_lock(bm, idx, cid)
    assert r.valid and not r.success and r.total <= r.dc - 5
    assert r.trap.fired and r.trap.damage == 5, f"trap fired for 1d1+4, got {r.trap.damage}"
    assert engine.get_agent_stats(bm, idx).hp_cur == 195
    t = bm.chests[0].trap
    assert t.fired and t.found
    r = engine.attempt_pick_chest_lock(bm, idx, cid)
    assert not r.trap.fired, "a trap fires once"
    print("✅ a pick failed by 5+ fires the trap, once")


def test_break_chest_and_arcane_plus_ten():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine, str=30, athletics_prof=True)
    cid = bm.add_chest(_chest(_free_cell(bm), locked=True, break_dc=5, arcane_lock=True))
    r = engine.attempt_break_chest(bm, idx, cid)
    assert r.valid and r.dc == 15, "an active Arcane Lock adds 10 to the break DC"
    if r.success:
        c = bm.chests[0]
        assert c.broken and c.open and not c.locked
    r2 = engine.attempt_break_chest(bm, idx, cid) if r.success else None
    if r2 is not None:
        assert r2.valid and r2.roll == 0, "an open chest needs no breaking"
    print("✅ break a chest; Arcane Lock +10")


def test_break_open_fires_trap():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine, str=30, athletics_prof=True)
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    cid = bm.add_chest(_chest(_free_cell(bm), locked=True, break_dc=1))
    bm.set_chest_trap(cid, _trap(num_dice=2, die_size=1, bonus=0, save_dc=40, half_on_save=False))
    r = engine.attempt_break_chest(bm, idx, cid)
    assert r.success and r.trap.fired and r.trap.damage == 2
    print("✅ breaking a chest open sets its trap off")


def test_trigger_save_for_half_and_poison():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine)
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    cid = bm.add_chest(_chest(_free_cell(bm)))
    # DC 1: always saved → half of 1d1+9 = 5, no poison.
    bm.set_chest_trap(cid, _trap(num_dice=1, die_size=1, bonus=9, save_dc=1, poisons=True))
    r = engine.trigger_chest_trap(bm, idx, cid)
    assert r.fired and r.saved and r.damage == 5 and not r.poisoned
    # DC 40: always failed → full damage + Poisoned.
    cid2 = bm.add_chest(_chest(rpg.Cell(1, 1)))
    bm.set_chest_trap(cid2, _trap(num_dice=1, die_size=1, bonus=9, save_dc=40, poisons=True))
    r = engine.trigger_chest_trap(bm, idx, cid2)
    assert r.fired and not r.saved and r.damage == 10 and r.poisoned
    assert engine.get_agent_conditions(bm, idx).poisoned
    # No trap / disarmed: nothing.
    cid3 = bm.add_chest(_chest(rpg.Cell(2, 1)))
    assert not engine.trigger_chest_trap(bm, idx, cid3).fired
    print("✅ trap save-for-half, poison, no-trap no-op")


def test_trap_damage_respects_resistance():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine)
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = s.hp_cur = 200
    mm = list(s.magic_damage_multipliers)
    mm[int(rpg.MagicDamage.Fire)] = 0.0
    s.magic_damage_multipliers = mm
    engine.set_agent_stats(bm, idx, s)
    cid = bm.add_chest(_chest(_free_cell(bm)))
    bm.set_chest_trap(cid, _trap(num_dice=1, die_size=1, bonus=9, save_dc=40,
                                 damage_type=int(rpg.MagicDamage.Fire)))
    r = engine.trigger_chest_trap(bm, idx, cid)
    assert r.fired and r.damage == 0, "Fire immunity zeroes a fire trap"
    print("✅ trap damage honours immunity")


def test_find_and_disarm():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _agent(bm, engine, wis=30, dex=30, sleight_of_hand_prof=True)
    cid = bm.add_chest(_chest(_free_cell(bm)))
    r = engine.attempt_disarm_chest_trap(bm, idx, cid)
    assert r.valid and r.roll == 0, "nothing to disarm before a trap is found"
    bm.set_chest_trap(cid, _trap(detect_dc=1, disarm_dc=1))
    r = engine.attempt_find_chest_trap(bm, idx, cid)
    assert r.success and bm.chests[0].trap.found
    r = engine.attempt_disarm_chest_trap(bm, idx, cid)
    assert r.success and bm.chests[0].trap.disarmed
    assert not engine.trigger_chest_trap(bm, idx, cid).fired, "a disarmed trap never fires"

    cid2 = bm.add_chest(_chest(rpg.Cell(1, 1)))
    r = engine.attempt_find_chest_trap(bm, idx, cid2)
    assert r.valid and not r.success and r.roll > 0, "a search of an untrapped chest finds nothing"
    print("✅ search and disarm")


def test_knock_spell_unlocks_chest():
    """Knock cast at a chest's cell unlocks it (no door there) and leaves it shut."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    cell = _free_cell(bm)
    cid = bm.add_chest(_chest(cell, locked=True))
    knock = rpg.Spell()
    knock.name = "Knock"
    knock.opens_doors = True
    idx = _agent(bm, engine, "Wizard", cell.col - 1 if cell.col > 0 else cell.col + 1, cell.row)
    engine.set_agent_spells(bm, idx, [knock])
    act = rpg.SpellAction()
    act.caster_idx = idx
    act.spell_idx = 0
    act.aoe_col, act.aoe_row = cell.col, cell.row
    engine.execute_spell(bm, act)
    c = bm.chests[bm.chest_index(cid)]
    assert not c.locked and not c.open, "Knock springs the lock, the lid stays shut"
    print("✅ Knock unlocks a chest")


if __name__ == "__main__":
    tests = [
        test_map_item_kinds_and_names,
        test_place_map_item_and_weapon_only_pickup,
        test_chest_add_replace_remove,
        test_chest_blocks_walkers_not_fliers,
        test_chest_open_close_break_knock,
        test_chest_contents,
        test_pick_chest_lock,
        test_pick_fail_by_five_fires_trap,
        test_break_chest_and_arcane_plus_ten,
        test_break_open_fires_trap,
        test_trigger_save_for_half_and_poison,
        test_trap_damage_respects_resistance,
        test_find_and_disarm,
        test_knock_spell_unlocks_chest,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} chest tests passed")
    sys.exit(1 if failed else 0)
