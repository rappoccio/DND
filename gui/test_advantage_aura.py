#!/usr/bin/env python3
"""
Tests for the data-driven "advantage emanation" (Spell::grants_advantage_aura): a
caster-following Sphere whose conscious caster and same-faction allies within `radius`
ft gain Advantage on attack rolls and saving throws. Covers the helper's range / self /
ally / enemy semantics, the aura following the caster, ending on concentration drop, the
behavioral attack-advantage hook, and serialization round-trip.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _spell_to_dict, _dict_to_spell
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)


def _aura_spell(radius=15):
    """A buff emanation: a moving Sphere (centered on the caster) that grants Advantage to
    the caster + allies inside `radius`. Help-type so it deals no damage and rolls no save."""
    s = rpg.Spell()
    s.name = "Aura of Advantage"
    s.level = 0  # avoid spell-slot bookkeeping in tests
    s.type = rpg.SpellType.Help
    s.geometry = rpg.SpellGeometry.Sphere
    s.attack_type = rpg.SpellAttack.Automatic
    s.radius = radius
    s.range = 0
    s.duration = 100  # >1 so a persistent (anchored) zone is created
    s.moves_with_caster = True
    s.requires_concentration = True
    s.grants_advantage_aura = True
    return s


def _arm_caster(engine, bm, caster, spell):
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [spell])


def _cast(engine, bm, caster):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.aoe_col = bm.placed_agents[caster].origin.col
    action.aoe_row = bm.placed_agents[caster].origin.row
    return engine.execute_spell(bm, action)


def _wpn(name="Sword"):
    w = rpg.Weapon()
    w.name = name
    w.damage_dice = 8
    w.damage_dice_count = 1
    w.range_short_feet = 5
    w.range_long_feet = 5
    return w


def test_helper_range_self_ally_enemy():
    """The aura reaches the caster and same-faction allies in range; it spares out-of-range
    allies and never benefits enemies (a different faction)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster   = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    near_all = add_agent_to_battle(engine, bm, create_test_agent("NearAlly", 7, 5))   # 10 ft
    far_all  = add_agent_to_battle(engine, bm, create_test_agent("FarAlly", 11, 5))   # 30 ft
    enemy    = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))      # 5 ft, hostile

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(near_all, 1)
    bm.set_agent_faction(far_all, 1)
    bm.set_agent_faction(enemy, 2)

    _arm_caster(engine, bm, caster, _aura_spell(radius=15))
    _cast(engine, bm, caster)

    assert engine.has_advantage_aura(bm, caster),  "caster benefits from its own aura"
    assert engine.has_advantage_aura(bm, near_all), "ally within 15 ft benefits"
    assert not engine.has_advantage_aura(bm, far_all), "ally beyond 15 ft does not benefit"
    assert not engine.has_advantage_aura(bm, enemy), "an enemy in range never benefits"
    print("✅ test_helper_range_self_ally_enemy passed")


def test_aura_follows_caster():
    """Reading the caster's live position, the aura sweeps onto an ally as the caster nears,
    and off an ally as the caster departs — no extra bookkeeping."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 2))  # 30 ft away

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)

    _arm_caster(engine, bm, caster, _aura_spell(radius=15))
    _cast(engine, bm, caster)
    assert not engine.has_advantage_aura(bm, ally), "ally starts outside the aura"

    # Caster advances to within 15 ft of the ally.
    engine.begin_turn(bm, caster)
    bm.placed_agents[caster].init_movement(60)
    assert engine.move_agent(bm, caster, rpg.Cell(6, 2), rpg.MovementType.Walk)
    assert engine.has_advantage_aura(bm, ally), "the aura should follow the caster onto the ally"

    # Caster walks back out of range.
    bm.placed_agents[caster].init_movement(60)
    assert engine.move_agent(bm, caster, rpg.Cell(2, 2), rpg.MovementType.Walk)
    assert not engine.has_advantage_aura(bm, ally), "leaving the aura ends the benefit"
    print("✅ test_aura_follows_caster passed")


def test_aura_ends_on_concentration_drop():
    """The emanation rides the concentration effect — dropping concentration ends the aura."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)

    _arm_caster(engine, bm, caster, _aura_spell(radius=15))
    _cast(engine, bm, caster)
    assert engine.has_advantage_aura(bm, ally), "ally benefits while the aura is up"

    engine.drop_concentration(bm, caster)
    assert not engine.has_advantage_aura(bm, ally), "dropping concentration ends the aura"
    print("✅ test_aura_ends_on_concentration_drop passed")


def test_unconscious_caster_suppresses_aura():
    """Like the Paladin aura, the emanation radiates only from a conscious caster."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)

    _arm_caster(engine, bm, caster, _aura_spell(radius=15))
    _cast(engine, bm, caster)
    assert engine.has_advantage_aura(bm, ally), "ally benefits while the caster is up"

    cs = engine.get_agent_stats(bm, caster)
    cs.hp_cur = 0
    engine.set_agent_stats(bm, caster, cs)
    assert not engine.has_advantage_aura(bm, ally), "a downed caster's aura is suppressed"
    print("✅ test_unconscious_caster_suppresses_aura passed")


def test_attack_advantage_is_granted():
    """End-to-end: an ally inside the aura rolls its attack with Advantage (AttackResult.advantage),
    and an ally outside it does not."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    ally   = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    enemy  = add_agent_to_battle(engine, bm, create_test_agent("Enemy", 7, 5), hp=100)

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)
    engine.set_agent_weapons(bm, ally, [_wpn(), rpg.Weapon(), rpg.Weapon()])

    _arm_caster(engine, bm, caster, _aura_spell(radius=15))
    _cast(engine, bm, caster)

    engine.begin_turn(bm, ally)
    r = engine.execute_action(bm, rpg.Attack(ally, enemy, 0))
    assert r.advantage, "an ally inside the advantage aura should attack with Advantage"

    # Drop the aura; the same ally attacking the same enemy no longer has Advantage.
    engine.drop_concentration(bm, caster)
    engine.begin_turn(bm, ally)
    r2 = engine.execute_action(bm, rpg.Attack(ally, enemy, 0))
    assert not r2.advantage, "with no aura, the ally should not have Advantage"
    print("✅ test_attack_advantage_is_granted passed")


def test_serialization_round_trip():
    """grants_advantage_aura must survive a save/reload (spell dict round-trip)."""
    s = _aura_spell(radius=20)
    d = _spell_to_dict(s)
    assert d["grants_advantage_aura"] is True, "flag must be written to the spell dict"
    s2 = _dict_to_spell(d)
    assert s2.grants_advantage_aura is True, "flag must be read back from the spell dict"

    # A spell without the flag must round-trip as False (default).
    plain = rpg.Spell()
    assert _dict_to_spell(_spell_to_dict(plain)).grants_advantage_aura is False
    print("✅ test_serialization_round_trip passed")


if __name__ == "__main__":
    test_helper_range_self_ally_enemy()
    test_aura_follows_caster()
    test_aura_ends_on_concentration_drop()
    test_unconscious_caster_suppresses_aura()
    test_attack_advantage_is_granted()
    test_serialization_round_trip()
    print("\n✅ All advantage-aura tests passed!")
