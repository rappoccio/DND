# Combat Test Scenarios

Comprehensive unit tests for the D&D combat system with detailed logging.

## Test 1: Comprehensive Scenario Test (`ComprehensiveScenarioTest`)

**File:** `combat_tests.cpp`  
**Log Output:** `/tmp/combat_test_log.txt`

### Scenario
Knight vs Mage one-on-one duel with melee and ranged combat.

### Tests
- ✓ Agent configuration and placement
- ✓ Weapon assignment
- ✓ Movement mechanics
- ✓ Attack resolution with accuracy checks
- ✓ Damage calculation and application
- ✓ HP tracking across multiple turns

### Key Metrics Logged
```
Phase 1: Agent Configuration
  - Load stats from JSON
  - HP pools and AC values

Phase 2: Agent Placement
  - Starting positions
  - Grid coordinates

Phase 3: Weapon Equipping
  - Weapon name and damage type
  - Damage dice configuration

Phase 4: Movement
  - Movement source/destination
  - Movement success verification

Phase 5-6: Combat Attacks
  - Attack validity
  - d20 roll + modifier
  - Target AC comparison
  - Hit/miss result
  - Damage rolls and totals
  - HP changes before/after

Phase 7: Final Status
  - Final HP and health percentage
```

---

## Test 2: Multi-Agent Spell Battle (`MultiAgentSpellBattleTest`)

**File:** `combat_tests.cpp`  
**Log Output:** `/tmp/multi_agent_spell_battle.txt`

### Scenario
Complex 4-agent battle featuring two spell-casting wizards and two mobile fighters, with concentration checks, spell effects, and terrain interactions.

### Agents
1. **Wizard A** - Casts Wall of Fire (concentration spell)
2. **Wizard B** - Casts Black Tentacles (concentration spell)
3. **Fighter A** - Moves through Wall of Fire
4. **Fighter B** - Moves through Black Tentacles and gets restrained

### Spells Used

#### Wall of Fire
- **Type:** Line geometry (20ft wide × 60ft long)
- **Damage:** 5d8 fire damage
- **Save:** DEX for half damage
- **Concentration:** Yes (maintained by Wizard A)

#### Black Tentacles
- **Type:** Sphere geometry (20ft radius)
- **Damage:** 3d6 force damage (grapple)
- **Save:** STR to escape restraint
- **Effect:** Applies restrained condition
- **Concentration:** Yes (maintained by Wizard B)

### Tests Covered

#### Phase 1-2: Setup
- ✓ Load multiple agent stats
- ✓ Place 4 agents on map
- ✓ Verify positions

#### Phase 3: Spell Creation
- ✓ Complex spell geometry (Line and Sphere)
- ✓ Save-based spell mechanics
- ✓ Concentration requirements
- ✓ Multi-damage-type support

#### Phase 4: Wall of Fire Cast
- ✓ Concentration check before cast (should be false)
- ✓ Spell casting at specific AoE location
- ✓ Concentration set after cast (should be true)
- ✓ Spell name stored in concentration tracking

#### Phase 5: Black Tentacles Cast
- ✓ Second caster maintaining separate concentration
- ✓ Verify each wizard tracks own spell independently
- ✓ Multiple concentration spells active simultaneously

#### Phase 6-7: Terrain Interaction
- ✓ Agents move into spell effect areas
- ✓ Damage application from moving into spell
- ✓ Condition application (restrained from tentacles)
- ✓ HP tracking through spell effects

#### Phase 8: Concentration Maintenance
- ✓ Concentration check when taking damage
- ✓ DC calculation: max(10, damage/2)
- ✓ Successful concentration check result
- ✓ Spell maintained after concentration check

#### Phase 9: Final Status Reporting
- ✓ All agents' HP and positions
- ✓ Active concentration spells
- ✓ Applied conditions (restrained, grappled, etc.)
- ✓ Complete battle state snapshot

### Key Metrics Logged

```
PHASE 4: Wizard A casts Wall of Fire
├─ Wizard A concentration: no (before)
├─ Cast at position (6, 6)
├─ Wall geometry: columns 4-8, rows 3-9
├─ Wizard A concentration: yes (after)
└─ Spell: Wall of Fire

PHASE 5: Wizard B casts Black Tentacles
├─ Wizard B concentration: no (before)
├─ Cast at position (8, 6)
├─ Sphere radius: 4 cells
├─ Wizard B concentration: yes (after)
└─ Spell: Black Tentacles

PHASE 6: Fighter A moves into Wall of Fire
├─ Start position: (2, 6)
├─ End position: (6, 5)
├─ Fire damage taken: 15
└─ HP: 42/60

PHASE 7: Fighter B into Black Tentacles
├─ Start position: (10, 6)
├─ End position: (8, 6)
├─ Grapple damage: 10
├─ Condition: RESTRAINED
└─ HP: 35/55

PHASE 8: Concentration Check
├─ Wizard A damage: 12
├─ DC: 10 (max(10, 12/2))
├─ Check result: SUCCESS
└─ Spell maintained: Wall of Fire

PHASE 9: Final Status
├─ Wizard A: 48/60 HP | Concentrating: Wall of Fire
├─ Wizard B: 60/60 HP | Concentrating: Black Tentacles
├─ Fighter A: 42/60 HP
└─ Fighter B: 35/55 HP | RESTRAINED
```

---

## Running the Tests

```bash
# Build and run all tests
cmake --build build
ctest

# Run only comprehensive scenario
./build/combat_tests --gtest_filter="ComprehensiveScenarioTest.*"

# Run only spell battle test
./build/combat_tests --gtest_filter="MultiAgentSpellBattleTest.*"

# View logs
cat /tmp/combat_test_log.txt
cat /tmp/multi_agent_spell_battle.txt
```

---

## Log File Analysis

Each test produces a detailed log file suitable for:

### Debugging
- Track exact sequence of events
- Verify spell geometry calculations
- Check damage roll results
- Validate state transitions

### Balance Analysis
- Average damage output
- Spell effectiveness metrics
- Concentration check pass rates
- Comparative spell costs/benefits

### Player Analysis (Future)
- Action sequences and decisions
- Resource expenditure (spell slots, HP)
- Tactical positioning
- Outcome analytics

---

## Future Test Scenarios

Consider adding:
- [ ] Terrain interaction with movement (difficult terrain, water, lava)
- [ ] Spell stacking (multiple spells in same area)
- [ ] Concentration break scenarios (failed saves, damage)
- [ ] Complex movement through multiple spell areas
- [ ] Boss encounters with multiple phase transitions
- [ ] Crowd control effectiveness tests
- [ ] Resource depletion scenarios (spell slots, actions)
- [ ] Line of sight and cover mechanics
- [ ] Environmental hazards interaction
- [ ] Long-duration battle simulation (10+ rounds)
