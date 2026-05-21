# Known Bugs

## Agents randomly drop weapons at unpredictable times
**Severity:** Medium  
**Status:** Unresolved  
**Description:** Occasionally (sporadically), when advancing turns and agents are ready to move, equipped weapons will appear on the ground as map items. The weapon is removed from inventory and placed at the agent's current cell. This happens without any explicit user action to drop the weapon.

**Steps to reproduce:**  
Unknown - occurs randomly during turn sequence, particularly after multiple End Turn actions.

**Example:**
- User ends turn multiple times through the initiative order
- When Drak's turn arrives and he attempts to move, his Longsword drops
- Weapon appears as an item on the map

**Last observed:** During normal turn progression without combat actions (just advancing turns)

**Notes:**
- Added traceback logging to `_drop_weapon()` in main.py to capture stack trace on next occurrence
- Likely related to unarmed strike restoration logic (`_unarmed_strike_original_weapons`) or turn cleanup code
- Happens sporadically and is difficult to reproduce consistently
