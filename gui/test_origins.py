#!/usr/bin/env python3
"""
Test Origins system: 16 backgrounds, 18 skills, alignments, subclasses
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_skill_enum_values():
    """Verify all 18 skill enum values exist"""
    assert rpg.Skill.Acrobatics
    assert rpg.Skill.AnimalHandling
    assert rpg.Skill.Arcana
    assert rpg.Skill.Athletics
    assert rpg.Skill.Deception
    assert rpg.Skill.History
    assert rpg.Skill.Insight
    assert rpg.Skill.Intimidation
    assert rpg.Skill.Investigation
    assert rpg.Skill.Medicine
    assert rpg.Skill.Nature
    assert rpg.Skill.Perception
    assert rpg.Skill.Performance
    assert rpg.Skill.Persuasion
    assert rpg.Skill.Religion
    assert rpg.Skill.SleigtOfHand
    assert rpg.Skill.Stealth
    assert rpg.Skill.Survival
    print("✅ test_skill_enum_values passed")

def test_background_enum_values():
    """Verify all 16 background enum values exist (2024 PHB)"""
    assert rpg.Background.Acolyte
    assert rpg.Background.Artisan
    assert rpg.Background.Charlatan
    assert rpg.Background.Criminal
    assert rpg.Background.Entertainer
    assert rpg.Background.Farmer
    assert rpg.Background.Guard
    assert rpg.Background.Guide
    assert rpg.Background.Hermit
    assert rpg.Background.Merchant
    assert rpg.Background.Noble
    assert rpg.Background.Sage
    assert rpg.Background.Sailor
    assert rpg.Background.Scribe
    assert rpg.Background.Soldier
    assert rpg.Background.Wayfarer
    print("✅ test_background_enum_values passed")

def test_alignment_enum_values():
    """Verify all alignment enum values exist"""
    assert rpg.Alignment.LawfulGood
    assert rpg.Alignment.LawfulNeutral
    assert rpg.Alignment.LawfulEvil
    assert rpg.Alignment.NeutralGood
    assert rpg.Alignment.TrueNeutral
    assert rpg.Alignment.NeutralEvil
    assert rpg.Alignment.ChaoticGood
    assert rpg.Alignment.ChaoticNeutral
    assert rpg.Alignment.ChaoticEvil
    print("✅ test_alignment_enum_values passed")

def test_barbarian_subclass_enum_values():
    """Verify all Barbarian subclass enum values exist (2024 D&D)"""
    assert rpg.BarbianSubclass.Berserker
    assert rpg.BarbianSubclass.WildHeart
    assert rpg.BarbianSubclass.WorldTree
    assert rpg.BarbianSubclass.Zealot
    print("✅ test_barbarian_subclass_enum_values passed")

def test_stats_background_field():
    """Test reading/writing background field"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.background == rpg.Background.NONE, "Default background should be NONE"

    stats.background = rpg.Background.Criminal
    assert stats.background == rpg.Background.Criminal
    engine.set_agent_stats(bm, idx, stats)

    stats2 = engine.get_agent_stats(bm, idx)
    assert stats2.background == rpg.Background.Criminal
    print("✅ test_stats_background_field passed")

def test_stats_alignment_field():
    """Test reading/writing alignment field"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.alignment == rpg.Alignment.TrueNeutral, "Default alignment should be TrueNeutral"

    stats.alignment = rpg.Alignment.LawfulGood
    assert stats.alignment == rpg.Alignment.LawfulGood
    engine.set_agent_stats(bm, idx, stats)

    stats2 = engine.get_agent_stats(bm, idx)
    assert stats2.alignment == rpg.Alignment.LawfulGood
    print("✅ test_stats_alignment_field passed")

def test_stats_barbarian_subclass_field():
    """Test reading/writing Barbarian subclass field"""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    config = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.barbarian_subclass == rpg.BarbianSubclass.NONE

    stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    assert stats.barbarian_subclass == rpg.BarbianSubclass.WildHeart
    engine.set_agent_stats(bm, idx, stats)

    stats2 = engine.get_agent_stats(bm, idx)
    assert stats2.barbarian_subclass == rpg.BarbianSubclass.WildHeart
    print("✅ test_stats_barbarian_subclass_field passed")

def test_acolyte_origin_data():
    """Verify Acolyte origin has correct data"""
    origin = rpg.Origin()
    origin.background = rpg.Background.Acolyte
    origin.ability_increases = [3, 4, 5]  # INT, WIS, CHA
    origin.origin_feat = "Magic Initiate (Cleric)"
    origin.skill_proficiencies = [rpg.Skill.Insight, rpg.Skill.Religion]

    assert origin.background == rpg.Background.Acolyte
    assert len(origin.ability_increases) == 3
    assert origin.ability_increases[0] == 3  # INT
    assert origin.ability_increases[1] == 4  # WIS
    assert origin.ability_increases[2] == 5  # CHA
    assert origin.origin_feat == "Magic Initiate (Cleric)"
    assert len(origin.skill_proficiencies) == 2
    assert origin.skill_proficiencies[0] == rpg.Skill.Insight
    assert origin.skill_proficiencies[1] == rpg.Skill.Religion
    print("✅ test_acolyte_origin_data passed")

def test_soldier_origin_data():
    """Verify Soldier origin has correct data"""
    origin = rpg.Origin()
    origin.background = rpg.Background.Soldier
    origin.ability_increases = [0, 1, 2]  # STR, DEX, CON
    origin.origin_feat = "Savage Attacker"
    origin.skill_proficiencies = [rpg.Skill.Athletics, rpg.Skill.Intimidation]

    assert origin.background == rpg.Background.Soldier
    assert origin.ability_increases[0] == 0  # STR
    assert origin.ability_increases[1] == 1  # DEX
    assert origin.ability_increases[2] == 2  # CON
    assert origin.origin_feat == "Savage Attacker"
    assert len(origin.skill_proficiencies) == 2
    assert origin.skill_proficiencies[0] == rpg.Skill.Athletics
    assert origin.skill_proficiencies[1] == rpg.Skill.Intimidation
    print("✅ test_soldier_origin_data passed")

def main():
    print("Running Origins system tests...")
    print()

    test_skill_enum_values()
    test_background_enum_values()
    test_alignment_enum_values()
    test_barbarian_subclass_enum_values()
    test_stats_background_field()
    test_stats_alignment_field()
    test_stats_barbarian_subclass_field()
    test_acolyte_origin_data()
    test_soldier_origin_data()

    print()
    print("=" * 60)
    print("✅ All Origins tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
