# Vistani Curse "Kickback" — Implementation Plan

**Immediate ask:** implement the **Vistani** monster (Curse + Evil Eye). This plan covers
**only the "kickback"** slice — *the Vistana takes psychic damage when a Curse it inflicted
**ends**, if that happens during combat.* The three Curse **options** (vulnerability, save/
check disadvantage, blinded/deafened) and **Evil Eye** (Charm/Hold Person 1/rest) are noted
for scope but specified separately.

> Status: **DONE** — kickback core + Persistence slice built + green 2026-07-06 (test_vistani.py,
> 10 tests). Decisions LOCKED (§Decisions, 2026-07-06). Curse-options + Evil Eye remain separate slices.

---

## The mechanic (from the statblock)

The Vistana curses a target; the curse lasts until it ends. **When the curse ends, the
Vistana takes psychic damage:**

| Curse option | Effect on target | Kickback to Vistana on end |
|--------------|------------------|----------------------------|
| Vulnerability | target gains vulnerability to a chosen damage type | **3d6 psychic** |
| Disadvantage  | disadvantage on checks + saves tied to one ability | **3d6 psychic** |
| Blind/Deafen  | target is blinded, deafened, or both              | **5d6 psychic** |

The kickback is **automatic** (no save), and lands on the **caster** (the Vistana), not the
target. It fires **whenever the curse ends by any means** — and only matters if that happens
mid-combat.

---

## Why this is not just `delayed_trigger`

The engine already has a general stored-damage mechanism (`delayed_trigger` /
`resolveDelayedEffect`, `combat_conditions.cpp:674`) used by Quivering Palm and Delayed Blast
Fireball. It is **the wrong tool here**, because:

| | `delayed_trigger` | Vistani kickback |
|---|---|---|
| **Damage recipient** | the condition's *target* (`cond.agent_idx`) | the *caster* — the Vistana (`cond.caster_idx`) |
| **When it fires** | owner detonates, or auto **on duration expiry** | whenever the curse **ends by any means** |
| **Save** | usually yes (`delay_requires_save`) | none — automatic |

`resolveDelayedEffect` damages `agent_idx` and uses `caster` only as the damage-multiplier
source. So we add a small, distinct mechanism rather than overloading the delayed path.

---

## The surface: where a condition can end

A curse-condition is removed through **two independent mechanisms**. The kickback must fire
from **both**, or curses that end via the "wrong" path will silently skip the kickback.

### Mechanism A — `removeAgentCondition(id)` (`combat_conditions.cpp:506`)
Shared chokepoint for three end-paths:
- **Successful repeat save** — `combat_turn.cpp:795` (and the incapacitating-save branch ~`:704`)
- **Concentration dropped** — `dropConcentration` (`combat_spells.cpp`) calls it per cascaded condition
- **Owner detonate** — `triggerDelayedEffect` (`combat_conditions.cpp:746`)

### Mechanism B — the `remaining` rebuild inside the tick loops (does **not** call `removeAgentCondition`)
- `tickAgentConditions` (`combat_conditions.cpp:520`, filter at `:580`) — natural duration expiry
- `tickAgentConditionsForCaster` (`:595`, filter at `:645`) — caster/concentration-scoped expiry

### Third implicit end — target death
Target dropped to 0 / `dead`. **LOCKED: no kickback on target death.** The tracking entry is
simply left on the dead agent so neither mechanism A nor B fires — the Vistana is not punished
for killing its victim. No extra gate is needed *provided* death paths don't route the curse
through `removeAgentCondition`; if any do (e.g. a death cleanup that clears conditions),
`onConditionEnded` must early-out when the target is `dead` / `hp_cur <= 0`. **Verify this
during build** (check `applyUnconscious` and any death-time condition cleanup).

---

## Recommended design: one `onConditionEnded` chokepoint

Do **not** sprinkle kickback logic across the 4+ removal sites. Centralize into a single
helper, and make both mechanisms call it.

### 1. Data — new fields on `ActiveAgentCondition`
In `battle_map.hpp:191`, alongside the `delay_*` block:
```cpp
// ── Caster "kickback" on curse end (Vistani Curse) ──────────────────────────
// When kickback_dice > 0, ending this condition (by ANY path) deals
// kickback_dice × d(kickback_die_size) of kickback_damage_type to the CASTER
// (caster_idx), automatically (no save). Recipient is always the caster.
int           kickback_dice        = 0;      // 3 or 5
int           kickback_die_size     = 0;      // 6 → d6
MagicDamage_t kickback_damage_type  = Psychic;
```
Bind all three in `rpg_bindings.cpp` next to the `delay_*` bindings (`:1779`) so the curse can
be authored from Python/JSON.

### 2. One helper — `onConditionEnded`
Declare in `combat.hpp` (near `resolveDelayedEffect`, `:2660`); define in
`combat_conditions.cpp`:
```cpp
void CombatEngine::onConditionEnded(BattleMap& bm, const ActiveAgentCondition& cond) noexcept;
```
Body: if `cond.kickback_dice <= 0` return. Otherwise roll the dice, then apply the damage to
`cond.caster_idx`, reusing the temp-HP-then-real-HP + `checkConcentrationOnDamage` +
`processDamageTaken` + `applyUnconscious` block from `resolveDelayedEffect:717-730` — **but
targeting the caster, with no save**. Log a clear line ("Curse rebounds on <Vistana>: N
psychic damage").

### 3. Wire both mechanisms to call it

- **Mechanism B (tick loops):** when `turns_remaining <= 0`, push the condition onto a
  deferred list and fire `onConditionEnded` **after** the `remaining` rebuild — mirroring the
  existing `auto_detonate` pattern (`combat_conditions.cpp:526`, fired at `:588-590`). This
  pattern exists *precisely because* applying damage mutates `activeAgentConditions_` and
  invalidates the loop iterators. Do the same in **both** `tickAgentConditions` and
  `tickAgentConditionsForCaster`.

- **Mechanism A (`removeAgentCondition`):** call `onConditionEnded` on the found entry
  **before** `erase` (`combat_conditions.cpp:510`). One edit here covers save-success,
  concentration-drop, and detonate simultaneously.

### 4. Re-entrancy / double-fire guards
- **No double-fire:** Mechanism B rebuilds `remaining` directly and never calls
  `removeAgentCondition`; Mechanism A only fires inside `removeAgentCondition`. They are
  disjoint — but confirm no single expiry path invokes both.
- **Recursion:** `onConditionEnded` → `applyUnconscious` (if the Vistana dies to its own
  kickback) → `dropConcentration` → `removeAgentCondition`. The deferred-list pattern in B and
  applying damage on a **copy** of `cond` in A both keep the container stable during the call.

---

## Files touched

| File | Change |
|------|--------|
| `battle_map.hpp` | +3 `kickback_*` fields on `ActiveAgentCondition` (`:191`) |
| `combat.hpp` | declare `onConditionEnded` (near `:2660`) |
| `combat_conditions.cpp` | define `onConditionEnded`; call from `removeAgentCondition` (`:510`) + both tick loops (deferred, `:588` / `:653`) |
| `rpg_bindings.cpp` | bind `kickback_dice` / `kickback_die_size` / `kickback_damage_type` (`:1779`) |
| `helpers.py` | **new** `_condition_to_dict` / `_dict_to_condition` (whole `ActiveAgentCondition`) — Persistence slice |
| `main.py` | save active conditions in `_save_agents` (`:9399`); reconstruct + `add_agent_condition` on load — Persistence slice |
| `test_vistani.py` (new) | kickback fires on each end-path; no-fire on target death; save/reload round-trip |

The kickback core is engine-internal (no GUI change). The **Persistence slice** adds the
Python save/load round-trip. Authoring the curse that *sets* `kickback_*` belongs to the
separate Curse-options slice.

---

## Decisions (LOCKED — user-approved 2026-07-06)

1. **Kickback on target death → NO.** The curse does not rebound when the cursed target dies.
   Implementation: leave the tracking entry on the dead agent (neither mechanism fires); add a
   `dead` / `hp_cur <= 0` early-out inside `onConditionEnded` only if a death path is found to
   route the curse through `removeAgentCondition`. See §Third implicit end.

2. **Persistence across save/reload → YES (serialize).** A curse can outlast a battle and
   affect a later one, so the live curse must survive save/reload. **This is a new slice** —
   see §Persistence below.

3. **Evil Eye → trivial, separate.** A class **action** (Charm Person / Hold Person) that
   **refreshes on a short or long rest**. Standard uses/day resource + existing spell-cast
   path; not part of this plan.

---

## Persistence (new slice — required by Decision 2)

**Finding:** the live tracking list `activeAgentConditions_` is **not serialized anywhere
today.** Save/load persists only the per-agent boolean condition *flags* (`Agent::Conditions`
— `blinded`, `stunned`, … at `main.py:9385`, which is actually the *spell's* condition list;
the agent-flag save is the per-agent block) — **not** the `ActiveAgentCondition` entries that
carry duration, save timers, `delay_*`, and the new `kickback_*`. So on reload today a curse's
*flag* may linger but its **tracking entry (and thus its kickback) is lost.**

To make the kickback survive reload, add a round-trip for the active-condition list:

1. **`_condition_to_dict` / `_dict_to_condition`** (helpers.py, mirroring the weapon/spell
   serializers) covering the fields that matter for an in-flight curse: `agent_idx`,
   `caster_idx`, `condition_name`, `turns_remaining`, `save_ability`, `save_dc`,
   `save_repeat_turns`, `next_save_turn`, `on_damage`, the `delay_*` block, **and the new
   `kickback_*` fields**. (Do the whole struct, not just kickback — a half-serialized entry is
   worse than none.)
2. **Save:** in `_save_agents` (`main.py:9399`), read `combat.active_agent_conditions` (already
   bound readonly, `rpg_bindings.cpp:3414`) → list of dicts → into the saved doc.
3. **Load:** reconstruct each `rpg.ActiveAgentCondition()` (see the existing build at
   `main.py:3751`) and re-add via `combat.add_agent_condition(bm, cond)`
   (`rpg_bindings.cpp:3409`) after agents are placed, so `agent_idx` / `caster_idx` still
   resolve.
4. **Round-trip discipline** ([[stats-serializer-roundtrip]] / [[weapon_serializer_roundtrip]]):
   every field must live in **both** `_condition_to_dict` and `_dict_to_condition`, or it
   resets on reload. Add a unit test that authors a curse, saves, reloads, and asserts the
   `kickback_*` fields + `turns_remaining` survive.

> Scope note: this promotes "serialize the whole active-condition list" to a first-class
> feature. It also fixes a latent bug — Quivering Palm / Delayed Blast Fireball and every
> duration-tracked condition currently lose their timers on reload. Worth calling out as a
> side benefit.

---

## Out of scope for this plan (separate slices)

- **Curse options themselves** — vulnerability field, checks/saves disadvantage tied to one
  ability, and `Blinded`/`Deafened` conditions. These map onto existing primitives and are the
  bigger half of "implement Vistani."
- **Evil Eye** — cast Charm Person / Hold Person 1/short-or-long rest (uses/day resource +
  existing spell path).
- **"During combat only"** falls out for free: if a curse never ends in-sim, `onConditionEnded`
  never runs.

Per standing scope guidance ([[feedback_scope_combat_sim]]): specialize existing pieces, add
narrow mechanism (the `kickback_*` fields + one chokepoint), don't build a general
"effect-on-condition-end" rule engine.
