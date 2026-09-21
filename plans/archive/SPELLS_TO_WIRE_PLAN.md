# Spells to Wire — Implementation Plan

Wires the seven spells listed in `Spells to wire.md`. The file's order holds, with one agreed swap:
**Animal Shapes moves to last** (it is the only one needing both a C++ API split and new content data,
and nothing depends on it).

Bless → Haste → Aid → Dispel Magic → Animate Dead → Animate Objects → Animal Shapes.

## Current state (verified)

All seven already exist in `gui/spells.json`, but every one of them is an **inert scraped stub**:
the flavor text is right and the level/school/range are roughly right, but the mechanics are absent.
Concretely:

- Bless, Haste, Animal Shapes, Animate Dead, Animate Objects are typed `Harm` with `geometry: Single`
  and an empty `conditions` list, so casting them today rolls nothing and does nothing.
- Aid is typed `Heal` with no `healing_type` dice — it heals 0.
- Dispel Magic is typed `Harm` / `Automatic` with no damage — a no-op.
- None of them has any engine-side support.

The engine already has most of the machinery these spells need. The gaps are listed in Phase 0.

## What already exists and gets reused

| Need | Existing mechanism |
| --- | --- |
| Buff spell that only applies a condition | `Spell::Help` type — the `Help` early-out in `executeSpell` (combat_spells.cpp:1013) marks a "hit" so condition application runs, skipping damage/healing. It sits in the loop that serves **both** Single and Multiple geometry (combat_spells.cpp:787), so a `Help` + `Multiple` spell like Bless routes correctly. Persistent-zone creation is already suppressed for `Help` (combat_spells.cpp:2005). |
| N targets, +1 per upcast level | `Spell::num_targets` + `targets_per_upcast_level`, capped by the engine (`getNumTargetsForSpell`). GUI collects N clicks (`_dispatch_geometry`, main.py:8983). |
| Temporary AC | `Stats::ac_temporary_modifications` (the Shield spell's +5 channel). |
| An extra action | `Stats::wild_magic_extra_action` + a GUI button that resets `self.action_used` (main.py:18966). There is no engine-side action budget — actions are GUI-gated. |
| Spawning a controlled creature | `BattleMap::spawnAgent` + `summoner_idx` / `summon_spell` / faction inheritance, driven from `_resolve_summon` (main.py:9709). Non-destructive (does not rebuild `placedAgents_`). |
| Shapechanging into a beast | `CombatEngine::activateWildShape` / `deactivateWildShape` (combat_resources.cpp:3183), fed by `beast_forms.json`. |
| Bestiary blocks for the summons | `DND2024_MonsterStats.json` already contains Skeleton, Zombie, Animated Armor, Animated Flying Sword, Animated Broom, Animated Rug of Smothering, and 91 beasts with a CR in `meta.cr`. |

---

## Phase 0 — Shared infrastructure

These three items are prerequisites. Bless/Haste/Aid all need a *reliable* teardown, and Dispel
Magic needs to know what level a spell was cast at. Doing them first is what keeps the rest small.

### 0.1 — Unify condition teardown into ONE chokepoint  ⚠️ enabling refactor

Today a condition's "undo" logic is duplicated in **four** places:

1. `clearSpellConditionEffect` (combat_spells.cpp:2985) — used by `dropConcentration`.
2. `tickAgentConditions` (combat_conditions.cpp:865) — an inline if/else chain for duration expiry.
3. `tickAgentConditionsForCaster` (combat_conditions.cpp:957) — a third copy.
4. `beginTurn`'s save-success paths (combat_turn.cpp:782 and :921) — a fourth copy, which calls
   `removeAgentCondition` and *then* clears the flags by hand.

`removeAgentCondition` itself only fires `onConditionEnded`, which handles the Vistani curse teardown
and nothing else — so a caller that uses it *without* also calling `clearSpellConditionEffect`
(combat_conditions.cpp:399/1194, combat_resources.cpp:815) leaves the agent's flags set.

That is survivable for flag-only conditions like Blinded. It is **not** survivable for Aid (must give
back exactly the HP maximum it granted), Haste (must remove +2 AC, restore speed, and inflict the
end-of-spell lethargy), or Dispel Magic (which ends conditions by yet another path). A missed teardown
is a permanently buffed creature.

**Change:** make `onConditionEnded` THE single end-of-condition chokepoint, in the spirit of the
existing `applyUnconscious` (death) and `applyIncapacitated` chokepoints.

- Fold the body of `clearSpellConditionEffect` into `onConditionEnded` (flags first, then the curse
  teardown/kickback that already lives there).
- Delete the inline copies in `tickAgentConditions`, `tickAgentConditionsForCaster`, and
  `beginTurn`; those sites collect the ended conditions, rebuild `activeAgentConditions_`, and *then*
  call `onConditionEnded` on each — the deferral pattern `tickAgentConditions` already uses for curse
  kickbacks and auto-detonations. This matters: Haste's teardown *adds* a new condition (lethargy),
  which would invalidate iterators if fired mid-loop.
- Keep `clearSpellConditionEffect` as a thin forwarder (or remove it and update its ~6 call sites).

**Risk:** touches every condition in the game. Mitigated by the existing suites
(`test_conditions.py`, `test_condition_saves.py`, `test_sanctuary.py`, `test_frightened.py`,
`test_petrified.py`, `test_vampire.py`, `test_misty_escape.py`, `test_vistani.py`) — this refactor
should be built and run green **before** any spell work starts.

### 0.2 — Record the cast level on active effects

`executeSpell` never writes `action.slot_level` back into `sp.level` (upcasting only inflates dice —
combat_spells.cpp:733), so an upcast spell's *actual* level is lost the moment it lands. Dispel Magic
cannot work without it, and Aid's "+5 per level above 2" needs it too.

**Change:** add `int cast_level = 0;` to `ActiveSpellEffect` and `ActiveAgentCondition`
(battle_map.hpp:162/173), set from `max(action.slot_level, sp.level)` wherever those are created,
expose it in the bindings, and persist it in main.py's condition save/restore block (main.py:11471 /
12938). `ActiveTerrainEffect` already carries `spell_idx`; give it `cast_level` too so Dispel can
reach a Web/Grease.

### 0.3 — Ability-scoped save advantage

`curseSaveDisadvantage(bm, idx, ability)` (combat_core.cpp:337) already gives Disadvantage on saves of
one named ability. There is no symmetric "Advantage on DEX saves" — `Agent::hasAdvantage()` is a
blanket flag. Haste needs the scoped version.

**Change:** add `saveAdvantageFor(bm, idx, ability)` alongside it, consulted in `rollSpellSave`
(combat_spells.cpp:239), in the condition-save site (combat_spells.cpp:1794), and in the turn-start
condition saves (combat_turn.cpp:761/900). Keep it data-driven off a Stats flag, so future
"advantage on X saves" effects reuse it.

---

## Phase 1 — Bless

*Level 1 · Concentration · 3 creatures, +1 per slot level above 1 · targets add 1d4 to attack rolls
and saving throws.*

**Data (`spells.json`):** `type: Help`, `geometry: Multiple`, `num_targets: 3`,
`targets_per_upcast_level: 1`, `requires_concentration: true`, `duration: 10` (1 minute),
`conditions: [{condition_name: "Blessed", requires_save: false}]`.

**Engine:**
- New `Stats` field `blessed` (bool). Register `"Blessed"` in `addAgentCondition` (set it) and in the
  Phase-0.1 teardown (clear it).
- **Attack rolls:** `rollToHit` (combat_attack.cpp:224) takes `const Agent::Stats&`, so the flag must
  live on Stats, not Conditions — exactly like the Paladin's `sacred_weapon_bonus`, which is read two
  lines below. Add `if (attacker.blessed) r.attack_mod += roll(4);` and surface the d4 in the existing
  one-line to-hit log.
- **Spell attacks:** same addition in `rollSpellAttack` (combat_spells.cpp:207).
- **Saving throws:** `saveModFor` (combat_core.cpp:305) is the single source of truth for save
  modifiers, so the d4 goes there. It is currently `const noexcept` and `roll()` is not const —
  **decision needed**: drop the `const` from `saveModFor` (its call sites are all non-const, so this
  looks clean) rather than making `rng_` mutable, which would hide a die roll inside a const method.

**GUI:** nothing new — Multiple-geometry target collection already exists and already permits clicking
allies (the Mass Healing Word path).

**Serialization:** `blessed` must be added to **both** `dict_to_stats` (helpers.py) and main.py's save
block, or it resets on save/reload.

**Test:** `test_bless.py` — three targets get the condition; an attack roll and a save each gain 1–4;
the buff dies with the caster's concentration; upcasting at level 2 allows a fourth target.

---

## Phase 2 — Haste

*Level 3 · Concentration · one willing creature · +2 AC, Advantage on DEX saves, doubled Speed, one
extra (limited) action; when it ends the target is Incapacitated with Speed 0 for one turn.*

**Data:** `type: Help`, `geometry: Single`, `requires_concentration: true`, `requires_los: true`,
`duration: 10`, `conditions: [{condition_name: "Hasted", requires_save: false}]`.

**Engine** — new Stats fields `hasted`, `haste_speed_bonus` (the walk speed added, so the restore is
exact), `haste_action_available`:
- Apply (`addAgentCondition`): `ac_temporary_modifications += 2`; `haste_speed_bonus = speed_walk`,
  `speed_walk += haste_speed_bonus`; `hasted = true`.
- DEX-save Advantage: via the Phase-0.3 `saveAdvantageFor` helper.
- Extra action: refresh `haste_action_available = hasted` in `beginTurn`. The GUI spends it.
- End (Phase-0.1 chokepoint): undo the AC and speed, then apply the lethargy —
  `addAgentCondition(Incapacitated, turns_remaining = 1)` + Speed 0. Suppress it if the target is dead
  (the Vistani kickback gate is the precedent). **This is the reason 0.1 must land first**: the
  lethargy has to fire on *every* end path — concentration drop, duration expiry, Dispel Magic — and
  it mutates the condition list while it does so.

**GUI:** a "⚡ Haste Action" button, cloned from the Wild Magic extra-action button (main.py:18966):
shown while `haste_action_available`, sets `self.action_used = False` and consumes the flag. Log the
RAW restriction (Attack ×1 / Dash / Disengage / Hide / Utilize) rather than hard-enforcing it — the
existing extra-action button sets that precedent.

**Metamagic:** Twinned Spell needs no work — Haste is Single-geometry, which is exactly what
`_twinned_single_armed` already handles.

**Test:** `test_haste.py` — AC +2, speed doubled, DEX save rolls at Advantage, the extra action is
granted once per turn, and dropping concentration leaves the target Incapacitated with Speed 0 for one
turn and then restores it cleanly.

---

## Phase 3 — Aid

*Level 2 · no concentration · up to 3 creatures · +5 current and maximum HP, +5 more per slot level
above 2 · 8 hours.*

**Data:** `type: Help` (**not** `Heal` — the HP maximum is the point, and a `Heal` spell would roll
`healing_type` dice instead), `geometry: Multiple`, `num_targets: 3`, `duration: 100` (effectively the
whole fight), `conditions: [{condition_name: "Aided", requires_save: false}]`.

**Engine** — new Stats field `aid_hp_bonus`:
- Apply: `bonus = 5 * (1 + max(0, cast_level - 2))` — reads the Phase-0.2 `cast_level`. Then
  `hp_max += bonus`, `aid_hp_bonus = bonus`, and route the current-HP gain through the healing
  chokepoint (`healAgent`) so a downed ally is revived and rejoins initiative, exactly as the short-rest
  heal does.
- End: `hp_max -= aid_hp_bonus`, `hp_cur = min(hp_cur, effectiveMaxHp())`, `aid_hp_bonus = 0`.
  Storing the granted amount (rather than recomputing 5×level at teardown) is what makes the restore
  exact when the spell is dispelled or the caster dies.

**Serialization:** `aid_hp_bonus` into `dict_to_stats` + main.py's save block. Note that `hp_max`
itself is already saved with the bonus folded in, so the teardown value has to ride along with it.

**Test:** `test_aid.py` — three targets gain 5/5, an upcast at level 4 grants 15, HP maximum returns to
its original value when the spell ends, and a target at 0 HP is brought back up.

---

## Phase 4 — Dispel Magic ✅ DONE + green 2026-07-14

*Level 3 · one creature/object/effect · ends any spell of level ≤ 3 on it; for level 4+, an ability
check with the spellcasting ability vs DC 10 + the spell's level. Upcast: auto-ends spells of level ≤
the slot used.*

Depends on Phase 0.2 (`cast_level`) and benefits from 0.1 (one teardown path to call).

**Data:** `type: Help`, `geometry: Single`, `attack_type: Automatic`, `range: 120`, plus a new
**data-driven flag** `dispels_magic: true` on `Spell` — following the `opens_doors` (Knock) precedent
rather than a name check, per the codebase's stated rule.

**Engine** — new `CombatEngine::dispelMagic(bm, caster_idx, target_idx, slot_level)`, dispatched from
`executeSpell` when `sp.dispels_magic`:
1. Collect everything magical attached to the target: `ActiveAgentCondition`s on `target_idx`,
   `ActiveSpellEffect`s anchored to it, and (stretch) an `ActiveTerrainEffect`/`ActiveLightEffect` at
   the aimed cell.
2. For each, `level = cast_level` (falling back to the caster's `spells[spell_idx].level`).
   `level <= slot_level` → ends automatically. Otherwise roll `d20 + spellcasting ability modifier` vs
   `DC 10 + level`; on success it ends. Log every check.
3. End each one through the Phase-0.1 chokepoint (so an Aid's HP maximum and a Haste's +2 AC come off
   correctly, and Haste's lethargy fires).
4. If nothing owned by `(caster, spell_idx)` remains anywhere on the map, clear that caster's
   `concentrating` flag — otherwise they are left concentrating on nothing.

**Test:** `test_dispel_magic.py` — a level-1 Bless is auto-dispelled; a level-5 effect requires the
check and can fail; upcasting Dispel to level 5 auto-ends it; dispelling Haste inflicts the lethargy.

---

## Phase 5 — Animate Dead

*Level 3 · Necromancy · **no concentration** · animates a Skeleton (bones) or Zombie (corpse); two
additional undead per slot level above 3.*

**Blocking bug (fix first):** `dropConcentration` (combat_spells.cpp:2960) dismisses **every** summon
belonging to the caster whenever concentration drops — with a single hard-coded exception for the
Trickery Cleric's `"Invoke Duplicity"`. Animate Dead is a 24-hour, non-concentration spell, so a
wizard's skeletons would evaporate the moment an *unrelated* concentration spell was broken.

**Fix:** add `bool summon_concentration` to `PlacedAgent` (set at spawn, alongside `summon_spell`) and
dismiss only summons whose *summoning* spell required concentration. The Invoke Duplicity special case
then deletes itself. Note the memory: construct `PlacedAgent` with **designated initializers**.

**Implementation:** almost entirely Python. Register Animate Dead in the summon dispatch (main.py:8914)
with a form choice — Skeleton or Zombie — reusing the context-menu pattern that `SUMMON_SPELL_TO_SPIRIT`
already uses, then place `1 + 2 * (slot_level - 3)` creatures. `_resolve_summon` currently places
exactly one creature per cast, so it needs a `pending_summon_count` and a placement loop.

Both stat blocks are already in the bestiary. Faction/summoner linking, sprite lookup, and NPC-spell
loading all come free from the existing path.

**Test:** `test_animate_dead.py` — a level-3 cast spawns one undead on the caster's team; a level-5 cast
spawns five; and (the regression that motivates the fix) breaking concentration on an unrelated spell
does **not** dismiss them.

---

## Phase 6 — Animate Objects

*Level 5 · Concentration · animates up to (spellcasting ability modifier) objects as Constructs under
your control.*

Rides on Phase 5's multi-placement summon path; the only real difference is that it *is* a
concentration spell, so the Phase-5 `summon_concentration` flag is set and the existing dismissal
cascade does the right thing.

- **Count:** the caster's spellcasting ability modifier, so the placement loop's count is computed at
  cast time rather than from the slot level. **Check the upcast rule against the SRD PDF** — the
  scraped `spells.json` claims `upcast_dice_bonus: 1`, which is meaningless for a spell that rolls no
  dice.
- **Stat blocks:** RAW uses one "Animated Object" block scaled by the object's size. The bestiary
  already has Animated Armor, Animated Flying Sword, Animated Broom, and Animated Rug of Smothering —
  offer those four as the form choice in v1. A size-scaled synthetic block (the `summon_spirits.json` /
  `compute_summon_loadout` pattern) is the RAW-faithful version if it turns out to matter.

---

## Phase 7 — Animal Shapes

*Level 8 · any number of willing creatures · each becomes a Large-or-smaller Beast of CR ≤ 4; temp HP
equal to the beast's HP; the target keeps its own HP and mental stats.*

The largest of the seven, and deliberately last. Consider scoping v1 to a single target.

- `activateWildShape` (combat_resources.cpp:3183) is close to what is needed, but it **spends the
  caster's "Wild Shape" resource** and returns false without it — so it cannot be pointed at a
  non-Druid ally as-is. Split it: a shared core (snapshot stats/weapons → overwrite from the beast
  block) plus two entry points, the Druid one that spends the resource and an Animal Shapes one that
  does not.
- **HP differs from Wild Shape**: Animal Shapes grants *temporary* HP equal to the beast's HP and the
  target keeps its own HP. Wild Shape swaps the HP pool. The shared core needs an HP-mode parameter.
- **Beast list**: `beast_forms.json` currently holds six beasts topping out at CR 1 — not enough for a
  CR ≤ 4 spell. Extend it with CR 2–4, Large-or-smaller beasts (Dire Wolf, Giant Boar, Giant Elk,
  Polar Bear, …). This is the cheap option and it upgrades high-level Wild Shape at the same time; the
  alternative (adapting the 91 CR-tagged bestiary beasts on the fly) is more code for the same result.
- Track each transformed target with an `ActiveAgentCondition` ("AnimalShape"); the Phase-0.1 teardown
  calls `deactivateWildShape` and drops any remaining temp HP.
- **Verify against the SRD PDF in-repo** whether the 2024 version is Concentration (the scraped
  `spells.json` says no; the 2014 spell says yes). The scraped data is not trustworthy on this.

---

## Ordering

Phase 0 first — 0.1 is a refactor, not a feature, so build it and run the existing suites green before
any spell work starts.

| Phase | Scope | Depends on |
| --- | --- | --- |
| 0.1 Teardown chokepoint | Refactor | — |
| 0.2 `cast_level` | Small | — |
| 0.3 Scoped save advantage | Small | — |
| 1. Bless | Small | 0.1 |
| 2. Haste | Medium | 0.1, 0.3 |
| 3. Aid | Small | 0.1, 0.2 |
| 4. Dispel Magic ✅ | Medium | 0.1, 0.2 |
| 5. Animate Dead | Medium (+ summon bugfix) | — |
| 6. Animate Objects | Small | 5 |
| 7. Animal Shapes | Large | 0.1 |

## Cross-cutting reminders

- **Stats round-trip:** every new `rpg.Stats` field (`blessed`, `hasted`, `haste_speed_bonus`,
  `haste_action_available`, `aid_hp_bonus`) must be added to `dict_to_stats` **and** main.py's save
  block, or it silently resets on save/reload.
- **Bestiary is hand-authored:** never re-run the CSV→JSON converter over `DND2024_MonsterStats.json`.
- **New tests** go in `run_all_tests.py`.
- The scraped `spells.json` text is a starting point, not ground truth — check levels, durations, and
  concentration against the SRD PDF in the repo root.


## Bugs Found

* ~~Hypnotic pattern is now a line? ~~
* ~~Hasted actions are somehow blocked if a bonus action is taken. ~~
