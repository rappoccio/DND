// ─────────────────────────────────────────────────────────────────────────────
//  combat_core.cpp  –  CombatEngine dice, modifiers, AC, spell DCs, RL interface
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · Dice & RNG    — construction, reseed, roll, rollAdvantage, rollDisadvantage
//    · Modifiers     — attackModifier, damageAbilityMod, spellAttackMod,
//                      spellSaveDc, spellSaveDcFromAbility
//    · Armor Class   — calculateAC, applyArmorMultipliers, canEquipArmor
//    · RL interface  — getBattleObservation, availableAttacks
//    · Misc          — agentName
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <algorithm>
#include <cassert>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Dice & RNG
//
//  roll/rollAdvantage/rollDisadvantage/attackModifier/damageAbilityMod/spellAttackMod/
//  spellSaveDc(FromAbility)/calculateAC/isHoldingShield/canEquipArmor/the Paladin+advantage
//  aura queries/saveModFor/saveAdvantageFor now live in rules.hpp as free functions
//  (COMBAT_REFACTOR_PLAN.md R3) — these are one-line forwarders so every existing call
//  site (both C++ and the pybind11 bindings) keeps working unchanged.
// ─────────────────────────────────────────────────────────────────────────────

CombatEngine::CombatEngine(uint32_t seed)
{
    reseed(seed == 0 ? std::random_device{}() : seed);
}

void CombatEngine::reseed(uint32_t seed)
{
    ctx_.rng_.seed(seed);
}

int CombatEngine::roll(int sides, int modifier)
{
    return rules::roll(ctx_, sides, modifier);
}

int CombatEngine::rollAdvantage(int sides, int modifier)
{
    return rules::rollAdvantage(ctx_, sides, modifier);
}

int CombatEngine::rollDisadvantage(int sides, int modifier)
{
    return rules::rollDisadvantage(ctx_, sides, modifier);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Modifiers
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::attackModifier(const Weapon& w,
                                  const Agent::Stats& s) noexcept
{
    return rules::attackModifier(w, s);
}

int CombatEngine::damageAbilityMod(const Weapon& w,
                                    const Agent::Stats& s) noexcept
{
    return rules::damageAbilityMod(w, s);
}

int CombatEngine::spellAttackMod(const Agent::Stats& s) noexcept
{
    return rules::spellAttackMod(s);
}

int CombatEngine::spellSaveDc(const Agent::Stats& s) noexcept
{
    return rules::spellSaveDc(s);
}

int CombatEngine::spellSaveDcFromAbility(const Agent::Stats& s, SaveAbility_t ability) noexcept
{
    return rules::spellSaveDcFromAbility(s, ability);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Paladin auras (team-scoped emanations)
// ─────────────────────────────────────────────────────────────────────────────

// dndMod (floor-rounding ability modifier) now lives in combat_internal.hpp so every
// translation unit shares one correct implementation. See note there.

int CombatEngine::bestPaladinAura(const BattleMap& bm, int agent_idx, int min_level,
                                  PaladinOath require_oath) const noexcept
{
    return rules::bestPaladinAura(bm, agent_idx, min_level, require_oath);
}

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

bool CombatEngine::hasAdvantageAura(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::hasAdvantageAura(bm, agent_idx);
}

// Not const: a blessed creature adds a fresh 1d4 to each save (roll() mutates ctx_.rng_). Every
// call site is a live save resolution in a non-const method, so dropping const is clean —
// preferable to a mutable rng_ that would hide a die roll inside a const method.
int CombatEngine::saveModFor(const BattleMap& bm, int agent_idx, SaveAbility_t ab) noexcept
{
    return rules::saveModFor(bm, ctx_, agent_idx, ab);
}

int CombatEngine::applyIndomitableMight(const BattleMap& bm, int saver_idx, SaveAbility_t ab, int total) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (saver_idx < 0 || static_cast<std::size_t>(saver_idx) >= agents.size()) return total;
    const Agent::Stats& s = agents[static_cast<std::size_t>(saver_idx)].agent->getStats();

    // Indomitable Might (Barbarian L18): STR saving throw total can't be lower than STR score
    if (ab == SaveStr && s.hasClass(CharacterClass::Barbarian) && s.classLevel(CharacterClass::Barbarian) >= 18) {
        return std::max(total, s.str);
    }
    return total;
}

bool CombatEngine::curseSaveDisadvantage(const BattleMap& bm, int agent_idx, SaveAbility_t ab) const noexcept
{
    (void)bm;
    if (agent_idx < 0) return false;
    for (const ActiveAgentCondition& c : activeAgentConditions_) {
        if (c.agent_idx == agent_idx && c.curse_disadv_ability == static_cast<int>(ab))
            return true;
    }
    return false;
}

// Ability-scoped save Advantage (Phase 0.3) — the symmetric counterpart to
// curseSaveDisadvantage. Data-driven off Stats::save_advantage_mask so any
// "Advantage on X saves" buff (Haste's DEX save, future effects) is honored
// at every save site without a per-feature branch.
bool CombatEngine::saveAdvantageFor(const BattleMap& bm, int agent_idx, SaveAbility_t ab) const noexcept
{
    return rules::saveAdvantageFor(bm, agent_idx, ab);
}

// NPC turn playback: record an Outcome event (flash text + animation-synced HP/death state).
// Declared in combat.hpp next to the other recorders; lives here because it needs the full
// BattleMap definition (the header only forward-declares it). No-op unless an automated NPC
// turn is recording (npc_recording_).
void CombatEngine::recordNpcOutcome(const BattleMap& bm, int target_idx, std::string text,
                                    bool good, bool sync_hp)
{
    if (!ctx_.npc_recording_) return;
    NpcVisualEvent e;
    e.kind = NpcVisualEvent::Outcome;
    e.agent_idx = target_idx;
    e.text = std::move(text);
    e.good = good;
    const int n = static_cast<int>(bm.placedAgents().size());
    if (sync_hp && target_idx >= 0 && target_idx < n) {
        e.hp_after = bm.getAgentStats(target_idx).hp_cur;
        // died gates the GUI's deferred corpse removal: NPC corpses clear via conditions.dead
        // (PCs at 0 HP stay drawn — they roll death saves), mirroring _draw_agents' rules.
        e.died = bm.getAgentConditions(target_idx).dead ||
                 bm.placedAgents()[static_cast<std::size_t>(target_idx)].removed_from_play;
    }
    ctx_.npc_visual_events_.push_back(std::move(e));
}

// ─────────────────────────────────────────────────────────────────────────────
//  Armor Class
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::calculateAC(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::calculateAC(bm, agent_idx);
}

bool CombatEngine::isHoldingShield(const BattleMap& bm, int agent_idx) const noexcept
{
    return rules::isHoldingShield(bm, agent_idx);
}

bool CombatEngine::canShieldBash(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return false;
    if (!bm.getAgentStats(agent_idx).hasFeat("Shield Master")) return false;
    if (!isHoldingShield(bm, agent_idx)) return false;
    return hasBonusAction(bm, agent_idx);
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
    if (s.hasClass(CharacterClass::Cleric) && s.cleric_subclass == WarDomain && s.classLevel(CharacterClass::Cleric) >= 17) {
        for (auto t : {PhysicalDamage_t::Bludgeoning, PhysicalDamage_t::Piercing, PhysicalDamage_t::Slashing}) {
            float& cur = s.physical_damage_multipliers[static_cast<std::size_t>(t)];
            if (cur > 0.5f && cur != 2.0f) cur = 0.5f;  // resist, but don't override vuln/immunity
        }
    }

    bm.setAgentStats(agent_idx, s);
}

bool CombatEngine::canEquipArmor(const BattleMap& bm, int agent_idx, const Armor& armor) const noexcept
{
    return rules::canEquipArmor(bm, agent_idx, armor);
}

// ─────────────────────────────────────────────────────────────────────────────
//  RL interface
// ─────────────────────────────────────────────────────────────────────────────

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
                                          tgt.origin, tgt_sz)
                       && canPerceiveTarget(bm, attacker_idx, ti);

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

    Agent::Stats stats = bm.getAgentStats(attacker_idx);
    log_("[AVAILABLE_ATTACKS] Agent {} has {} weapons, has_offhand_attack={}", attacker_idx, atk.weapons.size(), stats.has_offhand_attack);
    for (std::size_t i = 0; i < atk.weapons.size(); ++i) {
        log_("[AVAILABLE_ATTACKS] Weapon {}: '{}' off_hand={}", i, atk.weapons[i].name, atk.weapons[i].off_hand);
    }

    for (int ti = 0; ti < n; ++ti) {
        if (ti == attacker_idx) continue;
        const PlacedAgent& tgt = agents[static_cast<std::size_t>(ti)];
        int tgt_sz = tgt.agent->getSize();

        for (int wi = 0; wi < static_cast<int>(atk.weapons.size()); ++wi) {
            const Weapon& w = atk.weapons[static_cast<std::size_t>(wi)];
            if (canAttack(w, bm, atk.origin, atk_sz, tgt.origin, tgt_sz)
                    && canPerceiveTarget(bm, attacker_idx, ti)
                    && !forcecageSeparates(bm, attacker_idx, ti)) {   // no attack crosses a Forcecage Box wall
                log_("[AVAILABLE_ATTACKS] Can attack with weapon {}: '{}'", wi, w.name);
                result.push_back({attacker_idx, ti, wi});
            }
        }
    }
    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Misc
// ─────────────────────────────────────────────────────────────────────────────

std::string CombatEngine::agentName(const BattleMap& bm, int idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return "agent[" + std::to_string(idx) + "]";
    return std::string(agents[idx].agent->name());
}

} // namespace rpg
