#!/usr/bin/env python3
"""
Test the NPC attack analysis (pre-attack probability report).

npc_analyze_attack / npc_save_chance / npc_spell_hit_chance are pure probability
queries over the engine's own to-hit / damage / save math — no dice are rolled and
nothing mutates. The automated executors log them as "Analysis:" combat-log lines;
these tests verify the math against hand-computed values.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

EPS = 1e-9


def _place(engine, bm, name, col, row, faction, hp=10):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=hp)
    bm.set_agent_faction(idx, faction)
    return idx


def _arm(engine, bm, idx, bonus_hit=0, num_dice=1, die_size=6, bonus_damage=0,
         no_crit=True):
    """A melee weapon with an explicit 1-group physical damage roll. no_crit lifts the
    crit threshold above 20 so hand-computed probabilities stay clean fractions."""
    w = rpg.Weapon()
    w.name = "Testblade"
    w.type = rpg.WeaponType.Melee
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = num_dice
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    w.bonus_hit = bonus_hit
    w.bonus_damage = bonus_damage
    engine.set_agent_weapons(bm, idx, [w, rpg.Weapon(), rpg.Weapon()])
    if no_crit:
        s = engine.get_agent_stats(bm, idx)
        s.crit_threshold = 21          # a natural 20 is a plain hit → exact fractions
        engine.set_agent_stats(bm, idx, s)


def _set_ac(engine, bm, idx, ac):
    s = engine.get_agent_stats(bm, idx)
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def test_hit_probability_flat():
    """+4 to hit vs AC 15: d20 >= 11 hits → exactly 0.5 (nat 1 misses anyway, no crit)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    _arm(engine, bm, npc, bonus_hit=4)
    _set_ac(engine, bm, pc, 15)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert abs(a.p_hit - 0.5) < EPS, f"p_hit should be 0.5, got {a.p_hit}"
    assert not a.advantage and not a.disadvantage
    print("✅ test_hit_probability_flat passed")


def test_hit_probability_nat1_and_crit():
    """+20 to hit vs AC 10 with the default crit threshold: only the natural 1 misses → 19/20."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    _arm(engine, bm, npc, bonus_hit=20, no_crit=False)
    _set_ac(engine, bm, pc, 10)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert abs(a.p_hit - 19.0 / 20.0) < EPS, f"p_hit should be 0.95, got {a.p_hit}"
    print("✅ test_hit_probability_nat1_and_crit passed")


def test_advantage_squares_the_miss():
    """Same 0.5 swing made at Advantage (attacker condition) → 1 - 0.5² = 0.75."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    _arm(engine, bm, npc, bonus_hit=4)
    _set_ac(engine, bm, pc, 15)
    c = engine.get_agent_conditions(bm, npc)
    c.has_advantage = True
    engine.set_agent_conditions(bm, npc, c)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert a.advantage and not a.disadvantage
    assert abs(a.p_hit - 0.75) < EPS, f"p_hit should be 0.75, got {a.p_hit}"
    print("✅ test_advantage_squares_the_miss passed")


def test_prone_target_gives_melee_advantage():
    """A prone target within 5 ft grants the estimate Advantage (performAttack's rule)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    _arm(engine, bm, npc, bonus_hit=4)
    _set_ac(engine, bm, pc, 15)
    c = engine.get_agent_conditions(bm, pc)
    c.prone = True
    engine.set_agent_conditions(bm, pc, c)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert a.advantage, "melee vs an adjacent prone target is at Advantage"
    assert abs(a.p_hit - 0.75) < EPS
    print("✅ test_prone_target_gives_melee_advantage passed")


def test_drop_chance_exact_die_tail():
    """1d6 damage (no mods, no crit) vs a 4 HP target: drop on a 4-6 → exactly 0.5."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2, hp=4)
    _arm(engine, bm, npc, bonus_hit=4)      # str 10 → no ability damage mod
    _set_ac(engine, bm, pc, 15)
    s = engine.get_agent_stats(bm, pc)
    s.hp_cur = 4
    engine.set_agent_stats(bm, pc, s)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert abs(a.p_drop_given_hit - 0.5) < EPS, \
        f"p_drop_given_hit should be 0.5, got {a.p_drop_given_hit}"
    print("✅ test_drop_chance_exact_die_tail passed")


def test_drop_chance_resistance_and_temp_hp():
    """Slashing resistance halves (truncated) the 1d6 → damage 0,1,1,2,2,3; with 2 HP + 1
    temp HP the drop needs 3 post-resist → only a rolled 6 drops → 1/6."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2, hp=2)
    _arm(engine, bm, npc, bonus_hit=4)
    _set_ac(engine, bm, pc, 15)
    s = engine.get_agent_stats(bm, pc)
    s.hp_cur = 2
    s.temp_hp = 1
    s.set_physical_damage_multiplier(rpg.PhysicalDamage.Slashing, 0.5)
    engine.set_agent_stats(bm, pc, s)

    a = engine.npc_analyze_attack(bm, npc, pc, 0)
    assert abs(a.p_drop_given_hit - 1.0 / 6.0) < EPS, \
        f"p_drop_given_hit should be 1/6, got {a.p_drop_given_hit}"
    print("✅ test_drop_chance_resistance_and_temp_hp passed")


def _save_spell(ability=rpg.SaveAbility.SaveWis):
    sp = rpg.Spell()
    sp.name = "Test Hold"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = ability
    sp.range = 60
    sp.level = 2
    return sp


def test_save_chance_flat():
    """Caster WIS 16 + prof 2 → DC 13; target WIS mod 0, no proficiency: saves on
    d20 >= 13 → 8/20 = 0.4."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Cult Fanatic", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    s = engine.get_agent_stats(bm, npc)
    s.wis = 16
    s.spellcasting_ability = 4      # WIS
    s.prof_bonus = 2
    engine.set_agent_stats(bm, npc, s)

    p = engine.npc_save_chance(bm, npc, pc, _save_spell())
    assert abs(p - 0.4) < EPS, f"save chance should be 0.4, got {p}"
    print("✅ test_save_chance_flat passed")


def test_save_auto_fail_paralyzed_dex():
    """A Paralyzed target auto-fails STR/DEX saves (rollSpellSave rule) → 0.0."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Cult Fanatic", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    c = engine.get_agent_conditions(bm, pc)
    c.paralyzed = True
    engine.set_agent_conditions(bm, pc, c)

    p = engine.npc_save_chance(bm, npc, pc, _save_spell(rpg.SaveAbility.SaveDex))
    assert abs(p) < EPS, f"paralyzed DEX save chance should be 0, got {p}"
    # A WIS save is unaffected by the STR/DEX auto-fail.
    p_wis = engine.npc_save_chance(bm, npc, pc, _save_spell(rpg.SaveAbility.SaveWis))
    assert p_wis > 0.0
    print("✅ test_save_auto_fail_paralyzed_dex passed")


def test_spell_hit_chance():
    """Attack-roll spell: spell attack mod +5 (WIS 16, prof 2) vs AC 16 → d20 >= 11 with a
    natural-20 crit already inside that range → 0.5. The target stands beyond 10 ft so the
    caster is not Threatened (which would impose Disadvantage, as in rollSpellAttack)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    npc = _place(engine, bm, "Cult Fanatic", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 12, 5, 2)
    s = engine.get_agent_stats(bm, npc)
    s.wis = 16
    s.spellcasting_ability = 4
    s.prof_bonus = 2
    engine.set_agent_stats(bm, npc, s)
    _set_ac(engine, bm, pc, 16)

    sp = _save_spell()
    sp.attack_type = rpg.SpellAttack.AttackRoll
    p = engine.npc_spell_hit_chance(bm, npc, pc, sp)
    assert abs(p - 0.5) < EPS, f"spell hit chance should be 0.5, got {p}"
    print("✅ test_spell_hit_chance passed")


def test_analysis_line_logged_by_npc_turn():
    """An automated Simple turn logs an 'Analysis:' line before the swing."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    logger = rpg.MessageLogger()
    engine.set_logger(logger)
    npc = _place(engine, bm, "Orc", 5, 5, 1)
    pc = _place(engine, bm, "Fighter", 6, 5, 2)
    _arm(engine, bm, npc, bonus_hit=4)
    _set_ac(engine, bm, pc, 15)
    bm.set_agent_npc_automated(npc, True)

    engine.begin_turn(bm, npc)
    logger.flush()
    status = engine.run_npc_turn(bm, npc)
    msgs = logger.flush()
    analysis = [m for m in msgs if m.startswith("Analysis:")]
    assert status == rpg.FlowStatus.Completed
    assert analysis, f"expected an Analysis: line in the NPC turn log, got {msgs}"
    assert "% to hit" in analysis[0] and "% to drop" in analysis[0]
    print("✅ test_analysis_line_logged_by_npc_turn passed")


if __name__ == "__main__":
    test_hit_probability_flat()
    test_hit_probability_nat1_and_crit()
    test_advantage_squares_the_miss()
    test_prone_target_gives_melee_advantage()
    test_drop_chance_exact_die_tail()
    test_drop_chance_resistance_and_temp_hp()
    test_save_chance_flat()
    test_save_auto_fail_paralyzed_dex()
    test_spell_hit_chance()
    test_analysis_line_logged_by_npc_turn()
    print("\n🎉 All NPC analysis tests passed!")
