#pragma once

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

} // namespace rpg
