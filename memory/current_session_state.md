---
name: current-session-state
description: Active work and implementation progress
type: project
---

## Session Progress (May 14-15, 2026)

### Completed
- Fixed Docker build and noVNC connectivity
- Fixed visibility popup bug
- Implemented map panning with mouse wheel and arrow keys
- Updated memory with vision system and darkvision/truesight/devil's sight additions

### In Progress: Forced Movement System

Implementing push/shove/knockback mechanics. All logic in C++, Python for UI only.

**Completed Steps:**
1. ✅ Added `push_ft` field to `AttackCondition` (condition.hpp)
2. ✅ Implemented `BattleMap::forceMoveAgent()` (battle_map.hpp/cpp)
   - Moves agent away from attacker by computing direction vector
   - Stops at walls, map edge
   - Returns cells actually moved
   - Diagonal fallback to orthogonal if blocked

3. ✅ Added result fields and Shove types (combat.hpp)
   - Added `push_ft_applied` to `AttackResult` and `SpellTargetResult`
   - Added `ShoveAction` and `ShoveResult` structs
   - Declared `executeShove()` method

**Next Steps:**
4. Implement `executeShove()` in combat.cpp
   - Contested Athletics check: attacker vs target (Acrobatics/Athletics)
   - On success: knock prone OR push 5ft (based on flag)
5. Handle "Push" condition in `executeAction()` and `executeSpell()`
6. Add rpg_bindings for all new C++ API
7. Update helpers.py to parse `push_ft` from JSON
8. Update spells.json (Thunderwave, Gust of Wind)
9. Python UI: Shove button (bonus action), unarmed strike button

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
