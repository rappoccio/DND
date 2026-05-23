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
- **Phase 3 — combat-relevant Eldritch Invocations**: Agonizing Blast (+CHA to cantrip damage),
  Repelling Blast (push), Eldritch Spear (range), Devil's Sight, Eldritch Mind (advantage on
  concentration saves), Pact of the Blade (CHA finesse pact weapon + conjure), Thirsting Blade /
  Devouring Blade (extra attacks), Eldritch Smite, Lifedrinker.
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
