#!/usr/bin/env python3
"""
Test Paladin auras (team-scoped emanations):
  - Aura of Protection (L6+): +CHA mod (min 1) to the saving throws of the Paladin and
    same-team allies within 10 ft (30 ft at L18).
  - Aura of Courage (L10+): the Paladin and same-team allies in range can't be Frightened.

Distance note: footprintDistance is Chebyshev in CELLS; 5 ft per cell, so 10 ft = 2 cells,
30 ft = 6 cells. The map is 12x12.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

RED, BLUE = 1, 2


def _paladin(engine, bm, idx, level, cha=16, faction=RED):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Paladin, level)
    s.cha = cha
    s.initialize_class_resources(rpg.CharacterClass.Paladin, level)
    engine.set_agent_stats(bm, idx, s)
    bm.set_agent_faction(idx, faction)
    return engine.get_agent_stats(bm, idx)


def _ally(engine, bm, idx, faction=RED, wis=10):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, 1)
    s.wis = wis
    s.hp_max = 30
    s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)
    bm.set_agent_faction(idx, faction)
    return engine.get_agent_stats(bm, idx)


def _place(engine, bm, name, col, row):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row))


# CHA 16 -> +3; min-1 aura is +3 here.
EXPECT = 3


def test_aura_protection_ally_in_range():
    """A same-team ally adjacent to a L6 Paladin gains +CHA to saves."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)   # 1 cell = 5 ft, in range
    _paladin(engine, bm, pal, 6)
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == EXPECT, "ally in 10 ft should get +CHA"
    print("✅ test_aura_protection_ally_in_range passed")


def test_aura_protection_out_of_range():
    """An ally beyond 10 ft (but within 30 ft) gets nothing from a sub-L18 Paladin."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 9, 5)   # 4 cells = 20 ft, out of 10 ft
    _paladin(engine, bm, pal, 6)
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == 0, "ally beyond 10 ft gets no aura"
    print("✅ test_aura_protection_out_of_range passed")


def test_aura_protection_l18_extends_to_30ft():
    """At L18 the aura radius grows to 30 ft (6 cells)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 2, 2)
    ally = _place(engine, bm, "Ally", 7, 2)   # 5 cells = 25 ft, in 30 ft
    _paladin(engine, bm, pal, 18)
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == EXPECT, "L18 aura reaches 30 ft"
    print("✅ test_aura_protection_l18_extends_to_30ft passed")


def test_aura_protection_enemy_excluded():
    """A different-faction creature in range gets no benefit (allies only)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5)
    _paladin(engine, bm, pal, 6, faction=RED)
    _ally(engine, bm, foe, faction=BLUE)
    assert engine.aura_save_bonus(bm, foe) == 0, "enemy in range gets no aura"
    print("✅ test_aura_protection_enemy_excluded passed")


def test_aura_protection_self():
    """The Paladin always benefits from its own aura, even with no team set (neutral)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    _paladin(engine, bm, pal, 6, faction=0)   # neutral
    assert engine.aura_save_bonus(bm, pal) == EXPECT, "Paladin benefits from its own aura"
    print("✅ test_aura_protection_self passed")


def test_aura_protection_min_one():
    """Even with CHA 10 (+0) the aura is at least +1."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _paladin(engine, bm, pal, 6, cha=10)
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == 1, "aura floor is +1"
    print("✅ test_aura_protection_min_one passed")


def test_aura_protection_level_gate():
    """Below L6 there is no Aura of Protection."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _paladin(engine, bm, pal, 5)
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == 0, "L5 Paladin has no aura"
    print("✅ test_aura_protection_level_gate passed")


def test_aura_protection_suppressed_when_down():
    """An unconscious Paladin projects no aura."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _paladin(engine, bm, pal, 6)
    _ally(engine, bm, ally)
    c = engine.get_agent_conditions(bm, pal)
    c.unconscious = True
    engine.set_agent_conditions(bm, pal, c)
    assert engine.aura_save_bonus(bm, ally) == 0, "downed Paladin gives no aura"
    print("✅ test_aura_protection_suppressed_when_down passed")


def test_aura_protection_takes_strongest():
    """With two allied Paladins in range, the higher CHA aura wins (no stacking)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    p1 = _place(engine, bm, "Pal1", 5, 5)
    p2 = _place(engine, bm, "Pal2", 4, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _paladin(engine, bm, p1, 6, cha=14)   # +2
    _paladin(engine, bm, p2, 6, cha=20)   # +5
    _ally(engine, bm, ally)
    assert engine.aura_save_bonus(bm, ally) == 5, "take the strongest aura, not the sum"
    print("✅ test_aura_protection_takes_strongest passed")


def test_save_mod_for_includes_aura():
    """save_mod_for folds the aura into the ability+proficiency modifier."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _paladin(engine, bm, pal, 6)
    _ally(engine, bm, ally, wis=14)   # WIS +2, not proficient
    # base WIS save = +2; with aura = +2 + 3 = +5
    assert engine.save_mod_for(bm, ally, rpg.SaveAbility.Wisdom) == 5
    # Out of aura the same ally is just +2.
    bm.set_agent_faction(ally, BLUE)
    assert engine.save_mod_for(bm, ally, rpg.SaveAbility.Wisdom) == 2
    print("✅ test_save_mod_for_includes_aura passed")


def test_aura_of_courage_levels():
    """Aura of Courage needs L10; L6-9 grants Protection but not fear immunity."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _ally(engine, bm, ally)
    _paladin(engine, bm, pal, 6)
    assert not engine.has_aura_of_courage(bm, ally), "L6: no Aura of Courage"
    _paladin(engine, bm, pal, 10)
    assert engine.has_aura_of_courage(bm, ally), "L10: Aura of Courage active"
    print("✅ test_aura_of_courage_levels passed")


def _fireball():
    sp = rpg.Spell()
    sp.name = "Fireball"
    sp.level = 0
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Dexterity
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.radius = 20
    sp.range = 120
    return sp


def test_aoe_save_reports_aura_in_save_mod():
    """The end-to-end smoke-test scenario: an enemy AoE Save spell — the per-target
    SpellTargetResult.save_mod for an ally in a Paladin's aura includes the +CHA, so the
    GUI no longer shows the un-buffed modifier."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 1, 1))
    pal = add_agent_to_battle(engine, bm, create_test_agent("Paladin", 8, 8))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 8, 9), hp=100)
    _paladin(engine, bm, pal, 6)                 # RED, CHA 16 -> +3 aura
    _ally(engine, bm, ally, faction=RED)         # DEX 10 -> +0 base save
    bm.set_agent_faction(foe, BLUE)

    engine.set_agent_spells(bm, foe, [_fireball()])
    s = engine.get_agent_stats(bm, foe)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, foe, s)
    action = rpg.SpellAction()
    action.caster_idx = foe
    action.spell_idx = 0
    action.aoe_col, action.aoe_row = 8, 8
    res = engine.execute_spell(bm, action)

    by_idx = {tr.target_idx: tr for tr in res.target_results}
    assert ally in by_idx, "ally should be in the blast"
    assert by_idx[ally].save_mod == EXPECT, \
        f"ally save_mod should include the +{EXPECT} aura, got {by_idx[ally].save_mod}"
    assert by_idx[pal].save_mod == EXPECT, "the Paladin's own save also gets its aura"
    print("✅ test_aoe_save_reports_aura_in_save_mod passed")


def test_aura_of_courage_blocks_frightened():
    """A protected ally can't be Frightened; an enemy in range still can."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    pal = _place(engine, bm, "Paladin", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    foe = _place(engine, bm, "Foe", 4, 5)
    _paladin(engine, bm, pal, 10)
    _ally(engine, bm, ally, faction=RED)
    _ally(engine, bm, foe, faction=BLUE)

    engine.apply_frightened(bm, ally)
    assert not engine.get_agent_conditions(bm, ally).frightened, "ally immune via Aura of Courage"

    engine.apply_frightened(bm, foe)
    assert engine.get_agent_conditions(bm, foe).frightened, "enemy is not protected"
    print("✅ test_aura_of_courage_blocks_frightened passed")


if __name__ == "__main__":
    test_aura_protection_ally_in_range()
    test_aura_protection_out_of_range()
    test_aura_protection_l18_extends_to_30ft()
    test_aura_protection_enemy_excluded()
    test_aura_protection_self()
    test_aura_protection_min_one()
    test_aura_protection_level_gate()
    test_aura_protection_suppressed_when_down()
    test_aura_protection_takes_strongest()
    test_save_mod_for_includes_aura()
    test_aura_of_courage_levels()
    test_aoe_save_reports_aura_in_save_mod()
    test_aura_of_courage_blocks_frightened()
    print("\n✅ All Paladin aura tests passed!")
