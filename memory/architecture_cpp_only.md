---
name: All Core Logic in C++
description: Architectural rule: game logic lives in C++, Python is UI/I/O only
type: feedback
originSessionId: 788255f5-e211-4375-89e2-3bbd41e752f0
---
**Rule:** All core game logic must live in C++. Python handles only JSON loading, rendering, and user input.

**Why:** You need to run the game in "expert mode" for internal development and RL training. This requires:
- Deterministic game state that C++ owns completely
- No split logic between Python and C++
- Reproducible combat/spell mechanics for network training
- Ability to serialize/replay game states

**How to apply:** When implementing a feature, ask:
1. Is this game logic? (spell mechanics, movement, resources, combat rules) → C++
2. Is this I/O or rendering? (loading JSON, drawing UI, handling clicks) → Python

If you find yourself writing game logic in Python, move it to C++ and expose it via pybind11 bindings.

Examples:
- ✅ Spell availability checking → C++ (CombatEngine::availableCastableSpells)
- ✅ Resource decrement (uses, slots) → C++ (inside executeSpell)
- ✅ Movement pathfinding → C++ (BattleMap reachableCells)
- ❌ Loading agent JSON → Python (calls C++ to populate, but I/O is Python)
- ❌ Rendering map/spells → Python (calls C++ to query state, but rendering is Python)
