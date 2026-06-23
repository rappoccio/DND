#!/usr/bin/env python3
"""
Unit tests for map items (weapons on the ground) functionality.
Tests C++ item placement/retrieval and Python pickup/drop logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _dict_to_weapon
from test_helpers import TEST_MAP_PATH

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

def run_tests():
    """Run all item tests."""
    print("\n" + "="*50)
    print("Testing Map Items Functionality")
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
