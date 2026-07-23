#!/usr/bin/env python3
"""
Multiclassing Phase 3 — multiclass spellcasting (combined caster level).

Before Phase 3, spell_slots_max was computed from ONE class's table
(compute_class_slots(character_class, char_level)). For a multiclass caster that is
wrong twice over: a Cleric 3 / Wizard 3 would get a single class's level-3 slots
instead of the combined level-6 full-caster row.

Phase 3 adds Stats.computeMulticlassSlots() (bound as compute_multiclass_slots),
wired into set_class_level / add_class_level, implementing the PHB multiclass rule:

  * ONE spellcasting class  → that class's OWN table (single-class Paladin keeps
    kHalf; single-class EK/AT keeps the third-caster table; a single full caster
    keeps kFull) — the combined table applies only to a genuine multi-caster.
  * TWO+ spellcasting classes → combined caster level =
        full-levels + floor(half-levels / 2) + floor(third-levels / 3)
    read off the full-caster table (kFull).

Warlock Pact Magic is a SEPARATE pool that never folds into the combined level:
a Warlock-only caster returns its pact table; a Warlock's levels are ignored when
other caster classes are present (the parallel pact pool for that combo is deferred).

Run standalone (asserts raise → non-zero exit) or via tests/run_all_tests.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg

CC = rpg.CharacterClass


def _slots(stats):
    """The engine's per-level slot array as a plain list of 9 ints."""
    return list(stats.compute_multiclass_slots())


def _table(cls, level):
    """The single-class reference table for (cls, level)."""
    return list(rpg.compute_class_slots(cls, level))


# ── Single-class casters are unchanged (the combined table must NOT apply) ─────────
def test_single_class_full_caster_unchanged():
    s = rpg.Stats()
    s.set_class_level(CC.Wizard, 6)
    assert _slots(s) == _table(CC.Wizard, 6), \
        f"single-class Wizard 6 should use kFull[6], got {_slots(s)}"
    # And spell_slots_max was populated by set_class_level via the same path.
    assert list(s.spell_slots_max) == _table(CC.Wizard, 6), \
        "set_class_level should have written the same combined slots into spell_slots_max"
    print("✅ test_single_class_full_caster_unchanged passed")


def test_single_class_half_caster_uses_half_table():
    # A single-class Paladin 5 must use kHalf (4/2/...), NOT the combined-level path
    # (which would be floor(5/2)=2 → kFull[2] = 3 first-level slots — the classic bug).
    s = rpg.Stats()
    s.set_class_level(CC.Paladin, 5)
    assert _slots(s) == _table(CC.Paladin, 5), \
        f"single-class Paladin 5 should use kHalf[5], got {_slots(s)}"
    assert _slots(s) != _table(CC.Wizard, 2), \
        "single-class Paladin must NOT collapse to the combined floor(level/2) full-caster row"
    print("✅ test_single_class_half_caster_uses_half_table passed")


def test_pure_warlock_keeps_pact_table():
    s = rpg.Stats()
    s.set_class_level(CC.Warlock, 5)
    assert _slots(s) == _table(CC.Warlock, 5), \
        f"pure Warlock 5 should keep its pact table (kPact[5]), got {_slots(s)}"
    assert s.pact_slot_level() == 3, \
        f"Warlock 5 pact slots sit at 3rd level, got pact_slot_level={s.pact_slot_level()}"
    print("✅ test_pure_warlock_keeps_pact_table passed")


def test_caster_multiclassed_with_martial_unchanged():
    # Wizard 5 / Fighter 5 (no EK) — Fighter is not a caster → still one caster class.
    s = rpg.Stats()
    s.set_class_level(CC.Wizard, 5)
    s.add_class_level(CC.Fighter, 5)
    assert _slots(s) == _table(CC.Wizard, 5), \
        f"Wizard 5 / Fighter 5 (non-EK) should use Wizard's own kFull[5], got {_slots(s)}"
    print("✅ test_caster_multiclassed_with_martial_unchanged passed")


# ── The centerpiece: two caster classes → combined caster level → kFull ────────────
def test_full_plus_full_uses_combined_level():
    # Cleric 3 / Wizard 3 → combined caster level 6 → the full-caster level-6 row,
    # NOT two separate level-3 tables.
    s = rpg.Stats()
    s.set_class_level(CC.Cleric, 3)
    s.add_class_level(CC.Wizard, 3)
    combined = _table(CC.Cleric, 6)          # any full-caster row at level 6
    assert _slots(s) == combined, \
        f"Cleric 3 / Wizard 3 should get the combined level-6 kFull row {combined}, got {_slots(s)}"
    assert _slots(s) != _table(CC.Cleric, 3), \
        "combined slots must differ from a single class's level-3 table"
    # add_class_level should have written the combined array into spell_slots_max too.
    assert list(s.spell_slots_max) == combined, \
        "add_class_level should have written the combined slots into spell_slots_max"
    print("✅ test_full_plus_full_uses_combined_level passed")


def test_full_plus_half_rounds_half_down():
    # Cleric 6 / Paladin 3 → combined = 6 + floor(3/2) = 7 → kFull[7].
    s = rpg.Stats()
    s.set_class_level(CC.Cleric, 6)
    s.add_class_level(CC.Paladin, 3)
    assert _slots(s) == _table(CC.Cleric, 7), \
        f"Cleric 6 / Paladin 3 should be combined level 7 (6 + floor(3/2)), got {_slots(s)}"
    print("✅ test_full_plus_half_rounds_half_down passed")


def test_full_plus_third_caster_counts_ek():
    # Wizard 3 / Fighter 3 (Eldritch Knight) → combined = 3 + floor(3/3) = 4 → kFull[4].
    # The third-caster contribution is subclass-gated, so set fighter_subclass first,
    # then read compute_multiclass_slots() (which recomputes from the current subclass).
    s = rpg.Stats()
    s.set_class_level(CC.Wizard, 3)
    s.add_class_level(CC.Fighter, 3)
    # Before the subclass is set, the Fighter contributes nothing → still Wizard-only.
    assert _slots(s) == _table(CC.Wizard, 3), \
        "without the EK subclass the Fighter is not a caster → Wizard-only slots"
    s.fighter_subclass = rpg.FighterSubclass.EldritchKnight
    assert _slots(s) == _table(CC.Wizard, 4), \
        f"Wizard 3 / EK-Fighter 3 should be combined level 4 (3 + floor(3/3)), got {_slots(s)}"
    print("✅ test_full_plus_third_caster_counts_ek passed")


def test_warlock_multiclass_ignores_pact_in_combined():
    # Warlock 5 / Wizard 5 → Warlock is excluded from the combined level, and there is
    # only ONE non-Warlock caster (Wizard) → the Wizard's own table. (The parallel pact
    # pool for this combo is deferred; documented Phase 3 limitation.)
    s = rpg.Stats()
    s.set_class_level(CC.Wizard, 5)
    s.add_class_level(CC.Warlock, 5)
    assert _slots(s) == _table(CC.Wizard, 5), \
        f"Warlock 5 / Wizard 5 combined slots should be Wizard's kFull[5] (pact excluded), got {_slots(s)}"
    print("✅ test_warlock_multiclass_ignores_pact_in_combined passed")


if __name__ == "__main__":
    test_single_class_full_caster_unchanged()
    test_single_class_half_caster_uses_half_table()
    test_pure_warlock_keeps_pact_table()
    test_caster_multiclassed_with_martial_unchanged()
    test_full_plus_full_uses_combined_level()
    test_full_plus_half_rounds_half_down()
    test_full_plus_third_caster_counts_ek()
    test_warlock_multiclass_ignores_pact_in_combined()
    print("\n✅ All multiclass spell-slot tests passed!")
