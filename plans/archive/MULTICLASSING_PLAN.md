# Multiclassing Implementation Plan

**Model policy: Opus-only.** Every phase below is correctness-critical or depends
on judgment that has no compiler/test backstop (especially Phase 2). Do not
delegate any phase to a faster model. The volume work in Phase 1 is not worth
splitting off because it cannot safely precede the Phase 0 data-model decision.

**Scope note:** This is a large feature. Build and land it phase-by-phase per the
combat-sim scoping rule — one phase per diff, tests green before the next starts.
HP-by-hit-dice and spells-known/prepared bookkeeping are explicitly **out of
scope** (HP is entered manually today; spell lists are authored on the agent).

---

## The core problem

Class identity lives in **two single-valued fields** on `Agent::Stats`:

- `CharacterClass character_class` — one enum (`agent.hpp:183`)
- `int char_level` — one integer 1–20 (`agent.hpp:184`)

The single-`char_level` field silently conflates **three** different concepts
that multiclassing forces apart:

1. **Total character level** — proficiency bonus, ASI/feat cadence, HP. Stays a sum.
2. **Class level** — *every class-feature gate.* "Flurry at 10" = **Monk** 10, not
   character 10. A Fighter 5 / Monk 5 has total level 10 but Monk level 5.
3. **Caster level** — a *combined* value for multiclass spell slots (not a sum,
   not a single class level; see Phase 3).

The mechanical `==` → `hasClass()` sweep is the cheap part. The load-bearing wall
is Phase 2: telling apart, at 114 sites, which of these three a `char_level >= N`
actually meant.

### Concrete site inventory (measured)

`== / != CharacterClass::X` gates — **217 total**:

| File | Count | | File | Count |
|---|---|---|---|---|
| combat_attack.cpp | 58 | | combat_turn.cpp | 11 |
| combat_resources.cpp | 62 | | combat_core.cpp | 8 |
| combat_spells.cpp | 44 | | rpg_bindings.cpp | 25 |
| combat_riders.cpp | 17 | | others (6 files) | 1 each |

`char_level >= N` feature gates — **115 total**:

| File | Count | | File | Count |
|---|---|---|---|---|
| combat_attack.cpp | 35 | | combat_turn.cpp | 9 |
| combat_spells.cpp | 26 | | combat_core.cpp | 5 |
| combat_resources.cpp | 24 | | others | 1 each |
| combat_riders.cpp | 13 | | | |

---

## Phase 0 — Data model (design gate; nothing ships until this is settled) ✅ DONE

**Status:** Landed in `gui/agent.hpp` (header-only, no behavior change; build clean/green).
- `std::array<uint8_t, NumCharacterClass> class_levels{}` is the new source of truth.
- Accessors `classLevel(c)` / `hasClass(c)` / `totalLevel()` added (Phase 1/2 targets).
- `character_class` + `char_level` kept as derived transition mirrors; `recompute_class_mirrors()` rebuilds them from the array.
- `set_class_level` reworked as single-class reset (fills 0 first); new additive `add_class_level`.
- No gate rewrites; bindings/serializer reshape deferred to Phase 1.


Decision to lock **before any edits**, because Phase 1's sweep depends on the
field's final shape:

- Replace `CharacterClass character_class` with per-class levels:
  ```cpp
  std::array<uint8_t, NumCharacterClass> class_levels{};  // index by enum
  ```
- Derive, don't store, the aggregates:
  - `int totalLevel() const` — sum of `class_levels` (replaces most `char_level` reads).
  - `int classLevel(CharacterClass c) const` — `class_levels[c]` (the Phase-2 target).
  - `bool hasClass(CharacterClass c) const` — `class_levels[c] > 0`.
- **Keep `char_level` as a derived, read-only mirror of `totalLevel()`** during the
  transition so the 247 existing reads keep compiling. Recompute it in
  `set_class_level` and after deserialization. This lets Phase 1 and Phase 2 land
  independently instead of in one 500-site megadiff.
- `set_class_level(cls, level)` becomes **additive**: it sets `class_levels[cls]`
  and recomputes `char_level`. Add `add_class_level(cls, level)` as the explicit
  multiclass entry point; keep `set_class_level` meaning "single-class reset"
  (clear the array first) so existing single-class callers are unchanged in intent.

**Backward-compat helper strategy:** provide `hasClass()` and do **not** open-code
`std::array` lookups at 217 sites. One helper, reviewed once.

**Deliverable:** header-only change + helpers + the derived-mirror wiring, compiles
with no behavior change (array has exactly one nonzero entry for every existing
agent). No gate rewrites yet.

---

## Phase 1 — Mechanical `==` → `hasClass()` sweep (large, shallow, compiler-checked) ✅ DONE

**Status:** Landed. All 205 real class-identity gates across the engine converted
(combat_resources 62, combat_attack 58, combat_spells 44, combat_riders 17,
combat_turn 11, combat_core 8, agent.hpp 1, and four single-site files); the 12
`rpg_bindings.cpp` matches are docstrings, and agent.hpp's two remaining hits are
mirror machinery (`add_class_level`) and a non-gate (`get_caster_type(...)`).

Two deliberate deviations from the sketch below, both to keep the sweep safe and
the test suite green:
- **`lacksClass(c)` companion helper** (`= !hasClass(c)`) added alongside `hasClass`.
  `!=` gates became `.character_class != c → .lacksClass(c)`, making the ENTIRE sweep
  an object-independent, collision-free **suffix** rewrite (leaves the object token
  untouched) with no `!`-placement to get wrong — eliminating the negation-bug risk
  this phase flags.
- **`character_class`/`char_level` stay read/WRITE**, not read-only. ~200 test sites
  (and other code) assign them directly as `stats.character_class = X; stats.char_level = N`.
  Since gates now read `class_levels`, those scalar writes route through compat setters
  (`setPrimaryClassMirror` / `setCharLevelMirror`) that keep `class_levels` in sync for
  the single-class case two scalars can express. `class_levels`/`has_class`/`class_level`/
  `total_level`/`add_class_level` are also now bound. Serialization adds
  `agent_class_levels` ({class:level} dict) with legacy-scalar fallback on load.

Convert all 217 comparison sites:

- `s.character_class == CharacterClass::Monk` → `s.hasClass(Monk)`
- `s.character_class != CharacterClass::Monk` → `!s.hasClass(Monk)` *(watch every
  negation — this is the only place bugs hide in Phase 1)*

Risk is low: a wrong substitution fails the build or a test. Do it file-by-file,
biggest first (combat_resources 62, combat_attack 58, combat_spells 44).

**Serialization round-trip** (per the stats-serializer rule) — the class field
changes shape, so BOTH sides need updating:
- `dict_to_stats` in the loader **and** the `main.py` save block: serialize
  `class_levels` as a `{class_name: level}` dict (back-compat: read the old scalar
  `character_class` + `char_level` if present and fold into the array).
- pybind11: replace the `def_readwrite("character_class", …)` (`rpg_bindings.cpp:310`)
  with bindings for the array/helpers; keep `char_level` readable.

**Deliverable:** all class-identity checks go through `hasClass()`; save/load
round-trips a single-class agent identically. Still no per-class-level semantics.

---

## Phase 2 — Per-class level gates (THE hard phase; Opus, manual, one at a time) ✅ DONE

**Status:** Landed (build clean, tests green). Every `char_level` comparison and
class-scaling read across all 8 engine files audited site-by-site and converted to
`classLevel(<thatclass>)` — the class read off the adjacent subclass check or the
enclosing `hasClass/lacksClass` guard. Also converted the non-comparison class-scaling
reads that carry the same multiclass bug (martial-arts die, rage-damage bonus,
sneak-attack dice, Assassinate/Undying-Sentinel/Celestial-Resilience/Arcane-Ward/
Wild-Shape-THP/Lay-on-Hands/Inspiring-Smite/Divine-Fury/Eldritch-Spear-range scaling).
Deliberately left as total/caster level: `getNumTargetsForSpell(…char_level…)` (cantrip
beam scaling is total character level per RAW), `compute_class_slots(…, char_level)`
(caster level → Phase 3), and the `char_level`/`character_class` mirror-setter plumbing.
New test `tests/test_multiclass_gates.py` (registered in `run_all_tests.py`) proves a
Fighter 5/Monk 5 gets each class's low-level features but neither class's higher-level
feature via the bound eligibility predicates.

Audit all **115** `char_level >= N` sites. Each is one of:

- **Class-feature gate** (the large majority) → `classLevel(<thatclass>) >= N`.
  The class is almost always evident from the enclosing function's early guard
  (e.g. code already inside a `if (!hasClass(Monk)) return` block gates on Monk).
- **Total-level gate** (proficiency bonus, feat/ASI cadence, HP-per-level like the
  `2 * char_level` boon at `agent.hpp:688`) → leave as `totalLevel()` / `char_level`.
- **Caster-level gate** (spell-related) → defer to Phase 3, mark it.

Process, to keep it tractable and reviewable:
1. Generate the worklist: `grep -n "char_level >=" *.cpp *.hpp` → a checklist file.
2. For each site, record in a scratch table: file:line, enclosing feature, which of
   the three categories, and the replacement. **No blind sweep** — every line gets
   an individual judgment call.
3. Convert, compile, run the class-feature tests after each file.

Same treatment for the ~114 `char_level >=` companions inside subclass gates
(subclasses already coexist as separate fields — Phase 4 good news — but their
level checks are class-level too).

**Failure mode this phase exists to prevent:** compiles clean, tests may pass, and
a Fighter 5/Monk 5 silently gets *both* classes' level-10 capstones. There is no
automatic backstop — hence Opus-only and site-by-site.

**Deliverable:** a genuine Fighter 5/Monk 5 test agent gets Monk-5 and Fighter-5
features and **neither** class's level-10 feature. New test: `test_multiclass_gates.py`.

---

## Phase 3 — Multiclass spellcasting (self-contained feature) ✅ DONE

**Status:** Landed (build clean, tests green). Added `Agent::Stats::computeMulticlassSlots()`
(`agent.hpp`, bound as `compute_multiclass_slots`) implementing the PHB rule: 0 non-Warlock
casters → pact-or-empty; exactly 1 → that class's OWN table (single-class Paladin/Ranger keep
kHalf, EK/AT keep the third-caster table); 2+ → combined level = full + ⌊half/2⌋ + ⌊third/3⌋
→ kFull. Wired into `set_class_level`/`add_class_level` (single-class results identical) and the
EK/AT resource-init overrides (`combat.cpp`, subclass known there). Warlock Pact Magic stays a
SEPARATE pool and is NOT folded in — a Warlock-only caster returns kPact; a Warlock + other-caster
multiclass returns only the non-Warlock slots (the parallel pact pool for that combo is deferred:
it needs new pact_slots_max/_remaining fields + rewiring ~15 pact-consumption sites). New test
`tests/test_multiclass_slots.py` (registered) covers single-class-unchanged, full+full (Cleric 3/
Wizard 3 → combined 6 = kFull[6] = 4/3/3), full+half rounding, subclass-gated full+third (EK), and
the Warlock exclusion. (Plan prose "4/3/2" was the level-5 row; combined level 6 is 4/3/3 — the
test trusts the engine table.)

`compute_class_slots(cls, char_level)` (`character_class.hpp:27`) takes ONE class.
Multiclass slots need a combined caster level:

- **Combined caster level** = (full-caster class levels) + ⌊half-caster/2⌋ +
  ⌊third-caster/3⌋, then look up the existing full-caster table (`kFull`).
  - Full: Bard, Cleric, Druid, Sorcerer, Wizard.
  - Half: Paladin, Ranger (and count Fighter/Rogue only if EK/AT — third).
  - Third: Eldritch Knight, Arcane Trickster (÷3).
- **Warlock Pact Magic stays a SEPARATE pool** — it does not fold into the combined
  slots. Keep `kPact` keyed on Warlock level alone, tracked in parallel.
- New `compute_multiclass_slots(const Stats&)` replaces the single-class call inside
  `set_class_level` / resource init. Touches cast-level tracking — verify Dispel/Aid
  read the right effective level.

Spells known/prepared remain per-class and authored on the agent (out of scope).

**Deliverable:** Cleric 3/Wizard 3 has 4/3/2 (level-6 full-caster row), not two
separate level-3 tables. `test_multiclass_slots.py`.

---

## Phase 4 — Resource init merge ✅ DONE

**Status:** Landed (edits only; user builds/tests). The `switch(cls)` body was
extracted into `Agent::Stats::applyClassResources(cls, level)` (no `resources.clear()`
— the weapon-mastery switch moved inside it too, guarded by `addFeat`'s dup check).
`initializeClassResources` is now a thin wrapper (clear + one apply; behavior identical
to before). New `initializeMulticlassResources()` clears once, then iterates the
populated `class_levels` calling `applyClassResources` per class so resources ACCUMULATE.
Extra Attack does not stack: `num_attacks` is reset to 1 before each class body and the
running **max** is taken (Fighter 11's 3 attacks beats Barbarian 5's 2), order-independent.
One-shot bumps (Primal Champion / Body and Mind / Draconic HP) stay guarded by their
`*_applied` flags. Bound as `initialize_multiclass_resources`. New test
`tests/test_multiclass_resources.py` (registered). GUI wiring to call it is Phase 5.

`initializeClassResources(cls, level)` is a `switch(cls)` that calls
`resources.clear()` at the top (`combat.cpp:20`) — a **merge hazard**. For
multiclass it must run for each class and accumulate:

- Clear once, then iterate the populated `class_levels` calling the per-class body
  with that class's level (refactor the switch body into a helper that does NOT
  clear).
- Watch resources that must not double-count `num_attacks` (Extra Attack from two
  martial classes still grants one extra attack, not two) and idempotent one-shots
  (`primal_champion_applied` etc.).

**Deliverable:** Barbarian 5/Fighter 5 has Rage uses AND Second Wind AND a single
Extra Attack. `test_multiclass_resources.py`.

---

## Phase 5 — GUI ✅ DONE

**Status:** Landed (Python edits only; USER builds/tests). CLOSES the feature.
`StatsDialog` (`gui/dialogs.py`) uses a "focused class" model: the existing class
cycle + level stepper + subclass picker edit ONE class at a time, backed by two
maps (`_class_levels`, `_subclasses`) that persist the whole build across focus
switches. Cycling class commits the focused stepper/subclass then loads the target;
level stepper lo dropped 1→0 (0 removes the class). A "Build: Fighter 5 / Monk 5 —
Total level: 10" readout is derived live. `_confirm` passes the two maps as new
trailing callback args; `_on_stats_ok` (`gui/main.py`) applies each class's subclass,
does `set_class_level(primary)` + `add_class_level(rest)`, then
`initialize_multiclass_resources()`. Single-class specialized guards changed to class
MEMBERSHIP (`X in cl_map`). Loader (`agent_loader.py`) switched to
`initialize_multiclass_resources()`. New test `tests/test_multiclass_gui_roundtrip.py`
(registered) covers the data path the pygame dialog feeds (Fighter5/Monk5,
Cleric3/Wizard3 combined slots, legacy single-class).

- Class picker → multi-select (class + per-class level steppers), writing through
  `add_class_level`. Total-level readout derived.
- Subclass pickers already per-class — surface one per chosen class.
- Feed the multiclass dict through the existing stats save/OK path.

---

## Sequencing & risk

| Phase | Effort | Risk | Backstop |
|---|---|---|---|
| 0 Data model ✅ | ~0.5 day | low | compiler |
| 1 `==` sweep + serialize | ~1 day | low | compiler + round-trip test |
| 2 Level gates | ~2–3 days | **high** | **none — manual audit** |
| 3 Spell slots | ~1–2 days | med | targeted test |
| 4 Resource merge | ~0.5 day | med | targeted test |
| 5 GUI | ~1 day | low | manual |

**Do not ship Phase 1 alone.** Without Phase 2 you have a character who "is a Monk
and a Fighter" and gets both capstones at total level 10 — worse than no
multiclassing. Phases 0→1→2 are the minimum coherent unit; 3–5 layer on after.

**User owns all builds, commits, and test runs.** This plan produces edits only.
