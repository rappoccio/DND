# Sorcerer Metamagic — Implementation Plan (2026-07-13)

Wire the **already-complete** Metamagic engine to the GUI. This is almost entirely a **GUI job**:
the C++ engine + pybind11 bindings for all 10 options are done and correct (SP costs verified against
SRD_CC_v5.2.pdf p.66). The only C++ change in this whole plan is **Phase 3 (Twinned)**.

The UX (per the user): **armed toggle buttons on the combat sidebar** (like Overchannel / Tides of
Chaos). Arming an option modifies the *next* spell cast. The engine already validates applicability
**before spending SP** and no-ops with a logged reason if the armed option doesn't fit the chosen
spell — so a mismatched armed toggle costs nothing.

## Ground rules (read first)
- **Do NOT run builds, tests, git, or any state-mutating Bash.** The user runs all builds and owns all
  commits. Propose edits only. (`gui/CLAUDE.md`, memory: `feedback_user_runs_builds`,
  `feedback_user_owns_git_commits`.)
- **Fix root cause in C++.** No Python-side workarounds for engine behavior. (memory:
  `feedback_fix_root_cause`.) Phase 3's Twinned fix belongs in the engine, not a GUI hack.
- **Every new `rpg.Stats` field round-trips in THREE places or it resets on save/reload** (memory:
  `stats_serializer_roundtrip`):
  1. C++ field on `Stats` (`gui/agent.hpp`) + `def_readwrite` in `gui/rpg_bindings.cpp`.
  2. Load: `dict_to_stats` in `gui/agent_loader.py`.
  3. Save: the save dict block in `gui/main.py` (~line 10426, where `elemental_adept_types` /
     `draconic_affinity_type` are written).
  **`metamagic_options` already exists + is bound but is NOT serialized** — Phase 2 adds its round-trip.
- Each task names the **precedent to clone** — match that idiom, don't invent a new shape.
- Register new tests in `gui/test_sorcerer.py`'s `__main__` block. Leave the user a "what to verify"
  summary. **You do not build or run — the user does.**

---

## What already exists (do NOT rebuild)

**Engine (`gui/combat_spells.cpp`) — all 10 options, verified vs SRD p.66:**

| Option | SP | Engine site | Effect |
|---|---|---|---|
| Careful    | 1 | `:572` | Allies excluded from AoE (Sculpt-style, capped at CHA mod). Save spells only. |
| Distant    | 1 | `:581` | Range ×2 (or 30 ft if touch). |
| Empowered  | 1 | `:588`,`:819` | Reroll low damage dice, up to CHA mod. **(Working — the "Deferred" note at `combat.hpp:147` is STALE.)** |
| Extended   | 1 | `:585` | Duration ×2. Needs duration ≥ 2 rounds. |
| Heightened | 2 | `:265` | One target has Disadvantage on its save. |
| Quickened  | 2 | `:596` | casting_time → Bonus Action (`result.cast_as_bonus_action`). |
| Seeking    | 1 | `:217` | Reroll a missed spell attack. **Stackable** with one other option (SRD). |
| Subtle     | 1 | `:530` | **Deliberate no-op** — V/S/M components aren't simulated. |
| Transmuted | 1 | `:604` | Rewrite elemental damage to a chosen type (needs `transmuted_damage_type`). |
| Twinned    | 1 | `:610` | **Broken for the common case** — see Phase 3. |

- Applicability gate + SP spend: `combat_spells.cpp:532-567`. Mismatched option → logged reason, **no SP spent**.
- SP cost table: `metamagicSpCost()` `combat_spells.cpp:2306`.
- Bindings (all done): `SpellAction.metamagic`, `.careful_targets`, `.transmuted_damage_type`,
  `CombatEngine.metamagic_sp_cost`, `Stats.metamagic_options` (`rpg_bindings.cpp:494,1221,1443`).
- Enum: `MetamagicOption` (`character_class.hpp:233`): NONE, Careful, Distant, Empowered, Extended,
  Heightened, Quickened, Seeking, Subtle, Transmuted, Twinned.

**GUI (`gui/main.py`): ZERO metamagic references.** Everything below is net-new GUI.

---

## Framework (used by all phases)

**New GUI state on the app (near `self.overchannel_armed`, `main.py:508`):**
- `self.armed_metamagic = rpg.MetamagicOption.NONE` — the single armed option (radio-style; SRD p.65:
  "only one Metamagic option on a spell").
- `self.armed_seeking = False` — Seeking is the one option that stacks with another (SRD `:600` note).
- `self.pending_metamagic_transmute_type = -1` — chosen replacement damage type for Transmuted.

**Read the armed state at BOTH player cast sites** — clone the existing `action.overchannel = …` lines:
- Targeted/Multiple: `main.py:9521-9533`.
- AoE: `main.py:9881-9886`.

Add a small helper `_apply_armed_metamagic(action, sp, caster_idx)` called at both sites:
```
if self.armed_seeking and self.armed_metamagic == NONE:
    action.metamagic = Seeking
elif self.armed_metamagic != NONE:
    action.metamagic = self.armed_metamagic
    if action.metamagic == Transmuted:
        action.transmuted_damage_type = self.pending_metamagic_transmute_type
    if action.metamagic == Careful:
        action.careful_targets = <party allies within/near the AoE>   # Phase 1 detail below
# (Superseded by Phase 4: the helper now builds an ordered ≤2 list via _armed_metamagic_options()
#  and writes action.metamagic + action.metamagic2 — Seeking stacks, and Sorcery Incarnate licenses
#  any second option.)
```
Disarm after a successful cast? **No** — Overchannel stays armed until manually toggled; match that so a
sorcerer can keep an option armed across turns. (Revisit only if playtesting wants auto-disarm.)

**Sidebar buttons** — clone the Tides/Bend-Luck/Trance draw+gate+click pattern:
- Declare each `Button` once near `main.py:1371` (dummy rect; positioned each draw).
- Draw+gate in the sidebar pass near `main.py:14624`. **Per-button gate:** caster is Sorcerer,
  `char_level >= 2`, the option is in `stats.metamagic_options` (learned — Phase 2), and
  `Sorcery Points >= metamagicSpCost(option)`. Show the armed one highlighted (mirror Overchannel's
  ARMED/disarmed visual at `main.py:16303-16309`).
- Click handler (event loop, near the Bend-Luck/Tides handlers `main.py:17559-17600`): toggle
  `self.armed_metamagic` (radio — arming one clears the others; clicking the armed one disarms to NONE);
  Seeking toggles `self.armed_seeking` independently. Log "Metamagic X ARMED (cost SP) / disarmed".

---

## PHASE 1 — Learned-options picker (Stats dialog) + round-trip  ✅ DONE + GREEN (2026-07-13)

Build this FIRST (user's call): the sidebar buttons in Phase 2 gate on `stats.metamagic_options`, so
the sorcerer must be able to *learn* options and have them persist.

**Rule (SRD p.65):** learn **2 options at L2**, **+2 at L10**, **+2 at L17** (max 6). On a level-up you
may swap one — irrelevant to a combat sim; skip swap tracking.

### 1a. `MetamagicDialog` — clone `InvocationDialog`
`InvocationDialog` (`dialogs.py:447`, `.show(callback, current_codes, eff_level)`) is a scrollable
checkbox picker with greyed/locked rows — the exact shape needed.
- New `MetamagicDialog` listing the **9 selectable** options (exclude **Subtle** — pure no-op here; or
  include it greyed with a "flavor only" note — recommend **exclude** to avoid dead picks). Each row shows
  the SP cost.
- Cap selections at the level-derived count: `known = 2 if L>=2 else 0; if L>=10: 4; if L>=17: 6`. When at
  the cap, un-selected rows render greyed (mirror InvocationDialog's locked-row rendering).
- Commit chosen options (as `MetamagicOption` values) to the callback on dismiss.

### 1b. Wire into `StatsDialog` (mirror the Invocations button end-to-end)
Follow every invocations touch-point:
- Field + rects: `dialogs.py:1420-1423` (`_eldritch_invocations`, `_invocation_dialog`, button rect).
- Load current from stats on open: `dialogs.py:1449`.
- Instantiate dialog: `dialogs.py:1459`.
- Launch button click: `dialogs.py:1604-1608`.
- Callback storing the result: `_on_invocations_chosen` `dialogs.py:1766`.
- Draw the "Metamagic…" launch button: mirror `dialogs.py:2090-2103`. **Gate: Sorcerer + eff_level ≥ 2.**
- Pass it out via `StatsDialog._cb(...)`: add to the call at `dialogs.py:1803` (a new trailing arg,
  e.g. `metamagic_options`).

### 1c. Thread through `_on_stats_ok` + write to Stats
- Add `metamagic_options=None` param to `_on_stats_ok` (`main.py:2417`) — match how
  `elemental_adept_types` is threaded.
- Assign, gated: `stats.metamagic_options = [rpg.MetamagicOption(v) for v in (metamagic_options or [])]`
  **only** when `class_name == "Sorcerer"`, else `[]`. (`metamagic_options` is a bound
  `std::vector<MetamagicOption>`; assign the whole list via the property setter — do NOT mutate elements
  in place, cf. memory `pybind11_array_copy_gotcha`.)

### 1d. Round-trip (memory: `stats_serializer_roundtrip`)
Store as a list of ints (enum values):
- **Save** (`main.py` ~10426, beside `elemental_adept_types`):
  `"metamagic_options": [int(m) for m in s.metamagic_options],`
- **Load** (`agent_loader.py` `dict_to_stats`, beside where `sorcerer_subclass`/`eldritch_invocations`
  load): `stats.metamagic_options = [rpg.MetamagicOption(int(v)) for v in data.get("metamagic_options", [])]`
- No new C++ field or binding — `metamagic_options` already exists and is bound.

**Tests (`test_sorcerer.py`):**
- `test_metamagic_learn_roundtrip` — set `stats.metamagic_options`, run through the save-dict →
  `dict_to_stats` cycle, assert the list survives as the same `MetamagicOption`s.
- `test_metamagic_known_count_cap` — the count rule (2/4/6 by level) — assert the dialog's cap helper if
  factored out as a pure function.

---

## PHASE 2 — The 8 working toggles (sidebar)  ✅ DONE + GREEN (2026-07-13)

Add sidebar toggle buttons for the eight fully-working options: **Distant, Extended, Quickened,
Heightened, Seeking, Empowered, Transmuted, Careful.** (Subtle excluded; Twinned = Phase 3.)

- **State + cast-site wiring:** the Framework section above (`_apply_armed_metamagic` at `9521`/`9881`).
- **Buttons:** one per option, declared near `1371`, drawn/gated near `14624`, clicked near `17559`.
  Gate on learned (`option in stats.metamagic_options`) + affordable (`SP >= cost`). To avoid crowding
  the sidebar, consider a single **"✨ Metamagic ▸"** expander row that reveals the individual toggles,
  OR a compact 2-column block — match the surrounding sidebar density.
- **Radio behavior:** arming one clears the others; Seeking is a separate independent toggle.

**Two options need a param, handled at arm-time or cast-time:**
- **Transmuted** — on arm, pop `ElementPickerDialog` (reuse the Chromatic Orb flow `main.py:8057-8070`)
  restricted to the 6 transmutable types (Acid/Cold/Fire/Lightning/Poison/Thunder); store the pick in
  `self.pending_metamagic_transmute_type`. Set `action.transmuted_damage_type` at cast.
- **Careful** — no picker. At cast, auto-fill `action.careful_targets` with the caster's **party allies
  in/adjacent to the AoE** (engine caps at CHA mod). Reuse the ally-detection already used by the Evoker
  safe-targets / `areAllies` path.

**Tests (`test_sorcerer.py`):**
- `test_metamagic_distant_extends_range`, `test_metamagic_heightened_disadv_save`,
  `test_metamagic_transmuted_changes_type`, `test_metamagic_careful_shields_ally` — arm the option via a
  `SpellAction`, cast, assert the engine effect + that SP dropped by the correct cost.
- `test_metamagic_inapplicable_no_sp` — arm Heightened on a non-save spell → no effect, **SP unchanged**
  (proves the safety net).
- `test_metamagic_not_learned_hidden` — the sidebar gate: an option not in `metamagic_options` is not
  offered (test the gate predicate if factored out).

---

## PHASE 3 — Twinned (the one engine change)  ✅ DONE + GREEN (live-confirmed 2026-07-13)

**Also fixed this pass:** Careful Spell now spares the CASTER from their own AoE (engine adds
`action.caster_idx` to the safe set when Careful applied — independent of the CHA-mod ally cap).
Test: `test_metamagic_careful_shields_caster`. Live-confirmed.


**Implemented:**
- **Engine (root cause):** `getNumTargetsForSpell` gained a `bool twinned` param (default false):
  Single → 2, Multiple → +1 (target COUNT only; upcast damage untouched). The no-op
  `sp.targets_per_upcast_level += 1` in the Twinned case was removed. The `executeSpell` cap block
  (`combat_spells.cpp` ~674) now trims BOTH Single and Multiple to `getNumTargetsForSpell(..., twinned)`
  where `twinned = (applied_metamagic == MetamagicTwinned)` — so Single now authoritatively caps at 1
  (2 when Twinned actually pays). A Twinned applicability guard was added to the metamagic gate:
  Twinned rejects any non-Single geometry (AoE + multi-target like Magic Missile) BEFORE spending SP.
- **Bindings:** `get_num_targets_for_spell` exposes `twinned=false`.
- **GUI:** removed the Twinned skip so it gets a sidebar arm-toggle (generic draw/click loops handle it —
  radio behavior, no arm-time picker). `_twinned_single_armed(sp)` gates the extra target collection;
  `_dispatch_geometry` collects 2 clicks for a Twinned Single spell; `_resolve_spell_cast` uses a
  `multi_target` flag (Multiple geometry OR twinned-single) for both the collect loop and `target_indices`.
- **Tests:** `test_twinned_num_targets_helper`, `test_twinned_single_target_hits_two` (also asserts the
  non-twinned cap trims to 1), `test_twinned_gating` — registered in `__main__`.

Original design notes below (retained for reference):



**The gap:** current `MetamagicTwinned` does `sp.targets_per_upcast_level += 1` (`combat_spells.cpp:610`),
but `getNumTargetsForSpell` (`combat_spells.cpp:2259`) only grants extra targets for **Multiple**
geometry AND multiplies by `(slot_level − spell.level)`. So Twinned is a **no-op** on Single-geometry
spells (Charm Person, Haste, Ray of Frost — the classic twin targets) and on any base-level cast.

**SRD p.66:** *"increase the spell's effective level by 1"* to target one additional creature — matches
the user's model: same slot, +1 SP, one more target.

**Engine approach (root-cause, C++):**
- Give Twinned a genuine "+1 target regardless of geometry, without consuming a bigger slot." Cleanest:
  in `getNumTargetsForSpell`, add a `bool twinned` param (or read a flag off the action) that adds **+1**
  to the returned count and, for **Single** geometry, promotes the effective target count to 2 for this
  cast. Ensure the resolution path applies the full spell to each of the (now 2) targets independently.
- Decide whether the +1 effective level ALSO boosts upcast damage scaling (RAW: yes, it's "+1 effective
  level"). If that's undesirable for balance, scope the bump to target-count only and document it.
- Keep SP spend in the existing gate (already 1 SP).

**GUI:**
- Add the **Twinned** toggle to the sidebar (same framework).
- Single-geometry casts currently collect exactly one click. Under armed Twinned, collect **one extra**
  target (extend the `pending_spell_targets` collection like the Multiple-geometry loop at
  `main.py:9508-9519`, "click 2 targets (1/2)").

**Tests (`test_sorcerer.py`):**
- `test_twinned_single_target_hits_two` — a Single-geometry twinnable spell + armed Twinned → both
  targets receive the effect; SP −1.
- `test_twinned_gating` — Twinned on a self/area spell that can't be twinned → no-op, SP unchanged.

---

## PHASE 4 — Sorcery Incarnate two-option casts  ✅ DONE + GREEN (2026-07-13)

SRD p.65 L7 "Sorcery Incarnate": while Innate Sorcery is active you may use **two** Metamagic options on
one spell (and, with its uses gone, 2 SP still activate Innate Sorcery). This phase also delivers the
**Seeking stacking** exception that Phases 2–3 deferred here.

**Implemented:**
- **Engine (`combat_spells.cpp`):** new `SpellAction::metamagic2`. The one-shot metamagic `if/else` in
  `executeSpell` became `applyMetamagicOption(opt)` (gate → pay SP → mutate the local `sp`), driven by a
  `requested` list: slot 1, plus slot 2 when either option is **Seeking** (the SRD stacking exception) or
  `sorceryIncarnateActive(caster_stats)`. Otherwise slot 2 is logged + dropped, **unpaid**. A duplicate
  `metamagic2 == metamagic` is dropped (never charged twice). The scalar `applied_metamagic` became
  `applied_mm` (a small vector) + an `mmApplied(opt)` predicate — every downstream consumer (Twinned
  target cap, Careful caster-shield, Empowered budget ×4, Seeking reroll, Heightened save) now asks
  `mmApplied()`, so an option works from **either** slot. `advanceCast`'s save preroll reads Heightened
  from either slot too.
- **Engine (`combat_resources.cpp`):** `sorceryIncarnateActive(stats)` (Sorcerer + L7 + `innate_sorcery_turns > 0`),
  and `activateInnateSorcery` gained the **2-SP fallback** at L7 when no uses remain (spent on the local
  `stats` copy — a `spendResource` call would be clobbered by the trailing `setAgentStats`).
- **Bindings:** `SpellAction.metamagic2`, `CombatEngine.sorcery_incarnate_active(stats)` (static).
- **GUI (`main.py`):** `self.armed_metamagic2` + `_sorcery_incarnate_active(idx)` +
  `_armed_metamagic_options(caster_idx)` (the ordered ≤2 armed set; Seeking fills a free slot).
  `_apply_armed_metamagic` writes both slots and fills Transmuted/Careful params from **either** slot;
  `_twinned_single_armed(sp, caster_idx)` now takes the caster explicitly. Sidebar: arming a second
  option while one is armed fills **slot 2** under Sorcery Incarnate (radio otherwise); disarming slot 1
  promotes slot 2; a "Sorcery Incarnate: 2 options per spell" caption appears while it's up. **New
  "Innate Sorcery" sidebar button** (Bonus Action) — the GUI previously had *no* way to activate it, so
  Sorcery Incarnate was unreachable in play; it shows "(2 SP)" when using the L7 fallback.
- **Tests (`test_sorcerer.py`, registered in `__main__`):** `test_sorcery_incarnate_predicate`,
  `test_sorcery_incarnate_two_options` (Quickened + Twinned: bonus action AND 2 targets, −3 SP),
  `test_sorcery_incarnate_gates_second_option` (no Incarnate → 2nd dropped, unpaid),
  `test_metamagic_seeking_stacks_without_incarnate`, `test_metamagic_duplicate_option_charged_once`,
  `test_innate_sorcery_sp_fallback_at_l7`.

**Verify in-app:** a L7+ Sorcerer with ≥2 learned options → click **Innate Sorcery** (bonus action) →
the caption appears and two toggles can be lit at once → cast → the log shows both options applied and
SP drops by the sum. Spend the Innate Sorcery uses, then re-activate for 2 SP.

---

## Done-criteria
- **Phase 1:** `MetamagicDialog` built; "Metamagic…" button in StatsDialog (Sorcerer L2+); options thread
  through `_on_stats_ok` → `stats.metamagic_options`; round-trip added to `agent_loader.py` AND the
  `main.py` save block; learn tests green.
- **Phase 2:** 8 sidebar toggles gated on learned+affordable; `_apply_armed_metamagic` at both cast sites;
  Transmuted element pick + Careful auto-ally fill; effect + no-wasted-SP tests green.
- **Phase 3:** ✅ engine Twinned grants a real extra target; GUI collects the extra target; Careful now
  spares the caster; tests green + live-confirmed 2026-07-13.
- **Phase 4:** ✅ `SpellAction.metamagic2` + `sorceryIncarnateActive` gate + Seeking stacking + the 2-SP
  Innate Sorcery fallback + the second sidebar arm-slot and the new Innate Sorcery button; build clean,
  tests green 2026-07-13. **All phases complete — the Metamagic plan is closed.**
- Leave the user a "what to verify in-app" note each phase. **Build + tests are the USER's to run.**
