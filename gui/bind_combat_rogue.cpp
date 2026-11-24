// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_rogue.cpp  –  pybind11 bindings for CombatEngine (combat_rogue.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Rogue class and subclass features: every bound method implemented in combat_rogue.cpp.
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

void bindCombatRogue(py::class_<CombatEngine>& engine) {
    engine
        .def("psychic_teleportation",
             &CombatEngine::psychicTeleportation,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Soulknife Soul Blades — Psychic Teleportation (L9): spend 1 Psionic Energy Die, roll it, and\n"
             "teleport up to (10 × roll) ft. Returns True on a successful (in-range, legal) teleport.")
        .def("activate_psychic_veil",
             &CombatEngine::activatePsychicVeil,
             py::arg("battle_map"), py::arg("idx"),
             "Soulknife Psychic Veil (L13): Magic action → Invisible. Once/Long Rest or by 1 Psionic Energy Die.")
        .def("apply_cunning_strike_effect",
             &CombatEngine::applyCunningStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"),
             py::arg("result"), py::arg("round_num") = -1,
             "Apply Rogue Sneak Attack + optional Cunning Strike riders after a qualifying hit\n"
             "(conditions.cunning_strike_available). effects: rider codes (0=Poison, 1=Trip, 2=Withdraw,\n"
             "4=KnockOut, 5=Obscure, 6=Stealth Attack [Thief]); empty = full Sneak Attack with no rider.\n"
             "Rolls (sneak dice − cost)d6, folds it into the AttackResult and target HP, then applies riders.\n"
             "round_num (0 = first round) drives the Assassin subclass round-1 features: Assassinate\n"
             "(+level damage), Envenom Weapons (free Poison rider + 2d6), Death Strike (CON save → double).")
        .def("apply_homing_strike",
             &CombatEngine::applyHomingStrike,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("weapon_idx"), py::arg("result"),
             "Soulknife Soul Blades — Homing Strikes (L9): convert a missed Psychic-Blade attack to a hit\n"
             "by adding a Psionic Energy Die to the roll (die spent only if it converts). Returns True iff hit.")
        .def("can_rend_mind",
             &CombatEngine::canRendMind,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Soulknife Rend Mind (L17) availability: L17+ Soulknife with a Rend Mind use or ≥3 Psionic Energy Dice.")
        .def("apply_rend_mind",
             &CombatEngine::applyRendMind,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Soulknife Rend Mind (L17): after a Psychic-Blade Sneak Attack, WIS save (DC 8+DEX+PB) or Stunned\n"
             "1 minute. Costs a Rend Mind use or 3 Psionic Energy Dice. Returns True iff the target is Stunned.")
        ;
}
