// ─────────────────────────────────────────────────────────────────────────────
//  combat_feats.cpp  –  CombatEngine feat, fighting-style, boon, mastery and species features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Scope (COMBAT_CLASS_SPLIT_PLAN.md D8): feats (Telekinetic, Sentinel, Grappler, Lucky),
//  fighting styles (Interception), Epic Boons (Peerless Aim, Merge with Shadows), Weapon
//  Mastery (Topple) and species features. Nothing a class grants goes here.
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

GrappleResult CombatEngine::applyPunchAndGrab(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    GrappleResult result;
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return result;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return result;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.grappler_punch_grab_available || atk_cond.grappler_punch_grab_used) return result;  // once per turn

    // Mark Punch-and-Grab used for the turn + clear the flag, THEN run the grapple. The grapple routes
    // through the shared resolveGrapple core (contested check + computed escape DC), exactly like the
    // standalone Grapple action — no parallel grapple path.
    atk_cond.grappler_punch_grab_used      = true;
    atk_cond.grappler_punch_grab_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    result = resolveGrapple(bm, attacker_idx, target_idx, /*contested=*/true, /*escape_dc_override=*/0);
    log_("{}: Grappler — Punch-and-Grab also attempts to grapple {}",
         agentName(bm, attacker_idx), agentName(bm, target_idx));
    return result;
}

// Boon of Combat Prowess (Peerless Aim) eligibility — path-agnostic gate shared by the NPC auto-fire
// (maybePeerlessAim), the PC deferred-flag arming (applyAttackResult), and applyPeerlessAim. The
// attacker must hold the boon, be alive, and not have used the once-per-turn miss→hit yet. The caller
// confirms the attack actually missed.
bool CombatEngine::canPeerlessAim(const BattleMap& bm, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return false;
    const Agent::Stats as = bm.getAgentStats(attacker_idx);
    if (as.hp_cur <= 0 || !as.hasFeat("Boon of Combat Prowess")) return false;
    return !bm.getAgentConditions(attacker_idx).peerless_aim_used;
}

// Boon of Combat Prowess (Peerless Aim) — post-hoc GUI entry. After a PC misses, the GUI offers this;
// it turns the miss into a hit, rolls + applies weapon damage, and updates result (mirrors
// applyGuidedStrike's damage application). Consumes the once-per-turn use.
void CombatEngine::applyPeerlessAim(BattleMap& bm, const Attack& action, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx, tgt = action.target_idx;
    if (atk < 0 || atk >= n || tgt < 0 || tgt >= n) return;
    if (!canPeerlessAim(bm, atk)) return;
    if (result.hit) return;                                // nothing to promote (already a hit)

    // Consume the once-per-turn use and clear the deferred flag.
    Agent::Conditions ac = bm.getAgentConditions(atk);
    ac.peerless_aim_used      = true;
    ac.peerless_aim_available = false;
    bm.setAgentConditions(atk, ac);

    result.hit = true;
    log_("{} takes Peerless Aim: the miss becomes a hit instead", agentName(bm, atk));

    Agent::Stats atk_stats_p = bm.getAgentStats(atk);
    Agent::Stats tgt_stats_p = bm.getAgentStats(tgt);
    auto weapons = bm.getAgentWeapons(atk);
    if (weapons.empty()) return;
    const int wi_p = std::clamp(action.weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
    const Weapon& w = weapons[static_cast<std::size_t>(wi_p)];
    rollDamage(w, atk_stats_p, tgt_stats_p, result, action.no_ability_damage);  // miss was not a crit → normal damage
    result.hp_before = tgt_stats_p.hp_cur;
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_stats_p.temp_hp);
    tgt_stats_p.temp_hp = std::max(0, tgt_stats_p.temp_hp - dmg);
    tgt_stats_p.hp_cur  = std::clamp(tgt_stats_p.hp_cur - overflow, 0, tgt_stats_p.hp_max);
    result.hp_after = tgt_stats_p.hp_cur;
    result.target_down = (tgt_stats_p.hp_cur <= 0);
    bm.setAgentStats(tgt, tgt_stats_p);
    log_("Peerless Aim turns a miss into a hit: {} damage to {}", dmg, agentName(bm, tgt));
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, tgt, dmg);
        processDamageTaken(bm, tgt, dmg);
    }
}

AttackResult CombatEngine::applySentinelGuard(BattleMap& bm, int sentinel_idx,
                                              int attacker_idx, int weapon_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (sentinel_idx < 0 || sentinel_idx >= n || attacker_idx < 0 || attacker_idx >= n)
        return AttackResult{};
    Agent::Conditions sc = bm.getAgentConditions(sentinel_idx);
    if (!canTakeReaction(sc)) return AttackResult{};      // re-validate (canSentinelGuard checked, but be safe)

    log_("Sentinel Guardian: {} reacts — melee attack vs {}",
         agentName(bm, sentinel_idx), agentName(bm, attacker_idx));

    // The guard counter-attack: a fresh melee attack at the attacker. resolving_sentinel_guard_ keeps
    // this strike from re-opening the OnAllyAttacked window (a guard does not provoke its own guard).
    ctx_.resolving_sentinel_guard_ = true;
    AttackResult r = executeAction(bm, Attack{sentinel_idx, attacker_idx, weapon_idx});
    ctx_.resolving_sentinel_guard_ = false;

    // Spend the reaction (re-fetch: executeAction may have mutated the Sentinel's conditions).
    sc = bm.getAgentConditions(sentinel_idx);
    sc.reaction_used = true;
    bm.setAgentConditions(sentinel_idx, sc);
    return r;
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
    ac.topple_used_this_turn = true;           // mark as used (once per turn)
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
    res.save_roll = roll(20, mod);

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

int CombatEngine::applyInterception(BattleMap& bm, int interceptor_idx, int target_idx, int damage_taken) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (interceptor_idx < 0 || interceptor_idx >= n || target_idx < 0 || target_idx >= n) return -1;
    if (damage_taken <= 0) return -1;

    Agent::Stats istats = bm.getAgentStats(interceptor_idx);
    if (!istats.hasFeat("Interception")) return -1;

    Agent::Conditions ic = bm.getAgentConditions(interceptor_idx);
    if (!canTakeReaction(ic)) return -1;                       // re-validate (canIntercept checked; be safe)

    // Reduction = 1d10 + the interceptor's Proficiency Bonus; never restore more than the hit cost.
    int reduction = roll(10) + istats.prof_bonus;
    int prevented = std::min(reduction, damage_taken);

    // Spend the reaction, then heal back the prevented damage to the target.
    ic.reaction_used = true;
    bm.setAgentConditions(interceptor_idx, ic);
    healAgent(bm, target_idx, prevented);

    log_("{} uses Interception: prevents {} damage to {} (rolled reduction {})",
         agentName(bm, interceptor_idx), prevented, agentName(bm, target_idx), reduction);
    return prevented;
}

ShoveResult CombatEngine::applyTelekineticShove(BattleMap& bm, int caster_idx, int target_idx) noexcept
{
    ShoveResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size()) ||
        target_idx < 0 || target_idx >= static_cast<int>(agents.size()) ||
        caster_idx == target_idx) {
        result.log_message = "Invalid Telekinetic Shove.";
        return result;
    }

    auto& caster = agents[static_cast<std::size_t>(caster_idx)];
    auto& target = agents[static_cast<std::size_t>(target_idx)];

    // Range 30 ft (6 cells, Chebyshev).
    int dx = std::abs(target.origin.col - caster.origin.col);
    int dy = std::abs(target.origin.row - caster.origin.row);
    if (std::max(dx, dy) > 6) {
        result.log_message = "Target is beyond 30 feet.";
        return result;
    }

    const Agent::Stats cs = getAgentStats(bm, caster_idx);
    auto mod = [](int score) {
        int m = (score - 10) / 2;
        if (score < 10 && (score - 10) % 2 != 0) --m;
        return m;
    };
    // DC = 8 + PB + the best of INT/WIS/CHA (the feat's spellcasting-ability choice; we take the
    // caster's strongest mental modifier rather than store a per-character pick).
    int spell_mod = std::max({mod(cs.intel), mod(cs.wis), mod(cs.cha)});
    int dc = 8 + cs.prof_bonus + spell_mod;

    const Agent::Stats ts = getAgentStats(bm, target_idx);
    int str_mod = mod(ts.str);
    int save_d20 = roll(20);
    int save_total = save_d20 + str_mod + (ts.save_prof_str ? ts.prof_bonus : 0);

    result.valid = true;
    result.attacker_roll = dc;
    result.defender_roll = save_total;

    if (save_total >= dc) {
        result.success = false;
        result.log_message = "\"" + std::string(target.agent->name()) +
                             "\" resists the Telekinetic Shove (" + std::to_string(save_total) +
                             " vs DC " + std::to_string(dc) + ").";
        log_("{}", result.log_message);
        return result;
    }

    int cells_moved = bm.forceMoveAgent(target_idx, caster.origin, 5);
    result.push_ft_applied = cells_moved * 5;
    result.success = (result.push_ft_applied > 0);
    result.log_message = "\"" + std::string(caster.agent->name()) + "\" telekinetically shoves \"" +
                         std::string(target.agent->name()) + "\" " +
                         std::to_string(result.push_ft_applied) + " feet (save " +
                         std::to_string(save_total) + " vs DC " + std::to_string(dc) + ").";
    log_("{}", result.log_message);
    return result;
}

// Boon of the Night Spirit — Merge with Shadows: a Bonus Action grants the Invisible condition while
// the boon-holder stands in Dim Light or Darkness. The Invisibility ends when the creature next takes
// an action/bonus/reaction (invisible_persists_on_action = false), so it is mostly a one-turn setup —
// structurally identical to the Warlock's One with Shadows above.
bool CombatEngine::applyMergeWithShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& s = pa.agent->getStats();
    if (!s.hasFeat("Boon of the Night Spirit")) return false;

    // Must be standing in an area of Dim Light or Darkness (the cell's light level — not the
    // obscuration-effect layer used for fog/magical-darkness AoEs), matching Shadowy Form's gate.
    VisibilityLevel light = bm.getLightLevel(pa.origin);
    if (light != VisibilityLevel::Dim && light != VisibilityLevel::Dark &&
        light != VisibilityLevel::MagicalDark)
        return false;

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = false;  // ends when you next take an action/bonus/reaction
    bm.setAgentConditions(idx, c);
    log_("{}: Merge with Shadows — gains the Invisible condition", agentName(bm, idx));
    return true;
}

bool CombatEngine::spendLuckForAdvantage(BattleMap& bm, int idx)
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return false;  // invalid idx
    if (s.hasFeat("Lucky") && s.luck_points > 0) {
        s.luck_points -= 1;
        bm.setAgentStats(idx, s);
        grantPendingAdvantage(true, idx);   // consumed by idx's own next D20 Test, nobody else's
        log_("{} spends a Luck Point for Advantage ({} remaining)",
             agentName(bm, idx), s.luck_points);
        return true;
    }
    // RAVENLOFT M6: a carried, switched-on item's Luck Point (the Luck Blade), spent the same way.
    // Not while Incapacitated ("if you don't have the Incapacitated condition").
    if (bm.getAgentConditions(idx).incapacitated) return false;
    if (ItemSpells* is = itemLuckSource(bm, idx)) {
        is->luck -= 1;
        grantPendingAdvantage(true, idx);
        log_("{} calls on an item's luck for Advantage ({} left today)", agentName(bm, idx), is->luck);
        return true;
    }
    return false;
}

// RAVENLOFT M6: the first carried, switched-on item with a Luck Point left; nullptr if none.
ItemSpells* CombatEngine::itemLuckSource(BattleMap& bm, int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return nullptr;
    PlacedAgent& pa = bm.placedAgentMut(idx);
    auto ok = [](const std::string& name, const ItemSpells& is) {
        return !name.empty() && is.attunedOrFree() && is.luck > 0;
    };
    for (auto& it : pa.items)   if (ok(it.name, it.item_spells)) return &it.item_spells;
    for (auto& w  : pa.weapons) if (ok(w.name, w.item_spells))   return &w.item_spells;
    for (auto& a  : pa.armor)   if (ok(a.name, a.item_spells))   return &a.item_spells;
    return nullptr;
}

int CombatEngine::luckAvailable(const BattleMap& bm, int idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return 0;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& s = pa.agent->getStats();
    int n = s.hasFeat("Lucky") ? std::max(0, s.luck_points) : 0;
    auto add = [&](const std::string& name, const ItemSpells& is) {
        if (!name.empty() && is.attunedOrFree()) n += std::max(0, is.luck);
    };
    for (const auto& it : pa.items)   add(it.name, it.item_spells);
    for (const auto& w  : pa.weapons) add(w.name, w.item_spells);
    for (const auto& a  : pa.armor)   add(a.name, a.item_spells);
    return n;
}

} // namespace rpg
