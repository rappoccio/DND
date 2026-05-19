# Plan: Migrate Class/Spell-Slot Logic to C++

## Context

The spell slot system (class tables, slot tracking, spell level/upcast data) was implemented in Python using `classes.json` and Python dicts. The user wants the core logic moved to C++ for future extensibility and type safety. This means:
- `CharacterClass` and `CasterType` enums in C++
- Hardcoded slot tables in C++ as a free function
- `Spell.level` and `Spell.upcast_dice_bonus` move from Python `_spell_metadata` dict into the `Spell` C++ struct
- `Agent::Stats` gains `character_class`, `char_level`, `spell_slots_max[9]`, `spell_slots_remaining[9]`
- Python removes all Python-side class/slot dicts; reads/writes through `bm.get_agent_stats()`

---

## Critical Files

- **`gui/spell.hpp`** — add `level`, `upcast_dice_bonus` to `Spell`
- **`gui/agent.hpp`** — add class/level/slot fields to `Stats`; `#include "character_class.hpp"`
- **`gui/character_class.hpp`** — NEW: enums + `compute_class_slots()` hardcoded tables
- **`gui/rpg_bindings.cpp`** — bind enums, new Stats fields, new Spell fields, free function
- **`gui/main.py`** — replace Python dicts with C++ stats field access

---

## Step 1 — New file: `character_class.hpp`

```cpp
#pragma once
#include <array>
#include <stdexcept>

namespace rpg {

enum CharacterClass {
    CharClassNone=0, Barbarian, Fighter, Monk, Rogue,
    Bard, Cleric, Druid, Sorcerer, Wizard,
    Paladin, Ranger, Warlock, NumCharacterClass
};

enum CasterType { CasterNone=0, CasterFull, CasterHalf, CasterPact };

inline CasterType get_caster_type(CharacterClass cls) {
    switch (cls) {
        case Bard: case Cleric: case Druid:
        case Sorcerer: case Wizard:  return CasterFull;
        case Paladin: case Ranger:   return CasterHalf;
        case Warlock:                return CasterPact;
        default:                     return CasterNone;
    }
}

inline std::array<int,9> compute_class_slots(CharacterClass cls, int lvl) {
    // Full caster table (Bard, Cleric, Druid, Sorcerer, Wizard) — see SRD
    static constexpr std::array<std::array<int,9>,20> kFull{{
        {2,0,0,0,0,0,0,0,0}, // 1 - Sorcerer/Wizard start with 2 first-level slots
        ...
    }};
    // NOTE: Bard/Cleric/Druid have 0 at level 1; Sorcerer/Wizard start with slots.
    // The function handles the Bard/Cleric/Druid vs Sorcerer/Wizard difference.
    // ... full table data here
}

} // namespace rpg
```

**Exact slot tables** (from `classes.json`):

Full-1 table (Bard/Cleric/Druid — 0 slots at lvl 1):
```
lvl 1: [0,0,0,0,0,0,0,0,0]
lvl 2: [2,0,0,0,0,0,0,0,0]
...
lvl 20:[4,3,3,3,2,2,2,1,1]
```

Full-2 table (Sorcerer/Wizard — start with slots at lvl 1):
```
lvl 1: [2,0,0,0,0,0,0,0,0]
...
lvl 20:[4,3,3,3,3,2,2,2,1]
```

Half table (Paladin/Ranger):
```
lvl 1: [0,0,0,0,0,0,0,0,0]
lvl 2: [2,0,0,0,0,0,0,0,0]
...
lvl 20:[4,3,3,2,1,1,0,0,0]
```

Pact (Warlock) — all slots packed into one level slot:
```
lvl 1: [1,0,0,0,0,0,0,0,0]
lvl 2: [2,0,0,0,0,0,0,0,0]
lvl 3: [0,2,0,0,0,0,0,0,0]
...
lvl 9+: [0,0,0,0,2,0,0,0,0]
lvl 11+:[0,0,0,0,3,0,0,0,0]
lvl 17+:[0,0,0,0,4,0,0,0,0]
```

Non-casters: return all zeros.

`compute_class_slots(cls, lvl)` checks `get_caster_type(cls)` and selects the right table + row.

For Bard/Cleric/Druid vs Sorcerer/Wizard within CasterFull, distinguish by checking class directly.

---

## Step 2 — Modify `spell.hpp`

Add two fields to the `Spell` struct after `requires_concentration`:

```cpp
int level{0};              // 0 = cantrip; 1-9 = slot required
int upcast_dice_bonus{0};  // extra dice added per slot level above spell.level
```

---

## Step 3 — Modify `agent.hpp`

Add `#include "character_class.hpp"` and add to `Agent::Stats`:

```cpp
#include <array>
// ...
CharacterClass character_class{CharClassNone};
int char_level{1};
std::array<int,9> spell_slots_max{};       // zero-initialized
std::array<int,9> spell_slots_remaining{};

// Sets class+level and recomputes spell_slots_max; does NOT restore remaining.
void set_class_level(CharacterClass cls, int level) {
    character_class   = cls;
    char_level        = level;
    spell_slots_max   = compute_class_slots(cls, level);
    can_cast_spell    = std::any_of(spell_slots_max.begin(), spell_slots_max.end(),
                                    [](int s){ return s > 0; });
}

// Restore remaining slots to max (Long Rest).
void restore_spell_slots() {
    spell_slots_remaining = spell_slots_max;
}
```

---

## Step 4 — Modify `rpg_bindings.cpp`

Add `#include "character_class.hpp"` at top.

Before the `Stats` binding, register:

```cpp
py::enum_<CharacterClass>(m, "CharacterClass")
    .value("None",      CharacterClass::CharClassNone)
    .value("Barbarian", CharacterClass::Barbarian)
    .value("Fighter",   CharacterClass::Fighter)
    .value("Monk",      CharacterClass::Monk)
    .value("Rogue",     CharacterClass::Rogue)
    .value("Bard",      CharacterClass::Bard)
    .value("Cleric",    CharacterClass::Cleric)
    .value("Druid",     CharacterClass::Druid)
    .value("Sorcerer",  CharacterClass::Sorcerer)
    .value("Wizard",    CharacterClass::Wizard)
    .value("Paladin",   CharacterClass::Paladin)
    .value("Ranger",    CharacterClass::Ranger)
    .value("Warlock",   CharacterClass::Warlock)
    .export_values();

py::enum_<CasterType>(m, "CasterType")
    .value("None", CasterType::CasterNone)
    .value("Full", CasterType::CasterFull)
    .value("Half", CasterType::CasterHalf)
    .value("Pact", CasterType::CasterPact)
    .export_values();

m.def("compute_class_slots", &rpg::compute_class_slots,
      py::arg("character_class"), py::arg("level"));
m.def("get_caster_type",     &rpg::get_caster_type,
      py::arg("character_class"));
```

In the `Stats` binding block, add:
```cpp
.def_readwrite("character_class",       &Agent::Stats::character_class)
.def_readwrite("char_level",            &Agent::Stats::char_level)
.def_readwrite("spell_slots_max",       &Agent::Stats::spell_slots_max)
.def_readwrite("spell_slots_remaining", &Agent::Stats::spell_slots_remaining)
.def("set_class_level",                 &Agent::Stats::set_class_level,
     py::arg("cls"), py::arg("level"))
.def("restore_spell_slots",             &Agent::Stats::restore_spell_slots)
```

In the `Spell` binding block, add:
```cpp
.def_readwrite("level",             &Spell::level)
.def_readwrite("upcast_dice_bonus", &Spell::upcast_dice_bonus)
```

**Note on `CharacterClass.None` in Python**: pybind11 stores enum value names as strings and exposes them as attributes. `rpg.CharacterClass.None` is a syntax error in Python (keyword), so access via `getattr(rpg.CharacterClass, 'None')` or build a lookup dict by name in `main.py`.

---

## Step 5 — Modify `main.py`

### 5a. Remove Python-side state
- Remove `self._spell_slots`, `self._spell_slots_max`, `self._agent_class`, `self._agent_char_level`, `self._classes_json_cache`
- Remove methods `_load_classes_json()`, `_class_slots()`
- Keep `self.pending_spell_slot_level`

### 5b. Add class name ↔ enum mapping
```python
_CHAR_CLASS_NAMES = [
    "None", "Barbarian", "Fighter", "Monk", "Rogue",
    "Bard", "Cleric", "Druid", "Sorcerer", "Wizard",
    "Paladin", "Ranger", "Warlock"
]
def _class_name_to_enum(name):
    return getattr(rpg.CharacterClass, name)  # works for all except "None"
    # For "None": getattr(rpg.CharacterClass, 'None')  -- accessed via getattr
```

Use `getattr(rpg.CharacterClass, cls_name)` uniformly since it works for all names including "None".

### 5c. Update `_on_stats_ok()`
```python
stats.set_class_level(getattr(rpg.CharacterClass, class_name), char_level)
stats.spell_slots_remaining = list(stats.spell_slots_max)   # restore on class change
bm.set_agent_stats(idx, stats)
```
Remove old `_agent_class[idx]`, `_agent_char_level[idx]`, `_spell_slots[idx]`, `_spell_slots_max[idx]` assignments.

### 5d. Update `_start_cast_spell()`
Read from `bm.get_agent_stats(idx).spell_slots_remaining` and `.spell_slots_max` instead of `self._spell_slots`, `self._spell_slots_max`.

Spell level now from `spell.level` directly (no `_spell_metadata` lookup for level).

### 5e. Update `_resolve_spell_cast()` and `_resolve_spell_cast_aoe()`
- Get `sp_level = sp.level` and `upcast_bonus = sp.upcast_dice_bonus` directly from the spell object
- Decrement slot:
  ```python
  sl = self.pending_spell_slot_level
  if sl > 0:
      stats = self.bm.get_agent_stats(caster_idx)
      slots = list(stats.spell_slots_remaining)
      slots[sl - 1] = max(0, slots[sl - 1] - 1)
      stats.spell_slots_remaining = slots
      self.bm.set_agent_stats(caster_idx, stats)
  ```

### 5f. Update `_on_long_rest()`
```python
for idx in range(len(self.bm.placed_agents)):
    stats = self.bm.get_agent_stats(idx)
    stats.restore_spell_slots()
    self.bm.set_agent_stats(idx, stats)
```

### 5g. Update `_draw_combat_panel()`
```python
stats = self.bm.get_agent_stats(cur_idx)
slots_max = list(stats.spell_slots_max)
slots_cur = list(stats.spell_slots_remaining)
```

### 5h. Update `_spell_to_dict()` 
Read `level` and `upcast_dice_bonus` directly from the spell object (not `_spell_metadata`).
Keep `_spell_metadata` only for terrain_color and hatch_pattern.

### 5i. Update `_on_spell_done()`
Set `sp.level = d["level"]` and `sp.upcast_dice_bonus = d["upcast_dice_bonus"]` on the spell object, then call `bm.set_agent_spells(idx, spells)`.

### 5j. Update `_save_agents()`
Save from C++ stats:
```python
stats = self.bm.get_agent_stats(i)
d["agent_class"]       = stats.character_class.name   # e.g. "Wizard"
d["agent_char_level"]  = stats.char_level
d["spell_slots_max"]   = list(stats.spell_slots_max)
d["spell_slots_cur"]   = list(stats.spell_slots_remaining)
```
Spell level/upcast now come from `_spell_to_dict()` via Spell object directly.

### 5k. Update `_load_agents()`
```python
cls_name = d.get("agent_class", "None")
level    = d.get("agent_char_level", 1)
stats.set_class_level(getattr(rpg.CharacterClass, cls_name), level)
slots_cur = d.get("spell_slots_cur", list(stats.spell_slots_max))
stats.spell_slots_remaining = slots_cur
bm.set_agent_stats(i, stats)
```

### 5l. Apply-agent-configs save/restore block
Remove the Python-dict save/restore for `_spell_slots*`, `_agent_class`, `_agent_char_level` — now persisted in C++ stats which survive `apply_agent_configs()` via the stats snapshot/restore pattern already in place.

### 5m. PC creation flow (`_on_pc_class_selected()`)
Use `getattr(rpg.CharacterClass, class_name)` and call `stats.set_class_level(...)` instead of the old string-based approach.

---

## Step 6 — classes.json

Keep `gui/classes.json` as a reference document (do not delete it). It is no longer loaded at runtime.

---

## Build & Verify

```bash
cmake -S gui -B gui/build -DCMAKE_BUILD_TYPE=Release
cmake --build gui/build --parallel
cmake --install gui/build
python gui/main.py <map.png>
```

Verification checklist:
1. Select PC → Wizard, level 5 → Stats show spell_slots_max = [4,3,2,0,0,0,0,0,0]
2. Begin combat → spell slot pips display correctly
3. Cast a leveled spell at upcast level → extra damage dice applied; slot decremented
4. Exhaust slots → spell no longer in cast menu
5. Long Rest → all slots restored
6. Save → reload → class, level, remaining slots persist correctly
7. Non-caster agent → no spell slot display
8. Warlock level 5 → 2 pact slots at 3rd level
