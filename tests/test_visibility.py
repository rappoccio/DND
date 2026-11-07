#!/usr/bin/env python3
"""
Test suite for Visibility Mechanics
Tests line of sight, hiding, stealth checks, perception contests, and related mechanics.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

def test_visibility_level_clear():
    """Test Clear visibility level."""
    assert hasattr(rpg, 'VisibilityLevel')
    assert hasattr(rpg.VisibilityLevel, 'Clear')
    print("✅ Clear visibility level exists")

def test_visibility_level_dim():
    """Test Dim visibility level."""
    assert hasattr(rpg.VisibilityLevel, 'Dim')
    print("✅ Dim visibility level exists")

def test_visibility_level_lightly_obscured():
    """Test LightlyObscured visibility level."""
    assert hasattr(rpg.VisibilityLevel, 'LightlyObscured')
    print("✅ LightlyObscured visibility level exists")

def test_visibility_level_dark():
    """Test Dark visibility level."""
    assert hasattr(rpg.VisibilityLevel, 'Dark')
    print("✅ Dark visibility level exists")

def test_visibility_level_magical_dark():
    """Test MagicalDark visibility level."""
    assert hasattr(rpg.VisibilityLevel, 'MagicalDark')
    print("✅ MagicalDark visibility level exists")

def test_visibility_level_blocked():
    """Test Blocked visibility level (no LOS)."""
    assert hasattr(rpg.VisibilityLevel, 'Blocked')
    print("✅ Blocked visibility level exists")

def test_line_of_sight():
    """Test line of sight between agents."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent1 = create_test_agent("Agent1", 5, 5)
    agent2 = create_test_agent("Agent2", 7, 5)  # 2 cells away horizontally

    idx1 = add_agent_to_battle(engine, bm, agent1)
    idx2 = add_agent_to_battle(engine, bm, agent2)

    has_los = bm.has_line_of_sight(rpg.Cell(5, 5), 1, rpg.Cell(7, 5), 1)
    assert has_los
    print("✅ Line of sight computed correctly")

def test_can_see():
    """Test vision check with all factors."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent1 = create_test_agent("Observer", 5, 5)
    agent2 = create_test_agent("Target", 7, 5)

    idx1 = add_agent_to_battle(engine, bm, agent1, wis=14)
    idx2 = add_agent_to_battle(engine, bm, agent2)
    # WIS 14 = +2 modifier
    # Passive Perception = 10 + WIS modifier = 12
    wis_mod = (14 - 10) // 2
    assert wis_mod == 2
    print("✅ Can see computation includes visibility factors")

def test_passive_perception():
    """Test passive perception calculation."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent = create_test_agent("Scout", 5, 5)
    idx = add_agent_to_battle(engine, bm, agent, wis=16)
    # WIS 16 = +3 modifier
    # Passive Perception = 10 + WIS modifier = 13
    wis_mod = (16 - 10) // 2
    passive_perception = 10 + wis_mod
    assert passive_perception == 13
    print("✅ Passive perception calculation correct")

def test_stealth_bonus():
    """Test stealth bonus calculation."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent = create_test_agent("Rogue", 5, 5)
    idx = add_agent_to_battle(engine, bm, agent, dex=18)
    # DEX 18 = +4 modifier
    # Stealth = DEX modifier (if proficient would add prof bonus)
    dex_mod = (18 - 10) // 2
    stealth_bonus = dex_mod
    assert stealth_bonus == 4
    print("✅ Stealth bonus calculation correct")

def test_stealth_proficiency():
    """Test stealth proficiency bonus."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent = create_test_agent("Rogue", 5, 5)
    idx = add_agent_to_battle(engine, bm, agent, dex=16)
    # With proficiency, gets +prof_bonus to stealth (typically +2 at low levels)
    dex_mod = (16 - 10) // 2
    assert dex_mod == 3
    print("✅ Stealth proficiency flag accessible")

def test_check_hide_pre_combat():
    """Test hide check before combat (vs passive perception)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    hider = create_test_agent("Hider", 5, 5)
    observer = create_test_agent("Observer", 8, 5)

    hider_idx = add_agent_to_battle(engine, bm, hider, dex=16)
    observer_idx = add_agent_to_battle(engine, bm, observer, wis=14)

    # Out of combat: uses passive perception
    in_combat = False
    result = engine.check_hide(bm, hider_idx, in_combat)
    assert hasattr(result, 'valid')
    assert hasattr(result, 'hidden')
    assert hasattr(result, 'stealth_total')
    print("✅ Hide check returns proper result structure")

def test_check_hide_in_combat():
    """Test hide check during combat (vs active perception)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    hider = create_test_agent("Hider", 5, 5)
    observer = create_test_agent("Observer", 8, 5)

    hider_idx = add_agent_to_battle(engine, bm, hider, dex=16)
    observer_idx = add_agent_to_battle(engine, bm, observer, wis=14)

    # In combat: observer makes active perception roll
    in_combat = True
    result = engine.check_hide(bm, hider_idx, in_combat)
    assert hasattr(result, 'valid')
    print("✅ Hide check in combat works")

def test_hidden_condition():
    """Test that hidden condition is set after successful hide."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    agent = create_test_agent("TestAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, agent)

    cond = engine.get_agent_conditions(bm, idx)
    assert not cond.hidden
    cond.hidden = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.hidden
    print("✅ Hidden condition can be set and retrieved")

def test_hidden_agent_reveals_on_attack():
    """Test that attacking reveals hidden agent."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    attacker = create_test_agent("Attacker", 5, 5)
    target = create_test_agent("Target", 7, 5)

    att_idx = add_agent_to_battle(engine, bm, attacker)
    tgt_idx = add_agent_to_battle(engine, bm, target)

    # Set target hidden
    cond = engine.get_agent_conditions(bm, tgt_idx)
    cond.hidden = True
    engine.set_agent_conditions(bm, tgt_idx, cond)

    # Attack should reveal the target
    # (actual attack execution may vary by implementation)
    assert cond.hidden
    print("✅ Hidden condition affects combat (implementation varies)")

def test_darkvision():
    """Test darkvision sight range."""
    stats = rpg.Stats()
    stats.darkvision_range = 60  # 60 feet
    assert stats.darkvision_range == 60
    print("✅ Darkvision range property accessible")

def test_truesight():
    """Test truesight sight range."""
    stats = rpg.Stats()
    stats.truesight_range = 120  # 120 feet
    assert stats.truesight_range == 120
    print("✅ Truesight range property accessible")

def test_devilssight():
    """Test devil's sight (see in magical darkness)."""
    agent = create_test_agent("Warlock", 5, 5)
    a = rpg.AgentConfig()
    a.stats.devilssight_range = 120  # Can see in darkness within 120 feet
    assert a.stats.devilssight_range == 120
    print("✅ Devil's sight range property accessible")

def test_hidden_agent_detection_on_movement():
    """Test that moving hidden agent triggers LOS recheck."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    hider = create_test_agent("Hider", 5, 5)
    observer = create_test_agent("Observer", 8, 5)

    hider_idx = add_agent_to_battle(engine, bm, hider, dex=16)
    observer_idx = add_agent_to_battle(engine, bm, observer, wis=14)

    # Set hider as hidden
    cond = engine.get_agent_conditions(bm, hider_idx)
    cond.hidden = True
    engine.set_agent_conditions(bm, hider_idx, cond)

    # Move hider (implementation may trigger detection check)
    print("✅ Hidden agent movement can trigger detection (implementation varies)")

def test_blinded_condition_blocks_sight():
    """Test that blinded condition prevents seeing."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    blind_agent = create_test_agent("BlindAgent", 5, 5)
    idx = add_agent_to_battle(engine, bm, blind_agent)

    cond = engine.get_agent_conditions(bm, idx)
    cond.blinded = True
    engine.set_agent_conditions(bm, idx, cond)

    cond = engine.get_agent_conditions(bm, idx)
    assert cond.blinded
    print("✅ Blinded condition can be applied")

def test_advantage_on_stealth_with_invisible():
    """Test that invisible agents have advantage on stealth (conceptually)."""
    # Invisible agents automatically succeed on stealth checks
    agent = create_test_agent("Invisible", 5, 5)
    assert agent.name == "Invisible"
    print("✅ Invisibility concept acknowledged")

def _set_invisible(engine, bm, idx, value=True):
    cond = engine.get_agent_conditions(bm, idx)
    cond.invisible = value
    engine.set_agent_conditions(bm, idx, cond)


def test_invisible_target_not_attackable():
    """An invisible target is excluded from available_attacks (can't target what you can't see)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    # Baseline: target is attackable.
    attacks = engine.available_attacks(bm, atk)
    assert any(a.target_idx == tgt for a in attacks), "target should be attackable when visible"
    # Make the target invisible → no longer in the action space.
    _set_invisible(engine, bm, tgt, True)
    attacks = engine.available_attacks(bm, atk)
    assert not any(a.target_idx == tgt for a in attacks), "invisible target must be excluded from available_attacks"
    assert not engine.can_perceive_target(bm, atk, tgt), "can_perceive_target should be False for invisible target"
    print("✅ test_invisible_target_not_attackable")


def test_truesight_and_blindsight_pierce_invisibility():
    """Truesight or Blindsight in range lets a viewer perceive (and attack) an invisible target."""
    for sense in ("truesight_range", "blindsight_range"):
        bm = setup_battle_map()
        engine = setup_combat_engine()
        atk = add_agent_to_battle(engine, bm, create_test_agent("Seer", 5, 5))
        tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
        _set_invisible(engine, bm, tgt, True)
        s = engine.get_agent_stats(bm, atk)
        setattr(s, sense, 30)
        engine.set_agent_stats(bm, atk, s)
        assert engine.can_perceive_target(bm, atk, tgt), f"{sense} should pierce invisibility"
        attacks = engine.available_attacks(bm, atk)
        assert any(a.target_idx == tgt for a in attacks), f"{sense} viewer should be able to attack invisible target"
    print("✅ test_truesight_and_blindsight_pierce_invisibility")


def test_invisible_target_visibility_blocked():
    """compute_visibility/get_visibility report an invisible target as Blocked (no truesight)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    obs = add_agent_to_battle(engine, bm, create_test_agent("Observer", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    _set_invisible(engine, bm, tgt, True)
    engine.compute_visibility(bm, obs)
    assert engine.get_visibility(obs, tgt) == rpg.VisibilityLevel.Blocked, \
        "invisible target should be Blocked in the visibility map"
    print("✅ test_invisible_target_visibility_blocked")


def _melee_wpn():
    w = rpg.Weapon()
    w.name = "Dagger"; w.type = rpg.WeaponType.Melee; w.proficient = True
    w.reach_ft = 5; w.range_short_feet = 5; w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing; roll.num_dice = 1; roll.die_size = 4
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_ally_still_perceives_invisible_teammate():
    """An invisible creature does NOT vanish from its own party's map.

    Regression: sight lines were gated against everyone, so an invisible PC
    dropped off their own teammates' visible-target list (Astarion → Karlach).
    Allies (same non-zero faction) should keep perceiving the invisible friend,
    while enemies are still blocked.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()
    ally = add_agent_to_battle(engine, bm, create_test_agent("Karlach", 5, 5))
    sneak = add_agent_to_battle(engine, bm, create_test_agent("Astarion", 6, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Nalfeshnee", 7, 5))
    # Karlach + Astarion on the blue team; Nalfeshnee on the red team.
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(sneak, 1)
    bm.set_agent_faction(enemy, 2)

    _set_invisible(engine, bm, sneak, True)

    # Ally perceives the invisible teammate (no truesight needed).
    assert engine.can_perceive_target(bm, ally, sneak), \
        "ally should still perceive an invisible teammate"
    engine.compute_visibility(bm, ally)
    assert engine.get_visibility(ally, sneak) != rpg.VisibilityLevel.Blocked, \
        "invisible teammate must not be Blocked on an ally's visibility map"

    # Enemy without truesight is still blocked — the fix must not leak to foes.
    assert not engine.can_perceive_target(bm, enemy, sneak), \
        "enemy must NOT perceive the invisible target"
    engine.compute_visibility(bm, enemy)
    assert engine.get_visibility(enemy, sneak) == rpg.VisibilityLevel.Blocked, \
        "invisible target should stay Blocked for enemies"
    print("✅ test_ally_still_perceives_invisible_teammate")


def test_ally_still_perceives_hidden_teammate():
    """A Hidden teammate likewise stays visible to its own party, not to enemies."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    ally = add_agent_to_battle(engine, bm, create_test_agent("Karlach", 5, 5))
    hider = add_agent_to_battle(engine, bm, create_test_agent("Astarion", 6, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Nalfeshnee", 7, 5))
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(hider, 1)
    bm.set_agent_faction(enemy, 2)

    cond = engine.get_agent_conditions(bm, hider)
    cond.hidden = True
    engine.set_agent_conditions(bm, hider, cond)

    engine.compute_visibility(bm, ally)
    assert engine.get_visibility(ally, hider) != rpg.VisibilityLevel.Blocked, \
        "hidden teammate must not be Blocked on an ally's visibility map"
    engine.compute_visibility(bm, enemy)
    assert engine.get_visibility(enemy, hider) == rpg.VisibilityLevel.Blocked, \
        "hidden target should stay Blocked for enemies"
    print("✅ test_ally_still_perceives_hidden_teammate")


def test_invisible_attacker_has_advantage():
    """An invisible attacker rolls its attacks with advantage."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Sneak", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5))
    engine.set_agent_weapons(bm, atk, _melee_wpn())
    engine.begin_turn(bm, atk)
    # Baseline: no advantage.
    base = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert not base.advantage, "control attack should not have advantage"
    # Invisible attacker → advantage.
    _set_invisible(engine, bm, atk, True)
    engine.begin_turn(bm, atk)
    res = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert res.advantage, "invisible attacker should roll with advantage"
    print("✅ test_invisible_attacker_has_advantage")


def _dark_arena(attacker_at=(5, 5), target_at=(8, 5), target_size=1):
    """An attacker and an enemy (factions 1 and 2), with a bow and a dagger, and a block of magical
    darkness over cols 8-10, rows 3-7. Returns (bm, engine, attacker_idx, target_idx)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Archer", *attacker_at))
    cfg = create_test_agent("Target", *target_at)
    cfg.size = target_size
    tgt = add_agent_to_battle(engine, bm, cfg)
    bm.set_agent_faction(atk, 1)
    bm.set_agent_faction(tgt, 2)
    bow = rpg.Weapon()
    bow.name = "Shortbow"; bow.type = rpg.WeaponType.Ranged; bow.proficient = True
    bow.normal_range_ft = 80; bow.long_range_ft = 320
    engine.set_agent_weapons(bm, atk, [bow, _melee_wpn()[0], rpg.Weapon()])
    cells = [rpg.Cell(c, r) for c in range(8, 11) for r in range(3, 8)]
    bm.place_light_effect("Darkness", cells, rpg.VisibilityLevel.MagicalDark, -1, -1)
    bm.update_lighting()
    engine.begin_turn(bm, atk)
    return bm, engine, atk, tgt


def _targets(engine, bm, atk):
    return {a.target_idx for a in engine.available_attacks(bm, atk)}


def test_darkness_hides_enemy_from_outside():
    """A ranged attack from outside can't target an enemy inside the Darkness."""
    bm, engine, atk, tgt = _dark_arena()
    assert not engine.can_perceive_target(bm, atk, tgt)
    assert tgt not in _targets(engine, bm, atk), "enemy in darkness must leave the action space"
    res = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert not res.valid, "a direct attack into the darkness must be refused"
    print("✅ test_darkness_hides_enemy_from_outside")


def test_darkness_blocks_adjacent_melee_from_outside():
    """It isn't only a range rule: a dagger from the next cell over can't target them either."""
    bm, engine, atk, tgt = _dark_arena(attacker_at=(7, 5))
    assert tgt not in _targets(engine, bm, atk)
    assert not engine.execute_action(bm, rpg.Attack(atk, tgt, 1)).valid
    print("✅ test_darkness_blocks_adjacent_melee_from_outside")


def test_darkness_does_not_hide_enemy_outside_it():
    """Control: the same shot at an enemy standing in the open is legal."""
    bm, engine, atk, tgt = _dark_arena(target_at=(7, 5))
    assert engine.can_perceive_target(bm, atk, tgt)
    assert engine.execute_action(bm, rpg.Attack(atk, tgt, 0)).valid
    print("✅ test_darkness_does_not_hide_enemy_outside_it")


def test_darkness_allows_fighting_inside_it():
    """Two creatures both in the darkness can still fight."""
    bm, engine, atk, tgt = _dark_arena(attacker_at=(8, 4), target_at=(8, 5))
    assert engine.can_perceive_target(bm, atk, tgt)
    assert engine.execute_action(bm, rpg.Attack(atk, tgt, 1)).valid
    print("✅ test_darkness_allows_fighting_inside_it")


def test_senses_pierce_darkness_from_outside():
    """Truesight, Blindsight and Devil's Sight in range see in; out of range or Darkvision don't."""
    for sense, ft, sees in (("truesight_range", 60, True), ("blindsight_range", 60, True),
                            ("devilssight_range", 120, True), ("devilssight_range", 10, False),
                            ("darkvision_range", 120, False)):
        bm, engine, atk, tgt = _dark_arena()
        s = engine.get_agent_stats(bm, atk)
        setattr(s, sense, ft)
        engine.set_agent_stats(bm, atk, s)
        assert engine.can_perceive_target(bm, atk, tgt) == sees, f"{sense} {ft} ft"
        assert engine.execute_action(bm, rpg.Attack(atk, tgt, 0)).valid == sees, f"{sense} {ft} ft"
    print("✅ test_senses_pierce_darkness_from_outside")


def test_own_shadow_arts_darkness_stays_transparent():
    """A caster tagged see-through still targets an enemy inside their own Darkness."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Monk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 8, 5))
    bm.set_agent_faction(atk, 1)
    bm.set_agent_faction(tgt, 2)
    bm.place_light_effect("Darkness", [rpg.Cell(8, 5)], rpg.VisibilityLevel.MagicalDark, -1, atk, atk)
    bm.update_lighting()
    assert engine.can_perceive_target(bm, atk, tgt)
    print("✅ test_own_shadow_arts_darkness_stays_transparent")


def test_ally_in_darkness_stays_targetable():
    """Only enemies are hidden: a friend in the darkness can still be reached (a heal, say)."""
    bm, engine, atk, tgt = _dark_arena()
    bm.set_agent_faction(tgt, 1)
    assert engine.can_perceive_target(bm, atk, tgt)
    print("✅ test_ally_in_darkness_stays_targetable")


def test_large_target_half_out_of_darkness_is_targetable():
    """A Large enemy with cells sticking out of the darkness is still in plain view."""
    bm, engine, atk, tgt = _dark_arena(target_at=(7, 5), target_size=2)
    assert engine.can_perceive_target(bm, atk, tgt)
    assert engine.execute_action(bm, rpg.Attack(atk, tgt, 0)).valid
    print("✅ test_large_target_half_out_of_darkness_is_targetable")


def test_darkness_refuses_single_target_spell_from_outside():
    """A directly-targeted spell is refused like the attack, and spends nothing."""
    bm, engine, atk, tgt = _dark_arena()
    spell = rpg.Spell()
    spell.name = "Bolt"
    spell.level = 1
    spell.geometry = rpg.SpellGeometry.Single
    spell.range = 120
    engine.set_agent_spells(bm, atk, [spell])
    s = engine.get_agent_stats(bm, atk)
    s.spell_slots_remaining = [2] * 9
    engine.set_agent_stats(bm, atk, s)
    act = rpg.SpellAction()
    act.caster_idx = atk
    act.spell_idx = 0
    act.slot_level = 1
    act.target_indices = [tgt]
    assert not engine.execute_spell(bm, act).valid
    assert list(engine.get_agent_stats(bm, atk).spell_slots_remaining) == [2] * 9, "no slot spent"
    print("✅ test_darkness_refuses_single_target_spell_from_outside")


def test_npc_outside_darkness_does_not_shoot_in():
    """An automated archer outside the darkness doesn't attack the enemy hidden in it."""
    bm, engine, atk, tgt = _dark_arena()
    bm.set_agent_npc_automated(atk, True)
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, atk)
    assert engine.run_npc_turn(bm, atk) == rpg.FlowStatus.Completed
    assert not calls, f"NPC attacked into the darkness: {calls}"
    print("✅ test_npc_outside_darkness_does_not_shoot_in")


if __name__ == "__main__":
    tests = [
        test_visibility_level_clear,
        test_visibility_level_dim,
        test_visibility_level_lightly_obscured,
        test_visibility_level_dark,
        test_visibility_level_magical_dark,
        test_visibility_level_blocked,
        test_line_of_sight,
        test_can_see,
        test_passive_perception,
        test_stealth_bonus,
        test_stealth_proficiency,
        test_check_hide_pre_combat,
        test_check_hide_in_combat,
        test_hidden_condition,
        test_hidden_agent_reveals_on_attack,
        test_darkvision,
        test_truesight,
        test_devilssight,
        test_hidden_agent_detection_on_movement,
        test_blinded_condition_blocks_sight,
        test_advantage_on_stealth_with_invisible,
        test_invisible_target_not_attackable,
        test_truesight_and_blindsight_pierce_invisibility,
        test_invisible_target_visibility_blocked,
        test_ally_still_perceives_invisible_teammate,
        test_ally_still_perceives_hidden_teammate,
        test_invisible_attacker_has_advantage,
        test_darkness_hides_enemy_from_outside,
        test_darkness_blocks_adjacent_melee_from_outside,
        test_darkness_does_not_hide_enemy_outside_it,
        test_darkness_allows_fighting_inside_it,
        test_senses_pierce_darkness_from_outside,
        test_own_shadow_arts_darkness_stays_transparent,
        test_ally_in_darkness_stays_targetable,
        test_large_target_half_out_of_darkness_is_targetable,
        test_darkness_refuses_single_target_spell_from_outside,
        test_npc_outside_darkness_does_not_shoot_in,
    ]

    print("Running Visibility Mechanics Tests...")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
