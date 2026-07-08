// ─────────────────────────────────────────────────────────────────────────────
//  combat_movement.cpp  –  CombatEngine movement, teleport, terrain slip
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · Move budgets   — get*/spend* Walk/Fly/Swim/Burrow, clearMovement
//    · Movement       — canAgentMove, moveAgent (with spell-effect checking)
//    · Jump & teleport— jumpAgent, teleportAgent, isValidTeleportDestination,
//                       placeTeleportedAgents
//    · Terrain        — checkSlippingTerrain
//    · Stand up       — standup
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <unordered_set>
#include <utility>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Move budgets
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::getWalkRemaining(int agent_idx) const noexcept
{
    auto it = walkRemaining_.find(agent_idx);
    return (it != walkRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getFlyRemaining(int agent_idx) const noexcept
{
    auto it = flyRemaining_.find(agent_idx);
    return (it != flyRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getSwimRemaining(int agent_idx) const noexcept
{
    auto it = swimRemaining_.find(agent_idx);
    return (it != swimRemaining_.end()) ? it->second : 0;
}

int CombatEngine::getBurrowRemaining(int agent_idx) const noexcept
{
    auto it = burrowRemaining_.find(agent_idx);
    return (it != burrowRemaining_.end()) ? it->second : 0;
}

int CombatEngine::spendWalk(int agent_idx, int feet) noexcept
{
    auto& rem  = walkRemaining_[agent_idx];  // inserts 0 if absent
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendFly(int agent_idx, int feet) noexcept
{
    auto& rem  = flyRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendSwim(int agent_idx, int feet) noexcept
{
    auto& rem  = swimRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

int CombatEngine::spendBurrow(int agent_idx, int feet) noexcept
{
    auto& rem  = burrowRemaining_[agent_idx];
    int   spent = std::min(feet, rem);
    rem -= spent;
    return spent;
}

void CombatEngine::clearMovement() noexcept
{
    walkRemaining_.clear();
    flyRemaining_.clear();
    swimRemaining_.clear();
    burrowRemaining_.clear();
}

// ─────────────────────────────────────────────────────────────────────────────
//  Movement (with spell effect checking)
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canAgentMove(const BattleMap& bm, int idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    // Check for any condition that reduces speed to 0
    if (cond.incapacitated || cond.unconscious || cond.paralyzed
            || cond.branches_speed_zeroed) {   // World Tree Branches of the Tree: Speed 0 this turn
        return false;
    }
    // A grapple only pins the creature while its grappler can still maintain it (alive, conscious,
    // not incapacitated). A grapple whose grappler is gone no longer zeroes Speed.
    if (cond.grappled && grapplerActive(bm, idx))
        return false;
    return true;
}

bool CombatEngine::moveAgent(BattleMap& bm, int idx, Cell newOrigin, MovementType type) noexcept
{
    // Get old position before moving
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;

    // Check if agent is incapacitated or unconscious - cannot move
    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.incapacitated || cond.unconscious) {
        log_("Movement blocked: agent is incapacitated or unconscious");
        return false;
    }

    // Check if agent is grappled - cannot move (Speed = 0).
    // A grapple is released the instant the grappler becomes Incapacitated/Unconscious/dies
    // (see dropGrapplesBy in applyIncapacitated/applyUnconscious). Distance alone does NOT break a
    // grapple — the grappler can drag this creature along (at 2x cost); it ends only via drop/escape.
    if (cond.grappled) {
        if (grapplerActive(bm, idx)) {
            log_("Movement blocked: grappled creature cannot move (Speed = 0)");
            return false;
        }
        // Grappler is gone/downed/incapacitated (or the reference is stale): the grapple has silently
        // ended. Self-heal the flag so this creature regains its Speed instead of staying pinned.
        cond.grappled = false;
        cond.grappler_idx = -1;
        bm.setAgentConditions(idx, cond);
        log_("{}'s grapple has ended (grappler can no longer maintain it); movement allowed",
             agentName(bm, idx));
    }

    Cell oldOrigin = agents[static_cast<std::size_t>(idx)].origin;

    // Grappling a creature doubles the cost of every foot of movement (you drag it along). That
    // surcharge is charged inside BattleMap::moveAgent against the agent's own movement budget — the
    // same one a Dash, exhaustion, and every speed modifier flow through — so it scales with them.
    // (It used to be charged here against the CombatEngine's separate per-turn walkRemaining_ map,
    // which never received a Dash bonus and so capped a grappler at base speed even after Dashing.)

    // Check if agent is Frightened and would move toward fear source
    for (const auto& ac : activeAgentConditions_) {
        if (ac.agent_idx == idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
            Cell src  = bm.placedAgents()[ac.caster_idx].origin;
            int cur_d = std::max(std::abs(oldOrigin.col - src.col), std::abs(oldOrigin.row - src.row));
            int new_d = std::max(std::abs(newOrigin.col - src.col), std::abs(newOrigin.row - src.row));
            if (new_d < cur_d) {
                log_("Movement blocked: Frightened cannot move closer to fear source");
                return false;
            }
            break;
        }
    }

    // Command (Flee/Approach): the Bard's Command forces a one-turn movement direction relative to
    // the bard. Flee = the target must move away (cannot decrease the distance); Approach = the
    // target must move toward (cannot increase the distance). Both expire as the bard's next turn
    // begins (1-turn duration keyed to the bard).
    for (const auto& ac : activeAgentConditions_) {
        if (ac.agent_idx != idx || ac.caster_idx < 0) continue;
        const bool flee     = (ac.condition_name == "CommandFlee");
        const bool approach = (ac.condition_name == "CommandApproach");
        if (!flee && !approach) continue;
        Cell src  = bm.placedAgents()[ac.caster_idx].origin;
        int cur_d = std::max(std::abs(oldOrigin.col - src.col), std::abs(oldOrigin.row - src.row));
        int new_d = std::max(std::abs(newOrigin.col - src.col), std::abs(newOrigin.row - src.row));
        if (flee && new_d < cur_d) {
            log_("Movement blocked: Command (Flee) — cannot move closer to {}",
                 agentName(bm, ac.caster_idx));
            return false;
        }
        if (approach && new_d > cur_d) {
            log_("Movement blocked: Command (Approach) — cannot move away from {}",
                 agentName(bm, ac.caster_idx));
            return false;
        }
        break;
    }

    // Delegate to BattleMap for pathfinding and movement budget logic
    if (!bm.moveAgent(idx, newOrigin, type))
        return false;

    // Check for spell effects along the path from old to new position. A creature that
    // enters a zone is affected at most once per turn (see applyZoneIfNewThisTurn).
    std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);
    for (const auto& pathCell : pathCells) {
        for (const auto& effect : bm.activeSpellEffects()) {
            if (zoneSparesTarget(bm, effect, idx)) continue;  // self + allies (faction rules)
            if (std::find(effect.cells.begin(), effect.cells.end(), pathCell) != effect.cells.end())
                applyZoneIfNewThisTurn(bm, effect, idx);
        }
    }

    // A moving Sphere (Emanation) anchored to this agent follows them as they move.
    // Snapshot each anchored zone's footprint, re-center it, then affect creatures the
    // zone newly swept onto — "whenever the Emanation enters a creature's space" (once/turn).
    std::vector<std::pair<int, std::vector<Cell>>> oldAnchoredCells;  // (effect_id, cells before move)
    for (const auto& effect : bm.activeSpellEffects())
        if (effect.anchor_agent_idx == idx)
            oldAnchoredCells.emplace_back(effect.effect_id, effect.cells);

    recomputeAnchoredEffects(bm, idx);

    for (const auto& [eff_id, oldCells] : oldAnchoredCells) {
        const ActiveSpellEffect* eff = nullptr;
        for (const auto& e : bm.activeSpellEffects())
            if (e.effect_id == eff_id) { eff = &e; break; }
        if (!eff) continue;
        for (int j = 0; j < static_cast<int>(agents.size()); ++j) {
            if (zoneSparesTarget(bm, *eff, j)) continue;  // anchor + allies (faction rules)
            const PlacedAgent& other = agents[static_cast<std::size_t>(j)];
            if (footprintOverlapsCells(other, eff->cells) && !footprintOverlapsCells(other, oldCells))
                applyZoneIfNewThisTurn(bm, *eff, j);
        }
    }

    // Check for slipping terrain (ice/grease) along the path
    checkSlippingTerrain(bm, idx, oldOrigin, newOrigin);

    // Update darkness-based blinding after movement
    updateDarknessBlinding(bm, idx);

    // If grappling someone, drag them along maintaining relative position
    for (int i = 0; i < static_cast<int>(agents.size()); ++i) {
        if (i == idx) continue;
        Agent::Conditions grappled_cond = bm.getAgentConditions(i);
        if (grappled_cond.grappled && grappled_cond.grappler_idx == idx) {
            // Calculate relative offset of grappled creature from grappler
            int offset_col = agents[i].origin.col - oldOrigin.col;
            int offset_row = agents[i].origin.row - oldOrigin.row;

            // Try to maintain the same relative position
            Cell preferred = Cell(newOrigin.col + offset_col, newOrigin.row + offset_row);
            Cell drag_dest = preferred;

            // Check if preferred position is valid
            bool position_valid = bm.setAgentPosition(i, preferred);

            // If preferred position blocked, find adjacent unoccupied cell
            if (!position_valid) {
                bool found = false;
                // Try all 8 adjacent cells
                const int deltas[][2] = {{0,1}, {0,-1}, {1,0}, {-1,0}, {1,1}, {-1,-1}, {1,-1}, {-1,1}};
                for (const auto& delta : deltas) {
                    Cell candidate = Cell(newOrigin.col + delta[0], newOrigin.row + delta[1]);
                    if (bm.setAgentPosition(i, candidate)) {
                        drag_dest = candidate;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    // No valid position found, leave creature at current position
                    continue;
                }
            } else {
                drag_dest = preferred;
            }

            log_("Grappled creature dragged");
        }
    }

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Jump & teleport
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::jumpAgent(BattleMap& bm, int idx, Cell newOrigin, bool is_running) noexcept
{
    // Get old position before jumping
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;
    Cell oldOrigin = agents[static_cast<std::size_t>(idx)].origin;

    // Delegate to BattleMap for jump logic
    if (!bm.jumpAgent(idx, newOrigin, is_running))
        return false;

    // Check for spell effects along the jump path
    std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);

    // Track which effects we've already applied
    std::unordered_set<int> appliedEffects;

    for (const auto& pathCell : pathCells) {
        for (const auto& effect : bm.activeSpellEffects()) {
            if (appliedEffects.count(effect.effect_id)) continue;
            if (zoneSparesTarget(bm, effect, idx)) continue;  // self + allies (faction rules)

            auto it = std::find(effect.cells.begin(), effect.cells.end(), pathCell);
            if (it != effect.cells.end()) {
                applySpellEffect(bm, effect, idx);
                appliedEffects.insert(effect.effect_id);
            }
        }
    }

    // Update darkness-based blinding after jump
    updateDarknessBlinding(bm, idx);

    return true;
}

bool CombatEngine::teleportAgent(BattleMap& bm, int idx, int target_col, int target_row) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size()))
        return false;

    Cell targetCell{target_col, target_row};

    // Check if target cell is blocked by terrain (walls, chasms, etc.)
    const CellSet& disallowed = bm.disallowedCells();
    if (disallowed.count(targetCell))
        return false;

    // Check bounds
    if (target_col < 0 || target_row < 0 || target_col >= bm.gridCols() || target_row >= bm.gridRows())
        return false;

    // Set the new position
    if (!bm.setAgentPosition(idx, targetCell))
        return false;

    // Check for spell effects at the destination
    for (const auto& effect : bm.activeSpellEffects()) {
        if (zoneSparesTarget(bm, effect, idx)) continue;  // self + allies (faction rules)
        auto it = std::find(effect.cells.begin(), effect.cells.end(), targetCell);
        if (it != effect.cells.end()) {
            applySpellEffect(bm, effect, idx);
        }
    }

    // Update darkness-based blinding after teleport
    updateDarknessBlinding(bm, idx);

    return true;
}

bool CombatEngine::isValidTeleportDestination(const BattleMap& bm, int col, int row) const noexcept
{
    // Check bounds
    if (col < 0 || row < 0 || col >= bm.gridCols() || row >= bm.gridRows())
        return false;

    // Check if blocked by terrain
    Cell destination{col, row};
    const CellSet& disallowed = bm.disallowedCells();
    if (disallowed.count(destination))
        return false;

    return true;
}

int CombatEngine::placeTeleportedAgents(BattleMap& bm, const std::vector<int>& agent_indices,
                                        int dest_col, int dest_row) noexcept
{
    if (agent_indices.empty())
        return 0;

    // Validate destination
    if (!isValidTeleportDestination(bm, dest_col, dest_row))
        return 0;

    int placed_count = 0;

    // Place the first agent at the destination
    if (!agent_indices.empty()) {
        if (teleportAgent(bm, agent_indices[0], dest_col, dest_row))
            placed_count++;
    }

    // Place remaining agents in expanding circles around the destination
    // Check cells at Manhattan distance 1, 2, 3, ... until all agents are placed
    for (int radius = 1; radius <= 20 && placed_count < static_cast<int>(agent_indices.size()); ++radius) {
        // For each radius, check cells in a square ring around the destination
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                // Only check cells at this radius (on the ring, not inside)
                if (std::abs(dy) != radius && std::abs(dx) != radius)
                    continue;

                int candidate_col = dest_col + dx;
                int candidate_row = dest_row + dy;

                // Check if this cell is valid
                if (isValidTeleportDestination(bm, candidate_col, candidate_row)) {
                    // Try to place the next agent
                    int agent_idx = agent_indices[placed_count];
                    if (teleportAgent(bm, agent_idx, candidate_col, candidate_row))
                        placed_count++;

                    // Stop if all agents are placed
                    if (placed_count >= static_cast<int>(agent_indices.size()))
                        return placed_count;
                }
            }
        }
    }

    return placed_count;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Terrain
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::checkSlippingTerrain(BattleMap& bm, int agent_idx, Cell oldOrigin, Cell newOrigin) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return;

    // Check all terrain effects to see if any are slipping terrain
    for (const auto& terrain : bm.activeTerrainEffects()) {
        if (terrain.difficulty != TerrainDifficulty::Slipping)
            continue;

        // Check if the agent moved into a cell with this slipping terrain
        std::vector<Cell> pathCells = getCellsAlongPath(oldOrigin, newOrigin);
        bool on_slipping_terrain = false;
        for (const auto& cell : pathCells) {
            int cell_idx = cell.row * bm.gridCols() + cell.col;
            if (std::find(terrain.cell_indices.begin(), terrain.cell_indices.end(), cell_idx) != terrain.cell_indices.end()) {
                on_slipping_terrain = true;
                break;
            }
        }

        if (!on_slipping_terrain)
            continue;

        // Agent is on slipping terrain; add distance moved to slip counter
        int distance_moved = std::max({
            std::abs(newOrigin.col - oldOrigin.col),
            std::abs(newOrigin.row - oldOrigin.row)
        }) * 5;  // Each cell is 5 feet

        int& slip_counter = slipDistanceMoved_[agent_idx];
        slip_counter += distance_moved;

        // Check if they've moved enough feet to trigger a save
        if (slip_counter >= terrain.slip_distance_feet) {
            // Roll DEX save
            Agent::Stats target_stats = bm.getAgentStats(agent_idx);
            int save_d20 = roll(20);
            int save_mod = (target_stats.dex - 10) / 2;
            if (target_stats.dex < 10 && (target_stats.dex - 10) % 2 != 0) --save_mod;  // floor for odd negative scores
            if (target_stats.save_prof_dex) save_mod += target_stats.prof_bonus;        // DEX save proficiency
            int total_save = save_d20 + save_mod;

            log_("{} attempts DEX save ({}) vs DC {} - d20={}, mod={}, total={}",
                 agents[static_cast<std::size_t>(agent_idx)].agent->name(),
                 terrain.name,
                 terrain.slip_save_dc,
                 save_d20, save_mod, total_save);

            if (total_save < terrain.slip_save_dc) {
                // Save failed — apply prone condition and skip turn
                log_("{} slipped on {} and fell prone", agents[static_cast<std::size_t>(agent_idx)].agent->name(), terrain.name);
                applyProne(bm, agent_idx);
                agents[static_cast<std::size_t>(agent_idx)].agent->setSlippedThisTurn(true);
            } else {
                // Save succeeded — stay upright
                log_("{} maintained footing on {}", agents[static_cast<std::size_t>(agent_idx)].agent->name(), terrain.name);
            }

            // Reset slip counter after save check
            slip_counter = 0;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Stand up
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::standup(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Check if agent is prone
    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.prone) {
        log_("Agent is not prone");
        return;
    }

    // Cost to stand up: half of walk speed. Athlete (general feat) lets you stand from Prone using
    // only 5 feet of movement. (Athlete's Climb Speed = Speed and the running-jump clauses are not
    // mechanically modelled — no climb-budget / jump system; see known_limitations.md.)
    int walk_speed = agents[idx].agent->getStats().speed_walk;
    int standup_cost = agents[idx].agent->getStats().hasFeat("Athlete") ? 5 : walk_speed / 2;

    // Check if agent has enough movement
    auto it = walkRemaining_.find(idx);
    int remaining = (it != walkRemaining_.end()) ? it->second : 0;
    if (remaining < standup_cost) {
        log_("Agent lacks sufficient movement to stand up (needs {}, has {})", standup_cost, remaining);
        return;
    }

    // Deduct cost and remove prone condition
    spendWalk(idx, standup_cost);
    cond.prone = false;
    bm.setAgentConditions(idx, cond);

    log_("{} stands up, spending {} feet of movement", agentName(bm, idx), standup_cost);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Reaction system — Opportunity Attacks via flow checkpoints
//  The OA rule used to live in main.py; it now lives
//  here. detectProvokes finds per-creature / per-step leavers along the path;
//  beginMove/submitDecision (GUI) and resolveMove (auto/RL) drive the checkpoints.
// ─────────────────────────────────────────────────────────────────────────────

std::vector<ProvokeEvent>
CombatEngine::detectProvokes(const BattleMap& bm, int mover_idx,
                             Cell origin, Cell dest, MovementType /*type*/) const
{
    std::vector<ProvokeEvent> events;
    const auto& agents = bm.placedAgents();
    if (mover_idx < 0 || mover_idx >= static_cast<int>(agents.size())) return events;

    // Disengage normally suppresses all opportunity attacks for this move — EXCEPT against a
    // Sentinel-ready threatener: the Sentinel feat (clause 2) makes a
    // creature provoke an OA from you even if it Disengages. So Disengage is checked per-reactor below.
    const bool disengaging = bm.getAgentConditions(mover_idx).disengaging;

    const int moverSize = agents[static_cast<std::size_t>(mover_idx)].agent->getSize();
    const std::vector<Cell> path = getCellsAlongPath(origin, dest);  // straight-line (interim; plan §11)
    const int reach = 1;  // 5-ft melee reach, in cells

    for (int r = 0; r < static_cast<int>(agents.size()); ++r) {
        if (r == mover_idx) continue;
        if (areAllies(bm, mover_idx, r)) continue;  // teammates don't provoke OAs from each other
        const PlacedAgent& ra = agents[static_cast<std::size_t>(r)];
        if (ra.on_deck) continue;                    // a reserve held On Deck makes no opportunity attacks
        if (ra.agent->getConditions().incapacitated) continue;
        if (ra.agent->getStats().hp_cur <= 0) continue;
        if (bm.getAgentConditions(r).reaction_used) continue;
        if (!canAgentMove(bm, r)) continue;  // Speed 0 cannot make an OA
        // Disengage suppresses the OA for an ordinary threatener, but a Sentinel-feated one still provokes.
        if (disengaging && !ra.agent->getStats().has_sentinel) continue;

        const int rSize = ra.agent->getSize();
        bool wasIn = footprintDistance(ra.origin, rSize, path.front(), moverSize) <= reach;
        bool provoked = false;
        Cell leftCell = path.front();
        int  leftStep = 0;
        for (std::size_t i = 1; i < path.size(); ++i) {
            const bool nowIn = footprintDistance(ra.origin, rSize, path[i], moverSize) <= reach;
            if (wasIn && !nowIn) {                       // left this reactor's reach on this step
                leftCell = path[i - 1];
                leftStep = static_cast<int>(i - 1);
                provoked = true;
                break;                                    // one OA per reactor per move
            }
            wasIn = nowIn;
        }
        if (provoked) events.push_back(ProvokeEvent{r, leftCell, leftStep});
    }
    std::sort(events.begin(), events.end(),
              [](const ProvokeEvent& a, const ProvokeEvent& b){ return a.step < b.step; });
    return events;
}

ReactionCtx
CombatEngine::buildReactionCheckpoint(const BattleMap& bm, ReactionWindow window,
                                      int reactor_idx, int source_idx, Cell source_cell) const
{
    ReactionCtx ctx;
    ctx.window      = window;
    ctx.reactor_idx = reactor_idx;
    ctx.source_idx  = source_idx;
    ctx.source_cell = source_cell;

    const auto& agents = bm.placedAgents();
    if (reactor_idx >= 0 && reactor_idx < static_cast<int>(agents.size())) {
        const std::vector<Weapon> weapons = bm.getAgentWeapons(reactor_idx);
        for (int wi = 0; wi < static_cast<int>(weapons.size()); ++wi) {
            const Weapon& w = weapons[static_cast<std::size_t>(wi)];
            if (w.name.empty() || w.type != WeaponType::Melee) continue;   // OA is a melee strike
            ctx.options.push_back(ReactionOption{ReactionOption::Weapon, wi, "[Weapon] " + w.name, ""});
        }
        const std::vector<Spell> spells = bm.getAgentSpells(reactor_idx);
        for (int si = 0; si < static_cast<int>(spells.size()); ++si) {
            if (spells[static_cast<std::size_t>(si)].geometry != Spell::Single) continue;  // single-target only
            ctx.options.push_back(ReactionOption{ReactionOption::Spell, si,
                                                 "[Spell] " + spells[static_cast<std::size_t>(si)].name, ""});
        }
    }
    ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});  // always offer Skip
    return ctx;
}

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

    // Sentinel feat clause 1: when a Sentinel-feated reactor HITS with its opportunity attack, the
    // target's speed becomes 0 for the rest of the turn (it stops where the OA triggered).
    const bool reactor_has_sentinel = bm.getAgentStats(reactor).has_sentinel;
    bool sentinel_hit = false;

    if (opt.kind == ReactionOption::Weapon) {
        Attack oa{reactor, target, opt.index};
        oa.opportunity = true;   // a Speedy target imposes Disadvantage on the OA roll
        AttackResult r = executeAction(bm, oa);
        const bool is_sentinel_oa = reactor_has_sentinel && target == ctx.source_idx;
        // Log the to-hit result (executeAction logs damage/conditions but not the roll). The old
        // Python OA path logged this; it now lives here so OA hits/misses aren't silent.
        if (!r.valid) {
            log_("{}: {} can't reach {}", is_sentinel_oa ? "Sentinel OA" : "OA",
                 agentName(bm, reactor), agentName(bm, target));
        } else if (r.hit) {
            sentinel_hit = is_sentinel_oa;
            log_("{}: {} hits {} — roll {} vs AC {}{}{}{}",
                 is_sentinel_oa ? "Sentinel OA" : "OA",
                 agentName(bm, reactor), agentName(bm, target), r.total_roll, r.target_ac,
                 r.critical ? " (CRIT)" : "", r.target_down ? " — DOWN" : "",
                 (sentinel_hit && !r.target_down) ? " — Sentinel: speed → 0" : "");
        } else {
            log_("{}: {} misses {} — roll {} vs AC {}", is_sentinel_oa ? "Sentinel OA" : "OA",
                 agentName(bm, reactor), agentName(bm, target), r.total_roll, r.target_ac);
        }
        in_flight_move_.results.push_back(r);
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
        in_flight_move_.mover_down = true;
        bm.setAgentPosition(ctx.source_idx, ctx.source_cell);
    } else {
        if (sentinel_hit) {
            in_flight_move_.mover_halted = true;
            in_flight_move_.halt_cell    = ctx.source_cell;   // stop where the OA triggered
        }
        bm.setAgentPosition(ctx.source_idx, saved);
    }
}

FlowStatus
CombatEngine::advanceMove(BattleMap& bm)
{
    InFlightMove& m = in_flight_move_;
    while (m.cursor < m.provokes.size() && !m.mover_down && !m.mover_halted) {
        const ProvokeEvent ev = m.provokes[m.cursor];
        // The reactor may have lost eligibility since detection (downed/used by a prior OA).
        if (ev.reactor < 0 ||
            bm.getAgentConditions(ev.reactor).reaction_used ||
            bm.getAgentConditions(ev.reactor).incapacitated ||
            bm.getAgentStats(ev.reactor).hp_cur <= 0) {
            ++m.cursor;
            continue;
        }
        ReactionCtx ctx = buildReactionCheckpoint(bm, ReactionWindow::LeftReach,
                                                  ev.reactor, m.mover_idx, ev.left_cell);
        if (m.interactive) {
            pending_decision_ = PendingDecision{true, ctx};   // suspend; GUI resumes via submitDecision
            return FlowStatus::AwaitingDecision;
        }
        const ReactionResponse resp = decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{};
        applyReactionResponse(bm, ctx, resp);
        ++m.cursor;
    }

    // All provokes resolved (or the mover went down / was halted) — commit.
    pending_decision_.active = false;
    if (!m.mover_down) {
        // A Sentinel OA stops the mover at the provoke cell; otherwise it completes the move to dest.
        const Cell commit = m.mover_halted ? m.halt_cell : m.dest;
        (void)moveAgent(bm, m.mover_idx, commit, m.type);   // real budgeted move + terrain/zone checks
        if (m.mover_halted) {
            // Sentinel feat: speed becomes 0 for the rest of the turn. Zero BOTH the engine budgets and
            // the Agent's own remaining (BattleMap::moveAgent reads the latter) so no further movement —
            // including a fresh begin_move — is possible this turn.
            walkRemaining_[m.mover_idx]   = 0;
            flyRemaining_[m.mover_idx]    = 0;
            swimRemaining_[m.mover_idx]   = 0;
            burrowRemaining_[m.mover_idx] = 0;
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

    in_flight_move_             = InFlightMove{};
    in_flight_move_.active      = true;
    in_flight_move_.interactive = true;
    in_flight_move_.mover_idx   = idx;
    in_flight_move_.origin      = agents[static_cast<std::size_t>(idx)].origin;
    in_flight_move_.dest        = dest;
    in_flight_move_.type        = type;
    in_flight_move_.provokes    = detectProvokes(bm, idx, in_flight_move_.origin, dest, type);
    return advanceMove(bm);
}

FlowStatus
CombatEngine::submitDecision(BattleMap& bm, const ReactionResponse& resp)
{
    if (!pending_decision_.active) return FlowStatus::Completed;
    const ReactionCtx ctx = pending_decision_.ctx;
    pending_decision_.active = false;
    // Dispatch to whichever interruptible flow is parked. Cast (OnDeclareCast), attack (OnHit), move
    // (LeftReach) and turn-start (OnTurnStartNearby) share one transport; only one is active at a time
    // (the decision stack that would allow a reaction-during-reaction arrives later with
    // Counterspell-vs-Counterspell).
    if (in_flight_turn_.active) {   // OnTurnStartNearby — top-level, never nested inside another flow
        applyTurnStartReaction(bm, ctx, resp);
        ++in_flight_turn_.cursor;
        return advanceTurnStart(bm);
    }
    if (in_flight_attack_.active) {
        // Two windows share the in-flight attack: OnD20Seen (multi-reactor cursor, BEFORE the hit) and
        // OnHit Shield (single reactor, no cursor). Advance the d20 cursor on each OnD20Seen resume so
        // a Skip moves to the next reactor; the Shield branch re-enters advanceAttack with the gate
        // already consumed.
        if (ctx.window == ReactionWindow::OnD20Seen) {
            applyD20SeenReaction(bm, ctx, resp);
            ++in_flight_attack_.d20_cursor;
        } else {
            applyAttackReaction(bm, ctx, resp);
        }
        return advanceAttack(bm);
    }
    if (castActive()) {
        // Two windows share the top in-flight cast: OnDeclareCast/OnHit (Counterspell/Shield, `cursor`)
        // and OnSaveFail (reroll a failed save, its own `savefail_cursor`). Advance the matching cursor.
        InFlightCast& c = topCast();
        if (ctx.window == ReactionWindow::OnSaveFail) {
            applySaveFailReaction(bm, ctx, resp);
            ++c.savefail_cursor;
        } else if (isCounterspellChoice(ctx, resp) &&
                   cast_stack_.size() <= bm.placedAgents().size()) {
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
    ++in_flight_move_.cursor;
    return advanceMove(bm);
}

std::vector<AttackResult>
CombatEngine::resolveMove(BattleMap& bm, int idx, Cell dest, MovementType type)
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return {};

    in_flight_move_             = InFlightMove{};
    in_flight_move_.active      = true;
    in_flight_move_.interactive = false;
    in_flight_move_.mover_idx   = idx;
    in_flight_move_.origin      = agents[static_cast<std::size_t>(idx)].origin;
    in_flight_move_.dest        = dest;
    in_flight_move_.type        = type;
    in_flight_move_.provokes    = detectProvokes(bm, idx, in_flight_move_.origin, dest, type);
    (void)advanceMove(bm);
    return in_flight_move_.results;
}

} // namespace rpg
