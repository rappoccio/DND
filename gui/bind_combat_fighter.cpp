// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_fighter.cpp  –  pybind11 bindings for CombatEngine (combat_fighter.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Fighter class and subclass features: every bound method implemented in combat_fighter.cpp.
//  Split out of bind_combat_resources.cpp / bind_combat_turn.cpp / bind_combat_attack.cpp
//  (COMBAT_CLASS_SPLIT_PLAN.md R6b), mechanical move only. See bindings_internal.hpp
//  for the shared py::class_<CombatEngine> handle each bind_* function adds .def()s to.
//
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/functional.h> // std::function ↔ Python callable

#include "battle_map.hpp"
#include "combat.hpp"
#include "combat_internal.hpp"
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

void bindCombatFighter(py::class_<CombatEngine>& engine) {
    engine
        .def("can_use_war_magic",
             &CombatEngine::canUseWarMagic,
             py::arg("battle_map"), py::arg("idx"),
             "Eldritch Knight War Magic (L7+): true if idx is an EK Fighter L7+ who has not yet used\n"
             "War Magic this Attack action (conditions.war_magic_used). The GUI also requires the EK to\n"
             "be mid Attack action with attacks left; the cast itself goes through execute_spell, then\n"
             "decrements one attack instead of the whole action.")
        .def("mark_war_magic_used",
             &CombatEngine::markWarMagicUsed,
             py::arg("battle_map"), py::arg("idx"),
             "Set the War Magic once-per-Attack-action gate (conditions.war_magic_used). The GUI clears\n"
             "it when a fresh action-attack sequence seeds, so Action Surge's second Attack action allows\n"
             "another substitution.")
        .def("available_war_magic_spells",
             &CombatEngine::availableWarMagicSpells,
             py::arg("battle_map"), py::arg("idx"),
             "Spell indices an Eldritch Knight may cast via War Magic: action-casting-time cantrips\n"
             "(L7+), plus level 1-5 action spells at L18+ (Improved War Magic). Empty for non-EK / <L7.")
        .def("apply_arcane_charge",
             &CombatEngine::applyArcaneCharge,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Eldritch Knight Arcane Charge (L15): teleport up to 30 ft (the optional rider on Action\n"
             "Surge). Validates EK L15+, the 30-ft range, and a clear destination, then teleports.\n"
             "Returns feet moved (>=0) on success, or negative: -1 not eligible, -2 out of range,\n"
             "-3 destination blocked.")
        .def("apply_riposte",
             &CombatEngine::applyRiposte,
             py::arg("battle_map"), py::arg("defender_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Battle Master Riposte (on-miss DEFENDER reaction): after a melee attack misses the\n"
             "defender, flagged via conditions.riposte_available, spend the reaction + 1 Superiority\n"
             "Die to make a melee attack defender→attacker; on a hit, add the Superiority Die to the\n"
             "damage. Returns the riposte AttackResult (invalid if the flag wasn't set / no die / no weapon).")
        .def("apply_psionic_strike_effect",
             &CombatEngine::applyPsionicStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("result"),
             "Psi Warrior Psionic Strike: after a qualifying hit (conditions.psionic_strike_available),\n"
             "spend one Psionic Energy die and add Force damage (die roll + INT mod) to the AttackResult\n"
             "and the target's HP. Once per turn.")
        .def("apply_protective_field",
             &CombatEngine::applyProtectiveField,
             py::arg("battle_map"), py::arg("defender_idx"), py::arg("damage_taken"),
             "Psi Warrior Protective Field (reaction): spend one Psionic Energy die + the defender's\n"
             "reaction to prevent (die roll + INT mod) damage, capped at damage_taken (modeled as a\n"
             "heal-back). Returns the damage prevented, or -1 if it could not be used.")
        .def("apply_telekinetic_movement",
             &CombatEngine::applyTelekineticMovement,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Psi Warrior Telekinetic Movement: spend the once-per-rest use to push a creature up to\n"
             "30 ft straight away from the Psi Warrior. Returns feet moved, or -1 if unavailable.")
        .def("apply_maneuver_effect",
             &CombatEngine::applyManeuverEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("maneuver_type"),
             "Battle Master Maneuver: after a qualifying hit (conditions.maneuver_available),\n"
             "spend 1 Superiority Die and apply one rider (DC = 8 + PB + max(STR,DEX) mod):\n"
             "0=Trip (STR save or Prone), 1=Menacing (WIS save or Frightened), 2=Pushing (15 ft),\n"
             "3=Goading (WIS save or Disadvantage attacking anyone but you), 4=Distracting (next\n"
             "attack vs target by another creature has Advantage), 5=Disarming (STR save or fights\n"
             "with improvised Unarmed Strikes until your next turn).\n"
             "Returns a ManeuverResult with save details / push distance.")
        .def("apply_arcane_shot",
             &CombatEngine::applyArcaneShot,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("target_idx"), py::arg("option"),
             py::arg("result"),
             "Arcane Archer: after a ranged weapon hit (conditions.arcane_shot_available), spend one\n"
             "Arcane Shot use (once per turn) on a known on-hit option (ArcaneShotOption: Banishing,\n"
             "Beguiling, Bursting, Grasping, Shadow). Folds the target's damage into `result`.\n"
             "Returns an ArcaneShotResult.")
        .def("escape_grasping_shot",
             &CombatEngine::escapeGraspingShot,
             py::arg("battle_map"), py::arg("actor_idx"), py::arg("target_idx"),
             "Grasping Shot: STR (Athletics) check vs the Arcane Shot DC by the restrained creature or\n"
             "one within 5 ft; success ends Restrained. The action cost is the caller's.")
        .def("can_use_arcane_shot", &CombatEngine::canUseArcaneShot,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("option"),
             "Arcane Archer: True if the archer knows `option` (ArcaneShotOption), has an Arcane Shot\n"
             "use left and has not used one this turn.")
        .def("piercing_shot_cells", &CombatEngine::piercingShotCells,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("aim_col"), py::arg("aim_row"),
             "Piercing Shot: the cells of the 30-ft line from the archer toward the aim cell\n"
             "(walls don't stop it).")
        .def("piercing_shot", &CombatEngine::piercingShot,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("weapon_idx"),
             py::arg("aim_col"), py::arg("aim_row"),
             "Piercing Shot (replaces an attack, ranged weapon): each creature in the 30-ft line makes a\n"
             "DEX save; fail = weapon damage + 2 dice Piercing, success = half. Returns ArcaneShotSaveResult.")
        .def("seeking_shot_target_valid", &CombatEngine::seekingShotTargetValid,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("weapon_idx"), py::arg("target_idx"),
             "Seeking Shot: True if the creature is within the ranged weapon's long range (no line of\n"
             "sight needed).")
        .def("seeking_shot", &CombatEngine::seekingShot,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("weapon_idx"), py::arg("target_idx"),
             "Seeking Shot (replaces an attack, ranged weapon): the target makes a DEX save; fail =\n"
             "weapon damage + 2 dice Force, success = half the weapon damage. Returns ArcaneShotSaveResult.")
        .def("curving_shot_targets", &CombatEngine::curvingShotTargets,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("original_idx"), py::arg("weapon_idx"),
             "Curving Shot: the creatures a missed ranged shot may be rerolled against (seen by the\n"
             "archer, in the weapon's range, within 60 ft of the original target).")
        .def("apply_curving_shot", &CombatEngine::applyCurvingShot,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("original_idx"),
             py::arg("new_target_idx"), py::arg("weapon_idx"),
             "Curving Shot (Arcane Archer L7): after a ranged miss (conditions.curving_shot_available),\n"
             "spend the Bonus Action and reroll the attack against new_target_idx. Returns the\n"
             "AttackResult (invalid if the offer, target or Bonus Action isn't there).")
        .def("apply_ever_ready_shot", &CombatEngine::applyEverReadyShot, py::arg("battle_map"),
             "Ever-Ready Shot (Arcane Archer L10): at combat start, each archer with no Arcane Shot\n"
             "uses left regains one. RNG-free.")
        .def("can_indomitable_teleport", &CombatEngine::canIndomitableTeleport,
             py::arg("battle_map"), py::arg("idx"),
             "Indomitable Teleport (Arcane Archer L15): the archer is an L15+ Arcane Archer, alive and\n"
             "not Incapacitated. The cast flow opens an AfterSave window after a successful Indomitable.")
        .def("is_indomitable_teleport_destination", &CombatEngine::isIndomitableTeleportDestination,
             py::arg("battle_map"), py::arg("idx"), py::arg("dest"),
             "Indomitable Teleport: an unoccupied cell within 60 ft the archer can see (not its own).")
        .def("apply_indomitable_teleport", &CombatEngine::applyIndomitableTeleport,
             py::arg("battle_map"), py::arg("idx"), py::arg("col"), py::arg("row"),
             "Indomitable Teleport: teleport the archer to (col,row). False if ineligible or illegal.")
        .def("can_masterful_shots", &CombatEngine::canMasterfulShots,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("attacker_idx"),
             "Masterful Shots (Arcane Archer L18): the archer has its Reaction, sees the attacker and\n"
             "carries a Ranged weapon. Offered when the attacker's attack roll misses it.")
        .def("masterful_shots_weapon", &CombatEngine::masterfulShotsWeapon,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("attacker_idx"), py::arg("from_cell"),
             "The Ranged weapon slot that reaches the attacker from from_cell (normal range first), or -1.")
        .def("is_masterful_shots_destination", &CombatEngine::isMasterfulShotsDestination,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("attacker_idx"), py::arg("dest"),
             "Masterful Shots: the archer's own cell, or one reachable on foot within half its Speed,\n"
             "unoccupied and farther from the attacker.")
        .def("masterful_shots_destination", &CombatEngine::masterfulShotsDestination,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("attacker_idx"),
             "Masterful Shots: the engine's cell (in range, farthest from the attacker, shortest move).")
        .def("apply_masterful_shots", &CombatEngine::applyMasterfulShots,
             py::arg("battle_map"), py::arg("archer_idx"), py::arg("attacker_idx"),
             py::arg("col") = -1, py::arg("row") = -1,
             "Masterful Shots: spend the Reaction, move to (col,row) (-1 = the engine's cell) without\n"
             "provoking, then make a ranged attack at the attacker. Returns the AttackResult.")
        .def("held_by_grasping_shot", &CombatEngine::heldByGraspingShot, py::arg("target_idx"),
             "True if the creature is Restrained by a Grasping Shot.")
        .def("apply_sweeping_attack",
             &CombatEngine::applySweepingAttack,
             py::arg("battle_map"), py::arg("action"), py::arg("result"), py::arg("secondary_idx"),
             "Battle Master Sweeping Attack: after a qualifying hit (conditions.maneuver_available),\n"
             "spend 1 Superiority Die to splash the same attack onto a 2nd creature within 5 ft of the\n"
             "original target. If the original attack roll (result.total_roll) would hit the 2nd\n"
             "creature's AC, it takes superiority-die damage of the attack's type. Returns a\n"
             "ManeuverResult (extra_damage / extra_target_down; save_dc=2nd AC, save_roll=orig roll).")
        .def("apply_rally",
             &CombatEngine::applyRally,
             py::arg("battle_map"), py::arg("fighter_idx"), py::arg("target_idx"),
             "Battle Master Rally (Bonus Action): spend 1 Superiority Die to grant a creature within\n"
             "30 ft Temporary HP = superiority die + your CHA modifier (min 1). Returns temp HP granted\n"
             "(0 = no die / bad index).")
        .def("apply_feinting_attack",
             &CombatEngine::applyFeintingAttack,
             py::arg("battle_map"), py::arg("fighter_idx"), py::arg("target_idx"),
             "Battle Master Feinting Attack (Bonus Action): spend 1 Superiority Die to feint a creature\n"
             "within 5 ft — Advantage on your next attack vs it this turn, and that hit adds the die to\n"
             "damage (conditions.feint_target_idx). Returns False if no die.")
        .def("prepare_quick_toss",
             &CombatEngine::prepareQuickToss,
             py::arg("battle_map"), py::arg("fighter_idx"),
             "Battle Master Quick Toss (Bonus Action): spend 1 Superiority Die to arm a superiority-die\n"
             "damage bonus on your next thrown-weapon attack this turn (conditions.quick_toss_die_pending).\n"
             "The GUI then makes the actual thrown attack. Returns False if no die.")
        .def("apply_precision_attack_effect",
             &CombatEngine::applyPrecisionAttackEffect,
             py::arg("battle_map"), py::arg("action"), py::arg("result"),
             "Battle Master Precision Attack: after a non-fumble miss (conditions.maneuver_precision_available),\n"
             "spend 1 Superiority Die, add 1d8/d10 to the roll, and recompute the hit.\n"
             "May convert a miss to a hit with full weapon damage. Mutates result in place.")
        ;
}
