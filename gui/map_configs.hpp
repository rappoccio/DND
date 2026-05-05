#pragma once
#include <string>
#include "battle_map.hpp"

namespace rpg {

/**
 * Load and apply terrain configuration from a JSON file to a BattleMap.
 *
 * Expected JSON format:
 * {
 *   "terrain_features": [
 *     {
 *       "type": "rect",
 *       "col": 5, "row": 1, "width": 3, "height": 10,
 *       "multiplier": 0.5
 *     },
 *     {
 *       "type": "column",
 *       "col": 1, "row_start": 1, "row_end": 10,
 *       "multiplier": 0.0
 *     }
 *   ]
 * }
 */
void applyTerrainConfiguration(BattleMap& bm, const std::string& json_path) noexcept;

}  // namespace rpg
