#!/usr/bin/env python3
"""
Test: spells and magical effects are blocked by walls (Total Cover).

D&D 2024, "Areas of Effect": an area is blocked by Total Cover. Trace a line from the area's
point of origin to a creature; if a wall blocks that line, the creature isn't in the area — the
area never bends around a corner or leaks into the next room. The same rule gates targeting:
"to target something you must have a clear path to it, so it can't be behind Total Cover."

Every one of these used to pass through a wall, because the AoE resolver was pure geometry and
never consulted the map. The engine now prunes each area to the cells its point of origin can
actually reach, and refuses a cast aimed through a wall outright.

Layout for all tests (12x12 grid), a solid wall down column 7:

        col:   1 . . 5 6 [7] 8 . .
   row 1      C                #
   row 5              o A  #   B
                      |    #
                   center   wall (column 7, full height)

  · A at (6,5) is in the open with the blast — always hit.
  · B at (8,5) is 3 cells (15 ft) from the center, well inside a 20-ft Sphere, but the wall
    between them means it is NOT in the area.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

WALL_COL = 7


def _walled_map():
    """A test map with a solid wall running down column 7, top to bottom."""
    bm = setup_battle_map()
    for row in range(bm.grid_rows):
        bm.set_terrain_type(rpg.Cell(WALL_COL, row), rpg.TerrainType.Wall)
    return bm


def _fireball():
    """An aimed 20-ft Sphere (the canonical placed area)."""
    sp = rpg.Spell()
    sp.name = "Fireball"
    sp.level = 0  # cantrip-level avoids spell-slot bookkeeping in the test
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Dexterity
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.radius = 20
    sp.range = 120
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Fire
    dmg.num_dice = 8
    dmg.die_size = 6
    sp.magic_damage_rolls = [dmg]
    return sp


def _spirit_guardians():
    """A 15-ft Emanation centered on the caster, persisting as a zone."""
    sp = rpg.Spell()
    sp.name = "Spirit Guardians"
    sp.level = 0
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Wisdom
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.moves_with_caster = True
    sp.radius = 15
    sp.range = 0
    sp.duration = 10
    sp.effects_on_begin_turn = True
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Radiant
    dmg.num_dice = 3
    dmg.die_size = 8
    sp.magic_damage_rolls = [dmg]
    return sp


def _fire_bolt():
    """A directly-targeted (Single geometry) attack spell."""
    sp = rpg.Spell()
    sp.name = "Fire Bolt"
    sp.level = 0
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.AttackRoll
    sp.geometry = rpg.SpellGeometry.Single
    sp.range = 120
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Fire
    dmg.num_dice = 1
    dmg.die_size = 10
    sp.magic_damage_rolls = [dmg]
    return sp


def _cast(engine, bm, caster, spell, aoe=None, targets=None):
    engine.set_agent_spells(bm, caster, [spell])
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    if aoe is not None:
        action.aoe_col, action.aoe_row = aoe
    if targets is not None:
        action.target_indices = targets
    return engine.execute_spell(bm, action)


def test_aimed_sphere_stops_at_a_wall():
    """Fireball catches the victim in the open, not the one behind the wall."""
    bm = _walled_map()
    engine = setup_combat_engine()

    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 1, 1))
    a = add_agent_to_battle(engine, bm, create_test_agent("Exposed", 6, 5), hp=100)
    b = add_agent_to_battle(engine, bm, create_test_agent("Sheltered", 8, 5), hp=100)

    res = _cast(engine, bm, caster, _fireball(), aoe=(5, 5))
    assert res.valid, "the caster has a clear path to (5,5); the cast should go through"

    hit = {tr.target_idx for tr in res.target_results}
    assert a in hit, "the exposed victim is in the blast and must be hit"
    assert b not in hit, (
        "the sheltered victim is within 20 ft of the center but behind a wall — "
        "Total Cover keeps it out of the area")
    assert engine.get_agent_stats(bm, b).hp_cur == 100, "sheltered victim must take no damage"

    print("✅ test_aimed_sphere_stops_at_a_wall passed")


def test_cannot_aim_an_area_through_a_wall():
    """The point of origin itself needs a clear path — no dropping a Fireball in the next room."""
    bm = _walled_map()
    engine = setup_combat_engine()

    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 1, 1))
    victim = add_agent_to_battle(engine, bm, create_test_agent("Sheltered", 9, 5), hp=100)

    res = _cast(engine, bm, caster, _fireball(), aoe=(9, 5))  # center is behind the wall

    assert not res.valid, "an area can't be centered on a point behind Total Cover"
    assert engine.get_agent_stats(bm, victim).hp_cur == 100, "nobody takes damage from a refused cast"

    print("✅ test_cannot_aim_an_area_through_a_wall passed")


def test_emanation_does_not_leak_through_a_wall():
    """Spirit Guardians' zone stops at the wall, both in its targets and in its footprint."""
    bm = _walled_map()
    engine = setup_combat_engine()

    # The caster IS the point of origin for an Emanation.
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("Exposed", 6, 5), hp=100)
    b = add_agent_to_battle(engine, bm, create_test_agent("Sheltered", 8, 5), hp=100)

    res = _cast(engine, bm, caster, _spirit_guardians(), aoe=(5, 5))
    assert res.valid

    hit = {tr.target_idx for tr in res.target_results}
    assert a in hit, "the adjacent victim is inside the emanation"
    assert b not in hit, "the victim behind the wall is 15 ft away but under Total Cover"

    # The persistent zone's footprint is pruned too, so every downstream membership test
    # (start of turn, walking into the zone, the GUI overlay) inherits the fix.
    effects = [e for e in bm.active_spell_effects if e.spell.name == "Spirit Guardians"]
    assert len(effects) == 1, "the emanation should have left exactly one persistent zone"
    cells = {(c.col, c.row) for c in effects[0].cells}
    assert (6, 5) in cells, "the near side of the zone is intact"
    assert (8, 5) not in cells, "the zone must not extend past the wall"

    print("✅ test_emanation_does_not_leak_through_a_wall passed")


def test_cannot_target_a_creature_behind_a_wall():
    """A directly-targeted spell needs a clear path to its target."""
    bm = _walled_map()
    engine = setup_combat_engine()

    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 1, 1))
    exposed = add_agent_to_battle(engine, bm, create_test_agent("Exposed", 6, 5), hp=100)
    sheltered = add_agent_to_battle(engine, bm, create_test_agent("Sheltered", 8, 5), hp=100)

    ok = _cast(engine, bm, caster, _fire_bolt(), targets=[exposed])
    assert ok.valid, "a target in the open is a legal target"

    blocked = _cast(engine, bm, caster, _fire_bolt(), targets=[sheltered])
    assert not blocked.valid, "a target behind Total Cover can't be targeted at all"
    assert engine.get_agent_stats(bm, sheltered).hp_cur == 100

    print("✅ test_cannot_target_a_creature_behind_a_wall passed")


def test_open_map_is_unaffected():
    """Sanity: with no wall in the way, nothing changes — both victims are caught."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 1, 1))
    a = add_agent_to_battle(engine, bm, create_test_agent("V1", 6, 5), hp=100)
    b = add_agent_to_battle(engine, bm, create_test_agent("V2", 8, 5), hp=100)

    res = _cast(engine, bm, caster, _fireball(), aoe=(5, 5))
    hit = {tr.target_idx for tr in res.target_results}
    assert a in hit and b in hit, "with no wall, both victims are inside the 20-ft Sphere"

    print("✅ test_open_map_is_unaffected passed")


if __name__ == "__main__":
    test_aimed_sphere_stops_at_a_wall()
    test_cannot_aim_an_area_through_a_wall()
    test_emanation_does_not_leak_through_a_wall()
    test_cannot_target_a_creature_behind_a_wall()
    test_open_map_is_unaffected()
    print("\nAll Total Cover tests passed! 🎉")
