// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_druid.cpp  –  pybind11 bindings for CombatEngine (combat_druid.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Druid class and subclass features: every bound method implemented in combat_druid.cpp.
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

void bindCombatDruid(py::class_<CombatEngine>& engine) {
    engine
        .def("activate_wild_shape", &CombatEngine::activateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("beast_name"), py::arg("weapons"), py::arg("beast_forms_path") = "",
             "Activate Druid Wild Shape: spend 1 use, swap to beast form stats, grant Temp HP.\n"
             "For Circle of the Moon: Temp HP = 3×level, AC = max(beast_ac, 13+WIS).\n"
             "For other circles: Temp HP = 1×level, AC = beast_ac.\n"
             "weapons: list of Weapon objects for the beast form (padded to >=3 internally).\n"
             "Optional beast_forms_path: if provided, use this path to load beast_forms.json; otherwise try standard locations.")
        .def("deactivate_wild_shape", &CombatEngine::deactivateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wild Shape: restore original AC, STR, DEX, CON, and weapons.")
        .def("activate_starry_form", &CombatEngine::activateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("constellation"),
             "Activate Druid Starry Form (Circle of the Stars): spend 1 Wild Shape use.\n"
             "constellation: 1=Archer, 2=Chalice, 3=Dragon.\n"
             "Dragon at L10+: add fly speed. L14+: add B/P/S resistance.")
        .def("deactivate_starry_form", &CombatEngine::deactivateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Starry Form: restore fly speed and resistances.")
        .def("activate_wrath_of_sea", &CombatEngine::activateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Druid Wrath of the Sea (Circle of the Sea): spend 1 Wild Shape use.\n"
             "At L10+: add fly speed and resistances to Cold/Lightning/Thunder.")
        .def("deactivate_wrath_of_sea", &CombatEngine::deactivateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wrath of the Sea: restore fly speed and resistances.")
        .def("apply_dragon_min_roll", &CombatEngine::applyDragonMinRoll,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("d20_roll"),
             "Apply Dragon Constellation min-roll-10 for CON concentration saves.\n"
             "Returns max(d20_roll, 10) if conditions met, else returns d20_roll unchanged.")
        ;
}
