# Arcane Archer (Fighter subclass) — Plan

Drafted 2026-11-24. Source: 2024-style Arcane Archer text supplied by the user.

## Step 0 — decisions (FROZEN 2026-11-24)

- **D1 Ammunition.** No Ammunition property is modelled. Any *ranged weapon attack* qualifies
  for Arcane Shot / Curving Shot / Masterful Shots (thrown included). No weapon-data change.
- **D2 Known options.** A real known list on the character: 2/3/4/5/6 options at Fighter
  L3/7/10/15/18, picked in character setup; one swap allowed each time a new option is learned.
  Only known options are offered in combat.
- **D3 Banishment.** The Banishment spell has data in `spells.json` but no engine effect. Add it
  (AA0) on top of the **Untouchable** condition: banished = Untouchable + Incapacitated + Speed 0,
  then the creature returns to its space (or the nearest unoccupied space). Banishing Shot reuses
  the same helper with a "until end of its next turn" duration.
- **D4 Enfeebling Shot.** Postponed. Record in `memory/known_limitations.md` (needs a
  "Poisoned attacker subtracts a die from its damage" hook).
- **D5 Grasping Shot.** Restrained for 1 minute, or until the archer uses Grasping Shot again. An
  action by the target, or a creature within reach of it, makes a STR (Athletics) check against
  the Arcane Shot DC to end it; reuse the grapple-escape flow where it fits.
- **D6 Beguiling Shot.** Simplified: the target is always Charmed by the archer (no ally choice).
  The Charmed condition ends early if the archer attacks or damages the target, or forces it to
  make a saving throw.
- **D7 Magical Ammunition.** Deferred entirely → known_limitations.
- **D8 Ever-Ready Shot.** Regain 1 expended use at combat start, in both auto and real-dice
  initiative modes.
- **D9 Scope.** PC only. No NPC policy or AI support.
- **Skipped (flavor):** Arcane Archer Lore (cantrip + skills) and D&D Beyond import mapping
  → known_limitations.

## Rules constants

- Arcane Shot uses = max(1, INT mod), restored on Short/Long Rest. Once per turn.
- Die: d6, d8 @ L10, d10 @ L15, d12 @ L18.
- Save DC = 8 + INT mod + proficiency bonus.

## Steps

Per-step loop: implement → `./test.sh` in the container → fix → commit on request → handoff.

- **AA0 — Banishment spell.** Shared `banish(target, until)` helper: Untouchable +
  Incapacitated + Speed 0, returns the creature on expiry. Spell version: CHA save, lasts while
  concentration holds (≤ 1 min). If an Aberration/Celestial/Elemental/Fey/Fiend stays banished
  for the full minute, it does not return (reuse Divine Word's sent-home removal). Tests.
- **AA1 — Core setup.** `ArcaneArcherPath` added to the Fighter subclass enum. "Arcane Shot"
  resource, die size, DC, known-option list (D2), serialization, Python bindings, and an
  option picker in character setup (the minimum D2 needs). Tests.
- **AA2 — On-hit options.** Banishing (psychic 1 die, CHA save → AA0 helper until end of its next
  turn), Beguiling (psychic 2 dice, WIS save → Charmed by archer until start of archer's next
  turn, D6 break rules), Bursting (force 2 dice to target + each creature in 10-ft emanation),
  Grasping (slashing 1 die, STR save → Restrained, D5), Shadow (psychic 1 die, WIS save →
  Blinded until end of its next turn). Deferred "option available" flag after a ranged hit +
  Python prompt, mirroring `maneuver_available` / `offer_maneuver`. Condition immunities respected.
- **AA3 — No-attack-roll options.** Piercing Shot (30-ft × 1-ft line from the archer, ignores
  cover, DEX save; fail = weapon damage + 2 dice piercing, success = half) and Seeking Shot
  (a creature seen in the last minute and within long range, no LOS needed, ignores Half and
  Three-Quarters cover, DEX save; fail = weapon damage + 2 dice force, success = half the
  weapon damage). Chosen before the attack, as entries in the attack list; each spends the
  attack.
- **AA4 — Curving Shot (L7) and Ever-Ready Shot (L10).** Curving Shot: after a ranged miss,
  spend the Bonus Action to reroll against a different visible creature within range and
  within 60 ft of the original target (prompt like Precision Attack). Ever-Ready Shot: D8.
- **AA5 — Indomitable Teleport (L15) and Masterful Shots (L18).** Indomitable Teleport: after a
  successful Indomitable reroll, offer a teleport of up to 60 ft to an unoccupied visible space
  (reuse the existing teleport picker). Masterful Shots: a Reaction when a visible attacker's
  attack roll misses the archer. Move up to half Speed away from the attacker without provoking
  Opportunity Attacks, then make a ranged attack against it if it's in range. Goes through the
  reaction arbiter.
- **AA6 — known_limitations + CLASS_STATUSES.** Enfeebling Shot, Magical Ammunition, Lore,
  DDB import, NPC support. **Done 2026-11-24.**
- **AA7 — Live check** in `./run.sh` (user-driven).
