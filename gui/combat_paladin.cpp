// ─────────────────────────────────────────────────────────────────────────────
//  combat_paladin.cpp  –  CombatEngine Paladin features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Devotion, Vengeance, Glory, Ancients.
//  Contents: Divine Smite, Lay on Hands, Sacred Weapon, Vow of Enmity, Soul of Vengeance,
//  Avenging Angel, Elder Champion, Inspiring Smite, Living Legend.
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
#include <tuple>
#include <unordered_set>
#include <vector>

namespace rpg {

int CombatEngine::applyDivineSmiteEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                         int slot_level, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.divine_smite_available || atk_cond.divine_smite_used) return -1;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    // Must still have a bonus action, the chosen slot, and no leveled spell already this turn.
    if (!hasBonusAction(bm, attacker_idx)) return -1;
    if (atk_stats.leveled_spell_cast_this_turn) return -1;
    const auto si = static_cast<std::size_t>(slot_level - 1);
    if (atk_stats.spell_slots_remaining[si] <= 0) return -1;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // 2d8 base, +1d8 per slot level above 1st (capped at a 5th-level slot → 6d8),
    // +1d8 if the target is an Undead or a Fiend.
    int dice = 1 + std::min(slot_level, 5);
    if (tgt_stats.is_undead || tgt_stats.is_fiend) dice += 1;
    int raw = 0;
    for (int i = 0; i < dice; ++i) raw += roll(8);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Radiant];
    const int smite_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"divine smite", smite_damage});
    result.total_damage += smite_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Radiant);

    int overflow = std::max(0, smite_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - smite_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    bm.setAgentStats(target_idx, tgt_stats);

    // Spend the slot, the bonus action, and mark the leveled-spell + once-per-turn interlocks.
    atk_stats.spell_slots_remaining[si] -= 1;
    atk_stats.leveled_spell_cast_this_turn = true;
    bm.setAgentStats(attacker_idx, atk_stats);
    (void)spendBonusAction(bm, attacker_idx);

    atk_cond.divine_smite_used = true;
    atk_cond.divine_smite_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} casts Divine Smite (level {} slot): +{} Radiant damage{}",
         agentName(bm, attacker_idx), slot_level, smite_damage,
         (tgt_stats.is_undead || tgt_stats.is_fiend) ? " (+1d8 vs Undead/Fiend)" : "");

    // The extra damage can break concentration and trigger on-damage conditions.
    if (smite_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, smite_damage);
        processDamageTaken(bm, target_idx, smite_damage);
    }
    return smite_damage;
}

AttackResult CombatEngine::applySoulOfVengeance(BattleMap& bm, int paladin_idx,
                                                int attacker_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (paladin_idx < 0 || paladin_idx >= n || attacker_idx < 0 || attacker_idx >= n)
        return AttackResult{};
    Agent::Conditions pc = bm.getAgentConditions(paladin_idx);
    if (!canTakeReaction(pc)) return AttackResult{};      // re-validate (canSoulOfVengeance checked, but be safe)

    log_("Soul of Vengeance: {} reacts — melee attack vs its sworn foe {}",
         agentName(bm, paladin_idx), agentName(bm, attacker_idx));

    // A fresh melee attack at the sworn foe. resolving_sentinel_guard_ (shared reaction-nesting guard)
    // keeps this counter-strike from re-opening the reaction window (no counter-of-a-counter).
    ctx_.resolving_sentinel_guard_ = true;
    AttackResult r = executeAction(bm, Attack{paladin_idx, attacker_idx, weapon_idx});
    ctx_.resolving_sentinel_guard_ = false;

    // Spend the reaction (re-fetch: executeAction may have mutated the paladin's conditions).
    pc = bm.getAgentConditions(paladin_idx);
    pc.reaction_used = true;
    bm.setAgentConditions(paladin_idx, pc);
    return r;
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

int CombatEngine::activateSacredWeapon(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return -1;  // invalid idx

    // Requires a Paladin who has taken the Oath of Devotion.
    if (stats.lacksClass(CharacterClass::Paladin) ||
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

// Paladin Oath of Vengeance — Vow of Enmity (L3). Spend one Channel Oath use to swear
// enmity against a creature within 30 ft: the paladin gains Advantage on attacks against
// it for 1 minute (or until this feature is used again). Returns true on success.
bool CombatEngine::activateVowOfEnmity(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx == idx) return false;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Requires a Paladin who has taken the Oath of Vengeance.
    if (stats.lacksClass(CharacterClass::Paladin) ||
        stats.paladin_oath != OathOfVengeancePath) return false;

    // Needs an available Channel Oath use.
    Resource* co = stats.getResource("Channel Oath");
    if (!co || co->current <= 0) return false;

    // Target must be a visible enemy within 30 ft.
    if (areAllies(bm, idx, target_idx)) return false;
    const PlacedAgent& sp = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    const int dist_ft = footprintDistance(sp.origin, sp.agent->getSize(),
                                          tp.origin, tp.agent->getSize()) * 5;
    if (dist_ft > 30) {
        log_("{} is more than 30 ft away — Vow of Enmity fails", agentName(bm, target_idx));
        return false;
    }
    if (!bm.hasLineOfSight(sp.origin, sp.agent->getSize(), tp.origin, tp.agent->getSize())) {
        log_("{} can't see {} — Vow of Enmity fails",
             agentName(bm, idx), agentName(bm, target_idx));
        return false;
    }

    // Spend 1 Channel Oath use, then re-fetch so we keep that decrement.
    spendResource(bm, idx, "Channel Oath", 1);
    stats = bm.getAgentStats(idx);
    stats.vow_of_enmity_target = target_idx;   // overwrites any prior vow ("until you use this again")
    stats.vow_of_enmity_turns  = 10;           // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} swears a Vow of Enmity against {}: Advantage on attacks against it for 1 minute",
         agentName(bm, idx), agentName(bm, target_idx));
    return true;
}

// Paladin Oath of Vengeance — Avenging Angel (L20). Bonus action, 10 minutes: gain a Fly Speed of
// 60 ft (+ hover) and a Frightful Aura inside the Aura of Protection (applied at enemy turn start in
// beginTurn). Costs one "Avenging Angel" use per long rest, or a level-5 spell slot when exhausted.
bool CombatEngine::activateAvengingAngel(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Paladin) ||
        s.paladin_oath != OathOfVengeancePath || s.classLevel(CharacterClass::Paladin) < 20) {
        log_("{} cannot use Avenging Angel (not a L20 Oath of Vengeance paladin)", agentName(bm, idx));
        return false;
    }
    if (s.avenging_angel_turns > 0) {
        log_("{}'s Avenging Angel is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    // Cost: one Avenging Angel use, or — when exhausted — a level-5 spell slot.
    Resource* aa = s.getResource("Avenging Angel");
    const bool has_use = aa && aa->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Avenging Angel (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        aa->spend(1);
        s.resources["Avenging Angel"] = *aa;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Avenging Angel", agentName(bm, idx));
    }

    // Snapshot the prior Fly speed so it reverts on expiry (beginTurn) — then grant Fly 60 + hover.
    s.avenging_angel_prior_fly = s.speed_fly;
    s.speed_fly = std::max(s.speed_fly, 60);
    s.avenging_angel_turns = 100;   // 10 minutes
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} becomes an Avenging Angel: Fly 60 ft (hover) and a Frightful Aura for 10 minutes",
         agentName(bm, idx));
    return true;
}

// Paladin Oath of the Ancients — Elder Champion (L20). Bonus action, 1 minute: regain 10 HP at the
// start of each of your turns, and enemies in your Aura of Protection have Disadvantage on saves vs
// your spells & Channel Oath options (applied in rollSpellSave). Costs one "Elder Champion" use per
// long rest, or a level-5 spell slot when exhausted. (Swift Spells is deferred — see known_limitations.)
bool CombatEngine::activateElderChampion(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Paladin) ||
        s.paladin_oath != OathOfAncientsPath || s.classLevel(CharacterClass::Paladin) < 20) {
        log_("{} cannot use Elder Champion (not a L20 Oath of the Ancients paladin)", agentName(bm, idx));
        return false;
    }
    if (s.elder_champion_turns > 0) {
        log_("{}'s Elder Champion is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    Resource* ec = s.getResource("Elder Champion");
    const bool has_use = ec && ec->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Elder Champion (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        ec->spend(1);
        s.resources["Elder Champion"] = *ec;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Elder Champion", agentName(bm, idx));
    }

    s.elder_champion_turns = 10;   // 1 minute
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} channels primal power (Elder Champion): 10 HP/turn regen and Disadvantage on enemy saves "
         "vs your spells for 1 minute", agentName(bm, idx));
    return true;
}

// Paladin Oath of Glory — Inspiring Smite (L3). Immediately after casting Divine Smite this turn,
// spend one Channel Oath use to grant a creature within 30 ft (may be self) 2d8 + Paladin level
// temporary HP. Returns the temp HP granted, or -1 if not allowed. (RAW lets you split the pool
// among several creatures; this grants the whole pool to one chosen creature — see known_limitations.)
int CombatEngine::activateInspiringSmite(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Paladin) || s.paladin_oath != OathOfGloryPath) return -1;

    // Must immediately follow a Divine Smite this turn, and only once per turn.
    const Agent::Conditions ic = bm.getAgentConditions(idx);
    if (!ic.divine_smite_used || ic.inspiring_smite_used) return -1;

    Resource* co = s.getResource("Channel Oath");
    if (!co || co->current <= 0) return -1;

    // Target must be within 30 ft (may be the paladin itself).
    const PlacedAgent& sp = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    if (footprintDistance(sp.origin, sp.agent->getSize(), tp.origin, tp.agent->getSize()) * 5 > 30) {
        log_("{} is more than 30 ft away — Inspiring Smite fails", agentName(bm, target_idx));
        return -1;
    }

    const int pool = roll(8) + roll(8) + s.classLevel(CharacterClass::Paladin);   // 2d8 + Paladin level
    spendResource(bm, idx, "Channel Oath", 1);

    // Mark used this turn (re-fetch conditions in case spendResource touched them).
    Agent::Conditions pc = bm.getAgentConditions(idx);
    pc.inspiring_smite_used = true;
    bm.setAgentConditions(idx, pc);

    Agent::Stats ts = bm.getAgentStats(target_idx);
    grantTempHp(ts, pool, idx);
    bm.setAgentStats(target_idx, ts);

    log_("{} channels Inspiring Smite: {} temporary HP to {}",
         agentName(bm, idx), pool, agentName(bm, target_idx));
    return pool;
}

// Paladin Oath of Glory — Living Legend (L20). Bonus action, 10 minutes: gain a reaction to reroll a
// failed saving throw (Living Legend save-reroll) and, once on each of your turns, turn a weapon miss
// into a hit (Unerring Strike). Costs one "Living Legend" use per long rest, or a level-5 spell slot
// when exhausted. (Charismatic — Advantage on CHA checks — is non-combat and not modeled.)
bool CombatEngine::activateLivingLegend(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Paladin) ||
        s.paladin_oath != OathOfGloryPath || s.classLevel(CharacterClass::Paladin) < 20) {
        log_("{} cannot use Living Legend (not a L20 Oath of Glory paladin)", agentName(bm, idx));
        return false;
    }
    if (s.living_legend_turns > 0) {
        log_("{}'s Living Legend is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    Resource* ll = s.getResource("Living Legend");
    const bool has_use = ll && ll->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Living Legend (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        ll->spend(1);
        s.resources["Living Legend"] = *ll;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Living Legend", agentName(bm, idx));
    }

    s.living_legend_turns = 100;   // 10 minutes
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} becomes a Living Legend: save-reroll reaction and once-per-turn Unerring Strike for 10 minutes",
         agentName(bm, idx));
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Moved from combat_core.cpp (COMBAT_CLASS_SPLIT_PLAN.md R6c)
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::auraSaveBonus(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::auraSaveBonus(bm, agent_idx);
}

bool CombatEngine::hasAuraOfCourage(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::hasAuraOfCourage(bm, agent_idx);
}

bool CombatEngine::hasAuraOfWarding(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::hasAuraOfWarding(bm, agent_idx);
}

bool CombatEngine::hasAuraOfAlacrity(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::hasAuraOfAlacrity(bm, agent_idx);
}


} // namespace rpg
