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

## Dead characters are getting turns in combat
**Severity:** High
**Status:** Fix landed (needs rebuild + retest)
**Description:** NPCs that dropped to 0 HP were being put into the unconscious / death-save state, so they kept getting turns (to roll death saves) instead of dying outright.

**Rule:** NPCs do **not** make death saves — they die immediately at 0 HP. Only **player characters** fall unconscious and roll death saves.

**Fix:** `CombatEngine::applyUnconscious` (combat.cpp) now branches on `stats.is_npc`: NPCs are marked `dead` at 0 HP (no death saves); PCs fall unconscious as before. The turn-advance loop (`main.py` ~1516) already skips agents flagged `dead`, so dead NPCs are now correctly passed over. `applyUnconscious` is the single chokepoint for all four 0-HP transition paths (melee, spell, maneuver, condition tick).

**Watch on retest:** any existing test that knocked an NPC to 0 and expected it to linger as `unconscious` will now see `dead` instead.
