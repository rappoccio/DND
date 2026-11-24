// ─────────────────────────────────────────────────────────────────────────────
//  combat_sorcerer.cpp  –  CombatEngine Sorcerer features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Draconic, Clockwork, Aberrant.
//  Contents: Innate Sorcery, Sorcery Incarnate, Dragon Wings, Draconic Resistance, Trance
//  of Order, Bastion of Law, Clockwork Cavalcade, Revelation in Flesh, Warping Implosion;
//  Font of Magic, Metamagic costs, Psionic Sorcery, Bend Luck, Tides of Chaos, Wild Magic Surge.
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
#include <unordered_set>
#include <vector>

namespace rpg {

bool CombatEngine::activateInnateSorcery(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer)) return false;

    // Normally requires an available Innate Sorcery use (Bonus Action; 2 uses per long rest).
    // Sorcery Incarnate (L7): with the uses spent, 2 Sorcery Points buy an activation instead.
    // Both resources are spent on this local `stats` copy (not via spendResource) so the single
    // setAgentStats below writes the spend AND the duration — a bm-side spend would be clobbered.
    Resource* innate = stats.getResource("Innate Sorcery");
    bool paid_with_sp = false;
    if (innate && innate->current > 0) {
        innate->spend(1);
    } else if (stats.classLevel(CharacterClass::Sorcerer) >= 7) {
        Resource* sp = stats.getResource("Sorcery Points");
        if (!sp || sp->current < 2) return false;
        sp->spend(2);
        paid_with_sp = true;
    } else {
        return false;
    }

    stats.innate_sorcery_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Innate Sorcery{}: +1 spell save DC and advantage on spell attacks for 1 minute",
         agentName(bm, idx), paid_with_sp ? " (Sorcery Incarnate — 2 SP)" : "");
    return true;
}

bool CombatEngine::sorceryIncarnateActive(const Agent::Stats& s) noexcept
{
    return s.hasClass(CharacterClass::Sorcerer) &&
           s.classLevel(CharacterClass::Sorcerer) >= 7 && s.innate_sorcery_turns > 0;
}

bool CombatEngine::activateDragonWings(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::DraconicPath ||
        stats.classLevel(CharacterClass::Sorcerer) < 14) {
        return false;
    }

    if (stats.dragon_wings_active) {
        // Dismiss — retract wings and clear fly speed granted by this feature.
        stats.dragon_wings_active = false;
        stats.speed_fly = 0;
        bm.setAgentStats(idx, stats);
        log_("{} retracts their Dragon Wings (fly speed removed)", agentName(bm, idx));
    } else {
        // Extend — grant fly speed equal to walk speed.
        stats.dragon_wings_active = true;
        stats.speed_fly = std::max(stats.speed_fly, stats.speed_walk);
        bm.setAgentStats(idx, stats);
        log_("{} extends Dragon Wings: fly speed {} ft (no concentration)", agentName(bm, idx), stats.speed_walk);
    }
    return true;
}

bool CombatEngine::activateDraconicResistance(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::DraconicPath ||
        stats.classLevel(CharacterClass::Sorcerer) < 6 || stats.draconic_affinity_type < 0) {
        return false;
    }
    if (stats.draconic_affinity_resist_turns > 0) return false;  // already active

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < 1) return false;

    sp->spend(1);
    auto t = static_cast<std::size_t>(stats.draconic_affinity_type);
    stats.magic_damage_multipliers[t] = 0.5f;
    stats.draconic_affinity_resist_turns = 600;  // 1 hour = 600 rounds
    bm.setAgentStats(idx, stats);

    log_("{} gains Draconic Resistance (type {}) for 1 hour (1 SP spent)",
         agentName(bm, idx), stats.draconic_affinity_type);
    return true;
}

bool CombatEngine::activateTranceOfOrder(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        stats.classLevel(CharacterClass::Sorcerer) < 14) {
        log_("{} cannot enter Trance of Order (not a L14+ Clockwork Sorcerer)", agentName(bm, idx));
        return false;
    }

    // Free 1/long rest via the "Trance of Order" Resource; otherwise 5 Sorcery Points.
    Resource* trance = stats.getResource("Trance of Order");
    Resource* sp     = stats.getResource("Sorcery Points");
    if (trance && trance->current >= 1) {
        trance->current -= 1;
    } else if (sp && sp->current >= 5) {
        sp->current -= 5;
        log_("{} spends 5 Sorcery Points for Trance of Order", agentName(bm, idx));
    } else {
        log_("{} has no Trance of Order use left and lacks 5 Sorcery Points", agentName(bm, idx));
        return false;
    }

    stats.trance_of_order_turns = 10;            // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);                // persist BEFORE spending the bonus action
    spendBonusAction(bm, idx);                   // re-reads stats internally (ordering gotcha)

    log_("{} enters a Trance of Order: for 1 minute, attacks against them lose Advantage and they "
         "treat their own d20 of 9 or lower as a 10", agentName(bm, idx));
    return true;
}

int CombatEngine::activateBastionOfLaw(BattleMap& bm, int caster_idx, int target_idx, int sp) noexcept
{
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.lacksClass(CharacterClass::Sorcerer) ||
        caster.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        caster.classLevel(CharacterClass::Sorcerer) < 6) {
        log_("{} cannot use Bastion of Law (not a L6+ Clockwork Sorcerer)", agentName(bm, caster_idx));
        return -1;
    }

    sp = std::clamp(sp, 1, 5);   // 1-5 Sorcery Points = 1-5 d8 ward dice

    // Self or a creature within 30 ft.
    if (caster_idx != target_idx) {
        const PlacedAgent& cpa = agents[static_cast<std::size_t>(caster_idx)];
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
        if (footprintDistance(cpa.origin, cpa.agent->getSize(),
                              tpa.origin, tpa.agent->getSize()) * 5 > 30) {
            log_("Bastion of Law: target is beyond 30 ft");
            return -1;
        }
    }

    Resource* sp_res = caster.getResource("Sorcery Points");
    if (!sp_res || sp_res->current < sp) {
        log_("{} lacks {} Sorcery Points for Bastion of Law", agentName(bm, caster_idx), sp);
        return -1;
    }
    sp_res->current -= sp;
    bm.setAgentStats(caster_idx, caster);   // persist the SP spend

    // Pre-roll (sp)d8 into a flat absorption pool (overwrites any prior ward).
    int ward = 0;
    for (int i = 0; i < sp; ++i) ward += roll(8, 0);

    Agent::Stats tgt = bm.getAgentStats(target_idx);
    tgt.bastion_ward = ward;
    bm.setAgentStats(target_idx, tgt);

    log_("{} spends {} Sorcery Points: Bastion of Law wards {} with a {}-point shield ({}d8)",
         agentName(bm, caster_idx), sp, agentName(bm, target_idx), ward, sp);
    return ward;
}

int CombatEngine::applyBastionWard(BattleMap& bm, int idx, Agent::Stats& s, int dmg) noexcept
{
    if (s.bastion_ward <= 0 || dmg <= 0) return dmg;
    int soaked = std::min(s.bastion_ward, dmg);
    s.bastion_ward -= soaked;
    log_("{}: Bastion of Law ward absorbs {} damage ({} ward left)",
         agentName(bm, idx), soaked, s.bastion_ward);
    return dmg - soaked;
}

int CombatEngine::clockworkCavalcade(BattleMap& bm, int caster_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.lacksClass(CharacterClass::Sorcerer) ||
        caster.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        caster.classLevel(CharacterClass::Sorcerer) < 18) {
        log_("{} cannot use Clockwork Cavalcade (not a L18+ Clockwork Sorcerer)", agentName(bm, caster_idx));
        return -1;
    }

    // Free 1/long rest via the "Clockwork Cavalcade" Resource; otherwise 7 Sorcery Points.
    Resource* cav = caster.getResource("Clockwork Cavalcade");
    Resource* sp  = caster.getResource("Sorcery Points");
    if (cav && cav->current >= 1) {
        cav->current -= 1;
    } else if (sp && sp->current >= 7) {
        sp->current -= 7;
        log_("{} spends 7 Sorcery Points for Clockwork Cavalcade", agentName(bm, caster_idx));
    } else {
        log_("{} has no Clockwork Cavalcade use left and lacks 7 Sorcery Points", agentName(bm, caster_idx));
        return -1;
    }
    bm.setAgentStats(caster_idx, caster);   // persist the resource/SP spend

    const PlacedAgent& cpa = agents[static_cast<std::size_t>(caster_idx)];
    int affected = 0;
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int tgt_idx = static_cast<int>(i);
        const PlacedAgent& tpa = agents[i];
        if (tpa.removed_from_play) continue;
        // The caster and each ALLY within 30 ft ("each creature of your choice" → your team).
        if (tgt_idx != caster_idx && !areAllies(bm, caster_idx, tgt_idx)) continue;
        if (footprintDistance(cpa.origin, cpa.agent->getSize(),
                              tpa.origin, tpa.agent->getSize()) * 5 > 30) continue;

        Agent::Conditions tc = bm.getAgentConditions(tgt_idx);
        if (tc.dead) continue;   // the dead are not restored

        // Regain 100 HP (revives a downed-but-living ally via healAgent).
        healAgent(bm, tgt_idx, 100);

        // End active spell-applied conditions on the creature (Tasha's: "any spell of level 6 or
        // lower ends" — modeled here as clearing this creature's tracked spell conditions).
        std::vector<int> to_remove;
        for (const auto& cond : conditions_.all()) {
            if (cond.agent_idx != tgt_idx) continue;
            to_remove.push_back(cond.condition_id);
        }
        // removeAgentCondition → onConditionEnded reverses each condition's base flag.
        for (int cid : to_remove) removeAgentCondition(bm, cid);
        if (!to_remove.empty())
            log_("Clockwork Cavalcade ends {} spell effect(s) on {}",
                 to_remove.size(), agentName(bm, tgt_idx));

        ++affected;
    }

    log_("{} summons a Clockwork Cavalcade: {} creature(s) within 30 ft regain 100 HP and are freed "
         "of spell effects", agentName(bm, caster_idx), affected);
    return affected;
}

bool CombatEngine::activateRevelationInFlesh(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Sorcerer) ||
        s.sorcerer_subclass != SorcererSubclass::AberrantPath || s.classLevel(CharacterClass::Sorcerer) < 14) {
        log_("{} cannot use Revelation in Flesh (not a L14+ Aberrant Mind Sorcerer)", agentName(bm, idx));
        return false;
    }
    if (s.revelation_in_flesh_turns > 0) {
        log_("{}'s Revelation in Flesh is already active", agentName(bm, idx));
        return false;
    }
    Resource* sp = s.getResource("Sorcery Points");
    if (!sp || sp->current < 1) {
        log_("{} lacks a Sorcery Point for Revelation in Flesh", agentName(bm, idx));
        return false;
    }

    sp->current -= 1;
    // Snapshot the prior speeds/truesight so they revert on expiry (beginTurn) or a long rest.
    s.revelation_prior_fly       = s.speed_fly;
    s.revelation_prior_swim      = s.speed_swim;
    s.revelation_prior_truesight = s.truesight_range;
    s.speed_fly       = std::max(s.speed_fly, s.speed_walk);   // fly = walk, with hover
    s.speed_swim      = std::max(s.speed_swim, s.speed_walk);  // swim = walk, breathe water
    s.truesight_range = std::max(s.truesight_range, 60);       // see Invisible creatures within 60 ft
    s.revelation_in_flesh_turns = 100;                         // 10 minutes
    bm.setAgentStats(idx, s);
    log_("{} invokes Revelation in Flesh: fly {} ft (hover), swim {} ft, truesight 60 ft for 10 minutes",
         agentName(bm, idx), s.speed_fly, s.speed_swim);
    return true;
}

int CombatEngine::warpingImplosion(BattleMap& bm, int caster_idx, int dest_col, int dest_row) noexcept
{
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.lacksClass(CharacterClass::Sorcerer) ||
        caster.sorcerer_subclass != SorcererSubclass::AberrantPath || caster.classLevel(CharacterClass::Sorcerer) < 18) {
        log_("{} cannot use Warping Implosion (not a L18+ Aberrant Mind Sorcerer)", agentName(bm, caster_idx));
        return -1;
    }

    const PlacedAgent& cpa = agents[static_cast<std::size_t>(caster_idx)];
    const int csize = cpa.agent->getSize();
    const Cell origin = cpa.origin;
    const Cell dest{dest_col, dest_row};

    // Validate the destination (in bounds + not blocked) and the 120 ft range BEFORE spending anything.
    if (!isValidTeleportDestination(bm, dest_col, dest_row)) {
        log_("{}: Warping Implosion destination is blocked or out of bounds", agentName(bm, caster_idx));
        return -1;
    }
    if (footprintDistance(origin, csize, dest, csize) * 5 > 120) {
        log_("{}: Warping Implosion destination is beyond 120 ft", agentName(bm, caster_idx));
        return -1;
    }

    // Pay the cost: free 1/long rest via the "Warping Implosion" Resource, else 5 Sorcery Points.
    Resource* wi = caster.getResource("Warping Implosion");
    Resource* sp = caster.getResource("Sorcery Points");
    if (wi && wi->current >= 1) {
        wi->current -= 1;
    } else if (sp && sp->current >= 5) {
        sp->current -= 5;
        log_("{} spends 5 Sorcery Points for Warping Implosion", agentName(bm, caster_idx));
    } else {
        log_("{} has no Warping Implosion use left and lacks 5 Sorcery Points", agentName(bm, caster_idx));
        return -1;
    }
    bm.setAgentStats(caster_idx, caster);   // persist the cost before moving

    if (!teleportAgent(bm, caster_idx, dest_col, dest_row)) {
        log_("{}: Warping Implosion teleport failed", agentName(bm, caster_idx));
        // Refund the spent use/SP since the feature didn't fire.
        Agent::Stats refund = bm.getAgentStats(caster_idx);
        if (Resource* w2 = refund.getResource("Warping Implosion"); w2 && wi && wi->current < wi->max)
            w2->current += 1;
        else if (Resource* s2 = refund.getResource("Sorcery Points"))
            s2->current += 5;
        bm.setAgentStats(caster_idx, refund);
        return -1;
    }

    // Implosion centered on the space the caster LEFT: every OTHER creature within 30 ft makes a
    // Dexterity save vs the caster's spell DC, taking 3d10 Force (half on a success).
    const int dc = rules::spellSaveDcFromAbility(caster, SaveDex);
    int affected = 0;
    for (std::size_t i = 0; i < agents.size(); ++i) {
        const int tgt_idx = static_cast<int>(i);
        if (tgt_idx == caster_idx) continue;             // the caster already left
        const PlacedAgent& tpa = agents[i];
        if (tpa.removed_from_play) continue;
        if (bm.getAgentConditions(tgt_idx).dead) continue;
        if (bm.getAgentStats(tgt_idx).hp_cur <= 0) continue;
        if (footprintDistance(origin, csize, tpa.origin, tpa.agent->getSize()) * 5 > 30) continue;

        const int base = roll(10) + roll(10) + roll(10);  // 3d10 Force
        const int save = roll(20, saveModFor(bm, tgt_idx, SaveDex));
        const bool made = save >= dc;
        const int dmg = made ? base / 2 : base;
        log_("Warping Implosion: {} DEX save {} vs DC {} → {} ({} Force)", agentName(bm, tgt_idx),
             save, dc, made ? "success (half)" : "failure", dmg);
        if (dmg > 0) {
            damageAgent(bm, tgt_idx, dmg);
            checkConcentrationOnDamage(bm, tgt_idx, dmg, caster_idx);
            processDamageTaken(bm, tgt_idx, dmg);
        }
        ++affected;
    }
    log_("{}: Warping Implosion strikes {} creature(s) within 30 ft of the space it left",
         agentName(bm, caster_idx), affected);
    return affected;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Moved from combat_spells.cpp (COMBAT_CLASS_SPLIT_PLAN.md R6c)
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::convertSlotToSorceryPoints(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer)) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;   // no slot of that level to spend

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp) return -1;

    stats.spell_slots_remaining[si] -= 1;
    sp->gain(slot_level);  // gain SP equal to the slot level (capped at max by Resource::gain)
    bm.setAgentStats(idx, stats);

    log_("{} converts a level-{} slot into Sorcery Points (now {}/{})",
         agentName(bm, idx), slot_level, sp->current, sp->max);
    return sp->current;
}

int CombatEngine::createSpellSlot(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    // Font of Magic creates only level 1-5 slots.
    if (slot_level < 1 || slot_level > 5) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer)) return -1;

    static const int cost_by_level[6] = {0, 2, 3, 5, 6, 7};  // SP cost; index = slot level
    int cost = cost_by_level[slot_level];

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < cost) return -1;

    sp->spend(cost);
    auto si = static_cast<std::size_t>(slot_level - 1);
    stats.spell_slots_remaining[si] += 1;  // temporary slot; cleared at the next long rest
    bm.setAgentStats(idx, stats);

    log_("{} spends {} Sorcery Points to create a level-{} slot",
         agentName(bm, idx), cost, slot_level);
    return sp->current;
}

// Sorcerer Metamagic — Sorcery Point cost per option (2024 PHB).
int CombatEngine::metamagicSpCost(MetamagicOption opt) noexcept
{
    switch (opt) {
        case MetamagicHeightened:
        case MetamagicQuickened:   return 2;
        case MetamagicCareful:
        case MetamagicDistant:
        case MetamagicEmpowered:
        case MetamagicExtended:
        case MetamagicSeeking:
        case MetamagicSubtle:
        case MetamagicTransmuted:
        case MetamagicTwinned:     return 1;
        default:                   return 0;  // MetamagicNone
    }
}

int CombatEngine::sorcererBendLuck(BattleMap& bm, int idx, bool boost) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.classLevel(CharacterClass::Sorcerer) < 6) {
        log_("{} cannot use Bend Luck (not a L6+ Wild Magic Sorcerer)", agentName(bm, idx));
        return 0;
    }

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < 1) {
        log_("{} has no Sorcery Point for Bend Luck", agentName(bm, idx));
        return 0;
    }

    sp->current -= 1;
    int value = roll(4);                                 // 1d4
    ctx_.pending_roll_bonus_ = boost ? value : -value;        // bonus or penalty to the next D20 Test
    bm.setAgentStats(idx, stats);

    log_("{} uses Bend Luck: {}{} to the next D20 Test ({} Sorcery Points left)",
         agentName(bm, idx), boost ? "+" : "-", value, sp->current);
    return value;
}

WildMagicSurgeResult CombatEngine::rollWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    WildMagicSurgeResult res;
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return res;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.classLevel(CharacterClass::Sorcerer) < 3) {
        log_("{} cannot surge (not a L3+ Wild Magic Sorcerer)", agentName(bm, idx));
        return res;  // effect = 0
    }

    res.d100_roll  = roll(100);                       // 1-100
    res.effect      = (res.d100_roll - 1) / 10 + 1;   // → band 1-10
    res.description = wildMagicSurgeDescription(res.effect);

    log_("{} Wild Magic Surge (d100={}, effect {}): {}",
         agentName(bm, idx), res.d100_roll, res.effect, res.description);
    return res;
}

std::string CombatEngine::wildMagicSurgeDescription(int effect) noexcept
{
    // Curated d100 surge table (bands of 10 → effect 1-10). Applying each effect is the
    // caller's job; some bands are placeholders pending easier replacements (see notes).
    switch (effect) {
        case 1:  return "Plant Growth sprouts around your feet (difficult terrain in a sphere "
                        "centered on you).";
        case 2:  return "A spectral shield hovers near you for the next minute, granting you a "
                        "+2 bonus to AC and immunity to Magic Missile.";
        case 3:  return "For the next minute, you regain 5 Hit Points at the start of each of "
                        "your turns.";
        case 4:  return "Up to three creatures of your choice within 30 ft take 4d10 Lightning "
                        "damage.";
        case 5:  return "You cast Blindness on a creature you can see within range "
                        "(Constitution save or the Blinded condition).";
        case 6:  return "For the next minute, your spells that take an action to cast can be "
                        "cast as a Bonus Action.";
        case 7:  return "Your next turn is skipped.";
        case 8:  return "You can take one extra action on this turn.";
        case 9:  return "Your weapons are all dropped and appear on a random square you can see.";
        case 10: return "For the next minute, you can teleport up to 20 ft as a Bonus Action on "
                        "each of your turns.";
        default: return "";
    }
}

bool CombatEngine::applyWildMagicSurgeEffect(BattleMap& bm, int idx, int effect) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    if (effect == 1) {  // "Plant Growth sprouts around your feet" — cast Plant Growth on the caster.
        Cell origin = agents[static_cast<std::size_t>(idx)].origin;
        const int size = agents[static_cast<std::size_t>(idx)].agent->getSize();
        // 10-ft radius Sphere centered on the caster, pruned to what that point can reach —
        // Total Cover blocks it like any other area.
        auto cells = bm.pruneBlockedCells(AreaOrigin{origin, size},
                                          sphereCellsAround(origin.col, origin.row, 10));
        [[maybe_unused]] int id = bm.placeTerrainEffect(
            "Plant Growth (Wild Magic Surge)", cells,
            TerrainDifficulty::Quartered, 10 /* rounds ≈ 1 minute */, idx);
        log_("{}: Plant Growth sprouts — difficult terrain over {} cells",
             agentName(bm, idx), cells.size());
        return true;
    }

    if (effect == 9) {  // "Your weapons are all dropped and appear on a random square you can see."
        // Simplified: the weapons land on the caster's own cell as ground items.
        Cell origin = agents[static_cast<std::size_t>(idx)].origin;
        auto weapons = bm.getAgentWeapons(idx);
        int dropped = 0;
        for (auto& w : weapons) {
            // Only real weapons drop — natural/innate attacks stay (Weapon::droppable()).
            if (w.droppable()) {
                [[maybe_unused]] int item_id = bm.placeItem(origin, w);
                w = Weapon{};  // clear the slot back to the default (Unarmed)
                ++dropped;
            }
        }
        if (dropped > 0) bm.setAgentWeapons(idx, weapons);
        log_("{}: Wild Magic Surge drops {} weapon(s) to the ground", agentName(bm, idx), dropped);
        return true;
    }

    // Bands 2/3/6/7/8/10 are per-agent state effects, ticked at the start of the agent's turns.
    constexpr int kMinuteRounds = 10;
    Agent::Stats stats = bm.getAgentStats(idx);
    switch (effect) {
        case 2:  // Spectral shield: +2 AC + Magic Missile immunity for 1 minute.
            stats.ac_temporary_modifications += 2;       // removed when wild_magic_shield_turns hits 0
            stats.wild_magic_shield_turns = kMinuteRounds;
            log_("{}: a spectral shield grants +2 AC and Magic Missile immunity for 1 minute",
                 agentName(bm, idx));
            break;
        case 3:  // Regain 5 HP at the start of each of your turns for 1 minute.
            stats.wild_magic_regen_turns = kMinuteRounds;
            log_("{}: surging vitality — regain 5 HP at the start of each turn for 1 minute",
                 agentName(bm, idx));
            break;
        case 6:  // For 1 minute, action-cast spells can be cast as a Bonus Action (GUI-enforced).
            stats.wild_magic_bonus_cast_turns = kMinuteRounds;
            log_("{}: for 1 minute, spells that take an action can be cast as a Bonus Action",
                 agentName(bm, idx));
            break;
        case 7:  // Your next turn is skipped.
            stats.wild_magic_skip_next_turn = true;
            log_("{}: the surge will skip their next turn", agentName(bm, idx));
            break;
        case 8:  // You can take one extra action on this turn (enforced by the GUI turn economy).
            stats.wild_magic_extra_action = true;
            log_("{}: the surge grants one extra action this turn", agentName(bm, idx));
            break;
        case 10: // For 1 minute, teleport up to 20 ft as a Bonus Action each turn (GUI-enforced).
            stats.wild_magic_teleport_bonus_turns = kMinuteRounds;
            log_("{}: for 1 minute, can teleport up to 20 ft as a Bonus Action each turn",
                 agentName(bm, idx));
            break;
        default:
            return false;  // applied by the caller / not yet wired
    }
    bm.setAgentStats(idx, stats);
    return true;
}

bool CombatEngine::activateTidesOfChaos(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.classLevel(CharacterClass::Sorcerer) < 3) {
        log_("{} cannot use Tides of Chaos (not a L3+ Wild Magic Sorcerer)", agentName(bm, idx));
        return false;
    }

    Resource* tides = stats.getResource("Tides of Chaos");
    if (!tides || tides->current < 1) {
        log_("{} has no Tides of Chaos use left (recharges on a long rest or a Wild Magic Surge)",
             agentName(bm, idx));
        return false;
    }

    tides->current -= 1;
    grantPendingAdvantage(true, idx);            // Advantage on idx's next D20 Test, nobody else's
    bm.setAgentStats(idx, stats);

    log_("{} uses Tides of Chaos: Advantage on the next D20 Test", agentName(bm, idx));
    return true;
}

bool CombatEngine::armTidesForInitiative(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.classLevel(CharacterClass::Sorcerer) < 3) {
        log_("{} cannot use Tides of Chaos (not a L3+ Wild Magic Sorcerer)", agentName(bm, idx));
        return false;
    }

    auto& armed = ctx_.tides_on_initiative_;
    if (std::find(armed.begin(), armed.end(), idx) != armed.end()) return true;  // already spent

    Resource* tides = stats.getResource("Tides of Chaos");
    if (!tides || tides->current < 1) {
        log_("{} has no Tides of Chaos use left (recharges on a long rest or a Wild Magic Surge)",
             agentName(bm, idx));
        return false;
    }

    tides->current -= 1;
    bm.setAgentStats(idx, stats);
    armed.push_back(idx);
    return true;
}

bool CombatEngine::spendSorceryPointsForSpell(BattleMap& bm, int idx, int spell_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (spell_level < 1) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::AberrantPath ||
        stats.classLevel(CharacterClass::Sorcerer) < 3) {
        return false;
    }

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < spell_level) return false;

    sp->spend(spell_level);
    bm.setAgentStats(idx, stats);

    log_("{} spends {} Sorcery Points to cast a level-{} psionic spell",
         agentName(bm, idx), spell_level, spell_level);
    return true;
}

WildMagicSurgeResult CombatEngine::maybeWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    // Non-interactive path: offer, then auto-apply the first rolled band (no Controlled Chaos /
    // Tamed Surge choice — the GUI uses offerWildMagicSurge + resolveWildMagicSurge for those).
    WildMagicSurgeOffer offer = offerWildMagicSurge(bm, idx);
    if (!offer.surged || offer.options.empty()) return WildMagicSurgeResult{};
    return resolveWildMagicSurge(bm, idx, offer.options.front(), offer.tides_expended);
}

WildMagicSurgeOffer CombatEngine::offerWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    WildMagicSurgeOffer offer;                   // surged == false → no surge
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return offer;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.lacksClass(CharacterClass::Sorcerer) ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.classLevel(CharacterClass::Sorcerer) < 3) {
        return offer;                            // silent: only Wild Magic Sorcerers surge
    }

    // Tides of Chaos: if it is currently expended, the next slot-spell cast forces a surge
    // (and the surge then recharges it). Otherwise a surge needs a natural 20 on a d20.
    Resource* tides = stats.getResource("Tides of Chaos");
    offer.tides_expended = tides && tides->current < tides->max;

    const int d20 = roll(20);
    const bool surge = offer.tides_expended || (d20 == 20);
    log_("{}: Wild Magic Surge check — d20={}{}", agentName(bm, idx), d20,
         offer.tides_expended ? " (Tides of Chaos forces a surge)" : "");
    if (!surge) return offer;

    offer.surged = true;
    // Roll the table. Controlled Chaos (L14): roll twice and keep both bands so the caller may use
    // either result.
    const int rolls = (stats.classLevel(CharacterClass::Sorcerer) >= 14) ? 2 : 1;
    for (int i = 0; i < rolls; ++i) {
        WildMagicSurgeResult r = rollWildMagicSurge(bm, idx);   // rolls d100, classifies, logs
        if (r.effect > 0 &&
            std::find(offer.options.begin(), offer.options.end(), r.effect) == offer.options.end())
            offer.options.push_back(r.effect);
    }
    // Tamed Surge (L18): the caller may replace the rolled result with any band 1-10.
    offer.can_choose_any = (stats.classLevel(CharacterClass::Sorcerer) >= 18);
    return offer;
}

WildMagicSurgeResult CombatEngine::resolveWildMagicSurge(BattleMap& bm, int idx, int effect,
                                                         bool tides_expended) noexcept
{
    WildMagicSurgeResult res;                    // effect == 0 → nothing applied
    if (effect < 1 || effect > 10) return res;

    res.effect      = effect;
    res.description = wildMagicSurgeDescription(effect);
    applyWildMagicSurgeEffect(bm, idx, effect);  // mutates + persists stats internally
    if (tides_expended) {
        // Re-fetch (applyWildMagicSurgeEffect may have written stats) before recharging Tides
        // so the surge's own state changes aren't clobbered.
        Agent::Stats fresh = bm.getAgentStats(idx);
        if (Resource* t2 = fresh.getResource("Tides of Chaos")) {
            t2->current = t2->max;
            bm.setAgentStats(idx, fresh);
            log_("{}: the surge recharges Tides of Chaos", agentName(bm, idx));
        }
    }
    return res;
}

void CombatEngine::clearWildMagicSurgeEffects(BattleMap& bm) noexcept
{
    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
        Agent::Stats st = bm.getAgentStats(i);
        if (st.wild_magic_shield_turns == 0 && st.wild_magic_regen_turns == 0 &&
            st.wild_magic_bonus_cast_turns == 0 && st.wild_magic_teleport_bonus_turns == 0 &&
            !st.wild_magic_skip_next_turn && !st.wild_magic_extra_action)
            continue;
        if (st.wild_magic_shield_turns > 0) st.ac_temporary_modifications -= 2;  // band 2's +2 AC
        st.wild_magic_shield_turns         = 0;
        st.wild_magic_regen_turns          = 0;
        st.wild_magic_bonus_cast_turns     = 0;
        st.wild_magic_teleport_bonus_turns = 0;
        st.wild_magic_skip_next_turn       = false;
        st.wild_magic_extra_action         = false;
        bm.setAgentStats(i, st);
    }
}


} // namespace rpg
