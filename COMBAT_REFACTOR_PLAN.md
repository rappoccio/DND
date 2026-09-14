# Combat Engine Refactor — Implementation Plan

Status: **PLANNING** (assessment done 2026-08-11 — discuss and lock the cross-cutting
decisions before any code moves). No implementation started.

Goal: break up the `CombatEngine` god class so that (a) adding a spell/feat/subclass stops
triggering a full rebuild of every combat TU, (b) the rules layer becomes testable without
instantiating an engine, and (c) combat state becomes serializable — which is the same work
`MULTIPLAYER_PLAN.md` is currently blocked on.

Scope rule (per `memory/feedback_scope_combat_sim.md`): this is a **structural** refactor.
No behavior changes, no new features, no bug fixes bundled in. Every phase must leave
`tests/run_all_tests.py` green with byte-identical results for a fixed seed.

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
| **R3** | Extract `CombatContext` + `rules.hpp` | medium | 1–2 weeks | dissolves the 950-call edge; testable rules |
| **R4** | Decompose into sub-engines behind a facade | high | multi-week | true modularity |
| **R5** | State serialization → snapshot/restore | medium | 1–2 weeks | `MULTIPLAYER_PLAN.md`, mid-combat save |

R0–R2 are mechanical and near-risk-free — do them regardless of whether R4 ever happens.
R3 is the highest-leverage single step. **R4 should not start until R3 has settled.**

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

### R1 — Split the bindings

`rpg_bindings.cpp` is the second god file: 4,850 lines, touched in 150 of the last 200
commits, and almost certainly the slowest TU in the build (pybind11 template
instantiation). Split into `bind_types.cpp`, `bind_combat_attack.cpp`,
`bind_combat_spells.cpp`, `bind_combat_resources.cpp`, `bind_combat_turn.cpp`,
`bind_battle_map.cpp`, with a shared `bindings_internal.hpp` holding the
`py::class_<CombatEngine>` handle that each TU adds `.def`s to.

No C++ API changes, no Python API changes. The binding name→method mapping is mechanical
and the test suite covers it densely.

While here: the **43 bound-but-never-referenced** methods (`activate_starry_form`,
`apply_shield`, `can_bend_luck`, `get_battle_observation`, `resolve_attack`, `reseed`, …)
are worth triaging — some are dead, some are RL-facing and deliberate, some are reaction
internals that leaked into the API. Delete or document; do not silently keep.

### R2 — `combat_types.hpp`

Move the ~900 lines of result/action structs (`combat.hpp` lines 63–967: `HideResult`,
`AttackResult`, `Attack`, `SpellAction`, `SpellResult`, `ReactionCtx`, `InFlight*`,
`NpcTurnState`, …) into `combat_types.hpp`.

Alone this is cosmetic — all 10 combat TUs still need the class. **Its value is entirely in
combination with R1**: the binding TUs that only bind structs then depend on
`combat_types.hpp` and not `combat.hpp`, so the 40% of header churn landing in the struct
region stops rebuilding them.

### R3 — `CombatContext` + `rules.hpp` ⭐

The highest-leverage step.

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

### R4 — Sub-engines behind a facade

Only after R3 settles. Each sub-engine owns its state struct and holds `CombatContext&`:

| Sub-engine | Owns | From |
| ---------- | ---- | ---- |
| `VisibilityService` | `visibilityMap_` | `combat_visibility.cpp` (49 in / 4 out — cleanest cut) |
| `MovementController` | `in_flight_move_`, walk/fly/swim/burrow budgets, `slipDistanceMoved_` | `combat_movement.cpp` |
| `ConditionTracker` | `activeAgentConditions_`, `nextConditionId_`, petrify/gaseous snapshots | `combat_conditions.cpp` |
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
- `rules.hpp` has direct unit tests that construct no `CombatEngine` and no `BattleMap`.
- Every module's state round-trips through `snapshot()`/`restore()`.
