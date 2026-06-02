// ─────────────────────────────────────────────────────────────────────────────
//  combat_internal.hpp  –  shared file-scope helpers for the combat_*.cpp TUs
// ─────────────────────────────────────────────────────────────────────────────
//
//  Internal (non-installed) header. The CombatEngine implementation is split
//  across several translation units (combat_core.cpp, combat_attack.cpp, …).
//  The free helper functions below were previously file-scope `static` functions
//  in combat.cpp; they are promoted to `inline` here so every TU shares one
//  definition with no ODR violation. Pure helpers only — none touch CombatEngine
//  state (those are member functions and live with the class).
//
//  Sections:
//    · Ability modifier
//    · Geometry (footprint distance, line paths, footprint overlap, sphere cells)
//    · RL observation block builder
//    · Spell AoE target resolution
//    · Rogue Cunning Strike cost tables
//
#pragma once

#include "battle_map.hpp"   // PlacedAgent, Cell, Agent::*, Spell, std::span
#include "spell.hpp"        // Spell geometry enums used by resolveAoeTargets

#include <algorithm>
#include <cmath>
#include <limits>
#include <span>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Ability modifier
// ─────────────────────────────────────────────────────────────────────────────

// Standard D&D ability modifier formula.
inline constexpr int abilityMod(int score) noexcept
{
    return (score - 10) / 2;   // integer truncation rounds toward zero,
                                // which is correct for negative scores too
                                // because C++11 guarantees truncation.
}

// ─────────────────────────────────────────────────────────────────────────────
//  Geometry
// ─────────────────────────────────────────────────────────────────────────────

// Chebyshev distance from a single cell (tc, tr) to the nearest cell
// inside the attacker's footprint [atk_origin, atk_origin + atk_size).
inline int chebyshevToFootprint(int tc, int tr,
                                 Cell atk_origin, int atk_size) noexcept
{
    int dc = std::max({atk_origin.col - tc,
                       tc - (atk_origin.col + atk_size - 1),
                       0});
    int dr = std::max({atk_origin.row - tr,
                       tr - (atk_origin.row + atk_size - 1),
                       0});
    return std::max(dc, dr);
}

// Helper: get all cells along a line from start to end (Bresenham-like)
inline std::vector<Cell> getCellsAlongPath(Cell start, Cell end) noexcept
{
    std::vector<Cell> cells;
    int x0 = start.col, y0 = start.row;
    int x1 = end.col, y1 = end.row;

    int dx = std::abs(x1 - x0);
    int dy = std::abs(y1 - y0);
    int sx = (x0 < x1) ? 1 : -1;
    int sy = (y0 < y1) ? 1 : -1;
    int err = dx - dy;

    int x = x0, y = y0;
    while (true) {
        cells.push_back(Cell{x, y});
        if (x == x1 && y == y1) break;

        int e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            x += sx;
        }
        if (e2 < dx) {
            err += dx;
            y += sy;
        }
    }
    return cells;
}

// True if any cell of the agent's NxN footprint lies within the given cell set.
inline bool footprintOverlapsCells(const PlacedAgent& pa, const std::vector<Cell>& cells)
{
    const int size = pa.agent->getSize();
    for (int c = pa.origin.col; c < pa.origin.col + size; ++c)
        for (int r = pa.origin.row; r < pa.origin.row + size; ++r)
            if (std::find(cells.begin(), cells.end(), Cell{c, r}) != cells.end())
                return true;
    return false;
}

// Cells of a Sphere of the given foot-radius centered on (center_col, center_row).
// Matches the integer-radius disc used by the persistent-effect builder, so a moving
// Sphere's footprint is identical whether it's first placed or later re-centered.
inline std::vector<Cell> sphereCellsAround(int center_col, int center_row, int radius_ft)
{
    std::vector<Cell> cells;
    const int radius_cells = (radius_ft + 4) / 5;  // feet -> cells (5 ft/cell)
    for (int c = center_col - radius_cells; c <= center_col + radius_cells; ++c)
        for (int r = center_row - radius_cells; r <= center_row + radius_cells; ++r) {
            const int dc = c - center_col, dr = r - center_row;
            if (dc * dc + dr * dr <= radius_cells * radius_cells)
                cells.push_back(Cell{c, r});
        }
    return cells;
}

// ─────────────────────────────────────────────────────────────────────────────
//  RL observation block builder
// ─────────────────────────────────────────────────────────────────────────────

inline void appendAgentBlock(std::vector<float>& obs,
                              const Agent::Stats& s,
                              int col, int row,
                              int grid_cols, int grid_rows)
{
    float hp_frac = (s.hp_max > 0)
                    ? static_cast<float>(s.hp_cur) / static_cast<float>(s.hp_max)
                    : 0.f;
    obs.push_back(static_cast<float>(col) / static_cast<float>(grid_cols));
    obs.push_back(static_cast<float>(row) / static_cast<float>(grid_rows));
    obs.push_back(hp_frac);
    obs.push_back(static_cast<float>(s.base_ac)    / 30.f);
    obs.push_back(static_cast<float>(s.str   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.dex   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.con   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.intel - 10) / 10.f);
    obs.push_back(static_cast<float>(s.wis   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.cha   - 10) / 10.f);
    obs.push_back(static_cast<float>(s.speed_walk) / 60.f);
    obs.push_back(static_cast<float>(s.speed_fly)  / 60.f);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Spell AoE target resolution
// ─────────────────────────────────────────────────────────────────────────────

inline std::vector<int> resolveAoeTargets(
    std::span<const PlacedAgent> agents,
    const Spell& sp,
    int caster_idx,
    int aoe_col, int aoe_row,
    int aoe_col2 = -1, int aoe_row2 = -1)
{
    std::vector<int> targets;
    const int n = static_cast<int>(agents.size());

    const Cell& cc = agents[static_cast<std::size_t>(caster_idx)].origin;
    const float cx = static_cast<float>(cc.col);
    const float cy = static_cast<float>(cc.row);
    const float ax = static_cast<float>(aoe_col);
    const float ay = static_cast<float>(aoe_row);

    for (int i = 0; i < n; ++i) {
        const Cell& tc = agents[static_cast<std::size_t>(i)].origin;
        const float tx = static_cast<float>(tc.col);
        const float ty = static_cast<float>(tc.row);
        bool in_area = false;

        switch (sp.geometry) {

        case Spell::Sphere: {
            float dx = tx - ax, dy = ty - ay;
            float dist_ft = std::sqrt(dx*dx + dy*dy) * 5.0f;
            in_area = dist_ft <= static_cast<float>(sp.radius);
            break;
        }

        case Spell::Cone: {
            // Direction from caster toward the aimed point.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) { in_area = (i == caster_idx); break; }
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float plen = std::sqrt(px*px + py*py);
            float dist_ft = plen * 5.0f;
            // 60° cone half-angle: cos(30°) ≈ 0.866
            in_area = (plen >= 0.001f)
                   && dist_ft <= static_cast<float>(sp.radius)
                   && (px*ux + py*uy) / plen >= 0.866f;
            break;
        }

        case Spell::Line: {
            // Direction from caster toward the aimed endpoint.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) break;
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float along_ft = (px*ux + py*uy) * 5.0f;
            float perp_ft  = std::abs(-py*ux + px*uy) * 5.0f;
            in_area = along_ft >= 0.0f
                   && along_ft <= static_cast<float>(sp.length)
                   && perp_ft  <= static_cast<float>(sp.width) / 2.0f;
            break;
        }

        case Spell::Rectangle: {
            // Oriented wall: thick segment from the aim point toward the endpoint.
            const float ex = static_cast<float>(aoe_col2);
            const float ey = static_cast<float>(aoe_row2);
            const float dx = ex - ax, dy = ey - ay;
            const float len = std::sqrt(dx*dx + dy*dy);
            if (aoe_col2 < 0 || len < 0.001f) {
                // Degenerate fallback: centered box (legacy behavior).
                float dx_ft = std::abs(tx - ax) * 5.0f;
                float dy_ft = std::abs(ty - ay) * 5.0f;
                in_area = dx_ft <= static_cast<float>(sp.width) / 2.0f
                       && dy_ft <= static_cast<float>(sp.length) / 2.0f;
                break;
            }
            const float ux = dx / len, uy = dy / len;
            const float px = tx - ax, py = ty - ay;
            const float along_ft = (px*ux + py*uy) * 5.0f;
            const float perp_ft  = std::abs(-py*ux + px*uy) * 5.0f;
            const float max_along_ft = std::min(len * 5.0f, static_cast<float>(sp.length));
            in_area = along_ft >= 0.0f
                   && along_ft <= max_along_ft
                   && perp_ft  <= static_cast<float>(sp.width) / 2.0f;
            break;
        }

        case Spell::Square: {
            // Square centered on aimed point, using width and length
            float dx_ft = std::abs(tx - ax) * 5.0f;
            float dy_ft = std::abs(ty - ay) * 5.0f;
            in_area = dx_ft <= static_cast<float>(sp.width) / 2.0f
                   && dy_ft <= static_cast<float>(sp.length) / 2.0f;
            break;
        }

        default:
            break;
        }

        if (in_area) targets.push_back(i);
    }
    return targets;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Rogue Cunning Strike cost tables
// ─────────────────────────────────────────────────────────────────────────────

// Rogue Cunning Strike: Sneak Attack dice cost per effect (0 = unknown/deferred → invalid).
inline int cunningStrikeCost(int effect) noexcept {
    switch (effect) {
        case 0: return 1;  // Poison
        case 1: return 1;  // Trip
        case 2: return 1;  // Withdraw
        case 4: return 6;  // Knock Out
        case 5: return 3;  // Obscure
        default: return 0; // 3=Daze deferred, anything else invalid
    }
}

inline int cunningStrikeMinLevel(int effect) noexcept {
    switch (effect) {
        case 0: case 1: case 2: return 5;   // Cunning Strike
        case 4: case 5:         return 14;  // Devious Strikes
        default:                return 99;  // invalid
    }
}

} // namespace rpg
