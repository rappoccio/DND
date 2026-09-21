# Multiplayer Plan

**Approach: Option B** — spectator + intent submission. The pygame app stays the
DM console *and* the authoritative server; player web clients get a per-player
view and submit coarse-grained intents.

Status: **plan written 2026-09-21**, after `COMBAT_REFACTOR_PLAN.md` R5 closed the
serialization blocker. Nothing implemented yet. Phases are M0–M8 below, gated behind
**Step 0**.

---

## Step 0 — before any code is written

**These steps run to completion, and are reviewed with the user, BEFORE the first line of
implementation.** Their outputs land in this file. Once the user agrees to them, the
results become **frozen constraints**: they do not change except by the user's explicit
agreement, recorded here with a date and a one-line reason.

This exists because the last plan of this size (`COMBAT_REFACTOR_PLAN.md`) proved the
point: its R0 phase built the determinism oracle *before* anything moved, and every phase
since has been checkable against it. Multiplayer has no equivalent oracle yet, and its
riskiest phase (M2) edits a 1,896-line method with no automated coverage at all.

| # | Step | Output | Done |
| --- | ---- | ------ | :--: |
| 0.1 | **Agree the constraint set.** Walk the Non-negotiables and the Identity/auth constraints below with the user, line by line. Amend on disagreement, then freeze. | A dated "Frozen constraints" block appended to this section | ☑ |
| 0.2 | **Inventory the prompt sites.** *(Done 2026-09-21 — see [Step 0.2 — the prompt-site inventory](#step-02--the-prompt-site-inventory-done-2026-09-21).)* Classify all 69 `ContextMenu.show` call sites: combat-turn vs DM-authoring, which close over `pending_*` state, which are reachable mid-reaction. | A table in this file, one row per site group | ☑ |
| 0.3 | **Inventory the action surface.** *(Done 2026-09-21 — see [Step 0.3 — the action-surface inventory](#step-03--the-action-surface-inventory-done-2026-09-21).)* Group the `btn_cbt_*` buttons by panel section; mark turn-action vs DM-tool; note which have availability logic that is *not* expressible without a frame of layout context. | A table in this file; the M2 work order falls out of it | ☑ |
| 0.4 | **Write the identity schema on paper.** *(Done 2026-09-21 — see [Step 0.4 — the identity schema](#step-04--the-identity-schema-frozen-2026-09-21).)* The principal record, the session-file shape, and the exact `authorize(principal, action, target)` signature — including the fields that only a future real-auth phase will populate. | A schema block in the Identity section below | ☑ |
| 0.5 | **Write the wire-format spec.** *(Done 2026-09-21 — see [Step 0.5 — the wire-format spec](#step-05--the-wire-format-spec-done-2026-09-21).)* `GameView`, the event envelope, the prompt envelope and the auth envelope, each with a `protocol_version`. No client code before this exists. | A schema block in this file | ☑ |
| 0.6 | **Build the GUI regression oracle.** The M2-analog of R0's determinism harness: a scripted scenario plus a captured baseline of the combat panel, so panel extraction can be proven **structurally identical**. *(Amended 2026-09-21, user-agreed: was "pixel-identical". `SysFont("sans", …)` (`main.py:468`) resolves through the platform font stack and the Dockerfile installs no font packages, so a pixel golden is valid in exactly one environment. Panel rects come from fixed `W`/`HW`/`TW3`/`TW5` arithmetic, never text metrics, so geometry IS cross-machine deterministic — see [Step 0.6 — the oracle's shape](#step-06--the-oracles-shape-decided-2026-09-21).)* *(Built 2026-09-21 — see [Step 0.6 — what was built](#step-06--what-was-built-done-2026-09-21).)* `tests/run_all_tests.py` did not cover the GUI at all before this — that was the gap that made M2 dangerous. | A new registered suite, green | ☑ |
| 0.7 | **Timeboxed throwaway spike.** *(Confirmed 2026-09-21: goes ahead. Step 0.2 already documented the callback shape and the six blocking modals, but the net-thread → frame-tick handoff under a real socket is the assumption every phase from M4 on rests on, and paper cannot answer it.)* On a scratch branch: wire *one* prompt (the reaction window) to a static page end to end, to validate the threading model and the blocking-modal fix. **Deleted, never merged** — its only output is findings. | Findings recorded here; branch deleted | ☐ |
| 0.8 | **Decide deployment and dependencies.** *(Done 2026-09-21 — see [Step 0.8 — deployment and dependencies](#step-08--deployment-and-dependencies-decided-2026-09-21).)* Stdlib vs `aiohttp`; which port; LAN binding; how the future public path terminates TLS. User signs off. | A decision block in this file | ☑ |
| 0.9 | **Review this whole document with the user.** Only then does M0 begin. | User's go-ahead, dated | ☐ |

Steps 0.2–0.5 are pure reading and writing — no source file changes. 0.6 adds tests only.
0.7 is the only one that writes code, and that code is thrown away.

**Standing rules once Step 0 is agreed** (these also do not change without agreement):

- No phase begins until the previous phase's tests are green and this file has been updated
  with what actually happened (the `COMBAT_REFACTOR_PLAN.md` handoff-section convention).
- No phase bundles a bug fix, a rules change or an adjacent refactor. If one is found,
  it gets written down and done separately.
- Every phase leaves `tests/run_all_tests.py` green and `test_determinism.py`
  byte-identical.

---

## Frozen constraints — agreed 2026-09-21

**Step 0.1 is complete.** The Non-negotiables and the Identity/auth constraints were walked
line by line with the user on 2026-09-21. What follows is the agreed result and is
**frozen**: it does not change except by the user's explicit agreement, recorded here with a
date and a one-line reason. Where the wording below differs from the prose later in this
document, **this block wins**.

### Vocabulary (frozen — the "token" collision)

The original draft used "token" for both the auth bearer and a creature on the map,
sometimes in one sentence. Frozen terms, used consistently from here on:

| Term | Means |
| ---- | ----- |
| **credential** | the auth bearer presented on a request |
| **token** | a creature on the map |
| **seat** | a principal's place at the table |

### Non-negotiables (final wording)

**NN1 — Nothing but the pygame thread touches the game.** The net thread never touches the
`CombatEngine`, the `BattleMap`, or `App` — *read or write*. It sees only an immutable
snapshot published by the frame tick, plus an inbound command queue the frame tick drains.
*(Tightened from "no engine call off the pygame thread": reads are equally unsafe — the GIL
protects Python objects, not C++ invariants mid-mutation, and a pybind11 accessor is a C++
call.)*

**NN2 — No rules in JavaScript.** The client renders `GameView` and posts prompt responses;
every legality question is answered server-side. The client **may** render server-computed
overlays (reachable cells, AoE footprints, legal target sets) shipped inside `GameView`; it
**may never compute one**. Overlays are a projection concern (M3), not a client concern.

**NN3 — No new subsystem lives in `main.py`.** New code goes in new modules (`gui/net/`,
`gui/prompts.py`). Changes to `main.py` are limited to call-site rewiring and deletions; its
net line count should trend down, never up. *(Reworded — the original "new code goes in new
modules" literally forbade M1's 69 call-site rewrites and M2's panel work.)*

**NN4 — The DM can always act for any token.** Connections drop; this is the normal path
with an extra button, not a fallback. Concurrent submissions (a player clicking as the DM
takes over) are resolved by the prompt bus's liveness check — the first valid submission
wins, the second is refused as no-longer-live.

**NN5 — Identity is a first-class principal**, never a display name, a seat or an IP address.

**NN6 — One authorization chokepoint.** Every read projection *and* every state-changing
submission passes through a single `authorize(principal, action, target)`. No call site does
its own check.

**NN7 — The session survives a crash.** *(Added 2026-09-21 at the user's request: a
multi-hour sim dying unrecoverably is the failure that matters most in practice.)*

- Combat state is autosaved **at every turn boundary**.
- Autosaves go to a dedicated rotating ring of **1–5 slots, configurable in
  `<base>_session.json`, default 3** — **never** over the DM's scene file, which must stay
  re-runnable.
- Each slot holds the **full sidecar set** (agents + combat + terrain + lighting + effects).
  Spells create terrain and change lighting mid-fight, so an agents-only autosave restores
  onto a clean floor.
- Every write is **atomic**: serialize to a temp file in the same directory, then
  `os.replace()`. A crash leaves the old file or the new one, never a truncated one.
- Each slot carries `{round, turn_idx, actor, timestamp}` so a slot is identifiable. With
  N ≥ 2 a known-good prior save always exists, and the ring doubles as a **rewind** feature:
  the DM can step the sim back a turn, not merely recover from a crash. The DM-facing
  restore UI is M7; the mechanism lands with the autosave.
- **The restore point is the top of a turn.** Mid-turn resume is explicitly not supported.

### Identity constraints (final wording)

**A1 — `controller` is the sole persisted source of truth for ownership.** An agent's
`controller` field stores an opaque, stable principal id (`"dm"` default); display names are
a lookup, never a key. The session roster carries **no** `seats` / ownership list on disk —
*"what does principal P control?"* is a scan over `placed_agents`, cached in memory.
*(Amended 2026-09-21: the original schema stored ownership twice, once as `controller` and
once as `seats: [4, 7]` — agent indices. `_save_agents` (`main.py:12557-12564`) drops summons
and `removed_from_play` agents and renumbers what is left, so any persisted index is
basis-dependent. That is the hazard R5 already needed `agent_basis` for, and a dual store
of the same relation is a bug class this repo has been bitten by before.)*
Consequences, all frozen:
- A `controller` naming an unknown principal **loads as DM-controlled** (harmless), rather
  than silently handing a real person the wrong creature.
- A summon **inherits its summoner's `controller`** at creation (`summoner_idx` already
  exists); summons are never persisted.

**A2 — A join code is an invite that mints a credential**, never itself an identity. **One
table-wide code is permitted**, because each join mints a *distinct principal* with its own
credential. The forbidden thing is the code *being* the identity.

**A3 — The credential is a bearer credential** with an expiry and a key id. Never a cookie.
- **HTTP routes**: `Authorization: Bearer <credential>`.
- **WebSocket**: **first-frame auth**. The browser `WebSocket` API cannot set handshake
  headers, so the socket connects unauthenticated, the client's first frame carries the
  credential, and the server sends nothing and accepts nothing else until it validates —
  dropping the socket on timeout (~5 s) or failure. Chosen over the
  `Sec-WebSocket-Protocol` smuggle (breaks behind the reverse proxy M8 adds) and over a
  query-string ticket (a second credential type with its own mint, expiry and revocation).
  *This corrects the M4 login diagram's `WS /live (Bearer)`, which is not implementable
  from a browser.*
- **Credentials are session-scoped**: they die with the process. *(User decision
  2026-09-21: "This is a per-combat sim… they will need to re-auth every time they log into
  the game.")*

**A4 — The persisted principal record carries an `auth` block with a `method` field from day
one.** v1 only ever writes `method: "join_code"`. `exp` remains a populated field even though
lifetime is session-scoped — the slot must exist before M8 needs it.

**A5 — Revocation exists even when unused.** The roster keeps a revoked list and the check
runs on every request. The **credential signing key is generated in memory at process start
and never persisted** — which is what makes A3's session-scoping automatic (no expiry
arithmetic, no key file to leak) and makes regenerating it a working panic button.

**A6 — The socket is untrusted from day one**: validate `Origin`, never derive identity from
IP or `X-Forwarded-For`, treat every field as hostile. Recorded honestly: the `Origin` check
is a **browser-only** defense — it stops a malicious page in a player's browser, and does
nothing against a non-browser client, which forges the header freely. The credential is the
authentication.

**A7 — The app never terminates TLS.** It listens plain; a reverse proxy or tunnel does TLS.

**A8 — Authorization is by principal → seat → owned tokens**, always, even with one table
and one DM. No `if viewer == "dm"` branches.

**A9 — All requests pass one middleware point**, so rate limiting, audit logging and abuse
controls can be added without touching routes.

**A10 — The DM console and the player server are separate trust domains.** *(Promoted
2026-09-21 from a note to a constraint: "let me just expose 6080 so a friend can join" is the
realistic failure.)* The noVNC DM console on 6080 is unauthenticated (`x11vnc -nopw`) and is
**never exposed beyond the host LAN**. The player port is the only externally reachable
surface, now or after M8.

### Persistence split (frozen)

| | Lifetime | Stored |
| --- | --- | --- |
| **Principal** (id, display name, `auth` block) | persists across runs | `<base>_session.json` |
| **Credential** (the bearer) | dies with the process | memory only |

Principals **must** persist, because A1 puts `controller` in the encounter save: if principal
ids were regenerated each launch, every saved encounter would load fully orphaned and M0
would do nothing. Re-login is therefore **join code + seat claim** — the returning player
picks their existing principal or creates a new one.

### v1 gameplay decisions (frozen)

- **Fog is party-scoped.** It is what `_draw_agents` already gates on, so a client provably
  cannot see more than the DM's own screen renders. Per-agent fog
  (`VisibilityService::computeVisibility`) is M7 and is a gameplay call, not a technical one.
- **Seating is automatic** on a valid join code. The plumbing is identical to DM-approval, so
  this can flip later without rework.

### The target user procedure (frozen 2026-09-21)

**This is the constraint the whole plan is built to satisfy.** If a design decision in any
phase would add a step here, the decision is wrong. Changes need a dated amendment with a
one-line reason, like every other frozen block.

**DM**
1. `./run.sh maps/yourmap.png`
2. Read the join code and URL printed at startup.
3. Give both to your players.
4. Right-click each PC token → **Controller ▸** → pick the player.

**Players**
1. Open the URL in a browser.
2. Enter the join code and your name.
3. If you've played before, pick your seat from the list.
4. Play.

**Dropped connection**
- Reload the page.

**DM restarted the app**
- Everyone redoes Players 1–3.

What this pins down, phase by phase: startup prints the join code *and* the reachable URL
(M4); controller assignment is one submenu on the existing agent right-click menu, never a
new dialog (M0); rejoin after a restart is a seat list, not a re-invite (M6); and a dropped
client recovers with a page reload and nothing else (M6). No step requires the DM to touch a
player's device, and no step requires a player to install anything.

### Accepted v1 risks

Written down explicitly so M8 has a list of what it retires, rather than leaving these buried
in constraint text.

| # | Risk | Retired by |
| - | ---- | ---------- |
| R1 | **Credentials cross the LAN in cleartext** and are sniffable by anyone on the network (A3 + A7). | M8's reverse proxy / tunnel |
| R2 | **A seat claim is not an authentication.** Anyone holding the join code can claim to be Kira. Mitigated by the DM seeing every seat and being able to reassign any of them (NN4). | M8: `auth.subject` from a real IdP becomes the match |
| R3 | **An app restart means everyone re-joins and re-claims** (credentials are session-scoped). Within-run reconnect — closed laptop, wifi drop — is unaffected and seamless. | Accepted permanently; correct for a per-combat sim |
| R4 | **Restore lands at the top of a turn**, never mid-action. Re-taking one turn is the cost. | Accepted permanently (see NN7) |

### Consequential edits this walk makes to the rest of this document

These are amendments to later sections, recorded here so they are not lost:

1. **M6b is deleted.** It proposed extending the sidecar with an `app_turn_state` block to
   cover the 72 `pending_*` flags, `action_used` / `bonus_used` and `attacks_remaining`.
   NN7 saves *at* the turn boundary, where `_clear_pending_target_picks` has already run
   (`main.py:4460`) and the action economy is reset — so the state the sidecar lacks does not
   exist at the moment of the save. The requirement shrinks M6 instead of growing it.
2. **M0's roster test changes.** `tests/test_session_roster.py` drops "index remapping when
   the encounter save compacts" (moot under A1) and gains "a `controller` referencing an
   unknown principal loads as DM-controlled".
3. **The M0 session schema drops `seats`** and renames `tokens` → `credentials` (A1, A8).
4. **The M4 route table's `WS /live (Bearer)`** becomes `WS /live (first-frame auth)` (A3).
5. **A new standalone item: make `_save_agents` / `_save_combat_state` writes atomic.** Both
   currently do `open(path, "w")` + `json.dump` (`main.py:12843`, `main.py:12897`), which
   truncates before rewriting. This is a pre-existing latent bug that NN7 makes load-bearing
   — per this document's own standing rule that no phase bundles a bug fix, it is **its own
   item and a prerequisite for NN7**, not part of M6.
6. **Unmeasured, deliberately not solved here**: per-turn autosave cost. `_save_agents` calls
   `get_agent_stats` per agent and builds a large dict each time. If it visibly hitches, the
   escape hatch is to serialize on the game thread (required by NN1) and hand the finished
   bytes to a writer thread.

---

## Step 0.2 — the prompt-site inventory (done 2026-09-21)

Pure reading; no source file was changed. Line numbers are `gui/main.py` unless noted.

### What "69 sites" actually counts

`self.context_menu.show(` appears **69 times**, and `ContextMenu` is a *single* instance
(`main.py:500`) with one `visible` flag — so exactly one prompt can be on screen at a time,
and a nested submenu (*NPC Automation ▸ Difficulty ▸*) works by re-`show()`ing over itself,
destroying the parent. `ContextMenu.handle` (`dialogs.py:3081`) dismisses first and then
calls `cb()` **synchronously inside the pygame event loop**. That is exactly the shape M1
says to preserve ("keep the local renderer synchronous (same frame) throughout M1").

**Finding — the prompt surface is 87 sites, not 69.** Seven other dialog classes prompt with
the same `(label, callback)` model and are *not* in the 69:

| Renderer | Sites | Combat-turn? | Note |
| -------- | ----: | ------------ | ---- |
| `ContextMenu` | 69 | mixed | the inventory below |
| `ElementPickerDialog` (`self._element_dialog`) | 10 | yes (8 of 10) | damage-type / curse / command-word / forcecage / ward / elemental-monk pickers |
| `SpellSelectionDialog` | 3 | 1 of 3 | 9743, 9997 combat; 19216 authoring |
| `SpellGridMenu` | 1 | **yes** | `10168` — *the in-combat spell list itself*. `_start_cast_spell` shows a `ContextMenu` for the slot choice (10069) and a `SpellGridMenu` for the spell (10168). A count of `ContextMenu` sites alone misses the single most-used combat prompt in the game. |
| `NamePromptDialog` | 1 | no | 19257 |
| `TeamPickerDialog` | 1 | no | 5307 |
| `MobSelectionDialog` | 1 | no | 2203 |
| `GridSpanDialog` | 1 | no | 14724 |
| **Total** | **87** | | |

`SpellGridMenu.show(items, …)` takes the same `(label, callback)` list, so it is a second
*renderer* of one `Prompt`, not a second mechanism — which is what M1's design already
assumes. `ElementPickerDialog` takes `(label, value)` + an `on_choose`, which is the same
thing with the callback hoisted out. **Consequence for M1: the `Prompt` → renderer mapping is
one-to-many from day one** (`ContextMenu` for ≤ ~12 options, `SpellGridMenu` for long lists,
`ElementPickerDialog` for value pickers). Budget for that in M1 Step 1 rather than
discovering it at site 40.

### The 69 `ContextMenu.show` sites, by group

`pending` = distinct `self.pending_*` flags the enclosing method reads or writes.
"Mid-reaction" = can appear while the C++ engine is parked at
`FlowStatus::AwaitingDecision`, or is itself a reaction window.

| # | Group | Sites | Where | Class | `pending_*` closed over | Mid-reaction | M1 order |
| - | ----- | ----: | ----- | ----- | ----------------------- | ------------ | -------- |
| G1 | **Engine reaction window** | 1 | `_show_pending_reaction_menu:10578` | combat-turn | none | **is** the reaction | **1st** (M1 Step 2, as planned) |
| G2 | **Post-hit riders, actor's own** | 24 | dispatched from the 24-way `elif` chain in `_finish_attack:6009-6062`; bodies at 6195–7377 | combat-turn | 4 sites only: `_offer_cleave`→`pending_cleave`, `_offer_sudden_strike`→`pending_attack_slot`, `_offer_maneuver`→`pending_sweep`, `_offer_rend_mind` (none) | no — mid *attack sequence*, engine not parked | 2nd |
| G3 | **Post-hit riders, defender / third-party** | 5 | `_offer_riposte:7418`, `_offer_protective_field:7582`, `_offer_interception:7631`, `_offer_sentinel_guard:7473`, `_offer_soul_of_vengeance:7527` | combat-turn, **owner ≠ current actor** | none | yes (they *are* reactions, Python-side) | 3rd |
| G4 | **Attack setup** | 2 | `_start_attack:5461, 5537` | combat-turn | 4 — `pending_weapon_idx`, `pending_attack_slot`, `pending_attack_offhand`, `pending_attack_resource` | no | 4th |
| G5 | **Spellcasting chain** | 6 | `_activate_spell:9842`, `_start_cast_spell:10069`, `_resolve_animate_dead:11502`, `_maybe_wild_magic_surge:11797`, `_maybe_offer_beguiling_magic:11838`, `_maybe_offer_bewitching_magic:11864` | combat-turn | **21 distinct** (49 refs) in `_activate_spell` alone: `pending_spell_*` ×6, `pending_summon_*` ×6, `pending_chromatic_*` ×3, `pending_ward_*` ×2, `pending_forcecage_sealed`, … | no | **last** |
| G6 | **Panel-button sub-menus** | 13 | `_show_legendary_action_menu:4568`, `_show_flurry_rider_menu:6869`, `_show_portent_dice_menu:7776`, `_show_arcane_ward_menu:7821`, `_show_wild_shape_menu:7903`, `_show_unarmed_menu:7981`, `_offer_bonus_maneuver:8171`, `_show_use_item_menu:8927`, `_show_companion_menu:11081`, `_show_familiar_menu:11209`, + in `_handle_events`: Bend Luck `20538`, Boon of Fate `20558`, Bastion of Law `20613` | combat-turn | 6 — `pending_rally`, `pending_feint`, `pending_weapon_idx`, `pending_use_item`, `pending_bastion_sp`, `pending_bastion_of_law` | no | 5th |
| G7 | **Map-object menus** | 4 | `_show_item_pickup_menu:4900`, `_show_item_context_menu:4934`, `_show_door_menu:5008`, `_show_ladder_menu:5032` | mixed — pickup is a turn action; door/ladder/item-context are reachable out of combat too | none | no | 6th |
| G8 | **Target-pick confirmations** | 2 | `_begin_dispel_pick:5223`, `_confirm_friendly_harm:5684` | combat-turn | none directly; both *arm* a pending pick | no | 7th |
| G9 | **Map right-click DM menus** | 7 | `_handle_events`: agent menu `19365` + nested Fiendish Resilience `19312`, NPC-automation root `19363`, difficulty `19336`, strategy `19357`; recall On-Deck reserve `19381`; fog overrides `19409` | **DM-authoring** | none | no | **never remoted** — `DM_COMMAND` |
| G10 | **Top-bar authoring menus** | 5 | `_show_agents_menu:2208`, `_show_pc_class_menu:2286`, `_show_terrain_menu:2298`, `_show_lighting_menu:2365`, `_show_dungeon_menu:2445` | **DM-authoring** | none | no | **never remoted**; these are the entry points to the six blocking modals (M4's `_pump_net` task) |
| | **Total** | **69** | | | | | |

**Split: 57 combat-turn · 12 DM-authoring** (G9 + G10). Of the 57, **6 have a non-actor
owner** (G3's five, plus G1 whenever the reactor is not the current actor) — i.e. the
`Prompt.owner` field is load-bearing from the very first conversion, not a later addition.

### Three structural facts M1 must design around

1. **The turn is genuinely blocked on the callback.** Every G2/G3 rider's `_apply` *and*
   `_skip` end in `self._continue_attack_sequence_after_rider(atk_idx)` — the attack sequence
   does not advance until the prompt is answered. That is what makes a `PromptBus` a drop-in:
   there is already exactly one resumption point per prompt. It is also why an unanswered
   prompt wedges the table, and why M5's `deadline` matters for G3 (defender reactions) even
   more than for G1.
2. **Nested menus destroy their parent.** G9's *NPC Automation ▸ Difficulty ▸* is three
   `show()` calls on one widget. A `PromptBus` needs either a prompt *stack* or an explicit
   "re-ask with a new prompt id" convention; a flat `current_prompt` slot silently loses the
   back path. Decide this in M1 Step 1 and write it into the wire format (Step 0.5).
3. **G5 is the wall.** `_activate_spell` is 193 lines closing over 21 pending flags across 49
   references. It should be converted **last**, after the bus has 63 other conversions behind
   it, and it is the single most likely place for the "callback fires in a different frame and
   reads a cleared flag" failure the plan already names.

---

## Step 0.3 — the action-surface inventory (done 2026-09-21)

Pure reading; no source file was changed. All line numbers are `gui/main.py`.
`_draw_combat_panel` spans **16541–18436** (1,896 lines, as recorded).

### Correcting the count

`grep -o 'btn_cbt_[A-Za-z0-9_]*' | sort -u` returns **114**, but one of those is the literal
prefix `"btn_cbt_"` used by the stale-rect guard's `startswith` test (16548). The real figure:

- **113 named buttons**, of which **110 are positioned/drawn inside `_draw_combat_panel`**.
- `btn_cbt_metamagic` is not a button but a **dict of 9 buttons** (`1561-1565`,
  one per `METAMAGIC_OPTIONS` entry, `dialogs.py:646`), so the panel draws up to
  **118 distinct clickable widgets**.
- **3 are dead** (see F2).

### By panel section

| # | Section | Panel lines | `btn_cbt_*` | Kind | Availability fused with layout? |
| - | ------- | ----------- | ----------: | ---- | ------------------------------- |
| 1 | Pause + End Combat | 16583–16600 | 2 — `pause_resume`, `end_combat` | **DM tool** | no — unconditional |
| 2 | Initiative list + On Deck | 16601–16671 | 0 | DM tool | n/a — uses `initiative_item_rects` and `_draw_on_deck_section`, not `Button`s |
| 3 | End Turn | 16772–16778 | 1 — `end_turn` | turn action | no — unconditional |
| 4 | Action | 16779–16899 | 10 — `nick`, `dash`, `atk_action`, `unarmed`, `dodge`, `disengage`, `hide`, `standup`, `prone`, `spell_action` | turn action | **yes** — a five-way branch (`incapacitated` / `action_used` / `frightened` / normal / prone) decides which buttons exist at all |
| 5 | Spell slots / N-per-day display | 16900–16962 | 0 | display | n/a |
| 6 | Portent dice | 16963–16984 | 1 — `use_portent` | turn action | no — one class/level guard |
| 7 | **Bonus Action (mega-section)** | 16985–18241 | **91 names / 99 widgets** | turn action | **yes** — see below |
| 8 | Movement toggles | 18242–18316 | 0 | mixed | the walk/fly toggles are not `btn_cbt_*` |
| 9 | Visibility + drops | 18317–18378 | 5 — `place_terrain` (DM), `drop_concentration`, `drop_weapon_main`, `drop_weapon_off`, `drop_weapon_rng` (turn) | mixed | no |
| 10 | Combat log | 18379–18416 | 0 | display | n/a |
| — | **never drawn** | — | 3 — `pass_action`, `pass_bonus`, `reckless` | dead | see F2 |

**Split: 3 DM-tool buttons · 107 turn-action buttons · 3 dead.**

### Section 7 broken down — this is the M2 work order

The 91 names in the Bonus Action section are not one thing. They fall into five guard shapes,
and the shapes — not the class names — are what M2 should batch by:

| Bucket | Guard shape | Count | Examples | Difficulty |
| ------ | ----------- | ----: | -------- | ---------- |
| **7a** | `if not _is_incapacitated and not self.bonus_used and <class/subclass/level/resource>` — one flat independent `if`, no interaction with any other button | ~60 | `rage 17272`, `second_wind 17722`, `war_priest 17648`, `steady_aim 17635`, `tireless 18010`, `natures_veil 18024`, `corona 17966`, `sacred_weapon 17865`, all 3 Paladin L20 capstones, all 4 Sorcerer Clockwork/Aberrant features | **easy** — each is already a pure predicate wearing an `if` |
| **7b** | economy-band header buttons, whose layout *and* label depend on `attacks_remaining` / `_attack_sequence_slot` | 2 | `atk_bonus 17001`, `spell_bonus 17011` | medium — label is state, see F3 |
| **7c** | gated on a **computed spatial fact** the panel derives inline | 6 | `_has_adjacent` loop at 17058-17067 gates `long_jump`/`shove_push`/`shove_prone` (17073-17079) and `grapple_esc 17098`; `grapple_drop 17148` scans every other agent for a grapple; `bite_grappled 17662` | medium — the computation must move into `ActionMenu`, and it is an O(n) scan done **every frame** today |
| **7d** | drawn **outside** the `bonus_used` band on purpose — availability is genuinely not a function of the bonus action | 10 | `haste_action 17196` (Haste's extra Action), the 9 `metamagic` toggles (18193-18240), `grapple_drop 17148` (free action) | medium — these are the cases that prove `ActionMenu` needs an explicit `economy` field rather than a boolean |
| **7e** | multi-button feature clusters sharing one guard + one arming flag | ~13 | Trickery duplicity trio (17402/17408/17414), Soulknife pair (18041/18051), Shadow monk trio (18064/18071/18080), Archfey trio (18099/18106/18114), Elemental monk pair (18132/18140), Channel Divinity trio (17360/17367/17374) | medium — convert as a cluster, not button by button |

**Proposed M2 order** (each step ends with a structurally identical panel on the Step 0.6 scenario
plus a green determinism run):

- **M2a** — sections 1, 3, 9 (8 buttons, zero branches). Proves the `ActionMenu.build` →
  panel-renders-from-data path end to end on the cheapest possible surface.
- **M2b** — section 6 (1) + section 4 (10). First real branch structure; small enough to
  eyeball the whole diff.
- **M2c** — bucket 7a (~60). Long but mechanical; batch ~10 at a time by class.
- **M2d** — buckets 7e, then 7c. Clusters and the spatial predicates.
- **M2e** — buckets 7b and 7d. Last, because they are the two that force the `ActionMenu`
  schema to carry action-economy as data rather than as a flag.

### Findings

These are **recorded, not fixed** — the standing rule forbids bundling a bug fix into a phase.
Each becomes its own item. None of them blocks Step 0.

- **F1 — the count.** 114 grep hits = 113 real buttons + the `"btn_cbt_"` prefix literal.
  110 drawn, 3 dead, and one of the 110 is a 9-entry dict. Update "114" wherever this document
  says it.
- **F2 — three dead buttons.** `btn_cbt_pass_action` (built `1242`, handled `19917`),
  `btn_cbt_pass_bonus` (`1301` / `20671`), `btn_cbt_reckless` (`1374` / `20145`) are
  constructed and have live `clicked()` handlers, but are never positioned during the draw
  pass — so the stale-rect guard parks them at `x = -10000` on every frame and they are
  permanently unreachable. `_reposition_panel:1211,1217` still lays two of them out, which is
  what makes this look alive. **Deleting them is the cheapest possible M2a warm-up.**
- **F3 — two buttons are invisible but clickable.** `btn_cbt_atk_action` has its rect set at
  `16839` and is drawn at `16846` only `if _cur_has_weapons`; `btn_cbt_atk_bonus` is set at
  `17008` and drawn at `17015` only `if _cur_has_offhand or mid_sequence_bonus`. In both
  cases the rect is live while the button is not rendered, so a click in that space fires the
  handler on an option the panel is deliberately not offering. This is precisely the
  legality/layout fusion M2 exists to remove; M2b deletes the failure mode by construction.
- **F4 — the stale-rect guard has a hole.** `16547-16549` iterates `vars(self).items()` and
  filters on `isinstance(_btn, Button)` — so the `btn_cbt_metamagic` **dict** is skipped and
  its 9 buttons keep their last drawn position when they stop being offered. The click handler
  (`20683`) re-checks only the Quickened/`bonus_used` case, not `metamagic_offered(...)`, so a
  metamagic toggle whose Sorcery Points have since been spent below its cost remains clickable
  at its stale location. The guard's own comment ("All `btn_cbt_*` buttons are drawn
  exclusively within this method, so this is safe") is true but insufficient.
- **F5 — the precedent already exists.** `metamagic_offered(option, learned_values,
  sp_available, sp_cost)` (`dialogs.py:659`) is a pure, documented, unit-testable availability
  predicate that the panel calls at `18219`. It is exactly the shape `ActionMenu.build`
  generalizes, and it is the only one of its kind in the panel today. **Model M2's extraction
  on it**, and cite it when the group-by-group work needs a target shape.

---

## Step 0.5 — the wire-format spec (done 2026-09-21)

Pure writing; no source file was changed. **No client code may be written before this
section exists** — that was the point of gating it. Once agreed it is frozen on the same
terms as Step 0.1: changes need a dated amendment with a one-line reason.

This spec is transport-agnostic on purpose. Step 0.8 picks the library and the port; nothing
below changes as a result of that choice.

### Ground rules

1. **Everything on the wire is a JSON object with a `v` and a `t`.** `v` is the
   `protocol_version` (an integer, `1` for everything here); `t` is the envelope type. There
   are exactly four types, defined below: `auth`, `view`, `events`, `prompt` — plus their
   client→server counterparts `auth`, `submit`, `resync`.
2. **`v` is checked on every frame, not just at connect.** A client whose `v` the server does
   not know is told so and dropped; a server envelope whose `v` the client does not know makes
   the client stop and show "reload me". Cheap now, and the only thing that makes a mid-season
   protocol change survivable.
3. **Omit, never send-and-hide.** A field a viewer may not see is *absent from the JSON*. This
   is the M3 byte-level test's whole basis. There is no `"visible": false`.
4. **Every id is an opaque string.** Prompt ids, principal ids, event ids. A client never
   parses one, never orders by one, never constructs one.
5. **Agent indices on the wire are live `BattleMap` indices** and are valid *only* within the
   `seq` that carried them. They are never persisted client-side across a resync. This is the
   same rule R5's `agent_basis` enforces for the engine snapshot, applied to the wire: the
   index basis is a property of the moment, not of the campaign.
6. **Floats are avoided.** Cells are `[col, row]` integer pairs. HP is an integer or a band
   string. Deadlines are integer milliseconds remaining, not absolute timestamps, so a client
   with a wrong clock still counts down correctly.

### Envelope 1 — `auth` (both directions)

The WS first frame (A3), and the body/response of `POST /join`. This is the only envelope a
client may send before it is authenticated.

```jsonc
// client → server, WS first frame. Nothing else is accepted, and the socket is dropped
// after ~5 s of silence or on any failure (A3).
{ "v": 1, "t": "auth", "credential": "<bearer>" }

// client → server, POST /join body. The one pre-auth HTTP route; it does not call authorize().
{ "v": 1, "t": "auth", "join_code": "…", "display_name": "Kira",
  "principal_id": "p_7f3a…" }        // OPTIONAL: re-claim an existing seat after a restart
                                     // (R3). Absent = mint a new principal.

// server → client, on success. 202 from /join; the first server frame on the WS.
{ "v": 1, "t": "auth", "ok": true,
  "credential": "<bearer>",          // /join only; the WS never re-issues one
  "principal": { "id": "p_7f3a…", "display_name": "Kira", "role": "player" },
  "seated": true,                    // false is legal and means "spectator" (zero owned tokens)
  "server_seq": 1284 }               // the EventStream cursor to open a view at

// server → client, on failure. One shape for every failure, deliberately.
{ "v": 1, "t": "auth", "ok": false, "error": "denied" }
```

**`error` is a closed set of four opaque strings: `"denied"`, `"expired"`, `"revoked"`,
`"protocol"`.** It never says *which* check failed and never echoes anything the client sent.
The reason lives in the middleware audit log (A9), exactly as Step 0.4 decided for
`authorize()`'s `bool` return. `"revoked"` and `"expired"` are distinguished from `"denied"`
only because the client's behavior differs — re-join versus stop.

`role` is on the wire so the client can pick a layout. **It is never a permission**: NN6/A8
mean every actual decision was already made server-side, and a client that lies to itself
about its own role simply gets 403s.

### Envelope 2 — `view` (server → client)

The M3 `GameView`, returned by `GET /state` and pushed on the WS after any resync. Shape as
M3 specifies, with the wire-level details pinned here:

```jsonc
{ "v": 1, "t": "view",
  "seq": 1284,                        // the EventStream cursor this view is consistent with
  "you": { "principal_id": "p_7f3a…",
           "controls": [4, 7],        // live agent indices; valid only at this seq
           "prompt_id": "pr_00291" }, // or null — the full prompt arrives in its own envelope
  "map":  { "page": "wachterhaus", "cell_px": 70, "cols": 40, "rows": 30,
            "image": "/map.png?v=<content-hash>" },
  "fog":  { "active": true, "explored": [[c, r], …] },   // from bm.explored_cells()
  "combat": { "active": true, "paused": false, "round": 3, "turn_idx": 2,
              "initiative": [ { "agent": 4, "total": 19 }, … ] },
  "agents":   [ … ],                  // see the filter table below
  "terrain":  …, "lighting": …, "effects": …,   // the existing sidecar shapes, verbatim
  "log":      [ { "seq": 1280, "text": "…" }, … ]        // tail only; the full log is /events
}
```

**`agents[]` is where the filtering lives.** Three shapes, chosen per agent per viewer. The
gate is the one `_draw_agents` / `_draw_agent_hover_name` already applies
(`main.py:15349-15352`, `16399-16402`): `_fog_active()` **and** `faction != PC_FACTION`
**and** every footprint cell unexplored ⇒ the agent is omitted. `_npc_concealed_from_party`
(hidden / unpierced-invisible automated NPCs, `main.py:2958`) omits it too.

```jsonc
// (a) owned, or the DM viewer: the full sheet
{ "idx": 4, "name": "Kira", "faction": 2, "size": 1, "cell": [12, 7],
  "hp": { "cur": 23, "max": 31, "temp": 0 }, "ac": 16,
  "conditions": ["blessed"], "resources": [ … ], "slots": [ … ],
  "sprite": "kira.png", "controller": "p_7f3a…" }

// (b) an allied PC token the viewer does not own: vitals, no sheet
{ "idx": 5, "name": "Bran", "faction": 2, "size": 1, "cell": [13, 7],
  "hp": { "cur": 9, "max": 40, "temp": 0 }, "conditions": ["frightened"],
  "sprite": "bran.png" }
//   ↑ no "ac", no "resources", no "slots", no "controller" — omitted, not nulled

// (c) a visible enemy: a band, never a number
{ "idx": 9, "name": "Ghoul", "faction": 1, "size": 1, "cell": [18, 9],
  "hp": { "band": "bloodied" }, "conditions": ["prone"], "sprite": "ghoul.png" }

// (d) an enemy in unexplored space: THE OBJECT IS NOT IN THE ARRAY AT ALL
```

`hp.band` is a closed set: `"unharmed" | "hurt" | "bloodied" | "critical" | "down"`,
cut at the same 100 / >66 / >33 / >0 / 0 boundaries the DM's own HP bar colors use
(`main.py:16677-16680`), so a player's band can never disagree with what the DM sees.

**Overlays ship inside `view`, computed server-side (NN2):** `reachable` (cells), `aoe`
(cells), `targets` (agent indices) are optional arrays under `you`. The client renders them
and may never compute one.

### Envelope 3 — `events` (server → client)

The S3 `EventStream`. Append-only, gapless, sequence-numbered. Pushed on the WS and pulled by
`GET /events?since=<seq>`.

```jsonc
{ "v": 1, "t": "events", "since": 1284, "seq": 1291,   // seq = the cursor AFTER these events
  "events": [
    { "seq": 1285, "kind": "move",     "agent": 4, "path": [[12,7],[13,7],[14,7]] },
    { "seq": 1286, "kind": "announce", "agent": 4, "target": 9,
      "text": "Kira attacks Ghoul with Longsword!" },
    { "seq": 1287, "kind": "outcome",  "agent": 9, "text": "Hit (7)", "good": true,
      "hp_after": 4, "died": false },
    { "seq": 1288, "kind": "log",      "text": "Round 4 begins." },
    { "seq": 1289, "kind": "turn",     "round": 4, "turn_idx": 0, "agent": 7 }
  ] }
```

`move` / `announce` / `outcome` are `NpcVisualEvent` (`combat_types.hpp:812`) field for field,
with `kind` spelled as a string instead of the C++ enum's `0|1|2` — an integer on the wire
would mean a client silently mis-renders if the enum ever gains a member. `log` and `turn`
are the two Python-side additions.

**Filtering applies to events exactly as it does to `view`.** An event naming an agent the
viewer may not see is **dropped, not redacted** — and, because dropping leaves a hole, `seq`
is *per-viewer*, assigned as each viewer's stream is filtered. The global stream's cursor is
never exposed. (A shared global `seq` with holes in it leaks the existence and the *rate* of
hidden activity, which is the same class of leak as sending a hidden agent with a flag.)

**`hp_after` obeys the band rule**: it is an integer for (a)/(b) agents and is replaced by
`"band"` for enemies.

**Resync contract.** A client that receives `since` ≠ its own cursor has a gap and must
`resync`; it never tries to patch. `{ "v": 1, "t": "resync" }` client→server gets a fresh
`view`. No client is ever required to be *correct*, only *current*.

### Envelope 4 — `prompt` (server → client) and `submit` (client → server)

The S2 `PromptBus` on the wire. One live prompt per viewer at a time.

```jsonc
// server → client
{ "v": 1, "t": "prompt",
  "id": "pr_00291",                   // opaque; the reply must quote it
  "parent_id": "pr_00290",            // or null — see "nested prompts" below
  "seq": 1291,                        // the view/event cursor this prompt is valid at
  "actor": 4,                         // whose turn or reaction this is
  "kind": "reaction",                 // "reaction" | "action" | "target" | "cell" | "confirm"
  "title": "Kira may react to Ghoul's attack",
  "expects": "choice",                // "choice" | "cell" | "agent" | "none"
  "options": [ { "id": "opt_0", "label": "Shield (1st-level slot)", "enabled": true },
               { "id": "opt_1", "label": "Uncanny Dodge", "enabled": false,
                 "disabled_reason": "Reaction already used" },
               { "id": "opt_2", "label": "Skip", "enabled": true } ],
  "deadline_ms": 60000 }              // or null = never expires. RELATIVE, not absolute.

// client → server
{ "v": 1, "t": "submit", "id": "pr_00291",
  "option": "opt_1",                  // expects "choice"
  "cell": [14, 9],                    // expects "cell"
  "agent": 9 }                        // expects "agent"

// server → client, the ack. Sent to the submitter; the outcome reaches everyone as events.
{ "v": 1, "t": "submit_ack", "id": "pr_00291", "ok": true }
{ "v": 1, "t": "submit_ack", "id": "pr_00291", "ok": false, "error": "not_live" }
```

`submit` `error` is a closed set: `"not_live"` (answered already, or the DM took over — NN4's
first-valid-submission-wins), `"denied"` (`authorize()` said no), `"bad_option"` (unknown or
`enabled: false`), `"protocol"`.

**`disabled_reason` is a rules string, never an authorization one** — Step 0.4 is explicit
that denial reasons belong to the audit log. A prompt the viewer is not entitled to answer is
not sent to them at all; it is never sent greyed out.

**Nested prompts.** Step 0.2 found that `ContextMenu` is one instance and a submenu destroys
its parent — so "go back" does not exist today and a flat `current_prompt` would quietly
match that. The wire models it explicitly instead: **`parent_id` carries the stack**, the
server holds the stack, and the client renders only the leaf. Answering an option whose
callback opens a submenu produces `submit_ack{ok:true}` immediately followed by a new
`prompt` with `parent_id` set to the one just answered. **Cancelling a prompt with a
`parent_id` re-sends the parent** — which makes remote play strictly better than the DM
console's current behavior, and is the one place this spec deliberately does not mirror the
local renderer. *(Recorded as the single intentional behavior difference in the whole
protocol.)*

**`deadline_ms` counts down on the client purely for display.** Expiry is decided by the
server, on the frame tick, and auto-answers Skip (M5). A client whose timer runs out sends
nothing and waits for the server's event.

### What is deliberately *not* in v1

Written down so M7/M8 have a list rather than an argument:

- **No client→server chat or free text.** Nothing on the wire carries a string a client wrote.
  That removes an entire injection and moderation surface from v1. Table talk is out of band.
- **No binary frames.** JSON text only, so the whole protocol is readable in a browser
  devtools panel — which is how M4/M5 will actually be debugged.
- **No compression, no batching beyond the natural per-frame `events` array.** If a turn's
  event burst ever matters, it is a measurement, not a guess.
- **No server→client push of another viewer's prompt.** A player never learns that another
  player is being asked something; the DM learns it from the DM console, not from this
  protocol.

---

## Step 0.6 — the oracle's shape (decided 2026-09-21)

The design the amended 0.6 row points at. Building it is the next piece of work; this
section is what it is being built to.

### Why not a pixel hash

- `self.font_sm/md/lg = pygame.font.SysFont("sans", …)` (`main.py:468-470`) resolves through
  the platform font stack. The `Dockerfile` installs **no** font package, so the container
  falls back to pygame's bundled default while native macOS matches a real sans face. The
  same panel renders different glyphs on the two run paths Step 0.8 committed to supporting.
- A committed pixel golden would therefore be valid in exactly one environment, and would
  break the day a font package is added to the image for any unrelated reason.
- A hash mismatch also fails opaquely: it says the panel changed, not *which button moved* —
  the one thing an M2 reviewer needs.

### Why structure is nonetheless deterministic

Panel geometry never consults text metrics. Every rect is derived from
`W = PANEL_W - 2*_PANEL_PAD` and its fixed subdivisions (`HW`, `TW3`, `TW5`), and the `y`
cursor advances by constants (`B`, `gap`, `section_gap`) — so **button rects are identical
across machines even when the glyphs inside them are not.** That makes a structural capture
a strictly better oracle than a pixel hash, not a weaker substitute for one.

### What the capture records

For a scripted scenario, at fixed checkpoints, one record per widget actually drawn:

```
section | widget name | label text | rect (x, y, w, h) | drawn?
```

- **Hook `Button.draw`**, do not infer from the rect. The stale-rect guard's `x = -10000`
  parking makes "not drawn" *usually* readable from geometry, but Step 0.3's **F4** found
  the `btn_cbt_metamagic` dict escapes the guard entirely — so inferring would bake the bug
  into the baseline.
- Capture the panel's `txt()` strings too. Section labels (`"Action ✓"`, `"[Bonus used]"`,
  `"Frightened — must Dash"`) are how a reader tells *which branch* of the Action section
  ran, and they are the cheapest possible check that M2 preserved the branch structure.
- Golden is a plain text file in `tests/`, alongside `test_determinism.golden.txt`. Diffs
  are readable line by line, which is the property that makes an oracle usable during a
  multi-week phase.

### The scenario

- `maps/TestGrid12x12.png` — already in the tree with `_terrain` and `_effects` sidecars, and
  a generator (`gui/gen_testmap.py`) if it ever needs regenerating.
- Fixed RNG seed via `App(map_path, seed=…)` (the `--seed` CLI path already exists).
- Checkpoints must cover the five-way Action branch (normal / `action_used` / incapacitated /
  frightened / prone) and at least one member of each Step 0.3 bucket **7a–7e**, or the
  baseline will not constrain the M2 steps that need it most.

### Known cost

No test constructs `App` today. `tests/test_feats.py:321-325` sets
`SDL_VIDEODRIVER=dummy` and imports `App` to call a **static** method — the precedent exists
for the import, not for the construction. `App.__init__` loads the monster CSV/JSON, runs
OpenCV grid analysis on the map, and calls `pygame.display.set_mode` (`main.py:902`) at a
size derived from the map image. Standing that up headlessly is the real work in 0.6, and it
is also exactly what makes every *later* GUI test cheap — which is the side benefit that
justifies the phase independently of multiplayer
(`memory/feedback_gui_not_tested.md`).

---

## Step 0.6 — what was built (done 2026-09-21)

`tests/test_combat_panel.py` + `tests/test_combat_panel.golden.txt`, registered in
`tests/run_all_tests.py` immediately after `test_snapshot.py` — the four refactor guards
sit together so a layout regression fails before the rules suites run. Suite result after
the change: **146 passed, 1 failed**, the one failure being the pre-existing
`test_monk.py` (untouched, and failing identically before this work).

### What it does

Stands `App` up headlessly (`SDL_VIDEODRIVER=dummy`, the `test_feats.py:321-325`
precedent) on `maps/TestGrid12x12.png` with `App(map_path, seed=20260921)`, scripts one
encounter, and dumps a structural capture of `_draw_combat_panel` at **14 checkpoints**:

```
text | <section> | <string>                        every string the panel renders
btn  | <section> | <name> | <label> | x,y,w,h | yes  every widget actually drawn
btn  | -         | <name> | -       | -       | no   every btn_cbt_* NOT drawn
meta | bottom=<y> max_scroll=<n>                   the layout's one-line summary
```

The undrawn roster is the half that catches a button *vanishing*; `bottom=` is the
one-line "the panel got taller" signal a reviewer reads before scanning any rect.

### The three mechanics that made it possible without touching `main.py`

Step 0.6 was scoped as "adds tests only", and it held — **no source file changed**.

1. **`Button.draw` is hooked**, not inferred, exactly as this section required.
   `widgets.Button` is a plain Python class, so the test swaps its `draw` for the
   duration of one panel draw and restores it. `btn_cbt_metamagic`'s 9 dict entries are
   indexed as `btn_cbt_metamagic[<int>]` and are captured like any other widget — the F4
   guard-escape is therefore *recorded*, not baked in.
2. **`txt()` is captured through the fonts.** `txt` is a closure inside
   `_draw_combat_panel` and cannot be reached from outside. `pygame.font.Font` is an
   immutable extension type, so `render` cannot be patched on the class either — instead
   the App's `font_sm`/`font_md`/`font_lg` are wrapped in a transparent proxy for the
   duration of the draw. A re-entrancy flag set inside the `Button.draw` hook keeps a
   button's own label from being recorded twice.
3. **Sections are derived from the headings the panel already draws** (`"Initiative
   Order"`, `"Action ✓"`, `"Bonus Action"`, `"Movement"`, `"Combat Log:"`), so the
   capture needs no hand-maintained name→section map that M2 would immediately
   invalidate. Caveat, recorded honestly: Step 0.3's sections **8 (Movement toggles) and
   9 (Visibility + drops)** share the label `Movement`, because the panel draws no
   heading between them.

### Coverage against this section's requirement

| Requirement | Checkpoint(s) |
| ----------- | ------------- |
| Action branch — normal | 01 |
| Action branch — `action_used` | 02 |
| Action branch — incapacitated | 04 |
| Action branch — frightened | 05 |
| Action branch — prone | 06 |
| **7a** flat class/resource guard (Second Wind, Action Surge) | 01, 02 |
| **7b** economy-band headers, label from `attacks_remaining` | 08 (`⚔ Attack (2)`), 08b (`⚔ Bonus (1)`) |
| **7c** spatial predicate (`_has_adjacent`) | 01 (adjacent → three-up row), 07 (+ grappled → Escape), 09/10 (not adjacent → the `else` arm) |
| **7d** drawn outside the bonus band | 11 (metamagic survives `bonus_used`; Quickened alone drops), 12 (`haste_action`) |
| **7e** multi-button cluster | 09 (Channel Divinity: Turn Undead + Radiance of the Dawn) |

Checkpoint 13 is a combatant with no class features at all — the floor of the panel,
so an M2 step that accidentally *adds* a widget to the base case shows up.

### Two deliberate design choices, for whoever maintains this

- **The checkpoints set panel state directly; they never step a turn.** The panel is a
  pure function of state, so `_goto()` sets `turn_idx` / `action_used` / `bonus_used` and
  calls `_reset_movement`. An oracle that re-ran the turn pipeline would churn every time
  the dice changed — that is `test_determinism.py`'s job, and duplicating it here would
  make the GUI golden untrustworthy exactly when the engine is being worked on. The one
  place RNG does enter is `_start_combat`'s `roll_initiative`, which is why `_goto` looks
  its actor up **by name**: new dice reorder the initiative list without invalidating a
  single checkpoint.
- **The two cwd log files are preserved.** `_start_combat` truncates `replay_log.txt` and
  `combat_log.txt` in the cwd (`gui/`, per the runner). Those are the live session's logs,
  not test artifacts, so the suite saves and restores them.

### What this bought beyond multiplayer

The `App`-headless harness is the reusable part, and it turned out to cost far less than
this section feared: the constructor needed **no** changes, and the whole suite runs in
well under a second. Any future GUI test now starts from `App(map, seed=…)` and a
`PanelCapture`.

---

## Step 0.8 — deployment and dependencies (decided 2026-09-21)

User signed off 2026-09-21. **Frozen** on the same terms as Step 0.1: changes need a dated
amendment with a one-line reason.

### D1 — Transport: `aiohttp`

One pip line in the `Dockerfile` (which today installs only `Pillow` and `pygame`), and
`pip install aiohttp` in whatever environment `python gui/main.py` is launched from. Both
run paths are in use and either may be the one a session starts from.

Chosen over stdlib-only and over `websockets`+`http.server` because **A9 requires one
middleware point**, and only a combined HTTP+WS server gives all five M4 routes a single
place to hang the `Origin` → credential → revocation → `authorize()` chain. The plan's
earlier "~60 lines" estimate for a hand-rolled WS understated masking, fragmentation,
ping/pong and the close handshake; none of that is game code, and its failure mode under
remote play is "works at the table, not for the remote player."

**`gui/net/` is imported lazily.** The DM console starts normally when `aiohttp` is absent —
the player server is simply unavailable, logged once at startup. This keeps
`python gui/main.py map.png` working untouched on a machine without the dependency, and
makes the dependency soft on both paths.

### D2 — Port: 6081, published to the LAN

- `run.sh` gains `-p 6081:6081`; the app listens plain on `0.0.0.0:6081` inside the
  container (A7 — the app never terminates TLS).
- Adjacent to 6080 so the two-trust-domain split (A10) is legible in the run script itself.
- Phones at the table reach it directly, which is what makes M4 a milestone you can see.
- Non-blocking for remote play: M8's tunnel option (Tailscale / Cloudflare) needs no inbound
  port at all and works over this binding unchanged.

### D3 — 6080 is bound to loopback

`run.sh` changes `-p 6080:6080` → `-p 127.0.0.1:6080:6080`.

`initgui.sh` runs `x11vnc -nopw`, so anyone who can reach 6080 **is** the DM, with no
password. The current binding exposes that to the whole LAN. The user DMs from a browser on
the container's own machine, so loopback costs nothing today, and it converts A10 from an
intention into a fact before remote play makes "just expose the other port too" a tempting
five-second fix.

**This is a standalone item, not part of a phase** — the standing rule forbids bundling. It
lands before M4, alongside the atomic-write fix (Consequential edit 5).

### Standalone items this document now owes, in order

Neither belongs to a phase; both are prerequisites.

| # | Item | Why it is standalone | Blocks |
| - | ---- | -------------------- | ------ |
| S1 | Atomic `_save_agents` / `_save_combat_state` writes (`main.py:12551`, `12869`) | Pre-existing latent bug that NN7 makes load-bearing | NN7, M6 |
| S2 | `run.sh` binds 6080 to `127.0.0.1` | One-line deployment fix, not a feature | M4 |

---

## The finding that shapes this plan

R5 answered *"can combat state be saved and resumed?"* — yes, and the parked-reaction
test proves it survives a suspended decision window. That was the blocker this file
originally recorded, and it is genuinely gone.

But measuring the tree for *this* plan turned up a second blocker that R5 does not
touch and that is now the real work:

> **Every choice in this game is asked by drawing pixels and waiting for a click at
> those pixels.** There is no place to stand between "the game needs a decision" and
> "a human is holding the mouse."

Concretely, from `gui/main.py` (20,951 lines, one `App` class, 627 methods):

| Surface | Size | Shape today |
| ------- | ---: | ----------- |
| `_draw_combat_panel` | 1,896 lines | immediate-mode; "is this action legal now" is fused with "where does the button get drawn" |
| `_handle_events` | 2,162 lines | one `if btn.clicked(event)` chain; **113** distinct `btn_cbt_*` buttons — 110 drawn, 3 dead, one of them a 9-entry dict (Step 0.3, F1/F2) |
| `ContextMenu.show(pos, [(label, callback)])` | 69 sites | **already** a label+callback model — the one remotable seam that exists. Step 0.2 found **18 more** prompt sites on six other dialog widgets (**87 total**), including the in-combat spell list. |
| `self.pending_*` interaction flags | 72 distinct | mid-turn "awaiting a map click" state, all Python, cleared at turn boundaries by `_clear_pending_target_picks` |

And the authority for a turn is **split three ways**:

- **C++ engine** — rules, RNG, conditions, reactions, `reaction_used` (`Agent::Conditions`).
  Snapshot-able since R5.
- **C++ `BattleMap`** — positions, HP, terrain, lighting, the fog explored mask. Saved by
  `_save_agents` / `_save_terrain` / `_save_lighting`.
- **Python `App`** — initiative loop, `action_used` / `bonus_used` (202 references),
  `attacks_remaining`, and the 72 `pending_*` flags. Only the first three of these are in
  the R5 sidecar.

That split is *fine* for Option B — the pygame process is the server, so Python state is
still server-authoritative state. It is not fine for any design where the server is a
separate process. **This plan commits to Option B for that reason, explicitly.**

---

## Foundations already in place

Four things already exist that this plan leans on hard. None need to be built.

### 1. The intent protocol — `pendingDecision` / `submitDecision`

The reaction system is already an intent bus in miniature, and it is the exact shape a
remote player needs:

```
beginMove / beginAttack / beginCast  →  FlowStatus::AwaitingDecision
    pendingDecision().ctx  →  ReactionCtx { window, reactor_idx, source_idx,
                                            options: [ReactionOption{kind, index, label, feature}], … }
    submitDecision(bm, ReactionResponse{ option, target_idx })  →  FlowStatus
```

`ReactionCtx.options` is an **engine-vetted legal choice list with human-facing labels**
(`combat_types.hpp:573`). The engine re-validates the response before applying it. It
survives snapshot/restore (`test_parked_reaction_round_trips`). A network client needs
nothing more than `label` + an index.

**This is the model for every other prompt.** M1 generalizes it Python-side rather than
inventing a second mechanism.

### 2. The broadcast wire format — `NpcVisualEvent`

`combat_types.hpp:812`, drained via `take_npc_visual_events()`:

```cpp
struct NpcVisualEvent {
    enum Kind { Move, Announce, Outcome };
    int kind; int agent_idx; int target_idx;
    std::vector<Cell> path;   // Move: the route actually taken
    std::string text;         // "X attacks Y with Z!" / "Hit (7)"
    bool good; int hp_after; bool died;
};
```

This was built to animate automated NPC turns on the DM screen. It is already a
serializable, replayable, per-turn event stream carrying exactly what a remote client must
render. M4 broadcasts it verbatim; M5 extends it to cover human turns too (today only the
NPC driver emits it).

### 3. Per-faction fog of war, in C++

`revealFogForFaction(PC_FACTION)` + `isExplored` / `exploredCells` / `setExploredCells`
(`bind_battle_map.cpp:346-368`): a persistent, monotonic explored mask, party-scoped,
already the thing `_draw_fog_overlay` and `_draw_agents` gate enemy tokens on
(`_fog_active() and pt.faction != PC_FACTION`).

Finer-grained per-*creature* vision also exists — `VisibilityService::computeVisibility` /
`getVisibility` / `canPerceiveTarget` (`visibility_service.hpp`) — but it is per-pair and
cached per turn, not a mask.

**Recommendation: party-scoped fog for v1.** It is what already works, it is what the DM
screen shows, and it matches how a table actually plays (the party shares what it sees).
Per-agent fog is M7-or-later, and is a gameplay decision, not a technical one.

### 4. A state format that is already JSON

`*_agents.json` (`agents` / `map_items` / `active_conditions`), `_terrain`, `_lighting`,
`_effects`, and R5's `<base>_combat.json` (engine snapshot + `initiative_order` / `turn_idx`
/ `round_num` / `combat_active` + an `agent_basis` guard). The view projection in M3 is a
*filtered* version of these, not a new schema.

Also worth knowing: `RecordingCombat.__getattr__` (`replay_record.py:50`) already wraps the
engine as a transparent proxy. Anything that needs to observe every engine call has a home.

### Two constraints a server implementation must respect (from R5)

- A snapshot is **engine state only**, keyed by RAW `BattleMap` agent index, and must be
  restored against the same agent list it was taken from — hence `agent_basis` and the
  refuse-on-mismatch behavior. The encounter save compacts indices (dropping summons and
  removed agents), so the two files are deliberately different artifacts.
- Host callbacks (logger, NPC render hook, decider) are **not** in a snapshot; `restore()`
  preserves the live ones. A fresh process must bind them itself before restoring.

---

## Architecture

One process. One thread touching the game.

```
   ┌─────────────────────── pygame process (authoritative) ────────────────────────┐
   │                                                                               │
   │   C++ CombatEngine + BattleMap        App (turn loop, action economy)         │
   │              ▲                                    ▲                            │
   │              │                                    │                            │
   │        ┌─────┴────────────────────────────────────┴─────┐                     │
   │        │  PromptBus   │   GameView   │   EventStream     │   ← the three seams │
   │        └─────┬────────────────┬──────────────┬───────────┘                     │
   │              │                │              │                                 │
   │      local DM UI          projection     seq'd events                          │
   │      (ContextMenu,            │              │                                 │
   │       combat panel)           │              │                                 │
   │                         ┌─────┴──────────────┴─────┐                           │
   │                         │  net thread (asyncio)    │  ← HTTP + WS only         │
   │                         │  command queue ──────────┼──► drained on frame tick  │
   └─────────────────────────┴──────────────────────────┴───────────────────────────┘
                                        │
                              browser clients (canvas; no rules in JS)
```

### The three seams

**S1 — `GameView` (read).** A pure function `build_view(app, viewer) -> dict`. Server-side
projection, per viewer, filtered by fog and ownership. Never a raw dump of `App`.

**S2 — `PromptBus` (write).** Every choice becomes a first-class object:

```python
Prompt(
    id:        str,            # opaque, monotonic; the reply must quote it
    actor_idx: int,            # whose turn/reaction this is
    owner:     str,            # "dm" | player id — who may answer
    kind:      str,            # "reaction" | "action" | "target" | "cell" | "confirm"
    title:     str,
    options:   list[Option],   # Option{id, label, enabled, disabled_reason}
    expects:   str,            # "choice" | "cell" | "agent" | "none"
    deadline:  float | None,   # reactions only; expiry auto-answers Skip
)
```

Local DM rendering and remote rendering are two *renderers of the same prompt*. Resolution
routes back through one `bus.submit(prompt_id, response)` which validates id, owner, option
id, and liveness before invoking the callback.

**S3 — `EventStream` (broadcast).** Append-only, sequence-numbered. Entries are
`NpcVisualEvent`-shaped plus combat-log lines. Clients pull `?since=<seq>`; a gap or a
reconnect triggers a full `GameView` resync. No client ever has to be *correct* — it only
has to be *current*.

### Non-negotiables

> **Frozen 2026-09-21 (Step 0.1).** The authoritative wording is
> [Frozen constraints → Non-negotiables](#non-negotiables-final-wording) in Step 0. NN1,
> NN2 and NN3 were tightened there and NN7 was added; the summaries below are for
> orientation only. **Implement from the frozen block, not from this list.**

1. **Nothing but the pygame thread touches the game** — the net thread never reads *or*
   writes the engine, the `BattleMap` or `App`. It sees a published snapshot and an
   inbound command queue. *(NN1, tightened: reads are unsafe too.)*
2. **No rules in JavaScript.** The client may *render* server-computed overlays shipped in
   `GameView`; it may never *compute* one. *(NN2, clarified.)*
3. **No new subsystem lives in `main.py`** (`gui/net/`, `gui/prompts.py` instead). Edits to
   `main.py` are call-site rewiring and deletions only. *(NN3, reworded — the original
   literally forbade M1 and M2.)*
4. **The DM can always act for any token.** Races resolve via the prompt bus's liveness
   check: first valid submission wins. *(NN4.)*
5. **Identity is a first-class principal**, never a display name, a seat or an IP address.
   *(NN5.)*
6. **One authorization chokepoint** — `authorize(principal, action, target)`, for reads as
   well as writes. *(NN6.)*
7. **The session survives a crash** — per-turn atomic autosave into a rotating slot ring.
   *(NN7, added 2026-09-21.)*

---

## Identity, authentication, and the outside-the-house constraint

**Stated requirement (user, 2026-09-21): eventually players from outside the house must be
able to join, which means real authentication. That is not being built now — but no
decision taken now may block it.**

This section is therefore written as a set of prohibitions on the early phases, not as a
design for the auth system itself. The auth system is **M8**, and it is deliberately
undesigned here beyond the seams it will need.

### What "real auth later" actually requires of us now

The migration that goes wrong is the one where identity is entangled with something that
isn't identity. Nine concrete constraints, each with the shortcut it forbids:

| # | Constraint | The shortcut it forbids |
| - | ---------- | ----------------------- |
| A1 | An agent's `controller` field stores an opaque, stable **principal id**. Display names are a lookup, never a key. | Storing `"Kira"` in the encounter file. Two Kiras, or one rename, and tokens rebind to the wrong person. |
| A2 | A join code is an **invite that mints a credential**. It is never itself an identity. | "Everyone shares one code" — cryptographically indistinguishable players, forever. |
| A3 | The credential is a **bearer token in an `Authorization` header**, with an expiry and a key id. | Session cookies (CSRF and `SameSite` grief the moment a reverse proxy is in front) and never-expiring tokens (nothing to revoke). |
| A4 | The persisted principal record carries an `auth` block with a `method` field from day one. v1 only ever writes `method: "join_code"`. | A schema with no room for `"oidc"`, forcing a save-file migration later. |
| A5 | **Revocation exists even when unused.** The roster keeps a revoked-token list and the check runs on every request. | "We'll add revocation with real auth" — which means adding a check to every route later. |
| A6 | The socket is **untrusted from day one**: validate `Origin`, never derive identity from IP or `X-Forwarded-For`, treat every field as hostile. | LAN-trust assumptions baked into the request path. |
| A7 | **The app never terminates TLS.** It listens plain on a port; a reverse proxy or tunnel does TLS. | Embedding certs in the pygame process, which pins us to one deployment shape. |
| A8 | Authorization is by **principal → seat → owned tokens**, always, even with one table and one DM. | `if viewer == "dm"` branches, which do not generalize to more than one table. |
| A9 | All requests pass one middleware point, so rate limiting, audit logging and abuse controls can be added without touching routes. | Per-route ad-hoc handling. |
### Step 0.4 — the identity schema (frozen 2026-09-21)

The paper schema Step 0.4 asks for. This is what M0 implements; nothing here may be
changed without a dated amendment. Lives in `gui/net/roster.py` (new).

#### The two records, and which one persists

```python
class Role(enum.Enum):          # a role is not an identity (A8). Read ONLY inside
    DM     = "dm"               # authorize() — no call site may branch on it.
    PLAYER = "player"           # a PLAYER owning zero tokens is a spectator.

@dataclass(frozen=True)
class AuthBlock:                # A4: the slot M8 fills, present from day one
    method:  str  = "join_code" # v1 only ever writes "join_code"; later "oidc" / "password"
    subject: str | None = None  # the IdP's subject id, when there is one

@dataclass(frozen=True)
class Principal:                # PERSISTED in <base>_session.json, survives restarts
    id:           str           # "p_7f3a…" opaque + stable; the ONLY thing agents reference
    display_name: str           # a label. Never a key, never compared, never persisted
    role:         Role          #   anywhere but here (A1)
    auth:         AuthBlock

@dataclass(frozen=True)
class Credential:               # IN MEMORY ONLY. Dies with the process (A3/A5).
    kid:          str           # key id, so a single credential can be revoked
    principal_id: str
    exp:          float         # populated even though lifetime is session-scoped (A4)
```

Principals **must** outlive the process: A1 puts `controller` in the encounter save, so
regenerating principal ids each launch would orphan every saved encounter and make M0 a
no-op. Credentials **must not**: the signing key is generated in memory at process start
and never written (A5), which is what makes A3's session-scoping free.

The persisted file shape is in [M0](#m0--ownership). The signing key appears in neither
record — it is a process-local secret, held by the roster and never serialized.

#### Ownership is derived, never stored twice

```python
def controlled_by(self, principal_id: str) -> list[int]:
    """Live agent indices this principal controls. A1: `controller` on the agent record
    is the sole persisted truth; this is a cache, rebuilt on load and on any roster or
    agent-list change. Never persisted — indices are basis-dependent."""
```

#### `authorize()` — the exact signature

```python
class Action(enum.Enum):
    # reads
    VIEW_SESSION      = "view_session"       # may connect / receive any view at all
    VIEW_TOKEN_VITALS = "view_token_vitals"  # hp numbers + conditions
    VIEW_TOKEN_SHEET  = "view_token_sheet"   # full stat block, resources, slots
    VIEW_DM_CHANNEL   = "view_dm_channel"    # private notes, enemy stat blocks, whole map
    # writes
    CONTROL_TOKEN     = "control_token"      # act as this creature
    ANSWER_PROMPT     = "answer_prompt"      # submit a response to a live prompt
    DM_COMMAND        = "dm_command"         # takeover, kick, reveal, force-advance,
                                             #   rotate join code, restore an autosave slot

Target = None | TokenTarget | PromptTarget   # TokenTarget(agent_idx: int)
                                             # PromptTarget(prompt_id: str)

def authorize(self, principal: Principal | None,
              action: Action, target: Target = None) -> bool: ...
```

A **closed enum, not strings**: a typo'd string silently denies (or, worse, silently
matches a permissive branch). `TokenTarget` carries a **live** agent index, which is safe
precisely because it is never persisted — A1 forbids persisted indices, and this never
reaches disk.

`principal=None` is the unauthenticated caller and is denied every action without
exception. `POST /join` is the one pre-auth route and does not call `authorize()`.

**Return is a plain `bool`.** Denial *reasons* belong to the middleware's audit log (A9),
not to the policy function; the user-facing "why is this greyed out" string is
`ActionMenu`'s `disabled_reason` (M2) and is a rules question, not an authorization one.

#### The policy table

| Action | Target | DM | Player |
| ------ | ------ | :-: | ------ |
| `VIEW_SESSION` | — | ✓ | ✓ if seated |
| `VIEW_TOKEN_VITALS` | token | ✓ | ✓ if owned, **or** target is `PC_FACTION` |
| `VIEW_TOKEN_SHEET` | token | ✓ | ✓ if owned |
| `VIEW_DM_CHANNEL` | — | ✓ | ✗ |
| `CONTROL_TOKEN` | token | ✓ *always* (NN4) | ✓ if owned |
| `ANSWER_PROMPT` | prompt | ✓ *always* (NN4) | ✓ if `prompt.owner == principal.id` **and** the prompt is live |
| `DM_COMMAND` | — | ✓ | ✗ |

The two *always* rows are NN4 in code: the DM can act for any token, at any time, without
a handoff step.

#### Entitlement is not visibility — keep them apart

`authorize()` answers **entitlement**: what this principal is allowed to know *if* they
could perceive the creature at all. `GameView` (M3) then applies **fog** on top. Both must
pass, and neither substitutes for the other:

- Fog is never an `authorize()` concern — it is game state, and it changes every turn.
- Ownership is never a `GameView` concern — it is policy, and NN6 says it has one home.

A player is entitled to `VIEW_TOKEN_VITALS` on any `PC_FACTION` token, but still sees
nothing of an ally standing in an unexplored cell. Smearing the two together is the most
likely way M3 leaks state, which is why M3's test is a byte-level assertion.

#### Request order (A6 → A5 → A3 → A9 → NN6)

One middleware point, in this fixed order; `authorize()` is last and assumes everything
before it has passed:

```
1. Origin check                 (A6 — browser-only defense, NOT authentication)
2. Extract credential           (A3 — Authorization header, or WS first frame)
3. Verify signature + exp       (A3/A5 — process-local key; failure = 401)
4. Revocation check by kid      (A5 — runs even while the list is empty)
5. Resolve → Principal          (A1 — by principal id; never by display name or IP)
6. authorize(principal, …)      (NN6 — the only policy decision in the request)
```

Steps 1–5 are authentication and are identical for every route. Step 6 is the only one a
route parameterizes. **M8 replaces steps 2–5 and touches nothing else** — that is the whole
point of the A-series.

### What M8 will then be able to be, without rework

Any of: an OIDC/OAuth identity provider (Google/Discord sign-in), per-user accounts with
passwords, or a signed invite link — all of which reduce to *"something else mints the
principal, and `authorize()` is unchanged."* Deployment likewise stays open: reverse proxy
with TLS, or a tunnel (Tailscale / Cloudflare Tunnel) with no inbound port at all.

### What remote play changes beyond auth

Worth recording now, because it affects M5/M6 design even though the work is later:

- **Latency stops being ~0.** The one-frame command-queue drain is still fine, but reaction
  deadlines (M5) and resync-on-gap (M6) become load-bearing rather than theoretical.
- **Disconnects become routine**, not exceptional. Non-negotiable #4 (the DM can always act
  for any token) is what makes this survivable, and it is why it is a non-negotiable.
- **Real people's names and identifiers land in logs.** Keep the session log separable from
  the combat log, and keep `<base>_session.json` out of git (`.gitignore` it in M0 — it
  will hold bearer tokens).

### Login flow (as it works against a pygame process)

`App.run()` is one thread at `clock.tick(60)`, and it owns the C++ engine. Login therefore
splits in two, and the halves must never mix:

| Half | Runs on | May touch |
| ---- | ------- | --------- |
| **Network** — accept, join-code check, token mint, WS handshake | net thread | the published roster snapshot; the command queue. Nothing else. |
| **Game** — seating a principal, claiming tokens, emitting log lines | pygame frame tick | everything |

```
browser                    net thread                  pygame frame tick
  │  POST /join            │                           │
  │  {code, name}          ├─ verify code (pure)       │
  │                        ├─ mint bearer token        │
  │                        ├─ enqueue SeatRequest ─────►│ roster.seat(principal)
  │  202 {token, pending}  │                           │ log "<name> joined"
  │◄───────────────────────┤                           │ DM panel shows the seat
  │  WS /live (1st frame)  │                           │
  ├───────────────────────►│ token → principal, via    │
  │  {seated, view}        │   the roster snapshot ◄───┤ (published once per frame)
  │◄───────────────────────┤                           │
```

Drain latency is one frame — under 17 ms, invisible to a human. Reconnect after a closed
laptop is the stored token replaying; no re-approval. A seated principal with zero owned
tokens is a legitimate state: that is a spectator.

Whether seating needs DM approval is a table preference, not an architectural one — the
plumbing is identical. **Frozen 2026-09-21: auto-seat on a valid join code in v1.**

### The blocking-modal hazard

`App.run()` is not the only event loop. Six methods run their own blocking
`while True:` + `pygame.event.get()`:

`_modal_dungeon_pages` · `_modal_text_prompt` · `_modal_message` ·
`_modal_generate_terrain` · `_modal_select_items` · `_modal_generate_dungeon`

While any of them is open, `run()` is stalled and **the command queue never drains** — a
player hitting `/join` hangs until the DM closes the dialog. All six are DM *authoring*
tools, so this cannot bite mid-combat, and the fix is one `self._pump_net()` call inside
each loop. **It is a named M4 task, not a discovery to make live.**

---

## Phases

| Phase | Scope | Risk | Est. | Ships what |
| ----- | ----- | ---- | ---- | ---------- |
| **M0** | Token ownership model | very low | 1–2 days | who controls what |
| **M1** | `PromptBus`; reroute reactions + the 69 `ContextMenu` sites | medium | 1–2 weeks | a scriptable, headless-testable DM console |
| **M2** | Legal-action model out of `_draw_combat_panel` | **high** | multi-week | a turn's options as data |
| **M3** | `GameView` projection + fog filtering | low | ~1 week | per-player state, still local |
| **M4** | Transport + spectator web client | medium | 1–2 weeks | **players watch on their own screens** |
| **M5** | Intent submission | medium | 1–2 weeks | **actual multiplayer** |
| **M6** | Reconnect / resync / restart | low | ~1 week | survives a dropped laptop |
| **M7** | Hardening, DM controls, per-agent fog | low | ongoing | table-ready |
| **M8** | **Real authentication** (see Identity section) | medium | TBD | **play from outside the house** |

M0–M7 are gated behind **Step 0** above. M8 is deliberately undesigned — its only
requirement on M0–M7 is the nine constraints A1–A9.

**Recommended v1 cut: M0 + M1 + M3 + M4.** That delivers "every player sees their own
fogged view of the board and the log, live, on their own device" without touching the
1,896-line combat panel at all. It is most of the value at a fraction of the risk. M2 + M5
then convert spectators into participants.

---

### M0 — Ownership

Multiplayer needs to know who controls which token. Today the only grouping is `faction`
(`constants.py`: `PC_FACTION = 2`) and `is_npc_automated`.

- Add `controller: str` to the agent record — an opaque **principal id** (`"dm"` default),
  per constraint A1. Never a display name. Additive field in `*_agents.json`; old saves
  load unchanged, new saves round-trip.
- A session roster in a new file, `<base>_session.json`, kept out of the encounter save
  (table metadata, not scene data) and **added to `.gitignore`**. Shape per Step 0.4's
  frozen schema — note there is **no `seats` list** (A1: `controller` on the agent record is
  the sole persisted source of truth) and **no credentials on disk** (A3/A5: credentials are
  session-scoped and the signing key is never persisted):

```jsonc
{
  "protocol_version": 1,
  "join_code": "…",                    // rotatable; an invite, not an identity (A2)
  "autosave_slots": 3,                 // NN7: 1–5, the rotating autosave ring depth
  "principals": [
    { "id": "p_7f3a…",                 // opaque, stable, the only thing agents reference
      "display_name": "Kira",          // a label; never a key (A1)
      "role": "player",                // "dm" | "player"; read ONLY inside authorize() (A8)
      "auth": { "method": "join_code", // A4: "oidc" / "password" slot in here later
                "subject": null } } ], // the IdP's subject id, when there is one
  "revoked": []                        // A5: reserved slot; the live list is in-memory,
}                                      //     since credentials die with the process
```

- `SessionRoster.authorize(principal, action, target) -> bool` lands here as the single
  chokepoint (NN6/A8). The full signature, the closed `Action` set and the policy table are
  frozen in [Step 0.4](#step-04--the-identity-schema-frozen-2026-09-21) — **implement from
  there**. Building it now is what makes M8 a swap of the *issuer* rather than an edit of
  every route.
- DM panel: assign/clear controller per agent. One new context-menu entry on the existing
  agent menu — no new dialog.

**Test**: `tests/test_session_roster.py` — save/load round-trip with `controller` present,
absent, and naming an unknown principal (**must load as DM-controlled**, per A1); a summon
inherits its summoner's `controller`; ownership survives a save that compacts indices
(the A1 amendment's whole point — `_save_agents` drops summons and `removed_from_play`
agents and renumbers, so a name-keyed `controller` must still resolve); `authorize()`
denies a principal that owns no seat; a revoked credential is refused.

**Why first**: every later phase's authorization check reads this, and it is the one piece
that cannot be retrofitted cheaply — it lands in a persisted file format, which is exactly
where constraint A4 says the future auth method must already have a slot.

---

### M1 — The `PromptBus` ⭐

The pivotal phase. Everything else is plumbing around it.

**Step 1 — build the bus** (`gui/prompts.py`, new). `Prompt` / `Option` / `PromptBus` as
above. Local renderer: `ContextMenu`, unchanged in appearance.

**Step 2 — reroute the reaction window first.** `_show_pending_reaction_menu`
(`main.py:10493`) is the ideal first customer: the engine already hands it a vetted,
labeled option list; there is exactly **one** call site; and the flow is already
snapshot-safe. Converting it changes no behavior and proves the bus end to end.

**Step 3 — reroute the 69 `ContextMenu.show` sites.** These are already
`(label, callback)` pairs — the conversion is close to mechanical:

```python
self.context_menu.show(pos, [("Longsword", cb1), ("Skip", cb2)], size)
          ↓
self.prompts.ask(actor_idx, owner, "action", title, [Option("longsword", "Longsword"), …],
                 on_answer=lambda opt: …)
```

Do it in batches by feature area, not all at once.

**Acceptance**: the app behaves *identically*, all local. New
`tests/test_prompts.py` drives a scripted combat by submitting prompt responses with **no
pygame events at all** — which is the first time this codebase can test a GUI flow, and
addresses `memory/feedback_gui_not_tested.md` as a side effect.

**Independent value even if multiplayer stops here**: a scriptable DM console, a
headless-drivable combat, and a real answer for the open TODO epic *"Headless / RL default
decider"* — the `CombatDecider` auto-policy and the prompt bus are the same abstraction
seen from the two ends (`memory/architecture_decider_flow_state.md`).

**Risk**: 69 `ContextMenu` sites plus 18 on other dialog widgets (Step 0.2), each with a callback closing over `App` state. The failure mode is a
prompt whose callback fires in a different frame than it used to and reads a `pending_*`
flag that has since been cleared. Mitigation: convert in batches, keep the local renderer
synchronous (same frame) throughout M1, and defer *any* deferred/async answering to M5.

---

### M2 — The legal-action model

The expensive phase, and the only one with real regression risk.

**Goal**: `ActionMenu.build(app, agent_idx) -> list[Action]` where
`Action{id, label, group, enabled, disabled_reason, expects}`. The panel then *draws from*
that list, and `_handle_events` dispatches by `action.id` instead of by button identity.

**Why it is hard**: in `_draw_combat_panel`, legality and layout are the same code — a
button is legal exactly when the branch that positions it runs. There is also a live
stale-rect hack at the top of the method (every `btn_cbt_*` is parked at `x = -10000`
each frame so an undrawn button cannot capture a click), which is a direct symptom of
this fusion and disappears once availability is data.

**What partially exists**: `availableAttacks(bm, idx)` and `availableCastableSpells(bm, idx)`
(`combat.hpp:1907`) already enumerate weapon/target pairs and castable spells. They cover
maybe a third of a turn's real option space — no class features, no bonus-action options,
no action-economy gating (that is Python: `action_used` / `bonus_used`).

**Strategy**: group by group, following the panel's existing visual sections. For each
group: extract availability into `ActionMenu`, make the panel render from it, verify the
drawn panel is **structurally identical** on a fixed scenario (Step 0.6's capture, not a
pixel hash — amended 2026-09-21), and run the determinism harness.
This is the same incremental-with-an-oracle discipline `COMBAT_REFACTOR_PLAN.md` used —
and it needs the same honesty: `tests/run_all_tests.py` (149 suites) does **not** cover
the GUI, so each group needs a manual smoke pass too.

**Explicitly out of scope here**: migrating `action_used` / `bonus_used` /
`attacks_remaining` into C++ (the open `memory/TODO.md` epic *"Turn-economy state → C++"*).
`ActionMenu` can read them from Python today; moving them later changes neither the model
nor the wire format. **Do not bundle it in** — that is exactly the mistake
`COMBAT_REFACTOR_PLAN.md`'s scope rule exists to prevent.

---

### M3 — `GameView`

`gui/net/view.py` (new): `build_view(app, viewer) -> dict`.

**Shape** — a filtered projection of what the saves already serialize:

```jsonc
{
  "seq": 1284,                       // EventStream cursor this view is consistent with
  "map":  {"page": "wachterhaus", "cell_px": 70, "cols": 40, "rows": 30, "image": "/map.png?v=…"},
  "fog":  {"explored": [[c,r], …]},  // party mask, from exploredCells()
  "combat": {"active": true, "round": 3, "turn_idx": 2,
             "initiative": [{"agent": 4, "total": 19}, …]},
  "agents": [ … ],                   // filtered; see below
  "terrain": …, "lighting": …, "effects": …,
  "you":  {"controls": [4, 7], "prompt": {…} | null}
}
```

**Filtering rules** — deliberately identical to what the DM screen already enforces, so a
client can never see something the DM's own render hides:

| Viewer sees | Rule |
| ----------- | ---- |
| Own tokens | full sheet: HP, slots, resources, conditions |
| Allied PC tokens | HP numbers, conditions; no private notes |
| Enemy tokens | **only if** `not _fog_active()` or the cell is explored and visible — the exact gate at `_draw_agents` / `_draw_agent_hover_name`. HP as a **band** ("Bloodied"), never a number. No stat block. |
| Unexplored cells | omitted entirely — not sent-and-hidden. A client that cheats by reading its own network traffic must learn nothing. |
| DM viewer | everything, unfiltered |

**Test**: `tests/test_gameview.py` — assert a player view of a scenario with an unexplored
enemy contains no reference to that agent anywhere in the serialized bytes. That is the
whole security model of a spectator client, and it deserves a byte-level assertion, not a
field-level one.

---

### M4 — Transport + spectator client

**Server**: one `threading.Thread` running an asyncio loop in-process.
`aiohttp` if a dependency is acceptable; otherwise stdlib `http.server` + a minimal WS
implementation. No networking exists in the tree today, so this is a clean add.

Routes:

| Route | Purpose |
| ----- | ------- |
| `GET /` | the client (static HTML/JS, served from `gui/net/static/`) |
| `POST /join` | join code → **bearer token** (A3) → principal. Never a cookie. |
| `GET /state` | full `GameView` for the authenticated principal |
| `GET /map.png` | the current page's map image (cached by content hash) |
| `WS /live` | push: `{seq, events[]}` deltas; `{prompt}` when one is addressed to you. **Authenticates by first frame, not by header** (A3) — the browser `WebSocket` API cannot set one. |

Every route goes through one middleware point (A9) that does: `Origin` check, bearer
validation, revocation check, then `authorize()`. Even in M4 — where the only answer is
"yes, you may read your view" — the checks run, so M8 changes the issuer and nothing else.

**Named task: the blocking-modal fix.** Add `self._pump_net()` to the six nested
`while True:` loops listed in the Identity section, or a join lands during
*Generate Dungeon* and hangs until the DM closes the dialog.

**Client**: canvas. Map image + grid + tokens + fog rectangles + initiative list + combat
log. Animates `NpcVisualEvent` `Move` paths the same way `_npc_anim_start` does on the DM
screen. Read-only — no input surface at all in this phase.

**Deployment**: the Docker image already runs Xvfb + x11vnc + noVNC on 6080. Add one
*separate* published port for the player server — never a second view onto 6080.

> **Security note, true today**: `initgui.sh` starts `x11vnc -nopw`, and `run.sh` publishes
> 6080. **Anyone who can reach port 6080 is the DM**, with no password. The join code
> guards the player port only and is not a defense for 6080. Nothing in this plan makes
> 6080 safe to expose, and M8 does not change that — the DM console and the player server
> are different trust domains and stay that way.

Default binding is the LAN (A6/A7): the app listens plain, and any future public exposure
is a reverse proxy or tunnel in front of it, never TLS inside the pygame process.

**Dependency note**: the image installs only `Pillow` and `pygame`. `websockify` is present
but is a proxy, not a library. Either add a pip line to the Dockerfile or implement the WS
handshake on stdlib `http.server` (~60 lines: SHA-1 + base64 of the client key, then frame
parsing). **Decided in Step 0.8, not here.**

**This is a real milestone on its own**: players stop crowding around one noVNC window.

---

### M5 — Intent submission

Now the client gets an input surface.

- When a prompt's `owner` is a remote player, push it over the WS. The client renders
  `options` as buttons (and, for `expects: "cell" | "agent"`, arms a canvas click that
  posts a cell/agent index).
- The DM console shows the *same* prompt with a "waiting on <player>" banner and a **Take
  over** button that reassigns `owner` to `dm` — the dropped-connection path.
- Reaction prompts carry a `deadline`; expiry auto-answers Skip and logs it. DM-settable,
  default generous (60s), 0 = never expire.
- Human turns must now emit `NpcVisualEvent`s too (today only `run_npc_turn` does), or
  remote clients see tokens teleport. Emit them at the same commit points the DM screen
  already animates (`_after_move_committed`, attack/spell resolution).

**Validation** — every submission is re-checked server-side against: live prompt id, owner
match, option id present and `enabled`, and the engine's own re-validation
(`submitDecision` already does this for reactions). A client is never trusted; a client is
*told what it may pick* and then still re-checked.

**Determinism**: remote input changes *when* an engine call happens, never the order or the
sequence of calls. The `RecordingCombat` log and `tests/test_determinism.py` should be
unaffected — but assert it: add a test that plays a scripted fight through the prompt bus
with simulated network latency and matches the golden byte-for-byte.

---

### M6 — Reconnect, resync, restart

- **Client reconnect, process still alive** (closed laptop, wifi drop): the credential is
  still valid, so this is a full `GameView` + resume the WS at `seq`. Free from S1/S3. This
  is the common case.
- **Server restart**: everyone re-joins and re-claims a seat, because credentials are
  session-scoped (A3) and the signing key is never persisted (A5). Principals survive in
  `<base>_session.json`, so re-claiming re-attaches a player to the tokens they already
  control. Accepted risk **R4**.
- **Restoring the fight itself**: NN7's rotating autosave ring, not a manual save. Restore
  lands at the **top of a turn** — the sidecar carries the engine snapshot and the turn
  loop, not the 72 `pending_*` flags, `action_used` / `bonus_used` or `attacks_remaining`.
  **This is no longer a limitation to work around**: NN7 saves *at* the turn boundary,
  where `_clear_pending_target_picks` has already run (`main.py:4460`) and the action
  economy is reset, so the state the sidecar lacks does not exist at the moment of the save.
  ~~M6b (an `app_turn_state` block)~~ **is deleted** — Step 0.1, 2026-09-21.
- **Prerequisite, its own item**: `_save_agents` (`main.py:12843`) and `_save_combat_state`
  (`main.py:12897`) truncate-then-rewrite. NN7 turns that from a rare narrow window into a
  100+-times-per-session one. Atomic writes land **before** NN7, as a standalone bug fix —
  this document's standing rule forbids bundling it into a phase.
- Rebind host callbacks (logger, render hook) **before** `restore()`, per R5's note.

---

### M7 — Hardening

DM controls (pause, kick, reveal a region, take over any token, force-advance the turn),
rate limiting, join-code rotation, a session log. And, if the table wants it, **per-agent
fog** via `VisibilityService::computeVisibility` / `canPerceiveTarget` — a gameplay
decision about whether the scout's vision is private, not a technical blocker.

---

### M8 — Real authentication

**Not designed here, on purpose.** Its requirement on every earlier phase is the nine
constraints A1–A9, and nothing else. When it is picked up, it should be scoped as its own
document the way `COMBAT_REFACTOR_PLAN.md` was.

What it will consist of, given those constraints hold: replacing the join-code issuer with
a real one (OIDC via an existing identity provider is the least work and the least
liability — no password storage), populating `auth.method` / `auth.subject` on the
principal record, and putting a TLS-terminating reverse proxy or a tunnel in front of the
player port. `authorize()`, the roster, the view projection, the prompt bus and every route
are unchanged.

**The check that M8 has not been blocked** should be run at the end of *each* earlier
phase, not saved up: grep for a display name used as a key, an `if viewer == "dm"` branch,
a cookie, an identity derived from an IP, or a route that skips the middleware. Any hit is
a constraint violation and gets fixed in that phase, not deferred.

---

## Rejected options

| Option | Why not |
| ------ | ------- |
| **Separate headless server process** | The turn loop, action economy and 72 interaction flags live in `App`. A separate server means porting all of it first — that is M2 plus the whole turn-economy epic before a single packet moves. Option B's whole point is that the DM console already *is* the server. |
| **Rules in the client** | Duplicates a 23k-line C++ rules engine in JS, then has to keep them agreeing. `memory/architecture_cpp_only.md` already forbids this one layer down. |
| **Lockstep / deterministic clients** | The engine is deterministic, which makes this tempting. But every client would need the C++ engine compiled to WASM plus full hidden state to stay in sync — which defeats fog of war entirely. |
| **Screen-share the noVNC session** | What we do today. No per-player view, no fog, no input. It is the baseline M4 beats. |
| **Engine calls from the network thread** | Not thread-safe; breaks RNG ordering and the replay log. Non-negotiable. |

---

## Risks

- **M2 is the god-panel.** 1,896 lines where legality and layout are the same code, with no
  automated GUI coverage (`memory/feedback_gui_not_tested.md`). It is the one phase that can
  silently break live play. Budget real time; go group by group; smoke-test each.
- **Prompt callbacks close over `App` state.** Converting 87 sites (Step 0.2) to a bus risks a callback
  firing against a `pending_*` flag that has since been cleared. Keep M1 synchronous; defer
  async answering to M5, where the turn is already gated on a specific prompt.
- **Fog leaks via the wire.** The rule is *omit*, not *send-and-hide*. Assert it at the byte
  level (M3).
- **`main.py` merge pain.** It is 1.17 MB and touched by nearly every feature. Keep new code
  in new modules; keep each phase short enough to land.
- **Scope creep into the C++ turn-economy epic.** It is adjacent, it is tempting, and it is
  not needed for any phase here. Do it separately.
- **Auth retrofit debt.** The A1–A9 constraints cost almost nothing to honor in M0–M4 and
  are expensive to retrofit — a display name used as a key reaches into a persisted save
  format, and a missing middleware point reaches into every route. The per-phase check in
  M8 exists because this is the risk most likely to be traded away under delivery pressure.
- **Trust-domain confusion.** Port 6080 is an unauthenticated DM console. The failure mode
  is someone exposing it "so a friend can join." The player port is the only thing that is
  ever externally reachable.

## Success criteria

- A player on a phone sees their own fogged view of the board, live, and can take a full
  turn without the DM touching the mouse.
- Step 0 completed and agreed before M0 began, and its outputs are in this file.
- At the end of every phase, the A1–A9 check comes back clean — real auth stays one
  issuer-swap away.
- `tests/run_all_tests.py` stays green, with `test_determinism.py` byte-identical, after
  every phase.
- A scripted combat can be played to completion through the prompt bus with zero pygame
  events (M1), and through simulated network clients (M5).
- A player view of a scenario with an unexplored enemy contains no byte referencing that
  enemy.
- The DM can take over any token at any time, and a dropped client never blocks the table.
