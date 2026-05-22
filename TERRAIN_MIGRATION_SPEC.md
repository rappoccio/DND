# Terrain → C++ Migration Spec

Goal: make **dynamic, combat-generated terrain** pure C++ state so a headless
`executeSpell()` loop produces identical terrain (Grease, Spike Growth, Spirit
Guardians, concentration difficult-terrain) without any Python. This is the
unblocker for moving `_advance_turn`, attack resolution, and OA into C++ later.

Principle (`memory/architecture_cpp_only.md`): game logic in C++, Python = I/O +
render + input. Decisions that today pop a GUI menu route through an injected
**CombatDecider** — GUI supplies a Python callback, RL supplies an auto policy.

## Decisions locked (2026-05-22)
- **Movement cost model:** keep the `TerrainDifficulty` enum. Snap any custom
  `multiplier` from spells.json to the nearest enum (≤0.25 → Quartered, else
  Halved; "Slipping" type → Slipping). No arbitrary `double` multiplier.
- **CombatDecider:** land the empty interface + nullable engine pointer now as
  scaffolding. Terrain itself needs no decisions, so it is wired but unused here.

## What stays in Python (do NOT move)
- **Static DM-painted terrain**: `_terrain_regions` entries shaped
  `{type, x, y, width, height, multiplier}` from the terrain editor, saved to
  `<map>_terrain.json`. This is map authoring I/O; it already pushes into the C++
  multiplier grid at load via `_apply_terrain_to_battle_map` → keep as-is.
- **Cosmetic render hints**: per-effect `color` and `hatch_pattern`. After
  migration these live in `_effect_meta`, keyed by C++ effect id, rebuilt from
  `bm.active_terrain_effects` (render-only; irrelevant headless).

## Root-cause notes (why this is needed)
1. `executeSpell` places **no terrain at all** today — it is done entirely in
   Python `_resolve_spell_cast_aoe` (main.py ~2873–2967).
2. **Determinism bug** main.py:2913 — slipping DEX saves use `random.randint`,
   bypassing the seeded engine RNG. Seed will not reproduce. Fixed by step 4.
3. **Latent bug** — `_apply_terrain_to_battle_map` (main.py:3820) only applies
   *pixel-rect* regions to the C++ multiplier; cell-based concentration regions
   are skipped, so spell difficult-terrain may not slow movement. Fixed by unifying.
4. `_dict_to_spell` (main.py:3215) **never sets `Spell.terrain_difficulty`** — the
   field exists but is always `Normal`. Terrain info lives only in the Python
   `_spell_metadata["terrain_effect"]` dict. Step 2 closes this gap.

---

## Step 1 — Port `_aoe_cells` to C++  [HAIKU]
**Files:** `gui/battle_map.hpp`, `gui/battle_map.cpp`
Prerequisite for placing terrain in C++. Port main.py `_aoe_cells` (2969–3040)
verbatim. Cone/Line use the caster origin as apex.

```cpp
// battle_map.hpp, public section near filterSpellCells:
[[nodiscard]] std::vector<Cell> aoeCells(Cell center, const Spell& spell,
                                         Cell casterOrigin) const;
```
Geometry (1 cell = 5 ft; cols_=gridCols(), rows_=gridRows()):
- **Sphere**: `r = radius/5`; include cell if `sqrt(dx²+dy²) <= r` from center.
- **Cone**: unit vector from casterOrigin→center; include if `dot>0 && plen<=r &&
  dot/plen >= 0.866` (30° half-angle).
- **Line**: unit vector casterOrigin→center; `along=p·u`, `perp=|p×u|`; include if
  `0<=along<=length/5 && perp<=width/10`.
- **Square/Rectangle**: `|c-cx|<=width/10 && |r-cy|<=length/10` around center.
- **Single/Multiple**: return `{center}` / empty (no AoE footprint).

Then Python `_aoe_cells`, `_draw_spell_aoe_preview` (3075), and `_filter_spell_cells_by_range_and_los`
(3044) call `bm.aoe_cells(...)` so GUI preview and headless use identical footprints.

## Step 2 — Spell carries its own terrain spec  [HAIKU]
**Files:** `gui/spell.hpp`, `gui/main.py` (`_dict_to_spell`, `_spell_to_dict`),
`gui/rpg_bindings.cpp`
`Spell` already has `terrain_difficulty` + `duration`. Add:
```cpp
int slip_save_dc{10};       // DEX save DC for Slipping terrain
int slip_distance_feet{5};  // feet moved before a save is required
```
Bind both (snake_case). In `_dict_to_spell`, parse the `terrain_effect` dict
(currently dropped) onto the Spell:
```python
te = d.get("terrain_effect")
if te:
    t = te.get("type", "")
    if t == "Slipping":
        s.terrain_difficulty = rpg.TerrainDifficulty.Slipping
        s.slip_save_dc       = int(te.get("slip_save_dc", 10))
        s.slip_distance_feet = int(te.get("slip_distance_feet", 5))
    else:
        m = float(te.get("multiplier", 0.5))
        s.terrain_difficulty = (rpg.TerrainDifficulty.Quartered if m <= 0.25
                                else rpg.TerrainDifficulty.Halved)
```
Keep `color`/`hatch_pattern`/`terrain_color` in `_spell_metadata` for rendering
(unchanged). `_spell_to_dict` round-trips terrain_difficulty back into `terrain_effect`
only if you need editor round-trip; otherwise leave metadata path as-is.

## Step 3 — Extend `ActiveTerrainEffect` + `placeTerrainEffect`  [HAIKU]
**Files:** `gui/battle_map.hpp`, `gui/battle_map.cpp`, `gui/rpg_bindings.cpp`
Add two fields (it already has `source_agent_idx`, `name`, slip params):
```cpp
int  spell_idx{-1};                 // index into caster's spell list (-1 = none)
bool requires_concentration{false}; // terrain ends when caster drops concentration
```
**Ordering note (matters):** `placeTerrainEffect` builds `ActiveTerrainEffect` by
positional aggregate init, so append the two new fields/params **last** (after the
slip params), not before — otherwise existing positional callers break:
```cpp
[[nodiscard]] int placeTerrainEffect(std::string name, std::vector<Cell> cells,
    TerrainDifficulty difficulty, int turns_remaining, int source_agent_idx,
    int slip_save_dc = 10, int slip_distance_feet = 5,
    int spell_idx = -1, bool requires_concentration = false);
```
Bind the two new fields read-only for rendering. `tickTerrainEffects(src)` /
`removeTerrainEffectsBySource(src)` already exist and now naturally cover
concentration terrain (it has turns + source) — no new tick code needed.

> Steps 1–3 are written up as exact, self-contained edits in
> **`HAIKU_TERRAIN_FOUNDATION.md`** (the file to hand Haiku). They are purely
> additive/behavior-neutral, so the suite stays 25/25 after them. Step 1 ports
> `aoeCells` to C++ but does NOT yet swap the Python `_aoe_cells` caller — that
> Python swap is folded into Step 7, after the Opus steps land.

## Step 4 — Place/replace terrain inside `executeSpell`  [OPUS]
**Files:** `gui/combat.hpp`, `gui/combat.cpp`, `gui/rpg_bindings.cpp`
Port the terrain block of `_resolve_spell_cast_aoe` (main.py 2873–2967) into
`executeSpell`, after damage/condition resolution, for AoE casts (action has
`aoe_col`/`aoe_row`). Logic:
1. If `spell.terrain_difficulty == Normal` → done.
2. `cells = filterSpellCells(aoeCells(center, spell, casterOrigin), ...)`.
3. `id = placeTerrainEffect(spell.name, cells, spell.terrain_difficulty,
   spell.duration, caster_idx, action.spell_idx, spell.requires_concentration,
   spell.slip_save_dc, spell.slip_distance_feet)`.
4. **Slipping only:** for each agent (≠caster) whose origin ∈ cells, roll a seeded
   DEX save with the engine RNG and set prone on failure — **replaces the
   `random.randint` determinism bug**:
   ```cpp
   int d20 = roll(20);
   int dexMod = (stats.dex - 10) / 2;          // floor div matches Python //
   if (d20 + dexMod < spell.slip_save_dc) cond.prone = true;
   ```
   Emit log lines via the attached MessageLogger (Python flushes them).
5. **Concentration replacement:** `executeSpell` already sets
   `concentration_replaced` / `prev_concentration_spell`. When it replaces, call
   `bm.removeTerrainEffectsBySource(caster_idx)` to drop the old spell's terrain —
   this retires the Python name-matching block (2929–2932).
6. Return new ids on `SpellResult`:
   ```cpp
   std::vector<int> terrain_effect_ids;  // SpellResult; bind read-only
   ```

## Step 5 — `dropConcentration` in C++  [OPUS]
**Files:** `gui/combat.hpp`, `gui/combat.cpp`, `gui/rpg_bindings.cpp`
```cpp
struct DropConcentrationResult {
    bool dropped = false;
    std::string spell_name;
    std::vector<int> removed_terrain_ids;
    std::vector<int> removed_spell_effect_ids;
    std::vector<int> removed_condition_ids;
};
[[nodiscard]] DropConcentrationResult dropConcentration(BattleMap& bm, int agent_idx);
```
Body: if not concentrating → `{}`. Else clear `concentrating`/`concentrating_on`,
`removeTerrainEffectsBySource(agent_idx)`, remove spell-effects + spell-applied
conditions whose caster == agent_idx, return ids + spell name for Python logging.
Call it from `executeAction`/`executeSpell` when a target hits `target_down`
(retires main.py 1852–1855, 2695 concentration-after-OA terrain removal).

## Step 6 — CombatDecider stub  [OPUS]
**Files:** `gui/combat.hpp`, `gui/rpg_bindings.cpp`
Land the interface + nullable engine pointer. No engine call sites yet (those come
with the Brutal-Strike/Reckless/OA menu migration).
```cpp
struct BrutalStrikeCtx { int attacker_idx; int target_idx; int level; };
struct RecklessCtx     { int attacker_idx; };
struct OACtx           { int attacker_idx; int target_idx; };
struct CombatDecider {
    virtual ~CombatDecider() = default;
    virtual std::vector<int> chooseBrutalStrike(const BrutalStrikeCtx&) { return {}; }
    virtual bool chooseReckless(const RecklessCtx&)                     { return false; }
    virtual int  chooseOAResponse(const OACtx&)                         { return -1; }
};
// CombatEngine:
void setDecider(CombatDecider* d) noexcept { decider_ = d; }
private: CombatDecider* decider_ = nullptr;  // null = built-in defaults
```
Bind with a `PyCombatDecider` trampoline (PYBIND11_OVERRIDE) so a Python subclass
can implement the menus; GUI sets `combat.set_decider(py_decider)`. Default
(nullptr / base methods) is the RL/headless auto-policy seed — fleshed out later.

## Step 7 — Strip Python spell-terrain code; render cache only  [HAIKU]
**File:** `gui/main.py`
- **Delete** `_cells_to_terrain_region` (3054), `_tick_concentration_terrain`
  (1491), and the terrain block of `_resolve_spell_cast_aoe` (2873–2967). Keep the
  action-economy lines (`action_used`/`bonus_used`) at the end.
- `_drop_concentration_for_agent` (1449) → thin wrapper:
  ```python
  res = self.combat.drop_concentration(self.bm, agent_idx)
  if res.dropped:
      self._sync_spell_effect_cache()
      self._combat_log_add(f"{agent_name} drops concentration on {res.spell_name or 'spell'}.")
  ```
  Remove the `_terrain_regions` filtering and manual condition/effect removal.
- `_advance_turn` (1373): drop the `_tick_concentration_terrain()` call; concentration
  terrain now ticks through the existing `tick_terrain_effects(new_idx)` path.
- Rendering: `_draw_concentration_terrain` (4315) keeps **only** its first loop
  (static pixel-rect terrain). Its second loop (concentration cells) is deleted —
  those effects now render through `_draw_temp_terrain_overlays` (4192), which
  already reads `bm.active_terrain_effects` + `_effect_meta[id]` for color. Add a
  hatch lookup there if hatching is still wanted.
- `_effect_meta` becomes a pure render cache: extend `_build_spell_effect_metadata`
  (or add a sibling) to populate color/hatch for `active_terrain_effects` by spell
  name from `all_spells`, keyed by `effect.id`.
- Delete the now-unused `_concentration_state` dict.

## Sequence
1 → 2 → 3 (Haiku, mechanical), then 4 → 5 → 6 (Opus, load-bearing), then 7 (Haiku).
Build/run owned by user (CLAUDE.md). After step 4, verify a seeded Grease cast
reproduces identical prone outcomes headless vs GUI.
