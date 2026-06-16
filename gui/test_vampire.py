#!/usr/bin/env python3
"""
Tests for vampire-support engine features:
  • available_hit_points: a max-HP reduction that mirrors temp HP (effective_max_hp,
    cleared on a long rest, healing capped to it).
  • the "reduceHPMax" on-hit weapon rider (a Vampire's Bite life-drain): on a hit it
    lowers the target's HP maximum by the Necrotic damage dealt and heals the attacker
    by the same amount.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _bite_weapon():
    """A Vampire's Bite: 1d4 Piercing + 3d6 Necrotic, with the reduceHPMax drain rider."""
    w = rpg.Weapon()
    w.name = "Bite"
    w.reach_ft = 5
    w.proficient = True

    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 4
    pr.bonus = 0
    w.physical_damage_types = [pr]

    mr = rpg.MagicDamageRoll()
    mr.type = rpg.MagicDamage.Necrotic
    mr.num_dice = 3
    mr.die_size = 6
    mr.bonus = 0
    w.magic_damage_types = [mr]

    c = rpg.AttackCondition()
    c.condition_name = "reduceHPMax"
    w.conditions = [c]
    return w


def test_available_hit_points_basics():
    """effective_max_hp = hp_max - available_hit_points (floored at 0)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Drained", 5, 5), hp=40)

    s = engine.get_agent_stats(bm, idx)
    assert s.available_hit_points == 0, "fresh agent has no max-HP reduction"
    assert s.effective_max_hp == 40

    s.available_hit_points = 15
    engine.set_agent_stats(bm, idx, s)
    s = engine.get_agent_stats(bm, idx)
    assert s.effective_max_hp == 25, f"expected 25, got {s.effective_max_hp}"

    s.available_hit_points = 999  # over-drain floors at 0
    engine.set_agent_stats(bm, idx, s)
    assert engine.get_agent_stats(bm, idx).effective_max_hp == 0
    print("✅ available_hit_points / effective_max_hp math")


def test_long_rest_clears_drain():
    """A long rest clears available_hit_points and restores full HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bitten", 5, 5), hp=50)

    s = engine.get_agent_stats(bm, idx)
    s.available_hit_points = 20
    s.hp_cur = 12
    engine.set_agent_stats(bm, idx, s)

    engine.apply_long_rest(bm)

    s = engine.get_agent_stats(bm, idx)
    assert s.available_hit_points == 0, "long rest clears the max-HP reduction"
    assert s.hp_cur == s.hp_max == 50, f"long rest restores full HP, got {s.hp_cur}/{s.hp_max}"
    print("✅ long rest clears available_hit_points and restores HP")


def test_bite_drains_max_and_heals_attacker():
    """A reduceHPMax hit drains the target's HP maximum by the Necrotic damage and
    heals the attacker by the same amount."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # High-STR attacker, started at low HP so the life-drain heal is observable.
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), str=20, hp=100)
    # Target with a soft AC so the bite reliably lands; generous HP so it survives.
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), con=10, hp=60, ac=1)

    engine.set_agent_weapons(bm, atk, [_bite_weapon(), rpg.Weapon(), rpg.Weapon()])

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0

    result = None
    for _ in range(25):
        # Reset both combatants and retry until a (non-fumble) hit lands. hp_max is set here (not
        # just at add time) because adding the 2nd agent rebuilds all agents from their configs,
        # which would otherwise reset the attacker's max back to the default — capping the heal.
        sa = engine.get_agent_stats(bm, atk); sa.hp_cur = 5; sa.hp_max = 200
        engine.set_agent_stats(bm, atk, sa)
        st = engine.get_agent_stats(bm, tgt)
        st.hp_cur = 60; st.hp_max = 60; st.available_hit_points = 0
        engine.set_agent_stats(bm, tgt, st)
        result = engine.execute_action(bm, action)
        if result.hit:
            break
    assert result is not None and result.hit, "bite never landed in 25 tries"

    tgt_s = engine.get_agent_stats(bm, tgt)
    atk_s = engine.get_agent_stats(bm, atk)

    drain = tgt_s.available_hit_points
    assert 3 <= drain <= 18, f"Necrotic drain should be 3d6 (3..18), got {drain}"
    assert tgt_s.effective_max_hp == tgt_s.hp_max - drain, "effective max reflects the drain"
    # Life-drain heal: attacker regained exactly the drained amount (5 -> 5 + drain).
    assert atk_s.hp_cur == 5 + drain, f"attacker should heal by {drain}, got {atk_s.hp_cur - 5}"
    print(f"✅ Bite drained {drain} max HP and healed the attacker by {drain}")


def test_no_necrotic_no_drain():
    """A reduceHPMax rider on a weapon dealing no Necrotic drains nothing."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Biter", 5, 5), str=20, hp=50)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Prey", 6, 5), hp=40, ac=1)

    w = rpg.Weapon()
    w.name = "Dry Bite"
    w.reach_ft = 5
    w.proficient = True
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 4
    pr.bonus = 0
    w.physical_damage_types = [pr]
    c = rpg.AttackCondition()
    c.condition_name = "reduceHPMax"
    w.conditions = [c]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0
    for _ in range(15):
        engine.execute_action(bm, action)
    assert engine.get_agent_stats(bm, tgt).available_hit_points == 0, \
        "no Necrotic damage → no max-HP reduction"
    print("✅ reduceHPMax with no Necrotic damage drains nothing")


if __name__ == "__main__":
    test_available_hit_points_basics()
    test_long_rest_clears_drain()
    test_bite_drains_max_and_heals_attacker()
    test_no_necrotic_no_drain()
    print("\n✅ All vampire-feature tests passed!")
