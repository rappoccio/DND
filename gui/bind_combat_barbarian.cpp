// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_barbarian.cpp  –  pybind11 bindings for CombatEngine (combat_barbarian.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Barbarian class and subclass features: every bound method implemented in combat_barbarian.cpp.
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

void bindCombatBarbarian(py::class_<CombatEngine>& engine) {
    engine
        .def_static("get_rage_damage_bonus",
                    &CombatEngine::getRageDamageBonus,
                    py::arg("level"),
                    "Get Barbarian Rage damage bonus for a given level.")
        .def("activate_rage",
             &CombatEngine::activateRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Barbarian Rage: set raging=true, apply 0.5x physical damage multipliers (B/P/S), spend 1 Rage use.")
        .def("extend_rage",
             &CombatEngine::extendRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Extend active Rage: reset duration_remaining to full duration.")
        .def("end_rage",
             &CombatEngine::endRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End Barbarian Rage: set raging=false, restore normal damage multipliers, clear reckless_attack.")
        .def("use_intimidating_presence",
             &CombatEngine::useIntimidatingPresence,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Berserker L14 — Intimidating Presence (Bonus Action):\n"
             "Each creature of the Barbarian's choice within a 30-ft emanation makes a WIS save\n"
             "(DC 8 + STR mod + PB) or is Frightened until the end of the Barbarian's next turn.\n"
             "Usable PB times per long rest, or expend one Rage use. Spends a bonus action.")
        .def("use_zealous_presence",
             &CombatEngine::useZealousPresence,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Zealot L10 — Zealous Presence (Bonus Action):\n"
             "Up to 10 creatures of the Barbarian's choice (allies) within 60 ft gain Advantage on\n"
             "attack rolls and saving throws until the start of the Barbarian's next turn.\n"
             "Usable 1 time per long rest, or expend one Rage use. Spends a bonus action.")
        .def("activate_rage_of_the_gods",
             &CombatEngine::activateRageOfTheGods,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Barbarian Path of the Zealot L14 — Rage of the Gods: while raging, assume a divine-warrior\n"
             "form (once per long rest). Grants Fly Speed = Speed (can hover) and Resistance to Necrotic/\n"
             "Psychic/Radiant; enables the Revivification reaction. Ends when Rage ends or at 0 HP.\n"
             "Returns False if not a raging Zealot L14+, or the form was already used this long rest.")
        .def("travel_along_tree",
             &CombatEngine::travelAlongTree,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("long_range") = false,
             "Barbarian Path of the World Tree L14 — Travel along the Tree (Bonus Action while raging):\n"
             "teleport up to 60 ft (or up to 150 ft once per Rage when long_range=True) to a visible,\n"
             "unoccupied space. Spends a bonus action. Returns False if illegal (out of range, occupied,\n"
             "long-range already used this Rage, not a raging World Tree L14+, or no bonus action).")
        .def("apply_retaliation",
             &CombatEngine::applyRetaliation,
             py::arg("battle_map"), py::arg("defender_idx"),
             "Barbarian Path of the Berserker L10 — Retaliation: spend the reaction to make one melee\n"
             "weapon attack back at the creature that just damaged this Barbarian from within 5 ft\n"
             "(flagged via conditions.retaliation_available / retaliation_target_idx). Returns the\n"
             "AttackResult (default/empty if not eligible).")
        .def("can_use_primal_knowledge",
             &CombatEngine::canUsePrimalKnowledge,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("skill_name"),
             "Check if Barbarian can use STR for a skill (Acrobatics/Stealth) while Raging.\n"
             "Returns true if: L3+ Barbarian, Raging, and skill is Acrobatics or Stealth.")
        .def("can_branches_of_tree",
             &CombatEngine::canBranchesOfTree,
             py::arg("battle_map"), py::arg("reactor"), py::arg("source"),
             "True if reactor may use Branches of the Tree (STR-save-or-Grappled) vs source starting its turn in reach.")
        .def("apply_branches_of_tree",
             &CombatEngine::applyBranchesOfTree,
             py::arg("battle_map"), py::arg("reactor"), py::arg("source"),
             "Spend reactor's reaction; source makes a STR save vs the reactor's spell save DC or is Grappled.\n"
             "Returns True iff it grappled the source.")
        .def("can_vitality_of_tree",
             &CombatEngine::canVitalityOfTheTree,
             py::arg("battle_map"), py::arg("source"),
             "True if source (raging World Tree Barbarian L3+) may use Vitality of the Tree at its own turn\n"
             "start: free, once per turn, needs a creature within 10 ft.")
        .def("apply_vitality_of_tree",
             &CombatEngine::applyVitalityOfTheTree,
             py::arg("battle_map"), py::arg("source"), py::arg("target"),
             "Grant target Xd6 temp HP (X = Rage Damage bonus, min 1) with max() semantics, tagged so it\n"
             "vanishes when the source's Rage ends. Sets vitality_used_this_turn. Returns True iff granted.")
        .def("apply_brutal_strike_effect",
             &CombatEngine::applyBrutalStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"), py::arg("result"),
             "Apply Brutal Strike effects: damage + chosen effects (0=Forceful, 1=Hamstring, 2=Staggering, 3=Sundering).\n"
             "Modifies the AttackResult to include brutal strike damage in damage_breakdown and updates total_damage.")
        .def("apply_reckless_reroll",
             &CombatEngine::applyRecklessReroll,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx"),
             "Reckless Attack (Barbarian), post-hoc entry: after a miss flags\n"
             "conditions.reckless_reroll_available, commit Reckless (enemies gain advantage vs you\n"
             "until your next turn) and re-resolve the SAME attack with advantage. Returns the fresh\n"
             "AttackResult (invalid if the flag wasn't set).")
        ;
}
