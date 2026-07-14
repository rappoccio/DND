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
#include "cell.hpp"
#include "item.hpp"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <unordered_set>
#include <vector>

namespace rpg {

// ── Wall between two adjacent cells ───────────────────────────────────────
struct Wall {
    Cell a;
    Cell b;
    bool operator==(const Wall&) const noexcept = default;
};

// ── Door occupying one or more doorway cells ───────────────────────────────
// A door is one or more CELLS, not an edge. A wide door (double door, portcullis,
// gate) spans up to 4 contiguous cells that open/close/lock as a single object.
// State lives here; syncDoorTerrain() keeps every cell's TerrainType in agreement
// (open → Standard/passable, closed → Wall), so isBlocked() and hasLineOfSight()
// need no door-specific logic.
struct Door {
    int  id{-1};
    std::vector<Cell> cells;   // doorway cells (1..4) — source of truth for placement
    bool open{false};
    bool locked{false};
    int  lock_dc{15};
    // Arcane Lock (the spell): magically held shut; cannot be opened by a normal
    // pull or a mundane pick. Knock suppresses it for arcane_suppressed_turns.
    bool arcane_lock{false};
    int  arcane_suppressed_turns{0};
    // Anchor cell (first occupied cell): the glyph/label anchor and the value the
    // single-cell convenience API reports. Empty door → {-1,-1}.
    [[nodiscard]] Cell anchor() const noexcept {
        return cells.empty() ? Cell{-1, -1} : cells.front();
    }
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
    Blocked,                // Cannot see at all (blocked by walls, full cover, etc.)
    // Sunlight is a distinct brightness category that, for vision, behaves exactly like Clear
    // (BrightLight). It is tracked separately so vampire features (Sunlight Sensitivity, etc.) can
    // ask "is this cell in sunlight?". Appended at the end so the restrictiveness ordering of the
    // values above is unchanged; brightness combining is handled by brighter() (Sunlight is the
    // brightest), never by raw enum comparison.
    Sunlight,
    // HeavilyObscured = fog / smoke / dense foliage. Like Dark it produces the effectively-Blinded
    // state, but it is the NON-magical, light-independent kind that DARKVISION AND DEVIL'S SIGHT DO
    // NOT pierce (only Truesight/Blindsight do) and that bright light cannot dispel. This is the key
    // distinction from Dark (= Darkness, pierced by darkvision) and MagicalDark (= magical darkness,
    // pierced by devil's sight). Appended last to preserve the spells.json `light_level` int contract
    // (Darkness=4, Daylight=6); HeavilyObscured=7. It is an OVERRIDE level — see updateLighting() and
    // canSee(); it is never combined via brighter() (which treats it as the dimmest).
    HeavilyObscured
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
    int                 spell_idx{-1};                  // caster's spell index (-1 = none)
    bool                requires_concentration{false};  // terrain ends when caster drops concentration
    // Moving emanation (e.g. Spirit Guardians): the difficult-terrain footprint follows this
    // agent. -1 = static placement. anchor_radius_ft is the Sphere radius used to re-center.
    int                 anchor_agent_idx{-1};
    int                 anchor_radius_ft{0};
    // "Creatures of your choice" sparing: when true, the source agent and its allies ignore
    // this terrain (mirrors the spell's selective_targeting / the zone-damage faction rule).
    bool                spares_source_allies{false};
};

// ── Active temporary light effect ──────────────────────────────────────────
struct ActiveLightEffect {
    int              id;               // unique, returned to Python on add
    std::string      name;             // "Torch", "Darkness", "Faerie Fire", etc.
    std::vector<int> cell_indices;     // flat: row*cols_ + col
    VisibilityLevel  light_level;      // Clear, Dim, Dark, or MagicalDark
    int              turns_remaining;  // -1 = permanent, 0+ = expires after N turns
    int              source_agent_idx; // -1 = DM-placed or map-defined
    int              see_through_agent_idx{-1}; // agent who sees through this MagicalDark (Shadow Arts: Darkness); -1 = nobody
    int              anchor_agent_idx{-1};       // if >=0, cells re-center on this agent (moving Sphere / Emanation)
    int              anchor_radius_ft{0};        // Sphere radius used to re-center an anchored light effect
};


// ── Active persistent spell effect (AoE affecting agents over time) ─────────
struct ActiveSpellEffect {
    int          caster_idx     = -1;      // index into BattleMap::placedAgents()
    int          spell_idx      = -1;      // index into caster's spell list
    Spell        spell;                    // copy of the spell (damage, duration, etc.)
    std::vector<Cell> cells;               // cells occupied by this effect
    int          turns_remaining = 0;      // decremented per turn; effect expires when 0
    int          effect_id      = -1;      // unique ID for removal
    int          anchor_agent_idx = -1;    // if >=0, cells re-center on this agent (moving Sphere)
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
    OnDamage_t       on_damage            = OnDamage_t::None;  // End / RepeatSave on taking damage

    // ── Delayed / stored effect (Quivering Palm, Delayed Blast Fireball, …) ──────
    // When delayed_trigger is true this condition is a *planted* effect that does
    // nothing on its own; it resolves into a burst of damage when its owner
    // detonates it (CombatEngine::triggerDelayedEffect) — or automatically when
    // turns_remaining hits 0, if delay_auto_on_expire is set (Delayed Blast
    // Fireball). The save (delay_requires_save) reuses save_ability / save_dc.
    // This is the general mechanism the GUI surfaces as a "detonate" button; any
    // future stored-effect ability builds one of these instead of a bespoke path.
    bool          delayed_trigger      = false;
    int           delay_dice           = 0;        // number of damage dice (e.g. 10)
    int           delay_die_size       = 0;        // die size (e.g. 12 → d12)
    int           delay_flat_bonus     = 0;        // flat damage added after the dice
    MagicDamage_t delay_damage_type    = MagicDamage_t::Force;
    bool          delay_requires_save  = true;     // target rolls save_ability vs save_dc
    bool          delay_half_on_save   = true;     // half damage on a successful save
    bool          delay_drop_to_zero   = false;    // failed save drops the target to 0 HP
    bool          delay_auto_on_expire = false;    // detonate when duration ends (vs. owner-triggered)
    std::string   delay_label;                     // display label, e.g. "Quivering Palm"

    // ── Caster "kickback" on condition end (Vistani Curse) ──────────────────────
    // When kickback_dice > 0, ending this condition by ANY path deals
    // kickback_dice × d(kickback_die_size) of kickback_damage_type to the CASTER
    // (caster_idx), automatically (no save). Recipient is always the caster, NOT the
    // condition's target. Suppressed when the target has died (see onConditionEnded).
    int           kickback_dice         = 0;        // e.g. 3 or 5
    int           kickback_die_size      = 0;        // e.g. 6 → d6
    MagicDamage_t kickback_damage_type   = MagicDamage_t::Psychic;

    // ── Vistani Curse effect state ──────────────────────────────────────────────
    // Which curse effect this tracked condition carries (beyond any base condition
    // flag such as Blinded/Deafened). These are set at apply time from the spell's
    // AttackCondition::curse_kind + the cast-time SpellAction::curse_choice, and
    // torn down in onConditionEnded when the curse ends.
    //   curse_disadv_ability : SaveAbility_t made to roll at Disadvantage; -1 = none.
    //   curse_vuln_type_code : encoded damage type made vulnerable (2.0×); -1 = none.
    //                          0..NumMagicDamage_t-1 = magic, 100+i = physical type i.
    //   curse_vuln_prev_mult : the target's prior multiplier for that type, restored on end.
    int   curse_disadv_ability = -1;
    int   curse_vuln_type_code = -1;
    float curse_vuln_prev_mult = 1.0f;
};

// ── A placed agent on the map ──────────────────────────────────────────────
// ── NPC automation strategy ─────────────────────────────────────────────────
// Selects which decision algorithm an automated NPC uses on its turn. Only takes
// effect when PlacedAgent::is_npc_automated is true (and gated by the difficulty
// level). Simple = baseline "attack the nearest/weakest enemy" behaviour.
enum class NpcAutomationStrategy {
    Simple = 0,             // Baseline: engage the nearest reachable enemy with a basic attack
    PreferTargetCaster = 1, // Prioritise enemy spellcasters as targets
    PreferAOE = 2,          // Prefer area-of-effect options that catch multiple enemies
    PreferRange = 3,        // Keep distance and favour ranged attacks
    PreferHide = 4,         // Favour stealth/hiding and ambush positioning
    NoOp = 5,               // Bystander: take no action and no movement — cower in place, end turn
};

struct PlacedAgent {
    std::shared_ptr<Agent> agent;
    Cell                   origin;        // top-left cell of the NxN footprint
    // Variable-length attack list. Invariant: always padded to ≥3 entries so the PC path's
    // weapons[0]=Main Hand, [1]=Off Hand, [2]=Ranged stays valid; monsters may add more (Attack 4+).
    std::vector<Weapon>    weapons = std::vector<Weapon>(3);
    std::vector<Spell>     spells;        // known spells (may be empty)
    std::vector<Item>      items;         // carried consumables — potions etc. (may be empty)
    std::array<Armor, 6>   armor;         // [Helmet, Chest, Leggings, Boots, Gloves, Cloak]
    // ── Summoning ──────────────────────────────────────────────────────────
    int         summoner_idx      = -1;    // index of the summoner; -1 = not a summon
    bool        removed_from_play = false; // tombstoned (summon dismissed): skip in turns + rendering
    std::string summon_spell;              // name of the spell that created this summon (if any)
    // ── Faction / team ─────────────────────────────────────────────────────
    // Encounter-side team assignment (NOT an intrinsic Stat). 0 = neutral/unassigned
    // (its own faction, hostile to everyone). 1+ = red/blue/... Used for hide vs only
    // enemies, sparing allies from selective AoEs, and restricting heals to allies.
    int         faction           = 0;
    // ── On Deck / reinforcements (phased battles) ──────────────────────────
    // true = a reserve combatant: placed on the map and still rendered, but
    // EXCLUDED from initiative (rollInitiative skips it) until the DM deploys
    // it. Deploying clears this flag and inserts the agent into the live order.
    bool        on_deck           = false;
    // ── NPC automation ─────────────────────────────────────────────────────
    // When is_npc_automated is true, the GUI may drive this agent's turn with an
    // automated decision algorithm instead of requiring manual control. The
    // difficulty level (0+) lets the DM scale how aggressively the algorithm plays;
    // strategy picks which decision algorithm runs.
    bool                  is_npc_automated              = false;
    int                   npc_automation_difficulty_level = 0;
    NpcAutomationStrategy npc_automation_strategy       = NpcAutomationStrategy::Simple;
};

// ── Agent configuration (supplied from Python GUI) ─────────────────────────
struct AgentConfig {
    std::string           name;
    std::filesystem::path spritePath;
    int                   size{1};      // 1–6
    int                   startCol{0};
    int                   startRow{0};
    Agent::Stats          stats;
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

    // Replace the auto-detected grid with a uniform grid of square cells `cellPx`
    // pixels on a side, phase-aligned so (anchorX, anchorY) lands on a cell boundary,
    // tiled across the whole map image. Lets the GUI define the grid by sampling one
    // tile when line-detection mis-reads a map (e.g. textured maps with a border
    // margin). Clears walls and resets the per-cell terrain/light buffers to the new
    // dimensions.
    void setUniformGrid(int cellPx, int anchorX, int anchorY);

    [[nodiscard]] int gridCols()      const noexcept { return cols_; }
    [[nodiscard]] int gridRows()      const noexcept { return rows_; }
    [[nodiscard]] int cellPixelSize() const noexcept { return cellPx_; }

    // ── Global placement (multi-map dungeons) ─────────────────────────────
    // This page's origin on the shared dungeon grid: the global (X, Y, Z) of the
    // page's local (0, 0). All engine hot paths stay local (z=0); these convert
    // between local (col,row) and global (X,Y,Z) only at the dungeon-manifest seam.
    [[nodiscard]] int originCol() const noexcept { return origin_col_; }
    [[nodiscard]] int originRow() const noexcept { return origin_row_; }
    [[nodiscard]] int zLevel()    const noexcept { return z_level_; }
    void setOriginCol(int v) noexcept { origin_col_ = v; }
    void setOriginRow(int v) noexcept { origin_row_ = v; }
    void setZLevel(int v)    noexcept { z_level_    = v; }

    // Local (col,row) → global cell (X = origin_col_+col, Y = origin_row_+row, z = z_level_).
    [[nodiscard]] Cell localToGlobal(Cell local) const noexcept {
        return Cell{origin_col_ + local.col, origin_row_ + local.row, z_level_};
    }
    // Global (X,Y,Z) → local (col,row) on THIS page; nullopt if the wrong floor or
    // outside this page's [0,cols)×[0,rows) footprint. Returned cell keeps z=0 (local).
    [[nodiscard]] std::optional<Cell> globalToLocal(int X, int Y, int Z) const noexcept {
        if (Z != z_level_) return std::nullopt;
        int c = X - origin_col_;
        int r = Y - origin_row_;
        if (c < 0 || r < 0 || c >= cols_ || r >= rows_) return std::nullopt;
        return Cell{c, r, 0};
    }

    [[nodiscard]] const std::vector<int>& hLinePositions() const noexcept { return hLines_; }
    [[nodiscard]] const std::vector<int>& vLinePositions() const noexcept { return vLines_; }

    // ── Wall / boundary detection ─────────────────────────────────────────
    void detectWalls();

    // Discard every auto-detected wall/obstacle so the map is fully passable
    // except where explicit terrain regions say otherwise. Lets the GUI offer a
    // "turn off auto-detection" toggle when the detector mis-reads a map.
    void clearWalls() noexcept { walls_.clear(); disallowed_.clear(); }

    [[nodiscard]] const std::vector<Wall>& walls()           const noexcept { return walls_; }
    [[nodiscard]] const CellSet&           disallowedCells() const noexcept { return disallowed_; }
    [[nodiscard]] bool isBlocked(Cell origin, int agentSize, MovementType mt = MovementType::Walk) const noexcept;

    // ── Agent management ──────────────────────────────────────────────────
    // Called from Python after the GUI collects AgentConfig objects.
    void addAgentConfig(AgentConfig cfg);
    void applyAgentConfigs();
    void clearAgents();

    // Spawn a single agent at runtime (e.g. a summoned creature) WITHOUT clearing or
    // rebuilding existing agents, so all runtime state (HP, conditions, concentration,
    // summon links, movement budgets) is preserved. Appends to placedAgents_ only (not
    // agentConfigs_), making the summon a transient runtime entity. The caller sets stats /
    // weapons / summoner_idx afterward by index. Returns the new index, or -1 if blocked.
    int spawnAgent(const AgentConfig& cfg);

    [[nodiscard]] std::span<const PlacedAgent> placedAgents() const noexcept;

    // Move an already-placed agent to a new grid origin using the specified
    // movement type.  Returns false if the agent lacks sufficient budget.
    bool moveAgent(int idx, Cell newOrigin,
                   MovementType type = MovementType::Walk) noexcept;

    // Jump an agent to a new location (ignores walls, deducts from walk budget).
    // is_running: true for running jump (full strength), false for standing jump (half strength).
    bool jumpAgent(int idx, Cell newOrigin, bool is_running) noexcept;

    // Force move an agent (push/knockback). By default moves the agent AWAY from push_from; with
    // pull=true, moves it TOWARD push_from instead. Does not consume movement budget. Stops at walls
    // or map edge. A pull also stops once the agent is adjacent to the puller's footprint (it never
    // moves onto or past it) — from_size is the puller's footprint side (cells); ignored for a push.
    // Returns number of cells actually moved.
    [[nodiscard]] int forceMoveAgent(int idx, Cell push_from, int push_ft,
                                     bool pull = false, int from_size = 1) noexcept;

    // Directly set an agent's position (used for grapple dragging, not validated against movement).
    // Returns false if idx is invalid or destination is out of bounds.
    bool setAgentPosition(int idx, Cell newOrigin) noexcept;

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
    [[nodiscard]] std::vector<Weapon> getAgentWeapons(int idx) const noexcept;
    void setAgentWeapons(int idx, std::vector<Weapon> weapons) noexcept;

    // Armor accessors (by index into placedAgents()): 6 slots [helmet, chest, leggings, boots, gloves, cloak].
    [[nodiscard]] std::array<Armor, 6> getAgentArmor(int idx) const noexcept;
    void setAgentArmor(int idx, std::array<Armor, 6> armor) noexcept;

    // Summon accessors (by index into placedAgents()).
    // A summon links to its summoner via summoner_idx; removed_from_play tombstones it
    // (kept in the vector to preserve every index reference, then skipped in turns + rendering).
    [[nodiscard]] int  getAgentSummonerIdx(int idx) const noexcept;
    void setAgentSummonerIdx(int idx, int summoner_idx) noexcept;

    // Faction / team accessors (0 = neutral). See PlacedAgent::faction.
    [[nodiscard]] int  getAgentFaction(int idx) const noexcept;
    void setAgentFaction(int idx, int faction) noexcept;

    // Rename / re-sprite a placed agent in-flight (GUI right-click editors).
    // Also patches the matching AgentConfig when one exists (idx < agentConfigs_),
    // so a later applyAgentConfigs() rebuild and save/load preserve the change;
    // spawn_agent'd entities (summons, pastes) live only in placedAgents_.
    void setAgentName(int idx, std::string name) noexcept;
    void setAgentSprite(int idx, std::string sprite_path) noexcept;
    [[nodiscard]] std::string getAgentSummonSpell(int idx) const noexcept;
    void setAgentSummonSpell(int idx, std::string spell_name) noexcept;
    [[nodiscard]] bool isAgentRemovedFromPlay(int idx) const noexcept;
    void setAgentRemovedFromPlay(int idx, bool removed) noexcept;

    // On-deck (reserve) accessors. See PlacedAgent::on_deck. An on-deck agent is
    // skipped by rollInitiative until the DM deploys it (clears the flag).
    [[nodiscard]] bool isAgentOnDeck(int idx) const noexcept;
    void setAgentOnDeck(int idx, bool on_deck) noexcept;

    // NPC automation accessors. See PlacedAgent's is_npc_automated /
    // npc_automation_difficulty_level / npc_automation_strategy.
    [[nodiscard]] bool isAgentNpcAutomated(int idx) const noexcept;
    void setAgentNpcAutomated(int idx, bool automated) noexcept;
    [[nodiscard]] int  getAgentNpcAutomationDifficulty(int idx) const noexcept;
    void setAgentNpcAutomationDifficulty(int idx, int level) noexcept;
    [[nodiscard]] NpcAutomationStrategy getAgentNpcAutomationStrategy(int idx) const noexcept;
    void setAgentNpcAutomationStrategy(int idx, NpcAutomationStrategy strategy) noexcept;

    // Spell accessors (by index into placedAgents()).
    [[nodiscard]] std::vector<Spell> getAgentSpells(int idx) const noexcept;
    void setAgentSpells(int idx, std::vector<Spell> spells) noexcept;
    void addSpellToAgent(int idx, Spell s) noexcept;
    void removeSpellFromAgent(int idx, int spell_idx) noexcept;

    // Inventory accessors (by index into placedAgents()). Carried consumables — see item.hpp.
    // addItemToAgent stacks by name: adding an item the agent already carries bumps its
    // quantity instead of appending a second row.
    [[nodiscard]] std::vector<Item> getAgentItems(int idx) const noexcept;
    void setAgentItems(int idx, std::vector<Item> items) noexcept;
    void addItemToAgent(int idx, Item it) noexcept;
    void removeItemFromAgent(int idx, int item_idx) noexcept;

    // Movement reach
    // Returns every grid origin an agent of the given size can reach from
    // `origin` using at most `speedFt` feet of the requested movement type.
    // Walk: Dijkstra BFS through passable cells (5 ft per orthogonal or
    //       diagonal step — the simplified D&D optional rule).
    // Fly:  All origins within Chebyshev distance speedFt/5, ignoring terrain.
    // mover_idx (default -1) lets the cost respect faction-sparing difficult terrain
    // (e.g. an ally is not slowed by their own Spirit Guardians). -1 = no sparing.
    [[nodiscard]] CellSet reachableCells(Cell origin, int agentSize,
                                        int speedFt, MovementType type,
                                        int mover_idx = -1) const;

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

    // Compute the grid cells covered by a spell's AoE geometry (1 cell = 5 ft).
    // Cone/Line emanate from the cell on the caster's casterSize×casterSize
    // footprint nearest the aim point (so a Large+ caster fires from the facing
    // edge, not its top-left origin) and never cover the caster's own space.
    // Single/Multiple return {}. For Rectangle (oriented wall), `endpoint` aims
    // the wall from `center`; when it is unset ({-1,-1}) or equals `center`, a
    // centered box is produced instead.
    [[nodiscard]] std::vector<Cell> aoeCells(Cell center, const Spell& spell,
                                             Cell casterOrigin,
                                             Cell endpoint = Cell{-1, -1},
                                             int casterSize = 1) const;

    // Cells covered by an oriented "wall": the thick segment running from `anchor`
    // toward `endpoint`, clamped to maxLenFt (1 cell = 5 ft), thickness widthFt
    // centered on the line. If anchor == endpoint, returns a single-thickness box
    // centered on anchor (degenerate fallback for non-interactive callers).
    [[nodiscard]] std::vector<Cell> wallCells(Cell anchor, Cell endpoint,
                                              int widthFt, int maxLenFt) const;

    // ── Terrain multipliers ───────────────────────────────────────────────
    // Movement cost multiplier for each cell (default 1.0).
    // Used for difficult terrain, spells, etc. Stored as cols × rows.
    [[nodiscard]] double getTerrainMultiplier(Cell c, MovementType mt = MovementType::Walk) const noexcept;
    // Mover-aware variant: difficult-terrain effects flagged spares_source_allies (e.g. Spirit
    // Guardians) do not slow their source or its allies. mover_idx == -1 → no sparing (identical
    // to getTerrainMultiplier). Iterates active effects (the precomputed overlay is faction-blind).
    [[nodiscard]] double getTerrainMultiplierFor(Cell c, MovementType mt, int mover_idx) const noexcept;
    void setTerrainMultiplier(Cell c, double mult) noexcept;
    void setTerrainMultiplierRect(Cell topLeft, int width, int height, double mult) noexcept;
    void resetTerrainMultipliers() noexcept;

    // ── Terrain types ──────────────────────────────────────────────────────
    [[nodiscard]] TerrainType getTerrainType(Cell c) const noexcept;
    void setTerrainType(Cell c, TerrainType t) noexcept;

    // ── Doors (lockable doorway cells) ─────────────────────────────────────
    // A door's blocking is expressed through the cell's TerrainType (Standard when
    // open, Wall when closed), so isBlocked/hasLineOfSight need no door logic.
    [[nodiscard]] const std::vector<Door>& doors() const noexcept { return doors_; }
    // Index into doors_ for the door occupying a cell (any of its cells), or -1 if none.
    [[nodiscard]] int doorAt(Cell c) const noexcept;
    // Create a door spanning one or more cells; returns its unique id and syncs every
    // cell's terrain. Any pre-existing door overlapping these cells is replaced first
    // (no stacking). A wide door is one logical object: it opens/closes/locks as a unit.
    int addDoor(const std::vector<Cell>& cells, bool open = false, bool locked = false,
                int lock_dc = 15, bool arcane_lock = false);
    // Single-cell convenience overload (delegates to the multi-cell form).
    int addDoor(Cell c, bool open = false, bool locked = false,
                int lock_dc = 15, bool arcane_lock = false);
    // Remove a door by id; restores all of its cells to Standard terrain.
    void removeDoor(int id) noexcept;
    // Open/close: openDoor fails (returns false) on a locked or arcane-locked door.
    bool openDoor(int id) noexcept;
    bool closeDoor(int id) noexcept;
    void lockDoor(int id, int dc) noexcept;
    void unlockDoor(int id) noexcept;
    // Knock spell semantics: removes a mundane lock; an Arcane Lock is SUPPRESSED (not
    // removed) for arcane_suppress_turns; then the door is opened. Returns true if a
    // door with this id exists and is now open. (No tick decrements arcane_suppressed_turns
    // yet — a large count keeps the lock suppressed for the rest of combat, matching RAW's
    // 10-minute suppression.)
    bool knockDoor(int id, int arcane_suppress_turns = 100) noexcept;

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
                                         int slip_distance_feet = 5,
                                         int spell_idx = -1,
                                         bool requires_concentration = false,
                                         int anchor_agent_idx = -1,
                                         int anchor_radius_ft = 0,
                                         bool spares_source_allies = false);

    // Re-point an anchored terrain effect's footprint (moving emanation follows the caster).
    void setTerrainEffectCells(int effect_id, std::vector<Cell> cells) noexcept;

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
                                        int source_agent_idx,
                                        int see_through_agent_idx = -1,
                                        int anchor_agent_idx = -1,
                                        int anchor_radius_ft = 0) noexcept;
    // Re-point an anchored light effect's footprint (moving emanation follows the caster).
    void setLightEffectCells(int effect_id, std::vector<Cell> cells) noexcept;
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
    // Replace the cells of an existing spell effect (used to re-center a moving Sphere).
    void setSpellEffectCells(int effect_id, std::vector<Cell> cells) noexcept;
    // Decrement turns_remaining for effects sourced from the given agent.
    // Removes expired effects. Returns list of removed effect ids.
    [[nodiscard]] std::vector<int> tickSpellEffects(int source_agent_idx) noexcept;
    // Clear all spell effects (end of combat).
    void clearSpellEffects() noexcept;

    // ── Fog of war (persistent explored mask, PC-party scoped) ─────────────
    // A monotonic "has ever been seen" mask over the grid. Cells only ever go
    // unexplored → explored (revealFogForFaction ORs in newly-seen cells; nothing
    // clears a bit except the DM-facing clearFog / a fresh grid analysis). The GUI
    // greys out unexplored cells and hides enemy tokens standing entirely in them.
    // Single mask, PC-party only (see FOG_OF_WAR_PLAN.md); promote to a per-faction
    // map if multi-side fog is ever needed.
    //
    // Reveal (monotonic OR): for each LIVING placed agent on `faction`, mark every
    // cell it can currently see (canSee, honoring LOS/doors/lighting/senses). Reads
    // the agent's full Stats directly so blindsight can fold in later without
    // touching canSee's signature.
    void revealFogForFaction(int faction) noexcept;
    [[nodiscard]] bool isExplored(Cell c) const noexcept;
    [[nodiscard]] const std::vector<uint8_t>& exploredMask() const noexcept { return explored_; }
    [[nodiscard]] std::vector<Cell> exploredCells() const;         // for JSON export
    void setExplored(Cell c, bool v) noexcept;                     // DM paint
    void setExploredCells(const std::vector<Cell>& cells) noexcept; // JSON import (replaces mask)
    void revealAllFog() noexcept;                                  // DM "reveal all"
    void clearFog() noexcept;                                      // DM "reset fog"

    // Get/set light level at a cell (for debugging or manual map configuration).
    [[nodiscard]] VisibilityLevel getLightLevel(Cell c) const noexcept;
    // Light level at a cell as perceived BY a specific observer: a MagicalDark light effect tagged
    // see-through for this observer (Shadow Arts: Darkness) is treated as transparent for them, so
    // the underlying (non-magical-dark) light shows through. Identical to getLightLevel for everyone
    // else. observer_idx < 0 behaves exactly like getLightLevel.
    [[nodiscard]] VisibilityLevel getLightLevelFor(Cell c, int observer_idx) const noexcept;
    void setLightLevel(Cell c, VisibilityLevel lvl) noexcept;
    void resetLightLevels() noexcept;

    // ── NPC Spell Initialization ────────────────────────────────────────
    // Set is_npc=true and initialize uses_max/uses_remaining from spell groups.
    // groups: maps N (uses/day) -> list of spell names in that group.
    // Called once after setAgentSpells().
    void initNpcSpellGroups(int agent_idx,
                            const std::map<int, std::vector<std::string>>& groups) noexcept;

    // Mutable access to a placed agent for in-place modification.
    [[nodiscard]] PlacedAgent& placedAgentMut(int idx) noexcept;

    // ── Map items (weapons on the ground) ──────────────────────────────────
    [[nodiscard]] int placeItem(Cell cell, Weapon weapon, std::string sprite_path = "");
    void removeItem(int item_id) noexcept;
    // Pick up an item and assign it to an agent's weapon slot. If slot_idx >= 0, uses that slot
    // (replacing any weapon there). Otherwise uses the first empty slot. Returns true if successful.
    [[nodiscard]] bool pickUpItem(int item_id, int agent_idx, int slot_idx = -1) noexcept;
    [[nodiscard]] std::vector<MapItem> getItemsAtCell(Cell cell) const noexcept;
    [[nodiscard]] std::vector<MapItem> getAllItems()             const noexcept;
    void clearItems() noexcept;

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

    // Reconcile doors_[idx]'s cell TerrainType with its open state (see .cpp).
    void syncDoorTerrain(int idx) noexcept;

    // True iff an agent of `size` placed at `origin` lies entirely within the grid.
    [[nodiscard]] bool inBounds(Cell origin, int size) const noexcept;

    // Dijkstra pathfinding for path-based movement (Walk, Swim, Burrow, Jump).
    [[nodiscard]] CellSet pathfindMovement(Cell origin, int tokenSize,
                                           int speedFt, MovementType type,
                                           int mover_idx = -1) const;

    // Occupancy of the footprint a `size`-token would cover with top-left `origin`,
    // for a mover identified by `mover_idx` (its own footprint never counts). Other
    // living, in-play (not removed/on-deck) agents block movement: an enemy footprint
    // is impassable (can't pass through or stop), an ally footprint is passable but
    // can't be stopped on (D&D 5e moving-through-allies rule). Returns:
    //   0 = free, 1 = ally-occupied (pass-through only), 2 = enemy-occupied (impassable).
    // mover_idx < 0 (no actor) means agents are ignored entirely (returns 0).
    [[nodiscard]] int agentOccupancy(Cell origin, int size, int mover_idx) const noexcept;

    std::filesystem::path mapImagePath_;
    int cols_{0}, rows_{0}, cellPx_{0};
    // Global placement on the shared dungeon grid (all default 0 ⇒ standalone map
    // sits at the global origin on floor 0; unchanged behavior for single-map use).
    int origin_col_{0}, origin_row_{0}, z_level_{0};
    std::vector<int>   hLines_, vLines_;
    std::vector<Wall>  walls_;
    CellSet            disallowed_;
    std::vector<double>     terrainMult_;     // cols × rows static movement multipliers (default 1.0)
    std::vector<TerrainType> terrainType_;    // cols × rows terrain types (default Standard)
    std::vector<Door>        doors_;          // lockable doorway cells
    int                      nextDoorId_{0};  // monotonically increasing door id generator
    std::vector<VisibilityLevel>  baseVisibilityLevel_; // cols × rows base light levels (from JSON; default BrightLight)
    std::vector<VisibilityLevel>  lightLevel_;     // cols × rows computed light levels (base + effects; default BrightLight)
    std::vector<uint8_t>          explored_;       // cols × rows fog-of-war "ever seen" mask (0 = fogged, 1 = revealed); reset on grid analysis
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


    // Map items (weapons sitting on the ground)
    std::vector<MapItem> mapItems_;
    int nextItemId_{0};  // monotonically increasing item id generator
};

} // namespace rpg
