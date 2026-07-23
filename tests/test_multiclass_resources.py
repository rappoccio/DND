#!/usr/bin/env python3
"""
Multiclassing Phase 4 — resource-init merge.

Before Phase 4, Agent::Stats::initializeClassResources(cls, level) called
resources.clear() at the top of a single switch(cls). For a multiclass character
there was no way to run it per class without the second call WIPING the first
class's resources — a Barbarian 5 / Fighter 5 could keep either Rage OR Second Wind,
never both.

Phase 4 splits the body into applyClassResources(cls, level) (no clear) and adds
Stats.initializeMulticlassResources() (bound as initialize_multiclass_resources),
which clears ONCE and then applies every populated class in class_levels so the
resources ACCUMULATE. Two hazards it guards:

  * Extra Attack must NOT stack — two martial classes each granting a second attack
    still yield ONE extra attack. num_attacks is the MAX any single class grants
    (Fighter 11's three attacks beats Barbarian 5's two), independent of merge order.
  * One-shot ability bumps (Primal Champion, Body and Mind, Draconic HP) stay guarded
    by their *_applied flags, so re-running the merge never double-applies them.

Run standalone (asserts raise → non-zero exit) or via tests/run_all_tests.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg

CC = rpg.CharacterClass


def _res(stats):
    """Set of resource names currently present."""
    return set(stats.resources.keys())


# ── The centerpiece: Barbarian 5 / Fighter 5 keeps BOTH classes' resources ─────────
def test_barbarian_fighter_merges_resources():
    s = rpg.Stats()
    s.set_class_level(CC.Barbarian, 5)
    s.add_class_level(CC.Fighter, 5)
    s.initialize_multiclass_resources()

    names = _res(s)
    # Barbarian side
    assert "Rage" in names, f"Barbarian 5 / Fighter 5 must keep Rage, got {sorted(names)}"
    # Fighter side — both survive the merge (pre-Phase-4 the clear would drop one class)
    assert "Second Wind" in names, f"Fighter's Second Wind must survive the merge, got {sorted(names)}"
    assert "Action Surge" in names, f"Fighter's Action Surge must survive the merge, got {sorted(names)}"
    print("✅ test_barbarian_fighter_merges_resources passed")


# ── Extra Attack does not stack across two martial classes ─────────────────────────
def test_extra_attack_does_not_stack():
    s = rpg.Stats()
    s.set_class_level(CC.Barbarian, 5)   # grants a 2nd attack
    s.add_class_level(CC.Fighter, 5)     # also grants a 2nd attack
    s.initialize_multiclass_resources()
    assert s.num_attacks == 2, \
        f"Barbarian 5 / Fighter 5 should have ONE extra attack (num_attacks=2), got {s.num_attacks}"
    print("✅ test_extra_attack_does_not_stack passed")


def test_extra_attack_takes_the_max_regardless_of_order():
    # Fighter 11 grants THREE attacks; Barbarian 5 grants two. The merge must land on
    # the max (3), and that must not depend on which class was added first.
    a = rpg.Stats()
    a.set_class_level(CC.Fighter, 11)
    a.add_class_level(CC.Barbarian, 5)
    a.initialize_multiclass_resources()
    assert a.num_attacks == 3, f"Fighter 11 / Barbarian 5 should be 3 attacks, got {a.num_attacks}"

    b = rpg.Stats()
    b.set_class_level(CC.Barbarian, 5)   # lower-attack class first this time
    b.add_class_level(CC.Fighter, 11)
    b.initialize_multiclass_resources()
    assert b.num_attacks == 3, \
        f"order must not matter: Barbarian 5 / Fighter 11 should be 3 attacks, got {b.num_attacks}"
    print("✅ test_extra_attack_takes_the_max_regardless_of_order passed")


def test_non_martial_multiclass_has_single_attack():
    # Two classes, neither granting Extra Attack → num_attacks stays 1.
    s = rpg.Stats()
    s.set_class_level(CC.Wizard, 3)
    s.add_class_level(CC.Cleric, 3)
    s.initialize_multiclass_resources()
    assert s.num_attacks == 1, \
        f"Wizard 3 / Cleric 3 grant no Extra Attack → num_attacks should be 1, got {s.num_attacks}"
    print("✅ test_non_martial_multiclass_has_single_attack passed")


# ── Single-class merge is identical to the single-class entry point ────────────────
def test_single_class_merge_matches_single_class_init():
    merged = rpg.Stats()
    merged.set_class_level(CC.Fighter, 5)
    merged.initialize_multiclass_resources()

    direct = rpg.Stats()
    direct.set_class_level(CC.Fighter, 5)
    direct.initialize_class_resources(CC.Fighter, 5)

    assert _res(merged) == _res(direct), \
        f"single-class merge should match direct init: {_res(merged)} vs {_res(direct)}"
    assert merged.num_attacks == direct.num_attacks == 2, \
        f"single-class Fighter 5 should have num_attacks=2 both ways, got {merged.num_attacks}/{direct.num_attacks}"
    print("✅ test_single_class_merge_matches_single_class_init passed")


# ── One-shot ability bumps are idempotent under re-merge ───────────────────────────
def test_primal_champion_not_double_applied_on_remerge():
    s = rpg.Stats()
    s.str = 17
    s.con = 15
    s.set_class_level(CC.Barbarian, 20)
    s.initialize_multiclass_resources()
    str_after_first = s.str
    con_after_first = s.con
    # Primal Champion (+4/+4, capped at 25) should have fired exactly once.
    assert str_after_first == 21, f"Primal Champion should give STR 21, got {str_after_first}"
    assert con_after_first == 19, f"Primal Champion should give CON 19, got {con_after_first}"
    # Re-running the merge (as happens on every save/load) must NOT bump again.
    s.initialize_multiclass_resources()
    assert s.str == str_after_first and s.con == con_after_first, \
        f"re-merge double-applied Primal Champion: STR {s.str}, CON {s.con}"
    print("✅ test_primal_champion_not_double_applied_on_remerge passed")


if __name__ == "__main__":
    test_barbarian_fighter_merges_resources()
    test_extra_attack_does_not_stack()
    test_extra_attack_takes_the_max_regardless_of_order()
    test_non_martial_multiclass_has_single_attack()
    test_single_class_merge_matches_single_class_init()
    test_primal_champion_not_double_applied_on_remerge()
    print("\n✅ All multiclass resource-merge tests passed!")
