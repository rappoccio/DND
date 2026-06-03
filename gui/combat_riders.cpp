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
    const int dice = (atk_stats.char_level >= 14) ? 2 : 1;
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

bool CombatEngine::canUseWarMagic(BattleMap& bm, int idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats st = bm.getAgentStats(idx);
    if (st.character_class != CharacterClass::Fighter) return false;
    if (st.fighter_subclass != EldritchKnightPath) return false;
    if (st.char_level < 7) return false;                       // War Magic unlocks at L7
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
    if (stats.character_class != CharacterClass::Fighter ||
        stats.fighter_subclass != EldritchKnightPath || stats.char_level < 7)
        return result;

    const bool improved = stats.char_level >= 18;  // Improved War Magic also allows level 1-5 spells
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
    if (stats.character_class != CharacterClass::Fighter ||
        stats.fighter_subclass != EldritchKnightPath || stats.char_level < 15)
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

void CombatEngine::applyCunningStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                            const std::vector<int>& effects, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Stats      atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Conditions atk_cond  = bm.getAgentConditions(attacker_idx);

    // Only valid right after a qualifying hit flagged this attack, and only once per turn.
    if (!atk_cond.cunning_strike_available || atk_cond.sneak_attack_used) return;

    const int sneak_dice = (atk_stats.char_level + 1) / 2;  // 1d6 @ L1-2 … 10d6 @ L19-20

    // Validate the chosen rider set: count limit (Improved Cunning Strike), per-effect cost, min level.
    const int max_effects = (atk_stats.char_level >= 11) ? 2 : 1;
    int cost = 0;
    bool effects_ok = (static_cast<int>(effects.size()) <= max_effects);
    for (int e : effects) {
        int c = cunningStrikeCost(e);
        if (c <= 0 || atk_stats.char_level < cunningStrikeMinLevel(e)) { effects_ok = false; break; }
        cost += c;
    }
    if (!effects_ok || cost > sneak_dice) { effects_ok = false; cost = 0; }

    // Roll the remaining Sneak Attack dice and fold them into the result + target HP.
    const int dmg_dice = sneak_dice - cost;
    int sneak_bonus = 0;
    for (int i = 0; i < dmg_dice; ++i) sneak_bonus += roll(6);

    result.total_damage += sneak_bonus;
    result.damage_breakdown.push_back({"sneak attack", sneak_bonus});

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    int overflow = std::max(0, sneak_bonus - tgt_stats.temp_hp);
    tgt_stats.temp_hp  = std::max(0, tgt_stats.temp_hp - sneak_bonus);
    tgt_stats.hp_cur   = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    result.hp_after    = tgt_stats.hp_cur;
    result.target_down = (result.hp_after <= 0);
    bm.setAgentStats(target_idx, tgt_stats);

    atk_cond.sneak_attack_used        = true;
    atk_cond.cunning_strike_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("Sneak Attack: {} adds {}d6 = {} damage", agentName(bm, attacker_idx), dmg_dice, sneak_bonus);

    // If the Sneak Attack dropped the target, knock it unconscious (matches the base-attack path).
    Agent::Conditions tgt_cond = bm.getAgentConditions(target_idx);
    if (result.hp_after <= 0 && !tgt_cond.unconscious && !tgt_cond.dead) {
        applyUnconscious(bm, target_idx);
        result.target_down = true;
    }

    // Apply rider conditions LAST, after this attack's damage is fully settled — so a rider that sets
    // a condition (e.g. Knock Out → Unconscious) can never feed back into this attack's resolution.
    if (effects_ok && cost > 0)
        applyCunningStrikeRiders(bm, attacker_idx, target_idx, effects);
}

void CombatEngine::applyCunningStrikeRiders(BattleMap& bm, int attacker_idx, int target_idx,
                                            const std::vector<int>& effects) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    const Agent::Stats atk = bm.getAgentStats(attacker_idx);
    const int dc = spellSaveDcFromAbility(atk, SaveDex);  // 8 + prof + DEX mod

    auto saveMod = [](const Agent::Stats& s, SaveAbility_t ab) -> int {
        int score = 0; bool prof = false;
        switch (ab) {
            case SaveStr: score = s.str;   prof = s.save_prof_str;   break;
            case SaveDex: score = s.dex;   prof = s.save_prof_dex;   break;
            case SaveCon: score = s.con;   prof = s.save_prof_con;   break;
            case SaveInt: score = s.intel; prof = s.save_prof_intel; break;
            case SaveWis: score = s.wis;   prof = s.save_prof_wis;   break;
            default:      score = s.cha;   prof = s.save_prof_cha;   break;
        }
        int m = (score - 10) / 2;
        if (score < 10 && (score - 10) % 2 != 0) --m;
        return m + (prof ? s.prof_bonus : 0);
    };

    for (int e : effects) {
        if (e == 2) {  // Withdraw — no save; attacker moves without provoking opportunity attacks
            Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
            ac.disengaging = true;
            bm.setAgentConditions(attacker_idx, ac);
            log_("Cunning Strike (Withdraw): {} won't provoke opportunity attacks",
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
        bool saved = auto_fail ? false : (d20 + saveMod(tgt, sa) >= dc);
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
    }
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
    Agent::Stats ts = bm.getAgentStats(target_idx);

    // Save DC = 8 + prof + STR mod (melee Battle Master)
    int str_atk_mod = (as.str - 10) / 2;
    if (as.str < 10 && (as.str - 10) % 2 != 0) --str_atk_mod;
    int dc = 8 + as.prof_bonus + str_atk_mod;
    res.save_dc = dc;

    auto saveMod = [](const Agent::Stats& s, SaveAbility_t ab) -> int {
        int score = 0; bool prof = false;
        switch (ab) {
            case SaveStr: score = s.str; prof = s.save_prof_str; break;
            case SaveWis: score = s.wis; prof = s.save_prof_wis; break;
            default:      score = s.str; prof = s.save_prof_str; break;
        }
        int m = (score - 10) / 2;
        if (score < 10 && (score - 10) % 2 != 0) --m;
        return m + (prof ? s.prof_bonus : 0);
    };

    if (maneuver_type == 0) {
        // Trip: STR save or Prone for 1 turn
        res.save_roll = roll(20, saveMod(ts, SaveStr));
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
        res.save_roll = roll(20, saveMod(ts, SaveWis));
        if (res.save_roll < dc) {
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
    }

    return res;
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
    const Weapon& w = weapons[static_cast<std::size_t>(std::clamp(action.weapon_idx, 0, 2))];
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
    if (cleric.character_class != CharacterClass::Cleric ||
        cleric.cleric_subclass != WarDomain || cleric.char_level < 3) return;
    Resource* cd = cleric.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return;

    // An ally cleric (not the attacker) also spends a Reaction and must be within 30 ft.
    if (cleric_idx != atk) {
        Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
        if (cc.reaction_used) return;
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
    const Weapon& w = weapons[static_cast<std::size_t>(std::clamp(action.weapon_idx, 0, 2))];
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
    if (stats.character_class != CharacterClass::Fighter ||
        stats.fighter_subclass != PsiWarriorPath || stats.char_level < 3) return -1;

    Agent::Conditions cond = bm.getAgentConditions(defender_idx);
    if (cond.reaction_used || cond.incapacitated) return -1;

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

int CombatEngine::applyTelekineticMovement(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()) ||
        target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Fighter ||
        stats.fighter_subclass != PsiWarriorPath || stats.char_level < 3) return -1;

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

    // Execute first attack
    Attack atk1(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk1.is_offhand = true;
    atk1.attack_slot = "bonus";
    result.attack1 = executeAction(bm, atk1);

    // Apply Open Hand rider on first hit if applicable
    if (result.attack1.valid && result.attack1.hit && rider_option >= 0 && rider_option <= 2) {
        Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
        if (ac.open_hand_rider_available) {
            result.rider1 = applyOpenHandRider(bm, attacker_idx, target_idx, rider_option);
        }
    }

    // Execute second attack
    Attack atk2(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk2.is_offhand = true;
    atk2.attack_slot = "bonus";
    result.attack2 = executeAction(bm, atk2);

    // Apply Open Hand rider on second hit if applicable
    if (result.attack2.valid && result.attack2.hit && rider_option >= 0 && rider_option <= 2) {
        Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
        if (ac.open_hand_rider_available) {
            result.rider2 = applyOpenHandRider(bm, attacker_idx, target_idx, rider_option);
        }
    }

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    ac.open_hand_rider_available = false;
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

    // Roll attacker Athletics: d20 + STR mod + proficiency (assume grapple is proficient)
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
        result.escape_dc = 10 + attacker_str_mod + attacker_prof;
        applyGrappled(bm, action.target_idx, action.attacker_idx, result.escape_dc);
        result.log_message = std::string("\"") + std::string(attacker.agent->name()) + "\" grapples \"" + std::string(target.agent->name()) +
                            "\" (attacker " + std::to_string(attacker_total) + " vs defender " +
                            std::to_string(defender_total) + " - DC " + std::to_string(result.escape_dc) + ")";
    } else {
        result.log_message = std::string("\"") + std::string(attacker.agent->name()) + "\" fails to grapple \"" +
                            std::string(target.agent->name()) + "\" (attacker " + std::to_string(attacker_total) +
                            " vs defender " + std::to_string(defender_total) + ")";
    }

    return result;
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
