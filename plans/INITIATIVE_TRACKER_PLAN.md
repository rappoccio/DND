# Initiative tracker mode — the table rolls, the DM's screen keeps score

**Status 2026-11-09: Step 0 frozen (D1–D5 decided by the user). T1 committed 1b44e2c (222/0).
T2 committed 19caef6 (223/0). T3 committed 4722635 (223/0). T5 + T4 committed 72fb29d
(223/0). D5 amended + click-to-activate committed a4779f2. T4b committed a2ff22d. T6 committed 7620024. T7 (live check) next.**

## What the user asked for

> A simple "initiative tracker" mode where players and the DM roll their own dice. I only
> need to keep track of initiative and HP, as well as the fog of war and the mobs being
> laid out initially. … In this mode, there aren't player screens at all.

**Only the DM console is used.** Everyone rolls real dice and calls out numbers; the DM
types them in. The app is a board plus a score sheet.

| Kept                                                            | Off in this mode                                        |
|-----------------------------------------------------------------|---------------------------------------------------------|
| Map, grid, walls, doors, lighting, terrain                      | Player server: no seats, no browser screens             |
| Placing mobs (Agents…, stat blocks give name / AC / max HP)     | Attacks, spells, saves, every engine dice roll          |
| Fog of war (party reveal, explored mask) and On Deck benching   | NPC automation, action buttons, reactions               |
| DM drags any token, any time                                    | Movement budgets, opportunity attacks                   |
| Initiative order, whose turn, round counter                     | Conditions, concentration, resources, death saves       |
| HP (current / max / temp) per token                             | Replay recording                                        |

**No C++ change and no `net/` change.** It's `main.py` plus one new pure-Python module.

## What the code has today (2026-11-09)

- **Initiative:** `app.initiative_order: list[rpg.InitiativeEntry]` (all fields
  writable), `app.turn_idx`, `app.round_num`. `_begin_combat` (`main.py` ~5051) rolls it;
  `_advance_turn` (~5457) steps it, along with effect ticks, NPC turns and much else.
- **Fog on the DM's screen** already works the way a table display needs it to:
  `_draw_fog_overlay` paints never-seen cells solid black, and `_agent_fogged` hides
  non-party tokens inside them. `_refresh_fog` reveals from party positions and then
  `_deploy_fog_revealed_enemies` wakes On Deck mobs. `_begin_combat` reveals and then
  calls `_bench_unrevealed_enemies`.
- **HP:** `combat.damage_agent(bm, idx, n)` and `CombatEngine.heal_agent(...)` clamp at 0
  and at max. `stats.hp_max` and `temp_hp` are writable.

## Step 0 — decided (user, 2026-11-09)

- **D1. The console is the table's display, with a DM toggle.** By default it shows the
  table view: fog solid, mobs in fog hidden, no monster HP numbers (party HP shown). A
  **DM view** toggle ("muting the display") shows everything: fog lifted, every mob, every
  number. While DM view is on, a banner on the map says so, so it isn't left on by
  accident. A view toggle only: it never changes the explored mask.
- **D2. A Tracker mode button** in the DM's session menu. Switchable only out of combat;
  saved with the run.
- **D3. Roll for monsters: yes.** It fills every blank monster entry; same-name mobs share
  one roll. The DM can still overwrite any number.
- **D4. A monster at 0 HP is removed from the screen**: tombstoned through the existing
  `_clear_mob` path (off the board, out of the turn order, indices stay valid). A PC at 0
  HP stays on the board and in the order; the table tracks death saves.
- **D5. Mobs revealed mid-fight roll initiative automatically** (same-name share a roll)
  and **start acting next round**: they are inserted into the order at their total but
  skipped for the rest of the current round.
  **Amended 2026-11-09 (user):** "there's no 'act' in this mode, just put them into the
  initiative list." The group still rolls once, but goes straight into the order at its
  total with no next-round wait. Clicking a name in the running order, or a token on the
  map, moves the ▶ to it and opens its HP box (`App._tracker_select`).

## Steps, in order

### T1 — The mode flag and the gate
- `app.tracker_mode` (D2). With it on: the player server takes no joins, NPC automation
  never fires, the combat panel draws no action rows, and Begin Combat becomes **Begin
  Encounter** (T3). Map drag, Agents…, terrain/lighting editors and the fog toggle are
  unchanged.
- **Tests:** `tests/test_tracker_mode.py`: no NPC turn, no action rows, toggle refused
  mid-combat.
- **Landed 2026-11-09.** The toggle is `menus.dm.set_tracker_mode`, a row in the Table…
  menu. "No joins" is done by stopping the player server on the way in and restarting it
  on the way out (only if the toggle stopped it), so `net/` is untouched. Tracker mode
  filters `_action_menu` to the `session` group (Pause, reaction timer, End Combat,
  Table…), so End Turn is gone too until T3's Next/Prev; the panel skips from the order
  to the log (`_draw_combat_panel_log`, extracted). Begin Encounter is a status-line stub
  until T3. Not yet saved with the run (T6).

### T2 — The tracker model (`gui/tracker.py`, pure Python)
- Entries `(agent_idx, total | None, joins_round)`, `round`, `turn`, `phase` (`idle` /
  `collecting` / `running`). `set_total`, stable sort (ties keep entry order),
  `move(idx, ±1)` for manual reorder / delayed turns, `add(idxs, total, joins_round)`,
  `remove` (D4), `next` / `prev` (skip removed entries and entries whose `joins_round` is
  later than the current round, D5; wrap → round + 1), `to_json` / `from_json`.
- `main.py` mirrors it into `initiative_order` / `turn_idx` / `round_num`, so the existing
  initiative drawing keeps working.
- **Tests:** `tests/test_tracker.py`: sort, ties, reorder, skip-dead, wrap, add mid-fight,
  JSON round-trip.
- **Landed 2026-11-09.** Entries are keyed by `agent_idx` (one per agent); `remove`
  tombstones (`removed` flag), so the entry keeps its place and round-trips. `turn` is a
  position: `move` on the acting entry hands the turn to the one that was next (a delay).
  `add` inserts after equal totals and keeps the acting entry acting; `start()` sorts and
  hands round 1 to the top. Rounds are 1-based in the tracker; `App._mirror_tracker`
  writes `round_num = round − 1`, leaves removed entries out, and draws a blank total as
  0. `app.tracker` lives in `App.__init__`; nothing calls the mirror yet (T3 does).
  `test_tracker_mode.test_mirror` covers the mirror.

### T3 — Begin Encounter and entering initiative
- **Begin Encounter:** fog reveal + `_bench_unrevealed_enemies`, as `_begin_combat` does,
  then a list of every in-play token, one number field each (mob groups share one row),
  **Roll for monsters** (D3, `roll_initiative_for` once per name), **Start** (blanks sink
  to the bottom) and **End Encounter**.
- Running: the order, the current turn, the round, **Next** / **Prev**, ↑/↓ per row.
- Revealed mobs (D5): `_deploy_fog_revealed_enemies` in tracker mode rolls once per name,
  adds them with `joins_round = round + 1`, and logs "Ghoul ×3 join at 14 next round".
- **Tests:** totals sort correctly; Start with blanks; Roll for monsters fills only
  blanks and shares by name; a revealed group is skipped this round and acts next round.
- **Landed 2026-11-09.** `_begin_encounter` reveals, benches, fills the tracker with every
  in-play token (blank totals, phase `collecting`) and sets `combat_active` so the combat
  panel draws, without the engine loop: no roll, no recording, no `_proceed_to_new_turn`.
  `_mirror_tracker` mirrors an empty order until Start, so `_current_agent_idx()` is −1
  while totals are collected. The sheet is `menus.panel.draw_tracker_section`; clicks and
  typing go through `App._tracker_handle_event` (ahead of the arrow/zoom keys), fields
  commit per keystroke, Tab/Enter walks down the rows. The session row shrinks to **End
  Encounter** (the `end_combat` id, relabelled in `actions.py`) and Table…; Pause and the
  reaction timer are dropped. In tracker mode `_advance_turn` is `_tracker_step(+1)`, so
  `_clear_mob` and any other caller step the tracker; a step first tombstones entries
  whose token left the board. On Deck joins (fog wake-up or a manual Deploy click) go
  through `_tracker_join`: blank while collecting, one roll per group and
  `joins_round = round + 1` once running. Rolls go through `App._tracker_roll` (one
  seam, so tests can fix the number). `_end_combat` resets the tracker. While running,
  each token is its own row (a mob group sits together at one total, but Next steps
  through it member by member). `test_tracker_mode.py` now begins through Begin
  Encounter, not `_begin_combat`.

### T4 — HP
- Click a row or a token → HP box: `−N` (damage, temp first), `+N` (heal, clamped), set
  temp, set max. One combat-log line per change. A monster reaching 0 → `_clear_mob`
  (D4); a PC reaching 0 stays.
- HP display follows D1: table view shows party HP only; DM view shows every number.
- **Tests:** temp absorbs first, clamps, a monster at 0 leaves the board and the order,
  a PC at 0 keeps its turn.
- **Landed 2026-11-09 (after T5).** The HP box is inline in the panel, under the sheet
  (`menus.panel._draw_hp_box`), in either phase. A click on a running row's name (kind
  `hp_open`) or on a token (the drag press) opens it on that token. Typed digits fill the
  amount (Esc closes, so does ×); **−N / +N / Temp / Max** apply it through
  `App._tracker_hp_apply`, which writes the engine stats directly. A monster at 0 goes
  through `_clear_mob` (stepping on first if it was acting) and is tombstoned in the
  tracker at once, not on the next step. D1 is `App._tracker_hp_shown`: party HP always,
  monster HP only when `app.dm_view` (added here, default off; T4b adds its toggle). It
  governs the row HP, the box header, the log line's "x/y HP" tail and the token HP bar.

### T4b — DM view toggle (D1)
- `app.dm_view` (default off) with a button next to Fog. On: `_fog_active()` is false for
  drawing and `_agent_fogged` hides nothing, and monster HP numbers are drawn; a "DM VIEW"
  banner sits on the map. Off: today's fogged drawing. Reveal (`_refresh_fog`) is
  unaffected either way.
- **Tests:** toggling shows/hides a fogged mob and leaves `explored_cells()` unchanged.
- **Landed 2026-11-09.** The button heads the encounter sheet (both phases), not the Fog
  row: the setup panel holding Fog is put away once an encounter begins, which is when
  the toggle is needed. `_fog_active()` gains `not dm_view`, so the overlay, the token
  gate, hover names and door visibility lift together; `_party_fog_active()` and the
  reveal are untouched. A red "DM VIEW" bar runs across the top of the map
  (`_draw_dm_view_banner`). `_end_combat` turns it off, since its button goes with the
  sheet.

### T5 — Moving tokens
- The DM drags any token, with no budget and no opportunity attacks; the drop marks fog
  dirty, so reveal and On Deck wake-up run as for any move.
- **Tests:** a drag that sees into a room reveals it and wakes its On Deck mobs.
- **Landed 2026-11-09.** Tracker mode is treated like a pause at the three drag gates in
  `_handle_events` (press: any token; motion: no reach clamp; release:
  `set_agent_position` + `_mark_fog_dirty`, not `commit_move`), so there is no budget and
  no opportunity attack, before Start too. The fog reveal on the next frame wakes On Deck
  groups through `_tracker_join`.

### T6 — Save and resume
- `tracker_mode` and `Tracker.to_json` go in the run save (`save_layout.py`), so a session
  can stop mid-fight and resume on the same turn with the same HP. Fog and positions are
  already saved.
- **Tests:** save mid-round, reload, same order / turn / round / HP.
- **Landed 2026-11-09.** Mid-fight state rides on the existing combat sidecar, which every
  resume path (Restore Autosave, Load Save File, loading an encounter) already reads:
  `_save_combat_state` adds `tracker_mode` and `tracker`, HP comes back with the board
  snapshot, and `_load_combat_state` sets the mode to the save's (the collecting phase
  resumes too). Tracker mode never reaches `_finish_turn_start`, so
  `App._tracker_save_turn` writes the same autosave + turn save after Start, each
  Next/Prev, and a click that moves the ▶. Out of a fight the mode is
  `run.json`'s `tracker_mode` (campaign runs only): written by the toggle, applied when
  the run is opened and when a save's run is swapped in.

### T7 — Live check
- The user runs a short fight with a fogged room holding an On Deck group. Bugs go to a
  findings list here.

## Out of scope

Player screens, conditions, concentration, spell slots, death saves, speed enforcement,
and any engine (C++) change.
