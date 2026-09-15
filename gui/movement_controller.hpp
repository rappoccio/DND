#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  movement_controller.hpp – per-turn movement budgets & slipping-terrain counter
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, second cut (R4b). Owns five of the six members
//  the plan's sub-engine table assigns to MovementController: walkRemaining_,
//  flyRemaining_, swimRemaining_, burrowRemaining_ and slipDistanceMoved_.
//
//  WHAT IS NOT HERE, AND WHY. The plan also lists `in_flight_move_`, and the
//  movement *flow* functions that own it — moveAgent, jumpAgent, teleportAgent,
//  canAgentMove, placeTeleportedAgents, checkSlippingTerrain, standup — stay on
//  CombatEngine for now. Measured before deciding: those functions touch
//  `pending_decision_` (5×), `activeAgentConditions_` (3×), `in_flight_turn_`
//  (2×), `in_flight_attack_` (2×), `cast_stack_` and `decider_`. That is state
//  belonging to ReactionArbiter, ConditionTracker and SpellResolver — none of
//  which exist yet, and ReactionArbiter is deliberately LAST because the
//  park/resume flow is the one place the plan says "mechanical move" is a lie.
//  Moving the flow now would mean threading four not-yet-extracted members into
//  this class, so the flow comes with ReactionArbiter instead. Everything here
//  is the part with no cross-module coupling at all.
//
//  No CombatContext& member, unlike VisibilityService: nothing in the budget
//  layer rolls a die or logs, so a reference would be dead weight (and would
//  delete CombatEngine's copy-assignment for no reason). The flow functions that
//  DO roll and log are the ones staying on the engine.
//
//  CombatEngine keeps getWalkRemaining/…/spendBurrow/clearMovement/seedMoveBudgets
//  as forwarders, so the Python API and every existing call site are unchanged.
//  grantWalk/resetSlipDistance/addSlipDistance have no engine-level equivalent —
//  they exist to route the handful of direct field pokes that used to reach in
//  from combat_turn.cpp, combat_riders.cpp and combat_resources.cpp.
//
//  Serializable from the start, per plan decision #4 — and this one matters more
//  than the visibility cache: a mid-combat restore with empty budgets would let a
//  creature that had already moved move again.
// ─────────────────────────────────────────────────────────────────────────────

#include <algorithm>
#include <unordered_map>

#include <nlohmann/json.hpp>

namespace rpg {

class MovementController {
public:
    // ── Budget queries (feet). Absent entry ≡ 0 remaining. ────────────────
    [[nodiscard]] int getWalkRemaining(int agent_idx) const noexcept { return lookup(walkRemaining_, agent_idx); }
    [[nodiscard]] int getFlyRemaining(int agent_idx) const noexcept { return lookup(flyRemaining_, agent_idx); }
    [[nodiscard]] int getSwimRemaining(int agent_idx) const noexcept { return lookup(swimRemaining_, agent_idx); }
    [[nodiscard]] int getBurrowRemaining(int agent_idx) const noexcept { return lookup(burrowRemaining_, agent_idx); }

    // ── Spend. Clamps to 0; returns the amount actually spent. ────────────
    int spendWalk(int agent_idx, int feet) noexcept { return spend(walkRemaining_, agent_idx, feet); }
    int spendFly(int agent_idx, int feet) noexcept { return spend(flyRemaining_, agent_idx, feet); }
    int spendSwim(int agent_idx, int feet) noexcept { return spend(swimRemaining_, agent_idx, feet); }
    int spendBurrow(int agent_idx, int feet) noexcept { return spend(burrowRemaining_, agent_idx, feet); }

    // Seed all four budgets at once (turn start, or an out-of-turn legendary Dash).
    // Clamped to >= 0, matching what beginTurn and seedMoveBudgets always did.
    void seedMoveBudgets(int agent_idx, int walk, int fly, int swim, int burrow) noexcept {
        walkRemaining_  [agent_idx] = std::max(0, walk);
        flyRemaining_   [agent_idx] = std::max(0, fly);
        swimRemaining_  [agent_idx] = std::max(0, swim);
        burrowRemaining_[agent_idx] = std::max(0, burrow);
    }

    // Add to the walking budget mid-turn (Barbarian Instinctive Pounce's half-speed grant).
    // Deliberately un-clamped on the high side and additive, exactly as the raw `+=` was.
    void grantWalk(int agent_idx, int feet) noexcept { walkRemaining_[agent_idx] += feet; }

    // Clear all four movement budgets (end of combat / start of a new round).
    // Does NOT touch the slip counter — that is per-turn state reset by beginTurn,
    // and clearMovement never cleared it.
    void clearMovement() noexcept {
        walkRemaining_.clear();
        flyRemaining_.clear();
        swimRemaining_.clear();
        burrowRemaining_.clear();
    }

    // ── Slipping terrain (ice/grease) ─────────────────────────────────────
    // Feet moved across slipping terrain since the last save check. beginTurn resets it;
    // checkSlippingTerrain accumulates and resets it once a save is triggered.
    void resetSlipDistance(int agent_idx) noexcept { slipDistanceMoved_[agent_idx] = 0; }

    // Accumulate and return the new running total for this agent.
    int addSlipDistance(int agent_idx, int feet) noexcept {
        int& counter = slipDistanceMoved_[agent_idx];
        counter += feet;
        return counter;
    }

    // ── Serialization (COMBAT_REFACTOR_PLAN.md R4/R5) ─────────────────────
    // Int-keyed maps serialize as arrays of {agent, feet} objects rather than relying
    // on nlohmann's handling of a non-string key — the same choice R3 made for
    // CombatContext::agent_portent_round_used_.
    [[nodiscard]] nlohmann::json to_json() const {
        return nlohmann::json{
            {"walk_remaining",   mapToJson(walkRemaining_)},
            {"fly_remaining",    mapToJson(flyRemaining_)},
            {"swim_remaining",   mapToJson(swimRemaining_)},
            {"burrow_remaining", mapToJson(burrowRemaining_)},
            {"slip_distance",    mapToJson(slipDistanceMoved_)},
        };
    }

    void from_json(const nlohmann::json& j) {
        mapFromJson(j, "walk_remaining",   walkRemaining_);
        mapFromJson(j, "fly_remaining",    flyRemaining_);
        mapFromJson(j, "swim_remaining",   swimRemaining_);
        mapFromJson(j, "burrow_remaining", burrowRemaining_);
        mapFromJson(j, "slip_distance",    slipDistanceMoved_);
    }

private:
    using Budget = std::unordered_map<int, int>;

    [[nodiscard]] static int lookup(const Budget& m, int agent_idx) noexcept {
        auto it = m.find(agent_idx);
        return (it != m.end()) ? it->second : 0;
    }

    static int spend(Budget& m, int agent_idx, int feet) noexcept {
        auto& rem   = m[agent_idx];              // inserts 0 if absent
        int   spent = std::min(feet, rem);
        rem -= spent;
        return spent;
    }

    [[nodiscard]] static nlohmann::json mapToJson(const Budget& m) {
        nlohmann::json out = nlohmann::json::array();
        for (const auto& [agent, feet] : m)
            out.push_back({{"agent", agent}, {"feet", feet}});
        return out;
    }

    static void mapFromJson(const nlohmann::json& j, const char* key, Budget& m) {
        m.clear();
        if (auto it = j.find(key); it != j.end())
            for (const auto& entry : *it)
                m[entry.value("agent", 0)] = entry.value("feet", 0);
    }

    // Movement budgets for the current turn. Key = agent_idx; value = remaining feet.
    Budget walkRemaining_;
    Budget flyRemaining_;
    Budget swimRemaining_;
    Budget burrowRemaining_;

    // Distance moved on slipping terrain (ice/grease) since the last save check.
    Budget slipDistanceMoved_;
};

} // namespace rpg
