---
name: plan-dnd-class-system
description: Full D&D 5e class system implementation plan with Resource abstraction, Barbarian first
metadata:
  type: project
---

## D&D 5e Class System Implementation Plan

**Status:** Planning phase
**First Implementation:** Barbarian (all subclasses, full mechanics)
**Date Started:** 2026-05-19

---

## Phase 1: Foundation — Resource Concept

### Resource Struct (C++ in new `resource.hpp`)

```cpp
struct Resource {
  std::string name;           // e.g., "Rage", "Ki", "Sorcery Points"
  int current{0};             // current amount
  int max{0};                 // maximum amount
  int short_rest_regen{0};    // amount restored after short rest
  int long_rest_regen{0};     // amount restored after long rest
  int duration{0};            // duration in turns (for limited-time resources like Rage)
};
```

### Example: Barbarian Rage at Level 1
```
name: "Rage"
current: 2
max: 2
short_rest_regen: 0
long_rest_regen: 2
duration: 10  // lasts 10 turns (~1 minute)
```

### Resource Integration with Agent
- `Agent::Stats` gets a `std::map<std::string, Resource> resources` field
- Classes can define custom resources (Rage, Ki, Sorcery Points, Channel Divinity, etc.)
- Generic enough for future AI/RL training (trainer can interrogate available resources)

---

## Phase 2: Agent Class Metadata — Enum Design

### New Enums to Create

**1. Background Enum** (D&D backgrounds)
- Acolyte, Charlatan, Criminal, Entertainer, Folk Hero, Guild Artisan, Hermit, Noble, Outlander, Sage, Sailor, Soldier, Urchin, Custom
- ~14 options from PHB

**2. Alignment Enum** (9 alignments)
- LawfulGood, LawfulNeutral, LawfulEvil
- NeutralGood, TrueNeutral, NeutralEvil
- ChaoticGood, ChaoticNeutral, ChaoticEvil

**3. Barbarian Subclasses** (for subclass_name when class = Barbarian)
- BerserkerPath, TotemWarriorPath, ZealotPath, AncestralGuardianPath, WildMagicPath, and others (all PHB + Xanathar's)

**4. Other Class Subclasses** (enums for each class, created as needed)

### Agent::Stats Field Additions
```cpp
Background background{BackgroundNone};
Alignment alignment{TrueNeutral};
BarbianSubclass subclass{BerserkerPath};  // polymorphic on character_class
```

---

## Phase 3: Skill System (Non-Breaking)

### Current State
- Agent::Stats has hardcoded save proficiency flags: `save_prof_str`, `save_prof_dex`, etc.
- Two skill proficiency flags: `stealth_prof`, `perception_prof` (for save proficiencies)

### Clarification
These flags are for **saving throw proficiencies**, not skill proficiencies.

### Skill Proficiencies Design
Skills are **modifiers** to specific rolls, not boolean flags:
- Acrobatics (DEX), Animal Handling (WIS), Arcana (INT), Athletics (STR), Deception (CHA)
- History (INT), Insight (WIS), Intimidation (CHA), Investigation (INT), Medicine (WIS)
- Nature (INT), Perception (WIS), Performance (CHA), Persuasion (CHA), Religion (INT)
- Sleight of Hand (DEX), Stealth (DEX), Survival (WIS)

**Implementation:** Add to Agent::Stats:
```cpp
std::map<std::string, int> skill_proficiency_bonus{};
// e.g., {"Perception": 2, "Survival": 2} for Barbarian
```
- When a skill check is needed, add `ability_modifier + skill_proficiency_bonus[skill_name]`
- No proficiency = 0 bonus

---

## Phase 4: Barbarian Class Full Implementation

### Core Mechanics

**1. Rage** (Resource)
- Uses per day: 2 at level 1, scaling to 6 at level 11, unlimited at level 20
- Duration: 10 turns (1 minute in-game)
- Bonus damage: 2 at level 1, scaling to 4 at level 9+
- Resistance: resistance to physical damage (0.5×) while active
- How to end: not attack or take damage on turn = ends at end of turn
- How to trigger: bonus action at turn start

**2. Unarmored Defense** (AC calculation)
- Formula: 10 + DEX mod + CON mod
- Overrides normal AC when not wearing armor/shield
- Needs: flag in Stats + AC computation override in combat

**3. Reckless Attack** (level 2)
- Attack rolls have advantage
- Melee attack rolls against have advantage
- Toggle at start of turn or per-attack

**4. Danger Sense** (level 2, reaction)
- React to visible threat (Dex save spell, area spell, ranged attack)
- Half damage on success, no damage on failure
- Needs: reaction tracking + condition system integration

**5. Extra Attack** (level 5)
- Already exists as `num_attacks` field in Stats
- Barbarian gets 2 attacks at level 5

**6. Fast Movement** (level 5)
- +10 feet to walk speed

**7. Feral Instinct** (level 7)
- Cannot be surprised
- Needs: surprise condition handling in combat

**8. Brutal Critical** (level 9, scales level 13, 17)
- On critical hit, roll extra damage dice
- Level 9: 1 extra die, Level 13: 2 extra dice, Level 17: 3 extra dice
- Applies per damage type per critical hit

**9. Relentless Rage** (level 11)
- If creature hit/takes damage during Rage, can extend Rage by 1 turn
- Limits: up to 10 turns total per Rage instance
- Needs: Rage duration tracking during turn

**10. Primal Champion** (level 20)
- Unlimited Rage
- No restriction on Rage/turn bonus damage bonus

### Subclass Features (Berserker, Totem Warrior, Zealot, etc.)
- Each subclass gets features at levels 3, 6, 10, 14
- Implemented one at a time after core Barbarian works

### Hit Die
- Barbarian uses d12 (highest in game)
- Already can be set via `Stats::set_class_level()`

### Proficiencies (Barbarian)
- Saving throws: STR, CON
- Skills: Choose 2 from {Animal Handling, Athletics, Intimidation, Nature, Perception, Survival}
- Weapons: Simple + Martial
- Armor: Light, Medium, Shields
- Starting equipment: Greataxe or 75 GP

---

## Implementation Order (Barbarian)

1. **Create `resource.hpp`** with Resource struct
2. **Add enum types** (Background, Alignment, BarbianSubclass, etc.)
3. **Extend Agent::Stats** with resources map, background, alignment, subclass fields
4. **Add skill proficiency system** to Stats (map-based)
5. **Implement Unarmored Defense** AC override
6. **Implement Rage resource** and bonus damage application
7. **Add Reckless Attack** toggle and advantage/disadvantage logic
8. **Add Danger Sense** reaction and half-damage logic
9. **Auto-scale hit die, prof_bonus** based on level (already partially done)
10. **Implement remaining features** (Extra Attack, Fast Movement, Feral Instinct, etc.)
11. **Test Barbarian full combat** (no subclass yet)
12. **Add Berserker subclass** features
13. **Test Berserker in combat**
14. Move to next class

---

## Key Architectural Notes

- **Mechanics in C++**: All damage calculations, Rage state, Unarmored Defense, etc.
- **Python layer**: Display Rage counter, show advantage/disadvantage UI, handle subclass selection in character creation
- **Generic resource system**: Allows future classes (Wizard Ki, Warlock Pact Magic, Cleric Channel Divinity) to reuse same code
- **One class at a time**: Barbarian complete before moving to Fighter, Monk, etc.
- **All subclasses for each class**: Don't move on until all Barbarian subclasses are done

---

## Files to Create/Modify

**New Files:**
- `gui/resource.hpp` — Resource struct

**Modified Files:**
- `gui/character_class.hpp` — Add Background, Alignment, BarbianSubclass enums
- `gui/agent.hpp` — Add resources map, background, alignment, subclass to Stats; extend skill system
- `gui/combat.cpp` — Implement Unarmored Defense, Rage damage, Reckless Attack, etc.
- `gui/main.py` — Add Barbarian subclass selection, Rage counter display, Reckless Attack toggle
- `gui/test_barbarian.py` — 20+ test cases for Barbarian mechanics

---

## Related Memories

- [[architecture-mechanics-in-cpp]] — Game mechanics belong in C++
- [[grapple-mechanics-implementation]] — Reference for how complex features are tested
