---
name: D&D Battle Map - Pending Features
description: Major feature work queued for the battle map spell/combat system
type: project
originSessionId: 6a475336-8241-4b12-ad96-af65d34b9e00
---
## Major Features to Implement

0. **Game Mode Architecture** 
   - Current main.py becomes "DM Mode" (manual dungeon master control)
   - New "Game Mode" with automated mobs and human-controlled players
   - Players can join automated encounters and play against AI mobs

0a. **DM mode and Player mode visibility** (#32)
   - DM Mode: Always see all agents (debugging/DM view)
   - Player Mode: Team-based visibility with LOS, invisibility, obscured checks
   - Two teams: "Players" and "Environment"
   - Players see all teammates, Environment agents only if LOS + not invisible/obscured
   - Need UI toggle and visual feedback for visibility

1. **Spell mechanics for non-player mobs** (#23) — ✅ RESOLVED
   - NPCs/monsters use "N/day" spell usage instead of spell slots
   - Separate tracking from player character spell slot system
   - Common in monster stat blocks

2a. **Persistent AoE Spell Effects** ✅ COMPLETED
   - Spells that affect agents entering the area AFTER casting
   - Examples: Black Tentacles, Wall of Fire, Spike Growth
   - Track which agents are in persistent effect areas each turn
   - Apply damage/effects when agents enter or move through areas
   - Integration with terrain/effect persistence system
   
   **Implementation Details:**
   1. **Spell Effects Overlay**
      - Add visual overlay like terrain and lighting overlays
      - Enabled by default to show persistent spell areas
      - Different colors/patterns for different spell types
   
   2. **Environmental Effects Logic**
      - Damage effects (e.g., Wall of Fire does 5d8 fire)
      - Difficult terrain effects (e.g., ice requires DEX save every N squares to avoid slip)
      - Obscuring terrain effects (e.g., fog clouds)
      - Difficult terrain already implemented; extend with save mechanics
   
   3. **Agent Location Checking**
      - **beginTurn()** - Check agents in effects at start of turn, apply standing effects
      - **executeTurn()** - Apply effects during movement/actions, track squares entered
      - **endTurn()** - Apply effects at end of turn, track net damage/condition changes

2b. **Spell Geometry Expansion** (Mostly Complete)
   - ✅ Implement Square geometry for spell areas (width/length based)
   - ✅ Implement Rectangle geometry for spell areas (width ≠ length)
   - ✅ **Square spell display fixed** — centered on clicked point, correct size
   - Implement Emanation geometry for spell effects radiating from a point
   - Distinguish from existing Line and Cone geometries
   - NOTE: Cube geometry deferred until 3D height maps are implemented (requires major refactoring)

2c. **Crowd control spells** (#24)
   - Skip turns (stunned, paralyzed, held conditions)
   - Automatic/forced movement triggered by spells
   - Dropping/disarming weapons
   - Integrate with condition system on agents

3. **Visibility and light mechanics** (#25)
   - ✅ Darkness and dim light areas
   - Darkvision, blindsight, truesight
   - Hiding and obscured conditions
   - Integration with LOS system for various vision types

4. **Missing spells in fetch_spells** (#26)
   - Some PHB spells missing from open5e database (e.g., Hunger of Hadar)
   - Add support for user-specified hardcoded spells
   - Merge custom spells with API-fetched data

5. **Bonus action constraints** (#27) — ✅ RESOLVED
   - Only available if off-hand weapon is equipped
   - Bonus action button only shows when off-hand weapon equipped
   - Off-hand weapons can be ranged or melee

6. **Default sprites** (#28)
   - Current default character sprites are visually unappealing
   - Find or create better free/AI-generated sprites
   - At minimum need acceptable geometric or symbolic representations

7. **Attack count bug** (#29) — ✅ RESOLVED
   - Currently gives N attacks per weapon equipped
   - Should be N attacks total to distribute among weapons
   - Dual wielding with 2 attacks should give 2 total attacks, not 4

8. **Refactor main.py** (#30) — ✅ RESOLVED
   - File has grown very large and is becoming unwieldy
   - Consider splitting into modules: dialogs, combat_ui, map_rendering, event_handling
   - Improve maintainability and code organization

9. **Difficult terrain not clearing on quit** (#31) — ✅ RESOLVED
   - Cleared TestDNDMap_terrain.json and added cleanup on exit
   - `_clear_temporary_terrain()` filters out spell-created terrain (regions with "source" field)
   - Terrain is now saved to JSON file on quit to persist cleanup

10. **D&D Class System**
    - Implement core classes: Barbarian, Bard, Druid, Fighter, Ranger, Sorcerer, Wizard, Warlock, Cleric, Paladin
    - Class-specific abilities: Rage, Action Surge, Heroic Inspiration, etc.
    - Cunning Action as bonus action for Rogues
    - Character leveling mechanics with level-up progression

11. **Character Creation Mechanics**
    - Point-buy system for stat allocation
    - Standard array option (15, 14, 13, 12, 10, 8)
    - Stat calculation and ability modifiers

11a. **Armor and Shields System**
    - Implement armor AC calculations (light, medium, heavy)
    - Shield support and AC bonuses
    - Armor class integration with attack rolls and defense

12. **Identifying Mechanics**
    - Identifying unknown items, potions, etc.
    - Arcana checks for magic item identification
    - Integration with inventory system

13. **Vision Mechanics Expansion**
    - "Heavily Obscured" condition (darkness, heavy fog)
    - "Partially Obscured" condition (light fog, shadows)
    - Vision type restrictions for heavily/partially obscured areas

14. **Damage Mechanics Expansion** ✅ COMPLETED
    - Resistance to damage types (0.5× multiplier)
    - Vulnerability to damage types (2.0× multiplier)
    - Immunity to damage types (0.0× multiplier)
    - Temporary hit points (separate from regular HP pool, absorbs damage first)
    - Per-type damage application across all damage paths (weapons, spells, persistent effects)
    - Save effects applied correctly (multipliers before halving)
    - Immunity messages in combat log (e.g., "Immune to Fire")
    - Vulnerability messages in combat log (e.g., "X dmg (Vulnerable to Fire)")
    - Resistance messages in combat log (e.g., "X dmg (Resistant to Cold)")
    - Combat log printed to console (stdout) and saved to combat_log.txt
    - Messages integrated across all spell attack types (AttackRoll, Save, Automatic)
    - Physical weapon damage types display correctly (e.g., "HIT 9 Piercing")
    - Fixed pybind11 vector assignment for proper damage roll loading from JSON

15. **Condition System**
    - Exhaustion levels and effects
    - Track multiple conditions on agents simultaneously
    - Death saves when HP reaches 0
    - Death mechanic and handling defeated agents
    - Implement D&D conditions:
      - Blinded, Charmed, Deafened, Exhaustion, Frightened
      - Grappled, Incapacitated, Invisible, Paralyzed, Petrified
      - Poisoned, Prone, Restrained, Stunned, Unconscious

16. **Experience and Progression**
    - XP tracking for characters
    - XP thresholds for level-up progression
    - Integration with character leveling mechanics

17. **Teams and Encounter Design**
    - Team system: Players vs Non-Players, Players vs Players
    - Visibility and targeting rules based on teams
    - Challenge Rating (CR) for NPCs for encounter balance

## Recent Completions (May 10, 2026)

### Off-Hand Weapon Support ✅
- Added `off_hand` boolean field to Weapon struct
- Off-hand weapons visible in weapon dialog checkbox
- Bonus action attack button only shows when off-hand weapon equipped
- Bonus attacks marked `is_offhand=True` (strips proficiency bonus)
- `has_offhand_attack` stat auto-derived from weapon configuration

### Weapon Damage Refactor (Spell-Format) ✅
- Replaced scalar `num_dice`/`die_size` with per-type damage roll vectors
- Weapons now use `MagicDamageRoll` and `PhysicalDamageRoll` structs (from spell.hpp)
- Each damage type has its own num_dice and die_size (e.g., 1d8 Piercing + 2d6 Fire)
- Updated combat damage rolling to iterate per-type rolls
- WeaponDialog completely redesigned:
  - Active damage types shown with editable dice inputs
  - Toggle buttons to add/remove damage types
  - Matches spell damage UI structure
- agents.json updated to new format
- Critical hits correctly double dice per damage type

## Context

These are the next priorities after fixing the spell dialog UI and getting spell creation working properly from spells.json.
