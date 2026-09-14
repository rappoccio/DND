// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_attack.cpp  –  pybind11 bindings for CombatEngine (combat_attack.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Attack resolution: to-hit/damage rolls, execute_action/begin_attack/resolve_attack,
//  class-feature attack riders (Sneak Attack, Divine Smite, martial maneuvers, …).
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

void bindCombatAttack(py::class_<CombatEngine>& engine) {
    engine
        .def_static("can_attack",
                    &CombatEngine::canAttack,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    py::arg("as_throw") = false,
                    "True iff weapon can reach target with LoS. as_throw: hurl a Thrown weapon "
                    "(reaches long_range_ft instead of reach_ft).")
        .def_static("has_disadvantage",
                    &CombatEngine::hasDisadvantage,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    py::arg("as_throw") = false,
                    "True iff the attack should be rolled at disadvantage (long range).")
        .def("damage_agent",
                    &CombatEngine::damageAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Reduce hp_cur of agent[idx] by amount (clamped to 0). "
                    "Returns new hp_cur.")
        .def("roll_to_hit",
             &CombatEngine::rollToHit,
             py::arg("weapon"), py::arg("attacker_stats"),
             py::arg("target_ac"), py::arg("advantage") = false,
             py::arg("disadvantage") = false, py::arg("exhaustion_level") = 0,
             "Roll d20 + modifier vs AC.  Does not apply damage.")
        .def("resolve_attack",
             // Wrapper keeps the 6-arg Python API stable — the engine-internal bm/target_idx
             // (Shadowy Form light gate) default off for this direct convenience binding.
             [](CombatEngine& self, const Weapon& w, const Agent& attacker, const Agent& target,
                bool advantage, bool disadvantage, bool suppress_positive_mod) {
                 return self.resolveAttack(w, attacker, target, advantage, disadvantage,
                                           suppress_positive_mod);
             },
             py::arg("weapon"), py::arg("attacker"), py::arg("target"),
             py::arg("advantage") = false, py::arg("disadvantage") = false,
             py::arg("suppress_positive_mod") = false,
             "Roll to hit, roll damage, and apply damage to target. "
             "Applies Barbarian Rage bonus, temporary HP absorption, etc. "
             "suppress_positive_mod drops a positive ability modifier from damage (Cleave).")
        .def("execute_action",
             &CombatEngine::executeAction,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute an Attack; writes HP change to BattleMap.")
        .def("begin_attack",
             &CombatEngine::beginAttack,
             py::arg("battle_map"), py::arg("action"),
             "GUI/interactive weapon attack that rolls, then opens the OnHit window so the target may\n"
             "cast Shield (+5 AC) to negate the hit before damage. Returns FlowStatus: Completed\n"
             "(resolved) or AwaitingDecision (parked — poll pending_decision(), resume via\n"
             "submit_decision()). Read the AttackResult via last_attack_result() once Completed.\n"
             "The auto/RL path stays on execute_action (inline Shield via the installed decider).")
        .def("last_attack_result",
             &CombatEngine::lastAttackResult,
             py::return_value_policy::reference_internal,
             "The AttackResult of the most recent begin_attack flow (valid once Completed).")
        .def("threatening_agents",
             &CombatEngine::threateningAgents,
             py::arg("battle_map"), py::arg("target_idx"), py::arg("reach_cells") = 1,
             "Indices of non-incapacitated agents within reach_cells of target's footprint.")
        .def("pending_auto_grapple_strike",
             &CombatEngine::pendingAutoGrappleStrike,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Vampire-Bite auto-use intent: return the (weapon_slot, victim_idx) of a weapon flagged\n"
             "auto_use_when_grappling fired at a creature the attacker is currently Grappling (alive, in\n"
             "reach), or (-1, -1) if none. Manual play offers this as a one-click Bite; NPC automation\n"
             "auto-attempts it. Resolution (CON save / auto-hit / drain) is unchanged.")
        .def("can_guided_strike", &CombatEngine::canGuidedStrike,
             py::arg("battle_map"), py::arg("action"), py::arg("cleric_idx"),
             "True iff cleric_idx (War Domain L3+ with a Channel Divinity use; the attacker itself, or an\n"
             "ally within 30 ft whose reaction is free) may Guided-Strike action's miss. Eligibility gate\n"
             "shared by the GUI flag and the auto/RL OnMiss window (maybeGuidedStrikeInline).")
        .def("can_uncanny_dodge", &CombatEngine::canUncannyDodge,
             py::arg("battle_map"), py::arg("target_idx"),
             "True iff target_idx (Rogue L5+, reaction free, not incapacitated, alive) may use Uncanny\n"
             "Dodge to halve an attack's damage. Eligibility gate for the OnHit defender window.")
        .def("apply_uncanny_dodge", &CombatEngine::applyUncannyDodge,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Uncanny Dodge (on-hit DEFENDER reaction): halve result.total_damage (round down), spend the\n"
             "reactor's reaction, and record the reduction in result.damage_breakdown. Re-validates\n"
             "can_uncanny_dodge. Returns True iff applied. The OnHit window (begin_attack/submit_decision)\n"
             "drives this for the GUI; auto/RL runs it inline via maybeDefenderOnHitInline.")
        .def("can_superior_hunter_defense", &CombatEngine::canSuperiorHunterDefense,
             py::arg("battle_map"), py::arg("target_idx"),
             "True iff target_idx (Hunter Ranger L15+, reaction free, not incapacitated, alive) may use\n"
             "Superior Hunter's Defense to resist (halve) the triggering damage. OnHit defender window gate.")
        .def("apply_superior_hunter_defense", &CombatEngine::applySuperiorHunterDefense,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Superior Hunter's Defense (on-hit DEFENDER reaction): halve result.total_damage (round down),\n"
             "spend the reactor's reaction, record the reduction. Re-validates can_superior_hunter_defense.\n"
             "Returns True iff applied. Same OnHit-window plumbing as Uncanny Dodge.")
        .def("can_deflect_attacks", &CombatEngine::canDeflectAttacks,
             py::arg("battle_map"), py::arg("defender_idx"),
             "True iff defender_idx (Monk L3+, reaction free, not incapacitated, alive) may use Deflect\n"
             "Attacks. The damage-type gate (B/P/S only below L13; any type at L13 Deflect Energy) is\n"
             "enforced in apply_deflect_attacks and at the OnHit-window offer site.")
        .def("apply_deflect_attacks", &CombatEngine::applyDeflectAttacks,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Deflect Attacks / Deflect Energy (on-hit DEFENDER reaction): reduce result.total_damage by\n"
             "1d10 + DEX modifier + Monk level, spend the reactor's reaction, record the reduction. Only an\n"
             "attack dealing B/P/S below L13; any damage type at L13+. Re-validates can_deflect_attacks and\n"
             "the type gate. Returns True iff applied. Same OnHit-window plumbing as Uncanny Dodge.")
        .def("can_parry", &CombatEngine::canParry,
             py::arg("battle_map"), py::arg("defender_idx"),
             "True iff defender_idx (Battle Master, Superiority Die left, reaction free, not incapacitated,\n"
             "alive) may Parry. The melee-attack gate is applied at the OnHit-window call site.")
        .def("apply_parry", &CombatEngine::applyParry,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Battle Master Parry (on-hit DEFENDER reaction vs a melee hit): reduce result.total_damage by\n"
             "(superiority die + DEX mod), spend the reaction + 1 die, record the reduction in\n"
             "result.damage_breakdown. Returns True iff applied. Same OnHit-window plumbing as Uncanny Dodge.")
        .def("can_defensive_duelist", &CombatEngine::canDefensiveDuelist,
             py::arg("battle_map"), py::arg("action"), py::arg("result"),
             "True iff action's target may use Defensive Duelist vs the just-resolved attack: has the feat,\n"
             "reaction free, wields a Finesse melee weapon, the attack is melee and a non-crit hit, and +PB\n"
             "to AC would flip it to a miss. Eligibility gate for the OnHit defender window.")
        .def("apply_defensive_duelist", &CombatEngine::applyDefensiveDuelist,
             py::arg("battle_map"), py::arg("reactor_idx"),
             "Defensive Duelist (on-hit DEFENDER reaction): spend the reactor's reaction so its +PB AC\n"
             "negates the attack. The caller flips result.hit to a miss. Returns True iff the reaction fired.")
        .def("can_sentinel_guard", &CombatEngine::canSentinelGuard,
             py::arg("battle_map"), py::arg("action"), py::arg("sentinel_idx"),
             "True iff sentinel_idx (has the Sentinel feat, reaction free, alive, a melee weapon, the\n"
             "attacker within 5 ft, and neither the attacker nor action's target is itself — RAW: the\n"
             "target must not have the feat) may use Guardian to counter-attack action's attacker.\n"
             "Eligibility gate shared by the GUI flag and the auto/RL OnAllyAttacked window.")
        .def("can_glorious_defense", &CombatEngine::canGloriousDefense,
             py::arg("battle_map"), py::arg("action"), py::arg("result"), py::arg("pal_idx"),
             "True iff pal_idx (L15+ Oath of Glory paladin, a Glorious Defense use, reaction free) may\n"
             "add +CHA AC to the hit creature (itself or an ally within 10 ft) to flip this hit to a\n"
             "miss — only when the boost actually would flip it.")
        .def("can_soul_of_vengeance", &CombatEngine::canSoulOfVengeance,
             py::arg("battle_map"), py::arg("action"), py::arg("pal_idx"),
             "True iff pal_idx (L15+ Oath of Vengeance paladin, active Vow of Enmity on action's\n"
             "attacker, reaction free, a melee weapon, and the sworn foe within 5 ft) may use Soul of\n"
             "Vengeance to counter-strike. Shared by the GUI flag and the auto/RL OnAllyAttacked window.")
        .def("can_bend_luck", &CombatEngine::canBendLuck,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"),
             "True iff reactor (L6+ Wild Magic Sorcerer, >=1 Sorcery Point, reaction free, within 60ft\n"
             "+ LoS of the roller) may use Bend Luck on the roller's attack roll.")
        .def("can_cutting_words", &CombatEngine::canCuttingWords,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"),
             "True iff reactor (L3+ College of Lore Bard, >=1 Bardic Inspiration, reaction free, 60ft+LoS)\n"
             "may use Cutting Words on the roller's attack roll.")
        .def("can_silvery_barbs", &CombatEngine::canSilveryBarbs,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"),
             "True iff reactor knows Silvery Barbs, has a L1+ slot, reaction free, 60ft+LoS of the roller.")
        .def("can_warding_flare", &CombatEngine::canWardingFlare,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"), py::arg("target_idx"),
             "True iff reactor (L3+ Light Domain Cleric, >=1 Warding Flare use, reaction free, within\n"
             "30ft + LoS of the roller) may use Warding Flare on the roller's attack roll. Team-gated:\n"
             "the attack's target must be the reactor itself or one of its allies.")
        .def("can_restore_balance", &CombatEngine::canRestoreBalance,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"), py::arg("result"),
             "True iff reactor (L3+ Clockwork Soul Sorcerer, >=1 Restore Balance use, reaction free,\n"
             "within 60ft + LoS of the roller) may cancel advantage on the roller's attack roll. Offered\n"
             "only when the roll was made at advantage (result.advantage && not result.disadvantage).")
        .def("apply_restore_balance_to_attack", &CombatEngine::applyRestoreBalanceToAttack,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Spend 1 Restore Balance use + reaction; cancel advantage by reverting result.d20 to\n"
             "result.d20_primary and re-evaluate hit/crit. Mutates `result`. Returns True if applied.")
        .def("can_restore_balance_miss", &CombatEngine::canRestoreBalanceMiss,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("roller_idx"), py::arg("result"),
             "True iff reactor (L3+ Clockwork Soul Sorcerer, >=1 Restore Balance use, reaction free,\n"
             "within 60ft + LoS) may cancel DISADVANTAGE on an ally's MISSED attack roll. Offered only\n"
             "when result.disadvantage, the roll missed, and result.d20_primary > result.d20 (so the\n"
             "cancel actually raises the roll). The roller must be an ally of the reactor.")
        .def("apply_restore_balance_miss_to_attack", &CombatEngine::applyRestoreBalanceMissToAttack,
             py::arg("battle_map"), py::arg("action"), py::arg("reactor_idx"), py::arg("result"),
             "Spend 1 Restore Balance use + reaction; cancel disadvantage by reverting result.d20 to\n"
             "result.d20_primary (a RAISE) and re-evaluate hit/crit. If the raised roll meets AC the\n"
             "miss becomes a hit and weapon damage is rolled + applied. Pass the Attack that missed and\n"
             "its AttackResult. Mutates `result`. Returns True if applied.")
        .def("apply_bend_luck_to_attack", &CombatEngine::applyBendLuckToAttack,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Spend 1 Sorcery Point + reaction; subtract 1d4 from the in-flight attack result and\n"
             "re-evaluate hit/crit. Mutates `result`. Returns True if applied.")
        .def("apply_cutting_words_to_attack", &CombatEngine::applyCuttingWordsToAttack,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Spend 1 Bardic Inspiration use + reaction; subtract the Bardic die from the attack result\n"
             "and re-evaluate. Mutates `result`. Returns True if applied.")
        .def("apply_silvery_barbs_to_attack", &CombatEngine::applySilveryBarbsToAttack,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("result"),
             "Spend the lowest L1+ slot + reaction; reroll the d20 and re-evaluate (attacker uses the\n"
             "new roll). Mutates `result`. Returns True if applied.")
        .def("apply_warding_flare_to_attack", &CombatEngine::applyWardingFlareToAttack,
             py::arg("battle_map"), py::arg("reactor_idx"), py::arg("target_idx"), py::arg("result"),
             "Spend 1 Warding Flare use + reaction; impose Disadvantage (reroll the d20, take the lower)\n"
             "and re-evaluate hit/crit. If the reactor is a Light Domain Cleric of level 6+ (Improved\n"
             "Warding Flare), the target also gains 2d6+WIS temporary HP (max() semantics), regardless of\n"
             "the reroll's outcome. Mutates `result`. Returns True if applied.")
        .def("can_intercept",
             &CombatEngine::canIntercept,
             py::arg("battle_map"), py::arg("action"), py::arg("interceptor_idx"), py::arg("damage_taken"),
             "Interception fighting style: True iff agent[interceptor_idx] may reduce the damage of\n"
             "`action` (which just hit action.target_idx for damage_taken). Requires the Interception\n"
             "feat, reaction free, alive/not incapacitated, holding a Shield or weapon, within 5 ft of the\n"
             "(still-standing) target, able to see the attacker, and != attacker/target. The GUI scans all\n"
             "agents with this to find an eligible interceptor.")
        .def("can_combat_inspiration_ac",
             &CombatEngine::canCombatInspirationAC,
             py::arg("battle_map"), py::arg("attack"), py::arg("attack_result"),
             "Combat Inspiration AC mode gate (Valor Bard L3+): checks if the reactor holds\n"
             "a Bardic Inspiration die and whether rolling it + adding to AC could flip the\n"
             "hit to a miss. Returns true if the feature can be offered as an OnHit reaction\n"
             "option. Do not call applyCombatInspirationAC without checking this first.")
        .def("apply_combat_inspiration_ac",
             &CombatEngine::applyCombatInspirationAC,
             py::arg("battle_map"), py::arg("reactor_idx"),
             "Combat Inspiration AC mode apply: rolls the held die, spends it + the reaction.\n"
             "Returns the rolled value on success, or -1 on failure (no die, reaction already\n"
             "spent). The caller compares the value to the attack roll to determine if the\n"
             "hit is negated (DM ruling: a negated hit is a genuine miss).")
        ;
}
