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

#include <algorithm>
#include <cassert>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Dice & RNG
// ─────────────────────────────────────────────────────────────────────────────

CombatEngine::CombatEngine(uint32_t seed)
{
    reseed(seed == 0 ? std::random_device{}() : seed);
}

void CombatEngine::reseed(uint32_t seed)
{
    rng_.seed(seed);
}

int CombatEngine::roll(int sides, int modifier)
{
    assert(sides >= 2 && "Die must have at least 2 sides");
    // One-shot advantage/disadvantage applies only to d20 Tests (damage dice ignore it).
    const int adv = (sides == 20) ? consumePendingAdvantage() : 0;

    // Portent Dice: if pending, return it instead of rolling (and clear)
    if (pending_portent_die_ >= 0) {
        int result = pending_portent_die_;
        pending_portent_die_ = -1;
        return result + modifier + consumePendingRollBonus();
    }

    std::uniform_int_distribution<int> d{1, sides};
    int die;
    if (adv > 0)      die = std::max(d(rng_), d(rng_));   // advantage
    else if (adv < 0) die = std::min(d(rng_), d(rng_));   // disadvantage
    else              die = d(rng_);
    return die + modifier + consumePendingRollBonus();
}

int CombatEngine::rollAdvantage(int sides, int modifier)
{
    // Check if portent die is pending (need to apply after advantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }
    // Capture the Bardic bonus before the inner rolls so they don't consume it
    // mid-selection; it is added once after max().
    int roll_bonus = consumePendingRollBonus();
    // Consume any pending one-shot advantage/disadvantage up front so the inner roll()s don't
    // re-trigger it. A pending disadvantage cancels this explicit advantage (roll straight).
    const int pa = (sides == 20) ? consumePendingAdvantage() : 0;

    int result = (pa < 0) ? roll(sides) : std::max(roll(sides), roll(sides));

    // Apply portent die if one was pending (after advantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", result, pending_portent);
        result = pending_portent;
    }

    // Flat modifier + Bardic bonus added once, after die selection / portent replacement.
    return result + modifier + roll_bonus;
}

int CombatEngine::rollDisadvantage(int sides, int modifier)
{
    // Check if portent die is pending (need to apply after disadvantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }
    // Capture the Bardic bonus before the inner rolls so they don't consume it
    // mid-selection; it is added once after min().
    int roll_bonus = consumePendingRollBonus();
    // Consume any pending one-shot advantage/disadvantage up front. A pending advantage
    // cancels this explicit disadvantage (roll straight).
    const int pa = (sides == 20) ? consumePendingAdvantage() : 0;

    int result = (pa > 0) ? roll(sides) : std::min(roll(sides), roll(sides));

    // Apply portent die if one was pending (after disadvantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", result, pending_portent);
        result = pending_portent;
    }

    // Flat modifier + Bardic bonus added once, after die selection / portent replacement.
    return result + modifier + roll_bonus;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Modifiers
// ─────────────────────────────────────────────────────────────────────────────

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
    // Sorcerer Innate Sorcery: +1 to spell save DC while active.
    int innate = (s.innate_sorcery_turns > 0) ? 1 : 0;
    return 8 + spellAttackMod(s) + innate;
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
    // Sorcerer Innate Sorcery: +1 to spell save DC while active.
    int innate = (s.innate_sorcery_turns > 0) ? 1 : 0;
    return 8 + s.prof_bonus + m + innate;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Armor Class
// ─────────────────────────────────────────────────────────────────────────────

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

    // Monk Unarmored Defense: AC = 10 + DEX + WIS (no armor worn)
    if (pa.agent->getStats().character_class == CharacterClass::Monk && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int wis_mod = (pa.agent->getStats().wis - 10) / 2;
        int ac = 10 + dex_mod + wis_mod;

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

    // College of Dance Bard (L3+) Unarmored Defense: AC = 10 + DEX + CHA (no armor worn)
    if (pa.agent->getStats().character_class == CharacterClass::Bard &&
        pa.agent->getStats().bard_subclass == BardCollege::DancePath &&
        pa.agent->getStats().char_level >= 3 && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int cha_mod = (pa.agent->getStats().cha - 10) / 2;
        int ac = 10 + dex_mod + cha_mod;

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

    // Draconic Sorcerer (L3+) Draconic Resilience: AC = 10 + DEX + CHA (no armor worn)
    if (pa.agent->getStats().character_class == CharacterClass::Sorcerer &&
        pa.agent->getStats().sorcerer_subclass == SorcererSubclass::DraconicPath &&
        pa.agent->getStats().char_level >= 3 && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int cha_mod = (pa.agent->getStats().cha - 10) / 2;
        int ac = 10 + dex_mod + cha_mod;

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

    // Standard AC calculation (non-Barbarian/Monk or wearing armor)
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
            if (canAttack(w, bm, atk.origin, atk_sz, tgt.origin, tgt_sz)) {
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
