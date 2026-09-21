# Archfey Warlock Patron — Implementation Notes

Status: **BUILT (engine + bindings + GUI + tests) — needs the user's build + test run.**
Date: 2026-07-08. Closes the last of the four 2024 Warlock patrons (Fiend / Celestial / Great Old
One already done — see the `warlock_patrons` memory).

The always-prepared Archfey spell table (L3 Calm Emotions/Faerie Fire/Misty Step/Phantasmal Force/
Sleep, L5 Blink/Plant Growth, L7 Dominate Beast/Greater Invisibility, L9 Dominate Person/Seeming)
was already granted in Phase 1 via `_WARLOCK_SUBCLASS_SPELLS["Archfey"]` in `main.py`. This work
adds the four class features.

## Features

### L3 — Steps of the Fey  ✅
- Resource **"Steps of the Fey"** = `max(1, CHA mod)` uses / long rest, granted at `ArchfeyPath` L3
  in `combat.cpp` (Warlock block).
- Engine: `stepsOfTheFey(bm, idx, col, row, effect, as_reaction=false)` (`combat_resources.cpp`).
  Bonus-Action Misty Step (30 ft, no slot); spends one use. `effect` rider:
  - `0` None, `1` Refreshing (self 1d10 temp HP), `2` Taunting (creatures within 5 ft of the
    departed square make a WIS save vs the warlock's CHA DC or get the directed **FeyTaunt** mark).
  - `3` Disappearing and `4` Dreadful are **L6+** (see Misty Escape).
- **Taunting Step** is a directed `FeyTaunt` `ActiveAgentCondition` (caster = warlock, turns = 1),
  ticked away at the start of the warlock's next turn by `tickAgentConditionsForCaster`. The
  Disadvantage ("attacking anyone but the warlock") is enforced in `determineAdvantage`
  (`combat_attack.cpp`), mirroring the Clairvoyant Combatant mark.

### L6 — Misty Escape  ✅ (engine); GUI is an approximation
- Adds the **Disappearing** (self Invisible, ends on attack/cast) and **Dreadful** (2d10 Psychic to
  creatures within 5 ft of the departed square on a failed WIS save) riders (effects 3/4).
- **Reaction Misty Step:** `stepsOfTheFey(..., as_reaction=true)` spends the **reaction** instead of
  a Bonus Action (gated L6+).
- **GUI simplification:** RAW timing is "cast Misty Step as a Reaction *in response to taking
  damage*." Integrating that into the OnHit damage checkpoint is a larger lift, so the GUI exposes a
  **"Misty Escape (React)"** button on the warlock's own turn that spends the reaction. The engine
  entry point is timing-agnostic, so a future phase can hook it into the reaction window with no
  engine change. (Documented as a known simplification.)

### L10 — Beguiling Defenses  ✅ (fully live, no dedicated GUI needed)
- **Charmed immunity:** guarded at the top of `applyCharmed` (`combat_conditions.cpp`) for
  `ArchfeyPath` L10+, like Aura of Courage vs Frightened.
- **Reflect reaction:** `canBeguilingDefenses` / `applyBeguilingDefenses` (`combat_attack.cpp`), an
  OnHit defender reaction folded into `defenderOnHitOptions` + both apply paths
  (`maybeDefenderOnHitInline` auto/RL and `applyAttackReaction` GUI). Halves the incoming damage
  (like Uncanny Dodge) AND forces the attacker to make a WIS save vs the warlock's CHA DC; on a
  failure the attacker takes Psychic = the halved damage. Costs one **"Beguiling Defenses"** use
  (1 / long rest) OR — when spent — a Pact Magic slot to restore it. Surfaces automatically in the
  generic OnHit reaction menu, so it needs no dedicated button.

### L14 — Bewitching Magic  ✅
- Engine: `bewitchingMistyStep(bm, idx, col, row, effect)` (`combat_resources.cpp`) — a **free**
  Misty Step (no slot / no use / no action), gated `ArchfeyPath` L14+, applying the same rider.
- GUI: `_maybe_offer_bewitching_magic` in `_finish_cast` (`main.py`) offers a modal popup right
  after a slot-fueled Enchantment/Illusion cast; accepting arms a destination click that calls
  `bewitching_misty_step`.

## Shared plumbing
- `applyStepsOfFeyRider(bm, idx, from, effect)` (`combat_resources.cpp`) is the single rider
  implementation reused by Steps of the Fey, Misty Escape, and Bewitching Magic.
- Bindings (`rpg_bindings.cpp`): `steps_of_the_fey`, `bewitching_misty_step`.
- GUI (`main.py`): rider selector (`btn_cbt_fey_effect`, cycles `steps_of_fey_effect`, capped at 3
  options below L6), `btn_cbt_steps_of_fey` (Bonus), `btn_cbt_misty_escape` (React); pending flags
  `pending_steps_of_fey` / `pending_misty_escape` / `pending_bewitching_misty` + resolve methods.

## Design notes
- Used **resources** (serialize generically) not new bool flags → no 3-place round-trip needed.
- Refreshing Step applies temp HP to the warlock only (RAW allows an ally within 10 ft — v1
  common case). Dreadful/Taunting key off the **departed** square (RAW Dreadful allows "left or
  arrived, your choice"; v1 uses the departed square, matching Taunting).

## Tests
`gui/test_archfey.py` (12 engine-level tests, registered in `run_all_tests.py`): resource grants +
gating (L3/L10), teleport + use/bonus-action spend, range gate, Refreshing temp HP, Taunting
FeyTaunt mark, Disappearing (L6 gate) Invisible, Dreadful psychic, Misty Escape reaction-vs-bonus,
Charmed immunity (L9 charmable / L10 immune), Bewitching free teleport (L14 gate, no use spent).

## Not done / future
- Hook Misty Escape into the real OnHit "took damage" reaction window (currently own-turn button).
- Refreshing Step ally-target option; Dreadful arrival-square choice.
