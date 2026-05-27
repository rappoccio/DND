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
    // Portent Dice: if pending, return it instead of rolling (and clear)
    if (pending_portent_die_ >= 0) {
        int result = pending_portent_die_;
        pending_portent_die_ = -1;
        return result;
    }
    return std::uniform_int_distribution<int>{1, sides}(rng_);
}

int CombatEngine::rollAdvantage(int sides)
{
    // Check if portent die is pending (need to apply after advantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }

    int result = std::max(roll(sides), roll(sides));

    // Apply portent die if one was pending (after advantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", result, pending_portent);
        result = pending_portent;
    }

    return result;
}

int CombatEngine::rollDisadvantage(int sides)
{
    // Check if portent die is pending (need to apply after disadvantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }

    int result = std::min(roll(sides), roll(sides));

    // Apply portent die if one was pending (after disadvantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", result, pending_portent);
        result = pending_portent;
    }

    return result;
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

    // Check if any armor is equipped
    bool has_armor = false;
    for (const auto& piece : pa.armor) {
        if (!piece.name.empty()) {
            has_armor = true;
            break;
        }
    }

    // Barbarian Unarmored Defense: AC = 10 + DEX + CON (no armor worn)
    if (pa.agent->getStats().character_class == CharacterClass::Barbarian && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int con_mod = (pa.agent->getStats().con - 10) / 2;
        int ac = 10 + dex_mod + con_mod;

        // Add shield bonus (off-hand weapon with ac_bonus)
        if (!pa.weapons.empty() && pa.weapons.size() > 1) {
            const Weapon& shield = pa.weapons.back();
            if (shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
            }
        }

        // Add temporary modifications
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // Standard AC calculation (non-Barbarian or wearing armor)
    int ac = pa.agent->getStats().base_ac;

    // Calculate DEX modifier and determine cap from equipped armor
    int dex_mod = (pa.agent->getStats().dex - 10) / 2;
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
    ac += pa.agent->getStats().ac_temporary_modifications;

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

    // War Domain — Avatar of Battle (L17+): Resistance to Bludgeoning/Piercing/Slashing.
    if (s.character_class == CharacterClass::Cleric && s.cleric_subclass == WarDomain && s.char_level >= 17) {
        for (auto t : {PhysicalDamage_t::Bludgeoning, PhysicalDamage_t::Piercing, PhysicalDamage_t::Slashing}) {
            float& cur = s.physical_damage_multipliers[static_cast<std::size_t>(t)];
            if (cur > 0.5f && cur != 2.0f) cur = 0.5f;  // resist, but don't override vuln/immunity
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
    return pa.agent->getStats().str >= armor.str_requirement;
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

    // New turn: advance the counter used for persistent-zone "once per turn" dedup.
    ++turnCounter_;

    auto agent_name = agentName(bm, agent_idx);
    // Reset slip distance counter and slipped flag for the new turn
    slipDistanceMoved_[agent_idx] = 0;
    agents[static_cast<std::size_t>(agent_idx)].agent->setSlippedThisTurn(false);

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    auto stats = agent.agent->getStats();

    // Death from Exhaustion: agent dies at exhaustion level 6
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);

    // Reset per-turn Barbarian flags at start of each turn
    cond.reckless_attack = false;

    if (cond.exhaustion_level >= 6 && stats.hp_cur > 0) {
        stats.hp_cur = 0;
        cond.dead = true;
        cond.unconscious = true;
        bm.setAgentStats(agent_idx, stats);
        bm.setAgentConditions(agent_idx, cond);
        log_("{} dies from Exhaustion Level 6", agent_name);
        result.save_roll_message = "DEATH: Exhaustion Level 6";
        return result;
    }

    // Death saves: roll CON save DC 10 if unconscious at 0 HP
    if (cond.unconscious && stats.hp_cur <= 0 && !cond.stabilized && !cond.dead) {
        int con_mod = (stats.con - 10) / 2;
        if (stats.con < 10 && (stats.con - 10) % 2 != 0) --con_mod;
        int death_d20 = roll(20);
        int death_total = death_d20 + con_mod;

        if (death_d20 == 20) {
            // Natural 20: auto-stabilize
            cond.stabilized = true;
            cond.death_save_successes = 3;  // Mark as stabilized
            bm.setAgentConditions(agent_idx, cond);
            log_("Death save: NATURAL 20! Character automatically stabilizes");
            result.save_roll_message = "Death Save: Natural 20! Automatically stabilized!";
        } else if (death_d20 == 1) {
            // Natural 1: 2 failures
            cond.death_save_failures += 2;
            if (cond.death_save_failures >= 3) {
                cond.dead = true;
                log_("Death save: NATURAL 1! Character dies");
                result.save_roll_message = "Death Save: Natural 1! Character dies!";
            } else {
                log_("Death save: Natural 1 (2 failures) — {} failures total", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Natural 1 (2 failures) — {}/3 failures", cond.death_save_failures);
            }
            bm.setAgentConditions(agent_idx, cond);
        } else if (death_total >= 10) {
            // Success
            cond.death_save_successes++;
            if (cond.death_save_successes >= 3) {
                cond.stabilized = true;
                log_("Death save: SUCCESS (stabilized) — {}/3 successes", cond.death_save_successes);
                result.save_roll_message = std::format("Death Save: Success! Stabilized ({}/3 successes)", cond.death_save_successes);
            } else {
                log_("Death save: SUCCESS — {}/3 successes", cond.death_save_successes);
                result.save_roll_message = std::format("Death Save: Success ({}/3 successes)", cond.death_save_successes);
            }
            bm.setAgentConditions(agent_idx, cond);
        } else {
            // Failure
            cond.death_save_failures++;
            if (cond.death_save_failures >= 3) {
                cond.dead = true;
                log_("Death save: FAILED — Character dies ({}/3 failures)", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Failed! Character dies ({}/3 failures)", cond.death_save_failures);
            } else {
                log_("Death save: FAILED — {}/3 failures", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Failed ({}/3 failures)", cond.death_save_failures);
            }
            bm.setAgentConditions(agent_idx, cond);
        }
    }

    // If unconscious but not stabilized/dead, skip turn (death save was rolled above)
    if (cond.unconscious && !cond.stabilized && !cond.dead) {
        result.turn_skipped = true;
        result.skip_reason = "Unconscious";
        log_("{} cannot act, skipping turn", agent_name);
        return result;
    }

    // Check if concentration spell has any living targets left
    if (cond.concentrating && !cond.concentrating_on.empty()) {
        bool has_living_targets = false;
        for (const auto& active_cond : activeAgentConditions_) {
            // Check if any agents have conditions applied by this caster's spells
            if (active_cond.caster_idx == agent_idx &&
                active_cond.agent_idx >= 0 &&
                active_cond.agent_idx < static_cast<int>(agents.size())) {
                const auto& target_stats = agents[static_cast<std::size_t>(active_cond.agent_idx)].agent->getStats();
                const auto& target_cond = agents[static_cast<std::size_t>(active_cond.agent_idx)].agent->getConditions();
                // Target is alive if not dead and not unconscious (unconscious targets can't be affected by control spells)
                if (target_stats.hp_cur > 0 && !target_cond.dead && !target_cond.unconscious) {
                    has_living_targets = true;
                    break;
                }
            }
        }
        // A persistent zone (Spirit Guardians, Cloudkill, etc.) keeps concentration alive
        // on its own — the area is the ongoing effect even with no condition-targets.
        if (!has_living_targets) {
            for (const auto& fx : bm.activeSpellEffects())
                if (fx.caster_idx == agent_idx) { has_living_targets = true; break; }
        }
        if (!has_living_targets) {
            cond.concentrating = false;
            cond.concentrating_on = "";
            bm.setAgentConditions(agent_idx, cond);
            log_("Concentration on {} dropped: no living targets remaining", cond.concentrating_on);
        }
    }

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
            log_("{} cannot act, skipping turn", agent_name);
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
                cond = bm.getAgentConditions(agent_idx);
                cond.paralyzed = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Incapacitated") {
                cond = bm.getAgentConditions(agent_idx);
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Stunned") {
                cond = bm.getAgentConditions(agent_idx);
                cond.stunned = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            }

            // Drop the caster's concentration ONLY if this was the last affected target from that spell
            if (active_cond.caster_idx >= 0 && active_cond.caster_idx < static_cast<int>(agents.size())) {
                Agent::Conditions caster_cond = bm.getAgentConditions(active_cond.caster_idx);
                if (caster_cond.concentrating) {
                    // Check if there are any remaining conditions from this spell
                    bool spell_still_affects_targets = false;
                    for (const auto& other_cond : activeAgentConditions_) {
                        if (other_cond.caster_idx == active_cond.caster_idx &&
                            other_cond.spell_idx == active_cond.spell_idx &&
                            other_cond.condition_id != active_cond.condition_id) {
                            spell_still_affects_targets = true;
                            break;
                        }
                    }

                    // Only drop concentration if this was the last affected target
                    if (!spell_still_affects_targets) {
                        caster_cond.concentrating = false;
                        caster_cond.concentrating_on = "";
                        bm.setAgentConditions(active_cond.caster_idx, caster_cond);
                        log_("{} drops concentration on spell (no more affected targets)", agentName(bm, active_cond.caster_idx));
                    } else {
                        log_("{} maintains concentration on spell (still {} other affected targets)", agentName(bm, active_cond.caster_idx), spell_still_affects_targets ? "has" : "no");
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
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED", ability_name(active_cond.save_ability), active_cond.condition_name, save_d20, save_mod, save_total, save_dc);
                log_("{} cannot act, skipping turn", agent_name);
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

        // Frightened: save only if no LOS to fear source
        if (active_cond.condition_name == "Frightened" && active_cond.caster_idx >= 0) {
            Cell src = bm.placedAgents()[active_cond.caster_idx].origin;
            Cell vic = bm.placedAgents()[active_cond.agent_idx].origin;
            if (bm.hasLineOfSight(vic, 1, src, 1)) continue;  // still sees source, no save
        }

        // Unconscious: auto-fail STR/DEX saves
        Agent::Conditions agent_cond = bm.getAgentConditions(active_cond.agent_idx);
        if (agent_cond.unconscious && (active_cond.save_ability == SaveStr || active_cond.save_ability == SaveDex)) {
            auto ability_name = [](SaveAbility_t ab) -> std::string {
                return (ab == SaveStr) ? "STR" : "DEX";
            };
            log_("{} save vs {} — AUTOMATICALLY FAILED (Unconscious auto-fails STR/DEX saves)",
                 ability_name(active_cond.save_ability), active_cond.condition_name);
            active_cond.next_save_turn = active_cond.save_repeat_turns;
            continue;
        }

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
        int save_total = save_d20 + save_mod - (2 * agent_cond.exhaustion_level);
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

    // Seed movement budgets from current stats, applying exhaustion penalty (5 ft per level)
    cond = bm.getAgentConditions(agent_idx);
    int exhaustion_penalty = 5 * cond.exhaustion_level;
    // Movement debuffs: Brutal Strike's Hamstring Blow (-15) and the Slow weapon
    // mastery (-10). These are consumed (cleared) in Agent::turn(), which runs
    // just after this seeding — so they reduce Speed for exactly this one turn.
    int move_penalty = exhaustion_penalty
                     + (cond.hamstrung ? 15 : 0)
                     + (cond.slowed    ? 10 : 0);
    walkRemaining_[agent_idx] = std::max(0, stats.speed_walk - move_penalty);
    flyRemaining_ [agent_idx] = std::max(0, stats.speed_fly - move_penalty);
    swimRemaining_[agent_idx] = std::max(0, stats.speed_swim - move_penalty);
    burrowRemaining_[agent_idx] = std::max(0, stats.speed_burrow - move_penalty);

    // Reset per-turn conditions
    agent.agent->turn();

    // Reset leveled spell cast flag
    auto new_stats = stats;
    new_stats.resetLeveledSpellCastFlag();
    bm.setAgentStats(agent_idx, new_stats);

    // Keep any Emanation anchored to this agent centered on them (e.g. after a forced move).
    recomputeAnchoredEffects(bm, agent_idx);

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
                    applyZoneIfNewThisTurn(bm, effect, agent_idx);
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

bool CombatEngine::canAgentMove(const BattleMap& bm, int idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    // Check for any condition that reduces speed to 0
    if (cond.incapacitated || cond.unconscious || cond.grappled || cond.paralyzed) {
        return false;
    }
    return true;
}

// True if any cell of the agent's NxN footprint lies within the given cell set.
static bool footprintOverlapsCells(const PlacedAgent& pa, const std::vector<Cell>& cells)
{
    const int size = pa.agent->getSize();
    for (int c = pa.origin.col; c < pa.origin.col + size; ++c)
        for (int r = pa.origin.row; r < pa.origin.row + size; ++r)
            if (std::find(cells.begin(), cells.end(), Cell{c, r}) != cells.end())
                return true;
    return false;
}

bool CombatEngine::moveAgent(BattleMap& bm, int idx, Cell newOrigin, MovementType type) noexcept
{
    // Get old position before moving
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;

    // Check if agent is incapacitated or unconscious - cannot move
    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.incapacitated || cond.unconscious) {
        log_("Movement blocked: agent is incapacitated or unconscious");
        return false;
    }

    // Check if agent is grappled - cannot move (Speed = 0)
    if (cond.grappled) {
        log_("Movement blocked: grappled creature cannot move (Speed = 0)");
        return false;
    }

    // Check if grapple should auto-end (grappler incapacitated or out of range)
    if (cond.grappler_idx >= 0 && cond.grappler_idx < static_cast<int>(agents.size())) {
        Agent::Conditions grappler_cond = bm.getAgentConditions(cond.grappler_idx);
        if (grappler_cond.incapacitated) {
            cond.grappled = false;
            cond.grappler_idx = -1;
            bm.setAgentConditions(idx, cond);
            log_("Grapple ended: grappler is incapacitated");
            // Continue with movement now that grapple is broken
        } else {
            // Check distance
            Cell grappler_pos = agents[cond.grappler_idx].origin;
            Cell my_pos = agents[idx].origin;
            int dist_cells = std::max(std::abs(my_pos.col - grappler_pos.col),
                                     std::abs(my_pos.row - grappler_pos.row));
            if (dist_cells * 5 > cond.grapple_range_ft) {
                cond.grappled = false;
                cond.grappler_idx = -1;
                bm.setAgentConditions(idx, cond);
                log_("Grapple ended: distance exceeds grapple range");
                // Continue with movement now that grapple is broken
            }
        }
    }

    Cell oldOrigin = agents[static_cast<std::size_t>(idx)].origin;

    // Check if agent is grappling someone - double movement cost
    int move_dist_ft = std::max(std::abs(newOrigin.col - oldOrigin.col),
                                std::abs(newOrigin.row - oldOrigin.row)) * 5;
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == idx) continue;
        Agent::Conditions target_cond = bm.getAgentConditions(i);
        if (target_cond.grappled && target_cond.grappler_idx == idx) {
            // Grappler paying extra movement cost to drag (same as movement type being used)
            int extra_cost = move_dist_ft;
            int remaining = 0;

            if (type == MovementType::Walk) {
                remaining = getWalkRemaining(idx);
                if (remaining < extra_cost) {
                    log_("Not enough movement to drag grappled creature");
                    return false;
                }
                spendWalk(idx, extra_cost);
            } else if (type == MovementType::Fly) {
                remaining = getFlyRemaining(idx);
                if (remaining < extra_cost) {
                    log_("Not enough movement to drag grappled creature");
                    return false;
                }
                spendFly(idx, extra_cost);
            } else if (type == MovementType::Swim) {
                remaining = getSwimRemaining(idx);
                if (remaining < extra_cost) {
                    log_("Not enough movement to drag grappled creature");
                    return false;
                }
                spendSwim(idx, extra_cost);
            } else if (type == MovementType::Burrow) {
                remaining = getBurrowRemaining(idx);
                if (remaining < extra_cost) {
                    log_("Not enough movement to drag grappled creature");
                    return false;
                }
                spendBurrow(idx, extra_cost);
            }
            break;
        }
    }

    // Check if agent is Frightened and would move toward fear source
    for (const auto& ac : activeAgentConditions_) {
        if (ac.agent_idx == idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
            Cell src  = bm.placedAgents()[ac.caster_idx].origin;
            int cur_d = std::max(std::abs(oldOrigin.col - src.col), std::abs(oldOrigin.row - src.row));
            int new_d = std::max(std::abs(newOrigin.col - src.col), std::abs(newOrigin.row - src.row));
            if (new_d < cur_d) {
                log_("Movement blocked: Frightened cannot move closer to fear source");
                return false;
            }
            break;
        }
    }

    // Delegate to BattleMap for pathfinding and movement budget logic
    if (!bm.moveAgent(idx, newOrigin, type))
        return false;

    // Check for spell effects along the path from old to new position. A creature that
    // enters a zone is affected at most once per turn (see applyZoneIfNewThisTurn).
    std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);
    for (const auto& pathCell : pathCells) {
        for (const auto& effect : bm.activeSpellEffects()) {
            if (effect.caster_idx == idx) continue;  // don't damage self
            if (std::find(effect.cells.begin(), effect.cells.end(), pathCell) != effect.cells.end())
                applyZoneIfNewThisTurn(bm, effect, idx);
        }
    }

    // A moving Sphere (Emanation) anchored to this agent follows them as they move.
    // Snapshot each anchored zone's footprint, re-center it, then affect creatures the
    // zone newly swept onto — "whenever the Emanation enters a creature's space" (once/turn).
    std::vector<std::pair<int, std::vector<Cell>>> oldAnchoredCells;  // (effect_id, cells before move)
    for (const auto& effect : bm.activeSpellEffects())
        if (effect.anchor_agent_idx == idx)
            oldAnchoredCells.emplace_back(effect.effect_id, effect.cells);

    recomputeAnchoredEffects(bm, idx);

    for (const auto& [eff_id, oldCells] : oldAnchoredCells) {
        const ActiveSpellEffect* eff = nullptr;
        for (const auto& e : bm.activeSpellEffects())
            if (e.effect_id == eff_id) { eff = &e; break; }
        if (!eff) continue;
        for (int j = 0; j < static_cast<int>(agents.size()); ++j) {
            if (j == idx) continue;  // the anchor is never affected by its own Emanation
            const PlacedAgent& other = agents[static_cast<std::size_t>(j)];
            if (footprintOverlapsCells(other, eff->cells) && !footprintOverlapsCells(other, oldCells))
                applyZoneIfNewThisTurn(bm, *eff, j);
        }
    }

    // Check for slipping terrain (ice/grease) along the path
    checkSlippingTerrain(bm, idx, oldOrigin, newOrigin);

    // Update darkness-based blinding after movement
    updateDarknessBlinding(bm, idx);

    // If grappling someone, drag them along maintaining relative position
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == idx) continue;
        Agent::Conditions grappled_cond = bm.getAgentConditions(i);
        if (grappled_cond.grappled && grappled_cond.grappler_idx == idx) {
            // Calculate relative offset of grappled creature from grappler
            int offset_col = agents[i].origin.col - oldOrigin.col;
            int offset_row = agents[i].origin.row - oldOrigin.row;

            // Try to maintain the same relative position
            Cell preferred = Cell(newOrigin.col + offset_col, newOrigin.row + offset_row);
            Cell drag_dest = preferred;

            // Check if preferred position is valid
            bool position_valid = bm.setAgentPosition(i, preferred);

            // If preferred position blocked, find adjacent unoccupied cell
            if (!position_valid) {
                bool found = false;
                // Try all 8 adjacent cells
                const int deltas[][2] = {{0,1}, {0,-1}, {1,0}, {-1,0}, {1,1}, {-1,-1}, {1,-1}, {-1,1}};
                for (const auto& delta : deltas) {
                    Cell candidate = Cell(newOrigin.col + delta[0], newOrigin.row + delta[1]);
                    if (bm.setAgentPosition(i, candidate)) {
                        drag_dest = candidate;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    // No valid position found, leave creature at current position
                    continue;
                }
            } else {
                drag_dest = preferred;
            }

            log_("Grappled creature dragged");
        }
    }

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

    // Update darkness-based blinding after jump
    updateDarknessBlinding(bm, idx);

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

    // Reset per-turn flags at the start of the round
    for (int i = 0; i < n; ++i) {
        bm.placedAgents()[static_cast<std::size_t>(i)].agent->setReactionUsed(false);

        // Reset per-round Barbarian flags (per-turn flags reset in beginTurn)
        Agent::Conditions cond = bm.getAgentConditions(i);
        cond.berserker_frenzy_used = false;
        cond.zealot_divine_fury_used = false;
        cond.brutal_strike_available = false;
        cond.brutal_strike_used_this_turn = false;
        cond.hamstrung = false;
        cond.sundering_target_idx = -1;
        cond.staggered_next_save = false;
        // Weapon Mastery fallback resets (also consumed on-use / in Agent::turn()).
        cond.sapped = false;
        cond.slowed = false;
        cond.vex_target_idx = -1;
        cond.push_available = false;
        cond.topple_available = false;
        cond.cleave_available = false;
        cond.cleave_used_this_turn = false;
        bm.setAgentConditions(i, cond);
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
        if (other.agent->getStats().hp_cur <= 0) continue;

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
                                      bool disadvantage,
                                      int exhaustion_level)
{
    AttackResult r;
    r.disadvantage = disadvantage;
    r.attack_mod   = attackModifier(w, attacker) + w.bonus_hit;
    r.target_ac    = target_ac;

    // Check if portent die is pending (need to apply after advantage/disadvantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }

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

    // Apply portent die if one was pending (after advantage/disadvantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", r.d20, pending_portent);
        r.d20 = pending_portent;
    }

    r.critical   = (r.d20 >= attacker.crit_threshold);
    r.fumble     = (r.d20 == 1);
    r.total_roll = r.d20 + r.attack_mod - (2 * exhaustion_level);
    r.hit        = r.critical || (!r.fumble && r.total_roll >= target_ac);

    return r;
}

void CombatEngine::rollDamage(const Weapon& w,
                               const Agent::Stats& attacker,
                               const Agent::Stats& target,
                               AttackResult& result,
                               bool suppress_positive_mod)
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

    int ability_mod = damageAbilityMod(w, attacker);
    if (suppress_positive_mod && ability_mod > 0) ability_mod = 0;  // Cleave: keep only a negative mod
    result.damage_mod   = ability_mod + w.bonus_damage;
    result.total_damage = std::max(0, raw + result.damage_mod);
    result.damage_breakdown.clear();
    result.damage_breakdown.push_back({"weapon", result.total_damage});
}

AttackResult CombatEngine::resolveAttack(const Weapon& w,
                                          const Agent& attacker,
                                          const Agent& target,
                                          bool advantage,
                                          bool disadvantage,
                                          bool suppress_positive_mod)
{
    int target_ac = target.getStats().base_ac;
    AttackResult r = rollToHit(w, attacker.getStats(), target_ac, advantage, disadvantage, attacker.getConditions().exhaustion_level);
    r.hp_before = target.getStats().hp_cur;

    if (r.hit) {
        rollDamage(w, attacker.getStats(), target.getStats(), r, suppress_positive_mod);

        // Barbarian Rage damage bonus (STR-based attacks only)
        // Applies to melee and thrown weapons (where STR is the primary damage ability)
        if (attacker.getConditions().raging &&
            attacker.getStats().character_class == CharacterClass::Barbarian &&
            (w.type == WeaponType::Melee || w.thrown)) {
            int rage_bonus = getRageDamageBonus(attacker.getStats().char_level);
            r.total_damage += rage_bonus;
            r.damage_breakdown.push_back({"rage", rage_bonus});
        }

        // Compute resulting HP without mutating the target — the caller applies
        // the damage to its working stats copy and persists it once. (Temp HP
        // absorbs first, then overflow reduces hp_cur.)
        int overflow = std::max(0, r.total_damage - target.getStats().temp_hp);
        r.hp_after = std::clamp(target.getStats().hp_cur - overflow, 0, target.getStats().hp_max);
    } else {
        r.hp_after = target.getStats().hp_cur;
    }

    r.target_down = (r.hp_after <= 0);
    r.valid       = true;
    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Rogue Cunning Strike helpers
// ─────────────────────────────────────────────────────────────────────────────

// Rogue Cunning Strike: Sneak Attack dice cost per effect (0 = unknown/deferred → invalid).
static int cunningStrikeCost(int effect) noexcept {
    switch (effect) {
        case 0: return 1;  // Poison
        case 1: return 1;  // Trip
        case 2: return 1;  // Withdraw
        case 4: return 6;  // Knock Out
        case 5: return 3;  // Obscure
        default: return 0; // 3=Daze deferred, anything else invalid
    }
}

static int cunningStrikeMinLevel(int effect) noexcept {
    switch (effect) {
        case 0: case 1: case 2: return 5;   // Cunning Strike
        case 4: case 5:         return 14;  // Devious Strikes
        default:                return 99;  // invalid
    }
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

    // Attacker conditions
    const Agent::Conditions& atk_cond = atk_pt.agent->getConditions();

    // Barbarian Reckless Attack: give attacker advantage on STR-based melee attacks
    if (atk_cond.reckless_attack && w.type != WeaponType::Ranged &&
        (w.type == WeaponType::Melee || w.thrown)) {
        adv = true;
    }

    // Attacker blinded: attacks have disadvantage
    if (atk_cond.blinded) {
        dis = true;
        log_("Disadvantage: attacker is blinded");
    }

    // Attacker poisoned: attacks have disadvantage
    if (atk_cond.poisoned) {
        dis = true;
        log_("Disadvantage: attacker is poisoned");
    }

    // Attacker frightened: disadvantage on attacks when fear source is in LOS
    if (atk_cond.frightened) {
        for (const auto& ac : activeAgentConditions_) {
            if (ac.agent_idx == action.attacker_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
                if (bm.hasLineOfSight(atk_pt.origin, atk_sz, bm.placedAgents()[ac.caster_idx].origin, 1)) {
                    dis = true;
                    log_("Disadvantage: attacker is frightened and fear source is in LOS");
                }
                break;
            }
        }
    }

    // Attacker grappled: disadvantage on attacks except against the grappler
    if (atk_cond.grappled) {
        if (action.target_idx != atk_cond.grappler_idx) {
            dis = true;
            log_("Disadvantage: attacker is grappled");
        }
    }

    // Attacker is hidden: attacks have advantage (will be revealed after attack)
    bool attacker_was_hidden = atk_cond.hidden;
    if (attacker_was_hidden) {
        adv = true;
        log_("Advantage: attacker is hidden");
    }

    // Rogue Steady Aim: the bonus action grants advantage on this attack (consumed below).
    if (atk_cond.steady_aim) {
        adv = true;
        log_("Advantage: Steady Aim");
    }

    // Wild Heart Wolf Form: allies within 5ft of the Barbarian get advantage on attacks
    // Check if there's a Wolf-form Wild Heart Barbarian within 5ft of the attacker
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == action.attacker_idx) continue;  // Skip self
        const PlacedAgent& ally_pa = agents[static_cast<std::size_t>(i)];
        const Agent::Stats& ally_stats = ally_pa.agent->getStats();
        const Agent::Conditions& ally_cond = ally_pa.agent->getConditions();

        // Check if ally is a Wolf-form Wild Heart Barbarian in Rage
        if (ally_stats.barbarian_subclass == WildHeartPath &&
            ally_stats.wild_heart_rage_choice == WolfForm &&
            ally_cond.raging) {
            // Check distance: within 5ft (1 cell on 5ft/cell grid = Chebyshev distance <= 1)
            int dc = std::max({atk_pt.origin.col - ally_pa.origin.col,
                               ally_pa.origin.col - (atk_pt.origin.col + atk_sz - 1),
                               0});
            int dr = std::max({atk_pt.origin.row - ally_pa.origin.row,
                               ally_pa.origin.row - (atk_pt.origin.row + atk_sz - 1),
                               0});
            int dist = std::max(dc, dr);

            if (dist <= 1) {
                adv = true;
                log_("Advantage: Wild Heart Wolf Form ally within 5 feet");
                break;
            }
        }
    }

    // Target is paralyzed: attacker gets advantage
    const Agent::Conditions& tgt_cond = tgt_pt.agent->getConditions();
    // Snapshot incapacitation BEFORE this attack's own effects can change it. tgt_cond is a
    // live reference, so a rider applied mid-resolution (e.g. Cunning Strike Knock Out) would
    // otherwise leak into the post-resolution blocks below (auto-crit-on-unconscious and
    // auto-wake) and act on the very hit that caused the condition.
    const bool tgt_unconscious_at_attack   = tgt_cond.unconscious;
    const bool tgt_incapacitated_at_attack = tgt_cond.paralyzed || tgt_unconscious_at_attack;
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

    // Target is unconscious: attacker gets advantage
    if (tgt_cond.unconscious) {
        adv = true;
        log_("Advantage: target is unconscious");
    }

    // Target has Reckless Attack active (Barbarian): attacker gets advantage
    if (tgt_cond.reckless_attack) {
        adv = true;
        log_("Advantage: target has Reckless Attack active");
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

    // ── Weapon Mastery: Vex (advantage) / Sap (disadvantage) carried from a prior hit ──
    // These were set on a previous attack and are consumed here (cleared after the roll
    // via updated_atk_cond), independent of the weapon used for this attack.
    bool consume_vex = false, consume_sap = false;
    if (atk_cond.vex_target_idx == action.target_idx) {
        adv = true; consume_vex = true;
        log_("Advantage: Vex (your last hit on this target)");
    }
    if (atk_cond.sapped) {
        dis = true; consume_sap = true;
        log_("Disadvantage: attacker was Sapped");
    }

    Agent::Stats atk_stats = bm.getAgentStats(action.attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(action.target_idx);
    log_("[ATTACK START] {} - unconscious={}, hp={}", agentName(bm, action.target_idx), tgt_cond.unconscious, tgt_stats.hp_cur);

    // Check Brutal Strike eligibility (L9+: Reckless Attack + melee weapon, once per turn)
    bool can_use_brutal_strike = false;
    if (atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.char_level >= 9 &&
        atk_cond.reckless_attack &&
        !atk_cond.brutal_strike_used_this_turn &&
        (w.type == WeaponType::Melee || w.thrown)) {
        can_use_brutal_strike = true;
        log_("Brutal Strike eligible: L9+ Barbarian with Reckless Attack + melee weapon");
    }

    // Rogue Elusive (L18+): no attack roll can have advantage against you unless Incapacitated.
    if (adv && tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 18 &&
        !tgt_cond.incapacitated) {
        adv = false;
        log_("Elusive: target is a L18+ Rogue — advantage negated");
    }

    AttackResult r = resolveAttack(w, *atk_pt.agent, *tgt_pt.agent, adv, dis, action.no_ability_damage);

    // Set Brutal Strike flag if eligible and attack hits
    Agent::Conditions updated_atk_cond = atk_cond;
    if (r.hit && can_use_brutal_strike) {
        updated_atk_cond.brutal_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }
    // Reckless Attack: auto-reroll on miss for Barbarians
    else if (!r.hit &&
             atk_stats.character_class == CharacterClass::Barbarian &&
             !atk_cond.reckless_attack &&
             (w.type == WeaponType::Melee || w.thrown)) {
        updated_atk_cond.reckless_attack = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        adv = true;
        r = resolveAttack(w, *atk_pt.agent, *tgt_pt.agent, adv, dis, action.no_ability_damage);
        log_("{} uses Reckless Attack (auto-reroll on miss)", agentName(bm, action.attacker_idx));
    }

    // Consume Rogue Steady Aim: it grants advantage on a single attack this turn.
    if (atk_cond.steady_aim) {
        updated_atk_cond.steady_aim = false;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Rogue Sneak Attack / Cunning Strike eligibility ───────────────────
    // Once per turn, a hit with a Finesse or Ranged weapon while having advantage qualifies for
    // Sneak Attack. Like Brutal Strike, the dice and any Cunning Strike rider are applied out of
    // band via applyCunningStrikeEffect() AFTER this attack fully resolves — so a rider that sets a
    // condition (e.g. Knock Out) can never leak into this attack's own post-resolution logic. Here
    // we only flag availability. (The "ally within 5 ft" trigger is deferred — needs a faction system.)
    if (r.hit && atk_stats.character_class == CharacterClass::Rogue &&
        (w.finesse || w.type == WeaponType::Ranged) &&
        adv && !dis && !atk_cond.sneak_attack_used) {
        updated_atk_cond.cunning_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Cleric Blessed Strikes — Divine Strike eligibility ────────────────
    // L7+ Clerics who chose Divine Strike can, once per turn, add Necrotic/Radiant to a weapon
    // hit. Like Brutal/Cunning Strike, the extra die is applied out of band (applyDivineStrikeEffect).
    if (r.hit && atk_stats.character_class == CharacterClass::Cleric &&
        atk_stats.char_level >= 7 &&
        atk_stats.blessed_strike == BlessedStrikeDivineStrike &&
        !atk_cond.divine_strike_used) {
        updated_atk_cond.divine_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── War Domain — Guided Strike eligibility (on a miss) ────────────────
    // A missed attack (not a natural 1) can be nudged to a hit by a War Cleric L3+ spending Channel
    // Divinity — the attacker themselves, or an ally within 30 ft (who pays a Reaction). Flag it; the
    // GUI offers the choice and calls applyGuidedStrike.
    if (!r.hit && !r.fumble) {
        bool eligible = false;
        for (int c = 0; c < static_cast<int>(agents.size()) && !eligible; ++c) {
            Agent::Stats cs = bm.getAgentStats(c);
            if (cs.character_class != CharacterClass::Cleric ||
                cs.cleric_subclass != WarDomain || cs.char_level < 3) continue;
            const Resource* cd = cs.getResource("Channel Divinity");
            if (!cd || cd->current <= 0) continue;
            if (c == action.attacker_idx) { eligible = true; break; }
            if (bm.getAgentConditions(c).reaction_used) continue;
            const Cell co = agents[static_cast<std::size_t>(c)].origin;
            const Cell ao = agents[static_cast<std::size_t>(action.attacker_idx)].origin;
            const double dx = co.col - ao.col, dy = co.row - ao.row;
            if (std::sqrt(dx * dx + dy * dy) * 5.0 <= 30.0) eligible = true;
        }
        if (eligible) {
            updated_atk_cond.guided_strike_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Rogue Uncanny Dodge (L5+) ─────────────────────────────────────────
    // Reaction: halve the attack's damage (round down). Consumes the target's reaction.
    if (r.hit && r.total_damage > 0 &&
        tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 5 &&
        !tgt_cond.reaction_used && !tgt_cond.incapacitated) {
        int before = r.total_damage;
        r.total_damage = before / 2;
        Agent::Conditions tdef = bm.getAgentConditions(action.target_idx);
        tdef.reaction_used = true;
        bm.setAgentConditions(action.target_idx, tdef);
        r.damage_breakdown.push_back({"uncanny dodge", r.total_damage - before});  // negative: reduction
        log_("Uncanny Dodge: {} halves the attack ({} -> {})",
             agentName(bm, action.target_idx), before, r.total_damage);
    }

    // Apply base attack damage to the target's working stats. resolveAttack now
    // computes damage but does not mutate HP, so the single source of truth is
    // applied here (and persisted once via setAgentStats below). Subsequent
    // class effects (Divine Fury) and the auto-crit path adjust tgt_stats further.
    const int temp_hp_before = tgt_stats.temp_hp;  // for auto-crit revert
    if (r.hit) {
        int overflow = std::max(0, r.total_damage - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - r.total_damage);
        tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after    = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);
    }

    // Zealot Divine Fury: add extra 1d6 + floor(level/2) Necrotic damage on first hit when Raging
    if (r.hit && atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.barbarian_subclass == ZealotPath &&
        atk_cond.raging &&
        !atk_cond.zealot_divine_fury_used &&
        (w.type == WeaponType::Melee || w.thrown)) {

        // Roll 1d6 + floor(level/2)
        int divine_fury_bonus = roll(6) + (atk_stats.char_level / 2);

        r.total_damage += divine_fury_bonus;
        r.damage_breakdown.push_back({"divine fury", divine_fury_bonus});
        // Update target HP with the additional damage
        int overflow = std::max(0, divine_fury_bonus - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - divine_fury_bonus);
        tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);

        // Mark Divine Fury as used this turn
        updated_atk_cond.zealot_divine_fury_used = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);

        //log_("Zealot Divine Fury: added 1d6 + {} = {} damage", atk_stats.char_level / 2, divine_fury_bonus);
    }
    
    // Berserker Frenzy bonus: add extra Nd6, where N is the rage damage bonus
    if (r.hit && atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.barbarian_subclass == BerserkerPath &&
        atk_cond.raging &&
        !atk_cond.berserker_frenzy_used &&
        (w.type == WeaponType::Melee || w.thrown)) {

        // Roll 1d6 + floor(level/2)
        int berserker_frenzy_bonus = 0;

	for ( int irage_bonus = 0; irage_bonus < getRageDamageBonus(atk_stats.char_level); ++irage_bonus ){
	  berserker_frenzy_bonus += roll(6); 
	}

        r.total_damage += berserker_frenzy_bonus;
        r.damage_breakdown.push_back({"frenzy", berserker_frenzy_bonus});
        // Update target HP with the additional damage
        int overflow = std::max(0, berserker_frenzy_bonus - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - berserker_frenzy_bonus);
        tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);

        // Mark Divine Fury as used this turn
        updated_atk_cond.berserker_frenzy_used = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // Automatic critical hit for melee attacks (within 5 ft) against paralyzed or unconscious targets.
    // Uses the pre-attack snapshot so a rider this attack applied (Cunning Strike Knock Out) does not
    // retroactively crit the triggering hit.
    if (tgt_incapacitated_at_attack && r.hit) {
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
            std::string reason = tgt_cond.paralyzed ? "paralyzed" : "unconscious";
            log_("Automatic critical hit: target is {} and within 5 feet", reason);

            // If unconscious, auto-fail 2 death saves
            if (tgt_cond.unconscious) {
                Agent::Conditions updated_cond = bm.getAgentConditions(action.target_idx);
                updated_cond.death_save_failures += 2;
                if (updated_cond.death_save_failures >= 3) {
                    updated_cond.dead = true;
                    log_("Melee hit on unconscious: 2 death save failures — character dies");
                } else {
                    log_("Melee hit on unconscious: 2 death save failures ({}/3)", updated_cond.death_save_failures);
                }
                bm.setAgentConditions(action.target_idx, updated_cond);
            }

            // Re-roll damage with crit flag set (revert HP and temp HP to pre-attack)
            tgt_stats.hp_cur  = r.hp_before;
            tgt_stats.temp_hp = temp_hp_before;
            rollDamage(w, atk_stats, tgt_stats, r, action.no_ability_damage);
            int overflow = std::max(0, r.total_damage - tgt_stats.temp_hp);
            tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - r.total_damage);
            tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow,
                                            0, tgt_stats.hp_max);
            r.hp_after = tgt_stats.hp_cur;
            r.target_down = (r.hp_after <= 0);
        }
    }

    // ════ Weapon Mastery ════════════════════════════════════════════════════
    // Consume any Vex/Sap this attack used (set adv/dis above), then apply the
    // wielded weapon's mastery if the attacker has the Weapon Mastery feature.
    // Auto: Sap/Slow/Vex (on hit), Graze (on miss). Prompted (flag only — the GUI
    // offers the choice and calls the resolver): Push/Topple/Cleave.
    int graze_damage = 0;
    {
        bool dirty_atk = false;
        if (consume_vex) { updated_atk_cond.vex_target_idx = -1; dirty_atk = true; }
        if (consume_sap) { updated_atk_cond.sapped = false;       dirty_atk = true; }

        if (atk_stats.weapon_mastery > 0 && w.proficient &&
            w.mastery != WeaponMastery::None) {
            if (r.hit) {
                switch (w.mastery) {
                case WeaponMastery::Sap: {
                    Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                    tc.sapped = true;
                    bm.setAgentConditions(action.target_idx, tc);
                    log_("{} is Sapped (disadvantage on its next attack)",
                         agentName(bm, action.target_idx));
                    break;
                }
                case WeaponMastery::Slow: {
                    if (r.total_damage > 0) {
                        Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                        tc.slowed = true;
                        bm.setAgentConditions(action.target_idx, tc);
                        log_("{} is Slowed (Speed -10 ft until your next turn)",
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Vex: {
                    if (r.total_damage > 0) {
                        updated_atk_cond.vex_target_idx = action.target_idx;
                        dirty_atk = true;
                        log_("{} gains Vex (advantage on next attack vs {})",
                             agentName(bm, action.attacker_idx),
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Push: {
                    if (tgt_sz <= 2) { updated_atk_cond.push_available = true; dirty_atk = true; }
                    break;
                }
                case WeaponMastery::Topple: {
                    updated_atk_cond.topple_available = true; dirty_atk = true;
                    break;
                }
                case WeaponMastery::Cleave: {
                    if (!atk_cond.cleave_used_this_turn) {
                        updated_atk_cond.cleave_available = true; dirty_atk = true;
                    }
                    break;
                }
                default: break;  // Graze handled on miss; Nick is an action-economy property
                }
            } else if (w.mastery == WeaponMastery::Graze) {
                // A miss (including a natural 1) still deals the attack ability modifier.
                int graze = std::max(0, damageAbilityMod(w, atk_stats));
                if (graze > 0) {
                    int overflow = std::max(0, graze - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - graze);
                    tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
                    r.hp_after    = tgt_stats.hp_cur;
                    r.target_down = (r.hp_after <= 0);
                    r.total_damage += graze;
                    r.damage_breakdown.push_back({"graze", graze});
                    graze_damage = graze;
                    log_("Graze: {} takes {} damage despite the miss",
                         agentName(bm, action.target_idx), graze);
                }
            }
        }
        if (dirty_atk) bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    bm.setAgentStats(action.target_idx, tgt_stats);  // apply HP change

    if (r.total_damage > 0 && (r.hit || graze_damage > 0)) {
        // Taking weapon damage forces a concentration save on the target (DC = max(10, dmg/2)).
        checkConcentrationOnDamage(bm, action.target_idx, r.total_damage);
        // ...and ends/triggers on-damage conditions (Sleep, Hypnotic Pattern, Tasha's).
        processDamageTaken(bm, action.target_idx, r.total_damage);
    }

    // Auto-trigger Unconscious if HP drops to 0 or below
    bool just_knocked_unconscious = (r.hp_after <= 0 && !tgt_cond.unconscious && !tgt_cond.dead);
    if (just_knocked_unconscious) {
        log_("[ATTACK KNOCKDOWN] {} going unconscious from attack damage", agentName(bm, action.target_idx));
        applyUnconscious(bm, action.target_idx);
        r.target_down = true;
        // Don't roll death save yet - they'll roll on their next turn or if they take more damage

        // TASK A: Dark One's Blessing (Fiend L3): temp HP on kill
        if (atk_stats.character_class == CharacterClass::Warlock && atk_stats.warlock_subclass == FiendPath && atk_stats.char_level >= 3) {
            int chaMod = (atk_stats.cha - 10) / 2;
            if (atk_stats.cha < 10 && (atk_stats.cha - 10) % 2 != 0) --chaMod;
            int bonus = std::max(1, chaMod + atk_stats.char_level);
            atk_stats.temp_hp = std::max(atk_stats.temp_hp, bonus);
            bm.setAgentStats(action.attacker_idx, atk_stats);
            log_("{}: Dark One's Blessing grants {} temp HP", agentName(bm, action.attacker_idx), bonus);
        }
    }

    // Death save on damage for agents already unconscious (unless melee hit within 5ft, which auto-fails 2)
    // Only roll if the agent was ALREADY unconscious BEFORE this attack (not if just knocked unconscious)
    if (r.hp_after <= 0 && tgt_cond.unconscious && !tgt_cond.dead && r.total_damage > 0 && !just_knocked_unconscious) {
        log_("[DEATH SAVE ON DAMAGE] {} was already unconscious, rolling death save (was unconscious before: {})",
             agentName(bm, action.target_idx), tgt_cond.unconscious);
        // Check if this is a melee hit within 5ft (those already auto-failed 2 above)
        bool is_melee_within_5ft = false;
        if (r.critical && action.weapon_idx < static_cast<int>(atk_pt.weapons.size())) {
            const Weapon& wpn = atk_pt.weapons[static_cast<std::size_t>(action.weapon_idx)];
            if (wpn.type == WeaponType::Melee) {  // melee weapon
                Cell src = agents[action.attacker_idx].origin;
                Cell tgt = agents[action.target_idx].origin;
                int dist = std::max(std::abs(src.col - tgt.col), std::abs(src.row - tgt.row));
                if (dist <= 1) {
                    is_melee_within_5ft = true;
                }
            }
        }
        // Only roll regular death save if NOT a melee within 5ft (which auto-fails 2 instead)
        if (!is_melee_within_5ft) {
            rollDeathSave(bm, action.target_idx);
        }
    }

    // Auto-wake if healed above 0 HP while unconscious
    // But only if not actively dying (death save failures already set by damage/auto-crit).
    // Uses the pre-attack snapshot: a rider this attack applied (Cunning Strike Knock Out) must
    // not be undone by the same hit just because the target still has positive HP.
    if (r.hp_after > 0 && tgt_unconscious_at_attack && !tgt_cond.dead && tgt_cond.death_save_failures == 0) {
        Agent::Conditions updated_tgt_cond = tgt_cond;
        updated_tgt_cond.unconscious = false;
        updated_tgt_cond.incapacitated = false;
        updated_tgt_cond.prone = false;  // Waking up also clears prone
        updated_tgt_cond.death_save_successes = 0;
        updated_tgt_cond.death_save_failures = 0;
        updated_tgt_cond.stabilized = false;
        bm.setAgentConditions(action.target_idx, updated_tgt_cond);
        log_("Target healed above 0 HP and wakes up!");
    }

    // Apply weapon conditions on hit
    if (r.hit && !w.conditions.empty()) {
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

        for (const auto& weapon_cond : w.conditions) {
            bool condition_applies = false;

            if (!weapon_cond.requires_save) {
                // Condition is automatic on hit
                condition_applies = true;
            } else {
                // Target makes a save to resist the condition
                int save_dc = spellSaveDcFromAbility(atk_stats, weapon_cond.save_dc_ability);

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

                condition_applies = !saved;

                if (!saved) {
                    log_("Target failed {} save vs weapon condition '{}' (save DC {})",
                         ability_name(weapon_cond.save_ability), weapon_cond.condition_name, save_dc);
                } else {
                    log_("Target resisted weapon condition '{}' (save DC {})",
                         weapon_cond.condition_name, save_dc);
                }
            }

            if (condition_applies) {
                // Apply condition
                int save_dc = spellSaveDcFromAbility(atk_stats, weapon_cond.save_dc_ability);
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
                log_("Weapon condition '{}' applied to target", weapon_cond.condition_name);
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

    // If attacker was hidden, reveal them (clear hidden condition)
    if (attacker_was_hidden && action.attacker_idx >= 0 && action.attacker_idx < static_cast<int>(agents.size())) {
        Agent::Conditions cond = bm.getAgentConditions(action.attacker_idx);
        cond.hidden = false;
        bm.setAgentConditions(action.attacker_idx, cond);
        log_("{} is no longer hidden", agents[action.attacker_idx].agent->name());
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

// Cells of a Sphere of the given foot-radius centered on (center_col, center_row).
// Matches the integer-radius disc used by the persistent-effect builder, so a moving
// Sphere's footprint is identical whether it's first placed or later re-centered.
static std::vector<Cell> sphereCellsAround(int center_col, int center_row, int radius_ft)
{
    std::vector<Cell> cells;
    const int radius_cells = (radius_ft + 4) / 5;  // feet -> cells (5 ft/cell)
    for (int c = center_col - radius_cells; c <= center_col + radius_cells; ++c)
        for (int r = center_row - radius_cells; r <= center_row + radius_cells; ++r) {
            const int dc = c - center_col, dr = r - center_row;
            if (dc * dc + dr * dr <= radius_cells * radius_cells)
                cells.push_back(Cell{c, r});
        }
    return cells;
}

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

// Re-center any persistent Sphere effects anchored to this agent on their current
// position. Called when the agent moves and at the start of their turn so an
// Emanation (e.g. Spirit Guardians) tracks the caster.
void CombatEngine::recomputeAnchoredEffects(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;
    const Cell origin = agents[static_cast<std::size_t>(agent_idx)].origin;

    std::vector<std::pair<int, int>> to_update;  // (effect_id, radius_ft)
    for (const auto& eff : bm.activeSpellEffects())
        if (eff.anchor_agent_idx == agent_idx)
            to_update.emplace_back(eff.effect_id, eff.spell.radius);

    for (const auto& [id, radius] : to_update)
        bm.setSpellEffectCells(id, sphereCellsAround(origin.col, origin.row, radius));
}

bool CombatEngine::applyZoneIfNewThisTurn(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const int64_t key = (static_cast<int64_t>(effect.effect_id) << 32)
                      ^ static_cast<int64_t>(static_cast<uint32_t>(target_idx));
    auto it = zoneAppliedTurn_.find(key);
    if (it != zoneAppliedTurn_.end() && it->second == turnCounter_)
        return false;  // already applied to this target by this effect this turn
    applySpellEffect(bm, effect, target_idx);
    zoneAppliedTurn_[key] = turnCounter_;
    return true;
}

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

    const Agent::Stats& caster_stats = caster_pa.agent->getStats();

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
            // Remove old spell's terrain when dropping concentration
            [[maybe_unused]] auto removed_ids = bm.removeTerrainEffectsBySource(action.caster_idx);
        }
    }

    // Moving Sphere (Emanation): the area is centered on the caster, not an aimed point.
    const bool moving_sphere = (sp.geometry == Spell::Sphere && sp.moves_with_caster);
    int center_col = action.aoe_col;
    int center_row = action.aoe_row;
    if (moving_sphere) {
        center_col = caster_pa.origin.col;
        center_row = caster_pa.origin.row;
    }

    std::vector<int> targets =
        (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple)
        ? action.target_indices
        : resolveAoeTargets(agents, sp, action.caster_idx, center_col, center_row);

    // Evoker safe targets: fully exclude the caster's protected allies from AoE spells
    // (no save, no damage, no conditions). Single/Multiple are directly targeted, so untouched.
    if (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple) {
        auto it = safeTargets_.find(action.caster_idx);
        if (it != safeTargets_.end() && !it->second.empty()) {
            const std::vector<int>& safe = it->second;
            std::erase_if(targets, [&safe](int t) {
                return std::find(safe.begin(), safe.end(), t) != safe.end();
            });
        }
    }

    // Emanation ignores the caster's own space — the caster is never a target.
    if (moving_sphere)
        std::erase(targets, action.caster_idx);

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
    bool any_kill = false;  // TASK A: Dark One's Blessing tracking

    // TASK D: Radiant Soul (Celestial L6): does this spell deal Radiant(8) or Fire(2) damage?
    // Computed once per cast; the +CHA bonus below applies to the first damaged target this turn.
    bool spell_radiant_or_fire = false;
    for (const auto& rinfo : sp.magic_damage_rolls)
        if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }
    if (!spell_radiant_or_fire)
        for (const auto& rinfo : sp.physical_damage_rolls)
            if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }

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

            // Frightened: caster has disadvantage when fear source is in LOS
            if (caster_pa.agent->getConditions().frightened) {
                for (const auto& ac : activeAgentConditions_) {
                    if (ac.agent_idx == action.caster_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
                        if (bm.hasLineOfSight(caster_pa.origin, caster_pa.agent->getSize(),
                                              bm.placedAgents()[ac.caster_idx].origin, 1)) {
                            caster_dis = true;
                            log_("Disadvantage: caster is frightened and fear source is in LOS");
                        }
                        break;
                    }
                }
            }

            // Grappled: caster has disadvantage on spell attacks except against the grappler
            if (caster_pa.agent->getConditions().grappled) {
                if (action.target_indices[0] != caster_pa.agent->getConditions().grappler_idx) {
                    caster_dis = true;
                    log_("Disadvantage: caster is grappled");
                }
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
            tr.critical   = (d20_val >= caster_stats.crit_threshold);
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

                // Agonizing Blast: add CHA modifier to each Eldritch Blast beam's damage.
                if (sp.name == "Eldritch Blast" &&
                    caster_stats.character_class == CharacterClass::Warlock &&
                    caster_stats.hasInvocation(0)) {
                    int chaMod = abilityMod(caster_stats.cha);
                    if (chaMod > 0) {
                        dmg += chaMod;
                        log_("Agonizing Blast: +{} damage", chaMod);
                    }
                }

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

            // Paralyzed, Stunned, and Unconscious targets automatically fail STR and DEX saves
            bool auto_fail = (target_cond.paralyzed || target_cond.stunned || target_cond.unconscious) &&
                            (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

            // Barbarian Danger Sense (L2+): Advantage on DEX saves unless Incapacitated
            if (sp.save_ability == SaveDex && !target_cond.incapacitated &&
                tgt_stats.character_class == CharacterClass::Barbarian && tgt_stats.char_level >= 2) {
                target_adv = true;
                log_("Danger Sense: target has Advantage on DEX save");
            }

            int save_d20;
            if (auto_fail) {
                save_d20 = 1;  // Automatic fail
                std::string reason = target_cond.paralyzed ? "paralyzed" : (target_cond.stunned ? "stunned" : "unconscious");
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

            // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
            // A successful save already halved per-roll above; override to the Evasion outcome.
            if (sp.save_ability == SaveDex && sp.type != Spell::Heal &&
                tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 7 &&
                !target_cond.incapacitated) {
                dmg = tr.saved ? 0 : (dmg / 2);
                log_("Evasion: {} {} damage on a DEX save", agentName(bm, tgt_idx),
                     tr.saved ? "takes no" : "halves");
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

        // TASK D: Radiant Soul (Celestial L6+): once per turn, add CHA mod to one damaging
        // Radiant/Fire spell. Applies across all attack types (AttackRoll/Save/Automatic).
        if (tr.total_damage > 0 && sp.type != Spell::Heal && spell_radiant_or_fire &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.warlock_subclass == CelestialPath && caster_stats.char_level >= 6) {
            Agent::Conditions caster_cond = bm.getAgentConditions(action.caster_idx);
            if (!caster_cond.radiant_soul_used) {
                int chaMod = (caster_stats.cha - 10) / 2;
                if (caster_stats.cha < 10 && (caster_stats.cha - 10) % 2 != 0) --chaMod;
                if (chaMod > 0) {
                    int overflow = std::max(0, chaMod - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - chaMod);
                    tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                    tr.total_damage += chaMod;
                    log_("{}: Radiant Soul adds {} damage to {} spell", agentName(bm, action.caster_idx), chaMod, sp.name);
                }
                caster_cond.radiant_soul_used = true;
                bm.setAgentConditions(action.caster_idx, caster_cond);
            }
        }

        // Cleric Blessed Strikes — Potent Spellcasting (L7+): add WIS mod to Cleric cantrip damage.
        if (tr.total_damage > 0 && sp.type != Spell::Heal && sp.level == 0 &&
            caster_stats.character_class == CharacterClass::Cleric &&
            caster_stats.char_level >= 7 &&
            caster_stats.blessed_strike == BlessedStrikePotentSpellcasting) {
            int wisMod = (caster_stats.wis - 10) / 2;
            if (caster_stats.wis < 10 && (caster_stats.wis - 10) % 2 != 0) --wisMod;
            if (wisMod > 0) {
                int overflow = std::max(0, wisMod - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - wisMod);
                tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                tr.total_damage += wisMod;
                log_("{}: Potent Spellcasting adds {} damage to {}", agentName(bm, action.caster_idx), wisMod, sp.name);
            }
        }

        tr.hp_after    = tgt_stats.hp_cur;
        tr.target_down = (tgt_stats.hp_cur <= 0);
        bm.setAgentStats(tgt_idx, tgt_stats);

        // Repelling Blast: each Eldritch Blast beam that hits pushes the target 10 ft away.
        if (tr.hit && sp.name == "Eldritch Blast" &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.hasInvocation(1)) {
            int moved = bm.forceMoveAgent(tgt_idx, caster_pa.origin, 10);
            if (moved > 0)
                log_("Repelling Blast: {} pushed {} ft", agentName(bm, tgt_idx), moved * 5);
        }

        // TASK A: Dark One's Blessing tracking
        if (tr.target_down) any_kill = true;

        // Auto-trigger Unconscious if HP drops to 0 or below
        if (tgt_stats.hp_cur <= 0) {
            Agent::Conditions tgt_cond_before = bm.getAgentConditions(tgt_idx);
            bool spell_just_knocked_unconscious = (!tgt_cond_before.unconscious && !tgt_cond_before.dead);
            if (spell_just_knocked_unconscious) {
                log_("[SPELL KNOCKDOWN] {} going unconscious from spell damage ({})", agentName(bm, tgt_idx), sp.name);
                applyUnconscious(bm, tgt_idx);
                // Don't roll death save yet - they'll roll on their next turn or if they take more damage
            } else if (tgt_cond_before.unconscious && !tgt_cond_before.dead && tr.total_damage > 0) {
                log_("[SPELL DEATH SAVE] {} already unconscious, rolling death save from spell damage", agentName(bm, tgt_idx));
                // Death save on damage for agents already unconscious
                rollDeathSave(bm, tgt_idx);
            }
        }

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

        // On-damage condition behavior (Sleep/Hypnotic Pattern end; Tasha's re-saves) for
        // any pre-existing condition on this target. Runs before this spell's own conditions
        // are applied, so a damaging spell can't instantly cancel the condition it just set.
        processDamageTaken(bm, tgt_idx, tr.total_damage);

        // Apply spell-based conditions (e.g., Hold Person applies Paralyzed)
        if (!sp.conditions.empty()) {
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

            for (const auto& spell_cond : sp.conditions) {
                // Determine if this specific condition applies to the target
                log_("[COND] Processing condition '{}' for {}, requires_save={}, push_ft={}",
                     spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);
                bool condition_applies = false;
                bool target_failed_save = false;

                // Determine if condition applies based on spell type and whether it requires a save
                if (spell_cond.requires_save) {
                    // Condition requires a save
                    if (sp.attack_type == Spell::Save) {
                        // For Save spells, reuse the existing save result
                        target_failed_save = !tr.saved;
                        condition_applies = target_failed_save;
                        log_("[COND SAVE] {} vs {}: tr.saved={}, target_failed_save={}, condition_applies={}",
                             spell_cond.condition_name, agentName(bm, tgt_idx), tr.saved, target_failed_save, condition_applies);
                    } else {
                        // For other spell types, roll a new save for this condition
                        int save_dc = spellSaveDc(caster_stats);

                        int save_d20 = roll(20);
                        auto saveMod = [&](SaveAbility_t ab) -> int {
                            int score = 0; bool prof = false;
                            switch (ab) {
                                case SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                                case SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                                case SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                                case SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                                case SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                                default:      score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                            }
                            int m = (score - 10) / 2;
                            if (score < 10 && (score - 10) % 2 != 0) --m;
                            return m + (prof ? tgt_stats.prof_bonus : 0);
                        };

                        bool save_succeeded = (save_d20 + saveMod(spell_cond.save_ability) >= save_dc);
                        target_failed_save = !save_succeeded;
                        condition_applies = target_failed_save;

                        log_("{} save vs {} condition: rolled {} + {} = {} vs DC {} — {}",
                             ability_name(spell_cond.save_ability),
                             spell_cond.condition_name,
                             save_d20, saveMod(spell_cond.save_ability),
                             save_d20 + saveMod(spell_cond.save_ability),
                             save_dc,
                             save_succeeded ? "SAVED" : "FAILED");
                    }
                } else {
                    // Condition doesn't require a save, apply based on spell attack type
                    if (sp.attack_type == Spell::AttackRoll) {
                        condition_applies = tr.hit;
                    } else {
                        condition_applies = true;
                    }
                }

                if (condition_applies) {
                    log_("[APPLY] Applying condition '{}' to {}, requires_save={}, push_ft={}",
                         spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);

                    ActiveAgentCondition cond;
                    cond.agent_idx   = tgt_idx;
                    cond.caster_idx  = action.caster_idx;
                    cond.spell_idx   = action.spell_idx;
                    cond.condition_name = spell_cond.condition_name;
                    cond.save_ability = spell_cond.save_ability;
                    cond.on_damage = spell_cond.on_damage;

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
                    if (spell_cond.condition_name == "Push" && spell_cond.push_ft > 0) {
                        log_("[PUSH] Attempting to push {} {} feet by spell '{}'", agentName(bm, tgt_idx), spell_cond.push_ft, sp.name);
                        auto spell_agents = bm.placedAgents();
                        if (action.caster_idx >= 0 && action.caster_idx < static_cast<int>(spell_agents.size())) {
                            const auto& caster = spell_agents[action.caster_idx];
                            log_("[PUSH] Caster at ({},{}), target at ({},{})", caster.origin.col, caster.origin.row, spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            int cells_moved = bm.forceMoveAgent(tgt_idx, caster.origin, spell_cond.push_ft);
                            log_("[PUSH] forceMoveAgent returned {} cells moved", cells_moved);
                            tr.push_ft_applied = cells_moved * 5;
                            if (cells_moved > 0) {
                                log_("Target pushed {} feet by {}", tr.push_ft_applied, sp.name);
                                log_("[PUSH] Target now at ({},{})", spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            } else {
                                log_("[PUSH] No movement occurred (blocked or out of range)");
                            }
                        } else {
                            log_("[PUSH] Invalid caster index: {}", action.caster_idx);
                        }
                    }
                }
            }
        }

        result.target_results.push_back(tr);
    }

    // TASK A: Dark One's Blessing (Fiend L3): temp HP on spell kill
    if (any_kill && caster_stats.character_class == CharacterClass::Warlock && caster_stats.warlock_subclass == FiendPath && caster_stats.char_level >= 3) {
        int chaMod = (caster_stats.cha - 10) / 2;
        if (caster_stats.cha < 10 && (caster_stats.cha - 10) % 2 != 0) --chaMod;
        int bonus = std::max(1, chaMod + caster_stats.char_level);
        Agent::Stats updated_stats = bm.getAgentStats(action.caster_idx);
        updated_stats.temp_hp = std::max(updated_stats.temp_hp, bonus);
        bm.setAgentStats(action.caster_idx, updated_stats);
        log_("{}: Dark One's Blessing grants {} temp HP", agentName(bm, action.caster_idx), bonus);
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
        const bool is_aoe = (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple);
        if (is_aoe) {
            // AoE spells create a persistent area (terrain/zone); concentration holds
            // even with no current targets in the area.
            should_concentrate = true;
        } else if (!sp.conditions.empty()) {
            // Targeted (Single/Multiple) condition spell: only concentrate if a
            // condition actually landed (e.g. Hold Person fizzles if every target saved).
            should_concentrate = any_conditions_applied;
        } else {
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
            // For a moving Sphere, center_col/center_row are the caster's origin.
            effect_cells = sphereCellsAround(center_col, center_row, sp.radius);
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
            effect.anchor_agent_idx = moving_sphere ? action.caster_idx : -1;
            [[maybe_unused]] int effect_id = bm.addSpellEffect(effect);
        }
    }

    // Terrain placement: if spell creates difficult terrain
    if (result.valid && sp.terrain_difficulty != TerrainDifficulty::Normal) {
        Cell center = Cell{action.aoe_col, action.aoe_row};
        Cell caster_origin = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].origin;
        int caster_size = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].agent->getSize();

        auto raw_cells = bm.aoeCells(center, sp, caster_origin);
        auto terrain_cells = bm.filterSpellCells(raw_cells, caster_origin, caster_size, sp, center);

        if (!terrain_cells.empty()) {
            int terrain_id = bm.placeTerrainEffect(
                sp.name, terrain_cells, sp.terrain_difficulty,
                sp.duration, action.caster_idx,
                sp.slip_save_dc, sp.slip_distance_feet,
                action.spell_idx, sp.requires_concentration);

            if (terrain_id >= 0) {
                result.terrain_effect_ids.push_back(terrain_id);

                // Slipping terrain: immediate DEX save for agents in the AoE
                if (sp.terrain_difficulty == TerrainDifficulty::Slipping) {
                    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
                        if (i == action.caster_idx) continue;
                        Cell agent_cell = bm.placedAgents()[static_cast<std::size_t>(i)].origin;
                        bool in_aoe = std::any_of(terrain_cells.begin(), terrain_cells.end(),
                            [&agent_cell](const Cell& c) { return c.col == agent_cell.col && c.row == agent_cell.row; });
                        if (!in_aoe) continue;
                        auto stats = getAgentStats(bm, i);
                        int dex_mod = (stats.dex - 10) / 2;
                        int d20 = roll(20);
                        if (d20 + dex_mod < sp.slip_save_dc) {
                            Agent::Conditions cond_i = bm.getAgentConditions(i);
                            cond_i.prone = true;
                            bm.setAgentConditions(i, cond_i);
                            log_("Slipping terrain: {} fails DEX save (d20={}) — prone.",
                                 bm.placedAgents()[i].agent->name(), d20);
                        }
                    }
                }
            }
        }
    }

    // If caster was hidden and cast a spell, reveal them
    if (result.valid && action.caster_idx >= 0 && action.caster_idx < static_cast<int>(agents.size())) {
        const Agent::Conditions& caster_cond = agents[static_cast<std::size_t>(action.caster_idx)].agent->getConditions();
        if (caster_cond.hidden) {
            Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
            cond.hidden = false;
            bm.setAgentConditions(action.caster_idx, cond);
            log_("{} is no longer hidden", agents[static_cast<std::size_t>(action.caster_idx)].agent->name());
        }
    }

    // Decrement resources (uses or spell slots) after successful cast
    if (result.valid) {
        log_("[DEBUG execute_spell] result.valid=true, slot_level={}, caster_idx={}", action.slot_level, action.caster_idx);
        PlacedAgent& pa = bm.placedAgentMut(action.caster_idx);
        Spell& spell_mut = pa.spells[static_cast<std::size_t>(action.spell_idx)];
        Agent::Stats& stats = pa.agent->getStats();

        // Mark leveled spell cast (once per turn, even if upcasted)
        if (sp.level > 0) {
            stats.markLeveledSpellCast(sp.level);
        }

        if (!spell_mut.resource_name.empty()) {
            // Class feature: spend its named resource (e.g. Channel Divinity) instead of a slot.
            int cost = std::max(1, spell_mut.resource_cost);
            Resource* res = stats.getResource(spell_mut.resource_name);
            if (res) res->spend(cost);
            log_("{} spends {} {}", agentName(bm, action.caster_idx), cost, spell_mut.resource_name);
        } else if (stats.is_npc) {
            log_("[DEBUG execute_spell] NPC branch taken for agent {}", action.caster_idx);
            // NPC: decrement N/day uses
            if (spell_mut.uses_max > 0) {
                spell_mut.uses_remaining = std::max(0, spell_mut.uses_remaining - 1);
            }
        } else {
            log_("[DEBUG execute_spell] Player branch taken for agent {}", action.caster_idx);
            // Player: decrement spell slot (if not a cantrip)
            int slot_level = action.slot_level > 0 ? action.slot_level : sp.level;
            log_("[DEBUG execute_spell] Calculated slot_level={}, checking if > 0 and <= 9", slot_level);
            if (slot_level > 0 && slot_level <= 9) {
                auto& slots = stats.spell_slots_remaining;
                slots[static_cast<std::size_t>(slot_level - 1)] =
                    std::max(0, slots[static_cast<std::size_t>(slot_level - 1)] - 1);

                // Wizard Diviner L6: Expert Divination
                // Cast Divination spell with L2+ slot → regain highest-level lower-level slot (max L5)
                log_("[EXPERT DIVINATION DEBUG] Spell: {}, School: {}, IsWizard: {}, IsDiviner: {}, IsL2Plus: {}",
                     spell_mut.name, static_cast<int>(spell_mut.school),
                     (stats.character_class == Wizard ? 1 : 0),
                     (stats.wizard_subclass == DivinierPath ? 1 : 0),
                     (slot_level >= 2 ? 1 : 0));
                log_("[EXPERT DIVINATION DEBUG] Spell::Divination value: {}, Match: {}",
                     static_cast<int>(Spell::Divination), (spell_mut.school == Spell::Divination ? 1 : 0));

                if (stats.character_class == Wizard && stats.wizard_subclass == DivinierPath &&
                    spell_mut.school == Spell::Divination && slot_level >= 2) {
                    log_("[EXPERT DIVINATION] Restoring spell slot for spell: {}", spell_mut.name);
                    // Find highest expended lower-level slot (capped at L5)
                    int restore_level = -1;
                    for (int lvl = std::min(5, slot_level - 1); lvl >= 1; --lvl) {
                        if (slots[static_cast<std::size_t>(lvl - 1)] <
                            stats.spell_slots_max[static_cast<std::size_t>(lvl - 1)]) {
                            restore_level = lvl;
                            break;
                        }
                    }
                    if (restore_level > 0) {
                        slots[static_cast<std::size_t>(restore_level - 1)]++;
                        log_("{} Expert Divination: restored 1 level {} spell slot", agentName(bm, action.caster_idx), restore_level);
                    }
                }

                // Wizard Abjurer L3+: Arcane Ward auto-charging
                // Cast abjuration spell → Ward gains 2 × spell slot level (capped at max)
                if (stats.character_class == Wizard && stats.wizard_subclass == AbjurerPath &&
                    stats.char_level >= 3 && spell_mut.school == Spell::Abjuration) {
                    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
                    int ward_gain = 2 * slot_level;
                    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);
                    log_("{} Arcane Ward charged: +{} HP ({}/{})", agentName(bm, action.caster_idx), ward_gain, stats.temp_hp, max_ward);
                }
            }
        }

        // Persist stats back to battle map after modifications
        bm.setAgentStats(action.caster_idx, stats);
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

// ─────────────────────────────────────────────────────────────────────────────
//  Apply grappled condition to target
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyGrappled(BattleMap& bm, int target_idx, int grappler_idx, int escape_dc) noexcept
{
    Agent::Conditions cond = getAgentConditions(bm, target_idx);
    cond.grappled = true;
    cond.grappler_idx = grappler_idx;
    cond.grapple_escape_dc = escape_dc;
    cond.grapple_range_ft = 5;
    setAgentConditions(bm, target_idx, cond);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Execute grapple attempt
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
//  Execute grapple escape attempt
// ─────────────────────────────────────────────────────────────────────────────

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
        if (fx.spell.type != Spell::Heal)
            processDamageTaken(bm, fx.target_idx, std::max(0, total));
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
    zoneAppliedTurn_.clear();
    turnCounter_ = 0;
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
    {
        Agent::Stats cs = bm.getAgentStats(agent_idx);
        if (cs.character_class == CharacterClass::Warlock && cs.hasInvocation(3))
            has_adv = true;  // Eldritch Mind
    }
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

void CombatEngine::updateDarknessBlinding(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    const VisibilityLevel obscuration = bm.getObscurationAtCell(pa.origin);

    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    bool should_be_blinded = false;

    // Check if agent should be blinded based on darkness/heavy obscurement
    if (obscuration == VisibilityLevel::Dark) {
        // Heavily Obscured (Darkness): blinded unless have darkvision
        should_be_blinded = (stats.darkvision_range == 0);
    } else if (obscuration == VisibilityLevel::MagicalDark) {
        // Magically Dark (Impenetrable): blinded unless have devil's sight
        should_be_blinded = (stats.devilssight_range == 0);
    }
    // BrightLight: full visibility, never blinded
    // DimLight: lightly obscured but visible, never blinded
    // PartiallyObscured: not fully blinded (disadvantage on perception, but not Blinded condition)

    // Apply or remove blinded condition as needed
    if (should_be_blinded && !cond.blinded) {
        cond.blinded = true;
        bm.setAgentConditions(agent_idx, cond);
        log_("{} is blinded by darkness", pa.agent->name());
    } else if (!should_be_blinded && cond.blinded) {
        // Only remove blinded if it was from darkness (not from a spell like Blindness/Deafness)
        // For now, we'll remove it - in future we could track the source
        cond.blinded = false;
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

DropConcentrationResult CombatEngine::dropConcentration(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return {};
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating)
        return {};

    DropConcentrationResult result;
    result.dropped    = true;
    result.spell_name = cond.concentrating_on;

    // 1. Remove this caster's concentration terrain only (leave non-concentration
    //    timed terrain, e.g. Grease, which is not a concentration spell in 5e).
    for (const auto& eff : bm.activeTerrainEffects()) {
        if (eff.source_agent_idx == agent_idx && eff.requires_concentration)
            result.removed_terrain_ids.push_back(eff.id);
    }
    for (int tid : result.removed_terrain_ids)
        bm.removeTerrainEffect(tid);

    // 2. Remove this caster's concentration spell-effects only
    for (const auto& eff : bm.activeSpellEffects()) {
        if (eff.caster_idx == agent_idx && eff.spell.requires_concentration)
            result.removed_spell_effect_ids.push_back(eff.effect_id);
    }
    for (int eid : result.removed_spell_effect_ids)
        bm.removeSpellEffect(eid);

    // 3. Remove conditions applied by this agent's concentration spells
    const auto& spells = bm.getAgentSpells(agent_idx);
    for (const auto& ac : activeAgentConditions_) {
        if (ac.caster_idx == agent_idx &&
            ac.spell_idx >= 0 && ac.spell_idx < static_cast<int>(spells.size()) &&
            spells[static_cast<std::size_t>(ac.spell_idx)].requires_concentration)
            result.removed_condition_ids.push_back(ac.condition_id);
    }
    for (int cid : result.removed_condition_ids)
        removeAgentCondition(cid);

    // 4. Clear C++ concentration state
    cond.concentrating    = false;
    cond.concentrating_on = {};
    bm.setAgentConditions(agent_idx, cond);

    return result;
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

void CombatEngine::clearAllConcentration(BattleMap& bm)
{
    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
        if (bm.getAgentConditions(i).concentrating)
            (void)dropConcentration(bm, i);  // cascades: terrain + spell effects + conditions + flag
    }
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
    int healed = std::min(total_healing, target_stats.hp_max - target_stats.hp_cur);
    target_stats.hp_cur = std::min(target_stats.hp_max, target_stats.hp_cur + total_healing);
    bm.setAgentStats(target_idx, target_stats);

    log_("{}: Healing Light: {} d6 = {} healing to {}", agentName(bm, healer_idx), num_dice, total_healing, agentName(bm, target_idx));
    return healed;
}

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
        const int save_total = roll(20) + mod;

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
        if (!w.name.empty() && w.name != "Unnamed") {
	    log_("{} dropped weapon {}", agentName(bm, idx), w.name);
            (void)bm.placeItem(pa.origin, w, "");
            w = Weapon{};
        }
    }
}

void CombatEngine::applyFrightened(BattleMap& bm, int idx) noexcept
{
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
    bm.setAgentConditions(attacker_idx, ac);

    const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
    int feet = bm.forceMoveAgent(target_idx, origin, 10) * 5;
    if (feet > 0)
        log_("{} pushes {} {} ft (Push mastery)",
             agentName(bm, attacker_idx), agentName(bm, target_idx), feet);
    return feet;
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
    res.save_roll = roll(20) + mod;

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
    bm.setAgentConditions(idx, cond);

    log_("Agent is Unconscious: incapacitated, prone, speed 0, attacks have advantage, auto-fail STR/DEX saves, auto-crit within 5ft");
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

// ─────────────────────────────────────────────────────────────────────────────
//  Barbarian Rage lifecycle methods
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
        stats.temp_hp = std::max(stats.temp_hp, vitality_temp_hp);
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
    log_("{} ends Rage: raging=false, BPS resistance cleared, reckless_attack cleared", agentName(bm, idx));
}

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

// ─────────────────────────────────────────────────────────────────────────────
//  Diviner Wizard Portent Dice
// ─────────────────────────────────────────────────────────────────────────────

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

bool CombatEngine::expendArcaneWardSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Validate: Abjurer L3+ with active ward
    if (stats.character_class != Wizard || stats.wizard_subclass != AbjurerPath ||
        stats.char_level < 3 || stats.temp_hp <= 0) {
        return false;
    }

    // Validate: slot_level is valid (1-9)
    if (slot_level < 1 || slot_level > 9) return false;

    // Validate: agent has remaining spell slot at this level
    if (stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)] <= 0) {
        return false;
    }

    // Expend the slot
    stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)]--;

    // Charge the ward
    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
    int ward_gain = 2 * slot_level;
    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends Level {} slot, Arcane Ward now {}/{}",
         agentName(bm, agent_idx), slot_level, stats.temp_hp, max_ward);

    return true;
}

void CombatEngine::rollDeathSave(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    const auto& agent = agents[static_cast<std::size_t>(idx)];
    const auto& stats = agent.agent->getStats();

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.unconscious || cond.dead || cond.stabilized) {
        log_("[DEATH SAVE SKIP] {} - unconscious={}, dead={}, stabilized={}",
             agentName(bm, idx), cond.unconscious, cond.dead, cond.stabilized);
        return;
    }
    log_("[DEATH SAVE ROLL] {} rolling death save (current: {}/3 successes, {}/3 failures)",
         agentName(bm, idx), cond.death_save_successes, cond.death_save_failures);

    int con_mod = (stats.con - 10) / 2;
    if (stats.con < 10 && (stats.con - 10) % 2 != 0) --con_mod;
    int death_d20 = roll(20);
    int death_total = death_d20 + con_mod;

    if (death_d20 == 20) {
        cond.stabilized = true;
        cond.death_save_successes = 3;
        bm.setAgentConditions(idx, cond);
        log_("Death save (on damage): NATURAL 20! Character automatically stabilizes");
    } else if (death_d20 == 1) {
        cond.death_save_failures += 2;
        if (cond.death_save_failures >= 3) {
            cond.dead = true;
            log_("Death save (on damage): NATURAL 1! Character dies");
        } else {
            log_("Death save (on damage): Natural 1 (2 failures) — {}/3 failures", cond.death_save_failures);
        }
        bm.setAgentConditions(idx, cond);
    } else if (death_total >= 10) {
        cond.death_save_successes++;
        if (cond.death_save_successes >= 3) {
            cond.stabilized = true;
            log_("Death save (on damage): SUCCESS (stabilized) — {}/3 successes", cond.death_save_successes);
        } else {
            log_("Death save (on damage): SUCCESS — {}/3 successes", cond.death_save_successes);
        }
        bm.setAgentConditions(idx, cond);
    } else {
        cond.death_save_failures++;
        if (cond.death_save_failures >= 3) {
            cond.dead = true;
            log_("Death save (on damage): FAILED — Character dies");
        } else {
            log_("Death save (on damage): FAILED — {}/3 failures", cond.death_save_failures);
        }
        bm.setAgentConditions(idx, cond);
    }
}

void CombatEngine::applyLongRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);

        // Restore spell slots and all resources
        stats.restore_resources_long_rest();

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

HideResult CombatEngine::checkHide(BattleMap& bm, int agent_idx, bool in_combat) noexcept
{
    HideResult result;
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        result.log_message = "Invalid agent";
        return result;
    }

    const PlacedAgent& hider_pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& hider_stats = hider_pa.agent->getStats();
    Cell hider_origin = hider_pa.origin;
    int hider_size = hider_pa.agent->getSize();

    // Check if any other agent has LOS to the hider — if so, can't hide
    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Check line of sight
        if (bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            result.log_message = std::format(
                "{} cannot hide: {} can see them",
                hider_pa.agent->name(), observer_pa.agent->name()
            );
            return result;
        }
    }

    result.valid = true;

    // Roll Stealth check
    result.stealth_d20 = roll(20);
    int stealth_mod = hider_stats.stealthBonus();
    result.stealth_total = result.stealth_d20 + stealth_mod;

    log_("{} attempts to hide (Stealth check): d20={} + {} = {}",
         hider_pa.agent->name(), result.stealth_d20, stealth_mod, result.stealth_total);

    // Contest against agents with LOS to the hider
    bool spotted = false;
    std::string contest_log;

    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Only contest against agents who have LOS to the hider
        // (The first loop already confirmed no one has direct LOS, but checking again for clarity)
        if (!bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            continue;  // Agent can't see hider, skip Perception contest
        }

        const Agent::Stats& observer_stats = observer_pa.agent->getStats();
        int observer_perception = 0;

        if (in_combat) {
            // Active Perception roll
            int perc_d20 = roll(20);
            int perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
            observer_perception = perc_d20 + perc_mod;
            contest_log += std::format(
                "\n  {}: Perception check d20={} + {} = {}",
                observer_pa.agent->name(), perc_d20, perc_mod, observer_perception
            );
        } else {
            // Passive Perception
            observer_perception = observer_stats.passivePerception();
            contest_log += std::format("\n  {}: Passive Perception {}", observer_pa.agent->name(), observer_perception);
        }

        if (observer_perception >= result.stealth_total) {
            spotted = true;
            contest_log += " — SPOTTED";
        } else {
            contest_log += " — doesn't notice";
        }
    }

    if (spotted) {
        result.log_message = std::format(
            "{} failed to hide (Stealth {}){}",
            hider_pa.agent->name(), result.stealth_total, contest_log
        );
    } else {
        applyHidden(bm, agent_idx);
        result.hidden = true;
        result.log_message = std::format(
            "{} successfully hidden (Stealth {}){}",
            hider_pa.agent->name(), result.stealth_total, contest_log
        );
    }

    return result;
}

std::string CombatEngine::checkHiddenAgentDetection(BattleMap& bm, int agent_idx, bool in_combat) noexcept
{
    auto agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) {
        return "";  // Invalid agent
    }

    const PlacedAgent& hider_pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Conditions& hider_cond = hider_pa.agent->getConditions();

    if (!hider_cond.hidden) {
        return "";  // Agent not hidden, no detection check needed
    }

    const Agent::Stats& hider_stats = hider_pa.agent->getStats();
    Cell hider_origin = hider_pa.origin;
    int hider_size = hider_pa.agent->getSize();
    int hider_stealth = hider_stats.stealthBonus();

    // Check each other agent for LOS
    std::string detection_log;
    bool spotted = false;

    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        if (agents[i].agent->getConditions().incapacitated || agents[i].agent->getStats().hp_cur <= 0) continue;

        const PlacedAgent& observer_pa = agents[i];
        Cell observer_origin = observer_pa.origin;
        int observer_size = observer_pa.agent->getSize();

        // Only check agents with LOS to the hidden agent
        if (!bm.hasLineOfSight(hider_origin, hider_size, observer_origin, observer_size)) {
            continue;
        }

        // Agent has LOS, roll Perception to detect
        const Agent::Stats& observer_stats = observer_pa.agent->getStats();
        int observer_perception = 0;
        int perc_d20 = 0;
        int perc_mod = 0;
        bool is_passive = false;

        if (in_combat) {
            // Active Perception roll
            perc_d20 = roll(20);
            perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
            observer_perception = perc_d20 + perc_mod;
        } else {
            // Passive Perception
            is_passive = true;
            observer_perception = observer_stats.passivePerception();
            perc_mod = (observer_stats.wis - 10) / 2 + (observer_stats.perception_prof ? observer_stats.prof_bonus : 0);
        }

        if (observer_perception >= hider_stealth) {
            spotted = true;
            if (is_passive) {
                detection_log += std::format(
                    "\n  {}: Passive Perception {} vs {} Stealth {} — SPOTTED",
                    observer_pa.agent->name(), observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            } else {
                detection_log += std::format(
                    "\n  {}: Perception d20={} + {} = {} vs {} Stealth {} — SPOTTED",
                    observer_pa.agent->name(), perc_d20, perc_mod, observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            }
        } else {
            if (is_passive) {
                detection_log += std::format(
                    "\n  {}: Passive Perception {} vs {} Stealth {} — doesn't notice",
                    observer_pa.agent->name(), observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            } else {
                detection_log += std::format(
                    "\n  {}: Perception d20={} + {} = {} vs {} Stealth {} — doesn't notice",
                    observer_pa.agent->name(), perc_d20, perc_mod, observer_perception,
                    hider_pa.agent->name(), hider_stealth
                );
            }
        }
    }

    if (spotted) {
        // Reveal the hidden agent
        Agent::Conditions cond = bm.getAgentConditions(agent_idx);
        cond.hidden = false;
        bm.setAgentConditions(agent_idx, cond);

        return std::format("{} is no longer hidden{}", hider_pa.agent->name(), detection_log);
    }

    return "";  // Still hidden
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
    int walk_speed = agents[idx].agent->getStats().speed_walk;
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

    log_("{} stands up, spending {} feet of movement", agentName(bm, idx), standup_cost);
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
            }
            log_("Applied condition '{}' to {} for {} turns",
                 cond.condition_name, agentName(bm, cond.agent_idx), cond.turns_remaining);
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
                    } else if (cond.condition_name == "Frightened") {
                        agent_cond.frightened = false;
                    } else if (cond.condition_name == "Unconscious") {
                        agent_cond.unconscious = false;
                        agent_cond.incapacitated = false;
                        // Keep prone=true per 5e rule: "When this condition ends, you remain Prone"
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

void CombatEngine::removeAgentCondition(int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                          [condition_id](const ActiveAgentCondition& c) { return c.condition_id == condition_id; });
    if (it != activeAgentConditions_.end()) {
        activeAgentConditions_.erase(it);
    }
}

void CombatEngine::clearSpellConditionEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();
    if (cond.agent_idx < 0 || cond.agent_idx >= static_cast<int>(agents.size())) return;
    Agent::Conditions ac = bm.getAgentConditions(cond.agent_idx);
    const std::string& n = cond.condition_name;
    if      (n == "Paralyzed")     { ac.paralyzed = false; ac.incapacitated = false; }
    else if (n == "Blinded")       { ac.blinded = false; }
    else if (n == "Incapacitated") { ac.incapacitated = false; }
    else if (n == "Stunned")       { ac.stunned = false; ac.incapacitated = false; }
    else if (n == "Charmed")       { ac.charmed = false; }
    else if (n == "Frightened")    { ac.frightened = false; }
    else if (n == "Unconscious")   { ac.unconscious = false; ac.incapacitated = false; }
    else if (n == "Prone")         { ac.prone = false; }
    bm.setAgentConditions(cond.agent_idx, ac);
}

void CombatEngine::processDamageTaken(BattleMap& bm, int idx, int amount) noexcept
{
    if (amount <= 0) return;  // taking 0 damage is not "taking damage"
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    std::vector<int> to_remove;
    for (const auto& cond : activeAgentConditions_) {
        if (cond.agent_idx != idx) continue;

        if (cond.on_damage == OnDamage_t::End) {
            clearSpellConditionEffect(bm, cond);
            to_remove.push_back(cond.condition_id);
            log_("{} takes damage — {} ends.", agentName(bm, idx), cond.condition_name);
        } else if (cond.on_damage == OnDamage_t::RepeatSave) {
            Agent::Stats s = bm.getAgentStats(idx);
            auto saveMod = [&](SaveAbility_t ab) -> int {
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
            // Damage-triggered save is made at Advantage (Tasha's Hideous Laughter).
            int total = rollAdvantage(20) + saveMod(cond.save_ability);
            if (total >= cond.save_dc) {
                clearSpellConditionEffect(bm, cond);
                to_remove.push_back(cond.condition_id);
                log_("{} shakes off {} after taking damage ({} vs DC {}).",
                     agentName(bm, idx), cond.condition_name, total, cond.save_dc);
            } else {
                log_("{} fails the on-damage save vs {} ({} vs DC {}).",
                     agentName(bm, idx), cond.condition_name, total, cond.save_dc);
            }
        }
    }
    for (int cid : to_remove) removeAgentCondition(cid);
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

std::string CombatEngine::agentName(const BattleMap& bm, int idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return "agent[" + std::to_string(idx) + "]";
    return std::string(agents[idx].agent->name());
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
    const Agent::Stats& viewer_stats = viewer.agent->getStats();

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

        // Check if target is hidden — if so, they're invisible
        if (target.agent->getConditions().hidden) {
            int64_t key = (static_cast<int64_t>(agent_idx) << 32) | static_cast<uint32_t>(target_idx);
            visibilityMap_[key] = VisibilityLevel::Blocked;
            continue;
        }

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
                VisibilityLevel obscuration = bm.getObscurationAtCell(target.origin);

                // Check if viewer can see through magical darkness (devil's sight)
                bool can_see_through_darkness = viewer_stats.devilssight_range > (chebyshev_distance * 5);

                if (obscuration == VisibilityLevel::MagicalDark && !can_see_through_darkness) {
                    visibility = VisibilityLevel::Blocked;
                } else if (obscuration == VisibilityLevel::LightlyObscured) {
                    visibility = VisibilityLevel::LightlyObscured;
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
    int con_mod = (pa.agent->getStats().con - 10) / 2;
    int save_roll = roll(20);
    int save_total = save_roll + con_mod;

    if (save_total >= dc) {
        log_("Concentration save: {} rolled {} + {} = {} vs DC {} — HELD",
             pa.agent->name(), save_roll, con_mod, save_total, dc);
        return false;  // Save succeeded
    }

    log_("Concentration save: {} rolled {} + {} = {} vs DC {} — BROKEN",
         pa.agent->name(), save_roll, con_mod, save_total, dc);

    // Concentration lost — fully drop it (terrain + spell effects + spell-applied conditions + flags).
    (void)dropConcentration(bm, target_idx);
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
    const Agent::Stats& stats = pa.agent->getStats();
    const auto& spells = pa.spells;

    for (size_t i = 0; i < spells.size(); ++i) {
        const Spell& spell = spells[i];

        // Class feature: castable iff its named resource has enough charges.
        if (!spell.resource_name.empty()) {
            const Resource* res = stats.getResource(spell.resource_name);
            if (res && res->current >= std::max(1, spell.resource_cost))
                result.push_back(static_cast<int>(i));
            continue;
        }

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

int CombatEngine::getNumTargetsForSpell(const Spell& sp, int slot_level,
                                        int caster_level) const noexcept
{
    // Eldritch Blast beams scale with CHARACTER level (cantrip), not slot level.
    if (sp.name == "Eldritch Blast" && caster_level >= 0) {
        int beams = 1;
        if (caster_level >= 5)  ++beams;
        if (caster_level >= 11) ++beams;
        if (caster_level >= 17) ++beams;
        return beams;
    }

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
    const Spell& sp = effect.spell;

    // Save-for-half: a damaging zone with a Save attack type lets the target make a
    // saving throw each time the effect is applied (half damage on success).
    const bool do_save = (sp.attack_type == Spell::Save && sp.type != Spell::Heal);
    bool saved = false;
    if (do_save) {
        const Agent& tgt = *agents[static_cast<std::size_t>(target_idx)].agent;
        const Agent::Conditions& tc = tgt.getConditions();

        // Auto-fail STR/DEX saves while paralyzed/stunned/unconscious.
        const bool auto_fail = (tc.paralyzed || tc.stunned || tc.unconscious) &&
                               (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

        bool adv = tgt.hasAdvantage();
        bool dis = tgt.hasDisadvantage();
        // Barbarian Danger Sense (L2+): advantage on DEX saves unless incapacitated.
        if (sp.save_ability == SaveDex && !tc.incapacitated &&
            target_stats.character_class == CharacterClass::Barbarian && target_stats.char_level >= 2)
            adv = true;

        int save_d20;
        if (auto_fail)       save_d20 = 1;
        else if (adv && dis) save_d20 = roll(20);
        else if (adv)        save_d20 = rollAdvantage(20);
        else if (dis)        save_d20 = rollDisadvantage(20);
        else                 save_d20 = roll(20);

        auto saveMod = [&](SaveAbility_t ab) -> int {
            int score = 0; bool prof = false;
            switch (ab) {
                case SaveStr: score = target_stats.str;   prof = target_stats.save_prof_str;   break;
                case SaveDex: score = target_stats.dex;   prof = target_stats.save_prof_dex;   break;
                case SaveCon: score = target_stats.con;   prof = target_stats.save_prof_con;   break;
                case SaveInt: score = target_stats.intel; prof = target_stats.save_prof_intel; break;
                case SaveWis: score = target_stats.wis;   prof = target_stats.save_prof_wis;   break;
                default:      score = target_stats.cha;   prof = target_stats.save_prof_cha;   break;
            }
            int m = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --m;
            return m + (prof ? target_stats.prof_bonus : 0);
        };

        int dc = 0;
        if (effect.caster_idx >= 0 && static_cast<std::size_t>(effect.caster_idx) < agents.size())
            dc = spellSaveDcFromAbility(bm.getAgentStats(effect.caster_idx), sp.save_ability);
        saved = !auto_fail && (save_d20 + saveMod(sp.save_ability) >= dc);
    }

    // Calculate total by rolling all damage types and applying multipliers (then halving on a save).
    int total = 0;
    for (const auto& roll_info : sp.magic_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) type_damage += roll(roll_info.die_size);
        type_damage += roll_info.bonus;
        float multiplier = target_stats.magic_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }
    for (const auto& roll_info : sp.physical_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) type_damage += roll(roll_info.die_size);
        type_damage += roll_info.bonus;
        float multiplier = target_stats.physical_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }

    // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
    if (do_save && sp.save_ability == SaveDex &&
        target_stats.character_class == CharacterClass::Rogue && target_stats.char_level >= 7 &&
        !agents[static_cast<std::size_t>(target_idx)].agent->getConditions().incapacitated) {
        total = saved ? 0 : (total / 2);
    }

    // Log the effect
    const char* verb = (sp.type == Spell::Heal) ? "healed" : "took";
    if (do_save)
        log_("{} {} {} from {} ({} save)", agents[static_cast<std::size_t>(target_idx)].agent->name(),
             verb, total, sp.name, saved ? "made" : "failed");
    else
        log_("{} {} {} from {}", agents[static_cast<std::size_t>(target_idx)].agent->name(), verb, total, sp.name);

    // Apply damage or healing
    if (sp.type == Spell::Heal) {
        healAgent(bm, target_idx, total);
    } else {
        damageAgent(bm, target_idx, total);
        processDamageTaken(bm, target_idx, total);  // zone damage ends/triggers on-damage conditions
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

// ── Resource Initialization by Class and Level ──────────────────────────────
void Agent::Stats::initializeClassResources(CharacterClass cls, int level) {
  resources.clear();

  switch (cls) {
    case Barbarian: {
      // Rage: uses per day scales with level
      // Level 1-2: 2 uses, Level 3-4: 3 uses, Level 5-6: 3 uses, Level 7-8: 4 uses,
      // Level 9-10: 4 uses, Level 11-12: 4 uses, Level 13-14: 5 uses, Level 15-16: 5 uses,
      // Level 17-18: 6 uses, Level 19-20: 6 uses (but 20 is unlimited)
      int rage_uses = 2;
      if (level >= 3) rage_uses = 3;
      if (level >= 5) rage_uses = 3;
      if (level >= 7) rage_uses = 4;
      if (level >= 9) rage_uses = 4;
      if (level >= 11) rage_uses = 4;
      if (level >= 13) rage_uses = 5;
      if (level >= 15) rage_uses = 5;
      if (level >= 17) rage_uses = 6;

      Resource rage("Rage", rage_uses, 10);  // 10-turn duration (~1 minute)
      rage.short_rest_regen = 1;  // regain 1 use on short rest
      rage.long_rest_regen = rage_uses;
      resources["Rage"] = rage;

      // Extra Attack (L5+): gain second weapon attack per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Fast Movement (L5+): +10 feet speed (not in heavy armor, but we can't check that here)
      if (level >= 5) {
        speed_walk += 10;
      }

      // Brutal Strike (L9+): 1d10 damage; L17+: 2d10 damage
      if (level >= 9) {
        brutal_strike_damage_dice = 1;
      }
      if (level >= 17) {
        brutal_strike_damage_dice = 2;
      }
      break;
    }

    case Monk: {
      // Chassis: Dexterity + Wisdom save proficiencies
      save_prof_dex = true;
      save_prof_wis = true;

      // Ki: number of ki points = character level
      Resource ki("Ki", level, 0);  // no duration
      ki.short_rest_regen = level;  // fully restored on short rest
      ki.long_rest_regen = level;
      resources["Ki"] = ki;

      // Extra Attack (L5+): 2 attacks per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Unarmored Defense (L1+): AC = 10 + DEX + WIS (note: not implemented yet, see known_limitations.md)
      // This would need special AC calculation logic in combat.cpp
      break;
    }

    case Rogue: {
      // Chassis: Dexterity + Intelligence saving-throw proficiencies.
      save_prof_dex = true;
      save_prof_intel = true;
      // Cunning Action (L2+): Dash/Disengage/Hide as a bonus action.
      if (level >= 2) has_cunning_action = true;
      // Slippery Mind (L15+): proficiency in Wisdom and Charisma saves.
      if (level >= 15) {
        save_prof_wis = true;
        save_prof_cha = true;
      }
      break;
    }

    case Sorcerer: {
      // Sorcery Points: equal to sorcerer level
      Resource sp("Sorcery Points", level, 0);
      sp.short_rest_regen = 0;
      sp.long_rest_regen = level;
      resources["Sorcery Points"] = sp;
      break;
    }

    case Fighter: {
      // Extra Attack (L5+): 2 at L5, 3 at L11, 4 at L20
      if (level >= 20) {
        num_attacks = 4;
      } else if (level >= 11) {
        num_attacks = 3;
      } else if (level >= 5) {
        num_attacks = 2;
      }

      // Second Wind (L1+): 1d10 + level, regains on short/long rest
      int sw_uses = 1;
      Resource sw("Second Wind", sw_uses, 0);
      sw.short_rest_regen = 1;
      sw.long_rest_regen = 1;
      resources["Second Wind"] = sw;

      // Action Surge (L1+): 1 use at L1, 2 at L17, regains on long rest
      int as_uses = (level >= 17) ? 2 : 1;
      Resource as("Action Surge", as_uses, 0);
      as.long_rest_regen = as_uses;
      resources["Action Surge"] = as;

      // Weapon Mastery (L1+): activate the mastery system
      weapon_mastery = 1;

      // Champion: lower crit threshold
      if (fighter_subclass == ChampionPath) {
        if (level >= 15) {
          crit_threshold = 18;  // L15: critical on 18-20
        } else if (level >= 3) {
          crit_threshold = 19;  // L3: critical on 19-20
        }
      }
      break;
    }

    case Druid: {
      // Druid: WIS full caster (like Cleric)
      spellcasting_ability = 4;  // 4 = WIS (SaveAbility_t::SaveWis)
      can_cast_spell = true;
      save_prof_intel = true;
      save_prof_wis = true;

      // Wild Shape (L2+): uses scale with level
      // L2-4: 2 uses, L5-6: 3 uses, L7-8: 4 uses, L9+: 4 uses
      int ws_uses = 0;
      if (level >= 2) ws_uses = 2;
      if (level >= 5) ws_uses = 3;
      if (level >= 7) ws_uses = 4;
      // Note: Wild Shape can be used unlimited times at L20, but that's handled separately

      Resource ws("Wild Shape", ws_uses, 0);
      ws.short_rest_regen = 1;  // regain one use on short rest
      ws.long_rest_regen = ws_uses;  // full on long rest
      resources["Wild Shape"] = ws;
      break;
    }

    case Cleric: {
      // Channel Divinity (2024): 2 uses at L2, 3 at L6, 4 at L18 (none before L2).
      // Regain one use on a Short Rest, all on a Long Rest.
      int cd_uses = (level >= 18) ? 4 : (level >= 6) ? 3 : (level >= 2) ? 2 : 0;
      Resource cd("Channel Divinity", cd_uses, 0);
      cd.short_rest_regen = 1;       // regain one use on a short rest
      cd.long_rest_regen = cd_uses;  // full on a long rest
      resources["Channel Divinity"] = cd;

      // War Domain — War Priest (L3+): WIS-mod (min 1) bonus-action weapon attacks per Short/Long Rest.
      if (cleric_subclass == WarDomain && level >= 3) {
        int wp = std::max(1, _mod(wis));
        Resource war_priest("War Priest", wp, 0);
        war_priest.short_rest_regen = wp;  // regained on a Short or Long Rest
        war_priest.long_rest_regen = wp;
        resources["War Priest"] = war_priest;
      }
      break;
    }

    case Wizard: {
      // Arcane Recovery: recover spell levels = ceil(level / 2) once per long rest
      // Full mechanic deferred; for now just track the resource exists
      Resource ar("Arcane Recovery", 1, 0);  // 1 use per long rest
      ar.long_rest_regen = 1;
      resources["Arcane Recovery"] = ar;

      // Memorize Spell (L5+): swap 1 prepared spell after short rest
      if (level >= 5) {
        Resource ms("Memorize Spell", 1, 0);  // 1 use per short rest
        ms.short_rest_regen = 1;
        ms.long_rest_regen = 1;  // Also restored on long rest
        resources["Memorize Spell"] = ms;
      }

      // Portent Dice (L3+): Diviner only, but we create the resource for all Wizards
      // It will only be usable if wizard_subclass == Diviner
      if (level >= 3) {
        int portent_max = 2;
        if (level >= 14) portent_max = 3;
        Resource pd("Portent Dice", portent_max, 0);  // Uses per long rest
        pd.long_rest_regen = portent_max;
        resources["Portent Dice"] = pd;
        // Note: portent_dice deque will be populated on long rest or first use
      }

      // Spellcasting ability is INT for Wizards
      spellcasting_ability = 3;  // 3 = INT (SaveAbility_t::SaveInt)

      // Cantrips known: 3 at L1, +1 at L4 and L10
      // This is tracked separately in the spell system; just mark can_cast_spell
      can_cast_spell = true;

      break;
    }

    case Warlock: {
      // Pact Magic: Charisma caster. Pact slots come from kPact (set by set_class_level);
      // they all share one level and recharge on a SHORT or long rest.
      spellcasting_ability = 5;  // 5 = CHA
      can_cast_spell = true;
      save_prof_wis = true;      // Warlock saving-throw proficiencies: WIS and CHA
      save_prof_cha = true;
      spell_slots_remaining = spell_slots_max;  // start with pact slots full

      // Magical Cunning (L2+): once per long rest, recover expended pact slots up to
      // ceil(max/2) — or all of them at L20 (Eldritch Master). See useMagicalCunning.
      if (level >= 2) {
        Resource mc("Magical Cunning", 1, 1);  // 1 use, available now, restored on long rest
        mc.long_rest_regen = 1;
        resources["Magical Cunning"] = mc;
      }

      // Subclass-specific features
      if (warlock_subclass == FiendPath && level >= 10 && fiendish_resilience_type >= 0) {
        set_magic_damage_multiplier(fiendish_resilience_type, 0.5f);
      }
      if (warlock_subclass == CelestialPath && level >= 6) {
        set_magic_damage_multiplier(8 /* Radiant */, 0.5f);
      }
      if (warlock_subclass == GreatOldOnePath && level >= 10) {
        set_magic_damage_multiplier(7 /* Psychic */, 0.5f);
      }

      // Healing Light (Celestial L3): pool of d6 healing
      if (warlock_subclass == CelestialPath && level >= 3) {
        Resource hl("Healing Light", 1 + level, 1 + level);
        hl.long_rest_regen = 1 + level;
        resources["Healing Light"] = hl;
      }
      break;
    }

    case Paladin: {
      // Paladin: CHA half-caster (spell slots already set via set_class_level using kHalf column)
      spellcasting_ability = 5;  // 5 = CHA (SaveAbility_t::SaveCha)
      can_cast_spell = true;
      save_prof_wis = true;

      // Extra Attack (L5+): 2 attacks per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Channel Oath (L1+): 2 uses at L1, 3 at L6, 4 at L18 (like Channel Divinity)
      int co_uses = (level >= 18) ? 4 : (level >= 6) ? 3 : 2;
      Resource co("Channel Oath", co_uses, 0);
      co.short_rest_regen = 1;       // regain one use on a short rest
      co.long_rest_regen = co_uses;  // full on a long rest
      resources["Channel Oath"] = co;

      // Lay on Hands (L1+): pool of 5 × level HP to heal
      Resource loh("Lay on Hands", 5 * level, 5 * level);
      loh.long_rest_regen = 5 * level;
      resources["Lay on Hands"] = loh;
      break;
    }

    // Other classes without resources (Rogue, Ranger, Bard)
    // have no custom resources
    default:
      break;
  }
}

} // namespace rpg
