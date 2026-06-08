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


def _add_warlock(engine, bm, level, cha=10, dex=10, invocations=None):
    """Place a single Warlock on the map and return its index."""
    cfg = rpg.AgentConfig()
    cfg.name = "Warlock"
    cfg.start_col = 5
    cfg.start_row = 5
    cfg.size = 1
    cfg.sprite_path = "test.png"
    engine.add_agent_config(bm, cfg)
    engine.apply_agent_configs(bm)
    idx = 0
    s = _warlock_stats(level, cha=cha, invocations=invocations)
    s.dex = dex
    engine.set_agent_stats(bm, idx, s)
    return idx


def test_armor_of_shadows_ac():
    """Armor of Shadows (code 5): unarmored AC = 13 + DEX, no slot, always on."""
    # DEX 16 (+3) → Mage Armor AC 16; without the invocation → base AC.
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, dex=16, invocations=[5])
    ac = engine.calculate_ac(bm, idx)
    assert ac == 16, f"Armor of Shadows: expected AC 13+3=16, got {ac}"

    # Control: same warlock without the invocation must NOT get 13+DEX.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, dex=16, invocations=[])
    ac2 = engine2.calculate_ac(bm2, idx2)
    assert ac2 != 16, f"No invocation should not yield Mage Armor AC, got {ac2}"

    print("✅ test_armor_of_shadows_ac passed")


def test_fiendish_vigor_temp_hp():
    """Fiendish Vigor (code 6): max False Life (2d4+4 = 12) temp HP on first turn."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[6])
    assert engine.get_agent_stats(bm, idx).temp_hp == 0, "should start with 0 temp HP"
    engine.begin_turn(bm, idx)
    assert engine.get_agent_stats(bm, idx).temp_hp == 12, \
        f"Fiendish Vigor: expected 12 temp HP, got {engine.get_agent_stats(bm, idx).temp_hp}"

    # Control: no invocation → no temp HP granted.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    engine2.begin_turn(bm2, idx2)
    assert engine2.get_agent_stats(bm2, idx2).temp_hp == 0, "no invocation = no temp HP"

    print("✅ test_fiendish_vigor_temp_hp passed")


def test_devils_sight_vision():
    """Devil's Sight (code 4): materialize devilssight_range = 120 ft (see in dark)."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[4])
    assert engine.get_agent_stats(bm, idx).devilssight_range == 120, \
        f"Devil's Sight: expected devilssight_range 120, got {engine.get_agent_stats(bm, idx).devilssight_range}"

    # Control: no invocation → no devil's sight.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    assert engine2.get_agent_stats(bm2, idx2).devilssight_range == 0, "no invocation = no devil's sight"

    print("✅ test_devils_sight_vision passed")


def test_eldritch_spear_range():
    """Eldritch Spear (code 2): EB range += 30 ft x Warlock level."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[2])
    eb = _dict_to_spell(_get_eldritch_blast_spell_dict())
    base = eb.range
    eff = engine.effective_spell_range(bm, idx, eb)
    assert eff == base + 30 * 5, f"Eldritch Spear L5: expected {base + 150}, got {eff}"

    # Control: no invocation → unchanged range.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    assert engine2.effective_spell_range(bm2, idx2, eb) == base, "no invocation = base range"

    print("✅ test_eldritch_spear_range passed")


def test_witch_sight_truesight():
    """Witch Sight (code 7): materialize truesight_range = 30 ft."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=15, invocations=[7])
    assert engine.get_agent_stats(bm, idx).truesight_range == 30, \
        f"Witch Sight: expected truesight_range 30, got {engine.get_agent_stats(bm, idx).truesight_range}"

    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=15, invocations=[])
    assert engine2.get_agent_stats(bm2, idx2).truesight_range == 0, "no invocation = no truesight"

    print("✅ test_witch_sight_truesight passed")


def test_gift_of_the_depths_swim():
    """Gift of the Depths (code 11): swim speed becomes equal to walk speed."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[11])
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = 30
    s.speed_swim = 0
    engine.set_agent_stats(bm, idx, s)
    out = engine.get_agent_stats(bm, idx)
    assert out.speed_swim == 30, f"Gift of the Depths: expected swim 30, got {out.speed_swim}"

    # Control: no invocation → swim stays 0.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    s2 = engine2.get_agent_stats(bm2, idx2)
    s2.speed_walk = 30
    s2.speed_swim = 0
    engine2.set_agent_stats(bm2, idx2, s2)
    assert engine2.get_agent_stats(bm2, idx2).speed_swim == 0, "no invocation = no swim grant"

    print("✅ test_gift_of_the_depths_swim passed")


if __name__ == '__main__':
    test_beam_count_scaling()
    test_invocation_storage_roundtrip()
    test_armor_of_shadows_ac()
    test_fiendish_vigor_temp_hp()
    test_devils_sight_vision()
    test_eldritch_spear_range()
    test_witch_sight_truesight()
    test_gift_of_the_depths_swim()
    print("\n✅ All Warlock Phase 3 tests passed!")
