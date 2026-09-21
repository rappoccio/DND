# Live-Play Bugfix Plan

Working plan for the open bugs in `BUGS_FROM_LIVE_PLAY.md`, ordered by leverage and
grouping related root causes. Check items off as they land. Each phase ends with a
hand-back for the user to build/test.

---

## Phase 1 — Systemic GUI plumbing (highest leverage)

These are two single, well-scoped fixes that each repair ~15 features at once.

- [x] **L35 — `self.hint` rendered nowhere.** DONE.
  ~15 target-pick flows set `self.hint` (Flurry of Blows, Lay on Hands, Bardic
  Inspiration, Mantle of Inspiration, Hand of Healing, Telekinetic Movement, Escape
  Net, Command, Psychic Teleportation, Shadow Step, Shadow Arts: Darkness, Steps of
  the Fey, Misty Escape, Bewitching Magic, Elemental Burst, Wild Magic Teleport) but
  it is never drawn, so no "click a target" prompt appears.
  **Fix applied:** `hint` is now a write-only *property* whose setter forwards to
  `_combat_log_add` (the one prompt mechanism the rest of the GUI already uses), so
  every existing `self.hint = "…"` site emits a real prompt with no per-site change.
  The ~10 sites that *also* called `_combat_log_add` explicitly had that redundant
  call removed so the prompt shows exactly once.

- [x] **L36 — `pending_*` flags leak across turns.** DONE.
  `pending_cleave`, `pending_sweep`, `pending_rally`, `pending_feint`,
  `pending_mantle_active`, `pending_clairvoyant`, `pending_vow_of_enmity`,
  `pending_inspiring_smite`, `pending_use_item`, … are cleared in
  `_start_combat`/`_end_combat` but NOT in `_proceed_to_new_turn`, so an armed
  target-pick leaks into a later turn and swallows the next map click.
  **Fix applied:** new `_clear_pending_target_picks()` helper resets EVERY armed
  target-pick flag (booleans + None/-1 sentinels + companion state) to idle. It is
  called at every turn boundary — `_proceed_to_new_turn` (turn start),
  `_start_combat`, and `_end_combat` — replacing the scattered one-off clears.

---

## Phase 2 — Save-timing & save-correctness cluster

Related mechanism (start-vs-end-of-turn re-saves, `save_repeat_turns`, and what counts
as a "spell" for gating). Batch them.

- [x] **L38 — Hold Person now re-saves at the END of the target's turn (RAW).** DONE.
  (Plan text originally had the direction reversed; the DM confirmed RAW = end of turn.)
  New `save_at_end_of_turn` flag on `AttackCondition`/`ActiveAgentCondition`, parsed from
  `spells.json`, serialized for round-trips, and copied onto the tracked condition. `beginTurn`
  skips (does NOT roll) the save for flagged conditions — the creature still can't act — and
  `endTurn` runs a new save pass; a success frees the creature starting on its NEXT turn.
  Extracted the shared `dropCasterConcentrationIfLastTarget` helper (used by both loops). Set
  the flag on Hold Person + Hold Monster. Test: `tests/test_hold_person_endturn.py`.
- [x] **L37 / L27 — Sanctuary WIS save.** DONE (verified already correct). The ward's WIS save
  fires in `determineAdvantage`, reached by BOTH the GUI attack path (`begin_attack`) and the
  NPC/RL path (`execute_action`); the spell-side ward is in `applySpellEffect`. No change needed.
- [x] **L25 — Spirit Guardians timing.** DONE (verified already correct). Uses the default
  `effects_on_begin_turn` — damage lands at the START of a creature's turn plus on entering the
  zone / the emanation sweeping onto a creature, NOT at end of turn. (The "end of turn" live-play
  read is the GUI perception effect: clicking End Turn immediately runs the NEXT creature's
  `beginTurn`, so its tick shows in the log right after you end your turn.) No change needed.
- [x] **L39 — Warding Flare temp HP.** DONE (verified correct per DM). 2024 Improved Warding
  Flare (L6) grants 2d6+WIS TEMP HP — the current behavior is intended. No change.
- [x] **L41 — Warding Flare vs Sanctuary interplay.** DONE (verified already correct). Warding
  Flare never touches `sanctuary_active` and isn't routed through `executeAction`/`executeSpell`
  (the two paths that end a ward), so a warded cleric's Sanctuary correctly persists. No change.

---

## Phase 3 — Reaction / opportunity-attack correctness

Both are guard conditions in the OA path.

- [x] **L8 — Block all actions after an OA inflicts an incapacitating condition**
  (e.g. Stunned) mid-move/mid-turn. DONE. In `applyReactionResponse` (combat_movement.cpp), after the
  OA resolves and the mover is still up, if the mover is now `incapacitated` (Stunned/Paralyzed/
  Incapacitated all route through `applyIncapacitated`) the move is `mover_halted` at the provoke cell —
  mirroring the Sentinel path. `advanceMove` commits the partial move and zeroes every movement budget,
  so Speed → 0; the GUI's existing `_is_incapacitated` action-gate (main.py ~16639) then blocks all
  further actions this turn. Test: `test_oa_incapacitating_condition_halts_mover`.
- [x] **L13 — No OA through a wall** between the two agents (line-of-effect check). DONE. The prior
  `hasLineOfSight` guard in `detectProvokes` was a *no-op* at 5-ft reach: a pure distance-1 diagonal's
  corner is flanked by the two endpoint cells, which `hasLineOfSight` always excludes, so its wall test
  never fired for adjacent 1×1 tokens. Replaced with a real 5-ft **corner rule**: a diagonal reach is
  blocked only when BOTH cells shared by the diagonal are walls (a sealed corner); orthogonal adjacency
  is always open. Walls read from `disallowedCells()` (auto-detected) + `getTerrainType()==Wall` (manual);
  off-map counts as solid. Tests: `test_no_oa_through_a_walled_corner`, `test_open_corner_still_provokes`.

---

## Phase 4 — Stats / AC / persistence quick wins

Likely small serializer / derived-stat fixes.

- [x] **L42 — DEX modifier not accurately added to AC.** DONE. Root cause: the weapon-attack
  path (`resolveAttack`, combat_attack.cpp) read the target's raw `base_ac`, so a PC's DEX (and
  armor/shield/feats) never reached the to-hit comparison — while the spell/Cleave paths already
  used `calculateAC`. Fixed by routing `resolveAttack`'s `target_ac` through `calculateAC`
  (falling back to raw `base_ac` only for the index-less direct `resolve_attack` binding).
  `base_ac` carries two conventions — PCs store a **pre-DEX base** (the GUI dialog's "Armor Class"
  stepper, previewed via `_calculate_total_ac`); NPCs store the **final published AC** with DEX
  already folded in — so `calculateAC`'s DEX/armor/shield/feat layering is now gated on
  `!is_npc`. NPCs return `base_ac` (+ transient `ac_temporary_modifications` like Shield/acid,
  which apply to both). This also fixes a latent over-add of DEX on spell attacks vs monsters.
  Tests: `tests/test_ac_dex.py`.
- [x] **L40 — Current spell-slot state not saved on reload.** DONE. Save block already wrote
  `spell_slots_cur` at agent level (main.py ~12732); load block restores it in
  `restore_class_resources` (agent_loader.py ~285). A regression test exposed a real gap:
  `initialize_multiclass_resources()` seeds `spell_slots_remaining` for the AT/EK/Warlock
  subclass branches but NOT for full casters, so a load with no persisted `spell_slots_cur`
  (legacy save / hand-built dict) left a caster at zero slots. Added an `else` fallback that
  seeds `spell_slots_remaining = spell_slots_max` in that case (mirrors main.py `_on_stats_ok`).
  Regression tests in `tests/test_ac_dex.py` (restored-verbatim + absent-defaults-to-max).

---

## Phase 5 — Movement / terrain

- [x] **L17 — Can walk on water.** DONE (crossed off per DM: fixed by another feature). Verified the
  engine already blocks it: `isBlocked` (battle_map.cpp) treats `TerrainType::Water` as impassable to
  Walk/Burrow (passable only to Swim/Fly/Jump), and every movement path enforces it — the Dijkstra
  commit in `moveAgent`, the `reachableCells` preview that gates `drag_valid`, and the NPC driver.
  The terrain save/load round-trip preserves a painted "Water" region (`_load_terrain` →
  `_apply_terrain_to_battle_map`; neither `detect_walls` nor grid re-analysis wipes `terrainType_`).
  The live "walk on water" was water that was not painted as the Water terrain type. No code change.
- [x] **L19 — Incapacitated does not restore movement speed after it clears.** DONE. Root cause:
  `applyIncapacitated` (the shared side-effect of Paralyzed/Stunned/Incapacitated) sets Speed→0, but
  the `onConditionEnded` teardown cleared only the `incapacitated` FLAG — it never gave the Speed
  back. A creature whose Agent movement budget had been zeroed (e.g. the Phase-3 L8 path where an OA
  inflicts Stun mid-move and zeroes the budget) was left at 0 movement even after shaking the
  condition off. Fix: new `restoreMovementAfterIncapacitation()` re-seeds BOTH the Stats
  remaining-speed fields and the Agent's own budget (the one `moveAgent`/`reachableCells` read) from
  the base speeds, called from `clearSpellConditionEffect` for Paralyzed/Stunned/Incapacitated.
  Safe against refunding a partial move — incapacitation always ends at a turn boundary, never
  mid-move. Test: `tests/test_incapacitated_movement_restore.py`.

---

### Notes
- User owns all git commits; do not commit or push.
- Default: user runs builds and tests unless told otherwise.
- Fix root causes in C++ where the engine is at fault; avoid Python-side masks.
