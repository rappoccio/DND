// ─────────────────────────────────────────────────────────────────────────────
//  bindings_internal.hpp  –  shared declarations for the pybind11 bind_*.cpp TUs
// ─────────────────────────────────────────────────────────────────────────────
//
//  COMBAT_REFACTOR_PLAN.md R1: rpg_bindings.cpp used to be a single ~4,850-line TU
//  (the second god file, touched in 150 of the last 200 commits) holding every
//  pybind11 binding, including one ~1,900-line py::class_<CombatEngine> chain
//  (324 methods). It's now split by domain:
//    - bind_types.cpp            plain value types, enums, results, CombatDecider
//    - bind_combat_attack.cpp    CombatEngine methods implemented in combat_attack.cpp
//    - bind_combat_spells.cpp    CombatEngine methods implemented in combat_spells.cpp
//    - bind_combat_resources.cpp CombatEngine methods implemented in combat_resources.cpp
//    - bind_combat_turn.cpp      everything else CombatEngine-related (turn, movement,
//                                conditions, reactions, NPC automation, state accessors,
//                                rules primitives, visibility)
//    - bind_battle_map.cpp       BattleMap
//  The four bind_combat_*.cpp files all add .def()s to the SAME
//  py::class_<CombatEngine> handle, which rpg_bindings.cpp constructs once and
//  passes to each in turn; bind_types.cpp and bind_battle_map.cpp each take the
//  py::module_ directly since they own their own py::class_/py::enum_ instances.
//
//  No C++ API change, no Python API change — this is purely how the bindings
//  are wired together across translation units.
//
#pragma once

#include <pybind11/pybind11.h>
#include "combat.hpp"

void bindTypes(pybind11::module_& m);
void bindBattleMap(pybind11::module_& m);

void bindCombatAttack(pybind11::class_<rpg::CombatEngine>& engine);
void bindCombatSpells(pybind11::class_<rpg::CombatEngine>& engine);
void bindCombatResources(pybind11::class_<rpg::CombatEngine>& engine);
void bindCombatTurn(pybind11::class_<rpg::CombatEngine>& engine);
