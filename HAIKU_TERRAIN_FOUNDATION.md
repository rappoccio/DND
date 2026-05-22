# Haiku Handoff — Brutal Strike Fix (Step 0) + Terrain Foundation (Steps 1–3)

Self-contained, mechanical C++/binding changes. Background/design is in
`TERRAIN_MIGRATION_SPEC.md` — you do NOT need to read it. Do exactly the edits below.

**TASK 0 is a bug fix (it DOES change behavior). TASKS 1–3 are purely additive /
behavior-neutral** — nothing in C++ reads their new fields yet (that wiring is a
later Opus step). In all cases the full test suite must still report
**25 passed, 0 failed** after your edits — that is your verification. If a
`test_barbarian_*` suite breaks after TASK 0, STOP and report it (it likely encoded
the old buggy behavior); do not "fix" it by reverting TASK 0.

**Build + test (Docker; host has no local cmake):**
```
docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build --parallel && cmake --install build"
docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND/gui && python3 run_all_tests.py"
```
The image ENTRYPOINT is `/bin/bash`, so pass `-c "..."` directly (NOT `bash -c`).

**Ordering rule (important):** `placeTerrainEffect` builds `ActiveTerrainEffect` by
positional aggregate init (battle_map.cpp ~1145). New struct fields and new function
params MUST be appended **last**, after the slip params, or existing callers break.

Do not reformat unrelated lines. Do not touch `main.py` except Task 2c.

---

## TASK 0 — Fix Brutal Strike "first attack only" bug (reset per-turn flags)

**Bug:** Brutal Strike is offered on the first attack it's used, then never again
for the rest of combat. Same root cause hides a second bug: Zealot Divine Fury
fires only once per combat instead of once per turn.

**Root cause:** The per-turn Barbarian condition flags are reset ONLY in
`CombatEngine::runRound` (combat.cpp:1162-1168), which the **GUI never calls** (the
GUI drives combat via `begin_turn` + `execute_action`). The real per-turn reset hook
is `Agent::turn()` (called from `beginTurn`, combat.cpp:727), and it currently does
NOT reset these flags. So once `brutal_strike_used_this_turn` is set true (on use),
nothing ever clears it in the GUI, and the eligibility gate
`!brutal_strike_used_this_turn` (combat.cpp:1639) stays false forever.

> Do NOT try to fix this by adding resets in `CombatEngine::beginTurn` after the
> `cond.reckless_attack = false` line — that local `cond` is re-read at combat.cpp:719
> and never written back on the normal path, so such edits are dead code. The fix
> must go in `Agent::turn()`, which mutates the agent's conditions in place.

### `gui/agent.hpp` — add per-turn resets to `Agent::turn()`
Find (lines ~500-506):
```cpp
    void turn() {
      conditions_.dashing     = false;
      conditions_.dodging     = false;
      conditions_.disengaging = false;
      conditions_.reaction_used = false;
      takeTurn();
    }
```
Change to:
```cpp
    void turn() {
      conditions_.dashing     = false;
      conditions_.dodging     = false;
      conditions_.disengaging = false;
      conditions_.reaction_used = false;
      // Per-turn Barbarian flags. Previously reset only in CombatEngine::runRound,
      // which the GUI never calls — left Brutal Strike/Divine Fury stuck after one use.
      conditions_.reckless_attack              = false;
      conditions_.brutal_strike_used_this_turn = false;
      conditions_.brutal_strike_available      = false;
      conditions_.berserker_frenzy_used        = false;
      conditions_.zealot_divine_fury_used      = false;
      takeTurn();
    }
```
Notes: (1) This also makes `reckless_attack` actually reset each turn (so a raging
Barbarian is re-prompted to declare Reckless Attack each turn — intended D&D
behavior; the existing `beginTurn:415` reset was dead code). (2) `agent.hpp` is a
header, so this requires a full rebuild (the build command below handles it). (3)
Leave `combat.cpp:1162-1168` and `beginTurn:415` as-is — redundant now but harmless.

---

## TASK 1 — Add `BattleMap::aoeCells` (C++ port of Python `_aoe_cells`)

### 1a. `gui/battle_map.hpp` — declaration
Find the `filterSpellCells` declaration (ends ~line 263):
```cpp
    [[nodiscard]] std::vector<Cell> filterSpellCells(const std::vector<Cell>& cells,
                                                     Cell casterOrigin, int casterSize,
                                                     const Spell& spell, Cell centerCell) const;
```
Immediately AFTER it, add:
```cpp
    // Compute the grid cells covered by a spell's AoE geometry (1 cell = 5 ft).
    // Cone/Line use casterOrigin as the apex/source. Single/Multiple return {}.
    [[nodiscard]] std::vector<Cell> aoeCells(Cell center, const Spell& spell,
                                             Cell casterOrigin) const;
```

### 1b. `gui/battle_map.cpp` — definition
Find the `filterSpellCells` definition (starts line 855). Add this complete function
immediately BEFORE it (i.e., just above the `std::vector<Cell> BattleMap::filterSpellCells(` line).
`<cmath>` is already included.
```cpp
std::vector<Cell> BattleMap::aoeCells(Cell center, const Spell& spell,
                                      Cell casterOrigin) const {
    std::vector<Cell> cells;
    const double ax = static_cast<double>(center.col);
    const double ay = static_cast<double>(center.row);

    switch (spell.geometry) {
    case Spell::Sphere: {
        const double r = spell.radius / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double dx = c - ax, dy = rr - ay;
                if (std::sqrt(dx * dx + dy * dy) <= r) cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Cone: {
        const double cx = casterOrigin.col, cy = casterOrigin.row;
        const double dx = ax - cx, dy = ay - cy;
        const double ln = std::sqrt(dx * dx + dy * dy);
        if (ln < 0.001) break;
        const double ux = dx / ln, uy = dy / ln;
        const double r = spell.radius / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double px = c - cx, py = rr - cy;
                const double plen = std::sqrt(px * px + py * py);
                if (plen < 0.001) continue;
                const double dot = px * ux + py * uy;
                if (dot > 0 && plen <= r && (dot / plen) >= 0.866)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Line: {
        const double cx = casterOrigin.col, cy = casterOrigin.row;
        const double dx = ax - cx, dy = ay - cy;
        const double ln = std::sqrt(dx * dx + dy * dy);
        if (ln < 0.001) break;
        const double ux = dx / ln, uy = dy / ln;
        const double lcells = spell.length / 5.0;
        const double wcells = spell.width / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double px = c - cx, py = rr - cy;
                const double along = px * ux + py * uy;
                const double perp = std::abs(-py * ux + px * uy);
                if (along >= 0.0 && along <= lcells && perp <= wcells / 2.0)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    case Spell::Square:
    case Spell::Rectangle: {
        const double wcells = spell.width / 5.0;
        const double lcells = spell.length / 5.0;
        for (int c = 0; c < cols_; ++c)
            for (int rr = 0; rr < rows_; ++rr) {
                const double dx = std::abs(c - ax), dy = std::abs(rr - ay);
                if (dx <= wcells / 2.0 && dy <= lcells / 2.0)
                    cells.push_back(Cell{c, rr});
            }
        break;
    }
    default:  // Single, Multiple, NumGeometry_t: no AoE footprint
        break;
    }
    return cells;
}
```

### 1c. `gui/rpg_bindings.cpp` — binding
Find the `filter_spell_cells` `.def(...)` block (lines 1682–1688), ending with:
```cpp
             "If check_los_on_center, only the center cell needs LOS (D&D 5e standard).")
```
Immediately AFTER that closing `)` line, add:
```cpp

        .def("aoe_cells", &BattleMap::aoeCells,
             py::arg("center"), py::arg("spell"), py::arg("caster_origin"),
             "Cells covered by a spell's AoE geometry (Cone/Line use caster_origin as apex).")
```

---

## TASK 2 — Spell carries its own terrain spec

### 2a. `gui/spell.hpp` — two new fields
Find (line ~46):
```cpp
      TerrainDifficulty terrain_difficulty{static_cast<TerrainDifficulty>(0)};  // Normal
```
Add immediately AFTER it:
```cpp
      int slip_save_dc{10};       // Slipping terrain: DEX save DC
      int slip_distance_feet{5};  // Slipping terrain: feet moved before a save is required
```

### 2b. `gui/rpg_bindings.cpp` — bind the two fields
Find the `terrain_difficulty` binding (lines 709–711):
```cpp
        .def_readwrite("terrain_difficulty",   &Spell::terrain_difficulty,
             "Terrain difficulty applied by this spell (Normal = no terrain effect).\n"
             "The duration is the same as spell.duration (in rounds).")
```
Add immediately AFTER it (before the `requires_concentration` line):
```cpp
        .def_readwrite("slip_save_dc",         &Spell::slip_save_dc,
             "Slipping terrain: DEX save DC.")
        .def_readwrite("slip_distance_feet",   &Spell::slip_distance_feet,
             "Slipping terrain: feet moved before a save is required.")
```

### 2c. `gui/main.py` — populate terrain_difficulty in `_dict_to_spell`
Find (line ~3285–3286):
```python
        s.effects_on_begin_turn = d.get("effects_on_begin_turn", True)
        s.effects_on_end_turn = d.get("effects_on_end_turn", False)
```
Add immediately AFTER those two lines:
```python
        # Parse terrain effect (Grease, Spike Growth, etc.) onto the C++ Spell.
        # Cosmetic color/hatch stay in _spell_metadata for rendering.
        te = d.get("terrain_effect")
        if te:
            if te.get("type") == "Slipping":
                s.terrain_difficulty = rpg.TerrainDifficulty.Slipping
                s.slip_save_dc       = int(te.get("slip_save_dc", 10))
                s.slip_distance_feet = int(te.get("slip_distance_feet", 5))
            else:
                m = float(te.get("multiplier", 0.5))
                s.terrain_difficulty = (rpg.TerrainDifficulty.Quartered if m <= 0.25
                                        else rpg.TerrainDifficulty.Halved)
```

---

## TASK 3 — Extend `ActiveTerrainEffect` + `placeTerrainEffect`

### 3a. `gui/battle_map.hpp` — two new struct fields (append LAST)
Find the end of the `ActiveTerrainEffect` struct (lines ~84–86):
```cpp
    int                 slip_save_dc{10};        // DC for DEX save (default 10)
    int                 slip_distance_feet{5};  // Feet moved before requiring save (default 5)
};
```
Change to:
```cpp
    int                 slip_save_dc{10};        // DC for DEX save (default 10)
    int                 slip_distance_feet{5};  // Feet moved before requiring save (default 5)
    int                 spell_idx{-1};                  // caster's spell index (-1 = none)
    bool                requires_concentration{false};  // terrain ends when caster drops concentration
};
```

### 3b. `gui/battle_map.hpp` — `placeTerrainEffect` declaration (append params LAST)
Find (lines ~281–287):
```cpp
    [[nodiscard]] int placeTerrainEffect(std::string name,
                                         std::vector<Cell> cells,
                                         TerrainDifficulty difficulty,
                                         int turns_remaining,
                                         int source_agent_idx,
                                         int slip_save_dc = 10,
                                         int slip_distance_feet = 5);
```
Change the final line `int slip_distance_feet = 5);` to:
```cpp
                                         int slip_distance_feet = 5,
                                         int spell_idx = -1,
                                         bool requires_concentration = false);
```

### 3c. `gui/battle_map.cpp` — definition signature + aggregate init
Find the definition signature (lines ~1125–1131) and change the final
`int slip_distance_feet) {` line to:
```cpp
                                   int slip_distance_feet,
                                   int spell_idx,
                                   bool requires_concentration) {
```
Then find the aggregate init (lines ~1145–1154):
```cpp
    ActiveTerrainEffect effect{
        id,
        std::move(name),
        std::move(indices),
        difficulty,
        turns_remaining,
        source_agent_idx,
        slip_save_dc,
        slip_distance_feet
    };
```
Change to (append two values):
```cpp
    ActiveTerrainEffect effect{
        id,
        std::move(name),
        std::move(indices),
        difficulty,
        turns_remaining,
        source_agent_idx,
        slip_save_dc,
        slip_distance_feet,
        spell_idx,
        requires_concentration
    };
```

### 3d. `gui/rpg_bindings.cpp` — bind new fields + new args
Find the `ActiveTerrainEffect` binding (lines 1579–1584). Change the last line
`        .def_readonly("source_agent_idx",  &ActiveTerrainEffect::source_agent_idx);`
(note the trailing `;`) to:
```cpp
        .def_readonly("source_agent_idx",  &ActiveTerrainEffect::source_agent_idx)
        .def_readonly("spell_idx",         &ActiveTerrainEffect::spell_idx)
        .def_readonly("requires_concentration", &ActiveTerrainEffect::requires_concentration);
```
Then find the `place_terrain_effect` binding (lines 1767–1772). After the line
`             py::arg("slip_save_dc") = 10, py::arg("slip_distance_feet") = 5,`
add:
```cpp
             py::arg("spell_idx") = -1, py::arg("requires_concentration") = false,
```

---

## Verify
Run the build, then the suite. Expected: **25 passed, 0 failed** (these changes add
fields/functions nothing reads yet, so no test behavior changes). If any C++ file
fails to compile, re-check the aggregate-init order in 3c and that every `.def`
chain still has exactly one terminating `;`. Do not modify tests.
