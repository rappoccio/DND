// ─────────────────────────────────────────────────────────────────────────────
//  combat_conditions.cpp  –  CombatEngine status-effect application + lifecycle
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · Condition application — apply* status setters (Paralyzed, Blinded, …),
//                              updateDarknessBlinding, dropAgentWeapons
//    · Condition lifecycle   — addAgentCondition, removeAgentCondition,
//                              activeAgentConditions, tickAgentConditions,
//                              tickAgentConditionsForCaster
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Condition application
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyParalyzed(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set paralyzed condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.paralyzed = true;
    cond.incapacitated = true;  // Paralyzed is incapacitated
    bm.setAgentConditions(idx, cond);

    // Set all movement speeds to 0
    Agent::Stats stats = bm.getAgentStats(idx);
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 0;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;
    bm.setAgentStats(idx, stats);

    log_("Agent paralyzed: movement speed set to 0, incapacitated");
}

void CombatEngine::applyBlinded(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set blinded condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.blinded = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent blinded: attack rolls have disadvantage, attacks against have advantage");
}

void CombatEngine::updateDarknessBlinding(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    // Single source of truth: the live light-effect layer, as perceived by THIS agent. A Shadow Arts:
    // Darkness caster sees through their own Darkness (getLightLevelFor reports a non-dark level for
    // them), so it never blinds them. The dead obscuration layer is no longer consulted — fog/cloud
    // spells now write light_level into this same layer (DARKNESS_MERGE_HANDOFF.md Phase 1).
    const VisibilityLevel light = bm.getLightLevelFor(pa.origin, agent_idx);

    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    bool should_be_blinded = false;

    // Magical darkness is the most restrictive, so it takes priority.
    if (light == VisibilityLevel::MagicalDark) {
        // Magically Dark (Impenetrable): blinded unless have devil's sight
        should_be_blinded = (stats.devilssight_range == 0);
    } else if (light == VisibilityLevel::HeavilyObscured) {
        // Fog/smoke (non-magical heavy obscurement): blinded unless Truesight/Blindsight. Neither
        // darkvision nor devil's sight pierces a physical cloud.
        should_be_blinded = (stats.truesight_range == 0 && stats.blindsight_range == 0);
    } else if (light == VisibilityLevel::Dark) {
        // Heavily Obscured by Darkness: blinded unless have darkvision
        should_be_blinded = (stats.darkvision_range == 0);
    }
    // BrightLight: full visibility, never blinded
    // DimLight: lightly obscured but visible, never blinded
    // PartiallyObscured: not fully blinded (disadvantage on perception, but not Blinded condition)

    // Apply or remove blinded condition as needed
    if (should_be_blinded && !cond.blinded) {
        cond.blinded = true;
	cond.has_disadvantage = true; 
        bm.setAgentConditions(agent_idx, cond);
        log_("{} is blinded by darkness", pa.agent->name());
    } else if (!should_be_blinded && cond.blinded) {
        // Only remove blinded if it was from darkness (not from a spell like Blindness/Deafness)
        // For now, we'll remove it - in future we could track the source
        cond.blinded = false;
	cond.has_disadvantage = false; 
        bm.setAgentConditions(agent_idx, cond);
        log_("{} can see again", pa.agent->name());
    }
}

void CombatEngine::applyIncapacitated(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set incapacitated condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.incapacitated = true;
    bm.setAgentConditions(idx, cond);

    // Break concentration if the agent is concentrating.
    // dropConcentration cascades removal of terrain + spell-effects + conditions.
    if (cond.concentrating) {
        [[maybe_unused]] auto dropped = dropConcentration(bm, idx);
        log_("Agent incapacitated: concentration broken");
    }

    // Set all movement speeds to 0
    Agent::Stats stats = bm.getAgentStats(idx);
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 0;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;
    bm.setAgentStats(idx, stats);

    log_("Agent incapacitated: cannot act, movement speed set to 0");
}

void CombatEngine::applyStunned(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set stunned condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.stunned = true;
    cond.incapacitated = true;  // Stunned is incapacitated
    bm.setAgentConditions(idx, cond);

    log_("Agent stunned: cannot act, auto-fails STR/DEX saves, attacks have advantage");
}

void CombatEngine::applyCharmed(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set charmed condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.charmed = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent charmed: cannot attack the charmer or target with damaging abilities/effects");
}

void CombatEngine::dropAgentWeapons(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Get mutable reference and drop all non-empty weapons
    PlacedAgent& pa = const_cast<PlacedAgent&>(agents[idx]);
    for (auto& w : pa.weapons) {
        if (!w.name.empty() && w.name != "Unarmed" && w.name != "MonkUnarmed") {
	    log_("{} dropped weapon {}", agentName(bm, idx), w.name);
            (void)bm.placeItem(pa.origin, w, "");
            w = Weapon{};
        }
    }
}

void CombatEngine::applyFrightened(BattleMap& bm, int idx) noexcept
{
    // Aura of Courage (allied Paladin L10+ in range): immune to the Frightened condition.
    if (hasAuraOfCourage(bm, idx)) {
        log_("{} can't be Frightened (Aura of Courage)", agentName(bm, idx));
        return;
    }
    dropAgentWeapons(bm, idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.frightened = true;
    bm.setAgentConditions(idx, cond);
    log_("Agent is Frightened: dropped weapons, disadvantage on attacks/checks when fear source in LOS, cannot approach");
}

void CombatEngine::applyProne(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set prone condition (movement restricted to crawling, disadvantage on attacks)
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.prone = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is now prone: movement costs doubled (triple in difficult terrain), disadvantage on attack rolls");
}

int CombatEngine::applyPush(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return 0;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.push_available) return 0;          // only after a qualifying Push hit
    ac.push_available = false;
    ac.push_used_this_turn = true;             // mark as used (once per turn)
    bm.setAgentConditions(attacker_idx, ac);

    const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
    int feet = bm.forceMoveAgent(target_idx, origin, 10) * 5;
    if (feet > 0)
        log_("{} pushes {} {} ft (Push mastery)",
             agentName(bm, attacker_idx), agentName(bm, target_idx), feet);
    return feet;
}

void CombatEngine::applyHidden(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.hidden = true;
    bm.setAgentConditions(idx, cond);

    log_("{} is now hidden", agents[static_cast<std::size_t>(idx)].agent->name());
}

void CombatEngine::applyUnconscious(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    dropAgentWeapons(bm, idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.unconscious = true;
    cond.incapacitated = true;
    cond.prone = true;

    // NPCs do not make death saves: they die outright at 0 HP. Only player
    // characters fall unconscious and roll death saves on their turns.
    if (bm.getAgentStats(idx).is_npc) {
        cond.dead = true;
        bm.setAgentConditions(idx, cond);
        log_("{} drops to 0 HP and dies (NPC — no death saves)", agents[static_cast<std::size_t>(idx)].agent->name());
        return;
    }

    bm.setAgentConditions(idx, cond);

    log_("Agent is Unconscious: incapacitated, prone, speed 0, attacks have advantage, auto-fail STR/DEX saves, auto-crit within 5ft");
}

void CombatEngine::reviveOnHeal(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    if (bm.getAgentStats(idx).hp_cur <= 0) return;   // still at 0 HP — nothing to recover from

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.dead) return;                     // true death needs revival magic, not healing
    // Only act when the creature was actually downed; a heal on a conscious creature is a no-op here.
    if (!cond.unconscious && !cond.stabilized &&
        cond.death_save_successes == 0 && cond.death_save_failures == 0)
        return;

    // Regaining any HP from 0 returns the creature to consciousness and clears death saves
    // (D&D 5e), so begin_turn no longer skips them. Prone is left in place — they stand on
    // their turn, per RAW. Static (no `this`), so the heal log lives at the calling sites.
    cond.unconscious          = false;
    cond.incapacitated        = false;
    cond.stabilized           = false;
    cond.death_save_successes  = 0;
    cond.death_save_failures   = 0;
    bm.setAgentConditions(idx, cond);
}

void CombatEngine::applyPoisoned(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    // Petrified agents are immune to poison
    if (cond.petrified) {
        log_("Agent is immune to poison (petrified)");
        return;
    }

    cond.poisoned = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is Poisoned: disadvantage on attack rolls and ability checks");
}

void CombatEngine::applyDeafened(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.deafened = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is Deafened: cannot hear; auto-fail ability checks requiring hearing");
}

void CombatEngine::applyPetrified(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set condition flags
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.petrified = true;
    cond.incapacitated = true;
    bm.setAgentConditions(idx, cond);

    // Set all movement speeds to 0
    Agent::Stats stats = bm.getAgentStats(idx);
    stats.speed_walk = 0;
    stats.speed_fly = 0;
    stats.speed_swim = 0;
    stats.speed_burrow = 0;
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 0;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;

    // Set all damage multipliers to 0.5 (resistance to all damage)
    for (std::size_t i = 0; i < stats.magic_damage_multipliers.size(); ++i) {
        stats.magic_damage_multipliers[i] = 0.5f;
    }
    for (std::size_t i = 0; i < stats.physical_damage_multipliers.size(); ++i) {
        stats.physical_damage_multipliers[i] = 0.5f;
    }

    bm.setAgentStats(idx, stats);
    log_("Agent is Petrified: incapacitated, speed 0, resistance to all damage (0.5x), immune to poisoned, auto-fail STR/DEX saves, attacks have advantage");
}

void CombatEngine::applyGrappled(BattleMap& bm, int target_idx, int grappler_idx, int escape_dc) noexcept
{
    Agent::Conditions cond = getAgentConditions(bm, target_idx);
    cond.grappled = true;
    cond.grappler_idx = grappler_idx;
    cond.grapple_escape_dc = escape_dc;
    cond.grapple_range_ft = 5;
    setAgentConditions(bm, target_idx, cond);
}

void CombatEngine::applyCommandEffect(BattleMap& bm, int bard_idx, int target_idx, int word) noexcept
{
    auto agents = bm.placedAgents();
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return;
    if (word < 0 || word > 4) word = 3;  // default to Halt when the caller doesn't specify a word

    // The movement / incapacitation effects are keyed to the bard with a 1-turn duration, so they
    // expire when the bard's next turn begins (tickAgentConditionsForCaster) — i.e. they constrain
    // exactly the target's one intervening "next turn", matching Command's RAW timing.
    switch (word) {
        case 0: {  // Drop — drops what it's holding (reuse the Disarming Strike path)
            dropAgentWeapons(bm, target_idx);
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.disarmed    = true;
            tc.disarmed_by = bard_idx;
            bm.setAgentConditions(target_idx, tc);
            log_("Command (Drop): {} drops what it is holding", agentName(bm, target_idx));
            break;
        }
        case 1: {  // Flee — moves away from the bard; modeled as a 1-turn "can't approach" restriction
            ActiveAgentCondition c;
            c.agent_idx       = target_idx;
            c.caster_idx      = bard_idx;
            c.condition_name  = "CommandFlee";
            c.turns_remaining = 1;
            (void)addAgentCondition(bm, c);
            log_("Command (Flee): {} must move away from {} on its next turn",
                 agentName(bm, target_idx), agentName(bm, bard_idx));
            break;
        }
        case 2:    // Grovel — the target falls Prone and ends its turn
            applyProne(bm, target_idx);
            log_("Command (Grovel): {} falls Prone", agentName(bm, target_idx));
            break;
        case 3: {  // Halt — no move, no action, no Bonus Action next turn (Incapacitated for one turn)
            ActiveAgentCondition c;
            c.agent_idx        = target_idx;
            c.caster_idx       = bard_idx;
            c.condition_name   = "Incapacitated";
            c.turns_remaining  = 1;
            c.save_repeat_turns = -1;  // no save — the target simply skips its next turn
            (void)addAgentCondition(bm, c);
            log_("Command (Halt): {} won't move or act on its next turn", agentName(bm, target_idx));
            break;
        }
        case 4: {  // Approach — moves toward the bard; modeled as a 1-turn "can't retreat" restriction
            ActiveAgentCondition c;
            c.agent_idx       = target_idx;
            c.caster_idx      = bard_idx;
            c.condition_name  = "CommandApproach";
            c.turns_remaining = 1;
            (void)addAgentCondition(bm, c);
            log_("Command (Approach): {} must move toward {} on its next turn",
                 agentName(bm, target_idx), agentName(bm, bard_idx));
            break;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Condition lifecycle
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::addAgentCondition(BattleMap& bm, ActiveAgentCondition cond) noexcept
{
    cond.condition_id = nextConditionId_++;

    // Apply the condition to the agent
    if (cond.agent_idx >= 0) {
        auto agents = bm.placedAgents();
        if (cond.agent_idx < static_cast<int>(agents.size())) {
            if (cond.condition_name == "Paralyzed") {
                applyParalyzed(bm, cond.agent_idx);
            } else if (cond.condition_name == "Blinded") {
                applyBlinded(bm, cond.agent_idx);
            } else if (cond.condition_name == "Incapacitated") {
                applyIncapacitated(bm, cond.agent_idx);
            } else if (cond.condition_name == "Stunned") {
                applyStunned(bm, cond.agent_idx);
            } else if (cond.condition_name == "Charmed") {
                applyCharmed(bm, cond.agent_idx);
                // Track the charm source so Mantle of Majesty can auto-fail Command for a creature
                // Charmed by the casting bard.
                auto cc = bm.getAgentConditions(cond.agent_idx);
                cc.charmed_by = cond.caster_idx;
                bm.setAgentConditions(cond.agent_idx, cc);
            } else if (cond.condition_name == "Frightened") {
                applyFrightened(bm, cond.agent_idx);
            } else if (cond.condition_name == "Unconscious") {
                applyUnconscious(bm, cond.agent_idx);
            } else if (cond.condition_name == "Poisoned") {
                applyPoisoned(bm, cond.agent_idx);
            } else if (cond.condition_name == "Deafened") {
                applyDeafened(bm, cond.agent_idx);
            } else if (cond.condition_name == "Petrified") {
                applyPetrified(bm, cond.agent_idx);
            } else if (cond.condition_name == "Invisible" || cond.condition_name == "GreaterInvisible") {
                auto ac = bm.getAgentConditions(cond.agent_idx);
                ac.invisible = true;
                // Greater Invisibility does not end when the creature attacks or casts.
                ac.invisible_persists_on_action = (cond.condition_name == "GreaterInvisible");
                bm.setAgentConditions(cond.agent_idx, ac);
            }
            log_("Applied condition '{}' to {} for {} turns",
                 cond.condition_name, agentName(bm, cond.agent_idx), cond.turns_remaining);
        }
    }

    activeAgentConditions_.push_back(cond);
    return cond.condition_id;
}

void CombatEngine::removeAgentCondition(int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                          [condition_id](const ActiveAgentCondition& c) { return c.condition_id == condition_id; });
    if (it != activeAgentConditions_.end()) {
        activeAgentConditions_.erase(it);
    }
}

const std::vector<ActiveAgentCondition>& CombatEngine::activeAgentConditions() const noexcept
{
    return activeAgentConditions_;
}

std::vector<int> CombatEngine::tickAgentConditions(BattleMap& bm) noexcept
{
    std::vector<int> removed_ids;

    for (auto& cond : activeAgentConditions_) {
        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);

            // Remove the condition from the agent
            if (cond.agent_idx >= 0) {
                auto agents = bm.placedAgents();
                if (cond.agent_idx < static_cast<int>(agents.size())) {
                    auto agent_cond = bm.getAgentConditions(cond.agent_idx);
                    if (cond.condition_name == "Paralyzed") {
                        agent_cond.paralyzed = false;
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Blinded") {
                        agent_cond.blinded = false;
                    } else if (cond.condition_name == "Incapacitated") {
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Stunned") {
                        agent_cond.stunned = false;
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Charmed") {
                        agent_cond.charmed = false;
                        agent_cond.charmed_by = -1;
                    } else if (cond.condition_name == "Frightened") {
                        agent_cond.frightened = false;
                    } else if (cond.condition_name == "Unconscious") {
                        agent_cond.unconscious = false;
                        agent_cond.incapacitated = false;
                        // Keep prone=true per 5e rule: "When this condition ends, you remain Prone"
                    } else if (cond.condition_name == "Invisible" || cond.condition_name == "GreaterInvisible") {
                        agent_cond.invisible = false;
                        agent_cond.invisible_persists_on_action = false;
                    }
                    bm.setAgentConditions(cond.agent_idx, agent_cond);
                    log_("Condition '{}' expired for {}",
                         cond.condition_name, agentName(bm, cond.agent_idx));
                }
            }
        }
    }

    // Remove expired conditions
    std::vector<ActiveAgentCondition> remaining;
    for (const auto& cond : activeAgentConditions_) {
        if (std::find(removed_ids.begin(), removed_ids.end(), cond.condition_id) == removed_ids.end()) {
            remaining.push_back(cond);
        }
    }
    activeAgentConditions_ = remaining;

    return removed_ids;
}

std::vector<int> CombatEngine::tickAgentConditionsForCaster(BattleMap& bm, int caster_idx) noexcept
{
    std::vector<int> removed_ids;

    for (auto& cond : activeAgentConditions_) {
        // Only tick conditions cast by this caster
        if (cond.caster_idx != caster_idx) continue;

        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);

            // Remove the condition from the agent
            if (cond.agent_idx >= 0) {
                auto agents = bm.placedAgents();
                if (cond.agent_idx < static_cast<int>(agents.size())) {
                    auto agent_cond = bm.getAgentConditions(cond.agent_idx);
                    if (cond.condition_name == "Paralyzed") {
                        agent_cond.paralyzed = false;
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Blinded") {
                        agent_cond.blinded = false;
                    } else if (cond.condition_name == "Incapacitated") {
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Stunned") {
                        agent_cond.stunned = false;
                        agent_cond.incapacitated = false;
                    } else if (cond.condition_name == "Charmed") {
                        agent_cond.charmed = false;
                        agent_cond.charmed_by = -1;
                    } else if (cond.condition_name == "Frightened") {
                        agent_cond.frightened = false;
                    } else if (cond.condition_name == "Unconscious") {
                        agent_cond.unconscious = false;
                        agent_cond.incapacitated = false;
                        // Keep prone=true per 5e rule: "When this condition ends, you remain Prone"
                    }
                    bm.setAgentConditions(cond.agent_idx, agent_cond);
                    log_("Condition '{}' expired for {} (spell duration ended)",
                         cond.condition_name, agentName(bm, cond.agent_idx));
                }
            }
        }
    }

    // Remove expired conditions
    std::vector<ActiveAgentCondition> remaining;
    for (const auto& cond : activeAgentConditions_) {
        if (std::find(removed_ids.begin(), removed_ids.end(), cond.condition_id) == removed_ids.end()) {
            remaining.push_back(cond);
        }
    }
    activeAgentConditions_ = remaining;

    return removed_ids;
}

} // namespace rpg
