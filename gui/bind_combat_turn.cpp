// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_turn.cpp  –  pybind11 bindings for CombatEngine
//  (combat_turn.cpp + combat_movement.cpp + combat_conditions.cpp + combat_contested.cpp +
//   combat_core.cpp + combat_state.cpp + combat_visibility.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Everything else CombatEngine-related: turn lifecycle, movement, conditions, reactions,
//  NPC automation, agent stat/equipment accessors, rules primitives, visibility.
//  Class features live in bind_combat_<class>.cpp (COMBAT_CLASS_SPLIT_PLAN.md R6b).
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
#include "rules.hpp"             // carriedItemBonuses
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

void bindCombatTurn(py::class_<CombatEngine>& engine) {
    engine
        .def_static("attack_modifier",
                    &CombatEngine::attackModifier,
                    py::arg("weapon"), py::arg("stats"),
                    "Total attack-roll modifier for weapon + attacker stats.")
        .def("roll",              &CombatEngine::roll,            py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_advantage",    &CombatEngine::rollAdvantage,   py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_disadvantage", &CombatEngine::rollDisadvantage,py::arg("sides"), py::arg("modifier") = 0)
        .def("grant_pending_advantage", &CombatEngine::grantPendingAdvantage, py::arg("advantage") = true,
             py::arg("owner") = -1,
             "Grant one-shot advantage (advantage=True) or disadvantage on the NEXT D20 Test\n"
             "(attack, save, or check). With owner >= 0 only that agent's own attack roll, spell\n"
             "attack, save vs a spell or Concentration save takes it (Tides of Chaos, Lucky).")
        .def("roll_initiative",
             &CombatEngine::rollInitiative,
             py::arg("battle_map"),
             "Roll d20 + DEX mod [+ prof_bonus if initiative_prof] for every\n"
             "living agent.  Returns a list of InitiativeEntry sorted highest\n"
             "first.  Call once at combat start; reuse the order each round.")
        .def("roll_initiative_for",
             &CombatEngine::rollInitiativeFor,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Roll a single InitiativeEntry for one agent. Used to deploy an on-deck\n"
             "reinforcement group mid-combat: roll once, then copy the total onto every\n"
             "member of the spawn (same type → same Initiative).")
        .def("swap_initiative",
             &CombatEngine::swapInitiative,
             py::arg("order"), py::arg("agent_a"), py::arg("agent_b"),
             "Alert feat — Initiative Swap: exchange two agents' Initiative totals in the\n"
             "order list and re-sort. The caller enforces the willing-ally / not-Incapacitated\n"
             "constraint. The list is modified in place.")
        .def("available_attacks",
             &CombatEngine::availableAttacks,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Return all legal (weapon, target) pairs for the attacker.")
        .def("get_battle_observation",
             &CombatEngine::getBattleObservation,
             py::arg("battle_map"), py::arg("attacker_idx"),
             py::arg("target_indices"), py::arg("max_targets") = 8,
             "Fixed-length float vector for NN input (12 + max_targets×14 floats).")
        .def("begin_turn",
             &CombatEngine::beginTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Begin agent's turn: seed movement budgets, reset conditions,\n"
             "reset leveled spell flag, and apply persistent spell effects.")
        .def("begin_turn_flow",
             &CombatEngine::beginTurnFlow,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("interactive") = true,
             "Interruptible turn start: runs begin_turn, then opens the\n"
             "OnTurnStartNearby window so nearby creatures may react (Sentinel strike / Branches of the\n"
             "Tree grapple). Returns FlowStatus: Completed, or AwaitingDecision (parked — poll\n"
             "pending_decision(), resume via submit_decision()). interactive=False is the auto/RL driver\n"
             "(resolves each reactor inline via the installed decider). Read the TurnStartResult via\n"
             "last_turn_start_result() once Completed.")
        .def("last_turn_start_result",
             &CombatEngine::lastTurnStartResult,
             py::return_value_policy::reference_internal,
             "The TurnStartResult of the most recent begin_turn_flow (valid once Completed).")
        .def("run_npc_turn",
             &CombatEngine::runNpcTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Drive one automated NPC's turn through the engine (NPC automation Steps 2-3). Uses the C++\n"
             "resolution primitives (no pygame), so it is callable headless from pytest and RL rollouts.\n"
             "Returns FlowStatus: Completed (turn resolved — caller advances the turn) or AwaitingDecision\n"
             "(parked at a human reaction window — poll pending_decision(), resume via submit_decision(),\n"
             "then call run_npc_turn again to continue; the turn's resume point is held in the engine).\n"
             "Step 3 implements the Simple (preferMelee) strategy: engage the nearest enemy, move into melee\n"
             "reach, make a full Attack action; if none is reachable, Dash and advance toward the nearest.\n"
             "Steps 4-5 add PreferTargetCaster (target enemy casters) and PreferRange (best bow, kite, focus\n"
             "fire the weakest). Step 6 adds PreferAOE: cast the available area spell + aim that catches the\n"
             "most net enemies (friendly-fire aware), falling back to a Simple weapon turn with no good blast.\n"
             "Step 8 adds PreferControl: walk the DM-authored control_priority list (npc_automation_config.json)\n"
             "and cast the first castable control spell on a valid enemy (single → nearest; area → best cluster),\n"
             "approaching if out of range and falling back to a weapon turn with nothing castable. Step 9 adds\n"
             "PreferHeal: heal the most-wounded ally (downed first, then most missing HP) with an HP-restoring\n"
             "Heal spell when an ally is downed or below heal_threshold_fraction of max HP (Multiple heals fill\n"
             "several allies), approaching an out-of-range ally and falling back to a weapon turn otherwise. Step\n"
             "10 adds PreferSupport: apply a Help buff (Bless, Aid, ...) to allies that don't already carry it\n"
             "(checked by named condition), preferring allies engaged with an enemy; Multiple buffs fill several\n"
             "allies, approaching an out-of-range ally and falling back to a weapon turn once everyone is buffed.")
        .def("resolve_strategy",
             &CombatEngine::resolveStrategy,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Resolve which NpcAutomationStrategy an automated agent uses this turn — the difficulty-level\n"
             "override. Level 0 (manual) returns the per-agent strategy field. Levels 1+ resolve from the\n"
             "agent's role (npc_classify_role) + level: L1 all Simple; L2 ranged/casters kite (PreferRange);\n"
             "L3 casters with a castable AoE blast → PreferAOE; L4 ranged with stealth tools → PreferHide and\n"
             "casters resolve dynamically by probing the live planners (Heal → Control → Support, first\n"
             "actionable plan wins, else the L3 result); L5/6 run the archetype fallback chain when a model\n"
             "is loaded (see npc_decide), else clamp to L4.")
        .def("npc_classify_role",
             &CombatEngine::npcClassifyRole,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Combat role the difficulty resolver maps to a strategy: Caster (knows a combat-relevant spell —\n"
             "classification_ignore_spells filters flavor/utility like Speak with Animals), else Ranged (owns\n"
             "a non-shield ranged weapon), else Melee.")
        // ── NPC archetypes + Level 5/6 fallback chain (NPC_LEARNING_PLAN.md Step 4) ──
        .def("npc_decide",
             [](const CombatEngine& eng, const BattleMap& bm, int agent_idx) {
                 NpcDecision d = eng.npcDecide(bm, agent_idx);
                 if (const std::exception_ptr err = eng.takeNpcPolicyError()) std::rethrow_exception(err);
                 return d;
             },
             py::arg("battle_map"), py::arg("agent_idx"),
             "resolve_strategy plus how it decided: an NpcDecision (archetype, fallback rung, strategy, and a\n"
             "Policy decision's macro-action). An exception raised by the installed policy propagates.")
        .def("last_npc_decision",
             &CombatEngine::lastNpcDecision,
             py::return_value_policy::copy,
             "The NpcDecision behind the latest fresh run_npc_turn (agent_idx -1 when that turn never\n"
             "reached the resolver: a corpse, Command Flee, a Forcecage escape). A resume keeps its launch's.")
        .def("npc_classify_archetype",
             &CombatEngine::npcClassifyArchetype,
             py::arg("battle_map"), py::arg("agent_idx"),
             "NpcArchetype: npc_classify_role refined. A Caster tallies its known combat-relevant spells by the\n"
             "Level 4 planner each feeds (AoE blast → Blaster, control_priority → Controller, heal/buff →\n"
             "HealerSupport); largest tally wins, ties by summed spell level; none of the three → Ranged.")
        .def("npc_strategy_actionable",
             &CombatEngine::npcStrategyActionable,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("strategy"),
             "Whether the strategy is legal and has work to do for the agent now (the fallback chain's test).")
        .def_static("npc_archetype_chain",
             &CombatEngine::npcArchetypeChain, py::arg("archetype"),
             "Rung 3's archetype order: the archetype, then its secondaries.")
        .def_static("npc_archetype_strategies",
             &CombatEngine::npcArchetypeStrategies, py::arg("archetype"),
             "The strategies one archetype contributes to rung 3, in preference order.")
        .def("set_npc_archetype_model",
             &CombatEngine::setNpcArchetypeModel,
             py::arg("archetype"), py::arg("ranked"),
             "Step 4 stand-in model: a ranked list of NpcAutomationStrategy for one archetype (what a tree\n"
             "leaf will hold). An empty list clears it. With no model at all, Levels 5/6 run Level 4.")
        .def("npc_models_loaded", &CombatEngine::npcModelsLoaded,
             "True when Levels 5/6 have anything to run: an archetype model or an installed policy.")
        // ── Macro-actions, policy seam, entity observation (NPC_LEARNING_PLAN.md Step 5) ──
        .def("available_macro_actions",
             &CombatEngine::availableMacroActions,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Every NpcMacroAction candidate for the agent now, each flagged legal or not, ordered by kind,\n"
             "then spell index, then target index. Casts are legal regardless of range (the executor closes).")
        .def("macro_action_mask",
             &CombatEngine::macroActionMask,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Per NpcMacroKind (NPC_MACRO_KIND_COUNT entries): whether any candidate of that kind is legal.")
        .def("execute_macro_action",
             &CombatEngine::executeMacroAction,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("action"),
             "Run one macro-action as the agent's turn through the Level 4 executors. Same park/resume\n"
             "contract as run_npc_turn (call again with the same action after submit_decision). Skips\n"
             "run_npc_turn's liveness / Command (Flee) / Forcecage gates and its event-recording switch.")
        .def("npc_heuristic_macro_action",
             &CombatEngine::npcHeuristicMacroAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "What Level 4 would do this turn as the matching available_macro_actions candidate (the\n"
             "behaviour-cloning label). No match → the synthesized action with legal False.")
        .def("describe_macro_action",
             &CombatEngine::describeMacroAction,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("action"),
             "\"Control: Hold Person → Goblin\" — the macro-action as text.")
        .def("get_entity_observation",
             &CombatEngine::getEntityObservation,
             py::arg("battle_map"), py::arg("agent_idx"),
             "NpcEntityObservation: one token per in-play creature (self first, then by index) + a map token.")
        .def_static("entity_observation_fields", &CombatEngine::entityObservationFields,
                    py::return_value_policy::copy)
        .def_static("map_observation_fields", &CombatEngine::mapObservationFields,
                    py::return_value_policy::copy)
        .def("set_npc_policy",
             [](CombatEngine& eng, CallbackNpcPolicy::Fn fn) {
                 eng.setNpcPolicy(std::make_shared<CallbackNpcPolicy>(std::move(fn)));
             },
             py::arg("rank"),
             "Install a policy: rank(agent_idx, archetype, actions) -> indices into actions, best first. The\n"
             "engine runs the first legal one (rung 1 = top, rung 2 = later); none legal → the Step 4 chain\n"
             "from rung 3. Consulted at Levels 5/6 and by the Policy strategy at Level 0. Must be deterministic.")
        .def("clear_npc_policy", &CombatEngine::clearNpcPolicy)
        .def("npc_policy_loaded", &CombatEngine::npcPolicyLoaded)
        .def("npc_control_priority",
             &CombatEngine::npcControlPriority,
             "PreferControl (Step 8) config: the DM-authored control-spell priority order the planner walks,\n"
             "loaded once from gui/npc_automation_config.json (baked-in defaults if the file is absent).")
        .def("npc_heal_threshold",
             &CombatEngine::npcHealThreshold,
             "PreferHeal (Step 9) config: cast a heal when an ally is below this fraction of max HP (default\n"
             "0.5), loaded once from gui/npc_automation_config.json.")
        .def("npc_classification_ignore",
             &CombatEngine::npcClassificationIgnore,
             "Difficulty-resolver config: LOWERCASED spell names that do not make their owner a 'caster' for\n"
             "role classification (flavor/utility spells), from classification_ignore_spells in\n"
             "gui/npc_automation_config.json (baked-in defaults if the file is absent).")
        .def("npc_find_self_invis_spell",
             &CombatEngine::npcFindSelfInvisSpell,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("casting_time"),
             "PreferHide (Step 7) helper: index in agent[idx]'s spell list of a castable Help spell that\n"
             "grants Invisible to the caster with the given CastingTime (Action/BonusAction); prefers\n"
             "Greater Invisibility. Returns -1 if none. Gated by available_castable_spells.")
        .def("npc_find_cover_cell",
             [](CombatEngine& self, BattleMap& bm, int agent_idx) -> py::object {
                 Cell out{};
                 if (self.npcFindCoverCell(bm, agent_idx, out)) return py::cast(out);
                 return py::none();
             },
             py::arg("battle_map"), py::arg("agent_idx"),
             "PreferHide (Step 7) helper: nearest reachable cell (live walk budget) with no enemy line of\n"
             "sight to agent[idx]'s footprint — 'move to cover'. Returns the Cell, or None if every\n"
             "reachable cell is exposed.")
        .def("npc_classify_conceal",
             &CombatEngine::npcClassifyConceal,
             py::arg("battle_map"), py::arg("agent_idx"),
             "PreferHide (Step 7) helper: classify the conceal route (A/B/C/D) for agent[idx] from its\n"
             "current tools — bonus-invis (A), cunning action + cover (B), action-invis (C), else kite (D).")
        .def("npc_analyze_attack",
             &CombatEngine::npcAnalyzeAttack,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx"),
             "NPC attack analysis: NpcAttackAnalysis (p_hit, p_drop_given_hit, advantage, disadvantage)\n"
             "for attacker[weapon] vs target, computed as pure probability over the engine's own to-hit\n"
             "and damage math. No dice are rolled and nothing mutates. The automated executors log this\n"
             "as an 'Analysis:' combat-log line right before each swing.")
        .def("npc_save_chance",
             &CombatEngine::npcSaveChance,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("spell"),
             "NPC cast analysis: P(target SAVES) vs caster's spell save DC for a Save-type spell —\n"
             "deterministic saveModFor pieces + Bless d4 by convolution, save adv/dis, and the\n"
             "Paralyzed/Stunned/Unconscious STR/DEX auto-fail. Logged per target on automated casts.")
        .def("npc_spell_hit_chance",
             &CombatEngine::npcSpellHitChance,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("spell"),
             "NPC cast analysis: P(hit) for an attack-roll spell — spellAttackMod (+Bless) vs\n"
             "calculate_ac, with rollSpellAttack's advantage/disadvantage sources.")
        .def("set_render_attack_hook",
             &CombatEngine::setRenderAttackHook,
             py::arg("hook"),
             "Install a Python callable hook(attacker_idx, target_idx) the NPC driver calls when an\n"
             "automated action resolves, for GUI visualization (Step 2e seam). Headless leaves it unset.")
        .def("take_npc_visual_events",
             &CombatEngine::takeNpcVisualEvents,
             "Drain the NPC-turn visual event stream (move-out-and-clear; a second drain returns []).\n"
             "The GUI calls this after EVERY run_npc_turn return (Completed or parked) and plays the\n"
             "events back — token slides along Move paths, Announce text scrolls above the actor,\n"
             "Outcome flashes/HP-bar updates land in narrative order — before advancing the turn or\n"
             "opening the parked reaction menu.")
        .def_property("record_moves",
             &CombatEngine::recordMoves, &CombatEngine::setRecordMoves,
             "M4b: when True, a player- or DM-driven move also records a Move event (one per\n"
             "committed move, after any Opportunity Attack resolves), drained by\n"
             "take_npc_visual_events. Off by\n"
             "default; headless/RL callers leave it off. Only moves — attacks still record nothing.")
        .def("end_turn",
             &CombatEngine::endTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End agent's turn: apply end-of-turn spell effects.")
        .def("calculate_ac",
             &CombatEngine::calculateAC,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Calculate total AC for agent (base AC + armor + DEX + shield + temp mods).")
        .def("carried_item_bonuses",
             [](const CombatEngine&, const BattleMap& bm, int agent_idx) {
                 const auto& agents = bm.placedAgents();
                 if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
                     return ItemBonuses{};
                 return rules::carriedItemBonuses(agents[static_cast<std::size_t>(agent_idx)]);
             },
             py::arg("battle_map"), py::arg("agent_idx"),
             "RAVENLOFT M1: the summed passive bonuses of the agent's carried, switched-on items\n"
             "(class-limited spell bonuses only when the agent has that class).")
        .def("save_mod_for",
             &CombatEngine::saveModFor,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("ability"),
             "Canonical saving-throw modifier for an agent vs an ability: ability mod + proficiency\n"
             "+ aura bonuses. Single source of truth used by every save site.")
        .def("is_holding_shield",
             &CombatEngine::isHoldingShield,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True iff a weapon slot holds a Shield (Weapon.is_shield or a weapon named 'Shield'). Gate\n"
             "for Shield Master and the shield-gated Fighting Styles (Interception, Protection, Unarmed).")
        .def("can_shield_bash",
             &CombatEngine::canShieldBash,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True iff the agent may use Shield Master's bonus-action Shield Bash now: has the Shield\n"
             "Master feat, is holding a Shield, and has a Bonus Action free. The shove reuses execute_shove.")
        .def("apply_armor_multipliers",
             &CombatEngine::applyArmorMultipliers,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Merge equipped armor damage multipliers into agent stats.\n"
             "Call once at combat start and when armor changes mid-combat.")
        .def("get_walk_remaining",
             &CombatEngine::getWalkRemaining,
             py::arg("agent_idx"),
             "Remaining walk movement in feet for agent_idx this turn.")
        .def("get_fly_remaining",
             &CombatEngine::getFlyRemaining,
             py::arg("agent_idx"),
             "Remaining fly movement in feet for agent_idx this turn.")
        .def("get_swim_remaining",
             &CombatEngine::getSwimRemaining,
             py::arg("agent_idx"),
             "Remaining swim movement in feet for agent_idx this turn.")
        .def("get_burrow_remaining",
             &CombatEngine::getBurrowRemaining,
             py::arg("agent_idx"),
             "Remaining burrow movement in feet for agent_idx this turn.")
        .def("spend_walk",
             &CombatEngine::spendWalk,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from walk budget (clamped to 0). Returns amount spent.")
        .def("spend_fly",
             &CombatEngine::spendFly,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from fly budget (clamped to 0). Returns amount spent.")
        .def("spend_swim",
             &CombatEngine::spendSwim,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from swim budget (clamped to 0). Returns amount spent.")
        .def("spend_burrow",
             &CombatEngine::spendBurrow,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from burrow budget (clamped to 0). Returns amount spent.")
        .def("seed_move_budgets",
             &CombatEngine::seedMoveBudgets,
             py::arg("agent_idx"), py::arg("walk"), py::arg("fly"),
             py::arg("swim"), py::arg("burrow"),
             "Seed the engine-side movement budgets (feet, clamped >=0) for an out-of-turn move "
             "(legendary Dash / DashHalf), since beginTurn was not called for this creature.")
        .def("clear_movement",
             &CombatEngine::clearMovement,
             "Clear all movement budgets (call at end of combat).")
        .def("can_agent_move",
             &CombatEngine::canAgentMove,
             py::arg("battle_map"), py::arg("idx"),
             "Check if agent can move (has Speed > 0, not grappled, etc.).\n"
             "Returns false if any condition reduces speed to 0.")
        .def("move_agent",
             &CombatEngine::moveAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("new_origin"), py::arg("movement_type"),
             "Move agent to a new origin. Returns false if blocked or budget insufficient.\n"
             "On successful move, checks for spell effects at destination and applies them.")
        .def("jump_agent",
             &CombatEngine::jumpAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("new_origin"), py::arg("is_running"),
             "Jump agent to a location (ignores walls, deducts from walk budget).\n"
             "Returns false if distance exceeds jump range.\n"
             "On successful move, checks for spell effects at destination and applies them.")
        .def("teleport_agent",
             &CombatEngine::teleportAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Teleport agent to a new location (col, row). Only checks that destination is not blocked by terrain.\n"
             "Returns false if destination is blocked, out of bounds, or agent index invalid.\n"
             "On successful teleport, checks for spell effects at destination and applies them,\n"
             "and an Emanation anchored to the teleporter (Spirit Guardians) goes with them.")
        .def("recenter_anchored_effects",
             &CombatEngine::recenterAnchoredEffects,
             py::arg("battle_map"), py::arg("idx"),
             "Re-center every Emanation anchored to agent idx on its current position, affecting\n"
             "no one. For a DM reposition (set_agent_position), which is not a move.")
        .def("is_valid_teleport_destination",
             &CombatEngine::isValidTeleportDestination,
             py::arg("battle_map"), py::arg("col"), py::arg("row"),
             "Check if a destination cell is valid for teleportation (in bounds, not blocked by terrain).\n"
             "Returns true if valid, false if out of bounds or blocked.")
        .def("begin_move",
             &CombatEngine::beginMove,
             py::arg("battle_map"), py::arg("idx"), py::arg("dest"), py::arg("type"),
             "GUI/interactive move that may provoke Opportunity Attacks. Returns FlowStatus:\n"
             "Completed (no decision needed) or AwaitingDecision (parked at an OA checkpoint —\n"
             "poll pending_decision() and resume via submit_decision()).")
        .def("submit_decision",
             &CombatEngine::submitDecision,
             py::arg("battle_map"), py::arg("response"),
             "Resume a parked move with the chosen ReactionResponse (route a menu click here).\n"
             "Returns FlowStatus (Completed or AwaitingDecision for the next checkpoint).")
        .def("resolve_move",
             &CombatEngine::resolveMove,
             py::arg("battle_map"), py::arg("idx"), py::arg("dest"), py::arg("type"),
             "Auto/RL/test driver: run the whole move, resolving each OA checkpoint inline via the\n"
             "installed CombatDecider (no decider -> skip every reaction). Returns OA AttackResults.")
        .def("pending_decision",
             &CombatEngine::pendingDecision,
             py::return_value_policy::reference_internal,
             "The decision the engine is currently parked on (PendingDecision; .active is False\n"
             "when not parked). The GUI polls this each frame.")
        .def("place_teleported_agents",
             &CombatEngine::placeTeleportedAgents,
             py::arg("battle_map"), py::arg("agent_indices"), py::arg("dest_col"), py::arg("dest_row"),
             "Teleport multiple agents and place them in a circular pattern around the destination.\n"
             "Places the first agent at dest_col, dest_row; subsequent agents in expanding circles.\n"
             "Returns the number of agents successfully teleported.")
        .def("set_logger",
             &CombatEngine::setLogger,
             py::arg("logger"),
             py::keep_alive<1, 2>(),
             "Attach a MessageLogger; flush() it after each action to read messages.")
        .def("set_decider",
             &CombatEngine::setDecider,
             py::arg("decider"),
             py::keep_alive<1, 2>(),
             "Set the CombatDecider (GUI=Python subclass, RL/headless=nullptr for defaults).")
        .def("run_round",
             &CombatEngine::runRound,
             py::arg("battle_map"), py::arg("turns"),
             "Execute one combat round from an ordered list of TurnActions.\n"
             "Each entry triggers action(), bonusAction(), walk(), fly() on\n"
             "the acting agent, resolves any weapon Attacks, and calls\n"
             "reaction() on any targeted agent.\n"
             "Returns a list of AttackResult (one per resolved Attack).")
        .def("execute_shove",
             &CombatEngine::executeShove,
             py::arg("battle_map"), py::arg("action"),
             "Execute a shove attempt (bonus action, contested Athletics check).\n"
             "On success: either push 5ft or knock prone based on action.knock_prone.\n"
             "Returns ShoveResult with rolls, success status, and log message.")
        .def("attempt_pick_lock",
             &CombatEngine::attemptPickLock,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("door_id"),
             "Pick a door's lock with a Sleight of Hand check: d20 + sleight_of_hand() vs the door's\n"
             "lock_dc. On success the mundane lock is removed (door stays closed until opened). An\n"
             "Arcane Lock cannot be picked. door_id is the Door.id. Returns a PickLockResult.")
        .def("attempt_break_door",
             &CombatEngine::attemptBreakDoor,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("door_id"),
             "Force a door with a Strength (Athletics) check: d20 + athletics() vs the door's\n"
             "break_dc (+10 while an Arcane Lock is active). On success the door is smashed off its\n"
             "frame (permanently open; no lock survives). Works on a locked/arcane-locked door.\n"
             "door_id is the Door.id. Returns a BreakDoorResult.")
        .def("roll_fixed_dc_save", &CombatEngine::rollFixedDcSave,
             py::arg("battle_map"), py::arg("saver_idx"), py::arg("ability"), py::arg("dc"),
             py::arg("source"),
             "A non-spell save against a fixed DC (Advantage/Disadvantage, Bless/auras,\n"
             "Indomitable Might, auto-fail, Legendary Resistance). Logs; True on a success.")
        .def("attempt_pick_chest_lock", &CombatEngine::attemptPickChestLock,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chest_id"),
             "Sleight of Hand vs the chest's lock_dc; a failure by 5+ sets off a live trap.")
        .def("attempt_break_chest", &CombatEngine::attemptBreakChest,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chest_id"),
             "Athletics vs break_dc (+10 under an active Arcane Lock); success opens it for good\n"
             "and sets off a live trap.")
        .def("attempt_find_chest_trap", &CombatEngine::attemptFindChestTrap,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chest_id"),
             "Best of Perception / Investigation vs detect_dc; success marks the trap found.")
        .def("attempt_disarm_chest_trap", &CombatEngine::attemptDisarmChestTrap,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chest_id"),
             "Sleight of Hand vs disarm_dc on a found trap; a failure by 5+ sets it off.")
        .def("trigger_chest_trap", &CombatEngine::triggerChestTrap,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("chest_id"),
             "Set off the chest's live trap on agent_idx (no-op if none is live).")
        .def("execute_grapple",
             &CombatEngine::executeGrapple,
             py::arg("battle_map"), py::arg("action"),
             "Execute a grapple attempt (contested Athletics vs Athletics/Acrobatics).\n"
             "On success: grapple initiates, escape_dc = 10 + attacker_roll.\n"
             "Returns GrappleResult with rolls, success status, escape_dc, and log message.")
        .def("execute_grapple_escape",
             &CombatEngine::executeGrappleEscape,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Attempt to escape an ongoing grapple (contested STR(Athletics)/DEX(Acrobatics) vs escape_dc).\n"
             "On success: grapple condition is cleared.\n"
             "Returns GrappleEscapeResult with rolls, success status, and log message.")
        .def("drop_grapples_by",
             &CombatEngine::dropGrapplesBy,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Voluntarily drop all grapples initiated by the agent (free action).\n"
             "Clears grappled condition and grappler_idx for all affected targets.")
        .def("has_advantage_aura",
             &CombatEngine::hasAdvantageAura,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True if agent_idx is inside an active advantage emanation it benefits from\n"
             "(Spell::grants_advantage_aura): it is the caster, or a same-faction ally, within\n"
             "the spell's radius of a conscious caster. Such a creature has Advantage on attack\n"
             "rolls and saving throws. Continuous — follows the caster, ends with the effect.")
        .def("trigger_delayed_effect",
             &CombatEngine::triggerDelayedEffect,
             py::arg("battle_map"), py::arg("condition_id"),
             "Detonate a planted delayed-trigger condition (Quivering Palm, Delayed Blast Fireball, …) by\n"
             "its condition_id: rolls the stored damage, applies the optional save, deals it to the\n"
             "affected agent, and removes the condition. Returns the damage dealt, or -1 if the id is not\n"
             "a valid delayed-trigger condition.")
        .def("apply_push",
             &CombatEngine::applyPush,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Weapon Mastery — Push: after a qualifying hit (conditions.push_available), shove the\n"
             "target 10 ft straight away from the attacker. Clears the flag; returns feet moved.")
        .def("apply_frightened",
             &CombatEngine::applyFrightened,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Apply the Frightened condition to an agent (drops weapons, sets the flag). No-op if the\n"
             "agent is protected by an allied Paladin's Aura of Courage (L10+ in range).")
        .def("consume_bonus_attack",
             &CombatEngine::consumeBonusAttack,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Decrement bonus_attacks_remaining for an agent (Flurry of Blows, Martial Arts, etc).\n"
             "Returns true if more attacks are queued, false if sequence is exhausted.")
        .def("add_agent_config",
             &CombatEngine::addAgentConfig,
             py::arg("battle_map"), py::arg("config"),
             "Queue an agent configuration for later application.")
        .def("apply_agent_configs",
             &CombatEngine::applyAgentConfigs,
             py::arg("battle_map"),
             "Apply all queued agent configs, creating agents on the map.")
        .def("get_agent_stats",
             &CombatEngine::getAgentStats,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the Stats for agent[idx].")
        .def("set_agent_stats",
             &CombatEngine::setAgentStats,
             py::arg("battle_map"), py::arg("idx"), py::arg("stats"),
             "Replace the Stats for agent[idx].")
        .def("get_agent_conditions",
             &CombatEngine::getAgentConditions,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the Conditions for agent[idx].")
        .def("set_agent_conditions",
             &CombatEngine::setAgentConditions,
             py::arg("battle_map"), py::arg("idx"), py::arg("conditions"),
             "Replace the Conditions for agent[idx].")
        .def("apply_poisoned",
             &CombatEngine::applyPoisoned,
             py::arg("battle_map"), py::arg("idx"),
             "Apply poisoned condition to agent[idx]: disadvantage on attack rolls and ability checks.")
        .def("apply_deafened",
             &CombatEngine::applyDeafened,
             py::arg("battle_map"), py::arg("idx"),
             "Apply deafened condition to agent[idx]: cannot hear; auto-fail ability checks requiring hearing.")
        .def("apply_petrified",
             &CombatEngine::applyPetrified,
             py::arg("battle_map"), py::arg("idx"),
             "Apply petrified condition to agent[idx]: incapacitated, speed 0, resistance to all damage (0.5x), immune to poisoned.")
        .def("apply_unconscious",
             &CombatEngine::applyUnconscious,
             py::arg("battle_map"), py::arg("idx"),
             "Drop agent[idx] (the single down/death chokepoint): releases grapples/concentration/imposed\n"
             "conditions and self-buffs (Gaseous Form), sets Unconscious (NPCs die outright at 0 HP).")
        .def("get_agent_weapons",
             &CombatEngine::getAgentWeapons,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the weapon list for agent[idx] (>=3: [0]=main_hand, [1]=off_hand, [2]=ranged, then extra attacks).")
        .def("set_agent_weapons",
             &CombatEngine::setAgentWeapons,
             py::arg("battle_map"), py::arg("idx"), py::arg("weapons"),
             "Replace the weapon list for agent[idx] (padded to >=3; may contain extra attacks beyond slot 2).")
        .def("get_agent_armor",
             &CombatEngine::getAgentArmor,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the armor array [helmet, chest, leggings, boots, gloves, cloak] for agent[idx].")
        .def("set_agent_armor",
             &CombatEngine::setAgentArmor,
             py::arg("battle_map"), py::arg("idx"), py::arg("armor"),
             "Replace the armor array for agent[idx].")
        .def("can_equip_armor",
             &CombatEngine::canEquipArmor,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("armor"),
             "Check if agent[agent_idx] meets STR requirement for the given armor piece. "
             "Returns true if armor has no STR requirement or agent meets it.")
        .def("get_agent_spells",
             &CombatEngine::getAgentSpells,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the spell list for agent[idx].")
        .def("set_agent_spells",
             &CombatEngine::setAgentSpells,
             py::arg("battle_map"), py::arg("idx"), py::arg("spells"),
             "Replace the spell list for agent[idx].")
        .def("add_spell_to_agent",
             &CombatEngine::addSpellToAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell"),
             "Append a spell to agent[idx]'s spell list.")
        .def("remove_spell_from_agent",
             &CombatEngine::removeSpellFromAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell_idx"),
             "Remove spell at spell_idx from agent[idx]'s list.")
        .def("discard_spent_scrolls",
             &CombatEngine::discardSpentScrolls,
             py::arg("battle_map"), py::arg("idx"),
             "Erase agent[idx]'s spent spell scrolls (SPELL_SCROLLS_PLAN.md S3), keeping any whose\n"
             "spell is still live (concentration, a condition or effect it made). Later item\n"
             "spell tags are shifted; the scroll's own entries are untagged. Returns the count.")
        .def("spend_spell_slot",
             &CombatEngine::spendSpellSlot,
             py::arg("battle_map"), py::arg("idx"), py::arg("level"),
             "Expend one player spell slot of `level` (1-9) for agent[idx], clamped at 0.\n"
             "No-op (returns False) for NPCs or if no slot of that level remains. Used by the\n"
             "GUI Wish flow to charge Wish's own 9th-level slot while the duplicated spell is\n"
             "cast for free.")
        .def("init_npc_spell_groups",
             &CombatEngine::initNpcSpellGroups,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("groups"),
             "Set is_npc=true on agent and initialize uses_max/uses_remaining from spell groups.\n"
             "groups: dict mapping N (uses/day) -> list of spell names in that group.\n"
             "Call once after set_agent_spells().")
        .def("get_agent_items",
             &CombatEngine::getAgentItems,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the carried-item list (inventory) for agent[idx].")
        .def("set_agent_items",
             &CombatEngine::setAgentItems,
             py::arg("battle_map"), py::arg("idx"), py::arg("items"),
             "Replace the carried-item list for agent[idx].")
        .def("add_item_to_agent",
             &CombatEngine::addItemToAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("item"),
             "Add an item to agent[idx]'s inventory. Stacks by name: if the agent already carries\n"
             "an item with that name, its quantity is increased instead of adding a second row.")
        .def("remove_item_from_agent",
             &CombatEngine::removeItemFromAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("item_idx"),
             "Remove the inventory row at item_idx from agent[idx] (the whole stack).")
        .def("apply_burning",
             &CombatEngine::applyBurning,
             py::arg("battle_map"), py::arg("idx"),
             "Set a creature alight (Burning [Hazard]): 1d4 Fire at the start of each of its turns.")
        .def("extinguish_burning",
             &CombatEngine::extinguishBurning,
             py::arg("battle_map"), py::arg("idx"),
             "Put out a Burning creature by dropping it Prone and rolling on the ground (an action).\n"
             "Returns False if it was not burning.")
        .def("escape_net",
             &CombatEngine::escapeNet,
             py::arg("battle_map"), py::arg("actor_idx"), py::arg("target_idx"),
             "Free a netted creature with a DC 10 STR (Athletics) check (an action). actor_idx is the\n"
             "netted creature itself or a creature within 5 ft of it. Returns an EscapeNetResult.")
        .def("add_agent_condition",
             &CombatEngine::addAgentCondition,
             py::arg("battle_map"), py::arg("condition"),
             "Add an active agent condition (e.g., from a spell).\n"
             "Returns the condition_id for later removal.")
        .def_property_readonly("active_agent_conditions",
             [](const CombatEngine& e) { return e.activeAgentConditions(); },
             "List of ActiveAgentCondition objects currently applied to agents.")
        .def("tick_agent_conditions",
             &CombatEngine::tickAgentConditions,
             py::arg("battle_map"),
             "Decrement all active agent condition durations by 1 turn.\n"
             "Remove expired conditions and apply their end-of-life effects.\n"
             "Returns list of expired condition IDs.")
        .def("tick_agent_conditions_for_caster",
             &CombatEngine::tickAgentConditionsForCaster,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Decrement condition durations for conditions cast by the given caster.\n"
             "Duration is counted in the caster's turns, not absolute turns.\n"
             "Returns list of expired condition IDs.")
        .def("remove_agent_condition",
             &CombatEngine::removeAgentCondition,
             py::arg("battle_map"), py::arg("condition_id"),
             "Explicitly remove an active agent condition by its ID.\n"
             "Fires the condition's caster kickback (Vistani Curse) before erasing.")
        .def("banish",
             &CombatEngine::banish,
             py::arg("battle_map"), py::arg("target_idx"), py::arg("source_idx"), py::arg("turns"),
             py::arg("sends_home") = false, py::arg("spell_idx") = -1,
             "Banish target_idx (Banishment / Banishing Shot): a 'Banished' condition = Untouchable +\n"
             "Incapacitated, ticking at source_idx's turn starts. On end the creature returns to its\n"
             "space or the nearest unoccupied one; with sends_home an Aberration/Celestial/Elemental/\n"
             "Fey/Fiend whose banishment expires is removed from play. Returns the condition id or -1.")
        .def("curse_save_disadvantage",
             &CombatEngine::curseSaveDisadvantage,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("save_ability"),
             "True when agent_idx is under a Vistani Curse of Weakness imposing Disadvantage on\n"
             "saving throws tied to the given SaveAbility.")
        .def("save_advantage_for",
             &CombatEngine::saveAdvantageFor,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("save_ability"),
             "True when agent_idx has a scoped save-Advantage buff (e.g. Haste's DEX save) for the\n"
             "given SaveAbility, per Stats::save_advantage_mask.")
        .def("apply_prone",
             &CombatEngine::applyProne,
             py::arg("battle_map"), py::arg("idx"),
             "Apply prone condition to agent[idx].")
        .def("standup",
             &CombatEngine::standup,
             py::arg("battle_map"), py::arg("idx"),
             "Remove prone condition from agent[idx] (costs half movement speed).")
        .def("check_hide",
             &CombatEngine::checkHide,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("in_combat"),
             "Attempt Hide action: validate out-of-LOS, roll Stealth vs Perception.\n"
             "If successful, applies hidden condition. Returns HideResult with details.")
        .def("check_hidden_agent_detection",
             &CombatEngine::checkHiddenAgentDetection,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("in_combat"),
             "Check if a hidden agent comes into LOS and is detected by Perception.\n"
             "Returns empty string if still hidden, or detection message if revealed.")
        .def("update_darkness_blinding",
             &CombatEngine::updateDarknessBlinding,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Apply or remove Blinded condition based on agent's location obscuration.\n"
             "Agents in Darkness without darkvision, or MagicalDarkness without devil's sight, become Blinded.")
        .def("compute_visibility",
             &CombatEngine::computeVisibility,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Compute and cache visibility from one agent to all others.\n"
             "Respects perception range (based on stats + lighting modifiers),\n"
             "line-of-sight, and obscuration effects.\n"
             "Results are cached for use by spells/attacks until next turn.")
        .def("get_visibility",
             &CombatEngine::getVisibility,
             py::arg("source_idx"), py::arg("target_idx"),
             "Get the cached visibility level between two agents.\n"
             "Returns Blocked if visibility hasn't been computed for this pair.\n"
             "Call compute_visibility() first to populate the cache.")
        .def("can_perceive_target",
             &CombatEngine::canPerceiveTarget,
             py::arg("battle_map"), py::arg("viewer_idx"), py::arg("target_idx"),
             "True unless the target has the Invisible condition and the viewer lacks\n"
             "Truesight/Blindsight in range, or magical darkness hides an enemy from a viewer\n"
             "outside it. Geometric line-of-sight is separate.")
        .def("reseed", &CombatEngine::reseed, py::arg("seed"))
        // ── Snapshot / restore (COMBAT_REFACTOR_PLAN.md R5) ──────────────────
        // Strings, not dicts: the payload is written straight to a save file and read
        // straight back, so converting it through Python objects on the way would only
        // add a lossy hop (large int keys, float round-tripping) for no caller.
        .def("snapshot_json", &CombatEngine::snapshotJson,
             "Serialize the engine's full combat state (RNG state, conditions, active\n"
             "effects, movement budgets, visibility cache, and every in-flight flow's\n"
             "park/resume state) to a JSON string. ENGINE state only — agents, terrain\n"
             "and lighting are saved separately, and indices are raw BattleMap agent\n"
             "indices, so a snapshot restores only against the agent list it came from.")
        .def("restore_json", &CombatEngine::restoreJson, py::arg("text"),
             "Load a snapshot_json() payload. Returns False (having changed nothing, or\n"
             "left the engine partially restored on a malformed document) if the text is\n"
             "not parseable, is not an object, or was written by a newer engine — treat\n"
             "False as 'reload the encounter from scratch'. The live logger, NPC render\n"
             "hook and decider are preserved across the call.")
        ;
}
