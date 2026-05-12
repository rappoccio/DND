// ─────────────────────────────────────────────────────────────────────────────
//  combat.cpp  –  CombatEngine implementation
// ─────────────────────────────────────────────────────────────────────────────

#include "combat.hpp"
#include "battle_map.hpp"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Construction / RNG
// ─────────────────────────────────────────────────────────────────────────────

CombatEngine::CombatEngine(uint32_t seed)
{
    reseed(seed == 0 ? std::random_device{}() : seed);
}

void CombatEngine::reseed(uint32_t seed)
{
    rng_.seed(seed);
}

int CombatEngine::roll(int sides)
{
    assert(sides >= 2 && "Die must have at least 2 sides");
    return std::uniform_int_distribution<int>{1, sides}(rng_);
}

int CombatEngine::rollAdvantage(int sides)
{
    return std::max(roll(sides), roll(sides));
}

int CombatEngine::rollDisadvantage(int sides)
{
    return std::min(roll(sides), roll(sides));
}

// ─────────────────────────────────────────────────────────────────────────────
//  Static helpers
// ─────────────────────────────────────────────────────────────────────────────

// Standard D&D ability modifier formula.
static constexpr int abilityMod(int score) noexcept
{
    return (score - 10) / 2;   // integer truncation rounds toward zero,
                                // which is correct for negative scores too
                                // because C++11 guarantees truncation.
}

int CombatEngine::attackModifier(const Weapon& w,
                                  const Agent::Stats& s) noexcept
{
    int base;
    if (w.finesse)
        base = std::max(abilityMod(s.str), abilityMod(s.dex));
    else if (w.thrown || w.type == WeaponType::Melee)
        base = abilityMod(s.str);
    else
        base = abilityMod(s.dex);

    return base + (w.proficient ? s.prof_bonus : 0);
}

int CombatEngine::damageAbilityMod(const Weapon& w,
                                    const Agent::Stats& s) noexcept
{
    if (w.finesse)
        return std::max(abilityMod(s.str), abilityMod(s.dex));
    if (w.thrown || w.type == WeaponType::Melee)
        return abilityMod(s.str);
    return abilityMod(s.dex);
}

// Chebyshev distance from a single cell (tc, tr) to the nearest cell
// inside the attacker's footprint [atk_origin, atk_origin + atk_size).
static int chebyshevToFootprint(int tc, int tr,
                                 Cell atk_origin, int atk_size) noexcept
{
    int dc = std::max({atk_origin.col - tc,
                       tc - (atk_origin.col + atk_size - 1),
                       0});
    int dr = std::max({atk_origin.row - tr,
                       tr - (atk_origin.row + atk_size - 1),
                       0});
    return std::max(dc, dr);
}

bool CombatEngine::canAttack(const Weapon& w,
                               const BattleMap& bm,
                               Cell atk_origin, int atk_size,
                               Cell tgt_origin, int tgt_size) noexcept
{
    const int range_ft    = (w.type == WeaponType::Melee) ? w.reach_ft
                                                           : w.long_range_ft;
    const int range_cells = range_ft / 5;

    // Check every cell of the target's footprint: if any is within range
    // AND has LoS from the attacker, the attack is possible.
    for (int tr = tgt_origin.row; tr < tgt_origin.row + tgt_size; ++tr) {
        for (int tc = tgt_origin.col; tc < tgt_origin.col + tgt_size; ++tc) {
            int dist = chebyshevToFootprint(tc, tr, atk_origin, atk_size);
            if (dist <= range_cells
                    && bm.hasLineOfSight(atk_origin, atk_size, {tc, tr}, 1))
                return true;
        }
    }
    return false;
}

bool CombatEngine::hasDisadvantage(const Weapon& w,
                                    const BattleMap& /*bm*/,
                                    Cell atk_origin, int atk_size,
                                    Cell tgt_origin, int tgt_size) noexcept
{
    // Ranged (not thrown) weapons have disadvantage beyond normal_range_ft.
    if (w.type == WeaponType::Ranged && !w.thrown && w.normal_range_ft > 0) {
        int min_dist_cells = std::numeric_limits<int>::max();
        for (int tr = tgt_origin.row; tr < tgt_origin.row + tgt_size; ++tr) {
            for (int tc = tgt_origin.col; tc < tgt_origin.col + tgt_size; ++tc) {
                int d = chebyshevToFootprint(tc, tr, atk_origin, atk_size);
                min_dist_cells = std::min(min_dist_cells, d);
            }
        }
        if (min_dist_cells * 5 > w.normal_range_ft)
            return true;
    }
    // Future: disadvantage when ranged while adjacent to a threatening enemy,
    //         or other situational modifiers.
    return false;
}

int CombatEngine::damageAgent(BattleMap& bm, int idx, int amount) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return 0;   // default-constructed → invalid idx
    // Temporary HP absorbs damage first, then overflow damages hp_cur
    int overflow = std::max(0, amount - s.temp_hp);
    s.temp_hp = std::max(0, s.temp_hp - amount);
    s.hp_cur = std::max(0, s.hp_cur - overflow);
    bm.setAgentStats(idx, s);
    return s.hp_cur;
}

int CombatEngine::healAgent(BattleMap& bm, int idx, int amount) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return 0;   // default-constructed → invalid idx
    s.hp_cur = std::min(s.hp_max, s.hp_cur + amount);
    bm.setAgentStats(idx, s);
    return s.hp_cur;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Per-agent turn count
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::getAgentTurns(int idx) const noexcept
{
    auto it = agentTurns_.find(idx);
    return (it != agentTurns_.end()) ? it->second : 1;
}

void CombatEngine::setAgentTurns(int idx, int turns) noexcept
{
    if (turns <= 1) {
        agentTurns_.erase(idx);   // restore default — no entry needed
    } else {
        agentTurns_[idx] = turns;
    }
}

void CombatEngine::clearAgentTurns() noexcept
{
    agentTurns_.clear();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Per-agent movement budget
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::beginTurn(int agent_idx, const BattleMap& bm) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;
    const auto& stats = agents[static_cast<std::size_t>(agent_idx)].stats;
    walkRemaining_[agent_idx] = stats.speed_walk;
    flyRemaining_ [agent_idx] = stats.speed_fly;
    swimRemaining_[agent_idx] = stats.speed_swim;
    burrowRemaining_[agent_idx] = stats.speed_burrow;
}

int CombatEngine::getWalkRemaining(int agent_idx) const noexcept
{
    auto it = walkRemaining_.find(agent_idx);
    return (it != walkRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getFlyRemaining(int agent_idx) const noexcept
{
    auto it = flyRemaining_.find(agent_idx);
    return (it != flyRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getSwimRemaining(int agent_idx) const noexcept
{
    auto it = swimRemaining_.find(agent_idx);
    return (it != swimRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getBurrowRemaining(int agent_idx) const noexcept
{
    auto it = burrowRemaining_.find(agent_idx);
    return (it != burrowRemaining_.end()) ? it->second : 0;
}

int CombatEngine::spendWalk(int agent_idx, int feet) noexcept
{
    auto& rem  = walkRemaining_[agent_idx];  // inserts 0 if absent
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendFly(int agent_idx, int feet) noexcept
{
    auto& rem  = flyRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendSwim(int agent_idx, int feet) noexcept
{
    auto& rem  = swimRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendBurrow(int agent_idx, int feet) noexcept
{
    auto& rem  = burrowRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

void CombatEngine::clearMovement() noexcept
{
    walkRemaining_.clear();
    flyRemaining_.clear();
    swimRemaining_.clear();
    burrowRemaining_.clear();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Initiative
// ─────────────────────────────────────────────────────────────────────────────

std::vector<InitiativeEntry> CombatEngine::rollInitiative(const BattleMap& bm)
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());

    std::vector<InitiativeEntry> entries;
    entries.reserve(static_cast<std::size_t>(n));

    for (int i = 0; i < n; ++i) {
        const Agent::Stats& s = bm.getAgentStats(i);
        if (s.hp_cur <= 0) continue;   // dead / incapacitated before combat starts

        InitiativeEntry e;
        e.agent_idx = i;
        e.d20       = roll(20);
        e.modifier  = s.initiativeModifier();
        e.total     = e.d20 + e.modifier;
        entries.push_back(e);
    }

    // Sort descending: total first, then modifier (higher DEX breaks ties),
    // then agent_idx ascending (stable, deterministic final tiebreaker).
    std::sort(entries.begin(), entries.end(), [](const InitiativeEntry& a,
                                                  const InitiativeEntry& b) {
        if (a.total    != b.total)    return a.total    > b.total;
        if (a.modifier != b.modifier) return a.modifier > b.modifier;
        return a.agent_idx < b.agent_idx;
    });

    return entries;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Round execution
// ─────────────────────────────────────────────────────────────────────────────

std::vector<AttackResult> CombatEngine::runRound(
    BattleMap& bm, const std::vector<TurnActions>& turns)
{
    std::vector<AttackResult> results;
    const int n = static_cast<int>(bm.placedAgents().size());

    // Reset reaction_used for all agents at the start of the round
    for (int i = 0; i < n; ++i) {
        bm.placedAgents()[static_cast<std::size_t>(i)].agent->setReactionUsed(false);
    }

    for (const TurnActions& t : turns) {
        if (t.agent_idx < 0 || t.agent_idx >= n) continue;

        // Incapacitated agents (0 hp) skip their turn entirely.
        if (bm.getAgentStats(t.agent_idx).hp_cur <= 0) continue;

        // Retrieve the acting agent's shared_ptr through the span.
        auto& actor = bm.placedAgents()[static_cast<std::size_t>(t.agent_idx)];

        // ── Action ────────────────────────────────────────────────────────
        actor.agent->action();
        for (const Attack& atk : t.attacks) {
            AttackResult r = executeAction(bm, atk);
            if (r.valid) {
                int tgt = atk.target_idx;
                if (tgt >= 0 && tgt < n) {
                    auto& tgt_agent = bm.placedAgents()[static_cast<std::size_t>(tgt)];
                    if (!tgt_agent.agent->hasUsedReaction()) {
                        tgt_agent.agent->reaction();
                        tgt_agent.agent->setReactionUsed(true);
                    }
                }
            }
            results.push_back(std::move(r));
        }
        for (const SpellAction& sa : t.spell_actions) {
            (void)executeSpell(bm, sa);
        }

        // ── Bonus action ──────────────────────────────────────────────────
        actor.agent->bonusAction();
        for (const Attack& atk : t.bonus_attacks) {
            AttackResult r = executeAction(bm, atk);
            if (r.valid) {
                int tgt = atk.target_idx;
                if (tgt >= 0 && tgt < n) {
                    auto& tgt_agent = bm.placedAgents()[static_cast<std::size_t>(tgt)];
                    if (!tgt_agent.agent->hasUsedReaction()) {
                        tgt_agent.agent->reaction();
                        tgt_agent.agent->setReactionUsed(true);
                    }
                }
            }
            results.push_back(std::move(r));
        }
        for (const SpellAction& sa : t.bonus_spells) {
            (void)executeSpell(bm, sa);
        }

        // ── Movement ──────────────────────────────────────────────────────
        actor.agent->walk();
        actor.agent->fly();
    }

    return results;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Core attack mechanics
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::isThreatened(const BattleMap& bm, int attacker_idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()))
        return false;

    const PlacedAgent& atk = agents[attacker_idx];
    const int THREAT_DISTANCE = 2;  // 10 feet = 2 cells (each cell is 5 feet)

    // Check if any other agent is within 10 feet
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == attacker_idx) continue;  // Skip self

        const PlacedAgent& other = agents[i];
        if (other.agent->getConditions().incapacitated) continue;  // Skip incapacitated agents

        // Calculate Chebyshev distance (max of absolute differences)
        int dc = std::max({atk.origin.col - other.origin.col,
                           other.origin.col - (atk.origin.col + atk.agent->getSize() - 1),
                           0});
        int dr = std::max({atk.origin.row - other.origin.row,
                           other.origin.row - (atk.origin.row + atk.agent->getSize() - 1),
                           0});
        int dist = std::max(dc, dr);

        if (dist <= THREAT_DISTANCE)
            return true;
    }

    return false;
}

std::vector<int> CombatEngine::threateningAgents(const BattleMap& bm, int target_idx, int reach_cells) const {
    auto agents = bm.placedAgents();
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size()))
        return {};

    const PlacedAgent& tgt = agents[static_cast<std::size_t>(target_idx)];
    std::vector<int> result;

    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == target_idx) continue;
        const PlacedAgent& other = agents[static_cast<std::size_t>(i)];
        if (other.agent->getConditions().incapacitated) continue;
        if (other.stats.hp_cur <= 0) continue;

        // Chebyshev distance from target's footprint to other's origin
        int dc = std::max({tgt.origin.col - other.origin.col,
                           other.origin.col - (tgt.origin.col + tgt.agent->getSize() - 1),
                           0});
        int dr = std::max({tgt.origin.row - other.origin.row,
                           other.origin.row - (tgt.origin.row + tgt.agent->getSize() - 1),
                           0});
        int dist = std::max(dc, dr);

        if (dist <= reach_cells)
            result.push_back(i);
    }
    return result;
}

AttackResult CombatEngine::rollToHit(const Weapon& w,
                                      const Agent::Stats& attacker,
                                      int target_ac,
                                      bool advantage,
                                      bool disadvantage)
{
    AttackResult r;
    r.disadvantage = disadvantage;
    r.attack_mod   = attackModifier(w, attacker) + w.bonus_hit;
    r.target_ac    = target_ac;

    // If both advantage and disadvantage: they cancel out (roll normally)
    if (advantage && disadvantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = d1;
        log_("Advantage+disadvantage cancel: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else if (advantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = std::max(d1, d2);
        log_("Advantage: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else if (disadvantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = std::min(d1, d2);
        log_("Disadvantage: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else {
        r.d20 = roll(20);
    }

    r.critical   = (r.d20 == 20);
    r.fumble     = (r.d20 == 1);
    r.total_roll = r.d20 + r.attack_mod;
    r.hit        = r.critical || (!r.fumble && r.total_roll >= target_ac);

    return r;
}

void CombatEngine::rollDamage(const Weapon& w,
                               const Agent::Stats& attacker,
                               const Agent::Stats& target,
                               AttackResult& result)
{
    result.dice_results.clear();
    int raw = 0;

    // Roll physical damage types and apply target's multipliers
    for (const auto& dmg_roll : w.physicalDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            result.dice_results.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.physical_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.physical_damage_types.push_back(dmg_roll.type);
    }

    // Roll magic damage types and apply target's multipliers
    for (const auto& dmg_roll : w.magicDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            result.dice_results.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.magic_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.magic_damage_types.push_back(dmg_roll.type);
    }

    result.damage_mod   = damageAbilityMod(w, attacker) + w.bonus_damage;
    result.total_damage = std::max(0, raw + result.damage_mod);
}

AttackResult CombatEngine::resolveAttack(const Weapon& w,
                                          const Agent::Stats& attacker,
                                          Agent::Stats& target,
                                          bool advantage,
                                          bool disadvantage)
{
    AttackResult r = rollToHit(w, attacker, target.ac, advantage, disadvantage);
    r.hp_before = target.hp_cur;

    if (r.hit) {
        rollDamage(w, attacker, target, r);
        // Temporary HP absorbs damage first, then overflow damages hp_cur
        int overflow = std::max(0, r.total_damage - target.temp_hp);
        target.temp_hp = std::max(0, target.temp_hp - r.total_damage);
        target.hp_cur = std::clamp(target.hp_cur - overflow,
                                    0, target.hp_max);
    }

    r.hp_after    = target.hp_cur;
    r.target_down = (r.hp_after <= 0);
    r.valid       = true;
    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
//  High-level BattleMap integration
// ─────────────────────────────────────────────────────────────────────────────

AttackResult CombatEngine::executeAction(BattleMap& bm,
                                          const Attack& action)
{
    AttackResult invalid;  // valid = false

    auto agents = bm.placedAgents();
    int  n      = static_cast<int>(agents.size());

    if (action.attacker_idx < 0 || action.attacker_idx >= n) return invalid;
    if (action.target_idx   < 0 || action.target_idx   >= n) return invalid;
    if (action.attacker_idx == action.target_idx)             return invalid;

    const PlacedAgent& atk_pt = agents[action.attacker_idx];
    const PlacedAgent& tgt_pt = agents[action.target_idx];

    if (action.weapon_idx < 0 ||
            action.weapon_idx >= static_cast<int>(atk_pt.weapons.size()))
        return invalid;

    Weapon w = atk_pt.weapons[static_cast<std::size_t>(action.weapon_idx)];
    if (action.is_offhand) w.proficient = false;  // off-hand: no proficiency bonus to hit

    int atk_sz = atk_pt.agent->getSize();
    int tgt_sz = tgt_pt.agent->getSize();

    if (!canAttack(w, bm, atk_pt.origin, atk_sz, tgt_pt.origin, tgt_sz))
        return invalid;

    bool disadv = hasDisadvantage(w, bm,
                                   atk_pt.origin, atk_sz,
                                   tgt_pt.origin, tgt_sz);

    // Apply engagement disadvantage: ranged attacks suffer disadvantage if engaged
    bool is_ranged = (w.normal_range_ft > 0);
    if (is_ranged && isThreatened(bm, action.attacker_idx)) {
        disadv = true;
    }

    // Check agent conditions for advantage/disadvantage
    bool adv = atk_pt.agent->hasAdvantage();
    bool dis = disadv || atk_pt.agent->hasDisadvantage();

    // Log reasons for disadvantage
    if (is_ranged && isThreatened(bm, action.attacker_idx))
        log_("Disadvantage: threatened (enemy within 10 ft)");
    else if (disadv)  // long-range disadvantage
        log_("Disadvantage: long range");
    if (atk_pt.agent->hasDisadvantage())
        log_("Disadvantage: condition");
    if (atk_pt.agent->hasAdvantage())
        log_("Advantage: condition");

    Agent::Stats atk_stats = bm.getAgentStats(action.attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(action.target_idx);

    AttackResult r = resolveAttack(w, atk_stats, tgt_stats, adv, dis);
    bm.setAgentStats(action.target_idx, tgt_stats);  // apply HP change
    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
//  RL action space
// ─────────────────────────────────────────────────────────────────────────────

std::vector<Attack> CombatEngine::availableAttacks(
    const BattleMap& bm, int attacker_idx) const
{
    std::vector<Attack> result;
    auto agents = bm.placedAgents();
    int  n      = static_cast<int>(agents.size());

    if (attacker_idx < 0 || attacker_idx >= n)
        return result;

    const PlacedAgent& atk = agents[static_cast<std::size_t>(attacker_idx)];
    int atk_sz = atk.agent->getSize();

    for (int ti = 0; ti < n; ++ti) {
        if (ti == attacker_idx) continue;
        const PlacedAgent& tgt = agents[static_cast<std::size_t>(ti)];
        int tgt_sz = tgt.agent->getSize();

        for (int wi = 0; wi < static_cast<int>(atk.weapons.size()); ++wi) {
            const Weapon& w = atk.weapons[static_cast<std::size_t>(wi)];
            if (canAttack(w, bm, atk.origin, atk_sz, tgt.origin, tgt_sz))
                result.push_back({attacker_idx, ti, wi});
        }
    }
    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  RL observation vector
// ─────────────────────────────────────────────────────────────────────────────

static void appendAgentBlock(std::vector<float>& obs,
                              const Agent::Stats& s,
                              int col, int row,
                              int grid_cols, int grid_rows)
{
    float hp_frac = (s.hp_max > 0)
                    ? static_cast<float>(s.hp_cur) / static_cast<float>(s.hp_max)
                    : 0.f;
    obs.push_back(static_cast<float>(col) / static_cast<float>(grid_cols));
    obs.push_back(static_cast<float>(row) / static_cast<float>(grid_rows));
    obs.push_back(hp_frac);
    obs.push_back(static_cast<float>(s.ac)    / 30.f);
    obs.push_back(static_cast<float>(s.str   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.dex   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.con   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.intel - 10) / 10.f);
    obs.push_back(static_cast<float>(s.wis   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.cha   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.speed_walk) / 60.f);
    obs.push_back(static_cast<float>(s.speed_fly)  / 60.f);
}

std::vector<float> CombatEngine::getBattleObservation(
    const BattleMap& bm,
    int attacker_idx,
    const std::vector<int>& target_indices,
    int max_targets) const
{
    static constexpr int ATK_FLOATS = 12;   // matches appendAgentBlock output
    static constexpr int TGT_FLOATS = 14;   // 12 + chebyshev_norm + has_los

    std::vector<float> obs;
    obs.reserve(static_cast<std::size_t>(ATK_FLOATS + max_targets * TGT_FLOATS));

    auto agents = bm.placedAgents();
    int  cols   = bm.gridCols();
    int  rows   = bm.gridRows();
    int  maxDim = std::max(cols, rows);

    // ── Attacker block ────────────────────────────────────────────────────
    if (attacker_idx >= 0 && attacker_idx < static_cast<int>(agents.size())) {
        const PlacedAgent& atk = agents[static_cast<std::size_t>(attacker_idx)];
        Agent::Stats s = bm.getAgentStats(attacker_idx);
        appendAgentBlock(obs, s, atk.origin.col, atk.origin.row, cols, rows);
    } else {
        obs.insert(obs.end(), ATK_FLOATS, 0.f);
    }

    // ── Target blocks (zero-padded to max_targets) ────────────────────────
    int n = 0;
    for (int ti : target_indices) {
        if (n >= max_targets) break;

        if (ti < 0 || ti >= static_cast<int>(agents.size())) {
            obs.insert(obs.end(), TGT_FLOATS, 0.f);
        } else {
            const PlacedAgent& tgt = agents[static_cast<std::size_t>(ti)];
            Agent::Stats s = bm.getAgentStats(ti);

            // Chebyshev distance from attacker's footprint to nearest target cell.
            int atk_sz  = 1;
            Cell atk_org{0, 0};
            if (attacker_idx >= 0 &&
                    attacker_idx < static_cast<int>(agents.size())) {
                const PlacedAgent& atk =
                    agents[static_cast<std::size_t>(attacker_idx)];
                atk_sz  = atk.agent->getSize();
                atk_org = atk.origin;
            }
            int tgt_sz = tgt.agent->getSize();

            int min_dist = std::numeric_limits<int>::max();
            for (int tr = tgt.origin.row; tr < tgt.origin.row + tgt_sz; ++tr)
                for (int tc = tgt.origin.col; tc < tgt.origin.col + tgt_sz; ++tc)
                    min_dist = std::min(min_dist,
                                        chebyshevToFootprint(tc, tr, atk_org, atk_sz));

            bool los = bm.hasLineOfSight(atk_org, atk_sz,
                                          tgt.origin, tgt_sz);

            appendAgentBlock(obs, s,
                             tgt.origin.col, tgt.origin.row, cols, rows);
            obs.push_back(static_cast<float>(min_dist) / static_cast<float>(maxDim));
            obs.push_back(los ? 1.f : 0.f);
        }
        ++n;
    }

    // Zero-pad any unused target slots.
    while (n < max_targets) {
        obs.insert(obs.end(), TGT_FLOATS, 0.f);
        ++n;
    }

    return obs;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Spell helpers
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::spellAttackMod(const Agent::Stats& s) noexcept
{
    auto abilityScore = [&]() -> int {
        switch (s.spellcasting_ability) {
            case 0: return s.str;
            case 1: return s.dex;
            case 2: return s.con;
            case 3: return s.intel;
            case 4: return s.wis;
            default: return s.cha;
        }
    }();
    int m = (abilityScore - 10) / 2;
    if (abilityScore < 10 && (abilityScore - 10) % 2 != 0) --m;
    return s.prof_bonus + m;
}

int CombatEngine::spellSaveDc(const Agent::Stats& s) noexcept
{
    return 8 + spellAttackMod(s);
}

// ─────────────────────────────────────────────────────────────────────────────
//  AoE target resolver  (1 cell = 5 ft, D&D standard)
// ─────────────────────────────────────────────────────────────────────────────

static std::vector<int> resolveAoeTargets(
    std::span<const PlacedAgent> agents,
    const Spell& sp,
    int caster_idx,
    int aoe_col, int aoe_row)
{
    std::vector<int> targets;
    const int n = static_cast<int>(agents.size());

    const Cell& cc = agents[static_cast<std::size_t>(caster_idx)].origin;
    const float cx = static_cast<float>(cc.col);
    const float cy = static_cast<float>(cc.row);
    const float ax = static_cast<float>(aoe_col);
    const float ay = static_cast<float>(aoe_row);

    for (int i = 0; i < n; ++i) {
        const Cell& tc = agents[static_cast<std::size_t>(i)].origin;
        const float tx = static_cast<float>(tc.col);
        const float ty = static_cast<float>(tc.row);
        bool in_area = false;

        switch (sp.geometry) {

        case Spell::Sphere: {
            float dx = tx - ax, dy = ty - ay;
            float dist_ft = std::sqrt(dx*dx + dy*dy) * 5.0f;
            in_area = dist_ft <= static_cast<float>(sp.radius);
            break;
        }

        case Spell::Cone: {
            // Direction from caster toward the aimed point.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) { in_area = (i == caster_idx); break; }
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float plen = std::sqrt(px*px + py*py);
            float dist_ft = plen * 5.0f;
            // 60° cone half-angle: cos(30°) ≈ 0.866
            in_area = (plen >= 0.001f)
                   && dist_ft <= static_cast<float>(sp.radius)
                   && (px*ux + py*uy) / plen >= 0.866f;
            break;
        }

        case Spell::Line: {
            // Direction from caster toward the aimed endpoint.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) break;
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float along_ft = (px*ux + py*uy) * 5.0f;
            float perp_ft  = std::abs(-py*ux + px*uy) * 5.0f;
            in_area = along_ft >= 0.0f
                   && along_ft <= static_cast<float>(sp.length)
                   && perp_ft  <= static_cast<float>(sp.width) / 2.0f;
            break;
        }

        case Spell::Square:
        case Spell::Rectangle: {
            // Rectangle/Square centered on aimed point, using width and length
            float dx_ft = std::abs(tx - ax) * 5.0f;
            float dy_ft = std::abs(ty - ay) * 5.0f;
            in_area = dx_ft <= static_cast<float>(sp.width) / 2.0f
                   && dy_ft <= static_cast<float>(sp.length) / 2.0f;
            break;
        }

        default:
            break;
        }

        if (in_area) targets.push_back(i);
    }
    return targets;
}

// ─────────────────────────────────────────────────────────────────────────────
//  executeSpell
// ─────────────────────────────────────────────────────────────────────────────

SpellResult CombatEngine::executeSpell(BattleMap& bm, const SpellAction& action)
{
    SpellResult result;
    auto agents = bm.placedAgents();

    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size()))
        return result;
    const PlacedAgent& caster_pa = agents[static_cast<std::size_t>(action.caster_idx)];
    if (caster_pa.agent->getConditions().incapacitated) return result;

    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size()))
        return result;
    const Spell& sp = spells[static_cast<std::size_t>(action.spell_idx)];

    result.valid       = true;
    result.spell_idx   = action.spell_idx;
    result.spell_name  = sp.name;
    result.attack_type = sp.attack_type;

    const Agent::Stats& caster_stats = caster_pa.stats;

    // Concentration management: check if casting a concentration spell
    if (sp.requires_concentration) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        if (cond.concentrating) {
            // Drop previous concentration
            result.concentration_replaced    = true;
            result.prev_concentration_spell  = cond.concentrating_on;
            cond.concentrating    = false;
            cond.concentrating_on = {};
            bm.setAgentConditions(action.caster_idx, cond);
        }
    }

    const std::vector<int> targets =
        (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple)
        ? action.target_indices
        : resolveAoeTargets(agents, sp, action.caster_idx, action.aoe_col, action.aoe_row);

    for (int tgt_idx : targets) {
        if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;

        Agent::Stats tgt_stats = bm.getAgentStats(tgt_idx);
        SpellTargetResult tr;
        tr.target_idx = tgt_idx;
        tr.hp_before  = tgt_stats.hp_cur;

        switch (sp.attack_type) {

        case Spell::AttackRoll: {
            // Apply advantage/disadvantage from caster conditions
            bool caster_adv = caster_pa.agent->hasAdvantage();
            bool caster_dis = caster_pa.agent->hasDisadvantage();

            // Apply engagement disadvantage for ranged spells
            if (sp.range > 0 && isThreatened(bm, action.caster_idx)) {
                caster_dis = true;
                log_("Disadvantage: threatened (enemy within 10 ft)");
            }
            if (caster_pa.agent->hasDisadvantage())
                log_("Disadvantage: condition");
            if (caster_pa.agent->hasAdvantage())
                log_("Advantage: condition");

            int d20_val;
            if (caster_adv && caster_dis) {
                d20_val = roll(20);  // Cancel out
            } else if (caster_adv) {
                d20_val = rollAdvantage(20);
            } else if (caster_dis) {
                d20_val = rollDisadvantage(20);
            } else {
                d20_val = roll(20);
            }
            int mod     = spellAttackMod(caster_stats);
            int total   = d20_val + mod;
            tr.d20        = d20_val;
            tr.attack_mod = mod;
            tr.total_roll = total;
            tr.target_ac  = tgt_stats.ac;
            tr.critical   = (d20_val == 20);
            tr.hit        = tr.critical || (d20_val != 1 && total >= tgt_stats.ac);

            if (tr.hit) {
                std::vector<int> dice;
                int dmg = 0;

                // Roll per-damage-type damage and apply target's multipliers
                for (const auto& roll_info : sp.magic_damage_rolls) {
                    int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                    int type_damage = 0;
                    for (int i = 0; i < n_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    // Apply target's resistance/vulnerability/immunity multiplier
                    float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    std::cerr << "[DAMAGE] Spell attack: type=" << static_cast<int>(roll_info.type)
                              << " base=" << type_damage << " mult=" << multiplier
                              << " result=" << modified_damage << std::endl;
                    dmg += modified_damage;
                }
                for (const auto& roll_info : sp.physical_damage_rolls) {
                    int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                    int type_damage = 0;
                    for (int i = 0; i < n_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    // Apply target's resistance/vulnerability/immunity multiplier
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    dmg += modified_damage;
                }

                tr.dice_results = dice;
                if (sp.type == Spell::Heal) {
                    tr.total_healing = std::max(0, dmg);
                    tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                                tgt_stats.hp_cur + tr.total_healing);
                } else {
                    tr.total_damage  = std::max(0, dmg);
                    // Temporary HP absorbs damage first, then overflow damages hp_cur
                    int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                    tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
                }
            }

            // Generate log message
            std::string crit_str = tr.critical ? " CRIT!" : "";
            std::string result_str = tr.total_healing ? "HEAL" : (tr.total_damage > 0 ? "HIT" : "HIT");
            std::string damage_str = std::to_string(tr.total_healing ? tr.total_healing : tr.total_damage);
            std::string down_str = tr.target_down ? " — DOWN" : "";

            if (tr.hit) {
                tr.log_message = "HIT (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")"
                    + crit_str + " " + damage_str + down_str;
            } else {
                tr.log_message = "miss (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")";
            }
            break;
        }

        case Spell::Save: {
            int save_dc  = spellSaveDc(caster_stats);
            // Apply advantage/disadvantage from target conditions
            const PlacedAgent& target_pa = agents[static_cast<std::size_t>(tgt_idx)];
            bool target_adv = target_pa.agent->hasAdvantage();
            bool target_dis = target_pa.agent->hasDisadvantage();
            int save_d20;
            if (target_adv && target_dis) {
                save_d20 = roll(20);  // Cancel out
            } else if (target_adv) {
                save_d20 = rollAdvantage(20);
            } else if (target_dis) {
                save_d20 = rollDisadvantage(20);
            } else {
                save_d20 = roll(20);
            }
            auto saveMod = [&](Spell::SaveAbility_t ab) -> int {
                int score = 0; bool prof = false;
                switch (ab) {
                    case Spell::SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                    case Spell::SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                    case Spell::SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                    case Spell::SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                    case Spell::SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                    default:             score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                }
                int m = (score - 10) / 2;
                if (score < 10 && (score - 10) % 2 != 0) --m;
                return m + (prof ? tgt_stats.prof_bonus : 0);
            };
            tr.save_d20 = save_d20;
            tr.save_dc  = save_dc;
            tr.saved = (save_d20 + saveMod(sp.save_ability) >= save_dc);

            std::vector<int> dice;
            int dmg = 0;

            // Roll per-damage-type damage and apply target's multipliers
            for (const auto& roll_info : sp.magic_damage_rolls) {
                int type_damage = 0;
                for (int i = 0; i < roll_info.num_dice; ++i) {
                    int d = roll(roll_info.die_size);
                    dice.push_back(d);
                    type_damage += d;
                }
                type_damage += roll_info.bonus;
                // Apply target's resistance/vulnerability/immunity multiplier first
                float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                // Then apply half damage on successful save
                if (tr.saved) modified_damage /= 2;
                dmg += modified_damage;
            }
            for (const auto& roll_info : sp.physical_damage_rolls) {
                int type_damage = 0;
                for (int i = 0; i < roll_info.num_dice; ++i) {
                    int d = roll(roll_info.die_size);
                    dice.push_back(d);
                    type_damage += d;
                }
                type_damage += roll_info.bonus;
                // Apply target's resistance/vulnerability/immunity multiplier first
                float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                // Then apply half damage on successful save
                if (tr.saved) modified_damage /= 2;
                dmg += modified_damage;
            }

            tr.dice_results = dice;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, dmg);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, dmg);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        case Spell::Automatic:
        default: {
            std::vector<int> dice;
            int total = 0;

            // Roll per-damage-type damage and apply target's multipliers
            for (const auto& roll_info : sp.magic_damage_rolls) {
                int type_damage = 0;
                for (int i = 0; i < roll_info.num_dice; ++i) {
                    int d = roll(roll_info.die_size);
                    dice.push_back(d);
                    type_damage += d;
                }
                type_damage += roll_info.bonus;
                // Apply target's resistance/vulnerability/immunity multiplier
                float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                total += modified_damage;
            }
            for (const auto& roll_info : sp.physical_damage_rolls) {
                int type_damage = 0;
                for (int i = 0; i < roll_info.num_dice; ++i) {
                    int d = roll(roll_info.die_size);
                    dice.push_back(d);
                    type_damage += d;
                }
                type_damage += roll_info.bonus;
                // Apply target's resistance/vulnerability/immunity multiplier
                float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                total += modified_damage;
            }

            tr.dice_results = dice;
            tr.hit = true;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, total);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, total);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        } // switch

        tr.hp_after    = tgt_stats.hp_cur;
        tr.target_down = (tgt_stats.hp_cur <= 0);
        bm.setAgentStats(tgt_idx, tgt_stats);
        result.target_results.push_back(tr);
    }

    // Register persistent effects (duration > 1 means per-tick damage/heal on
    // subsequent turns; we already applied the first application above).
    if (sp.duration > 1) {
        for (int tgt_idx : targets) {
            if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;
            ActiveEffect fx;
            fx.caster_idx      = action.caster_idx;
            fx.target_idx      = tgt_idx;
            fx.spell           = sp;
            fx.turns_remaining = sp.duration - 1;
            activeEffects_.push_back(fx);
        }
    }

    // Set concentration after successful spell cast (if required)
    if (sp.requires_concentration && result.valid) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        cond.concentrating    = true;
        cond.concentrating_on = sp.name;
        bm.setAgentConditions(action.caster_idx, cond);
    }

    // Decrement resources (uses or spell slots) after successful cast
    if (result.valid) {
        PlacedAgent& pa = bm.placedAgentMut(action.caster_idx);
        Spell& spell_mut = pa.spells[static_cast<std::size_t>(action.spell_idx)];
        Agent::Stats& stats = pa.stats;

        // Mark leveled spell cast (once per turn, even if upcasted)
        if (sp.level > 0) {
            stats.markLeveledSpellCast(sp.level);
        }

        if (stats.is_npc) {
            // NPC: decrement N/day uses
            if (spell_mut.uses_max > 0) {
                spell_mut.uses_remaining = std::max(0, spell_mut.uses_remaining - 1);
            }
        } else {
            // Player: decrement spell slot (if not a cantrip)
            int slot_level = action.slot_level > 0 ? action.slot_level : sp.level;
            if (slot_level > 0 && slot_level <= 9) {
                auto& slots = stats.spell_slots_remaining;
                slots[static_cast<std::size_t>(slot_level - 1)] =
                    std::max(0, slots[static_cast<std::size_t>(slot_level - 1)] - 1);
            }
        }
    }

    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Tick persistent effects
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::tickEffects(BattleMap& bm)
{
    auto agents = bm.placedAgents();
    for (auto& fx : activeEffects_) {
        if (fx.turns_remaining <= 0) continue;
        --fx.turns_remaining;

        if (fx.target_idx < 0 || fx.target_idx >= static_cast<int>(agents.size())) continue;
        Agent::Stats s = bm.getAgentStats(fx.target_idx);

        std::vector<int> dice;
        int total = 0;

        // Roll per-damage-type damage
        // Roll per-damage-type damage and apply target's multipliers
        for (const auto& roll_info : fx.spell.magic_damage_rolls) {
            int type_damage = 0;
            for (int i = 0; i < roll_info.num_dice; ++i) {
                int d = roll(roll_info.die_size);
                dice.push_back(d);
                type_damage += d;
            }
            // Apply target's resistance/vulnerability/immunity multiplier
            float multiplier = s.magic_damage_multipliers[roll_info.type];
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }
        for (const auto& roll_info : fx.spell.physical_damage_rolls) {
            int type_damage = 0;
            for (int i = 0; i < roll_info.num_dice; ++i) {
                int d = roll(roll_info.die_size);
                dice.push_back(d);
                type_damage += d;
            }
            // Apply target's resistance/vulnerability/immunity multiplier
            float multiplier = s.physical_damage_multipliers[roll_info.type];
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }

        if (fx.spell.type == Spell::Heal)
            s.hp_cur = std::min(s.hp_max, s.hp_cur + std::max(0, total));
        else {
            int damage = std::max(0, total);
            // Temporary HP absorbs damage first, then overflow damages hp_cur
            int overflow = std::max(0, damage - s.temp_hp);
            s.temp_hp = std::max(0, s.temp_hp - damage);
            s.hp_cur = std::max(0, s.hp_cur - overflow);
        }

        bm.setAgentStats(fx.target_idx, s);
    }

    auto expired = [](const ActiveEffect& fx) { return fx.turns_remaining <= 0; };
    activeEffects_.erase(
        std::remove_if(activeEffects_.begin(), activeEffects_.end(), expired),
        activeEffects_.end());
}

const std::vector<ActiveEffect>& CombatEngine::activeEffects() const noexcept
{
    return activeEffects_;
}

void CombatEngine::clearEffects() noexcept
{
    activeEffects_.clear();
}

ConcentrationSaveResult CombatEngine::concentrationSave(
        BattleMap& bm, int agent_idx, int damage_taken)
{
    ConcentrationSaveResult r;
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating) return r;

    r.checked    = true;
    r.spell_name = cond.concentrating_on;
    r.save_dc    = std::max(10, damage_taken / 2);

    // Apply advantage/disadvantage from agent conditions
    bool has_adv = cond.has_advantage;
    bool has_dis = cond.has_disadvantage;
    int save_d20;
    if (has_adv && has_dis) {
        save_d20 = roll(20);  // Cancel out
    } else if (has_adv) {
        save_d20 = rollAdvantage(20);
    } else if (has_dis) {
        save_d20 = rollDisadvantage(20);
    } else {
        save_d20 = roll(20);
    }
    r.save_d20   = save_d20;

    Agent::Stats s = bm.getAgentStats(agent_idx);
    int con_mod = (s.con - 10) / 2;
    if (s.con < 10 && (s.con - 10) % 2 != 0) --con_mod;
    con_mod += s.save_prof_con ? s.prof_bonus : 0;
    r.con_mod = con_mod;
    r.passed  = (r.save_d20 + con_mod >= r.save_dc);

    if (!r.passed) {
        r.concentration_lost  = true;
        cond.concentrating    = false;
        cond.concentrating_on = {};
        bm.setAgentConditions(agent_idx, cond);
    }
    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
//  availableCastableSpells – filter spells by resource availability
// ─────────────────────────────────────────────────────────────────────────────

std::vector<int> CombatEngine::availableCastableSpells(
        const BattleMap& bm, int agent_idx) const
{
    std::vector<int> result;
    const auto& agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return result;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.stats;
    const auto& spells = pa.spells;

    for (size_t i = 0; i < spells.size(); ++i) {
        const Spell& spell = spells[i];

        // Cantrips (level 0) are always available
        if (spell.level == 0) {
            result.push_back(static_cast<int>(i));
            continue;
        }

        // Check leveled spell per-turn rule
        if (!stats.canCastLeveledSpell()) {
            continue;  // Already cast a leveled spell this turn
        }

        if (stats.is_npc) {
            // NPC: need remaining uses
            if (spell.uses_max > 0 && spell.uses_remaining > 0) {
                result.push_back(static_cast<int>(i));
            }
        } else {
            // Player: need a spell slot at spell.level or higher
            bool hasSlot = false;
            for (int lvl = spell.level; lvl <= 9; ++lvl) {
                if (stats.spell_slots_remaining[static_cast<size_t>(lvl - 1)] > 0) {
                    hasSlot = true;
                    break;
                }
            }
            if (hasSlot) {
                result.push_back(static_cast<int>(i));
            }
        }
    }

    return result;
}

} // namespace rpg
