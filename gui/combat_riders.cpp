// ─────────────────────────────────────────────────────────────────────────────
//  combat_riders.cpp  –  CombatEngine on-hit riders, maneuvers, shoves/grapples
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · On-hit damage riders   — Brutal / Divine Strike / Divine Smite / Psionic /
//                               Cunning Strike (+ its rider conditions)
//    · Maneuvers & save riders— Maneuver, Precision Attack, Guided Strike, Topple,
//                               Stunning Strike, Open Hand
//    · Reaction/utility riders— Protective Field, Telekinetic Movement
//    · Bonus attacks & grapple— Flurry of Blows, consumeBonusAttack, Shove,
//                               Grapple, Grapple Escape
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  On-hit damage riders
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyBrutalStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                          const std::vector<int>& effects, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    Agent::Conditions tgt_cond = bm.getAgentConditions(target_idx);

    // Roll Brutal Strike damage (1d10 or 2d10)
    int damage_dice = atk_stats.brutal_strike_damage_dice;
    int bs_damage = 0;
    for (int i = 0; i < damage_dice; ++i) {
        bs_damage += roll(10);
    }

    // Add brutal strike damage to result's breakdown
    result.damage_breakdown.push_back({"brutal", bs_damage});
    result.total_damage += bs_damage;

    // Apply damage to target (apply additional Brutal Strike damage)
    int overflow = std::max(0, bs_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - bs_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);

    // Apply chosen effects
    std::string effect_name;
    for (int effect : effects) {
        if (effect == 0) {  // Forceful Blow: Push 15 ft straight away from the attacker
            effect_name = "Forceful Blow";
            const Cell attacker_origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
            int cells_moved = bm.forceMoveAgent(target_idx, attacker_origin, 15);
            result.push_ft_applied = cells_moved * 5;
            if (cells_moved > 0) {
                log_("{} is pushed {} feet (Forceful Blow)", agentName(bm, target_idx), cells_moved * 5);
            }
        } else if (effect == 1) {  // Hamstring Blow: Speed -15 ft
            tgt_cond.hamstrung = true;
            effect_name = "Hamstring Blow";
        } else if (effect == 2) {  // Staggering Blow (L13): Disadvantage on next save
            tgt_cond.staggered_next_save = true;
            effect_name = "Staggering Blow";
        } else if (effect == 3) {  // Sundering Blow (L13): +5 to next attack vs target
            tgt_cond.sundering_target_idx = attacker_idx;
            effect_name = "Sundering Blow";
        }
    }

    // Log Brutal Strike with the chosen effect
    if (!effect_name.empty()) {
        log_("{} is {}", agentName(bm, target_idx), effect_name );
    }

    // Set per-turn flag and clear availability
    atk_cond.brutal_strike_used_this_turn = true;
    atk_cond.brutal_strike_available = false;

    bm.setAgentStats(attacker_idx, atk_stats);
    bm.setAgentConditions(attacker_idx, atk_cond);
    bm.setAgentStats(target_idx, tgt_stats);
    bm.setAgentConditions(target_idx, tgt_cond);
}

void CombatEngine::applyDivineStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                           bool radiant, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (atk_cond.divine_strike_used) return;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // L7: 1d8; L14 (Improved Blessed Strikes): 2d8.
    const int dice = (atk_stats.classLevel(CharacterClass::Cleric) >= 14) ? 2 : 1;
    const MagicDamage_t dtype = radiant ? MagicDamage_t::Radiant : MagicDamage_t::Necrotic;
    int raw = 0;
    for (int i = 0; i < dice; ++i) raw += roll(8);

    const float mult = tgt_stats.magic_damage_multipliers[dtype];
    const int ds_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"divine strike", ds_damage});
    result.total_damage += ds_damage;
    result.magic_damage_types.push_back(dtype);

    int overflow = std::max(0, ds_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - ds_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);

    atk_cond.divine_strike_used = true;
    atk_cond.divine_strike_available = false;

    bm.setAgentConditions(attacker_idx, atk_cond);
    bm.setAgentStats(target_idx, tgt_stats);

    log_("{} adds Divine Strike: +{} {} damage", agentName(bm, attacker_idx), ds_damage,
         radiant ? "Radiant" : "Necrotic");

    // The extra damage can break concentration and trigger on-damage conditions.
    if (ds_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, ds_damage);
        processDamageTaken(bm, target_idx, ds_damage);
    }
}

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

int CombatEngine::applyEldritchSmiteEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                           int slot_level, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.eldritch_smite_available || atk_cond.eldritch_smite_used) return -1;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    // Must still have a bonus action, the pact slot, and no leveled spell already this turn.
    if (!hasBonusAction(bm, attacker_idx)) return -1;
    if (atk_stats.leveled_spell_cast_this_turn) return -1;
    const auto si = static_cast<std::size_t>(slot_level - 1);
    if (atk_stats.spell_slots_remaining[si] <= 0) return -1;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // (slot_level + 1)d8 Force damage.
    const int dice = slot_level + 1;
    int raw = 0;
    for (int i = 0; i < dice; ++i) raw += roll(8);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Force];
    const int smite_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"eldritch smite", smite_damage});
    result.total_damage += smite_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Force);

    int overflow = std::max(0, smite_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - smite_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    bm.setAgentStats(target_idx, tgt_stats);

    // Spend the pact slot, the bonus action, and mark the leveled-spell + once-per-turn interlocks.
    atk_stats.spell_slots_remaining[si] -= 1;
    atk_stats.leveled_spell_cast_this_turn = true;
    bm.setAgentStats(attacker_idx, atk_stats);
    (void)spendBonusAction(bm, attacker_idx);

    atk_cond.eldritch_smite_used = true;
    atk_cond.eldritch_smite_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} uses Eldritch Smite (level {} pact slot): +{} Force damage",
         agentName(bm, attacker_idx), slot_level, smite_damage);

    // Knock a Huge-or-smaller target Prone. getSize() is the grid footprint in cells
    // (Medium/Small=1, Large=2, Huge=3, Gargantuan=4), so Huge-or-smaller is <= 3 — the same
    // convention the Push mastery uses for "Large or smaller" (<= 2). Skip if already down.
    if (!result.target_down) {
        Agent::Conditions tgt_cond = bm.getAgentConditions(target_idx);
        const int tgt_sz = agents[static_cast<std::size_t>(target_idx)].agent->getSize();
        if (tgt_sz <= 3 && !tgt_cond.prone) {
            tgt_cond.prone = true;
            bm.setAgentConditions(target_idx, tgt_cond);
            log_("{} is knocked Prone (Eldritch Smite)", agentName(bm, target_idx));
        }
    }

    // The extra damage can break concentration and trigger on-damage conditions.
    if (smite_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, smite_damage);
        processDamageTaken(bm, target_idx, smite_damage);
    }
    return smite_damage;
}

bool CombatEngine::canUseWarMagic(BattleMap& bm, int idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats st = bm.getAgentStats(idx);
    if (st.lacksClass(CharacterClass::Fighter)) return false;
    if (st.fighter_subclass != EldritchKnightPath) return false;
    if (st.classLevel(CharacterClass::Fighter) < 7) return false;  // War Magic unlocks at L7
    if (bm.getAgentConditions(idx).war_magic_used) return false;  // once per Attack action
    return true;
}

void CombatEngine::markWarMagicUsed(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;
    Agent::Conditions c = bm.getAgentConditions(idx);
    c.war_magic_used = true;
    bm.setAgentConditions(idx, c);
    log_("{} uses War Magic (cast replaces a weapon attack)", agentName(bm, idx));
}

std::vector<int> CombatEngine::availableWarMagicSpells(const BattleMap& bm, int idx) const
{
    std::vector<int> result;
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return result;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    if (stats.lacksClass(CharacterClass::Fighter) ||
        stats.fighter_subclass != EldritchKnightPath || stats.classLevel(CharacterClass::Fighter) < 7)
        return result;

    const bool improved = stats.classLevel(CharacterClass::Fighter) >= 18;  // Improved War Magic also allows level 1-5 spells
    const auto& spells = pa.spells;
    for (int si : availableCastableSpells(bm, idx)) {
        if (si < 0 || si >= static_cast<int>(spells.size())) continue;
        const Spell& sp = spells[static_cast<std::size_t>(si)];
        if (sp.casting_time != Spell::Action) continue;
        if (sp.level == 0 || (improved && sp.level >= 1 && sp.level <= 5))
            result.push_back(si);
    }
    return result;
}

int CombatEngine::applyArcaneCharge(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    const Agent::Stats& stats = agents[static_cast<std::size_t>(idx)].agent->getStats();
    if (stats.lacksClass(CharacterClass::Fighter) ||
        stats.fighter_subclass != EldritchKnightPath || stats.classLevel(CharacterClass::Fighter) < 15)
        return -1;  // not an EK L15+

    const Cell origin = agents[static_cast<std::size_t>(idx)].origin;
    const double dx = static_cast<double>(target_col - origin.col);
    const double dy = static_cast<double>(target_row - origin.row);
    const double dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0;
    if (dist_ft > 30.0 + 1e-6) return -2;                              // out of range
    if (!isValidTeleportDestination(bm, target_col, target_row)) return -3;  // blocked
    if (!teleportAgent(bm, idx, target_col, target_row)) return -3;

    const int feet = static_cast<int>(dist_ft + 0.5);
    log_("{} uses Arcane Charge: teleports {} ft to ({}, {})",
         agentName(bm, idx), feet, target_col, target_row);
    return feet;
}

void CombatEngine::applyPsionicStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                            AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.psionic_strike_available || atk_cond.psionic_strike_used) return;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    const Resource* ped = atk_stats.getResource("Psionic Energy");
    if (!ped || ped->current <= 0) return;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // Force damage = one Psionic Energy die + INT mod (floored for odd negative scores).
    int int_mod = (atk_stats.intel - 10) / 2;
    if (atk_stats.intel < 10 && (atk_stats.intel - 10) % 2 != 0) --int_mod;
    int raw = std::max(0, roll(atk_stats.psionic_die_size) + int_mod);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Force];
    const int ps_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"psionic strike", ps_damage});
    result.total_damage += ps_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Force);

    int overflow = std::max(0, ps_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - ps_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);

    // Spend one Psionic Energy die and mark Psionic Strike used for the turn.
    spendResource(bm, attacker_idx, "Psionic Energy", 1);
    atk_cond.psionic_strike_used = true;
    atk_cond.psionic_strike_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);
    bm.setAgentStats(target_idx, tgt_stats);

    log_("{} adds Psionic Strike: +{} Force damage", agentName(bm, attacker_idx), ps_damage);

    if (ps_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, ps_damage);
        processDamageTaken(bm, target_idx, ps_damage);
    }
}

// Monk Martial Arts die size by character level (2024 PHB): d6 (1–4), d8 (5–10), d10 (11–16), d12 (17+).
static int martialArtsDieSize(int level) noexcept
{
    if (level >= 17) return 12;
    if (level >= 11) return 10;
    if (level >= 5)  return 8;
    return 6;
}

void CombatEngine::applyHandOfHarmEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                         AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.hand_of_harm_available) return;

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    if (atk_stats.lacksClass(CharacterClass::Monk) ||
        atk_stats.monk_subclass  != WarriorOfMercyPath ||
        atk_stats.classLevel(CharacterClass::Monk) < 3) return;

    const bool free = atk_stats.classLevel(CharacterClass::Monk) >= 11;   // L11 Flurry of Healing and Harm: no Focus Point cost

    // L11: usable any number of times per turn, but only once per target.
    if (free && atk_cond.hand_of_harm_last_target == target_idx) return;

    // Below L11: a Focus Point is required (and the once-per-turn gate is enforced at the eligibility site).
    const Resource* fp = atk_stats.getResource("Focus Points");
    if (!free && (!fp || fp->current <= 0)) return;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // Necrotic damage = one Martial Arts die + WIS modifier (floored for odd negative scores).
    int wis_mod = (atk_stats.wis - 10) / 2;
    if (atk_stats.wis < 10 && (atk_stats.wis - 10) % 2 != 0) --wis_mod;
    int raw = std::max(0, roll(martialArtsDieSize(atk_stats.classLevel(CharacterClass::Monk))) + wis_mod);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Necrotic];
    const int hoh_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"hand of harm", hoh_damage});
    result.total_damage += hoh_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Necrotic);

    int overflow = std::max(0, hoh_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - hoh_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    bm.setAgentStats(target_idx, tgt_stats);

    // Spend a Focus Point unless L11 makes it free; mark Hand of Harm used / record the target.
    if (!free) spendResource(bm, attacker_idx, "Focus Points", 1);
    atk_cond = bm.getAgentConditions(attacker_idx);
    atk_cond.hand_of_harm_used = true;
    atk_cond.hand_of_harm_available = false;
    atk_cond.hand_of_harm_last_target = target_idx;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} adds Hand of Harm: +{} Necrotic damage{}", agentName(bm, attacker_idx), hoh_damage,
         free ? " (free)" : "");

    // L6 Physician's Touch: the target is also Poisoned (until the end of the Monk's next turn — modeled
    // as the Poisoned condition, cleared like other conditions).
    if (atk_stats.classLevel(CharacterClass::Monk) >= 6) {
        applyPoisoned(bm, target_idx);
        log_("{} is Poisoned (Physician's Touch)", agentName(bm, target_idx));
    }

    if (hoh_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, hoh_damage);
        processDamageTaken(bm, target_idx, hoh_damage);
    }
}

HandOfHealingResult CombatEngine::handOfHealing(BattleMap& bm, int monk_idx, int target_idx, bool free) noexcept
{
    HandOfHealingResult res;
    auto agents = bm.placedAgents();
    if (monk_idx   < 0 || monk_idx   >= static_cast<int>(agents.size())) return res;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return res;

    Agent::Stats ms = bm.getAgentStats(monk_idx);
    if (ms.lacksClass(CharacterClass::Monk) ||
        ms.monk_subclass  != WarriorOfMercyPath ||
        ms.classLevel(CharacterClass::Monk) < 3) return res;

    // "free" (no Focus Point, no Bonus Action) is only granted at L11 (Flurry of Healing and Harm),
    // where a Flurry strike may be replaced with a use of Hand of Healing.
    const bool actually_free = free && ms.classLevel(CharacterClass::Monk) >= 11;

    if (!actually_free) {
        if (!hasBonusAction(bm, monk_idx)) return res;
        const Resource* fp = ms.getResource("Focus Points");
        if (!fp || fp->current <= 0) return res;
    }

    res.valid = true;

    // Heal = one Martial Arts die + WIS modifier (floored for odd negative scores; minimum 1).
    int wis_mod = (ms.wis - 10) / 2;
    if (ms.wis < 10 && (ms.wis - 10) % 2 != 0) --wis_mod;
    int amount = std::max(1, roll(martialArtsDieSize(ms.classLevel(CharacterClass::Monk))) + wis_mod);

    int before = bm.getAgentStats(target_idx).hp_cur;
    healAgent(bm, target_idx, amount);
    res.amount_healed = bm.getAgentStats(target_idx).hp_cur - before;

    // L6 Physician's Touch: Hand of Healing also ends one of Blinded/Deafened/Paralyzed/Poisoned/Stunned.
    if (ms.classLevel(CharacterClass::Monk) >= 6) {
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        const char* cleared = nullptr;
        if      (tc.blinded)   { tc.blinded   = false; cleared = "Blinded"; }
        else if (tc.deafened)  { tc.deafened  = false; cleared = "Deafened"; }
        else if (tc.paralyzed) { tc.paralyzed = false; cleared = "Paralyzed"; }
        else if (tc.poisoned)  { tc.poisoned  = false; cleared = "Poisoned"; }
        else if (tc.stunned)   { tc.stunned   = false; cleared = "Stunned"; }
        if (cleared) {
            bm.setAgentConditions(target_idx, tc);
            res.condition_cleared = true;
            res.cleared_condition = cleared;
        }
    }

    // Spend the Focus Point first, then the Bonus Action (spendResource re-reads/writes stats; doing it
    // last would clobber the spendBonusAction decrement). Skipped entirely when folded into a Flurry strike.
    if (!actually_free) {
        spendResource(bm, monk_idx, "Focus Points", 1);
        spendBonusAction(bm, monk_idx);
    }

    log_("{} uses Hand of Healing: {} HP to {}{}{}", agentName(bm, monk_idx), res.amount_healed,
         agentName(bm, target_idx), actually_free ? " (free)" : "",
         res.condition_cleared ? std::format(" — ends {}", res.cleared_condition) : "");
    return res;
}

int CombatEngine::wholenessOfBody(BattleMap& bm, int monk_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (monk_idx < 0 || monk_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats ms = bm.getAgentStats(monk_idx);
    if (ms.lacksClass(CharacterClass::Monk) ||
        ms.monk_subclass  != WarriorOfTheOpenHandPath ||
        ms.classLevel(CharacterClass::Monk) < 6) return 0;

    if (!hasBonusAction(bm, monk_idx)) return 0;
    const Resource* wob = ms.getResource("Wholeness of Body");
    if (!wob || wob->current <= 0) return 0;

    // Heal = one Martial Arts die + WIS modifier (floored for odd negative scores; minimum 1).
    int wis_mod = (ms.wis - 10) / 2;
    if (ms.wis < 10 && (ms.wis - 10) % 2 != 0) --wis_mod;
    int amount = std::max(1, roll(martialArtsDieSize(ms.classLevel(CharacterClass::Monk))) + wis_mod);

    int before = bm.getAgentStats(monk_idx).hp_cur;
    healAgent(bm, monk_idx, amount);
    int healed = bm.getAgentStats(monk_idx).hp_cur - before;

    // Spend the resource first, then the Bonus Action (spendResource re-reads/writes stats; doing it
    // last would clobber the spendBonusAction decrement — mirrors handOfHealing).
    spendResource(bm, monk_idx, "Wholeness of Body", 1);
    spendBonusAction(bm, monk_idx);

    log_("{} uses Wholeness of Body: {} HP restored", agentName(bm, monk_idx), healed);
    return healed;
}

GrappleResult CombatEngine::applyPunchAndGrab(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    GrappleResult result;
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return result;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return result;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.grappler_punch_grab_available || atk_cond.grappler_punch_grab_used) return result;  // once per turn

    // Mark Punch-and-Grab used for the turn + clear the flag, THEN run the grapple. The grapple routes
    // through the shared resolveGrapple core (contested check + computed escape DC), exactly like the
    // standalone Grapple action — no parallel grapple path.
    atk_cond.grappler_punch_grab_used      = true;
    atk_cond.grappler_punch_grab_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    result = resolveGrapple(bm, attacker_idx, target_idx, /*contested=*/true, /*escape_dc_override=*/0);
    log_("{}: Grappler — Punch-and-Grab also attempts to grapple {}",
         agentName(bm, attacker_idx), agentName(bm, target_idx));
    return result;
}

void CombatEngine::applyCunningStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                            const std::vector<int>& effects, AttackResult& result,
                                            int round_num) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Stats      atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Conditions atk_cond  = bm.getAgentConditions(attacker_idx);

    // Only valid right after a qualifying hit flagged this attack, and only once per turn.
    if (!atk_cond.cunning_strike_available || atk_cond.sneak_attack_used) return;

    const bool is_assassin = (atk_stats.hasClass(CharacterClass::Rogue) &&
                              atk_stats.rogue_subclass == AssassinPath);

    const int sneak_dice = (atk_stats.classLevel(CharacterClass::Rogue) + 1) / 2;  // 1d6 @ L1-2 … 10d6 @ L19-20

    // Validate the chosen rider set: count limit (Improved Cunning Strike), per-effect cost, min level.
    const int max_effects = (atk_stats.classLevel(CharacterClass::Rogue) >= 11) ? 2 : 1;
    int cost = 0;
    bool has_poison_rider = false;
    bool effects_ok = (static_cast<int>(effects.size()) <= max_effects);
    for (int e : effects) {
        int c = cunningStrikeCost(e);
        if (c <= 0 || atk_stats.classLevel(CharacterClass::Rogue) < cunningStrikeMinLevel(e)) { effects_ok = false; break; }
        // Stealth Attack (Thief Supreme Sneak): Thief-only, and only if this strike came from
        // stealth (the attack just ended the Hide/Invisible condition this turn).
        if (e == 6 && (atk_stats.rogue_subclass != ThiefPath || !atk_cond.attacked_while_invisible)) {
            effects_ok = false; break;
        }
        if (e == 0) has_poison_rider = true;
        cost += c;
    }
    // Envenom Weapons (Assassin L13+): the Poison option costs 0 Sneak Attack dice (refund it).
    if (effects_ok && has_poison_rider && is_assassin && atk_stats.classLevel(CharacterClass::Rogue) >= 13)
        cost -= cunningStrikeCost(0);
    if (!effects_ok || cost > sneak_dice) { effects_ok = false; cost = 0; }

    // Roll the remaining Sneak Attack dice.
    const int dmg_dice = sneak_dice - cost;
    int sneak_bonus = 0;
    for (int i = 0; i < dmg_dice; ++i) sneak_bonus += roll(6);

    result.total_damage += sneak_bonus;
    result.damage_breakdown.push_back({"sneak attack", sneak_bonus});
    log_("Sneak Attack: {} adds {}d6 = {} damage", agentName(bm, attacker_idx), dmg_dice, sneak_bonus);

    int extra = sneak_bonus;

    // Assassinate (Assassin L3+): a Sneak hit during the first round of combat (round_num == 0)
    // also deals flat damage equal to the Rogue's level.
    if (is_assassin && atk_stats.classLevel(CharacterClass::Rogue) >= 3 && round_num == 0) {
        const int bonus = atk_stats.classLevel(CharacterClass::Rogue);
        result.total_damage += bonus;
        result.damage_breakdown.push_back({"Assassinate", bonus});
        log_("Assassinate: {} adds +{} damage (first round)", agentName(bm, attacker_idx), bonus);
        extra += bonus;
    }

    // Fold the Sneak Attack (+ Assassinate) damage into the target's HP.
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    int overflow = std::max(0, extra - tgt_stats.temp_hp);
    tgt_stats.temp_hp  = std::max(0, tgt_stats.temp_hp - extra);
    tgt_stats.hp_cur   = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    result.hp_after    = tgt_stats.hp_cur;
    result.target_down = (result.hp_after <= 0);
    bm.setAgentStats(target_idx, tgt_stats);

    atk_cond.sneak_attack_used        = true;
    atk_cond.cunning_strike_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    // If the Sneak Attack dropped the target, knock it unconscious (matches the base-attack path).
    Agent::Conditions tgt_cond = bm.getAgentConditions(target_idx);
    if (result.hp_after <= 0 && !tgt_cond.unconscious && !tgt_cond.dead) {
        applyUnconscious(bm, target_idx);
        result.target_down = true;
    }

    // Apply rider conditions LAST, after this attack's damage is fully settled — so a rider that sets
    // a condition (e.g. Knock Out → Unconscious) can never feed back into this attack's resolution.
    // (Envenom Weapons' bonus 2d6 Poison folds into result/HP inside this call.)
    if (effects_ok && cost >= 0 && !effects.empty())
        applyCunningStrikeRiders(bm, attacker_idx, target_idx, effects, result);

    // Death Strike (Assassin L17+): a Sneak hit during the first round forces the target to make a
    // Constitution save (DC 8 + DEX + PB). On a failure, the entire attack's damage is doubled. Run
    // last so it doubles base + Sneak + Assassinate + Envenom damage together.
    if (is_assassin && atk_stats.classLevel(CharacterClass::Rogue) >= 17 && round_num == 0 && result.total_damage > 0) {
        const int dc = spellSaveDcFromAbility(atk_stats, SaveDex);   // 8 + PB + DEX mod
        int total = roll(20) + saveModFor(bm, target_idx, SaveCon);
        total = applyIndomitableMight(bm, target_idx, SaveCon, total);
        if (total >= dc) {
            log_("Death Strike: {} succeeds its CON save (DC {})", agentName(bm, target_idx), dc);
        } else {
            const int dbl = result.total_damage;   // deal the attack's damage again → doubled
            Agent::Stats ds = bm.getAgentStats(target_idx);
            int dov = std::max(0, dbl - ds.temp_hp);
            ds.temp_hp = std::max(0, ds.temp_hp - dbl);
            ds.hp_cur  = std::clamp(ds.hp_cur - dov, 0, ds.hp_max);
            bm.setAgentStats(target_idx, ds);
            result.total_damage += dbl;
            result.damage_breakdown.push_back({"Death Strike (doubled)", dbl});
            result.hp_after    = ds.hp_cur;
            result.target_down = (result.hp_after <= 0);
            log_("Death Strike: {} fails its CON save (DC {}) — damage doubled (+{})",
                 agentName(bm, target_idx), dc, dbl);
            Agent::Conditions dc2 = bm.getAgentConditions(target_idx);
            if (result.hp_after <= 0 && !dc2.unconscious && !dc2.dead) {
                applyUnconscious(bm, target_idx);
                result.target_down = true;
            }
        }
    }
}

void CombatEngine::applyCunningStrikeRiders(BattleMap& bm, int attacker_idx, int target_idx,
                                            const std::vector<int>& effects, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    const Agent::Stats atk = bm.getAgentStats(attacker_idx);
    const int dc = spellSaveDcFromAbility(atk, SaveDex);  // 8 + prof + DEX mod
    const bool envenom = (atk.hasClass(CharacterClass::Rogue) &&
                          atk.rogue_subclass == AssassinPath && atk.classLevel(CharacterClass::Rogue) >= 13);

    for (int e : effects) {
        if (e == 2) {  // Withdraw — no save; attacker moves without provoking opportunity attacks
            Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
            ac.disengaging = true;
            bm.setAgentConditions(attacker_idx, ac);
            log_("Cunning Strike (Withdraw): {} won't provoke opportunity attacks",
                 agentName(bm, attacker_idx));
            continue;
        }

        if (e == 6) {  // Stealth Attack (Thief Supreme Sneak) — the Sneak Attack doesn't end your Hide.
            Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
            ac.invisible = true;          // remain hidden after the strike (restores the just-ended Hide)
            ac.hidden    = true;
            // v1: the RAW "end the turn behind Three-Quarters/Total Cover" clause is not modeled.
            bm.setAgentConditions(attacker_idx, ac);
            log_("Cunning Strike (Stealth Attack): {} remains hidden after the strike",
                 agentName(bm, attacker_idx));
            continue;
        }

        SaveAbility_t sa; std::string name; int dur; int repeat;
        switch (e) {
            case 0: sa = SaveCon; name = "Poisoned";    dur = 10; repeat = 1; break;
            case 1: sa = SaveDex; name = "Prone";       dur = 10; repeat = 0; break;
            case 4: sa = SaveCon; name = "Unconscious"; dur = 10; repeat = 1; break;  // Knock Out
            case 5: sa = SaveDex; name = "Blinded";     dur = 2;  repeat = 0; break;  // Obscure
            default: continue;  // 3=Daze deferred / unknown
        }

        const Agent::Stats tgt = bm.getAgentStats(target_idx);
        const Agent::Conditions& tc0 = agents[static_cast<std::size_t>(target_idx)].agent->getConditions();
        bool auto_fail = (tc0.paralyzed || tc0.stunned) && (sa == SaveStr || sa == SaveDex);
        int d20 = auto_fail ? 1 : roll(20);
        int total = d20 + saveModFor(bm, target_idx, sa);
        total = applyIndomitableMight(bm, target_idx, sa, total);
        bool saved = auto_fail ? false : (total >= dc);
        if (saved) {
            log_("Cunning Strike: {} resisted {} (DC {})", agentName(bm, target_idx), name, dc);
            continue;
        }

        // Set the flag immediately, and register an ActiveAgentCondition for duration / repeat saves.
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        if      (name == "Poisoned")    tc.poisoned = true;
        else if (name == "Prone")       tc.prone = true;
        else if (name == "Blinded")     tc.blinded = true;
        else if (name == "Unconscious") { tc.unconscious = true; tc.incapacitated = true; tc.prone = true; }
        bm.setAgentConditions(target_idx, tc);

        ActiveAgentCondition cond;
        cond.agent_idx        = target_idx;
        cond.caster_idx       = attacker_idx;
        cond.spell_idx        = -1;
        cond.condition_name   = name;
        cond.save_ability     = sa;
        cond.turns_remaining  = dur;
        cond.save_dc          = dc;
        cond.save_repeat_turns = repeat;
        cond.next_save_turn   = 0;
        (void)addAgentCondition(bm, cond);
        log_("Cunning Strike: {} fails its {} save → {} (DC {})",
             agentName(bm, target_idx), name, name, dc);

        // Envenom Weapons (Assassin L13+): a failed Poison save also deals 2d6 Poison damage that
        // ignores Resistance to Poison (Immunity 0.0 and Vulnerability still apply).
        if (e == 0 && envenom) {
            const int raw = roll(6) + roll(6);
            Agent::Stats es = bm.getAgentStats(target_idx);
            float mult = es.magic_damage_multipliers[Poison];
            if (mult > 0.0f && mult < 1.0f) mult = 1.0f;   // ignore Resistance
            const int pd = static_cast<int>(static_cast<float>(raw) * mult);
            if (pd > 0) {
                int pov = std::max(0, pd - es.temp_hp);
                es.temp_hp = std::max(0, es.temp_hp - pd);
                es.hp_cur  = std::clamp(es.hp_cur - pov, 0, es.hp_max);
                bm.setAgentStats(target_idx, es);
                result.total_damage += pd;
                result.damage_breakdown.push_back({"Envenom (Poison)", pd});
                result.hp_after    = es.hp_cur;
                result.target_down = (es.hp_cur <= 0);
                Agent::Conditions ec = bm.getAgentConditions(target_idx);
                if (es.hp_cur <= 0 && !ec.unconscious && !ec.dead) {
                    applyUnconscious(bm, target_idx);
                    result.target_down = true;
                }
            }
            log_("Envenom Weapons: {} takes {} Poison damage (ignores Resistance)",
                 agentName(bm, target_idx), pd);
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Soulknife Rogue — Soul Blades & Rend Mind
// ─────────────────────────────────────────────────────────────────────────────

// Homing Strikes (L9): convert a MISS with a Psychic Blade into a hit by adding a Psionic Energy Die
// to the attack roll. The die is spent only when it converts (RAW). On a convert, fresh damage is
// rolled and applied (temp HP first), with a concentration check. v1: a converted hit does not open
// the Sneak Attack window.
bool CombatEngine::applyHomingStrike(BattleMap& bm, int attacker_idx, int target_idx,
                                     int weapon_idx, AttackResult& result) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return false;
    if (result.hit) return false;                              // only a miss can be homed
    if (weapon_idx < 0 || weapon_idx > 2) return false;

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    if (atk_stats.lacksClass(CharacterClass::Rogue) ||
        atk_stats.rogue_subclass != SoulknifePath || atk_stats.classLevel(CharacterClass::Rogue) < 9) return false;
    Resource* ped = atk_stats.getResource("Psionic Energy");
    if (!ped || ped->current < 1) return false;

    const std::vector<Weapon> weapons = bm.getAgentWeapons(attacker_idx);
    if (weapon_idx < 0 || weapon_idx >= static_cast<int>(weapons.size())) return false;
    const Weapon& w = weapons[static_cast<std::size_t>(weapon_idx)];
    if (!w.psychic_blade) return false;

    const int die = roll(atk_stats.psionic_die_size);
    result.attack_mod += die;
    result.total_roll += die;
    reevaluateAttackHit(result);
    log_("{} uses Homing Strikes: +{} (now {} vs AC {})", agentName(bm, attacker_idx), die,
         result.total_roll, result.target_ac);
    if (!result.hit) {
        // Did not connect → the die is NOT expended (RAW: spent only if it causes a hit).
        log_("{}: Homing Strikes still misses — the die is not expended", agentName(bm, attacker_idx));
        return false;
    }

    // Converted to a hit: spend the die, roll + apply damage.
    ped->current -= 1;
    bm.setAgentStats(attacker_idx, atk_stats);

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    result.total_damage = 0;
    result.damage_breakdown.clear();
    rollDamage(w, atk_stats, tgt_stats, result, false);
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - dmg);
    tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    result.hp_after    = tgt_stats.hp_cur;
    result.target_down = (result.hp_after <= 0);
    bm.setAgentStats(target_idx, tgt_stats);
    log_("Homing Strikes connects for {} damage", dmg);

    (void)checkConcentrationOnDamage(bm, target_idx, dmg, attacker_idx);
    Agent::Conditions tc = bm.getAgentConditions(target_idx);
    if (result.hp_after <= 0 && !tc.unconscious && !tc.dead) applyUnconscious(bm, target_idx);
    return true;
}

bool CombatEngine::canRendMind(const BattleMap& bm, int attacker_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(attacker_idx);
    if (s.lacksClass(CharacterClass::Rogue) ||
        s.rogue_subclass != SoulknifePath || s.classLevel(CharacterClass::Rogue) < 17) return false;
    const Resource* rm  = s.getResource("Rend Mind");
    const Resource* ped = s.getResource("Psionic Energy");
    const bool have_use = rm && rm->current >= 1;
    const bool have_ped = ped && ped->current >= 3;
    return have_use || have_ped;
}

// Rend Mind (L17): WIS save (DC 8 + DEX + PB) or Stunned for 1 minute (repeat save end of each turn).
// Cost: a "Rend Mind" use, or 3 Psionic Energy Dice if the use is spent. Returns true iff Stunned.
bool CombatEngine::applyRendMind(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return false;
    if (!canRendMind(bm, attacker_idx)) return false;

    Agent::Stats atk = bm.getAgentStats(attacker_idx);
    Resource* rm  = atk.getResource("Rend Mind");
    Resource* ped = atk.getResource("Psionic Energy");
    if (rm && rm->current >= 1)            rm->current -= 1;       // free use first
    else if (ped && ped->current >= 3)     ped->current -= 3;      // else 3 Psionic Energy Dice
    else                                   return false;
    bm.setAgentStats(attacker_idx, atk);

    const int dc = spellSaveDcFromAbility(atk, SaveDex);           // 8 + PB + DEX mod
    const Agent::Conditions tc0 = bm.getAgentConditions(target_idx);
    const bool auto_fail = tc0.paralyzed || tc0.stunned;
    const int d20   = auto_fail ? 1 : roll(20);
    const int total = applyIndomitableMight(bm, target_idx, SaveWis, d20 + saveModFor(bm, target_idx, SaveWis));
    if (!auto_fail && total >= dc) {
        log_("Rend Mind: {} resists (WIS {} vs DC {})", agentName(bm, target_idx), total, dc);
        return false;
    }

    Agent::Conditions tc = bm.getAgentConditions(target_idx);
    tc.stunned = true;
    tc.incapacitated = true;
    bm.setAgentConditions(target_idx, tc);

    ActiveAgentCondition cond;
    cond.agent_idx         = target_idx;
    cond.caster_idx        = attacker_idx;
    cond.spell_idx         = -1;
    cond.condition_name    = "Stunned";
    cond.save_ability      = SaveWis;
    cond.turns_remaining   = 10;
    cond.save_dc           = dc;
    cond.save_repeat_turns = 1;
    cond.next_save_turn    = 0;
    (void)addAgentCondition(bm, cond);
    log_("Rend Mind: {} fails its WIS save ({} vs DC {}) → Stunned", agentName(bm, target_idx),
         auto_fail ? 0 : total, dc);
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Maneuvers & save riders
// ─────────────────────────────────────────────────────────────────────────────

ManeuverResult CombatEngine::applyManeuverEffect(BattleMap& bm, int attacker_idx, int target_idx, int maneuver_type) noexcept
{
    ManeuverResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.maneuver_available) return res;

    res.valid = true;
    res.maneuver_type = maneuver_type;

    // Spend 1 Superiority Die and clear the flag
    spendResource(bm, attacker_idx, "Superiority Dice", 1);
    ac.maneuver_available = false;
    bm.setAgentConditions(attacker_idx, ac);

    Agent::Stats as = bm.getAgentStats(attacker_idx);

    // Maneuver save DC = 8 + prof + the higher of STR or DEX mod (2024 PHB). Uses
    // dndMod (floor) — abilityMod truncates toward zero and is wrong for odd scores < 10.
    int dc = 8 + as.prof_bonus + std::max(dndMod(as.str), dndMod(as.dex));
    res.save_dc = dc;

    if (maneuver_type == 0) {
        // Trip: STR save or Prone for 1 turn
        int save_total = roll(20, saveModFor(bm, target_idx, SaveStr));
        save_total = applyIndomitableMight(bm, target_idx, SaveStr, save_total);
        res.save_roll = save_total;
        if (res.save_roll < dc) {
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.prone = true;
            bm.setAgentConditions(target_idx, tc);
            ActiveAgentCondition cond;
            cond.agent_idx       = target_idx;
            cond.caster_idx      = attacker_idx;
            cond.condition_name  = "Prone";
            cond.turns_remaining = 1;
            (void)addAgentCondition(bm, cond);
            res.condition_applied = true;
            log_("{} is tripped Prone (Battle Master Tripping Attack — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        } else {
            log_("{} resists Tripping Attack (Battle Master — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        }
    } else if (maneuver_type == 1) {
        // Menacing: WIS save or Frightened for 1 turn
        res.save_roll = roll(20, saveModFor(bm, target_idx, SaveWis));
        if (res.save_roll < dc && hasAuraOfCourage(bm, target_idx)) {
            // Aura of Courage: the target can't be Frightened — the maneuver lands no condition.
            log_("{} can't be Frightened (Aura of Courage) — Menacing Attack has no effect",
                 agentName(bm, target_idx));
        } else if (res.save_roll < dc) {
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.frightened = true;
            bm.setAgentConditions(target_idx, tc);
            ActiveAgentCondition cond;
            cond.agent_idx       = target_idx;
            cond.caster_idx      = attacker_idx;
            cond.condition_name  = "Frightened";
            cond.turns_remaining = 1;
            (void)addAgentCondition(bm, cond);
            res.condition_applied = true;
            log_("{} is Frightened (Battle Master Menacing Attack — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        } else {
            log_("{} resists Menacing Attack (Battle Master — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        }
    } else if (maneuver_type == 2) {
        // Pushing: forceMoveAgent 15 feet
        const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
        int cells_moved = bm.forceMoveAgent(target_idx, origin, 15);
        res.push_distance = cells_moved * 5;
        log_("{} is pushed back {} feet (Battle Master Pushing Attack)",
             agentName(bm, target_idx), res.push_distance);
    } else if (maneuver_type == 3) {
        // Goading Attack: WIS save or the target has Disadvantage attacking anyone other than
        // you until the end of your next turn (goaded_by, expired in beginTurn).
        res.save_roll = roll(20, saveModFor(bm, target_idx, SaveWis));
        if (res.save_roll < dc) {
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.goaded_by = attacker_idx;
            bm.setAgentConditions(target_idx, tc);
            res.condition_applied = true;
            log_("{} is Goaded (Disadvantage attacking anyone but {} — save {} vs DC {})",
                 agentName(bm, target_idx), agentName(bm, attacker_idx), res.save_roll, dc);
        } else {
            log_("{} resists Goading Attack (Battle Master — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        }
    } else if (maneuver_type == 4) {
        // Distracting Strike: no save. The next attack vs the target by an attacker other than you
        // (before the start of your next turn) has Advantage (distracted_by, consumed on use).
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        tc.distracted_by = attacker_idx;
        bm.setAgentConditions(target_idx, tc);
        res.condition_applied = true;
        log_("{} is Distracted (the next attack against it by another creature has Advantage)",
             agentName(bm, target_idx));
    } else if (maneuver_type == 5) {
        // Disarming Attack: STR save or the target drops its weapon — its weapon attacks resolve as
        // improvised Unarmed Strikes until the start of your next turn (disarmed/disarmed_by).
        int save_total = roll(20, saveModFor(bm, target_idx, SaveStr));
        save_total = applyIndomitableMight(bm, target_idx, SaveStr, save_total);
        res.save_roll = save_total;
        if (res.save_roll < dc) {
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.disarmed = true;
            tc.disarmed_by = attacker_idx;
            bm.setAgentConditions(target_idx, tc);
            res.condition_applied = true;
            log_("{} is Disarmed (must fight with improvised Unarmed Strikes — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        } else {
            log_("{} resists Disarming Attack (Battle Master — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
        }
    }

    return res;
}

ManeuverResult CombatEngine::applySweepingAttack(BattleMap& bm, const Attack& action,
                                                 const AttackResult& result, int secondary_idx) noexcept
{
    ManeuverResult res;
    res.maneuver_type = 6;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx;
    if (atk < 0 || atk >= n || secondary_idx < 0 || secondary_idx >= n || secondary_idx == atk) return res;

    Agent::Conditions ac = bm.getAgentConditions(atk);
    if (!ac.maneuver_available) return res;          // only right after a qualifying hit

    res.valid = true;
    // Spend 1 Superiority Die and clear the per-attack flag (mirrors applyManeuverEffect).
    spendResource(bm, atk, "Superiority Dice", 1);
    ac.maneuver_available = false;
    bm.setAgentConditions(atk, ac);

    // The original attack roll must "would hit" the 2nd creature's AC.
    const int secondary_ac = calculateAC(bm, secondary_idx);
    res.save_dc  = secondary_ac;          // reuse save_dc to report the 2nd creature's AC
    res.save_roll = result.total_roll;    // reuse save_roll to report the original attack roll
    if (result.total_roll < secondary_ac) {
        log_("Sweeping Attack misses {} (attack roll {} vs AC {})",
             agentName(bm, secondary_idx), result.total_roll, secondary_ac);
        return res;
    }

    // Roll the superiority die; deal it as the attack's damage type (use the wielded weapon's
    // primary physical/magic type for the resistance multiplier; untyped if the weapon defines none).
    Agent::Stats as = bm.getAgentStats(atk);
    int die = roll(as.superiority_die_size);

    Agent::Stats ts = bm.getAgentStats(secondary_idx);
    const auto weapons = bm.getAgentWeapons(atk);
    float mult = 1.0f;
    if (action.weapon_idx >= 0 && action.weapon_idx < static_cast<int>(weapons.size())) {
        const Weapon& w = weapons[static_cast<std::size_t>(action.weapon_idx)];
        if (!w.physicalDamageRolls.empty())
            mult = effectivePhysicalDamageMult(as, ts, w.physicalDamageRolls.front().type);
        else if (!w.magicDamageRolls.empty())
            mult = effectiveMagicDamageMult(as, ts, w.magicDamageRolls.front().type, false);
    }
    int dmg = std::max(0, static_cast<int>(static_cast<float>(die) * mult));

    res.condition_applied = true;
    res.extra_damage = dmg;
    int overflow = std::max(0, dmg - ts.temp_hp);
    ts.temp_hp = std::max(0, ts.temp_hp - dmg);
    ts.hp_cur  = std::clamp(ts.hp_cur - overflow, 0, ts.hp_max);
    res.extra_target_down = (ts.hp_cur <= 0);
    bm.setAgentStats(secondary_idx, ts);
    log_("Sweeping Attack: {} takes {} damage (superiority die {}{})",
         agentName(bm, secondary_idx), dmg, die, mult != 1.0f ? " x mult" : "");

    if (dmg > 0) {
        checkConcentrationOnDamage(bm, secondary_idx, dmg, atk);
        processDamageTaken(bm, secondary_idx, dmg);
    }
    if (res.extra_target_down && !bm.getAgentConditions(secondary_idx).unconscious &&
        !bm.getAgentConditions(secondary_idx).dead) {
        applyUnconscious(bm, secondary_idx);
    }
    return res;
}

int CombatEngine::applyRally(BattleMap& bm, int fighter_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (fighter_idx < 0 || fighter_idx >= n || target_idx < 0 || target_idx >= n) return 0;
    Agent::Stats fs = bm.getAgentStats(fighter_idx);
    const Resource* sd = fs.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) return 0;
    spendResource(bm, fighter_idx, "Superiority Dice", 1);

    const int amount = std::max(1, roll(fs.superiority_die_size) + dndMod(fs.cha));  // die + CHA mod (min 1)
    Agent::Stats ts = bm.getAgentStats(target_idx);
    grantTempHp(ts, amount, -1);   // max() semantics, non-rage source
    bm.setAgentStats(target_idx, ts);
    log_("{}: Rally grants {} Temporary HP to {} (Battle Master, 1 Superiority Die)",
         agentName(bm, fighter_idx), amount, agentName(bm, target_idx));
    return amount;
}

int CombatEngine::bardMantleOfInspiration(BattleMap& bm, int bard_idx,
                                          const std::vector<int>& targets) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (bard_idx < 0 || bard_idx >= n) return 0;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.lacksClass(CharacterClass::Bard) ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.classLevel(CharacterClass::Bard) < 3) {
        log_("{} cannot use Mantle of Inspiration (not a L3+ College of Glamour Bard)",
             agentName(bm, bard_idx));
        return 0;
    }
    const Resource* bi = bs.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) {
        log_("{} has no Bardic Inspiration use for Mantle of Inspiration", agentName(bm, bard_idx));
        return 0;
    }
    spendResource(bm, bard_idx, "Bardic Inspiration", 1);

    // Roll the Bardic Inspiration die ONCE; every recipient gets twice that roll.
    const int rolled = roll(bs.bardic_inspiration_die_size);
    const int thp    = 2 * rolled;
    const int cap    = std::max(1, dndMod(bs.cha));   // up to CHA mod creatures (min 1)

    int granted = 0;
    for (int t : targets) {
        if (granted >= cap) break;
        if (t < 0 || t >= n || t == bard_idx) continue;   // 2024: "other creatures", not self
        Agent::Stats ts = bm.getAgentStats(t);
        grantTempHp(ts, thp, -1);                          // max() semantics, non-rage source
        bm.setAgentStats(t, ts);
        log_("{}: Mantle of Inspiration grants {} Temporary HP to {}",
             agentName(bm, bard_idx), thp, agentName(bm, t));
        ++granted;
    }
    log_("{} weaves Mantle of Inspiration (rolled {} on d{}): {} Temporary HP to {} creature(s)",
         agentName(bm, bard_idx), rolled, bs.bardic_inspiration_die_size, thp, granted);
    return thp;
}

bool CombatEngine::applyFeintingAttack(BattleMap& bm, int fighter_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (fighter_idx < 0 || fighter_idx >= n || target_idx < 0 || target_idx >= n) return false;
    Agent::Stats fs = bm.getAgentStats(fighter_idx);
    const Resource* sd = fs.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) return false;
    spendResource(bm, fighter_idx, "Superiority Dice", 1);

    Agent::Conditions fc = bm.getAgentConditions(fighter_idx);
    fc.feint_target_idx = target_idx;
    bm.setAgentConditions(fighter_idx, fc);
    log_("{}: Feinting Attack vs {} — Advantage on your next attack this turn (+1 die on a hit)",
         agentName(bm, fighter_idx), agentName(bm, target_idx));
    return true;
}

bool CombatEngine::prepareQuickToss(BattleMap& bm, int fighter_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (fighter_idx < 0 || fighter_idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats fs = bm.getAgentStats(fighter_idx);
    const Resource* sd = fs.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) return false;
    spendResource(bm, fighter_idx, "Superiority Dice", 1);

    Agent::Conditions fc = bm.getAgentConditions(fighter_idx);
    fc.quick_toss_die_pending = true;
    bm.setAgentConditions(fighter_idx, fc);
    log_("{}: Quick Toss — the next thrown-weapon attack this turn adds a superiority die to damage",
         agentName(bm, fighter_idx));
    return true;
}

void CombatEngine::applyPrecisionAttackEffect(BattleMap& bm, const Attack& action, AttackResult& result) noexcept
{
    const auto& agents = bm.placedAgents();
    const int atk = action.attacker_idx, tgt = action.target_idx;
    if (atk < 0 || atk >= static_cast<int>(agents.size()) ||
        tgt < 0 || tgt >= static_cast<int>(agents.size())) return;

    Agent::Conditions ac = bm.getAgentConditions(atk);
    if (!ac.maneuver_precision_available) return;

    Agent::Stats as = bm.getAgentStats(atk);
    Resource* sd = as.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) return;

    // Spend 1 die and roll it
    int die_roll = roll(as.superiority_die_size);
    sd->spend(1);
    bm.setAgentStats(atk, as);

    result.total_roll += die_roll;
    log_("{}: Precision Attack +{} -> {} vs AC {}", agentName(bm, atk), die_roll, result.total_roll, result.target_ac);

    ac.maneuver_precision_available = false;
    bm.setAgentConditions(atk, ac);

    if (result.hit || result.fumble || result.total_roll < result.target_ac) return;

    // Miss becomes a hit — roll and apply weapon damage (mirrors applyGuidedStrike)
    result.hit = true;
    Agent::Stats atk_g = bm.getAgentStats(atk);
    Agent::Stats tgt_g = bm.getAgentStats(tgt);
    auto weapons = bm.getAgentWeapons(atk);
    const int wi_g = std::clamp(action.weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
    const Weapon& w = weapons[static_cast<std::size_t>(wi_g)];
    rollDamage(w, atk_g, tgt_g, result);
    result.hp_before = tgt_g.hp_cur;
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_g.temp_hp);
    tgt_g.temp_hp = std::max(0, tgt_g.temp_hp - dmg);
    tgt_g.hp_cur  = std::clamp(tgt_g.hp_cur - overflow, 0, tgt_g.hp_max);
    result.hp_after  = tgt_g.hp_cur;
    result.target_down = (tgt_g.hp_cur <= 0);
    bm.setAgentStats(tgt, tgt_g);
    log_("Precision Attack turns a miss into a hit: {} damage to {}", dmg, agentName(bm, tgt));
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, tgt, dmg);
        processDamageTaken(bm, tgt, dmg);
    }
}

void CombatEngine::applyGuidedStrike(BattleMap& bm, const Attack& action, int cleric_idx, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx, tgt = action.target_idx;
    if (atk < 0 || atk >= n || tgt < 0 || tgt >= n || cleric_idx < 0 || cleric_idx >= n) return;

    Agent::Stats cleric = bm.getAgentStats(cleric_idx);
    if (cleric.lacksClass(CharacterClass::Cleric) ||
        cleric.cleric_subclass != WarDomain || cleric.classLevel(CharacterClass::Cleric) < 3) return;
    Resource* cd = cleric.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return;

    // An ally cleric (not the attacker) also spends a Reaction and must be within 30 ft.
    if (cleric_idx != atk) {
        Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
        if (!canTakeReaction(cc)) return;
        const Cell co = agents[static_cast<std::size_t>(cleric_idx)].origin;
        const Cell ao = agents[static_cast<std::size_t>(atk)].origin;
        const double dx = co.col - ao.col, dy = co.row - ao.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) return;
        cc.reaction_used = true;
        bm.setAgentConditions(cleric_idx, cc);
    }

    cd->spend(1);
    bm.setAgentStats(cleric_idx, cleric);

    result.total_roll += 10;
    log_("{}: Guided Strike +10 -> {} vs AC {}", agentName(bm, cleric_idx), result.total_roll, result.target_ac);

    Agent::Conditions atk_cond_g = bm.getAgentConditions(atk);
    atk_cond_g.guided_strike_available = false;
    bm.setAgentConditions(atk, atk_cond_g);

    // Still a miss (or already a hit) — only the +10 is recorded.
    if (result.hit || result.fumble || result.total_roll < result.target_ac) return;

    // Now meets AC — turn it into a hit and roll/apply weapon damage.
    result.hit = true;
    Agent::Stats atk_stats_g = bm.getAgentStats(atk);
    Agent::Stats tgt_stats_g = bm.getAgentStats(tgt);
    auto weapons = bm.getAgentWeapons(atk);
    const int wi_g2 = std::clamp(action.weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
    const Weapon& w = weapons[static_cast<std::size_t>(wi_g2)];
    rollDamage(w, atk_stats_g, tgt_stats_g, result);   // miss was not a crit → normal damage
    result.hp_before = tgt_stats_g.hp_cur;
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_stats_g.temp_hp);
    tgt_stats_g.temp_hp = std::max(0, tgt_stats_g.temp_hp - dmg);
    tgt_stats_g.hp_cur  = std::clamp(tgt_stats_g.hp_cur - overflow, 0, tgt_stats_g.hp_max);
    result.hp_after = tgt_stats_g.hp_cur;
    result.target_down = (tgt_stats_g.hp_cur <= 0);
    bm.setAgentStats(tgt, tgt_stats_g);
    log_("Guided Strike turns a miss into a hit: {} damage to {}", dmg, agentName(bm, tgt));
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, tgt, dmg);
        processDamageTaken(bm, tgt, dmg);
    }
}

// Boon of Combat Prowess (Peerless Aim) eligibility — path-agnostic gate shared by the NPC auto-fire
// (maybePeerlessAim), the PC deferred-flag arming (applyAttackResult), and applyPeerlessAim. The
// attacker must hold the boon, be alive, and not have used the once-per-turn miss→hit yet. The caller
// confirms the attack actually missed.
bool CombatEngine::canPeerlessAim(const BattleMap& bm, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return false;
    const Agent::Stats as = bm.getAgentStats(attacker_idx);
    if (as.hp_cur <= 0 || !as.hasFeat("Boon of Combat Prowess")) return false;
    return !bm.getAgentConditions(attacker_idx).peerless_aim_used;
}

// Boon of Combat Prowess (Peerless Aim) — post-hoc GUI entry. After a PC misses, the GUI offers this;
// it turns the miss into a hit, rolls + applies weapon damage, and updates result (mirrors
// applyGuidedStrike's damage application). Consumes the once-per-turn use.
void CombatEngine::applyPeerlessAim(BattleMap& bm, const Attack& action, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx, tgt = action.target_idx;
    if (atk < 0 || atk >= n || tgt < 0 || tgt >= n) return;
    if (!canPeerlessAim(bm, atk)) return;
    if (result.hit) return;                                // nothing to promote (already a hit)

    // Consume the once-per-turn use and clear the deferred flag.
    Agent::Conditions ac = bm.getAgentConditions(atk);
    ac.peerless_aim_used      = true;
    ac.peerless_aim_available = false;
    bm.setAgentConditions(atk, ac);

    result.hit = true;
    log_("{} takes Peerless Aim: the miss becomes a hit instead", agentName(bm, atk));

    Agent::Stats atk_stats_p = bm.getAgentStats(atk);
    Agent::Stats tgt_stats_p = bm.getAgentStats(tgt);
    auto weapons = bm.getAgentWeapons(atk);
    if (weapons.empty()) return;
    const int wi_p = std::clamp(action.weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
    const Weapon& w = weapons[static_cast<std::size_t>(wi_p)];
    rollDamage(w, atk_stats_p, tgt_stats_p, result, action.no_ability_damage);  // miss was not a crit → normal damage
    result.hp_before = tgt_stats_p.hp_cur;
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_stats_p.temp_hp);
    tgt_stats_p.temp_hp = std::max(0, tgt_stats_p.temp_hp - dmg);
    tgt_stats_p.hp_cur  = std::clamp(tgt_stats_p.hp_cur - overflow, 0, tgt_stats_p.hp_max);
    result.hp_after = tgt_stats_p.hp_cur;
    result.target_down = (tgt_stats_p.hp_cur <= 0);
    bm.setAgentStats(tgt, tgt_stats_p);
    log_("Peerless Aim turns a miss into a hit: {} damage to {}", dmg, agentName(bm, tgt));
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, tgt, dmg);
        processDamageTaken(bm, tgt, dmg);
    }
}

AttackResult CombatEngine::applyRecklessReroll(BattleMap& bm, int attacker_idx,
                                               int target_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n)
        return AttackResult{};

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.reckless_reroll_available) return AttackResult{};   // only when the miss offered it

    // Commit to Reckless for the round (the downside): enemies have advantage vs this Barbarian
    // until the start of its next turn. reckless_attack is cleared at that turn's start (Agent::turn).
    ac.reckless_attack           = true;
    ac.reckless_reroll_available = false;
    bm.setAgentConditions(attacker_idx, ac);
    log_("{} attacks recklessly — rerolling with advantage (attacks against them have advantage "
         "until the start of their next turn)", agentName(bm, attacker_idx));

    // Re-resolve the same attack; reckless_attack now grants advantage on the melee roll, and
    // executeAction applies damage/riders on a hit. The eligibility guard (!reckless_attack) is now
    // false, so this reroll cannot itself re-trigger another reckless reroll.
    return executeAction(bm, Attack{attacker_idx, target_idx, weapon_idx});
}

AttackResult CombatEngine::applyRiposte(BattleMap& bm, int defender_idx,
                                        int attacker_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (defender_idx < 0 || defender_idx >= n || attacker_idx < 0 || attacker_idx >= n)
        return AttackResult{};

    Agent::Conditions dc = bm.getAgentConditions(defender_idx);
    if (!dc.riposte_available) return AttackResult{};   // only when the miss offered it

    Agent::Stats ds = bm.getAgentStats(defender_idx);
    const Resource* sd = ds.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) {                      // shouldn't happen (canRiposte checked), but be safe
        dc.riposte_available = false;
        bm.setAgentConditions(defender_idx, dc);
        return AttackResult{};
    }
    const int die_size = ds.superiority_die_size;

    // Spend the reaction + clear the flag, then spend 1 Superiority Die.
    dc.riposte_available = false;
    dc.reaction_used     = true;
    bm.setAgentConditions(defender_idx, dc);
    spendResource(bm, defender_idx, "Superiority Dice", 1);
    log_("{} ripostes {} (reaction + 1 Superiority Die)",
         agentName(bm, defender_idx), agentName(bm, attacker_idx));

    // The riposte: a fresh melee attack back at the attacker. (Atomic executeAction, like
    // applyRecklessReroll — the riposte does not open a separate GUI reaction window.)
    AttackResult r = executeAction(bm, Attack{defender_idx, attacker_idx, weapon_idx});

    // On a hit, add one Superiority Die to the damage (RAW 2024). Added directly to total_damage like
    // the Divine Fury / Berserker Frenzy bonus dice; HP/concentration applied as in applyPsionicStrikeEffect.
    if (r.hit) {
        const int die = roll(die_size);
        Agent::Stats as = bm.getAgentStats(attacker_idx);
        r.total_damage += die;
        r.damage_breakdown.push_back({"riposte", die});
        const int overflow = std::max(0, die - as.temp_hp);
        as.temp_hp = std::max(0, as.temp_hp - die);
        as.hp_cur  = std::clamp(as.hp_cur - overflow, 0, as.hp_max);
        r.hp_after    = as.hp_cur;
        r.target_down = (as.hp_cur <= 0);
        bm.setAgentStats(attacker_idx, as);
        log_("Riposte: +{} Superiority Die damage to {}", die, agentName(bm, attacker_idx));
        if (die > 0) {
            checkConcentrationOnDamage(bm, attacker_idx, die);
            processDamageTaken(bm, attacker_idx, die);
        }
    }
    return r;
}

AttackResult CombatEngine::applySentinelGuard(BattleMap& bm, int sentinel_idx,
                                              int attacker_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (sentinel_idx < 0 || sentinel_idx >= n || attacker_idx < 0 || attacker_idx >= n)
        return AttackResult{};
    Agent::Conditions sc = bm.getAgentConditions(sentinel_idx);
    if (!canTakeReaction(sc)) return AttackResult{};      // re-validate (canSentinelGuard checked, but be safe)

    log_("Sentinel Guardian: {} reacts — melee attack vs {}",
         agentName(bm, sentinel_idx), agentName(bm, attacker_idx));

    // The guard counter-attack: a fresh melee attack at the attacker. resolving_sentinel_guard_ keeps
    // this strike from re-opening the OnAllyAttacked window (a guard does not provoke its own guard).
    resolving_sentinel_guard_ = true;
    AttackResult r = executeAction(bm, Attack{sentinel_idx, attacker_idx, weapon_idx});
    resolving_sentinel_guard_ = false;

    // Spend the reaction (re-fetch: executeAction may have mutated the Sentinel's conditions).
    sc = bm.getAgentConditions(sentinel_idx);
    sc.reaction_used = true;
    bm.setAgentConditions(sentinel_idx, sc);
    return r;
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
    resolving_sentinel_guard_ = true;
    AttackResult r = executeAction(bm, Attack{paladin_idx, attacker_idx, weapon_idx});
    resolving_sentinel_guard_ = false;

    // Spend the reaction (re-fetch: executeAction may have mutated the paladin's conditions).
    pc = bm.getAgentConditions(paladin_idx);
    pc.reaction_used = true;
    bm.setAgentConditions(paladin_idx, pc);
    return r;
}

ToppleResult CombatEngine::applyTopple(BattleMap& bm, int attacker_idx, int target_idx, int weapon_idx) noexcept
{
    ToppleResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.topple_available) return res;      // only after a qualifying Topple hit
    ac.topple_available = false;
    ac.topple_used_this_turn = true;           // mark as used (once per turn)
    bm.setAgentConditions(attacker_idx, ac);
    res.valid = true;

    Agent::Stats as = bm.getAgentStats(attacker_idx);
    Agent::Stats ts = bm.getAgentStats(target_idx);

    // Save DC = 8 + the attacker's attack-ability modifier + proficiency bonus.
    int dc = 8 + as.prof_bonus;
    const auto& weapons = agents[static_cast<std::size_t>(attacker_idx)].weapons;
    if (!weapons.empty()) {
        int wi = std::clamp(weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
        dc += damageAbilityMod(weapons[static_cast<std::size_t>(wi)], as);
    }
    res.save_dc = dc;

    // Target CON save (with proficiency), floored correctly for odd negative scores.
    int mod = (ts.con - 10) / 2;
    if (ts.con < 10 && (ts.con - 10) % 2 != 0) --mod;
    if (ts.save_prof_con) mod += ts.prof_bonus;
    res.save_roll = roll(20, mod);

    if (res.save_roll < dc) {
        applyProne(bm, target_idx);
        res.toppled = true;
        log_("{} is knocked Prone (Topple — save {} vs DC {})",
             agentName(bm, target_idx), res.save_roll, dc);
    } else {
        log_("{} resists Topple (save {} vs DC {})",
             agentName(bm, target_idx), res.save_roll, dc);
    }
    return res;
}

StunningStrikeResult CombatEngine::applyStunningStrike(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    StunningStrikeResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.stunning_strike_available) return res;
    ac.stunning_strike_available = false;
    ac.stunning_strike_used = true;
    bm.setAgentConditions(attacker_idx, ac);
    res.valid = true;

    // Spend 1 Focus Point
    Agent::Stats as = bm.getAgentStats(attacker_idx);
    auto fp = as.getResource("Focus Points");
    if (fp && fp->current > 0) {
        spendResource(bm, attacker_idx, "Focus Points", 1);
    }

    Agent::Stats ts = bm.getAgentStats(target_idx);

    // Save DC = 8 + attacker's DEX mod + proficiency bonus
    int dex_mod = (as.dex - 10) / 2;
    if (as.dex < 10 && (as.dex - 10) % 2 != 0) --dex_mod;
    int dc = 8 + dex_mod + as.prof_bonus;
    res.save_dc = dc;

    // Target CON save (with proficiency), floored correctly for odd negative scores
    int con_mod = (ts.con - 10) / 2;
    if (ts.con < 10 && (ts.con - 10) % 2 != 0) --con_mod;
    if (ts.save_prof_con) con_mod += ts.prof_bonus;
    res.save_roll = roll(20, con_mod);

    if (res.save_roll < dc) {
        // Apply Stunned condition for 1 turn
        ActiveAgentCondition cond;
        cond.agent_idx = target_idx;
        cond.caster_idx = attacker_idx;
        cond.condition_name = "Stunned";
        cond.turns_remaining = 1;
        [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
        res.stunned = true;
        log_("{} is Stunned (Stunning Strike — save {} vs DC {})",
             agentName(bm, target_idx), res.save_roll, dc);
    } else {
        log_("{} resists Stunning Strike (save {} vs DC {})",
             agentName(bm, target_idx), res.save_roll, dc);
    }
    return res;
}

OpenHandRiderResult CombatEngine::applyOpenHandRider(BattleMap& bm, int attacker_idx, int target_idx, int option) noexcept
{
    OpenHandRiderResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.open_hand_rider_available) return res;

    bm.setAgentConditions(attacker_idx, ac);
    res.valid = true;
    res.option = option;

    // Spend 1 Focus Point
    Agent::Stats as = bm.getAgentStats(attacker_idx);
    auto fp = as.getResource("Focus Points");
    if (fp && fp->current > 0) {
        spendResource(bm, attacker_idx, "Focus Points", 1);
    }

    Agent::Stats ts = bm.getAgentStats(target_idx);

    if (option == 0) {
        // Knockdown: STR save DC = 8 + attacker's DEX mod + prof, on failure apply Prone
        int dex_mod = (as.dex - 10) / 2;
        if (as.dex < 10 && (as.dex - 10) % 2 != 0) --dex_mod;
        int dc = 8 + dex_mod + as.prof_bonus;
        res.knockdown_save_dc = dc;

        // Target STR save (with proficiency)
        int str_mod = (ts.str - 10) / 2;
        if (ts.str < 10 && (ts.str - 10) % 2 != 0) --str_mod;
        if (ts.save_prof_str) str_mod += ts.prof_bonus;
        res.knockdown_save_roll = roll(20, str_mod);

        if (res.knockdown_save_roll < dc) {
            // Apply Prone condition for 1 turn
            ActiveAgentCondition cond;
            cond.agent_idx = target_idx;
            cond.caster_idx = attacker_idx;
            cond.condition_name = "Prone";
            cond.turns_remaining = 1;
            [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
            res.target_knocked_prone = true;
            log_("{} is knocked Prone (Open Hand Knockdown — save {} vs DC {})",
                 agentName(bm, target_idx), res.knockdown_save_roll, dc);
        } else {
            log_("{} resists Open Hand Knockdown (save {} vs DC {})",
                 agentName(bm, target_idx), res.knockdown_save_roll, dc);
        }
    } else if (option == 1) {
        // Push: forceMoveAgent for 5 feet
        const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
        int cells_moved = bm.forceMoveAgent(target_idx, origin, 5);
        res.push_distance = cells_moved * 5;  // Convert cells to feet
        log_("{} is pushed back {} feet (Open Hand Push)",
             agentName(bm, target_idx), res.push_distance);
    } else if (option == 2) {
        // Deny Reaction: set reaction_used on target
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        tc.reaction_used = true;
        bm.setAgentConditions(target_idx, tc);
        res.reaction_denied = true;
        log_("{} cannot use a reaction (Open Hand Deny Reaction)",
             agentName(bm, target_idx));
    }

    return res;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Reaction / utility riders
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::applyProtectiveField(BattleMap& bm, int defender_idx, int damage_taken) noexcept
{
    const auto& agents = bm.placedAgents();
    if (defender_idx < 0 || defender_idx >= static_cast<int>(agents.size())) return -1;
    if (damage_taken <= 0) return -1;

    Agent::Stats stats = bm.getAgentStats(defender_idx);
    if (stats.lacksClass(CharacterClass::Fighter) ||
        stats.fighter_subclass != PsiWarriorPath || stats.classLevel(CharacterClass::Fighter) < 3) return -1;

    Agent::Conditions cond = bm.getAgentConditions(defender_idx);
    if (!canTakeReaction(cond)) return -1;

    const Resource* ped = stats.getResource("Psionic Energy");
    if (!ped || ped->current <= 0) return -1;

    // Reduction = one Psionic Energy die + INT mod (the mod never reduces below the die roll).
    int int_mod = (stats.intel - 10) / 2;
    if (stats.intel < 10 && (stats.intel - 10) % 2 != 0) --int_mod;
    int reduction = roll(stats.psionic_die_size) + std::max(0, int_mod);
    int healed = std::min(reduction, damage_taken);  // only restore what this hit actually cost

    // Spend the die + the reaction, then heal back the prevented damage.
    spendResource(bm, defender_idx, "Psionic Energy", 1);
    cond.reaction_used = true;
    bm.setAgentConditions(defender_idx, cond);
    healAgent(bm, defender_idx, healed);

    log_("{} uses Protective Field: prevents {} damage (rolled reduction {})",
         agentName(bm, defender_idx), healed, reduction);
    return healed;
}

int CombatEngine::applyInterception(BattleMap& bm, int interceptor_idx, int target_idx, int damage_taken) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (interceptor_idx < 0 || interceptor_idx >= n || target_idx < 0 || target_idx >= n) return -1;
    if (damage_taken <= 0) return -1;

    Agent::Stats istats = bm.getAgentStats(interceptor_idx);
    if (!istats.hasFeat("Interception")) return -1;

    Agent::Conditions ic = bm.getAgentConditions(interceptor_idx);
    if (!canTakeReaction(ic)) return -1;                       // re-validate (canIntercept checked; be safe)

    // Reduction = 1d10 + the interceptor's Proficiency Bonus; never restore more than the hit cost.
    int reduction = roll(10) + istats.prof_bonus;
    int prevented = std::min(reduction, damage_taken);

    // Spend the reaction, then heal back the prevented damage to the target.
    ic.reaction_used = true;
    bm.setAgentConditions(interceptor_idx, ic);
    healAgent(bm, target_idx, prevented);

    log_("{} uses Interception: prevents {} damage to {} (rolled reduction {})",
         agentName(bm, interceptor_idx), prevented, agentName(bm, target_idx), reduction);
    return prevented;
}

int CombatEngine::applyTelekineticMovement(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()) ||
        target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Fighter) ||
        stats.fighter_subclass != PsiWarriorPath || stats.classLevel(CharacterClass::Fighter) < 3) return -1;

    const Resource* tk = stats.getResource("Telekinetic Movement");
    if (!tk || tk->current <= 0) return -1;

    // Push the target up to 30 ft straight away from the Psi Warrior.
    const Cell origin = agents[static_cast<std::size_t>(idx)].origin;
    int feet = bm.forceMoveAgent(target_idx, origin, 30) * 5;

    spendResource(bm, idx, "Telekinetic Movement", 1);
    if (feet > 0)
        log_("{} telekinetically moves {} {} ft",
             agentName(bm, idx), agentName(bm, target_idx), feet);
    return feet;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Bonus attacks & grapple
// ─────────────────────────────────────────────────────────────────────────────

FlurryResult CombatEngine::executeFlurryOfBlows(BattleMap& bm, int attacker_idx, int target_idx, int rider_option) noexcept
{
    FlurryResult result;
    const Agent::Stats& stats = bm.getAgentStats(attacker_idx);

    // L10 Heightened Focus: Flurry grants 3 strikes instead of 2
    int num_flurry_attacks = (stats.classLevel(CharacterClass::Monk) >= 10 && stats.hasClass(CharacterClass::Monk)) ? 3 : 2;

    // L11 Warrior of Mercy — Flurry of Healing and Harm: each Flurry strike that hits also delivers a free
    // Hand of Harm (no Focus Point), capped at once per target by applyHandOfHarmEffect itself.
    const bool mercy_flurry_harm =
        stats.hasClass(CharacterClass::Monk) &&
        stats.monk_subclass  == WarriorOfMercyPath && stats.classLevel(CharacterClass::Monk) >= 11;

    auto apply_riders = [&](AttackResult& atk_result, OpenHandRiderResult& rider) {
        if (!atk_result.valid || !atk_result.hit) return;
        if (rider_option >= 0 && rider_option <= 2) {
            if (bm.getAgentConditions(attacker_idx).open_hand_rider_available)
                rider = applyOpenHandRider(bm, attacker_idx, target_idx, rider_option);
        }
        if (mercy_flurry_harm && bm.getAgentConditions(attacker_idx).hand_of_harm_available)
            applyHandOfHarmEffect(bm, attacker_idx, target_idx, atk_result);
    };

    // Execute first attack
    Attack atk1(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk1.is_offhand = true;
    atk1.attack_slot = "bonus";
    result.attack1 = executeAction(bm, atk1);
    apply_riders(result.attack1, result.rider1);

    // Execute second attack
    Attack atk2(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk2.is_offhand = true;
    atk2.attack_slot = "bonus";
    result.attack2 = executeAction(bm, atk2);
    apply_riders(result.attack2, result.rider2);

    // Execute third attack if L10+ (Heightened Focus)
    if (num_flurry_attacks >= 3) {
        Attack atk3(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
        atk3.is_offhand = true;
        atk3.attack_slot = "bonus";
        result.attack3 = executeAction(bm, atk3);
        apply_riders(result.attack3, result.rider3);
    }

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    ac.open_hand_rider_available = false;
    ac.hand_of_harm_available = false;
    bm.setAgentConditions(attacker_idx, ac);
    return result;
}

bool CombatEngine::consumeBonusAttack(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.bonus_attacks_remaining <= 0) return false;

    stats.bonus_attacks_remaining--;
    bm.setAgentStats(agent_idx, stats);

    if (stats.bonus_attacks_remaining > 0) {
        log_("{} has {} bonus attack{} remaining",
             agentName(bm, agent_idx), stats.bonus_attacks_remaining,
             stats.bonus_attacks_remaining == 1 ? "" : "s");
        return true;
    }
    return false;
}

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

ShoveResult CombatEngine::applyTelekineticShove(BattleMap& bm, int caster_idx, int target_idx) noexcept
{
    ShoveResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size()) ||
        target_idx < 0 || target_idx >= static_cast<int>(agents.size()) ||
        caster_idx == target_idx) {
        result.log_message = "Invalid Telekinetic Shove.";
        return result;
    }

    auto& caster = agents[static_cast<std::size_t>(caster_idx)];
    auto& target = agents[static_cast<std::size_t>(target_idx)];

    // Range 30 ft (6 cells, Chebyshev).
    int dx = std::abs(target.origin.col - caster.origin.col);
    int dy = std::abs(target.origin.row - caster.origin.row);
    if (std::max(dx, dy) > 6) {
        result.log_message = "Target is beyond 30 feet.";
        return result;
    }

    const Agent::Stats cs = getAgentStats(bm, caster_idx);
    auto mod = [](int score) {
        int m = (score - 10) / 2;
        if (score < 10 && (score - 10) % 2 != 0) --m;
        return m;
    };
    // DC = 8 + PB + the best of INT/WIS/CHA (the feat's spellcasting-ability choice; we take the
    // caster's strongest mental modifier rather than store a per-character pick).
    int spell_mod = std::max({mod(cs.intel), mod(cs.wis), mod(cs.cha)});
    int dc = 8 + cs.prof_bonus + spell_mod;

    const Agent::Stats ts = getAgentStats(bm, target_idx);
    int str_mod = mod(ts.str);
    int save_d20 = roll(20);
    int save_total = save_d20 + str_mod + (ts.save_prof_str ? ts.prof_bonus : 0);

    result.valid = true;
    result.attacker_roll = dc;
    result.defender_roll = save_total;

    if (save_total >= dc) {
        result.success = false;
        result.log_message = "\"" + std::string(target.agent->name()) +
                             "\" resists the Telekinetic Shove (" + std::to_string(save_total) +
                             " vs DC " + std::to_string(dc) + ").";
        log_("{}", result.log_message);
        return result;
    }

    int cells_moved = bm.forceMoveAgent(target_idx, caster.origin, 5);
    result.push_ft_applied = cells_moved * 5;
    result.success = (result.push_ft_applied > 0);
    result.log_message = "\"" + std::string(caster.agent->name()) + "\" telekinetically shoves \"" +
                         std::string(target.agent->name()) + "\" " +
                         std::to_string(result.push_ft_applied) + " feet (save " +
                         std::to_string(save_total) + " vs DC " + std::to_string(dc) + ").";
    log_("{}", result.log_message);
    return result;
}

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

// ─────────────────────────────────────────────────────────────────────────────
//  OnTurnStartNearby reactions (beginTurn)
//  When a creature starts its turn within a reactor's 5 ft reach, the reactor may spend its reaction:
//  Branches of the Tree → the creature makes a STR save vs the reactor's spell save DC or is Grappled.
//  A post-effect interrupt that does not alter the TurnStartResult, so the flow is the simplest of the
//  seven windows (no pre-roll / re-evaluation). The apply rolls directly → no nested window opens.
//  (Sentinel is NOT here — RAW it provokes an OA when a creature Disengages out of reach; that lives in
//  detectProvokes' LeftReach path, gated on Agent::Stats::has_sentinel.)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canBranchesOfTree(const BattleMap& bm, int reactor, int source) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n || source < 0 || source >= n || reactor == source) return false;
    if (bm.isAgentOnDeck(reactor)) return false;          // On Deck reserves take no reactions until deployed
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (!s.has_branches_of_the_tree) return false;
    if (s.hp_cur <= 0) return false;
    const Agent::Conditions c = bm.getAgentConditions(reactor);
    if (!canTakeReaction(c)) return false;
    if (!c.raging) return false;                                 // "While your Rage is active"
    if (!canPerceiveTarget(bm, reactor, source)) return false;   // "a creature you can see"
    // "starts its turn within 30 feet of you" — 30 ft = 6 cells (Chebyshev footprint distance).
    const auto in_range = threateningAgents(bm, source, 6);
    return std::find(in_range.begin(), in_range.end(), reactor) != in_range.end();
}

std::vector<int> CombatEngine::turnStartReactors(const BattleMap& bm, int source) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    std::vector<int> out;
    // Vitality of the Tree fires on the source's OWN turn start, so the source itself is a reactor.
    if (canVitalityOfTheTree(bm, source)) out.push_back(source);
    for (int i = 0; i < n; ++i) {
        if (i == source) continue;
        if (canBranchesOfTree(bm, i, source)) out.push_back(i);
    }
    return out;
}

std::vector<ReactionOption> CombatEngine::turnStartOptions(const BattleMap& bm, int reactor, int source) const
{
    std::vector<ReactionOption> opts;
    if (reactor == source) {
        // The source's own turn-start self-option (free, once per turn — needs a target pick).
        if (canVitalityOfTheTree(bm, source))
            opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                          "Vitality of the Tree — grant Xd6 temp HP (free)",
                                          "VitalityOfTheTree"});
    } else if (canBranchesOfTree(bm, reactor, source)) {
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Branches of the Tree — STR save or teleported + Speed 0 (reaction)",
                                      "BranchesOfTheTree"});
    }
    opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

bool CombatEngine::applyBranchesOfTree(BattleMap& bm, int reactor, int source)
{
    if (!canBranchesOfTree(bm, reactor, source)) return false;
    Agent::Conditions rc = bm.getAgentConditions(reactor);
    rc.reaction_used = true;                                          // spend the reaction
    bm.setAgentConditions(reactor, rc);

    // An ally is a willing target: no STR save, and no Speed-0 penalty — Branches is used purely to
    // reposition them. Only an enemy must save, and only an enemy suffers Speed 0 on a failed save.
    const bool ally = areAllies(bm, reactor, source);
    if (!ally) {
        const Agent::Stats rs = bm.getAgentStats(reactor);
        const int dc       = spellSaveDcFromAbility(rs, SaveStr);   // 8 + PB + STR mod (2024 PHB)
        const int save_mod = saveModFor(bm, source, SaveStr);      // incl. Aura of Protection
        const int d20      = roll(20);
        const int total    = d20 + save_mod;
        log_("{} uses Branches of the Tree on {} (reaction): STR save {} {:+} = {} vs DC {}",
             agentName(bm, reactor), agentName(bm, source), d20, save_mod, total, dc);
        if (total >= dc) {
            log_("{} resists the branches", agentName(bm, source));
            return false;
        }
    } else {
        log_("{} uses Branches of the Tree to reposition ally {} (willing — no save)",
             agentName(bm, reactor), agentName(bm, source));
    }

    // Teleport the source to an unoccupied space within 5 ft of the reactor (or, failing that, the
    // nearest unoccupied space). An enemy that failed its save also has its Speed set to 0 until the
    // end of the current turn (an ally keeps its movement).
    const auto& agents = bm.placedAgents();
    const Cell rorigin = agents[static_cast<std::size_t>(reactor)].origin;
    const int  rsize   = agents[static_cast<std::size_t>(reactor)].agent->getSize();
    const int  ssize   = agents[static_cast<std::size_t>(source)].agent->getSize();

    // Does an origin fit the source's whole footprint on passable, unoccupied terrain?
    auto fitsFree = [&](Cell o) -> bool {
        for (int dc2 = 0; dc2 < ssize; ++dc2)
            for (int dr2 = 0; dr2 < ssize; ++dr2)
                if (!isValidTeleportDestination(bm, o.col + dc2, o.row + dr2))
                    return false;
        for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
            if (i == source) continue;
            if (agents[static_cast<std::size_t>(i)].agent->getStats().hp_cur <= 0) continue;
            const Cell oo = agents[static_cast<std::size_t>(i)].origin;
            const int  os = agents[static_cast<std::size_t>(i)].agent->getSize();
            const bool overlap = !(o.col + ssize - 1 < oo.col || oo.col + os - 1 < o.col ||
                                   o.row + ssize - 1 < oo.row || oo.row + os - 1 < o.row);
            if (overlap) return false;
        }
        return true;
    };
    // Chebyshev gap (in cells) between the source footprint placed at `o` and the reactor footprint.
    auto chebFoot = [&](Cell o) -> int {
        const int dx = std::max({rorigin.col - (o.col + ssize - 1), o.col - (rorigin.col + rsize - 1), 0});
        const int dy = std::max({rorigin.row - (o.row + ssize - 1), o.row - (rorigin.row + rsize - 1), 0});
        return std::max(dx, dy);
    };

    // Scan a bounded box around the reactor; pick the nearest fitting free origin (prefers ≤5 ft).
    constexpr int kReach = 8;
    Cell dest{-1, -1};
    int best_d = 1 << 30;
    for (int c = rorigin.col - rsize - kReach; c <= rorigin.col + rsize + kReach; ++c) {
        for (int r = rorigin.row - rsize - kReach; r <= rorigin.row + rsize + kReach; ++r) {
            const Cell cand{c, r};
            if (!fitsFree(cand)) continue;
            const int d = chebFoot(cand);
            if (d < best_d) { best_d = d; dest = cand; }
        }
    }

    if (dest.col >= 0) {
        (void)teleportAgent(bm, source, dest.col, dest.row);
        log_("{} is yanked by the branches to ({}, {})", agentName(bm, source), dest.col, dest.row);
    } else {
        log_("{} has no space to be teleported by the branches", agentName(bm, source));
    }

    // Speed 0 until the end of the current turn (enemies only — an ally keeps moving). The GUI gate is
    // canAgentMove(branches_speed_zeroed); also zero the engine + agent budgets so the auto/RL path
    // (no per-turn re-seed) honors it now.
    if (!ally) {
        Agent::Conditions sc = bm.getAgentConditions(source);
        sc.branches_speed_zeroed = true;
        bm.setAgentConditions(source, sc);
        walkRemaining_[source]   = 0;
        flyRemaining_[source]    = 0;
        swimRemaining_[source]   = 0;
        burrowRemaining_[source] = 0;
        agents[static_cast<std::size_t>(source)].agent->initMovement(0, 0, 0, 0);
        log_("{}'s Speed is reduced to 0 until the end of its turn", agentName(bm, source));
    }
    return true;
}

// ── World Tree: Vitality of the Tree (self-option on the Barbarian's own turn start) ──────────────
// Unlike Branches (a reaction to another creature's turn), this fires on the source's OWN turn, so the
// window offers the source itself this option. It is free (not the reaction) but once per turn.

bool CombatEngine::canVitalityOfTheTree(const BattleMap& bm, int source) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (source < 0 || source >= n) return false;
    if (bm.isAgentOnDeck(source)) return false;           // On Deck reserves take no reactions until deployed
    const Agent::Stats s = bm.getAgentStats(source);
    if (s.lacksClass(Barbarian) || s.barbarian_subclass != WorldTreePath) return false;
    if (s.classLevel(CharacterClass::Barbarian) < 3 || s.hp_cur <= 0) return false;
    const Agent::Conditions c = bm.getAgentConditions(source);
    if (!c.raging || c.vitality_used_this_turn || c.incapacitated) return false;
    // At least one other living creature within 10 ft (2 cells) to receive the temp HP.
    return !threateningAgents(bm, source, 2).empty();
}

bool CombatEngine::applyVitalityOfTheTree(BattleMap& bm, int source, int target)
{
    if (!canVitalityOfTheTree(bm, source)) return false;
    const auto in_range = threateningAgents(bm, source, 2);
    if (std::find(in_range.begin(), in_range.end(), target) == in_range.end()) return false;  // target not within 10 ft

    const Agent::Stats ss = bm.getAgentStats(source);
    const int dice = std::max(1, getRageDamageBonus(ss.classLevel(CharacterClass::Barbarian)));
    int amount = 0;
    for (int i = 0; i < dice; ++i) amount += roll(6);

    Agent::Stats ts = bm.getAgentStats(target);
    grantTempHp(ts, amount, source);                                  // max() semantics + rage provenance
    bm.setAgentStats(target, ts);

    Agent::Conditions sc = bm.getAgentConditions(source);
    sc.vitality_used_this_turn = true;                                // free, once per turn (NOT the reaction)
    bm.setAgentConditions(source, sc);

    log_("{} uses Vitality of the Tree on {}: {}d6 = {} temp HP",
         agentName(bm, source), agentName(bm, target), dice, amount);
    return true;
}

void CombatEngine::applyTurnStartReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // Skip / invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;                                     // Skip
    if (opt.feature == "BranchesOfTheTree") (void)applyBranchesOfTree(bm, ctx.reactor_idx, ctx.source_idx);
    else if (opt.feature == "VitalityOfTheTree")
        // Self-option (reactor == source); resp.target_idx is the chosen creature within 10 ft.
        (void)applyVitalityOfTheTree(bm, ctx.source_idx, resp.target_idx);
}

FlowStatus CombatEngine::advanceTurnStart(BattleMap& bm)
{
    InFlightTurn& t = in_flight_turn_;
    // A creature whose turn is skipped (paralyzed/unconscious/Wild-Magic) or that is down isn't
    // meaningfully "present" to be reacted to — open no window (completes immediately).
    const bool open = !t.result.turn_skipped && t.agent_idx >= 0
                   && t.agent_idx < static_cast<int>(bm.placedAgents().size())
                   && bm.getAgentStats(t.agent_idx).hp_cur > 0;
    if (open && !t.window_built) {
        t.reactors     = turnStartReactors(bm, t.agent_idx);
        t.window_built = true;
    }
    while (open && t.cursor < t.reactors.size()) {
        const int reactor = t.reactors[t.cursor];
        const auto opts = turnStartOptions(bm, reactor, t.agent_idx);
        if (opts.size() <= 1) { ++t.cursor; continue; }            // only Skip → no longer qualifies
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnTurnStartNearby;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = t.agent_idx;
        ctx.options     = opts;
        if (t.interactive) {                                       // GUI suspends; resumes via submitDecision
            pending_decision_ = PendingDecision{true, ctx};
            return FlowStatus::AwaitingDecision;
        }
        applyTurnStartReaction(bm, ctx, decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{});
        ++t.cursor;                                                // auto/RL inline
    }
    pending_decision_.active = false;
    t.active = false;
    return FlowStatus::Completed;
}

FlowStatus CombatEngine::beginTurnFlow(BattleMap& bm, int agent_idx, bool interactive)
{
    in_flight_turn_             = InFlightTurn{};
    in_flight_turn_.active      = true;
    in_flight_turn_.interactive = interactive;
    in_flight_turn_.agent_idx   = agent_idx;
    in_flight_turn_.result      = beginTurn(bm, agent_idx);        // the existing synchronous body
    return advanceTurnStart(bm);
}

} // namespace rpg
