#!/usr/bin/env python3
"""
Master test runner for all Python test suites.
Runs all test scripts and reports overall results.
"""

import subprocess
import sys
import os

test_scripts = [
    # Core mechanics
    "test_conditions.py",
    "test_combat.py",
    "test_helpers.py",
    "test_spells.py",
    "test_chromatic_orb.py",
    "test_items.py",
    "test_thrown_weapons.py",
    "test_movement.py",
    "test_teleportation.py",
    "test_floors.py",
    "test_visibility.py",
    "test_light_effects.py",
    "test_heavily_obscured.py",
    "test_fog_cloud.py",
    "test_frightened.py",
    "test_unconscious.py",
    "test_deafened.py",
    "test_poisoned.py",
    "test_petrified.py",
    "test_condition_saves.py",
    "test_grapple.py",
    "test_death_saves.py",
    "test_heal_revives_downed.py",
    "test_exhaustion.py",
    "test_forced_movement_oa.py",
    "test_reactions.py",
    "test_reckless.py",
    "test_shield.py",
    "test_counterspell.py",
    "test_shield_vs_attack.py",
    "test_shield_vs_spell_attack.py",
    "test_riposte.py",
    "test_d20seen.py",
    "test_savefail.py",
    "test_legendary.py",
    "test_turn_start.py",
    "test_npc_automation.py",
    "test_vitality.py",
    "test_resource.py",
    "test_bonus_actions.py",
    "test_terrain_concentration.py",
    "test_summoning.py",
    "test_npc_spells.py",
    "test_origins.py",
    "test_feats.py",
    "test_general_feats.py",
    "test_general_feats_g4.py",
    "test_general_feats_g5.py",
    "test_general_feats_g5b.py",
    "test_element_spells.py",
    "test_fighting_styles.py",
    "test_dual_wield.py",
    "test_reaction_feats.py",
    "test_save_load_weapons.py",
    "test_weapon_list.py",
    "test_multiattack_recipes.py",
    "test_evoker_safe_targets.py",
    "test_factions.py",
    "test_emanation.py",
    "test_class_features.py",
    "test_on_damage.py",
    "test_cleric.py",
    "test_replay_roundtrip.py",

    # Barbarian features
    "test_barbarian_l1_3.py",
    "test_barbarian_l5.py",
    "test_barbarian_l6.py",
    "test_barbarian_l9_17.py",
    "test_barbarian_l14.py",

    # Wizard features
    "test_wizard_l1_3.py",
    "test_wizard_l3_portent.py",
    "test_wizard_l3_arcaneward.py",
    "test_wizard_l5.py",
    "test_wizard_l6_diviner.py",
    "test_evoker.py",

    # Warlock features
    "test_warlock_l1_5.py",
    "test_warlock_phase2.py",
    "test_warlock_phase3.py",
    "test_archfey.py",

    # Rogue features
    "test_rogue_l1_18.py",
    "test_rogue_cunning_actions.py",
    "test_rogue_phase2.py",
    "test_rogue_thief.py",
    "test_rogue_soulknife.py",
    "test_rogue_assassin.py",
    "test_rogue_arcane_trickster.py",

    # Monk features
    "test_monk.py",

    # Fighter features
    "test_weapon_mastery.py",
    "test_fighter.py",

    # Druid features
    "test_druid.py",

    # Paladin features
    "test_paladin.py",
    "test_paladin_auras.py",

    # Sorcerer features
    "test_sorcerer.py",

    # Bard features
    "test_bard.py",

    # Ranger features
    "test_ranger.py",

    # Vampire support (available_hit_points + reduceHPMax bite rider)
    "test_vampire.py",

    # Monster on-hit riders (Roper Reel = data-driven "Pull" forced move)
    "test_roper.py",

    # Regeneration (turn-start HP regain + damage-type / Sunlight interrupt)
    "test_regeneration.py",

    # Vistani Curse "kickback" (caster takes psychic damage when its curse ends)
    "test_vistani.py",

    # Vampire Misty Escape (Gaseous Form self-buff: physical immunity, fly-only, attack/cast lockout)
    "test_misty_escape.py",
]

def run_tests():
    """Run all test scripts and collect results."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    total_passed = 0
    total_failed = 0
    failed_scripts = []

    print("\n" + "=" * 70)
    print("  RUNNING ALL TEST SUITES")
    print("=" * 70 + "\n")

    for script in test_scripts:
        script_path = os.path.join(script_dir, script)
        print(f"\n{'=' * 70}")
        print(f"Running: {script}")
        print(f"{'=' * 70}\n")

        result = subprocess.run([sys.executable, script_path], cwd=script_dir)

        if result.returncode != 0:
            failed_scripts.append(script)
            total_failed += 1
        else:
            total_passed += 1

    print("\n" + "=" * 70)
    print("  OVERALL TEST RESULTS")
    print("=" * 70)
    print(f"Test suites passed: {total_passed}")
    print(f"Test suites failed: {total_failed}")

    if failed_scripts:
        print(f"\nFailed suites:")
        for script in failed_scripts:
            print(f"  - {script}")
    else:
        print("\n✓ All test suites passed!")

    print("=" * 70 + "\n")

    return 0 if total_failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_tests())
