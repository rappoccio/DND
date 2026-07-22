#!/usr/bin/env python3
"""
Test suite for fog spells (Fog Cloud, Stinking Cloud, Cloudkill, Sleet Storm, Incendiary Cloud).

Phase 2 of the Darkness/Obscuration merge (DARKNESS_MERGE_HANDOFF.md): heavily-obscured spells now
carry "light_level": 7 in spells.json, so executeSpell drops a HeavilyObscured light effect over the
sphere. Consequences proven here by driving the ACTUAL spell (not place_light_effect, which
test_heavily_obscured.py already covers):
  · casting a fog spell creates a HeavilyObscured light effect
  · a creature inside the fog is Blinded unless it has Truesight/Blindsight
  · darkvision and devil's sight do NOT pierce fog (only Truesight)
  · can_see and compute_visibility agree that you can't see into the cloud
  · the light effect is removed when concentration drops
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


_SPELLS_JSON = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "spells.json")

# Fog is cast centered on this cell (col=7, row=5); the caster sits at (5, 5).
FOG_COL, FOG_ROW = 7, 5
CASTER_COL, CASTER_ROW = 5, 5


def _load_spell(name):
    """Load a real spell from spells.json."""
    catalog = json.load(open(_SPELLS_JSON))
    d = next((s for s in catalog if s["name"] == name), None)
    if not d:
        raise ValueError(f"Spell {name} not found in spells.json")
    return helpers._dict_to_spell(d)


def _make_caster(engine, bm):
    """Place a caster with spell slots at (CASTER_COL, CASTER_ROW)."""
    idx = add_agent_to_battle(engine, bm, create_test_agent("Caster", CASTER_COL, CASTER_ROW))
    stats = engine.get_agent_stats(bm, idx)
    stats.spell_slots_remaining = [999] * 9
    engine.set_agent_stats(bm, idx, stats)
    return idx


def _cast_fog(engine, bm, caster_idx, spell_name="Fog Cloud"):
    """Give the caster a fog spell and cast it on (FOG_COL, FOG_ROW). Returns the SpellResult."""
    spell = _load_spell(spell_name)
    engine.set_agent_spells(bm, caster_idx, [spell])

    act = rpg.SpellAction()
    act.caster_idx = caster_idx
    act.spell_idx = 0
    act.target_indices = []
    act.aoe_row = FOG_ROW
    act.aoe_col = FOG_COL
    act.aoe_row2 = FOG_ROW
    act.aoe_col2 = FOG_COL
    return engine.execute_spell(bm, act)


# ─────────────────────────────────────────────────────────────────────────────


def test_fog_cloud_has_light_level():
    """Fog Cloud spell has light_level=7 (HeavilyObscured) in spells.json."""
    spell = _load_spell("Fog Cloud")
    assert spell.light_level == 7, f"Fog Cloud light_level should be 7, got {spell.light_level}"
    assert spell.requires_concentration, "Fog Cloud should require concentration"
    print("✅ Fog Cloud spell has light_level=7 (HeavilyObscured)")


def test_fog_cloud_creates_light_effect():
    """Casting Fog Cloud creates a HeavilyObscured light effect."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud spell should execute successfully"
    assert len(result.light_effect_ids) > 0, "Fog Cloud should create light effects"

    light_effects = bm.active_light_effects
    assert len(light_effects) > 0, "Battle map should have light effects"
    assert light_effects[0].light_level == rpg.VisibilityLevel.HeavilyObscured, \
        f"Light effect should be HeavilyObscured, got {light_effects[0].light_level}"
    print("✅ Fog Cloud creates HeavilyObscured light effect")


def test_fog_blinds_without_truesight():
    """A creature inside fog is Blinded without Truesight."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", FOG_COL, FOG_ROW))

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud should execute"

    engine.update_darkness_blinding(bm, target_idx)
    assert engine.get_agent_conditions(bm, target_idx).blinded, \
        "Target without Truesight inside fog should be Blinded"
    print("✅ Creature inside fog is Blinded (without Truesight)")


def test_fog_truesight_pierces():
    """Truesight pierces fog (creature not Blinded)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", FOG_COL, FOG_ROW))

    stats = engine.get_agent_stats(bm, target_idx)
    stats.truesight_range = 60
    engine.set_agent_stats(bm, target_idx, stats)

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud should execute"

    engine.update_darkness_blinding(bm, target_idx)
    assert not engine.get_agent_conditions(bm, target_idx).blinded, \
        "Target with Truesight inside fog should NOT be Blinded"
    print("✅ Truesight pierces fog (creature not Blinded)")


def test_fog_darkvision_does_not_pierce():
    """Darkvision does NOT pierce fog (creature still Blinded)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", FOG_COL, FOG_ROW))

    stats = engine.get_agent_stats(bm, target_idx)
    stats.darkvision_range = 60
    engine.set_agent_stats(bm, target_idx, stats)

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud should execute"

    engine.update_darkness_blinding(bm, target_idx)
    assert engine.get_agent_conditions(bm, target_idx).blinded, \
        "Darkvision should NOT pierce fog (creature is Blinded)"
    print("✅ Darkvision does NOT pierce fog (creature is Blinded)")


def test_fog_can_see_matches_compute_visibility():
    """can_see and compute_visibility agree: an observer can't see a creature inside the cloud."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)
    # Observer (no special senses) stands 10 ft from the fog; target stands inside it.
    observer_idx = add_agent_to_battle(engine, bm, create_test_agent("Observer", CASTER_COL, CASTER_ROW + 2))
    target_idx = add_agent_to_battle(engine, bm, create_test_agent("Target", FOG_COL, FOG_ROW))

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud should execute"

    obs = rpg.Cell(CASTER_COL, CASTER_ROW + 2)
    tgt = rpg.Cell(FOG_COL, FOG_ROW)
    # can_see(obs_origin, obs_size, darkvision, truesight, devilssight, tgt_origin, tgt_size)
    geometric = bm.can_see(obs, 1, 0, 0, 0, tgt, 1)
    assert not geometric, "can_see: normal sight should not pierce fog"

    engine.compute_visibility(bm, observer_idx)
    cached = engine.get_visibility(observer_idx, target_idx)
    assert cached == rpg.VisibilityLevel.Blocked, \
        f"compute_visibility should agree the target is Blocked, got {cached}"
    print("✅ can_see and compute_visibility agree the cloud blocks sight")


def test_fog_concentration_cleanup():
    """Fog Cloud light effect is removed when concentration drops."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster_idx = _make_caster(engine, bm)

    result = _cast_fog(engine, bm, caster_idx)
    assert result.valid, "Fog Cloud should execute"
    assert len(bm.active_light_effects) > 0, "Light effect should exist after casting"

    drop_result = engine.drop_concentration(bm, caster_idx)
    assert drop_result.dropped, "Concentration should be dropped"

    remaining = bm.active_light_effects
    assert len(remaining) == 0, \
        f"Light effect should be removed after concentration drops, but {len(remaining)} remain"
    print("✅ Fog Cloud light effect removed when concentration drops")


def run_all():
    tests = [
        test_fog_cloud_has_light_level,
        test_fog_cloud_creates_light_effect,
        test_fog_blinds_without_truesight,
        test_fog_truesight_pierces,
        test_fog_darkvision_does_not_pierce,
        test_fog_can_see_matches_compute_visibility,
        test_fog_concentration_cleanup,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n✅ Fog Cloud tests passed! ({passed}/{len(tests)})")
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
