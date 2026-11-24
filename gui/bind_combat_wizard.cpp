// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_wizard.cpp  –  pybind11 bindings for CombatEngine (combat_wizard.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Wizard class and subclass features: every bound method implemented in combat_wizard.cpp.
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

void bindCombatWizard(py::class_<CombatEngine>& engine) {
    engine
        .def("use_portent_die",
             &CombatEngine::usePortentDie,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("die_index"), py::arg("current_round"),
             "Use a Portent Die on the next roll (for Diviner Wizards).\n"
             "Validates agent is Diviner, has dice, not used this round.\n"
             "Sets pending_portent_die for CombatEngine::roll() to return.\n"
             "Decrements Portent Dice resource.\n"
             "die_index: 0-based index into agent's portent_dice deque.\n"
             "current_round: for per-round enforcement.\n"
             "Returns true on success, false on validation failure.")
        .def("regenerate_portent_dice",
             &CombatEngine::regeneratePortentDice,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Regenerate Portent Dice pool after long rest (for Diviner Wizards).\n"
             "Rolls new d20s and populates agent's portent_dice deque.")
        .def("expend_arcane_ward_slot",
             &CombatEngine::expendArcaneWardSlot,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("slot_level"),
             "Expend a spell slot as bonus action to charge Arcane Ward (for Abjurer Wizards L3+).\n"
             "Adds 2 × slot_level HP to the ward (capped at max = 2 × level + INT mod).\n"
             "slot_level: 1-9 (spell slot level to expend).\n"
             "Returns true on success, false if agent is not Abjurer L3+ or has no ward.")
        ;
}
