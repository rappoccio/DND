#include "map_configs.hpp"
#include <fstream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace rpg {

void applyTerrainConfiguration(BattleMap& bm, const std::string& json_path) noexcept {
    try {
        // Read JSON file
        std::ifstream file(json_path);
        if (!file.is_open()) {
            throw std::runtime_error("Could not open terrain configuration file: " + json_path);
        }

        json config;
        file >> config;
        file.close();

        // Apply terrain features
        if (!config.contains("terrain_features")) {
            return;  // No terrain features to apply
        }

        for (const auto& feature : config["terrain_features"]) {
            std::string type = feature.value("type", "");
            double multiplier = feature.value("multiplier", 1.0);

            if (type == "rect") {
                // Rectangle terrain: {"type": "rect", "col": X, "row": Y, "width": W, "height": H, "multiplier": M}
                int col = feature.value("col", 0);
                int row = feature.value("row", 0);
                int width = feature.value("width", 1);
                int height = feature.value("height", 1);
                bm.setTerrainMultiplierRect(Cell{col, row}, width, height, multiplier);
            } else if (type == "column") {
                // Column terrain: {"type": "column", "col": X, "row_start": Y1, "row_end": Y2, "multiplier": M}
                int col = feature.value("col", 0);
                int row_start = feature.value("row_start", 0);
                int row_end = feature.value("row_end", 0);
                for (int row = row_start; row <= row_end; ++row) {
                    bm.setTerrainMultiplier(Cell{col, row}, multiplier);
                }
            } else if (type == "row") {
                // Row terrain: {"type": "row", "row": Y, "col_start": X1, "col_end": X2, "multiplier": M}
                int row = feature.value("row", 0);
                int col_start = feature.value("col_start", 0);
                int col_end = feature.value("col_end", 0);
                for (int col = col_start; col <= col_end; ++col) {
                    bm.setTerrainMultiplier(Cell{col, row}, multiplier);
                }
            } else if (type == "cell") {
                // Single cell terrain: {"type": "cell", "col": X, "row": Y, "multiplier": M}
                int col = feature.value("col", 0);
                int row = feature.value("row", 0);
                bm.setTerrainMultiplier(Cell{col, row}, multiplier);
            }
        }
    } catch (const std::exception& e) {
        // Silently fail - terrain configuration is optional
        // In a real application, you might log this error
    }
}

// Helper: parse Spell from JSON object
static Spell spellFromJson(const json& j) noexcept {
    Spell spell;

    spell.name = j.value("name", "Unnamed Spell");

    // Parse type
    std::string type_str = j.value("type", "Harm");
    if (type_str == "Heal") spell.type = Spell::Heal;
    else spell.type = Spell::Harm;

    // Parse geometry
    std::string geom_str = j.value("geometry", "Single");
    if (geom_str == "Line") spell.geometry = Spell::Line;
    else if (geom_str == "Cone") spell.geometry = Spell::Cone;
    else if (geom_str == "Sphere") spell.geometry = Spell::Sphere;
    else if (geom_str == "Square") spell.geometry = Spell::Square;
    else if (geom_str == "Rectangle") spell.geometry = Spell::Rectangle;
    else if (geom_str == "Multiple") spell.geometry = Spell::Multiple;
    else spell.geometry = Spell::Single;

    // Parse attack type
    std::string attack_str = j.value("attack_type", "AttackRoll");
    if (attack_str == "Save") spell.attack_type = Spell::Save;
    else if (attack_str == "Automatic") spell.attack_type = Spell::Automatic;
    else spell.attack_type = Spell::AttackRoll;

    // Parse save ability
    std::string save_str = j.value("save_ability", "SaveDex");
    if (save_str == "SaveStr") spell.save_ability = SaveStr;
    else if (save_str == "SaveDex") spell.save_ability = SaveDex;
    else if (save_str == "SaveCon") spell.save_ability = SaveCon;
    else if (save_str == "SaveInt") spell.save_ability = SaveInt;
    else if (save_str == "SaveWis") spell.save_ability = SaveWis;
    else if (save_str == "SaveCha") spell.save_ability = SaveCha;
    else spell.save_ability = SaveDex;

    spell.range = j.value("range", 30);
    spell.radius = j.value("radius", 10);
    spell.width = j.value("width", 5);
    spell.length = j.value("length", 30);
    spell.duration = j.value("duration", 1);
    spell.num_targets = j.value("num_targets", 1);
    spell.targets_per_upcast_level = j.value("targets_per_upcast_level", 0);
    spell.level = j.value("level", 0);
    spell.upcast_dice_bonus = j.value("upcast_dice_bonus", 0);
    spell.requires_concentration = j.value("requires_concentration", false);
    spell.requires_los = j.value("requires_los", false);
    spell.check_los_on_center = j.value("check_los_on_center", true);
    spell.selective_targeting = j.value("selective_targeting", false);
    spell.uses_max = j.value("uses_max", 0);
    spell.uses_remaining = j.value("uses_remaining", 0);
    spell.effects_on_begin_turn = j.value("effects_on_begin_turn", true);
    spell.effects_on_end_turn = j.value("effects_on_end_turn", false);

    // Parse terrain difficulty
    std::string terrain_str = j.value("terrain_difficulty", "Normal");
    if (terrain_str == "Halved") spell.terrain_difficulty = TerrainDifficulty::Halved;
    else if (terrain_str == "Quartered") spell.terrain_difficulty = TerrainDifficulty::Quartered;
    else if (terrain_str == "Slipping") spell.terrain_difficulty = TerrainDifficulty::Slipping;
    else spell.terrain_difficulty = TerrainDifficulty::Normal;

    spell.slip_save_dc = j.value("slip_save_dc", 10);
    spell.slip_distance_feet = j.value("slip_distance_feet", 5);
    spell.moves_with_caster = j.value("moves_with_caster", false);

    // Parse light level (-1 = no light effect)
    spell.light_level = j.value("light_level", -1);

    return spell;
}

void applySpellEffectConfiguration(BattleMap& bm, const std::string& json_path) noexcept {
    try {
        // Determine directory of the effects file
        std::string dir = json_path;
        size_t pos = dir.find_last_of("/\\");
        if (pos != std::string::npos) {
            dir = dir.substr(0, pos);
        } else {
            dir = ".";
        }

        // Load spell registry from spells.json in the same directory
        std::string spells_path = dir + "/spells.json";
        std::ifstream spells_file(spells_path);
        if (!spells_file.is_open()) {
            throw std::runtime_error("Could not open spell registry: " + spells_path);
        }

        json spells_data;
        spells_file >> spells_data;
        spells_file.close();

        // Build a map of spell name -> Spell
        std::map<std::string, Spell> spell_registry;
        if (spells_data.is_array()) {
            for (const auto& spell_json : spells_data) {
                try {
                    Spell spell = spellFromJson(spell_json);
                    spell_registry[spell.name] = spell;
                } catch (...) {
                    // Skip malformed spells
                }
            }
        }

        // Read effects configuration file
        std::ifstream file(json_path);
        if (!file.is_open()) {
            throw std::runtime_error("Could not open spell effect configuration file: " + json_path);
        }

        json config;
        file >> config;
        file.close();

        // Apply spell effects
        if (!config.contains("spell_effects")) {
            return;  // No spell effects to apply
        }

        int next_effect_id = 0;
        for (const auto& effect : config["spell_effects"]) {
            std::string spell_name = effect.value("spell_name", "");
            int remaining_turns = effect.value("remaining_turns", 1);
            std::string type = effect.value("type", "");

            // Look up spell in registry
            auto spell_it = spell_registry.find(spell_name);
            if (spell_it == spell_registry.end()) {
                continue;  // Skip unknown spells
            }

            Spell spell_copy = spell_it->second;
            std::vector<Cell> cells;

            // Generate cells based on type
            if (type == "rect") {
                int col = effect.value("col", 0);
                int row = effect.value("row", 0);
                int width = effect.value("width", 1);
                int height = effect.value("height", 1);
                for (int c = col; c < col + width; ++c) {
                    for (int r = row; r < row + height; ++r) {
                        cells.push_back(Cell{c, r});
                    }
                }
            } else if (type == "sphere") {
                int col = effect.value("col", 0);
                int row = effect.value("row", 0);
                int radius = effect.value("radius", 1);
                for (int c = col - radius; c <= col + radius; ++c) {
                    for (int r = row - radius; r <= row + radius; ++r) {
                        int dc = c - col;
                        int dr = r - row;
                        if (dc * dc + dr * dr <= radius * radius) {
                            cells.push_back(Cell{c, r});
                        }
                    }
                }
            } else if (type == "column") {
                int col = effect.value("col", 0);
                int row_start = effect.value("row_start", 0);
                int row_end = effect.value("row_end", 0);
                for (int row = row_start; row <= row_end; ++row) {
                    cells.push_back(Cell{col, row});
                }
            } else if (type == "row") {
                int row = effect.value("row", 0);
                int col_start = effect.value("col_start", 0);
                int col_end = effect.value("col_end", 0);
                for (int col = col_start; col <= col_end; ++col) {
                    cells.push_back(Cell{col, row});
                }
            } else if (type == "cell") {
                int col = effect.value("col", 0);
                int row = effect.value("row", 0);
                cells.push_back(Cell{col, row});
            }

            // Create ActiveSpellEffect
            if (!cells.empty()) {
                ActiveSpellEffect active_effect;
                active_effect.caster_idx = -1;  // Environment/preset effect
                active_effect.spell_idx = -1;   // No caster spell list
                active_effect.spell = spell_copy;
                active_effect.cells = cells;
                active_effect.turns_remaining = remaining_turns;
                active_effect.effect_id = next_effect_id++;

                [[maybe_unused]] int effect_id = bm.addSpellEffect(active_effect);
            }
        }
    } catch (const std::exception& e) {
        // Silently fail - spell effect configuration is optional
    }
}

}  // namespace rpg
