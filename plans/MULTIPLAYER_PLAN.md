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
| 0.2 | **Inventory the prompt sites.** *(Done 2026-09-21 — see [Step 0.2 — the prompt-site inventory](#step-02--the-prompt-site-inventory-done-2026-09-21).)* Classify all **87** prompt sites — the 69 `ContextMenu.show` calls plus 18 on seven other dialog classes — as combat-turn vs DM-authoring, which close over `pending_*` state, which are reachable mid-reaction. | A table in this file, one row per site group | ☑ |
| 0.3 | **Inventory the action surface.** *(Done 2026-09-21 — see [Step 0.3 — the action-surface inventory](#step-03--the-action-surface-inventory-done-2026-09-21).)* Group the `btn_cbt_*` buttons by panel section; mark turn-action vs DM-tool; note which have availability logic that is *not* expressible without a frame of layout context. | A table in this file; the M2 work order falls out of it | ☑ |
| 0.4 | **Write the identity schema on paper.** *(Done 2026-09-21 — see [Step 0.4 — the identity schema](#step-04--the-identity-schema-frozen-2026-09-21).)* The principal record, the session-file shape, and the exact `authorize(principal, action, target)` signature — including the fields that only a future real-auth phase will populate. | A schema block in the Identity section below | ☑ |
| 0.5 | **Write the wire-format spec.** *(Done 2026-09-21 — see [Step 0.5 — the wire-format spec](#step-05--the-wire-format-spec-done-2026-09-21).)* `GameView`, the event envelope, the prompt envelope and the auth envelope, each with a `protocol_version`. No client code before this exists. | A schema block in this file | ☑ |
| 0.6 | **Build the GUI regression oracle.** The M2-analog of R0's determinism harness: a scripted scenario plus a captured baseline of the combat panel, so panel extraction can be proven **structurally identical**. *(Amended 2026-09-21, user-agreed: was "pixel-identical". `SysFont("sans", …)` (`main.py:468`) resolves through the platform font stack and the Dockerfile installs no font packages, so a pixel golden is valid in exactly one environment. Panel rects come from fixed `W`/`HW`/`TW3`/`TW5` arithmetic, never text metrics, so geometry IS cross-machine deterministic — see [Step 0.6 — the oracle's shape](#step-06--the-oracles-shape-decided-2026-09-21).)* *(Built 2026-09-21 — see [Step 0.6 — what was built](#step-06--what-was-built-done-2026-09-21).)* `tests/run_all_tests.py` did not cover the GUI at all before this — that was the gap that made M2 dangerous. | A new registered suite, green | ☑ |
| 0.7 | **Timeboxed throwaway spike.** *(Confirmed 2026-09-21: goes ahead. Step 0.2 already documented the callback shape and the six blocking modals, but the net-thread → frame-tick handoff under a real socket is the assumption every phase from M4 on rests on, and paper cannot answer it.)* On a scratch branch: wire *one* prompt (the reaction window) to a static page end to end, to validate the threading model and the blocking-modal fix. **Deleted, never merged** — its only output is findings. *(Done 2026-09-21 — see [Step 0.7 — the spike's findings](#step-07--the-spikes-findings-done-2026-09-21). 22 checks green; branch deleted. F1's one ask — a `"timeout"` member for the `submit` error set — was agreed and amended into Step 0.5 the same day.)* | Findings recorded here; branch deleted | ☑ |
| 0.8 | **Decide deployment and dependencies.** *(Done 2026-09-21 — see [Step 0.8 — deployment and dependencies](#step-08--deployment-and-dependencies-decided-2026-09-21).)* Stdlib vs `aiohttp`; which port; LAN binding; how the future public path terminates TLS. User signs off. | A decision block in this file | ☑ |
| 0.9 | **Review this whole document with the user.** Only then does M0 begin. *(Step 0.7's F1 is already settled — `"timeout"` was added to Step 0.5 by agreement on 2026-09-21.)* | User's go-ahead, dated | ☑ |

Steps 0.2–0.5 are pure reading and writing — no source file changes. 0.6 adds tests only.
0.7 was the only one that wrote code, and that code was thrown away (branch deleted 2026-09-21).
**Step 0 is closed.**

**0.9 — the go-ahead, 2026-09-21.** The user reviewed the status against the git history
(0.6's oracle in `899a4db`, 0.7's findings in `5c37e8e`, the count correction in `9fa1b84`,
the spike branch confirmed gone) and said go for M0. The frozen blocks above are unchanged
by this review — no amendment was needed. Implementation of M0 began the same day.

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
modules" literally forbade M1's 87 call-site rewrites and M2's panel work.)* *(Count
corrected 2026-09-21 from 69 to 87 — editorial only, no change to the constraint: 69 was
the `ContextMenu` sub-count, and Step 0.2's own finding puts the prompt surface at 87.)*

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
5. **A new standalone item: make `_save_agents` / `_save_combat_state` writes atomic.**
   *(Done 2026-09-22 as S1.)* Both did `open(path, "w")` + `json.dump`, which
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

> ### Re-derived against `395e020`, 2026-09-21 — the count did NOT move
>
> M1 Step 3 closed by warning that this inventory is a snapshot and M2 should re-derive it
> rather than trust it, because Step 0.2's prompt count had gone stale exactly that way
> (G9 7→8, others 18→19, both from M0). **It was re-derived, and every figure below still
> holds**: 114 grep hits, **113** real names, **110** appearing inside the draw pass, the
> **same three** dead ones (`pass_action`, `pass_bonus`, `reckless`), `METAMAGIC_OPTIONS`
> still 9, so **118** clickable widgets. `_draw_combat_panel` is still **1,896 lines**.
>
> **Why this one held and 0.2's did not**: M0 and M1 added *prompts* — a Controller ▸
> submenu, a seat-a-player dialog — and touched no panel button. The prompt surface and
> the action surface turn out to be independent under change, which is a small piece of
> evidence for the seam split S2/S3 rather than a coincidence worth relying on. **Re-derive
> again after M2a** — that one deletes buttons.
>
> ### Re-derived again after M2a, 2026-09-21 — the count DID move, as predicted
>
> **110 named buttons** (was 113; F2's three are gone), **118 clickable widgets**
> (unchanged — the three deleted were never drawn, so they were never in that figure),
> `METAMAGIC_OPTIONS` still 9, `_draw_combat_panel` now **1,875 lines** (was 1,896).
> Section 10's "never drawn" row is now empty.
>
> **The grep no longer finds everything.** Seven names — `pause_resume`, `end_combat`,
> `end_turn`, `drop_concentration`, and the three `drop_weapon_*` — are positioned
> through `_cbt_btn(action_id)`, i.e. `getattr(self, "btn_cbt_" + …)`, so
> `grep -n 'btn_cbt_<name>'` finds their *constructor* and nothing in the draw pass.
> That is what conversion looks like from the outside, and every later M2 step widens
> it. **Navigate a converted button by its action id in `gui/actions.py`**; the grep
> stays correct only for the 103 not yet converted.
>
> **The line numbers below are all off by a uniform +142** (the method head moved
> `16541 → 16683`, the tail `18436 → 18578`; spot-checked at fifteen cited lines, every one
> landing on what this section says is there). They are *not* rewritten here, because M2a's
> first act invalidates them again. Navigate by name:
> `grep -n 'btn_cbt_<name>' gui/main.py`.
>
> ### Re-derived again after M2b, 2026-09-22 — only the panel's size moved
>
> **110 named buttons** (M2b deleted none), **118 clickable widgets**, `METAMAGIC_OPTIONS`
> still 9. `_draw_combat_panel` is now **1,781 lines** (1,896 → 1,875 → 1,781).
>
> **Eighteen names have now left the draw pass** — M2a's seven plus M2b's eleven
> (`atk_action`, `unarmed`, `dash`, `dodge`, `disengage`, `hide`, `standup`, `prone`,
> `spell_action`, `nick`, `use_portent`). The grep stays correct for the **92** still
> fused; for the other 18, navigate by action id in `gui/actions.py`. Sections 4 and 6
> below are now history, not a map of the code: what they describe lives in
> `ActionMenu._action` / `._portent`.

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
| **7b** | economy-band header buttons, whose layout *and* label depend on `attacks_remaining` / `_attack_sequence_slot` | 2 | `atk_bonus 17001`, `spell_bonus 17011` | medium — label is state, see F3. **M2e ☑** |
| **7c** | gated on a **computed spatial fact** the panel derives inline | 6 | `_has_adjacent` loop at 17058-17067 gates `long_jump`/`shove_push`/`shove_prone` (17073-17079) and `grapple_esc 17098`; `grapple_drop 17148` scans every other agent for a grapple; `bite_grappled 17662` | medium — the computation must move into `ActionMenu`, and it is an O(n) scan done **every frame** today |
| **7d** | drawn **outside** the `bonus_used` band on purpose — availability is genuinely not a function of the bonus action | 10 | `haste_action 17196` (Haste's extra Action), the 9 `metamagic` toggles (18193-18240), `grapple_drop 17148` (free action) | medium — these are the cases that prove `ActionMenu` needs an explicit `economy` field rather than a boolean. **M2e ☑ — it does** |
| **7e** | multi-button feature clusters sharing one guard + one arming flag | ~13 | Trickery duplicity trio (17402/17408/17414), Soulknife pair (18041/18051), Shadow monk trio (18064/18071/18080), Archfey trio (18099/18106/18114), Elemental monk pair (18132/18140), Channel Divinity trio (17360/17367/17374) | medium — convert as a cluster, not button by button |

**Proposed M2 order** (each step ends with a structurally identical panel on the Step 0.6 scenario
plus a green determinism run):

- **M2a** ☑ (done 2026-09-21) — sections 1, 3, 9 (8 buttons). Proves the
  `ActionMenu.build` → panel-renders-from-data path end to end on the cheapest possible
  surface. See [M2a — what was built](#m2a--what-was-built-done-2026-09-21). *("zero
  branches" was wrong, and usefully so: §9 has three — concentration, the droppable-slot
  filter, and the n-up row width that follows from it. They are the reason M2a has an
  oracle diff to talk about at all.)*
- **M2b** ☑ (done 2026-09-22) — section 6 (1) + section 4 (10). First real branch
  structure. See [M2b — what was built](#m2b--what-was-built-done-2026-09-22).
  *(The handoff's claim that "checkpoints 01/02/04/05/06 already cover all five arms,
  so the oracle needs no extending" was half right and had to be checked: the five ARMS
  were covered, but neither guard M2b actually moves — Nick's and Portent's — was ever
  satisfied by the scene, so both buttons read `no` in all 17 blocks. Checkpoints 17/18
  were added first, against the old fused code.)*
- **M2c** ☑ (done 2026-09-22) — bucket 7a, **56 buttons converted**, by the boundary below. Long but
  mechanical; batched by class, because one creature shows a whole class's band at once.
  See [M2c — bucket 7a](#m2c--bucket-7a-done-2026-09-22).
- **M2d** ☑ (done 2026-09-22) — buckets 7e and 7c, **31 buttons converted**: the six
  named clusters, the Cunning Action row, the four Glamour Bard buttons nested inside
  `grant_inspiration`'s resource test, the seven spatial predicates, and `telekinetic`
  under two ids. See [M2d — the clusters and the spatial predicates](#m2d--the-clusters-and-the-spatial-predicates-done-2026-09-22).
- **M2e** ☑ (done 2026-09-22) — buckets 7b and 7d, **12 buttons converted**: the two
  economy-band headers, Haste's extra Action, and the nine Metamagic toggles that were
  a dict. Last, because they are the two that force the `ActionMenu` schema to carry
  action-economy as data rather than as a flag — and it does now. **§7 is complete and
  every one of the 110 named buttons has left the draw pass**, which is what let the
  stale-rect guard go. See [M2e — the economy, as data](#m2e--the-economy-as-data-done-2026-09-22).

### Findings

These are **recorded, not fixed** — the standing rule forbids bundling a bug fix into a phase.
Each becomes its own item. None of them blocks Step 0.

- **F1 — the count.** 114 grep hits = 113 real buttons + the `"btn_cbt_"` prefix literal.
  110 drawn, 3 dead, and one of the 110 is a 9-entry dict. Update "114" wherever this document
  says it.
- **F2 — three dead buttons. CLOSED by M2a, 2026-09-21.** All three deleted
  (constructor, `_reposition_panel` line where present, and click handler); the panel
  oracle's only diff was the same three names leaving the undrawn roster at all 14
  checkpoints, which is the proof they were dead. Reckless Attack itself is untouched —
  it is reached from the attack menu (`_activate_reckless_and_attack`) and from the
  post-hoc `_offer_reckless_reroll`, and the deleted handler was a second, unreachable
  emitter of the same `log_event("reckless")`. Original finding:
  `btn_cbt_pass_action` (built `1242`, handled `19917`),
  `btn_cbt_pass_bonus` (`1301` / `20671`), `btn_cbt_reckless` (`1374` / `20145`) are
  constructed and have live `clicked()` handlers, but are never positioned during the draw
  pass — so the stale-rect guard parks them at `x = -10000` on every frame and they are
  permanently unreachable. `_reposition_panel:1211,1217` still lays two of them out, which is
  what makes this look alive. **Deleting them is the cheapest possible M2a warm-up.**
- **F3 — two buttons are invisible but clickable. CLOSED by M2e, 2026-09-22**
  (half by M2b before it).
  `btn_cbt_atk_action` (rect at `16839`, drawn at `16846` only `if _cur_has_weapons`) is
  gone: an action the ActionMenu does not build has no rect set at all. **That half was
  also vacuous** — `_cur_has_weapons` is `len(get_agent_weapons(...)) > 0`, and
  `PlacedAgent.weapons` defaults to a 3-vector (`battle_map.hpp:302`) that
  `setAgentWeapons` re-pads to ≥3, so no creature could ever fail it. The predicate is
  kept in `ActionMenu._action` as a statement of the rule, not as a live branch.
  **`btn_cbt_atk_bonus` (set `17008`, drawn `17015` only `if _cur_has_offhand or
  mid_sequence_bonus`) was real, and M2e closed it** the same way: the rect is set by
  `_draw_action_row`-style layout on the frame the option is drawn, and an id the menu
  does not build is never laid out. Its predicates — `_cur_has_offhand`, `_cur_can_spell`,
  `_cur_has_spells` and the handler's `_has_offhand` — are deleted.
  **M2e found the same shape a third time, and recorded it as F14.**
  Original finding: in both cases the rect is live while the button is not rendered, so a
  click in that space fires the handler on an option the panel is deliberately not
  offering. This is precisely the legality/layout fusion M2 exists to remove.
- **F4 — the stale-rect guard has a hole. CLOSED by M2e, 2026-09-22**, in two
  commits: bucket 7d replaced the dict with nine named widgets dispatched by id, and the
  commit after it deleted the guard itself — not by fixing the hole but by removing the
  need for the guard. Every `btn_cbt_*` is now laid out from the menu on the frame it is
  drawn and dispatched through `_action_clicked`, which tests the click against the offer
  the panel drew; a stale rect can exist and nothing can fire through it.
  `_reposition_panel`'s thirteen-line combat block went with it. Original finding:
  `16547-16549` iterates `vars(self).items()` and
  filters on `isinstance(_btn, Button)` — so the `btn_cbt_metamagic` **dict** is skipped and
  its 9 buttons keep their last drawn position when they stop being offered. The click handler
  (`20683`) re-checks only the Quickened/`bonus_used` case, not `metamagic_offered(...)`, so a
  metamagic toggle whose Sorcery Points have since been spent below its cost remains clickable
  at its stale location. The guard's own comment ("All `btn_cbt_*` buttons are drawn
  exclusively within this method, so this is safe") is true but insufficient.
- **F7 — with nobody on turn, §4 drew six buttons for a creature that does not exist.
  CLOSED by M2b, 2026-09-22** (and it is a behaviour change, recorded as such). See
  [M2b — what was built](#m2b--what-was-built-done-2026-09-22). Short form: with
  `combat_active` but `_current_agent_idx()` out of range, the fused code fell through to
  the open-band arm and drew Unarmed + the whole five-up posture row, because the arm's
  only per-creature guard was `_cur_has_weapons` and the five-up row had none. Checkpoint
  19 pins the corrected behaviour; the old one was captured side by side before the change
  was accepted.
- **F8 — the panel crashed for a Draconic Sorcerer. FIXED 2026-09-22, as its own commit.**
  `main.py:17546` read a bare `bonus_used` where every other guard in the method reads
  `self.bonus_used`, so the Draconic L6 Elemental Affinity guard raised `NameError` out
  of `_draw_combat_panel` — not a mis-drawn button, the whole panel down — for any
  Draconic Sorcerer at L6+ who had chosen an affinity element (`dialogs.py:2208`, an
  ordinary character-creation choice) and was not already resisting. Python's
  left-to-right `and` is why it hid: `not bonus_used` is the last conjunct, so the name
  is only looked up once the four class/level/element/duration tests have all passed.
  `btn_cbt_draconic_resistance` had therefore never been drawn by anything, and could
  not be checkpointed against code that raises — which is what surfaced it, and why the
  fix is the one thing M2c did before its oracle work. **Checkpoint 19** pins the state;
  breaking the fix again fails it with the original `NameError`. This is a behaviour
  change (a raise became a button) and, like F7, is recorded as one. It is the only
  unqualified *bug* the M2 sweep has turned up so far; F2/F3/F4 were all latent.

- **F9 — Intimidating Presence is gated at two different levels.** The panel offers
  `btn_cbt_intimidating_presence` at `barbarian_subclass == Berserker and char_level >=
  10`, but `class_resources.cpp:74` only grants the "Intimidating Presence" resource at
  **14** (which is right for the 2024 PHB; L10 Berserker is Retaliation). The resource
  test that follows therefore dominates, and levels 10–13 are a branch that can never
  reach the draw. No behaviour change — the button is correctly hidden — but the panel
  states a rule it does not implement, and checkpoint 25 has to use a level-14 Berserker
  to see the button at all. Fix the panel's `10` to `14` as its own item.
- **F10 — one widget, two draw sites. FIXED 2026-09-22, as its own commit (M2e).**
  `btn_cbt_telekinetic_feat` and `btn_cbt_telekinetic_psi`, two labels — the feat's
  "🌀 Telekinetic Shove" is drawn for the first time — and two handlers dispatched by
  `_action_clicked` on the two ids M2d put in the menu. `App._CBT_BTN_ALIAS` is deleted:
  one id, one widget, no exceptions. `test_telekinetic_is_two_ids_behind_one_widget`
  became `test_the_two_telekinetic_options_are_two_widgets`, which clicks each and
  asserts the other did not arm. Checkpoint 63, written against the fused code so this
  fix would have a before, is the record of the change. Original finding:
  `btn_cbt_telekinetic` is positioned and drawn
  twice in the same pass under two unrelated guards: the **Telekinetic feat** (30 ft
  shove, `17211`) and **Psi Warrior**'s Telekinetic Movement (`18077`). A Psi Warrior who
  has taken the feat satisfies both, so the widget is painted at the upper position and
  then moved and painted again at the lower one — the upper is a ghost with no rect
  behind it, and the single click handler cannot tell which of the two the player meant.
  This is F3's shape with the halves swapped (drawn but not clickable, rather than
  clickable but not drawn). **It is why `telekinetic` is not in M2c's scope**: an
  `Action` id is a dispatch key and there is one widget for two options, so splitting it
  needs a decision the phase should not make in passing. Checkpoints 38 and 47 cover the
  two sites separately; **checkpoint 63 (M2d) covers the state where BOTH fire**, and
  the golden now records the widget painted twice in one pass — `1052,460` and again at
  `1052,562`.

  **M2d found two more halves of the same fault, and neither is fixed:**
  · the feat's own constructor is **dead**. `main.py:1372` builds
  `btn_cbt_telekinetic` as "🌀 Telekinetic Shove" and `main.py:1535` **rebinds the same
  attribute** to "Telekinetic Movement"; the first label has therefore never been drawn
  by anything, at either site. That is why both of M2d's ids carry the Psi Warrior's
  label — anything else would have been a behaviour change.
  · the two click handlers **cross-fire**. `19442` (`_start_telekinetic_shove`) and
  `19809` (`pending_telekinetic = True`) sit in the same `if not self.bonus_used:`
  block, one after the other, and **neither is gated on the feat or on the subclass** —
  so one click on the one widget arms both, whoever the creature is, and the elif chain
  at `19025` decides which of the two the next map click resolves. This is the half that
  makes F10 a bug rather than a cosmetic ghost.

  **M2d converted the DRAW only** (decision, 2026-09-22): the menu carries
  `telekinetic_feat` and `telekinetic_psi` — `_action_menu` is keyed by id, so one
  option cannot appear twice — and `App._CBT_BTN_ALIAS` points both at the one widget.
  The handlers were deliberately **left on raw `.clicked()`**, because moving them to
  `_action_clicked` would gate each on its own id and thereby *fix* the cross-firing,
  which is a behaviour change and belongs to F10's own item, not to a conversion.
  `test_telekinetic_is_two_ids_behind_one_widget` fails the moment the widget is split,
  which is the reminder to come back here.

- **F11 — Step of the Wind's Fleet Step arm is unreachable.** The guard at `17319`
  offers `btn_cbt_step_of_wind` when `normal_ready or fleet_step_ready`, and
  `fleet_step_ready` is explicitly "Open Hand L11, no Focus, **bonus action already
  spent**". It is written inside the band block, which has already required
  `not self.bonus_used`, so the arm can never fire: the comment above it describes a
  feature the panel does not offer. `ActionMenu._bonus` reproduces it in that shape and
  `test_the_fleet_step_arm_of_step_of_the_wind_is_unreachable` pins it, because making
  it live is a behaviour change and belongs to its own item, not to a conversion.

- **F12 — §4's five-up posture row is too narrow for its labels.** *(Found by the
  manual smoke pass, 2026-09-22 — the first thing it has turned up.)* The row gives each
  button `TW5 = 60px`, and at `font_sm` "Disengage" renders wider than that: the final
  glyph is clipped and the text bleeds across the 4px gap into Dodge and Hide. "Go Prone"
  fills its button edge to edge with no padding. **Not an M2 regression** — the rects are
  `1052,300,60,30` etc. in the golden both before M2a and after M2c, so the geometry has
  never moved; M2b only changed who computes it. It is a straightforward cosmetic bug
  (shorten the labels, or let the row size itself to its widest), and it is exactly the
  class of thing a structural golden cannot see: every checkpoint agrees the rect is
  right, because the rect *is* right. Its own item. **Now pinned by name** in
  `tests/test_gui_headless_smoke.py`'s `_KNOWN_TOO_WIDE`, which fails both if a new
  overflow appears and if one of these three is fixed without being removed from the
  set. Measured: `Disengage` needs 76px of a 60px button, `Go Prone` 65, `Stand Up` 64.

- **F13 — §7 draws a Jump button for a creature that does not exist. FIXED
  2026-09-22, as its own commit (M2e)** — the same answer M2b gave F7 one section up.
  `ActionMenu._bonus` returns nothing for an index it cannot read, and checkpoint 99,
  which had recorded the defect since it was written, records the fix. *(Found by
  M2d, 2026-09-22.)* F7's shape, one section down. With `combat_active` and
  `_current_agent_idx()` out of range, `_is_incapacitated` is `False` (there are no
  conditions to read) and `bonus_used` falls back to `_bonus_used_fallback`, so the
  Bonus Action band is **open** — and the Jump/Shove row's only per-creature test is the
  adjacency scan, which decides the row's WIDTH and not whether it exists. Checkpoint 99
  has recorded the lone full-width `Jump` at `1052,228` since it was written; nobody had
  read it as a defect. **Preserved, not fixed**: `ActionMenu._bonus` returns exactly
  that one action for an out-of-range index, with the finding written above it, and
  `test_out_of_range_agent_yields_only_the_creature_free_groups` pins it. M2b *did*
  change the same shape in §4 (F7) — deliberately, and as a recorded behaviour change;
  doing it here would have been a second one bundled into a conversion.

- **F14 — `⚔ Bonus (n)` is drawn and does nothing.** *(Found by M2e, 2026-09-22.)*
  F3's shape a third time, and the last of it. The two economy-band headers are offered
  while an Extra Attack sequence is parked in the bonus slot — `bonus_used` is already
  True and the sequence still owes swings — but both click handlers sit inside the
  `if not self.bonus_used:` block they have always been in, so the button that says how
  many swings are left cannot be clicked. Checkpoints 08b and 65 draw it. **Preserved,
  not fixed**: moving the two handlers out of that block would make a dead button live,
  which is a behaviour change and belongs to its own item. It may well be harmless in
  play — the swings are driven by map clicks through `pending_attack_slot`, not by
  re-pressing the header — which is exactly the kind of thing that should be decided
  deliberately rather than by an extraction.

- **F5 — the precedent already exists.** `metamagic_offered(option, learned_values,
  sp_available, sp_cost)` (`dialogs.py:659`) is a pure, documented, unit-testable availability
  predicate that the panel calls at `18219`. It is exactly the shape `ActionMenu.build`
  generalizes, and it is the only one of its kind in the panel today. **Model M2's extraction
  on it**, and cite it when the group-by-group work needs a target shape. *(M2e moved it,
  and `METAMAGIC_OPTIONS` with it, into `actions.py` — §7 needs both and that module may
  not import pygame. `dialogs.py` re-exports them, so the selection dialog and
  `test_sorcerer.py` are unchanged. The precedent is now an ordinary member of the module
  it was the precedent for.)*

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
  "fog":  { "active": true,
            "explored_runs": [[row, c0, c1], …] },  // inclusive spans; D-M4-2 amended 2026-09-23
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
`enabled: false`), `"protocol"`, `"timeout"`.

> **Amended 2026-09-21, user-agreed: `"timeout"` added** (the set was four members).
> **Reason:** Step 0.7's F1 proved the ack is not decidable on the net thread — liveness is
> game state — so the handler parks on a future the frame tick resolves, and needs a
> server-side deadline for the case where the frame loop never comes back.

`"timeout"` is the only member the **server** raises without the game thread having ruled:
it means the submit was queued and never drained. It is therefore the one error whose
outcome is genuinely unknown to the client — the prompt may still be live. A client that
receives it re-reads `/state` (or waits for the next `live` frame) rather than assuming
either result, and **never auto-resubmits**: NN4's first-valid-submission-wins makes a
blind retry a second valid submission.

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

> **Upheld 2026-09-21 (D-M1-12).** M1 Step 3 left nine sites on their widgets and asked
> whether `expects` should grow `"text"` and `"number"` for them. It does not: the
> no-free-text clause above is the answer, and every site that wanted text or a number
> turned out to be DM authoring. `expects` remains the frozen four — `choice` / `cell` /
> `agent` / `none` — through M2, M3 and M4. A closed multi-select (`"choices"`, a list of
> option *ids*, no client-authored strings) has exactly one caller and is M5's call.

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

## Step 0.7 — the spike's findings (done 2026-09-21)

**The branch is gone.** `spike/0.7-reaction-window` was built, run, recorded here, and
deleted. Nothing below survives as code; the numbers are what it cost to learn.

### What was actually wired

`gui/net/spike.py` (an `aiohttp` `AppRunner` on its own thread, `GET /` · `GET /state` ·
`POST /submit` · `WS /live`), a 30-line static page, and **five** touch points in
`main.py`: a lazy import in `__init__`, `_pump_net()` at the top of `run()`'s loop, a
publish after the one `context_menu.show` in `_show_pending_reaction_menu`, a clear at
the top of `_submit_reaction`, and `_pump_net()` inside `_modal_message`'s `while True:`.

The driver stands `App` up headlessly (Step 0.6's scaffolding, reused), parks the C++
engine on a **real** `LeftReach` OA window via `begin_move`, and answers it from another
thread over a **real** socket with a stdlib HTTP client — deliberately not `aiohttp`'s,
so the exercised path is the browser's. 22 checks, all green.

### F1 — the ack cannot be produced by the net thread *(the finding)*

`submit_ack{ok}` is a function of **liveness**, and liveness is game state. NN1 forbids
the HTTP handler from reading it. So the handler cannot answer its own request: it must
park on an `asyncio.Future` that the frame tick resolves through
`loop.call_soon_threadsafe`. Measured: with the game thread not ticking, the POST sat
**0.76 s** in flight and returned on the first `_pump_net()`.

This is not a detail of the spike — it is the shape of every `submit` in M5. Two
consequences the plan does not currently carry:

1. **The handler needs a server-side timeout.** The spike used 5 s → `{"ok": false,
   "error": "timeout"}`. **Step 0.5 declares `submit` `error` a closed set of four**
   (`not_live`, `denied`, `bad_option`, `protocol`) and had no member for "the game
   thread never came back." **Resolved 2026-09-21: the user agreed a fifth member,
   `"timeout"`**, and Step 0.5 carries the dated amendment.
2. A wedged frame loop is now visible to clients as a hung POST rather than a silent
   stall. That is strictly better than the alternative and worth keeping.

### F2 — the frame tick is the only scheduler that matters

Submit latency is exactly "time to the next `_pump_net()`" — ≤16 ms at 60 fps, and
**unbounded whenever `run()` is not looping**. E2 confirmed the queue genuinely does not
drain otherwise; the 0.75 s stall was the mechanism, not an artifact of the test.

### F3 — the blocking-modal fix works, and it is one line — but it changes what a modal *is*

A submit posted while `_modal_message` owned the event loop was drained, acked `ok`, and
resumed the parked engine flow **from inside the modal**. The plan's named M4 task is
confirmed and holds no surprises.

What the spike also shows, and the plan does not yet say: pumping inside a modal means
**a DM authoring modal is no longer a quiescent point**. Game state can now advance while
*Generate Dungeon* is open. For reactions that is exactly what you want, but
`_submit_reaction` drags `_flush_combat_log` / `_update_attack_overlay` /
`_sync_spell_effect_cache` along with it, and those ran here only headlessly, while the
modal owned the screen. **M4 should pump the command queue and nothing that redraws** —
and this is worth one deliberate look on a real display before M4 calls it done.

### F4 — the `Prompt` the bus holds is not the object on the wire

The prompt carries Python callables — that is how `ContextMenu` works, and the spike
reuses **the same callbacks the local click would have fired** (that is what makes the
remote path a second renderer rather than a parallel implementation). The published dict
therefore has to be a projection with `callbacks` stripped. One line here; a load-bearing
distinction for S1/S2, because it means `Prompt` and its wire form are two types, not one
object serialized.

### F5 — WS push has exactly one legal direction

The game thread cannot touch a `WebSocketResponse` (different loop): `publish()` may only
*schedule* — `call_soon_threadsafe` → `ensure_future` → send on the net loop. Verified no
broadcast ran on the game thread. **Late-joiner resync fell out for free**: the `/live`
handler sends the current snapshot on `prepare`, so a client connecting mid-prompt gets
the live prompt, not an empty view. M6's resync story for prompts is cheap.

### F6 — `web.run_app` is not usable; `AppRunner` + `TCPSite` + `run_forever` is

Tested, not assumed. `web.run_app` off the main thread dies with
`RuntimeError: set_wakeup_fd only works in main thread of the main interpreter` — it
installs signal handlers. M4 must use the runner form. One afternoon saved.

### F7 — D1's soft dependency behaves as specified

With `aiohttp` absent, `App` boots normally, logs `[net] player server unavailable: No
module named 'aiohttp'` **once**, leaves `self._net = None`, and `_pump_net()` is a no-op.
`python gui/main.py map.png` is untouched on a machine without the dependency.

### F8 — the seam is inert against the existing suite

`./test.sh` on the patched tree: **146 passed / 1 failed**, the failure being the known
pre-existing `test_monk.py`. Identical to the baseline Step 0.6 left. The five touch
points cost nothing.

### What the spike did NOT answer

Stated so M1 does not mistake this for coverage:

- **`parent_id` and the prompt stack are untested.** G1 is flat — one window, one list of
  options, no submenu. Step 0.2's fact 2 (nested menus destroy their parent) remains a
  paper decision.
- **No `authorize()`, no principal, no join code.** Every submit was anonymous; the spike
  proves the *transport* of a decision, not the right to make it.
- **One prompt, one client, one reactor.** No two-player race over the same prompt (E3
  raced a *local* click against a remote submit, which is NN4's case but not the only one),
  no `deadline_ms` expiry, no reconnect mid-prompt.
- **Headless only.** Nothing was ever drawn on a real display.

### Settled against Step 0.5 *(user-agreed 2026-09-21)*

F1's one ask — a fifth `submit` error member — was put to the user and **agreed**:
`"timeout"` joins the closed set, and Step 0.5 carries the dated amendment and the
client-side rule that follows from it (re-read state, never auto-resubmit). The spike
asked for nothing else.

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

| # | Item | Why it is standalone | Blocks | |
| - | ---- | -------------------- | ------ | - |
| S1 | Atomic `_save_agents` / `_save_combat_state` writes (`main.py:13029`, `13085`) | Pre-existing latent bug that NN7 makes load-bearing | NN7, M6 | ☑ |
| S2 | `run.sh` binds 6080 to `127.0.0.1` | One-line deployment fix, not a feature | M4 | ☑ |

#### S1 + S2 — landed 2026-09-22

Two commits, not one: the standing rule forbids bundling, and they share nothing but a
date. Suite **152 pass / 1 fail** (`test_monk.py`, pre-existing and unrelated) — one suite
up, which is the new one.

**S2** was specified as `run.sh` and is **two** lines, because `interactive.sh:1` publishes
`-p 6080:6080` as well. The item's reason is A10 — convert the two-trust-domain split from
an intention into a fact — and a second script handing the unauthenticated DM console to
the LAN leaves the fact unconverted. Both now bind `127.0.0.1`. `debug.sh` publishes no
port and needed nothing.

**S1** landed as `gui/atomic_io.py` — `atomic_write_json(path, doc)`: temp sibling,
`flush` + `fsync`, `os.replace`, and the temp removed on **any** exception rather than only
`OSError`, so a doc that fails to serialize leaves no litter beside the real file.

It is a new module rather than a private helper in `main.py` because the pattern already
existed once: `SessionRoster.save` (M0) wrote it out longhand, per the M0 requirement that
the session file be atomic from day one. Writing it a second time in `main.py` would have
made an invariant that two files have to agree about — the same argument as D-M3-2, one
milestone earlier in its life. `roster.save` is repointed at the helper in the same change
and lost its now-unused `import os`. The module is stdlib-only, which is what keeps
`net/roster.py` importable without the GUI.

Line numbers in the table above were stale by ~190 lines (the M1–M3 work moved them); they
are corrected to the sites as they stand today.

**`tests/test_atomic_saves.py`, 5 checks**, registered beside the oracles. **Four of the
five force a write to fail** rather than asserting a happy path — an atomicity fix whose
test only ever sees a successful save is a test of `json.dump`. The fifth
(`test_round_trip_and_no_litter`) is the happy path, and earns its place only because it
also asserts the temp file is gone afterwards. `os.replace` is monkeypatched to
raise `ENOSPC`, which is the worst moment a crash can pick: temp written, fsynced, and the
swap never visible.

Per M3's rule, each check was run against a deliberately broken version first:

| Mutant | Caught by |
| ------ | --------- |
| `_save_agents` reverted to `open(path, "w")` | `_save_agents truncated the previous save` |
| `_save_combat_state` reverted to `open(path, "w")` | `_save_combat_state truncated the sidecar` |
| temp-file cleanup removed from the helper | `temp file survived a failed write: ['doc.json.tmp.1']` |
| helper writes in place, no temp at all | `a failed replace must not be swallowed by the helper` |

**Owed, and named honestly**: nothing asserts the `fsync`. The tests prove the swap is
atomic against a *process* crash, which is the failure mode NN7 actually has; surviving a
*power* loss additionally needs the fsync, and no test in this tree can observe it. The
directory is deliberately **not** fsynced — that would be needed for the rename itself to
be durable across power loss, and it costs a sync per autosave, which NN7 does a hundred
times a session. If the ring ever needs power-loss durability, that is the line to add and
the trade-off to re-take.

---

## Step 0.9 — M4's frozen decisions (frozen 2026-09-23)

User signed off 2026-09-23 on **D-M4-1** and **D-M4-2**; the remaining four are write-downs
of things this document already decided elsewhere, recorded here so M4 does not rediscover
them. **Frozen** on the same terms as Step 0.1: changes need a dated amendment with a
one-line reason.

### D-M4-1 — `GET /map.png` is masked server-side

`_draw_fog_overlay` (`main.py:15303`) paints unexplored cells dark. The DM's own screen
hides the map art there — which is precisely why D-M3-5 filters terrain, doors and lighting
against the explored mask. Serving the page PNG verbatim hands a player the floor plan of
the wing they have not entered, as a picture, and the M3 filter table's *"omitted entirely —
not sent-and-hidden"* row forbids exactly that. Compositing fog **client-side** is rejected
for the same sentence: a player who reads their own traffic would have the level.

So the route masks before it serves, and the rules are:

- **The mask is opaque: alpha 255.** It is *not* `FOG_COL`. `FOG_COL = (24, 24, 28, 245)`
  (`main.py:15326`) composites 10/255 ≈ 4% of the underlying art through the fog —
  invisible at a glance on the DM's screen, recoverable by contrast-stretch on a
  high-contrast floor plan. Reusing the constant is the obvious implementation and it is
  the wrong one.
- **Cell geometry comes from raw image px**, `bm.v_line_positions` / `h_line_positions`
  unscaled — `map_scale` is a screen-space concern and has no meaning on the wire.
- **Two cache entries, not one per viewer.** Fog is party-scoped and that is frozen
  (Step 0.1), so one mask serves every player: raw for the DM viewer, masked for everyone
  else.
- **The cache key is the mask hash**, not the image content hash. `_map()`
  (`gui/net/view.py:271`) does not emit `image` at all today, so M4 writes the field fresh
  and breaks no contract: `?v=<mask-hash>` for a player, `?v=<content-hash>` for the DM.
- **Staleness is safe in exactly one direction.** A masked PNG that lags the mask shows
  *more* fog than the party has earned, never less. Any later debounce or throttle must
  preserve that direction; this sentence is the invariant it has to be checked against.
- **Amended 2026-09-23 — the image key lags on purpose** (reason: measured, an exploration
  delta re-keys the PNG and costs each player a fresh 0.8-2.5 MB fetch of the largest page).
  The debounce this bullet anticipated is now specified, and it is the *published snapshot*
  that lags, not the render — so the `?v=` in a view always names a picture the route can
  actually serve, and a client never chases a key that does not exist yet. The policy:
  · at most one re-key per **3 s**, and always one at a turn boundary;
  · the client draws fog from the view's own (live) fog block, so a cell the party has just
    earned reads as dark art until the next re-key — the lag is visible, and it is fog;
  · **the lag is allowed only while the published mask is a subset of the live one.** Page
    switch, fog toggled *on*, and a mask that shrank (a save loaded) each publish
    immediately, because in those three the lagged image is not foggier — it is *wrong*, and
    in the fog-on case it is a leak. Subset is the machine-checkable form of the invariant
    above, and the code asserts it rather than trusting the three cases to be exhaustive.
  Worst case is still one page per viewer per 3 s (~0.85 MB/s on `wachterhaus`). If the
  table finds that too much, the answer remains tiles, in M4b — never a rawer image.
- **Cost, named:** the mask changes on every newly-explored cell, so this is one full-page
  PNG re-encode per exploration delta. Regenerate lazily, on request, off the frame thread —
  and **measure it on the largest page in the tree before M4 calls the route done.** If the
  encode is not affordable there, the answer is a cheaper mask representation, never a
  rawer image. *(Measured 2026-09-23 — see [The masked page image](#the-masked-page-image--landed-2026-09-23).
  The encode passes at 95 ms worst case. The bullet named the encode and not the
  **download**, which is the cost that does not pass: a decision is owed before the route
  is wired.)*

### D-M4-2 — M4 ships snapshot-only; Envelope 3 and the animation are M4b

Step 0.5's Envelope 3 makes `seq` **per-viewer**, assigned as each viewer's stream is
filtered, because dropping an event leaves a hole and a shared global cursor with holes
leaks the rate of hidden activity. That makes S3 a filtered per-viewer projection with the
same discipline as `build_view` and a byte-level test of its own — not a field on a
message. M4's client spec also animates `NpcVisualEvent` `Move` paths, which needs that
stream. Together they make M4 the largest phase in the plan.

**M4** is therefore snapshot-only: every push is a full `view`, tokens jump rather than
walk, and the client has no event cursor. F5 makes this nearly free — `/live` sends the
current snapshot on prepare, so late-joiner resync already fell out of the spike.
**M4b** adds Envelope 3, the per-viewer filtered stream, and the `Move` animation, with its
own mutant pass.

**Snapshot-only is not a strict subset — it has its own bandwidth profile, so the cadence
is frozen with it.** A full view carries the party's explored mask, and a push per token
move is the traffic Envelope 3 exists to avoid. M4 therefore **coalesces**: at most one push
per viewer per 250 ms, always one at a turn boundary, always one when a prompt is addressed
to that viewer, and never two in flight. Without this rule M4b arrives to fix a problem M4
invented.

**Amended 2026-09-23 — the mask crosses as row runs, not cell pairs** (reason: measured,
this paragraph's "up to 1200 pairs on a 40×30 page" was 7x low — the real pages in this tree
have ~10 px cells, and a fully-explored `wachterhaus` is 8918 pairs, 85 KB of JSON on every
push, 341 KB/s per viewer at the frozen cadence). The field is **renamed as well as
reshaped**, to `fog.explored_runs`, carrying `[row, col_start, col_end]` inclusive spans:

- 8918 pairs become **91 runs**, and the 12×12 test scene's 49 pairs become 7. The cadence
  rule above stands unchanged; it was necessary and it was not sufficient.
- The rename is the point of doing it now. A client that read pairs would misread runs
  silently, and M4's client does not exist yet, so the shape change costs nothing today and
  a rename costs nothing ever.
- A bitmap is smaller still and was rejected: the byte-level discipline M3 was built on
  depends on being able to read a leak out of the serialized bytes, and base64 rows cannot
  be read that way.
- Runs are emitted row-major with `col_start` ascending, so the encoding is canonical and a
  byte-level assertion over it is stable.

### D-M4-3 — `_pump_net()` pumps the command queue and nothing that redraws

F3's advice, promoted to the named shape. Pumping inside a modal means **a DM authoring
modal is no longer a quiescent point** — state can advance while *Generate Dungeon* is
open. `_submit_reaction` drags `_flush_combat_log` / `_update_attack_overlay` /
`_sync_spell_effect_cache` behind it, and in the spike those ran headlessly while the modal
owned the screen. F3's owed real-display look belongs to **M4**, not M3.

### D-M4-4 — the seat claim on re-join: credential first, display name second

Step 0.1 froze auto-seat on a valid code, and a returning player "picks their existing
principal or creates a new one". The matching rule:

1. A live, unrevoked credential re-attaches to **its own principal**, by `kid`. Names are
   not consulted.
2. Only when the credential is gone does the join fall back to matching `display_name`
   **case-insensitively** against existing player principals.
3. No match creates a new principal.

The order matters: two players who both type "Kira" race under name-matching alone, and the
second silently takes a seat the token could have resolved without the DM touching
anything. Name-matching is acceptable as the fallback because R2 already accepts that
anyone holding the code can claim to be Kira, and the DM sees and can reassign every seat
(NN4). `display_name` remains "never a key" (`net/roster.py:73`) for storage and ownership —
this is a join-time hint, not an identity.

### D-M4-5 — `AppRunner` + `TCPSite` + `run_forever`

F6 tested it: `web.run_app` off the main thread dies on `set_wakeup_fd`. Carried here so it
is a constraint M4 starts from and not an afternoon it spends.

### D-M4-6 — the `Origin` check is same-origin against `Host`, never a constant list

A9 requires the check, and a phone at the table sends `Origin: http://<lan-ip>:6081` where
the IP varies with the network. So:

- **`Origin` present** ⇒ its scheme-less `host:port` must equal the request's own `Host`.
- **`Origin` absent** ⇒ allow. Native clients and `curl` send none, and a strict deny breaks
  the tooling. This is safe *because* A3 forbids cookies: credentials are bearer tokens a
  cross-origin page cannot read or cause to be sent, so `Origin` here is defense in depth,
  not the primary CSRF defense.

A configured allowlist is rejected because it cannot be written down correctly in advance,
and "just skip `Origin` on the LAN" is rejected because it is the version that makes the
DM's own browser a CSRF vector into the player server.

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
| `ContextMenu.show(pos, [(label, callback)])` | 69 sites | **already** a label+callback model — the one remotable seam that exists. Step 0.2 found **18 more** prompt sites on seven other dialog classes (**87 total**), including the in-combat spell list. |
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
| **M0** ☑ | Token ownership model | very low | 1–2 days | who controls what |
| **M1** ◐ | `PromptBus`; reroute reactions + all **87** prompt sites | medium | 1–2 weeks | a scriptable, headless-testable DM console |
| **M2** ◐ | Legal-action model out of `_draw_combat_panel` | **high** | multi-week | a turn's options as data |
| **M3** ☑ | `GameView` projection + fog filtering | low | ~1 week | per-player state, still local |
| **M4** | Transport + **snapshot-only** spectator web client (D-M4-2) | medium | ~1 week | **players watch on their own screens** |
| **M4b** | Envelope 3 (per-viewer filtered stream) + `Move` animation | medium | ~1 week | the board moves instead of jumping |
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

### M0 — what was built (done 2026-09-21)

Implemented straight from Step 0.4's frozen schema, on the go-ahead recorded in Step 0.9.
No behavior outside ownership changed, nothing was bundled in, and the frozen blocks were
not amended.

#### Where the code went

| File | What |
| ---- | ---- |
| `gui/net/__init__.py` (new) | The multiplayer package. Import-safe without pygame and without the C++ extension, which is what lets the M0 tests run headless. |
| `gui/net/roster.py` (new) | `Role` / `AuthBlock` / `Principal` / `Credential` / `Action` / `TokenTarget` / `PromptTarget`, and `SessionRoster` with `authorize()`, `controlled_by()`, credential mint/verify/revoke, and the atomic session-file read/write. |
| `gui/battle_map.hpp`, `battle_map.cpp` | `PlacedAgent::controller` (`std::string`, defaults to `"dm"`) plus `getAgentController` / `setAgentController`. |
| `gui/bind_battle_map.cpp`, `bind_types.cpp` | `set_agent_controller` / `get_agent_controller`, and `placed_agents[i].controller` as a read-only property. |
| `gui/main.py` | Call-site wiring only (NN3): the import, `self.roster`, `self._session_path`, `_sync_roster_tokens()`, `_save_session()`, `controller` in the agents save/load, and the **Controller ▸** submenu. |
| `tests/test_session_roster.py` (new), `tests/run_all_tests.py` | 11 tests, registered next to the other oracles. |
| `.gitignore` | `*_session.json` — table metadata, never scene data. |

#### Three decisions worth recording

**D-M0-1 — `controller` lives on the C++ `PlacedAgent`, not in a Python side table.**
A1 says the agent record is the sole persisted truth, and a Python `dict` keyed by agent
index would reintroduce exactly the basis-dependence A1 was amended to kill: every agent
deletion would shift its keys. On the struct it rides through `_save_agents`'s compaction
for free, next to `faction` and `on_deck`, which are the same kind of encounter-side
metadata.

**D-M0-2 — summon inheritance is implemented in `setAgentSummonerIdx`, not at the call
sites.** Tagging the summon is the one funnel every summon path already goes through
(five Python sites today, and any future C++ one), so the inheritance cannot be forgotten
by a new caller. It inherits *at creation*, which is A1's wording: re-assigning the
summoner later does not chase down its existing summons.

**D-M0-3 — `authorize()` keeps Step 0.4's exact signature; prompt liveness arrives through
a hook.** The `ANSWER_PROMPT` row needs the prompt's owner and whether it is still live,
and the prompt bus that owns that state does not exist until M1. Rather than widen the
frozen signature, the roster carries `prompt_lookup: (prompt_id) -> (owner, is_live)`,
which M1 installs. **With no bus installed a player is denied** — the safe direction — and
the DM is still allowed by NN4.

#### What the DM sees

Right-click an agent → **Controller ▸** → `✓ DM`, one row per seated player, and
`Seat a new player…` (which reuses the existing name prompt, as `Edit Name…` does). One
submenu on the existing menu, no new dialog — what the frozen target user procedure pins
down. Assigning writes the agent's `controller` and saves `<base>_session.json`.

#### Deviations from the M0 text, and why

1. **`Seat a new player…` was not in the M0 bullet list.** Without it the submenu would
   list only the DM until M4's join route exists, and the phase would be unverifiable by
   hand. It mints a principal exactly as a join will.
2. **The session file is written atomically from day one** (temp file + `os.replace`),
   which is S1's fix applied to *new* code rather than bundled into it. S1 itself —
   `_save_agents` / `_save_combat_state` — is untouched and still owed.
3. **`main.py` grew by 88 lines, against NN3's "should trend down".** All of it is
   wiring the constraint permits (an import, four short methods, two save/load lines),
   but ~40 of those lines are the Controller submenu, which M0 itself asks to put on the
   existing agent menu. Recorded rather than argued away: the trend NN3 cares about starts
   at M1, where 87 prompt sites move *out*.

#### Test results

`tests/run_all_tests.py`: **147 suites passed, 1 failed**. The single failure is the
pre-existing `test_monk.py::test_deflect_attacks_reduces_physical` (same test, same
line 505) that has been the baseline since `COMBAT_REFACTOR_PLAN.md` R0. `test_determinism.py`
is byte-identical and `test_combat_panel.py`'s golden is unchanged — M0 touched no rules
and no panel geometry. `test_session_roster.py` is **11/11**:

| Test | Proves |
| ---- | ------ |
| `test_session_file_round_trip` | the file round-trips; no seat list (A1), no credential and no signing key on disk (A3/A5); a credential from a previous process does not verify |
| `test_autosave_slots_clamped` | NN7's 1–5 ring depth, default 3 |
| `test_credential_lifecycle` | signature, expiry, tamper-rejection, and `revoke_all()` as A5's panic button |
| `test_revoked_credential_refused` | revocation is per-`kid`; unseating refuses every credential the seat held |
| `test_authorize_policy_table` | every row of Step 0.4's table, including both NN4 *always* rows and the prompt-liveness refusal |
| `test_unseated_principal_denied` | a principal off the roster is denied all seven actions, and a caller-supplied record claiming `role: dm` is not a DM (A8) |
| `test_ownership_is_derived` | `controlled_by` is a cache over `controller`; a player owning zero tokens is a spectator, not an error |
| `test_unknown_controller_loads_as_dm` | A1's fold-to-DM, *and* that the id is kept so re-seating restores the link |
| `test_controller_round_trip` | `controller` present and absent (a pre-multiplayer save) through a real `App` save/load |
| `test_ownership_survives_compaction` | a tombstoned agent renumbers the list and ownership still lands on the same creatures |
| `test_summon_inherits_controller` | inheritance through `set_agent_summoner_idx`, and that summons stay unpersisted |

#### Not covered by a test

The **Controller ▸** submenu itself. This codebase cannot drive a pygame menu from a test
until M1's bus exists — that is the gap M1's acceptance criterion closes. Everything the
submenu *calls* (`set_agent_controller`, `_sync_roster_tokens`, `add_principal`,
`_save_session`) is covered by `test_session_roster.py`; the wiring between the click and
those calls is **unexercised** — not by a test, and not yet by a run of the app. First
click of it is the thing to watch.

#### What M1 inherits

- `SessionRoster.prompt_lookup` is the seam the `PromptBus` fills (D-M0-3).
- `_sync_roster_tokens()` is the only way the ownership cache moves. It is called on load,
  on a controller assignment, and when the Controller submenu opens. **M3 must call it
  when it builds each `GameView`** — it is cheap, and the alternative is a stale index.
- The standalone items are still owed and unchanged: **S1** (atomic `_save_agents` /
  `_save_combat_state`, blocks NN7/M6) and **S2** (`run.sh` binds 6080 to loopback,
  blocks M4). *(Both landed 2026-09-22 — see [S1 + S2](#s1--s2--landed-2026-09-22).)*

---

### M1 — The `PromptBus` ⭐

The pivotal phase. Everything else is plumbing around it.

**Step 1 ☑ — build the bus** (`gui/prompts.py`, new). `Prompt` / `Option` / `PromptBus` as
above. Local renderer: `ContextMenu`, unchanged in appearance.

**Step 2 ☑ — reroute the reaction window first.** `_show_pending_reaction_menu`
(`main.py:10493`) is the ideal first customer: the engine already hands it a vetted,
labeled option list; there is exactly **one** call site; and the flow is already
snapshot-safe. Converting it changes no behavior and proves the bus end to end.

**Step 3 — reroute the 69 `ContextMenu.show` sites, then the 18 on the other seven renderers (87 total).** These are already
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

### M1 Steps 1–2 — what was built (done 2026-09-21)

The bus exists and the reaction window runs on it. Step 3 (the remaining 86 prompt
sites) has not started. No behavior changed on the DM console, and the frozen blocks
were not amended.

#### Where the code went

| File | What |
| ---- | ---- |
| `gui/prompts.py` (new, 464 lines) | `Option` / `Response` / `Prompt` / `PromptState` / `SubmitResult` / `PromptBus`, the `ContextMenuRenderer`, and `options_from_pairs`. Imports no pygame — the renderer is duck-typed on `show` / `dismiss` / `visible`. |
| `gui/main.py` (+28 net) | Call-site wiring only (NN3): the import, `self.prompts`, the re-bind in `_set_encounter_base`, the converted `_show_pending_reaction_menu`, and `self.prompts.renderer_dismissed()` in place of the reaction-skip guard in `_handle_events`. |
| `tests/test_prompts.py` (new), `tests/run_all_tests.py` | 12 tests, registered next to the other oracles. |

#### Six decisions worth recording

**D-M1-1 — the callback rides on the `Option`, not only on the `Prompt`.** All 87 sites
are already `(label, callback)` pairs, so `options_from_pairs` converts one mechanically
and the callback the remote answer fires in M5 is *the same object* the local click
fires today (F4's point). `Prompt.on_answer` remains for the responses that are not a
choice at all — `expects` `"cell"` / `"agent"`, which is where the target-pick sites
land later in Step 3. Exactly one of the two runs: the option's, if it has one.

**D-M1-2 — `parent` is explicit, never inferred.** The tempting rule — "a prompt opened
during another prompt's callback is its child" — is wrong here: a reaction chain opens
the *next* reactor's window from inside the previous window's callback, and those are
siblings. Only a call site that means "this is a submenu of that" passes `parent=`.

**D-M1-3 — locally, answering or cancelling a stack resolves the whole stack.** Step 0.5
has a cancelled child re-send its parent, and records that as the protocol's single
deliberate divergence from the DM console. It stays a divergence: implementing it in the
local renderer would change DM behavior inside the one phase whose acceptance criterion
is that nothing changes. `parent_id` is carried and tested; M5's renderer is where it
starts to *do* something. Ancestors resolved this way are marked `superseded`, never
`cancelled` — nobody declined them, and firing their `on_cancel` would submit a Skip
nobody asked for.

**D-M1-4 — a prompt is marked answered before its callback runs.** NN4's "first valid
submission wins" is decided by liveness and by nothing else, and the callback is exactly
where a second submission gets its chance to interleave (in M5 from the network; today
from a chained prompt). `test_first_submission_wins` submits again *from inside* the
first submission's callback and asserts `not_live`.

**D-M1-5 — the reaction window's combat-log sentence is now also the prompt's title.**
It was already composed per window (`"Threat gets an opportunity attack vs Mover!"`);
it is composed once into `title`, logged, and sent. A remote player reads exactly what
the DM's log says, and no second wording can drift from the first.

**D-M1-6 — dismissal is reported by the event loop, not detected by the bus.**
`_handle_events` calls `renderer_dismissed()` after `ContextMenu.handle`; the bus
cancels only if a prompt is still live *and* the widget is no longer showing. That
subsumes the two flag guards the old code needed (`pending_vitality_target`,
`pending_decision().active`): picking "Vitality of the Tree" *answers* the prompt before
it arms its target-pick, so there is nothing live left to cancel.

#### What the DM sees

Nothing new. The popup is the same widget at the same anchor with the same rows in the
same order; `ContextMenu` was not modified. The one internal difference is that the
row's callback now goes `click → bus.choose(option_id) → validate → the same callback`
instead of `click → the callback`.

#### Test results

`tests/run_all_tests.py`: **148 suites passed, 1 failed** — the pre-existing
`test_monk.py::test_deflect_attacks_reduces_physical` that has been the baseline since
`COMBAT_REFACTOR_PLAN.md` R0. The count is 147 + this suite. `test_determinism.py` is
byte-identical and `test_combat_panel.py`'s golden is unchanged. `test_prompts.py` is
12/12 here, and 14/14 once the click-path pair below is added:

| Test | Proves |
| ---- | ------ |
| `test_wire_projection` | every Step 0.5 `prompt` field is present, and no callable and no local render hint reaches the projection (F4) |
| `test_submit_errors` | `protocol` / `bad_option` / `not_live`, a disabled option refused, a refused submit leaving the prompt live, and `expects: "cell"` rejecting an option id |
| `test_first_submission_wins` | NN4, from inside the winning submission's own callback |
| `test_authorization` | a non-owning player and an unseated principal are denied and never reach the callback; the DM is allowed anyway |
| `test_prompt_lookup_hook` | the bus fills M0's `prompt_lookup` (D-M0-3), reports liveness, and re-fills it when a load swaps the roster |
| `test_supersede_runs_no_callback` | a re-ask destroys the live prompt without resolving it — Step 0.2's single-`ContextMenu` reality, and no phantom Skip |
| `test_cancel_and_dismissal` | dismissal runs `on_cancel`; a click that chose an option does not |
| `test_prompt_stack` | `parent_id` on the wire, the parent live while its submenu is up, and D-M1-3's local resolution |
| `test_oa_opens_reaction_prompt` | a real parked `LeftReach` window becomes a prompt owned by the **reactor**, with the engine's own options in the engine's order — and the DM's popup genuinely on screen |
| `test_answer_resumes_the_move` | **the M1 acceptance criterion**: the OA is taken, the reaction is spent and the move completes, with no pygame event anywhere in the call stack |
| `test_player_answers_own_reaction` | a seated player answers their own creature's window; another player gets `denied` and the engine is untouched |
| `test_dismissal_skips_the_window` | clicking away submits the Skip, the reaction is not spent, and the move still completes |

#### The click path, and M0's gap (added 2026-09-21)

M0 and M1 Step 2 both had to record the same hole: everything between the *mouse* and
the callback was unexercised. It is now covered, by posting real `MOUSEBUTTONDOWN`
events onto pygame's queue — `_handle_events` reads `pygame.event.get()`, so a posted
event is indistinguishable from one SDL put there, and under the dummy video driver the
display surface draws and saves like any other.

| File | What |
| ---- | ---- |
| `tests/gui_driver.py` (new) | The shared harness: `cell_center` (the inverse of `_screen_to_cell`, pan and scale included), `post_click`, `menu_row_pos` / `click_menu` / `click_away` keyed off `ContextMenu`'s own geometry constants, and `screenshot`. Each Step 3 batch gets its click check for free. |
| `tests/test_prompts.py` | `test_click_takes_the_opportunity_attack` — the DM's actual mouse, through `ContextMenu.handle` into the bus and the engine; `test_click_away_skips_the_window` — dismissal, the path that freezes a turn if it regresses. **14/14.** |
| `tests/test_session_roster.py` | `test_controller_submenu_click_path` — right-click the token → **Controller ▸** → the player's row, then the four things the callback owes: the agent record, the ownership cache, `<base>_session.json`, and the log line. It also asserts the ✓ moves on re-open. **12/12.** M0's "first click of it is the thing to watch" is answered: it works. |

`python3 tests/test_prompts.py --shot <path>` renders the parked reaction popup to a PNG
— not an assertion, a way to look at the widget, which is otherwise unverifiable without
a display. Inspected 2026-09-21: four rows (`[Weapon] Test Blade`, two `[Weapon]
Unarmed`, `Skip`), unchanged in appearance.

> **Observed while looking, and not fixed here:** `_agent_screen_pos` (`main.py:10713`)
> anchors the popup with `cell_pixel_size` arithmetic and consults neither `map_scale`
> nor `pan_x/pan_y`, so on a panned or zoomed map the popup opens away from its token.
> Pre-existing and untouched by M1 — the bus passes that function's output through
> unchanged — but it is a real bug and belongs on the cleanup list, not in this phase.

#### Not covered by a test

- **A real display.** Everything here is headless (`SDL_VIDEODRIVER=dummy`) and every
  click is synthesized. The VNC path itself — noVNC → x11vnc → Xvfb → pygame — is the
  one link no test exercises; the cheap check is one manual pass through
  `http://localhost:6080/vnc.html` after `run.sh`.
- **`deadline`.** The field exists and reaches the wire; nothing sets it and nothing
  expires. Expiry is M5's, per the plan.
- **The other 86 sites.** They still call their widget directly, which is exactly why
  `renderer_dismissed()` is a no-op when the bus holds nothing live.

#### What Step 3 inherits

- `options_from_pairs(...)` is the whole mechanical conversion for a
  `(label, callback)` site; the judgement per site is only `owner`, `kind` and whether
  it is a submenu (`parent=`).
- **`owner` is the one field that needs thought at every site.** G3's five defender
  reactions and G1 have a non-actor owner; everything in G2/G4/G5/G6 is the actor's own
  controller; G9/G10 are DM-authoring and take `owner=DM_PRINCIPAL_ID`, since Step 0.2
  marks them never-remoted.
- Batch order is Step 0.2's `M1 order` column, unchanged: G2 → G3 → G4 → G6 → G7 → G8 →
  **G5 last**.
- `main.py` grew by 28 lines here, against NN3's "trend down". That was the price of the
  seam; the reversal is Step 3, where 86 option lists move out of `main.py` and the
  `pending_*` flag closures go with them.

---

### M1 Step 3 — what was built (done 2026-09-21)

Every `ContextMenu.show` site in the game is on the bus, plus the spell grid and the
single-select value pickers. 79 sites this step, 80 with Step 2's reaction window. No
behavior changed on the DM console, no frozen block was amended, and the nine sites that
are **not** converted are listed below with the reason, because each of them needs Step
0.5 unfrozen rather than more work.

#### The inventory moved twice, and both extras came from M0

Step 0.2 counted **69 `ContextMenu` sites and 18 on seven other renderers = 87**. The
live counts are **70 and 19 = 89**, and the diff is not a miscount:

| Delta | Where | Why Step 0.2 missed it |
| ----- | ----- | ---------------------- |
| G9: 7 → 8 | the **Controller ▸** submenu on the map right-click menu | M0 (`0a8ca7a`) added it *after* Step 0.2 was written |
| others: 18 → 19 | a second `NamePromptDialog` — "Seat a new player…" | same commit, same reason |

So the phase that inventoried the prompt surface was itself overtaken by the phase that
followed it. Worth remembering for M2's action inventory (Step 0.3, 87 actions): that
count is a snapshot too, and M2 should re-derive it rather than trust it.

#### What went on the bus

| Group | Sites | `owner` | Note |
| ----- | ----: | ------- | ---- |
| G2 post-hit riders | 24 | attacker's controller | one identical two-line tail at all 24; converted by script |
| G3 defender reactions | 5 | **the reactor's** controller | the per-site judgement Step 0.2 warned about — see D-M1-8 |
| G4 attack setup | 2 | actor's | anchored on the panel, not on a token |
| G6 panel sub-menus | 13 | actor's | includes the three built inline in `_handle_events` |
| G7 map objects | 4 | actor's, folding to DM out of combat | item-context is DM-only and says so |
| G8 target-pick confirmations | 2 | actor's | `kind` is `target` / `confirm` here, not `action` |
| G5 spellcasting | 6 | caster's | converted last, as planned; the 21 `pending_*` flags were never touched |
| G9 map right-click DM menus | 8 | **pinned** to `DM_PRINCIPAL_ID` | five of the eight are submenus — see D-M1-9 |
| G10 top-bar authoring | 5 | **pinned** to `DM_PRINCIPAL_ID` | |
| `SpellGridMenu` | 1 | caster's | the in-combat spell list, Step 0.2's "single most-used combat prompt" |
| `ElementPickerDialog` (single-select) | 9 | actor's | the new `ElementPickerRenderer` |
| **Total** | **79** | | |

#### What did NOT go on the bus, and why

Nine sites remain on their widgets. They are not leftovers — every one of them asks for
something Step 0.5's **frozen** `expects` vocabulary (`choice` / `cell` / `agent` /
`none`) cannot express, so converting them means unfreezing the wire format first.

| Renderer | Sites | What it actually asks for |
| -------- | ----: | ------------------------- |
| `ElementPickerDialog`, `multi=True` | 1 — Magic Circle / Hallow warded types | a **set** of values. There is no multi-select response shape. |
| `SpellSelectionDialog` | 3 | a search over all 405 spells with per-level tabs — a browser, not an option list. **One** of the three is DM authoring. |
| `NamePromptDialog` | 2 | **free text**. There is no `expects: "text"`. |
| `GridSpanDialog` | 1 | two numbers. Same gap. |
| `TeamPickerDialog` | 1 | a per-creature team grid — DM authoring, and an editor rather than a choice. |
| `MobSelectionDialog` | 1 | the monster catalogue — a browser. |

**D-M1-12 — `expects` stays frozen at four; six renderers become DM-console-only, and
the browsers were never a wire problem.** *(Decided 2026-09-21, user-agreed.)*

Step 3 handed back "grow `expects`, or declare these DM-only". The answer is neither, in
three parts, and two of the three cost nothing:

**a. `expects: "text"` and `"number"` are refused — the question was already answered.**
Step 0.5's *"What is deliberately not in v1"* reads: *"No client→server chat or free text.
Nothing on the wire carries a string a client wrote. That removes an entire injection and
moderation surface from v1."* Adding `"text"` is not an amendment to that clause, it is a
reversal of it. Nothing is given up by honoring it, because **every** site that wants text
or a number is DM authoring: both `NamePromptDialog`s (rename at `19404`, seat-a-player at
`19548`), `GridSpanDialog` (`14866`, map setup) and `TeamPickerDialog` (`5370`).

**b. Six of the nine are DM-console-only, not five.** Step 3's own count was off by one in
the same sentence that named the exception: `SpellSelectionDialog` at `19363` is the *add
a spell* button inside the DM's creature-sheet editor, not a combat path. The DM-only set
is therefore those six — 2 `NamePromptDialog`, `GridSpanDialog`, `TeamPickerDialog`,
`MobSelectionDialog` (`2261`, "Create Mob…") and `SpellSelectionDialog` (`19363`). **M3's
`GameView` never shows them**, which is the only obligation this creates, and it is a
filtering rule of exactly the kind M3 is already written around.

**c. The two player-facing browsers need no wire change at all — they need M5's renderer.**
Wish (`9789`, ≤ 8th level → **389** of the 405 spells) and Divine Intervention (`10049`,
`CLERIC_DI_SPELL_NAMES` → **80**, all present in `spells.json` at level ≤ 5) are *closed,
finite option lists*. "Browser" is a property of the widget, not of the question, and
D-M1-10 already put that behind `Prompt.render` — a local hint that never reaches the wire.
On the wire they are `expects: "choice"` with a long `options` array and a render hint a
remote client answers with a search box; the cost is ~23 KB on one prompt, once.

They are **not converted now**, deliberately. `prompts.py`'s own module docstring already
schedules this ("a second renderer — a browser, in M5"), and converting today would build
389 `Option` objects per Wish cast for a consumer that does not exist until M5. The
classification is what M2–M4 needed; the code is M5's, and it is now a fourth renderer
rather than an open question.

**What is genuinely deferred: exactly one site.** The Magic Circle / Hallow ward picker
(`9935`, `multi=True`, six rows) is the only site in the game that asks for a **set**, and
it is player-reachable. Growing the wire for it is small and does not touch the no-strings
clause — one `expects` member (`"choices"`) and one `submit` field carrying a list of
option *ids*. **Not done now**: a one-member vocabulary change with one caller is decided
better in M5, when intent submission is the thing that needs it, than in an amendment
written three phases ahead of its only consumer.

**Net effect on the phases that follow**: Step 0.5 stays frozen, unamended, through M2,
M3 and M4. M3 owes one filtering rule (the six renderers). M5 owes a browser renderer and
a one-member `expects` decision. M2 is unblocked and is not touched by any of this.

#### Where the code went

| File | What |
| ---- | ---- |
| `gui/main.py` (+83 net) | three helpers — `_ask_actor`, `_ask_dm`, `_agent_name` — the three-renderer registration, and 79 converted call sites. |
| `gui/prompts.py` (+152) | `SpellGridRenderer`, `ElementPickerRenderer`, a renderer *registry* on the bus (`render=` names one), and `PromptBus.answering`. |
| `gui/dialogs.py` (+8) | `ElementPickerDialog.dismiss()` — close without committing, for the supersede path. |
| `tests/gui_driver.py` (+69) | click helpers for the two new widgets, keyed off their own geometry constants. |
| `tests/test_prompts.py` (+188) | five checks, one per judgement Step 3 makes. |

#### Five decisions worth recording

**D-M1-7 — two helpers, not 79 inline `prompts.ask` calls.** `_ask_actor(actor_idx,
kind, title, pairs, …)` is the whole conversion of a site: it derives the owner, anchors
at the token and runs `options_from_pairs`. `_ask_dm(...)` is the same with `owner`
**pinned** to `DM_PRINCIPAL_ID` rather than derived, which is what keeps seating a player
on a token from handing them the authoring menus. The pin is asserted, not assumed
(`test_dm_menu_submenu_chain_carries_parent` seats a player on the very token whose DM
menu it then opens).

**D-M1-8 — `owner` follows the ANCHOR, and that is why G3 was free.** Every prompt is
anchored at the creature it belongs to, and G3's five defender reactions were *already*
anchored at the reactor (`_agent_screen_pos(target_idx)`, `(sentinel_idx)`, `(pal_idx)`,
`(interceptor_idx …)`) because that is where the DM needs to see the popup. Deriving the
owner from the anchored index therefore gets all five right by construction instead of by
five separate judgements. Step 0.2 called `owner` "the one field that needs thought at
every site"; in the event the thought had already been done, by whoever decided where the
popup should appear.

**D-M1-9 — `PromptBus.answering` names a submenu's parent, and exposes a hole in
Step 0.5's back path.** A row reading "Difficulty ▸" opens its child from inside its own
`on_choose`, so the parent is simply *the prompt being answered*; the bus now tracks that
(saved and restored, so a chained rider nests correctly) and a submenu passes
`parent=self.prompts.answering` instead of threading the parent object through three
closures. Set only during `submit` dispatch, never during `on_cancel` — a declined
reaction chaining to the next reactor is a sibling, which is exactly what D-M1-2 refuses
to infer a parent for.

The consequence is the part to remember: **on the DM console the parent is already
ANSWERED by the time its submenu opens**, because clicking the row is what answered it
(D-M1-4). Step 0.5's "cancelling a child re-sends its parent" therefore cannot re-*send*
that prompt in M5 — it has to re-**ask** it, producing a new id. Harmless today (an
answered ancestor is skipped by every resolution path in the bus) and tested, but M5 must
not be written against the assumption that the parent is still live.

**D-M1-10 — three renderers, chosen by a local hint that never reaches the wire.**
`Prompt.render` sits beside `anchor` as a render hint, and the bus holds a name →
renderer registry (`"default"` the popup, `"grid"`, `"picker"`). The renderer that drew
the live prompt is remembered, because dismissal is *reported* by the event loop
(D-M1-6) and there are now three widgets that can report it. `_handle_events` calls
`renderer_dismissed()` after the picker's and the grid's `handle` exactly as it already
did after the popup's.

Each converted site passes the widget's **existing** title string through as
`Prompt.title`, so the DM sees no new text — a friendlier sentence there would have been
a visible change inside the one phase whose acceptance criterion is that nothing changes.
A remote renderer names the creature from the wire's `actor` field instead.

**D-M1-11 — the picker's empty commit is a cancel, routed the same way every other
dismissal is.** `ElementPickerDialog` commits on dismiss, calling its callback with an
empty list; nine call sites are written against that. `ElementPickerRenderer` **drops**
the empty commit (it is not an answer) and the event loop's `renderer_dismissed()` turns
it into `on_cancel`, which each site sets to the handler it always called. That needed a
public `ElementPickerDialog.dismiss()` — close *without* committing — because the
supersede path must not fire a callback nobody asked for.

#### What the DM sees

Nothing new. Same widgets, same anchors, same rows in the same order, same titles on the
two widgets that have one. What changed is under each click:
`widget.handle → bus.choose → authorize → the same callback`.

#### Test results

`tests/run_all_tests.py`: **148 suites passed, 1 failed** — the pre-existing
`test_monk.py::test_deflect_attacks_reduces_physical`, unchanged since `COMBAT_REFACTOR_PLAN.md`
R0. `test_determinism.py` byte-identical; `test_combat_panel.py`'s golden unchanged. The
suite was run after each batch (G2+G3, G4+G6, G7–G10, G5, the other renderers) and was
green at every one. `test_prompts.py` is **19/19**.

| Test | Proves |
| ---- | ------ |
| `test_rider_prompt_owned_by_the_attacker` | G2: the rider is the attacker's, another player is `denied`, and the denial leaves it live; then the real mouse resolves it |
| `test_defender_reaction_is_owned_by_the_defender` | G3: the prompt belongs to the defender and the **attacker's** player is refused — the one judgement that is not the actor's |
| `test_dm_menu_submenu_chain_carries_parent` | G9, by mouse: right-click ▸ *NPC Automation* ▸ *Difficulty* ▸ *Level 3* really sets the difficulty; `parent_id` chains and reaches the wire; owner stays the DM although a player holds the token |
| `test_picker_renderer_answers_and_cancels` | the picker answers through the real widget, keeps its exact title, and its empty commit arrives as `on_cancel` with the prompt `CANCELLED` |
| `test_spell_grid_renderer_answers_and_dismisses` | the grid answers, and dismissing it runs no callback |

#### Two things this step owes, and one it did not fix

- **`main.py` went UP by 83 lines, not down.** Step 3 was written expecting the reversal
  of M1's +28 — "86 option lists move out of `main.py` and the `pending_*` flag closures
  go with them". They did not move: the conversion replaced a *two-line* tail per site
  with a one-to-three-line call, and the three shared helpers cost more than the 79 tails
  saved. Actually relocating the option builders is a genuine refactor of 79 feature
  methods, not the "close to mechanical" conversion Step 3 describes, and doing it under
  the "nothing changes" acceptance criterion would have been reckless. **It is still
  owed** — the natural home is a `gui/menus/` module per feature area, and the natural
  time is after M2, when `ActionMenu` has already pulled the panel's legality out.
- **The nine unconverted sites** need the Step 0.5 decision above before anything can
  move.
- **`_agent_screen_pos` (`main.py:10741`) still ignores pan and zoom**, so on a panned or
  zoomed map every one of these popups opens away from its token. Recorded in M1 Steps
  1–2, untouched here, and now 79 sites wide rather than one — it belongs at the top of
  the cleanup list.

#### Not covered by a test

- **A real display.** Still headless, still synthesized clicks; the noVNC → x11vnc →
  Xvfb → pygame path remains unexercised. One manual pass at
  `http://localhost:6080/vnc.html` after `run.sh` — **done 2026-09-22**, see
  [the manual smoke pass](#the-manual-smoke-pass--done-2026-09-22); it was worth more
  than it was: 79 popups changed hands.
- **75 of the 79 sites individually.** The checks cover one site per *judgement*, not per
  site. The mechanical half is identical at all 79 (the same `options_from_pairs` call),
  so a per-site test would re-prove the same thing 79 times; what is genuinely untested
  is a mis-typed `owner` or `kind` at an individual site.
- **`deadline`.** Still unset, still M5's.

#### What M2 inherits

- Every choice in the game that has a fixed option list is a `Prompt` with an id, an
  owner and a wire projection. M2's `ActionMenu` is the *other* half — the panel buttons
  — and it now has a worked example of the same shape to follow.
- `Action.disabled_reason` (M2) and `Option.disabled_reason` (here) are deliberately the
  same idea: a **rules** string, never an authorization one. No converted site sets it
  yet; the 79 sites all build lists that already omit what is illegal.
- Step 0.3's 87-action inventory is a snapshot from before M0 and M1, exactly as Step
  0.2's 87-prompt inventory turned out to be. Re-derive it.

---

### M2 — The legal-action model

The expensive phase, and the only one with real regression risk.

**Goal**: `ActionMenu.build(app, agent_idx) -> list[Action]` where
`Action{id, label, group, enabled, disabled_reason, expects, economy}`. The panel then
*draws from* that list, and `_handle_events` dispatches by `action.id` instead of by
button identity. *(`economy` was added by M2e, which is the phase bucket 7d exists to
force; see below.)*

**Why it is hard**: in `_draw_combat_panel`, legality and layout are the same code — a
button is legal exactly when the branch that positions it runs. There is also a live
stale-rect hack at the top of the method (every `btn_cbt_*` is parked at `x = -10000`
each frame so an undrawn button cannot capture a click), which is a direct symptom of
this fusion and disappears once availability is data. **It did**, in M2e's last
commit but one.

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
the GUI, so each group needs a manual smoke pass too. *(Done for M2a-M2c on
2026-09-22, and the repeatable half of it is now `tests/test_gui_headless_smoke.py`,
which M2d extended to 20 creature states and six invariants. M2d's and M2e's
**looking** half — the part no assertion covers — are still owed; both need permission
to launch the real GUI.)*

**Explicitly out of scope here**: migrating `action_used` / `bonus_used` /
`attacks_remaining` into C++ (the open `memory/TODO.md` epic *"Turn-economy state → C++"*).
`ActionMenu` can read them from Python today; moving them later changes neither the model
nor the wire format. **Do not bundle it in** — that is exactly the mistake
`COMBAT_REFACTOR_PLAN.md`'s scope rule exists to prevent.

---

### M2a — what was built (done 2026-09-21)

`gui/actions.py` (new, 139 lines) + `tests/test_action_menu.py` (new, 12 checks) +
three new checkpoints in `tests/test_combat_panel.py`. `gui/main.py` is **net −21
lines**. Suite: **149 passed, 1 failed** — the failure is the pre-existing
`test_monk.py`, failing identically before this work (148/1 plus the new suite).

#### What moved

| Step 0.3 § | Buttons | What is now data |
| ---------- | ------- | ---------------- |
| 1 | `pause_resume`, `end_combat` | the Pause/Resume **label** (the row's only state) |
| 3 | `end_turn` | nothing — unconditional, and deliberately still so (below) |
| 9 | `place_terrain`, `drop_concentration`, 3 × `drop_weapon_*` | the concentration guard, the droppable-slot filter, and therefore the n-up row's width |

`ActionMenu.build(app, agent_idx) -> list[Action]` is pure, imports no pygame, and holds
no state. The panel calls it once per frame into `self._action_menu` and three new
helpers turn the result into pixels: `_cbt_btn` (id → widget), `_menu_group` (this
frame's actions in a group), `_draw_action_row` (one equal-width row; an empty row
consumes no vertical space, which is how "not on offer" now reaches the layout in place
of a positioning branch). `_handle_events` dispatches the eight through
`_action_clicked(id, event)`, which consults the menu the panel actually drew.

#### The three decisions worth carrying forward (all three still stand after M2b)

- **D-M2-1 — `enabled` is built but never false.** `widgets.Button` draws exactly one
  way; there is no grey state to render a disabled option into. So an unavailable
  option is *absent*, and `enabled`/`disabled_reason` ride along unused until M4's
  client — the first renderer that can show them. Setting one false today would change
  what the panel draws, which the phase forbids.
- **D-M2-2 — End Turn stays unconditional, including while paused.** The paused refusal
  (and the armed-Beguiling refusal) live in the click handler. They *look* like
  availability and are not: moving them would make the button vanish mid-combat.
  `test_end_turn_is_offered_even_while_paused` pins this down so a later step does not
  "tidy" it.
- **D-M2-3 — the stale-rect guard stays.** It still protects the 103 unconverted
  buttons. For the converted eight it is now redundant, and `_action_clicked` is what
  actually holds; the guard can only be deleted in M2e, when the last button leaves.
  Step 0.3's **F4** (the `btn_cbt_metamagic` dict escapes the guard entirely) is
  therefore still open and is M2e's to close. *(After M2b it protected 92, not 103; after
  M2d, **5**.)* **CLOSED by M2e, 2026-09-22 — the decision is reversed and the guard is
  deleted.** `_action_clicked` is what holds for every button now, so the guard had
  nothing left to protect and F4's hole nothing left to be a hole in.

#### How "structurally identical" was actually proven

The 14 existing checkpoints never reached three of the branches M2a moved: the
`▶ Resume` label, `drop_concentration`, and a drop row with fewer than three slots
(every combatant in the scene has three, so the n-up width arithmetic was untested).
An oracle written *after* an extraction proves nothing about it, so the three
checkpoints were added **first**, the golden regenerated against the old fused code,
and only then was the extraction restored: **17 checkpoints, byte-identical.**

`tests/test_action_menu.py` is the other half — the availability rules with no screen
in the room, which is the payoff the phase was for. Three of its checks drive real
`MOUSEBUTTONDOWN` events through `_handle_events` (M1's `tests/gui_driver.py`), and one
of those, `test_a_click_on_an_unoffered_action_does_nothing`, is the regression M2a
exists to make impossible: a widget parked at a live-looking location whose action is
not on offer must do nothing. **It was vacuous on the first attempt** — the stale rect
was planted on top of End Turn, so the click also advanced the turn and
`_drop_concentration` then acted on a different creature, and the check passed with the
gate removed. It now plants the rect on a probe-verified free strip and is confirmed to
fail against the pre-M2a call site. Worth repeating for every later step: *check that a
negative test fails when you break the thing it guards.*

#### Still manual

None of the above looks at the panel. A **manual VNC smoke pass** was owed for these
eight buttons and for every later M2 group — the suite could prove the rects and the
dispatch, not the appearance. **Closed 2026-09-22** for M2a, M2b and M2c together, and
the assertions it yielded are now `tests/test_gui_headless_smoke.py`. The premise was
half wrong: the obstacle was never headlessness, it was that nothing was *looking*.

---

### M2b — what was built (done 2026-09-22)

Section 6 (`use_portent`, 1 button) and section 4 (10 buttons, the five-way Action
branch). `gui/actions.py` **+97 lines** (`_action`, `_portent`), `gui/main.py` **net
−80**, `tests/test_action_menu.py` 12 → **22 checks**, `tests/test_combat_panel.py`
17 → **20 checkpoints**. Suite: **149 passed, 1 failed** — the pre-existing
`test_monk.py`, failing identically before this work. `test_determinism.py` green.

#### What moved

| Step 0.3 § | Buttons | What is now data |
| ---------- | ------- | ---------------- |
| 4 | `atk_action`, `unarmed`, `dash`, `dodge`, `disengage`, `hide`, `standup`, `prone`, `spell_action`, `nick` | the whole five-way branch: incapacitated/unconscious, spent-Action (and Nick's three-part guard inside it), frightened, the open band, and prone's swap of Stand Up into the fifth column — plus the `⚔ Attack (N)` label |
| 6 | `use_portent` | Diviner + subclass + resource + dice-left, which is also the guard on the section's *heading*, so §6 collapsed to a dice readout and one row |

**How the branch survived the split.** `ActionMenu._action` answers *which buttons*;
`_draw_combat_panel` still runs the same five arms, because each one prints a line of
text ("[Action used]", "Frightened — must Dash") that is display, not an option — and
because `_is_incapacitated` and `mid_sequence_action` are read again by §7, which this
phase has not reached. Three arms are one full-width row; the open band is three rows
named by `_ACT_ROW_ATTACK` / `_ACT_ROW_MOVE` / `_ACT_ROW_SPELL` in `main.py`, the only
place row membership is written down. The menu builds the group **in column order**, so
`_draw_action_row`'s positional layout is correct by construction —
`test_the_open_band_is_built_in_column_order` is what pins that.

`_draw_action_row` grew one parameter, `font`, and §1's hand-rolled two-up row became
its first caller (identical arithmetic: `W // 2 - 2 == (W - 4) // 2` for every `W`).
That is where a good part of the −80 comes from.

#### F3 is closed, and half of it was already vacuous

`btn_cbt_atk_action`'s rect was set at `16839` and drawn only `if _cur_has_weapons` —
the classic invisible-but-clickable shape. It is gone by construction: an action the
menu does not build has no rect set at all. **But that half of F3 could never fire**:
`_cur_has_weapons` was `len(get_agent_weapons(...)) > 0`, and `PlacedAgent.weapons`
defaults to a 3-vector (`battle_map.hpp:302`) which `setAgentWeapons` re-pads to ≥3, so
the test is `3 > 0` for every creature that exists. The predicate is kept in
`ActionMenu._action` because it states the rule the panel meant to state, not because
anything reaches it. **F3's other half — `btn_cbt_atk_bonus`, gated on
`_cur_has_offhand or mid_sequence_bonus` — is real and is still open**; it is bucket
7b, so M2e closes it.

#### F7 — the one place M2b changed what the panel draws *(new finding, and it is a fix)*

With combat active and **nobody on turn** (`_current_agent_idx()` out of range: combat
started with no combatants, or the acting token was removed), the fused code fell
through to the open-band arm and drew **six buttons for a creature that does not
exist** — Unarmed, Dash, Dodge, Disengage, Hide, Go Prone. It reached them because the
arm's only per-creature guard was `_cur_has_weapons` (False out of range, so Attack
alone was suppressed) while the five-up row had no guard at all. Clicking any of them
ran a handler whose `0 <= idx < len(...)` test no-opped — except that Dash/Dodge/etc.
then set `action_used = True` for nobody.

`ActionMenu._action` returns `[]` for an index it cannot read, so §4 is now empty in
that state. This is outside the "no behaviour change" rule and was **verified by
capture, not asserted**: the old and new panels were driven into the state side by side
before the change was accepted. **Checkpoint 19** pins the new behaviour and
`test_out_of_range_agent_yields_only_the_creature_free_groups` pins the menu.

#### D-M2-4 — the mid-sequence refusal is a handler rule, like the paused one

Mid-attack-sequence (`action_used` True, `attacks_remaining > 0`, slot `"action"`) the
band stays open for the swings still owed — so Dash, Dodge, Disengage, Hide, Go Prone
and Cast Spell are **drawn**, and the handler's `if not self.action_used:` refuses them
anyway. That gate looks like availability and is not: moving it into `ActionMenu` would
make the whole row vanish in the middle of an Extra Attack. It is D-M2-2's shape exactly,
and `test_dash_is_drawn_mid_sequence_but_the_click_is_refused` pins it.
(Whether drawing a live-looking Dash there is *right* is a separate question, and a
separate item — M2 does not answer it.)

#### The negatives were broken on purpose before being believed

M2a's note said to check that a negative test fails when the thing it guards is broken.
Both of M2b's were:

- `test_stand_up_from_a_stale_rect_does_nothing` — `btn_cbt_standup`'s handler has **no
  gate of its own** (Stand Up costs no action), so availability is the only thing
  standing between a stale rect and a creature standing up it never knocked down. Swap
  `_action_clicked("standup", …)` back to `.clicked(event)` → *"an unoffered Stand Up
  fired from a stale rect"*.
- `test_dash_is_drawn_mid_sequence_but_the_click_is_refused` — replace `if not
  self.action_used:` with `if True:` → *"Dash was honoured with the Action already
  spent"*.

#### Re-derived after M2b

**110 named buttons** (unchanged — M2b deleted none), **118 clickable widgets**
(unchanged), `METAMAGIC_OPTIONS` still 9, `_draw_combat_panel` now **1,781 lines**
(was 1,875 after M2a, 1,896 originally). **18 of the 110 no longer appear in the draw
pass at all** (M2a's 7 + M2b's 11); `grep -n 'btn_cbt_<name>'` stays correct for the
remaining **92**, and a converted button is navigated by its action id in
`gui/actions.py`.

#### Carried into M2c

- **All of D-M2-1/2/3 still stand.** `enabled` is still never false; End Turn is still
  unconditional; the stale-rect guard still protects the 92, and F4 (the
  `btn_cbt_metamagic` dict escapes it) is still M2e's.
- **Dead `_reposition_panel` lines.** `1239-1250` still re-`update()`s `atk_action`,
  `unarmed`, `dash`, `dodge`, `disengage`, `spell_action` (and, from M2a, `end_turn`
  and `end_combat`) on window resize. Harmless — the draw pass sets x/y/w every frame —
  but they are now dead weight for 8 of the 18 converted names. Sweep them when the
  guard goes in M2e, not before; they are a resize path nothing in the suite exercises.
  **Swept 2026-09-22**, with the guard: the whole thirteen-line block is deleted.
- **Manual VNC smoke pass** — owed here for M2a's eight and M2b's eleven; **done
  2026-09-22**, with M2c's 56, and partly automated as
  `tests/test_gui_headless_smoke.py`.

---

### M2c — bucket 7a (done 2026-09-22)

M2c's first commit converts nothing. **78 of the 110 named buttons were drawn by no
checkpoint at all**, and a golden that reads `no` for a button in all 20 blocks cannot
tell whether an extraction preserved its rule or deleted it. So the checkpoints came
first, against the still-fused code — the same order 14–18 took for M2a and M2b, and
the one place M2c would have been most tempted to skip it.

`tests/test_combat_panel.py` **21 → 50 checkpoints** (20 before F8's commit added one);
the golden **2,910 → 6,987 lines**, with **zero deleted lines** — every existing block
came through byte-identical, which is the only reason the extraction that follows can
claim anything. F8's commit had already renumbered the F7 block `19 → 99`, so a new
checkpoint is now always an insertion before it rather than an append after it.
**All 57 of M2c's buttons now read `yes` somewhere.** 22 of the 110 are still dark:
they are exactly the clusters and spatial predicates M2d and M2e own.

#### The bucket boundary, settled

Step 0.3 sized 7a at "~60" without drawing the line. M2c draws it: **7a is a guard that
is flat and independent** — one `if` over (index in range, the action/bonus band, and a
class / subclass / level / resource / feat / condition test), reached by nothing else and
reaching nothing else. 91 names in §7, **56 converted, 35 out** (57 are *covered* — `telekinetic` gets its checkpoints here and its conversion in M2d):

| Out | Count | Why, and who takes it |
| --- | ----: | --------------------- |
| 7b | 2 | `atk_bonus`, `spell_bonus` — layout *and* label depend on `attacks_remaining`. **M2e ☑** |
| 7c | 7 | `long_jump`, `shove_push`, `shove_prone`, `grapple_esc`, `grapple_drop`, `bite_grappled`, `escape_net` — an O(n) scan the panel runs every frame. **M2d** |
| 7d | 2 | `haste_action`, the `metamagic` dict — drawn outside the band on purpose. **M2e ☑** |
| 7e | 23 | six named clusters (duplicity 3, soulknife 2, shadow monk 3, archfey 3, elemental monk 2, Channel Divinity 3), plus the Cunning Action three-up row and the four Glamour Bard buttons nested inside `grant_inspiration`'s own resource test. **M2d** |
| — | 1 | `telekinetic` — one widget, two draw sites. See **F10**. **M2d** |

#### What the coverage work turned up

Three findings, all from states no checkpoint had ever driven the panel into:

- **F8** — a bare `bonus_used` crashed the whole panel for any Draconic Sorcerer L6+
  with an affinity element. Fixed as its own commit, ahead of this one.
- **F9** — Intimidating Presence: the panel says level 10, the engine grants the
  resource at 14.
- **F10** — `btn_cbt_telekinetic` is drawn twice in one pass from two unrelated guards.

#### The trap the checkpoints themselves walked into

The first draft of `_reclass` mutated a combatant's stats in place, and checkpoint 48
(Monk 17) came out with a Cunning Action row that checkpoint 23 (Monk 17, identical in
every other way) did not have. The cause: `initialize_class_resources` only ever *sets*
the sticky feature fields on `Stats` — `has_cunning_action`, `weapon_mastery`,
`can_cast_spell`, `num_attacks`, `feats`, the save proficiencies — and never clears the
previous class's, so checkpoint 36's Rogue was still paying out twelve blocks later.
`can_cast_spell` is the one that really bites: it decides the Bonus Action band's two-up
layout, so a block's **geometry** would have depended on which class the block before it
happened to use.

`_reclass` now restores a field-dict baseline snapshotted right after `_start_combat`
(`Stats` is neither deep-copyable nor copy-constructible, which is why it is a dict and
not an object), and each block is independent of the ones before it. **23 and 48 now
differ only in what 48 exists to show** — `quivering_palm`, the Focus the planting spent,
and the one row of vertical shift that follows. That equality is the check; it was
failing before the fix.

An oracle whose blocks depend on their own order is worth no more than one written after
the extraction. M2d and M2e will both add checkpoints, and both inherit this.

#### What the extraction moved

`gui/actions.py` **+289 lines** (`_bonus`, and `_res`, which answers the "does this
creature have a use of X left" question §7 asks about forty times); `gui/main.py`
**net −730**, `_draw_combat_panel` **1,781 → 1,050 lines**; `tests/test_action_menu.py`
22 → **29 checks**. Suite: **149 passed, 1 failed** — the pre-existing `test_monk.py`,
failing identically before this work. All 50 panel checkpoints **byte-identical**.

Five batches, each proving byte-identity before the next started: the four guards
outside the big band block; the Monk/Barbarian/Warlock band plus Divine Intervention;
the Sorcerer run; Hew-to-Lay-on-Hands plus Grant Inspiration; and the Paladin oaths,
Ranger and the two summons.

**`_draw_action_stack` is the new piece**, and it exists because of a mistake worth
recording: §7 is a *column of one-button rows*, not a grid, and reusing M2b's
`_draw_action_row` for a run laid a Monk's whole band out as a three-up. The two shapes
are one call apart and the error is silent — every availability test still passed. The
golden is what caught it.

Which run a converted button belongs to lives in the six `_BON_RUN_*` tuples in
`main.py`, the only place it is written down, exactly as `_ACT_ROW_*` does for §4. A run
is a *maximal stretch with no still-fused button between its members*, which is why
there are six rather than one — the clusters M2d owns cut the column into pieces.
`_BON_RUN_SORCERER` contains `boon_of_fate`, `steady_aim` and `war_priest` for that
reason and not because they are Sorcerer features.

#### The band gate, preserved rather than tidied

Most of §7 sits inside one `if not _is_incapacitated and not self.bonus_used:`,
**whatever an individual feature's real action cost is**. `action_surge`'s own comment
says "available anytime"; `corona`, `tireless`, `bastion_of_law`, `divine_intervention`
and the three Paladin capstones are Actions, not Bonus Actions. Spending the Bonus
Action hides all of them today. Checkpoint 03 has always recorded it, and
`test_spending_the_bonus_action_takes_action_surge_with_it` now names it. Whether the
panel is *right* is a separate question and a separate item; M2c does not answer it.
The two 7a guards genuinely outside the band — `use_item`, which asks each carried item
what THAT item costs, and `extinguish`, which costs an Action — are the reason the
plan's `economy` field cannot be a boolean.

Where the panel repeated `not self.bonus_used` *inside* that block, the repeat is
dropped rather than carried as an always-true expression. `F11`'s dead arm is the one
exception: it is kept in its original shape, because deleting it would read as agreement
that the feature works.

#### Carried into M2d (all discharged)

- **D-M2-1/2/3/4 all still stand.** `enabled` is still never false. The stale-rect guard
  now protects **36**, not 92 — and F4 (the `btn_cbt_metamagic` dict escaping it) is
  still M2e's.
- **`_reposition_panel:1239-1250`** is now dead weight for more of the 74; still sweep it
  in M2e with the guard, not before.
- **F9, F10, F11** are open, and all three are behaviour questions rather than
  conversions. F10 in particular blocks `telekinetic`: one widget cannot serve two
  `Action` ids without a decision about what an id means.
- **The 22 dark buttons are exactly M2d's and M2e's**, so the "add the checkpoint first"
  rule now costs those phases what it cost this one. M2d's clusters are the harder case:
  several are nested *inside* another button's resource test (the four Glamour Bard
  buttons live inside `grant_inspiration`'s `bi`), so a cluster is not a run and cannot
  be converted one button at a time.
- **`tests/test_gui_headless_smoke.py` is a gate now, not a courtesy.** It is cheap, it
  needs no display, and it is the only thing in the suite that would have caught M2c's
  five-up. Run it on every batch. A cluster converted to the wrong shape is exactly the
  failure it is built for, and M2d converts nothing but clusters.

#### Re-derived after M2c

**110 named buttons** (M2c deleted none), `METAMAGIC_OPTIONS` still 9.
`_draw_combat_panel` is now **1,050 lines** (1,896 → 1,875 → 1,781 → 1,050).
**74 of the 110 have left the draw pass** (M2a's 7 + M2b's 11 + M2c's 56);
`grep -n 'btn_cbt_<name>' gui/main.py` stays correct for the remaining **36**, and a
converted button is navigated by its action id in `gui/actions.py`.

#### The manual smoke pass — DONE 2026-09-22

Owed since M2a and discharged here, against a live GUI. It turned out not to need a
browser at all: the container runs Xvfb, so `PIL.ImageGrab.grab(xdisplay=":99")` captures
real frames and `python-xlib`'s XTEST sends real clicks. **"Nothing headless will ever
close this" was wrong** — what the suite cannot do is not headless rendering, it is
*looking*. Worth remembering for M2d and M2e, which owe the same pass.

Driven: a Fighter 5 / Battle Master and a Monk 17 / Open Hand, adjacent, plus a Draconic
Sorcerer 14 with a Fire ancestry. What it confirmed, in the app rather than in a golden:

| | |
| --- | --- |
| §1 (M2a) | Pause ▸ the label flips to `▶ Resume` and back |
| §4 (M2b) | the two-up, the five-up posture row, Cast Spell; Go Prone ▸ the fifth column becomes **Stand Up** in the same slot |
| §4 arm 2 | spending the Action collapses the band to `Action ✓ / [Action used]` |
| §7 (M2c) | **the stacking is right** — Second Wind / Maneuver / Action Surge, and the Monk's five, are separate full-width rows, not an n-up |
| §7 band gate | spending the Bonus Action removes the whole band, Action Surge included, exactly as checkpoint 03 says |
| §7 dispatch | Second Wind heals `3 → 8` and spends its use; the button then correctly stops being offered |
| F8 | the Draconic Sorcerer draws **Dragon Wings (extend)** + **Draconic Resistance (1 SP)** + **Innate Sorcery**. This is the state that used to take the panel down |
| the baseline fix | a clean Monk 17 shows **no** Cunning Action row — the leak that bit the oracle does not exist in the real app either |

And it found **F12**, a cosmetic defect no structural golden could ever see.

#### It is now a suite, not a ritual — `tests/test_gui_headless_smoke.py`

The pass is only worth what it can be repeated for, so the parts of it that are
*assertions* rather than *looking* were written down. `SDL_VIDEODRIVER=dummy` renders
into a real `Surface`, so no display server is involved at all — the Xvfb/XTEST rig was
needed to watch, never to check. Five invariants, swept over thirteen creature states
(chosen for band length and label width, not rules coverage — that is the golden's job):

| Check | What only it can see |
| ----- | -------------------- |
| `test_every_drawn_label_fits_its_button` | **F12.** `Button.draw` centres the label and never clips, so a too-wide one bleeds over its neighbours while every rect stays correct |
| `test_no_two_drawn_buttons_overlap` | the golden records each rect on its own line and is blind to the relationship between them |
| `test_every_drawn_button_lands_inside_the_panel` | a widget drawn over the map or off-screen is unusable, and no availability test would notice |
| `test_a_converted_run_is_stacked_not_columnised` | **the mistake M2c actually made.** Every availability test passed while a Monk's band was laid out as a five-up |
| `test_the_panel_paints_where_it_says_it_does` | reads the framebuffer back, so the four above cannot pass on stale bookkeeping if nothing was painted |

All five were broken on purpose and all five failed correctly, including the two halves
of the F12 pin (a new overflow, and an entry that has silently started to fit).

This is the third leg of M2's stool, and the division of labour is worth stating: the
golden proves the structure did not **change**, `test_action_menu.py` proves the
**rules**, and this proves the result is **usable**. A rect that has been wrong since
before M2a is, to a golden, simply the truth.


### M2d — the clusters and the spatial predicates (done 2026-09-22)

**31 buttons converted**, in six batches, each proving byte-identity before the next
started. `_draw_combat_panel` **1,050 → 768 lines**; `gui/actions.py` **597 → 854**;
`gui/main.py` net **−260**. After it, **105 of the 110 named buttons have left the draw
pass**. The five that have not are exactly M2e's: `atk_bonus` and `spell_bonus` (7b),
`haste_action` and the `btn_cbt_metamagic` dict (7d) — plus `place_terrain`, which the
menu has owned since M2a but whose rect is still placed by hand because it shares a row
with two non-`btn_cbt_*` toggles.

#### The coverage commit, again first

M2d's first commit converts nothing. **21 of M2d's buttons read `no` in all 50
checkpoints** — the clusters are, almost by definition, the states an oracle written
from the outside never drives the panel into. `tests/test_combat_panel.py` **50 → 65
checkpoints**, the golden **6,987 → 9,079 lines, zero deleted**: every block M2a-M2c
wrote came through byte-identical, which is the only thing that lets the extraction
below claim anything.

The fifteen new blocks, and what only they reach:

| | |
| --- | --- |
| 49/50 | Trickery Cleric 6, without and with an illusion on the map — `_my_duplicates` is a SCAN, so the cluster's other two buttons exist only in the second |
| 51 | Life Domain 3 — Preserve Life, the third arm of Channel Divinity |
| 52/53 | Glamour Bard 14, uses in hand then windows open: Mantle of Majesty and Unbreakable Majesty are each `a use left OR already running`, and only 53 reaches the second arm |
| 54 | Soulknife 13 — both labels carry the Psionic Energy count |
| 55 | Shadow Monk 17 — two Bonus Actions and a Magic action in one cluster |
| 56/57 | Elemental Monk 6, and the same creature with Attunement running: the label flips to a tick, and that flag is on the CONDITIONS |
| 58/59 | Archfey 6 with a rider chosen, then Archfey 3 with a **stale** rider — 59 is the only block that exercises the clamp |
| 60/61 | Aria holding Skarn: Drop Grapple, then the same hold with a weapon flagged `auto_use_when_grappling` so the Bite appears |
| 62 | Aria netted — Free from Net |
| 63 | **F10 in full**: a Psi Warrior who has also taken the Telekinetic feat, so the one widget is painted at both sites in one pass |

**Only the seven `btn_cbt_metamagic[…]` entries are still dark**, and they are M2e's:
the scene's Sorcerer has learned two of the nine options.

#### What the extraction moved

Six batches: the two Cleric clusters; the Glamour four (which dissolved the Bard
wrapper `bi` and all); the four tail clusters (Soulknife, Shadow, Archfey, Elements);
bucket 7c; the Cunning Action row with the Telekinetic feat site; and, folded into that
last one, the Psi Warrior site.

Three things in `actions.py` are new in kind rather than in volume:

- **`_has_adjacent` and `_grappling_anyone`** — the O(n) scans the panel ran *per
  frame, per button*, now named predicates run once. `_has_adjacent` compares ORIGINS,
  not footprints, so a Large creature is adjacent by its top-left cell; preserved as
  written and noted, because correcting it is a rules change.
- **`fey_rider_index(app, stats)`** — §7's one WRITE during the draw pass. The Steps of
  the Fey rider cycle is five options at L6 and three below it, and the panel clamped a
  stale selection back to 0 on the spot. `actions.py` must not mutate `app`, so the
  clamp is a pure function used for the label, and `main.py` writes it through next to
  the run — the click handler and the engine call both read the raw field.
  `test_the_fey_rider_is_clamped_without_the_menu_writing_it_back` asserts both halves.
- **two ids for one widget** — `telekinetic_feat` / `telekinetic_psi`, resolved by
  `App._CBT_BTN_ALIAS`. See F10 for why the handlers were left alone.

**A cluster is not a run, and the layout tuples say so.** Six `_BON_RUN_*` became
**thirteen**, plus the first two `_BON_ROW_*`: a run is still "a maximal stretch with no
still-fused button between its members", and converting the clusters that CUT the column
adds runs rather than merging them. **They can be merged once 7b and 7d leave** — M2e's
tidy-up, worth one line in its diff and nothing in its risk.

#### The two rows

§7 has exactly two n-up rows and M2d converted both: Jump/Shove/Trip, whose shape is
the adjacency scan (a three-up when something is standing next to you, `Jump` alone at
full width when nothing is — and the narrow arm draws in `font_sm`, as §4's five-up
does), and Cunning Action. That made the *mirror* of M2c's mistake reachable for the
first time, so `tests/test_gui_headless_smoke.py` grew its sixth invariant:
**`test_a_converted_row_is_side_by_side_not_stacked`** — within one `_*_ROW_*` tuple the
drawn members must share a y and a width and differ in x. It was broken on purpose and
failed correctly. The sweep is **13 → 20 creature states**; the new seven are M2d's
clusters plus a grappler, chosen for label width (the Glamour Bard's four are the
longest strings in §7) and because nothing else draws bucket 7c's Drop and Bite at all.
No new F12 overflow appeared: at full width, all of them fit.

`tests/test_action_menu.py` **29 → 46 checks**, one per cluster rule plus the two
findings.

#### Findings

- **F13** — the panel draws a Jump button with nobody on turn. Preserved and recorded;
  see the findings list.
- **F10, twice as bad as recorded** — the feat's constructor is dead code, and the two
  click handlers cross-fire. Also recorded rather than fixed, and the reason M2d
  converted only the draw.

#### Carried into M2e (all discharged except the smoke pass)

- **The five buttons still in the draw pass are 7b + 7d + `place_terrain`**, and 7b/7d
  are the two that force `economy` to be data rather than a flag. M2d added three more
  witnesses for that: Drop Grapple (free), Free from Net (an Action) and Bite (grappled)
  (the Attack action, or mid-multiattack) all sit in §7 and none of them answers to the
  Bonus Action. ☑
- **F4 + the stale-rect guard + `_reposition_panel:1239-1250` are still M2e's,
  together.** The guard now protects **5**, not 36. ☑
- **The seven dark metamagic entries** are the last of the "add the checkpoint first"
  debt. The scene's Cyra has learned Quickened and Seeking; M2e needs the other seven
  learned and affordable before it touches `18193-18240`. ☑
- **The thirteen `_BON_RUN_*` tuples can be merged** once nothing fused separates them.
  ☑ — four.
- **F9, F10, F11, F12, F13 are all open**, and all five are behaviour questions rather
  than conversions. **F10 and F13 fixed by M2e; F9, F11 and F12 are still open**, and
  F14 joins them.
- **The manual smoke pass — the LOOKING half — is owed for M2d.** The suite covers what
  can be asserted; what it cannot do is see. The rig from M2c still works
  (`PIL.ImageGrab.grab(xdisplay=":99")` + XTEST through the container's Xvfb).
  **Still owed, for M2d and M2e both** — it needs permission to launch the GUI.


### M2e — the economy, as data (done 2026-09-22)

**12 buttons converted** — `atk_bonus`, `spell_bonus`, `haste_action` and the nine
Metamagic toggles — plus `place_terrain`'s hand-placed rect, and after them **all 110
named buttons have left the draw pass**. `_draw_combat_panel` **768 → 646 lines**;
`gui/actions.py` **854 → 1,064**; `gui/main.py` net **−91**. Eight commits: one coverage
commit, four conversions, two behaviour changes with their own commits, and a tidy-up.

#### The coverage commit, again first

**65 → 71 checkpoints**, the golden **9,079 → 9,923 lines, zero deleted.** The seven
unlearned `btn_cbt_metamagic[…]` entries were the last of the "add the checkpoint first"
debt, and four other rules of that draw site were dark with them. Bucket 7b had a dark
arm nobody had noticed: the header row is a fixed two-column band, and in 65 blocks no
checkpoint had ever drawn **both** of its columns — Aria has an off-hand and no spells,
Cyra and Brannor have spells and no off-hand.

| | |
| --- | --- |
| 64/65 | a dual-wielding caster, then the same creature mid-sequence in the BONUS slot: the two-up with both columns filled, and `⚔ Bonus (2)` in it |
| 66 | a Sorcerer 7 with all nine options learned and 7 SP to pay for them |
| 67 | two armed — Heightened by radio-select, and Seeking, which stacks rather than radio-selecting |
| 68 | Sorcery Incarnate running: the caption, and the second armed slot that exists only while it is |
| 69 | the same caption with an empty purse — the heading standing over nothing, which is the state the extraction was most likely to get wrong |

#### What `economy` is, and what it is not

`Action` carries `economy` from this phase: one of seven values, each with a witness
already in the suite — `none` (a DM tool), `free` (Drop Grapple, a Portent die), `bonus`,
`action` (Free from Net), `attack` (the Bite, and Nick — paid out of the Attack action's
attacks rather than out of the Action a second time), `reaction` (Misty Escape), and
`varies` (Use Item, which asks each carried item what THAT item costs: a potion is a
Bonus Action and the flask beside it in the same pack replaces an attack).

**Nothing reads it.** The panel's band gate is still the panel's, preserved exactly. It
is here because a remote client cannot lay out an action economy it has to infer from
which section a button arrived in, and because the band-gate note — §7 hides
Action-costing features whenever the Bonus Action is spent — needs somewhere to be fixed
*from*.

§7 is stamped from one table (`actions._BONUS_ECONOMY`) rather than at ninety
construction sites, because the rule is "the Bonus Action, unless this table says
otherwise". The table has three groups: the six the panel already draws outside the band
(bucket 7d itself); the fourteen inside it that carry their own `not action_used` guard;
and the three that cost nothing at all and are in the band's way for no other reason.
**It is a vocabulary, not a rules audit** — an id is absent unless the panel's own guard,
or its own comment, already said otherwise.

#### The two shapes that would not fit an existing helper

- **The economy-band header row is not an n-up.** `_draw_action_row` gives its drawn
  members equal width across the whole column; this row is two fixed columns, and when
  only the spell half is offered the left column stays *empty* rather than the right one
  growing. It also reserves its height when the band is open and neither button is
  offered (checkpoint 13 is a creature with no off-hand and no spells). So it is laid out
  by hand, and the menu answers only which of the two exist and what they read.
- **The Metamagic caption belongs to the section, not to the buttons.** Sorcery Incarnate
  is a property of the creature and affordability a property of each option, so an empty
  purse leaves the heading standing over nothing. `_metamagic` could not answer it, and
  checkpoint 69 exists to prove the split was made correctly. The armed **highlight** is
  styling, which `Action` carries no field for; it follows the tick in the label, so
  "armed" still has exactly one definition and it is the menu's.

#### What left main.py, and what the guard's departure cost

`btn_cbt_metamagic` was nine buttons in a **dict**, and F4 was that the stale-rect guard
iterated `vars(self)` filtering on `isinstance(_btn, Button)` and skipped it entirely.
They are nine ordinary `btn_cbt_metamagic_*` widgets now. `METAMAGIC_OPTIONS` and
`metamagic_offered` moved from `dialogs.py` into `actions.py` to make that possible —
§7 needs both and `actions.py` may not import pygame — with a re-export so the selection
dialog and `test_sorcerer.py` are untouched. That is **F5** arriving at its destination.

The guard itself then went, and `_reposition_panel`'s thirteen-line combat block with
it. **What replaced it is not a better guard but the absence of the problem**: every one
of these buttons is dispatched through `_action_clicked`, which tests the click against
`self._action_menu` — the offer the panel last drew. A stale rect can still exist;
nothing can fire through it. Deleting the guard therefore had a prerequisite, and it is
why F10 had to be fixed inside this phase rather than after it: `telekinetic` was the
last widget on a raw `.clicked()`.

**Thirteen `_BON_RUN_*` tuples become four** — a run is a maximal stretch with no
still-fused button between its members, and nothing fused is left. `_BON_RUN_BAND` is 74
ids and one call; it was derived mechanically from the thirteen it replaces and checked
id for id, and the feature groups survive as its comments. The Archfey rider write — §7's
one write during a draw pass — is hoisted above the run rather than splitting it.

#### Findings

- **F3 and F4 closed**, by construction rather than by a guard. See the findings list.
- **F10 and F13 fixed**, each as its own commit, each a behaviour change with a
  checkpoint written against the old behaviour to be a change *from*.
- **F14, new**: `⚔ Bonus (n)` is drawn and cannot be clicked. F3's shape a third time,
  preserved rather than bundled into a conversion.

#### The manual smoke pass — DONE 2026-09-22, for M2d and M2e together

Owed since M2d and discharged here, against a live GUI on the container's Xvfb. The rig
is no longer rebuilt each time: **`tests/manual_smoke_xvfb.py`**, deliberately *not* in
`run_all_tests.py` — it needs a display, asserts almost nothing, and its output is a
directory of PNGs for a human to look at. Nineteen panels, each cropped out of the root
window, with the real X11 path underneath (`SDL_VIDEODRIVER` is explicitly *unset*; the
one bug in building the rig was `test_combat_panel` setting it to `dummy` at import time
and the pass silently capturing a black screen).

**Clicks are posted into the app's real event loop, not synthesized with XTEST** — the
image has no `python-xlib`, and the X input path is not what M2 changed. Stated rather
than implied.

| | |
| --- | --- |
| 7b, both arms | the two-up with **both** columns filled (`⚔ Bonus Atk` + `✨ Spell`), and the one-up with only the left. The fixed two-column band is visibly a band: with only the spell half offered the LEFT column stays empty rather than the right one growing |
| 7d, the nine | all nine toggles as separate full-width rows, not an n-up |
| 7d, armed | Heightened and Seeking armed **by real clicks** — tick, lighter fill and the pale highlight border, which follows the label rather than a second copy of the rule |
| 7d, the caption | "Sorcery Incarnate: 2 options per spell" standing alone over nothing with an empty purse. This is the split the extraction was most likely to get wrong, and checkpoint 69's subject |
| 7d, Haste | the extra Action still drawn with the Bonus Action spent |
| F10 | **two** buttons, two labels, two colours, two positions — "🌀 Telekinetic Shove" above Second Wind and "Telekinetic Movement" below Action Surge. One click arms one: the log says only the one that was pressed |
| F13 | "Bonus Action" with nothing under it, for nobody on turn |
| F14 | confirmed in the app: `Bonus Action ✓` over `⚔ Bonus (2)` and `✨ Spell`, and clicking either does nothing (`pending_attack_slot` and `pending_spell_slot` unmoved) |
| M2d's owed | the Glamour Bard's four — §7's longest labels, all fitting — the Shadow Monk trio, the Soulknife pair with the Cunning Action row, the Archfey rider, and Drop + Bite (grappled) over the Jump/Shove/Trip three-up |
| the guard's absence | nothing fired from a stale rect across nineteen state changes and five real clicks |

**No new defect.** F12 is plainly visible in every frame (`Disengage` bleeding across
Dodge and Hide in §4's five-up), exactly as `_KNOWN_TOO_WIDE` pins it. Emoji render as
boxes because the image installs no emoji font — an environment fact, and the reason the
oracle is structural rather than pixel.

#### Re-derived after M2e

**110 named buttons, 110 converted.** `BUILT_GROUPS` now names every section that has a
`btn_cbt_*` in it, so **an id `actions.py` does not build is one the panel does not
offer** — a stronger statement than M2a-M2d could make, and the one the guard's deletion
rests on. `tests/test_action_menu.py` **46 → 52 checks**; the suite is **150 pass / 1
fail** (`test_monk.py`, pre-existing and unrelated), with the 71 panel checkpoints
byte-identical across every conversion commit.

#### Carried out of M2

- **F9** (Intimidating Presence gated at 10, the resource granted at 14), **F11**
  (Step of the Wind's Fleet Step arm is unreachable), **F12** (§4's five-up posture row
  is too narrow for three of its labels, pinned in `_KNOWN_TOO_WIDE`) and **F14** are the
  open ones. All four are behaviour questions, and each is its own item.
- ~~**The manual smoke pass's LOOKING half is owed for M2d and M2e both.**~~ **Done
  2026-09-22**, and the rig is checked in — see below.
- **`gui/menus/` relocation** — the panel's rendering helpers were to move out of
  `main.py` after M2. Still owed.

---

### M3 — `GameView`

> **Frozen 2026-09-22 (Step 0, M3).** Four of the six items below **amend** the shape and
> filter table that follow. Implement from this block; the table is orientation once it
> disagrees.

#### D-M3-1 — `seq` is a parameter, not a counter M3 invents

`EventStream` is seam S3 and does not exist in the tree: `grep` finds it in this document
and nowhere in `gui/`. `Prompt.to_wire(seq=0)` (`gui/prompts.py:138`) already set the
precedent — the prompt projection takes the cursor from its caller rather than reaching
for a clock. `GameView` does the same:

```python
build_view(app, viewer, seq: int = 0) -> dict
```

M4 supplies a real cursor when S3 lands. M3 adds no counter, because a counter added here
would be an `EventStream` with one field and no consumer, and S3 would then have to
dislodge it.

#### D-M3-2 — the fog predicate is extracted, not copied a fourth time

The same test — *every cell of a non-party token's footprint is unexplored* — is written
out three times today:

| Site | Purpose |
| ---- | ------- |
| `main.py:16609` (`_draw_agents`) | don't paint the token |
| `main.py:15559` (`_draw_agent_hover_name`) | don't leak the name on hover |
| `main.py:3080` (`_npc_anim_agent_fogged`) | resolve its Move/Announce silently |

`build_view` would be the fourth, and the only one whose drift is a security bug rather
than a cosmetic one. So M3 lands `App._agent_fogged(idx)` first and repoints all three
existing sites at it, **as a no-behaviour-change commit of its own**, with the 71 panel
checkpoints as the oracle — byte-identical, or the extraction is wrong.

This is the one M3 change that touches `main.py`'s draw pass. Everything after it is
additive.

#### D-M3-3 — concealment is a filter rule, alongside fog

**Amends the filter table.** The DM's screen hides an enemy through *two* gates, and the
table names one. `_npc_concealed_from_party` (`main.py:15255`) drops an automated
non-party token that is Hidden, or Invisible with no living party member whose senses
pierce it — the same gate targeting uses. `_draw_agents` and `_draw_agent_hover_name` both
apply it immediately after the fog check.

A `GameView` that applied only fog would render, on a player's canvas, an ambusher the
DM's own console is deliberately not drawing. That is precisely the sentence the table
opens with ("a client can never see something the DM's own render hides"), so the omission
is an error in the table and not a decision. **Both gates apply**, in the draw pass's
order.

#### D-M3-4 — the agent projection is new code, not the save path filtered

**Amends "a filtered projection of what the saves already serialize".** It cannot be.
`_save_agents` (`main.py:12743`) skips every token with `summoner_idx >= 0` or
`removed_from_play` and renumbers what survives — which is exactly why `gui/net/roster.py`
refuses to persist an index at all. Ground rule 5 requires the wire to carry **live**
`BattleMap` indices, so a projection built on the save's numbering would address the wrong
creature the moment a summon is on the map.

`build_view` therefore walks `bm.placed_agents` directly and shares no code with
`_save_agents`. The two disagree about their subject as well as their numbering: the save
wants every field needed to reconstruct a creature, the view wants a band where the save
wants a number.

#### D-M3-5 — omission wins over "verbatim" for terrain, doors and lighting

**Amends `"terrain": …, "lighting": …, "effects": …, // the existing sidecar shapes,
verbatim`.** That line and the table's *"Unexplored cells — omitted entirely"* row cannot
both hold: `_save_terrain` (`main.py:14864`) writes every region, every door with its
`locked` / `lock_dc` / `link_target`, every ladder and its global target. Sent verbatim to
a player, that is the floor plan of the wing they have not entered, including which doors
are locked and where the staples lead — the same class of leak as sending the enemy token,
arriving by a quieter route.

For a non-DM viewer, terrain regions, doors, ladders and light sources are **filtered
against the explored mask** and omitted when no cell of theirs is explored. A DM viewer
gets them verbatim. The byte-level assertion covers map structure as well as agents.

#### D-M3-6 — `viewer` is a `Principal`; the DM-prompt rule costs one predicate

`build_view(app, viewer, …)` takes a `Principal` (`gui/net/roster.py`), not an id, so
`roster.authorize()` is callable on it directly. Entitlement and visibility stay two
checks, as the Identity section requires, and neither is inferred from the other.

The obligation recorded as *"M3 owes one filtering rule (the six renderers)"* discharges
differently than either M2 or the first draft of this block expected, and the difference is
worth recording because it removes a rule rather than writing one.

Prompts do not ride in the `view` envelope at all — only `you.prompt_id` does. And the six
DM-console-only dialogs **never become `Prompt`s**: `grep -n "render=" gui/main.py` finds
thirteen sites, all `"picker"` or `"grid"`, and the bus registers exactly three renderers
(`main.py:659`). `NamePromptDialog`, `GridSpanDialog`, `TeamPickerDialog`,
`MobSelectionDialog` and `SpellSelectionDialog` are all called directly, outside the bus.
Nothing that reaches `you.prompt_id` can therefore be one of them.

So M3 owes **no renderer blocklist**. It owes the gate that was always the right one:

```python
you["prompt_id"] = p.id if roster.authorize(viewer, Action.ANSWER_PROMPT,
                                            PromptTarget(p.id)) else None
```

That is strictly stronger than a blocklist — it is scoped to the *prompt's owner* rather
than to the widget that happens to draw it, it runs through the NN6 chokepoint instead of
beside it, and it cannot rot when a seventh DM dialog is written. A blocklist would have
had to be maintained forever to keep saying what ownership already says.

**M4 still inherits the obligation**, because the `prompt` envelope is where a prompt body
actually crosses the wire, and M4 is the phase that can first send one.


`gui/net/view.py` (new): `build_view(app, viewer) -> dict`.

**Shape** — a filtered projection of what the saves already serialize:

```jsonc
{
  "seq": 1284,                       // EventStream cursor this view is consistent with
  "map":  {"page": "wachterhaus", "cell_px": 70, "cols": 40, "rows": 30, "image": "/map.png?v=…"},
  "fog":  {"explored_runs": [[row,c0,c1], …]},  // row runs, D-M4-2 amended 2026-09-23
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
| DM-authoring prompts | **never shown**, whoever the viewer is. Per D-M1-12 six renderers are DM-console-only — 2 `NamePromptDialog`, `GridSpanDialog`, `TeamPickerDialog`, `MobSelectionDialog`, and `SpellSelectionDialog` at `19363`. They ask for free text, numbers or a catalogue edit, none of which crosses the wire in v1. |

**Test**: `tests/test_gameview.py` — assert a player view of a scenario with an unexplored
enemy contains no reference to that agent anywhere in the serialized bytes. That is the
whole security model of a spectator client, and it deserves a byte-level assertion, not a
field-level one.

#### Landed 2026-09-22

`gui/net/view.py`, and `App._agent_fogged` (D-M3-2) as a separate no-behaviour-change
change ahead of it — the 71 panel checkpoints byte-identical across it, which is what
licensed touching the draw pass at all.

`tests/test_gameview.py`, **13 checks**, registered in `run_all_tests.py` beside the other
oracles. The suite is **151 pass / 1 fail** (`test_monk.py`, pre-existing and unrelated).

Every headline check was run against a deliberately broken projection before being
believed, because a byte-level assertion that cannot fail is worse than none:

| Mutant | Caught by |
| ------ | --------- |
| agent fog + concealment gates removed | `the creature's name reached a player's wire` |
| initiative not cut to the visible set | `initiative names {3}, which no token explains` |
| `_visible()` forced to `True` (map rides verbatim) | `a door behind the fog reached a player` |
| `is_dm` forced to `True` (DM fields ungated) | `the creature's name reached a player's wire` |

**Carried out of M3**: nothing new. `GameView` is a pure read — M4 owes the transport, the
`ANSWER_PROMPT` gate again on the `prompt` envelope (D-M3-6), and the `_pump_net()` fix in
the six blocking modals.

---

### M4 — Transport + spectator client

> **Scoped by Step 0.9 (frozen 2026-09-23).** M4 is **snapshot-only** per D-M4-2: every
> push is a full `view`, coalesced at one per viewer per 250 ms. Envelope 3, the per-viewer
> filtered event stream and the `Move` animation are **M4b**. Read D-M4-1 through D-M4-6
> before writing any of this section's code.

**Server**: one `threading.Thread` running an asyncio loop in-process.
`aiohttp` if a dependency is acceptable; otherwise stdlib `http.server` + a minimal WS
implementation. No networking exists in the tree today, so this is a clean add.

Routes:

| Route | Purpose |
| ----- | ------- |
| `GET /` | the client (static HTML/JS, served from `gui/net/static/`) |
| `POST /join` | join code → **bearer token** (A3) → principal. Never a cookie. |
| `GET /state` | full `GameView` for the authenticated principal |
| `GET /map.png` | the current page's map image, **masked server-side for a player viewer** (D-M4-1): opaque fog over unexplored cells, cached by mask hash; the DM viewer gets it raw, cached by content hash. *(The masking core landed 2026-09-23; the handler is owed with the server.)* |
| `WS /live` | push: **a full `view` per update in M4** (D-M4-2; `{seq, events[]}` deltas are M4b); `{prompt}` when one is addressed to you. **Authenticates by first frame, not by header** (A3) — the browser `WebSocket` API cannot set one. |

Every route goes through one middleware point (A9) that does: `Origin` check
(same-origin against the request's own `Host`, per D-M4-6 — never a configured list), bearer
validation, revocation check, then `authorize()`. Even in M4 — where the only answer is
"yes, you may read your view" — the checks run, so M8 changes the issuer and nothing else.

**Named task: the blocking-modal fix.** Add `self._pump_net()` to the six nested
`while True:` loops listed in the Identity section, or a join lands during
*Generate Dungeon* and hangs until the DM closes the dialog. Per D-M4-3 it pumps the
command queue and **nothing that redraws**, and F3's owed look on a real display is M4's.

**Client**: canvas. Map image + grid + tokens + fog rectangles + initiative list + combat
log, redrawn from each snapshot — **tokens jump rather than walk in M4**. Fog rectangles come
from `fog.explored_runs`, which is live, while `map.image` lags up to 3 s (D-M4-1 as amended):
**the client may not assume the picture and the mask agree**, and a just-earned cell reads as
dark art until the next re-key. Animating
`NpcVisualEvent` `Move` paths the way `_npc_anim_start` does on the DM screen is **M4b**,
because it needs Envelope 3 (D-M4-2). Read-only — no input surface at all in this phase.

**M4b — the event stream and the animation.** Envelope 3 as Step 0.5 specifies it: a
per-viewer *filtered projection* with its own byte-level test, not a `seq` field bolted to
the push. Then the client animates `Move`. Its mutant table is owed on the same terms M3's
was.

#### The masked page image — landed 2026-09-23

D-M4-1's half that needs no socket: `gui/net/mapimg.py`, the `image` field `_map()` never
emitted, and `tests/test_mapimg.py` (**14 checks**, registered beside the other oracles).
Suite **153 pass / 1 fail** (`test_monk.py`, pre-existing and unrelated). The route handler
itself lands with the server — this is the thing it will serve.

`mapimg.py` imports no pygame and no extension, the way `roster.py` does not: it takes a
frozen `PageImage` snapshot (page path, grid lines as **raw image px**, the explored set,
`fog_on`) and renders from that, so the encode happens off the frame thread and the handoff
cannot tear. `view.page_image(app)` is the one place the pygame thread reads it, and it
reuses the `explored` set `build_view` has already paid for.

**The render starts opaque and punches out the explored cells** rather than painting fog
over the unexplored ones. The two differ on the margins — image area outside the outermost
grid lines, and any cell the line lists are too short to describe — and on this page tree
those margins are real: `wachterhaus.png` has 17 px outside the grid on the left and 17 at
the bottom. Punch-out's failure mode is extra fog; paint-over's is a strip of floor plan.

**D-M4-1's acceptance gate, measured in the container** on the largest page in the tree.
First, a correction the measurement forced: this document's example geometry for
`wachterhaus` (`40x30`, `cell_px: 70`) is illustrative and wrong. `analyze_grid()` finds
**98x91 at ~10 px/cell — 8918 cells**, 7.4x the example's cell count, so the gate was
measured against the page as the engine actually sees it.

| Page | Mask | Render | On the wire | Cache hit |
| ---- | ---- | ------ | ----------- | --------- |
| `wachterhaus.png` 1084x1504, 98x91 (3.05 MB raw) | a quarter seen | 63 ms | 0.80 MB | 0.2 us |
| | half seen | 69 ms | 1.32 MB | |
| | fully explored | 95 ms | 2.51 MB | |
| `ChurchOfStAndral.png` 50x44 (0.33 MB raw) | half seen | 20 ms | 0.18 MB | 0.2 us |
| `TestDNDMap.png` 20x16 (0.15 MB raw) | half seen | 15 ms | 0.07 MB | 0.2 us |

**The encode is the whole cost, and the profile is what set the constants:**

- **`compress_level=1`, measured rather than defaulted.** The mask build and the composite
  together are under 5 ms at every exploration level; Pillow's default level 6 spends
  330-430 ms on the same image level 1 encodes in 60-72 ms, for 6% fewer bytes. A route
  that re-encodes on an exploration delta buys the time.
- **A fully-opaque alpha channel is dropped.** Every page in this tree is RGBA with alpha
  255 everywhere: a quarter of the bytes and a sixth of the encode carrying nothing. Art
  that really is translucent keeps its channel, and a test holds that line.
- **Row-run merging was measured and rejected.** Merging adjacent explored cells took 8918
  rectangles to 91 and saved ~3 ms of a ~95 ms render. Not worth the code.
- **The cache hit went from ~1.8 ms to 0.2 us** by memoizing the key on the snapshot. It was
  re-hashing all 8918 explored cells per request *and* per view build.

| Mutant | Caught by |
| ------ | --------- |
| fog composited at `FOG_COL`'s alpha 245 | `cell (2, 0) carries 2 colours` |
| cell geometry multiplied by a screen scale | `the fog starts a px late` |
| fog painted over cells instead of punched out | `margin px (0, 0) was served` |
| the DM's content hash reused as a player's key | `the DM and a player share a key` |

The FOG_COL mutant has a check of its own that states the reasoning rather than the
symptom: it composites the DM's own constant at alpha 245, runs the contrast stretch anyone
reading their own traffic would run, and asserts the floor plan comes back — then asserts
the frozen mask, given identical treatment, stays a single flat value.

**What the measurement cost was not the encode.** The gate D-M4-1 set is passed — 95 ms
worst case, off the frame thread, one render for the whole party. What that decision did not
name is the **download**: the player's `?v=` is the mask hash, so it changed on *every*
newly-explored cell, and each change cost that player a fresh 0.8-2.5 MB fetch of the largest
page. And the same 10 px-cell geometry made `fog.explored` 8918 pairs — 85 KB of JSON on
*every* push, 341 KB/s per viewer at the frozen cadence, against the 1200 pairs D-M4-2 froze
its coalescing rule around.

Both were taken the same day, as dated amendments to the blocks they belong to, and both are
implemented here:

- **The image key lags on purpose** (D-M4-1, amended): at most one re-key per 3 s, always one
  at a turn boundary, and the lag lives in the *published snapshot* so a view never names a
  `?v=` the route cannot serve. `_lag_is_only_fog()` is the invariant as code — same page,
  same fog state, and a mask that has only grown — and it is checked on every publish rather
  than trusted to three remembered cases. A page switch, fog toggled back **on**, and a mask
  that shrank because a save was loaded each publish immediately; the fog-on case is the one
  that would otherwise serve the unmasked page.
- **The mask crosses as row runs** (D-M4-2, amended): `fog.explored_runs`, inclusive
  `[row, col_start, col_end]` spans, row-major and canonical. 8918 pairs become 91 runs; the
  test scene's 49 become 7. Renamed as well as reshaped, because a client written against
  pairs would misread runs in silence and M4's client does not exist yet.

| Mutant (the amendments) | Caught by |
| ----------------------- | --------- |
| fog toggled back on, and the raw render kept its publish | `fog came back up and the unmasked page stayed published` |
| a mask that shrank treated as a lag | `a mask that shrank was lagged` |
| a turn boundary that does not re-key | `a turn boundary must re-key` |
| the lag never expiring | `the cache served the old mask` |
| a run walking one cell past its gap | `[[0, 0, 2], [0, 3, 4], [2, 9, 9]]` |
| rows emitted in arbitrary order | `[[6, 0, 6], [5, 0, 6], …]` |

**One of those mutants survived first time round, and that is the finding worth keeping.** A
run reaching one cell too far *inside* a row passed the whole suite, because the 7x7 explored
block in `test_gameview.py`'s scene is contiguous in every row and never exercises the branch
that closes a run mid-row. `test_row_runs_split_on_a_gap` feeds the encoder a mask with a gap
directly. A byte-level scene is only as good as the shapes it contains.

**And one byte-level probe had to get sharper.** `map.image` puts a 16-char hex key in every
view, and `SECRET_LADDER_TARGET`'s `61` began matching it by luck. That is exactly what that
file's own comment warned about ("a DC of 15 would collide with half the integers in a view"),
so the fix was a more distinctive probe — the targets are now 4281-4286 — and **not** a
narrower search. The checks still read the whole blob.

**Still owed on this route**: the handler itself (ETag / `Cache-Control` off the same key), the
once-per-push-cycle `publish()` call from the pygame thread, and the 6081 port and `aiohttp`
line D1/D2 specify. All three land with the server. If the 3 s lag still moves too many bytes
at a real table, the answer remains tiles, in M4b — never a rawer image.

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
- **Prerequisite, its own item**: `_save_agents` and `_save_combat_state` used to
  truncate-then-rewrite. NN7 turns that from a rare narrow window into a
  100+-times-per-session one. Atomic writes landed **before** NN7, as a standalone bug fix —
  this document's standing rule forbids bundling it into a phase. *(S1, done 2026-09-22 —
  `gui/atomic_io.py`. NN7 may assume both writes are atomic against a process crash; see
  [S1 + S2](#s1--s2--landed-2026-09-22) for what it may **not** assume about power loss.)*
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
