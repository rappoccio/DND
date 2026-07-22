#!/usr/bin/env python3
"""
Test: an area-of-effect damage spell makes ONE damage roll for the whole area.

RAW, the caster rolls the spell's damage a single time and every creature in the area
takes that same rolled total (full on a failed save, half on a success) — the damage is
NOT re-rolled per target. Fireball is the canonical case.

We cast an 8d6 Fireball over several identical targets and assert:
  • every target shares the exact same rolled dice (the single area roll), and
  • each target's damage matches that shared roll (full if it failed its save, half if it
    saved) — so the only per-target variation is the save outcome, not a fresh roll.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _fireball():
    sp = rpg.Spell()
    sp.name = "Fireball"
    sp.level = 0  # cantrip-level avoids spell-slot bookkeeping in the test
    sp.type = rpg.SpellType.Harm
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.Dexterity
    sp.geometry = rpg.SpellGeometry.Sphere
    sp.radius = 20
    sp.range = 120
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Fire
    dmg.num_dice = 8   # 8d6 — independent per-target rolls would almost never match
    dmg.die_size = 6
    sp.magic_damage_rolls = [dmg]
    return sp


def _cast_sphere(engine, bm, caster, spell, col, row):
    engine.set_agent_spells(bm, caster, [spell])
    s = engine.get_agent_stats(bm, caster)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, caster, s)
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.aoe_col = col
    action.aoe_row = row
    return engine.execute_spell(bm, action)


def test_fireball_one_roll_for_whole_area():
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Caster well away from the blast; three identical victims clustered at the center
    # (high HP so none drop, plain stats so nobody has resistance to skew the totals).
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 2, 2))
    victims = [
        add_agent_to_battle(engine, bm, create_test_agent("V1", 8, 8), hp=100),
        add_agent_to_battle(engine, bm, create_test_agent("V2", 8, 9), hp=100),
        add_agent_to_battle(engine, bm, create_test_agent("V3", 9, 8), hp=100),
    ]

    res = _cast_sphere(engine, bm, caster, _fireball(), 8, 8)

    # Collect the per-target results for our victims.
    by_idx = {tr.target_idx: tr for tr in res.target_results}
    for v in victims:
        assert v in by_idx, f"victim {v} should be caught in the Fireball"

    rolls = [tuple(by_idx[v].dice_results) for v in victims]

    # Core invariant: ONE area roll — every victim shows the identical dice.
    assert len(rolls[0]) == 8, f"expected 8d6 dice, got {rolls[0]}"
    assert rolls[0] == rolls[1] == rolls[2], (
        f"all targets must share the single area damage roll, got {rolls}")

    # And each victim's damage ties back to that shared roll: full on a failed save,
    # half (rounded down) on a successful one.
    shared_total = sum(rolls[0])
    for v in victims:
        tr = by_idx[v]
        expected = shared_total // 2 if tr.saved else shared_total
        assert tr.total_damage == expected, (
            f"victim {v}: saved={tr.saved} expected {expected} from shared roll "
            f"{shared_total}, got {tr.total_damage}")

    print("✅ test_fireball_one_roll_for_whole_area passed")


if __name__ == "__main__":
    test_fireball_one_roll_for_whole_area()
    print("\nAll AoE shared-roll tests passed! 🎉")
