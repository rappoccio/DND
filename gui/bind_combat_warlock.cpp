// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_warlock.cpp  –  pybind11 bindings for CombatEngine (combat_warlock.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Warlock class and subclass features: every bound method implemented in combat_warlock.cpp.
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

void bindCombatWarlock(py::class_<CombatEngine>& engine) {
    engine
        .def("apply_one_with_shadows",
             &CombatEngine::applyOneWithShadows,
             py::arg("battle_map"), py::arg("idx"),
             "One with Shadows (Warlock invocation 8): if standing in Dim Light/Darkness,\n"
             "gain the Invisible condition for free (ends on the Warlock's next attack/cast).\n"
             "Returns True if applied.")
        .def("use_magical_cunning",
             &CombatEngine::useMagicalCunning,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Warlock Magical Cunning: recover expended Pact Magic slots (ceil(max/2), or all at L20).\n"
             "Returns True if used; False if unavailable or nothing to recover.")
        .def("use_healing_light",
             &CombatEngine::useHealingLight,
             py::arg("battle_map"), py::arg("healer_idx"), py::arg("target_idx"), py::arg("num_dice"),
             "Celestial Warlock Healing Light (L3+): spend d6 healing dice.\n"
             "Validates healer is Celestial L3+, clamps num_dice to min(num_dice, current, chaMod).\n"
             "Spends dice from resource, rolls that many d6, heals target.\n"
             "Returns HP healed (0 if invalid).")
        .def("activate_clairvoyant_combatant",
             &CombatEngine::activateClairvoyantCombatant,
             py::arg("battle_map"), py::arg("warlock_idx"), py::arg("target_idx"),
             "Great Old One Warlock L6 — Clairvoyant Combatant (Bonus Action):\n"
             "Make telepathic contact with one creature you can see within 60 ft, forcing a WIS save\n"
             "(DC 8 + CHA mod + PB). On a failure you have Advantage on attack rolls against it and it\n"
             "has Disadvantage on attack rolls against you, until the start of your next turn. Once per\n"
             "short or long rest, or spend a Pact Magic slot to reuse it. Spends a bonus action.\n"
             "Returns True if it activated.")
        .def("steps_of_the_fey",
             &CombatEngine::stepsOfTheFey,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("effect"), py::arg("as_reaction") = false,
             "Archfey Warlock Steps of the Fey (L3+): Bonus-Action Misty Step (30 ft) with no slot,\n"
             "spending one 'Steps of the Fey' use. effect: 0 None, 1 Refreshing (self 1d10 temp HP),\n"
             "2 Taunting (WIS save near departure or Disadvantage attacking anyone but the warlock),\n"
             "3 Disappearing (L6+, self Invisible), 4 Dreadful (L6+, 2d10 psychic near departure on a\n"
             "failed WIS save). Pass as_reaction=True for Misty Escape (L6+): spend the Reaction instead\n"
             "of a Bonus Action in response to taking damage. Returns True iff the teleport happens.")
        .def("bewitching_misty_step",
             &CombatEngine::bewitchingMistyStep,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             py::arg("effect"),
             "Archfey Warlock Bewitching Magic (L14+): a free Misty Step (30 ft, no slot/use/action)\n"
             "cast right after an Enchantment/Illusion action-cast. effect matches steps_of_the_fey\n"
             "(0 None, 1 Refreshing, 2 Taunting, 3 Disappearing, 4 Dreadful). The GUI enforces the\n"
             "'just cast Enchantment/Illusion' timing. Returns True iff the teleport happens.")
        .def("apply_eldritch_smite_effect",
             &CombatEngine::applyEldritchSmiteEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("slot_level"), py::arg("result"),
             "Warlock Eldritch Smite (inv 15, L5+, Pact of the Blade): after a pact-weapon hit\n"
             "(conditions.eldritch_smite_available), spend a Pact Magic slot (slot_level =\n"
             "pact_slot_level()) as a Bonus Action to add (slot_level+1)d8 Force to the AttackResult\n"
             "and target HP, and knock a Huge-or-smaller target Prone. Spends the slot + bonus action,\n"
             "sets the leveled-spell + once-per-turn interlocks. Returns Force dealt, or -1 if not\n"
             "allowed (no pact slot/bonus action, already smited, leveled spell already cast).")
        ;
}
