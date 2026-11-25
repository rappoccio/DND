// ─────────────────────────────────────────────────────────────────────────────
//  combat_resources.cpp  –  CombatEngine shared resources, items and rests
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The class-independent half of the action economy (COMBAT_CLASS_SPLIT_PLAN.md D3): the
//  bonus-action budget and consumeBonusAttack, spendResource, healAgent, items and thrown
//  items, regaining a slot from an item, terrain and light ticks, long and short rests.
//  Class and feat features live in combat_<class>.cpp and combat_feats.cpp.
//
//  combat_riders.cpp and the per-class code were split out in COMBAT_REFACTOR_PLAN.md R6
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

bool CombatEngine::consumeBonusAttack(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.bonus_attacks_remaining <= 0) return false;

    stats.bonus_attacks_remaining--;
    bm.setAgentStats(agent_idx, stats);

    if (stats.bonus_attacks_remaining > 0) {
        log_("{} has {} bonus attack{} remaining",
             agentName(bm, agent_idx), stats.bonus_attacks_remaining,
             stats.bonus_attacks_remaining == 1 ? "" : "s");
        return true;
    }
    return false;
}

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
    // A creature under a prevents_healing condition (Pit Fiend poison: "can't regain hit points")
    // gains no HP from any source. The condition still ends normally via its saves; this only
    // gates the gain. Revival from 0 is likewise blocked — a downed target can't be healed up.
    if (s.cant_heal) return s.hp_cur;
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
    // A Wondrous item has no Use Item effect: it only casts its item_spells (ENSPELLED D8). Nor
    // does a scroll: its spell is cast from the spell menu.
    if (item.type == Item::Wondrous || item.type == Item::Scroll) return res;

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
        const bool heals = item.healing.num_dice > 0 || item.healing.bonus > 0;
        if (!heals)   // a potion that only buffs (Potion of Heroism): no "regains 0 HP"
            log_("{} {} {}.", agentName(bm, user_idx),
                 target_idx == user_idx ? "drinks" : "administers", item.name);
        else if (target_idx == user_idx)
            log_("{} drinks {} and regains {} HP.", agentName(bm, user_idx), item.name, res.amount_healed);
        else
            log_("{} administers {} to {}, who regains {} HP.", agentName(bm, user_idx), item.name,
                 agentName(bm, target_idx), res.amount_healed);
        // Potion of Heroism (RAVENLOFT M11): Temporary Hit Points (they don't stack: keep the
        // larger) and Bless without Concentration — a condition no spell owns (spell_idx -1),
        // so no concentration drop can end it; it runs out on its own timer.
        if (item.temp_hp > 0) {
            Agent::Stats ts = bm.getAgentStats(target_idx);
            ts.temp_hp = std::max(ts.temp_hp, item.temp_hp);
            bm.setAgentStats(target_idx, ts);
            log_("{} gains {} Temporary Hit Points ({}).", agentName(bm, target_idx), item.temp_hp,
                 item.name);
        }
        if (!item.applies_condition.empty() && item.applies_condition_turns > 0) {
            ActiveAgentCondition c{};
            c.agent_idx         = target_idx;
            c.caster_idx        = user_idx;
            c.spell_idx         = -1;
            c.condition_name    = item.applies_condition;
            c.turns_remaining   = item.applies_condition_turns;
            c.save_dc           = 0;
            c.save_repeat_turns = item.applies_condition_turns + 1;
            c.next_save_turn    = item.applies_condition_turns + 1;
            (void)addAgentCondition(bm, c);
            log_("{} is {} ({}).", agentName(bm, target_idx), item.applies_condition, item.name);
        }
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
    // rules::spellSaveDcFromAbility, which folds in caster-only buffs (Innate Sorcery) that have no
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
    else                 save_d20 = d20TestFor(bm, target_idx, adv, dis);   // Halfling Luck

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
    } else if (item.condition_applied == "Restrained" && !conditionImmune(bm, target_idx, "Restrained")) {
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

// RAVENLOFT M10: a carried, switched-on item regains one expended spell slot (the highest level
// with one missing; a Warlock's pact slot) once per long rest. The Magic action is the GUI's.
int CombatEngine::regainSlotFromItem(BattleMap& bm, int idx) noexcept
{
    if (idx < 0 || idx >= static_cast<int>(bm.placedAgents().size())) return 0;
    Agent::Stats s = bm.getAgentStats(idx);
    int level = 0;
    for (int i = static_cast<int>(s.spell_slots_max.size()) - 1; i >= 0; --i) {
        const auto k = static_cast<std::size_t>(i);
        if (s.spell_slots_remaining[k] < s.spell_slots_max[k]) { level = i + 1; break; }
    }
    if (level == 0) return 0;
    PlacedAgent& pa = bm.placedAgentMut(idx);
    ItemSpells* src = nullptr;
    std::string src_name;
    auto pick = [&](const std::string& name, ItemSpells& is) {
        if (!src && !name.empty() && is.attunedOrFree() && is.slot_regain && !is.slot_regain_used) {
            src = &is;
            src_name = name;
        }
    };
    for (auto& it : pa.items)   pick(it.name, it.item_spells);
    for (auto& w  : pa.weapons) pick(w.name, w.item_spells);
    for (auto& a  : pa.armor)   pick(a.name, a.item_spells);
    if (!src) return 0;
    src->slot_regain_used = true;
    s.spell_slots_remaining[static_cast<std::size_t>(level - 1)] += 1;
    bm.setAgentStats(idx, s);
    log_("{} regains a level {} spell slot from {}", agentName(bm, idx), level, src_name);
    return level;
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

void CombatEngine::applyLongRest(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        int agent_idx = static_cast<int>(i);
        Agent::Stats stats = bm.getAgentStats(agent_idx);

        // Restore spell slots and all resources
        stats.restore_resources_long_rest();
        // A spell's weapon damage rider (RAVENLOFT M5: the Helm's flames) is long gone by morning.
        stats.weapon_rider_dice  = 0;
        stats.weapon_rider_turns = 0;

        // Greater Divine Intervention lock (Cleric L20): a Wish use costs 2d4 Long Rests before
        // DI returns. restore_resources_long_rest() just refilled the DI resource generically, so
        // undo that refill while the lock is still counting down.
        if (stats.divine_intervention_lock > 0) {
            stats.divine_intervention_lock -= 1;
            if (stats.divine_intervention_lock > 0)
                if (Resource* di = stats.getResource("Divine Intervention")) di->current = 0;
        }

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
        if (stats.hasClass(Wizard) && stats.wizard_subclass == AbjurerPath && stats.classLevel(CharacterClass::Wizard) >= 3) {
            stats.temp_hp = stats.classLevel(CharacterClass::Wizard);
        }

        // TASK E: Celestial Resilience (Celestial L10): temp HP on long rest
        if (stats.hasClass(CharacterClass::Warlock) && stats.warlock_subclass == CelestialPath && stats.classLevel(CharacterClass::Warlock) >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.classLevel(CharacterClass::Warlock) + chaMod);
        }

        // Warrior of the Elements — Elemental Attunement ends on a long rest (clear the active flag and
        // the unarmed damage-type override it set).
        if (stats.hasClass(CharacterClass::Monk) && stats.unarmed_damage_override >= 0)
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
        if (stats.hasClass(CharacterClass::Barbarian) &&
            stats.barbarian_subclass == ZealotPath)
            stats.rage_of_gods_used = false;

        // Evoker L14 Overchannel: the next use is free again after a Long Rest.
        stats.overchannel_uses = 0;

        // Granted spells (SPECIES_PLAN.md D3): every free cast comes back on a Long Rest.
        stats.refillGrantedSpells();

        // Save stats back (includes resource restoration)
        bm.setAgentStats(agent_idx, stats);

        // Enspelled items (ENSPELLED_ITEMS_PLAN.md E2): every carried item, weapon and worn armor
        // piece refills its N/day groups and its charge pool. Attunement doesn't matter: the item
        // regains its uses whoever holds it. Items on the floor or in a chest don't (known limit).
        // A spell scroll never refills (SPELL_SCROLLS_PLAN.md S3).
        {
            PlacedAgent& rpa = bm.placedAgentMut(agent_idx);
            for (auto& it : rpa.items)
                if (it.item_spells.magical() && it.type != Item::Scroll) it.item_spells.refill();
            for (auto& w  : rpa.weapons) if (w.item_spells.magical()) w.item_spells.refill();
            for (auto& a  : rpa.armor)   if (a.item_spells.magical()) a.item_spells.refill();
        }

        // Regenerate Portent Dice for Diviners
        if (stats.hasClass(Wizard) && stats.wizard_subclass == DivinierPath) {
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
        if (stats.hasClass(CharacterClass::Warlock) && stats.warlock_subclass == CelestialPath && stats.classLevel(CharacterClass::Warlock) >= 10) {
            int chaMod = (stats.cha - 10) / 2;
            if (stats.cha < 10 && (stats.cha - 10) % 2 != 0) --chaMod;
            stats.temp_hp = std::max(stats.temp_hp, stats.classLevel(CharacterClass::Warlock) + chaMod);
        }

        // Warrior of the Elements — Elemental Attunement ends on a short rest too.
        if (stats.hasClass(CharacterClass::Monk) && stats.unarmed_damage_override >= 0)
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

} // namespace rpg
