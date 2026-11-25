// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_spells.cpp  –  pybind11 bindings for CombatEngine (combat_spells.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Spellcasting: begin_cast/resolve_cast, concentration, dispel, safe targets,
//  sorcery points / metamagic, Wild Magic Surge.
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

void bindCombatSpells(py::class_<CombatEngine>& engine) {
    engine
        .def("begin_cast",
             &CombatEngine::beginCast,
             py::arg("battle_map"), py::arg("action"),
             "GUI/interactive spell cast that opens the OnDeclareCast window before resolving (this\n"
             "pass: Shield vs Magic Missile). Returns FlowStatus: Completed (resolved) or\n"
             "AwaitingDecision (parked — poll pending_decision(), resume via submit_decision()).\n"
             "Read the SpellResult via last_cast_result() once Completed.")
        .def("resolve_cast",
             &CombatEngine::resolveCast,
             py::arg("battle_map"), py::arg("action"),
             "Auto/RL/test driver: run the whole cast, resolving each OnDeclareCast checkpoint inline\n"
             "via the installed CombatDecider. Returns the SpellResult.")
        .def("last_cast_result",
             &CombatEngine::lastCastResult,
             py::return_value_policy::reference_internal,
             "The SpellResult of the most recent begin_cast/resolve_cast (valid once Completed).")
        .def("last_cast_countered",
             &CombatEngine::lastCastCountered,
             "True if the most recent begin_cast/resolve_cast was countered (spell fizzled, slot kept).")
        .def("set_safe_targets",
             &CombatEngine::setSafeTargets,
             py::arg("caster_idx"), py::arg("targets"),
             "Set the agent indices fully excluded from caster_idx's AoE spells (Evoker safe targets).")
        .def("get_safe_targets",
             &CombatEngine::getSafeTargets,
             py::arg("caster_idx"),
             "Get the agent indices excluded from caster_idx's AoE spells.")
        .def("execute_spell",
             &CombatEngine::executeSpell,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute a SpellAction; applies damage/healing to targets\n"
             "and writes HP changes back to BattleMap.\n"
             "Registers persistent effects when spell.duration > 1.")
        .def("drop_concentration",
             &CombatEngine::dropConcentration,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Drop concentration for agent: removes terrain, spell effects, conditions. Returns removed IDs.")
        .def("can_move_hunters_mark",
             &CombatEngine::canMoveHuntersMark,
             py::arg("battle_map"), py::arg("caster_idx"),
             "True iff the caster concentrates on Hunter's Mark / Hex, its marked creature is at 0 HP\n"
             "(or out of play), and the caster has a Bonus Action to move the mark.")
        .def("can_move_hunters_mark_to",
             &CombatEngine::canMoveHuntersMarkTo,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"),
             "can_move_hunters_mark, plus: the target is another living creature the caster can see\n"
             "within 90 ft.")
        .def("move_hunters_mark",
             &CombatEngine::moveHuntersMark,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"),
             "Spend the Bonus Action to move the Hunter's Mark / Hex mark to target_idx. Returns True\n"
             "if the mark moved.")
        .def("dispel_magic",
             &CombatEngine::dispelMagic,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("slot_level"),
             "Dispel Magic: end ongoing spells/conditions on target_idx. Auto-ends effects of level\n"
             "<= slot_level; otherwise rolls d20 + spellcasting mod vs DC 10 + level. Clears a now-empty\n"
             "concentration on the source caster. Normally dispatched from execute_spell (dispels_magic).")
        .def("dispel_magic_at_cell",
             &CombatEngine::dispelMagicAtCell,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("col"), py::arg("row"), py::arg("slot_level"),
             "Cell-aimed Dispel Magic: end ongoing area magic (persistent spell zones like Hunger of\n"
             "Hadar / Cloudkill and spell-sourced difficult terrain like Web / Grease) whose footprint\n"
             "covers (col, row). One roll per source spell; success clears its whole map footprint and a\n"
             "now-empty concentration. Dispatched from execute_spell when dispels_magic has no creature target.")
        .def("dispel_candidates_on_agent",
             &CombatEngine::dispelCandidatesOnAgent,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"),
             "Enumerate the dispellable ongoing spells on a creature (grouped one entry per spell) for\n"
             "the GUI dispel picker. Read-only: rolls no dice and removes nothing. Returns [DispelCandidate].")
        .def("dispel_candidates_at_cell",
             &CombatEngine::dispelCandidatesAtCell,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("col"), py::arg("row"),
             "Enumerate the dispellable area effects (zones + spell-sourced terrain) overlapping a cell,\n"
             "grouped one entry per source spell, for the GUI dispel picker. Read-only. Returns [DispelCandidate].")
        .def("dispel_selected",
             &CombatEngine::dispelSelected,
             py::arg("battle_map"), py::arg("caster_idx"),
             py::arg("condition_ids"), py::arg("spell_effect_ids"), py::arg("terrain_ids"),
             py::arg("slot_level"),
             "Dispel exactly the chosen structures (the picker's selection): the ids are grouped by\n"
             "source spell and each group gets one auto-end-or-check roll; success removes the group and\n"
             "clears a now-empty concentration. Dispatched from execute_spell when a dispels_magic cast\n"
             "carries a selection (SpellAction.dispel_*_ids).")
        .def("clear_all_concentration",
             &CombatEngine::clearAllConcentration,
             py::arg("battle_map"),
             "Drop concentration for every concentrating agent (e.g. on End Combat).")
        .def("tick_effects",
             &CombatEngine::tickEffects,
             py::arg("battle_map"),
             "Apply per-turn damage/healing for active persistent effects;\n"
             "decrement turns_remaining and remove expired effects.")
        .def_property_readonly("active_effects",
             [](const CombatEngine& e) { return e.activeEffects(); },
             "List of ActiveEffect objects currently in play.")
        .def("clear_effects",
             &CombatEngine::clearEffects,
             "Remove all persistent spell effects.")
        .def("concentration_save",
             &CombatEngine::concentrationSave,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("damage_taken"),
             "Check if concentrating agent must save (on damage).\n"
             "Rolls CON save (DC = max(10, damage/2)).\n"
             "Clears concentration on failed save.\n"
             "Returns ConcentrationSaveResult with details.")
        .def("check_concentration_on_damage",
             &CombatEngine::checkConcentrationOnDamage,
             py::arg("battle_map"), py::arg("target_idx"), py::arg("damage"), py::arg("damager_idx") = -1,
             "Roll the target's concentration save on taking `damage` (DC = max(10, damage/2)); on a\n"
             "failure fully drop concentration. War Caster (target feat) grants Advantage; a damager with\n"
             "Mage Slayer (pass damager_idx) imposes Disadvantage (Concentration Breaker). Returns True\n"
             "iff concentration was lost.")
        .def("available_castable_spells",
             &CombatEngine::availableCastableSpells,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Returns indices of spells agent_idx can cast this turn.\n"
             "For NPCs: spells with uses_remaining > 0 (and leveled spell check).\n"
             "For players: spells with available slots at spell.level or higher (and leveled spell check).\n"
             "Cantrips (level 0) always included.")
        .def("get_num_targets_for_spell",
             &CombatEngine::getNumTargetsForSpell,
             py::arg("spell"), py::arg("slot_level"), py::arg("caster_level") = -1,
             py::arg("twinned") = false,
             "Calculate the number of targets for a Multiple geometry spell when cast at given slot level.\n"
             "Formula: spell.num_targets + (slot_level - spell.level) * spell.targets_per_upcast_level\n"
             "For Single geometry: returns 1 (2 if twinned). For AoE: returns 0.\n"
             "caster_level: character level for special cases like Eldritch Blast (default -1 uses slot level formula)\n"
             "twinned: Twinned Spell (Sorcerer Metamagic) grants one additional target this cast")
        .def_static("twinnable_spell", &CombatEngine::twinnableSpell, py::arg("spell"),
             "True when Twinned Spell can apply: a single-target spell, or one that targets an\n"
             "additional creature per upcast level (not Magic Missile / Scorching Ray / Eldritch Blast).")
        .def("effective_spell_range",
             &CombatEngine::effectiveSpellRange,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("spell"),
             "Casting range (ft) for a spell as cast by caster_idx, after range-extending\n"
             "invocations (Eldritch Spear: +30 ft x Warlock level for Eldritch Blast). Returns\n"
             "spell.range unchanged otherwise.")
        .def("cure_curses",
             &CombatEngine::cureCurses,
             py::arg("battle_map"), py::arg("target_idx"),
             "Remove Curse: strip every curse-tracked condition (Vistani Curse of Vulnerability/\n"
             "Weakness/Affliction) from the target. Returns the number of curses cleared.")
        .def("greater_restoration",
             &CombatEngine::greaterRestoration,
             py::arg("battle_map"), py::arg("target_idx"),
             "Greater Restoration: cure curses, end Charmed/Petrified, reduce Exhaustion by one\n"
             "level, and restore any HP-maximum reduction. Returns True if anything changed.")
        ;
}
