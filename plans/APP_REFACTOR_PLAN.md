# `App` (main.py) refactor

**Status 2026-11-18: Step 0 frozen (D1–D7). A0 committed d3c4cf1: baseline `./test.sh` 263/0.
A1.1 (narrowed) committed a849702, 263/0. A1.2 committed 449d603, 263/0. A1.3 done, uncommitted, 263/0. A1.4 next.**

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
  Re-run graphify (`/graphify . --update`) after each and check that the cluster's in/out
  edges now cross a module boundary instead of `App`.
- **A2. Pending modes** (D4). Take Drag & Cancel and Special Attacks with it: 72 and 64 of
  their outbound calls are the pending machine reaching into Spell Activation.
- **A3. Turn mirrors** (D5, behavior change, separate sign-off): read budgets/action state
  from the engine instead of copying them.
- **A4. Spell Activation UI** last, once its callers go through `app.pending`.

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
- No `move_remaining_*` / `attacks_remaining` mirrors after A3.
- Goldens byte-identical and `./test.sh` all green after every step.
