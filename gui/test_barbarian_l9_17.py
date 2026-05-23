#!/usr/bin/env python3
"""
Test Barbarian L9-17 mechanics: Brutal Strike (L9), enhanced effects (L13), upgraded damage (L17)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle, create_melee_weapon)


def test_brutal_strike_damage_dice_l9():
    """Verify Brutal Strike damage dice is 1d10 at L9"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian9", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 9
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 9)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.brutal_strike_damage_dice == 1, f"L9 should have 1d10, got {stats.brutal_strike_damage_dice}d10"
    print("✅ test_brutal_strike_damage_dice_l9 passed")


def test_brutal_strike_damage_dice_l17():
    """Verify Brutal Strike damage dice is 2d10 at L17"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian17", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 17
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 17)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.brutal_strike_damage_dice == 2, f"L17 should have 2d10, got {stats.brutal_strike_damage_dice}d10"
    print("✅ test_brutal_strike_damage_dice_l17 passed")


def test_brutal_strike_conditions_binding():
    """Verify Brutal Strike condition fields are properly bound"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Test", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert hasattr(cond, 'brutal_strike_available'), "Conditions should have brutal_strike_available"
    assert hasattr(cond, 'hamstrung'), "Conditions should have hamstrung"
    assert hasattr(cond, 'sundering_target_idx'), "Conditions should have sundering_target_idx"
    assert hasattr(cond, 'staggered_next_save'), "Conditions should have staggered_next_save"

    assert cond.brutal_strike_available == False, "brutal_strike_available should default to False"
    assert cond.hamstrung == False, "hamstrung should default to False"
    assert cond.sundering_target_idx == -1, "sundering_target_idx should default to -1"
    assert cond.staggered_next_save == False, "staggered_next_save should default to False"
    print("✅ test_brutal_strike_conditions_binding passed")


def test_brutal_strike_available_each_turn():
    """Reckless Attack is a per-turn declaration: it resets at the start of each turn, and
    Brutal Strike is eligible again on any turn the Barbarian re-declares Reckless Attack."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    atk = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 6, 5), ac=1, hp=500)

    stats = engine.get_agent_stats(bm, atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 9
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 9)
    engine.set_agent_stats(bm, atk, stats)
    w = create_melee_weapon(); w.proficient = True
    engine.set_agent_weapons(bm, atk, [w, create_melee_weapon(), create_melee_weapon()])

    # Turn 1: declare Rage + Reckless Attack, eligible attack -> BS available, then consumed.
    c = engine.get_agent_conditions(bm, atk)
    c.raging = True
    c.reckless_attack = True
    engine.set_agent_conditions(bm, atk, c)
    engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert engine.get_agent_conditions(bm, atk).brutal_strike_available, "BS should be available turn 1"
    res = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, atk, tgt, [1], res)

    # Turn 2: a new turn resets the per-turn flags, including reckless_attack.
    engine.begin_turn(bm, atk)
    c2 = engine.get_agent_conditions(bm, atk)
    assert not c2.reckless_attack, "Reckless Attack resets at the start of each turn (per-turn declaration)"
    assert not c2.brutal_strike_available, "BS availability resets at turn start"

    # Re-declare Reckless Attack this turn -> Brutal Strike is eligible again.
    c2.reckless_attack = True
    engine.set_agent_conditions(bm, atk, c2)
    engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert engine.get_agent_conditions(bm, atk).brutal_strike_available, \
        "BS should be eligible again on turn 2 after re-declaring Reckless Attack"
    print("✅ test_brutal_strike_available_each_turn passed")


def test_forceful_blow_push():
    """Verify Forceful Blow (effect 0) pushes the target away from the attacker."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config_atk = create_test_agent("Barbarian9", 5, 5)
    idx_atk = add_agent_to_battle(engine, bm, config_atk)

    config_tgt = create_test_agent("Target", 6, 5)
    idx_tgt = add_agent_to_battle(engine, bm, config_tgt)

    stats = engine.get_agent_stats(bm, idx_atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 9
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 9)
    engine.set_agent_stats(bm, idx_atk, stats)

    before_col = bm.placed_agents[idx_tgt].origin.col

    # Apply Brutal Strike with Forceful Blow effect (effect 0)
    result = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, idx_atk, idx_tgt, [0], result)

    after_col = bm.placed_agents[idx_tgt].origin.col
    assert result.push_ft_applied > 0, f"Forceful Blow should push the target, got {result.push_ft_applied} ft"
    assert after_col > before_col, f"Target should be pushed away from attacker (+x): before {before_col}, after {after_col}"
    print("✅ test_forceful_blow_push passed")


def test_hamstring_blow_condition():
    """Verify Hamstring Blow applies hamstrung condition"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create attacker and target
    config_atk = create_test_agent("Barbarian9", 5, 5)
    idx_atk = add_agent_to_battle(engine, bm, config_atk)

    config_tgt = create_test_agent("Target", 6, 5)
    idx_tgt = add_agent_to_battle(engine, bm, config_tgt)

    stats = engine.get_agent_stats(bm, idx_atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 9
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 9)
    engine.set_agent_stats(bm, idx_atk, stats)

    # Apply Brutal Strike with Hamstring Blow effect (effect 1)
    result = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, idx_atk, idx_tgt, [1], result)

    # Verify target has hamstrung condition
    cond_tgt = engine.get_agent_conditions(bm, idx_tgt)
    assert cond_tgt.hamstrung == True, "Target should be hamstrung"
    print("✅ test_hamstring_blow_condition passed")


def test_staggering_blow_condition_l13():
    """Verify Staggering Blow applies disadvantage on next save (L13+)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config_atk = create_test_agent("Barbarian13", 5, 5)
    idx_atk = add_agent_to_battle(engine, bm, config_atk)

    config_tgt = create_test_agent("Target", 6, 5)
    idx_tgt = add_agent_to_battle(engine, bm, config_tgt)

    stats = engine.get_agent_stats(bm, idx_atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 13
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 13)
    engine.set_agent_stats(bm, idx_atk, stats)

    # Apply Brutal Strike with Staggering Blow effect (effect 2)
    result = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, idx_atk, idx_tgt, [2], result)

    # Verify target has staggered_next_save condition
    cond_tgt = engine.get_agent_conditions(bm, idx_tgt)
    assert cond_tgt.staggered_next_save == True, "Target should have staggered_next_save"
    print("✅ test_staggering_blow_condition_l13 passed")


def test_sundering_blow_condition_l13():
    """Verify Sundering Blow applies +5 to next attack vs target (L13+)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config_atk = create_test_agent("Barbarian13", 5, 5)
    idx_atk = add_agent_to_battle(engine, bm, config_atk)

    config_tgt = create_test_agent("Target", 6, 5)
    idx_tgt = add_agent_to_battle(engine, bm, config_tgt)

    stats = engine.get_agent_stats(bm, idx_atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 13
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 13)
    engine.set_agent_stats(bm, idx_atk, stats)

    # Apply Brutal Strike with Sundering Blow effect (effect 3)
    result = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, idx_atk, idx_tgt, [3], result)

    # Verify target has sundering_target_idx set to attacker
    cond_tgt = engine.get_agent_conditions(bm, idx_tgt)
    assert cond_tgt.sundering_target_idx == idx_atk, f"Target should have sundering_target_idx = {idx_atk}, got {cond_tgt.sundering_target_idx}"
    print("✅ test_sundering_blow_condition_l13 passed")


def test_brutal_strike_multi_effect_l17():
    """Verify L17+ can apply multiple effects (pick 2)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config_atk = create_test_agent("Barbarian17", 5, 5)
    idx_atk = add_agent_to_battle(engine, bm, config_atk)

    config_tgt = create_test_agent("Target", 6, 5)
    idx_tgt = add_agent_to_battle(engine, bm, config_tgt)

    stats = engine.get_agent_stats(bm, idx_atk)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 17
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 17)
    engine.set_agent_stats(bm, idx_atk, stats)

    # Apply Brutal Strike with two effects: Hamstring (1) and Staggering (2)
    result = rpg.AttackResult()
    engine.apply_brutal_strike_effect(bm, idx_atk, idx_tgt, [1, 2], result)

    # Verify both conditions are applied
    cond_tgt = engine.get_agent_conditions(bm, idx_tgt)
    assert cond_tgt.hamstrung == True, "Target should be hamstrung"
    assert cond_tgt.staggered_next_save == True, "Target should be staggered"
    print("✅ test_brutal_strike_multi_effect_l17 passed")


def test_brutal_strike_flag_reset():
    """Verify brutal_strike_available flag is reset at start of round"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Barbarian9", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 9
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 9)
    engine.set_agent_stats(bm, idx, stats)

    # Set brutal_strike_available flag manually
    cond = engine.get_agent_conditions(bm, idx)
    cond.brutal_strike_available = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.brutal_strike_available == True, "Flag should be set"

    # Run a round (this should reset the flag)
    turn_actions = [rpg.TurnActions()]
    turn_actions[0].agent_idx = idx
    engine.run_round(bm, turn_actions)

    # Verify flag is reset
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.brutal_strike_available == False, "Flag should be reset at start of round"
    print("✅ test_brutal_strike_flag_reset passed")


def test_hamstrung_reset():
    """Verify hamstrung condition is reset at start of round"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Target", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set hamstrung condition manually
    cond = engine.get_agent_conditions(bm, idx)
    cond.hamstrung = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.hamstrung == True, "Condition should be set"

    # Run a round
    turn_actions = [rpg.TurnActions()]
    turn_actions[0].agent_idx = idx
    engine.run_round(bm, turn_actions)

    # Verify condition is reset
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.hamstrung == False, "Hamstrung should be reset at start of round"
    print("✅ test_hamstrung_reset passed")


if __name__ == "__main__":
    test_brutal_strike_damage_dice_l9()
    test_brutal_strike_damage_dice_l17()
    test_brutal_strike_conditions_binding()
    test_brutal_strike_available_each_turn()
    test_forceful_blow_push()
    test_hamstring_blow_condition()
    test_staggering_blow_condition_l13()
    test_sundering_blow_condition_l13()
    test_brutal_strike_multi_effect_l17()
    test_brutal_strike_flag_reset()
    test_hamstrung_reset()
    print("\n✅ All L9-17 Brutal Strike tests passed!")
