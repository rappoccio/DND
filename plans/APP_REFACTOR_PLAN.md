# `App` (main.py) refactor

**Status 2026-11-18: Step 0 frozen (D1–D7). A0 committed d3c4cf1: baseline `./test.sh` 263/0.
A1.1 (narrowed) committed a849702, 263/0. A1.2 committed 449d603, 263/0. A1.3 committed 44ce65d, 263/0. A1.4 committed cbdaccf, 263/0. A2a (click picks → `app.pick`) committed, 263/0. A2b (base modes → `app.pending`) committed e6fff8e, 263/0. A2c (Special Attacks → `gui/app_attacks.py`) committed b2bf1bf, 263/0. A2 closed 2026-11-18: Drag & Cancel dropped (user). Combat plan R4 closed (b736057). A3 (movement mirrors) committed 8062330, 263/0. A3b (action economy storage) committed e01fd7f, 263/0. Graph rebuilt at e01fd7f; A4 re-scoped as A4 (spells) + A4b (summons). A4 (spells → `gui/app_spells.py`) committed a5675cc, 263/0; A4b next.**

**Sequencing with `COMBAT_REFACTOR_PLAN.md` (agreed 2026-11-18):** (1) this plan's A0–A2;
(2) the combat plan's `NpcDriver` and `ReactionArbiter`, informed by A2's `app.pending` modes;
(3) this plan's A3–A4, once `ReactionArbiter` has settled the engine's turn-state API. The
combat plan's riders+resources class-family split floats: do it the next time class features
are added.
Came out of a graphify pass over `gui/` + `tools/` (`graphify-out/`), run after
`COMBAT_REFACTOR_PLAN.md` was written. The C++ refactor did its job: `combat.hpp` went from
125 of 200 commits to 25 of the last 200. The churn moved to `main.py` (124 of the last
200), and no plan covers it.

Scope rule, same as the combat plan: **structural only.** No behavior changes, no features,
no bug fixes bundled in, with one deliberately separate exception (A3) that is called out
as a behavior change and gets its own sign-off.

## Today (measured 2026-11-18)

| Metric | Value |
| ------ | ----- |
| `class App` | `main.py:373`–`23201`, **22,828 lines** |
| Methods | **649** |
| Distinct `self.*` attributes | **531** |
| `main.py` churn | 124 of the last 200 commits |
| Engine surface used | 536 `self.combat.` sites, 182 distinct methods |
| Already split out | `menus/{board,dm,features,panel,reactions,riders}.py`, `dialogs*.py`, `items_play.py`, `lair.py`, `dungeon.py`, `helpers.py`, `widgets.py`, … |

Sources: method → community from the graphify clustering (call edges only); attribute
ownership from an `ast` scan of `main.py` (source text only, nothing run). Community
names are labels on algorithmic clusters. Treat them as candidate seams and confirm each
one against the code before cutting.

### Method clusters inside `App`

| Cluster | Methods | Lines | Calls within | Out | In |
| ------- | ------: | ----: | -----: | --: | --: |
| Spell Activation UI | 125 | 3,356 | 386 | 47 | **201** |
| Dungeon Pages & Navigation | 98 | 3,135 | 214 | 74 | 65 |
| App Shell & Dialog Plumbing | 101 | 2,310 | 53 | 30 | 41 |
| Board Rendering & Fog | 66 | 2,123 | 122 | 24 | 24 |
| Drag & Cancel Interactions | 41 | 1,574 | 51 | 72 | 8 |
| Special Attack Actions UI | 34 | 1,363 | 36 | 64 | 4 |
| Selection Dialogs & Prompts | — | 1,179 | — | — | — |
| Initiative & Lair Turns | 29 | 1,133 | 35 | 27 | 21 |
| `_spawn_summon` group | 22 | 833 | 35 | 11 | 19 |
| `_resume` group | 21 | 810 | 24 | 18 | 13 |
| `_drive_npc_turn_if_pending` group | 21 | — | 28 | 18 | 7 |

Biggest cross-cluster edges: Special Attacks → Spell Activation **52**, Drag & Cancel →
Spell Activation **28**, Dungeon Pages → Shell **23**, Initiative → Spell Activation 17,
Shell → Spell Activation 17, Dungeon Pages → Spell Activation 16.

## Findings

1. **Spell Activation UI is the sink**, the way `combat_core` was for the engine: 201
   calls in, 47 out. It moves **last**, not first.
2. **About 82 `pending_*` fields form a hand-rolled input-mode state machine**
   (`pending_spell_slot` 39 refs, `pending_attack_slot` 30, `pending_spell_idx`,
   `pending_cleave`, `pending_chromatic_*`, `pending_summon_*`, `pending_mantle_*`, …), driven
   by about 26 `_start_*`/`_arm_*`/`_cancel_*` methods and reset by
   `_clear_pending_target_picks` (`main.py:6528`). `pending_spell_slot` has 8 writer
   clusters and `pending_attack_slot` has 8. This is the Python twin of the engine's
   `pending_decision_` and the hardest part of `App`.
3. **`App` mirrors engine turn state.** `move_remaining_{walk,fly,swim,burrow}` are copied
   from `ag.walk_remaining` etc. at about 10 sites (`main.py:5461`, `12903`, `15272`, `20276`,
   …). `MovementController` already owns those budgets. `action_used` and
   `attacks_remaining` are set by hand in about 12 places (`attacks_remaining` re-derived
   from `stats.num_attacks` at `main.py:8280`). These are duplicated state that can drift.
4. **The shared state is small and identifiable.** `bm` (19 of 24 clusters, 1,324 refs),
   `combat` (18, 539), `screen` (8, 360) and the fonts are context. They play the same role
   `CombatContext` plays in the engine. The next tier is turn state (`combat_active`,
   `initiative_order`, `selected_idx`, `action_used`) and the `pending_*` set.
5. **194 attributes have a single owning cluster**, 143 of them in Selection Dialogs &
   Prompts. That cluster and its state lift out cleanly.
6. **The extraction pattern already exists.** `menus/*.py` and `items_play.py` are
   module-level functions taking the app. Use it. Don't invent mixins: inheritance-split
   was rejected for the engine for the same reason (one object, one namespace, the actual
   problem).

## Oracles (what "no behavior change" is checked against)

- `tests/test_combat_panel.py`: structural golden of `_draw_combat_panel` (existing,
  Step 0.6 of the multiplayer plan).
- `tests/test_determinism.py`: engine golden (existing).
- The 21 suites that drive `App` through `tests/gui_driver.py` (existing).
- A fresh `./test.sh` baseline count taken before A1 starts.
- **Gap**: nothing goldens the board renderer or the dungeon-page flow. A0 adds them.

## Step 0: frozen 2026-11-18

- **D1. Mechanism.** Clusters move to module-level functions in new `gui/app_*.py` (or
  existing `menus/` where they fit), taking `app` as the first argument, like
  `menus/features.py`. `App` keeps a one-line forwarder **only** where a method name is
  referenced from outside `main.py` (tests, `gui_driver`, callbacks bound by name).
  Otherwise call sites are rewritten.
- **D2. No mixins, no `App` subclasses.**
- **D3. Context object.** No new `AppContext` in A1/A2. `bm`/`combat`/`screen` stay on
  `app`, read through it. Revisit only if a module ends up needing nothing else from `app`.
- **D4. Pending modes (A2).** The `pending_*` fields become one `PendingAction`-style
  object per mode (spell, attack, shove, summon, chromatic chain, mantle, …), with
  `app.pending` holding at most one. `_clear_pending_target_picks` becomes
  `app.pending = None`. Field-for-field translation. No mode semantics change.
  **Amended 2026-11-18 (user): two slots.** "At most one" did not hold: Chromatic Orb's
  chain sits on its spell arm, and Cleave/Sweep arm while `pending_attack_slot` still
  holds the next Extra Attack; `resolve_pick`'s priority chain decides between them. So
  `app.pending` holds the action being built (Attack / Spell / Shove / Unarmed / Summon,
  with their companions) and `app.pick` holds at most one click pick on top of it
  (teleports, heals, maneuvers, Chromatic chain, legendary and lair picks). An
  instrumented full-suite run (263/0) confirmed it: never two picks or two base modes at
  once, only a pick over a base. The same run found base-mode companions that outlive
  their arm: `pending_attack_offhand` / `pending_weapon_idx` / `pending_attack_resource`
  are attack-sequence state that `cancel_attack` restores while the slot is idle; summon
  and spell staging fields are set before the slot arms; `_resolve_teleport_spell` reads
  `pending_spell_slot_level` after the slot clears. A2b has to settle each of those before
  `app.pending` can be None when idle. Split: **A2a** picks, **A2b** base modes, then
  Drag & Cancel and Special Attacks.
  **A2b companions settled 2026-11-18 (user):** (1) attack-sequence state
  (`attacks_remaining`, `_attack_sequence_slot`, offhand, weapon_idx, resource) becomes
  one `AttackSequence` at `app.attack_seq`, beside `app.pending`, lifetime unchanged;
  (2) cast-menu staging (damage type, curse choice, command word, Forcecage form,
  free_cast, `pending_summon_fey_reinforcements`) becomes one `CastSetup` at
  `app.cast_setup`, reset per cast, lifetime unchanged; (3) `_resolve_teleport_spell`
  reads the slot level into a local before clearing the slot.
- **D5. Turn mirrors (A3) are a behavior change.** They are a separate step with its own
  sign-off, not folded into a move. Leave them alone until A2 lands.
- **D6. One cluster per commit**, each green on `./test.sh` with goldens byte-identical.
  Commit on request, never push (standing rule).
- **D7. Order.** Leaf clusters first, sink last (see Steps).

## Steps (after Step 0 is frozen)

- **A0. Oracle.** Add a board-render structural golden (draw calls/rects per checkpoint,
  same shape as `test_combat_panel.py`, no pixels) and a dungeon-page open/navigate golden.
  Register both in `run_all_tests.py`. Record the baseline count.
  **Done 2026-11-18:** `tests/test_board_render.py` (12 checkpoints, every draw call of
  `run()`'s map layer), `tests/test_dungeon_pages.py` (10 checkpoints: campaign-dungeon
  open, East/West, Floor ±, refusals, staircase carry, in-combat refusal; state + saved
  creatures + Floor-nav and overview draw calls), shared recorder `tests/draw_capture.py`.
  Baseline: **263 passed / 0 failed** (with the working tree's uncommitted
  `DND2024_MonsterStats.json` / `spells.json` edits in place).
- **A1. Leaf cuts**, in this order:
  1. ~~Selection Dialogs & Prompts~~ **narrowed 2026-11-18** to `_init_combat_panel` →
     `menus/panel.py:init_combat_panel(app)` (about 425 lines). Checked against the code,
     the cluster was not a seam: inside `App` it is `__init__` (about 764 lines, stays) plus
     `_init_combat_panel`, and the "143 single-owner attributes" are the `btn_cbt_*`
     buttons, which everything else reaches by string through `panel.cbt_btn`. The dialog
     classes the cluster is named after already live in `dialogs.py` / `prompts.py`.
     **Done 2026-11-18:** 263/0, goldens unchanged.
  2. Board Rendering & Fog (about 2.1k lines, 24 in / 24 out, mostly reads state).
     **Done 2026-11-18:** 40 render methods → `gui/app_board_render.py` (about 1.8k lines);
     `run()` calls the module directly, and `App` keeps 18 one-line forwarders for the
     names tests call (`_draw_map`, `_draw_agents`, `_draw_doors`, …). Stayed on `App`,
     because `net/`, `playback.py` or `App` itself also ask them: the fog rules
     (`_fog_active`, `_fog_conceals`, `_party_fog_active`, `_agent_fogged`, `_door_visible`,
     `_any_explored`), `_staircase_cells_here`/`_ends_here`, `_cell_to_screen(_f)`,
     `_get_sprite`, the fog state setters, and the NPC-playback state machine (not
     rendering). `_draw_floor_overview` waits for A1.3. Three tests that read `main.py`'s
     text or patch its namespace (`test_roster`, `test_drag`, `test_drawn_wall_detection`)
     now point at the new module. 263/0, goldens unchanged. `App` 20,704 lines, 629 methods.
  3. Dungeon Pages & Navigation (about 3.1k lines; its 23 calls into Shell show what the
     shell has to keep exposing).
     **Done 2026-11-18:** 58 methods → `gui/app_dungeon_pages.py` (about 1.5k lines):
     encounter export/import across pages, page/floor switching and carry, campaign and
     New Dungeon flows, save/open/close/add page, Pages/Overview modal,
     `_draw_floor_overview`, staircases, Send to page, the panel's Floor nav. `App` keeps
     33 forwarders (names used by `menus/dm.py`, `menus/board.py`, `scene_store.py`,
     `saves.py`, `floor_overlay.py`, `run_control.py`, tests, or passed as bound callbacks).
     `_draw_panel` still calls `self._draw_panel_floor_nav` because `test_dungeon_pages`
     wraps it on the instance. `_ROOM_FLOOD_CAP` moved to `constants.py` (shared).
     `test_modal_pump`'s seven-loop scan now reads both files. Left for their own cuts:
     the dungeon generator (`_generate_multifloor`, `_modal_generate_dungeon`, about 1.3k
     lines) and the edge-carry review (`_maybe_carry_edges`, …); `_clear_page_mobs`
     (staticmethod), ladders and door links stay. 263/0, goldens unchanged.
     `App` 19,913 lines.
  4. Initiative & Lair Turns (next to the existing `lair.py` / `tracker.py`).
     **Done 2026-11-18:** 52 methods → `gui/app_initiative.py` (about 1.3k lines): combat
     start/end, the initiative tracker, Tides of Chaos on Initiative, encounter XP, On Deck
     and mob clearing, Thief's Reflexes, `_advance_turn` / `_proceed_to_new_turn` /
     `_finish_turn_start`, and the legendary-action phase. `App` keeps 24 forwarders (names
     used by `menus/`, `lair.py`, `tracker.py`, `arena.py`, `autosave.py`, `saves.py`,
     `replay.py`, `app_dungeon_pages.py`, tests, or bound as callbacks); the module calls
     those through the forwarder so instance patches in tests still see them. Stayed:
     `_reset_turn_economy` (A3) and the pick machine (A2). 263/0, goldens unchanged.
     `App` 18,166 lines, 576 methods.
  Re-run graphify (`/graphify . --update`) after each and check that the cluster's in/out
  edges now cross a module boundary instead of `App`.
- **A2. Pending modes** (D4). Take Drag & Cancel and Special Attacks with it: 72 and 64 of
  their outbound calls are the pending machine reaching into Spell Activation.
  **A2a done 2026-11-18:** the 41 click-pick arms (`pending_shadow_step`, `pending_cleave`,
  `arcane_charge_pending`, `_legendary_spell_pick`, `_lair_pick`, …) became one
  `app.pick: pending.Pick(kind, data) | None` (`gui/pending.py`, which catalogues each kind
  and the field it replaced). `App` reads and writes it through `_picking`, `_pick_data`,
  `_arm_pick`, `_drop_pick` and `_set_pick`; dropping a kind that is not the armed one is a
  no-op, as resetting its old flag was. `resolve_pick`'s chain is unchanged in order;
  `net/picks.py` arms for picks are named by kind with `idle=PICK`. The turn-boundary clear
  drops every pick except `chromatic`, which the old clear never reset (kept as is; worth
  a look as its own fix). Companion fields (`pending_mantle_targets`, `pending_bastion_sp`,
  `pending_beguiling_bard`, `pending_flurry_*`, `move_duplicity_idx`, …) stay on `app` for
  now. 263/0, goldens unchanged.
  **A2b committed e6fff8e 2026-11-18 (263/0, goldens unchanged):** the base modes became
  `app.pending: pending.Attack | Spell | Shove | Unarmed | Summon | None`, with companions
  inside their mode (spell idx/slot_level/is_aoe/targets, summon monster/spirit/…, shove
  type). `App._armed(*modes)`, `_armed_slot(mode)` (the old "" when idle) and
  `_disarm(*modes)` replace the fields. Settled companions per D4: `app.attack_seq`
  (`pending.AttackSequence`) and `app.cast_setup` (`pending.CastSetup`); spell resolvers
  take a local `ps` before disarming, which fixes the teleport slot-level read. Kept as
  they were: the turn-boundary clear disarms only a Summon; `_reset_turn_economy` disarms
  every mode but Summon; an armed Unarmed option still does not hold the offer back
  (`_TARGET_PICK_MODES`). `pending_grapple_slot` was never armed and is gone. Save files
  keep the `attacks_remaining` / `_attack_sequence_slot` keys (`saves._ECONOMY` maps
  them). `net/picks.py` base arms are named `attack` / `summon` / `spell` / `shove` /
  `unarmed` with the mode class as `idle`. A pre-move probe over the whole suite found no
  two base modes armed at once. Still on `app`: the Attack arm's riders
  (`pending_horde_breaker_targets`, …), `pending_ward_*`, `pending_dispel_selection` and
  the Chromatic chain state.
  **A2c committed 2026-11-18 (263/0, goldens unchanged):** neither cluster's
  member list had been recorded, and `graph.json` (built at a849702) clusters differently,
  so the seam was re-derived from the code. 50 methods (about 1.47k lines) →
  `gui/app_attacks.py`: the Attack action's sequence (`_start_attack`,
  `_resolve_combat_attack`, `_finish_attack`, Extra Attack, off-hand/Nick, attack
  replacements), its riders (Cleave, Sweep, Horde Breaker, Sudden Strike, Beast's Strike,
  GWM Hew, Flurry, Quivering Palm) and the attacks that replace one (unarmed
  punch/grapple/push, Vampiric Bite, Shove, grapple escape/drop). `App` keeps 24
  forwarders (names used by `menus/riders.py`, `menus/reactions.py`, `menus/features.py`,
  `net/picks.py`, `actions.py`, `app_initiative.py`, tests, plus `_finish_attack` bound as
  the reaction continuation). Stayed: `_are_allies` and the `_pending_spell_*` helpers
  (Spell Activation, A4), the Soulknife/Interception checks, the weapon factories other
  than the unarmed punch. `App` 16,579 lines, 558 methods.
  **Drag & Cancel is not a method seam:** map drag handling is inline in `_handle_events`
  (its map-mouse block), item drag is three small methods, and cancel already lives in
  `net/picks.py`. **Dropped 2026-11-18 (user): A2 closes without it.**

- **A3. Turn mirrors** (D5, behavior change, separate sign-off): read budgets/action state
  from the engine instead of copying them.
  **Scoped 2026-11-18 (user):** movement only. `attacks_remaining` already left with A2b
  (`app.attack_seq`). `action_used` / `bonus_used` have no engine owner to read, so they
  move to A3b. Done: the four `move_remaining_*` fields are gone; `app.move_remaining(idx,
  move_type)` reads the placed agent's own budget (exhaustion already off), and
  `move_budget`, the panel and `_reset_movement`'s default move type use it. Signed-off
  behavior change: Steady Aim zeroes the agent's budget (`init_movement(0,0,0,0)`) and
  Dragon Wings retract zeroes its fly budget, through a new `PlacedAgent.raw_movement`
  binding (stored budgets before exhaustion). Side effects of reading per agent: during a
  legendary Dash the panel shows the current creature's budget, not the legendary mover's,
  and a stale mirror no longer outlives that move; the legendary mover's budget now has
  exhaustion taken off like every other. Tests: `test_move.py`, `test_perform.py`,
  `test_restore_oracle.py` read agent budgets; Steady Aim's test drives the real handler.
  263/0, goldens unchanged.
  **Left for the combat plan:** the engine holds two movement budgets, the agent's and
  `MovementController`'s (`begin_move` spends/clamps the latter); the legendary Dash seeds
  both by hand. Merging them is C++ work.
- **A3b. Action economy into the engine, storage only** (agreed 2026-11-18): `action_used`
  and `bonus_used` become `Agent::Conditions` flags beside `reaction_used`, cleared in the
  `beginTurn` reset, bound read/write, serialized. C++ about 20 lines. Python: about 80
  writes become a helper (`app.spend_action()` style) on the current creature, about 255
  reads go through it; 43 test suites (281 refs, 61 direct writes) follow. `saves.py`
  stores both at app level today, so old saves need a load shim. Semantics to check: the
  flags are turn-global today and per-creature after, so Haste's extra action (writes
  `False`) and anything spending an action off the creature's own turn need a look. No
  gameplay change intended.
  Done (2026-11-18), smaller than planned: `bonus_used` was already engine-owned (a
  property over `bonus_actions_remaining`), so only `action_used` moved. It is a new
  `Agent::Conditions::action_used`, cleared in `Agent::turn()` (beginTurn), bound
  read/write and in `RPG_CONDITIONS_FIELDS`. `app.action_used` became a property beside
  `bonus_used` over the current combatant's copy, with the same pre-combat fallback, so
  no call site or test changed and no `spend_action()` helper was needed. Old saves need
  no shim: `saves.py` still restores the `economy` keys through the property after
  `settle_turn`. Semantics checked: Haste / Action Surge write `False` on the current
  creature (the one they apply to); no legendary or off-turn path writes `action_used`;
  every `turn_idx` re-point keeps the same actor. A spent Action now stays on its creature
  until that creature's next beginTurn. New test in `test_action_menu.py`. 263/0, goldens
  unchanged.
  **Not in scope (Size B):** the engine enforcing the economy at every action entry point.
  That is plan-sized C++ and a behavior change; it belongs with multiplayer's future-auth
  work, not here.
- **A4. Spell Activation UI** last, once its callers go through `app.pending`.
  **Re-scoped 2026-11-18 against a graph rebuilt at e01fd7f** (`graphify-out/`, code-only
  incremental update over `gui/` + `tools/`: 8,930 nodes, 310 communities). `App` is now
  16,542 lines and 561 methods. The table's "Spell Activation UI" cluster (125 methods,
  3,356 lines) predates A1–A3b and no longer exists as such. In the new clustering, the
  spell lifecycle sits mostly in two `main.py` communities, *App Spell Resolution & Pending
  Modes* (69 nodes) and *App Spell & Feature Activation* (131), with some of it in *App Pick
  Resolution & Cancels*. The second also pulls in class-feature activations
  (`_use_*`, `_start_mantle`, Wild Shape), door actions and the 819-line `_perform_action`,
  because call edges cluster callers with what they call. That is not a seam, so the cut
  below was re-derived from the code (as A2c was), with the graph as a cross-check.
  - **A4 → `gui/app_spells.py`: 56 methods, about 1,545 lines.** The spell lifecycle:
    start/activate (`_start_cast_spell`, `_activate_spell`, `_dispatch_spell_geometry`,
    `_ask_spell_browser`, `_ask_ward_types`, `_on_spell_done`); resolution
    (`_resolve_spell_cast`, `_resolve_spell_cast_aoe`, `_resolve_teleport_spell`,
    `_resolve_corpse_spell`, `_finish_animate_dead`, `_resolve_planar_binding`, the
    multi-target pair, `_finish_cast`, `_resolve_wild_magic_surge`); cost
    (`_consume_cast_slot`, `_apply_pact_slot_level`, `_spell_costs_action_and_bonus`) and
    `_log_spell_results`; the aiming reads (`_pending_spell*` predicates, `_aoe_cells`,
    `_area_template`, `_filter_spell_cells_by_range_and_los`, `_wall_anchor_in_range`);
    and the spell-specific flows: Chromatic Orb chain (6), armed Metamagic (6), Dispel
    Magic (`_cast_dispel_selection`, `_apply_dispel_selection`), Wish / Divine
    Intervention (4), Beguiling / Bewitching Magic (6).
  - **A4b → `gui/app_summons.py`: 16 methods, about 610 lines.** Summons, familiars,
    companions, Duplicity (`_resolve_summon`, `_spawn_summon`, `_auto_summon_fey`,
    `_choose_summon_form`, `_summon_cell_valid`, the companion/familiar find / summon /
    dismiss sets, the Duplicity five). A separate lifecycle with its own callers
    (`menus/features.py`, `actions.py`, `arena.py`), cut separately to keep each step short.
  - Mechanics as A2c: module-level functions taking `app`; `App` keeps a one-line
    forwarder for every name reached from outside `main.py` (about 31 for A4, mostly
    `net/picks.py`, `menus/features.py` and tests; 11 for A4b) or bound as a callback;
    calls between moved functions go through the forwarder where a test wraps the
    instance. Grep string references before dropping any forwarder. Goldens
    byte-identical, `./test.sh` all green.
  - **Stays on `app` in A4:** `_are_allies`, the pick plumbing (`_armed`, `_disarm`,
    `_clear_pending_target_picks`, `_reset_turn_economy`), `_drop_concentration*`,
    `_sync_item_spells` / item-spell panel, `_spell_to_dict` (save path),
    `_load_spell_effects` / `_build_spell_effect_metadata` (load path).
  - **After A4 + A4b `App` is about 14.4k lines**, still well over the ~8k criterion.
    Candidate cuts the new graph surfaces, not yet scoped: class-feature activations
    (the `_use_*` / `_start_*` feature handlers, about 25 methods), the `_perform_action`
    dispatcher (819 lines in one method), *App Map Editing & Encounters* (173 nodes),
    *App Dungeon Generation & Import* (55), fog/rooms/doors.
  **A4 done 2026-11-18 (263/0, goldens unchanged, uncommitted):** the 56 methods above
  (1,545 lines; the six Metamagic are `_careful_ally_targets`, `_sorcery_incarnate_active`,
  `_armed_metamagic_options`, `_enhanced_necromancy_armed_for`, `_twinned_single_armed`,
  `_apply_armed_metamagic`; `_grave_return_to_life` stayed) → `gui/app_spells.py`. `App`
  keeps 31 forwarders (names used outside `main.py`, plus the bound callbacks
  `_on_wish_duplicate`, `_drop_di_wish_free`, `_finish_cast`, `_finish_multi_target_spell`).
  The spell-only tables moved with them (`_REPEAT_TARGET_SPELLS`, `ELEMENT_CHOICE_SPELLS`,
  the Magic Circle ward options, `CLERIC_DI_SPELL_NAMES`, the Curse options) and so did the
  summon registry (`SUMMON_SPELL_TO_MONSTER`, `_load_summon_spirits`,
  `SUMMON_SPELL_TO_SPIRIT`), because `_activate_spell` reads it and `app_spells` cannot import
  `main`; `main.py` imports back `CLERIC_DI_SPELL_NAMES` (tests) and `SUMMON_SPELL_TO_SPIRIT`.
  A4b can take the summon registry into `app_summons.py`. `main.py` 15,459 lines.

## Risks

- **Name-bound callbacks.** Buttons, `PromptBus` handlers and `gui_driver` reach methods
  by name. Grep for string references before deleting a forwarder.
- **Merge pain.** `main.py` is in 62% of commits. Keep each cut short and pause feature
  work on `main.py` for its duration, same as the engine plan.
- **The pending machine is the sharp edge** (as `pending_decision_` is for the engine).
  Budget real time for A2.
- **Cluster ≠ seam.** The graph's communities come from call edges and don't know about
  attribute writes. Re-check attribute ownership (the `ast` scan) for each cluster before
  cutting.

## Success criteria

- `class App` under about 8k lines, and no single module over about 3.5k.
- Adding a spell's activation UI touches the spell-activation module plus at most a
  `pending` mode, not `main.py`'s class body.
- No `move_remaining_*` / `attacks_remaining` mirrors after A3; `action_used` / `bonus_used` engine-owned after A3b.
- Goldens byte-identical and `./test.sh` all green after every step.
