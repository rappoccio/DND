# Handoff: live-play bugs, 2026-11-04 (remaining items)

Source list: `plans/BUGS_FROM_LIVE_PLAY.md`, section "Live play, 2026-11-04".

## Already done this session (uncommitted)

All of this is uncommitted on `main`. The full suite passed at **203/0** after the last change.

- **Greyed-out squares:** the Drawn detector's "Wall cell at" now defaults to 100%
  (`gui/dialogs.py:1426`, `gui/main.py:14934`). Existing pages that saved 0.6 keep it
  until changed in Wall Detection….
- **Toll the Dead:** added to `gui/spells.json`. The d12 swap on a wounded target is
  in the Save branch of `executeSpell`. Also added to `CLERIC_DI_SPELL_NAMES`. Test:
  `tests/test_toll_the_dead.py` (registered in the runner).
- **Save cantrips:** they now deal nothing on a successful save, except under Potent
  Cantrip. Breath weapons and auras keep half. Same block in
  `gui/combat_spells.cpp`, plus three tests in `tests/test_cantrip_scaling.py`.
- **Test updates:** `tests/test_picks.py` spell-count asserts went up by one
  (392→393, 80→81, 81→82).

Files to stage by name: `gui/dialogs.py`, `gui/main.py`, `gui/spells.json`,
`gui/combat_spells.cpp`, `tests/test_drawn_wall_detection.py`,
`tests/test_toll_the_dead.py`, `tests/test_cantrip_scaling.py`, `tests/test_picks.py`,
`tests/run_all_tests.py`, `plans/BUGS_FROM_LIVE_PLAY.md`, this file.

## 1. Phone max zoom 600% → ~1000%

- Player client: `gui/net/static/app.js:501` `const ZOOM_MAX = 6.0;`. Its comment says it
  mirrors `main.py App.ZOOM_MAX` (`gui/main.py:1249`, the DM console).
- Fix: raise the JS constant to `10.0`. Change `main.py` only if the user wants the DM side
  raised too. It has a separate `ZOOM_MAX_DIM = 8000` px memory guard
  (`main.py:1252`) that may cap it first.
- Check for a test asserting the limit: `grep -rn "ZOOM_MAX\|6.0" tests/`
  (likely `tests/test_qol*.py` / player-client tests).
- Pure JS, so no rebuild is needed; the player reloads the page.

## 2. Phone menu too big, covers the map

**Decided (user, 2026-11-04): put the menu behind a button that opens it.**

- **Which menu:** almost certainly the `#prompt` section in `gui/net/static/index.html`.
  It is the action/spell choice list (`#prompt-title`, `#prompt-filter`,
  `#prompt-options`, Cancel). Below the 46rem breakpoint (`app.css:162`) the layout is
  one column, so this list stacks **above** the canvas and pushes the board off screen.
  Confirm with the user before you start. A screenshot is ideal. If they mean the
  `.panels` block (roster, log, table) instead, the same pattern applies.
- **Behaviour on phone widths only** (below 46rem; desktop and tablet unchanged):
  - When a prompt arrives, don't expand the list. Show a compact **"Menu" button**
    instead, pinned over the board (bottom edge, thumb reach), labelled with the prompt
    title, e.g. "▸ Aria: choose an action". Give it a visible badge or pulse so the
    player knows a choice is waiting.
  - Tapping it opens the full menu as an **overlay sheet** over the bottom of the board,
    with `max-height` around 60vh and its own scrolling. Include a close (▾) control that
    collapses it back to the button without cancelling the prompt. The **Cancel** button
    keeps its current meaning: decline the prompt.
  - Picking an option closes the sheet, as the prompt clears today.
  - **Cell-pick prompts** ("Tap a highlighted square", `#prompt-hint`) must leave the
    board tappable. Show only the button or title strip there, and never an open sheet
    covering the highlighted squares.
  - A timed prompt (`#prompt-timer`) should show its countdown on the collapsed button,
    so a player who never opens it still sees time running.
- **Where:** markup in `index.html`, styles in `app.css` (new rules inside
  `@media (max-width: 45.99rem)`), and show/hide in `app.js`. Find the code that
  un-hides `#prompt` and renders `#prompt-options`; hang the collapsed/open state there.
  Keep the state per prompt: a new prompt starts collapsed.
- **Don't** change the wire protocol or `net/*.py`. This is client-only, so no rebuild is
  needed; players reload the page.
- **Test:** check for player-client tests first (`grep -rln "prompt-options\|app.js" tests/`).
  If the client has no JS harness, verify by hand at phone width (Chrome devtools device
  mode, ~390px). Check: prompt arrives collapsed, button opens it, close re-collapses,
  option pick clears it, cell-pick leaves the board usable, desktop width unchanged.

## 3. "Automate all NPCs" slider

**Decided (user, 2026-11-04):**
- **NPC = any monster in the red faction** (faction 1, `constants.FACTION_NAMES`).
- **A slider, 0–5, sets every red creature at once.** At 1–5, every red agent gets
  `set_agent_npc_automated(i, True)` plus `set_agent_npc_automation_difficulty(i, level)`.
  **At 0 the slider means Off:** every red agent gets `set_agent_npc_automated(i, False)`
  and goes back to manual. Also reset its difficulty to 0 so a later per-agent toggle
  doesn't resurrect a stale level.
- **It lives under the Agents… panel button** (`gui/menus/dm.py:29`
  `show_agents_menu`).

**What exists:**
- Per-agent toggle and difficulty submenu (0–6): `gui/menus/board.py:251`
  `_npc_automation_menu`.
- Turn-start hook that arms the driver: `main.py:5843` sets `self._npc_drive_idx`.
- Difficulty is an override (plan: `plans/NPC_AUTOMATION_PLAN.md`). 0 = manual
  (per-agent strategy). 1–4 are implemented. 5 is the NN policy and, until trained,
  clamps to 4 with a one-time log line. So "5" works but behaves as 4.

**Design notes for the implementer:**
- Agents… is a popup `ContextMenu` (`_ask_dm`), not a tab, and it can't hold a slider.
  Add a row such as **"Automate NPCs…"** that opens a small docked dialog with the
  slider, like `WallDetectionDialog` in `gui/dialogs.py:1414`, with OK/Cancel.
- There is **no slider widget** yet. `widgets.py:67` has `IntStepper` only. Add a small
  `Slider` (or `IntSlider`) to `widgets.py`: discrete 0–5 stops, drag plus click, value
  label ("Off" at 0, "Level n" otherwise).
- On apply: loop `bm.placed_agents`, filter `bm.get_agent_faction(i) == 1` (bound in
  `gui/bind_battle_map.cpp:191`), skip dead/removed agents, and set both
  fields. Log one line, e.g. "NPC automation: 7 red creatures at difficulty 3."
- If the current turn's agent is red and combat is active, arm `self._npc_drive_idx`
  right away. Otherwise it waits a full round.
- The flags already round-trip through save/load (`main.py:12548`) and copy/paste
  (`main.py:4078`), so nothing new is needed there.
- Remember the last slider value for the session (default 1, or the most common
  difficulty among the reds).

**Test:** a headless GUI test in the pattern of `tests/test_npc_automation*.py`. Place blue
PCs, red mobs and a neutral agent. Apply level 3. Assert only the reds are automated at
3, and the blue and neutral agents are untouched. Then apply 0 and assert every red is
back to manual. Also apply it on a red agent's turn
and assert `_npc_drive_idx` is armed. Register the test in `tests/run_all_tests.py`.

## Reminders

- Container only: `./test.sh`, or one suite via
  `docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && python3 tests/<suite>.py"`.
- No commit and no push unless asked. Stage files by name.

## Status: items 1–3 done (uncommitted), suite 205/0

More files to stage by name: `gui/net/static/app.js`, `gui/net/static/app.css`,
`gui/net/static/index.html`, `gui/widgets.py`, `gui/menus/dm.py`,
`tests/viewport_checks.js`, `tests/app_harness.js`, `tests/prompt_sheet_checks.js`,
`tests/test_prompt_sheet.py`, `tests/test_npc_automation_slider.py`.
Item 2 still needs a check by hand on a real phone (~390px wide).
