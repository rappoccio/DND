# Hover Tooltips — Implementation Plan

Hover-over tooltips for everything in the GUI: map tokens, map cells, panel buttons,
combat-panel readouts, and dialog rows. Status checkboxes are updated as work lands,
mirroring the door/floors plan style.

**Nothing here touches C++.** Every field a tooltip wants (HP, AC, speed, conditions,
resistances, slots, resources) is already read by the Python panel, so it is already
across the pybind11 boundary. This is a pure GUI-layer change.

---

## Core design decision: **register on hover, draw once at the end of the frame**

Tooltips cannot be painted where they are detected. `App.run()` (`main.py:19124`) is a
fixed z-ordered list of ~20 `.draw()` calls — map, agents, panel, then every modal, then
the popups. The existing token tooltip (`_draw_agent_hover_name`, `main.py:13724`) fires
*before* `_draw_panel`, so anything a dialog wanted to show would simply be painted over
by the layers above it.

So: a hovered widget does **not** draw its own tooltip. It **registers** one with a
frame-scoped manager, and a single `self.tooltips.draw(self.screen)` at the very end of
`run()` paints the winner.

Two things fall out of this for free:

- **Correct z-behavior with no bookkeeping.** Registration happens in draw order, so
  *last registrant wins* is exactly *topmost layer wins*. A tip from an open dialog beats
  a tip from the map underneath it without consulting `_modal_active()` (`main.py:16893`)
  at all.
- **Stale-rect safety is inherited.** `_draw_combat_panel` parks undrawn buttons at
  `x = -10000` to stop them capturing clicks (`main.py:14866-14875`). A parked button is
  never hovered, so it never registers. No special case needed.

---

## Current architecture (grounding facts)

- **pygame, immediate-mode-ish.** Widgets draw themselves each frame and hit-test against
  a live `.rect`. There is no retained widget tree and no event-bubbling to hook.
- **Hover detection already exists on every button.** `Button.draw()` (`widgets.py`)
  already calls `pygame.mouse.get_pos()` and `self.rect.collidepoint(...)` to pick its
  hover color — it computes the answer and throws it away.
- **There are TWO `Button` classes.** `widgets.Button` (used by `main.py`, imported at
  `main.py:43`) and a private copy at `dialogs.py:2521` (used internally by the dialogs).
  Both need the `tip` field. Unifying them is tempting but out of scope — note it and move on.
- **A working tooltip already exists.** `_draw_agent_hover_name` (`main.py:13724`) solves
  cursor-relative anchoring, viewport clamping against `_panel_x()`, and fog-of-war gating
  (it refuses to name an unexplored non-party token). It becomes the **renderer** for
  every phase below; only its *content* is token-name-specific.
- **Some hit rects are already kept.** `initiative_item_rects` (`main.py:633`),
  `on_deck_item_rects` (`main.py:634`), `_dungeon_nav_rects` (`main.py:528`). These are
  nearly-free tooltip surfaces.
- **Most combat-panel info has NO hit rect.** `_draw_combat_panel`
  (`main.py:14866-16674`, ~1,800 lines) blits its text through a local `txt(s, x, y)`
  helper that captures no rectangle. Every readout you want hoverable must record one at
  draw time. **This is the whole cost of Phase 3.**
- **Cell geometry is free.** `_screen_to_cell` + `_draw_cursor_cell_info`
  (`main.py:16846`) already resolve the cell under the pointer every frame.

### Content sources — what exists vs. what must be authored

| Source | Count | Has text? |
|---|---|---|
| `spells.json` | 399 | ✅ `description` |
| `armor.json` | 11 | ✅ `description` |
| `items.json` | 8 | ✅ `description` |
| `classfeatures.json` | 5 | ✅ `description` |
| `DND2024_MonsterStats.json` | — | ✅ full stat blocks |
| **Conditions** (`agent.hpp:695-726`) | ~20 | ⚠️ rules text exists **as inline C++ comments** — lift once into JSON |
| `weapons.json` | 161 | ❌ no `description` — **synthesize** from the flags already stored (`mastery`, `finesse`, `heavy`, `light`, `thrown`, reach/range) |
| **Panel buttons** | 133 | ❌ **hand-author** |

Authored strings live in a new **`gui/tooltips.json`**, keyed by a stable id — not
scattered as literals through `main.py`.

---

## Phase 0 — the manager (`gui/tooltip.py`, ~120 lines)

- [ ] `TooltipManager`: `offer(rect, text, *, title=None, color=None)` records the
      candidate if `rect.collidepoint(mouse)`; later offers overwrite earlier ones (topmost wins).
- [ ] `draw(screen)`: renders the pending tip, then clears it. Reuses the anchor/clamp
      logic lifted out of `_draw_agent_hover_name` (above-right of cursor, flipped below
      when it would clip the top, clamped against `_panel_x()`).
- [ ] Multi-line + wrapped body text (spell descriptions are long — `textwrap` is already
      imported in `main.py`), optional bold title line, optional accent border
      (`_draw_agent_hover_name` already tints its border by `faction_color`).
- [ ] Hover **dwell delay** (~350 ms) so tips don't strobe while the pointer crosses the panel.
- [ ] Add `tip: str = ""` to **both** `widgets.Button` and `dialogs.Button`; when set and
      hovered, `draw()` calls `mgr.offer(...)`. Manager reachable as a module singleton so
      the dialogs don't all need a new constructor arg.
- [ ] One line at the end of `App.run()`: `self.tooltips.draw(self.screen)` — **after**
      every modal and popup, immediately before `pygame.display.flip()`.
- [ ] Loader for `gui/tooltips.json` (id → text), with a missing-key fallback that returns
      `""` (a missing tip is silently no tooltip, never a crash).

## Phase 1 — map layer (tokens + cells)

- [ ] Rewrite `_draw_agent_hover_name` → `_offer_agent_tooltip`: full stat card
      (name, HP/max, AC, speed, active conditions, resistances/immunities) instead of
      name-only. **Keep the fog-of-war gate** — an unexplored non-party token must not leak
      its stat block. Keep the faction-colored border.
- [ ] Cell tooltip: terrain type, light level, cover, door state (open/closed/locked/arcane),
      ladder target floor, ground items. All resolvable from the existing
      `_screen_to_cell` result.
- [ ] Condition badges drawn on a token (`_draw_one_agent`, `main.py:13919`) get sub-token
      hit rects → per-condition tooltips from the authored condition text.
- [ ] Decide: does the cell tip suppress the token tip, or do they merge into one card?
      (Recommend: merge — one card, token section on top of cell section.)

## Phase 2 — panel buttons (133 buttons; 107 are `btn_cbt_*`)

- [ ] Author `tooltips.json` entries for all 133. Each: what it does, what it costs
      (action / bonus action / reaction / resource), and why it's greyed out if disabled.
- [ ] Pass `tip=` at each `Button(...)` construction site. Mechanical — no other plumbing,
      because `Button.draw()` already knows it's hovered.
- [ ] **Highest value per unit of work in the whole plan.** This is the layer where a
      player actually asks "what does this cost me?"

## Phase 3 — combat-panel internals ⚠️ *scope this explicitly before starting*

- [ ] Free wins first: `initiative_item_rects`, `on_deck_item_rects`, `_dungeon_nav_rects`
      already hold rects — offer tips straight from them (initiative row → that agent's
      stat card, reusing the Phase-1 renderer).
- [ ] Everything else needs a rect captured at draw time. Extend the local `txt()` helper
      to optionally return/record its blit rect, then opt in per readout.
- [ ] **Recommended scope cap:** spell-slot pips, resource counters (Ki / Rage / Bardic /
      Sorcery / Lay on Hands / …), and condition badges. Stop there.
- [ ] Explicitly **out of scope**: every static section label and every incidental number
      in the 1,800-line panel. "Everything" has no natural stopping point here and this is
      the phase that will balloon.

## Phase 4 — dialogs (24 classes across 6 files)

Payoff is concentrated in the *pick-from-a-list* dialogs, where the description already
exists in JSON and the row rect already exists for click handling:

- [ ] `SpellSelectionDialog` (`dialogs.py:3037`) + `SpellGridMenu` (`dialogs.py:2907`) —
      hover a spell → full `description` from `spells.json`. **The single best tooltip in
      the game.**
- [ ] `ItemSelectionDialog` / `ItemsDialog`, `ArmorSelectionDialog` / `ArmorDialog`,
      `WeaponSelectionDialog` / `WeaponsDialog` (synthesized weapon text — see above).
- [ ] `FeatDialog` (`dialogs.py:942`), `InvocationDialog` (`dialogs.py:448`),
      `MetamagicDialog` (`dialogs.py:680`), `ConditionsDialog` (`dialogs_conditions.py`).
- [ ] `ContextMenu` (`dialogs.py:2834`) row tips.
- [ ] Deferred / probably skip: `StatsDialog`, `WeaponDialog`, `TerrainEditorDialog`,
      `LightingEditorDialog` — these are editors of self-explanatory fields.

---

## Files touched

| File | Phase | Size of change |
|---|---|---|
| `gui/tooltip.py` (**new**) | 0 | ~120 lines |
| `gui/tooltips.json` (**new**) | 0/2 | content, ~150 entries |
| `gui/widgets.py` | 0 | `tip` field on `Button` |
| `gui/dialogs.py` | 0, 4 | `tip` field on the 2nd `Button`; ~10 dialog classes |
| `gui/main.py` | 0–3 | 1 line in `run()`; rewrite `_draw_agent_hover_name`; 133 `tip=` kwargs; rect capture in `_draw_combat_panel` |
| `gui/spell_dialog.py`, `weapon_dialog.py`, `dialogs_conditions.py`, `terrain_dialogs.py`, `lighting_dialogs.py` | 4 | row tips |
| **C++ / bindings** | — | **none** |

---

## Known limitations / risks

- **The `txt()` rect-capture in Phase 3 is the only invasive edit.** Everything else is
  additive. If Phase 3 gets ugly, Phases 0/1/2/4 still ship and still stand alone.
- **Two `Button` classes** must be kept in sync (`widgets.py` and `dialogs.py:2521`).
- **Fog of war must be honored by every map tooltip**, not just the token one — a cell tip
  that names the contents of an unexplored cell is a fog leak.
- **Tooltips are read-only decoration**: no event handling, no click capture, no effect on
  `_modal_active()`. If a tooltip ever needs to swallow a click, this design is wrong.
- **Perf**: `offer()` is one `collidepoint` per drawn widget per frame at 60fps. The panel
  already does this for hover coloring; the map already does it for the hover cursor. Not
  a concern at this scale.

---

## Recommendation

**Phases 0 + 1 + 2** deliver most of the perceived coverage for a fraction of the work and
are independently shippable. Phase 4 is a strong follow-up because the content is already
sitting in JSON. **Phase 3 needs an explicit scope decision from the user before it starts.**

Suggested first slice: **Phase 0 + Phase 1 only** — one tooltip working end-to-end on the
map, before committing to the 133-string authoring grind in Phase 2.

---

## Open decisions for the user

1. **Phase 3 scope** — slots/resources/conditions only (recommended), or genuinely every
   readout in the combat panel?
2. **Token vs. cell tip** — merge into one card (recommended), or token suppresses cell?
3. **Dwell delay** — ~350 ms (recommended), or instant-on?
4. **Verbosity** — full rules text (long, wrapped), or one-line summaries with full text
   only in dialogs? Affects how the 133 button strings get written.
5. **DM vs. player framing** — should an enemy token's tooltip show exact HP/AC, or a
   coarse descriptor ("Bloodied")? Currently the panel shows exact numbers, so exact is
   the status-quo-preserving default.
