#!/usr/bin/env python3
"""
Test Warlock Phase 3a: Eldritch Blast invocations
- Eldritch Blast multi-beam (character-level scaling)
- Agonizing Blast (+CHA damage per beam)
- Repelling Blast (10 ft push per beam)
- Eldritch Mind (advantage on concentration saves)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine


# Load spells from spells.json
def _load_spells():
    """Load spells from spells.json (as dictionaries)."""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "spells.json"),
        os.path.join(os.path.dirname(__file__), "..", "spells.json"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("spells.json not found")


_SPELLS = _load_spells()


def _get_eldritch_blast_spell_dict():
    """Get Eldritch Blast spell dictionary from spells.json."""
    for spell_dict in _SPELLS:
        if spell_dict.get("name") == "Eldritch Blast":
            return spell_dict
    raise AssertionError("Eldritch Blast not found in spells.json")


def _dict_to_spell(spell_dict):
    """Convert spell dictionary to rpg.Spell object."""
    spell = rpg.Spell()
    spell.name = spell_dict.get("name", "")
    spell.level = spell_dict.get("level", 0)
    spell.range = spell_dict.get("range", 0)
    spell.radius = spell_dict.get("radius", 0)
    spell.width = spell_dict.get("width", 0)
    spell.length = spell_dict.get("length", 0)
    spell.duration = spell_dict.get("duration", 0)
    spell.requires_concentration = spell_dict.get("requires_concentration", False)

    # Geometry
    geom_name = spell_dict.get("geometry", "Single")
    spell.geometry = getattr(rpg.SpellGeometry, geom_name, rpg.SpellGeometry.Single)

    # Attack type
    attack_name = spell_dict.get("attack_type", "Automatic")
    spell.attack_type = getattr(rpg.SpellAttack, attack_name, rpg.SpellAttack.Automatic)

    # Multiple geometry properties
    spell.num_targets = spell_dict.get("num_targets", 1)
    spell.targets_per_upcast_level = spell_dict.get("targets_per_upcast_level", 0)

    return spell


def _warlock_stats(level, cha=10, invocations=None):
    """Create a Warlock stats object with optional invocations."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    s.warlock_subclass = rpg.WarlockSubclass.Fiend
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    s.cha = cha
    s.spell_slots_remaining = list(s.spell_slots_max)
    if invocations:
        s.eldritch_invocations = list(invocations)
    return s


def test_beam_count_scaling():
    """Test that Eldritch Blast beams scale with character level."""
    engine = setup_combat_engine()
    spell_dict = _get_eldritch_blast_spell_dict()
    spell = _dict_to_spell(spell_dict)

    # L1: 1 beam
    result = engine.get_num_targets_for_spell(spell, 0, 1)
    assert result == 1, f"L1 should have 1 beam, got {result}"

    # L5: 2 beams
    result = engine.get_num_targets_for_spell(spell, 0, 5)
    assert result == 2, f"L5 should have 2 beams, got {result}"

    # L11: 3 beams
    result = engine.get_num_targets_for_spell(spell, 0, 11)
    assert result == 3, f"L11 should have 3 beams, got {result}"

    # L17: 4 beams
    result = engine.get_num_targets_for_spell(spell, 0, 17)
    assert result == 4, f"L17 should have 4 beams, got {result}"

    print("✅ test_beam_count_scaling passed")


def test_invocation_storage_roundtrip():
    """Test that eldritch_invocations can be saved and loaded."""
    engine = setup_combat_engine()
    bm = setup_battle_map()

    # Add a warlock
    warlock_config = rpg.AgentConfig()
    warlock_config.name = "Warlock"
    warlock_config.start_col = 5
    warlock_config.start_row = 5
    warlock_config.size = 1
    warlock_config.sprite_path = "test.png"

    engine.add_agent_config(bm, warlock_config)
    engine.apply_agent_configs(bm)
    warlock_idx = 0

    # Create stats with invocations [0, 2]
    warlock_stats = _warlock_stats(5, invocations=[0, 2])
    engine.set_agent_stats(bm, warlock_idx, warlock_stats)

    # Verify they round-trip
    stats = engine.get_agent_stats(bm, warlock_idx)
    assert len(stats.eldritch_invocations) == 2, f"Expected 2 invocations, got {len(stats.eldritch_invocations)}"
    assert stats.has_invocation(0), "Agonizing Blast (code 0) not found"
    assert stats.has_invocation(2), "Eldritch Spear (code 2) not found"
    assert not stats.has_invocation(1), "Repelling Blast (code 1) should not be present"
    assert not stats.has_invocation(3), "Eldritch Mind (code 3) should not be present"

    # Update invocations
    stats.eldritch_invocations = [1, 3]
    engine.set_agent_stats(bm, warlock_idx, stats)

    # Verify updated invocations
    stats_reloaded = engine.get_agent_stats(bm, warlock_idx)
    assert len(stats_reloaded.eldritch_invocations) == 2, f"Expected 2 invocations after update, got {len(stats_reloaded.eldritch_invocations)}"
    assert not stats_reloaded.has_invocation(0), "Agonizing Blast should not be present"
    assert stats_reloaded.has_invocation(1), "Repelling Blast (code 1) not found"
    assert not stats_reloaded.has_invocation(2), "Eldritch Spear should not be present"
    assert stats_reloaded.has_invocation(3), "Eldritch Mind (code 3) not found"

    print("✅ test_invocation_storage_roundtrip passed")


if __name__ == '__main__':
    test_beam_count_scaling()
    test_invocation_storage_roundtrip()
    print("\n✅ All Warlock Phase 3 tests passed!")
