#!/usr/bin/env python3
"""
Test Wish (primary use — duplicate a spell of level ≤ 8).

The GUI flow (main.py _on_wish_duplicate) does three engine-level things when the player
picks a spell from the Wish picker:
  1. spend_spell_slot(caster, 9)          — charge Wish's own 9th-level slot.
  2. add_spell_to_agent(caster, dup)      — inject the chosen spell (engine casts by index).
  3. execute a free cast (SpellAction.free_cast=True) at the duplicate's BASE level, so it
     consumes no slot of its own.

These tests exercise those building blocks directly (the pygame layer is not unit-testable):
the new spend_spell_slot binding, and that a free-cast duplicate deals its effect while
spending no additional slot.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)


def _place(engine, bm, name, col, row, faction):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx, slots):
    """Set the caster up as a player spellcaster with the given per-level slot counts
    (a 9-element list, index 0 == 1st level … index 8 == 9th level)."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.is_npc = False
    s.spell_slots_remaining = list(slots)
    s.spell_slots_max = list(slots)
    engine.set_agent_stats(bm, idx, s)


def _make_wish():
    sp = rpg.Spell()
    sp.name = "Wish"
    sp.type = rpg.SpellType.Heal
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.level = 9
    sp.duration = 1
    return sp


def _make_damage_spell(name="Fireball", level=3):
    """A deterministic single-target Automatic Fire spell: 1d1+5 = always 6 damage."""
    sp = rpg.Spell()
    sp.name = name
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 150
    sp.level = level
    sp.duration = 1
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 1
    roll.die_size = 1     # d1 → always 1
    roll.bonus = 5        # +5 → 6 total
    sp.magic_damage_rolls = [roll]
    return sp


def _slots(**kw):
    """Build a 9-element slot list, e.g. _slots(three=2, nine=1)."""
    names = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    return [kw.get(n, 0) for n in names]


def test_spend_spell_slot_basic():
    """spend_spell_slot decrements the named level, clamps at 0, and reports success/failure."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5, faction=1)
    _make_caster(engine, bm, caster, _slots(nine=1))

    assert engine.spend_spell_slot(bm, caster, 9) is True, "should spend the one 9th-level slot"
    assert engine.get_agent_stats(bm, caster).spell_slots_remaining[8] == 0

    # No slot left → returns False and stays clamped at 0.
    assert engine.spend_spell_slot(bm, caster, 9) is False, "no 9th slot left to spend"
    assert engine.get_agent_stats(bm, caster).spell_slots_remaining[8] == 0

    # Out-of-range levels are rejected.
    assert engine.spend_spell_slot(bm, caster, 0) is False
    assert engine.spend_spell_slot(bm, caster, 10) is False
    print("✅ test_spend_spell_slot_basic passed")


def test_spend_spell_slot_npc_noop():
    """NPCs use the N/day system, not slots — spend_spell_slot is a no-op for them."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Lich", 5, 5, faction=2)
    s = engine.get_agent_stats(bm, npc)
    s.is_npc = True
    s.spell_slots_remaining = _slots(nine=1)
    engine.set_agent_stats(bm, npc, s)

    assert engine.spend_spell_slot(bm, npc, 9) is False, "NPC slot-spend must be a no-op"
    assert engine.get_agent_stats(bm, npc).spell_slots_remaining[8] == 1, "NPC slot untouched"
    print("✅ test_spend_spell_slot_npc_noop passed")


def test_wish_duplicates_spell_for_free():
    """The full Wish-duplication sequence: charge the 9th slot, inject a spell, free-cast it.
    The 9th slot drops by one, the duplicate's own (3rd-level) slot is untouched, and the
    duplicated spell deals its damage."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5, faction=1)
    enemy  = _place(engine, bm, "Goblin", 6, 5, faction=2)
    _make_caster(engine, bm, caster, _slots(three=2, nine=1))
    engine.set_agent_spells(bm, caster, [_make_wish()])

    enemy_hp0 = engine.get_agent_stats(bm, enemy).hp_cur

    # 1) Charge Wish's own 9th-level slot.
    assert engine.spend_spell_slot(bm, caster, 9) is True

    # 2) Inject the chosen duplicate (Fireball, level 3) and grab its index.
    engine.add_spell_to_agent(bm, caster, _make_damage_spell("Fireball", 3))
    spells = engine.get_agent_spells(bm, caster)
    dup_idx = len(spells) - 1
    assert spells[dup_idx].name == "Fireball", "duplicate should be the last spell in the list"

    # 3) Free-cast the duplicate at its base level (no slot of its own).
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = dup_idx
    action.slot_level = 3
    action.free_cast = True
    action.target_indices = [enemy]
    engine.execute_spell(bm, action)

    stats = engine.get_agent_stats(bm, caster)
    assert stats.spell_slots_remaining[8] == 0, "the 9th-level (Wish) slot should be spent"
    assert stats.spell_slots_remaining[2] == 2, "the duplicate's 3rd-level slots must be untouched"

    enemy_hp1 = engine.get_agent_stats(bm, enemy).hp_cur
    assert enemy_hp1 == enemy_hp0 - 6, f"duplicated Fireball should deal 6, {enemy_hp0}->{enemy_hp1}"
    print("✅ test_wish_duplicates_spell_for_free passed")


def test_duplicate_not_free_would_spend_own_slot():
    """Control: the SAME cast WITHOUT free_cast spends the duplicate's own 3rd-level slot,
    proving free_cast is what protects it in the Wish flow."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5, faction=1)
    enemy  = _place(engine, bm, "Goblin", 6, 5, faction=2)
    _make_caster(engine, bm, caster, _slots(three=2, nine=1))
    engine.set_agent_spells(bm, caster, [_make_wish()])
    engine.add_spell_to_agent(bm, caster, _make_damage_spell("Fireball", 3))
    dup_idx = len(engine.get_agent_spells(bm, caster)) - 1

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = dup_idx
    action.slot_level = 3
    action.free_cast = False   # NOT the Wish path
    action.target_indices = [enemy]
    engine.execute_spell(bm, action)

    assert engine.get_agent_stats(bm, caster).spell_slots_remaining[2] == 1, \
        "a non-free cast should consume one 3rd-level slot"
    print("✅ test_duplicate_not_free_would_spend_own_slot passed")


def run_all():
    test_spend_spell_slot_basic()
    test_spend_spell_slot_npc_noop()
    test_wish_duplicates_spell_for_free()
    test_duplicate_not_free_would_spend_own_slot()
    print("\n✅ All Wish tests passed")


if __name__ == "__main__":
    run_all()
