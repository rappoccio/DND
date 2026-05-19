---
name: current-session-state
description: Active work and implementation progress
type: project
---

## Session Progress (May 14-19, 2026)

### Completed
- Fixed Docker build and noVNC connectivity
- Fixed visibility popup bug
- Implemented map panning with mouse wheel and arrow keys
- Updated memory with vision system and darkvision/truesight/devil's sight additions
- ✅ Thunderwave Push now working correctly (forceMoveAgent executing)
- ✅ Crowd Control Spells (stun, paralyze, held conditions)

### Forced Movement System - COMPLETE

All push/shove/knockback mechanics implemented. All logic in C++, Python for UI only.

**Completed Steps:**
1. ✅ Added `push_ft` field to `AttackCondition`
2. ✅ Implemented `BattleMap::forceMoveAgent()`
3. ✅ Added result structs (ShoveAction, ShoveResult, push_ft_applied)
4. ✅ Implemented `executeShove()` in combat.cpp
5. ✅ Handle "Push" condition in `executeAction()` and `executeSpell()`
6. ✅ rpg_bindings for ShoveAction/ShoveResult API
7. ✅ helpers.py parses `push_ft` from JSON
8. ✅ spells.json updated (Thunderwave push_ft: 10, Gust of Wind push_ft: 15)
9. ✅ Python UI - Shove buttons (bonus action) + Unarmed Strike menu:
   - "🔨 Shove (Push)" and "⬇ Shove (Prone)" in bonus action section
   - "👊 Unarmed" opens modal with Punch/Grapple/Push options (action)

---

## Architecture

**Flow:** 
- User clicks "Shove" → Python calls `executeShove(ShoveAction(...))` 
- C++ resolves contested Athletics check 
- If success: calls `BattleMap::forceMoveAgent()` 
- Result includes push_ft_applied and log message
- Python refreshes overlays (`_update_reach()`, `_update_attack_overlay()`)

**Key Design:**
- Push is represented as `AttackCondition` with `condition_name == "Push"` and `push_ft` value
- Works for weapons (proficiency required), spells (no proficiency needed)
- Unarmed strike uses same synthetic weapon system with proficiency always true
