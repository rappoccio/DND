// ─────────────────────────────────────────────────────────────────────────────
//  combat_resources.cpp  –  CombatEngine resources, rests, class & subclass forms
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The resource half of the action economy: the bonus-action budget, healing /
//  resource spending, long/short rests, per-class activations, and the Druid /
//  subclass transformation forms.
//  Sections:
//    · Bonus-action budget — hasBonusAction, spendBonusAction, resetBonusActions
//    · Resources & healing  — spendResource, healAgent, layOnHands, tickTerrainForTurn
//    · Rests                — applyLongRest, applyShortRest
//    · Class activations    — Rage, Primal Knowledge, Sacred Weapon, Innate Sorcery,
//                             Magical Cunning, Healing Light, Turn Undead, Portent
//    · Subclass forms       — Wild Shape, Starry Form, Wrath of the Sea, Dragon
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <unordered_set>
#include <vector>

namespace rpg {

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

// ─────────────────────────────────────────────────────────────────────────────
//  Bonus-action budget (general action economy)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::hasBonusAction(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;
    return bm.getAgentStats(agent_idx).bonus_actions_remaining > 0;
}

bool CombatEngine::spendBonusAction(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.bonus_actions_remaining <= 0) return false;

    stats.bonus_actions_remaining--;
    bm.setAgentStats(agent_idx, stats);
    log_("{} uses a bonus action ({} remaining)", agentName(bm, agent_idx),
         stats.bonus_actions_remaining);
    return true;
}

void CombatEngine::resetBonusActions(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    stats.bonus_actions_remaining = stats.bonus_actions_max;
    bm.setAgentStats(agent_idx, stats);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Resources & healing
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::spendResource(BattleMap& bm, int idx, const std::string& name, int amount) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    Resource* r = s.getResource(name);
    if (!r || r->current < amount) return false;
    r->spend(amount);
    bm.setAgentStats(idx, s);
    log_("{} spends {} {}.", agentName(bm, idx), amount, name);
    return true;
}

int CombatEngine::healAgent(BattleMap& bm, int idx, int amount) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return 0;   // default-constructed → invalid idx
    s.hp_cur = std::min(s.effectiveMaxHp(), s.hp_cur + amount);  // can't heal past a drained max
    bm.setAgentStats(idx, s);
    reviveOnHeal(bm, idx);   // regaining HP from 0 returns a downed creature to consciousness
    return s.hp_cur;
}

UseItemResult CombatEngine::useItem(BattleMap& bm, int user_idx, int item_slot, int target_idx) noexcept
{
    UseItemResult res;
    const auto& agents = bm.placedAgents();
    if (user_idx   < 0 || user_idx   >= static_cast<int>(agents.size())) return res;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return res;

    std::vector<Item> inv = bm.getAgentItems(user_idx);
    if (item_slot < 0 || item_slot >= static_cast<int>(inv.size())) return res;
    const Item item = inv[static_cast<std::size_t>(item_slot)];   // by value: the row may be erased below
    if (item.quantity <= 0) return res;

    // The user has to be able to act: no rummaging through your pack while dead or Incapacitated
    // (which covers Unconscious/Paralyzed/Stunned — see applyIncapacitated).
    const Agent::Conditions uc = bm.getAgentConditions(user_idx);
    if (uc.dead || uc.unconscious || uc.incapacitated) return res;
    // …and there is no point pouring a potion down a corpse's throat (a *downed* ally is fine —
    // healAgent revives it).
    if (bm.getAgentConditions(target_idx).dead) return res;

    // Range. 0 ⇒ self only; otherwise the target must be within `range` feet.
    if (target_idx != user_idx) {
        if (item.range <= 0) return res;
        const PlacedAgent& upa = agents[static_cast<std::size_t>(user_idx)];
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
        if (footprintDistance(upa.origin, upa.agent->getSize(),
                              tpa.origin, tpa.agent->getSize()) * 5 > item.range) return res;
    }

    // Action economy. (An Action-cost item is gated by the GUI's action budget, as spellcasting is,
    // and an AttackReplacement item is paid for out of the Attack action's swing budget — only the
    // Bonus Action has an engine-side budget to spend.)
    if (item.action_type == Item::BonusAction && !hasBonusAction(bm, user_idx)) return res;

    res.valid     = true;
    res.item_name = item.name;

    if (item.type == Item::Heal) {
        int amount = item.healing.bonus;
        for (int i = 0; i < item.healing.num_dice; ++i) amount += roll(item.healing.die_size);
        const int before = bm.getAgentStats(target_idx).hp_cur;
        healAgent(bm, target_idx, amount);
        res.amount_healed = bm.getAgentStats(target_idx).hp_cur - before;
        if (target_idx == user_idx)
            log_("{} drinks {} and regains {} HP.", agentName(bm, user_idx), item.name, res.amount_healed);
        else
            log_("{} administers {} to {}, who regains {} HP.", agentName(bm, user_idx), item.name,
                 agentName(bm, target_idx), res.amount_healed);
    } else if (item.type == Item::Thrown) {
        resolveThrownItem(bm, user_idx, target_idx, item, res);
    }

    // Spend the charge.
    if (item.consumable) {
        Item& row = inv[static_cast<std::size_t>(item_slot)];
        if (--row.quantity <= 0) {
            inv.erase(inv.begin() + item_slot);
            res.consumed = true;
        }
        bm.setAgentItems(user_idx, inv);
    }

    if (item.action_type == Item::BonusAction) spendBonusAction(bm, user_idx);
    return res;
}

void CombatEngine::resolveThrownItem(BattleMap& bm, int user_idx, int target_idx,
                                     const Item& item, UseItemResult& res) noexcept
{
    const auto& agents = bm.placedAgents();
    const Agent::Stats user_stats   = bm.getAgentStats(user_idx);
    const Agent::Stats target_stats = bm.getAgentStats(target_idx);
    const Agent::Conditions tc      = bm.getAgentConditions(target_idx);
    const std::string user_name = agentName(bm, user_idx);
    const std::string tgt_name  = agentName(bm, target_idx);

    // Holy Water: "…or take 2d8 Radiant damage IF IT IS a Fiend or an Undead." Everything else is
    // just splashed with water — no save, no damage, but the flask is still gone.
    if (item.only_vs_fiend_undead && !target_stats.is_fiend && !target_stats.is_undead) {
        res.no_effect = true;
        log_("{} throws {} at {} — no effect (not a Fiend or an Undead).", user_name, item.name, tgt_name);
        return;
    }

    // DC 8 + the THROWER's ability modifier + Proficiency Bonus. Computed here rather than through
    // spellSaveDcFromAbility, which folds in caster-only buffs (Innate Sorcery) that have no
    // business raising the DC of a hurled flask.
    const int score = (item.save_ability == SaveStr) ? user_stats.str
                    : (item.save_ability == SaveCon) ? user_stats.con
                    : (item.save_ability == SaveInt) ? user_stats.intel
                    : (item.save_ability == SaveWis) ? user_stats.wis
                    : (item.save_ability == SaveCha) ? user_stats.cha
                                                     : user_stats.dex;
    int throw_mod = (score - 10) / 2;
    if (score < 10 && (score - 10) % 2 != 0) --throw_mod;   // floor for odd scores below 10
    res.save_dc = 8 + user_stats.prof_bonus + throw_mod;

    // Net: "The target succeeds automatically if it is Huge or larger." Size is the agent footprint
    // in cells (1 = Medium/Small, 2 = Large, 3 = Huge).
    const int target_size = agents[static_cast<std::size_t>(target_idx)].agent->getSize();
    if (item.max_target_size > 0 && target_size > item.max_target_size) {
        res.saved = true;
        log_("{} throws {} at {}, but it is too big to be caught — the {} slides off.",
             user_name, item.name, tgt_name, item.name);
        return;
    }

    // The target's DEX save. Paralyzed/Stunned/Unconscious creatures auto-fail STR and DEX saves,
    // and a Restrained creature has Disadvantage on DEX saves — the same rules the spell-save and
    // zone-tick paths apply.
    const bool auto_fail = (tc.paralyzed || tc.stunned || tc.unconscious) &&
                           (item.save_ability == SaveStr || item.save_ability == SaveDex);
    const Agent& tgt = *agents[static_cast<std::size_t>(target_idx)].agent;
    bool adv = tgt.hasAdvantage();
    bool dis = tgt.hasDisadvantage();
    if (item.save_ability == SaveDex && tc.restrained) dis = true;

    int save_d20;
    if (auto_fail)       save_d20 = 1;
    else if (adv && dis) save_d20 = roll(20);
    else if (adv)        save_d20 = rollAdvantage(20);
    else if (dis)        save_d20 = rollDisadvantage(20);
    else                 save_d20 = roll(20);

    const int save_mod = saveModFor(bm, target_idx, item.save_ability);
    res.save_roll = save_d20 + save_mod;
    res.saved     = !auto_fail && (res.save_roll >= res.save_dc);

    log_("{} throws {} at {} — save {} + {} = {} vs DC {} ({})",
         user_name, item.name, tgt_name, save_d20, save_mod, res.save_roll, res.save_dc,
         auto_fail ? "AUTO-FAIL" : (res.saved ? "PASSED" : "FAILED"));

    if (res.saved) return;   // these items have no half-damage-on-a-save: a made save is a clean miss

    // Damage (after the target's Resistance/Immunity multiplier). num_dice == 0 for a Net.
    if (item.damage.num_dice > 0) {
        int raw = item.damage.bonus;
        for (int i = 0; i < item.damage.num_dice; ++i) raw += roll(item.damage.die_size);
        const float mult = effectiveMagicDamageMult(user_stats, target_stats, item.damage.type,
                                                    false, &bm, target_idx);
        res.damage_dealt = static_cast<int>(static_cast<float>(raw) * mult);
        damageAgent(bm, target_idx, res.damage_dealt);
        processDamageTaken(bm, target_idx, res.damage_dealt,
                           1u << static_cast<unsigned>(item.damage.type));
        checkConcentrationOnDamage(bm, target_idx, res.damage_dealt, user_idx);
        log_("{} takes {} damage from {}.", tgt_name, res.damage_dealt, item.name);
        // A thrown flask has no post-hit resolution step of its own (unlike an attack), so mark a
        // creature it killed here — otherwise an NPC dropped by Acid is never flagged dead and its
        // corpse lingers on the map.
        if (bm.getAgentStats(target_idx).hp_cur <= 0) {
            const Agent::Conditions dc = bm.getAgentConditions(target_idx);
            if (!dc.unconscious && !dc.dead) applyUnconscious(bm, target_idx);
            return;   // don't set a creature it just killed on fire / tangle its corpse in a Net
        }
    }

    // Condition rider on the failed save.
    if (item.condition_applied == "Burning") {
        applyBurning(bm, target_idx);
        res.condition_applied = "Burning";
    } else if (item.condition_applied == "Restrained") {
        Agent::Conditions nc = bm.getAgentConditions(target_idx);
        nc.restrained    = true;
        nc.netted        = true;
        nc.net_escape_dc = (item.escape_dc > 0) ? item.escape_dc : 10;
        bm.setAgentConditions(target_idx, nc);
        res.condition_applied = "Restrained";
        log_("{} is caught in the {} — Restrained until it escapes (DC {} STR check).",
             tgt_name, item.name, nc.net_escape_dc);
    }
}

bool CombatEngine::applyOneWithShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const PlacedAgent& pa = agents[static_cast<std::size_t>(idx)];
    const Agent::Stats& s = pa.agent->getStats();
    if (s.character_class != CharacterClass::Warlock || !s.hasInvocation(8)) return false;

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

// Soulknife Rogue — Psychic Veil (L13): a Magic action → gain Invisible. Once per Long Rest, or by
// expending 1 Psionic Energy Die. v1: "ends when you deal damage or force a save" is approximated by
// the base Invisibility (ends on the next attack); the force-a-save end-trigger is not tracked.
bool CombatEngine::activatePsychicVeil(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Rogue ||
        s.rogue_subclass != SoulknifePath || s.char_level < 13) return false;
    Resource* pv  = s.getResource("Psychic Veil");
    Resource* ped = s.getResource("Psionic Energy");
    if (pv && pv->current >= 1)        pv->current  -= 1;     // free use first
    else if (ped && ped->current >= 1) ped->current -= 1;     // else 1 Psionic Energy Die
    else return false;
    bm.setAgentStats(idx, s);

    Agent::Conditions c = bm.getAgentConditions(idx);
    c.invisible = true;
    c.invisible_persists_on_action = false;
    bm.setAgentConditions(idx, c);
    log_("{}: Psychic Veil — gains the Invisible condition", agentName(bm, idx));
    return true;
}

// Warrior of Shadow Monk — Shadow Step (L6+): a Bonus Action teleport. Spend 0 resources.
// Teleport up to 30 feet in dim light or darkness (L6). At L11, can teleport from any light level.
// On successful teleport, set shadow_step_advantage flag for Advantage on next attack this turn.
bool CombatEngine::shadowStepTeleport(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Monk ||
        s.monk_subclass != WarriorOfShadowPath || s.char_level < 6) return false;

    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    const int max_ft = 30;  // Fixed 30 ft range
    if (dcells * 5 > max_ft) {
        log_("{}: Shadow Step destination too far ({} ft > {} ft)",
             agentName(bm, idx), dcells * 5, max_ft);
        return false;
    }

    // L6 gate: must be in dim or dark light
    if (s.char_level < 11) {
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
    if (s.char_level >= 11) c.bonus_reach_available = true;
    bm.setAgentConditions(idx, c);

    log_("{}: Shadow Step — teleports {} ft, next attack has Advantage{}",
         agentName(bm, idx), dcells * 5,
         s.char_level >= 11 ? " and +5 ft reach" : "");
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
    if (s.character_class != CharacterClass::Warlock ||
        s.warlock_subclass != ArchfeyPath || s.char_level < 3) return false;

    // Misty Escape (L6): casting Misty Step reactively (in response to taking damage) requires L6+.
    if (as_reaction && s.char_level < 6) {
        log_("{}: Misty Escape (reaction Misty Step) unlocks at Warlock level 6", agentName(bm, idx));
        return false;
    }

    // L6+ gate for the Disappearing / Dreadful step options.
    if ((effect == 3 || effect == 4) && s.char_level < 6) {
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
        if (rc.reaction_used || rc.incapacitated) {
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
    const int save_dc = spellSaveDcFromAbility(bm.getAgentStats(idx), SaveCha);

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
    if (s.character_class != CharacterClass::Warlock ||
        s.warlock_subclass != ArchfeyPath || s.char_level < 14) return false;

    // The Disappearing / Dreadful riders are L6+ — always satisfied at L14, but keep the shared gate.
    if ((effect == 3 || effect == 4) && s.char_level < 6) return false;

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

// Warrior of Shadow Monk — Cloak of Shadows (L17): a Bonus Action. Gain Invisible in dim/dark.
// Invisibility persists through attacks (doesn't end on action like standard Invisibility).
// Expires on turn start if in bright light, or at end of turn naturally.
bool CombatEngine::cloakOfShadows(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Monk ||
        s.monk_subclass != WarriorOfShadowPath || s.char_level < 17) return false;

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
    if (s.character_class != CharacterClass::Monk ||
        s.monk_subclass != WarriorOfShadowPath || s.char_level < 3) return -1;
    Resource* fp = s.getResource("Focus Points");
    if (!fp || fp->current < 1) {
        log_("{}: Shadow Arts: Darkness requires 1 Focus Point", agentName(bm, idx));
        return -1;
    }

    std::vector<Cell> cells = sphereCellsAround(target_col, target_row, 15);
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
    if (s.character_class != CharacterClass::Monk ||
        s.monk_subclass != WarriorOfFourElementsPath || s.char_level < 3) return false;
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
    if (cs.character_class != CharacterClass::Monk ||
        cs.monk_subclass != WarriorOfFourElementsPath || cs.char_level < 6) return false;
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
    const int  dc  = spellSaveDcFromAbility(cs, SaveWis);   // Monk Ki DC = 8 + PB + WIS
    const int  num = martialArtsDieCount(cs.char_level);

    spendResource(bm, idx, "Focus Points", 2);
    log_("{}: Elemental Burst — a 20 ft Sphere of {} erupts (DC {} DEX save, {}d8)",
         agentName(bm, idx), elementName(mt), dc, num);

    std::vector<Cell> cells = sphereCellsAround(target_col, target_row, 20);
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
        if (ts.character_class == CharacterClass::Rogue && ts.char_level >= 7) {
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
    if (ms.character_class != CharacterClass::Monk ||
        ms.monk_subclass != WarriorOfTheOpenHandPath || ms.char_level < 17) {
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
    for (const auto& c : activeAgentConditions_)
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
    cond.save_dc             = spellSaveDcFromAbility(ms, SaveWis);  // Monk Ki DC = 8 + PB + WIS
    cond.delay_half_on_save  = true;
    cond.delay_auto_on_expire = false;       // monk chooses when to detonate; never auto-fires
    cond.delay_label         = "Quivering Palm";

    int id = addAgentCondition(bm, cond);
    log_("{} plants Quivering Palm in {} (4 Focus; detonate → 10d12 Force, DC {} CON save) [id {}]",
         agentName(bm, monk_idx), agentName(bm, target_idx), cond.save_dc, id);
    return true;
}

// Soulknife Rogue — Psychic Teleportation (L9): a Bonus Action; spend 1 Psionic Energy Die, roll it,
// and teleport up to (10 × roll) feet to an unoccupied cell. Grid distance is Chebyshev × 5 ft. The
// die is spent only on a successful (in-range, legal) teleport.
bool CombatEngine::psychicTeleportation(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Rogue ||
        s.rogue_subclass != SoulknifePath || s.char_level < 9) return false;
    Resource* ped = s.getResource("Psionic Energy");
    if (!ped || ped->current < 1) return false;

    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    const int die    = roll(s.psionic_die_size);
    const int max_ft = 10 * die;
    if (dcells * 5 > max_ft) {
        log_("{}: Psychic Teleportation rolled {} ({} ft) — destination too far ({} ft)",
             agentName(bm, idx), die, max_ft, dcells * 5);
        return false;                                          // die not spent (bad pick)
    }
    if (!teleportAgent(bm, idx, target_col, target_row)) return false;
    ped->current -= 1;
    bm.setAgentStats(idx, s);
    log_("{}: Psychic Teleportation — teleports {} ft (rolled {} → up to {} ft)",
         agentName(bm, idx), dcells * 5, die, max_ft);
    return true;
}

// Trickery Domain Cleric — Invoke Duplicity duplicate movement (Bonus Action on later turns):
// move the cleric's illusory duplicate up to 30 ft to (target_col, target_row). The duplicate is an
// intangible summon (summon_spell == "Invoke Duplicity") owned by the cleric. Creation lives in the
// GUI (it shares the summon-spawn path); this owns the RAW 30-ft range + ownership rule. Returns
// true iff the duplicate moved.
bool CombatEngine::moveDuplicate(BattleMap& bm, int cleric_idx, int dup_idx,
                                 int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (cleric_idx < 0 || cleric_idx >= n || dup_idx < 0 || dup_idx >= n) return false;
    const PlacedAgent& dup = agents[static_cast<std::size_t>(dup_idx)];
    if (dup.removed_from_play || dup.summoner_idx != cleric_idx ||
        dup.summon_spell != "Invoke Duplicity") return false;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.character_class != CharacterClass::Cleric ||
        cs.cleric_subclass != TrickeryDomain || cs.char_level < 3) return false;

    const Cell from = dup.origin;
    const int dcells = std::max(std::abs(target_col - from.col), std::abs(target_row - from.row));
    if (dcells * 5 > 30) {
        log_("{}: Invoke Duplicity — destination too far ({} ft > 30 ft)",
             agentName(bm, cleric_idx), dcells * 5);
        return false;                                          // out of range (illusion not moved)
    }
    if (!teleportAgent(bm, dup_idx, target_col, target_row)) return false;
    log_("{}: moves the illusory duplicate {} ft", agentName(bm, cleric_idx), dcells * 5);
    return true;
}

// Trickster's Transposition (Trickery Cleric L6+): swap the cleric's position with their duplicate.
// No resource or action cost — RAW it rides on creating or moving the duplicate. The duplicate is
// intangible, so only the cleric re-checks destination spell effects / darkness after the swap.
// Returns true iff the swap happened.
bool CombatEngine::swapWithDuplicate(BattleMap& bm, int cleric_idx, int dup_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (cleric_idx < 0 || cleric_idx >= n || dup_idx < 0 || dup_idx >= n) return false;
    const PlacedAgent& dup = agents[static_cast<std::size_t>(dup_idx)];
    if (dup.removed_from_play || dup.summoner_idx != cleric_idx ||
        dup.summon_spell != "Invoke Duplicity") return false;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.character_class != CharacterClass::Cleric ||
        cs.cleric_subclass != TrickeryDomain || cs.char_level < 6) return false;

    const Cell cleric_from = agents[static_cast<std::size_t>(cleric_idx)].origin;
    const Cell dup_from    = dup.origin;
    // Direct position swap — setAgentPosition only checks bounds, so trading two occupied cells is
    // legal. Roll back the cleric if the second move fails (e.g. duplicate's old cell off-grid).
    if (!bm.setAgentPosition(cleric_idx, dup_from)) return false;
    if (!bm.setAgentPosition(dup_idx, cleric_from)) {
        bm.setAgentPosition(cleric_idx, cleric_from);
        return false;
    }
    // Re-apply any destination spell effects + darkness blinding to the cleric (mirrors teleportAgent).
    for (const auto& effect : bm.activeSpellEffects()) {
        if (zoneSparesTarget(bm, effect, cleric_idx)) continue;
        if (std::find(effect.cells.begin(), effect.cells.end(), dup_from) != effect.cells.end())
            applySpellEffect(bm, effect, cleric_idx);
    }
    updateDarknessBlinding(bm, cleric_idx);
    log_("Trickster's Transposition: {} swaps places with the duplicate", agentName(bm, cleric_idx));
    return true;
}

int CombatEngine::layOnHands(BattleMap& bm, int caster_idx, int target_idx, int amount) noexcept
{
    // Fetch caster's Lay on Hands pool
    Agent::Stats caster_stats = bm.getAgentStats(caster_idx);
    if (caster_stats.hp_max == 0 && caster_stats.hp_cur == 0) return -1;  // invalid caster idx

    Resource* pool = caster_stats.getResource("Lay on Hands");
    if (!pool) return -1;  // No Lay on Hands resource
    if (pool->current <= 0) return -1;  // Pool depleted

    // Fetch target stats
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    if (tgt_stats.hp_max == 0 && tgt_stats.hp_cur == 0) return -1;  // invalid target idx

    // Clamp amount to: min(pool remaining, target HP deficit)
    int hp_deficit = tgt_stats.effectiveMaxHp() - tgt_stats.hp_cur;
    int clamped = std::min(amount, std::min(pool->current, hp_deficit));

    if (clamped <= 0) return 0;  // Nothing to heal

    // Apply healing to target
    healAgent(bm, target_idx, clamped);

    // Decrement pool
    pool->current = std::max(0, pool->current - clamped);
    caster_stats.resources["Lay on Hands"] = *pool;
    bm.setAgentStats(caster_idx, caster_stats);

    return clamped;
}

bool CombatEngine::spendLuckForAdvantage(BattleMap& bm, int idx)
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return false;  // invalid idx
    if (!s.hasFeat("Lucky") || s.luck_points <= 0) return false;
    s.luck_points -= 1;
    bm.setAgentStats(idx, s);
    grantPendingAdvantage(true);   // consumed by the agent's next d20 roll
    log_("{} spends a Luck Point for Advantage ({} remaining)",
         agentName(bm, idx), s.luck_points);
    return true;
}

TerrainTickResult CombatEngine::tickTerrainForTurn(BattleMap& bm, int agent_idx)
{
    TerrainTickResult result;

    // Snapshot which of this source's terrain effects are concentration-bound,
    // so we can detect a concentration spell ending by natural expiry.
    std::unordered_set<int> concentration_ids;
    for (const auto& eff : bm.activeTerrainEffects()) {
        if (eff.source_agent_idx == agent_idx && eff.requires_concentration)
            concentration_ids.insert(eff.id);
    }

    result.expired_terrain_ids = bm.tickTerrainEffects(agent_idx);

    // If a concentration terrain expired, the caster's concentration ends —
    // drop it (and cascade removal of the spell's other effects/conditions).
    for (int id : result.expired_terrain_ids) {
        if (concentration_ids.count(id)) {
            result.concentration = dropConcentration(bm, agent_idx);
            break;
        }
    }

    return result;
}

void CombatEngine::tickLightEffectsForTurn(BattleMap& bm, int agent_idx) noexcept
{
    // Tick the agent's own light effects (e.g., Darkness, Shadow Arts: Darkness)
    auto expired = bm.tickLightEffects(agent_idx);

    // Also tick DM-placed light effects (they affect everyone)
    auto dm_expired = bm.tickDmLightEffects();
    expired.insert(expired.end(), dm_expired.begin(), dm_expired.end());

    // For each expired light effect, re-evaluate blinding for all agents who were inside.
    // (We don't have the expired effect's cell_indices anymore, so we'll re-run updateDarknessBlinding
    //  for all agents — a bit conservative but safe.)
    if (!expired.empty()) {
        const auto& agents = bm.placedAgents();
        for (std::size_t i = 0; i < agents.size(); ++i) {
            updateDarknessBlinding(bm, static_cast<int>(i));
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Rests
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyLongRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);

        // Restore spell slots and all resources
        stats.restore_resources_long_rest();

        // Spell Thief (Arcane Trickster L17): the 8-hour lock on a stolen spell clears on a long rest.
        stats.stolen_spell_names.clear();

        // Long rest restores all Hit Points and clears any max-HP reduction (vampiric drain, etc.).
        // The dead stay dead (not revived).
        stats.available_hit_points = 0;
        Agent::Conditions rest_cond = bm.getAgentConditions(agent_idx);
        if (!rest_cond.dead) {
            stats.hp_cur = stats.hp_max;
            // If the agent was downed but survived the rest, clear the downed /
            // death-save state so they aren't left flagged unconscious at full HP.
            if (rest_cond.unconscious) {
                rest_cond.unconscious        = false;
                rest_cond.incapacitated      = false;
                rest_cond.prone              = false;
                rest_cond.stabilized         = false;
                rest_cond.death_save_successes = 0;
                rest_cond.death_save_failures  = 0;
                bm.setAgentConditions(agent_idx, rest_cond);
            }
        }

        // Initialize Arcane Ward for Abjurers at L3+
        if (stats.character_class == Wizard && stats.wizard_subclass == AbjurerPath && stats.char_level >= 3) {
            stats.temp_hp = stats.char_level;
        }

        // TASK E: Celestial Resilience (Celestial L10): temp HP on long rest
        if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        }

        // Warrior of the Elements — Elemental Attunement ends on a long rest (clear the active flag and
        // the unarmed damage-type override it set).
        if (stats.character_class == CharacterClass::Monk && stats.unarmed_damage_override >= 0)
            stats.unarmed_damage_override = -1;
        {
            Agent::Conditions ec = bm.getAgentConditions(agent_idx);
            if (ec.elemental_attunement_active) {
                ec.elemental_attunement_active = false;
                bm.setAgentConditions(agent_idx, ec);
            }
        }

        // Clockwork L6 Bastion of Law: the ward lasts "until you finish a Long Rest" — clear it here.
        stats.bastion_ward = 0;

        // Aberrant L14 Revelation in Flesh: if still active, end it and restore the prior speeds/truesight.
        if (stats.revelation_in_flesh_turns > 0) {
            stats.speed_fly       = stats.revelation_prior_fly;
            stats.speed_swim      = stats.revelation_prior_swim;
            stats.truesight_range = stats.revelation_prior_truesight;
            stats.revelation_in_flesh_turns = 0;
        }

        // Paladin Oath of Vengeance L20 Avenging Angel: if still active, end it and restore the Fly speed.
        if (stats.avenging_angel_turns > 0) {
            stats.speed_fly = stats.avenging_angel_prior_fly;
            stats.avenging_angel_turns = 0;
        }

        // Paladin Oath of the Ancients L15 Undying Sentinel: recharge the once-per-long-rest use.
        stats.undying_sentinel_used = false;
        // Elder Champion (L20): end any lingering form (it lasts only 1 minute, but be safe).
        stats.elder_champion_turns = 0;
        // Paladin Oath of Glory L20 Living Legend: end any lingering form on a long rest.
        stats.living_legend_turns = 0;

        // Zealot L14 Rage of the Gods is usable once per long rest — restore it here.
        if (stats.character_class == CharacterClass::Barbarian &&
            stats.barbarian_subclass == ZealotPath)
            stats.rage_of_gods_used = false;

        // Evoker L14 Overchannel: the next use is free again after a Long Rest.
        stats.overchannel_uses = 0;

        // Save stats back (includes resource restoration)
        bm.setAgentStats(agent_idx, stats);

        // Regenerate Portent Dice for Diviners
        if (stats.character_class == Wizard && stats.wizard_subclass == DivinierPath) {
            regeneratePortentDice(bm, agent_idx);
        }

        log_("{} completed long rest: resources restored, Portent Dice regenerated", agentName(bm, agent_idx));
    }
}

void CombatEngine::applyShortRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);
        stats.restore_resources_short_rest();  // Warlock pact slots, Monk Ki, etc.

        // TASK E: Celestial Resilience (Celestial L10): temp HP on short rest
        if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        }

        // Warrior of the Elements — Elemental Attunement ends on a short rest too.
        if (stats.character_class == CharacterClass::Monk && stats.unarmed_damage_override >= 0)
            stats.unarmed_damage_override = -1;
        {
            Agent::Conditions ec = bm.getAgentConditions(agent_idx);
            if (ec.elemental_attunement_active) {
                ec.elemental_attunement_active = false;
                bm.setAgentConditions(agent_idx, ec);
            }
        }

        bm.setAgentStats(agent_idx, stats);

        // House rule: a short rest heals each creature for half its (drained-adjusted) maximum HP.
        // Route through healAgent so a downed-but-living creature is brought back to consciousness
        // and rejoins the initiative rotation (reviveOnHeal clears unconscious/stabilized/death saves);
        // true-dead corpses are skipped so a short rest never revives them.
        if (!bm.getAgentConditions(agent_idx).dead) {
            int heal = stats.effectiveMaxHp() / 2;
            if (heal > 0) {
                healAgent(bm, agent_idx, heal);
                Agent::Stats healed = bm.getAgentStats(agent_idx);
                log_("{} completed short rest: short-rest resources restored, regained {} HP (now {}/{})",
                     agentName(bm, agent_idx), heal, healed.hp_cur, healed.effectiveMaxHp());
                continue;
            }
        }
        log_("{} completed short rest: short-rest resources restored", agentName(bm, agent_idx));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Class activations
// ─────────────────────────────────────────────────────────────────────────────

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
        int vitality_temp_hp = stats.char_level;
        grantTempHp(stats, vitality_temp_hp);  // entry THP is NOT rage-tagged: it persists past Rage end
        log_("{} grants Vitality: {} temp HP", agentName(bm, idx), vitality_temp_hp);
    }

    // Berserker L6: Mindless Rage - clear Charmed and Frightened conditions
    if (stats.barbarian_subclass == BerserkerPath && stats.char_level >= 6) {
        cond.charmed = false;
        cond.frightened = false;
        log_("{} Mindless Rage: charmed/frightened cleared", agentName(bm, idx));
    }

    // Wild Heart L6: Aspect of the Wilds - apply aspect bonuses
    if (stats.barbarian_subclass == WildHeartPath && stats.char_level >= 6) {
        if (stats.wild_heart_aspect == OwlAspect) {
            stats.darkvision_range = std::max(stats.darkvision_range, 60);
            log_("{} Owl Aspect: darkvision 60 ft", agentName(bm, idx));
        } else if (stats.wild_heart_aspect == SalmonAspect) {
            stats.speed_swim = std::max(stats.speed_swim, stats.speed_walk);
            log_("{} Salmon Aspect: swim speed = walk speed ({})", agentName(bm, idx), stats.speed_walk);
        }
    }

    // Reset Zealot Fanatical Focus flag on Rage activation (can use once per Rage)
    if (stats.barbarian_subclass == ZealotPath && stats.char_level >= 6) {
        cond.fanatical_focus_used = false;
        log_("{} Fanatical Focus: ready for use this Rage", agentName(bm, idx));
    }

    // Wild Heart L14 — Power of the Wilds: the chosen option (Falcon/Lion/Ram) applies for
    // the duration of this Rage. Ram is an on-hit melee rider (handled in applyAttackResult);
    // Falcon grants a Fly Speed (only while unarmored); Lion sets the disadvantage-aura flag.
    if (stats.barbarian_subclass == WildHeartPath && stats.char_level >= 14) {
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
    if (stats.barbarian_subclass == WorldTreePath && stats.char_level >= 14) {
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
    if (stats.char_level >= 7) {
        walkRemaining_[idx] += stats.speed_walk / 2;
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
    if (stats.barbarian_subclass == WildHeartPath && stats.char_level >= 6) {
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
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Necrotic)] = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Psychic)]  = 1.0f;
        stats.magic_damage_multipliers[static_cast<std::size_t>(MagicDamage_t::Radiant)]  = 1.0f;
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
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != BerserkerPath ||
        stats.char_level < 14) {
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

        if (areAllies(bm, idx, target_idx)) continue;  // Skip allies (enemies only)

        // Roll WIS save for the target
        const int wis_save_mod = saveModFor(bm, target_idx, SaveWis);

        const int save_d20 = roll(20);
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

bool CombatEngine::activateClairvoyantCombatant(BattleMap& bm, int warlock_idx, int target_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (warlock_idx < 0 || warlock_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx == warlock_idx) return false;

    Agent::Stats stats = bm.getAgentStats(warlock_idx);

    // Gate on Great Old One L6+
    if (stats.character_class != CharacterClass::Warlock ||
        stats.warlock_subclass != GreatOldOnePath ||
        stats.char_level < 6) {
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
    const int save_dc  = spellSaveDcFromAbility(stats, SaveCha);
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
    if (stats.character_class != CharacterClass::Warlock ||
        stats.warlock_subclass != CelestialPath || stats.char_level < 14) return false;
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

bool CombatEngine::useZealousPresence(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Gate on Zealot L10+
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != ZealotPath ||
        stats.char_level < 10) {
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
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != ZealotPath ||
        stats.char_level < 14 ||
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
    if (stats.character_class != CharacterClass::Barbarian ||
        stats.barbarian_subclass != WorldTreePath ||
        stats.char_level < 14 ||
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
    if (stats.character_class != CharacterClass::Barbarian || stats.char_level < 3)
        return false;

    if (!cond.raging)
        return false;

    // Only Acrobatics and Stealth are relevant for combat
    if (skill_name == "Acrobatics" || skill_name == "Stealth")
        return true;

    return false;
}

int CombatEngine::activateSacredWeapon(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return -1;  // invalid idx

    // Requires a Paladin who has taken the Oath of Devotion.
    if (stats.character_class != CharacterClass::Paladin ||
        stats.paladin_oath != OathOfDevotionPath) return -1;

    // Needs an available Channel Oath use.
    Resource* co = stats.getResource("Channel Oath");
    if (!co || co->current <= 0) return -1;

    // Bonus = CHA modifier (minimum +1), floored correctly for odd negative scores.
    int cha_mod = (stats.cha - 10) / 2;
    if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --cha_mod;
    int bonus = std::max(1, cha_mod);

    // Spend 1 Channel Oath use, then re-fetch so we keep that decrement.
    spendResource(bm, idx, "Channel Oath", 1);
    stats = bm.getAgentStats(idx);
    stats.sacred_weapon_bonus = bonus;
    stats.sacred_weapon_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Sacred Weapon: +{} to weapon attack rolls for 1 minute",
         agentName(bm, idx), bonus);
    return bonus;
}

// Paladin Oath of Vengeance — Vow of Enmity (L3). Spend one Channel Oath use to swear
// enmity against a creature within 30 ft: the paladin gains Advantage on attacks against
// it for 1 minute (or until this feature is used again). Returns true on success.
bool CombatEngine::activateVowOfEnmity(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return false;
    if (target_idx == idx) return false;

    Agent::Stats stats = bm.getAgentStats(idx);

    // Requires a Paladin who has taken the Oath of Vengeance.
    if (stats.character_class != CharacterClass::Paladin ||
        stats.paladin_oath != OathOfVengeancePath) return false;

    // Needs an available Channel Oath use.
    Resource* co = stats.getResource("Channel Oath");
    if (!co || co->current <= 0) return false;

    // Target must be a visible enemy within 30 ft.
    if (areAllies(bm, idx, target_idx)) return false;
    const PlacedAgent& sp = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    const int dist_ft = footprintDistance(sp.origin, sp.agent->getSize(),
                                          tp.origin, tp.agent->getSize()) * 5;
    if (dist_ft > 30) {
        log_("{} is more than 30 ft away — Vow of Enmity fails", agentName(bm, target_idx));
        return false;
    }
    if (!bm.hasLineOfSight(sp.origin, sp.agent->getSize(), tp.origin, tp.agent->getSize())) {
        log_("{} can't see {} — Vow of Enmity fails",
             agentName(bm, idx), agentName(bm, target_idx));
        return false;
    }

    // Spend 1 Channel Oath use, then re-fetch so we keep that decrement.
    spendResource(bm, idx, "Channel Oath", 1);
    stats = bm.getAgentStats(idx);
    stats.vow_of_enmity_target = target_idx;   // overwrites any prior vow ("until you use this again")
    stats.vow_of_enmity_turns  = 10;           // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} swears a Vow of Enmity against {}: Advantage on attacks against it for 1 minute",
         agentName(bm, idx), agentName(bm, target_idx));
    return true;
}

// Paladin Oath of Vengeance — Avenging Angel (L20). Bonus action, 10 minutes: gain a Fly Speed of
// 60 ft (+ hover) and a Frightful Aura inside the Aura of Protection (applied at enemy turn start in
// beginTurn). Costs one "Avenging Angel" use per long rest, or a level-5 spell slot when exhausted.
bool CombatEngine::activateAvengingAngel(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Paladin ||
        s.paladin_oath != OathOfVengeancePath || s.char_level < 20) {
        log_("{} cannot use Avenging Angel (not a L20 Oath of Vengeance paladin)", agentName(bm, idx));
        return false;
    }
    if (s.avenging_angel_turns > 0) {
        log_("{}'s Avenging Angel is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    // Cost: one Avenging Angel use, or — when exhausted — a level-5 spell slot.
    Resource* aa = s.getResource("Avenging Angel");
    const bool has_use = aa && aa->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Avenging Angel (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        aa->spend(1);
        s.resources["Avenging Angel"] = *aa;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Avenging Angel", agentName(bm, idx));
    }

    // Snapshot the prior Fly speed so it reverts on expiry (beginTurn) — then grant Fly 60 + hover.
    s.avenging_angel_prior_fly = s.speed_fly;
    s.speed_fly = std::max(s.speed_fly, 60);
    s.avenging_angel_turns = 100;   // 10 minutes
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} becomes an Avenging Angel: Fly 60 ft (hover) and a Frightful Aura for 10 minutes",
         agentName(bm, idx));
    return true;
}

// Paladin Oath of the Ancients — Elder Champion (L20). Bonus action, 1 minute: regain 10 HP at the
// start of each of your turns, and enemies in your Aura of Protection have Disadvantage on saves vs
// your spells & Channel Oath options (applied in rollSpellSave). Costs one "Elder Champion" use per
// long rest, or a level-5 spell slot when exhausted. (Swift Spells is deferred — see known_limitations.)
bool CombatEngine::activateElderChampion(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Paladin ||
        s.paladin_oath != OathOfAncientsPath || s.char_level < 20) {
        log_("{} cannot use Elder Champion (not a L20 Oath of the Ancients paladin)", agentName(bm, idx));
        return false;
    }
    if (s.elder_champion_turns > 0) {
        log_("{}'s Elder Champion is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    Resource* ec = s.getResource("Elder Champion");
    const bool has_use = ec && ec->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Elder Champion (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        ec->spend(1);
        s.resources["Elder Champion"] = *ec;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Elder Champion", agentName(bm, idx));
    }

    s.elder_champion_turns = 10;   // 1 minute
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} channels primal power (Elder Champion): 10 HP/turn regen and Disadvantage on enemy saves "
         "vs your spells for 1 minute", agentName(bm, idx));
    return true;
}

// Paladin Oath of Glory — Inspiring Smite (L3). Immediately after casting Divine Smite this turn,
// spend one Channel Oath use to grant a creature within 30 ft (may be self) 2d8 + Paladin level
// temporary HP. Returns the temp HP granted, or -1 if not allowed. (RAW lets you split the pool
// among several creatures; this grants the whole pool to one chosen creature — see known_limitations.)
int CombatEngine::activateInspiringSmite(BattleMap& bm, int idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Paladin || s.paladin_oath != OathOfGloryPath) return -1;

    // Must immediately follow a Divine Smite this turn, and only once per turn.
    const Agent::Conditions ic = bm.getAgentConditions(idx);
    if (!ic.divine_smite_used || ic.inspiring_smite_used) return -1;

    Resource* co = s.getResource("Channel Oath");
    if (!co || co->current <= 0) return -1;

    // Target must be within 30 ft (may be the paladin itself).
    const PlacedAgent& sp = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    if (footprintDistance(sp.origin, sp.agent->getSize(), tp.origin, tp.agent->getSize()) * 5 > 30) {
        log_("{} is more than 30 ft away — Inspiring Smite fails", agentName(bm, target_idx));
        return -1;
    }

    const int pool = roll(8) + roll(8) + s.char_level;   // 2d8 + Paladin level
    spendResource(bm, idx, "Channel Oath", 1);

    // Mark used this turn (re-fetch conditions in case spendResource touched them).
    Agent::Conditions pc = bm.getAgentConditions(idx);
    pc.inspiring_smite_used = true;
    bm.setAgentConditions(idx, pc);

    Agent::Stats ts = bm.getAgentStats(target_idx);
    grantTempHp(ts, pool, idx);
    bm.setAgentStats(target_idx, ts);

    log_("{} channels Inspiring Smite: {} temporary HP to {}",
         agentName(bm, idx), pool, agentName(bm, target_idx));
    return pool;
}

// Paladin Oath of Glory — Living Legend (L20). Bonus action, 10 minutes: gain a reaction to reroll a
// failed saving throw (Living Legend save-reroll) and, once on each of your turns, turn a weapon miss
// into a hit (Unerring Strike). Costs one "Living Legend" use per long rest, or a level-5 spell slot
// when exhausted. (Charismatic — Advantage on CHA checks — is non-combat and not modeled.)
bool CombatEngine::activateLivingLegend(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Paladin ||
        s.paladin_oath != OathOfGloryPath || s.char_level < 20) {
        log_("{} cannot use Living Legend (not a L20 Oath of Glory paladin)", agentName(bm, idx));
        return false;
    }
    if (s.living_legend_turns > 0) {
        log_("{}'s Living Legend is already active", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;

    Resource* ll = s.getResource("Living Legend");
    const bool has_use = ll && ll->current > 0;
    const bool can_spend_slot = s.spell_slots_remaining[4] > 0;   // index 4 = level-5 slots
    if (!has_use && !can_spend_slot) {
        log_("{} cannot use Living Legend (no use or level-5 slot available)", agentName(bm, idx));
        return false;
    }
    if (has_use) {
        ll->spend(1);
        s.resources["Living Legend"] = *ll;
    } else {
        s.spell_slots_remaining[4] -= 1;
        log_("{} spends a level-5 spell slot to restore Living Legend", agentName(bm, idx));
    }

    s.living_legend_turns = 100;   // 10 minutes
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);

    log_("{} becomes a Living Legend: save-reroll reaction and once-per-turn Unerring Strike for 10 minutes",
         agentName(bm, idx));
    return true;
}

bool CombatEngine::activateCoronaOfLight(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return false;  // invalid idx

    // Requires a Light Domain Cleric of level 17+.
    if (stats.character_class != CharacterClass::Cleric ||
        stats.cleric_subclass != LightDomain || stats.char_level < 17) return false;

    stats.corona_of_light_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Corona of Light: enemies within 60 ft have Disadvantage on saves vs its "
         "Fire/Radiant spells for 1 minute", agentName(bm, idx));
    return true;
}

bool CombatEngine::activateInnateSorcery(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return false;

    // Normally requires an available Innate Sorcery use (Bonus Action; 2 uses per long rest).
    // Sorcery Incarnate (L7): with the uses spent, 2 Sorcery Points buy an activation instead.
    // Both resources are spent on this local `stats` copy (not via spendResource) so the single
    // setAgentStats below writes the spend AND the duration — a bm-side spend would be clobbered.
    Resource* innate = stats.getResource("Innate Sorcery");
    bool paid_with_sp = false;
    if (innate && innate->current > 0) {
        innate->spend(1);
    } else if (stats.char_level >= 7) {
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
    return s.character_class == CharacterClass::Sorcerer &&
           s.char_level >= 7 && s.innate_sorcery_turns > 0;
}

bool CombatEngine::activateDragonWings(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::DraconicPath ||
        stats.char_level < 14) {
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
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::DraconicPath ||
        stats.char_level < 6 || stats.draconic_affinity_type < 0) {
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
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        stats.char_level < 14) {
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
    if (caster.character_class != CharacterClass::Sorcerer ||
        caster.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        caster.char_level < 6) {
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
    if (caster.character_class != CharacterClass::Sorcerer ||
        caster.sorcerer_subclass != SorcererSubclass::ClockworkPath ||
        caster.char_level < 18) {
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
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx != tgt_idx) continue;
            clearSpellConditionEffect(bm, cond);
            to_remove.push_back(cond.condition_id);
        }
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
    if (s.character_class != CharacterClass::Sorcerer ||
        s.sorcerer_subclass != SorcererSubclass::AberrantPath || s.char_level < 14) {
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
    if (caster.character_class != CharacterClass::Sorcerer ||
        caster.sorcerer_subclass != SorcererSubclass::AberrantPath || caster.char_level < 18) {
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
    const int dc = spellSaveDcFromAbility(caster, SaveDex);
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

bool CombatEngine::useMagicalCunning(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.character_class != Warlock) return false;

    Resource* mc = stats.getResource("Magical Cunning");
    if (!mc || mc->current <= 0) return false;  // not available / already used

    const int lvl = stats.pact_slot_level();
    if (lvl < 1) return false;
    const std::size_t i = static_cast<std::size_t>(lvl - 1);
    const int maxs = stats.spell_slots_max[i];
    const int expended = maxs - stats.spell_slots_remaining[i];
    if (expended <= 0) return false;  // nothing to recover

    // ceil(max/2), or all expended at L20 (Eldritch Master).
    const int recover = (stats.char_level >= 20) ? expended
                                                 : std::min(expended, (maxs + 1) / 2);
    stats.spell_slots_remaining[i] += recover;
    mc->spend();
    bm.setAgentStats(agent_idx, stats);
    log_("{}: Magical Cunning recovers {} pact slot(s).", agentName(bm, agent_idx), recover);

    // TASK E: Celestial Resilience (Celestial L10): temp HP on Magical Cunning use
    if (stats.character_class == CharacterClass::Warlock && stats.warlock_subclass == CelestialPath && stats.char_level >= 10) {
        int chaMod = (stats.cha - 10) / 2;
        if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
        stats.temp_hp = std::max(stats.temp_hp, stats.char_level + chaMod);
        bm.setAgentStats(agent_idx, stats);
        log_("{}: Celestial Resilience grants {} temp HP", agentName(bm, agent_idx), stats.char_level + chaMod);
    }

    return true;
}

int CombatEngine::useHealingLight(BattleMap& bm, int healer_idx, int target_idx, int num_dice)
{
    auto agents = bm.placedAgents();
    if (healer_idx < 0 || healer_idx >= static_cast<int>(agents.size())) return 0;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats healer_stats = bm.getAgentStats(healer_idx);
    if (healer_stats.character_class != CharacterClass::Warlock || healer_stats.warlock_subclass != CelestialPath ||
        healer_stats.char_level < 3) {
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
    target_stats.hp_cur = std::min(target_stats.effectiveMaxHp(), target_stats.hp_cur + total_healing);
    bm.setAgentStats(target_idx, target_stats);
    reviveOnHeal(bm, target_idx);   // a healed downed ally rejoins initiative

    log_("{}: Healing Light: {} d6 = {} healing to {}", agentName(bm, healer_idx), num_dice, total_healing, agentName(bm, target_idx));
    return healed;
}

TurnUndeadResult CombatEngine::useTurnUndead(BattleMap& bm, int caster_idx)
{
    TurnUndeadResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return result;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.character_class != CharacterClass::Cleric || caster.char_level < 2) return result;

    Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return result;

    result.valid   = true;
    result.save_dc = spellSaveDcFromAbility(caster, SaveWis);

    int wisMod = (caster.wis - 10) / 2;
    if (caster.wis < 10 && (caster.wis - 10) % 2 != 0) --wisMod;

    // Sear Undead (L5+): roll WIS-mod d8 (minimum 1d8) ONCE; each failed undead takes that total.
    int sear_total = 0;
    if (caster.char_level >= 5) {
        int sear_dice = std::max(1, wisMod);
        for (int i = 0; i < sear_dice; ++i) sear_total += roll(8);
        result.sear_damage = sear_total;
    }

    // Expend one Channel Divinity use (cd points into caster.resources; persist below).
    cd->spend(1);
    bm.setAgentStats(caster_idx, caster);
    log_("{} uses Turn Undead (DC {})", agentName(bm, caster_idx), result.save_dc);

    const Cell c_origin = agents[static_cast<std::size_t>(caster_idx)].origin;

    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == caster_idx) continue;
        Agent::Stats tgt = bm.getAgentStats(i);
        if (!tgt.is_undead) continue;

        // Within 30 ft (Euclidean cell distance × 5 ft), matching Sphere targeting.
        const Cell o = agents[static_cast<std::size_t>(i)].origin;
        const double dx = o.col - c_origin.col, dy = o.row - c_origin.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) continue;

        int mod = (tgt.wis - 10) / 2;
        if (tgt.wis < 10 && (tgt.wis - 10) % 2 != 0) --mod;
        if (tgt.save_prof_wis) mod += tgt.prof_bonus;
        const int save_total = roll(20, mod);

        if (save_total >= result.save_dc) {
            result.resisted.push_back(i);
            log_("Turn Undead: {} resists ({} vs DC {})", agentName(bm, i), save_total, result.save_dc);
            continue;
        }

        // Sear damage is dealt BEFORE the conditions are applied, so the on-damage "ends" rule
        // doesn't immediately cancel the Frightened/Incapacitated we're about to add.
        if (sear_total > 0) {
            damageAgent(bm, i, sear_total);
            checkConcentrationOnDamage(bm, i, sear_total);
            processDamageTaken(bm, i, sear_total);
        }

        // Frightened + Incapacitated for 1 minute; ends early if the undead takes damage.
        for (const char* cname : {"Frightened", "Incapacitated"}) {
            ActiveAgentCondition cond;
            cond.agent_idx        = i;
            cond.caster_idx       = caster_idx;   // fear source (used by Frightened movement rule)
            cond.condition_name   = cname;
            cond.save_ability     = SaveWis;
            cond.save_dc          = result.save_dc;
            cond.save_repeat_turns = -1;          // no per-turn save; ends on damage / after 1 min
            cond.turns_remaining  = 10;           // 1 minute
            cond.on_damage        = OnDamage_t::End;
            cond.next_save_turn   = 0;
            (void)addAgentCondition(bm, cond);
        }
        result.turned.push_back(i);
        log_("Turn Undead: {} is Turned ({} vs DC {})", agentName(bm, i), save_total, result.save_dc);
    }

    return result;
}

bool CombatEngine::lifeSupremeHealing(const Agent::Stats& s) const noexcept
{
    return s.character_class == CharacterClass::Cleric &&
           s.cleric_subclass == LifeDomain && s.char_level >= 17;
}

int CombatEngine::discipleOfLifeBonus(const Agent::Stats& s, int slot_level) const noexcept
{
    if (s.character_class == CharacterClass::Cleric &&
        s.cleric_subclass == LifeDomain && s.char_level >= 3 && slot_level >= 1)
        return 2 + slot_level;
    return 0;
}

PreserveLifeResult CombatEngine::usePreserveLife(BattleMap& bm, int caster_idx,
                                                 const std::vector<int>& targets)
{
    PreserveLifeResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return result;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.character_class != CharacterClass::Cleric ||
        caster.cleric_subclass != LifeDomain || caster.char_level < 3) return result;

    Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return result;

    result.valid = true;
    result.pool  = 5 * caster.char_level;
    int pool     = result.pool;

    // Expend one Channel Divinity use.
    cd->spend(1);
    bm.setAgentStats(caster_idx, caster);
    log_("{} uses Preserve Life ({} HP pool)", agentName(bm, caster_idx), result.pool);

    const Cell c_origin = agents[static_cast<std::size_t>(caster_idx)].origin;

    // Distribute the pool in the caller's chosen order; each creature is restored to no more than
    // half its HP maximum. Undead cannot benefit.
    for (int t : targets) {
        if (pool <= 0) break;
        if (t < 0 || t >= static_cast<int>(agents.size())) continue;
        Agent::Stats tgt = bm.getAgentStats(t);
        if (tgt.is_undead) continue;
        if (tgt.hp_cur <= 0 && tgt.hp_max <= 0) continue;

        // Within 30 ft (Euclidean cell distance × 5 ft), matching Emanation targeting.
        const Cell o = agents[static_cast<std::size_t>(t)].origin;
        const double dx = o.col - c_origin.col, dy = o.row - c_origin.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) continue;

        const int cap = tgt.hp_max / 2;          // can restore up to half its HP max
        if (tgt.hp_cur >= cap) continue;          // already at/above the cap → no healing
        const int give = std::min(pool, cap - tgt.hp_cur);
        if (give <= 0) continue;

        tgt.hp_cur += give;
        pool       -= give;
        bm.setAgentStats(t, tgt);
        reviveOnHeal(bm, t);

        result.healed.push_back(t);
        result.amounts.push_back(give);
        result.spent += give;
        log_("Preserve Life: {} regains {} HP (to {}/{})",
             agentName(bm, t), give, tgt.hp_cur, tgt.hp_max);
    }

    return result;
}

bool CombatEngine::usePortentDie(BattleMap& bm, int agent_idx, int die_index, int current_round) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard with Portent Dice resource
    if (stats.character_class != Wizard || stats.wizard_subclass != DivinierPath) {
        log_("{} is not a Diviner Wizard", agentName(bm, agent_idx));
        return false;
    }

    auto* portent_res = stats.getResource("Portent Dice");
    if (!portent_res) {
        log_("{} has no Portent Dice resource", agentName(bm, agent_idx));
        return false;
    }

    // Check if this agent already used a portent this round
    auto it = agent_portent_round_used_.find(agent_idx);
    if (it != agent_portent_round_used_.end() && it->second == current_round) {
        log_("{} already used Portent Dice in round {}", agentName(bm, agent_idx), current_round);
        return false;
    }

    // Check if die_index is valid and portent_dice has that index
    if (die_index < 0 || die_index >= static_cast<int>(stats.portent_dice.size())) {
        log_("{} has no portent die at index {}", agentName(bm, agent_idx), die_index);
        return false;
    }

    // Get the die value and remove it from the deque
    int die_value = stats.portent_dice[static_cast<std::size_t>(die_index)];
    stats.portent_dice.erase(stats.portent_dice.begin() + die_index);

    // Decrement the resource
    portent_res = stats.getResource("Portent Dice");
    if (portent_res) {
        portent_res->current = std::max(0, portent_res->current - 1);
    }

    // Set pending portent for next roll
    pending_portent_die_ = die_value;

    // Track that this agent used a portent in this round
    agent_portent_round_used_[agent_idx] = current_round;

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} using Portent Die: value={}, remaining={}/{}",
         agentName(bm, agent_idx), die_value, portent_res ? portent_res->current : 0,
         portent_res ? portent_res->max : 0);

    return true;
}

bool CombatEngine::grantBardicDie(BattleMap& bm, int agent_idx, int d) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    // RAW: a creature holds only one Bardic Inspiration die at a time; overwrite.
    stats.bardic_inspiration_die = d;
    bm.setAgentStats(agent_idx, stats);

    log_("{} gains a Bardic Inspiration d{}", agentName(bm, agent_idx), d);
    return true;
}

int CombatEngine::useBardicDie(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);            // roll the held die (1..d)
    pending_roll_bonus_ = value;    // fold into the agent's NEXT d20 Test
    stats.bardic_inspiration_die = 0;  // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next D20 Test",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::useBardicDieForDamage(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);                   // roll the held die (1..d)
    pending_damage_bonus_ = value;         // fold into the attacker's NEXT weapon damage roll
    stats.bardic_inspiration_die = 0;     // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next weapon damage roll",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::bardRegainInspirationFromSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.character_class != CharacterClass::Bard || stats.char_level < 5) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;  // no slot of that level to spend

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current >= bi->max) return -1;          // nothing to regain → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    bi->gain(1);
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends a level-{} slot (Font of Inspiration): Bardic Inspiration now {}/{}",
         agentName(bm, agent_idx), slot_level, bi->current, bi->max);
    return bi->current;
}

bool CombatEngine::activateMantleOfMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 6) return false;

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left → don't open the window

    // Spend the use (spendResource re-reads/writes stats internally).
    spendResource(bm, bard_idx, "Mantle of Majesty", 1);

    // The "unearthly appearance" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears mantle_majesty_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.mantle_majesty_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Mantle of Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on an unearthly appearance (Mantle of Majesty): may cast Command as a Bonus "
         "Action with no slot for 1 minute", agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreMantleOfMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 6) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Mantle of Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::activateUnbreakableMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 14) return false;

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left

    // Spend the use
    spendResource(bm, bard_idx, "Unbreakable Majesty", 1);

    // The "majestic presence" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears majestic_presence_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.majestic_presence_turns = 10;  // 1 minute = 10 rounds
    stats.majesty_checked_this_turn = false;  // fresh turn, ready to check
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Unbreakable Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on a majestic presence (Unbreakable Majesty): melee attacks against {} trigger "
         "Psychic damage and a CHA save for 1 minute", agentName(bm, bard_idx), agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreUnbreakableMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != GlamourPath || stats.char_level < 14) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Unbreakable Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::bardBeguilingMagic(BattleMap& bm, int bard_idx, int target_idx,
                                      bool use_frightened) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (bard_idx < 0 || bard_idx >= n || target_idx < 0 || target_idx >= n || target_idx == bard_idx)
        return false;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.character_class != CharacterClass::Bard ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.char_level < 3) {
        log_("{} cannot use Beguiling Magic (not a L3+ College of Glamour Bard)", agentName(bm, bard_idx));
        return false;
    }
    const Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current <= 0) {
        log_("{} has no Beguiling Magic use available", agentName(bm, bard_idx));
        return false;
    }
    // Must be a creature the bard can see within 60 ft (the GUI also gates LOS/perception).
    const int dist_ft = footprintDistance(agents[bard_idx].origin, agents[bard_idx].agent->getSize(),
                                          agents[target_idx].origin, agents[target_idx].agent->getSize()) * 5;
    if (dist_ft > 60) {
        log_("Beguiling Magic: {} is more than 60 ft away", agentName(bm, target_idx));
        return false;
    }

    // Using the benefit spends the use whether or not the target ultimately fails its save.
    spendResource(bm, bard_idx, "Beguiling Magic", 1);

    const char* cond_name = use_frightened ? "Frightened" : "Charmed";
    const int   dc        = spellSaveDc(bs);
    const int   save_mod  = saveModFor(bm, target_idx, SaveWis);
    const int   save_roll = roll(20, save_mod);

    if (save_roll >= dc) {
        log_("{} resists Beguiling Magic (WIS save {} vs DC {})", agentName(bm, target_idx), save_roll, dc);
        return true;
    }
    // Frightened can be refused outright by Aura of Courage — the use is still spent.
    if (use_frightened && hasAuraOfCourage(bm, target_idx)) {
        log_("{} can't be Frightened (Aura of Courage) — Beguiling Magic has no effect",
             agentName(bm, target_idx));
        return true;
    }

    ActiveAgentCondition cond;
    cond.agent_idx        = target_idx;
    cond.caster_idx       = bard_idx;
    cond.condition_name   = cond_name;
    cond.turns_remaining  = 10;            // 1 minute = 10 rounds (ticked on the bard's turns)
    cond.save_ability     = SaveWis;
    cond.save_dc          = dc;
    cond.save_repeat_turns = 1;            // repeats at the start of each of the target's turns
    cond.next_save_turn   = 0;
    (void)addAgentCondition(bm, cond);
    log_("{} fails vs Beguiling Magic and is {} for 1 minute (WIS save {} vs DC {})",
         agentName(bm, target_idx), cond_name, save_roll, dc);
    return true;
}

int CombatEngine::bardRestoreBeguilingMagic(BattleMap& bm, int bard_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.character_class != CharacterClass::Bard ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.char_level < 3) return -1;

    Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current >= beg->max) return -1;   // already full → don't waste an Inspiration
    const Resource* bi = bs.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) return -1;            // no Bardic Inspiration use to spend

    spendResource(bm, bard_idx, "Bardic Inspiration", 1);
    // Re-read stats: spendResource mutated them; gain on a fresh copy and write back.
    bs = bm.getAgentStats(bard_idx);
    beg = bs.getResource("Beguiling Magic");
    if (!beg) return -1;
    beg->gain(1);
    bm.setAgentStats(bard_idx, bs);

    log_("{} expends a Bardic Inspiration use to restore Beguiling Magic: now {}/{}",
         agentName(bm, bard_idx), beg->current, beg->max);
    return beg->current;
}

void CombatEngine::applySuperiorInspiration(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    for (int i = 0; i < n; ++i) {
        Agent::Stats stats = bm.getAgentStats(i);
        if (stats.character_class != CharacterClass::Bard || stats.char_level < 18) continue;

        Resource* bi = stats.getResource("Bardic Inspiration");
        if (!bi || bi->current >= 2) continue;

        bi->current = std::min(bi->max, 2);  // regain up to 2 (never above the resource max)
        bm.setAgentStats(i, stats);
        log_("{} regains Bardic Inspiration to {} (Superior Inspiration)",
             agentName(bm, i), bi->current);
    }
}

int CombatEngine::bardCuttingWords(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.character_class != CharacterClass::Bard ||
        stats.bard_subclass != BardCollege::LorePath || stats.char_level < 3) {
        log_("{} cannot use Cutting Words (not a L3+ College of Lore Bard)", agentName(bm, bard_idx));
        return 0;
    }

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) {
        log_("{} has no Bardic Inspiration use for Cutting Words", agentName(bm, bard_idx));
        return 0;
    }

    bi->current -= 1;
    int value = roll(stats.bardic_inspiration_die_size);
    pending_roll_bonus_ = -value;   // SUBTRACT from the next D20 Test (the target's roll)
    bm.setAgentStats(bard_idx, stats);

    log_("{} uses Cutting Words: -{} to the next D20 Test ({} Bardic Inspiration left)",
         agentName(bm, bard_idx), value, bi->current);
    return value;
}

void CombatEngine::regeneratePortentDice(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Check if Diviner wizard
    if (stats.character_class != Wizard || stats.wizard_subclass != DivinierPath) {
        return;
    }

    auto* portent_res = stats.getResource("Portent Dice");
    if (!portent_res) {
        return;
    }

    // Clear old dice and roll new ones
    stats.portent_dice.clear();
    int count = portent_res->current;  // Use current after long rest restoration
    for (int i = 0; i < count; ++i) {
        stats.portent_dice.push_back(roll(20));
    }

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} regenerated {} Portent Dice: [{}]",
         agentName(bm, agent_idx), count,
         [&]() {
             std::string vals;
             for (int i = 0; i < static_cast<int>(stats.portent_dice.size()); ++i) {
                 if (i > 0) vals += ", ";
                 vals += std::to_string(stats.portent_dice[static_cast<std::size_t>(i)]);
             }
             return vals;
         }());
}

// ─────────────────────────────────────────────────────────────────────────────
//  Subclass forms
// ─────────────────────────────────────────────────────────────────────────────

// ── Wild Shape Activation / Deactivation ──────────────────────────────────
bool CombatEngine::activateWildShape(BattleMap& bm, int idx, const std::string& beast_name, std::vector<Weapon> weapons, const std::string& beast_forms_path) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

  Agent::Stats stats = bm.getAgentStats(idx);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) return false;

  // Load beast form from JSON to get stats
  nlohmann::json beasts;
  std::vector<std::string> paths;
  if (!beast_forms_path.empty()) paths.push_back(beast_forms_path);
  paths.insert(paths.end(), {"beast_forms.json", "./beast_forms.json", "../gui/beast_forms.json"});

  bool loaded = false;
  for (const auto& path : paths) {
    try {
      std::ifstream f(path);
      if (f.is_open()) {
        f >> beasts;
        loaded = true;
        break;
      }
    } catch (...) {}
  }
  if (!loaded) return false;

  // Find beast
  nlohmann::json beast_data;
  for (const auto& b : beasts) {
    if (b.value("name", "") == beast_name) {
      beast_data = b;
      break;
    }
  }
  if (beast_data.empty()) return false;

  // Save original weapons, stats, and ability scores
  stats.wild_shape_saved_weapons = getAgentWeapons(bm, idx);
  stats.wild_shape_saved_ac = stats.base_ac;
  stats.wild_shape_saved_str = stats.str;
  stats.wild_shape_saved_dex = stats.dex;
  stats.wild_shape_saved_con = stats.con;

  stats.str = beast_data.value("str", 10);
  stats.dex = beast_data.value("dex", 10);
  stats.con = beast_data.value("con", 10);
  stats.base_ac = beast_data.value("ac", 10);
  if (stats.druid_circle == CircleOfMoon) {
    stats.base_ac = std::max(stats.base_ac, 13 + (stats.wis - 10) / 2);
  }

  int temp_hp = stats.char_level * (stats.druid_circle == CircleOfMoon ? 3 : 1);
  stats.temp_hp += temp_hp;
  stats.rage_thp_source_idx = -1;  // Wild Shape THP is not rage-sourced (don't let endRage wipe it)

  stats.wild_shape_active = true;
  stats.wild_shape_form_name = beast_name;
  stats.num_attacks = 2;

  bm.setAgentStats(idx, stats);

  // Set the beast form weapons on the agent
  bm.setAgentWeapons(idx, weapons);

  return true;
}

bool CombatEngine::deactivateWildShape(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WILD_SHAPE] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore saved AC and ability scores
  if (stats.base_ac > 0 && stats.wild_shape_saved_ac > 0) {
    stats.base_ac = stats.wild_shape_saved_ac;
  }
  if (stats.wild_shape_saved_str > 0) stats.str = stats.wild_shape_saved_str;
  if (stats.wild_shape_saved_dex > 0) stats.dex = stats.wild_shape_saved_dex;
  if (stats.wild_shape_saved_con > 0) stats.con = stats.wild_shape_saved_con;

  log_("[WILD_SHAPE] Restored stats: AC={}, STR={}, DEX={}, CON={}", stats.base_ac, stats.str, stats.dex, stats.con);

  // Restore original weapons
  bm.setAgentWeapons(idx, stats.wild_shape_saved_weapons);

  stats.wild_shape_active = false;
  stats.wild_shape_form_name = "";
  stats.lunar_radiance_available = false;

  bm.setAgentStats(idx, stats);
  log_("[WILD_SHAPE] Deactivated Wild Shape");
  return true;
}

// ── Starry Form Activation (Circle of the Stars) ────────────────────────────
bool CombatEngine::activateStarryForm(BattleMap& bm, int idx, int constellation) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[STARRY_FORM] Activating constellation {}", constellation);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[STARRY_FORM] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.starry_form_active = true;
  stats.starry_constellation = constellation;

  // Dragon constellation: add fly speed at L10+
  if (constellation == 3 && stats.char_level >= 10) {  // 3 = Dragon
    stats.speed_fly = stats.speed_walk;
    log_("[STARRY_FORM] Added fly speed for Dragon constellation");
  }

  // Full of Stars (L14): add resistances to B/P/S
  if (stats.char_level >= 14) {
    stats.set_physical_damage_multiplier(0, 0.5f);  // Bludgeoning
    stats.set_physical_damage_multiplier(1, 0.5f);  // Piercing
    stats.set_physical_damage_multiplier(2, 0.5f);  // Slashing
    log_("[STARRY_FORM] Added B/P/S resistances at level 14+");
  }

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] SUCCESS: Activated constellation {}", constellation);
  return true;
}

bool CombatEngine::deactivateStarryForm(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore fly speed
  stats.speed_fly = 0;

  // Clear resistances
  stats.set_physical_damage_multiplier(0, 1.0f);  // Bludgeoning
  stats.set_physical_damage_multiplier(1, 1.0f);  // Piercing
  stats.set_physical_damage_multiplier(2, 1.0f);  // Slashing

  stats.starry_form_active = false;
  stats.starry_constellation = 0;

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] Deactivated Starry Form");
  return true;
}

// ── Wrath of the Sea Activation (Circle of the Sea) ────────────────────────
bool CombatEngine::activateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[WRATH_OF_SEA] Activating Wrath of the Sea");

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[WRATH_OF_SEA] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.wrath_of_sea_active = true;

  // Stormborn (L10): add fly speed and resistances
  if (stats.char_level >= 10) {
    stats.speed_fly = stats.speed_walk;
    // Cold, Lightning, Thunder
    stats.set_magic_damage_multiplier(1, 0.5f);   // Cold
    stats.set_magic_damage_multiplier(4, 0.5f);   // Lightning
    stats.set_magic_damage_multiplier(9, 0.5f);   // Thunder
    log_("[WRATH_OF_SEA] Added fly speed and resistances at level 10+");
  }

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] SUCCESS: Activated Wrath of the Sea");
  return true;
}

bool CombatEngine::deactivateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  stats.speed_fly = 0;
  stats.set_magic_damage_multiplier(1, 1.0f);   // Cold
  stats.set_magic_damage_multiplier(4, 1.0f);   // Lightning
  stats.set_magic_damage_multiplier(9, 1.0f);   // Thunder

  stats.wrath_of_sea_active = false;

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] Deactivated Wrath of the Sea");
  return true;
}

// ── Dragon Min Roll (Starry Form, Dragon constellation) ──────────────────────
int CombatEngine::applyDragonMinRoll(BattleMap& bm, int idx, int d20_roll) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    return d20_roll;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Dragon constellation (value 3) with level 10+ gets min-roll-10
  if (stats.starry_form_active && stats.starry_constellation == 3 && stats.char_level >= 10) {
    int result = std::max(d20_roll, 10);
    if (result > d20_roll) {
      log_("[DRAGON_MIN_ROLL] Applied min-10: rolled {} -> {}", d20_roll, result);
    }
    return result;
  }

  return d20_roll;
}

} // namespace rpg
