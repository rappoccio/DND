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

**These ten items share only that no phase owns them.** (Nine when this was written; item 10 was found by item 8's manual pass and appended on 2026-09-24.) The standing rule applies with full
force: **one item, one commit, never bundled** — four of them are behaviour changes and two
of those need a decision before any code is written.

---

## Pick up here — 2026-09-24, after the first manual pass

**State**: `./test.sh` green at **160 suites / 0 failures**. Items **1–7 have landed**, one
commit each, `8cec103` … `0b0f561`. Item 8 is **IN PROGRESS** — its manual pass has run once
and produced five findings (four real defects, one authored-scene misread); commits
`1005a5d`, `b4a92a0`, `5bb8681`, `c1e4e61`. Items **9 and 10 are untouched**.

**The next step is finishing item 8's manual pass**, not writing code. The pass exists to
answer four questions the suite cannot, and *none of them has been answered yet* — every
session so far was spent on defects that blocked getting far enough to ask:

1. Do the fog rectangles line up with the art? M4e predicts they do **not** — the client's
   lattice is nominal `col * cell_px` while the console and the server's mask use the real
   detected grid-line positions. A mismatch here is **M4b**'s, not this file's.
2. Do tokens sit on their cells?
3. Do the initiative list and the log fill as the DM plays rounds?
4. Does a reload of the phone keep the seat? (`5bb8681` should have made this true; it has
   not been confirmed by a human.)

**How to run it**: the DM launches `./run.sh maps/TestDNDMap.png` (it publishes ports — ask),
reads the join code off the console, and opens the URL on a phone; the next session reads the
console log and probes the live server from the host rather than guessing. The map is now lit
(`c1e4e61`), so fog reveal finally does something — **reload the encounter** after launching
if the app was already up, since lighting is read at load.

**Two housekeeping rules that have bitten twice.** `maps/TestDNDMap_agents.json` is *tracked*
and is `test_replay_roundtrip.py`'s fixture; the app overwrites it on save, so
`git checkout -- maps/TestDNDMap_agents.json` after any manual pass on that map.
`encounters/simplemap_strahd_feastofstandral_terrain.json` and `maps/TestDNDMap_terrain.json`
stay staged-and-dirty — every commit uses `git commit -m … --only -- <explicit paths>`.

**If code is wanted instead**, there are exactly two things ready to start, and they are
independent of each other and of the pass:
· **Item 7's remainder** — the right-click map menu (14 prompt sites still inline in
  `App._handle_events`) and the panel rendering helpers M2 left behind. Next slice, same
  shape as slices 1–4.
· **Item 10** — the lighting editor's missing base-light button. Small, UI-only, and the
  reason finding 5 cost a session.

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

**DECIDED 2026-09-24 by the user: make it live — and it is only half the item.** The two
headers are not the same button. `atk_bonus` is `atk_action`'s mirror: the Action side has
dispatched its attack header ungated since F3, on the offer the menu drew, precisely so a
parked sequence can be resumed. That handler is now ungated too, and `_start_attack` resumes
rather than reseeds (`attacks_remaining != 0` skips the seed), so the click means what the
label says.

`spell_bonus` is **not** that mirror and stays refused. Its opposite number is
`spell_action`, which is one of D-M2-4's five: drawn mid-sequence because the band stands
open, refused by the handler because the economy is spent. A Bonus Action spell cannot be
cast with the Bonus Action already gone into the sequence, so making that one live would
have been a rules bug wearing F14's clothes.

Two checks, each verified against its own mutant — put the handler back inside the gate and
`test_the_bonus_attack_header_is_clickable_mid_sequence` fails; ungate `spell_bonus` and
`test_the_bonus_spell_header_is_drawn_mid_sequence_but_refused` fails. Suite **159/159**.

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

**DECIDED 2026-09-24 by the user: make the arm live.** It took three moves, not one, because
the arm was unreachable in three places at once:

1. **The menu.** The offer is hoisted ABOVE `_bonus`'s `if app.bonus_used: return`, which is
   the only side of that return where `bonus_used` is True. The unspent-band arm stays below
   and now reads plain `focus > 0`, so the two arms are mutually exclusive by construction and
   the option can never be offered twice. The five-term predicate they used to share by
   hand-copy is `actions._fleet_step_ready(stats, cond)`, which deliberately says nothing
   about `bonus_used` — the caller supplies the state, the helper supplies the creature.
2. **The panel.** `step_of_wind` sits in `_BON_RUN_BAND`, and the band stack is drawn only
   `if not bonus_used`, so an offered arm would still not have been painted. The spent side
   gets an `elif` that draws exactly this one group; it is empty for everyone else and an
   empty stack costs no vertical space.
3. **The handler.** It was inside `not self.bonus_used` too — F14's shape on a second button
   — and is dispatched outside the gate now. Its own `fleet_step` test already distinguished
   the free arm from the focus-paying one, and the focus arm still refuses to run with the
   Bonus Action spent.

`test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable` is inverted to
`..._is_reachable`, and a second check clicks it: movement goes up, `fleet_step_used` is
spent, the Focus Point is **not**, and `bonus_used` stays True. The panel golden is
**byte-identical** — no checkpoint holds an Open Hand 11 with the Bonus Action spent, which
is why nobody had ever seen this button. One thing deliberately unchanged: the option's
`economy` stays `"bonus"`, because `ECONOMY_VARIES` means "depends which thing is picked"
and this depends on the turn's state, not the choice. Suite **159/159**.

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

**IN PROGRESS from 2026-09-24**, one commit per slice, each with all three oracles green and
items 3–6 already landed and out of the way.

The shape every slice takes: a builder becomes a module-level function whose first argument is
the live `App` (`actions.py`'s `ActionMenu.build(app, idx)` set that precedent), `self` becomes
`app`, and every call site — including the handful in `tests/` — is repointed. `_ask_actor` and
`_ask_dm` do **not** move; the builders keep calling them through `app`.

| slice | module | methods | lines out of `main.py` |
|---|---|---|---|
| 1 | `menus/riders.py` — the post-hit attack riders | 25 | 845 |
| 2 | `menus/reactions.py` — the defender/third-party reactions | 6 | 246 |
| 3 | `menus/dm.py` — the authoring menus, all `_ask_dm` | 9 | 178 |
| 4 | `menus/features.py` — the per-feature menus | 16 | 495 |

`main.py`: **20,191 → 18,419**, which is the reversal M1 Step 3 expected and did not get.

**What slice 3 shipped broken, and what closed the hole.** The rewrite repointed *calls*
(`self._x(…)`) and not bare *references*, so `show_agents_menu`'s `("Create PC…",
app._show_pc_class_menu)` raised `AttributeError` the moment the menu was built. All three
oracles were green through it, because not one of them builds a top-bar DM menu or a
per-feature menu; the DM found it in one click. `tests/test_menus.py` now covers the class
both ways — statically, every `app._name` a menus module mentions must exist on a real `App`;
and at runtime, every builder that needs nothing but the app is called and its rows checked
for callables. Both halves fail on the shipped bug. A third check pins the rule the package
exists to respect: `_ask_actor`/`_ask_dm` stay in `main.py` and no menus module calls the bus
directly.

Also carried out with the features slice: `PACT_CHAIN_FAMILIARS` and `COMMAND_WORD_OPTIONS`
moved next to the menus that draw them (`main.py`'s own Command site imports the table from
there, which is the direction that already exists), and Wild Shape's `beast_forms.json` path
was `os.path.dirname(__file__)` — main.py's directory when the code lived there, and one
level too deep once it did not.

**Still owed on item 7**: the right-click map menu, still built inline in `_handle_events`
(the 14 sites there), and the panel's rendering helpers M2 left behind.

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

**STARTED 2026-09-24**, the user driving the console and the phone, and it paid for itself
before any of the four questions could be asked.

**Finding 1 — the first seated player crashes the app.** `view.py:214` projected a sheet's
resources with `for r in stats.resources`, and `stats.resources` is the C++
`std::map<std::string, Resource>`, so Python sees a **dict keyed by name**: the loop walks
the KEYS and `"Second Wind".name` raises `AttributeError` inside `_push_views`, which is on
the frame tick, which is the app. The trigger is one right-click — *Controller ▸* on a token
whose class has any resource at all. The suite could not see it: no fixture had ever called
`initialize_class_resources`, so every sheet it ever built belonged to a creature with an
empty dict, where iterating keys and values are the same thing. Fixed with `.values()`, and
`test_gameview.py::test_a_sheet_lists_the_creatures_class_resources` gives the owned creature
real resources first and fails on the old line.

**Finding 2 — the manual pass and the test fixtures share a file.** Running on
`maps/TestDNDMap.png` makes the app save `maps/TestDNDMap_agents.json`, which is *tracked*
and is `test_replay_roundtrip.py`'s fixture (`need >=2 agents in fixture, got 0` when the app
had saved an empty board over it). Restore it with `git checkout --` after any manual pass on
that map, or the next `./test.sh` reports a regression that is really a session save.

**Finding 3 — the map art never loaded on any client, and that is why the board is dark.**
The DM reported "the entire map is obscure on the phone" while every token was visible.
Probing the live server from the host settled it: `/state` names
`"image": "/map.png?v=45fe9815c28ce822"`, that URL serves **153 KB of PNG with a
credential**, and **401 `unauthenticated` without one** — which is correct and is asserted
(`test_mapserver.test_unauthenticated_is_401`). The client did `img.src = url`, and a
browser can no more put a bearer header on an image request than on a WebSocket handshake,
which this very file says in its own comments about the socket. So every `<img>` fetch was
a 401, `onload` never fired, and `drawBoard` left its `MASK` fill covering the board — for
every client, fog or no fog, for the whole life of M4e. `app.js` now **fetches** the art
with the credential and decodes it from a blob, releasing the previous one; a key that
will not load is remembered, retried at a human interval rather than per frame, and said
out loud instead of failing silently. `test_live.py` pins the shape statically, which is
the only way available: nothing in the suite renders this file.

**Not a bug — the fog gate was simply down.** All tokens crossing to the phone is what
`fog.active: False` means; `_fog_active()` reads `show_fog`, the DM's own toggle, and M3's
rule is that a client never sees *more* than the console, not that it always sees less.
Turn fog on and the unexplored non-party tokens go.

**Not a bug — there is no player input yet.** `app.js` sends exactly one frame ever, the
auth frame, and `test_live.test_the_client_has_no_input_surface` pins the count at 1 on
purpose: D-M4e-3 made M4e read-only, and M5 is the gate a game action would have to arrive
through. A seated player cannot move their PC because nothing in the protocol lets them
yet — the seat is real, the view is theirs, the input is M5's.

**Finding 4 — loading an encounter logged every player out.** Reported as "it crashed when
I loaded the agents", and it was neither the phone nor a crash: `_set_encounter_base`
replaced the `SessionRoster` on *every* call, and `SessionRoster.__init__` mints a fresh
signing key (A5), so every outstanding credential stopped verifying at once. Every socket
then closed with `WS_CLOSE_UNAUTHENTICATED`, and `app.js` did exactly what it should —
forgot the credential and showed the join card. Measured rather than reasoned: the
credential minted before the DM's load returned **401 `unauthenticated`** afterwards,
while a fresh join with the *same* join code succeeded, because the code is persisted in
the session file and only the key is new.

Replacing the roster is right when the table changes and a mass logout when it does not, so
it now happens only when `_session_path` actually moves. `test_session_roster.py` pins both
halves: re-loading the open encounter keeps the roster object, the seat and a live
credential; pointing at a different encounter still re-keys and still refuses the old one.

**Finding 5 — not a bug: the party was fighting in the dark because the map is unlit.**
Reported as "when I switch fog on, the agents disappear... when I start combat the fog from
my Team is not lifted". Measured against the live session: all **320** cells of
`lighting.cells` read `"Dark"` and `fog.explored_runs` was **empty** — the explored mask had
never held a single cell. `maps/TestDNDMap_lighting.json` was
`{"default_light": "Darkness", "light_sources": []}`, not one torch on the board, and no
agent in `maps/TestDNDMap_agents.json` carries a `darkvision_range`.
`BattleMap::revealFogForFaction` ORs in only the cells `canSee` accepts, and in `Dark`
`canSee` is `darkvision_ft > 0 && dist_ft <= darkvision_ft` (`battle_map.cpp:1866`) — so a
PC with no darkvision reveals nothing, *including the cell they stand on*. An empty mask
fogs every non-party token off both screens and masks the whole page for every player.
Starting combat cannot change it: combat start is not a vision event, it only marks the mask
stale, and re-running a reveal that reveals nothing reveals nothing.

The engine was right; the scene was pitch black. The DM chose to light the map, so
`maps/TestDNDMap_lighting.json` now reads `"BrightLight"` — a one-line change, safe because
nothing in `tests/` or `gui/` reads that file (an absent lighting file resets the base to
`Clear` anyway, `main.py:13366`). The two other ways out, for the record: right-click an empty
cell with fog on → **Reveal all fog**, which paints the mask but leaves the party
mechanically blind (darkness disadvantage still applies); or place torches through
Lighting… ▸ Edit… ▸ Add Light, at a fixed 5-cell radius each.

**Still owed**: the four questions the pass exists to answer — fog alignment against the art
(now that the art draws at all), tokens on their cells, initiative and log filling, and a
reload keeping the seat.

---

## 9. Not this plan: `COMBAT_REFACTOR_PLAN.md` R4

R4 (sub-engines behind a facade) is still **IN PROGRESS** — 3 of 7 cuts and 1 of 2
mis-groupings as of 2026-09-15. Untouched by every M-phase. Its oracle is
`test_determinism.py`, which must stay byte-identical. Listed only so it is not forgotten; it
is a different document's work.

---

## 10. The lighting editor cannot set the base light level

Found by item 8's manual pass (Finding 5), and it is why that finding cost a session: a DM
who opens a map authored as `"default_light": "Darkness"` **has no way to turn the lights up
from inside the GUI**. `LightingEditor` (`gui/lighting_dialogs.py`) offers Add Light, Remove,
Light Level (which cycles the level of the *next placed source*, not the base), Done and
Cancel. `default_light` is only ever read — `open()` takes it from the caller and `Done`
hands the same value straight back to `_save_lighting_no_reload`, so whatever the file said
is what the file keeps saying. The only remedies are sprinkling 5-cell torches, editing the
JSON by hand, or deleting the file so `_load_lighting` falls through to `Clear`.

The fix is one more button next to the existing `cycle_level`, cycling `self.default_light`
through the same `light_level_choices` and relabelling itself, plus the redraw that
`_apply_light_effects` already triggers on Done. It is UI-only and behaviour-changing in the
DM's favour; it touches no multiplayer surface.

Note while there: the two lighting readers disagree on what an absent key means.
`_open_lighting_editor` (`main.py:2515`) and `_load_lighting` (`main.py:13316`) both default
`data.get("default_light", ...)` to `"BrightLight"`, but `LightingEditor.__init__` starts at
`Dark` (`lighting_dialogs.py:22`). Nothing reaches that initial value today because `open()`
is always passed one; it is a trap for whoever adds the button.

**No test covers any of this** — the editor has no suite, and the only headless rig that
could reach it is `test_gui_headless_smoke.py`. Landing the button is the moment to decide
whether that stays true.

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
played the rounds. 7 last, alone, in slices. 10 is independent of all of them and can go whenever.
