// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_monk.cpp  –  pybind11 bindings for CombatEngine (combat_monk.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Monk class and subclass features: every bound method implemented in combat_monk.cpp.
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

void bindCombatMonk(py::class_<CombatEngine>& engine) {
    engine
        .def("shadow_step_teleport",
             &CombatEngine::shadowStepTeleport,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Warrior of Shadow Shadow Step (L6+): Bonus Action teleport up to 30 ft in dim/dark (L6) or\n"
             "any light (L11+). Sets Advantage on next attack. Returns True iff teleport succeeds.")
        .def("cloak_of_shadows",
             &CombatEngine::cloakOfShadows,
             py::arg("battle_map"), py::arg("idx"),
             "Warrior of Shadow Cloak of Shadows (L17): Bonus Action → Invisible in dim/dark. Persists\n"
             "through attacks. Expires on turn start if in bright light. Returns True iff activated.")
        .def("shadow_arts_darkness",
             &CombatEngine::shadowArtsDarkness,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Warrior of Shadow Shadow Arts: Darkness (L3): spend 1 Focus Point to fill a 15-ft-radius\n"
             "Sphere with magical Darkness (1 min). The caster sees through their own Darkness (not\n"
             "Blinded); others inside without Devil's Sight are Blinded. Returns the light-effect id (>=0),\n"
             "or -1 on failure.")
        .def("activate_elemental_attunement",
             &CombatEngine::activateElementalAttunement,
             py::arg("battle_map"), py::arg("idx"), py::arg("element"),
             "Warrior of the Elements Elemental Attunement (L3): Magic action + 1 Focus Point. `element` is\n"
             "a MagicDamage_t (Acid=0/Cold=1/Fire=2/Lightning=4/Thunder=9). Until a short/long rest the Monk's\n"
             "unarmed strikes gain +10 ft reach, deal the chosen element, and can push/pull 10 ft on a hit.\n"
             "Returns True on success.")
        .def("elemental_attunement_move",
             &CombatEngine::elementalAttunementMove,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("pull"),
             "Elemental Attunement push/pull rider: on an unarmed hit while attunement is active, push the\n"
             "target 10 ft away (pull=False) or pull it 10 ft toward the Monk (pull=True). No save. Returns\n"
             "the feet actually moved.")
        .def("elemental_burst",
             &CombatEngine::elementalBurst,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"), py::arg("element"),
             "Warrior of the Elements Elemental Burst (L6): Magic action + 2 Focus Points → a 20-ft-radius\n"
             "Sphere of the chosen element (a MagicDamage_t). Each non-ally creature in the area makes a DEX\n"
             "save vs the Monk's Ki DC (8 + PB + WIS); failure = (Martial Arts die count) × d8, half on a\n"
             "save. Returns True on success.")
        .def("plant_quivering_palm",
             &CombatEngine::plantQuiveringPalm,
             py::arg("battle_map"), py::arg("monk_idx"), py::arg("target_idx"),
             "Monk Way of the Open Hand L17 — Quivering Palm. After an Unarmed Strike hit\n"
             "(conditions.quivering_palm_available), spend 4 Focus Points to plant a delayed-trigger\n"
             "condition on the target (10d12 Force, CON save vs Ki DC for half). Only one creature may\n"
             "be affected at a time. Detonate later with trigger_delayed_effect. Returns True on success.")
        .def("apply_stunning_strike",
             &CombatEngine::applyStunningStrike,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Monk Stunning Strike: after a qualifying unarmed hit (conditions.stunning_strike_available),\n"
             "spend 1 Focus Point and force a CON save (DC 8 + DEX mod + prof) or the target is Stunned.\n"
             "Returns a StunningStrikeResult.")
        .def("apply_open_hand_rider",
             &CombatEngine::applyOpenHandRider,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("option"),
             "Monk Warrior of the Open Hand: after a qualifying Flurry hit (conditions.open_hand_rider_available),\n"
             "spend 1 Focus Point and apply one of three riders: 0=Knockdown (STR save or Prone),\n"
             "1=Push (5 feet), 2=Deny Reaction. Returns an OpenHandRiderResult.")
        .def("hand_of_healing",
             &CombatEngine::handOfHealing,
             py::arg("battle_map"), py::arg("monk_idx"), py::arg("target_idx"), py::arg("free") = false,
             "Monk Warrior of Mercy — Hand of Healing (L3+): a Bonus Action spending 1 Focus Point to heal a\n"
             "creature within reach for (Martial Arts die + WIS mod). At L6 (Physician's Touch) it also ends\n"
             "one of Blinded/Deafened/Paralyzed/Poisoned/Stunned. free=true (only at L11, Flurry of Healing\n"
             "and Harm) folds the heal into a Flurry strike: no Focus Point, no Bonus Action. Returns a\n"
             "HandOfHealingResult.")
        .def("wholeness_of_body",
             &CombatEngine::wholenessOfBody,
             py::arg("battle_map"), py::arg("monk_idx"),
             "Monk Warrior of the Open Hand — Wholeness of Body (L6+): a Bonus Action spending one use of the\n"
             "\"Wholeness of Body\" resource (PB per long rest) to heal yourself (Martial Arts die + WIS mod).\n"
             "Returns the HP restored, or 0 if unavailable.")
        .def("apply_hand_of_harm_effect",
             &CombatEngine::applyHandOfHarmEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("result"),
             "Monk Warrior of Mercy — Hand of Harm (L3+): after a qualifying unarmed hit\n"
             "(conditions.hand_of_harm_available), spend 1 Focus Point and add (Martial Arts die + WIS mod)\n"
             "Necrotic damage to the AttackResult and the target's HP. At L6 (Physician's Touch) the target is\n"
             "also Poisoned. At L11 it is free and may be used once per target. Once per turn below L11.")
        .def("execute_flurry_of_blows",
             &CombatEngine::executeFlurryOfBlows,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("rider_option"),
             "Monk Flurry of Blows: spend 1 Focus Point to make two bonus-action unarmed strikes\n"
             "against the same target, optionally applying an Open Hand rider on each hit.\n"
             "rider_option: -1=None, 0=Knockdown, 1=Push, 2=DenyReaction.\n"
             "Returns a FlurryResult containing both attack results and rider results.")
        ;
}
