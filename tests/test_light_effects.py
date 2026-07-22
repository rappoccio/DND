#!/usr/bin/env python3
"""
Light effect creation from spells — Daylight (Sunlight) and Darkness (MagicalDark).

Daylight spell:
  · Creates a Sunlight light effect (VisibilityLevel::Sunlight = 6) over a Sphere
  · Lasts for its full duration (concentration not required)

Darkness spell:
  · Creates a MagicalDark light effect (VisibilityLevel::MagicalDark = 4) over a Sphere
  · Requires concentration

Verified here:
  · Daylight creates a Sunlight light effect; Darkness creates a MagicalDark one
  · Light effects are added to bm.active_light_effects (a property)
  · Light effects carry the correct light_level enum, name, source agent, and cells
  · Multiple light effects can coexist
  · A vampire takes 20 radiant at turn start when standing in Sunlight, none outside it

Engine facts this relies on (combat_spells.cpp / combat_internal.hpp):
  · A spell's `radius` is in FEET; a static Sphere covers a disk of (radius+4)//5 cells,
    so Daylight/Darkness (radius 15 ft) cover a ~3-cell-radius disk (~29 cells), NOT the
    whole map. All coordinates below fit the 11×11 test grid (cols/rows 0..10).
  · A non-moving Sphere light effect is placed at the AIM cell (aoe_col/aoe_row).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

_SPELLS_JSON = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "spells.json")


def _load_spell(name):
    """Load a real spell from spells.json."""
    catalog = json.load(open(_SPELLS_JSON))
    d = next((s for s in catalog if s["name"] == name), None)
    if not d:
        raise ValueError(f"Spell {name} not found in spells.json")
    return helpers._dict_to_spell(d)


def _place_caster(engine, bm, name, col, row, **abilities):
    """Place a caster. NOTE: do not set runtime stats (slots, etc.) here that must survive —
    each add_agent_to_battle calls applyAgentConfigs, which clears and rebuilds ALL agents from
    their configs, wiping any runtime stats set on earlier-placed agents. Slots are (re)granted
    at cast time in _cast_light, after every agent is placed."""
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), **abilities)


def _cast_light(engine, bm, caster_idx, spell, col, row):
    """Grant full spell slots, give `spell` to the caster, and cast it centered on (col, row).
    Slots are set here (post-placement) so they survive the applyAgentConfigs rebuilds. Returns
    the SpellResult."""
    stats = engine.get_agent_stats(bm, caster_idx)
    stats.spell_slots_remaining = [999] * 9
    engine.set_agent_stats(bm, caster_idx, stats)
    engine.set_agent_spells(bm, caster_idx, [spell])
    act = rpg.SpellAction()
    act.caster_idx = caster_idx
    act.spell_idx = 0
    act.target_indices = []
    act.aoe_col = col
    act.aoe_row = row
    act.aoe_col2 = col
    act.aoe_row2 = row
    return engine.execute_spell(bm, act)


def test_daylight_light_effect():
    """Daylight spell creates a Sunlight light effect."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster_idx = _place_caster(engine, bm, "Wizard", 5, 5, intel=16, dex=14, hp=10, ac=12)

    spell = _load_spell("Daylight")
    assert spell.light_level == 6, f"Daylight light_level should be 6 (Sunlight), got {spell.light_level}"
    assert spell.radius == 15, f"Daylight radius should be 15, got {spell.radius}"

    # Cast Daylight at (7, 5) — 2 cells from the caster.
    result = _cast_light(engine, bm, caster_idx, spell, col=7, row=5)
    assert result.valid, "Daylight spell should be valid"
    assert len(result.light_effect_ids) > 0, "Daylight should create at least one light effect"

    light_effects = bm.active_light_effects
    assert len(light_effects) > 0, "Battle map should have active light effects"

    light_effect = light_effects[0]
    assert light_effect.light_level == rpg.VisibilityLevel.Sunlight, \
        f"Light effect should have Sunlight level, got {light_effect.light_level}"
    assert light_effect.source_agent_idx == caster_idx, \
        f"Light effect source should be caster ({caster_idx}), got {light_effect.source_agent_idx}"
    assert light_effect.name == "Daylight", \
        f"Light effect name should be 'Daylight', got '{light_effect.name}'"
    assert len(light_effect.cell_indices) > 0, "Light effect should cover cells"

    print(f"✓ Daylight creates Sunlight light effect with {len(light_effect.cell_indices)} cells")


def test_darkness_light_effect():
    """Darkness spell creates a MagicalDark light effect."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster_idx = _place_caster(engine, bm, "Warlock", 5, 5, cha=16, dex=14, con=12, hp=9, ac=12)

    spell = _load_spell("Darkness")
    assert spell.light_level == 4, f"Darkness light_level should be 4 (MagicalDark), got {spell.light_level}"
    assert spell.radius == 15, f"Darkness radius should be 15, got {spell.radius}"

    # Cast Darkness at (3, 5).
    result = _cast_light(engine, bm, caster_idx, spell, col=3, row=5)
    assert result.valid, "Darkness spell should be valid"
    assert len(result.light_effect_ids) > 0, "Darkness should create at least one light effect"

    light_effects = bm.active_light_effects
    assert len(light_effects) > 0, "Battle map should have active light effects"

    light_effect = light_effects[0]
    assert light_effect.light_level == rpg.VisibilityLevel.MagicalDark, \
        f"Light effect should have MagicalDark level, got {light_effect.light_level}"
    assert light_effect.source_agent_idx == caster_idx, \
        f"Light effect source should be caster ({caster_idx}), got {light_effect.source_agent_idx}"
    assert light_effect.name == "Darkness", \
        f"Light effect name should be 'Darkness', got '{light_effect.name}'"
    assert len(light_effect.cell_indices) > 0, "Light effect should cover cells"

    print(f"✓ Darkness creates MagicalDark light effect with {len(light_effect.cell_indices)} cells")


def test_light_effect_coverage():
    """A Sphere light effect covers a disk of cells around its aim, including the center."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster_idx = _place_caster(engine, bm, "Wizard", 5, 5, intel=16, dex=14, hp=10, ac=12)
    spell = _load_spell("Daylight")

    # Cast on the caster's own cell so the full disk lands inside the grid.
    result = _cast_light(engine, bm, caster_idx, spell, col=5, row=5)
    assert result.valid, "Spell should be valid"

    light_effects = bm.active_light_effects
    assert len(light_effects) > 0, "Should have light effect"

    light_effect = light_effects[0]
    cell_count = len(light_effect.cell_indices)

    # Daylight's 15 ft radius -> a ~3-cell-radius disk (~29 cells); assert it covers a real
    # area (not a single cell) without over-fitting the exact disk count.
    assert cell_count >= 9, f"Expected a multi-cell sphere (>=9), got {cell_count}"

    # The aim cell (5, 5) must be in the effect. Cell index convention: row * grid_cols + col.
    center_idx = 5 * bm.grid_cols + 5
    assert center_idx in light_effect.cell_indices, "Center cell should be in light effect"

    print(f"✓ Light effect covers {cell_count} cells (reasonable for a 15 ft sphere)")


def test_multiple_light_effects():
    """Multiple light effects can coexist."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster1 = _place_caster(engine, bm, "Wizard1", 2, 2, intel=16, dex=14, hp=10, ac=12)
    caster2 = _place_caster(engine, bm, "Wizard2", 8, 8, intel=16, dex=14, hp=10, ac=12)

    daylight = _load_spell("Daylight")
    darkness = _load_spell("Darkness")

    result1 = _cast_light(engine, bm, caster1, daylight, col=2, row=2)
    assert result1.valid

    result2 = _cast_light(engine, bm, caster2, darkness, col=8, row=8)
    assert result2.valid

    light_effects = bm.active_light_effects
    assert len(light_effects) == 2, f"Expected 2 light effects, got {len(light_effects)}"

    sunlight_effect = next((e for e in light_effects if e.light_level == rpg.VisibilityLevel.Sunlight), None)
    magical_dark_effect = next((e for e in light_effects if e.light_level == rpg.VisibilityLevel.MagicalDark), None)

    assert sunlight_effect is not None, "Should have Sunlight effect"
    assert magical_dark_effect is not None, "Should have MagicalDark effect"

    print("✓ Multiple light effects coexist: Sunlight + MagicalDark")


def test_vampire_sunlight_damage():
    """A vampire takes 20 radiant damage at turn start while standing in Sunlight."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Vampire at (5, 5); a wizard at (2, 2) casts Daylight centered on the vampire.
    # Place BOTH agents first, then set the vampire's stats — applyAgentConfigs (run by each
    # placement) rebuilds all agents from configs, so vampire stats set before the wizard's
    # placement would be wiped.
    vampire_idx = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5))
    wizard_idx = _place_caster(engine, bm, "Wizard", 2, 2, intel=16, dex=14, hp=10, ac=12)

    vstats = engine.get_agent_stats(bm, vampire_idx)
    vstats.hp_max = 100
    vstats.hp_cur = 100
    vstats.is_vampire = True
    engine.set_agent_stats(bm, vampire_idx, vstats)

    daylight = _load_spell("Daylight")
    result = _cast_light(engine, bm, wizard_idx, daylight, col=5, row=5)
    assert result.valid, "Daylight spell should be valid"

    light_effects = bm.active_light_effects
    assert len(light_effects) > 0, "Should have light effect"
    assert light_effects[0].light_level == rpg.VisibilityLevel.Sunlight, "Should be Sunlight"

    initial_hp = engine.get_agent_stats(bm, vampire_idx).hp_cur
    assert initial_hp == 100, f"Vampire should start at 100 HP, got {initial_hp}"

    # Begin the vampire's turn — 20 radiant from Sunlight exposure.
    engine.begin_turn(bm, vampire_idx)

    final_hp = engine.get_agent_stats(bm, vampire_idx).hp_cur
    assert final_hp == 80, f"Vampire should take 20 damage in Sunlight, expected 80 HP, got {final_hp}"

    print("✓ Vampire takes 20 radiant damage at turn start in Sunlight (100 → 80 HP)")


def test_vampire_outside_sunlight_no_damage():
    """A vampire takes NO damage if its cell is outside the Sunlight sphere."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Vampire at (9, 9); Daylight cast at (3, 3) — ~8.5 cells away, well outside the 3-cell disk.
    # Place both agents first, then set the vampire's stats (see note in the sunlight-damage test).
    vampire_idx = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 9, 9))
    wizard_idx = _place_caster(engine, bm, "Wizard", 2, 2, intel=16, dex=14, hp=10, ac=12)

    vstats = engine.get_agent_stats(bm, vampire_idx)
    vstats.hp_max = 100
    vstats.hp_cur = 100
    vstats.is_vampire = True
    engine.set_agent_stats(bm, vampire_idx, vstats)

    daylight = _load_spell("Daylight")
    result = _cast_light(engine, bm, wizard_idx, daylight, col=3, row=3)
    assert result.valid, "Daylight spell should be valid"

    initial_hp = engine.get_agent_stats(bm, vampire_idx).hp_cur
    assert initial_hp == 100, f"Vampire should start at 100 HP, got {initial_hp}"

    # Begin the vampire's turn — no Sunlight on its cell, so no damage.
    engine.begin_turn(bm, vampire_idx)

    final_hp = engine.get_agent_stats(bm, vampire_idx).hp_cur
    assert final_hp == 100, f"Vampire outside Sunlight should take no damage, expected 100 HP, got {final_hp}"

    print("✓ Vampire outside Sunlight takes no damage (100 HP unchanged)")


if __name__ == "__main__":
    test_daylight_light_effect()
    test_darkness_light_effect()
    test_light_effect_coverage()
    test_multiple_light_effects()
    test_vampire_sunlight_damage()
    test_vampire_outside_sunlight_no_damage()
    print("\n✅ All light effect tests passed!")
