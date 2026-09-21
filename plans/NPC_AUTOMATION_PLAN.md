# NPC Automation — Implementation Plan

Goal: let the DM hand control of NPCs to the engine. A per-agent `is_npc_automated`
flag, a `npc_automation_difficulty_level` knob, and a `npc_automation_strategy` enum
select *which* decision algorithm runs on an automated agent's turn. Strategies build
from hand-written heuristics up to NN policies trained in headless mode.

All settings live on `PlacedAgent` (per-encounter instance state, like `faction` and
`on_deck`), are exposed through `BattleMap` accessors + pybind11 bindings, and survive
save/load through `main.py`'s agent serialization block.

---

## Strategy enum

`enum class NpcAutomationStrategy` (in `battle_map.hpp`, bound as `rpg.NpcAutomationStrategy`):

| Value                | Step | Meaning                                           |
| -------------------- | ---- | ------------------------------------------------- |
| `Simple`             | 3    | Attack the closest reachable enemy.               |
| `PreferTargetCaster` | 4    | Attack enemy casters when possible.               |
| `PreferRange`        | 5    | Stay/move to range; attack lowest-HP target.      |
| `PreferAOE`          | 6    | Maximize enemies caught in an AoE catchment.      |
| `PreferHide`         | 7    | Favor stealth/ambush positioning. *(enum exists)* |
| `PreferControl`      | 8    | *(new)* Crowd-control the nearest N enemies.      |
| `PreferHeal`         | 9    | *(new)* Heal the most-damaged ally.               |
| `PreferSupport`      | 10   | *(new)* Buff nearby allies (e.g. Bless).          |

> `PreferHide` is already in the C++ enum (added in Step 1). Steps 8–10 add three NEW
> enum values not yet in the enum. They get added when their step begins (enum value +
> binding + serialization already round-trips ints, so only the `.value(...)` line and
> the strategy table need updating).

---

## Difficulty-level → strategy mapping ✅ DONE for Levels 1–4 (built + green 2026-07-16)

`npc_automation_difficulty_level` overrides the per-agent strategy, resolving one per
agent from role (melee / ranged / caster) + level at turn time, in `resolveStrategy`:

- **Level 1** — All agents: `Simple`.
- **Level 2** — Melee → `Simple`; ranged → `PreferRange`; casters → `PreferRange`.
- **Level 3** — Level 2, plus a caster holding a *castable* AoE blast
  (`npcHasCastableAoeSpell`) → `PreferAOE` (out of slots → degrades back to kiting).
- **Level 4** — Level 3, plus the Step 7–10 specialists:
  - Ranged with **stealth tools** (`npcHasStealthTools` = self-invis spell, bonus or
    action, or Cunning Action — the tools `npcClassifyConceal` routes A–C use, minus
    Route B's cover-cell reachability, which needs the unseeded-at-resolve-time walk
    budget) → `PreferHide`; otherwise `PreferRange`.
  - Casters resolve **DYNAMICALLY** (decided 2026-07-16): probe the LIVE planners in
    priority order **Heal → Control → Support** and resolve to the first *actionable*
    plan (`spell_idx >= 0` OR `approach_target >= 0`), else fall through to the L3 rule.
    Probing the planners themselves — not a parallel capability heuristic — guarantees
    the resolved executor actually finds work, and a healer whose allies are all healthy
    flows on to Control/Support instead of dead-ending in the weapon fallback.
- **Level 5** — NN policy trained on Step 11 (hit-probability features). *Until trained:
  clamps to Level 4 with a one-time combat-log line (decided 2026-07-16).*
- **Level 6** — NN policy trained on Step 12 (kill-probability features). *Clamps like 5.*

**Role classification** — `NpcRole npcClassifyRole` (bound as `npc_classify_role`):
Caster if `npcIsCaster`, else Ranged if any non-shield ranged weapon, else Melee.
`npcIsCaster` now means "knows a COMBAT-RELEVANT spell": the
`classification_ignore_spells` list in `npc_automation_config.json` (lowercased match,
baked-in defaults) filters flavor/utility spells — Speak with Animals, Thaumaturgy,
Mage Armor (pre-baked into stat-block AC), Phantom Steed (no mounts), Feather Fall (no
vertical axis), etc. — so a Centaur Warden is not a "caster". This deliberately also
sharpens Step 4 `PreferTargetCaster` targeting (one definition of caster). Rules stay
coarse; refinement is a planned follow-up.

**Park-safety (critical for the dynamic L4 resolution):** the resolution is stamped on
`NpcTurnState.resolved_strategy` whenever a turn parks; a resumed `runNpcTurn` REUSES it
instead of re-resolving — the game state changed mid-park (the heal landed), and a
re-resolve could route the resume into the wrong executor. `runNpcTurn` was split:
liveness gate + flee intercept + load-or-resolve + stamp stay in `runNpcTurn`;
everything after (resume routing, NoOp, Bucket D, policy dispatch) moved to
`dispatchNpcTurn(bm, idx, strategy)`.

**Difficulty is an OVERRIDE, not a gate** (decided): Level 0 = manual (per-agent
`npc_automation_strategy` field rules); Levels 1+ ignore the field entirely. The
resolver stays separate from the strategy executors.

Files: `combat.hpp` (`NpcRole` + `NpcTurnState.resolved_strategy` + decls + config
cache), `combat_turn.cpp` (resolver + classifier + probes + `runNpcTurn` split + config
loader), `rpg_bindings.cpp` (`NpcRole` enum + `npc_classify_role` +
`npc_classification_ignore`), `gui/npc_automation_config.json`
(`classification_ignore_spells`). Tests: `test_npc_automation.py`
(`test_role_classification`, `test_classification_ignores_flavor_spells`,
`test_difficulty_level1_everyone_simple`, `test_difficulty_level2_role_split`,
`test_difficulty_level3_caster_blasts`, `test_difficulty_level4_ranged_stealth_hide`,
`test_difficulty_level4_caster_dynamic`, `test_difficulty_level4_heal_outranks_control`,
`test_difficulty_level5_clamps_to_level4`, `test_difficulty_level4_turn_actually_heals`).

**Generate Dungeon integration (2026-07-16):** the encounter generator used to
hardcode `automation_level=1` on every mob while ALSO writing curated per-category
strategies — and level 1+ now overrides the strategy field, so everything played
Simple (an Efreeti with Wall of Fire + Invisibility included). Fixed: the Generate
Dungeon dialog gained an **"NPC automation"** stepper (0–6, **default 4**) passed
through both `build_dungeon` call sites, and the CLI `--automation-level` default is
now 4. Level 0 = the generator's legacy fixed per-category strategy table rules;
level 1+ = the resolver rules (the strategy field is still written for level-0 use).
Older generated encounters keep their saved level (right-click → Difficulty to bump).

> **AoE = every damaging area (built + green 2026-07-16):** `isAoeBlastSpell` redefined
> as *any* non-Single/non-Multiple geometry, `Harm`-typed, **with actual damage**
> (`npcSpellAvgDamage > 0`). Rectangle (Wall of Fire) is now IN — an NPC cast aims it
> with the single-point form, which `resolveAoeTargets` evaluates as a width×length box
> centered on the aim, so the planner's catchment count and the actual cast agree
> exactly. Condition-only Harm areas (Hypnotic Pattern) are now OUT of AoE (they are
> control spells; a zero-damage "blast" wasted the action). Rectangle also joined the
> placed-area range gates in `npcPlanAoeCast` AND `npcPlanControlCast`'s area branch
> (a DM-listed Rectangle in `control_priority` now aims at the cluster). Tests:
> `test_aoe_includes_damaging_rectangle`, `test_aoe_skips_condition_only_area`, plus a
> Rectangle case in `test_difficulty_level3_caster_blasts`. *Remaining refinement:*
> oriented two-point wall placement (the cast uses the degenerate centered box).

> **Config-test gotcha (fixed 2026-07-16):** when the suite runs from `gui/`,
> `npcLoadConfig` finds `npc_automation_config.json` and the DM-authored values win over
> the baked-in defaults. `test_control_priority_config_loaded` now probes the SAME
> relative paths the loader tries and asserts against whichever source actually loaded
> (file verbatim, else baked-in defaults). Tests that cast control spells by name may
> only use names present in BOTH lists (Hold Person, Hypnotic Pattern — pinned by the
> config test); removing those from the file's `control_priority` will trip it.

---

## Steps

### Step 1 — Data + plumbing ✅ DONE
- `NpcAutomationStrategy` enum + three `PlacedAgent` fields (`is_npc_automated`,
  `npc_automation_difficulty_level`, `npc_automation_strategy`).
- `BattleMap` get/set accessors (bounds-checked, mirror `setAgentOnDeck`).
- pybind11: `rpg.NpcAutomationStrategy` + six snake_case methods.
- `main.py` save/load round-trip (defaults for older saves; strategy via
  `rpg.NpcAutomationStrategy(int)`).
- Files: `battle_map.hpp`, `battle_map.cpp`, `rpg_bindings.cpp`, `main.py`.

### Step 2 — GUI picker + headless flag pass-through ✅ DONE
**Decisions locked (2026-06-30). Option A confirmed. Right-click-only. Built + green + confirmed in live play 2026-06-30.**

Delivered: `CombatEngine::runNpcTurn` (parkable FlowStatus stub) + `resolveStrategy` seam + `renderAttack`
hook (combat.hpp/combat_turn.cpp); bound `run_npc_turn`/`resolve_strategy`/`set_render_attack_hook`
(rpg_bindings.cpp, `<pybind11/functional.h>`); `NPC Automation ▸` right-click submenu + per-frame driver
(`_npc_drive_idx`/`_drive_npc_turn_if_pending`/`_resume_npc_turn` in main.py, one engine turn per frame);
test_npc_automation.py (headless pass-through proof, registered in run_all_tests.py).


Deliverable: an automated agent's turn is *driven by the engine* through a **parkable
flow**; the decision logic itself is a **stub** that no-ops / ends the turn until Step 3.

#### 2a. GUI control — right-click submenu ONLY (no StatsDialog)
- Add a nested `NPC Automation ▸` entry to the agent right-click menu, built next to
  `Set Teams…` / `Send to On Deck` in `_menu_opts` (`main.py` ~13347). Copy the nested-
  submenu pattern of the `Fiendish Resilience` entry just below (~13364): the parent item
  opens a second `context_menu.show` with the sub-options.
- Submenu contents, each calling the Step-1 setters directly:
  - `Automated: on/off` — toggles `set_agent_npc_automated`.
  - `Difficulty ▸` — picks 0 (manual) … 6 → `set_agent_npc_automation_difficulty`.
  - `Strategy ▸` — picks one of the 5 existing enum values →
    `set_agent_npc_automation_strategy`.
- Per-instance state, mirrors `on_deck`/faction. No StatsDialog mirror.

#### 2b. Engine-side turn driver — Option A (NEW seam, NOT CombatDecider)
`CombatDecider` is a mid-flow *oracle* (choose_brutal_strike / choose_reckless /
choose_reaction); it is NOT a turn driver and must not be overloaded into one. Add a new
entry point instead: 
- New C++ method (combat layer), e.g. `CombatEngine::runNpcTurn(BattleMap&, idx)` — for
  Step 2 a **stub**: log "NPC < name > auto-passes", spend nothing, end the turn. Bind it
  (snake_case `run_npc_turn` ). *rebuild required*
- It MUST drive the **C++ resolution primitives** the tests/headless use (resolveAttack,
  executeSpell, movement budgets) — NOT main.py's interactive `begin_attack` / drag-to-move
  orchestration, which cannot run headless. The Step-2 stub spends nothing so this is moot
  now, but it is the architecture being committed to for Step 3+.
- **Parkable flow (required).** An NPC action must be attemptable, then the human player
  gets a window to counter/react, then it resolves. This already exists via the flow-
  checkpoint system: the driver runs as a flow that returns `AwaitingDecision` and parks
  (same mechanism `begin_turn_flow` uses) so the GUI surfaces the human's reaction menu,
  resuming on submit. The driver returns/yields — it never blocks in a loop. (Step-2 stub
  provokes nothing, but the seam is built parkable from day one.)

#### 2c. Difficulty resolver seam (stub now)
- Add `resolveStrategy(idx)` that returns the per-agent strategy today. It is the SINGLE
  place the later difficulty→role→strategy override will live. `runNpcTurn` always calls
  `resolveStrategy`, never the raw field. Keeps resolver separate from executors.

#### 2d. GUI integration + pacing
- In `_finish_turn_start` (`main.py` ~2752), if `is_agent_npc_automated(idx)` and the agent
  is not on-deck, set a "drive this NPC" flag rather than recursing.
- The main loop drives **one** automated turn per frame (flag-driven), then calls
  `_advance_turn`. Render one at a time — never recurse through `_finish_turn_start`, so the
  board renders between turns and a run of automated NPCs is watchable, and parked human
  reaction windows still surface.

#### 2e. `renderAttack` hook (seam only, no visuals yet)
- Add a `renderAttack(...)`-style hook the driver calls when an NPC action resolves, so the
  GUI can later visualize it (highlight attacker + target, ranged "arrow" animation, AoE
  area blink-then-resolve, etc.). **Implement the hook/seam only — NO animation work now.**
  In headless mode it is a no-op.

#### 2f. Headless pass-through + test
- "Headless pass-through" for Step 2 = `run_npc_turn` is a pybind-exposed C++ function with
  no pygame dependency, callable from pytest today and a rollout loop later. No headless
  turn-loop harness is built here (that is Step 13).
- Test: place an automated NPC, call `run_npc_turn` with no GUI, assert its turn ends and
  nothing is spent. That test IS the headless-pass-through proof.

#### Files
`combat*.cpp/.hpp` (driver + resolveStrategy + renderAttack hook), `rpg_bindings.cpp`
(bind `run_npc_turn`), `main.py` (right-click submenu + per-frame driver flag).

> **FUTURE WORK (NN training / headless rollouts):** in headless mode, auto-apply any
> available reaction immediately upon availability (no human in the loop) so rollouts run
> unattended. Not implemented in Step 2 — recorded here for Steps 11–13.

### Step 3 — `Simple` (= "preferMelee") ✅ DONE (built + green + confirmed in live play, 2026-06-30)
**Decisions locked (2026-06-30):** per-attack loop honoring `num_attacks`; prefer melee (PreferRange is
Step 5); enemy = any non-ally (`areAllies == false`); no reachable enemy → Dash + advance; on a kill
mid-multiattack, re-acquire the next-closest target; weapon = highest average-damage melee weapon.

- On an automated agent's turn: select the nearest attackable enemy (footprint distance, ties → lowest
  HP; faction-aware via `areAllies`), pick the highest-avg-damage melee weapon, move into reach if needed,
  then make a full Attack action (`num_attacks` swings). If no enemy is reachable to strike, Dash and
  advance toward the nearest. Re-acquires the next target if the current one drops mid-multiattack.
- **Resumable.** `runNpcTurn` dispatches `resolveStrategy` → `runSimpleTurn`, which parks (returns
  `AwaitingDecision`) whenever a move it makes provokes an OA or an attack opens a defender/OnD20 window.
  The GUI driver resolves the window and re-calls `run_npc_turn`; `NpcTurnState npc_turn_` holds the
  resume point (target / weapon / attacks-left / phase) so the swing that already resolved is never
  repeated (attacks decremented BEFORE `beginAttack`). Movement uses the parkable `beginMove`; attacks use
  the parkable `beginAttack` — the same paths player actions use, so reactions surface identically.
- **Headless self-containment.** `runSimpleTurn` seeds the agent's OWN movement budget on a fresh turn
  (`initMovement` from base speeds — the budget `moveAgent`/`reachableCells` read, which `beginTurn` does
  NOT seed; the GUI's `_reset_movement` does). All geometry reuses `footprintDistance` + `reachableCells`
  (no re-derivation). `renderAttack` fires per swing (no-op headless).
- Files: `combat.hpp` (`NpcTurnState` + `runSimpleTurn`/`npcSelectTarget`/`npcAttackable`/`npcSelectWeapon`
  decls), `combat_turn.cpp` (dispatcher + Simple executor + helpers), `rpg_bindings.cpp` (docstring).
  Tests: `test_npc_automation.py` (engage+attack, full multiattack, Dash-when-unreachable, ally-immune,
  no-target pass).
- **Live fix (2026-06-30):** the Round-1 first combatant sat idle for a turn. `_start_combat` hand-rolled
  the first turn and skipped `begin_turn_flow`, so C++ `beginTurn` never seeded the engine move budget and
  `_finish_turn_start` (the only place `_npc_drive_idx` is armed) never ran for the first agent. Fixed by
  routing turn 0 through `_proceed_to_new_turn()` like every later turn (`main.py`, Python-only, no rebuild).

### Step 4 — `PreferTargetCaster` ✅ DONE (built + green + confirmed in live play, 2026-06-30)
- Same as Simple but target selection prioritizes enemies that are spellcasters; fall
  back to Simple when no caster is reachable.
- Implemented by REUSING the Step-3 `runSimpleTurn` executor with a `prefer_caster` flag
  (identical movement/attack logic, only target selection changes — no second executor).
  `runNpcTurn` dispatches `PreferTargetCaster` → `runSimpleTurn(bm, idx, prefer_caster=true)`.
- `npcSelectTarget(bm, idx, prefer_caster)`: when set, restricts the candidate pool to enemy
  spellcasters *only if at least one is attackable*; otherwise falls back to the full enemy
  pool (Simple). The nearest / ties→lowest-HP tie-break is unchanged for both pools.
- Spellcaster = `npcIsCaster` ≡ the agent's known-spell list is non-empty
  (`BattleMap::getAgentSpells`). Threaded into BOTH the initial pick and the mid-multiattack
  re-acquire so a parked-then-resumed turn keeps prioritising casters.
- Enum value `PreferTargetCaster` + its binding already existed (Step 1); no binding change.
- Files: `combat.hpp` (signatures + `npcIsCaster` decl), `combat_turn.cpp` (dispatch +
  `npcIsCaster` + `npcSelectTarget` pool logic + `runSimpleTurn` threading).
  Tests: `test_npc_automation.py` (`test_prefer_caster_bypasses_closer_noncaster`,
  `test_prefer_caster_falls_back_to_nearest`).

### Step 5 — `PreferRange` ✅ DONE (needs rebuild + test run)
- If already at range, attack; else move to maintain/establish range (kite). Target the
  lowest-current-HP enemy. Needs a ranged option to be meaningful.
- **Refactor:** Steps 3–5 are now ONE shared executor `runWeaponTurn(bm, idx, NpcStrategyPolicy)`
  (renamed from `runSimpleTurn`). Each `runNpcTurn` dispatch case builds a small policy and calls
  the same executor — new strategies add a case + policy, NOT a new turn driver. `NpcStrategyPolicy`
  (combat.hpp): `prefer_caster` (Step 4), `prefer_ranged` (best ranged weapon, else fall back to
  melee — `npcSelectRangedWeapon`), `kite` (positioning), `priority` (`NpcTargetPriority` enum:
  `Nearest` ties→lowest-HP, or `LowestHp` ties→nearest). Simple=defaults, Caster={prefer_caster},
  Range={prefer_ranged,kite,LowestHp}. Behaviour for Simple/Caster is byte-for-byte preserved.
- Positioning unified into one `findPositionCell(t,w,out)`: kite=false → fewest steps (close in, Simple);
  kite=true → MAXIMISE distance from the nearest enemy (`enemyMinDist`) among in-range+LoS cells, ties→
  fewest steps. `reachableCells` includes the current origin, so a kiter already optimally placed "stays
  put" (guarded by `dest != curOrigin()` so no spurious move). One finder handles both ESTABLISH and
  MAINTAIN range. Geometry still single-sourced (`footprintDistance`/`reachableCells`/`hasLineOfSight`).
- Files: `combat.hpp` (NpcTargetPriority + NpcStrategyPolicy + decls), `combat_turn.cpp` (policy dispatch +
  npcSelectTarget priority + npcSelectRangedWeapon + runWeaponTurn). Enum value `PreferRange` + binding
  already existed (Step 1) — no binding change. Tests: `test_npc_automation.py`
  (`test_range_attacks_without_closing`, `test_range_focus_fires_lowest_hp`,
  `test_range_falls_back_to_melee_when_no_bow`).

### Step 6 — `PreferAOE` ✅ DONE (built + green pending — needs rebuild + test run)
- Compute the AoE catchment that maximizes enemies hit. Start with k-means clustering of
  the opposing team into 1 partition sized to the spell's AoE; place the AoE on that
  cluster. Respect `selective_targeting` / ally-sparing.
- **NOT a weapon turn** — PreferAOE gets its OWN executor `runAoeTurn` (spell casting, not
  `runWeaponTurn`). `runNpcTurn` dispatches `PreferAOE → runAoeTurn` and returns early.
- `npcPlanAoeCast(bm, idx) → NpcAoePlan{spell_idx, aim, net_enemies}`: over the agent's
  currently-castable AoE **blast** spells (`availableCastableSpells`, filtered to
  Sphere/Cone/Line/Square + `Harm` type — Single/Multiple are targeted, Rectangle walls are
  control) and candidate **aim points = each attackable enemy's cell**, choose the spell+aim
  with the most **net enemies** (enemies caught − friendly-fire allies caught, unless the
  spell `selective_targeting` spares allies; the caster itself counts as an ally). Catchment
  is counted with **`resolveAoeTargets`** — the SAME resolver `executeSpell` uses, so geometry
  is single-sourced (no re-derivation). Placed areas (Sphere/Square) are range-gated
  (`effectiveSpellRange`) + LoS-gated to the aim; self-origin Cone/Line need only LoS. Ties →
  higher average spell damage (`npcSpellAvgDamage`).
- **Parkable + resumable.** `runAoeTurn` casts ONCE via the parkable `beginCast` (same path a
  player cast uses, so a human reaction/Counterspell window surfaces identically). It sets
  `NpcTurnState.aoe_cast_launched` BEFORE `beginCast`; on a park→resume, `submitDecision`
  resolved the cast, so the re-entry sees the flag and just ends the turn (never re-casts).
- **AoE is ALWAYS prioritised over melee.** If no blast is catchable from the current cell but
  the agent still HAS a castable AoE (`npcHasCastableAoeSpell`), it does NOT melee — it seeds its
  movement budget, walks toward the nearest enemy (`npcFindAoeApproachCell`, mirror of the weapon
  approach finder) to bring foes into range, then re-plans and casts this turn. If the approach
  move parks on an OA, `NpcTurnState.aoe_moving` marks the resume so re-entry re-plans + casts from
  the new cell (never a second move). If it still can't reach range this turn it ends the turn
  having closed distance — it holds the AoE for next round rather than swinging a weapon.
- **Fallback to weapons only when NO AoE exists.** Only when the agent has NO castable AoE blast
  at all does `runAoeTurn` fall back to a Simple weapon turn (`runWeaponTurn` with default policy)
  so an AoE-less "caster" is never idle. A resume that is neither `aoe_cast_launched` nor
  `aoe_moving` routes back into that weapon turn (which owns `npc_turn_`). (An expended recharge
  breath weapon is not "castable," so a dragon on cooldown correctly bites instead.)
- **Deferred:** the approach targets the nearest enemy (closes distance) rather than solving for
  the cell that maximises catchment; k-means is approximated by per-enemy aim candidates
  (exact-maximizing for blast shapes, whose best center sits on/beside an enemy).
- Files: `combat.hpp` (`NpcAoePlan` + `NpcTurnState.aoe_cast_launched`/`aoe_moving` + `runAoeTurn`/
  `npcPlanAoeCast`/`npcHasCastableAoeSpell`/`npcFindAoeApproachCell` decls), `combat_turn.cpp`
  (dispatch + `npcSpellAvgDamage` + `isAoeBlastSpell` + `npcPlanAoeCast` + the two new helpers +
  `runAoeTurn`), `rpg_bindings.cpp` (`run_npc_turn` docstring). Tests: `test_npc_automation.py`
  (`test_aoe_blasts_enemy_cluster`, `test_aoe_avoids_friendly_fire`,
  `test_aoe_moves_into_range_before_meleeing`, `test_aoe_falls_back_to_weapon_without_aoe_spell`).
  GUI strategy picker already lists "Prefer AOE" (enum existed since Step 1) — no GUI change.

### Step 7 — `PreferHide` ✅ DONE (built + green)
- Favor stealth/ambush positioning: move to break line-of-sight / gain cover, take the
  Hide action, and set up advantage for a later strike. (Enum value already exists.)
- Implemented as a `runWeaponTurn` policy (`conceal`) plus an up-front conceal-route classifier
  `npcClassifyConceal` → `NpcConcealRoute` A/B/C/D, chosen from the agent's tools (bonus/action
  self-invisibility finders `npcFindSelfInvisSpell`, Cunning Action, current Invisible state, and
  `npcFindCoverCell` — nearest reachable no-enemy-LoS cell, mirroring `checkHide`'s LoS gate):
  - **Route A** — bonus-action invis: attack, then bonus-action self-invisibility.
  - **Route B** — cover + Hide: attack, move to the nearest LoS-breaking cover, bonus/Cunning Hide
    (`checkHide`); ends exposed if no cover is reachable.
  - **Route C** — action invis: alternates casting Greater/Invisibility (skips the attack that turn).
  - **Route D** — no stealth tools: falls back to kite positioning.
  - Pre-hidden agents strike with Advantage; a no-target ambusher just sets up.
- Parkable/resumable through the shared `runWeaponTurn` (`st.conceal_route` holds the route across a
  park). Geometry single-sourced (`reachableCells`/`hasLineOfSight`). GUI picker already lists it.
- Files: `combat.hpp` (`NpcConcealRoute` + `npcClassifyConceal`/`npcFindCoverCell`/`npcFindSelfInvisSpell`
  decls + `NpcStrategyPolicy.conceal`), `combat_turn.cpp` (classifier + conceal tail + Route-C skip).
  Tests: `test_npc_automation.py` — 11 `test_hide_*` (all four routes, focus-fire, cover finder, invis
  finder, pre-hidden Advantage, no-cover-exposed, no-target ambush, Route-D kite fallback).

### Steps 8–10 shared foundation — the caster executor ✅ DONE (builds clean 2026-07-15 — needs test run)
Delivered 2026-07-15: enum values `PreferControl=6`/`PreferHeal=7`/`PreferSupport=8` (`battle_map.hpp`) +
bindings (`rpg_bindings.cpp`) + `Strategy ▸` submenu entries (`main.py`); `NpcCastPlan` + `CasterIntent`
(`combat.hpp`); resume flags renamed `aoe_cast_launched`/`aoe_moving` → generic `cast_launched`/`cast_moving`
(shared by `runAoeTurn` + `runCasterTurn`); `npcFindAoeApproachCell` → `npcFindApproachCell(...,approach_target,...)`
so Heal/Support can close on an ALLY; `runCasterTurn(bm,idx,CasterIntent)` cloned from `runAoeTurn`
(approach → single parkable `beginCast` → resume-guard → weapon fallback when `spell_idx<0`); dispatcher
`npcPlanCasterCast` + three **STUB planners** (`npcPlanControlCast`/`npcPlanHealCast`/`npcPlanSupportCast`
return an empty plan → weapon fallback until each step lands); `npcHoldsConcentration` guard helper;
`runNpcTurn` routes `PreferControl/Heal/Support → runCasterTurn` + adds all three to the Bucket-D
recharge-exclusion; resume-routing moved below `resolveStrategy` and routes by strategy. Tests:
`test_npc_automation.py` (`test_caster_strategy_flags_round_trip`, `test_caster_strategies_fall_back_to_weapon`).
The per-step planners (8 Control / 9 Heal / 10 Support) are NOT yet implemented — that is each step's work.

Steps 8–10 are **caster turns**, structurally identical to `runAoeTurn` (Step 6): plan a
spell + targets, cast ONCE through the parkable `beginCast`, guard the resume, and fall
back to a weapon turn when nothing is worth casting. So they share ONE executor + one
planner each (mirroring how `runWeaponTurn` is shared across Simple/Caster/Range/Hide via
`NpcStrategyPolicy`). Do NOT write three copy-pasted executors.

- **Enum + plumbing:** add `PreferControl = 6`, `PreferHeal = 7`, `PreferSupport = 8` to
  `NpcAutomationStrategy` (`battle_map.hpp`), the three `.value(...)` lines
  (`rpg_bindings.cpp`), and the `Strategy ▸` submenu entries (`main.py`). Serialization
  already round-trips ints — no save/load change. `resolveStrategy` unchanged.
- **`NpcCastPlan`** `{ int spell_idx; std::vector<int> target_indices; Cell aim; double score; }`
  generalizes `NpcAoePlan`. `spell_idx < 0` ⇒ nothing worth casting → weapon fallback.
- **`runCasterTurn(bm, idx, CasterIntent)`** cloned from `runAoeTurn`: call the intent's
  planner → if the chosen target is out of range, seed movement and approach → single
  parkable `beginCast` → `renderAttack` toward a representative target → resume-guard →
  fall back to `runWeaponTurn` (default policy) when `spell_idx < 0` so the NPC is never idle.
- **Resume flags:** rename `NpcTurnState.aoe_cast_launched`/`aoe_moving` → generic
  `cast_launched`/`cast_moving` (they already mean "the single cast fired" / "approaching to
  bring a cast into range"); `runAoeTurn` keeps using them. `npcFindAoeApproachCell` gains an
  approach-target parameter so Heal/Support can close on an ALLY, not just the nearest enemy.
- **Dispatch:** `runNpcTurn` routes `PreferControl/Heal/Support → runCasterTurn(...)` and
  returns early (like PreferAOE). All three join PreferAOE/PreferHide in the Bucket-D
  recharge-exclusion condition.
- **Concentration guard (Control + Support):** never re-cast a concentration spell the caster
  already maintains, and never drop a live concentration effect for a weaker one.

**Tuning config — `gui/npc_automation_config.json`** (loaded once in C++ via the existing
`nlohmann/json`; one home for all NPC-automation knobs so difficulty tuning has somewhere to
grow — supersedes the narrower "control priority only" name):
```json
{
  "control_priority": ["Hold Monster", "Hold Person", "Hypnotic Pattern",
                       "Slow", "Command", "Tasha's Hideous Laughter"],
  "heal_threshold_fraction": 0.5
}
```

### Step 8 — `PreferControl` (new enum value) ✅ DONE (built + green 2026-07-15)
- Planner `npcPlanControlCast` walks the DM-authored `control_priority` list IN ORDER and casts
  the FIRST entry that is castable (`availableCastableSpells` gating) with a valid enemy target/aim:
  - *Single* (Hold Person, Command) → nearest attackable enemy (ties → lowest HP), range + LoS gated.
  - *Area* (Hypnotic Pattern, Slow) → catchment-maximizing aim, reusing the `resolveAoeTargets`
    counting loop now factored into shared `npcAreaNetEnemies` (used by both `npcPlanAoeCast` and
    this planner), `selective_targeting`-aware. Placed areas range-gated to the aim; Cone/Line LoS-only.
- **Priority is ABSOLUTE**: the first list entry that yields a valid cast wins — DM order dictates
  which control lands, not a cross-spell score.
- **Concentration guard**: a caster already concentrating skips any `requires_concentration` control
  spell (never drops a live effect to recast one); can still cast a non-concentration control (Command).
- **Approach/fallback** (via `runCasterTurn`): a castable control spell whose target is out of range
  from the current cell returns `approach_target` (nearest enemy) so the executor closes distance +
  re-plans; no castable control spell at all → weapon-turn fallback. Control is prioritised over melee
  exactly like PreferAOE — it moves to bring a control spell online rather than swinging.
- **Config** `gui/npc_automation_config.json` (loaded ONCE, lazy, into mutable caches via `npcLoadConfig`;
  baked-in defaults if the file is absent): `control_priority` (Step 8) + `heal_threshold_fraction`
  (read via `npcHealThreshold`, awaits Step 9).
- Melee grapples stay with the `runWeaponTurn` on-hit riders — PreferControl owns spell/ability control only.
- Files: `combat.hpp` (config caches + `npcLoadConfig`/`npcControlPriority`/`npcHealThreshold` +
  `npcAreaNetEnemies` decls), `combat_turn.cpp` (config loader + `npcAreaNetEnemies` refactor + real
  `npcPlanControlCast`), `rpg_bindings.cpp` (`run_npc_turn` docstring), `gui/npc_automation_config.json`.
  Tests: `test_npc_automation.py` (`test_control_casts_single_target_on_nearest`,
  `test_control_respects_priority_order`, `test_control_area_targets_cluster`,
  `test_control_moves_into_range_before_casting`, `test_control_falls_back_to_weapon_without_control_spell`,
  `test_control_skips_concentration_spell_when_already_concentrating`).

### Step 9 — `PreferHeal` (new enum value) ✅ DONE (built + green 2026-07-15)
- Planner `npcPlanHealCast` scans the caster's castable **HP-restoring** Heal spells (`isHpHealSpell`
  = `type == Heal` AND healing dice/bonus > 0, so Heal-typed non-healers like Beacon of Hope / Mending
  / the unwired mass/resurrection entries are excluded — the planner never "heals" nobody). Gathers
  healable allies (self included; `areAllies`, skipping `removed_from_play`/`on_deck`/true-`dead`),
  ranks **downed allies first** (`reviveOnHeal` inside `executeSpell` revives + rejoins initiative),
  then conscious allies by missing HP (ties → lower index, deterministic).
- **Spell/target choice FROM THE CURRENT CELL** (range + LoS gated per ally, mirroring
  `npcPlanControlCast`): *Single* heals (Cure Wounds, Healing Word, Heal) land on the single top-priority
  needy ally in range; *Multiple* heals (Mass Healing Word) fill `target_indices` with the top-N needy
  allies up to `num_targets`. Among several castable heals, score = **#allies actually healed** ×1000 +
  average healing (`npcSpellAvgHealing`) → a Multiple heal wins when 2+ are hurt, else a bigger single
  heal wins for one badly-hurt ally.
- **Threshold + fallback:** an ally qualifies only when **downed** OR below `heal_threshold_fraction`
  of max HP (default 0.5, `npc_automation_config.json`-tunable via `npcHealThreshold`). No qualifying
  ally → empty plan → weapon-turn fallback (a healer with nobody to heal still fights). A heal is held
  but no needy ally is reachable → `approach_target` = the neediest ally so `runCasterTurn` closes +
  re-plans (heal prioritised over melee, like AoE/Control). HP heals never require concentration → no guard.
- Files: `combat.hpp` (already declared `npcPlanHealCast`), `combat_turn.cpp` (`npcSpellAvgHealing` +
  `isHpHealSpell` helpers + real `npcPlanHealCast`), `rpg_bindings.cpp` (`run_npc_turn` docstring).
  Tests: `test_npc_automation.py` (`test_heal_targets_most_wounded_ally`, `test_heal_revives_downed_ally_first`,
  `test_heal_multiple_fills_wounded_allies`, `test_heal_moves_into_range_before_casting`,
  `test_heal_falls_back_to_weapon_when_allies_healthy`).

### Step 10 — `PreferSupport` (new enum value) ✅ DONE (built + green pending — needs rebuild + test run)
- Planner `npcPlanSupportCast` scans the caster's castable **Help** buff spells (`isSupportBuffSpell`
  = `type == Help` AND applies at least one NAMED condition, so a buff with no condition to check — which
  the planner couldn't tell was already applied — is excluded and never re-cast every turn). Gathers in-play
  allies (self included; `areAllies`, skipping downed/dead — a downed ally wants a heal, not a buff).
- **Already-buffed check:** an ally carries a spell's buff if it holds any of that spell's `sp.conditions`
  names in the live `activeAgentConditions()` list — so a Blessed ally is never re-Blessed. Candidate allies
  per spell = those lacking THAT buff and within range + LoS (mirrors `npcPlanControlCast`/`npcPlanHealCast`).
- **Target choice FROM THE CURRENT CELL:** *Single* buffs (Shield of Faith) land on one unbuffed ally;
  *Multiple* buffs (Bless) fill `target_indices` up to `num_targets`. Candidates are sorted **engaged-with-an-
  enemy first** (adjacent, `footprintDistance <= 1`) so offensive buffs land where the fighting is, filling
  any remaining slots with the rest (ties → lower index, deterministic). Among several castable buffs, score =
  **#allies buffed** ×1000 + `sp.level` → a wider buff wins, ties broken toward the stronger (higher-level) buff.
- **Concentration guard:** a caster already concentrating skips any `requires_concentration` buff (never drops
  a live effect to re-buff); a non-concentration buff still casts.
- **Approach/fallback** (via `runCasterTurn`): a castable buff whose unbuffed allies are all out of range
  returns `approach_target` = the nearest unbuffed ally so the executor closes + re-plans (support prioritised
  over melee like AoE/Control/Heal); every reachable ally already buffed (or no buff at all) → empty plan →
  weapon-turn fallback (a support caster with nobody to buff still fights).
- Files: `combat.hpp` (already declared `npcPlanSupportCast`), `combat_turn.cpp` (`isSupportBuffSpell` helper +
  real `npcPlanSupportCast`), `rpg_bindings.cpp` (`run_npc_turn` docstring).
  Tests: `test_npc_automation.py` (`test_support_buffs_unbuffed_allies`, `test_support_skips_already_buffed_ally`,
  `test_support_multiple_fills_allies_preferring_engaged`, `test_support_moves_into_range_before_casting`,
  `test_support_skips_concentration_buff_when_already_concentrating`,
  `test_support_falls_back_to_weapon_when_all_buffed`).

**Build order:** foundation (enum + `NpcCastPlan` + `runCasterTurn` + approach-target
refactor) → Step 9 (Heal, simplest planner) → Step 10 (Support) → Step 8 (Control, needs the
JSON loader). Each step lands with `test_npc_automation.py` cases mirroring the Step-6 tests.

### Step 11 — Hit-probability model
- For each candidate action, compute P(hit): attack-roll `+hit` vs target AC, or spell
  save DC vs target's relevant save. Pure function over engine state; feeds heuristics
  and NN features.

### Step 12 — Kill-probability model
- Extend Step 11 with average damage per attack and target current HP to estimate
  P(kill) / expected damage. Drives "focus fire" target selection.

### Step 13 — NN training (headless)
- Train a policy NN using the probability strategies (Steps 11–12) as features/labels,
  via headless rollouts. Levels 5 and 6 load the trained policies.

### Step 14 — Teleport-to-reach (blocked-movement escape hatch) ✅ DONE (built + green 2026-07-25)
_Requested 2026-07-24 during the Forcecage box-variant work. Kept out of that diff on purpose so a
build error here wouldn't tangle with the Forcecage mechanics (which are now built + green)._

**Delivered (2026-07-25):** scope simplified per the user's steer — *"just try all movement types (walk,
fly, swim) and if none are available, try to teleport."*
- **`npcMovementType(bm, idx)`** — the primary movement type for the turn: Walk if the creature has a walk
  speed, else Fly, else Swim (a flying-/aquatic-only monster with `speed_walk == 0` previously couldn't
  move at all under automation, which seeds a 0 walk budget). Threaded through `runWeaponTurn` (its
  positioning/approach lambdas + every `beginMove` + the Dash-step math now read this type and its matching
  remaining budget via `moveBudget()`/`moveSpeed()`) and through `npcFindApproachCell` + the AoE/caster
  approach `beginMove`s. Normal walkers are unchanged (Walk wins whenever `speed_walk > 0`).
- **`npcTeleportEscape(bm, idx)`** — last-resort branch: with a castable `teleportation_spell`
  (`availableCastableSpells`-gated; longest range wins) it scans cells within range that are legal
  (`isValidTeleportDestination`), footprint-fitting, unoccupied, and **strictly** closer to the nearest
  attackable enemy (never sideways → no oscillation), spends the spell's N/day use (mirrors `executeSpell`'s
  NPC branch), and funnels through **`teleportAgent`** (which rolls the Forcecage CHA save). Returns true ⇒
  turn spent (a failed cage save still counts, RAW).
- **Two trigger points:** (1) a fresh **Forcecaged/sealed** NPC in `runNpcTurn` (before dispatch — a boxed
  NPC's only useful turn) tries it up front; (2) `runWeaponTurn`'s stuck branch calls it after walk/fly/swim
  (even with a Dash) fail to close, just before "holding position". No teleport / no improving cell → the
  existing Dash/hold behavior is unchanged.
- Files: `combat.hpp` (2 decls), `combat_turn.cpp` (both helpers + moveType threading + the two triggers).
  Tests: `test_npc_automation.py` — `test_step14_flying_monster_flies_to_engage`,
  `test_step14_teleports_when_no_movement_reaches`, `test_step14_teleport_spends_npc_use`,
  `test_step14_boxed_npc_teleports_out`, `test_step14_no_teleport_holds_when_stuck`.
- *Deferred (unchanged from below):* ability-teleports (Shadow Step / Misty Escape / Psychic Teleportation /
  Arcane Charge) — v1 gates on `teleportation_spell` spells only; teleport-then-attack same turn (v1 spends
  the whole turn on the teleport, attacking next round).

<details><summary>Original handoff spec (for reference)</summary>

**Motivation.** Two concrete cases, one mechanism:
1. A **sealed NPC** inside a Forcecage **Box** (`conditions.forcecage_sealed`) can't move, attack,
   or cast anything except a teleport — its only useful turn is a teleport-out attempt. The driver
   currently doesn't try, so a boxed NPC just wastes every turn.
2. **More generally**, an NPC that can reach **no** enemy this turn — walled off by a chasm/water it
   can't cross, or simply too far for move+reach — should, if it has a teleport, use it to close the
   distance (or escape) instead of Dashing into a wall / parking.

Both reduce to: **when the NPC can't bring any attack/spell to bear this turn AND it has a teleport
available, plan a teleport toward the best reachable position.**

**Where it lives.** Engine-side in the turn driver (`runNpcTurn` and its executors
`runWeaponTurn` / `runCasterTurn` / `runAoeTurn`), NOT Python. It is a **fallback branch**: only
fires when the normal plan yields no in-range attack/cast AND no productive approach (see the existing
`approach_target` / Dash-and-advance fallbacks — this slots in just before/alongside them).

**Reuse — most of the machinery already exists:**
- **`teleportAgent`** is the single chokepoint every teleport funnels through and already gates a
  Forcecaged mover on the CHA save (fail → blocked, success → cage condition removed). So a driver
  teleport into it "just works" for the escape case — no new escape logic needed.
- **Teleport inventory:** detect a usable teleport the same way other planners gate spells
  (`availableCastableSpells` + `sp.teleportation_spell` for Misty Step / Dimension Door / Teleport),
  plus the ability-teleports already exposed to the engine (Shadow Step `shadowStepTeleport`,
  Steps of the Fey / Misty Escape, Psychic Teleportation, Arcane Charge). Start with
  `teleportation_spell` spells only; fold in abilities later.
- **Destination scoring:** reuse `footprint_distance` for range/adjacency and
  `isValidTeleportDestination` for legality. Pick the reachable, LoS-having cell (within the
  teleport's range — `teleport_range_ft`, else the spell range) that **minimises distance to the
  nearest enemy** (ideally lands adjacent / within the NPC's weapon reach so NEXT turn it attacks;
  for the boxed case, "nearest enemy" naturally lands it outside the cage).
- **Range/target math:** the AoE/approach planners already compute nearest-enemy; factor the
  "nearest attackable enemy" bit into a shared helper if not already one.

**Behavior spec.**
- Trigger only when the turn would otherwise be a no-op (no attackable enemy, no useful approach).
- Boxed NPC: teleport toward the nearest enemy's side of the cage; `teleportAgent` rolls the CHA save.
  On a failed save the attempt is spent (RAW) — end the turn (don't loop trying other cells; mirror
  the `placeTeleportedAgents` `first_caged` short-circuit already added).
- Terrain-blocked NPC: teleport to the closest legal cell that gets it within move+reach of an enemy
  next turn (or into reach this turn if the teleport lands adjacent — then it may still attack if the
  action economy allows; simplest v1: teleport = the turn's action, attack next turn).
- No teleport available, or no destination improves the position → fall through to the existing
  Dash/advance/park behavior unchanged.

**Edge cases / gotchas.**
- Don't teleport a caster that has a better in-range cast — this is strictly a *last-resort* branch.
- Concentration: a `teleportation_spell` cast doesn't break concentration; fine.
- Slot/resource cost is spent by the normal cast path; a failed Forcecage CHA save still spends it
  (matches the GUI `_resolve_teleport_spell` behavior already wired).
- Avoid oscillation: only teleport if it strictly reduces distance-to-nearest-enemy (or frees a
  boxed NPC); never teleport "sideways."
- Headless/RL: it's a pure engine branch, so rollouts get it for free.

**Files (expected).** `combat_turn.cpp` (the fallback branch + a `npcPlanTeleportToReach`-style
helper), `combat.hpp` (helper decl), maybe `rpg_bindings.cpp` (`run_npc_turn` docstring). Tests:
`test_npc_automation.py` — a boxed NPC with Misty Step teleports out on a passed CHA save; an NPC
walled off by a chasm teleports toward the enemy; an NPC with no teleport falls back to Dash.

**Acceptance.** Boxed NPC caster with a teleport escapes (subject to the CHA save) instead of wasting
turns; a chasm-separated NPC closes the gap via teleport; nothing regresses for NPCs without teleports.

</details>

---

## Architecture notes / where logic lives

- **Engine, not Python.** Per project rule (fix root cause in C++), the decision
  algorithms belong in the C++ combat layer so headless RL can use them. The GUI only
  toggles flags and renders. **The driver is a NEW engine entry point (`runNpcTurn`),
  NOT the `CombatDecider` interface** — `CombatDecider` is a mid-flow oracle
  (choose_brutal_strike / choose_reckless / choose_reaction), the wrong shape for whole-
  turn driving. The driver must use the C++ resolution primitives (resolveAttack /
  executeSpell / movement budgets), not main.py's interactive orchestration.
- **Reuse footprint distance** (`rpg.footprint_distance`) for all range/adjacency math;
  don't re-derive in Python.
- **Faction aware** at every target-selection step (`areAllies`, `selective_targeting`).
- **Difficulty mapping is a layer above strategy.** Strategy is per-agent; the level
  override resolves a strategy per agent from role + level at turn time. Keep the
  resolver separate from the strategy executors.

## Resolved decisions
1. **`PreferHide`** — kept; it is Step 7 and joins Difficulty Level 4.
2. **Difficulty = OVERRIDE.** A set level resolves a strategy per agent by role + level
   and overrides the per-agent `npc_automation_strategy`.
3. **Role classification** (melee/ranged/caster) is assigned from the agent's available
   weapons + spells. Define once and reuse. *(User will refine the classification rules
   later.)*
4. **Step-2 driver = Option A** (engine-side `runNpcTurn`, stubbed), NOT a Python GUI stub
   and NOT `CombatDecider`. Confirmed 2026-06-30.
5. **GUI control = right-click submenu ONLY** (no StatsDialog mirror). Confirmed 2026-06-30.
6. **NPC action = parkable flow**: NPC attempts → human reaction/counter window → resolves,
   via the existing flow-checkpoint `AwaitingDecision` mechanism. One automated turn rendered
   per frame; never recurse.
7. **`renderAttack` hook** added as a seam for future action visualization; NO animations in
   Step 2.
8. **Headless reactions = FUTURE WORK**: rollouts auto-apply available reactions immediately
   (no human in the loop). Deferred to Steps 11–13.


