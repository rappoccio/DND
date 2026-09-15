// ─────────────────────────────────────────────────────────────────────────────
//  combat_contested.cpp  –  CombatEngine contested physical actions
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//
//  Shove, Grapple, Grapple Escape, Pick Lock and Break Door: actions resolved by
//  one creature's check against another creature's check or against a fixed object
//  DC. COMBAT_REFACTOR_PLAN.md's R4 section flags these as one of two mis-groupings
//  in combat_riders.cpp — they are neither on-hit riders nor reactions, and this TU
//  is the "own ContestedActions module" that section calls for.
//
//  Sections:
//    · Shove          — executeShove
//    · Objects        — attemptPickLock, attemptBreakDoor
//    · Grapple        — resolveGrapple (shared core), executeGrapple,
//                       executeGrappleEscape
//
//  Deliberately NOT a sub-engine class, unlike VisibilityService / MovementController /
//  ConditionTracker: these six functions own no state at all. R4b's rule — a sub-engine
//  takes a CombatContext& when it needs one, not on principle — applies a level up here:
//  a module becomes a class when it owns state. Wrapping six stateless functions would
//  buy nothing a translation unit does not already give, while forcing the same
//  applyProne/applyGrappled seam R4a had to hand-verify for checkHide/applyHidden.
//  So this is a pure TU move: every body below is byte-identical to the one that was
//  in combat_riders.cpp, and every call site (C++, pybind11, main.py) is untouched.
//
//  applyTelekineticShove stays in combat_riders.cpp on purpose. It is spelled "shove"
//  but it is a saving throw against a feat's DC, not a contested check, and it is a
//  Telekinetic-feat activation — a rider, which is what that file is for.
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Shove
// ─────────────────────────────────────────────────────────────────────────────

ShoveResult CombatEngine::executeShove(BattleMap& bm, const ShoveAction& action)
{
    ShoveResult result;
    auto agents = bm.placedAgents();

    // Validate indices
    if (action.attacker_idx < 0 || action.attacker_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid attacker index.";
        return result;
    }
    if (action.target_idx < 0 || action.target_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid target index.";
        return result;
    }
    if (action.attacker_idx == action.target_idx) {
        result.log_message = "Cannot shove yourself.";
        return result;
    }

    auto& attacker = agents[action.attacker_idx];
    auto& target = agents[action.target_idx];

    // Check adjacency (within 5ft = 1 cell in any direction)
    int dx = std::abs(target.origin.col - attacker.origin.col);
    int dy = std::abs(target.origin.row - attacker.origin.row);
    int distance_cells = std::max(dx, dy);  // Chebyshev distance
    if (distance_cells > 1) {
        result.log_message = "Target is not adjacent (within 5 feet).";
        return result;
    }

    // Roll attacker Athletics: d20 + STR mod + proficiency (assume all shoves are proficient)
    int attacker_str_mod = (attacker.agent->getStats().str - 10) / 2;
    auto attacker_stats = getAgentStats(bm, action.attacker_idx);
    int attacker_prof = attacker_stats.prof_bonus;
    int attacker_d20 = roll(20);
    int attacker_total = attacker_d20 + attacker_str_mod + attacker_prof;

    // Roll defender: max(Athletics, Acrobatics) = max(STR, DEX) + d20
    int target_str_mod = (target.agent->getStats().str - 10) / 2;
    int target_dex_mod = (target.agent->getStats().dex - 10) / 2;
    int target_d20 = roll(20);
    int target_athletic = target_d20 + target_str_mod;
    int target_acrobatic = target_d20 + target_dex_mod;
    int defender_total = std::max(target_athletic, target_acrobatic);

    result.valid = true;
    result.attacker_roll = attacker_total;
    result.defender_roll = defender_total;
    result.success = (attacker_total > defender_total);  // ties go to defender

    if (result.success) {
        if (action.knock_prone) {
            applyProne(bm, action.target_idx);
            result.knocked_prone = true;
            result.log_message = "\"" + std::string(attacker.agent->name()) + "\" knocked \"" + std::string(target.agent->name()) + "\" prone.";
        } else {
            // Push 5ft away
            int cells_moved = bm.forceMoveAgent(action.target_idx, attacker.origin, 5);
            result.push_ft_applied = cells_moved * 5;
            if (result.push_ft_applied > 0) {
                result.log_message = "\"" + std::string(attacker.agent->name()) + "\" pushed \"" + std::string(target.agent->name()) + "\" " + std::to_string(result.push_ft_applied) + " feet.";
            } else {
                result.log_message = "\"" + std::string(attacker.agent->name()) + "\" tried to push \"" + std::string(target.agent->name()) + "\" but they didn't move.";
            }
        }
    } else {
        result.log_message = "\"" + std::string(target.agent->name()) + "\" resisted the shove from \"" + std::string(attacker.agent->name()) + "\".";
    }

    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Objects — locked and barred doors
// ─────────────────────────────────────────────────────────────────────────────

PickLockResult CombatEngine::attemptPickLock(BattleMap& bm, int agent_idx, int door_id)
{
    PickLockResult result;
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid agent index.";
        return result;
    }

    // Locate the door by id.
    const Door* door = nullptr;
    for (const Door& d : bm.doors()) {
        if (d.id == door_id) { door = &d; break; }
    }
    if (door == nullptr) {
        result.log_message = "No such door.";
        return result;
    }

    const auto& picker = agents[agent_idx];
    const std::string name = std::string(picker.agent->name());

    if (!door->locked) {
        result.valid = true;
        result.dc = door->lock_dc;
        result.log_message = "\"" + name + "\" — that door isn't locked.";
        return result;
    }
    if (door->arcane_lock && door->arcane_suppressed_turns <= 0) {
        result.valid = true;
        result.dc = door->lock_dc;
        result.log_message = "\"" + name + "\" cannot pick an Arcane Lock.";
        return result;
    }

    const Agent::Stats st = getAgentStats(bm, agent_idx);
    int bonus = st.sleightOfHand();
    int d20 = roll(20);

    result.valid   = true;
    result.roll    = d20;
    result.total   = d20 + bonus;
    result.dc      = door->lock_dc;
    result.success = result.total >= result.dc;

    if (result.success) {
        bm.unlockDoor(door_id);
        result.log_message = "\"" + name + "\" picks the lock (Sleight of Hand " +
                             std::to_string(result.total) + " vs DC " +
                             std::to_string(result.dc) + ").";
    } else {
        result.log_message = "\"" + name + "\" fails to pick the lock (Sleight of Hand " +
                             std::to_string(result.total) + " vs DC " +
                             std::to_string(result.dc) + ").";
    }
    log_("{}", result.log_message);
    return result;
}

BreakDoorResult CombatEngine::attemptBreakDoor(BattleMap& bm, int agent_idx, int door_id)
{
    BreakDoorResult result;
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid agent index.";
        return result;
    }

    // Locate the door by id.
    const Door* door = nullptr;
    for (const Door& d : bm.doors()) {
        if (d.id == door_id) { door = &d; break; }
    }
    if (door == nullptr) {
        result.log_message = "No such door.";
        return result;
    }

    const auto& breaker = agents[agent_idx];
    const std::string name = std::string(breaker.agent->name());

    if (door->broken) {
        result.valid = true;
        result.log_message = "\"" + name + "\" — that door is already smashed off its frame.";
        return result;
    }
    if (door->open) {
        result.valid = true;
        result.log_message = "\"" + name + "\" — that door is already open.";
        return result;
    }

    // Effective DC: an active Arcane Lock stiffens the door by +10 (RAW). A suppressed
    // Arcane Lock (Knock) imposes no penalty.
    int dc = door->break_dc;
    if (door->arcane_lock && door->arcane_suppressed_turns <= 0) dc += 10;

    const Agent::Stats st = getAgentStats(bm, agent_idx);
    int bonus = st.athletics();
    int d20 = roll(20);

    result.valid   = true;
    result.roll    = d20;
    result.total   = d20 + bonus;
    result.dc      = dc;
    result.success = result.total >= result.dc;

    if (result.success) {
        bm.breakDoor(door_id);
        result.log_message = "\"" + name + "\" breaks the door down (Athletics " +
                             std::to_string(result.total) + " vs DC " +
                             std::to_string(result.dc) + ").";
    } else {
        result.log_message = "\"" + name + "\" fails to force the door (Athletics " +
                             std::to_string(result.total) + " vs DC " +
                             std::to_string(result.dc) + ").";
    }
    log_("{}", result.log_message);
    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Grapple
// ─────────────────────────────────────────────────────────────────────────────

GrappleResult CombatEngine::resolveGrapple(BattleMap& bm, int attacker_idx, int target_idx,
                                           bool contested, int escape_dc_override) noexcept
{
    GrappleResult result;
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size()) ||
        attacker_idx == target_idx) {
        return result;
    }

    auto& attacker = agents[attacker_idx];
    auto& target   = agents[target_idx];

    // Attacker Athletics: d20 + STR mod + proficiency (grapple assumed proficient).
    int attacker_str_mod = (attacker.agent->getStats().str - 10) / 2;
    auto attacker_stats = getAgentStats(bm, attacker_idx);
    int attacker_prof = attacker_stats.prof_bonus;

    result.valid = true;
    if (contested) {
        int attacker_d20 = roll(20);
        int attacker_total = attacker_d20 + attacker_str_mod + attacker_prof;
        // Defender: max(Athletics, Acrobatics) = max(STR, DEX) + the same d20.
        int target_str_mod = (target.agent->getStats().str - 10) / 2;
        int target_dex_mod = (target.agent->getStats().dex - 10) / 2;
        int target_d20 = roll(20);
        int defender_total = std::max(target_d20 + target_str_mod, target_d20 + target_dex_mod);
        result.attacker_roll = attacker_total;
        result.defender_roll = defender_total;
        result.success = (attacker_total > defender_total);  // ties go to defender
    } else {
        // Automatic on a qualifying hit (the attack already landed).
        result.success = true;
    }

    if (result.success) {
        // Fixed escape DC override, else the standard 10 + STR mod + proficiency.
        result.escape_dc = (escape_dc_override > 0) ? escape_dc_override
                                                    : (10 + attacker_str_mod + attacker_prof);
        applyGrappled(bm, target_idx, attacker_idx, result.escape_dc);
        result.log_message = std::string("\"") + std::string(attacker.agent->name()) + "\" grapples \"" +
                             std::string(target.agent->name()) + "\" (escape DC " +
                             std::to_string(result.escape_dc) + ")";
    } else {
        result.log_message = std::string("\"") + std::string(attacker.agent->name()) + "\" fails to grapple \"" +
                             std::string(target.agent->name()) + "\" (attacker " + std::to_string(result.attacker_roll) +
                             " vs defender " + std::to_string(result.defender_roll) + ")";
    }
    return result;
}

GrappleResult CombatEngine::executeGrapple(BattleMap& bm, const GrappleAction& action)
{
    GrappleResult result;
    auto agents = bm.placedAgents();

    // Validate indices
    if (action.attacker_idx < 0 || action.attacker_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid attacker index.";
        return result;
    }
    if (action.target_idx < 0 || action.target_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid target index.";
        return result;
    }
    if (action.attacker_idx == action.target_idx) {
        result.log_message = "Cannot grapple yourself.";
        return result;
    }

    auto& attacker = agents[action.attacker_idx];
    auto& target = agents[action.target_idx];

    // Check adjacency (within 5ft = 1 cell in any direction)
    int dx = std::abs(target.origin.col - attacker.origin.col);
    int dy = std::abs(target.origin.row - attacker.origin.row);
    int distance_cells = std::max(dx, dy);  // Chebyshev distance
    if (distance_cells > 1) {
        result.log_message = "Target is not adjacent (within 5 feet).";
        return result;
    }

    // Standalone Grapple action: contested check, computed escape DC.
    return resolveGrapple(bm, action.attacker_idx, action.target_idx,
                          /*contested=*/true, /*escape_dc_override=*/0);
}

GrappleEscapeResult CombatEngine::executeGrappleEscape(BattleMap& bm, int agent_idx)
{
    GrappleEscapeResult result;
    auto agents = bm.placedAgents();

    // Validate index
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid agent index.";
        return result;
    }

    Agent::Conditions cond = getAgentConditions(bm, agent_idx);

    // Check if actually grappled
    if (!cond.grappled) {
        result.log_message = "Not grappled.";
        return result;
    }

    result.valid = true;
    result.escape_dc = cond.grapple_escape_dc;

    // Get agent stats
    auto stats = getAgentStats(bm, agent_idx);
    int str_mod = (stats.str - 10) / 2;
    int dex_mod = (stats.dex - 10) / 2;

    // Roll best of STR (Athletics) or DEX (Acrobatics)
    int str_d20 = roll(20);
    int dex_d20 = roll(20);
    int str_roll = str_d20 + str_mod;
    int dex_roll = dex_d20 + dex_mod;
    result.escape_roll = std::max(str_roll, dex_roll);

    // Check success
    if (result.escape_roll >= result.escape_dc) {
        result.success = true;
        cond.grappled = false;
        cond.grappler_idx = -1;
        setAgentConditions(bm, agent_idx, cond);
        result.log_message = std::string("\"") + std::string(agents[agent_idx].agent->name()) + "\" escapes grapple! (rolled " +
                            std::to_string(result.escape_roll) + " vs DC " + std::to_string(result.escape_dc) + ")";
    } else {
        result.log_message = std::string("\"") + std::string(agents[agent_idx].agent->name()) + "\" fails to escape grapple (rolled " +
                            std::to_string(result.escape_roll) + " vs DC " + std::to_string(result.escape_dc) + ")";
    }

    return result;
}

} // namespace rpg
