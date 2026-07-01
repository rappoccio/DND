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
#include <array>
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

// D&D ability modifier rounding toward negative infinity (floor). The free-function
// abilityMod() above truncates toward zero, which is WRONG for odd scores below 10
// (e.g. score 9 → abilityMod gives 0, D&D wants -1). Prefer dndMod at every DC/save
// site. Lives here so all translation units share one correct implementation.
inline constexpr int dndMod(int score) noexcept
{
    int m = (score - 10) / 2;
    if (score < 10 && (score - 10) % 2 != 0) --m;
    return m;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Damage-type mask
// ─────────────────────────────────────────────────────────────────────────────

// Bitmask (bit t = MagicDamage_t t) of every magic type that dealt > 0 damage in this result.
// Fed to processDamageTaken so Regeneration interrupts (Troll acid/fire, Vampire radiant) can fire.
inline unsigned magicTypeMask(const std::array<int, NumMagicDamage_t>& dealt) noexcept
{
    unsigned mask = 0u;
    for (unsigned t = 0; t < NumMagicDamage_t; ++t)
        if (dealt[t] > 0) mask |= (1u << t);
    return mask;
}

// Convenience: the mask for a single MagicDamage_t (or 0 if t is out of range / "none" == -1).
inline unsigned magicTypeBit(int t) noexcept
{
    return (t >= 0 && t < NumMagicDamage_t) ? (1u << static_cast<unsigned>(t)) : 0u;
}

// Mask of every magic damage type a spell can deal (types already reflect any damage_type_override /
// Transmuted Spell rewrite, which mutate sp.magic_damage_rolls in place before damage is applied).
inline unsigned magicTypeMaskFromSpell(const Spell& sp) noexcept
{
    unsigned mask = 0u;
    for (const auto& r : sp.magic_damage_rolls) mask |= magicTypeBit(static_cast<int>(r.type));
    return mask;
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

// footprintDistance now lives in cell.hpp (the map/geometry layer) so BattleMap can
// share it too; still the single source of truth. Pulled in transitively via
// battle_map.hpp → cell.hpp above. (Intentionally not redefined here.)

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

    const PlacedAgent& caster_pa = agents[static_cast<std::size_t>(caster_idx)];
    const Cell& cc = caster_pa.origin;
    const int   cs = caster_pa.agent ? caster_pa.agent->getSize() : 1;
    // Cone/Line apex: the cell on the caster's NxN footprint nearest the aimed
    // point, so a Large+ creature emanates from the edge facing the target
    // instead of always from its top-left origin cell.
    const float cx = static_cast<float>(std::clamp(aoe_col, cc.col, cc.col + cs - 1));
    const float cy = static_cast<float>(std::clamp(aoe_row, cc.row, cc.row + cs - 1));
    const float ax = static_cast<float>(aoe_col);
    const float ay = static_cast<float>(aoe_row);

    // Does a single grid cell (tx,ty) fall inside this spell's area? Evaluated
    // per target cell so that a Large+ target is hit if ANY cell of its
    // footprint overlaps the area, not just its top-left origin cell.
    auto cellInArea = [&](float tx, float ty) -> bool {
        switch (sp.geometry) {

        case Spell::Sphere: {
            float dx = tx - ax, dy = ty - ay;
            float dist_ft = std::sqrt(dx*dx + dy*dy) * 5.0f;
            return dist_ft <= static_cast<float>(sp.radius);
        }

        case Spell::Cone: {
            // Direction from the footprint apex toward the aimed point.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) return false;
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float plen = std::sqrt(px*px + py*py);
            float dist_ft = plen * 5.0f;
            // 60° cone half-angle: cos(30°) ≈ 0.866
            return (plen >= 0.001f)
                && dist_ft <= static_cast<float>(sp.radius)
                && (px*ux + py*uy) / plen >= 0.866f;
        }

        case Spell::Line: {
            // Direction from the footprint apex toward the aimed endpoint.
            float dx = ax - cx, dy = ay - cy;
            float len = std::sqrt(dx*dx + dy*dy);
            if (len < 0.001f) return false;
            float ux = dx / len, uy = dy / len;
            float px = tx - cx, py = ty - cy;
            float along_ft = (px*ux + py*uy) * 5.0f;
            float perp_ft  = std::abs(-py*ux + px*uy) * 5.0f;
            return along_ft >= 0.0f
                && along_ft <= static_cast<float>(sp.length)
                && perp_ft  <= static_cast<float>(sp.width) / 2.0f;
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
                return dx_ft <= static_cast<float>(sp.width) / 2.0f
                    && dy_ft <= static_cast<float>(sp.length) / 2.0f;
            }
            const float ux = dx / len, uy = dy / len;
            const float px = tx - ax, py = ty - ay;
            const float along_ft = (px*ux + py*uy) * 5.0f;
            const float perp_ft  = std::abs(-py*ux + px*uy) * 5.0f;
            const float max_along_ft = std::min(len * 5.0f, static_cast<float>(sp.length));
            return along_ft >= 0.0f
                && along_ft <= max_along_ft
                && perp_ft  <= static_cast<float>(sp.width) / 2.0f;
        }

        case Spell::Square: {
            // Square centered on aimed point, using width and length
            float dx_ft = std::abs(tx - ax) * 5.0f;
            float dy_ft = std::abs(ty - ay) * 5.0f;
            return dx_ft <= static_cast<float>(sp.width) / 2.0f
                && dy_ft <= static_cast<float>(sp.length) / 2.0f;
        }

        default:
            return false;
        }
    };

    for (int i = 0; i < n; ++i) {
        // A creature is never caught in its own cone/line emanation.
        if ((sp.geometry == Spell::Cone || sp.geometry == Spell::Line)
            && i == caster_idx) {
            continue;
        }

        const PlacedAgent& tpa = agents[static_cast<std::size_t>(i)];
        const Cell& tc = tpa.origin;
        const int   ts = tpa.agent ? tpa.agent->getSize() : 1;

        // A target is in the area if ANY cell of its footprint overlaps it.
        bool in_area = false;
        for (int dc = 0; dc < ts && !in_area; ++dc) {
            for (int dr = 0; dr < ts && !in_area; ++dr) {
                in_area = cellInArea(static_cast<float>(tc.col + dc),
                                     static_cast<float>(tc.row + dr));
            }
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
        case 6: return 1;  // Stealth Attack (Thief Supreme Sneak)
        default: return 0; // 3=Daze deferred, anything else invalid
    }
}

inline int cunningStrikeMinLevel(int effect) noexcept {
    switch (effect) {
        case 0: case 1: case 2: return 5;   // Cunning Strike
        case 4: case 5:         return 14;  // Devious Strikes
        case 6:                 return 9;   // Stealth Attack (Thief Supreme Sneak)
        default:                return 99;  // invalid
    }
}

} // namespace rpg
