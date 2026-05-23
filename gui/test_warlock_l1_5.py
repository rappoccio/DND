#!/usr/bin/env python3
"""
Test Warlock Phase 1: Pact Magic foundation — chassis (CHA caster, WIS/CHA saves),
pact slot counts/level by level, short-rest recharge, and Magical Cunning.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _warlock_stats(level, subclass=None):
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    if subclass is not None:
        s.warlock_subclass = subclass
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    return s


def test_warlock_chassis():
    """Charisma caster, WIS+CHA save proficiencies, can cast."""
    s = _warlock_stats(1)
    assert s.spellcasting_ability == 5, f"Warlock casts with CHA (5), got {s.spellcasting_ability}"
    assert s.save_prof_wis and s.save_prof_cha, "Warlock has WIS + CHA save proficiencies"
    assert s.can_cast_spell, "Warlock can cast"
    assert s.warlock_subclass == rpg.WarlockSubclass.NONE
    print("✅ test_warlock_chassis passed")


def test_warlock_subclass_roundtrip():
    """The patron subclass enum is settable/readable."""
    for sc in [rpg.WarlockSubclass.Archfey, rpg.WarlockSubclass.Celestial,
               rpg.WarlockSubclass.Fiend, rpg.WarlockSubclass.GreatOldOne]:
        s = _warlock_stats(3, subclass=sc)
        assert s.warlock_subclass == sc
    print("✅ test_warlock_subclass_roundtrip passed")


def test_pact_slots_by_level():
    """kPact: count + uniform slot level at representative levels."""
    # (warlock level, slot count, slot level)
    cases = [(1, 1, 1), (2, 2, 1), (3, 2, 2), (5, 2, 3), (7, 2, 4),
             (9, 2, 5), (11, 3, 5), (17, 4, 5)]
    for lvl, count, slot_lvl in cases:
        s = _warlock_stats(lvl)
        assert s.pact_slot_level() == slot_lvl, \
            f"L{lvl}: expected pact slot level {slot_lvl}, got {s.pact_slot_level()}"
        assert s.spell_slots_max[slot_lvl - 1] == count, \
            f"L{lvl}: expected {count} slots, got {s.spell_slots_max[slot_lvl - 1]}"
        # all other slot levels must be empty (pact slots are all one level)
        total = sum(s.spell_slots_max)
        assert total == count, f"L{lvl}: pact slots must all be one level (total {total} != {count})"
    print("✅ test_pact_slots_by_level passed")


def test_short_rest_recharge():
    """Pact slots recharge on a short rest (not just long rest)."""
    s = _warlock_stats(5)  # 2 slots at level 3
    lvl = s.pact_slot_level()
    rem = list(s.spell_slots_remaining)
    rem[lvl - 1] = 0  # expend both
    s.spell_slots_remaining = rem
    assert s.spell_slots_remaining[lvl - 1] == 0
    s.restore_resources_short_rest()
    assert s.spell_slots_remaining[lvl - 1] == 2, "short rest must recharge pact slots"
    print("✅ test_short_rest_recharge passed")


def test_apply_short_rest_engine():
    """CombatEngine.apply_short_rest restores a Warlock's expended pact slots."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Warlock, 5)  # 2 slots at level 3
    s.initialize_class_resources(rpg.CharacterClass.Warlock, 5)
    lvl = s.pact_slot_level()
    rem = list(s.spell_slots_remaining)
    rem[lvl - 1] = 0
    s.spell_slots_remaining = rem
    engine.set_agent_stats(bm, idx, s)

    engine.apply_short_rest(bm)
    after = engine.get_agent_stats(bm, idx)
    assert after.spell_slots_remaining[lvl - 1] == 2, "engine short rest must restore pact slots"
    print("✅ test_apply_short_rest_engine passed")


def test_magical_cunning():
    """Magical Cunning recovers ceil(max/2) expended pact slots, once per long rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Warlock, 9)  # 2 slots at level 5
    s.initialize_class_resources(rpg.CharacterClass.Warlock, 9)
    lvl = s.pact_slot_level()
    rem = list(s.spell_slots_remaining)
    rem[lvl - 1] = 0  # expend both
    s.spell_slots_remaining = rem
    engine.set_agent_stats(bm, idx, s)

    assert engine.use_magical_cunning(bm, idx), "Magical Cunning should be usable"
    after = engine.get_agent_stats(bm, idx)
    assert after.spell_slots_remaining[lvl - 1] == 1, \
        f"ceil(2/2)=1 slot recovered, got {after.spell_slots_remaining[lvl - 1]}"
    # Once per long rest: a second use fails.
    assert not engine.use_magical_cunning(bm, idx), "Magical Cunning is once per long rest"
    print("✅ test_magical_cunning passed")


if __name__ == "__main__":
    test_warlock_chassis()
    test_warlock_subclass_roundtrip()
    test_pact_slots_by_level()
    test_short_rest_recharge()
    test_apply_short_rest_engine()
    test_magical_cunning()
    print("\n✅ All Warlock Phase 1 tests passed!")
