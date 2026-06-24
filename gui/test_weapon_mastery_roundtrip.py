#!/usr/bin/env python3
"""
Test that weapon masteries round-trip through JSON serialization (encounter save/load).
Reproduces the issue where Seneval's Cleave mastery is lost.
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _parse_mastery, _dict_to_weapon, _weapon_to_dict


def test_parse_mastery():
    """Test that _parse_mastery correctly converts string "Cleave" to the enum."""
    mastery = _parse_mastery("Cleave")
    assert mastery == rpg.WeaponMastery.Cleave, f"Expected Cleave, got {mastery.name}"
    print("✅ test_parse_mastery: 'Cleave' string parsed correctly")


def test_mastery_round_trip():
    """Test that mastery survives dict → weapon → dict round-trip."""
    # Start with what's in the JSON
    weapon_dict = {
        "name": "Greataxe",
        "type": "melee",
        "reach_ft": 5,
        "normal_range_ft": 0,
        "long_range_ft": 0,
        "finesse": False,
        "thrown": False,
        "pact_weapon": False,
        "psychic_blade": False,
        "proficient": True,
        "off_hand": False,
        "two_handed": False,
        "heavy": True,
        "light": False,
        "is_shield": False,
        "auto_hit_if_grappled": False,
        "mastery": "Cleave",  # This is what's in Seneval's JSON
        "bonus_hit": 0,
        "bonus_damage": 0,
        "ac_bonus": 0,
        "physical_damage_types": [{"type": "Slashing", "num_dice": 1, "die_size": 12}],
        "magic_damage_types": [],
        "conditions": []
    }

    print(f"  Input dict mastery: {weapon_dict['mastery']}")

    # Convert dict → weapon (what happens when loading from JSON)
    weapon = _dict_to_weapon(weapon_dict)
    print(f"  Weapon.mastery after loading: {weapon.mastery.name}")
    assert weapon.mastery == rpg.WeaponMastery.Cleave, \
        f"Mastery lost during _dict_to_weapon! Got {weapon.mastery.name}"

    # Convert weapon → dict (what happens when saving)
    output_dict = _weapon_to_dict(weapon)
    print(f"  Output dict mastery: {output_dict['mastery']}")
    assert output_dict["mastery"] == "Cleave", \
        f"Mastery lost during _weapon_to_dict! Got {output_dict['mastery']}"

    print("✅ test_mastery_round_trip passed")


def test_mastery_none_round_trip():
    """Test that the 'None' enum value (default, no mastery) also works."""
    weapon_dict = {
        "name": "Unarmed",
        "type": "melee",
        "reach_ft": 5,
        "normal_range_ft": 80,
        "long_range_ft": 320,
        "finesse": False,
        "thrown": False,
        "pact_weapon": False,
        "psychic_blade": False,
        "proficient": False,
        "off_hand": False,
        "two_handed": False,
        "heavy": False,
        "light": False,
        "is_shield": False,
        "auto_hit_if_grappled": False,
        "mastery": "None",
        "bonus_hit": 0,
        "bonus_damage": 0,
        "ac_bonus": 0,
        "physical_damage_types": [],
        "magic_damage_types": [],
        "conditions": []
    }

    weapon = _dict_to_weapon(weapon_dict)
    assert weapon.mastery == rpg.WeaponMastery.None

    output_dict = _weapon_to_dict(weapon)
    assert output_dict["mastery"] == "None"

    print("✅ test_mastery_none_round_trip passed")


def main():
    print("Testing weapon mastery serialization...\n")
    test_parse_mastery()
    test_mastery_round_trip()
    test_mastery_none_round_trip()
    print("\n✅ All weapon mastery round-trip tests passed!")


if __name__ == "__main__":
    main()
