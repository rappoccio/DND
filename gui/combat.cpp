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

    // If agent is now dead, drop concentration
    if (s.hp_cur <= 0) {
        const auto& agents = bm.placedAgents();
        if (idx >= 0 && static_cast<std::size_t>(idx) < agents.size()) {
            Agent::Conditions cond = bm.getAgentConditions(idx);
            if (cond.concentrating) {
                std::string spell_name = cond.concentrating_on;
                cond.concentrating = false;
                cond.concentrating_on = "";
                bm.setAgentConditions(idx, cond);
                // Remove spell effects from this agent's concentration spell
                const auto& effects = bm.activeSpellEffects();
                std::vector<int> to_remove;
                for (const auto& effect : effects) {
                    if (effect.caster_idx == idx && effect.spell.name == spell_name) {
                        to_remove.push_back(effect.effect_id);
                    }
                }
                for (int effect_id : to_remove) {
                    bm.removeSpellEffect(effect_id);
                }
            }
        }
    }

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

int CombatEngine::calculateAC(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return 10;  // default AC

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    int ac = pa.stats.base_ac;

    // Calculate DEX modifier and determine cap from equipped armor
    int dex_mod = (pa.stats.dex - 10) / 2;
    int dex_mod_cap = 30;  // Default: no cap (light armor/unarmored)

    // Find the most restrictive DEX modifier cap from equipped armor
    for (const auto& piece : pa.armor) {
        if (!piece.name.empty()) {
            // Most restrictive cap wins (e.g., heavy armor overrides light)
            dex_mod_cap = std::min(dex_mod_cap, piece.dex_mod_cap);
        }
    }

    // Apply capped DEX modifier
    int capped_dex_mod = std::min(dex_mod, dex_mod_cap);
    ac += capped_dex_mod;

    // Add armor piece bonuses
    for (const auto& piece : pa.armor) {
        if (!piece.name.empty()) {
            ac += piece.ac_bonus;
        }
    }

    // Add shield bonus (off-hand weapon with ac_bonus)
    if (!pa.weapons.empty() && pa.weapons.size() > 1) {
        const Weapon& shield = pa.weapons.back();
        if (shield.name.find("Shield") != std::string::npos || shield.off_hand) {
            ac += shield.ac_bonus;
        }
    }

    // Add temporary modifications
    ac += pa.stats.ac_temporary_modifications;

    // TODO: Apply condition modifiers (prone, etc.)

    return ac;
}

void CombatEngine::applyArmorMultipliers(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    Agent::Stats s = bm.getAgentStats(agent_idx);

    // Start with base multipliers (1.0 = normal, 0.5 = resist, 2.0 = vuln, 0 = immune)
    // Loop through armor pieces and merge multipliers (most restrictive wins)

    for (const auto& piece : pa.armor) {
        if (piece.name.empty()) continue;

        // Merge magic damage multipliers
        for (int damage_type = 0; damage_type < NumMagicDamage_t; ++damage_type) {
            float armor_mult = piece.magic_damage_multipliers[damage_type];
            if (armor_mult == 1.0f) continue;  // No effect, skip

            float& current = s.magic_damage_multipliers[damage_type];

            // Most restrictive wins: 0 (immune) > 2.0 (vuln) > 0.5 (resist) > 1.0 (normal)
            if (armor_mult == 0.f) {
                current = 0.f;  // Immunity
            } else if (armor_mult > 1.f && current < 2.f) {
                current = armor_mult;  // Vulnerability (if not already immune)
            } else if (armor_mult < 1.f && current > 0.5f && current != 2.f) {
                current = armor_mult;  // Resistance (if not vulnerable/immune)
            }
        }

        // Merge physical damage multipliers
        for (int damage_type = 0; damage_type < NumPhysicalDamage_t; ++damage_type) {
            float armor_mult = piece.physical_damage_multipliers[damage_type];
            if (armor_mult == 1.0f) continue;  // No effect, skip

            float& current = s.physical_damage_multipliers[damage_type];

            // Most restrictive wins: 0 (immune) > 2.0 (vuln) > 0.5 (resist) > 1.0 (normal)
            if (armor_mult == 0.f) {
                current = 0.f;  // Immunity
            } else if (armor_mult > 1.f && current < 2.f) {
                current = armor_mult;  // Vulnerability (if not already immune)
            } else if (armor_mult < 1.f && current > 0.5f && current != 2.f) {
                current = armor_mult;  // Resistance (if not vulnerable/immune)
            }
        }
    }

    bm.setAgentStats(agent_idx, s);
}

bool CombatEngine::canEquipArmor(const BattleMap& bm, int agent_idx, const Armor& armor) const noexcept
{
    // If armor has no STR requirement, it can always be equipped
    if (!armor.requires_strength)
        return true;

    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    return pa.stats.str >= armor.str_requirement;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Per-agent movement budget
// ─────────────────────────────────────────────────────────────────────────────

TurnStartResult CombatEngine::beginTurn(BattleMap& bm, int agent_idx) noexcept
{
    TurnStartResult result;

    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return result;

    // Reset slip distance counter and slipped flag for the new turn
    slipDistanceMoved_[agent_idx] = 0;
    agents[static_cast<std::size_t>(agent_idx)].agent->setSlippedThisTurn(false);

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    const auto& stats = agent.stats;

    // Check for incapacitating conditions first (Paralyzed, Incapacitated, Stunned)
    // These always cause a turn skip unless the agent succeeds on a save
    for (auto& active_cond : activeAgentConditions_) {
        if (active_cond.agent_idx != agent_idx) continue;
        if (active_cond.condition_name != "Paralyzed" &&
            active_cond.condition_name != "Incapacitated" &&
            active_cond.condition_name != "Stunned") continue;

        // If save_repeat_turns == -1, skip turn without attempt
        if (active_cond.save_repeat_turns == -1) {
            result.turn_skipped = true;
            result.skip_reason = active_cond.condition_name;
            log_("Turn skipped by {} (no save allowed)", active_cond.condition_name);
            return result;
        }

        // Check if it's time for a save
        if (active_cond.next_save_turn > 0) continue;

        // Helper to get ability modifier
        auto getSaveMod = [&](SaveAbility_t ability) -> int {
            int score = 0;
            bool prof = false;
            switch (ability) {
                case SaveStr: score = stats.str; prof = stats.save_prof_str; break;
                case SaveDex: score = stats.dex; prof = stats.save_prof_dex; break;
                case SaveCon: score = stats.con; prof = stats.save_prof_con; break;
                case SaveInt: score = stats.intel; prof = stats.save_prof_intel; break;
                case SaveWis: score = stats.wis; prof = stats.save_prof_wis; break;
                default: score = stats.cha; prof = stats.save_prof_cha; break;
            }
            int mod = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --mod;
            return mod + (prof ? stats.prof_bonus : 0);
        };

        int save_mod = getSaveMod(active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod;
        int save_dc = active_cond.save_dc;

        auto ability_name = [](SaveAbility_t ab) -> std::string {
            switch (ab) {
                case SaveStr: return "STR";
                case SaveDex: return "DEX";
                case SaveCon: return "CON";
                case SaveInt: return "INT";
                case SaveWis: return "WIS";
                default: return "CHA";
            }
        };

        if (save_total >= save_dc) {
            // Save succeeded, remove condition
            removeAgentCondition(active_cond.condition_id);

            // Handle condition-specific cleanup
            if (active_cond.condition_name == "Paralyzed") {
                Agent::Conditions cond = bm.getAgentConditions(agent_idx);
                cond.paralyzed = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Incapacitated") {
                Agent::Conditions cond = bm.getAgentConditions(agent_idx);
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Stunned") {
                Agent::Conditions cond = bm.getAgentConditions(agent_idx);
                cond.stunned = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            }

            // Drop the caster's concentration on the spell that caused this condition
            if (active_cond.caster_idx >= 0 && active_cond.caster_idx < static_cast<int>(agents.size())) {
                Agent::Conditions caster_cond = bm.getAgentConditions(active_cond.caster_idx);
                if (caster_cond.concentrating) {
                    caster_cond.concentrating = false;
                    caster_cond.concentrating_on = "";
                    bm.setAgentConditions(active_cond.caster_idx, caster_cond);
                    log_("Caster (agent[{}]) drops concentration", active_cond.caster_idx);

                    // Remove all conditions caused by concentration spells from this caster
                    const auto& caster_spells = bm.getAgentSpells(active_cond.caster_idx);
                    std::vector<int> conds_to_remove;
                    for (const auto& other_cond : activeAgentConditions_) {
                        if (other_cond.caster_idx == active_cond.caster_idx &&
                            other_cond.spell_idx >= 0 &&
                            other_cond.spell_idx < static_cast<int>(caster_spells.size())) {
                            if (caster_spells[static_cast<std::size_t>(other_cond.spell_idx)].requires_concentration) {
                                conds_to_remove.push_back(other_cond.condition_id);
                            }
                        }
                    }
                    for (int cond_id : conds_to_remove) {
                        removeAgentCondition(cond_id);
                    }
                }
            }

            result.save_roll_message = ability_name(active_cond.save_ability) + " save vs " + active_cond.condition_name +
                                      " — SAVED! (" + active_cond.condition_name + " broken)";
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — SAVED!",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        } else {
            // Save failed, skip this turn (only for incapacitating conditions)
            if (active_cond.condition_name == "Paralyzed" || active_cond.condition_name == "Incapacitated" || active_cond.condition_name == "Stunned") {
                result.turn_skipped = true;
                result.skip_reason = active_cond.condition_name + " (save failed)";
                result.save_roll_message = ability_name(active_cond.save_ability) + " save vs " + active_cond.condition_name +
                                          " — FAILED (turn skipped)";
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED (turn skipped)",
                     ability_name(active_cond.save_ability), active_cond.condition_name,
                     save_d20, save_mod, save_total, save_dc);
                return result;
            } else {
                // Non-incapacitating condition failed save, reset next save time
                active_cond.next_save_turn = active_cond.save_repeat_turns;
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED",
                     ability_name(active_cond.save_ability), active_cond.condition_name,
                     save_d20, save_mod, save_total, save_dc);
            }
        }
        break;  // Only check one condition per turn
    }

    // Check for non-incapacitating conditions that allow save repeats
    for (auto& active_cond : activeAgentConditions_) {
        if (active_cond.agent_idx != agent_idx) continue;
        if (active_cond.condition_name == "Paralyzed" ||
            active_cond.condition_name == "Incapacitated" ||
            active_cond.condition_name == "Stunned") continue;  // Skip incapacitating conditions

        if (active_cond.save_repeat_turns == -1) continue;  // Never allows saves
        if (active_cond.next_save_turn > 0) continue;  // Not time to save yet

        // Helper to get ability modifier
        auto getSaveMod = [&](SaveAbility_t ability) -> int {
            int score = 0;
            bool prof = false;
            switch (ability) {
                case SaveStr: score = stats.str; prof = stats.save_prof_str; break;
                case SaveDex: score = stats.dex; prof = stats.save_prof_dex; break;
                case SaveCon: score = stats.con; prof = stats.save_prof_con; break;
                case SaveInt: score = stats.intel; prof = stats.save_prof_intel; break;
                case SaveWis: score = stats.wis; prof = stats.save_prof_wis; break;
                default: score = stats.cha; prof = stats.save_prof_cha; break;
            }
            int mod = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --mod;
            return mod + (prof ? stats.prof_bonus : 0);
        };

        int save_mod = getSaveMod(active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod;
        int save_dc = active_cond.save_dc;

        auto ability_name = [](SaveAbility_t ab) -> std::string {
            switch (ab) {
                case SaveStr: return "STR";
                case SaveDex: return "DEX";
                case SaveCon: return "CON";
                case SaveInt: return "INT";
                case SaveWis: return "WIS";
                default: return "CHA";
            }
        };

        if (save_total >= save_dc) {
            // Save succeeded, remove condition
            removeAgentCondition(active_cond.condition_id);
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — SAVED!",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        } else {
            // Save failed, reset next save time
            active_cond.next_save_turn = active_cond.save_repeat_turns;
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        }
        break;  // Only check one condition per turn
    }

    // Seed movement budgets from current stats
    walkRemaining_[agent_idx] = stats.speed_walk;
    flyRemaining_ [agent_idx] = stats.speed_fly;
    swimRemaining_[agent_idx] = stats.speed_swim;
    burrowRemaining_[agent_idx] = stats.speed_burrow;

    // Reset per-turn conditions
    agent.agent->turn();

    // Reset leveled spell cast flag
    auto new_stats = stats;
    new_stats.resetLeveledSpellCastFlag();
    bm.setAgentStats(agent_idx, new_stats);

    // Apply begin-of-turn spell effects
    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_begin_turn) continue;
        if (effect.caster_idx == agent_idx) continue;  // don't damage self

        // Check if agent occupies any cell in the effect (only apply once per effect)
        bool in_effect = false;
        for (int c = agent.origin.col; c < agent.origin.col + agent.agent->getSize() && !in_effect; ++c) {
            for (int r = agent.origin.row; r < agent.origin.row + agent.agent->getSize() && !in_effect; ++r) {
                auto it = std::find(effect.cells.begin(), effect.cells.end(), Cell{c, r});
                if (it != effect.cells.end()) {
                    applySpellEffect(bm, effect, agent_idx);
                    in_effect = true;
                }
            }
        }
    }

    return result;
}

void CombatEngine::endTurn(BattleMap& bm, int agent_idx) noexcept
{
    // Apply end-of-turn spell effects
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_end_turn) continue;
        if (effect.caster_idx == agent_idx) continue;  // don't damage self

        // Check if agent occupies any cell in the effect (only apply once per effect)
        bool in_effect = false;
        for (int c = agent.origin.col; c < agent.origin.col + agent.agent->getSize() && !in_effect; ++c) {
            for (int r = agent.origin.row; r < agent.origin.row + agent.agent->getSize() && !in_effect; ++r) {
                auto it = std::find(effect.cells.begin(), effect.cells.end(), Cell{c, r});
                if (it != effect.cells.end()) {
                    applySpellEffect(bm, effect, agent_idx);
                    in_effect = true;
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Movement (with spell effect checking)
// ─────────────────────────────────────────────────────────────────────────────

// Helper: get all cells along a line from start to end (Bresenham-like)
static std::vector<Cell> getCellsAlongPath(Cell start, Cell end) noexcept
{
    std::vector<Cell> cells;
    int x0 = start.col, y0 = start.row;
    int x1 = end.col, y1 = end.row;

    int dx = std::abs(x1 - x0);
    int dy = std::abs(y1 - y0);
    int sx = (x0 < x1) ? 1 : -1;
    int sy = (y0 < y1) ? 1 : -1;
    int err = dx - dy;

    int x = x0, y = y0;
    while (true) {
        cells.push_back(Cell{x, y});
        if (x == x1 && y == y1) break;

        int e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            x += sx;
        }
        if (e2 < dx) {
            err += dx;
            y += sy;
        }
    }
    return cells;
}

bool CombatEngine::moveAgent(BattleMap& bm, int idx, Cell newOrigin, MovementType type) noexcept
{
    // Get old position before moving
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;
    Cell oldOrigin = agents[static_cast<std::size_t>(idx)].origin;

    // Delegate to BattleMap for pathfinding and movement budget logic
    if (!bm.moveAgent(idx, newOrigin, type))
        return false;

    // Check for spell effects along the path from old to new position
    std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);

    // Track which effects we've already applied to avoid double-hits
    std::unordered_set<int> appliedEffects;

    for (const auto& pathCell : pathCells) {
        for (const auto& effect : bm.activeSpellEffects()) {
            if (appliedEffects.count(effect.effect_id)) continue;  // Already applied this effect
            if (effect.caster_idx == idx) continue;  // Don't damage self

            // Check if this path cell is in the effect
            auto it = std::find(effect.cells.begin(), effect.cells.end(), pathCell);
            if (it != effect.cells.end()) {
                applySpellEffect(bm, effect, idx);
                appliedEffects.insert(effect.effect_id);
            }
        }
    }

    // Check for slipping terrain (ice/grease) along the path
    checkSlippingTerrain(bm, idx, oldOrigin, newOrigin);

    return true;
}

bool CombatEngine::jumpAgent(BattleMap& bm, int idx, Cell newOrigin, bool is_running) noexcept
{
    // Get old position before jumping
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;
    Cell oldOrigin = agents[static_cast<std::size_t>(idx)].origin;

    // Delegate to BattleMap for jump logic
    if (!bm.jumpAgent(idx, newOrigin, is_running))
        return false;

    // Check for spell effects along the jump path
    std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);

    // Track which effects we've already applied
    std::unordered_set<int> appliedEffects;

    for (const auto& pathCell : pathCells) {
        for (const auto& effect : bm.activeSpellEffects()) {
            if (appliedEffects.count(effect.effect_id)) continue;
            if (effect.caster_idx == idx) continue;

            auto it = std::find(effect.cells.begin(), effect.cells.end(), pathCell);
            if (it != effect.cells.end()) {
                applySpellEffect(bm, effect, idx);
                appliedEffects.insert(effect.effect_id);
            }
        }
    }

    return true;
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
                                          bool disadvantage,
                                          int target_ac)
{
    if (target_ac == -1) target_ac = target.base_ac;
    AttackResult r = rollToHit(w, attacker, target_ac, advantage, disadvantage);
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

    // Check if attacker is charmed and target is the charmer
    if (atk_pt.agent->getConditions().charmed) {
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.attacker_idx &&
                cond.condition_name == "Charmed" &&
                cond.caster_idx == action.target_idx) {
                log_("Attack blocked: attacker is charmed and cannot attack the charmer");
                return invalid;
            }
        }
    }

    // Check if attacker slipped this turn
    if (atk_pt.agent->hasSlippedThisTurn()) {
        log_("Attack blocked: attacker slipped and cannot act this turn");
        return invalid;
    }

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
    bool is_ranged = (w.type == WeaponType::Ranged);
    if (is_ranged && isThreatened(bm, action.attacker_idx)) {
        disadv = true;
    }

    // Check agent conditions for advantage/disadvantage
    bool adv = atk_pt.agent->hasAdvantage();
    bool dis = disadv || atk_pt.agent->hasDisadvantage();

    // Attacker blinded: attacks have disadvantage
    const Agent::Conditions& atk_cond = atk_pt.agent->getConditions();
    if (atk_cond.blinded) {
        dis = true;
        log_("Disadvantage: attacker is blinded");
    }

    // Target is paralyzed: attacker gets advantage
    const Agent::Conditions& tgt_cond = tgt_pt.agent->getConditions();
    if (tgt_cond.paralyzed) {
        adv = true;
        log_("Advantage: target is paralyzed");
    }

    // Target is blinded: attacker gets advantage
    if (tgt_cond.blinded) {
        adv = true;
        log_("Advantage: target is blinded");
    }

    // Target is stunned: attacker gets advantage
    if (tgt_cond.stunned) {
        adv = true;
        log_("Advantage: target is stunned");
    }

    // Target is prone: advantage for melee attacks within 5 feet, disadvantage for ranged
    if (tgt_cond.prone) {
        int dc = std::max({atk_pt.origin.col - tgt_pt.origin.col,
                           tgt_pt.origin.col - (atk_pt.origin.col + atk_sz - 1),
                           0});
        int dr = std::max({atk_pt.origin.row - tgt_pt.origin.row,
                           tgt_pt.origin.row - (atk_pt.origin.row + atk_sz - 1),
                           0});
        int dist = std::max(dc, dr);

        // Within 5 feet (1 cell on 5ft/cell grid): attacker gets advantage (melee)
        if (dist <= 1) {
            adv = true;
            log_("Advantage: target is prone and within 5 feet");
        } else if (is_ranged) {
            // Beyond 5 feet with ranged attack: attacker gets disadvantage
            dis = true;
            log_("Disadvantage: target is prone and attacker is beyond 5 feet");
        }
    }

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

    // Calculate target AC (includes base AC, armor, DEX modifier, temp modifications)
    int target_ac = calculateAC(bm, action.target_idx);

    AttackResult r = resolveAttack(w, atk_stats, tgt_stats, adv, dis, target_ac);

    // Automatic critical hit for melee attacks (within 5 ft) against paralyzed targets
    if (tgt_cond.paralyzed && r.hit) {
        int dc = std::max({atk_pt.origin.col - tgt_pt.origin.col,
                           tgt_pt.origin.col - (atk_pt.origin.col + atk_sz - 1),
                           0});
        int dr = std::max({atk_pt.origin.row - tgt_pt.origin.row,
                           tgt_pt.origin.row - (atk_pt.origin.row + atk_sz - 1),
                           0});
        int dist = std::max(dc, dr);

        // Within 5 feet (1 cell on 5ft/cell grid)
        if (dist <= 1) {
            r.critical = true;
            log_("Automatic critical hit: target is paralyzed and within 5 feet");
            // Re-roll damage with crit flag set
            tgt_stats.hp_cur = r.hp_before;  // revert damage
            rollDamage(w, atk_stats, tgt_stats, r);
            int overflow = std::max(0, r.total_damage - tgt_stats.temp_hp);
            tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - r.total_damage);
            tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow,
                                            0, tgt_stats.hp_max);
            r.hp_after = tgt_stats.hp_cur;
            r.target_down = (r.hp_after <= 0);
        }
    }

    bm.setAgentStats(action.target_idx, tgt_stats);  // apply HP change

    // Apply weapon conditions on hit
    if (r.hit && !w.conditions.empty()) {
        for (const auto& weapon_cond : w.conditions) {
            int save_dc = spellSaveDcFromAbility(atk_stats, weapon_cond.save_dc_ability);

            // Target makes a save to resist the condition
            auto getSaveMod = [&](SaveAbility_t ability) -> int {
                int score = 0;
                bool prof = false;
                switch (ability) {
                    case SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                    case SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                    case SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                    case SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                    case SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                    default:             score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                }
                int m = (score - 10) / 2;
                if (score < 10 && (score - 10) % 2 != 0) --m;
                return m + (prof ? tgt_stats.prof_bonus : 0);
            };

            // Check for auto-fail conditions (paralyzed, stunned auto-fail STR/DEX)
            bool auto_fail = (tgt_cond.paralyzed || tgt_cond.stunned) &&
                            (weapon_cond.save_ability == SaveStr || weapon_cond.save_ability == SaveDex);

            int save_d20 = auto_fail ? 1 : roll(20);
            int save_mod = getSaveMod(weapon_cond.save_ability);
            bool saved = auto_fail ? false : (save_d20 + save_mod >= save_dc);

            if (!saved) {
                // Target failed save, apply condition
                ActiveAgentCondition cond;
                cond.agent_idx = action.target_idx;
                cond.caster_idx = action.attacker_idx;
                cond.spell_idx = -1;  // weapon attack, not a spell
                cond.condition_name = weapon_cond.condition_name;
                cond.save_ability = weapon_cond.save_ability;
                cond.turns_remaining = weapon_cond.condition_duration > 0 ? weapon_cond.condition_duration : 10;  // default 10 turns
                cond.save_dc = save_dc;
                cond.save_repeat_turns = weapon_cond.save_repeat_turns;
                cond.next_save_turn = 0;

                [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
                log_("Weapon condition '{}' applied to target (save DC {})",
                     weapon_cond.condition_name, save_dc);
            } else {
                log_("Target resisted weapon condition '{}' (save DC {})",
                     weapon_cond.condition_name, save_dc);
            }
        }
    }

    // Apply weapon push on hit (push_ft > 0 and weapon is proficient)
    if (r.hit && w.proficient) {
        for (const auto& weapon_cond : w.conditions) {
            if (weapon_cond.condition_name == "Push" && weapon_cond.push_ft > 0) {
                if (action.attacker_idx >= 0 && action.attacker_idx < static_cast<int>(agents.size())) {
                    const auto& attacker = agents[action.attacker_idx];
                    int cells_moved = bm.forceMoveAgent(action.target_idx, attacker.origin, weapon_cond.push_ft);
                    r.push_ft_applied = cells_moved * 5;
                    if (cells_moved > 0) {
                        log_("Target pushed {} feet", r.push_ft_applied);
                    }
                }
                break;  // only one push condition per attack
            }
        }
    }

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
    obs.push_back(static_cast<float>(s.base_ac)    / 30.f);
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

int CombatEngine::spellSaveDcFromAbility(const Agent::Stats& s, SaveAbility_t ability) noexcept
{
    auto abilityScore = [&]() -> int {
        switch (ability) {
            case SaveStr:  return s.str;
            case SaveDex:  return s.dex;
            case SaveCon:  return s.con;
            case SaveInt:  return s.intel;
            case SaveWis:  return s.wis;
            default:              return s.cha;
        }
    }();
    int m = (abilityScore - 10) / 2;
    if (abilityScore < 10 && (abilityScore - 10) % 2 != 0) --m;
    return 8 + s.prof_bonus + m;
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
    if (caster_pa.agent->hasSlippedThisTurn()) return result;

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

    // Check if caster is charmed and any target is the charmer
    if (caster_pa.agent->getConditions().charmed) {
        int charmer_idx = -1;
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.caster_idx &&
                cond.condition_name == "Charmed") {
                charmer_idx = cond.caster_idx;
                break;
            }
        }

        if (charmer_idx >= 0) {
            // Check if charmer is in the target list
            for (int tgt_idx : targets) {
                if (tgt_idx == charmer_idx) {
                    log_("Spell blocked: caster is charmed and cannot target the charmer with a damaging spell");
                    return result;  // Invalid (valid = false)
                }
            }
        }
    }

    bool any_conditions_applied = false;

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

            // Blinded: caster's attacks have disadvantage
            if (caster_pa.agent->getConditions().blinded) {
                caster_dis = true;
                log_("Disadvantage: caster is blinded");
            }

            // Apply engagement disadvantage for ranged spells
            if (sp.range > 0 && isThreatened(bm, action.caster_idx)) {
                caster_dis = true;
                log_("Disadvantage: threatened (enemy within 10 ft)");
            }
            if (caster_pa.agent->hasDisadvantage())
                log_("Disadvantage: condition");
            if (caster_pa.agent->hasAdvantage())
                log_("Advantage: condition");

            // Target blinded: attacker has advantage
            bool target_blinded = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().blinded;
            if (target_blinded) {
                caster_adv = true;
                log_("Advantage: target is blinded");
            }

            // Target stunned: attacker has advantage
            bool target_stunned = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().stunned;
            if (target_stunned) {
                caster_adv = true;
                log_("Advantage: target is stunned");
            }

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
            tr.target_ac  = calculateAC(bm, tgt_idx);
            tr.critical   = (d20_val == 20);
            tr.hit        = tr.critical || (d20_val != 1 && total >= tr.target_ac);

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
            const Agent::Conditions& target_cond = target_pa.agent->getConditions();
            bool target_adv = target_pa.agent->hasAdvantage();
            bool target_dis = target_pa.agent->hasDisadvantage();

            // Paralyzed and Stunned targets automatically fail STR and DEX saves
            bool auto_fail = (target_cond.paralyzed || target_cond.stunned) &&
                            (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

            int save_d20;
            if (auto_fail) {
                save_d20 = 1;  // Automatic fail
                std::string reason = target_cond.paralyzed ? "paralyzed" : "stunned";
                log_("Target is {}: automatically fails {} save",
                     reason, sp.save_ability == SaveStr ? "STR" : "DEX");
            } else if (target_adv && target_dis) {
                save_d20 = roll(20);  // Cancel out
            } else if (target_adv) {
                save_d20 = rollAdvantage(20);
            } else if (target_dis) {
                save_d20 = rollDisadvantage(20);
            } else {
                save_d20 = roll(20);
            }
            auto saveMod = [&](SaveAbility_t ab) -> int {
                int score = 0; bool prof = false;
                switch (ab) {
                    case SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                    case SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                    case SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                    case SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                    case SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                    default:             score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                }
                int m = (score - 10) / 2;
                if (score < 10 && (score - 10) % 2 != 0) --m;
                return m + (prof ? tgt_stats.prof_bonus : 0);
            };
            tr.save_d20 = save_d20;
            tr.save_dc  = save_dc;
            tr.saved = auto_fail ? false : (save_d20 + saveMod(sp.save_ability) >= save_dc);

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

        // Check concentration saves: once per damage instance (e.g., once per Magic Missile)
        if (tr.total_damage > 0 && !tr.dice_results.empty()) {
            // For spells with multiple damage instances (dice rolls), check concentration for each
            int num_instances = std::max(1, static_cast<int>(tr.dice_results.size()));
            int damage_per_instance = tr.total_damage / num_instances;
            if (damage_per_instance == 0 && tr.total_damage > 0) {
                damage_per_instance = 1;  // Ensure at least 1 damage per instance
            }
            for (int i = 0; i < num_instances && !tr.concentration_lost; ++i) {
                if (checkConcentrationOnDamage(bm, tgt_idx, damage_per_instance)) {
                    tr.concentration_checked = true;
                    tr.concentration_lost = true;
                }
            }
            if (damage_per_instance > 0) {
                tr.concentration_checked = true;
            }
        }

        // Apply spell-based conditions (e.g., Hold Person applies Paralyzed)
        bool spell_affected_target = false;
        switch (sp.attack_type) {
            case Spell::AttackRoll:
                spell_affected_target = tr.hit;
                break;
            case Spell::Save:
                spell_affected_target = !tr.saved;  // Condition applies on failed save
                break;
            case Spell::Automatic:
            default:
                spell_affected_target = true;  // Automatic hits always apply conditions
                break;
        }

        if (spell_affected_target && !sp.conditions.empty()) {
            for (const auto& spell_cond : sp.conditions) {
                ActiveAgentCondition cond;
                cond.agent_idx   = tgt_idx;
                cond.caster_idx  = action.caster_idx;
                cond.spell_idx   = action.spell_idx;
                cond.condition_name = spell_cond.condition_name;
                cond.save_ability = spell_cond.save_ability;

                // Condition duration: if condition_duration is 0, use spell duration
                cond.turns_remaining = (spell_cond.condition_duration > 0) ? spell_cond.condition_duration : sp.duration;
                // Save DC: use caster's spellcasting ability if SaveSpellcasterMod, else use specified ability
                if (spell_cond.save_dc_ability == SaveSpellcasterMod) {
                    cond.save_dc = spellSaveDc(caster_stats);
                } else {
                    cond.save_dc = spellSaveDcFromAbility(caster_stats, spell_cond.save_dc_ability);
                }
                // How often to repeat save checks
                cond.save_repeat_turns = spell_cond.save_repeat_turns;
                // Target can save at the start of their next turn (next_save_turn == 0 means "save now")
                cond.next_save_turn = 0;

                [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
                any_conditions_applied = true;

                // Apply spell push on failed save
                if (spell_cond.condition_name == "Push" && spell_cond.push_ft > 0 && !tr.saved) {
                    auto spell_agents = bm.placedAgents();
                    if (action.caster_idx >= 0 && action.caster_idx < static_cast<int>(spell_agents.size())) {
                        const auto& caster = spell_agents[action.caster_idx];
                        int cells_moved = bm.forceMoveAgent(tgt_idx, caster.origin, spell_cond.push_ft);
                        tr.push_ft_applied = cells_moved * 5;
                        if (cells_moved > 0) {
                            log_("Target pushed {} feet by {}", tr.push_ft_applied, sp.name);
                        }
                    }
                }
            }
        }

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

    // Set concentration after successful spell cast (if required and if spell affected targets)
    // For condition-based spells, only set concentration if a condition was actually applied
    // For damage/heal spells or AoE terrain spells, set concentration if any targets were affected
    bool should_concentrate = false;
    if (sp.requires_concentration && result.valid) {
        if (!sp.conditions.empty()) {
            // Condition-based spell: only concentrate if a condition was applied
            should_concentrate = any_conditions_applied;
        } else {
            // Damage/heal/terrain spell: concentrate if spell hit any targets
            should_concentrate = true;
        }
    }

    if (should_concentrate) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        cond.concentrating    = true;
        cond.concentrating_on = sp.name;
        bm.setAgentConditions(action.caster_idx, cond);
    }

    // Create persistent spell effect if spell has AoE geometry and duration > 1
    if (result.valid && sp.duration > 1 && sp.geometry != Spell::Single) {
        std::vector<Cell> effect_cells;

        // Calculate cells based on spell geometry
        if (sp.geometry == Spell::Sphere) {
            int radius_cells = (sp.radius + 4) / 5;  // Convert feet to cells (5ft/cell)
            for (int c = action.aoe_col - radius_cells; c <= action.aoe_col + radius_cells; ++c) {
                for (int r = action.aoe_row - radius_cells; r <= action.aoe_row + radius_cells; ++r) {
                    int dc = c - action.aoe_col;
                    int dr = r - action.aoe_row;
                    if (dc * dc + dr * dr <= radius_cells * radius_cells) {
                        effect_cells.push_back(Cell{c, r});
                    }
                }
            }
        } else if (sp.geometry == Spell::Rectangle) {
            // Treat aoe_col/aoe_row as center, like Python's _aoe_cells does
            double w_cells = sp.width / 5.0;
            double l_cells = sp.length / 5.0;
            int cols = bm.gridCols();
            int rows = bm.gridRows();
            for (int c = 0; c < cols; ++c) {
                for (int r = 0; r < rows; ++r) {
                    double dx = std::abs(c - action.aoe_col);
                    double dy = std::abs(r - action.aoe_row);
                    if (dx <= w_cells / 2.0 && dy <= l_cells / 2.0) {
                        effect_cells.push_back(Cell{c, r});
                    }
                }
            }
        } else if (sp.geometry == Spell::Square) {
            double w_cells = sp.width / 5.0;
            double l_cells = sp.length / 5.0;
            int cols = bm.gridCols();
            int rows = bm.gridRows();
            // Center the square on the clicked point
            for (int c = 0; c < cols; ++c) {
                for (int r = 0; r < rows; ++r) {
                    double dx = std::abs(c - action.aoe_col);
                    double dy = std::abs(r - action.aoe_row);
                    if (dx <= w_cells / 2.0 && dy <= l_cells / 2.0) {
                        effect_cells.push_back(Cell{c, r});
                    }
                }
            }
        } else if (sp.geometry == Spell::Line) {
            int length_cells = (sp.length + 4) / 5;
            // Assume horizontal for now (can be enhanced)
            for (int c = action.aoe_col; c < action.aoe_col + length_cells; ++c) {
                effect_cells.push_back(Cell{c, action.aoe_row});
            }
        } else if (sp.geometry == Spell::Cone) {
            int length_cells = (sp.length + 4) / 5;
            // Simple cone approximation (would need direction in real implementation)
            for (int dist = 0; dist < length_cells; ++dist) {
                for (int width = -dist; width <= dist; ++width) {
                    effect_cells.push_back(Cell{action.aoe_col + dist, action.aoe_row + width});
                }
            }
        }

        // Create ActiveSpellEffect if we have cells
        if (!effect_cells.empty()) {
            ActiveSpellEffect effect;
            effect.caster_idx = action.caster_idx;
            effect.spell_idx = action.spell_idx;
            effect.spell = sp;
            effect.cells = effect_cells;
            effect.turns_remaining = sp.duration;
            effect.effect_id = -1;  // Will be assigned by addSpellEffect
            [[maybe_unused]] int effect_id = bm.addSpellEffect(effect);
        }
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
//  Execute a shove attempt (contested Athletics check)
// ─────────────────────────────────────────────────────────────────────────────

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
    int attacker_str_mod = (attacker.stats.str - 10) / 2;
    auto attacker_stats = getAgentStats(bm, action.attacker_idx);
    int attacker_prof = attacker_stats.prof_bonus;
    int attacker_d20 = roll(20);
    int attacker_total = attacker_d20 + attacker_str_mod + attacker_prof;

    // Roll defender: max(Athletics, Acrobatics) = max(STR, DEX) + d20
    int target_str_mod = (target.stats.str - 10) / 2;
    int target_dex_mod = (target.stats.dex - 10) / 2;
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
//  Agent stat and equipment management – delegates to BattleMap
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::addAgentConfig(BattleMap& bm, AgentConfig cfg) noexcept
{
    bm.addAgentConfig(cfg);
}

void CombatEngine::applyAgentConfigs(BattleMap& bm) noexcept
{
    bm.applyAgentConfigs();
}

Agent::Stats CombatEngine::getAgentStats(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentStats(idx);
}

void CombatEngine::setAgentStats(BattleMap& bm, int idx, Agent::Stats s) noexcept
{
    bm.setAgentStats(idx, s);
}

Agent::Conditions CombatEngine::getAgentConditions(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentConditions(idx);
}

void CombatEngine::setAgentConditions(BattleMap& bm, int idx, const Agent::Conditions& c) noexcept
{
    bm.setAgentConditions(idx, c);
}

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

void CombatEngine::applyIncapacitated(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set incapacitated condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.incapacitated = true;
    bm.setAgentConditions(idx, cond);

    // Break concentration if the agent is concentrating
    if (cond.concentrating) {
        cond.concentrating = false;
        cond.concentrating_on = "";
        bm.setAgentConditions(idx, cond);
        log_("Agent incapacitated: concentration broken");

        // Remove all conditions caused by concentration spells cast by this agent
        const auto& spells = bm.getAgentSpells(idx);
        std::vector<int> conds_to_remove;
        for (const auto& active_cond : activeAgentConditions_) {
            if (active_cond.caster_idx == idx &&
                active_cond.spell_idx >= 0 &&
                active_cond.spell_idx < static_cast<int>(spells.size())) {
                if (spells[static_cast<std::size_t>(active_cond.spell_idx)].requires_concentration) {
                    conds_to_remove.push_back(active_cond.condition_id);
                }
            }
        }
        for (int cond_id : conds_to_remove) {
            removeAgentCondition(cond_id);
        }
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

void CombatEngine::standup(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Check if agent is prone
    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.prone) {
        log_("Agent is not prone");
        return;
    }

    // Cost to stand up: half of walk speed
    int walk_speed = agents[idx].stats.speed_walk;
    int standup_cost = walk_speed / 2;

    // Check if agent has enough movement
    auto it = walkRemaining_.find(idx);
    int remaining = (it != walkRemaining_.end()) ? it->second : 0;
    if (remaining < standup_cost) {
        log_("Agent lacks sufficient movement to stand up (needs {}, has {})", standup_cost, remaining);
        return;
    }

    // Deduct cost and remove prone condition
    spendWalk(idx, standup_cost);
    cond.prone = false;
    bm.setAgentConditions(idx, cond);

    log_("Agent stands up, spending {} feet of movement", standup_cost);
}

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
            }
            log_("Applied condition '{}' to agent[{}] for {} turns",
                 cond.condition_name, cond.agent_idx, cond.turns_remaining);
        }
    }

    activeAgentConditions_.push_back(cond);
    return cond.condition_id;
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
                    }
                    bm.setAgentConditions(cond.agent_idx, agent_cond);
                    log_("Condition '{}' expired for agent[{}]",
                         cond.condition_name, cond.agent_idx);
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

void CombatEngine::removeAgentCondition(int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                          [condition_id](const ActiveAgentCondition& c) { return c.condition_id == condition_id; });
    if (it != activeAgentConditions_.end()) {
        activeAgentConditions_.erase(it);
    }
}

std::array<Weapon, 3> CombatEngine::getAgentWeapons(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentWeapons(idx);
}

void CombatEngine::setAgentWeapons(BattleMap& bm, int idx, std::array<Weapon, 3> weapons) noexcept
{
    bm.setAgentWeapons(idx, weapons);
}

std::array<Armor, 6> CombatEngine::getAgentArmor(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentArmor(idx);
}

void CombatEngine::setAgentArmor(BattleMap& bm, int idx, std::array<Armor, 6> armor) noexcept
{
    bm.setAgentArmor(idx, armor);
}

std::vector<Spell> CombatEngine::getAgentSpells(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentSpells(idx);
}

void CombatEngine::setAgentSpells(BattleMap& bm, int idx, std::vector<Spell> spells) noexcept
{
    bm.setAgentSpells(idx, spells);
}

void CombatEngine::addSpellToAgent(BattleMap& bm, int idx, Spell s) noexcept
{
    bm.addSpellToAgent(idx, s);
}

void CombatEngine::removeSpellFromAgent(BattleMap& bm, int idx, int spell_idx) noexcept
{
    bm.removeSpellFromAgent(idx, spell_idx);
}

void CombatEngine::initNpcSpellGroups(BattleMap& bm, int agent_idx,
                                      const std::map<int, std::vector<std::string>>& groups) noexcept
{
    bm.initNpcSpellGroups(agent_idx, groups);
}

void CombatEngine::computeVisibility(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;

    const PlacedAgent& viewer = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& viewer_stats = viewer.stats;

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
                LightLevel obscuration = bm.getObscurationAtCell(target.origin);

                // Check if viewer can see through magical darkness (devil's sight)
                bool can_see_through_darkness = viewer_stats.devilssight_range > (chebyshev_distance * 5);

                if (obscuration == LightLevel::MagicalDarkness && !can_see_through_darkness) {
                    visibility = VisibilityLevel::Blocked;
                } else if (obscuration == LightLevel::PartiallyObscured) {
                    visibility = VisibilityLevel::PartiallyObscured;
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

bool CombatEngine::checkConcentrationOnDamage(BattleMap& bm, int target_idx, int damage) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(target_idx)];
    const Agent::Conditions& cond = pa.agent->getConditions();
    if (!cond.concentrating)
        return false;  // Not concentrating, no save needed

    // DC is 10 or half damage, whichever is higher
    int dc = std::max(10, damage / 2);
    int con_mod = (pa.stats.con - 10) / 2;
    int save_roll = roll(20);
    int save_total = save_roll + con_mod;

    if (save_total >= dc) {
        log_("Concentration save: {} rolled {} + {} = {} vs DC {} — HELD",
             pa.agent->name(), save_roll, con_mod, save_total, dc);
        return false;  // Save succeeded
    }

    log_("Concentration save: {} rolled {} + {} = {} vs DC {} — BROKEN",
         pa.agent->name(), save_roll, con_mod, save_total, dc);

    // Concentration lost - clear it and remove spell effects
    std::string spell_name = cond.concentrating_on;
    Agent::Conditions new_cond = cond;
    new_cond.concentrating = false;
    new_cond.concentrating_on = "";
    bm.setAgentConditions(target_idx, new_cond);

    // Remove spell effects from this agent's concentration spell
    const auto& effects = bm.activeSpellEffects();
    std::vector<int> to_remove;
    for (const auto& effect : effects) {
        if (effect.caster_idx == target_idx && effect.spell.name == spell_name) {
            to_remove.push_back(effect.effect_id);
        }
    }
    for (int effect_id : to_remove) {
        bm.removeSpellEffect(effect_id);
    }

    return true;  // Concentration was lost
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

// ─────────────────────────────────────────────────────────────────────────────
//  getNumTargetsForSpell – calculate target count for Multiple geometry spells
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::getNumTargetsForSpell(const Spell& sp, int slot_level) const noexcept
{
    // For Multiple geometry spells, calculate targets based on upcast level
    if (sp.geometry != Spell::Multiple) {
        return (sp.geometry == Spell::Single) ? 1 : 0;
    }

    // Multiple geometry: num_targets + (slot_level - spell.level) * targets_per_upcast_level
    int num_targets = sp.num_targets;
    if (slot_level > 0 && slot_level > sp.level) {
        num_targets += (slot_level - sp.level) * sp.targets_per_upcast_level;
    }
    return std::max(1, num_targets);  // Always at least 1 target
}

void CombatEngine::applySpellEffect(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return;

    Agent::Stats target_stats = bm.getAgentStats(target_idx);

    // Calculate total damage by rolling all damage types and applying multipliers
    int total_damage = 0;

    // Magic damage
    for (const auto& roll_info : effect.spell.magic_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) {
            type_damage += roll(roll_info.die_size);
        }
        type_damage += roll_info.bonus;
        float multiplier = target_stats.magic_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        total_damage += modified;
    }

    // Physical damage
    for (const auto& roll_info : effect.spell.physical_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) {
            type_damage += roll(roll_info.die_size);
        }
        type_damage += roll_info.bonus;
        float multiplier = target_stats.physical_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        total_damage += modified;
    }

    // Log the effect
    std::string action = (effect.spell.type == Spell::Heal) ? "healed" : "took";
    log_("{} {} {} from {}", agents[static_cast<std::size_t>(target_idx)].agent->name(), action, total_damage, effect.spell.name);

    // Apply damage or healing
    if (effect.spell.type == Spell::Heal) {
        healAgent(bm, target_idx, total_damage);
    } else {
        damageAgent(bm, target_idx, total_damage);
    }
}

void CombatEngine::checkSlippingTerrain(BattleMap& bm, int agent_idx, Cell oldOrigin, Cell newOrigin) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return;

    // Check all terrain effects to see if any are slipping terrain
    for (const auto& terrain : bm.activeTerrainEffects()) {
        if (terrain.difficulty != TerrainDifficulty::Slipping)
            continue;

        // Check if the agent moved into a cell with this slipping terrain
        std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);
        bool on_slipping_terrain = false;
        for (const auto& cell : pathCells) {
            int cell_idx = cell.row * bm.gridCols() + cell.col;
            if (std::find(terrain.cell_indices.begin(), terrain.cell_indices.end(), cell_idx) != terrain.cell_indices.end()) {
                on_slipping_terrain = true;
                break;
            }
        }

        if (!on_slipping_terrain)
            continue;

        // Agent is on slipping terrain; add distance moved to slip counter
        int distance_moved = std::max({
            std::abs(newOrigin.col - oldOrigin.col),
            std::abs(newOrigin.row - oldOrigin.row)
        }) * 5;  // Each cell is 5 feet

        int& slip_counter = slipDistanceMoved_[agent_idx];
        slip_counter += distance_moved;

        // Check if they've moved enough feet to trigger a save
        if (slip_counter >= terrain.slip_distance_feet) {
            // Roll DEX save
            Agent::Stats target_stats = bm.getAgentStats(agent_idx);
            int save_d20 = roll(20);
            int save_mod = (target_stats.dex - 10) / 2;
            int total_save = save_d20 + save_mod;

            log_("{} attempts DEX save ({}) vs DC {} - d20={}, mod={}, total={}",
                 agents[static_cast<std::size_t>(agent_idx)].agent->name(),
                 terrain.name,
                 terrain.slip_save_dc,
                 save_d20, save_mod, total_save);

            if (total_save < terrain.slip_save_dc) {
                // Save failed — apply prone condition and skip turn
                log_("{} slipped on {} and fell prone", agents[static_cast<std::size_t>(agent_idx)].agent->name(), terrain.name);
                applyProne(bm, agent_idx);
                agents[static_cast<std::size_t>(agent_idx)].agent->setSlippedThisTurn(true);
            } else {
                // Save succeeded — stay upright
                log_("{} maintained footing on {}", agents[static_cast<std::size_t>(agent_idx)].agent->name(), terrain.name);
            }

            // Reset slip counter after save check
            slip_counter = 0;
        }
    }
}

} // namespace rpg
