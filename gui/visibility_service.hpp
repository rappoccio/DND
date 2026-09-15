#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  visibility_service.hpp – vision, perception and hiding, free of CombatEngine
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, first cut. The plan's sub-engine table takes
//  the clean cuts first, and combat_visibility.cpp is the cleanest by a wide
//  margin (49 calls in / 4 out): it owns exactly one member, visibilityMap_,
//  which no other TU touches.
//
//  VisibilityService owns that map and holds a CombatContext& for the RNG and
//  logger (the plan's shape: "each sub-engine owns its state struct and holds
//  CombatContext&"). Implementations live in combat_visibility.cpp — the same
//  TU as before, moved verbatim apart from the three seams noted below.
//
//  Seams where this is NOT a pure `CombatEngine::` → `VisibilityService::`
//  rename, each deliberate:
//
//   1. areAllies now forwards to rules::alliedFactions (rules.hpp) instead of
//      re-implementing the faction test. R3 duplicated those two lines into
//      rules.hpp with a comment saying "dedupe when R4 extracts
//      VisibilityService" — this is that dedupe; rules.hpp is now the single
//      definition and both engine and service route through it.
//   2. roll(20) → rules::roll(ctx_, 20) and log_(…) → ctx_.log(…), which is
//      what those calls already resolve to on CombatEngine (R3 forwarders).
//   3. checkHide no longer calls applyHidden itself. That helper lives in
//      combat_conditions.cpp — the future ConditionTracker, not this module —
//      so CombatEngine::checkHide applies the condition after the service
//      returns result.hidden. Logger output and the resulting BattleMap state
//      are unchanged: nothing was logged after the applyHidden call, and
//      nothing between it and the return read the hidden flag back.
//
//  CombatEngine keeps all seven methods as one-line forwarders, so the ~60
//  existing call sites across the combat_*.cpp TUs, the pybind11 bindings and
//  main.py are untouched — the plan's "land additively, migrate call sites
//  later" rule applied to sub-engines exactly as R3 applied it to rules.hpp.
//
//  Note: the CombatContext& member makes CombatEngine copy-*assignable* no
//  longer (copy construction would alias the source's context). Nothing copies
//  a CombatEngine today; if that ever changes, the engine needs explicit copy
//  semantics that rebind vis_ to its own ctx_.
//
//  Serializable from the start, per plan decision #4.
// ─────────────────────────────────────────────────────────────────────────────

#include "combat_types.hpp"    // HideResult
#include "combat_context.hpp"  // CombatContext (and, transitively, nlohmann/json)

#include <cstdint>
#include <string>
#include <unordered_map>

namespace rpg {

class BattleMap;
enum class VisibilityLevel;    // defined in battle_map.hpp

class VisibilityService {
public:
    explicit VisibilityService(CombatContext& ctx) noexcept : ctx_(ctx) {}

    // ── Visibility ────────────────────────────────────────────────────────
    // Compute visibility from one agent to all others on the map.
    // Respects perception range (based on stats + lighting modifiers),
    // line-of-sight, and obscuration effects. Caches into visibilityMap_.
    void computeVisibility(BattleMap& bm, int agent_idx) noexcept;

    // Cached visibility level between two agents (from the last computeVisibility
    // call). Blocked if visibility hasn't been computed for this pair.
    [[nodiscard]] VisibilityLevel getVisibility(int source_idx, int target_idx) const noexcept;

    // True if `viewer` can perceive `target` for targeting purposes: a target with the
    // Invisible condition can only be perceived by a viewer with Truesight or Blindsight
    // whose range reaches it. Non-invisible targets are always perceivable here (geometric
    // line-of-sight is enforced separately).
    [[nodiscard]] bool canPerceiveTarget(const BattleMap& bm, int viewer_idx, int target_idx) const noexcept;

    // True when a Forcecage BOX (10-ft solid) stands between the two agents: exactly one of
    // them is sealed inside a box, so they are on opposite sides of that wall and NO attack,
    // spell, or effect passes between them (a two-way seal).
    [[nodiscard]] bool forcecageSeparates(const BattleMap& bm, int a_idx, int b_idx) const noexcept;

    // True if two placed agents are allies: same NON-zero faction. Faction 0 is
    // neutral/unassigned — every neutral is its own faction, allied with no one.
    [[nodiscard]] bool areAllies(const BattleMap& bm, int a_idx, int b_idx) const noexcept;

    // ── Hiding ────────────────────────────────────────────────────────────
    // Stealth check vs enemy Perception. On success sets result.hidden; the CALLER applies
    // the Hidden condition (see seam 3 in the file header).
    [[nodiscard]] HideResult checkHide(BattleMap& bm, int agent_idx, bool in_combat) noexcept;

    // Check if a hidden agent comes into LOS and gets detected by Perception.
    // Returns an empty message if still hidden, or the detection message if revealed.
    [[nodiscard]] std::string checkHiddenAgentDetection(BattleMap& bm, int agent_idx, bool in_combat) noexcept;

    // ── Serialization (COMBAT_REFACTOR_PLAN.md R4/R5) ─────────────────────
    // visibilityMap_ is a cache, but a restored engine that skipped it would report
    // Blocked for every pair until the next computeVisibility — so it round-trips.
    // Keys are stored raw (source << 32 | target) rather than unpacked, so no index
    // is reinterpreted on the way back.
    [[nodiscard]] nlohmann::json to_json() const;
    void from_json(const nlohmann::json& j);

private:
    CombatContext& ctx_;

    // Visibility map: (source_idx, target_idx) -> VisibilityLevel.
    // Computed at turn start and cached until the next turn.
    std::unordered_map<int64_t, VisibilityLevel> visibilityMap_;
};

} // namespace rpg
