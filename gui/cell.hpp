#pragma once

#include <algorithm>
#include <functional>
#include <unordered_set>

namespace rpg {

// ── Grid coordinate ────────────────────────────────────────────────────
// `z` carries the FLOOR at the global addressing layer only. The engine's live
// cells (movement/LOS/occupancy/terrain) always keep z = 0; z is meaningful only
// on cells produced by BattleMap::local_to_global. Never mix a nonzero-z cell into
// a CellSet that the engine hot paths touch (defaulted-== is now z-sensitive).
struct Cell {
    int col{0};
    int row{0};
    int z{0};
    bool operator==(const Cell&) const noexcept = default;
};

struct CellHash {
    std::size_t operator()(const Cell& c) const noexcept {
        return std::hash<int>{}(c.col)
             ^ (std::hash<int>{}(c.row) << 16)
             ^ (std::hash<int>{}(c.z)   << 8);
    }
};

using CellSet = std::unordered_set<Cell, CellHash>;

// ── Footprint geometry (single source of truth) ─────────────────────────
// Chebyshev distance in CELLS between two square footprints (origin = top-left,
// size = side length). 0 ⇒ overlapping; 1 ⇒ directly adjacent (incl. diagonal).
// The same formula the combat engine uses for reach/adjacency, so callers must
// never re-derive it (re-deriving it broke Cleave-vs-Large three times). Lives
// here in the map/geometry layer so BattleMap and the combat TUs share one copy.
inline int footprintDistance(Cell a, int sa, Cell b, int sb) noexcept
{
    int dc = std::max({a.col - (b.col + sb - 1), b.col - (a.col + sa - 1), 0});
    int dr = std::max({a.row - (b.row + sb - 1), b.row - (a.row + sa - 1), 0});
    return std::max(dc, dr);
}

} // namespace rpg
