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

    // Roll physical damage types and apply target's multipliers
    for (const auto& dmg_roll : w.physicalDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            result.dice_results.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.physical_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.physical_damage_types.push_back(dmg_roll.type);
    }

    // Roll magic damage types and apply target's multipliers
    for (const auto& dmg_roll : w.magicDamageRolls) {
        const int num_dice = result.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
        int type_damage = 0;
        for (int i = 0; i < num_dice; ++i) {
            int d = roll(dmg_roll.die_size);
            result.dice_results.push_back(d);
            type_damage += d;
        }
        // Apply target's resistance/vulnerability/immunity multiplier
        float multiplier = target.magic_damage_multipliers[dmg_roll.type];
        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        raw += modified_damage;
        result.magic_damage_types.push_back(dmg_roll.type);
    }

    int ability_mod = damageAbilityMod(w, attacker);
    if (suppress_positive_mod && ability_mod > 0) ability_mod = 0;  // Cleave: keep only a negative mod
    result.damage_mod   = ability_mod + w.bonus_damage;
    result.total_damage = std::max(0, raw + result.damage_mod);
    result.damage_breakdown.clear();
    result.damage_breakdown.push_back({"weapon", result.total_damage});
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

AttackResult CombatEngine::executeAction(BattleMap& bm,
                                          const Attack& action)
{
    AttackResult invalid;  // valid = false

    auto agents = bm.placedAgents();
    int  n      = static_cast<int>(agents.size());

    if (action.attacker_idx < 0 || action.attacker_idx >= n) return invalid;
    if (action.target_idx   < 0 || action.target_idx   >= n) return invalid;
    if (action.attacker_idx == action.target_idx)             return invalid;

    const PlacedAgent& atk_pt = agents[action.attacker_idx];
    const PlacedAgent& tgt_pt = agents[action.target_idx];

    // Check if attacker is charmed and target is the charmer
    if (atk_pt.agent->getConditions().charmed) {
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.attacker_idx &&
                cond.condition_name == "Charmed" &&
                cond.caster_idx == action.target_idx) {
                log_("Attack blocked: attacker is charmed and cannot attack the charmer");
                return invalid;
            }
        }
    }

    // Check if attacker slipped this turn
    if (atk_pt.agent->hasSlippedThisTurn()) {
        log_("Attack blocked: attacker slipped and cannot act this turn");
        return invalid;
    }

    if (action.weapon_idx < 0 ||
            action.weapon_idx >= static_cast<int>(atk_pt.weapons.size()))
        return invalid;

    Weapon w = atk_pt.weapons[static_cast<std::size_t>(action.weapon_idx)];
    if (action.is_offhand) w.proficient = false;  // off-hand: no proficiency bonus to hit

    int atk_sz = atk_pt.agent->getSize();
    int tgt_sz = tgt_pt.agent->getSize();

    if (!canAttack(w, bm, atk_pt.origin, atk_sz, tgt_pt.origin, tgt_sz))
        return invalid;

    bool disadv = hasDisadvantage(w, bm,
                                   atk_pt.origin, atk_sz,
                                   tgt_pt.origin, tgt_sz);

    // Apply engagement disadvantage: ranged attacks suffer disadvantage if engaged
    bool is_ranged = (w.type == WeaponType::Ranged);
    if (is_ranged && isThreatened(bm, action.attacker_idx)) {
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

    AttackResult r = resolveAttack(w, *atk_pt.agent, *tgt_pt.agent, adv, dis, action.no_ability_damage);

    // Set Brutal Strike flag if eligible and attack hits
    Agent::Conditions updated_atk_cond = atk_cond;
    if (r.hit && can_use_brutal_strike) {
        updated_atk_cond.brutal_strike_available = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
    }
    // Reckless Attack: auto-reroll on miss for Barbarians
    else if (!r.hit &&
             atk_stats.character_class == CharacterClass::Barbarian &&
             !atk_cond.reckless_attack &&
             (w.type == WeaponType::Melee || w.thrown)) {
        updated_atk_cond.reckless_attack = true;
        bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        adv = true;
        r = resolveAttack(w, *atk_pt.agent, *tgt_pt.agent, adv, dis, action.no_ability_damage);
        log_("{} uses Reckless Attack (auto-reroll on miss)", agentName(bm, action.attacker_idx));
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

    // ── War Domain — Guided Strike eligibility (on a miss) ────────────────
    // A missed attack (not a natural 1) can be nudged to a hit by a War Cleric L3+ spending Channel
    // Divinity — the attacker themselves, or an ally within 30 ft (who pays a Reaction). Flag it; the
    // GUI offers the choice and calls applyGuidedStrike.
    if (!r.hit && !r.fumble) {
        bool eligible = false;
        for (int c = 0; c < static_cast<int>(agents.size()) && !eligible; ++c) {
            Agent::Stats cs = bm.getAgentStats(c);
            if (cs.character_class != CharacterClass::Cleric ||
                cs.cleric_subclass != WarDomain || cs.char_level < 3) continue;
            const Resource* cd = cs.getResource("Channel Divinity");
            if (!cd || cd->current <= 0) continue;
            if (c == action.attacker_idx) { eligible = true; break; }
            if (bm.getAgentConditions(c).reaction_used) continue;
            const Cell co = agents[static_cast<std::size_t>(c)].origin;
            const Cell ao = agents[static_cast<std::size_t>(action.attacker_idx)].origin;
            const double dx = co.col - ao.col, dy = co.row - ao.row;
            if (std::sqrt(dx * dx + dy * dy) * 5.0 <= 30.0) eligible = true;
        }
        if (eligible) {
            updated_atk_cond.guided_strike_available = true;
            bm.setAgentConditions(action.attacker_idx, updated_atk_cond);
        }
    }

    // ── Rogue Uncanny Dodge (L5+) ─────────────────────────────────────────
    // Reaction: halve the attack's damage (round down). Consumes the target's reaction.
    if (r.hit && r.total_damage > 0 &&
        tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 5 &&
        !tgt_cond.reaction_used && !tgt_cond.incapacitated) {
        int before = r.total_damage;
        r.total_damage = before / 2;
        Agent::Conditions tdef = bm.getAgentConditions(action.target_idx);
        tdef.reaction_used = true;
        bm.setAgentConditions(action.target_idx, tdef);
        r.damage_breakdown.push_back({"uncanny dodge", r.total_damage - before});  // negative: reduction
        log_("Uncanny Dodge: {} halves the attack ({} -> {})",
             agentName(bm, action.target_idx), before, r.total_damage);
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
        checkConcentrationOnDamage(bm, action.target_idx, r.total_damage);
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
            atk_stats.temp_hp = std::max(atk_stats.temp_hp, bonus);
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

    return r;
}

} // namespace rpg
