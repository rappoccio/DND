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
#include <format>
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

// ─────────────────────────────────────────────────────────────────────────────
//  Species features (SPECIES_PLAN.md SP4)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canAdrenalineRush(const BattleMap& bm, int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_cur <= 0 || s.adrenalineRushRemaining() <= 0) return false;
    return !bm.getAgentConditions(idx).incapacitated;
}

bool CombatEngine::useAdrenalineRush(BattleMap& bm, int idx)
{
    if (!canAdrenalineRush(bm, idx)) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    s.adrenaline_rush_used += 1;
    const int pb = std::max(1, s.prof_bonus);
    const bool gained = pb > s.temp_hp;            // temp HP don't stack: keep the larger
    s.temp_hp = std::max(s.temp_hp, pb);
    bm.setAgentStats(idx, s);
    bm.applyDash(idx);
    log_("{}: Adrenaline Rush — Dash (+{} ft){} ({} left)", agentName(bm, idx), s.speed_walk,
         gained ? std::format(", {} temp HP", pb) : std::string(", temp HP unchanged"),
         s.adrenalineRushRemaining());
    return true;
}

bool CombatEngine::canDraconicFlight(const BattleMap& bm, int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_cur <= 0 || !s.canStartDraconicFlight()) return false;
    return !bm.getAgentConditions(idx).incapacitated;
}

bool CombatEngine::toggleDraconicFlight(BattleMap& bm, int idx)
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.draconic_flight_rounds > 0) {
        s.endDraconicFlight();
        bm.setAgentStats(idx, s);
        log_("{} folds their spectral wings (Draconic Flight ends)", agentName(bm, idx));
        return true;
    }
    if (!canDraconicFlight(bm, idx)) return false;
    s.startDraconicFlight();
    bm.setAgentStats(idx, s);
    log_("{}: Draconic Flight — fly Speed {} ft for 10 minutes", agentName(bm, idx), s.speed_fly);
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Goliath (SPECIES_PLAN.md SP6)
// ─────────────────────────────────────────────────────────────────────────────

namespace {
// The usual gate for a creature using a feature on its own turn or as a reaction.
bool featureReady(const BattleMap& bm, int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    if (bm.isAgentOnDeck(idx)) return false;
    return bm.getAgentStats(idx).hp_cur > 0 && !bm.getAgentConditions(idx).incapacitated;
}

// Spend one Giant Ancestry use (false, nothing spent, when none is left).
bool spendGiantAncestry(BattleMap& bm, int idx) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.giantAncestryRemaining() <= 0) return false;
    s.giant_ancestry_used += 1;
    bm.setAgentStats(idx, s);
    return true;
}

// Damage of one type, the target's multiplier applied (the same rounding as the riders).
int typedDamage(const Agent::Stats& tgt, MagicDamage_t t, int raw) noexcept
{
    return static_cast<int>(static_cast<float>(raw) * tgt.magic_damage_multipliers[static_cast<std::size_t>(t)]);
}
} // namespace

Cell CombatEngine::largeFormOrigin(const BattleMap& bm, int idx) const
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return {-1, -1};
    const Cell o = agents[static_cast<std::size_t>(idx)].origin;
    // The 2×2 must keep the token's own cell, so the anchor is it or a step up and/or left.
    for (const auto& [dc, dr] : {std::pair{0, 0}, {-1, 0}, {0, -1}, {-1, -1}}) {
        const Cell a{o.col + dc, o.row + dr, o.z};
        bool ok = true;
        for (int c = 0; c < 2 && ok; ++c)
            for (int r = 0; r < 2 && ok; ++r)
                ok = isValidTeleportDestination(bm, a.col + c, a.row + r);
        if (!ok || bm.footprintSplit(a, 2) || bm.agentOccupancy(a, 2, idx) != 0) continue;
        return a;
    }
    return {-1, -1};
}

bool CombatEngine::canLargeForm(const BattleMap& bm, int idx) const
{
    if (!featureReady(bm, idx)) return false;
    if (!bm.getAgentStats(idx).canStartLargeForm()) return false;
    return bm.placedAgents()[static_cast<std::size_t>(idx)].agent->getSize() == 1;
}

void CombatEngine::endLargeForm(BattleMap& bm, int idx, std::string_view why)
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return;
    Agent::Stats s = bm.getAgentStats(idx);
    if (!s.inLargeForm()) return;
    s.large_form_rounds = 0;
    const int added = s.large_form_speed_added;
    if (s.speed_walk >= added) s.speed_walk -= added;
    s.large_form_speed_added = 0;
    bm.setAgentStats(idx, s);
    const PlacedAgent& pa = bm.placedAgents()[static_cast<std::size_t>(idx)];
    pa.agent->setSize(1);                      // back to its top-left cell (D6)
    auto mv = pa.agent->rawMovement();
    pa.agent->initMovement(std::max(0, mv[0] - added), mv[1], mv[2], mv[3]);
    log_("{} shrinks back to their usual size (Large Form ends{})", agentName(bm, idx), why);
}

bool CombatEngine::toggleLargeForm(BattleMap& bm, int idx)
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    if (bm.getAgentStats(idx).inLargeForm()) {
        endLargeForm(bm, idx, "");
        return true;
    }
    if (!canLargeForm(bm, idx)) return false;
    const Cell at = largeFormOrigin(bm, idx);
    if (at.col < 0) {
        log_("{}: no room to grow — Large Form needs a free 2×2 space", agentName(bm, idx));
        return false;
    }
    Agent::Stats s = bm.getAgentStats(idx);
    s.large_form_used        = true;
    s.large_form_rounds      = kLargeFormRounds;
    s.large_form_speed_added = kLargeFormSpeed;
    s.speed_walk            += kLargeFormSpeed;
    bm.setAgentStats(idx, s);
    const PlacedAgent& pa = bm.placedAgents()[static_cast<std::size_t>(idx)];
    const int z = pa.agent->getZ();
    pa.agent->setSize(2);
    (void)bm.setAgentPosition(idx, at);
    pa.agent->setPosition(at.col, at.row, z);
    auto mv = pa.agent->rawMovement();
    pa.agent->initMovement(mv[0] + kLargeFormSpeed, mv[1], mv[2], mv[3]);
    log_("{}: Large Form — Large for 10 minutes, Speed {} ft, Advantage on Strength checks",
         agentName(bm, idx), s.speed_walk);
    return true;
}

bool CombatEngine::applyGiantAncestryOnHit(BattleMap& bm, int attacker_idx, AttackResult& result)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n) return false;
    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.giant_ancestry_available) return false;
    const int t = ac.giant_ancestry_target;
    ac.giant_ancestry_available = false;
    ac.giant_ancestry_target    = -1;
    bm.setAgentConditions(attacker_idx, ac);
    if (t < 0 || t >= n || bm.getAgentStats(t).hp_cur <= 0) return false;
    const GiantAncestry ga = bm.getAgentStats(attacker_idx).giantAncestry();
    if (ga == GiantAncestry::Hill && bm.placedAgents()[static_cast<std::size_t>(t)].agent->getSize() > 2)
        return false;
    if (!spendGiantAncestry(bm, attacker_idx)) return false;
    const int left = bm.getAgentStats(attacker_idx).giantAncestryRemaining();

    if (ga == GiantAncestry::Hill) {
        applyProne(bm, t);
        log_("{}: Hill's Tumble — {} is knocked Prone ({} left)", agentName(bm, attacker_idx),
             agentName(bm, t), left);
        return true;
    }
    const bool fire = (ga == GiantAncestry::Fire);
    if (!fire && ga != GiantAncestry::Frost) return false;
    const MagicDamage_t type = fire ? MagicDamage_t::Fire : MagicDamage_t::Cold;
    Agent::Stats ts = bm.getAgentStats(t);
    const int raw = roll(fire ? 10 : 6);
    const int dmg = typedDamage(ts, type, raw);
    result.damage_breakdown.push_back({fire ? "fire's burn" : "frost's chill", dmg});
    result.total_damage += dmg;
    result.magic_damage_types.push_back(type);
    if (dmg > 0) damageAgent(bm, t, dmg);
    ts = bm.getAgentStats(t);
    result.hp_after    = ts.hp_cur;
    result.target_down = ts.hp_cur <= 0;
    if (!fire) {
        Agent::Conditions tc = bm.getAgentConditions(t);
        tc.slowed = true;                       // Speed −10 ft (until its next turn ends)
        bm.setAgentConditions(t, tc);
    }
    log_("{}: {} — +{} {} ({}){} ({} left)", agentName(bm, attacker_idx),
         fire ? "Fire's Burn" : "Frost's Chill", dmg, fire ? "Fire" : "Cold",
         fire ? "1d10" : "1d6", fire ? "" : std::format(", {}'s Speed −10 ft", agentName(bm, t)), left);
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, t, dmg, attacker_idx);
        processDamageTaken(bm, t, dmg);
    }
    return true;
}

void CombatEngine::autoGiantAncestry(BattleMap& bm, int attacker_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n) return;
    const Agent::Conditions c = bm.getAgentConditions(attacker_idx);
    if (!c.giant_ancestry_available) return;
    const int t = c.giant_ancestry_target;
    // A Prone target gains nothing from Hill's Tumble: keep the use for a later hit.
    const bool wasted = t < 0 || t >= n || bm.getAgentStats(t).hp_cur <= 0
        || (bm.getAgentStats(attacker_idx).giantAncestry() == GiantAncestry::Hill
            && bm.getAgentConditions(t).prone);
    if (wasted) {
        Agent::Conditions keep = c;
        keep.giant_ancestry_available = false;
        keep.giant_ancestry_target    = -1;
        bm.setAgentConditions(attacker_idx, keep);
        return;
    }
    AttackResult scratch;
    (void)applyGiantAncestryOnHit(bm, attacker_idx, scratch);
}

bool CombatEngine::canCloudsJaunt(const BattleMap& bm, int idx) const
{
    if (!featureReady(bm, idx)) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    return s.giantAncestry() == GiantAncestry::Cloud && s.giantAncestryRemaining() > 0;
}

bool CombatEngine::cloudsJaunt(BattleMap& bm, int idx, int col, int row)
{
    if (!canCloudsJaunt(bm, idx)) return false;
    const PlacedAgent& pa = bm.placedAgents()[static_cast<std::size_t>(idx)];
    const Cell dest{col, row, pa.origin.z};
    if (!isSeenTeleportSpace(bm, idx, dest, kCloudsJauntCells)) return false;
    if (!teleportAgent(bm, idx, col, row)) return false;
    (void)spendGiantAncestry(bm, idx);
    log_("{}: Cloud's Jaunt — teleports to ({}, {}) ({} left)", agentName(bm, idx), col, row,
         bm.getAgentStats(idx).giantAncestryRemaining());
    return true;
}

bool CombatEngine::canStonesEndurance(const BattleMap& bm, int reactor_idx) const
{
    if (!featureReady(bm, reactor_idx)) return false;
    if (!canTakeReaction(bm.getAgentConditions(reactor_idx))) return false;
    const Agent::Stats s = bm.getAgentStats(reactor_idx);
    return s.giantAncestry() == GiantAncestry::Stone && s.giantAncestryRemaining() > 0;
}

bool CombatEngine::applyStonesEndurance(BattleMap& bm, int reactor_idx, AttackResult& r)
{
    if (!canStonesEndurance(bm, reactor_idx) || !r.hit || r.total_damage <= 0) return false;
    (void)spendGiantAncestry(bm, reactor_idx);
    Agent::Conditions c = bm.getAgentConditions(reactor_idx);
    c.reaction_used = true;
    bm.setAgentConditions(reactor_idx, c);
    const Agent::Stats s = bm.getAgentStats(reactor_idx);
    const int d = roll(12);
    const int cut = std::max(0, d + dndMod(s.con));
    const int before = r.total_damage;
    r.total_damage = std::max(0, before - cut);
    r.damage_breakdown.push_back({"stone's endurance", r.total_damage - before});
    log_("{}: Stone's Endurance — reduces the damage by {} (1d12 {} + CON) ({} -> {}, {} left)",
         agentName(bm, reactor_idx), cut, d, before, r.total_damage, s.giantAncestryRemaining());
    return true;
}

bool CombatEngine::canStormsThunder(const BattleMap& bm, int reactor_idx, int attacker_idx) const
{
    if (!featureReady(bm, reactor_idx)) return false;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) || attacker_idx == reactor_idx)
        return false;
    if (!canTakeReaction(bm.getAgentConditions(reactor_idx))) return false;
    const Agent::Stats s = bm.getAgentStats(reactor_idx);
    if (s.giantAncestry() != GiantAncestry::Storm || s.giantAncestryRemaining() <= 0) return false;
    if (bm.getAgentStats(attacker_idx).hp_cur <= 0) return false;
    const PlacedAgent& me = agents[static_cast<std::size_t>(reactor_idx)];
    const PlacedAgent& them = agents[static_cast<std::size_t>(attacker_idx)];
    return footprintDistance(me.origin, me.agent->getSize(), them.origin, them.agent->getSize())
           <= kStormsThunderCells;
}

bool CombatEngine::applyStormsThunder(BattleMap& bm, int reactor_idx, int attacker_idx)
{
    if (!canStormsThunder(bm, reactor_idx, attacker_idx)) return false;
    (void)spendGiantAncestry(bm, reactor_idx);
    Agent::Conditions c = bm.getAgentConditions(reactor_idx);
    c.reaction_used = true;
    bm.setAgentConditions(reactor_idx, c);
    const int raw = roll(8);
    const int dmg = typedDamage(bm.getAgentStats(attacker_idx), MagicDamage_t::Thunder, raw);
    log_("{}: Storm's Thunder — {} takes {} Thunder ({} left)", agentName(bm, reactor_idx),
         agentName(bm, attacker_idx), dmg, bm.getAgentStats(reactor_idx).giantAncestryRemaining());
    if (dmg > 0) {
        damageAgent(bm, attacker_idx, dmg);
        checkConcentrationOnDamage(bm, attacker_idx, dmg, reactor_idx);
        processDamageTaken(bm, attacker_idx, dmg);
    }
    return true;
}

// ── Hellish Rebuke (SP6) ──────────────────────────────────────────────────────

namespace {
constexpr std::string_view kHellishRebuke = "Hellish Rebuke";

bool knowsHellishRebuke(const PlacedAgent& pa) noexcept
{
    if (pa.agent->getStats().grantedSpell(kHellishRebuke)) return true;
    for (const auto& sp : pa.spells)
        if (sp.name == kHellishRebuke) return true;
    return false;
}

// The lowest slot of level 1 or more with a cast left (1-based), 0 for none.
int lowestSlot(const Agent::Stats& s) noexcept
{
    for (int i = 0; i < static_cast<int>(s.spell_slots_remaining.size()); ++i)
        if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) return i + 1;
    return 0;
}
} // namespace

bool CombatEngine::canHellishRebuke(const BattleMap& bm, int reactor_idx, int attacker_idx) const
{
    if (!featureReady(bm, reactor_idx)) return false;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) || attacker_idx == reactor_idx)
        return false;
    if (!canTakeReaction(bm.getAgentConditions(reactor_idx))) return false;
    const PlacedAgent& me = agents[static_cast<std::size_t>(reactor_idx)];
    if (!knowsHellishRebuke(me)) return false;
    const Agent::Stats s = me.agent->getStats();
    if (s.grantedFreeLeft(kHellishRebuke) <= 0 && lowestSlot(s) == 0) return false;
    if (bm.getAgentStats(attacker_idx).hp_cur <= 0) return false;
    const PlacedAgent& them = agents[static_cast<std::size_t>(attacker_idx)];
    if (footprintDistance(me.origin, me.agent->getSize(), them.origin, them.agent->getSize()) > 12)
        return false;
    return canPerceiveTarget(bm, reactor_idx, attacker_idx);
}

bool CombatEngine::applyHellishRebuke(BattleMap& bm, int reactor_idx, int attacker_idx)
{
    if (!canHellishRebuke(bm, reactor_idx, attacker_idx)) return false;
    Agent::Stats s = bm.getAgentStats(reactor_idx);
    int level = 1;
    const char* paid = "a free cast";
    if (!s.spendGrantedFree(kHellishRebuke)) {
        level = lowestSlot(s);
        s.spell_slots_remaining[static_cast<std::size_t>(level - 1)] -= 1;
        paid = "a slot";
    }
    bm.setAgentStats(reactor_idx, s);
    Agent::Conditions c = bm.getAgentConditions(reactor_idx);
    c.reaction_used = true;
    bm.setAgentConditions(reactor_idx, c);

    const GrantedSpell* g = s.grantedSpell(kHellishRebuke);
    const int ability = (g && g->ability >= 0) ? g->ability : s.spellcasting_ability;
    const int dc = rules::spellSaveDcFromAbility(s, static_cast<SaveAbility_t>(ability)) + s.spell_dc_bonus;
    int raw = 0;
    for (int i = 0; i < 1 + level; ++i) raw += roll(10);   // 2d10, +1d10 per level above 1
    log_("{} casts Hellish Rebuke at level {} ({}) — {} makes a DEX save (DC {})",
         agentName(bm, reactor_idx), level, paid, agentName(bm, attacker_idx), dc);
    const bool saved = rollFixedDcSave(bm, attacker_idx, SaveDex, dc, "Hellish Rebuke");
    const int dealt = typedDamage(bm.getAgentStats(attacker_idx), MagicDamage_t::Fire, saved ? raw / 2 : raw);
    log_("Hellish Rebuke: {} takes {} Fire{}", agentName(bm, attacker_idx), dealt, saved ? " (half)" : "");
    if (dealt > 0) {
        damageAgent(bm, attacker_idx, dealt);
        checkConcentrationOnDamage(bm, attacker_idx, dealt, reactor_idx);
        processDamageTaken(bm, attacker_idx, dealt);
    }
    return true;
}

AttackResult CombatEngine::applyHeroicReroll(BattleMap& bm, int attacker_idx, int target_idx,
                                             int weapon_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n)
        return AttackResult{};
    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    Agent::Stats s = bm.getAgentStats(attacker_idx);
    if (!ac.heroic_reroll_available || !s.heroic_inspiration) return AttackResult{};
    ac.heroic_reroll_available = false;
    s.heroic_inspiration = false;
    bm.setAgentConditions(attacker_idx, ac);
    bm.setAgentStats(attacker_idx, s);
    log_("{} spends Heroic Inspiration — rerolling the attack", agentName(bm, attacker_idx));
    // The ★ is gone, so this re-resolution cannot offer another Heroic reroll.
    return executeAction(bm, Attack{attacker_idx, target_idx, weapon_idx});
}

bool CombatEngine::canHeroicSaveReroll(const BattleMap& bm, int reactor, int save_target) const
{
    if (reactor != save_target) return false;                     // your own save only
    if (reactor < 0 || reactor >= static_cast<int>(bm.placedAgents().size())) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    return s.heroic_inspiration && s.hp_cur > 0;
}

bool CombatEngine::applyHeroicRerollToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    if (!canHeroicSaveReroll(bm, reactor, ss.target_idx)) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    s.heroic_inspiration = false;                                 // costs the ★, not the Reaction
    bm.setAgentStats(reactor, s);
    const int old_d20 = ss.d20;
    ss.d20 = d20TestFor(bm, reactor);                             // the new roll stands
    reevaluateSave(ss);
    log_("{} spends Heroic Inspiration: rerolls the save {}→{} = {} vs DC {} → {}",
         agentName(bm, reactor), old_d20, ss.d20, ss.total, ss.dc, ss.saved ? "SAVES" : "still fails");
    return true;
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

// ─────────────────────────────────────────────────────────────────────────────
//  Moved from combat_spells.cpp (COMBAT_CLASS_SPLIT_PLAN.md R6c)
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::applyBoonOfFate(BattleMap& bm, int idx, bool boost) noexcept
{
    // Boon of Fate — Improve Fate (SRD 5.2 p.88). Roll 2d4 and apply ± to the NEXT D20 Test
    // (attack roll or saving throw) via the shared pending_roll_bonus_ primitive; 1/short-or-long
    // rest (also refreshed at initiative). Mirrors Bend Luck (2d4 instead of 1d4, feat-gated).
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (!stats.hasFeat("Boon of Fate")) {
        log_("{} does not have the Boon of Fate", agentName(bm, idx));
        return 0;
    }
    if (stats.boon_of_fate_used) {
        log_("{} has already used Boon of Fate since the last rest", agentName(bm, idx));
        return 0;
    }

    int value = roll(4) + roll(4);                       // 2d4
    ctx_.pending_roll_bonus_ = boost ? value : -value;        // bonus or penalty to the next D20 Test
    stats.boon_of_fate_used = true;
    bm.setAgentStats(idx, stats);

    log_("{} invokes Boon of Fate: {}{} to the next D20 Test (attack roll or saving throw)",
         agentName(bm, idx), boost ? "+" : "-", value);
    return value;
}

// ── More species (MORE_SPECIES_PLAN.md MS3) ──────────────────────────────────────────────────

int CombatEngine::surpriseAttackDamage(BattleMap& bm, int attacker_idx, int target_idx, float mult)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return -1;
    if (!bm.getAgentStats(attacker_idx).hasSurpriseAttack()) return -1;
    if (bm.getAgentConditions(attacker_idx).surprise_attack_used) return -1;
    if (bm.getAgentConditions(target_idx).has_taken_turn_this_combat) return -1;
    const int a = roll(6), b = roll(6);
    const int dmg = std::max(0, static_cast<int>(static_cast<float>(a + b) * mult));
    log_("{}: Surprise Attack +2d6 [{}, {}]{} = {} ({} hasn't acted yet)", agentName(bm, attacker_idx),
         a, b, mult != 1.0f ? std::format(" x{:g}", mult) : std::string{}, dmg, agentName(bm, target_idx));
    return dmg;
}

void CombatEngine::beginCheck(int idx) noexcept
{
    if (ctx_.past_life_idx_ == idx && ctx_.last_check_.idx == idx) {   // armed: replay
        ctx_.check_replaying_  = true;
        ctx_.check_replay_pos_ = 0;
        return;
    }
    ctx_.check_replaying_ = false;
    ctx_.past_life_idx_   = -1;
    ctx_.past_life_d6_    = 0;
    ctx_.last_check_      = {};
    ctx_.last_check_.idx  = idx;
}

int CombatEngine::checkD20(int rolled) noexcept
{
    auto& c = ctx_.last_check_;
    if (ctx_.check_replaying_) {
        if (ctx_.check_replay_pos_ < c.d20s.size()) return c.d20s[ctx_.check_replay_pos_++];
        return rolled;
    }
    c.d20s.push_back(rolled);
    return rolled;
}

int CombatEngine::checkContestD20(int defender_idx, int rolled) noexcept
{
    auto& c = ctx_.last_check_;
    if (ctx_.check_replaying_) return c.def_idx == defender_idx ? c.def_d20 : rolled;
    c.def_idx = defender_idx;
    c.def_d20 = rolled;
    return rolled;
}

int CombatEngine::checkBonus(BattleMap& bm, int idx) noexcept
{
    if (ctx_.check_replaying_ && ctx_.last_check_.idx == idx) {
        log_("{}: Knowledge from a Past Life +{} to the same roll", agentName(bm, idx), ctx_.past_life_d6_);
        return ctx_.last_check_.strengthen + ctx_.past_life_d6_;
    }
    const int s = consumeStrengthenBonus(bm, idx);
    if (!ctx_.check_replaying_ && ctx_.last_check_.idx == idx) ctx_.last_check_.strengthen = s;
    return s;
}

void CombatEngine::endCheck(bool success) noexcept
{
    if (ctx_.check_replaying_) {
        ctx_.last_check_.replayed = true;
        ctx_.check_replaying_ = false;
        ctx_.past_life_idx_   = -1;
        ctx_.past_life_d6_    = 0;
    }
    ctx_.last_check_.failed = !success;
}

bool CombatEngine::canPastLife(const BattleMap& bm, int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    const auto& c = ctx_.last_check_;
    return c.idx == idx && c.failed && !c.replayed && bm.getAgentStats(idx).pastLifeRemaining() > 0;
}

int CombatEngine::armPastLife(BattleMap& bm, int idx)
{
    if (!canPastLife(bm, idx)) return 0;
    Agent::Stats st = bm.getAgentStats(idx);
    ++st.past_life_used;
    bm.setAgentStats(idx, st);
    ctx_.past_life_idx_ = idx;
    ctx_.past_life_d6_  = roll(6);
    log_("{}: Knowledge from a Past Life (1d6 = {}; {} use{} left)", agentName(bm, idx),
         ctx_.past_life_d6_, st.pastLifeRemaining(), st.pastLifeRemaining() == 1 ? "" : "s");
    return ctx_.past_life_d6_;
}

bool CombatEngine::spendPastLife(BattleMap& bm, int idx)
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    Agent::Stats st = bm.getAgentStats(idx);
    if (st.pastLifeRemaining() <= 0) return false;
    ++st.past_life_used;
    bm.setAgentStats(idx, st);
    log_("{}: Knowledge from a Past Life spent on a check at the table ({} use{} left)",
         agentName(bm, idx), st.pastLifeRemaining(), st.pastLifeRemaining() == 1 ? "" : "s");
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Lupin (MORE_SPECIES_PLAN.md MS4)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canHowl(const BattleMap& bm, int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_cur <= 0 || s.howlRemaining() <= 0) return false;
    return !bm.getAgentConditions(idx).incapacitated;
}

int CombatEngine::howlDc(const BattleMap& bm, int idx) const noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return 0;
    const Agent::Stats s = bm.getAgentStats(idx);
    return 8 + abilityMod(s.con) + s.prof_bonus;
}

int CombatEngine::useHowl(BattleMap& bm, int idx)
{
    if (!canHowl(bm, idx)) return -1;
    Agent::Stats s = bm.getAgentStats(idx);
    ++s.howl_used;
    bm.setAgentStats(idx, s);
    const int dc = howlDc(bm, idx);
    log_("{} Howls (WIS save DC {}; {} use{} left)", agentName(bm, idx), dc,
         s.howlRemaining(), s.howlRemaining() == 1 ? "" : "s");
    const auto& agents = bm.placedAgents();
    const PlacedAgent& lp = agents[static_cast<std::size_t>(idx)];
    int howled = 0;
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == idx || areAllies(bm, idx, i) || sealedApart(bm, idx, i)) continue;
        const PlacedAgent& tp = agents[static_cast<std::size_t>(i)];
        if (tp.removed_from_play || tp.agent->getStats().hp_cur <= 0) continue;
        const Agent::Conditions tc0 = bm.getAgentConditions(i);
        if (tc0.dead || tc0.deafened) continue;   // "that can hear you"
        if (footprintDistance(lp.origin, lp.agent->getSize(), tp.origin, tp.agent->getSize()) * 5 > 15)
            continue;
        if (rollFixedDcSave(bm, i, SaveWis, dc, "Howl", "")) continue;
        Agent::Conditions tc = bm.getAgentConditions(i);
        tc.howled_by = idx;
        bm.setAgentConditions(i, tc);
        ++howled;
        log_("{} is Howled: Disadvantage on attacks and saves until {}'s next turn",
             agentName(bm, i), agentName(bm, idx));
    }
    return howled;
}

ShoveResult CombatEngine::applyFeralPounce(BattleMap& bm, int attacker_idx, int target_idx, bool knock_prone)
{
    ShoveResult result;
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return result;
    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.feral_pounce_available || ac.feral_pounce_used) return result;   // once per turn
    ac.feral_pounce_available = false;
    ac.feral_pounce_used      = true;
    bm.setAgentConditions(attacker_idx, ac);
    log_("{}: Feral Pounce also Shoves {}", agentName(bm, attacker_idx), agentName(bm, target_idx));
    ShoveAction sa;
    sa.attacker_idx = attacker_idx;
    sa.target_idx   = target_idx;
    sa.knock_prone  = knock_prone;
    return executeShove(bm, sa);
}

int CombatEngine::consumeStrengthenBonus(BattleMap& bm, int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return 0;
    Agent::Stats stats = bm.getAgentStats(idx);
    const int bonus = stats.vampiric_strengthen_bonus;
    if (bonus <= 0) return 0;
    stats.vampiric_strengthen_bonus = 0;
    stats.vampiric_strengthen_turns = 0;
    bm.setAgentStats(idx, stats);
    log_("{} spends Vampiric Bite Strengthen: +{} to this roll", agentName(bm, idx), bonus);
    return bonus;
}


} // namespace rpg
