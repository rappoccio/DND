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

    // A grapple ends the moment the grappler is Incapacitated (RAW). Release every
    // creature this agent was holding so they regain their Speed immediately.
    dropGrapplesBy(bm, idx);

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

    // Get mutable reference and drop all non-empty weapons (except permanently armed ones)
    PlacedAgent& pa = const_cast<PlacedAgent&>(agents[idx]);
    for (auto& w : pa.weapons) {
        if (!w.name.empty() && w.name.find("Unarmed") == std::string::npos && !w.permanently_armed) {
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

    // Dropping to 0 HP makes the agent Incapacitated, which ends any grapple it was
    // maintaining — free its victims so they aren't stuck at Speed 0 by a dead grappler.
    dropGrapplesBy(bm, idx);

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

    // Snapshot the real speeds and damage multipliers BEFORE overwriting them, so curePetrified
    // (Greater Restoration) can restore them. Guard against a double-apply clobbering a good snapshot
    // with the already-petrified 0-speed / 0.5× values.
    Agent::Stats stats = bm.getAgentStats(idx);
    if (petrifySnapshots_.find(idx) == petrifySnapshots_.end()) {
        PetrifySnapshot snap;
        snap.speed_walk   = stats.speed_walk;
        snap.speed_fly    = stats.speed_fly;
        snap.speed_swim   = stats.speed_swim;
        snap.speed_burrow = stats.speed_burrow;
        snap.magic_mult   = stats.magic_damage_multipliers;
        snap.phys_mult    = stats.physical_damage_multipliers;
        petrifySnapshots_[idx] = snap;
    }

    // Set all movement speeds to 0
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

void CombatEngine::dropGrapplesBy(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    for (size_t i = 0; i < agents.size(); ++i) {
        Agent::Conditions cond = getAgentConditions(bm, static_cast<int>(i));
        if (cond.grappler_idx == agent_idx && cond.grappled) {
            cond.grappled = false;
            cond.grappler_idx = -1;
            setAgentConditions(bm, static_cast<int>(i), cond);
        }
    }
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
            c.save_repeat_turns = -1;  // Command grants NO repeated save (RAW). Without this the struct
                                       // default (repeat every turn, DC 0, SaveDex) auto-passes at the
                                       // victim's turn start and strips the command before it can flee.
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
            c.save_repeat_turns = -1;  // no repeated save (RAW) — see the Flee case above
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
            } else if (cond.condition_name == "Sanctuary") {
                // Sanctuary ward: store the WIS save DC attackers must beat (the caster's spell save DC).
                auto ac = bm.getAgentConditions(cond.agent_idx);
                ac.sanctuary_active = true;
                ac.sanctuary_dc     = cond.save_dc;
                bm.setAgentConditions(cond.agent_idx, ac);
            }
            log_("Applied condition '{}' to {} for {} turns",
                 cond.condition_name, agentName(bm, cond.agent_idx), cond.turns_remaining);
        }
    }

    activeAgentConditions_.push_back(cond);
    return cond.condition_id;
}

void CombatEngine::removeAgentCondition(BattleMap& bm, int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                          [condition_id](const ActiveAgentCondition& c) { return c.condition_id == condition_id; });
    if (it != activeAgentConditions_.end()) {
        // Fire the caster "kickback" (Vistani Curse) on a copy BEFORE erasing — onConditionEnded
        // may apply damage that drops the caster and cascades into dropConcentration →
        // removeAgentCondition, mutating this container. No-op unless kickback_dice > 0.
        ActiveAgentCondition ended = *it;
        activeAgentConditions_.erase(it);
        onConditionEnded(bm, ended);
    }
}

const std::vector<ActiveAgentCondition>& CombatEngine::activeAgentConditions() const noexcept
{
    return activeAgentConditions_;
}

std::vector<int> CombatEngine::tickAgentConditions(BattleMap& bm) noexcept
{
    std::vector<int> removed_ids;
    // Delayed effects that auto-detonate on expiry (Delayed Blast Fireball) are resolved AFTER the
    // loop: resolveDelayedEffect can drop a creature unconscious → dropConcentration, which mutates
    // activeAgentConditions_ and would invalidate the iterators below. Copy them out and fire later.
    std::vector<ActiveAgentCondition> auto_detonate;
    // Curse "kickbacks" (Vistani) are likewise deferred: onConditionEnded may damage the caster and
    // cascade into dropConcentration, mutating activeAgentConditions_ mid-loop. Fire after rebuild.
    std::vector<ActiveAgentCondition> ended_kickbacks;

    for (auto& cond : activeAgentConditions_) {
        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);

            // Owner-triggered effects (Quivering Palm) leave delay_auto_on_expire false and simply
            // fade harmlessly when the duration runs out.
            if (cond.delayed_trigger && cond.delay_auto_on_expire)
                auto_detonate.push_back(cond);
            if (cond.kickback_dice > 0)
                ended_kickbacks.push_back(cond);

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
                    } else if (cond.condition_name == "Poisoned") {
                        agent_cond.poisoned = false;
                    } else if (cond.condition_name == "Unconscious") {
                        agent_cond.unconscious = false;
                        agent_cond.incapacitated = false;
                        // Keep prone=true per 5e rule: "When this condition ends, you remain Prone"
                    } else if (cond.condition_name == "Invisible" || cond.condition_name == "GreaterInvisible") {
                        agent_cond.invisible = false;
                        agent_cond.invisible_persists_on_action = false;
                    } else if (cond.condition_name == "Sanctuary") {
                        agent_cond.sanctuary_active = false;
                        agent_cond.sanctuary_dc     = 0;
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

    // Now that the condition list is stable again, fire any auto-detonations (Delayed Blast Fireball).
    for (const auto& cond : auto_detonate)
        (void)resolveDelayedEffect(bm, cond);
    // ...and any curse kickbacks whose duration ran out (Vistani Curse).
    for (const auto& cond : ended_kickbacks)
        onConditionEnded(bm, cond);

    return removed_ids;
}

std::vector<int> CombatEngine::tickAgentConditionsForCaster(BattleMap& bm, int caster_idx) noexcept
{
    std::vector<int> removed_ids;
    // Deferred curse kickbacks (Vistani) — same iterator-stability rationale as tickAgentConditions.
    std::vector<ActiveAgentCondition> ended_kickbacks;

    for (auto& cond : activeAgentConditions_) {
        // Only tick conditions cast by this caster
        if (cond.caster_idx != caster_idx) continue;

        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);
            if (cond.kickback_dice > 0)
                ended_kickbacks.push_back(cond);

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
                    } else if (cond.condition_name == "Poisoned") {
                        agent_cond.poisoned = false;
                    } else if (cond.condition_name == "Unconscious") {
                        agent_cond.unconscious = false;
                        agent_cond.incapacitated = false;
                        // Keep prone=true per 5e rule: "When this condition ends, you remain Prone"
                    } else if (cond.condition_name == "Sanctuary") {
                        agent_cond.sanctuary_active = false;
                        agent_cond.sanctuary_dc     = 0;
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

    // Container is stable again — fire any curse kickbacks (Vistani Curse).
    for (const auto& cond : ended_kickbacks)
        onConditionEnded(bm, cond);

    return removed_ids;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Delayed / stored effects (general mechanism)
// ─────────────────────────────────────────────────────────────────────────────

namespace {
    // File-local damage-type name for delayed-effect log lines (combat_resources.cpp's elementName
    // lives in its own anonymous namespace and isn't visible here).
    const char* delayDamageName(MagicDamage_t t) noexcept {
        switch (t) {
            case Acid: return "Acid";   case Cold: return "Cold";   case Fire: return "Fire";
            case Force: return "Force"; case Lightning: return "Lightning"; case Necrotic: return "Necrotic";
            case Poison: return "Poison"; case Psychic: return "Psychic"; case Radiant: return "Radiant";
            case Thunder: return "Thunder"; default: return "damage";
        }
    }
}

int CombatEngine::resolveDelayedEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();
    const int t = cond.agent_idx;
    if (t < 0 || t >= static_cast<int>(agents.size())) return 0;

    Agent::Stats ts = bm.getAgentStats(t);
    if (ts.hp_max == 0 && ts.hp_cur == 0) return 0;          // not a real combatant

    const std::string label = cond.delay_label.empty() ? cond.condition_name : cond.delay_label;

    // Roll the stored dice + flat bonus.
    int rolled = cond.delay_flat_bonus;
    for (int i = 0; i < cond.delay_dice; ++i)
        rolled += roll(cond.delay_die_size > 0 ? cond.delay_die_size : 1);

    // The owner's stats drive the multiplier (target-side resistance / vulnerability honored).
    Agent::Stats owner = (cond.caster_idx >= 0 && cond.caster_idx < static_cast<int>(agents.size()))
                       ? bm.getAgentStats(cond.caster_idx) : Agent::Stats{};
    float multiplier = effectiveMagicDamageMult(owner, ts, cond.delay_damage_type, true);
    int dmg = static_cast<int>(static_cast<float>(rolled) * multiplier);

    bool saved = false;
    if (cond.delay_requires_save) {
        int save_d20 = roll(20);
        int save_mod = saveModFor(bm, t, cond.save_ability);
        int save_tot = applyIndomitableMight(bm, t, cond.save_ability, save_d20 + save_mod);
        saved = (save_tot >= cond.save_dc);
        log_("{} {} {} ({} vs DC {})", agentName(bm, t),
             saved ? "saves vs" : "fails the save against", label, save_tot, cond.save_dc);
    }

    // Drop-to-zero variant (2014-style Quivering Palm): a failed save reduces the target to 0 HP
    // outright, ignoring the rolled dice. Otherwise a successful save halves (or negates) the damage.
    if (cond.delay_drop_to_zero && !saved) {
        dmg = ts.hp_cur + ts.temp_hp;
    } else if (saved) {
        dmg = cond.delay_half_on_save ? dmg / 2 : 0;
    }

    log_("{} detonates on {}: {} {} damage",
         label, agentName(bm, t), dmg, delayDamageName(cond.delay_damage_type));

    if (dmg > 0) {
        // Apply temp HP first, then real HP (mirrors elementalBurst / applyHandOfHarmEffect).
        int overflow = std::max(0, dmg - ts.temp_hp);
        ts.temp_hp = std::max(0, ts.temp_hp - dmg);
        ts.hp_cur  = std::clamp(ts.hp_cur - overflow, 0, ts.hp_max);
        bm.setAgentStats(t, ts);

        checkConcentrationOnDamage(bm, t, dmg);
        processDamageTaken(bm, t, dmg);
        if (ts.hp_cur <= 0) {
            Agent::Conditions tc = bm.getAgentConditions(t);
            if (!tc.unconscious && !tc.dead) applyUnconscious(bm, t);
        }
    }
    return dmg;
}

void CombatEngine::onConditionEnded(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();

    // ── Vistani Curse of Vulnerability teardown ─────────────────────────────────
    // Restore the target's prior damage multiplier for the cursed type. Done on EVERY
    // end path (before the kickback gates below) so the vulnerability never lingers.
    if (cond.curse_vuln_type_code >= 0) {
        const int tv = cond.agent_idx;
        if (tv >= 0 && tv < static_cast<int>(agents.size())) {
            Agent::Stats ts = bm.getAgentStats(tv);
            const int code = cond.curse_vuln_type_code;
            if (code >= 100) {
                const int pi = code - 100;
                if (pi >= 0 && pi < NumPhysicalDamage_t)
                    ts.physical_damage_multipliers[static_cast<std::size_t>(pi)] = cond.curse_vuln_prev_mult;
            } else if (code < NumMagicDamage_t) {
                ts.magic_damage_multipliers[static_cast<std::size_t>(code)] = cond.curse_vuln_prev_mult;
            }
            bm.setAgentStats(tv, ts);
        }
    }

    // Only curse-style conditions carry a kickback; everything else ends silently here.
    if (cond.kickback_dice <= 0) return;

    // Decision (LOCKED, Vistani plan): no kickback when the cursed target has died — the Vistana
    // is not punished for killing its victim. The tracking entry may still reach an end-path
    // (e.g. duration expiry) while the target is dead, so gate here rather than at each call site.
    const int t = cond.agent_idx;
    if (t >= 0 && t < static_cast<int>(agents.size())) {
        Agent::Conditions tc = bm.getAgentConditions(t);
        if (tc.dead || bm.getAgentStats(t).hp_cur <= 0) return;
    }

    const int c = cond.caster_idx;
    if (c < 0 || c >= static_cast<int>(agents.size())) return;

    Agent::Stats cs = bm.getAgentStats(c);
    if (cs.hp_max == 0 && cs.hp_cur == 0) return;               // not a real combatant

    // Roll the kickback dice (automatic — no save).
    int rolled = 0;
    for (int i = 0; i < cond.kickback_dice; ++i)
        rolled += roll(cond.kickback_die_size > 0 ? cond.kickback_die_size : 1);

    // Honor the caster's own resistance / vulnerability to the kickback damage type.
    float multiplier = effectiveMagicDamageMult(cs, cs, cond.kickback_damage_type, true);
    int dmg = static_cast<int>(static_cast<float>(rolled) * multiplier);

    log_("Curse rebounds on {}: {} {} damage",
         agentName(bm, c), dmg, delayDamageName(cond.kickback_damage_type));

    if (dmg > 0) {
        // Apply temp HP first, then real HP (mirrors resolveDelayedEffect).
        int overflow = std::max(0, dmg - cs.temp_hp);
        cs.temp_hp = std::max(0, cs.temp_hp - dmg);
        cs.hp_cur  = std::clamp(cs.hp_cur - overflow, 0, cs.hp_max);
        bm.setAgentStats(c, cs);

        checkConcentrationOnDamage(bm, c, dmg);
        processDamageTaken(bm, c, dmg);
        if (cs.hp_cur <= 0) {
            Agent::Conditions cc = bm.getAgentConditions(c);
            if (!cc.unconscious && !cc.dead) applyUnconscious(bm, c);
        }
    }
}

int CombatEngine::triggerDelayedEffect(BattleMap& bm, int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                           [condition_id](const ActiveAgentCondition& c) {
                               return c.condition_id == condition_id && c.delayed_trigger; });
    if (it == activeAgentConditions_.end()) {
        log_("triggerDelayedEffect: no delayed effect with id {}", condition_id);
        return -1;
    }
    // Resolve on a copy, then remove the planted condition (it is spent whether it hits or misses).
    ActiveAgentCondition cond = *it;
    int dmg = resolveDelayedEffect(bm, cond);
    removeAgentCondition(bm, condition_id);
    return dmg;
}

} // namespace rpg
