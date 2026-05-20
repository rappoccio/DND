---
name: bug-push-not-working
description: Bug debugging - Thunderwave Push condition not executing forced movement
metadata:
  type: project
---

## Status: ✅ RESOLVED (May 19, 2026)

Thunderwave spell now correctly applies Push condition and executes forced movement.

### What Was Fixed
- forceMoveAgent() now returns correct cells moved
- Fire Elemental (and other targets) positioned correctly after Thunderwave
- Push condition applies on failed save

### Recent Changes Made
1. Fixed requires_save logic: set based on whether condition has save_ability in JSON
2. Cleaned up condition application logic in executeSpell()
3. For Save spells, reuse tr.saved instead of rolling new saves

### What to Do When You Resume

**IMMEDIATE NEXT STEP**: Run Thunderwave and look for `[APPLY]` log message showing:
```
[APPLY] Applying condition 'Push' to agent[3], requires_save=true, push_ft=?
```

**Two possibilities**:
1. **If push_ft=0**: Value lost between Python and C++. Check Python binding for AttackCondition.push_ft or JSON parsing in helpers.py
2. **If push_ft=10**: Check why forceMoveAgent() returns 0 despite valid push_ft. Look at:
   - Is caster position correct?
   - Is target blocked?
   - Does forceMoveAgent have a bug preventing movement?

### Key Files
- `/Users/rappoccio/Documents/Claude/Projects/Games/DND/gui/helpers.py` line ~426: push_ft parsing
- `/Users/rappoccio/Documents/Claude/Projects/Games/DND/gui/combat.cpp` line ~2366: condition application & push code
- `/Users/rappoccio/Documents/Claude/Projects/Games/DND/gui/combat.cpp` line ~475: forceMoveAgent() implementation

### Debug Logging Currently In Place
- `[COND]` log before condition check (shows push_ft value at load time)
- `[APPLY]` log when condition is applied (shows requires_save and push_ft)
- `[PUSH]` logs throughout push execution (shows caster/target positions, cells_moved)
