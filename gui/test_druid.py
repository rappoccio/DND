#!/usr/bin/env python3
"""
Test Druid: Wild Shape resources, spell casting (WIS caster), and subclasses
(Circle of the Moon, Land, Sea, Stars).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg


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
    """Druid spell slots follow full caster table A."""
    cases = [
        (1, [0, 0, 0, 0, 0, 0, 0, 0, 0]),
        (2, [2, 0, 0, 0, 0, 0, 0, 0, 0]),
        (3, [3, 0, 0, 0, 0, 0, 0, 0, 0]),
        (5, [4, 3, 0, 0, 0, 0, 0, 0, 0]),
        (9, [4, 3, 3, 1, 0, 0, 0, 0, 0]),
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
    print("\n✅ All Druid tests passed!")
