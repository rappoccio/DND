# QOL plan — the player screen catches up with the DM's

Plan for the items in `plans/QOL.md` (2026-10-21). Nearly all of it is the player
client (`gui/net/static/app.{js,css}`, `index.html`); only Q4 touches the server.

## What the code says today

- **The view is pushed 4×/s** (`net/view.PUSH_INTERVAL_MS = 250`), followed by its prompt
  frame. Every `view` and every `prompt` calls `drawPrompt()`, which does
  `list.textContent = ""` and builds every option button again.
- **The board canvas is the map's nominal size** (`cols × cell_px`) scaled by CSS
  (`width: 100%`). No transform, so no zoom or pan; `cellAt()` maps a tap back by the
  CSS ratio alone.
- **Layout:** header → prompt band → board (full width) → three panels below
  (Round / On the board / Log). The DM is the pygame window: map area = window − 340 px
  `PANEL_W`, fit-to-area × `view_zoom` (0.5–6).
- **The wire has no grouping or colour.** `Option.to_wire()` sends
  `id/label/enabled/disabled_reason`. The DM's grouping comes from `Action.group`
  (`actions.py`) and the `_ACT_ROW_*` / `_BON_*` tuples (`main.py`); its colours are on the
  `btn_cbt_<id>` Button widgets (`menus/panel.py` looks them up by that name).
- **Whose turn** is already on the wire: `view.combat.turn_agent`. The client only uses it
  to tint the initiative row.

## Steps, in order

### Q0 — Attack needs 2–3 clicks (the bug). **Deferred — the user is watching it (2026-10-21).**
The cause below would produce an intermittent bug, so "intermittent" fits it. If it
shows up again, this is the fix.
**Cause (from the code, high confidence):** the button is destroyed and rebuilt every
250 ms. A click whose mousedown lands on one button and whose mouseup lands on its
replacement never fires `click`. Holding the mouse longer makes it worse, which fits "2–3
tries". The bug hits every prompt button, not just Attack.
**Fix:** `drawPrompt()` builds the option list only when its signature changes:
`(prompt.id, options [id, label, enabled, reason], awaiting, filter text)`. Otherwise it
leaves the DOM alone. The title, timer and note still update in place.
**Tests:** `tests/app_harness.js` check: two views with the same prompt → the same button
object; a click after the re-render still reaches `submit`; a changed option set does
rebuild.

### Q1 — Zoom and pan on the player board (item 2). **Done 2026-10-21**, checked live.
- The canvas gets its container's size × `devicePixelRatio`. It draws the map through one
  world→screen transform `(scale, ox, oy)`: `ctx.setTransform` once at the top of
  `drawBoard`, and every existing draw call keeps its `col * cell` coordinates.
- **Fit** = the whole map in the board area (today's look). Zoom is a multiplier on fit,
  clamped to 0.5–6, the same as the DM's `ZOOM_MIN/MAX`.
- Input: wheel/trackpad zooms around the cursor. Pinch (two pointers) zooms around the
  midpoint. Dragging empty board pans. +, −, Fit buttons and a "100%" readout go on the
  board corner.
- A tap counts only if the pointer moved < ~6 px, so a pan never fires a cell submit.
  `cellAt()` inverts the transform.
- Zoom and pan stay on this device (like `dnd.animate`). Nothing goes on the wire.
- **Tests:** harness checks that `cellAt` round-trips at several zoom/pan settings, and
  that a pan gesture does not submit.

### Q2 — One layout for both screens (item 1). **Done 2026-10-21**, checked live.
- On a wide window (≥ ~56rem) the player page uses the DM's layout: the board fills the
  left side at full height, and a fixed **340 px** column on the right holds the prompt and
  action panel, the combined table (Q3) and the log. On a narrow window (phone portrait)
  it stacks as it does now.
- Same sizing rule as the DM: fit the map to the board area, × zoom. In the same browser
  at the same window size, both screens then show the map at the same scale at matching
  zoom. They match exactly only when noVNC is not rescaling its canvas; a "Local scaling"
  setting changes the DM's apparent size.
- CSS/HTML only. It goes after Q1 because the board area's size has to drive the canvas.

### Q3 — Initiative and health in one table (item 3) + turn highlight (item 5). **Done 2026-10-21**, checked live (suite 186/0, `tests/test_roster.py`).
- Replace "Round" and "On the board" with one table: **▶ marker · name · init · HP
  (numbers or band) · conditions**, in initiative order. Creatures on the board but not in
  initiative go below a divider. Out of combat it lists the board alphabetically, as now.
- The `turn_agent` row gets the DM's yellow ▶ and highlight. On the board, that token gets
  the DM's yellow outline (take the colour from `main.py`'s turn ring). `turn_agent` is
  null for a creature this viewer can't see, so nothing is drawn for a hidden one, which is
  correct as is.
- Client only.

### Q4 — The DM's action groups, order, colours and disabled states (item 4)
- **Server:** `prompts.Option` gains two optional fields, `group` and `color` (hex).
  `to_wire()` sends them only when set, so every other prompt stays as it is.
  `net/offer.offered()` fills them in:
  - `group`: Move → `"movement"`; everything else from `Action.group` (`action`, `bonus`,
    `turn`, `utility`, `portent`).
  - `color`: read off `btn_cbt_<id>.color`, the same widget the DM draws. One source, so
    the two screens can't drift apart. No widget → no colour → the client's default.
  - order: the DM's draw order (`_ACT_ROW_*`, then `_BON_*`). If the menu is already built
    in that order, keep the menu order; check that first.
  - The fields are additive. `PROTOCOL_VERSION` stays 1, and an older client ignores them.
- **Client:** for `kind:"action"`, draw a section per group with the DM's headings
  ("Action", "Bonus Action", "Movement", then turn control), buttons in each section's own
  colour, and disabled buttons greyed like the DM's, with the reason still shown. Other
  prompt kinds look as they do now.
- **Tests:** `tests/test_offer.py`: `atk_action`, `spell_action`, `spell_bonus`, `dash` carry
  the right group and colour, and Move is `movement`. Harness check: sections render in
  order.

### Q5 — Drag to move with a live preview (item 6). Depends on Q1.
- **No Move button on the player screen** (decision 2): dragging is how you move.
- Press on **your own token** → the sprite follows the pointer and the cell under it is
  outlined: green if it is in `you.reachable`, red if not. Release on a green cell →
  `submit({cell})`. Release anywhere else → the token snaps back and nothing is sent.
- A drag started while only the **action offer** is up (Move not yet chosen) runs as a
  chain: on drop the client submits `{option:"move"}`, then submits the held cell once
  the Move prompt arrives, if that cell is in `reachable`. Both go through the one
  `submit()`, so F-M5-5's frame count still holds. *(Open decision 2.)*
- Your own drop lands at once, with no origin→destination replay: the client skips the
  `move` event's animation when it matches the cell it just dropped.
- **Tests:** harness checks: drop on reachable submits that cell; drop off reachable sends
  nothing; the chained case sends exactly two submits; your own move does not animate.

## Decisions (resolved 2026-10-21)

1. **Layout (Q2):** the player page matches the DM's right-hand column.
2. **Drag replaces the Move button (Q5):** the player screen shows no Move button. Moving
   is done by dragging your token, through the chain above (`{option:"move"}`, then the
   cell). The server still offers Move: the chain needs it, and the DM console is
   unchanged. Only the client stops drawing it. A drag while the Move prompt is already
   live (after a cancel or reconnect) submits the cell directly.

## Order and size

Q1 → Q2 → Q3 → Q4 → Q5 (Q0 on hold). Each step is one commit with its own
tests, run in the container (`./test.sh`). As each one lands, move its item in `QOL.md`
to *Done*.
