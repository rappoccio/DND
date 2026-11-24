// ─────────────────────────────────────────────────────────────────────────────
//  combat_reactions.cpp  –  CombatEngine park/resume reaction flow
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The four interruptible flows that can park at a reaction window and resume through
//  submitDecision. Their state lives in ReactionArbiter (reaction_arbiter.hpp, R4g); the
//  flow bodies live here (COMBAT_REFACTOR_PLAN.md R4h, a pure TU move — bodies unchanged).
//  Sections:
//    · Turn start  — turnStartReactors, turnStartOptions, applyTurnStartReaction,
//                    advanceTurnStart, beginTurnFlow (R4's second mis-grouping, from
//                    combat_riders.cpp; the Branches/Vitality features themselves stay there)
//    · Movement    — applyReactionResponse, advanceMove, beginMove, submitDecision (the single
//                    resume point of all four flows), resolveMove (from combat_movement.cpp)
//    · Attack      — beginAttack, advanceAttack (from combat_attack.cpp)
//    · Cast stack  — pushCounterspell, resolveCounterspellEffect, stepTopCast, finalizeAndPop,
//                    advanceCast, beginCast, resolveCast (from combat_spells.cpp)
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <algorithm>
#include <string>
#include <utility>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Turn start — the OnTurnStartNearby window (beginTurn)
// ─────────────────────────────────────────────────────────────────────────────

std::vector<int> CombatEngine::turnStartReactors(const BattleMap& bm, int source) const
{
    const int n = static_cast<int>(bm.placedAgents().size());
    std::vector<int> out;
    // Vitality of the Tree fires on the source's OWN turn start, so the source itself is a reactor.
    if (canVitalityOfTheTree(bm, source)) out.push_back(source);
    for (int i = 0; i < n; ++i) {
        if (i == source) continue;
        if (canBranchesOfTree(bm, i, source)) out.push_back(i);
    }
    return out;
}

std::vector<ReactionOption> CombatEngine::turnStartOptions(const BattleMap& bm, int reactor, int source) const
{
    std::vector<ReactionOption> opts;
    if (reactor == source) {
        // The source's own turn-start self-option (free, once per turn — needs a target pick).
        if (canVitalityOfTheTree(bm, source))
            opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                          "Vitality of the Tree — grant Xd6 temp HP (free)",
                                          "VitalityOfTheTree"});
    } else if (canBranchesOfTree(bm, reactor, source)) {
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Branches of the Tree — STR save or teleported + Speed 0 (reaction)",
                                      "BranchesOfTheTree"});
    }
    opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

void CombatEngine::applyTurnStartReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // Skip / invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;                                     // Skip
    if (opt.feature == "BranchesOfTheTree") (void)applyBranchesOfTree(bm, ctx.reactor_idx, ctx.source_idx);
    else if (opt.feature == "VitalityOfTheTree")
        // Self-option (reactor == source); resp.target_idx is the chosen creature within 10 ft.
        (void)applyVitalityOfTheTree(bm, ctx.source_idx, resp.target_idx);
}

FlowStatus CombatEngine::advanceTurnStart(BattleMap& bm)
{
    InFlightTurn& t = rx_.turn();
    // A creature whose turn is skipped (paralyzed/unconscious/Wild-Magic) or that is down isn't
    // meaningfully "present" to be reacted to — open no window (completes immediately).
    const bool open = !t.result.turn_skipped && t.agent_idx >= 0
                   && t.agent_idx < static_cast<int>(bm.placedAgents().size())
                   && bm.getAgentStats(t.agent_idx).hp_cur > 0;
    if (open && !t.window_built) {
        t.reactors     = turnStartReactors(bm, t.agent_idx);
        t.window_built = true;
    }
    while (open && t.cursor < t.reactors.size()) {
        const int reactor = t.reactors[t.cursor];
        const auto opts = turnStartOptions(bm, reactor, t.agent_idx);
        if (opts.size() <= 1) { ++t.cursor; continue; }            // only Skip → no longer qualifies
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnTurnStartNearby;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = t.agent_idx;
        ctx.options     = opts;
        if (t.interactive) {                                       // GUI suspends; resumes via submitDecision
            rx_.park(ctx);
            return FlowStatus::AwaitingDecision;
        }
        applyTurnStartReaction(bm, ctx, decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{});
        ++t.cursor;                                                // auto/RL inline
    }
    rx_.unpark();
    t.active = false;
    return FlowStatus::Completed;
}

FlowStatus CombatEngine::beginTurnFlow(BattleMap& bm, int agent_idx, bool interactive)
{
    rx_.turn()             = InFlightTurn{};
    rx_.turn().active      = true;
    rx_.turn().interactive = interactive;
    rx_.turn().agent_idx   = agent_idx;
    rx_.turn().result      = beginTurn(bm, agent_idx);        // the existing synchronous body
    return advanceTurnStart(bm);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Movement — Opportunity Attacks (LeftReach) and the shared resume point
// ─────────────────────────────────────────────────────────────────────────────

void
CombatEngine::applyReactionResponse(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // skip/invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind == ReactionOption::Skip) return;

    const auto& agents = bm.placedAgents();
    if (ctx.source_idx < 0 || ctx.source_idx >= static_cast<int>(agents.size())) return;
    const int reactor = ctx.reactor_idx;
    const int target  = (resp.target_idx >= 0) ? resp.target_idx : ctx.source_idx;

    // Place the mover on the cell it is leaving so the OA's melee range check is correct.
    const Cell saved = agents[static_cast<std::size_t>(ctx.source_idx)].origin;
    bm.setAgentPosition(ctx.source_idx, ctx.source_cell);

    // Speed→0 on an opportunity-attack hit: shared by two features whose reactor HITS the mover with
    // its OA, freezing the mover's Speed for the rest of the turn (it stops where the OA triggered).
    //   • Sentinel feat clause 1 (any Sentinel-feated reactor).
    //   • Paladin Oath of Vengeance L7 Relentless Avenger (adds the rider to a normal OA hit).
    const Agent::Stats rstats = bm.getAgentStats(reactor);
    const bool reactor_has_sentinel = rstats.has_sentinel;
    const bool reactor_relentless =
        rstats.hasClass(CharacterClass::Paladin) &&
        rstats.paladin_oath == OathOfVengeancePath && rstats.classLevel(CharacterClass::Paladin) >= 7;
    bool sentinel_hit = false;   // an OA hit that reduces the mover's Speed to 0 (either source)

    if (opt.kind == ReactionOption::Weapon) {
        Attack oa{reactor, target, opt.index};
        oa.opportunity = true;   // a Speedy target imposes Disadvantage on the OA roll
        AttackResult r = executeAction(bm, oa);
        const bool halts_mover = (reactor_has_sentinel || reactor_relentless) && target == ctx.source_idx;
        const char* oa_label = reactor_has_sentinel ? "Sentinel OA"
                             : (reactor_relentless ? "Relentless Avenger OA" : "OA");
        // Log the to-hit result (executeAction logs damage/conditions but not the roll). The old
        // Python OA path logged this; it now lives here so OA hits/misses aren't silent.
        if (!r.valid) {
            log_("{}: {} can't reach {}", oa_label,
                 agentName(bm, reactor), agentName(bm, target));
        } else if (r.hit) {
            sentinel_hit = halts_mover;
            log_("{}: {} hits {} — roll {} vs AC {}{}{}{}",
                 oa_label,
                 agentName(bm, reactor), agentName(bm, target), r.total_roll, r.target_ac,
                 r.critical ? " (CRIT)" : "", r.target_down ? " — DOWN" : "",
                 (sentinel_hit && !r.target_down) ? " — Speed → 0" : "");
        } else {
            log_("{}: {} misses {} — roll {} vs AC {}", oa_label,
                 agentName(bm, reactor), agentName(bm, target), r.total_roll, r.target_ac);
        }
        rx_.move().results.push_back(r);
    } else {  // Spell
        SpellAction sa;
        sa.caster_idx     = reactor;
        sa.spell_idx      = opt.index;
        sa.target_indices = {target};
        (void)executeSpell(bm, sa);
    }

    // Consume the reactor's reaction for the round.
    Agent::Conditions rc = bm.getAgentConditions(reactor);
    rc.reaction_used = true;
    bm.setAgentConditions(reactor, rc);

    // Stop-on-down: if the OA dropped the mover, leave it where it fell; otherwise restore it to its
    // starting cell so the final committed move runs from the true origin. A Sentinel OA hit halts the
    // mover at the provoke cell (speed → 0) — advanceMove commits the partial move there and zeroes the
    // remaining budget, so the run from `saved` (origin) is still needed for the budgeted/terrain commit.
    if (bm.getAgentStats(ctx.source_idx).hp_cur <= 0) {
        rx_.move().mover_down = true;
        bm.setAgentPosition(ctx.source_idx, ctx.source_cell);
    } else {
        // An OA can inflict an incapacitating condition (Stunned/Paralyzed/Incapacitated — all route
        // through applyIncapacitated) on the mover as a rider. An incapacitated creature's Speed drops
        // to 0 and it can take no further actions this turn, so — like a Sentinel hit — the move halts
        // at the provoke cell and advanceMove zeroes the remaining movement budget. Blocking further
        // *actions* is handled GUI-side by the Incapacitated action-gate, which now sees the condition.
        const bool mover_incapacitated = bm.getAgentConditions(ctx.source_idx).incapacitated;
        if (sentinel_hit || mover_incapacitated) {
            rx_.move().mover_halted = true;
            rx_.move().halt_cell    = ctx.source_cell;   // stop where the OA triggered
        }
        bm.setAgentPosition(ctx.source_idx, saved);
    }
}

FlowStatus
CombatEngine::advanceMove(BattleMap& bm)
{
    InFlightMove& m = rx_.move();
    while (m.cursor < m.provokes.size() && !m.mover_down && !m.mover_halted) {
        const ProvokeEvent ev = m.provokes[m.cursor];
        // The reactor may have lost eligibility since detection (downed/used by a prior OA).
        if (ev.reactor < 0 ||
            !canTakeReaction(bm.getAgentConditions(ev.reactor)) ||
            bm.getAgentStats(ev.reactor).hp_cur <= 0) {
            ++m.cursor;
            continue;
        }
        ReactionCtx ctx = buildReactionCheckpoint(bm, ReactionWindow::LeftReach,
                                                  ev.reactor, m.mover_idx, ev.left_cell);
        if (m.interactive) {
            rx_.park(ctx);   // suspend; GUI resumes via submitDecision
            return FlowStatus::AwaitingDecision;
        }
        const ReactionResponse resp = decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{};
        applyReactionResponse(bm, ctx, resp);
        ++m.cursor;
    }

    // All provokes resolved (or the mover went down / was halted) — commit.
    rx_.unpark();
    if (!m.mover_down) {
        // A Sentinel OA stops the mover at the provoke cell; otherwise it completes the move to dest.
        const Cell commit = m.mover_halted ? m.halt_cell : m.dest;
        (void)moveAgent(bm, m.mover_idx, commit, m.type);   // real budgeted move + terrain/zone checks
        if (m.mover_halted) {
            // Sentinel / Relentless Avenger: speed becomes 0 for the rest of the turn. Zero BOTH the engine budgets and
            // the Agent's own remaining (BattleMap::moveAgent reads the latter) so no further movement —
            // including a fresh begin_move — is possible this turn.
            mv_.seedMoveBudgets(m.mover_idx, 0, 0, 0, 0);
            const auto& agents = bm.placedAgents();
            if (m.mover_idx >= 0 && m.mover_idx < static_cast<int>(agents.size()))
                agents[static_cast<std::size_t>(m.mover_idx)].agent->initMovement(0, 0, 0, 0);
        }
    }
    m.active = false;
    return FlowStatus::Completed;
}

FlowStatus
CombatEngine::beginMove(BattleMap& bm, int idx, Cell dest, MovementType type)
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return FlowStatus::Completed;

    rx_.move()             = InFlightMove{};
    rx_.move().active      = true;
    rx_.move().interactive = true;
    rx_.move().mover_idx   = idx;
    rx_.move().origin      = agents[static_cast<std::size_t>(idx)].origin;
    rx_.move().dest        = dest;
    rx_.move().type        = type;
    rx_.move().provokes    = detectProvokes(bm, idx, rx_.move().origin, dest, type);
    return advanceMove(bm);
}

FlowStatus
CombatEngine::submitDecision(BattleMap& bm, const ReactionResponse& resp)
{
    if (!rx_.parked()) return FlowStatus::Completed;
    const ReactionCtx ctx = rx_.pending().ctx;
    rx_.unpark();
    // Dispatch to whichever interruptible flow is parked. Cast (OnDeclareCast), attack (OnHit), move
    // (LeftReach) and turn-start (OnTurnStartNearby) share one transport; only one is active at a time
    // (the decision stack that would allow a reaction-during-reaction arrives later with
    // Counterspell-vs-Counterspell).
    if (rx_.turn().active) {   // OnTurnStartNearby — top-level, never nested inside another flow
        applyTurnStartReaction(bm, ctx, resp);
        ++rx_.turn().cursor;
        return advanceTurnStart(bm);
    }
    if (rx_.attack().active) {
        // Two windows share the in-flight attack: OnD20Seen (multi-reactor cursor, BEFORE the hit) and
        // OnHit Shield (single reactor, no cursor). Advance the d20 cursor on each OnD20Seen resume so
        // a Skip moves to the next reactor; the Shield branch re-enters advanceAttack with the gate
        // already consumed.
        if (ctx.window == ReactionWindow::OnAttackDeclared) {
            // Shadowy Dodge, before the roll: advanceAttack rolls next, with the Disadvantage if taken.
            if (resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                ctx.options[static_cast<std::size_t>(resp.option)].feature == "ShadowyDodge")
                takeShadowyDodge(bm, rx_.attack());
        } else if (ctx.window == ReactionWindow::AfterAttack) {
            // Shadowy Dodge's teleport (the safest cell, or the one the response names), or Masterful
            // Shots (move away — the engine's cell or the named one — then shoot the attacker).
            if (resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                ctx.options[static_cast<std::size_t>(resp.option)].kind == ReactionOption::Feature) {
                const std::string& f = ctx.options[static_cast<std::size_t>(resp.option)].feature;
                if (f == "MasterfulShots" || f == "MasterfulShotsPick")
                    (void)applyMasterfulShots(bm, ctx.reactor_idx, ctx.source_idx,
                                              f == "MasterfulShotsPick" ? resp.cell_col : -1,
                                              f == "MasterfulShotsPick" ? resp.cell_row : -1);
                else
                    shadowyDodgeFollowUp(bm, ctx.reactor_idx, resp.cell_col, resp.cell_row);
            }
        } else if (ctx.window == ReactionWindow::OnD20Seen) {
            applyD20SeenReaction(bm, ctx, resp);
            ++rx_.attack().d20_cursor;
        } else if (rx_.attack().sentinel_parked) {
            // Sentinel at Death's Door (multi-reactor cursor after the defender's OnHit window).
            rx_.attack().sentinel_parked = false;
            if (resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                ctx.options[static_cast<std::size_t>(resp.option)].feature == "SentinelAtDeathsDoor")
                (void)applySentinelAtDeathsDoor(bm, ctx.reactor_idx, rx_.attack().action,
                                                rx_.attack().w, rx_.attack().r);
            ++rx_.attack().sentinel_cursor;
        } else {
            applyAttackReaction(bm, ctx, resp);
        }
        return advanceAttack(bm);
    }
    if (castActive()) {
        // Two windows share the top in-flight cast: OnDeclareCast/OnHit (Counterspell/Shield, `cursor`)
        // and OnSaveFail (reroll a failed save, its own `savefail_cursor`). Advance the matching cursor.
        InFlightCast& c = topCast();
        if (ctx.window == ReactionWindow::AfterSave) {
            // Indomitable Teleport: the cell the response names (none = stay put).
            if (resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                ctx.options[static_cast<std::size_t>(resp.option)].kind == ReactionOption::Feature &&
                !applyIndomitableTeleport(bm, ctx.reactor_idx, resp.cell_col, resp.cell_row))
                log_("{} stays put (Indomitable Teleport)", agentName(bm, ctx.reactor_idx));
        } else if (ctx.window == ReactionWindow::OnSaveFail) {
            applySaveFailReaction(bm, ctx, resp);
            ++c.savefail_cursor;
        } else if (isCounterspellChoice(ctx, resp) &&
                   rx_.casts().size() <= bm.placedAgents().size()) {
            // Counterspell → push a nested cast. Capture the parent caster
            // (ctx.source_idx) before the push, and do NOT touch c afterward (it dangles).
            ++c.cursor;
            castCounterspell(bm, ctx.reactor_idx, ctx.source_idx);
            pushCounterspell(bm, ctx.reactor_idx, ctx.source_idx);
            return advanceCast(bm);
        } else {
            applyCastReaction(bm, ctx, resp);
            ++c.cursor;
        }
        return advanceCast(bm);
    }
    applyReactionResponse(bm, ctx, resp);
    ++rx_.move().cursor;
    return advanceMove(bm);
}

std::vector<AttackResult>
CombatEngine::resolveMove(BattleMap& bm, int idx, Cell dest, MovementType type)
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return {};

    rx_.move()             = InFlightMove{};
    rx_.move().active      = true;
    rx_.move().interactive = false;
    rx_.move().mover_idx   = idx;
    rx_.move().origin      = agents[static_cast<std::size_t>(idx)].origin;
    rx_.move().dest        = dest;
    rx_.move().type        = type;
    rx_.move().provokes    = detectProvokes(bm, idx, rx_.move().origin, dest, type);
    (void)advanceMove(bm);
    return rx_.move().results;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Attack — the weapon-attack windows (OnAttackDeclared, OnD20Seen, OnHit, AfterAttack)
// ─────────────────────────────────────────────────────────────────────────────

// beginAttack — GUI/interactive entry to a weapon attack. Runs phase A
// (determineAdvantage) and the roll (resolveAttack) into the in-flight state, then hands off to
// advanceAttack which opens the Shield window or finalizes. The auto/RL path stays on executeAction
// (inline Shield). Result is read via lastAttackResult(); submitDecision resumes a parked attack.
FlowStatus CombatEngine::beginAttack(BattleMap& bm, const Attack& action)
{
    rx_.attack()             = InFlightAttack{};
    rx_.attack().active      = true;
    rx_.attack().interactive = true;
    rx_.attack().action      = action;
    InFlightAttack& s = rx_.attack();
    if (!determineAdvantage(bm, s)) {            // illegal/blocked attack (s.r stays valid == false)
        last_attack_result_ = s.r;
        s.active = false;
        return FlowStatus::Completed;
    }
    return advanceAttack(bm);
}

// advanceAttack — drive the in-flight attack. If a defender Shield window should open (GUI path only),
// suspend at the OnHit checkpoint; the GUI resumes via submitDecision → applyAttackReaction → here
// again, where the gate is now false/consumed and we finalize. applyAttackResult re-fetches working
// stats, so a Shield cast in the window (its +5 AC / slot spend) is reflected.
FlowStatus CombatEngine::advanceAttack(BattleMap& bm)
{
    InFlightAttack& s = rx_.attack();
    // Shadowy Dodge (Gloom Stalker L15): the target may react BEFORE the d20 is rolled, imposing
    // Disadvantage. Offered once; submitDecision applies the choice and comes back here to roll.
    if (!s.rolled) {
        if (s.interactive && !s.preroll_offered) {
            s.preroll_offered = true;
            if (canShadowyDodge(bm, s.action.target_idx, s.action.attacker_idx)) {
                ReactionCtx ctx;
                ctx.window      = ReactionWindow::OnAttackDeclared;
                ctx.reactor_idx = s.action.target_idx;
                ctx.source_idx  = s.action.attacker_idx;
                ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                                     "Shadowy Dodge (Disadvantage, then teleport)", "ShadowyDodge"});
                ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
                rx_.park(ctx);   // suspend; GUI resumes via submitDecision
                return FlowStatus::AwaitingDecision;
            }
        }
        rollInFlightAttack(bm, s);
    }
    // OnD20Seen window (BEFORE Shield): nearby creatures may lower the roll. Build the reactor list
    // once (post-roll), then offer each in turn. submitDecision advances d20_cursor on each resume, so
    // a Skip simply moves to the next reactor; a lowering reaction that flips the hit to a miss then
    // makes the Shield gate below false.
    if (s.interactive && !s.d20_window_built) {
        s.d20_reactors     = d20SeenReactors(bm, s.action, s.r);
        s.d20_window_built = true;
    }
    while (s.interactive && s.d20_cursor < s.d20_reactors.size()) {
        const int reactor = s.d20_reactors[s.d20_cursor];
        auto opts = d20SeenOptions(bm, reactor, s.action, s.r);   // re-checked: an earlier window may
        if (opts.size() <= 1) { ++s.d20_cursor; continue; }       // have spent this reactor's resource
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnD20Seen;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = s.action.attacker_idx;
        ctx.options     = std::move(opts);
        ctx.d20_value   = s.r.total_roll;
        rx_.park(ctx);           // suspend; GUI resumes via submitDecision
        return FlowStatus::AwaitingDecision;
    }
    // Offer the OnHit defender window (Shield and/or Uncanny Dodge) at most once: on resume after a Skip
    // the hit still stands, so without this guard the gate would stay true and re-park forever (single
    // reactor, no cursor). applyAttackReaction (via submitDecision) spends the one reaction.
    if (s.interactive && !s.onhit_offered) {
        auto opts = defenderOnHitOptions(bm, s.action, s.r);
        if (opts.size() > 1) {
            s.onhit_offered = true;
            ReactionCtx ctx;
            ctx.window      = ReactionWindow::OnHit;
            ctx.reactor_idx = s.action.target_idx;
            ctx.source_idx  = s.action.attacker_idx;
            ctx.options     = std::move(opts);
            rx_.park(ctx);   // suspend; GUI resumes via submitDecision
            return FlowStatus::AwaitingDecision;
        }
        s.onhit_offered = true;   // nothing to offer — don't re-check on a later resume
    }
    // Sentinel at Death's Door window (after the defender's own OnHit window): each eligible Grave
    // cleric in turn, until one halves the hit. submitDecision advances sentinel_cursor on resume.
    if (s.interactive && !s.sentinel_window_built) {
        s.sentinel_reactors     = sentinelAtDeathsDoorReactors(bm, s.action, s.r);
        s.sentinel_window_built = true;
    }
    while (s.interactive && s.sentinel_cursor < s.sentinel_reactors.size()) {
        const int cleric = s.sentinel_reactors[s.sentinel_cursor];
        if (s.r.crit_canceled) break;   // a cleric already used Sentinel on this hit
        if (!s.r.hit || !canSentinelAtDeathsDoor(bm, cleric, s.action.target_idx)) { ++s.sentinel_cursor; continue; }
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnHit;
        ctx.reactor_idx = cleric;
        ctx.source_idx  = s.action.attacker_idx;
        ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                             "Sentinel at Death's Door (halve the damage)", "SentinelAtDeathsDoor"});
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        s.sentinel_parked = true;
        rx_.park(ctx);   // suspend; GUI resumes via submitDecision
        return FlowStatus::AwaitingDecision;
    }
    rx_.unpark();
    if (!s.applied) {
        last_attack_result_ = applyAttackResult(bm, s);
        s.applied = true;
    }
    // Shadowy Dodge, second half: "whether the attack hits or misses, you can then teleport up to
    // 30 feet". Offered once, to a Ranger still on its feet.
    if (s.interactive && s.shadowy_dodge && !s.after_offered) {
        s.after_offered = true;
        const int d = s.action.target_idx;
        if (bm.getAgentStats(d).hp_cur > 0 && !bm.getAgentConditions(d).incapacitated) {
            ReactionCtx ctx;
            ctx.window      = ReactionWindow::AfterAttack;
            ctx.reactor_idx = d;
            ctx.source_idx  = s.action.attacker_idx;
            ctx.options     = shadowyDodgeTeleportOptions();
            rx_.park(ctx);
            return FlowStatus::AwaitingDecision;
        }
    }
    // Masterful Shots (Arcane Archer L18): a missed archer may move away and shoot back. Offered once.
    if (s.interactive && !s.masterful_offered) {
        s.masterful_offered = true;
        if (last_attack_result_.valid && !last_attack_result_.hit &&
            canMasterfulShots(bm, s.action.target_idx, s.action.attacker_idx)) {
            ReactionCtx ctx;
            ctx.window      = ReactionWindow::AfterAttack;
            ctx.reactor_idx = s.action.target_idx;
            ctx.source_idx  = s.action.attacker_idx;
            ctx.options     = masterfulShotsOptions();
            rx_.park(ctx);
            return FlowStatus::AwaitingDecision;
        }
    }
    s.active = false;
    return FlowStatus::Completed;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Cast stack — OnDeclareCast / OnHit / OnSaveFail, nested Counterspell
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::pushCounterspell(BattleMap& bm, int reactor, int target_caster)
{
    // Synthesize a Counterspell SpellAction so the existing castName/canCastCounterspell machinery
    // keeps working, then push it as a nested in-flight cast targeting the parent's caster.
    SpellAction csa{};
    csa.caster_idx     = reactor;
    csa.spell_idx      = agentSpellIndex(bm, reactor, "Counterspell");
    csa.target_indices = { target_caster };
    InFlightCast child{};
    child.active                = true;
    child.interactive           = !rx_.casts().empty() && rx_.casts().back().interactive;  // inherit driver
    child.action                = csa;
    child.is_counterspell       = true;
    child.counter_target_caster = target_caster;
    child.reactors              = declareCastReactors(bm, csa);     // who can counter THIS counterspell
    rx_.casts().push_back(std::move(child));                        // ⚠ any prior back() ref now invalid
}

void CombatEngine::resolveCounterspellEffect(BattleMap& bm, InFlightCast& c)
{
    const int reactor = c.action.caster_idx;             // the counterspeller
    const int target  = c.counter_target_caster;         // the caster being countered
    // The save was pre-rolled in stepTopCast's OnSaveFail window (where Legendary Resistance etc.
    // could rescue it). Fall back to a fresh roll only if that window never ran.
    bool saved = false;
    const SpellSave* pre = nullptr;
    for (const auto& p : c.save_prerolls) if (p.target_idx == target) { pre = &p; break; }
    if (pre) {
        saved = pre->saved;
    } else {
        const int dc = rules::holderSpellSaveDc(bm.placedAgents()[static_cast<std::size_t>(reactor)]);
        const Agent::Stats cs = bm.getAgentStats(target);
        const int save_mod = abilityMod(cs.con) + (cs.save_prof_con ? cs.prof_bonus : 0);
        const int d20 = roll(20), total = d20 + save_mod;
        log_("{} must make a DC {} CON save vs Counterspell (rolled {}{}{} = {})",
             agentName(bm, target), dc, d20, save_mod >= 0 ? "+" : "", save_mod, total);
        saved = total >= dc;
    }
    if (saved) { log_("{} resists — the spell resolves", agentName(bm, target)); return; }
    log_("{}'s spell is countered and fails (its slot is retained)", agentName(bm, target));
    if (rx_.casts().size() >= 2)                          // mark the PARENT (directly below) countered
        rx_.casts()[rx_.casts().size() - 2].countered = true;
}

// One step of cast_stack_.back() through its windows. Operates on a re-fetched back() reference and
// NEVER touches it after a push_back (which would dangle it) — the Counterspell branch captures all
// values it needs before pushing, then returns Pushed immediately.
CombatEngine::CastStep CombatEngine::stepTopCast(BattleMap& bm)
{
    InFlightCast& c = rx_.casts().back();
    const auto& agents = bm.placedAgents();
    std::string castName;                                            // the spell being cast (for option gating)
    if (c.action.caster_idx >= 0 && c.action.caster_idx < static_cast<int>(agents.size())) {
        const auto& spells = bm.getAgentSpells(c.action.caster_idx);
        if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size()))
            castName = spells[static_cast<std::size_t>(c.action.spell_idx)].name;
    }
    while (c.cursor < c.reactors.size() && !c.countered) {
        const int reactor = c.reactors[c.cursor];
        ReactionCtx ctx;
        ctx.window       = ReactionWindow::OnDeclareCast;
        ctx.reactor_idx  = reactor;
        ctx.source_idx   = c.action.caster_idx;
        ctx.spell_idx    = c.action.spell_idx;
        // Build this reactor's options fresh (eligibility may have changed since enumeration). A
        // reactor can be offered both Counterspell and Shield when both apply. A Counterspell can now
        // itself be countered, so the option is offered regardless of castName.
        if (canCastCounterspell(bm, reactor, c.action.caster_idx))
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                "Cast Counterspell vs " + agentName(bm, c.action.caster_idx) + "'s " + castName,
                "Counterspell"});
        if (canSpellThief(bm, reactor, c.action.caster_idx))
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                "Spell Thief: steal " + agentName(bm, c.action.caster_idx) + "'s " + castName +
                " (it makes an INT save)", "SpellThief"});
        if (castName == "Magic Missile" && canCastShield(bm, reactor) &&
            std::find(c.action.target_indices.begin(), c.action.target_indices.end(), reactor)
                != c.action.target_indices.end())
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                                 "Cast Shield (+5 AC, immune to Magic Missile)", "Shield"});
        if (ctx.options.empty()) { ++c.cursor; continue; }           // lost eligibility since enumeration
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        if (c.interactive) {
            rx_.park(ctx);         // suspend; GUI resumes via submitDecision
            return CastStep::Awaiting;
        }
        const ReactionResponse resp = decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{};
        // Counterspell → push a nested cast (defensive depth cap backstops the economy bound).
        if (isCounterspellChoice(ctx, resp) && rx_.casts().size() <= agents.size()) {
            const int target_caster = c.action.caster_idx;           // capture BEFORE the push (c dangles after)
            ++c.cursor;                                              // this reactor is handled in the parent
            castCounterspell(bm, reactor, target_caster);
            pushCounterspell(bm, reactor, target_caster);
            return CastStep::Pushed;                                 // ⚠ do NOT touch c after this
        }
        applyCastReaction(bm, ctx, resp);
        ++c.cursor;
    }

    // ── Single-target spell-attack OnHit Shield window (GUI suspend) ──
    // Once the OnDeclareCast windows close (and the cast wasn't countered), a single-target AttackRoll
    // spell pre-rolls its to-hit here so the target can react with Shield — the spell analog of
    // beginAttack's OnHit window. Only for the interactive (GUI) path and only when the target can
    // actually cast Shield (so the common no-Shield cast still rolls inside executeSpell, in order).
    // The auto/RL path and GUI multi-beam attack spells use maybeDefenderShieldInlineSpell instead.
    // A Counterspell cast is not an AttackRoll spell, so this window self-skips for it.
    if (c.interactive && !c.countered && !c.attack_window_done) {
        c.attack_window_done = true;                                 // evaluate the window at most once
        int  single_target   = (c.action.target_indices.size() == 1) ? c.action.target_indices[0] : -1;
        bool is_attack_spell = false;
        if (single_target >= 0 && c.action.caster_idx >= 0 &&
            c.action.caster_idx < static_cast<int>(agents.size())) {
            const auto& spells = bm.getAgentSpells(c.action.caster_idx);
            if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size()))
                is_attack_spell = (spells[static_cast<std::size_t>(c.action.spell_idx)].attack_type
                                   == Spell::AttackRoll);
        }
        if (is_attack_spell && canCastShield(bm, single_target)) {
            c.preroll        = rollSpellAttack(bm, c.action, single_target, MetamagicNone);
            c.has_preroll    = true;                                 // executeSpell consumes this roll
            c.preroll_target = single_target;
            if (shouldOfferSpellShield(bm, single_target, c.preroll)) {
                ReactionCtx ctx;
                ctx.window      = ReactionWindow::OnHit;
                ctx.reactor_idx = single_target;
                ctx.source_idx  = c.action.caster_idx;
                ctx.spell_idx   = c.action.spell_idx;
                ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                                     "Cast Shield (+5 AC — the spell attack misses)", "Shield"});
                ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
                rx_.park(ctx);     // suspend; GUI resumes via submitDecision
                return CastStep::Awaiting;
            }
        }
    }

    // ── OnSaveFail window: pre-roll a directly-targeted Save spell's saves and let
    // creatures reroll a FAILURE → possible success (Countercharm / Indomitable). Runs for BOTH drivers
    // (interactive suspends; auto resolves inline via the decider, like the OnDeclareCast loop above).
    // AoE-geometry save spells (cone/cube/sphere) are deferred — their target list is resolved inside
    // executeSpell, so only Single/Multiple geometry (targets == action.target_indices) is pre-rolled (§8).
    // A Counterspell cast is not a Save spell, so this window self-skips for it.
    if (!c.countered && !c.save_window_built) {
        c.save_window_built = true;
        // A Counterspell's own CON save (rolled by the countered caster) goes through this same
        // window, so Legendary Resistance / Indomitable / … are offered on a failure. Pre-rolled
        // here; resolveCounterspellEffect consumes the (possibly rescued) result at pop time.
        if (c.is_counterspell) {
            const int target = c.counter_target_caster;
            if (target >= 0 && target < static_cast<int>(agents.size())) {
                const int reactor = c.action.caster_idx;    // the counterspeller
                const Agent::Stats cs = bm.getAgentStats(target);
                SpellSave ss{};
                ss.target_idx = target;
                ss.ability    = SaveCon;
                ss.dc         = rules::holderSpellSaveDc(agents[static_cast<std::size_t>(reactor)]);
                ss.save_mod   = abilityMod(cs.con) + (cs.save_prof_con ? cs.prof_bonus : 0);
                ss.d20        = roll(20);
                reevaluateSave(ss);
                log_("{} must make a DC {} CON save vs Counterspell (rolled {}{}{} = {})",
                     agentName(bm, target), ss.dc, ss.d20, ss.save_mod >= 0 ? "+" : "",
                     ss.save_mod, ss.total);
                c.save_prerolls.push_back(ss);
                for (int r : saveFailReactors(bm, c.action, ss))
                    c.savefail_pairs.emplace_back(target, r);
            }
        }
        bool is_save_spell = false;
        if (c.action.caster_idx >= 0 && c.action.caster_idx < static_cast<int>(agents.size())) {
            const auto& spells = bm.getAgentSpells(c.action.caster_idx);
            if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size())) {
                const Spell& sp = spells[static_cast<std::size_t>(c.action.spell_idx)];
                is_save_spell = (sp.attack_type == Spell::Save) &&
                                (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple);
            }
        }
        if (is_save_spell) {
            // rollSpellSave only reads Heightened, and a cast may carry it in either Metamagic slot
            // (Sorcery Incarnate / the Seeking pairing). The SP for it are spent inside executeSpell,
            // which consumes these prerolls — so the requested option drives the preroll.
            const MetamagicOption pre_mm =
                (c.action.metamagic  == MetamagicHeightened ||
                 c.action.metamagic2 == MetamagicHeightened) ? MetamagicHeightened : MetamagicNone;
            for (int tgt : c.action.target_indices)
                c.save_prerolls.push_back(rollSpellSave(bm, c.action, tgt, pre_mm));
            c.has_save_preroll = true;                              // executeSpell consumes these
            for (const SpellSave& ss : c.save_prerolls)
                for (int reactor : saveFailReactors(bm, c.action, ss))
                    c.savefail_pairs.emplace_back(ss.target_idx, reactor);
        }
    }
    for (;;) {
        // Indomitable Teleport (Arcane Archer L15): an Indomitable reroll just succeeded, so the archer
        // may teleport before the next failed save is offered. Owed once per success.
        if (c.indomitable_teleport_reactor >= 0) {
            const int who = c.indomitable_teleport_reactor;
            c.indomitable_teleport_reactor = -1;
            if (!canIndomitableTeleport(bm, who)) continue;
            ReactionCtx ctx;
            ctx.window      = ReactionWindow::AfterSave;
            ctx.reactor_idx = who;
            ctx.source_idx  = who;
            ctx.spell_idx   = c.action.spell_idx;
            ctx.options     = indomitableTeleportOptions();
            if (c.interactive) {
                rx_.park(ctx);    // suspend; submitDecision teleports to the picked cell
                return CastStep::Awaiting;
            }
            const ReactionResponse resp = decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{};
            if (resp.option >= 0 && resp.option < static_cast<int>(ctx.options.size()) &&
                ctx.options[static_cast<std::size_t>(resp.option)].kind == ReactionOption::Feature)
                (void)applyIndomitableTeleport(bm, who, resp.cell_col, resp.cell_row);
            continue;
        }
        if (c.savefail_cursor >= c.savefail_pairs.size()) break;
        const int save_target = c.savefail_pairs[c.savefail_cursor].first;
        const int reactor     = c.savefail_pairs[c.savefail_cursor].second;
        SpellSave* ss = nullptr;
        for (auto& p : c.save_prerolls) if (p.target_idx == save_target) { ss = &p; break; }
        // Re-gate: an earlier reaction may have flipped this save to a success or spent the resource.
        auto opts = (ss && !ss->saved) ? saveFailOptions(bm, reactor, c.action, *ss)
                                       : std::vector<ReactionOption>{};
        if (opts.size() <= 1) { ++c.savefail_cursor; continue; }   // only Skip / nothing left to offer
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnSaveFail;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = save_target;                             // the creature that failed the save
        ctx.spell_idx   = c.action.spell_idx;
        ctx.d20_value   = ss->total;
        ctx.options     = opts;
        if (c.interactive) {
            rx_.park(ctx);        // suspend; GUI resumes via submitDecision
            return CastStep::Awaiting;
        }
        applySaveFailReaction(bm, ctx, decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{});
        ++c.savefail_cursor;
    }

    return CastStep::Completed;
}

// Resolve cast_stack_.back() and pop it. No push happens in here, so the reference stays valid.
void CombatEngine::finalizeAndPop(BattleMap& bm)
{
    InFlightCast& c = rx_.casts().back();
    if (c.is_counterspell) {
        if (!c.countered)                                 // not itself countered → it works
            resolveCounterspellEffect(bm, c);             // deferred CON save → maybe mark parent .countered
        // a counterspell yields no SpellResult of interest
    } else if (!c.countered) {
        c.result = executeSpell(bm, c.action);            // normal resolution (slot spent inside, late)
    }
    c.active = false;
    const bool bottom = (rx_.casts().size() == 1);
    const SpellResult r = c.result;
    const bool cnt = c.countered;
    rx_.casts().pop_back();
    if (bottom) { last_cast_result_ = r; last_cast_countered_ = cnt; }
}

FlowStatus CombatEngine::advanceCast(BattleMap& bm)
{
    while (!rx_.casts().empty()) {
        const CastStep st = stepTopCast(bm);               // runs back()'s windows; may push/suspend
        if (st == CastStep::Awaiting) return FlowStatus::AwaitingDecision;  // GUI suspend
        if (st == CastStep::Pushed)   continue;            // a counterspell went on top → loop to it
        finalizeAndPop(bm);                                // Completed → resolve + pop back()
    }
    rx_.unpark();
    return FlowStatus::Completed;
}

FlowStatus CombatEngine::beginCast(BattleMap& bm, const SpellAction& action)
{
    rx_.casts().clear();
    InFlightCast c{};
    c.active      = true;
    c.interactive = true;
    c.action      = action;
    c.reactors    = declareCastReactors(bm, action);
    rx_.casts().push_back(std::move(c));
    return advanceCast(bm);
}

SpellResult CombatEngine::resolveCast(BattleMap& bm, const SpellAction& action)
{
    rx_.casts().clear();
    InFlightCast c{};
    c.active      = true;
    c.interactive = false;                                 // auto driver: resolve each checkpoint inline
    c.action      = action;
    c.reactors    = declareCastReactors(bm, action);
    rx_.casts().push_back(std::move(c));
    (void)advanceCast(bm);
    return last_cast_result_;                              // snapshot, set when the bottom popped
}

} // namespace rpg
