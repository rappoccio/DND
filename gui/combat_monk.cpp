// ─────────────────────────────────────────────────────────────────────────────
//  combat_monk.cpp  –  CombatEngine Monk features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Mercy, Open Hand, Shadow, Elements.
//  Contents: Flurry of Blows, Stunning Strike, Hand of Harm / Healing, Open Hand rider,
//  Wholeness of Body, Quivering Palm, Shadow Step / Arts, Cloak of Shadows, Elemental
//  Attunement and Burst.
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

// Monk Martial Arts die size by character level (2024 PHB): d6 (1–4), d8 (5–10), d10 (11–16), d12 (17+).
static int martialArtsDieSize(int level) noexcept
{
    if (level >= 17) return 12;
    if (level >= 11) return 10;
    if (level >= 5)  return 8;
    return 6;
}

void CombatEngine::applyHandOfHarmEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                         AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.hand_of_harm_available) return;

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    if (atk_stats.lacksClass(CharacterClass::Monk) ||
        atk_stats.monk_subclass  != WarriorOfMercyPath ||
        atk_stats.classLevel(CharacterClass::Monk) < 3) return;

    const bool free = atk_stats.classLevel(CharacterClass::Monk) >= 11;   // L11 Flurry of Healing and Harm: no Focus Point cost

    // L11: usable any number of times per turn, but only once per target.
    if (free && atk_cond.hand_of_harm_last_target == target_idx) return;

    // Below L11: a Focus Point is required (and the once-per-turn gate is enforced at the eligibility site).
    const Resource* fp = atk_stats.getResource("Focus Points");
    if (!free && (!fp || fp->current <= 0)) return;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // Necrotic damage = one Martial Arts die + WIS modifier (floored for odd negative scores).
    int wis_mod = (atk_stats.wis - 10) / 2;
    if (atk_stats.wis < 10 && (atk_stats.wis - 10) % 2 != 0) --wis_mod;
    int raw = std::max(0, roll(martialArtsDieSize(atk_stats.classLevel(CharacterClass::Monk))) + wis_mod);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Necrotic];
    const int hoh_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"hand of harm", hoh_damage});
    result.total_damage += hoh_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Necrotic);

    int overflow = std::max(0, hoh_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - hoh_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    bm.setAgentStats(target_idx, tgt_stats);

    // Spend a Focus Point unless L11 makes it free; mark Hand of Harm used / record the target.
    if (!free) spendResource(bm, attacker_idx, "Focus Points", 1);
    atk_cond = bm.getAgentConditions(attacker_idx);
    atk_cond.hand_of_harm_used = true;
    atk_cond.hand_of_harm_available = false;
    atk_cond.hand_of_harm_last_target = target_idx;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} adds Hand of Harm: +{} Necrotic damage{}", agentName(bm, attacker_idx), hoh_damage,
         free ? " (free)" : "");

    // L6 Physician's Touch: the target is also Poisoned (until the end of the Monk's next turn — modeled
    // as the Poisoned condition, cleared like other conditions).
    if (atk_stats.classLevel(CharacterClass::Monk) >= 6) {
        applyPoisoned(bm, target_idx);
        log_("{} is Poisoned (Physician's Touch)", agentName(bm, target_idx));
    }

    if (hoh_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, hoh_damage);
        processDamageTaken(bm, target_idx, hoh_damage);
    }
}

HandOfHealingResult CombatEngine::handOfHealing(BattleMap& bm, int monk_idx, int target_idx, bool free) noexcept
{
    HandOfHealingResult res;
    auto agents = bm.placedAgents();
    if (monk_idx   < 0 || monk_idx   >= static_cast<int>(agents.size())) return res;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return res;

    Agent::Stats ms = bm.getAgentStats(monk_idx);
    if (ms.lacksClass(CharacterClass::Monk) ||
        ms.monk_subclass  != WarriorOfMercyPath ||
        ms.classLevel(CharacterClass::Monk) < 3) return res;

    // "free" (no Focus Point, no Bonus Action) is only granted at L11 (Flurry of Healing and Harm),
    // where a Flurry strike may be replaced with a use of Hand of Healing.
    const bool actually_free = free && ms.classLevel(CharacterClass::Monk) >= 11;

    if (!actually_free) {
        if (!hasBonusAction(bm, monk_idx)) return res;
        const Resource* fp = ms.getResource("Focus Points");
        if (!fp || fp->current <= 0) return res;
    }

    res.valid = true;

    // Heal = one Martial Arts die + WIS modifier (floored for odd negative scores; minimum 1).
    int wis_mod = (ms.wis - 10) / 2;
    if (ms.wis < 10 && (ms.wis - 10) % 2 != 0) --wis_mod;
    int amount = std::max(1, roll(martialArtsDieSize(ms.classLevel(CharacterClass::Monk))) + wis_mod);

    int before = bm.getAgentStats(target_idx).hp_cur;
    healAgent(bm, target_idx, amount);
    res.amount_healed = bm.getAgentStats(target_idx).hp_cur - before;

    // L6 Physician's Touch: Hand of Healing also ends one of Blinded/Deafened/Paralyzed/Poisoned/Stunned.
    if (ms.classLevel(CharacterClass::Monk) >= 6) {
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        const char* cleared = nullptr;
        if      (tc.blinded)   { tc.blinded   = false; cleared = "Blinded"; }
        else if (tc.deafened)  { tc.deafened  = false; cleared = "Deafened"; }
        else if (tc.paralyzed) { tc.paralyzed = false; cleared = "Paralyzed"; }
        else if (tc.poisoned)  { tc.poisoned  = false; cleared = "Poisoned"; }
        else if (tc.stunned)   { tc.stunned   = false; cleared = "Stunned"; }
        if (cleared) {
            bm.setAgentConditions(target_idx, tc);
            res.condition_cleared = true;
            res.cleared_condition = cleared;
        }
    }

    // Spend the Focus Point first, then the Bonus Action (spendResource re-reads/writes stats; doing it
    // last would clobber the spendBonusAction decrement). Skipped entirely when folded into a Flurry strike.
    if (!actually_free) {
        spendResource(bm, monk_idx, "Focus Points", 1);
        spendBonusAction(bm, monk_idx);
    }

    log_("{} uses Hand of Healing: {} HP to {}{}{}", agentName(bm, monk_idx), res.amount_healed,
         agentName(bm, target_idx), actually_free ? " (free)" : "",
         res.condition_cleared ? std::format(" — ends {}", res.cleared_condition) : "");
    return res;
}

int CombatEngine::wholenessOfBody(BattleMap& bm, int monk_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (monk_idx < 0 || monk_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats ms = bm.getAgentStats(monk_idx);
    if (ms.lacksClass(CharacterClass::Monk) ||
        ms.monk_subclass  != WarriorOfTheOpenHandPath ||
        ms.classLevel(CharacterClass::Monk) < 6) return 0;

    if (!hasBonusAction(bm, monk_idx)) return 0;
    const Resource* wob = ms.getResource("Wholeness of Body");
    if (!wob || wob->current <= 0) return 0;

    // Heal = one Martial Arts die + WIS modifier (floored for odd negative scores; minimum 1).
    int wis_mod = (ms.wis - 10) / 2;
    if (ms.wis < 10 && (ms.wis - 10) % 2 != 0) --wis_mod;
    int amount = std::max(1, roll(martialArtsDieSize(ms.classLevel(CharacterClass::Monk))) + wis_mod);

    int before = bm.getAgentStats(monk_idx).hp_cur;
    healAgent(bm, monk_idx, amount);
    int healed = bm.getAgentStats(monk_idx).hp_cur - before;

    // Spend the resource first, then the Bonus Action (spendResource re-reads/writes stats; doing it
    // last would clobber the spendBonusAction decrement — mirrors handOfHealing).
    spendResource(bm, monk_idx, "Wholeness of Body", 1);
    spendBonusAction(bm, monk_idx);

    log_("{} uses Wholeness of Body: {} HP restored", agentName(bm, monk_idx), healed);
    return healed;
}

StunningStrikeResult CombatEngine::applyStunningStrike(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    StunningStrikeResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.stunning_strike_available) return res;
    ac.stunning_strike_available = false;
    ac.stunning_strike_used = true;
    bm.setAgentConditions(attacker_idx, ac);
    res.valid = true;

    // Spend 1 Focus Point
    Agent::Stats as = bm.getAgentStats(attacker_idx);
    auto fp = as.getResource("Focus Points");
    if (fp && fp->current > 0) {
        spendResource(bm, attacker_idx, "Focus Points", 1);
    }

    Agent::Stats ts = bm.getAgentStats(target_idx);

    // Save DC = 8 + attacker's DEX mod + proficiency bonus
    int dex_mod = (as.dex - 10) / 2;
    if (as.dex < 10 && (as.dex - 10) % 2 != 0) --dex_mod;
    int dc = 8 + dex_mod + as.prof_bonus;
    res.save_dc = dc;

    // Target CON save (with proficiency), floored correctly for odd negative scores
    int con_mod = (ts.con - 10) / 2;
    if (ts.con < 10 && (ts.con - 10) % 2 != 0) --con_mod;
    if (ts.save_prof_con) con_mod += ts.prof_bonus;
    res.save_roll = roll(20, con_mod);

    if (res.save_roll < dc) {
        // Apply Stunned condition for 1 turn
        ActiveAgentCondition cond;
        cond.agent_idx = target_idx;
        cond.caster_idx = attacker_idx;
        cond.condition_name = "Stunned";
        cond.turns_remaining = 1;
        res.stunned = addAgentCondition(bm, cond) >= 0;   // -1: immune to Stunned
        if (res.stunned)
            log_("{} is Stunned (Stunning Strike — save {} vs DC {})",
                 agentName(bm, target_idx), res.save_roll, dc);
    } else {
        log_("{} resists Stunning Strike (save {} vs DC {})",
             agentName(bm, target_idx), res.save_roll, dc);
    }
    return res;
}

OpenHandRiderResult CombatEngine::applyOpenHandRider(BattleMap& bm, int attacker_idx, int target_idx, int option) noexcept
{
    OpenHandRiderResult res;
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return res;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.open_hand_rider_available) return res;

    bm.setAgentConditions(attacker_idx, ac);
    res.valid = true;
    res.option = option;

    // Spend 1 Focus Point
    Agent::Stats as = bm.getAgentStats(attacker_idx);
    auto fp = as.getResource("Focus Points");
    if (fp && fp->current > 0) {
        spendResource(bm, attacker_idx, "Focus Points", 1);
    }

    Agent::Stats ts = bm.getAgentStats(target_idx);

    if (option == 0) {
        // Knockdown: STR save DC = 8 + attacker's DEX mod + prof, on failure apply Prone
        int dex_mod = (as.dex - 10) / 2;
        if (as.dex < 10 && (as.dex - 10) % 2 != 0) --dex_mod;
        int dc = 8 + dex_mod + as.prof_bonus;
        res.knockdown_save_dc = dc;

        // Target STR save (with proficiency)
        int str_mod = (ts.str - 10) / 2;
        if (ts.str < 10 && (ts.str - 10) % 2 != 0) --str_mod;
        if (ts.save_prof_str) str_mod += ts.prof_bonus;
        res.knockdown_save_roll = roll(20, str_mod);

        if (res.knockdown_save_roll < dc) {
            // Apply Prone condition for 1 turn
            ActiveAgentCondition cond;
            cond.agent_idx = target_idx;
            cond.caster_idx = attacker_idx;
            cond.condition_name = "Prone";
            cond.turns_remaining = 1;
            res.target_knocked_prone = addAgentCondition(bm, cond) >= 0;   // -1: immune to Prone
            if (res.target_knocked_prone)
                log_("{} is knocked Prone (Open Hand Knockdown — save {} vs DC {})",
                     agentName(bm, target_idx), res.knockdown_save_roll, dc);
        } else {
            log_("{} resists Open Hand Knockdown (save {} vs DC {})",
                 agentName(bm, target_idx), res.knockdown_save_roll, dc);
        }
    } else if (option == 1) {
        // Push: forceMoveAgent for 5 feet
        const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
        int cells_moved = bm.forceMoveAgent(target_idx, origin, 5);
        res.push_distance = cells_moved * 5;  // Convert cells to feet
        log_("{} is pushed back {} feet (Open Hand Push)",
             agentName(bm, target_idx), res.push_distance);
    } else if (option == 2) {
        // Deny Reaction: set reaction_used on target
        Agent::Conditions tc = bm.getAgentConditions(target_idx);
        tc.reaction_used = true;
        bm.setAgentConditions(target_idx, tc);
        res.reaction_denied = true;
        log_("{} cannot use a reaction (Open Hand Deny Reaction)",
             agentName(bm, target_idx));
    }

    return res;
}

FlurryResult CombatEngine::executeFlurryOfBlows(BattleMap& bm, int attacker_idx, int target_idx, int rider_option) noexcept
{
    FlurryResult result;
    const Agent::Stats& stats = bm.getAgentStats(attacker_idx);

    // L10 Heightened Focus: Flurry grants 3 strikes instead of 2
    int num_flurry_attacks = (stats.classLevel(CharacterClass::Monk) >= 10 && stats.hasClass(CharacterClass::Monk)) ? 3 : 2;

    // L11 Warrior of Mercy — Flurry of Healing and Harm: each Flurry strike that hits also delivers a free
    // Hand of Harm (no Focus Point), capped at once per target by applyHandOfHarmEffect itself.
    const bool mercy_flurry_harm =
        stats.hasClass(CharacterClass::Monk) &&
        stats.monk_subclass  == WarriorOfMercyPath && stats.classLevel(CharacterClass::Monk) >= 11;

    auto apply_riders = [&](AttackResult& atk_result, OpenHandRiderResult& rider) {
        if (!atk_result.valid || !atk_result.hit) return;
        if (rider_option >= 0 && rider_option <= 2) {
            if (bm.getAgentConditions(attacker_idx).open_hand_rider_available)
                rider = applyOpenHandRider(bm, attacker_idx, target_idx, rider_option);
        }
        if (mercy_flurry_harm && bm.getAgentConditions(attacker_idx).hand_of_harm_available)
            applyHandOfHarmEffect(bm, attacker_idx, target_idx, atk_result);
    };

    // Execute first attack
    Attack atk1(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk1.is_offhand = true;
    atk1.attack_slot = "bonus";
    result.attack1 = executeAction(bm, atk1);
    apply_riders(result.attack1, result.rider1);

    // Execute second attack
    Attack atk2(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
    atk2.is_offhand = true;
    atk2.attack_slot = "bonus";
    result.attack2 = executeAction(bm, atk2);
    apply_riders(result.attack2, result.rider2);

    // Execute third attack if L10+ (Heightened Focus)
    if (num_flurry_attacks >= 3) {
        Attack atk3(attacker_idx, target_idx, 0);  // weapon 0 = unarmed
        atk3.is_offhand = true;
        atk3.attack_slot = "bonus";
        result.attack3 = executeAction(bm, atk3);
        apply_riders(result.attack3, result.rider3);
    }

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    ac.open_hand_rider_available = false;
    ac.hand_of_harm_available = false;
    bm.setAgentConditions(attacker_idx, ac);
    return result;
}

namespace {
    // File-local damage-type name for log lines (combat_attack.cpp's magicDamageName is in its own
    // anonymous namespace and not visible here). Only the elemental types are used by the Monk's
    // Warrior of the Elements features, but cover the full enum for safety.
    const char* elementName(MagicDamage_t t) noexcept {
        switch (t) {
            case Acid:      return "Acid";
            case Cold:      return "Cold";
            case Fire:      return "Fire";
            case Force:     return "Force";
            case Lightning: return "Lightning";
            case Necrotic:  return "Necrotic";
            case Poison:    return "Poison";
            case Psychic:   return "Psychic";
            case Radiant:   return "Radiant";
            case Thunder:   return "Thunder";
            default:        return "Magic";
        }
    }
}

// Warrior of Shadow Monk — Shadow Step (L6+): a Bonus Action teleport. Spend 0 resources.
// Teleport up to 30 feet in dim light or darkness (L6). At L11, can teleport from any light level.
// On successful teleport, set shadow_step_advantage flag for Advantage on next attack this turn.
bool CombatEngine::shadowStepTeleport(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Monk) ||
        s.monk_subclass != WarriorOfShadowPath || s.classLevel(CharacterClass::Monk) < 6) return false;

    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    const int max_ft = 30;  // Fixed 30 ft range
    if (dcells * 5 > max_ft) {
        log_("{}: Shadow Step destination too far ({} ft > {} ft)",
             agentName(bm, idx), dcells * 5, max_ft);
        return false;
    }

    // L6 gate: must be in dim or dark light
    if (s.classLevel(CharacterClass::Monk) < 11) {
        VisibilityLevel light = bm.getLightLevel(from);
        if (light != VisibilityLevel::Dim && light != VisibilityLevel::Dark &&
            light != VisibilityLevel::MagicalDark) {
            log_("{}: Shadow Step requires dim light or darkness (currently in bright light)",
                 agentName(bm, idx));
            return false;
        }
    }
    // L11+: no light gate — can teleport from any light level

    if (!teleportAgent(bm, idx, target_col, target_row)) return false;

    // Set Advantage flag for next attack this turn
    Agent::Conditions c = bm.getAgentConditions(idx);
    c.shadow_step_advantage = true;
    // L11 Improved Shadow Step: the Advantage attack also gains +5 ft reach.
    if (s.classLevel(CharacterClass::Monk) >= 11) c.bonus_reach_available = true;
    bm.setAgentConditions(idx, c);

    log_("{}: Shadow Step — teleports {} ft, next attack has Advantage{}",
         agentName(bm, idx), dcells * 5,
         s.classLevel(CharacterClass::Monk) >= 11 ? " and +5 ft reach" : "");
    return true;
}

// Warrior of Shadow Monk — Cloak of Shadows (L17): a Bonus Action. Gain Invisible in dim/dark.
// Invisibility persists through attacks (doesn't end on action like standard Invisibility).
// Expires on turn start if in bright light, or at end of turn naturally.
bool CombatEngine::cloakOfShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Monk) ||
        s.monk_subclass != WarriorOfShadowPath || s.classLevel(CharacterClass::Monk) < 17) return false;

    // Must be in dim or dark light
    VisibilityLevel light = bm.getLightLevel(agents[static_cast<std::size_t>(idx)].origin);
    if (light != VisibilityLevel::Dim && light != VisibilityLevel::Dark &&
        light != VisibilityLevel::MagicalDark) {
        log_("{}: Cloak of Shadows requires dim light or darkness",
             agentName(bm, idx));
        return false;
    }

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = true;  // Shadow Step: persists through attacks (unlike standard Invisibility)
    c.cloak_of_shadows_active = true;
    bm.setAgentConditions(idx, c);
    log_("{}: Cloak of Shadows — becomes Invisible", agentName(bm, idx));
    return true;
}

// Warrior of Shadow Monk — Shadow Arts: Darkness (L3): spend 1 Focus Point to fill a 15-ft-radius
// Sphere (centered on the chosen point) with magical Darkness for 1 minute (10 rounds). The light
// effect is tagged see-through for the casting Monk, so getLightLevelFor() reports it as transparent
// to them — they are NOT Blinded by their own Darkness, while other creatures inside without Devil's
// Sight gain the Blinded condition. Returns the new light-effect id (>= 0) on success, -1 on failure.
int CombatEngine::shadowArtsDarkness(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Monk) ||
        s.monk_subclass != WarriorOfShadowPath || s.classLevel(CharacterClass::Monk) < 3) return -1;
    Resource* fp = s.getResource("Focus Points");
    if (!fp || fp->current < 1) {
        log_("{}: Shadow Arts: Darkness requires 1 Focus Point", agentName(bm, idx));
        return -1;
    }

    // The Sphere is blocked by Total Cover: the darkness pools where the target point can see,
    // and doesn't seep through a wall into the next room.
    std::vector<Cell> cells = bm.pruneBlockedCells(
        AreaOrigin{Cell{target_col, target_row}, 1},
        sphereCellsAround(target_col, target_row, 15));
    int light_id = bm.placeLightEffect("Shadow Arts: Darkness", cells,
                                       VisibilityLevel::MagicalDark, 10, idx, /*see_through=*/idx);
    if (light_id < 0) {
        log_("{}: Shadow Arts: Darkness — no valid cells at the target point", agentName(bm, idx));
        return -1;
    }

    spendResource(bm, idx, "Focus Points", 1);
    log_("{}: Shadow Arts: Darkness — a 15 ft Sphere of magical Darkness fills the area (sees through it)",
         agentName(bm, idx));

    // Re-evaluate darkness-blinding for any agent now standing inside the Sphere: those without
    // Devil's Sight are Blinded; the caster's see-through tag keeps them sighted.
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        const Cell origin = agents[static_cast<std::size_t>(i)].origin;
        if (std::find(cells.begin(), cells.end(), origin) != cells.end())
            updateDarknessBlinding(bm, i);
    }
    return light_id;
}

// Monk Martial Arts die COUNT for Warrior of the Elements — Elemental Burst (2024 PHB): the number of
// d8s the burst rolls scales with tier. Mirrors martialArtsDieSize's breakpoints: 2 (≤10), 3 (11–16),
// 4 (17+). Elemental Burst is L6+, so only the 2/3/4 values are reachable.
static int martialArtsDieCount(int level) noexcept
{
    if (level >= 17) return 4;
    if (level >= 11) return 3;
    return 2;
}

// Warrior of the Elements — Elemental Attunement (L3): a Magic action; spend 1 Focus Point to attune to
// a chosen element for the rest of the encounter (the sim doesn't track the 10-min duration; cleared on a
// short/long rest). While active: unarmed strikes reach +10 ft, deal the chosen element, and can push or
// pull the target 10 ft on a hit. `element` is a MagicDamage_t value; only the five elemental types are
// legal (Acid/Cold/Fire/Lightning/Thunder).
bool CombatEngine::activateElementalAttunement(BattleMap& bm, int idx, int element) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Monk) ||
        s.monk_subclass != WarriorOfFourElementsPath || s.classLevel(CharacterClass::Monk) < 3) return false;
    if (element != Acid && element != Cold && element != Fire &&
        element != Lightning && element != Thunder) {
        log_("{}: Elemental Attunement requires an elemental damage type", agentName(bm, idx));
        return false;
    }
    Resource* fp = s.getResource("Focus Points");
    if (!fp || fp->current < 1) {
        log_("{}: Elemental Attunement requires 1 Focus Point", agentName(bm, idx));
        return false;
    }

    s.unarmed_damage_override = element;
    bm.setAgentStats(idx, s);

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.elemental_attunement_active = true;
    bm.setAgentConditions(idx, c);

    spendResource(bm, idx, "Focus Points", 1);
    log_("{}: Elemental Attunement — attunes to {} (unarmed strikes gain +10 ft reach, deal {}, and can push/pull 10 ft)",
         agentName(bm, idx), elementName(static_cast<MagicDamage_t>(element)),
         elementName(static_cast<MagicDamage_t>(element)));
    return true;
}

// Elemental Attunement push/pull rider: while attunement is active, an unarmed hit can push the target
// 10 ft away from the Monk (pull=false) or pull it 10 ft toward the Monk (pull=true). No save (2024).
int CombatEngine::elementalAttunementMove(BattleMap& bm, int attacker_idx, int target_idx, bool pull) noexcept
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return 0;
    if (target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return 0;
    if (attacker_idx == target_idx) return 0;

    const auto& puller = agents[static_cast<std::size_t>(attacker_idx)];
    const Cell from = puller.origin;
    // Pass the Monk's footprint so a pull stops adjacent to it rather than through it.
    int cells_moved = bm.forceMoveAgent(target_idx, from, 10, pull, puller.agent->getSize());
    int ft = cells_moved * 5;
    if (ft > 0) {
        log_("{}: Elemental Attunement {} {} {} ft",
             agentName(bm, attacker_idx), pull ? "pulls" : "pushes",
             agentName(bm, target_idx), ft);
    } else {
        log_("{}: Elemental Attunement could not {} {} (blocked)",
             agentName(bm, attacker_idx), pull ? "pull" : "push", agentName(bm, target_idx));
    }
    return ft;
}

// Warrior of the Elements — Elemental Burst (L6): a Magic action; spend 2 Focus Points to detonate a
// 20-ft-radius Sphere of the chosen element centered on (target_col, target_row). Every creature in the
// area (the caster's allies are spared — faction-aware) makes a DEX save vs the Monk's Ki DC; on a fail
// it takes (Martial Arts die count) × d8 of the chosen element, half on a success.
bool CombatEngine::elementalBurst(BattleMap& bm, int idx, int target_col, int target_row, int element) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats cs = bm.getAgentStats(idx);
    if (cs.lacksClass(CharacterClass::Monk) ||
        cs.monk_subclass != WarriorOfFourElementsPath || cs.classLevel(CharacterClass::Monk) < 6) return false;
    if (element != Acid && element != Cold && element != Fire &&
        element != Lightning && element != Thunder) {
        log_("{}: Elemental Burst requires an elemental damage type", agentName(bm, idx));
        return false;
    }
    Resource* fp = cs.getResource("Focus Points");
    if (!fp || fp->current < 2) {
        log_("{}: Elemental Burst requires 2 Focus Points", agentName(bm, idx));
        return false;
    }

    const auto mt  = static_cast<MagicDamage_t>(element);
    const int  dc  = rules::spellSaveDcFromAbility(cs, SaveWis);   // Monk Ki DC = 8 + PB + WIS
    const int  num = martialArtsDieCount(cs.classLevel(CharacterClass::Monk));

    spendResource(bm, idx, "Focus Points", 2);
    log_("{}: Elemental Burst — a 20 ft Sphere of {} erupts (DC {} DEX save, {}d8)",
         agentName(bm, idx), elementName(mt), dc, num);

    // Blocked by Total Cover, like every other Sphere — a creature behind a wall is spared.
    std::vector<Cell> cells = bm.pruneBlockedCells(
        AreaOrigin{Cell{target_col, target_row}, 1},
        sphereCellsAround(target_col, target_row, 20));
    for (int t = 0; t < static_cast<int>(agents.size()); ++t) {
        if (t == idx) continue;                              // the caster is never in their own burst
        if (areAllies(bm, idx, t)) continue;                 // faction-aware: spare allies
        const Cell torigin = agents[static_cast<std::size_t>(t)].origin;
        if (std::find(cells.begin(), cells.end(), torigin) == cells.end()) continue;

        Agent::Stats ts = bm.getAgentStats(t);
        if (ts.hp_max == 0 && ts.hp_cur == 0) continue;      // not a real combatant

        int rolled = 0;
        for (int i = 0; i < num; ++i) rolled += roll(8);
        float multiplier = effectiveMagicDamageMult(cs, ts, mt, true);
        int dmg = static_cast<int>(static_cast<float>(rolled) * multiplier);

        int save_d20  = roll(20);
        int save_mod  = saveModFor(bm, t, SaveDex);
        int save_tot  = applyIndomitableMight(bm, t, SaveDex, save_d20 + save_mod);
        bool saved    = (save_tot >= dc);

        // Rogue Evasion (L7+): DEX save success = no damage, failure = half.
        if (ts.hasClass(CharacterClass::Rogue) && ts.classLevel(CharacterClass::Rogue) >= 7) {
            dmg = saved ? 0 : (dmg / 2);
        } else if (saved) {
            dmg /= 2;
        }

        log_("{} {} the Elemental Burst ({} vs DC {}) — takes {} {}",
             agentName(bm, t), saved ? "saves vs" : "fails", save_tot, dc, dmg, elementName(mt));

        if (dmg > 0) {
            // Apply the damage: temp HP first, then real HP (mirrors applyHandOfHarmEffect).
            int overflow = std::max(0, dmg - ts.temp_hp);
            ts.temp_hp = std::max(0, ts.temp_hp - dmg);
            ts.hp_cur  = std::clamp(ts.hp_cur - overflow, 0, ts.hp_max);
            bm.setAgentStats(t, ts);

            checkConcentrationOnDamage(bm, t, dmg);
            processDamageTaken(bm, t, dmg);   // on-damage condition triggers (Sleep end, re-saves, ...)
            if (ts.hp_cur <= 0) {
                Agent::Conditions tc = bm.getAgentConditions(t);
                if (!tc.unconscious && !tc.dead) applyUnconscious(bm, t);
            }
        }
    }
    return true;
}

// Monk Way of the Open Hand L17 — Quivering Palm. After an Unarmed Strike hit, the monk spends 4
// Focus Points to plant imperceptible vibrations in the target. They do nothing until detonated: the
// monk later takes an action (triggerDelayedEffect) to force a CON save vs the Monk's Ki DC for 10d12
// Force damage (half on a success). Only one creature can carry this monk's vibrations at a time, so
// any prior ones are ended first. Built entirely on the general delayed-trigger condition mechanism;
// future stored-effect abilities (e.g. Delayed Blast Fireball) construct the same condition shape.
bool CombatEngine::plantQuiveringPalm(BattleMap& bm, int monk_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (monk_idx < 0 || monk_idx >= n || target_idx < 0 || target_idx >= n) return false;

    Agent::Stats ms = bm.getAgentStats(monk_idx);
    if (ms.lacksClass(CharacterClass::Monk) ||
        ms.monk_subclass != WarriorOfTheOpenHandPath || ms.classLevel(CharacterClass::Monk) < 17) {
        log_("{}: Quivering Palm requires Warrior of the Open Hand (L17)", agentName(bm, monk_idx));
        return false;
    }
    Resource* fp = ms.getResource("Focus Points");
    if (!fp || fp->current < 4) {
        log_("{}: Quivering Palm requires 4 Focus Points", agentName(bm, monk_idx));
        return false;
    }

    // Only one creature may carry this monk's vibrations at a time — end any prior ones harmlessly.
    std::vector<int> stale;
    for (const auto& c : conditions_.all())
        if (c.delayed_trigger && c.caster_idx == monk_idx && c.condition_name == "QuiveringPalm")
            stale.push_back(c.condition_id);
    for (int id : stale) removeAgentCondition(bm, id);

    spendResource(bm, monk_idx, "Focus Points", 4);

    ActiveAgentCondition cond;
    cond.agent_idx           = target_idx;
    cond.caster_idx          = monk_idx;
    cond.condition_name      = "QuiveringPalm";
    cond.turns_remaining     = 100000;       // "days equal to your Monk level" — effectively whole battle
    cond.delayed_trigger     = true;
    cond.delay_dice          = 10;
    cond.delay_die_size      = 12;
    cond.delay_damage_type   = MagicDamage_t::Force;
    cond.delay_requires_save = true;
    cond.save_ability        = SaveCon;
    cond.save_dc             = rules::spellSaveDcFromAbility(ms, SaveWis);  // Monk Ki DC = 8 + PB + WIS
    cond.delay_half_on_save  = true;
    cond.delay_auto_on_expire = false;       // monk chooses when to detonate; never auto-fires
    cond.delay_label         = "Quivering Palm";

    int id = addAgentCondition(bm, cond);
    log_("{} plants Quivering Palm in {} (4 Focus; detonate → 10d12 Force, DC {} CON save) [id {}]",
         agentName(bm, monk_idx), agentName(bm, target_idx), cond.save_dc, id);
    return true;
}

} // namespace rpg
