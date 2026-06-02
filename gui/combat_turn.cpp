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
        const Agent::Stats& s = bm.getAgentStats(i);
        if (s.hp_cur <= 0) continue;   // dead / incapacitated before combat starts

        InitiativeEntry e;
        e.agent_idx = i;
        e.d20       = roll(20);
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

    const auto& agent = agents[static_cast<std::size_t>(agent_idx)];
    auto stats = agent.agent->getStats();

    // Paladin Oath of Devotion — Sacred Weapon: tick down its 1-minute (10-round) duration.
    // Persisted immediately so the rest of this turn (and the GUI) sees the updated count.
    if (stats.sacred_weapon_turns > 0) {
        --stats.sacred_weapon_turns;
        if (stats.sacred_weapon_turns == 0) stats.sacred_weapon_bonus = 0;
        bm.setAgentStats(agent_idx, stats);
    }

    // Sorcerer Innate Sorcery: tick down its 1-minute (10-round) duration.
    if (stats.innate_sorcery_turns > 0) {
        --stats.innate_sorcery_turns;
        bm.setAgentStats(agent_idx, stats);
    }

    // Death from Exhaustion: agent dies at exhaustion level 6
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);

    // Reset per-turn Barbarian flags at start of each turn
    cond.reckless_attack = false;

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

    // Death saves: roll CON save DC 10 if unconscious at 0 HP
    if (cond.unconscious && stats.hp_cur <= 0 && !cond.stabilized && !cond.dead) {
        int con_mod = (stats.con - 10) / 2;
        if (stats.con < 10 && (stats.con - 10) % 2 != 0) --con_mod;
        int death_d20 = roll(20);
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

        // Helper to get ability modifier
        auto getSaveMod = [&](SaveAbility_t ability) -> int {
            int score = 0;
            bool prof = false;
            switch (ability) {
                case SaveStr: score = stats.str; prof = stats.save_prof_str; break;
                case SaveDex: score = stats.dex; prof = stats.save_prof_dex; break;
                case SaveCon: score = stats.con; prof = stats.save_prof_con; break;
                case SaveInt: score = stats.intel; prof = stats.save_prof_intel; break;
                case SaveWis: score = stats.wis; prof = stats.save_prof_wis; break;
                default: score = stats.cha; prof = stats.save_prof_cha; break;
            }
            int mod = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --mod;
            return mod + (prof ? stats.prof_bonus : 0);
        };

        int save_mod = getSaveMod(active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod;
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

        // Helper to get ability modifier
        auto getSaveMod = [&](SaveAbility_t ability) -> int {
            int score = 0;
            bool prof = false;
            switch (ability) {
                case SaveStr: score = stats.str; prof = stats.save_prof_str; break;
                case SaveDex: score = stats.dex; prof = stats.save_prof_dex; break;
                case SaveCon: score = stats.con; prof = stats.save_prof_con; break;
                case SaveInt: score = stats.intel; prof = stats.save_prof_intel; break;
                case SaveWis: score = stats.wis; prof = stats.save_prof_wis; break;
                default: score = stats.cha; prof = stats.save_prof_cha; break;
            }
            int mod = (score - 10) / 2;
            if (score < 10 && (score - 10) % 2 != 0) --mod;
            return mod + (prof ? stats.prof_bonus : 0);
        };

        int save_mod = getSaveMod(active_cond.save_ability);
        int save_d20 = roll(20);
        int save_total = save_d20 + save_mod - (2 * agent_cond.exhaustion_level);
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
    walkRemaining_[agent_idx] = std::max(0, stats.speed_walk - move_penalty);
    flyRemaining_ [agent_idx] = std::max(0, stats.speed_fly - move_penalty);
    swimRemaining_[agent_idx] = std::max(0, stats.speed_swim - move_penalty);
    burrowRemaining_[agent_idx] = std::max(0, stats.speed_burrow - move_penalty);

    // Reset per-turn conditions
    agent.agent->turn();

    // Reset leveled spell cast flag
    auto new_stats = stats;
    new_stats.resetLeveledSpellCastFlag();
    bm.setAgentStats(agent_idx, new_stats);

    // Refill the bonus-action budget for the new turn (general action economy).
    resetBonusActions(bm, agent_idx);

    // Keep any Emanation anchored to this agent centered on them (e.g. after a forced move).
    recomputeAnchoredEffects(bm, agent_idx);

    // Apply begin-of-turn spell effects
    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_begin_turn) continue;
        if (effect.caster_idx == agent_idx) continue;  // don't damage self

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
        if (effect.caster_idx == agent_idx) continue;  // don't damage self

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
        cond.divine_smite_available = false;
        cond.divine_smite_used = false;
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
