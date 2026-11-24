// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_bard.cpp  –  pybind11 bindings for CombatEngine (combat_bard.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Bard class and subclass features: every bound method implemented in combat_bard.cpp.
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

void bindCombatBard(py::class_<CombatEngine>& engine) {
    engine
        .def("activate_mantle_of_majesty",
             &CombatEngine::activateMantleOfMajesty,
             py::arg("battle_map"), py::arg("bard_idx"),
             "College of Glamour Mantle of Majesty (Bonus Action): spend the once/long-rest 'Mantle of\n"
             "Majesty' use, open a 1-minute (10-round) unearthly-appearance window (stats.mantle_majesty_turns\n"
             "= 10) and start Concentration on 'Mantle of Majesty' (replacing any prior concentration).\n"
             "While active the bard may re-cast Command as a Bonus Action with no slot (SpellAction.free_cast),\n"
             "and a creature Charmed by this bard auto-fails its save vs that Command. The free Command cast\n"
             "is driven separately by the caller. Returns False if not a Glamour Bard L6+ or no use left.")
        .def("bard_restore_mantle_of_majesty_from_slot",
             &CombatEngine::bardRestoreMantleOfMajestyFromSlot,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("slot_level"),
             "Restore the expended Mantle of Majesty use by spending an unused level 3+ spell slot (no\n"
             "action). Returns the resource's new current count, or -1 (not a Glamour Bard L6+, slot_level\n"
             "< 3, no such slot, or already full).")
        .def("activate_unbreakable_majesty",
             &CombatEngine::activateUnbreakableMajesty,
             py::arg("battle_map"), py::arg("bard_idx"),
             "College of Glamour Unbreakable Majesty (Bonus Action, Bard L14+): spend the once/long-rest\n"
             "'Unbreakable Majesty' use, open a 1-minute (10-round) majestic-presence window\n"
             "(stats.majestic_presence_turns = 10) and start Concentration on 'Unbreakable Majesty'\n"
             "(replacing any prior concentration). While active any melee attack against the bard triggers\n"
             "Psychic damage equal to the bard's CHA modifier (min 1) and forces a CHA save vs the bard's\n"
             "spell save DC; on a failure the attacker gains Disadvantage on the next save vs the bard's\n"
             "spells (TODO: full rider). The Psychic damage is applied automatically (no reaction).\n"
             "Returns False if not a Glamour Bard L14+ or no use left.")
        .def("bard_restore_unbreakable_majesty_from_slot",
             &CombatEngine::bardRestoreUnbreakableMajestyFromSlot,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("slot_level"),
             "Restore the expended Unbreakable Majesty use by spending an unused level 3+ spell slot (no\n"
             "action). Returns the resource's new current count, or -1 (not a Glamour Bard L14+, slot_level\n"
             "< 3, no such slot, or already full).")
        .def("bard_beguiling_magic",
             &CombatEngine::bardBeguilingMagic,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("target_idx"), py::arg("use_frightened"),
             "College of Glamour Beguiling Magic (Bard L3+): fire the once/long-rest benefit after the\n"
             "bard casts an Enchantment/Illusion spell with a slot (the caller gates school/slot). Spends\n"
             "the 'Beguiling Magic' resource, then forces a WIS save (vs the bard's spell save DC) on the\n"
             "target within 60 ft; on a failure the target is Charmed (use_frightened=False) or Frightened\n"
             "(True) for 1 minute, repeating the save each of its turns. Returns True if used (resource\n"
             "spent), False if it could not be used (not a L3+ Glamour Bard, no use, bad/out-of-range target).")
        .def("bard_restore_beguiling_magic",
             &CombatEngine::bardRestoreBeguilingMagic,
             py::arg("battle_map"), py::arg("bard_idx"),
             "Restore the expended Beguiling Magic use by spending one Bardic Inspiration use (no action).\n"
             "Returns the resource's new current count, or -1 (not a Glamour Bard L3+, no Bardic Inspiration\n"
             "use, or already full).")
        .def("grant_bardic_die",
             &CombatEngine::grantBardicDie,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("d") = 8,
             "Grant a Bardic Inspiration die of size d (6/8/10/12) to a creature.\n"
             "Overwrites any die it already holds (one at a time, per RAW).\n"
             "Returns true on success, false if the agent index is invalid.")
        .def("use_bardic_die",
             &CombatEngine::useBardicDie,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Spend the held Bardic Inspiration die: rolls it, folds the result into the\n"
             "agent's NEXT d20 Test (roll / roll_advantage / roll_disadvantage / roll_to_hit),\n"
             "then clears the held die. Returns the rolled value (0 if none held).")
        .def("use_bardic_die_for_damage",
             &CombatEngine::useBardicDieForDamage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Combat Inspiration damage mode (Valor Bard L3+, any held die): rolls the held\n"
             "Bardic Inspiration die and folds it into pending_damage_bonus_ so the NEXT\n"
             "weapon damage roll adds it, then clears the held die. Returns the rolled value\n"
             "(0 if no die held).")
        .def("bard_regain_inspiration_from_slot",
             &CombatEngine::bardRegainInspirationFromSlot,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("slot_level"),
             "Font of Inspiration (Bard L5+): expend a spell slot of slot_level to regain\n"
             "one use of Bardic Inspiration. Returns the new count, or -1 on failure\n"
             "(not a L5+ Bard, no such slot, or already at max).")
        .def("apply_superior_inspiration",
             &CombatEngine::applySuperiorInspiration,
             py::arg("battle_map"),
             "Superior Inspiration (Bard L18+): every qualifying Bard regains Bardic\n"
             "Inspiration up to 2 if it has fewer. RNG-free; call once at combat start.")
        .def("bard_cutting_words",
             &CombatEngine::bardCuttingWords,
             py::arg("battle_map"), py::arg("bard_idx"),
             "Cutting Words (College of Lore, L3+): reaction that expends one Bardic\n"
             "Inspiration use to SUBTRACT the die from the next D20 Test (the target's roll).\n"
             "Returns the amount subtracted, or 0 on failure.")
        .def("apply_mantle_of_inspiration",
             &CombatEngine::bardMantleOfInspiration,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("targets"),
             "College of Glamour Mantle of Inspiration (Bonus Action): expend 1 Bardic Inspiration\n"
             "use and roll the Bardic Inspiration die ONCE; each chosen creature gains Temporary HP =\n"
             "twice the roll. 'targets' is a list of agent indices (the GUI validates the 60 ft range\n"
             "per click); the engine caps it to the bard's CHA modifier (min 1) and skips the bard\n"
             "itself. Returns the temp HP granted to each recipient (0 = not a L3+ Glamour Bard / no\n"
             "Bardic Inspiration use).")
        ;
}
