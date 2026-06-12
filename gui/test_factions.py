#!/usr/bin/env python3
"""
Test suite for Factions / Teams (red vs blue vs neutral).

Covers:
  • faction get/set round-trip on PlacedAgent
  • Rule 1 — hiding ignores same-faction observers; enemies still block/spot a hide
  • Rule 2 — harmful AoE: friendly fire ON by default; selective_targeting spares allies
  • Rule 3 — beneficial (Heal) AoE only affects allies; neutral caster keeps legacy behavior
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── Spell builders ───────────────────────────────────────────────────────────
def _aoe_harm():
    sp = rpg.Spell()
    sp.name = "Fireball"
    sp.level = 0  # cantrip-level avoids spell-slot bookkeeping in the test
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Dexterity
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.radius = 20
    sp.range = 120
    return sp


def _aoe_heal():
    sp = rpg.Spell()
    sp.name = "Mass Cure"
    sp.level = 0
    sp.type = rpg.SpellType.Heal
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.radius = 20
    sp.range = 120
    h = rpg.HealingRoll()
    h.num_dice = 2
    h.die_size = 6
    h.bonus = 0
    sp.healing_type = h
    return sp


def _cast_sphere(engine, bm, caster, spell, col, row):
    engine.set_agent_spells(bm, caster, [spell])
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.aoe_col = col
    action.aoe_row = row
    return engine.execute_spell(bm, action)


# ── faction round-trip ────────────────────────────────────────────────────────
def test_faction_get_set_roundtrip():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 2, 2))
    # Default is neutral (0).
    assert bm.get_agent_faction(a) == 0, "agents default to neutral (faction 0)"
    bm.set_agent_faction(a, 1)
    assert bm.get_agent_faction(a) == 1
    assert bm.placed_agents[a].faction == 1, "readonly property mirrors the setter"
    print("✅ test_faction_get_set_roundtrip passed")


# ── Rule 1: hide vs only enemies ──────────────────────────────────────────────
def test_hide_ignores_allied_observer():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    hider = add_agent_to_battle(engine, bm, create_test_agent("Hider", 5, 5), dex=16)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 5), wis=20)
    bm.set_agent_faction(hider, 1)
    bm.set_agent_faction(ally, 1)
    # Sanity: the ally actually has LOS to the hider (otherwise the test is vacuous).
    assert bm.has_line_of_sight(rpg.Cell(5, 5), 1, rpg.Cell(8, 5), 1), "ally must have LOS"
    res = engine.check_hide(bm, hider, False)
    assert res.valid, "an ally in LOS must NOT prevent hiding"
    assert res.hidden, "with only allies watching, the hide should succeed"
    print("✅ test_hide_ignores_allied_observer passed")


def test_hide_blocked_by_enemy_observer():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    hider = add_agent_to_battle(engine, bm, create_test_agent("Hider", 5, 5), dex=16)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 5), wis=14)
    bm.set_agent_faction(hider, 1)
    bm.set_agent_faction(enemy, 2)
    assert bm.has_line_of_sight(rpg.Cell(5, 5), 1, rpg.Cell(8, 5), 1), "enemy must have LOS"
    res = engine.check_hide(bm, hider, False)
    assert not res.valid, "an enemy with LOS must prevent hiding"
    print("✅ test_hide_blocked_by_enemy_observer passed")


# ── Rule 2: harmful AoE friendly fire + selective sparing ─────────────────────
def test_harm_aoe_friendly_fire_on_by_default():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 8), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 9), hp=100)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)
    res = _cast_sphere(engine, bm, caster, _aoe_harm(), 8, 8)
    hit = {tr.target_idx for tr in res.target_results}
    assert ally in hit, "ordinary Fireball must still roast allies (friendly fire ON)"
    assert enemy in hit, "enemy is hit too"
    print("✅ test_harm_aoe_friendly_fire_on_by_default passed")


def test_harm_aoe_selective_targeting_spares_allies():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 8), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 9), hp=100)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)
    sp = _aoe_harm()
    sp.name = "Radiance of the Dawn"
    sp.selective_targeting = True
    res = _cast_sphere(engine, bm, caster, sp, 8, 8)
    hit = {tr.target_idx for tr in res.target_results}
    assert ally not in hit, "selective_targeting must spare the caster's ally"
    assert enemy in hit, "the enemy is still struck"
    print("✅ test_harm_aoe_selective_targeting_spares_allies passed")


# ── Rule 3: beneficial AoE only affects allies ────────────────────────────────
def test_heal_aoe_excludes_enemies():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 8), hp=100)
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 8, 9), hp=100)
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)
    res = _cast_sphere(engine, bm, caster, _aoe_heal(), 8, 8)
    hit = {tr.target_idx for tr in res.target_results}
    assert ally in hit, "the ally should be healed"
    assert enemy not in hit, "an enemy must never be healed by an area heal"
    print("✅ test_heal_aoe_excludes_enemies passed")


def test_neutral_caster_heal_keeps_legacy_behavior():
    """A neutral (faction 0) caster has no team, so its area heal still touches everyone in
    range — preserving behavior for un-teamed encounters and old saves."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 8, 8), hp=100)
    b = add_agent_to_battle(engine, bm, create_test_agent("B", 8, 9), hp=100)
    # All neutral (default).
    res = _cast_sphere(engine, bm, caster, _aoe_heal(), 8, 8)
    hit = {tr.target_idx for tr in res.target_results}
    assert a in hit and b in hit, "neutral caster's area heal affects everyone (legacy)"
    print("✅ test_neutral_caster_heal_keeps_legacy_behavior passed")


if __name__ == "__main__":
    tests = [
        test_faction_get_set_roundtrip,
        test_hide_ignores_allied_observer,
        test_hide_blocked_by_enemy_observer,
        test_harm_aoe_friendly_fire_on_by_default,
        test_harm_aoe_selective_targeting_spares_allies,
        test_heal_aoe_excludes_enemies,
        test_neutral_caster_heal_keeps_legacy_behavior,
    ]
    print("Running Faction / Team Tests...")
    print("=" * 60)
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
