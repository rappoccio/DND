#!/usr/bin/env python3
"""
Test Haste (SPELLS_TO_WIRE Phase 2):
  - Level 3, Concentration, one willing creature.
  - While it lasts: +2 AC, Advantage on DEX saves, doubled walk Speed, and one extra limited
    action each turn (refilled at the start of every one of the target's turns).
  - The buff is a "Hasted" AgentCondition driving Stats flags; it is torn down through the
    Phase-0.1 chokepoint on EVERY end path (concentration drop, duration expiry, Dispel Magic).
  - When it ends the target is Incapacitated with Speed 0 until the end of its next turn (a
    "HasteLethargy" condition), after which Speed is restored exactly.

Haste targets a willing creature, so all agents share one faction here.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1
BASE_SPEED = 30


def _make_haste():
    """Build the Haste spell exactly as spells.json now defines it."""
    sp = rpg.Spell()
    sp.name = "Haste"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = 3
    sp.duration = 10
    sp.requires_concentration = True
    sp.requires_los = True

    cond = rpg.AttackCondition()
    cond.condition_name = "Hasted"
    cond.requires_save = False
    cond.condition_duration = 0   # 0 → inherit the spell's duration
    cond.save_repeat_turns = -1   # a buff, not a debuff: begin_turn must not "save" it away
    sp.conditions = [cond]
    return sp


def _place(engine, bm, name, col, row, faction=TEAM):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, idx, s)


def _cast_haste(engine, bm, caster, target, slot_level=3):
    engine.set_agent_spells(bm, caster, [_make_haste()])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level
    action.target_indices = [target]
    engine.execute_spell(bm, action)


def test_buffs_applied():
    """Casting Haste sets +2 AC, doubled Speed, DEX-save Advantage, and the extra action."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    ally = _place(engine, bm, "Fighter", 6, 5)
    _make_caster(engine, bm, caster)

    before = engine.get_agent_stats(bm, ally)
    assert before.speed_walk == BASE_SPEED and before.ac_temporary_modifications == 0

    _cast_haste(engine, bm, caster, ally)

    s = engine.get_agent_stats(bm, ally)
    assert s.hasted, "target should be hasted"
    assert s.ac_temporary_modifications == 2, f"expected +2 AC, got {s.ac_temporary_modifications}"
    assert s.speed_walk == 2 * BASE_SPEED, f"expected doubled speed, got {s.speed_walk}"
    assert s.haste_speed_bonus == BASE_SPEED, f"expected speed bonus {BASE_SPEED}, got {s.haste_speed_bonus}"
    assert s.haste_action_available, "the extra action should be available after casting"
    assert engine.save_advantage_for(bm, ally, rpg.SaveAbility.Dexterity), "DEX saves should be at Advantage"
    assert engine.get_agent_conditions(bm, caster).concentrating, "caster should be concentrating"
    print("✅ test_buffs_applied passed")


def test_extra_action_refreshes_each_turn():
    """The extra action is spent once, then refilled at the start of the target's next turn."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    ally = _place(engine, bm, "Fighter", 6, 5)
    _make_caster(engine, bm, caster)
    _cast_haste(engine, bm, caster, ally)

    # Spend it (what the GUI button does).
    s = engine.get_agent_stats(bm, ally)
    s.haste_action_available = False
    engine.set_agent_stats(bm, ally, s)
    assert not engine.get_agent_stats(bm, ally).haste_action_available

    # A fresh turn refills it.
    engine.begin_turn(bm, ally)
    assert engine.get_agent_stats(bm, ally).haste_action_available, "begin_turn should refill the Haste action"
    print("✅ test_extra_action_refreshes_each_turn passed")


def test_lethargy_on_concentration_drop():
    """Ending Haste undoes every buff exactly and leaves the target Incapacitated with Speed 0."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    ally = _place(engine, bm, "Fighter", 6, 5)
    _make_caster(engine, bm, caster)
    _cast_haste(engine, bm, caster, ally)

    engine.drop_concentration(bm, caster)

    s = engine.get_agent_stats(bm, ally)
    assert not s.hasted, "Haste flag should be cleared"
    assert s.ac_temporary_modifications == 0, f"the +2 AC should be gone, got {s.ac_temporary_modifications}"
    assert not engine.save_advantage_for(bm, ally, rpg.SaveAbility.Dexterity), "DEX Advantage should be gone"
    assert not s.haste_action_available, "the extra action should be revoked"
    # Lethargy: Incapacitated + Speed 0 (the base speed was first restored, then zeroed).
    assert engine.get_agent_conditions(bm, ally).incapacitated, "target should be Incapacitated (lethargy)"
    assert s.speed_walk == 0, f"lethargy should zero Speed, got {s.speed_walk}"

    # The lethargy is self-inflicted (caster_idx == target), so it ticks on the target's own turn.
    engine.tick_agent_conditions_for_caster(bm, ally)

    s = engine.get_agent_stats(bm, ally)
    assert s.speed_walk == BASE_SPEED, f"Speed should be restored to {BASE_SPEED}, got {s.speed_walk}"
    assert not engine.get_agent_conditions(bm, ally).incapacitated, "Incapacitated should be cleared after lethargy"
    print("✅ test_lethargy_on_concentration_drop passed")


def test_apply_is_idempotent():
    """Applying the "Hasted" condition twice must not double the AC or Speed (the !hasted guard)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    ally = _place(engine, bm, "Fighter", 6, 5)

    def _apply():
        c = rpg.ActiveAgentCondition()
        c.agent_idx = ally
        c.caster_idx = ally
        c.condition_name = "Hasted"
        c.turns_remaining = 10
        c.save_repeat_turns = -1
        engine.add_agent_condition(bm, c)

    _apply()
    _apply()  # second application of the same buff

    s = engine.get_agent_stats(bm, ally)
    assert s.hasted
    assert s.ac_temporary_modifications == 2, f"AC must not stack, got {s.ac_temporary_modifications}"
    assert s.speed_walk == 2 * BASE_SPEED, f"Speed must not stack, got {s.speed_walk}"
    assert s.haste_speed_bonus == BASE_SPEED, f"speed bonus must not stack, got {s.haste_speed_bonus}"
    print("✅ test_apply_is_idempotent passed")


def run_all():
    test_buffs_applied()
    test_extra_action_refreshes_each_turn()
    test_lethargy_on_concentration_drop()
    test_apply_is_idempotent()
    print("\n✅ All Haste tests passed")


if __name__ == "__main__":
    run_all()
