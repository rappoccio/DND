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
#include <cmath>
#include <cstdlib>
#include <format>
#include <limits>
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

    // Self-heal any grapple whose grappler can no longer maintain it (died/downed/incapacitated,
    // possibly on another creature's turn, or via a kill path that missed the down chokepoint, or
    // a stale grappler_idx). This frees a creature grappled by a now-dead captor at the start of its
    // own turn even if the release was never explicitly propagated.
    reconcileGrapples(bm);

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

    // Paladin Oath of Vengeance — Avenging Angel: Frightful Aura. When this creature starts its turn
    // inside an enemy Avenging Angel paladin's Aura of Protection, it must succeed on a WIS save or be
    // Frightened for 1 minute (or until it takes any damage). Modeled as a Turn-Undead-style tracked
    // Frightened condition (fear source = the paladin; ends on damage). One save per turn.
    if (!bm.getAgentConditions(agent_idx).frightened) {
        for (int p = 0; p < static_cast<int>(agents.size()); ++p) {
            if (p == agent_idx) continue;
            const Agent::Stats ps = bm.getAgentStats(p);
            if (ps.avenging_angel_turns <= 0) continue;
            if (ps.hp_cur <= 0) continue;
            const Agent::Conditions pc = bm.getAgentConditions(p);
            if (pc.unconscious || pc.incapacitated) continue;
            if (areAllies(bm, p, agent_idx)) continue;
            const int radius_ft = (ps.char_level >= 18) ? 30 : 10;
            const PlacedAgent& pal_pa = agents[static_cast<std::size_t>(p)];
            const PlacedAgent& vic_pa = agents[static_cast<std::size_t>(agent_idx)];
            const int d = footprintDistance(pal_pa.origin, pal_pa.agent->getSize(),
                                            vic_pa.origin, vic_pa.agent->getSize());
            if (d * 5 > radius_ft) continue;
            // The aura is an Emanation — blocked by Total Cover (matches bestPaladinAura).
            if (!bm.hasLineOfSight(pal_pa.origin, pal_pa.agent->getSize(),
                                   vic_pa.origin, vic_pa.agent->getSize()))
                continue;
            const int save_dc  = spellSaveDcFromAbility(ps, SaveCha);
            const int save_mod = saveModFor(bm, agent_idx, SaveWis);
            const int save_d20 = roll(20);
            const int save_total = save_d20 + save_mod;
            log_("{} makes a WIS save vs Frightful Aura (DC {}): {} + {} = {} ({})",
                 agent_name, save_dc, save_d20, save_mod, save_total,
                 (save_total < save_dc) ? "FAILED" : "PASSED");
            if (save_total < save_dc) {
                ActiveAgentCondition cond;
                cond.agent_idx        = agent_idx;
                cond.caster_idx       = p;              // fear source (Frightened LOS/movement rule)
                cond.condition_name   = "Frightened";
                cond.save_ability     = SaveWis;
                cond.save_dc          = save_dc;
                cond.save_repeat_turns = -1;            // no per-turn save; ends on damage / after 1 min
                cond.turns_remaining  = 10;             // 1 minute
                cond.on_damage        = OnDamage_t::End;
                cond.next_save_turn   = 0;
                (void)addAgentCondition(bm, cond);
            }
            break;   // one Frightful Aura save per turn
        }
    }

    // Paladin Oath of Devotion — Sacred Weapon: tick down its 1-minute (10-round) duration.
    // Persisted immediately so the rest of this turn (and the GUI) sees the updated count.
    if (stats.sacred_weapon_turns > 0) {
        --stats.sacred_weapon_turns;
        if (stats.sacred_weapon_turns == 0) stats.sacred_weapon_bonus = 0;
        bm.setAgentStats(agent_idx, stats);
    }

    // Paladin Oath of Vengeance — Vow of Enmity: tick down its 1-minute (10-round) duration.
    // When it lapses, drop the sworn target so the Advantage stops applying.
    if (stats.vow_of_enmity_turns > 0) {
        --stats.vow_of_enmity_turns;
        if (stats.vow_of_enmity_turns == 0) stats.vow_of_enmity_target = -1;
        bm.setAgentStats(agent_idx, stats);
    }

    // Paladin Oath of Vengeance — Avenging Angel: tick down its 10-minute (100-round) duration.
    // On expiry, revert the granted Fly speed to the pre-activation snapshot.
    if (stats.avenging_angel_turns > 0) {
        --stats.avenging_angel_turns;
        if (stats.avenging_angel_turns == 0)
            stats.speed_fly = stats.avenging_angel_prior_fly;
        bm.setAgentStats(agent_idx, stats);
    }

    // Paladin Oath of the Ancients — Elder Champion: regain 10 HP at the start of each of your turns,
    // then tick down its 1-minute (10-round) duration.
    if (stats.elder_champion_turns > 0) {
        stats.hp_cur = std::min(stats.hp_max, stats.hp_cur + 10);
        --stats.elder_champion_turns;
        bm.setAgentStats(agent_idx, stats);
        log_("{} regains 10 HP (Elder Champion) — now at {} HP", agent_name, stats.hp_cur);
    }

    // Paladin Oath of Glory — Living Legend: tick down its 10-minute (100-round) duration.
    if (stats.living_legend_turns > 0) {
        --stats.living_legend_turns;
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

    // Draconic Sorcerer Elemental Affinity: reset the per-turn CHA-bonus flag.
    if (stats.draconic_affinity_used_this_turn) {
        stats.draconic_affinity_used_this_turn = false;
        bm.setAgentStats(agent_idx, stats);
    }

    // Draconic Sorcerer Elemental Affinity — resistance: tick down the 1-hour (600-round) window.
    // On expiry, restore the chosen type's multiplier to 1.0.
    if (stats.draconic_affinity_resist_turns > 0) {
        --stats.draconic_affinity_resist_turns;
        if (stats.draconic_affinity_resist_turns == 0 &&
            stats.draconic_affinity_type >= 0) {
            auto t = static_cast<std::size_t>(stats.draconic_affinity_type);
            stats.magic_damage_multipliers[t] = 1.0f;
            log_("{}'s Draconic Resistance expires", agent_name);
        }
        bm.setAgentStats(agent_idx, stats);
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

    // Clockwork L14 Trance of Order: tick down the 1-minute (10-round) window. While >0, attacks
    // against this sorcerer lose Advantage and the sorcerer floors its own d20s to 10 (applyTranceFloor).
    if (stats.trance_of_order_turns > 0) {
        --stats.trance_of_order_turns;
        bm.setAgentStats(agent_idx, stats);
        if (stats.trance_of_order_turns == 0)
            log_("{}'s Trance of Order ends", agent_name);
    }

    // Aberrant L14 Revelation in Flesh: tick the 10-minute (100-round) window. On expiry, restore the
    // fly/swim/truesight values snapshotted at activation.
    if (stats.revelation_in_flesh_turns > 0) {
        --stats.revelation_in_flesh_turns;
        if (stats.revelation_in_flesh_turns == 0) {
            stats.speed_fly       = stats.revelation_prior_fly;
            stats.speed_swim      = stats.revelation_prior_swim;
            stats.truesight_range = stats.revelation_prior_truesight;
            log_("{}'s Revelation in Flesh ends", agent_name);
        }
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
    cond.retaliation_available = false;   // Berserker L10 Retaliation: stale reaction offer (resets with the reaction)
    cond.retaliation_target_idx = -1;

    if (cond.exhaustion_level >= 6 && stats.hp_cur > 0) {
        stats.hp_cur = 0;
        bm.setAgentStats(agent_idx, stats);
        // Route through the single down/death chokepoint so ALL of this creature's influence
        // (grapples, concentration, imposed conditions, reverse-reference marks) is released at once.
        // applyUnconscious sets dead for NPCs; force it for PCs too — Exhaustion 6 kills outright.
        applyUnconscious(bm, agent_idx);
        cond = bm.getAgentConditions(agent_idx);
        cond.dead = true;
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
                    // The Radiant exposure also shuts off Regeneration for this turn (consumed by the
                    // regen block below). No separate "in sunlight" field needed — sunlight IS Radiant.
                    if (stats.regeneration_amount > 0) stats.regen_suppressed = true;
                    bm.setAgentStats(agent_idx, stats);
		    bm.setAgentConditions(agent_idx, cond);
                    log_("{} takes 20 radiant damage from Sunlight exposure → {}/{}", agent_name,
                         stats.hp_cur, stats.hp_max);
                    if (stats.hp_cur == 0) {
                        // Route through the single down/death chokepoint (releases grapples,
                        // concentration, imposed conditions, and reverse-reference marks at once).
                        // A dead grappler (e.g. a vampire that grapple-bit a victim) frees its victims
                        // here. applyUnconscious sets dead for NPCs; force it in case this ever runs
                        // on a non-NPC sunlight-vulnerable creature.
                        applyUnconscious(bm, agent_idx);
                        cond = bm.getAgentConditions(agent_idx);
                        cond.dead = true;
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

    // Burning [Hazard] (Alchemist's Fire): "A burning creature or object takes 1d4 Fire damage at
    // the start of each of its turns." Runs BEFORE Regeneration on purpose: the Fire damage goes
    // through processDamageTaken, so a creature whose regeneration is interrupted by fire (a Troll)
    // has regen_suppressed set in time for the regen block below to consume it this same turn.
    if (bm.getAgentConditions(agent_idx).burning && stats.hp_cur > 0) {
        const int raw = roll(4);
        // No "caster" — the flames are on their own now, so no one's resistance-bypass feats apply.
        const Agent::Stats no_source{};
        const float mult = effectiveMagicDamageMult(no_source, stats, MagicDamage_t::Fire, false,
                                                    &bm, agent_idx);
        const int dmg = static_cast<int>(static_cast<float>(raw) * mult);
        damageAgent(bm, agent_idx, dmg);
        processDamageTaken(bm, agent_idx, dmg, 1u << static_cast<unsigned>(MagicDamage_t::Fire));
        checkConcentrationOnDamage(bm, agent_idx, dmg);
        // damageAgent wrote the new HP; re-sync the local copy or the blocks below (which write
        // `stats` back wholesale) would restore the pre-burn HP.
        stats = bm.getAgentStats(agent_idx);
        log_("{} is Burning: takes {} Fire damage → {}/{}", agent_name, dmg,
             stats.hp_cur, stats.effectiveMaxHp());
        if (stats.hp_cur <= 0) {
            const Agent::Conditions bc = bm.getAgentConditions(agent_idx);
            if (!bc.unconscious && !bc.dead) applyUnconscious(bm, agent_idx);
            result.save_roll_message = "Burning: burned to death";
            return result;   // the creature is down — nothing else happens on its turn
        }
    }

    // Regeneration (Troll, Vampire, Hydra, …): regain regeneration_amount HP at the start of the
    // turn, capped at effectiveMaxHp(), provided the creature still has ≥1 HP. Regeneration is
    // suppressed for this one check if regen_suppressed is set — either by an interrupting damage
    // type taken since the last turn (processDamageTaken) or, for vampires, by the Radiant damage the
    // Sunlight block above just dealt this turn. The flag is consumed here so only the one turn is hit.
    if (stats.regeneration_amount > 0 && stats.hp_cur > 0) {
        if (stats.regen_suppressed) {
            stats.regen_suppressed = false;  // consume
            log_("{}'s Regeneration is suppressed this turn", agent_name);
        } else {
            int before = stats.hp_cur;
            stats.hp_cur = std::min(stats.effectiveMaxHp(), stats.hp_cur + stats.regeneration_amount);
            if (stats.hp_cur > before)
                log_("{} regenerates {} HP → {}/{}", agent_name,
                     stats.hp_cur - before, stats.hp_cur, stats.effectiveMaxHp());
        }
        bm.setAgentStats(agent_idx, stats);
    }

    // ── Recharge (Monster-Manual breath weapons / limited actions) ──────────────
    // For each of this agent's weapons and innate spells that is currently `expended`
    // (recharge_min > 0 and spent), roll a d6: on a roll ≥ recharge_min the action
    // recharges — clear `expended` and refill its N/day uses. recharge_min == 0 means
    // the action has no recharge mechanic and is skipped.
    {
        auto rch_weapons = bm.getAgentWeapons(agent_idx);
        bool weapons_dirty = false;
        for (auto& w : rch_weapons) {
            if (w.recharge_min > 0 && w.expended) {
                int d6 = roll(6);
                if (d6 >= w.recharge_min) {
                    w.expended = false;
                    if (w.uses_max > 0) w.uses_remaining = std::max(w.uses_remaining, w.uses_max);
                    weapons_dirty = true;
                    log_("{} recharges {} (rolled {} ≥ {})", agent_name, w.name, d6, w.recharge_min);
                }
            }
        }
        if (weapons_dirty) bm.setAgentWeapons(agent_idx, rch_weapons);

        auto rch_spells = bm.getAgentSpells(agent_idx);
        bool spells_dirty = false;
        for (auto& sp : rch_spells) {
            if (sp.recharge_min > 0 && sp.expended) {
                int d6 = roll(6);
                if (d6 >= sp.recharge_min) {
                    sp.expended = false;
                    if (sp.uses_max > 0) sp.uses_remaining = std::max(sp.uses_remaining, sp.uses_max);
                    spells_dirty = true;
                    log_("{} recharges {} (rolled {} ≥ {})", agent_name, sp.name, d6, sp.recharge_min);
                }
            }
        }
        if (spells_dirty) bm.setAgentSpells(agent_idx, rch_spells);
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

    // Searing Vengeance (Celestial Warlock L14): instead of rolling a death save at the start of its
    // turn, the warlock may spring back to its feet in a radiant burst (once per long rest). The &&
    // chain short-circuits for everyone else, and triggerSearingVengeance also returns false when the
    // resource is spent — so a non-qualifying creature falls through to the normal death save below.
    if (cond.unconscious && stats.hp_cur <= 0 && !cond.stabilized && !cond.dead &&
        stats.character_class == CharacterClass::Warlock &&
        stats.warlock_subclass == CelestialPath && stats.char_level >= 14 &&
        triggerSearingVengeance(bm, agent_idx)) {
        cond  = bm.getAgentConditions(agent_idx);   // refresh: now conscious and standing
        stats = bm.getAgentStats(agent_idx);
    }
    // Death saves: roll CON save DC 10 if unconscious at 0 HP
    else if (cond.unconscious && stats.hp_cur <= 0 && !cond.stabilized && !cond.dead) {
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
        // Area-control terrain (Web, Grease, Spike Growth, Fog Cloud, etc.) is the ongoing
        // effect itself — it has no condition-targets, so it must not be dropped for lack of them.
        if (!has_living_targets) {
            for (const auto& te : bm.activeTerrainEffects())
                if (te.source_agent_idx == agent_idx) { has_living_targets = true; break; }
        }
        // Light/visibility effects (Darkness, Fog Cloud's heavy obscurement, etc.) likewise are
        // the spell's effect; they affect cells, not creatures, so living-target count is irrelevant.
        if (!has_living_targets) {
            for (const auto& le : bm.activeLightEffects())
                if (le.source_agent_idx == agent_idx) { has_living_targets = true; break; }
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

        // Check if it's time for a save; count down the repeat timer if not
        if (active_cond.next_save_turn > 0) { --active_cond.next_save_turn; break; }

        // Save modifier (ability + proficiency + Aura of Protection).
        int save_mod = saveModFor(bm, agent_idx, active_cond.save_ability);
        // Vistani Curse of Weakness: Disadvantage on saves tied to the cursed ability.
        int save_d20 = curseSaveDisadvantage(bm, agent_idx, active_cond.save_ability)
                           ? rollDisadvantage(20) : roll(20);
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
            removeAgentCondition(bm, active_cond.condition_id);

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
                // Reset countdown so the next save fires after save_repeat_turns more turns.
                // save_repeat_turns-1 because the countdown is pre-decremented in the > 0 branch.
                active_cond.next_save_turn = std::max(0, active_cond.save_repeat_turns - 1);
                return result;
            } else {
                // Non-incapacitating condition failed save, reset next save time
                active_cond.next_save_turn = std::max(0, active_cond.save_repeat_turns - 1);
                log_("{} save vs {} — rolled {} + {} = {} vs DC {} — FAILED",
                     ability_name(active_cond.save_ability), active_cond.condition_name,
                     save_d20, save_mod, save_total, save_dc);
            }
        }
        break;  // Only check one condition per turn
    }

    // Fallback: if still incapacitated after the condition loop (next_save_turn was >0 and got
    // decremented, or incapacitated was set without an active condition), skip this turn.
    // This ensures incapacitated agents never act even between periodic save windows.
    {
        cond = bm.getAgentConditions(agent_idx);
        if (!result.turn_skipped && cond.incapacitated) {
            result.turn_skipped = true;
            result.skip_reason = "Incapacitated";
            log_("{} cannot act (incapacitated), skipping turn", agent_name);
            return result;
        }
    }

    // Check for non-incapacitating conditions that allow save repeats
    for (auto& active_cond : activeAgentConditions_) {
        if (active_cond.agent_idx != agent_idx) continue;
        if (active_cond.condition_name == "Paralyzed" ||
            active_cond.condition_name == "Incapacitated" ||
            active_cond.condition_name == "Stunned") continue;  // Skip incapacitating conditions

        if (active_cond.save_repeat_turns == -1) continue;  // Never allows saves
        if (active_cond.next_save_turn > 0) { --active_cond.next_save_turn; continue; }  // Count down repeat timer

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
        // Vistani Curse of Weakness: Disadvantage on saves tied to the cursed ability.
        int save_d20 = curseSaveDisadvantage(bm, agent_idx, active_cond.save_ability)
                           ? rollDisadvantage(20) : roll(20);
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
            removeAgentCondition(bm, active_cond.condition_id);
            log_("{} save vs {} — rolled {} + {} = {} vs DC {} — SAVED!",
                 ability_name(active_cond.save_ability), active_cond.condition_name,
                 save_d20, save_mod, save_total, save_dc);
        } else {
            // Save failed, reset next save time (use save_repeat_turns-1 so first decrement
            // in the > 0 branch still yields the correct inter-save interval).
            active_cond.next_save_turn = std::max(0, active_cond.save_repeat_turns - 1);
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
    // Aura of Alacrity (Paladin Oath of Glory L7): +10 ft Speed while in a Glory paladin's aura (the
    // paladin itself always qualifies). A budget bonus for this turn — no stat mutation.
    if (hasAuraOfAlacrity(bm, agent_idx)) speed_bonus += 10;
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
        cond.quivering_palm_available = false;
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

// ── NPC automation turn driver (NPC_AUTOMATION_PLAN.md Step 2) ────────────────
NpcAutomationStrategy CombatEngine::resolveStrategy(const BattleMap& bm, int agent_idx) const noexcept
{
    // SINGLE place the later difficulty-level → role → strategy override will live. Today it returns the
    // per-agent strategy unchanged; when difficulty levels arrive, this resolves a strategy from the
    // agent's role + the team difficulty level instead, leaving runNpcTurn and the executors untouched.
    return bm.getAgentNpcAutomationStrategy(agent_idx);
}

int CombatEngine::npcCommandFleeSource(int agent_idx) const noexcept
{
    for (const auto& ac : activeAgentConditions_)
        if (ac.agent_idx == agent_idx && ac.condition_name == "CommandFlee" && ac.caster_idx >= 0)
            return ac.caster_idx;
    return -1;
}

FlowStatus CombatEngine::runFleeTurn(BattleMap& bm, int agent_idx, int fear_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (agent_idx < 0 || agent_idx >= n || fear_idx < 0 || fear_idx >= n)
        return FlowStatus::Completed;

    NpcTurnState& st = npc_turn_;
    // Resume after a parked OA on the way out: the flee move already resolved during advanceMove, so just
    // end the turn (Command Flee grants no action). Guarded on flee_move_launched (mirrors aoe_moving).
    if (st.active && st.agent_idx == agent_idx && st.flee_move_launched) {
        st = NpcTurnState{};
        return FlowStatus::Completed;
    }

    // Fresh flee turn: seed the agent's OWN movement budget (the one moveAgent/reachableCells read), exactly
    // as runWeaponTurn does — beginTurn only seeds the parallel engine budget, and headless RL has no GUI
    // _reset_movement to seed this one.
    st = NpcTurnState{};
    st.active    = true;
    st.agent_idx = agent_idx;
    const Agent::Stats s = bm.getAgentStats(agent_idx);
    bm.placedAgents()[static_cast<std::size_t>(agent_idx)].agent->initMovement(
        s.speed_walk, s.speed_fly, s.speed_swim, s.speed_burrow);

    const auto& pa  = bm.placedAgents();
    const Cell  me  = pa[static_cast<std::size_t>(agent_idx)].origin;
    const int   ms  = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
    const Cell  src = pa[static_cast<std::size_t>(fear_idx)].origin;
    const int   ss  = pa[static_cast<std::size_t>(fear_idx)].agent->getSize();
    const int   budget = pa[static_cast<std::size_t>(agent_idx)].agent->getWalkRemaining();

    // Among all reachable cells, pick the one that MAXIMISES footprint distance from the fear source
    // (running away by the fastest available route). reachableCells only ever returns passable, unobstructed
    // cells, so the winner is by construction a clear cell — satisfying the "flee to a clear area" fallback
    // when a straight line away is blocked. Ties → the farthest-travelled cell (commit to the getaway).
    Cell dest = me;
    int  bestAway = footprintDistance(me, ms, src, ss);
    int  bestSteps = 0;
    for (const Cell& c : bm.reachableCells(me, ms, budget, MovementType::Walk, agent_idx)) {
        const int away  = footprintDistance(c, ms, src, ss);
        const int steps = std::max(std::abs(c.col - me.col), std::abs(c.row - me.row));
        if (away > bestAway || (away == bestAway && steps > bestSteps)) {
            bestAway = away; bestSteps = steps; dest = c;
        }
    }

    if (dest == me) {   // boxed in — nowhere farther to run; the turn is spent (no action either way)
        log_("Command (Flee): {} is cornered and cannot get farther from {}",
             agentName(bm, agent_idx), agentName(bm, fear_idx));
        st = NpcTurnState{};
        return FlowStatus::Completed;
    }

    log_("Command (Flee): {} flees from {}", agentName(bm, agent_idx), agentName(bm, fear_idx));
    st.flee_move_launched = true;   // set BEFORE beginMove so a park→resume ends the turn (no re-flee)
    if (beginMove(bm, agent_idx, dest, MovementType::Walk) == FlowStatus::AwaitingDecision)
        return FlowStatus::AwaitingDecision;

    st = NpcTurnState{};            // move resolved inline → flee complete, no action taken
    return FlowStatus::Completed;
}

FlowStatus CombatEngine::runNpcTurn(BattleMap& bm, int agent_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (agent_idx < 0 || agent_idx >= n) return FlowStatus::Completed;

    // A dead/downed/removed NPC must NOT act. Initiative can still hand a turn to a creature that was
    // killed earlier this round (or tombstoned/benched), and without this gate that corpse would run a
    // full strategy — Anastrasya, already dead, cast Hunger of Hadar. Mirror npcAttackable's in-play test
    // on the ACTOR: no HP, dead/unconscious condition, or out of play → end the turn immediately, taking
    // no action. Clear any parked turn state so a stale resume doesn't fire on the corpse next round.
    {
        const PlacedAgent& self = bm.placedAgents()[static_cast<std::size_t>(agent_idx)];
        const auto cond = bm.getAgentConditions(agent_idx);
        if (self.removed_from_play || self.on_deck ||
            bm.getAgentStats(agent_idx).hp_cur <= 0 || cond.dead || cond.unconscious) {
            if (npc_turn_.active && npc_turn_.agent_idx == agent_idx)
                npc_turn_ = NpcTurnState{};
            return FlowStatus::Completed;
        }
    }

    // Command (Flee) overrides all strategy: the creature spends its whole turn running away from the fear
    // source and takes no action (Command RAW). Intercept BEFORE the strategy dispatch so it applies to any
    // NPC regardless of role. On a park→resume the flee flag routes back here (the condition persists until
    // the caster's next turn), and runFleeTurn's flee_move_launched guard ends the turn without re-fleeing.
    const int fearIdx = npcCommandFleeSource(agent_idx);
    if (fearIdx >= 0)
        return runFleeTurn(bm, agent_idx, fearIdx);

    // Resume routing (Bucket D + PreferAOE): if a parked NPC turn is mid-flight for this agent and it was
    // launched as an AoE/recharge cast (or its approach move), it MUST re-enter runAoeTurn to finish. The
    // recharge feature that triggered the AoE route below is expended once the cast launches, so the
    // fresh-turn heuristic would mis-route the resume. A weapon-turn resume leaves both flags clear and
    // falls through — runWeaponTurn/runAoeTurn detect it via npc_turn_.
    if (npc_turn_.active && npc_turn_.agent_idx == agent_idx &&
        (npc_turn_.aoe_cast_launched || npc_turn_.aoe_moving))
        return runAoeTurn(bm, agent_idx);

    // Dispatch on the resolved strategy (NEVER the raw field — resolveStrategy is the single seam where a
    // later difficulty-level override will swap the algorithm). Strategies are added per step; until a
    // strategy has an executor it falls through to Simple (the always-defined baseline).
    const NpcAutomationStrategy strategy = resolveStrategy(bm, agent_idx);

    // No-op (bystander): take no action and no movement — cower in place and end the turn. Intercept
    // BEFORE the Bucket D recharge route so a cowering monster never fires a breath either. Clear any
    // parked turn state defensively (a No-op turn never parks a decision window).
    if (strategy == NpcAutomationStrategy::NoOp) {
        log_("{} cowers in place and takes no action.", agentName(bm, agent_idx));
        if (npc_turn_.active && npc_turn_.agent_idx == agent_idx)
            npc_turn_ = NpcTurnState{};
        return FlowStatus::Completed;
    }

    // Bucket D — rechargeable features (dragon breath etc.): whatever the base strategy, a monster with a
    // currently-available recharge AoE action should spend it as often as it recharges. Route through the
    // AoE executor (it prioritises the area breath, respects friendly-fire/ally-sparing, and falls back to
    // a weapon turn when the breath can't catch an enemy this turn). An expended breath is not "available",
    // so a dragon on cooldown correctly bites instead. PreferAOE already routes to runAoeTurn below.
    if (strategy != NpcAutomationStrategy::PreferAOE &&
        strategy != NpcAutomationStrategy::PreferHide &&
        npcHasAvailableRechargeAoe(bm, agent_idx))
        return runAoeTurn(bm, agent_idx);

    // Each strategy is just a policy fed to the one shared executor (runWeaponTurn). New strategies add a
    // case + a policy, not a new turn driver. Until a strategy has a policy it falls through to Simple.
    NpcStrategyPolicy policy;   // defaults == Simple (preferMelee): Nearest target, best melee weapon, no kite
    switch (strategy) {
        case NpcAutomationStrategy::PreferTargetCaster:
            // Step 4: same executor, but target selection prioritises enemy spellcasters.
            policy.prefer_caster = true;
            break;
        case NpcAutomationStrategy::PreferRange:
            // Step 5: best ranged weapon, focus-fire the lowest-HP enemy, and kite to keep distance.
            policy.prefer_ranged = true;
            policy.kite          = true;
            policy.priority      = NpcTargetPriority::LowestHp;
            break;
        case NpcAutomationStrategy::PreferHide:
            // Step 7: a ranged ambusher. Best ranged weapon, focus-fire the lowest-HP enemy, but spend the
            // MINIMUM movement to reach range+LoS (kite stays false — the saved movement funds the retreat),
            // then run the Conceal tail to re-hide / go invisible each round. Route D flips kite on internally.
            policy.prefer_ranged = true;
            policy.priority      = NpcTargetPriority::LowestHp;
            policy.conceal       = true;
            break;
        case NpcAutomationStrategy::PreferAOE:
            // Step 6: cast the available area spell that catches the most enemies; this is NOT a weapon
            // turn — it has its own executor (and falls back to a Simple weapon turn when nothing is worth
            // blasting). Dispatch straight to it and skip the shared runWeaponTurn below.
            return runAoeTurn(bm, agent_idx);
        case NpcAutomationStrategy::Simple:
        default:
            break;   // Simple == "preferMelee" (NPC_AUTOMATION_PLAN.md Step 3)
    }
    return runWeaponTurn(bm, agent_idx, policy);
}

// ── Simple strategy (= "preferMelee") ────────────────────────────────────────
// Average damage of a weapon's roll set (dice expectation + flat bonuses), used only to RANK weapons.
// Falls back to the convenience damage_dice fields when the roll vectors are empty (test/simple weapons).
// Shields return -1 (they make no attack) so they never win the ranking.
static double npcWeaponAvgDamage(const Weapon& w) noexcept
{
    if (w.is_shield) return -1.0;
    double avg = 0.0;
    bool   hasRolls = false;
    for (const auto& pr : w.physicalDamageRolls) {
        avg += pr.num_dice * (pr.die_size + 1) / 2.0 + pr.bonus;
        hasRolls = true;
    }
    for (const auto& mr : w.magicDamageRolls) {
        avg += mr.num_dice * (mr.die_size + 1) / 2.0 + mr.bonus;
        hasRolls = true;
    }
    if (!hasRolls)
        avg = w.damage_dice_count * (w.damage_dice + 1) / 2.0 + w.damage_modifier;
    return avg + w.bonus_damage;
}

int CombatEngine::npcSelectWeapon(const BattleMap& bm, int agent_idx) const noexcept
{
    const std::vector<Weapon> weapons = bm.getAgentWeapons(agent_idx);
    int bestMelee = -1; double bestMeleeDmg = -1.0;
    int bestAny   = -1; double bestAnyDmg   = -1.0;
    for (int i = 0; i < static_cast<int>(weapons.size()); ++i) {
        const Weapon& w = weapons[static_cast<std::size_t>(i)];
        if (w.is_shield) continue;
        const double dmg = npcWeaponAvgDamage(w);
        if (dmg > bestAnyDmg) { bestAnyDmg = dmg; bestAny = i; }
        if (w.type == WeaponType::Melee && dmg > bestMeleeDmg) { bestMeleeDmg = dmg; bestMelee = i; }
    }
    if (bestMelee >= 0) return bestMelee;       // prefer melee (Simple == preferMelee)
    return bestAny >= 0 ? bestAny : 0;          // ranged-only creature still acts; default to slot 0
}

int CombatEngine::npcSelectRangedWeapon(const BattleMap& bm, int agent_idx) const noexcept
{
    const std::vector<Weapon> weapons = bm.getAgentWeapons(agent_idx);
    int bestRanged = -1; double bestRangedDmg = -1.0;
    for (int i = 0; i < static_cast<int>(weapons.size()); ++i) {
        const Weapon& w = weapons[static_cast<std::size_t>(i)];
        if (w.is_shield || w.type != WeaponType::Ranged) continue;
        const double dmg = npcWeaponAvgDamage(w);
        if (dmg > bestRangedDmg) { bestRangedDmg = dmg; bestRanged = i; }
    }
    if (bestRanged >= 0) return bestRanged;     // prefer ranged (PreferRange == kite at distance)
    return npcSelectWeapon(bm, agent_idx);      // no ranged weapon: a melee-only creature still acts
}

bool CombatEngine::npcAttackable(const BattleMap& bm, int agent_idx, int target_idx) const noexcept
{
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (target_idx < 0 || target_idx >= n || target_idx == agent_idx) return false;
    const PlacedAgent& t = agents[static_cast<std::size_t>(target_idx)];
    if (t.removed_from_play || t.on_deck)          return false;   // tombstoned / reserve: not in play
    if (areAllies(bm, agent_idx, target_idx))      return false;   // enemy == any non-ally
    if (bm.getAgentStats(target_idx).hp_cur <= 0)  return false;
    const auto cond = bm.getAgentConditions(target_idx);
    if (cond.dead || cond.unconscious)             return false;
    return true;
}

bool CombatEngine::npcIsCaster(const BattleMap& bm, int idx) const noexcept
{
    return !bm.getAgentSpells(idx).empty();   // a spellcaster is any agent with a known spell
}

int CombatEngine::npcSelectTarget(const BattleMap& bm, int agent_idx, bool prefer_caster,
                                  NpcTargetPriority priority) const noexcept
{
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return -1;
    const Cell myOrigin = agents[static_cast<std::size_t>(agent_idx)].origin;
    const int  mySize   = agents[static_cast<std::size_t>(agent_idx)].agent->getSize();

    // Step 4: only restrict to spellcasters when at least one enemy caster is attackable; otherwise the
    // pool is the full enemy set and selection degrades to the base priority ("fall back when no caster").
    bool casterPool = false;
    if (prefer_caster) {
        for (int j = 0; j < n; ++j)
            if (npcAttackable(bm, agent_idx, j) && npcIsCaster(bm, j)) { casterPool = true; break; }
    }

    int best = -1;
    int bestDist = std::numeric_limits<int>::max();
    int bestHp   = std::numeric_limits<int>::max();
    for (int j = 0; j < n; ++j) {
        if (!npcAttackable(bm, agent_idx, j)) continue;
        if (casterPool && !npcIsCaster(bm, j)) continue;   // caster pool active: skip non-casters
        const Cell tOrigin = agents[static_cast<std::size_t>(j)].origin;
        const int  tSize   = agents[static_cast<std::size_t>(j)].agent->getSize();
        const int  d  = footprintDistance(myOrigin, mySize, tOrigin, tSize);
        const int  hp = bm.getAgentStats(j).hp_cur;
        const bool better = (priority == NpcTargetPriority::LowestHp)
            ? (hp < bestHp || (hp == bestHp && d < bestDist))   // weakest first, ties → nearest
            : (d  < bestDist || (d == bestDist && hp < bestHp)); // nearest first, ties → weakest
        if (better) { best = j; bestDist = d; bestHp = hp; }
    }
    return best;
}

int CombatEngine::npcFindSelfInvisSpell(const BattleMap& bm, int agent_idx,
                                        Spell::CastingTime_t want) const noexcept
{
    const auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return -1;
    const auto& spells = agents[static_cast<std::size_t>(agent_idx)].spells;

    int fallback = -1;   // a plain Invisibility match (used unless a Greater one turns up)
    // availableCastableSpells applies the slot / N-day / per-turn gating, so a matched spell is
    // one the agent can actually cast right now with the requested casting time.
    for (int si : availableCastableSpells(bm, agent_idx)) {
        const Spell& sp = spells[static_cast<std::size_t>(si)];
        if (sp.type != Spell::Help)          continue;   // self-invis ships as a Help buff
        if (sp.casting_time != want)         continue;   // Action vs BonusAction gate
        bool greater = false, plain = false;
        for (const AttackCondition& c : sp.conditions) {
            if (c.condition_name == "GreaterInvisible") greater = true;   // persists through attacks
            else if (c.condition_name == "Invisible")   plain   = true;
        }
        if (greater) return si;              // prefer Greater Invisibility outright
        if (plain && fallback < 0) fallback = si;
    }
    return fallback;
}

bool CombatEngine::npcFindCoverCell(const BattleMap& bm, int agent_idx, Cell& out) const noexcept
{
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return false;
    const PlacedAgent& me_pa = agents[static_cast<std::size_t>(agent_idx)];
    const Cell me     = me_pa.origin;
    const int  ms     = me_pa.agent->getSize();
    const int  budget = me_pa.agent->getWalkRemaining();

    // A cell is "cover" when no living, non-incapacitated ENEMY has line of sight to the agent's
    // footprint placed there — the exact LoS/enemy filter checkHide uses to gate a Hide.
    auto noEnemyLos = [&](Cell c) -> bool {
        for (int i = 0; i < n; ++i) {
            if (i == agent_idx) continue;
            if (areAllies(bm, agent_idx, i)) continue;
            const PlacedAgent& obs = agents[static_cast<std::size_t>(i)];
            if (obs.agent->getConditions().incapacitated || obs.agent->getStats().hp_cur <= 0) continue;
            if (bm.hasLineOfSight(c, ms, obs.origin, obs.agent->getSize())) return false;
        }
        return true;
    };

    bool found = false; int bestSteps = std::numeric_limits<int>::max();
    // reachableCells is the single geometry source (respects the live walk budget + footprints) and
    // includes the current origin, so an agent already in cover legitimately "stays put" (0 steps).
    for (const Cell& c : bm.reachableCells(me, ms, budget, MovementType::Walk, agent_idx)) {
        if (!noEnemyLos(c)) continue;
        const int steps = std::max(std::abs(c.col - me.col), std::abs(c.row - me.row));
        if (steps < bestSteps) { bestSteps = steps; out = c; found = true; }
    }
    return found;
}

NpcConcealRoute CombatEngine::npcClassifyConceal(const BattleMap& bm, int agent_idx) const noexcept
{
    // Route A — a bonus-action self-Invisibility: full damage AND stealth every turn, no LoS
    // constraint, so it outranks the cover-Hide route.
    if (npcFindSelfInvisSpell(bm, agent_idx, Spell::BonusAction) >= 0) return NpcConcealRoute::RouteA;

    // Route B — cunning action + a reachable no-LoS cover cell to Hide into after attacking.
    if (bm.getAgentStats(agent_idx).has_cunning_action) {
        Cell cover{};
        if (npcFindCoverCell(bm, agent_idx, cover)) return NpcConcealRoute::RouteB;
    }

    // Route C — an action-cast self-Invisibility (alternates cast/attack across rounds).
    if (npcFindSelfInvisSpell(bm, agent_idx, Spell::Action) >= 0) return NpcConcealRoute::RouteC;

    // Route D — no stealth tools: plain PreferRange kite (handled by the caller flipping kite on).
    return NpcConcealRoute::RouteD;
}

FlowStatus CombatEngine::runWeaponTurn(BattleMap& bm, int agent_idx, const NpcStrategyPolicy& policy)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (agent_idx < 0 || agent_idx >= n) return FlowStatus::Completed;

    NpcTurnState& st = npc_turn_;
    if (!(st.active && st.agent_idx == agent_idx)) {   // fresh turn (else: resuming after a parked window)
        st           = NpcTurnState{};
        st.active    = true;
        st.agent_idx = agent_idx;
        st.phase     = NpcTurnState::PickAndMove;
        // Seed the agent's OWN movement budget for this turn — the budget moveAgent/reachableCells read,
        // which starts at 0 on a fresh Agent. beginTurn only seeds the PARALLEL engine budget; in the GUI
        // _reset_movement seeds this one via init_movement, but headless RL has no GUI, so run_npc_turn must
        // seed it itself to be self-contained. Mirror _reset_movement: pass base speeds (getWalkRemaining
        // then applies the exhaustion penalty). Skip on a resume — we are mid-turn and must not refill.
        const Agent::Stats s = bm.getAgentStats(agent_idx);
        bm.placedAgents()[static_cast<std::size_t>(agent_idx)].agent->initMovement(
            s.speed_walk, s.speed_fly, s.speed_swim, s.speed_burrow);
    }

    // Live kite flag: usually just policy.kite, but a PreferHide Route-D agent (no stealth tools) flips this
    // on below so it runs the plain PreferRange kiting path. Kept as a local (policy is const&) that the
    // positioning lambdas capture by reference and read at call time — after the Route-D override runs.
    bool kite = policy.kite;

    // Reach of weapon slot `w`, in CELLS (footprintDistance units): melee uses reach_ft, ranged uses
    // normal_range_ft. reachableCells/footprintDistance are the single geometry source — never re-derived.
    auto reachCellsFor = [&](int w) -> int {
        const Weapon wp = bm.getAgentWeapons(agent_idx)[static_cast<std::size_t>(std::clamp(w, 0, 2))];
        const int rangeFt = (wp.type == WeaponType::Melee) ? wp.reach_ft : wp.normal_range_ft;
        return std::max(1, rangeFt / 5);
    };
    auto isRanged = [&](int w) -> bool {
        return bm.getAgentWeapons(agent_idx)[static_cast<std::size_t>(std::clamp(w, 0, 2))].type
               != WeaponType::Melee;
    };
    // Can the agent, standing at cell `from`, attack `t` with weapon slot `w` (in reach + LoS if ranged)?
    auto canAttackFrom = [&](Cell from, int t, int w) -> bool {
        const auto& pa = bm.placedAgents();
        const int  ms = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
        const Cell tg = pa[static_cast<std::size_t>(t)].origin;
        const int  ts = pa[static_cast<std::size_t>(t)].agent->getSize();
        const int  d  = footprintDistance(from, ms, tg, ts);
        if (d < 1 || d > reachCellsFor(w)) return false;
        if (isRanged(w) && !bm.hasLineOfSight(from, ms, tg, ts)) return false;
        return true;
    };
    auto inReachOf = [&](int t, int w) -> bool {
        return canAttackFrom(bm.placedAgents()[static_cast<std::size_t>(agent_idx)].origin, t, w);
    };
    // Min footprint distance from `c` to ANY attackable enemy — the "safety" a kiter maximises (back away
    // from the nearest threat while staying in weapon range). Larger = safer.
    auto enemyMinDist = [&](Cell c) -> int {
        const auto& pa = bm.placedAgents();
        const int  ms  = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
        int mn = std::numeric_limits<int>::max();
        for (int j = 0; j < n; ++j) {
            if (!npcAttackable(bm, agent_idx, j)) continue;
            const Cell eo = pa[static_cast<std::size_t>(j)].origin;
            const int  es = pa[static_cast<std::size_t>(j)].agent->getSize();
            mn = std::min(mn, footprintDistance(c, ms, eo, es));
        }
        return mn;
    };
    // Reachable cell from which `t` can be attacked with weapon `w`. With kite=false: fewest steps moved
    // (close in, least OA exposure). With kite=true: MAXIMISE distance from the nearest enemy among in-range
    // cells (ties → fewest steps), so a ranged attacker establishes AND maintains range from one finder.
    // reachableCells includes the current origin, so when already in range this can legitimately "stay put".
    // budgetOverride >= 0 tests a HYPOTHETICAL budget (e.g. "what could I reach WITH a Dash?") without
    // mutating the agent; < 0 uses the agent's live remaining budget.
    auto findPositionCell = [&](int t, int w, Cell& out, int budgetOverride = -1) -> bool {
        const auto& pa = bm.placedAgents();
        const Cell me = pa[static_cast<std::size_t>(agent_idx)].origin;
        const int  ms = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
        const int  budget = budgetOverride >= 0 ? budgetOverride
                          : pa[static_cast<std::size_t>(agent_idx)].agent->getWalkRemaining();
        bool found = false; int bestSteps = std::numeric_limits<int>::max();
        int  bestSafety = std::numeric_limits<int>::min();
        for (const Cell& c : bm.reachableCells(me, ms, budget, MovementType::Walk, agent_idx)) {
            if (!canAttackFrom(c, t, w)) continue;
            const int steps = std::max(std::abs(c.col - me.col), std::abs(c.row - me.row));
            if (kite) {
                const int safety = enemyMinDist(c);
                if (safety > bestSafety || (safety == bestSafety && steps < bestSteps)) {
                    bestSafety = safety; bestSteps = steps; out = c; found = true;
                }
            } else if (steps < bestSteps) {
                bestSteps = steps; out = c; found = true;
            }
        }
        return found;
    };
    // Closest reachable approach toward `t` (minimise footprint distance) when no attack cell is reachable.
    auto findApproachCell = [&](int t, Cell& out, int budgetOverride = -1) -> bool {
        const auto& pa = bm.placedAgents();
        const Cell me = pa[static_cast<std::size_t>(agent_idx)].origin;
        const int  ms = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
        const Cell tg = pa[static_cast<std::size_t>(t)].origin;
        const int  ts = pa[static_cast<std::size_t>(t)].agent->getSize();
        const int  budget = budgetOverride >= 0 ? budgetOverride
                          : pa[static_cast<std::size_t>(agent_idx)].agent->getWalkRemaining();
        bool found = false; int bestDist = footprintDistance(me, ms, tg, ts);
        for (const Cell& c : bm.reachableCells(me, ms, budget, MovementType::Walk, agent_idx)) {
            if (c == me) continue;
            const int d = footprintDistance(c, ms, tg, ts);
            if (d >= 1 && d < bestDist) { bestDist = d; out = c; found = true; }
        }
        return found;
    };
    auto curOrigin = [&]() -> Cell {
        return bm.placedAgents()[static_cast<std::size_t>(agent_idx)].origin;
    };
    const auto selectTarget = [&]() {
        return npcSelectTarget(bm, agent_idx, policy.prefer_caster, policy.priority);
    };
    // Nearest attackable enemy for which weapon `w` has a reachable striking cell within `budget`
    // (findPositionCell semantics; budget<0 = live budget, >=0 = a hypothetical Dash budget). Used to
    // RETARGET when the nearest enemy is boxed in / walled off so a melee NPC bites whoever it can reach
    // rather than burning its turn dashing at an unreachable body. Returns -1 if nobody is reachable.
    auto nearestReachableTarget = [&](int w, int budget) -> int {
        const auto& pa = bm.placedAgents();
        const Cell  me = pa[static_cast<std::size_t>(agent_idx)].origin;
        const int   ms = pa[static_cast<std::size_t>(agent_idx)].agent->getSize();
        int best = -1; int bestDist = std::numeric_limits<int>::max();
        for (int j = 0; j < n; ++j) {
            if (!npcAttackable(bm, agent_idx, j)) continue;
            Cell d{};
            if (!findPositionCell(j, w, d, budget)) continue;
            const Cell tg = pa[static_cast<std::size_t>(j)].origin;
            const int  ts = pa[static_cast<std::size_t>(j)].agent->getSize();
            const int  dist = footprintDistance(me, ms, tg, ts);
            if (dist < bestDist) { bestDist = dist; best = j; }
        }
        return best;
    };
    // Seed the turn from an NPC multiattack recipe (ordered (slot,count) segments). Returns true if a
    // non-empty, deliverable recipe was applied — sets st.weapon_idx / attacks_remaining to the FIRST
    // valid segment and st.pending_segments to the rest. Skips leading segments whose slot is invalid or
    // whose weapon is empty (empty-slot ruling). Empty recipe (or nothing deliverable) → false ⇒ caller
    // falls back to legacy num_attacks with the already-selected weapon.
    auto seedFromRecipe = [&](NpcTurnState& s) -> bool {
        // getAgentStats returns by VALUE — copy the recipe vector out, never bind a reference into the
        // destroyed temporary (that dangles).
        const auto ma = bm.getAgentStats(agent_idx).multiattack;
        if (ma.empty()) return false;
        const auto weapons = bm.getAgentWeapons(agent_idx);
        s.pending_segments.assign(ma.begin(), ma.end());
        while (!s.pending_segments.empty()) {
            auto [slot, cnt] = s.pending_segments.front();
            s.pending_segments.erase(s.pending_segments.begin());
            // Recipe slot indexes the variable-length weapon list (may exceed the base 3 slots,
            // e.g. Pit Fiend's Fiery Mace at index 3), so bound against the actual list size.
            if (slot < 0 || slot >= static_cast<int>(weapons.size()) || cnt <= 0) continue;
            if (weapons[static_cast<std::size_t>(slot)].name.empty()) continue;
            s.weapon_idx = slot;
            s.attacks_remaining = cnt;
            return true;
        }
        return false;
    };

    // ── PreferHide (Step 7): up-front conceal-route classification + Route-C skip-attack ────────────
    // Classify the conceal route ONCE, up front, so it is stable across a park→resume AND known before the
    // attack loop. Route C (action-cast self-Invisibility) alternates cast/attack: on a round we are NOT yet
    // invisible, the Action goes to casting Invisibility (no attack) and we then retreat to cover; on a round
    // we START invisible we attack with advantage and retreat. On a cast round, jump straight to the Conceal
    // tail (skip the whole pick/move/attack path). Only runs on a fresh turn (phase == PickAndMove).
    if (policy.conceal && st.phase == NpcTurnState::PickAndMove) {
        st.conceal_route = static_cast<int>(npcClassifyConceal(bm, agent_idx));
        const auto& cond =
            bm.placedAgents()[static_cast<std::size_t>(agent_idx)].agent->getConditions();

        // No attackable target → pure ambush (CP5): if already Hidden/Invisible, hold; otherwise slip to the
        // nearest no-LoS cover and Hide as an ACTION (free — no attack was made, so no cunning action needed).
        // st.target_idx == -1 flags the ambush for the Conceal tail (which runs the cover-move + Hide). Takes
        // precedence over the Route-C cast: with nobody to hide from there is nothing to cast Invisibility for.
        if (selectTarget() < 0) {
            st.target_idx = -1;
            if (cond.hidden || cond.invisible) {       // already concealed — hold position and stay hidden
                log_("NPC {} has no target — holding in concealment", agentName(bm, agent_idx));
                st.active = false;
                return FlowStatus::Completed;
            }
            st.phase = NpcTurnState::Conceal;          // ambush: cover-move + action Hide run in the tail
        } else if (static_cast<NpcConcealRoute>(st.conceal_route) == NpcConcealRoute::RouteC
                   && !cond.invisible) {
            st.target_idx        = selectTarget();
            st.conceal_spell_idx = npcFindSelfInvisSpell(bm, agent_idx, Spell::Action);
            st.phase = NpcTurnState::Conceal;          // no attack this round — cast + retreat run in the tail
        }
    }
    // Route D (no stealth tools): behave as a plain PreferRange kiter for the whole turn. Guarded on
    // st.conceal_route (set on the fresh turn above) so a park→resume keeps kiting. Set BEFORE the PickAndMove
    // positioning path reads `kite` via findPositionCell.
    if (policy.conceal && static_cast<NpcConcealRoute>(st.conceal_route) == NpcConcealRoute::RouteD)
        kite = true;

    if (st.phase == NpcTurnState::PickAndMove) {
        st.target_idx = selectTarget();
        if (st.target_idx < 0) {                       // no enemies on the field
            log_("NPC {} has no target — passing", agentName(bm, agent_idx));
            st.active = false;
            return FlowStatus::Completed;
        }
        st.weapon_idx = policy.prefer_ranged ? npcSelectRangedWeapon(bm, agent_idx)
                                             : npcSelectWeapon(bm, agent_idx);

        // A non-empty multiattack recipe overrides prefer_ranged weapon selection (kite ignored when a
        // recipe is present) and sets st.weapon_idx to the first deliverable segment + queues the rest in
        // st.pending_segments BEFORE positioning runs below, so reachNow / findPositionCell already target
        // the recipe's first weapon. When hasRecipe, seedFromRecipe already set attacks_remaining.
        const bool hasRecipe = seedFromRecipe(st);
        // Auto-use-when-grappling (MONSTER_AUTO_EFFECTS_PLAN.md CP2): a vampire that is ALREADY
        // grappling a creature coming into its turn with NO multiattack recipe would otherwise never
        // bite (legacy selection picks a single weapon by proximity). Append one grapple-bite segment
        // so the Bite is attempted regardless of statblock recipe; the loop below forces its target to
        // the grappled victim. Skip when the legacy weapon IS the bite (avoid a double bite).
        if (!hasRecipe) {
            const auto [biteSlot, biteVictim] = pendingAutoGrappleStrike(bm, agent_idx);
            if (biteVictim >= 0 && biteSlot != st.weapon_idx)
                st.pending_segments.push_back({biteSlot, 1});
        }
        const bool reachNow = inReachOf(st.target_idx, st.weapon_idx);
        // Non-kiters already in reach swing where they stand. Kiters always look for a better-spaced cell
        // first (findPositionCell includes the current cell, so "stay put" remains an option).
        if (reachNow && !kite) {
            st.phase = NpcTurnState::Attacking;
            if (!hasRecipe) st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
        } else {
            Cell dest{};
            if (findPositionCell(st.target_idx, st.weapon_idx, dest)) {
                // Commit the phase BEFORE beginMove so that if the move provokes an OA and parks, the resume
                // re-enters in Attacking (the move is already in flight, not restarted).
                st.phase = NpcTurnState::Attacking;
                if (!hasRecipe) st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
                if (dest != curOrigin()) {             // a kiter may already be on the best cell → no move
                    if (beginMove(bm, agent_idx, dest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
                // move resolved inline → fall through to the attack loop
            } else if (reachNow) {
                // Kiter with no reachable cell at all (e.g. 0 movement budget) but already in range: swing.
                st.phase = NpcTurnState::Attacking;
                if (!hasRecipe) st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
            } else {
                // The nearest enemy (st.target_idx) is unreachable with a normal move — it may be boxed in
                // by other creatures or walled off. Before spending any Dash, RETARGET to the nearest OTHER
                // enemy we can reach a striking cell for this turn (a vampire ringed by commoners should just
                // bite whoever it can reach rather than starve over the one that looked at it funny).
                Cell altDest{};
                const int altTgt = nearestReachableTarget(st.weapon_idx, /*budget=*/-1);
                if (altTgt >= 0 && findPositionCell(altTgt, st.weapon_idx, altDest)) {
                    log_("NPC {} can't reach {} — retargeting to reachable {}",
                         agentName(bm, agent_idx), agentName(bm, st.target_idx), agentName(bm, altTgt));
                    st.target_idx = altTgt;
                    st.phase = NpcTurnState::Attacking;
                    if (!hasRecipe) st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
                    if (altDest != curOrigin()) {
                        if (beginMove(bm, agent_idx, altDest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                            return FlowStatus::AwaitingDecision;
                    }
                    // reached a reachable target → fall through to the swing loop (Action + bonus intact)
                } else {
                    // Nobody is reachable with a normal move. Close the gap by Dashing — but only spend a
                    // Dash that actually BUYS something (a striking cell, or at least a cell closer to the
                    // target). Probe the hypothetical dashed budget first so we never burn an Action/bonus on
                    // a Dash that changes nothing (the old bug: a vampire boxed out of its target spent BOTH
                    // dashes and moved nowhere).
                    const int dashStep = bm.getAgentStats(agent_idx).speed_walk;
                    const int walkNow  =
                        bm.placedAgents()[static_cast<std::size_t>(agent_idx)].agent->getWalkRemaining();
                    const int dashedBudget = walkNow + dashStep;
                    const bool bonusDashAvail =
                        bm.getAgentStats(agent_idx).has_cunning_action && hasBonusAction(bm, agent_idx);

                    // 1) BONUS-ACTION Dash — only if the doubled budget makes SOME target reachable, so the
                    //    Action stays free to swing this same turn.
                    const int bonusReachTgt =
                        bonusDashAvail ? nearestReachableTarget(st.weapon_idx, dashedBudget) : -1;
                    if (bonusReachTgt >= 0) {
                        bm.applyDash(agent_idx);
                        (void)spendBonusAction(bm, agent_idx);
                        st.target_idx = bonusReachTgt;
                        log_("NPC {} Dashes as a bonus action to close on {}",
                             agentName(bm, agent_idx), agentName(bm, st.target_idx));
                        Cell bonusDest{};
                        if (findPositionCell(st.target_idx, st.weapon_idx, bonusDest)) {
                            st.phase = NpcTurnState::Attacking;
                            if (!hasRecipe)
                                st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
                            if (bonusDest != curOrigin()) {
                                if (beginMove(bm, agent_idx, bonusDest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                                    return FlowStatus::AwaitingDecision;
                            }
                            // fall through to the swing loop (Action stays free)
                        }
                    } else {
                        // 2) No Dash reaches anyone → spend the ACTION to Dash and merely close on the nearest
                        //    target, but only if that actually gets us a cell closer (else don't waste the
                        //    Action either — just hold position).
                        Cell adv{};
                        if (findApproachCell(st.target_idx, adv, dashedBudget)) {
                            bm.applyDash(agent_idx);
                            log_("NPC {} dashes toward {}", agentName(bm, agent_idx), agentName(bm, st.target_idx));
                            if (beginMove(bm, agent_idx, adv, MovementType::Walk) == FlowStatus::AwaitingDecision)
                                return FlowStatus::AwaitingDecision;
                        } else {
                            log_("NPC {} can't reach or approach any enemy — holding position",
                                 agentName(bm, agent_idx));
                        }
                        st.phase  = NpcTurnState::Done;
                        st.active = false;
                        return FlowStatus::Completed;
                    }
                }
            }
        }
    }

    if (st.phase == NpcTurnState::Attacking) {
        while (true) {
            if (st.attacks_remaining <= 0) {
                if (st.pending_segments.empty()) break;   // recipe exhausted (or legacy single-weapon done)
                // Advance to the next recipe segment; skip invalid slots / empty weapons (empty-slot ruling).
                const auto weapons = bm.getAgentWeapons(agent_idx);
                bool advanced = false;
                while (!st.pending_segments.empty()) {
                    auto [slot, cnt] = st.pending_segments.front();
                    st.pending_segments.erase(st.pending_segments.begin());
                    // slot indexes the variable-length weapon list (extra attacks live at index 3+).
                    if (slot < 0 || slot >= static_cast<int>(weapons.size()) || cnt <= 0) continue;
                    if (weapons[static_cast<std::size_t>(slot)].name.empty()) continue;
                    st.weapon_idx = slot;
                    st.attacks_remaining = cnt;
                    advanced = true;
                    break;
                }
                if (!advanced) break;
                continue;   // re-evaluate reach for the NEW weapon
            }
            // Auto-use-when-grappling (MONSTER_AUTO_EFFECTS_PLAN.md CP2): if THIS segment's weapon is a
            // grapple-bite (auto_use_when_grappling) and this agent is currently grappling a legal victim,
            // force the segment onto that victim — the Bite lands on the thing being held, overriding the
            // proximity/lowest-HP pick. Resolution (CON save via save_for_damage / forceAutoHit) is
            // unchanged. Runs before re-acquire so the forced (valid) victim survives the drop-check below.
            {
                const auto [biteSlot, biteVictim] = pendingAutoGrappleStrike(bm, agent_idx);
                if (biteVictim >= 0 && biteSlot == st.weapon_idx)
                    st.target_idx = biteVictim;
            }
            // Re-acquire if the current target dropped (or became invalid) mid-multiattack — move to next.
            if (!npcAttackable(bm, agent_idx, st.target_idx)) {
                const int nt = selectTarget();
                if (nt < 0) break;                     // nobody left to hit
                st.target_idx = nt;
            }
            // Step in with leftover movement if out of reach for THIS segment's weapon.
            if (!inReachOf(st.target_idx, st.weapon_idx)) {
                Cell dest{};
                if (findPositionCell(st.target_idx, st.weapon_idx, dest)) {
                    if (dest != curOrigin()) {
                        if (beginMove(bm, agent_idx, dest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                            return FlowStatus::AwaitingDecision;
                    }
                }
                if (!inReachOf(st.target_idx, st.weapon_idx)) {
                    st.attacks_remaining = 0;   // SKIP this segment (skip-unreachable policy), try next
                    continue;
                }
            }
            Attack a;
            a.attacker_idx = agent_idx;
            a.target_idx   = st.target_idx;
            a.weapon_idx   = st.weapon_idx;
            a.attack_slot  = "action";
            --st.attacks_remaining;     // BEFORE beginAttack: a park→resume must not repeat this swing
            renderAttack(agent_idx, st.target_idx);
            if (beginAttack(bm, a) == FlowStatus::AwaitingDecision)
                return FlowStatus::AwaitingDecision;
            // attack resolved inline → next swing
        }
    }

    // ── Conceal tail (PreferHide — NPC_AUTOMATION_PLAN.md Step 7, PREFER_HIDE_PLAN.md) ─────────────
    // After the attack loop a hider re-conceals. The route (A/B/C/D) was classified ONCE up front and cached
    // in st.conceal_route (stable across a park→resume) — don't re-classify here. CP2 implements Route B
    // (cunning-action cover Hide); CP3 adds Route C (action-cast Invisibility); CP4 adds Route A (bonus-cast
    // Invisibility after a full-damage attack). Route D (plain kite, no stealth tools) falls through to Done.
    if (policy.conceal && st.phase == NpcTurnState::Attacking) {
        st.phase = NpcTurnState::Conceal;
    }

    if (st.phase == NpcTurnState::Conceal) {
        const NpcConcealRoute route = static_cast<NpcConcealRoute>(st.conceal_route);
        if (st.target_idx < 0) {
            // No-target ambush (CP5) — no attack was made this turn, so the ACTION is free for a Hide. Slip to
            // the nearest no-LoS cover (parkable: an OA may fire on the way), then Hide as an Action. checkHide
            // gates on enemy LoS itself, so an agent that reached no cover simply fails the hide and stays put.
            if (!st.conceal_move_launched) {
                st.conceal_move_launched = true;
                Cell cover{};
                if (npcFindCoverCell(bm, agent_idx, cover) && cover != curOrigin()) {
                    if (beginMove(bm, agent_idx, cover, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
            }
            if (!st.conceal_act_launched) {
                st.conceal_act_launched = true;
                (void)checkHide(bm, agent_idx, /*in_combat=*/true);   // Action Hide; no bonus/cunning action
            }
        } else if (route == NpcConcealRoute::RouteA) {
            // Route A (CP4) — best of both worlds: the attack already landed for full damage in the loop
            // above; now retreat to cover and BONUS-CAST a BonusAction self-Invisibility spell. Preferred
            // over B (classified first) because it delivers damage AND stealth every round with no LoS
            // constraint (invisibility beats line of sight — the cover move is a bonus, not required).
            // Phase 1 — retreat to nearest no-LoS cover (parkable: an OA may fire on the way).
            if (!st.conceal_move_launched) {
                st.conceal_move_launched = true;
                Cell cover{};
                if (npcFindCoverCell(bm, agent_idx, cover) && cover != curOrigin()) {
                    if (beginMove(bm, agent_idx, cover, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
            }
            // Phase 2 — bonus-action cast self-Invisibility. The finder was not resolved up front (Route A
            // runs the normal attack path), so look it up now. spendBonusAction BEFORE beginCast, and the
            // conceal_act_launched guard is set first, so a parked/resumed cast (Counterspell) never repeats.
            if (!st.conceal_act_launched) {
                st.conceal_act_launched = true;
                if (st.conceal_spell_idx < 0)
                    st.conceal_spell_idx = npcFindSelfInvisSpell(bm, agent_idx, Spell::BonusAction);
                if (st.conceal_spell_idx >= 0 && hasBonusAction(bm, agent_idx)) {
                    (void)spendBonusAction(bm, agent_idx);
                    SpellAction cast;
                    cast.caster_idx     = agent_idx;
                    cast.spell_idx      = st.conceal_spell_idx;
                    cast.slot_level     = 0;               // NPC mode: spends an N/day use, not a player slot
                    cast.target_indices = { agent_idx };   // self-buff: apply Invisible to the caster
                    log_("NPC {} bonus-casts {} to vanish", agentName(bm, agent_idx),
                         bm.getAgentSpells(agent_idx)[static_cast<std::size_t>(st.conceal_spell_idx)].name);
                    if (beginCast(bm, cast) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
            }
        } else if (route == NpcConcealRoute::RouteC) {
            // Route C — action-cast self-Invisibility, alternating with attacks. On a cast round
            // (conceal_spell_idx was set in PickAndMove because we were not yet invisible) the Action goes to
            // the spell and NO attack was made; on an attack round (spell_idx == -1, we started invisible) we
            // already swung with advantage. Either way we now retreat to cover. No bonus-action Hide — the
            // Invisible condition IS the concealment.
            if (st.conceal_spell_idx >= 0 && !st.conceal_act_launched) {
                st.conceal_act_launched = true;   // set BEFORE beginCast so a parked/resumed cast never repeats
                SpellAction cast;
                cast.caster_idx     = agent_idx;
                cast.spell_idx      = st.conceal_spell_idx;
                cast.slot_level     = 0;          // NPC mode: spends an N/day use, not a player slot
                cast.target_indices = { agent_idx };   // self-buff: apply Invisible to the caster
                log_("NPC {} casts {} to vanish", agentName(bm, agent_idx),
                     bm.getAgentSpells(agent_idx)[static_cast<std::size_t>(st.conceal_spell_idx)].name);
                if (beginCast(bm, cast) == FlowStatus::AwaitingDecision)
                    return FlowStatus::AwaitingDecision;   // parked (OnDeclareCast/Counterspell); resume re-enters
            }
            // Retreat to cover (move only — already invisible, so no Hide). Parkable OA window on the way.
            if (!st.conceal_move_launched) {
                st.conceal_move_launched = true;
                Cell cover{};
                if (npcFindCoverCell(bm, agent_idx, cover) && cover != curOrigin()) {
                    if (beginMove(bm, agent_idx, cover, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
            }
        } else if (route == NpcConcealRoute::RouteB) {
            // Phase 1 — retreat to the nearest no-LoS cover cell (parkable: an OA may fire on the way).
            // Commit conceal_move_launched BEFORE beginMove so a parked/resumed move skips this scan.
            if (!st.conceal_move_launched) {
                st.conceal_move_launched = true;
                Cell cover{};
                if (npcFindCoverCell(bm, agent_idx, cover) && cover != curOrigin()) {
                    if (beginMove(bm, agent_idx, cover, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
                // No reachable cover (or already on it) → fall through; the checkHide gate below leaves
                // the bonus action intact when an enemy still has line of sight (ends exposed, retries next round).
            }
            // Phase 2 — bonus-action Hide. checkHide's own LoS gate returns valid=false (no roll, no
            // condition applied) when any enemy can still see us, so an agent that reached no cover ends
            // exposed with its bonus action UNSPENT. Only pay the bonus action for a genuine hide attempt.
            if (!st.conceal_act_launched) {
                st.conceal_act_launched = true;
                if (hasBonusAction(bm, agent_idx)) {
                    const HideResult hr = checkHide(bm, agent_idx, /*in_combat=*/true);
                    if (hr.valid) (void)spendBonusAction(bm, agent_idx);
                }
            }
        }
    }

    st.phase  = NpcTurnState::Done;
    st.active = false;
    return FlowStatus::Completed;
}

// ── PreferAOE strategy (NPC_AUTOMATION_PLAN.md Step 6) ────────────────────────
// Average damage of a spell's roll set (dice expectation + flat bonuses), used only to RANK candidate
// AoE spells when two of them catch the same number of enemies (mirror of npcWeaponAvgDamage).
static double npcSpellAvgDamage(const Spell& sp) noexcept
{
    double avg = 0.0;
    for (const auto& r : sp.magic_damage_rolls)
        avg += r.num_dice * (r.die_size + 1) / 2.0 + r.bonus;
    for (const auto& r : sp.physical_damage_rolls)
        avg += r.num_dice * (r.die_size + 1) / 2.0 + r.bonus;
    return avg;
}

// An AoE blast spell for PreferAOE purposes: a damaging (Harm) area geometry. Single/Multiple are directly
// targeted; Rectangle walls are control — neither is catchment-maximized here. Single-sourced so the plan
// finder (npcPlanAoeCast) and the "does the agent even have an AoE?" gate (npcHasCastableAoeSpell) agree.
static bool isAoeBlastSpell(const Spell& sp) noexcept
{
    const bool isArea = sp.geometry == Spell::Sphere || sp.geometry == Spell::Cone
                      || sp.geometry == Spell::Line   || sp.geometry == Spell::Square;
    return isArea && sp.type == Spell::Harm;
}

NpcAoePlan CombatEngine::npcPlanAoeCast(const BattleMap& bm, int agent_idx) const noexcept
{
    NpcAoePlan plan;
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return plan;

    const PlacedAgent& caster = agents[static_cast<std::size_t>(agent_idx)];
    const Cell casterOrigin = caster.origin;
    const int  casterSize   = caster.agent ? caster.agent->getSize() : 1;

    // Candidate aim points = each attackable enemy's cell (aim at / through a cluster). Cheap (few enemies)
    // and effectively maximizing for blast shapes, whose best catchment center sits on or beside an enemy.
    std::vector<int> enemies;
    for (int j = 0; j < n; ++j)
        if (npcAttackable(bm, agent_idx, j)) enemies.push_back(j);
    if (enemies.empty()) return plan;          // no enemies → no AoE

    double bestPower = -1.0;   // tie-break: among equal net-enemy counts, prefer the higher-damage spell
    for (int si : availableCastableSpells(bm, agent_idx)) {
        const Spell& sp = caster.spells[static_cast<std::size_t>(si)];
        // Only AoE BLAST geometries (Single/Multiple are directly targeted; Rectangle walls are control,
        // handled by other strategies). Catchment maximization is meaningful only for damaging Harm areas.
        if (!isAoeBlastSpell(sp)) continue;

        // Sphere/Square are PLACED at an aim point (range + LoS gated). Cone/Line emanate from the caster,
        // so the aim cell only sets direction — the geometry's own length bounds reach (LoS still required).
        const bool   placedArea   = (sp.geometry == Spell::Sphere || sp.geometry == Spell::Square);
        const int    rangeFt      = effectiveSpellRange(bm, agent_idx, sp);
        const double power        = npcSpellAvgDamage(sp);
        const bool   sparesAllies = sp.selective_targeting;   // RAW "creatures of your choosing" → no FF

        for (int ai : enemies) {
            const Cell aim = agents[static_cast<std::size_t>(ai)].origin;
            if (placedArea) {
                // D&D 5e uses grid (Chebyshev) distance — every cell, diagonals included, is 5 ft.
                // Match the engine's canonical range test (BattleMap range uses std::max(dc,dr)). A
                // Euclidean hypot here made a diagonally-adjacent aim read as ~7.07 ft and wrongly fail
                // the 5-ft gate, so an NPC that closed to a diagonal cell could never cast its short blast.
                const int dCells = std::max(std::abs(aim.col - casterOrigin.col),
                                            std::abs(aim.row - casterOrigin.row));
                if (dCells * 5 > rangeFt) continue;                   // aim beyond casting range
            }
            if (!bm.hasLineOfSight(casterOrigin, casterSize, aim, 1)) continue;

            // Count the catchment with the SAME resolver executeSpell uses — geometry is single-sourced.
            const std::vector<int> hit = resolveAoeTargets(bm, sp, agent_idx, aim.col, aim.row);
            int enemiesHit = 0, alliesHit = 0;
            for (int t : hit) {
                if (npcAttackable(bm, agent_idx, t)) { ++enemiesHit; continue; }   // living enemy in play
                if (t == agent_idx || areAllies(bm, agent_idx, t)) {              // friendly-fire candidate
                    const PlacedAgent& tp = agents[static_cast<std::size_t>(t)];
                    if (!tp.removed_from_play && !tp.on_deck && bm.getAgentStats(t).hp_cur > 0)
                        ++alliesHit;
                }
            }
            const int net = enemiesHit - (sparesAllies ? 0 : alliesHit);
            if (net > plan.net_enemies || (net == plan.net_enemies && net > 0 && power > bestPower)) {
                plan.spell_idx   = si;
                plan.aim         = aim;
                plan.net_enemies = net;
                bestPower        = power;
            }
        }
    }
    return plan;
}

bool CombatEngine::npcHasCastableAoeSpell(const BattleMap& bm, int agent_idx) const noexcept
{
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return false;
    const auto& spells = agents[static_cast<std::size_t>(agent_idx)].spells;
    for (int si : availableCastableSpells(bm, agent_idx))
        if (isAoeBlastSpell(spells[static_cast<std::size_t>(si)])) return true;
    return false;
}

bool CombatEngine::npcHasAvailableRechargeAoe(const BattleMap& bm, int agent_idx) const noexcept
{
    // Bucket D gate: does the agent have a currently-castable recharge feature that runAoeTurn can fire?
    // "Recharge" == recharge_min > 0 (the (Recharge 5–6) mechanic); "castable" == returned by
    // availableCastableSpells (so it has a remaining use and is NOT expended); "AoE blast" so the AoE
    // executor actually casts it (single-target / control recharge actions are out of Bucket D's scope).
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return false;
    const auto& spells = agents[static_cast<std::size_t>(agent_idx)].spells;
    for (int si : availableCastableSpells(bm, agent_idx)) {
        const Spell& sp = spells[static_cast<std::size_t>(si)];
        if (sp.recharge_min > 0 && isAoeBlastSpell(sp)) return true;
    }
    return false;
}

bool CombatEngine::npcFindAoeApproachCell(const BattleMap& bm, int agent_idx, Cell& out) const noexcept
{
    const auto agents = bm.placedAgents();
    const int  n = static_cast<int>(agents.size());
    if (agent_idx < 0 || agent_idx >= n) return false;
    const PlacedAgent& me = agents[static_cast<std::size_t>(agent_idx)];
    const Cell myOrigin = me.origin;
    const int  mySize   = me.agent ? me.agent->getSize() : 1;

    const int tgt = npcSelectTarget(bm, agent_idx);   // nearest attackable enemy (default priority)
    if (tgt < 0) return false;
    const Cell tOrigin = agents[static_cast<std::size_t>(tgt)].origin;
    const int  tSize   = agents[static_cast<std::size_t>(tgt)].agent
                       ? agents[static_cast<std::size_t>(tgt)].agent->getSize() : 1;
    const int  budget  = me.agent ? me.agent->getWalkRemaining() : 0;

    bool found = false;
    int  bestDist = footprintDistance(myOrigin, mySize, tOrigin, tSize);
    for (const Cell& c : bm.reachableCells(myOrigin, mySize, budget, MovementType::Walk, agent_idx)) {
        if (c == myOrigin) continue;
        const int d = footprintDistance(c, mySize, tOrigin, tSize);
        if (d >= 1 && d < bestDist) { bestDist = d; out = c; found = true; }
    }
    return found;
}

FlowStatus CombatEngine::runAoeTurn(BattleMap& bm, int agent_idx)
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (agent_idx < 0 || agent_idx >= n) return FlowStatus::Completed;

    auto curOrigin = [&]() -> Cell {
        return bm.placedAgents()[static_cast<std::size_t>(agent_idx)].origin;
    };

    NpcTurnState& st = npc_turn_;
    bool resuming_after_move = false;
    if (st.active && st.agent_idx == agent_idx) {        // resuming after a parked window
        if (st.aoe_cast_launched) {                      // the single AoE cast already resolved → turn over
            st = NpcTurnState{};
            return FlowStatus::Completed;
        }
        if (st.aoe_moving) {
            // The approach move (bringing enemies into AoE range) resolved after parking on an OA. Re-plan
            // and cast from the new cell — do NOT re-seed movement or approach a second time.
            st.aoe_moving = false;
            resuming_after_move = true;
        } else {
            // No AoE launched and not approaching → this turn fell back to a weapon turn. Resume it:
            // runWeaponTurn owns npc_turn_ and detects the resume via (active && agent_idx match).
            return runWeaponTurn(bm, agent_idx, NpcStrategyPolicy{});
        }
    }

    // Plan from the CURRENT position (fresh turn, or the cell we ended the approach move on).
    NpcAoePlan plan = npcPlanAoeCast(bm, agent_idx);

    if (!resuming_after_move && plan.spell_idx < 0) {
        // Nothing catchable from here. Two very different situations:
        //   · The agent has NO castable AoE blast at all → it can never blast; act like a Simple melee
        //     attacker so an AoE-less "caster" is not idle (runWeaponTurn seeds npc_turn_ from scratch).
        //   · The agent HAS an AoE spell but no enemy is in range/LoS right now → PreferAOE must ALWAYS
        //     prioritise the AoE (never melee while holding one): move toward the enemies to bring them
        //     into range, then cast this turn if the approach closed enough distance.
        if (!npcHasCastableAoeSpell(bm, agent_idx))
            return runWeaponTurn(bm, agent_idx, NpcStrategyPolicy{});   // st still inactive → fresh weapon turn

        // Seed the agent's OWN movement budget (mirrors runWeaponTurn) so the approach can spend it.
        st           = NpcTurnState{};
        st.active    = true;
        st.agent_idx = agent_idx;
        st.phase     = NpcTurnState::Done;
        st.aoe_moving = true;                            // resume-marker: re-plan + cast if the move parks
        const Agent::Stats s = bm.getAgentStats(agent_idx);
        bm.placedAgents()[static_cast<std::size_t>(agent_idx)].agent->initMovement(
            s.speed_walk, s.speed_fly, s.speed_swim, s.speed_burrow);

        Cell dest{};
        if (npcFindAoeApproachCell(bm, agent_idx, dest) && dest != curOrigin()) {
            log_("NPC {} moves to bring enemies into AoE range", agentName(bm, agent_idx));
            if (beginMove(bm, agent_idx, dest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                return FlowStatus::AwaitingDecision;     // parked on an OA; resume re-plans + casts
        }
        st.aoe_moving = false;
        plan = npcPlanAoeCast(bm, agent_idx);            // re-plan from the new position
    }

    if (plan.spell_idx < 0) {
        // Still nothing to blast even after approaching (short-range emanation we could not reach this turn).
        // PreferAOE never melees while it holds an AoE — end the turn having closed distance for next round.
        st = NpcTurnState{};
        return FlowStatus::Completed;
    }

    // Commit the AoE turn state BEFORE beginCast so a parked OnDeclareCast window resumes without re-casting.
    st           = NpcTurnState{};
    st.active    = true;
    st.agent_idx = agent_idx;
    st.phase     = NpcTurnState::Done;       // an AoE turn is one action — no movement/attack phases
    st.aoe_cast_launched = true;             // resume-guard: never re-cast (set BEFORE beginCast)

    SpellAction action;
    action.caster_idx     = agent_idx;
    action.spell_idx      = plan.spell_idx;
    action.slot_level     = 0;               // NPC mode: spends an N/day use or a cantrip, not a player slot
    action.aoe_col        = plan.aim.col;
    action.aoe_row        = plan.aim.row;
    action.target_indices = {};              // engine computes the area's targets (resolveAoeTargets)

    log_("NPC {} casts {} (AoE) catching {} enemies", agentName(bm, agent_idx),
         bm.getAgentSpells(agent_idx)[static_cast<std::size_t>(plan.spell_idx)].name, plan.net_enemies);
    const int rt = npcSelectTarget(bm, agent_idx);           // visualize from the caster toward a hit enemy
    if (rt >= 0) renderAttack(agent_idx, rt);

    if (beginCast(bm, action) == FlowStatus::AwaitingDecision)
        return FlowStatus::AwaitingDecision;  // parked for a human reaction; resume re-enters runAoeTurn

    // Cast resolved inline (no reaction) → the turn is complete.
    st = NpcTurnState{};
    return FlowStatus::Completed;
}

} // namespace rpg
