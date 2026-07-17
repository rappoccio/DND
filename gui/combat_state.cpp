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
    // Materialize invocation-derived passive vision so every read site (combat_visibility,
    // the blinded-in-darkness check, the GUI) sees it without each re-deriving the rules.
    // Idempotent (only ever raises the field), so internal bm.setAgentStats round-trips
    // preserve it.
    if (s.character_class == CharacterClass::Warlock) {
        // Devil's Sight (code 4): see normally in dim light & darkness within 120 ft.
        if (s.hasInvocation(4) && s.devilssight_range < 120)
            s.devilssight_range = 120;
        // Witch Sight (code 7): Truesight 30 ft (the engine's superset of "blindsight" —
        // see invisible/through-darkness within range).
        if (s.hasInvocation(7) && s.truesight_range < 30)
            s.truesight_range = 30;
        // Gift of the Depths (code 11): a Swim Speed equal to the Warlock's Speed.
        if (s.hasInvocation(11) && s.speed_swim < s.speed_walk)
            s.speed_swim = s.speed_walk;
    }
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

std::vector<Weapon> CombatEngine::getAgentWeapons(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentWeapons(idx);
}

void CombatEngine::setAgentWeapons(BattleMap& bm, int idx, std::vector<Weapon> weapons) noexcept
{
    bm.setAgentWeapons(idx, std::move(weapons));
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

bool CombatEngine::spendSpellSlot(BattleMap& bm, int idx, int level) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    if (level < 1 || level > 9) return false;
    PlacedAgent& pa = bm.placedAgentMut(idx);
    Agent::Stats& stats = pa.agent->getStats();
    if (stats.is_npc) return false;   // NPCs use the N/day system, not slots
    auto& slots = stats.spell_slots_remaining;
    const std::size_t li = static_cast<std::size_t>(level - 1);
    if (slots[li] <= 0) return false;
    slots[li] -= 1;
    return true;
}

std::vector<Item> CombatEngine::getAgentItems(const BattleMap& bm, int idx) const noexcept
{
    return bm.getAgentItems(idx);
}

void CombatEngine::setAgentItems(BattleMap& bm, int idx, std::vector<Item> items) noexcept
{
    bm.setAgentItems(idx, items);
}

void CombatEngine::addItemToAgent(BattleMap& bm, int idx, Item it) noexcept
{
    bm.addItemToAgent(idx, it);
}

void CombatEngine::removeItemFromAgent(BattleMap& bm, int idx, int item_idx) noexcept
{
    bm.removeItemFromAgent(idx, item_idx);
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
