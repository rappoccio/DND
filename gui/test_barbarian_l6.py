#!/usr/bin/env python3
"""
Test Barbarian L6 mechanics: Mindless Rage, Aspect of the Wilds, Fanatical Focus
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_barbarian_subclass_persistence():
    """Verify barbarian_subclass persists after set/get"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Test", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set barbarian_subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.Berserker
    engine.set_agent_stats(bm, idx, stats)

    # Verify it persists on get
    stats = engine.get_agent_stats(bm, idx)
    assert stats.barbarian_subclass == rpg.BarbianSubclass.Berserker, f"After set_agent_stats, expected Berserker, got {stats.barbarian_subclass}"
    print("✅ test_barbarian_subclass_persistence passed")


def test_charmed_condition_persistence():
    """Verify charmed condition can be set and retrieved"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Test", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set charmed condition
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.charmed == False, "Should start not charmed"
    cond.charmed = True
    engine.set_agent_conditions(bm, idx, cond)

    # Verify it persists
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.charmed == True, "Charmed should persist after set"

    print("✅ test_charmed_condition_persistence passed")


def test_berserker_mindless_rage():
    """Verify Berserker L6 Mindless Rage clears charmed/frightened on Rage activation"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Berserker6", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 6
    config.stats.barbarian_subclass = rpg.BarbianSubclass.Berserker
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources and set charmed/frightened conditions
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.Berserker
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 6)
    engine.set_agent_stats(bm, idx, stats)

    cond = engine.get_agent_conditions(bm, idx)
    cond.charmed = True
    cond.frightened = True
    engine.set_agent_conditions(bm, idx, cond)

    # Activate Rage
    engine.activate_rage(bm, idx)

    # Verify charmed and frightened are cleared
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.charmed == False, "Berserker L6 Mindless Rage should clear charmed"
    assert cond.frightened == False, "Berserker L6 Mindless Rage should clear frightened"
    assert cond.raging == True, "Barbarian should be raging"
    print("✅ test_berserker_mindless_rage passed")


def test_wild_heart_owl_aspect():
    """Verify Wild Heart L6 Owl Aspect grants darkvision 60ft"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WildHeart6", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 6
    config.stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    config.stats.wild_heart_aspect = rpg.WildHeartAspect.Owl
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    stats.wild_heart_aspect = rpg.WildHeartAspect.Owl
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 6)
    engine.set_agent_stats(bm, idx, stats)

    # Activate Rage
    engine.activate_rage(bm, idx)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.darkvision_range == 60, f"Owl Aspect should grant 60ft darkvision, got {stats.darkvision_range}"
    print("✅ test_wild_heart_owl_aspect passed")


def test_wild_heart_salmon_aspect():
    """Verify Wild Heart L6 Salmon Aspect grants swim speed = walk speed"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WildHeart6", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 6
    config.stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    config.stats.wild_heart_aspect = rpg.WildHeartAspect.Salmon
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    stats.wild_heart_aspect = rpg.WildHeartAspect.Salmon
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 6)
    walk_speed = stats.speed_walk  # imported speed (Fast Movement already baked in, not added by engine)
    engine.set_agent_stats(bm, idx, stats)

    # Activate Rage
    engine.activate_rage(bm, idx)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.speed_swim == walk_speed, f"Salmon Aspect should grant swim speed = {walk_speed}, got {stats.speed_swim}"
    print("✅ test_wild_heart_salmon_aspect passed")


def test_wild_heart_aspect_resumes_on_rage_end():
    """Verify Wild Heart L6 Aspect bonuses are removed when Rage ends"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WildHeart6", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 6
    config.stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    config.stats.wild_heart_aspect = rpg.WildHeartAspect.Owl
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    stats.wild_heart_aspect = rpg.WildHeartAspect.Owl
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 6)
    engine.set_agent_stats(bm, idx, stats)

    # Activate Rage
    engine.activate_rage(bm, idx)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.darkvision_range == 60, "Owl Aspect should grant darkvision during Rage"

    # End Rage
    engine.end_rage(bm, idx)
    stats = engine.get_agent_stats(bm, idx)
    cond = engine.get_agent_conditions(bm, idx)
    assert stats.darkvision_range == 0, "Owl Aspect darkvision should be removed when Rage ends"
    assert cond.raging == False, "Should not be raging"
    print("✅ test_wild_heart_aspect_resumes_on_rage_end passed")


def test_zealot_fanatical_focus_flag():
    """Verify Zealot L6 Fanatical Focus flag is available on Rage activation"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Zealot6", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 6
    config.stats.barbarian_subclass = rpg.BarbianSubclass.Zealot
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 6
    stats.barbarian_subclass = rpg.BarbianSubclass.Zealot
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 6)
    engine.set_agent_stats(bm, idx, stats)

    cond = engine.get_agent_conditions(bm, idx)
    cond.fanatical_focus_used = True
    engine.set_agent_conditions(bm, idx, cond)

    # Activate Rage - should reset fanatical_focus_used flag
    engine.activate_rage(bm, idx)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.fanatical_focus_used == False, "Zealot Fanatical Focus should be available on Rage activation"
    assert cond.raging == True, "Should be raging"
    print("✅ test_zealot_fanatical_focus_flag passed")


def test_wildheartaspect_binding():
    """Verify WildHeartAspect enum is properly bound"""
    assert hasattr(rpg, 'WildHeartAspect'), "WildHeartAspect enum should be bound"
    assert hasattr(rpg.WildHeartAspect, 'NONE'), "WildHeartAspect.NONE should exist"
    assert hasattr(rpg.WildHeartAspect, 'Owl'), "WildHeartAspect.Owl should exist"
    assert hasattr(rpg.WildHeartAspect, 'Panther'), "WildHeartAspect.Panther should exist"
    assert hasattr(rpg.WildHeartAspect, 'Salmon'), "WildHeartAspect.Salmon should exist"
    print("✅ test_wildheartaspect_binding passed")


def test_fanatical_focus_used_binding():
    """Verify fanatical_focus_used condition flag is properly bound"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Test", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert hasattr(cond, 'fanatical_focus_used'), "Conditions should have fanatical_focus_used"
    assert cond.fanatical_focus_used == False, "fanatical_focus_used should default to False"

    cond.fanatical_focus_used = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.fanatical_focus_used == True, "fanatical_focus_used should be settable"
    print("✅ test_fanatical_focus_used_binding passed")


def test_wild_heart_aspect_stats_binding():
    """Verify wild_heart_aspect field is properly bound in Stats"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Test", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    assert hasattr(stats, 'wild_heart_aspect'), "Stats should have wild_heart_aspect field"
    assert stats.wild_heart_aspect == rpg.WildHeartAspect.NONE, "wild_heart_aspect should default to NONE"

    stats.wild_heart_aspect = rpg.WildHeartAspect.Owl
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.wild_heart_aspect == rpg.WildHeartAspect.Owl, "wild_heart_aspect should be settable"
    print("✅ test_wild_heart_aspect_stats_binding passed")


if __name__ == "__main__":
    test_barbarian_subclass_persistence()
    test_charmed_condition_persistence()
    test_berserker_mindless_rage()
    test_wild_heart_owl_aspect()
    test_wild_heart_salmon_aspect()
    test_wild_heart_aspect_resumes_on_rage_end()
    test_zealot_fanatical_focus_flag()
    test_wildheartaspect_binding()
    test_fanatical_focus_used_binding()
    test_wild_heart_aspect_stats_binding()
    print("\n✅ All L6 feature tests passed!")
