// ─────────────────────────────────────────────────────────────────────────────
//  combat_barbarian.cpp  –  CombatEngine Barbarian features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Berserker, World Tree, Zealot.
//  Contents: Rage, Brutal Strike, Reckless Attack reroll, Intimidating / Zealous Presence,
//  Rage of the Gods, Primal Knowledge, Retaliation, World Tree's Branches and Vitality of
//  the Tree and Travel Along the Tree.
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

// ─────────────────────────────────────────────────────────────────────────────
//  OnTurnStartNearby reactions (beginTurn)
//  When a creature starts its turn within a reactor's 5 ft reach, the reactor may spend its reaction:
//  Branches of the Tree → the creature makes a STR save vs the reactor's spell save DC or is Grappled.
//  A post-effect interrupt that does not alter the TurnStartResult, so the flow is the simplest of the
//  seven windows (no pre-roll / re-evaluation). The apply rolls directly → no nested window opens.
//  (Sentinel is NOT here — RAW it provokes an OA when a creature Disengages out of reach; that lives in
//  detectProvokes' LeftReach path, gated on Agent::Stats::has_sentinel.)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canBranchesOfTree(const BattleMap& bm, int reactor, int source) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n || source < 0 || source >= n || reactor == source) return false;
    if (bm.isAgentOnDeck(reactor)) return false;          // On Deck reserves take no reactions until deployed
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (!s.has_branches_of_the_tree) return false;
    if (s.hp_cur <= 0) return false;
    const Agent::Conditions c = bm.getAgentConditions(reactor);
    if (!canTakeReaction(c)) return false;
    if (!c.raging) return false;                                 // "While your Rage is active"
    if (!canPerceiveTarget(bm, reactor, source)) return false;   // "a creature you can see"
    // "starts its turn within 30 feet of you" — 30 ft = 6 cells (Chebyshev footprint distance).
    const auto in_range = threateningAgents(bm, source, 6);
    return std::find(in_range.begin(), in_range.end(), reactor) != in_range.end();
}

bool CombatEngine::applyBranchesOfTree(BattleMap& bm, int reactor, int source)
{
    if (!canBranchesOfTree(bm, reactor, source)) return false;
    Agent::Conditions rc = bm.getAgentConditions(reactor);
    rc.reaction_used = true;                                          // spend the reaction
    bm.setAgentConditions(reactor, rc);

    // An ally is a willing target: no STR save, and no Speed-0 penalty — Branches is used purely to
    // reposition them. Only an enemy must save, and only an enemy suffers Speed 0 on a failed save.
    const bool ally = areAllies(bm, reactor, source);
    if (!ally) {
        const Agent::Stats rs = bm.getAgentStats(reactor);
        const int dc       = rules::spellSaveDcFromAbility(rs, SaveStr);   // 8 + PB + STR mod (2024 PHB)
        const int save_mod = saveModFor(bm, source, SaveStr);      // incl. Aura of Protection
        const int d20      = roll(20);
        const int total    = d20 + save_mod;
        log_("{} uses Branches of the Tree on {} (reaction): STR save {} {:+} = {} vs DC {}",
             agentName(bm, reactor), agentName(bm, source), d20, save_mod, total, dc);
        if (total >= dc) {
            log_("{} resists the branches", agentName(bm, source));
            return false;
        }
    } else {
        log_("{} uses Branches of the Tree to reposition ally {} (willing — no save)",
             agentName(bm, reactor), agentName(bm, source));
    }

    // Teleport the source to an unoccupied space within 5 ft of the reactor (or, failing that, the
    // nearest unoccupied space). An enemy that failed its save also has its Speed set to 0 until the
    // end of the current turn (an ally keeps its movement).
    const auto& agents = bm.placedAgents();
    const Cell rorigin = agents[static_cast<std::size_t>(reactor)].origin;
    const int  rsize   = agents[static_cast<std::size_t>(reactor)].agent->getSize();
    const int  ssize   = agents[static_cast<std::size_t>(source)].agent->getSize();

    // Does an origin fit the source's whole footprint on passable, unoccupied terrain?
    auto fitsFree = [&](Cell o) -> bool {
        for (int dc2 = 0; dc2 < ssize; ++dc2)
            for (int dr2 = 0; dr2 < ssize; ++dr2)
                if (!isValidTeleportDestination(bm, o.col + dc2, o.row + dr2))
                    return false;
        for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
            if (i == source) continue;
            if (agents[static_cast<std::size_t>(i)].agent->getStats().hp_cur <= 0) continue;
            const Cell oo = agents[static_cast<std::size_t>(i)].origin;
            const int  os = agents[static_cast<std::size_t>(i)].agent->getSize();
            const bool overlap = !(o.col + ssize - 1 < oo.col || oo.col + os - 1 < o.col ||
                                   o.row + ssize - 1 < oo.row || oo.row + os - 1 < o.row);
            if (overlap) return false;
        }
        return true;
    };
    // Chebyshev gap (in cells) between the source footprint placed at `o` and the reactor footprint.
    auto chebFoot = [&](Cell o) -> int {
        const int dx = std::max({rorigin.col - (o.col + ssize - 1), o.col - (rorigin.col + rsize - 1), 0});
        const int dy = std::max({rorigin.row - (o.row + ssize - 1), o.row - (rorigin.row + rsize - 1), 0});
        return std::max(dx, dy);
    };

    // Scan a bounded box around the reactor; pick the nearest fitting free origin (prefers ≤5 ft).
    constexpr int kReach = 8;
    Cell dest{-1, -1};
    int best_d = 1 << 30;
    for (int c = rorigin.col - rsize - kReach; c <= rorigin.col + rsize + kReach; ++c) {
        for (int r = rorigin.row - rsize - kReach; r <= rorigin.row + rsize + kReach; ++r) {
            const Cell cand{c, r};
            if (!fitsFree(cand)) continue;
            const int d = chebFoot(cand);
            if (d < best_d) { best_d = d; dest = cand; }
        }
    }

    if (dest.col >= 0) {
        (void)teleportAgent(bm, source, dest.col, dest.row);
        log_("{} is yanked by the branches to ({}, {})", agentName(bm, source), dest.col, dest.row);
    } else {
        log_("{} has no space to be teleported by the branches", agentName(bm, source));
    }

    // Speed 0 until the end of the current turn (enemies only — an ally keeps moving). The GUI gate is
    // canAgentMove(branches_speed_zeroed); also zero the engine + agent budgets so the auto/RL path
    // (no per-turn re-seed) honors it now.
    if (!ally) {
        Agent::Conditions sc = bm.getAgentConditions(source);
        sc.branches_speed_zeroed = true;
        bm.setAgentConditions(source, sc);
        mv_.seedMoveBudgets(source, 0, 0, 0, 0);
        agents[static_cast<std::size_t>(source)].agent->initMovement(0, 0, 0, 0);
        log_("{}'s Speed is reduced to 0 until the end of its turn", agentName(bm, source));
    }
    return true;
}

// Unlike Branches (a reaction to another creature's turn), this fires on the source's OWN turn, so the
// window offers the source itself this option. It is free (not the reaction) but once per turn.
bool CombatEngine::canVitalityOfTheTree(const BattleMap& bm, int source) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (source < 0 || source >= n) return false;
    if (bm.isAgentOnDeck(source)) return false;           // On Deck reserves take no reactions until deployed
    const Agent::Stats s = bm.getAgentStats(source);
    if (s.lacksClass(Barbarian) || s.barbarian_subclass != WorldTreePath) return false;
    if (s.classLevel(CharacterClass::Barbarian) < 3 || s.hp_cur <= 0) return false;
    const Agent::Conditions c = bm.getAgentConditions(source);
    if (!c.raging || c.vitality_used_this_turn || c.incapacitated) return false;
    // At least one other living creature within 10 ft (2 cells) to receive the temp HP.
    return !threateningAgents(bm, source, 2).empty();
}

bool CombatEngine::applyVitalityOfTheTree(BattleMap& bm, int source, int target)
{
    if (!canVitalityOfTheTree(bm, source)) return false;
    const auto in_range = threateningAgents(bm, source, 2);
    if (std::find(in_range.begin(), in_range.end(), target) == in_range.end()) return false;  // target not within 10 ft

    const Agent::Stats ss = bm.getAgentStats(source);
    const int dice = std::max(1, getRageDamageBonus(ss.classLevel(CharacterClass::Barbarian)));
    int amount = 0;
    for (int i = 0; i < dice; ++i) amount += roll(6);

    Agent::Stats ts = bm.getAgentStats(target);
    grantTempHp(ts, amount, source);                                  // max() semantics + rage provenance
    bm.setAgentStats(target, ts);

    Agent::Conditions sc = bm.getAgentConditions(source);
    sc.vitality_used_this_turn = true;                                // free, once per turn (NOT the reaction)
    bm.setAgentConditions(source, sc);

    log_("{} uses Vitality of the Tree on {}: {}d6 = {} temp HP",
         agentName(bm, source), agentName(bm, target), dice, amount);
    return true;
}

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
        int vitality_temp_hp = stats.classLevel(CharacterClass::Barbarian);
        grantTempHp(stats, vitality_temp_hp);  // entry THP is NOT rage-tagged: it persists past Rage end
        log_("{} grants Vitality: {} temp HP", agentName(bm, idx), vitality_temp_hp);
    }

    // Berserker L6: Mindless Rage - clear Charmed and Frightened conditions
    if (stats.barbarian_subclass == BerserkerPath && stats.classLevel(CharacterClass::Barbarian) >= 6) {
        cond.charmed = false;
        cond.frightened = false;
        log_("{} Mindless Rage: charmed/frightened cleared", agentName(bm, idx));
    }

    // Wild Heart L6: Aspect of the Wilds - apply aspect bonuses
    if (stats.barbarian_subclass == WildHeartPath && stats.classLevel(CharacterClass::Barbarian) >= 6) {
        if (stats.wild_heart_aspect == OwlAspect) {
            stats.darkvision_range = std::max(stats.darkvision_range, 60);
            log_("{} Owl Aspect: darkvision 60 ft", agentName(bm, idx));
        } else if (stats.wild_heart_aspect == SalmonAspect) {
            stats.speed_swim = std::max(stats.speed_swim, stats.speed_walk);
            log_("{} Salmon Aspect: swim speed = walk speed ({})", agentName(bm, idx), stats.speed_walk);
        }
    }

    // Reset Zealot Fanatical Focus flag on Rage activation (can use once per Rage)
    if (stats.barbarian_subclass == ZealotPath && stats.classLevel(CharacterClass::Barbarian) >= 6) {
        cond.fanatical_focus_used = false;
        log_("{} Fanatical Focus: ready for use this Rage", agentName(bm, idx));
    }

    // Wild Heart L14 — Power of the Wilds: the chosen option (Falcon/Lion/Ram) applies for
    // the duration of this Rage. Ram is an on-hit melee rider (handled in applyAttackResult);
    // Falcon grants a Fly Speed (only while unarmored); Lion sets the disadvantage-aura flag.
    if (stats.barbarian_subclass == WildHeartPath && stats.classLevel(CharacterClass::Barbarian) >= 14) {
        cond.lion_aura_active = (stats.wild_heart_power == LionPower);
        bool wearing_armor = false;
        for (const auto& piece : agents[static_cast<std::size_t>(idx)].armor) {
            if (!piece.name.empty()) { wearing_armor = true; break; }
        }
        if (stats.wild_heart_power == FalconPower && !wearing_armor) {
            stats.speed_fly = std::max(stats.speed_fly, stats.speed_walk);
            log_("{} Falcon: Fly Speed {} ft while raging", agentName(bm, idx), stats.speed_walk);
        } else if (stats.wild_heart_power == LionPower) {
            log_("{} Lion: enemies within 5 ft have Disadvantage attacking anyone but you", agentName(bm, idx));
        } else if (stats.wild_heart_power == RamPower) {
            log_("{} Ram: melee hits knock Large-or-smaller creatures Prone", agentName(bm, idx));
        }
    }

    // World Tree L14 — Travel along the Tree: the 150-ft teleport upgrade is once per Rage.
    if (stats.barbarian_subclass == WorldTreePath && stats.classLevel(CharacterClass::Barbarian) >= 14) {
        cond.world_tree_long_teleport_used = false;
    }

    // Spend one use of Rage resource
    if (stats.resources.find("Rage") != stats.resources.end()) {
        Resource& rage = stats.resources.at("Rage");
        if (rage.current > 0) {
            rage.current--;
            rage.duration_remaining = rage.duration;
        }
    }

    // Instinctive Pounce (L7): grant up to half speed of extra movement THIS turn
    if (stats.classLevel(CharacterClass::Barbarian) >= 7) {
        mv_.grantWalk(idx, stats.speed_walk / 2);
        log_("{} Instinctive Pounce: +{} ft movement", agentName(bm, idx), stats.speed_walk / 2);
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

    // Reset Relentless Rage DC to base (10) when rage ends
    stats.relentless_rage_dc = 10;

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
    if (stats.barbarian_subclass == WildHeartPath && stats.classLevel(CharacterClass::Barbarian) >= 6) {
        if (stats.wild_heart_aspect == SalmonAspect) {
            stats.speed_swim = 0;  // Reset swim speed (Salmon aspect only during Rage)
        }
        if (stats.wild_heart_aspect == OwlAspect) {
            stats.darkvision_range = 0;  // Reset darkvision (Owl aspect only during Rage)
        }
    }

    // Wild Heart L14 Falcon: the granted Fly Speed only lasts while raging.
    if (stats.barbarian_subclass == WildHeartPath && stats.wild_heart_power == FalconPower) {
        stats.speed_fly = 0;
    }
    cond.lion_aura_active = false;
    cond.world_tree_long_teleport_used = false;

    // Zealot L14 Rage of the Gods: the divine-warrior form ends with the Rage. Drop the granted
    // Fly Speed and the Necrotic/Psychic/Radiant resistances (rage_of_gods_used stays set — it's
    // once per long rest, cleared by applyLongRest).
    if (cond.rage_of_gods_active) {
        cond.rage_of_gods_active = false;
        stats.speed_fly = 0;
        for (MagicDamage_t t : {MagicDamage_t::Necrotic, MagicDamage_t::Psychic, MagicDamage_t::Radiant})
            stats.magic_damage_multipliers[static_cast<std::size_t>(t)] = stats.speciesMagicMult(t);
        log_("{} Rage of the Gods: divine form ends", agentName(bm, idx));
    }

    // Clear Rage duration
    if (stats.resources.find("Rage") != stats.resources.end()) {
        Resource& rage = stats.resources.at("Rage");
        rage.duration_remaining = 0;
    }

    bm.setAgentConditions(idx, cond);
    bm.setAgentStats(idx, stats);

    // World Tree "Vitality of the Tree": temp HP granted by THIS Barbarian's Rage vanishes when the
    // Rage ends. 5e temp HP never stacks, so any creature whose current temp_hp is tagged with this
    // Barbarian's index loses exactly that temp HP. (The entry temp HP grant is left untagged on
    // purpose — it persists as normal temp HP.)
    for (std::size_t i = 0; i < agents.size(); ++i) {
        Agent::Stats ts = bm.getAgentStats(static_cast<int>(i));
        if (ts.rage_thp_source_idx == idx) {
            ts.temp_hp = 0;
            ts.rage_thp_source_idx = -1;
            bm.setAgentStats(static_cast<int>(i), ts);
        }
    }

    log_("{} ends Rage: raging=false, BPS resistance cleared, reckless_attack cleared", agentName(bm, idx));
}

bool CombatEngine::useIntimidatingPresence(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);

    // Gate on Berserker L14+ (2024 PHB: Intimidating Presence is the L14 feature; L10 is Retaliation)
    if (stats.lacksClass(CharacterClass::Barbarian) ||
        stats.barbarian_subclass != BerserkerPath ||
        stats.classLevel(CharacterClass::Barbarian) < 14) {
        return false;
    }

    // Check bonus action availability
    if (!hasBonusAction(bm, idx)) {
        return false;
    }

    // Check resource availability (uses per long rest, or spend Rage)
    Resource* ip_resource = stats.getResource("Intimidating Presence");
    bool has_ip_uses = ip_resource && ip_resource->current > 0;
    bool can_spend_rage = stats.resources.count("Rage") && stats.resources.at("Rage").current > 0;

    if (!has_ip_uses && !can_spend_rage) {
        return false;
    }

    const PlacedAgent& barbarian_pa = agents[static_cast<std::size_t>(idx)];
    const int origin_col = barbarian_pa.origin.col;
    const int origin_row = barbarian_pa.origin.row;
    const int radius_ft = 30;

    // Calculate save DC: 8 + STR mod + PB
    int str_mod = (stats.str - 10) / 2;
    if (stats.str < 10 && (stats.str - 10) % 2 != 0) --str_mod;
    const int save_dc = 8 + str_mod + stats.prof_bonus;

    // Scan all creatures within 30 ft; skip self and skip allies
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int target_idx = static_cast<int>(i);
        if (target_idx == idx) continue;  // Skip self

        const PlacedAgent& target_pa = agents[i];
        // Euclidean emanation radius, matching Spirit Guardians (resolveAoeTargets, Spell::Sphere).
        const float dx = static_cast<float>(target_pa.origin.col - origin_col);
        const float dy = static_cast<float>(target_pa.origin.row - origin_row);
        const float dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0f;

        if (dist_ft > static_cast<float>(radius_ft)) continue;  // Out of range

        // Blocked by Total Cover like any Emanation — a creature behind a wall isn't cowed.
        if (!bm.hasLineOfSight(barbarian_pa.origin, barbarian_pa.agent->getSize(),
                               target_pa.origin, target_pa.agent->getSize()))
            continue;

        if (areAllies(bm, idx, target_idx)) continue;  // Skip allies (enemies only)

        // Roll WIS save for the target
        const int wis_save_mod = saveModFor(bm, target_idx, SaveWis);

        const int save_d20 = beguilingTwistAdvantage(bm, target_idx, "Frightened") ? rollAdvantage(20) : roll(20);
        const int save_total = save_d20 + wis_save_mod;
        const bool failed = save_total < save_dc;

        log_("{} makes a WIS save vs Intimidating Presence (DC {}): {} + {} = {} ({})",
             agentName(bm, target_idx), save_dc, save_d20, wis_save_mod, save_total,
             failed ? "FAILED" : "PASSED");

        if (failed) {
            // Apply Frightened until end of Barbarian's next turn. addAgentCondition routes
            // through applyFrightened internally (which also honors Aura of Courage immunity),
            // so we do NOT call applyFrightened separately here.
            ActiveAgentCondition aac{};
            aac.agent_idx = target_idx;
            aac.condition_name = "Frightened";
            aac.caster_idx = idx;
            aac.turns_remaining = 2;  // until end of next turn (turn starts, runs, then starts next turn)
            (void)addAgentCondition(bm, aac);
        } else {
            charmFearSaveSucceeded(bm, target_idx);   // Beguiling Twist's trigger
        }
    }

    // Spend resource (IP use or Rage use)
    if (has_ip_uses) {
        ip_resource->spend(1);
        stats.resources["Intimidating Presence"] = *ip_resource;
    } else {
        Resource& rage = stats.resources.at("Rage");
        rage.current--;
    }

    // Persist the resource spend, THEN consume the bonus action. spendBonusAction re-reads
    // fresh stats and writes them back, so it must run AFTER setAgentStats or it would be
    // clobbered (and the bonus action effectively refunded).
    bm.setAgentStats(idx, stats);
    spendBonusAction(bm, idx);

    log_("{} uses Intimidating Presence (save DC {})", agentName(bm, idx), save_dc);
    return true;
}

bool CombatEngine::useZealousPresence(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Gate on Zealot L10+
    if (stats.lacksClass(CharacterClass::Barbarian) ||
        stats.barbarian_subclass != ZealotPath ||
        stats.classLevel(CharacterClass::Barbarian) < 10) {
        return false;
    }

    // Check bonus action availability
    if (!hasBonusAction(bm, idx)) {
        return false;
    }

    // Check resource availability (1 use per long rest, or spend Rage)
    Resource* zp_resource = stats.getResource("Zealous Presence");
    bool has_zp_uses = zp_resource && zp_resource->current > 0;
    bool can_spend_rage = stats.resources.count("Rage") && stats.resources.at("Rage").current > 0;

    if (!has_zp_uses && !can_spend_rage) {
        return false;
    }

    const PlacedAgent& zealot_pa = agents[static_cast<std::size_t>(idx)];
    const int origin_col = zealot_pa.origin.col;
    const int origin_row = zealot_pa.origin.row;
    const int radius_ft = 60;
    const int max_targets = 10;

    int targets_buffed = 0;

    // Scan all creatures within 60 ft; select ALLIES (up to 10, including self)
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int target_idx = static_cast<int>(i);

        // Allow self and allies only
        if (target_idx != idx && !areAllies(bm, idx, target_idx)) continue;

        const PlacedAgent& target_pa = agents[i];
        // Euclidean emanation radius, matching Spirit Guardians (resolveAoeTargets, Spell::Sphere).
        const float dx = static_cast<float>(target_pa.origin.col - origin_col);
        const float dy = static_cast<float>(target_pa.origin.row - origin_row);
        const float dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0f;

        if (dist_ft > static_cast<float>(radius_ft)) continue;  // Out of range

        // Blocked by Total Cover like any Emanation — an ally behind a wall isn't inspired.
        if (!bm.hasLineOfSight(zealot_pa.origin, zealot_pa.agent->getSize(),
                               target_pa.origin, target_pa.agent->getSize()))
            continue;

        if (targets_buffed >= max_targets) break;  // Hit cap

        // Grant zealous_blessing: will be read in determineAdvantage (attacks) and rollSpellSave (saves)
        Agent::Conditions target_cond = bm.getAgentConditions(target_idx);
        target_cond.zealous_blessing = true;
        target_cond.zealous_blessing_by = idx;  // expires as this Zealot's next turn begins (beginTurn sweep)
        bm.setAgentConditions(target_idx, target_cond);
        targets_buffed++;

        log_("{} gains Zealous Presence: Advantage on attack rolls and saves until start of {}'s next turn",
             agentName(bm, target_idx), agentName(bm, idx));
    }

    // Spend resource (ZP use or Rage use)
    if (has_zp_uses) {
        zp_resource->spend(1);
        stats.resources["Zealous Presence"] = *zp_resource;
    } else {
        Resource& rage = stats.resources.at("Rage");
        rage.current--;
    }

    // Persist the resource spend, THEN consume the bonus action. spendBonusAction re-reads
    // fresh stats and writes them back, so it must run AFTER setAgentStats or it would be
    // clobbered (and the bonus action effectively refunded).
    bm.setAgentStats(idx, stats);
    spendBonusAction(bm, idx);

    log_("{} uses Zealous Presence: {} creature(s) gain Advantage on attacks and saves",
         agentName(bm, idx), targets_buffed);
    return true;
}

bool CombatEngine::activateRageOfTheGods(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);

    // Gate on Zealot L14+, currently raging, once per long rest.
    if (stats.lacksClass(CharacterClass::Barbarian) ||
        stats.barbarian_subclass != ZealotPath ||
        stats.classLevel(CharacterClass::Barbarian) < 14 ||
        !cond.raging ||
        stats.rage_of_gods_used) {
        return false;
    }

    cond.rage_of_gods_active = true;
    stats.rage_of_gods_used  = true;

    // Flight (= Speed, can hover) + Resistance to Necrotic, Psychic, Radiant.
    stats.speed_fly = std::max(stats.speed_fly, stats.speed_walk);
    stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Necrotic)] = 0.5f;
    stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Psychic)]  = 0.5f;
    stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Radiant)]  = 0.5f;

    bm.setAgentConditions(idx, cond);
    bm.setAgentStats(idx, stats);
    log_("{} assumes the form of a divine warrior (Rage of the Gods): Fly Speed {} ft + hover, "
         "Resistance to Necrotic/Psychic/Radiant", agentName(bm, idx), stats.speed_walk);
    return true;
}

bool CombatEngine::travelAlongTree(BattleMap& bm, int idx, int target_col, int target_row,
                                   bool long_range) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);

    // Gate on World Tree L14+, currently raging.
    if (stats.lacksClass(CharacterClass::Barbarian) ||
        stats.barbarian_subclass != WorldTreePath ||
        stats.classLevel(CharacterClass::Barbarian) < 14 ||
        !cond.raging) {
        return false;
    }

    // The 150-ft upgrade is once per Rage; the base teleport is 60 ft.
    if (long_range && cond.world_tree_long_teleport_used) return false;
    const int max_ft = long_range ? 150 : 60;

    if (!hasBonusAction(bm, idx)) return false;

    // Range check (Euclidean cell distance × 5 ft) from current space to destination.
    const Cell origin = agents[static_cast<std::size_t>(idx)].origin;
    const float dx = static_cast<float>(target_col - origin.col);
    const float dy = static_cast<float>(target_row - origin.row);
    const float dist_ft = std::sqrt(dx * dx + dy * dy) * 5.0f;
    if (dist_ft > static_cast<float>(max_ft)) return false;

    if (!isValidTeleportDestination(bm, target_col, target_row)) return false;
    if (!teleportAgent(bm, idx, target_col, target_row)) return false;

    if (long_range) {
        cond.world_tree_long_teleport_used = true;
        bm.setAgentConditions(idx, cond);
    }
    spendBonusAction(bm, idx);
    log_("{} travels along the World Tree: teleports {} ft", agentName(bm, idx),
         static_cast<int>(dist_ft));
    return true;
}

AttackResult CombatEngine::applyRetaliation(BattleMap& bm, int defender_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (defender_idx < 0 || defender_idx >= n) return AttackResult{};

    Agent::Conditions dc = bm.getAgentConditions(defender_idx);
    if (!dc.retaliation_available) return AttackResult{};   // only when a qualifying hit offered it

    const int attacker_idx = dc.retaliation_target_idx;
    const int widx = riposteWeaponIdx(bm, defender_idx);     // a melee weapon to strike back with
    if (attacker_idx < 0 || attacker_idx >= n || widx < 0) {
        dc.retaliation_available = false;
        dc.retaliation_target_idx = -1;
        bm.setAgentConditions(defender_idx, dc);
        return AttackResult{};
    }

    // Spend the reaction + clear the flag, then make a single melee attack back (RAW: no resource).
    dc.retaliation_available = false;
    dc.retaliation_target_idx = -1;
    dc.reaction_used = true;
    bm.setAgentConditions(defender_idx, dc);
    log_("{} retaliates against {} (reaction — one melee attack)",
         agentName(bm, defender_idx), agentName(bm, attacker_idx));

    // Atomic melee attack back (like applyRiposte — no separate GUI reaction window).
    return executeAction(bm, Attack{defender_idx, attacker_idx, widx});
}

bool CombatEngine::canUsePrimalKnowledge(const BattleMap& bm, int idx, const std::string& skill_name) const noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    const Agent::Conditions& cond = pa.agent->getConditions();

    // Primal Knowledge (L3): Acrobatics and Stealth can use STR instead of their normal ability while Raging
    if (stats.lacksClass(CharacterClass::Barbarian) || stats.classLevel(CharacterClass::Barbarian) < 3)
        return false;

    if (!cond.raging)
        return false;

    // Only Acrobatics and Stealth are relevant for combat
    if (skill_name == "Acrobatics" || skill_name == "Stealth")
        return true;

    return false;
}

} // namespace rpg
