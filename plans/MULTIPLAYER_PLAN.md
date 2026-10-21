# Multiplayer Plan

**Approach: Option B** — spectator + intent submission. The pygame app stays the
DM console *and* the authoritative server; player web clients get a per-player
view and submit coarse-grained intents.

Status: **plan written 2026-09-21**, after `COMBAT_REFACTOR_PLAN.md` R5 closed the
serialization blocker. Phases are M0–M8 below, gated behind **Step 0**.

**As of 2026-09-25: M0–M4 have landed** (M4 as M4a–M4e, plus the between-phase debt in
[`MULTIPLAYER_PLAN_OWED.md`](MULTIPLAYER_PLAN_OWED.md), items 1–8, 10, 11). Players can join on
6081 and *watch* their own fogged board; they cannot act. **M5 is next** and has **not
started**: read [M5 — where it starts](#m5--where-it-starts-surveyed-2026-09-25) before
anything else — it records what the M5 text below does not cover, and proposes the Step 0.12
that has to be agreed and frozen before M5's first line of code.
**2026-09-28: Step 0.12 is frozen** (user: "all approved"); see [the walk](#step-012--the-walk-started-2026-09-28)
for D-M5-1 through D-M5-9. **M5a (reactions over the wire) has landed (`2ed68bd`), and so has
M5b's first commit, D-M5-1 `perform` (`2ade754`). D-M5-2, the action offer, is next**; its
handoff follows "M5b, commit 1 — D-M5-1 landed".
**2026-10-14: M5b–M5d have landed. M5e (the spell pipeline) has started.** Its Step 0 is
frozen (user: "agreed"). M5e.0, the two bug fixes, is committed. **M5e.1 has landed
(committed, 2026-10-14)**; it found two DM-console bugs (F-M5e-9, F-M5e-10) that want their
own commits. Both are now fixed and committed. **M5e.2 has landed (committed,
2026-10-14). M5e.3 has landed (committed, 2026-10-14). M5e.4 has landed (`06b3b6b`,
2026-10-14); M5e is complete.** Read "Handoff — M5e.4 landed", just before M6.
**2026-10-19: M4b.0–M4b.2 are committed. M4b paused** for core-game fixes.
**2026-10-20: M4b resumed. M4b.3 (browser playback and the toggle) has landed, uncommitted.
M4b.4 is next:** read "Handoff — M4b.3 landed", just before M6.

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

> **Amended 2026-09-28, user-agreed (D-M5-5):** `combat` gains `turn_agent`, the agent index
> whose turn it is, or `null` when that agent is not in this viewer's `agents[]`. `turn_idx`
> is unchanged and still indexes the unfiltered order.

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

> **Amended 2026-09-28, user-agreed (D-M5-3):** `submit` may carry `"cancel": true` in place
> of an answer; it cancels the prompt (and, per the nested-prompt rule, re-sends the parent).
> A prompt with `expects:"cell"` may also carry `options` (closed ids, v1 only `"done"`), and
> its submit then carries exactly one of `option` / `cell`. Nothing a client writes is a free
> string.

> **Amended 2026-10-13, user-agreed (M5d manual pass, 7(b)):** the `prompt` frame carries
> `"cancellable": true | false`, always present, default `true`. It is a **display hint**:
> `false` tells the client not to draw Cancel, because the server re-posts that prompt as
> soon as it is cancelled. v1 sets it `false` on the action offer (`kind:"action"`) only.
> The bus still accepts `{cancel:true}` on such a prompt (logged, then re-posted); no
> `not_cancellable` error is added, and the closed `submit` error set is unchanged.
> **Reason:** the offer's Cancel button did nothing visible, and a client heuristic ("the
> prompt whose options include `move`") would break the first time the option set changed.

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

**Amended 2026-09-24 — there is only one run path, and it is the container** (reason: user
decision, this project runs in Linux in the `rpg_map` image and never natively on the
macOS host). The sentence above is retired: a bare `python gui/main.py` on the host is not
a supported deployment and cannot be one — the installed extension is a Linux/py3.12 build
that a host Python cannot import. So the `Dockerfile` pip line is the whole of D1's
dependency story, and the image must be rebuilt when that line changes.

**The soft dependency stays anyway, and its justification changes.** It was justified by
"a machine without `aiohttp`", which no longer exists as a supported case. It is kept
because it is free and because it is what keeps `net/` honest: the guarded import is the
reason `App` has no hard edge against the transport, which is what lets every headless
suite construct an `App` with `self._net = None` and no socket. Nothing in the tree should
be rewritten to *rely* on the absent-aiohttp path being a deployment.

Chosen over stdlib-only and over `websockets`+`http.server` because **A9 requires one
middleware point**, and only a combined HTTP+WS server gives all five M4 routes a single
place to hang the `Origin` → credential → revocation → `authorize()` chain. The plan's
earlier "~60 lines" estimate for a hand-rolled WS understated masking, fragmentation,
ping/pong and the close handshake; none of that is game code, and its failure mode under
remote play is "works at the table, not for the remote player."

**`gui/net/` is imported lazily.** The DM console starts normally when `aiohttp` is absent —
the player server is simply unavailable, logged once at startup. This keeps
`python gui/main.py map.png` working untouched on a machine without the dependency, and
makes the dependency soft on both paths. *(Per the 2026-09-24 amendment above, "both
paths" is now one path plus the headless suites; the laziness is kept for the suites'
sake, not for a host deployment's.)*

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

**Discharged 2026-09-24 — `test_fsync_precedes_replace`, and the paragraph above was half
wrong.** The *durability* is what no test in this tree can observe; the **call** is
observable, and three separate things about it can be wrong while the suite stays green.
`os.fstat` on the descriptor answers all three, because a write-only fd still stats:

- **which file** — `(st_dev, st_ino)` at sync time, compared against the target *after* the
  swap. `os.replace` carries the temp file's inode onto the target, so the file sitting at
  `path` **is** the descriptor that was synced, and a helper that synced the directory (or
  a second handle, or the wrong file) fails the comparison.
- **whether Python had let go of the bytes** — `st_size` counts only what reached the OS, so
  a sync called before `f.flush()` reads short. The doc is sized to outrun the io buffer on
  purpose; at 324 KB a premature sync sees 319 KB, and a one-line doc would have seen the
  whole thing and passed.
- **whether the swap had already happened** — the journal records `fsync` and `replace` in
  order, so a sync moved after `os.replace` (on a reopened handle, which is the plausible
  way to write it wrong) fails on the order alone.

| Mutant | Caught by |
| ------ | --------- |
| `os.fsync(f.fileno())` deleted | `the temp file was not fsynced exactly once: ['replace']` |
| the sync moved above `f.flush()` | `the fsync ran before the flush: 319634 of 324309 bytes` |
| the *directory* synced instead of the file | `the fsync was not on the file descriptor that became the save` |
| the sync moved after the swap | `the fsync must happen before the swap: ['replace', 'fsync']` |

What is still not asserted is unchanged and is the honest remainder: that the platform's
`fsync` reaches the platter, and the deliberately-absent directory sync. Neither is
observable from inside this process, and the trade-off above stands.

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
- **Amended 2026-09-24 — every viewer is served the grid, not the page** (owed item 11;
  reason: measured on the first manual pass). The client stretches the image onto its
  nominal `cols * cell_px` lattice, so a margin around the grid is stretched with the art.
  `TestDNDMap.png` is 1298x1003 with its grid at x 58-1057, y 89-887, and a phone put the
  right-hand column 3.7 cells and the bottom row 1.9 cells from their art. The route now
  crops both renders to the outermost lines (`mapimg.grid_box`), which leaves only the
  spacing jitter between lines (under 3 px on that page). This changes the "raw for the
  DM viewer" rule above: the DM gets the page's own pixels, unmasked, cropped, in the
  page's own mode — a lossless re-encode — and the file's own bytes only when the grid
  already fills it. The DM key is the content hash folded with the line lists, since both
  now decide the bytes. The margin was already masked for a player; now nobody is sent it.
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
2. *(Amended 2026-09-24 — Envelope 1 carries an optional `principal_id` this rule never
   mentioned, and R3's restart case is the one it exists for.)* Only when the credential is
   gone does an explicit `principal_id` claim that principal — **if it names an existing
   principal whose role is `PLAYER`**.
3. Only when neither resolves does the join fall back to matching `display_name`
   **case-insensitively** against existing player principals.
4. No match creates a new principal.

The order matters: two players who both type "Kira" race under name-matching alone, and the
second silently takes a seat the token could have resolved without the DM touching
anything. Name-matching is acceptable as the fallback because R2 already accepts that
anyone holding the code can claim to be Kira, and the DM sees and can reassign every seat
(NN4). `display_name` remains "never a key" (`net/roster.py:73`) for storage and ownership —
this is a join-time hint, not an identity.

**Two limits on the amended step 2, both of them the difference between a re-claim and an
escalation.** A `principal_id` naming the **DM** is not claimable: R2 accepts that a
code-holder can claim to be Kira, not that they can become the DM, and the roster's own seat
is the one principal a join may never resolve to. A `principal_id` naming **nothing** falls
through to step 3 rather than failing — an error that distinguishes "no such seat" from "not
your seat" is an oracle for which ids exist, and Step 0.5's closed `error` set is closed for
exactly this reason. Neither path renames anything it matches (D-M4c-4).

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

## Step 0.10 — M4c/M4d's frozen decisions (frozen 2026-09-24)

User signed off 2026-09-24 on **D-M4c-1** (the seam), on the **M4c/M4d split**, and on
**D-M4-4's `principal_id` amendment**. The rest are write-downs of consequences those three
force, recorded here so M4c does not rediscover them. **Frozen** on the same terms as
Step 0.1 and Step 0.9: changes need a dated amendment with a one-line reason.

### The correction that forced this section

The M4 route table says `GET /state` returns "full `GameView` for the authenticated
principal", and M3 built exactly that: `build_view(app, viewer, seq=0)` at
`gui/net/view.py:71`, byte-level tested. It is tempting to read that as *the route is a
function call*, and the transport skeleton's own docstring encourages it by calling the
remaining routes ones that "add no new machinery".

They do add one. `build_view` reads `app.bm` (`view.py:94`) and `app._fog_active()`
(`view.py:92`) — it is a **pygame-thread reader by construction**, which is precisely why
`view.py` imports the extension and why `server.py` holds no `App`. NN1 forbids the net
thread from calling it. So `GET /state` is not a projection problem, which is solved; it is
a **thread-handoff** problem, which is not. `GET /map.png` only looked free because M4
already paid this cost for it, in `MapImageCache`.

There are two ways to pay it, and they are not equivalent — one of them is also the
machinery two later features need.

### D-M4c-1 — the view crosses the seam on a command queue, not in a cache

**A second cache was rejected.** Mirroring `MapImageCache` — `push_cycle` building one view
per seated principal every 250 ms and publishing an immutable snapshot — makes `/state` a
dict read with no parking, no timeout and no new failure mode. It also builds N views per
cycle whether or not anyone is listening, answers every request up to 250 ms stale, and,
decisively, **leaves D-M4-3's `_pump_net()` with nothing to pump**. The blocking-modal fix
is a *named M4 task*; a design that defers the only machinery it can be built from has moved
M4's work into M5 without saying so.

**The queue, as F1 measured it.** The handler parks on an `asyncio.Future` that the frame
tick resolves through `loop.call_soon_threadsafe`. F1 recorded 0.76 s in flight with the
game thread not ticking, returning on the first `_pump_net()`; F2 recorded the steady-state
cost as "time to the next pump" — ≤16 ms at 60 fps. This is the same object M5's `submit`
needs (F1 says so in as many words: *"this is the shape of every `submit` in M5"*) and the
same object the six blocking modals pump. **It is built once, in M4c, for three callers.**

**Where it lives.** `gui/net/commands.py` — a new module, import-safe without pygame,
without the extension and without `aiohttp`, the way `roster.py` and `mapimg.py` are. It is
neither thread's half: `server.py` holds no `App` and `link.py` holds nothing else, while a
queue is the thing *between* them, which is the same reason `MapImageCache` lives in
`mapimg.py` rather than in either.

**The shape, frozen:**

- `CommandQueue.submit(fn) -> asyncio.Future` — called on the **net thread**, inside its
  running loop. Appends `(fn, loop, future)` to a `collections.deque` and returns the
  future. No lock: `append` and `popleft` are atomic under the GIL, and the queue holds no
  invariant spanning two operations.
- `CommandQueue.pump(app, budget=32) -> int` — called on the **pygame thread**. Pops up to
  `budget` commands, calls `fn(app)`, and schedules the resolution back. Returns how many
  ran, so a caller can tell a drained queue from a capped one.
- **`budget` is a bound, not a tuning knob.** An unbounded drain makes a flood of requests a
  frame-time attack from the one route that has no authentication in front of it. 32 per
  frame is ~1,900 commands/s at 60 fps, which is far past any real table, and the remainder
  waits exactly one frame.

**Three things the obvious implementation gets wrong, and they are the mutant list:**

1. **Resolution must be scheduled, never performed.** The pygame thread may not touch the
   future — F5's rule, for the same reason. `loop.call_soon_threadsafe(resolver)` where
   `resolver` runs **on the net loop** and checks `future.done()` first. A client that
   disconnected or timed out has already cancelled its future, and a bare `set_result` on it
   raises `InvalidStateError` *on the net loop*, where nothing is waiting to catch it.
2. **A command that raises may not kill the frame loop.** `fn(app)` is wrapped;
   the exception is carried to the future via `set_exception` and the route turns it into a
   status. `PermissionError` from `build_view` is the realistic one — a principal whose seat
   was pulled between the middleware and the pump — and it is a 403, not a 500.
3. **A command returns freshly-built data the caller owns.** `build_view` already satisfies
   this: every block is constructed per call and `log` is `list(app.combat_log)`. Returning a
   live `App` structure would hand the net thread a reference into game state and make NN1 a
   matter of what the handler happens not to read. **Stated as an invariant here because the
   type system will not state it**, and tested by mutating the log after the response.

**Serialization happens on the net thread.** The command returns a `dict`; `json.dumps` runs
in the handler. The frame tick pays for the projection and not for the encoding — the same
division `GET /map.png` makes when it runs the 95 ms PNG encode in an executor.

### D-M4c-2 — `GET /state`, and the timeout Envelope 2 has no room for

Authenticated like every other route (it is not exempt), `authorize(VIEW_SESSION)` at the
top, then `await asyncio.wait_for(queue.submit(...), 5.0)`.

**Five seconds, and then a 503.** F1's number, chosen there because a wedged frame loop
should be visible to a client as a hung request rather than a silent stall. Step 0.5's fifth
`error` member `"timeout"` belongs to `submit_ack`; **Envelope 2 is a view and has no error
shape at all**, so the timeout is an HTTP status and not an envelope: `503` with
`Retry-After: 1`. Inventing a `{"t": "view", "ok": false}` would give the one envelope with
a byte-level test a second, untested shape.

**`Cache-Control: no-store`**, and no ETag. A view is per-viewer live state that changes on
every tick; the conditional-request machinery `GET /map.png` earned is exactly wrong here,
where nothing repeats.

**`seq` is 0.** `EventStream` is seam S3 and does not exist; D-M3-1 froze the caller as the
supplier of `seq` and M4c has nothing to supply. M4b's Envelope 3 is where a real cursor
arrives.

**Known, temporary, and named on purpose**: until M4d puts `_pump_net()` in the six blocking
modals, a `GET /state` issued while *Generate Dungeon* is open parks for the full 5 s and
returns 503. That is D-M4-3's whole point arriving one commit late, and it is a wrong answer
rather than a hang — which is why the split is acceptable.

*(Closed 2026-09-24 by M4d. The 503 did not go away and was never going to: D-M4d-3 shows
the authoring **work** after a dialog closes still blocks the frame loop, and must, because
a command reads `app.bm`. What changed is the bound — from as long as a DM reads a dialog to
as long as the carve runs. `test_a_wedged_frame_loop_is_a_503` is unchanged and still green.)*

### D-M4c-3 — the pre-auth exemption skips the 401, and nothing else

The middleware today denies every request without a valid bearer, deliberately: with no
`POST /join`, an exemption list with no members is a hole waiting for a typo. `POST /join`
gives it its first member, and the exemption is narrower than "skip the middleware":

- **The `Origin` check still runs.** D-M4-6 is step 1 and applies to `/join` most of all —
  a cross-origin page that can mint principals is a defacement vector even though A3 stops
  it from reading the response.
- **Verification still runs.** The exemption suppresses the **401**, not the
  `verify_credential` call. This is not a nicety: D-M4-4's step 1 *is* "a live, unrevoked
  credential re-attaches to its own principal", and that is exactly what a successful
  verification of the request's own `Authorization: Bearer` header answers. So the route
  reads `request["principal"]`, where `None` means "not authenticated" rather than "denied",
  and M8 still replaces one function.
- **The list matches `(method, path)` pairs exactly** — never a path prefix, and never a
  path alone. `GET /join` is not a member, and a prefix match is how `/join/../state`
  becomes one. M4d adds `GET /` and whatever shape its static files need, and that shape is
  M4d's decision, not a generalization taken in advance here.
- **An exempt route may not call `_authorize()`**, and `authorize()` already enforces the
  other half: `principal is None` is denied everything, without exception
  (`roster.py:329`).

### D-M4c-4 — what `POST /join` answers, and the one thing it may not do

Envelope 1 is frozen and unchanged. The statuses it does not name:

| Case | Status | Body |
| ---- | ------ | ---- |
| join code accepted | `202` | the `auth` envelope, `ok: true` |
| join code absent or wrong | `403` | `{"v":1,"t":"auth","ok":false,"error":"denied"}` |
| body not JSON, wrong `v`, or `t != "auth"` | `400` | `…"error":"protocol"` |
| too many failed joins from this address | `429` | `…"error":"denied"` (D-M4c-5) |

`"expired"` and `"revoked"` are never emitted by `/join`: a dead credential is not a failure
there, it is step 1 falling through to step 2. They remain the WS's and M6's.

`seated` is `bool(roster.controlled_by(principal.id))` — answerable on the net thread,
because `TokenInfo` exists so ownership can be (Step 0.4). `server_seq` is `0`, per D-M4c-2.

**The join never renames an existing principal.** Accepting the body's `display_name` as an
update is the obvious implementation and it hands anyone holding the join code the ability
to relabel another player's seat — through the *`principal_id`* path, a seat they did not
otherwise touch. Renaming is the DM's, through the roster UI (NN4). `display_name` on a
re-join is a **matching hint and nothing else**, which is what `roster.py:73`'s "never a key"
has said all along.

### D-M4c-5 — the join is rate-limited, because it is the one route with nothing in front of it

The join code is 6 characters of a 31-symbol alphabet — 887,503,681 codes. Unthrottled, an
attacker already on the LAN at 100 req/s has an even chance inside **51 days**, which is a
long weekend more than a lifetime. A9 owes rate limiting and has none; this route is where
the debt comes due.

**Per source address, 10 failed joins per rolling 60 s, then `429`.** A success does not
count against the bucket, so a table typing the code correctly never meets it, and one
player fat-fingering it cannot lock out another. At 10/min the search is ~168 years.

`request.remote` is the address, and **`X-Forwarded-For` is not consulted** — A6/A7 put any
proxy outside this process, and trusting a header a client writes converts the limiter into
a per-attacker bucket. The documented consequence: behind a reverse proxy this degrades to
one global bucket. M7 revisits it; M4c states it.

The existing `denials` counter keeps counting, and this adds nothing to A9's audit log
beyond it. **A9's log is still a counter**, which is the honest description of it.

### The split — M4c and M4d

| | Contents | Testable by |
| - | -------- | ----------- |
| **M4c** | `net/commands.py`, the `/join` exemption, `POST /join` with D-M4-4 as amended, `GET /state` | real socket + stdlib `urllib`, no browser, no display |
| **M4d** | `WS /live`, the client under `gui/net/static/`, `_pump_net()` in the six modals, F3's owed real-display look | the above, plus an Xvfb rig for the look |

M4c holds nothing that needs a browser or a display, which is why the line falls there.
F3's look is a real-display observation and it belongs beside the code it observes.

*(Amended 2026-09-24 — **M4d splits again**, into M4d (the six pump sites + F3's look) and
M4e (`WS /live` + the client). Reason: the temporary 503 above is live in `main`, and the
half that closes it needs neither a browser nor a socket. See
[D-M4d-0](#d-m4d-0--the-split-splits-again).)*

## Step 0.11 — M4d/M4e's decisions (frozen 2026-09-24)

Four questions were put to the user on 2026-09-24 and answered; this section is the
write-down of those answers plus the consequences they force, in the form the other Step 0
sections take. **User signed off 2026-09-24.** Frozen on the same terms as Step 0.1, Step
0.9 and Step 0.10: changes need a dated amendment with a one-line reason.

### D-M4d-0 — the split splits again

*(Amendment to Step 0.10's split table, 2026-09-24. Reason: the temporary 503 is live in
`main` today, and the half that closes it needs neither a browser nor a socket.)*

| | Contents | Testable by |
| - | -------- | ----------- |
| **M4d** | `_pump_net()` in the six blocking modals, F3's owed real-display look | headless suites + an Xvfb rig for the look |
| **M4e** | `WS /live`, the client under `gui/net/static/`, `GET /` and its assets | the above, plus a real socket |

Step 0.10 drew the line at "needs a browser or a display". That line is still right and
this is a second cut inside M4d, not a redrawing of it: the modal pump is the only piece
that **removes** a known-wrong answer rather than adding a route, and it is the piece with
no dependency on either half of M4e. Landing it first means the window in which
`GET /state` answers 503 because a DM is reading a dialog is measured in one commit.

### D-M4d-1 — the pump goes where a loop waits, never where one works

**The six sites, verified rather than listed from the plan** (`gui/main.py`):

| Modal | `def` | loop | pump |
| ----- | ----- | ---- | ---- |
| `_modal_dungeon_pages` | 2817 | 2864 | 2865 |
| `_modal_text_prompt` | 13252 | 13265 | 13266 |
| `_modal_message` | 13293 | 13323 | 13324 |
| `_modal_generate_terrain` | 13335 | 13373 | 13374 |
| `_modal_select_items` | 13925 | 13949 | 13950 |
| `_modal_generate_dungeon` | 14024 | 14104 | 14105 |

*(Line numbers refreshed 2026-09-24 after the pump landed; the `def`/loop pairs this section
was frozen with were the pre-M4d ones and differ by the inserted lines.)*

All six are the **same shape** — `while True:` → `for event in pygame.event.get():` →
render → `self.clock.tick(60)` — which is why this is six identical one-line edits and not
six decisions. A seventh `while True:` at 3119 is `_advance_npc_playback`, which is not a
modal and is not a site.

**The line goes first in the loop body, above `pygame.event.get()`.** A command queued
while the modal was opening then runs on the first iteration, rather than losing a race to
an event that returns out of the loop. Consistent placement across all six is itself worth
something: six lines that differ only in indentation are six lines a reader checks once.

**Through `App._pump_net()`, a one-line method.** `run()` calls `net_link.pump_commands(self)`
directly today (`main.py:19999`); seven call sites of one expression is where the plan's own
name for it (D-M4-3 says `_pump_net()`, and so did the spike) stops being a convention and
starts being a method. It gives the rig one thing to observe and the tests one thing to
substitute.

**The rule the six sites are an instance of: the pump belongs in a loop that is *waiting for
input*, and never inside work.** `_modal_generate_dungeon` returns its params and the carve
runs afterwards, outside any loop, announced by a `_modal_message(..., blocking=False)` that
draws one frame and returns. Nothing pumps during the carve, and D-M4d-3 says why that is
correct rather than merely unimplemented.

Note for the reader who goes looking: `_modal_select_items` is called from *inside*
`_modal_generate_dungeon`'s loop (`main.py:14132`, `14142`), so the pump runs at two modal
depths. That is fine — the queue holds no depth and `pump` is reentrant only in the sense
that it is not called from inside a command (D-M4d-4).

### D-M4d-2 — the projection the pump cannot widen, and the one that widens without it

The question a reviewer asks first: **can a command pumped inside a DM modal see a wider
projection than the same command on the frame tick?** For these six, no — and the answer is
a fact, not a hope:

- `build_view` gates on `app._fog_active()` (`view.py:92`), which is False while
  `terrain_editor.active` or `lighting_editor.active` (`main.py:15273`). With fog off,
  `hide_map` is False and a **player's view carries the whole map**.
- Neither editor is a blocking modal. Both are flag-and-handler dialogs driven by `run()`'s
  own loop, so that widening happens on the ordinary frame tick and is reachable through
  `GET /state` in `main` today. It is not M4d's, and M4d does not touch it.
- **The six modals cannot be reached while either editor is open.** `_handle_events`
  gives the editors first pick and `continue`s (`main.py:17889-17908`), swallowing every
  event, so no top-bar menu opens and none of the six entry points (G10) is clickable.

So the pump adds no path to the wide projection. **What it does add is state advancing while
a modal owns the screen** — D-M4-3's named consequence, and exactly what F3's look is for.

**Owed, named, not bundled.** The editor path itself deserves the question `_agent_fogged`'s
Xvfb look already asked of the filter table: *the DM's screen drawing a thing is not licence
to send it.* An editor session is a DM authoring the map, and a player's device showing the
unfogged board for its duration is the floor argument doing more work than it can carry. It
is a decision for M7 or a standalone item, and this plan's standing rule is that no phase
bundles one.

### D-M4d-3 — what the pump does not close, stated before someone measures it

`_pump_net()` in the six modals does **not** make the frame loop continuously pumpable. The
generation work each authoring flow runs after its dialog closes — the terrain carve, the
dungeon build, the per-floor map writes — blocks `run()` for as long as it takes, and
nothing pumps through it.

**That is correct and not a gap.** A command is `build_view`, which reads `app.bm`; running
one mid-carve is a read of the `BattleMap` while it is being rebuilt, which is the C++
invariant NN1's tightening exists to name. The distinction `server.py` already draws — dict
and dataclass reads under the GIL are safe, C++ invariants mid-mutation are not — lands
exactly here.

So the honest claim for M4d is a **change of bound, not a removal**: the 503 window goes
from *as long as the DM reads the dialog* (unbounded; a coffee break is a minute of 503s) to
*as long as the carve runs* (bounded by the work, seconds). `test_a_wedged_frame_loop_is_a_503`
keeps its meaning and stays green, because a wedged frame loop is still a 503 — M4d changes
how often the loop is wedged, not what happens when it is.

### D-M4d-4 — a command may not open a modal

With the pump inside modal loops, a command that opened a modal would open one *from inside*
another one's event loop, re-entering `pygame.event.get()` at a depth the first loop does not
know about. Today every command is `build_view` and the question is theoretical; it is
written down here because the next two callers (D-M4-3's own sites, and M5's `submit`) are
exactly where someone reaches for a confirmation dialog.

**A command is a read that returns freshly-built data** (D-M4c-1, rule 3) **and draws
nothing** (D-M4-3). Opening a modal violates both. Tested by submitting one that tries.

### D-M4d-5 — F3's owed look

`tests/manual_modal_pump_xvfb.py`, on the pattern `manual_fog_xvfb.py` set: real pixels
through pygame → X11 → Xvfb, back via `PIL.ImageGrab`, **not** registered in
`run_all_tests.py` because it needs a display. Its output is PNGs for a human plus the cheap
assertions a screenshot cannot make on its own.

What it has to show, each against its own control, because a rig that only shows absence
proves nothing:

| | With the pump | Control (pump removed) |
| --- | --- | --- |
| a command submitted while the modal is open | runs, future resolves | still pending when the modal closes |
| the frame under the modal | unchanged across the pump | unchanged (the point: the pump is not why) |
| the modal itself | drawn, on top, unperturbed | drawn, on top |

The middle row is F3's actual worry and is the one that needs real pixels: *pumping inside a
modal means a DM authoring modal stops being a quiescent point.* The assertion is that the
screen outside the dialog is byte-identical across a pump that ran a command — state may
advance, the **screen** may not, which is precisely D-M4-3's "pumps the command queue and
nothing that redraws" made observable.

### M4e's decisions, frozen here so M4e does not rediscover them

**D-M4e-1 — the client's assets are explicit `GET` routes, one exact pair each.**
`aiohttp`'s `add_static` registers a *prefix* resource whose `canonical` is the prefix, so a
`PRE_AUTH_ROUTES` membership test against it would exempt the entire subtree — the precise
hazard D-M4c-3 wrote "never a prefix" about, arriving through the router rather than through
a URL. So: `GET /`, `GET /app.js`, `GET /app.css` as real routes, three exact pairs, and
adding a file means adding a line. That friction is the feature.

**This is the commit where path-only matching stops being harmless.** `_is_pre_auth` asks
the router which resource matched, and for a method with no route the router answers `None`
before the pair is ever compared — so a mutant collapsing the pair to a path alone survives
on today's route table. `test_the_exemption_is_a_method_and_a_path` stands up a subclass
carrying a real `GET /join` to make the rule observable; M4e is where a second method on a
path exists for real.

**D-M4e-2 — the credential lives in `sessionStorage`.** A reload keeps the seat; closing the
tab drops it. It is not a cookie, it is never sent automatically, it is scoped to the origin
and the tab — so it adds nothing to the CSRF surface A3's "never a cookie" is about — and its
lifetime matches the credential's own (A5: the signing key is minted in memory at process
start, so a credential cannot usefully outlive the tab by much). `localStorage` was rejected
for storing a longer-lived secret that is usually already dead.

**D-M4e-3 — no `prompt` envelope in M4e.** *(Amendment to the M4 route table, 2026-09-24.
Reason: the client is read-only in M4, and the envelope's gate is worth testing beside the
path that can answer it.)* `WS /live` pushes `view` and nothing else. `you.prompt_id` is
already in the view and already gated by `ANSWER_PROMPT` (`view.py:269`, D-M3-6), so a client
can say *Kira is being asked something* without the body crossing. The body, and D-M3-6's
gate applied a second time with its own byte-level test, move to **M5**, where the submit
path that answers it lands too. M1's prompt sites are not all routed yet, so an M4e test of
that gate would be partly synthetic — which is the other half of the reason.

**D-M4e-4 — the push needs the *reverse* handoff, and it is not `commands.py`.**
`build_view` is a pygame-thread reader, so a push is built on the frame tick — but the frame
tick has to know **who is connected**, and the sockets live on the net thread. That is a
second crossing, in the opposite direction to D-M4c-1's, and `CommandQueue` does not carry
it.

The shape it must have, from F5's one legal push direction (game thread may only
*schedule*: `call_soon_threadsafe` → `ensure_future` → send on the net loop):

- `push_cycle` (`link.py:80`) already owns the cadence — 250 ms coalescing, forced at a
  `(combat_active, round_num, turn_idx)` boundary. The view snapshot joins **there**, on that
  same tick, beside `map_images.publish`.
- It reads a **snapshot of connected principals** published by the net thread, the way
  `MapImageCache` publishes a picture the other way, and builds one view per *connected
  socket* — not per seated principal. This is the thing D-M4c-1 rejected for `/state`
  ("builds N views per cycle whether or not anyone is listening") and it is correct here for
  the reason that rejection turned on: a socket **is** a listener.
- "Never two in flight" is per-connection state on the net thread's side, read through the
  same snapshot: a connection with a send outstanding is skipped this cycle rather than
  queued behind it. A slow client coalesces to the next boundary; it never grows a backlog.
- Late-joiner resync falls out of sending the current snapshot on `prepare`, as the spike
  found (F5) — no separate resync path in M4e.

The snapshot's exact type is M4e's to choose; that it is a published immutable snapshot and
not a lock over the connection table is decided here, because it is the same decision
`MapImageCache` already made and reversing it on one thread is how the seam stops being one.

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
| **M1** ☑ | `PromptBus`; reroute reactions + all **87** prompt sites *(done; six DM-authoring renderers stay DM-console-only by D-M1-12)* | medium | 1–2 weeks | a scriptable, headless-testable DM console |
| **M2** ☑ | Legal-action model out of `_draw_combat_panel` *(M2a–M2e; 110/110 buttons)* | **high** | multi-week | a turn's options as data |
| **M3** ☑ | `GameView` projection + fog filtering | low | ~1 week | per-player state, still local |
| **M4** ☑ | Transport + **snapshot-only** spectator web client (D-M4-2) *(M4a–M4e, 2026-09-23/24)* | medium | ~1 week | **players watch on their own screens** |
| **M4b** | Envelope 3 (per-viewer filtered stream) + `Move` animation, a per-viewer "Animate moves" toggle (D-M5-6b) | medium | ~1 week | the board moves instead of jumping |
| **M5** | Intent submission *(next; see "M5 — where it starts")* | medium → **high**, see below | 1–2 weeks → more | **actual multiplayer** |
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
- ~~**`_agent_screen_pos` (`main.py:10741`) still ignores pan and zoom**, so on a panned or
  zoomed map every one of these popups opens away from its token.~~ **Fixed 2026-09-24**
  as item 2 of [`MULTIPLAYER_PLAN_OWED.md`](MULTIPLAYER_PLAN_OWED.md), and it was worse
  than this line said: `map_scale` starts at the fit-to-window scale, so the anchor was a
  whole cell out on the *untouched* view of any map wider than the viewport, not only on
  a moved one.

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

- ~~**F9**, **F11**, **F12** and **F14** are the open ones.~~ **All four landed
  2026-09-24**, one commit each, as items 3–6 of
  [`MULTIPLAYER_PLAN_OWED.md`](MULTIPLAYER_PLAN_OWED.md), with the two behaviour
  questions (F14's dead button, F11's unreachable arm) decided by the user rather than
  by the implementer. F9 and F11 left the panel golden byte-identical; F12 re-blessed it
  deliberately, in one place, with the diff described in its commit.
- ~~**The manual smoke pass's LOOKING half is owed for M2d and M2e both.**~~ **Done
  2026-09-22**, and the rig is checked in — see below.
- **`gui/menus/` relocation** — **four slices landed 2026-09-24** (item 7 of
  [`MULTIPLAYER_PLAN_OWED.md`](MULTIPLAYER_PLAN_OWED.md)): the 25 post-hit riders, the
  6 defender reactions, the 9 DM authoring menus and the 16 per-feature menus, 56
  builders and 1,764 lines, taking `main.py` from 20,191 to 18,419 — the reversal M1
  Step 3 expected and did not get. `_ask_actor`/`_ask_dm` stayed put, and
  `tests/test_menus.py` now pins that. ~~**Still owed**: the right-click map menu, still
  built inline in `_handle_events`, and the panel's rendering helpers.~~ **Closed
  2026-09-25**: four more slices moved the right-click map menu (`menus/board.py`), the
  panel's action-button prompts (`menus/features.py`), and the panel's ActionMenu
  rendering and On Deck section (`menus/panel.py`). `main.py` is at **17,940**. M2d left
  `_draw_combat_panel` at 1,050 lines; it is now 654, and its body was left in place by
  the user's decision.

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

#### The owed look at `_agent_fogged` — done 2026-09-24

D-M3-2's extraction was licensed by the 71 panel checkpoints going byte-identical across
it, and **the panel is the one region of the frame the fog gate cannot reach**. The three
consequences that gate actually has — a sprite that is not painted, a tooltip that does not
appear, a slide that does not play — had only ever been seen headlessly.
`tests/manual_fog_xvfb.py` is the looking half as a rig, the way `manual_smoke_xvfb.py` is
M2's: real pixels through pygame → X11 → Xvfb, back via `ImageGrab`, cropped to the **map**
rather than the panel. Not in `run_all_tests.py` — it needs a display.

The scene is `test_gameview.py`'s, unchanged and deliberately so: the scene the byte-level
checks read, looked at instead of serialized. Each consequence is checked against its own
control, because a rig that only ever shows absence proves nothing:

| | Fogged (`Skarn`, 9 9) | Control (`Gnasher`, 5 3) |
| --- | --- | --- |
| `_draw_agents` | cell is **one flat colour**, `(33, 33, 37)` | 112 distinct colours |
| `_draw_agent_hover_name` | hover draws the cursor square and no more | tooltip reads `Gnasher` |
| `_advance_npc_playback` | Move + Announce drain in **one** frame, `on_done` fired | still sliding after that frame |

The pointer is driven with `pygame.mouse.set_pos` — an SDL warp, which moves SDL's own
mouse state, so `pygame.mouse.get_pos()` (what both hover draws read) agrees. The smoke rig
could only post clicks; this is why the tooltip was reachable at all.

**The finding, and it is not a bug.** The secret door at `(10, 9)` and the ladder at
`(10, 10)` are painted **on top of** the fog on the DM's own screen — plainly visible in
`01_fog_skarn_unpainted.png`, two lit icons in the dark. D-M3-5 omits both from a player's
view. So the projection is **stricter** than the DM's render, which is the safe direction
and needs no change. It is recorded because the filter table's opening sentence — *"a
client can never see something the DM's own render hides"* — is a floor and reads like a
rule: the DM's screen drawing a thing is not licence to send it. `_draw_fog_overlay`
likewise leaves the margins outside the outermost grid lines unpainted, where `mapimg`
renders them opaque — the same direction, and independent confirmation of the margin
finding M4 made from the other side.

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
| `GET /` | the client (static HTML/JS/CSS from `gui/net/static/`), as **three explicit routes and three exact pre-auth pairs** — never `add_static`, whose prefix resource would exempt a whole subtree (D-M4e-1). *(2026-09-24.)* |
| `POST /join` | join code → **bearer token** (A3) → principal. Never a cookie. The one pre-auth route, and the exemption suppresses only the 401 (D-M4c-3). Seat matching is D-M4-4 as amended. *(2026-09-24.)* |
| `GET /state` | full `GameView` for the authenticated principal — built on the **frame tick** and handed back over `net/commands.py`, because `build_view` reads the `BattleMap` (D-M4c-1). *(2026-09-24.)* |
| `GET /map.png` | the current page's map image, **masked server-side for a player viewer** (D-M4-1): opaque fog over unexplored cells, cached by mask hash; the DM viewer gets it raw, cached by content hash. *(Masking core 2026-09-23; route, middleware and server thread 2026-09-24.)* |
| `WS /live` | push: **a full `view` per update in M4** (D-M4-2; `{seq, events[]}` deltas are M4b). **Authenticates by first frame, not by header** (A3) — the browser `WebSocket` API cannot set one. The `{prompt}` envelope moved to M5 with the submit path that answers it (D-M4e-3). *(2026-09-24.)* |

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
*(Landed 2026-09-24 as M4e; the client draws the live mask over the lagging picture in the
server's own fog colour, so the two disagree invisibly rather than wrongly.)*

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

#### The transport skeleton — landed 2026-09-24

All four of the items above, and nothing else: `gui/net/server.py` is the thread, the one
middleware point A9 requires, and `GET /map.png`. `POST /join`, `GET /state`, `WS /live`
and the client add routes to it and no new machinery — which is the test of whether it is a
skeleton or a first draft. **Answered, 2026-09-24**: `POST /join`, `GET /state` and the
client's three files added routes and nothing else; `WS /live` added exactly one thing the
skeleton did not have, and it is the one the skeleton could not have had — the *reverse*
handoff (D-M4e-4), because a push is the frame tick looking for requesters rather than a
requester waiting for the frame tick. `tests/test_mapserver.py`, **8 checks**, registered beside the
other oracles, driving a real `aiohttp` server on a real port with **stdlib `urllib`** — the
Step 0.7 spike's discipline: the exercised path should be the browser's, not the library
talking to itself.

**The middleware is the frozen request order, and it stops at step 5.** `Origin` (A6/D-M4-6,
scheme-less against the request's own `Host`, absent ⇒ allow), then bearer extraction, then
`verify_credential` — which is steps 3, 4 and 5 in one call and returns `None` for all of
them, so a caller never learns which failed. Step 6 is not there: `authorize()` is the one
step a route parameterizes, and putting it in the middleware is how it stops being one.
There is **no pre-auth exemption list**, because `POST /join` does not exist yet and an
exemption list with no members is a hole waiting for a typo.

**Which render a viewer gets is asked of `authorize()`, not of `Role`.** `VIEW_DM_CHANNEL`
is the entitlement whose description is literally "whole map", so the route reads
`is_dm = authorize(principal, VIEW_DM_CHANNEL)` and A8's *no `if viewer == "dm"` branches*
holds in the one place it would have been most tempting to break.

**`?v=` is not read, and that is what fixes the ETag.** The cache always serves the newest
published mask — which can only reveal cells the party has already earned, where honouring
an older `?v=` would mean retaining every mask a client might still hold in order to show it
*more* fog. So the query string is a cache-buster and **the ETag is the key actually
served**. A handler that echoed the request's `?v=` would label bytes the client did not
receive, and every conditional request after it would be answered about the wrong picture.
`Cache-Control: private, no-cache` — `no-cache` means *revalidate*, not *do not store*, and
`immutable` would be wrong however much the `?v=` invites it, because that URL's body
genuinely changes. This is the other half of the 3 s lag's saving: between re-keys a player
spends one conditional request instead of 0.8-2.5 MB.

**Three findings from actually running it.**

1. **A constructed `App` must not bind a port.** `start_player_server()` began life in
   `App.__init__`, and the suite's first run reported `address already in use` four times
   over — every headless test builds an `App` and never runs one. The start moved to
   `run()`, which is also where the frozen user procedure wants it (*the join code and URL
   printed at startup*), and `run()`'s exit now stops it. `__init__` builds an App; `run()`
   starts one.
2. **`wachterhaus` has two geometries, and the gate measured the other one.** The M4 render
   figures above come from `analyze_grid()` — 98x91, ~10 px/cell, 8918 cells. The App does
   not use that for this page: `encounters/wachterhaus_terrain.json` carries
   `manual_grid: {cell_px: 34}`, so the loaded page is **30x43 = 1290 cells**. Both are real
   — a page with no terrain sidecar gets the analyzed grid, and that file is untracked, so a
   clean checkout *is* the 8918-cell case. Re-measured on the authored geometry:

   | | cells | `page_image` | render | on the wire | `explored_runs` |
   | - | - | - | - | - | - |
   | analyzed (no sidecar) | 8918 | — | 95 ms | 2.51 MB | 91 runs |
   | authored (`manual_grid`) | 1290 | 0.37 ms | 92.5 ms | 2.41 MB | 43 runs, 549 B |

   **The encode is the whole cost and it barely knows how many cells there are** — 92.5 ms
   against 95 ms for 7x fewer. So the gate's worst case stands, D-M4-2's run reshape is
   comfortable at either geometry, and the push cycle itself is free: 0.37 ms at four
   pushes a second is 1.5 ms of frame time per second.
3. **The printed URL was `http://172.17.0.2:6081/`, and that is a broken user procedure.**
   The first real launch printed the Docker bridge address, because inside the container
   that genuinely *is* what the routing table answers — and it is reachable from no phone at
   the table. 6081 is **published** to the host, so the address to read out belongs to the
   host and only the host can measure it. `run.sh` now does
   (`ipconfig getifaddr en0`, falling back to `en1` and then to `hostname -I`) and passes it
   as `PLAYER_ADVERTISE_HOST`, which `_lan_ip()` prefers over the routing-table answer. The
   routing-table fallback is kept for any launch that does not come through `run.sh` — not
   for a host deployment, which D1's 2026-09-24 amendment rules out. This is the kind of
   thing the frozen procedure exists to catch: it does not add a step, it makes step 2
   print a URL that works.

**The push cycle** (`net/link.py`) is D-M4-2's cadence with only the image in it so far:
coalesced at `view.PUSH_INTERVAL_MS` (250 ms), forced at a turn boundary, and run after
`_refresh_fog` so the mask it publishes is the one that frame draws. The boundary is detected
by comparing `(combat_active, round_num, turn_idx)` rather than by a hook in the turn
machinery, because that tuple is already the whole answer and a hook is a thing that can be
forgotten at the one call site that matters. The `view` snapshot joins it on this same
cadence when the socket lands.

**Where the code went, and NN3.** `gui/net/server.py` is the net thread's half and holds no
`App`. `gui/net/link.py` is the frame tick's half and holds nothing else — the two functions
that read a live `App` on the pygame thread, for the same reason `view.py` does. Both
started as methods on `App`; at +80 lines `main.py` was going the wrong way, and NN3's *its
net line count should trend down, never up* is not a stylistic preference. What is left in
`main.py` is +24: four state attributes and three call sites (`run()`, the frame loop, the
way out), plus one line in `_set_encounter_base`. That is rewiring, which NN3 permits.

**NN1, and what this server is allowed to hold.** Neither an `App` nor anything reachable
from the map: a `SessionRoster` (plain Python, holds no `BattleMap` by construction — which
is what `TokenInfo` was for) and the `MapImageCache` (the handoff itself). Named honestly:
the roster is *mutated* on the pygame thread while the net thread reads it. Nothing can tear
— these are dict reads under the GIL, not C++ invariants mid-mutation, which is the
distinction NN1's tightening draws — but a request can see a **stale ownership answer** for
the frame between a `Controller ▸` reassignment and the next `sync_tokens`. Liveness, not
safety, and the same window the DM's own screen has. `set_roster()` exists because
`_set_encounter_base` **replaces** `App.roster` rather than mutating it; a server holding the
old one would authenticate against the previous table forever. *(For M6: the replacement
roster mints a new in-memory signing key, so loading a different encounter is a re-join for
everybody — R3's case, arriving a milestone early.)*

**Deployment, as D1/D2 specify**: `aiohttp` on the `Dockerfile`'s pip line, and
`-p 6081:6081` on `run.sh` — published on every interface on purpose, since a phone at the
table has to reach it, while 6080 stays on `127.0.0.1` (S2/A10). D1's soft dependency was
re-checked on an image *without* `aiohttp` and behaves as F7 recorded: one line,
`[net] player server unavailable: No module named 'aiohttp'`, `self._net = None`, and the
app otherwise untouched. *(That check was run against the pre-rebuild image. Per D1's
2026-09-24 amendment it is no longer a deployment being verified — it is the state every
headless suite runs in, which is why the behaviour still matters.)*

| Mutant | Caught by |
| ------ | --------- |
| the `Origin` check removed | `a cross-origin fetch with a good token returned 200` |
| `Origin` compared *with* its scheme | `a same-host https Origin was refused with 403` |
| an absent `Origin` denied | `an anonymous fetch of the page returned 403` |
| any bearer accepted without verifying | `a tampered signature returned 200` |
| `is_dm` hardcoded true | `the player was served the page file — the route is not masking` |
| the ETag echoing the requested `?v=` | `the route echoed the requested ?v= instead of the key it served` |
| `If-None-Match` ignored | `a matching If-None-Match returned 200` |
| `If-None-Match` always matching | `a non-matching If-None-Match was not served` |
| an unpublished page as an empty 200 | `an unpublished page returned 200` |

**Still owed on this route**, and split in two by **Step 0.10 (frozen 2026-09-24)**:

- **M4c** — *(landed 2026-09-24, below.)* `net/commands.py` (the command queue F1 measured,
  which `GET /state`, D-M4-3's `_pump_net()` and M5's `submit` all share), the `POST /join`
  pre-auth exemption, `POST /join` with D-M4-4 *as amended 2026-09-24* and its own mutant
  pass, and `GET /state`. Nothing in it needs a browser or a display.
- **M4d** — *(landed 2026-09-24, below.)* `_pump_net()` in the six blocking modals, and
  F3's owed real-display look. Split out of the item below by **Step 0.11's D-M4d-0**.
- **M4e** — *(landed 2026-09-24, below.)* `WS /live` and the client under
  `gui/net/static/`. Its decisions were frozen in Step 0.11 (D-M4e-1 through D-M4e-4)
  rather than left for it to rediscover, and it spent none of its day rediscovering them.

Read D-M4c-1 through D-M4c-5 before writing any of it; the short version is that `GET /state`
is **not** a call to `build_view` — that function is a pygame-thread reader (`view.py:94`) and
NN1 puts it out of the net thread's reach. A9's audit log is a `denials` counter and nothing
more; rate limiting gets its first implementation in M4c, on `POST /join` only (D-M4c-5).

#### The join and the view — landed 2026-09-24

M4c, as Step 0.10 froze it: `gui/net/commands.py`, the `POST /join` exemption, `POST /join`
and `GET /state`. `tests/test_join.py` (**11 checks**) and `tests/test_state.py`
(**11 checks**), both registered beside the other oracles. Suite **156 pass / 1 fail**
(`test_monk.py`'s `test_deflect_attacks_reduces_physical`, pre-existing and unrelated).

**The queue is the whole of the new machinery**, and it is 120 lines. `CommandQueue.submit`
on the net thread, `pump(app, budget=32)` on the frame tick, resolution scheduled back
through `call_soon_threadsafe`. Import-safe without pygame, the extension or `aiohttp`,
because it is neither thread's half — `server.py` holds no `App` and `link.py` holds nothing
else, so the queue between them belongs to neither. `main.py` grew one attribute and one
frame-loop line; `net/link.py` grew `pump_commands()`, which is the function D-M4-3's six
call sites will call in M4d.

**`server.py` does not import `net.view`, and that is structural rather than tidy.**
`net.view` imports the C++ extension at module scope; a net-thread module that *requires*
the thing NN1 forbids it to touch is a contradiction worth not writing down. So
`build_view` is handed to `PlayerServer.__init__` by `net.link`, which holds a live `App`
already and is the half allowed to. It also made the NN1 check below possible: the test
substitutes its own builder and asks which thread ran it.

**The headline check is about a thread, not a payload.** A handler that called `build_view`
itself would serve a byte-identical view and read the `BattleMap` off the pygame thread on
every request — and *no assertion about the response can see that*.
`test_the_view_is_built_on_the_pumping_thread` injects a builder that records
`threading.get_ident()` and compares it against the pumping thread's, and against the
requesting thread's, so a route that quietly went direct fails on the only evidence there is.

**Two findings from running it.**

1. **A mutant survived, and the reason is a fact about aiohttp worth keeping.** D-M4c-3 says
   the exemption matches `(method, path)` pairs and never a path alone; the obvious check is
   that `GET /join` returns 401. It passes **either way**. `_is_pre_auth` asks the router
   which resource matched, and for a method with no route the router answers `None` before
   the pair is ever compared — so on today's route table, path-only matching is
   *behaviourally identical*. It stops being identical the moment M4d adds `GET /` and its
   static files, which is exactly when a silent hole would open.
   `test_the_exemption_is_a_method_and_a_path` therefore stands up a `PlayerServer` subclass
   that **does** carry a `GET /join`, and requires it to still refuse an anonymous caller.
   The rule now has a test instead of a claim.
2. **Two mutants died illegibly, which is a defect in the checks.** One turned a join into a
   500 and the suite reported `JSONDecodeError` on aiohttp's HTML error page; one tripped a
   bare `assert … == 202` inside a loop. Both are caught, and neither said what broke. The
   fix is in the helpers rather than in the checks: `_body()` asserts the status before it
   parses, and the loop names which iteration failed. A mutant that dies on a stack trace is
   a mutant whose next reader re-derives it.

**The rig grew a frame tick.** `test_mapserver.py`'s `_server` takes `pump=True` and runs
`CommandQueue.pump` on a thread of its own — the test's own thread is blocked in `urlopen`,
which is precisely the deadlock the real frame loop is arranged to avoid. `GET /map.png`'s
eight checks default to `pump=False` and run in exactly the conditions they were written in.

**What `POST /join` mutates, and from where.** `add_principal` now runs on the **net
thread**, which the skeleton's docstring previously said happened only on the pygame thread.
Deliberate: a join routed through the queue would be a join that hangs behind whichever modal
the DM has open, and D-M4c-4 computes `seated` from `controlled_by()` precisely because
`TokenInfo` makes ownership answerable off-thread. `sync_tokens` rebinds `_tokens` rather
than mutating it, so a concurrent `_rebuild_ownership()` iterates a dict nothing will touch
again. The one exposure left is a DM seating a principal by hand in the same instant as a
join, which can make `players()` iterate a dict that grew under it: a 500 on that one join,
and a retry. Hardening the roster needs a lock it does not have, and is written down here
rather than bundled in.

| Mutant | Caught by |
| ------ | --------- |
| the exemption matched by path alone | `GET /join was exempt — the pair collapsed to a path` |
| the exemption skipping the `Origin` check | `a cross-origin join with a good code returned 202` |
| the exemption skipping `verify_credential` | `a live credential did not re-attach to its own principal` |
| the name consulted before the credential | `a live credential did not re-attach to its own principal` |
| name matching made case-sensitive | `'kira' did not match Kira — a second player would take her seat` |
| `principal_id` honoured for any principal | `a join code claimed the DM's seat` |
| an unknown `principal_id` refused instead of falling through | `the join returned 500, not 202` |
| the join renaming the seat it matched | `the join renamed the seat it matched` |
| a successful join spending the limiter's bucket | `successful join 0 returned 429 — a success spent the bucket` |
| the view built on the net thread | `an authenticated /state returned 500` |
| `wait_for` removed | the request never returns — `TimeoutError` at the client |
| `PermissionError` not distinguished from a bug | `a refused viewer got 500, not 403` |
| the cancelled-future `done()` check dropped | `an authenticated /state returned 503` |
| a raising command taking the frame loop with it | `the pump stopped after a command raised` |
| the pump unbounded | `one pump ran 49 commands, not 32` |

**Owed when this was written, and landed below as M4e**: `WS /live` and the client under
`gui/net/static/`. What used to stand here — that a `GET /state` issued while a DM authoring
modal is open parks for the frozen 5 s and returns `503` — is closed by M4d, though not in
the way "closed" usually means: the 503 is still reachable and D-M4d-3 says why it has to be.

#### The blocking-modal fix — landed 2026-09-24

M4d, from Step 0.11. `self._pump_net()` at the top of the six blocking modal loops, and
F3's owed look at what that does to a screen a DM is holding.

- **`App._pump_net()`** (`main.py:19998`), one line of work and seven callers: the frame
  loop, which used to call `net_link.pump_commands(self)` directly, and the six modals. The
  plan has used that name since Step 0.7's spike; this is where it stopped being a
  convention.
- **The six sites**, first-in-the-body and above `pygame.event.get()` (D-M4d-1), at
  `main.py` 2865, 13266, 13324, 13374, 13950 and 14105.
- **D-M4d-4 is enforced, not documented.** `_pump_net` refuses to reenter. Without it, a
  command that opens a modal does not fail — it **spins forever**, which is how the mutant
  pass found out: the first version of the guard's checks hung the suite for the full ten
  minutes instead of failing. The three checks now queue a `QUIT` first, so removing the
  guard makes the suite *fail* rather than *hang*.
- **`tests/test_modal_pump.py`** — 9 checks, registered. Suite **157 pass / 1 fail**
  (`test_monk.py::test_deflect_attacks_reduces_physical`, pre-existing and unrelated; the
  baseline was 156/1).
- **`tests/manual_modal_pump_xvfb.py`** — D-M4d-5's rig, not registered, needs a display.

**The check that would have caught a seventh modal.** `test_every_event_draining_loop_has_a_pump`
reads `main.py` with `ast` and asserts that **every** `while True:` whose body drains
`pygame.event.get()` opens with `self._pump_net()` — six of them, no more and no less. The
rule is what makes the site list a consequence rather than a copy: `_advance_npc_playback`'s
`while True:` (`main.py:3119`) drains a recorded event list rather than pygame's queue, which
is why the count is six.

| Mutant | Caught by |
| ------ | --------- |
| the pump moved below the event drain (all six) | `the modal's first two acts were ['drain', 'pump'], not a pump then a drain` |
| the pump removed from one modal | `_modal_generate_dungeon returned without draining the command queue` |
| the reentrancy guard removed | `a command opened a modal and nothing stopped it` |
| the guard set but never cleared (no `finally`) | `a command may not open a modal or pump the queue (D-M4d-4)` |
| the pump draws one pixel | `the pump changed the screen` |

#### F3's look, and the finding it made

`manual_modal_pump_xvfb.py` observes from **inside a command**, which is the only place the
instant exists: a command runs on the pygame thread, inside `_pump_net`, inside the modal's
own loop. So the rig submits screenshot-taking commands from the net thread and lets the
pump run them. Two frames, back to back inside one open `_modal_message`:

| | What it shows |
| --- | --- |
| A — a bare grab | the dialog, 1,435,200 pixels different from the plain board |
| B — a real `build_view(app, kira)`, then a grab | **identical to A**, whole frame and dialog alike |

So the projection ran, the party's whole state was read across the seam, and not one pixel
moved. That is D-M4-3's *"pumps the command queue and nothing that redraws"* as pixels
rather than as a surface comparison. The control is the mutant: with `_pump_net` stubbed,
the command is still on the deque when the modal closes.

**The finding, and it is neither a bug nor M4d's.** The board behind an open modal is
**saturated black**, not dimmed — 412 distinct colours in the whole frame, all of them in
the dialog. `_modal_message.render()` blits its alpha-170 overlay over the *previous* frame
every iteration, so `0.333^5` of the board survives five frames, which is 0.4%. All six do
this and all six always have; the loops are untouched by M4d. It is recorded because it is
invisible headlessly, because it is the answer to "why is the map not dimly visible in these
PNGs", and because it made the rig's first `drift == 0` weaker than it looked — a whole-frame
comparison of two nearly-black frames. The rig now also asserts the lit region is rich (412
colours) before believing that zero.

It is also worth setting beside D-M4d-2. The DM's own screen shows *nothing* of the board
while one of these modals is open, which is one more reason the filter table's floor — *a
client can never see something the DM's own render hides* — is a floor and not a rule.

#### The push socket and the client — landed 2026-09-24

M4e, exactly as Step 0.11 froze it: `WS /live`, `GET /` and the two files beside it, and the
reverse handoff the push needs. With this the M4 route table is complete and a player at the
table sees the board on their own phone.

- **The client's three files as three routes** (D-M4e-1) — `GET /`, `GET /app.js`,
  `GET /app.css`, and three exact pairs in `PRE_AUTH_ROUTES`. Not `add_static`, whose prefix
  resource has the *prefix* as its `canonical`: one membership test against it exempts
  everything underneath, which is D-M4c-3's "never a prefix" arriving through the router
  instead of through a URL. Adding a file means adding two lines, and the friction is the
  feature. Served `no-store`, because a player running last week's client against this
  week's server is a bug report with no evidence in it.
- **`WS /live`**, pre-auth in the middleware and authenticating itself on the first frame
  (A3). Until that frame verifies, the socket is prepared and *nothing else*: nothing is
  sent, no view is built, and it is not in the connection table. One close code
  (`4401`) for every failure, for the reason `_auth_error` has one shape. `heartbeat=20 s`
  and a 64 KB message cap, the latter because 4 MB of aiohttp default on a route reachable
  before a credential exists is 4 MB an anonymous peer can make the net loop assemble.
- **The reverse handoff** (D-M4e-4) — `_LiveConnections` publishes an immutable tuple of
  connected principals on every change, `link._push_views` reads it on the frame tick and
  builds **one view per connected socket**, and `PlayerServer.push_views` schedules the
  whole cycle in one `call_soon_threadsafe`. F5's direction, unchanged: the game thread
  schedules and never sends. Late-joiner resync is `_live_resync`, which asks the same
  `CommandQueue` `GET /state` asks, so a client connecting mid-combat sees the board now —
  and M4e needs no resync path of its own.
- **`sessionStorage`** (D-M4e-2), every access guarded: a private-browsing tab throws rather
  than returning `null`, and a player who cannot store a credential should still play until
  they reload.
- **No `prompt` envelope** (D-M4e-3). The socket carries `view` and nothing else, and the
  client sends exactly one frame in its life — the auth frame. That count is a registered
  check, so wiring a button fails the suite rather than shipping an ungated submit.
- **Zero lines in `main.py`.** The frame loop already called `push_cycle` and `stop()`
  already released the port, so the entire phase landed in `net/`, `net/static/` and
  `tests/` — which is NN3 arriving at the case it was written for.
- **`tests/test_live.py`** — **17 checks**, registered, driven by a hand-rolled WebSocket
  client over a raw socket. `aiohttp`'s own client would have been five lines and would have
  been the library talking to itself; what a browser does — the upgrade handshake, the mask
  bit on every client frame, the close code — is what these read. Suite **158 pass / 1 fail**
  (`test_monk.py::test_deflect_attacks_reduces_physical`, pre-existing and unrelated; the
  baseline M4d left was 157/1).

**The finding: a socket is one request an hour long.** A5 says the revocation check runs on
every request, and every route in front of this one satisfies that by construction — a
request arrives, the middleware verifies. A connection does not: it authenticates once and
then receives for as long as it stays open, so a DM revoking a credential or unseating a
player would have been a kick that takes effect whenever the player next chose to reconnect.
So `_push_views` re-verifies **per viewer per cycle** and `drop_viewer` closes the socket the
moment it stops verifying — four HMACs a second per player, which is why it is affordable to
put A5 where it belongs rather than where it is cheap. This is not in Step 0.11; it is what
M4e found, and `test_a_revoked_credential_closes_the_socket` is its witness.

**`test_the_exemption_is_a_method_and_a_path` stopped needing its subclass.** Step 0.11
predicted that M4e would be the commit where path-only matching stops being harmless, and it
is — through a route nobody registered. `add_get` registers **HEAD on the same resource**,
whose `canonical` is the same path, so `HEAD /` is a second method on an exempt path: the
pair refuses it (401) and a path alone serves it. The 401 is deliberate and the direction is
the safe one — nothing in the client issues a HEAD — and it makes the rule observable on the
real route table rather than only inside `test_join.py`'s `_AlsoGet`.

**Where "never two in flight" actually lives.** Not in the snapshot: a snapshot read and a
schedule are two operations with a whole 250 ms cycle between them, so a guarantee resting
there would be a race with a comfortable margin. It lives in `_send`, which reads and sets
the flag with no `await` between, on the one loop that touches it. A view arriving while a
send is outstanding is **dropped, not queued** — the next cycle is fresher — and the
snapshot's exclusion of an in-flight connection is the *economy* that keeps the frame tick
from building a view that is about to be discarded.

| Mutant | Caught by |
| ------ | --------- |
| the exemption collapsed to a path alone | `HEAD / answered 200 — the exemption collapsed to a path alone` |
| the first frame's credential trusted rather than verified | `a forged credential: the socket was sent a text` |
| the resync sent on `prepare`, before the first frame | `an unauthenticated socket was sent a text ({"v": 1, "t": "view", …` |
| the in-flight guard dropped | `a second send started while one was in flight — the guard is gone` |
| the credential not re-checked on the push cycle | `a revoked credential kept its socket (closed with None)` |
| an `add_static` mount beside the three routes | `the router holds ['PlainResource', 'StaticResource'] — a prefix resource is a whole subtree` |
| ...and its prefix exempted, which is D-M4e-1's actual hazard | `/static/app.js answered 200 to an anonymous caller` |

**Two of those mutants are worth more than their row.**

*The static mount survived the first pass.* Every check in the file asked what a path
answers, and an `add_static` mount answers **401** for exactly as long as nobody puts its
prefix in `PRE_AUTH_ROUTES` — so the harmless half of the mutant passed 16 checks while
leaving the dangerous half one line away. The answer was not a sharper response check but a
statement of the rule: `test_no_route_is_a_prefix` asserts that **every resource on this
router is a `PlainResource`** and pins the seven canonical paths. Both halves now die, on
different messages, and the route table stops being able to grow a subtree quietly.

*Dropping the in-flight guard hung the suite rather than failing it* — the same way removing
D-M4d-4's reentrancy guard did, and for the same reason: without the guard the second send
does not return a wrong answer, it blocks on the gate the first one is holding. The check
now bounds that `await` with `wait_for` and reports the named message, so the mutant fails in
half a second instead of timing out the container. Twice now, on this seam, a missing guard
has presented as a hang; a check that exercises one should assume that shape.

**The A1–A9 check, run and written down.** M8's section asks for it at the end of *each*
phase and no phase had recorded the result, so M4e is where it stops being an intention.
Five greps over `net/` including `static/`: no cookie anywhere but the comment explaining
why there is none (A3); no `role ==` or `== "dm"` branch outside `roster.py`, where A8 puts
it — the client colours a token by the entitlement it was *granted* (`hp.cur` present) and
never by who it thinks it is; no identity derived from an address (`request.remote` reaches
the limiter and nothing else, and `X-Forwarded-For` is still unread on purpose); no display
name used as a key; and **seven routes, one middleware** — every route on the application
that middleware is constructed with, the socket included. Clean, and the greps are cheap
enough that the next phase has no excuse either.

**Owed, and named rather than bundled:**

- **The client cannot mark whose turn it is.** `combat.turn_idx` indexes the *unfiltered*
  initiative order (`view.py`'s `_combat`, deliberately — a renumbered cursor would mean
  something different everywhere else in the protocol), and the `initiative` list in a view
  is cut to the tokens that view explains. So the active row cannot be resolved client-side,
  and counting rows would mark the wrong creature exactly when a hidden one exists. It needs
  a cursor Envelope 2 does not carry; adding one is an M3-frozen envelope change, so it is
  M4b's or a standalone item. The client shows the round and the order, and marks nothing.
- **The client's lattice is nominal.** `map` carries `cell_px`, `cols` and `rows`, so the
  client draws cell *n* at `n * cell_px`, while the DM console (`_cell_to_screen`) and the
  server-side mask both use the page's **real** grid-line positions. *Corrected
  2026-09-24:* this said an offset grid puts a token "up to one line-spacing" from its art.
  It was worse — the client stretched the **whole page**, margins included, onto the
  lattice, and the first manual pass measured 3.7 cells on `TestDNDMap.png`. Owed item 11
  crops the served image to the grid (D-M4-1, amended), which leaves only the spacing
  jitter; drawing on the real lines is still the same envelope question, same answer.
- **The push serializes on the net loop.** `send_json` is `json.dumps` of a whole view —
  tens of KB on a small page, and unbounded in principle by the terrain cell list — inside
  the loop that also answers `GET /map.png`. It is the same division `GET /state` already
  makes and it has the same ceiling; the PNG encode was moved to an executor when it reached
  95 ms, and this has not been measured at a real table.
- **The client is checked, not run.** Three of its properties are asserted by reading the
  file (sessionStorage, no `localStorage`, one `send`). Nothing in the suite executes the
  JavaScript, so a rendering bug in `app.js` is invisible to `./test.sh` — the same shape as
  F3's owed look, and it wants a browser rather than a display.
- **`_fog_active()` is False while a map-authoring editor is open** (`main.py:15273`), so a
  player's view — and now a player's *push*, four times a second — carries the whole map for
  as long as a DM edits terrain or lighting. Reachable in `main` before M4e and untouched by
  it (D-M4d-2 named it); M4e only makes it arrive faster. M7's or a standalone item.

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

> **Read [M5 — where it starts](#m5--where-it-starts-surveyed-2026-09-25) first.** The text
> below was written on 2026-09-21, before M1–M4 existed, and it describes the *prompt* half of
> M5 only. The survey found that the *turn* half — a player clicking Attack and picking a
> target — has no remote path at all yet, and is the larger piece of work.

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

### M5 — where it starts (surveyed 2026-09-25)

Written at `main` @ `38ea487` plus the uncommitted R4e, suite **161 / 0**, after the user
asked for "a working client up so we can start debugging live-time games". Nothing here is
frozen; the findings are measurements, and **the proposals need the user's agreement before
they become Step 0.12**.

#### What M5 inherits, ready to use

- **The prompt half is built end to end except the wire.** `PromptBus` (`gui/prompts.py`)
  has ids, `owner` principals, liveness, `authorize()` on every answer, a nested-prompt
  stack, `Prompt.to_wire()`, `Response.from_wire()` and a `SubmitResult.to_wire()` whose
  error set is Envelope 4's. Every combat prompt goes through `_ask_actor` / `_ask_dm` (≈82
  call sites across `main.py` and `menus/`), and `_ask_actor` already defaults `owner` to
  the token's controller.
- **The view already says a prompt exists.** `you.prompt_id` rides in every `view`, gated by
  `ANSWER_PROMPT` (D-M3-6, `net/view.py:269`). The body does not (D-M4e-3).
- **The transport reserves the slot.** `WS /live` authenticates on its first frame, and
  `net/server.py:99` already sizes the socket for "from M5, one submit". The submit must be
  decided on the frame tick through `net/commands.py` (Step 0.7 F1) — that queue and its
  future-parking are built and tested for `GET /state`.
- **The engine side of a reaction is already an intent protocol** — `pendingDecision` /
  `submitDecision`, with the engine re-validating the choice.

#### Findings — what the M5 text above does not cover

**F-M5-1 — a turn does not start with a prompt.** It starts with a panel button. The 110
`ActionMenu` actions (`gui/actions.py`) are data since M2, but they are *dispatched* by 112
`self._action_clicked(action_id, event)` tests inside `_handle_events` — each one a pygame
click on a widget rect, with the handler body inline after it. A remote player has no event
and no rect. **M5 needs an id-only dispatch path for an `Action`** — `perform(action_id,
principal)` or similar — that the DM click and the remote submit both call, the way M1 made
`bus.choose` the one route for a menu choice. That is a `main.py` extraction of the M2 kind,
with M2's risk, and the M5 text does not mention it.

**F-M5-2 — target selection is not on the bus at all.** Every `Action` today has
`expects="none"`, and **no prompt anywhere uses `expects` "cell" or "agent"** — every
`_ask_*` site is a `choice`. What happens after Attack/Cast/Move is that the handler arms one
of the **72 `pending_*` flags** and the *next map click* resolves it. For a remote player that
map click has to become a `cell` / `agent` prompt the client answers from its canvas. The wire
already allows it (`expects` is frozen at `choice|cell|agent|none`, and `PromptBus.submit`
validates `cell`/`agent` responses, `prompts.py:452`) — but no site produces one, and the
`pending_*` arms are exactly the state the Risks section warns callbacks close over.

**F-M5-3 — Envelope 4 already has a home for the offer: `kind: "action"`.** It is in the
frozen kind set and nothing produces it. The cheapest honest shape is to project
`ActionMenu.build(app, actor)` onto the bus as a `kind:"action"`, `expects:"choice"` prompt
owned by the token's controller at the top of each step of a player's turn. That reuses
`authorize()`, liveness, first-valid-submission-wins (NN4), `submit_ack` and the frozen
envelope — **no protocol change** — and `Action.enabled` / `disabled_reason` map one-to-one
onto `Option`. *Proposal, not decided.*

**F-M5-4 — the client cannot tell a player it is their turn.** Owed since M4e:
`combat.turn_idx` indexes the *unfiltered* initiative order and the view's `initiative` list is
filtered, so the client marks nothing. That was cosmetic for spectators; **for M5 it is a
blocker**, because the `action` prompt would arrive with no visible reason. The fix is an
Envelope 2 cursor field — an M3-frozen envelope change, so it needs a dated amendment.
Proposed for Step 0.12.

**F-M5-5 — the "one send" check is the tripwire, on purpose.** `tests/test_live.py:659`
asserts `app.js` contains exactly one `.send(`. M5 must change it *deliberately*, to exactly
two frame kinds (auth, submit), in the same commit that adds the gated submit — never by
relaxing it to "at least one".

**F-M5-6 — D-M3-6's gate is owed a second time, on the `prompt` envelope, with its own
byte-level test** (D-M4e-3). A prompt a viewer may not answer is never sent, not sent greyed.

**F-M5-7 — M5 exercises exactly what `COMBAT_REFACTOR_PLAN.md`'s `ReactionArbiter` will
move.** Remote reactions go through `pending_decision_` / `submitDecision`; the R4
amendment of 2026-09-25 folded the attack and cast interrupt flows into `ReactionArbiter` too.
**Recommended order: M5 before `ReactionArbiter`**, so live play shakes reaction bugs out
of the current code with the determinism golden unchanged, and the refactor then moves code
that has been exercised by real submits. `NpcDriver` (R4's next cut) is independent of M5 and
can land either side. *Needs the user's call.*

**F-M5-8 — the stated purpose is debugging live games, and the plan has no tool for it until
M7.** M7 lists "a session log". What makes a live bug reproducible is already half-built:
`RecordingCombat` (`replay_log.txt`) records engine calls, and R5's `<base>_combat.json` sidecar
snapshots engine state. Missing is the *intent* side — which principal submitted what, to
which prompt id, when, with what `submit_ack`. **Proposed: pull a minimal append-only submit
log forward into M5** (principal id, never a display name — A2/A4 still apply), so a reported
bug comes with the intents that led to it. *Proposal.*

**F-M5-9 — animation is not needed to debug.** The M5 text asks human turns to emit
`NpcVisualEvent`s "or remote clients see tokens teleport". With M4's snapshot-only pushes,
tokens jump for NPC turns too, and that is acceptable for a debugging table. **Proposed: leave
it with M4b** and say so, rather than bundling Envelope 3 work into M5.

#### Step 0.12 — M5's pre-code steps *(frozen 2026-09-28)*

| # | Step | Output | Done |
| --- | ---- | ------ | :--: |
| 0.12.1 | **Re-derive the turn surface.** For each of the 110 `ActionMenu` ids: does its handler arm a `pending_*` flag, which one, and what does the follow-up click resolve (cell / agent / none)? Which handlers read `event` beyond "it was a click"? | A table in this file; M5's work order falls out of it, the way Step 0.3's did for M2. *(Done 2026-09-28: see 0.12.1 below.)* | ☑ |
| 0.12.2 | **Decide the offer's shape** (F-M5-3): `kind:"action"` prompt vs anything else. | A frozen D-M5 decision || ☑ |
| 0.12.3 | **Decide the target step's shape** (F-M5-2): one `cell`/`agent` prompt per `pending_*` arm, its owner, and what Cancel does (re-offer the action prompt, per Envelope 4's `parent_id` rule). | A frozen D-M5 decision || ☑ |
| 0.12.4 | **Amend Envelope 2 for the turn cursor** (F-M5-4). | A dated amendment to Step 0.5 || ☑ |
| 0.12.5 | **Decide deadlines and Take over**: default, who may set it, what expiry answers for an `action` prompt (Skip is defined for reactions only). | A frozen D-M5 decision || ☑ |
| 0.12.6 | **Decide the submit log** (F-M5-8) and the M4b split (F-M5-9). | Two decisions, one line each. *(Decided 2026-09-28: D-M5-6a, D-M5-6b.)* | ☑ |
| 0.12.7 | **Name the oracle.** The M5 text's own: a scripted fight played through the bus with simulated network latency matches `test_determinism.py`'s golden byte-for-byte, plus the panel golden for the id-dispatch extraction (F-M5-1). | A test plan with its mutant table || ☑ |
| 0.12.8 | **Decide the order against R4** (F-M5-7). | The user's call, dated. *(Decided 2026-09-28: D-M5-8, M5 first.)* | ☑ |
| 0.12.9 | **Review with the user; freeze.** | Go-ahead, dated || ☑ |

The practical cut that gets a table playing soonest is probably **reactions first** (the
engine protocol exists and every reaction is already a `choice` prompt with an owner), then
the action offer, then the target step — each one landing a playable slice. That ordering is
itself a Step 0.12 decision.

#### Step 0.12 — the walk (started 2026-09-28)

Measured at `main` @ `f9c4385`, suite **161 / 0**. 0.12.1 is a measurement. 0.12.6 and 0.12.8
are **decided by the user, 2026-09-28**. 0.12.2–0.12.5, 0.12.7 and the slice order were
proposals; **the user approved all of them on 2026-09-28, and the whole of Step 0.12 is frozen.** The walk also found a turn surface that is not in the
`ActionMenu` (F-M5-10) and a missing wire form (F-M5-11). Both are proposed below, and their
decisions join 0.12.3.

##### 0.12.1 — the turn surface, re-derived *(done 2026-09-28)*

**Method.** This was an `ast` scan of source text, and nothing was run. It found every `if
self._action_clicked("<id>", event):` inside `_handle_events` and followed the body's callees
four levels deep through `App` methods and `menus/*` functions. At each level it collected
assignments that **arm** a flag (a `pending_*` flag, `arcane_charge_pending`,
`blink_steps_pending` or `jump_overlay_active`, set to anything but a falsy constant), bus
prompts (`_ask_actor` / `_ask_dm` / `prompts.ask`), and reads of `event` or
`pygame.mouse.get_pos`. The raw output was then hand-classified: a flag armed only by a
downstream rider (for example, Cleave after a hit) is recorded as a note, not as the action's
own target step. Because the scan over-approximates by following references as well as calls,
every A and X row below was checked against the handler.

**The count is 110, not 112.** There are 110 dispatch sites and 110 distinct ids, and they
match `ActionMenu`'s 110 buildable ids one to one (the six built in loops were matched by
hand). The earlier grep's 112 included the `def` and a docstring line.

| Class | Meaning | Count |
| --- | --- | ---: |
| **I** | Resolves on the click: no prompt, no target | 57 |
| **C→I** | One or more `choice` prompts (already on the bus), then resolves | 8 |
| **A** | Arms an **agent** pick; the next map click on a creature resolves it | 16 |
| **A\*** | Agent multi-pick, finished with Enter (`mantle`) | 1 |
| **C→A** | Choice prompt(s), then an agent pick | 7 |
| **X** | Arms a **cell** pick | 12 |
| **C→X** | Choice prompt, then a cell pick (`elemental_burst`) | 1 |
| **S** | The spell pipeline: the spell grid and slot/variant choices, then the spell's own geometry | 5 |
| **DM** | A DM tool, never remoted (`pause_resume`, `end_combat`, `place_terrain`) | 3 |

**What falls out:**

- **65 of the 110 need no target step at all** (I + C→I), and End Turn is among them. Once
  F-M5-1's id-only `perform` exists, those 65 are playable remotely with no new prompt shape.
- **No handler reads `event` except as a position.** Four pass `event.pos` and thirteen call
  `pygame.mouse.get_pos()`, and every one of those is only the anchor for a popup menu. The
  F-M5-1 extraction is therefore mechanical: `perform(action_id, principal, anchor=None)`, and
  the 110 `if` bodies move under it unchanged.
- **The target step has two resolvers, not 72.** Every A/X arm is resolved by the single
  `elif` chain at `main.py:16447` (the button-1 map click, which computes `cell` and `hit =
  _agent_at(cell)`), and moves resolve on the drag release (`main.py:16717`). The chain
  already takes a cell and derives the creature from it. That is what D-M5-3 proposes to
  reuse.
- **The spell pipeline is the one hard arm.** `pending_spell_slot` resolves, depending on the
  spell, as: a single creature, N creatures (`spell_num_targets`), an AoE cell, a two-click
  wall (`spell_anchor_cell`), a corpse cell, a door cell (Knock), a creature *or* a cell
  (Dispel), or the Chromatic Orb leap chain (Enter to finish). It is 5 ids, but it is the
  largest slice.
- **Most target picks cannot be cancelled today.** Esc branches exist for about a dozen arms
  (`main.py:16277–16360`: summon, the Duplicity trio, the Chromatic chain, Cleave, Mantle,
  Beguiling, Clairvoyant, Vow, Inspiring Smite, and the spell pick). Every other A/X arm has
  none, `pending_attack_slot` included. Those arms stay live until a valid click, or until
  `_clear_pending_target_picks()` (`main.py:4444`) resets all of them at a turn boundary (the
  L36 fix). A remote player with no Esc and a stuck arm cannot end the step, which is
  F-M5-11.

<details><summary>The 110 rows (line = the dispatch site in <code>main.py</code> @ <code>f9c4385</code>)</summary>

| id | line | class | armed flag | note |
| --- | ---: | :-: | --- | --- |
| `atk_action` | 16914 | C→A | `attack_slot` | weapon choice only when >1 weapon; riders (cleave/sweep/…) may arm follow-up agent picks |
| `nick` | 16917 | A | `attack_slot` |  |
| `unarmed` | 16923 | C→A | `attack_slot / unarmed_type` | Punch · Grapple · Push |
| `dash` | 16930 | I | — |  |
| `dodge` | 16942 | I | — |  |
| `disengage` | 16948 | I | — |  |
| `hide` | 16954 | I | — |  |
| `prone` | 16964 | I | — |  |
| `spell_action` | 16972 | S | `spell_slot` | spell grid + slot/upcast/variant choices, then the spell's own geometry |
| `long_jump` | 16976 | X | `jump_overlay_active` | resolved on MOUSEBUTTONUP, not DOWN |
| `standup` | 16980 | I | — |  |
| `use_portent` | 16992 | C→I | — |  |
| `grapple_drop` | 16994 | I | — |  |
| `use_item` | 16998 | C→A | `use_item` | potion on self resolves immediately; reads event.pos (menu anchor only) |
| `extinguish` | 17000 | I | — |  |
| `escape_net` | 17002 | A | `escape_net` |  |
| `atk_bonus` | 17011 | C→A | `attack_slot` | as atk_action |
| `spell_bonus` | 17018 | S | `spell_slot` |  |
| `shove_push` | 17020 | A | `shove_slot` |  |
| `shove_prone` | 17022 | A | `shove_slot` |  |
| `grapple_esc` | 17024 | I | — |  |
| `telekinetic_feat` | 17026 | A | `shove_slot` |  |
| `hide_bonus` | 17028 | I | — |  |
| `dash_bonus` | 17038 | I | — |  |
| `disengage_bonus` | 17050 | I | — |  |
| `patient_defense` | 17056 | I | — |  |
| `wholeness_of_body` | 17066 | I | — |  |
| `hand_of_healing` | 17076 | A | `hand_of_healing` |  |
| `rage` | 17079 | I | — |  |
| `intimidating_presence` | 17086 | I | — |  |
| `zealous_presence` | 17094 | I | — |  |
| `clairvoyant_combatant` | 17102 | A | `clairvoyant` |  |
| `vow_of_enmity` | 17107 | A | `vow_of_enmity` |  |
| `inspiring_smite` | 17112 | A | `inspiring_smite` |  |
| `avenging_angel` | 17117 | I | — |  |
| `elder_champion` | 17121 | I | — |  |
| `living_legend` | 17125 | I | — |  |
| `magical_cunning` | 17129 | I | — |  |
| `healing_light` | 17136 | A | `heal_light` |  |
| `turn_undead` | 17141 | I | — |  |
| `divine_intervention` | 17153 | S | `spell_slot` |  |
| `radiance` | 17155 | I | — | follow-ups may arm beguiling / bewitching_misty / vitality_target |
| `preserve_life` | 17169 | I | — |  |
| `invoke_duplicity` | 17197 | X | `invoke_duplicity` | places N duplicates, one cell click each |
| `move_duplicity` | 17210 | X | `move_duplicity` |  |
| `swap_duplicity` | 17223 | X | `swap_duplicity` |  |
| `steady_aim` | 17234 | I | — |  |
| `war_priest` | 17249 | A | `attack_slot` |  |
| `bite_grappled` | 17254 | I | — | resolves against the grappled creature; riders may arm cleave/sweep |
| `gwm_hew` | 17266 | A | `attack_slot` |  |
| `blink_steps` | 17270 | X | `blink_steps_pending` |  |
| `martial_arts` | 17277 | A | `attack_slot` |  |
| `flurry_of_blows` | 17282 | C→A | `flurry_target` | rider choice, then per-strike target |
| `second_wind` | 17294 | I | — |  |
| `bm_maneuver` | 17298 | C→A | `rally / feint / attack_slot` |  |
| `one_with_shadows` | 17302 | I | — |  |
| `merge_shadows` | 17309 | I | — |  |
| `action_surge` | 17316 | I | — | EK L15 follow-up arms arcane_charge_pending (cell) |
| `lay_on_hands` | 17320 | A | `lay_on_hands` |  |
| `grant_inspiration` | 17323 | A | `grant_inspiration` |  |
| `mantle` | 17326 | A* | `mantle_active` | multi-pick, Enter finishes |
| `mantle_majesty` | 17331 | S | `spell_slot` | Command, free cast |
| `unbreakable_majesty` | 17335 | I | — |  |
| `beguiling_restore` | 17339 | I | — |  |
| `use_inspiration` | 17343 | I | — |  |
| `sacred_weapon` | 17347 | I | — |  |
| `corona` | 17351 | I | — |  |
| `telekinetic_psi` | 17355 | A | `telekinetic` |  |
| `dread_ambusher` | 17358 | I | — |  |
| `tireless` | 17378 | I | — |  |
| `natures_veil` | 17382 | I | — |  |
| `psychic_veil` | 17386 | I | — |  |
| `psychic_teleport` | 17390 | X | `psychic_teleport` |  |
| `shadow_step` | 17396 | X | `shadow_step` |  |
| `cloak_of_shadows` | 17402 | I | — |  |
| `shadow_arts_darkness` | 17412 | X | `shadow_darkness` |  |
| `fey_effect` | 17418 | I | — |  |
| `steps_of_fey` | 17426 | X | `steps_of_fey` |  |
| `misty_escape` | 17432 | X | `misty_escape` |  |
| `elemental_attunement` | 17438 | C→I | — |  |
| `elemental_burst` | 17442 | C→X | `elemental_burst` |  |
| `quivering_palm` | 17446 | I | — |  |
| `dragon_wings` | 17450 | I | — |  |
| `draconic_resistance` | 17463 | I | — |  |
| `bend_luck` | 17475 | C→I | — | reads event.pos (menu anchor only) |
| `boon_of_fate` | 17479 | C→I | — | reads event.pos (menu anchor only) |
| `tides_of_chaos` | 17483 | I | — |  |
| `innate_sorcery` | 17494 | I | — |  |
| `trance_of_order` | 17509 | I | — |  |
| `bastion_of_law` | 17519 | C→A | `bastion_of_law` | reads event.pos (menu anchor only) |
| `clockwork_cavalcade` | 17523 | I | — |  |
| `revelation_in_flesh` | 17533 | I | — |  |
| `warping_implosion` | 17548 | X | `warping_implosion` |  |
| `wild_magic_extra_action` | 17556 | I | — |  |
| `wild_magic_bonus_cast` | 17565 | S | `spell_slot` |  |
| `wild_magic_teleport` | 17567 | X | `wild_magic_teleport` |  |
| `companion` | 17572 | C→I | — |  |
| `familiar` | 17574 | C→I | — |  |
| `charge_arcane_ward` | 17576 | C→I | — |  |
| `wild_shape` | 17578 | C→I | — |  |
| `step_of_wind` | 17586 | I | — |  |
| `haste_action` | 17673 | I | — |  |
| `place_terrain` | 17689 | DM | — | opens TemporaryTerrainPlacementDialog |
| `pause_resume` | 17698 | DM | — |  |
| `end_turn` | 17700 | I | — | refused while beguiling is armed or paused |
| `end_combat` | 17711 | DM | — |  |
| `drop_concentration` | 17713 | I | — |  |
| `drop_weapon_main` | 17715 | I | — |  |
| `drop_weapon_off` | 17717 | I | — |  |
| `drop_weapon_rng` | 17719 | I | — |  |

</details>

##### Two findings the walk added

**F-M5-10 — a player's turn is also three things the `ActionMenu` does not hold.**
1. **Moving** is a drag of your own token: `MOUSEBUTTONDOWN` on it, `drag_valid` kept up to date
   on motion, then `begin_move(bm, idx, cell, move_type)` on release (`main.py:16717`), with
   OA reactions parked through `pending_decision`. The walk/fly/swim/burrow choice is
   `_move_type_btns`, which is not an action either.
2. **Doors and ladders** open from a click on an empty door or ladder cell with nothing armed
   (`dm.show_door_menu` / `show_ladder_menu`). Those menus are already `_ask_actor` prompts
   owned by the actor; only their entry point is a raw click.
3. **Item pickup** works the same way, through a click on an adjacent cell with items
   (`dm.show_item_pickup_menu`).

Without (1), a remote player cannot move, so M5 is not playable without it.

**F-M5-11 — the wire cannot cancel.** `PromptBus.cancel()` exists and runs `on_cancel`, and
Envelope 4 specifies that cancelling a child re-sends its parent. But the `submit` envelope
carries only `option` / `cell` / `agent`: there is no client form of "Esc". A new frame type
would break F-M5-5's "exactly two" on purpose rather than by design, so the proposal (D-M5-3)
is a closed boolean on `submit`.

##### 0.12.6 — the submit log and the animation *(decided by the user, 2026-09-28)*

- **D-M5-6a — a minimal append-only submit log is pulled forward into M5** (F-M5-8). It
  records one line per submit: the principal **id** (never a display name: A2/A4), the prompt
  id, `kind`, the answer (`option` / `cell` / `agent` / `cancel`), the `submit_ack` result, the
  frame `seq` and a monotonic timestamp. A cancel and a DM take-over are logged as well. The
  log sits beside `replay_log.txt`, so a live bug report can come with the engine calls
  (`RecordingCombat`), the state (`_combat.json`) and the intents that led to it. M7's
  "session log" builds on this rather than replacing it.
- **D-M5-6b — animation stays out of M5 and remains M4b** (F-M5-9). Tokens jump in M5, which
  is acceptable for debugging. **For play, the user wants move animation, as an option people
  can select.** M4b is amended accordingly: the `Move` animation is a **per-viewer setting**
  ("Animate moves", on by default), kept in the client's own storage and never sent to the
  server, because animating is purely a rendering of Envelope 3 events that every viewer
  receives either way. The DM console gets the same toggle for its existing
  `_npc_anim` playback. *The per-viewer reading, the default and the DM-console toggle are
  this document's interpretation; approved by the user at 0.12.9, 2026-09-28.*

##### 0.12.8 — order against R4 *(decided by the user, 2026-09-28)*

- **D-M5-8 — M5 lands before `ReactionArbiter`** (F-M5-7), so real remote submits exercise
  the reaction flows in their current form with the determinism golden unchanged, and R4's
  last cut then moves code that has been played. `NpcDriver` stays independent and can land
  on either side of M5.

##### The frozen decisions *(approved 2026-09-28)*

**D-M5-1 — id-only dispatch (F-M5-1).** Add `App.perform(action_id, principal, anchor=None)`.
The 110 `if self._action_clicked(...)` bodies move under it verbatim, and each click site
becomes `if self._action_clicked(id, event): self.perform(id, DM_PRINCIPAL_ID, event.pos)`.
`perform` re-checks the offer (`_action_menu`, `enabled`) and `authorize()`; a remote submit
cannot reach an id the menu did not build. The oracle is the panel golden plus the
determinism golden, both byte-identical. This carries M2's level of risk, so it goes in its
own slice with nothing else in it.

**D-M5-2 — the offer (0.12.2, F-M5-3).** Take F-M5-3 as written. At the top of each step of a
remotely controlled token's turn (turn start, and after every resolved action, move or
cancel, whenever nothing else is live for that owner), post a `kind:"action"`,
`expects:"choice"` prompt built from `ActionMenu.build(app, actor)`, owned by the token's
controller. Disabled actions are sent with their `disabled_reason`. `GROUP_SESSION` and
`place_terrain` are **never** in a player's offer. Two options are added that are not
`ActionMenu` ids: **Move** (D-M5-4) and **Interact** (doors, ladders, pickup; F-M5-10). The
offer is re-derived after each step rather than patched, which is why no action needs an
"it changed" rule.

**D-M5-3 — the target step and cancel (0.12.3, F-M5-2, F-M5-11).**
- The `pending_*` flags stay as the state. When a flag is armed for a remotely controlled
  actor, a target prompt is posted as its projection: `kind:"target"` when a creature is
  wanted, `kind:"cell"` for a place, **both with `expects:"cell"`**, `parent_id` = the action
  prompt, owner = the controller.
- A submitted cell goes into the **same** resolver chain as the DM's map click, refactored
  from the `elif` at `main.py:16447` into `resolve_pick(cell)`, which computes `hit` itself
  exactly as it does now. The DM's click and a remote submit then cannot disagree, and a
  hidden creature is resolved by the engine's perception rules, not by the client.
  `expects:"agent"` stays in the frozen vocabulary, unused in v1.
- Valid cells ship as the overlays that Envelope 2 already specifies under `you`
  (`reachable` / `aoe` / `targets`), which `net/view.py` does not build yet.
- **Multi-picks** (`mantle`, the Chromatic chain, `invoke_duplicity`, `spell_num_targets`)
  post one target prompt per pick. The one amendment needed: a cell prompt may carry
  `options` (closed ids, here only `"done"`), and a submit carries exactly one of
  `option` / `cell`.
- **Cancel:** `submit` gains `"cancel": true`, a closed boolean with no client string. It runs
  `bus.cancel(id)`, whose `on_cancel` is the existing Esc branch where there is one. Where
  there is none, it is the matching slice of `_clear_pending_target_picks()`, so a cancel
  resets exactly what a turn boundary would. Per Envelope 4, the parent (the action offer) is
  then re-sent. **Owed before M5d:** for each arm without an Esc, confirm that arming spends
  nothing (no Action, slot or pool until resolution). If arming does spend something, a
  cancel must refund it, and that becomes a rules decision rather than a mechanical one. Esc
  on the DM console routes through the same cancel, which gives about 30 arms an Esc they do
  not have today: a behavior change, recorded as such.
- Both changes are one dated amendment to Envelope 4.

**D-M5-4 — movement (F-M5-10.1).** Choosing **Move** posts a `kind:"cell"` prompt carrying
`you.reachable`, with the move mode as options (`walk` / `fly` / `swim` / `burrow`, only
those with speed > 0). The answer calls the same `begin_move` the drag release calls,
factored into `commit_move(idx, cell, move_type)`, so OA reactions park and resume exactly as
they do for the DM. One Move prompt covers one leg, and the offer is re-posted after it, so a
player can move, attack and move again.

**D-M5-5 — the turn cursor (0.12.4, F-M5-4).** Amend Envelope 2 to add `combat.turn_agent`:
the agent index whose turn it is, or `null` when that agent is not in this viewer's filtered
`agents[]` (a hidden enemy's turn must not leak its existence). `turn_idx` stays as it is,
unremapped, for the DM and the engine. The byte-level test: a fogged viewer's `view` during a
hidden NPC's turn carries `turn_agent: null`, and nothing else in the view changes.

**D-M5-7 — deadlines and Take over (0.12.5).**
- **Action and target prompts have no deadline** (`deadline_ms: null`). Expiry never
  ends a player's turn, and the DM is the timeout.
- **Reaction prompts** take a session-wide DM setting, default **60 s**, with expiry answering
  **Skip** as Envelope 4 already says. Only the DM may set it, from the console.
- **Take over:** the DM clicking a panel button or the map during a remote player's turn
  answers the live prompt first. Under NN4 that is first-valid-submission-wins, so the
  player's pending prompt is superseded and their late submit gets `not_live`. Nothing new is
  needed on the wire. The take-over is a line in the submit log.

**D-M5-9 — the oracle (0.12.7).**

| Test | What it pins | Mutant that must die |
| --- | --- | --- |
| panel golden, before vs after D-M5-1 | the extraction moved code without changing it | `perform` skipping the `enabled` re-check |
| scripted fight through the bus, with simulated latency, vs `test_determinism`'s golden | a remote-played fight is the same fight, byte for byte | `resolve_pick` computing `hit` differently from the map click |
| `test_live.py:659`, amended to **exactly two** `.send(` | auth + submit, nothing else | a third send; relaxing it to "≥ 1" |
| prompt gate, byte level (F-M5-6) | a prompt the viewer may not answer is never sent | sending it greyed |
| `turn_agent` fog test (D-M5-5) | a hidden turn does not leak | emitting the raw index |
| cancel re-offers the parent (D-M5-3) | Esc and remote cancel run the same branch | the remote cancel clearing a different field set |
| submit log (D-M5-6a) | one line per submit, principal id only | writing the display name |
| offer excludes DM tools (D-M5-2) | `pause_resume` / `end_combat` / `place_terrain` never reach a player | dropping the `GROUP_SESSION` filter |

**Slice order (proposed).** Every slice ends playable, runs the whole suite, and passes its
mutant table.
- **M5a — reactions over the wire.** The submit path, the `cancel` field, the prompt gate, the
  submit log, `turn_agent` and the two-send tripwire. Reactions are already owned `choice`
  prompts, so a remote player can Shield or take an OA on the DM's turn.
- **M5b — `perform` and the offer.** D-M5-1 on its own first, then D-M5-2, which makes the
  65 I / C→I actions and End Turn playable.
- **M5c — movement** (D-M5-4).
- **M5d — agent and cell picks** for the 37 A / A\* / C→A / X / C→X rows (D-M5-3).
- **M5e — the spell pipeline** (S).
- **M5f — Interact**: doors, ladders, pickup.

A table can play from M5c on, using weapons, moves and features; M5e adds spells.

##### M5a — what landed *(2026-09-28, commit `2ed68bd`)*

Suite **162 / 0** (`test_submit.py` is new), determinism and snapshot unchanged. All
eleven mutants in the table below die.

- **The submit path.** `WS /live` reads `submit` frames after the auth frame. Each one goes
  to a task, so the read loop keeps answering pings. The task queues it on a **second
  `CommandQueue`, `App._net_submits`**, which `run()` drains beside `_handle_events` via
  `net_link.pump_submits` and `_pump_net()` never drains. A submit is input, and its callback
  may open a modal; D-M4d-4 forbids that to a command. `net/submit.py` decides it on the
  frame tick: it checks shape (`parse_submit`: exactly one of `option` / `cell` / `agent` /
  `cancel:true`), then `PromptBus.submit` or the new `PromptBus.cancel_as`, both of which
  go through `authorize()`. The `submit_ack` goes back under a per-socket send lock, so it
  never interleaves with a push. `timeout` leaves the submit queued, and it is decided
  when the loop returns.
- **The prompt envelope's gate (F-M5-6).** `net_link.build_live` sends `[view, prompt]`,
  and it sends the prompt only when `you.prompt_id` names it, which is the `ANSWER_PROMPT`
  gate already. The prompt is re-sent every cycle while live, and the client keys it by
  id.
- **The submit log (D-M5-6a).** `SubmitLog` writes `submit_log.jsonl` (gitignored) and only
  once a transport exists. It writes one line per remote submit (accepted, refused and
  malformed alike) and one `takeover` line when the DM resolves a player's prompt on the
  console. It records principal ids only.
- **`turn_agent` (D-M5-5)** is in `combat`. It is null out of combat and on a hidden
  creature's turn.
- **The client.** It gets a prompt panel (options, disabled reasons, Cancel, and the ack
  refusals in words), the second `.send(` (`submit`), and the initiative turn marker.
  `test_live.py`'s tripwire is now **exactly two** sends, named `auth` and `submit`.

| Mutant | Killed by |
| --- | --- |
| `build_live` sends the live prompt without the gate | `test_the_prompt_reaches_only_who_may_answer` |
| `handle_submit` submits as the DM | `test_the_wrong_player_is_denied` |
| `cancel_as` skips `authorize()` | `test_cancel_over_the_wire` |
| `parse_submit` accepts two answers | `test_a_malformed_submit_runs_nothing` |
| `_pump_net()` also drains submits | `test_a_modal_never_decides_a_submit` |
| the log writes `display_name` | `test_the_log_keeps_ids_not_names` |
| no bus observer (takeovers unlogged) | `test_a_takeover_is_logged` |
| no `remote` flag (the DM's browser logged twice) | `test_the_dms_browser_is_logged_once` |
| `turn_agent` emits the raw index | `test_turn_agent_never_names_a_hidden_creature` |
| a third `.send(` in `app.js` | `test_the_client_sends_auth_and_submit_and_nothing_else` |
| a timed-out submit is dropped from the queue | `test_a_stalled_frame_loop_is_a_timeout` |

**Carried to M5b, not done in M5a:**
- Cancelling a child prompt re-sends its parent. `PromptBus.cancel` still cancels the
  whole stack, and the re-offer arrives with the action offer (D-M5-2).
- D-M5-7's reaction deadline (60 s, then Skip, DM-settable). `Prompt.to_wire` still
  projects `deadline` as an absolute monotonic value, and Envelope 4 wants a relative one,
  so this has to be fixed before any deadline is set.
- **A manual pass in a real browser.** The client is checked only by `node --check` and
  static reads. No browser has rendered the prompt panel yet.

##### Handoff — to M5b *(written 2026-09-28)*

**State.** `main` @ `2ed68bd` (M5a), three commits ahead of `origin/main` (`38ea487`), none
pushed. The suite is **162 / 0** in the container, with determinism and snapshot unchanged.
Step 0.12 is frozen, and D-M5-1 through D-M5-9 are the contract. Read "The frozen
decisions" above before touching code.

**M5b is two commits, in this order, and never one:**

1. **D-M5-1 — `App.perform(action_id, principal, anchor=None)`, and nothing else.** A pure
   extraction:
   - **Where the sites are.** The 110 `if self._action_clicked("<id>", event):` sites are
     at `main.py:16923–17728`, all inside `_handle_events`'s combat-active `else:` branch.
   - **Guards that must move in with the bodies.** These are handler-level guards, and
     each one has to come along with the ids it covers:
     - `if not self.action_used:` (`main.py:16938`) covers `dash`, `dodge`, `disengage`,
       `hide`, `prone` and `spell_action`. D-M2-4 says these are drawn mid-sequence and
       refused here, so the gate is a handler rule, not availability.
     - `if not self.bonus_used:` (`main.py:17022`) spans the whole Bonus band through about
       `17588`.
     - `step_of_wind` (the F11 Fleet Step case) and `haste_action` sit deliberately
       **outside** that band, and so do the session, turn and utility ids after it.
     - `end_turn` refuses while `pending_beguiling` is armed or the combat is paused.
     - `long_jump` refuses while `pending_spell_slot` is set.
   - **Other shape details.** `nick` reads the local `_ev_idx`. Four bodies pass
     `event.pos` and thirteen call `pygame.mouse.get_pos()`, and every one of those is only
     a menu anchor, so it becomes `anchor` (default: the actor's screen position, as
     `_ask_actor` already does).
   - **What stays at the click site.** Each site becomes `if self._action_clicked(id,
     event): self.perform(id, DM_PRINCIPAL_ID, event.pos)`.
   - **What `perform` checks.** It re-checks the offer (`self._action_menu.get(id)`, and
     `enabled`), then `authorize()` for a non-DM principal, before it dispatches.
     `ActionMenu.build` must have run for the current actor. Today the panel draw builds it
     each frame, so decide whether `perform` rebuilds the menu or trusts the last draw, and
     write the choice down.
   - **Oracle:**
     - `test_combat_panel.py` (the panel golden) and `test_determinism.py` stay
       byte-identical.
     - `test_action_menu.py`'s click tests all pass. Several were verified against the
       pre-M2 call sites and exercise the D-M2-4 refusals.
     - A new test drives `perform` for a sample of I-class ids with no pygame event and
       compares the engine state with the click path.
   - **Mutants:** `perform` skipping the `enabled` re-check; the `action_used` guard
     dropped for `dash`; `haste_action` moved inside the bonus band.
   - **Build and memory.** No C++ changes, so there is no rebuild. It is still a ~800-line
     move in a 17,940-line file, so check the diff for anything other than indentation and
     the anchor substitution.
2. **D-M5-2 — the offer.** A `kind:"action"`, `expects:"choice"` prompt, built from
   `ActionMenu.build`, owned by the controller, and posted at the top of each step of a
   remotely controlled token's turn. Its option callbacks call `perform`.
   - **Filtering.** `GROUP_SESSION` and `place_terrain` are filtered out, and so is **Move**
     (not until M5c) and **Interact** (not until M5f).
   - **Re-posting.** The offer is re-posted after each resolved step and after a cancel.
     That re-post is also where M5a's first carried item lands: a cancelled child re-offers
     its parent.
   - **Scope.** The 65 I / C→I rows and End Turn become playable. The A / X / S rows are
     offered but still arm a map-click flag, which a remote player cannot answer until
     M5d, so offer them **disabled** with a `disabled_reason` rather than letting a
     player strand themselves.
   - **Local vs remote.** "Remotely controlled" means the token's controller is not the DM.
     The DM's own panel behaviour must not change, and the panel golden proves that.

**Also owed in M5b** (M5a's carried items):
- The reaction deadline (D-M5-7: 60 s, then Skip, set by the DM). This needs
  `Prompt.to_wire`'s `deadline_ms` fixed to a *relative* value first. Today it projects the
  absolute monotonic deadline.
- A **manual browser pass** of M5a's prompt panel. Only the user can launch it (`./run.sh`,
  join on 6081, drag an NPC out of a player token's reach).

**Rules, unchanged:**
- Container only.
- A header change under `combat.hpp` builds with `cmake --build build --parallel 3` inside
  the image, then `cmake --install build`.
- Stage by name and use `git commit --only`. Never `-A`, never push unasked.
- After a manual pass on TestDNDMap, run `git checkout -- maps/TestDNDMap_agents.json
  maps/TestDNDMap_terrain.json`.
- Mutant-check every new test.

##### M5b, commit 1 — D-M5-1 landed *(2026-09-30)*

Suite **163 / 0** (`test_perform.py` is new). The panel golden and the determinism golden
are byte-identical. No C++ change.

- **The move.** 111 sites went under `App._perform_action(action_id, anchor)`: the 110
  literal `_action_clicked("<id>", event)` tests, plus the Metamagic loop. They were
  moved by a script, and the only edits were the 8-space dedent, `_action_clicked(…)` →
  `action_id == …`, and `event.pos` / `pygame.mouse.get_pos()` → `anchor`. A multiset
  diff of the stripped lines shows nothing else changed. The `action_used` and
  `bonus_used` guards, `dash_bonus`'s `not self.context_menu.visible`, End Turn's
  refusals and `long_jump`'s refusal all moved in with their bodies. `draconic_resistance`'s
  `bonus_used = True` still assigns a local, not `self.bonus_used`, exactly as before. That
  is a pre-existing bug, preserved and noted here, not fixed in a no-change slice.
- **Anchors.** Five anchors were in the bodies: `unarmed` read the mouse, and `use_item`,
  `bend_luck`, `boon_of_fate` and `bastion_of_law` used `event.pos`. The other
  `pygame.mouse.get_pos()` popups are inside `menus/features.py`'s helpers (portent,
  arcane ward, wild shape, companion, familiar). They still read the mouse, which on
  the DM's click is the same point. Threading `anchor` into them belongs with the offer,
  not with this move.
- **Decision: `perform` trusts the last draw.** It checks `self._action_menu`, the offer
  the panel drew. It does not rebuild the menu. The panel rebuilds every frame before
  events and submits are drained, so the offer is at most a frame old. What the DM sees
  is then what may run, and the handler guards are the within-frame backstop, as they
  always were. A rebuild inside `perform` would be a second offer that could disagree
  with the drawn one. Out of combat the setup panel clears the menu, so nothing is
  performable.
- **Decision: `authorize()` is always asked, the DM included** (NN6: no call site
  branches on who is asking). `GROUP_SESSION` and `place_terrain` ask `DM_COMMAND`.
  Every other id asks `CONTROL_TOKEN` over the current actor. `perform` therefore cannot
  be a back door to the DM tools, even before D-M5-2's filter.
- **Click site.** This is one loop, not 110 one-liners: the first offered id under the
  pointer goes to `perform(id, DM_PRINCIPAL_ID, event.pos)`. Since F10 there is one widget
  per id, and a click is one event, so this is the same dispatch. The move-type buttons
  and the three `btn_show_*` toggles are not actions and stay in `_handle_events`.
- **Return value.** `perform` returns True when it dispatched, not when the body did
  something. A mid-sequence Dash is dispatched, and the handler refuses it.

| Mutant | Killed by |
| --- | --- |
| `perform` skips the `enabled` re-check | `test_perform_refuses_what_the_offer_does_not_name` |
| the `action_used` guard dropped for `dash` | `test_the_handler_guards_moved_with_their_bodies` |
| `haste_action` inside the bonus band | `test_the_handler_guards_moved_with_their_bodies` |
| `perform` skips `authorize()` | `test_perform_asks_authorize` |
| DM tools asked as `CONTROL_TOKEN` | `test_perform_asks_authorize` |

`test_perform_is_the_click` runs 11 no-target ids (`dodge`, `dash`, `disengage`, `hide`,
`prone`, `standup`, `second_wind`, `action_surge`, `drop_weapon_main`, `end_turn`,
`pause_resume`). Each id runs once as a click and once as `perform` with no event, in
same-seed twin apps. It then compares every combatant's stats, conditions, weapons,
position and movement, plus the app's economy and the log.

##### Handoff — to D-M5-2 *(written 2026-09-30)*

**State.** `main` is at `2ade754` (D-M5-1), four commits ahead of `origin/main`
(`38ea487`). None are pushed. The suite is **163 / 0** in the container, and the
determinism and panel goldens are unchanged. D-M5-2 is M5b's second commit, and it stays
separate from anything else.

**What D-M5-2 is.** Take D-M5-2 as frozen above. On each step of a turn whose token is
controlled by a player, post a `kind:"action"`, `expects:"choice"` prompt, owned by
`roster.controller_of(actor)`, with one option per offered id. Each option's callback is
`perform(id, owner)`. Choosing an option answers the prompt. The step resolves, and the
next offer is derived fresh.

**Where things are** (`gui/main.py` @ `2ade754`):
- `perform` is at `:15047`, its dispatch `_perform_action` at `:15081`, and the click site
  at `:17766`.
- The frame loop is `run()`, at about `:17917`. Its order is `_handle_events` →
  `pump_submits` → NPC drive → `_pump_net` → `push_cycle` → draw (`_draw_panel` at
  `:17940`, which rebuilds `_action_menu`).
- `_ask_actor` is at `:9264` and `_advance_turn` at `:4399`.
  `_clear_pending_target_picks` is at `:4456`.
- The bus is in `prompts.py`: `ask` `:379`, `cancel` `:528`, `renderer_dismissed` `:557`,
  `_render` `:580` and `Prompt.to_wire` `:141`.
- The per-id classes (I / C→I / A / A\* / C→A / X / C→X / S / DM) are in Step 0.12's
  110-row table above. Its line numbers are @ `f9c4385`; the ids are what matter.

**Recommended shape** (decide, then write it down, as D-M5-1 did):
1. **Make the offer a poll, not a set of hooks.** Add `_ensure_action_offer()`, called
   once per frame right after `_draw_panel()`, so the offer is built from the
   `_action_menu` that `perform` will check and cannot offer an id `perform` would
   refuse. Post an offer when all of these hold:
   - combat is active and not paused;
   - the actor's controller is not the DM;
   - nothing is live on the bus;
   - no `pending_*` target flag is armed;
   - no NPC playback is running.

   If an offer is live but its projection has changed, re-post it. The projection is the
   actor plus `(id, label, enabled, reason)` for each option. A new actor after End Turn,
   a DM edit and a resolved step all count as a change. One rule then covers "turn
   start", "after every step" and "after a cancel", and nothing has to be patched: that is
   what "re-derived rather than patched" means in D-M5-2.
2. **The offer must not appear on the DM console.** Give it a renderer name
   (`render="remote"`, say) whose renderer draws nothing and reports `is_showing()` True
   while the prompt is live. **The trap:** `_render` with no renderer leaves `_showing =
   None`. `renderer_dismissed()` then cancels the live prompt the next time the DM clicks
   any popup (`main.py:16945`, `:17109`, `:17123`), so the offer would be cancelled every
   time. Add a test for exactly this.
3. **What goes in the options.**
   - Leave out `GROUP_SESSION` and `place_terrain`. (`perform` refuses them for a player
     anyway, but D-M5-9's mutant is "dropping the `GROUP_SESSION` filter", so the filter
     is tested at the offer.)
   - No Move and no Interact yet (M5c, M5f).
   - I and C→I rows are enabled. A / A\* / C→A / X / C→X / S rows go out
     `enabled:false`, with a `disabled_reason` such as "needs a map pick — coming in
     M5d". That is 65 playable, 42 disabled and 3 withheld.
   - Encode the class in one place. The natural home is `actions.Action.expects`, which
     exists and is set nowhere (`"agent"` / `"cell"` for A/X). Check that the panel golden
     does not serialize it. If it does, use a table in the offer module instead.
   - **Verify each C→I row's leaves.** A leaf that arms a pick (a thrown flask under
     `use_item`, for example) strands the player just as an A row would.
   - Option ids: use the action ids themselves rather than `opt_N`, since they are closed
     and stable. The client must still treat them as opaque.
4. **C→I sub-prompts** already go to the controller through `_ask_actor`, and they open
   with no parent, so they supersede the offer. That is fine: the offer was answered
   first. With no anchor, a remote `perform` anchors them at the token.
   `menus/features.py`'s five helpers (portent, arcane ward, wild shape, companion,
   familiar) still read `pygame.mouse.get_pos()`. Pass them `anchor` now, since the DM's
   mouse is no anchor for a remote player's popup.
5. **Cancel.**
   - A cancelled C→I child empties the bus, so the poll re-offers. That closes M5a's
     carried "child cancel re-sends parent" for this slice, with no change to
     `PromptBus.cancel`. Record it as closed in that reading. If you want literal
     re-send semantics, that is a dated amendment.
   - Decide what cancelling the offer itself does. The recommendation is to refuse it
     (`cancel_as` gives `not_cancellable`), because the next frame would re-post it
     anyway and each attempt would be a log line.
6. **Take over (D-M5-7).** A DM panel click on a remote turn must resolve the live offer
   *as the DM* before it calls `perform`, so the submit log gets its `takeover` line and a
   late player submit gets `not_live`. Do it at the click site at `:17766`: if a live
   `kind:"action"` prompt is on the bus, cancel it with `principal_id=DM_PRINCIPAL_ID`
   before `perform`, and check that the M5a observer logs that as a takeover. Map clicks
   on a remote turn belong to M5d.

**Oracle, and a mutant for each** (all new tests go in `tests/test_offer.py` or extend
`test_submit.py`):

| Test | Mutant that must die |
| --- | --- |
| the offer never carries `pause_resume` / `end_combat` / `place_terrain` (byte level, on the wire) | dropping the `GROUP_SESSION` filter |
| no offer on a DM-controlled or NPC turn | posting whenever combat is active |
| the DM panel golden is unchanged with a player seated on the current token | the offer rendered through the default ContextMenu renderer |
| a DM popup click-away does not cancel the live offer | the remote renderer's `is_showing()` returning False |
| a remote Dodge through the socket: `action_used` set, then a fresh offer without Dodge | no re-post after a step |
| End Turn through the socket advances the turn and moves the offer to the next owner, or to none | the offer kept across a turn change |
| an A/X row is offered disabled, with a reason, and a submit of it is refused | offering A/X rows enabled |
| a DM click during the offer logs `takeover`, and the player's late submit gets `not_live` | the click site not resolving the offer first |

End to end, extend `test_submit.py`'s `_table` harness: a seated player, a live socket, and
a submit of `dodge` from the offer.

**Also owed in M5b** (carried from M5a; not part of the D-M5-2 commit, and each is its
own small commit):
- **The reaction deadline (D-M5-7).**
  - First fix `Prompt.to_wire` (`prompts.py:153`). It sends `int(deadline * 1000)`, an
    absolute monotonic value, and Envelope 4 wants the time remaining:
    `max(0, deadline - monotonic())` in ms, or null.
  - Then add a DM-set session value, default 60 s, applied to reaction prompts only.
  - Expire on the frame tick by submitting Skip, and log it.
  - Action and target prompts keep `deadline_ms: null`.
- **The manual browser pass.** The user runs `./run.sh`, joins on 6081 from a phone, and
  drags an NPC out of a player token's reach to trigger an opportunity attack. After
  D-M5-2, the same pass should also cover a player's own turn: Dodge, then End Turn.
  Afterwards run `git checkout -- maps/TestDNDMap_agents.json maps/TestDNDMap_terrain.json`.

**Rules, unchanged.**
- Container only.
- No C++ is expected. A header change under `combat.hpp` builds with
  `cmake --build build --parallel 3`, then `cmake --install build`, inside the image.
- Stage files by name and use `git commit --only`. Never `-A`, never push unasked.
- Mutant-check every new test.

**0.12.9 — frozen 2026-09-28.** The user approved D-M5-1 through D-M5-5, D-M5-7, D-M5-9, the
slice order and the D-M5-6b reading as written. Changing any of them now takes a dated
amendment here, as with every earlier Step 0.

##### D-M5-2 — decisions *(frozen 2026-10-01; user: "Confirmed all")*

These settle the six points the handoff left open. Three of them depart from its
recommendation, and each is marked **(departure)** with its reason.

1. **The offer comes from a once-per-frame check, not from turn hooks.**
   `net/offer.ensure(app)` runs in `run()` right after `_draw_panel()`, so it reads the
   `_action_menu` that `perform` checks.
   - **The gate.** An offer is posted only when all of these hold:
     - combat is active and not paused;
     - the actor index is valid, and its controller is not the DM;
     - no NPC drive or playback is pending;
     - the engine has no parked decision;
     - no target pick is armed (`App._target_pick_armed()`);
     - nothing is live on the bus, or what is live is our own offer.
   - **Staleness.** The offer's projection is the actor, the owner, and
     `(id, label, enabled, reason)` per option. When it changes, the offer is re-posted
     with `ask(parent=None)`, which supersedes the old one.
   - **(departure) `PromptBus.withdraw(id)`.** A live offer whose gate has closed (a pause,
     combat ending, an NPC playback) is marked `SUPERSEDED` with no callbacks. The submit
     log ignores superseded prompts, so a withdrawal never reads as a takeover.
2. **The offer stays off the DM console.** It is posted with `render="remote"`.
   `RemoteRenderer` draws nothing, and its `is_showing()` is True while it holds a prompt,
   so `renderer_dismissed()` (the only DM-side canceller, at three call sites) leaves it
   alone.
3. **What goes in the options.**
   - **(departure)** The class (I / C→I / A / A\* / C→A / X / C→X / S / DM) lives in a
     110-row table in `net/offer.py`, not in `Action.expects`. `test_action_menu.py`
     asserts `expects == "none"` for every built action, and the wire's `expects` cannot
     tell C→A from A anyway. A test holds the table to the ids `_perform_action`
     dispatches. An id missing from the table goes out disabled.
   - Enabled: I and C→I (65). Disabled, with a reason written for the player: A, A\*,
     C→A, X, C→X and S (42). Withheld: `GROUP_SESSION` and `place_terrain` (3). No Move
     and no Interact yet. Option ids are the action ids, and each callback is
     `perform(id, owner)`.
   - **The C→I leaves were verified.** None of the eight handlers or their callees arms a
     pick (summons place themselves; Wild Shape loads its file).
   - **Known gap, carried to M5d.** `action_surge` (EK L15's `arcane_charge_pending`),
     `radiance` and `bite_grappled` (attack riders) can arm a pick as a follow-up. The
     gate then closes, and the player sees no offer until the DM resolves the pick or the
     turn ends. That is a stall, not a corrupted state.
4. **C→I sub-prompts** keep `_ask_actor`: they are owned by the controller and opened
   with no parent. The five `menus/features.py` helpers (portent, arcane ward, wild
   shape, companion, familiar) take `anchor` instead of reading the DM's mouse. They are
   still drawn on the DM console as the normal popup, as M5a's reactions are, so a DM
   click-away cancels them and is logged as a takeover (D-M5-7).
5. **Cancel.**
   - A cancelled C→I child leaves the bus empty, so the next frame posts a fresh offer.
     **M5a's carried "cancelling a child re-sends its parent" is closed for this slice in
     that reading**, with no change to `PromptBus.cancel`.
   - **(departure)** A player may cancel the offer itself. `not_cancellable` is not in the
     closed `submit` error set, and adding it would amend Envelope 4. The cancel is
     logged, and the gate re-posts the same options under a new id on the next frame. A
     client should not show Esc on a `kind:"action"` prompt.
6. **Take over (D-M5-7).** At the panel click site, when the live prompt is the offer, the
   DM cancels it as `DM_PRINCIPAL_ID` before `perform` runs. The observer logs the
   `takeover`, and the player's late submit gets `not_live`. Map clicks stay with M5c and
   M5d.

The oracle is the handoff's eight-row table plus three more:
- a pause withdraws a live offer with no takeover line (mutant: no withdraw);
- the class table covers exactly the dispatched ids (mutant: drop a row);
- `_target_pick_armed()` accounts for every field `_clear_pending_target_picks` resets
  (mutant: drop a flag).

##### M5b, commit 2 — D-M5-2 landed *(2026-10-01)*

- **New code:** `gui/net/offer.py` holds the class table, `offered`, `gate`, `ensure` and
  `take_over`. `prompts.py` gains `RemoteRenderer` and `PromptBus.withdraw`. `main.py`
  registers the `"remote"` renderer, adds `_target_pick_armed()` with its two field
  lists, calls `ensure` after `_draw_panel()`, and calls `take_over` at the panel click
  site. The five `menus/features.py` helpers take `anchor`.
- **Tests:** `tests/test_offer.py` has 11 checks, and each one fails against its mutant
  (12 mutants, all of them killed). The wire checks drive a real socket, through
  `test_submit._Table` with the drawing half of the frame tick added.
- **Results:** the suite is **164 / 0** in the container, and the panel and determinism
  goldens are unchanged. No C++ changed.
- **Still owed in M5b:** the reaction deadline (D-M5-7), and the manual browser pass,
  which should now include Dodge then End Turn from a phone.

##### M5b, commit 3 — the reaction deadline (D-M5-7) landed *(2026-10-01)*

**Decisions taken while building it:**
- **Where the setting lives:** `App.reaction_timeout_s`, default 60, with `None` meaning
  no limit. It is a table rule, not something a principal owns. It is saved in
  `_combat.json` beside `combat_paused`, so a resumed fight keeps it. A sidecar without the
  key, or with a value that isn't one of the choices, keeps the session's value. It is not
  reset between fights, but it does not outlive the process unless a fight is resumed:
  `_combat.json` is deleted when combat ends.
- **How the DM sets it** *(user's choice: the session panel)*: a third button in the
  session row, `reaction_timer`, labelled `React 60s`. Each click moves it on through
  15 / 30 / 60 / 120 s / untimed. It is `GROUP_SESSION`, so `perform` asks `DM_COMMAND`, the
  offer filters it out, and `CLASS` lists it as `DM` (111 dispatched ids, 4 DM tools). A
  click on it does not take the player's turn over. A change applies to the next reaction
  prompt; one already live keeps the deadline its owner has already been shown. The panel
  golden was regenerated, and its diff is only the header row: three 102-px buttons where
  there were two of 156 px, in all 72 checkpoints.
- **Who gets a deadline:** `App._reaction_deadline(kind, owner, on_cancel)` is the one rule.
  A deadline goes only on `kind == "reaction"`, only when the owner isn't the DM, and only
  when the prompt has an `on_cancel`. The action offer, and action and target prompts, never
  get one, and neither do the DM's own reactions on the DM's own console.
- **Expiry = Skip = `on_cancel`.** `PromptBus.expire()` cancels the live leaf as
  `CLOCK_PRINCIPAL_ID` (`"clock"`, which is not a roster principal). The engine-parked
  windows already had `_submit_reaction_skip`. The five `menus/reactions.py` reactions now
  pass their own `_skip` as `on_cancel`, which is why no closed "skip" option id was needed.
  **This changes DM behaviour:** a click-away on Riposte, Sentinel Guard, Soul of Vengeance,
  Protective Field or Interception used to run nothing, so the original attack's log line
  was lost and the attack sequence never continued. It now runs Skip, the same as the
  engine-parked windows. Restore Balance is `kind="action"` and is unchanged. A reaction
  site with no `on_cancel` gets no deadline rather than an expiry that runs nothing.
- **When it fires:** at the end of `net_link.pump_submits`, after the submit queue is
  drained. A submit that was already queued wins over the deadline, and a blocking modal
  holds expiry back the same way it holds submits back.
- **The log:** `SubmitLog.observe` writes one `expired` line with principal `"clock"`.
  `resolved_by` isn't the DM, so no `takeover` line is written. A late submit gets
  `not_live`.
- **The wire:** `deadline_ms` is now the time remaining (`Prompt.deadline_ms()`). The phone
  shows "Skipped in N s if you don't answer" under the prompt title, re-anchored on every
  push.

**Tests:** `tests/test_deadline.py` has 9 checks, and each one fails against its mutant
(13 mutants, all killed).
- **Mutant-runner hazard, fixed here and worth keeping:** one mutant
  (`prompt.deadline = None; prompt.on_cancel()`) is the same byte length as the line it
  replaces. Python accepts a `.pyc` whose source has the same mtime second and the same
  size. So the copy ran stale bytecode, and one run's results flipped. Run mutants with
  `PYTHONDONTWRITEBYTECODE=1`, and leave `__pycache__` out of the copy.

**Results:** the suite is **165 / 0** in the container. The determinism golden is
unchanged; the panel golden changed only as described above. No C++ changed.

**Manual browser pass, done by the user on 2026-10-01, with a phone on 6081.** All of it
worked:
- an OA answered on the phone;
- Dodge, then End Turn, from the phone, with no DM popup for the offer;
- a DM panel click taking the turn over;
- a 15 s reaction left to expire.

The submit log read, in order:
- a `submit` for the reaction;
- four `submit` lines for the action offer;
- one `takeover` line, from `dm`;
- one `expired` line, from `clock`, with no `takeover` beside it.

It held principal ids only. **M5b is complete; M5c (movement) is next.**


##### Handoff — to M5c *(written 2026-10-02)*

**State.** `main` is at `1daa8c4`, seven commits ahead of `origin/main` (`38ea487`), none
pushed. The suite is **165 / 0** in the container; the determinism golden is unchanged
and the panel golden changed in `e1c887d` only in the session row. M5b is complete.

**What M5b left behind.** The offer is `net/offer.py` (`ensure` every frame after
`_draw_panel()`, `take_over` at the panel click site), with no Move row yet. The deadline
is `App._reaction_deadline` + `PromptBus.expire()` at the end of `pump_submits`, set by
the `reaction_timer` session button and saved in `_combat.json`. Known gap still carried
to M5d: `action_surge` (EK L15), `radiance` and `bite_grappled` can arm a map pick that
closes the offer gate until the DM resolves it.

**Mutant runs.** Copy the repo into the container's `/tmp` without `__pycache__`, with
`PYTHONDONTWRITEBYTECODE=1`. D-M5-2's twelve mutants predate that rule and are worth
re-running under it.

##### D-M5-4 — decisions *(frozen 2026-10-02)*

The user confirmed 1, 3, 5 and 6 as proposed, and changed 2 and 4.

1. **Mode switch is an option on the cell prompt.** Envelope 4, amended 2026-10-02: an
   `expects:"cell"` prompt accepts either an `option` (it must name an enabled option;
   its `on_choose` runs) or a `cell` (its `on_answer` runs). `Prompt` gains an off-wire
   `cells: frozenset | None`; a cell outside it is refused with `bad_option` and the
   prompt **stays live**, so a mis-tap costs nothing. The mode options are the modes with
   **remaining budget > 0** other than the current one; the title names the current mode
   and the feet left. With one mode there are no options.
2. **`reachable` is not fog-filtered** *(user's change)*. The player sees, and may pick,
   the whole reachable set, exactly as the DM's drag overlay does; a player must never
   have to tap into fog to find out where they can go. **The leak is accepted and
   recorded:** the set's outline can show walls and blocked cells the party has not
   explored. The set is stored on the prompt (`prompt.cells`); `view.py` only reads it,
   and sends it as `you.reachable` only while the live prompt is a Move prompt and only
   to viewers who get its `prompt_id` (owner and DM). The overlay and the validation are
   one source.
3. **The Move row is an extra option from `offered()`**, first in the list, id `"move"`,
   with its own callback (not `perform`). A test holds that no `ActionMenu` id is
   `"move"`. Disabled with `"Speed is 0"` when `can_agent_move` is False, and with
   `"No movement left this turn"` when every `App.move_remaining_*` is 0.
4. **The mode lives in the prompt; `App.move_type` is never written** *(amended
   2026-10-02, user: "confirm your recommendation then"; an earlier draft of this item
   had the player's choice write `move_type`)*. The Move prompt opens on the DM's current
   `move_type` if it has budget, else the first mode that does, and a mode option re-posts
   the prompt for its mode. `reachable_for(idx, mt)` reads `App.move_remaining_*`, not the
   agent's own budgets, because Steady Aim zeroes only the App fields
   (`main.py:15521`); it keeps the grapple halving, and `_update_reach` calls it. That is
   safe because the offer gate already requires the actor to be the current turn agent;
   legendary out-of-turn moves stay DM-only.
5. **Cancel.** The Move prompt is asked with `parent=offer`. A cancel leaves the bus empty
   and `ensure` posts a fresh offer next frame, as in D-M5-2 item 5. Arming Move spends
   nothing.
6. **A DM drag takes the turn over.** When the DM releases a drag of the actor in combat
   while that player's offer or Move prompt is live, the prompt is cancelled as the DM
   (one `takeover` line) before `commit_move` runs.

`commit_move(idx, cell, mt, principal)` checks `authorize(CONTROL_TOKEN,
TokenTarget(idx))` as `perform` does; the drag passes `DM_PRINCIPAL_ID`.

**Tests** (`tests/test_move.py`), each with a mutant that must fail it:

| Test | Mutant |
| --- | --- |
| `commit_move` extraction: panel and determinism goldens byte-identical | `commit_move` skipping `can_agent_move` |
| remote Move through the socket: token moves, budgets drop, offer re-posted with Move on it | no re-post after the leg |
| a cell outside `reachable` is refused with `bad_option`, the prompt stays live, nothing moves | trusting the client's cell / checking after commit |
| a remote move that provokes parks the OA, resumes on the answer, completes | `move_agent` instead of `begin_move` |
| a mode option re-posts with that mode's set; `App.move_type` untouched | writing `move_type` |
| `you.reachable` only for viewers who get the prompt id, and equals `prompt.cells` | sending it to every viewer |
| cancelling Move re-offers and spends nothing | cancel leaving the offer withdrawn |
| Move disabled with a reason at speed 0 | offering it enabled |
| Steady Aim actor: Move disabled | `reachable_for` reading `ag.walk_remaining` |
| DM drag mid-prompt: one `takeover` line | no cancel on the drag |


##### M5c — movement (D-M5-4) landed *(2026-10-04, commit `M5c, D-M5-4`)*

- **New code:**
  - `gui/net/move.py` builds the Move row (`option`), the Move prompt (`ask`) and the mode switch.
  - `App.commit_move(idx, cell, mt, principal)` is the drag release's combat branch, extracted verbatim, plus an `authorize(CONTROL_TOKEN)` check.
  - `App.move_budget` and `App.reachable_for` are factored out of `_update_reach`, which now calls them.
  - `Prompt.cells` and the cell-prompt option path were added to `PromptBus.submit` (the Envelope 4 amendment of D-M5-4.1).
  - `you.reachable` is now in `net/view.py`.
  - `offer.ensure` and `take_over` both know about the Move prompt.
  - The drag release calls `take_over`.
  - Client: the reachable overlay, tap → cell submit (still exactly two `.send(`), and a "Tap a highlighted square." hint.
- **Changed test:** `test_prompts.test_submit_errors`. An unknown option on a cell prompt is now `bad_option` (it used to be `protocol`), and an empty answer is `protocol`.
- **Tests:** `tests/test_move.py` has 12 checks. The handoff's table, plus Steady Aim, the drag takeover, the gate withdrawing the Move prompt, a player's OA expiring mid-move, and Move being first in the offer. 15 mutants were run on a `/tmp` copy without `__pycache__`, with `PYTHONDONTWRITEBYTECODE=1`. All 15 were killed. That count includes "a mode option writes `move_type`", which was added after item 4's amendment.
- **Results:** the suite is **166 / 0** in the container. The panel and determinism goldens are unchanged. No C++ changed.
- **Manual browser pass:** run by the user on 6081, reported 2026-10-04 as "all confirmed". It followed the eleven-step script handed over on 2026-10-02: Move, a tap off the overlay, a leg, cancel, Dodge then move, mode, an OA, the DM drag takeover, the fog check and Speed 0.
- **Fog, decided 2026-10-04** (user: "do A now, B later"). This supersedes item 2 above, which had left `reachable` unfiltered.
  - **Fix A, done** (committed 2026-10-04, "M5c, D-M5-4.2: fog fix A"). With fog up, `net/move.reachable_cells` cuts the reachable set to cells whose whole footprint is explored. That one set is both the overlay and the accepted set. With fog down, nothing is cut, which is the same rule `net/view.py` applies to terrain and lighting. A player can't move into a never-seen cell from the browser; the DM drags. `test_reachable_is_cut_to_the_explored_mask` covers it, and 3 mutants are killed: no filter, ignoring the fog switch, and checking only the origin of a Large token.
  - **Fix B, deferred.** Plan a player's reach from what the party knows, with unexplored cells treated as open. When a move hits an unseen wall, walk until it stops the token. Today `BattleMap::moveAgent` refuses an unreachable destination outright (`battle_map.cpp:431`), and that refusal would leak the wall one tap at a time. So B needs a C++ change to `advanceMove` / `moveAgent`, plus rules decisions: the partial path, OAs along it, and what the move costs. It is its own slice, not a fix.

**M5c is complete; M5d (agent and cell picks) is next.**


##### Handoff — to M5d *(written 2026-10-04)*

**State.**
- `main` is nine commits ahead of `origin/main` (`38ea487`), none pushed. The last two are `ee2ec4b` (M5c, D-M5-4) and the fog fix A commit that carries this handoff.
- The suite is **166 / 0** in the container. The panel and determinism goldens are unchanged.
- **Flaky, not investigated:** `test_menus.test_on_deck_row_deploys_its_group_on_click` failed once in a full run ("the reserves should start outside the initiative order"). It passed alone, and on the next full run. A guess, not checked: suites sharing cwd encounter files.

**What M5c left that M5d reuses:**
- `Prompt.cells` plus the cell-prompt option path in `PromptBus.submit`. An `expects:"cell"` prompt takes an enabled option or a cell. A cell outside `cells` is `bad_option`, and the prompt stays live. M5d's target prompts use it as is: `cells` holds the valid picks, and `"done"` is the multi-pick option.
- `you.reachable` in `net/view.py`, which reads the live prompt's `cells` and is gated by `prompt_id`. `you.targets` and `you.aoe` (Envelope 2) can follow the same pattern.
- `net/move.reachable_cells`, the fog rule (fix A): with fog up, keep a cell only if its whole footprint is explored.
- `offer.ensure` treats the Move prompt as the offer's child: it leaves it up while the turn is open, and withdraws it when the gate closes. `offer.take_over` cancels the offer or the Move prompt as the DM. The DM's drag calls it.
- `App.commit_move` (`main.py:~9442`) and `App.reachable_for` / `move_budget` (`:~3530`).

**What D-M5-3 says (frozen 2026-09-28):**
- The `pending_*` flags stay the state. When one is armed for a remotely controlled actor, a target prompt is posted as its projection:
  - `kind:"target"` for a creature, `kind:"cell"` for a place, both `expects:"cell"`;
  - parent = the offer, owner = the controller.
- A submitted cell goes into the same resolver chain as the DM's map click. That chain, about `main.py:17468–17660` (it starts at `hit = self._agent_at(cell)`), gets extracted into `resolve_pick(cell)`, which computes `hit` itself. A hidden creature is resolved by the engine's perception, not by the client.
- Multi-picks (`mantle`, the Chromatic chain, `invoke_duplicity`, `spell_num_targets`) get one prompt per pick, with a `"done"` option.
- **Cancel:** the existing Esc branch where there is one. Where there isn't, the matching slice of `_clear_pending_target_picks()` (`:~4484`), followed by a re-offer. Esc on the DM console then goes through the same cancel, which gives about 30 arms an Esc they lack today. That is a recorded behaviour change.
- **Owed before M5d:** for each arm with no Esc, confirm that arming spends nothing. If one does spend, a cancel must refund it, and that is a rules decision.

**Decisions to freeze before coding (Step-0 style):**
1. **The gate.** `offer.gate` closes on `_target_pick_armed()` today. That is why `action_surge` (EK L15), `radiance` and `bite_grappled` stall a player's turn. In M5d, an armed pick for a remote actor posts its target prompt. Decide whether `ensure` owns that projection, the way it owns the Move prompt, or whether each arm site posts it.
2. **What `cells` holds for a creature pick.** The visible, valid targets' footprint cells, or every cell. D-M5-3 has hidden creatures resolved by perception, so limiting the set to visible targets would block a guess at a hidden one. Also decide whether `you.targets` (agent indices) ships as well, for highlighting.
3. **Fog for place picks (X / C→X).** Recommendation: fix A's rule, explored cells only.
4. **Sub-slicing the 37 rows.** Suggested order:
   - weapon attacks first (`atk_action`, `atk_bonus`, `unarmed`, C→A), since that makes a table self-sufficient;
   - then single A picks;
   - then X;
   - then multi-picks.
   Each row flips in `net/offer.CLASS` only when it is wired, and the class-count assertion in `test_offer.py` moves with it.
5. **C→A.** The choice half already reaches the player (`_ask_actor`). The target prompt that follows it needs a parent, either the offer or the choice prompt.
6. **DM map click during a player's target prompt** is a take-over, like the drag (D-M5-4.6). Extend `take_over` to cover it.
7. **The oracle for the `resolve_pick` extraction:** the panel and determinism goldens stay byte-identical. The mutant is `resolve_pick` computing `hit` differently from the map click (D-M5-9).

**Also owed:**
- Re-run D-M5-2's twelve mutants under the fixed method.
- Fix B, knowledge-based reach (see M5c above), is its own later slice.

**Rules:**
- Everything runs in the container. Never run `docker build`; if M5d needs a new image, say so and stop.
- Stage files by name and use `git commit --only`. Never `-A`, never push unasked.
- Mutants: run them on a `/tmp` copy without `__pycache__`, with `PYTHONDONTWRITEBYTECODE=1`. Copy `gui tests maps tools`.
- After a manual pass on TestDNDMap, run `git checkout -- maps/TestDNDMap_agents.json maps/TestDNDMap_terrain.json`.


##### M5d — Step 0 *(frozen 2026-10-04, user: "agreed")*

**The owed audit (D-M5-3): does arming spend?** Checked arm by arm for every arm without an
Esc. Slots, Focus, Superiority Dice, Sorcery Points and the Action are all spent at
resolution, not at arming. Arcane Charge arms after Action Surge is spent, but the teleport
itself is free, so cancelling it is the same as declining it. **Two exceptions, found while
implementing:** Great Weapon Master's Hew clears `gwm_hew_available` when it arms, and the
Unarmed Strike's Damage option swaps the punch weapon into slot 0 when it arms. A cancel puts
both back. That restores the state from before the arm, so it is not a new rules decision.

**Amendment to D-M5-3's cancel.** "The matching slice of `_clear_pending_target_picks()`" is
wrong for four arms, because a bare flag reset leaves a continuation stuck:

| Arm | A flag reset alone leaves | The cancel therefore |
|---|---|---|
| `pending_sweep` | the Extra Attack sequence stalled | calls `_continue_attack_sequence_after_rider(atk)`, as a refused pick does |
| `pending_vitality_target` | the engine's reaction window parked (a deadlock) | calls `_submit_reaction_skip()` |
| `pending_attack_slot` | `attacks_remaining` / `_attack_sequence_slot` seeded by the arm | restores them from the snapshot `perform` took, when no pick has resolved since; otherwise it only disarms |
| `pending_flurry_target` | two companion fields set | resets the companions too |

So **each arm has its own cancel function, and Esc runs that same function.** Arms that had
an Esc keep its body, now as the arm's cancel. D-M5-9's cancel mutant applies to each arm.

**Decisions:**
1. **The gate.** `offer.ensure` owns the target prompt, the way it owns the Move prompt. One
   table, `net/picks.ARMS`, lists every arm in the click chain's order, with its kind, its
   actor, its title and its cancel. A test holds the table's order to `resolve_pick`'s. The
   arm sites are unchanged, so it does not matter who armed the pick. When the first armed
   arm is wired and the actor's controller is a player, `ensure` posts its prompt. Otherwise
   the offer stays held, as in M5b, and the DM resolves the pick on the map.
2. **`cells` for a creature pick** is every cell the viewer may hear about: the explored mask
   with fog up, the whole grid with fog down (`net/view._visible_cells`'s rule). The set
   does not depend on where hidden creatures stand, so it cannot leak them, and a guess at a
   hidden one stays possible. `you.targets` is not sent in M5d. The client outlines tokens
   from its own `agents[]`.
   - `resolve_pick(cell, anchor=None)` returns whether a branch took the click. On the DM
     console, False falls through to doors, ladders and the drag, exactly as before. For a
     remote submit, False logs a line, and the prompt is posted again on the next frame.
3. **Place picks (X, C→X)** use the same set. The resolvers still check range, line of
   sight and light.
4. **Sub-slices.**
   - **M5d.0:** extract `resolve_pick`, add the arm table, the cancels and the `ensure`
     projection. No row is wired yet, and the panel and determinism goldens stay
     byte-identical.
   - **M5d.1:** weapon attacks and the picks that follow them: `atk_action`, `atk_bonus`,
     `unarmed`, `nick`, `flurry_of_blows`, `martial_arts`, `gwm_hew`, `war_priest`, the
     shoves and `bm_maneuver` (Rally, Feint), plus Cleave and Sweep.
   - **M5d.2:** single-creature picks (A), and Vitality of the Tree.
   - **M5d.3:** place picks (X, C→X).
   - **M5d.4:** `mantle` and the duplicity rows.
   - **Moved to M5e:** the Chromatic chain, `spell_num_targets`, Beguiling and Bewitching
     (spells and spell riders). **Dropped:** `_legendary_target_pick`, which is NPC-only.
   - A row is enabled in the offer when its id is in `net/offer.WIRED`. `CLASS` keeps the
     row's class, and `test_offer.py` asserts the unwired counts.
5. **C→A's parent is the offer.** Once the choice's callback has armed the pick, the choice
   prompt is already answered, so it cannot be the parent. Vitality of the Tree arms inside a
   reaction window, and its prompt is posted while the window is parked.
6. **A DM map click during a player's target prompt is a take-over.** It cancels the prompt
   as the DM, which logs the `takeover` line, but **the DM's cancel does not disarm**, so the
   DM's click then resolves the pick that is still armed. `take_over` covers the offer and
   both of its children (Move and target prompts).
7. **The oracle:** the panel and determinism goldens stay byte-identical across the
   extraction; the mutant is `resolve_pick` computing `hit` differently from the map click.
   Each continuation cancel (Sweep, Vitality, a fresh attack) gets its own mutant.

**Not checked:** after an arm-then-Dash with no swing, `attacks_remaining > 0` may keep
`mid_sequence_action` (`actions.py:834`) live once the Action is spent. This is a DM-console
bug too, and it is left alone in M5d. **Confirmed and fixed 2026-10-14** (fragments D1–D3,
see "Progress on the fragments" below): Dash then a full Attack was a free Action.

##### M5d — what landed *(2026-10-04, uncommitted)*

M5d.0 through M5d.4 were built together, with one table, so the sub-slices are rows in
`WIRED` rather than separate commits.

- **`App.resolve_pick(cell, anchor=None)`** (`main.py`) is the click chain, moved unchanged.
  The map click calls it and falls through to doors, ladders and the drag when it returns
  False. Dispel Magic's popup takes `anchor` instead of `event.pos`. A resolved pick drops
  `_attack_arm_snapshot`.
- **`gui/net/picks.py`** holds `ARMS` (the 40 chain arms plus the long jump, in chain
  order), one cancel per arm, `WIRED` (35 arms), `wanted`, `cells`, `projection`, `post`
  and `cancel`. The prompt's `on_cancel` skips the disarm when `resolved_by` is the DM.
- **`net/offer.py`:** `ensure` handles the pick first: it posts, re-posts on a changed
  projection, or withdraws a pick prompt whose arm has gone. `take_over` covers pick
  prompts. `WIRED` lists the 37 pick rows, and `offered` enables them.
- **`main.py`:** `perform` calls `_snapshot_attack_arm(actor)`. The inline Esc bodies for
  duplicity, Clairvoyant, Vow and Inspiring Smite now call the arm's cancel. A last Esc
  branch runs `net_picks.cancel`, which gives every other armed pick an Esc. The DM's map
  click and the jump click call `take_over` while a pick prompt is live.
- **`net/move.explored_footprints`** is fix A's cut on its own. The jump's landing set uses
  it.
- **Client (`app.js`):** a `kind:"target"` prompt rings the tokens instead of painting the
  accepted squares, and its hint reads "Tap a creature on the board". Nothing on the wire
  changed.
- **Behavior changes on the DM console, recorded as D-M5-3 said:** Esc now cancels each of
  the arms that had none, and a cancelled attack restores the fields its arm seeded. A
  cancelled punch restores the weapons. Before, an abandoned punch left the unarmed weapon
  in slot 0, because nothing restored it at the turn boundary either.
- **Handoff stalls:** `action_surge` (Arcane Charge) and `bite_grappled` (attack slot) arm
  wired picks now. `radiance` arms `pending_spell_slot`, which is M5e's, and still holds the
  offer if it is left armed.
- **Tests:** `tests/test_picks.py` has 20 checks. `test_offer.py` now checks the unwired
  rows by emptying `WIRED` for the duration, and asserts that `WIRED` is exactly the
  A / A* / C→A / X / C→X rows. 22 M5d mutants were run on a container `/tmp` copy, and all
  22 were killed. D-M5-2's twelve mutants were re-run the same way, and all 12 were killed.
  The original list isn't in this document, so the twelve were rebuilt from D-M5-2's
  oracle (eight rows plus three, plus a disabled row with no reason).
- **Results:** the suite is **167 / 0** in the container. The panel and determinism goldens
  are unchanged. No C++ changed.
- **Not covered by a test:** most wired arms are checked only through
  `test_every_wired_arm_projects_and_cancels`, which arms each flag directly on a
  Fighter 5. That test checks the projection and the cancel, not that each class's own
  resolver accepts a remote cell. End to end, only Attack, Unarmed, the jump and Mantle's
  Done were driven. The client's ring drawing has no test, so it needs the manual pass.

**Owed:**
- ~~The manual browser pass~~ — done 2026-10-13, results below.
- The arm-then-Dash question above.

**Manual browser pass, 2026-10-13** (user; a browser seat and a phone seat, a Barbarian and
a Paladin, because the test file has no Fighter):

| # | Check | Result |
|---|---|---|
| 1 | Attack from the phone | **OK.** Rings, hint and resolution right, and Reckless Attack reached the phone. Brutal Strike once showed only on the DM console (`submit_log.jsonl`: phone target `pr_00012`, then the DM answered the player-owned `pr_00013` 7.5 s later). Not reproduced: a headless run shows it live, player-owned and named in the player's view, and it later reached the phone. User: "mark it as okay". |
| 2 | Extra Attack | **OK.** |
| 3 | Tap on an empty square | **OK.** |
| 4 | Cancel | **OK.** |
| 5 | DM map click during a target prompt | **Not reproduced; watching.** The takeover works, but the player's screen then "stays stuck and cannot resume control". The log shows the DM takeover of `pr_00037` at t=863, nothing from the player until t=920, then five Cancels on re-posted offers (`pr_00038`–`42`). Not diagnosed. On 2026-10-13 the user tried again and could not make it stick, and will watch for it in normal play. The five Cancels on `pr_00038`–`42` fit the dead Cancel button that 7(b) has since hidden, so part of what looked stuck may have been that button. |
| 6 | Long Jump | **Works, but provokes no Opportunity Attacks.** It predates M5d (the DM console does the same): C++ `jumpAgent` never runs OA detection. Logged in `memory/known_limitations.md` as a [needs C++] TODO. |
| 7 | Lay on Hands on the other seated player | **Fixed (a) and (b).** (a) A full-HP target used to disarm the pick silently, so the player landed back on the offer. It is now refused like an empty square: the pick stays armed and the log asks again (`_resolve_lay_on_hands`, test `test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick`, mutant-checked). (b) The offer shows a Cancel button that does nothing, because the offer is derived and re-posts at once. Hiding it needs either a wire field (`"cancellable": false` on the offer, an Envelope 4 amendment that needs the user's agreement) or a client heuristic. **(b) fixed 2026-10-13 with the wire field** (user's choice): `Prompt.cancellable`, sent by `to_wire`; `net/offer.ensure` posts the offer with `cancellable=False`; `app.js` `drawPrompt` hides `#prompt-cancel`. Envelope 4 amended. Tests: `test_prompts.test_wire_projection` (default `true`), `test_offer.test_the_wire_never_carries_dm_tools` (offer `false`, mutant-checked). Not yet re-checked in a browser. |


##### Handoff — M5d committed *(written 2026-10-13)*

**State.**
- M5d is committed as "M5d, D-M5-3: agent and cell picks from the browser", on top of
  `8bc5a1f`. `main` is ten commits ahead of `origin/main`, none pushed. Never push unasked.
- Suite: **167 / 0** in the container (2026-10-13). The panel and determinism goldens are
  unchanged. No C++ changed, and no image rebuild is needed.
- The user's manual browser pass is done. Results are in the table under "Owed", above.
  Row 7(b) is fixed with the `cancellable` wire field (Envelope 4, amended 2026-10-13).
  Row 5, the player stuck after a DM takeover, did not reproduce on a retry; the user is
  watching for it.
- Left out of the commit on purpose: `maps/TestDNDMap_terrain.json` (modified by the
  manual pass; the **user** resets it), `submit_log.jsonl` (repo root, untracked, the
  manual pass's intent log) and `gui/replay_log.txt`.

**Read first:** "M5d — Step 0", "M5d — what landed" and the manual-pass table under "Owed".

**Next, in order:**
1. **Coverage gap, before M5e:** drive a few real arms from the offer through to
   resolution with a remote cell: Battle Master Rally, Misty Escape / Shadow Step,
   Elemental Burst (C→X), Invoke Duplicity at L17 (Done after the first placement), EK L15
   Action Surge → Arcane Charge. Lay on Hands is already covered.
2. **M5e — the spell pipeline.** The arms waiting on it are already in `ARMS`, unwired:
   `pending_spell_slot`, `pending_chromatic_active`, `pending_summon_slot`,
   `pending_beguiling` and `pending_bewitching_misty`. `radiance` still holds the offer while
   it leaves `pending_spell_slot` armed. Wiring an arm means adding it to `picks.WIRED`
   with a cancel; the cancel must restore whatever the arm changed.
3. **If row 5 comes back:** reproduce it with a Paladin on a player seat (Attack, then the
   DM clicks during the target prompt) and capture the player page's `you.prompt_id`
   against the prompt frame's id, plus the live prompt on the bus. Suspects, unverified: a
   player-owned rider prompt the phone never draws, or an offer whose rows are all
   disabled after the DM's swing. Launching `./run.sh` needs the user's go-ahead.

**Fragments — the coverage gap (Next 1) and the arm-then-Dash question** *(written
2026-10-13)*. Each fragment is one sitting: write the test, watch it fail or pass, run a
mutant, run the whole suite, stop. No fragment commits on its own; commit when the user
asks. Line numbers are as of `f130bf1`.

*Coverage gap.* All of these go in `tests/test_picks.py`, after
`test_lay_on_hands_on_a_full_hp_creature_keeps_the_pick`, which is the template: it drives
the arm from the offer with `_choose(app, kira, "<action id>")`, reaches the pick with
`_until_pick(app, kira)` and answers it with `Response(cell=...)`. Register each new test
in the suite's `__main__` block. `tests/run_all_tests.py` needs nothing, because the suite
is already registered.

- **C0 — the rig.**
  1. Add `_make(app, idx, cls, level, **subclass)` to the rig. It runs `set_class_level`,
     `initialize_class_resources` and the subclass field (`fighter_subclass`,
     `monk_subclass`, `warlock_subclass`, `cleric_subclass`), then `set_agent_stats`. Lay
     on Hands inlines this; switch it over.
  2. Add `_free_cell(app, near, within)`: the first cell within `within` cells (Chebyshev)
     of agent `near` that `app._can_place(cell, size)` accepts. That is the check
     `_resolve_invoke_duplicity` uses (`main.py:9956`). Assert that one exists, so a
     changed test map fails loudly instead of skipping.
  3. Done when Lay on Hands still passes on the new helpers.
- **C1 — Battle Master Rally** (`bm_maneuver` → the maneuver prompt → `_rally` →
  `pending_rally`, `riders.py:874`; resolver `main.py:7087`).
  1. `_make(aria, Fighter, 3, fighter_subclass=BattleMaster)`. `_choose("bm_maneuver")`.
     `_until_pick` with `first=0` picks Rally, the first option.
  2. Happy path: put Skarn within 6 cells. Answer with Skarn's cell. Assert that
     `pending_rally is None`, `bonus_used`, Skarn's temp HP is above 0 and the Superiority
     Die count went down by one.
  3. **Expected finding, check it first:** `_resolve_rally` sets `pending_rally = None`
     *before* its range test (`main.py:7090` against 7095), so a creature more than 30 ft
     away disarms the pick silently, and the player lands back on the offer. That is the
     class of bug as Lay on Hands 7(a). Write the test for the far tap and confirm it.
     If confirmed, ask the user before fixing it. The proposed fix is the Lay on Hands
     pattern: refuse, keep the pick armed, ask again. `_resolve_feint` (`main.py:7106`) has
     the same shape. Check it in the same sitting.
  4. Mutant: drop `bonus_used = True` from `_resolve_rally`.
- **C2 — Misty Escape and Shadow Step** (`misty_escape`, `main.py:15986`, resolver
  7247; `shadow_step`, `main.py:15950`, resolver 7200).
  1. Misty Escape: `_make(aria, Warlock, 6, warlock_subclass=Archfey)`. The action is
     offered only while `reaction_used` is False and Steps of the Fey is above 0
     (`actions.py:1030`). Answer with `_free_cell(aria, 6)`. Assert that Aria is on that
     cell, `reaction_used` is set, Steps of the Fey went down by one, `bonus_used` is
     **unchanged** (it is a reaction), and the offer re-posts.
  2. Answer once with a cell beyond 30 ft first: the resolver keeps the pick (`main.py:7266`).
     Assert that `pending_misty_escape` is still set, and that `_pick` returns a new prompt
     id after a `_frame`.
  3. Shadow Step: `_make(aria, Monk, 11, monk_subclass=WarriorOfShadow)`. Use level 11 so
     the dim-light gate does not apply, and write that choice in the docstring. Assert the
     move and `bonus_used`.
  4. Own-cell tap: `cells` is the whole grid (`picks.cells`), so a player may send their
     own cell. Assert that it cancels (`"Shadow Step cancelled."`) and spends nothing,
     the same as the Cancel button.
  5. Mutant: `_resolve_misty_escape` sets `bonus_used` instead of the reaction.
- **C3 — Elemental Burst** (`elemental_burst` → `show_elemental_burst_menu`, a
  `render="picker"` prompt, `features.py:600` → `pending_elemental_burst = element`;
  resolver `main.py:7379`).
  1. `_make(aria, Monk, 6, monk_subclass=WarriorOfFourElements)` with Focus at 2 or more.
  2. **Risk:** `_until_pick` answers with `Response(option=...)`. Check that the picker
     prompt accepts an option id over the bus the way a choice does. If it does not,
     that is a finding for M5d, not a test workaround: write it down and stop.
  3. Answer with a cell that has Skarn inside the 20-ft sphere. Assert that `action_used`
     is set, Focus went down by 2, Skarn took damage or the log shows his save, and the arm
     is back at -1.
  4. Mutant: `_resolve_elemental_burst` leaves `pending_elemental_burst` armed on success.
- **C4 — Invoke Duplicity at L17** (`invoke_duplicity`, `main.py:15753`; resolver 9933;
  Done appears once `_duplicity_cd_pending` is False).
  1. `_make(aria, Cleric, 17, cleric_subclass=TrickeryDomain)`. Note the Channel Divinity
     count.
  2. Before any placement, the pick has **no** Done option (the `done` lambda). Cancel
     here, and assert that Channel Divinity and `bonus_used` are untouched (`cancel_duplicity`).
  3. Arm again. Place one: assert that CD went down by one, `bonus_used` is set, a
     duplicate spawned, the re-posted pick now carries Done, and the title is unchanged.
  4. Place a second: CD does **not** go down again.
  5. Choose Done: assert that the arm is idle, two duplicates exist and the offer is back.
  6. Mutant: drop `self._duplicity_cd_pending = False` (`main.py:9976`). Expected: CD
     goes down twice, and Done never appears.
- **C5 — EK L15 Action Surge → Arcane Charge** (`action_surge`, `main.py:7425–7445`;
  resolver 7447).
  1. `_make(aria, Fighter, 15, fighter_subclass=EldritchKnight)`. Set `action_used =
     True` first, as if Aria had already attacked. `_choose("action_surge")`.
  2. Assert that the Arcane Charge pick is up (an `expects:"cell"` prompt titled
     "Arcane Charge: …"), that Action Surge went down by one and that `action_used` is False.
  3. Answer with a cell beyond 30 ft: the pick stays (`feet == -2`, `main.py:7464`).
     Then a free cell within 6: Aria moves, the arm is idle, and the offer re-posts with the
     Attack row enabled. That last check is the point. It proves the surge's fresh Action
     survives the pick.
  4. Mutant: `_resolve_arcane_charge` clears `arcane_charge_pending` before the range test.
- **C6 — close out.**
  1. Run the whole suite in the container.
  2. Update "Owed" (the coverage-gap bullet) and this handoff.
  3. List any findings from C1.3 and C3.2 for the user, each with a proposed fix and no
     fix applied.

*The arm-then-Dash question* (`mid_sequence_action`, `actions.py:834`, and the panel's
copy at `main.py:16501`).
**What the code says, read but not run:** `_start_attack("action")` seeds
`attacks_remaining = num_attacks` and `_attack_sequence_slot = "action"` **at the arm**,
with `action_used` still False (`main.py:5637–5642`). Dash (`main.py:15481`) sets
`action_used = True` and touches neither field, nor `pending_attack_slot`. So after "Attack
(arm), then Dash, with no swing", `mid_sequence_action` is still True. The suspicion is
that the band stays open, and that the map may still be armed, so a click would swing.
Dash plus the full Attack would be a free Action.
- **D1 — reproduce it, DM console path.**
  1. A new test in `tests/test_picks.py`, or `tests/test_offer.py` if it reads better
     there. Use a DM-owned token (Skarn's turn) so no prompt is involved.
     `app.perform(..., "atk_action")`, then `app.perform(..., "dash")`. Match how the
     existing tests call `perform` and with which principal.
  2. Record `_attack_fields(app)` after each step.
  3. Assert the *correct* outcome. The test should fail today: after the Dash,
     `pending_attack_slot == ""`, `attacks_remaining == 0`, `_attack_sequence_slot == ""`,
     and the action menu offers no `atk_action` row.
  4. If it passes, the suspicion is wrong. Write that down here and skip to D4.
- **D2 — the remote paths.**
  1. *Player alone:* while Kira's attack pick is live, the offer is gated, so Kira
     cannot reach Dash without cancelling. `cancel_attack` restores the snapshot. Assert
     that path is clean: cancel, then Dash, then no `atk_action` row.
  2. *DM takeover:* `take_over` cancels the pick **as the DM**, and `picks.post._cancel`
     deliberately leaves the arm armed for the DM's click. Then the DM clicks Dash on the
     panel. That is the D1 state on a player's token. Test it, and check what Kira's next
     offer contains. If it carries an enabled `atk_action`, note that it may bear on row 5
     (the player stuck after a takeover), and tell the user. It is not a diagnosis of row 5.
- **D3 — the fix, only after the user agrees on the rule.** The proposed rule: an Action
  other than Attack, taken while an attack is armed and **no swing has landed**, first
  undoes the arm, exactly as `cancel_attack` does. The snapshot is still held then, so
  the restore is exact. Mid-sequence (one swing landed), `action_used` is already True and
  Dash is refused anyway (the `if not self.action_used:` gate, `main.py:15480`), so the fix
  touches only the no-swing case.
  1. Place it at the top of the `if not self.action_used:` block in `_perform_action`,
     guarded by `self._attack_arm_snapshot is not None`.
  2. Mutant: remove the guard's body. D1 and D2 must fail.
  3. The panel draw (`main.py:16501`) and `actions.py:834` need no change once the state
     is right. Confirm that, don't assume it.
- **D4 — close out.** Run the whole suite. Update the "Not checked" note under "M5d — Step 0"
  and the "Still open" bullet below with the outcome.

**Progress on the fragments** *(2026-10-14)*. All of C0–C6 and D1–D4 are done. Suite
**167 / 0** in the container, goldens unchanged. **Nothing committed**: `gui/main.py`,
`tests/test_picks.py` and this file are modified.

- **C0:** `_make`, `_free_cell` (with an optional `beyond`, for the out-of-range taps) and
  `_res` are in the rig, and Lay on Hands uses `_make`. The test map is 11×11, so with Aria
  at (3,3) the farthest cell is 7 away: "beyond 30 ft" is `beyond=6`.
- **C1–C5 pass**, each registered: `test_rally_picked_over_the_bus`,
  `test_misty_escape_picked_over_the_bus`, `test_shadow_step_picked_over_the_bus`,
  `test_elemental_burst_picked_over_the_bus`, `test_invoke_duplicity_at_17_picked_over_the_bus`,
  `test_arcane_charge_picked_over_the_bus`. The five mutants (Rally without `bonus_used`,
  Misty Escape spending the Bonus Action, Burst left armed, `_duplicity_cd_pending` never
  cleared, Arcane Charge disarmed before its range test) were all killed, each by its own
  test, on a container `/tmp` copy.
- **C3.2, no finding:** the element picker (`render="picker"`) takes an option id over the
  bus like any choice.
- **C1.3, finding confirmed:** `_resolve_rally` and `_resolve_feint` clear their flag before
  the range test, so an out-of-range tap disarms the pick silently and the player lands on
  the offer. Tests `test_rally_out_of_range_keeps_the_pick` and
  `test_feint_out_of_reach_keeps_the_pick` are written and fail; they are **not registered**.
  Feint's self-tap (`target_idx == fighter`) disarmed silently too. **Fixed 2026-10-14**
  (user: "go for it"), the Lay on Hands pattern: each resolver clears its flag only once
  the target passes, so a refusal keeps the pick armed and the log asks again. Tests
  registered, plus `test_feint_on_yourself_keeps_the_pick`.
- **D1, confirmed:** on the DM console (Skarn), Attack → the weapon prompt → Dash leaves
  `('action', 1, 'action')` armed with `action_used` True. The panel still enables Attack, and
  a map click swings. Test `test_dash_after_an_unswung_attack_undoes_the_arm`.
- **D2.1 passes** (`test_a_player_cancels_then_dashes`, registered): Kira's own Cancel
  restores the snapshot, so Dash after it is clean.
- **D2.2, confirmed and worse:** after the DM's panel takeover and a DM Dash, the attack
  stays armed with **2** swings, and `ensure` re-posts it to Kira as "Attack: choose a target
  (2 left)". Test `test_a_dm_takeover_then_dash_leaves_no_attack`. This may bear on row 5,
  though it is not a diagnosis: Kira is not stuck here, she is handed a pick she should not
  have.
- **D3, fixed 2026-10-14** (user: "Agreed, go for it"). The plan's placement, at the top of
  the Dash block, could not work: `perform` re-takes `_attack_arm_snapshot` before **every**
  action, so by the time Dash ran the snapshot held the armed state. The fix is in `perform`
  instead:
  - `_attack_unswung()`: the snapshot is held, the sequence is seeded for `"action"`, and
    the Action is unspent. The first swing spends the Action, so this means "Attack chosen,
    nothing swung".
  - While it holds, `perform` keeps the snapshot from before the Attack instead of re-taking
    it. That also fixes arm → a Bonus Action → Cancel, which used to restore the armed counts.
  - After the handler: if it was unswung and the Action is now spent, `perform` runs
    `net_picks.cancel_attack`. The test is on the outcome, not on `economy`, because the
    economy tags are a vocabulary, not a rules audit (Stand Up, Go Prone and Unarmed are
    tagged `action`). Rows tagged `ECONOMY_ATTACK` are excluded: Bite (grappled) swings
    inside its handler and is one of the Attack's swings.
  - D3.3 confirmed: once the state is right, the panel and `actions.py:834` drop Attack
    with no change of their own.
  - New tests: `test_attack_after_a_dash_is_refused` (the other order) and
    `test_a_bite_after_an_unswung_attack_is_one_of_its_swings`.
- **Mutants, all killed**, on a container `/tmp` copy: the undo's body removed, the snapshot
  re-taken while unswung, Bite not excluded, Rally and Feint disarmed before their reach
  test, and Feint's self-tap disarming.
- **Recorded behaviour change, DM console and players alike:** an Action taken while an
  Attack is chosen and unswung now abandons the Attack, logging "Attack cancelled.". Before,
  the Attack stayed armed.

**Still open:**
- The Long Jump draws no Opportunity Attacks (C++, `known_limitations.md`).
- ~~The arm-then-Dash bug~~ and ~~Rally / Feint disarming silently~~: fixed 2026-10-14,
  uncommitted. See "Progress on the fragments" below.
- An Action spent in a prompt's callback, after `perform` has returned (an item from Use
  Item, a spell), does not run D3's undo. No free Action was found that way, because the
  attack pick comes first in the click chain, but it was not audited.
- Fix B (planning a player's reach from what the party knows) needs a C++ change, and is
  its own slice.
- The flaky `test_menus.test_on_deck_row_deploys_its_group_on_click` was not investigated.

**Probes.** A headless probe that imports the test rig (`test_offer._aria_turn`,
`test_picks._choose` / `_until_pick`) reproduces a remote attack in about a minute. Run it
from a file mounted into the container. Piping a heredoc into `docker run` without `-i`
silently runs nothing. Wrap it in `_preserve_cwd_logs` / `_restore_cwd_logs`, or it
overwrites `gui/replay_log.txt`. The scene's seed is fixed, so to force a hit, lower the
target's `ac_temporary_modifications`.

**Mutant runners** (not in the repo; recreate them if needed). Pipe a Python script into
`docker run --rm -i -v "$HOME":/home/user rpg_map -c "python3 -"`. The script copies
`gui tests maps tools` into the container's `/tmp`, ignoring `__pycache__`, applies a single
string replacement, and runs the suite with `PYTHONDONTWRITEBYTECODE=1`. Each of the 22 M5d mutants
pairs with one test in `tests/test_picks.py`: the `hit` swap, each continuation cancel, the
DM's cancel disarming, `take_over` skipping pick prompts, cells drawn from creature
positions, the order of `ARMS`, an unwired arm or the DM's token being projected, a pick
posted over a parked window, and the snapshot taken or dropped at the wrong time.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name and use `git commit --only`. Never `-A`, never push unasked.
- Commit only when the user asks.


##### Handoff — the M5d fragments committed *(written 2026-10-14)*

**State.**
- Committed as "M5d fragments: pick coverage, Rally/Feint refusals, arm-then-Dash", on top
  of `f130bf1`. `main` is eleven commits ahead of `origin/main`, none pushed. Never push
  unasked.
- Suite: **167 / 0** in the container (2026-10-14). The panel and determinism goldens are
  unchanged. No C++ changed, and no image rebuild is needed.
- `tests/test_picks.py` has 35 checks, up from 21. The 11 mutants for this work were all
  killed. The runners are recreated as described under "Mutant runners" above; the two used
  here were piped into `docker run -i … python3 -` and ran only `test_picks.py`.
- Still uncommitted on purpose: `maps/TestDNDMap_terrain.json` (the **user** resets it),
  `submit_log.jsonl`, `gui/replay_log.txt` and the untracked scratch.

**What landed** (details under "Progress on the fragments", above):
- **Coverage:** Rally, Misty Escape, Shadow Step, Elemental Burst, Invoke Duplicity at 17
  and EK Action Surge → Arcane Charge are each driven from the offer to resolution with a
  remote cell. Rig helpers `_make`, `_free_cell` (with `beyond`) and `_res`.
- **Rally / Feinting Attack** (`main.py:7087`, `:7107`): an out-of-reach tap, or Feint on
  yourself, is refused and keeps the pick, the Lay on Hands pattern.
- **Arm-then-Dash (D3)**, in `App.perform` (`main.py:15419`; `_attack_unswung` at `:15464`):
  - while an Attack is chosen and unswung, `perform` keeps the snapshot from before it;
  - an action that spends the Action in that state runs `net_picks.cancel_attack` after its
    handler;
  - `ECONOMY_ATTACK` rows (Bite (grappled)) are exempt.
  - Recorded behaviour change: an Action taken while an Attack is chosen and unswung now
    abandons the Attack ("Attack cancelled.").

**Next, in order:**
1. **M5e, the spell pipeline.** Unchanged from the previous handoff: the arms
   `pending_spell_slot`, `pending_chromatic_active`, `pending_summon_slot`,
   `pending_beguiling` and `pending_bewitching_misty` are in `ARMS`, unwired. `radiance`
   still holds the offer while it leaves `pending_spell_slot` armed. Wiring an arm means
   adding it to `picks.WIRED` with a cancel that restores whatever the arm changed. Freeze
   a Step 0 with the user before coding.
   - M5e should also settle the gap D3 left. An Action spent inside a prompt callback, after
     `perform` has returned, does not run D3's undo; spells and Use Item spend that way.
     Check, case by case, whether an Attack chosen and unswung, followed by a spell cast
     through its prompt, leaves the attack armed after the Action is spent. If it does, the
     undo belongs where the callback spends the Action, not in `perform`.
2. **Row 5 (a player stuck after a DM takeover)**, if it comes back. D2.2 found that a
   takeover followed by a DM Action used to re-post the player's attack pick. That is fixed
   now, and may have been part of row 5, but it is not a diagnosis. The capture steps are in
   the previous handoff's "Next" 3.

**Still open:** the Long Jump draws no Opportunity Attacks (C++), Fix B (C++), the flaky
`test_menus.test_on_deck_row_deploys_its_group_on_click`, and the D3 callback gap above.

**Rules:** unchanged. Container only, never `docker build`, stage files by name with
`git commit --only`, never `-A`, commit only when asked, never push unasked.


##### M5e — Step 0 *(frozen 2026-10-14, user: "agreed")*

**Method.** I read the source and ran nothing. The survey covers the five S rows (`spell_action`,
`spell_bonus`, `divine_intervention`, `mantle_majesty`, `wild_magic_bonus_cast`), plus
`radiance`, from the dispatch in `perform` through `_start_cast_spell` (`main.py:8865`),
`_activate_spell` (`:8544`) and `_dispatch_spell_geometry` (`:8744`), to the spell branches of
`resolve_pick` (`:4562–4626`) and the Esc branches (`:17543–17605`). Line numbers are as of
`44b28c8`.

**What M5e inherits, ready to use.**
- The choice half already reaches the player. The spell grid (`render="grid"`), the
  slot-level popup, the element, curse, Command-word and Forcecage pickers, the summon-form
  menu, the Dispel picker and the friendly-harm confirm all go through `_ask_actor`, so they
  are owned by the caster's controller. `render` is a local hint and never reaches the wire
  (D-M1-10), so a phone draws each of them as an ordinary option list.
- The arms are already in `net/picks.ARMS`, in chain order, unwired: `pending_summon_slot`,
  `pending_chromatic_active`, `pending_spell_slot`, `pending_beguiling` and
  `pending_bewitching_misty`. The last two already have their cancels.
- Every slot, Sorcery Point and Action for a normal cast is spent at resolution
  (`begin_cast` → `_finish_cast` / `_consume_cast_slot`), not when the spell is armed.

**Findings.**

- **F-M5e-1: `pending_spell_slot` is one arm with nine shapes.** Which shape it takes depends
  on the spell, and the shape fixes the prompt's `kind`, its title and its number of clicks:

  | Shape | Set by | Kind | Clicks |
  |---|---|---|---|
  | single creature | Single geometry | target | 1 |
  | N creatures | Multiple geometry, or Twinned on a Single spell | target | exactly N, with no Done (`_resolve_spell_cast` appends until N) |
  | area | Line, Cone, Sphere, Square | cell | 1 |
  | wall | Rectangle | cell | 2: the anchor, then the end. Esc first clears the anchor. |
  | corpse | `revives_dead` / `animates_dead` | cell | 1 (`_corpse_at`, invisible to `_agent_at`) |
  | binding | Planar Binding | target | 1 |
  | door | Knock, on a door cell | cell | 1 |
  | dispel | Dispel Magic | either | 1, then a picker |
  | teleport | `teleportation_spell` | cell | 1 |

  `Arm.kind` and `Arm.title` are fixed per arm today. The spell arm needs both computed from
  this shape.
- **F-M5e-2: four casts spend before the pick, and Esc does not refund them.** Psionic
  Sorcery spends its SP at the level choice (`:8967`). Wish spends its 9th-level slot when the
  duplicate is picked (`:8807`). Divine Intervention spends its use and sets `action_used`
  at the pick (`:8844–8853`). Mantle of Majesty activates on the word choice
  (`menus/features.py:329`). Esc after any of these loses the resource. This is today's behaviour
  on the DM console, and it is not new.
- **F-M5e-3: five choice pickers treat Cancel as "use the default" and cast anyway.** The
  element (Chromatic Orb, Sorcerous Burst), the Vistani Curse, Command's word, Forcecage's
  form and Mantle of Majesty's word all pass `on_cancel=lambda: _on_x([])`. On the DM console
  that is Esc on the picker. On a phone it is a button labelled Cancel, and pressing it casts
  the spell, which a player will not expect.
- **F-M5e-4: the summon arm leaks, and it does not hold the offer.** This is a DM-console
  bug, and it reaches players too.
  1. `pending_summon_slot` is not in `_clear_pending_target_picks`, nor in
     `_proceed_to_new_turn`. An abandoned summon stays armed into the next turn.
     `_resolve_summon` reads `_current_agent_idx()` as the caster, so the *next* combatant's
     map click spawns the creature, using the previous caster's `spell_idx`. That is the L36
     class of bug.
  2. It is not in `_TARGET_PICK_ARMS`, so `offer.gate` stays open while a summon is armed for
     a player. They are offered their turn as if nothing were pending.
  3. A spirit summon arms *before* its form menu. If that menu is cancelled, the arm is left
     with `pending_summon_monster == ""`, so `resolve_pick` swallows every map click and does
     nothing, until Esc.
- **F-M5e-5: the D3 gap has a second shape, and it is a DM-console bug.** Suppose an Attack
  is chosen and not yet swung, and then Cast a Spell is clicked. The `if not
  self.action_used:` gate lets it through, and `pending_spell_slot` arms beside
  `pending_attack_slot`. `pending_attack_slot` comes first in the chain, so the "spell" click
  swings the weapon. D3's undo does not fire, because nothing has spent the Action when
  `perform` returns. A player cannot reach this alone, because the offer is gated while the
  attack pick is armed. They can reach it after a DM take-over followed by the DM's Spell click.
  *This is unconfirmed: it was read, not run.*
- **F-M5e-6: two pickers are DM widgets, not bus prompts, and D-M1-12 left them to M5.**
  - Wish and Divine Intervention open `SpellSelectionDialog` (`:8570`, `:8830`), a browser over
    389 and 80 spells, on the DM's screen. D-M1-12c already decided their wire shape: a
    `choice` prompt with a long `options` list (about 23 KB, once per cast) and a search box
    on the client.
  - The Magic Circle / Hallow ward picker (`:8715`, `_element_dialog`, `multi=True`) asks for
    a **set**. D-M1-12 deferred one decision to M5: add `expects:"choices"`, or don't.
- **F-M5e-7: the Metamagic toggles are not in `offer.CLASS`.** They are nine `metamagic_*` ids
  dispatched in `perform` by a loop, not by an `if action_id ==` site. So they go out disabled
  ("Not playable remotely yet"), and a Sorcerer player cannot Twin, Quicken or Heighten.
  Evoker L14 Overchannel is not an action id at all. It is a board context-menu toggle
  (`menus/board.py:190`), so a player cannot reach it.
- **F-M5e-8: Envelope 2's `you.aoe` cannot be a hover preview.** The DM sees the template
  follow the mouse (`_draw_spell_aoe_preview`). A client sends only `auth` and `submit` (the
  two-send tripwire), so the server never learns where a player is hovering. A player who
  taps for Fireball sees nothing before the tap resolves.
- **To check in M5e.1, not assumed** *(settled in M5e.1: the claim is struck; see
  "M5e.1 — what landed")*: the previous handoff says `radiance` "leaves
  `pending_spell_slot` armed". Its dispatch resolves at once through
  `_resolve_spell_cast_aoe`, which clears the slot before `begin_cast`. Find the path that
  leaves it armed (a parked reaction window is the suspect), or strike the claim.

**Decisions to freeze** *(proposals; each needs the user's yes)*:

1. **E-1: the arm table.** `Arm.kind` and `Arm.title` may be functions of `app`. The spell arm
   computes both from F-M5e-1's shape: "Fireball: choose the center", "Magic Missile: choose
   a target (2 of 3)", "Wall of Fire: choose the start point", then "…: choose the end point".
   A changed title re-posts the prompt, through the projection key `ensure` already uses.
   `cells` keeps M5d's rule for every shape (explored with fog up, the whole grid with fog
   down). The resolvers still check range, line of sight and perception. Dispel is `kind:"target"`
   with `expects:"cell"`. The chain already takes a creature or a cell, and the picker that
   follows is already a bus prompt.
2. **E-2: cancels, one function per arm, run by both Esc and a remote cancel (the M5d rule).**
   - Spell: the existing Esc body, lifted into `picks.cancel_spell`. On a wall that has an
     anchor, it clears the anchor and keeps the arm, so a player's Cancel on "choose the end
     point" goes back to "choose the start point".
   - Chromatic: `_cancel_chromatic_chain`, with Done = `_finalize_chromatic_cast`.
   - Summon: the existing Esc body, lifted into `picks.cancel_summon`.
   - **F-M5e-2: no refunds in M5e.** A cancel is Esc, and Esc refunds nothing today. If you
     want refunds for Psionic Sorcery, Wish, DI or Mantle of Majesty, that is a separate
     rules fix with its own commit, under the standing rule.
3. **E-3: the default-on-cancel pickers (F-M5e-3)** go to players with `cancellable=False`.
   The player must choose, and can still cancel the target pick that follows. The DM console
   is unchanged, and so is the bus, because `cancellable` is a display hint (Envelope 4,
   2026-10-13).
4. **E-4: two bug fixes go first, each in its own commit and each only with your OK**
   (standing rule: no bundling).
   - **F-M5e-4, summon:** add the summon fields to `_clear_pending_target_picks` and
     `pending_summon_slot` to `_TARGET_PICK_ARMS`. Make a cancelled form menu disarm.
   - **F-M5e-5, Attack → Spell:** first write the test, and confirm the bug. If it holds, then
     in `perform`, while `_attack_unswung()` holds, choosing `spell_action`,
     `divine_intervention` or `wild_magic_bonus_cast` first runs `net_picks.cancel_attack`
     (the snapshot is still exact). If the player then cancels the spell grid, the Attack is
     back on the offer, because nothing was swung.
5. **E-5: Wish and DI** follow D-M1-12c as written. Each becomes one bus `choice` prompt
   with `render="spell_browser"`. The DM console keeps drawing `SpellSelectionDialog` as that
   renderer, and `app.js` gets a filter box for a long option list. Nothing on the wire changes.
6. **E-6: the Magic Circle ward picker becomes a toggle loop of plain `choice` prompts**, not
   `expects:"choices"`. Each type is an option marked ✓ when it is chosen, plus "Trap inside"
   and Done, and the prompt re-posts after each toggle. The frozen vocabulary stays at four
   members, for a site with one caller. Recorded behaviour change: the DM console draws it as
   a popup instead of the multi-select widget.
7. **E-7: the Metamagic toggles are classed `I`.** Arming costs nothing, and the SP go with the
   cast. Overchannel stays DM-only in M5e, as a recorded limitation. Making it an action id
   touches the panel golden, so it would be its own slice.
8. **E-8: AoE aim, then confirm, for remote casters only (F-M5e-8).** A tap on an area
   shape does not resolve. It posts a `kind:"confirm"` choice prompt (Cast here / Re-aim),
   with `you.aoe` set to the template's cells cut to what the viewer may see. **Cast here**
   runs `resolve_pick` on the stored cell. The DM console is unchanged. This adds no wire
   field, because `you.aoe` is already in Envelope 2. It is the last slice, and it can be
   dropped without touching the others.
9. **E-9: sub-slices.** Each one ends green, with its mutants killed.
   - **M5e.0:** E-4's two fixes, each with a failing test first.
   - **M5e.1:** E-1, E-2, E-3 and E-7. Wire the spell, chromatic and summon arms. Flip
     `spell_action`, `spell_bonus`, `mantle_majesty` and `wild_magic_bonus_cast` into the
     offer, and settle `radiance`.
   - **M5e.2:** E-5, Wish and DI. Flip `divine_intervention`.
   - **M5e.3:** E-6, the ward toggle loop.
   - **M5e.4:** E-8, aim and confirm.
   - **Not in M5e:** the riders `pending_beguiling` and `pending_bewitching_misty`. They are
     wired with M5e.1 only if they arm on a player's spell, which needs checking. Also out:
     refunds (E-2) and Overchannel (E-7).
10. **E-10: the oracle.** The panel and determinism goldens stay byte-identical through M5e.1.
    E-6 moves the panel golden only if the golden draws the ward widget, which needs checking.
    Each spell shape in F-M5e-1 is driven from the offer through to resolution with a remote cell
    in `tests/test_picks.py`, using the C0 rig. Mutants that must die:
    - the spell arm's kind fixed at `target`;
    - the wall cancel disarming instead of clearing the anchor;
    - Chromatic Done not casting;
    - the summon cancel leaving `pending_summon_monster` set;
    - E-3's pickers posted cancellable;
    - the Attack → Spell undo removed;
    - the summon missing from `_clear_pending_target_picks`;
    - `you.aoe` sent uncut by fog (E-8).

##### M5e.0 — what landed *(2026-10-14, two commits)*

E-4's two fixes, each with its failing test written first and watched fail.

- **F-M5e-4, the summon arm.** All three parts were confirmed before the fix.
  - `_clear_pending_target_picks` now resets the summon fields at the turn boundary.
  - `pending_summon_slot` is an arm in `_TARGET_PICK_ARMS`, so the offer waits on it. Its
    companions are listed in `_TARGET_PICK_COMPANIONS`.
  - The spirit form menu's `on_cancel` disarms.
  - The Esc body moved into `net_picks.cancel_summon`, and the arm in `ARMS` carries it.
    The arm is still unwired, so the DM places the summon until M5e.1.
  - Tests: `test_a_summon_does_not_outlive_its_turn`, `test_an_armed_summon_holds_the_offer`
    and `test_a_cancelled_summon_form_disarms`.
- **F-M5e-5, Attack → Spell.** Confirmed: the spell armed beside the attack, which was left
  at `('action', 1, 'action')`.
  - **The fix, in `perform`:** while `_attack_unswung()` holds, a row in
    `App._ARMS_A_SPELL` first runs `net_picks.cancel_attack`, from the snapshot.
  - **Deviation from E-4's wording, and why.** E-4 named three rows: `spell_action`,
    `divine_intervention` and `wild_magic_bonus_cast`. The set also takes `spell_bonus`
    and `mantle_majesty`. A Bonus Action spell arms the same `pending_spell_slot`, and the
    attack still comes first in the chain. This is safe because nothing has swung: choosing
    Attack again afterwards costs nothing.
  - Tests: `test_a_spell_after_an_unswung_attack_undoes_the_arm` and
    `test_a_cancelled_spell_after_an_unswung_attack_leaves_the_attack_open`. The second
    uses Esc, because the spell arm's remote cancel belongs to M5e.1.
- **Mutants, all killed**, on a container `/tmp` copy, running `test_picks.py` and
  `test_offer.py`:
  - the summon reset dropped from the clear;
  - the summon dropped from `_TARGET_PICK_ARMS` (caught by
    `test_offer.test_the_pick_predicate_covers_the_clear`);
  - the form menu without its cancel;
  - the undo's body removed;
  - `spell_action` dropped from `_ARMS_A_SPELL`.

  No test covers the Bonus Action rows of `_ARMS_A_SPELL`.
- **Suite:** 167 / 0 in the container. The panel and determinism goldens are unchanged. No
  C++ changed.
- **Recorded behaviour changes on the DM console:**
  - an abandoned summon no longer survives the turn;
  - Esc on a summon now also clears `pending_summon_free_cast`;
  - choosing a spell while an Attack is chosen and unswung logs "Attack cancelled." first.

##### Handoff — M5e.0 committed *(written 2026-10-14)*

**State.**
- Two commits sit on top of `44b28c8`, one per fix, as E-4 asked:
  - "M5e.0, F-M5e-4: the summon arm";
  - "M5e.0, F-M5e-5: a spell after an unswung Attack", which also carries this plan update.

  `main` is thirteen commits ahead of `origin/main`, none pushed. Never push unasked.
- Suite: **167 / 0** in the container (2026-10-14). The panel and determinism goldens are
  unchanged. No C++ changed, and no image rebuild is needed.
- `tests/test_picks.py` has 40 checks. The mutant runner is the one under "Mutant runners"
  above, now running `test_picks.py` and `test_offer.py`.
- Still uncommitted on purpose: `maps/TestDNDMap_terrain.json` (the **user** resets it),
  `submit_log.jsonl`, `gui/replay_log.txt` and the untracked scratch.

**Read first:** "M5e — Step 0" (frozen; E-1 through E-10 are the contract), then "M5e.0 —
what landed".

**Next: M5e.1** (E-1, E-2, E-3, E-7). In order:
1. **The `radiance` claim.** Find the path where `radiance` leaves `pending_spell_slot`
   armed. The suspect is a reaction window parked inside `begin_cast`. If no such path
   exists, strike the claim from the M5d handoffs.
2. **E-1, the arm table.**
   - Make `Arm.kind` and `Arm.title` callables.
   - Write one `spell_shape(app)` that maps the live spell to one of F-M5e-1's nine shapes.
     The spell arm's kind and title come from it. The predicates it needs already exist:
     `_pending_spell_targets_corpse`, `_binds_creature`, `_opens_doors`, `_dispels_magic`,
     `_is_wall`, `pending_spell_is_aoe`, `pending_spell_num_targets`, `spell_anchor_cell`
     and `teleportation_spell`.
   - Test the shapes in the same order as `resolve_pick`'s spell branch, so the prompt
     names what the click will actually do.
   - Titles carry the counts ("2 of 3") and the wall's step ("start point", then "end point").
     A changed title re-posts the prompt through the projection key.
3. **E-2, cancels.**
   - Lift the spell Esc body (`main.py`, the `K_ESCAPE and self.pending_spell_slot` branch)
     into `picks.cancel_spell`. On a wall that has an anchor, it clears the anchor and keeps
     the arm.
   - The Chromatic arm gets cancel = `_cancel_chromatic_chain`, `done` always, and
     `finish` = `_finalize_chromatic_cast`.
   - The summon arm already has `cancel_summon`.
   - Point the Esc branches at the arm cancels, as M5d did. Refund nothing (F-M5e-2).
4. **E-3.** Post the five default-on-cancel pickers with `cancellable=False`: element,
   Vistani Curse, Command word, Forcecage form, and Mantle of Majesty's word
   (`menus/features.py:329`). `_ask_actor` does not take `cancellable` yet, so add it as a
   pass-through.
5. **E-7.** Add the nine `metamagic_*` ids to `net/offer.CLASS` as `I`. Check that
   `test_offer`'s both-ways check against the dispatch sites accepts the loop dispatch. If it
   does not, extend that check rather than special-casing the ids.
6. **Wire and flip.**
   - `picks.WIRED` gains `pending_spell_slot`, `pending_chromatic_active` and
     `pending_summon_slot`.
   - `offer.WIRED` gains `spell_action`, `spell_bonus`, `mantle_majesty` and
     `wild_magic_bonus_cast`. Leave `divine_intervention` for M5e.2.
   - Check whether `pending_beguiling` and `pending_bewitching_misty` can arm on a player's
     own spell, and decide those two arms from that.
   - `test_offer.py` asserts the unwired counts, so it moves with the flips.
7. **E-10, tests.** Drive each of F-M5e-1's shapes from the offer to resolution with a
   remote cell, using the C0 rig (`_make`, `_free_cell`). Write the eight mutants E-10 lists.
   - Give Aria a spell list with `set_agent_spells`, as `_summon_beast` does.
     `test_combat_panel`'s scene puts Fire Bolt and Magic Missile on Cyra.
   - A caster needs slots, not just spells. `_make` with a full caster (Wizard 5) grants them.

**Then:**
- **M5e.2:** Wish and DI as one bus prompt with `render="spell_browser"`.
- **M5e.3:** the ward toggle loop.
- **M5e.4:** aim, then confirm, with `you.aoe`.

**Still open:**
- The Long Jump draws no Opportunity Attacks (C++).
- Fix B (C++).
- The flaky `test_menus.test_on_deck_row_deploys_its_group_on_click`.
- Row 5, if it comes back.
- No test covers the Bonus Action rows of `_ARMS_A_SPELL` (`spell_bonus`, `mantle_majesty`,
  `wild_magic_bonus_cast`).
- Out of M5e by decision: refunds (F-M5e-2) and Overchannel (E-7).

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.


##### M5e.1 — what landed *(2026-10-14, commit `f26ba9e`)*

E-1, E-2, E-3 and E-7, and the wiring. The `radiance` claim is struck.

- **`radiance` (step 1).** It never leaves `pending_spell_slot` armed. Its dispatch arms the
  slot and calls `_resolve_spell_cast_aoe` on the same line. That function's only early
  return is for a missing caster or slot, and every other path clears the slot before
  `begin_cast`. So a parked reaction window finds it already idle. The riders it could arm
  afterwards are Beguiling and Bewitching, which are wired now (below). Pinned by
  `test_radiance_leaves_nothing_armed`, which runs it from the offer. The M5d handoffs
  that make the claim are left as written, as history.
- **E-1, the arm table** (`net/picks.py`).
  - `Arm.kind` is a string or a function of the app, read through `Arm.kind_for(app)`.
    `projection` and `post` use it, so a changed kind re-posts the prompt, as a changed
    title does.
  - `spell_shape(app)` returns one of the nine shapes. It tests them in the order of
    `resolve_pick`'s spell branch: corpse, binding, door, dispel, then for an AoE, wall,
    teleport, area, and otherwise multi or single. "Multi" is `_resolve_spell_cast`'s own
    test: Multiple geometry, or Twinned armed on a Single spell. `SHAPE_KIND` maps each
    shape to a kind. Dispel is a `target`.
  - The titles are "Fire Bolt: choose a target", "Magic Missile: choose a target (2 of 3)",
    "Fireball: choose the center" (Sphere or Square), "…: choose where to aim" (Line or
    Cone), "Wall of Fire: choose the start point" and then "…the end point", "…: choose a
    body", "…: choose a creature to bind", "Knock: choose a door", "Dispel Magic: choose
    a creature or a spot" and "Misty Step: choose a destination".
  - The Chromatic arm's title counts its leaps ("(0 chosen)"). The summon arm's title
    names the creature ("Summon: choose where to place Bestial Spirit (Air)").
- **E-2, cancels.**
  - `picks.cancel_spell` is the spell's Esc body, lifted. The Esc branch in `main.py` now
    calls it. On a wall with an anchor, it clears the anchor and keeps the arm.
  - The Chromatic arm: cancel = `_cancel_chromatic_chain`, `done` always, `finish` =
    `_finalize_chromatic_cast`. The console's Enter and Esc branches already call those
    two functions, so they are unchanged.
  - The summon arm keeps `cancel_summon` from M5e.0.
  - Nothing is refunded (F-M5e-2).
- **E-3.** `_ask_actor` takes `cancellable` and passes it to `prompts.ask`. The element,
  Vistani Curse, Command-word and Forcecage pickers, and Mantle of Majesty's word
  (`menus/features.py`), pass `cancellable=False`. Nothing on the DM console reads the
  flag. A player's cancel sent over the wire anyway still runs the default, as today.
- **E-7.** The nine `metamagic_*` ids are in `offer.CLASS` as `I`, through one
  comprehension over `actions.METAMAGIC_VALUE_BY_ID`. `test_the_class_table_is_the_dispatch`
  now also finds the loop dispatch (`for x, … in TABLE.items(): if x != action_id`) and
  takes every key of `actions.TABLE`. So the ids are checked both ways, with no special
  case. The counts are 120 ids, with 66 of them `I`.
- **Wired.**
  - `picks.WIRED` gains `pending_spell_slot`, `pending_chromatic_active`,
    `pending_summon_slot`, `pending_beguiling` and `pending_bewitching_misty`. The only
    arm still unwired is `_legendary_target_pick`, which is NPC-only.
    `test_an_unwired_arm_holds_the_offer` uses it now.
  - **The riders are in.** Both arm on the caster's own slot-fueled spell: `_finish_cast`
    → `maybe_offer_beguiling_magic` / `maybe_offer_bewitching_magic` → a `confirm`
    prompt owned by the caster's controller → the arm. Left unwired, a player's own spell
    would have held their turn until the DM clicked.
  - `offer.WIRED` gains `spell_action`, `spell_bonus`, `mantle_majesty` and
    `wild_magic_bonus_cast`. `divine_intervention` stays disabled until M5e.2.
- **Tests:** `tests/test_picks.py` has 56 checks, up from 40. Each shape is driven from the
  offer to resolution with a remote cell:
  - Fire Bolt (one target);
  - Magic Missile (three counted picks);
  - Fireball (a `cell`);
  - Wall of Fire (two picks, and a Cancel that clears the anchor);
  - Misty Step (through `spell_bonus`);
  - Revivify (a body);
  - Planar Binding;
  - Knock (on a locked door);
  - Dispel Magic on nothing (asks again, then Cancel).

  Also covered: Chromatic Orb (the element picker not cancellable, then Done casts), a
  summon placed and a summon cancelled, Mantle of Majesty, Twinned armed from the offer,
  the Beguiling rider end to end, Radiance, and Esc agreeing with the remote cancel. The
  rig gains `_caster`, which re-classes Aria and fills her slots (`_make` sets the
  maximum, not what remains), plus `_slots`, `_answer` and `_tap`.
- **Mutants, all 14 killed** (runner as under "Mutant runners", on `test_picks.py` and
  `test_offer.py`):
  - the spell kind fixed at `target`;
  - the wall cancel disarming;
  - Chromatic Done not casting;
  - the summon cancel keeping the creature;
  - the element picker cancellable;
  - Mantle's word picker cancellable;
  - the Attack → Spell undo removed;
  - the summon missing from the clear;
  - the spell arm unwired;
  - the Metamagic rows unclassified;
  - the multi count off by one;
  - the wall shape skipped;
  - Dispel's kind as `cell`;
  - Beguiling unwired.

  E-10's eighth mutant (`you.aoe` uncut) belongs to M5e.4.
- **Suite:** 167 / 0 in the container. The panel and determinism goldens are unchanged.
  No C++ changed.
- **Recorded behaviour changes on the DM console:** none. The spell Esc runs the same
  body through `cancel_spell`, and `cancellable` is not drawn.

**Findings.**

- **F-M5e-9: Animate Dead's finish raises on the DM console.** `_finish_animate_dead`
  (`main.py`, "Consume the corpse") assigns `placed_agents[i].removed_from_play = True`.
  The binding is `def_property_readonly` (`bind_types.cpp:136`). So choosing Skeleton or
  Zombie raises `AttributeError`, after the corpse pick and before anything is spent. No
  test covered it (`test_animate_dead.py` checks only flags and JSON). The fix is
  `self.bm.set_agent_removed_from_play(i, …)`, in both places. It needs its own commit,
  and your OK. Until then, the corpse test uses Revivify.
  **Fixed (2026-10-14, user OK, its own commit).** All three writes (the retire and both
  rollbacks) use `set_agent_removed_from_play`. `test_animate_dead_raises_an_undead` was
  watched failing with the `AttributeError` first. It now checks the corpse leaves play,
  a Skeleton stands on its square (the corpse's own position reads (-1, -1) once it has
  left play) and the 3rd-level slot is spent.
- **F-M5e-10: Mantle of Majesty's Command raises if no spell has been cast this session.**
  `pending_forcecage_sealed` is set only in `_activate_spell`. It is not in `__init__`, and
  Mantle's `_on_word` never sets it. So `_resolve_spell_cast` raises `AttributeError` on a
  session's first Mantle cast, and the DM console hits this too. The reverse also
  happens: Mantle inherits a Box choice left over from an earlier Forcecage. The fix:
  initialise it in `__init__`, and reset it in Mantle's `_on_word`. It needs its own
  commit, and your OK. `test_mantle_of_majesty_from_the_offer` sets the attribute itself,
  with a comment to drop that line once the fix lands.
  **Fixed (2026-10-14, user OK, its own commit).** `__init__` sets it to False, and Mantle's
  `_on_word` resets it with the other spell fields. The workaround line is gone, so
  `test_mantle_of_majesty_from_the_offer` is again a session's first cast. The new
  `test_mantle_command_does_not_inherit_a_forcecage_box` covers the leak. Both were watched
  failing first.
- **F-M5e-11: two pickers still open on the DM's screen when a player casts.** Wish
  (`SpellSelectionDialog`) and the Magic Circle / Hallow ward picker (`_element_dialog`)
  are DM widgets, not bus prompts. `spell_action` is on offer now, so a player who
  casts either spell opens that widget on the DM console. While it is up, nothing is
  armed and no bus prompt is live, so the next frame posts the player a fresh offer. The
  DM completes the picker. Nothing is spent until resolution, so no resource is lost.
  M5e.2 (Wish) and M5e.3 (the ward) close this, as planned.

**Not covered by a test:** a Bewitching Magic cast end to end (only projection and cancel,
through `test_every_wired_arm_projects_and_cancels`). Also untested: `wild_magic_bonus_cast`,
which is `_start_cast_spell("bonus")`, the same call `spell_bonus` makes, and Psionic
Sorcery's SP levels.

##### Handoff — M5e.1 landed *(written 2026-10-14)*

**State.**
- Three commits sit on top of "M5e.0, F-M5e-5" (`c765fcc`), each made at the user's request:
  - `f26ba9e` "M5e.1: the spell pipeline from the browser";
  - `54589be` "F-M5e-9: Animate Dead no longer raises when the undead is chosen";
  - `e06af78` "F-M5e-10: Mantle of Majesty's Command, first cast and after Forcecage".

  Each fix had its test written first and watched fail. `main` is sixteen commits ahead of
  `origin/main`, none pushed. Never push unasked.
- Suite: **167 / 0** in the container (2026-10-14). The goldens are unchanged. No C++
  changed, and no image rebuild is needed.
- `tests/test_picks.py` has 58 checks. The mutant runner is the one under "Mutant
  runners", running `test_picks.py` and `test_offer.py`.
- No tracked file is modified. The untracked scratch (encounters, `replay_log.txt`,
  `.DS_Store`, …) stays out of every commit.

**Read first:** "M5e — Step 0" (frozen; E-1 through E-10 are the contract), then "M5e.1 —
what landed" and its findings.

**Next, in order:**
1. **M5e.2:** Wish and DI as one bus `choice` prompt with `render="spell_browser"` (E-5).
   Then flip `divine_intervention`.
2. **M5e.3:** the ward toggle loop (E-6).
3. **M5e.4:** aim, then confirm, with `you.aoe` (E-8).

**Still open:** everything in the M5e.0 handoff's list, plus F-M5e-11 until M5e.2 and M5e.3,
and the gaps under "Not covered by a test" above.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.


##### M5e.2 — what landed *(2026-10-14, commit "M5e.2: Wish and Divine Intervention from the browser")*

E-5 as written: Wish and Divine Intervention each ask one bus `choice` prompt, and
`divine_intervention` is on the offer. Nothing on the wire changed.

- **The prompt.** `App._ask_spell_browser(idx, title, spells, on_pick)` posts one
  `kind:"action"` prompt through `_ask_actor`, owned by the caster's controller. It has an
  option per spell, labelled with the spell's name, in catalogue order, and
  `render="spell_browser"` (`prompts.SPELL_BROWSER_RENDER`). There is no `on_cancel`,
  because both spells pay on the pick, so a cancel has nothing to undo.
  - Wish: every spell of level 8 or lower, **389** options.
  - DI: level 5 or lower and in `CLERIC_DI_SPELL_NAMES`, **80** options. The cap is applied
    before the names, as the dialog applied it (see F-M5e-12).
  - The titles are the dialog's, unchanged.
- **The DM console's renderer.** `prompts.SpellBrowserRenderer(dialog, catalogue)` draws the
  prompt with the same `SpellSelectionDialog`. It looks each label up in `all_spells`, shows
  only those, and caps the tabs at the highest level on offer. A click commits that row's
  option id. The event loop now calls `renderer_dismissed()` after the dialog handles an
  event, so Esc or a click outside cancels the prompt, as it does for the element picker.
- **Two dialog changes**, both invisible on the DM console:
  - `show(spells=…)` narrows the list for one showing. The authoring callers pass nothing,
    so they still get the whole catalogue.
  - `_commit` closes the dialog *before* calling back. A callback that opens the browser
    again (Greater DI choosing Wish) was otherwise closed by the dismiss that followed it.
    The authoring callbacks do not re-open it, so nothing they do changes.
- **The client.** A prompt with more than 40 options (`FILTER_AT`) gets a filter box
  (`#prompt-filter`). The action offer stays under that number, so it gets no box. The box
  hides buttons whose label does not contain the text. What is typed never leaves the
  page: the answer is still an option id, and the two-send check still passes. The list
  scrolls inside the band (`max-height: 50vh`).
- **Wired.** `offer.WIRED` gains `divine_intervention`, so every S row is on offer.
  `test_offer` now asserts `WIRED` covers every pick row and every S row.
- **F-M5e-11 is half closed.** Wish no longer opens a DM widget for a player's cast. The
  ward picker is M5e.3.
- **Tests:** `tests/test_picks.py` has 62 checks, up from 58.
  - `test_wish_is_one_choice_prompt_over_the_bus`: the kind, render and owner, the 389
    labels in order, the wire option has no extra keys, and Fireball spends the 9th slot
    and is then cast free from a cell pick.
  - `test_a_cancelled_wish_spends_nothing`: the slot and Action are kept, and the offer is
    back.
  - `test_divine_intervention_from_the_offer`: enabled at Cleric 10, the 80 labels, and
    Guiding Bolt spends the use and the Action, then casts on Skarn for no slot.
  - `test_the_dm_console_draws_the_browser`: the dialog lists exactly the options; Esc
    cancels and spends nothing; a DM click answers with that row's id; a callback that
    re-opens the dialog leaves it open.
- **Mutants:** 7 of 8 killed (`test_picks.py` and `test_offer.py`):
  - the render hint dropped;
  - DI unwired;
  - no `renderer_dismissed()` after the dialog;
  - `_commit` dismissing after the callback;
  - Wish listing 9th-level spells;
  - the renderer committing the first option;
  - the renderer ignoring the prompt's options.

  The survivor is the DI list without its level cap. It is equivalent below Cleric 20,
  because every name in `CLERIC_DI_SPELL_NAMES` is level 5 or lower. At 20 it would add
  Wish, which is F-M5e-12's fix, so no test pins the cap.
- **Suite:** 167 / 0 in the container. The panel and determinism goldens are unchanged. No
  C++ changed.
- **Recorded behaviour changes on the DM console:** none visible. A Wish or DI cast opens the
  same dialog with the same rows, title and tabs. It is now a bus prompt, so the submit
  log records the answer or cancel, and a cast for a player can be answered by the player.

**Findings.**

- **F-M5e-12: Greater Divine Intervention never offers Wish, and its Wish would leak a free
  slot.** Found by reading. Not run, and not fixed.
  1. `_start_divine_intervention` adds "Wish" to the allowed names at Cleric 20. It also
     passed `max_level=5`, and the dialog applies the cap before the names, so Wish (9th)
     was always filtered out. M5e.2 keeps that order so the conversion changes nothing.
  2. If Wish were reachable, `_on_divine_intervention_pick` would set `_di_wish_free` and
     open Wish's browser. Cancelling that browser leaves `_di_wish_free` set, so the
     caster's next real Wish costs no 9th-level slot. Nothing resets the flag at the turn
     boundary.

  The fix: list Wish whenever `greater` holds, and give Wish's browser an `on_cancel` that
  clears `_di_wish_free` (the DI use stays spent; F-M5e-2 stands). It needs its own
  commit, with a failing test first, and your OK.
  Recorded in `memory/known_limitations.md` (Cleric section).

**Not covered by a test:** the client's filter box (only `node --check` and the two-send
check read `app.js`), and a phone drawing 389 buttons. Both want a look in a real browser.

##### Handoff — M5e.2 landed *(written 2026-10-14)*

**State.**
- Committed at the user's request as "M5e.2: Wish and Divine Intervention from the
  browser", on top of `e06af78`. It carries the code, the tests, this plan and the
  F-M5e-12 entry in `memory/known_limitations.md`. `main` is seventeen commits ahead of
  `origin/main`, none pushed. Never push unasked.
- Suite: **167 / 0** in the container (2026-10-14). The goldens are unchanged. No C++
  changed, and no image rebuild is needed.

**Next, in order:**
1. **F-M5e-12**, if you OK it: its own commit, with a failing test first.
2. **M5e.3:** the ward toggle loop (E-6). Check first whether the panel golden draws the
   ward widget (E-10).
3. **M5e.4:** aim, then confirm, with `you.aoe` (E-8).
4. A manual look at the filter box on a phone (Wish's 389 rows).

**Still open:** everything in the M5e.0 handoff's list, F-M5e-11's ward half until M5e.3,
and the gaps under "Not covered by a test" in M5e.1 and M5e.2.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.


##### M5e.3 — what landed *(2026-10-14, commit "M5e.3: the Magic Circle ward as a toggle loop")*

E-6 as written: the Magic Circle / Hallow ward picker is a toggle loop of plain `choice`
prompts. Nothing on the wire changed, and `expects` keeps its four members.

- **The prompt.** `App._ask_ward_types(idx, spell_name, chosen, on_done)` posts one
  `kind:"action"` prompt through `_ask_actor`, owned by the caster's controller, with the
  default render (the popup). Its options are the six rows of `MAGIC_CIRCLE_TYPE_OPTIONS`
  (five types and "↺ Reverse (trap them inside)"), each prefixed "✓ " when chosen, then
  Done. Picking a row re-posts the prompt with that row toggled (`chosen ^ {v}`). Done is
  labelled "Done (n chosen)", counting types only, or "Done (ward every type)" when none
  is checked, and calls the old `_on_ward` with the sorted values, as the widget's commit
  did. So the mask, Reverse and the empty-means-every-type rule are unchanged.
- **Cancel abandons the cast.** The prompt has no `on_cancel`. Nothing is armed or spent
  before the center pick, so a cancel leaves the turn as it was and the offer comes back.
  E-6 did not say what Cancel does; this was chosen because the widget had no cancel at all
  (Esc committed the selection), and a player's Cancel that casts would be F-M5e-3 again.
- **F-M5e-11 is closed.** No in-combat cast opens a DM-only widget for a player any more.
- **E-10's check.** The panel golden does not draw the ward widget (it is a cast-time
  modal), and it is unchanged. So is the determinism golden.
- `ElementPickerRenderer`'s docstring now names the ward's toggle loop. The multi-select
  `ElementPickerDialog` itself stays, for Elemental Adept in the character dialog.
- **Tests:** `tests/test_picks.py` has 65 checks, up from 62.
  - `test_the_ward_is_a_toggle_loop_over_the_bus`: the kind, `expects`, render and owner;
    the seven labels; no widget drawn; five picks (one taking Celestials back) each re-post;
    the ✓ marks and "Done (2 chosen)"; Done spends nothing and posts "Magic Circle: choose
    the center"; the tap spends the 3rd-level slot and lays a ward of Fiend | Undead,
    trapped inside.
  - `test_done_with_nothing_checked_wards_every_type`: all five types, kept out.
  - `test_a_cancelled_ward_spends_nothing`: after a toggle, both Kira's Cancel and the DM's
    Esc on the popup spend nothing, arm nothing, and bring back Cast a Spell.
- **Mutants, all 7 killed** (`test_picks.py`): the toggle keeping its state; the toggle
  committing at once; Done dropping the choice; no ✓ mark; the widget kept; a cancel that
  casts; the Done count including Reverse.
- **Suite:** 167 / 0 in the container. The goldens are unchanged. No C++ changed.
- **Recorded behaviour changes on the DM console:**
  - the ward is chosen from a popup at the caster's token, one toggle per click, instead of
    the centred multi-select widget;
  - Esc or a click outside now abandons the cast. Before, it committed what was checked and
    went on to the center pick.

##### Handoff — M5e.3 landed *(written 2026-10-14)*

**State.**
- Committed at the user's request as "M5e.3: the Magic Circle ward as a toggle loop", on
  top of `ab240c9`. It carries `gui/main.py`, `gui/prompts.py`, `tests/test_picks.py` and
  this plan. `main` is eighteen commits ahead of `origin/main`, none pushed. Never push
  unasked.
- No tracked file is modified. The untracked scratch (encounters, `replay_log.txt`,
  `.DS_Store`, …) stays out of every commit.
- Suite: **167 / 0** in the container (2026-10-14). No C++ changed, no image rebuild.

**Read first:** "M5e — Step 0" (frozen; E-1 through E-10 are the contract), then "M5e.3 —
what landed", including its recorded behaviour changes (Cancel on the ward now abandons
the cast).

**Next, in order:**
1. **F-M5e-12**, still waiting for your OK: its own commit, with a failing test first.
2. **M5e.4:** aim, then confirm, with `you.aoe` (E-8). E-10's eighth mutant (`you.aoe`
   uncut by fog) belongs here.
3. A manual look in a real browser: the filter box on a phone (Wish's 389 rows), and the
   ward loop's re-post on a phone.

**Still open:** everything in the M5e.0 handoff's list, and the gaps under "Not covered by
a test" in M5e.1 and M5e.2.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.



##### M5e.4 — what landed *(2026-10-14, commit "M5e.4: aim, then confirm, for an area spell")*

E-8 as written: for a remote caster, a tap on an area spell aims it, and a confirm casts
it. No wire field was added: `you.aoe` was already in Envelope 2.

- **The aim.** `net/picks.aiming(app, arm)` holds for the spell arm in its `area` shape
  (F-M5e-1: Line, Cone, Sphere, Square). A tap there sets `app._aoe_aim = (col, row)`,
  and nothing is spent or cast. A wall, a teleport and a door resolve on the tap, as
  before. E-8 named only the area shape.
- **The confirm.** While an aim is held, `picks.post` posts `_post_confirm` instead of the
  cell pick, in the same slot (`app._pick_prompt`). So `ensure` and `take_over` treat it as
  their own, with no change to either. It is a `kind:"confirm"`, `expects:"choice"` prompt,
  titled "Fireball: cast here?", with options `cast` ("Cast here") and `reaim`
  ("Re-aim"). It is owned by the controller, has the offer as parent, and uses
  `render="remote"`, so the DM console draws nothing.
  - **Cast here** drops the aim and runs `resolve_pick` on the held cell.
  - **Re-aim** drops the aim, and the next frame posts the cell pick again.
  - **Cancel** is the spell's Cancel (`cancel_spell`). A cancel by the DM is a take-over:
    it drops the aim and leaves the spell armed for the DM's click, as for the pick.
  - The projection key gains the aim.
- **The template.** `App._area_template(caster, sp, center)` is the hover preview's
  non-wall branch (`_aoe_cells`, then range and line of sight), lifted out. The preview
  calls it, and so does `picks.template`, so what a player confirms is exactly what the DM
  would see hovering there. `picks.template` cuts it to `cells(app, arm, actor)`, the
  explored mask with fog up.
- **The wire.** `Prompt` gains `aoe` (a frozenset, not on the prompt envelope), and
  `PromptBus.ask` takes it. `net/view._you` sends it as `you.aoe` under `reachable`'s
  gate: only with a `prompt_id` the viewer may answer.
- **The client.** `drawAoe` paints `you.aoe` in the DM preview's purple, under the tokens.
  It computes nothing (NN2). The confirm itself is an ordinary option list.
- **The aim's lifetime.** It is cleared by Cast here, Re-aim, either cancel, Esc
  (`cancel_spell`) and the turn boundary. It is in `_clear_pending_target_picks` and
  `_TARGET_PICK_COMPANIONS`. `aim()` ignores it unless the armed spell is in the area
  shape.
- **Tests:** `tests/test_picks.py` has 69 checks, up from 65.
  - `test_an_area_tap_aims_and_asks_to_confirm`: the tap spends nothing. Also checked:
    the confirm's kind, title, owner, render, options and parent; `aoe` equals
    `_area_template`; Kira's `you.aoe` has it and Wen's view does not; the prompt
    envelope carries no `aoe`; Re-aim brings back the cell pick with no overlay; a
    second tap and Cast here spend one slot; and the overlay is gone.
  - `test_a_cancelled_confirm_cancels_the_cast`: Kira's Cancel and the DM's Esc each spend
    nothing, arm nothing and leave no aim, and Cast a Spell is back on the offer.
  - `test_a_dm_click_during_the_confirm_casts_where_the_dm_clicked`: the take-over leaves
    Kira's late Cast here `not_live`. The cast lands on the DM's square, and the aim is
    dropped.
  - `test_the_aoe_is_cut_to_the_explored_mask`: with rows ≤ 3 explored, the template
    reaches into the fog, and `you.aoe` is exactly its explored part.
  - The four existing area-spell taps (Fireball, Wish's Fireball, both ward tests) now
    answer the confirm through `_cast_here`.
- **Mutants:** 10 of 11 killed (`test_picks.py` and `test_offer.py`):
  - `you.aoe` uncut by fog (E-10's eighth);
  - the tap resolving without an aim;
  - Cast here doing nothing;
  - Re-aim keeping the aim;
  - the confirm's Cancel keeping the spell;
  - the DM take-over keeping the aim;
  - the view ungated;
  - Esc keeping the aim;
  - the turn boundary keeping the aim (caught by `test_offer`'s clear check);
  - the confirm's template taken from another cell.

  The survivor is the aim left out of the projection key. It is equivalent: the aim
  changes only through the confirm's own answers, and those resolve the prompt, which
  forces a re-post anyway. The field stays, so the key still describes what the prompt
  shows.
- **Suite:** 167 / 0 in the container. The panel and determinism goldens are unchanged. No
  C++ changed, and no image rebuild is needed.
- **Recorded behaviour changes on the DM console:** none. The DM's click on an area spell
  still resolves at once, and the hover preview draws the same cells through
  `_area_template`.

**Not covered by a test:** `drawAoe` in a real browser (only `node --check` and the two-send
check read `app.js`). Also untested: an area spell with `moves_with_caster`, whose template
sits on the caster wherever the tap lands, and a Line or Cone aim.

##### Handoff — M5e.4 landed *(written 2026-10-14)*

**State.**
- Committed at the user's request as "M5e.4: aim, then confirm, for an area spell". It touches `gui/main.py`,
  `gui/net/picks.py`, `gui/net/view.py`, `gui/prompts.py`, `gui/net/static/app.js`,
  `tests/test_picks.py` and this plan. `main` is nineteen commits ahead of
  `origin/main`, none pushed.
- Suite: **167 / 0** in the container (2026-10-14). No C++ changed, no image rebuild.
- With M5e.4, every slice of E-9 has landed. M5e is complete, except for the items it
  left out by decision.

**Next, in order:**
1. ~~F-M5e-12~~: fixed 2026-10-16, see below.
2. A manual look in a real browser:
   - ~~the filter box on a phone (Wish's 389 rows)~~: **confirmed working by the user,
     2026-10-16**;
   - ~~the ward loop's re-post~~: **confirmed working by the user, 2026-10-16**;
   - ~~the `you.aoe` overlay with its confirm~~: **confirmed working by the user,
     2026-10-16**.
3. **M6**: reconnect, resync and restart.

**Still open:** everything in the M5e.0 handoff's list. Out of M5e by decision: refunds
(F-M5e-2), Overchannel (E-7), and aim-and-confirm for a wall's end point.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.


##### F-M5e-12 — fixed *(2026-10-16, user OK, commit "F-M5e-12: Greater Divine Intervention offers Wish")*

Both parts, each with its test written first and watched fail in the container.

- **Part 1, Wish never listed.** `_start_divine_intervention` caps only the Cleric spells
  at 5th level and lists Wish when `greater` holds. Wish comes in catalogue order, so the
  list has 81 options at Cleric 20, and 80 below that. At 20 the title reads "… (≤ 5th
  level, or Wish)".
  - `test_greater_divine_intervention_offers_wish` failed first on the missing label.
  - Now it checks the 81 labels, then follows the cast through: Wish spends the DI use and
    the Action, its list has 389 options, and its Fireball (aimed, then confirmed) costs no
    9th- or 3rd-level slot.
- **Part 2, the free Wish leaked.** `_ask_spell_browser` takes `on_cancel`, and Wish's list
  passes `_drop_di_wish_free`. Because a superseded prompt runs no callback,
  `_clear_pending_target_picks` also resets `_di_wish_free` at the turn boundary. It is in
  `_TARGET_PICK_COMPANIONS`.
  - `test_a_cancelled_greater_di_wish_leaves_no_free_wish` failed first with "the free Wish
    outlived its cancelled list", once part 1 had made Wish reachable.
  - Now it checks that the DI use stays spent (F-M5e-2), that the next real Wish pays its
    9th-level slot, and that the turn boundary clears the flag.
  - The turn-boundary reset goes beyond the fix as written. It closes the same leak by its
    other path, so it is in the same commit.
- **Mutants, all 5 killed:**
  - Wish still capped;
  - Wish listed below Cleric 20 (`test_divine_intervention_from_the_offer` counts 80);
  - no `on_cancel` on Wish's list;
  - `_ask_spell_browser` dropping `on_cancel`;
  - no turn reset.
- **Suite:** 167 / 0 in the container. The goldens are unchanged. No C++ changed.
  `tests/test_picks.py` has 71 checks.
- `memory/known_limitations.md` marks the entry fixed.
- **Recorded behaviour change on the DM console:** a Cleric 20's DI browser lists Wish,
  under its own 9th-level tab, and its title names it.


##### Handoff — M5e complete *(written 2026-10-16)*

**State.**
- **M5e is done.** E-1 through E-10 have landed, F-M5e-12 is fixed, and the user confirmed
  all three manual browser checks on 2026-10-16:
  - the filter box on a phone (Wish's 389 rows);
  - the ward loop's re-post;
  - the `you.aoe` overlay with its confirm.
- Last commits:
  - `06b3b6b` "M5e.4: aim, then confirm, for an area spell";
  - `043c2ce` "F-M5e-12: Greater Divine Intervention offers Wish".

  `main` is twenty commits ahead of `origin/main`, none pushed. Never push unasked.
- This plan update (the manual checks, and this handoff) is **uncommitted**.
- Suite: **167 / 0** in the container (2026-10-16). The goldens are unchanged. No C++
  changed, and no image rebuild is needed. `tests/test_picks.py` has 71 checks.
- `maps/TestDNDMap_terrain.json` shows as modified after a suite run. The **user** resets
  it, so never stage it. The untracked scratch stays out of every commit.

**Read first:** this handoff, then "M5e.4 — what landed" and "F-M5e-12 — fixed" for the
newest code (`net/picks.py`, the aim and confirm; `App._area_template`; `Prompt.aoe`;
`you.aoe`).

**Next: choose the next phase with the user.** Neither of these has a frozen Step 0 yet:
- **M4b**, the event stream and the animation: Envelope 3 (`/events`, gapless `seq`),
  and the `Move` animation as a per-viewer setting (D-M5-6b). It was deferred out of M5,
  so tokens still jump.
- **M6**, reconnect, resync and restart:
  - a client that reconnects resumes from its `seq`;
  - after a server restart, players re-join and re-claim their seats (R4);
  - NN7, a rotating autosave at the turn boundary, and restoring from it.

  M6's resume assumes Envelope 3's `seq`, so M4b probably comes first. Confirm the
  order with the user.

Whichever is chosen, follow the standing method: survey by reading only, write the
findings and the proposed decisions as a Step 0, and get the user's "agreed" before any
code.

**After that:**
- **M7**, hardening:
  - DM controls: pause, kick, reveal a region, take over any token, force the turn;
  - rate limits, join-code rotation, a session log;
  - optional per-agent fog.
- **M8**, real authentication. It gets its own document. Run the A1–A9 check at the end
  of every phase.

**Still open:**
- The Long Jump draws no Opportunity Attacks (C++).
- Fix B (C++).
- The flaky `test_menus.test_on_deck_row_deploys_its_group_on_click`.
- Row 5, if it comes back.
- No test covers the Bonus Action rows of `_ARMS_A_SPELL`.
- Out by decision: refunds (F-M5e-2), Overchannel for a player (E-7), and aim-and-confirm
  for a wall's end point.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.

##### M4b — Step 0 *(frozen 2026-10-16, user: "I approve the technical decisions you made")*

**Goal, in the user's words:** the board in the browser should look "as close as possible to
the DM screen version". Four choices were put to the user on 2026-10-16, and each one went
with the recommendation: motion **and** the token look; every move slides, on both screens;
all flashes reach players; the toggle switches off only the slide.

**Method.** I read the source and ran nothing. The survey covered the NPC playback
(`main.py:3020–3200`, `_drive_npc_turn_if_pending` `:5087`), `_spawn_flash` and its 15 call
sites, `_draw_one_agent`, the move commit (`:9740–9790`), the C++ recorders
(`combat.hpp:2046–2065`, `combat_core.cpp:155`, `combat_movement.cpp:198`,
`combat_turn.cpp:1515`), `net/link.py` `push_cycle` / `_push_views`, `net/server.py` `_send`,
`net/view.py` and `net/static/app.js`. Line numbers are as of `043c2ce`.

**Findings.**
- **F-M4b-1: the DM screen animates automated NPC turns and nothing else.** `run_npc_turn`
  records `NpcVisualEvent`s while `npc_recording_` is on, and `_npc_anim_start` plays them:
  - a slide along the route at `NPC_ANIM_CELLS_PER_SEC` = 10;
  - a typewriter bubble above the actor at 40 characters/s, then a 900 ms hold;
  - per outcome, a flash with its HP-bar drop, then a 300 ms beat.

  A killed token keeps drawing until the queue drains. Any click or key fast-forwards. The
  turn advances in `on_done`.
- **F-M4b-2: a human move jumps, and its route never reaches Python.**
  `BattleMap::moveAgent` keeps `lastMovePath_` and `CombatEngine::moveAgent` hands it to
  `recordNpcMove`, but that is gated on `npc_recording_`. `lastMovePath()` is not bound.
  *(Corrected at M4b.0, 2026-10-16, by a probe in the container: this said an Opportunity
  Attack splits a move into segments. It does not. `advanceMove` resolves every OA first and
  then commits the whole route once, to `dest` or, under Sentinel, to the halt cell, so a
  human move is always one `moveAgent` and one `Move`. The B-2 switch is still the right
  shape: it records at the commit, wherever the commit happens.)*
- **F-M4b-3: human flashes are Python-only.** About 15 `_spawn_flash` sites (attacks,
  Cleave, riders, saves) cover the human-driven path. None of them is an engine event, and
  none carries an HP value; the bar is live because the state already changed.
- **F-M4b-4: fog rules on the DM screen.** A mover fogged at playback time skips the slide
  and lands. A concealed actor's bubble is suppressed (`_npc_concealed_from_party`).
- **F-M4b-5: the push drops a cycle while one is in flight** (`_send`, D-M4e-4). That is
  right for a snapshot and wrong for a stream: an event frame dropped this way is a gap.
- **F-M4b-6: the browser token is a ringed circle**, while `_draw_one_agent` draws:
  - a team-coloured square (`faction_color`);
  - sprite art, or the name's first letter when the sprite is a one-letter placeholder;
  - grey when unconscious;
  - a red hatch on a corpse.

  `view.agents[].sprite` already carries the basename, and nothing serves the file.
- **F-M4b-7: `view.seq` is always 0.** No `events` frame exists, and the whole log rides in
  every view (`net/view.py:115`).

**Proposed decisions.**

1. **B-1: one global stream, projected per viewer.** `net/events.py` holds
   `EventStream`, the S3 seam: an append-only list of global events with a global index
   that never leaves the process. At each push cycle, every viewer's new global events are
   filtered by B-4 and appended to that **principal's** projected stream, which assigns
   that principal's gapless `seq`. Each socket keeps its own sent cursor into it. Envelope 3
   is unchanged: `move`, `announce`, `outcome` and `turn`.
2. **B-2: the sources, all pushed into the stream on the frame thread.**
   - NPC turns: what `take_npc_visual_events()` returns, appended where
     `_drive_npc_turn_if_pending` already drains it.
   - Human moves (F-M4b-2), a **C++ change**: a `record_moves` switch on `CombatEngine`,
     off by default, so RL and headless runs are untouched. While it is on, `recordNpcMove`
     records outside NPC turns too: one `move` per committed move, recorded after any
     Opportunity Attack resolves (see the F-M4b-2 correction). The GUI turns it on at start-up and drains the buffer after
     `begin_move`, `submit_decision` and `move_agent`, the same way it drains after
     `run_npc_turn`. No RNG draw changes, so the determinism golden must stay byte-identical.
   - Flashes (F-M4b-3): `_spawn_flash` appends an `outcome` with `hp_after: -1`, which
     means "no timed HP drop". `_npc_anim_apply_outcome` calls `_spawn_flash` too, so it
     must not append again: NPC outcomes come only from the engine's buffer.
   - Turn changes: `turn` at the boundary `push_cycle` already detects.
   - `log` is **not** a kind in M4b. The log stays in the view as it is (F-M4b-7);
     filtering it is separate work.
3. **B-3: delivery that never loses an event (F-M4b-5).** A cycle sends
   `[events?, view, prompt?]`. The `events` frame carries everything from the socket's
   sent cursor onward, and the net loop advances that cursor only after a successful
   send, publishing it in the `LiveViewer` snapshot the frame tick already reads. A dropped
   cycle therefore re-sends on the next one rather than leaving a hole. Events are not
   coalesced: if there are new ones, a cycle carries them. `view.seq` becomes the
   principal's cursor. Each principal keeps a 512-event ring for `GET /events?since=`; a
   `since` older than the ring answers with a fresh `view`, which is the resync contract
   M6 builds on.
4. **B-4: the filter, the same gates `_agents` uses, and drop rather than redact.**
   - An event whose agent, or whose `target` for an `announce`, is not in that viewer's
     `shown` set at projection time is dropped.
   - A `move` path is cut to its longest suffix of explored cells ending at the
     destination, so a slide never draws an unexplored corridor. If the destination is
     hidden, the event is dropped. If the cut leaves fewer than 2 cells, the event becomes
     a jump.
   - `hp_after` follows the band rule: an integer for (a)/(b) agents, a band for enemies.
   - Flash text is sent word for word ("Hit (7)" is damage dealt, which the table sees
     anyway).
   - A concealed actor's `announce` is dropped, as on the DM screen.
5. **B-5: the client plays exactly what the DM screen plays.** `app.js` copies the four
   timing constants and the draw order, and adds a `requestAnimationFrame` loop that runs
   only while a playback is active. When an `events` frame arrives, the client keeps the
   positions, HP and alive state from its current view for every agent the events name,
   and draws those until the queue drains. A view that arrives mid-playback is stored, but
   those agents keep their held state until playback ends, so a token never jumps and then
   slides. A tap on the board fast-forwards that viewer only. The DM's pace never waits for
   a browser.
6. **B-6: every move slides on the DM screen too** (the user's choice). A human move's
   `move` events start an `_npc_anim` playback with `on_done=None`. The move is already
   committed and the menus are already open, so the slide only changes what is drawn and
   defers nothing. A click on the board fast-forwards it, as it does an NPC turn today.
7. **B-7: one "Animate moves" toggle per viewer, on by default; it switches off only the
   slide** (the user's choice). With it off, a `move` lands at once, while bubbles,
   flashes and HP timing still play.
   - Browser: a checkbox in the session header, kept in `localStorage` and never sent.
   - DM console: an "Animate: ON/OFF" button under "Fog: ON", in session-only state, read
     by `_advance_npc_playback`.

   That button moves the panel golden if the golden draws that column, which needs checking.
8. **B-8: the browser token matches `_draw_one_agent`**:
   - a team-coloured square: the same RGB as `faction_color`, sent as CSS by the client;
   - the sprite art, or the first letter under the one-letter placeholder rule;
   - grey when unconscious, and a red hatch on a corpse.

   It keeps the name label and the band, because a player has no hover. The sprite is
   served by `GET /sprite/<basename>`, behind the same authentication as `/map.png`. It
   answers only for a basename some agent in **that viewer's** view carries; any other
   name gets 404, so the route can't be used to list the bestiary. It is cacheable, with an
   ETag.
9. **B-9: sub-slices.** Each one ends green, with its mutants killed.
   - **M4b.0:** the C++ `record_moves` switch and its binding, with a failing test first.
     This is the only rebuild.
   - **M4b.1:** `EventStream`, the projection and the filter (B-1, B-4), unit-tested with
     no socket.
   - **M4b.2:** the delivery (B-3): `events` frames, the cursor and `/events?since=`.
   - **M4b.3:** the playback in the browser (B-5) and the toggle (B-7).
   - **M4b.4:** human-move slides on the DM screen (B-6).
   - **M4b.5:** the token look (B-8) and `/sprite`.
10. **B-10: the oracle.**
    - The determinism golden stays byte-identical.
    - The event projection gets a byte-level test of its own, the way `build_view` did.
    - Mutants that must die:
      - a global index leaking into `seq`;
      - a gap after a dropped send;
      - a hidden agent's `move` or `announce` sent;
      - a path left uncut through unexplored cells;
      - an enemy's `hp_after` sent as an integer;
      - a flash appended twice for an NPC outcome;
      - `/sprite` serving a basename outside the viewer's view;
      - `record_moves` on by default.
    - Manual browser checks, owed to the user: an NPC turn played on a phone beside the DM
      screen; a player's own move sliding; the toggle off; the token look.

##### M4b.0 — what landed *(2026-10-16, uncommitted)*

- `CombatContext::record_moves_`, off by default and not serialized. `recordNpcMove`
  records when `npc_recording_ || record_moves_`. The other recorders are untouched.
- `CombatEngine::recordMoves` / `setRecordMoves`, bound as the `record_moves` property.
- `tests/test_npc_visual_events.py` gains 4 checks, written first and seen failing
  (`AttributeError: … no attribute 'record_moves'`):
  - the switch defaults off, and a human walk records nothing;
  - with it on, a human walk records one Move, origin to destination;
  - a walk parked at an OA records nothing at the park and one whole Move on resume;
  - the switch does not open the attack recorders.
- Suite **167 / 0** in the container. The goldens are unchanged. Nothing in Python uses the
  switch yet: M4b.1 adds the stream and M4b.4 turns the switch on.
- The probe that corrected F-M4b-2 ran in the container.

##### Handoff — M4b.0 committed *(written 2026-10-17)*

**State.**
- **M4b has started.** Its Step 0 is frozen (user: "I approve the technical decisions you
  made", 2026-10-16), with the user's four look choices as B-5 to B-8. **M4b.0 is
  committed** in "M4b.0: record_moves, so a human move records its route", which also
  carries the M5e-complete handoff and this Step 0.
- `main` is 1 commit ahead of `origin/main` (M4b.0). The twenty M5 commits before it were pushed by the user. Never push unasked.
- Suite: **167 / 0** in the container. The goldens are unchanged.
- **C++ changed in M4b.0, and the installed `.so` is rebuilt.** No image rebuild is needed.
  M4b.1 to M4b.5 are planned as Python and JS only.
- `maps/TestDNDMap_terrain.json` shows as modified after a suite run. The **user** resets
  it, so never stage it. The untracked scratch stays out of every commit.

**Read first:** this handoff, then "M4b — Step 0" (B-1 to B-10), including the F-M4b-2
correction: a human move commits once, after any Opportunity Attack resolves, so it is
one `Move`.

**Next: M4b.1, the stream and the filter (B-1, B-4), unit-tested with no socket.**
- `gui/net/events.py`:
  - `EventStream`: global, append-only, with an internal index that never leaves the
    process;
  - a per-principal projection that assigns a gapless `seq` and keeps a 512-event ring;
  - per-socket sent cursors for M4b.2.
- The filter uses the same gates `net/view.py` `_agents` uses: the `shown` set;
  `announce` dropped when its target is not shown or its actor is concealed; a `move`
  path cut to its longest explored suffix ending at the destination (dropped if the
  destination is hidden, a jump if fewer than 2 cells are left); `hp_after` as a band for
  enemies; flash text word for word.
- The wire kinds are `move`, `announce`, `outcome` and `turn`, spelled as strings. There is
  no `log` kind in M4b.
- The byte-level test goes in the style of the `build_view` oracle, and the B-10 mutants
  that belong to this slice must die.
- The sources (B-2) are wired in M4b.1 or M4b.4, whichever is cleaner:
  - NPC events where `_drive_npc_turn_if_pending` already drains them;
  - `_spawn_flash` appending an `outcome` with `hp_after: -1`, but **not** when
    `_npc_anim_apply_outcome` is the caller (no double flash);
  - `turn` at `push_cycle`'s boundary.
- **Watch for the B-2 / M4b.4 trap.** Once `record_moves` is on, the human-move drain
  after `submit_decision` must not steal a parked NPC turn's events. While an NPC turn is
  parked for a reaction, those events belong to `_resume_npc_turn` → `run_npc_turn`'s
  drain. The engine exposes no "NPC turn active" flag, so key the drain on Python's own
  state (`_reaction_finish` coming from `_resume_npc_turn`), or add a binding.

**Then:** M4b.2 delivery, M4b.3 the browser playback and toggle, M4b.4 human-move slides
on the DM screen, M4b.5 the token look and `/sprite`. Manual browser checks are owed at
the end (B-10).

**After M4b:** M6, then M7, then M8, as in the M5e-complete handoff. The "still open"
list there is unchanged.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.

##### M4b.1 — what landed *(2026-10-17, commit "M4b.1: the event stream and its fog filter")*

- **`gui/net/events.py`** (new; imports neither pygame nor the extension):
  - `EventStream`: the global list, its position internal. It is trimmed to the slowest
    projection's position, so a stream nobody projects holds nothing.
  - `Projection`: one per principal, opened at the head (a newcomer starts from a
    `view`). It has a gapless `seq`, a `RING_SIZE` = 512 ring, `since()` / `frame()`
    raising `Resync` outside the ring or ahead of it, and per-socket `attach` / `ack` /
    `detach` / `socket_frame`. Only `ack` advances a cursor, and never backwards or past
    the stream.
  - `visible(ev, sight)`: the B-4 filter. `Sight` is a frozen dataclass of everything it
    reads. `project()` takes a `Sight` or a callable, so a cycle with nothing new never
    walks the board.
  - Constructors: `from_npc`, `outcome`, `turn`. `band()` is the one band function, and
    `net/view._band` now calls it.
- **`net/view.py`**: `_drawn()` holds `_agents`' three gates, and `sight(app, viewer)` uses
  the same gates and the same `authorize` calls, so the filter and the view can't disagree.
- **Sources wired (B-2), two of four:**
  - `_drive_npc_turn_if_pending` appends the drained NPC events;
  - `_spawn_flash` appends an `outcome` (`hp_after` -1). It takes `stream=False` from
    `_npc_anim_apply_outcome`, so an NPC outcome is not appended twice.
  - `turn` moves to M4b.2, with `push_cycle`, which returns early with no transport. Human
    moves stay in M4b.4, with the B-2 trap.
- **`tests/test_events.py`** (new, registered beside `test_gameview.py`), 17 checks: 12
  with a hand-built `Sight`, 5 on the `test_gameview` scene (byte-level for the hidden
  creature, `sight` against `build_view`, and the two sources).
- **Mutants, all killed** (10), run on a container-local copy with a passing no-change
  control:
  - a global index into `seq`, as holes and as the starting value;
  - a hidden agent's `move` / `announce`, and a hidden `announce` target;
  - an uncut path;
  - an enemy's `hp_after` as an integer;
  - a double NPC flash;
  - a cursor advanced by building a frame rather than by `ack` (the gap after a dropped
    send);
  - `sight` without the view's gates;
  - the NPC drain not streamed.
- Suite **168 / 0** in the container. The goldens are unchanged. No C++ changed.

**Decisions this slice made that Step 0 did not spell out:**
- **`NpcVisualEvent.kind` is a plain `int`** across the binding (`combat_types.hpp:814`),
  not the enum. `events._NPC_KINDS` maps `0|1|2` to strings, and a test pins that table
  against the whole `NpcVisualEvent.Kind` enum, so a new C++ member fails the suite.
- **`outcome` HP fields are omitted rather than `-1`.** `hp_after` rides only for a
  `vitals` agent, and `band` only for anyone else, and only when the engine gave a value.
  A GUI flash sends neither, so "no field" is the client's one test for "leave the bar
  alone". This amends Envelope 3's `hp_after: -1`.
- **`outcome` carries `crit: true`** when the DM screen draws gold (`FLASH_CRIT`). `good`
  alone would turn a critical hit green on the player's screen.
- **`announce.target` is `null`** where the engine says -1 (an area, or nobody).
- **The DM principal is unfiltered**, as in `_agents`. The concealed-actor drop is the
  concealment gate in `shown`, so it applies to players only.
- **A party token's path is never cut**, as `_agent_fogged` never fogs one. A path cell
  counts as seen if any cell of the footprint at that origin is explored, which is the
  same rule.
- **Visibility is read at projection time**, which is the push cycle after the turn has
  resolved. That is the moment the DM screen's playback reads it too.

##### Handoff — M4b.1 landed *(written 2026-10-17)*

**State.** M4b.1 is committed in "M4b.1: the event stream and its fog filter":
- new: `gui/net/events.py` and `tests/test_events.py`;
- changed: `gui/net/view.py`, `gui/main.py` and `tests/run_all_tests.py`;
- this plan.

Suite 168 / 0, goldens unchanged. `.claude/mutants_m4b1.py` is the mutant harness. It is
untracked scratch, and it is not to be staged.

**Next: M4b.2, delivery (B-3).**
- `push_cycle`:
  - append `turn` at the boundary it already detects;
  - `project()` once per connected principal;
  - send `[events?, view, prompt?]` per socket, with `view.seq` = the principal's cursor;
  - `attach` a socket when it first appears, `detach` it when it goes.
- The net loop publishes each socket's sent cursor in the `LiveViewer` snapshot after a
  successful send. The frame tick `ack`s from it.
- `GET /events?since=` reads the ring and answers `Resync` with a fresh `view`.
- **A principal with no socket keeps being projected** (user's decision, 2026-10-17:
  "Keep updating their stream"). Every *seated* principal is projected each cycle, not
  only the connected ones, so a reconnect within the 512-event ring resumes from its
  `seq` (M6). The cost is one `sight()` board walk per principal, only on a cycle with new
  events. `forget` runs when the seat goes away (kick or revoke), never on a disconnect.
  This means `project()` is driven from the roster's seated principals, not from
  `live_viewers()`.

##### M4b.2 — what landed *(2026-10-17, commit "M4b.2: event delivery, the sent cursor and /events")*

- **`net/link.py`, the frame-tick half:**
  - `push_cycle` appends `turn(round, turn_idx, agent)` at the boundary it already
    detects, before anyone is projected, so it lands after the turn's own moves and
    flashes. It is not appended on the first cycle (`_net_turn` is `None`), whose boundary
    is only the server starting.
  - `_project_seated` projects **every seated principal** each cycle, connected or not
    (the user's decision). `retain` forgets a stream only when its seat goes, and
    `detach_gone` drops a socket's cursor only when the connection is gone.
  - `_push_views`: the first cycle a socket appears, its cursor is attached; after that it
    moves only by `ack(viewer.sent_seq)`.
  - `build_live(app, viewer, socket_id=None)` sends `[events?, view, prompt?]`.
    `view.seq` is the principal's `seq`, so the `events` frame and the view end at the
    same number. A cursor that fell off the ring is re-attached at the head, with no
    `events` frame, and the view is the resync.
  - `view_at_seq` is `GET /state`'s builder, so `/state` carries the `seq` too.
  - `events_since` is `GET /events?since=`'s answer.
- **`net/server.py`, the net-loop half:**
  - `_LiveConn.sent_seq` is set in `_send` only after every frame of a cycle went out.
    `LiveViewer` carries it to the frame tick.
  - `live_ids()` publishes every connection id, **including one mid-send**.
    `live_viewers()` still leaves that one out (D-M4e-4), and detaching on absence from it
    would lose the events the next cycle has to re-send.
  - `_contiguous` holds the client's one invariant: an `events` frame always starts at the
    `seq` this socket was last sent. A prefix the socket already holds is cut, which
    happens when two cycles were built from the same cursor and both went out. A frame
    that would leave a gap, or that comes before any view, is dropped, and the view in the
    same cycle resyncs.
  - `GET /events?since=` is authenticated like `/state` and answered on the frame tick
    through the command queue. It answers in one of three ways: an `events` frame; an
    `events` frame with an empty list when nothing is new; or a `view` when `since` is
    negative, ahead of the stream, or older than the ring. A missing or non-integer
    `since` is `400 protocol`. A server built without the handler answers every `since`
    with a view, which is always a correct answer.
- **`net/events.py`:** `Projection.attach(socket_id, at=None)`, `sockets()`,
  `EventStream.retain()` and `detach_gone()`.
- **Tests.** `tests/test_event_delivery.py` is new, with 12 checks, registered after
  `test_events.py`:
  - nine checks on the frame-tick half against a stand-in transport;
  - two on the net-loop half, on a server that is built but never started;
  - one end-to-end check over a real socket and the real route.

  `test_live.test_no_route_is_a_prefix` now lists `/events` in the pinned route table.
- **Mutants: all 16 killed**, plus a passing no-change control (`.claude/mutants_m4b2.py`,
  untracked scratch):
  - the B-10 gap, both ways: `sent_seq` published on a failed send, and the tick acking
    what it built;
  - `view.seq` not the principal's;
  - only connected principals projected;
  - a stream outliving its seat;
  - a socket mid-send detached, and `live_ids` dropping in-flight connections;
  - no `turn`, and a `turn` at startup;
  - a resent prefix not cut, a gap let through, and events sent before the first view;
  - a `since` outside the ring patched instead of resynced;
  - an attach that ignores the held view;
  - a ring overflow not re-attached;
  - the snapshot dropping `sent_seq`.

  `turn` at startup survived the first pass. The test opened no stream before the
  `None` boundary, so the event was trimmed either way. The test now opens the streams
  first.
- Suite **169 / 0** in the container. The goldens are unchanged. No C++ changed. The client
  (`app.js`) is untouched: it ignores an `events` frame until M4b.3.

**Decisions this slice made that the handoff did not spell out:**
- **A new socket's cursor starts at the view it already holds, not at the head.** The
  end-to-end test found this. The connect-time resync usually lands before the first
  push cycle sees the socket. Attaching at the head then silently skipped whatever
  happened in between. So `attach` takes the published `sent_seq` when there is one.
- **The net loop enforces contiguity (`_contiguous`), not only the cursor.** The ack
  crosses the seam a cycle late, so two cycles can be built from one cursor. The client
  contract M4b.3 relies on is simple: `since` always equals the client's `seq`, and a
  `view` sets that `seq`.
- **`/state` carries the principal's `seq`**, so a client can `GET /state` and then
  `GET /events?since=` from it. `POST /join`'s `server_seq` stays 0, because that answer
  does not wait for the frame tick.

**Found, not fixed (pre-existing, outside this slice):** `_push_views` builds with the
`Principal` captured at connect time. A DM rename replaces the roster's `Principal`
(`dataclasses.replace`), so `authorize` sees `seated != principal`, `build_view` raises
`PermissionError`, and that socket silently gets no more pushes until it reconnects. The
fix is probably to build with the principal `verify_credential` returns each cycle. It
needs its own failing test first. It is logged in `memory/known_limitations.md`.

##### Handoff — M4b.2 landed *(written 2026-10-17)*

**State.**
- M4b.2 is **committed** in "M4b.2: event delivery, the sent cursor and /events":
  - changed: `gui/net/events.py`, `gui/net/link.py`, `gui/net/server.py`,
    `tests/run_all_tests.py`, `tests/test_live.py`, `memory/known_limitations.md` and
    this plan;
  - new: `tests/test_event_delivery.py`.
- `main` is 3 commits ahead of `origin/main` (M4b.0, M4b.1 and M4b.2). Never push unasked.
- Suite **169 / 0** in the container, and the goldens are unchanged.
- Leave these alone:
  - `maps/TestDNDMap_terrain.json`, which a suite run modifies;
  - `.claude/mutants_m4b1.py` and `.claude/mutants_m4b2.py`, which are untracked
    scratch.

**Read first:** this handoff, then "M4b.2 — what landed".

**Next: M4b.3, the browser playback (B-5) and the toggle (B-7).**
- `app.js` handles `t: "events"`:
  - Apply a frame only when `since` equals the client's `seq`. The server guarantees this,
    so anything else is a bug: drop the frame and fetch `GET /events?since=`.
  - A `view` sets the client's `seq`.
  - While a playback runs, hold the named agents' position, HP and alive state from
    the previous view (B-5). A tap fast-forwards.
- It copies the four DM-screen timing constants and the draw order.
- The "Animate moves" checkbox goes in `localStorage`. It switches off only the slide.

**After that:** M4b.4 (human-move slides on the DM screen, with the B-2 trap), M4b.5 (the
token look and `/sprite`), the manual browser checks, then M6, M7 and M8. The "still
open" list is unchanged, plus the rename finding above.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.

##### Handoff — M4b paused for core-game fixes *(written 2026-10-19)*

**M4b is on hold.** The user wants to fix some "core game" issues first, before M4b.3.
Nothing below has started. When multiplayer work resumes, pick it up from here.

**State.**
- `1c00dea` "M4b.2: event delivery, the sent cursor and /events" is **committed and not
  pushed**. `main` is 3 commits ahead of `origin/main`: M4b.0, M4b.1 and M4b.2.
- Suite **169 / 0** in the container. The goldens are unchanged, and no C++ changed.
- Leave these alone:
  - `maps/TestDNDMap_terrain.json`, which a suite run modifies. Never stage it.
  - `.claude/mutants_m4b1.py` and `.claude/mutants_m4b2.py`, which are untracked
    scratch.

**Read first:** this handoff, then "Handoff — M4b.2 landed", then "M4b.2 — what landed".

**What M4b.2 put in place.**
- Each push cycle sends a socket `[events?, view, prompt?]`, and `view.seq` is that
  player's seq.
- The server guarantees that an `events` frame always starts at the seq that socket was
  last sent (`_contiguous`). A `view` resets the seq.
- A dropped send is re-sent on the next cycle, so there's no gap.
- Every seated player's stream keeps updating, whether connected or not.
- `GET /events?since=` answers from the 512-event buffer, or with a fresh `view` when
  `since` is outside it. `GET /state` carries the seq too.

**Next, when M4b resumes: M4b.3, the browser playback (B-5) and the toggle (B-7).**
- Handle `t: "events"` in `app.js`:
  - Apply a frame only when `since` equals the client's `seq`. Anything else is a bug:
    drop the frame and fetch `GET /events?since=`.
  - While a playback runs, keep the agents it names at the position, HP and alive state
    of the previous view. A tap fast-forwards.
- Copy the DM screen's four timing constants and its draw order.
- Add an "Animate moves" checkbox, saved in `localStorage`. It switches off only the
  slide.

**After that:**
- M4b.4: human-move slides on the DM screen. Watch the trap: once `record_moves` is on,
  the move drain after `submit_decision` must not take a paused NPC turn's events.
- M4b.5: the token look and the `/sprite` route.
- The user's manual browser checks.
- Then M6, M7 and M8.

**Still open.**
- The rename bug (in `memory/known_limitations.md`): after a DM renames a player, that
  player's socket gets no pushes until it reconnects. Fixing it needs the user's OK, its
  own failing test and its own commit.
- The rest of the earlier "still open" list:
  - Long Jump draws no Opportunity Attacks (C++);
  - Fix B (C++);
  - the flaky menus test;
  - Row 5;
  - no test for the Bonus Action rows of `_ARMS_A_SPELL`.

**Rules:**
- Container only. Never run `docker build`.
- Stage files by name. Never `-A`.
- Commit only when asked. Never push unasked.

##### M4b.3 — what landed *(2026-10-20, uncommitted)*

- **`gui/net/static/app.js`**, a new "Playback" section (B-5):
  - `seq`: a `view` sets it, and a contiguous `events` frame advances it. A frame whose
    `since` is not `seq` is dropped, and the client asks `GET /events?since=seq` (one
    request at a time). An `events` answer is applied if it still starts at `seq`. A
    `view` answer fast-forwards any playback and replaces the board. An answer that
    arrives after the socket has moved `seq` on is stale and ignored. A socket close sets
    `seq` to `null`, so nothing plays until the new socket's view.
  - The four timing constants and the three flash colours are copied from
    `constants.py`. `advance` follows `_advance_npc_playback` step for step: a move
    slides, an announce typewrites and then holds, an outcome flashes and drops the bar,
    then waits 300 ms. A `turn` event is skipped instantly. Draw order: tokens, flashes,
    then the bubble. The `requestAnimationFrame` loop runs only while a playback or a
    flash is live.
  - Hold: each agent named by a `move`, an `announce`, or an `outcome` that carries
    `hp_after` or `band` is held from the view in place when the frame arrives (the
    previous view). A later view does not release it; only the end of the queue does. An
    agent the previous view did not have (it walked into sight) is not drawn until its
    first move starts.
  - A tap on the board during a playback fast-forwards it, `_npc_anim_fast_forward`'s
    way, and is consumed: it does not answer a cell prompt.
- **B-7:** an "Animate moves" checkbox in the session header (`index.html`, `app.css`),
  on by default and saved in `localStorage` under `dnd.animate`. When it is off, a move
  lands at once, and announces, flashes and HP timing still play.
- **Tests:**
  - `tests/app_harness.js` loads the real `app.js` under node with a stub browser
    (elements, canvas, socket, `fetch`, clock and animation frames), so a check can step
    the client one frame at a time.
  - `tests/playback_checks.js` holds 17 checks.
  - `tests/test_playback.py` runs those checks and also pins the copied constants against
    `constants.py`. It is registered after `test_event_delivery.py`.
- **`test_live`'s storage rule** now allows `localStorage` for `ANIM_KEY` only. The
  credential rule (D-M4e-2) is unchanged.
- **Mutants: all 17 killed**, plus a passing no-change control. The harness is
  `.claude/mutants_m4b3.py`, untracked scratch. One equivalent mutant (`adopt` setting a
  position that the move overwrites in the same frame) pointed at dead code, and the dead
  code was removed.
- Suite **178 / 0** in the container. No C++ changed, and no Python under `gui/` changed.

**Decisions this slice made that Step 0 did not spell out:**
- **A GUI flash (no HP field) holds nothing.** On the DM screen the state has already
  changed by the time it flashes, so the player sees the live bar under the flash, as the
  DM does.
- **The side panels (token list, log) stay live** during a playback. Only the board is
  held. If that spoils a kill too early in practice, it is a follow-up.
- **Flashes and the bubble start above the name label**, which the DM screen does not
  draw.

##### Handoff — M4b.3 landed *(written 2026-10-20)*

**State.** M4b.3 is **uncommitted**:
- changed: `gui/net/static/app.js`, `index.html`, `app.css`, `tests/test_live.py`,
  `tests/run_all_tests.py` and this plan;
- new: `tests/app_harness.js`, `tests/playback_checks.js` and `tests/test_playback.py`.

Leave `maps/TestDNDMap_terrain.json` and `.claude/mutants_m4b*.py` alone.

**Next: M4b.4, human-move slides on the DM screen (B-6).** Two parts:
- Turn `record_moves` on, and drain the buffer after `begin_move`, `submit_decision` and
  `move_agent` into the stream.
- Start an `_npc_anim` with `on_done=None` for those moves.

**The B-2 trap:** the drain after `submit_decision` must not take a paused NPC turn's
events. B-7's DM-side "Animate: ON/OFF" button also belongs to M4b.4; check whether it
moves the panel golden.

**After that:**
- M4b.5, the token look and `/sprite`.
- The manual browser checks (B-10):
  - an NPC turn on a phone beside the DM screen;
  - a player's own move sliding (needs M4b.4);
  - the toggle off;
  - the token look.
- Then M6, M7 and M8.

**Rules:** container only, never `docker build`; stage by name; commit only when asked;
never push unasked.

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
