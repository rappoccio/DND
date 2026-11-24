// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_sorcerer.cpp  –  pybind11 bindings for CombatEngine (combat_sorcerer.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Sorcerer class and subclass features: every bound method implemented in combat_sorcerer.cpp.
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

void bindCombatSorcerer(py::class_<CombatEngine>& engine) {
    engine
        .def("activate_innate_sorcery",
             &CombatEngine::activateInnateSorcery,
             py::arg("battle_map"), py::arg("idx"),
             "Sorcerer Innate Sorcery (L1): Bonus Action, spend 1 use to gain +1 spell save\n"
             "DC and advantage on spell attack rolls for 1 minute (10 rounds). Sorcery Incarnate\n"
             "(L7): with no uses left, 2 Sorcery Points activate it instead. Returns True if\n"
             "activated, False otherwise (not a Sorcerer, or no use / no 2 SP fallback).")
        .def_static("sorcery_incarnate_active",
                    &CombatEngine::sorceryIncarnateActive,
                    py::arg("stats"),
                    "Sorcery Incarnate (Sorcerer L7): True while a level-7+ Sorcerer has Innate\n"
                    "Sorcery running. While it is, a cast may carry TWO Metamagic options\n"
                    "(SpellAction.metamagic + .metamagic2).")
        .def("activate_dragon_wings",
             &CombatEngine::activateDragonWings,
             py::arg("battle_map"), py::arg("idx"),
             "Draconic L14 Dragon Wings: toggle fly speed = walk speed (no concentration).\n"
             "First call extends wings (dragon_wings_active=True, speed_fly=speed_walk).\n"
             "Second call retracts them (dragon_wings_active=False, speed_fly=0).\n"
             "Returns True if the agent is a Draconic Sorcerer L14+, False otherwise.")
        .def("activate_draconic_resistance",
             &CombatEngine::activateDraconicResistance,
             py::arg("battle_map"), py::arg("idx"),
             "Draconic L6 Elemental Affinity — Resistance: spend 1 SP to gain resistance\n"
             "(0.5x multiplier) to the chosen element for 1 hour (600 rounds).\n"
             "Returns True if activated, False if gating fails (wrong class/subclass/level,\n"
             "affinity_type unset, resistance already active, or insufficient SP).")
        .def("activate_trance_of_order",
             &CombatEngine::activateTranceOfOrder,
             py::arg("battle_map"), py::arg("idx"),
             "Trance of Order (Clockwork Sorcerer L14+, Bonus Action): for 1 minute attacks against\n"
             "you can't benefit from Advantage and you treat your own d20 of 9-or-lower as a 10 on\n"
             "D20 Tests. Free 1/long rest (the 'Trance of Order' Resource), else 5 Sorcery Points.\n"
             "Sets trance_of_order_turns=10 and spends the bonus action. Returns True if used.")
        .def("activate_bastion_of_law",
             &CombatEngine::activateBastionOfLaw,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("sp"),
             "Bastion of Law (Clockwork Sorcerer L6+, Magic Action): spend 1-5 Sorcery Points to ward\n"
             "the caster or a creature within 30 ft with a pre-rolled (sp)d8 damage-absorption pool\n"
             "(Stats.bastion_ward), overwriting any prior ward. Returns the ward total rolled, or -1\n"
             "on failure (gating / range / not enough Sorcery Points).")
        .def("clockwork_cavalcade",
             &CombatEngine::clockworkCavalcade,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Clockwork Cavalcade (Clockwork Sorcerer L18+, Magic Action): the caster and each ally\n"
             "within 30 ft regain 100 HP and have their active spell conditions ended. Free 1/long\n"
             "rest (the 'Clockwork Cavalcade' Resource), else 7 Sorcery Points. Returns the number of\n"
             "creatures affected, or -1 on failure.")
        .def("activate_revelation_in_flesh",
             &CombatEngine::activateRevelationInFlesh,
             py::arg("battle_map"), py::arg("idx"),
             "Revelation in Flesh (Aberrant Mind Sorcerer L14+, Bonus Action): spend 1 Sorcery Point to\n"
             "transform for 10 minutes (100 rounds) — fly+hover (speed_fly=walk), swim (speed_swim=walk),\n"
             "and truesight 60 ft (see Invisible). Prior speeds/truesight are restored on expiry / long\n"
             "rest. Returns True if activated (False if gated, already active, or no Sorcery Point).")
        .def("warping_implosion",
             &CombatEngine::warpingImplosion,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("dest_col"), py::arg("dest_row"),
             "Warping Implosion (Aberrant Mind Sorcerer L18+): teleport the caster to (dest_col,dest_row)\n"
             "within 120 ft, then every OTHER creature within 30 ft of the space it left makes a DEX save\n"
             "vs the caster's spell DC, taking 3d10 Force (half on a success). Free 1/long rest (the\n"
             "'Warping Implosion' Resource), else 5 Sorcery Points. Returns the number of creatures\n"
             "damaged, or -1 on failure (gating / range / blocked dest / no use & < 5 SP).")
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
        .def("arm_tides_for_initiative",
             &CombatEngine::armTidesForInitiative,
             py::arg("battle_map"), py::arg("idx"),
             "Tides of Chaos spent on the caster's coming Initiative roll instead: same check and\n"
             "spend as activate_tides_of_chaos, but the Advantage is held for this agent and used\n"
             "by roll_initiative / roll_initiative_for. Returns True if spent.")
        .def("spend_sorcery_points_for_spell",
             &CombatEngine::spendSorceryPointsForSpell,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell_level"),
             "Aberrant Mind L3+ Psionic Sorcery: spend SP equal to spell_level to cast an\n"
             "always-prepared psionic spell without expending a slot (free_cast path).\n"
             "Returns True if SP were spent, False if gating fails (wrong class/subclass/level,\n"
             "spell_level < 1, or insufficient SP).")
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
        .def("clear_wild_magic_surge_effects",
             &CombatEngine::clearWildMagicSurgeEffects,
             py::arg("battle_map"),
             "End every lingering Wild Magic Surge effect on every agent (End Combat): shield\n"
             "(and its +2 AC), regen, bonus-action casting, teleport, skip-next-turn, extra action.")
        ;
}
