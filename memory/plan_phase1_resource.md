---
name: plan-phase1-resource
description: Detailed implementation plan for Resource struct and integration with Agent
metadata:
  type: project
---

## Phase 1: Resource Concept — Detailed Implementation Plan

**Scope:** Create generic Resource abstraction for use by all classes
**Files:** New `gui/resource.hpp`; modified `gui/agent.hpp`, `gui/combat.cpp`
**Testing:** Python tests to verify resource tracking, rest mechanics

---

## Step 1: Create `resource.hpp`

### Resource Struct Definition

```cpp
#pragma once
#include <string>
#include <nlohmann/json.hpp>

namespace rpg {

struct Resource {
  // Identity
  std::string name;  // e.g., "Rage", "Ki", "Sorcery Points", "Channel Divinity"

  // Current state
  int current{0};     // current amount available
  int max{0};         // max amount per rest cycle
  
  // Regeneration rules
  int short_rest_regen{0};  // restored after short rest
  int long_rest_regen{0};   // restored after long rest (or if short_rest_regen=0, restored here)
  
  // Duration tracking (for limited-time resources like Rage)
  int duration{0};           // duration in turns (0 = permanent resource)
  int duration_remaining{0}; // turns left (only used if duration > 0)

  // Constructor
  Resource() = default;
  Resource(const std::string& n, int mx, int dur = 0)
    : name(n), current(mx), max(mx), duration(dur), duration_remaining(dur) {}

  // Queries
  [[nodiscard]] bool isFull() const noexcept { return current >= max; }
  [[nodiscard]] bool isEmpty() const noexcept { return current <= 0; }
  [[nodiscard]] bool isActive() const noexcept { 
    return duration_remaining > 0; 
  }

  // Spending a resource (e.g., using a Rage)
  // Returns true if successfully spent, false if not enough
  bool spend(int amount = 1) noexcept {
    if (current < amount) return false;
    current -= amount;
    return true;
  }

  // Gain resource (e.g., from a feature that grants bonus uses)
  void gain(int amount = 1) noexcept {
    current = std::min(current + amount, max);
  }

  // Restore to full (Long Rest)
  void restore_long_rest() noexcept {
    if (long_rest_regen > 0) {
      current = long_rest_regen;
    } else {
      current = max;
    }
    duration_remaining = duration;  // reset duration counter
  }

  // Restore partial (Short Rest)
  void restore_short_rest() noexcept {
    if (short_rest_regen > 0) {
      current = std::min(current + short_rest_regen, max);
    }
    // duration_remaining unchanged on short rest
  }

  // Tick down duration (called each turn)
  void tick_duration() noexcept {
    if (duration > 0 && duration_remaining > 0) {
      duration_remaining--;
    }
  }

  // Reset duration (e.g., when Rage is activated)
  void reset_duration() noexcept {
    duration_remaining = duration;
  }

  // JSON serialization for persistence
  [[nodiscard]] nlohmann::json to_json() const {
    return nlohmann::json{
      {"name", name},
      {"current", current},
      {"max", max},
      {"short_rest_regen", short_rest_regen},
      {"long_rest_regen", long_rest_regen},
      {"duration", duration},
      {"duration_remaining", duration_remaining}
    };
  }

  // JSON deserialization
  static Resource from_json(const nlohmann::json& j) {
    Resource r;
    r.name = j.value("name", "");
    r.current = j.value("current", 0);
    r.max = j.value("max", 0);
    r.short_rest_regen = j.value("short_rest_regen", 0);
    r.long_rest_regen = j.value("long_rest_regen", 0);
    r.duration = j.value("duration", 0);
    r.duration_remaining = j.value("duration_remaining", 0);
    return r;
  }
};

} // namespace rpg
```

---

## Step 2: Integrate Resource into Agent::Stats

### Modify `agent.hpp`

**Add to Stats struct:**
```cpp
#include "resource.hpp"

struct Stats {
  // ... existing fields ...

  // Class resources: Rage, Ki, Sorcery Points, Channel Divinity, etc.
  std::map<std::string, Resource> resources{};

  // Helper: get resource by name (returns nullptr if not found)
  [[nodiscard]] Resource* getResource(const std::string& name) noexcept {
    auto it = resources.find(name);
    return (it != resources.end()) ? &it->second : nullptr;
  }

  // Helper: const version
  [[nodiscard]] const Resource* getResource(const std::string& name) const noexcept {
    auto it = resources.find(name);
    return (it != resources.end()) ? &it->second : nullptr;
  }

  // Initialize class resources based on class and level
  // Called by set_class_level() or from character creation
  void initializeClassResources(CharacterClass cls, int level);

  // Long rest: restore spell slots + all resources
  void restore_resources_long_rest() {
    restore_spell_slots();
    for (auto& [name, res] : resources) {
      res.restore_long_rest();
    }
  }

  // Short rest: restore some resources (e.g., Ki for Monk)
  void restore_resources_short_rest() {
    for (auto& [name, res] : resources) {
      res.restore_short_rest();
    }
  }

  // Called at end of turn to tick down duration-based resources
  void tick_resource_durations() {
    for (auto& [name, res] : resources) {
      res.tick_duration();
    }
  }
};
```

---

## Step 3: Implement Resource Initialization

### In `agent.cpp`, add:

```cpp
void Agent::Stats::initializeClassResources(CharacterClass cls, int level) {
  resources.clear();

  switch (cls) {
    case Barbarian:
      // Rage: uses per day scales with level
      // Level 1-2: 2 uses, Level 3-4: 3 uses, ..., Level 11+: 6 uses, Level 20: unlimited
      {
        int rage_uses = 2;
        if (level >= 3) rage_uses = 3;
        if (level >= 5) rage_uses = 3;
        if (level >= 7) rage_uses = 4;
        if (level >= 9) rage_uses = 4;
        if (level >= 11) rage_uses = 4;
        if (level >= 13) rage_uses = 5;
        if (level >= 15) rage_uses = 5;
        if (level >= 17) rage_uses = 6;
        if (level >= 20) rage_uses = INT_MAX;  // unlimited

        Resource rage("Rage", rage_uses, 10);  // 10-turn duration
        rage.short_rest_regen = 0;  // not restored on short rest
        rage.long_rest_regen = rage_uses;
        resources["Rage"] = rage;
      }
      break;

    case Monk:
      // Ki: number of ki points = character level
      {
        Resource ki("Ki", level, 0);  // no duration
        ki.short_rest_regen = level;  // fully restored on short rest
        ki.long_rest_regen = level;
        resources["Ki"] = ki;
      }
      break;

    case Sorcerer:
      // Sorcery Points: equal to sorcerer level
      {
        Resource sp("Sorcery Points", level, 0);
        sp.short_rest_regen = 0;
        sp.long_rest_regen = level;
        resources["Sorcery Points"] = sp;
      }
      break;

    case Warlock:
      // Pact Magic: handled by spell slots, not resources
      // (could add Eldritch Invocations as a resource if needed)
      break;

    case Cleric:
      // Channel Divinity: uses per rest = 1 + WIS mod (minimum 1)
      {
        int uses = 1;  // base
        int cd_uses = std::max(1, 1 + _mod(wis));
        Resource cd("Channel Divinity", cd_uses, 0);
        cd.short_rest_regen = 0;
        cd.long_rest_regen = cd_uses;
        resources["Channel Divinity"] = cd;
      }
      break;

    // Other classes without resources (Fighter, Rogue, etc.) have no entries
    default:
      break;
  }
}
```

---

## Step 4: Python Bindings (pybind11)

### In `rpg_bindings.cpp`, add:

```cpp
// Resource bindings
py::class_<rpg::Resource>(m, "Resource")
  .def(py::init<>())
  .def(py::init<const std::string&, int>())
  .def(py::init<const std::string&, int, int>())
  .def_readwrite("name", &rpg::Resource::name)
  .def_readwrite("current", &rpg::Resource::current)
  .def_readwrite("max", &rpg::Resource::max)
  .def_readwrite("short_rest_regen", &rpg::Resource::short_rest_regen)
  .def_readwrite("long_rest_regen", &rpg::Resource::long_rest_regen)
  .def_readwrite("duration", &rpg::Resource::duration)
  .def_readwrite("duration_remaining", &rpg::Resource::duration_remaining)
  .def("is_full", &rpg::Resource::isFull)
  .def("is_empty", &rpg::Resource::isEmpty)
  .def("is_active", &rpg::Resource::isActive)
  .def("spend", &rpg::Resource::spend)
  .def("gain", &rpg::Resource::gain)
  .def("restore_long_rest", &rpg::Resource::restore_long_rest)
  .def("restore_short_rest", &rpg::Resource::restore_short_rest)
  .def("tick_duration", &rpg::Resource::tick_duration)
  .def("reset_duration", &rpg::Resource::reset_duration);
```

---

## Step 5: Testing (Python)

### Create `gui/test_resource.py`:

```python
import rpg_battle_map as rpg

def test_resource_spend():
    """Test spending a resource"""
    res = rpg.Resource("Rage", 2)
    assert res.current == 2
    assert res.spend(1) == True
    assert res.current == 1
    assert res.spend(2) == False  # not enough
    assert res.current == 1

def test_resource_long_rest():
    """Test resource restoration on long rest"""
    res = rpg.Resource("Rage", 2)
    res.long_rest_regen = 2
    res.spend(1)
    assert res.current == 1
    res.restore_long_rest()
    assert res.current == 2

def test_resource_short_rest():
    """Test partial restoration on short rest"""
    res = rpg.Resource("Ki", 10, 0)
    res.short_rest_regen = 4
    res.spend(6)
    assert res.current == 4
    res.restore_short_rest()
    assert res.current == 8  # 4 + 4

def test_resource_duration():
    """Test duration-based resource (Rage)"""
    res = rpg.Resource("Rage", 2, 10)  # 10-turn duration
    assert res.is_active() == False  # not active yet
    res.reset_duration()
    assert res.is_active() == True
    assert res.duration_remaining == 10
    for _ in range(10):
        res.tick_duration()
    assert res.is_active() == False

def test_barbarian_resources():
    """Test Barbarian resource setup at different levels"""
    # Level 1: 2 Rage uses
    bm = rpg.BattleMap(100, 100)
    agent = bm.create_agent(50, 50, 0, 1, "test.png")
    agent.set_class_level(rpg.CharacterClass.Barbarian, 1)
    
    rage = agent.get_resource("Rage")
    assert rage is not None
    assert rage.current == 2
    assert rage.max == 2
    assert rage.duration == 10
    assert rage.short_rest_regen == 0
    assert rage.long_rest_regen == 2
    
    # Level 17: 6 Rage uses
    agent.set_class_level(rpg.CharacterClass.Barbarian, 17)
    rage = agent.get_resource("Rage")
    assert rage.max == 6

if __name__ == "__main__":
    test_resource_spend()
    test_resource_long_rest()
    test_resource_short_rest()
    test_resource_duration()
    test_barbarian_resources()
    print("✅ All resource tests passed")
```

---

## Implementation Checklist

- [ ] Create `gui/resource.hpp` with Resource struct
- [ ] Add includes to `agent.hpp`
- [ ] Add resources map to Agent::Stats
- [ ] Add resource helper methods to Stats
- [ ] Implement `initializeClassResources()` in `agent.cpp`
- [ ] Add pybind11 bindings for Resource
- [ ] Rebuild C++ extension
- [ ] Create `gui/test_resource.py` test suite
- [ ] Run tests and verify all pass
- [ ] Commit changes with message: "Add Resource system for class abilities (Rage, Ki, Sorcery Points, etc)"

---

## Success Criteria

✅ Resource struct compiles with all methods  
✅ Resources are accessible from Python via pybind11  
✅ All test cases pass (spend, rest mechanics, duration ticking)  
✅ Barbarian Rage resources created correctly per level  
✅ Ready for Phase 2 (Enum design)

