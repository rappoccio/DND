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
        .def("can_adrenaline_rush", &CombatEngine::canAdrenalineRush,
             py::arg("battle_map"), py::arg("idx"),
             "Orc Adrenaline Rush is usable now (a use left, conscious, not Incapacitated).")
        .def("use_adrenaline_rush", &CombatEngine::useAdrenalineRush,
             py::arg("battle_map"), py::arg("idx"),
             "Orc Adrenaline Rush: Dash plus temp HP = PB, one use spent. The caller pays the\n"
             "Bonus Action. Returns False when unavailable.")
        .def("can_draconic_flight", &CombatEngine::canDraconicFlight,
             py::arg("battle_map"), py::arg("idx"),
             "Dragonborn Draconic Flight can start now (level 5+, unused since the Long Rest,\n"
             "not already flying by it, conscious, not Incapacitated).")
        .def("toggle_draconic_flight", &CombatEngine::toggleDraconicFlight,
             py::arg("battle_map"), py::arg("idx"),
             "Dragonborn Draconic Flight: start it (fly Speed = Speed for 100 rounds; the caller\n"
             "pays the Bonus Action) or, while it runs, dismiss it for free. False if neither.")
        // SP6: Goliath
        .def("large_form_origin", &CombatEngine::largeFormOrigin, py::arg("battle_map"), py::arg("idx"),
             "Goliath Large Form: the top-left of a free 2x2 that keeps the token's cell, or\n"
             "Cell(-1, -1) when there is no room.")
        .def("can_large_form", &CombatEngine::canLargeForm, py::arg("battle_map"), py::arg("idx"),
             "Goliath Large Form can start now (level 5+, unused since the Long Rest, Medium or\n"
             "Small, conscious, not Incapacitated). Room is checked when it starts.")
        .def("toggle_large_form", &CombatEngine::toggleLargeForm, py::arg("battle_map"), py::arg("idx"),
             "Goliath Large Form: start it (2x2, +10 ft Speed, 100 rounds; the caller pays the Bonus\n"
             "Action) or, while it runs, end it for free. False if neither (or no room).")
        .def("apply_giant_ancestry_on_hit", &CombatEngine::applyGiantAncestryOnHit,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("result"),
             "Goliath Fire's Burn / Frost's Chill / Hill's Tumble on the offered hit\n"
             "(conditions.giant_ancestry_available): spends a use and adds the rider to result.")
        .def("can_clouds_jaunt", &CombatEngine::canCloudsJaunt, py::arg("battle_map"), py::arg("idx"),
             "Goliath Cloud's Jaunt is available (Cloud ancestry, a use left, able to act).")
        .def("clouds_jaunt", &CombatEngine::cloudsJaunt,
             py::arg("battle_map"), py::arg("idx"), py::arg("col"), py::arg("row"),
             "Goliath Cloud's Jaunt: teleport up to 30 ft to an unoccupied space it can see and\n"
             "spend a use. The caller pays the Bonus Action. False (nothing spent) if refused.")
        .def("can_hellish_rebuke", &CombatEngine::canHellishRebuke,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("attacker_idx"),
             "Hellish Rebuke can be cast now as a reaction against attacker_idx.")
        .def("apply_heroic_reroll", &CombatEngine::applyHeroicReroll,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx"),
             "Heroic Inspiration after a miss (conditions.heroic_reroll_available): spend the ★ and\n"
             "re-resolve the same attack; the new roll stands. Returns the new AttackResult.")
        // MORE_SPECIES_PLAN.md MS3: Reborn Knowledge from a Past Life (D10)
        .def("can_past_life", &CombatEngine::canPastLife, py::arg("battle_map"), py::arg("idx"),
             "The last engine-rolled ability check was idx's, it failed, it has not been re-evaluated\n"
             "and idx (a Reborn) has a Past Life use left: offer +1d6.")
        .def("arm_past_life", &CombatEngine::armPastLife, py::arg("battle_map"), py::arg("idx"),
             "Spend a Past Life use and roll the 1d6 (returned; 0 = refused). Then call the same check\n"
             "again: it replays the recorded d20s (the defender's too) and adds the d6.")
        .def("spend_past_life", &CombatEngine::spendPastLife, py::arg("battle_map"), py::arg("idx"),
             "Tracker button: spend a Past Life use on a check the DM rolled at the table.")
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
        .def("apply_boon_of_fate",
             &CombatEngine::applyBoonOfFate,
             py::arg("battle_map"), py::arg("idx"), py::arg("boost"),
             "Boon of Fate (epic boon — Improve Fate): once per short-or-long rest (refreshed at\n"
             "initiative), roll 2d4 and apply it as a bonus (boost=True) or penalty (boost=False)\n"
             "to the next D20 Test (attack roll or saving throw). Returns the 2d4 value, or 0 on\n"
             "failure (no Boon of Fate feat, or the use is already spent this rest).")
        ;
}
