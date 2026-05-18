---
name: Vision mechanics implementation design
description: Spatial partitioning approach for agent visibility computation
type: project
originSessionId: 5d137bad-b42c-4631-af40-e332b3ff2d1c
---
## Implementation Staging

### Phase 1: Obscuration Conditions (DO FIRST)
- Heavily Obscured: targets in this area cannot be seen at all (blocked)
- Partially Obscured: disadvantage on attack rolls/perception checks vs targets here
- **Design:** Terrain property (not agent condition)
  - Integrate into existing Light enum
  - Store as ActiveObscurationEffect in BattleMap
  - Add helper `getObscurationAtCell()` for visibility checks

**Implementation:**

**lighting.hpp - Update Light enum:**
```cpp
enum class Light {
    Bright,
    Dim,
    Darkness,
    PartiallyObscured,    // new
    HeavilyObscured,      // new
    MagicalDarkness       // new - stricter than HeavilyObscured (Darkness spell)
};
```

**Spells that create obscuration effects:**
- **MagicalDarkness:** Darkness (blocked except for Devil's Sight)
- **HeavilyObscured:** Fog Cloud, Sleet Storm, Cloudkill, Stinking Cloud, Incendiary Cloud, Storm of Vengeance
- **PartiallyObscured:** Insect Plague, Web
- **Hunger of Hadar:** Creates both damage area and obscuration (deferred - requires Cube geometry)

**MagicalDarkness Vision Exception:**
- Blocks all vision by default (even darkvision)
- Agents with Devil's Sight can see through it
- Add to Agent::Stats: `bool has_devil_sight{false};` (placeholder for feat system)
- Visibility check: if MagicalDarkness && !has_devil_sight → Blocked

**battle_map.hpp - Add to BattleMap:**
```cpp
struct ActiveObscurationEffect {
    int source_agent_idx;
    std::vector<Cell> cells;
    Light obscuration_level;  // PartiallyObscured or HeavilyObscured
    int turns_remaining;
};

std::vector<ActiveObscurationEffect> activeObscurationEffects_;
Light getObscurationAtCell(const Cell& c) const;
```

**Visibility check logic:**
- Check target's full footprint cell-by-cell
- For each cell, call `getObscurationAtCell()`
- If any cell is HeavilyObscured → visibility = Blocked
- If any cell is PartiallyObscured → visibility = PartiallyObscured
- Otherwise → continue with LOS check

**Obscuration Effect Duration & Management:**
- Obscuration effects have turns_remaining (duration tracked like other effects)
- Often linked to spell concentration (fog cloud, etc.)
- Need Python bindings:
  - `addObscurationEffect(battle_map, effect)`
  - `removeObscurationEffect(effect_id)`
- When concentration breaks, obscuration effect expires

**How Spells Create Obscuration:**
- Spell specifies geometry (Square, Cone, Line, Rectangle, etc.) + obscuration level
- Cells auto-calculated from geometry when spell is cast (like terrain effects)
- Example in spells.json:
  ```json
  {
    "name": "Fog Cloud",
    "obscuration": "PartiallyObscured",
    "geometry": "Square",
    "size": 20,
    "duration": 10,
    "concentration": true
  }
  ```

### Phase 2: Global Visibility System (THEN THIS)
- Recompute visibility at start of each agent's turn and before casting sight-dependent spells
- Global visibility structure: `Map<(AgentA, AgentB), VisibilityLevel>`
  - VisibilityLevel: Clear, PartiallyObscured, or HeavilyObscured (blocked)

### Phase 3: Advanced Vision (LATER)
- Invisibility condition (requires more work, defer)
- Vision types: Darkvision (darkness penalty reduced), Blindsight (ignores darkness), Truesight (sees through illusions)

## Design: On-Demand Visibility Computation with Spatial Partitioning

### Perception Range
- **Base:** pulled from agent stats (Wisdom or custom perception attribute)
- **Lighting modifiers:** darkness reduces range, bright light extends it
- **Darkvision:** regular darkness doesn't impede darkvision agents as much
- Implementation: leverage existing lighting system

### Trigger Points
Recompute visibility:
- At the beginning of each agent's turn
- When a spell is cast that has `requires_sight=true`

### Implementation

**spell.hpp:**
- Add `bool requires_sight{false};` field to Spell struct

**combat.hpp:**
- Add method: `void computeVisibility(BattleMap& bm, int agent_idx);`
- Recomputes which agents agent[idx] can currently see
- Stores results in global visibility map (reusable for spells requiring sight)

**combat.cpp - computeVisibility() logic:**
1. Determine agent's perception range (base from stats + lighting modifiers, darkvision adjustments)
2. Filter agents within Chebyshev distance ≤ perception_range
3. For each nearby agent, check: `LOS(A, B) && passesObscuration(A, B)`
4. Determine visibility level: Clear, PartiallyObscured, or HeavilyObscured (blocked)
5. Store in global visibility map: `Map<(AgentA, AgentB), VisibilityLevel>`

**rpg_bindings.cpp:**
- Bind `computeVisibility(battle_map, agent_idx)`
- Bind `spell.requires_sight` getter/setter

**main.py:**
- Call `self.combat.computeVisibility(self.bm, idx)` at start of agent turn in `beginTurn()`
- Before casting spell with `requires_sight=true`, call visibility computation
- Check spell target visibility before applying effects

**spells.json:**
- Add `"requires_sight": true` to spells: Hypnotic Pattern, Command, and other sight-dependent spells
- Most damage spells leave as false (auto-hit, don't require visibility)

## Benefits
- Avoids O(N²) pairwise computation; uses spatial filtering
- Only recomputes when needed (turn start + sight-dependent spells)
- Leverages existing lighting system for perception range
- Scales efficiently with agent count
