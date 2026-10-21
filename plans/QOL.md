# QOL — Quality-of-Life Improvements

Running list from live play (started 2026-10-21). Items are observations from the DM
(noVNC, :6080) and player (Battle Map, :6081) screens.

Format: **[DM|Player|Both]** short title — what happened, what would be better.

## Open

1. **[Both] Homogenize layout / map zoom across DM and player screens** — The DM screen
   puts its controls in a panel on the right; the player screen puts them (Round / On the
   board / Log) along the bottom. So the map renders at a different relative zoom on each
   screen, even in the same browser at the same window size. Pick one layout (or one sizing
   rule for the map area) so both views show the map at the same scale.

3. **[Player] Merge initiative and health into one table** — The player screen shows the
   initiative order ("Round" panel) and creature health ("On the board" panel) as two
   separate panels. Combine them into a single table in initiative order (name, initiative,
   health/condition, current-turn marker), like a real table's initiative tracker.

4. **[Player] Match the DM's action-panel groupings** — The player action bar is one flat
   row of identical yellow buttons. The DM's Combat panel groups them into Action / Bonus
   Action / Movement, with per-button colours (green Attack, purple Cast Spell, blue Dash,
   etc.) and greys out unavailable actions (e.g. Lay on Hands). The player view should use
   the same groups, order, colours, and disabled states, so "Cast Spell" (action) vs
   "Spell" (bonus action) is unambiguous.

5. **[Player] Show whose turn it is the way the DM screen does** — On the DM screen the active
   creature is highlighted yellow (▶ marker in the initiative list, yellow outline on its
   token). The player screen has no equivalent on the map or in the initiative/board panels
   (only a text banner above the action buttons). Use the same yellow highlight.

6. **[Player] Drag-to-move preview like the DM screen** — When moving a token on the
   player view, the sprite doesn't follow the cursor to show which square it will land in;
   after the move is committed it just animates from origin to destination. The DM screen
   drags the sprite live so you can see the target square before dropping. Make the player
   view match: live drag preview of the token (and target square) before committing.

## Bugs

- **[Player] Attack button needs 2–3 clicks to register** — On the player screen, clicking
  "Attack" during Ireena Kolyana's turn (adjacent to Strahd) often does nothing the first
  time; it takes two or three clicks before the attack actually arms/registers. Suspects:
  the click racing a live-state re-render that rebuilds the action bar (button replaced
  between mousedown and click), or the request being dropped/debounced server-side.

## Done

- **[Player] No zoom on the player screen** — QOL_PLAN Q1 (2026-10-21): wheel/trackpad,
  pinch, drag-to-pan, + / − / Fit and a % readout; range 50–600% like the DM. Checked live.
