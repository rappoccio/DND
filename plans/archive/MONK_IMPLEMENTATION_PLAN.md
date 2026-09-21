# Monk Implementation Plan (2024 PHB)

Plan to finish the Monk class: remaining base-class progression features (L2–L20) and
the three stubbed subclasses (Mercy, Shadow, Elements). Open Hand is largely done.

Model tags: `[HAIKU]` = reuse-only, safe for the lower model; `[OPUS]` = novel engine
surface; `[DEFER]` = flavor / out-of-combat → record in `memory/known_limitations.md`.
Per the model-split rule, a lower model MUST stop at any `[OPUS]` task.

---

## Current state (already implemented)

**Base chassis:** Unarmored Defense (AC 10 + DEX + WIS, `combat_core.cpp:319`), Focus Points
(= level, short-rest regen, `combat.cpp:86`), Martial Arts die scaling, Extra Attack at L5,
Flurry of Blows, Patient Defense, Step of the Wind, Stunning Strike
(`applyStunningStrike`, eligibility flag set in `executeAction`).

**Warrior of the Open Hand:** Flurry riders — Knockdown / Push / Deny Reaction
(`applyOpenHandRider`, `combat_riders.cpp:1362`; GUI `_show_flurry_rider_menu` /
`_offer_open_hand_rider`).

**Subclass enum:** `MonkSubclass { None, WarriorOfTheOpenHandPath, WarriorOfMercyPath,
WarriorOfShadowPath, WarriorOfFourElementsPath }` (`character_class.hpp:276`), bound in
`rpg_bindings.cpp:971`, GUI picker + save/load wired (`main.py:1639`).

**Stubbed (enum only, no mechanics):** Mercy, Shadow, Elements.

### Infrastructure to reuse
- On-hit rider chain: Cunning / Brutal / Psionic Strike → deferred flag + `apply_*_effect`.
- Heal-back reactions: Protective Field, Uncanny Dodge (post-hit heal-back model).
- Heals: Lay on Hands / Second Wind (`combat_resources.cpp`).
- Teleport: Soulknife Psychic Teleportation.
- Invisibility: `applyOneWithShadows` (`combat_resources.cpp:95`).
- Forced movement: `forceMoveAgent`; Telekinetic Shove flow.
- Element-choice picker: `ElementPickerDialog` (`dialogs.py`), `damage_type_override`.
- AoE saves: `executeSpell` AoE path; Barbarian Rage resistance for damage-resistance grants.

---

## Phase 0 — Base-class progression (L2–L20) `[HAIKU batch, one OPUS item]`

Reuse of existing resource / heal / damage-type / resistance plumbing.

- **L2 Uncanny Metabolism** `[HAIKU]` — on initiative roll, restore all Focus Points + heal
  (1×/long rest). Reuse resource-restore + heal at turn/initiative start.
- **L3 Deflect Attacks** ✅ `[was OPUS]` — OnHit defender reaction reducing a B/P/S hit by
  `1d10 + DEX + level` (`canDeflectAttacks`/`applyDeflectAttacks`, `combat_attack.cpp`). Mirrors
  Parry/Uncanny Dodge: wired into `defenderOnHitOptions` + `maybeDefenderOnHitInline` (auto/RL) +
  `applyAttackReaction` (GUI in-flight window) + bound + GUI display name. Type-gate enforced in
  `apply` and at the offer site. **The "redirect as a ranged attack" clause is deferred** →
  known_limitations.md. Tests in `test_monk.py`.
- **L6 Empowered Strikes** `[HAIKU]` — unarmed strikes may deal Force instead of Bludgeoning.
  Trivial damage-type flag on the MonkUnarmed weapon.
- **L10 Heightened Focus** `[HAIKU]` — Patient Defense grants temp HP; Step of the Wind grants
  an ally movement; Flurry → 3 strikes (3-strike at L10 already in `test_monk.py`). Extend
  existing handlers.
- **L10 Self-Restoration** `[HAIKU]` — end one condition (Charmed/Frightened/Poisoned) at turn
  start; ignore one effect. Reuse turn-start condition clearing.
- **L13 Deflect Energy** ✅ `[HAIKU]` — Deflect Attacks applies to all damage types (the type-gate in
  `applyDeflectAttacks`/the offer site drops for `char_level >= 13`; label switches to "Deflect Energy").
- **L14 Disciplined Survivor** `[HAIKU]` — proficiency in all saves + spend 1 focus to reroll a
  failed save. Reuse OnSaveFail reroll path.
- **L15 Perfect Focus** `[HAIKU]` — regain focus on initiative if below a threshold.
- **L18 Superior Defense** `[HAIKU]` — spend 3 focus → resistance to all damage but Force.
  Reuse Barbarian Rage resistance grant.
- **L20 Body and Mind** `[HAIKU]` — +4 DEX, +4 WIS (cap 25) in `initializeClassResources`.

---

## Phase 1 — Warrior of Shadow ✅ COMPLETE (2026-06-21, built + 78 suites green)

Highest reuse; shipped a complete subclass. All four combat features done, engine-tested in
`test_monk.py` (12 new tests). GUI buttons + target-click wired (validated in live play).

- **L6 Shadow Step** ✅ — bonus-action teleport 30 ft from dim/dark + Advantage on next attack
  (`shadowStepTeleport`, `shadow_step_advantage`). Reuses `teleportAgent`.
- **L11 Improved Shadow Step** ✅ — teleport from any light level + +5 ft reach on the Advantage
  attack. **Fixed a latent bug: `bonus_reach_available` was read/consumed in combat_attack.cpp
  but NEVER set — `shadowStepTeleport` now sets it for L11+.**
- **L17 Cloak of Shadows** ✅ — BA → Invisible in dim/dark (`invisible_persists_on_action`, now
  bound to Python); expires at turn start in bright light (`cloakOfShadows`).
- **L3 Shadow Arts: Darkness** ✅ `[was OPUS]` — Magic action, 1 Focus → a 15-ft MagicalDark
  Sphere via `placeLightEffect`. **New infra:** `ActiveLightEffect.see_through_agent_idx` +
  `BattleMap::getLightLevelFor(cell, observer_idx)` (a MagicalDark effect tagged for an observer
  reads as transparent to them). `updateDarknessBlinding` now ALSO consults the light-effect layer
  (MagicalDark light Blinds creatures without Devil's Sight, not just the obscuration layer), with
  the caster see-through exempted. `shadowArtsDarkness` re-blinds agents standing in the Sphere.
- **L3 Shadow Arts: Darkvision** ✅ — Shadow Monks now gain 60 ft Darkvision (`darkvision_range`,
  derived in `initializeClassResources`, idempotent `std::max` so it survives save/load re-runs).
  **Minor Illusion** `[DEFER]` — flavor → known_limitations.

---

## Phase 2 — Warrior of Mercy ✅ COMPLETE (2026-06-22, built + 80 suites green)

All combat features done, engine-tested in `test_monk.py` (9 new tests). GUI buttons + on-hit
offer wired (validated in live play). Martial Arts die size now computed in C++
(`martialArtsDieSize`, combat_riders.cpp: d6/d8/d10/d12 by level).

- **L3 Hand of Healing** ✅ `[was HAIKU]` — `handOfHealing` (combat_riders.cpp): BA + 1 Focus → heal
  `MA die + WIS` (reuses `healAgent`). GUI button + target-click (`_resolve_hand_of_healing`),
  mirrors Lay on Hands.
- **L3 Hand of Harm** ✅ `[was OPUS]` — `applyHandOfHarmEffect`: deferred on-hit rider (mirrors
  `applyPsionicStrikeEffect`), `MA die + WIS` Necrotic. Eligibility flagged on an unarmed hit
  (`hand_of_harm_available`); GUI `_offer_hand_of_harm` in the on-hit rider dispatch.
- **L6 Physician's Touch** ✅ `[was HAIKU]` — Hand of Harm also Poisons (`applyPoisoned`); Hand of
  Healing also ends one of Blinded/Deafened/Paralyzed/Poisoned/Stunned.
- **L11 Flurry of Healing and Harm** ✅ `[was OPUS]` — Hand of Harm is free (no Focus) and once
  per target; `executeFlurryOfBlows` auto-folds a free Hand of Harm onto a Mercy hit. Hand of
  Healing accepts `free=true` (no Focus / Bonus Action) to fold into a strike (engine primitive;
  the per-strike heal-replacement GUI picker is deferred → known_limitations).
- **L17 Hand of Ultimate Mercy** `[DEFER]` — out-of-combat revive; flavor → known_limitations.

---

## Phase 3 — Warrior of the Elements ✅ COMPLETE (2026-06-22)

L3 + L6 combat features done, engine-tested in `test_monk.py` (10 new tests). GUI buttons + element
picker + target-click + on-hit push/pull menu wired (validated in live play per convention).

- **L3 Elemental Attunement** ✅ `[was OPUS]` — `activateElementalAttunement` (combat_resources.cpp):
  Magic action + 1 Focus → attune to a chosen Acid/Cold/Fire/Lightning/Thunder for the encounter
  (the sim doesn't track the 10-min duration; cleared on a short/long rest **and** at combat start).
  While active: unarmed strikes get +10 ft reach (non-consuming flag at combat_attack.cpp reach site),
  deal the chosen element, and can push **or** pull the target 10 ft on a hit (no save). **Design
  decisions:** (1) ONE generalized `Stats.unarmed_damage_override` field (-1 = none, else MagicDamage_t)
  replaced the old `monk_empowered_strikes_damage_type` — shared by Empowered Strikes (Force) and
  Attunement; (2) "forever until rest" instead of a timer. **New infra:** `forceMoveAgent` gained a
  `pull` mode (inverts the direction vector); `elementalAttunementMove` rider; `elemental_attunement_active`
  + `elemental_attunement_move_available` conditions. Reuses the on-hit rider dispatch + ElementPickerDialog.
- **L6 Elemental Burst** ✅ `[was OPUS]` — `elementalBurst` (combat_resources.cpp): Magic action + 2 Focus
  → a 20-ft-radius Sphere of the chosen element; each non-ally creature (faction-aware) makes a DEX save
  vs the Monk's Ki DC (8 + PB + WIS), taking `martialArtsDieCount × d8` (2/3/4 by tier), half on a save.
  Rogue Evasion honored. Reuses sphereCellsAround + effectiveMagicDamageMult + saveModFor.
- **L11 Stride of the Elements** ✅ — passive Fly Speed **and** Swim Speed each equal to walking
  speed (`speed_fly`/`speed_swim` derived in `initializeClassResources`, idempotent `std::max`,
  mirrors the Thief climb-speed pattern). Tests in `test_monk.py`.
- **L17 Epitome of Elements** `[DEFER]` — flavor → known_limitations.

---

## Phase 4 — Open Hand finish `[mixed]`

- **L6 Wholeness of Body** ✅ — BA self-heal (`MA die + WIS`), PB uses / long rest. `wholenessOfBody`
  (combat_riders.cpp) mirrors `handOfHealing`: reuses `healAgent` + `martialArtsDieSize`; "Wholeness
  of Body" Resource added in `initializeClassResources`; bound as `wholeness_of_body`; GUI button
  `btn_cbt_wholeness_of_body`. Tests in `test_monk.py`.
- **L11 Fleet Step** ✅ — a free Step of the Wind (no Focus Point, no Bonus Action, once per turn)
  that rides alongside another Bonus Action. Modeled in the GUI Step-of-the-Wind handler: kicks in
  when the normal cost can't be paid (bonus action spent or Focus empty), gated by the per-turn
  `fleet_step_used` Conditions flag (reset in `beginTurn`). Draw gate shows the button whenever the
  free use is still available.
- **L17 Quivering Palm** ✅ `[was OPUS]` — DONE (built + green 2026-06-25). Implemented as a
  **general delayed/stored-effect Condition** (not a bespoke rider): `ActiveAgentCondition` gained a
  `delayed_trigger` payload (dice / die size / flat bonus / damage type / save / half-on-save /
  drop-to-zero / auto-on-expire / label). `resolveDelayedEffect` + `triggerDelayedEffect`
  (combat_conditions.cpp) roll+save+apply; `plantQuiveringPalm` (combat_resources.cpp) spends 4 Focus
  for a 10d12 Force, CON-save-for-half effect (2024 RAW; `delay_drop_to_zero` is wired for the 2014
  variant), one creature at a time. Eligibility flag `quivering_palm_available` armed on an L17
  Open-Hand unarmed hit; GUI plants via the Stunning Strike / Open Hand menus (+ standalone fallback)
  and detonates with a `💥 Detonate Quivering Palm` action button. The same condition shape is
  Delayed-Blast-Fireball-ready (`delay_auto_on_expire` fires on duration end). Tests in test_monk.py.

---

## Recommended sequencing

1. **Phase 0 Haiku batch** (base-class passives, minus Deflect redirect) — fast; unblocks correct
   higher-level behavior.
2. **Phase 1 Shadow** — almost entirely reuse; complete subclass quickly (one Opus item: Darkness).
3. **Phase 2 Mercy + Phase 4 Open Hand** Opus items batched — both are on-hit / delayed riders, so
   do the engine work together.
4. **Phase 3 Elements** last — most new engine surface.

### Model-split summary
- **Haiku-safe whole tasks:** Phase 0 passives (except Deflect redirect), Shadow L6/L11/L17,
  Mercy L3 Hand of Healing + L6 Physician's Touch, Open Hand L6 Wholeness.
- **Opus-required:** Deflect Attacks redirect, Shadow Arts Darkness, Hand of Harm, Flurry of
  Healing and Harm, all Elements combat features, Quivering Palm ✅ (done — general delayed-effect
  Condition; see Phase 4).

## Testing
Extend `gui/test_monk.py` (engine-level, mirrors existing setup helpers). GUI-only wiring
(buttons, target-click) is validated in live play per project convention, not unit-tested.
Add `test_monk.py` to `run_all_tests.py` if not already listed.
