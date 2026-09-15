# Combat Engine Refactor — Implementation Plan

Status: **IN PROGRESS** — R0, R1, R2, R3's additive landing (`CombatContext` + `rules.hpp`,
forwarders wired in) plus its `rules.hpp` unit tests, and R4's first three sub-engine cuts
(`VisibilityService`, `MovementController`, `ConditionTracker`) are done and verified. R3's
call-site migration is open but is now expected to fall out of R4 rather than be swept; R4 has
4 of its 7 sub-engines left, `SpellResolver`/`AttackResolver` next. See
**Handoff (2026-09-14)** below before picking this up in a new session.

Goal: break up the `CombatEngine` god class so that (a) adding a spell/feat/subclass stops
triggering a full rebuild of every combat TU, (b) the rules layer becomes testable without
instantiating an engine, and (c) combat state becomes serializable — which is the same work
`MULTIPLAYER_PLAN.md` is currently blocked on.

Scope rule (per `memory/feedback_scope_combat_sim.md`): this is a **structural** refactor.
No behavior changes, no new features, no bug fixes bundled in. Every phase must leave
`tests/run_all_tests.py` green with byte-identical results for a fixed seed.

---

## Handoff (2026-09-14)

Read this first if you're picking this up in a fresh session with no prior context.

**Done**: R0 (`2e9fdd9`), R1 (`c1b4c0d`), and R2, all committed to `main`, none pushed to
the remote (only push if the user explicitly asks). Full details of what each phase did are
in the R0/R1/R2 sections below — read those, not just this summary, before touching any of
these phases' files again.

**R2 build/test verification** (2026-09-14, in the `angry_goodall` container): clean build
succeeded (same LTO-relink profile as R1, no new warnings), `tests/test_determinism.py`
matched the golden byte-for-byte, and `tests/run_all_tests.py` was 143/144 — the one
failure is `test_monk.py::test_deflect_attacks_reduces_physical`, confirmed to be the exact
same pre-existing AC-helper bug documented below (same assertion, same line), not a
regression from R2.

**R3 additive landing (2026-09-14, done and verified)**: `combat_context.hpp` (new) and
`rules.hpp` (new) are in place, and `combat.hpp`/`combat_core.cpp`/`combat_attack.cpp`/
`combat_spells.cpp`/`combat_resources.cpp`/`combat_riders.cpp`/`combat_turn.cpp` use them —
see the R3 section below for the full writeup. Not yet committed at time of writing.

**R3 build/test verification** (2026-09-14, in the `angry_goodall` container): the build
succeeded on the first attempt with **no compile errors and no new warnings** (only the
pre-existing pybind11 CMake deprecation notice and the known `-flto` serial-LTRANS note);
`tests/test_determinism.py` matched the golden byte-for-byte; and `tests/run_all_tests.py`
was 143/144, the one failure being `test_monk.py::test_deflect_attacks_reduces_physical` —
verified to be the identical pre-existing bug documented below (same test, same line 505,
same `"the Slashing hit should land for damage"` assertion), not a regression. Worth noting
as extra signal: that failing test is itself an exercise of `calculateAC`, one of the exact
functions R3 moved into `rules.hpp`, so its failing in precisely the same way is direct
evidence the moved AC logic behaves identically.

**R4a landing (2026-09-14)**: `visibility_service.hpp` (new) extracts `VisibilityService` —
the first of R4's seven sub-engines and the cleanest cut in the table. `CombatEngine` keeps
all seven visibility/hide methods as forwarders, so nothing outside `combat.hpp`,
`combat_visibility.cpp`, `combat_context.hpp` and `rules.hpp`'s comments changed. Read the
**R4a** subsection below before touching any of it — especially seam 3 (`checkHide` no longer
calls `applyHidden` itself), the one place the move is not purely mechanical.

**R4a build/test verification** (2026-09-14, in the `angry_goodall` container): build succeeded
**on the first attempt with no compile errors and no new warnings** (only the pre-existing
pybind11 CMake deprecation notice and the known `-flto` serial-LTRANS note);
`tests/test_determinism.py` matched the golden byte-for-byte; and `tests/run_all_tests.py` was
**144/145** — the suite count went up by one because `test_rules.py` was added, and the single
failure is the same pre-existing `test_monk.py::test_deflect_attacks_reduces_physical`
(verified: same test, same line 505, same `"the Slashing hit should land for damage"`
assertion), not a regression.

**`rules.hpp` unit tests — DONE (2026-09-14)**, closing the success criterion at the bottom of
this file. New `gui/test_rules.cpp` (its own `add_executable` target, no pybind11/OpenCV
dependency — it links against nothing but headers) with `tests/test_rules.py` driving it from
`build/` so it reports through `run_all_tests.py` like every other suite. 62 checks, all
passing. See the **R3 — what "done" actually means** subsection for what it covers and the two
plan corrections that writing it turned up.

**R4b landing (2026-09-14)**: `movement_controller.hpp` (new) takes the per-turn walk/fly/swim/
burrow budgets and the slipping-terrain counter. The movement *flow* and `in_flight_move_`
stayed on `CombatEngine` on purpose — they are entangled with `pending_decision_` and travel
with `ReactionArbiter`. Same verification as R4a: clean build, golden byte-identical, 144/145.
Read the **R4b** subsection before touching it.

**R4c landing (2026-09-14)**: `condition_tracker.hpp` (new) takes the active-condition store,
the id counter and both stat-snapshot maps, with `ActiveAgentCondition` gaining a 33-field JSON
mapping (as free functions, so `battle_map.hpp` is untouched). The container moved; the effect
logic that drives it did not. Same verification: clean build, golden byte-identical, 144/145.
Read the **R4c** subsection first — especially why `nextId()`/`append()` stayed two calls and
what `mutableAll()` is for.

**Not done**: everything from "migrate call sites TU-by-TU" onward in R3 (though see "R3 — what
'done' actually means": it is 298 sites, not 950, most forwarders must stay, and the migration
now falls out of R4 for free), R4's remaining four sub-engines plus the movement flow deferred
from R4b and `ConditionTracker::mutableAll()`'s removal deferred from R4c, and all of R5.
**`SpellResolver`/`AttackResolver` are next and are NOT yet measured** — scope them the way R4b
and R4c were scoped before starting. Do not start further work on R3 or R4 without the R0 determinism harness
passing at every step — it's the oracle this whole plan depends on.

**Build environment — read this before running anything.** This repo's real build/run
environment is a Docker container, not the host machine directly:
- Container: name `angry_goodall`, id `62aa12a89476` (check `docker ps` — the name/id may
  change if the container was recreated; look for image `rpg_map`).
- `/Users/rappoccio` on the host is bind-mounted to `/home/user` in the container, so
  editing files via normal tools on the host is immediately visible inside the container —
  no syncing needed. Repo root inside the container: `/home/user/Claude/DND`.
- Build via `docker exec <container> bash -lc 'cd /home/user/Claude/DND && ./compile.sh'`.
  `compile.sh` auto-detects Ninja (available in the container) vs `make` (host-only
  fallback) — don't hard-code a generator again, that was a real bug fixed in R0.
  `FETCHCONTENT_UPDATES_DISCONNECTED` is also load-bearing (R0) — without it, every
  configure forces a full rebuild; don't remove it.
- Run tests the same way: `docker exec <container> bash -lc 'cd /home/user/Claude/DND &&
  python3 tests/run_all_tests.py'`. `gui/CLAUDE.md` says never run build/test commands
  without the user's explicit go-ahead by default — this session had standing permission
  ("do everything except push to git"); check current permission before assuming that
  still holds in a new session.

**Known pre-existing failure, not caused by this refactor**: `tests/run_all_tests.py`
is 143/144 green. The one failure, `test_monk.py::test_deflect_attacks_reduces_physical`,
is a latent test bug unrelated to R0/R1 (confirmed deterministic and reproducible on
build state before either phase touched anything): its `_hittable_monk_defender` helper
force-sets `base_ac=1`, but Monk Unarmored Defense recomputes AC as `10+DEX+WIS`
unconditionally, so the target's real AC is 15, not 1. Not fixed here per the plan's
no-bug-fixes-bundled-in scope rule — don't be alarmed by it, and don't silently start
"fixing" it as part of a later refactor phase without calling it out as a separate change.

**Open follow-up, not part of any phase**: `pybind11_add_module` enables `-flto` by
default for Release builds, which relinks all ~71 LTRANS units on every single build
(~40-50s) regardless of what changed — this significantly dampens R1's per-TU incremental
build win. Not addressed (changes the shipped `.so`'s characteristics, a real tradeoff the
user should decide on, not something to change unilaterally mid-refactor). See R1's
write-up below for the measured numbers.

---

## Baseline measurements (2026-08-11)

Everything below is measured, not estimated. Re-measure before starting each phase.

| Metric | Value |
| ------ | ----- |
| `combat.hpp` | 3,416 lines — 401 public + 90 private methods |
| Implementation | ~23,000 lines across 10 `combat_*.cpp` TUs |
| `rpg_bindings.cpp` | 4,850 lines; 324 `CombatEngine` methods bound, 281 used from Python |
| `combat.hpp` churn | **125 of the last 200 commits** |
| `rpg_bindings.cpp` churn | **150 of the last 200 commits** |
| Header churn location | 58% public class body · 40% struct region · **2% private block** |
| Python call sites | 620 in `main.py` (192 distinct methods) · 256 distinct across `tests/` |
| Public methods NOT exposed to Python | **87** (free to move or demote) |

### TU sizes

| File | Lines | `CombatEngine::` defs |
| ---- | ----: | ----: |
| `combat_spells.cpp` | 5,203 | 80 |
| `combat_attack.cpp` | 4,452 | 69 |
| `combat_turn.cpp` | 3,644 | 47 |
| `combat_resources.cpp` | 3,482 | 84 |
| `combat_riders.cpp` | 2,530 | 58 |
| `combat_conditions.cpp` | 1,385 | 37 |
| `combat_movement.cpp` | 923 | 17 |
| `combat_core.cpp` | 826 | 28 |
| `combat_visibility.cpp` | 378 | 7 |
| `combat_state.cpp` | 204 | 23 |

> `combat.cpp` (898 lines) contains **no engine code at all** — it holds
> `Agent::Stats::applyClassResources` / `initializeClassResources` /
> `initializeMulticlassResources`. Misnamed; rename in R0.

---

## The key finding

**The implementation is already correctly decomposed. Only the declaration isn't.**

Every private member of `CombatEngine` is already owned by essentially one TU. This is not
a tangled-state problem — it is a single-header problem.

| private member | core | state | attack | spells | turn | resrc | riders | cond | move | vis |
| -------------- | :--: | :---: | :----: | :----: | :--: | :---: | :----: | :--: | :--: | :-: |
| `in_flight_move_`        | · | · | ·  | ·  | ·  | · | · | ·  | **23** | · |
| `npc_turn_`              | · | · | ·  | ·  | **23** | · | · | ·  | ·  | · |
| `in_flight_attack_`      | · | · | **17** | · | ·  | · | · | ·  | 2  | · |
| `cast_stack_`            | · | · | ·  | **16** | · | · | · | ·  | 1  | · |
| `in_flight_turn_`        | · | · | ·  | ·  | ·  | · | **6** | · | 2 | · |
| `activeEffects_`         | · | · | ·  | **7** | ·  | · | · | ·  | ·  | · |
| `gaseousSnapshots_`      | · | · | ·  | ·  | ·  | · | · | **5** | · | · |
| `visibilityMap_`         | · | · | ·  | ·  | ·  | · | · | ·  | ·  | **5** |
| `safeTargets_` / `zoneAppliedTurn_` | · | · | · | **4** | · | · | · | · | · | · |
| `agentTurns_`            | · | **5** | · | · | ·  | · | · | ·  | ·  | · |
| `walkRemaining_` et al.  | · | · | ·  | ·  | 1  | 1 | 1 | ·  | **8** | · |
| `activeAgentConditions_` | 1 | · | 5  | 12 | 11 | 2 | · | **19** | 3 | · |
| `pending_decision_`      | · | · | 3  | 4  | ·  | · | 2 | ·  | 5  | · |

Only two members are genuinely shared across modules: **`activeAgentConditions_`** and
**`pending_decision_`** (the reaction system). Everything else has a single owner today.

### True internal call graph

Self-calls only (`bm.`-prefixed calls to `BattleMap` excluded — a naive grep over-counts
them ~10×, since `bm.getAgentStats(...)` alone appears 380 times):

```
turn        (3 in / 190 out)   ← top-level driver, almost nothing calls it
  ├→ spells (107 in / 274 out)
  ├→ attack  (65 in / 238 out)
  ├→ resrc   (58 in / 292 out)
  ├→ riders  (13 in / 252 out)
  ├→ cond    (75 in /  63 out)
  ├→ move    (28 in /  47 out)
  └→ core   (950 in /   7 out) ← pure primitives; a sink
     vis     (49 in /   4 out) ← near-sink
```

Two structural facts fall out:

1. **`core` is a 950-in / 7-out sink of pure rules primitives** — `roll`, `rollAdvantage`,
   `attackModifier`, `damageAbilityMod`, `calculateAC`, `saveModFor`, `saveAdvantageFor`,
   `spellAttackMod`, `spellSaveDc`, the aura queries, `canEquipArmor`, `isHoldingShield`.
   One dependency edge accounts for ~55% of all internal coupling and it points one way.
2. **`state` is internally inert** (21 self-calls in 204 lines). It is a pybind shim over
   `BattleMap` — `getAgentStats` is a one-line pass-through called 9 times internally
   versus 380 direct `bm.getAgentStats(...)` calls. It exists for Python, not for C++.

Excluding `core` and `state`, peer-to-peer coupling is only **~370 calls**. That is the
real cut cost of a full decomposition. Worst edges: `turn→spells` 34, `riders→resources`
27, `riders→attack` 25, `spells→conditions` 20, `resources→conditions` 18,
`spells→attack` 18, `movement→spells` 17.

### Conditions that make this tractable

- No `friend` declarations anywhere in `combat.hpp`.
- `BattleMap` has **zero** compile-time dependency on `CombatEngine` (only comment
  references) — the layering is already clean in the right direction.
- Only 14 files include `combat.hpp`.
- Python already goes through `RecordingCombat.__getattr__` (`replay_record.py:50`), a
  transparent proxy — a ready-made facade seam that can absorb a re-shaped C++ API.
- 87 public methods are unexposed to Python and can be moved or demoted freely.

### What this rules out

`combat.hpp`'s private block accounts for **2% of header churn**. A pImpl on the state
therefore buys essentially nothing — the churn is method *additions* in the public body
(new spells, feats, subclass activations), which pImpl does not address. **Rejected.**

---

## Cross-cutting decisions — PROPOSED, confirm before R2

1. **The Python API does not change.** `main.py`'s 620 call sites and the 256 distinct
   methods used across `tests/` keep working verbatim. `CombatEngine` survives as a thin
   facade of forwarders. Any phase that would rename a bound method is out of scope.
   *(This is the single most important constraint — it makes every phase independently
   revertable and keeps the test suite as a continuous oracle.)*

2. **`CombatContext` is a struct, not a class.** Plain aggregate of the genuinely global
   scratch state, passed by reference. No behavior, no invariants, no getters — so it
   serializes trivially and reads cheaply at the ~950 call sites that will touch it.

3. **The rules layer becomes free functions, not a class.** `combat_core.cpp`'s primitives
   take `(const BattleMap&, ...)` and at most a `CombatContext&` for `rng_`. They are pure
   or near-pure today (`attackModifier` already is). Free functions in `rules.hpp` are
   directly unit-testable and cost nothing to call.

4. **Serialization is designed in from R2, not retrofitted.** Every state struct extracted
   gets `to_json`/`from_json` in the same commit that creates it. This is what
   `MULTIPLAYER_PLAN.md` needs, and retrofitting it later means touching every struct twice.

5. **One module per phase, each independently shippable.** No big-bang branch. Every phase
   ends with a green `tests/run_all_tests.py` and is a sane stopping point if priorities
   change.

6. **Fixed-seed determinism is the acceptance test.** Beyond the unit suite, a scripted
   encounter at a fixed seed must produce a byte-identical `replay_log.txt` before and
   after each phase. Build this harness in R0 — without it, "no behavior change" is a hope
   rather than a check.

> Open question for discussion: whether `combat_state.cpp`'s 23 accessors should stay on
> the engine at all, or move to `BattleMap` with the engine forwarding. They are pure
> pass-throughs *except* `setAgentStats`, which materializes Warlock Devil's Sight passive
> vision. Recommendation: leave them alone in R0–R3 (zero internal callers = zero benefit
> to moving them) and revisit only if R4 makes them awkward.

---

## Phases

| Phase | Scope | Risk | Est. | Unlocks |
| ----- | ----- | ---- | ---- | ------- |
| **R0** | Rename `combat.cpp`; build determinism harness | none | ~1 day | the oracle everything else relies on |
| **R1** | Split `rpg_bindings.cpp` by domain | very low | 2–3 days | biggest single build-time win |
| **R2** | Extract `combat_types.hpp` | low | 1–2 days | 40% of header churn stops rebuilding binding TUs |
| **R3** | Extract `CombatContext` + `rules.hpp` | medium | 1–2 weeks | dissolves the 950-call edge; testable rules — *additive landing done; call-site migration open* |
| **R4** | Decompose into sub-engines behind a facade | high | multi-week | true modularity — *`VisibilityService` cut; 6 sub-engines left* |
| **R5** | State serialization → snapshot/restore | medium | 1–2 weeks | `MULTIPLAYER_PLAN.md`, mid-combat save |

R0–R2 are mechanical and near-risk-free — do them regardless of whether R4 ever happens.
R3 is the highest-leverage single step. **R4 should not start until R3 has settled.**

> Deviation, recorded 2026-09-14: R4a (`VisibilityService`) was started while R3's call-site
> migration is still open, at the user's direction. The two turn out not to conflict — R3's
> open half is rewriting `foo(...)` to `rules::foo(...)` inside the combat TUs, while R4a only
> moved *declarations* and left every call site alone — but the rule above still stands for the
> later, more entangled sub-engines. In particular, do not take `ReactionArbiter` (the
> `pending_decision_` / `in_flight_*` cut) with R3 half-migrated.

---

### R0 — Groundwork — **DONE** (2026-09-14)

- Rename `combat.cpp` → `class_resources.cpp` (it holds `Agent::Stats` resource tables, not
  engine code). Update `CMakeLists.txt`. Pure rename, no code movement.
- Build `tests/test_determinism.py`: run a scripted encounter at a fixed seed, dump the
  full engine-visible outcome, compare against a golden fixture. Register in
  `tests/run_all_tests.py` per the `tests/` convention.
- Record a baseline clean-build wall time and a single-header-touch incremental-build time,
  so R1/R2's payoff is measurable rather than asserted.

**Baseline build times** (measured in the project's Docker container — aarch64 Linux,
Ninja, `-flto`; this is the real build environment, not the macOS host):

| Build | Wall time |
| ----- | --------: |
| Clean (`rm`'d `build/`, full configure+build+install) | 1m 03.4s |
| No-op (nothing changed) | 0.19s |
| Single-header touch (`touch gui/combat.hpp`) | 50.5s — rebuilds all 11 `combat_*.cpp`/`class_resources.cpp` TUs + `rpg_bindings.cpp` (26/32 targets); `battle_map.cpp`, `map_configs.cpp`, `spell.cpp` are skipped, matching the plan's "14 files include `combat.hpp`" count |

Also fixed two build-tooling bugs found while measuring these (both real, both now fixed,
neither in scope of the "no behavior change" rule since they're build config, not engine
code):
- `compile.sh` hard-coded `-G Ninja`, which isn't installed on a plain macOS host — it now
  detects the available generator (`Ninja` if present, else `Unix Makefiles`) so the same
  script works on the Docker container and a bare host.
- `gui/CMakeLists.txt`'s `FetchContent` block re-checked-out pybind11/nlohmann_json on
  *every* configure (even to the same pinned tag), which rewrites their file mtimes and
  was forcing a full rebuild on every single invocation regardless of what changed — this
  is what made the "no-op" measurement meaningless before the fix (48s instead of 0.19s).
  Fixed with `FETCHCONTENT_UPDATES_DISCONNECTED ON`.

### R1 — Split the bindings — **DONE** (2026-09-14)

`rpg_bindings.cpp` is the second god file: 4,850 lines, touched in 150 of the last 200
commits, and almost certainly the slowest TU in the build (pybind11 template
instantiation). Split into `bind_types.cpp`, `bind_combat_attack.cpp`,
`bind_combat_spells.cpp`, `bind_combat_resources.cpp`, `bind_combat_turn.cpp`,
`bind_battle_map.cpp`, with a shared `bindings_internal.hpp` holding the
`py::class_<CombatEngine>` handle that each TU adds `.def`s to.

No C++ API changes, no Python API changes. The binding name→method mapping is mechanical
and the test suite covers it densely.

**How the split was done**: the ~1,900-line, 324-method `py::class_<CombatEngine>` chain
had no internal domain grouping to lean on, so each `.def(...)` statement was categorized
programmatically — parsed into individual top-level statements (tracking paren depth and
string literals), matched against a `CombatEngine::MethodName → implementation file`
table built by grepping every `combat_*.cpp` TU, and bucketed: `combat_attack.cpp` →
`bind_combat_attack.cpp`, `combat_spells.cpp` → `bind_combat_spells.cpp`,
`combat_resources.cpp` → `bind_combat_resources.cpp`, and everything else
(`combat_turn.cpp`, `combat_movement.cpp`, `combat_conditions.cpp`, `combat_riders.cpp`,
`combat_core.cpp`, `combat_state.cpp`, `combat_visibility.cpp`, plus a couple dozen
methods/lambdas inlined directly in `combat.hpp` with no TU of their own — cross-cutting
state like `pending_decision_`, `logger_`, `last_*_result_`) → `bind_combat_turn.cpp` as
the catch-all, matching `combat_turn.cpp`'s role as the top-level driver in the call-graph
table above. No two `.def()` calls in the original chain bound the same Python name, so
statement order across the split carries no behavioral meaning. `bind_types.cpp` and
`bind_battle_map.cpp` were then split off as contiguous blocks (no categorization
needed — clean top-level boundaries). Verified via a full rebuild + `test_determinism.py`
(byte-identical golden) + `tests/run_all_tests.py` (143/144, same pre-existing
`test_monk.py` failure as the R0 baseline) after each step.

**Result**: `rpg_bindings.cpp` 4,850 → 58 lines (just the module entry point + wiring
order). New files: `bind_types.cpp` 2,459 · `bind_combat_turn.cpp` 922 ·
`bind_combat_resources.cpp` 517 · `bind_battle_map.cpp` 511 · `bind_combat_spells.cpp`
268 · `bind_combat_attack.cpp` 243 · `bindings_internal.hpp` 36.

**Build-time finding**: clean-build wall time did *not* improve (1m03s → 1m22s — more
total CPU work, since pybind11 template instantiation overhead is now paid per-TU across
7 files instead of once). That's expected and isn't what R1 promised. What R1 actually
delivers — confirmed — is that a change to *one* binding file now only recompiles that
file: touching `bind_combat_attack.cpp` alone rebuilds just that TU, not the other 5
binding files or any `combat_*.cpp` engine TU (before, ANY binding change meant
recompiling the entire 4,850-line file). However, this TU-isolation win is currently
**masked by `-flto`**: `pybind11_add_module` enables link-time optimization by default
for Release builds, and that LTO relink (71 LTRANS units) costs ~40-50s on *every* build
regardless of what changed, dwarfing the actual compile time of a single small TU. Both
the single-binding-file touch (49s) and the whole-old-file-equivalent touch (58s) are
dominated by this relink, not by compilation. **Not fixed here** — changing the shipped
`.so`'s LTO/strip characteristics is outside R1's "mechanical split, no other changes"
scope — but worth a deliberate decision later: e.g. a non-LTO profile for local dev
iteration (`pybind11_add_module(... NO_EXTRAS)` or a `Debug`/`RelWithDebInfo` config),
keeping LTO for release packaging.

**Deferred, not done here**: the **43 bound-but-never-referenced** methods
(`activate_starry_form`, `apply_shield`, `can_bend_luck`, `get_battle_observation`,
`resolve_attack`, `reseed`, …) are still worth triaging — some are dead, some are
RL-facing and deliberate, some are reaction internals that leaked into the API. Deleting
or documenting them is a behavior/API-surface decision, not a mechanical move, so it's
out of scope for R1's "no behavior changes" rule — left for a dedicated pass.

### R2 — `combat_types.hpp` — **DONE** (2026-09-14)

Moved the struct/free-function region (`combat.hpp` original lines 63–964: `HideResult`,
`AttackResult`, `Attack`, `SpellAction`, `SpellResult`, `ReactionCtx`, `InFlight*`,
`NpcTurnState`, …, plus the trailing `canTakeReaction()` free function — the whole block
immediately before the `CombatEngine` class banner) verbatim into new `gui/combat_types.hpp`.
`combat.hpp` gained one `#include "combat_types.hpp"` (alongside its other top-of-file
includes, before `namespace rpg {` opens — the same pattern `weapon.hpp`/`spell.hpp` already
use, so the struct definitions land in `rpg::`, not a nested `rpg::rpg::`) and a 3-line
pointer comment where the block used to live. No struct content, comments, or formatting
were altered — verified with a line-range diff against the pre-edit file.

**Includes for `combat_types.hpp`** were derived by checking, for every forward-declared
type available in `combat.hpp` (`BattleMap`, `Cell`, `AgentConfig`, `ActiveSpellEffect`,
`ActiveAgentCondition`, `MovementType`, `VisibilityLevel`, `NpcAutomationStrategy`), whether
the moved structs use it as a real field/parameter type or only mention it in a comment.
Only `Cell` (by value, many structs), `Weapon` (`InFlightAttack::w`), `Spell`
(`ActiveEffect::spell`), `Agent::Conditions` (`canTakeReaction`'s parameter), and
`MovementType` (`InFlightMove::type` — kept as a forward declaration exactly as before,
since a forward-declared scoped enum's fixed `int` underlying type makes it usable as a
member without the full definition) are real usages. `BattleMap`, `AgentConfig`,
`ActiveSpellEffect`, `ActiveAgentCondition`, `VisibilityLevel`, `NpcAutomationStrategy` are
comment-only in this region and stay forward-declared in `combat.hpp` for the `CombatEngine`
class body that still follows. Two types are used only *transitively* through others:
`SaveAbility_t`/`SaveStr` (via `weapon.hpp` → `condition.hpp`) and `MetamagicOption` (via
`agent.hpp` → `character_class.hpp`) — confirmed rather than assumed, so
`combat_types.hpp`'s explicit include list is `weapon.hpp`, `spell.hpp`, `agent.hpp`,
`cell.hpp` (no `armor.hpp`/`item.hpp`/`message_logger.hpp` — grepped for real, non-comment
`Armor`/`Item`/`MessageLogger` usage in the moved region and found none).

**Result**: `combat.hpp` 3,416 → 2,517 lines; new `combat_types.hpp` is 931 lines (19 lines
of header/include preamble + the 902-line moved block + closing brace). No other file
needed changes — every `.cpp` TU already reaches these types by including `combat.hpp`,
which now pulls in `combat_types.hpp` transitively, and `CMakeLists.txt` doesn't enumerate
headers.

Alone this is cosmetic — all 10 combat TUs still include `combat.hpp` and so still pull in
`combat_types.hpp` too. **Its value is entirely in combination with R1**: a future binding
TU that only needs these structs (not the full `CombatEngine` declaration) can include
`combat_types.hpp` directly, and the 40% of header churn that the baseline measurement
found landing in the struct region stops rebuilding it.

**Verification**: checked by line-range diff against the pre-edit file (byte-identical
struct body, byte-identical surrounding `combat.hpp` content), then build/test-verified in
the container — see the Handoff section above for the results.

### R3 — `CombatContext` + `rules.hpp` ⭐ — **ADDITIVE LANDING DONE** (2026-09-14)

The highest-leverage step. The additive half — `CombatContext` extracted, `rules.hpp`
landed, `CombatEngine` forwarding to both — is done and verified; the call-site migration
that follows it is deliberately still open (see the landing writeup below).

**`CombatContext`** (new `combat_context.hpp`) absorbs the genuinely cross-cutting scratch
state: `rng_`, `logger_`, `pending_roll_bonus_`, `pending_damage_bonus_`,
`pending_advantage_`, `force_max_damage_`, `turnCounter_`, `pending_portent_die_`,
`resolving_sentinel_guard_`, `agent_portent_round_used_`, `render_attack_hook_`,
`npc_recording_`, `npc_visual_events_` — plus the `consumePending*` helpers, which are
already tiny inline accessors on exactly this state.

**`rules.hpp`** takes `combat_core.cpp`'s primitives as free functions in `namespace
rpg::rules`. Most are already pure; the dice functions take `CombatContext&` for `rng_`.

Payoff:
- Dissolves the 950-call `→core` edge — the largest single source of coupling.
- The rules layer becomes unit-testable with no engine, no `BattleMap`, no map image.
- Changes to dice/AC/save-modifier logic stop touching `combat.hpp` entirely.
- `CombatContext` is the first serializable unit, proving the R5 pattern on the smallest
  possible surface.

Sequencing note: land `rules.hpp` **first** as a pure additive header with `CombatEngine`
methods forwarding to it, then migrate call sites TU-by-TU, then delete the forwarders.
Never a single 950-site sweep.

**Additive landing — DONE (2026-09-14).** The first step above (land `rules.hpp` +
`CombatContext` additively, forwarders only, zero call-site migration) is complete and
build/test-verified — see the Handoff section above for the verification results.

**`combat_context.hpp`** (new) holds exactly the member list this section originally
specified: `rng_`, `logger_`, `render_attack_hook_`, `pending_roll_bonus_`,
`pending_damage_bonus_`, `pending_advantage_`, `force_max_damage_`, `pending_portent_die_`,
`agent_portent_round_used_`, `resolving_sentinel_guard_`, `turnCounter_`, `npc_recording_`,
`npc_visual_events_`, plus the three `consumePending*` helpers. `CombatEngine` gained one
member, `CombatContext ctx_;`, replacing all of the above as individual fields.
`zoneAppliedTurn_` (the map keyed off `turnCounter_`, not the counter itself) stays on
`CombatEngine` — it's spell-effect bookkeeping, not scratch state, and wasn't in this
section's original member list.

Serialization was written now, not deferred to R5, per decision #4: `to_json()`/`from_json()`
round-trip `rng_` (via `operator<<`/`>>` on the live `mt19937` — the actual generator state,
not the original seed, so a resumed engine can't diverge from rerolling), the pending-roll/
portent/sentinel-guard/turn-counter scratch ints, and `agent_portent_round_used_` (as a JSON
array of `{agent, round}` objects — nlohmann's native map support wasn't trusted for a
non-string key without a precedent elsewhere in the codebase). `logger_`,
`render_attack_hook_`, `npc_recording_`, and `npc_visual_events_` are deliberately NOT
serialized: the first two are host callbacks rebound after any restore, and the NPC ones are
transient GUI-animation plumbing drained every turn, not gameplay state.

**Every existing call site was preserved without touching non-context code.** Rather than
rewriting the ~15 sites that called `consumePendingRollBonus()`/`consumePendingDamageBonus()`/
`consumePendingAdvantage()`, `CombatEngine` keeps those three method names as one-line
forwarders to `ctx_`'s versions — the plan's "no big sweep" principle applied one level
lower than the rules-layer call sites it was written about. The ~80 remaining direct field
touches (`rng_`, `pending_portent_die_`, `resolving_sentinel_guard_`, `turnCounter_`,
`npc_recording_`, `npc_visual_events_`, direct `pending_roll_bonus_`/`pending_damage_bonus_`
assignments in the bardic/portent/sentinel-guard feature code) across `combat_core.cpp`,
`combat_attack.cpp`, `combat_spells.cpp`, `combat_resources.cpp`, `combat_riders.cpp`, and
`combat_turn.cpp` were mechanically renamed to `ctx_.<field>` — verified by grepping for
every bare field name afterward and confirming only comments remained.

**`rules.hpp`** (new) is header-only `inline` free functions in `namespace rpg::rules`,
matching `combat_internal.hpp`'s existing convention for helpers shared across the
`combat_*.cpp` TUs — no new `.cpp`, no `CMakeLists.txt` change. Covers exactly this section's
list: `roll`/`rollAdvantage`/`rollDisadvantage` (take `CombatContext&`), `attackModifier`,
`damageAbilityMod`, `spellAttackMod`, `spellSaveDc`, `spellSaveDcFromAbility`, `calculateAC`,
`isHoldingShield`, `canEquipArmor`, the five Paladin/advantage aura queries
(`bestPaladinAura`, `auraSaveBonus`, `hasAuraOfCourage`, `hasAuraOfWarding`,
`hasAuraOfAlacrity`, `hasAdvantageAura`), `saveModFor` (takes `CombatContext&` — rolls
Bless's 1d4), and `saveAdvantageFor`. `curseSaveDisadvantage` and `applyIndomitableMight`
were deliberately left on `CombatEngine`: the former reads `activeAgentConditions_`, which
isn't in `CombatContext` (it's real per-encounter game state slated for R4's
`ConditionTracker`, not scratch), so it can't become a pure `rules::` function without
dragging that member along too.

One dependency wrinkle, resolved by small duplication rather than a cross-module call: the
aura queries need a same-team-or-self check, which already exists as
`CombatEngine::areAllies` (`combat_visibility.cpp`) — but that's a non-static member with no
state dependency of its own (it only reads `bm.getAgentFaction`), so calling it from a free
function would mean threading an engine instance through for no real reason. `rules.hpp`
instead defines its own two-line `alliedFactions()` with a comment pointing at
`CombatEngine::areAllies` as the canonical version, to be deduped when R4 extracts
`VisibilityService`.

`CombatEngine`'s methods in `combat_core.cpp` for every function above are now one-line
`return rules::foo(...)` forwarders — the pybind11 bindings, `main.py`'s 620 call sites, and
every test call these exactly as before with zero signature changes.

**Not done, by design (per the sequencing note)**: none of the ~950 internal call sites that
currently call the `CombatEngine` methods (e.g. `attackModifier(...)` from inside
`combat_attack.cpp`) were rewritten to call `rules::attackModifier(...)` directly, and none
of the forwarders were deleted. That migration is separate, incremental, TU-by-TU work for a
later session — doing it in the same pass as landing `rules.hpp` is exactly the "single
950-site sweep" this section says never to do.

**Verification**: grep-verified field-rename completeness first (every bare moved-field name
gone from code, comments only remaining), then built clean and test-verified in the
container — no compile errors, no new warnings, determinism golden byte-identical, suite at
the same 143/144. See the Handoff section above for the full results.

#### R3 — what "done" actually means (measured 2026-09-14)

Two corrections to this phase's remaining scope, both from counting rather than estimating.

**1. The call-site migration is 298 sites, not ~950.** The 950 figure was the whole `→core`
edge, and `agentName(bm, idx)` alone accounts for **607** of it — a core primitive R3 never
moved into `rules.hpp`. Actual unqualified calls to the 19 `rules::` functions still routing
through `CombatEngine`:

| TU | sites | | function | sites |
| --- | ---: | --- | --- | ---: |
| `combat_spells.cpp` | 79 | | `roll` | 182 |
| `combat_attack.cpp` | 63 | | `saveModFor` | 33 |
| `combat_riders.cpp` | 57 | | `spellSaveDcFromAbility` | 18 |
| `combat_resources.cpp` | 48 | | `rollAdvantage`/`rollDisadvantage` | 23 |
| `combat_turn.cpp` | 42 | | `spellSaveDc`/`calculateAC` | 18 |
| `combat_conditions.cpp` | 7 | | the other 13 functions | 24 |
| `combat_movement.cpp`/`_state.cpp` | 4 | | | |

`combat_core.cpp` and `combat_visibility.cpp` are already fully migrated.

**2. "Delete the forwarders" is mostly impossible, and that's correct.** **15 of the 19** are
bound to Python (`bind_combat_turn.cpp`, plus `roll` in `bind_combat_resources.cpp`), and
cross-cutting decision #1 says the Python API does not change — so `roll`, `calculateAC`,
`saveModFor`, the five aura queries and the rest keep their forwarders *permanently*. They are
the public API now, not scaffolding. Only `spellAttackMod`, `spellSaveDc`,
`spellSaveDcFromAbility` and `bestPaladinAura` are unbound and genuinely deletable.

**Recommendation: don't do the migration as a standalone sweep — it falls out of R4 for free.**
A sub-engine has no `CombatEngine this`, so anything moved into one *must* call `rules::`
directly. That is exactly what happened in R4a: `VisibilityService`'s `roll(20)` became
`rules::roll(ctx_, 20)`, which is why `combat_visibility.cpp` now shows zero unqualified calls.
Each R4 cut migrates its own TU as a byproduct, verified by the same build.

**The unit-test criterion is met, but it was only ever half-achievable as written.**
`gui/test_rules.cpp` covers what genuinely needs neither an engine nor a map: the dice layer
(`roll`/`rollAdvantage`/`rollDisadvantage` — bounds, seeded determinism, the flat modifier, the
Bardic pending bonus added exactly once even under advantage, Portent replacing the die and
stacking with modifier+bonus, one-shot advantage being d20-only, the 5e cancellation rule in
both directions, and the adv/straight/dis distributions), the weapon modifiers
(`attackModifier`/`damageAbilityMod` — STR/DEX/finesse selection, proficiency, Archery applying
to Ranged but *not* to a thrown melee weapon, Pact of the Blade's never-worse CHA option), the
spell DCs (`spellAttackMod`/`spellSaveDc`/`spellSaveDcFromAbility`, including Innate Sorcery and
the sub-10 odd-score rounding correction that C++ truncation would otherwise get wrong), and
`CombatContext`'s JSON round-trip — including a check that a restored context *continues* the
mt19937 stream while a seed-restored one diverges, which is the whole reason `to_json` stores
state rather than the seed.

`calculateAC`, `isHoldingShield`, `canEquipArmor`, `saveModFor`, `saveAdvantageFor` and the five
aura queries all take `const BattleMap&` by design, so "no BattleMap" is unreachable for them.
They stay covered by the Python suites that build a real map (`test_ac_dex.py`,
`test_paladin_auras.py`, `test_advantage_aura.py`, `test_bless.py`, …).

**Why the test is C++ and not Python — asked and decided 2026-09-14.** Binding `rules::` to
pybind11 is entirely possible (15 of the 19 need no new class bindings at all — `Agent::Stats`,
`Weapon` and `BattleMap` are already bound), so "it had to be C++" would be wrong. It was
declined deliberately: the C++ binary links against headers alone and so *cannot* construct an
engine or a map, which proves the criterion structurally rather than by convention; binding the
four dice functions would mean exposing `CombatContext`'s scratch state to Python as a writable
object; and 15 of the 19 are already bound on `CombatEngine`, so a `rules` submodule would give
Python two routes to the same logic. The full write-up, including what the cheap version would
look like if a Python-side *caller* ever wants it, is in `memory/known_limitations.md` →
*Architecture / Infrastructure* → "`rules::` has no Python binding". `README.md`'s Test section
summarises it for anyone running the suite.

### R4 — Sub-engines behind a facade — **IN PROGRESS** (3 of 7 cut, 2026-09-14)

Legend in the table below: ✅ fully cut · ◐ partially cut (see its subsection for what stayed
behind and why).

Each sub-engine owns its state struct and holds `CombatContext&`:

| Sub-engine | Owns | From |
| ---------- | ---- | ---- |
| `VisibilityService` ✅ | `visibilityMap_` | `combat_visibility.cpp` (49 in / 4 out — cleanest cut) |
| `MovementController` ◐ | `in_flight_move_`, walk/fly/swim/burrow budgets, `slipDistanceMoved_` | `combat_movement.cpp` |
| `ConditionTracker` ◐ | `activeAgentConditions_`, `nextConditionId_`, petrify/gaseous snapshots | `combat_conditions.cpp` |
| `SpellResolver` | `cast_stack_`, `activeEffects_`, `safeTargets_`, `zoneAppliedTurn_` | `combat_spells.cpp` |
| `AttackResolver` | `in_flight_attack_` | `combat_attack.cpp` |
| `ReactionArbiter` | `pending_decision_`, `in_flight_turn_` | reaction paths in `combat_riders.cpp` |
| `NpcDriver` | `npc_turn_`, npc config cache | `combat_turn.cpp` |

`CombatEngine` becomes ~281 one-line forwarders preserving the Python API exactly.

**Order matters — take the clean cuts first:** `VisibilityService` → `MovementController` →
`ConditionTracker` → `SpellResolver`/`AttackResolver` → `NpcDriver` → `ReactionArbiter`
**last**, because `pending_decision_` plus the three `in_flight_*` members are the only
genuinely entangled state in the class (4 TUs touch `pending_decision_`) and the reaction
system's park/resume flow is the hardest thing to move without behavior drift.

Two mis-groupings to fix while here, both currently in `combat_riders.cpp`:
- The turn-start reaction flow (`beginTurnFlow`, `turnStartOptions`, `turnStartReactors`,
  `applyTurnStartReaction`, `advanceTurnStart`) belongs in `ReactionArbiter`.
- Contested physical actions (`executeGrapple`, `executeGrappleEscape`, `executeShove`,
  `attemptBreakDoor`, `attemptPickLock`, `resolveGrapple`) are neither riders nor
  reactions — they want their own `ContestedActions` module.

Also flag: `combat_resources.cpp` (84 methods of class/subclass activations) is the file
guaranteed to grow forever as classes are added. It should eventually split by class
family (`resources_martial.cpp`, `resources_caster.cpp`, …), but that is a follow-on to
R4, not part of it.

#### R4a — `VisibilityService` — **DONE** (2026-09-14)

The first and cleanest cut, taken per the order above. `combat_visibility.cpp` was the only
module whose state member (`visibilityMap_`) is touched by *no* other TU — grep-confirmed
before starting — so this cut moves an owner without disturbing a single external call site.

**New `gui/visibility_service.hpp`** declares `class VisibilityService`: constructed with a
`CombatContext&`, owning `visibilityMap_`, exposing the seven methods that used to be
`CombatEngine::computeVisibility` / `getVisibility` / `canPerceiveTarget` /
`forcecageSeparates` / `areAllies` / `checkHide` / `checkHiddenAgentDetection`. Bodies stay in
`combat_visibility.cpp` (same TU, same `CMakeLists.txt` entry — no build-file change) and are
verbatim apart from the three seams below. `CombatEngine` drops `visibilityMap_`, gains
`VisibilityService vis_{ctx_};` (declared after `ctx_` so the reference it binds is already
initialized), and keeps all seven methods as one-line forwarders — so the ~60 internal call
sites across `combat_core/_attack/_spells/_turn/_riders/_movement/_conditions.cpp`, the five
pybind11 `.def`s in `bind_combat_turn.cpp`, and `main.py` are **completely untouched**. Same
"land additively, migrate call sites later, TU-by-TU" rule R3 followed for `rules.hpp`.

**Three deliberate non-rename seams**, each recorded in `visibility_service.hpp`'s header:

1. **`areAllies` deduped.** R3 copied the two-line faction test into `rules.hpp` as
   `alliedFactions` with a comment reading "dedupe when R4 extracts `VisibilityService`".
   That dedupe happened here: `rules.hpp` is now the single definition and
   `VisibilityService::areAllies` (and therefore `CombatEngine::areAllies`) forwards to it.
   Both `rules.hpp` comments saying otherwise were updated.
2. **`log_` deduped upward instead of copied sideways.** The service needs to log, and copying
   `CombatEngine::log_` into it would have created a second implementation. Instead
   `CombatContext` gained a `log(...)` member template — the single definition — and
   `CombatEngine::log_` became a one-line forwarder to it. Every one of the engine's existing
   `log_(...)` call sites is unchanged; sub-engines from here on log via `ctx_.log(...)` with
   no engine in hand. `roll(20)` inside the service is likewise now `rules::roll(ctx_, 20)`,
   which is exactly what `CombatEngine::roll` already forwards to after R3.
3. **`checkHide` no longer applies the Hidden condition itself.** It used to call
   `applyHidden`, which lives in `combat_conditions.cpp` — the future `ConditionTracker`, not
   this module. Rather than duplicate that helper or drag a cross-module dependency into the
   first cut, `VisibilityService::checkHide` sets `result.hidden` and
   `CombatEngine::checkHide` calls `applyHidden` when it sees that flag. **Observably
   identical**: in the original, nothing was logged after the `applyHidden` call and nothing
   between it and the `return` read the hidden flag back, so both the logger sequence and the
   `BattleMap` state at return are unchanged. This is the one place the move is not purely
   mechanical, and it is the seam to re-check first if the determinism golden ever drifts.

**Serialization** written now, per decision #4: `VisibilityService::to_json`/`from_json`
round-trip `visibilityMap_` as an array of `{key, level}` objects. The packed
`(source << 32 | target)` key is stored **raw** rather than unpacked into two fields, so no
index can be reinterpreted on the way back. It is a cache, but a restored engine that skipped
it would answer `Blocked` for every pair until the next `computeVisibility`, so it round-trips
rather than being treated as transient the way R3 treated the NPC-animation plumbing.

**Consequence worth knowing**: the `CombatContext&` member makes `CombatEngine` no longer
copy-*assignable* (copy construction still compiles but would alias the source's context).
Nothing copies a `CombatEngine` today — `py::class_<CombatEngine>` only registers
`py::init<uint32_t>` — but if that ever changes the engine needs explicit copy semantics that
rebind `vis_` to its own `ctx_`.

#### R4b — `MovementController` (partial: budgets, not the flow) — **DONE** (2026-09-14)

**New `gui/movement_controller.hpp`** — header-only `inline` like `combat_context.hpp`, since
every method is a one-liner over five `unordered_map<int,int>`s. Owns **five of the six** members
the table above assigns it: `walkRemaining_`, `flyRemaining_`, `swimRemaining_`,
`burrowRemaining_`, `slipDistanceMoved_`. `CombatEngine` keeps `getWalkRemaining`/…/`spendBurrow`/
`clearMovement`/`seedMoveBudgets` as forwarders, so the pybind11 surface and `main.py` are
untouched.

**`in_flight_move_` and the movement FLOW deliberately did not come along**, and this is the
first place R4's ordering rule actually bites. Measured before deciding: `moveAgent`, `jumpAgent`,
`teleportAgent`, `canAgentMove`, `placeTeleportedAgents`, `checkSlippingTerrain`, `standup` and
the `beginMove`/`advanceMove` park-resume pair touch `pending_decision_` (5×),
`activeAgentConditions_` (3×), `in_flight_turn_` (2×), `in_flight_attack_` (2×), `cast_stack_`
and `decider_` — state owned by `ReactionArbiter`, `ConditionTracker` and `SpellResolver`, none of
which exist yet, and `ReactionArbiter` is scheduled LAST on purpose. Moving the flow now would
mean threading four unextracted members into the controller. **The flow travels with
`ReactionArbiter`; `in_flight_move_` stays on `CombatEngine` until then.** What landed is the
half with no cross-module coupling whatsoever.

**No `CombatContext&` member**, unlike `VisibilityService` — nothing in the budget layer rolls a
die or logs, so the reference would be dead weight and would delete `CombatEngine`'s
copy-assignment for no reason. (The flow functions that *do* roll and log are exactly the ones
staying on the engine.) A sub-engine takes `CombatContext&` when it needs one, not on principle.

**Ten direct field pokes from outside the module were routed through the controller**, each
checked to be behaviour-identical rather than assumed:
- `combat_turn.cpp` beginTurn's four `std::max(0, …)` budget seeds → one `seedMoveBudgets` call
  (which applies the same clamp), and its `slipDistanceMoved_[idx] = 0` → `resetSlipDistance`.
- `combat_riders.cpp`'s Speed-0 rider and `combat_movement.cpp`'s Sentinel-halt commit, both
  zeroing all four budgets → `seedMoveBudgets(idx, 0,0,0,0)` (`max(0,0) == 0`).
- `combat_resources.cpp`'s Instinctive Pounce `walkRemaining_[idx] += speed/2` → `grantWalk`,
  which is additive and un-clamped on the high side exactly as the raw `+=` was.
- `standup`'s hand-rolled `walkRemaining_.find` → `getWalkRemaining`.
- `checkSlippingTerrain`'s `int& slip_counter` reference → `addSlipDistance` (accumulate and
  return the new total) + `resetSlipDistance`. Same per-iteration re-read semantics.

`grantWalk`/`resetSlipDistance`/`addSlipDistance` have no engine-level equivalent and are not
exposed to Python — they exist solely to give those pokes a typed route. Note `clearMovement`
still does **not** clear the slip counter, matching the original exactly.

**Serialization** per decision #4, and it matters more here than for the visibility cache: a
mid-combat restore with empty budgets would let a creature that had already moved move again.
Int-keyed maps serialize as arrays of `{agent, feet}`, the same choice R3 made for
`agent_portent_round_used_`.

**Verification** (2026-09-14, `angry_goodall`): clean build, no errors, no new warnings;
`test_determinism.py` byte-identical to the golden; `test_rules` 62/62;
`tests/run_all_tests.py` **144/145** with only the pre-existing `test_monk.py` failure. The
movement paths are densely covered — `test_movement.py`, `test_forced_movement_oa.py`,
`test_grapple.py`, `test_teleportation.py`, `test_reactions.py` all pass, which exercises the
budget seeds, the Sentinel halt, and the slip counter.

#### R4c — `ConditionTracker` (the container, not the effect logic) — **DONE** (2026-09-14)

The first cut where the member is genuinely **shared** — the plan's opening analysis named
`activeAgentConditions_` and `pending_decision_` as the only two — so the boundary is drawn
differently from R4a/R4b, and that is the main thing to understand here.

**New `gui/condition_tracker.hpp`** owns all four members the table assigns it:
`activeAgentConditions_`, `nextConditionId_`, `petrifySnapshots_`, `gaseousSnapshots_` — and the
`PetrifySnapshot`/`GaseousSnapshot` structs, which moved out of `CombatEngine`'s private section.
`CombatEngine` is down to one member, `ConditionTracker conditions_;`.

**Where the line is drawn**: the **container** and its bookkeeping moved (stamp an id, append,
look up by id, erase by id, drop a batch of ids, hand out the list, store/find/erase a snapshot).
The **effect logic** stayed on `CombatEngine` — `addAgentCondition`'s ~230 lines of per-condition
application, `onConditionEnded`'s teardown chokepoint, `resolveDelayedEffect`, and the two tick
drivers. Those call into damage, spells, concentration and every `applyXxx`; they are engine
orchestration that happens to write to this container, not container logic. Unlike R4a/R4b,
where the whole file had one obvious owner, `combat_conditions.cpp`'s 37 methods do not — and
~830 of its lines (the `applyParalyzed`/`applyBlinded`/… flag setters) never touch the container
at all.

**The 53 call sites**: almost all were read-only range-fors and became `conditions_.all()`.
Exactly three mutate in place — `combat_turn.cpp:825`, `:927` and `:1103` (the last deliberately
index-based, because `removeAgentCondition` mutates the vector mid-iteration) — and those go
through `mutableAll()`. That accessor is a **deliberate, documented transitional seam**, not an
oversight: it is the honest statement that the tick logic still lives outside the tracker, and it
should disappear when that logic moves. Everything else is a typed route.

Three subtleties preserved rather than tidied:
- `nextId()` and `append()` are two calls, not one `add()`. `addAgentCondition` stamps the id
  **first**, runs its long apply logic — which can itself add conditions — and appends **last**.
  Merging them would reorder the container relative to the ids, which is observable.
- `take(id, out)` copies the entry out **after** erasing it, because `removeAgentCondition`'s
  caller fires the Vistani-curse kickback on that copy and the teardown can cascade back into
  this container via `dropConcentration`.
- `dropByIds` reproduces the old "rebuild a `remaining` vector in order" exactly, deduped from
  the two tick drivers that each had their own copy of it.

**Both snapshot maps came along, including the leak.** `petrifySnapshots_` had 3 touches in
`combat_spells.cpp` (`curePetrified`, i.e. Flesh to Stone's reversal); those now go through
`conditions_.findPetrifySnapshot()` / `erasePetrifySnapshot()`. Keeping the pair together beat
splitting them — they are the same kind of thing (pre-transformation stat snapshots) and the
alternative was leaving one on the engine for no reason but call-site count.

**Serialization** per decision #4, and this is the one that matters: active conditions are the
biggest chunk of real per-encounter state `MULTIPLAYER_PLAN.md` needs. `ActiveAgentCondition`'s
33 fields get their JSON mapping as **free functions in `combat_conditions.cpp`**, not as members
on the struct — deliberately, so `battle_map.hpp` (included by nearly every TU) gains neither a
diff nor an nlohmann dependency. Enums round-trip through their underlying int; `from_json`
starts from a default-constructed condition so a payload missing a field inherits the default
rather than a zero.

**One include-graph decision worth keeping**: the tracker's method bodies live in
`combat_conditions.cpp`, not inline in the header, so `condition_tracker.hpp` needs only a
forward declaration of `ActiveAgentCondition`. A header-only tracker would have forced
`battle_map.hpp` (59 KB) into `combat.hpp`, which today only forward-declares it.

**Verification** (2026-09-14, `angry_goodall`): clean build, no errors, no new warnings;
`test_determinism.py` byte-identical to the golden; `test_rules` 62/62;
`tests/run_all_tests.py` **144/145** with only the pre-existing `test_monk.py` failure. Dense
coverage on exactly these paths — `test_conditions.py`, `test_condition_saves.py`,
`test_hold_person_endturn.py`, `test_petrified.py`, `test_misty_escape.py` (gaseous snapshots),
`test_spells_tier2.py` (Flesh to Stone → `curePetrified`), `test_vistani.py` (the kickback
cascade), `test_haste.py` (lethargy added during teardown) all pass.

#### Next cut: `SpellResolver` / `AttackResolver`

Per the order at the top of this section. Not yet measured — do that first, the way R4b and R4c
were scoped, rather than guessing from the file sizes. Note that `ReactionArbiter` stays last,
and that it now carries three deferred items with it: `in_flight_move_` plus the movement flow
(R4b), and `ConditionTracker::mutableAll()`'s removal once the tick drivers move.

### R5 — Serialization

With R3+R4 done, each state struct gets `to_json`/`from_json`, and `CombatEngine` gets
`snapshot()` / `restore()`. `rng_` must serialize the **mt19937 state**, not the seed.
Python-side turn sequencing (`App.initiative_order`, `App.turn_idx`, `main.py:677-680`) has
to round-trip too, or a restored engine comes back with no turn loop.

This closes the `MULTIPLAYER_PLAN.md` blocker and independently delivers mid-combat
save/resume, crash recovery, and fully reproducible bug reports from live play. See that
plan's TODO for the full member list — it matches the R4 table above almost exactly, which
is the strongest evidence the two efforts are the same work.

---

## Rejected options

| Option | Why not |
| ------ | ------- |
| **pImpl the private state** | Private block is only 2% of header churn. Solves nothing. |
| **`combat_types.hpp` alone** | Cosmetic without R1 — all 10 combat TUs still need the class. |
| **C++20 modules** | pybind11 + the CMake/Docker toolchain will fight this hard, for a benefit R1+R2 already deliver. Revisit in years, not now. |
| **Split by inheritance** (`CombatEngine : AttackMixin, SpellMixin, …`) | Keeps one object and one header — the actual problem — while adding template/diamond complexity. Composition per R4 is strictly better. |
| **Big-bang rewrite** | ~23k lines of dense, live-play-validated rules with a 30-suite test net. Incremental with a determinism oracle is the only responsible path. |

---

## Risks

- **Behavior drift during mechanical moves.** Mitigated by R0's determinism harness — do
  not start R3 without it.
- **R4 facade bloat.** 281 forwarders is a lot of boilerplate; if it becomes unpleasant,
  generate it rather than hand-writing it, and keep the generator in `tools/`.
- **Merge pain against in-flight feature work.** `combat.hpp` is touched in 63% of commits,
  so a long-lived refactor branch will conflict constantly. Each phase should be short and
  land quickly; prefer pausing feature work for a few days over a multi-week branch.
- **Reaction system is the sharp edge.** `pending_decision_` + `in_flight_*` + the
  park/resume flow across `beginAttack`/`beginCast`/`beginMove`/`beginTurnFlow` is the one
  place where "mechanical move" is a lie. Budget real time for it; it is deliberately last.

## Success criteria

- `tests/run_all_tests.py` green after every phase, with byte-identical fixed-seed replay.
- Adding a new spell or subclass feature no longer requires editing `combat.hpp`.
- Incremental build after a one-line rules change drops from "all 11 TUs + bindings" to a
  single TU (measure against the R0 baseline).
- ~~`rules.hpp` has direct unit tests that construct no `CombatEngine` and no `BattleMap`.~~
  **Met 2026-09-14** — `gui/test_rules.cpp` (62 checks) via `tests/test_rules.py`, the tree's
  only non-Python suite. Only partly achievable as written; see "R3 — what 'done' actually
  means" for which functions are structurally out of reach, and `memory/known_limitations.md`
  for why `rules::` is deliberately left unbound.
- Every module's state round-trips through `snapshot()`/`restore()`.
