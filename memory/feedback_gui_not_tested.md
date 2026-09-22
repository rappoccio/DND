---
name: feedback-gui-not-tested
description: main.py's GUI is only thinly covered (panel oracle + prompt bus + click harness, since 2026-09-21); everything outside those still needs manual in-app verification
metadata:
  type: feedback
---

`gui/main.py` (the pygame GUI) used to be exercised by nothing at all. **Amended 2026-09-21:** three suites now reach into it, and everything outside them is still uncovered.

**What IS covered now:**
- `tests/test_combat_panel.py` — a structural golden of `_draw_combat_panel` (section / widget / label / rect / drawn?), so a layout regression fails loudly. Not a pixel comparison; the container installs no fonts.
- `tests/test_prompts.py` — the `PromptBus` and the reaction window, driven headlessly end to end.
- `tests/gui_driver.py` — the shared click harness: real `MOUSEBUTTONDOWN` events posted onto pygame's queue and drained by `App._handle_events`, plus `screenshot()`. Used by `test_prompts.py` (the reaction popup) and `test_session_roster.py` (the **Controller ▸** submenu). **Reuse it** rather than writing a new one — a click test is now cheap.

**What is still NOT covered:** every other dialog and flow, the draw loop as a whole (the frame is composed inline in `run()`; `gui_driver.screenshot` redraws a deliberate subset), anything needing a real display, and the VNC path.

**Why:** Several GUI-only bugs slipped past green tests in this project, e.g. a stale enum reference (`rpg.VisibilityLevel.PartiallyObscured`, which never existed in the bindings) that crashed on "Show Visible", and an agent-placement save/restore that dropped spells+armor across `apply_agent_configs()` (recreates agents from scratch). Both compiled and passed all tests but broke the running app.

**How to apply:**
- After any `main.py` change (or any binding/enum change that main.py consumes), tell the user it needs manual in-app verification unless one of the three suites above actually covers the flow you touched — a green `run_all_tests.py` is NOT by itself sufficient.
- If the flow is a popup or a click, prefer adding a `gui_driver` check to disclaiming it.
- Two recurring GUI bug classes to watch: (1) `rpg.<Enum>.<Value>` references that don't match `rpg_bindings.cpp` definitions; (2) flows that call `apply_agent_configs()` must explicitly save/restore PlacedAgent-only data (spells, armor) — these are NOT in stats and are wiped on recreate.
- Pure main.py edits do NOT require a C++ rebuild — the user can just re-run `python main.py`.
