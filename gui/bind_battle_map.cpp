// ─────────────────────────────────────────────────────────────────────────────
//  bind_battle_map.cpp  –  pybind11 bindings for BattleMap
// ─────────────────────────────────────────────────────────────────────────────
//
//  Split out of rpg_bindings.cpp (COMBAT_REFACTOR_PLAN.md R1) — mechanical move
//  only, no binding behavior changed.
//
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/functional.h> // std::function ↔ Python callable (NPC render-attack hook)
#include <pybind11/operators.h>

#include "battle_map.hpp"
#include "combat.hpp"
#include "combat_internal.hpp"   // footprintDistance — shared with the combat_*.cpp TUs
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

// Helper: convert CellSet → Python list (pybind11 can't auto-convert custom hash sets)
static std::vector<Cell> cellSetToVec(const CellSet& s) {
    return {s.begin(), s.end()};
}

void bindBattleMap(py::module_& m) {
    // ── BattleMap ───────────────────────────────────────────────────────────
    py::class_<BattleMap>(m, "BattleMap")
        .def(py::init<std::string>(),   // accept plain str from Python
             py::arg("map_image_path"))

        // Grid analysis
        .def("analyze_grid",  &BattleMap::analyzeGrid,
             "Detect grid lines; call before detect_walls().")
        .def("set_uniform_grid", &BattleMap::setUniformGrid,
             py::arg("cell_px"), py::arg("anchor_x"), py::arg("anchor_y"),
             "Replace the detected grid with a uniform grid of square cells `cell_px`\n"
             "pixels on a side, phase-aligned to (anchor_x, anchor_y) in image pixels,\n"
             "tiled across the whole map. Clears walls and resizes terrain buffers.")
        .def("detect_walls",  &BattleMap::detectWalls,
             "Detect thick walls and compute disallowed cells via flood fill.")
        .def("clear_walls",   &BattleMap::clearWalls,
             "Discard all auto-detected walls/obstacles (turn off wall auto-detection).")

        // Grid geometry (used by Python renderer to draw overlays)
        .def_property_readonly("grid_cols",       &BattleMap::gridCols)
        .def_property_readonly("grid_rows",       &BattleMap::gridRows)
        .def_property_readonly("cell_pixel_size", &BattleMap::cellPixelSize)
        .def_property_readonly("h_line_positions",&BattleMap::hLinePositions)
        .def_property_readonly("v_line_positions",&BattleMap::vLinePositions)

        // Global placement on the shared dungeon grid (multi-map dungeons).
        // origin_(col,row) = global (X,Y) of this page's local (0,0); z_level = floor.
        .def_property("origin_col", &BattleMap::originCol, &BattleMap::setOriginCol)
        .def_property("origin_row", &BattleMap::originRow, &BattleMap::setOriginRow)
        .def_property("z_level",    &BattleMap::zLevel,    &BattleMap::setZLevel)
        .def("local_to_global", &BattleMap::localToGlobal, py::arg("local"),
             "Local (col,row) → global Cell (X,Y,z=z_level) on the shared dungeon grid.")
        .def("global_to_local", &BattleMap::globalToLocal,
             py::arg("x"), py::arg("y"), py::arg("z"),
             "Global (X,Y,Z) → local Cell on THIS page, or None if wrong floor / off-page.")

        // Wall / passability data
        .def_property_readonly("walls", [](const BattleMap& bm) -> std::vector<Wall> {
            return {bm.walls().begin(), bm.walls().end()};
        })
        .def_property_readonly("disallowed_cells", [](const BattleMap& bm){
            return cellSetToVec(bm.disallowedCells());
        })
        .def("is_blocked", &BattleMap::isBlocked,
             py::arg("origin"), py::arg("agent_size"), py::arg("movement_type") = MovementType::Walk)
        .def("agent_occupancy", &BattleMap::agentOccupancy,
             py::arg("origin"), py::arg("size"), py::arg("mover_idx"),
             "Agent-footprint passability of the size×size cell at `origin` for mover_idx:\n"
             "0 = free, 1 = ally footprint (pass-through), 2 = enemy footprint (impassable).\n"
             "Corpses (conditions.dead) free their square; unconscious/downed bodies still block.")
        .def("set_terrain_type", &BattleMap::setTerrainType,
             py::arg("cell"), py::arg("terrain_type"),
             "Set a cell's TerrainType (Standard/Water/Wall/Chasm).")
        .def("get_terrain_type", &BattleMap::getTerrainType,
             py::arg("cell"),
             "Get a cell's TerrainType.")

        // ── Doors ────────────────────────────────────────────────────────────
        .def_property_readonly("doors", [](const BattleMap& bm){
            return std::vector<Door>(bm.doors().begin(), bm.doors().end());
        }, "List of all doors on the map.")
        .def("door_at", &BattleMap::doorAt, py::arg("cell"),
             "Index into doors for the door occupying a cell (any of its cells), or -1 if none.")
        .def("add_door",
             py::overload_cast<const std::vector<Cell>&, bool, bool, int, bool, int>(&BattleMap::addDoor),
             py::arg("cells"), py::arg("open") = false, py::arg("locked") = false,
             py::arg("lock_dc") = 15, py::arg("arcane_lock") = false, py::arg("break_dc") = 15,
             "Create a door spanning a list of cells (a wide door is one object); returns its\n"
             "unique id and syncs every cell's terrain. Overlapping doors are replaced first.")
        .def("add_door",
             py::overload_cast<Cell, bool, bool, int, bool, int>(&BattleMap::addDoor),
             py::arg("cell"), py::arg("open") = false, py::arg("locked") = false,
             py::arg("lock_dc") = 15, py::arg("arcane_lock") = false, py::arg("break_dc") = 15,
             "Create a single-cell door; returns its unique id and syncs the cell's terrain.")
        .def("remove_door", &BattleMap::removeDoor, py::arg("id"),
             "Remove a door by id; restores all of its cells to Standard terrain.")
        .def("open_door", &BattleMap::openDoor, py::arg("id"),
             "Open a door; returns false if it is locked or arcane-locked.")
        .def("close_door", &BattleMap::closeDoor, py::arg("id"),
             "Close a door (cell becomes a Wall).")
        .def("lock_door", &BattleMap::lockDoor, py::arg("id"), py::arg("dc"),
             "Lock a door and set its pick DC.")
        .def("unlock_door", &BattleMap::unlockDoor, py::arg("id"),
             "Unlock a door (does not open it).")
        .def("knock_door", &BattleMap::knockDoor,
             py::arg("id"), py::arg("arcane_suppress_turns") = 100,
             "Knock spell: removes a mundane lock, suppresses an Arcane Lock for\n"
             "arcane_suppress_turns, then opens the door. Returns true if opened.")
        .def("break_door", &BattleMap::breakDoor, py::arg("id"),
             "Force a door off its frame: unlock it, mark it broken, and open it permanently\n"
             "(works even on a locked/arcane-locked door). Returns true if the door now broke open.")

        // Agent management (core spatial operations only; stat/equipment management moved to CombatEngine)
        .def("clear_agents",       &BattleMap::clearAgents)
        .def("spawn_agent",        &BattleMap::spawnAgent,
             py::arg("config"),
             "Spawn one agent at runtime (e.g. a summon) WITHOUT clearing existing agents,\n"
             "preserving all runtime state. Returns the new agent index, or -1 if blocked.\n"
             "Set stats/weapons/summoner_idx on the returned index afterward.")
        .def("move_agent",         &BattleMap::moveAgent,
             py::arg("idx"), py::arg("new_origin"),
             py::arg("movement_type") = MovementType::Walk,
             "Move placed agent[idx] to new_origin using the given movement type.\n"
             "Returns False if the agent lacks sufficient movement budget.")
        .def("jump_agent",         &BattleMap::jumpAgent,
             py::arg("idx"), py::arg("new_origin"), py::arg("is_running"),
             "Jump placed agent[idx] to new_origin (ignores walls, deducts from walk budget).\n"
             "is_running: True for running jump (up to STR), False for standing jump (up to STR/2).\n"
             "Returns False if out of range or insufficient movement budget.")
        .def("force_move_agent",   &BattleMap::forceMoveAgent,
             py::arg("idx"), py::arg("push_from"), py::arg("push_ft"), py::arg("pull") = false,
             py::arg("from_size") = 1,
             "Force move agent[idx] relative to push_from by up to push_ft. By default pushes AWAY;\n"
             "with pull=True, pulls TOWARD push_from instead.\n"
             "Does not consume movement budget. Stops at walls. A pull also stops adjacent to the\n"
             "puller's footprint (from_size = puller's size in cells) — it never moves onto or past it.\n"
             "Returns number of cells actually moved.")
        .def("set_agent_position", &BattleMap::setAgentPosition,
             py::arg("idx"), py::arg("new_origin"),
             "Directly set agent[idx] position (used for grapple dragging).\n"
             "Returns false if idx invalid or destination out of bounds.")
        .def("remove_agent",       &BattleMap::removeAgent,
             py::arg("idx"),
             "Remove placed agent[idx] from the map.")

        // ── Summoning ─────────────────────────────────────────────────────
        .def("get_agent_summoner_idx", &BattleMap::getAgentSummonerIdx,
             py::arg("idx"),
             "Index of the agent that summoned agent[idx]; -1 if not a summon.")
        .def("set_agent_summoner_idx", &BattleMap::setAgentSummonerIdx,
             py::arg("idx"), py::arg("summoner_idx"),
             "Tag agent[idx] as a summon controlled by summoner_idx (-1 to clear).")
        .def("get_agent_faction", &BattleMap::getAgentFaction,
             py::arg("idx"),
             "Team/faction id of agent[idx] (0 = neutral/unassigned).")
        .def("set_agent_faction", &BattleMap::setAgentFaction,
             py::arg("idx"), py::arg("faction"),
             "Assign agent[idx] to a team/faction (0 = neutral; 1+ = red/blue/...).")
        .def("set_agent_name", &BattleMap::setAgentName,
             py::arg("idx"), py::arg("name"),
             "Rename placed agent[idx] (also patches its AgentConfig so it survives "
             "save/load and config re-apply).")
        .def("set_agent_sprite", &BattleMap::setAgentSprite,
             py::arg("idx"), py::arg("sprite_path"),
             "Set the sprite image path for placed agent[idx] (also patches its "
             "AgentConfig so it survives save/load and config re-apply).")
        .def("get_agent_summon_spell", &BattleMap::getAgentSummonSpell,
             py::arg("idx"),
             "Name of the spell that summoned agent[idx] (empty if none).")
        .def("set_agent_summon_spell", &BattleMap::setAgentSummonSpell,
             py::arg("idx"), py::arg("spell_name"),
             "Record the spell name that summoned agent[idx].")
        .def("is_agent_removed_from_play", &BattleMap::isAgentRemovedFromPlay,
             py::arg("idx"),
             "True if agent[idx] is tombstoned (e.g. dismissed summon): skip in turns + rendering.")
        .def("set_agent_removed_from_play", &BattleMap::setAgentRemovedFromPlay,
             py::arg("idx"), py::arg("removed"),
             "Tombstone/un-tombstone agent[idx]. Kept in placedAgents_ so indices stay valid.")
        .def("is_agent_on_deck", &BattleMap::isAgentOnDeck,
             py::arg("idx"),
             "True if agent[idx] is an on-deck reserve: rendered but excluded from\n"
             "initiative until the DM deploys it.")
        .def("set_agent_on_deck", &BattleMap::setAgentOnDeck,
             py::arg("idx"), py::arg("on_deck"),
             "Flag/unflag agent[idx] as an on-deck reserve (phased-battle reinforcement).")
        .def("is_agent_npc_automated", &BattleMap::isAgentNpcAutomated,
             py::arg("idx"),
             "True if agent[idx] is driven by an automated NPC decision algorithm.")
        .def("set_agent_npc_automated", &BattleMap::setAgentNpcAutomated,
             py::arg("idx"), py::arg("automated"),
             "Enable/disable automated decision-making for agent[idx].")
        .def("get_agent_npc_automation_difficulty", &BattleMap::getAgentNpcAutomationDifficulty,
             py::arg("idx"),
             "Difficulty level (0+) tuning how aggressively agent[idx]'s automation plays.")
        .def("set_agent_npc_automation_difficulty", &BattleMap::setAgentNpcAutomationDifficulty,
             py::arg("idx"), py::arg("level"),
             "Set the automation difficulty level for agent[idx].")
        .def("get_agent_npc_automation_strategy", &BattleMap::getAgentNpcAutomationStrategy,
             py::arg("idx"),
             "Which NpcAutomationStrategy agent[idx] uses when automated.")
        .def("set_agent_npc_automation_strategy", &BattleMap::setAgentNpcAutomationStrategy,
             py::arg("idx"), py::arg("strategy"),
             "Set the NpcAutomationStrategy for agent[idx].")
        .def("apply_dash",         &BattleMap::applyDash,
             py::arg("idx"),
             "Set dashing condition and add base speeds to remaining movement for agent[idx].")

        // Line-of-sight
        .def("has_line_of_sight",
             &BattleMap::hasLineOfSight,
             py::arg("from_origin"), py::arg("from_size"),
             py::arg("to_origin"),   py::arg("to_size"),
             "Bresenham ray from centre of 'from' agent to centre of 'to' agent.\n"
             "Returns False if any intermediate cell is a wall/obstacle.")

        .def("filter_spell_cells",
             &BattleMap::filterSpellCells,
             py::arg("cells"), py::arg("caster_origin"), py::arg("caster_size"),
             py::arg("spell"), py::arg("center_cell"),
             "Filter spell cells by range and Total Cover.\n"
             "Drops cells out of the caster's range, and every cell a wall hides from the\n"
             "area's point of origin (see prune_blocked_cells) — no area of effect reaches\n"
             "through Total Cover. spell.requires_los additionally demands a clear path from\n"
             "the caster to center_cell; without one, nothing is affected at all.")

        .def("prune_blocked_cells",
             [](const BattleMap& bm, const std::vector<Cell>& cells, const Spell& spell,
                Cell caster_origin, int caster_size, Cell center_cell) {
                 return bm.pruneBlockedCells(
                     BattleMap::areaOrigin(spell, caster_origin, caster_size, center_cell), cells);
             },
             py::arg("cells"), py::arg("spell"),
             py::arg("caster_origin"), py::arg("caster_size"), py::arg("center_cell"),
             "Drop every cell a wall (or closed door) hides from the area's point of origin —\n"
             "an area of effect is blocked by Total Cover and never bends around a corner.\n"
             "The origin is the caster's footprint for a Cone/Line/Emanation, else center_cell.\n"
             "The engine prunes every area this way; call it on a hand-built cell list (e.g. a\n"
             "wall_cells preview) so the GUI shows exactly the cells the spell will affect.")

        .def("aoe_cells", &BattleMap::aoeCells,
             py::arg("center"), py::arg("spell"), py::arg("caster_origin"),
             py::arg("endpoint") = Cell{-1, -1}, py::arg("caster_size") = 1,
             "Cells covered by a spell's AoE geometry. Cone/Line emanate from the cell on\n"
             "the caster's caster_size×caster_size footprint nearest the aim point and skip\n"
             "the caster's own space. For Rectangle walls, `endpoint` aims the wall from `center`.")

        .def("wall_cells", &BattleMap::wallCells,
             py::arg("anchor"), py::arg("endpoint"),
             py::arg("width_ft"), py::arg("max_len_ft"),
             "Cells of an oriented wall: thick segment from anchor toward endpoint,\n"
             "clamped to max_len_ft, thickness width_ft centered on the line.\n"
             "If anchor == endpoint, returns a centered box (degenerate fallback).")

        // Attack target cells (melee reach or ranged range, with LoS filter)
        .def("attack_target_cells",
             [](const BattleMap& bm, Cell origin, int agentSize, int rangeFt) {
                 return bm.attackTargetCells(origin, agentSize, rangeFt);
             },
             py::arg("origin"), py::arg("agent_size"), py::arg("range_ft"),
             "Return cells within range_ft feet (Chebyshev from footprint edge)\n"
             "that have line-of-sight from the agent.\n"
             "Use for melee (range_ft = 5/10/15) and ranged (call twice for\n"
             "normal/long zones and subtract).")

        // Movement reach
        .def("reachable_cells",
             [](const BattleMap& bm, Cell origin, int agentSize,
                int speedFt, MovementType type, int moverIdx) {
                 return cellSetToVec(bm.reachableCells(origin, agentSize,
                                                       speedFt, type, moverIdx));
             },
             py::arg("origin"), py::arg("agent_size"),
             py::arg("speed_ft"), py::arg("movement_type"),
             py::arg("mover_idx") = -1,
             "Return a list of Cell origins reachable from origin.\n"
             "Walk: Dijkstra BFS through passable cells.\n"
             "Fly:  Chebyshev radius ignoring terrain.\n"
             "mover_idx>=0 lets faction-spared difficult terrain (Spirit Guardians)\n"
             "not slow the moving agent or its allies.")

        .def_property_readonly("placed_agents", [](const BattleMap& bm){
            auto sp = bm.placedAgents();
            return std::vector<PlacedAgent>(sp.begin(), sp.end());
        })

        // Terrain multipliers (for difficult terrain, spells, etc.)
        .def("get_terrain_multiplier", &BattleMap::getTerrainMultiplier,
             py::arg("cell"), py::arg("movement_type") = MovementType::Walk,
             "Get the movement cost multiplier for a cell (default 1.0).")
        .def("set_terrain_multiplier", &BattleMap::setTerrainMultiplier,
             py::arg("cell"), py::arg("multiplier"),
             "Set the movement cost multiplier for a single cell.")
        .def("set_terrain_multiplier_rect", &BattleMap::setTerrainMultiplierRect,
             py::arg("top_left"), py::arg("width"), py::arg("height"), py::arg("multiplier"),
             "Set the movement cost multiplier for a rectangular region.")
        .def("reset_terrain_multipliers", &BattleMap::resetTerrainMultipliers,
             "Reset all terrain multipliers to 1.0 (default).")

        // Terrain types (Standard, Water, Wall, Chasm)
        .def("get_terrain_type", &BattleMap::getTerrainType,
             py::arg("cell"),
             "Get the terrain type for a cell (Standard, Water, Wall, or Chasm).")
        .def("set_terrain_type", &BattleMap::setTerrainType,
             py::arg("cell"), py::arg("terrain_type"),
             "Set the terrain type for a cell.")

        // Light levels (BrightLight, DimLight, Darkness, MagicalDarkness)
        .def("get_light_level", &BattleMap::getLightLevel,
             py::arg("cell"),
             "Get the light level for a cell (BrightLight, DimLight, Darkness, or MagicalDarkness).")
        .def("get_light_level_for", &BattleMap::getLightLevelFor,
             py::arg("cell"), py::arg("observer_idx"),
             "Light level at a cell as perceived by a specific observer: a MagicalDark light effect\n"
             "tagged see-through for this observer (Shadow Arts: Darkness) reads as transparent for them.")
        .def("set_light_level", &BattleMap::setLightLevel,
             py::arg("cell"), py::arg("light_level"),
             "Set the light level for a cell.")
        .def("reset_light_levels", &BattleMap::resetLightLevels,
             "Reset all light levels to BrightLight (default).")

        // Visibility & Darkvision
        .def("can_see", &BattleMap::canSee,
             py::arg("obs_origin"), py::arg("obs_size"),
             py::arg("darkvision_ft"), py::arg("truesight_ft"), py::arg("devilssight_ft"),
             py::arg("tgt_origin"), py::arg("tgt_size"),
             "Check if observer can see target (D&D 5e vision rules).\n"
             "Returns false = observer is blinded and cannot target.\n"
             "Implements: Truesight (all conditions), Devil's Sight (darkness/magical darkness),\n"
             "Darkvision (disadvantage in pure darkness), Normal vision (blinded in darkness).")
        .def("perception_disadvantage", &BattleMap::perceptionDisadvantage,
             py::arg("obs_origin"), py::arg("obs_size"),
             py::arg("darkvision_ft"), py::arg("truesight_ft"), py::arg("devilssight_ft"),
             py::arg("tgt_origin"), py::arg("tgt_size"),
             "Check if observer has disadvantage on perception vs target.\n"
             "Returns true for: DimLight (normal/devil's sight), Darkness (darkvision only).")

        // Fog of war (persistent explored mask, PC-party scoped) — see FOG_OF_WAR_PLAN.md.
        .def("reveal_fog_for_faction", &BattleMap::revealFogForFaction,
             py::arg("faction"),
             "Monotonically OR every cell currently seen by a LIVING agent on `faction`\n"
             "into the persistent explored mask (honors LOS/doors/lighting/senses via can_see).\n"
             "Never clears a bit. Cheap to call redundantly; drive it from a dirty flag.")
        .def("is_explored", &BattleMap::isExplored,
             py::arg("cell"),
             "True if the given cell has ever been seen by the PC party (revealed).\n"
             "Out-of-bounds cells return false. Drives the GUI fog overlay / enemy gate.")
        .def("explored_cells", &BattleMap::exploredCells,
             "List of all currently-revealed cells (for terrain-JSON serialization).")
        .def("set_explored", &BattleMap::setExplored,
             py::arg("cell"), py::arg("value"),
             "DM paint: set a single cell's explored bit (True = revealed, False = fogged).")
        .def("set_explored_cells", &BattleMap::setExploredCells,
             py::arg("cells"),
             "Replace the explored mask with exactly these cells revealed (JSON import).\n"
             "Clears every other bit first, so an empty list fully re-fogs the map.")
        .def("reveal_all_fog", &BattleMap::revealAllFog,
             "DM 'reveal all': mark every cell explored.")
        .def("clear_fog", &BattleMap::clearFog,
             "DM 'reset fog': mark every cell unexplored (fully fogged).")

        // Temporary terrain effects (spells, items, etc. with duration)
        .def("place_terrain_effect", &BattleMap::placeTerrainEffect,
             py::arg("name"), py::arg("cells"), py::arg("difficulty"),
             py::arg("turns_remaining"), py::arg("source_agent_idx"),
             py::arg("slip_save_dc") = 10, py::arg("slip_distance_feet") = 5,
             py::arg("spell_idx") = -1, py::arg("cast_level") = 0,
             py::arg("requires_concentration") = false,
             py::arg("anchor_agent_idx") = -1, py::arg("anchor_radius_ft") = 0,
             py::arg("spares_source_allies") = false,
             py::arg("ward_creature_mask") = 0, py::arg("ward_traps") = false,
             py::arg("ward_all_living") = false, py::arg("sets_wall") = false,
             "Place a temporary terrain effect covering the given cells.\n"
             "anchor_agent_idx>=0 makes it follow that agent (moving emanation);\n"
             "spares_source_allies excludes the source + its allies (selective_targeting).\n"
             "ward_creature_mask != 0 makes it a Magic Circle / Hallow movement ward (an OR of\n"
             "rpg.CreatureType bits); ward_traps=False keeps those types out, True traps them in.\n"
             "ward_all_living=True is an Antilife Shell ward: blocks any non-Undead mover (typeless\n"
             "creatures too), independent of ward_creature_mask.\n"
             "sets_wall=True is a Wall of Stone: each cell becomes solid Wall terrain (impassable +\n"
             "LOS-blocking) for the duration, restored to its original type on removal.\n"
             "Returns unique effect id (for later removal/metadata).")
        .def("set_terrain_effect_cells", &BattleMap::setTerrainEffectCells,
             py::arg("effect_id"), py::arg("cells"),
             "Re-point an anchored terrain effect's footprint (moving emanation).")
        .def("tick_terrain_effects", &BattleMap::tickTerrainEffects,
             py::arg("source_agent_idx"),
             "Decrement turns_remaining for effects from this source.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("tick_dm_terrain_effects", &BattleMap::tickDMTerrainEffects,
             "Decrement turns_remaining for DM-placed effects (source_agent_idx == -1).\n"
             "Called at round boundary. Returns list of removed effect ids.")
        .def("remove_terrain_effects_by_source", &BattleMap::removeTerrainEffectsBySource,
             py::arg("source_agent_idx"),
             "Remove all effects sourced from the given agent (concentration drop, death, etc.).\n"
             "Returns list of removed effect ids.")
        .def("remove_terrain_effect", &BattleMap::removeTerrainEffect,
             py::arg("effect_id"),
             "Remove a specific effect by id (manual DM removal).")
        .def("clear_terrain_effects", &BattleMap::clearTerrainEffects,
             "Clear all terrain effects (end of combat).")
        .def_property_readonly("active_terrain_effects", &BattleMap::activeTerrainEffects,
             "Get a copy of all active terrain effects (for rendering).")
        .def("has_active_terrain_effects", &BattleMap::hasActiveTerrainEffects,
             "Check if there are any active terrain effects.")

        // Persistent spell effects (AoE from spells)
        .def_property_readonly("active_spell_effects", &BattleMap::activeSpellEffects,
             "Get all active spell effects from spells cast during combat.")
        .def("add_spell_effect", &BattleMap::addSpellEffect,
             py::arg("effect"),
             "Add a spell effect to the map. Returns effect_id.")
        .def("remove_spell_effect", &BattleMap::removeSpellEffect,
             py::arg("effect_id"),
             "Remove a spell effect by id.")
        .def("clear_spell_effects", &BattleMap::clearSpellEffects,
             "Remove all active spell effects (e.g. on End Combat).")

        // Dynamic light effects (spells, DM-placed lights, etc. with duration)
        .def("apply_base_lighting", &BattleMap::applyBaseLighting,
             py::arg("default_light"), py::arg("sources"),
             "Apply base lighting from map JSON. sources: list[(pixel_x, pixel_y, bright_radius_ft, dim_radius_ft)]")
        .def("update_lighting", &BattleMap::updateLighting,
             "Recompute lightLevel_ from baseLightLevel_ + activeLightEffects_.")
        .def("place_light_effect", &BattleMap::placeLightEffect,
             py::arg("name"), py::arg("cells"), py::arg("light_level"),
             py::arg("turns_remaining"), py::arg("source_agent_idx"),
             py::arg("see_through_agent_idx") = -1,
             py::arg("anchor_agent_idx") = -1,
             py::arg("anchor_radius_ft") = 0,
             "Place a dynamic light effect covering the given cells.\n"
             "see_through_agent_idx: an agent who sees through this MagicalDark (Shadow Arts: Darkness).\n"
             "anchor_agent_idx>=0 makes the light follow that agent (moving Sphere / Emanation),\n"
             "re-centered by anchor_radius_ft on every move / turn start.\n"
             "Returns unique effect id (for later removal).")
        .def("set_light_effect_cells", &BattleMap::setLightEffectCells,
             py::arg("effect_id"), py::arg("cells"),
             "Re-point an anchored light effect's footprint (moving emanation follows the caster).")
        .def("tick_light_effects", &BattleMap::tickLightEffects,
             py::arg("source_agent_idx"),
             "Decrement turns_remaining for light effects from this source.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("tick_dm_light_effects", &BattleMap::tickDmLightEffects,
             "Decrement turns_remaining for DM-placed light effects (source_agent_idx == -1).\n"
             "Returns list of removed effect ids.")
        .def("remove_light_effects_by_source", &BattleMap::removeLightEffectsBySource,
             py::arg("source_agent_idx"),
             "Remove all light effects sourced from the given agent.\n"
             "Returns list of removed effect ids.")
        .def("remove_light_effect", &BattleMap::removeLightEffect,
             py::arg("effect_id"),
             "Remove a specific light effect by id.")
        .def("clear_light_effects", &BattleMap::clearLightEffects,
             "Clear all dynamic light effects.")
        .def_property_readonly("active_light_effects", &BattleMap::activeLightEffects,
             "Get a copy of all active light effects.")
        .def("has_active_light_effects", &BattleMap::hasActiveLightEffects,
             "Check if there are any active light effects.")


        // Map items (weapons on the ground)
        .def("place_item", &BattleMap::placeItem,
             py::arg("cell"), py::arg("weapon"), py::arg("sprite_path") = "",
             "Place a weapon item at a cell. Returns a unique item id.")
        .def("remove_item", &BattleMap::removeItem,
             py::arg("item_id"),
             "Remove the item with the given id from the map.")
        .def("pick_up_item", &BattleMap::pickUpItem,
             py::arg("item_id"), py::arg("agent_idx"), py::arg("slot_idx") = -1,
             "Pick up an item and assign it to an agent's weapon slot. If slot_idx < 0, uses first empty slot. Returns true if successful.")
        .def("get_items_at_cell", &BattleMap::getItemsAtCell,
             py::arg("cell"),
             "Return list of MapItem at the given cell.")
        .def("get_all_items", &BattleMap::getAllItems,
             "Return list of all MapItem on the map.")
        .def("clear_items", &BattleMap::clearItems,
             "Remove all items from the map.")

        // Expose params so Python can tune detection
        .def_readwrite("params", &BattleMap::params);

    // ── Diagnostic verbosity ──────────────────────────────────────────────
    m.def("set_battlemap_verbose", &setBattleMapVerbose, py::arg("on"),
          "Enable/disable the '[BattleMap] …' stdout diagnostics printed during grid/wall\n"
          "analysis and agent placement. An explicit call wins over the RPG_QUIET environment\n"
          "variable. Call set_battlemap_verbose(False) for quiet headless/test runs.");
    m.def("get_battlemap_verbose", &battleMapVerbose,
          "Whether '[BattleMap] …' stdout diagnostics are currently enabled.");

    // ── Map Configuration Functions ───────────────────────────────────────
    m.def("apply_terrain_configuration", &applyTerrainConfiguration,
         py::arg("bm"), py::arg("json_path"),
         "Load and apply terrain configuration from a JSON file to the BattleMap.\n"
         "JSON format: {\"terrain_features\": [{\"type\": \"rect|column|row|cell\", ...}]}");

    m.def("apply_spell_effect_configuration", &applySpellEffectConfiguration,
         py::arg("bm"), py::arg("json_path"),
         "Load and apply spell effect configuration from a JSON file to the BattleMap.\n"
         "Loads spells from spells.json in the same directory and creates ActiveSpellEffect instances.\n"
         "JSON format: {\"spell_effects\": [{\"type\": \"rect|sphere|column|row|cell\", \"spell_name\": \"...\", \"remaining_turns\": N, ...}]}");
}
