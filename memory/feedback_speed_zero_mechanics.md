---
name: speed-zero-oa-mechanics
description: Critical rule about Speed=0 conditions blocking both movement and opportunity attacks
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 961b62bf-211f-415e-beb7-f2fee35e4787
---

## Speed=0 and Opportunity Attack Mechanics

**Rule:** When a creature has Speed=0 (grappled, incapacitated, unconscious, paralyzed), they:
1. Cannot move
2. Cannot make opportunity attacks (reactions are blocked)

**Why:** D&D 5e creatures with Speed=0 are effectively immobilized and can't use reactions. This is a foundational rule that applies consistently.

**How to apply:** 
- Always check `canAgentMove()` BEFORE OA logic in Python
- When filtering threatening agents for OA checks, use `canAgentMove()` to exclude Speed=0 creatures
- This single check handles all conditions that reduce speed to 0, not just grappled

**Related:** [[grapple-mechanics-implementation]]

## Forced Movement vs Normal Movement

**Rule:** When a grappler moves and drags a grappled creature:
- Use direct position updates (bypass pathfinding)
- Don't validate destination against walls/terrain
- The creature has no choice - it's forced movement

**Why:** The creature is being dragged, not choosing to move. Pathfinding validation doesn't apply.

**How to apply:**
- Created `setAgentPosition()` method in BattleMap for direct updates
- Use this for grapple dragging, not `moveAgent()`
- Grapple dragging should maintain relative position or fall back to adjacent cells

## Movement Budget for Dragging

**Rule:** When dragging a grappled creature, double movement cost is deducted from the SAME movement type being used.

**Why:** If flying and dragging, use fly budget. If walking, use walk budget. Consistency with movement system.

**How to apply:**
- Check movement type in the drag cost validation
- Use the appropriate getter/spender based on MovementType enum
- This applies to Walk, Fly, Swim, and Burrow
