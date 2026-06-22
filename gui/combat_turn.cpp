// ─────────────────────────────────────────────────────────────────────────────
//  combat_turn.cpp  –  CombatEngine turn flow & initiative
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The turn-flow half of the action economy: initiative, per-turn start/end
//  bookkeeping (death saves, condition saves, movement-budget seeding, begin/end
//  spell effects), round execution, and standalone death saves.
//  Sections:
//    · Initiative      — rollInitiative
//    · Turn start/end  — beginTurn, endTurn
//    · Round execution — runRound
//    · Death saves     — rollDeathSave
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <format>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Initiative
// ─────────────────────────────────────────────────────────────────────────────

std::vector<InitiativeEntry> CombatEngine::rollInitiative(const BattleMap& bm)
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());

    std::vector<InitiativeEntry> entries;
    entries.reserve(static_cast<std::size_t>(n));

    for (int i = 0; i < n; ++i) {
        if (agents[static_cast<std::size_t>(i)].on_deck) continue;  // reserve: deployed later by the DM
        const Agent::Stats& s = bm.getAgentStats(i);
        if (s.hp_cur <= 0) continue;   // dead / incapacitated before combat starts

        InitiativeEntry e;
        e.agent_idx = i;
        // Roll Initiative at Advantage: Feral Instinct (Barbarian L7) or Assassinate (Assassin Rogue L3+).
        if ((s.character_class == CharacterClass::Barbarian && s.char_level >= 7) ||
            (s.character_class == CharacterClass::Rogue &&
             s.rogue_subclass == AssassinPath && s.char_level >= 3)) {
            e.d20 = std::max(roll(20), roll(20));
        } else {
            e.d20 = roll(20);
        }
        e.modifier  = s.initiativeModifier();
        e.total     = e.d20 + e.modifier;
        entries.push_back(e);
    }

    // Sort descending: total first, then modifier (higher DEX breaks ties),
    // then agent_idx ascending (stable, deterministic final tiebreaker).
    std::sort(entries.begin(), entries.end(), [](const InitiativeEntry& a,
                                                  const InitiativeEntry& b) {
        if (a.total    != b.total)    return a.total    > b.total;
        if (a.modifier != b.modifier) return a.modifier > b.modifier;
        return a.agent_idx < b.agent_idx;
    });

    return entries;
}

// Roll a single Initiative entry for one agent. Used when the DM deploys an on-deck
// reinforcement group mid-combat: every member of a spawn shares one roll (the
// "same type → same initiative" rule), so the GUI rolls once via this and copies the
// total onto each member. Mirrors the per-agent logic in rollInitiative (Feral
// Instinct advantage, Diviner-aware roll()).
InitiativeEntry CombatEngine::rollInitiativeFor(const BattleMap& bm, int agent_idx)
{
    InitiativeEntry e;
    e.agent_idx = agent_idx;
    const auto agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return e;
    Agent::Stats s = bm.getAgentStats(agent_idx);
    if ((s.character_class == CharacterClass::Barbarian && s.char_level >= 7) ||
        (s.character_class == CharacterClass::Rogue &&
         s.rogue_subclass == AssassinPath && s.char_level >= 3))
        e.d20 = std::max(roll(20), roll(20));
    else
        e.d20 = roll(20);
    e.modifier = s.initiativeModifier();
    e.total    = e.d20 + e.modifier;

    // ── Monk L15 Perfect Focus: regain focus on initiative if below max ────────
    if (s.character_class == CharacterClass::Monk && s.char_level >= 15) {
      auto fp_res = s.resources.find("Focus Points");
      if (fp_res != s.resources.end() && fp_res->second.current < fp_res->second.max) {
        int regain = 1;  // Regain 1 Focus Point
        fp_res->second.current = std::min(fp_res->second.max, fp_res->second.current + regain);
        s.resources["Focus Points"] = fp_res->second;
        const_cast<BattleMap&>(bm).setAgentStats(agent_idx, s);
        log_("{} regains 1 Focus Point (Perfect Focus)", agentName(bm, agent_idx));
      }
    }

    return e;
}

// Alert (Origin feat) — Initiative Swap: exchange the Initiative totals of two agents
// (e.g. the Alert character and a willing ally) and re-sort the order. No-op if either
// agent_idx is missing from `order` or the two indices are equal.
std::vector<InitiativeEntry> CombatEngine::swapInitiative(std::vector<InitiativeEntry> order,
                                                          int agent_a, int agent_b) const
{
    if (agent_a == agent_b) return order;
    InitiativeEntry* ea = nullptr;
    InitiativeEntry* eb = nullptr;
    for (auto& e : order) {
        if (e.agent_idx == agent_a) ea = &e;
        if (e.agent_idx == agent_b) eb = &e;
    }
    if (!ea || !eb) return order;
    // Swap the rolled Initiative (total + its d20 component) so the two agents trade
    // turn-order slots. The DEX modifier stays with each agent (used only as a tiebreaker).
    std::swap(ea->total, eb->total);
    std::swap(ea->d20,   eb->d20);
    std::sort(order.begin(), order.end(), [](const InitiativeEntry& a,
                                             const InitiativeEntry& b) {
        if (a.total    != b.total)    return a.total    > b.total;
        if (a.modifier != b.modifier) return a.modifier > b.modifier;
        return a.agent_idx < b.agent_idx;
    });
    return order;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Turn start / end
// ─────────────────────────────────────────────────────────────────────────────

TurnStartResult CombatEngine::beginTurn(BattleMap& bm, int agent_idx) noexcept
{
    TurnStartResult result;

    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return result;

    // New turn: advance the counter used for persistent-zone "once per turn" dedup.
    ++turnCounter_;

    auto agent_name = agentName(bm, agent_idx);
    // Reset slip distance counter and slipped flag for the new turn
    slipDistanceMoved_[agent_idx] = 0;
    agents[static_cast<std::size_t>(agent_idx)].agent->setSlippedThisTurn(false);

    // General feats — expire enhanced-crit marks that this agent set on a victim "until the start
    // of your next turn" (Crusher: attackers Advantage vs victim; Slasher: victim's attacks at
    // Disadvantage). The mark lives on the victim with *_marked_by == this agent, so clear it here.
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        Agent::Conditions c = bm.getAgentConditions(i);
        bool dirty = false;
        if (c.crusher_marked && c.crusher_marked_by == agent_idx) {
            c.crusher_marked = false; c.crusher_marked_by = -1; dirty = true;
        }
        if (c.slasher_marked && c.slasher_marked_by == agent_idx) {
            c.slasher_marked = false; c.slasher_marked_by = -1; dirty = true;
        }
        // Battle Master maneuvers that last "until the end of your next turn" — the mark lives on
        // the victim tagged with the maneuvering Fighter's index, so expire it as that Fighter's
        // turn begins (Goading Attack, Distracting Strike, Disarming Attack).
        if (c.goaded_by == agent_idx)     { c.goaded_by = -1;                       dirty = true; }
        if (c.distracted_by == agent_idx) { c.distracted_by = -1;                   dirty = true; }
        if (c.disarmed && c.disarmed_by == agent_idx) {
            c.disarmed = false; c.disarmed_by = -1;                                 dirty = true;
        }
        // Zealot Zealous Presence — the Advantage buff lasts "until the start of the granting
        // Zealot's next turn", so expire it as that Zealot's turn begins (tagged on each ally).
        if (c.zealous_blessing && c.zealous_blessing_by == agent_idx) {
            c.zealous_blessing = false; c.zealous_blessing_by = -1;                 dirty = true;
        }
        if (dirty) bm.setAgentConditions(i, c);
    }

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    auto stats = agent.agent->getStats();

    // Mark that this agent has now taken a turn in the current combat. Drives the Assassin's
    // Assassinate Advantage (vs creatures that haven't acted yet). Per-combat marker reset at
    // combat start (GUI _start_combat); never cleared in Agent::turn().
    {
        Agent::Conditions tc = bm.getAgentConditions(agent_idx);
        if (!tc.has_taken_turn_this_combat) {
            tc.has_taken_turn_this_combat = true;
            bm.setAgentConditions(agent_idx, tc);
        }
    }

    // Paladin Oath of Devotion — Sacred Weapon: tick down its 1-minute (10-round) duration.
    // Persisted immediately so the rest of this turn (and the GUI) sees the updated count.
    if (stats.sacred_weapon_turns > 0) {
        --stats.sacred_weapon_turns;
        if (stats.sacred_weapon_turns == 0) stats.sacred_weapon_bonus = 0;
        bm.setAgentStats(agent_idx, stats);
    }

    // Cleric Light Domain — Corona of Light: tick down its 1-minute (10-round) duration.
    if (stats.corona_of_light_turns > 0) {
        --stats.corona_of_light_turns;
        bm.setAgentStats(agent_idx, stats);
    }

    // Bard College of Glamour — Mantle of Majesty: tick down the 1-minute (10-round) "unearthly
    // appearance" window. When it expires, also drop the Concentration that holds it.
    if (stats.mantle_majesty_turns > 0) {
        --stats.mantle_majesty_turns;
        bm.setAgentStats(agent_idx, stats);
        if (stats.mantle_majesty_turns == 0) {
            Agent::Conditions mc = bm.getAgentConditions(agent_idx);
            if (mc.concentrating && mc.concentrating_on == "Mantle of Majesty") {
                mc.concentrating    = false;
                mc.concentrating_on = {};
                bm.setAgentConditions(agent_idx, mc);
            }
            log_("{}'s unearthly appearance fades (Mantle of Majesty ends)", agent_name);
        }
    }

    // Bard College of Glamour — Unbreakable Majesty: tick down the 1-minute (10-round) "majestic
    // presence" window. Reset the per-turn gate. When it expires, also drop the Concentration.
    if (stats.majestic_presence_turns > 0) {
        --stats.majestic_presence_turns;
        stats.majesty_checked_this_turn = false;  // reset gate for the new turn
        bm.setAgentStats(agent_idx, stats);
        if (stats.majestic_presence_turns == 0) {
            Agent::Conditions mc = bm.getAgentConditions(agent_idx);
            if (mc.concentrating && mc.concentrating_on == "Unbreakable Majesty") {
                mc.concentrating    = false;
                mc.concentrating_on = {};
                bm.setAgentConditions(agent_idx, mc);
            }
            log_("{}'s majestic presence fades (Unbreakable Majesty ends)", agent_name);
        }
    }

    // Sorcerer Innate Sorcery: tick down its 1-minute (10-round) duration.
    if (stats.innate_sorcery_turns > 0) {
        --stats.innate_sorcery_turns;
        bm.setAgentStats(agent_idx, stats);
    }

    // Wild Magic Surge — spectral shield (band 2): tick down; remove the +2 AC on expiry.
    if (stats.wild_magic_shield_turns > 0) {
        --stats.wild_magic_shield_turns;
        if (stats.wild_magic_shield_turns == 0) stats.ac_temporary_modifications -= 2;
        bm.setAgentStats(agent_idx, stats);
    }

    // Shield spell: the +5 AC lasts "until the start of your next turn" — remove it here.
    if (stats.shield_active) {
        stats.shield_active = false;
        stats.ac_temporary_modifications -= 5;
        bm.setAgentStats(agent_idx, stats);
    }

    // Wild Magic Surge — vitality (band 3): regain 5 HP at the start of each of your turns.
    if (stats.wild_magic_regen_turns > 0 && stats.hp_cur > 0) {
        stats.hp_cur = std::min(stats.hp_max, stats.hp_cur + 5);
        --stats.wild_magic_regen_turns;
        bm.setAgentStats(agent_idx, stats);
        log_("{} regains 5 HP (Wild Magic vitality) → {}/{}", agent_name, stats.hp_cur, stats.hp_max);
    }

    // Wild Magic Surge — bonus-action casting (band 6) and teleport-as-bonus (band 10):
    // tick down their 1-minute (10-round) windows (the GUI enforces the actual benefit).
    if (stats.wild_magic_bonus_cast_turns > 0) {
        --stats.wild_magic_bonus_cast_turns;
        bm.setAgentStats(agent_idx, stats);
    }
    if (stats.wild_magic_teleport_bonus_turns > 0) {
        --stats.wild_magic_teleport_bonus_turns;
        bm.setAgentStats(agent_idx, stats);
    }

    // Fiendish Vigor invocation (code 6): the Warlock keeps False Life up (free, no
    // slot) and auto-maxes the dice (2d4 + 4 = 12 temp HP). Granted once, the first
    // time this Warlock begins a turn in the combat (the pre-buff is "already up").
    if (stats.character_class == CharacterClass::Warlock && stats.hasInvocation(6) &&
        !stats.fiendish_vigor_applied) {
        stats.fiendish_vigor_applied = true;
        if (stats.temp_hp < 12) stats.temp_hp = 12;
        bm.setAgentStats(agent_idx, stats);
        log_("{} gains 12 temporary HP (Fiendish Vigor — max False Life)", agent_name);
    }

    // Death from Exhaustion: agent dies at exhaustion level 6
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);

    // Reset per-turn Barbarian flags at start of each turn
    cond.reckless_attack = false;
    cond.reckless_reroll_available = false;

    if (cond.exhaustion_level >= 6 && stats.hp_cur > 0) {
        stats.hp_cur = 0;
        cond.dead = true;
        cond.unconscious = true;
        bm.setAgentStats(agent_idx, stats);
        bm.setAgentConditions(agent_idx, cond);
        log_("{} dies from Exhaustion Level 6", agent_name);
        result.save_roll_message = "DEATH: Exhaustion Level 6";
        return result;
    }

    // Vampire Sunlight Vulnerability: vampires take 20 radiant damage at the start
    // of their turn if they're in Sunlight (VisibilityLevel::Sunlight).
    // They also receive disadvantage on all attack rolls. 
    if (stats.is_vampire && stats.hp_cur > 0) {
        int cell_index = agent.origin.row * bm.gridCols() + agent.origin.col;
        const auto& light_effects = bm.activeLightEffects();
        for (const auto& effect : light_effects) {
            if (effect.light_level == VisibilityLevel::Sunlight) {
                // Check if this agent's origin cell is in the Sunlight effect
                if (std::find(effect.cell_indices.begin(), effect.cell_indices.end(),
                              cell_index) != effect.cell_indices.end()) {
                    // Deal 20 radiant damage
                    stats.hp_cur = std::max(0, stats.hp_cur - 20);
		    cond.has_disadvantage = true;
                    bm.setAgentStats(agent_idx, stats);
		    bm.setAgentConditions(agent_idx, cond);
                    log_("{} takes 20 radiant damage from Sunlight exposure → {}/{}", agent_name,
                         stats.hp_cur, stats.hp_max);
                    if (stats.hp_cur == 0) {
                        cond.dead = true;
                        cond.unconscious = true;
                        bm.setAgentConditions(agent_idx, cond);
                        log_("{} dies from Sunlight exposure", agent_name);
                        result.save_roll_message = "Sunlight Exposure: Death";
                        return result;
                    }
                    break;  // Only take damage once per turn
                }
		// If the vampire didn't start in sunlight, clear the disadvantage flag. 
		else {
		  cond.has_disadvantage = false;     // This should NOT clear "sap" disadvantage. 
		  bm.setAgentConditions(agent_idx, cond); 
		}
            }
        }
    }

    // ── Monk Phase 0: Turn-start features ───────────────────────────────────────
    // L2 Uncanny Metabolism: restore all Focus Points + heal once per combat
    if (stats.character_class == CharacterClass::Monk && stats.char_level >= 2 &&
        !cond.uncanny_metabolism_used_this_combat) {
      auto fp_res = stats.resources.find("Focus Points");
      if (fp_res != stats.resources.end()) {
        int max_fp = fp_res->second.max;
        fp_res->second.current = max_fp;
        stats.resources["Focus Points"] = fp_res->second;
        cond.uncanny_metabolism_used_this_combat = true;
        bm.setAgentStats(agent_idx, stats);
        log_("{} restores all Focus Points (Uncanny Metabolism)", agent_name);
      }
    }

    // L10 Self-Restoration: remove Charmed/Frightened/Poisoned at turn start
    if (stats.character_class == CharacterClass::Monk && stats.char_level >= 10) {
      bool restored = false;
      if (cond.charmed) {
        cond.charmed = false;
        cond.charmed_by = -1;
        log_("{} ends the Charmed condition (Self-Restoration)", agent_name);
        restored = true;
      }
      if (cond.frightened) {
        cond.frightened = false;
        log_("{} ends the Frightened condition (Self-Restoration)", agent_name);
        restored = true;
      }
      if (cond.poisoned) {
        cond.poisoned = false;
        log_("{} ends the Poisoned condition (Self-Restoration)", agent_name);
        restored = true;
      }
      if (restored) {
        bm.setAgentConditions(agent_idx, cond);
      }
    }

    // Death saves: roll CON save DC 10 if unconscious at 0 HP
    if (cond.unconscious && stats.hp_cur <= 0 && !cond.stabilized && !cond.dead) {
        int con_mod = (stats.con - 10) / 2;
        if (stats.con < 10 && (stats.con - 10) % 2 != 0) --con_mod;
        int death_d20 = roll(20);
        // Durable (general feat) — Defy Death: Advantage on Death Saving Throws (take the higher d20).
        if (stats.hasFeat("Durable")) death_d20 = std::max(death_d20, roll(20));
        int death_total = death_d20 + con_mod;

        if (death_d20 == 20) {
            // Natural 20: auto-stabilize
            cond.stabilized = true;
            cond.death_save_successes = 3;  // Mark as stabilized
            bm.setAgentConditions(agent_idx, cond);
            log_("Death save: NATURAL 20! Character automatically stabilizes");
            result.save_roll_message = "Death Save: Natural 20! Automatically stabilized!";
        } else if (death_d20 == 1) {
            // Natural 1: 2 failures
            cond.death_save_failures += 2;
            if (cond.death_save_failures >= 3) {
                cond.dead = true;
                log_("Death save: NATURAL 1! Character dies");
                result.save_roll_message = "Death Save: Natural 1! Character dies!";
            } else {
                log_("Death save: Natural 1 (2 failures) — {} failures total", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Natural 1 (2 failures) — {}/3 failures", cond.death_save_failures);
            }
            bm.setAgentConditions(agent_idx, cond);
        } else if (death_total >= 10) {
            // Success
            cond.death_save_successes++;
            if (cond.death_save_successes >= 3) {
                cond.stabilized = true;
                log_("Death save: SUCCESS (stabilized) — {}/3 successes", cond.death_save_successes);
                result.save_roll_message = std::format("Death Save: Success! Stabilized ({}/3 successes)", cond.death_save_successes);
            } else {
                log_("Death save: SUCCESS — {}/3 successes", cond.death_save_successes);
                result.save_roll_message = std::format("Death Save: Success ({}/3 successes)", cond.death_save_successes);
            }
            bm.setAgentConditions(agent_idx, cond);
        } else {
            // Failure
            cond.death_save_failures++;
            if (cond.death_save_failures >= 3) {
                cond.dead = true;
                log_("Death save: FAILED — Character dies ({}/3 failures)", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Failed! Character dies ({}/3 failures)", cond.death_save_failures);
            } else {
                log_("Death save: FAILED — {}/3 failures", cond.death_save_failures);
                result.save_roll_message = std::format("Death Save: Failed ({}/3 failures)", cond.death_save_failures);
            }
            bm.setAgentConditions(agent_idx, cond);
        }
    }

    // If unconscious but not stabilized/dead, skip turn (death save was rolled above)
    if (cond.unconscious && !cond.stabilized && !cond.dead) {
        result.turn_skipped = true;
        result.skip_reason = "Unconscious";
        log_("{} cannot act, skipping turn", agent_name);
        return result;
    }

    // Wild Magic Surge (band 7): the surge skips this agent's next turn (once).
    if (stats.wild_magic_skip_next_turn) {
        stats.wild_magic_skip_next_turn = false;
        bm.setAgentStats(agent_idx, stats);
        result.turn_skipped = true;
        result.skip_reason = "Wild Magic Surge";
        log_("{} skips their turn (Wild Magic Surge)", agent_name);
        return result;
    }

    // Check if concentration spell has any living targets left
    if (cond.concentrating && !cond.concentrating_on.empty()) {
        bool has_living_targets = false;
        for (const auto& active_cond : activeAgentConditions_) {
            // Check if any agents have conditions applied by this caster's spells
            if (active_cond.caster_idx == agent_idx &&
                active_cond.agent_idx >= 0 &&
                active_cond.agent_idx < static_cast<int>(agents.size())) {
                const auto& target_stats = agents[static_cast<std::size_t>(active_cond.agent_idx)].agent->getStats();
                const auto& target_cond = agents[static_cast<std::size_t>(active_cond.agent_idx)].agent->getConditions();
                // Target is alive if not dead and not unconscious (unconscious targets can't be affected by control spells)
                if (target_stats.hp_cur > 0 && !target_cond.dead && !target_cond.unconscious) {
                    has_living_targets = true;
                    break;
                }
            }
        }
        // A persistent zone (Spirit Guardians, Cloudkill, etc.) keeps concentration alive
        // on its own — the area is the ongoing effect even with no condition-targets.
        if (!has_living_targets) {
            for (const auto& fx : bm.activeSpellEffects())
                if (fx.caster_idx == agent_idx) { has_living_targets = true; break; }
        }
        if (!has_living_targets) {
            cond.concentrating = false;
            cond.concentrating_on = "";
            bm.setAgentConditions(agent_idx, cond);
            log_("Concentration on {} dropped: no living targets remaining", cond.concentrating_on);
        }
    }

    // Check for incapacitating conditions first (Paralyzed, Incapacitated, Stunned)
    // These always cause a turn skip unless the agent succeeds on a save
    for (auto& active_cond : activeAgentConditions_) {
        if (active_cond.agent_idx != agent_idx) continue;
        if (active_cond.condition_name != "Paralyzed" &&
            active_cond.condition_name != "Incapacitated" &&
            active_cond.condition_name != "Stunned") continue;

        // If save_repeat_turns == -1, skip turn without attempt
        if (active_cond.save_repeat_turns == -1) {
            result.turn_skipped = true;
            result.skip_reason = active_cond.condition_name;
            log_("{} cannot act, skipping turn", agent_name);
            return result;
        }

        // Check if it's time for a save
        if (active_cond.next_save_turn > 0) continue;

        // Save modifier (ability + proficiency + Aura of Protection).
        int save_mod = saveModFor(bm, agent_idx, active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod;
        save_total = applyIndomitableMight(bm, agent_idx, active_cond.save_ability, save_total);
        int save_dc = active_cond.save_dc;

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

        if (save_total >= save_dc) {
            // Save succeeded, remove condition
            removeAgentCondition(active_cond.condition_id);

            // Handle condition-specific cleanup
            if (active_cond.condition_name == "Paralyzed") {
                cond = bm.getAgentConditions(agent_idx);
                cond.paralyzed = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Incapacitated") {
                cond = bm.getAgentConditions(agent_idx);
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            } else if (active_cond.condition_name == "Stunned") {
                cond = bm.getAgentConditions(agent_idx);
                cond.stunned = false;
                cond.incapacitated = false;
                bm.setAgentConditions(agent_idx, cond);
            }

            // Drop the caster's concentration ONLY if this was the last affected target from that spell
            if (active_cond.caster_idx >= 0 && active_cond.caster_idx < static_cast<int>(agents.size())) {
                Agent::Conditions caster_cond = bm.getAgentConditions(active_cond.caster_idx);
                if (caster_cond.concentrating) {
                    // Check if there are any remaining conditions from this spell
                    bool spell_still_affects_targets = false;
                    for (const auto& other_cond : activeAgentConditions_) {
                        if (other_cond.caster_idx == active_cond.caster_idx &&
                            other_cond.spell_idx == active_cond.spell_idx &&
                            other_cond.condition_id != active_cond.condition_id) {
                            spell_still_affects_targets = true;
                            break;
                        }
                    }

                    // Only drop concentration if this was the last affected target
                    if (!spell_still_affects_targets) {
                        caster_cond.concentrating = false;
                        caster_cond.concentrating_on = "";
                        bm.setAgentConditions(active_cond.caster_idx, caster_cond);
                        log_("{} drops concentration on spell (no more affected targets)", agentName(bm, active_cond.caster_idx));
                    } else {
                        log_("{} maintains concentration on spell (still {} other affected targets)", agentName(bm, active_cond.caster_idx), spell_still_affects_targets ? "has" : "no");
                    }
                }
            }

            result.save_roll_message = ability_name(active_cond.save_ability) + " save vs " + active_cond.condition_name +
                                      " — SAVED! (" + active_cond.condition_name + " broken)";
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — SAVED!",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        } else {
            // Save failed, skip this turn (only for incapacitating conditions)
            if (active_cond.condition_name == "Paralyzed" || active_cond.condition_name == "Incapacitated" || active_cond.condition_name == "Stunned") {
                result.turn_skipped = true;
                result.skip_reason = active_cond.condition_name + " (save failed)";
                result.save_roll_message = ability_name(active_cond.save_ability) + " save vs " + active_cond.condition_name +
                                          " — FAILED (turn skipped)";
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED", ability_name(active_cond.save_ability), active_cond.condition_name, save_d20, save_mod, save_total, save_dc);
                log_("{} cannot act, skipping turn", agent_name);
                return result;
            } else {
                // Non-incapacitating condition failed save, reset next save time
                active_cond.next_save_turn = active_cond.save_repeat_turns;
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED",
                     ability_name(active_cond.save_ability), active_cond.condition_name,
                     save_d20, save_mod, save_total, save_dc);
            }
        }
        break;  // Only check one condition per turn
    }

    // Check for non-incapacitating conditions that allow save repeats
    for (auto& active_cond : activeAgentConditions_) {
        if (active_cond.agent_idx != agent_idx) continue;
        if (active_cond.condition_name == "Paralyzed" ||
            active_cond.condition_name == "Incapacitated" ||
            active_cond.condition_name == "Stunned") continue;  // Skip incapacitating conditions

        if (active_cond.save_repeat_turns == -1) continue;  // Never allows saves
        if (active_cond.next_save_turn > 0) continue;  // Not time to save yet

        // Frightened: save only if no LOS to fear source
        if (active_cond.condition_name == "Frightened" && active_cond.caster_idx >= 0) {
            Cell src = bm.placedAgents()[active_cond.caster_idx].origin;
            Cell vic = bm.placedAgents()[active_cond.agent_idx].origin;
            if (bm.hasLineOfSight(vic, 1, src, 1)) continue;  // still sees source, no save
        }

        // Unconscious: auto-fail STR/DEX saves
        Agent::Conditions agent_cond = bm.getAgentConditions(active_cond.agent_idx);
        if (agent_cond.unconscious && (active_cond.save_ability == SaveStr || active_cond.save_ability == SaveDex)) {
            auto ability_name = [](SaveAbility_t ab) -> std::string {
                return (ab == SaveStr) ? "STR" : "DEX";
            };
            log_("{} save vs {} — AUTOMATICALLY FAILED (Unconscious auto-fails STR/DEX saves)",
                 ability_name(active_cond.save_ability), active_cond.condition_name);
            active_cond.next_save_turn = active_cond.save_repeat_turns;
            continue;
        }

        // Save modifier (ability + proficiency + Aura of Protection).
        int save_mod = saveModFor(bm, agent_idx, active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod - (2 * agent_cond.exhaustion_level);
        save_total = applyIndomitableMight(bm, agent_idx, active_cond.save_ability, save_total);
        int save_dc = active_cond.save_dc;

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

        if (save_total >= save_dc) {
            // Save succeeded, remove condition
            removeAgentCondition(active_cond.condition_id);
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — SAVED!",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        } else {
            // Save failed, reset next save time
            active_cond.next_save_turn = active_cond.save_repeat_turns;
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        }
        break;  // Only check one condition per turn
    }

    // Seed movement budgets from current stats, applying exhaustion penalty (5 ft per level)
    cond = bm.getAgentConditions(agent_idx);
    int exhaustion_penalty = 5 * cond.exhaustion_level;
    // Movement debuffs: Brutal Strike's Hamstring Blow (-15) and the Slow weapon
    // mastery (-10). These are consumed (cleared) in Agent::turn(), which runs
    // just after this seeding — so they reduce Speed for exactly this one turn.
    int move_penalty = exhaustion_penalty
                     + (cond.hamstrung ? 15 : 0)
                     + (cond.slowed    ? 10 : 0);
    // Speedy (general feat) — your Speed increases by 10 feet. Applied as a budget bonus (not a
    // stat mutation, so it's idempotent across turns/reloads); affects the walking budget only.
    int speed_bonus = stats.hasFeat("Speedy") ? 10 : 0;
    walkRemaining_[agent_idx] = std::max(0, stats.speed_walk + speed_bonus - move_penalty);
    flyRemaining_ [agent_idx] = std::max(0, stats.speed_fly - move_penalty);
    swimRemaining_[agent_idx] = std::max(0, stats.speed_swim - move_penalty);
    burrowRemaining_[agent_idx] = std::max(0, stats.speed_burrow - move_penalty);

    // Warrior of Shadow L17 Cloak of Shadows: Invisibility expires if agent moves to bright light
    if (cond.cloak_of_shadows_active) {
        VisibilityLevel light = bm.getLightLevel(agent.origin);
        if (light == VisibilityLevel::Clear || light == VisibilityLevel::Sunlight) {
            cond.invisible = false;
            cond.cloak_of_shadows_active = false;
            bm.setAgentConditions(agent_idx, cond);
            log_("{}'s Cloak of Shadows fades (moved to bright light)", agent_name);
        }
    }

    // Reset per-turn conditions
    agent.agent->turn();

    // Reset leveled spell cast flag
    auto new_stats = stats;
    new_stats.resetLeveledSpellCastFlag();
    // Legendary Actions: a creature regains all of its legendary actions at the start of its turn.
    if (new_stats.has_legendary_actions)
        new_stats.legendary_actions_current = new_stats.legendary_actions_max;
    bm.setAgentStats(agent_idx, new_stats);

    // Refill the bonus-action budget for the new turn (general action economy).
    resetBonusActions(bm, agent_idx);

    // Keep any Emanation anchored to this agent centered on them (e.g. after a forced move).
    recomputeAnchoredEffects(bm, agent_idx);

    // Apply begin-of-turn spell effects
    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_begin_turn) continue;
        if (zoneSparesTarget(bm, effect, agent_idx)) continue;  // self + allies (faction rules)

        // Check if agent occupies any cell in the effect (only apply once per effect)
        bool in_effect = false;
        for (int c = agent.origin.col; c < agent.origin.col + agent.agent->getSize() && !in_effect; ++c) {
            for (int r = agent.origin.row; r < agent.origin.row + agent.agent->getSize() && !in_effect; ++r) {
                auto it = std::find(effect.cells.begin(), effect.cells.end(), Cell{c, r});
                if (it != effect.cells.end()) {
                    applyZoneIfNewThisTurn(bm, effect, agent_idx);
                    in_effect = true;
                }
            }
        }
    }

    return result;
}

void CombatEngine::endTurn(BattleMap& bm, int agent_idx) noexcept
{
    // Apply end-of-turn spell effects
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return;

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_end_turn) continue;
        if (zoneSparesTarget(bm, effect, agent_idx)) continue;  // self + allies (faction rules)

        // Check if agent occupies any cell in the effect (only apply once per effect)
        bool in_effect = false;
        for (int c = agent.origin.col; c < agent.origin.col + agent.agent->getSize() && !in_effect; ++c) {
            for (int r = agent.origin.row; r < agent.origin.row + agent.agent->getSize() && !in_effect; ++r) {
                auto it = std::find(effect.cells.begin(), effect.cells.end(), Cell{c, r});
                if (it != effect.cells.end()) {
                    applySpellEffect(bm, effect, agent_idx);
                    in_effect = true;
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Round execution
// ─────────────────────────────────────────────────────────────────────────────

std::vector<AttackResult> CombatEngine::runRound(
    BattleMap& bm, const std::vector<TurnActions>& turns)
{
    std::vector<AttackResult> results;
    const int n = static_cast<int>(bm.placedAgents().size());

    // Reset per-turn flags at the start of the round
    for (int i = 0; i < n; ++i) {
        bm.placedAgents()[static_cast<std::size_t>(i)].agent->setReactionUsed(false);

        // Refill the bonus-action budget (RL/headless path; beginTurn covers the GUI path).
        resetBonusActions(bm, i);

        // Reset per-round Barbarian flags (per-turn flags reset in beginTurn)
        Agent::Conditions cond = bm.getAgentConditions(i);
        cond.berserker_frenzy_used = false;
        cond.zealot_divine_fury_used = false;
        cond.brutal_strike_available = false;
        cond.brutal_strike_used_this_turn = false;
        cond.stunning_strike_available = false;
        cond.stunning_strike_used = false;
        cond.psionic_strike_available = false;
        cond.psionic_strike_used = false;
        cond.hand_of_harm_available = false;
        cond.hand_of_harm_used = false;
        cond.hand_of_harm_last_target = -1;
        cond.divine_smite_available = false;
        cond.divine_smite_used = false;
        cond.eldritch_smite_available = false;
        cond.eldritch_smite_used = false;
        cond.lifedrinker_used = false;
        cond.war_magic_used = false;
        cond.open_hand_rider_available = false;
        cond.open_hand_rider_used = false;
        cond.hamstrung = false;
        cond.sundering_target_idx = -1;
        cond.staggered_next_save = false;
        // Weapon Mastery fallback resets (also consumed on-use / in Agent::turn()).
        cond.sapped = false;
        cond.sap_used_this_turn = false;
        cond.slowed = false;
        cond.slow_used_this_turn = false;
        cond.vex_target_idx = -1;
        cond.vex_used_this_turn = false;
        cond.push_available = false;
        cond.push_used_this_turn = false;
        cond.poison_used_this_turn = false;
        cond.topple_available = false;
        cond.topple_used_this_turn = false;
        cond.cleave_available = false;
        cond.cleave_used_this_turn = false;
        bm.setAgentConditions(i, cond);
    }

    for (const TurnActions& t : turns) {
        if (t.agent_idx < 0 || t.agent_idx >= n) continue;

        // Incapacitated agents (0 hp) skip their turn entirely.
        if (bm.getAgentStats(t.agent_idx).hp_cur <= 0) continue;

        // Retrieve the acting agent's shared_ptr through the span.
        auto& actor = bm.placedAgents()[static_cast<std::size_t>(t.agent_idx)];

        // ── Action ────────────────────────────────────────────────────────
        actor.agent->action();
        for (const Attack& atk : t.attacks) {
            AttackResult r = executeAction(bm, atk);
            if (r.valid) {
                int tgt = atk.target_idx;
                if (tgt >= 0 && tgt < n) {
                    auto& tgt_agent = bm.placedAgents()[static_cast<std::size_t>(tgt)];
                    if (!tgt_agent.agent->hasUsedReaction()) {
                        tgt_agent.agent->reaction();
                        tgt_agent.agent->setReactionUsed(true);
                    }
                }
            }
            results.push_back(std::move(r));
        }
        for (const SpellAction& sa : t.spell_actions) {
            (void)executeSpell(bm, sa);
        }

        // ── Bonus action ──────────────────────────────────────────────────
        actor.agent->bonusAction();
        // Keep the bonus-action budget honest in the batch path. A bonus_attacks list is
        // ONE bonus action's worth of strikes (e.g. an off-hand attack, or a Flurry's two
        // hits), so spend once for the whole block; likewise one per bonus spell. Execution
        // is not blocked here — availableAttacks() is responsible for action-space legality.
        if (!t.bonus_attacks.empty()) (void)spendBonusAction(bm, t.agent_idx);
        for (const Attack& atk : t.bonus_attacks) {
            AttackResult r = executeAction(bm, atk);
            if (r.valid) {
                int tgt = atk.target_idx;
                if (tgt >= 0 && tgt < n) {
                    auto& tgt_agent = bm.placedAgents()[static_cast<std::size_t>(tgt)];
                    if (!tgt_agent.agent->hasUsedReaction()) {
                        tgt_agent.agent->reaction();
                        tgt_agent.agent->setReactionUsed(true);
                    }
                }
            }
            results.push_back(std::move(r));
        }
        for (const SpellAction& sa : t.bonus_spells) {
            (void)spendBonusAction(bm, t.agent_idx);
            (void)executeSpell(bm, sa);
        }

        // ── Movement ──────────────────────────────────────────────────────
        actor.agent->walk();
        actor.agent->fly();
    }

    return results;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Death saves
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::rollDeathSave(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    const auto& agent = agents[static_cast<std::size_t>(idx)];
    const auto& stats = agent.agent->getStats();

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.unconscious || cond.dead || cond.stabilized) {
        log_("[DEATH SAVE SKIP] {} - unconscious={}, dead={}, stabilized={}",
             agentName(bm, idx), cond.unconscious, cond.dead, cond.stabilized);
        return;
    }
    log_("[DEATH SAVE ROLL] {} rolling death save (current: {}/3 successes, {}/3 failures)",
         agentName(bm, idx), cond.death_save_successes, cond.death_save_failures);

    int con_mod = (stats.con - 10) / 2;
    if (stats.con < 10 && (stats.con - 10) % 2 != 0) --con_mod;
    int death_d20 = roll(20);
    // Durable (general feat) — Defy Death: Advantage on Death Saving Throws (take the higher d20).
    if (stats.hasFeat("Durable")) death_d20 = std::max(death_d20, roll(20));
    int death_total = death_d20 + con_mod;

    if (death_d20 == 20) {
        cond.stabilized = true;
        cond.death_save_successes = 3;
        bm.setAgentConditions(idx, cond);
        log_("Death save (on damage): NATURAL 20! Character automatically stabilizes");
    } else if (death_d20 == 1) {
        cond.death_save_failures += 2;
        if (cond.death_save_failures >= 3) {
            cond.dead = true;
            log_("Death save (on damage): NATURAL 1! Character dies");
        } else {
            log_("Death save (on damage): Natural 1 (2 failures) — {}/3 failures", cond.death_save_failures);
        }
        bm.setAgentConditions(idx, cond);
    } else if (death_total >= 10) {
        cond.death_save_successes++;
        if (cond.death_save_successes >= 3) {
            cond.stabilized = true;
            log_("Death save (on damage): SUCCESS (stabilized) — {}/3 successes", cond.death_save_successes);
        } else {
            log_("Death save (on damage): SUCCESS — {}/3 successes", cond.death_save_successes);
        }
        bm.setAgentConditions(idx, cond);
    } else {
        cond.death_save_failures++;
        if (cond.death_save_failures >= 3) {
            cond.dead = true;
            log_("Death save (on damage): FAILED — Character dies");
        } else {
            log_("Death save (on damage): FAILED — {}/3 failures", cond.death_save_failures);
        }
        bm.setAgentConditions(idx, cond);
    }
}

} // namespace rpg
