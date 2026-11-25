// ─────────────────────────────────────────────────────────────────────────────
//  combat_ranger.cpp  –  CombatEngine Ranger features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Gloom Stalker, Fey Wanderer, Beast Master.
//  Contents: Dreadful Strike, Stalker's Flurry, Sudden Strike, Beguiling Twist and
//  charmFearSaveSucceeded, Misty Wanderer, Primal Companion commands and Beast's Strike,
//  Shadowy Dodge (moved from combat_attack.cpp in R6c).
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

// The hit only OFFERS the rider (dreadful_strike_available, set in applyAttackResult). A human takes
// it from the rider prompt; an automated Ranger through autoDreadfulStrike, from runWeaponTurn.
bool CombatEngine::applyDreadfulStrikeEffect(BattleMap& bm, int attacker_idx, AttackResult& result)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n) return false;
    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.dreadful_strike_available || atk_cond.dreadful_strike_used) return false;
    const int target_idx = atk_cond.dreadful_strike_target;
    if (target_idx < 0 || target_idx >= n) return false;
    if (!spendResource(bm, attacker_idx, "Dread Ambusher", 1)) return false;

    const Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    int raw = 0;
    for (int i = 0; i < atk_stats.dreadful_strike_dice; ++i) raw += roll(atk_stats.dreadful_strike_die_size);
    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Psychic];
    const int ds = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"dreadful strike", ds});
    result.total_damage += ds;
    result.magic_damage_types.push_back(MagicDamage_t::Psychic);
    const int overflow = std::max(0, ds - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - ds);
    tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    result.hp_after    = tgt_stats.hp_cur;
    result.target_down = (tgt_stats.hp_cur <= 0);
    bm.setAgentStats(target_idx, tgt_stats);

    atk_cond = bm.getAgentConditions(attacker_idx);   // spendResource may have written the agent
    atk_cond.dreadful_strike_used      = true;
    atk_cond.dreadful_strike_available = false;
    // Stalker's Flurry (L11): "when you use Dreadful Strike, you can cause one of the following".
    atk_cond.stalkers_flurry_pending   = atk_stats.classLevel(CharacterClass::Ranger) >= 11;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} uses Dreadful Strike: +{} Psychic ({}d{})", agentName(bm, attacker_idx), ds,
         atk_stats.dreadful_strike_dice, atk_stats.dreadful_strike_die_size);
    if (ds > 0) {
        checkConcentrationOnDamage(bm, target_idx, ds);
        processDamageTaken(bm, target_idx, ds);
    }
    return true;
}

bool CombatEngine::chooseStalkersFlurry(BattleMap& bm, int attacker_idx, int option)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n) return false;
    Agent::Conditions c = bm.getAgentConditions(attacker_idx);
    if (!c.stalkers_flurry_pending) return false;
    c.stalkers_flurry_pending = false;
    c.sudden_strike_available = (option == 1);
    bm.setAgentConditions(attacker_idx, c);
    if (option == 1)
        log_("{}: Stalker's Flurry — Sudden Strike (a free attack vs a creature within 5 ft of {})",
             agentName(bm, attacker_idx), agentName(bm, c.dreadful_strike_target));
    else if (option == 2)
        (void)applyMassFear(bm, attacker_idx, c.dreadful_strike_target);
    return true;
}

int CombatEngine::applyMassFear(BattleMap& bm, int ranger_idx, int target_idx)
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (ranger_idx < 0 || ranger_idx >= n || target_idx < 0 || target_idx >= n) return 0;
    const int dc = rules::spellSaveDc(bm.getAgentStats(ranger_idx));
    const PlacedAgent& tg = agents[static_cast<std::size_t>(target_idx)];
    log_("{}: Stalker's Flurry — Mass Fear around {} (WIS save DC {})", agentName(bm, ranger_idx),
         agentName(bm, target_idx), dc);
    int frightened = 0;
    for (int j = 0; j < n; ++j) {
        if (j == ranger_idx) continue;
        const PlacedAgent& pt = agents[static_cast<std::size_t>(j)];
        if (pt.removed_from_play || bm.isAgentOnDeck(j)) continue;
        if (pt.agent->getConditions().dead || pt.agent->getStats().hp_cur <= 0) continue;
        if (j != target_idx &&
            footprintDistance(tg.origin, tg.agent->getSize(), pt.origin, pt.agent->getSize()) > 2) continue;
        const int save = (conditionSaveAdvantage(bm, j, "Frightened") ? rollAdvantage(20) : roll(20)) +
                         saveModFor(bm, j, SaveWis);
        if (save >= dc) {
            log_("{} resists Mass Fear (WIS save {} vs DC {})", agentName(bm, j), save, dc);
            charmFearSaveSucceeded(bm, j);   // Beguiling Twist's trigger
            continue;
        }
        if (hasAuraOfCourage(bm, j)) {
            log_("{} can't be Frightened (Aura of Courage) — Mass Fear has no effect", agentName(bm, j));
            continue;
        }
        ActiveAgentCondition cond;
        cond.agent_idx       = j;
        cond.caster_idx      = ranger_idx;   // the fear source; ticked off as the Ranger's next turn begins
        cond.condition_name  = "Frightened";
        cond.turns_remaining = 1;
        (void)addAgentCondition(bm, cond);
        ++frightened;
        log_("{} is Frightened (Mass Fear — WIS save {} vs DC {})", agentName(bm, j), save, dc);
    }
    return frightened;
}

bool CombatEngine::beguilingTwistAdvantage(const BattleMap& bm, int saver,
                                           std::string_view condition_name) const
{
    if (condition_name != "Charmed" && condition_name != "Frightened") return false;
    if (saver < 0 || saver >= static_cast<int>(bm.placedAgents().size())) return false;
    const Agent::Stats s = bm.getAgentStats(saver);
    return s.hasClass(CharacterClass::Ranger) && s.ranger_subclass == FeyWandererPath &&
           s.classLevel(CharacterClass::Ranger) >= 7;
}

std::vector<int> CombatEngine::beguilingTwistTargets(const BattleMap& bm, int reactor, int saver) const
{
    std::vector<int> out;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n) return out;
    const PlacedAgent& me = agents[static_cast<std::size_t>(reactor)];
    for (int i = 0; i < n; ++i) {
        if (i == reactor || i == saver) continue;
        const PlacedAgent& o = agents[static_cast<std::size_t>(i)];
        if (o.removed_from_play || o.on_deck) continue;
        if (rules::untouchableApart(bm, reactor, i)) continue;   // Untouchable: out of reach
        if (o.agent->getConditions().dead || o.agent->getStats().hp_cur <= 0) continue;
        if (footprintDistance(me.origin, me.agent->getSize(), o.origin, o.agent->getSize()) > 24) continue;
        if (!bm.hasLineOfSight(me.origin, me.agent->getSize(), o.origin, o.agent->getSize())) continue;
        if (!canPerceiveTarget(bm, reactor, i)) continue;
        out.push_back(i);
    }
    return out;
}

bool CombatEngine::canBeguilingTwist(const BattleMap& bm, int reactor, int saver) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n || saver < 0 || saver >= n) return false;
    const PlacedAgent& rp = agents[static_cast<std::size_t>(reactor)];
    if (rp.removed_from_play || rp.on_deck) return false;
    if (rules::untouchableApart(bm, reactor, saver)) return false;   // Untouchable: out of reach
    const Agent::Stats s = rp.agent->getStats();
    if (s.hp_cur <= 0 || !s.hasClass(CharacterClass::Ranger) || s.ranger_subclass != FeyWandererPath ||
        s.classLevel(CharacterClass::Ranger) < 7) return false;
    if (!canTakeReaction(rp.agent->getConditions())) return false;
    if (saver != reactor) {   // "you or a creature you can see within 120 feet of you"
        const PlacedAgent& sp = agents[static_cast<std::size_t>(saver)];
        if (footprintDistance(rp.origin, rp.agent->getSize(), sp.origin, sp.agent->getSize()) > 24) return false;
        if (!bm.hasLineOfSight(rp.origin, rp.agent->getSize(), sp.origin, sp.agent->getSize())) return false;
        if (!canPerceiveTarget(bm, reactor, saver)) return false;
    }
    return !beguilingTwistTargets(bm, reactor, saver).empty();
}

bool CombatEngine::applyBeguilingTwist(BattleMap& bm, int reactor, int saver, int target, bool frightened)
{
    if (!canBeguilingTwist(bm, reactor, saver)) return false;
    const std::vector<int> legal = beguilingTwistTargets(bm, reactor, saver);
    if (std::find(legal.begin(), legal.end(), target) == legal.end()) return false;
    Agent::Conditions rc = bm.getAgentConditions(reactor);
    rc.reaction_used = true;
    bm.setAgentConditions(reactor, rc);

    const char* cond_name = frightened ? "Frightened" : "Charmed";
    const int dc = rules::spellSaveDc(bm.getAgentStats(reactor));
    log_("{}: Beguiling Twist — {} must make a WIS save (DC {}) or be {}", agentName(bm, reactor),
         agentName(bm, target), dc, cond_name);
    recordNpcAnnounce(reactor, target, std::format("{} uses Beguiling Twist!", agentName(bm, reactor)));
    const bool adv = conditionSaveAdvantage(bm, target, cond_name);
    const int  d20 = adv ? rollAdvantage(20) : roll(20);
    const int  save = d20 + saveModFor(bm, target, SaveWis);
    if (save >= dc) {
        log_("{} resists Beguiling Twist (WIS save {} vs DC {})", agentName(bm, target), save, dc);
        charmFearSaveSucceeded(bm, target);   // that success is itself a trigger (another Ranger's Reaction)
        return true;
    }
    if (frightened && hasAuraOfCourage(bm, target)) {
        log_("{} can't be Frightened (Aura of Courage) — Beguiling Twist has no effect", agentName(bm, target));
        return true;
    }
    ActiveAgentCondition cond;
    cond.agent_idx           = target;
    cond.caster_idx          = reactor;
    cond.condition_name      = cond_name;
    cond.turns_remaining     = 10;        // 1 minute (ticked on the Ranger's turns)
    cond.save_ability        = SaveWis;
    cond.save_dc             = dc;
    cond.save_repeat_turns   = 1;
    cond.save_at_end_of_turn = true;      // "repeats the save at the end of each of its turns"
    cond.next_save_turn      = 0;
    (void)addAgentCondition(bm, cond);
    log_("{} is {} by Beguiling Twist for 1 minute (WIS save {} vs DC {})", agentName(bm, target),
         cond_name, save, dc);
    return true;
}

void CombatEngine::charmFearSaveSucceeded(BattleMap& bm, int saver)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (saver < 0 || saver >= n) return;
    for (int r = 0; r < n; ++r) {
        if (!canBeguilingTwist(bm, r, saver)) continue;
        if (!bm.placedAgents()[static_cast<std::size_t>(r)].is_npc_automated) {
            // The GUI asks the Ranger's player. Bounded: a headless caller that never drains it
            // (non-automated agents outside the GUI) keeps only the latest few.
            if (beguiling_twist_offers_.size() >= 16)
                beguiling_twist_offers_.erase(beguiling_twist_offers_.begin());
            beguiling_twist_offers_.emplace_back(r, saver);
            continue;
        }
        // D7 auto: Frightened, on the enemy the auto-target heuristic ranks first, else the nearest.
        const std::vector<int> legal = beguilingTwistTargets(bm, r, saver);
        int tgt = npcSelectTarget(bm, r);
        if (std::find(legal.begin(), legal.end(), tgt) == legal.end()) {
            tgt = -1;
            const PlacedAgent& me = bm.placedAgents()[static_cast<std::size_t>(r)];
            int best = 1 << 30;
            for (int t : legal) {
                if (rules::alliedFactions(bm, r, t)) continue;
                const PlacedAgent& o = bm.placedAgents()[static_cast<std::size_t>(t)];
                const int d = footprintDistance(me.origin, me.agent->getSize(), o.origin, o.agent->getSize());
                if (d < best) { best = d; tgt = t; }
            }
        }
        if (tgt >= 0) (void)applyBeguilingTwist(bm, r, saver, tgt, /*frightened=*/true);
    }
}

std::vector<std::pair<int,int>> CombatEngine::takeBeguilingTwistOffers()
{
    std::vector<std::pair<int,int>> out;
    out.swap(beguiling_twist_offers_);
    return out;
}

std::vector<int> CombatEngine::suddenStrikeTargets(const BattleMap& bm, int attacker_idx) const
{
    std::vector<int> out;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (attacker_idx < 0 || attacker_idx >= n) return out;
    const Agent::Conditions c = bm.getAgentConditions(attacker_idx);
    if (!c.sudden_strike_available) return out;
    const int origin = c.dreadful_strike_target;
    const auto weapons = bm.getAgentWeapons(attacker_idx);
    if (origin < 0 || origin >= n || c.dreadful_strike_weapon < 0 ||
        c.dreadful_strike_weapon >= static_cast<int>(weapons.size())) return out;
    const Weapon& w = weapons[static_cast<std::size_t>(c.dreadful_strike_weapon)];
    if (w.name.empty()) return out;
    const PlacedAgent& me = agents[static_cast<std::size_t>(attacker_idx)];
    const PlacedAgent& og = agents[static_cast<std::size_t>(origin)];
    for (int j = 0; j < n; ++j) {
        if (j == attacker_idx || j == origin) continue;
        const PlacedAgent& pt = agents[static_cast<std::size_t>(j)];
        if (pt.removed_from_play || bm.isAgentOnDeck(j)) continue;
        if (pt.agent->getConditions().dead || pt.agent->getStats().hp_cur <= 0) continue;
        if (rules::alliedFactions(bm, attacker_idx, j)) continue;
        if (footprintDistance(og.origin, og.agent->getSize(), pt.origin, pt.agent->getSize()) > 1) continue;
        if (!canAttack(w, bm, me.origin, me.agent->getSize(), pt.origin, pt.agent->getSize(), false)) continue;
        out.push_back(j);
    }
    return out;
}

void CombatEngine::autoDreadfulStrike(BattleMap& bm, int attacker_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n) return;
    const Agent::Conditions c = bm.getAgentConditions(attacker_idx);
    if (!c.dreadful_strike_available) return;
    const int t = c.dreadful_strike_target;
    if (t < 0 || t >= n || bm.getAgentStats(t).hp_cur <= 0) {
        // The hit already dropped it: keep the use for a later hit this turn.
        Agent::Conditions keep = c;
        keep.dreadful_strike_available = false;
        bm.setAgentConditions(attacker_idx, keep);
        return;
    }
    AttackResult scratch;
    if (!applyDreadfulStrikeEffect(bm, attacker_idx, scratch)) return;
    if (!bm.getAgentConditions(attacker_idx).stalkers_flurry_pending) return;
    // D4: Sudden Strike if a valid second target stands within 5 ft of the first, otherwise Mass Fear.
    Agent::Conditions probe = bm.getAgentConditions(attacker_idx);
    probe.sudden_strike_available = true;
    bm.setAgentConditions(attacker_idx, probe);
    const bool has_second = !suddenStrikeTargets(bm, attacker_idx).empty();
    probe.sudden_strike_available = false;
    bm.setAgentConditions(attacker_idx, probe);
    (void)chooseStalkersFlurry(bm, attacker_idx, has_second ? 1 : 2);
}

int CombatEngine::companionRanger(const BattleMap& bm, int comp_idx) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (comp_idx < 0 || comp_idx >= n) return -1;
    if (bm.getAgentSummonSpell(comp_idx) != "Primal Companion") return -1;
    const int owner = bm.getAgentSummonerIdx(comp_idx);
    if (owner < 0 || owner >= n) return -1;
    const Agent::Stats os = bm.getAgentStats(owner);
    if (!os.hasClass(CharacterClass::Ranger) || os.ranger_subclass != BeastMasterPath ||
        os.classLevel(CharacterClass::Ranger) < 3) return -1;
    return owner;
}

int CombatEngine::primalCompanionOf(const BattleMap& bm, int ranger_idx) const
{
    const auto& agents = bm.placedAgents();
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        const PlacedAgent& pt = agents[static_cast<std::size_t>(i)];
        if (pt.removed_from_play || pt.summoner_idx != ranger_idx) continue;
        if (pt.summon_spell != "Primal Companion") continue;
        if (pt.agent->getConditions().dead) continue;
        if (companionRanger(bm, i) == ranger_idx) return i;
    }
    return -1;
}

bool CombatEngine::companionRestricted(const BattleMap& bm, int comp_idx) const
{
    const int owner = companionRanger(bm, comp_idx);
    if (owner < 0) return false;
    const Agent::Conditions oc = bm.getAgentConditions(owner);
    // "If you are Incapacitated, the beast can take any action of its choice."
    if (oc.dead || oc.incapacitated || oc.unconscious) return false;
    return !oc.companion_commanded;
}

bool CombatEngine::canCommandCompanion(const BattleMap& bm, int ranger_idx) const
{
    if (primalCompanionOf(bm, ranger_idx) < 0) return false;
    const Agent::Conditions c = bm.getAgentConditions(ranger_idx);
    if (c.companion_commanded || c.incapacitated || c.unconscious || c.dead) return false;
    return hasBonusAction(bm, ranger_idx);
}

bool CombatEngine::commandCompanion(BattleMap& bm, int ranger_idx)
{
    if (!canCommandCompanion(bm, ranger_idx)) return false;
    if (!spendBonusAction(bm, ranger_idx)) return false;
    Agent::Conditions c = bm.getAgentConditions(ranger_idx);
    c.companion_commanded = true;
    bm.setAgentConditions(ranger_idx, c);
    log_("{} commands {} (Bonus Action) — it may take any action on its turn",
         agentName(bm, ranger_idx), agentName(bm, primalCompanionOf(bm, ranger_idx)));
    return true;
}

bool CombatEngine::armBeastsStrike(BattleMap& bm, int ranger_idx)
{
    const int comp = primalCompanionOf(bm, ranger_idx);
    if (comp < 0) return false;
    const Agent::Conditions cc = bm.getAgentConditions(comp);
    if (cc.incapacitated || cc.unconscious) return false;
    Agent::Conditions c = bm.getAgentConditions(ranger_idx);
    // Bestial Fury (L11): "When you command your beast to take the Beast's Strike action, the beast
    // can use it twice."
    c.beast_strikes_left = bm.getAgentStats(ranger_idx).classLevel(CharacterClass::Ranger) >= 11 ? 2 : 1;
    bm.setAgentConditions(ranger_idx, c);
    log_("{} gives up an attack: {} takes the Beast's Strike action{}", agentName(bm, ranger_idx),
         agentName(bm, comp), c.beast_strikes_left > 1 ? " (twice — Bestial Fury)" : "");
    return true;
}

std::vector<int> CombatEngine::beastsStrikeTargets(const BattleMap& bm, int ranger_idx) const
{
    std::vector<int> out;
    const int comp = primalCompanionOf(bm, ranger_idx);
    if (comp < 0) return out;
    const auto& agents = bm.placedAgents();
    const PlacedAgent& me = agents[static_cast<std::size_t>(comp)];
    const Agent::Conditions mc = me.agent->getConditions();
    if (mc.incapacitated || mc.unconscious) return out;
    const auto weapons = bm.getAgentWeapons(comp);
    if (weapons.empty() || weapons.front().name.empty()) return out;
    const Weapon& w = weapons.front();
    for (int j = 0; j < static_cast<int>(agents.size()); ++j) {
        if (j == comp || j == ranger_idx) continue;
        const PlacedAgent& pt = agents[static_cast<std::size_t>(j)];
        if (pt.removed_from_play || bm.isAgentOnDeck(j)) continue;
        if (pt.agent->getConditions().dead || pt.agent->getStats().hp_cur <= 0) continue;
        if (rules::alliedFactions(bm, comp, j)) continue;
        if (!canAttack(w, bm, me.origin, me.agent->getSize(), pt.origin, pt.agent->getSize(), false)) continue;
        out.push_back(j);
    }
    return out;
}

FlowStatus CombatEngine::beastsStrike(BattleMap& bm, int ranger_idx, int target_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (ranger_idx < 0 || ranger_idx >= n) return FlowStatus::Completed;
    Agent::Conditions c = bm.getAgentConditions(ranger_idx);
    if (c.beast_strikes_left <= 0) return FlowStatus::Completed;
    const std::vector<int> legal = beastsStrikeTargets(bm, ranger_idx);
    if (std::find(legal.begin(), legal.end(), target_idx) == legal.end()) return FlowStatus::Completed;
    const int comp = primalCompanionOf(bm, ranger_idx);
    --c.beast_strikes_left;   // BEFORE the swing: a parked attack must not repeat it
    bm.setAgentConditions(ranger_idx, c);
    Attack a;
    a.attacker_idx = comp;
    a.target_idx   = target_idx;
    a.weapon_idx   = 0;
    a.attack_slot  = "action";
    log_("{}: Beast's Strike against {}", agentName(bm, comp), agentName(bm, target_idx));
    renderAttack(comp, target_idx);
    recordNpcAnnounce(comp, target_idx,
        std::format("{} attacks {} with {} (Beast's Strike)!", agentName(bm, comp),
                    agentName(bm, target_idx), bm.getAgentWeapons(comp).front().name));
    return beginAttack(bm, a);
}

void CombatEngine::vanishOrphanedCompanions(BattleMap& bm)
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    for (int i = 0; i < n; ++i) {
        const PlacedAgent& pt = agents[static_cast<std::size_t>(i)];
        if (pt.removed_from_play || pt.summon_spell != "Primal Companion") continue;
        const int owner = pt.summoner_idx;
        const bool gone = owner < 0 || owner >= n ||
                          agents[static_cast<std::size_t>(owner)].removed_from_play ||
                          agents[static_cast<std::size_t>(owner)].agent->getConditions().dead;
        if (!gone) continue;
        bm.setAgentRemovedFromPlay(i, true);
        log_("{} vanishes — its Ranger has died", agentName(bm, i));
    }
}

void CombatEngine::endBeguilingCharm(BattleMap& bm, int source_idx, int target_idx) noexcept
{
    std::vector<int> ids;
    for (const auto& c : conditions_.all())
        if (c.arcane_shot == ArcaneShotBeguiling && c.caster_idx == source_idx &&
            c.agent_idx == target_idx && c.condition_name == "Charmed")
            ids.push_back(c.condition_id);
    for (int id : ids) {
        removeAgentCondition(bm, id);
        log_("Beguiling Shot: {}'s charm on {} breaks", agentName(bm, source_idx), agentName(bm, target_idx));
    }
}

// Misty Wanderer (Fey Wanderer Ranger L15): cast Misty Step without a slot, spending one "Misty
// Wanderer" use (max(1, WIS mod) per Long Rest). It is still a Bonus Action spell. The Ranger may bring
// one willing creature it can see within 5 ft: that creature teleports to an unoccupied space within
// 5 ft of the Ranger's destination.
std::vector<int> CombatEngine::mistyWandererAllies(const BattleMap& bm, int idx) const
{
    std::vector<int> out;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (idx < 0 || idx >= n) return out;
    const PlacedAgent& me = agents[static_cast<std::size_t>(idx)];
    const int ms = me.agent->getSize();
    for (int i = 0; i < n; ++i) {
        if (i == idx || !rules::alliedFactions(bm, idx, i)) continue;   // "willing" = on the Ranger's side
        const PlacedAgent& o = agents[static_cast<std::size_t>(i)];
        if (o.removed_from_play || o.on_deck) continue;
        if (o.agent->getConditions().dead || o.agent->getStats().hp_cur <= 0) continue;
        if (footprintDistance(me.origin, ms, o.origin, o.agent->getSize()) != 1) continue;   // within 5 ft
        if (!bm.hasLineOfSight(me.origin, ms, o.origin, o.agent->getSize())) continue;       // you can see
        out.push_back(i);
    }
    return out;
}

bool CombatEngine::isMistyWandererAllyCell(const BattleMap& bm, int ally_idx, Cell dest,
                                           int ranger_idx, Cell ranger_dest) const
{
    const auto& agents = bm.placedAgents();
    if (ally_idx < 0 || ally_idx >= static_cast<int>(agents.size())) return false;
    if (ranger_idx < 0 || ranger_idx >= static_cast<int>(agents.size())) return false;
    const int as = agents[static_cast<std::size_t>(ally_idx)].agent->getSize();
    const int rs = agents[static_cast<std::size_t>(ranger_idx)].agent->getSize();
    if (footprintDistance(dest, as, ranger_dest, rs) != 1) return false;   // within 5 ft, not overlapping
    for (int r = 0; r < as; ++r)
        for (int c = 0; c < as; ++c)
            if (!isValidTeleportDestination(bm, dest.col + c, dest.row + r)) return false;
    // Unoccupied by anyone but the two travellers (the Ranger has already left its square).
    const auto& pa = bm.placedAgents();
    for (int j = 0; j < static_cast<int>(pa.size()); ++j) {
        if (j == ally_idx || j == ranger_idx) continue;
        const PlacedAgent& o = pa[static_cast<std::size_t>(j)];
        if (o.removed_from_play || o.on_deck || o.agent->getConditions().dead) continue;
        if (footprintDistance(dest, as, o.origin, o.agent->getSize()) == 0) return false;
    }
    return true;
}

Cell CombatEngine::mistyWandererAllyCell(const BattleMap& bm, int ally_idx, int ranger_idx,
                                         Cell ranger_dest) const
{
    const Cell none{-1, -1};
    const auto& agents = bm.placedAgents();
    if (ally_idx < 0 || ally_idx >= static_cast<int>(agents.size())) return none;
    const int as = agents[static_cast<std::size_t>(ally_idx)].agent->getSize();
    const int rs = ranger_idx >= 0 && ranger_idx < static_cast<int>(agents.size())
                 ? agents[static_cast<std::size_t>(ranger_idx)].agent->getSize() : 1;
    for (int dr = -as; dr <= rs; ++dr)
        for (int dc = -as; dc <= rs; ++dc) {
            const Cell at{ranger_dest.col + dc, ranger_dest.row + dr};
            if (isMistyWandererAllyCell(bm, ally_idx, at, ranger_idx, ranger_dest)) return at;
        }
    return none;
}

bool CombatEngine::mistyWanderer(BattleMap& bm, int idx, int target_col, int target_row,
                                 int ally_idx, int ally_col, int ally_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Ranger) || s.ranger_subclass != FeyWandererPath ||
        s.classLevel(CharacterClass::Ranger) < 15) return false;
    const Resource* mw = s.getResource("Misty Wanderer");
    if (!mw || mw->current <= 0) {
        log_("{} has no Misty Wanderer uses left", agentName(bm, idx));
        return false;
    }
    if (!hasBonusAction(bm, idx)) return false;
    const Cell from = agents[static_cast<std::size_t>(idx)].origin;
    const Cell dest{target_col, target_row};
    if (!isShadowyDodgeDestination(bm, idx, dest)) {   // ≤30 ft, unoccupied, a space you can see
        log_("{}: Misty Wanderer — can't teleport there", agentName(bm, idx));
        return false;
    }
    // The passenger: one willing creature within 5 ft, to a free space within 5 ft of the destination.
    Cell ally_dest{-1, -1};
    if (ally_idx >= 0) {
        const std::vector<int> allies = mistyWandererAllies(bm, idx);
        if (std::find(allies.begin(), allies.end(), ally_idx) == allies.end()) {
            log_("{}: Misty Wanderer — {} isn't a willing creature within 5 ft", agentName(bm, idx),
                 agentName(bm, ally_idx));
            return false;
        }
        ally_dest = (ally_col >= 0 && ally_row >= 0) ? Cell{ally_col, ally_row}
                                                     : mistyWandererAllyCell(bm, ally_idx, idx, dest);
        if (ally_dest.col < 0 || !isMistyWandererAllyCell(bm, ally_idx, ally_dest, idx, dest)) {
            log_("{}: Misty Wanderer — no room for {} beside the destination", agentName(bm, idx),
                 agentName(bm, ally_idx));
            return false;
        }
    }

    if (!teleportAgent(bm, idx, dest.col, dest.row)) return false;
    s = bm.getAgentStats(idx);   // teleportAgent may re-persist the stats
    if (Resource* r = s.getResource("Misty Wanderer")) r->spend(1);
    s.markLeveledSpellCast(2);   // it is still a Misty Step: the one-leveled-spell rule sees it
    bm.setAgentStats(idx, s);
    spendBonusAction(bm, idx);
    log_("{}: Misty Wanderer — casts Misty Step ({} ft)", agentName(bm, idx),
         5 * std::max(std::abs(dest.col - from.col), std::abs(dest.row - from.row)));
    recordNpcAnnounce(idx, -1, std::format("{} casts Misty Step!", agentName(bm, idx)));
    if (ally_idx >= 0 && teleportAgent(bm, ally_idx, ally_dest.col, ally_dest.row))
        log_("Misty Wanderer: {} is carried along", agentName(bm, ally_idx));
    return true;
}

bool CombatEngine::autoMistyWanderer(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.lacksClass(CharacterClass::Ranger) || s.ranger_subclass != FeyWandererPath ||
        s.classLevel(CharacterClass::Ranger) < 15) return false;
    const Resource* mw = s.getResource("Misty Wanderer");
    if (!mw || mw->current <= 0 || !hasBonusAction(bm, idx)) return false;
    // Only to get a ranged Ranger out of melee: an enemy must have it in reach.
    if (!isThreatened(bm, idx)) return false;
    const Cell dest = shadowyDodgeDestination(bm, idx);
    if (dest.col < 0) return false;
    // D8: bring an adjacent ally who is in melee with an enemy, if there is one with room.
    int ally = -1;
    for (int a : mistyWandererAllies(bm, idx))
        if (isThreatened(bm, a) && mistyWandererAllyCell(bm, a, idx, dest).col >= 0) { ally = a; break; }
    return mistyWanderer(bm, idx, dest.col, dest.row, ally, -1, -1);
}

// ── Shadowy Dodge (Gloom Stalker L15) ─────────────────────────────────────────────────────────
bool CombatEngine::canShadowyDodge(const BattleMap& bm, int defender_idx, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (defender_idx < 0 || defender_idx >= n || attacker_idx < 0 || attacker_idx >= n) return false;
    if (defender_idx == attacker_idx || bm.isAgentOnDeck(defender_idx)) return false;
    const Agent::Conditions cond = bm.getAgentConditions(defender_idx);
    if (!canTakeReaction(cond) || cond.dead) return false;
    const Agent::Stats s = bm.getAgentStats(defender_idx);
    if (s.hp_cur <= 0) return false;
    return s.hasClass(CharacterClass::Ranger) && s.ranger_subclass == GloomStalkerPath &&
           s.classLevel(CharacterClass::Ranger) >= 15;
}

bool CombatEngine::applyShadowyDodge(BattleMap& bm, int defender_idx)
{
    if (defender_idx < 0 || defender_idx >= static_cast<int>(bm.placedAgents().size())) return false;
    Agent::Conditions c = bm.getAgentConditions(defender_idx);
    if (!canTakeReaction(c)) return false;
    c.reaction_used = true;
    bm.setAgentConditions(defender_idx, c);
    log_("{} uses Shadowy Dodge — the attack roll has Disadvantage", agentName(bm, defender_idx));
    return true;
}

bool CombatEngine::isShadowyDodgeDestination(const BattleMap& bm, int idx, Cell dest) const
{
    return isSeenTeleportSpace(bm, idx, dest, 6);   // 30 ft
}

Cell CombatEngine::shadowyDodgeDestination(const BattleMap& bm, int idx) const
{
    const Cell none{-1, -1};
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (idx < 0 || idx >= n) return none;
    const PlacedAgent& me = agents[static_cast<std::size_t>(idx)];
    const int sz = me.agent->getSize();
    // D6: a cell is safe when, for every enemy, it is out of that enemy's melee reach OR out of its
    // line of sight. Reach is the enemy's longest melee weapon (5 ft at least), as isThreatened has it.
    struct Foe { Cell origin; int size; int reach_cells; };
    std::vector<Foe> foes;
    for (int i = 0; i < n; ++i) {
        if (i == idx || rules::alliedFactions(bm, idx, i)) continue;
        const PlacedAgent& o = agents[static_cast<std::size_t>(i)];
        if (o.removed_from_play || o.on_deck) continue;
        if (rules::untouchableApart(bm, idx, i)) continue;   // Untouchable: out of reach
        if (o.agent->getConditions().dead || o.agent->getStats().hp_cur <= 0) continue;
        int reach_ft = 5;
        for (const Weapon& w : bm.getAgentWeapons(i))
            if (!w.name.empty() && w.type == WeaponType::Melee) reach_ft = std::max(reach_ft, w.reach_ft);
        foes.push_back({o.origin, o.agent->getSize(), reach_ft / 5});
    }
    const auto safe = [&](Cell at) {
        for (const Foe& f : foes)
            if (footprintDistance(at, sz, f.origin, f.size) <= f.reach_cells &&
                bm.hasLineOfSight(f.origin, f.size, at, sz)) return false;
        return true;
    };
    if (safe(me.origin)) return none;   // already out of every enemy's reach (or sight): stay put
    Cell best = none;
    int best_d = 1 << 30;
    for (int dr = -6 - (sz - 1); dr <= 6 + (sz - 1); ++dr)
        for (int dc = -6 - (sz - 1); dc <= 6 + (sz - 1); ++dc) {
            const Cell at{me.origin.col + dc, me.origin.row + dr};
            if (!isShadowyDodgeDestination(bm, idx, at) || !safe(at)) continue;
            const int d = footprintDistance(me.origin, sz, at, sz);
            if (d < best_d) { best = at; best_d = d; }   // nearest first; ties keep row-major order
        }
    return best;
}

bool CombatEngine::shadowyDodgeTeleport(BattleMap& bm, int idx, Cell dest)
{
    if (!isShadowyDodgeDestination(bm, idx, dest)) return false;
    const Cell from = bm.placedAgents()[static_cast<std::size_t>(idx)].origin;
    if (!teleportAgent(bm, idx, dest.col, dest.row)) return false;
    log_("{} teleports {} ft (Shadowy Dodge)", agentName(bm, idx),
         5 * std::max(std::abs(dest.col - from.col), std::abs(dest.row - from.row)));
    return true;
}

// Shadowy Dodge accepted: the reaction is spent and the roll (not yet made) takes Disadvantage.
void CombatEngine::takeShadowyDodge(BattleMap& bm, InFlightAttack& s)
{
    if (!applyShadowyDodge(bm, s.action.target_idx)) return;
    s.dis = true;
    s.shadowy_dodge = true;
}

// Shadowy Dodge's teleport, after the attack: a decided cell, else the engine's own pick (D6).
void CombatEngine::shadowyDodgeFollowUp(BattleMap& bm, int idx, int col, int row)
{
    const Cell dest = (col >= 0 && row >= 0) ? Cell{col, row} : shadowyDodgeDestination(bm, idx);
    if (dest.col < 0 || !shadowyDodgeTeleport(bm, idx, dest))
        log_("{} stays put (Shadowy Dodge)", agentName(bm, idx));
}

std::vector<ReactionOption> CombatEngine::shadowyDodgeTeleportOptions() const
{
    std::vector<ReactionOption> opts;
    opts.push_back(ReactionOption{ReactionOption::Feature, -1, "Shadowy Dodge: teleport (safest cell)",
                                  "ShadowyDodgeTeleport"});
    opts.push_back(ReactionOption{ReactionOption::Feature, -1, "Shadowy Dodge: teleport (pick a cell)",
                                  "ShadowyDodgeTeleportPick"});
    opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Stay put", ""});
    return opts;
}

} // namespace rpg
