// ─────────────────────────────────────────────────────────────────────────────
//  combat_fighter.cpp  –  CombatEngine Fighter features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Battle Master, Eldritch Knight, Psi Warrior, Arcane Archer.
//  Contents: War Magic, Arcane Charge, Psionic Strike, Protective Field, Telekinetic
//  Movement, Battle Master maneuvers, Arcane Shot and the Arcane Archer features.
//
//  Split out of combat_riders.cpp and combat_resources.cpp in COMBAT_REFACTOR_PLAN.md R6
//  (plans/COMBAT_CLASS_SPLIT_PLAN.md).
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <algorithm>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>

namespace rpg {

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
        if (res.save_roll < dc && conditionImmune(bm, target_idx, "Prone")) {
            // Condition Immunity: the trip lands no condition.
        } else if (res.save_roll < dc) {
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
        res.save_roll = (beguilingTwistAdvantage(bm, target_idx, "Frightened") ? rollAdvantage(20)
                                                                               : roll(20)) +
                        saveModFor(bm, target_idx, SaveWis);
        if (res.save_roll < dc && hasAuraOfCourage(bm, target_idx)) {
            // Aura of Courage: the target can't be Frightened — the maneuver lands no condition.
            log_("{} can't be Frightened (Aura of Courage) — Menacing Attack has no effect",
                 agentName(bm, target_idx));
        } else if (res.save_roll < dc && conditionImmune(bm, target_idx, "Frightened")) {
            // Condition Immunity: the maneuver lands no condition.
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
            charmFearSaveSucceeded(bm, target_idx);   // Beguiling Twist's trigger
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

bool CombatEngine::heldByGraspingShot(int target_idx) const noexcept
{
    for (const auto& c : conditions_.all())
        if (c.arcane_shot == ArcaneShotGrasping && c.agent_idx == target_idx &&
            c.condition_name == "Restrained")
            return true;
    return false;
}

ArcaneShotResult CombatEngine::applyArcaneShot(BattleMap& bm, int archer_idx, int target_idx, int option,
                                               AttackResult& result) noexcept
{
    ArcaneShotResult res;
    res.option = option;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || target_idx < 0 || target_idx >= n) return res;

    const auto opt = static_cast<ArcaneShotOption>(option);
    if (opt != ArcaneShotBanishing && opt != ArcaneShotBeguiling && opt != ArcaneShotBursting &&
        opt != ArcaneShotGrasping && opt != ArcaneShotShadow) return res;   // not an on-hit option

    Agent::Conditions ac = bm.getAgentConditions(archer_idx);
    if (!ac.arcane_shot_available || ac.arcane_shot_used) return res;
    const Agent::Stats as = bm.getAgentStats(archer_idx);
    if (!as.knowsArcaneShot(opt)) return res;
    const Resource* uses = as.getResource("Arcane Shot");
    if (!uses || uses->current <= 0) return res;

    // Commit: one use, once per turn.
    spendResource(bm, archer_idx, "Arcane Shot", 1);
    ac.arcane_shot_available = false;
    ac.arcane_shot_used      = true;
    bm.setAgentConditions(archer_idx, ac);
    res.valid   = true;

    const int die  = as.arcane_shot_die_size;
    const int dice = (opt == ArcaneShotBeguiling || opt == ArcaneShotBursting) ? 2 : 1;
    for (int i = 0; i < dice; ++i) res.die_total += roll(die);

    const bool magic = (opt != ArcaneShotGrasping);
    const int  mtype = (opt == ArcaneShotBursting) ? static_cast<int>(MagicDamage_t::Force)
                                                    : static_cast<int>(MagicDamage_t::Psychic);
    auto mult_for = [&](int idx) -> float {
        const Agent::Stats ts = bm.getAgentStats(idx);
        return magic ? effectiveMagicDamageMult(as, ts, static_cast<MagicDamage_t>(mtype), false, &bm, idx)
                     : effectivePhysicalDamageMult(as, ts, Slashing, &bm, idx);
    };
    auto hurt = [&](int idx, int dmg) {
        if (dmg <= 0) return;
        (void)damageAgent(bm, idx, dmg);
        checkConcentrationOnDamage(bm, idx, dmg, archer_idx);
        processDamageTaken(bm, idx, dmg, magic ? magicTypeBit(mtype) : 0u);
    };

    // The hit target: fold the dice into the attack's result.
    static constexpr const char* kName[] = {"", "Banishing Shot", "Beguiling Shot", "Bursting Shot",
                                            "Grasping Shot", "Piercing Shot", "Seeking Shot", "Shadow Shot"};
    const char* label = kName[static_cast<int>(opt)];
    res.damage = std::max(0, static_cast<int>(static_cast<float>(res.die_total) * mult_for(target_idx)));
    result.damage_breakdown.push_back({label, res.damage});
    result.total_damage += res.damage;
    if (magic) result.magic_damage_types.push_back(static_cast<MagicDamage_t>(mtype));
    else       result.physical_damage_types.push_back(Slashing);
    hurt(target_idx, res.damage);
    result.target_down = bm.getAgentStats(target_idx).hp_cur <= 0;
    log_("{}: {} takes {} {} damage", label, agentName(bm, target_idx), res.damage,
         opt == ArcaneShotBursting ? "Force" : opt == ArcaneShotGrasping ? "Slashing" : "Psychic");

    if (opt == ArcaneShotBursting) {
        // Each other creature in a 10-ft emanation from the target takes the same 2 dice of Force.
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
        for (int i = 0; i < n; ++i) {
            if (i == target_idx) continue;
            const PlacedAgent& pa = agents[static_cast<std::size_t>(i)];
            if (pa.removed_from_play || pa.origin.z != tpa.origin.z) continue;
            const Agent::Stats st = bm.getAgentStats(i);
            if (st.hp_cur <= 0 || (st.hp_max == 0 && st.hp_cur == 0)) continue;
            if (sealedApart(bm, target_idx, i)) continue;
            if (footprintDistance(tpa.origin, tpa.agent->getSize(), pa.origin, pa.agent->getSize()) * 5 > 10)
                continue;
            if (!bm.hasLineOfSight(tpa.origin, tpa.agent->getSize(), pa.origin, pa.agent->getSize())) continue;
            const int dmg = std::max(0, static_cast<int>(static_cast<float>(res.die_total) * mult_for(i)));
            hurt(i, dmg);
            if (i != archer_idx) endBeguilingCharm(bm, archer_idx, i);
            res.splash_targets.push_back(i);
            res.splash_damage.push_back(dmg);
            log_("Bursting Shot: {} takes {} Force damage", agentName(bm, i), dmg);
        }
        return res;
    }

    if (result.target_down) return res;   // nothing left to save

    // Save-rider options.
    res.save_dc = as.arcaneShotDC();
    const int dc = res.save_dc;
    std::string cond_name;
    SaveAbility_t ab = SaveWis;
    switch (opt) {
        case ArcaneShotBanishing: cond_name = "Banished";   ab = SaveCha; break;
        case ArcaneShotBeguiling: cond_name = "Charmed";    ab = SaveWis; break;
        case ArcaneShotGrasping:  cond_name = "Restrained"; ab = SaveStr; break;
        case ArcaneShotShadow:    cond_name = "Blinded";    ab = SaveWis; break;
        default: return res;
    }
    // The Beguiling save is itself a forced save from the archer, which would break a standing charm.
    endBeguilingCharm(bm, archer_idx, target_idx);

    if (opt == ArcaneShotBeguiling && beguilingTwistAdvantage(bm, target_idx, "Charmed"))
        res.save_roll = rollAdvantage(20, saveModFor(bm, target_idx, ab));
    else
        res.save_roll = roll(20, saveModFor(bm, target_idx, ab));
    if (ab == SaveStr) res.save_roll = applyIndomitableMight(bm, target_idx, ab, res.save_roll);

    if (res.save_roll >= dc) {
        log_("{} resists {} ({} save {} vs DC {})", agentName(bm, target_idx), label,
             ab == SaveCha ? "CHA" : ab == SaveStr ? "STR" : "WIS", res.save_roll, dc);
        if (opt == ArcaneShotBeguiling) charmFearSaveSucceeded(bm, target_idx);
        return res;
    }
    if (conditionImmune(bm, target_idx, cond_name)) {
        log_("{} is immune to {} — {} lands no condition", agentName(bm, target_idx), cond_name, label);
        return res;
    }

    if (opt == ArcaneShotBanishing) {
        // Until the end of its next turn: ticks at the TARGET's turn starts (AA0 helper).
        res.condition_applied = banish(bm, target_idx, target_idx, 2) >= 0;
    } else {
        if (opt == ArcaneShotGrasping) {
            // A new Grasping Shot ends this archer's previous one.
            std::vector<int> ids;
            for (const auto& c : conditions_.all())
                if (c.arcane_shot == ArcaneShotGrasping && c.caster_idx == archer_idx)
                    ids.push_back(c.condition_id);
            for (int id : ids) removeAgentCondition(bm, id);
        }
        ActiveAgentCondition c;
        c.agent_idx         = target_idx;
        c.save_ability      = ab;
        c.save_dc           = dc;
        c.save_repeat_turns = -1;            // no repeat save (Grasping escapes by a check instead)
        c.next_save_turn    = -1;
        c.condition_name    = cond_name;
        c.arcane_shot       = static_cast<int>(opt);
        if (opt == ArcaneShotBeguiling) {
            c.caster_idx = archer_idx; c.turns_remaining = 1;    // until the start of the archer's next turn
        } else if (opt == ArcaneShotGrasping) {
            c.caster_idx = archer_idx; c.turns_remaining = 10;   // 1 minute
        } else {                                                 // Shadow: until the end of its next turn
            c.caster_idx = target_idx; c.turns_remaining = 2;
        }
        res.condition_applied = addAgentCondition(bm, c) >= 0;
    }
    if (res.condition_applied)
        log_("{} fails its save ({} vs DC {}) — {} ({})", agentName(bm, target_idx), res.save_roll, dc,
             cond_name, label);
    return res;
}

bool CombatEngine::canUseArcaneShot(const BattleMap& bm, int archer_idx, int option) const noexcept
{
    if (archer_idx < 0 || archer_idx >= static_cast<int>(bm.placedAgents().size())) return false;
    if (option <= 0 || option > static_cast<int>(ArcaneShotShadow)) return false;
    const Agent::Stats as = bm.getAgentStats(archer_idx);
    if (!as.knowsArcaneShot(static_cast<ArcaneShotOption>(option))) return false;
    const Resource* uses = as.getResource("Arcane Shot");
    if (!uses || uses->current <= 0) return false;
    return !bm.getAgentConditions(archer_idx).arcane_shot_used;
}

std::vector<Cell> CombatEngine::piercingShotCells(const BattleMap& bm, int archer_idx,
                                                  int aim_col, int aim_row) const
{
    const auto& agents = bm.placedAgents();
    if (archer_idx < 0 || archer_idx >= static_cast<int>(agents.size())) return {};
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    // A 30-ft line, one cell wide (the grid's resolution of the 1-ft-wide line), from the archer.
    // Unfiltered: the shot passes through objects, so walls neither stop nor shorten it.
    Spell line;
    line.geometry = Spell::Line;
    line.length   = 30;
    line.width    = 5;
    Cell aim = apa.origin;
    aim.col = aim_col;
    aim.row = aim_row;
    std::vector<Cell> cells = bm.aoeCells(aim, line, apa.origin, Cell{-1, -1}, apa.agent->getSize());
    for (Cell& c : cells) c.z = apa.origin.z;
    return cells;
}

namespace {
// The shot's ranged weapon, or nullptr. D1 counts thrown weapons as ranged attacks, but a thrown
// Piercing/Seeking Shot would also have to drop the weapon at the far end; AA3 takes Ranged only.
const Weapon* arcaneShotWeapon(const PlacedAgent& pa, int weapon_idx) noexcept
{
    if (weapon_idx < 0 || weapon_idx >= static_cast<int>(pa.weapons.size())) return nullptr;
    const Weapon& w = pa.weapons[static_cast<std::size_t>(weapon_idx)];
    return w.type == WeaponType::Ranged ? &w : nullptr;
}
} // namespace

bool CombatEngine::seekingShotTargetValid(const BattleMap& bm, int archer_idx, int weapon_idx,
                                          int target_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || target_idx < 0 || target_idx >= n || archer_idx == target_idx)
        return false;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
    const Weapon* w = arcaneShotWeapon(apa, weapon_idx);
    if (!w || tpa.removed_from_play || tpa.origin.z != apa.origin.z) return false;
    const Agent::Stats ts = bm.getAgentStats(target_idx);
    if (ts.hp_cur <= 0) return false;
    if (sealedApart(bm, archer_idx, target_idx)) return false;
    return footprintDistance(apa.origin, apa.agent->getSize(), tpa.origin, tpa.agent->getSize()) * 5
           <= w->long_range_ft;
}

// Shared resolution: commit the use, roll the 2 dice once, then a DEX save per creature.
// Piercing: fail = weapon + 2 dice Piercing, success = half of that. Seeking: fail = weapon + 2 dice
// Force, success = half the weapon damage only. The weapon damage is rolled per creature (it runs
// through rollDamage, which applies each creature's own multipliers as it rolls).
ArcaneShotSaveResult CombatEngine::finishArcaneSaveShot(BattleMap& bm, int archer_idx, const Weapon& w,
                                                        ArcaneShotOption opt, const std::vector<int>& targets,
                                                        ArcaneShotSaveResult res) noexcept
{
    // Commit: one use, once per turn.
    spendResource(bm, archer_idx, "Arcane Shot", 1);
    Agent::Conditions ac = bm.getAgentConditions(archer_idx);
    ac.arcane_shot_available = false;
    ac.arcane_shot_used      = true;
    bm.setAgentConditions(archer_idx, ac);
    res.valid = true;

    const Agent::Stats as = bm.getAgentStats(archer_idx);
    const int die = as.arcane_shot_die_size;
    res.die_total = roll(die) + roll(die);
    res.save_dc   = as.arcaneShotDC();
    const bool piercing = (opt == ArcaneShotPiercing);
    const char* label = piercing ? "Piercing Shot" : "Seeking Shot";
    log_("{}: {} looses a {} (2d{} = {}, DEX save DC {})", label, agentName(bm, archer_idx), w.name,
         die, res.die_total, res.save_dc);

    for (int idx : targets) {
        // Forcing a save on the creature it charmed ends Beguiling Shot's charm (D6).
        endBeguilingCharm(bm, archer_idx, idx);
        const Agent::Stats ts = bm.getAgentStats(idx);
        AttackResult wr;
        rollDamage(w, as, ts, wr, false, &bm, idx);
        const int weapon_dmg = std::max(0, wr.total_damage);
        const float mult = piercing ? effectivePhysicalDamageMult(as, ts, Piercing, &bm, idx)
                                    : effectiveMagicDamageMult(as, ts, MagicDamage_t::Force, false, &bm, idx);
        const int extra = std::max(0, static_cast<int>(static_cast<float>(res.die_total) * mult));
        const int save  = roll(20, saveModFor(bm, idx, SaveDex));
        const bool ok   = save >= res.save_dc;
        int dmg = 0;
        if (!ok)           dmg = weapon_dmg + extra;
        else if (piercing) dmg = (weapon_dmg + extra) / 2;
        else               dmg = weapon_dmg / 2;
        unsigned mask = 0;
        for (auto mt : wr.magic_damage_types) mask |= magicTypeBit(static_cast<int>(mt));
        if (!piercing && !ok) mask |= magicTypeBit(static_cast<int>(MagicDamage_t::Force));
        if (dmg > 0) {
            (void)damageAgent(bm, idx, dmg);
            checkConcentrationOnDamage(bm, idx, dmg, archer_idx);
            processDamageTaken(bm, idx, dmg, mask);
        }
        log_("{}: {} DEX save {} vs DC {} — {}, takes {} damage", label, agentName(bm, idx), save,
             res.save_dc, ok ? "succeeds" : "fails", dmg);
        res.targets.push_back(idx);
        res.save_rolls.push_back(save);
        res.saved.push_back(ok);
        res.damage.push_back(dmg);
    }
    return res;
}

ArcaneShotSaveResult CombatEngine::piercingShot(BattleMap& bm, int archer_idx, int weapon_idx,
                                                int aim_col, int aim_row) noexcept
{
    ArcaneShotSaveResult res;
    res.option = static_cast<int>(ArcaneShotPiercing);
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (!canUseArcaneShot(bm, archer_idx, res.option)) return res;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const Weapon* wp = arcaneShotWeapon(apa, weapon_idx);
    if (!wp) return res;
    const std::vector<Cell> cells = piercingShotCells(bm, archer_idx, aim_col, aim_row);
    if (cells.empty()) return res;   // aimed at the archer's own square: no direction

    std::vector<int> targets;
    for (int i = 0; i < n; ++i) {
        if (i == archer_idx) continue;
        const PlacedAgent& pa = agents[static_cast<std::size_t>(i)];
        if (pa.removed_from_play || pa.origin.z != apa.origin.z) continue;
        const Agent::Stats st = bm.getAgentStats(i);
        if (st.hp_cur <= 0 || (st.hp_max == 0 && st.hp_cur == 0)) continue;
        if (sealedApart(bm, archer_idx, i)) continue;
        const int sz = pa.agent->getSize();
        const bool in_line = std::any_of(cells.begin(), cells.end(), [&](const Cell& c) {
            return c.col >= pa.origin.col && c.col < pa.origin.col + sz &&
                   c.row >= pa.origin.row && c.row < pa.origin.row + sz;
        });
        if (in_line) targets.push_back(i);
    }
    return finishArcaneSaveShot(bm, archer_idx, *wp, ArcaneShotPiercing, targets, res);
}

ArcaneShotSaveResult CombatEngine::seekingShot(BattleMap& bm, int archer_idx, int weapon_idx,
                                               int target_idx) noexcept
{
    ArcaneShotSaveResult res;
    res.option = static_cast<int>(ArcaneShotSeeking);
    if (!canUseArcaneShot(bm, archer_idx, res.option)) return res;
    if (!seekingShotTargetValid(bm, archer_idx, weapon_idx, target_idx)) return res;
    const Weapon& w = bm.placedAgents()[static_cast<std::size_t>(archer_idx)]
                          .weapons[static_cast<std::size_t>(weapon_idx)];
    return finishArcaneSaveShot(bm, archer_idx, w, ArcaneShotSeeking, {target_idx}, res);
}

// After a ranged weapon attack misses, a Bonus Action rerolls the attack against a different
// creature the archer can see, within the weapon's range and within 60 ft of the original target.
// Ranged weapons only (as AA3): a thrown weapon is already lying at the first target.
std::vector<int> CombatEngine::curvingShotTargets(const BattleMap& bm, int archer_idx, int original_idx,
                                                  int weapon_idx) const noexcept
{
    std::vector<int> out;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || original_idx < 0 || original_idx >= n) return out;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& opa = agents[static_cast<std::size_t>(original_idx)];
    const Weapon* w = arcaneShotWeapon(apa, weapon_idx);
    if (!w) return out;
    for (int i = 0; i < n; ++i) {
        if (i == archer_idx || i == original_idx) continue;
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(i)];
        if (tpa.removed_from_play || tpa.origin.z != apa.origin.z) continue;
        if (bm.getAgentStats(i).hp_cur <= 0) continue;
        if (sealedApart(bm, archer_idx, i)) continue;
        if (footprintDistance(opa.origin, opa.agent->getSize(), tpa.origin, tpa.agent->getSize()) * 5 > 60)
            continue;
        if (!canAttack(*w, bm, apa.origin, apa.agent->getSize(), tpa.origin, tpa.agent->getSize())) continue;
        if (!canPerceiveTarget(bm, archer_idx, i)) continue;
        out.push_back(i);
    }
    return out;
}

AttackResult CombatEngine::applyCurvingShot(BattleMap& bm, int archer_idx, int original_idx,
                                            int new_target_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n) return AttackResult{};
    Agent::Conditions ac = bm.getAgentConditions(archer_idx);
    if (!ac.curving_shot_available) return AttackResult{};   // only when the miss offered it
    const std::vector<int> legal = curvingShotTargets(bm, archer_idx, original_idx, weapon_idx);
    if (std::find(legal.begin(), legal.end(), new_target_idx) == legal.end()) return AttackResult{};
    if (!spendBonusAction(bm, archer_idx)) return AttackResult{};
    ac = bm.getAgentConditions(archer_idx);
    ac.curving_shot_available = false;
    bm.setAgentConditions(archer_idx, ac);
    log_("{} curves the missed shot toward {} (Curving Shot, Bonus Action)",
         agentName(bm, archer_idx), agentName(bm, new_target_idx));
    // The reroll is a fresh attack roll against the new creature; a hit may then offer Arcane Shot.
    // The Bonus Action is spent, so a miss here cannot offer Curving Shot again.
    return executeAction(bm, Attack{archer_idx, new_target_idx, weapon_idx});
}

// When initiative is rolled, an Arcane Archer with no Arcane Shot uses left regains one. RNG-free;
// called once at combat start (auto and real-dice initiative alike; replay/arena mirror it).
void CombatEngine::applyEverReadyShot(BattleMap& bm) noexcept
{
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int i = 0; i < n; ++i) {
        Agent::Stats st = bm.getAgentStats(i);
        if (st.fighter_subclass != ArcaneArcherPath || st.classLevel(CharacterClass::Fighter) < 10) continue;
        Resource* au = st.getResource("Arcane Shot");
        if (!au || au->current > 0 || au->max <= 0) continue;
        au->gain(1);
        bm.setAgentStats(i, st);
        log_("{} regains an Arcane Shot use (Ever-Ready Shot)", agentName(bm, i));
    }
}

// After the archer succeeds on a saving throw using Indomitable, it can teleport up to 60 ft to an
// unoccupied space it can see. No action, no Reaction (it rides on Indomitable).
bool CombatEngine::canIndomitableTeleport(const BattleMap& bm, int idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()) || bm.isAgentOnDeck(idx)) return false;
    const Agent::Stats st = bm.getAgentStats(idx);
    if (st.hp_cur <= 0 || st.fighter_subclass != ArcaneArcherPath ||
        st.classLevel(CharacterClass::Fighter) < 15) return false;
    const Agent::Conditions c = bm.getAgentConditions(idx);
    return !c.dead && !c.incapacitated;
}

bool CombatEngine::isIndomitableTeleportDestination(const BattleMap& bm, int idx, Cell dest) const
{
    return isSeenTeleportSpace(bm, idx, dest, 12);   // 60 ft
}

bool CombatEngine::applyIndomitableTeleport(BattleMap& bm, int idx, int col, int row)
{
    if (!canIndomitableTeleport(bm, idx)) return false;
    if (!isIndomitableTeleportDestination(bm, idx, Cell{col, row})) return false;
    const Cell from = bm.placedAgents()[static_cast<std::size_t>(idx)].origin;
    if (!teleportAgent(bm, idx, col, row)) return false;
    log_("{} teleports {} ft (Indomitable Teleport)", agentName(bm, idx),
         5 * std::max(std::abs(col - from.col), std::abs(row - from.row)));
    return true;
}

std::vector<ReactionOption> CombatEngine::indomitableTeleportOptions() const
{
    std::vector<ReactionOption> opts;
    opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                  "Indomitable Teleport: teleport up to 60 ft (pick a cell)",
                                  "IndomitableTeleportPick"});
    opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Stay put", ""});
    return opts;
}

// Reaction: when a creature the archer can see misses it with an attack roll, the archer moves up to
// half its Speed away from that creature without provoking Opportunity Attacks, then makes one
// ranged weapon attack against it if it is within range.
bool CombatEngine::canMasterfulShots(const BattleMap& bm, int archer_idx, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || attacker_idx < 0 || attacker_idx >= n) return false;
    if (archer_idx == attacker_idx || bm.isAgentOnDeck(archer_idx)) return false;
    const Agent::Stats st = bm.getAgentStats(archer_idx);
    if (st.hp_cur <= 0 || st.fighter_subclass != ArcaneArcherPath ||
        st.classLevel(CharacterClass::Fighter) < 18) return false;
    const Agent::Conditions c = bm.getAgentConditions(archer_idx);
    if (c.dead || !canTakeReaction(c)) return false;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(attacker_idx)];
    if (tpa.removed_from_play || tpa.origin.z != apa.origin.z) return false;
    if (bm.getAgentStats(attacker_idx).hp_cur <= 0) return false;
    if (sealedApart(bm, archer_idx, attacker_idx)) return false;
    if (!canPerceiveTarget(bm, archer_idx, attacker_idx)) return false;   // "a creature you can see"
    for (int w = 0; w < static_cast<int>(apa.weapons.size()); ++w)
        if (arcaneShotWeapon(apa, w)) return true;                         // something to shoot with
    return false;
}

int CombatEngine::masterfulShotsWeapon(const BattleMap& bm, int archer_idx, int attacker_idx, Cell from) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || attacker_idx < 0 || attacker_idx >= n) return -1;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(attacker_idx)];
    const int asz = apa.agent->getSize(), tsz = tpa.agent->getSize();
    int at_long = -1;
    for (int w = 0; w < static_cast<int>(apa.weapons.size()); ++w) {
        const Weapon* wp = arcaneShotWeapon(apa, w);
        if (!wp || !canAttack(*wp, bm, from, asz, tpa.origin, tsz)) continue;
        if (!hasDisadvantage(*wp, bm, from, asz, tpa.origin, tsz)) return w;
        if (at_long < 0) at_long = w;
    }
    return at_long;
}

namespace {
// Half the archer's walking Speed in feet, rounded down to a 5-ft square; 0 while its Speed is 0.
int masterfulHalfSpeed(const Agent::Stats& st, const Agent::Conditions& c) noexcept
{
    if (c.grappled || c.restrained || c.branches_speed_zeroed) return 0;
    return (st.speed_walk / 2) / 5 * 5;
}
} // namespace

bool CombatEngine::isMasterfulShotsDestination(const BattleMap& bm, int archer_idx, int attacker_idx,
                                               Cell dest) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || attacker_idx < 0 || attacker_idx >= n) return false;
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(attacker_idx)];
    if (dest.col == apa.origin.col && dest.row == apa.origin.row) return true;   // shoot without moving
    const int sz = apa.agent->getSize(), tsz = tpa.agent->getSize();
    const Cell at{dest.col, dest.row, apa.origin.z};
    // "away from the attacker": every legal end cell is farther from it than the start.
    if (footprintDistance(at, sz, tpa.origin, tsz) <= footprintDistance(apa.origin, sz, tpa.origin, tsz))
        return false;
    if (bm.agentOccupancy(at, sz, archer_idx) != 0) return false;
    const int half = masterfulHalfSpeed(bm.getAgentStats(archer_idx), bm.getAgentConditions(archer_idx));
    if (half <= 0) return false;
    const CellSet reach = bm.reachableCells(apa.origin, sz, half, MovementType::Walk, archer_idx);
    for (const Cell& c : reach)
        if (c.col == at.col && c.row == at.row) return true;
    return false;
}

Cell CombatEngine::masterfulShotsDestination(const BattleMap& bm, int archer_idx, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (archer_idx < 0 || archer_idx >= n || attacker_idx < 0 || attacker_idx >= n) return Cell{-1, -1};
    const PlacedAgent& apa = agents[static_cast<std::size_t>(archer_idx)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(attacker_idx)];
    const int sz = apa.agent->getSize(), tsz = tpa.agent->getSize();
    std::vector<Cell> cands{apa.origin};
    const int half = masterfulHalfSpeed(bm.getAgentStats(archer_idx), bm.getAgentConditions(archer_idx));
    if (half > 0)
        for (const Cell& c : bm.reachableCells(apa.origin, sz, half, MovementType::Walk, archer_idx))
            if (isMasterfulShotsDestination(bm, archer_idx, attacker_idx, c))
                cands.push_back(Cell{c.col, c.row, apa.origin.z});
    // Rank: a weapon reaches the attacker > no long-range Disadvantage > farther from it > shorter
    // move > row-major (the CellSet is unordered, so the last key keeps the pick deterministic).
    auto key = [&](const Cell& c) {
        const int w = masterfulShotsWeapon(bm, archer_idx, attacker_idx, c);
        int normal = 0;
        if (w >= 0) {
            const Weapon& wp = apa.weapons[static_cast<std::size_t>(w)];
            normal = hasDisadvantage(wp, bm, c, sz, tpa.origin, tsz) ? 0 : 1;
        }
        return std::make_tuple(w >= 0 ? 1 : 0, normal, footprintDistance(c, sz, tpa.origin, tsz),
                               -footprintDistance(apa.origin, sz, c, sz), -c.row, -c.col);
    };
    Cell best = cands.front();
    auto best_key = key(best);
    for (const Cell& c : cands) {
        const auto k = key(c);
        if (k > best_key) { best = c; best_key = k; }
    }
    return best;
}

AttackResult CombatEngine::applyMasterfulShots(BattleMap& bm, int archer_idx, int attacker_idx, int col, int row)
{
    if (!canMasterfulShots(bm, archer_idx, attacker_idx)) return AttackResult{};
    const Cell origin = bm.placedAgents()[static_cast<std::size_t>(archer_idx)].origin;
    Cell dest = (col >= 0 && row >= 0) ? Cell{col, row, origin.z}
                                       : masterfulShotsDestination(bm, archer_idx, attacker_idx);
    if (dest.col < 0 || !isMasterfulShotsDestination(bm, archer_idx, attacker_idx, dest)) return AttackResult{};
    dest.z = origin.z;
    Agent::Conditions c = bm.getAgentConditions(archer_idx);
    c.reaction_used = true;
    bm.setAgentConditions(archer_idx, c);
    if (dest.col != origin.col || dest.row != origin.row) {
        // A Reaction move that provokes no Opportunity Attacks: placed directly, no budget spent.
        (void)bm.setAgentPosition(archer_idx, dest);
        log_("{} uses Masterful Shots: moves {} ft away from {}", agentName(bm, archer_idx),
             5 * std::max(std::abs(dest.col - origin.col), std::abs(dest.row - origin.row)),
             agentName(bm, attacker_idx));
    } else {
        log_("{} uses Masterful Shots against {}", agentName(bm, archer_idx), agentName(bm, attacker_idx));
    }
    const int w = masterfulShotsWeapon(bm, archer_idx, attacker_idx, dest);
    if (w < 0) {
        log_("{} is out of range — no Masterful Shots attack", agentName(bm, attacker_idx));
        return AttackResult{};
    }
    AttackResult r = executeAction(bm, Attack{archer_idx, attacker_idx, w});
    // The shot lands outside the archer's own turn, where no Arcane Shot / Curving Shot prompt follows:
    // drop the offers so they don't surface on a later attack.
    Agent::Conditions after = bm.getAgentConditions(archer_idx);
    after.arcane_shot_available  = false;
    after.curving_shot_available = false;
    bm.setAgentConditions(archer_idx, after);
    return r;
}

std::vector<ReactionOption> CombatEngine::masterfulShotsOptions() const
{
    std::vector<ReactionOption> opts;
    opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                  "Masterful Shots: move away and shoot back (best cell)", "MasterfulShots"});
    opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                  "Masterful Shots: move away and shoot back (pick a cell)", "MasterfulShotsPick"});
    opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

GraspingEscapeResult CombatEngine::escapeGraspingShot(BattleMap& bm, int actor_idx, int target_idx) noexcept
{
    GraspingEscapeResult res;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (actor_idx < 0 || actor_idx >= n || target_idx < 0 || target_idx >= n) return res;

    int cond_id = -1;
    for (const auto& c : conditions_.all())
        if (c.arcane_shot == ArcaneShotGrasping && c.agent_idx == target_idx &&
            c.condition_name == "Restrained") { cond_id = c.condition_id; res.dc = c.save_dc; break; }
    if (cond_id < 0) return res;

    // Same reach rule as the Net: the restrained creature itself, or a creature within 5 ft of it.
    const Agent::Conditions acd = bm.getAgentConditions(actor_idx);
    if (acd.dead || acd.unconscious || acd.incapacitated) return res;
    if (actor_idx != target_idx) {
        const PlacedAgent& apa = agents[static_cast<std::size_t>(actor_idx)];
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
        if (footprintDistance(apa.origin, apa.agent->getSize(),
                              tpa.origin, tpa.agent->getSize()) * 5 > 5) return res;
        if (!bm.hasLineOfSight(apa.origin, apa.agent->getSize(),
                               tpa.origin, tpa.agent->getSize())) return res;
    }

    const Agent::Stats st = bm.getAgentStats(actor_idx);
    const int str_mod = dndMod(st.str);
    res.valid = true;
    res.d20   = roll(20);
    res.total = res.d20 + str_mod;
    res.freed = res.total >= res.dc;
    if (res.freed) removeAgentCondition(bm, cond_id);
    log_("{} makes a DC {} STR check to free {} from the Grasping Shot: {} + {} = {} ({})",
         agentName(bm, actor_idx), res.dc,
         actor_idx == target_idx ? "itself" : agentName(bm, target_idx),
         res.d20, str_mod, res.total, res.freed ? "FREED" : "FAILED");
    return res;
}

} // namespace rpg
