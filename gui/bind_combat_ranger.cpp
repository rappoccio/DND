// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_ranger.cpp  –  pybind11 bindings for CombatEngine (combat_ranger.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Ranger class and subclass features: every bound method implemented in combat_ranger.cpp.
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

void bindCombatRanger(py::class_<CombatEngine>& engine) {
    engine
        .def("apply_dreadful_strike_effect", &CombatEngine::applyDreadfulStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("result"),
             "Gloom Stalker Dreadful Strike: spend a Dread Ambusher use and add 2d6 Psychic (2d8 at L11)\n"
             "to the offered hit (dreadful_strike_available / dreadful_strike_target), into result. At L11\n"
             "leaves stalkers_flurry_pending. Returns True iff the damage was dealt.")
        .def("choose_stalkers_flurry", &CombatEngine::chooseStalkersFlurry,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("option"),
             "Stalker's Flurry (Gloom Stalker L11), after Dreadful Strike: 0 = neither, 1 = Sudden Strike\n"
             "(arms sudden_strike_available), 2 = Mass Fear. Returns True iff a pending choice resolved.")
        .def("apply_mass_fear", &CombatEngine::applyMassFear,
             py::arg("battle_map"), py::arg("ranger_idx"), py::arg("target_idx"),
             "Mass Fear: the target and each other creature within 10 ft of it save (WIS vs the Ranger's\n"
             "spell DC) or are Frightened until the start of the Ranger's next turn. Returns the count.")
        .def("sudden_strike_targets", &CombatEngine::suddenStrikeTargets,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Sudden Strike: indices the armed free attack may strike — a different creature within 5 ft\n"
             "of the Dreadful Strike target, not an ally, in reach/range + LoS of the same weapon.")
        .def("primal_companion_of", &CombatEngine::primalCompanionOf,
             py::arg("battle_map"), py::arg("ranger_idx"),
             "Beast Master: the Ranger's live Primal Companion index, or -1.")
        .def("companion_ranger", &CombatEngine::companionRanger,
             py::arg("battle_map"), py::arg("comp_idx"),
             "Beast Master: the Ranger that owns this Primal Companion, or -1 if it is not one.")
        .def("companion_restricted", &CombatEngine::companionRestricted,
             py::arg("battle_map"), py::arg("comp_idx"),
             "True when this Primal Companion's only action this turn is Dodge (its Ranger is able\n"
             "and did not command it).")
        .def("can_command_companion", &CombatEngine::canCommandCompanion,
             py::arg("battle_map"), py::arg("ranger_idx"),
             "May the Beast Master spend its Bonus Action commanding its companion right now?")
        .def("command_companion", &CombatEngine::commandCompanion,
             py::arg("battle_map"), py::arg("ranger_idx"),
             "Command the Primal Companion (spends the Bonus Action). Returns True iff it was spent.")
        .def("arm_beasts_strike", &CombatEngine::armBeastsStrike,
             py::arg("battle_map"), py::arg("ranger_idx"),
             "Beast's Strike in place of one attack (the caller pays the attack): sets\n"
             "beast_strikes_left (2 with Bestial Fury). Returns True iff armed.")
        .def("beasts_strike_targets", &CombatEngine::beastsStrikeTargets,
             py::arg("battle_map"), py::arg("ranger_idx"),
             "Enemies the Ranger's companion can strike where it stands (reach + LoS).")
        .def("beasts_strike", &CombatEngine::beastsStrike,
             py::arg("battle_map"), py::arg("ranger_idx"), py::arg("target_idx"),
             "One Beast's Strike by the companion against target_idx (spends one of beast_strikes_left).\n"
             "Returns the attack's FlowStatus; Completed (nothing happens) when refused.")
        .def("vanish_orphaned_companions", &CombatEngine::vanishOrphanedCompanions,
             py::arg("battle_map"),
             "Tombstone every Primal Companion whose Ranger has died or left play.")
        .def("condition_save_advantage",
             [](const CombatEngine& e, const BattleMap& bm, int saver, const std::string& cond) {
                 return e.conditionSaveAdvantage(bm, saver, cond);
             },
             py::arg("battle_map"), py::arg("saver"), py::arg("condition_name"),
             "True iff saver has Advantage on a save to avoid or end this condition (Beguiling\n"
             "Twist half, species Brave / Fey Ancestry / Dwarven Resilience, condition_save_adv).")
        .def("beguiling_twist_advantage",
             [](const CombatEngine& e, const BattleMap& bm, int saver, const std::string& cond) {
                 return e.beguilingTwistAdvantage(bm, saver, cond);
             },
             py::arg("battle_map"), py::arg("saver"), py::arg("condition_name"),
             "Beguiling Twist (Fey Wanderer L7): True iff saver has Advantage on a save vs this condition\n"
             "('Charmed' / 'Frightened').")
        .def("charm_fear_save_succeeded", &CombatEngine::charmFearSaveSucceeded,
             py::arg("battle_map"), py::arg("saver"),
             "Beguiling Twist's trigger: saver just succeeded a save to avoid or end Charmed/Frightened.\n"
             "Automated Fey Wanderers react at once; human ones are queued (take_beguiling_twist_offers).")
        .def("can_beguiling_twist", &CombatEngine::canBeguilingTwist,
             py::arg("battle_map"), py::arg("reactor"), py::arg("saver"),
             "May the Fey Wanderer reactor use Beguiling Twist on saver's success right now?")
        .def("beguiling_twist_targets", &CombatEngine::beguilingTwistTargets,
             py::arg("battle_map"), py::arg("reactor"), py::arg("saver"),
             "Beguiling Twist: the creatures (not the saver) the reactor can see within 120 ft.")
        .def("apply_beguiling_twist", &CombatEngine::applyBeguilingTwist,
             py::arg("battle_map"), py::arg("reactor"), py::arg("saver"), py::arg("target"),
             py::arg("frightened"),
             "Beguiling Twist: spend the Reaction; target saves (WIS vs spell DC) or is Charmed /\n"
             "Frightened for 1 minute, repeating the save at the end of each of its turns.")
        .def("take_beguiling_twist_offers", &CombatEngine::takeBeguilingTwistOffers,
             "Drain the queued (reactor, saver) Beguiling Twist offers for human-controlled Rangers.")
        .def("misty_wanderer_allies", &CombatEngine::mistyWandererAllies,
             py::arg("battle_map"), py::arg("idx"),
             "Fey Wanderer L15 Misty Wanderer: the willing creatures within 5 ft who may come along.")
        .def("misty_wanderer_ally_cell", &CombatEngine::mistyWandererAllyCell,
             py::arg("battle_map"), py::arg("ally_idx"), py::arg("ranger_idx"), py::arg("ranger_dest"),
             "First free space within 5 ft of ranger_dest for the passenger (Cell(-1,-1) = none).")
        .def("is_misty_wanderer_ally_cell", &CombatEngine::isMistyWandererAllyCell,
             py::arg("battle_map"), py::arg("ally_idx"), py::arg("dest"), py::arg("ranger_idx"),
             py::arg("ranger_dest"),
             "True if dest is a legal landing space for the passenger beside ranger_dest.")
        .def("misty_wanderer", &CombatEngine::mistyWanderer,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("ally_idx") = -1, py::arg("ally_col") = -1, py::arg("ally_row") = -1,
             "Fey Wanderer L15 Misty Wanderer: a slotless Bonus-Action Misty Step (30 ft), spending one\n"
             "use, optionally bringing ally_idx (within 5 ft) to (ally_col, ally_row) beside the\n"
             "destination (negative = first free space). Returns True iff the Ranger teleported.")
        .def("auto_misty_wanderer", &CombatEngine::autoMistyWanderer,
             py::arg("battle_map"), py::arg("idx"),
             "The NpcDriver's Misty Wanderer: out of melee to the nearest safe cell, with an engaged ally.")
        ;
}
