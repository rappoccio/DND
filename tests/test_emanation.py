#!/usr/bin/env python3
"""
Tests for the "Emanation" spell type: a Sphere whose center follows the caster
(Spirit Guardians). Covers caster-centering, caster exclusion, the zone following
the caster's movement (sweep), once-per-turn dedup, and save-for-half on the tick.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _radiant_3d8():
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Radiant
    roll.num_dice = 3
    roll.die_size = 8
    return roll


def _emanation(attack=None):
    """Spirit-Guardians-like moving Sphere. Defaults to Automatic so the damage is
    deterministic (no save) for the structural tests."""
    s = rpg.Spell()
    s.name = "Spirit Guardians"
    s.level = 0  # avoid spell-slot bookkeeping in tests
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Sphere
    s.attack_type = attack if attack is not None else rpg.SpellAttack.Automatic
    s.save_ability = rpg.SaveAbility.Wisdom
    s.radius = 15
    s.range = 0
    s.duration = 100  # >1 so a persistent zone is created; ends on concentration drop
    s.moves_with_caster = True
    s.requires_concentration = True
    s.effects_on_begin_turn = True
    s.magic_damage_rolls = [_radiant_3d8()]
    return s


def _arm_caster(engine, bm, caster, spell):
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [spell])


def _cast(engine, bm, caster, aoe_col, aoe_row):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.aoe_col = aoe_col
    action.aoe_row = aoe_row
    return engine.execute_spell(bm, action)


def _has_cell(cells, col, row):
    return any(c.col == col and c.row == row for c in cells)


def test_zone_centers_on_caster_not_aim():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    _arm_caster(engine, bm, caster, _emanation())

    # Aim far away from the caster; a moving Sphere must ignore the aim and center on the caster.
    _cast(engine, bm, caster, aoe_col=11, aoe_row=11)

    effects = bm.active_spell_effects
    assert len(effects) == 1, f"expected one persistent zone, got {len(effects)}"
    cells = effects[0].cells
    assert _has_cell(cells, 5, 5), "zone must cover the caster's cell"
    assert not _has_cell(cells, 11, 11), "zone must NOT center on the aim point"
    print("✅ test_zone_centers_on_caster_not_aim passed")


def test_caster_excluded_enemy_hit_at_cast():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5), hp=100)
    _arm_caster(engine, bm, caster, _emanation())

    caster_hp = engine.get_agent_stats(bm, caster).hp_cur
    res = _cast(engine, bm, caster, aoe_col=5, aoe_row=5)
    hit = {tr.target_idx for tr in res.target_results}

    assert caster not in hit, "the caster's own Emanation must never target the caster"
    assert enemy in hit, "an adjacent enemy should be inside the Emanation at cast"
    assert engine.get_agent_stats(bm, caster).hp_cur == caster_hp, "caster took self-damage"
    assert engine.get_agent_stats(bm, enemy).hp_cur < 100, "enemy should have taken damage"
    print("✅ test_caster_excluded_enemy_hit_at_cast passed")


def test_zone_follows_caster_onto_enemy():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 2, 2))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 8, 2), hp=100)
    _arm_caster(engine, bm, caster, _emanation())

    # Enemy is 30 ft away — outside the 15 ft zone — so the cast doesn't touch it.
    _cast(engine, bm, caster, aoe_col=2, aoe_row=2)
    assert engine.get_agent_stats(bm, enemy).hp_cur == 100, "enemy should be outside the zone at cast"

    # Caster advances to within 15 ft; the zone sweeps onto the enemy.
    engine.begin_turn(bm, caster)
    bm.placed_agents[caster].init_movement(60)  # seed the agent's walk budget
    moved = engine.move_agent(bm, caster, rpg.Cell(5, 2), rpg.MovementType.Walk)
    assert moved, "caster move should succeed on open ground"
    assert engine.get_agent_stats(bm, enemy).hp_cur < 100, "zone sweeping onto the enemy should damage it"
    print("✅ test_zone_follows_caster_onto_enemy passed")


def test_once_per_turn_dedup():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5), hp=200)
    _arm_caster(engine, bm, caster, _emanation())
    _cast(engine, bm, caster, aoe_col=5, aoe_row=5)

    # Enemy's turn begins inside the zone -> takes damage once.
    engine.begin_turn(bm, enemy)
    hp_after_begin = engine.get_agent_stats(bm, enemy).hp_cur
    assert hp_after_begin < 200, "enemy should be damaged when starting its turn in the zone"

    # Moving within the same zone on the same turn must NOT damage it again.
    bm.placed_agents[enemy].init_movement(60)  # seed the agent's walk budget
    moved = engine.move_agent(bm, enemy, rpg.Cell(5, 6), rpg.MovementType.Walk)
    assert moved, "enemy move should succeed"
    assert engine.get_agent_stats(bm, enemy).hp_cur == hp_after_begin, \
        "a creature is affected at most once per turn (no second hit when shuffling in-zone)"
    print("✅ test_once_per_turn_dedup passed")


def test_zone_spares_allies_hits_enemies():
    """Spirit Guardians is 'creatures of your choice' (selective_targeting): the ongoing
    zone must spare the caster's allies the same way the cast does, while still damaging
    enemies who enter it or start their turn in it."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    ally  = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 9, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 9, 6))

    # add_agent_to_battle re-applies all configs (destructive), resetting earlier agents'
    # stats — so set HP for everyone AFTER the last agent is placed.
    for idx in (ally, enemy):
        s = engine.get_agent_stats(bm, idx)
        s.hp_max = 100
        s.hp_cur = 100
        engine.set_agent_stats(bm, idx, s)

    # Put caster + ally on team 1, enemy on team 2.
    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)

    spell = _emanation()
    spell.selective_targeting = True
    _arm_caster(engine, bm, caster, spell)
    _cast(engine, bm, caster, aoe_col=5, aoe_row=5)  # zone centered on caster, out of reach of both

    assert engine.get_agent_stats(bm, ally).hp_cur == 100, "ally outside zone at cast"
    assert engine.get_agent_stats(bm, enemy).hp_cur == 100, "enemy outside zone at cast"

    # Both walk adjacent to the caster, into the zone, on their own turns.
    engine.begin_turn(bm, ally)
    bm.placed_agents[ally].init_movement(60)
    assert engine.move_agent(bm, ally, rpg.Cell(6, 5), rpg.MovementType.Walk)
    assert engine.get_agent_stats(bm, ally).hp_cur == 100, \
        "an ally must NOT be damaged by the caster's own selective_targeting zone"

    engine.begin_turn(bm, enemy)
    bm.placed_agents[enemy].init_movement(60)
    assert engine.move_agent(bm, enemy, rpg.Cell(6, 6), rpg.MovementType.Walk)
    assert engine.get_agent_stats(bm, enemy).hp_cur < 100, "an enemy entering the zone takes damage"

    # And the ally starting its turn inside the zone is still spared.
    ally_hp = engine.get_agent_stats(bm, ally).hp_cur
    engine.begin_turn(bm, ally)
    assert engine.get_agent_stats(bm, ally).hp_cur == ally_hp, \
        "an ally starting its turn in the zone must not be damaged"
    print("✅ test_zone_spares_allies_hits_enemies passed")


def test_emanation_halves_enemy_speed_spares_allies():
    """Spirit Guardians halves Speed in the Emanation — modeled as Halved difficult terrain.
    It must slow enemies but NOT the caster's allies, and it must follow the caster."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    ally  = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 1, 1))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 1, 2))

    bm.set_agent_faction(caster, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(enemy, 2)

    spell = _emanation()
    spell.selective_targeting = True
    spell.terrain_difficulty = rpg.TerrainDifficulty.Halved
    _arm_caster(engine, bm, caster, spell)
    _cast(engine, bm, caster, aoe_col=5, aoe_row=5)

    # A cell well inside the 15-ft (3-cell) zone.
    in_zone = rpg.Cell(5, 5)
    assert bm.get_terrain_multiplier(in_zone) == 0.5, "cast should lay Halved terrain over the zone"

    # From the same origin and speed, an enemy (slowed) reaches fewer cells than an ally (spared).
    origin, speed = rpg.Cell(5, 5), 30
    reach_enemy = bm.reachable_cells(origin, 1, speed, rpg.MovementType.Walk, enemy)
    reach_ally  = bm.reachable_cells(origin, 1, speed, rpg.MovementType.Walk, ally)
    reach_caster = bm.reachable_cells(origin, 1, speed, rpg.MovementType.Walk, caster)
    assert len(reach_enemy) < len(reach_ally), \
        f"enemy should be slowed by the zone: enemy={len(reach_enemy)} ally={len(reach_ally)}"
    # The caster is spared exactly like the ally (full speed), so it reaches AT LEAST as many cells.
    # It may reach one MORE: a mover can stop on its own (vacated) origin square, but the ally cannot
    # stop on the caster's occupied square — the engine forbids ending a move on an ally's cell. That
    # occupancy artifact is not slowing, so we assert "not slowed" as >= a spared ally's reach.
    assert len(reach_caster) >= len(reach_ally), "the caster is never slowed by its own emanation"

    # The terrain follows the caster: move the caster, the old center clears and the new one is Halved.
    engine.begin_turn(bm, caster)
    bm.placed_agents[caster].init_movement(60)
    assert engine.move_agent(bm, caster, rpg.Cell(8, 8), rpg.MovementType.Walk)  # re-centers anchored terrain
    assert bm.get_terrain_multiplier(rpg.Cell(8, 8)) == 0.5, "zone terrain should follow the caster"
    assert bm.get_terrain_multiplier(rpg.Cell(5, 5)) == 1.0, "old zone terrain should clear after the move"
    print("✅ test_emanation_halves_enemy_speed_spares_allies passed")


def _save_zone_damage(caster_wis, target_wis):
    """Apply one Save-type zone tick to a target via begin_turn; return damage dealt.
    Both engines share seed 42, so the save d20 and the 3d8 are identical — only the
    pass/fail outcome (and thus the halving) differs."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5), wis=caster_wis)
    target = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5), wis=target_wis, hp=100)

    cs = engine.get_agent_stats(bm, caster)
    cs.prof_bonus = 2
    engine.set_agent_stats(bm, caster, cs)

    eff = rpg.ActiveSpellEffect()
    eff.caster_idx = caster
    eff.spell = _emanation(attack=rpg.SpellAttack.Save)
    eff.cells = [rpg.Cell(6, 5)]
    eff.turns_remaining = 5
    bm.add_spell_effect(eff)

    before = engine.get_agent_stats(bm, target).hp_cur
    engine.begin_turn(bm, target)
    return before - engine.get_agent_stats(bm, target).hp_cur


def test_save_for_half_on_tick():
    # High caster WIS + low target WIS -> guaranteed failed save -> full damage.
    full = _save_zone_damage(caster_wis=30, target_wis=1)
    # Low caster WIS + high target WIS -> guaranteed successful save -> half damage.
    half = _save_zone_damage(caster_wis=1, target_wis=30)

    assert full > 0, "a failed save should deal full damage"
    assert half == full // 2, f"a successful save should halve damage: full={full}, half={half}"
    print(f"✅ test_save_for_half_on_tick passed (full={full}, half={half})")


if __name__ == "__main__":
    test_zone_centers_on_caster_not_aim()
    test_caster_excluded_enemy_hit_at_cast()
    test_zone_follows_caster_onto_enemy()
    test_once_per_turn_dedup()
    test_zone_spares_allies_hits_enemies()
    test_emanation_halves_enemy_speed_spares_allies()
    test_save_for_half_on_tick()
    print("\n✅ All Emanation tests passed!")
