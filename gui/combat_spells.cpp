// ─────────────────────────────────────────────────────────────────────────────
//  combat_spells.cpp  –  CombatEngine spellcasting, zones, concentration, slots
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The spellcasting core: cast resolution (attack/save/automatic), Metamagic,
//  persistent zone/effect application & ticking, concentration management, and
//  Sorcerer/Abjurer spell-slot accounting.
//  Sections:
//    · Casting             — executeSpell, availableCastableSpells,
//                            getNumTargetsForSpell, metamagicSpCost
//    · Spell effects & zones— applySpellEffect, applyZoneIfNewThisTurn,
//                            recomputeAnchoredEffects, tickEffects, activeEffects,
//                            clearEffects
//    · Concentration       — concentrationSave, checkConcentrationOnDamage,
//                            dropConcentration, clearAllConcentration,
//                            clearSpellConditionEffect
//    · Slots               — createSpellSlot, convertSlotToSorceryPoints,
//                            expendArcaneWardSlot
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Casting
// ─────────────────────────────────────────────────────────────────────────────

SpellResult CombatEngine::executeSpell(BattleMap& bm, const SpellAction& action)
{
    SpellResult result;
    auto agents = bm.placedAgents();

    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size()))
        return result;
    const PlacedAgent& caster_pa = agents[static_cast<std::size_t>(action.caster_idx)];
    if (caster_pa.agent->getConditions().incapacitated) return result;
    if (caster_pa.agent->hasSlippedThisTurn()) return result;

    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size()))
        return result;
    // Mutable copy: some Metamagic options modify the spell for this cast only
    // (Distant doubles range, Extended doubles duration, Transmuted changes the
    // damage type, Quickened changes the casting time). The agent's stored spell
    // is untouched, and persistent effects copy this (already-modified) sp below.
    Spell sp = spells[static_cast<std::size_t>(action.spell_idx)];

    result.valid       = true;
    result.spell_idx   = action.spell_idx;
    result.spell_name  = sp.name;
    result.attack_type = sp.attack_type;

    const Agent::Stats& caster_stats = caster_pa.agent->getStats();

    // ── Sorcerer Metamagic ────────────────────────────────────────────────────
    // Validate applicability, then deduct Sorcery Points up front and apply the
    // option by temporarily mutating the local `sp` copy (Distant/Extended/Quickened/
    // Transmuted) or, for Careful, building a per-cast safe-target set used in the AoE
    // exclusion below. Heightened/Seeking are resolved per target in the AttackRoll/
    // Save branches via applied_metamagic. Empowered is deferred and Subtle is flavor
    // only — both log and spend no SP. See known_limitations.md.
    MetamagicOption applied_metamagic = MetamagicNone;
    std::vector<int> careful_set;          // Careful: allies excluded from this spell's area (capped at CHA mod)
    const int cha_mod = abilityMod(caster_stats.cha);

    auto isElemental = [](MagicDamage_t t) {
        return t == Acid || t == Cold || t == Fire || t == Lightning || t == Poison || t == Thunder;
    };

    if (action.metamagic == MetamagicEmpowered) {
        log_("Metamagic not applied: Empowered Spell not yet implemented in the combat engine");
    } else if (action.metamagic == MetamagicSubtle) {
        log_("Metamagic not applied: Subtle Spell has no effect in the combat engine");
    } else if (action.metamagic != MetamagicNone) {
        // Decide whether the option is applicable to THIS spell before spending SP.
        bool applicable = true;
        std::string why;
        switch (action.metamagic) {
            case MetamagicTransmuted: {
                bool valid_type = action.transmuted_damage_type >= 0 &&
                                  action.transmuted_damage_type < NumMagicDamage_t &&
                                  isElemental(static_cast<MagicDamage_t>(action.transmuted_damage_type));
                bool has_elem = std::any_of(sp.magic_damage_rolls.begin(), sp.magic_damage_rolls.end(),
                                            [&](const MagicDamageRoll& r){ return isElemental(r.type); });
                if (!valid_type)    { applicable = false; why = "no valid replacement damage type"; }
                else if (!has_elem) { applicable = false; why = "spell deals no Acid/Cold/Fire/Lightning/Poison/Thunder damage"; }
                break;
            }
            case MetamagicCareful:
                if (sp.attack_type != Spell::Save) { applicable = false; why = "Careful only affects saving-throw spells"; }
                break;
            case MetamagicExtended:
                if (sp.duration < 2) { applicable = false; why = "Extended needs a lasting (non-instantaneous) spell"; }
                break;
            case MetamagicQuickened:
                if (sp.casting_time != Spell::Action) { applicable = false; why = "Quickened needs an Action-cast spell"; }
                break;
            default: break;  // Distant / Heightened / Seeking / Twinned always apply
        }

        if (!applicable) {
            log_("Metamagic not applied: {}", why);
        } else if (!spendResource(bm, action.caster_idx, "Sorcery Points", metamagicSpCost(action.metamagic))) {
            log_("Metamagic not applied: not enough Sorcery Points");
        } else {
            const int cost = metamagicSpCost(action.metamagic);
            applied_metamagic = action.metamagic;
            switch (action.metamagic) {
                case MetamagicCareful:
                    // Same effect as the Evoker's safe targets: chosen allies are excluded from the area.
                    for (int t : action.careful_targets) {
                        if (static_cast<int>(careful_set.size()) >= std::max(1, cha_mod)) break;
                        careful_set.push_back(t);
                    }
                    log_("Metamagic: Careful Spell ({} SP) — {} creature(s) shielded from the area", cost, careful_set.size());
                    break;
                case MetamagicDistant:
                    sp.range = (sp.range >= 5) ? sp.range * 2 : 30;
                    log_("Metamagic: Distant Spell ({} SP) — range now {} ft", cost, sp.range);
                    break;
                case MetamagicExtended:
                    sp.duration *= 2;
                    log_("Metamagic: Extended Spell ({} SP) — duration now {} rounds", cost, sp.duration);
                    break;
                case MetamagicHeightened:
                    log_("Metamagic: Heightened Spell ({} SP)", cost);
                    break;
                case MetamagicQuickened:
                    sp.casting_time = Spell::BonusAction;
                    result.cast_as_bonus_action = true;
                    log_("Metamagic: Quickened Spell ({} SP) — cast as a Bonus Action", cost);
                    break;
                case MetamagicSeeking:
                    log_("Metamagic: Seeking Spell ({} SP)", cost);
                    break;
                case MetamagicTransmuted: {
                    auto new_type = static_cast<MagicDamage_t>(action.transmuted_damage_type);
                    for (auto& r : sp.magic_damage_rolls)
                        if (isElemental(r.type)) r.type = new_type;
                    log_("Metamagic: Transmuted Spell ({} SP) — elemental damage changed type", cost);
                    break;
                }
                case MetamagicTwinned:
                    sp.targets_per_upcast_level += 1;
                    log_("Metamagic: Twinned Spell ({} SP) — +1 target per upcast level", cost);
                    break;
                default: break;
            }
        }
    }

    // Concentration management: check if casting a concentration spell
    if (sp.requires_concentration) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        if (cond.concentrating) {
            // Drop previous concentration
            result.concentration_replaced    = true;
            result.prev_concentration_spell  = cond.concentrating_on;
            cond.concentrating    = false;
            cond.concentrating_on = {};
            bm.setAgentConditions(action.caster_idx, cond);
            // Remove old spell's terrain when dropping concentration
            [[maybe_unused]] auto removed_ids = bm.removeTerrainEffectsBySource(action.caster_idx);
        }
    }

    // Moving Sphere (Emanation): the area is centered on the caster, not an aimed point.
    const bool moving_sphere = (sp.geometry == Spell::Sphere && sp.moves_with_caster);
    int center_col = action.aoe_col;
    int center_row = action.aoe_row;
    if (moving_sphere) {
        center_col = caster_pa.origin.col;
        center_row = caster_pa.origin.row;
    }

    std::vector<int> targets =
        (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple)
        ? action.target_indices
        : resolveAoeTargets(agents, sp, action.caster_idx, center_col, center_row,
                            action.aoe_col2, action.aoe_row2);

    // Evoker safe targets fully exclude the caster's protected allies from AoE spells
    // (no save, no damage, no conditions). Metamagic Careful protects the chosen
    // creatures the same way for this one cast. Single/Multiple are directly targeted,
    // so they are untouched.
    if (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple) {
        auto it = safeTargets_.find(action.caster_idx);
        std::vector<int> safe = (it != safeTargets_.end()) ? it->second : std::vector<int>{};
        safe.insert(safe.end(), careful_set.begin(), careful_set.end());
        if (!safe.empty()) {
            std::erase_if(targets, [&safe](int t) {
                return std::find(safe.begin(), safe.end(), t) != safe.end();
            });
        }
    }

    // Emanation ignores the caster's own space — the caster is never a target.
    if (moving_sphere)
        std::erase(targets, action.caster_idx);

    // Check if caster is charmed and any target is the charmer
    if (caster_pa.agent->getConditions().charmed) {
        int charmer_idx = -1;
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.caster_idx &&
                cond.condition_name == "Charmed") {
                charmer_idx = cond.caster_idx;
                break;
            }
        }

        if (charmer_idx >= 0) {
            // Check if charmer is in the target list
            for (int tgt_idx : targets) {
                if (tgt_idx == charmer_idx) {
                    log_("Spell blocked: caster is charmed and cannot target the charmer with a damaging spell");
                    return result;  // Invalid (valid = false)
                }
            }
        }
    }

    bool any_conditions_applied = false;
    bool any_kill = false;  // TASK A: Dark One's Blessing tracking

    // TASK D: Radiant Soul (Celestial L6): does this spell deal Radiant(8) or Fire(2) damage?
    // Computed once per cast; the +CHA bonus below applies to the first damaged target this turn.
    bool spell_radiant_or_fire = false;
    for (const auto& rinfo : sp.magic_damage_rolls)
        if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }
    if (!spell_radiant_or_fire)
        for (const auto& rinfo : sp.physical_damage_rolls)
            if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }

    for (int tgt_idx : targets) {
        if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;

        Agent::Stats tgt_stats = bm.getAgentStats(tgt_idx);
        SpellTargetResult tr;
        tr.target_idx = tgt_idx;
        tr.hp_before  = tgt_stats.hp_cur;

        // Wild Magic Surge band 2 (spectral shield): immunity to Magic Missile.
        if (sp.name == "Magic Missile" && tgt_stats.wild_magic_shield_turns > 0) {
            tr.hp_after = tgt_stats.hp_cur;
            tr.log_message = agentName(bm, tgt_idx) + " is immune to Magic Missile (spectral shield)";
            log_("{}", tr.log_message);
            result.target_results.push_back(tr);
            continue;
        }

        switch (sp.attack_type) {

        case Spell::AttackRoll: {
            // Apply advantage/disadvantage from caster conditions
            bool caster_adv = caster_pa.agent->hasAdvantage();
            bool caster_dis = caster_pa.agent->hasDisadvantage();

            // Blinded: caster's attacks have disadvantage
            if (caster_pa.agent->getConditions().blinded) {
                caster_dis = true;
                log_("Disadvantage: caster is blinded");
            }

            // Frightened: caster has disadvantage when fear source is in LOS
            if (caster_pa.agent->getConditions().frightened) {
                for (const auto& ac : activeAgentConditions_) {
                    if (ac.agent_idx == action.caster_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
                        if (bm.hasLineOfSight(caster_pa.origin, caster_pa.agent->getSize(),
                                              bm.placedAgents()[ac.caster_idx].origin, 1)) {
                            caster_dis = true;
                            log_("Disadvantage: caster is frightened and fear source is in LOS");
                        }
                        break;
                    }
                }
            }

            // Grappled: caster has disadvantage on spell attacks except against the grappler
            if (caster_pa.agent->getConditions().grappled) {
                if (action.target_indices[0] != caster_pa.agent->getConditions().grappler_idx) {
                    caster_dis = true;
                    log_("Disadvantage: caster is grappled");
                }
            }

            // Apply engagement disadvantage for ranged spells
            if (sp.range > 0 && isThreatened(bm, action.caster_idx)) {
                caster_dis = true;
                log_("Disadvantage: threatened (enemy within 10 ft)");
            }
            if (caster_pa.agent->hasDisadvantage())
                log_("Disadvantage: condition");
            if (caster_pa.agent->hasAdvantage())
                log_("Advantage: condition");

            // Sorcerer Innate Sorcery: advantage on the caster's spell attack rolls while active.
            if (caster_stats.innate_sorcery_turns > 0) {
                caster_adv = true;
                log_("Advantage: Innate Sorcery");
            }

            // Target blinded: attacker has advantage
            bool target_blinded = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().blinded;
            if (target_blinded) {
                caster_adv = true;
                log_("Advantage: target is blinded");
            }

            // Target stunned: attacker has advantage
            bool target_stunned = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().stunned;
            if (target_stunned) {
                caster_adv = true;
                log_("Advantage: target is stunned");
            }

            int d20_val;
            if (caster_adv && caster_dis) {
                d20_val = roll(20);  // Cancel out
            } else if (caster_adv) {
                d20_val = rollAdvantage(20);
            } else if (caster_dis) {
                d20_val = rollDisadvantage(20);
            } else {
                d20_val = roll(20);
            }
            int mod     = spellAttackMod(caster_stats);
            int total   = d20_val + mod;
            tr.d20        = d20_val;
            tr.attack_mod = mod;
            tr.total_roll = total;
            tr.target_ac  = calculateAC(bm, tgt_idx);
            tr.critical   = (d20_val >= caster_stats.crit_threshold);
            tr.hit        = tr.critical || (d20_val != 1 && total >= tr.target_ac);

            // Metamagic — Seeking Spell: reroll a missed spell attack once, keep the new roll.
            if (applied_metamagic == MetamagicSeeking && !tr.hit) {
                int reroll;
                if (caster_adv && caster_dis)      reroll = roll(20);
                else if (caster_adv)               reroll = rollAdvantage(20);
                else if (caster_dis)               reroll = rollDisadvantage(20);
                else                               reroll = roll(20);
                log_("Metamagic Seeking: reroll {} (was {})", reroll, d20_val);
                d20_val       = reroll;
                total         = d20_val + mod;
                tr.d20        = d20_val;
                tr.total_roll = total;
                tr.critical   = (d20_val >= caster_stats.crit_threshold);
                tr.hit        = tr.critical || (d20_val != 1 && total >= tr.target_ac);
            }

            if (tr.hit) {
                std::vector<int> dice;
                int dmg = 0;

                if (sp.type == Spell::Heal) {
                    // Healing spell: roll healing_type dice + add spellcasting ability modifier
                    int n_dice = sp.healing_type.num_dice;
                    int die_size = sp.healing_type.die_size;
                    for (int i = 0; i < n_dice; ++i) {
                        int d = roll(die_size);
                        dice.push_back(d);
                        dmg += d;
                    }
                    dmg += sp.healing_type.bonus;
                    // Add spellcasting ability modifier
                    int ability_score = 10;  // default
                    if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                    else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                    else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                    else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                    else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                    else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                    int ability_mod = abilityMod(ability_score);
                    dmg += ability_mod;
                    log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                         n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                         sp.healing_type.bonus, ability_mod, dmg);
                } else {
                    // Damage spell: roll per-damage-type damage and apply target's multipliers
                    for (const auto& roll_info : sp.magic_damage_rolls) {
                        int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                        int type_damage = 0;
                        for (int i = 0; i < n_dice; ++i) {
                            int d = roll(roll_info.die_size);
                            dice.push_back(d);
                            type_damage += d;
                        }
                        // Apply target's resistance/vulnerability/immunity multiplier
                        float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                        log_("[DAMAGE] Spell attack: type={} base={} mult={} result={}", static_cast<int>(roll_info.type), type_damage, multiplier, modified_damage);
                        dmg += modified_damage;
                    }
                    for (const auto& roll_info : sp.physical_damage_rolls) {
                        int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                        int type_damage = 0;
                        for (int i = 0; i < n_dice; ++i) {
                            int d = roll(roll_info.die_size);
                            dice.push_back(d);
                            type_damage += d;
                        }
                        // Apply target's resistance/vulnerability/immunity multiplier
                        float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                        dmg += modified_damage;
                    }

                    // Agonizing Blast: add CHA modifier to each Eldritch Blast beam's damage.
                    if (sp.name == "Eldritch Blast" &&
                        caster_stats.character_class == CharacterClass::Warlock &&
                        caster_stats.hasInvocation(0)) {
                        int chaMod = abilityMod(caster_stats.cha);
                        if (chaMod > 0) {
                            dmg += chaMod;
                            log_("Agonizing Blast: +{} damage", chaMod);
                        }
                    }
                }

                tr.dice_results = dice;

                if (sp.type == Spell::Heal) {
                    tr.total_healing = std::max(0, dmg);
                    tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                                tgt_stats.hp_cur + tr.total_healing);
                } else {
                    tr.total_damage  = std::max(0, dmg);
                    // Temporary HP absorbs damage first, then overflow damages hp_cur
                    int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                    tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
                }
            }

            // Generate log message
            std::string crit_str = tr.critical ? " CRIT!" : "";
            std::string result_str = tr.total_healing ? "HEAL" : (tr.total_damage > 0 ? "HIT" : "HIT");
            std::string damage_str = std::to_string(tr.total_healing ? tr.total_healing : tr.total_damage);
            std::string down_str = tr.target_down ? " — DOWN" : "";

            if (tr.hit) {
                tr.log_message = "HIT (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")"
                    + crit_str + " " + damage_str + down_str;
            } else {
                tr.log_message = "miss (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")";
            }
            break;
        }

        case Spell::Save: {
            int save_dc  = spellSaveDc(caster_stats);
            // Apply advantage/disadvantage from target conditions
            const PlacedAgent& target_pa = agents[static_cast<std::size_t>(tgt_idx)];
            const Agent::Conditions& target_cond = target_pa.agent->getConditions();
            bool target_adv = target_pa.agent->hasAdvantage();
            bool target_dis = target_pa.agent->hasDisadvantage();

            // Metamagic — Heightened Spell: one target has disadvantage on its save.
            if (applied_metamagic == MetamagicHeightened && !targets.empty() && tgt_idx == targets.front()) {
                target_dis = true;
                log_("Metamagic Heightened: {} has disadvantage on the save", agentName(bm, tgt_idx));
            }

            // Paralyzed, Stunned, and Unconscious targets automatically fail STR and DEX saves
            bool auto_fail = (target_cond.paralyzed || target_cond.stunned || target_cond.unconscious) &&
                            (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

            // Barbarian Danger Sense (L2+): Advantage on DEX saves unless Incapacitated
            if (sp.save_ability == SaveDex && !target_cond.incapacitated &&
                tgt_stats.character_class == CharacterClass::Barbarian && tgt_stats.char_level >= 2) {
                target_adv = true;
                log_("Danger Sense: target has Advantage on DEX save");
            }

            int save_d20;
            if (auto_fail) {
                save_d20 = 1;  // Automatic fail
                std::string reason = target_cond.paralyzed ? "paralyzed" : (target_cond.stunned ? "stunned" : "unconscious");
                log_("Target is {}: automatically fails {} save",
                     reason, sp.save_ability == SaveStr ? "STR" : "DEX");
            } else if (target_adv && target_dis) {
                save_d20 = roll(20);  // Cancel out
            } else if (target_adv) {
                save_d20 = rollAdvantage(20);
            } else if (target_dis) {
                save_d20 = rollDisadvantage(20);
            } else {
                save_d20 = roll(20);
            }
            auto saveMod = [&](SaveAbility_t ab) -> int {
                int score = 0; bool prof = false;
                switch (ab) {
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
            tr.save_d20 = save_d20;
            tr.save_dc  = save_dc;
            tr.saved = auto_fail ? false : (save_d20 + saveMod(sp.save_ability) >= save_dc);

            std::vector<int> dice;
            int dmg = 0;

            if (sp.type == Spell::Heal) {
                // Healing spell: roll healing_type dice + add spellcasting ability modifier
                int n_dice = sp.healing_type.num_dice;
                int die_size = sp.healing_type.die_size;
                for (int i = 0; i < n_dice; ++i) {
                    int d = roll(die_size);
                    dice.push_back(d);
                    dmg += d;
                }
                dmg += sp.healing_type.bonus;
                // Add spellcasting ability modifier
                int ability_score = 10;  // default
                if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                int ability_mod = abilityMod(ability_score);
                dmg += ability_mod;
                log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                     n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                     sp.healing_type.bonus, ability_mod, dmg);
            } else {
                // Damage spell: roll per-damage-type damage and apply target's multipliers
                for (const auto& roll_info : sp.magic_damage_rolls) {
                    int type_damage = 0;
                    for (int i = 0; i < roll_info.num_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier first
                    float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    // Then apply half damage on successful save
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }
                for (const auto& roll_info : sp.physical_damage_rolls) {
                    int type_damage = 0;
                    for (int i = 0; i < roll_info.num_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier first
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    // Then apply half damage on successful save
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }

                // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
                // A successful save already halved per-roll above; override to the Evasion outcome.
                if (sp.save_ability == SaveDex &&
                    tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 7 &&
                    !target_cond.incapacitated) {
                    dmg = tr.saved ? 0 : (dmg / 2);
                    log_("Evasion: {} {} damage on a DEX save", agentName(bm, tgt_idx),
                         tr.saved ? "takes no" : "halves");
                }
            }

            tr.dice_results = dice;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, dmg);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, dmg);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        case Spell::Automatic:
        default: {
            std::vector<int> dice;
            int total = 0;

            if (sp.type == Spell::Heal) {
                // Healing spell: roll healing_type dice + add spellcasting ability modifier
                int n_dice = sp.healing_type.num_dice;
                int die_size = sp.healing_type.die_size;
                for (int i = 0; i < n_dice; ++i) {
                    int d = roll(die_size);
                    dice.push_back(d);
                    total += d;
                }
                total += sp.healing_type.bonus;
                // Add spellcasting ability modifier
                int ability_score = 10;  // default
                if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                int ability_mod = abilityMod(ability_score);
                total += ability_mod;
                log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                     n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                     sp.healing_type.bonus, ability_mod, total);
            } else {
                // Damage spell: roll per-damage-type damage and apply target's multipliers
                for (const auto& roll_info : sp.magic_damage_rolls) {
                    int type_damage = 0;
                    for (int i = 0; i < roll_info.num_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier
                    float multiplier = tgt_stats.magic_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    total += modified_damage;
                }
                for (const auto& roll_info : sp.physical_damage_rolls) {
                    int type_damage = 0;
                    for (int i = 0; i < roll_info.num_dice; ++i) {
                        int d = roll(roll_info.die_size);
                        dice.push_back(d);
                        type_damage += d;
                    }
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    total += modified_damage;
                }
            }

            tr.dice_results = dice;
            tr.hit = true;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, total);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, total);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        } // switch

        // TASK D: Radiant Soul (Celestial L6+): once per turn, add CHA mod to one damaging
        // Radiant/Fire spell. Applies across all attack types (AttackRoll/Save/Automatic).
        if (tr.total_damage > 0 && sp.type != Spell::Heal && spell_radiant_or_fire &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.warlock_subclass == CelestialPath && caster_stats.char_level >= 6) {
            Agent::Conditions caster_cond = bm.getAgentConditions(action.caster_idx);
            if (!caster_cond.radiant_soul_used) {
                int chaMod = (caster_stats.cha - 10) / 2;
                if (caster_stats.cha < 10 && (caster_stats.cha - 10) % 2 != 0) --chaMod;
                if (chaMod > 0) {
                    int overflow = std::max(0, chaMod - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - chaMod);
                    tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                    tr.total_damage += chaMod;
                    log_("{}: Radiant Soul adds {} damage to {} spell", agentName(bm, action.caster_idx), chaMod, sp.name);
                }
                caster_cond.radiant_soul_used = true;
                bm.setAgentConditions(action.caster_idx, caster_cond);
            }
        }

        // Cleric Blessed Strikes — Potent Spellcasting (L7+): add WIS mod to Cleric cantrip damage.
        if (tr.total_damage > 0 && sp.type != Spell::Heal && sp.level == 0 &&
            caster_stats.character_class == CharacterClass::Cleric &&
            caster_stats.char_level >= 7 &&
            caster_stats.blessed_strike == BlessedStrikePotentSpellcasting) {
            int wisMod = (caster_stats.wis - 10) / 2;
            if (caster_stats.wis < 10 && (caster_stats.wis - 10) % 2 != 0) --wisMod;
            if (wisMod > 0) {
                int overflow = std::max(0, wisMod - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - wisMod);
                tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                tr.total_damage += wisMod;
                log_("{}: Potent Spellcasting adds {} damage to {}", agentName(bm, action.caster_idx), wisMod, sp.name);
            }
        }

        tr.hp_after    = tgt_stats.hp_cur;
        tr.target_down = (tgt_stats.hp_cur <= 0);
        bm.setAgentStats(tgt_idx, tgt_stats);

        // Repelling Blast: each Eldritch Blast beam that hits pushes the target 10 ft away.
        if (tr.hit && sp.name == "Eldritch Blast" &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.hasInvocation(1)) {
            int moved = bm.forceMoveAgent(tgt_idx, caster_pa.origin, 10);
            if (moved > 0)
                log_("Repelling Blast: {} pushed {} ft", agentName(bm, tgt_idx), moved * 5);
        }

        // TASK A: Dark One's Blessing tracking
        if (tr.target_down) any_kill = true;

        // Auto-trigger Unconscious if HP drops to 0 or below
        if (tgt_stats.hp_cur <= 0) {
            Agent::Conditions tgt_cond_before = bm.getAgentConditions(tgt_idx);
            bool spell_just_knocked_unconscious = (!tgt_cond_before.unconscious && !tgt_cond_before.dead);
            if (spell_just_knocked_unconscious) {
                log_("[SPELL KNOCKDOWN] {} going unconscious from spell damage ({})", agentName(bm, tgt_idx), sp.name);
                applyUnconscious(bm, tgt_idx);
                // Don't roll death save yet - they'll roll on their next turn or if they take more damage
            } else if (tgt_cond_before.unconscious && !tgt_cond_before.dead && tr.total_damage > 0) {
                log_("[SPELL DEATH SAVE] {} already unconscious, rolling death save from spell damage", agentName(bm, tgt_idx));
                // Death save on damage for agents already unconscious
                rollDeathSave(bm, tgt_idx);
            }
        }

        // Check concentration saves: once per damage instance (e.g., once per Magic Missile)
        if (tr.total_damage > 0 && !tr.dice_results.empty()) {
            // For spells with multiple damage instances (dice rolls), check concentration for each
            int num_instances = std::max(1, static_cast<int>(tr.dice_results.size()));
            int damage_per_instance = tr.total_damage / num_instances;
            if (damage_per_instance == 0 && tr.total_damage > 0) {
                damage_per_instance = 1;  // Ensure at least 1 damage per instance
            }
            for (int i = 0; i < num_instances && !tr.concentration_lost; ++i) {
                if (checkConcentrationOnDamage(bm, tgt_idx, damage_per_instance)) {
                    tr.concentration_checked = true;
                    tr.concentration_lost = true;
                }
            }
            if (damage_per_instance > 0) {
                tr.concentration_checked = true;
            }
        }

        // On-damage condition behavior (Sleep/Hypnotic Pattern end; Tasha's re-saves) for
        // any pre-existing condition on this target. Runs before this spell's own conditions
        // are applied, so a damaging spell can't instantly cancel the condition it just set.
        processDamageTaken(bm, tgt_idx, tr.total_damage);

        // Apply spell-based conditions (e.g., Hold Person applies Paralyzed)
        if (!sp.conditions.empty()) {
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

            for (const auto& spell_cond : sp.conditions) {
                // Determine if this specific condition applies to the target
                log_("[COND] Processing condition '{}' for {}, requires_save={}, push_ft={}",
                     spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);
                bool condition_applies = false;
                bool target_failed_save = false;

                // Determine if condition applies based on spell type and whether it requires a save
                if (spell_cond.requires_save) {
                    // Condition requires a save
                    if (sp.attack_type == Spell::Save) {
                        // For Save spells, reuse the existing save result
                        target_failed_save = !tr.saved;
                        condition_applies = target_failed_save;
                        log_("[COND SAVE] {} vs {}: tr.saved={}, target_failed_save={}, condition_applies={}",
                             spell_cond.condition_name, agentName(bm, tgt_idx), tr.saved, target_failed_save, condition_applies);
                    } else {
                        // For other spell types, roll a new save for this condition
                        int save_dc = spellSaveDc(caster_stats);

                        int save_d20 = roll(20);
                        auto saveMod = [&](SaveAbility_t ab) -> int {
                            int score = 0; bool prof = false;
                            switch (ab) {
                                case SaveStr: score = tgt_stats.str;   prof = tgt_stats.save_prof_str;   break;
                                case SaveDex: score = tgt_stats.dex;   prof = tgt_stats.save_prof_dex;   break;
                                case SaveCon: score = tgt_stats.con;   prof = tgt_stats.save_prof_con;   break;
                                case SaveInt: score = tgt_stats.intel; prof = tgt_stats.save_prof_intel; break;
                                case SaveWis: score = tgt_stats.wis;   prof = tgt_stats.save_prof_wis;   break;
                                default:      score = tgt_stats.cha;   prof = tgt_stats.save_prof_cha;   break;
                            }
                            int m = (score - 10) / 2;
                            if (score < 10 && (score - 10) % 2 != 0) --m;
                            return m + (prof ? tgt_stats.prof_bonus : 0);
                        };

                        bool save_succeeded = (save_d20 + saveMod(spell_cond.save_ability) >= save_dc);
                        target_failed_save = !save_succeeded;
                        condition_applies = target_failed_save;

                        log_("{} save vs {} condition: rolled {} + {} = {} vs DC {} — {}",
                             ability_name(spell_cond.save_ability),
                             spell_cond.condition_name,
                             save_d20, saveMod(spell_cond.save_ability),
                             save_d20 + saveMod(spell_cond.save_ability),
                             save_dc,
                             save_succeeded ? "SAVED" : "FAILED");
                    }
                } else {
                    // Condition doesn't require a save, apply based on spell attack type
                    if (sp.attack_type == Spell::AttackRoll) {
                        condition_applies = tr.hit;
                    } else {
                        condition_applies = true;
                    }
                }

                if (condition_applies) {
                    log_("[APPLY] Applying condition '{}' to {}, requires_save={}, push_ft={}",
                         spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);

                    ActiveAgentCondition cond;
                    cond.agent_idx   = tgt_idx;
                    cond.caster_idx  = action.caster_idx;
                    cond.spell_idx   = action.spell_idx;
                    cond.condition_name = spell_cond.condition_name;
                    cond.save_ability = spell_cond.save_ability;
                    cond.on_damage = spell_cond.on_damage;

                    // Condition duration: if condition_duration is 0, use spell duration
                    cond.turns_remaining = (spell_cond.condition_duration > 0) ? spell_cond.condition_duration : sp.duration;
                    // Save DC: use caster's spellcasting ability if SaveSpellcasterMod, else use specified ability
                    if (spell_cond.save_dc_ability == SaveSpellcasterMod) {
                        cond.save_dc = spellSaveDc(caster_stats);
                    } else {
                        cond.save_dc = spellSaveDcFromAbility(caster_stats, spell_cond.save_dc_ability);
                    }
                    // How often to repeat save checks
                    cond.save_repeat_turns = spell_cond.save_repeat_turns;
                    // Target can save at the start of their next turn (next_save_turn == 0 means "save now")
                    cond.next_save_turn = 0;

                    [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
                    any_conditions_applied = true;

                    // Apply spell push on failed save
                    if (spell_cond.condition_name == "Push" && spell_cond.push_ft > 0) {
                        log_("[PUSH] Attempting to push {} {} feet by spell '{}'", agentName(bm, tgt_idx), spell_cond.push_ft, sp.name);
                        auto spell_agents = bm.placedAgents();
                        if (action.caster_idx >= 0 && action.caster_idx < static_cast<int>(spell_agents.size())) {
                            const auto& caster = spell_agents[action.caster_idx];
                            log_("[PUSH] Caster at ({},{}), target at ({},{})", caster.origin.col, caster.origin.row, spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            int cells_moved = bm.forceMoveAgent(tgt_idx, caster.origin, spell_cond.push_ft);
                            log_("[PUSH] forceMoveAgent returned {} cells moved", cells_moved);
                            tr.push_ft_applied = cells_moved * 5;
                            if (cells_moved > 0) {
                                log_("Target pushed {} feet by {}", tr.push_ft_applied, sp.name);
                                log_("[PUSH] Target now at ({},{})", spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            } else {
                                log_("[PUSH] No movement occurred (blocked or out of range)");
                            }
                        } else {
                            log_("[PUSH] Invalid caster index: {}", action.caster_idx);
                        }
                    }
                }
            }
        }

        result.target_results.push_back(tr);
    }

    // TASK A: Dark One's Blessing (Fiend L3): temp HP on spell kill
    if (any_kill && caster_stats.character_class == CharacterClass::Warlock && caster_stats.warlock_subclass == FiendPath && caster_stats.char_level >= 3) {
        int chaMod = (caster_stats.cha - 10) / 2;
        if (caster_stats.cha < 10 && (caster_stats.cha - 10) % 2 != 0) --chaMod;
        int bonus = std::max(1, chaMod + caster_stats.char_level);
        Agent::Stats updated_stats = bm.getAgentStats(action.caster_idx);
        updated_stats.temp_hp = std::max(updated_stats.temp_hp, bonus);
        bm.setAgentStats(action.caster_idx, updated_stats);
        log_("{}: Dark One's Blessing grants {} temp HP", agentName(bm, action.caster_idx), bonus);
    }

    // Register persistent effects (duration > 1 means per-tick damage/heal on
    // subsequent turns; we already applied the first application above).
    if (sp.duration > 1) {
        for (int tgt_idx : targets) {
            if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;
            ActiveEffect fx;
            fx.caster_idx      = action.caster_idx;
            fx.target_idx      = tgt_idx;
            fx.spell           = sp;
            fx.turns_remaining = sp.duration - 1;
            activeEffects_.push_back(fx);
        }
    }

    // Set concentration after successful spell cast (if required and if spell affected targets)
    // For condition-based spells, only set concentration if a condition was actually applied
    // For damage/heal spells or AoE terrain spells, set concentration if any targets were affected
    bool should_concentrate = false;
    if (sp.requires_concentration && result.valid) {
        const bool is_aoe = (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple);
        if (is_aoe) {
            // AoE spells create a persistent area (terrain/zone); concentration holds
            // even with no current targets in the area.
            should_concentrate = true;
        } else if (!sp.conditions.empty()) {
            // Targeted (Single/Multiple) condition spell: only concentrate if a
            // condition actually landed (e.g. Hold Person fizzles if every target saved).
            should_concentrate = any_conditions_applied;
        } else {
            should_concentrate = true;
        }
    }

    if (should_concentrate) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        cond.concentrating    = true;
        cond.concentrating_on = sp.name;
        bm.setAgentConditions(action.caster_idx, cond);
    }

    // Create persistent spell effect if spell has AoE geometry and duration > 1
    if (result.valid && sp.duration > 1 && sp.geometry != Spell::Single) {
        std::vector<Cell> effect_cells;

        // Calculate cells based on spell geometry
        if (sp.geometry == Spell::Sphere) {
            // For a moving Sphere, center_col/center_row are the caster's origin.
            effect_cells = sphereCellsAround(center_col, center_row, sp.radius);
        } else if (sp.geometry == Spell::Rectangle) {
            // Oriented wall from the aim point toward the endpoint, clamped to
            // spell.length (falls back to a centered box when unaimed).
            effect_cells = bm.wallCells(Cell{action.aoe_col, action.aoe_row},
                                        Cell{action.aoe_col2, action.aoe_row2},
                                        sp.width, sp.length);
        } else if (sp.geometry == Spell::Square) {
            double w_cells = sp.width / 5.0;
            double l_cells = sp.length / 5.0;
            int cols = bm.gridCols();
            int rows = bm.gridRows();
            // Center the square on the clicked point
            for (int c = 0; c < cols; ++c) {
                for (int r = 0; r < rows; ++r) {
                    double dx = std::abs(c - action.aoe_col);
                    double dy = std::abs(r - action.aoe_row);
                    if (dx <= w_cells / 2.0 && dy <= l_cells / 2.0) {
                        effect_cells.push_back(Cell{c, r});
                    }
                }
            }
        } else if (sp.geometry == Spell::Line) {
            int length_cells = (sp.length + 4) / 5;
            // Assume horizontal for now (can be enhanced)
            for (int c = action.aoe_col; c < action.aoe_col + length_cells; ++c) {
                effect_cells.push_back(Cell{c, action.aoe_row});
            }
        } else if (sp.geometry == Spell::Cone) {
            int length_cells = (sp.length + 4) / 5;
            // Simple cone approximation (would need direction in real implementation)
            for (int dist = 0; dist < length_cells; ++dist) {
                for (int width = -dist; width <= dist; ++width) {
                    effect_cells.push_back(Cell{action.aoe_col + dist, action.aoe_row + width});
                }
            }
        }

        // Create ActiveSpellEffect if we have cells
        if (!effect_cells.empty()) {
            ActiveSpellEffect effect;
            effect.caster_idx = action.caster_idx;
            effect.spell_idx = action.spell_idx;
            effect.spell = sp;
            effect.cells = effect_cells;
            effect.turns_remaining = sp.duration;
            effect.effect_id = -1;  // Will be assigned by addSpellEffect
            effect.anchor_agent_idx = moving_sphere ? action.caster_idx : -1;
            [[maybe_unused]] int effect_id = bm.addSpellEffect(effect);
        }
    }

    // Terrain placement: if spell creates difficult terrain
    if (result.valid && sp.terrain_difficulty != TerrainDifficulty::Normal) {
        Cell center = Cell{action.aoe_col, action.aoe_row};
        Cell caster_origin = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].origin;
        int caster_size = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].agent->getSize();

        Cell endpoint = Cell{action.aoe_col2, action.aoe_row2};  // for oriented walls
        auto raw_cells = bm.aoeCells(center, sp, caster_origin, endpoint);
        auto terrain_cells = bm.filterSpellCells(raw_cells, caster_origin, caster_size, sp, center);

        if (!terrain_cells.empty()) {
            int terrain_id = bm.placeTerrainEffect(
                sp.name, terrain_cells, sp.terrain_difficulty,
                sp.duration, action.caster_idx,
                sp.slip_save_dc, sp.slip_distance_feet,
                action.spell_idx, sp.requires_concentration);

            if (terrain_id >= 0) {
                result.terrain_effect_ids.push_back(terrain_id);

                // Slipping terrain: immediate DEX save for agents in the AoE
                if (sp.terrain_difficulty == TerrainDifficulty::Slipping) {
                    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
                        if (i == action.caster_idx) continue;
                        Cell agent_cell = bm.placedAgents()[static_cast<std::size_t>(i)].origin;
                        bool in_aoe = std::any_of(terrain_cells.begin(), terrain_cells.end(),
                            [&agent_cell](const Cell& c) { return c.col == agent_cell.col && c.row == agent_cell.row; });
                        if (!in_aoe) continue;
                        auto stats = getAgentStats(bm, i);
                        int dex_mod = (stats.dex - 10) / 2;
                        if (stats.dex < 10 && (stats.dex - 10) % 2 != 0) --dex_mod;  // floor for odd negative scores
                        if (stats.save_prof_dex) dex_mod += stats.prof_bonus;        // DEX save proficiency
                        int d20 = roll(20);
                        if (d20 + dex_mod < sp.slip_save_dc) {
                            Agent::Conditions cond_i = bm.getAgentConditions(i);
                            cond_i.prone = true;
                            bm.setAgentConditions(i, cond_i);
                            log_("Slipping terrain: {} fails DEX save (d20={}) — prone.",
                                 bm.placedAgents()[i].agent->name(), d20);
                        }
                    }
                }
            }
        }
    }

    // If caster was hidden and cast a spell, reveal them
    if (result.valid && action.caster_idx >= 0 && action.caster_idx < static_cast<int>(agents.size())) {
        const Agent::Conditions& caster_cond = agents[static_cast<std::size_t>(action.caster_idx)].agent->getConditions();
        if (caster_cond.hidden) {
            Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
            cond.hidden = false;
            bm.setAgentConditions(action.caster_idx, cond);
            log_("{} is no longer hidden", agents[static_cast<std::size_t>(action.caster_idx)].agent->name());
        }
    }

    // Decrement resources (uses or spell slots) after successful cast
    if (result.valid) {
        log_("[DEBUG execute_spell] result.valid=true, slot_level={}, caster_idx={}", action.slot_level, action.caster_idx);
        PlacedAgent& pa = bm.placedAgentMut(action.caster_idx);
        Spell& spell_mut = pa.spells[static_cast<std::size_t>(action.spell_idx)];
        Agent::Stats& stats = pa.agent->getStats();

        // Mark leveled spell cast (once per turn, even if upcasted)
        if (sp.level > 0) {
            stats.markLeveledSpellCast(sp.level);
        }

        if (!spell_mut.resource_name.empty()) {
            // Class feature: spend its named resource (e.g. Channel Divinity) instead of a slot.
            int cost = std::max(1, spell_mut.resource_cost);
            Resource* res = stats.getResource(spell_mut.resource_name);
            if (res) res->spend(cost);
            log_("{} spends {} {}", agentName(bm, action.caster_idx), cost, spell_mut.resource_name);
        } else if (stats.is_npc) {
            log_("[DEBUG execute_spell] NPC branch taken for agent {}", action.caster_idx);
            // NPC: decrement N/day uses
            if (spell_mut.uses_max > 0) {
                spell_mut.uses_remaining = std::max(0, spell_mut.uses_remaining - 1);
            }
        } else {
            log_("[DEBUG execute_spell] Player branch taken for agent {}", action.caster_idx);
            // Player: decrement spell slot (if not a cantrip)
            int slot_level = action.slot_level > 0 ? action.slot_level : sp.level;
            log_("[DEBUG execute_spell] Calculated slot_level={}, checking if > 0 and <= 9", slot_level);
            if (slot_level > 0 && slot_level <= 9) {
                auto& slots = stats.spell_slots_remaining;
                slots[static_cast<std::size_t>(slot_level - 1)] =
                    std::max(0, slots[static_cast<std::size_t>(slot_level - 1)] - 1);

                // Wizard Diviner L6: Expert Divination
                // Cast Divination spell with L2+ slot → regain highest-level lower-level slot (max L5)
                log_("[EXPERT DIVINATION DEBUG] Spell: {}, School: {}, IsWizard: {}, IsDiviner: {}, IsL2Plus: {}",
                     spell_mut.name, static_cast<int>(spell_mut.school),
                     (stats.character_class == Wizard ? 1 : 0),
                     (stats.wizard_subclass == DivinierPath ? 1 : 0),
                     (slot_level >= 2 ? 1 : 0));
                log_("[EXPERT DIVINATION DEBUG] Spell::Divination value: {}, Match: {}",
                     static_cast<int>(Spell::Divination), (spell_mut.school == Spell::Divination ? 1 : 0));

                if (stats.character_class == Wizard && stats.wizard_subclass == DivinierPath &&
                    spell_mut.school == Spell::Divination && slot_level >= 2) {
                    log_("[EXPERT DIVINATION] Restoring spell slot for spell: {}", spell_mut.name);
                    // Find highest expended lower-level slot (capped at L5)
                    int restore_level = -1;
                    for (int lvl = std::min(5, slot_level - 1); lvl >= 1; --lvl) {
                        if (slots[static_cast<std::size_t>(lvl - 1)] <
                            stats.spell_slots_max[static_cast<std::size_t>(lvl - 1)]) {
                            restore_level = lvl;
                            break;
                        }
                    }
                    if (restore_level > 0) {
                        slots[static_cast<std::size_t>(restore_level - 1)]++;
                        log_("{} Expert Divination: restored 1 level {} spell slot", agentName(bm, action.caster_idx), restore_level);
                    }
                }

                // Wizard Abjurer L3+: Arcane Ward auto-charging
                // Cast abjuration spell → Ward gains 2 × spell slot level (capped at max)
                if (stats.character_class == Wizard && stats.wizard_subclass == AbjurerPath &&
                    stats.char_level >= 3 && spell_mut.school == Spell::Abjuration) {
                    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
                    int ward_gain = 2 * slot_level;
                    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);
                    log_("{} Arcane Ward charged: +{} HP ({}/{})", agentName(bm, action.caster_idx), ward_gain, stats.temp_hp, max_ward);
                }
            }
        }

        // Persist stats back to battle map after modifications
        bm.setAgentStats(action.caster_idx, stats);
    }

    return result;
}

std::vector<int> CombatEngine::availableCastableSpells(
        const BattleMap& bm, int agent_idx) const
{
    std::vector<int> result;
    const auto& agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return result;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    const auto& spells = pa.spells;

    for (size_t i = 0; i < spells.size(); ++i) {
        const Spell& spell = spells[i];

        // Class feature: castable iff its named resource has enough charges.
        if (!spell.resource_name.empty()) {
            const Resource* res = stats.getResource(spell.resource_name);
            if (res && res->current >= std::max(1, spell.resource_cost))
                result.push_back(static_cast<int>(i));
            continue;
        }

        // Cantrips (level 0) are always available
        if (spell.level == 0) {
            result.push_back(static_cast<int>(i));
            continue;
        }

        // Check leveled spell per-turn rule
        if (!stats.canCastLeveledSpell()) {
            continue;  // Already cast a leveled spell this turn
        }

        if (stats.is_npc) {
            // NPC: need remaining uses
            if (spell.uses_max > 0 && spell.uses_remaining > 0) {
                result.push_back(static_cast<int>(i));
            }
        } else {
            // Player: need a spell slot at spell.level or higher
            bool hasSlot = false;
            for (int lvl = spell.level; lvl <= 9; ++lvl) {
                if (stats.spell_slots_remaining[static_cast<size_t>(lvl - 1)] > 0) {
                    hasSlot = true;
                    break;
                }
            }
            if (hasSlot) {
                result.push_back(static_cast<int>(i));
            }
        }
    }

    return result;
}

int CombatEngine::getNumTargetsForSpell(const Spell& sp, int slot_level,
                                        int caster_level) const noexcept
{
    // Eldritch Blast beams scale with CHARACTER level (cantrip), not slot level.
    if (sp.name == "Eldritch Blast" && caster_level >= 0) {
        int beams = 1;
        if (caster_level >= 5)  ++beams;
        if (caster_level >= 11) ++beams;
        if (caster_level >= 17) ++beams;
        return beams;
    }

    // For Multiple geometry spells, calculate targets based on upcast level
    if (sp.geometry != Spell::Multiple) {
        return (sp.geometry == Spell::Single) ? 1 : 0;
    }

    // Multiple geometry: num_targets + (slot_level - spell.level) * targets_per_upcast_level
    int num_targets = sp.num_targets;
    if (slot_level > 0 && slot_level > sp.level) {
        num_targets += (slot_level - sp.level) * sp.targets_per_upcast_level;
    }
    return std::max(1, num_targets);  // Always at least 1 target
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

// ─────────────────────────────────────────────────────────────────────────────
//  Spell effects & zones
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applySpellEffect(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return;

    Agent::Stats target_stats = bm.getAgentStats(target_idx);
    const Spell& sp = effect.spell;

    // Save-for-half: a damaging zone with a Save attack type lets the target make a
    // saving throw each time the effect is applied (half damage on success).
    const bool do_save = (sp.attack_type == Spell::Save && sp.type != Spell::Heal);
    bool saved = false;
    if (do_save) {
        const Agent& tgt = *agents[static_cast<std::size_t>(target_idx)].agent;
        const Agent::Conditions& tc = tgt.getConditions();

        // Auto-fail STR/DEX saves while paralyzed/stunned/unconscious.
        const bool auto_fail = (tc.paralyzed || tc.stunned || tc.unconscious) &&
                               (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

        bool adv = tgt.hasAdvantage();
        bool dis = tgt.hasDisadvantage();
        // Barbarian Danger Sense (L2+): advantage on DEX saves unless incapacitated.
        if (sp.save_ability == SaveDex && !tc.incapacitated &&
            target_stats.character_class == CharacterClass::Barbarian && target_stats.char_level >= 2)
            adv = true;

        int save_d20;
        if (auto_fail)       save_d20 = 1;
        else if (adv && dis) save_d20 = roll(20);
        else if (adv)        save_d20 = rollAdvantage(20);
        else if (dis)        save_d20 = rollDisadvantage(20);
        else                 save_d20 = roll(20);

        auto saveMod = [&](SaveAbility_t ab) -> int {
            int score = 0; bool prof = false;
            switch (ab) {
                case SaveStr: score = target_stats.str;   prof = target_stats.save_prof_str;   break;
                case SaveDex: score = target_stats.dex;   prof = target_stats.save_prof_dex;   break;
                case SaveCon: score = target_stats.con;   prof = target_stats.save_prof_con;   break;
                case SaveInt: score = target_stats.intel; prof = target_stats.save_prof_intel; break;
                case SaveWis: score = target_stats.wis;   prof = target_stats.save_prof_wis;   break;
                default:      score = target_stats.cha;   prof = target_stats.save_prof_cha;   break;
            }
            int m = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --m;
            return m + (prof ? target_stats.prof_bonus : 0);
        };

        int dc = 0;
        if (effect.caster_idx >= 0 && static_cast<std::size_t>(effect.caster_idx) < agents.size())
            dc = spellSaveDcFromAbility(bm.getAgentStats(effect.caster_idx), sp.save_ability);
        saved = !auto_fail && (save_d20 + saveMod(sp.save_ability) >= dc);
    }

    // Calculate total by rolling all damage types and applying multipliers (then halving on a save).
    int total = 0;
    for (const auto& roll_info : sp.magic_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) type_damage += roll(roll_info.die_size);
        type_damage += roll_info.bonus;
        float multiplier = target_stats.magic_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }
    for (const auto& roll_info : sp.physical_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) type_damage += roll(roll_info.die_size);
        type_damage += roll_info.bonus;
        float multiplier = target_stats.physical_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }

    // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
    if (do_save && sp.save_ability == SaveDex &&
        target_stats.character_class == CharacterClass::Rogue && target_stats.char_level >= 7 &&
        !agents[static_cast<std::size_t>(target_idx)].agent->getConditions().incapacitated) {
        total = saved ? 0 : (total / 2);
    }

    // Log the effect
    const char* verb = (sp.type == Spell::Heal) ? "healed" : "took";
    if (do_save)
        log_("{} {} {} from {} ({} save)", agents[static_cast<std::size_t>(target_idx)].agent->name(),
             verb, total, sp.name, saved ? "made" : "failed");
    else
        log_("{} {} {} from {}", agents[static_cast<std::size_t>(target_idx)].agent->name(), verb, total, sp.name);

    // Apply damage or healing
    if (sp.type == Spell::Heal) {
        healAgent(bm, target_idx, total);
    } else {
        damageAgent(bm, target_idx, total);
        processDamageTaken(bm, target_idx, total);  // zone damage ends/triggers on-damage conditions
    }
}

bool CombatEngine::applyZoneIfNewThisTurn(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const int64_t key = (static_cast<int64_t>(effect.effect_id) << 32)
                      ^ static_cast<int64_t>(static_cast<uint32_t>(target_idx));
    auto it = zoneAppliedTurn_.find(key);
    if (it != zoneAppliedTurn_.end() && it->second == turnCounter_)
        return false;  // already applied to this target by this effect this turn
    applySpellEffect(bm, effect, target_idx);
    zoneAppliedTurn_[key] = turnCounter_;
    return true;
}

// Re-center any persistent Sphere effects anchored to this agent on their current
// position. Called when the agent moves and at the start of their turn so an
// Emanation (e.g. Spirit Guardians) tracks the caster.
void CombatEngine::recomputeAnchoredEffects(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;
    const Cell origin = agents[static_cast<std::size_t>(agent_idx)].origin;

    std::vector<std::pair<int, int>> to_update;  // (effect_id, radius_ft)
    for (const auto& eff : bm.activeSpellEffects())
        if (eff.anchor_agent_idx == agent_idx)
            to_update.emplace_back(eff.effect_id, eff.spell.radius);

    for (const auto& [id, radius] : to_update)
        bm.setSpellEffectCells(id, sphereCellsAround(origin.col, origin.row, radius));
}

void CombatEngine::tickEffects(BattleMap& bm)
{
    auto agents = bm.placedAgents();
    for (auto& fx : activeEffects_) {
        if (fx.turns_remaining <= 0) continue;
        --fx.turns_remaining;

        if (fx.target_idx < 0 || fx.target_idx >= static_cast<int>(agents.size())) continue;
        Agent::Stats s = bm.getAgentStats(fx.target_idx);

        std::vector<int> dice;
        int total = 0;

        // Roll per-damage-type damage
        // Roll per-damage-type damage and apply target's multipliers
        for (const auto& roll_info : fx.spell.magic_damage_rolls) {
            int type_damage = 0;
            for (int i = 0; i < roll_info.num_dice; ++i) {
                int d = roll(roll_info.die_size);
                dice.push_back(d);
                type_damage += d;
            }
            // Apply target's resistance/vulnerability/immunity multiplier
            float multiplier = s.magic_damage_multipliers[roll_info.type];
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }
        for (const auto& roll_info : fx.spell.physical_damage_rolls) {
            int type_damage = 0;
            for (int i = 0; i < roll_info.num_dice; ++i) {
                int d = roll(roll_info.die_size);
                dice.push_back(d);
                type_damage += d;
            }
            // Apply target's resistance/vulnerability/immunity multiplier
            float multiplier = s.physical_damage_multipliers[roll_info.type];
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }

        if (fx.spell.type == Spell::Heal)
            s.hp_cur = std::min(s.hp_max, s.hp_cur + std::max(0, total));
        else {
            int damage = std::max(0, total);
            // Temporary HP absorbs damage first, then overflow damages hp_cur
            int overflow = std::max(0, damage - s.temp_hp);
            s.temp_hp = std::max(0, s.temp_hp - damage);
            s.hp_cur = std::max(0, s.hp_cur - overflow);
        }

        bm.setAgentStats(fx.target_idx, s);
        if (fx.spell.type != Spell::Heal)
            processDamageTaken(bm, fx.target_idx, std::max(0, total));
    }

    auto expired = [](const ActiveEffect& fx) { return fx.turns_remaining <= 0; };
    activeEffects_.erase(
        std::remove_if(activeEffects_.begin(), activeEffects_.end(), expired),
        activeEffects_.end());
}

const std::vector<ActiveEffect>& CombatEngine::activeEffects() const noexcept
{
    return activeEffects_;
}

void CombatEngine::clearEffects() noexcept
{
    activeEffects_.clear();
    zoneAppliedTurn_.clear();
    turnCounter_ = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Concentration
// ─────────────────────────────────────────────────────────────────────────────

ConcentrationSaveResult CombatEngine::concentrationSave(
        BattleMap& bm, int agent_idx, int damage_taken)
{
    ConcentrationSaveResult r;
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating) return r;

    r.checked    = true;
    r.spell_name = cond.concentrating_on;
    r.save_dc    = std::max(10, damage_taken / 2);

    // Apply advantage/disadvantage from agent conditions
    bool has_adv = cond.has_advantage;
    {
        Agent::Stats cs = bm.getAgentStats(agent_idx);
        if (cs.character_class == CharacterClass::Warlock && cs.hasInvocation(3))
            has_adv = true;  // Eldritch Mind
    }
    bool has_dis = cond.has_disadvantage;
    int save_d20;
    if (has_adv && has_dis) {
        save_d20 = roll(20);  // Cancel out
    } else if (has_adv) {
        save_d20 = rollAdvantage(20);
    } else if (has_dis) {
        save_d20 = rollDisadvantage(20);
    } else {
        save_d20 = roll(20);
    }
    r.save_d20   = save_d20;

    Agent::Stats s = bm.getAgentStats(agent_idx);
    int con_mod = (s.con - 10) / 2;
    if (s.con < 10 && (s.con - 10) % 2 != 0) --con_mod;
    con_mod += s.save_prof_con ? s.prof_bonus : 0;
    r.con_mod = con_mod;
    r.passed  = (r.save_d20 + con_mod >= r.save_dc);

    if (!r.passed) {
        r.concentration_lost  = true;
        cond.concentrating    = false;
        cond.concentrating_on = {};
        bm.setAgentConditions(agent_idx, cond);
    }
    return r;
}

bool CombatEngine::checkConcentrationOnDamage(BattleMap& bm, int target_idx, int damage) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(target_idx)];
    const Agent::Conditions& cond = pa.agent->getConditions();
    if (!cond.concentrating)
        return false;  // Not concentrating, no save needed

    // DC is 10 or half damage, whichever is higher
    int dc = std::max(10, damage / 2);
    const Agent::Stats& cstats = pa.agent->getStats();
    int con_mod = (cstats.con - 10) / 2;
    if (cstats.con < 10 && (cstats.con - 10) % 2 != 0) --con_mod;  // floor for odd negative scores
    if (cstats.save_prof_con) con_mod += cstats.prof_bonus;       // CON save proficiency
    int save_roll = roll(20);
    int save_total = save_roll + con_mod;

    if (save_total >= dc) {
        log_("Concentration save: {} rolled {} + {} = {} vs DC {} — HELD",
             pa.agent->name(), save_roll, con_mod, save_total, dc);
        return false;  // Save succeeded
    }

    log_("Concentration save: {} rolled {} + {} = {} vs DC {} — BROKEN",
         pa.agent->name(), save_roll, con_mod, save_total, dc);

    // Concentration lost — fully drop it (terrain + spell effects + spell-applied conditions + flags).
    (void)dropConcentration(bm, target_idx);
    return true;  // Concentration was lost
}

DropConcentrationResult CombatEngine::dropConcentration(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return {};
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating)
        return {};

    DropConcentrationResult result;
    result.dropped    = true;
    result.spell_name = cond.concentrating_on;

    // 1. Remove this caster's concentration terrain only (leave non-concentration
    //    timed terrain, e.g. Grease, which is not a concentration spell in 5e).
    for (const auto& eff : bm.activeTerrainEffects()) {
        if (eff.source_agent_idx == agent_idx && eff.requires_concentration)
            result.removed_terrain_ids.push_back(eff.id);
    }
    for (int tid : result.removed_terrain_ids)
        bm.removeTerrainEffect(tid);

    // 2. Remove this caster's concentration spell-effects only
    for (const auto& eff : bm.activeSpellEffects()) {
        if (eff.caster_idx == agent_idx && eff.spell.requires_concentration)
            result.removed_spell_effect_ids.push_back(eff.effect_id);
    }
    for (int eid : result.removed_spell_effect_ids)
        bm.removeSpellEffect(eid);

    // 3. Remove conditions applied by this agent's concentration spells
    const auto& spells = bm.getAgentSpells(agent_idx);
    for (const auto& ac : activeAgentConditions_) {
        if (ac.caster_idx == agent_idx &&
            ac.spell_idx >= 0 && ac.spell_idx < static_cast<int>(spells.size()) &&
            spells[static_cast<std::size_t>(ac.spell_idx)].requires_concentration)
            result.removed_condition_ids.push_back(ac.condition_id);
    }
    for (int cid : result.removed_condition_ids)
        removeAgentCondition(cid);

    // 4. Clear C++ concentration state
    cond.concentrating    = false;
    cond.concentrating_on = {};
    bm.setAgentConditions(agent_idx, cond);

    return result;
}

void CombatEngine::clearAllConcentration(BattleMap& bm)
{
    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
        if (bm.getAgentConditions(i).concentrating)
            (void)dropConcentration(bm, i);  // cascades: terrain + spell effects + conditions + flag
    }
}

void CombatEngine::clearSpellConditionEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();
    if (cond.agent_idx < 0 || cond.agent_idx >= static_cast<int>(agents.size())) return;
    Agent::Conditions ac = bm.getAgentConditions(cond.agent_idx);
    const std::string& n = cond.condition_name;
    if      (n == "Paralyzed")     { ac.paralyzed = false; ac.incapacitated = false; }
    else if (n == "Blinded")       { ac.blinded = false; }
    else if (n == "Incapacitated") { ac.incapacitated = false; }
    else if (n == "Stunned")       { ac.stunned = false; ac.incapacitated = false; }
    else if (n == "Charmed")       { ac.charmed = false; }
    else if (n == "Frightened")    { ac.frightened = false; }
    else if (n == "Unconscious")   { ac.unconscious = false; ac.incapacitated = false; }
    else if (n == "Prone")         { ac.prone = false; }
    bm.setAgentConditions(cond.agent_idx, ac);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Slots
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::createSpellSlot(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    // Font of Magic creates only level 1-5 slots.
    if (slot_level < 1 || slot_level > 5) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return -1;

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

int CombatEngine::convertSlotToSorceryPoints(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return -1;

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

int CombatEngine::sorcererBendLuck(BattleMap& bm, int idx, bool boost) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 6) {
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
    pending_roll_bonus_ = boost ? value : -value;        // bonus or penalty to the next D20 Test
    bm.setAgentStats(idx, stats);

    log_("{} uses Bend Luck: {}{} to the next D20 Test ({} Sorcery Points left)",
         agentName(bm, idx), boost ? "+" : "-", value, sp->current);
    return value;
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

WildMagicSurgeResult CombatEngine::rollWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    WildMagicSurgeResult res;
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return res;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 3) {
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

bool CombatEngine::applyWildMagicSurgeEffect(BattleMap& bm, int idx, int effect) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    if (effect == 1) {  // "Plant Growth sprouts around your feet" — cast Plant Growth on the caster.
        Cell origin = agents[static_cast<std::size_t>(idx)].origin;
        auto cells = sphereCellsAround(origin.col, origin.row, 10);  // 10-ft radius sphere
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
            // "Unarmed" is the default empty-slot weapon — only real weapons drop.
            if (!w.name.empty() && w.name != "Unarmed") {
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

bool CombatEngine::expendArcaneWardSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Validate: Abjurer L3+ with active ward
    if (stats.character_class != Wizard || stats.wizard_subclass != AbjurerPath ||
        stats.char_level < 3 || stats.temp_hp <= 0) {
        return false;
    }

    // Validate: slot_level is valid (1-9)
    if (slot_level < 1 || slot_level > 9) return false;

    // Validate: agent has remaining spell slot at this level
    if (stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)] <= 0) {
        return false;
    }

    // Expend the slot
    stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)]--;

    // Charge the ward
    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
    int ward_gain = 2 * slot_level;
    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends Level {} slot, Arcane Ward now {}/{}",
         agentName(bm, agent_idx), slot_level, stats.temp_hp, max_ward);

    return true;
}

} // namespace rpg
