// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_resources.cpp  –  pybind11 bindings for CombatEngine (combat_resources.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Shared resource plumbing: healing, the bonus-action budget, items, light ticks and
//  rests. Class features are bound in bind_combat_<class>.cpp, beside the
//  combat_<class>.cpp that implements them (COMBAT_CLASS_SPLIT_PLAN.md R6b).
//
//  Split out of rpg_bindings.cpp (COMBAT_REFACTOR_PLAN.md R1) — mechanical move only,
//  no binding behavior changed. See bindings_internal.hpp for the shared
//  py::class_<CombatEngine> handle each bind_* function adds .def()s to.
//
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/functional.h> // std::function ↔ Python callable (NPC render-attack hook)

#include "battle_map.hpp"
#include "combat.hpp"
#include "combat_internal.hpp"   // footprintDistance — shared with the combat_*.cpp TUs
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

void bindCombatResources(py::class_<CombatEngine>& engine) {
    engine
        .def_static("heal_agent",
                    &CombatEngine::healAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Raise hp_cur of agent[idx] by amount (clamped to hp_max). "
                    "A downed creature healed above 0 HP returns to consciousness. "
                    "Returns new hp_cur.")
        .def("regain_slot_from_item",
             &CombatEngine::regainSlotFromItem,
             py::arg("battle_map"), py::arg("idx"),
             "RAVENLOFT M10: an item (Rod of the Pact Keeper) regains one expended spell slot,\n"
             "once per long rest. Returns the level regained, 0 if none.")
        .def("tick_terrain_for_turn",
             &CombatEngine::tickTerrainForTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Tick the agent's terrain at start of turn; clears concentration if a concentration terrain expired.\n"
             "Returns TerrainTickResult(expired_terrain_ids, concentration).")
        .def("tick_light_effects_for_turn",
             &CombatEngine::tickLightEffectsForTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Phase 3: Tick light effects (Darkness, fog spells) at turn start. Expires effects and re-evaluates blinding.")
        .def("spend_resource",
             &CombatEngine::spendResource,
             py::arg("battle_map"), py::arg("idx"), py::arg("name"), py::arg("amount") = 1,
             "Spend a named class resource (e.g. 'War Priest', 'Superiority Dice'); returns True if\n"
             "the agent had >= amount and it was spent. Generic cost helper for extra-attack/maneuver\n"
             "features (the attack itself goes through execute_action).")
        .def("can_sentinel_at_deaths_door",
             &CombatEngine::canSentinelAtDeathsDoor,
             py::arg("battle_map"), py::arg("cleric_idx"), py::arg("target_idx"),
             "Grave Domain Sentinel at Death's Door (L6+): True iff the cleric has a use and its reaction\n"
             "and the hit creature is the cleric itself or a Bloodied ally it can see within 60 ft.\n"
             "Offered in the attack flow (OnHit window, after the defender's own reactions).")
        .def("has_bonus_action",
             &CombatEngine::hasBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True if the agent still has a bonus action this turn (bonus_actions_remaining > 0).\n"
             "Gate every Bonus Action feature (off-hand attack, Cunning Action, Rage, Healing\n"
             "Word, Divine Smite, etc.) on this before offering it.")
        .def("spend_bonus_action",
             &CombatEngine::spendBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Spend one bonus action if available; returns true if spent, false if none remained.")
        .def("reset_bonus_actions",
             &CombatEngine::resetBonusActions,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Refill bonus_actions_remaining = bonus_actions_max (done automatically each turn).")
        .def("apply_long_rest",
             &CombatEngine::applyLongRest,
             py::arg("battle_map"),
             "Apply long rest to all agents: restore spell slots, resources,\n"
             "and regenerate Portent Dice for Diviner Wizards.")
        .def("apply_short_rest",
             &CombatEngine::applyShortRest,
             py::arg("battle_map"),
             "Apply short rest to all agents: restore short-rest resources\n"
             "(Warlock Pact Magic slots, Monk Ki, etc.).")
        .def("use_item",
             &CombatEngine::useItem,
             py::arg("battle_map"), py::arg("user_idx"), py::arg("item_slot"), py::arg("target_idx"),
             "Use the carried item in inventory slot item_slot on target_idx (may be user_idx itself).\n"
             "Enforces the item's range (0 = self only), that the user can act, and its action cost\n"
             "(a BonusAction item spends the user's Bonus Action). A Heal item rolls its dice and heals\n"
             "through heal_agent, so a potion given to a downed ally revives it. Spends one charge and\n"
             "drops the row when the last one is used. Returns a UseItemResult (valid=False = nothing\n"
             "happened and nothing was spent).\n"
             "A Thrown item (Acid, Alchemist's Fire, Holy Water, Net) instead makes the target roll a\n"
             "DEX save vs 8 + the thrower's DEX modifier + PB; on a failure it deals its damage and/or\n"
             "applies its condition. The flask is spent whether or not the target saves, and the caller\n"
             "pays for it out of the Attack action (action_type == AttackReplacement).")
        ;
}
