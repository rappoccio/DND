#!/usr/bin/env python3
"""
Test Warlock Phase 3a: Eldritch Blast invocations
- Eldritch Blast multi-beam (character-level scaling)
- Agonizing Blast (+CHA damage per beam)
- Repelling Blast (10 ft push per beam)
- Eldritch Mind (advantage on concentration saves)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import json
import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# Load spells from spells.json
def _load_spells():
    """Load spells from spells.json (as dictionaries)."""
    possible_paths = [
        os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "spells.json"),
        os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "..", "spells.json"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("spells.json not found")


_SPELLS = _load_spells()


def _get_eldritch_blast_spell_dict():
    """Get Eldritch Blast spell dictionary from spells.json."""
    for spell_dict in _SPELLS:
        if spell_dict.get("name") == "Eldritch Blast":
            return spell_dict
    raise AssertionError("Eldritch Blast not found in spells.json")


def _dict_to_spell(spell_dict):
    """Convert spell dictionary to rpg.Spell object."""
    spell = rpg.Spell()
    spell.name = spell_dict.get("name", "")
    spell.level = spell_dict.get("level", 0)
    spell.range = spell_dict.get("range", 0)
    spell.radius = spell_dict.get("radius", 0)
    spell.width = spell_dict.get("width", 0)
    spell.length = spell_dict.get("length", 0)
    spell.duration = spell_dict.get("duration", 0)
    spell.requires_concentration = spell_dict.get("requires_concentration", False)

    # Geometry
    geom_name = spell_dict.get("geometry", "Single")
    spell.geometry = getattr(rpg.SpellGeometry, geom_name, rpg.SpellGeometry.Single)

    # Attack type
    attack_name = spell_dict.get("attack_type", "Automatic")
    spell.attack_type = getattr(rpg.SpellAttack, attack_name, rpg.SpellAttack.Automatic)

    # Multiple geometry properties
    spell.num_targets = spell_dict.get("num_targets", 1)
    spell.targets_per_upcast_level = spell_dict.get("targets_per_upcast_level", 0)

    return spell


def _warlock_stats(level, cha=10, invocations=None):
    """Create a Warlock stats object with optional invocations."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    s.warlock_subclass = rpg.WarlockSubclass.Fiend
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    s.cha = cha
    s.spell_slots_remaining = list(s.spell_slots_max)
    if invocations:
        s.eldritch_invocations = list(invocations)
    return s


def test_beam_count_scaling():
    """Test that Eldritch Blast beams scale with character level."""
    engine = setup_combat_engine()
    spell_dict = _get_eldritch_blast_spell_dict()
    spell = _dict_to_spell(spell_dict)

    # L1: 1 beam
    result = engine.get_num_targets_for_spell(spell, 0, 1)
    assert result == 1, f"L1 should have 1 beam, got {result}"

    # L5: 2 beams
    result = engine.get_num_targets_for_spell(spell, 0, 5)
    assert result == 2, f"L5 should have 2 beams, got {result}"

    # L11: 3 beams
    result = engine.get_num_targets_for_spell(spell, 0, 11)
    assert result == 3, f"L11 should have 3 beams, got {result}"

    # L17: 4 beams
    result = engine.get_num_targets_for_spell(spell, 0, 17)
    assert result == 4, f"L17 should have 4 beams, got {result}"

    print("✅ test_beam_count_scaling passed")


def test_invocation_storage_roundtrip():
    """Test that eldritch_invocations can be saved and loaded."""
    engine = setup_combat_engine()
    bm = setup_battle_map()

    # Add a warlock
    warlock_config = rpg.AgentConfig()
    warlock_config.name = "Warlock"
    warlock_config.start_col = 5
    warlock_config.start_row = 5
    warlock_config.size = 1
    warlock_config.sprite_path = "test.png"

    engine.add_agent_config(bm, warlock_config)
    engine.apply_agent_configs(bm)
    warlock_idx = 0

    # Create stats with invocations [0, 2]
    warlock_stats = _warlock_stats(5, invocations=[0, 2])
    engine.set_agent_stats(bm, warlock_idx, warlock_stats)

    # Verify they round-trip
    stats = engine.get_agent_stats(bm, warlock_idx)
    assert len(stats.eldritch_invocations) == 2, f"Expected 2 invocations, got {len(stats.eldritch_invocations)}"
    assert stats.has_invocation(0), "Agonizing Blast (code 0) not found"
    assert stats.has_invocation(2), "Eldritch Spear (code 2) not found"
    assert not stats.has_invocation(1), "Repelling Blast (code 1) should not be present"
    assert not stats.has_invocation(3), "Eldritch Mind (code 3) should not be present"

    # Update invocations
    stats.eldritch_invocations = [1, 3]
    engine.set_agent_stats(bm, warlock_idx, stats)

    # Verify updated invocations
    stats_reloaded = engine.get_agent_stats(bm, warlock_idx)
    assert len(stats_reloaded.eldritch_invocations) == 2, f"Expected 2 invocations after update, got {len(stats_reloaded.eldritch_invocations)}"
    assert not stats_reloaded.has_invocation(0), "Agonizing Blast should not be present"
    assert stats_reloaded.has_invocation(1), "Repelling Blast (code 1) not found"
    assert not stats_reloaded.has_invocation(2), "Eldritch Spear should not be present"
    assert stats_reloaded.has_invocation(3), "Eldritch Mind (code 3) not found"

    print("✅ test_invocation_storage_roundtrip passed")


def _add_warlock(engine, bm, level, cha=10, dex=10, invocations=None):
    """Place a single Warlock on the map and return its index."""
    cfg = rpg.AgentConfig()
    cfg.name = "Warlock"
    cfg.start_col = 5
    cfg.start_row = 5
    cfg.size = 1
    cfg.sprite_path = "test.png"
    engine.add_agent_config(bm, cfg)
    engine.apply_agent_configs(bm)
    idx = 0
    s = _warlock_stats(level, cha=cha, invocations=invocations)
    s.dex = dex
    engine.set_agent_stats(bm, idx, s)
    return idx


def test_armor_of_shadows_ac():
    """Armor of Shadows (code 5): unarmored AC = 13 + DEX, no slot, always on."""
    # DEX 16 (+3) → Mage Armor AC 16; without the invocation → base AC.
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, dex=16, invocations=[5])
    ac = engine.calculate_ac(bm, idx)
    assert ac == 16, f"Armor of Shadows: expected AC 13+3=16, got {ac}"

    # Control: same warlock without the invocation must NOT get 13+DEX.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, dex=16, invocations=[])
    ac2 = engine2.calculate_ac(bm2, idx2)
    assert ac2 != 16, f"No invocation should not yield Mage Armor AC, got {ac2}"

    print("✅ test_armor_of_shadows_ac passed")


def test_fiendish_vigor_temp_hp():
    """Fiendish Vigor (code 6): max False Life (2d4+4 = 12) temp HP on first turn."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[6])
    assert engine.get_agent_stats(bm, idx).temp_hp == 0, "should start with 0 temp HP"
    engine.begin_turn(bm, idx)
    assert engine.get_agent_stats(bm, idx).temp_hp == 12, \
        f"Fiendish Vigor: expected 12 temp HP, got {engine.get_agent_stats(bm, idx).temp_hp}"

    # Control: no invocation → no temp HP granted.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    engine2.begin_turn(bm2, idx2)
    assert engine2.get_agent_stats(bm2, idx2).temp_hp == 0, "no invocation = no temp HP"

    print("✅ test_fiendish_vigor_temp_hp passed")


def test_devils_sight_vision():
    """Devil's Sight (code 4): materialize devilssight_range = 120 ft (see in dark)."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[4])
    assert engine.get_agent_stats(bm, idx).devilssight_range == 120, \
        f"Devil's Sight: expected devilssight_range 120, got {engine.get_agent_stats(bm, idx).devilssight_range}"

    # Control: no invocation → no devil's sight.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    assert engine2.get_agent_stats(bm2, idx2).devilssight_range == 0, "no invocation = no devil's sight"

    print("✅ test_devils_sight_vision passed")


def test_eldritch_spear_range():
    """Eldritch Spear (code 2): EB range += 30 ft x Warlock level."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[2])
    eb = _dict_to_spell(_get_eldritch_blast_spell_dict())
    base = eb.range
    eff = engine.effective_spell_range(bm, idx, eb)
    assert eff == base + 30 * 5, f"Eldritch Spear L5: expected {base + 150}, got {eff}"

    # Control: no invocation → unchanged range.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    assert engine2.effective_spell_range(bm2, idx2, eb) == base, "no invocation = base range"

    print("✅ test_eldritch_spear_range passed")


def test_witch_sight_truesight():
    """Witch Sight (code 7): materialize truesight_range = 30 ft."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=15, invocations=[7])
    assert engine.get_agent_stats(bm, idx).truesight_range == 30, \
        f"Witch Sight: expected truesight_range 30, got {engine.get_agent_stats(bm, idx).truesight_range}"

    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=15, invocations=[])
    assert engine2.get_agent_stats(bm2, idx2).truesight_range == 0, "no invocation = no truesight"

    print("✅ test_witch_sight_truesight passed")


def test_gift_of_the_depths_swim():
    """Gift of the Depths (code 11): swim speed becomes equal to walk speed."""
    engine = setup_combat_engine()
    bm = setup_battle_map()
    idx = _add_warlock(engine, bm, level=5, invocations=[11])
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = 30
    s.speed_swim = 0
    engine.set_agent_stats(bm, idx, s)
    out = engine.get_agent_stats(bm, idx)
    assert out.speed_swim == 30, f"Gift of the Depths: expected swim 30, got {out.speed_swim}"

    # Control: no invocation → swim stays 0.
    engine2 = setup_combat_engine()
    bm2 = setup_battle_map()
    idx2 = _add_warlock(engine2, bm2, level=5, invocations=[])
    s2 = engine2.get_agent_stats(bm2, idx2)
    s2.speed_walk = 30
    s2.speed_swim = 0
    engine2.set_agent_stats(bm2, idx2, s2)
    assert engine2.get_agent_stats(bm2, idx2).speed_swim == 0, "no invocation = no swim grant"

    print("✅ test_gift_of_the_depths_swim passed")


def _alter_self_claws():
    """Guaranteed-hit AlterSelfClaws (1d6) for combat-path testing."""
    w = rpg.Weapon()
    w.name = "AlterSelfClaws"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.finesse = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 6
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_master_of_myriad_forms_claws_attack():
    """Master of Myriad Forms (code 12): the AlterSelfClaws 1d6 natural weapon
    is a valid combat attack (mirrors the MonkUnarmed named-weapon pattern)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    s = _warlock_stats(5, invocations=[12])
    s.dex = 16
    engine.set_agent_stats(bm, atk, s)
    engine.set_agent_weapons(bm, atk, _alter_self_claws())
    engine.begin_turn(bm, atk)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit, "AlterSelfClaws attack should hit"
    assert result.total_damage >= 1, f"expected positive claw damage, got {result.total_damage}"
    print("✅ test_master_of_myriad_forms_claws_attack passed")


def test_otherworldly_leap_jump():
    """Otherworldly Leap (code 10): triples jump distance (STR-based)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    s = _warlock_stats(5, invocations=[10])
    s.str = 10           # standing jump base = STR/2 = 5 ft
    s.speed_walk = 30
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(30)   # seed the Agent's walk budget (GUI does this)
    # 2 cells = 10 ft standing jump: > base 5 ft but <= tripled 15 ft → allowed.
    assert engine.jump_agent(bm, idx, rpg.Cell(7, 5), False), \
        "Otherworldly Leap should allow a 10 ft standing jump (base 5 ft x3 = 15 ft)"

    # Control: identical setup without the invocation → 10 ft > 5 ft base → fails on range.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    idx2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    s2 = _warlock_stats(5, invocations=[])
    s2.str = 10
    s2.speed_walk = 30
    engine2.set_agent_stats(bm2, idx2, s2)
    engine2.begin_turn(bm2, idx2)
    bm2.placed_agents[idx2].init_movement(30)   # ample budget, so only RANGE gates the jump
    assert not engine2.jump_agent(bm2, idx2, rpg.Cell(7, 5), False), \
        "Without the invocation a 10 ft standing jump (base 5 ft) should fail on range"
    # Sanity: a 5 ft jump (= base) IS allowed without the invocation (budget isn't the blocker).
    assert engine2.jump_agent(bm2, idx2, rpg.Cell(6, 5), False), \
        "Base 5 ft standing jump should succeed (budget seeded; range allows 5 ft)"

    print("✅ test_otherworldly_leap_jump passed")


def test_jump_clears_chasm_but_not_walls():
    """Jump ignores Chasm/Water terrain but is blocked by walls (MovementType.Jump)."""
    # Chasm in the path: a 2-cell jump over a chasm cell SUCCEEDS.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Jumper", 5, 5))
    s = rpg.Stats(); s.str = 20; s.speed_walk = 30  # base running/standing jump easily covers 10 ft
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(30)
    bm.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Chasm)   # gap between (5,5) and (7,5)
    assert engine.jump_agent(bm, idx, rpg.Cell(7, 5), True), \
        "Jump should clear a Chasm in the path"

    # Wall in the path: the same jump is BLOCKED.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    idx2 = add_agent_to_battle(engine2, bm2, create_test_agent("Jumper", 5, 5))
    s2 = rpg.Stats(); s2.str = 20; s2.speed_walk = 30
    engine2.set_agent_stats(bm2, idx2, s2)
    engine2.begin_turn(bm2, idx2)
    bm2.placed_agents[idx2].init_movement(30)
    bm2.set_terrain_type(rpg.Cell(6, 5), rpg.TerrainType.Wall)   # wall between (5,5) and (7,5)
    assert not engine2.jump_agent(bm2, idx2, rpg.Cell(7, 5), True), \
        "Jump should be blocked by a wall in the path"

    print("✅ test_jump_clears_chasm_but_not_walls passed")


def _invis_spell(name, cond_name):
    sp = rpg.Spell()
    sp.name = name
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Single
    sp.duration = 10
    c = rpg.AttackCondition()
    c.condition_name = cond_name
    c.condition_duration = 0
    c.requires_save = False
    sp.conditions = [c]
    return sp


def test_one_with_shadows():
    """One with Shadows (code 8): free Invisibility while in Dim Light/Darkness."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    engine.set_agent_stats(bm, idx, _warlock_stats(5, invocations=[8]))
    # Bright light → cannot.
    assert not engine.apply_one_with_shadows(bm, idx), "should fail in bright light"
    assert not bm.placed_agents[idx].conditions.invisible
    # Darkness → becomes invisible.
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert engine.apply_one_with_shadows(bm, idx), "should succeed in darkness"
    assert bm.placed_agents[idx].conditions.invisible, "should gain the Invisible condition"
    # Control: no invocation → fails even in darkness.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    idx2 = add_agent_to_battle(engine2, bm2, create_test_agent("W", 5, 5))
    engine2.set_agent_stats(bm2, idx2, _warlock_stats(5, invocations=[]))
    bm2.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert not engine2.apply_one_with_shadows(bm2, idx2), "no invocation 8 → no invisibility"
    print("✅ test_one_with_shadows passed")


def test_invisibility_spell_grants_and_breaks():
    """Invisibility spell grants the Invisible condition; it ends after the target attacks."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    engine.set_agent_spells(bm, caster, [_invis_spell("Invisibility", "Invisible")])
    engine.set_agent_weapons(bm, caster, _alter_self_claws())
    act = rpg.SpellAction()
    act.caster_idx = caster
    act.spell_idx = 0
    act.target_indices = [caster]
    engine.execute_spell(bm, act)
    assert bm.placed_agents[caster].conditions.invisible, "Invisibility should grant invisibility"
    # Attacking ends it.
    engine.begin_turn(bm, caster)
    engine.execute_action(bm, rpg.Attack(caster, foe, 0))
    assert not bm.placed_agents[caster].conditions.invisible, "Invisibility ends after attacking"
    print("✅ test_invisibility_spell_grants_and_breaks passed")


def test_greater_invisibility_persists_through_attack():
    """Greater Invisibility does NOT end when the target attacks."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    engine.set_agent_spells(bm, caster, [_invis_spell("Greater Invisibility", "GreaterInvisible")])
    engine.set_agent_weapons(bm, caster, _alter_self_claws())
    act = rpg.SpellAction()
    act.caster_idx = caster
    act.spell_idx = 0
    act.target_indices = [caster]
    engine.execute_spell(bm, act)
    assert bm.placed_agents[caster].conditions.invisible, "Greater Invisibility should grant invisibility"
    engine.begin_turn(bm, caster)
    engine.execute_action(bm, rpg.Attack(caster, foe, 0))
    assert bm.placed_agents[caster].conditions.invisible, "Greater Invisibility persists through attacks"
    print("✅ test_greater_invisibility_persists_through_attack passed")


# ── Pact of the Blade family ─────────────────────────────────────────────────

def _pact_blade(die_size=1):
    """A guaranteed-hit pact weapon (pact_weapon=True) for combat-path testing. die_size=1 makes
    the weapon die deterministic (roll(1)==1) so damage = 1 + ability-mod is exact."""
    w = rpg.Weapon()
    w.name = "PactBlade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.pact_weapon = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = die_size
    w.physical_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_pact_blade_uses_charisma():
    """Pact of the Blade: the pact weapon uses CHA for damage (and attack) — modeled as the best of
    STR/DEX/CHA, never worse. With STR=DEX=10 (mod 0), CHA=20 (mod +5), a 1d1 pact weapon deals
    1 + 5 = 6; the same weapon without pact_weapon deals just 1."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    s = _warlock_stats(1, cha=20, invocations=[13])
    s.str = 10
    s.dex = 10
    engine.set_agent_stats(bm, atk, s)
    engine.set_agent_weapons(bm, atk, _pact_blade())
    engine.begin_turn(bm, atk)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit, "pact blade should hit"
    assert result.total_damage == 6, f"expected 1(die) + 5(CHA) = 6, got {result.total_damage}"

    # Control: identical weapon but NOT a pact weapon → no CHA, damage = 1 + 0.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    a2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    t2 = add_agent_to_battle(engine2, bm2, create_test_agent("Dummy", 6, 5))
    s2 = _warlock_stats(1, cha=20, invocations=[])
    s2.str = 10
    s2.dex = 10
    engine2.set_agent_stats(bm2, a2, s2)
    wlist = _pact_blade()
    wlist[0].pact_weapon = False
    engine2.set_agent_weapons(bm2, a2, wlist)
    engine2.begin_turn(bm2, a2)
    r2 = engine2.execute_action(bm2, rpg.Attack(a2, t2, 0))
    assert r2.total_damage == 1, f"control (no pact) expected 1, got {r2.total_damage}"
    print("✅ test_pact_blade_uses_charisma passed")


def test_thirsting_blade_extra_attack():
    """Thirsting Blade (14, L5+, requires Pact of the Blade): grants a 2nd attack (num_attacks=2).
    Invocations must be set BEFORE initialize_class_resources (as the GUI does in _on_stats_ok)."""
    def _make(level, invocations):
        s = rpg.Stats()
        s.set_class_level(rpg.CharacterClass.Warlock, level)
        s.eldritch_invocations = list(invocations)
        s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
        return s

    assert _make(5, [13, 14]).num_attacks == 2, "L5 Pact-of-the-Blade + Thirsting Blade → 2 attacks"
    assert _make(5, [14]).num_attacks == 1, "Thirsting Blade without Pact of the Blade → no extra attack"
    assert _make(4, [13, 14]).num_attacks == 1, "Thirsting Blade requires L5"
    assert _make(5, [13]).num_attacks == 1, "Pact of the Blade alone → no extra attack"
    # Devouring Blade (17, L12+, needs Thirsting Blade): the extra attack becomes two → 3 total.
    assert _make(12, [13, 14, 17]).num_attacks == 3, "L12 Devouring Blade → 3 attacks"
    assert _make(11, [13, 14, 17]).num_attacks == 2, "Devouring Blade requires L12 (else just Thirsting Blade)"
    assert _make(12, [13, 17]).num_attacks == 1, "Devouring Blade without Thirsting Blade → no extra attack"
    print("✅ test_thirsting_blade_extra_attack passed")


def test_eldritch_smite():
    """Eldritch Smite (15, L5+): a pact-weapon hit can expend a pact slot for (slot+1)d8 Force and
    knock the target Prone. L5 pact slot level = 3 → 4d8 Force."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), hp=200)  # survive the smite to check Prone
    s = _warlock_stats(5, cha=18, invocations=[13, 15])
    engine.set_agent_stats(bm, atk, s)
    engine.set_agent_weapons(bm, atk, _pact_blade())
    engine.begin_turn(bm, atk)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    cond = engine.get_agent_conditions(bm, atk)
    assert cond.eldritch_smite_available, "pact-weapon hit should flag Eldritch Smite eligible"

    psl = engine.get_agent_stats(bm, atk).pact_slot_level()
    assert psl == 3, f"L5 Warlock pact slot level should be 3, got {psl}"
    slots_before = engine.get_agent_stats(bm, atk).spell_slots_remaining[psl - 1]
    dmg_before = result.total_damage
    force = engine.apply_eldritch_smite_effect(bm, atk, tgt, psl, result)
    assert force > 0, f"Eldritch Smite should add Force damage, got {force}"
    assert result.total_damage == dmg_before + force, "smite damage should add to the result"
    slots_after = engine.get_agent_stats(bm, atk).spell_slots_remaining[psl - 1]
    assert slots_after == slots_before - 1, "Eldritch Smite should spend one pact slot"
    assert engine.get_agent_conditions(bm, atk).eldritch_smite_used, "once-per-turn flag should be set"
    assert engine.get_agent_conditions(bm, tgt).prone, "Huge-or-smaller target should be knocked Prone"

    # A second smite the same turn is rejected (once per turn).
    assert engine.apply_eldritch_smite_effect(bm, atk, tgt, psl, result) == -1, \
        "Eldritch Smite is once per turn"
    print("✅ test_eldritch_smite passed")


def test_eldritch_smite_requires_pact_weapon():
    """Eldritch Smite is not offered for a non-pact weapon."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    s = _warlock_stats(5, cha=18, invocations=[13, 15])
    engine.set_agent_stats(bm, atk, s)
    engine.set_agent_weapons(bm, atk, _alter_self_claws())  # NOT a pact weapon
    engine.begin_turn(bm, atk)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert not engine.get_agent_conditions(bm, atk).eldritch_smite_available, \
        "Eldritch Smite should require the pact weapon"
    print("✅ test_eldritch_smite_requires_pact_weapon passed")


def test_lifedrinker():
    """Lifedrinker (16, L9+): a pact-weapon hit deals extra Necrotic = max(1, CHA mod) and grants the
    Warlock that many temp HP, once per turn. With CHA 20 (+5): 1(die) + 5(CHA dmg) + 5(necrotic) = 11,
    and the Warlock gains 5 temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    # High-HP target so it survives the hit — otherwise the (Fiend) Warlock's Dark One's Blessing
    # would fire on the kill and override Lifedrinker's temp HP, which is what we're isolating here.
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), hp=200)
    s = _warlock_stats(9, cha=20, invocations=[13, 16])
    s.str = 10
    s.dex = 10
    engine.set_agent_stats(bm, atk, s)
    engine.set_agent_weapons(bm, atk, _pact_blade())
    engine.begin_turn(bm, atk)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert result.total_damage == 11, f"expected 1 + 5(CHA) + 5(Lifedrinker) = 11, got {result.total_damage}"
    assert engine.get_agent_stats(bm, atk).temp_hp == 5, "Warlock should gain CHA-mod temp HP"
    assert engine.get_agent_conditions(bm, atk).lifedrinker_used, "once-per-turn flag should be set"

    # Control: no invocation 16 → no necrotic bonus, no temp HP (just 1 + 5 CHA = 6).
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    a2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    t2 = add_agent_to_battle(engine2, bm2, create_test_agent("Dummy", 6, 5))
    s2 = _warlock_stats(9, cha=20, invocations=[13])
    s2.str = 10
    s2.dex = 10
    engine2.set_agent_stats(bm2, a2, s2)
    engine2.set_agent_weapons(bm2, a2, _pact_blade())
    engine2.begin_turn(bm2, a2)
    r2 = engine2.execute_action(bm2, rpg.Attack(a2, t2, 0))
    assert r2.total_damage == 6, f"control expected 6, got {r2.total_damage}"
    assert engine2.get_agent_stats(bm2, a2).temp_hp == 0, "control should gain no temp HP"
    print("✅ test_lifedrinker passed")


def test_pact_of_chain_invocation_storage():
    """Pact of the Chain (18) + Investment of the Chain Master (19) round-trip in storage."""
    s = _warlock_stats(5, cha=16, invocations=[18, 19])
    assert s.has_invocation(18), "Pact of the Chain (18) not stored"
    assert s.has_invocation(19), "Investment of the Chain Master (19) not stored"
    assert not s.has_invocation(20), "Pact of the Tome (20) should not be present"
    print("✅ test_pact_of_chain_invocation_storage passed")


def test_pact_familiar_summon_link_and_dismiss():
    """The engine machinery the GUI _summon_familiar relies on: spawn a familiar, link it to the
    Warlock with the 'Pact Familiar' tag, then tombstone-dismiss it (indices stay valid)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    cfg = rpg.AgentConfig()
    cfg.name = "Imp"; cfg.start_col = 6; cfg.start_row = 6; cfg.size = 1; cfg.sprite_path = "x.png"
    fam = bm.spawn_agent(cfg)
    assert fam >= 0, "familiar spawn should succeed on an open cell"
    bm.set_agent_summoner_idx(fam, wl)
    bm.set_agent_summon_spell(fam, "Pact Familiar")
    assert bm.placed_agents[fam].summoner_idx == wl
    assert bm.placed_agents[fam].summon_spell == "Pact Familiar"
    assert not bm.is_agent_removed_from_play(fam), "familiar should start live"
    # Dismiss = tombstone (never erase, so the Warlock's index stays valid).
    bm.set_agent_removed_from_play(fam, True)
    assert bm.is_agent_removed_from_play(fam), "dismissed familiar should be tombstoned"
    assert bm.placed_agents[wl].name == "Warlock", "summoner index must survive dismissal"
    print("✅ test_pact_familiar_summon_link_and_dismiss passed")


def test_pact_chain_familiar_forms_in_bestiary():
    """All six 2024 Pact of the Chain familiar forms exist as engine-ready bestiary records."""
    path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "DND2024_MonsterStats.json")
    with open(path) as f:
        bestiary = json.load(f)
    keys = set(bestiary.keys()) if isinstance(bestiary, dict) \
        else {r.get("name") for r in bestiary}
    for form in ["Imp", "Pseudodragon", "Quasit", "Sprite", "Skeleton", "Venomous Snake"]:
        assert form in keys, f"Pact familiar form '{form}' missing from the bestiary"
    print("✅ test_pact_chain_familiar_forms_in_bestiary passed")


if __name__ == '__main__':
    test_beam_count_scaling()
    test_invocation_storage_roundtrip()
    test_armor_of_shadows_ac()
    test_fiendish_vigor_temp_hp()
    test_devils_sight_vision()
    test_eldritch_spear_range()
    test_witch_sight_truesight()
    test_gift_of_the_depths_swim()
    test_master_of_myriad_forms_claws_attack()
    test_otherworldly_leap_jump()
    test_jump_clears_chasm_but_not_walls()
    test_one_with_shadows()
    test_invisibility_spell_grants_and_breaks()
    test_greater_invisibility_persists_through_attack()
    test_pact_blade_uses_charisma()
    test_thirsting_blade_extra_attack()
    test_eldritch_smite()
    test_eldritch_smite_requires_pact_weapon()
    test_lifedrinker()
    test_pact_of_chain_invocation_storage()
    test_pact_familiar_summon_link_and_dismiss()
    test_pact_chain_familiar_forms_in_bestiary()
    print("\n✅ All Warlock Phase 3 tests passed!")
