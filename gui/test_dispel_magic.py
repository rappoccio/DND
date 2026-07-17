#!/usr/bin/env python3
"""
Test Dispel Magic (SPELLS_TO_WIRE Phase 4):
  - Level 3, one creature/object/effect within range.
  - Any ongoing spell whose cast level <= the slot used ends automatically.
  - For a higher-level effect, the caster rolls d20 + spellcasting ability modifier vs
    DC 10 + the effect's level; on a success it ends.
  - Everything ended routes through the onConditionEnded / removeSpellEffect teardown, so
    buffs come off cleanly (dispelling Haste inflicts its end-of-spell lethargy).
  - If a dispelled effect's original caster is left concentrating on a spell with no remaining
    footprint, that concentration is cleared.

Detected by the data-driven `dispels_magic` flag (the opens_doors precedent), not the name.
Most tests drive the engine's `dispel_magic` directly; the last drives the whole
`execute_spell` dispatch so the spells.json wiring is exercised too.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1
ENEMY = 2


def _place(engine, bm, name, col, row, faction=TEAM):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx, ability=None, score=None):
    """Flag idx as a caster; optionally set its spellcasting ability + that ability's score."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    if ability is not None:
        s.spellcasting_ability = ability
        if score is not None:
            # 5 == CHA in the engine's ability ordering (str,dex,con,int,wis,cha)
            s.cha = score
    engine.set_agent_stats(bm, idx, s)


def _make_bless():
    sp = rpg.Spell()
    sp.name = "Bless"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Multiple
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = 1
    sp.duration = 10
    sp.num_targets = 3
    sp.targets_per_upcast_level = 1
    sp.requires_concentration = True
    cond = rpg.AttackCondition()
    cond.condition_name = "Blessed"
    cond.requires_save = False
    cond.condition_duration = 0
    sp.conditions = [cond]
    return sp


def _make_haste():
    sp = rpg.Spell()
    sp.name = "Haste"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = 3
    sp.duration = 10
    sp.requires_concentration = True
    cond = rpg.AttackCondition()
    cond.condition_name = "Hasted"
    cond.requires_save = False
    cond.condition_duration = 0
    cond.save_repeat_turns = -1
    sp.conditions = [cond]
    return sp


def _make_dispel():
    """Build Dispel Magic exactly as spells.json now defines it."""
    sp = rpg.Spell()
    sp.name = "Dispel Magic"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 120
    sp.level = 3
    sp.duration = 1
    sp.dispels_magic = True
    return sp


def _cast(engine, bm, caster, spell, targets, slot_level):
    engine.set_agent_spells(bm, caster, [spell])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level
    action.target_indices = targets
    engine.execute_spell(bm, action)


def _has_condition(engine, target, name):
    return any(c.agent_idx == target and c.condition_name == name
               for c in engine.active_agent_conditions)


def _add_effect_condition(engine, bm, target, owner, name, cast_level):
    """Hand-build an ongoing spell condition on `target` with an explicit cast level."""
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx = target
    cond.caster_idx = owner
    cond.spell_idx = -1          # cast_level below is authoritative (recorded > 0 wins)
    cond.condition_name = name
    cond.turns_remaining = 100
    cond.save_repeat_turns = -1
    cond.next_save_turn = -1
    cond.cast_level = cast_level
    return engine.add_agent_condition(bm, cond)


# ─────────────────────────────────────────────────────────────────────────────


def test_low_level_auto_dispelled():
    """A level-1 Bless is auto-ended by a slot-3 Dispel, and the caster's concentration clears."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    blesser = _place(engine, bm, "Cleric", 5, 5)
    ally    = _place(engine, bm, "Ally", 6, 5)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, blesser)
    _make_caster(engine, bm, dispeller)

    _cast(engine, bm, blesser, _make_bless(), [ally], slot_level=1)
    assert engine.get_agent_stats(bm, ally).blessed, "ally should be blessed first"
    assert engine.get_agent_conditions(bm, blesser).concentrating

    engine.dispel_magic(bm, dispeller, ally, 3)   # 1 <= 3 → automatic

    assert not engine.get_agent_stats(bm, ally).blessed, "Bless should be dispelled"
    assert not _has_condition(engine, ally, "Blessed")
    assert not engine.get_agent_conditions(bm, blesser).concentrating, \
        "blesser should no longer be concentrating (footprint fully gone)"
    print("✅ test_low_level_auto_dispelled passed")


def test_high_level_requires_check_and_can_fail():
    """A high-level effect is NOT auto-ended below its level, and a hopeless check leaves it."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Sorcerer", 5, 5, faction=ENEMY)
    target    = _place(engine, bm, "Victim", 6, 5, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, dispeller, ability=5, score=10)   # CHA 10 → +0

    # A level-15 effect → DC 25; d20 + 0 can never reach it, so a slot-3 Dispel always fails.
    _add_effect_condition(engine, bm, target, owner, "Frightened", cast_level=15)
    engine.dispel_magic(bm, dispeller, target, 3)

    assert _has_condition(engine, target, "Frightened"), \
        "a hopeless check must leave the effect in place"
    print("✅ test_high_level_requires_check_and_can_fail passed")


def test_high_level_check_can_succeed():
    """The same above-slot effect ends when the caster's modifier makes the check reachable."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Sorcerer", 5, 5, faction=ENEMY)
    target    = _place(engine, bm, "Victim", 6, 5, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, dispeller, ability=5, score=40)   # CHA 40 → +15

    # A level-5 effect → DC 15; d20 + 15 always clears it (proves it rolled: 5 > slot 3).
    _add_effect_condition(engine, bm, target, owner, "Frightened", cast_level=5)
    engine.dispel_magic(bm, dispeller, target, 3)

    assert not _has_condition(engine, target, "Frightened"), \
        "a reachable check should end the effect"
    print("✅ test_high_level_check_can_succeed passed")


def test_upcast_auto_ends_high_level():
    """Upcasting Dispel to slot 5 auto-ends a level-5 effect with no roll needed."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Sorcerer", 5, 5, faction=ENEMY)
    target    = _place(engine, bm, "Victim", 6, 5, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, dispeller, ability=5, score=10)   # +0 — irrelevant when auto

    _add_effect_condition(engine, bm, target, owner, "Frightened", cast_level=5)
    engine.dispel_magic(bm, dispeller, target, 5)   # 5 <= 5 → automatic

    assert not _has_condition(engine, target, "Frightened"), \
        "a slot-5 Dispel should auto-end a level-5 effect"
    print("✅ test_upcast_auto_ends_high_level passed")


def test_dispel_haste_inflicts_lethargy():
    """Dispelling Haste tears the buff down AND applies its end-of-spell lethargy."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    haster    = _place(engine, bm, "Bard", 5, 5)
    target    = _place(engine, bm, "Fighter", 6, 5)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, haster)
    _make_caster(engine, bm, dispeller)

    _cast(engine, bm, haster, _make_haste(), [target], slot_level=3)
    assert engine.get_agent_stats(bm, target).hasted, "target should be hasted first"

    engine.dispel_magic(bm, dispeller, target, 3)   # Haste is level 3 → automatic

    s = engine.get_agent_stats(bm, target)
    assert not s.hasted, "Haste buff should be gone"
    assert s.speed_walk == 0, f"lethargy should zero walk speed, got {s.speed_walk}"
    assert engine.get_agent_conditions(bm, target).incapacitated, \
        "lethargy should leave the target Incapacitated"
    assert _has_condition(engine, target, "HasteLethargy"), \
        "the HasteLethargy condition should be present"
    assert not engine.get_agent_conditions(bm, haster).concentrating, \
        "the haster's concentration should clear"
    print("✅ test_dispel_haste_inflicts_lethargy passed")


def test_partial_dispel_keeps_concentration():
    """Dispelling Bless on ONE of two targets leaves the other blessed and keeps concentration."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    blesser   = _place(engine, bm, "Cleric", 5, 5)
    ally1     = _place(engine, bm, "Ally1", 6, 5)
    ally2     = _place(engine, bm, "Ally2", 4, 5)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, blesser)
    _make_caster(engine, bm, dispeller)

    _cast(engine, bm, blesser, _make_bless(), [ally1, ally2], slot_level=1)
    engine.dispel_magic(bm, dispeller, ally1, 3)

    assert not engine.get_agent_stats(bm, ally1).blessed, "ally1's Bless should be gone"
    assert engine.get_agent_stats(bm, ally2).blessed, "ally2 should still be blessed"
    assert engine.get_agent_conditions(bm, blesser).concentrating, \
        "concentration must persist while a Bless target remains"
    print("✅ test_partial_dispel_keeps_concentration passed")


def test_no_magic_is_a_noop():
    """Dispel on a target with nothing on it changes nothing and does not crash."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    dispeller = _place(engine, bm, "Wizard", 5, 5)
    target    = _place(engine, bm, "Bystander", 6, 5, faction=ENEMY)
    _make_caster(engine, bm, dispeller)

    engine.dispel_magic(bm, dispeller, target, 3)

    assert len(engine.active_agent_conditions) == 0
    print("✅ test_no_magic_is_a_noop passed")


def test_execute_spell_dispatch():
    """The full execute_spell path fires dispelMagic off the dispels_magic flag."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    blesser   = _place(engine, bm, "Cleric", 5, 5)
    ally      = _place(engine, bm, "Ally", 6, 5)
    dispeller = _place(engine, bm, "Wizard", 7, 5)
    _make_caster(engine, bm, blesser)
    _make_caster(engine, bm, dispeller)

    _cast(engine, bm, blesser, _make_bless(), [ally], slot_level=1)
    assert engine.get_agent_stats(bm, ally).blessed

    _cast(engine, bm, dispeller, _make_dispel(), [ally], slot_level=3)

    assert not engine.get_agent_stats(bm, ally).blessed, \
        "casting Dispel Magic should remove Bless via the execute_spell dispatch"
    print("✅ test_execute_spell_dispatch passed")


# ── Cell-aimed Dispel Magic (area effects: Hunger of Hadar, Web, …) ────────────


def _make_hoh(level=3):
    """A Hunger-of-Hadar-shaped zone spell: concentration, Sphere, per-tick damage."""
    sp = rpg.Spell()
    sp.name = "Hunger of Hadar"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.attack_type = rpg.SpellAttack.Save
    sp.range = 150
    sp.radius = 20
    sp.level = level
    sp.duration = 10
    sp.requires_concentration = True
    return sp


def _place_zone(engine, bm, owner, cells, level=3, cast_level=0):
    """Give `owner` a HoH spell (idx 0), lay down both its persistent zone (ActiveSpellEffect)
    and its difficult terrain (ActiveTerrainEffect) over `cells`, and mark owner concentrating.
    Mirrors what execute_spell builds for Hunger of Hadar. Returns (spell_effect_id, terrain_id)."""
    sp = _make_hoh(level)
    engine.set_agent_spells(bm, owner, [sp])
    eff = rpg.ActiveSpellEffect()
    eff.caster_idx = owner
    eff.spell_idx = 0
    eff.spell = sp
    eff.cells = cells
    eff.turns_remaining = 10
    eff.cast_level = cast_level
    eff_id = bm.add_spell_effect(eff)
    ter_id = bm.place_terrain_effect(
        "Hunger of Hadar", cells, rpg.TerrainDifficulty.Halved,
        10, owner, 10, 5, 0, cast_level, True)
    oc = engine.get_agent_conditions(bm, owner)
    oc.concentrating    = True
    oc.concentrating_on = "Hunger of Hadar"
    engine.set_agent_conditions(bm, owner, oc)
    return eff_id, ter_id


def _zone_ids(bm):
    return ([e.effect_id for e in bm.active_spell_effects],
            [t.id for t in bm.active_terrain_effects])


def test_cell_dispel_ends_zone():
    """A slot-3 Dispel aimed at a level-3 Hunger of Hadar cell ends BOTH its zone and terrain,
    and clears the caster's concentration."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller)

    cells = [rpg.Cell(5, 5), rpg.Cell(6, 5), rpg.Cell(5, 6)]
    _place_zone(engine, bm, owner, cells, level=3)
    assert bm.has_active_terrain_effects() and len(bm.active_spell_effects) == 1

    engine.dispel_magic_at_cell(bm, dispeller, 5, 5, 3)   # level 3 <= slot 3 → automatic

    se_ids, te_ids = _zone_ids(bm)
    assert se_ids == [] and te_ids == [], "both the zone and its terrain should be gone"
    assert not engine.get_agent_conditions(bm, owner).concentrating, \
        "owner's concentration should clear once the whole footprint is gone"
    print("✅ test_cell_dispel_ends_zone passed")


def test_cell_dispel_removes_whole_footprint():
    """Clicking ONE cell of a multi-cell zone ends the entire spell, not just that cell."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller)

    cells = [rpg.Cell(5, 5), rpg.Cell(6, 5), rpg.Cell(7, 5), rpg.Cell(8, 5)]
    _place_zone(engine, bm, owner, cells, level=3)

    engine.dispel_magic_at_cell(bm, dispeller, 8, 5, 3)   # click a far edge cell

    se_ids, te_ids = _zone_ids(bm)
    assert se_ids == [] and te_ids == [], "the whole zone footprint should be removed"
    print("✅ test_cell_dispel_removes_whole_footprint passed")


def test_cell_dispel_high_level_can_fail():
    """A cell-aimed dispel below the effect's level rolls a check; a hopeless one leaves it."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller, ability=5, score=10)   # CHA 10 → +0

    cells = [rpg.Cell(5, 5)]
    _place_zone(engine, bm, owner, cells, level=3, cast_level=15)   # counts as level 15 → DC 25
    engine.dispel_magic_at_cell(bm, dispeller, 5, 5, 3)

    se_ids, te_ids = _zone_ids(bm)
    assert se_ids and te_ids, "a hopeless check must leave the zone in place"
    assert engine.get_agent_conditions(bm, owner).concentrating
    print("✅ test_cell_dispel_high_level_can_fail passed")


def test_cell_dispel_empty_cell_noop():
    """Aiming at a cell with no area magic dispels nothing."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller)

    _place_zone(engine, bm, owner, [rpg.Cell(5, 5)], level=3)
    engine.dispel_magic_at_cell(bm, dispeller, 0, 0, 3)   # nothing at (0,0)

    se_ids, te_ids = _zone_ids(bm)
    assert se_ids and te_ids, "an empty cell should leave every effect untouched"
    print("✅ test_cell_dispel_empty_cell_noop passed")


def test_execute_spell_cell_dispatch():
    """The full execute_spell path fires dispelMagicAtCell when a dispels_magic cast has no
    creature target but an aoe aim point (the GUI's cell-cast route)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller)

    _place_zone(engine, bm, owner, [rpg.Cell(5, 5), rpg.Cell(6, 5)], level=3)

    engine.set_agent_spells(bm, dispeller, [_make_dispel()])
    action = rpg.SpellAction()
    action.caster_idx     = dispeller
    action.spell_idx      = 0
    action.slot_level     = 3
    action.target_indices = []       # cell-aimed
    action.aoe_col        = 5
    action.aoe_row        = 5
    engine.execute_spell(bm, action)

    se_ids, te_ids = _zone_ids(bm)
    assert se_ids == [] and te_ids == [], \
        "execute_spell should route an untargeted dispels_magic cast to dispelMagicAtCell"
    print("✅ test_execute_spell_cell_dispatch passed")


# ── Dispel picker: candidate enumeration + selective dispel ───────────────────


def test_candidates_group_hoh_into_one():
    """dispel_candidates_at_cell groups Hunger of Hadar's damage zone + its difficult terrain into
    ONE candidate (one roll ends both), flagged as an enemy effect."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner     = _place(engine, bm, "Warlock", 2, 2, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)          # TEAM
    _make_caster(engine, bm, dispeller)
    # add_agent_to_battle's apply_agent_configs wipes earlier factions — re-assert after placement.
    bm.set_agent_faction(owner, ENEMY)
    bm.set_agent_faction(dispeller, TEAM)

    _place_zone(engine, bm, owner, [rpg.Cell(5, 5), rpg.Cell(6, 5)], level=3)

    cands = engine.dispel_candidates_at_cell(bm, dispeller, 5, 5)
    assert len(cands) == 1, "the zone and its terrain must collapse into one candidate"
    c = cands[0]
    assert c.label == "Hunger of Hadar"
    assert len(c.spell_effect_ids) == 1 and len(c.terrain_ids) == 1
    assert c.level == 3 and c.owner_idx == owner
    assert not c.owner_is_ally, "an enemy's zone should not read as an ally buff"
    print("✅ test_candidates_group_hoh_into_one passed")


def test_multiple_aoes_on_one_cell_are_separate():
    """Two different spells overlapping the same cell are two candidates; dispelling one leaves
    the other (and its owner's concentration) intact."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    owner1    = _place(engine, bm, "WarlockA", 2, 2, faction=ENEMY)
    owner2    = _place(engine, bm, "WarlockB", 3, 3, faction=ENEMY)
    dispeller = _place(engine, bm, "Wizard", 9, 9)
    _make_caster(engine, bm, dispeller)

    _place_zone(engine, bm, owner1, [rpg.Cell(5, 5)], level=3)
    _place_zone(engine, bm, owner2, [rpg.Cell(5, 5)], level=3)

    cands = engine.dispel_candidates_at_cell(bm, dispeller, 5, 5)
    assert len(cands) == 2, "two overlapping spells must be two separate picker entries"

    # Dispel only the first spell.
    c = cands[0]
    engine.dispel_selected(bm, dispeller, c.condition_ids, c.spell_effect_ids, c.terrain_ids, 3)

    remaining = engine.dispel_candidates_at_cell(bm, dispeller, 5, 5)
    assert len(remaining) == 1, "exactly one overlapping spell should remain"
    # The dispelled owner dropped concentration; the other kept it.
    dropped_owner = c.owner_idx
    kept_owner    = owner2 if dropped_owner == owner1 else owner1
    assert not engine.get_agent_conditions(bm, dropped_owner).concentrating
    assert engine.get_agent_conditions(bm, kept_owner).concentrating
    print("✅ test_multiple_aoes_on_one_cell_are_separate passed")


def test_selective_dispel_buff_vs_debuff_on_creature():
    """A creature carrying an ally's buff and an enemy's debuff yields two candidates flagged
    ally/enemy; dispel_selected ends ONLY the chosen one."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    friend    = _place(engine, bm, "Cleric", 2, 2, faction=TEAM)
    foe       = _place(engine, bm, "Hexer", 3, 3, faction=ENEMY)
    target    = _place(engine, bm, "Fighter", 6, 5, faction=TEAM)
    dispeller = _place(engine, bm, "Wizard", 9, 9, faction=TEAM)
    _make_caster(engine, bm, dispeller)
    # add_agent_to_battle's apply_agent_configs wipes earlier factions — re-assert after placement.
    for _i, _f in ((friend, TEAM), (foe, ENEMY), (target, TEAM), (dispeller, TEAM)):
        bm.set_agent_faction(_i, _f)

    _add_effect_condition(engine, bm, target, friend, "Blessed",    cast_level=1)   # ally buff
    _add_effect_condition(engine, bm, target, foe,    "Frightened", cast_level=1)   # enemy debuff

    cands = engine.dispel_candidates_on_agent(bm, dispeller, target)
    assert len(cands) == 2
    buff  = next(c for c in cands if c.label == "Blessed")
    debuff = next(c for c in cands if c.label == "Frightened")
    assert buff.owner_is_ally and not debuff.owner_is_ally, "ally/enemy flags must distinguish them"

    # Dispel only the enemy's debuff; the ally's buff must survive.
    engine.dispel_selected(bm, dispeller, debuff.condition_ids,
                           debuff.spell_effect_ids, debuff.terrain_ids, 3)

    assert not _has_condition(engine, target, "Frightened"), "the chosen debuff should be gone"
    assert _has_condition(engine, target, "Blessed"), "the unchosen buff must remain"
    print("✅ test_selective_dispel_buff_vs_debuff_on_creature passed")


def test_execute_spell_selection_dispatch():
    """execute_spell honors a SpellAction dispel selection: only the chosen effect ends."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe       = _place(engine, bm, "Hexer", 3, 3, faction=ENEMY)
    friend    = _place(engine, bm, "Cleric", 2, 2, faction=TEAM)
    target    = _place(engine, bm, "Fighter", 6, 5, faction=TEAM)
    dispeller = _place(engine, bm, "Wizard", 9, 9, faction=TEAM)
    _make_caster(engine, bm, dispeller)

    _add_effect_condition(engine, bm, target, friend, "Blessed",    cast_level=1)
    _add_effect_condition(engine, bm, target, foe,    "Frightened", cast_level=1)

    debuff = next(c for c in engine.dispel_candidates_on_agent(bm, dispeller, target)
                  if c.label == "Frightened")

    engine.set_agent_spells(bm, dispeller, [_make_dispel()])
    action = rpg.SpellAction()
    action.caster_idx              = dispeller
    action.spell_idx               = 0
    action.slot_level              = 3
    action.target_indices          = [target]        # aimed at the creature…
    action.dispel_condition_ids    = list(debuff.condition_ids)   # …but only the debuff selected
    engine.execute_spell(bm, action)

    assert not _has_condition(engine, target, "Frightened")
    assert _has_condition(engine, target, "Blessed"), \
        "a selection must stop execute_spell from dispelling everything on the target"
    print("✅ test_execute_spell_selection_dispatch passed")


def run_all():
    test_low_level_auto_dispelled()
    test_high_level_requires_check_and_can_fail()
    test_high_level_check_can_succeed()
    test_upcast_auto_ends_high_level()
    test_dispel_haste_inflicts_lethargy()
    test_partial_dispel_keeps_concentration()
    test_no_magic_is_a_noop()
    test_execute_spell_dispatch()
    test_cell_dispel_ends_zone()
    test_cell_dispel_removes_whole_footprint()
    test_cell_dispel_high_level_can_fail()
    test_cell_dispel_empty_cell_noop()
    test_execute_spell_cell_dispatch()
    test_candidates_group_hoh_into_one()
    test_multiple_aoes_on_one_cell_are_separate()
    test_selective_dispel_buff_vs_debuff_on_creature()
    test_execute_spell_selection_dispatch()
    print("\n✅ All Dispel Magic tests passed")


if __name__ == "__main__":
    run_all()
