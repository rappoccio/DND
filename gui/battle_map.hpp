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
#include "armor.hpp"

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

// ── Terrain types ──────────────────────────────────────────────────────────
enum class TerrainType {
    Standard = 0,  // land; impassable to swim
    Water    = 1,  // impassable to walk/burrow
    Wall     = 2,  // impassable to all except burrow
    Chasm    = 3,  // impassable to walk/burrow/swim
};

// ── Terrain difficulty levels for temporary effects ─────────────────────────
// Ordered by restrictiveness: Normal (0) < Halved (1) < Quartered (2).
// std::max gives "most restrictive wins" for stacking.
enum class TerrainDifficulty {
    Normal = 0,      // 1.0x movement cost (no effect)
    Halved = 1,      // 0.5x movement cost (Spirit Guardians, etc.)
    Quartered = 2,   // 0.25x movement cost (Plant Growth, etc.)
    Slipping = 3,    // Icy/greasy surface; DEX save every N feet or go prone
};

// ── Visibility/Light levels for D&D 5e lighting and vision ─────────────────────
// Unified enum for both agent-to-agent sight and location lighting.
// Ordered by restrictiveness: Clear (0) < Dim (1) < LightlyObscured (2) < Dark (3) < MagicalDark (4) < Blocked (5).
enum class VisibilityLevel {
    Clear = 0,              // Fully visible / BrightLight (normal vision)
    Dim,                    // Lightly obscured but visible / DimLight (visible to all with LOS)
    LightlyObscured,        // Obscured by fog/shadows (disadvantage on perception/attacks)
    Dark,                   // Heavily obscured / Darkness (needs darkvision to see)
    MagicalDark,            // Impenetrable / MagicalDarkness (needs devil's sight to see)
    Blocked                 // Cannot see at all (blocked by walls, full cover, etc.)
};

// ── Active temporary terrain effect ────────────────────────────────────────
struct ActiveTerrainEffect {
    int                 id;               // unique, returned to Python on add
    std::string         name;             // "Grease", "Web", "Spike Growth", etc.
    std::vector<int>    cell_indices;     // flat: row*cols_ + col
    TerrainDifficulty   difficulty;       // Halved or Quartered
    int                 turns_remaining;  // -1 = permanent, 0+ = expires after N turns
    int                 source_agent_idx; // -1 = DM-placed or no concentration requirement
    // Slipping terrain (ice/grease) settings
    int                 slip_save_dc{10};        // DC for DEX save (default 10)
    int                 slip_distance_feet{5};  // Feet moved before requiring save (default 5)
};

// ── Active temporary light effect ──────────────────────────────────────────
struct ActiveLightEffect {
    int              id;               // unique, returned to Python on add
    std::string      name;             // "Torch", "Darkness", "Faerie Fire", etc.
    std::vector<int> cell_indices;     // flat: row*cols_ + col
    VisibilityLevel  light_level;      // Clear, Dim, Dark, or MagicalDark
    int              turns_remaining;  // -1 = permanent, 0+ = expires after N turns
    int              source_agent_idx; // -1 = DM-placed or map-defined
};

// ── Active obscuration effect (fog clouds, magical darkness, etc.) ──────────
struct ActiveObscurationEffect {
    int          id;                     // unique, returned to Python on add
    int          source_agent_idx = -1;  // caster/source of the effect
    std::vector<Cell> cells;             // cells occupied by this obscuration
    VisibilityLevel obscuration_level;   // LightlyObscured, Dark, or MagicalDark
    int          turns_remaining = 0;    // -1 = permanent, 0+ = expires after N turns
};

// ── Active persistent spell effect (AoE affecting agents over time) ─────────
struct ActiveSpellEffect {
    int          caster_idx     = -1;      // index into BattleMap::placedAgents()
    int          spell_idx      = -1;      // index into caster's spell list
    Spell        spell;                    // copy of the spell (damage, duration, etc.)
    std::vector<Cell> cells;               // cells occupied by this effect
    int          turns_remaining = 0;      // decremented per turn; effect expires when 0
    int          effect_id      = -1;      // unique ID for removal
};

// ── Active spell-applied condition on an agent ──────────────────────────────
struct ActiveAgentCondition {
    int              agent_idx            = -1;   // index into BattleMap::placedAgents()
    int              caster_idx           = -1;   // who cast the spell (for concentration checks)
    int              spell_idx            = -1;   // index into caster's spell list
    std::string      condition_name;              // "Paralyzed", "Stunned", etc.
    int              turns_remaining      = 0;    // decremented per turn; condition expires when 0
    int              next_save_turn       = 0;    // turn number when next save is attempted
    SaveAbility_t save_ability    = SaveDex;  // which save to repeat
    int              save_dc              = 0;    // DC for saving throws (must be set when condition created)
    int              save_repeat_turns    = 1;    // repeat save check every N turns (1 = every turn)
    int              condition_id         = -1;   // unique ID for tracking/removal
};

// ── A placed agent on the map ──────────────────────────────────────────────
struct PlacedAgent {
    std::shared_ptr<Agent> agent;
    Cell                   origin;        // top-left cell of the NxN footprint
    Agent::Stats           stats;         // D&D 5.5e character stats
    std::array<Weapon, 3>  weapons;       // [Main Hand, Off Hand, Ranged]
    std::vector<Spell>     spells;        // known spells (may be empty)
    std::array<Armor, 6>   armor;         // [Helmet, Chest, Leggings, Boots, Gloves, Cloak]
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
    [[nodiscard]] bool isBlocked(Cell origin, int agentSize, MovementType mt = MovementType::Walk) const noexcept;

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

    // Force move an agent (push/knockback). Moves agent away from push_from origin.
    // Does not consume movement budget. Stops at walls or map edge.
    // Returns number of cells actually moved.
    [[nodiscard]] int forceMoveAgent(int idx, Cell push_from, int push_ft) noexcept;

    // Remove a placed agent by index.
    void removeAgent(int idx) noexcept;

    // Stats accessors (by index into placedAgents()).
    [[nodiscard]] Agent::Stats getAgentStats(int idx) const noexcept;
    void setAgentStats(int idx, Agent::Stats s) noexcept;

    // Conditions accessors (by index into placedAgents()).
    [[nodiscard]] Agent::Conditions getAgentConditions(int idx) const noexcept;
    void setAgentConditions(int idx, const Agent::Conditions& c) noexcept;

    // Apply the Dash action: sets the dashing condition and adds the agent's
    // base speeds to its remaining movement budgets for this turn.
    void applyDash(int idx) noexcept;

    // Weapon accessors (by index into placedAgents()).
    [[nodiscard]] std::array<Weapon, 3> getAgentWeapons(int idx) const noexcept;
    void setAgentWeapons(int idx, std::array<Weapon, 3> weapons) noexcept;

    // Armor accessors (by index into placedAgents()): 6 slots [helmet, chest, leggings, boots, gloves, cloak].
    [[nodiscard]] std::array<Armor, 6> getAgentArmor(int idx) const noexcept;
    void setAgentArmor(int idx, std::array<Armor, 6> armor) noexcept;

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

    // Filter spell cells by range and LOS requirements.
    // If spell.requires_los is false, only filters by range.
    // If spell.check_los_on_center is true, only the centerCell needs LOS (standard D&D 5e).
    // If spell.check_los_on_center is false, all cells need LOS (rare case).
    [[nodiscard]] std::vector<Cell> filterSpellCells(const std::vector<Cell>& cells,
                                                     Cell casterOrigin, int casterSize,
                                                     const Spell& spell, Cell centerCell) const;

    // ── Terrain multipliers ───────────────────────────────────────────────
    // Movement cost multiplier for each cell (default 1.0).
    // Used for difficult terrain, spells, etc. Stored as cols × rows.
    [[nodiscard]] double getTerrainMultiplier(Cell c, MovementType mt = MovementType::Walk) const noexcept;
    void setTerrainMultiplier(Cell c, double mult) noexcept;
    void setTerrainMultiplierRect(Cell topLeft, int width, int height, double mult) noexcept;
    void resetTerrainMultipliers() noexcept;

    // ── Terrain types ──────────────────────────────────────────────────────
    [[nodiscard]] TerrainType getTerrainType(Cell c) const noexcept;
    void setTerrainType(Cell c, TerrainType t) noexcept;

    // ── Temporary terrain effects ──────────────────────────────────────────
    // Place a temporary terrain effect (from spells, items, etc.).
    // Returns unique effect id. Python stores this for later removal/metadata.
    // Converts cells to flat indices and registers the effect.
    [[nodiscard]] int placeTerrainEffect(std::string name,
                                         std::vector<Cell> cells,
                                         TerrainDifficulty difficulty,
                                         int turns_remaining,
                                         int source_agent_idx,
                                         int slip_save_dc = 10,
                                         int slip_distance_feet = 5);

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

    // Rebuild tempTerrainDiff_ from activeTerrainEffects_.
    // Called whenever effects are added, removed, or ticked.
    // Uses std::max to pick the most restrictive difficulty per cell.
    void updateTerrain();

    // Clear all terrain effects (end of combat).
    void clearTerrainEffects() noexcept;

    // Get a copy of all active terrain effects (for Python to render).
    [[nodiscard]] std::vector<ActiveTerrainEffect> activeTerrainEffects() const;
    [[nodiscard]] bool hasActiveTerrainEffects() const noexcept;

    // ── Light levels (visibility & darkvision) ────────────────────────────
    // Get/set the light level at a cell (default BrightLight).
    [[nodiscard]] VisibilityLevel getVisibilityLevel(Cell c) const noexcept;
    void setVisibilityLevel(Cell c, VisibilityLevel lvl) noexcept;
    void resetVisibilityLevels() noexcept;  // fills entire map with BrightLight

    // Check if an observer can see a target, considering LOS, light, and vision types.
    // obs_origin/tgt_origin: top-left cell of each agent's footprint
    // obs_size/tgt_size: agent sizes (1-6)
    // darkvision_ft, truesight_ft, devilssight_ft: observer's vision ranges in feet (0 = none)
    // Returns true iff LOS is clear AND light conditions permit visibility with given vision.
    [[nodiscard]] bool canSee(Cell obs_origin, int obs_size,
                              int darkvision_ft, int truesight_ft, int devilssight_ft,
                              Cell tgt_origin, int tgt_size) const noexcept;

    // Check if observer has disadvantage on perception vs target (due to lighting).
    // Returns true for DimLight (normal/devil's sight) and Darkness (darkvision only).
    [[nodiscard]] bool perceptionDisadvantage(Cell obs_origin, int obs_size,
                                              int darkvision_ft, int truesight_ft, int devilssight_ft,
                                              Cell tgt_origin, int tgt_size) const noexcept;

    // Apply base lighting from JSON: set default light level, then apply spherical sources.
    // sources: list of (pixel_x, pixel_y, bright_radius_ft, dim_radius_ft)
    void applyBaseLighting(VisibilityLevel default_light,
                           const std::vector<std::tuple<int, int, int, int>>& sources) noexcept;

    // Recompute lightLevel_ from baseVisibilityLevel_ + activeLightEffects_.
    void updateLighting() noexcept;

    // Dynamic light effects (analogous to terrain effects):
    [[nodiscard]] int  placeLightEffect(std::string name, std::vector<Cell> cells,
                                        VisibilityLevel level, int turns_remaining,
                                        int source_agent_idx) noexcept;
    [[nodiscard]] std::vector<int> tickLightEffects(int source_agent_idx) noexcept;
    [[nodiscard]] std::vector<int> tickDmLightEffects() noexcept;
    [[nodiscard]] std::vector<int> removeLightEffectsBySource(int source_agent_idx) noexcept;
    void removeLightEffect(int id) noexcept;
    void clearLightEffects() noexcept;
    [[nodiscard]] bool hasActiveLightEffects() const noexcept;
    [[nodiscard]] const std::vector<ActiveLightEffect>& activeLightEffects() const noexcept;

    // ── Persistent AoE Spell Effects (damage/conditions over multiple turns) ──
    // Add a new persistent spell effect to the map. Returns a unique effect_id.
    [[nodiscard]] int addSpellEffect(ActiveSpellEffect effect) noexcept;
    // Remove a spell effect by id.
    void removeSpellEffect(int effect_id) noexcept;
    // Get all active spell effects (for Python to render overlay).
    [[nodiscard]] const std::vector<ActiveSpellEffect>& activeSpellEffects() const noexcept;
    // Decrement turns_remaining for effects sourced from the given agent.
    // Removes expired effects. Returns list of removed effect ids.
    [[nodiscard]] std::vector<int> tickSpellEffects(int source_agent_idx) noexcept;
    // Clear all spell effects (end of combat).
    void clearSpellEffects() noexcept;

    // ── Obscuration Effects (fog clouds, magical darkness, etc.) ────────────
    // Add a new obscuration effect to the map. Returns a unique effect_id.
    [[nodiscard]] int addObscurationEffect(ActiveObscurationEffect effect) noexcept;
    // Remove an obscuration effect by id.
    void removeObscurationEffect(int effect_id) noexcept;
    // Get all active obscuration effects (for Python to render overlay).
    [[nodiscard]] const std::vector<ActiveObscurationEffect>& activeObscurationEffects() const noexcept;
    // Get the obscuration level at a specific cell. Returns BrightLight if no obscuration.
    [[nodiscard]] VisibilityLevel getObscurationAtCell(const Cell& c) const noexcept;
    // Get/set light level at a cell (for debugging or manual map configuration).
    [[nodiscard]] VisibilityLevel getLightLevel(Cell c) const noexcept;
    void setLightLevel(Cell c, VisibilityLevel lvl) noexcept;
    void resetLightLevels() noexcept;
    // Decrement turns_remaining for all obscuration effects.
    // Removes expired effects. Returns list of removed effect ids.
    [[nodiscard]] std::vector<int> tickObscurationEffects() noexcept;
    // Clear all obscuration effects (end of combat).
    void clearObscurationEffects() noexcept;

    // ── NPC Spell Initialization ────────────────────────────────────────
    // Set is_npc=true and initialize uses_max/uses_remaining from spell groups.
    // groups: maps N (uses/day) -> list of spell names in that group.
    // Called once after setAgentSpells().
    void initNpcSpellGroups(int agent_idx,
                            const std::map<int, std::vector<std::string>>& groups) noexcept;

    // Mutable access to a placed agent for in-place modification.
    [[nodiscard]] PlacedAgent& placedAgentMut(int idx) noexcept;

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

    // Dijkstra pathfinding for path-based movement (Walk, Swim, Burrow, Jump).
    [[nodiscard]] CellSet pathfindMovement(Cell origin, int tokenSize,
                                           int speedFt, MovementType type) const;

    std::filesystem::path mapImagePath_;
    int cols_{0}, rows_{0}, cellPx_{0};
    std::vector<int>   hLines_, vLines_;
    std::vector<Wall>  walls_;
    CellSet            disallowed_;
    std::vector<double>     terrainMult_;     // cols × rows static movement multipliers (default 1.0)
    std::vector<TerrainType> terrainType_;    // cols × rows terrain types (default Standard)
    std::vector<VisibilityLevel>  baseVisibilityLevel_; // cols × rows base light levels (from JSON; default BrightLight)
    std::vector<VisibilityLevel>  lightLevel_;     // cols × rows computed light levels (base + effects; default BrightLight)
    std::vector<AgentConfig>  agentConfigs_;
    std::vector<PlacedAgent>  placedAgents_;

    // Temporary terrain effects (spells, items, etc. with duration)
    std::vector<ActiveTerrainEffect> activeTerrainEffects_;
    std::vector<TerrainDifficulty>   tempTerrainDiff_;  // pre-computed overlay per cell (default Normal)
    int nextEffectId_{0};  // monotonically increasing terrain effect id generator

    // Dynamic light effects (spells, DM-placed lights, etc.)
    std::vector<ActiveLightEffect> activeLightEffects_;
    int nextLightEffectId_{0};  // monotonically increasing light effect id generator

    // Persistent AoE spell effects (Wall of Fire, Spike Growth, etc.)
    std::vector<ActiveSpellEffect> activeSpellEffects_;
    int nextSpellEffectId_{0};  // monotonically increasing spell effect id generator

    // Active obscuration effects (fog clouds, magical darkness, etc.)
    std::vector<ActiveObscurationEffect> activeObscurationEffects_;
    int nextObscurationEffectId_{0};  // monotonically increasing obscuration effect id generator
};

} // namespace rpg
