// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_feats.cpp  –  pybind11 bindings for CombatEngine (combat_feats.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Feats, fighting styles, Epic Boons, Weapon Mastery and species features: every bound method implemented in combat_feats.cpp.
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

void bindCombatFeats(py::class_<CombatEngine>& engine) {
    engine
        .def("apply_merge_with_shadows",
             &CombatEngine::applyMergeWithShadows,
             py::arg("battle_map"), py::arg("idx"),
             "Merge with Shadows (Boon of the Night Spirit): if standing in Dim Light/Darkness,\n"
             "gain the Invisible condition as a Bonus Action (ends when you next act).\n"
             "Returns True if applied.")
        .def("spend_luck_for_advantage",
             &CombatEngine::spendLuckForAdvantage,
             py::arg("battle_map"), py::arg("idx"),
             "Lucky feat: spend one Luck Point to grant the agent Advantage on its next d20\n"
             "Test (consumed by the next d20 roll). Returns False if no points remain.")
        .def("luck_available",
             &CombatEngine::luckAvailable,
             py::arg("battle_map"), py::arg("idx"),
             "Luck Points spendable now: the Lucky feat's plus carried items' (RAVENLOFT M6).")
        .def("apply_telekinetic_shove",
             &CombatEngine::applyTelekineticShove,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"),
             "Telekinetic feat — Telekinetic Shove (Bonus Action): shove a creature within 30 ft.\n"
             "Target makes a STR save (DC = 8 + caster PB + best of INT/WIS/CHA mod); on a failure it\n"
             "is pushed 5 ft away (reuses the Thunderwave knockback). Returns ShoveResult:\n"
             "attacker_roll=DC, defender_roll=save total, success=shove landed.")
        .def("apply_peerless_aim_effect",
             &CombatEngine::applyPeerlessAim,
             py::arg("battle_map"), py::arg("action"), py::arg("result"),
             "Boon of Combat Prowess — Peerless Aim: turn a missed attack (conditions.peerless_aim_available)\n"
             "into a hit, once per turn. Rolls and applies weapon damage and consumes the once-per-turn use.\n"
             "Pass the Attack that missed and its AttackResult (mirrors apply_guided_strike_effect).")
        .def("can_peerless_aim", &CombatEngine::canPeerlessAim,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "True iff attacker_idx holds Boon of Combat Prowess, is alive, and has not yet used the\n"
             "once-per-turn Peerless Aim miss→hit this turn. Caller confirms the attack missed.")
        .def("apply_sentinel_guard",
             &CombatEngine::applySentinelGuard,
             py::arg("battle_map"), py::arg("sentinel_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Sentinel Guardian (OnAllyAttacked bystander reaction): after an adjacent enemy attacks an\n"
             "ally (flagged via the attacker's conditions.sentinel_guard_available), the Sentinel spends\n"
             "its reaction to make a melee attack at the attacker. Returns the counter-attack's\n"
             "AttackResult (invalid if the reaction was already used).")
        .def("apply_topple",
             &CombatEngine::applyTopple,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx") = 0,
             "Weapon Mastery — Topple: after a qualifying hit (conditions.topple_available), the target\n"
             "makes a CON save (DC 8 + attack ability mod + prof) or is knocked Prone. Returns a ToppleResult.")
        .def("apply_punch_and_grab",
             &CombatEngine::applyPunchAndGrab,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Grappler feat — Punch-and-Grab: after an Unarmed-Strike hit in the Attack action\n"
             "(conditions.grappler_punch_grab_available), ALSO attempt a Grapple this attack (normally one\n"
             "or the other), once per turn. Runs through the shared resolveGrapple core (contested check,\n"
             "computed escape DC). Returns the GrappleResult (invalid if the flag wasn't set).")
        .def("apply_interception",
             &CombatEngine::applyInterception,
             py::arg("battle_map"), py::arg("interceptor_idx"), py::arg("target_idx"), py::arg("damage_taken"),
             "Interception fighting style (reaction): spend the interceptor's reaction to prevent\n"
             "(1d10 + Proficiency Bonus) damage to the target, capped at damage_taken (modeled as a\n"
             "heal-back, like Protective Field). Returns the damage prevented, or -1 if it could not be used.")
        ;
}
