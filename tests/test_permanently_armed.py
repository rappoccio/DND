#!/usr/bin/env python3
"""Test suite for the ``permanently_armed`` weapon property.

A ``permanently_armed`` weapon models a creature's *innate* natural weapon (a
dragon's bite, a monster's claws) that is part of its body — it can never be
dropped by a Fear/drop effect and can never be knocked away by a Battle Master
Disarming Attack (which would otherwise downgrade a held weapon to an improvised
Unarmed Strike). Regular equipped weapons stay fully droppable/disarmable.

The engine keys BOTH the drop path (CombatEngine::dropAgentWeapons, reached via
apply_frightened) and the disarm downgrade (in determineAdvantage, reached via
execute_action) off ``Weapon.permanently_armed``. These tests drive those real
paths and read the combat log through an attached MessageLogger.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


def _weapon(name, dmg=4, permanently_armed=False):
    """A melee weapon that always hits (huge bonus_hit) with a fixed, crit-proof damage bonus."""
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.damage_dice = 1
    w.damage_dice_count = 0
    w.damage_modifier = 0
    w.bonus_damage = dmg
    w.bonus_hit = 50
    w.proficient = True
    w.permanently_armed = permanently_armed
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.normal_range_ft = 5
    return w


def _logged_engine(engine):
    """Attach a MessageLogger; return it so callers flush() to read+clear buffered messages."""
    logger = rpg.MessageLogger()
    engine.set_logger(logger)
    return logger


def _two_combatants(hp_target=1000):
    """An attacker at (5,5) and an enemy target one cell east at (6,5), on opposing factions."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5), str=16)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5), hp=hp_target)
    bm.set_agent_faction(atk, 1); bm.set_agent_faction(foe, 2)
    return bm, engine, atk, foe


def _set_disarmed(engine, bm, idx):
    cond = engine.get_agent_conditions(bm, idx)
    cond.disarmed = True
    cond.disarmed_by = -1
    engine.set_agent_conditions(bm, idx, cond)


def _weapon_names(engine, bm, idx):
    return [w.name for w in engine.get_agent_weapons(bm, idx)]


# ── 1. The flag survives basic assignment and a weapons round-trip ─────────────────────────────────
def test_permanently_armed_flag_survives_roundtrip():
    w = rpg.Weapon()
    w.name = "TestWeapon"
    w.permanently_armed = True
    assert w.permanently_armed, "permanently_armed flag should be True after assignment"

    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    got = engine.get_agent_weapons(bm, atk)[0]
    assert got.name == "TestWeapon" and got.permanently_armed, \
        "permanently_armed flag should survive a set/get_agent_weapons round-trip"
    print("✅ test_permanently_armed_flag_survives_roundtrip passed")


# ── 2. Disarming does NOT downgrade a permanently armed weapon ─────────────────────────────────────
def test_disarming_attack_respects_permanently_armed():
    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk,
                             [_weapon("Innate Claw", permanently_armed=True), rpg.Weapon(), rpg.Weapon()])
    _set_disarmed(engine, bm, atk)                 # attacker has been Disarmed

    logger = _logged_engine(engine)
    engine.begin_turn(bm, atk)
    engine.execute_action(bm, rpg.Attack(atk, foe, 0))
    log = "\n".join(logger.flush())

    assert "improvised Unarmed Strike" not in log, \
        "a permanently armed weapon must NOT be downgraded to improvised when Disarmed"
    print("✅ test_disarming_attack_respects_permanently_armed passed")


# ── 3. A regular weapon IS downgraded to improvised when disarmed ──────────────────────────────────
def test_regular_weapons_still_disarm():
    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk,
                             [_weapon("Greataxe", permanently_armed=False), rpg.Weapon(), rpg.Weapon()])
    _set_disarmed(engine, bm, atk)

    logger = _logged_engine(engine)
    engine.begin_turn(bm, atk)
    engine.execute_action(bm, rpg.Attack(atk, foe, 0))
    log = "\n".join(logger.flush())

    assert "improvised Unarmed Strike" in log, \
        "a regular equipped weapon should be downgraded to an improvised Unarmed Strike when Disarmed"
    print("✅ test_regular_weapons_still_disarm passed")


# ── 4. Fear/drop effects retain permanently armed weapons, drop the rest ───────────────────────────
def test_drop_effects_respect_permanently_armed():
    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk,
                             [_weapon("Innate Bite", permanently_armed=True),
                              _weapon("Sword", permanently_armed=False), rpg.Weapon()])

    engine.apply_frightened(bm, atk)               # Fear → dropAgentWeapons (skips permanently armed)

    names = _weapon_names(engine, bm, atk)
    assert "Innate Bite" in names, "permanently armed weapon should be retained after a drop effect"
    assert "Sword" not in names, "a regular weapon should be dropped by a Fear effect"
    print("✅ test_drop_effects_respect_permanently_armed passed")


# ── 5. A dropped weapon lands on the map and can be picked back up ──────────────────────────────────
def test_pick_up_dropped_weapon():
    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk, [_weapon("Sword", permanently_armed=False),
                                       rpg.Weapon(), rpg.Weapon()])

    engine.apply_frightened(bm, atk)               # drops the Sword to the ground as a MapItem
    assert "Sword" not in _weapon_names(engine, bm, atk), "Sword should have been dropped"

    sword_item = next((it for it in bm.get_all_items() if it.weapon.name == "Sword"), None)
    assert sword_item is not None, "the dropped Sword should be a MapItem on the ground"

    assert bm.pick_up_item(sword_item.id, atk), "should successfully pick the Sword back up"
    assert "Sword" in _weapon_names(engine, bm, atk), "Sword should be re-armed after pickup"
    assert all(it.weapon.name != "Sword" for it in bm.get_all_items()), \
        "the item should be removed from the map after pickup"
    print("✅ test_pick_up_dropped_weapon passed")


# ── 6. Pickup with full slots appends a new slot; an explicit slot override replaces in place ───────
def test_pick_up_with_full_slots_and_slot_override():
    bm, engine, atk, foe = _two_combatants()
    engine.set_agent_weapons(bm, atk,
                             [_weapon("OldWeapon0"), _weapon("OldWeapon1"), _weapon("OldWeapon2")])
    cell = bm.placed_agents[atk].origin

    # No free slot + no override → the picked-up weapon APPENDS a new (4th) attack slot; originals kept.
    appended_id = bm.place_item(cell, _weapon("AppendedWeapon"), "")
    assert bm.pick_up_item(appended_id, atk), "pickup should still succeed (appends when slots are full)"
    names = _weapon_names(engine, bm, atk)
    assert names == ["OldWeapon0", "OldWeapon1", "OldWeapon2", "AppendedWeapon"], \
        f"a full-slot pickup should append a 4th slot, got {names}"
    assert all(it.id != appended_id for it in bm.get_all_items()), "appended item removed from the map"

    # Explicit slot override replaces that slot in place, leaving the others untouched.
    override_id = bm.place_item(cell, _weapon("OverrideWeapon"), "")
    assert bm.pick_up_item(override_id, atk, 1), "pickup should succeed with an explicit slot override"
    names = _weapon_names(engine, bm, atk)
    assert names[1] == "OverrideWeapon", "slot 1 should now hold the overridden weapon"
    assert names[0] == "OldWeapon0" and names[2] == "OldWeapon2", "other slots stay untouched"
    assert all(it.id != override_id for it in bm.get_all_items()), "override item removed from the map"
    print("✅ test_pick_up_with_full_slots_and_slot_override passed")


if __name__ == "__main__":
    test_permanently_armed_flag_survives_roundtrip()
    test_disarming_attack_respects_permanently_armed()
    test_regular_weapons_still_disarm()
    test_drop_effects_respect_permanently_armed()
    test_pick_up_dropped_weapon()
    test_pick_up_with_full_slots_and_slot_override()
    print("\n✅ All permanently_armed tests passed!")
