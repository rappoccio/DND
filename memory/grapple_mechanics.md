---
name: grapple-mechanics-implementation
description: "Complete D&D 5e grapple mechanics implementation with movement, OAs, and dragging"
metadata: 
  node_type: memory
  type: project
  originSessionId: 961b62bf-211f-415e-beb7-f2fee35e4787
---

## Grapple Mechanics Implementation

**Status:** Complete and working

### Core Features Implemented

1. **Grapple Initiation** (`executeGrapple()`)
   - Contested Athletics check: attacker STR+Prof vs defender max(Athletics, Acrobatics)
   - Requires adjacency (within 1 cell)
   - Sets grappled condition on target with escape DC = 10 + attacker's Athletics
   - Target can't be self

2. **Grapple Escape** (`executeGrappleEscape()`)
   - Best of STR (Athletics) or DEX (Acrobatics) vs escape DC
   - Clears grappled condition on success
   - Only valid if actually grappled

3. **Grappled Condition Effects**
   - Speed = 0 (handled by `canAgentMove()`)
   - Can't move (checked before movement)
   - Can't make opportunity attacks (filtered in OA logic)
   - Tracks grappler_idx and escape_dc

4. **Grapple Dragging** (`moveAgent()` in combat.cpp)
   - When grappler moves, grappled creature is forced along
   - Maintains relative position (e.g., 1x2 block configuration)
   - Falls back to adjacent unoccupied cells if original offset blocked
   - Movement cost is doubled: grappler pays for both themselves and dragged creature
   - Drag cost deducted from correct movement budget (walk/fly/swim/burrow)
   - Grapple auto-ends if grappler incapacitated or moves out of range (5ft)

### Key Files Modified

**C++ Implementation:**
- `combat.hpp`: Added grapple function declarations and result structs
- `combat.cpp`: Implemented grapple logic, escape logic, dragging, and movement cost checks
- `battle_map.hpp`: Added `setAgentPosition()` method for direct position updates
- `battle_map.cpp`: Implemented `setAgentPosition()` for grapple dragging
- `agent.hpp`: Added grapple fields to Conditions struct (grappled, grappler_idx, grapple_escape_dc, grapple_range_ft)

**Python Bindings:**
- `rpg_bindings.cpp`: Added bindings for GrappleAction, GrappleResult, GrappleEscapeResult, and grapple methods

**Python UI:**
- `main.py`: OA filtering to exclude Speed=0 creatures, grapple button/badge integration
- `test_grapple.py`: 10 comprehensive test cases including new drag test

### Critical Fixes Applied

1. **Dragging Position Update**
   - Initial implementation used `bm.moveAgent()` which failed validation
   - Fixed by implementing `setAgentPosition()` for direct position updates
   - No pathfinding validation for forced movement

2. **Movement Budget for Dragging**
   - Initially only checked walk budget regardless of movement type
   - Fixed to check/spend correct budget: Walk, Fly, Swim, or Burrow

3. **Opportunity Attack Logic**
   - OAs were triggering against grappled creatures (Speed=0)
   - Fixed by filtering threatening agents: only include those with `can_agent_move() == true`
   - This applies the general rule: Speed=0 creatures can't make OAs

### Architectural Decisions

- **Game mechanics in C++**: Grapple dragging, movement validation, and cost calculations all in C++
- **UI layer**: Python calls C++ functions, displays results, handles OA queue
- **Speed=0 principle**: Creatures with Speed=0 (grappled, incapacitated, unconscious, paralyzed) can't move AND can't make OAs
- **Forced movement**: Direct position updates bypass pathfinding validation (creature has no choice)

### Testing

- 10 unit tests in `test_grapple.py` covering initialization, success/failure, escape, movement restrictions, and dragging
- Test verifies relative position maintenance, adjacency, and condition persistence through forced movement
