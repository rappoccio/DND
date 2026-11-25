// ─────────────────────────────────────────────────────────────────────────────
//  combat_warlock.cpp  –  CombatEngine Warlock features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Archfey, Celestial, Great Old One.
//  Contents: Eldritch Smite, One with Shadows (invocation), Steps of the Fey, Bewitching Magic,
//  Clairvoyant Combatant, Searing Vengeance, Magical Cunning, Healing Light.
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

int CombatEngine::applyEldritchSmiteEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                           int slot_level, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.eldritch_smite_available || atk_cond.eldritch_smite_used) return -1;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    // Must still have a bonus action, the pact slot, and no leveled spell already this turn.
    if (!hasBonusAction(bm, attacker_idx)) return -1;
    if (atk_stats.leveled_spell_cast_this_turn) return -1;
    const auto si = static_cast<std::size_t>(slot_level - 1);
    if (atk_stats.spell_slots_remaining[si] <= 0) return -1;

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // (slot_level + 1)d8 Force damage.
    const int dice = slot_level + 1;
    int raw = 0;
    for (int i = 0; i < dice; ++i) raw += roll(8);

    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Force];
    const int smite_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"eldritch smite", smite_damage});
    result.total_damage += smite_damage;
    result.magic_damage_types.push_back(MagicDamage_t::Force);

    int overflow = std::max(0, smite_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - smite_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    bm.setAgentStats(target_idx, tgt_stats);

    // Spend the pact slot, the bonus action, and mark the leveled-spell + once-per-turn interlocks.
    atk_stats.spell_slots_remaining[si] -= 1;
    atk_stats.leveled_spell_cast_this_turn = true;
    bm.setAgentStats(attacker_idx, atk_stats);
    (void)spendBonusAction(bm, attacker_idx);

    atk_cond.eldritch_smite_used = true;
    atk_cond.eldritch_smite_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} uses Eldritch Smite (level {} pact slot): +{} Force damage",
         agentName(bm, attacker_idx), slot_level, smite_damage);

    // Knock a Huge-or-smaller target Prone. getSize() is the grid footprint in cells
    // (Medium/Small=1, Large=2, Huge=3, Gargantuan=4), so Huge-or-smaller is <= 3 — the same
    // convention the Push mastery uses for "Large or smaller" (<= 2). Skip if already down.
    if (!result.target_down) {
        Agent::Conditions tgt_cond = bm.getAgentConditions(target_idx);
        const int tgt_sz = agents[static_cast<std::size_t>(target_idx)].agent->getSize();
        if (tgt_sz <= 3 && !tgt_cond.prone && !conditionImmune(bm, target_idx, "Prone")) {
            tgt_cond.prone = true;
            bm.setAgentConditions(target_idx, tgt_cond);
            log_("{} is knocked Prone (Eldritch Smite)", agentName(bm, target_idx));
        }
    }

    // The extra damage can break concentration and trigger on-damage conditions.
    if (smite_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, smite_damage);
        processDamageTaken(bm, target_idx, smite_damage);
    }
    return smite_damage;
}

bool CombatEngine::applyOneWithShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& s = pa.agent->getStats();
    if (s.lacksClass(CharacterClass::Warlock) || !s.hasInvocation(8)) return false;

    // Must be standing in an area of Dim Light or Darkness (the light level at the cell —
    // not the obscuration-effect layer, which is for fog/magical-darkness AoEs).
    VisibilityLevel light = bm.getLightLevel(pa.origin);
    if (light != VisibilityLevel::Dim && light != VisibilityLevel::Dark &&
        light != VisibilityLevel::MagicalDark)
        return false;

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = false;  // free Invisibility — ends on the Warlock's next attack/cast
    bm.setAgentConditions(idx, c);
    log_("{}: One with Shadows — gains the Invisible condition", agentName(bm, idx));
    return true;
}

// Steps of the Fey (Archfey Warlock L3): cast Misty Step (30-ft Bonus-Action teleport) without a slot,
// spending one "Steps of the Fey" use. Each cast may attach one additional effect:
//   effect 0 = None          — plain teleport.
//   effect 1 = Refreshing    — the warlock gains 1d10 Temporary HP. (RAW allows an ally within 10 ft;
//                              v1 applies it to the warlock — the common case.)
//   effect 2 = Taunting      — creatures within 5 ft of the space left make a WIS save vs the warlock's
//                              CHA DC or have Disadvantage attacking anyone but the warlock until the
//                              start of the warlock's next turn (directed "FeyTaunt" mark).
//   effect 3 = Disappearing  — (L6+) the warlock gains the Invisible condition (ends on attack/cast).
//   effect 4 = Dreadful      — (L6+) creatures within 5 ft of the space left make a WIS save or take
//                              2d10 Psychic damage.
bool CombatEngine::stepsOfTheFey(BattleMap& bm, int idx, int target_col, int target_row,
                                 int effect, bool as_reaction) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Warlock) ||
        s.warlock_subclass != ArchfeyPath || s.classLevel(CharacterClass::Warlock) < 3) return false;

    // Misty Escape (L6): casting Misty Step reactively (in response to taking damage) requires L6+.
    if (as_reaction && s.classLevel(CharacterClass::Warlock) < 6) {
        log_("{}: Misty Escape (reaction Misty Step) unlocks at Warlock level 6", agentName(bm, idx));
        return false;
    }

    // L6+ gate for the Disappearing / Dreadful step options.
    if ((effect == 3 || effect == 4) && s.classLevel(CharacterClass::Warlock) < 6) {
        log_("{}: that Steps of the Fey option unlocks at Warlock level 6", agentName(bm, idx));
        return false;
    }

    Resource* steps = s.getResource("Steps of the Fey");
    if (!steps || steps->current <= 0) {
        log_("{} has no Steps of the Fey uses left", agentName(bm, idx));
        return false;
    }

    // Timing: normally a Bonus Action; Misty Escape spends the Reaction instead.
    Agent::Conditions rc = bm.getAgentConditions(idx);
    if (as_reaction) {
        if (!canTakeReaction(rc)) {
            log_("{} has no reaction available for Misty Escape", agentName(bm, idx));
            return false;
        }
    } else if (!hasBonusAction(bm, idx)) {
        return false;
    }

    // Misty Step range = 30 ft (Chebyshev cells × 5).
    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    if (dcells * 5 > 30) {
        log_("{}: Steps of the Fey destination too far ({} ft > 30 ft)", agentName(bm, idx), dcells * 5);
        return false;
    }

    // Teleport first — a blocked/occupied destination must not waste the use or the action.
    if (!teleportAgent(bm, idx, target_col, target_row)) return false;

    // Spend the use + the action (re-fetch stats: teleportAgent may re-persist the caster's slot).
    s = bm.getAgentStats(idx);
    steps = s.getResource("Steps of the Fey");
    if (steps) steps->spend(1);
    bm.setAgentStats(idx, s);
    if (as_reaction) {
        rc = bm.getAgentConditions(idx);
        rc.reaction_used = true;
        bm.setAgentConditions(idx, rc);
        log_("{}: Misty Escape — casts Misty Step as a Reaction ({} ft)", agentName(bm, idx), dcells * 5);
    } else {
        spendBonusAction(bm, idx);
        log_("{}: Steps of the Fey — casts Misty Step ({} ft)", agentName(bm, idx), dcells * 5);
    }

    applyStepsOfFeyRider(bm, idx, from, effect);
    return true;
}

// Shared "additional effect" rider for a Steps of the Fey / Misty Escape / Bewitching Magic Misty Step.
// `from` is the square the warlock LEFT (Taunting/Dreadful key off it). effect: 1 Refreshing, 2 Taunting,
// 3 Disappearing, 4 Dreadful (0 = no rider). Caller has already gated the L6 options + teleported.
void CombatEngine::applyStepsOfFeyRider(BattleMap& bm, int idx, const Cell& from, int effect) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;
    const int save_dc = rules::spellSaveDcFromAbility(bm.getAgentStats(idx), SaveCha);

    if (effect == 1) {
        // Refreshing Step: 1d10 Temporary HP to the warlock.
        const int thp = roll(10);
        Agent::Stats gs = bm.getAgentStats(idx);
        grantTempHp(gs, thp);
        bm.setAgentStats(idx, gs);
        log_("Refreshing Step: {} gains {} temporary HP", agentName(bm, idx), thp);
    } else if (effect == 2 || effect == 4) {
        // Taunting / Dreadful: affect creatures within 5 ft of the space the warlock LEFT.
        for (std::size_t i = 0; i < agents.size(); ++i) {
            const int tgt = static_cast<int>(i);
            if (tgt == idx) continue;
            const PlacedAgent& tp = agents[i];
            const int dc_cells = std::max(std::abs(tp.origin.col - from.col),
                                          std::abs(tp.origin.row - from.row));
            if (dc_cells > 1) continue;                     // within 5 ft of the departed square
            Agent::Stats ts = bm.getAgentStats(tgt);
            if (ts.hp_cur <= 0) continue;

            const int save_mod = saveModFor(bm, tgt, SaveWis);
            const int save_d20 = roll(20);
            const bool failed = save_d20 + save_mod < save_dc;
            log_("{} makes a WIS save vs Steps of the Fey (DC {}): {} + {} = {} ({})",
                 agentName(bm, tgt), save_dc, save_d20, save_mod, save_d20 + save_mod,
                 failed ? "FAILED" : "PASSED");
            if (!failed) continue;

            if (effect == 2) {
                // Taunting Step: directed mark — Disadvantage attacking anyone but the warlock, until
                // the start of the warlock's next turn (ticked on the warlock's turns, like Clairvoyant).
                ActiveAgentCondition aac{};
                aac.agent_idx       = tgt;
                aac.condition_name  = "FeyTaunt";
                aac.caster_idx      = idx;
                aac.turns_remaining = 1;
                (void)addAgentCondition(bm, aac);
                log_("Taunting Step: {} has Disadvantage attacking anyone but {}",
                     agentName(bm, tgt), agentName(bm, idx));
            } else {
                // Dreadful Step: 2d10 Psychic.
                int dmg = roll(10) + roll(10);
                dmg = std::max(0, static_cast<int>(std::lround(
                          static_cast<double>(dmg) * ts.get_magic_damage_multiplier(7 /* Psychic */))));
                if (dmg > 0) {
                    damageAgent(bm, tgt, dmg);
                    checkConcentrationOnDamage(bm, tgt, dmg, idx);
                    log_("Dreadful Step: {} takes {} psychic damage", agentName(bm, tgt), dmg);
                }
            }
        }
    } else if (effect == 3) {
        // Disappearing Step: the warlock gains the Invisible condition (ends on attack/cast).
        Agent::Conditions c = bm.getAgentConditions(idx);
        c.invisible = true;
        c.invisible_persists_on_action = false;
        bm.setAgentConditions(idx, c);
        log_("Disappearing Step: {} becomes Invisible", agentName(bm, idx));
    }
}

// Bewitching Magic (Archfey Warlock L14): immediately after casting an Enchantment or Illusion spell
// with an action and a slot, cast Misty Step as part of the same action WITHOUT expending a slot (and
// with no Steps of the Fey use / action cost). The GUI gates on the "just cast Enchantment/Illusion"
// timing; here we validate patron/level + range, teleport, and apply the chosen Steps of the Fey rider.
bool CombatEngine::bewitchingMistyStep(BattleMap& bm, int idx, int target_col, int target_row,
                                       int effect) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Warlock) ||
        s.warlock_subclass != ArchfeyPath || s.classLevel(CharacterClass::Warlock) < 14) return false;

    // The Disappearing / Dreadful riders are L6+ — always satisfied at L14, but keep the shared gate.
    if ((effect == 3 || effect == 4) && s.classLevel(CharacterClass::Warlock) < 6) return false;

    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    if (dcells * 5 > 30) {
        log_("{}: Bewitching Magic Misty Step destination too far ({} ft > 30 ft)",
             agentName(bm, idx), dcells * 5);
        return false;
    }
    if (!teleportAgent(bm, idx, target_col, target_row)) return false;
    log_("{}: Bewitching Magic — casts a free Misty Step ({} ft)", agentName(bm, idx), dcells * 5);
    applyStepsOfFeyRider(bm, idx, from, effect);
    return true;
}

bool CombatEngine::activateClairvoyantCombatant(BattleMap& bm, int warlock_idx, int target_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (warlock_idx < 0 || warlock_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx == warlock_idx) return false;

    Agent::Stats stats = bm.getAgentStats(warlock_idx);

    // Gate on Great Old One L6+
    if (stats.lacksClass(CharacterClass::Warlock) ||
        stats.warlock_subclass != GreatOldOnePath ||
        stats.classLevel(CharacterClass::Warlock) < 6) {
        return false;
    }

    if (!hasBonusAction(bm, warlock_idx)) return false;

    // Cost: one "Clairvoyant Combatant" use, or — when exhausted — a Pact Magic spell slot.
    // Pact slots all sit at the warlock's pact slot level (spell_slots_remaining is a per-level array).
    Resource* cc = stats.getResource("Clairvoyant Combatant");
    const bool has_use = cc && cc->current > 0;
    const int  psl = stats.pact_slot_level();
    const bool can_spend_slot =
        psl >= 1 && stats.spell_slots_remaining[static_cast<std::size_t>(psl - 1)] > 0;
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Clairvoyant Combatant (no use or Pact slot available)",
             agentName(bm, warlock_idx));
        return false;
    }

    // Range: within 60 ft and in line of sight (telepathic contact requires perceiving the creature).
    const PlacedAgent& wp = agents[static_cast<std::size_t>(warlock_idx)];
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    const int dist_ft = footprintDistance(wp.origin, wp.agent->getSize(),
                                          tp.origin, tp.agent->getSize()) * 5;
    if (dist_ft > 60) {
        log_("{} is more than 60 ft away — Clairvoyant Combatant fails", agentName(bm, target_idx));
        return false;
    }
    if (!bm.hasLineOfSight(wp.origin, wp.agent->getSize(), tp.origin, tp.agent->getSize())) {
        log_("{} can't see {} — Clairvoyant Combatant fails",
             agentName(bm, warlock_idx), agentName(bm, target_idx));
        return false;
    }

    // Spend the cost (use first, else a Pact slot), then persist before spending the bonus action.
    if (has_use) {
        cc->spend(1);
        stats.resources["Clairvoyant Combatant"] = *cc;
    } else {
        stats.spell_slots_remaining[static_cast<std::size_t>(psl - 1)] -= 1;
        log_("{} spends a Pact Magic slot to reuse Clairvoyant Combatant", agentName(bm, warlock_idx));
    }
    bm.setAgentStats(warlock_idx, stats);
    spendBonusAction(bm, warlock_idx);

    // Force a WIS save vs the warlock's CHA spell save DC.
    const int save_dc  = rules::spellSaveDcFromAbility(stats, SaveCha);
    const int save_mod = saveModFor(bm, target_idx, SaveWis);
    const int save_d20 = roll(20);
    const int save_total = save_d20 + save_mod;
    const bool failed = save_total < save_dc;

    log_("{} makes a WIS save vs Clairvoyant Combatant (DC {}): {} + {} = {} ({})",
         agentName(bm, target_idx), save_dc, save_d20, save_mod, save_total,
         failed ? "FAILED" : "PASSED");

    if (failed) {
        // Directed mark, ticked on the warlock's turns: expires at the start of the warlock's next turn.
        ActiveAgentCondition aac{};
        aac.agent_idx      = target_idx;
        aac.condition_name = "ClairvoyantCombatant";
        aac.caster_idx     = warlock_idx;
        aac.turns_remaining = 1;  // until the start of the warlock's next turn
        (void)addAgentCondition(bm, aac);
        log_("Clairvoyant Combatant: {} has Advantage vs {} (who has Disadvantage back) until its next turn",
             agentName(bm, warlock_idx), agentName(bm, target_idx));
    }

    return true;
}

bool CombatEngine::triggerSearingVengeance(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Warlock) ||
        stats.warlock_subclass != CelestialPath || stats.classLevel(CharacterClass::Warlock) < 14) return false;
    Resource* sv = stats.getResource("Searing Vengeance");
    if (!sv || sv->current <= 0) return false;

    sv->spend(1);                                   // once per long rest
    stats.hp_cur = std::max(1, stats.hp_max / 2);   // spring back with half HP maximum
    bm.setAgentStats(idx, stats);                   // persists the resource spend (ptr into stats.resources) + HP

    // Clear the dying state: conscious again, on your feet, death-save tally reset.
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.unconscious          = false;
    cond.stabilized           = false;
    cond.prone                = false;              // "spring back to your feet"
    cond.death_save_successes = 0;
    cond.death_save_failures  = 0;
    bm.setAgentConditions(idx, cond);

    int cha_mod = (stats.cha - 10) / 2;
    if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --cha_mod;

    const int origin_col = agents[static_cast<std::size_t>(idx)].origin.col;
    const int origin_row = agents[static_cast<std::size_t>(idx)].origin.row;

    log_("{}: Searing Vengeance! Springs back to {} HP in a radiant burst",
         agentName(bm, idx), stats.hp_cur);

    // 30-ft radiant emanation: each enemy takes 2d8 + CHA radiant and is Blinded until the end of
    // the warlock's next turn.
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int tgt = static_cast<int>(i);
        if (tgt == idx) continue;
        if (areAllies(bm, idx, tgt)) continue;       // enemies of the warlock's choice (auto: all enemies)

        const PlacedAgent& tp = agents[i];
        const float dx = static_cast<float>(tp.origin.col - origin_col);
        const float dy = static_cast<float>(tp.origin.row - origin_row);
        if (std::sqrt(dx * dx + dy * dy) * 5.0f > 30.0f) continue;

        Agent::Stats ts = bm.getAgentStats(tgt);
        if (ts.hp_cur <= 0) continue;                // skip the already-downed

        int dmg = roll(8) + roll(8) + cha_mod;
        dmg = std::max(0, static_cast<int>(std::lround(
                  static_cast<double>(dmg) * ts.get_magic_damage_multiplier(8 /* Radiant */))));
        if (dmg > 0) {
            damageAgent(bm, tgt, dmg);
            checkConcentrationOnDamage(bm, tgt, dmg, idx);
            log_("Searing Vengeance: {} takes {} radiant damage", agentName(bm, tgt), dmg);
        }

        ActiveAgentCondition aac{};
        aac.agent_idx      = tgt;
        aac.condition_name = "Blinded";
        aac.caster_idx     = idx;
        aac.turns_remaining = 2;                     // until end of the warlock's next turn
        (void)addAgentCondition(bm, aac);
    }
    return true;
}

bool CombatEngine::useMagicalCunning(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.lacksClass(Warlock)) return false;

    Resource* mc = stats.getResource("Magical Cunning");
    if (!mc || mc->current <= 0) return false;  // not available / already used

    const int lvl = stats.pact_slot_level();
    if (lvl < 1) return false;
    const std::size_t i = static_cast<std::size_t>(lvl - 1);
    const int maxs = stats.spell_slots_max[i];
    const int expended = maxs - stats.spell_slots_remaining[i];
    if (expended <= 0) return false;  // nothing to recover

    // ceil(max/2), or all expended at L20 (Eldritch Master).
    const int recover = (stats.classLevel(CharacterClass::Warlock) >= 20) ? expended
                                                 : std::min(expended, (maxs + 1) / 2);
    stats.spell_slots_remaining[i] += recover;
    mc->spend();
    bm.setAgentStats(agent_idx, stats);
    log_("{}: Magical Cunning recovers {} pact slot(s).", agentName(bm, agent_idx), recover);

    // TASK E: Celestial Resilience (Celestial L10): temp HP on Magical Cunning use
    if (stats.hasClass(CharacterClass::Warlock) && stats.warlock_subclass == CelestialPath && stats.classLevel(CharacterClass::Warlock) >= 10) {
        int chaMod = (stats.cha - 10) / 2;
        if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
        stats.temp_hp = std::max(stats.temp_hp, stats.classLevel(CharacterClass::Warlock) + chaMod);
        bm.setAgentStats(agent_idx, stats);
        log_("{}: Celestial Resilience grants {} temp HP", agentName(bm, agent_idx), stats.classLevel(CharacterClass::Warlock) + chaMod);
    }

    return true;
}

int CombatEngine::useHealingLight(BattleMap& bm, int healer_idx, int target_idx, int num_dice)
{
    auto agents = bm.placedAgents();
    if (healer_idx < 0 || healer_idx >= static_cast<int>(agents.size())) return 0;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats healer_stats = bm.getAgentStats(healer_idx);
    if (healer_stats.lacksClass(CharacterClass::Warlock) || healer_stats.warlock_subclass != CelestialPath ||
        healer_stats.classLevel(CharacterClass::Warlock) < 3) {
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
    int healed = std::min(total_healing, target_stats.effectiveMaxHp() - target_stats.hp_cur);
    if (target_stats.cant_heal) { total_healing = 0; healed = 0; }   // Chill Touch, Pit Fiend poison
    target_stats.hp_cur = std::min(target_stats.effectiveMaxHp(), target_stats.hp_cur + total_healing);
    bm.setAgentStats(target_idx, target_stats);
    reviveOnHeal(bm, target_idx);   // a healed downed ally rejoins initiative

    log_("{}: Healing Light: {} d6 = {} healing to {}", agentName(bm, healer_idx), num_dice, total_healing, agentName(bm, target_idx));
    return healed;
}

} // namespace rpg
