---
name: fix-thunderwave-push
description: Fixed Thunderwave Push condition not executing - missing push_ft and requires_save in main.py
metadata: 
  node_type: memory
  type: project
  originSessionId: 961b62bf-211f-415e-beb7-f2fee35e4787
---

## Problem
Thunderwave spell's Push condition was not executing forced movement. Logs showed:
- `push_ft=0` (should be 10)
- `requires_save=false` (should be true)

Despite JSON having correct values and helpers.py having correct parsing.

## Root Cause
**Duplicate code path in main.py**: The App class had its own `_dict_to_spell()` method (line 2865) that was incomplete compared to the `_dict_to_spell()` function in helpers.py.

**What was missing in main.py:**
```python
c.push_ft = int(cond_entry.get("push_ft", 0))
c.requires_save = ("save_ability" in cond_entry)
```

These were present in helpers.py but not in the main.py version.

## Solution
Added the two missing lines to main.py's `_dict_to_spell()` method:
- Line 2945 (after `save_repeat_turns`): Added `c.push_ft = int(cond_entry.get("push_ft", 0))`
- Line 2946: Added `c.requires_save = ("save_ability" in cond_entry)`
- Also added both to the legacy string case (lines 2965-2966)

## Result
✅ Thunderwave now correctly applies Push condition
✅ Fire Elemental moves 10 feet away on failed CON save
✅ Log shows correct values: `push_ft=10, requires_save=true`

## Notes
- The two `_dict_to_spell()` implementations (helpers.py and main.py) should ideally be unified to prevent this again
- Weapon rendering issue during push appeared briefly but resolved (likely stale state)
