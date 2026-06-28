#pragma once

#include <algorithm>
#include <functional>
#include <unordered_set>

namespace rpg {

// ── Grid coordinate ────────────────────────────────────────────────────
struct Cell {
    int col{0};
    int row{0};
    bool operator==(const Cell&) const noexcept = default;
};

struct CellHash {
    std::size_t operator()(const Cell& c) const noexcept {
        return std::hash<int>{}(c.col) ^ (std::hash<int>{}(c.row) << 16);
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
