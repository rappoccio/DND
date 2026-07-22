#!/usr/bin/env python3
"""
Test Druid: Wild Shape resources and mechanics, spell casting (WIS caster), and subclasses
(Circle of the Moon, Land, Sea, Stars).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_wild_shape_resources_by_level():
    """Druid Wild Shape: 0 uses L1, 2 uses L2-5, 3 uses L6-16, 4 uses L17+"""
    cases = [(1, 0), (2, 2), (5, 2), (6, 3), (16, 3), (17, 4), (20, 4)]
    for level, expected_uses in cases:
        s = rpg.Stats()
        s.initialize_class_resources(rpg.CharacterClass.Druid, level)
        ws = s.resources.get("Wild Shape")
        assert ws is not None, f"L{level}: Wild Shape resource should exist"
        assert ws.current == expected_uses, \
            f"L{level}: expected {expected_uses} uses, got {ws.current}"
    print("✅ test_wild_shape_resources_by_level passed")


def test_druid_is_wis_full_caster():
    """Druid is a WIS-based full caster."""
    s = rpg.Stats()
    s.initialize_class_resources(rpg.CharacterClass.Druid, 5)
    assert s.can_cast_spell, "Druid should be able to cast"
    assert s.spellcasting_ability == 4, "Druid spellcasting ability should be WIS (4)"
    print("✅ test_druid_is_wis_full_caster passed")


def test_druid_spell_slot_progression():
    """Druid spell slots follow the standard full-caster table (2 first-level slots at level 1 —
    Druids/Clerics/Bards are full casters, identical to Wizards/Sorcerers)."""
    cases = [
        (1, [2, 0, 0, 0, 0, 0, 0, 0, 0]),
        (2, [3, 0, 0, 0, 0, 0, 0, 0, 0]),
        (3, [4, 2, 0, 0, 0, 0, 0, 0, 0]),
        (5, [4, 3, 2, 0, 0, 0, 0, 0, 0]),
        (9, [4, 3, 3, 3, 1, 0, 0, 0, 0]),
    ]
    for level, expected_slots in cases:
        s = rpg.Stats()
        s.set_class_level(rpg.CharacterClass.Druid, level)
        actual = list(s.spell_slots_max)
        assert actual == expected_slots, \
            f"L{level} slots: expected {expected_slots}, got {actual}"
    print("✅ test_druid_spell_slot_progression passed")


def test_circle_of_moon():
    """Circle of the Moon initializes and stores subclass choice."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 3)
    s.druid_circle = rpg.DruidCircle.CircleOfMoon
    s.initialize_class_resources(rpg.CharacterClass.Druid, 3)
    assert s.druid_circle == rpg.DruidCircle.CircleOfMoon
    print("✅ test_circle_of_moon passed")


def test_circle_of_land():
    """Circle of the Land initializes and stores subclass choice."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 3)
    s.druid_circle = rpg.DruidCircle.CircleOfLand
    s.initialize_class_resources(rpg.CharacterClass.Druid, 3)
    assert s.druid_circle == rpg.DruidCircle.CircleOfLand
    print("✅ test_circle_of_land passed")


def test_circle_of_sea():
    """Circle of the Sea initializes and stores subclass choice."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 3)
    s.druid_circle = rpg.DruidCircle.CircleOfSea
    s.initialize_class_resources(rpg.CharacterClass.Druid, 3)
    assert s.druid_circle == rpg.DruidCircle.CircleOfSea
    print("✅ test_circle_of_sea passed")


def test_circle_of_stars():
    """Circle of the Stars initializes and stores subclass choice."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 3)
    s.druid_circle = rpg.DruidCircle.CircleOfStars
    s.initialize_class_resources(rpg.CharacterClass.Druid, 3)
    assert s.druid_circle == rpg.DruidCircle.CircleOfStars
    print("✅ test_circle_of_stars passed")


def test_wild_shape_state_inactive_by_default():
    """Wild Shape state starts inactive."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 5)
    s.initialize_class_resources(rpg.CharacterClass.Druid, 5)
    assert not s.wild_shape_active, "wild_shape_active should be False"
    assert s.wild_shape_form_name == "", "wild_shape_form_name should be empty"
    assert s.wild_shape_saved_ac == 0
    assert s.wild_shape_saved_str == 0
    assert s.wild_shape_saved_dex == 0
    assert s.wild_shape_saved_con == 0
    print("✅ test_wild_shape_state_inactive_by_default passed")


def test_starry_form_state_inactive_by_default():
    """Starry Form state starts inactive (Circle of the Stars only)."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Druid, 3)
    s.druid_circle = rpg.DruidCircle.CircleOfStars
    s.initialize_class_resources(rpg.CharacterClass.Druid, 3)
    assert not s.starry_form_active, "starry_form_active should be False"
    assert s.starry_constellation == 0, "starry_constellation should be 0 (none)"
    print("✅ test_starry_form_state_inactive_by_default passed")


# ─────────────────────────────────────────────────────────────────────────────
# Wild Shape activation/deactivation mechanics tests

def _druid(engine, bm, idx, level, circle=None):
    """Configure agent as a Druid of the given level and optional subclass."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Druid, level)
    s.wis = 16
    s.dex = 14
    s.con = 14
    if circle is not None:
        s.druid_circle = circle
    s.initialize_class_resources(rpg.CharacterClass.Druid, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _original_weapons():
    """Return the druid's original weapons (staff)."""
    w1 = rpg.Weapon()
    w1.name = "Staff"
    w1.type = rpg.WeaponType.Melee
    w1.proficient = True
    w1.reach_ft = 5
    return [w1, rpg.Weapon(), rpg.Weapon()]


def _beast_weapons():
    """Return beast form weapons (claw, bite, etc.)."""
    w1 = rpg.Weapon()
    w1.name = "Claw"
    w1.type = rpg.WeaponType.Melee
    w1.proficient = True
    w1.reach_ft = 5

    w2 = rpg.Weapon()
    w2.name = "Bite"
    w2.type = rpg.WeaponType.Melee
    w2.proficient = True
    w2.reach_ft = 5

    return [w1, w2, rpg.Weapon()]


def _get_beast_forms_path():
    """Get the path to beast_forms.json."""
    import os
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
    return os.path.join(script_dir, "beast_forms.json")


def _setup_druid(level, circle=rpg.DruidCircle.CircleOfMoon):
    """Set up a druid and place them on the battle map."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    druid_idx = add_agent_to_battle(engine, bm, create_test_agent("Druid", 5, 5))
    _druid(engine, bm, druid_idx, level, circle=circle)
    engine.set_agent_weapons(bm, druid_idx, _original_weapons())
    return bm, engine, druid_idx


def test_wild_shape_activation_spends_resource():
    """Activating Wild Shape spends one use from the resource."""
    bm, engine, druid_idx = _setup_druid(5)
    s = engine.get_agent_stats(bm, druid_idx)
    ws_before = s.get_resource("Wild Shape")
    assert ws_before.current == 2, f"L5 should start with 2 uses, got {ws_before.current}"

    result = engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    assert result, "Activation should succeed"

    s = engine.get_agent_stats(bm, druid_idx)
    ws_after = s.get_resource("Wild Shape")
    assert ws_after.current == 1, \
        f"After activation should have 1 use remaining, got {ws_after.current}"
    print("✅ test_wild_shape_activation_spends_resource passed")


def test_wild_shape_activation_sets_form_name():
    """Activating Wild Shape sets the beast form name."""
    bm, engine, druid_idx = _setup_druid(5)

    result = engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    assert result, "Activation should succeed"

    s = engine.get_agent_stats(bm, druid_idx)
    assert s.wild_shape_form_name == "Brown Bear", \
        f"Form name should be 'Brown Bear', got '{s.wild_shape_form_name}'"
    assert s.wild_shape_active, "wild_shape_active should be True"
    print("✅ test_wild_shape_activation_sets_form_name passed")


def test_wild_shape_activation_saves_original_stats():
    """Activating Wild Shape saves original AC, STR, DEX, CON."""
    bm, engine, druid_idx = _setup_druid(5)
    s_before = engine.get_agent_stats(bm, druid_idx)
    original_ac = s_before.base_ac
    original_str = s_before.str
    original_dex = s_before.dex
    original_con = s_before.con

    engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())

    s_after = engine.get_agent_stats(bm, druid_idx)
    assert s_after.wild_shape_saved_ac == original_ac, \
        f"Saved AC should be {original_ac}, got {s_after.wild_shape_saved_ac}"
    assert s_after.wild_shape_saved_str == original_str, \
        f"Saved STR should be {original_str}, got {s_after.wild_shape_saved_str}"
    assert s_after.wild_shape_saved_dex == original_dex, \
        f"Saved DEX should be {original_dex}, got {s_after.wild_shape_saved_dex}"
    assert s_after.wild_shape_saved_con == original_con, \
        f"Saved CON should be {original_con}, got {s_after.wild_shape_saved_con}"
    print("✅ test_wild_shape_activation_saves_original_stats passed")


def test_wild_shape_activation_replaces_weapons():
    """Activating Wild Shape replaces weapons with beast form weapons."""
    bm, engine, druid_idx = _setup_druid(5)
    beast_weapons = _beast_weapons()

    engine.activate_wild_shape(bm, druid_idx, "Brown Bear", beast_weapons, _get_beast_forms_path())

    current_weapons = engine.get_agent_weapons(bm, druid_idx)
    assert current_weapons[0].name == "Claw", "Weapons should be replaced with beast form weapons"
    print("✅ test_wild_shape_activation_replaces_weapons passed")


def test_wild_shape_failed_activation_no_resource():
    """Activation fails if no Wild Shape uses remain."""
    bm, engine, druid_idx = _setup_druid(1)  # L1 has 0 uses
    s = engine.get_agent_stats(bm, druid_idx)
    ws = s.get_resource("Wild Shape")
    assert ws.current == 0, "L1 should have 0 uses"

    result = engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    assert not result, "Activation should fail with no uses remaining"

    s = engine.get_agent_stats(bm, druid_idx)
    assert not s.wild_shape_active, "Should remain inactive on failed activation"
    print("✅ test_wild_shape_failed_activation_no_resource passed")


def test_wild_shape_deactivation_restores_stats():
    """Deactivating Wild Shape restores original AC, STR, DEX, CON."""
    bm, engine, druid_idx = _setup_druid(5)
    s_before = engine.get_agent_stats(bm, druid_idx)
    original_ac = s_before.base_ac
    original_str = s_before.str
    original_dex = s_before.dex
    original_con = s_before.con

    engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    result = engine.deactivate_wild_shape(bm, druid_idx)
    assert result, "Deactivation should succeed"

    s_after = engine.get_agent_stats(bm, druid_idx)
    assert s_after.base_ac == original_ac, \
        f"AC should be restored to {original_ac}, got {s_after.base_ac}"
    assert s_after.str == original_str, \
        f"STR should be restored to {original_str}, got {s_after.str}"
    assert s_after.dex == original_dex, \
        f"DEX should be restored to {original_dex}, got {s_after.dex}"
    assert s_after.con == original_con, \
        f"CON should be restored to {original_con}, got {s_after.con}"
    print("✅ test_wild_shape_deactivation_restores_stats passed")


def test_wild_shape_deactivation_restores_weapons():
    """Deactivating Wild Shape restores the original weapons."""
    bm, engine, druid_idx = _setup_druid(5)
    original_weapons = engine.get_agent_weapons(bm, druid_idx)

    engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    engine.deactivate_wild_shape(bm, druid_idx)

    restored_weapons = engine.get_agent_weapons(bm, druid_idx)
    assert restored_weapons[0].name == original_weapons[0].name, \
        f"Weapons should be restored: expected {original_weapons[0].name}"
    print("✅ test_wild_shape_deactivation_restores_weapons passed")


def test_wild_shape_deactivation_clears_active_flag():
    """Deactivating Wild Shape clears the active flag."""
    bm, engine, druid_idx = _setup_druid(5)

    engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    s = engine.get_agent_stats(bm, druid_idx)
    assert s.wild_shape_active, "Should be active after activation"

    engine.deactivate_wild_shape(bm, druid_idx)
    s = engine.get_agent_stats(bm, druid_idx)
    assert not s.wild_shape_active, "Should be inactive after deactivation"
    assert s.wild_shape_form_name == "", "Form name should be cleared"
    print("✅ test_wild_shape_deactivation_clears_active_flag passed")


def test_wild_shape_deactivation_invalid_index():
    """Deactivation fails gracefully with invalid agent index."""
    bm, engine, druid_idx = _setup_druid(5)

    result = engine.deactivate_wild_shape(bm, -1)
    assert not result, "Deactivation should fail with invalid index"

    result = engine.deactivate_wild_shape(bm, 999)
    assert not result, "Deactivation should fail with out-of-range index"
    print("✅ test_wild_shape_deactivation_invalid_index passed")


def test_wild_shape_multiple_activations():
    """Can activate/deactivate Wild Shape multiple times (as long as uses remain)."""
    bm, engine, druid_idx = _setup_druid(5)  # 2 uses

    # First activation
    result1 = engine.activate_wild_shape(bm, druid_idx, "Brown Bear", _beast_weapons(), _get_beast_forms_path())
    assert result1, "First activation should succeed"

    # Deactivate
    result2 = engine.deactivate_wild_shape(bm, druid_idx)
    assert result2, "Deactivation should succeed"

    # Second activation
    result3 = engine.activate_wild_shape(bm, druid_idx, "Wolf", _beast_weapons(), _get_beast_forms_path())
    assert result3, "Second activation should succeed"

    # No more uses (spent both)
    result4 = engine.activate_wild_shape(bm, druid_idx, "Wolf", _beast_weapons(), _get_beast_forms_path())
    assert not result4, "Third activation should fail (no uses left)"

    print("✅ test_wild_shape_multiple_activations passed")


if __name__ == "__main__":
    test_wild_shape_resources_by_level()
    test_druid_is_wis_full_caster()
    test_druid_spell_slot_progression()
    test_circle_of_moon()
    test_circle_of_land()
    test_circle_of_sea()
    test_circle_of_stars()
    test_wild_shape_state_inactive_by_default()
    test_starry_form_state_inactive_by_default()
    test_wild_shape_activation_spends_resource()
    test_wild_shape_activation_sets_form_name()
    test_wild_shape_activation_saves_original_stats()
    test_wild_shape_activation_replaces_weapons()
    test_wild_shape_failed_activation_no_resource()
    test_wild_shape_deactivation_restores_stats()
    test_wild_shape_deactivation_restores_weapons()
    test_wild_shape_deactivation_clears_active_flag()
    test_wild_shape_deactivation_invalid_index()
    test_wild_shape_multiple_activations()
    print("\n✅ All Druid tests passed!")
