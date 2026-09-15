#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  condition_tracker.hpp – the active spell-applied condition store
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, third cut (R4c). Owns the four members the
//  plan's sub-engine table assigns to ConditionTracker: activeAgentConditions_,
//  nextConditionId_, and the pre-transformation stat snapshots
//  (petrifySnapshots_ / gaseousSnapshots_, whose structs move here too).
//
//  This is the first cut where the member is genuinely SHARED — the plan's
//  opening analysis named activeAgentConditions_ and pending_decision_ as the
//  only two — so the boundary is drawn differently from R4a/R4b:
//
//    · The CONTAINER and its bookkeeping live here: stamp an id, append, look
//      up by id, erase by id, drop a batch of ids, hand out the list.
//    · The EFFECT logic stays on CombatEngine: addAgentCondition's ~230 lines
//      of per-condition application, onConditionEnded's teardown chokepoint,
//      resolveDelayedEffect, and the two tick drivers. Those call into damage,
//      spells, concentration and every applyXxx — they are engine orchestration
//      that happens to write to this container, not container logic.
//
//  The 53 call sites that reached in as `activeAgentConditions_` are almost all
//  read-only range-for loops; they now read `conditions_.all()`. Only the tick
//  drivers mutate in place, through mutableAll() — a deliberate transitional
//  seam, narrow and documented, to be removed when the tick logic itself moves.
//
//  Method bodies live in combat_conditions.cpp rather than inline here, so this
//  header needs only a forward declaration of ActiveAgentCondition and combat.hpp
//  keeps NOT including battle_map.hpp (it forward-declares today; a header-only
//  tracker would have forced the full 59 KB header into every TU that includes
//  combat.hpp).
//
//  Serializable per plan decision #4 — and this is the payload R5 and
//  MULTIPLAYER_PLAN.md actually care about: active conditions are the single
//  biggest chunk of real per-encounter combat state.
// ─────────────────────────────────────────────────────────────────────────────

#include "damage.hpp"   // NumMagicDamage_t / NumPhysicalDamage_t for the snapshot arrays

#include <array>
#include <unordered_map>
#include <vector>

#include <nlohmann/json.hpp>

namespace rpg {

struct ActiveAgentCondition;   // defined in battle_map.hpp

// Pre-Petrified snapshot so curePetrified (Greater Restoration) can restore a creature's real
// speeds and damage multipliers — applyPetrified overwrites them (speed 0, all 0.5×) and discards
// the originals. Keyed by agent index. Session-only: a save taken mid-Petrify loses this, so
// curePetrified falls back to normalising the 0.5× multipliers (speeds unrecoverable).
struct PetrifySnapshot {
    int speed_walk = 0, speed_fly = 0, speed_swim = 0, speed_burrow = 0;
    std::array<float, NumMagicDamage_t>    magic_mult{};
    std::array<float, NumPhysicalDamage_t> phys_mult{};
};

// Pre-Gaseous-Form snapshot so endGaseousForm can restore a creature's real speeds and physical
// damage multipliers — applyGaseousForm overwrites them (fly-only Speed 20, B/P/S set to 0.5×/0×).
// Keyed by agent index. Session-only, mirroring PetrifySnapshot (a mid-form save loses it).
struct GaseousSnapshot {
    int speed_walk = 0, speed_fly = 0, speed_swim = 0, speed_burrow = 0;
    std::array<float, NumPhysicalDamage_t> phys_mult{};
};

class ConditionTracker {
public:
    // ── Condition lifecycle primitives ────────────────────────────────────
    // nextId() and append() are deliberately two calls rather than one add():
    // addAgentCondition stamps the id FIRST, then runs its long apply logic — which
    // can itself add conditions — and appends LAST. Merging them would reorder the
    // container relative to the ids, which is observable.
    [[nodiscard]] int nextId() noexcept { return nextConditionId_++; }
    void append(const ActiveAgentCondition& cond);

    [[nodiscard]] const std::vector<ActiveAgentCondition>& all() const noexcept { return active_; }

    // Mutable access, for the two tick drivers that decrement turns_remaining in place.
    // Transitional seam — see the file header.
    [[nodiscard]] std::vector<ActiveAgentCondition>& mutableAll() noexcept { return active_; }

    // Erase the entry with this id, copying it into `out` first. False if there is none.
    // The copy-then-erase order matters: the caller's teardown can cascade back into this
    // container, so the entry must already be gone before the copy is handed over.
    bool take(int condition_id, ActiveAgentCondition& out);

    // Drop every entry whose id appears in `ids`, preserving the order of the survivors.
    void dropByIds(const std::vector<int>& ids);

    // ── Pre-transformation stat snapshots ─────────────────────────────────
    [[nodiscard]] bool hasPetrifySnapshot(int agent_idx) const noexcept {
        return petrify_.find(agent_idx) != petrify_.end();
    }
    void storePetrifySnapshot(int agent_idx, const PetrifySnapshot& snap) { petrify_[agent_idx] = snap; }
    // Pointer into the map, or nullptr. Read what you need, then erase — mirroring the
    // find/read/erase the callers did directly against the map.
    [[nodiscard]] const PetrifySnapshot* findPetrifySnapshot(int agent_idx) const noexcept {
        auto it = petrify_.find(agent_idx);
        return (it != petrify_.end()) ? &it->second : nullptr;
    }
    void erasePetrifySnapshot(int agent_idx) noexcept { petrify_.erase(agent_idx); }

    [[nodiscard]] bool hasGaseousSnapshot(int agent_idx) const noexcept {
        return gaseous_.find(agent_idx) != gaseous_.end();
    }
    void storeGaseousSnapshot(int agent_idx, const GaseousSnapshot& snap) { gaseous_[agent_idx] = snap; }
    [[nodiscard]] const GaseousSnapshot* findGaseousSnapshot(int agent_idx) const noexcept {
        auto it = gaseous_.find(agent_idx);
        return (it != gaseous_.end()) ? &it->second : nullptr;
    }
    void eraseGaseousSnapshot(int agent_idx) noexcept { gaseous_.erase(agent_idx); }

    // ── Serialization (COMBAT_REFACTOR_PLAN.md R4/R5) ─────────────────────
    // ActiveAgentCondition lives in battle_map.hpp and gets its JSON mapping as free
    // functions in combat_conditions.cpp rather than as members, so battle_map.hpp —
    // included by essentially everything — is not touched and does not gain a
    // nlohmann dependency.
    [[nodiscard]] nlohmann::json to_json() const;
    void from_json(const nlohmann::json& j);

private:
    // Active spell-applied conditions (Hold Person, Stun, etc.)
    std::vector<ActiveAgentCondition> active_;
    int nextConditionId_{0};

    std::unordered_map<int, PetrifySnapshot> petrify_;
    std::unordered_map<int, GaseousSnapshot> gaseous_;
};

} // namespace rpg
