# Condition-Triggered Auto-Effects — Implementation Plan

**Immediate ask:** a Vampire's **Bite should auto-apply to a creature it has Grappled**
instead of the DM manually selecting the weapon + target every turn. The broader ask:
*"there are other effects that automatically occur in certain conditions, so we need to
generalize that."*

> Status: **COMPLETE 2026-07-06** — all checkpoints (CP1 manual offer + CP2 NPC automation +
> CP3 data/tests) done, built, and live-confirmed working. Decisions locked (§Decisions).

---

## The family of "auto on a condition" effects

These already-or-soon-wanted behaviors are all the same shape — *when `<condition>` holds,
`<effect>` happens without the DM choosing it*:

| Effect | Condition | Effect kind | Status today |
|--------|-----------|-------------|--------------|
| Regeneration (Troll/Vampire) | turn start, HP > 0, not fire/radiant that turn | turn-start heal | **DONE**, hardcoded block in `beginTurn` (`combat_turn.cpp:397`) |
| Sunlight Vulnerability (vampires) | turn start, in Sunlight cell | turn-start radiant + suppress regen | **DONE**, hardcoded block (`combat_turn.cpp:357`) |
| **Vampire Bite** | vampire is Grappling a creature | **auto weapon attack** vs the grappled victim | **THIS PLAN** — engine can *resolve* it (`forceAutoHit` / `save_for_damage`), but nothing *initiates* it |
| Pack Tactics (Wolves) | an ally within 5 ft of the target | attack-roll Advantage | not started (`Monster Functionality Needed.md`) |

**Key realization — do NOT build one grand rule engine.** These effects differ too much in
*kind* (a passive HP tick vs. a full attack that spends the action economy vs. an
attack-roll modifier) to share one dispatcher cheaply. Per the standing scope guidance
([[feedback-scope-combat-sim]] / [[feedback_scope_combat_sim]]: *specialize existing
pieces, defer new infra, phase large features*), the generalization we want is **narrow and
concrete**: a reusable **"auto-use this weapon when I'm grappling a creature"** path, shared
by manual play and NPC automation. Pack Tactics and other modifier-style effects stay on
their own (Advantage) rails — they're noted here only to show why a universal engine is the
wrong altitude.

---

## What already works vs. the gap

- **Resolution is done.** The Bite weapon carries `auto_hit_if_grappled` + `save_for_damage`
  (`weapon.hpp:64`). When the vampire *attacks a creature it has Grappled* with the Bite,
  `forceAutoHit` (`combat_attack.cpp:1358`) turns a missed roll into a hit, or resolves it as
  a CON save vs `8+PB+mod`, then rolls damage + the HP-max drain rider. See
  [[vampire-multiattack-bite-save]].
- **NPC automation already bites.** The multiattack recipe `[[0,N],[1,1]]` seeded by
  `seedFromRecipe` (`combat_turn.cpp:1479`) fires claws-then-Bite at `st.target_idx`; the
  claws' Grappled rider grapples that same target, so the trailing Bite auto-hits it. Covered
  by `test_vampire_grapple_then_bite_combo`.
- **The gap is MANUAL play + robustness:**
  1. **Manual play has no prompt.** When the DM runs Strahd/a Spawn by hand (the St. Andral
     set-piece is DM-narrated), grapples a PC, then must *manually* pick the Bite weapon and
     the right target. Users have repeatedly hit friction here (see [[grapple-unarmed-strike]]
     "user confusion", [[vampire-support]] deferred "bite target-gate").
  2. **Automation is recipe-dependent.** A vampire that is *already* grappling a creature
     coming into its turn (grappled last round), or one whose statblock lacks the recipe, has
     no guarantee the grappled victim gets bitten — the driver targets by proximity/lowest-HP,
     not "the thing I'm holding."

---

## Decisions (LOCKED — user-approved 2026-07-06)

**D1 — Trigger context: BOTH** (manual + NPC automation), through one shared helper. The
whole point of the request is generalization; a manual-only fix would leave the automation
gap and vice-versa.

**D2 — Behavior when "grappling-by-me" holds — split by mode:**
- **Manual play → auto-OFFER.** A highlighted one-click "🧛 Bite (grappled)" button; the DM
  confirms. It routes through the normal attack economy, so **the target still gets its CON
  save** (`save_for_damage` → `forceAutoHit` resolves the Bite as CON save vs `8+PB+mod`:
  fail = full damage + HP-max drain, success = negated). Keeps DM control of a signature
  villain's turn; matches the repo's Legendary-Action / War-Priest *offer* pattern.
- **NPC automation → auto-ATTEMPT.** If the automated vampire is grappling a creature, the
  Bite is **automatically attempted** against that victim (no recipe required, and it
  overrides proximity/lowest-HP targeting for the Bite). Resolution is identical — the victim
  still rolls the CON save.

**Rejected:** fully-automatic no-click Bite in *manual* play (removes DM control); and a
generic data-driven `if <cond> then <effect>` table (over-infra for one concrete behavior —
revisit only if a 3rd auto-*attack* creature appears).

---

## Design — a narrow, reusable "auto-use-when-grappling weapon"

Introduce **one weapon-level intent flag** and reuse the existing resolution + targeting:

`weapon.hpp`: `bool auto_use_when_grappling = false;`
(*distinct from* `auto_hit_if_grappled`, which governs *resolution*; this governs *initiation
/ prompting*. A Bite sets both.) Round-trip it in `helpers.py` `_weapon_to_dict` /
`_dict_to_weapon` per [[weapon-serializer-roundtrip]] — this covers both encounter saves and
bestiary load. Bind it in `rpg_bindings.cpp` next to `auto_hit_if_grappled`
(`rpg_bindings.cpp:858`).

A small shared C++ helper answers "does agent A auto-bite, and whom?":

```cpp
// combat_attack.cpp (near forceAutoHit). Returns {weapon_idx, victim_idx} or {-1,-1}.
std::pair<int,int> CombatEngine::pendingAutoGrappleStrike(const BattleMap& bm, int atk) const;
//   for each weapon w of atk with w.auto_use_when_grappling:
//     find a creature v with v.conditions.grappled && v.conditions.grappler_idx == atk
//       (must still be a legal target: alive, not removed_from_play, in reach of w)
//     → return {slot, v}
```

Both call sites consume this one helper — no parallel logic.

### Checkpoint 1 — Manual play: auto-offer button  ✅ DONE  *(GUI-only, no rebuild for the button; C++ rebuild only for the flag + helper)*
Mirror the **War Priest (Bonus Attack)** conditional button (`main.py:1056`, generic
`_grant_extra_attack` at `main.py:3591`):
- After each attack/on turn refresh, if `rpg.pending_auto_grapple_strike(cur_idx)` returns a
  valid `(weapon, victim)`, show a highlighted **"🧛 Bite (grappled)"** button.
- Clicking it routes through the *normal* attack dispatch pre-seeded to that weapon + victim
  (reuse `_start_attack("action")` seeding, like the Unarmed mid-sequence resume in
  [[grapple-unarmed-strike]]), so `forceAutoHit` / `save_for_damage` / drain all fire
  unchanged and it correctly counts against the attack budget. **The victim's CON save
  therefore still applies** (per D2, manual) — the button doesn't bypass resolution, it just
  removes the manual weapon+target selection.
- Do **not** auto-click it — DM confirms (D2, manual).

### Checkpoint 2 — NPC automation: auto-attempt the Bite whenever grappling  ✅ DONE (built clean + tests green 2026-07-06)
Per D2 (automation), if the automated vampire is grappling a creature the Bite is
**automatically attempted** against that victim — no recipe required:
- In `runWeaponTurn` target selection (`combat_turn.cpp:1674` re-acquire region), when the
  current segment's weapon has `auto_use_when_grappling` **and** the agent is grappling
  someone, force `st.target_idx` to that victim for that segment (overrides proximity /
  lowest-HP just for the Bite).
- Covers the "already grappling coming into the turn, no recipe" case: if
  `pendingAutoGrappleStrike` is non-empty and the recipe is empty, append a single Bite
  segment so the Bite is attempted regardless of statblock recipe.
- Resolution is unchanged — the victim still rolls the CON save (`save_for_damage`).

### Checkpoint 3 — Data + tests  ✅ DONE 2026-07-06 (data edits; tests were authored in CP2, USER runs them)
- Data: the 8 auto-hit-bite vampires already have `auto_hit_if_grappled` bites
  ([[vampire-multiattack-bite-save]]); set `auto_use_when_grappling: true` on those same Bite
  weapons in `DND2024_MonsterStats.json` (hand-edit — the JSON bestiary is authoritative,
  never re-run the converter, [[feedback-json-bestiary-authoritative]]) and in the St. Andral
  encounter agents.
- Tests (`test_vampire.py`, USER runs them per [[feedback-user-runs-tests]]):
  - `pendingAutoGrappleStrike` returns the grappled victim only when actually grappling + in
    reach; empty otherwise.
  - Automation: a vampire *already grappling* at turn start (no recipe) bites that victim.
  - Regression: `test_vampire_grapple_then_bite_combo` still green (recipe path unchanged).

---

## Out of scope / deferred (noted, not built)
- **Pack Tactics**, and any other **modifier-style** auto-effect: belongs on the Advantage
  rails (cf. `hasAdvantageAura`, Reckless), not this weapon path. Separate small task.
- **Turn-start heals/damage** (Regeneration, Sunlight) stay as their `beginTurn` blocks — no
  value in retrofitting them onto the weapon path.
- Fully-automatic (no-click) Bite in *manual* play and a generic `if<cond>then<effect>` table
  — rejected in D2; revisit only on a future request.

## Serialization / workflow reminders
- New `Weapon` flag ⇒ **both** `_weapon_to_dict` **and** `_dict_to_weapon`
  ([[weapon-serializer-roundtrip]]), plus the `rpg_bindings.cpp` binding.
- USER builds (`rpg_map` Docker, [[feedback-build-handling]]) and USER runs tests
  ([[feedback-user-runs-tests]]); USER owns commits ([[feedback-user-owns-git-commits]]).
- Fix in C++ where the rule lives; no Python-side masking ([[feedback-fix-root-cause]]).
