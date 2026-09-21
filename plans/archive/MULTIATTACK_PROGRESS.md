# NPC Segmented Multiattack — Progress Report

**Date:** 2026-07-02
**Spec:** `MULTIATTACK_PLAN.md` (all 6 steps)
**Status:** All code edits + test COMPLETE. One root-cause bug found & fixed. **Awaiting final build + test run by user.**

## What was implemented (all steps of MULTIATTACK_PLAN.md)

| Step | File | Change | Done |
|------|------|--------|------|
| 1 | `gui/agent.hpp` (after `num_attacks`, ~line 119) | `std::vector<std::pair<int,int>> multiattack;` field on `Agent::Stats` | ✅ |
| 2 | `gui/rpg_bindings.cpp` (beside `num_attacks` def, ~line 279) | `.def_readwrite("multiattack", &Agent::Stats::multiattack)` | ✅ |
| 3 (save) | `gui/main.py` (~line 9291, beside `"num_attacks"`) | `"multiattack": [[int(slot), int(n)] for (slot, n) in s.multiattack],` | ✅ |
| 3 (load) | `gui/agent_loader.py` (~line 40, after `num_attacks`) | `stats.multiattack = [(int(a), int(b)) for a, b in stats_dict.get("multiattack", [])]` | ✅ |
| 4 | `gui/combat.hpp` (`NpcTurnState`, ~line 692) | `std::vector<std::pair<int,int>> pending_segments;` | ✅ |
| 5a | `gui/combat_turn.cpp` | `seedFromRecipe` lambda (after `selectTarget`); three seed sites now `if (!hasRecipe) st.attacks_remaining = num_attacks` with `const bool hasRecipe = seedFromRecipe(st);` computed once before `reachNow` | ✅ |
| 5b | `gui/combat_turn.cpp` | attack loop rewritten `while(true)` with segment-advance + skip-unreachable (`attacks_remaining=0; continue`) | ✅ |
| 6 | `gui/test_npc_multiattack.py` | 4 tests: composition / skip-unreachable / empty-slot / legacy | ✅ |

## Build + test history

1. **First full build: SUCCEEDED** (exit 0, 32/32, `.so` installed).
2. Ran `test_npc_multiattack.py`: **tests 1 & 2 PASSED** (composition incl. damage decode, skip-unreachable incl. damage decode). **Test 3 FAILED** — got `num_attacks` (3 swings) instead of the recipe's 1 swing.
3. **Root cause (real bug, now fixed):** in `seedFromRecipe` I wrote
   `const auto& ma = bm.getAgentStats(agent_idx).multiattack;`
   but **`getAgentStats` returns `Agent::Stats` BY VALUE** (`battle_map.hpp:327`, `combat.hpp:1141`). Binding a
   `const&` to a member of that temporary dangles the moment the statement ends. Tests 1–2 read the freed
   memory before it was clobbered (got lucky); test 3 didn't.
   **Fix applied:** changed to `const auto ma = ...` (copy the vector by value). Comment added in-code.
4. Attempted incremental rebuild in background; user interrupted (didn't want the polling pattern) and killed
   the containers mid-build. **The current `.so` on disk is therefore possibly incomplete — do a clean rebuild.**

## What remains (for the user / next session)

1. **Rebuild** (the dangling-ref fix in `combat_turn.cpp` needs to compile in):
   ```
   docker run --rm -v /Users/rappoccio/Claude/DND:/home/user/Claude/DND \
     -w /home/user/Claude/DND --entrypoint /bin/bash rpg_map \
     -c "cmake --build build --parallel && cmake --install build"
   ```
2. **Run tests:**
   ```
   docker run --rm -v /Users/rappoccio/Claude/DND:/home/user/Claude/DND \
     -w /home/user/Claude/DND/gui --entrypoint /bin/bash rpg_map -c "python3 test_npc_multiattack.py"
   ```
   Expect **4/4** (tests 1,2,4 are hit-independent swing-count checks; test 3 is the one the fix targets).
   Then `run_all_tests.py` for regressions.

## Notes / gotchas confirmed this session
- Render-attack hook fires once per **swing** (before resolution) → swing-count asserts are hit-independent.
- Test weapons use `damage_dice_count = 0` + `bonus_damage` → fixed, crit-proof per-hit damage (crit only
  doubles dice). Melee reach reads `Weapon.reach_ft` (NOT `range_short_feet`); `bonus_hit` (not
  `attack_bonus`) is the to-hit field the engine reads.
- OUT OF SCOPE (per plan): recipe JSON authoring / `tools/monster_parser.py` wiring; PC path. This cut is
  engine infra only, default-off (empty `multiattack` ⇒ exact legacy `num_attacks` behavior).
