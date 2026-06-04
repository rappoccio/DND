---
name: known-limitations
description: Comprehensive known limitations and deferred features across all character classes
metadata: 
  type: project
---

# Known Limitations

## Architecture / Infrastructure

### combat.cpp Refactoring [OPUS]
**Status:** Code complexity/maintainability issue (not a functional bug)

**Problem:** `combat.cpp` has grown to ~7000 lines and is becoming unwieldy. It now contains:
- Core combat engine (movement, attack resolution, saving throws, damage)
- All spell execution logic
- All class feature implementations (Divine Fury, Sneak Attack, Cunning Strike, maneuvers, etc.)
- Weapon mastery system (9 types × multiple code paths)
- Condition application and effect resolution
- Resource spending and turn economy

**Why deferred:**
- Refactoring large files risks introducing subtle bugs in well-tested code
- Requires careful extraction of cohesive subsystems without breaking the interdependencies
- Not a blocker for new feature development (can still add to monolithic file)
- High risk, moderate benefit for current phase

**When ready:** Extract into subsystems like:
- `combat_attack.cpp` — attack rolls, hits, misses, critical handling
- `combat_spell.cpp` — spell execution pipeline
- `combat_class_features.cpp` — all per-class abilities
- `combat_weapon_mastery.cpp` — mastery riders and checks
- Keep `combat.cpp` as the orchestrator

---

### Post-hoc reaction interrupts ("react after seeing the roll/cast") [OPUS]
**Status:** Missing engine mechanism — several features are simplified to a *pre-roll* model.

**Problem:** The engine resolves a d20 Test (and a spell cast) **atomically** — it rolls, applies, and
returns in one call. There is no way to *pause mid-resolution*, hand control to another creature's
decider so it can see the rolled number (or the declared spell) and choose to spend a reaction that
modifies or cancels the outcome, then resume. The only reaction hooks today are *pre-roll* (the
actor primes a pending modifier before its own next roll, e.g. Portent, Bardic Inspiration `use`,
Cutting Words) or *post-event* on a fully-resolved result (e.g. opportunity attacks on movement).

**Features simplified or blocked by this:**
- **Lore Cutting Words** (implemented): RAW the Lore Bard reacts *after* seeing an enemy's attack
  roll / ability check / damage roll and subtracts the die. Currently primed *before* the target's
  roll (negative `pending_roll_bonus_`) — the decider/player must decide ahead of time. Same
  simplification as Bardic Inspiration `use_bardic_die` and Portent's pre-roll model.
- **Counterspell** (IMPLEMENTED 2026-06-03, ONDECLARECAST_PLAN.md step 2): the OnDeclareCast window
  *is* the "pending decision / interrupt" mechanism for the cast case — `beginCast` yields between
  "spell declared" and "spell resolved" so any creature that sees the caster within 60 ft may cast
  Counterspell; the caster makes a CON save vs the counterspeller's DC; on a fail the cast fizzles and
  keeps its slot (2024 rules). *Remaining gaps:* (a) **no recursive counter-counterspell** — a
  Counterspell can't itself be countered (no decision stack yet); (b) the 60 ft range gate is untested
  (the 12×12 test map tops out at ~55 ft); (c) the same yield-mid-resolution mechanism is still NOT
  wired for the d20-roll case below (Cutting Words / Countercharm remain pre-roll).
- **Bard Countercharm** (deferred): reaction to reroll an ally's just-failed charm/frighten save —
  needs the post-save interrupt at the (many, inline) save sites.
- **Use Inspiration Die** GUI: RAW the holder decides *after* a failed roll; the button primes it
  before instead.

**When ready:** Introduce a general "pending decision / interrupt" mechanism — the engine yields a
*decision point* object (roll value or declared-spell info + the set of creatures who may react),
collects reaction choices from the decider, applies modifiers/cancellation, then resumes. Cutting
Words, Counterspell, Countercharm, and the Use-Inspiration prompt all become consumers of it.

---

# Known Limitations

## Battle Master Fighter

### Riposte (DEFER)
**Rule**: Reaction melee attack when a creature misses *you* with a melee attack.
**Why deferred**: All existing on-hit riders flag the *attacker*. Riposte requires flagging the
*defender* when the attacker misses them, then prompting the defender's player for a reaction.
No existing engine pattern covers this trigger direction. Will reuse `reaction_used` once the
"counter-reaction-on-miss" pattern is established (similar to Opportunity Attack, but triggered
by a miss rather than movement).

### Additional Maneuvers (beyond starter set)
The following maneuvers are not yet implemented but will reuse `applyManeuverEffect`'s dispatch
once the engine pattern is proven green:
- Disarming Strike (STR/DEX save or drop weapon)
- Feinting Attack (bonus action → advantage on next attack vs target)
- Lunging Attack (extend reach by 5 ft for one attack)
- Commander's Strike (bonus action + ally reaction → ally makes an attack)
- Evasive Footwork (add superiority die to AC until end of move)
- Goading Attack (WIS save or Disadvantage on attacks not targeting you)
- Rally (bonus action: give temp HP to an ally)

### Battle Master save DC simplification
Current implementation uses STR mod for the maneuver save DC. The 2024 rules allow
STR *or* DEX (player's choice). This will be a minor enhancement once tested — just take
`max(_mod(str), _mod(dex))` in `applyManeuverEffect`.

---

## Fighter — Deferred Features

### Indomitable (L9) [DEFER]
**Rule**: Reroll a failed saving throw (uses regain on long rest).
Will mirror Zealot Fanatical Focus / Diviner Portent pattern when implemented.

### Studied Attacks (L13) [DEFER]
**Rule**: Advantage on next attack roll against a creature you missed with a weapon attack.
Will reuse the existing `vex_target_idx` flag — trivial but out of scope for this pass.

---

## Paladin

### Implemented ✅
- **Chassis**: CHA half-caster, Extra Attack (L5), WIS save proficiency
- **Channel Oath** resource (2/3/4 uses by level), **Lay on Hands** pool (5×level, `layOnHands`)
- **Oath of Devotion — Sacred Weapon**: Bonus Action, spend 1 Channel Oath → +CHA mod (min +1)
  to weapon attack rolls for 1 minute (10 rounds). Engine `activateSacredWeapon` (`combat.cpp`),
  applied in `rollToHit`, duration decremented in `beginTurn`. GUI button + `test_paladin.py` coverage.

### Divine Smite [OPUS]
**Rule**: Spell cast as a Bonus Action triggered by a melee weapon hit, consuming the Attack-action
hit + bonus action + a spell slot, with radiant damage scaling by slot level.
The triple-economy coupling (hit + bonus action + spell slot) is the hard piece.
On-hit hook point exists; the economy wiring is deferred to [OPUS].

### Auras (Aura of Protection, etc.) [DEFER]
Requires a party/team aura system the engine currently lacks. Deferred until the team system
is established.

---

## Eldritch Knight Fighter — IMPLEMENTED ✅ (2026-06-02, awaiting build)
The attack↔cast interleave is done. See the Fighter section below for the full breakdown.
Remaining simplifications:
- **Eldritch Strike (L10)** is **one-shot** (consumed by the target's next save vs a spell the EK
  casts), not the RAW "until the end of your next turn" window — same family of timing
  simplifications as Cutting Words. The tag has no timed expiry; it clears on consume or at the
  EK's next turn (`_advance_turn` reset). Acceptable for combat-sim.
- **War Bond (L3)** — weapon-bonding / anti-disarm utility — NOT modeled (out-of-combat flavor).
- RL/headless: War Magic substitution isn't in the action space yet (`availableAttacks`); the
  engine gate (`war_magic_used`) is reset in `runRound` for consistency, full RL support deferred
  with the rest of RL spellcasting.

---

## Monk & Druid

### Weapon Loading from GUI
**Monk unarmed strikes** and **Druid Wild Shape attacks** are currently loaded by the Python GUI
layer (main.py) rather than the C++ engine. This means:
- These features cannot be used in headless/RL training mode without the GUI
- Weapons are created dynamically from Python, not from a pure C++ data-driven system
- To move to headless support, weapon definitions should be loaded directly in C++ (e.g., from
  a weapon database JSON) and passed to `setAgentWeapons` in `initializeClassResources` or
  the activation function, rather than being constructed in main.py

---

## Barbarian Reckless Attack Mechanic — RESOLVED 2026-06-03 (built + green)
- Now a **choice** with two entry points (RECKLESS_ATTACK_PLAN.md): (1) pre-declare before attacking
  (existing GUI button — still gated on `raging`), and (2) **post-hoc on a miss** — the engine flags
  `reckless_reroll_available`; the GUI prompts (`_offer_reckless_reroll`) and calls
  `apply_reckless_reroll`, the auto/RL driver consults `CombatDecider::choose_reckless` inline. Both
  set turn-scoped `reckless_attack` (downside: enemies have advantage vs you until your next turn,
  cleared at turn start). Replaces the old silent auto-reroll. Tests: `test_reckless.py`.
- **Remaining minor gaps:** (a) the inline auto/RL reroll doesn't grant Brutal Strike on the rerolled
  hit (eligibility computed before reckless is set); the GUI apply path does. (b) post-hoc activation
  isn't logged for replay (pre-declare logs `log_event("reckless")`). (c) the post-hoc path ignores
  `raging` while the pre-declare GUI prompt requires it — minor inconsistency.

## Spell mechanics
- _(resolved 2026-06-02)_ **Wall of Fire** and other Rectangle "wall" spells are now placed with a two-click flow (anchor → endpoint), any orientation, free angle, length clamped to the spell's max. Geometry computed by `BattleMap::wallCells` (single source of truth); `SpellAction.aoe_col2/aoe_row2` carry the endpoint. NPC/RL casts without an endpoint fall back to the legacy centered box.

---

## Agent Initialization Pattern Limitation
**Status:** Design limitation, affects all agent setup

**Description:**
Stats set on an AgentConfig before adding to battle are NOT preserved. Stats must be retrieved and modified AFTER `add_agent_to_battle()` is called.

**Current pattern (REQUIRED):**
```python
config = create_test_agent("Name", x, y)
idx = add_agent_to_battle(engine, bm, config)

# THEN modify stats
stats = engine.get_agent_stats(bm, idx)
stats.character_class = rpg.CharacterClass.Barbarian
stats.char_level = 6
stats.barbarian_subclass = rpg.BarbianSubclass.Berserker
engine.set_agent_stats(bm, idx, stats)
```

**Why this happens:**
- `add_agent_to_battle()` creates a fresh Stats object from hardcoded defaults (ability scores, HP)
- Config stats are not copied into the agent when added to battle
- Test helper function overwrites all stats

**Impact:**
- Cannot pre-configure agents in config before battle
- All stat modifications must happen post-battle-add
- Affects all test patterns and config setup workflows

**Future improvement:**
- Modify `add_agent_to_battle()` or battle agent creation to preserve config stats
- OR provide a post-add stats migration function

---

## Wild Heart L6: Panther Aspect (Climb Speed)
**Status:** Flavor feature, deferred

**What's needed:**
- Panther Aspect should grant climb speed = walk speed while Raging
- Currently, `speed_climb` field exists in Stats but is not integrated into movement system
- Movement system (walk/fly/swim in Agent class) would need enhancement to support climb speeds

**Why deferred:**
- Climb movement is not heavily used in typical D&D combat
- Requires changes to Agent's movement methods beyond scope of initial work
- User indicated this is "flavor for now"

---

## World Tree L6: Branches of the Tree
**Status:** Complex reaction system required, deferred

**Description:** 
Reaction ability that triggers when a creature starts its turn within 30ft of the Barbarian while Raging.
- Creature makes STR save (DC 8 + STR mod + Prof bonus)
- On failure: teleports within 5ft of Barbarian (Barbarian can reduce creature's speed to 0)
- On success: no effect

**What's needed:**
- Reaction trigger detection on turn start within 30ft range
- STR save resolution with proper DC calculation
- Teleport logic (similar to Branches' teleport mechanic)
- Speed reduction option (can choose to reduce speed to 0)
- Interaction with reaction economy (uses Barbarian's reaction)

---

## Wizard Features (Various)

### Illusionist L14: Illusory Reality [DEFER]
Requires object system; deferred indefinitely. Would need persistent object/terrain creation system.

### L3: Subclass Savant Features [DEFER]
Requires spellbook system separate from prepared spells.

### L3: Arcane Ward (Abjurer) [DEFER]
Requires parallel ward HP system separate from temp HP.

### L3: Portent (Diviner) [DEFER]
Requires d20 roll hook system to intercept/override rolls.

### L6: Sculpt Spells (Evoker) [DEFER]
Requires team/faction system to distinguish allies vs enemies in AoE.

### L6: Phantasmal Creatures (Illusionist) [DEFER]
Requires creature summoning system.

---

## Cleric

### Not modeled — Divine Order (L1) 🚫
- **Protector** (Martial weapon + Heavy armor training) grants nothing the engine models
- **Thaumaturge** (extra cantrip + skill checks) is out-of-combat flavor

### Deferred — Trickery Domain
- **Invoke Duplicity** and related features need illusory-entity concept

### Turn Undead — minor fidelity gaps
- Undead with **Frightened immunity** aren't spared (no creature condition-immunity system)
- "Ends early if caster is Incapacitated or dies" isn't cascaded

### Deferred — Light Domain (beyond Radiance of the Dawn)
- **Warding Flare**: needs pre-roll reaction hook in `executeAction`
- **Corona of Light**: needs aura/aura-save-modifier concept
- **Radiance of the Dawn** ally-exclusion: needs red/blue team system

### Deferred — War Domain spells
- **Crusader's Mantle**: needs ally-buff aura for +1d4 Radiant
- **Steel Wind Strike**: needs multi-target teleport/attack
- **War God's Blessing**: underlying spells (Shield of Faith, Spiritual Weapon) are hollow

### Deferred — Weapon Mastery: Nick (action economy)
- **Nick** off-hand benefit not modeled in turn economy. Requires three pieces: (1) off-hand doesn't consume bonus action, (2) tied to Attack action with Light weapon, (3) once-per-turn gate. Current TWF routes through Bonus button; Nick needs dedicated path.

---

## Warlock (Phased epic, Phase 1 foundation implemented)

### Implemented (Phase 1) ✅
- Chassis: CHA spellcasting, WIS+CHA save proficiencies
- `WarlockSubclass` enum (Archfey/Celestial/Fiend/GreatOldOne)
- Pact Magic slots (short-rest recharge), Magical Cunning

### Implemented (Phase 3a) ✅
- Eldritch Blast multi-beam (scales 1/2/3/4 beams)
- Agonizing Blast (+CHA/beam), Repelling Blast (10 ft push/beam)
- Eldritch Mind (advantage on CON saves)

### Deferred (Phase 2) — Patron subclasses
- Fiend: Dark One's Blessing, Fiendish Resilience (partially implemented)
- Celestial: Healing Light, Radiant Soul (partially implemented)
- Great Old One: Thought Shield (partially implemented)
- Archfey: Steps of the Fey, Misty Escape (need teleport primitive)

### Deferred (Phase 3b) — Remaining Eldritch Invocations
- Pact of the Blade line (needs weapon primitive)
- Devil's Sight, Eldritch Spear range (needs range-enforcement system)

### Not modeled (combat simulator only) 🚫
- Telepathy, familiars, Pact of the Tome, utility features

---

## Rogue (Phased epic, Phase 1 + Phase 2 implemented)

### Implemented (Phase 1) ✅
- `RogueSubclass` enum (ArcaneTrickster/Assassin/Soulknife/Thief)
- Chassis: DEX+INT saves, Cunning Action
- **Sneak Attack**: once/turn, gated on advantage + hit with finesse/ranged
- Steady Aim, Uncanny Dodge, Evasion, Elusive

### Implemented (Phase 2) ✅
- **Cunning Strike** (L5: Poison/Trip/Withdraw) with die-cost validation
- **Improved Cunning Strike** (L11: two effects)
- **Devious Strikes** (L14: Knock Out/Obscure)

### Deferred — Phase 2 continued
- **Daze** (Devious Strikes L14): needs per-turn action-economy tracking

### Deferred — Phase 3 (subclasses)
- Assassin, Arcane Trickster, Soulknife, Thief subclass mechanics

### Deferred — need NEW hooks
- *Stroke of Luck* (L20): turn failed d20 into 20 → needs roll-replace hook
- *Spell Thief*, *Thief's Reflexes*: need reaction-on-cast and initiative hooks

### Not modeled (combat simulator only) 🚫
- Expertise, Reliable Talent, Thieves' Cant, weapon proficiencies, skill features

---

## Weapon Mastery (Implemented: 9 of 9 types)

All eight 2024 weapon masteries plus Poison (custom) are implemented with **once-per-turn limits**:
- **Sap** — disadvantage on target's next attack (once/turn)
- **Slow** — speed -10 ft (once/turn)
- **Vex** — attacker advantage vs target (once/turn)
- **Push** — 10 ft push of Large-or-smaller (once/turn, GUI prompt)
- **Poison** — target Poisoned condition (once/turn, automatic)
- **Topple** — CON save or Prone (once/turn, GUI prompt)
- **Cleave** — extra attack vs 2nd creature within 5 ft (once/turn, GUI prompt)
- **Graze** — on miss, deal ability mod damage (passive, per-miss)
- **Nick** — action-economy benefit (NOT modeled in turn economy; needs refactor)

---

## Druid (Phase 1 implemented)

### Implemented (Phase 1) ✅
- **Chassis**: WIS full caster, INT+WIS saves
- **Wild Shape** resource (L2+): 2/3/4 uses, short-rest regen 1, long-rest full
- **DruidCircle** enum, GUI subclass picker, save/load
- **Weapon Mastery** for beast form attacks (Topple on Brown Bear, Poison on Giant Spider, etc.)
- **Beast form stat swapping**: AC/STR/DEX/CON swap on activation, restoration on deactivation
- **Weapon restoration**: original weapons saved and restored on Wild Shape exit

### Deferred — Wild Shape mechanics
- **Circle of the Moon L2**: bonus-action shift to beast form (turn-economy)
- **Circle of the Moon L6+**: increased durability, better damage
- **Circle of Wildfire**: Wildfire Spirit summon (needs summoning system)
- **Circle of Spores**: Symbiotic Entity (passive aura feature)
- **Circle of Land**: Land Circle Spells, Preserve Life (circle-specific deferred)

---

## Monk (Phase 1 implemented)

### Implemented (Phase 1) ✅
- **Chassis**: DEX+WIS saves, Ki/Focus Points resource (= level, short-rest regen)
- **Extra Attack** at L5
- **MonkSubclass** enum, GUI picker, save/load
- **Way of the Open Hand**: Flurry of Blows (2 bonus unarmed strikes via `_start_extra_attack`)
- **Unarmed Martial Arts**: strike die scales by level (configurable per subclass) with bonus-action extra attack
- **Unarmored Defense**: AC = 10 + DEX + WIS when not armored — implemented in the AC calc (`combat.cpp:313-330`), mirrors the Barbarian formula
- **Patient Defense** (spend 1 Focus → Dodge) and **Step of the Wind** (spend 1 Focus → Disengage+Dash) — GUI buttons + click handlers in `main.py`
- **Stunning Strike** (spend 1 Focus on a qualifying unarmed hit → CON save or Stunned) — on-hit rider: eligibility flag set in `executeAction` (`combat.cpp:1963`), applied out-of-band via `applyStunningStrike` (`combat.cpp:4595`)

### Deferred — Monk features
- **Subclass mechanics**: Shadow Arts, Four Elements

### Deferred — Warrior of Mercy [OPUS]
- **Hand of Healing** (L3): classfeature.json entry created with Focus Points cost, but bonus-action casting needs wiring
- **Hand of Harm** (L3): deferred on-hit rider pattern with necrotic damage + Poisoned save. Requires chained-rider logic to work alongside Stunning Strike (two riders on same unarmed hit).
- **Physician's Touch** (L6): Hand of Harm adds Stunned on failed save (L6 enhancement)
- **Deferred because**: Hand of Harm's chained-rider logic (one rider triggering another) is not yet established in the engine. Establishing the pattern in Battle Master maneuvers is lower risk.

---

## Fighter (Phase 1 implemented)

### Implemented (Phase 1) ✅
- **Chassis**: Extra Attack (2 at L5, 3 at L11, 4 at L20), Weapon Mastery activation
- **Crit threshold**: `Stats.crit_threshold` (default 20), Champion lowers to 19/18
- **Second Wind** (L1+): 1d10 + level, short/long-rest regen, bonus-action GUI button
- **Action Surge** (L1+): reset `action_used` flag, 1 use (2 at L17), long-rest regen
- **Champion subclass** (L3+): crit threshold reduction
- **FighterSubclass** enum + GUI picker + save/load
- **Battle Master**: Superiority Dice resource (`combat.cpp:6742`) + Maneuvers via `applyManeuverEffect` (`combat.cpp:5202`) — Trip→Prone, Menacing→Frightened, Pushing→forced move, Precision Attack (on-miss). Tested in `test_fighter.py`.
- **Psi Warrior** (L3+): Psionic Energy Dice resource (= 2 × prof, die d6/d8/d10/d12 by level) + Telekinetic Movement use.
  - **Psionic Strike** (on-hit rider): spend 1 die → Force damage (die + INT mod), once/turn. `applyPsionicStrikeEffect` + GUI rider chain (`_offer_psionic_strike`).
  - **Protective Field** (reaction): spend 1 die → prevent (die + INT mod) damage. `applyProtectiveField` (modeled as post-hit heal-back). Engine + binding + test done.
  - **Telekinetic Movement**: push a creature 30 ft, once/rest. `applyTelekineticMovement` + GUI button (target-click).
  - All tested in `test_fighter.py`.

### Deferred — Psi Warrior (GUI only)
- **Protective Field reaction prompt**: the mechanic is complete and callable via `apply_protective_field`,
  but the GUI does not yet *offer* it to a Psi Warrior when they are hit (no "defender reaction on being
  hit" prompt pattern exists yet — Uncanny Dodge auto-applies; this needs a player choice because it costs
  a die). Wire alongside a general defender-reaction prompt later.

### Deferred — Battle Master (remaining)
- **Riposte** (reaction-on-miss, flags the defender — no engine pattern yet)
- **Additional maneuvers** beyond the starter set (Disarming, Feinting, Lunging, etc. — dispatch via `applyManeuverEffect` once needed)

### Deferred — Champion extras
- **Remarkable Athlete** (bonus to non-proficient checks)
- **Second Fighting Style** (L3)

### Eldritch Knight — IMPLEMENTED ✅ (2026-06-02, awaiting build)
- **Spellcasting chassis (L3+)**: third-caster, INT, Wizard list. `compute_third_caster_slots`
  (`character_class.hpp`) + override in the Fighter chassis (`combat.cpp` case Fighter) since
  `compute_class_slots(Fighter)` can't see the subclass. Sets `spell_slots_max`,
  `spellcasting_ability=INT`, `can_cast_spell`.
- **War Magic (L7+)** — the attack↔cast interleave. Engine owns the gate
  (`canUseWarMagic`/`markWarMagicUsed` + `Conditions::war_magic_used`, reset in both turn paths);
  the cast itself goes through the normal `executeSpell`. GUI: a `slot=="war_magic"` pseudo-slot
  (mirrors `"bonus"`) — the resolve path (`_consume_cast_slot`) decrements ONE attack instead of
  consuming the whole action, marks the gate, and re-prompts for the remaining attack(s). Gated
  **once per Attack action** (reset when a fresh action-attack sequence seeds → Action Surge
  permits another).
- **Improved War Magic (L18+)**: the War Magic spell filter widens to level 1-5 action spells
  (`_eligible_war_magic_spells` + the `_start_cast_spell` filter), respecting the
  one-leveled-spell-per-turn rule via `available_castable_spells`.
- **Eldritch Strike (L10)**: on-hit rider tags the target (`Conditions::eldritch_strike_by`);
  the spell-save site applies disadvantage and consumes the tag. One-shot (see simplification note
  in the EK Architecture section above).
- **Arcane Charge (L15)**: optional 30-ft teleport offered after Action Surge
  (`_resolve_arcane_charge`, reuses `teleport_agent`).
- Tests: `test_fighter.py` (chassis L3/L7/scaling, non-EK has no slots, War Magic gate + L7
  requirement, Eldritch Strike tagging + L10 requirement).

### NOT IMPLEMENTED (Model boundary)
- **[DEFER] Indomitable** (L9): save-reroll resource
- **[DEFER] Studied Attacks** (L13): advantage on next attack vs missed creature

---

## Sorcerer (Phase 1 + Phase 2 + Phase-3 combat-core implemented)

**Implemented:** Chassis (CON/CHA save proficiency), full-caster table-B slots, Sorcery
Points, Innate Sorcery (L1: +1 spell save DC + advantage on spell attacks, 10-round buff,
2 uses), Font of Magic (slot↔SP conversion both directions), and Metamagic foundation
(`SorcererSubclass`/`MetamagicOption` enums, `SpellAction.metamagic`, `metamagic_sp_cost`).

### Metamagic — implemented options
Each applies for one cast by temporarily mutating a copy of the spell (the agent's stored
spell is untouched), and SP is spent only when the option is actually applicable:
- **Heightened Spell** (2 SP): one target rolls its save with disadvantage.
- **Seeking Spell** (1 SP): reroll a missed spell attack once.
- **Careful Spell** (1 SP): chosen allies (`SpellAction.careful_targets`, up to CHA mod) are
  excluded from the spell's area — reuses the Evoker safe-target exclusion. Save spells only.
- **Distant Spell** (1 SP): doubles the spell's range (touch → 30 ft).
- **Extended Spell** (1 SP): doubles a lasting spell's duration. (Advantage on concentration
  saves is **not** modeled.) Inapplicable to instantaneous spells (duration < 2).
- **Quickened Spell** (2 SP): an Action-cast spell becomes a Bonus Action; the engine reports
  `SpellResult.cast_as_bonus_action` so the GUI/turn-economy layer can charge the bonus action.
- **Transmuted Spell** (1 SP): retypes the spell's elemental damage to
  `SpellAction.transmuted_damage_type`. 2024 elemental set only (Acid/Cold/Fire/Lightning/
  Poison/Thunder); inapplicable if the spell deals none of those.
- **Twinned Spell** (1 SP): increments `targets_per_upcast_level` by 1 for the cast (adds a
  target on upcast Multiple-geometry spells); single-target plumbing handled GUI-side.

### Metamagic — deferred / flavor
- **[DEFER] Empowered** (1 SP): reroll up to CHA-mod damage dice — needs the per-type damage
  loop restructured to capture dice before multipliers are applied. Logged, no SP spent.
- **[KNOWN LIMITATION] Subtle** (1 SP): cast without V/S components — purely out-of-combat
  flavor (no combat-sim effect); will not be implemented.

### Subclasses (Phase 3 — combat-core slice implemented)
**Implemented:**
- **Draconic L3** — Draconic Resilience: unarmored AC = 10 + DEX + CHA, in `computeAC`
  (`combat_core.cpp`). GUI/save-load wired (`agent_sorcerer_subclass`).
- **Wild Magic L6** — Bend Luck: `sorcerer_bend_luck(bm, idx, boost)` spends 1 Sorcery Point to
  roll 1d4 and add (boost=True) / subtract (boost=False) it from the next D20 Test via
  `pending_roll_bonus_`. (Pre-roll prime — RAW is post-hoc; see Architecture → Post-hoc reaction
  interrupts.)

**Deferred:**
- **Draconic**: Draconic Resilience HP bonus (+1 HP/level — needs an idempotent application so
  re-init/load doesn't double-count); L6 Elemental Affinity (add CHA to your element's damage —
  needs a stored element/damage-type + a damage rider); L14 Dragon Wings; L18 Dragon Companion.
- **Wild Magic Surge** — the **roll + classification + narration foundation is IMPLEMENTED**:
  `roll_wild_magic_surge(bm, idx)` rolls d100 on the curated 10-band table and returns
  `WildMagicSurgeResult{d100_roll, effect (1-10), description}`; `wild_magic_surge_description(effect)`
  exposes the table text. **Per-effect APPLICATION is the follow-up** (the engine only classifies):
  - **Application dispatch:** `applyWildMagicSurgeEffect(bm, idx, effect)` / `apply_wild_magic_surge_effect`
    applies the engine-handled bands and returns true; unhandled bands return false (caller applies).
  - **APPLICATION IMPLEMENTED + tested (bands 1,2,3,7,8):**
    - Band 1 (Plant Growth): `placeTerrainEffect` — Quartered difficult terrain sphere (10-ft, 10 rounds)
      on the caster.
    - Band 2 (spectral shield): +2 AC (via `ac_temporary_modifications`) + Magic Missile immunity for
      10 rounds; ticks down in `beginTurn` (removes the +2 on expiry). MM immunity = a name-matched skip
      at the top of the executeSpell per-target loop.
    - Band 3 (vitality): +5 HP at the start of each of your turns for 10 rounds, healed in `beginTurn`.
    - Band 7 (skip turn): one-shot flag → `beginTurn` reports `turn_skipped` and clears it.
    - Band 8 (extra action): sets `wild_magic_extra_action` flag (GUI turn economy enforces the action).
    - Bands 6 / 10 (1-min windows): `wild_magic_bonus_cast_turns` (action-cast spells as a Bonus Action)
      and `wild_magic_teleport_bonus_turns` (teleport 20 ft as a Bonus Action) — duration ticked in
      `beginTurn`; the GUI enforces the actual benefit (like band 8).
    - Band 9 (drop weapons): `applyWildMagicSurgeEffect` drops all equipped weapons to the caster's cell
      as ground items via `bm.placeItem` + `bm.setAgentWeapons` ("random square" simplified to the
      caster's cell).
    State on `Agent::Stats` (`wild_magic_shield_turns` / `_regen_turns` / `_skip_next_turn` /
    `_extra_action` / `_bonus_cast_turns` / `_teleport_bonus_turns`).
  - **Bands 4 & 5 = "the surge casts a named JSON spell"** (user 2026-06-02) — handled through the
    normal `execute_spell` cast path with target selection, NOT special engine logic:
    - Band 4 = **Chain Lightning** (exists in spells.json; Multiple-geometry lightning at ≤3 targets).
    - Band 5 = **Blindness/Deafness** (exists in spells.json; Multiple, CON save, applies Blinded). The
      custom moving "blind aura" was abandoned — it needed per-turn zone condition application, which would
      have regressed the 4 persistent condition-spells (Black Tentacles / Fear / Hypnotic Pattern / Sleep)
      that apply their condition once; "just cast Blindness" reuses everything and avoids that.
    These two are wired with the surge TRIGGER (the trigger flow casts the named spell). No magic numbers
    in C++; the engine has a JSON reader (`spellFromJson`) so the spell data stays in JSON. See [[engine-reads-json]].
  - **No big-infra bands remain.**
  - GUI/trigger follow-ups: the surge TRIGGER (roll after a level-1+ cast, then apply the band — including
    casting Chain Lightning / Blindness for bands 4/5) and GUI enforcement of the flag/window bands (6, 8, 10).
  - Trigger wiring (when to surge — after casting a level 1+ spell) is also a follow-up.
- **Wild Magic** other: Tides of Chaos (advantage grant — needs a pending-advantage mechanism),
  L14 Controlled Chaos, L18 Spell Bombardment.
- **Clockwork** (entire): Restore Balance (reaction to cancel adv/disadv → post-hoc interrupt,
  see Architecture note), Bastion of Law ward dice.
- **Aberrant** (entire): Psionic Spells + Psionic Sorcery (cast a fixed psionic list using Sorcery
  Points instead of slots — needs subclass spell-list infra), Telepathy/Psychic Defenses (flavor).
- **No GUI button** yet for Bend Luck (reaction timing — shares the out-of-band reaction UI).

## Bard (Phase 1 + core Bardic Inspiration implemented)

**Implemented:** Roll-API flat modifier (`roll`/`rollAdvantage`/`rollDisadvantage`/`rollToHit`
take an additive bonus, applied after die selection / Portent replacement, never altering the
natural d20's crit/fumble). Bardic Inspiration die as an additive `pending_roll_bonus_` (portent-
style plumbing): `grant_bardic_die` / `use_bardic_die`. Chassis `case Bard:` (CHA full caster,
DEX+CHA save profs, "Bardic Inspiration" resource = max(1, CHA mod), die-size scaling
6/8/10/12 at L1/5/10/15). `BardCollege` enum + `Stats::bard_subclass` /
`bardic_inspiration_die_size`. Font of Inspiration (L5: short-rest regen + `bard_regain_inspiration_from_slot`
slot-spend). Superior Inspiration (L18: `apply_superior_inspiration`, tops to 2 at combat start).
Tests in `gui/test_bard.py`.

### Deferred
- **[DEFER] Countercharm (L7)**: reaction to reroll (with advantage) an ally's just-failed save
  that would apply Charmed/Frightened. Deferred by request — needs a reaction hook at the
  charm/frighten save sites (no single save chokepoint; saves are computed inline at many sites).
  Revisit alongside the same out-of-band reaction plumbing planned for Lore Cutting Words.

### College subclasses (Phase 3 — combat-core slice implemented)
**Implemented:**
- **Dance L3** — Unarmored Defense (AC = 10 + DEX + CHA, unarmored), in `computeAC` (`combat_core.cpp`).
- **Lore L3** — Cutting Words: `bard_cutting_words` reaction expends a Bardic Inspiration use to
  SUBTRACT the die from the next D20 Test (negative `pending_roll_bonus_`).
- **Valor L6** — Extra Attack (`num_attacks = 2`) in the `case Bard:` chassis.

**Deferred (per scope / size):**
- **Dance**: Bardic Damage unarmed strike, Agile Strikes, L6 Inspiring Movement, L14 Leading Evasion.
- **Glamour** (entire college): Mantle of Inspiration (multi-target temp HP — reuse temp-HP path),
  Beguiling Magic, L6 Mantle of Majesty, L14 Unbreakable Majesty.
- **Lore**: L14 Peerless Skill (re-add die on the bard's own fail).
- **Valor**: Combat Inspiration (+AC / +damage modes — the natural next reuse of the held die,
  needs a `pending_damage_bonus_` and an incoming-attack AC hook), Martial Training, L14 Battle Magic.
- **[KNOWN LIMITATION] Out-of-combat / flavor**: Jack of All Trades, Expertise, Magical Secrets,
  Words of Creation — no combat-sim path; not implemented (per scope rule).

### GUI notes for subclasses
- Cutting Words has **no GUI button yet** (it's a reaction during another creature's turn; the
  engine model primes the negative bonus before that creature's roll). Engine fn + binding + tests
  exist; wire a reaction prompt when the out-of-band reaction UI is built (shared with Countercharm).
- **RAW timing simplification:** Cutting Words should trigger *after* a Lore Bard sees the roll, not
  before. This is the same missing mechanism as Counterspell/Countercharm — see
  **Architecture / Infrastructure → "Post-hoc reaction interrupts"**.

### GUI notes (Phase 4 implemented)
- College selectable in the stats dialog; `bard_subclass` saved/loaded (`agent_bard_subclass`).
- "Grant Inspiration" bonus-action button (targets an ally) and "Use Inspiration Die" button
  (any die-holder). **Use Inspiration Die primes the bonus BEFORE the next d20** (engine model),
  not RAW's post-hoc "spend after seeing a failed roll" prompt. No separate resource bar; the
  button only appears when a use/die is available (mirrors Lay on Hands).
