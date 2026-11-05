# Grave Domain Cleric — plan

Source: *Ravenloft: The Horrors Within* (2024 chassis; text pasted by the user 2026-11-04).
Adds a fifth `ClericSubclass`, `GraveDomain`, alongside Life / Light / Trickery / War.

## Step 0 — before any code (frozen once signed off)

Changes to this set need a dated amendment with a reason, agreed by the user.
Steps 0.1–0.5 only read source and write this doc. They touch no source.

| # | Step | Status |
|---|------|--------|
| 0.1 | **Pull of Death hook.** Find the single point where a caster's spell damage and attack-hit damage both land on a target, for the once-per-turn extra die. Record whether "missing any HP" can be read *before* the triggering damage, which is what the text means. | [x] |
| 0.2 | **Sentinel crit cancel.** Check whether `AttackResult` keeps crit-only dice (doubled weapon dice, doubled smite / Divine Strike / Sneak Attack dice) apart from the base dice, so a crit can be turned back into a plain hit before the damage is halved. If it doesn't, write down the smallest change that would make it possible. | [x] |
| 0.3 | **Keeper of Souls hook.** Confirm that the Dark One's Blessing "reduced to 0" sites (`combat_attack.cpp` ~4210, `combat_spells.cpp` ~2102) cover every death path, including riders, auras and ongoing damage. List any gaps. | [x] |
| 0.4 | **Enhanced Necromancy.** Confirm that the Twinned Spell extra-target path can be reused, with Channel Divinity as the cost instead of Sorcery Points, for single-target spells only. | [x] |
| 0.5 | **Importer.** Find how `tools/import_character.py` maps D&D Beyond subclass names, and add "Grave Domain" there. | [x] |
| 0.6 | **User sign-off** on the decisions D1–D7 below. | [x] 2026-11-04 |

## Decisions (signed off 2026-11-04)

- **D1. Utility spells.** Detect Evil and Good, Gentle Repose and Dispel Evil and Good are added to the always-prepared list. They get no new mechanics.
- **D2. Pull of Death.** It applies automatically, since there's no reason ever to decline it. A target qualifies if its HP was below max *before* the triggering damage. For a multi-target spell it goes to the first qualifying target in resolution order, once per the cleric's turn. Strictly it is once per *any* turn, so it also works on reactions and opportunity attacks.
- **D3. Path to the Grave curse.** It is a condition that lasts until the start of the cleric's next turn, giving Disadvantage on attack rolls and saving throws. Ending it early for +cleric-level damage:
  - GUI: a prompt after the hit, in the same style as the Divine Strike rider.
  - Auto/RL: spend it on the first hit.
  - Damage type: Radiant or Necrotic, whichever the target doesn't resist. On a tie, Radiant (most undead resist Necrotic).
- **D4. Sentinel at Death's Door.** A reaction in the OnHit window that Uncanny Dodge uses, but the reactor is the cleric. The cleric can protect itself, or a Bloodied creature it can see within 60 ft. On a crit it first removes the crit-only damage (per 0.2), then halves the damage. Its uses are WIS mod (minimum 1) per Long Rest.
- **D5. Circle of Mortality, max dice.** It covers healing spells and the heal mode of Divine Spark, when the target is at exactly 0 HP. Spare the Dying can be cast as a Bonus Action.
- **D6. Keeper of Souls.** When an enemy dies within 60 ft of a cleric who isn't Incapacitated, the cleric or a creature it can see within 60 ft heals 2× cleric level.
  - Target: a GUI prompt; in auto mode, the lowest-HP% ally.
  - Use: once per Short/Long Rest. In the GUI it can be restored by spending a level 6+ slot; auto mode never spends one.
- **D7. Enhanced Necromancy.** For a single-target Necromancy spell of level 5 or lower, or any Grave domain spell, the cleric can spend 1 Channel Divinity for a second target within range. Material components aren't modelled (consistent with the rest of the engine).

## Phases (after sign-off; each one: new tests in `tests/test_grave_domain.py`, full suite green, commit only on request)

- **G1 — chassis.**
  - Enum value and bindings.
  - Subclass dropdown in `dialogs.py`, `_DOMAIN_SPELLS`, and the `classfeatures.json` entries.
  - Resources: Sentinel uses, the Keeper of Souls flag.
  - Importer mapping.
  - Spare the Dying as a Bonus Action; max-dice healing on 0-HP targets.
- **G2 — Pull of Death.**
- **G3 — Path to the Grave**: the curse condition, the Bonus Action button, the end-early rider.
- **G4 — Sentinel at Death's Door**: the reaction, the crit cancel, the GUI prompt.
- **G5 — Divine Reaper**: Keeper of Souls, Enhanced Necromancy.
- **Close-out**: tick Cleric → Grave Domain in `plans/CLASS_STATUSES.md`.

## Step 0 findings (2026-11-04)

- **0.1 Pull of Death.**
  - Weapon path: `applyAttackResult` already applies a string of on-hit riders after the base damage, each one adjusting the target's HP itself (Hunter's Mark, Divine Fury, …). Pull of Death becomes another automatic rider there. The target's HP before the hit is in `r.hp_before`.
  - Spell path: `executeSpell`'s per-target damage loop. The pre-damage HP is read before the subtraction.
  - The once-per-turn flag is a new `Agent::Conditions` field, reset in `beginTurn` like `zealot_divine_fury_used`. Spell attacks and save spells both go through the spell path.
- **0.2 Sentinel crit cancel.**
  - `AttackResult` does **not** keep the crit-only dice separately: `rollDamage` doubles `num_dice` inline.
  - Smallest change: when Sentinel cancels a crit, clear `r.critical`, set a new `r.crit_canceled`, and re-roll the base weapon damage as a normal hit (`rollDamage`). Then halve it.
  - The auto-crit block in `applyAttackResult` (melee vs Paralyzed/Unconscious, 2 death-save failures) is skipped when `crit_canceled` is set. So are the in-engine crit riders (Piercer, Crusher, Slasher, GWM Hew) and the GUI's later crit-doubled riders (Smite, Sneak Attack), because they all read `r.critical`.
  - Scope matches Uncanny Dodge: weapon attacks only. It halves the damage of the weapon hit itself; riders added after the reaction (Divine Fury, Hunter's Mark, Smite, …) are not halved. Spell attacks have only a Shield window today. Both limits go in `known_limitations.md`.
  - GUI: a new multi-reactor cursor on `InFlightAttack` (as for OnD20Seen), opened after the defender's own OnHit window, with window `OnHit` and the cleric as reactor. `_show_pending_reaction_menu` is generic; it only needs a display-name entry.
- **0.3 Keeper of Souls.**
  - Every NPC death goes through `applyUnconscious`'s NPC branch (`cond.dead = true`). That covers attacks, spells, Booming Blade, Power Word Kill, Divine Word, exhaustion and sunlight.
  - A hostile PC dying on death saves is not covered (rare; noted as a limitation).
  - Auto/RL (decider present): heal immediately. GUI: queue a pending flag that the GUI drains into a target prompt.
- **0.4 Enhanced Necromancy.** Twinned is a Metamagic option on `SpellAction`, and the `getNumTargetsForSpell(..., twinned)` cap is applied in `executeSpell`. Enhanced Necromancy gets its own `SpellAction` flag. It spends 1 Channel Divinity and reuses the `twinned` +1 target cap. If CD can't be paid, it is dropped silently, the same way a short-on-SP Twinned is.
- **0.5 Importer.** `tools/import_character.py:75` holds the per-class subclass list; add `GraveDomain` there.


## Status (2026-11-04)

G1–G5 implemented; tests in `tests/test_grave_domain.py` (engine) and `tests/test_grave_domain_gui.py`
(headless GUI). Limits are recorded under *Grave Domain* in `memory/known_limitations.md`.

Implementation notes beyond the decisions above (none changes D1–D7):
- D3: on a **spell** attack the end-early damage is taken automatically in the GUI too (the spell flow
  has no post-hit rider prompt). On a weapon hit the GUI prompt is offered *before* the normal rider
  chain, which resumes from its callback, so no other rider can shadow it.
- D4: any use of Sentinel sets `AttackResult::crit_canceled`, which also blocks a later melee auto-crit
  against a Paralyzed/Unconscious target. Only the cleric's allies are offered.
- D6: the GUI prompt is raised by a once-per-frame poll of `keeper_of_souls_pending`, and only when no
  other prompt or parked reaction is live.
- D7: Enhanced Necromancy is armed from the DM's right-click menu, like Overchannel.
