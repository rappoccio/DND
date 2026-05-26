---
name: known-limitations
description: "Known limitations in Barbarian implementation that require future work (Panther climb speed, Branches of the Tree reaction)"
metadata: 
  node_type: memory
  type: project
  originSessionId: e3daba3d-978d-4720-a63e-c3254b0b268b
---

## Known Limitations

**Date: 2026-05-21**

### Barbarian Reckless Attack Mechanic
- **Limitation**: Reckless Attack is always automatically triggered on any Barbarian melee/thrown attack miss
- **Why deferred**: Full Reckless Attack system would allow player choice to opt-in/opt-out per attack. Current auto-trigger avoids menu complexity.
- **Future**: Add toggle button or per-attack menu for player control

### Implemented Features ✅
- Barbarian L1-3: All core mechanics and subclass features
- Barbarian L5: Extra Attack, Fast Movement
- Barbarian L6: Berserker Mindless Rage, Wild Heart Owl/Salmon Aspects, Zealot Fanatical Focus

### Not Yet Implemented ❌

#### 1. Wild Heart L6: Panther Aspect (Climb Speed)
**Status:** Flavor feature, deferred

**What's needed:**
- Panther Aspect should grant climb speed = walk speed while Raging
- Currently, `speed_climb` field exists in Stats but is not integrated into movement system
- Movement system (walk/fly/swim in Agent class) would need enhancement to support climb speeds

**Why deferred:**
- Climb movement is not heavily used in typical D&D combat
- Requires changes to Agent's movement methods beyond scope of initial L6 work
- User indicated this is "flavor for now"

**Implementation when ready:**
1. Integrate speed_climb into Agent's movement validation
2. Add climb speed tracking (speed_climb_remaining) similar to walk/swim/fly
3. Bind climb speed remaining in Python for UI display
4. Test climb movement in combat scenarios

---

#### 2. World Tree L6: Branches of the Tree
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

**Why deferred:**
- Requires robust reaction system integration
- Must detect turn-start events and check nearby creatures
- Multiple conditional branches (save vs no save, speed reduction choice)
- Not critical to base combat flow

**Implementation when ready:**
1. Add turn-start event hook to runRound() or similar
2. When creature starts turn: check if any nearby Barbarians with Branches of the Tree are Raging
3. Trigger STR saves for each affected creature
4. Resolve teleportation and speed effects based on save result
5. Track reaction usage (Barbarian can only use reaction once per round)

---

#### 3. Illusionist L14: Illusory Reality
**Status:** Requires object system, deferred indefinitely

**Description:**
Illusionist capstone feature. When casting Illusion spell with slot, can make one inanimate nonmagical object from illusion real for 1 minute.

**What's needed:**
- Object/terrain creation system (currently doesn't exist)
- Object persistence (1-minute duration tracking)
- Object interaction (creatures can walk on/interact with created objects)
- Removal when duration expires

**Why deferred:**
- Requires fundamental world/terrain system we don't have
- Objects must be persistent entities in the battle system
- Not core to combat flow; primarily environmental utility
- High architectural cost for limited gameplay impact

---

#### 4. Wizard L3: Subclass Savant Features (All Subclasses)
**Status:** Requires spellbook system, deferred

**Description:**
Abjuration Savant, Divination Savant, Evocation Savant, Illusion Savant all grant:
- Add 2 spells of that school (L1-2) to spellbook for free
- Add 1 spell per new spell slot level gained (free)

**What's needed:**
- Spellbook data structure and tracking (which spells known vs prepared)
- Wizard subclass field in stats (✅ done)
- Spell school field (✅ done)
- Mechanic to auto-add spells based on school when leveling

**Why deferred:**
- Requires spellbook system separate from prepared spell slots
- Currently only track prepared spells, not known spells
- Would need UI/data model to display spellbook contents
- Feature is flavor (doesn't affect combat mechanics)

**Implementation when ready:**
1. Add spellbook tracking to Stats (list of known spells by name/ID)
2. When wizard gains level and new spell slot level → check subclass, add appropriate school spell
3. Display spellbook in character UI
4. Allow players to manage spellbook (add/remove spells via ritual scrolls, etc.)

---

#### 5. Wizard L3: Arcane Ward (Abjurer)
**Status:** Requires ward HP system, deferred

**Description:**
Create magical ward when casting Abjuration spell with slot.
- Ward HP = 2×wizard level + INT mod
- Ward absorbs damage (respects resistances)
- Regain HP when casting Abjuration spells
- Can only create once per Long Rest

**What's needed:**
- Temporary HP-like system but separate (ward ≠ temp HP)
- Ward persistence tracking
- Integration into damage calculation (damage goes to ward first)
- Restoration mechanics (regain HP on spell cast)

**Why deferred:**
- Requires parallel damage absorption system
- Complex interaction with existing HP system
- Would need testing for damage type interactions (resistances, etc.)
- High implementation cost for one subclass feature

**Implementation when ready:**
1. Add ward HP tracking to Conditions
2. In `executeDamage()`, check if ward exists and absorb damage
3. Track ward creation time (enforce once-per-LR rule)
4. Implement ward regeneration on spell cast

---

#### 6. Wizard L3: Portent (Diviner)
**Status:** Requires d20 roll hook system, deferred

**Description:**
Roll 2d20s after Long Rest. Can replace any D20 test (ability check, attack roll, save) by self or visible creature with portent roll (once per turn).

**What's needed:**
- Hook into d20 roll system (attack rolls, saves, ability checks)
- Allow spell/ability to override roll before it's used
- Per-turn replacement limit enforcement
- Portent roll expiration at next Long Rest

**Why deferred:**
- Requires intercepting/overriding d20 rolls throughout combat
- Affects attack execution, save resolution, ability checks
- Significant refactoring of roll infrastructure
- Complex interaction with advantage/disadvantage

**Implementation when ready:**
1. Add "roll hook" system to CombatEngine allowing features to intercept rolls
2. Store Portent rolls in Stats with expiration tracking
3. Before each roll (attack, save, check), consult hooks for overrides
4. Clear unused Portent rolls at Long Rest

---

#### 7. Wizard L6: Evoker - Sculpt Spells
**Status:** Requires team distinction, deferred

**Description:**
When casting Evocation spell, choose targets equal to 1 + spell level. Those targets auto-succeed saves and take no damage.

**What's needed:**
- Ability to distinguish allies vs enemies in AoE (red/blue team system)
- When executing Evocation spell with AoE, filter targets before applying effects
- Integration with spell execution pipeline

**Why deferred:**
- Requires team/faction system (currently all agents are generic)
- Would need to mark agents as ally/enemy
- Affects how AoE damage is resolved
- Needed for other mechanics (friendly fire, etc.)

**Implementation when ready:**
1. Add faction/team field to Stats (e.g., `int team_id`)
2. When resolving AoE targets, filter by team relationship
3. In executeSpell for Evocation spells, apply Sculpt Spells logic
4. Expand system for use in other contexts (party vs enemies, etc.)

---

#### 8. Wizard L6: Illusionist - Phantasmal Creatures
**Status:** Requires summoning system, deferred

**Description:**
Always have Summon Beast and Summon Fey prepared. Can cast them without slot (halves creature HP). Once per Long Rest without slot.

**What's needed:**
- Summoning mechanic (spawn creature at location for duration)
- Creature persistence and lifetime tracking
- Dismissal mechanic (can dismiss early)
- Duration expiration removal

**Why deferred:**
- Requires creature summoning system (not yet implemented)
- Would need to dynamically add/remove agents from battle
- Complex interaction with duration system
- Needs UI to show summoned creatures

---

#### 9. Agent Initialization Pattern Limitation
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

## Warlock (added 2026-05-23)

Built as a phased epic. **Phase 1 (Pact Magic foundation) is implemented**; everything else is
deferred. Scope is combat-only — flavor / out-of-combat utility is intentionally NOT modeled.

### Implemented (Phase 1) ✅
- Chassis: CHA spellcasting, WIS+CHA save proficiencies, `can_cast_spell`.
- `WarlockSubclass` enum (Archfey/Celestial/Fiend/GreatOldOne) + `warlock_subclass` field + GUI
  patron selection + save/load (`agent_warlock_subclass`).
- Pact Magic slots via `kPact` (uniform level), **short-rest recharge**, cast-at-pact-level
  (`pact_slot_level()`), Magical Cunning (recover ceil(max/2) once per long rest; all at L20).
- Tests: `test_warlock_l1_5.py`.

### Deferred to later phases ❌
- **Phase 2 — 4 patron subclasses' combat features**: Fiend (Dark One's Blessing temp-HP-on-kill,
  Dark One's Own Luck d10, Fiendish Resilience, Hurl Through Hell); Celestial (Healing Light pool,
  Radiant Soul +CHA radiant/fire, Celestial Resilience, Searing Vengeance); Great Old One (Psychic
  Spells damage-type swap, Eldritch Hex, Thought Shield psychic-resist+reflect, Clairvoyant
  Combatant); Archfey (Steps of the Fey misty-step uses, Beguiling Defenses charm immunity + psychic
  reflect, Misty Escape). These are specializations of existing engine pieces (temp HP, resistances,
  +CHA damage, condition immunities, healing pools).
- **Phase 3a (2026-05-24) — Eldritch Blast invocations ✅**:
  - **Implemented**: Eldritch Blast multi-beam (character-level scaling: 1 beam at L1, 2 at L5, 3 at L11, 4 at L17),
    Agonizing Blast (+CHA/beam), Repelling Blast (10 ft push/beam hit), Eldritch Mind (advantage on concentration saves).
    GUI invocation picker (checkboxes, gated by character level).
  - **Deferred (Phase 3b)**: Eldritch Spear range extension (not GUI-enforced), Devil's Sight, Pact of the Blade line
    (Thirsting Blade, Devouring Blade, Eldritch Smite, Lifedrinker — all require Pact-of-the-Blade weapon primitive).
    Invocation codes 4–9 reserved.
  - **Note on Eldritch Spear range**: GUI target selection does not currently validate spell range for Multiple geometry,
    so range extension requires inventing a range-enforcement system (deferred per spec).
  - **Tests**: `test_warlock_phase3.py`.
- **Phase 3b — remaining Eldritch Invocations** (deferred): Pact of the Blade weapon line (needs primitive), Devil's Sight.
- **Phase 4**: Mystic Arcanum (free 6th–9th-level cast/long rest), Eldritch Master.
- **Phase 5**: backfill missing Warlock/patron spells into `spells.json` (e.g. Hunger of Hadar,
  Witch Bolt) — many subclass "always-prepared" spells are absent.

### Needs new infrastructure (deferred) 🔧
- **"Always-prepared" spells mechanism**: patron spells and several invocation/feature spells are
  "always prepared." No engine mechanism exists; until built, the player prepares them manually.
- **Eldritch Invocation selection UI** + an at-will / once-per-rest free-cast mechanism for the
  "cast spell X without a slot" invocations.

### Not modeled (combat simulator only) 🚫
- Contact Patron / Contact Other Plane, telepathy (Awakened Mind), familiars (Pact of the Chain,
  Investment of the Chain Master), Pact of the Tome book/rituals, underwater breathing (Gift of the
  Depths), disguise/illusion utility (Mask of Many Faces, Master of Myriad Forms, Misty Visions,
  One with Shadows), planar travel, Gift of the Protectors, and other purely out-of-combat utility.

### Phase 2 (patron subclasses) — implemented vs deferred (2026-05-23)
**Implemented (Fiend / Celestial / Great Old One — specializations of existing pieces):**
Dark One's Blessing (temp HP on a kill), Fiendish Resilience (chosen damage resistance), Healing
Light (d6 heal pool), Radiant Soul (Radiant resistance + once/turn +CHA to radiant/fire spell
damage), Celestial Resilience (self temp HP on rest), Thought Shield (Psychic resistance).

**Deferred — Archfey patron (entire subclass), skipped for now.** Steps of the Fey, Misty Escape,
Bewitching Magic all hinge on a Misty Step *teleport primitive* + free-casting (new infra);
Beguiling Defenses needs the damage-reflect reaction hook below. Revisit when teleport lands.

**Deferred — features needing NEW hooks (not "specialize existing pieces"):**
- *Dark One's Own Luck* (Fiend L6): add 1d10 to a check/save after seeing it → needs an
  "add-to-roll" hook (Portent only *replaces* a roll, doesn't add).
- *Hurl Through Hell* (Fiend L14): on-hit, banish target (remove from map, return next turn) →
  needs a temporary-removal/return mechanic.
- *Searing Vengeance* (Celestial L14): intercept an ally's death save → needs a death-save hook.
- *Damage-reflect reactions* (GOO Thought Shield reflect, Archfey Beguiling Defenses) → need a
  reaction-triggered reflect-on-damage hook.
- *Psychic Spells* (GOO L3): per-cast option to change a spell's damage type to Psychic → needs a
  cast-time choice mechanism.
- *Eldritch Hex* (GOO L10): depends on the deferred "always-prepared" Hex + Hex's curse mechanics.
- *Awakened Mind / Clairvoyant Combatant* (GOO): telepathy (out-of-combat) — not modeled.
- *Dark One's Blessing ally-within-10ft trigger* and *Celestial Resilience ally temp HP*: the
  "you/an ally" and "up to 5 allies" parts need party/proximity targeting; only the self case is
  implemented for now.

---

## Rogue (added 2026-05-23)

Phased epic. **Phase 1 (chassis + Sneak Attack + core defenses) is implemented**; later phases and
out-of-combat utility are deferred. Combat-sim scope only.

### Implemented (Phase 1) ✅
- `RogueSubclass` enum (ArcaneTrickster/Assassin/Soulknife/Thief) + field + bindings + GUI patron
  picker + save/load (`agent_rogue_subclass`).
- Chassis: DEX+INT save proficiencies, Cunning Action flag (L2+), Slippery Mind (+WIS/CHA, L15+).
- **Sneak Attack**: once/turn `ceil(level/2)d6`, gated on a hit with a Finesse/Ranged weapon while
  having **advantage** on the roll. Mirrors the Zealot Divine Fury pattern (`sneak_attack_used`
  per-turn flag, `damage_breakdown` entry). Added before the base HP application so Uncanny Dodge
  can halve it.
- Steady Aim (L3, bonus action → advantage next attack + Speed 0), Uncanny Dodge (L5, reaction
  halves a hit), Evasion (L7, DEX-save → 0 on success / half on fail), Elusive (L18, no attacker
  advantage unless you're Incapacitated). Tests: `test_rogue_l1_18.py`.

### Deferred — needs the team/faction system 🔧
- **Sneak Attack "ally within 5 ft" trigger**: without ally/enemy distinction we can't detect a
  qualifying ally, so Phase 1 gates Sneak Attack on advantage only. (Same blocker as Evoker Sculpt.)

### Implemented (Phase 2) ✅
- **Cunning Strike** (L5: Poison/Trip/Withdraw) with die-cost validation, **Improved Cunning Strike**
  (L11: two effects), **Devious Strikes L14** (Knock Out/Obscure). Reuse Poisoned/Prone/Unconscious/
  Blinded; die-cost reduces Sneak Attack dice; per-attack GUI menu before execute. Tests:
  `test_rogue_phase2.py`.

### Deferred — Phase 2 continued (Cunning Strike riders)
- **Daze (Devious Strikes L14)** — "on its next turn the target can do only one of move / action /
  bonus action." Needs per-turn action-economy tracking the engine doesn't model; effect code 3 is
  treated as invalid until that exists. All other Cunning Strike effects are implemented.

### Deferred — Phase 3 (subclasses)
- Assassin (Assassinate first-round advantage + bonus damage, Death Strike, Envenom Weapons),
  Arcane Trickster (INT third-caster + Magical Ambush), Soulknife (Psychic Blades + energy dice),
  Thief (Supreme Sneak). Several need round/turn-order or initiative hooks.

### Deferred — need NEW hooks (not "specialize existing pieces")
- *Stroke of Luck* (L20): turn a failed d20 into a 20 → needs a roll-replace hook (Portent only
  *replaces*, and that itself isn't wired into the roll path yet).
- *Spell Thief* (Arcane Trickster L17), *Thief's Reflexes* (Thief L17, two turns round 1) → need
  reaction-on-cast and initiative-insertion hooks.

### Not modeled (combat simulator only / out-of-combat) 🚫
- Expertise, Reliable Talent, Thieves' Cant, Weapon Mastery, Fast Hands, Second-Story Work (climb —
  see Panther climb deferral), Use Magic Device, Infiltration Expertise, Mage Hand Legerdemain,
  Assassin's Tools, and other skill/utility features.

### Known fidelity note
- Uncanny Dodge halves base + Sneak Attack but not damage a Barbarian attacker adds *after* the base
  application (Divine Fury/Frenzy), and the auto-crit re-roll path (paralyzed/unconscious target)
  rebuilds the breakdown from the weapon only, dropping Sneak Attack — same pre-existing pattern as
  Divine Fury. Acceptable for Phase 1.

## Cleric

### Not modeled — Divine Order (L1) 🚫
- **Protector** (Martial weapon + Heavy armor training) grants nothing the engine models: weapons
  carry a per-weapon `proficient` flag with no class gate, and `canEquipArmor` only checks the STR
  requirement, not light/medium/heavy *training*. Would require real weapon/armor-training
  enforcement (separate infra) to mean anything.
- **Thaumaturge** (one extra cantrip + WIS-mod bonus to Intelligence (Arcana/Religion) checks) is an
  out-of-combat skill/known-spells feature.

### Deferred — Trickery Domain
- **Invoke Duplicity** (illusory duplicate: cast-from-illusion's-space, Distract advantage, move the
  illusion), **Trickster's Transposition** (teleport-swap with the illusion), **Improved Duplicity**
  (shared-distraction advantage, healing on dismiss). Needs an illusion/secondary-entity concept the
  engine doesn't have. **Blessing of the Trickster** (advantage on DEX (Stealth)) is out-of-combat.
  Trickery domain prepared-spell list can still load as data.

### Turn Undead — minor fidelity gaps
- Undead with **Frightened immunity** aren't spared (no creature condition-immunity system on Stats).
- "Ends early if the **caster is Incapacitated or dies**" isn't cascaded — only the 1-minute duration
  and the on-damage end (Infra B) are modeled.

### Deferred — Light Domain (beyond Radiance of the Dawn)
- **Warding Flare** (L3) / **Improved Warding Flare** (L6): a Reaction that imposes Disadvantage on an
  incoming attack roll (+ temp HP at L6). Needs a pre-roll reaction hook in `executeAction` (the
  engine's reactions, e.g. Uncanny Dodge, act *after* the hit). Resource is easy; the trigger is the work.
- **Corona of Light** (L17): aura granting Disadvantage on enemy saves vs the caster's Radiant/Fire
  spells — needs an aura/aura-save-modifier concept.
- **Radiance of the Dawn**: the "dispels magical Darkness in the area" clause is not applied (the
  damage + CON save + emanation targeting are). Light/darkness effect removal is out of combat-damage scope.
- **"Creatures of your choice" ally-exclusion**: Radiance (and AoE features with the same wording)
  currently affect *every* creature in range, not a chosen subset. The per-caster `safeTargets_`
  machinery (Evoker) can exclude specific allies manually, but auto-exclusion is deferred until a
  red/blue team (faction) system exists — at which point allies can be excluded by team.

### Deferred — War Domain spells (mechanics not modeled)
- **Crusader's Mantle** (L5 domain spell): a 30-ft aura granting allies +1d4 Radiant on their hits —
  needs an ally-buff aura that adds bonus damage to *other creatures'* attacks. Listed in the
  domain table; granting skips it until it's added to `spells.json` and the aura is modeled.
- **Steel Wind Strike** (L9 domain spell): teleport + attack up to five creatures — needs
  multi-target teleport/attack. Also listed-but-skipped until modeled.
- (War Priest, War God's Blessing, Guided Strike are implemented in the engine; War God's Blessing
  and the GUI prompts/buttons are the next work chunk, not permanent limitations.)
