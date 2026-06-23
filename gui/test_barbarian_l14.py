#!/usr/bin/env python3
"""
Barbarian L14 subclass capstones (2024 PHB):
  • Berserker  — Intimidating Presence (relabeled to L14) + L10 Retaliation reaction
  • Wild Heart — Power of the Wilds: Falcon (fly) / Lion (disadvantage aura) / Ram (prone)
  • World Tree — Travel along the Tree (60-ft / once-per-Rage 150-ft teleport)
  • Zealot     — Rage of the Gods (divine form: fly+hover, resistances, Revivification)

NOTE: add_agent_to_battle() calls apply_agent_configs(), which rebuilds every placed agent
from scratch and wipes runtime state. So each test adds ALL agents first, THEN configures.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle, create_melee_weapon)

# MagicDamage_t indices (match agent_loader ordering)
NECROTIC, PSYCHIC, RADIANT = 5, 7, 8


def _config_barbarian(engine, bm, idx, level, subclass, *, str_=18, give_weapon=True):
    stats = engine.get_agent_stats(bm, idx)
    stats.character_class = rpg.CharacterClass.Barbarian
    stats.char_level = level
    stats.barbarian_subclass = subclass
    stats.str = str_
    stats.speed_walk = 30
    stats.initialize_class_resources(rpg.CharacterClass.Barbarian, level)
    engine.set_agent_stats(bm, idx, stats)
    if give_weapon:
        w = create_melee_weapon(); w.proficient = True
        engine.set_agent_weapons(bm, idx, [w, create_melee_weapon(), create_melee_weapon()])
    return idx


def _arm(engine, bm, idx):
    w = create_melee_weapon(); w.proficient = True
    engine.set_agent_weapons(bm, idx, [w, create_melee_weapon(), create_melee_weapon()])


# ── Berserker relabel: Intimidating Presence is now L14 (not L10) ──────────────

def test_intimidating_presence_requires_l14():
    # L13 — not yet available.
    bm = setup_battle_map(); engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 13, rpg.BarbianSubclass.Berserker)
    assert not engine.use_intimidating_presence(bm, barb), \
        "Intimidating Presence must NOT be available at L13 (it is the L14 feature)"

    # L14 — now available.
    bm = setup_battle_map(); engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Enemy", 6, 5))
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.Berserker)
    assert engine.use_intimidating_presence(bm, barb), "Intimidating Presence should work at L14"
    print("✅ test_intimidating_presence_requires_l14 passed")


# ── Berserker L10 Retaliation ─────────────────────────────────────────────────

def test_retaliation_flagged_on_adjacent_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5), hp=200, ac=1)
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 6, 5), hp=100, ac=10, str=18)
    _config_barbarian(engine, bm, barb, 10, rpg.BarbianSubclass.Berserker)
    _arm(engine, bm, atk)

    res = engine.execute_action(bm, rpg.Attack(atk, barb, 0))
    assert res.hit, "setup expects the attacker to hit the AC-1 Berserker"

    cond = engine.get_agent_conditions(bm, barb)
    assert cond.retaliation_available, "Retaliation should be offered after an adjacent hit"
    assert cond.retaliation_target_idx == atk, "Retaliation target should be the attacker"

    engine.apply_retaliation(bm, barb)
    assert engine.get_agent_conditions(bm, barb).reaction_used, "Retaliation should spend the reaction"
    assert not engine.get_agent_conditions(bm, barb).retaliation_available, "flag cleared after use"
    print("✅ test_retaliation_flagged_on_adjacent_hit passed")


def test_retaliation_not_flagged_when_not_adjacent():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5), hp=200, ac=1)
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 9, 5), hp=100, ac=10, str=18)
    _config_barbarian(engine, bm, barb, 10, rpg.BarbianSubclass.Berserker)
    _arm(engine, bm, atk)

    engine.execute_action(bm, rpg.Attack(atk, barb, 0))  # 20 ft away — out of melee reach
    assert not engine.get_agent_conditions(bm, barb).retaliation_available, \
        "Retaliation must not trigger from more than 5 ft away"
    print("✅ test_retaliation_not_flagged_when_not_adjacent passed")


# ── Wild Heart L14 Power of the Wilds: Falcon ────────────────────────────────

def test_falcon_grants_fly_while_raging():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WildHeart)
    stats = engine.get_agent_stats(bm, barb)
    stats.wild_heart_power = rpg.WildHeartPower.Falcon
    engine.set_agent_stats(bm, barb, stats)

    assert engine.get_agent_stats(bm, barb).speed_fly == 0, "no fly speed before raging"
    engine.activate_rage(bm, barb)
    after = engine.get_agent_stats(bm, barb)
    assert after.speed_walk > 0 and after.speed_fly == after.speed_walk, \
        f"Falcon: fly should equal walk ({after.speed_walk}) while raging, got {after.speed_fly}"
    engine.end_rage(bm, barb)
    assert engine.get_agent_stats(bm, barb).speed_fly == 0, "Falcon fly speed ends with the Rage"
    print("✅ test_falcon_grants_fly_while_raging passed")


# ── Wild Heart L14 Power of the Wilds: Lion ──────────────────────────────────

def test_lion_aura_flag_lifecycle():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WildHeart)
    stats = engine.get_agent_stats(bm, barb)
    stats.wild_heart_power = rpg.WildHeartPower.Lion
    engine.set_agent_stats(bm, barb, stats)

    engine.activate_rage(bm, barb)
    assert engine.get_agent_conditions(bm, barb).lion_aura_active, "Lion aura active while raging"
    engine.end_rage(bm, barb)
    assert not engine.get_agent_conditions(bm, barb).lion_aura_active, "Lion aura ends with the Rage"
    print("✅ test_lion_aura_flag_lifecycle passed")


def test_lion_imposes_disadvantage_on_attacks_elsewhere():
    bm = setup_battle_map(); engine = setup_combat_engine()
    # Lion barbarian (team 1) adjacent to an enemy attacker (team 2). The attacker swings at a
    # different creature (team 1 ally) → Disadvantage. Then it swings at the Lion itself → no penalty.
    lion = add_agent_to_battle(engine, bm, create_test_agent("Lion", 5, 5), ac=10)
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 6, 5), hp=100, ac=10, str=18)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 7, 5), hp=100, ac=1)

    _config_barbarian(engine, bm, lion, 14, rpg.BarbianSubclass.WildHeart)
    stats = engine.get_agent_stats(bm, lion)
    stats.wild_heart_power = rpg.WildHeartPower.Lion
    engine.set_agent_stats(bm, lion, stats)
    _arm(engine, bm, atk)
    bm.set_agent_faction(lion, 1); bm.set_agent_faction(ally, 1); bm.set_agent_faction(atk, 2)

    engine.activate_rage(bm, lion)

    r_other = engine.execute_action(bm, rpg.Attack(atk, ally, 0))
    assert r_other.disadvantage, "attacking someone other than the adjacent Lion has Disadvantage"

    r_lion = engine.execute_action(bm, rpg.Attack(atk, lion, 0))
    assert not r_lion.disadvantage, "attacking the Lion itself is not hampered"
    print("✅ test_lion_imposes_disadvantage_on_attacks_elsewhere passed")


# ── Wild Heart L14 Power of the Wilds: Ram ───────────────────────────────────

def test_ram_knocks_prone_on_melee_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 6, 5), hp=500, ac=1)
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WildHeart)
    stats = engine.get_agent_stats(bm, barb)
    stats.wild_heart_power = rpg.WildHeartPower.Ram
    engine.set_agent_stats(bm, barb, stats)

    engine.activate_rage(bm, barb)
    res = engine.execute_action(bm, rpg.Attack(barb, tgt, 0))
    assert res.hit, "setup expects the Ram barbarian to hit the AC-1 target"
    assert engine.get_agent_conditions(bm, tgt).prone, "Ram knocks a Medium target Prone on a melee hit"
    print("✅ test_ram_knocks_prone_on_melee_hit passed")


# ── World Tree L14 Travel along the Tree ─────────────────────────────────────

def test_travel_along_tree_teleports():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WorldTree)
    engine.begin_turn(bm, barb)
    engine.activate_rage(bm, barb)
    assert engine.travel_along_tree(bm, barb, 8, 5, False), "60-ft teleport within range should succeed"
    assert bm.placed_agents[barb].origin.col == 8, "barbarian should have teleported to col 8"
    print("✅ test_travel_along_tree_teleports passed")


def test_travel_long_range_once_per_rage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WorldTree)
    engine.begin_turn(bm, barb)
    engine.activate_rage(bm, barb)

    assert engine.travel_along_tree(bm, barb, 8, 5, True), "first long-range hop should succeed"
    assert engine.get_agent_conditions(bm, barb).world_tree_long_teleport_used, "flag set after long hop"

    engine.begin_turn(bm, barb)  # refresh the bonus action (does NOT reset the once-per-Rage flag)
    assert not engine.travel_along_tree(bm, barb, 2, 5, True), \
        "the 150-ft upgrade is once per Rage — second long hop must fail"
    print("✅ test_travel_long_range_once_per_rage passed")


# ── Zealot L14 Rage of the Gods ──────────────────────────────────────────────

def test_rage_of_the_gods_grants_form():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.Zealot)
    engine.activate_rage(bm, barb)
    assert engine.activate_rage_of_the_gods(bm, barb), "Rage of the Gods should activate while raging"

    cond = engine.get_agent_conditions(bm, barb)
    stats = engine.get_agent_stats(bm, barb)
    assert cond.rage_of_gods_active, "divine form flag set"
    assert stats.rage_of_gods_used, "marked used (once per long rest)"
    assert stats.speed_walk > 0 and stats.speed_fly == stats.speed_walk, \
        f"form grants fly = walk ({stats.speed_walk}), got {stats.speed_fly}"
    for t in (NECROTIC, PSYCHIC, RADIANT):
        assert stats.get_magic_damage_multiplier(t) == 0.5, f"resistance to type {t}"

    assert not engine.activate_rage_of_the_gods(bm, barb), "cannot reuse before a long rest"

    engine.end_rage(bm, barb)
    cond = engine.get_agent_conditions(bm, barb); stats = engine.get_agent_stats(bm, barb)
    assert not cond.rage_of_gods_active, "form ends with the Rage"
    assert stats.speed_fly == 0, "fly speed cleared"
    for t in (NECROTIC, PSYCHIC, RADIANT):
        assert stats.get_magic_damage_multiplier(t) == 1.0, f"resistance cleared for type {t}"
    print("✅ test_rage_of_the_gods_grants_form passed")


def test_rage_of_gods_resets_on_long_rest():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.Zealot)
    engine.activate_rage(bm, barb)
    engine.activate_rage_of_the_gods(bm, barb)
    engine.end_rage(bm, barb)
    assert engine.get_agent_stats(bm, barb).rage_of_gods_used, "used flag set until a rest"
    engine.apply_long_rest(bm)
    assert not engine.get_agent_stats(bm, barb).rage_of_gods_used, "long rest restores the feature"
    print("✅ test_rage_of_gods_resets_on_long_rest passed")


def test_revivification_saves_nearby_creature():
    bm = setup_battle_map(); engine = setup_combat_engine()
    zealot = add_agent_to_battle(engine, bm, create_test_agent("Zealot", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5), hp=10)
    _config_barbarian(engine, bm, zealot, 14, rpg.BarbianSubclass.Zealot)

    engine.activate_rage(bm, zealot)
    engine.activate_rage_of_the_gods(bm, zealot)
    rage_before = engine.get_agent_stats(bm, zealot).get_resource("Rage").current

    engine.damage_agent(bm, ally, 100)  # would drop to 0

    ally_stats = engine.get_agent_stats(bm, ally)
    assert ally_stats.hp_cur == 14, f"Revivification sets HP to the Zealot's level (14), got {ally_stats.hp_cur}"
    z_cond = engine.get_agent_conditions(bm, zealot)
    z_rage = engine.get_agent_stats(bm, zealot).get_resource("Rage").current
    assert z_cond.reaction_used, "Revivification spends the Zealot's reaction"
    assert z_rage == rage_before - 1, "Revivification expends one Rage use"
    print("✅ test_revivification_saves_nearby_creature passed")


def test_save_load_fields_settable():
    """The new persisted Stats fields are bound and round-trip through the engine."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    _config_barbarian(engine, bm, barb, 14, rpg.BarbianSubclass.WildHeart)
    stats = engine.get_agent_stats(bm, barb)
    stats.wild_heart_power = rpg.WildHeartPower.Ram
    stats.rage_of_gods_used = True
    engine.set_agent_stats(bm, barb, stats)
    rt = engine.get_agent_stats(bm, barb)
    assert rt.wild_heart_power == rpg.WildHeartPower.Ram, "wild_heart_power persists"
    assert rt.rage_of_gods_used, "rage_of_gods_used persists"
    print("✅ test_save_load_fields_settable passed")


if __name__ == "__main__":
    test_intimidating_presence_requires_l14()
    test_retaliation_flagged_on_adjacent_hit()
    test_retaliation_not_flagged_when_not_adjacent()
    test_falcon_grants_fly_while_raging()
    test_lion_aura_flag_lifecycle()
    test_lion_imposes_disadvantage_on_attacks_elsewhere()
    test_ram_knocks_prone_on_melee_hit()
    test_travel_along_tree_teleports()
    test_travel_long_range_once_per_rage()
    test_rage_of_the_gods_grants_form()
    test_rage_of_gods_resets_on_long_rest()
    test_revivification_saves_nearby_creature()
    test_save_load_fields_settable()
    print("\n✅ All L14 Barbarian tests passed!")
