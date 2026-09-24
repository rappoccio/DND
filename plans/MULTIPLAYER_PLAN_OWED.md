# The owed items — debt no phase owns

*Written 2026-09-24, at `main` @ `0a4cad5` (M4e landed). Companion to
[`MULTIPLAYER_PLAN.md`](MULTIPLAYER_PLAN.md), which owns the phases; this file owns what
falls between them.*

**State when this was written**: suite **158 pass / 1 fail**, verified with `./test.sh`.
The failing suite is item 1 below — and its usual one-line description in every handoff
since M3 is wrong, which is the first thing this file fixes.

Still dirty, deliberately: `encounters/simplemap_strahd_feastofstandral_terrain.json` and
`maps/TestDNDMap_terrain.json`, both staged and both dirty before M4c. Every commit since
has used an explicit pathspec (`git commit --only -- <paths>`) to keep them out. Leave them
exactly as they are.

Environment is the container and nothing else: `./test.sh` is the oracle, a host run fails
~151 suites on PYTHONPATH and means nothing. `tests/test_mapimg.py` (PIL-only) and the two
Xvfb rigs are the only exceptions and license nothing else.

**These nine items share only that no phase owns them.** The standing rule applies with full
force: **one item, one commit, never bundled** — four of them are behaviour changes and two
of those need a decision before any code is written.

---

## 1. `test_monk.py`'s Deflect fixture — the red suite, and it is not a Deflect bug

Every handoff since M3 has called this "a Deflect Attacks damage assertion in the combat
engine". **It is not.** The failure is at `tests/test_monk.py:505`, which is the *setup*
line, and `apply_deflect_attacks` is never reached:

```
AssertionError: the Slashing hit should land for damage
```

`_hittable_monk_defender` (`tests/test_monk.py:488`) says *"Drop the Monk's AC to 1 so a
50-bonus attack always lands"*. Both halves of that are false, measured rather than read:

- **The Monk's AC is 15, not 1.** `base_ac = 1` is set, and Unarmored Defense computes
  `10 + DEX(3) + WIS(2)` and ignores it. Printed from the live engine:
  `monk AC after base_ac=1: 15`.
- **There is no 50 bonus anywhere.** The attacker is `_soft_target` — Fighter 1, **STR 8** —
  so it swings at roughly **+1**. `_slashing_weapon`'s docstring calls itself
  "guaranteed-hit" and sets only damage dice.

So the check is d20+1 against AC 15, and with the fixed seed (`CombatEngine(42)`) it is
deterministically a miss. The fixture arrived in `224c385` in exactly this shape, so this has
been failing since it was written — a **test-fixture defect, not an engine regression**, and
nothing here shows Deflect Attacks is broken.

The trap: `_hittable_monk_defender` has three callers (`502`, `526`, `540`) and **the other
two pass by luck of the RNG stream**, not because the fixture works. So fixing it will either
change what those two are actually testing or reveal that they were never testing it. Do not
fix the fixture and stop at green.

Fix options, ranked: give the attacker a real attack bonus (proficiency + STR, which is what
the docstring imagines); or make the defender's AC actually low by removing Unarmored Defense
from the picture (a non-Monk defender is not an option — the reaction is a Monk feature); or
force the roll if the engine has a hook for it. Whichever you pick, assert the hit landed
*and* that Deflect then reduced damage, so the test finally covers what its name claims.

**LANDED 2026-09-24.** The first option, through the weapon rather than the attacker's STR:
`Weapon.bonus_hit` is already on the to-hit line (`combat_attack.cpp:225`), so
`_slashing_weapon` and `_fire_weapon` — both of which call themselves "guaranteed-hit" —
now set `_SURE_HIT_BONUS = 50` and finally are. `_hittable_monk_defender` drops the no-op
`base_ac = 1`, keeps the 200 HP pool that is its real job, and says in its docstring why the
AC is 15 and stays 15. Measured after: all three callers land the same ordinary, non-crit
hit (d20 8 + 51 vs AC 15) and then diverge as their names claim — 17 → 9 for L3 physical,
17 → 17 and no reaction spent for the L3 fire type-gate, 17 → 0 for L13 Deflect Energy. So
the other two were not merely passing by luck any more. Suite **159/159**.

---

## 2. `_agent_screen_pos` ignores pan and zoom — 82 prompt sites open away from their token

`gui/main.py:10882`:

```python
x = ag.origin.col * cpx + cpx // 2
y = ag.origin.row * cpx + cpx // 2
```

`_cell_to_screen` (`gui/main.py:2003`) — the function the map itself draws with — does
`raw_v[c] * s + self.pan_x`, using the real grid-line positions, `map_scale` and the pan
offset. So on any panned or zoomed map every popup opens somewhere the token is not.

It has three callers (`5830`, `10731`, `10858`), and the third is `_ask_actor`'s default
anchor — which means it is **all 67 `_ask_actor` sites and all 15 `_ask_dm` sites**, not
three. The plan has called this "the top of the cleanup list" since M1 Steps 1–2.

The fix is small — mirror `_cell_to_screen` and add half a *scaled* cell — and the real work
is the test, because nothing in the suite pans or zooms: every headless check runs at
`map_scale == 1`, `pan == (0, 0)`, where the buggy and the correct formula agree exactly.
That is why it has survived this long. Write the check that pans and zooms first, watch it
fail, then fix the two lines.

**LANDED 2026-09-24**, and it was worse than this entry says. The check was written first
and failed on its *first* case, before any pan or zoom: `map_scale` does not start at 1, it
starts at the fit-to-window scale, which is below 1 for any map wider than the viewport
(0.867 on `TestGrid12x12.png`). Measured on the untouched view, the anchor for a token on
cell (5, 5) was (550, 550) — inside cell **(6, 6)**. So this was not "panned or zoomed maps"
but *every* map that gets scaled down to fit, which is most of them. The suite never saw it
because a headless `App` is built and read, never looked at.

The fix goes through `_cell_to_screen` twice and takes the midpoint of the cell's own two
corners, rather than adding half a nominal `cell_pixel_size`: same answer on a uniform grid,
and the drawn centre on an uneven one. The test is
`test_prompts.py::test_prompt_anchor_follows_pan_and_zoom`, and it states the invariant as
`_screen_to_cell(anchor) == the token's cell` — the inverse the mouse itself goes through —
with the scale-1/pan-0 case pinned to the old formula so the agreement view stays fixed.
Suite **159/159**.

---

## 3. F9 — one digit, and it should move no pixels

`gui/actions.py:646`:

```python
if (stats.barbarian_subclass == rpg.BarbianSubclass.Berserker and lvl >= 10
        and ip > 0):
```

`gui/class_resources.cpp:75` grants "Intimidating Presence" at **`level >= 14`** (correct for
the 2024 PHB — L10 Berserker is Retaliation). So levels 10–13 are a branch that can never
reach the draw, because the `ip > 0` test dominates.

Change the `10` to `14`. **The panel golden should come back byte-identical** — the button
never drew at 10–13 — and if it does not, that is the finding, not the fix. Checkpoint 25
(`tests/test_combat_panel.py:680`) already uses a level-14 Berserker and says why in a
comment.

Checked while writing this: the `zealous_presence` line two below it also reads `lvl >= 10`,
and that one is **right** — `class_resources.cpp:83` grants Zealous Presence at 10. F9 is
Berserker-only; don't "fix" its neighbour.

**LANDED 2026-09-24.** One digit and a comment that now says what the engine says. The
panel golden came back **byte-identical** — all 71 checkpoints match, `.golden.txt`
untouched — which is the prediction this entry made and the confirmation that 10–13 really
was dead. `zealous_presence` was left alone. Suite **159/159**.

---

## 4. F12 — cosmetic, and the golden will move

`tests/test_gui_headless_smoke.py:292` pins three ids in `_KNOWN_TOO_WIDE`:
`btn_cbt_disengage`, `btn_cbt_standup`, `btn_cbt_prone`. §4's five-up posture row gives each
button `TW5 = 60px`, and at `font_sm` **Disengage needs 76px, Go Prone 65, Stand Up 64** —
the final glyph is clipped and the text bleeds across the 4px gap.

Two candidate fixes: shorten the labels, or let the row size itself to its widest. The second
moves rects, which means `test_combat_panel.py`'s structural golden changes — and that golden
is the M2 oracle, so re-blessing it is a deliberate act that belongs in the same commit with
its diff described. `_KNOWN_TOO_WIDE` fails both if a new overflow appears *and* if one of
these three is fixed without being removed from the set, so the pin is the checklist.

The geometry has never moved (`1052,300,60,30` in the golden both before M2a and after M2c) —
this is not an M2 regression, it is a bug a structural golden cannot see, because every rect
is right.

**LANDED 2026-09-24**, the second fix, chosen by the user: the row sizes itself to its
labels. `App._row_widths` gives each column the width its own text needs *when an equal
split would clip and the natural widths still fit*, then hands the leftover slack out
evenly so the row still spans the panel exactly and its right edge still lines up. A row
that fits is untouched, which is why the golden moved in exactly one place.

The re-bless, described: 660 changed lines, all of them §4's posture row, in 66 checkpoints.
`1052,300,60,30 / 1116 / 1180 / 1244 / 1308` (five 60s) becomes
`1052,300,45,30 / 1101,56 / 1161,85 / 1250,41 / 1295,73` — Disengage gets 85 for its 76px of
text, Dash gives up 15 it never used. No other button in the sweep moved by a pixel;
`btn_cbt_standup` differs from `btn_cbt_prone` by one pixel of rounding on the rows where it
replaces it.

Two tests moved with it. `_KNOWN_TOO_WIDE` is now **empty** — kept rather than deleted, so a
new overflow still fails and a re-regression still fails the stale check. And
`test_a_converted_row_is_side_by_side_not_stacked` had been using *equal widths* as its proxy
for "side by side"; it now checks what it was really after, that the members tile one y with
no overlap. Suite **159/159**.

---

## 5. F14 — a drawn button that cannot be clicked (needs a decision)

`gui/main.py:19119`:

```python
if not self.bonus_used:
    # F14: both of these stay INSIDE `not self.bonus_used` ...
    if self._action_clicked("atk_bonus", event):
    if self._action_clicked("spell_bonus", event):
```

The two economy-band headers (`⚔ Bonus Atk` at `main.py:1409`, `✨ Spell` at `1442`) are
*offered* while an Extra Attack sequence is parked in the bonus slot — `bonus_used` is
already True and the sequence still owes swings — but both handlers sit inside the block that
requires `not bonus_used`. So the button that says how many swings are left cannot be
pressed. Checkpoints 08b and 65 draw it.

**This is a decision, not a fix.** The plan's own doubt is worth repeating: it may be
harmless in play, because the remaining swings are driven by map clicks through
`pending_attack_slot` rather than by re-pressing the header. Three honest outcomes — make it
live, stop drawing it mid-sequence, or keep it and say so in the code — and only the first
two are work. Whoever picks needs to have played a multiattack round.

---

## 6. F11 — an unreachable arm (needs a decision)

`gui/actions.py:627`:

```python
fleet_step_ready = (... and lvl >= 11 and not cond.fleet_step_used
                    and app.bonus_used)
if focus > 0 or fleet_step_ready:
```

`fleet_step_ready` requires `app.bonus_used`, and it is written inside a band gate that
already required `not bonus_used`, so the arm can never fire. Open Hand L11's free Step of
the Wind with the bonus action already spent is a feature the panel describes and does not
offer. The handler side is `gui/main.py:19179-19198` and does implement it.

`tests/test_action_menu.py:856` (`test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable`)
**pins the broken shape on purpose** — making the arm live means inverting that test in the
same commit, which is the right amount of friction for a rules change. Same class of decision
as F14: someone has to say whether the 2024 Open Hand L11 feature should work here.

---

## 7. `gui/menus/` — the big one, owed by two phases

`main.py` is **20,123 lines**. M1 Step 3 expected it to go *down* and it went **up by 83**,
because converting 79 prompt sites replaced a two-line tail with a one-to-three-line call and
the shared helpers cost more than the tails saved. The option builders never moved. M1 named
the destination (`gui/menus/`, a module per feature area) and the time (after M2, which is
now past); M2's own carry-out list repeats it.

The measurable scope: **67 `_ask_actor` callers and 15 `_ask_dm` callers**, plus the panel's
rendering helpers M2 left behind. `_ask_actor` / `_ask_dm` (`main.py:10832`, `10861`) are the
seam and should **not** move — they hold the owner defaulting and the anchor, which is where
authorization and F11-class mistakes live.

Three oracles make this provable rather than brave: `test_combat_panel.py`'s structural golden
(the panel must stay byte-identical), `test_prompts.py` (the bus drives a real reaction with
no pygame events), and `test_action_menu.py`'s 52 checks. Do it in feature-area slices with
the golden green after each, and **never together with any of items 3–6** — a relocation whose
diff also changes a rule is a relocation nobody can review.

---

## 8. The client is never rendered

`tests/test_live.py` parses `gui/net/static/app.js` with `node --check` and asserts three
properties by reading it (sessionStorage, no `localStorage` access, exactly one `send`).
**Nothing draws it.** A layout or canvas bug in `app.js` is invisible to `./test.sh`, the same
way F3's finding was invisible until it ran on a real display — except this one wants a
browser, not an Xvfb.

Cheapest honest first step is a manual pass: `./run.sh maps/TestDNDMap.png` (needs the user's
permission — it publishes ports), read the join code off the console, open the URL on a phone
and on a laptop, and check four things the suite cannot: the fog rectangles line up with the
art, tokens sit on their cells, the initiative list and log fill, and a reload keeps the seat.
Two of M4e's owed items predict what you will find — the lattice is nominal while the console
uses real grid-line positions, and the active token is not marked at all.

---

## 9. Not this plan: `COMBAT_REFACTOR_PLAN.md` R4

R4 (sub-engines behind a facade) is still **IN PROGRESS** — 3 of 7 cuts and 1 of 2
mis-groupings as of 2026-09-15. Untouched by every M-phase. Its oracle is
`test_determinism.py`, which must stay byte-identical. Listed only so it is not forgotten; it
is a different document's work.

---

## What is deliberately not in here

M4e's four owed items are **phase-attached** and belong to the phases that reopen the things
they touch, not to this list: the missing turn cursor and the nominal lattice are Envelope 2
changes and therefore **M4b**'s; `send_json` serializing on the net loop is unmeasured and
**M7**'s alongside the PNG executor; `_fog_active()` being False during a terrain edit is
**M7**'s or its own item and is the one with a real security shape. All four are written up in
`MULTIPLAYER_PLAN.md` at *"Owed, and named rather than bundled"* under
`#### The push socket and the client`.

Also carried and unchanged: the roster has no lock (a DM seating a principal in the same
instant as a `POST /join` can 500 that one join), A9's audit log is still a `denials` counter,
`X-Forwarded-For` is unread on purpose, `_free_port()` in `test_mapserver.py` binds and
releases (a race in principle), and `test_gameview.py`'s byte-level probes must stay ≥4
distinctive digits (they are 4281–4286).

**Suggested order**: 1 (the suite should be green before anything else moves), then 2, then 3,
then 8's manual pass — it will inform F12 and both decisions. Then 5 and 6 once someone has
played the rounds. 7 last, alone, in slices.
