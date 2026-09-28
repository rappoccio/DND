#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  spell_effect_store.hpp – persistent spell-effect state (ticking effects,
//  Evoker safe targets, the once-per-turn zone ledger)
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, fourth sub-engine cut (R4e). Owns three of the
//  four members the plan's table originally assigned to "SpellResolver":
//  activeEffects_, safeTargets_ and zoneAppliedTurn_. The row was renamed when
//  this landed, because nothing here resolves a spell — it is the store the
//  resolver writes to.
//
//  WHAT IS NOT HERE, AND WHY. The fourth member, `cast_stack_`, is the cast
//  interrupt flow's park/resume state: stepTopCast and advanceCast touch
//  `pending_decision_` and `decider_`, and the generic submitDecision (in
//  combat_movement.cpp) reads topCast(). That is ReactionArbiter's state, so
//  the cast stack travels with ReactionArbiter — the same call R4b made for
//  the movement flow.
//
//  The EFFECT LOGIC also stays on CombatEngine: tickEffects' per-tick damage and
//  healing, applyZoneIfNewThisTurn's call to applySpellEffect, zoneSparesTarget's
//  faction rules, and clearEffects' reset of ctx_.turnCounter_. Container here,
//  orchestration there — the line R4c drew for ConditionTracker.
//
//  tickEffects decrements turns_remaining in place while its loop can cascade
//  into damage processing, so it iterates through mutableActiveEffects() — a
//  deliberate transitional seam, like ConditionTracker::mutableAll(), to be
//  removed if the tick logic itself ever moves here.
//
//  No CombatContext& member (R4b's rule): nothing here rolls or logs. The zone
//  ledger takes the current turn counter as an argument instead of reading it.
//
//  Serialization writes the SAME three top-level snapshot keys the engine wrote
//  before this cut ("active_effects", "safe_targets", "zone_applied_turn"), not a
//  nested object — R5's obligation that a member which moves keeps its JSON key,
//  or existing saves silently stop restoring it. The bodies live in
//  combat_serialization.cpp, next to ActiveEffect's mapping and the keyed-map
//  helpers they use, so this header gains no template instantiations.
// ─────────────────────────────────────────────────────────────────────────────

#include "combat_types.hpp"   // ActiveEffect

#include <algorithm>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include <nlohmann/json.hpp>

namespace rpg {

class SpellEffectStore {
public:
    // ── Ticking effects (duration > 1 spells; see CombatEngine::tickEffects) ──
    [[nodiscard]] const std::vector<ActiveEffect>& activeEffects() const noexcept { return activeEffects_; }

    void addActiveEffect(const ActiveEffect& fx) { activeEffects_.push_back(fx); }

    // Mutable access, for tickEffects' in-place decrement. Transitional seam — see the file header.
    [[nodiscard]] std::vector<ActiveEffect>& mutableActiveEffects() noexcept { return activeEffects_; }

    // Drop every effect with turns_remaining <= 0, preserving the order of the rest.
    void eraseExpiredEffects() {
        auto expired = [](const ActiveEffect& fx) { return fx.turns_remaining <= 0; };
        activeEffects_.erase(
            std::remove_if(activeEffects_.begin(), activeEffects_.end(), expired),
            activeEffects_.end());
    }

    // ── Evoker safe targets: caster_idx -> indices excluded from its AoEs ──
    void setSafeTargets(int caster_idx, std::vector<int> targets) noexcept {
        safeTargets_[caster_idx] = std::move(targets);
    }
    [[nodiscard]] std::vector<int> getSafeTargets(int caster_idx) const {
        auto it = safeTargets_.find(caster_idx);
        return it == safeTargets_.end() ? std::vector<int>{} : it->second;
    }
    [[nodiscard]] bool isSafeTarget(int caster_idx, int target_idx) const noexcept {
        auto it = safeTargets_.find(caster_idx);
        return it != safeTargets_.end() &&
               std::find(it->second.begin(), it->second.end(), target_idx) != it->second.end();
    }

    // ── Persistent-zone "once per turn" ledger ─────────────────────────────
    // Maps (effect_id, agent_idx) -> the turn counter when that zone last applied to that
    // agent. The key is packed exactly as applyZoneIfNewThisTurn always packed it; the
    // snapshot stores it raw.
    [[nodiscard]] static int64_t zoneKey(int effect_id, int target_idx) noexcept {
        return (static_cast<int64_t>(effect_id) << 32)
             ^ static_cast<int64_t>(static_cast<uint32_t>(target_idx));
    }
    [[nodiscard]] bool zoneAppliedOnTurn(int64_t key, int turn) const noexcept {
        auto it = zoneAppliedTurn_.find(key);
        return it != zoneAppliedTurn_.end() && it->second == turn;
    }
    void markZoneApplied(int64_t key, int turn) { zoneAppliedTurn_[key] = turn; }

    // clearEffects' container half: the ticking effects and the zone ledger. Safe targets
    // are a GUI-configured per-caster setting and clearEffects never cleared them.
    void clearEffectsAndZones() noexcept {
        activeEffects_.clear();
        zoneAppliedTurn_.clear();
    }

    // ── Serialization (COMBAT_REFACTOR_PLAN.md R4/R5) ─────────────────────
    // Writes/reads three TOP-LEVEL keys of the engine snapshot `j`, unchanged from before
    // this cut. Defined in combat_serialization.cpp.
    void to_json(nlohmann::json& j) const;
    void from_json(const nlohmann::json& j);

private:
    std::vector<ActiveEffect> activeEffects_;
    std::unordered_map<int, std::vector<int>> safeTargets_;
    std::unordered_map<int64_t, int> zoneAppliedTurn_;
};

} // namespace rpg
