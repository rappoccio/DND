// ─────────────────────────────────────────────────────────────────────────────
//  combat_rogue.cpp  –  CombatEngine Rogue features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Soulknife (and every Rogue through Cunning Strike).
//  Contents: Cunning Strike and its riders, Homing Strikes, Rend Mind, Psychic Veil,
//  Psychic Teleportation.
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
        const int dc = rules::spellSaveDcFromAbility(atk_stats, SaveDex);   // 8 + PB + DEX mod
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
    const int dc = rules::spellSaveDcFromAbility(atk, SaveDex);  // 8 + prof + DEX mod
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
        if (conditionImmune(bm, target_idx, name)) continue;

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

    const int dc = rules::spellSaveDcFromAbility(atk, SaveDex);           // 8 + PB + DEX mod
    const Agent::Conditions tc0 = bm.getAgentConditions(target_idx);
    const bool auto_fail = tc0.paralyzed || tc0.stunned;
    const int d20   = auto_fail ? 1 : roll(20);
    const int total = applyIndomitableMight(bm, target_idx, SaveWis, d20 + saveModFor(bm, target_idx, SaveWis));
    if (!auto_fail && total >= dc) {
        log_("Rend Mind: {} resists (WIS {} vs DC {})", agentName(bm, target_idx), total, dc);
        return false;
    }
    if (conditionImmune(bm, target_idx, "Stunned")) return false;

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

// Soulknife Rogue — Psychic Veil (L13): a Magic action → gain Invisible. Once per Long Rest, or by
// expending 1 Psionic Energy Die. v1: "ends when you deal damage or force a save" is approximated by
// the base Invisibility (ends on the next attack); the force-a-save end-trigger is not tracked.
bool CombatEngine::activatePsychicVeil(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Rogue) ||
        s.rogue_subclass != SoulknifePath || s.classLevel(CharacterClass::Rogue) < 13) return false;
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
    if (s.lacksClass(CharacterClass::Rogue) ||
        s.rogue_subclass != SoulknifePath || s.classLevel(CharacterClass::Rogue) < 9) return false;
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

} // namespace rpg
