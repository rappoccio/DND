// ─────────────────────────────────────────────────────────────────────────────
//  combat_cleric.cpp  –  CombatEngine Cleric features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Life, Light, Trickery, War, Grave.
//  Contents: Divine Strike, Divine Intervention, Guided Strike, Turn Undead, Preserve Life,
//  Supreme Healing, Corona of Light, Trickery's duplicate, Grave's Circle of Mortality,
//  Path to the Grave, Keeper of Souls and the onCreatureDied hook.
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

void CombatEngine::applyDivineStrikeEffect(BattleMap& bm, int attacker_idx, int target_idx,
                                           bool radiant, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size())) return;
    if (target_idx  < 0 || target_idx  >= static_cast<int>(agents.size())) return;

    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (atk_cond.divine_strike_used) return;  // once per turn

    Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);

    // L7: 1d8; L14 (Improved Blessed Strikes): 2d8.
    const int dice = (atk_stats.classLevel(CharacterClass::Cleric) >= 14) ? 2 : 1;
    const MagicDamage_t dtype = radiant ? MagicDamage_t::Radiant : MagicDamage_t::Necrotic;
    int raw = 0;
    for (int i = 0; i < dice; ++i) raw += roll(8);

    const float mult = tgt_stats.magic_damage_multipliers[dtype];
    const int ds_damage = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"divine strike", ds_damage});
    result.total_damage += ds_damage;
    result.magic_damage_types.push_back(dtype);

    int overflow = std::max(0, ds_damage - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - ds_damage);
    tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);

    atk_cond.divine_strike_used = true;
    atk_cond.divine_strike_available = false;

    bm.setAgentConditions(attacker_idx, atk_cond);
    bm.setAgentStats(target_idx, tgt_stats);

    log_("{} adds Divine Strike: +{} {} damage", agentName(bm, attacker_idx), ds_damage,
         radiant ? "Radiant" : "Necrotic");

    // The extra damage can break concentration and trigger on-damage conditions.
    if (ds_damage > 0) {
        checkConcentrationOnDamage(bm, target_idx, ds_damage);
        processDamageTaken(bm, target_idx, ds_damage);
    }
}

bool CombatEngine::canUseDivineIntervention(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;
    const Agent::Stats& st = agents[static_cast<std::size_t>(agent_idx)].agent->getStats();
    if (st.classLevel(CharacterClass::Cleric) < 10) return false;          // unlocks at Cleric L10
    // Availability is the resource's current (0/1). The Greater-DI (L20) recharge lock keeps that
    // at 0 across the locked rests, so the resource check alone is sufficient here.
    const Resource* di = st.getResource("Divine Intervention");
    return di != nullptr && di->current > 0;
}

bool CombatEngine::useDivineIntervention(BattleMap& bm, int agent_idx, bool chose_wish) noexcept
{
    if (!canUseDivineIntervention(bm, agent_idx)) return false;
    Agent::Stats st = bm.getAgentStats(agent_idx);
    Resource* di = st.getResource("Divine Intervention");
    if (di == nullptr || !di->spend(1)) return false;
    if (chose_wish) {
        // Greater Divine Intervention (L20): Wish locks DI for 2d4 Long Rests. applyLongRest
        // decrements the lock instead of refilling the resource while it is > 0.
        st.divine_intervention_lock = static_cast<uint8_t>(roll(4) + roll(4));
    }
    bm.setAgentStats(agent_idx, st);
    log_("{} invokes Divine Intervention{}", agentName(bm, agent_idx),
         chose_wish ? " (Greater — Wish)" : "");
    return true;
}

void CombatEngine::applyGuidedStrike(BattleMap& bm, const Attack& action, int cleric_idx, AttackResult& result) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx, tgt = action.target_idx;
    if (atk < 0 || atk >= n || tgt < 0 || tgt >= n || cleric_idx < 0 || cleric_idx >= n) return;

    Agent::Stats cleric = bm.getAgentStats(cleric_idx);
    if (cleric.lacksClass(CharacterClass::Cleric) ||
        cleric.cleric_subclass != WarDomain || cleric.classLevel(CharacterClass::Cleric) < 3) return;
    Resource* cd = cleric.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return;

    // An ally cleric (not the attacker) also spends a Reaction and must be within 30 ft.
    if (cleric_idx != atk) {
        Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
        if (!canTakeReaction(cc)) return;
        const Cell co = agents[static_cast<std::size_t>(cleric_idx)].origin;
        const Cell ao = agents[static_cast<std::size_t>(atk)].origin;
        const double dx = co.col - ao.col, dy = co.row - ao.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) return;
        cc.reaction_used = true;
        bm.setAgentConditions(cleric_idx, cc);
    }

    cd->spend(1);
    bm.setAgentStats(cleric_idx, cleric);

    result.total_roll += 10;
    log_("{}: Guided Strike +10 -> {} vs AC {}", agentName(bm, cleric_idx), result.total_roll, result.target_ac);

    Agent::Conditions atk_cond_g = bm.getAgentConditions(atk);
    atk_cond_g.guided_strike_available = false;
    bm.setAgentConditions(atk, atk_cond_g);

    // Still a miss (or already a hit) — only the +10 is recorded.
    if (result.hit || result.fumble || result.total_roll < result.target_ac) return;

    // Now meets AC — turn it into a hit and roll/apply weapon damage.
    result.hit = true;
    Agent::Stats atk_stats_g = bm.getAgentStats(atk);
    Agent::Stats tgt_stats_g = bm.getAgentStats(tgt);
    auto weapons = bm.getAgentWeapons(atk);
    const int wi_g2 = std::clamp(action.weapon_idx, 0, static_cast<int>(weapons.size()) - 1);
    const Weapon& w = weapons[static_cast<std::size_t>(wi_g2)];
    rollDamage(w, atk_stats_g, tgt_stats_g, result);   // miss was not a crit → normal damage
    result.hp_before = tgt_stats_g.hp_cur;
    const int dmg = result.total_damage;
    const int overflow = std::max(0, dmg - tgt_stats_g.temp_hp);
    tgt_stats_g.temp_hp = std::max(0, tgt_stats_g.temp_hp - dmg);
    tgt_stats_g.hp_cur  = std::clamp(tgt_stats_g.hp_cur - overflow, 0, tgt_stats_g.hp_max);
    result.hp_after = tgt_stats_g.hp_cur;
    result.target_down = (tgt_stats_g.hp_cur <= 0);
    bm.setAgentStats(tgt, tgt_stats_g);
    log_("Guided Strike turns a miss into a hit: {} damage to {}", dmg, agentName(bm, tgt));
    if (dmg > 0) {
        checkConcentrationOnDamage(bm, tgt, dmg);
        processDamageTaken(bm, tgt, dmg);
    }
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
    if (cs.lacksClass(CharacterClass::Cleric) ||
        cs.cleric_subclass != TrickeryDomain || cs.classLevel(CharacterClass::Cleric) < 3) return false;

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
    if (cs.lacksClass(CharacterClass::Cleric) ||
        cs.cleric_subclass != TrickeryDomain || cs.classLevel(CharacterClass::Cleric) < 6) return false;

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
    followAnchoredEffects(bm, cleric_idx);   // the cleric's Spirit Guardians goes with them
    log_("Trickster's Transposition: {} swaps places with the duplicate", agentName(bm, cleric_idx));
    return true;
}

bool CombatEngine::activateCoronaOfLight(BattleMap& bm, int idx) noexcept
{
    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.hp_max == 0 && stats.hp_cur == 0) return false;  // invalid idx

    // Requires a Light Domain Cleric of level 17+.
    if (stats.lacksClass(CharacterClass::Cleric) ||
        stats.cleric_subclass != LightDomain || stats.classLevel(CharacterClass::Cleric) < 17) return false;

    stats.corona_of_light_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(idx, stats);

    log_("{} activates Corona of Light: enemies within 60 ft have Disadvantage on saves vs its "
         "Fire/Radiant spells for 1 minute", agentName(bm, idx));
    return true;
}

TurnUndeadResult CombatEngine::useTurnUndead(BattleMap& bm, int caster_idx)
{
    TurnUndeadResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return result;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.lacksClass(CharacterClass::Cleric) || caster.classLevel(CharacterClass::Cleric) < 2) return result;

    Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return result;

    result.valid   = true;
    result.save_dc = rules::spellSaveDcFromAbility(caster, SaveWis);

    int wisMod = (caster.wis - 10) / 2;
    if (caster.wis < 10 && (caster.wis - 10) % 2 != 0) --wisMod;

    // Sear Undead (L5+): roll WIS-mod d8 (minimum 1d8) ONCE; each failed undead takes that total.
    int sear_total = 0;
    if (caster.classLevel(CharacterClass::Cleric) >= 5) {
        int sear_dice = std::max(1, wisMod);
        for (int i = 0; i < sear_dice; ++i) sear_total += roll(8);
        result.sear_damage = sear_total;
    }

    // Expend one Channel Divinity use (cd points into caster.resources; persist below).
    cd->spend(1);
    bm.setAgentStats(caster_idx, caster);
    log_("{} uses Turn Undead (DC {})", agentName(bm, caster_idx), result.save_dc);

    const Cell c_origin = agents[static_cast<std::size_t>(caster_idx)].origin;
    const int  c_size   = agents[static_cast<std::size_t>(caster_idx)].agent->getSize();

    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == caster_idx) continue;
        Agent::Stats tgt = bm.getAgentStats(i);
        if (!tgt.is_undead) continue;

        // Within 30 ft (Euclidean cell distance × 5 ft), matching Sphere targeting.
        const Cell o = agents[static_cast<std::size_t>(i)].origin;
        const double dx = o.col - c_origin.col, dy = o.row - c_origin.row;
        if (std::sqrt(dx * dx + dy * dy) * 5.0 > 30.0) continue;

        // The Emanation is blocked by Total Cover: an undead behind a wall is untouched.
        if (!bm.hasLineOfSight(c_origin, c_size, o, agents[static_cast<std::size_t>(i)].agent->getSize()))
            continue;

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
    return s.hasClass(CharacterClass::Cleric) &&
           s.cleric_subclass == LifeDomain && s.classLevel(CharacterClass::Cleric) >= 17;
}

int CombatEngine::discipleOfLifeBonus(const Agent::Stats& s, int slot_level) const noexcept
{
    if (s.hasClass(CharacterClass::Cleric) &&
        s.cleric_subclass == LifeDomain && s.classLevel(CharacterClass::Cleric) >= 3 && slot_level >= 1)
        return 2 + slot_level;
    return 0;
}

bool CombatEngine::graveCircleOfMortality(const Agent::Stats& caster,
                                          const Agent::Stats& target) const noexcept
{
    return caster.hasClass(CharacterClass::Cleric) && caster.cleric_subclass == GraveDomain &&
           caster.classLevel(CharacterClass::Cleric) >= 3 && target.hp_cur <= 0;
}

int CombatEngine::pullOfDeathDamage(BattleMap& bm, int cleric_idx, const Agent::Stats& target,
                                    int target_hp_before) noexcept
{
    const auto& agents = bm.placedAgents();
    if (cleric_idx < 0 || cleric_idx >= static_cast<int>(agents.size())) return 0;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.lacksClass(CharacterClass::Cleric) || cs.cleric_subclass != GraveDomain ||
        cs.classLevel(CharacterClass::Cleric) < 3) return 0;
    if (target_hp_before >= target.hp_max || target_hp_before <= 0) return 0;  // must be missing HP (and alive)
    Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
    if (cc.pull_of_death_turn == ctx_.turnCounter_) return 0;                  // once per turn
    const int die = cs.classLevel(CharacterClass::Cleric) >= 11 ? 6 : 4;
    const int raw = roll(die);
    const float mult = target.magic_damage_multipliers[static_cast<std::size_t>(Necrotic)];
    const int dmg = static_cast<int>(static_cast<float>(raw) * mult);
    cc.pull_of_death_turn = ctx_.turnCounter_;
    bm.setAgentConditions(cleric_idx, cc);
    log_("Pull of Death: +1d{} [{}] Necrotic{} = {}", die, raw,
         mult != 1.0f ? std::format(" x{:g}", mult) : std::string{}, dmg);
    return dmg;
}

bool CombatEngine::canPathToTheGrave(const BattleMap& bm, int cleric_idx, int target_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (cleric_idx < 0 || cleric_idx >= n || target_idx < 0 || target_idx >= n) return false;
    if (cleric_idx == target_idx) return false;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.lacksClass(CharacterClass::Cleric) || cs.cleric_subclass != GraveDomain ||
        cs.classLevel(CharacterClass::Cleric) < 3 || cs.hp_cur <= 0) return false;
    const Resource* cd = cs.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return false;
    if (!hasBonusAction(bm, cleric_idx)) return false;
    const Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
    if (cc.incapacitated || cc.unconscious || cc.dead) return false;
    const PlacedAgent& tp = agents[static_cast<std::size_t>(target_idx)];
    if (tp.removed_from_play || bm.getAgentStats(target_idx).hp_cur <= 0) return false;
    if (!canPerceiveTarget(bm, cleric_idx, target_idx)) return false;
    const PlacedAgent& cp = agents[static_cast<std::size_t>(cleric_idx)];
    return footprintDistance(cp.origin, cp.agent->getSize(), tp.origin, tp.agent->getSize()) * 5 <= 30;
}

bool CombatEngine::usePathToTheGrave(BattleMap& bm, int cleric_idx, int target_idx)
{
    if (!canPathToTheGrave(bm, cleric_idx, target_idx)) return false;
    if (!spendResource(bm, cleric_idx, "Channel Divinity", 1)) return false;
    (void)spendBonusAction(bm, cleric_idx);
    // One curse per cleric: lift any earlier one before laying the new curse.
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int i = 0; i < n; ++i) {
        Agent::Conditions c = bm.getAgentConditions(i);
        if (c.grave_cursed_by == cleric_idx) { c.grave_cursed_by = -1; bm.setAgentConditions(i, c); }
    }
    Agent::Conditions tc = bm.getAgentConditions(target_idx);
    tc.grave_cursed_by = cleric_idx;
    bm.setAgentConditions(target_idx, tc);
    log_("{} uses Path to the Grave: {} is cursed (Disadvantage on attacks and saves) until {}'s next turn",
         agentName(bm, cleric_idx), agentName(bm, target_idx), agentName(bm, cleric_idx));
    return true;
}

int CombatEngine::pathToTheGraveCleric(const BattleMap& bm, int attacker_idx, int target_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return -1;
    const int c = bm.getAgentConditions(target_idx).grave_cursed_by;
    if (c < 0 || c >= n) return -1;
    const Agent::Stats cs = bm.getAgentStats(c);
    if (cs.hp_cur <= 0) return -1;
    const Agent::Conditions cc = bm.getAgentConditions(c);
    if (cc.incapacitated || cc.unconscious || cc.dead) return -1;
    if (attacker_idx != c) {
        // "you or an ally you can see"
        if (!areAllies(bm, c, attacker_idx) || !canPerceiveTarget(bm, c, attacker_idx)) return -1;
    }
    return c;
}

bool CombatEngine::pathToTheGraveAutoRadiant(const Agent::Stats& target) const noexcept
{
    return target.magic_damage_multipliers[static_cast<std::size_t>(Radiant)] >=
           target.magic_damage_multipliers[static_cast<std::size_t>(Necrotic)];
}

int CombatEngine::detonatePathToTheGrave(BattleMap& bm, int cleric_idx, int attacker_idx, int target_idx,
                                         bool radiant, AttackResult* r, bool standalone)
{
    if (pathToTheGraveCleric(bm, attacker_idx, target_idx) != cleric_idx || cleric_idx < 0) return -1;
    Agent::Conditions tc = bm.getAgentConditions(target_idx);
    tc.grave_cursed_by = -1;                       // the curse ends
    bm.setAgentConditions(target_idx, tc);

    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    Agent::Stats ts = bm.getAgentStats(target_idx);
    const MagicDamage_t dtype = radiant ? Radiant : Necrotic;
    const int raw  = cs.classLevel(CharacterClass::Cleric);
    const float mult = ts.magic_damage_multipliers[static_cast<std::size_t>(dtype)];
    const int dmg  = static_cast<int>(static_cast<float>(raw) * mult);
    log_("{} ends Path to the Grave on {}: +{} {} damage", agentName(bm, cleric_idx),
         agentName(bm, target_idx), dmg, radiant ? "Radiant" : "Necrotic");
    if (r) {
        r->total_damage += dmg;
        r->damage_breakdown.push_back({"path to the grave", dmg});
        r->magic_damage_types.push_back(dtype);
        r->magic_damage_dealt[static_cast<std::size_t>(dtype)] += dmg;
    }
    if (dmg <= 0) return 0;

    const bool was_down = ts.hp_cur <= 0;
    const int hp_left = damageAgent(bm, target_idx, dmg);
    if (r) { r->hp_after = hp_left; r->target_down = (hp_left <= 0); }
    if (!standalone) return dmg;
    checkConcentrationOnDamage(bm, target_idx, dmg, attacker_idx);
    processDamageTaken(bm, target_idx, dmg, magicTypeBit(dtype));
    if (!was_down && hp_left <= 0) {
        const Agent::Conditions dc = bm.getAgentConditions(target_idx);
        if (!dc.unconscious && !dc.dead) {
            applyUnconscious(bm, target_idx);
            grantDarkOnesBlessing(bm, target_idx, attacker_idx);
        }
    }
    return dmg;
}

bool CombatEngine::canKeeperOfSouls(const BattleMap& bm, int cleric_idx) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (cleric_idx < 0 || cleric_idx >= n) return false;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.lacksClass(CharacterClass::Cleric) || cs.cleric_subclass != GraveDomain ||
        cs.classLevel(CharacterClass::Cleric) < 17 || cs.hp_cur <= 0) return false;
    const Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
    if (cc.incapacitated || cc.unconscious || cc.dead) return false;
    const Resource* k = cs.getResource("Keeper of Souls");
    return (k && k->current > 0) || keeperOfSoulsSlot(cs) > 0;
}

std::vector<int> CombatEngine::keeperOfSoulsTargets(const BattleMap& bm, int cleric_idx) const
{
    std::vector<int> out;
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (cleric_idx < 0 || cleric_idx >= n) return out;
    const PlacedAgent& cp = agents[static_cast<std::size_t>(cleric_idx)];
    for (int i = 0; i < n; ++i) {
        const PlacedAgent& p = agents[static_cast<std::size_t>(i)];
        if (p.removed_from_play || bm.getAgentConditions(i).dead) continue;
        if (i != cleric_idx) {
            if (!areAllies(bm, cleric_idx, i) || !canPerceiveTarget(bm, cleric_idx, i)) continue;
            if (footprintDistance(cp.origin, cp.agent->getSize(), p.origin, p.agent->getSize()) * 5 > 60) continue;
        }
        out.push_back(i);
    }
    return out;
}

int CombatEngine::keeperOfSoulsSlot(const Agent::Stats& s) const noexcept
{
    for (int lvl = 6; lvl <= 9; ++lvl)
        if (s.spell_slots_remaining[static_cast<std::size_t>(lvl - 1)] > 0) return lvl;
    return 0;
}

int CombatEngine::useKeeperOfSouls(BattleMap& bm, int cleric_idx, int target_idx, int slot_level)
{
    if (!canKeeperOfSouls(bm, cleric_idx)) return -1;
    const auto targets = keeperOfSoulsTargets(bm, cleric_idx);
    if (std::find(targets.begin(), targets.end(), target_idx) == targets.end()) return -1;
    Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (slot_level == 0) {
        Resource* k = cs.getResource("Keeper of Souls");
        if (!k || k->current <= 0) return -1;
        k->current -= 1;
    } else {
        // Restore the use with a level 6+ slot and spend it at once.
        if (slot_level < 6 || slot_level > 9) return -1;
        auto& slots = cs.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)];
        if (slots <= 0) return -1;
        slots -= 1;
    }
    bm.setAgentStats(cleric_idx, cs);
    Agent::Conditions cc = bm.getAgentConditions(cleric_idx);
    cc.keeper_of_souls_pending = false;
    bm.setAgentConditions(cleric_idx, cc);

    const int amount = 2 * cs.classLevel(CharacterClass::Cleric);
    const int before = bm.getAgentStats(target_idx).hp_cur;
    const int after  = healAgent(bm, target_idx, amount);
    log_("{}: Keeper of Souls — {} regains {} HP{}", agentName(bm, cleric_idx), agentName(bm, target_idx),
         after - before, slot_level > 0 ? std::format(" (level {} slot)", slot_level) : std::string{});
    return after - before;
}

void CombatEngine::onCreatureDied(BattleMap& bm, int dead_idx)
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (dead_idx < 0 || dead_idx >= n) return;
    vanishOrphanedCompanions(bm);   // Beast Master: the Primal Companion goes with its Ranger
    const PlacedAgent& dp = agents[static_cast<std::size_t>(dead_idx)];
    for (int c = 0; c < n; ++c) {
        if (c == dead_idx || !canKeeperOfSouls(bm, c)) continue;
        if (areAllies(bm, c, dead_idx) || bm.getAgentFaction(dead_idx) == 0) continue;   // an enemy must die
        const PlacedAgent& cp = agents[static_cast<std::size_t>(c)];
        if (footprintDistance(cp.origin, cp.agent->getSize(), dp.origin, dp.agent->getSize()) * 5 > 60) continue;
        const auto targets = keeperOfSoulsTargets(bm, c);
        if (decider_) {
            // Auto: heal the lowest HP% creature that is actually hurt; never spend a slot.
            const Resource* k = bm.getAgentStats(c).getResource("Keeper of Souls");
            if (!k || k->current <= 0) continue;
            int best = -1; float best_frac = 1.0f;
            for (int t : targets) {
                const Agent::Stats ts = bm.getAgentStats(t);
                if (ts.hp_max <= 0 || ts.hp_cur >= ts.hp_max) continue;
                const float frac = static_cast<float>(ts.hp_cur) / static_cast<float>(ts.hp_max);
                if (best < 0 || frac < best_frac) { best = t; best_frac = frac; }
            }
            if (best >= 0) (void)useKeeperOfSouls(bm, c, best, 0);
        } else if (!targets.empty()) {
            Agent::Conditions cc = bm.getAgentConditions(c);
            cc.keeper_of_souls_pending = true;
            bm.setAgentConditions(c, cc);
        }
    }
}

bool CombatEngine::canEnhancedNecromancy(const Agent::Stats& caster, const Spell& sp,
                                         int slot_level) const noexcept
{
    if (caster.lacksClass(CharacterClass::Cleric) || caster.cleric_subclass != GraveDomain ||
        caster.classLevel(CharacterClass::Cleric) < 17) return false;
    const Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return false;
    if (sp.geometry != Spell::Single) return false;
    // The Grave Domain Spells table (Ravenloft: The Horrors Within).
    static constexpr std::string_view kGraveSpells[] = {
        "Detect Evil and Good", "False Life", "Gentle Repose", "Ray of Enfeeblement", "Spare the Dying",
        "Revivify", "Vampiric Touch", "Blight", "Death Ward", "Dispel Evil and Good", "Raise Dead"};
    for (std::string_view n : kGraveSpells)
        if (sp.name == n) return true;
    const int lvl = std::max(sp.level, slot_level);
    return sp.school == Spell::Necromancy && lvl <= 5;
}

PreserveLifeResult CombatEngine::usePreserveLife(BattleMap& bm, int caster_idx,
                                                 const std::vector<int>& targets)
{
    PreserveLifeResult result;
    auto agents = bm.placedAgents();
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return result;

    Agent::Stats caster = bm.getAgentStats(caster_idx);
    if (caster.lacksClass(CharacterClass::Cleric) ||
        caster.cleric_subclass != LifeDomain || caster.classLevel(CharacterClass::Cleric) < 3) return result;

    Resource* cd = caster.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return result;

    result.valid = true;
    result.pool  = 5 * caster.classLevel(CharacterClass::Cleric);
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
        if (tgt.cant_heal) continue;              // can't regain HP (Chill Touch, Pit Fiend poison)
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

} // namespace rpg
