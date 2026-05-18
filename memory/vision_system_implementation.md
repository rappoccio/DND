---
name: Vision System Implementation Status
description: Current state of vision mechanics implementation - Phases 1, 2, and 3 complete
type: project
---

## Completed Work

### Phase 1: Obscuration Conditions ✅ DONE
- LightLevel enum updated with PartiallyObscured, HeavilyObscured, MagicalDarkness
- ActiveObscurationEffect struct implemented for managing spell-created darkness/fog areas
- All obscuration management methods bound to Python

### Phase 2: Global Visibility System ✅ DONE
- VisibilityLevel enum: Clear, PartiallyObscured, Blocked
- computeVisibility() calculates which agents a given agent can see each turn
- getVisibility() returns cached visibility level between two agents
- Debug UI button "Show Visible Targets" displays visibility results in combat log
- requires_sight field added to spells for visibility-dependent spell casting

### Phase 3: Advanced Vision Types ✅ DONE (May 2026)
- **Darkvision**: Agents with darkvision_range stat can see in darkness (reduced penalty)
- **Truesight**: Agents with truesight_range stat see through all darkness and illusions
- **Devil's Sight**: Blocks MagicalDarkness obscuration (allows seeing through Darkness spell)
- **Blindsight**: Agents with blindsight_range can sense without sight
- Vision stats stored in agent.stats: darkvision_range, truesight_range, devilssight_range, blindsight_range

## Vision Configuration in agents.json

```json
"stats": {
  "str": 16,
  "darkvision_range": 60,
  "truesight_range": 0,
  "devilssight_range": 0,
  "blindsight_range": 0
}
```

## Next Steps

1. Mark requires_sight=true on spells like Hypnotic Pattern, Command, etc.
2. Implement spell casting checks to reject blocked targets
3. Test obscuration effects (fog clouds, darkness spells) with various vision types
