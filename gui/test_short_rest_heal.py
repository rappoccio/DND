#!/usr/bin/env python3
"""
Test the short-rest half-HP house rule (CombatEngine.apply_short_rest):

  · a wounded creature regains half its (drained-adjusted) maximum HP,
  · the heal caps at the effective maximum,
  · a downed-but-living creature is revived and rejoins the initiative
    rotation (unconscious/stabilized/death-saves cleared),
  · a true-dead corpse is NOT revived.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _wounded_agent(engine, bm, hp_max, hp_cur, col, row):
    idx = add_agent_to_battle(engine, bm, create_test_agent("Fighter", col, row))
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp_max
    s.hp_cur = hp_cur
    engine.set_agent_stats(bm, idx, s)
    return idx


def test_short_rest_heals_half_max():
    """A wounded creature regains floor(max/2) HP on a short rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _wounded_agent(engine, bm, hp_max=44, hp_cur=8, col=5, row=5)

    engine.apply_short_rest(bm)
    after = engine.get_agent_stats(bm, idx)
    assert after.hp_cur == 8 + 22, f"expected 8+22=30 HP, got {after.hp_cur}"
    print("✅ test_short_rest_heals_half_max passed")


def test_short_rest_heal_caps_at_max():
    """The half-max heal never exceeds the (effective) maximum HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _wounded_agent(engine, bm, hp_max=40, hp_cur=30, col=5, row=5)

    engine.apply_short_rest(bm)
    after = engine.get_agent_stats(bm, idx)
    # 30 + 20 = 50 would overshoot; must clamp to 40.
    assert after.hp_cur == 40, f"expected clamp to 40 HP, got {after.hp_cur}"
    print("✅ test_short_rest_heal_caps_at_max passed")


def test_short_rest_revives_downed_agent():
    """A downed (0 HP, unconscious) but living creature is healed and rejoins
    initiative: unconscious/stabilized/death-save flags cleared and HP > 0."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _wounded_agent(engine, bm, hp_max=30, hp_cur=0, col=5, row=5)

    cond = engine.get_agent_conditions(bm, idx)
    cond.unconscious = True
    cond.stabilized = True
    cond.death_save_failures = 2
    engine.set_agent_conditions(bm, idx, cond)

    engine.apply_short_rest(bm)

    after = engine.get_agent_stats(bm, idx)
    after_cond = engine.get_agent_conditions(bm, idx)
    assert after.hp_cur == 15, f"downed creature should regain 15 HP, got {after.hp_cur}"
    assert not after_cond.unconscious, "revived creature must not be unconscious"
    assert not after_cond.stabilized, "revived creature must not be stabilized"
    assert after_cond.death_save_failures == 0, "death saves must reset on revive"
    assert not after_cond.dead, "a healed downed creature is not dead"
    print("✅ test_short_rest_revives_downed_agent passed")


def test_short_rest_does_not_revive_dead():
    """A true-dead corpse stays dead and gains no HP on a short rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _wounded_agent(engine, bm, hp_max=30, hp_cur=0, col=5, row=5)

    cond = engine.get_agent_conditions(bm, idx)
    cond.dead = True
    engine.set_agent_conditions(bm, idx, cond)

    engine.apply_short_rest(bm)

    after = engine.get_agent_stats(bm, idx)
    after_cond = engine.get_agent_conditions(bm, idx)
    assert after.hp_cur == 0, f"a dead corpse must not be healed, got {after.hp_cur} HP"
    assert after_cond.dead, "a dead corpse must stay dead through a short rest"
    print("✅ test_short_rest_does_not_revive_dead passed")


if __name__ == "__main__":
    test_short_rest_heals_half_max()
    test_short_rest_heal_caps_at_max()
    test_short_rest_revives_downed_agent()
    test_short_rest_does_not_revive_dead()
    print("\n✅ all short-rest heal tests passed")
