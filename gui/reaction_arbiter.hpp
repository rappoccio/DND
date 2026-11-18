#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  reaction_arbiter.hpp – park/resume state of the reaction system (the
//  decision the engine is parked on, the in-flight move / attack / turn-start
//  flows, and the counter-counterspell cast stack)
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, sixth and last sub-engine cut (R4g). Owns the
//  five members the plan's table assigns ReactionArbiter: pending_decision_,
//  in_flight_move_ (deferred here from R4b), in_flight_attack_ (the folded
//  AttackResolver row), in_flight_turn_ and cast_stack_ (deferred from R4e).
//
//  A CONTAINER, NOT THE FLOW — the R4c/R4e/R4f line. The functions that drive
//  these flows (beginMove/advanceMove, beginAttack/advanceAttack, beginCast/
//  advanceCast/stepTopCast, beginTurnFlow/advanceTurnStart, and the single
//  resume point submitDecision) stay on CombatEngine: every one of them calls
//  back into attack resolution, executeSpell, the condition code and damage, so
//  as a class it would need the whole engine in hand and would only rename the
//  god class. R4h gathers their bodies into one TU (combat_reactions.cpp) instead.
//
//  Typed routes for the park itself (park / unpark / parked / pending). The four
//  flow states are handed out by mutable reference — move(), attack(), turn(),
//  casts() — because the flow functions write their fields throughout. That is a
//  deliberate seam like ConditionTracker::mutableAll() and NpcState::turn(), and
//  it stays: the code that writes through it is not moving.
//
//  Serialization: CombatEngine::snapshot()/restore() still write and read the
//  same five top-level keys ("pending_decision", "in_flight_move",
//  "in_flight_attack", "in_flight_turn", "cast_stack") in the same positions,
//  through these accessors — R5's rule that a moved member keeps its JSON key.
//  mutablePending() exists only for restore().
//
//  Nothing here rolls or logs, so there is no CombatContext& (R4b's rule).
// ─────────────────────────────────────────────────────────────────────────────

#include "combat_types.hpp"   // PendingDecision, ReactionCtx, InFlightMove/Attack/Turn/Cast

#include <vector>

namespace rpg {

class ReactionArbiter {
public:
    // ── The park (what the GUI polls) ──
    [[nodiscard]] const PendingDecision& pending() const noexcept { return pending_; }
    [[nodiscard]] bool parked() const noexcept { return pending_.active; }
    // Suspend on ctx: the exact `PendingDecision{true, ctx}` assignment every flow spells out.
    void park(const ReactionCtx& ctx) { pending_ = PendingDecision{true, ctx}; }
    // Clear the active flag only; ctx is left as it was, exactly as `.active = false` did.
    void unpark() noexcept { pending_.active = false; }
    // restore() only: reset and read the whole struct back.
    [[nodiscard]] PendingDecision& mutablePending() noexcept { return pending_; }

    // ── The in-flight flows. Mutable access for the flow functions — see the file header. ──
    [[nodiscard]] InFlightMove&         move() noexcept         { return move_; }
    [[nodiscard]] const InFlightMove&   move() const noexcept   { return move_; }
    [[nodiscard]] InFlightAttack&       attack() noexcept       { return attack_; }
    [[nodiscard]] const InFlightAttack& attack() const noexcept { return attack_; }
    [[nodiscard]] InFlightTurn&         turn() noexcept         { return turn_; }
    [[nodiscard]] const InFlightTurn&   turn() const noexcept   { return turn_; }

    // ── The cast stack. back() = the cast currently resolving; empty = idle. ──
    [[nodiscard]] std::vector<InFlightCast>&       casts() noexcept       { return casts_; }
    [[nodiscard]] const std::vector<InFlightCast>& casts() const noexcept { return casts_; }
    [[nodiscard]] bool castActive() const noexcept { return !casts_.empty(); }
    [[nodiscard]] InFlightCast&       topCast() noexcept       { return casts_.back(); }   // precond: castActive()
    [[nodiscard]] const InFlightCast& topCast() const noexcept { return casts_.back(); }

private:
    PendingDecision           pending_{};   // what the engine is parked on (GUI polls it)
    InFlightMove              move_{};      // resumable state of a provoking move
    InFlightAttack            attack_{};    // resumable state of a begin_attack flow
    InFlightTurn              turn_{};      // resumable state of a begin_turn_flow
    std::vector<InFlightCast> casts_;       // counter-counterspell decision stack
};

}  // namespace rpg
