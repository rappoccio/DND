#include <gtest/gtest.h>
#include "battle_map.hpp"
#include "map_configs.hpp"
#include "combat.hpp"
#include <vector>
#include <fstream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

using namespace rpg;

class BattleMapTest : public ::testing::Test {
protected:
    // Paths for Docker container with volume mounts
    std::string test_map_path = "/home/user/Documents/Claude/Projects/DND/maps/TestGrid12x12.png";
    std::string terrain_config_path = "/home/user/Documents/Claude/Projects/DND/maps/TestGrid12x12_terrain.json";
    BattleMap* bm = nullptr;

    void SetUp() override {
        bm = new BattleMap(test_map_path);
    }

    void TearDown() override {
        delete bm;
    }
};

// Test 1: Load map and add terrain features
TEST_F(BattleMapTest, LoadMapAndAddTerrain) {
    // Analyze grid and detect walls
    ASSERT_NO_THROW(bm->analyzeGrid());
    ASSERT_NO_THROW(bm->detectWalls());

    // Grid should be 11x11 (detected from image grid lines)
    int cols = bm->gridCols();
    int rows = bm->gridRows();
    EXPECT_EQ(cols, 11);
    EXPECT_EQ(rows, 11);
    EXPECT_EQ(bm->cellPixelSize(), 100);

    // Load and apply terrain configuration from JSON
    ASSERT_NO_THROW(applyTerrainConfiguration(*bm, terrain_config_path));

    // Verify walls/chasms are impassable
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{1, 5}), 0.0f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{3, 5}), 0.0f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{9, 5}), 0.0f);

    // Verify difficult terrain is 0.5x speed
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{5, 5}), 0.5f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{6, 5}), 0.5f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{7, 5}), 0.5f);

    // Verify empty cells are passable
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{0, 0}), 1.0f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{2, 5}), 1.0f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{4, 5}), 1.0f);
    EXPECT_EQ(bm->getTerrainMultiplier(Cell{8, 5}), 1.0f);
}

// ─────────────────────────────────────────────────────────────────────────────
// Test 2: Full combat scenario with agent creation, movement, attacks, and spells
// ─────────────────────────────────────────────────────────────────────────────

class CombatScenarioTest : public ::testing::Test {
protected:
    const std::string map_path     = "/home/user/Documents/Claude/Projects/DND/maps/TestGrid12x12.png";
    const std::string terrain_path = "/home/user/Documents/Claude/Projects/DND/maps/TestGrid12x12_terrain.json";
    const std::string stats_path   = "/home/user/Documents/Claude/Projects/DND/sprites/DND2024_MonsterStats.json";

    BattleMap*    bm     = nullptr;
    CombatEngine* engine = nullptr;
    const int deva_idx = 0;
    const int hag_idx  = 1;

    void SetUp() override {
        bm = new BattleMap(map_path);
        bm->analyzeGrid();
        bm->detectWalls();
        // Don't load terrain config — first test verifies that works.
        // This test focuses on combat mechanics on a clear grid.
        engine = new CombatEngine(42);  // fixed seed for deterministic rolls
    }

    void TearDown() override {
        delete engine;
        delete bm;
    }
};

TEST_F(CombatScenarioTest, FullCombatScenario) {
    // Phase A: Parse JSON and extract monster stats
    json data;
    {
        std::ifstream f(stats_path);
        ASSERT_TRUE(f.is_open());
        f >> data;
    }

    // Build Deva stats from JSON using the new constructor
    Agent::Stats deva_stats(data["Deva"]);
    deva_stats.spellcasting_ability = 5;  // CHA
    deva_stats.can_cast_spell = true;
    deva_stats.num_attacks = 1;

    // Build Green Hag stats from JSON using the new constructor
    Agent::Stats hag_stats(data["Green Hag"]);
    hag_stats.spellcasting_ability = 4;  // WIS
    hag_stats.can_cast_spell = true;
    hag_stats.num_attacks = 1;

    // Phase B: Place agents via AgentConfig
    AgentConfig deva_cfg;
    deva_cfg.name = "Deva";
    deva_cfg.spritePath = "deva.png";
    deva_cfg.size = 1;
    deva_cfg.startCol = 10;
    deva_cfg.startRow = 6;
    bm->addAgentConfig(deva_cfg);

    AgentConfig hag_cfg;
    hag_cfg.name = "Green Hag";
    hag_cfg.spritePath = "hag.png";
    hag_cfg.size = 1;
    hag_cfg.startCol = 0;
    hag_cfg.startRow = 6;
    bm->addAgentConfig(hag_cfg);

    bm->applyAgentConfigs();
    bm->setAgentStats(deva_idx, deva_stats);
    bm->setAgentStats(hag_idx,  hag_stats);

    // Phase C: Add weapons and spells
    Weapon longsword;
    longsword.name = "Longsword";
    longsword.type = WeaponType::Melee;
    longsword.reach_ft = 5;
    longsword.proficient = true;
    longsword.num_dice = 1;
    longsword.die_size = 8;
    longsword.physicalDamages = {PhysicalDamage_t::Slashing};
    bm->addWeaponToAgent(deva_idx, longsword);

    Weapon longbow;
    longbow.name = "Longbow";
    longbow.type = WeaponType::Ranged;
    longbow.normal_range_ft = 150;
    longbow.long_range_ft = 600;
    longbow.proficient = true;
    longbow.num_dice = 1;
    longbow.die_size = 8;
    longbow.physicalDamages = {PhysicalDamage_t::Piercing};
    bm->addWeaponToAgent(deva_idx, longbow);

    Spell ice_storm;
    ice_storm.name = "Ice Storm";
    ice_storm.type = Spell::Harm;
    ice_storm.geometry = Spell::Sphere;
    ice_storm.attack_type = Spell::Save;
    ice_storm.save_ability = Spell::SaveDex;
    ice_storm.range = 300;
    ice_storm.radius = 20;
    ice_storm.requires_concentration = true;
    ice_storm.terrain_difficulty = TerrainDifficulty::Halved;
    ice_storm.magic_damage_rolls = {{MagicDamage_t::Cold, 2, 8}};
    ice_storm.physical_damage_rolls = {{PhysicalDamage_t::Bludgeoning, 4, 6}};
    bm->addSpellToAgent(hag_idx, ice_storm);

    // Step 3: Verify fly speeds
    EXPECT_GT(bm->getAgentStats(deva_idx).speed_fly, 0);
    EXPECT_EQ(bm->getAgentStats(hag_idx).speed_fly,  0);

    // Step 4: Verify weapons
    EXPECT_EQ(bm->placedAgents()[deva_idx].weapons.size(), 2u);
    EXPECT_EQ(bm->placedAgents()[hag_idx].weapons.size(),  0u);
    EXPECT_EQ(bm->placedAgents()[deva_idx].weapons[0].name, "Longsword");
    EXPECT_EQ(bm->placedAgents()[deva_idx].weapons[1].name, "Longbow");

    // Step 5: Verify spells
    EXPECT_EQ(bm->placedAgents()[hag_idx].spells.size(), 1u);
    EXPECT_EQ(bm->placedAgents()[hag_idx].spells[0].name, "Ice Storm");

    // Turn 1, Step 6a: Green Hag dashes to (2,4)
    engine->beginTurn(hag_idx, *bm);
    bm->applyDash(hag_idx);
    EXPECT_TRUE(bm->getAgentConditions(hag_idx).dashing);
    EXPECT_TRUE(bm->moveAgent(hag_idx, Cell{2, 4}));
    EXPECT_EQ(bm->placedAgents()[hag_idx].origin.col, 2);
    EXPECT_EQ(bm->placedAgents()[hag_idx].origin.row, 4);

    // Turn 1, Step 6b: Deva begins their turn (movement skipped, remains at start)
    // The Deva will cast spell or attack from (10,6) position instead
    engine->beginTurn(deva_idx, *bm);

    // Turn 2, Step 7a: Deva shoots Longbow at Green Hag
    engine->beginTurn(deva_idx, *bm);
    int hag_hp_before = bm->getAgentStats(hag_idx).hp_cur;

    Attack bow_attack;
    bow_attack.attacker_idx = deva_idx;
    bow_attack.target_idx   = hag_idx;
    bow_attack.weapon_idx   = 1;  // Longbow

    AttackResult bow_result = engine->executeAction(*bm, bow_attack);
    EXPECT_TRUE(bow_result.valid);

    int hag_hp_after = bm->getAgentStats(hag_idx).hp_cur;
    if (bow_result.hit) {
        EXPECT_EQ(hag_hp_after, hag_hp_before - bow_result.total_damage);
    } else {
        EXPECT_EQ(hag_hp_after, hag_hp_before);
    }

    // Turn 2, Step 7b: Green Hag casts Ice Storm at Deva's cell
    engine->beginTurn(hag_idx, *bm);
    int deva_hp_before = bm->getAgentStats(deva_idx).hp_cur;

    // Deva is at starting position (10,6)
    int deva_aoe_col = 10;
    int deva_aoe_row = 6;

    SpellAction sa;
    sa.caster_idx     = hag_idx;
    sa.spell_idx      = 0;           // Ice Storm
    sa.target_indices = {deva_idx};  // Deva in AoE
    sa.aoe_col = deva_aoe_col;
    sa.aoe_row = deva_aoe_row;

    SpellResult sr = engine->executeSpell(*bm, sa);
    EXPECT_TRUE(sr.valid);
    ASSERT_FALSE(sr.target_results.empty());
    EXPECT_GT(sr.target_results[0].total_damage, 0);  // Ice Storm deals damage
    EXPECT_LT(bm->getAgentStats(deva_idx).hp_cur, deva_hp_before);

    // Manually place terrain effect for Ice Storm (executeSpell does not do this)
    std::vector<Cell> aoe_cells;
    for (int c = 0; c < bm->gridCols(); ++c) {
        for (int r = 0; r < bm->gridRows(); ++r) {
            int dc = c - deva_aoe_col;
            int dr = r - deva_aoe_row;
            if (dc * dc + dr * dr <= 16) {  // radius 4 cells = 20ft
                aoe_cells.push_back(Cell{c, r});
            }
        }
    }
    [[maybe_unused]] auto effect_id = bm->placeTerrainEffect("Ice Storm", aoe_cells, TerrainDifficulty::Halved, 999, hag_idx);
    bm->updateTerrain();  // Apply active effects to terrain multiplier cache
    EXPECT_FLOAT_EQ(static_cast<float>(bm->getTerrainMultiplier(Cell{deva_aoe_col, deva_aoe_row})), 0.5f);

    // Verify concentration set by executeSpell
    auto hag_cond = bm->getAgentConditions(hag_idx);
    EXPECT_TRUE(hag_cond.concentrating);
    EXPECT_EQ(hag_cond.concentrating_on, "Ice Storm");

    // Turn 3, Step 8: Green Hag drops concentration
    engine->beginTurn(hag_idx, *bm);

    auto cond = bm->getAgentConditions(hag_idx);
    cond.concentrating    = false;
    cond.concentrating_on = "";
    bm->setAgentConditions(hag_idx, cond);
    [[maybe_unused]] auto removed_effects = bm->removeTerrainEffectsBySource(hag_idx);

    // Verify terrain restored to normal at Deva's position
    EXPECT_FLOAT_EQ(static_cast<float>(bm->getTerrainMultiplier(Cell{deva_aoe_col, deva_aoe_row})), 1.0f);
    auto cond_final = bm->getAgentConditions(hag_idx);
    EXPECT_FALSE(cond_final.concentrating);
    EXPECT_EQ(cond_final.concentrating_on, "");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
