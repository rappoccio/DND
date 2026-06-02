// ─────────────────────────────────────────────────────────────────────────────
//  combat_state.cpp  –  CombatEngine agent config + stat/equipment accessors
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Thin accessors that delegate to BattleMap, plus the per-agent turn counter.
//  Sections:
//    · Agent config              — addAgentConfig, applyAgentConfigs
//    · Stats accessors           — getAgentStats, setAgentStats
//    · Conditions accessors      — getAgentConditions, setAgentConditions
//    · Weapon/Armor/Spell access — get/set Weapons/Armor/Spells, add/removeSpell
//    · Turn counters             — getAgentTurns, setAgentTurns, clearAgentTurns
//    · NPC spell groups          — initNpcSpellGroups
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <array>
#include <map>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Agent config
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::addAgentConfig(BattleMap& bm, AgentConfig cfg) noexcept
{
    bm.addAgentConfig(cfg);
}

void CombatEngine::applyAgentConfigs(BattleMap& bm) noexcept
{
    bm.applyAgentConfigs();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Stats accessors
// ─────────────────────────────────────────────────────────────────────────────

Agent::Stats CombatEngine::getAgentStats(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentStats(idx);
}

void CombatEngine::setAgentStats(BattleMap& bm, int idx, Agent::Stats s) noexcept
{
    bm.setAgentStats(idx, s);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Conditions accessors
// ─────────────────────────────────────────────────────────────────────────────

Agent::Conditions CombatEngine::getAgentConditions(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentConditions(idx);
}

void CombatEngine::setAgentConditions(BattleMap& bm, int idx, const Agent::Conditions& c) noexcept
{
    bm.setAgentConditions(idx, c);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Weapon / Armor / Spell accessors
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
//  Turn counters
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
//  NPC spell groups
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::initNpcSpellGroups(BattleMap& bm, int agent_idx,
                                      const std::map<int, std::vector<std::string>>& groups) noexcept
{
    bm.initNpcSpellGroups(agent_idx, groups);
}

} // namespace rpg
