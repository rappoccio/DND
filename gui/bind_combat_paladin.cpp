// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_paladin.cpp  –  pybind11 bindings for CombatEngine (combat_paladin.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Paladin class and subclass features: every bound method implemented in combat_paladin.cpp.
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

void bindCombatPaladin(py::class_<CombatEngine>& engine) {
    engine
        .def_static("lay_on_hands",
                    &CombatEngine::layOnHands,
                    py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("amount"),
                    "Paladin Lay on Hands: spend from caster's pool to heal target. "
                    "Clamps spend to min(pool_remaining, target_hp_deficit). "
                    "Returns actual HP healed (0 if nothing to heal, -1 if invalid).")
        .def("activate_sacred_weapon",
             &CombatEngine::activateSacredWeapon,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Devotion — Sacred Weapon: spend 1 Channel Oath use to add\n"
             "+CHA mod (min +1) to weapon attack rolls for 1 minute (10 rounds). Requires\n"
             "Oath of Devotion and an available Channel Oath use. Returns the bonus granted,\n"
             "or -1 if it could not be activated.")
        .def("activate_vow_of_enmity",
             &CombatEngine::activateVowOfEnmity,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Paladin Oath of Vengeance — Vow of Enmity: spend 1 Channel Oath use to swear\n"
             "enmity against a visible enemy within 30 ft, gaining Advantage on attacks against\n"
             "it for 1 minute (or until used again). The vow auto-transfers to the nearest enemy\n"
             "within 30 ft if the target dies. Returns True on success, False if not eligible.")
        .def("activate_avenging_angel",
             &CombatEngine::activateAvengingAngel,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Vengeance — Avenging Angel (L20): Bonus Action, 10 minutes. Grants\n"
             "Fly 60 ft (hover) and a Frightful Aura in the Aura of Protection. Costs one Avenging\n"
             "Angel use per long rest, or a level-5 spell slot when exhausted. Returns True on success.")
        .def("activate_elder_champion",
             &CombatEngine::activateElderChampion,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of the Ancients — Elder Champion (L20): Bonus Action, 1 minute. Regain 10 HP\n"
             "each turn start and enemies in your Aura of Protection have Disadvantage on saves vs your\n"
             "spells/Channel Oath. Costs one use per long rest, or a level-5 slot. Returns True on success.")
        .def("activate_inspiring_smite",
             &CombatEngine::activateInspiringSmite,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Paladin Oath of Glory — Inspiring Smite (L3): immediately after a Divine Smite this turn,\n"
             "spend one Channel Oath use to grant a creature within 30 ft (may be self) 2d8 + Paladin\n"
             "level temporary HP. Once per turn. Returns the temp HP granted, or -1 if not allowed.")
        .def("activate_living_legend",
             &CombatEngine::activateLivingLegend,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Glory — Living Legend (L20): Bonus Action, 10 minutes. Grants a save-reroll\n"
             "reaction and once-per-turn Unerring Strike (weapon miss→hit). Costs one use per long rest,\n"
             "or a level-5 spell slot when exhausted. Returns True on success.")
        .def("apply_divine_smite_effect",
             &CombatEngine::applyDivineSmiteEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("slot_level"), py::arg("result"),
             "Paladin Divine Smite: after a melee/unarmed hit (conditions.divine_smite_available),\n"
             "spend a level-slot_level spell slot as a Bonus Action to add (1+min(slot_level,5))d8\n"
             "Radiant, +1d8 vs Undead/Fiend, to the AttackResult and target HP. Spends the slot +\n"
             "bonus action, sets the leveled-spell + once-per-turn interlocks. Returns Radiant dealt,\n"
             "or -1 if not allowed (no slot/bonus action, already smited, leveled spell already cast).")
        .def("apply_soul_of_vengeance",
             &CombatEngine::applySoulOfVengeance,
             py::arg("battle_map"), py::arg("paladin_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Soul of Vengeance (Oath of Vengeance L15): after the sworn foe attacks (flagged via the\n"
             "attacker's conditions.soul_of_vengeance_available), the paladin spends its reaction to make\n"
             "a melee attack at that foe. Returns the counter-attack's AttackResult (invalid if the\n"
             "reaction was already used).")
        ;
}
