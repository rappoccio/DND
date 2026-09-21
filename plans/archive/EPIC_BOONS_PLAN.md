# Epic Boon Feats — Implementation Plan (SRD 5.2 / 2024 PHB)

Status: PLANNING (discuss before implementing). Builds on the general-feat system
(`GENERAL_FEATS_PLAN.md`, `memory/feat_system.md`): `feats` vector + `hasFeat`/`addFeat`
on `Agent::Stats`, multi-select `FeatDialog`, round-trip through StatsDialog.

Scope rule (`feedback_scope_combat_sim`): implement combat-relevant mechanics; reuse existing
engine hooks, don't invent parallel paths (`feedback_rider_pattern_parity`,
`feedback_reusable_bonus_attack`). ASI is **not** auto-applied (decision #1 of general feats) —
each boon's "+1 to a score, max 30" is set via the stat steppers; only special benefits are built.

Source: SRD 5.2 p.88, "Epic Boon Feats". All 7 have `Prerequisite: Level 19+`.

---

## The 7 Epic Boons — verdict & reuse

Legend: **C** = full combat mechanic · **P** = partial (combat bit in, rest noted) ·
**N** = note only · reuse = existing hook leaned on.

| Boon | Benefit | Verdict | Combat mechanic → reuse |
|------|---------|:------:|-------------------------|
| **Combat Prowess** | Peerless Aim: miss → hit, once/turn (until start of next turn) | C | miss→hit, mirrors **Unerring Strike** / **Guided Strike** (`combat_riders.cpp`); new `peerless_aim_used` flag reset in `beginTurn` |
| **Irresistible Offense** | Overcome Defenses: B/P/S ignores Resistance · Overwhelming Strike: nat-20 → extra dmg = the boosted score | C | physical-damage path (`combat_attack.cpp:378`) + nat-20 branch (`r.d20 == 20`) |
| **Truesight** | Truesight 60 ft | C | trivial passive → `Stats.truesight_range = 60` (already wired into visibility) |
| **Dimensional Travel** | Blink Steps: after Attack/Magic action, teleport ≤30 ft to a visible empty space | P→C | teleport reuse (`forceMoveAgent`/Misty-Step flow); GUI button + NPC reposition |
| **Spell Recall** | Free Casting: cast a lvl 1–4 slot, roll 1d4; if = slot level, slot not expended | C | `CombatEngine::spendSpellSlot` chokepoint (`combat_state.cpp:128`) |
| **Night Spirit** | Merge with Shadows: BA Invisible in Dim/Dark (ends when you act) · Shadowy Form: Resistance to all but Psychic/Radiant in Dim/Dark | P | Invisible condition + light query (lighting); resistance grant gated on current cell light |
| **Fate** | Improve Fate: you/creature ≤60 ft succeeds/fails a D20 Test → roll 2d4, apply ± to the roll; 1/short-or-long rest | P→N | broad "any D20 Test" reaction — hardest to wire cleanly; partial (attacks + saves) or defer |

**ASI note:** epic boons raise a score to **max 30** (not 20). **LOCKED:** ASI stays manual (stepper
cap unchanged; not auto-applied) — documented in `known_limitations.md`.

---

## Locked decisions (2026-07-17)

1. **Peerless Aim & Blink Steps** — **GUI-offered for PCs, automatic for NPCs** (matches GWM Hew /
   Unerring Strike pattern).
2. **Boon of Fate** — **partial**: apply 2d4 ± to attack rolls and saving throws only (1/rest); the
   full "any D20 Test incl. ability checks" scope goes to `known_limitations.md`.
3. **Night Spirit** — **build both** Merge with Shadows *and* the dynamic Dim/Dark Shadowy-Form
   resistance now (the light query already exists).
4. **ASI to 30** — **manual**; stepper cap unchanged, noted in `known_limitations.md`.

---

## Proposed phasing

### Phase E0 — GUI + infra (foundation) — ✅ DONE 2026-07-17
- ✅ `EPIC_BOON_FEATS` list (name, status, note) in `gui/dialogs.py`; `FeatDialog` now renders a
  combined `FEAT_DIALOG_ROWS` = general feats + an `("header", "Epic Boon Feats — Level 19+")`
  section-label row + the 7 boons. Header rows are non-selectable (skipped in hover/click; drawn as a
  tinted label). All 7 boons tagged `"soon"` until their mechanics land in E1–E4.
- ✅ `EPIC_BOON_FEAT_NAMES` set. Boons ride the same `stats.feats` vector and share the general-feat
  picker: `StatsDialog._general_feats` now captures `GENERAL_FEAT_NAMES | EPIC_BOON_FEAT_NAMES`, and
  `main.py::_set_general_feats` drops/re-adds both name-sets. Feats serialize as a plain string list
  (save `main.py:11888`, load `agent_loader.py:80`) — no new serializer work for E0.
- No new `Stats` fields yet (those arrive with E1+).

### Phase E1 — Cleanest, highest-value combat — ✅ DONE 2026-07-17
- ✅ **Boon of Truesight** — new `Agent::Stats::effectiveTruesightRange()` folds in 60 ft when
  `hasFeat("Boon of Truesight")`; queried (not materialized) like Skulker so it round-trips without
  serializing raw sense ranges. Routed through the three read sites: `piercesInvisibility`, the `ts`
  local in `computeVisibility`, and the HeavilyObscured blind check in `combat_conditions.cpp`.
- ✅ **Boon of Irresistible Offense**:
  - *Overcome Defenses.* New attacker-aware helper `effectivePhysicalDamageMult(attacker, target,
    type)` (combat_spells.cpp, declared in combat.hpp) lifts **Resistance** (0.5 → 1.0) for a boon
    holder; Immunity (0) and Vulnerability (2) intact. Symmetric to `effectiveMagicDamageMult`. All
    weapon-path B/P/S multiplier reads routed through it: `combat_attack.cpp` main physical roll,
    Tavern Brawler + Unarmed Fighting unarmed dice, the flat-mod `mod_mult`, the Piercer reroll/crit
    extras, the superiority-die rider (`combat_riders.cpp`), and the PMF analysis (`combat_turn.cpp`).
  - *Overwhelming Strike.* On a natural 20 (`r.d20 == 20`), extra damage = the **full ability score**
    (`irresistible_offense_ability`: 0=STR/1=DEX, new `Stats` field + binding + save/load round-trip),
    of the attack's damage type (scaled by the target's effective multiplier). Added as its own
    "Overwhelming Strike" breakdown line in the on-hit rider section.
- ✅ GUI: both boons flipped `soon`→`in` in `dialogs.py`; an ability picker (STR/DEX) reuses the
  shared `ElementPickerDialog`, plumbed through `_on_stats_ok(... irresistible_offense_ability)`.
- ✅ Tests: `test_epic_boons_e1.py` (registered in `run_all_tests.py`). **User builds + runs tests.**

### Phase E2 — miss→hit + teleport — ✅ DONE 2026-07-17 (NPC Blink reposition deferred)
- ✅ **Boon of Combat Prowess (Peerless Aim).** Mirrors the Unerring Strike miss→hit pattern
  (`maybePeerlessAim` right after `maybeUnerringStrike` in both attack paths). New `Conditions`
  `peerless_aim_used` (once/turn, reset in `turn()` — "until the start of your next turn") + deferred
  `peerless_aim_available`. **NPCs auto-fire** at roll time (damage-roll-on-promotion, `peerless_fired`
  committed as a late attacker-conditions write like `unerring_fired`); **PCs get the deferred prompt**
  (`applyAttackResult` arms `peerless_aim_available` for non-NPCs → GUI on-miss menu `_offer_peerless_aim`
  → `applyPeerlessAim`, which re-validates via `canPeerlessAim`, rolls + applies damage, consumes the
  use). A Peerless-Aim hit is a genuine hit (offered ahead of Guided Strike). `can_peerless_aim` /
  `apply_peerless_aim_effect` bound.
- ✅ **Boon of Dimensional Travel (Blink Steps).** No bespoke engine path — **reuses the existing
  teleport primitives** (`teleport_agent` / `is_valid_teleport_destination` / `has_line_of_sight` +
  the GUI's `_agent_at` occupancy check) from `_resolve_blink_steps`. Engine side is just the
  `blink_steps_available` `Conditions` flag (armed after the Attack/Magic action, reset in `turn()`).
  GUI: `_arm_blink_steps` fires at the Attack-action exhausted branches (`_finish_attack` +
  `_continue_attack_sequence_after_rider`) and after a spell (`_finish_cast`); a standing
  **✦ Blink Steps** button enters a ≤30-ft destination pick (mirrors Arcane Charge).
  **Deferred:** NPC auto-reposition (no C++ arming yet) → `known_limitations.md`.
- ✅ GUI: both boons flipped `soon`→`in` in `dialogs.py`.
- ✅ Tests: `test_epic_boons_e2.py` (registered in `run_all_tests.py`). **User builds + runs tests.**

### Phase E3 — caster boons — ✅ DONE + GREEN 2026-07-17
- ✅ **Boon of Spell Recall (Free Casting).** In `spendSpellSlot` (the single PC-cast chokepoint),
  for `level` 1–4 and a boon-holder, roll 1d4; on a match the slot is not decremented (logs "Free
  Casting: slot retained"). NPCs use the N/day system and never reach this path — unaffected.
- ✅ **Boon of the Night Spirit.**
  - *Merge with Shadows:* new `applyMergeWithShadows` (mirrors the Warlock `applyOneWithShadows` —
    Invisible + `invisible_persists_on_action=false`, gated on the cell's Dim/Dark light). Bound as
    `apply_merge_with_shadows`; GUI **Merge with Shadows** BA button (drawn when the holder has the
    feat, click enforces the lighting gate).
  - *Shadowy Form:* evaluated **at damage time** on the DEFENDER's current cell light via a new
    `shadowyFormActive(bm, idx)` helper, folded into **both** `effectiveMagicDamageMult` (already had
    `bm`/`target_idx`) and `effectivePhysicalDamageMult` (given the same optional params). Resistance
    (mult → 0.5) for all types except Psychic/Radiant while in Dim/Dark, added *before* the caster-side
    bypasses so Overcome Defenses (Boon of Irresistible Offense) can still lift it. `bm`/`target_idx`
    threaded through `resolveAttack` → `rollDamage` (all 3 interactive callers pass `&bm,
    action.target_idx`); this also enabled Aura of Warding on the weapon magic-damage path.
    **Deferred:** the secondary damage-reroll paths (Savage Attacker / Piercer / Brutal Strike / GWM
    Hew rerolls) don't pass `bm`/`target_idx`, so a boon-holder hit by those keeps full damage on the
    reroll → `known_limitations.md`.
- ✅ GUI: both boons flipped `soon`→`in` in `dialogs.py`.
- ✅ Tests: `test_epic_boons_e3.py` (registered in `run_all_tests.py`). **User builds + runs tests.**

### Phase E4 — Boon of Fate (partial) — ✅ DONE + GREEN 2026-07-21 (NPC auto deferred)
- ✅ **Improve Fate.** New `applyBoonOfFate(bm, idx, boost)` (combat_spells.cpp, declared in
  combat.hpp) — a near-clone of **Bend Luck** (`sorcererBendLuck`): rolls **2d4** and primes the
  shared `pending_roll_bonus_` (`+` boost / `-` penalty) that folds into the **next** D20 Test
  (attack roll or saving throw — saves go through `roll(20)`, so the same primitive reaches them).
  Gated on `hasFeat("Boon of Fate")` + a new `Agent::Stats::boon_of_fate_used` flag; **1/short-or-long
  rest** (reset in `restore_resources_short_rest`/`restore_resources_long_rest`) **plus refreshed at
  initiative** (reset in `rollInitiativeFor`). Round-trips (save `main.py`, load `agent_loader.py`).
- ✅ **Verified the reused primitives** (`pending_roll_bonus_`, `pending_portent_die_`, one-shot
  advantage): Bardic Inspiration / Cutting Words / Bend Luck / Lucky / Portent all sound — no
  double-consumption (adv/dis paths capture the bonus once before the inner rolls) and the bonus
  reaches saving throws. The one inherent caveat (global single-slot pending applies to whatever d20
  fires next) is pre-existing and noted.
- ✅ GUI: `boon_of_fate_used` + `apply_boon_of_fate` bound; a **Boon of Fate (2d4)** button (drawn
  for the current agent while it has the feat and an unspent use; next to Bend Luck) opens a
  Boost(+2d4)/Penalty(−2d4) menu. `dialogs.py` flipped `soon`→`in`.
- **Deferred → `known_limitations.md`:** ability checks (barely modeled); self-primed on the
  holder's turn only (no reactive "any creature within 60 ft" post-roll prompt — matches Bend Luck);
  **NPC auto-use** (no `runNpcTurn` heuristic yet).
- ✅ Tests: `test_epic_boons_e4.py` (registered in `run_all_tests.py`). Built clean, suite GREEN 2026-07-21.

---

## 🎉 ALL 7 EPIC BOONS COMPLETE (E0–E4, DONE + GREEN 2026-07-21)
Truesight · Irresistible Offense · Combat Prowess · Dimensional Travel · Spell Recall · Night Spirit · Fate.

---

## Suggested build order
E0 ✅ → E1 ✅ (Truesight + Irresistible Offense) → E2 ✅ (Combat Prowess + Dimensional Travel) →
E3 ✅ (Spell Recall + Night Spirit) → E4 ✅ (Fate, partial — all 7 boons now landed). Each phase: engine
edits → user builds (`feedback_user_runs_builds`) → user runs tests (`feedback_user_runs_tests`);
new `Stats`/`Weapon` flags round-trip per the serializer memories.
