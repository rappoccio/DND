// ─────────────────────────────────────────────────────────────────────────────
//  combat_resources.cpp  –  CombatEngine resources, rests, class & subclass forms
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The resource half of the action economy: the bonus-action budget, healing /
//  resource spending, long/short rests, per-class activations, and the Druid /
//  subclass transformation forms.
//  Sections:
//    · Bonus-action budget — hasBonusAction, spendBonusAction, resetBonusActions
//    · Resources & healing  — spendResource, healAgent, layOnHands, tickTerrainForTurn
//    · Rests                — applyLongRest, applyShortRest
//    · Class activations    — Rage, Primal Knowledge, Sacred Weapon, Innate Sorcery,
//                             Magical Cunning, Healing Light, Turn Undead, Portent
//    · Subclass forms       — Wild Shape, Starry Form, Wrath of the Sea, Dragon
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <unordered_set>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Bonus-action budget (general action economy)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::hasBonusAction(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;
    return bm.getAgentStats(agent_idx).bonus_actions_remaining > 0;
}

bool CombatEngine::spendBonusAction(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.bonus_actions_remaining <= 0) return false;

    stats.bonus_actions_remaining--;
    bm.setAgentStats(agent_idx, stats);
    log_("{} uses a bonus action ({} remaining)", agentName(bm, agent_idx),
         stats.bonus_actions_remaining);
    return true;
}

void CombatEngine::resetBonusActions(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    stats.bonus_actions_remaining = stats.bonus_actions_max;
    bm.setAgentStats(agent_idx, stats);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Resources & healing
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::spendResource(BattleMap& bm, int idx, const std::string& name, int amount) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    Resource* r = s.getResource(name);
    if (!r || r->current < amount) return false;
    r->spend(amount);
    bm.setAgentStats(idx, s);
    log_("{} spends {} {}.", agentName(bm, idx), amount, name);
    return true;
}

int CombatEngine::healAgent(BattleMap& bm, int idx, int amount) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return 0;   // default-constructed → invalid idx
    s.hp_cur = std::min(s.effectiveMaxHp(), s.hp_cur + amount);  // can't heal past a drained max
    bm.setAgentStats(idx, s);
    reviveOnHeal(bm, idx);   // regaining HP from 0 returns a downed creature to consciousness
    return s.hp_cur;
}

bool CombatEngine::applyOneWithShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& s = pa.agent->getStats();
    if (s.character_class != CharacterClass::Warlock || !s.hasInvocation(8)) return false;

    // Must be standing in an area of Dim Light or Darkness (the light level at the cell —
    // not the obscuration-effect layer, which is for fog/magical-darkness AoEs).
    VisibilityLevel light = bm.getLightLevel(pa.origin);
    if (light != VisibilityLevel::Dim && light != VisibilityLevel::Dark &&
        light != VisibilityLevel::MagicalDark)
        return false;

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = false;  // free Invisibility — ends on the Warlock's next attack/cast
    bm.setAgentConditions(idx, c);
    log_("{}: One with Shadows — gains the Invisible condition", agentName(bm, idx));
    return true;
}

// Soulknife Rogue — Psychic Veil (L13): a Magic action → gain Invisible. Once per Long Rest, or by
// expending 1 Psionic Energy Die. v1: "ends when you deal damage or force a save" is approximated by
// the base Invisibility (ends on the next attack); the force-a-save end-trigger is not tracked.
bool CombatEngine::activatePsychicVeil(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Rogue ||
        s.rogue_subclass != SoulknifePath || s.char_level < 13) return false;
    Resource* pv  = s.getResource("Psychic Veil");
    Resource* ped = s.getResource("Psionic Energy");
    if (pv && pv->current >= 1)        pv->current  -= 1;     // free use first
    else if (ped && ped->current >= 1) ped->current -= 1;     // else 1 Psionic Energy Die
    else return false;
    bm.setAgentStats(idx, s);

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = false;
    bm.setAgentConditions(idx, c);
    log_("{}: Psychic Veil — gains the Invisible condition", agentName(bm, idx));
    return true;
}

// Soulknife Rogue — Psychic Teleportation (L9): a Bonus Action; spend 1 Psionic Energy Die, roll it,
// and teleport up to (10 × roll) feet to an unoccupied cell. Grid distance is Chebyshev × 5 ft. The
// die is spent only on a successful (in-range, legal) teleport.
bool CombatEngine::psychicTeleportation(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Rogue ||
        s.rogue_subclass != SoulknifePath || s.char_level < 9) return false;
    Resource* ped = s.getResource("Psionic Energy");
    if (!ped || ped->current < 1) return false;

    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    const int die    = roll(s.psionic_die_size);
    const int max_ft = 10 * die;
    if (dcells * 5 > max_ft) {
        log_("{}: Psychic Teleportation rolled {} ({} ft) — destination too far ({} ft)",
             agentName(bm, idx), die, max_ft, dcells * 5);
        return false;                                          // die not spent (bad pick)
    }
    if (!teleportAgent(bm, idx, target_col, target_row)) return false;
    ped->current -= 1;
    bm.setAgentStats(idx, s);
    log_("{}: Psychic Teleportation — teleports {} ft (rolled {} → up to {} ft)",
         agentName(bm, idx), dcells * 5, die, max_ft);
    return true;
}

int CombatEngine::layOnHands(BattleMap& bm, int caster_idx, int target_idx, int amount) noexcept
{
    // Fetch caster's Lay on Hands pool
    Agent::Stats caster_stats = bm.getAgentStats(caster_idx);
    if (caster_stats.hp_max == 0 && caster_stats.hp_cur == 0) return -1;  // invalid caster idx

    Resource* pool = caster_stats.getResource("Lay on Hands");
    if (!pool) return -1;  // No Lay on Hands resource
    if (pool->current <= 0) return -1;  // Pool depleted

    // Fetch target stats
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    if (tgt_stats.hp_max == 0 && tgt_stats.hp_cur == 0) return -1;  // invalid target idx

    // Clamp amount to: min(pool remaining, target HP deficit)
    int hp_deficit = tgt_stats.effectiveMaxHp() - tgt_stats.hp_cur;
    int clamped = std::min(amount, std::min(pool->current, hp_deficit));

    if (clamped <= 0) return 0;  // Nothing to heal

    // Apply healing to target
    healAgent(bm, target_idx, clamped);

    // Decrement pool
    pool->current = std::max(0, pool->current - clamped);
    caster_stats.resources["Lay on Hands"] = *pool;
    bm.setAgentStats(caster_idx, caster_stats);

    return clamped;
}

bool CombatEngine::spendLuckForAdvantage(BattleMap& bm, int idx)
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return false;  // invalid idx
    if (!s.hasFeat("Lucky") || s.luck_points <= 0) return false;
    s.luck_points -= 1;
    bm.setAgentStats(idx, s);
    grantPendingAdvantage(true);   // consumed by the agent's next d20 roll
    log_("{} spends a Luck Point for Advantage ({} remaining)",
         agentName(bm, idx), s.luck_points);
    return true;
}

TerrainTickResult CombatEngine::tickTerrainForTurn(BattleMap& bm, int agent_idx)
{
    TerrainTickResult result;

    // Snapshot which of this source's terrain effects are concentration-bound,
    // so we can detect a concentration spell ending by natural expiry.
    std::unordered_set<int> concentration_ids;
    for (const auto& eff : bm.activeTerrainEffects()) {
        if (eff.source_agent_idx == agent_idx && eff.requires_concentration)
            concentration_ids.insert(eff.id);
    }

    result.expired_terrain_ids = bm.tickTerrainEffects(agent_idx);

    // If a concentration terrain expired, the caster's concentration ends —
    // drop it (and cascade removal of the spell's other effects/conditions).
    for (int id : result.expired_terrain_ids) {
        if (concentration_ids.count(id)) {
            result.concentration = dropConcentration(bm, agent_idx);
            break;
        }
    }

    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Rests
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyLongRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);

        // Restore spell slots and all resources
        stats.restore_resources_long_rest();

        // Long rest restores all Hit Points and clears any max-HP reduction (vampiric drain, etc.).
        // The dead stay dead (not revived).
        stats.available_hit_points = 0;
        Agent::Conditions rest_cond = bm.getAgentConditions(agent_idx);
        if (!rest_cond.dead) {
            stats.hp_cur = stats.hp_max;
            // If the agent was downed but survived the rest, clear the downed /
            // death-save state so they aren't left flagged unconscious at full HP.
            if (rest_cond.unconscious) {
                rest_cond.unconscious        = false;
                rest_cond.incapacitated      = false;
                rest_cond.prone              = false;
                rest_cond.stabilized         = false;
                rest_cond.death_save_successes = 0;
                rest_cond.death_save_failures  = 0;
                bm.setAgentConditions(agent_idx, rest_cond);
            }
        }

        // Initialize Arcane Ward for Abjurers at L3+
        if (stats.character_class == Wizard && stats.wizard_subclass == AbjurerPath && stats.char_level >= 3) {
            stats.temp_hp = stats.char_level;
        }

        // TASK E: Celestial Resilience (Celestial L10): temp HP on long rest
        if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        }

        // Save stats back (includes resource restoration)
        bm.setAgentStats(agent_idx, stats);

        // Regenerate Portent Dice for Diviners
        if (stats.character_class == Wizard && stats.wizard_subclass == DivinierPath) {
            regeneratePortentDice(bm, agent_idx);
        }

        log_("{} completed long rest: resources restored, Portent Dice regenerated", agentName(bm, agent_idx));
    }
}

void CombatEngine::applyShortRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);
        stats.restore_resources_short_rest();  // Warlock pact slots, Monk Ki, etc.

        // TASK E: Celestial Resilience (Celestial L10): temp HP on short rest
        if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        }

        bm.setAgentStats(agent_idx, stats);
        log_("{} completed short rest: short-rest resources restored", agentName(bm, agent_idx));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Class activations
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::activateRage(BattleMap& bm, int idx)
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    Agent::Stats stats = bm.getAgentStats(idx);

    // Set raging flag
    cond.raging = true;

    // Apply BPS (Bludgeoning, Piercing, Slashing) resistance (0.5x multiplier)
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Bludgeoning)] = 0.5f;
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Piercing)] = 0.5f;
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Slashing)] = 0.5f;

    // Wild Heart Bear Form: extra resistance to non-Force/Necrotic/Psychic/Radiant damage
    // (Bear grants resistance to all damage except Force, Necrotic, Psychic, Radiant)
    if (stats.barbarian_subclass == WildHeartPath && stats.wild_heart_rage_choice == BearForm) {
        // Bludgeoning, Piercing, Slashing already at 0.5x from Rage
        // Add resistance to Acid, Cold, Fire, Lightning, Poison, Thunder (0.5x)
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Acid)] = 0.5f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Cold)] = 0.5f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Fire)] = 0.5f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Lightning)] = 0.5f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Poison)] = 0.5f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Thunder)] = 0.5f;
        log_("{} activates Bear Form: resistance to all non-Force/Necrotic/Psychic/Radiant damage", agentName(bm, idx));
    }

    // World Tree Vitality of the Tree: grant temp HP = Barbarian level on Rage activation
    if (stats.barbarian_subclass == WorldTreePath) {
        int vitality_temp_hp = stats.char_level;
        grantTempHp(stats, vitality_temp_hp);  // entry THP is NOT rage-tagged: it persists past Rage end
        log_("{} grants Vitality: {} temp HP", agentName(bm, idx), vitality_temp_hp);
    }

    // Berserker L6: Mindless Rage - clear Charmed and Frightened conditions
    if (stats.barbarian_subclass == BerserkerPath && stats.char_level >= 6) {
        cond.charmed = false;
        cond.frightened = false;
        log_("{} Mindless Rage: charmed/frightened cleared", agentName(bm, idx));
    }

    // Wild Heart L6: Aspect of the Wilds - apply aspect bonuses
    if (stats.barbarian_subclass == WildHeartPath && stats.char_level >= 6) {
        if (stats.wild_heart_aspect == OwlAspect) {
            stats.darkvision_range = std::max(stats.darkvision_range, 60);
            log_("{} Owl Aspect: darkvision 60 ft", agentName(bm, idx));
        } else if (stats.wild_heart_aspect == SalmonAspect) {
            stats.speed_swim = std::max(stats.speed_swim, stats.speed_walk);
            log_("{} Salmon Aspect: swim speed = walk speed ({})", agentName(bm, idx), stats.speed_walk);
        }
    }

    // Reset Zealot Fanatical Focus flag on Rage activation (can use once per Rage)
    if (stats.barbarian_subclass == ZealotPath && stats.char_level >= 6) {
        cond.fanatical_focus_used = false;
        log_("{} Fanatical Focus: ready for use this Rage", agentName(bm, idx));
    }

    // Spend one use of Rage resource
    if (stats.resources.find("Rage") != stats.resources.end()) {
        Resource& rage = stats.resources.at("Rage");
        if (rage.current > 0) {
            rage.current--;
            rage.duration_remaining = rage.duration;
        }
    }

    // Instinctive Pounce (L7): grant up to half speed of extra movement THIS turn
    if (stats.char_level >= 7) {
        walkRemaining_[idx] += stats.speed_walk / 2;
        log_("{} Instinctive Pounce: +{} ft movement", agentName(bm, idx), stats.speed_walk / 2);
    }

    bm.setAgentConditions(idx, cond);
    bm.setAgentStats(idx, stats);
    log_("{} activates Rage: raging=true, BPS resistance (0.5x)", agentName(bm, idx));
}

void CombatEngine::extendRage(BattleMap& bm, int idx)
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Reset Rage duration
    if (stats.resources.find("Rage") != stats.resources.end()) {
        Resource& rage = stats.resources.at("Rage");
        rage.duration_remaining = rage.duration;
    }

    bm.setAgentStats(idx, stats);
    log_("{} extends Rage: duration reset", agentName(bm, idx));
}

void CombatEngine::endRage(BattleMap& bm, int idx)
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    Agent::Stats stats = bm.getAgentStats(idx);

    // Clear raging flag
    cond.raging = false;
    cond.reckless_attack = false;

    // Reset Relentless Rage DC to base (10) when rage ends
    stats.relentless_rage_dc = 10;

    // Restore normal damage multipliers for BPS (1.0x)
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Bludgeoning)] = 1.0f;
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Piercing)] = 1.0f;
    stats.physical_damage_multipliers[static_cast<std::size_t>(PhysicalDamage_t::Slashing)] = 1.0f;

    // Wild Heart Bear Form: restore magic damage multipliers
    if (stats.barbarian_subclass == WildHeartPath && stats.wild_heart_rage_choice == BearForm) {
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Acid)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Cold)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Fire)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Lightning)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Poison)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Thunder)] = 1.0f;
    }

    // Wild Heart L6 Aspect: restore swim speed / darkvision on Rage end
    if (stats.barbarian_subclass == WildHeartPath && stats.char_level >= 6) {
        if (stats.wild_heart_aspect == SalmonAspect) {
            stats.speed_swim = 0;  // Reset swim speed (Salmon aspect only during Rage)
        }
        if (stats.wild_heart_aspect == OwlAspect) {
            stats.darkvision_range = 0;  // Reset darkvision (Owl aspect only during Rage)
        }
    }

    // Clear Rage duration
    if (stats.resources.find("Rage") != stats.resources.end()) {
        Resource& rage = stats.resources.at("Rage");
        rage.duration_remaining = 0;
    }

    bm.setAgentConditions(idx, cond);
    bm.setAgentStats(idx, stats);

    // World Tree "Vitality of the Tree": temp HP granted by THIS Barbarian's Rage vanishes when the
    // Rage ends. 5e temp HP never stacks, so any creature whose current temp_hp is tagged with this
    // Barbarian's index loses exactly that temp HP. (The entry temp HP grant is left untagged on
    // purpose — it persists as normal temp HP.)
    for (std::size_t i = 0; i < agents.size(); ++i) {
        Agent::Stats ts = bm.getAgentStats(static_cast<int>(i));
        if (ts.rage_thp_source_idx == idx) {
            ts.temp_hp = 0;
            ts.rage_thp_source_idx = -1;
            bm.setAgentStats(static_cast<int>(i), ts);
        }
    }

    log_("{} ends Rage: raging=false, BPS resistance cleared, reckless_attack cleared", agentName(bm, idx));
}

bool CombatEngine::useIntimidatingPresence(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);

    // Gate on Berserker L10+
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != BerserkerPath ||
        stats.char_level < 10) {
        return false;
    }

    // Check bonus action availability
    if (!hasBonusAction(bm, idx)) {
        return false;
    }

    // Check resource availability (uses per long rest, or spend Rage)
    Resource* ip_resource = stats.getResource("Intimidating Presence");
    bool has_ip_uses = ip_resource && ip_resource->current > 0;
    bool can_spend_rage = stats.resources.count("Rage") && stats.resources.at("Rage").current > 0;

    if (!has_ip_uses && !can_spend_rage) {
        return false;
    }

    const PlacedAgent& barbarian_pa = agents[static_cast<std::size_t>(idx)];
    const int origin_col = barbarian_pa.origin.col;
    const int origin_row = barbarian_pa.origin.row;
    const int radius_ft = 30;

    // Calculate save DC: 8 + STR mod + PB
    int str_mod = (stats.str - 10) / 2;
    if (stats.str < 10 && (stats.str - 10) % 2 != 0) --str_mod;
    const int save_dc = 8 + str_mod + stats.prof_bonus;

    // Scan all creatures within 30 ft; skip self and skip allies
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int target_idx = static_cast<int>(i);
        if (target_idx == idx) continue;  // Skip self

        const PlacedAgent& target_pa = agents[i];
        // Euclidean emanation radius, matching Spirit Guardians (resolveAoeTargets, Spell::Sphere).
        const float dx = static_cast<float>(target_pa.origin.col - origin_col);
        const float dy = static_cast<float>(target_pa.origin.row - origin_row);
        const float dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0f;

        if (dist_ft > static_cast<float>(radius_ft)) continue;  // Out of range

        if (areAllies(bm, idx, target_idx)) continue;  // Skip allies (enemies only)

        // Roll WIS save for the target
        const int wis_save_mod = saveModFor(bm, target_idx, SaveWis);

        const int save_d20 = roll(20);
        const int save_total = save_d20 + wis_save_mod;
        const bool failed = save_total < save_dc;

        log_("{} makes a WIS save vs Intimidating Presence (DC {}): {} + {} = {} ({})",
             agentName(bm, target_idx), save_dc, save_d20, wis_save_mod, save_total,
             failed ? "FAILED" : "PASSED");

        if (failed) {
            // Apply Frightened until end of Barbarian's next turn. addAgentCondition routes
            // through applyFrightened internally (which also honors Aura of Courage immunity),
            // so we do NOT call applyFrightened separately here.
            ActiveAgentCondition aac{};
            aac.agent_idx = target_idx;
            aac.condition_name = "Frightened";
            aac.caster_idx = idx;
            aac.turns_remaining = 2;  // until end of next turn (turn starts, runs, then starts next turn)
            (void)addAgentCondition(bm, aac);
        }
    }

    // Spend resource (IP use or Rage use)
    if (has_ip_uses) {
        ip_resource->spend(1);
        stats.resources["Intimidating Presence"] = *ip_resource;
    } else {
        Resource& rage = stats.resources.at("Rage");
        rage.current--;
    }

    // Persist the resource spend, THEN consume the bonus action. spendBonusAction re-reads
    // fresh stats and writes them back, so it must run AFTER setAgentStats or it would be
    // clobbered (and the bonus action effectively refunded).
    bm.setAgentStats(idx, stats);
    spendBonusAction(bm, idx);

    log_("{} uses Intimidating Presence (save DC {})", agentName(bm, idx), save_dc);
    return true;
}

bool CombatEngine::useZealousPresence(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Gate on Zealot L10+
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != ZealotPath ||
        stats.char_level < 10) {
        return false;
    }

    // Check bonus action availability
    if (!hasBonusAction(bm, idx)) {
        return false;
    }

    // Check resource availability (1 use per long rest, or spend Rage)
    Resource* zp_resource = stats.getResource("Zealous Presence");
    bool has_zp_uses = zp_resource && zp_resource->current > 0;
    bool can_spend_rage = stats.resources.count("Rage") && stats.resources.at("Rage").current > 0;

    if (!has_zp_uses && !can_spend_rage) {
        return false;
    }

    const PlacedAgent& zealot_pa = agents[static_cast<std::size_t>(idx)];
    const int origin_col = zealot_pa.origin.col;
    const int origin_row = zealot_pa.origin.row;
    const int radius_ft = 60;
    const int max_targets = 10;

    int targets_buffed = 0;

    // Scan all creatures within 60 ft; select ALLIES (up to 10, including self)
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int target_idx = static_cast<int>(i);

        // Allow self and allies only
        if (target_idx != idx && !areAllies(bm, idx, target_idx)) continue;

        const PlacedAgent& target_pa = agents[i];
        // Euclidean emanation radius, matching Spirit Guardians (resolveAoeTargets, Spell::Sphere).
        const float dx = static_cast<float>(target_pa.origin.col - origin_col);
        const float dy = static_cast<float>(target_pa.origin.row - origin_row);
        const float dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0f;

        if (dist_ft > static_cast<float>(radius_ft)) continue;  // Out of range

        if (targets_buffed >= max_targets) break;  // Hit cap

        // Grant zealous_blessing: will be read in determineAdvantage (attacks) and rollSpellSave (saves)
        Agent::Conditions target_cond = bm.getAgentConditions(target_idx);
        target_cond.zealous_blessing = true;
        target_cond.zealous_blessing_by = idx;  // expires as this Zealot's next turn begins (beginTurn sweep)
        bm.setAgentConditions(target_idx, target_cond);
        targets_buffed++;

        log_("{} gains Zealous Presence: Advantage on attack rolls and saves until start of {}'s next turn",
             agentName(bm, target_idx), agentName(bm, idx));
    }

    // Spend resource (ZP use or Rage use)
    if (has_zp_uses) {
        zp_resource->spend(1);
        stats.resources["Zealous Presence"] = *zp_resource;
    } else {
        Resource& rage = stats.resources.at("Rage");
        rage.current--;
    }

    // Persist the resource spend, THEN consume the bonus action. spendBonusAction re-reads
    // fresh stats and writes them back, so it must run AFTER setAgentStats or it would be
    // clobbered (and the bonus action effectively refunded).
    bm.setAgentStats(idx, stats);
    spendBonusAction(bm, idx);

    log_("{} uses Zealous Presence: {} creature(s) gain Advantage on attacks and saves",
         agentName(bm, idx), targets_buffed);
    return true;
}

bool CombatEngine::canUsePrimalKnowledge(const BattleMap& bm, int idx, const std::string& skill_name) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    const Agent::Conditions& cond = pa.agent->getConditions();

    // Primal Knowledge (L3): Acrobatics and Stealth can use STR instead of their normal ability while Raging
    if (stats.character_class != CharacterClass::Barbarian || stats.char_level < 3)
        return false;

    if (!cond.raging)
        return false;

    // Only Acrobatics and Stealth are relevant for combat
    if (skill_name == "Acrobatics" || skill_name == "Stealth")
        return true;

    return false;
}

int CombatEngine::activateSacredWeapon(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return -1;  // invalid idx

    // Requires a Paladin who has taken the Oath of Devotion.
    if (stats.character_class != CharacterClass::Paladin ||
        stats.paladin_oath != OathOfDevotionPath) return -1;

    // Needs an available Channel Oath use.
    Resource* co = stats.getResource("Channel Oath");
    if (!co || co->current <= 0) return -1;

    // Bonus = CHA modifier (minimum +1), floored correctly for odd negative scores.
    int cha_mod = (stats.cha - 10) / 2;
    if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --cha_mod;
    int bonus = std::max(1, cha_mod);

    // Spend 1 Channel Oath use, then re-fetch so we keep that decrement.
    spendResource(bm, idx, "Channel Oath", 1);
    stats = bm.getAgentStats(idx);
    stats.sacred_weapon_bonus = bonus;
    stats.sacred_weapon_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Sacred Weapon: +{} to weapon attack rolls for 1 minute",
         agentName(bm, idx), bonus);
    return bonus;
}

bool CombatEngine::activateCoronaOfLight(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return false;  // invalid idx

    // Requires a Light Domain Cleric of level 17+.
    if (stats.character_class != CharacterClass::Cleric ||
        stats.cleric_subclass != LightDomain || stats.char_level < 17) return false;

    stats.corona_of_light_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Corona of Light: enemies within 60 ft have Disadvantage on saves vs its "
         "Fire/Radiant spells for 1 minute", agentName(bm, idx));
    return true;
}

bool CombatEngine::activateInnateSorcery(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return false;

    // Requires an available Innate Sorcery use (Bonus Action; 2 uses per long rest).
    Resource* innate = stats.getResource("Innate Sorcery");
    if (!innate || innate->current <= 0) return false;

    innate->spend(1);
    stats.innate_sorcery_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Innate Sorcery: +1 spell save DC and advantage on spell attacks for 1 minute",
         agentName(bm, idx));
    return true;
}

bool CombatEngine::useMagicalCunning(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.character_class != Warlock) return false;

    Resource* mc = stats.getResource("Magical Cunning");
    if (!mc || mc->current <= 0) return false;  // not available / already used

    const int lvl = stats.pact_slot_level();
    if (lvl < 1) return false;
    const std::size_t i = static_cast<std::size_t>(lvl - 1);
    const int maxs = stats.spell_slots_max[i];
    const int expended = maxs - stats.spell_slots_remaining[i];
    if (expended <= 0) return false;  // nothing to recover

    // ceil(max/2), or all expended at L20 (Eldritch Master).
    const int recover = (stats.char_level >= 20) ? expended
                                                 : std::min(expended, (maxs + 1) / 2);
    stats.spell_slots_remaining[i] += recover;
    mc->spend();
    bm.setAgentStats(agent_idx, stats);
    log_("{}: Magical Cunning recovers {} pact slot(s).", agentName(bm, agent_idx), recover);

    // TASK E: Celestial Resilience (Celestial L10): temp HP on Magical Cunning use
    if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
        int chaMod = (stats.cha - 10) / 2;
        if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
        stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        bm.setAgentStats(agent_idx, stats);
        log_("{}: Celestial Resilience grants {} temp HP", agentName(bm, agent_idx), stats.char_level + chaMod);
    }

    return true;
}

int CombatEngine::useHealingLight(BattleMap& bm, int healer_idx, int target_idx, int num_dice)
{
    auto agents = bm.placedAgents();
    if (healer_idx < 0 || healer_idx >= static_cast<int>(agents.size())) return 0;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats healer_stats = bm.getAgentStats(healer_idx);
    if (healer_stats.character_class != CharacterClass::Warlock || healer_stats.warlock_subclass != CelestialPath ||
        healer_stats.char_level < 3) {
        return 0;
    }

    Resource* hl = healer_stats.getResource("Healing Light");
    if (!hl || hl->current <= 0) return 0;

    int chaMod = (healer_stats.cha - 10) / 2;
    if (healer_stats.cha < 10 && (healer_stats.cha - 10) % 2 != 0) --chaMod;
    int max_dice = std::max(1, chaMod);

    num_dice = std::min(num_dice, std::min(hl->current, max_dice));
    if (num_dice <= 0) return 0;

    int total_healing = 0;
    for (int i = 0; i < num_dice; ++i) {
        total_healing += roll(6);
    }

    hl->spend(num_dice);  // hl points into healer_stats.resources, so this mutates it in place
    bm.setAgentStats(healer_idx, healer_stats);

    Agent::Stats target_stats = bm.getAgentStats(target_idx);
    int healed = std::min(total_healing, target_stats.effectiveMaxHp() - target_stats.hp_cur);
    target_stats.hp_cur = std::min(target_stats.effectiveMaxHp(), target_stats.hp_cur + total_healing);
    bm.setAgentStats(target_idx, target_stats);
    reviveOnHeal(bm, target_idx);   // a healed downed ally rejoins initiative

    log_("{}: Healing Light: {} d6 = {} healing to {}", agentName(bm, healer_idx), num_dice, total_healing, agentName(bm, target_idx));
    return healed;
}

TurnUndeadResult CombatEngine::useTurnUndead(BattleMap& bm, int caster_idx)
{
    TurnUndeadResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return result;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.character_class != CharacterClass::Cleric || caster.char_level < 2) return result;

    Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return result;

    result.valid   = true;
    result.save_dc = spellSaveDcFromAbility(caster, SaveWis);

    int wisMod = (caster.wis - 10) / 2;
    if (caster.wis < 10 && (caster.wis - 10) % 2 != 0) --wisMod;

    // Sear Undead (L5+): roll WIS-mod d8 (minimum 1d8) ONCE; each failed undead takes that total.
    int sear_total = 0;
    if (caster.char_level >= 5) {
        int sear_dice = std::max(1, wisMod);
        for (int i = 0; i < sear_dice; ++i) sear_total += roll(8);
        result.sear_damage = sear_total;
    }

    // Expend one Channel Divinity use (cd points into caster.resources; persist below).
    cd->spend(1);
    bm.setAgentStats(caster_idx, caster);
    log_("{} uses Turn Undead (DC {})", agentName(bm, caster_idx), result.save_dc);

    const Cell c_origin = agents[static_cast<std::size_t>(caster_idx)].origin;

    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == caster_idx) continue;
        Agent::Stats tgt = bm.getAgentStats(i);
        if (!tgt.is_undead) continue;

        // Within 30 ft (Euclidean cell distance × 5 ft), matching Sphere targeting.
        const Cell o = agents[static_cast<std::size_t>(i)].origin;
        const double dx = o.col - c_origin.col, dy = o.row - c_origin.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) continue;

        int mod = (tgt.wis - 10) / 2;
        if (tgt.wis < 10 && (tgt.wis - 10) % 2 != 0) --mod;
        if (tgt.save_prof_wis) mod += tgt.prof_bonus;
        const int save_total = roll(20, mod);

        if (save_total >= result.save_dc) {
            result.resisted.push_back(i);
            log_("Turn Undead: {} resists ({} vs DC {})", agentName(bm, i), save_total, result.save_dc);
            continue;
        }

        // Sear damage is dealt BEFORE the conditions are applied, so the on-damage "ends" rule
        // doesn't immediately cancel the Frightened/Incapacitated we're about to add.
        if (sear_total > 0) {
            damageAgent(bm, i, sear_total);
            checkConcentrationOnDamage(bm, i, sear_total);
            processDamageTaken(bm, i, sear_total);
        }

        // Frightened + Incapacitated for 1 minute; ends early if the undead takes damage.
        for (const char* cname : {"Frightened", "Incapacitated"}) {
            ActiveAgentCondition cond;
            cond.agent_idx        = i;
            cond.caster_idx       = caster_idx;   // fear source (used by Frightened movement rule)
            cond.condition_name   = cname;
            cond.save_ability     = SaveWis;
            cond.save_dc          = result.save_dc;
            cond.save_repeat_turns = -1;          // no per-turn save; ends on damage / after 1 min
            cond.turns_remaining  = 10;           // 1 minute
            cond.on_damage        = OnDamage_t::End;
            cond.next_save_turn   = 0;
            (void)addAgentCondition(bm, cond);
        }
        result.turned.push_back(i);
        log_("Turn Undead: {} is Turned ({} vs DC {})", agentName(bm, i), save_total, result.save_dc);
    }

    return result;
}

bool CombatEngine::usePortentDie(BattleMap& bm, int agent_idx, int die_index, int current_round) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard with Portent Dice resource
    if (stats.character_class != Wizard || stats.wizard_subclass != DivinierPath) {
        log_("{} is not a Diviner Wizard", agentName(bm, agent_idx));
        return false;
    }

    auto* portent_res = stats.getResource("Portent Dice");
    if (!portent_res) {
        log_("{} has no Portent Dice resource", agentName(bm, agent_idx));
        return false;
    }

    // Check if this agent already used a portent this round
    auto it = agent_portent_round_used_.find(agent_idx);
    if (it != agent_portent_round_used_.end() && it->second == current_round) {
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
    pending_portent_die_ = die_value;

    // Track that this agent used a portent in this round
    agent_portent_round_used_[agent_idx] = current_round;

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} using Portent Die: value={}, remaining={}/{}",
         agentName(bm, agent_idx), die_value, portent_res ? portent_res->current : 0,
         portent_res ? portent_res->max : 0);

    return true;
}

bool CombatEngine::grantBardicDie(BattleMap& bm, int agent_idx, int d) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    // RAW: a creature holds only one Bardic Inspiration die at a time; overwrite.
    stats.bardic_inspiration_die = d;
    bm.setAgentStats(agent_idx, stats);

    log_("{} gains a Bardic Inspiration d{}", agentName(bm, agent_idx), d);
    return true;
}

int CombatEngine::useBardicDie(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);            // roll the held die (1..d)
    pending_roll_bonus_ = value;    // fold into the agent's NEXT d20 Test
    stats.bardic_inspiration_die = 0;  // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next D20 Test",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::useBardicDieForDamage(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);                   // roll the held die (1..d)
    pending_damage_bonus_ = value;         // fold into the attacker's NEXT weapon damage roll
    stats.bardic_inspiration_die = 0;     // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next weapon damage roll",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::bardRegainInspirationFromSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.character_class != CharacterClass::Bard || stats.char_level < 5) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;  // no slot of that level to spend

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current >= bi->max) return -1;          // nothing to regain → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    bi->gain(1);
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends a level-{} slot (Font of Inspiration): Bardic Inspiration now {}/{}",
         agentName(bm, agent_idx), slot_level, bi->current, bi->max);
    return bi->current;
}

bool CombatEngine::activateMantleOfMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 6) return false;

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left → don't open the window

    // Spend the use (spendResource re-reads/writes stats internally).
    spendResource(bm, bard_idx, "Mantle of Majesty", 1);

    // The "unearthly appearance" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears mantle_majesty_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.mantle_majesty_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Mantle of Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on an unearthly appearance (Mantle of Majesty): may cast Command as a Bonus "
         "Action with no slot for 1 minute", agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreMantleOfMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 6) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Mantle of Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::activateUnbreakableMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 14) return false;

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left

    // Spend the use
    spendResource(bm, bard_idx, "Unbreakable Majesty", 1);

    // The "majestic presence" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears majestic_presence_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.majestic_presence_turns = 10;  // 1 minute = 10 rounds
    stats.majesty_checked_this_turn = false;  // fresh turn, ready to check
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Unbreakable Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on a majestic presence (Unbreakable Majesty): melee attacks against {} trigger "
         "Psychic damage and a CHA save for 1 minute", agentName(bm, bard_idx), agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreUnbreakableMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 14) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Unbreakable Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::bardBeguilingMagic(BattleMap& bm, int bard_idx, int target_idx,
                                      bool use_frightened) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (bard_idx < 0 || bard_idx >= n || target_idx < 0 || target_idx >= n || target_idx == bard_idx)
        return false;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.character_class != CharacterClass::Bard ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.char_level < 3) {
        log_("{} cannot use Beguiling Magic (not a L3+ College of Glamour Bard)", agentName(bm, bard_idx));
        return false;
    }
    const Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current <= 0) {
        log_("{} has no Beguiling Magic use available", agentName(bm, bard_idx));
        return false;
    }
    // Must be a creature the bard can see within 60 ft (the GUI also gates LOS/perception).
    const int dist_ft = footprintDistance(agents[bard_idx].origin, agents[bard_idx].agent->getSize(),
                                          agents[target_idx].origin, agents[target_idx].agent->getSize()) * 5;
    if (dist_ft > 60) {
        log_("Beguiling Magic: {} is more than 60 ft away", agentName(bm, target_idx));
        return false;
    }

    // Using the benefit spends the use whether or not the target ultimately fails its save.
    spendResource(bm, bard_idx, "Beguiling Magic", 1);

    const char* cond_name = use_frightened ? "Frightened" : "Charmed";
    const int   dc        = spellSaveDc(bs);
    const int   save_mod  = saveModFor(bm, target_idx, SaveWis);
    const int   save_roll = roll(20, save_mod);

    if (save_roll >= dc) {
        log_("{} resists Beguiling Magic (WIS save {} vs DC {})", agentName(bm, target_idx), save_roll, dc);
        return true;
    }
    // Frightened can be refused outright by Aura of Courage — the use is still spent.
    if (use_frightened && hasAuraOfCourage(bm, target_idx)) {
        log_("{} can't be Frightened (Aura of Courage) — Beguiling Magic has no effect",
             agentName(bm, target_idx));
        return true;
    }

    ActiveAgentCondition cond;
    cond.agent_idx        = target_idx;
    cond.caster_idx       = bard_idx;
    cond.condition_name   = cond_name;
    cond.turns_remaining  = 10;            // 1 minute = 10 rounds (ticked on the bard's turns)
    cond.save_ability     = SaveWis;
    cond.save_dc          = dc;
    cond.save_repeat_turns = 1;            // repeats at the start of each of the target's turns
    cond.next_save_turn   = 0;
    (void)addAgentCondition(bm, cond);
    log_("{} fails vs Beguiling Magic and is {} for 1 minute (WIS save {} vs DC {})",
         agentName(bm, target_idx), cond_name, save_roll, dc);
    return true;
}

int CombatEngine::bardRestoreBeguilingMagic(BattleMap& bm, int bard_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.character_class != CharacterClass::Bard ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.char_level < 3) return -1;

    Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current >= beg->max) return -1;   // already full → don't waste an Inspiration
    const Resource* bi = bs.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) return -1;            // no Bardic Inspiration use to spend

    spendResource(bm, bard_idx, "Bardic Inspiration", 1);
    // Re-read stats: spendResource mutated them; gain on a fresh copy and write back.
    bs = bm.getAgentStats(bard_idx);
    beg = bs.getResource("Beguiling Magic");
    if (!beg) return -1;
    beg->gain(1);
    bm.setAgentStats(bard_idx, bs);

    log_("{} expends a Bardic Inspiration use to restore Beguiling Magic: now {}/{}",
         agentName(bm, bard_idx), beg->current, beg->max);
    return beg->current;
}

void CombatEngine::applySuperiorInspiration(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    for (int i = 0; i < n; ++i) {
        Agent::Stats stats = bm.getAgentStats(i);
        if (stats.character_class != CharacterClass::Bard || stats.char_level < 18) continue;

        Resource* bi = stats.getResource("Bardic Inspiration");
        if (!bi || bi->current >= 2) continue;

        bi->current = std::min(bi->max, 2);  // regain up to 2 (never above the resource max)
        bm.setAgentStats(i, stats);
        log_("{} regains Bardic Inspiration to {} (Superior Inspiration)",
             agentName(bm, i), bi->current);
    }
}

int CombatEngine::bardCuttingWords(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != BardCollege::LorePath || stats.char_level < 3) {
        log_("{} cannot use Cutting Words (not a L3+ College of Lore Bard)", agentName(bm, bard_idx));
        return 0;
    }

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) {
        log_("{} has no Bardic Inspiration use for Cutting Words", agentName(bm, bard_idx));
        return 0;
    }

    bi->current -= 1;
    int value = roll(stats.bardic_inspiration_die_size);
    pending_roll_bonus_ = -value;   // SUBTRACT from the next D20 Test (the target's roll)
    bm.setAgentStats(bard_idx, stats);

    log_("{} uses Cutting Words: -{} to the next D20 Test ({} Bardic Inspiration left)",
         agentName(bm, bard_idx), value, bi->current);
    return value;
}

void CombatEngine::regeneratePortentDice(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard
    if (stats.character_class != Wizard || stats.wizard_subclass != DivinierPath) {
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
//  Subclass forms
// ─────────────────────────────────────────────────────────────────────────────

// ── Wild Shape Activation / Deactivation ──────────────────────────────────
bool CombatEngine::activateWildShape(BattleMap& bm, int idx, const std::string& beast_name, std::array<Weapon,3> weapons, const std::string& beast_forms_path) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

  Agent::Stats stats = bm.getAgentStats(idx);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) return false;

  // Load beast form from JSON to get stats
  nlohmann::json beasts;
  std::vector<std::string> paths;
  if (!beast_forms_path.empty()) paths.push_back(beast_forms_path);
  paths.insert(paths.end(), {"beast_forms.json", "./beast_forms.json", "../gui/beast_forms.json"});

  bool loaded = false;
  for (const auto& path : paths) {
    try {
      std::ifstream f(path);
      if (f.is_open()) {
        f >> beasts;
        loaded = true;
        break;
      }
    } catch (...) {}
  }
  if (!loaded) return false;

  // Find beast
  nlohmann::json beast_data;
  for (const auto& b : beasts) {
    if (b.value("name", "") == beast_name) {
      beast_data = b;
      break;
    }
  }
  if (beast_data.empty()) return false;

  // Save original weapons, stats, and ability scores
  stats.wild_shape_saved_weapons = getAgentWeapons(bm, idx);
  stats.wild_shape_saved_ac = stats.base_ac;
  stats.wild_shape_saved_str = stats.str;
  stats.wild_shape_saved_dex = stats.dex;
  stats.wild_shape_saved_con = stats.con;

  stats.str = beast_data.value("str", 10);
  stats.dex = beast_data.value("dex", 10);
  stats.con = beast_data.value("con", 10);
  stats.base_ac = beast_data.value("ac", 10);
  if (stats.druid_circle == CircleOfMoon) {
    stats.base_ac = std::max(stats.base_ac, 13 + (stats.wis - 10) / 2);
  }

  int temp_hp = stats.char_level * (stats.druid_circle == CircleOfMoon ? 3 : 1);
  stats.temp_hp += temp_hp;
  stats.rage_thp_source_idx = -1;  // Wild Shape THP is not rage-sourced (don't let endRage wipe it)

  stats.wild_shape_active = true;
  stats.wild_shape_form_name = beast_name;
  stats.num_attacks = 2;

  bm.setAgentStats(idx, stats);

  // Set the beast form weapons on the agent
  bm.setAgentWeapons(idx, weapons);

  return true;
}

bool CombatEngine::deactivateWildShape(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WILD_SHAPE] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore saved AC and ability scores
  if (stats.base_ac > 0 && stats.wild_shape_saved_ac > 0) {
    stats.base_ac = stats.wild_shape_saved_ac;
  }
  if (stats.wild_shape_saved_str > 0) stats.str = stats.wild_shape_saved_str;
  if (stats.wild_shape_saved_dex > 0) stats.dex = stats.wild_shape_saved_dex;
  if (stats.wild_shape_saved_con > 0) stats.con = stats.wild_shape_saved_con;

  log_("[WILD_SHAPE] Restored stats: AC={}, STR={}, DEX={}, CON={}", stats.base_ac, stats.str, stats.dex, stats.con);

  // Restore original weapons
  bm.setAgentWeapons(idx, stats.wild_shape_saved_weapons);

  stats.wild_shape_active = false;
  stats.wild_shape_form_name = "";
  stats.lunar_radiance_available = false;

  bm.setAgentStats(idx, stats);
  log_("[WILD_SHAPE] Deactivated Wild Shape");
  return true;
}

// ── Starry Form Activation (Circle of the Stars) ────────────────────────────
bool CombatEngine::activateStarryForm(BattleMap& bm, int idx, int constellation) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[STARRY_FORM] Activating constellation {}", constellation);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[STARRY_FORM] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.starry_form_active = true;
  stats.starry_constellation = constellation;

  // Dragon constellation: add fly speed at L10+
  if (constellation == 3 && stats.char_level >= 10) {  // 3 = Dragon
    stats.speed_fly = stats.speed_walk;
    log_("[STARRY_FORM] Added fly speed for Dragon constellation");
  }

  // Full of Stars (L14): add resistances to B/P/S
  if (stats.char_level >= 14) {
    stats.set_physical_damage_multiplier(0, 0.5f);  // Bludgeoning
    stats.set_physical_damage_multiplier(1, 0.5f);  // Piercing
    stats.set_physical_damage_multiplier(2, 0.5f);  // Slashing
    log_("[STARRY_FORM] Added B/P/S resistances at level 14+");
  }

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] SUCCESS: Activated constellation {}", constellation);
  return true;
}

bool CombatEngine::deactivateStarryForm(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore fly speed
  stats.speed_fly = 0;

  // Clear resistances
  stats.set_physical_damage_multiplier(0, 1.0f);  // Bludgeoning
  stats.set_physical_damage_multiplier(1, 1.0f);  // Piercing
  stats.set_physical_damage_multiplier(2, 1.0f);  // Slashing

  stats.starry_form_active = false;
  stats.starry_constellation = 0;

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] Deactivated Starry Form");
  return true;
}

// ── Wrath of the Sea Activation (Circle of the Sea) ────────────────────────
bool CombatEngine::activateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[WRATH_OF_SEA] Activating Wrath of the Sea");

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[WRATH_OF_SEA] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.wrath_of_sea_active = true;

  // Stormborn (L10): add fly speed and resistances
  if (stats.char_level >= 10) {
    stats.speed_fly = stats.speed_walk;
    // Cold, Lightning, Thunder
    stats.set_magic_damage_multiplier(1, 0.5f);   // Cold
    stats.set_magic_damage_multiplier(4, 0.5f);   // Lightning
    stats.set_magic_damage_multiplier(9, 0.5f);   // Thunder
    log_("[WRATH_OF_SEA] Added fly speed and resistances at level 10+");
  }

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] SUCCESS: Activated Wrath of the Sea");
  return true;
}

bool CombatEngine::deactivateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  stats.speed_fly = 0;
  stats.set_magic_damage_multiplier(1, 1.0f);   // Cold
  stats.set_magic_damage_multiplier(4, 1.0f);   // Lightning
  stats.set_magic_damage_multiplier(9, 1.0f);   // Thunder

  stats.wrath_of_sea_active = false;

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] Deactivated Wrath of the Sea");
  return true;
}

// ── Dragon Min Roll (Starry Form, Dragon constellation) ──────────────────────
int CombatEngine::applyDragonMinRoll(BattleMap& bm, int idx, int d20_roll) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    return d20_roll;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Dragon constellation (value 3) with level 10+ gets min-roll-10
  if (stats.starry_form_active && stats.starry_constellation == 3 && stats.char_level >= 10) {
    int result = std::max(d20_roll, 10);
    if (result > d20_roll) {
      log_("[DRAGON_MIN_ROLL] Applied min-10: rolled {} -> {}", d20_roll, result);
    }
    return result;
  }

  return d20_roll;
}

} // namespace rpg
