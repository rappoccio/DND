---
name: session_subclass_rage_portent
description: "Subclass selection UI, Rage button, and Portent Dice advantage/disadvantage fixes"
metadata: 
  node_type: memory
  type: project
  originSessionId: 900d552e-34ec-4fad-b01c-4a72cc126da9
---

# Session: Subclass Selection, Rage Button, Portent Dice Fixes

**Date:** 2026-05-20

## What was completed

### 1. Subclass Selection UI (dialogs.py)
- Added `_subclass_name` and `_subclass_rects` fields to track subclass selection
- Added `_get_available_subclasses()` method that returns subclasses per class:
  - Barbarian: Berserker, WildHeart, WorldTree, Zealot
  - Wizard: Abjurer, Diviner, Evoker, Illusionist
- Added left/right navigation buttons for subclass selection in the stats dialog (appears below class selector)
- Subclass resets to "NONE" when class is changed
- Added `_display_subclass_name()` helper to show "None" instead of "NONE" in UI
- Updated `_confirm()` to pass selected subclass to callback

### 2. Class Resource Initialization (main.py)
- Added `stats.initialize_class_resources()` calls in THREE places:
  1. When first creating an agent (`_place_agent_config()`)
  2. When updating stats via dialog (`_on_stats_ok()`)
  3. When loading saved agents (`_load_scenario()`)
- **CRITICAL:** Subclass must be set BEFORE `initialize_class_resources()` because resource initialization checks subclass to determine which features to create (e.g., Portent Dice only for Diviners)

### 3. Rage Bonus Action Button (main.py)
- Created `btn_cbt_rage` button with reddish styling
- Display logic: button appears only when agent is Barbarian, not raging, and has ≥1 Rage use
- Click handler: calls `self.combat.activate_rage()` and marks bonus action as used
- Located in Bonus Action section below other conditional buttons

### 4. Subclass Persistence (main.py)
- Added save: `agent_barbarian_subclass` and `agent_wizard_subclass` to JSON
- Added load: restore subclasses from JSON BEFORE calling `initialize_class_resources()`
- Ensures subclass selections persist when saving/loading scenarios

### 5. Portent Dice + Advantage/Disadvantage Fix (combat.cpp)
- **Problem:** When using Portent Die with disadvantage, the portent value was being consumed on the first d20 roll, leaving the second roll as random
- **Solution:** Applied Portent Die AFTER advantage/disadvantage logic instead of during
- Updated THREE methods:
  1. `rollToHit()` - weapon attacks
  2. `rollAdvantage()` - spell attacks with advantage
  3. `rollDisadvantage()` - spell attacks with disadvantage
- Flow: Extract pending portent → roll normally → apply portent to final result

## Key Implementation Details

### Subclass Enum Names (Python)
- Barbarian: "NONE", "Berserker", "WildHeart", "WorldTree", "Zealot"
- Wizard: "NONE", "Abjurer", "Diviner", "Evoker", "Illusionist"
- Used internally; displayed as "None" in UI

### Resource Initialization Order
```python
# WRONG - resources won't include subclass-specific features
stats.set_class_level(...)
stats.initialize_class_resources(...)
stats.wizard_subclass = ...  # Too late!

# RIGHT - subclass available when resources are created
stats.set_class_level(...)
stats.wizard_subclass = ...  # Set first
stats.initialize_class_resources(...)  # Will check subclass
```

### Portent Die with Rolls
- All three roll methods follow same pattern:
  - Save `pending_portent_die_` value
  - Clear the flag so subsequent `roll()` calls don't use it
  - Execute normal advantage/disadvantage logic
  - Apply portent value to final result
  - Log the replacement

## Testing Notes

- Portent Dice works without advantage/disadvantage ✓
- Portent Dice works with disadvantage (after fix) ✓
- Subclass persists after save/load ✓
- Rage button appears and functions for Barbarians ✓
- Diviner Wizard features initialize after long rest ✓

## Files Modified

- `dialogs.py` - Subclass selection UI
- `main.py` - Resource initialization, Rage button, subclass save/load
- `combat.cpp` - Portent dice advantage/disadvantage interaction
