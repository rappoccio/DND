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

}  // namespace rpg
