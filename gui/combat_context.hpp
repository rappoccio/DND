#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  combat_context.hpp – CombatEngine's cross-cutting scratch state
// ─────────────────────────────────────────────────────────────────────────────
//
//  R3 of COMBAT_REFACTOR_PLAN.md. Plain aggregate (no invariants, no behavior)
//  of the handful of CombatEngine members that are genuinely global scratch
//  state, touched from every combat_*.cpp TU rather than owned by one of them:
//  the RNG, the logger/GUI hook, and the one-shot pending-roll modifiers that
//  roll()/rollAdvantage()/rollDisadvantage() consume on the next d20 Test.
//
//  CombatEngine holds exactly one CombatContext (`ctx_`) and its methods reach
//  into it as `ctx_.member_` — this commit moves declarations, not behavior.
//  rules.hpp's free functions take a CombatContext& instead of an implicit
//  CombatEngine `this`, which is what lets them run with no engine at all.
//
//  Serializable from the start (plan decision #4 — every extracted state
//  struct gets to_json/from_json in the commit that creates it, not later).
//  logger_ and render_attack_hook_ are NOT serialized: they're host callbacks
//  (GUI logger pointer, NPC-turn animation hook) rebound by whoever restores
//  a snapshot, not gameplay state. npc_recording_/npc_visual_events_ are the
//  same kind of transient GUI-playback plumbing, drained every turn, so they
//  round-trip as empty/false rather than being persisted either.
// ─────────────────────────────────────────────────────────────────────────────

#include "combat_types.hpp"   // NpcVisualEvent
#include "message_logger.hpp"

#include <cstdint>
#include <format>
#include <functional>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace rpg {

struct CombatContext {
    // ── RNG ──────────────────────────────────────────────────────────────
    std::mt19937 rng_;

    // ── Logging / GUI hooks (not serialized — rebound by the host) ─────────
    MessageLogger* logger_{nullptr};
    // NPC-automation visualization hook (Step 2e seam). Unset in headless mode → renderAttack
    // is a no-op. Notifies the GUI (if installed) that an automated NPC's attacker→target action
    // resolved, so it can animate.
    std::function<void(int, int)> render_attack_hook_;

    // Emit a message to the logger (if attached). The single implementation of what used to be
    // CombatEngine::log_ — that method is now a one-line forwarder to this, so the sub-engines
    // extracted in R4 can log without either duplicating the helper or needing an engine.
    template<typename... Args>
    void log(std::format_string<Args...> fmt, Args&&... args) const {
        if (logger_) logger_->log(std::format(fmt, std::forward<Args>(args)...));
    }

    // ── One-shot pending-roll modifiers ─────────────────────────────────────
    // Bardic Inspiration: a flat bonus folded into the NEXT d20 Test (0 = none). Unlike Portent
    // (which replaces the d20), this is additive. Set by useBardicDie.
    int pending_roll_bonus_{0};
    int consumePendingRollBonus() noexcept { int b = pending_roll_bonus_; pending_roll_bonus_ = 0; return b; }

    // Combat Inspiration damage bonus: a flat bonus folded into the NEXT weapon damage roll.
    // Set by useBardicDieForDamage, mirroring pending_roll_bonus_ for the damage roll.
    int pending_damage_bonus_{0};
    int consumePendingDamageBonus() noexcept { int b = pending_damage_bonus_; pending_damage_bonus_ = 0; return b; }

    // One-shot advantage/disadvantage on the NEXT D20 Test (+1 = advantage, -1 = disadvantage,
    // 0 = none). General mechanism for "advantage on your next roll" (Tides of Chaos, etc.);
    // consumed by roll(20)/rollAdvantage/rollDisadvantage/rollToHit. If the roll already has the
    // opposite, the two cancel (5e rule). Only d20 Tests consume it (damage dice ignore it).
    int pending_advantage_{0};
    int consumePendingAdvantage() noexcept { int a = pending_advantage_; pending_advantage_ = 0; return a; }

    // Overchannel (Evoker Wizard L14): while true, rollDamageDice returns each die at its maximum
    // face instead of rolling. Scoped tightly inside executeSpell (set before the damage rolls,
    // cleared right after) so no unrelated roll is ever maximized.
    bool force_max_damage_{false};

    // Portent Dice system (Diviner Wizard L3+).
    int pending_portent_die_{-1};    // d20 value to use on next roll (-1 = none pending)
    std::unordered_map<int, int> agent_portent_round_used_;  // track which round each agent last used portent

    // True while a Sentinel Guardian counter-attack is resolving (suppresses guard-of-a-guard).
    bool resolving_sentinel_guard_{false};

    // Persistent-zone "once per turn" tracking. Increments on each beginTurn; combat.hpp's
    // zoneAppliedTurn_ maps (effect_id, agent_idx) -> the turnCounter_ value when last applied
    // (that map stays on CombatEngine — it's spell-effect bookkeeping, not scratch state).
    int turnCounter_{0};

    // ── NPC turn playback (GUI animation seam; not serialized) ──────────────
    // Recording is ON only while an automated NPC turn is in flight — set in runNpcTurn, kept on
    // across a park (the parked action resolves inside submitDecision and must record too), and
    // cleared when the turn completes. Every recorder is a no-op otherwise, so player-driven flows
    // and headless RL/tests never accumulate events beyond one turn (fresh turns clear the buffer).
    bool npc_recording_{false};
    std::vector<NpcVisualEvent> npc_visual_events_;

    // ── Serialization (COMBAT_REFACTOR_PLAN.md R3/R5) ───────────────────────
    // rng_ serializes its full mt19937 state via operator<<, not the seed — reseeding from the
    // original seed would diverge the instant any roll happened before the snapshot was taken.
    [[nodiscard]] nlohmann::json to_json() const {
        std::ostringstream rng_state;
        rng_state << rng_;

        nlohmann::json portent_rounds = nlohmann::json::array();
        for (const auto& [agent_idx, round] : agent_portent_round_used_)
            portent_rounds.push_back({{"agent", agent_idx}, {"round", round}});

        return nlohmann::json{
            {"rng_state", rng_state.str()},
            {"pending_roll_bonus", pending_roll_bonus_},
            {"pending_damage_bonus", pending_damage_bonus_},
            {"pending_advantage", pending_advantage_},
            {"force_max_damage", force_max_damage_},
            {"pending_portent_die", pending_portent_die_},
            {"agent_portent_round_used", portent_rounds},
            {"resolving_sentinel_guard", resolving_sentinel_guard_},
            {"turn_counter", turnCounter_},
        };
    }

    static CombatContext from_json(const nlohmann::json& j) {
        CombatContext ctx;
        if (auto it = j.find("rng_state"); it != j.end()) {
            std::istringstream rng_state(it->get<std::string>());
            rng_state >> ctx.rng_;
        }
        ctx.pending_roll_bonus_ = j.value("pending_roll_bonus", 0);
        ctx.pending_damage_bonus_ = j.value("pending_damage_bonus", 0);
        ctx.pending_advantage_ = j.value("pending_advantage", 0);
        ctx.force_max_damage_ = j.value("force_max_damage", false);
        ctx.pending_portent_die_ = j.value("pending_portent_die", -1);
        if (auto it = j.find("agent_portent_round_used"); it != j.end()) {
            for (const auto& entry : *it)
                ctx.agent_portent_round_used_[entry.value("agent", 0)] = entry.value("round", 0);
        }
        ctx.resolving_sentinel_guard_ = j.value("resolving_sentinel_guard", false);
        ctx.turnCounter_ = j.value("turn_counter", 0);
        return ctx;
    }
};

} // namespace rpg
