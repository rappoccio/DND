# Balor Rework — Implementation Plan

Goal: bring the Balor in line with the 2024 Monster Manual by giving it two
distinct, mechanically-rich attacks, a bonus-action teleport, and a death
explosion. Two of the required pieces are **new, reusable engine features**
(Deny Reactions, Death Burst) and get their own sections; the rest is data +
small glue that reuses machinery already in the engine.

Design principle throughout (per repo conventions): **data-drive it, don't
special-case the Balor by name.** Every new field is added generically so the
next demon/devil that pulls, knocks prone, denies reactions, or explodes on
death gets it for free.

---

## Target statblock (2024 MM)

| Attack | Slot | Reach | Damage | Rider |
|---|---|---|---|---|
| **Flame Whip** | main_hand | 30 ft | 3d6+8 Force + 5d6 Fire | Pull target up to 25 ft straight toward the balor; target has the **Prone** condition (automatic, no save) |
| **Lightning Blade** | off_hand | 10 ft | 3d8+8 Force + 4d10 Lightning | Target **can't take Reactions** until the start of the balor's next turn (automatic, no save) |

- **Multiattack:** one Flame Whip **and** one Lightning Blade (never 2 of one).
- **Bonus action — Teleport:** the balor teleports up to 60 ft to an unoccupied
  space it can see. (MM: balor *or* an ally — we restrict to the balor; see
  Known Limitations.)
- **Death Throes (on death):** each creature in a 30-ft Emanation makes a
  DEX save (the balor's own CHA-derived save DC, 22 — see note below), taking
  9d6 Fire + 9d6 Force on a failure, half on a success.

The existing `BalorEmanation` (end-of-turn 5-ft, 3d8 Fire aura) and the
`Death Throes`/`Fire Aura`/`Magic Resistance` traits stay as-is.

---

## Part A — Data-only changes (`gui/DND2024_MonsterStats.json`)

These require **no new engine code** — every mechanic already exists.

### A1. Flame Whip (main_hand)
Replace the generic "Melee (Force)" reach-30 weapon with:
- `name`: `"Flame Whip"`
- `reach_ft`: 30
- `magic_damage_types`: **Force `3d6` first**, then Fire `5d6`
  (order matters: the flat `bonus_damage` attaches to the *first* magic
  damage type and scales with that type's resistance — combat_attack.cpp:464–486).
- `bonus_damage`: 8  (the +8 rides on Force)
- `conditions`:
  - `{ condition_name: "Pull", push_ft: 25 }` — reuses the Roper Reel path
    (combat_attack.cpp:4222); no save, fires on any proficient hit.
  - `{ condition_name: "Prone", requires_save: false }` — **depends on Part C.**
- `mastery`: `"None"`

### A2. Lightning Blade (off_hand)
Replace the reach-10 "Melee (Force)" weapon with:
- `name`: `"Lightning Blade"`
- `reach_ft`: 10
- `magic_damage_types`: **Force `3d8` first**, then Lightning `4d10`
- `bonus_damage`: 8
- `off_hand`: true  (keep — but see note below on the off-hand damage mod)
- `conditions`:
  - `{ condition_name: "DenyReactions", requires_save: false }` — **depends on Part B.**
- `mastery`: `"None"`

> ⚠ **Off-hand damage-mod gotcha.** The engine zeroes a positive ability mod on
> an `off_hand` weapon unless the wielder has Two-Weapon Fighting
> (combat_attack.cpp:462). The Balor's +8 lives in `bonus_damage`, **not** the
> ability mod, so it is *not* stripped — good. But confirm during testing that
> Lightning Blade still shows `3d8+8`, not `3d8`. If the flat bonus ever needs
> to come from STR mod instead, either give the Balor the `"Two-Weapon
> Fighting"` feat or drop the `off_hand` flag (it exists only to model the TWF
> mod penalty, which does not apply to monster multiattack).

### A3. Multiattack — lock 1 + 1
`multiattack` stays `[[0,1],[1,1]]` = slot 0 ×1 then slot 1 ×1. The recipe
(seedFromRecipe, combat_turn.cpp:1861) drives automated turns and already
guarantees exactly one of each. Leave `num_attacks: 2` as the legacy fallback.
**Action item:** add a test asserting an automated Balor turn issues one
Flame Whip and one Lightning Blade (not 2×either).

### A4. Death Throes spell entry (`gui/spells.json`) — **depends on Part D.**
Add a `BalorDeathThroes` spell (Sphere, radius 30, DEX save, 9d6 Fire + 9d6
Force, half on save) and reference it from the Balor's death-burst field. The
save DC is the balor's implicit CHA-derived DC (22) — no explicit per-spell DC.
Data authored here; trigger wired in Part D.

---

## Part B — NEW FEATURE: Deny Reactions (do this first)

**What:** an effect that prevents a creature from taking any Reaction until the
start of the source's next turn. Reusable by any weapon/spell/feature.

**Why it needs real work:** reaction eligibility is gated in ~30 scattered
sites, each testing `cond.reaction_used` (and usually `cond.incapacitated`).
There is no central predicate and no "reactions denied" flag today. Simply
setting `reaction_used = true` (as the Monk Open-Hand rider does,
combat_riders.cpp:1590) is *wrong here* because `beginTurn` resets
`reaction_used` at the start of the **target's** turn — if the target acts
before the balor's next turn, they'd wrongly regain their Reaction.

### B1. State
- Add `bool reactions_denied = false;` to `Agent::Conditions`.
- **No serializer work.** Conditions are session-only (not persisted), so the
  flag needs no `dict_to_stats`/save-block round-trip.

### B2. Central predicate (recommended — avoids 30 divergent edits)
Introduce a single helper and route the gates through it:
```cpp
// true if this creature may still spend its Reaction right now.
bool CombatEngine::canTakeReaction(const Agent::Conditions& c) const noexcept {
    return !c.reaction_used && !c.incapacitated && !c.reactions_denied;
}
```
Then replace the `reaction_used || incapacitated` guards at the reaction sites
with `!canTakeReaction(cond)`. Sites (from grep, verify at implementation):
combat_movement.cpp:569,720; combat_riders.cpp:1256,1388,1414,1615,1648,2119;
combat_resources.cpp:424; combat_attack.cpp:744,771,854,882,926,1016,1057,1079,
1098,1115,1261,1323,1348,1419,1493,1543,1752,1777,1802,1831,1861,1908,3171.
- Some sites check only `reaction_used` (not `incapacitated`); those are the OA
  offer points. Denying reactions should also block OAs, so `canTakeReaction`
  is the correct unifying gate there too.
- **Minimal fallback** (if a 30-site refactor is judged too risky in one pass):
  OR `|| cond.reactions_denied` into each guard. Same behavior, larger diff.

### B3. Application + name mapping
Add a `"DenyReactions"` branch to `addAgentCondition` (combat_conditions.cpp:789
chain) that sets `ac.reactions_denied = true`. This makes it usable from the
generic weapon-condition path (Part A2) and from any spell.

### B4. Duration / teardown — "until the source's next turn"
- Key the condition's duration to the **caster (balor)**, so it expires at the
  start of the balor's next turn via the existing per-caster condition
  decrement — mirror an existing "until start of your next turn" effect
  (e.g. HasteLethargy pattern) rather than the target-keyed default.
- Route the flag clear through the condition-teardown chokepoint
  (`onConditionEnded` / `clearSpellConditionEffect`, per the Condition Teardown
  Chokepoint memory): on end, set `reactions_denied = false`.
- Guard `applyIncapacitated`/`applyUnconscious` don't need changes (those
  already block reactions), but make sure the flag is cleared on death cleanup
  so a revived/aided creature isn't stuck reaction-locked.

### B5. Tests (`gui/test_deny_reactions.py`)
- A creature hit by a DenyReactions rider cannot take an OA when an enemy leaves
  its reach before its own next turn.
- The lock is released at the start of the *source's* next turn (not the
  target's turn, if the target acts first).
- A creature that already used its reaction is unaffected (no double-charge).

---

## Part C — Auto-Prone weapon condition (small)

**What:** let a weapon apply the Prone condition automatically on hit (no save).

`"Prone"` is intentionally absent from `addAgentCondition`'s name→flag map
(only Topple/knockdown set `conditions.prone`, each via a save). Flame Whip's
prone is automatic, so:

- Add a `"Prone"` branch to `addAgentCondition` that sets `ac.prone = true`
  (mirror the `applyProne` flag-set used by the knockdown path). This makes the
  generic weapon-condition path (Part A1) apply prone with `requires_save:false`.
- Confirm end-of-prone teardown already exists (standing up / condition expiry);
  no new teardown expected since `prone` is a standard flag.
- Test: a Flame Whip hit leaves the target Prone with no save rolled.

> Alternative considered: reuse the Topple/knockdown machinery with the save
> skipped. Rejected — a name→flag `"Prone"` branch is smaller, and it makes
> Prone symmetric with every other condition the generic path can already apply.

---

## Part D — NEW FEATURE: Death Burst (on-death AoE) — generic

**What:** when a creature dies, it detonates a stored AoE effect centered on
itself. Reusable for any "explodes on death" monster (a common trope).

### D1. Trigger point
The single death cleanup chokepoint is `applyUnconscious` (Death Chokepoint
memory — it already fires for `is_npc` corpse handling). Add the death-burst
resolution there, gated on the dying agent actually dying (hp ≤ 0 / becoming a
corpse), **after** the existing cleanup so logs land in narrative order.

### D2. Data model
- Add a data-driven field, e.g. `std::string death_burst_spell` on `Agent::Stats`
  (empty = no burst), naming a spell in `spells.json`. Serializer round-trip in
  `dict_to_stats` + `main.py` save block.
- Balor: `death_burst_spell = "BalorDeathThroes"`.
- The spell (`gui/spells.json`, Part A4): Sphere, `radius:30`, `attack_type`
  Save, `save_ability:SaveDex`, damage 9d6 Fire + 9d6 Force, **half on save**.
  Save DC = the balor's implicit CHA-derived DC (22) — no explicit per-spell DC,
  same as every other Balor spell.

### D3. Resolution
Reuse the existing AoE engine: center on the dying agent's origin, call the
same `resolveAoeTargets` + `pruneBlockedCells`/total-cover path AoEs use (Total
Cover Chokepoint memory) so walls block the blast. Roll the DEX save per target,
full damage on fail, half on success. The caster for the burst is the dying
agent (already off the board — pass its last origin/stats; verify the AoE path
tolerates a downed/removed caster, since applyUnconscious runs mid-death).

### D4. Edge cases
- Do not damage the already-dead balor itself (exclude the source).
- Allies **and** enemies in range are hit (Death Throes is indiscriminate) —
  do not apply Evoker safe-target/Sculpt filtering.
- Fire damage: many demons are Fire-immune; resistances/immunities apply
  normally through the standard damage path (no special-casing).
- Multiple simultaneous deaths (AoE that drops several): each burst resolves at
  its own `applyUnconscious`; guard against infinite chains (a burst that kills
  another burster) — cap or process iteratively; note in tests.

### D5. Tests (`gui/test_death_burst.py`)
- Killing the Balor damages every creature within 30 ft; a creature at 35 ft is
  untouched; a wall between blocks the blast.
- Failed DEX save = full 9d6+9d6; success = half.
- Fire-immune target takes only the Force half.
- The dead Balor is not self-damaged; no infinite burst chain.

---

## Part E — Teleport (bonus action, balor-only)  ✅ DONE 2026-07-21 (data-only)

**Implemented as data-only** — no engine/GUI code. Added a level-0 `BonusAction`
`BalorTeleport` spell (`spells.json`, `teleportation_spell:true`,
`teleport_range_ft:60`) to the Balor's `spell_indices`. It rides the existing
generic teleport-destination flow (`_start_cast_spell` → `_resolve_teleport_spell`,
main.py:11489), the same path Misty Step/Dimension Door use; `casting_time
BonusAction` routes it into the bonus-action cast menu and spends the bonus
action; level-0 + no uses = at-will, no slot. **Caveat:** range/LOS are advisory
only — `isValidTeleportDestination` checks bounds+terrain-block, not distance or
LOS (pre-existing, shared by every teleport spell). Balor-only, manual-only (no
automation planner matches a damage-less Transport spell) — matches Limitations
#1/#3.

- Bonus action. Reuses `teleportAgent` + `isValidTeleportDestination`
  (combat.hpp:1237,1284). Mirror the manual "pick a destination cell" GUI flow
  used by Shadow Step / Psychic Teleportation for human play.
- Range: 60 ft, line-of-sight, unoccupied destination.
- **Ensure it is spent as a bonus action** (checks/consumes the bonus-action
  economy) — watch the `bonus_used` draw/click gotcha that dead-keys
  action-economy buttons (Haste Button bonus_used memory); model the button so
  it isn't suppressed by an over-broad `not self.bonus_used` guard.
- NPC automation: out of scope for this pass (manual GUI only) unless trivially
  free via an existing bonus-action-teleport driver hook.

---

## Known Limitations (record in-repo)

1. **Teleport is balor-only.** MM allows the balor to teleport *itself OR a
   willing ally within 60 ft*. We implement the balor-only case; the "teleport
   an ally" branch is intentionally omitted for simplicity.
2. **Death Throes save DC is 22, not 20.** We use the balor's implicit
   CHA-derived save DC (22) rather than the RAW DC 20, to avoid a per-spell DC
   override. Minor deviation, deliberate.
3. Teleport is **not** auto-driven in NPC automation in this pass (manual only).

---

## Suggested build order

1. **Part B (Deny Reactions)** — new feature, do first; land + test in isolation.
2. **Part C (Auto-Prone branch)** — tiny, unblocks Flame Whip prone.
3. **Part A (JSON data)** — Flame Whip + Lightning Blade + lock multiattack.
   Depends on B3 (`DenyReactions`) and C.
4. **Part D (Death Burst)** — new feature; author `BalorDeathThroes` + wire trigger.
5. **Part E (Teleport)** — GUI bonus-action flow.

Each part is independently buildable/testable. User runs builds and the test
suite (per repo rules); Opus finishes edits and hands off.

---

## Serializer / round-trip checklist (don't skip)

- `reactions_denied` (Conditions) — **session-only, no serializer work.**
- `death_burst_spell` (Stats) — `dict_to_stats` **and** `main.py` save block.
- New weapon conditions ("Prone"/"DenyReactions") ride the existing
  `w.conditions` serialization (`_weapon_to_dict` / `_dict_to_weapon`); confirm
  `push_ft`, `requires_save`, `condition_name` all round-trip.
- `BalorDeathThroes` in `spells.json` uses the same fields BalorEmanation does;
  verify Sphere radius + explicit save DC survive `_spell_to_dict` round-trip.
