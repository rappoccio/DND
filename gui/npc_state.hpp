#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  npc_state.hpp – NPC-automation state (the in-flight automated turn, the
//  tuning-config cache, the Level 5/6 models and policy, the latest decision)
// ─────────────────────────────────────────────────────────────────────────────
//
//  R4 of COMBAT_REFACTOR_PLAN.md, fifth sub-engine cut. Owns every member the
//  engine kept under "NPC automation internals": npc_turn_ (the resume point of
//  an automated turn parked at a reaction window), the npc_automation_config.json
//  cache, the one-shot "Level 5/6 is untrained" log guard, the archetype models,
//  the installed policy, the forced macro-action, the policy's pending exception
//  and the last fresh-turn decision.
//
//  A CONTAINER, NOT THE DRIVER. The plan's row was called NpcDriver and was
//  renamed NpcState when this landed (agreed with the user 2026-11-18), because
//  what moved is state, as in R4c and R4e. The turn logic stays on CombatEngine:
//  runNpcTurn, dispatchNpcTurn and the executors (runWeaponTurn, runAoeTurn, runCasterTurn,
//  runFleeTurn, …) drive the turn through beginAttack / beginCast / beginMove,
//  which park on pending_decision_ — ReactionArbiter's state. Moving them before
//  that sub-engine exists would split the park/resume flow across two owners.
//
//  The executors bind `NpcTurnState& st = npc_.turn();` and mutate the struct's
//  fields throughout their phase machines, so turn() hands out a mutable
//  reference. That is a deliberate transitional seam, like ConditionTracker's
//  mutableAll(): the honest statement that the executors still live outside.
//
//  Members that were `mutable` on the engine stay mutable here, behind const
//  methods, because the const planners and npcDecide write them (the config lazy
//  load, the log guard, the policy error). Nothing here rolls or logs, so there
//  is no CombatContext& (R4b's rule).
//
//  Serialization: only the turn is snapshot state. CombatEngine::snapshot()
//  still writes it under the same top-level "npc_turn" key, through turn() — R5's
//  rule that a moved member keeps its JSON key. The rest is deliberately not in a
//  snapshot (see combat_serialization.cpp's header).
//
//  loadConfig()'s body lives in combat_turn.cpp, next to the npcLowerName helper
//  it uses, so this header needs no <fstream> or JSON include.
// ─────────────────────────────────────────────────────────────────────────────

#include "combat_types.hpp"   // NpcTurnState, NpcDecision, NpcMacroAction, kNpcArchetypeCount

#include <array>
#include <cstddef>
#include <exception>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace rpg {

class NpcPolicy;   // combat.hpp; held by shared_ptr only

class NpcState {
public:
    // ── The in-flight automated turn ──
    // Mutable access for the executors' phase machines. Transitional seam — see the file header.
    [[nodiscard]] NpcTurnState&       turn() noexcept       { return turn_; }
    [[nodiscard]] const NpcTurnState& turn() const noexcept { return turn_; }
    // The `active && agent_idx == idx` test every resume check spells out.
    [[nodiscard]] bool turnActiveFor(int agent_idx) const noexcept {
        return turn_.active && turn_.agent_idx == agent_idx;
    }

    // ── npc_automation_config.json cache (lazy; see loadConfig in combat_turn.cpp) ──
    [[nodiscard]] const std::vector<std::string>& controlPriority() const noexcept {
        loadConfig();
        return control_priority_;
    }
    [[nodiscard]] double healThreshold() const noexcept {
        loadConfig();
        return heal_threshold_fraction_;
    }
    [[nodiscard]] const std::set<std::string>& classificationIgnore() const noexcept {
        loadConfig();
        return classification_ignore_;
    }

    // ── One-time "Level 5/6 clamps to Level 4" warning guard ──
    [[nodiscard]] bool nnLevelWarned() const noexcept { return nn_level_warned_; }
    void markNnLevelWarned() const noexcept { nn_level_warned_ = true; }

    // ── Level 5/6 archetype models (Step 4 stand-in), indexed by NpcArchetype ──
    [[nodiscard]] const std::vector<NpcAutomationStrategy>& model(NpcArchetype a) const noexcept {
        return models_[static_cast<std::size_t>(a)];
    }
    void setModel(NpcArchetype a, std::vector<NpcAutomationStrategy> ranked) {
        models_[static_cast<std::size_t>(a)] = std::move(ranked);
    }
    void clearModels() noexcept {
        for (auto& m : models_) m.clear();
    }
    [[nodiscard]] bool anyModel() const noexcept {
        for (const auto& m : models_)
            if (!m.empty()) return true;
        return false;
    }

    // ── The latest fresh-turn decision (trace / Playback HUD readout) ──
    [[nodiscard]] NpcDecision&       lastDecision() noexcept       { return last_decision_; }
    [[nodiscard]] const NpcDecision& lastDecision() const noexcept { return last_decision_; }

    // ── The installed policy (Step 5) ──
    [[nodiscard]] const std::shared_ptr<NpcPolicy>& policy() const noexcept { return policy_; }
    void setPolicy(std::shared_ptr<NpcPolicy> p) noexcept { policy_ = std::move(p); }
    void clearPolicy() noexcept { policy_.reset(); }

    // ── The macro-action executeMacroAction is running (set for the duration of the call) ──
    [[nodiscard]] std::optional<NpcMacroAction>&       forcedMacro() noexcept       { return forced_macro_; }
    [[nodiscard]] const std::optional<NpcMacroAction>& forcedMacro() const noexcept { return forced_macro_; }

    // ── An exception the policy threw inside the noexcept npcDecide ──
    void setPolicyError(std::exception_ptr e) const noexcept { policy_error_ = std::move(e); }
    [[nodiscard]] std::exception_ptr takePolicyError() const noexcept {
        return std::exchange(policy_error_, nullptr);
    }

private:
    void loadConfig() const noexcept;   // combat_turn.cpp

    NpcTurnState turn_{};   // resume point of an in-flight automated turn (parks at reaction windows)

    // NPC-automation tuning knobs (gui/npc_automation_config.json), loaded ONCE and cached. Mutable so the
    // const planners can lazy-load on first use. control_priority = DM-authored order PreferControl walks
    // (Step 8); heal_threshold_fraction = the missing-HP gate PreferHeal casts below (Step 9). Falls back to
    // baked-in defaults if the file is absent so the planners work without it.
    mutable bool                     config_loaded_ = false;
    mutable std::vector<std::string> control_priority_{};
    mutable double                   heal_threshold_fraction_ = 0.5;
    mutable std::set<std::string>    classification_ignore_{};  // lowercased names (role classification)

    // Mutable: resolveStrategy / npcDecide are const.
    mutable bool nn_level_warned_ = false;

    // Neither the models nor the decision is gameplay state, so neither is in a snapshot.
    std::array<std::vector<NpcAutomationStrategy>, kNpcArchetypeCount> models_{};
    NpcDecision last_decision_{};

    // The installed policy (not in a snapshot), and the forced macro-action.
    std::shared_ptr<NpcPolicy>    policy_{};
    std::optional<NpcMacroAction> forced_macro_{};
    mutable std::exception_ptr    policy_error_{};
};

} // namespace rpg
