---
name: plan-phase2-enums-and-origins
description: Origin struct design with 16 D&D 2024 backgrounds, 9 alignments, 18 skills
metadata:
  type: project
---

## Phase 2: Origins System — Detailed Implementation Plan

**Scope:** Create Origin struct with 16 backgrounds + skills, Alignment enum, Barbarian Subclass enum
**Files:** Modified `gui/character_class.hpp` (enums + Origin struct), `gui/agent.hpp` (add Origin field)
**Testing:** Python tests to verify all origins and skill proficiencies

---

## Step 1: Add Enums to `character_class.hpp`

### Skill Enum (18 skills from D&D 5e)

```cpp
enum Skill {
    SkillNone = 0,
    // Combat/Physical skills (mechanically important in combat simulator)
    Acrobatics, Athletics, Stealth, SleigtOfHand,
    // Social/Knowledge skills (flavor text, some used in specific checks)
    AnimalHandling, Arcana, Deception, History, Insight,
    Intimidation, Investigation, Medicine, Nature, Perception,
    Performance, Persuasion, Religion, Survival,
    NumSkill
};
```

**18 skills total:** 4 combat-relevant, 14 flavor/documentation

### Background Enum (D&D 5e 2024 PHB)

```cpp
enum Background {
    BackgroundNone = 0,
    Acolyte, Artisan, Charlatan, Criminal, Entertainer,
    Farmer, Guard, Guide, Hermit, Merchant,
    Noble, Sage, Sailor, Scribe, Soldier,
    Wayfarer,
    NumBackground
};
```

### Alignment Enum (9 alignments)

```cpp
enum Alignment {
    AlignmentNone = 0,
    LawfulGood, LawfulNeutral, LawfulEvil,
    NeutralGood, TrueNeutral, NeutralEvil,
    ChaoticGood, ChaoticNeutral, ChaoticEvil,
    NumAlignment
};
```

### Barbarian Subclass Enum (2024 D&D)

```cpp
enum BarbianSubclass {
    BarbianSubclassNone = 0,
    BerserkerPath, WildHeartPath, WorldTreePath, ZealotPath,
    NumBarbianSubclass
};
```

**4 Barbarian subclasses (2024):** Path of the Berserker, Path of the Wild Heart, Path of the World Tree, Path of the Zealot

---

## Step 2: Create Origin Struct

### Origin struct in `character_class.hpp`

```cpp
struct Origin {
  Background background;
  
  // Ability score increases: 3 indices (0=STR, 1=DEX, 2=CON, 3=INT, 4=WIS, 5=CHA)
  std::array<int, 3> ability_increases;
  
  // TODO: Origin Feat (implement when Feat system exists)
  std::string origin_feat;
  
  // Skill proficiencies (from the 18 D&D skills)
  std::vector<Skill> skill_proficiencies;
};
```

### Origin Data (hardcoded lookup table)

All 16 backgrounds with their data:

```cpp
static constexpr std::array<Origin, 16> kOrigins = {{
  // Acolyte: INT, WIS, CHA | Magic Initiate (Cleric) | Insight, Religion
  {Acolyte, {3, 4, 5}, "Magic Initiate (Cleric)", {Insight, Religion}},
  
  // Artisan: STR, DEX, INT | Crafter | Investigation, Persuasion
  {Artisan, {0, 1, 3}, "Crafter", {Investigation, Persuasion}},
  
  // Charlatan: DEX, CON, CHA | Skilled | Deception, Sleight of Hand
  {Charlatan, {1, 2, 5}, "Skilled", {Deception, SleigtOfHand}},
  
  // Criminal: DEX, CON, INT | Alert | Sleight of Hand, Stealth
  {Criminal, {1, 2, 3}, "Alert", {SleigtOfHand, Stealth}},
  
  // Entertainer: STR, DEX, CHA | Musician | Acrobatics, Performance
  {Entertainer, {0, 1, 5}, "Musician", {Acrobatics, Performance}},
  
  // Farmer: STR, CON, WIS | Tough | Animal Handling, Nature
  {Farmer, {0, 2, 4}, "Tough", {AnimalHandling, Nature}},
  
  // Guard: STR, INT, WIS | Alert | Athletics, Perception
  {Guard, {0, 3, 4}, "Alert", {Athletics, Perception}},
  
  // Guide: DEX, CON, WIS | Magic Initiate (Druid) | Stealth, Survival
  {Guide, {1, 2, 4}, "Magic Initiate (Druid)", {Stealth, Survival}},
  
  // Hermit: CON, WIS, CHA | Healer | Medicine, Religion
  {Hermit, {2, 4, 5}, "Healer", {Medicine, Religion}},
  
  // Merchant: CON, INT, CHA | Lucky | Animal Handling, Persuasion
  {Merchant, {2, 3, 5}, "Lucky", {AnimalHandling, Persuasion}},
  
  // Noble: STR, INT, CHA | Skilled | History, Persuasion
  {Noble, {0, 3, 5}, "Skilled", {History, Persuasion}},
  
  // Sage: CON, INT, WIS | Magic Initiate (Wizard) | Arcana, History
  {Sage, {2, 3, 4}, "Magic Initiate (Wizard)", {Arcana, History}},
  
  // Sailor: STR, DEX, WIS | Tavern Brawler | Acrobatics, Perception
  {Sailor, {0, 1, 4}, "Tavern Brawler", {Acrobatics, Perception}},
  
  // Scribe: DEX, INT, WIS | Skilled | Investigation, Perception
  {Scribe, {1, 3, 4}, "Skilled", {Investigation, Perception}},
  
  // Soldier: STR, DEX, CON | Savage Attacker | Athletics, Intimidation
  {Soldier, {0, 1, 2}, "Savage Attacker", {Athletics, Intimidation}},
  
  // Wayfarer: DEX, WIS, CHA | Lucky | Insight, Stealth
  {Wayfarer, {1, 4, 5}, "Lucky", {Insight, Stealth}},
}};
```

### Helper to get Origin by Background

```cpp
inline const Origin& getOrigin(Background bg) {
  if (bg >= 1 && bg < static_cast<int>(kOrigins.size())) {
    return kOrigins[bg - 1];  // 0-indexed array, 1-indexed enum
  }
  // Return first origin as fallback (should never happen)
  return kOrigins[0];
}
```

---

## Step 3: Add Origin Field to Agent::Stats

### Modify `agent.hpp` Stats struct

```cpp
struct Stats {
  // ... existing fields ...

  // ── Character Identity & Background ──────────────────────────────────
  Background background{BackgroundNone};
  Alignment alignment{TrueNeutral};
  BarbianSubclass barbarian_subclass{BarbianSubclassNone};
};
```

---

## Step 4: pybind11 Bindings

### In `rpg_bindings.cpp`, add enum bindings:

```cpp
// Skill enum (18 D&D skills)
py::enum_<Skill>(m, "Skill")
    .value("Acrobatics", Acrobatics)
    .value("AnimalHandling", AnimalHandling)
    .value("Arcana", Arcana)
    .value("Athletics", Athletics)
    .value("Deception", Deception)
    .value("History", History)
    .value("Insight", Insight)
    .value("Intimidation", Intimidation)
    .value("Investigation", Investigation)
    .value("Medicine", Medicine)
    .value("Nature", Nature)
    .value("Perception", Perception)
    .value("Performance", Performance)
    .value("Persuasion", Persuasion)
    .value("Religion", Religion)
    .value("Sleight of Hand", SleigtOfHand)
    .value("Stealth", Stealth)
    .value("Survival", Survival);

// Background enum (2024 PHB - 16 backgrounds)
py::enum_<Background>(m, "Background")
    .value("NONE", BackgroundNone)
    .value("Acolyte", Acolyte)
    .value("Artisan", Artisan)
    .value("Charlatan", Charlatan)
    .value("Criminal", Criminal)
    .value("Entertainer", Entertainer)
    .value("Farmer", Farmer)
    .value("Guard", Guard)
    .value("Guide", Guide)
    .value("Hermit", Hermit)
    .value("Merchant", Merchant)
    .value("Noble", Noble)
    .value("Sage", Sage)
    .value("Sailor", Sailor)
    .value("Scribe", Scribe)
    .value("Soldier", Soldier)
    .value("Wayfarer", Wayfarer);

// Alignment enum (9 alignments)
py::enum_<Alignment>(m, "Alignment")
    .value("NONE", AlignmentNone)
    .value("LawfulGood", LawfulGood)
    .value("LawfulNeutral", LawfulNeutral)
    .value("LawfulEvil", LawfulEvil)
    .value("NeutralGood", NeutralGood)
    .value("TrueNeutral", TrueNeutral)
    .value("NeutralEvil", NeutralEvil)
    .value("ChaoticGood", ChaoticGood)
    .value("ChaoticNeutral", ChaoticNeutral)
    .value("ChaoticEvil", ChaoticEvil);

// Barbarian Subclass enum (2024 D&D)
py::enum_<BarbianSubclass>(m, "BarbianSubclass")
    .value("NONE", BarbianSubclassNone)
    .value("Berserker", BerserkerPath)
    .value("WildHeart", WildHeartPath)
    .value("WorldTree", WorldTreePath)
    .value("Zealot", ZealotPath);

// Origin struct
py::class_<Origin>(m, "Origin")
    .def_readwrite("background", &Origin::background)
    .def_readwrite("ability_increases", &Origin::ability_increases)
    .def_readwrite("origin_feat", &Origin::origin_feat)
    .def_readwrite("skill_proficiencies", &Origin::skill_proficiencies);
```

### In Stats bindings:

```cpp
.def_readwrite("background", &Agent::Stats::background)
.def_readwrite("alignment", &Agent::Stats::alignment)
.def_readwrite("barbarian_subclass", &Agent::Stats::barbarian_subclass)
```

---

## Step 5: Python Tests

### Create `gui/test_origins.py` with test cases for:

1. All 16 background enum values exist
2. All 18 skill enum values exist
3. All 9 alignment values exist
4. All 4 Barbarian subclass values exist
5. Verify 1-2 Origins have correct data (e.g., Acolyte has INT/WIS/CHA increases, Insight/Religion skills)
6. Test reading/writing background field on Stats

---

## Implementation Checklist

- [ ] Add Skill, Background, Alignment, BarbianSubclass enums to `character_class.hpp`
- [ ] Create Origin struct with origin lookup table (all 16 backgrounds)
- [ ] Add helper `getOrigin()` function
- [ ] Add background, alignment, barbarian_subclass fields to Agent::Stats
- [ ] Add pybind11 bindings for all enums and Origin struct
- [ ] Add Stats property bindings for the three metadata fields
- [ ] Create `gui/test_origins.py` with comprehensive test cases
- [ ] Rebuild C++ extension
- [ ] Run tests and verify all pass
- [ ] Commit: "Add Origins system with 16 backgrounds, 18 skills, alignments, and Barbarian subclasses"

---

## Success Criteria

✅ All 4 enum types compile and are accessible from Python  
✅ Origin struct accessible from Python with correct data  
✅ All 16 origins have correct ability increases and skill proficiencies  
✅ Stats fields can be read/written correctly  
✅ All test cases pass  
✅ Ready for Phase 3 (Barbarian implementation)

