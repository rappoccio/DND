#!/usr/bin/env python3
"""
Unit tests for items.

Two distinct things share the word "item" here:
  · MapItem  — a weapon lying on the ground (place/pickup/drop).
  · Item     — a carried consumable from items.json (healing potions), used through
               CombatEngine::useItem: a Bonus Action to drink one yourself or
               administer it to a creature within 5 ft.
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _dict_to_weapon, _dict_to_item, _item_to_dict
from test_helpers import (TEST_MAP_PATH, setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)

_ITEMS_JSON = os.path.join(os.path.dirname(__file__), "items.json")


def _catalog_item(name: str):
    """Build an rpg.Item straight from the items.json catalog (the GUI's path)."""
    with open(_ITEMS_JSON) as f:
        for rec in json.load(f):
            if rec["name"] == name:
                return _dict_to_item(rec)
    raise ValueError(f"Item {name} not found in items.json")

def test_map_item_creation():
    """Test creating MapItem objects."""
    cell = rpg.Cell(5, 10)
    weapon = rpg.Weapon()
    weapon.name = "Longsword"
    item = rpg.MapItem()
    item.id = 1
    item.cell = cell
    item.weapon = weapon
    item.sprite_path = "sprites/longsword.png"

    assert item.id == 1
    assert item.cell.col == 5
    assert item.cell.row == 10
    assert item.weapon.name == "Longsword"
    assert item.sprite_path == "sprites/longsword.png"
    print("✅ MapItem creation")

def test_place_item():
    """Test placing items on the battle map."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    weapon = rpg.Weapon()
    weapon.name = "Rapier"
    weapon.type = rpg.WeaponType.Melee

    cell = rpg.Cell(5, 5)
    item_id = bm.place_item(cell, weapon, "")

    assert item_id >= 0, "Should return a valid item ID"
    items = bm.get_items_at_cell(cell)
    assert len(items) == 1, "Should have 1 item at that cell"
    assert items[0].weapon.name == "Rapier"
    print("✅ Place item")

def test_get_items_at_cell():
    """Test retrieving items from specific cells."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    # Place items at different cells
    w1 = rpg.Weapon()
    w1.name = "Sword"
    w2 = rpg.Weapon()
    w2.name = "Bow"

    cell1 = rpg.Cell(3, 3)
    cell2 = rpg.Cell(3, 4)

    id1 = bm.place_item(cell1, w1, "")
    id2 = bm.place_item(cell1, w2, "")
    id3 = bm.place_item(cell2, w1, "")

    # Check cell1 has 2 items
    items_cell1 = bm.get_items_at_cell(cell1)
    assert len(items_cell1) == 2
    assert items_cell1[0].weapon.name == "Sword"
    assert items_cell1[1].weapon.name == "Bow"

    # Check cell2 has 1 item
    items_cell2 = bm.get_items_at_cell(cell2)
    assert len(items_cell2) == 1
    assert items_cell2[0].weapon.name == "Sword"

    # Check empty cell
    empty_items = bm.get_items_at_cell(rpg.Cell(10, 10))
    assert len(empty_items) == 0
    print("✅ Get items at cell")

def test_remove_item():
    """Test removing items from the map."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    w = rpg.Weapon()
    w.name = "Dagger"
    cell = rpg.Cell(4, 4)

    id1 = bm.place_item(cell, w, "")
    assert len(bm.get_items_at_cell(cell)) == 1

    bm.remove_item(id1)
    assert len(bm.get_items_at_cell(cell)) == 0
    print("✅ Remove item")

def test_get_all_items():
    """Test retrieving all items on the map."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    w1 = rpg.Weapon()
    w1.name = "Sword"
    w2 = rpg.Weapon()
    w2.name = "Axe"

    bm.place_item(rpg.Cell(2, 2), w1, "")
    bm.place_item(rpg.Cell(3, 3), w2, "")
    bm.place_item(rpg.Cell(4, 4), w1, "")

    all_items = bm.get_all_items()
    assert len(all_items) == 3
    weapon_names = [item.weapon.name for item in all_items]
    assert "Sword" in weapon_names
    assert "Axe" in weapon_names
    print("✅ Get all items")

def test_clear_items():
    """Test clearing all items from the map."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    w = rpg.Weapon()
    w.name = "Bow"
    bm.place_item(rpg.Cell(1, 1), w, "")
    bm.place_item(rpg.Cell(2, 2), w, "")

    assert len(bm.get_all_items()) == 2
    bm.clear_items()
    assert len(bm.get_all_items()) == 0
    print("✅ Clear items")

def test_item_with_sprite_path():
    """Test items with custom sprite paths."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    w = rpg.Weapon()
    w.name = "Magic Sword"
    sprite_path = "sprites/items/magic_sword.png"

    cell = rpg.Cell(6, 6)
    bm.place_item(cell, w, sprite_path)

    items = bm.get_items_at_cell(cell)
    assert len(items) == 1
    assert items[0].sprite_path == sprite_path
    print("✅ Item with sprite path")

def test_multiple_items_same_cell():
    """Test placing multiple items on the same cell."""
    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    cell = rpg.Cell(7, 7)
    weapons = []
    ids = []

    for i in range(5):
        w = rpg.Weapon()
        w.name = f"Weapon{i}"
        weapons.append(w)
        ids.append(bm.place_item(cell, w, ""))

    items = bm.get_items_at_cell(cell)
    assert len(items) == 5
    for i, item in enumerate(items):
        assert item.weapon.name == f"Weapon{i}"

    # Remove one item
    bm.remove_item(ids[2])
    items = bm.get_items_at_cell(cell)
    assert len(items) == 4
    assert not any(item.id == ids[2] for item in items)
    print("✅ Multiple items same cell")

def test_cell_equality():
    """Test Cell equality for item placement."""
    cell1 = rpg.Cell(5, 5)
    cell2 = rpg.Cell(5, 5)
    cell3 = rpg.Cell(5, 6)

    assert cell1 == cell2
    assert cell1 != cell3

    bm = rpg.BattleMap(TEST_MAP_PATH)
    bm.analyze_grid()

    w = rpg.Weapon()
    w.name = "Test"
    bm.place_item(cell1, w, "")

    # Should find item using equivalent cell
    items = bm.get_items_at_cell(cell2)
    assert len(items) == 1
    print("✅ Cell equality")

# ─────────────────────────────────────────────────────────────────────────────
#  Carried consumables (items.json → rpg.Item → CombatEngine::use_item)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_two(hp=30, gap=1):
    """A user and a target `gap` cells apart, both at full HP, with a fresh engine."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    user = add_agent_to_battle(engine, bm, create_test_agent("Drinker", 5, 5, hp=hp), hp=hp)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5 + gap, 5, hp=hp), hp=hp)
    # apply_agent_configs (inside add_agent_to_battle) rebuilds the agent list, so give
    # out the potions only once every agent is placed.
    return bm, engine, user, ally


def test_potion_catalog_parses():
    """items.json records become rpg.Items with the right dice / action / reach."""
    p = _catalog_item("Potion of Healing")
    assert p.name == "Potion of Healing"
    assert p.type == rpg.ItemType.Heal
    assert p.action_type == rpg.ItemAction.BonusAction
    assert p.range == 5, f"potion reach should be 5 ft, got {p.range}"
    assert (p.healing.num_dice, p.healing.die_size, p.healing.bonus) == (2, 4, 2)
    assert p.consumable

    for name, dice in (("Greater Potion of Healing",  (4, 4, 4)),
                       ("Superior Potion of Healing", (8, 4, 8)),
                       ("Supreme Potion of Healing",  (10, 4, 20))):
        it = _catalog_item(name)
        assert (it.healing.num_dice, it.healing.die_size, it.healing.bonus) == dice, \
            f"{name} should heal {dice}, got {it.healing}"
    print("✅ items.json potions parse (2d4+2 / 4d4+4 / 8d4+8 / 10d4+20)")


def test_drink_potion_self():
    """Drinking your own potion heals 2d4+2, spends the Bonus Action, and burns the charge."""
    bm, engine, user, _ = _setup_two(hp=30)
    engine.set_agent_items(bm, user, [_catalog_item("Potion of Healing")])

    s = engine.get_agent_stats(bm, user)
    s.hp_cur = 5
    engine.set_agent_stats(bm, user, s)
    engine.begin_turn(bm, user)   # refill the bonus action

    res = engine.use_item(bm, user, 0, user)
    assert res.valid, "drinking your own potion should be legal"
    assert 4 <= res.amount_healed <= 10, f"2d4+2 is 4..10, got {res.amount_healed}"
    assert res.consumed, "the only charge should have been used up"
    assert engine.get_agent_stats(bm, user).hp_cur == 5 + res.amount_healed
    assert engine.get_agent_stats(bm, user).bonus_actions_remaining == 0, "Bonus Action not spent"
    assert engine.get_agent_items(bm, user) == [], "the empty potion should leave the pack"
    print("✅ Drink potion (self): heals 2d4+2, spends the Bonus Action, consumes the charge")


def test_administer_potion_to_adjacent_ally():
    """A potion can be poured into an adjacent ally instead of drunk."""
    bm, engine, user, ally = _setup_two(hp=30, gap=1)
    engine.set_agent_items(bm, user, [_catalog_item("Potion of Healing")])

    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 3
    engine.set_agent_stats(bm, ally, s)
    engine.begin_turn(bm, user)

    res = engine.use_item(bm, user, 0, ally)
    assert res.valid, "an adjacent ally is within the potion's 5 ft reach"
    assert 4 <= res.amount_healed <= 10
    assert engine.get_agent_stats(bm, ally).hp_cur == 3 + res.amount_healed
    assert engine.get_agent_stats(bm, user).hp_cur == 30, "the user should not heal itself"
    print("✅ Administer potion to an adjacent ally")


def test_potion_out_of_reach_costs_nothing():
    """Beyond 5 ft the use is rejected — no heal, no charge, no Bonus Action."""
    bm, engine, user, ally = _setup_two(hp=30, gap=3)   # 3 cells = 15 ft
    engine.set_agent_items(bm, user, [_catalog_item("Potion of Healing")])

    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 3
    engine.set_agent_stats(bm, ally, s)
    engine.begin_turn(bm, user)

    res = engine.use_item(bm, user, 0, ally)
    assert not res.valid, "15 ft away is out of a potion's 5 ft reach"
    assert engine.get_agent_stats(bm, ally).hp_cur == 3, "no healing should have happened"
    assert engine.get_agent_items(bm, user)[0].quantity == 1, "the charge must not be spent"
    assert engine.get_agent_stats(bm, user).bonus_actions_remaining == 1, \
        "a rejected use must not eat the Bonus Action"
    print("✅ Out-of-reach potion is rejected and costs nothing")


def test_potion_revives_downed_ally():
    """Pouring a potion into a downed (0 HP) ally brings it back to consciousness."""
    bm, engine, user, ally = _setup_two(hp=30, gap=1)
    engine.set_agent_items(bm, user, [_catalog_item("Potion of Healing")])

    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 0
    engine.set_agent_stats(bm, ally, s)
    c = engine.get_agent_conditions(bm, ally)
    c.unconscious = True
    c.incapacitated = True
    c.prone = True
    c.death_save_failures = 2
    engine.set_agent_conditions(bm, ally, c)
    engine.begin_turn(bm, user)

    res = engine.use_item(bm, user, 0, ally)
    assert res.valid
    assert engine.get_agent_stats(bm, ally).hp_cur >= 4
    c = engine.get_agent_conditions(bm, ally)
    assert not c.unconscious, "the healed ally should be conscious again"
    assert c.death_save_failures == 0, "death saves should be reset"
    print("✅ Potion revives a downed ally (heal_agent → revive_on_heal)")


def test_potion_needs_a_bonus_action():
    """With the Bonus Action already spent, the potion can't be used."""
    bm, engine, user, _ = _setup_two(hp=30)
    engine.set_agent_items(bm, user, [_catalog_item("Potion of Healing")])

    s = engine.get_agent_stats(bm, user)
    s.hp_cur = 5
    engine.set_agent_stats(bm, user, s)
    engine.begin_turn(bm, user)
    assert engine.spend_bonus_action(bm, user), "the setup should consume the bonus action"

    res = engine.use_item(bm, user, 0, user)
    assert not res.valid, "no Bonus Action left ⇒ the potion cannot be used"
    assert engine.get_agent_stats(bm, user).hp_cur == 5, "no healing without the action"
    assert engine.get_agent_items(bm, user)[0].quantity == 1, "the charge must survive"
    print("✅ Using a potion requires an unspent Bonus Action")


def test_potion_stack_decrements():
    """A stack of potions loses one charge per use and disappears when empty."""
    bm, engine, user, _ = _setup_two(hp=40)
    potion = _catalog_item("Potion of Healing")
    potion.quantity = 2
    engine.set_agent_items(bm, user, [potion])

    s = engine.get_agent_stats(bm, user)
    s.hp_cur = 1
    engine.set_agent_stats(bm, user, s)

    engine.begin_turn(bm, user)
    res = engine.use_item(bm, user, 0, user)
    assert res.valid and not res.consumed, "one of two potions used — the stack survives"
    assert engine.get_agent_items(bm, user)[0].quantity == 1

    engine.begin_turn(bm, user)   # new turn ⇒ new bonus action
    res = engine.use_item(bm, user, 0, user)
    assert res.valid and res.consumed, "the second use empties the stack"
    assert engine.get_agent_items(bm, user) == []

    engine.begin_turn(bm, user)
    res = engine.use_item(bm, user, 0, user)
    assert not res.valid, "an empty pack has nothing to use"
    print("✅ Potion stack decrements, then leaves the pack when empty")


def test_add_item_to_agent_stacks_by_name():
    """add_item_to_agent bumps the quantity of a potion already carried."""
    bm, engine, user, _ = _setup_two()
    engine.add_item_to_agent(bm, user, _catalog_item("Potion of Healing"))
    engine.add_item_to_agent(bm, user, _catalog_item("Potion of Healing"))
    engine.add_item_to_agent(bm, user, _catalog_item("Greater Potion of Healing"))

    inv = engine.get_agent_items(bm, user)
    assert len(inv) == 2, f"two distinct potions expected, got {[i.name for i in inv]}"
    assert inv[0].name == "Potion of Healing" and inv[0].quantity == 2
    assert inv[1].name == "Greater Potion of Healing" and inv[1].quantity == 1
    print("✅ add_item_to_agent stacks identical potions by name")


def test_item_dict_round_trip():
    """_item_to_dict → _dict_to_item preserves everything a save needs (quantity included)."""
    it = _catalog_item("Greater Potion of Healing")
    it.quantity = 3
    back = _dict_to_item(_item_to_dict(it))

    assert back.name == it.name
    assert back.type == it.type
    assert back.action_type == it.action_type
    assert back.range == it.range
    assert back.quantity == 3, "quantity must survive the save round-trip"
    assert back.consumable == it.consumable
    assert (back.healing.num_dice, back.healing.die_size, back.healing.bonus) == \
           (it.healing.num_dice, it.healing.die_size, it.healing.bonus)
    print("✅ Item save round-trip (_item_to_dict → _dict_to_item)")


def run_tests():
    """Run all item tests."""
    print("\n" + "="*50)
    print("Testing Map Items + Carried Consumables")
    print("="*50 + "\n")

    tests = [
        test_map_item_creation,
        test_place_item,
        test_get_items_at_cell,
        test_remove_item,
        test_get_all_items,
        test_clear_items,
        test_item_with_sprite_path,
        test_multiple_items_same_cell,
        test_cell_equality,
        # Carried consumables (potions)
        test_potion_catalog_parses,
        test_drink_potion_self,
        test_administer_potion_to_adjacent_ally,
        test_potion_out_of_reach_costs_nothing,
        test_potion_revives_downed_ally,
        test_potion_needs_a_bonus_action,
        test_potion_stack_decrements,
        test_add_item_to_agent_stacks_by_name,
        test_item_dict_round_trip,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "="*50)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*50 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
