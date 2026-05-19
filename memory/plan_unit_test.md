# Plan: Second Unit Test — Full Combat Scenario

## Context
The concentration-state C++ refactor from the previous plan is complete. This plan covers the second unit test: loading monster stats from JSON, creating agents with weapons and spells, running a multi-turn combat scenario (dash, fly, ranged attack, AoE spell, concentration management), and verifying state transitions.

## Previous Plan Status
COMPLETE — all concentration C++ refactoring has been implemented and the first unit test passes.

---

## Key API Facts

| Operation | Call |
|-----------|------|
| Add agents | `bm->addAgentConfig(cfg)` × N, then `bm->applyAgentConfigs()` once |
| Set stats | `bm->setAgentStats(idx, stats)` |
| Add weapon | `bm->addWeaponToAgent(idx, weapon)` |
| Add spell | `bm->addSpellToAgent(idx, spell)` |
| Dash | `bm->applyDash(idx)` — sets dashing condition + adds movement budget |
| Walk move | `bm->moveAgent(idx, Cell{col,row})` — Dijkstra, returns false if blocked |
| Fly move | `bm->moveAgent(idx, Cell{col,row}, MovementType::Fly)` — Chebyshev |
| Begin turn | `engine->beginTurn(idx, *bm)` — seeds walk/fly budgets from stats |
| Attack | `engine->executeAction(*bm, atk)` |
| Cast spell | `engine->executeSpell(*bm, sa)` — auto-sets concentration state |
| Place terrain | `bm->placeTerrainEffect(name, cells, difficulty, turns, source_idx)` |
| Remove terrain | `bm->removeTerrainEffectsBySource(source_idx)` |
| Read terrain | `bm->getTerrainMultiplier(Cell{col,row})` |
| Conditions | `bm->getAgentConditions(idx)` / `bm->setAgentConditions(idx, cond)` |
| Query position | `bm->placedAgents()[idx].origin` (`Cell` with `.col` and `.row`) |

**Critical**: `executeSpell` does NOT place terrain on the map. The caller must call `placeTerrainEffect` after a successful spell. `executeSpell` DOES set `concentrating=true` automatically when `requires_concentration=true`.

**Critical**: `Agent::Stats` stores raw ability scores (`stats.con = 18`). DND2024_MonsterStats.json stores modifiers (`"CON Mod": "4"`). Convert: `score = 10 + 2 * mod`.

---

## Monster Stats (from DND2024_MonsterStats.json)

### Deva — index 0, starts at (11,6)
- HP: 229, AC: 17, Walk: 30, Fly: 90, PB: 4
- STR/DEX/CON/WIS/INT/CHA mods: +4/+4/+4/+5/+3/+5 → scores: 18/18/18/20/16/20
- Spellcasting: CHA (index 5)

### Green Hag — index 1, starts at (0,6)
- HP: 82, AC: 17, Walk: 30, Fly: 0 (empty string), PB: 2
- STR/DEX/CON/WIS/INT/CHA mods: +4/+1/+3/+2/+1/+2 → scores: 18/12/16/14/12/14
- Spellcasting: WIS (index 4)

---

## Files to Modify

| File | Change |
|------|--------|
| `gui/Dockerfile` | Add `COPY sprites/DND2024_MonsterStats.json /src/sprites/` |
| `gui/combat_tests.cpp` | Add `CombatScenarioTest` fixture and `FullCombatScenario` test |

---

## New Test Structure

### Fixture

```cpp
class CombatScenarioTest : public ::testing::Test {
protected:
    const std::string map_path     = "/src/maps/TestGrid12x12.png";
    const std::string terrain_path = "/src/maps/TestGrid12x12_terrain.json";
    const std::string stats_path   = "/src/sprites/DND2024_MonsterStats.json";

    BattleMap*    bm     = nullptr;
    CombatEngine* engine = nullptr;
    int deva_idx = 0;
    int hag_idx  = 1;

    void SetUp() override {
        bm = new BattleMap(map_path);
        bm->analyzeGrid();
        bm->detectWalls();
        applyTerrainConfiguration(*bm, terrain_path);
        engine = new CombatEngine(42);  // fixed seed → deterministic rolls
    }
    void TearDown() override { delete engine; delete bm; }
};
```

### Test: `FullCombatScenario`

**Phase A — Parse JSON, build stats**
```cpp
nlohmann::json data;
{ std::ifstream f(stats_path); ASSERT_TRUE(f.is_open()); f >> data; }

// lambda: mod string → raw score (10 + 2*mod)
auto modToScore = [](const nlohmann::json& m, const std::string& key) {
    std::string s = m.value(key, "0");
    return s.empty() ? 10 : 10 + 2 * std::stoi(s);
};

// Build Deva stats from JSON
Agent::Stats deva_stats;
const auto& dj = data["Deva"];
deva_stats.hp_max = deva_stats.hp_cur = std::stoi(dj["HP"].get<std::string>());
deva_stats.ac         = std::stoi(dj["AC"].get<std::string>());
deva_stats.prof_bonus = std::stoi(dj["PB"].get<std::string>());
deva_stats.speed_walk = std::stoi(dj["Walk"].get<std::string>());
{ auto fly = dj["Fly"].get<std::string>();
  deva_stats.speed_fly = fly.empty() ? 0 : std::stoi(fly); }
deva_stats.str = modToScore(dj,"STR Mod"); deva_stats.dex = modToScore(dj,"DEX Mod");
deva_stats.con = modToScore(dj,"CON Mod"); deva_stats.wis = modToScore(dj,"WIS Mod");
deva_stats.intel = modToScore(dj,"INT Mod"); deva_stats.cha = modToScore(dj,"CHA Mod");
deva_stats.spellcasting_ability = 5; deva_stats.can_cast_spell = true;
deva_stats.num_attacks = 1;

// Build Green Hag stats from JSON (same pattern)
Agent::Stats hag_stats;
const auto& hj = data["Green Hag"];
// ... same pattern, hag has Fly = ""
hag_stats.spellcasting_ability = 4; hag_stats.can_cast_spell = true;
hag_stats.num_attacks = 1;
```

**Phase B — Place agents**
```cpp
// Register BOTH configs before the single applyAgentConfigs() call
AgentConfig deva_cfg; deva_cfg.name = "Deva"; deva_cfg.spritePath = "deva.png";
deva_cfg.size = 1; deva_cfg.startCol = 11; deva_cfg.startRow = 6;
bm->addAgentConfig(deva_cfg);

AgentConfig hag_cfg; hag_cfg.name = "Green Hag"; hag_cfg.spritePath = "hag.png";
hag_cfg.size = 1; hag_cfg.startCol = 0; hag_cfg.startRow = 6;
bm->addAgentConfig(hag_cfg);

bm->applyAgentConfigs();
bm->setAgentStats(deva_idx, deva_stats);
bm->setAgentStats(hag_idx, hag_stats);
```

**Phase C — Add weapons (Deva) and spell (Hag)**
```cpp
// Longsword — weapon index 0
Weapon longsword; longsword.name = "Longsword"; longsword.type = WeaponType::Melee;
longsword.reach_ft = 5; longsword.proficient = true;
longsword.num_dice = 1; longsword.die_size = 8;
longsword.physicalDamages = {PhysicalDamage_t::Slashing};
bm->addWeaponToAgent(deva_idx, longsword);

// Longbow — weapon index 1
Weapon longbow; longbow.name = "Longbow"; longbow.type = WeaponType::Ranged;
longbow.normal_range_ft = 150; longbow.long_range_ft = 600; longbow.proficient = true;
longbow.num_dice = 1; longbow.die_size = 8;
longbow.physicalDamages = {PhysicalDamage_t::Piercing};
bm->addWeaponToAgent(deva_idx, longbow);

// Ice Storm (made concentration for this test to exercise terrain/concentration removal)
Spell ice_storm; ice_storm.name = "Ice Storm";
ice_storm.type = Spell::Harm; ice_storm.geometry = Spell::Sphere;
ice_storm.attack_type = Spell::Save; ice_storm.save_ability = Spell::SaveDex;
ice_storm.range = 300; ice_storm.radius = 20;
ice_storm.requires_concentration = true;
ice_storm.terrain_difficulty = TerrainDifficulty::Halved;
ice_storm.magic_damage_rolls = {{ MagicDamage_t::Cold, 2, 8 }};
ice_storm.physical_damage_rolls = {{ PhysicalDamage_t::Bludgeoning, 4, 6 }};
bm->addSpellToAgent(hag_idx, ice_storm);
```

**Steps 3–5 — Verify loadout**
```cpp
EXPECT_GT(bm->getAgentStats(deva_idx).speed_fly, 0);
EXPECT_EQ(bm->getAgentStats(hag_idx).speed_fly,  0);

EXPECT_EQ(bm->placedAgents()[deva_idx].weapons.size(), 2u);
EXPECT_EQ(bm->placedAgents()[hag_idx].weapons.size(),  0u);
EXPECT_EQ(bm->placedAgents()[deva_idx].weapons[0].name, "Longsword");
EXPECT_EQ(bm->placedAgents()[deva_idx].weapons[1].name, "Longbow");

EXPECT_EQ(bm->placedAgents()[hag_idx].spells.size(), 1u);
EXPECT_EQ(bm->placedAgents()[hag_idx].spells[0].name, "Ice Storm");
```

**Step 6a — Turn 1: Green Hag dashes to (2,4)**
```cpp
// Green Hag: Dash → walk around col-1 wall through row 0
// Path: (0,6)→(0,0)→(1,0)→(2,0)→(2,4) = 12 cells = 60ft (30+30 from dash)
engine->beginTurn(hag_idx, *bm);
bm->applyDash(hag_idx);
EXPECT_TRUE(bm->getAgentConditions(hag_idx).dashing);
EXPECT_TRUE(bm->moveAgent(hag_idx, Cell{2, 4}));
EXPECT_EQ(bm->placedAgents()[hag_idx].origin.col, 2);
EXPECT_EQ(bm->placedAgents()[hag_idx].origin.row, 4);
```

**Step 6b — Turn 1: Deva flies to (9,4)**
```cpp
// Deva flies over impassable chasm at col 9 (rows 1–10); Chebyshev dist = 2 cells
engine->beginTurn(deva_idx, *bm);
EXPECT_TRUE(bm->moveAgent(deva_idx, Cell{9, 4}, MovementType::Fly));
EXPECT_EQ(bm->placedAgents()[deva_idx].origin.col, 9);
EXPECT_EQ(bm->placedAgents()[deva_idx].origin.row, 4);
```

**Step 7a — Turn 2: Deva shoots Longbow at Green Hag**
```cpp
engine->beginTurn(deva_idx, *bm);
int hag_hp_before = bm->getAgentStats(hag_idx).hp_cur;

Attack bow_attack;
bow_attack.attacker_idx = deva_idx;
bow_attack.target_idx   = hag_idx;
bow_attack.weapon_idx   = 1;  // Longbow

AttackResult bow_result = engine->executeAction(*bm, bow_attack);
EXPECT_TRUE(bow_result.valid);

int hag_hp_after = bm->getAgentStats(hag_idx).hp_cur;
if (bow_result.hit)
    EXPECT_EQ(hag_hp_after, hag_hp_before - bow_result.total_damage);
else
    EXPECT_EQ(hag_hp_after, hag_hp_before);
```

**Step 7b — Turn 2: Green Hag casts Ice Storm at Deva's cell**
```cpp
engine->beginTurn(hag_idx, *bm);
int deva_hp_before = bm->getAgentStats(deva_idx).hp_cur;

SpellAction sa;
sa.caster_idx     = hag_idx;
sa.spell_idx      = 0;           // Ice Storm
sa.target_indices = {deva_idx};  // Deva is at the center of AoE
sa.aoe_col = 9;  sa.aoe_row = 4;

SpellResult sr = engine->executeSpell(*bm, sa);
EXPECT_TRUE(sr.valid);
ASSERT_FALSE(sr.target_results.empty());
EXPECT_GT(sr.target_results[0].total_damage, 0);  // Ice Storm deals damage even on save
EXPECT_LT(bm->getAgentStats(deva_idx).hp_cur, deva_hp_before);

// Manually place terrain effect (executeSpell does not do this)
std::vector<Cell> aoe_cells;
for (int c = 0; c < bm->gridCols(); ++c)
    for (int r = 0; r < bm->gridRows(); ++r) {
        int dc = c-9, dr = r-4;
        if (dc*dc + dr*dr <= 16)   // radius 4 cells = 20ft
            aoe_cells.push_back(Cell{c, r});
    }
bm->placeTerrainEffect("Ice Storm", aoe_cells, TerrainDifficulty::Halved, 999, hag_idx);
EXPECT_FLOAT_EQ(static_cast<float>(bm->getTerrainMultiplier(Cell{9,4})), 0.5f);

// Verify concentration set by executeSpell
auto hag_cond = bm->getAgentConditions(hag_idx);
EXPECT_TRUE(hag_cond.concentrating);
EXPECT_EQ(hag_cond.concentrating_on, "Ice Storm");
```

**Step 8 — Turn 3: Green Hag drops concentration**
```cpp
engine->beginTurn(hag_idx, *bm);

// Voluntary drop
auto cond = bm->getAgentConditions(hag_idx);
cond.concentrating    = false;
cond.concentrating_on = "";
bm->setAgentConditions(hag_idx, cond);
bm->removeTerrainEffectsBySource(hag_idx);

// Terrain at (9,4) had no special modifier before Ice Storm; expect it restored to 1.0
EXPECT_FLOAT_EQ(static_cast<float>(bm->getTerrainMultiplier(Cell{9,4})), 1.0f);
auto cond_final = bm->getAgentConditions(hag_idx);
EXPECT_FALSE(cond_final.concentrating);
EXPECT_EQ(cond_final.concentrating_on, "");
```

---

## Rebuild & Verify

```bash
cd /Users/rappoccio/Documents/Claude/Projects/DND
bash gui/runtests.sh
```

Expected output:
```
[  PASSED  ] BattleMapTest.LoadMapAndAddTerrain
[  PASSED  ] CombatScenarioTest.FullCombatScenario
2/2 Test #…  ALL PASSED
```
