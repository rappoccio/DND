// ─────────────────────────────────────────────────────────────────────────────
//  combat_visibility.cpp  –  CombatEngine vision & hiding
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · Visibility  — computeVisibility, getVisibility
//    · Hiding      — checkHide, checkHiddenAgentDetection
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <format>
#include <string>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Visibility
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::computeVisibility(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;

    const PlacedAgent& viewer = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& viewer_stats = viewer.agent->getStats();

    // Base perception range (in feet): half of base wisdom score, minimum 20 feet
    // This is a heuristic; D&D 5e uses specific rules per situation
    int base_perception = std::max(20, (viewer_stats.wis / 2) * 5);

    // TODO: Lighting modifiers would go here (darkvision range, light effects, etc.)
    // For now, use base perception range

    // Iterate through all other agents on the map
    for (std::size_t target_idx = 0; target_idx < agents.size(); ++target_idx) {
        if (static_cast<int>(target_idx) == agent_idx)
            continue;  // Don't check visibility to self

        const PlacedAgent& target = agents[target_idx];

        // Check if target is hidden — if so, they're invisible
        if (target.agent->getConditions().hidden) {
            int64_t key = (static_cast<int64_t>(agent_idx) << 32) | static_cast<uint32_t>(target_idx);
            visibilityMap_[key] = VisibilityLevel::Blocked;
            continue;
        }

        // Calculate distance from viewer to target (Chebyshev distance = max of dx, dy)
        int dx = std::abs(viewer.origin.col - target.origin.col);
        int dy = std::abs(viewer.origin.row - target.origin.row);
        int chebyshev_distance = std::max(dx, dy);

        VisibilityLevel visibility = VisibilityLevel::Blocked;

        // Check if target is within perception range
        if (chebyshev_distance <= (base_perception / 5)) {  // convert feet to cells (5 ft per cell)
            // Check line of sight and obscuration
            int viewer_size = viewer.agent->getSize();
            int target_size = target.agent->getSize();
            bool has_los = bm.hasLineOfSight(viewer.origin, viewer_size, target.origin, target_size);

            if (has_los) {
                // Check obscuration at target's location
                VisibilityLevel obscuration = bm.getObscurationAtCell(target.origin);

                // Check if viewer can see through magical darkness (devil's sight)
                bool can_see_through_darkness = viewer_stats.devilssight_range > (chebyshev_distance * 5);

                if (obscuration == VisibilityLevel::MagicalDark && !can_see_through_darkness) {
                    visibility = VisibilityLevel::Blocked;
                } else if (obscuration == VisibilityLevel::LightlyObscured) {
                    visibility = VisibilityLevel::LightlyObscured;
                } else {
                    visibility = VisibilityLevel::Clear;
                }
            }
        }

        // Store in visibility map using a combined key (source_idx * large_prime + target_idx)
        // This works for reasonable agent counts (< 1M agents per combat)
        int64_t key = (static_cast<int64_t>(agent_idx) << 32) | static_cast<uint32_t>(target_idx);
        visibilityMap_[key] = visibility;
    }
}

VisibilityLevel CombatEngine::getVisibility(int source_idx, int target_idx) const noexcept
{
    int64_t key = (static_cast<int64_t>(source_idx) << 32) | static_cast<uint32_t>(target_idx);
    auto it = visibilityMap_.find(key);
    if (it != visibilityMap_.end()) {
        return it->second;
    }
    // Default to Blocked if visibility hasn't been computed
    return VisibilityLevel::Blocked;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Hiding
// ─────────────────────────────────────────────────────────────────────────────

HideResult CombatEngine::checkHide(BattleMap& bm, int agent_idx, bool in_combat) noexcept
{
    HideResult result;
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid agent";
        return result;
    }

    const PlacedAgent& hider_pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& hider_stats = hider_pa.agent->getStats();
    Cell hider_origin = hider_pa.origin;
    int hider_size = hider_pa.agent->getSize();

    // Check if any other agent has LOS to the hider — if so, can't hide
    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Check line of sight
        if (bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            result.log_message = std::format(
                "{} cannot hide: {} can see them",
                hider_pa.agent->name(), observer_pa.agent->name()
            );
            return result;
        }
    }

    result.valid = true;

    // Roll Stealth check
    result.stealth_d20 = roll(20);
    int stealth_mod = hider_stats.stealthBonus();
    result.stealth_total = result.stealth_d20 + stealth_mod;

    log_("{} attempts to hide (Stealth check): d20={} + {} = {}",
         hider_pa.agent->name(), result.stealth_d20, stealth_mod, result.stealth_total);

    // Contest against agents with LOS to the hider
    bool spotted = false;
    std::string contest_log;

    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Only contest against agents who have LOS to the hider
        // (The first loop already confirmed no one has direct LOS, but checking again for clarity)
        if (!bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            continue;  // Agent can't see hider, skip Perception contest
        }

        const Agent::Stats& observer_stats = observer_pa.agent->getStats();
        int observer_perception = 0;

        if (in_combat) {
            // Active Perception roll
            int perc_d20 = roll(20);
            int perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
            observer_perception = perc_d20 + perc_mod;
            contest_log += std::format(
                "\n  {}: Perception check d20={} + {} = {}",
                observer_pa.agent->name(), perc_d20, perc_mod, observer_perception
            );
        } else {
            // Passive Perception
            observer_perception = observer_stats.passivePerception();
            contest_log += std::format("\n  {}: Passive Perception {}", observer_pa.agent->name(), observer_perception);
        }

        if (observer_perception >= result.stealth_total) {
            spotted = true;
            contest_log += " — SPOTTED";
        } else {
            contest_log += " — doesn't notice";
        }
    }

    if (spotted) {
        result.log_message = std::format(
            "{} failed to hide (Stealth {}){}",
            hider_pa.agent->name(), result.stealth_total, contest_log
        );
    } else {
        applyHidden(bm, agent_idx);
        result.hidden = true;
        result.log_message = std::format(
            "{} successfully hidden (Stealth {}){}",
            hider_pa.agent->name(), result.stealth_total, contest_log
        );
    }

    return result;
}

std::string CombatEngine::checkHiddenAgentDetection(BattleMap& bm, int agent_idx, bool in_combat) noexcept
{
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        return "";  // Invalid agent
    }

    const PlacedAgent& hider_pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Conditions& hider_cond = hider_pa.agent->getConditions();

    if (!hider_cond.hidden) {
        return "";  // Agent not hidden, no detection check needed
    }

    const Agent::Stats& hider_stats = hider_pa.agent->getStats();
    Cell hider_origin = hider_pa.origin;
    int hider_size = hider_pa.agent->getSize();
    int hider_stealth = hider_stats.stealthBonus();

    // Check each other agent for LOS
    std::string detection_log;
    bool spotted = false;

    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Only check agents with LOS to the hidden agent
        if (!bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            continue;
        }

        // Agent has LOS, roll Perception to detect
        const Agent::Stats& observer_stats = observer_pa.agent->getStats();
        int observer_perception = 0;
        int perc_d20 = 0;
        int perc_mod = 0;
        bool is_passive = false;

        if (in_combat) {
            // Active Perception roll
            perc_d20 = roll(20);
            perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
            observer_perception = perc_d20 + perc_mod;
        } else {
            // Passive Perception
            is_passive = true;
            observer_perception = observer_stats.passivePerception();
            perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
        }

        if (observer_perception >= hider_stealth) {
            spotted = true;
            if (is_passive) {
                detection_log += std::format(
                    "\n  {}: Passive Perception {} vs {} Stealth {} — SPOTTED",
                    observer_pa.agent->name(), observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            } else {
                detection_log += std::format(
                    "\n  {}: Perception d20={} + {} = {} vs {} Stealth {} — SPOTTED",
                    observer_pa.agent->name(), perc_d20, perc_mod, observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            }
        } else {
            if (is_passive) {
                detection_log += std::format(
                    "\n  {}: Passive Perception {} vs {} Stealth {} — doesn't notice",
                    observer_pa.agent->name(), observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            } else {
                detection_log += std::format(
                    "\n  {}: Perception d20={} + {} = {} vs {} Stealth {} — doesn't notice",
                    observer_pa.agent->name(), perc_d20, perc_mod, observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            }
        }
    }

    if (spotted) {
        // Reveal the hidden agent
        Agent::Conditions cond = bm.getAgentConditions(agent_idx);
        cond.hidden = false;
        bm.setAgentConditions(agent_idx, cond);

        return std::format("{} is no longer hidden{}", hider_pa.agent->name(), detection_log);
    }

    return "";  // Still hidden
}

} // namespace rpg
