# Plan: beginTurn/executeTurn/endTurn Lifecycle + Agent Method Migration to CombatEngine

## Context

The current code has a muddled ownership model:
- `BattleMap` owns agent stats, conditions, weapons, and spells (via `PlacedAgent`), even though these are fundamentally combat concerns.
- `CombatEngine` only holds transient per-turn state (movement budgets, active effects).
- There is no explicit turn lifecycle — begin/execute/end logic is all jammed into `_advance_turn()` in Python.

**Goal:** Refactor so that `CombatEngine` owns all agent combat data (stats, conditions, weapons, spells) and provides explicit lifecycle hooks (beginTurn, executeTurn, endTurn). No observable behavior change yet.

**Design principle:** All new CombatEngine agent methods take `BattleMap&` as first parameter — consistent with the existing pattern (`executeAction(BattleMap&, ...)`, `executeSpell(BattleMap&, ...)`). Data continues to live in `PlacedAgent` for now; the methods move.

---

## Files to Modify

- `gui/combat.hpp` — add method declarations
- `gui/combat.cpp` — add method implementations (proxy delegates + lifecycle stubs)
- `gui/rpg_bindings.cpp` — move ~15 bindings from `BattleMap` block to `CombatEngine` block
- `gui/main.py` — update ~49 call sites from `self.bm.method()` to `self.combat.method()`
- `gui/battle_map.hpp` — remove declarations for migrated methods
- `gui/battle_map.cpp` — remove implementations for migrated methods

---

## Step 1: Add Agent Methods to CombatEngine (combat.hpp / combat.cpp)

All new methods delegate to the existing `BattleMap` implementation. This is purely structural — no logic changes.

### Agent Configuration
```cpp
void addAgentConfig(BattleMap& bm, AgentConfig cfg);        // → bm.addAgentConfig(cfg)
void applyAgentConfigs(BattleMap& bm);                      // → bm.applyAgentConfigs()
```

### Stats
```cpp
Agent::Stats getAgentStats(const BattleMap& bm, int idx) const noexcept;
void         setAgentStats(BattleMap& bm, int idx, Agent::Stats s) noexcept;
```

### Conditions
```cpp
Agent::Conditions getAgentConditions(const BattleMap& bm, int idx) const noexcept;
void              setAgentConditions(BattleMap& bm, int idx, const Agent::Conditions& c) noexcept;
```

### Weapons
```cpp
std::vector<Weapon> getAgentWeapons(const BattleMap& bm, int idx) const noexcept;
void                setAgentWeapons(BattleMap& bm, int idx, std::vector<Weapon> weapons) noexcept;
void                addWeaponToAgent(BattleMap& bm, int idx, Weapon w) noexcept;
void                removeWeaponFromAgent(BattleMap& bm, int idx, int weapon_idx) noexcept;
```

### Spells
```cpp
std::vector<Spell> getAgentSpells(const BattleMap& bm, int idx) const noexcept;
void               setAgentSpells(BattleMap& bm, int idx, std::vector<Spell> spells) noexcept;
```

---

## Step 2: Add Persistent Spell Effect Structures

### New: `ActiveSpellEffect` struct (battle_map.hpp)

A persistent AoE spell effect that occupies a set of cells and applies effects to agents in it.

```cpp
struct ActiveSpellEffect {
    int               caster_idx     = -1;
    int               spell_idx      = -1;   // into caster's spell list
    Spell             spell;                  // copy of the spell
    std::vector<Cell> cells;                  // cells occupied by this effect
    int               turns_remaining = 0;
    int               effect_id      = -1;   // unique ID for removal
};
```

Stored in `BattleMap` (it's spatial data):
```cpp
std::vector<ActiveSpellEffect> activeSpellEffects_;   // new member
int nextSpellEffectId_ = 0;
```

BattleMap gets accessors (spatial concern):
```cpp
int  addSpellEffect(ActiveSpellEffect effect);                   // returns effect_id
void removeSpellEffect(int effect_id);
const std::vector<ActiveSpellEffect>& activeSpellEffects() const;
std::vector<int> tickSpellEffects(int source_agent_idx);         // decrements, returns expired IDs
```

### New: Spell timing fields (spell.hpp)

Add two booleans to `Spell`:
```cpp
bool effects_on_begin_turn{true};   // apply damage/conditions at START of agent's turn in area
bool effects_on_end_turn{false};    // apply damage/conditions at END of agent's turn in area
```

Default: all spells fire at begin-of-turn. End-of-turn must be manually configured per spell (e.g., Black Tentacles restraint check fires at end of turn in 5e).

---

## Step 3: Add Lifecycle Methods to CombatEngine (combat.hpp / combat.cpp)

### beginTurn (expand existing)

Current `beginTurn()` only seeds movement budgets. Expand to also:
1. Seed movement budgets (already does this)
2. Reset per-turn conditions via `placed_agents[idx].agent->turn()` — currently done in Python
3. Reset leveled spell cast flag — currently done in Python
4. **NEW**: Loop through cells the agent occupies; for each `ActiveSpellEffect` in those cells where `effects_on_begin_turn == true`, apply damage/conditions to the agent

```cpp
void beginTurn(BattleMap& bm, int agent_idx);
```

### endTurn (new)

```cpp
void endTurn(BattleMap& bm, int agent_idx);
```

Does:
1. Loop through cells the agent occupies
2. For each `ActiveSpellEffect` where `effects_on_end_turn == true`, apply damage/conditions
3. (Initially no-op since no spells default to `effects_on_end_turn`)

### executeTurn (REMOVED)

**Decision:** executeTurn is an interactive experience with many user choices (movement, targeting, action selection, bonus actions, etc.). It's too complex to encapsulate in a single C++ method. Turn execution remains in Python's `_advance_turn()` and related UI handlers.

### Shared helper: applySpellEffect

```cpp
void applySpellEffect(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx);
```

Applies the spell's damage rolls (with resistance/vulnerability/immunity) and any conditions to the target. Reuses the existing per-type damage multiplier logic from `executeSpell()`.

---

## How beginTurn/endTurn Loop Through Cells

```cpp
void CombatEngine::beginTurn(BattleMap& bm, int agent_idx) {
    // 1. Movement budgets (existing)
    // 2. Conditions reset (absorb from Python)
    // 3. Spell flag reset (absorb from Python)

    // 4. Apply begin-of-turn spell effects
    const auto& agent = bm.placedAgents()[agent_idx];
    // Collect all cells this agent occupies (NxN footprint)
    auto agent_cells = bm.agentCells(agent_idx);

    for (const auto& effect : bm.activeSpellEffects()) {
        if (!effect.spell.effects_on_begin_turn) continue;
        if (effect.caster_idx == agent_idx) continue;  // don't hurt yourself (usually)
        for (const auto& cell : agent_cells) {
            if (std::find(effect.cells.begin(), effect.cells.end(), cell) != effect.cells.end()) {
                applySpellEffect(bm, effect, agent_idx);
                break;  // only apply once per effect even if multi-cell footprint
            }
        }
    }
}
```

---

## Step 3: Update rpg_bindings.cpp

Move these bindings from the `BattleMap` class block (~line 923–986) to the `CombatEngine` class block (~line 636):

| Python name | Moves to |
|---|---|
| `add_agent_config` | CombatEngine |
| `apply_agent_configs` | CombatEngine |
| `get_agent_stats` / `set_agent_stats` | CombatEngine |
| `get_agent_conditions` / `set_agent_conditions` | CombatEngine |
| `get_agent_weapons` / `set_agent_weapons` | CombatEngine |
| `add_weapon_to_agent` / `remove_weapon_from_agent` | CombatEngine |
| `get_agent_spells` / `set_agent_spells` | CombatEngine |
| `add_spell_to_agent` / `remove_spell_from_agent` | CombatEngine |
| `init_npc_spell_groups` | CombatEngine |
| `begin_turn` (existing) | update signature |
| `end_turn` (new) | CombatEngine |
| `execute_turn` (new) | CombatEngine |

New bindings all take `battle_map` as first arg (Python side), e.g.:
```python
combat.get_agent_stats(battle_map, idx)   # was: battle_map.get_agent_stats(idx)
```

---

## Step 4: Refactor _advance_turn() in main.py

Replace the inline logic with lifecycle method calls:

```python
def _advance_turn(self):
    prev_idx = self._current_agent_idx()

    # Find next living agent (skip dead)
    ...same skip-dead loop...

    # Round boundary (DM terrain, concentration tick)
    ...same round-wrap logic...

    new_idx = self._current_agent_idx()
    self.selected_idx = new_idx

    # End previous agent's turn
    self.combat.end_turn(self.bm, prev_idx)         # new call (no-op for now)

    # Reset Python-side action economy
    self.action_used = False
    self.bonus_used  = False
    ... etc ...

    # Begin new agent's turn (conditions reset + movement seed now happen in C++)
    self.combat.begin_turn(self.bm, new_idx)        # expanded: also resets conditions & spell flag

    # Remove these now-redundant lines (moved into C++ beginTurn):
    # self.bm.placed_agents[new_idx].turn()         ← absorbed into beginTurn
    # stats.reset_leveled_spell_cast_flag(); ...     ← absorbed into beginTurn

    # Tick terrain effects (stays in Python for now — terrain is BattleMap concern)
    expired = self.bm.tick_terrain_effects(new_idx)
    ...

    self._update_reach()
    self._update_attack_overlay()
```

### Call site updates (~49 sites in main.py)

```python
# Before                              # After
self.bm.get_agent_stats(idx)    →    self.combat.get_agent_stats(self.bm, idx)
self.bm.set_agent_stats(idx, s) →    self.combat.set_agent_stats(self.bm, idx, s)
self.bm.get_agent_weapons(idx)  →    self.combat.get_agent_weapons(self.bm, idx)
self.bm.set_agent_weapons(i, w) →    self.combat.set_agent_weapons(self.bm, i, w)
self.bm.get_agent_conditions(i) →    self.combat.get_agent_conditions(self.bm, i)
self.bm.set_agent_conditions(i) →    self.combat.set_agent_conditions(self.bm, i, c)
self.bm.get_agent_spells(idx)   →    self.combat.get_agent_spells(self.bm, idx)
self.bm.set_agent_spells(idx,s) →    self.combat.set_agent_spells(self.bm, idx, s)
self.bm.add_agent_config(cfg)   →    self.combat.add_agent_config(self.bm, cfg)
self.bm.apply_agent_configs()   →    self.combat.apply_agent_configs(self.bm)
```

---

## Step 5: Remove Migrated Methods from BattleMap

Remove declarations from `battle_map.hpp` and implementations from `battle_map.cpp` for all migrated methods. Spatial methods (`place_terrain_effect`, `tick_terrain_effects`, `placed_agents`, etc.) stay on BattleMap.

---

## Verification

1. Rebuild C++ extension: `cmake --build build && cmake --install build`
2. Run the game and confirm:
   - Combat starts, initiative rolls work
   - Attacks, spells, movement all function identically
   - Turn advancing works (combat log shows correct turn order)
   - Agent stats/HP update correctly in UI
   - Weapons and spells still load from JSON and function
3. Grep to confirm zero remaining `self.bm.get_agent_stats` / `self.bm.set_agent_stats` etc. calls in `main.py`

---

## What This Enables (Future Work)

Once this structure is in place:
- `endTurn()` can call `tickEffects()` to apply persistent AoE damage
- `beginTurn()` can check which terrain effects an agent is standing in and apply effects
- `executeTurn()` can be called during movement to check each cell for persistent effects
- The clean CombatEngine ownership makes adding the spell effects overlay straightforward
