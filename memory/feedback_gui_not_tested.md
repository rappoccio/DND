---
name: feedback-gui-not-tested
description: main.py GUI is not covered by run_all_tests.py; GUI-facing changes need manual in-app verification
metadata:
  type: feedback
---

`gui/main.py` (the pygame GUI) is NOT exercised by `run_all_tests.py` — the test suite covers the C++ engine and bindings, not the GUI event loop / rendering / dialog flows.

**Why:** Several GUI-only bugs slipped past green tests in this project, e.g. a stale enum reference (`rpg.VisibilityLevel.PartiallyObscured`, which never existed in the bindings) that crashed on "Show Visible", and an agent-placement save/restore that dropped spells+armor across `apply_agent_configs()` (recreates agents from scratch). Both compiled and passed all tests but broke the running app.

**How to apply:**
- After any `main.py` change (or any binding/enum change that main.py consumes), tell the user it needs manual in-app verification — `run_all_tests.py` passing is NOT sufficient.
- Two recurring GUI bug classes to watch: (1) `rpg.<Enum>.<Value>` references that don't match `rpg_bindings.cpp` definitions; (2) flows that call `apply_agent_configs()` must explicitly save/restore PlacedAgent-only data (spells, armor) — these are NOT in stats and are wiped on recreate.
- Pure main.py edits do NOT require a C++ rebuild — the user can just re-run `python main.py`.
