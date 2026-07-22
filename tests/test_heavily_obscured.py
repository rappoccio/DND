#!/usr/bin/env python3
"""
Test suite for the HeavilyObscured (fog / smoke) visibility level.

HeavilyObscured is the non-magical, light-independent "effectively Blinded" state produced by fog,
smoke, or dense foliage. Unlike Dark (Darkness, pierced by darkvision) and MagicalDark (pierced by
devil's sight), HeavilyObscured is pierced ONLY by Truesight/Blindsight and CANNOT be dispelled by
bright light. See DARKNESS_MERGE_HANDOFF.md (the "correct" semantics version).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

FOG = rpg.Cell(7, 5)        # the obscured cell (col=7, row=5)
OBSERVER = rpg.Cell(5, 5)   # 10 ft away, in the clear


def _fog_a_cell(bm, cell, level=rpg.VisibilityLevel.HeavilyObscured):
    """Place a permanent obscuration/light effect over one cell and recompute lighting."""
    bm.place_light_effect("Fog", [cell], level, -1, -1)
    bm.update_lighting()


def test_enum_value_exists():
    assert hasattr(rpg.VisibilityLevel, 'HeavilyObscured')
    # Must be appended last (int 7) to preserve the spells.json light_level contract.
    assert int(rpg.VisibilityLevel.HeavilyObscured) == 7
    print("✅ HeavilyObscured enum exists and is value 7 (appended last)")


def test_fog_sets_light_level():
    bm = setup_battle_map()
    _fog_a_cell(bm, FOG)
    assert bm.get_light_level(FOG) == rpg.VisibilityLevel.HeavilyObscured
    print("✅ placing fog sets the cell's light level to HeavilyObscured")


def test_fog_survives_bright_light():
    """Bright light cannot dispel fog (override, not a brighter()-combine)."""
    bm = setup_battle_map()
    # Brightest possible effect on the same cell, then fog on top.
    bm.place_light_effect("Daylight", [FOG], rpg.VisibilityLevel.Sunlight, -1, -1)
    bm.place_light_effect("Fog", [FOG], rpg.VisibilityLevel.HeavilyObscured, -1, -1)
    bm.update_lighting()
    assert bm.get_light_level(FOG) == rpg.VisibilityLevel.HeavilyObscured
    print("✅ fog survives bright light (override beats brighter-wins)")


def test_magical_dark_beats_fog():
    """Where magical darkness and fog overlap, MagicalDark wins (more restrictive)."""
    bm = setup_battle_map()
    bm.place_light_effect("Fog", [FOG], rpg.VisibilityLevel.HeavilyObscured, -1, -1)
    bm.place_light_effect("Darkness", [FOG], rpg.VisibilityLevel.MagicalDark, -1, -1)
    bm.update_lighting()
    assert bm.get_light_level(FOG) == rpg.VisibilityLevel.MagicalDark
    print("✅ MagicalDark overrides fog on overlap")


def test_can_see_through_fog_by_sense():
    """Darkvision and devil's sight do NOT pierce fog; only truesight does."""
    bm = setup_battle_map()
    _fog_a_cell(bm, FOG)

    # can_see(obs_origin, obs_size, darkvision, truesight, devilssight, tgt_origin, tgt_size)
    normal     = bm.can_see(OBSERVER, 1, 0,   0,  0,   FOG, 1)
    darkvision = bm.can_see(OBSERVER, 1, 60,  0,  0,   FOG, 1)
    devils     = bm.can_see(OBSERVER, 1, 0,   0,  120, FOG, 1)
    truesight  = bm.can_see(OBSERVER, 1, 0,   60, 0,   FOG, 1)

    assert not normal,     "normal sight should not pierce fog"
    assert not darkvision, "darkvision should NOT pierce fog (unlike Darkness)"
    assert not devils,     "devil's sight should NOT pierce fog (unlike MagicalDarkness)"
    assert truesight,      "truesight should pierce fog"
    print("✅ can_see: only truesight pierces fog (not darkvision, not devil's sight)")


def test_darkvision_still_pierces_darkness_not_fog():
    """Regression guard: Dark (Darkness) is still pierced by darkvision — only fog isn't."""
    bm = setup_battle_map()
    _fog_a_cell(bm, FOG, level=rpg.VisibilityLevel.Dark)
    assert bm.can_see(OBSERVER, 1, 60, 0, 0, FOG, 1), "darkvision should pierce plain Darkness"
    print("✅ darkvision still pierces Darkness (the distinction that justifies two levels)")


def test_fog_blinds_without_truesight():
    """A creature standing in fog is Blinded unless it has Truesight/Blindsight."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    # Target stands in the fog cell.
    idx = add_agent_to_battle(engine, bm, create_test_agent("Fogged", FOG.col, FOG.row))
    _fog_a_cell(bm, FOG)

    engine.update_darkness_blinding(bm, idx)
    assert engine.get_agent_conditions(bm, idx).blinded, "no-truesight creature in fog should be Blinded"

    # Give it truesight and re-evaluate → no longer blinded by the fog.
    stats = engine.get_agent_stats(bm, idx)
    stats.truesight_range = 60
    engine.set_agent_stats(bm, idx, stats)
    engine.update_darkness_blinding(bm, idx)
    assert not engine.get_agent_conditions(bm, idx).blinded, "truesight creature should see through fog"
    print("✅ fog Blinds creatures inside it unless they have truesight")


def test_darkvision_does_not_clear_fog_blinding():
    """Darkvision rescues you from Darkness but NOT from fog."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Fogged", FOG.col, FOG.row))
    stats = engine.get_agent_stats(bm, idx)
    stats.darkvision_range = 60
    engine.set_agent_stats(bm, idx, stats)
    _fog_a_cell(bm, FOG)

    engine.update_darkness_blinding(bm, idx)
    assert engine.get_agent_conditions(bm, idx).blinded, "darkvision must NOT clear fog blinding"
    print("✅ darkvision does not clear fog blinding (it would clear Darkness)")


def run_all():
    tests = [
        test_enum_value_exists,
        test_fog_sets_light_level,
        test_fog_survives_bright_light,
        test_magical_dark_beats_fog,
        test_can_see_through_fog_by_sense,
        test_darkvision_still_pierces_darkness_not_fog,
        test_fog_blinds_without_truesight,
        test_darkvision_does_not_clear_fog_blinding,
    ]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n✅ All HeavilyObscured tests passed! ({passed}/{len(tests)})")


if __name__ == "__main__":
    run_all()
