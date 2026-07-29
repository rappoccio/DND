#!/usr/bin/env python3
"""
Tests for SPELL_IMPLEMENTATION_PLAN.md **Tier 2** — control / terrain / ward spells.

Every spell is loaded straight from `gui/spells.json` via the real `helpers._dict_to_spell`
path, so these tests cover BOTH the authored JSON payloads and the engine wiring (the
save-gated condition loop in applySpellEffect, the terrain-effect / movement-ward chokepoints,
and the Forcecage/Wall-of-Stone name-keyed blocks in resolveSpell).

Saves are made deterministic the same way as the Tier 1 suite: a DC-24 caster (8 + prof 6 +
CHA +10) vs an ability-1 victim always FAILS its save; a DC-8 caster vs an ability-30 target
always SAVES. Each save-gated spell is checked both ways so a condition can never leak onto a
successful save (the `save_ability` gotcha the Tier 1 work flagged).

Covered condition/damage spells: Eyebite, Irresistible Dance, Reverse Gravity, Symbol,
Flesh to Stone, Maze, Imprisonment, Resilient Sphere, Forcecage.
Covered ward spell: Antilife Shell (ward_all_living — blocks living movers, Undead pass).
Covered terrain spell: Wall of Stone (sets_wall solid-Wall terrain effect).
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")


def _load_spell(name):
    """Build an rpg.Spell straight from spells.json via the real loader."""
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry)
    raise AssertionError(f"{name} not found in spells.json")


def _place(engine, bm, name, col, row, faction=1, **flags):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = 60
    s.speed_fly = 60
    for k, v in flags.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)
    return idx


def _strong_caster(engine, bm, idx):
    """Spell save DC 24 (8 + prof 6 + CHA +10) — no ability-1 victim can beat it."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5   # CHA
    s.cha = 30
    s.prof_bonus = 6
    engine.set_agent_stats(bm, idx, s)


def _weak_caster(engine, bm, idx):
    """Spell save DC 8 — an ability-30 target always saves."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5   # CHA
    s.cha = 10
    s.prof_bonus = 0
    engine.set_agent_stats(bm, idx, s)


def _set_ability(engine, bm, idx, **kw):
    s = engine.get_agent_stats(bm, idx)
    for k, v in kw.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)


def _cast(engine, bm, caster, sp, targets, slot_level=None, action_mut=None):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level if slot_level is not None else sp.level
    action.target_indices = targets if isinstance(targets, list) else [targets]
    if action_mut is not None:
        action_mut(action)
    return engine.execute_spell(bm, action)


def _cast_aoe(engine, bm, caster, sp, center_idx, slot_level=None):
    """Cast an AoE (Sphere/…) aimed at center_idx's cell. Sphere spells ignore target_indices —
    targets are resolved from the aim point (resolveAoeTargets) — so this sets aoe_col/aoe_row."""
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level if slot_level is not None else sp.level
    origin = bm.placed_agents[center_idx].origin
    action.aoe_col, action.aoe_row = origin.col, origin.row
    return engine.execute_spell(bm, action)


def _hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def _find_condition_id(engine, bm, agent_idx, name):
    for c in engine.active_agent_conditions:
        if c.agent_idx == agent_idx and c.condition_name == name:
            return c.condition_id
    return -1


# A caster + a foe that always FAILS the given save ability, and the cast result.
def _cast_on_failing_foe(spell_name, save_score_kw, faction=2):
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=faction)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, **save_score_kw)   # e.g. wis=1
    res = _cast(engine, bm, caster, _load_spell(spell_name), [foe])
    return bm, engine, foe, res


def _cast_on_saving_foe(spell_name, save_score_kw, faction=2):
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=faction)
    _weak_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, **save_score_kw)   # e.g. wis=30
    res = _cast(engine, bm, caster, _load_spell(spell_name), [foe])
    return bm, engine, foe, res


# ─────────────────────────────────────────────────────────────────────────────
#  Eyebite — WIS save → Frightened
# ─────────────────────────────────────────────────────────────────────────────
def test_eyebite_frightens_on_failed_wis_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Eyebite", dict(wis=1))
    assert engine.get_agent_conditions(bm, foe).frightened, "failed WIS save should Frighten"
    print("✅ test_eyebite_frightens_on_failed_wis_save passed")


def test_eyebite_saved_not_frightened():
    bm, engine, foe, _ = _cast_on_saving_foe("Eyebite", dict(wis=30))
    assert not engine.get_agent_conditions(bm, foe).frightened, "a WIS save must not Frighten"
    print("✅ test_eyebite_saved_not_frightened passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Irresistible Dance — WIS save → Incapacitated
# ─────────────────────────────────────────────────────────────────────────────
def test_irresistible_dance_incapacitates_on_failed_wis_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Irresistible Dance", dict(wis=1))
    assert engine.get_agent_conditions(bm, foe).incapacitated, "failed WIS save should Incapacitate"
    print("✅ test_irresistible_dance_incapacitates_on_failed_wis_save passed")


def test_irresistible_dance_saved_not_incapacitated():
    bm, engine, foe, _ = _cast_on_saving_foe("Irresistible Dance", dict(wis=30))
    assert not engine.get_agent_conditions(bm, foe).incapacitated, "a WIS save must not Incapacitate"
    print("✅ test_irresistible_dance_saved_not_incapacitated passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Reverse Gravity — Sphere, DEX save → 6d6 Bludgeoning + Prone (half on save, no Prone)
#  (Sphere geometry ignores target_indices — the AoE is resolved from the aim point.)
# ─────────────────────────────────────────────────────────────────────────────
def test_reverse_gravity_prone_and_damage_on_failed_dex_save():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 8, 8, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, caster, hp_cur=300, hp_max=300)
    _set_ability(engine, bm, foe, dex=1, hp_cur=300, hp_max=300)
    before = _hp(engine, bm, foe)
    _cast_aoe(engine, bm, caster, _load_spell("Reverse Gravity"), foe)
    assert engine.get_agent_conditions(bm, foe).prone, "failed DEX save should knock Prone"
    assert _hp(engine, bm, foe) < before, "failed DEX save takes bludgeoning damage"
    print("✅ test_reverse_gravity_prone_and_damage_on_failed_dex_save passed")


def test_reverse_gravity_saved_not_prone():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 8, 8, faction=2)
    _weak_caster(engine, bm, caster)
    _set_ability(engine, bm, caster, hp_cur=300, hp_max=300)
    _set_ability(engine, bm, foe, dex=30, hp_cur=300, hp_max=300)
    _cast_aoe(engine, bm, caster, _load_spell("Reverse Gravity"), foe)
    assert not engine.get_agent_conditions(bm, foe).prone, "a DEX save must not knock Prone"
    print("✅ test_reverse_gravity_saved_not_prone passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Symbol (Death rune) — Sphere, CON save → 10d10 Necrotic (half on save)
# ─────────────────────────────────────────────────────────────────────────────
def test_symbol_damages_on_failed_con_save():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 6, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, caster, hp_cur=300, hp_max=300)
    _set_ability(engine, bm, foe, con=1, hp_cur=300, hp_max=300)
    before = _hp(engine, bm, foe)
    _cast_aoe(engine, bm, caster, _load_spell("Symbol"), foe)
    assert _hp(engine, bm, foe) < before, "failed CON save takes necrotic damage"
    print("✅ test_symbol_damages_on_failed_con_save passed")


def test_symbol_save_for_half():
    # A DC-8 caster vs a CON-30 target always saves: still half damage on a success (save-for-half),
    # and the saved total must be at most half of 10d10 (≤50), proving the halving happened.
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 6, faction=2)
    _weak_caster(engine, bm, caster)
    _set_ability(engine, bm, caster, hp_cur=300, hp_max=300)
    _set_ability(engine, bm, foe, con=30, hp_cur=300, hp_max=300)
    before = _hp(engine, bm, foe)
    _cast_aoe(engine, bm, caster, _load_spell("Symbol"), foe)
    drop = before - _hp(engine, bm, foe)
    assert 0 <= drop <= 50, f"a successful CON save takes at most half of 10d10 (≤50), got {drop}"
    print("✅ test_symbol_save_for_half passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Flesh to Stone — CON save → Restrained
# ─────────────────────────────────────────────────────────────────────────────
def test_flesh_to_stone_restrains_on_failed_con_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Flesh to Stone", dict(con=1))
    assert engine.get_agent_conditions(bm, foe).restrained, "failed CON save should Restrain"
    print("✅ test_flesh_to_stone_restrains_on_failed_con_save passed")


def test_flesh_to_stone_saved_not_restrained():
    bm, engine, foe, _ = _cast_on_saving_foe("Flesh to Stone", dict(con=30))
    assert not engine.get_agent_conditions(bm, foe).restrained, "a CON save must not Restrain"
    print("✅ test_flesh_to_stone_saved_not_restrained passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Maze — INT save → Incapacitated (banished to a demiplane)
# ─────────────────────────────────────────────────────────────────────────────
def test_maze_incapacitates_on_failed_int_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Maze", dict(intel=1))
    assert engine.get_agent_conditions(bm, foe).incapacitated, "failed INT save should Incapacitate"
    print("✅ test_maze_incapacitates_on_failed_int_save passed")


def test_maze_saved_not_incapacitated():
    bm, engine, foe, _ = _cast_on_saving_foe("Maze", dict(intel=30))
    assert not engine.get_agent_conditions(bm, foe).incapacitated, "an INT save must not Incapacitate"
    print("✅ test_maze_saved_not_incapacitated passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Imprisonment — WIS save → Incapacitated (no escape re-save)
# ─────────────────────────────────────────────────────────────────────────────
def test_imprisonment_incapacitates_on_failed_wis_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Imprisonment", dict(wis=1))
    assert engine.get_agent_conditions(bm, foe).incapacitated, "failed WIS save should Incapacitate"
    print("✅ test_imprisonment_incapacitates_on_failed_wis_save passed")


def test_imprisonment_saved_not_incapacitated():
    bm, engine, foe, _ = _cast_on_saving_foe("Imprisonment", dict(wis=30))
    assert not engine.get_agent_conditions(bm, foe).incapacitated, "a WIS save must not Incapacitate"
    print("✅ test_imprisonment_saved_not_incapacitated passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Resilient Sphere — DEX save → Incapacitated (enclosed)
# ─────────────────────────────────────────────────────────────────────────────
def test_resilient_sphere_incapacitates_on_failed_dex_save():
    bm, engine, foe, _ = _cast_on_failing_foe("Resilient Sphere", dict(dex=1))
    assert engine.get_agent_conditions(bm, foe).incapacitated, "failed DEX save should enclose (Incapacitated)"
    print("✅ test_resilient_sphere_incapacitates_on_failed_dex_save passed")


def test_resilient_sphere_saved_not_incapacitated():
    bm, engine, foe, _ = _cast_on_saving_foe("Resilient Sphere", dict(dex=30))
    assert not engine.get_agent_conditions(bm, foe).incapacitated, "a DEX save must not enclose"
    print("✅ test_resilient_sphere_saved_not_incapacitated passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Forcecage — Automatic (no save) → Forcecaged (trapped in place); Box seals two-way
# ─────────────────────────────────────────────────────────────────────────────
def test_forcecage_traps_target_in_place():
    """Forcecage has no save: the target is Forcecaged and can't move out of its square."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, dex=30)   # even a great save can't help: Forcecage is Automatic
    _cast(engine, bm, caster, _load_spell("Forcecage"), [foe])

    c = engine.get_agent_conditions(bm, foe)
    assert c.forcecaged, "Forcecage traps the target regardless of save"
    assert c.forcecage_dc > 0, "the cage records a teleport-out CHA DC"

    # A caged creature can't walk out of its cell.
    engine.begin_turn(bm, foe)
    bm.placed_agents[foe].init_movement(60)
    assert not engine.move_agent(bm, foe, rpg.Cell(8, 5), rpg.MovementType.Walk), \
        "a Forcecaged creature can't leave its square"
    print("✅ test_forcecage_traps_target_in_place passed")


def test_forcecage_box_seals_two_way():
    """The Box form (action.forcecage_sealed) additionally seals the cage two-way."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _cast(engine, bm, caster, _load_spell("Forcecage"), [foe],
          action_mut=lambda a: setattr(a, "forcecage_sealed", True))
    c = engine.get_agent_conditions(bm, foe)
    assert c.forcecaged and c.forcecage_sealed, "the Box form seals the cage two-way"
    print("✅ test_forcecage_box_seals_two_way passed")


def _reach(bm, idx, speed=60, mt=rpg.MovementType.Walk):
    origin = bm.placed_agents[idx].origin
    return {(c.col, c.row) for c in bm.reachable_cells(origin, 1, speed, mt, idx)}


def _try_walk(engine, bm, idx, col, row, speed=60):
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(speed)
    return engine.move_agent(bm, idx, rpg.Cell(col, row), rpg.MovementType.Walk)


# ─────────────────────────────────────────────────────────────────────────────
#  Antilife Shell — a caster-anchored ward no living creature can cross (Undead pass)
# ─────────────────────────────────────────────────────────────────────────────
# A solid 3×3 ward footprint centered on (5,5): cols 4-6 × rows 4-6.
ANTILIFE_CELLS = [rpg.Cell(c, r) for c in (4, 5, 6) for r in (4, 5, 6)]


def test_antilife_shell_blocks_living_not_undead():
    """A ward_all_living zone blocks a living creature from entering; an Undead passes freely."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    bm.place_terrain_effect("Antilife Shell", ANTILIFE_CELLS, rpg.TerrainDifficulty.Normal, 100, -1,
                            ward_all_living=True)
    assert [t for t in bm.active_terrain_effects if t.ward_all_living], "effect carries ward_all_living"

    living = _place(engine, bm, "Fighter", 5, 1)                 # typeless (alive)
    undead = _place(engine, bm, "Wight", 5, 9, is_undead=True)   # Undead — exempt

    lreach = _reach(bm, living)
    for c in ANTILIFE_CELLS:
        assert (c.col, c.row) not in lreach, "a living creature can't enter the antilife shell"
    assert not _try_walk(engine, bm, living, 5, 5), "a living creature can't commit a move inside"

    assert (5, 5) in _reach(bm, undead), "an Undead is not warded — it can enter the shell"
    assert _try_walk(engine, bm, undead, 5, 5), "an Undead walks into the shell"
    print("✅ test_antilife_shell_blocks_living_not_undead passed")


def test_cast_antilife_shell_places_ward():
    """Casting Antilife Shell lays a caster-anchored ward_all_living terrain effect."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Druid", 5, 5)
    _strong_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_load_spell("Antilife Shell")])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 5
    action.aoe_col, action.aoe_row = 5, 5
    engine.execute_spell(bm, action)

    wards = [t for t in bm.active_terrain_effects if t.ward_all_living]
    assert wards, "casting Antilife Shell should create a ward_all_living terrain effect"
    assert wards[0].anchor_agent_idx == caster, "the shell is anchored to the caster (follows them)"
    print("✅ test_cast_antilife_shell_places_ward passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Wall of Stone — an oriented wall whose cells become solid Wall terrain
# ─────────────────────────────────────────────────────────────────────────────
# A full-height wall down column 5 partitions the map: with no gap top or bottom, a walker on the
# west side (col<5) genuinely can't reach the east side (col>5) at any speed. (A short wall would
# just be walked around, which is correct behavior but doesn't test the wall's impassability.)
def _wall_column(bm, col=5):
    return [rpg.Cell(col, r) for r in range(bm.grid_rows)]


def test_wall_of_stone_creates_wall_terrain_round_trips():
    sp = _load_spell("Wall of Stone")
    assert getattr(sp, "creates_wall_terrain", False), "Wall of Stone should load creates_wall_terrain=True"
    again = helpers._dict_to_spell(helpers._spell_to_dict(sp))
    assert again.creates_wall_terrain, "creates_wall_terrain should survive a serializer round-trip"
    print("✅ test_wall_of_stone_creates_wall_terrain_round_trips passed")


def test_wall_of_stone_sets_wall_makes_impassable_los_blocking_terrain():
    """A sets_wall terrain effect turns its cells into solid Wall: impassable + LOS-blocking."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    wall = _wall_column(bm, 5)
    for c in wall:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Standard

    eff_id = bm.place_terrain_effect("Wall of Stone", wall, rpg.TerrainDifficulty.Normal,
                                     100, -1, sets_wall=True)
    assert eff_id >= 0
    for c in wall:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Wall, "wall cells must become Wall terrain"
    assert [t for t in bm.active_terrain_effects if t.sets_wall], "effect carries sets_wall=True"

    # The full-height wall partitions the map: a west-side walker can reach neither the wall cells
    # nor anything east of it, at full speed.
    walker = _place(engine, bm, "Fighter", 3, 5)
    reach = _reach(bm, walker)
    for c in wall:
        assert (c.col, c.row) not in reach, f"wall cell {(c.col, c.row)} must be impassable"
    assert (7, 5) not in reach, "a full-height wall blocks the walker from the east side entirely"

    # A flier is likewise blocked — a solid stone wall stops fly movement (Wall passes only Burrow).
    flier = _place(engine, bm, "Imp", 3, 5)
    freach = _reach(bm, flier, mt=rpg.MovementType.Fly)
    for c in wall:
        assert (c.col, c.row) not in freach, "the wall blocks fly movement too"
    assert (7, 5) not in freach, "a full-height wall blocks the flier from the east side entirely"

    assert not bm.has_line_of_sight(rpg.Cell(3, 5), 1, rpg.Cell(7, 5), 1), \
        "the stone wall blocks line of sight"
    print("✅ test_wall_of_stone_sets_wall_makes_impassable_los_blocking_terrain passed")


def test_wall_of_stone_removal_restores_terrain():
    """Removing a sets_wall effect restores each cell's original terrain."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    wall = _wall_column(bm, 5)
    eff_id = bm.place_terrain_effect("Wall of Stone", wall, rpg.TerrainDifficulty.Normal,
                                     100, -1, sets_wall=True)
    for c in wall:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Wall
    bm.remove_terrain_effect(eff_id)
    for c in wall:
        assert bm.get_terrain_type(c) == rpg.TerrainType.Standard, "removal must restore original terrain"
    assert bm.has_line_of_sight(rpg.Cell(3, 5), 1, rpg.Cell(7, 5), 1), "LOS clear again after removal"
    print("✅ test_wall_of_stone_removal_restores_terrain passed")


def test_cast_wall_of_stone_places_and_blocks():
    """Casting Wall of Stone lays a sets_wall terrain effect along the aimed segment and blocks it.
    The wall is aimed to span the map's full height so it fully partitions west from east."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 1, 5)
    walker = _place(engine, bm, "Fighter", 3, 5)
    _strong_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_load_spell("Wall of Stone")])

    last_row = bm.grid_rows - 1
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 5
    action.aoe_col, action.aoe_row = 5, 0             # anchor (top of column 5)
    action.aoe_col2, action.aoe_row2 = 5, last_row    # endpoint (bottom) — a full-height wall
    engine.execute_spell(bm, action)

    assert [t for t in bm.active_terrain_effects if t.sets_wall], "cast should create a sets_wall effect"
    assert bm.get_terrain_type(rpg.Cell(5, 5)) == rpg.TerrainType.Wall, \
        "the aimed wall segment must be solid Wall terrain"
    assert (7, 5) not in _reach(bm, walker), "the summoned wall blocks the walker's path east"
    print("✅ test_cast_wall_of_stone_places_and_blocks passed")


if __name__ == "__main__":
    test_eyebite_frightens_on_failed_wis_save()
    test_eyebite_saved_not_frightened()
    test_irresistible_dance_incapacitates_on_failed_wis_save()
    test_irresistible_dance_saved_not_incapacitated()
    test_reverse_gravity_prone_and_damage_on_failed_dex_save()
    test_reverse_gravity_saved_not_prone()
    test_symbol_damages_on_failed_con_save()
    test_symbol_save_for_half()
    test_flesh_to_stone_restrains_on_failed_con_save()
    test_flesh_to_stone_saved_not_restrained()
    test_maze_incapacitates_on_failed_int_save()
    test_maze_saved_not_incapacitated()
    test_imprisonment_incapacitates_on_failed_wis_save()
    test_imprisonment_saved_not_incapacitated()
    test_resilient_sphere_incapacitates_on_failed_dex_save()
    test_resilient_sphere_saved_not_incapacitated()
    test_forcecage_traps_target_in_place()
    test_forcecage_box_seals_two_way()
    test_antilife_shell_blocks_living_not_undead()
    test_cast_antilife_shell_places_ward()
    test_wall_of_stone_creates_wall_terrain_round_trips()
    test_wall_of_stone_sets_wall_makes_impassable_los_blocking_terrain()
    test_wall_of_stone_removal_restores_terrain()
    test_cast_wall_of_stone_places_and_blocks()
    print("\n✅ All Tier 2 spell tests passed")
