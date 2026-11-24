// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_cleric.cpp  –  pybind11 bindings for CombatEngine (combat_cleric.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Cleric class and subclass features: every bound method implemented in combat_cleric.cpp.
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

void bindCombatCleric(py::class_<CombatEngine>& engine) {
    engine
        .def("activate_corona_of_light",
             &CombatEngine::activateCoronaOfLight,
             py::arg("battle_map"), py::arg("idx"),
             "Cleric Light Domain — Corona of Light (L17+): Magic action that, for 1 minute (10 rounds),\n"
             "gives enemies within 60 ft Disadvantage on saves vs this caster's Fire/Radiant spells.\n"
             "Returns True if activated, False if not eligible (wrong class/domain/level).")
        .def("use_turn_undead",
             &CombatEngine::useTurnUndead,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Cleric Turn Undead (Channel Divinity, L2+): each Undead within 30 ft makes a WIS save;\n"
             "failures are Frightened + Incapacitated for 1 minute (ends if the undead takes damage).\n"
             "Sear Undead (L5+) deals WIS-mod d8 Radiant (rolled once) to each failed undead.\n"
             "Spends one Channel Divinity use. Returns a TurnUndeadResult.")
        .def("use_preserve_life",
             &CombatEngine::usePreserveLife,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("targets"),
             "Life Domain Preserve Life (Channel Divinity, L3+): distribute 5 x cleric level HP among\n"
             "the chosen creatures within 30 ft (list order = distribution priority), each restored to\n"
             "no more than half its HP maximum. Undead cannot be healed. Supreme Healing does not affect\n"
             "this (no dice). Spends one Channel Divinity use. Returns a PreserveLifeResult.")
        .def("can_path_to_the_grave",
             &CombatEngine::canPathToTheGrave,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("target_idx"),
             "Grave Domain Path to the Grave (L3+): True iff the cleric has a Channel Divinity use and a\n"
             "Bonus Action, and can see the living target within 30 ft.")
        .def("use_path_to_the_grave",
             &CombatEngine::usePathToTheGrave,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("target_idx"),
             "Grave Domain Path to the Grave: spend a Channel Divinity use and the Bonus Action to curse\n"
             "the target until the start of the cleric's next turn (Disadvantage on attack rolls and\n"
             "saving throws). Returns True if the curse was laid.")
        .def("path_to_the_grave_cleric",
             &CombatEngine::pathToTheGraveCleric,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "The cleric who may end its Path to the Grave curse on target_idx to boost a hit by\n"
             "attacker_idx (the cleric itself or an ally it can see), or -1.")
        .def("detonate_path_to_the_grave",
             [](CombatEngine& e, BattleMap& bm, int cleric, int attacker, int target, bool radiant,
                AttackResult& r) {
                 return e.detonatePathToTheGrave(bm, cleric, attacker, target, radiant, &r);
             },
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("radiant"), py::arg("result"),
             "End the Path to the Grave curse early: the hit deals extra Radiant (radiant=True) or\n"
             "Necrotic damage equal to the cleric's level, added to `result` and the target's HP.\n"
             "Returns the damage dealt, or -1 when not eligible.")
        .def("can_keeper_of_souls",
             &CombatEngine::canKeeperOfSouls,
             py::arg("battle_map"), py::arg("cleric_idx"),
             "Grave Domain Keeper of Souls (L17+): True iff the cleric is up, not Incapacitated, and\n"
             "has the use or a level 6+ slot to restore it.")
        .def("keeper_of_souls_targets",
             &CombatEngine::keeperOfSoulsTargets,
             py::arg("battle_map"), py::arg("cleric_idx"),
             "Keeper of Souls recipients: the cleric and the living allies it can see within 60 ft.")
        .def("keeper_of_souls_slot",
             &CombatEngine::keeperOfSoulsSlot,
             py::arg("stats"),
             "Lowest available level 6+ spell slot (0 = none): the cost of restoring Keeper of Souls.")
        .def("use_keeper_of_souls",
             &CombatEngine::useKeeperOfSouls,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("target_idx"), py::arg("slot_level") = 0,
             "Keeper of Souls: target regains 2 x cleric level HP. slot_level 0 spends the use; 6-9\n"
             "spends that slot instead. Clears keeper_of_souls_pending. Returns HP restored or -1.")
        .def("can_enhanced_necromancy",
             &CombatEngine::canEnhancedNecromancy,
             py::arg("caster_stats"), py::arg("spell"), py::arg("slot_level") = 0,
             "Grave Domain Enhanced Necromancy (L17+): True iff a Channel Divinity use can give this\n"
             "single-target Necromancy (level <= 5) or Grave Domain spell a second target.")
        .def("path_to_the_grave_auto_radiant",
             &CombatEngine::pathToTheGraveAutoRadiant,
             py::arg("target_stats"),
             "Auto damage-type choice for Path to the Grave: True (Radiant) unless the target takes\n"
             "more damage from Necrotic.")
        .def("move_duplicate",
             &CombatEngine::moveDuplicate,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("dup_idx"),
             py::arg("target_col"), py::arg("target_row"),
             "Trickery Cleric Invoke Duplicity: move the illusory duplicate up to 30 ft. Returns True iff moved.")
        .def("swap_with_duplicate",
             &CombatEngine::swapWithDuplicate,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("dup_idx"),
             "Trickster's Transposition (L6+): swap the cleric's position with their duplicate. Returns True iff swapped.")
        .def("apply_divine_strike_effect",
             &CombatEngine::applyDivineStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("radiant"), py::arg("result"),
             "Cleric Blessed Strikes — Divine Strike: after a qualifying weapon hit\n"
             "(conditions.divine_strike_available), add 1d8 (2d8 at L14) Radiant (radiant=True) or\n"
             "Necrotic (False) to the AttackResult and target HP; once per turn.")
        .def("can_use_divine_intervention",
             &CombatEngine::canUseDivineIntervention,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Divine Intervention (Cleric L10+): true if agent_idx is a Cleric L10+ with a DI use\n"
             "available (the 'Divine Intervention' resource current > 0) and not under the Greater-DI\n"
             "recharge lock. The GUI gates the DI button on this, not on action_used.")
        .def("use_divine_intervention",
             &CombatEngine::useDivineIntervention,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chose_wish"),
             "Spend one Divine Intervention use. chose_wish=True (Greater DI, L20) applies the\n"
             "2d4-Long-Rest recharge lock. Returns False (no state change) if unavailable. The caller\n"
             "then free-casts the chosen Cleric spell (mirrors the Wish free-cast flow).")
        .def("apply_guided_strike_effect",
             &CombatEngine::applyGuidedStrike,
             py::arg("battle_map"), py::arg("action"), py::arg("cleric_idx"), py::arg("result"),
             "War Domain — Guided Strike: a War Cleric L3+ (the attacker, or an ally within 30 ft who\n"
             "also spends a Reaction) expends Channel Divinity to add +10 to a missed attack roll\n"
             "(conditions.guided_strike_available). If it now meets AC, the miss becomes a hit and\n"
             "weapon damage is rolled and applied. Pass the Attack that missed and its AttackResult.")
        ;
}
