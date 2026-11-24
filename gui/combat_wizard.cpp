// ─────────────────────────────────────────────────────────────────────────────
//  combat_wizard.cpp  –  CombatEngine Wizard features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Diviner.
//  Contents: Portent dice.
//
//  Split out of combat_riders.cpp and combat_resources.cpp in COMBAT_REFACTOR_PLAN.md R6
//  (plans/COMBAT_CLASS_SPLIT_PLAN.md).
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace rpg {

bool CombatEngine::usePortentDie(BattleMap& bm, int agent_idx, int die_index, int current_round) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard with Portent Dice resource
    if (stats.lacksClass(Wizard) || stats.wizard_subclass != DivinierPath) {
        log_("{} is not a Diviner Wizard", agentName(bm, agent_idx));
        return false;
    }

    auto* portent_res = stats.getResource("Portent Dice");
    if (!portent_res) {
        log_("{} has no Portent Dice resource", agentName(bm, agent_idx));
        return false;
    }

    // Check if this agent already used a portent this round
    auto it = ctx_.agent_portent_round_used_.find(agent_idx);
    if (it != ctx_.agent_portent_round_used_.end() && it->second == current_round) {
        log_("{} already used Portent Dice in round {}", agentName(bm, agent_idx), current_round);
        return false;
    }

    // Check if die_index is valid and portent_dice has that index
    if (die_index < 0 || die_index >= static_cast<int>(stats.portent_dice.size())) {
        log_("{} has no portent die at index {}", agentName(bm, agent_idx), die_index);
        return false;
    }

    // Get the die value and remove it from the deque
    int die_value = stats.portent_dice[static_cast<std::size_t>(die_index)];
    stats.portent_dice.erase(stats.portent_dice.begin() + die_index);

    // Decrement the resource
    portent_res = stats.getResource("Portent Dice");
    if (portent_res) {
        portent_res->current = std::max(0, portent_res->current - 1);
    }

    // Set pending portent for next roll
    ctx_.pending_portent_die_ = die_value;

    // Track that this agent used a portent in this round
    ctx_.agent_portent_round_used_[agent_idx] = current_round;

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} using Portent Die: value={}, remaining={}/{}",
         agentName(bm, agent_idx), die_value, portent_res ? portent_res->current : 0,
         portent_res ? portent_res->max : 0);

    return true;
}

void CombatEngine::regeneratePortentDice(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard
    if (stats.lacksClass(Wizard) || stats.wizard_subclass != DivinierPath) {
        return;
    }

    auto* portent_res = stats.getResource("Portent Dice");
    if (!portent_res) {
        return;
    }

    // Clear old dice and roll new ones
    stats.portent_dice.clear();
    int count = portent_res->current;  // Use current after long rest restoration
    for (int i = 0; i < count; ++i) {
        stats.portent_dice.push_back(roll(20));
    }

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} regenerated {} Portent Dice: [{}]",
         agentName(bm, agent_idx), count,
         [&]() {
             std::string vals;
             for (int i = 0; i < static_cast<int>(stats.portent_dice.size()); ++i) {
                 if (i > 0) vals += ", ";
                 vals += std::to_string(stats.portent_dice[static_cast<std::size_t>(i)]);
             }
             return vals;
         }());
}

// ─────────────────────────────────────────────────────────────────────────────
//  Moved from combat_spells.cpp (COMBAT_CLASS_SPLIT_PLAN.md R6c)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::expendArcaneWardSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Validate: Abjurer L3+ with active ward
    if (stats.lacksClass(Wizard) || stats.wizard_subclass != AbjurerPath ||
        stats.classLevel(CharacterClass::Wizard) < 3 || stats.temp_hp <= 0) {
        return false;
    }

    // Validate: slot_level is valid (1-9)
    if (slot_level < 1 || slot_level > 9) return false;

    // Validate: agent has remaining spell slot at this level
    if (stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)] <= 0) {
        return false;
    }

    // Expend the slot
    stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)]--;

    // Charge the ward
    int max_ward = 2 * stats.classLevel(CharacterClass::Wizard) + (stats.intel - 10) / 2;
    int ward_gain = 2 * slot_level;
    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends Level {} slot, Arcane Ward now {}/{}",
         agentName(bm, agent_idx), slot_level, stats.temp_hp, max_ward);

    return true;
}


} // namespace rpg
