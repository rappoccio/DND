// ─────────────────────────────────────────────────────────────────────────────
//  bind_combat_turn.cpp  –  pybind11 bindings for CombatEngine
//  (combat_turn.cpp + combat_movement.cpp + combat_conditions.cpp + combat_riders.cpp +
//   combat_core.cpp + combat_state.cpp + combat_visibility.cpp)
// ─────────────────────────────────────────────────────────────────────────────
//
//  Everything else CombatEngine-related: turn lifecycle, movement, conditions, reactions,
//  NPC automation, agent stat/equipment accessors, rules primitives, visibility.
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

void bindCombatTurn(py::class_<CombatEngine>& engine) {
    engine
        .def_static("attack_modifier",
                    &CombatEngine::attackModifier,
                    py::arg("weapon"), py::arg("stats"),
                    "Total attack-roll modifier for weapon + attacker stats.")
        .def_static("damage_ability_mod",
                    &CombatEngine::damageAbilityMod,
                    py::arg("weapon"), py::arg("stats"),
                    "Ability modifier added to damage rolls.")
        .def("roll",              &CombatEngine::roll,            py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_advantage",    &CombatEngine::rollAdvantage,   py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_disadvantage", &CombatEngine::rollDisadvantage,py::arg("sides"), py::arg("modifier") = 0)
        .def("grant_pending_advantage", &CombatEngine::grantPendingAdvantage, py::arg("advantage") = true,
             "Grant one-shot advantage (advantage=True) or disadvantage on the NEXT D20 Test\n"
             "(attack, save, or check). General hook for 'advantage on your next roll' (Tides of Chaos).")
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
        .def("get_agent_turns",
             &CombatEngine::getAgentTurns,
             py::arg("idx"),
             "Number of turns agent[idx] takes per round (default 1).")
        .def("set_agent_turns",
             &CombatEngine::setAgentTurns,
             py::arg("idx"), py::arg("turns"),
             "Override turn count for agent[idx]. set_agent_turns(idx, 1) "
             "removes the override and restores the default.")
        .def("clear_agent_turns",
             &CombatEngine::clearAgentTurns,
             "Reset every agent to the default of 1 turn per round.")
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
             "actionable plan wins, else the L3 result); L5/6 clamp to L4 until the NN policies exist.")
        .def("npc_classify_role",
             &CombatEngine::npcClassifyRole,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Combat role the difficulty resolver maps to a strategy: Caster (knows a combat-relevant spell —\n"
             "classification_ignore_spells filters flavor/utility like Speak with Animals), else Ranged (owns\n"
             "a non-shield ranged weapon), else Melee.")
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
        .def("can_branches_of_tree",
             &CombatEngine::canBranchesOfTree,
             py::arg("battle_map"), py::arg("reactor"), py::arg("source"),
             "True if reactor may use Branches of the Tree (STR-save-or-Grappled) vs source starting its turn in reach.")
        .def("apply_branches_of_tree",
             &CombatEngine::applyBranchesOfTree,
             py::arg("battle_map"), py::arg("reactor"), py::arg("source"),
             "Spend reactor's reaction; source makes a STR save vs the reactor's spell save DC or is Grappled.\n"
             "Returns True iff it grappled the source.")
        .def("can_vitality_of_tree",
             &CombatEngine::canVitalityOfTheTree,
             py::arg("battle_map"), py::arg("source"),
             "True if source (raging World Tree Barbarian L3+) may use Vitality of the Tree at its own turn\n"
             "start: free, once per turn, needs a creature within 10 ft.")
        .def("apply_vitality_of_tree",
             &CombatEngine::applyVitalityOfTheTree,
             py::arg("battle_map"), py::arg("source"), py::arg("target"),
             "Grant target Xd6 temp HP (X = Rage Damage bonus, min 1) with max() semantics, tagged so it\n"
             "vanishes when the source's Rage ends. Sets vitality_used_this_turn. Returns True iff granted.")
        .def("end_turn",
             &CombatEngine::endTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End agent's turn: apply end-of-turn spell effects.")
        .def("calculate_ac",
             &CombatEngine::calculateAC,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Calculate total AC for agent (base AC + armor + DEX + shield + temp mods).")
        .def("aura_save_bonus",
             &CombatEngine::auraSaveBonus,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Aura of Protection: the bonus this agent adds to every saving throw from a Paladin\n"
             "L6+ (itself or a same-team ally within 10 ft, 30 ft at L18). 0 if none in range.")
        .def("has_aura_of_courage",
             &CombatEngine::hasAuraOfCourage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Aura of Courage: True iff this agent is immune to Frightened (a Paladin L10+ aura\n"
             "reaches it — itself or a same-team ally in range).")
        .def("has_aura_of_warding",
             &CombatEngine::hasAuraOfWarding,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Aura of Warding (Oath of the Ancients L7+): True iff this agent has Resistance to\n"
             "Necrotic/Psychic/Radiant (an allied Ancients Paladin L7+ aura reaches it).")
        .def("has_aura_of_alacrity",
             &CombatEngine::hasAuraOfAlacrity,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Aura of Alacrity (Oath of Glory L7+): True iff this agent's Speed is +10 ft (an allied\n"
             "Glory Paladin L7+ aura reaches it — itself or a same-team ally in range).")
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
             "On successful teleport, checks for spell effects at destination and applies them.")
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
        .def("apply_telekinetic_shove",
             &CombatEngine::applyTelekineticShove,
             py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"),
             "Telekinetic feat — Telekinetic Shove (Bonus Action): shove a creature within 30 ft.\n"
             "Target makes a STR save (DC = 8 + caster PB + best of INT/WIS/CHA mod); on a failure it\n"
             "is pushed 5 ft away (reuses the Thunderwave knockback). Returns ShoveResult:\n"
             "attacker_roll=DC, defender_roll=save total, success=shove landed.")
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
        .def("apply_brutal_strike_effect",
             &CombatEngine::applyBrutalStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"), py::arg("result"),
             "Apply Brutal Strike effects: damage + chosen effects (0=Forceful, 1=Hamstring, 2=Staggering, 3=Sundering).\n"
             "Modifies the AttackResult to include brutal strike damage in damage_breakdown and updates total_damage.")
        .def("apply_cunning_strike_effect",
             &CombatEngine::applyCunningStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"),
             py::arg("result"), py::arg("round_num") = -1,
             "Apply Rogue Sneak Attack + optional Cunning Strike riders after a qualifying hit\n"
             "(conditions.cunning_strike_available). effects: rider codes (0=Poison, 1=Trip, 2=Withdraw,\n"
             "4=KnockOut, 5=Obscure, 6=Stealth Attack [Thief]); empty = full Sneak Attack with no rider.\n"
             "Rolls (sneak dice − cost)d6, folds it into the AttackResult and target HP, then applies riders.\n"
             "round_num (0 = first round) drives the Assassin subclass round-1 features: Assassinate\n"
             "(+level damage), Envenom Weapons (free Poison rider + 2d6), Death Strike (CON save → double).")
        .def("apply_homing_strike",
             &CombatEngine::applyHomingStrike,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("weapon_idx"), py::arg("result"),
             "Soulknife Soul Blades — Homing Strikes (L9): convert a missed Psychic-Blade attack to a hit\n"
             "by adding a Psionic Energy Die to the roll (die spent only if it converts). Returns True iff hit.")
        .def("trigger_delayed_effect",
             &CombatEngine::triggerDelayedEffect,
             py::arg("battle_map"), py::arg("condition_id"),
             "Detonate a planted delayed-trigger condition (Quivering Palm, Delayed Blast Fireball, …) by\n"
             "its condition_id: rolls the stored damage, applies the optional save, deals it to the\n"
             "affected agent, and removes the condition. Returns the damage dealt, or -1 if the id is not\n"
             "a valid delayed-trigger condition.")
        .def("can_rend_mind",
             &CombatEngine::canRendMind,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Soulknife Rend Mind (L17) availability: L17+ Soulknife with a Rend Mind use or ≥3 Psionic Energy Dice.")
        .def("apply_rend_mind",
             &CombatEngine::applyRendMind,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Soulknife Rend Mind (L17): after a Psychic-Blade Sneak Attack, WIS save (DC 8+DEX+PB) or Stunned\n"
             "1 minute. Costs a Rend Mind use or 3 Psionic Energy Dice. Returns True iff the target is Stunned.")
        .def("apply_divine_strike_effect",
             &CombatEngine::applyDivineStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("radiant"), py::arg("result"),
             "Cleric Blessed Strikes — Divine Strike: after a qualifying weapon hit\n"
             "(conditions.divine_strike_available), add 1d8 (2d8 at L14) Radiant (radiant=True) or\n"
             "Necrotic (False) to the AttackResult and target HP; once per turn.")
        .def("apply_divine_smite_effect",
             &CombatEngine::applyDivineSmiteEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("slot_level"), py::arg("result"),
             "Paladin Divine Smite: after a melee/unarmed hit (conditions.divine_smite_available),\n"
             "spend a level-slot_level spell slot as a Bonus Action to add (1+min(slot_level,5))d8\n"
             "Radiant, +1d8 vs Undead/Fiend, to the AttackResult and target HP. Spends the slot +\n"
             "bonus action, sets the leveled-spell + once-per-turn interlocks. Returns Radiant dealt,\n"
             "or -1 if not allowed (no slot/bonus action, already smited, leveled spell already cast).")
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
        .def("can_use_war_magic",
             &CombatEngine::canUseWarMagic,
             py::arg("battle_map"), py::arg("idx"),
             "Eldritch Knight War Magic (L7+): true if idx is an EK Fighter L7+ who has not yet used\n"
             "War Magic this Attack action (conditions.war_magic_used). The GUI also requires the EK to\n"
             "be mid Attack action with attacks left; the cast itself goes through execute_spell, then\n"
             "decrements one attack instead of the whole action.")
        .def("mark_war_magic_used",
             &CombatEngine::markWarMagicUsed,
             py::arg("battle_map"), py::arg("idx"),
             "Set the War Magic once-per-Attack-action gate (conditions.war_magic_used). The GUI clears\n"
             "it when a fresh action-attack sequence seeds, so Action Surge's second Attack action allows\n"
             "another substitution.")
        .def("available_war_magic_spells",
             &CombatEngine::availableWarMagicSpells,
             py::arg("battle_map"), py::arg("idx"),
             "Spell indices an Eldritch Knight may cast via War Magic: action-casting-time cantrips\n"
             "(L7+), plus level 1-5 action spells at L18+ (Improved War Magic). Empty for non-EK / <L7.")
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
        .def("apply_arcane_charge",
             &CombatEngine::applyArcaneCharge,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Eldritch Knight Arcane Charge (L15): teleport up to 30 ft (the optional rider on Action\n"
             "Surge). Validates EK L15+, the 30-ft range, and a clear destination, then teleports.\n"
             "Returns feet moved (>=0) on success, or negative: -1 not eligible, -2 out of range,\n"
             "-3 destination blocked.")
        .def("apply_guided_strike_effect",
             &CombatEngine::applyGuidedStrike,
             py::arg("battle_map"), py::arg("action"), py::arg("cleric_idx"), py::arg("result"),
             "War Domain — Guided Strike: a War Cleric L3+ (the attacker, or an ally within 30 ft who\n"
             "also spends a Reaction) expends Channel Divinity to add +10 to a missed attack roll\n"
             "(conditions.guided_strike_available). If it now meets AC, the miss becomes a hit and\n"
             "weapon damage is rolled and applied. Pass the Attack that missed and its AttackResult.")
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
        .def("apply_reckless_reroll",
             &CombatEngine::applyRecklessReroll,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx"),
             "Reckless Attack (Barbarian), post-hoc entry: after a miss flags\n"
             "conditions.reckless_reroll_available, commit Reckless (enemies gain advantage vs you\n"
             "until your next turn) and re-resolve the SAME attack with advantage. Returns the fresh\n"
             "AttackResult (invalid if the flag wasn't set).")
        .def("apply_riposte",
             &CombatEngine::applyRiposte,
             py::arg("battle_map"), py::arg("defender_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Battle Master Riposte (on-miss DEFENDER reaction): after a melee attack misses the\n"
             "defender, flagged via conditions.riposte_available, spend the reaction + 1 Superiority\n"
             "Die to make a melee attack defender→attacker; on a hit, add the Superiority Die to the\n"
             "damage. Returns the riposte AttackResult (invalid if the flag wasn't set / no die / no weapon).")
        .def("apply_sentinel_guard",
             &CombatEngine::applySentinelGuard,
             py::arg("battle_map"), py::arg("sentinel_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Sentinel Guardian (OnAllyAttacked bystander reaction): after an adjacent enemy attacks an\n"
             "ally (flagged via the attacker's conditions.sentinel_guard_available), the Sentinel spends\n"
             "its reaction to make a melee attack at the attacker. Returns the counter-attack's\n"
             "AttackResult (invalid if the reaction was already used).")
        .def("apply_soul_of_vengeance",
             &CombatEngine::applySoulOfVengeance,
             py::arg("battle_map"), py::arg("paladin_idx"), py::arg("attacker_idx"), py::arg("weapon_idx"),
             "Soul of Vengeance (Oath of Vengeance L15): after the sworn foe attacks (flagged via the\n"
             "attacker's conditions.soul_of_vengeance_available), the paladin spends its reaction to make\n"
             "a melee attack at that foe. Returns the counter-attack's AttackResult (invalid if the\n"
             "reaction was already used).")
        .def("apply_push",
             &CombatEngine::applyPush,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Weapon Mastery — Push: after a qualifying hit (conditions.push_available), shove the\n"
             "target 10 ft straight away from the attacker. Clears the flag; returns feet moved.")
        .def("apply_topple",
             &CombatEngine::applyTopple,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx") = 0,
             "Weapon Mastery — Topple: after a qualifying hit (conditions.topple_available), the target\n"
             "makes a CON save (DC 8 + attack ability mod + prof) or is knocked Prone. Returns a ToppleResult.")
        .def("apply_stunning_strike",
             &CombatEngine::applyStunningStrike,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Monk Stunning Strike: after a qualifying unarmed hit (conditions.stunning_strike_available),\n"
             "spend 1 Focus Point and force a CON save (DC 8 + DEX mod + prof) or the target is Stunned.\n"
             "Returns a StunningStrikeResult.")
        .def("apply_psionic_strike_effect",
             &CombatEngine::applyPsionicStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("result"),
             "Psi Warrior Psionic Strike: after a qualifying hit (conditions.psionic_strike_available),\n"
             "spend one Psionic Energy die and add Force damage (die roll + INT mod) to the AttackResult\n"
             "and the target's HP. Once per turn.")
        .def("apply_punch_and_grab",
             &CombatEngine::applyPunchAndGrab,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Grappler feat — Punch-and-Grab: after an Unarmed-Strike hit in the Attack action\n"
             "(conditions.grappler_punch_grab_available), ALSO attempt a Grapple this attack (normally one\n"
             "or the other), once per turn. Runs through the shared resolveGrapple core (contested check,\n"
             "computed escape DC). Returns the GrappleResult (invalid if the flag wasn't set).")
        .def("apply_protective_field",
             &CombatEngine::applyProtectiveField,
             py::arg("battle_map"), py::arg("defender_idx"), py::arg("damage_taken"),
             "Psi Warrior Protective Field (reaction): spend one Psionic Energy die + the defender's\n"
             "reaction to prevent (die roll + INT mod) damage, capped at damage_taken (modeled as a\n"
             "heal-back). Returns the damage prevented, or -1 if it could not be used.")
        .def("apply_interception",
             &CombatEngine::applyInterception,
             py::arg("battle_map"), py::arg("interceptor_idx"), py::arg("target_idx"), py::arg("damage_taken"),
             "Interception fighting style (reaction): spend the interceptor's reaction to prevent\n"
             "(1d10 + Proficiency Bonus) damage to the target, capped at damage_taken (modeled as a\n"
             "heal-back, like Protective Field). Returns the damage prevented, or -1 if it could not be used.")
        .def("apply_telekinetic_movement",
             &CombatEngine::applyTelekineticMovement,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Psi Warrior Telekinetic Movement: spend the once-per-rest use to push a creature up to\n"
             "30 ft straight away from the Psi Warrior. Returns feet moved, or -1 if unavailable.")
        .def("apply_open_hand_rider",
             &CombatEngine::applyOpenHandRider,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("option"),
             "Monk Warrior of the Open Hand: after a qualifying Flurry hit (conditions.open_hand_rider_available),\n"
             "spend 1 Focus Point and apply one of three riders: 0=Knockdown (STR save or Prone),\n"
             "1=Push (5 feet), 2=Deny Reaction. Returns an OpenHandRiderResult.")
        .def("hand_of_healing",
             &CombatEngine::handOfHealing,
             py::arg("battle_map"), py::arg("monk_idx"), py::arg("target_idx"), py::arg("free") = false,
             "Monk Warrior of Mercy — Hand of Healing (L3+): a Bonus Action spending 1 Focus Point to heal a\n"
             "creature within reach for (Martial Arts die + WIS mod). At L6 (Physician's Touch) it also ends\n"
             "one of Blinded/Deafened/Paralyzed/Poisoned/Stunned. free=true (only at L11, Flurry of Healing\n"
             "and Harm) folds the heal into a Flurry strike: no Focus Point, no Bonus Action. Returns a\n"
             "HandOfHealingResult.")
        .def("wholeness_of_body",
             &CombatEngine::wholenessOfBody,
             py::arg("battle_map"), py::arg("monk_idx"),
             "Monk Warrior of the Open Hand — Wholeness of Body (L6+): a Bonus Action spending one use of the\n"
             "\"Wholeness of Body\" resource (PB per long rest) to heal yourself (Martial Arts die + WIS mod).\n"
             "Returns the HP restored, or 0 if unavailable.")
        .def("apply_hand_of_harm_effect",
             &CombatEngine::applyHandOfHarmEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("result"),
             "Monk Warrior of Mercy — Hand of Harm (L3+): after a qualifying unarmed hit\n"
             "(conditions.hand_of_harm_available), spend 1 Focus Point and add (Martial Arts die + WIS mod)\n"
             "Necrotic damage to the AttackResult and the target's HP. At L6 (Physician's Touch) the target is\n"
             "also Poisoned. At L11 it is free and may be used once per target. Once per turn below L11.")
        .def("apply_frightened",
             &CombatEngine::applyFrightened,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Apply the Frightened condition to an agent (drops weapons, sets the flag). No-op if the\n"
             "agent is protected by an allied Paladin's Aura of Courage (L10+ in range).")
        .def("apply_maneuver_effect",
             &CombatEngine::applyManeuverEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("maneuver_type"),
             "Battle Master Maneuver: after a qualifying hit (conditions.maneuver_available),\n"
             "spend 1 Superiority Die and apply one rider (DC = 8 + PB + max(STR,DEX) mod):\n"
             "0=Trip (STR save or Prone), 1=Menacing (WIS save or Frightened), 2=Pushing (15 ft),\n"
             "3=Goading (WIS save or Disadvantage attacking anyone but you), 4=Distracting (next\n"
             "attack vs target by another creature has Advantage), 5=Disarming (STR save or fights\n"
             "with improvised Unarmed Strikes until your next turn).\n"
             "Returns a ManeuverResult with save details / push distance.")
        .def("apply_sweeping_attack",
             &CombatEngine::applySweepingAttack,
             py::arg("battle_map"), py::arg("action"), py::arg("result"), py::arg("secondary_idx"),
             "Battle Master Sweeping Attack: after a qualifying hit (conditions.maneuver_available),\n"
             "spend 1 Superiority Die to splash the same attack onto a 2nd creature within 5 ft of the\n"
             "original target. If the original attack roll (result.total_roll) would hit the 2nd\n"
             "creature's AC, it takes superiority-die damage of the attack's type. Returns a\n"
             "ManeuverResult (extra_damage / extra_target_down; save_dc=2nd AC, save_roll=orig roll).")
        .def("apply_rally",
             &CombatEngine::applyRally,
             py::arg("battle_map"), py::arg("fighter_idx"), py::arg("target_idx"),
             "Battle Master Rally (Bonus Action): spend 1 Superiority Die to grant a creature within\n"
             "30 ft Temporary HP = superiority die + your CHA modifier (min 1). Returns temp HP granted\n"
             "(0 = no die / bad index).")
        .def("apply_mantle_of_inspiration",
             &CombatEngine::bardMantleOfInspiration,
             py::arg("battle_map"), py::arg("bard_idx"), py::arg("targets"),
             "College of Glamour Mantle of Inspiration (Bonus Action): expend 1 Bardic Inspiration\n"
             "use and roll the Bardic Inspiration die ONCE; each chosen creature gains Temporary HP =\n"
             "twice the roll. 'targets' is a list of agent indices (the GUI validates the 60 ft range\n"
             "per click); the engine caps it to the bard's CHA modifier (min 1) and skips the bard\n"
             "itself. Returns the temp HP granted to each recipient (0 = not a L3+ Glamour Bard / no\n"
             "Bardic Inspiration use).")
        .def("apply_feinting_attack",
             &CombatEngine::applyFeintingAttack,
             py::arg("battle_map"), py::arg("fighter_idx"), py::arg("target_idx"),
             "Battle Master Feinting Attack (Bonus Action): spend 1 Superiority Die to feint a creature\n"
             "within 5 ft — Advantage on your next attack vs it this turn, and that hit adds the die to\n"
             "damage (conditions.feint_target_idx). Returns False if no die.")
        .def("prepare_quick_toss",
             &CombatEngine::prepareQuickToss,
             py::arg("battle_map"), py::arg("fighter_idx"),
             "Battle Master Quick Toss (Bonus Action): spend 1 Superiority Die to arm a superiority-die\n"
             "damage bonus on your next thrown-weapon attack this turn (conditions.quick_toss_die_pending).\n"
             "The GUI then makes the actual thrown attack. Returns False if no die.")
        .def("apply_precision_attack_effect",
             &CombatEngine::applyPrecisionAttackEffect,
             py::arg("battle_map"), py::arg("action"), py::arg("result"),
             "Battle Master Precision Attack: after a non-fumble miss (conditions.maneuver_precision_available),\n"
             "spend 1 Superiority Die, add 1d8/d10 to the roll, and recompute the hit.\n"
             "May convert a miss to a hit with full weapon damage. Mutates result in place.")
        .def("execute_flurry_of_blows",
             &CombatEngine::executeFlurryOfBlows,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("rider_option"),
             "Monk Flurry of Blows: spend 1 Focus Point to make two bonus-action unarmed strikes\n"
             "against the same target, optionally applying an Open Hand rider on each hit.\n"
             "rider_option: -1=None, 0=Knockdown, 1=Push, 2=DenyReaction.\n"
             "Returns a FlurryResult containing both attack results and rider results.")
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
        .def("apply_paralyzed",
             &CombatEngine::applyParalyzed,
             py::arg("battle_map"), py::arg("idx"),
             "Apply paralyzed condition to agent[idx]: sets paralyzed=true, incapacitated=true, and all movement speeds to 0.")
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
             "Truesight/Blindsight in range. Geometric line-of-sight is separate.")
        .def("reseed", &CombatEngine::reseed, py::arg("seed"))
        ;
}
