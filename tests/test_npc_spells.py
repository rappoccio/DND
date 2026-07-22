#!/usr/bin/env python3
"""Tests for NPC innate-spell auto-population (read_stats_from_csv).

Covers the CSV-column -> (spell_indices, npc_spell_groups) resolution that
feeds the bestiary records the GUI auto-loads onto placed NPCs:
  · At-Will cantrips stay ungrouped (always castable in C++)
  · At-Will leveled spells get the AT_WILL_USES budget
  · N/Day columns map to N-use groups
  · misspelled / variant names resolve via the alias table
  · non-casters produce empty results
  · the shipped bestiary JSON only references catalog spells
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import read_stats_from_csv as R


def _resolve(name):
    return R._resolve_spell(name, R._load_spell_catalog())


def test_atwill_cantrip_ungrouped():
    # Mage Hand is a cantrip (level 0): known, but never given a use budget.
    indices, groups = R.npc_spells_from_raw({"At Will": "Mage Hand"})
    assert indices == ["Mage Hand"], indices
    assert groups == {}, groups


def test_atwill_leveled_gets_atwill_budget():
    indices, groups = R.npc_spells_from_raw({"At Will": "Fireball"})
    assert indices == ["Fireball"], indices
    assert groups == {str(R.AT_WILL_USES): ["Fireball"]}, groups


def test_n_per_day_grouping():
    indices, groups = R.npc_spells_from_raw(
        {"3/Day": "Magic Missile", "1/Day": "Counterspell, Fireball"})
    assert set(indices) == {"Magic Missile", "Counterspell", "Fireball"}, indices
    assert groups["3"] == ["Magic Missile"], groups
    assert sorted(groups["1"]) == ["Counterspell", "Fireball"], groups


def test_level_annotation_stripped():
    # Dragons list upcast levels in parentheses; the base spell must still match.
    assert _resolve("Melf's Acid Arrow (3rd level)") == ("Acid Arrow", 2)
    assert _resolve("Guiding Bolt (level 2)")[0] == "Guiding Bolt"


def test_alias_typos_resolve():
    assert _resolve("Lighting Bolt")[0] == "Lightning Bolt"
    assert _resolve("Mage Armour")[0] == "Mage Armor"
    assert _resolve("Disintergrate")[0] == "Disintegrate"
    assert _resolve("Markness")[0] == "Darkness"


def test_unknown_spell_skipped_and_reported():
    unresolved = set()
    indices, groups = R.npc_spells_from_raw(
        {"At Will": "Nonexistent Spell, Mage Hand"}, unresolved=unresolved)
    assert indices == ["Mage Hand"], indices
    assert "Nonexistent Spell" in unresolved, unresolved


def test_non_caster_is_empty():
    indices, groups = R.npc_spells_from_raw({"At Will": "", "1/Day": ""})
    assert indices == [] and groups == {}


def test_first_listing_wins_on_duplicate():
    # A spell named under two frequencies keeps the higher-frequency listing.
    indices, groups = R.npc_spells_from_raw(
        {"At Will": "Fireball", "1/Day": "Fireball"})
    assert indices == ["Fireball"]
    assert groups == {str(R.AT_WILL_USES): ["Fireball"]}, groups


def test_bestiary_references_only_catalog_spells():
    gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
    bestiary = json.load(open(os.path.join(gui, "DND2024_MonsterStats.json")))
    catalog = {s["name"] for s in json.load(open(os.path.join(gui, "spells.json")))}
    casters = 0
    for name, rec in bestiary.items():
        for sp in rec.get("spell_indices", []):
            assert sp in catalog, f"{name}: '{sp}' not in spell catalog"
        # Every grouped name must also appear in spell_indices.
        for group in rec.get("npc_spell_groups", {}).values():
            for sp in group:
                assert sp in rec.get("spell_indices", []), \
                    f"{name}: grouped '{sp}' missing from spell_indices"
        if rec.get("spell_indices"):
            casters += 1
    assert casters > 100, f"expected many casters, found {casters}"


def run_all_tests():
    tests = [
        test_atwill_cantrip_ungrouped,
        test_atwill_leveled_gets_atwill_budget,
        test_n_per_day_grouping,
        test_level_annotation_stripped,
        test_alias_typos_resolve,
        test_unknown_spell_skipped_and_reported,
        test_non_caster_is_empty,
        test_first_listing_wins_on_duplicate,
        test_bestiary_references_only_catalog_spells,
    ]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"✅ {test.__name__} passed")
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
