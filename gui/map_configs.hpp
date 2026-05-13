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

/**
 * Load and apply spell effect configuration from a JSON file to a BattleMap.
 *
 * Expected JSON format:
 * {
 *   "spell_effects": [
 *     {
 *       "type": "rect",
 *       "col": 5, "row": 1, "width": 3, "height": 10,
 *       "spell_name": "Wall of Fire",
 *       "remaining_turns": 8
 *     },
 *     {
 *       "type": "sphere",
 *       "col": 3, "row": 5, "radius": 2,
 *       "spell_name": "Fireball",
 *       "remaining_turns": 1
 *     }
 *   ]
 * }
 *
 * Spell definitions are loaded from spells.json in the same directory as the effects file.
 */
void applySpellEffectConfiguration(BattleMap& bm, const std::string& json_path) noexcept;

}  // namespace rpg
