# D&D Battle Map: Class Architecture Refactoring Decision

## Current State

**Codebase:** C++ game engine (Qt GUI) + Python UI
- Main files: `gui/combat.cpp` (~4000 lines), `gui/agent.hpp`, `gui/combat.hpp`, `gui/rpg_bindings.cpp`
- Currently: Generic `Agent` class with `CharacterClass` enum (Barbarian, Wizard, Rogue, Cleric)
- **Problem:** Class-specific logic scattered throughout combat.cpp with conditionals like `if (stats.character_class == CharacterClass::Barbarian)`

## Current Progress

Recent implementation added:
- Barbarian Reckless Attack (auto-triggers on miss)
- Berserker Frenzy (bonus melee attack)
- Brutal Strike (L9+ feature with effect menu)
- All intertwined with generic Agent logic

**Trend:** Each new Barbarian feature adds 20-30 lines of conditionals. By L20 + 4 subclasses, Barbarian logic will be 500+ lines scattered across combat.cpp.

## Proposed Refactoring

**Goal:** Move class-specific mechanics into dedicated class objects

```cpp
Barbarian b(stats1);
Wizard w(stats2);
b.hit(w, weapon);  // Barbarian figures out its own mechanics
```

Two approaches:

### Option A: Virtual Functions (Traditional Polymorphism)
```cpp
class Character {
    virtual AttackResult hit(Character& target, const Weapon& w) = 0;
    virtual void activateRage() {}
};

class Barbarian : public Character {
    AttackResult hit(Character& target, const Weapon& w) override;
    void activateRage() override;
};
```

**Pros:** Simple, standard pattern, great IDE support, easy to understand  
**Cons:** Virtual dispatch overhead (negligible for game logic)

### Option B: Duck Typing with C++20 Concepts
```cpp
template<typename T>
concept CharacterClass = requires(T& c, T& target, const Weapon& w) {
    { c.hit(target, w) } -> std::same_as<AttackResult>;
};

class Barbarian {
    AttackResult hit(CharacterClass auto& target, const Weapon& w);
};
```

**Pros:** Zero runtime overhead, compile-time dispatch  
**Cons:** C++20 required, complex templates, cryptic error messages, harder to understand

## Questions for Opus

1. **Feasibility:** Measure actual scope in the codebase:
   - How many lines of Barbarian-specific logic exist in combat.cpp?
   - How many places check `character_class` or `barbarian_subclass` enums?
   - What are the dependency chains? (e.g., does Wizard code depend on generic Agent?)
   - How tightly coupled is the Python bindings layer?

2. **Effort Estimate:** Based on actual measurements:
   - Which approach (virtual functions vs. concepts) is actually easier?
   - Break down the work into concrete tasks with time estimates:
     - Extract Barbarian class (estimate based on actual code count)
     - Extract Wizard class
     - Refactor CombatEngine
     - Update Python bindings
     - Update/write tests
   - What's the minimum viable scope? (e.g., just Barbarian + Wizard, defer others?)
   - Is there a pilot task that would calibrate estimates better?

3. **Risk Assessment:**
   - Are there architectural blockers or hidden coupling that would blow up the timeline?
   - What's the backwards-compatibility impact on Python bindings?
   - How would this affect the test suite? (run_all_tests.py, etc.)

4. **Recommendation:** 
   - Which approach (virtual vs. concepts) do you recommend and why?
   - What's a realistic timeline? (I estimated 40-50 hrs with high uncertainty)
   - Should we do this now or after more features are implemented?

## Context Files

- `gui/combat.cpp` - Main game engine logic (4000 lines, contains all class-specific mechanics)
- `gui/combat.hpp` - CombatEngine class definition
- `gui/agent.hpp` - Agent/Stats/Conditions definitions
- `gui/rpg_bindings.cpp` - Python bindings for C++ classes
- `gui/main.py` - Python UI that calls combat engine

## Constraint

User prefers not to use excessive polymorphism, but is open to virtual functions if they're the cleaner solution. Team is experienced C++ but not necessarily with modern C++20 concepts.
