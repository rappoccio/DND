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

## Eldritch Knight Fighter [OPUS]
Replacing one Attack-action attack with a cantrip (War Magic) interleaves attack and cast
economies. Same care needed as the Cleave/Nick economy. EldritchKnight enum value exists in
FighterSubclass; the attack↔cast substitution is [OPUS].

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

## Barbarian Reckless Attack Mechanic
- **Limitation**: Reckless Attack is always automatically triggered on any Barbarian melee/thrown attack miss
- **Why deferred**: Full Reckless Attack system would allow player choice to opt-in/opt-out per attack. Current auto-trigger avoids menu complexity.
- **Future**: Add toggle button or per-attack menu for player control

## Spell mechanics
- **Wall of Fire** and other "wall" spells are only able to be in one orientation. Needs to be updated.

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

### NOT IMPLEMENTED (Model boundary)
- **[OPUS] Eldritch Knight**: War Magic (turn-economy interleave)
- **[DEFER] Indomitable** (L9): save-reroll resource
- **[DEFER] Studied Attacks** (L13): advantage on next attack vs missed creature

---

## Sorcerer (Phase 1 + Phase 2 implemented)

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

### NOT IMPLEMENTED (Model boundary)
- **[OPUS] Subclasses** (Aberrant / Clockwork / Draconic / Wild Magic): enums are bound and
  stubbed; all L3/L6/L14/L18 features deferred. Notable hard pieces: Aberrant psionic spells
  cast via SP; Clockwork persistent ward dice; Draconic 3rd unarmored-AC formula
  (10 + DEX + CHA); Wild Magic 100-entry surge table + Tides-of-Chaos state.
