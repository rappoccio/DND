---
name: plan_arcane_ward
description: Abjurer L3 Arcane Ward implementation - temp HP charging via spells and bonus action
metadata:
  type: project
---

# Plan: Arcane Ward (Abjurer L3)

**Status:** Pending

## Overview

Arcane Ward is temporary HP that charges when the Abjurer casts abjuration spells or manually expends spell slots as a bonus action. It's capped at `2 * wizard_level + INT_modifier`.

## D&D 5e Rules

1. **Initialization:** On long rest, Ward = wizard level (minimum 1)
2. **Maximum:** 2 × wizard level + INT modifier
3. **Charging - Automatic:** When casting an abjuration spell, Ward gains 2 × spell slot level (capped at max)
4. **Charging - Manual:** As bonus action, expend spell slot to gain 2 × spell slot level (capped at max)
5. **Display:** Show as temp HP

## Implementation Phases

### Phase 1: Long Rest Initialization
**Files:** `combat.cpp`

```cpp
// In apply_long_rest(), after restoring resources:
if (agent is Abjurer AND char_level >= 3) {
    stats.temp_hp = char_level;  // Initialize ward
}
```

**Notes:**
- Max is calculated on-the-fly when needed: `2 * level + int_mod`
- No separate resource needed; reuse temp_hp field

### Phase 2: Auto-charging on Abjuration Spell Cast
**Files:** `combat.cpp`

When a spell is cast:
1. Check if `spell.school == Spell::School::Abjuration`
2. Check if caster is Abjurer L3+
3. Calculate: `int max_ward = 2 * char_level + int_mod`
4. Add to temp HP: `temp_hp = min(temp_hp + (2 * spell_slot_level), max_ward)`
5. Log: "{name} Arcane Ward charged: +{amount} HP ({current}/{max})"

**Integration Point:**
- In the spell effect application code where we determine spell type
- Should happen after spell is confirmed to hit (if attack roll needed)

### Phase 3: Bonus Action Charging UI
**Files:** `main.py`, `dialogs.py`

#### Button Creation & Display
- Create `btn_cbt_charge_arcane_ward` button
- Show in Bonus Action section only if:
  - Agent is Abjurer L3+
  - Agent has active Arcane Ward (temp_hp > 0)
  - Bonus action not used this turn

#### Spell Slot Selection GUI
- Similar to Portent Die context menu
- Display available spell slots with level and effect:
  ```
  Level 1 Slot (+2 HP)
  Level 2 Slot (+4 HP)
  Level 3 Slot (+6 HP)
  ...
  ```
- Show current/max ward HP in header
- Grayed out slots that would exceed max

#### Click Handler
1. Call `self.combat.expend_spell_slot(bm, agent_idx, slot_level)`
2. Update temp_hp: `temp_hp = min(temp_hp + (2 * slot_level), max_ward)`
3. Log: "{name} expends Level {N} slot, Arcane Ward now {current}/{max}"
4. Mark bonus_used = True
5. Update UI

### Phase 4: Display Integration
**Files:** `main.py`

- Temp HP already displays in combat panel
- No changes needed; Ward shows as normal temp HP
- Optional: Add label "Arcane Ward" next to temp HP number for clarity

## Implementation Order

1. **Long Rest Init** (simplest, C++ only)
   - Modify `apply_long_rest()` 
   - Test: Create Abjurer, long rest, verify temp_hp = level

2. **Auto-charging** (C++ spell casting hook)
   - Find where spell type is determined
   - Add abjuration check and temp_hp charging
   - Test: Cast abjuration spell, verify ward charges

3. **Bonus Action UI** (Python + C++)
   - Add button and spell slot selection GUI
   - Add `expend_spell_slot()` method to C++
   - Test: Click button, select slot, verify ward charges and slot is consumed

## Key Details

- **Max calculation:** `2 * char_level + (int - 10) / 2`
- **Spell slot level:** Already tracked in Spell struct as `level`
- **Temp HP capping:** Use `min(current + amount, max)` to prevent over-charging
- **Slot expending:** Automatic through existing spell slot system; no manual tracking needed

## Testing

Scenarios to cover:
- [ ] Long rest initializes ward to char_level
- [ ] Auto-charging on different abjuration spell levels (L1, L2, L3)
- [ ] Ward caps at max (doesn't exceed 2×level + INT mod)
- [ ] Manual charging via bonus action
- [ ] Multiple charges stack correctly
- [ ] Temp HP display shows ward value
- [ ] Bonus action used when charging manually
- [ ] Abjurers below L3 don't get ward

## Files to Modify

- `combat.cpp` - long rest init, auto-charging logic, spell slot expending
- `combat.hpp` - if new methods needed
- `main.py` - button creation, display, UI for slot selection
- `dialogs.py` - spell slot selection GUI (if complex enough for separate class)
