// ─────────────────────────────────────────────────────────────────────────────
//  combat_attack.cpp  –  CombatEngine weapon-attack pipeline
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The full weapon-attack pipeline: reach/threat checks, the to-hit roll, damage
//  rolling, attack resolution, and the high-level executeAction that wires in
//  every class on-hit/on-miss rider, weapon mastery, and post-damage bookkeeping.
//  Sections:
//    · Reach & threat — canAttack, hasDisadvantage, isThreatened, threateningAgents
//    · Attack roll    — rollToHit
//    · Damage         — rollDamage, damageAgent, processDamageTaken
//    · Resolution     — resolveAttack, executeAction
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

namespace rpg {

namespace {
    // Damage-type names for the damage-roll log line (mirrors the GUI's
    // _get_damage_type_names so logs read the same way on every attack path).
    const char* physicalDamageName(PhysicalDamage_t t) noexcept {
        switch (t) {
            case Bludgeoning: return "Bludgeoning";
            case Piercing:    return "Piercing";
            case Slashing:    return "Slashing";
            default:          return "Physical";
        }
    }
    const char* magicDamageName(MagicDamage_t t) noexcept {
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
}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  Reach & threat
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canAttack(const Weapon& w,
                               const BattleMap& bm,
                               Cell atk_origin, int atk_size,
                               Cell tgt_origin, int tgt_size) noexcept
{
    const int range_ft    = (w.type == WeaponType::Melee) ? w.reach_ft
                                                           : w.long_range_ft;
    const int range_cells = range_ft / 5;

    // Check every cell of the target's footprint: if any is within range
    // AND has LoS from the attacker, the attack is possible.
    for (int tr = tgt_origin.row; tr < tgt_origin.row + tgt_size; ++tr) {
        for (int tc = tgt_origin.col; tc < tgt_origin.col + tgt_size; ++tc) {
            int dist = chebyshevToFootprint(tc, tr, atk_origin, atk_size);
            if (dist <= range_cells
                    && bm.hasLineOfSight(atk_origin, atk_size, {tc, tr}, 1))
                return true;
        }
    }
    return false;
}

bool CombatEngine::hasDisadvantage(const Weapon& w,
                                    const BattleMap& /*bm*/,
                                    Cell atk_origin, int atk_size,
                                    Cell tgt_origin, int tgt_size) noexcept
{
    // Ranged (not thrown) weapons have disadvantage beyond normal_range_ft.
    if (w.type == WeaponType::Ranged && !w.thrown && w.normal_range_ft > 0) {
        int min_dist_cells = std::numeric_limits<int>::max();
        for (int tr = tgt_origin.row; tr < tgt_origin.row + tgt_size; ++tr) {
            for (int tc = tgt_origin.col; tc < tgt_origin.col + tgt_size; ++tc) {
                int d = chebyshevToFootprint(tc, tr, atk_origin, atk_size);
                min_dist_cells = std::min(min_dist_cells, d);
            }
        }
        if (min_dist_cells * 5 > w.normal_range_ft)
            return true;
    }
    // Future: disadvantage when ranged while adjacent to a threatening enemy,
    //         or other situational modifiers.
    return false;
}

bool CombatEngine::isThreatened(const BattleMap& bm, int attacker_idx) const noexcept
{
    auto agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()))
        return false;

    const PlacedAgent& atk = agents[attacker_idx];
    const int THREAT_DISTANCE = 2;  // 10 feet = 2 cells (each cell is 5 feet)

    // Check if any other agent is within 10 feet
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == attacker_idx) continue;  // Skip self

        const PlacedAgent& other = agents[i];
        if (other.agent->getConditions().incapacitated) continue;  // Skip incapacitated agents

        // Calculate Chebyshev distance (max of absolute differences)
        int dc = std::max({atk.origin.col - other.origin.col,
                           other.origin.col - (atk.origin.col + atk.agent->getSize() - 1),
                           0});
        int dr = std::max({atk.origin.row - other.origin.row,
                           other.origin.row - (atk.origin.row + atk.agent->getSize() - 1),
                           0});
        int dist = std::max(dc, dr);

        if (dist <= THREAT_DISTANCE)
            return true;
    }

    return false;
}

std::vector<int> CombatEngine::threateningAgents(const BattleMap& bm, int target_idx, int reach_cells) const {
    auto agents = bm.placedAgents();
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size()))
        return {};

    const PlacedAgent& tgt = agents[static_cast<std::size_t>(target_idx)];
    std::vector<int> result;

    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == target_idx) continue;
        const PlacedAgent& other = agents[static_cast<std::size_t>(i)];
        if (other.agent->getConditions().incapacitated) continue;
        if (other.agent->getStats().hp_cur <= 0) continue;

        // Chebyshev distance from target's footprint to other's origin
        int dc = std::max({tgt.origin.col - other.origin.col,
                           other.origin.col - (tgt.origin.col + tgt.agent->getSize() - 1),
                           0});
        int dr = std::max({tgt.origin.row - other.origin.row,
                           other.origin.row - (tgt.origin.row + tgt.agent->getSize() - 1),
                           0});
        int dist = std::max(dc, dr);

        if (dist <= reach_cells)
            result.push_back(i);
    }
    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Attack roll
// ─────────────────────────────────────────────────────────────────────────────

AttackResult CombatEngine::rollToHit(const Weapon& w,
                                      const Agent::Stats& attacker,
                                      int target_ac,
                                      bool advantage,
                                      bool disadvantage,
                                      int exhaustion_level)
{
    AttackResult r;
    r.disadvantage = disadvantage;
    r.advantage    = advantage;
    r.attack_mod   = attackModifier(w, attacker) + w.bonus_hit;
    // Paladin Oath of Devotion — Sacred Weapon: while active, add the stored CHA bonus to weapon attack rolls.
    if (attacker.character_class == CharacterClass::Paladin && attacker.sacred_weapon_turns > 0)
        r.attack_mod += attacker.sacred_weapon_bonus;
    r.target_ac    = target_ac;

    // Check if portent die is pending (need to apply after advantage/disadvantage logic)
    int pending_portent = pending_portent_die_;
    if (pending_portent >= 0) {
        pending_portent_die_ = -1;  // Consume it now
    }
    // Bardic Inspiration adds to the d20 Test total (not the natural die, so it never
    // creates/removes a crit). Capture it before the inner rolls so they don't consume it.
    int roll_bonus = consumePendingRollBonus();

    // Fold in any one-shot pending advantage/disadvantage (Tides of Chaos, etc.). Consumed
    // here so the inner roll(20) calls don't re-trigger it.
    const int pa = consumePendingAdvantage();
    advantage    = advantage    || pa > 0;
    disadvantage = disadvantage || pa < 0;
    // Reflect a folded-in one-shot grant (Lucky, Tides of Chaos, …) in the reported flags.
    r.advantage    = advantage;
    r.disadvantage = disadvantage;

    // If both advantage and disadvantage: they cancel out (roll normally)
    if (advantage && disadvantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = d1;
        log_("Advantage+disadvantage cancel: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else if (advantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = std::max(d1, d2);
        log_("Advantage: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else if (disadvantage) {
        int d1 = roll(20), d2 = roll(20);
        r.d20 = std::min(d1, d2);
        log_("Disadvantage: rolled {} and {} → kept {}", d1, d2, r.d20);
    } else {
        r.d20 = roll(20);
    }

    // Apply portent die if one was pending (after advantage/disadvantage selection)
    if (pending_portent >= 0) {
        log_("Portent Die: replacing roll {} with {}", r.d20, pending_portent);
        r.d20 = pending_portent;
    }

    r.critical   = (r.d20 >= attacker.crit_threshold);
    r.fumble     = (r.d20 == 1);
    r.total_roll = r.d20 + r.attack_mod - (2 * exhaustion_level) + roll_bonus;
    r.hit        = r.critical || (!r.fumble && r.total_roll >= target_ac);

    // Always surface the to-hit math (the adv/dis dice, if any, were logged just above). total_roll
    // folds in the attack mod, exhaustion (−2/level) and any roll bonus, so it can differ from
    // d20+mod; we show the natural d20, the weapon mod, and the final total compared to AC.
    const char* outcome = r.critical ? "CRITICAL HIT"
                        : r.fumble    ? "MISS (nat 1)"
                        : r.hit       ? "HIT" : "MISS";
    log_("To-hit: d20 {} {:+} = {} vs AC {} → {}", r.d20, r.attack_mod, r.total_roll, target_ac, outcome);

    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Damage
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::rollDamage(const Weapon& w,
                               const Agent::Stats& attacker,
                               const Agent::Stats& target,
                               AttackResult& result,
                               bool suppress_positive_mod)
{
    result.dice_results.clear();
    int raw = 0;

    // Build a per-type dice breakdown string for the log (mirrors the To-hit line so
    // every attack path — GUI/OA/reroll/RL — shows the dice that produced the damage).
    std::vector<std::string> log_parts;
    auto format_type = [&](int num_dice, int die_size, int type_damage,
                           float multiplier, const std::vector<int>& dice,
                           const char* type_name) {
        std::string dice_str;
        for (std::size_t i = 0; i < dice.size(); ++i) {
            if (i) dice_str += "+";
            dice_str += std::to_string(dice[i]);
        }
        std::string part = std::format("{}d{} [{}]={} {}", num_dice, die_size,
                                       dice_str, type_damage, type_name);
        if (multiplier != 1.0f) {
            part += std::format(" x{:g}={}", multiplier,
                                static_cast<int>(static_cast<float>(type_damage) * multiplier));
        }
        log_parts.push_back(std::move(part));
    };

    // Great Weapon Fighting style: with a two-handed melee weapon, treat any 1 or 2 on a
    // weapon damage die as a 3. Applies only to the weapon's own physical dice (below).
    const bool gwf = w.type == WeaponType::Melee && w.two_handed
                     && attacker.hasFeat("Great Weapon Fighting");

    // Roll physical damage types and apply target's multipliers
    for (const auto& dmg_roll : w.physicalDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        std::vector<int> type_dice;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            if (gwf && d < 3) d = 3;   // Great Weapon Fighting: 1 or 2 → 3
            result.dice_results.push_back(d);
            type_dice.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.physical_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.physical_damage_types.push_back(dmg_roll.type);
        format_type(num_dice, dmg_roll.die_size, type_damage, multiplier, type_dice,
                    physicalDamageName(dmg_roll.type));
    }

    // Roll magic damage types and apply target's multipliers
    for (const auto& dmg_roll : w.magicDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        std::vector<int> type_dice;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            result.dice_results.push_back(d);
            type_dice.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.magic_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.magic_damage_types.push_back(dmg_roll.type);
        format_type(num_dice, dmg_roll.die_size, type_damage, multiplier, type_dice,
                    magicDamageName(dmg_roll.type));
    }

    // Tavern Brawler (Origin feat) — Enhanced Unarmed Strike: a bare Unarmed Strike deals
    // 1d4 + STR Bludgeoning (vs the default 1 + STR). Damage Rerolls: reroll a 1 on the
    // die (once, keep the new roll). Scoped to the default "Unarmed" weapon — the Monk's
    // "MonkUnarmed" die supersedes this and is left untouched.
    if (w.name == "Unarmed" && attacker.hasFeat("Tavern Brawler")
            && !attacker.hasFeat("Unarmed Fighting")) {
        const int num_dice = result.critical ? 2 : 1;
        int type_damage = 0;
        std::vector<int> type_dice;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(4);
            if (d == 1) d = roll(4);   // Damage Rerolls: reroll a 1, must use the new roll
            result.dice_results.push_back(d);
            type_dice.push_back(d);
            type_damage += d;
        }
        float multiplier = target.physical_damage_multipliers[Bludgeoning];
        raw += static_cast<int>(static_cast<float>(type_damage) * multiplier);
        result.physical_damage_types.push_back(Bludgeoning);
        format_type(num_dice, 4, type_damage, multiplier, type_dice,
                    physicalDamageName(Bludgeoning));
    }

    // Unarmed Fighting style: a bare Unarmed Strike deals 1d6 Bludgeoning (vs the default
    // flat STR-only). Supersedes Tavern Brawler's 1d4 above when both are present. Scoped
    // to the default "Unarmed" weapon ("MonkUnarmed" supersedes this and is untouched).
    // DEFERRED: the 1d8-when-empty-handed upgrade (no weapon-array access here) and the
    // start-of-turn 1d4 to a creature you have Grappled.
    if (w.name == "Unarmed" && attacker.hasFeat("Unarmed Fighting")) {
        const int num_dice = result.critical ? 2 : 1;
        int type_damage = 0;
        std::vector<int> type_dice;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(6);
            result.dice_results.push_back(d);
            type_dice.push_back(d);
            type_damage += d;
        }
        float multiplier = target.physical_damage_multipliers[Bludgeoning];
        raw += static_cast<int>(static_cast<float>(type_damage) * multiplier);
        result.physical_damage_types.push_back(Bludgeoning);
        format_type(num_dice, 6, type_damage, multiplier, type_dice,
                    physicalDamageName(Bludgeoning));
    }

    int ability_mod = damageAbilityMod(w, attacker);
    // An off-hand (Two-Weapon Fighting) attack adds no ability modifier to its damage unless that
    // modifier is negative. The Two-Weapon Fighting style lifts the restriction entirely. The
    // off-hand weapon's `off_hand` flag is the per-attack signal (the main-hand weapon is never
    // flagged off_hand, so a dual-wielder's first attack keeps its mod).
    const bool offhand_no_mod = w.off_hand && !attacker.hasFeat("Two-Weapon Fighting");
    if ((suppress_positive_mod || offhand_no_mod) && ability_mod > 0) ability_mod = 0;  // Cleave / off-hand: keep only a negative mod
    result.damage_mod   = ability_mod + w.bonus_damage;
    result.total_damage = std::max(0, raw + result.damage_mod);
    result.damage_breakdown.clear();
    result.damage_breakdown.push_back({"weapon", result.total_damage});

    // Log: "Damage: 1d8 [6]=6 Slashing +4 = 10" (crit doubles the dice count shown).
    std::string dmg_line;
    for (std::size_t i = 0; i < log_parts.size(); ++i) {
        if (i) dmg_line += " + ";
        dmg_line += log_parts[i];
    }
    if (dmg_line.empty()) dmg_line = "—";
    log_("Damage: {} {:+} = {}{}", dmg_line, result.damage_mod, result.total_damage,
         result.critical ? " (CRIT)" : "");
}

int CombatEngine::damageAgent(BattleMap& bm, int idx, int amount) noexcept
{
    Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_max == 0 && s.hp_cur == 0) return 0;   // default-constructed → invalid idx
    // Temporary HP absorbs damage first, then overflow damages hp_cur
    int overflow = std::max(0, amount - s.temp_hp);
    s.temp_hp = std::max(0, s.temp_hp - amount);
    s.hp_cur = std::max(0, s.hp_cur - overflow);
    bm.setAgentStats(idx, s);

    // If agent is now dead, drop concentration
    if (s.hp_cur <= 0) {
        const auto& agents = bm.placedAgents();
        if (idx >= 0 && static_cast<std::size_t>(idx) < agents.size()) {
            Agent::Conditions cond = bm.getAgentConditions(idx);
            if (cond.concentrating) {
                std::string spell_name = cond.concentrating_on;
                cond.concentrating = false;
                cond.concentrating_on = "";
                bm.setAgentConditions(idx, cond);
                // Remove spell effects from this agent's concentration spell
                const auto& effects = bm.activeSpellEffects();
                std::vector<int> to_remove;
                for (const auto& effect : effects) {
                    if (effect.caster_idx == idx && effect.spell.name == spell_name) {
                        to_remove.push_back(effect.effect_id);
                    }
                }
                for (int effect_id : to_remove) {
                    bm.removeSpellEffect(effect_id);
                }
            }
        }
    }

    return s.hp_cur;
}

void CombatEngine::processDamageTaken(BattleMap& bm, int idx, int amount) noexcept
{
    if (amount <= 0) return;  // taking 0 damage is not "taking damage"
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    std::vector<int> to_remove;
    for (const auto& cond : activeAgentConditions_) {
        if (cond.agent_idx != idx) continue;

        if (cond.on_damage == OnDamage_t::End) {
            clearSpellConditionEffect(bm, cond);
            to_remove.push_back(cond.condition_id);
            log_("{} takes damage — {} ends.", agentName(bm, idx), cond.condition_name);
        } else if (cond.on_damage == OnDamage_t::RepeatSave) {
            Agent::Stats s = bm.getAgentStats(idx);
            auto saveMod = [&](SaveAbility_t ab) -> int {
                int score = 0; bool prof = false;
                switch (ab) {
                    case SaveStr: score = s.str;   prof = s.save_prof_str;   break;
                    case SaveDex: score = s.dex;   prof = s.save_prof_dex;   break;
                    case SaveCon: score = s.con;   prof = s.save_prof_con;   break;
                    case SaveInt: score = s.intel; prof = s.save_prof_intel; break;
                    case SaveWis: score = s.wis;   prof = s.save_prof_wis;   break;
                    default:      score = s.cha;   prof = s.save_prof_cha;   break;
                }
                int m = (score - 10) / 2;
                if (score < 10 && (score - 10) % 2 != 0) --m;
                return m + (prof ? s.prof_bonus : 0);
            };
            // Damage-triggered save is made at Advantage (Tasha's Hideous Laughter).
            int total = rollAdvantage(20, saveMod(cond.save_ability));
            if (total >= cond.save_dc) {
                clearSpellConditionEffect(bm, cond);
                to_remove.push_back(cond.condition_id);
                log_("{} shakes off {} after taking damage ({} vs DC {}).",
                     agentName(bm, idx), cond.condition_name, total, cond.save_dc);
            } else {
                log_("{} fails the on-damage save vs {} ({} vs DC {}).",
                     agentName(bm, idx), cond.condition_name, total, cond.save_dc);
            }
        }
    }
    for (int cid : to_remove) removeAgentCondition(cid);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Resolution
// ─────────────────────────────────────────────────────────────────────────────

AttackResult CombatEngine::resolveAttack(const Weapon& w,
                                          const Agent& attacker,
                                          const Agent& target,
                                          bool advantage,
                                          bool disadvantage,
                                          bool suppress_positive_mod)
{
    int target_ac = target.getStats().base_ac;
    AttackResult r = rollToHit(w, attacker.getStats(), target_ac, advantage, disadvantage, attacker.getConditions().exhaustion_level);
    r.hp_before = target.getStats().hp_cur;

    if (r.hit) {
        rollDamage(w, attacker.getStats(), target.getStats(), r, suppress_positive_mod);

        // Barbarian Rage damage bonus (STR-based attacks only)
        // Applies to melee and thrown weapons (where STR is the primary damage ability)
        if (attacker.getConditions().raging &&
            attacker.getStats().character_class == CharacterClass::Barbarian &&
            (w.type == WeaponType::Melee || w.thrown)) {
            int rage_bonus = getRageDamageBonus(attacker.getStats().char_level);
            r.total_damage += rage_bonus;
            r.damage_breakdown.push_back({"rage", rage_bonus});
        }

        // Compute resulting HP without mutating the target — the caller applies
        // the damage to its working stats copy and persists it once. (Temp HP
        // absorbs first, then overflow reduces hp_cur.)
        int overflow = std::max(0, r.total_damage - target.getStats().temp_hp);
        r.hp_after = std::clamp(target.getStats().hp_cur - overflow, 0, target.getStats().hp_max);
    } else {
        r.hp_after = target.getStats().hp_cur;
    }

    r.target_down = (r.hp_after <= 0);
    r.valid       = true;
    return r;
}

// Shield only matters on a non-critical hit whose +5 AC could actually flip the outcome to a miss,
// and only if the target can cast Shield right now. Shared gate so the inline (auto/RL) and
// suspendable (GUI) paths offer the reaction under identical conditions.
bool CombatEngine::shouldOfferDefenderShield(const BattleMap& bm, const Attack& action,
                                             const AttackResult& r) const
{
    if (!r.hit || r.critical) return false;
    if (r.total_roll >= r.target_ac + 5) return false;
    return canCastShield(bm, action.target_idx);
}

// Rogue Uncanny Dodge (L5+): the target may spend its reaction to halve an attack's damage. Pure
// damage-reduction OnHit reaction (no resource beyond the reaction), so it only matters on a hit that
// actually dealt damage.
bool CombatEngine::canUncannyDodge(const BattleMap& bm, int target_idx) const
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return false;
    const Agent::Conditions cond = bm.getAgentConditions(target_idx);
    if (cond.reaction_used || cond.incapacitated) return false;
    const Agent::Stats s = bm.getAgentStats(target_idx);
    if (s.hp_cur <= 0) return false;
    return s.character_class == CharacterClass::Rogue && s.char_level >= 5;
}

bool CombatEngine::applyUncannyDodge(BattleMap& bm, int reactor_idx, AttackResult& r)
{
    if (!canUncannyDodge(bm, reactor_idx)) return false;
    if (!r.hit || r.total_damage <= 0) return false;
    const int before = r.total_damage;
    r.total_damage   = before / 2;
    Agent::Conditions cond = bm.getAgentConditions(reactor_idx);
    cond.reaction_used = true;
    bm.setAgentConditions(reactor_idx, cond);
    r.damage_breakdown.push_back({"uncanny dodge", r.total_damage - before});  // negative: reduction
    log_("Uncanny Dodge: {} halves the attack ({} -> {})",
         agentName(bm, reactor_idx), before, r.total_damage);
    return true;
}

// Defensive Duelist (feat): on a non-crit MELEE hit, a wielder of a Finesse melee weapon may add its
// Proficiency Bonus to AC against the attack (reaction), flipping the hit to a miss when +PB clears the
// roll. Offered only when the +PB would actually flip the outcome and the reaction is free.
bool CombatEngine::canDefensiveDuelist(const BattleMap& bm, const Attack& action, const AttackResult& r) const
{
    if (!r.hit || r.critical) return false;
    const int tgt = action.target_idx;
    const auto& agents = bm.placedAgents();
    if (tgt < 0 || tgt >= static_cast<int>(agents.size())) return false;
    const Agent::Stats ts = bm.getAgentStats(tgt);
    if (!ts.hasFeat("Defensive Duelist")) return false;
    if (ts.hp_cur <= 0) return false;
    const Agent::Conditions tc = bm.getAgentConditions(tgt);
    if (tc.reaction_used || tc.incapacitated) return false;
    // Adding PB to AC must actually flip the hit to a miss (else the reaction is wasted).
    if (r.total_roll >= r.target_ac + ts.prof_bonus) return false;
    // RAW: the triggering attack must be a MELEE attack, and the defender must wield a Finesse melee weapon.
    const int atk = action.attacker_idx;
    if (atk >= 0 && atk < static_cast<int>(agents.size())) {
        const auto aw = bm.getAgentWeapons(atk);
        if (action.weapon_idx >= 0 && action.weapon_idx < static_cast<int>(aw.size()) &&
            aw[static_cast<std::size_t>(action.weapon_idx)].type != WeaponType::Melee)
            return false;
    }
    const auto tw = bm.getAgentWeapons(tgt);
    for (const Weapon& w : tw)
        if (w.finesse && w.type == WeaponType::Melee) return true;
    return false;
}

bool CombatEngine::applyDefensiveDuelist(BattleMap& bm, int reactor_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (reactor_idx < 0 || reactor_idx >= static_cast<int>(agents.size())) return false;
    Agent::Conditions c = bm.getAgentConditions(reactor_idx);
    if (c.reaction_used) return false;
    c.reaction_used = true;
    bm.setAgentConditions(reactor_idx, c);
    log_("{} uses Defensive Duelist (+{} AC) — the attack misses!",
         agentName(bm, reactor_idx), bm.getAgentStats(reactor_idx).prof_bonus);
    return true;
}

// The defender's OnHit options against a just-resolved attack: Shield (negate) and/or Uncanny Dodge
// (halve). Both cost the one reaction, so the menu lists every legal one and the chosen reaction
// spends the reaction (foreclosing the others). Always appended with Skip when non-empty.
std::vector<ReactionOption> CombatEngine::defenderOnHitOptions(const BattleMap& bm, const Attack& action,
                                                               const AttackResult& r) const
{
    std::vector<ReactionOption> opts;
    if (shouldOfferDefenderShield(bm, action, r))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Cast Shield (+5 AC — the attack misses)", "Shield"});
    if (r.hit && r.total_damage > 0 && canUncannyDodge(bm, action.target_idx))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Uncanny Dodge (halve the damage)", "UncannyDodge"});
    if (canDefensiveDuelist(bm, action, r))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Defensive Duelist (+PB AC — the attack misses)", "DefensiveDuelist"});
    if (!opts.empty())
        opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

bool CombatEngine::maybeDefenderOnHitInline(BattleMap& bm, const Attack& action, AttackResult& r)
{
    // Auto/RL only: the GUI (no decider) gets the suspendable window via beginAttack in step 3b.
    if (!decider_) return false;
    auto opts = defenderOnHitOptions(bm, action, r);
    if (opts.size() <= 1) return false;                  // only Skip (or nothing) → no reaction

    ReactionCtx ctx;
    ctx.window      = ReactionWindow::OnHit;
    ctx.reactor_idx = action.target_idx;
    ctx.source_idx  = action.attacker_idx;
    ctx.options     = std::move(opts);

    const ReactionResponse resp = decider_->chooseReaction(ctx);
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return false;
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return false;

    if (opt.feature == "Shield") {
        if (applyShield(bm, action.target_idx)) {
            r.hit = false;                  // DM ruling: a Shield-negated hit is a genuine miss.
            log_("{} casts Shield (+5 AC) — the attack misses!", agentName(bm, action.target_idx));
            return true;
        }
        return false;
    }
    if (opt.feature == "UncannyDodge")
        return applyUncannyDodge(bm, action.target_idx, r);
    if (opt.feature == "DefensiveDuelist") {
        if (applyDefensiveDuelist(bm, action.target_idx)) {
            r.hit = false;                  // DM ruling: a Defensive-Duelist-negated hit is a genuine miss.
            return true;
        }
        return false;
    }
    return false;
}

int CombatEngine::riposteWeaponIdx(const BattleMap& bm, int idx) const
{
    const auto weapons = bm.getAgentWeapons(idx);
    for (int i = 0; i < static_cast<int>(weapons.size()); ++i)
        if (weapons[static_cast<std::size_t>(i)].type == WeaponType::Melee) return i;
    return -1;
}

bool CombatEngine::canRiposte(const BattleMap& bm, int defender_idx, int attacker_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (defender_idx < 0 || defender_idx >= n || attacker_idx < 0 || attacker_idx >= n) return false;
    if (defender_idx == attacker_idx) return false;
    const Agent::Conditions cond = bm.getAgentConditions(defender_idx);
    if (cond.reaction_used || cond.incapacitated) return false;
    const Agent::Stats s = bm.getAgentStats(defender_idx);
    if (s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Fighter || s.fighter_subclass != BattleMasterPath) return false;
    const Resource* sd = s.getResource("Superiority Dice");
    if (!sd || sd->current <= 0) return false;
    if (riposteWeaponIdx(bm, defender_idx) < 0) return false;          // needs a melee weapon to strike back
    // The attacker must be within the defender's melee reach (1 cell = 5 ft; reach weapons deferred).
    const auto threats = threateningAgents(bm, defender_idx, 1);
    return std::find(threats.begin(), threats.end(), attacker_idx) != threats.end();
}

bool CombatEngine::maybeRiposteInline(BattleMap& bm, const Attack& action, AttackResult& r)
{
    // Auto/RL only: the GUI (no decider) gets the deferred-flag prompt via riposte_available.
    if (!decider_) return false;
    if (r.hit) return false;
    const int defender = action.target_idx;       // the one who was missed → may riposte
    const int attacker = action.attacker_idx;
    Agent::Conditions dcond = bm.getAgentConditions(defender);
    if (!dcond.riposte_available) return false;    // set by applyAttackResult on an eligible melee miss
    const int widx = riposteWeaponIdx(bm, defender);
    if (widx < 0) { dcond.riposte_available = false; bm.setAgentConditions(defender, dcond); return false; }

    ReactionCtx ctx;
    ctx.window      = ReactionWindow::OnMiss;
    ctx.reactor_idx = defender;
    ctx.source_idx  = attacker;
    ctx.options.push_back(ReactionOption{ReactionOption::Feature, widx,
                                         "Riposte (reaction + 1 Superiority Die)", "Riposte"});
    ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});

    const ReactionResponse resp = decider_->chooseReaction(ctx);
    const bool accepted = resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                          ctx.options[static_cast<std::size_t>(resp.option)].kind == ReactionOption::Feature &&
                          ctx.options[static_cast<std::size_t>(resp.option)].feature == "Riposte";
    if (!accepted) {
        dcond.riposte_available = false;           // declined: drop the stale flag (resets at turn start anyway)
        bm.setAgentConditions(defender, dcond);
        return false;
    }
    (void)applyRiposte(bm, defender, attacker, widx);
    return true;
}

// ── Sentinel feat — Guardian (OnAllyAttacked bystander reaction) ─────────────
// RAW 2024: when a creature within 5 ft of you makes an attack against a target other than you (and
// that target doesn't have the Sentinel feat), you may use your reaction to make a melee attack
// against the attacking creature. Fires on a hit OR a miss (it keys on the attack being made, not the
// outcome) and never alters the original attack — it's a pure counter-strike.
bool CombatEngine::canSentinelGuard(const BattleMap& bm, const Attack& action, int sentinel_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx;
    const int tgt = action.target_idx;
    if (sentinel_idx < 0 || sentinel_idx >= n || atk < 0 || atk >= n) return false;
    if (sentinel_idx == atk || sentinel_idx == tgt) return false;   // the attack must be against someone OTHER than the Sentinel
    const Agent::Stats ss = bm.getAgentStats(sentinel_idx);
    if (!ss.has_sentinel || ss.hp_cur <= 0) return false;
    const Agent::Conditions sc = bm.getAgentConditions(sentinel_idx);
    if (sc.reaction_used || sc.incapacitated) return false;
    if (tgt >= 0 && tgt < n && bm.getAgentStats(tgt).has_sentinel) return false;  // RAW: target must not have the feat
    if (riposteWeaponIdx(bm, sentinel_idx) < 0) return false;       // needs a melee weapon to strike back
    // The attacking creature must be within the Sentinel's 5 ft reach (1 cell; reach weapons deferred).
    const auto threats = threateningAgents(bm, sentinel_idx, 1);
    return std::find(threats.begin(), threats.end(), atk) != threats.end();
}

// ── Interception fighting style — eligibility for one bystander vs a hit on someone else ─────
bool CombatEngine::canIntercept(const BattleMap& bm, const Attack& action,
                                int interceptor_idx, int damage_taken) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx;
    const int tgt = action.target_idx;
    if (interceptor_idx < 0 || interceptor_idx >= n || atk < 0 || atk >= n || tgt < 0 || tgt >= n)
        return false;
    if (interceptor_idx == atk || interceptor_idx == tgt) return false;  // protect a creature OTHER than yourself
    if (damage_taken <= 0) return false;

    const Agent::Stats is = bm.getAgentStats(interceptor_idx);
    if (!is.hasFeat("Interception") || is.hp_cur <= 0) return false;
    const Agent::Conditions ic = bm.getAgentConditions(interceptor_idx);
    if (ic.reaction_used || ic.incapacitated) return false;

    // v1 heal-back model: cannot rescue a target already dropped to 0 by the hit (see known_limitations).
    if (bm.getAgentStats(tgt).hp_cur <= 0) return false;

    // Must be holding a Shield or a Simple/Martial weapon (≈ any real weapon with damage dice).
    bool armed = isHoldingShield(bm, interceptor_idx);
    if (!armed) {
        for (const Weapon& w : agents[static_cast<std::size_t>(interceptor_idx)].weapons)
            if (!w.physicalDamageRolls.empty() || !w.magicDamageRolls.empty()) { armed = true; break; }
    }
    if (!armed) return false;

    // "A creature you can see hits…": the interceptor must be able to perceive the attacker.
    if (!canPerceiveTarget(bm, interceptor_idx, atk)) return false;

    // Within 5 ft (1 cell) of the TARGET being hit. Footprint Chebyshev (mirrors threateningAgents).
    const PlacedAgent& tp = agents[static_cast<std::size_t>(tgt)];
    const PlacedAgent& ip = agents[static_cast<std::size_t>(interceptor_idx)];
    const int dc = std::max({tp.origin.col - ip.origin.col,
                             ip.origin.col - (tp.origin.col + tp.agent->getSize() - 1), 0});
    const int dr = std::max({tp.origin.row - ip.origin.row,
                             ip.origin.row - (tp.origin.row + tp.agent->getSize() - 1), 0});
    return std::max(dc, dr) <= 1;
}

bool CombatEngine::maybeSentinelGuardInline(BattleMap& bm, const Attack& action, AttackResult& /*r*/)
{
    // Auto/RL only: the GUI (no decider) gets the deferred-flag prompt via sentinel_guard_available.
    if (!decider_) return false;
    if (resolving_sentinel_guard_) return false;          // a guard counter-attack doesn't provoke its own guard
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int sentinel = 0; sentinel < n; ++sentinel) {
        if (!canSentinelGuard(bm, action, sentinel)) continue;
        const int widx = riposteWeaponIdx(bm, sentinel);
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnAllyAttacked;
        ctx.reactor_idx = sentinel;
        ctx.source_idx  = action.attacker_idx;
        ctx.options.push_back(ReactionOption{ReactionOption::Feature, widx,
                                             "Sentinel Guardian (melee attack vs the attacker)", "SentinelGuard"});
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        const ReactionResponse resp = decider_->chooseReaction(ctx);
        if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) continue;
        const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
        if (opt.kind != ReactionOption::Feature || opt.feature != "SentinelGuard") continue;
        (void)applySentinelGuard(bm, sentinel, action.attacker_idx, widx);
        return true;                                      // one guard per attack (reaction-economy bounds the chain)
    }
    return false;
}

bool CombatEngine::maybeInterceptionInline(BattleMap& bm, const Attack& action, AttackResult& r)
{
    // Auto/RL only: the GUI (no decider) scans via can_intercept + _offer_interception.
    if (!decider_) return false;
    if (!r.hit || r.total_damage <= 0) return false;
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int i = 0; i < n; ++i) {
        if (!canIntercept(bm, action, i, r.total_damage)) continue;
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnAllyAttacked;
        ctx.reactor_idx = i;
        ctx.source_idx  = action.attacker_idx;
        ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                             "Interception (reduce the damage by 1d10 + PB)", "Interception"});
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        const ReactionResponse resp = decider_->chooseReaction(ctx);
        if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) continue;
        const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
        if (opt.kind != ReactionOption::Feature || opt.feature != "Interception") continue;
        (void)applyInterception(bm, i, action.target_idx, r.total_damage);
        return true;                                      // one interception per attack
    }
    return false;
}

// War Domain Guided Strike eligibility for one cleric vs a just-missed attack (shared by the GUI flag
// in applyAttackResult and the auto/RL OnMiss window). The attacker itself may guide its own miss
// (no reaction cost — Channel Divinity only); an ally cleric within 30 ft pays its reaction too.
bool CombatEngine::canGuidedStrike(const BattleMap& bm, const Attack& action, int cleric_idx) const
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    const int atk = action.attacker_idx;
    if (cleric_idx < 0 || cleric_idx >= n || atk < 0 || atk >= n) return false;
    const Agent::Stats cs = bm.getAgentStats(cleric_idx);
    if (cs.character_class != CharacterClass::Cleric ||
        cs.cleric_subclass != WarDomain || cs.char_level < 3) return false;
    const Resource* cd = cs.getResource("Channel Divinity");
    if (!cd || cd->current <= 0) return false;
    if (cleric_idx == atk) return true;                       // self-guide: no reaction needed
    if (bm.getAgentConditions(cleric_idx).reaction_used) return false;
    const Cell co = agents[static_cast<std::size_t>(cleric_idx)].origin;
    const Cell ao = agents[static_cast<std::size_t>(atk)].origin;
    const double dx = co.col - ao.col, dy = co.row - ao.row;
    return std::sqrt(dx * dx + dy * dy) * 5.0 <= 30.0;
}

bool CombatEngine::maybeGuidedStrikeInline(BattleMap& bm, const Attack& action, AttackResult& r)
{
    // Auto/RL only: the GUI (no decider) gets the deferred-flag prompt via guided_strike_available.
    if (!decider_) return false;
    if (r.hit || r.fumble) return false;                      // only a non-fumble miss can be guided
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int cleric = 0; cleric < n; ++cleric) {
        if (!canGuidedStrike(bm, action, cleric)) continue;
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnMiss;
        ctx.reactor_idx = cleric;
        ctx.source_idx  = action.attacker_idx;
        ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                             "Guided Strike (+10, 1 Channel Divinity)", "GuidedStrike"});
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        const ReactionResponse resp = decider_->chooseReaction(ctx);
        if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) continue;
        const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
        if (opt.kind != ReactionOption::Feature || opt.feature != "GuidedStrike") continue;
        applyGuidedStrike(bm, action, cleric, r);             // +10; may turn the miss into a hit
        return true;                                          // one guide per attack (the +10 is spent)
    }
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────
//  OnD20Seen reactions (attack rolls only)
//  Nearby creatures may LOWER a just-rolled attack roll (Bend Luck penalty / Cutting Words /
//  Silvery Barbs reroll). v1 is lowering-only: the sole outcome change is hit → miss, so the apply
//  path mirrors Shield (set r.hit=false; no post-hoc damage roll). The invariant total_roll =
//  d20 + attack_mod is maintained, so a later Silvery Barbs reroll carries any earlier penalty.
// ─────────────────────────────────────────────────────────────────────────────

// Shared "within 60 ft + line-of-sight to the roller, reaction free, alive, not the roller" gate
// (mirrors canCastCounterspell's range check). Feature-specific requirements layer on top.
static bool d20ReactorBase(const BattleMap& bm, int reactor, int roller)
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n || roller < 0 || roller >= n || reactor == roller) return false;
    const Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated) return false;
    if (bm.getAgentStats(reactor).hp_cur <= 0) return false;
    const PlacedAgent& rpa = agents[static_cast<std::size_t>(reactor)];
    const PlacedAgent& opa = agents[static_cast<std::size_t>(roller)];
    if (footprintDistance(rpa.origin, rpa.agent->getSize(),
                          opa.origin, opa.agent->getSize()) * 5 > 60) return false;
    return bm.hasLineOfSight(rpa.origin, rpa.agent->getSize(), opa.origin, opa.agent->getSize());
}

bool CombatEngine::canBendLuck(const BattleMap& bm, int reactor, int roller) const
{
    if (!d20ReactorBase(bm, reactor, roller)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Sorcerer ||
        s.sorcerer_subclass != SorcererSubclass::WildMagicPath || s.char_level < 6) return false;
    const Resource* sp = s.getResource("Sorcery Points");
    return sp && sp->current >= 1;
}

bool CombatEngine::canCuttingWords(const BattleMap& bm, int reactor, int roller) const
{
    if (!d20ReactorBase(bm, reactor, roller)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Bard ||
        s.bard_subclass != BardCollege::LorePath || s.char_level < 3) return false;
    const Resource* bi = s.getResource("Bardic Inspiration");
    return bi && bi->current >= 1;
}

bool CombatEngine::canSilveryBarbs(const BattleMap& bm, int reactor, int roller) const
{
    if (!d20ReactorBase(bm, reactor, roller)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    bool has_slot = false;                                  // Silvery Barbs is a 1st-level spell
    for (int i = 0; i < 9; ++i)
        if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) { has_slot = true; break; }
    if (!has_slot) return false;
    for (const auto& sp : bm.getAgentSpells(reactor))
        if (sp.name == "Silvery Barbs") return true;
    return false;
}

void CombatEngine::reevaluateAttackHit(AttackResult& r) const noexcept
{
    r.fumble = (r.d20 == 1);
    if      (r.d20 == 20) { r.critical = true;  r.hit = true;  }   // nat 20 always hits/crits
    else if (r.d20 == 1)  { r.critical = false; r.hit = false; }   // nat 1 always misses
    else                  { r.critical = false; r.hit = (r.total_roll >= r.target_ac); }
}

bool CombatEngine::applyBendLuckToAttack(BattleMap& bm, int reactor, AttackResult& r)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated || s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Sorcerer ||
        s.sorcerer_subclass != SorcererSubclass::WildMagicPath || s.char_level < 6) return false;
    Resource* sp = s.getResource("Sorcery Points");
    if (!sp || sp->current < 1) return false;

    sp->current -= 1;
    cond.reaction_used = true;
    const int v = roll(4);                                 // 1d4 PENALTY (lowering-only v1)
    r.attack_mod -= v;                                     // keep total_roll = d20 + attack_mod
    r.total_roll  = r.d20 + r.attack_mod;
    reevaluateAttackHit(r);
    bm.setAgentStats(reactor, s);
    bm.setAgentConditions(reactor, cond);
    log_("{} uses Bend Luck: -{} (now {} vs AC {}) → {}", agentName(bm, reactor), v,
         r.total_roll, r.target_ac, r.hit ? "still hits" : "the attack MISSES");
    return true;
}

bool CombatEngine::applyCuttingWordsToAttack(BattleMap& bm, int reactor, AttackResult& r)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated || s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Bard ||
        s.bard_subclass != BardCollege::LorePath || s.char_level < 3) return false;
    Resource* bi = s.getResource("Bardic Inspiration");
    if (!bi || bi->current < 1) return false;

    bi->current -= 1;
    cond.reaction_used = true;
    const int v = roll(s.bardic_inspiration_die_size);     // subtract the Bardic Inspiration die
    r.attack_mod -= v;
    r.total_roll  = r.d20 + r.attack_mod;
    reevaluateAttackHit(r);
    bm.setAgentStats(reactor, s);
    bm.setAgentConditions(reactor, cond);
    log_("{} uses Cutting Words: -{} (now {} vs AC {}) → {}", agentName(bm, reactor), v,
         r.total_roll, r.target_ac, r.hit ? "still hits" : "the attack MISSES");
    return true;
}

bool CombatEngine::applySilveryBarbsToAttack(BattleMap& bm, int reactor, AttackResult& r)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated || s.hp_cur <= 0) return false;
    int slot = -1;                                         // spend the lowest available L1+ slot
    for (int i = 0; i < 9; ++i)
        if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) { slot = i; break; }
    if (slot < 0) return false;
    bool knows = false;
    for (const auto& sp : bm.getAgentSpells(reactor))
        if (sp.name == "Silvery Barbs") { knows = true; break; }
    if (!knows) return false;

    s.spell_slots_remaining[static_cast<std::size_t>(slot)] -= 1;
    cond.reaction_used = true;
    const int old_d20 = r.d20;
    r.d20        = roll(20);                               // force a reroll; attacker uses the new die
    r.total_roll = r.d20 + r.attack_mod;                   // carries any earlier penalty (invariant)
    reevaluateAttackHit(r);
    bm.setAgentStats(reactor, s);
    bm.setAgentConditions(reactor, cond);
    log_("{} casts Silvery Barbs: rerolls the d20 {}→{} (now {} vs AC {}) → {}", agentName(bm, reactor),
         old_d20, r.d20, r.total_roll, r.target_ac, r.hit ? "still hits" : "the attack MISSES");
    return true;
}

// Which creatures may lower this attack roll, in index order. Only on a hit (a miss/fumble can't be
// lowered further). Additive reactions (Bend Luck/Cutting Words) can't change a natural 20, so they
// only count off a nat-20; Silvery Barbs' reroll can change anything (including a crit).
std::vector<int> CombatEngine::d20SeenReactors(const BattleMap& bm, const Attack& action,
                                               const AttackResult& r) const
{
    std::vector<int> out;
    if (!r.hit) return out;                                // nothing to lower
    const int roller = action.attacker_idx;
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int i = 0; i < n; ++i) {
        if (i == roller) continue;
        const bool additive = (r.d20 != 20) && (canBendLuck(bm, i, roller) || canCuttingWords(bm, i, roller));
        const bool reroll   = canSilveryBarbs(bm, i, roller);
        if (additive || reroll) out.push_back(i);
    }
    return out;
}

std::vector<ReactionOption> CombatEngine::d20SeenOptions(const BattleMap& bm, int reactor,
                                                         const Attack& action, const AttackResult& r) const
{
    std::vector<ReactionOption> opts;
    const int roller = action.attacker_idx;
    if (r.d20 != 20 && canBendLuck(bm, reactor, roller))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1, "Bend Luck (-1d4, 1 Sorcery Point)", "BendLuck"});
    if (r.d20 != 20 && canCuttingWords(bm, reactor, roller))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1, "Cutting Words (-1 Bardic die)", "CuttingWords"});
    if (canSilveryBarbs(bm, reactor, roller))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1, "Silvery Barbs (force a reroll)", "SilveryBarbs"});
    if (!opts.empty())
        opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

void CombatEngine::applyD20SeenReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // skip/invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;
    AttackResult& r = in_flight_attack_.r;
    if      (opt.feature == "BendLuck")     applyBendLuckToAttack(bm, ctx.reactor_idx, r);
    else if (opt.feature == "CuttingWords") applyCuttingWordsToAttack(bm, ctx.reactor_idx, r);
    else if (opt.feature == "SilveryBarbs") applySilveryBarbsToAttack(bm, ctx.reactor_idx, r);
}

bool CombatEngine::maybeD20SeenInline(BattleMap& bm, const Attack& action, AttackResult& r)
{
    // Auto/RL only: the GUI (no decider) gets the suspendable window via advanceAttack.
    if (!decider_) return false;
    bool changed = false;
    for (int reactor : d20SeenReactors(bm, action, r)) {
        if (!r.hit) break;                                 // already lowered to a miss → stop
        auto opts = d20SeenOptions(bm, reactor, action, r);
        if (opts.size() <= 1) continue;                    // only Skip (reactor no longer qualifies)
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnD20Seen;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = action.attacker_idx;
        ctx.options     = opts;
        ctx.d20_value   = r.total_roll;
        const ReactionResponse resp = decider_->chooseReaction(ctx);
        if (resp.option < 0 || resp.option >= static_cast<int>(opts.size())) continue;
        const ReactionOption& o = opts[static_cast<std::size_t>(resp.option)];
        if (o.kind != ReactionOption::Feature) continue;
        if      (o.feature == "BendLuck")     changed |= applyBendLuckToAttack(bm, reactor, r);
        else if (o.feature == "CuttingWords") changed |= applyCuttingWordsToAttack(bm, reactor, r);
        else if (o.feature == "SilveryBarbs") changed |= applySilveryBarbsToAttack(bm, reactor, r);
    }
    return changed;
}

// Apply the chosen OnHit defender reaction to the in-flight attack: Shield (negate) or Uncanny Dodge
// (halve damage). Mirrors applyCastReaction: on accept, spend the resource+reaction and mutate
// in_flight_attack_.r so advanceAttack's applyAttackResult sees the result. A Shield negation rolls no
// damage / fires no concentration save (per DM ruling a genuine miss, so the attacker's miss-branch
// features still fire later); Uncanny Dodge leaves the hit but reduces the damage applied.
void CombatEngine::applyAttackReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // skip/invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;
    if (opt.feature == "Shield") {
        if (applyShield(bm, ctx.reactor_idx)) {
            in_flight_attack_.r.hit = false;
            log_("{} casts Shield (+5 AC) — the attack misses!", agentName(bm, ctx.reactor_idx));
        }
    } else if (opt.feature == "UncannyDodge") {
        applyUncannyDodge(bm, ctx.reactor_idx, in_flight_attack_.r);
    } else if (opt.feature == "DefensiveDuelist") {
        if (applyDefensiveDuelist(bm, ctx.reactor_idx))
            in_flight_attack_.r.hit = false;
    }
}

// beginAttack — GUI/interactive entry to a weapon attack. Runs phase A
// (determineAdvantage) and the roll (resolveAttack) into the in-flight state, then hands off to
// advanceAttack which opens the Shield window or finalizes. The auto/RL path stays on executeAction
// (inline Shield). Result is read via lastAttackResult(); submitDecision resumes a parked attack.
FlowStatus CombatEngine::beginAttack(BattleMap& bm, const Attack& action)
{
    in_flight_attack_             = InFlightAttack{};
    in_flight_attack_.active      = true;
    in_flight_attack_.interactive = true;
    in_flight_attack_.action      = action;
    InFlightAttack& s = in_flight_attack_;
    if (!determineAdvantage(bm, s)) {            // illegal/blocked attack (s.r stays valid == false)
        last_attack_result_ = s.r;
        s.active = false;
        return FlowStatus::Completed;
    }
    auto agents = bm.placedAgents();
    const PlacedAgent& atk_pt = agents[static_cast<std::size_t>(action.attacker_idx)];
    const PlacedAgent& tgt_pt = agents[static_cast<std::size_t>(action.target_idx)];
    s.r = resolveAttack(s.w, *atk_pt.agent, *tgt_pt.agent, s.adv, s.dis, action.no_ability_damage);
    return advanceAttack(bm);
}

// advanceAttack — drive the in-flight attack. If a defender Shield window should open (GUI path only),
// suspend at the OnHit checkpoint; the GUI resumes via submitDecision → applyAttackReaction → here
// again, where the gate is now false/consumed and we finalize. applyAttackResult re-fetches working
// stats, so a Shield cast in the window (its +5 AC / slot spend) is reflected.
FlowStatus CombatEngine::advanceAttack(BattleMap& bm)
{
    InFlightAttack& s = in_flight_attack_;
    // OnD20Seen window (BEFORE Shield): nearby creatures may lower the roll. Build the reactor list
    // once (post-roll), then offer each in turn. submitDecision advances d20_cursor on each resume, so
    // a Skip simply moves to the next reactor; a lowering reaction that flips the hit to a miss then
    // makes the Shield gate below false.
    if (s.interactive && !s.d20_window_built) {
        s.d20_reactors     = d20SeenReactors(bm, s.action, s.r);
        s.d20_window_built = true;
    }
    while (s.interactive && s.d20_cursor < s.d20_reactors.size()) {
        const int reactor = s.d20_reactors[s.d20_cursor];
        auto opts = d20SeenOptions(bm, reactor, s.action, s.r);   // re-checked: an earlier window may
        if (opts.size() <= 1) { ++s.d20_cursor; continue; }       // have spent this reactor's resource
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnD20Seen;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = s.action.attacker_idx;
        ctx.options     = std::move(opts);
        ctx.d20_value   = s.r.total_roll;
        pending_decision_ = PendingDecision{true, ctx};           // suspend; GUI resumes via submitDecision
        return FlowStatus::AwaitingDecision;
    }
    // Offer the OnHit defender window (Shield and/or Uncanny Dodge) at most once: on resume after a Skip
    // the hit still stands, so without this guard the gate would stay true and re-park forever (single
    // reactor, no cursor). applyAttackReaction (via submitDecision) spends the one reaction.
    if (s.interactive && !s.onhit_offered) {
        auto opts = defenderOnHitOptions(bm, s.action, s.r);
        if (opts.size() > 1) {
            s.onhit_offered = true;
            ReactionCtx ctx;
            ctx.window      = ReactionWindow::OnHit;
            ctx.reactor_idx = s.action.target_idx;
            ctx.source_idx  = s.action.attacker_idx;
            ctx.options     = std::move(opts);
            pending_decision_ = PendingDecision{true, ctx};   // suspend; GUI resumes via submitDecision
            return FlowStatus::AwaitingDecision;
        }
        s.onhit_offered = true;   // nothing to offer — don't re-check on a later resume
    }
    pending_decision_.active = false;
    last_attack_result_ = applyAttackResult(bm, s);
    s.active = false;
    return FlowStatus::Completed;
}

// ── determineAdvantage: phase A — validate the attack and compute advantage/disadvantage + the
// pre-roll snapshots applyAttackResult will need, into `s`. Returns false for an illegal/blocked
// attack (s.r stays valid==false). STOPS before the roll: the caller does s.r = resolveAttack(...).
bool CombatEngine::determineAdvantage(BattleMap& bm, InFlightAttack& s)
{
    const Attack& action = s.action;

    auto agents = bm.placedAgents();
    int  n      = static_cast<int>(agents.size());

    if (action.attacker_idx < 0 || action.attacker_idx >= n) return false;
    if (action.target_idx   < 0 || action.target_idx   >= n) return false;
    if (action.attacker_idx == action.target_idx)             return false;

    const PlacedAgent& atk_pt = agents[action.attacker_idx];
    const PlacedAgent& tgt_pt = agents[action.target_idx];


    // beginning of checking if it's mechanically possible to attack this round

    // Check if attacker is charmed and target is the charmer
    if (atk_pt.agent->getConditions().charmed) {
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.attacker_idx &&
                cond.condition_name == "Charmed" &&
                cond.caster_idx == action.target_idx) {
                log_("Attack blocked: attacker is charmed and cannot attack the charmer");
                return false;
            }
        }
    }

    // Check if attacker slipped this turn
    if (atk_pt.agent->hasSlippedThisTurn()) {
        log_("Attack blocked: attacker slipped and cannot act this turn");
        return false;
    }

    if (action.weapon_idx < 0 ||
            action.weapon_idx >= static_cast<int>(atk_pt.weapons.size()))
        return false;

    Weapon w = atk_pt.weapons[static_cast<std::size_t>(action.weapon_idx)];
    // Note: an off-hand (Two-Weapon Fighting) attack uses the same attack roll as any other —
    // proficiency to-hit DOES apply (RAW). The only off-hand penalty is on damage (no positive
    // ability mod unless the Two-Weapon Fighting style), handled in rollDamage via w.off_hand.

    int atk_sz = atk_pt.agent->getSize();
    int tgt_sz = tgt_pt.agent->getSize();

    if (!canAttack(w, bm, atk_pt.origin, atk_sz, tgt_pt.origin, tgt_sz))
        return false;


    // end of checking if it's mechanically possible to attack this round


    // beginning of determination of advantage / disadvantage
    
    bool disadv = hasDisadvantage(w, bm,
                                   atk_pt.origin, atk_sz,
                                   tgt_pt.origin, tgt_sz);

    // Sharpshooter (general feat) — Long Range: attacking at long range imposes no
    // Disadvantage. hasDisadvantage returns only the long-range penalty here, so clearing
    // disadv before the engagement check below removes exactly that benefit.
    if (disadv && atk_pt.agent->getStats().hasFeat("Sharpshooter")) {
        disadv = false;
        log_("Sharpshooter: no Disadvantage at long range");
    }

    // Apply engagement disadvantage: ranged attacks suffer disadvantage if engaged
    bool is_ranged = (w.type == WeaponType::Ranged);
    if (is_ranged && isThreatened(bm, action.attacker_idx)) {
        // Firing in Melee — Sharpshooter (any ranged weapon) and Crossbow Expert (Crossbows
        // only) negate the within-5-ft Disadvantage from a nearby enemy.
        const Agent::Stats& fs = atk_pt.agent->getStats();
        bool firing_in_melee_ok =
            fs.hasFeat("Sharpshooter") ||
            (fs.hasFeat("Crossbow Expert") && w.name.find("Crossbow") != std::string::npos);
        if (firing_in_melee_ok)
            log_("{}: no Disadvantage firing in melee (feat)",
                 agentName(bm, action.attacker_idx));
        else
            disadv = true;
    }

    // Check agent conditions for advantage/disadvantage
    bool adv = atk_pt.agent->hasAdvantage();
    bool dis = disadv || atk_pt.agent->hasDisadvantage();

    // Attacker conditions
    const Agent::Conditions& atk_cond = atk_pt.agent->getConditions();

    // Barbarian Reckless Attack: give attacker advantage on STR-based melee attacks
    if (atk_cond.reckless_attack && w.type != WeaponType::Ranged &&
        (w.type == WeaponType::Melee || w.thrown)) {
        adv = true;
    }

    // Attacker blinded: attacks have disadvantage
    if (atk_cond.blinded) {
        dis = true;
        log_("Disadvantage: attacker is blinded");
    }

    // Attacker poisoned: attacks have disadvantage
    if (atk_cond.poisoned) {
        dis = true;
        log_("Disadvantage: attacker is poisoned");
    }

    // Speedy (general feat) — Opportunity Attacks made against you are made with Disadvantage.
    // The OA path flags the attack via Attack::opportunity.
    if (action.opportunity && tgt_pt.agent->getStats().hasFeat("Speedy")) {
        dis = true;
        log_("Disadvantage: {} has Speedy (Opportunity Attack against them)",
             agentName(bm, action.target_idx));
    }

    // Slasher (general feat) — Enhanced Critical: a creature crit by Slashing has Disadvantage on
    // its own attack rolls until the feat-user's next turn (mark cleared in beginTurn).
    if (atk_cond.slasher_marked) {
        dis = true;
        log_("Disadvantage: attacker was crit by Slasher");
    }

    // Attacker frightened: disadvantage on attacks when fear source is in LOS
    if (atk_cond.frightened) {
        for (const auto& ac : activeAgentConditions_) {
            if (ac.agent_idx == action.attacker_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
                if (bm.hasLineOfSight(atk_pt.origin, atk_sz, bm.placedAgents()[ac.caster_idx].origin, 1)) {
                    dis = true;
                    log_("Disadvantage: attacker is frightened and fear source is in LOS");
                }
                break;
            }
        }
    }

    // Attacker grappled: disadvantage on attacks except against the grappler
    if (atk_cond.grappled) {
        if (action.target_idx != atk_cond.grappler_idx) {
            dis = true;
            log_("Disadvantage: attacker is grappled");
        }
    }

    // Attacker is hidden: attacks have advantage (will be revealed after attack)
    bool attacker_was_hidden = atk_cond.hidden;
    if (attacker_was_hidden) {
        adv = true;
        log_("Advantage: attacker is hidden");
    }

    // Attacker is invisible: attacks have advantage (Invisibility ends after attacking) —
    // UNLESS the target can still perceive the attacker (Truesight/Blindsight in range, or
    // the Blind Fighting style's Blindsight 10 ft). canPerceiveTarget(viewer, perceived).
    if (atk_cond.invisible &&
        !canPerceiveTarget(bm, action.target_idx, action.attacker_idx)) {
        adv = true;
        log_("Advantage: attacker is invisible");
    }

    // Rogue Steady Aim: the bonus action grants advantage on this attack (consumed below).
    if (atk_cond.steady_aim) {
        adv = true;
        log_("Advantage: Steady Aim");
    }

    // Wild Heart Wolf Form: allies within 5ft of the Barbarian get advantage on attacks
    // Check if there's a Wolf-form Wild Heart Barbarian within 5ft of the attacker
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == action.attacker_idx) continue;  // Skip self
        const PlacedAgent& ally_pa = agents[static_cast<std::size_t>(i)];
        const Agent::Stats& ally_stats = ally_pa.agent->getStats();
        const Agent::Conditions& ally_cond = ally_pa.agent->getConditions();

        // Check if ally is a Wolf-form Wild Heart Barbarian in Rage
        if (ally_stats.barbarian_subclass == WildHeartPath &&
            ally_stats.wild_heart_rage_choice == WolfForm &&
            ally_cond.raging) {
            // Check distance: within 5ft (1 cell on 5ft/cell grid = Chebyshev distance <= 1)
            int dc = std::max({atk_pt.origin.col - ally_pa.origin.col,
                               ally_pa.origin.col - (atk_pt.origin.col + atk_sz - 1),
                               0});
            int dr = std::max({atk_pt.origin.row - ally_pa.origin.row,
                               ally_pa.origin.row - (atk_pt.origin.row + atk_sz - 1),
                               0});
            int dist = std::max(dc, dr);

            if (dist <= 1) {
                adv = true;
                log_("Advantage: Wild Heart Wolf Form ally within 5 feet");
                break;
            }
        }
    }

    // Target is paralyzed: attacker gets advantage
    const Agent::Conditions& tgt_cond = tgt_pt.agent->getConditions();
    // Snapshot incapacitation BEFORE this attack's own effects can change it. tgt_cond is a
    // live reference, so a rider applied mid-resolution (e.g. Cunning Strike Knock Out) would
    // otherwise leak into the post-resolution blocks below (auto-crit-on-unconscious and
    // auto-wake) and act on the very hit that caused the condition.
    const bool tgt_unconscious_at_attack   = tgt_cond.unconscious;
    const bool tgt_incapacitated_at_attack = tgt_cond.paralyzed || tgt_unconscious_at_attack;
    if (tgt_cond.paralyzed) {
        adv = true;
        log_("Advantage: target is paralyzed");
    }

    // Target is blinded: attacker gets advantage
    if (tgt_cond.blinded) {
        adv = true;
        log_("Advantage: target is blinded");
    }

    // Target is stunned: attacker gets advantage
    if (tgt_cond.stunned) {
        adv = true;
        log_("Advantage: target is stunned");
    }

    // Target is unconscious: attacker gets advantage
    if (tgt_cond.unconscious) {
        adv = true;
        log_("Advantage: target is unconscious");
    }

    // Target has Reckless Attack active (Barbarian): attacker gets advantage
    if (tgt_cond.reckless_attack) {
        adv = true;
        log_("Advantage: target has Reckless Attack active");
    }

    // Crusher (general feat) — Enhanced Critical: attack rolls against a creature crit by
    // Bludgeoning have Advantage until the feat-user's next turn (mark cleared in beginTurn).
    if (tgt_cond.crusher_marked) {
        adv = true;
        log_("Advantage: target was crit by Crusher");
    }

    // Grappler feat — Advantage on attack rolls against a creature you are grappling.
    if (tgt_cond.grappled && tgt_cond.grappler_idx == action.attacker_idx &&
        atk_pt.agent->getStats().hasFeat("Grappler")) {
        adv = true;
        log_("Advantage: Grappler attacking a creature it has grappled");
    }

    // Target is prone: advantage for melee attacks within 5 feet, disadvantage for ranged
    if (tgt_cond.prone) {
        int dc = std::max({atk_pt.origin.col - tgt_pt.origin.col,
                           tgt_pt.origin.col - (atk_pt.origin.col + atk_sz - 1),
                           0});
        int dr = std::max({atk_pt.origin.row - tgt_pt.origin.row,
                           tgt_pt.origin.row - (atk_pt.origin.row + atk_sz - 1),
                           0});
        int dist = std::max(dc, dr);

        // Within 5 feet (1 cell on 5ft/cell grid): attacker gets advantage (melee)
        if (dist <= 1) {
            adv = true;
            log_("Advantage: target is prone and within 5 feet");
        } else if (is_ranged) {
            // Beyond 5 feet with ranged attack: attacker gets disadvantage
            dis = true;
            log_("Disadvantage: target is prone and attacker is beyond 5 feet");
        }
    }

    // Log reasons for disadvantage
    if (is_ranged && isThreatened(bm, action.attacker_idx))
        log_("Disadvantage: threatened (enemy within 10 ft)");
    else if (disadv)  // long-range disadvantage
        log_("Disadvantage: long range");
    if (atk_pt.agent->hasDisadvantage())
        log_("Disadvantage: condition");
    if (atk_pt.agent->hasAdvantage())
        log_("Advantage: condition");

    // ── Weapon Mastery: Vex (advantage) / Sap (disadvantage) carried from a prior hit ──
    // These were set on a previous attack and are consumed here (cleared after the roll
    // via updated_atk_cond), independent of the weapon used for this attack.
    bool consume_vex = false, consume_sap = false;
    if (atk_cond.vex_target_idx == action.target_idx) {
        adv = true; consume_vex = true;
        log_("Advantage: Vex (your last hit on this target)");
    }
    if (atk_cond.sapped) {
        dis = true; consume_sap = true;
        log_("Disadvantage: attacker was Sapped");
    }


    // end of determination of advantage / disadvantage


    
    Agent::Stats atk_stats = bm.getAgentStats(action.attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(action.target_idx);
    log_("[ATTACK START] {} - unconscious={}, hp={}", agentName(bm, action.target_idx), tgt_cond.unconscious, tgt_stats.hp_cur);


    
    // Check Brutal Strike eligibility (L9+: Reckless Attack + melee weapon, once per turn)
    bool can_use_brutal_strike = false;
    if (atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.char_level >= 9 &&
        atk_cond.reckless_attack &&
        !atk_cond.brutal_strike_used_this_turn &&
        (w.type == WeaponType::Melee || w.thrown)) {
        can_use_brutal_strike = true;
        log_("Brutal Strike eligible: L9+ Barbarian with Reckless Attack + melee weapon");
    }

    // Rogue Elusive (L18+): no attack roll can have advantage against you unless Incapacitated.
    if (adv && tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 18 &&
        !tgt_cond.incapacitated) {
        adv = false;
        log_("Elusive: target is a L18+ Rogue — advantage negated");
    }


    // Phase A done — carry the pre-roll state across the (possible) defender reaction window. The
    // caller rolls the attack (resolveAttack) and may open the Shield window before applyAttackResult.
    s.w = w; s.adv = adv; s.dis = dis;
    s.can_use_brutal_strike       = can_use_brutal_strike;
    s.tgt_incapacitated_at_attack = tgt_incapacitated_at_attack;
    s.tgt_unconscious_at_attack   = tgt_unconscious_at_attack;
    s.consume_vex = consume_vex; s.consume_sap = consume_sap;
    s.attacker_was_hidden = attacker_was_hidden;
    s.atk_sz = atk_sz; s.tgt_sz = tgt_sz;
    return true;
}

// Atomic attack entry used by internal callers (OA, multiattack, riposte) and the auto/RL path:
// validate + advantage (determineAdvantage) → roll (resolveAttack) → inline defender Shield window →
// apply (applyAttackResult). The GUI suspends at the Shield window via beginAttack (step 3b) instead.
AttackResult CombatEngine::executeAction(BattleMap& bm, const Attack& action)
{
    InFlightAttack s;
    s.action = action;
    if (!determineAdvantage(bm, s)) return s.r;          // illegal/blocked attack (valid == false)
    auto agents = bm.placedAgents();
    const PlacedAgent& atk_pt = agents[static_cast<std::size_t>(action.attacker_idx)];
    const PlacedAgent& tgt_pt = agents[static_cast<std::size_t>(action.target_idx)];
    s.r = resolveAttack(s.w, *atk_pt.agent, *tgt_pt.agent, s.adv, s.dis, action.no_ability_damage);
    // Auto/RL OnD20Seen window (inline): nearby creatures may LOWER the roll (Bend Luck / Cutting
    // Words / Silvery Barbs) before it commits — runs BEFORE Shield so a lowered-to-miss attack opens
    // no Shield window (shouldOfferDefenderShield is gated on r.hit).
    maybeD20SeenInline(bm, action, s.r);
    // Auto/RL defender OnHit window (inline via the decider): Shield (negate) or Uncanny Dodge (halve).
    // applyAttackResult re-fetches the target's stats, so a Shield slot-spend/AC or the halved damage are
    // reflected (no stale-snapshot clobber).
    maybeDefenderOnHitInline(bm, action, s.r);
    AttackResult r = applyAttackResult(bm, s);
    // Auto/RL Interception (OnAllyAttacked): a nearby ally with the Interception fighting style may
    // spend its reaction to reduce the damage this hit dealt (post-hit heal-back). On-hit only.
    maybeInterceptionInline(bm, action, r);
    // Auto/RL War Domain Guided Strike (OnMiss): a War Cleric may add +10 to turn the miss into a hit.
    // Runs BEFORE Riposte so a guided hit forecloses the defender's miss-reaction.
    maybeGuidedStrikeInline(bm, action, r);
    // Auto/RL Battle Master Riposte (OnMiss defender reaction). Runs AFTER the attack fully resolves,
    // so the riposte is a fresh top-level attack (no nesting). The reaction economy caps the chain:
    // a riposte-of-a-riposte is possible once each (both reactors spend their one reaction), then stops.
    maybeRiposteInline(bm, action, r);
    // Auto/RL Sentinel Guardian (OnAllyAttacked): a Sentinel adjacent to the attacker may counter-attack
    // it after it struck an ally. Runs last — it's a bystander's reaction and never alters this attack.
    maybeSentinelGuardInline(bm, action, r);
    return r;
}

// ── applyAttackResult: phase B — apply the rolled attack's consequences (on-hit/on-miss rider
// eligibility, damage, concentration, conditions, downstate). Split from executeAction so a defender
// reaction (Shield) can fire between the roll and damage. Working
// stats/conditions are re-fetched fresh here, so a Shield cast in the window is reflected. ──────────
AttackResult CombatEngine::applyAttackResult(BattleMap& bm, InFlightAttack& s)
{
    const Attack& action = s.action;
    auto agents = bm.placedAgents();
    const PlacedAgent& atk_pt = agents[static_cast<std::size_t>(action.attacker_idx)];
    const PlacedAgent& tgt_pt = agents[static_cast<std::size_t>(action.target_idx)];
    Weapon w = s.w;
    AttackResult r = s.r;
    bool adv = s.adv, dis = s.dis;
    bool can_use_brutal_strike = s.can_use_brutal_strike;
    const bool tgt_incapacitated_at_attack = s.tgt_incapacitated_at_attack;
    const bool tgt_unconscious_at_attack   = s.tgt_unconscious_at_attack;
    bool consume_vex = s.consume_vex, consume_sap = s.consume_sap;
    bool attacker_was_hidden = s.attacker_was_hidden;
    int atk_sz = s.atk_sz, tgt_sz = s.tgt_sz;
    Agent::Stats atk_stats = bm.getAgentStats(action.attacker_idx);
    Agent::Stats tgt_stats = bm.getAgentStats(action.target_idx);
    const Agent::Conditions& atk_cond = atk_pt.agent->getConditions();
    const Agent::Conditions& tgt_cond = tgt_pt.agent->getConditions();

    // Set Brutal Strike flag if eligible and attack hits
    Agent::Conditions updated_atk_cond = atk_cond;
    if (r.hit && can_use_brutal_strike) {
        updated_atk_cond.brutal_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }
    // Reckless Attack (Barbarian L2+): a missed melee/thrown attack MAY be re-rolled recklessly.
    // It's a CHOICE — accepting grants enemies advantage vs you until your next turn — offered two
    // ways: the auto/RL driver consults the decider inline here (and re-resolves with advantage);
    // the GUI (no decider) instead sets a deferred flag and prompts, then calls applyRecklessReroll.
    // (Pre-declaring Reckless before the attack is the other entry point — handled by the
    // reckless_attack advantage at the top of resolveAttack.)
    // NOTE: the *attacker* can still change this attack's state here even after the defender's
    // window — a Reckless reroll re-resolves the attack (mutating `r` and setting reckless_attack).
    // This is intentional: a Shield-negated hit is a genuine miss the attacker may reroll (DM ruling).
    else if (!r.hit &&
             atk_stats.character_class == CharacterClass::Barbarian &&
             atk_stats.char_level >= 2 &&
             !atk_cond.reckless_attack &&
             (w.type == WeaponType::Melee || w.thrown)) {
        if (decider_ && decider_->chooseReckless(RecklessCtx{action.attacker_idx})) {
            updated_atk_cond.reckless_attack = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
            adv = true;
            r = resolveAttack(w, *atk_pt.agent, *tgt_pt.agent, adv, dis, action.no_ability_damage);
            log_("{} attacks recklessly (reroll with advantage; attacks against them gain advantage)",
                 agentName(bm, action.attacker_idx));
        } else if (!decider_) {
            // Interactive (GUI): defer — flag it; the GUI prompts and calls apply_reckless_reroll.
            updated_atk_cond.reckless_reroll_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // Consume Rogue Steady Aim: it grants advantage on a single attack this turn.
    if (atk_cond.steady_aim) {
        updated_atk_cond.steady_aim = false;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Rogue Sneak Attack / Cunning Strike eligibility ───────────────────
    // Once per turn, a hit with a Finesse or Ranged weapon while having advantage qualifies for
    // Sneak Attack. Like Brutal Strike, the dice and any Cunning Strike rider are applied out of
    // band via applyCunningStrikeEffect() AFTER this attack fully resolves — so a rider that sets a
    // condition (e.g. Knock Out) can never leak into this attack's own post-resolution logic. Here
    // we only flag availability. (The "ally within 5 ft" trigger is deferred — needs a faction system.)
    if (r.hit && atk_stats.character_class == CharacterClass::Rogue &&
        (w.finesse || w.type == WeaponType::Ranged) &&
        adv && !dis && !atk_cond.sneak_attack_used) {
        updated_atk_cond.cunning_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Monk Stunning Strike eligibility ────────────────────────────────────
    // Monks can, once per turn, spend 1 Focus Point to force a CON save (Stunned on fail)
    // The save is applied out of band via applyStunningStrikeEffect.
    if (r.hit && atk_stats.character_class == CharacterClass::Monk &&
        (w.name == "MonkUnarmed" || w.name == "Unarmed") &&
        !atk_cond.stunning_strike_used) {
        updated_atk_cond.stunning_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Monk Warrior of the Open Hand rider eligibility ──────────────────────
    // Monks with Warrior of the Open Hand subclass can apply one of three riders to a
    // bonus-action Flurry of Blows hit (only on bonus-action attacks, not action attacks).
    // Riders: Knockdown (STR save or Prone), Push (5 ft), or Deny Reaction (1 FP each).
    if (r.hit && atk_stats.character_class == CharacterClass::Monk &&
        atk_stats.monk_subclass == WarriorOfTheOpenHandPath &&
        (w.name == "MonkUnarmed" || w.name == "Unarmed") &&
        action.attack_slot == "bonus") {
        updated_atk_cond.open_hand_rider_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Battle Master Maneuver eligibility (on-hit) ───────────────────────────
    // On any hit, a Battle Master with Superiority Dice remaining can spend one die
    // for a Maneuver rider (Trip/Menacing/Pushing). Flagged here; applied out-of-band.
    if (r.hit && atk_stats.character_class == CharacterClass::Fighter &&
        atk_stats.fighter_subclass == BattleMasterPath) {
        const Resource* sd = atk_stats.getResource("Superiority Dice");
        if (sd && sd->current > 0) {
            updated_atk_cond.maneuver_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Battle Master Precision Attack eligibility (on-miss) ─────────────────
    // On a non-fumble miss, a Battle Master with Superiority Dice can spend one die
    // to add 1d8/d10 to the roll and potentially convert the miss to a hit.
    if (!r.hit && !r.fumble && atk_stats.character_class == CharacterClass::Fighter &&
        atk_stats.fighter_subclass == BattleMasterPath) {
        const Resource* sd = atk_stats.getResource("Superiority Dice");
        if (sd && sd->current > 0) {
            updated_atk_cond.maneuver_precision_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Battle Master Riposte eligibility (on-miss, DEFENDER reaction) ────────
    // When a MELEE attack misses, a Battle Master TARGET with a Superiority Die and its reaction free
    // may spend the die + reaction to make a melee attack back. Flagged on the TARGET (the reactor),
    // not the attacker. The GUI prompts (deferred-flag path); the auto/RL inline window is
    // maybeRiposteInline, called from executeAction after this returns. canRiposte is the single
    // eligibility gate (BattleMaster + die + reaction + alive + melee weapon + attacker in reach).
    if (!r.hit && w.type == WeaponType::Melee && canRiposte(bm, action.target_idx, action.attacker_idx)) {
        Agent::Conditions tdef = bm.getAgentConditions(action.target_idx);
        tdef.riposte_available = true;
        bm.setAgentConditions(action.target_idx, tdef);
    }

    // ── Cleric Blessed Strikes — Divine Strike eligibility ────────────────
    // L7+ Clerics who chose Divine Strike can, once per turn, add Necrotic/Radiant to a weapon
    // hit. Like Brutal/Cunning Strike, the extra die is applied out of band (applyDivineStrikeEffect).
    if (r.hit && atk_stats.character_class == CharacterClass::Cleric &&
        atk_stats.char_level >= 7 &&
        atk_stats.blessed_strike == BlessedStrikeDivineStrike &&
        !atk_cond.divine_strike_used) {
        updated_atk_cond.divine_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Psi Warrior Psionic Strike eligibility (on-hit) ───────────────────
    // L3+ Psi Warriors can, once per turn, spend one Psionic Energy die to add Force damage to a
    // hit (die roll + INT mod). Applied out of band via applyPsionicStrikeEffect.
    if (r.hit && atk_stats.character_class == CharacterClass::Fighter &&
        atk_stats.fighter_subclass == PsiWarriorPath && atk_stats.char_level >= 3 &&
        !atk_cond.psionic_strike_used) {
        const Resource* ped = atk_stats.getResource("Psionic Energy");
        if (ped && ped->current > 0) {
            updated_atk_cond.psionic_strike_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Grappler feat — Punch-and-Grab eligibility (on an Unarmed-Strike hit) ─
    // After hitting with an Unarmed Strike as part of the Attack action (not a bonus-action strike), a
    // Grappler may ALSO attempt a Grapple this attack (normally one or the other), once per turn. Flagged
    // for the GUI (which offers it and calls applyPunchAndGrab → resolveGrapple); the grapple itself runs
    // through the shared resolveGrapple core. attack_slot is set by Python ("action"/"bonus"); an empty
    // slot (internal callers / tests) is treated as the Attack action.
    if (r.hit && atk_stats.hasFeat("Grappler") &&
        (w.name == "Unarmed" || w.name == "MonkUnarmed") &&
        action.attack_slot != "bonus" && !atk_cond.grappler_punch_grab_used) {
        updated_atk_cond.grappler_punch_grab_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Paladin Divine Smite eligibility (on a melee/unarmed hit) ─────────
    // After hitting with a melee weapon or Unarmed Strike, a Paladin may spend a spell slot as
    // a Bonus Action to add Radiant damage (applied out of band via applyDivineSmiteEffect; the
    // GUI offers a slot-level choice). Gated on: a free bonus action, no leveled spell already
    // cast this turn (the bonus-action-spell interlock), not already smited this turn, and at
    // least one spell slot available. (A L1 Paladin has no slots, so the slot check gates it.)
    if (r.hit && atk_stats.character_class == CharacterClass::Paladin &&
        (w.type == WeaponType::Melee || w.name == "Unarmed" || w.name == "MonkUnarmed") &&
        !atk_cond.divine_smite_used && !atk_stats.leveled_spell_cast_this_turn &&
        hasBonusAction(bm, action.attacker_idx)) {
        bool has_slot = false;
        for (int lvl = 1; lvl <= 9 && !has_slot; ++lvl)
            if (atk_stats.spell_slots_remaining[static_cast<std::size_t>(lvl - 1)] > 0)
                has_slot = true;
        if (has_slot) {
            updated_atk_cond.divine_smite_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Warlock Eldritch Smite eligibility (on a pact-weapon hit) ─────────
    // L5+ Warlock with Pact of the Blade (13) + Eldritch Smite (15) may, once per turn, expend a
    // Pact Magic spell slot as a Bonus Action to add (slot+1)d8 Force + knock Prone. Like Divine
    // Smite: gated on a free bonus action, a pact slot, and no leveled spell already this turn.
    // Applied out of band via applyEldritchSmiteEffect (GUI offer / auto path).
    if (r.hit && atk_stats.character_class == CharacterClass::Warlock &&
        atk_stats.char_level >= 5 && w.pact_weapon &&
        atk_stats.hasInvocation(13) && atk_stats.hasInvocation(15) &&
        !atk_cond.eldritch_smite_used && !atk_stats.leveled_spell_cast_this_turn &&
        hasBonusAction(bm, action.attacker_idx)) {
        const int psl = atk_stats.pact_slot_level();
        if (psl >= 1 && atk_stats.spell_slots_remaining[static_cast<std::size_t>(psl - 1)] > 0) {
            updated_atk_cond.eldritch_smite_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Eldritch Knight — Eldritch Strike (on a weapon hit) ───────────────
    // L10+ EK: hitting a creature with a weapon gives it disadvantage on its next saving throw
    // against a spell the EK casts. Tag the target with the EK's index; the save site (executeSpell)
    // consumes it. RAW window ("before the end of your next turn") is simplified to one-shot.
    if (r.hit && atk_stats.character_class == CharacterClass::Fighter &&
        atk_stats.fighter_subclass == EldritchKnightPath && atk_stats.char_level >= 10) {
        Agent::Conditions tcond = bm.getAgentConditions(action.target_idx);
        tcond.eldritch_strike_by = action.attacker_idx;
        bm.setAgentConditions(action.target_idx, tcond);
    }

    // ── War Domain — Guided Strike eligibility (on a miss) ────────────────
    // A missed attack (not a natural 1) can be nudged to a hit by a War Cleric L3+ spending Channel
    // Divinity — the attacker themselves, or an ally within 30 ft (who pays a Reaction). Flag it for the
    // GUI (which offers the choice and calls applyGuidedStrike); the auto/RL path uses the OnMiss window
    // (maybeGuidedStrikeInline) with the same canGuidedStrike gate.
    if (!r.hit && !r.fumble) {
        for (int c = 0; c < static_cast<int>(agents.size()); ++c) {
            if (canGuidedStrike(bm, action, c)) {
                updated_atk_cond.guided_strike_available = true;
                bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
                break;
            }
        }
    }

    // ── Sentinel feat — Guardian eligibility (OnAllyAttacked) ─────────────
    // After ANY attack (hit or miss) against a creature other than themselves, a Sentinel adjacent to
    // the attacker may spend their reaction to make a melee attack back. Flagged on the ATTACKER for the
    // GUI (which scans for the eligible Sentinel and calls applySentinelGuard); the auto/RL path uses
    // the OnAllyAttacked window (maybeSentinelGuardInline) with the same canSentinelGuard gate. Skipped
    // while a guard counter-attack is itself resolving (a guard does not provoke its own guard).
    if (!resolving_sentinel_guard_) {
        for (int g = 0; g < static_cast<int>(agents.size()); ++g) {
            if (canSentinelGuard(bm, action, g)) {
                updated_atk_cond.sentinel_guard_available = true;
                bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
                break;
            }
        }
    }

    // (Rogue Uncanny Dodge — the target's damage-halving reaction — now fires in the OnHit defender
    // window before this finalize: applyUncannyDodge via maybeDefenderOnHitInline (auto/RL) or the
    // advanceAttack suspend (GUI), so r.total_damage already reflects it here.)

    // Savage Attacker (Origin feat): once per turn, reroll the weapon's damage dice and
    // keep the better roll. resolveAttack already rolled damage once (recorded as the
    // "weapon" entry in r.damage_breakdown); we reroll a fresh weapon-damage total and, if
    // higher, fold the delta into r.total_damage. Flat riders (Rage, etc.) are added equally
    // to both rolls, so comparing only the weapon portion picks the correct better roll.
    if (r.hit && atk_stats.hasFeat("Savage Attacker") &&
        !atk_cond.savage_attacker_used_this_turn) {
        int orig_weapon = 0;
        for (const auto& kv : r.damage_breakdown)
            if (kv.first == "weapon") { orig_weapon = kv.second; break; }
        AttackResult alt;
        alt.critical = r.critical;   // preserve crit (doubles the dice in rollDamage)
        rollDamage(w, atk_stats, tgt_stats, alt, action.no_ability_damage);
        if (alt.total_damage > orig_weapon) {
            r.total_damage += (alt.total_damage - orig_weapon);
            for (auto& kv : r.damage_breakdown)
                if (kv.first == "weapon") { kv.second = alt.total_damage; break; }
            r.dice_results = alt.dice_results;
            log_("{}: Savage Attacker rerolls damage ({} → {})",
                 agentName(bm, action.attacker_idx), orig_weapon, alt.total_damage);
        } else {
            log_("{}: Savage Attacker reroll not better ({} vs {}) — keeps original",
                 agentName(bm, action.attacker_idx), alt.total_damage, orig_weapon);
        }
        updated_atk_cond.savage_attacker_used_this_turn = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── General feats — damage-affecting on-hit riders (folded into r.total_damage
    //    before the single base-damage application below). ────────────────────────
    {
        auto deals_phys = [&](PhysicalDamage_t t) {
            return std::find(r.physical_damage_types.begin(), r.physical_damage_types.end(), t)
                   != r.physical_damage_types.end();
        };
        auto weapon_phys_die = [&](PhysicalDamage_t t) -> int {
            for (const auto& pr : w.physicalDamageRolls) if (pr.type == t) return pr.die_size;
            return 0;
        };
        auto bump_weapon_breakdown = [&](int delta) {
            for (auto& kv : r.damage_breakdown)
                if (kv.first == "weapon") { kv.second = std::max(0, kv.second + delta); return; }
        };

        // Great Weapon Master — Heavy Weapon Mastery: a hit with a Heavy melee weapon as part of
        // the Attack action deals +PB extra damage (every qualifying hit, not once/turn).
        if (r.hit && atk_stats.hasFeat("Great Weapon Master") && w.heavy &&
            (w.type == WeaponType::Melee || w.thrown) && action.attack_slot != "bonus") {
            int pb = atk_stats.prof_bonus;
            r.total_damage += pb;
            r.damage_breakdown.push_back({"GWM", pb});
            log_("{}: Great Weapon Master adds +{} damage (Heavy weapon)",
                 agentName(bm, action.attacker_idx), pb);
        }

        // Dueling fighting style: +2 damage when wielding a one-handed melee weapon and no
        // other weapon. A Shield does not count; empty slots (no damage dice) don't count.
        if (r.hit && atk_stats.hasFeat("Dueling") &&
            w.type == WeaponType::Melee && !w.two_handed) {
            bool another_weapon = false;
            for (int i = 0; i < static_cast<int>(atk_pt.weapons.size()); ++i) {
                if (i == action.weapon_idx) continue;
                const Weapon& other = atk_pt.weapons[static_cast<std::size_t>(i)];
                if (other.is_shield || other.name.find("Shield") != std::string::npos) continue;
                if (!other.physicalDamageRolls.empty() || !other.magicDamageRolls.empty()) {
                    another_weapon = true;
                    break;
                }
            }
            if (!another_weapon) {
                r.total_damage += 2;
                r.damage_breakdown.push_back({"Dueling", 2});
                log_("{}: Dueling adds +2 damage", agentName(bm, action.attacker_idx));
            }
        }

        // Thrown Weapon Fighting style: +2 damage on a hit with a thrown weapon.
        if (r.hit && atk_stats.hasFeat("Thrown Weapon Fighting") && w.thrown) {
            r.total_damage += 2;
            r.damage_breakdown.push_back({"Thrown Weapon Fighting", 2});
            log_("{}: Thrown Weapon Fighting adds +2 damage",
                 agentName(bm, action.attacker_idx));
        }

        // Piercer — Puncture: once per turn, reroll one of the attack's damage dice and use the
        // new roll. A rational user rerolls the lowest die, so we reroll min(dice) using the
        // weapon's Piercing die size (target's Piercing multiplier applied to the delta).
        if (r.hit && atk_stats.hasFeat("Piercer") && !atk_cond.piercer_reroll_used_this_turn &&
            deals_phys(Piercing) && !r.dice_results.empty()) {
            int die = weapon_phys_die(Piercing);
            if (die > 0) {
                auto it = std::min_element(r.dice_results.begin(), r.dice_results.end());
                int oldv = *it, newv = roll(die);
                float mult = tgt_stats.physical_damage_multipliers[Piercing];
                int delta = static_cast<int>(static_cast<float>(newv - oldv) * mult);
                *it = newv;
                r.total_damage = std::max(0, r.total_damage + delta);
                bump_weapon_breakdown(delta);
                updated_atk_cond.piercer_reroll_used_this_turn = true;
                bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
                log_("{}: Piercer rerolls a Piercing die ({} → {})",
                     agentName(bm, action.attacker_idx), oldv, newv);
            }
        }

        // Piercer — Enhanced Critical: on a Piercing critical hit, roll one extra Piercing die.
        if (r.hit && r.critical && atk_stats.hasFeat("Piercer") && deals_phys(Piercing)) {
            int die = weapon_phys_die(Piercing);
            if (die > 0) {
                float mult = tgt_stats.physical_damage_multipliers[Piercing];
                int extra = static_cast<int>(static_cast<float>(roll(die)) * mult);
                r.total_damage += extra;
                bump_weapon_breakdown(extra);
                log_("{}: Piercer crit adds an extra Piercing die ({})",
                     agentName(bm, action.attacker_idx), extra);
            }
        }
    }

    // Heavy Armor Master (general feat) — while wearing Heavy armor, Bludgeoning, Piercing, and
    // Slashing damage taken from an attack is reduced by the wearer's Proficiency Bonus. Heavy armor
    // is detected by an equipped piece with a 0 DEX cap (Plate / Chain Mail / Mithral Plate).
    // Approximation: the −PB is taken off r.total_damage when the attack dealt any B/P/S type; on a
    // mixed physical+magical hit this can trim the magical part too. Weapon-attack path only (spell
    // attacks that deal B/P/S are not covered — see known_limitations.md).
    if (r.hit && r.total_damage > 0 && tgt_stats.hasFeat("Heavy Armor Master") &&
        !r.physical_damage_types.empty()) {
        bool tgt_heavy_armor = false;
        for (const auto& piece : tgt_pt.armor)
            if (!piece.name.empty() && piece.dex_mod_cap == 0) { tgt_heavy_armor = true; break; }
        if (tgt_heavy_armor) {
            int pb = tgt_stats.prof_bonus;
            int reduced = std::min(pb, r.total_damage);
            r.total_damage -= reduced;
            log_("{}: Heavy Armor Master reduces damage by {} (B/P/S in Heavy armor)",
                 agentName(bm, action.target_idx), reduced);
        }
    }

    // Apply base attack damage to the target's working stats. resolveAttack now
    // computes damage but does not mutate HP, so the single source of truth is
    // applied here (and persisted once via setAgentStats below). Subsequent
    // class effects (Divine Fury) and the auto-crit path adjust tgt_stats further.
    const int temp_hp_before = tgt_stats.temp_hp;  // for auto-crit revert
    if (r.hit) {
        int overflow = std::max(0, r.total_damage - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - r.total_damage);
        tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after    = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);
    }

    // Tavern Brawler (Origin feat) — Push: on an Unarmed-Strike hit, shove the target 5 ft
    // straight away from you (once per turn). Reuses the forced-movement primitive shared
    // by Weapon Mastery Push and shove riders.
    if (r.hit && w.name == "Unarmed" && atk_stats.hasFeat("Tavern Brawler") &&
        !atk_cond.tavern_brawler_push_used_this_turn) {
        int cells = bm.forceMoveAgent(action.target_idx, atk_pt.origin, 5);
        if (cells > 0)
            log_("{}: Tavern Brawler pushes {} 5 ft", agentName(bm, action.attacker_idx),
                 agentName(bm, action.target_idx));
        updated_atk_cond.tavern_brawler_push_used_this_turn = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── General feats — non-damage on-hit riders (after damage is applied). ──────
    {
        auto deals_phys = [&](PhysicalDamage_t t) {
            return std::find(r.physical_damage_types.begin(), r.physical_damage_types.end(), t)
                   != r.physical_damage_types.end();
        };

        // Crusher — Push: once per turn, a Bludgeoning hit shoves the target 5 ft to an unoccupied
        // space if it is no more than one size larger than you. Enhanced Critical: a Bludgeoning
        // crit marks the target so attack rolls against it have Advantage until your next turn.
        if (r.hit && atk_stats.hasFeat("Crusher") && deals_phys(Bludgeoning)) {
            if (!atk_cond.crusher_push_used_this_turn && tgt_sz <= atk_sz + 1) {
                int cells = bm.forceMoveAgent(action.target_idx, atk_pt.origin, 5);
                if (cells > 0)
                    log_("{}: Crusher pushes {} 5 ft", agentName(bm, action.attacker_idx),
                         agentName(bm, action.target_idx));
                updated_atk_cond.crusher_push_used_this_turn = true;
                bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
            }
            if (r.critical) {
                Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                tc.crusher_marked = true;
                tc.crusher_marked_by = action.attacker_idx;
                bm.setAgentConditions(action.target_idx, tc);
                log_("{}: Crusher crit — attacks against {} have Advantage until {}'s next turn",
                     agentName(bm, action.attacker_idx), agentName(bm, action.target_idx),
                     agentName(bm, action.attacker_idx));
            }
        }

        // Slasher — Hamstring: once per turn, a Slashing hit reduces the target's Speed by 10 ft
        // until the start of your next turn (reuses the Weapon Mastery `slowed` flag). Enhanced
        // Critical: a Slashing crit marks the target so ITS attack rolls have Disadvantage until
        // your next turn.
        if (r.hit && atk_stats.hasFeat("Slasher") && deals_phys(Slashing)) {
            Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
            bool dirty = false;
            if (!atk_cond.slasher_slow_used_this_turn) {
                tc.slowed = true; dirty = true;
                updated_atk_cond.slasher_slow_used_this_turn = true;
                bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
                log_("{}: Slasher reduces {}'s Speed by 10 ft", agentName(bm, action.attacker_idx),
                     agentName(bm, action.target_idx));
            }
            if (r.critical) {
                tc.slasher_marked = true;
                tc.slasher_marked_by = action.attacker_idx;
                dirty = true;
                log_("{}: Slasher crit — {} has Disadvantage on attacks until {}'s next turn",
                     agentName(bm, action.attacker_idx), agentName(bm, action.target_idx),
                     agentName(bm, action.attacker_idx));
            }
            if (dirty) bm.setAgentConditions(action.target_idx, tc);
        }

        // Great Weapon Master — Hew: scoring a Critical Hit, or reducing a creature to 0 HP, with a
        // Heavy melee weapon as part of the Attack action arms a single bonus-action attack with that
        // weapon. The bonus-action economy naturally limits it to once per turn (the GUI offers it via
        // gwm_hew_available and routes it through the shared extra-attack flow).
        if (r.hit && atk_stats.hasFeat("Great Weapon Master") && w.heavy &&
            (w.type == WeaponType::Melee || w.thrown) && action.attack_slot != "bonus" &&
            (r.critical || r.target_down)) {
            updated_atk_cond.gwm_hew_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
            log_("{}: Great Weapon Master — Hew offers a bonus-action attack",
                 agentName(bm, action.attacker_idx));
        }
    }

    // Zealot Divine Fury: add extra 1d6 + floor(level/2) Necrotic damage on first hit when Raging
    if (r.hit && atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.barbarian_subclass == ZealotPath &&
        atk_cond.raging &&
        !atk_cond.zealot_divine_fury_used &&
        (w.type == WeaponType::Melee || w.thrown)) {

        // Roll 1d6 + floor(level/2)
        int divine_fury_bonus = roll(6) + (atk_stats.char_level / 2);

        r.total_damage += divine_fury_bonus;
        r.damage_breakdown.push_back({"divine fury", divine_fury_bonus});
        // Update target HP with the additional damage
        int overflow = std::max(0, divine_fury_bonus - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - divine_fury_bonus);
        tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);

        // Mark Divine Fury as used this turn
        updated_atk_cond.zealot_divine_fury_used = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);

        //log_("Zealot Divine Fury: added 1d6 + {} = {} damage", atk_stats.char_level / 2, divine_fury_bonus);
    }

    // Berserker Frenzy bonus: add extra Nd6, where N is the rage damage bonus
    if (r.hit && atk_stats.character_class == CharacterClass::Barbarian &&
        atk_stats.barbarian_subclass == BerserkerPath &&
        atk_cond.raging &&
        !atk_cond.berserker_frenzy_used &&
        (w.type == WeaponType::Melee || w.thrown)) {

        // Roll 1d6 + floor(level/2)
        int berserker_frenzy_bonus = 0;

	for ( int irage_bonus = 0; irage_bonus < getRageDamageBonus(atk_stats.char_level); ++irage_bonus ){
	  berserker_frenzy_bonus += roll(6);
	}

        r.total_damage += berserker_frenzy_bonus;
        r.damage_breakdown.push_back({"frenzy", berserker_frenzy_bonus});
        // Update target HP with the additional damage
        int overflow = std::max(0, berserker_frenzy_bonus - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - berserker_frenzy_bonus);
        tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);

        // Mark Divine Fury as used this turn
        updated_atk_cond.berserker_frenzy_used = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    // ── Warlock Lifedrinker (on a pact-weapon hit) — AUTOMATIC ────────────
    // L9+ Warlock with Pact of the Blade (13) + Lifedrinker (16): once per turn, a pact-weapon hit
    // deals extra Necrotic = max(1, CHA mod) and grants the Warlock that many temp HP. No player
    // choice (like Zealot Divine Fury above), so it covers every attack path. Must run AFTER the
    // base-damage application above (it adds to the already-decremented tgt_stats).
    if (r.hit && atk_stats.character_class == CharacterClass::Warlock &&
        atk_stats.char_level >= 9 && w.pact_weapon &&
        atk_stats.hasInvocation(13) && atk_stats.hasInvocation(16) &&
        !atk_cond.lifedrinker_used) {
        const int bonus = std::max(1, abilityMod(atk_stats.cha));
        const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Necrotic];
        const int ld_damage = static_cast<int>(static_cast<float>(bonus) * mult);

        r.total_damage += ld_damage;
        r.damage_breakdown.push_back({"lifedrinker", ld_damage});
        r.magic_damage_types.push_back(MagicDamage_t::Necrotic);
        int overflow = std::max(0, ld_damage - tgt_stats.temp_hp);
        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - ld_damage);
        tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
        r.hp_after = tgt_stats.hp_cur;
        r.target_down = (r.hp_after <= 0);

        // The Warlock drinks life: gains temp HP equal to the bonus. Persist atk_stats now — the
        // attacker's stats are otherwise only written in the Dark One's Blessing branch below (which
        // reuses this same local copy, so a later write stays consistent).
        grantTempHp(atk_stats, bonus, -1);
        bm.setAgentStats(action.attacker_idx, atk_stats);
        updated_atk_cond.lifedrinker_used = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        log_("{} drains life: +{} Necrotic, gains {} temp HP (Lifedrinker)",
             agentName(bm, action.attacker_idx), ld_damage, bonus);
    }

    // Automatic critical hit for melee attacks (within 5 ft) against paralyzed or unconscious targets.
    // Uses the pre-attack snapshot so a rider this attack applied (Cunning Strike Knock Out) does not
    // retroactively crit the triggering hit.
    if (tgt_incapacitated_at_attack && r.hit) {
        int dc = std::max({atk_pt.origin.col - tgt_pt.origin.col,
                           tgt_pt.origin.col - (atk_pt.origin.col + atk_sz - 1),
                           0});
        int dr = std::max({atk_pt.origin.row - tgt_pt.origin.row,
                           tgt_pt.origin.row - (atk_pt.origin.row + atk_sz - 1),
                           0});
        int dist = std::max(dc, dr);

        // Within 5 feet (1 cell on 5ft/cell grid)
        if (dist <= 1) {
            r.critical = true;
            std::string reason = tgt_cond.paralyzed ? "paralyzed" : "unconscious";
            log_("Automatic critical hit: target is {} and within 5 feet", reason);

            // If unconscious, auto-fail 2 death saves
            if (tgt_cond.unconscious) {
                Agent::Conditions updated_cond = bm.getAgentConditions(action.target_idx);
                updated_cond.death_save_failures += 2;
                if (updated_cond.death_save_failures >= 3) {
                    updated_cond.dead = true;
                    log_("Melee hit on unconscious: 2 death save failures — character dies");
                } else {
                    log_("Melee hit on unconscious: 2 death save failures ({}/3)", updated_cond.death_save_failures);
                }
                bm.setAgentConditions(action.target_idx, updated_cond);
            }

            // Re-roll damage with crit flag set (revert HP and temp HP to pre-attack)
            tgt_stats.hp_cur  = r.hp_before;
            tgt_stats.temp_hp = temp_hp_before;
            rollDamage(w, atk_stats, tgt_stats, r, action.no_ability_damage);
            int overflow = std::max(0, r.total_damage - tgt_stats.temp_hp);
            tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - r.total_damage);
            tgt_stats.hp_cur = std::clamp(tgt_stats.hp_cur - overflow,
                                            0, tgt_stats.hp_max);
            r.hp_after = tgt_stats.hp_cur;
            r.target_down = (r.hp_after <= 0);
        }
    }

    // ════ Weapon Mastery ════════════════════════════════════════════════════
    // Consume any Vex/Sap this attack used (set adv/dis above), then apply the
    // wielded weapon's mastery if the attacker has the Weapon Mastery feature.
    // Auto: Sap/Slow/Vex (on hit), Graze (on miss). Prompted (flag only — the GUI
    // offers the choice and calls the resolver): Push/Topple/Cleave.
    int graze_damage = 0;
    {
        bool dirty_atk = false;
        if (consume_vex) { updated_atk_cond.vex_target_idx = -1; dirty_atk = true; }
        if (consume_sap) { updated_atk_cond.sapped = false;       dirty_atk = true; }

        if (atk_stats.weapon_mastery > 0 && w.proficient &&
            w.mastery != WeaponMastery::None) {
            if (r.hit) {
                switch (w.mastery) {
                case WeaponMastery::Sap: {
                    if (!atk_cond.sap_used_this_turn) {
                        Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                        tc.sapped = true;
                        bm.setAgentConditions(action.target_idx, tc);
                        updated_atk_cond.sap_used_this_turn = true; dirty_atk = true;
                        log_("{} is Sapped (disadvantage on its next attack)",
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Slow: {
                    if (!atk_cond.slow_used_this_turn && r.total_damage > 0) {
                        Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                        tc.slowed = true;
                        bm.setAgentConditions(action.target_idx, tc);
                        updated_atk_cond.slow_used_this_turn = true; dirty_atk = true;
                        log_("{} is Slowed (Speed -10 ft until your next turn)",
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Vex: {
                    if (!atk_cond.vex_used_this_turn && r.total_damage > 0) {
                        updated_atk_cond.vex_target_idx = action.target_idx;
                        updated_atk_cond.vex_used_this_turn = true; dirty_atk = true;
                        log_("{} gains Vex (advantage on next attack vs {})",
                             agentName(bm, action.attacker_idx),
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Push: {
                    if (!atk_cond.push_used_this_turn && tgt_sz <= 2) {
                        updated_atk_cond.push_available = true;
                        updated_atk_cond.push_used_this_turn = true; dirty_atk = true;
                    }
                    break;
                }
                case WeaponMastery::Topple: {
                    if (!atk_cond.topple_used_this_turn) {
                        updated_atk_cond.topple_available = true; dirty_atk = true;
                    }
                    break;
                }
                case WeaponMastery::Poison: {
                    if (!atk_cond.poison_used_this_turn) {
                        Agent::Conditions tc = bm.getAgentConditions(action.target_idx);
                        tc.poisoned = true;
                        bm.setAgentConditions(action.target_idx, tc);
                        updated_atk_cond.poison_used_this_turn = true; dirty_atk = true;
                        log_("{} is Poisoned (disadvantage on attacks and ability checks)",
                             agentName(bm, action.target_idx));
                    }
                    break;
                }
                case WeaponMastery::Cleave: {
                    if (!atk_cond.cleave_used_this_turn) {
                        updated_atk_cond.cleave_available = true; dirty_atk = true;
                    }
                    break;
                }
                default: break;  // Graze handled on miss; Nick is an action-economy property
                }
            } else if (w.mastery == WeaponMastery::Graze) {
                // A miss (including a natural 1) still deals the attack ability modifier.
                int graze = std::max(0, damageAbilityMod(w, atk_stats));
                if (graze > 0) {
                    int overflow = std::max(0, graze - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - graze);
                    tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
                    r.hp_after    = tgt_stats.hp_cur;
                    r.target_down = (r.hp_after <= 0);
                    r.total_damage += graze;
                    r.damage_breakdown.push_back({"graze", graze});
                    graze_damage = graze;
                    log_("Graze: {} takes {} damage despite the miss",
                         agentName(bm, action.target_idx), graze);
                }
            }
        }
        if (dirty_atk) bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }

    bm.setAgentStats(action.target_idx, tgt_stats);  // apply HP change

    if (r.total_damage > 0 && (r.hit || graze_damage > 0)) {
        // Taking weapon damage forces a concentration save on the target (DC = max(10, dmg/2)).
        // Pass the attacker so a Mage Slayer imposes Disadvantage (Concentration Breaker).
        checkConcentrationOnDamage(bm, action.target_idx, r.total_damage, action.attacker_idx);
        // ...and ends/triggers on-damage conditions (Sleep, Hypnotic Pattern, Tasha's).
        processDamageTaken(bm, action.target_idx, r.total_damage);
    }

    // Auto-trigger Unconscious if HP drops to 0 or below
    bool just_knocked_unconscious = (r.hp_after <= 0 && !tgt_cond.unconscious && !tgt_cond.dead);
    if (just_knocked_unconscious) {
        log_("[ATTACK KNOCKDOWN] {} going unconscious from attack damage", agentName(bm, action.target_idx));
        applyUnconscious(bm, action.target_idx);
        r.target_down = true;
        // Don't roll death save yet - they'll roll on their next turn or if they take more damage

        // TASK A: Dark One's Blessing (Fiend L3): temp HP on kill
        if (atk_stats.character_class == CharacterClass::Warlock && atk_stats.warlock_subclass == FiendPath && atk_stats.char_level >= 3) {
            int chaMod = (atk_stats.cha - 10) / 2;
            if (atk_stats.cha < 10 && (atk_stats.cha - 10) % 2 != 0) --chaMod;
            int bonus = std::max(1, chaMod + atk_stats.char_level);
            grantTempHp(atk_stats, bonus);  // non-rage source: clears rage provenance if this grant wins
            bm.setAgentStats(action.attacker_idx, atk_stats);
            log_("{}: Dark One's Blessing grants {} temp HP", agentName(bm, action.attacker_idx), bonus);
        }
    }

    // Death save on damage for agents already unconscious (unless melee hit within 5ft, which auto-fails 2)
    // Only roll if the agent was ALREADY unconscious BEFORE this attack (not if just knocked unconscious)
    if (r.hp_after <= 0 && tgt_cond.unconscious && !tgt_cond.dead && r.total_damage > 0 && !just_knocked_unconscious) {
        log_("[DEATH SAVE ON DAMAGE] {} was already unconscious, rolling death save (was unconscious before: {})",
             agentName(bm, action.target_idx), tgt_cond.unconscious);
        // Check if this is a melee hit within 5ft (those already auto-failed 2 above)
        bool is_melee_within_5ft = false;
        if (r.critical && action.weapon_idx < static_cast<int>(atk_pt.weapons.size())) {
            const Weapon& wpn = atk_pt.weapons[static_cast<std::size_t>(action.weapon_idx)];
            if (wpn.type == WeaponType::Melee) {  // melee weapon
                Cell src = agents[action.attacker_idx].origin;
                Cell tgt = agents[action.target_idx].origin;
                int dist = std::max(std::abs(src.col - tgt.col), std::abs(src.row - tgt.row));
                if (dist <= 1) {
                    is_melee_within_5ft = true;
                }
            }
        }
        // Only roll regular death save if NOT a melee within 5ft (which auto-fails 2 instead)
        if (!is_melee_within_5ft) {
            rollDeathSave(bm, action.target_idx);
        }
    }

    // Auto-wake if healed above 0 HP while unconscious
    // But only if not actively dying (death save failures already set by damage/auto-crit).
    // Uses the pre-attack snapshot: a rider this attack applied (Cunning Strike Knock Out) must
    // not be undone by the same hit just because the target still has positive HP.
    if (r.hp_after > 0 && tgt_unconscious_at_attack && !tgt_cond.dead && tgt_cond.death_save_failures == 0) {
        Agent::Conditions updated_tgt_cond = tgt_cond;
        updated_tgt_cond.unconscious = false;
        updated_tgt_cond.incapacitated = false;
        updated_tgt_cond.prone = false;  // Waking up also clears prone
        updated_tgt_cond.death_save_successes = 0;
        updated_tgt_cond.death_save_failures = 0;
        updated_tgt_cond.stabilized = false;
        bm.setAgentConditions(action.target_idx, updated_tgt_cond);
        log_("Target healed above 0 HP and wakes up!");
    }

    // Apply weapon conditions on hit
    if (r.hit && !w.conditions.empty()) {
        auto ability_name = [](SaveAbility_t ab) -> std::string {
            switch (ab) {
                case SaveStr: return "STR";
                case SaveDex: return "DEX";
                case SaveCon: return "CON";
                case SaveInt: return "INT";
                case SaveWis: return "WIS";
                default: return "CHA";
            }
        };

        for (const auto& weapon_cond : w.conditions) {
            // Grappled routes through the shared Grapple Weapon Action core
            // (resolveGrapple → applyGrappled), reused by the standalone Grapple
            // action and the future Grappler feat — it sets the grappled flag +
            // escape DC, which the generic active-condition path does not. Range
            // is already satisfied (the attack hit), so no adjacency re-check.
            if (weapon_cond.condition_name == "Grappled") {
                (void)resolveGrapple(bm, action.attacker_idx, action.target_idx,
                                     weapon_cond.contested, weapon_cond.escape_dc);
                continue;
            }

            bool condition_applies = false;

            if (!weapon_cond.requires_save) {
                // Condition is automatic on hit
                condition_applies = true;
            } else {
                // Target makes a save to resist the condition
                int save_dc = spellSaveDcFromAbility(atk_stats, weapon_cond.save_dc_ability);

                auto getSaveMod = [&](SaveAbility_t ability) -> int {
                    int score = 0;
                    bool prof = false;
                    switch (ability) {
                        case SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                        case SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                        case SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                        case SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                        case SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                        default:             score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                    }
                    int m = (score - 10) / 2;
                    if (score < 10 && (score - 10) % 2 != 0) --m;
                    return m + (prof ? tgt_stats.prof_bonus : 0);
                };

                // Check for auto-fail conditions (paralyzed, stunned auto-fail STR/DEX)
                bool auto_fail = (tgt_cond.paralyzed || tgt_cond.stunned) &&
                                (weapon_cond.save_ability == SaveStr || weapon_cond.save_ability == SaveDex);

                int save_d20 = auto_fail ? 1 : roll(20);
                int save_mod = getSaveMod(weapon_cond.save_ability);
                bool saved = auto_fail ? false : (save_d20 + save_mod >= save_dc);

                condition_applies = !saved;

                if (!saved) {
                    log_("Target failed {} save vs weapon condition '{}' (save DC {})",
                         ability_name(weapon_cond.save_ability), weapon_cond.condition_name, save_dc);
                } else {
                    log_("Target resisted weapon condition '{}' (save DC {})",
                         weapon_cond.condition_name, save_dc);
                }
            }

            if (condition_applies) {
                // Apply condition
                int save_dc = spellSaveDcFromAbility(atk_stats, weapon_cond.save_dc_ability);
                ActiveAgentCondition cond;
                cond.agent_idx = action.target_idx;
                cond.caster_idx = action.attacker_idx;
                cond.spell_idx = -1;  // weapon attack, not a spell
                cond.condition_name = weapon_cond.condition_name;
                cond.save_ability = weapon_cond.save_ability;
                cond.turns_remaining = weapon_cond.condition_duration > 0 ? weapon_cond.condition_duration : 10;  // default 10 turns
                cond.save_dc = save_dc;
                cond.save_repeat_turns = weapon_cond.save_repeat_turns;
                cond.next_save_turn = 0;

                [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
                log_("Weapon condition '{}' applied to target", weapon_cond.condition_name);
            }
        }
    }

    // Apply weapon push on hit (push_ft > 0 and weapon is proficient)
    if (r.hit && w.proficient) {
        for (const auto& weapon_cond : w.conditions) {
            if (weapon_cond.condition_name == "Push" && weapon_cond.push_ft > 0) {
                if (action.attacker_idx >= 0 && action.attacker_idx < static_cast<int>(agents.size())) {
                    const auto& attacker = agents[action.attacker_idx];
                    int cells_moved = bm.forceMoveAgent(action.target_idx, attacker.origin, weapon_cond.push_ft);
                    r.push_ft_applied = cells_moved * 5;
                    if (cells_moved > 0) {
                        log_("Target pushed {} feet", r.push_ft_applied);
                    }
                }
                break;  // only one push condition per attack
            }
        }
    }

    // If attacker was hidden, reveal them (clear hidden condition)
    if (attacker_was_hidden && action.attacker_idx >= 0 && action.attacker_idx < static_cast<int>(agents.size())) {
        Agent::Conditions cond = bm.getAgentConditions(action.attacker_idx);
        cond.hidden = false;
        bm.setAgentConditions(action.attacker_idx, cond);
        log_("{} is no longer hidden", agents[action.attacker_idx].agent->name());
    }

    // Invisibility ends after the attacker makes an attack roll / deals damage (RAW),
    // unless it's Greater Invisibility (invisible_persists_on_action).
    if (action.attacker_idx >= 0 && action.attacker_idx < static_cast<int>(agents.size())) {
        Agent::Conditions cond = bm.getAgentConditions(action.attacker_idx);
        if (cond.invisible && !cond.invisible_persists_on_action) {
            cond.invisible = false;
            bm.setAgentConditions(action.attacker_idx, cond);
            log_("{}'s invisibility ends (made an attack)", agents[action.attacker_idx].agent->name());
        }
    }

    return r;
}

} // namespace rpg
