#!/usr/bin/env python3
"""
Master test runner for all Python test suites.
Runs all test scripts and reports overall results.
"""

import subprocess
import sys
import os

test_scripts = [
    # Combat refactor oracle (COMBAT_REFACTOR_PLAN.md R0) — keep first so a
    # determinism regression fails fast, before the rest of the suite runs.
    "test_determinism.py",

    # Direct unit tests for rules.hpp's free functions (COMBAT_REFACTOR_PLAN.md R3
    # success criterion) — a C++ binary, since rules:: has no pybind11 surface.
    # Kept next to the determinism oracle: both guard the refactor itself.
    "test_rules.py",

    # Engine snapshot/restore round-trip (COMBAT_REFACTOR_PLAN.md R5) — the third
    # refactor guard: proves a restored engine is indistinguishable from the one the
    # snapshot came from (RNG stream, conditions, and parked reaction windows).
    "test_snapshot.py",

    # GUI regression oracle for the combat panel (MULTIPLAYER_PLAN.md Step 0.6) — the
    # fourth guard, and the only suite that covers main.py's rendering at all. Stands
    # App up headlessly and compares a structural capture (section / widget / label /
    # rect / drawn?) of _draw_combat_panel against a golden, so the M2 panel extraction
    # can be proven structurally identical. Kept with the other oracles for the same
    # reason: a layout regression should fail before the rules suites run.
    "test_combat_panel.py",

    # The legal-action model (MULTIPLAYER_PLAN.md M2, seam S3) — the other half of the
    # panel split: test_combat_panel.py proves the pixels did not move, this proves the
    # availability rules that produced them, with no screen involved. Kept beside it
    # because the pair is only meaningful together.
    "test_action_menu.py",

    # Rendered-geometry invariants for the same panel (MULTIPLAYER_PLAN.md M2) — the
    # third leg. The golden proves the structure did not CHANGE and the action menu
    # proves the rules; this one asks what only pixels can answer: does the label fit
    # the button, do two widgets overlap, is a run stacked or laid out side by side,
    # did the panel actually paint. It found F12, which had been wrong since before
    # M2a and which a structural golden can never see.
    "test_gui_headless_smoke.py",

    # Session roster + token ownership (MULTIPLAYER_PLAN.md M0) — principals, the
    # single authorize() chokepoint, and the `controller` round-trip through a save
    # that renumbers the agent list. Kept with the oracles because it guards a
    # PERSISTED file format: a regression here silently mis-assigns creatures.
    "test_session_roster.py",

    # The prompt bus (MULTIPLAYER_PLAN.md M1) — the first suite that drives a GUI flow
    # with no pygame events: it parks the engine on a real opportunity attack through a
    # real App and answers the window through the bus. Kept with the oracles because it
    # is now the only coverage of main.py's reaction path.
    "test_prompts.py",

    # The GameView projection (MULTIPLAYER_PLAN.md M3, seam S1) — the per-viewer read
    # filter, and the only thing a remote client is ever sent. Kept with the oracles
    # because its acceptance criterion is a BYTE-level assertion: a regression here does
    # not break a feature, it quietly hands a player the enemy they cannot see.
    "test_gameview.py",

    # The masked page image (MULTIPLAYER_PLAN.md M4, D-M4-1) — `GET /map.png`. Kept with
    # the oracles for the same reason as the view: it is the one place the map crosses the
    # wire as ART, so a regression here undoes D-M3-5's filtering in a form no field-level
    # check can see. These read pixels.
    "test_mapimg.py",

    # The route that serves it (MULTIPLAYER_PLAN.md M4, D-M4-1 / D-M4-6) — a real aiohttp
    # server on a real port, driven with stdlib urllib. Kept with the oracles because the
    # render being correct is worth nothing if the middleware hands it to the wrong
    # caller: this is where authentication, the Origin check and the two cache entries are
    # the difference between a masked page and the whole floor plan.
    "test_mapserver.py",

    # The join and the view over the wire (MULTIPLAYER_PLAN.md M4c, D-M4-4 / D-M4c-1..5) —
    # `POST /join` and `GET /state`. Kept with the oracles because `/join` is the ONLY
    # route reachable without proving anything, so its matching order is what decides
    # whose seat a stranger lands in; and because `/state` is the one place a view
    # crosses a thread boundary, where a regression is not a broken feature but
    # `build_view` quietly reading the BattleMap off the pygame thread.
    "test_join.py",
    "test_state.py",

    # The blocking-modal fix (MULTIPLAYER_PLAN.md M4d, D-M4-3 / D-M4d-1..4) — the six
    # nested event loops that used to stall the command queue for as long as a DM read a
    # dialog. Kept with the oracles because the failure it prevents is invisible from the
    # DM's own screen: the app looks fine, and every player's request times out.
    "test_modal_pump.py",

    # The push socket and the client it serves (MULTIPLAYER_PLAN.md M4e, D-M4e-1..4) —
    # `WS /live`, `GET /` and the two files beside it, over a real socket with a hand-rolled
    # WebSocket client. Kept with the oracles because this is the route that authenticates
    # ITSELF: the middleware cannot 401 a browser's handshake (A3), so a regression in the
    # first-frame check hands the whole session to anyone who can reach the port — and
    # because it is the first place the frame tick sends a view nobody asked for, where a
    # projection built on the wrong thread is a silent NN1 violation four times a second.
    "test_live.py",

    # Atomic encounter saves (MULTIPLAYER_PLAN.md standalone item S1) — the two writes a
    # crash could tear. Kept with the oracles because NN7's autosave ring is built on the
    # assumption these are atomic, and the only way to see the fix is to force the write
    # to fail and find the previous save still whole.
    "test_atomic_saves.py",

    # Core mechanics
    "test_conditions.py",
    "test_combat.py",
    "test_helpers.py",
    "test_spells.py",
    "test_total_cover.py",
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
    "test_hold_person_endturn.py",
    "test_incapacitated_movement_restore.py",
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
    "test_npc_analysis.py",
    "test_npc_visual_events.py",
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
    "test_epic_boons_e1.py",
    "test_epic_boons_e2.py",
    "test_epic_boons_e3.py",
    "test_epic_boons_e4.py",
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

    # Bless (SPELLS_TO_WIRE Phase 1: +1d4 to attacks & saves, dies with concentration)
    "test_bless.py",

    # Bane (mirror of Bless: −1d4 to attacks & saves on a failed CHA save, dies with concentration)
    "test_bane.py",

    # Haste (SPELLS_TO_WIRE Phase 2: +2 AC, Adv DEX saves, doubled speed, extra action, end-lethargy)
    "test_haste.py",

    # Aid (SPELLS_TO_WIRE Phase 3: +5 current & max HP per target, +5/upcast level, revives downed)
    "test_aid.py",

    # LIVE_PLAY_BUGFIX_PLAN Phase 4 — L42 DEX layers into AC for PCs (is_npc=False) but not NPCs
    # (published final AC), and reaches the weapon to-hit roll; L40 spell-slot state round-trips.
    "test_ac_dex.py",

    # SPELL_IMPLEMENTATION_PLAN Tier 1 — False Life, Longstrider, Expeditious Retreat, Blur,
    # Barkskin, Ray of Enfeeblement, Enlarge/Reduce, Regenerate, Divine Word, Dominate Monster,
    # Mind Blank, Foresight (buff/debuff Stats flags + condition apply/clear + mechanic hooks)
    "test_spells_tier1.py",

    # Divine Intervention D0 (Cleric L10 free-cast resource; L20 Greater-DI 2d4 Wish lock)
    "test_divine_intervention.py",

    # Dead-vs-Unconscious occupancy split (DI SPEC §10, prereq for D2/D3): corpse frees its
    # square, unconscious body still blocks; engine agent_occupancy + helpers.can_place_agent
    "test_dead_unconscious_occupancy.py",

    # Divine Intervention D2 (Raise Dead / Revivify): revives_dead heal clears conditions.dead
    # and restores a corpse; the flag also drives the GUI corpse-pick mode (SPEC §7 D2, §10.5)
    "test_raise_dead.py",

    # Divine Intervention D3 (Animate Dead / Planar Binding): animates_dead routes the corpse-pick
    # to raise an undead servant; binds_creature routes a Cha-save single-target to a control
    # transfer. Both resolve GUI-side; flag round-trips + JSON wiring here (SPEC §7 D3)
    "test_animate_dead.py",

    # Divine Intervention D4 (Magic Circle): a creature-type movement ward (an emanation the chosen
    # species — Fiend, Fey, … — can't cross), in keep-out and reverse trap-inside modes (SPEC §7 D4)
    "test_magic_circle.py",

    # SPELL_IMPLEMENTATION_PLAN Tier 2 (control / terrain / ward): Eyebite, Irresistible Dance,
    # Reverse Gravity, Symbol, Flesh to Stone, Maze, Imprisonment, Resilient Sphere, Forcecage
    # (save-gated conditions, both fail + save paths), Antilife Shell (ward_all_living), and Wall
    # of Stone (sets_wall solid terrain).
    "test_spells_tier2.py",

    # Dispel Magic (SPELLS_TO_WIRE Phase 4: auto-end level<=slot, else DC 10+level check; clears concentration)
    "test_dispel_magic.py",

    # Wish (duplicate a spell ≤ 8: spend_spell_slot charges the 9th slot, duplicate is a free cast)
    "test_wish.py",

    # --- Previously unregistered suites (added during the tests/ reorg) ---
    "test_advantage_aura.py",
    "test_aoe_shared_roll.py",
    "test_balor_attacks.py",
    "test_pit_fiend.py",
    "test_death_burst.py",
    "test_deny_reactions.py",
    "test_doors.py",
    "test_green_slaad.py",
    "test_npc_multiattack.py",
    "test_permanently_armed.py",
    "test_recharge.py",
    "test_remove_curse.py",
    "test_sanctuary.py",
    "test_short_rest_heal.py",
    "test_warlock_patrons.py",
    "test_weapon_mastery_roundtrip.py",

    # Power Word Kill / Stun HP gates + Mass Heal / Power Word Fortify HP pool
    "test_power_words.py",

    # Multiclassing Phase 2 — per-class level gates (classLevel(cls) >= N, not char_level)
    "test_multiclass_gates.py",

    # Multiclassing Phase 3 — combined-caster-level spell slots (compute_multiclass_slots)
    "test_multiclass_slots.py",

    # Multiclassing Phase 4 — resource-init merge (initialize_multiclass_resources)
    "test_multiclass_resources.py",

    # Multiclassing Phase 5 — GUI save/load round-trip (class_levels + subclasses + merge)
    "test_multiclass_gui_roundtrip.py",
]

def run_tests():
    """Run all test scripts and collect results."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Tests live in tests/ but the compiled rpg_battle_map.so and the data JSONs
    # (spells.json, DND2024_MonsterStats.json, ...) live in gui/. Run each suite
    # with cwd=gui/ so the engine's cwd-relative JSON loads resolve as before.
    gui_dir = os.path.join(os.path.dirname(script_dir), "gui")
    # Silence the C++ map layer's "[BattleMap] …" stdout diagnostics for every suite (covers even
    # tests that don't import test_helpers). Honored by battleMapVerbose() in the engine.
    child_env = os.environ | {"RPG_QUIET": "1"}
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

        result = subprocess.run([sys.executable, script_path], cwd=gui_dir, env=child_env)

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
