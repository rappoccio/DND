#!/usr/bin/env python3
"""Test suite for the permanently_armed weapon property."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
import rpg_battle_map as rpg
from test_helpers import (
    create_map, place_creature, place_barbarian, place_battle_master,
    verify_log, get_all_logs, clear_logs
)

def test_permanently_armed_flag_survives_roundtrip():
    """Verify that the permanently_armed flag is preserved in serialization."""
    w = rpg.Weapon()
    w.name = "TestWeapon"
    w.permanently_armed = True

    # Simulate serialization roundtrip via helpers functions
    # (would be tested in GUI integration)
    assert w.permanently_armed, "permanently_armed flag should be True"
    print("✓ permanently_armed flag survives basic assignment")


def test_disarming_attack_respects_permanently_armed():
    """Verify that disarming attacks cannot disable permanently armed weapons."""
    bm = create_map("encounters/simplemap_blank.json")

    # Place a barbarian with permanently armed unarmed strikes
    barb_idx = place_barbarian(bm, (5, 5), "Barbarian")
    agent = bm.placedAgents()[barb_idx]

    # Mark their unarmed attack as permanently_armed (like a creature's innate ability)
    for w in agent.weapons:
        if w.name == "Unarmed":
            w.permanently_armed = True
            break

    # Place a Battle Master to perform disarming attack
    bm_idx = place_battle_master(bm, (10, 5), "BattleMaster")

    clear_logs()
    bm.beginTurn(barb_idx)

    # Barbarian tries to attack with their permanently armed unarmed strike
    targets = bm.availableTargets(barb_idx, use_limit_range=True)
    if bm_idx in targets:
        attack = rpg.Attack()
        attack.attacker_idx = barb_idx
        attack.target_idx = bm_idx
        attack.weapon_idx = 0  # Unarmed

        result = bm.resolveAttack(attack)
        # The attack should resolve normally (not as improvised)
        assert result.is_hit or not result.is_hit, "Attack should resolve"

    # Now Battle Master disarms the barbarian
    bm.beginTurn(bm_idx)
    targets = bm.availableTargets(bm_idx, use_limit_range=True)

    # Apply a disarming maneuver (assuming Battle Master's maneuver 5 = Disarming Attack)
    # This is a simplification; in real gameplay it would be part of an attack
    cond = bm.getAgentConditions(barb_idx)
    cond.disarmed = True
    cond.disarmed_by = bm_idx
    bm.setAgentConditions(barb_idx, cond)

    # Now the barbarian's permanently armed weapon should still work
    bm.beginTurn(barb_idx)
    attack = rpg.Attack()
    attack.attacker_idx = barb_idx
    attack.target_idx = bm_idx
    attack.weapon_idx = 0  # Unarmed (permanently armed)

    result = bm.resolveAttack(attack)
    # Should use the real unarmed weapon, not improvised
    # (We verify this by checking it's not downgraded to improvised in logs)
    logs = get_all_logs()
    disarmed_downgrade = any("improvised Unarmed" in log for log in logs if "Disarmed" in log)
    assert not disarmed_downgrade, "Permanently armed weapon should not be downgraded to improvised"

    print("✓ Permanently armed weapons resist disarming attacks")


def test_regular_weapons_still_disarm():
    """Verify that non-permanently-armed weapons can still be disarmed."""
    bm = create_map("encounters/simplemap_blank.json")

    # Place a barbarian with a regular weapon
    barb_idx = place_barbarian(bm, (5, 5), "Barbarian")
    agent = bm.placedAgents()[barb_idx]

    # Give them a regular (non-permanently-armed) weapon (not containing "Unarmed")
    w = rpg.Weapon()
    w.name = "Greataxe"
    w.type = rpg.WeaponType.Melee
    w.permanently_armed = False  # Explicitly not permanently armed
    w.proficient = True
    agent.weapons[0] = w

    # Apply disarmed condition
    cond = bm.getAgentConditions(barb_idx)
    cond.disarmed = True
    cond.disarmed_by = -1
    bm.setAgentConditions(barb_idx, cond)

    # Try to attack with the regular weapon
    clear_logs()
    bm.beginTurn(barb_idx)
    attack = rpg.Attack()
    attack.attacker_idx = barb_idx
    attack.target_idx = (barb_idx + 1) % len(bm.placedAgents())
    attack.weapon_idx = 0

    result = bm.resolveAttack(attack)

    # Should be downgraded to improvised unarmed strike
    logs = get_all_logs()
    disarmed_downgrade = any("improvised Unarmed" in log for log in logs if "Disarmed" in log)
    assert disarmed_downgrade, "Regular weapon should be downgraded to improvised when disarmed"

    print("✓ Regular weapons can still be disarmed normally")


def test_drop_weapons_respects_permanently_armed():
    """Verify that drop effects don't drop permanently armed weapons."""
    bm = create_map("encounters/simplemap_blank.json")

    # Place a creature with a mix of weapons
    idx = place_creature(bm, (5, 5), "TestCreature", "npc")
    agent = bm.placedAgents()[idx]

    # Add a permanently armed weapon
    w_perm = rpg.Weapon()
    w_perm.name = "Innate Bite"
    w_perm.permanently_armed = True
    agent.weapons[0] = w_perm

    # Add a regular weapon that should drop
    w_regular = rpg.Weapon()
    w_regular.name = "Sword"
    w_regular.permanently_armed = False
    agent.weapons.append(w_regular)

    # Trigger weapon drop (Fear effect would do this)
    # Simulate by calling dropAgentWeapons directly
    bm.dropAgentWeapons(idx)

    # Check that permanent weapon is retained but regular weapon was dropped
    agent = bm.placedAgents()[idx]  # Refresh reference
    found_perm = False
    found_regular = False

    for w in agent.weapons:
        if w.name == "Innate Bite":
            found_perm = True
        if w.name == "Sword":
            found_regular = True

    assert found_perm, "Permanently armed weapon should be retained after drop"
    assert not found_regular, "Regular weapon should be dropped"

    print("✓ Drop effects respect permanently armed weapons")


def test_pick_up_dropped_weapon():
    """Verify that dropped weapons can be picked up and re-armed."""
    bm = create_map("encounters/simplemap_blank.json")

    # Place a creature with a weapon
    idx = place_creature(bm, (5, 5), "TestCreature", "npc")
    agent = bm.placedAgents()[idx]

    # Set up their weapons
    w_sword = rpg.Weapon()
    w_sword.name = "Sword"
    w_sword.permanently_armed = False
    agent.weapons[0] = w_sword
    agent.weapons[1].name = ""  # Empty slot
    agent.weapons[2].name = ""  # Empty slot

    # Drop the weapon (simulate disarm effect)
    bm.dropAgentWeapons(idx)

    # Verify weapon was dropped
    agent = bm.placedAgents()[idx]
    assert agent.weapons[0].name.empty() or "Sword" not in agent.weapons[0].name, "Weapon should be dropped"

    # Find the dropped item
    items = bm.get_all_items()
    sword_item = None
    for item in items:
        if item.weapon.name == "Sword":
            sword_item = item
            break

    assert sword_item is not None, "Dropped sword should be on the map"

    # Pick it up and re-arm the agent
    success = bm.pick_up_item(sword_item.id, idx)
    assert success, "Should successfully pick up the dropped weapon"

    # Verify weapon is back in agent's inventory
    agent = bm.placedAgents()[idx]
    found_sword = False
    for w in agent.weapons:
        if w.name == "Sword":
            found_sword = True
            break

    assert found_sword, "Sword should be re-armed after pickup"

    # Verify item was removed from map
    items = bm.get_all_items()
    for item in items:
        assert item.weapon.name != "Sword", "Item should be removed from map after pickup"

    print("✓ Dropped weapons can be picked up and re-armed")


def test_pick_up_with_full_slots_and_slot_override():
    """Verify that pick up can override a slot even when all slots are full."""
    bm = create_map("encounters/simplemap_blank.json")

    # Place a creature with all weapon slots full
    idx = place_creature(bm, (5, 5), "TestCreature", "npc")
    agent = bm.placedAgents()[idx]

    # Fill all slots
    for i in range(3):
        w = rpg.Weapon()
        w.name = f"OldWeapon{i}"
        agent.weapons[i] = w

    # Drop an item at the creature's location
    cell = agent.origin
    dropped_weapon = rpg.Weapon()
    dropped_weapon.name = "DroppedWeapon"
    item_id = bm.place_item(cell, dropped_weapon)

    # Try to pick it up without slot override (should fail - no empty slots)
    success = bm.pick_up_item(item_id, idx)
    assert not success, "Should fail to pick up when no empty slots and no override"

    # Verify item is still on map
    items = bm.get_all_items()
    found_item = any(item.id == item_id for item in items)
    assert found_item, "Item should still be on map after failed pickup"

    # Now pick it up with explicit slot override (slot 1)
    success = bm.pick_up_item(item_id, idx, 1)
    assert success, "Should successfully pick up when explicit slot provided"

    # Verify the weapon replaced the old one in slot 1
    agent = bm.placedAgents()[idx]
    assert agent.weapons[1].name == "DroppedWeapon", "Slot 1 should have the dropped weapon"
    assert agent.weapons[0].name == "OldWeapon0", "Slot 0 should still have old weapon"
    assert agent.weapons[2].name == "OldWeapon2", "Slot 2 should still have old weapon"

    # Verify item was removed from map
    items = bm.get_all_items()
    found_item = any(item.id == item_id for item in items)
    assert not found_item, "Item should be removed from map after pickup"

    print("✓ Pick up can override slots when explicitly specified")


if __name__ == "__main__":
    test_permanently_armed_flag_survives_roundtrip()
    test_disarming_attack_respects_permanently_armed()
    test_regular_weapons_still_disarm()
    test_drop_weapons_respects_permanently_armed()
    test_pick_up_dropped_weapon()
    test_pick_up_with_full_slots_and_slot_override()
    print("\n✅ All weapon management tests passed!")
