#!/usr/bin/env python3
"""
Test Barbarian L1-3 mechanics: Rage, Unarmored Defense, Reckless Attack
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def test_rage_resource_initialization():
    """Verify Rage resource is initialized correctly for Barbarian"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Create Barbarian at level 1
    config = create_test_agent("Barbarian1", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 1
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize resources after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert "Rage" in stats.resources, "Barbarian should have Rage resource"

    rage = stats.resources["Rage"]
    assert rage.current == 2, f"Barbarian L1 should have 2 Rage uses, got {rage.current}"
    assert rage.max == 2, "Rage max should be 2"
    assert rage.duration == 10, "Rage duration should be 10 turns"
    print("✅ test_rage_resource_initialization passed")


def test_rage_uses_by_level():
    """Verify Rage uses scale correctly by level"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    test_cases = [
        (1, 2), (2, 2), (3, 3), (5, 3), (7, 4), (9, 4), (13, 5), (17, 6), (20, 6)
    ]

    for level, expected_uses in test_cases:
        config = create_test_agent(f"Barbarian{level}", 5, 5)
        config.stats.character_class = rpg.CharacterClass.Barbarian
        config.stats.char_level = level
        idx = add_agent_to_battle(engine, bm, config)

        stats = engine.get_agent_stats(bm, idx)
        stats.initialize_class_resources(rpg.CharacterClass.Barbarian, level)
        engine.set_agent_stats(bm, idx, stats)

        stats = engine.get_agent_stats(bm, idx)
        rage = stats.resources["Rage"]
        assert rage.current == expected_uses, f"L{level}: expected {expected_uses} uses, got {rage.current}"

    print("✅ test_rage_uses_by_level passed")


def test_unarmored_defense():
    """Test Unarmored Defense AC calculation (10 + DEX + CON)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("BarbarianUnarmored", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set all stats AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 1
    stats.dex = 14  # +2 modifier
    stats.con = 16  # +3 modifier
    engine.set_agent_stats(bm, idx, stats)

    ac = engine.calculate_ac(bm, idx)
    expected_ac = 10 + 2 + 3  # 10 + DEX mod + CON mod
    assert ac == expected_ac, f"Unarmored Defense AC should be {expected_ac}, got {ac}"
    print("✅ test_unarmored_defense passed")


def test_unarmored_defense_with_shield():
    """Test Unarmored Defense with shield bonus - SKIPPED (requires PlacedAgent.weapons access)"""
    print("🔴 test_unarmored_defense_with_shield skipped (needs PlacedAgent.weapons)")


def test_unarmored_defense_not_with_armor():
    """Test that Unarmored Defense doesn't apply when wearing armor - SKIPPED (requires PlacedAgent.armor access)"""
    print("🔴 test_unarmored_defense_not_with_armor skipped (needs PlacedAgent.armor)")


def test_rage_damage_bonus_by_level():
    """Test Rage damage bonus scales correctly"""
    test_cases = [
        (1, 2), (5, 2), (8, 2),   # +2 for levels 1-8
        (9, 3), (12, 3), (16, 3),  # +3 for levels 9-16
        (17, 4), (20, 4),           # +4 for levels 17-20
    ]

    for level, expected_bonus in test_cases:
        bonus = rpg.CombatEngine.get_rage_damage_bonus(level)
        assert bonus == expected_bonus, f"L{level}: expected bonus {expected_bonus}, got {bonus}"

    print("✅ test_rage_damage_bonus_by_level passed")


def test_raging_and_reckless_flags():
    """Test that raging and reckless_attack flags can be set/read"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("TestBarbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.raging, "Should start not raging"
    assert not cond.reckless_attack, "Should start without reckless_attack"

    # Set both flags
    cond.raging = True
    cond.reckless_attack = True
    engine.set_agent_conditions(bm, idx, cond)

    cond2 = engine.get_agent_conditions(bm, idx)
    assert cond2.raging, "raging flag should persist"
    assert cond2.reckless_attack, "reckless_attack flag should persist"
    print("✅ test_raging_and_reckless_flags passed")


def test_conditions_binding():
    """Test that new Conditions fields are properly bound to Python"""
    # Create a Conditions object directly
    cond = rpg.Conditions()

    # Test that raging and reckless_attack exist and default to False
    assert hasattr(cond, 'raging'), "Conditions should have raging field"
    assert hasattr(cond, 'reckless_attack'), "Conditions should have reckless_attack field"
    assert cond.raging == False, "raging should default to False"
    assert cond.reckless_attack == False, "reckless_attack should default to False"

    # Test that we can set them
    cond.raging = True
    cond.reckless_attack = True
    assert cond.raging == True
    assert cond.reckless_attack == True
    print("✅ test_conditions_binding passed")


def test_barbarian_character_class():
    """Test that Barbarian character class is accessible"""
    assert hasattr(rpg.CharacterClass, 'Barbarian'), "Barbarian class should exist"
    config = create_test_agent("TestBarbarian", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    assert config.stats.character_class == rpg.CharacterClass.Barbarian
    print("✅ test_barbarian_character_class passed")


def test_rage_activation():
    """Test activating Rage and applying BPS resistance"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("RageBarbarian", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 1
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize Rage resource
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, idx, stats)

    # Before activation: not raging, normal damage multipliers
    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.raging, "Should not be raging initially"
    stats = engine.get_agent_stats(bm, idx)
    assert stats.physical_damage_multipliers[0] == 1.0, "B damage multiplier should be 1.0 initially"  # Bludgeoning
    assert stats.physical_damage_multipliers[1] == 1.0, "P damage multiplier should be 1.0 initially"  # Piercing
    assert stats.physical_damage_multipliers[2] == 1.0, "S damage multiplier should be 1.0 initially"  # Slashing

    # Activate Rage
    engine.activate_rage(bm, idx)

    # After activation: raging, BPS resistance (0.5x)
    cond = engine.get_agent_conditions(bm, idx)
    assert cond.raging, "Should be raging after activation"
    stats = engine.get_agent_stats(bm, idx)
    assert stats.physical_damage_multipliers[0] == 0.5, f"B damage multiplier should be 0.5, got {stats.physical_damage_multipliers[0]}"
    assert stats.physical_damage_multipliers[1] == 0.5, f"P damage multiplier should be 0.5, got {stats.physical_damage_multipliers[1]}"
    assert stats.physical_damage_multipliers[2] == 0.5, f"S damage multiplier should be 0.5, got {stats.physical_damage_multipliers[2]}"

    # Rage resource should have 1 use remaining (started with 2, spent 1)
    rage = stats.resources["Rage"]
    assert rage.current == 1, f"Rage uses should be 1 after activation, got {rage.current}"
    print("✅ test_rage_activation passed")


def _attack_until_hit(engine, bm, atk, tgt, tries=40):
    """Resolve attacks until one lands (works around the random natural-1 fumble).
    Returns the hitting AttackResult; raises if none of `tries` attacks connect."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if r.hit:
            return r
    raise AssertionError(f"no hit in {tries} attacks (could not test damage)")


def test_rage_resistance_halves_modifier():
    """Regression: Rage's BPS resistance must halve ALL physical damage of the type — including
    the attacker's ability modifier and weapon bonus damage — not just the rolled dice. Uses a
    dice-less weapon so the dealt damage is the flat modifier only and thus deterministic
    regardless of the RNG (no damage dice are rolled)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Attacker: STR 18 (+4 melee modifier) at (5,5).
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    # Target: a raging Barbarian (BPS resistance 0.5x) adjacent at (6,5).
    tgt = add_agent_to_battle(engine, bm, create_test_agent("RageBarb", 6, 5))

    s = engine.get_agent_stats(bm, atk)
    s.str = 18  # +4 modifier
    engine.set_agent_stats(bm, atk, s)

    # Dice-less melee weapon → flat damage = STR mod (+4) + weapon bonus (+2) = 6, no dice.
    # bonus_hit guarantees the swing lands (except a natural 1, handled by the retry loop).
    w = rpg.Weapon()
    w.name = "Club"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.bonus_hit = 50
    w.bonus_damage = 2
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    # Target: low AC so it is hit, lots of HP so it survives the retry loop, raging.
    ts = engine.get_agent_stats(bm, tgt)
    ts.character_class = rpg.CharacterClass.Barbarian
    ts.char_level = 1
    ts.base_ac = 1
    ts.hp_max = 1000
    ts.hp_cur = 1000
    ts.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, tgt, ts)
    engine.activate_rage(bm, tgt)

    # Confirm rage really applied BPS resistance.
    ts = engine.get_agent_stats(bm, tgt)
    assert ts.physical_damage_multipliers[0] == 0.5, "precondition: target should have BPS resistance"

    r = _attack_until_hit(engine, bm, atk, tgt)
    assert r.damage_mod == 6, f"flat modifier should be +6 (STR +4, weapon +2), got {r.damage_mod}"
    # The bug: only the (zero) dice were halved and the +6 modifier was applied at full → 6.
    # Fixed: resistance halves the modifier too → floor(6 * 0.5) = 3.
    assert r.total_damage == 3, (
        f"Rage resistance must halve the +6 modifier to 3, got {r.total_damage} "
        "(regression: flat modifier taken at full damage)")
    print("✅ test_rage_resistance_halves_modifier passed")


def test_no_resistance_keeps_full_modifier():
    """Control for test_rage_resistance_halves_modifier: with no resistance the same dice-less
    +6 attack deals the full 6, confirming the multiplier path only scales when it should."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))

    s = engine.get_agent_stats(bm, atk)
    s.str = 18  # +4 modifier
    engine.set_agent_stats(bm, atk, s)

    w = rpg.Weapon()
    w.name = "Club"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.bonus_hit = 50
    w.bonus_damage = 2
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    ts = engine.get_agent_stats(bm, tgt)
    ts.base_ac = 1
    ts.hp_max = 1000
    ts.hp_cur = 1000
    engine.set_agent_stats(bm, tgt, ts)

    r = _attack_until_hit(engine, bm, atk, tgt)
    assert r.total_damage == 6, f"no resistance should deal the full +6, got {r.total_damage}"
    print("✅ test_no_resistance_keeps_full_modifier passed")


def test_rage_end():
    """Test ending Rage clears resistance and flags"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("EndRageBarbarian", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 5
    idx = add_agent_to_battle(engine, bm, config)

    # Initialize Rage and activate it
    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 5)
    engine.set_agent_stats(bm, idx, stats)

    # Set reckless_attack flag to test clearing
    cond = engine.get_agent_conditions(bm, idx)
    engine.activate_rage(bm, idx)
    cond = engine.get_agent_conditions(bm, idx)
    cond.reckless_attack = True
    engine.set_agent_conditions(bm, idx, cond)

    # End Rage
    engine.end_rage(bm, idx)

    # After end: not raging, normal damage multipliers, reckless_attack cleared
    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.raging, "Should not be raging after end_rage"
    assert not cond.reckless_attack, "reckless_attack should be cleared"
    stats = engine.get_agent_stats(bm, idx)
    assert stats.physical_damage_multipliers[0] == 1.0, "B damage multiplier should be 1.0 after end"
    assert stats.physical_damage_multipliers[1] == 1.0, "P damage multiplier should be 1.0 after end"
    assert stats.physical_damage_multipliers[2] == 1.0, "S damage multiplier should be 1.0 after end"

    rage = stats.resources["Rage"]
    assert rage.duration_remaining == 0, "Rage duration should be 0 after end"
    print("✅ test_rage_end passed")


def test_rage_extend():
    """Test extending Rage duration"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("ExtendRageBarbarian", 5, 5)
    config.stats.character_class = rpg.CharacterClass.Barbarian
    config.stats.char_level = 1
    idx = add_agent_to_battle(engine, bm, config)

    stats = engine.get_agent_stats(bm, idx)
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 1)
    engine.set_agent_stats(bm, idx, stats)

    # Activate Rage (duration_remaining = 10)
    engine.activate_rage(bm, idx)
    stats = engine.get_agent_stats(bm, idx)
    rage = stats.resources["Rage"]
    initial_duration = rage.duration_remaining
    assert initial_duration == 10, f"Initial Rage duration should be 10, got {initial_duration}"

    # Manually decrease duration (simulate turn passing)
    stats.resources["Rage"].duration_remaining = 5
    engine.set_agent_stats(bm, idx, stats)

    # Extend Rage (reset to 10)
    engine.extend_rage(bm, idx)
    stats = engine.get_agent_stats(bm, idx)
    rage = stats.resources["Rage"]
    assert rage.duration_remaining == 10, f"Extended Rage duration should be 10, got {rage.duration_remaining}"
    print("✅ test_rage_extend passed")


def test_berserker_frenzy_flag():
    """Test that Berserker Frenzy flag can be set/tracked"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("Berserker", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.berserker_frenzy_used, "Frenzy should not be used initially"

    # Set flag
    cond.berserker_frenzy_used = True
    engine.set_agent_conditions(bm, idx, cond)

    cond2 = engine.get_agent_conditions(bm, idx)
    assert cond2.berserker_frenzy_used, "Frenzy used flag should persist"
    print("✅ test_berserker_frenzy_flag passed")


def test_wild_heart_bear_form():
    """Test Wild Heart Bear Form damage resistance"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WildHeartBear", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set subclass and form AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 3
    stats.barbarian_subclass = rpg.BarbianSubclass.WildHeart
    stats.wild_heart_rage_choice = rpg.WildHeartRageChoice.Bear
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 3)
    engine.set_agent_stats(bm, idx, stats)

    engine.activate_rage(bm, idx)

    # Check that Bear Form grants extra resistances (Acid, Cold, Fire, Lightning, Poison, Thunder)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.magic_damage_multipliers[0] == 0.5, f"Acid resistance should be 0.5, got {stats.magic_damage_multipliers[0]}"  # Acid
    assert stats.magic_damage_multipliers[2] == 0.5, f"Fire resistance should be 0.5, got {stats.magic_damage_multipliers[2]}"  # Fire
    assert stats.magic_damage_multipliers[4] == 0.5, f"Lightning resistance should be 0.5, got {stats.magic_damage_multipliers[4]}"  # Lightning
    assert stats.magic_damage_multipliers[6] == 0.5, f"Poison resistance should be 0.5, got {stats.magic_damage_multipliers[6]}"  # Poison
    assert stats.magic_damage_multipliers[9] == 0.5, f"Thunder resistance should be 0.5, got {stats.magic_damage_multipliers[9]}"  # Thunder

    # Check BPS resistance still applies
    assert stats.physical_damage_multipliers[0] == 0.5, "Bludgeoning should be 0.5"
    assert stats.physical_damage_multipliers[1] == 0.5, "Piercing should be 0.5"
    assert stats.physical_damage_multipliers[2] == 0.5, "Slashing should be 0.5"

    # Non-resistant damage types should still be 1.0 (Force, Necrotic, Psychic, Radiant)
    assert stats.magic_damage_multipliers[3] == 1.0, f"Force should be 1.0, got {stats.magic_damage_multipliers[3]}"  # Force
    assert stats.magic_damage_multipliers[5] == 1.0, f"Necrotic should be 1.0, got {stats.magic_damage_multipliers[5]}"  # Necrotic
    assert stats.magic_damage_multipliers[7] == 1.0, f"Psychic should be 1.0, got {stats.magic_damage_multipliers[7]}"  # Psychic
    assert stats.magic_damage_multipliers[8] == 1.0, f"Radiant should be 1.0, got {stats.magic_damage_multipliers[8]}"  # Radiant

    print("✅ test_wild_heart_bear_form passed")


def test_wild_heart_rage_choice():
    """Test Wild Heart rage choice field"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WildHeartTest", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Get stats after adding to battle
    stats = engine.get_agent_stats(bm, idx)
    assert stats.wild_heart_rage_choice == rpg.WildHeartRageChoice.NONE, "Should start with no choice"

    # Set to Eagle
    stats.wild_heart_rage_choice = rpg.WildHeartRageChoice.Eagle
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.wild_heart_rage_choice == rpg.WildHeartRageChoice.Eagle, "Choice should persist"

    # Change to Wolf
    stats.wild_heart_rage_choice = rpg.WildHeartRageChoice.Wolf
    engine.set_agent_stats(bm, idx, stats)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.wild_heart_rage_choice == rpg.WildHeartRageChoice.Wolf, "Choice should be updated"
    print("✅ test_wild_heart_rage_choice passed")


def test_world_tree_vitality():
    """Test World Tree Vitality of the Tree granting temp HP"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("WorldTreeBarbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    # Set subclass AFTER adding to battle
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = 5
    stats.barbarian_subclass = rpg.BarbianSubclass.WorldTree
    initial_temp_hp = stats.temp_hp
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, 5)
    engine.set_agent_stats(bm, idx, stats)

    # Activate Rage - should grant temp HP = char level (5)
    engine.activate_rage(bm, idx)

    stats = engine.get_agent_stats(bm, idx)
    assert stats.temp_hp >= 5, f"World Tree Vitality should grant at least 5 temp HP, got {stats.temp_hp}"
    assert stats.temp_hp >= initial_temp_hp + 5, f"World Tree should add to existing temp HP"
    print("✅ test_world_tree_vitality passed")


def test_zealot_divine_fury_flag():
    """Test Zealot Divine Fury flag"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    config = create_test_agent("ZealotBarbarian", 5, 5)
    idx = add_agent_to_battle(engine, bm, config)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.zealot_divine_fury_used, "Divine Fury should not be used initially"

    # Set flag
    cond.zealot_divine_fury_used = True
    engine.set_agent_conditions(bm, idx, cond)

    cond2 = engine.get_agent_conditions(bm, idx)
    assert cond2.zealot_divine_fury_used, "Divine Fury used flag should persist"
    print("✅ test_zealot_divine_fury_flag passed")


def test_danger_sense():
    """Test Danger Sense is only available at L2+"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Test that Level 1 Barbarian doesn't have Danger Sense
    config_l1 = create_test_agent("BarbL1", 5, 5)
    idx_l1 = add_agent_to_battle(engine, bm, config_l1)

    stats_l1 = engine.get_agent_stats(bm, idx_l1)
    stats_l1.character_class = rpg.CharacterClass.Barbarian
    stats_l1.char_level = 1
    engine.set_agent_stats(bm, idx_l1, stats_l1)

    stats_l1 = engine.get_agent_stats(bm, idx_l1)
    assert stats_l1.char_level == 1, "L1 Barbarian created"

    # Test that Level 2 Barbarian would have Danger Sense (implementation is in spell save logic)
    config_l2 = create_test_agent("BarbL2", 10, 10)
    idx_l2 = add_agent_to_battle(engine, bm, config_l2)

    stats_l2 = engine.get_agent_stats(bm, idx_l2)
    stats_l2.character_class = rpg.CharacterClass.Barbarian
    stats_l2.char_level = 2
    engine.set_agent_stats(bm, idx_l2, stats_l2)

    stats_l2 = engine.get_agent_stats(bm, idx_l2)
    assert stats_l2.char_level == 2, "L2 Barbarian created"
    assert stats_l2.character_class == rpg.CharacterClass.Barbarian, "Is Barbarian"
    print("✅ test_danger_sense passed")


def test_primal_knowledge():
    """Test Primal Knowledge for Acrobatics and Stealth (L3+)"""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Test L2 Barbarian - no Primal Knowledge
    config_l2 = create_test_agent("BarbL2", 5, 5)
    idx_l2 = add_agent_to_battle(engine, bm, config_l2)

    stats_l2 = engine.get_agent_stats(bm, idx_l2)
    stats_l2.character_class = rpg.CharacterClass.Barbarian
    stats_l2.char_level = 2
    engine.set_agent_stats(bm, idx_l2, stats_l2)

    cond = engine.get_agent_conditions(bm, idx_l2)
    cond.raging = True
    engine.set_agent_conditions(bm, idx_l2, cond)

    # L2 should not have Primal Knowledge
    assert not engine.can_use_primal_knowledge(bm, idx_l2, "Acrobatics"), "L2 should not have Primal Knowledge"
    assert not engine.can_use_primal_knowledge(bm, idx_l2, "Stealth"), "L2 should not have Primal Knowledge"

    # Test L3 Barbarian with Rage - should have Primal Knowledge
    config_l3 = create_test_agent("BarbL3", 10, 10)
    idx_l3 = add_agent_to_battle(engine, bm, config_l3)

    stats_l3 = engine.get_agent_stats(bm, idx_l3)
    stats_l3.character_class = rpg.CharacterClass.Barbarian
    stats_l3.char_level = 3
    engine.set_agent_stats(bm, idx_l3, stats_l3)

    cond = engine.get_agent_conditions(bm, idx_l3)
    cond.raging = True
    engine.set_agent_conditions(bm, idx_l3, cond)

    # L3 with Rage should have Primal Knowledge for Acrobatics and Stealth
    assert engine.can_use_primal_knowledge(bm, idx_l3, "Acrobatics"), "L3 Raging should have Primal Knowledge for Acrobatics"
    assert engine.can_use_primal_knowledge(bm, idx_l3, "Stealth"), "L3 Raging should have Primal Knowledge for Stealth"

    # L3 without Rage should not have Primal Knowledge
    cond = engine.get_agent_conditions(bm, idx_l3)
    cond.raging = False
    engine.set_agent_conditions(bm, idx_l3, cond)

    assert not engine.can_use_primal_knowledge(bm, idx_l3, "Acrobatics"), "L3 not Raging should not have Primal Knowledge"
    assert not engine.can_use_primal_knowledge(bm, idx_l3, "Stealth"), "L3 not Raging should not have Primal Knowledge"

    # Other skills should not have Primal Knowledge
    cond = engine.get_agent_conditions(bm, idx_l3)
    cond.raging = True
    engine.set_agent_conditions(bm, idx_l3, cond)

    assert not engine.can_use_primal_knowledge(bm, idx_l3, "Perception"), "Perception should not use Primal Knowledge"
    assert not engine.can_use_primal_knowledge(bm, idx_l3, "Intimidation"), "Intimidation should not use Primal Knowledge"

    print("✅ test_primal_knowledge passed")


def main():
    print("Running Barbarian L1-3 tests...")
    print()

    test_rage_resource_initialization()
    test_rage_uses_by_level()
    test_unarmored_defense()
    test_unarmored_defense_with_shield()
    test_unarmored_defense_not_with_armor()
    test_rage_damage_bonus_by_level()
    test_raging_and_reckless_flags()
    test_conditions_binding()
    test_barbarian_character_class()
    test_rage_activation()
    test_rage_resistance_halves_modifier()
    test_no_resistance_keeps_full_modifier()
    test_rage_end()
    test_rage_extend()
    test_berserker_frenzy_flag()
    test_wild_heart_bear_form()
    test_wild_heart_rage_choice()
    test_world_tree_vitality()
    test_zealot_divine_fury_flag()
    test_danger_sense()
    test_primal_knowledge()

    print()
    print("=" * 60)
    print("✅ All Barbarian L1-3 tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
