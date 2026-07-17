#!/usr/bin/env python3
"""
Test Aid (Phase 3):
  - Level 2, NO concentration, up to 3 creatures.
  - Each target's HP maximum AND current HP rise by 5, +5 more per slot level above 2.
  - The grant is a Stats field (`aid_hp_bonus`) applied via an "Aided" AgentCondition; the
    teardown (Phase-0.1 chokepoint) gives back exactly what it added.
  - A downed (0 HP) target is revived, because the current-HP gain routes through healAgent.

Aid targets allies, so all agents share one faction here.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1


def _make_aid():
    """Build the Aid spell exactly as spells.json now defines it."""
    sp = rpg.Spell()
    sp.name = "Aid"
    sp.type = rpg.SpellType.Help
    sp.geometry = rpg.SpellGeometry.Multiple
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = 2
    sp.duration = 100
    sp.num_targets = 3
    sp.targets_per_upcast_level = 0
    sp.requires_concentration = False

    cond = rpg.AttackCondition()
    cond.condition_name = "Aided"
    cond.requires_save = False
    cond.condition_duration = 0   # 0 → inherit the spell's duration
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


def _cast_aid(engine, bm, caster, targets, slot_level=2):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level
    action.target_indices = targets
    engine.execute_spell(bm, action)


def _aided_condition_id(engine, target):
    for c in engine.active_agent_conditions:
        if c.agent_idx == target and c.condition_name == "Aided":
            return c.condition_id
    return None


def test_three_targets_gain_5():
    """A level-2 Aid raises hp_max and hp_cur by 5 on all three targets."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    t1 = _place(engine, bm, "Ally1", 6, 5)
    t2 = _place(engine, bm, "Ally2", 7, 5)
    t3 = _place(engine, bm, "Ally3", 4, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_aid()])

    _cast_aid(engine, bm, caster, [t1, t2, t3])

    for idx in (t1, t2, t3):
        s = engine.get_agent_stats(bm, idx)
        assert s.hp_max == 15, f"target {idx} hp_max should be 15, got {s.hp_max}"
        assert s.hp_cur == 15, f"target {idx} hp_cur should be 15, got {s.hp_cur}"
        assert s.aid_hp_bonus == 5, f"target {idx} aid_hp_bonus should be 5, got {s.aid_hp_bonus}"
    print("✅ test_three_targets_gain_5 passed")


def test_upcast_at_level_4_grants_15():
    """Cast with a level-4 slot, the bonus is 5 * (1 + 2) = 15."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_aid()])

    _cast_aid(engine, bm, caster, [ally], slot_level=4)

    s = engine.get_agent_stats(bm, ally)
    assert s.hp_max == 25, f"hp_max should be 25 at slot 4, got {s.hp_max}"
    assert s.hp_cur == 25, f"hp_cur should be 25 at slot 4, got {s.hp_cur}"
    assert s.aid_hp_bonus == 15, f"aid_hp_bonus should be 15 at slot 4, got {s.aid_hp_bonus}"
    print("✅ test_upcast_at_level_4_grants_15 passed")


def test_teardown_restores_maximum():
    """Ending Aid returns hp_max to its original value and clears aid_hp_bonus."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_aid()])

    _cast_aid(engine, bm, caster, [ally])
    assert engine.get_agent_stats(bm, ally).hp_max == 15

    cid = _aided_condition_id(engine, ally)
    assert cid is not None, "the Aided condition should exist"
    engine.remove_agent_condition(bm, cid)   # fires the Phase-0.1 teardown chokepoint

    s = engine.get_agent_stats(bm, ally)
    assert s.hp_max == 10, f"hp_max should return to 10, got {s.hp_max}"
    assert s.hp_cur == 10, f"hp_cur should be clamped to 10, got {s.hp_cur}"
    assert s.aid_hp_bonus == 0, f"aid_hp_bonus should be cleared, got {s.aid_hp_bonus}"
    print("✅ test_teardown_restores_maximum passed")


def test_teardown_keeps_spent_hp():
    """A target that spent HP below the lowered max keeps its current total on teardown."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_aid()])

    _cast_aid(engine, bm, caster, [ally])       # hp 15/15
    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 4                                 # took 11 damage → below the base max of 10
    engine.set_agent_stats(bm, ally, s)

    engine.remove_agent_condition(bm, _aided_condition_id(engine, ally))

    s = engine.get_agent_stats(bm, ally)
    assert s.hp_max == 10, f"hp_max should return to 10, got {s.hp_max}"
    assert s.hp_cur == 4, f"hp_cur should be untouched at 4, got {s.hp_cur}"
    print("✅ test_teardown_keeps_spent_hp passed")


def test_revives_downed_target():
    """A target at 0 HP is brought back up (the current-HP gain routes through healAgent)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _make_caster(engine, bm, caster)
    engine.set_agent_spells(bm, caster, [_make_aid()])

    # Down the ally: 0 HP and unconscious.
    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 0
    engine.set_agent_stats(bm, ally, s)
    c = engine.get_agent_conditions(bm, ally)
    c.unconscious = True
    engine.set_agent_conditions(bm, ally, c)

    _cast_aid(engine, bm, caster, [ally])

    s = engine.get_agent_stats(bm, ally)
    assert s.hp_cur == 5, f"downed ally should be healed to 5, got {s.hp_cur}"
    assert not engine.get_agent_conditions(bm, ally).unconscious, "ally should be revived"
    print("✅ test_revives_downed_target passed")


def run_all():
    test_three_targets_gain_5()
    test_upcast_at_level_4_grants_15()
    test_teardown_restores_maximum()
    test_teardown_keeps_spent_hp()
    test_revives_downed_target()
    print("\n✅ All Aid tests passed")


if __name__ == "__main__":
    run_all()
