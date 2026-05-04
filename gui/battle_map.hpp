#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  battle_map.hpp  –  Analysis-only core (no rendering dependencies)
//
//  Rendering is handled by main.py via pygame.
//  This module is compiled as a pybind11 extension and imported from Python.
//
//  Dependencies:  OpenCV 4.x only.
// ─────────────────────────────────────────────────────────────────────────────

#include "agent.hpp"
#include "weapon.hpp"
#include "spell.hpp"

#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <unordered_set>
#include <vector>

namespace rpg {

// ── Grid coordinate ────────────────────────────────────────────────────────
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

// ── Wall between two adjacent cells ───────────────────────────────────────
struct Wall {
    Cell a;
    Cell b;
    bool operator==(const Wall&) const noexcept = default;
};

// ── Movement types ─────────────────────────────────────────────────────────
enum class MovementType {
    Walk,    // Ground movement: BFS through passable cells, respects walls
    Fly,     // Aerial movement: Manhattan distance, ignores terrain, bounds only
    Swim,    // Aquatic movement: like walk but through water terrain
    Burrow,  // Underground movement: ignores surface obstacles
    Jump,    // Long jump: Manhattan distance, ignores terrain, deducts from walk budget
};

// ── Terrain difficulty levels for temporary effects ─────────────────────────
// Ordered by restrictiveness: Normal (0) < Halved (1) < Quartered (2).
// std::max gives "most restrictive wins" for stacking.
enum class TerrainDifficulty {
    Normal = 0,      // 1.0x movement cost (no effect)
    Halved = 1,      // 0.5x movement cost (Spirit Guardians, etc.)
    Quartered = 2,   // 0.25x movement cost (Plant Growth, etc.)
};

// ── Active temporary terrain effect ────────────────────────────────────────
struct ActiveTerrainEffect {
    int                 id;               // unique, returned to Python on add
    std::string         name;             // "Grease", "Web", "Spike Growth", etc.
    std::vector<int>    cell_indices;     // flat: row*cols_ + col
    TerrainDifficulty   difficulty;       // Halved or Quartered
    int                 turns_remaining;  // -1 = permanent, 0+ = expires after N turns
    int                 source_agent_idx; // -1 = DM-placed or no concentration requirement
};

// ── A placed agent on the map ──────────────────────────────────────────────
struct PlacedAgent {
    std::shared_ptr<Agent> agent;
    Cell                   origin;        // top-left cell of the NxN footprint
    Agent::Stats           stats;         // D&D 5.5e character stats
    std::vector<Weapon>    weapons;       // equipped weapons (may be empty)
    std::vector<Spell>     spells;        // known spells (may be empty)
};

// ── Agent configuration (supplied from Python GUI) ─────────────────────────
struct AgentConfig {
    std::string           name;
    std::filesystem::path spritePath;
    int                   size{1};      // 1–6
    int                   startCol{0};
    int                   startRow{0};
};

// ─────────────────────────────────────────────────────────────────────────────
class BattleMap {
public:
    explicit BattleMap(std::filesystem::path mapImagePath);
    ~BattleMap();

    BattleMap(const BattleMap&)            = delete;
    BattleMap& operator=(const BattleMap&) = delete;
    BattleMap(BattleMap&&)                 = default;
    BattleMap& operator=(BattleMap&&)      = default;

    // ── Grid analysis ─────────────────────────────────────────────────────
    void analyzeGrid();

    [[nodiscard]] int gridCols()      const noexcept { return cols_; }
    [[nodiscard]] int gridRows()      const noexcept { return rows_; }
    [[nodiscard]] int cellPixelSize() const noexcept { return cellPx_; }

    [[nodiscard]] const std::vector<int>& hLinePositions() const noexcept { return hLines_; }
    [[nodiscard]] const std::vector<int>& vLinePositions() const noexcept { return vLines_; }

    // ── Wall / boundary detection ─────────────────────────────────────────
    void detectWalls();

    [[nodiscard]] const std::vector<Wall>& walls()           const noexcept { return walls_; }
    [[nodiscard]] const CellSet&           disallowedCells() const noexcept { return disallowed_; }
    [[nodiscard]] bool isBlocked(Cell origin, int agentSize) const noexcept;

    // ── Agent management ──────────────────────────────────────────────────
    // Called from Python after the GUI collects AgentConfig objects.
    void addAgentConfig(AgentConfig cfg);
    void applyAgentConfigs();
    void clearAgents();

    [[nodiscard]] std::span<const PlacedAgent> placedAgents() const noexcept;

    // Move an already-placed agent to a new grid origin using the specified
    // movement type.  Returns false if the agent lacks sufficient budget.
    bool moveAgent(int idx, Cell newOrigin,
                   MovementType type = MovementType::Walk) noexcept;

    // Jump an agent to a new location (ignores walls, deducts from walk budget).
    // is_running: true for running jump (full strength), false for standing jump (half strength).
    bool jumpAgent(int idx, Cell newOrigin, bool is_running) noexcept;

    // Remove a placed agent by index.
    void removeAgent(int idx) noexcept;

    // Stats accessors (by index into placedAgents()).
    [[nodiscard]] Agent::Stats getAgentStats(int idx) const noexcept;
    void setAgentStats(int idx, Agent::Stats s) noexcept;

    // Apply the Dash action: sets the dashing condition and adds the agent's
    // base speeds to its remaining movement budgets for this turn.
    void applyDash(int idx) noexcept;

    // Weapon accessors (by index into placedAgents()).
    [[nodiscard]] std::vector<Weapon> getAgentWeapons(int idx) const noexcept;
    void setAgentWeapons(int idx, std::vector<Weapon> weapons) noexcept;
    void addWeaponToAgent(int idx, Weapon w) noexcept;
    void removeWeaponFromAgent(int idx, int weapon_idx) noexcept;

    // Spell accessors (by index into placedAgents()).
    [[nodiscard]] std::vector<Spell> getAgentSpells(int idx) const noexcept;
    void setAgentSpells(int idx, std::vector<Spell> spells) noexcept;
    void addSpellToAgent(int idx, Spell s) noexcept;
    void removeSpellFromAgent(int idx, int spell_idx) noexcept;

    // Movement reach
    // Returns every grid origin an agent of the given size can reach from
    // `origin` using at most `speedFt` feet of the requested movement type.
    // Walk: Dijkstra BFS through passable cells (5 ft per orthogonal or
    //       diagonal step — the simplified D&D optional rule).
    // Fly:  All origins within Chebyshev distance speedFt/5, ignoring terrain.
    [[nodiscard]] CellSet reachableCells(Cell origin, int agentSize,
                                        int speedFt, MovementType type) const;

    // ── Line-of-sight & attack range ──────────────────────────────────────
    // Bresenham ray from the centre of the `from` agent to the centre of
    // the `to` agent.  Returns false if any intermediate cell is in
    // disallowed_ (i.e. is a wall/obstacle).
    [[nodiscard]] bool hasLineOfSight(Cell from, int fromSize,
                                      Cell to,   int toSize) const noexcept;

    // All single cells within `rangeFt` feet (Chebyshev, measured from the
    // nearest edge of the attacker's footprint) that have line-of-sight.
    // Cells occupied by the attacker itself are excluded.
    // Use this for both melee (pass reachFt = 5/10/15) and ranged (pass
    // normalRangeFt or longRangeFt — call twice and subtract for two zones).
    [[nodiscard]] std::vector<Cell> attackTargetCells(Cell origin, int agentSize,
                                                      int rangeFt) const;

    // ── Terrain multipliers ───────────────────────────────────────────────
    // Movement cost multiplier for each cell (default 1.0).
    // Used for difficult terrain, spells, etc. Stored as cols × rows.
    [[nodiscard]] double getTerrainMultiplier(Cell c) const noexcept;
    void setTerrainMultiplier(Cell c, double mult) noexcept;
    void setTerrainMultiplierRect(Cell topLeft, int width, int height, double mult) noexcept;
    void resetTerrainMultipliers() noexcept;

    // ── Temporary terrain effects ──────────────────────────────────────────
    // Place a temporary terrain effect (from spells, items, etc.).
    // Returns unique effect id. Python stores this for later removal/metadata.
    // Converts cells to flat indices and registers the effect.
    [[nodiscard]] int placeTerrainEffect(std::string name,
                                         std::vector<Cell> cells,
                                         TerrainDifficulty difficulty,
                                         int turns_remaining,
                                         int source_agent_idx);

    // Decrement turns_remaining for effects sourced from the given agent.
    // Removes expired effects (turns_remaining <= 0).
    // Returns list of removed effect ids so Python can clean up metadata.
    [[nodiscard]] std::vector<int> tickTerrainEffects(int source_agent_idx);

    // Decrement turns_remaining for DM-placed effects (source_agent_idx == -1).
    // Called at round boundary. Returns list of removed effect ids.
    [[nodiscard]] std::vector<int> tickDMTerrainEffects();

    // Remove all effects sourced from the given agent (concentration drop, death, etc.).
    // Returns list of removed effect ids.
    [[nodiscard]] std::vector<int> removeTerrainEffectsBySource(int source_agent_idx);

    // Remove a specific effect by id. Called for manual DM removal mid-combat.
    void removeTerrainEffect(int effect_id);

    // Clear all terrain effects (end of combat).
    void clearTerrainEffects() noexcept;

    // Get a copy of all active terrain effects (for Python to render).
    [[nodiscard]] std::vector<ActiveTerrainEffect> activeTerrainEffects() const;
    [[nodiscard]] bool hasActiveTerrainEffects() const noexcept;

    // ── Tuning parameters ─────────────────────────────────────────────────
    struct DetectionParams {
        // Grid-line detection (Hough)
        double cannyLow       = 50.0;
        double cannyHigh      = 150.0;
        int    houghThreshold = 80;
        int    minLineLength  = 40;
        int    maxLineGap     = 10;

        // Cell-darkness wall detection (primary method).
        // Any cell whose mean grayscale value is below this threshold
        // is considered a wall/obstacle (0 = black, 255 = white).
        double darkCellThreshold = 40.0;

        // Edge-based wall detection (secondary, for line-wall maps).
        // Set to true if your map draws walls as thick lines between cells
        // rather than as black filled cells.
        bool   detectEdgeWalls = false;
        int    wallMinPx       = 6;

        // Flood-fill to find additional unreachable areas beyond dark cells.
        bool   floodFill  = true;
        Cell   floodSeed  = {1, 1};   // should be a clearly passable cell
    } params;

private:
    // detectGridLines and classifyWalls take cv::Mat — they live entirely
    // in battle_map.cpp as static free functions to keep OpenCV out of this header.
    void floodFillPassable();

    // True iff an agent of `size` placed at `origin` lies entirely within the grid.
    [[nodiscard]] bool inBounds(Cell origin, int size) const noexcept;

    // Rebuild tempTerrainDiff_ from activeTerrainEffects_.
    // Called whenever effects are added, removed, or ticked.
    // Uses std::max to pick the most restrictive difficulty per cell.
    void updateTerrain();

    std::filesystem::path mapImagePath_;
    int cols_{0}, rows_{0}, cellPx_{0};
    std::vector<int>   hLines_, vLines_;
    std::vector<Wall>  walls_;
    CellSet            disallowed_;
    std::vector<double> terrainMult_;         // cols × rows static movement multipliers (default 1.0)
    std::vector<AgentConfig>  agentConfigs_;
    std::vector<PlacedAgent>  placedAgents_;

    // Temporary terrain effects (spells, items, etc. with duration)
    std::vector<ActiveTerrainEffect> activeTerrainEffects_;
    std::vector<TerrainDifficulty>   tempTerrainDiff_;  // pre-computed overlay per cell (default Normal)
    int nextEffectId_{0};  // monotonically increasing effect id generator
};

} // namespace rpg
