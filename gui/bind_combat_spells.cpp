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
        .def("convert_slot_to_sorcery_points",
             &CombatEngine::convertSlotToSorceryPoints,
             py::arg("battle_map"), py::arg("idx"), py::arg("slot_level"),
             "Font of Magic (L2): convert a remaining spell slot (level 1-9) into that many\n"
             "Sorcery Points (capped at max). Returns the new SP total, or -1 if it could not\n"
             "be done (not a Sorcerer, or no slot of that level).")
        .def("create_spell_slot",
             &CombatEngine::createSpellSlot,
             py::arg("battle_map"), py::arg("idx"), py::arg("slot_level"),
             "Font of Magic (L2): spend Sorcery Points to create a temporary spell slot of\n"
             "level 1-5 (cost 2/3/5/6/7). The slot is cleared at the next long rest. Returns\n"
             "remaining SP, or -1 if it could not be done (not a Sorcerer, or not enough SP).")
        .def("spend_sorcery_points_for_spell",
             &CombatEngine::spendSorceryPointsForSpell,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell_level"),
             "Aberrant Mind L3+ Psionic Sorcery: spend SP equal to spell_level to cast an\n"
             "always-prepared psionic spell without expending a slot (free_cast path).\n"
             "Returns True if SP were spent, False if gating fails (wrong class/subclass/level,\n"
             "spell_level < 1, or insufficient SP).")
        .def_static("metamagic_sp_cost",
                    &CombatEngine::metamagicSpCost,
                    py::arg("option"),
                    "Sorcery Point cost for a Metamagic option (2024 PHB).")
        .def("sorcerer_bend_luck",
             &CombatEngine::sorcererBendLuck,
             py::arg("battle_map"), py::arg("idx"), py::arg("boost"),
             "Bend Luck (Wild Magic Sorcerer L6+): spend 1 Sorcery Point to roll 1d4 and apply\n"
             "it as a bonus (boost=True) or penalty (boost=False) to the next D20 Test. Returns\n"
             "the 1d4 value, or 0 on failure (not a L6+ Wild Magic Sorcerer, or no Sorcery Point).")
        .def("apply_boon_of_fate",
             &CombatEngine::applyBoonOfFate,
             py::arg("battle_map"), py::arg("idx"), py::arg("boost"),
             "Boon of Fate (epic boon — Improve Fate): once per short-or-long rest (refreshed at\n"
             "initiative), roll 2d4 and apply it as a bonus (boost=True) or penalty (boost=False)\n"
             "to the next D20 Test (attack roll or saving throw). Returns the 2d4 value, or 0 on\n"
             "failure (no Boon of Fate feat, or the use is already spent this rest).")
        .def("roll_wild_magic_surge",
             &CombatEngine::rollWildMagicSurge,
             py::arg("battle_map"), py::arg("idx"),
             "Wild Magic Surge (Wild Magic Sorcerer L3+): roll d100 on the curated surge table\n"
             "and return a WildMagicSurgeResult (d100_roll, effect band 1-10, description). The\n"
             "effect is applied by the caller. effect == 0 if not a L3+ Wild Magic Sorcerer.")
        .def_static("wild_magic_surge_description",
                    &CombatEngine::wildMagicSurgeDescription,
                    py::arg("effect"),
                    "Curated Wild Magic Surge table text for an effect band (1-10); '' if out of range.")
        .def("apply_wild_magic_surge_effect",
             &CombatEngine::applyWildMagicSurgeEffect,
             py::arg("battle_map"), py::arg("idx"), py::arg("effect"),
             "Apply the engine-handled part of a surge band. Currently band 1 (Plant Growth —\n"
             "Quartered difficult terrain in a sphere on the caster); other bands return False.")
        .def("activate_tides_of_chaos",
             &CombatEngine::activateTidesOfChaos,
             py::arg("battle_map"), py::arg("idx"),
             "Tides of Chaos (Wild Magic Sorcerer L3+): spend the use to grant Advantage on the\n"
             "caster's next D20 Test. Returns True if spent. Recharges on a long rest or when a\n"
             "Wild Magic Surge fires (see maybe_wild_magic_surge).")
        .def("maybe_wild_magic_surge",
             &CombatEngine::maybeWildMagicSurge,
             py::arg("battle_map"), py::arg("idx"),
             "Wild Magic Surge trigger: call right after a Wild Magic Sorcerer resolves a spell\n"
             "cast with a spell slot. Rolls 1d20 — on a 20, OR automatically if Tides of Chaos is\n"
             "expended, it rolls + applies a surge and recharges Tides of Chaos. Returns the\n"
             "applied WildMagicSurgeResult (effect == 0 if no surge occurred).")
        .def("offer_wild_magic_surge",
             &CombatEngine::offerWildMagicSurge,
             py::arg("battle_map"), py::arg("idx"),
             "Wild Magic Surge OFFER: same trigger as maybe_wild_magic_surge but only rolls, it does\n"
             "not apply. Returns a WildMagicSurgeOffer — with Controlled Chaos (L14) options holds two\n"
             "rolled bands, and with Tamed Surge (L18) can_choose_any lets you pick any band 1-10.\n"
             "Pair with resolve_wild_magic_surge to apply the chosen band.")
        .def("resolve_wild_magic_surge",
             &CombatEngine::resolveWildMagicSurge,
             py::arg("battle_map"), py::arg("idx"), py::arg("effect"), py::arg("tides_expended"),
             "Apply a Wild Magic Surge band (1-10) chosen from a WildMagicSurgeOffer, recharging\n"
             "Tides of Chaos if tides_expended. Returns the applied WildMagicSurgeResult.")
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
        .def("apply_shield",
             &CombatEngine::applyShield,
             py::arg("battle_map"), py::arg("reactor_idx"),
             "Shield (reaction): the reactor casts Shield — spend its lowest L1+ slot + its reaction,\n"
             "gain +5 AC until its next turn and Magic Missile immunity. Returns False if it can't.")
        .def("apply_counterspell",
             &CombatEngine::applyCounterspell,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("caster_idx"),
             "Counterspell (reaction): the counterspeller spends its lowest L3+ slot + reaction; the\n"
             "original caster makes a CON save vs the counterspeller's spell save DC. Returns True iff\n"
             "the cast is countered (save failed) — the spell fizzles but keeps its slot (2024 rules).")
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
        .def("can_countercharm", &CombatEngine::canCountercharm,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("save_target_idx"), py::arg("action"),
             "True iff reactor (L7+ Bard, reaction free, alive, within 30ft+LoS of the save target — or the\n"
             "target itself) may use Countercharm to reroll the failed save, and the spell would apply\n"
             "Charmed or Frightened.")
        .def("can_indomitable", &CombatEngine::canIndomitable,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("save_target_idx"),
             "True iff reactor == save_target, is a L9+ Fighter with >=1 Indomitable use, and is alive\n"
             "(reroll your OWN failed save; costs the use, not the reaction).")
        .def("expend_arcane_ward_slot",
             &CombatEngine::expendArcaneWardSlot,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("slot_level"),
             "Expend a spell slot as bonus action to charge Arcane Ward (for Abjurer Wizards L3+).\n"
             "Adds 2 × slot_level HP to the ward (capped at max = 2 × level + INT mod).\n"
             "slot_level: 1-9 (spell slot level to expend).\n"
             "Returns true on success, false if agent is not Abjurer L3+ or has no ward.")
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
        .def("cure_petrified",
             &CombatEngine::curePetrified,
             py::arg("battle_map"), py::arg("idx"),
             "Reverse the Petrified condition: restore speeds and damage multipliers from the\n"
             "snapshot taken when the creature was petrified.")
        ;
}
