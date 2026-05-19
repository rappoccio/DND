# Plan: D&D 5e Lighting System

## Context

Implement D&D 5e visibility rules driven by a per-map `_lighting.json` file with spherical
light sources (torches, lanterns, spell effects). Light levels affect targeting and impose
disadvantage/blindness. The C++ layer owns all game-logic; Python handles JSON loading, UI
rendering, and user input.

**Future features (architecture must not block these):**
- Invisible mobs until they have LOS in adequately lit regions (vision-type dependent)
- Interactive lighting: players can extinguish/light sources, open/close doors affecting light
- Dynamic light following agents (held torches, light spells on moving creatures)

### Visibility Table (from spec)

| Light Condition  | Normal Vision        | Darkvision (<range)   | Truesight        | Devil's Sight (<120ft) |
|-----------------|----------------------|-----------------------|------------------|------------------------|
| Bright Light    | Can see              | Can see               | Can see          | Can see                |
| Dim Light       | Can see (disadv PER) | Can see               | Can see          | Can see (disadv PER)   |
| Darkness        | Blinded              | Can see (disadv PER)  | Can see          | Can see                |
| Magical Darkness| Blinded              | Blinded               | Can see          | Can see                |

`canSee()` returns false = "Blinded" (cannot target for attack). Disadvantage on PER checks is
a flag returned separately so attack-roll code can apply it.

---

## Current State

Already in the codebase:
- `LightLevel` enum (BrightLight=0, DimLight=1, Darkness=2, MagicalDarkness=3) — **battle_map.hpp**
- `lightLevel_` flat vector (size rows×cols, initialized to BrightLight) — **battle_map.hpp**
- `getLightLevel()`, `setLightLevel()`, `resetLightLevels()` — **battle_map.hpp / .cpp**
- `canSee(obs_origin, obs_size, darkvision_ft, tgt_origin, tgt_size)` — basic darkvision only
- `darkvision_range` in `Agent::Stats` — **agent.hpp:126**
- Python-side terrain region loading pattern — `_load_terrain()` / `_apply_pixel_terrain()` in **main.py**

---

## C++ Changes

### 1. `Agent::Stats` (`agent.hpp`)

Add two vision fields after `darkvision_range`:
```cpp
int truesight_range{0};   // feet; 0 = none. Sees normally in all light including magical darkness
int devilssight_range{0}; // feet; 0 = none. Sees normally in darkness + magical darkness
```

### 2. `BattleMap` — base lighting storage + active effects (`battle_map.hpp`)

Add parallel to terrain system:

```cpp
// Per-cell base light level loaded from _lighting.json (static; never changes at runtime).
// Defaults to BrightLight for all cells. "Brightest wins" against active effects.
std::vector<LightLevel> baseLightLevel_;   // size rows_*cols_

// Dynamic light effects (spells, DM torches) — same pattern as ActiveTerrainEffect
struct ActiveLightEffect {
    int              id;
    std::string      name;
    std::vector<int> cell_indices;      // flat: row*cols_ + col
    LightLevel       light_level;
    int              turns_remaining;   // -1 = permanent
    int              source_agent_idx;  // -1 = DM-placed
};
std::vector<ActiveLightEffect> activeLightEffects_;
int nextLightEffectId_{0};
```

New public methods to declare:
```cpp
// Load base lighting from JSON (pixel-space spherical sources → grid cells).
// Called once after analyzeGrid(). Sets baseLightLevel_ to default_light, then applies
// bright/dim radii from light sources. Calls updateLighting().
void applyBaseLighting(LightLevel default_light,
                       const std::vector<std::tuple<int,int,int,int>>& sources) noexcept;
//  ↑  each tuple: (pixel_x, pixel_y, bright_radius_ft, dim_radius_ft)

// Recompute lightLevel_  from baseLightLevel_ + activeLightEffects_.
// "Brightest wins" for normal effects; MagicalDarkness always overrides.
void updateLighting() noexcept;

// Dynamic effects (mirrors terrain methods):
[[nodiscard]] int  placeLightEffect(std::string name, std::vector<Cell> cells,
                                    LightLevel level, int turns_remaining,
                                    int source_agent_idx) noexcept;
std::vector<int>   tickLightEffects(int source_agent_idx) noexcept;   // returns removed ids
std::vector<int>   tickDmLightEffects() noexcept;
std::vector<int>   removeLightEffectsBySource(int source_agent_idx) noexcept;
void               removeLightEffect(int id) noexcept;
void               clearLightEffects() noexcept;
[[nodiscard]] bool hasActiveLightEffects() const noexcept;
[[nodiscard]] const std::vector<ActiveLightEffect>& activeLightEffects() const noexcept;

// Updated canSee — adds truesight and devil's sight
// Returns false = observer is blinded (cannot target).
[[nodiscard]] bool canSee(Cell obs_origin, int obs_size,
                          int darkvision_ft, int truesight_ft, int devilssight_ft,
                          Cell tgt_origin, int tgt_size) const noexcept;

// Returns true if observer has disadvantage on perception vs target
// (dim light with normal/devil's sight, darkness with darkvision).
[[nodiscard]] bool perceptionDisadvantage(Cell obs_origin, int obs_size,
                                          int darkvision_ft, int truesight_ft, int devilssight_ft,
                                          Cell tgt_origin, int tgt_size) const noexcept;
```

### 3. `battle_map.cpp` — implementations

**`applyBaseLighting`**: 
1. Initialize all cells to `baseLightLevel_ = default_light`
2. For each light source (pixel_x, pixel_y, bright_radius_ft, dim_radius_ft):
   - Convert pixel coords to grid cells using `cellPixelSize_` and `gridOriginPx_`
   - Convert feet to cell units: `bright_cells = bright_radius_ft / 5`, `dim_cells = dim_radius_ft / 5`
   - For all cells within Chebyshev distance `bright_cells` from source: `baseLightLevel_[idx] = min(current, BrightLight)`
   - For all cells within Chebyshev distance `dim_cells` from source (but outside `bright_cells`): `baseLightLevel_[idx] = min(current, DimLight)`
   - Use Chebyshev distance (max of abs differences) to match grid-based movement

**`updateLighting()`**:
```cpp
// Step 1: reset to base
lightLevel_ = baseLightLevel_;
// Step 2: apply normal light effects (brightest wins = std::min)
for (auto& eff : activeLightEffects_) {
    if (eff.light_level == LightLevel::MagicalDarkness) continue;
    for (int idx : eff.cell_indices)
        lightLevel_[idx] = std::min(lightLevel_[idx], eff.light_level);
}
// Step 3: apply magical darkness (always wins = override)
for (auto& eff : activeLightEffects_) {
    if (eff.light_level != LightLevel::MagicalDarkness) continue;
    for (int idx : eff.cell_indices)
        lightLevel_[idx] = LightLevel::MagicalDarkness;
}
```

**Updated `canSee()`** (implement full table):
```
effective_light = darkest cell in target footprint
if truesight_ft > 0 && dist_ft <= truesight_ft: return true (all conditions)
if devilssight_ft > 0 && dist_ft <= devilssight_ft && effective_light != BrightLight && effective_light != DimLight:
    → darkness & magical darkness: return true
BrightLight, DimLight → return true (all)
Darkness → darkvision_ft > 0 && dist_ft <= darkvision_ft
MagicalDarkness → false (darkvision blocked)
```

**`perceptionDisadvantage()`**: returns true when:
- `effective_light == DimLight` AND observer has no truesight (normal or devil's sight)
- `effective_light == Darkness` AND observer uses darkvision (not truesight)

**`analyzeGrid()`**: initialize `baseLightLevel_` same size as `lightLevel_`, filled with BrightLight.

### 4. `rpg_bindings.cpp` — new bindings

| New binding | Notes |
|-------------|-------|
| `Stats::truesight_range` | `def_readwrite` |
| `Stats::devilssight_range` | `def_readwrite` |
| `ActiveLightEffect` struct | `.id`, `.name`, `.cell_indices`, `.light_level`, `.turns_remaining`, `.source_agent_idx` |
| `bm.apply_base_lighting(default_level, sources)` | sources: `list[tuple[int,int,int,int]]` (x, y, bright_radius_ft, dim_radius_ft) |
| `bm.update_lighting()` | void |
| `bm.place_light_effect(name, cells, level, turns, src_idx)` | → int id |
| `bm.tick_light_effects(src_idx)` | → list[int] |
| `bm.tick_dm_light_effects()` | → list[int] |
| `bm.remove_light_effects_by_source(src_idx)` | → list[int] |
| `bm.remove_light_effect(id)` | void |
| `bm.clear_light_effects()` | void |
| `bm.has_active_light_effects()` | → bool |
| `bm.active_light_effects` | read-only property |
| `bm.can_see(obs_origin, obs_size, dv_ft, ts_ft, ds_ft, tgt_origin, tgt_size)` | updated signature |
| `bm.perception_disadvantage(obs_origin, obs_size, dv_ft, ts_ft, ds_ft, tgt_origin, tgt_size)` | → bool |

---

## JSON Format (`<mapname>_lighting.json`)

```json
{
  "default_light": "Darkness",
  "light_sources": [
    {
      "name": "Torch - Main Hall",
      "x": 200, "y": 300,
      "bright_radius": 20,
      "dim_radius": 40
    },
    {
      "name": "Torch - North Corner",
      "x": 100, "y": 150,
      "bright_radius": 20,
      "dim_radius": 40
    }
  ]
}
```

`"default_light"` sets the entire map's base level (BrightLight for outdoors, Darkness for
dungeons). Then light_sources are applied with:
- `bright_radius` (feet): cells within this distance get BrightLight
- `dim_radius` (feet): cells within this distance (but outside bright_radius) get DimLight

Coordinates are pixel-space (top-left of map image = 0,0).

---

## Python Changes (`main.py`)

**New `_load_lighting()` method** (called in `_load_all()` alongside `_load_terrain()`):
```python
def _load_lighting(self):
    path = self._lighting_path()  # <mapname>_lighting.json
    if not os.path.exists(path):
        return
    data = json.load(open(path))
    default_str = data.get("default_light", "BrightLight")
    default_lvl = _parse_light_level(default_str)
    sources = []
    for src in data.get("light_sources", []):
        sources.append((int(src["x"]), int(src["y"]), 
                       int(src.get("bright_radius", 20)),
                       int(src.get("dim_radius", 40))))
    self.bm.apply_base_lighting(default_lvl, sources)
```

Add helper `_parse_light_level(s)` → `rpg.LightLevel` (mirrors `_parse_magic_damage`).

**Update all `bm.can_see()` call sites** to pass `truesight_ft` and `devilssight_ft` from agent stats.

**Add GUI lighting visualization button** (next to terrain button):
- Toggles visibility of light level overlay
- BrightLight: 0% opacity (fully transparent)
- DimLight: 50% opacity (semi-transparent grey)
- Darkness: 90% opacity (nearly opaque dark grey)
- MagicalDarkness: 100% opacity (fully opaque black)
- Allows DM to see the lighting map while editing/running combat

---

**Future interactive lighting**: Currently light sources are static from JSON. The architecture
supports adding `placeLightEffect()` to dynamically create/remove light (e.g., extinguishing
torches, opening/closing light-blocking doors, spells). This design does not block that feature.

---

## Files to Modify

| File | Change |
|------|--------|
| `gui/agent.hpp` | Add `truesight_range`, `devilssight_range` to `Stats` |
| `gui/battle_map.hpp` | Add `baseLightLevel_`, `activeLightEffects_`, `ActiveLightEffect`; declare all new methods; update `canSee()` signature |
| `gui/battle_map.cpp` | Implement `applyBaseLighting`, `updateLighting`, `canSee` (updated), `perceptionDisadvantage`, light effect CRUD, init `baseLightLevel_` in `analyzeGrid()` |
| `gui/rpg_bindings.cpp` | Expose all new bindings; update `can_see` binding signature |
| `gui/main.py` | Add `_load_lighting()`, `_lighting_path()`, `_parse_light_level()`; update `can_see` calls; add cell light-level tinting to renderer |

---

## Order of Execution

1. `agent.hpp` — add `truesight_range`, `devilssight_range`
2. `battle_map.hpp` — add `baseLightLevel_`, `ActiveLightEffect`, `activeLightEffects_`; declare all new methods; update `canSee` signature
3. `battle_map.cpp` — implement everything; update `canSee`; init `baseLightLevel_` in `analyzeGrid()`
4. `rpg_bindings.cpp` — add all bindings; update `can_see` binding
5. `main.py` — `_load_lighting()`, `_lighting_path()`, `_parse_light_level()`; update call sites; add tinting

---

## Verification

```python
# After build:
import rpg_battle_map as rpg

# Apply base lighting: dungeon (dark), one torch at pixel (200, 300) with 20ft bright, 40ft dim
bm.apply_base_lighting(rpg.LightLevel.Darkness, [(200, 300, 20, 40)])
# Cell in bright radius should be BrightLight
# Cell outside dim radius should be Darkness
# (exact cells depend on cellPixelSize_ and grid geometry)

# canSee: normal vision in darkness → blinded
assert not bm.can_see(obs_origin, 1, 0, 0, 0, tgt_origin, 1)  # no darkvision/truesight
# canSee: darkvision in darkness within range
assert bm.can_see(obs_origin, 1, 60, 0, 0, tgt_origin, 1)  # darkvision 60ft

# perceptionDisadvantage: darkvision in darkness → disadvantage
assert bm.perception_disadvantage(obs_origin, 1, 60, 0, 0, tgt_origin, 1)

# Load lighting file
app._load_lighting()  # loads <mapname>_lighting.json if exists
```
