---
name: known-limitations
description: Comprehensive known limitations and deferred features across all character classes
metadata: 
  type: project
---

# Known Limitations

## Architecture / Infrastructure

### combat.cpp Refactoring [OPUS] — ✅ DONE (2026-06)
**Status:** COMPLETED. The monolithic `combat.cpp` (~7600 lines) was split into translation units;
`combat.cpp` is now a ~388-line orchestrator and the logic lives in the `combat_*.cpp` files:
`combat_core.cpp`, `combat_attack.cpp`, `combat_spells.cpp`, `combat_movement.cpp`,
`combat_conditions.cpp`, `combat_riders.cpp`, `combat_resources.cpp`, `combat_turn.cpp`,
`combat_state.cpp`, `combat_visibility.cpp`. All remain methods of the single `CombatEngine` class
(one class, many `.cpp`) — no header/API churn. Kept here only as a record that this is resolved.

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
- **OnD20Seen window — attack rolls** (IMPLEMENTED 2026-06-04, OND20SEEN_PLAN.md): the true post-hoc
  "react after seeing the d20" window now exists **for attack rolls** and hosts **Bend Luck** (Wild
  Magic Sorcerer), **Cutting Words** (Lore Bard), and **Silvery Barbs** (new L1 spell). It reuses the
  `InFlightAttack`/`beginAttack`/`advanceAttack`/`submitDecision` flow checkpoints with a multi-reactor
  cursor, runs **before** the OnHit Shield window, and is **lowering-only** (a reaction can turn a hit
  into a miss but never a miss into a hit → no post-hoc damage roll, identical to the Shield contract).
  Auto/RL: `maybeD20SeenInline`; GUI: the cursor block in `advanceAttack`. Engine in `combat_attack.cpp`
  (`canBendLuck`/`canCuttingWords`/`canSilveryBarbs`, `d20SeenReactors`/`d20SeenOptions`,
  `reevaluateAttackHit`, `apply{BendLuck,CuttingWords,SilveryBarbs}ToAttack`). *Remaining gaps:*
  (a) **saving throws & ability checks** still use the pre-roll prime (`pending_roll_bonus_`) — no save
  chokepoint yet, so Bend Luck/Cutting Words/Silvery Barbs vs a save/check are still primed before the
  roll; (b) **Bend Luck BOOST** direction (help an ally's attack *hit*) is deferred — a miss→hit flip
  needs damage rolled post-hoc; the window offers the penalty only; (c) **Silvery Barbs ally-advantage**
  rider not modeled (only the reroll); (d) **60 ft range gate untested** (12×12 test map ≈55 ft max,
  same as Counterspell); (e) a Silvery Barbs reroll that downgrades a **crit** but still hits keeps the
  originally-(crit-)rolled damage; expanded crit ranges aren't recomputed. The old pre-roll
  `sorcererBendLuck`/`bardCuttingWords` primes are **kept** for the save/check case.
- **Lore Cutting Words / Bend Luck vs SAVES & CHECKS** (still pre-roll): for non-attack-roll d20 Tests
  the Lore Bard / Wild Magic Sorcerer still primes the modifier *before* the roll (negative/positive
  `pending_roll_bonus_`) — the decider/player decides ahead of time. Same simplification as Bardic
  Inspiration `use_bardic_die` and Portent's pre-roll model. Lifting this needs a `beginSave`
  chokepoint (saves are rolled inline across dozens of spell/condition sites).
- **Counterspell** (IMPLEMENTED 2026-06-03, ONDECLARECAST_PLAN.md step 2): the OnDeclareCast window
  *is* the "pending decision / interrupt" mechanism for the cast case — `beginCast` yields between
  "spell declared" and "spell resolved" so any creature that sees the caster within 60 ft may cast
  Counterspell; the caster makes a CON save vs the counterspeller's DC; on a fail the cast fizzles and
  keeps its slot (2024 rules). **Recursive counter-counterspell IS now supported** (COUNTERSPELL_STACK_PLAN.md,
  DONE 2026-06-06): `cast_stack_` makes a Counterspell a genuine nested cast whose CON save is deferred to
  pop time, so a deeper Counterspell can negate it first; the chain is bounded by the reaction economy
  (1 reaction + 1 L3+ slot each) with a defensive depth cap. *Remaining gaps:* (a) the 60 ft range gate is
  untested (the 12×12 test map tops out at ~55 ft); (b) the yield-mid-resolution mechanism is now wired for
  **attack rolls** (OnD20Seen — see the entry above) but still NOT for **saves/checks** (Countercharm,
  and Cutting Words / Bend Luck vs a save/check, remain pre-roll).
- **Shield vs spell attacks** (IMPLEMENTED 2026-06-04): `executeSpell`'s per-target to-hit roll was
  extracted into `rollSpellAttack` (the spell analog of `resolveAttack`) so a single-target AttackRoll
  spell (Fire Bolt, Guiding Bolt, Chromatic Orb, Ray of Frost…) opens an OnHit Shield window between
  the roll and damage — `advanceCast` pre-rolls the to-hit and `executeSpell` consumes that same roll
  (a negated hit deals no damage / fires no concentration save). *Remaining gaps:* (a) **GUI multi-beam
  attack spells auto-fire Shield** — Scorching Ray / multi-beam Eldritch Blast roll each beam inside
  `executeSpell`, which has no per-beam decision cursor yet, so in the GUI (no decider) the target's
  Shield is **auto-cast inline** whenever a beam's +5 AC would flip it to a miss (the auto/RL path asks
  the decider; only single-target casts park for a human choice). Same deferral as Cleave. (b) **Seeking
  Spell + the single-target GUI window don't combine** — the pre-roll in `advanceCast` passes
  `MetamagicNone`, so a Sorcerer's Seeking reroll is skipped for a GUI single-target attack spell that
  opens the Shield window (rare; the auto/RL path applies Seeking normally).
- **OnSaveFail window — spell saves** (IMPLEMENTED 2026-06-04, ONSAVEFAIL_PLAN.md): the true post-hoc
  "reroll a just-failed save" window now exists **for directly-targeted (Single/Multiple geometry)
  Save-type spells**, hosting **Countercharm** (Bard L7, reroll an ally's failed charm/frighten save
  with advantage, costs the reaction) and **Indomitable** (Fighter L9, reroll your own failed save +
  Fighter level, costs an Indomitable use, not the reaction). It reuses the `InFlightCast`/`beginCast`/
  `advanceCast`/`submitDecision` flow checkpoints with a multi-reactor `(failed-target, reactor)` pairs
  cursor, and is **"raising-only"** (a reroll can only flip failure→success → less/no damage, no
  condition). The chokepoint is created by **pre-rolling** every target's save in `advanceCast`
  (`rollSpellSave`, the save analog of `rollSpellAttack`) so `executeSpell` consumes the corrected save
  (`InFlightCast.has_save_preroll`) — no undo needed. Engine in `combat_spells.cpp` (`rollSpellSave`,
  `canCountercharm`/`canIndomitable`, `saveFailReactors`/`saveFailOptions`, `reevaluateSave`,
  `apply{Countercharm,Indomitable}ToSave`, `applySaveFailReaction`). *Remaining gaps:* (a) **only spell
  saves** — the ~7 other inline save sites (beginTurn condition re-saves, weapon-condition riders,
  slipping terrain, concentration, Topple/Stunning Strike/maneuver, death saves) are NOT windowed, so
  Countercharm can't reroll a beginTurn frighten re-save and Indomitable can't reroll a concentration
  save; (b) **AoE-geometry save spells deferred** (Fear cone, Hypnotic Pattern cube) — their target
  list is resolved *inside* `executeSpell` (`resolveAoeTargets`), so only Single/Multiple geometry
  (targets == `action.target_indices`) is pre-rolled; (c) the separate **condition-rider save** on a
  non-Save-type spell (combat_spells.cpp `:861`) is not windowed (most charm/frighten spells are
  Save-type, so this is narrow); (d) **30 ft Countercharm range untested** (12×12 map); (e) Countercharm
  is **reaction-only, no Bardic die**, and Indomitable does **not** cost the reaction (RAW "no action")
  — both are v1 modeling choices.
- **OnTurnStartNearby window — the LAST of the 7 windows** (IMPLEMENTED 2026-06-05, ONTURNSTARTNEARBY_PLAN.md):
  fires inside `beginTurn`, hosting **Branches of the Tree** (when a creature starts its turn within the
  reactor's 5 ft reach, it makes a STR save vs the reactor's spell save DC or is Grappled). Unlike every
  prior window it needed a **new** transport — `beginTurn` is a synchronous `noexcept` function, so a new
  `InFlightTurn` + `beginTurnFlow`/`advanceTurnStart` flow-checkpoint pair (mirroring `beginCast`/
  `advanceCast`) wraps it, with its own `submitDecision` branch and a multi-reactor cursor. It's the
  simplest window (a post-effect, fire-and-forget interrupt: no pre-roll / re-evaluation, since the
  reaction doesn't change the `TurnStartResult`). Engine in `combat_riders.cpp` (`canBranchesOfTree`,
  `turnStartReactors`/`turnStartOptions`, `applyBranchesOfTree`, `applyTurnStartReaction`,
  `advanceTurnStart`, `beginTurnFlow`); `Agent::Stats::has_branches_of_the_tree`; GUI `_advance_turn`
  split into a `begin_turn_flow` head + `_finish_turn_start` continuation.
  **Sentinel is NOT in this window** (corrected 2026-06-05 after the first cut wrongly modeled it as a
  turn-start strike): RAW Sentinel clause 2 makes a creature provoke an **Opportunity Attack** from a
  Sentinel-feated threatener **even when it Disengages**. Implemented in the LeftReach/OA path:
  `detectProvokes` (combat_movement.cpp) checks Disengage **per-reactor** — a Disengaging mover still
  provokes a reactor whose `Agent::Stats::has_sentinel` is set. **Clause 1** (speed-0 on an OA hit) is
  also done (added 2026-06-06): when a Sentinel reactor HITS with its OA, `applyReactionResponse` sets
  `InFlightMove::mover_halted` so `advanceMove` commits only the partial move to the provoke cell and
  zeroes the mover's movement (both the engine budgets and the Agent's own `initMovement(0,…)`, which
  `moveAgent` reads) for the rest of the turn; the GUI menu/log flag it as a "Sentinel opportunity
  attack". *v1 limits:* (a) **Sentinel clause 3 deferred** — the "react when an adjacent enemy attacks an
  ally" melee strike is a separate `OnAllyAttacked` window inside `resolveAttack`, not built; (b) **5 ft
  reach only** for Branches (reach weapons / a treant's 10 ft deferred, like Riposte); (c) **no faction
  system** — every adjacent creature with the feat is offered the reaction regardless of side (the human/
  decider Skips), same model as OAs; (d) **skipped/down turns open no Branches window** (a paralyzed/
  unconscious/0-hp creature that "starts its turn" isn't offered); (e) **RL/headless (`runRound`) does not
  fire the Branches window** — `runRound` never calls `beginTurn` (Sentinel-via-OA DOES work in RL since
  it's in `detectProvokes`); (f) **Branches DC** = the reactor's spell save DC (based on its
  `spellcasting_ability`), grapple escape DC matches.
- **Vitality of the Tree (Barbarian, Path of the World Tree, L3) — OnTurnStartNearby consumer #2 [DONE 2026-06-06]**
  (built + green, awaiting commit). While raging, at the Barbarian's OWN turn start it may grant one
  creature within 10 ft Xd6 temp HP (X = `getRageDamageBonus(level)` = 2/3/4, min 1). Free (NOT the
  reaction), once per turn. The granted THP **vanish when this Barbarian's Rage ends**; the separate
  entry THP (= Barbarian level on entering Rage) persists. As built:
  - **Self-option in the window:** `turnStartReactors` now also pushes `source` itself when
    `canVitalityOfTheTree`; `turnStartOptions` emits `Feature "VitalityOfTheTree"` when `reactor==source`
    (Branches stays the `reactor!=source` branch). `applyTurnStartReaction` dispatches to
    `applyVitalityOfTheTree(bm, source, resp.target_idx)`. No new window. (`combat_riders.cpp`)
  - **Cost/gate:** per-turn `Agent::Conditions::vitality_used_this_turn`, reset in `Agent::turn()`
    (agent.hpp — the canonical per-turn reset; NOT combat_turn.cpp's top block, which is clobbered by the
    `cond = getAgentConditions()` re-read at the movement-seed step). Gate: WorldTreePath + L≥3 + raging +
    !used + a creature within 10 ft (`threateningAgents(src, 2)`).
  - **Provenance ("vanish on Rage end"):** added `int Agent::Stats::rage_thp_source_idx{-1}` next to
    `temp_hp` + a static helper `CombatEngine::grantTempHp(Stats&, amount, src_idx=-1)` (max() semantics +
    tags the granter, or clears the tag for non-rage grants). `endRage` loops all agents and zeroes temp_hp
    tagged with the ending Barbarian. Routed the in-combat non-rage grants (Dark One's Blessing, Wild Shape,
    Vitality entry) through the helper so a stale tag can't wipe their THP.
  - **GUI target click:** `_show_pending_reaction_menu` routes the Vitality option to
    `_begin_vitality_target_pick` (arms `pending_vitality_target`); a map click on a creature within 10 ft
    runs `_resolve_vitality_target` → builds `ReactionResponse(option, target_idx)` → `submit_decision`.
    Out-of-range/invalid picks re-prompt (don't waste the once-per-turn use).
  - **Bindings:** `can_vitality_of_tree`, `apply_vitality_of_tree`, `Stats.rage_thp_source_idx`,
    `Conditions.vitality_used_this_turn`. Tests: `gui/test_vitality.py` (14, all green; registered in
    run_all_tests.py). RL/headless `runRound` still never opens the window (same as Branches).
- **Use Inspiration Die** GUI: RAW the holder decides *after* a failed roll; the button primes it
  before instead.

**When ready:** Introduce a general "pending decision / interrupt" mechanism — the engine yields a
*decision point* object (roll value or declared-spell info + the set of creatures who may react),
collects reaction choices from the decider, applies modifiers/cancellation, then resumes. Cutting
Words, Counterspell, Countercharm, and the Use-Inspiration prompt all become consumers of it.

---

### Multiple bonus attacks must hit the same target [DEFER]
**Status:** GUI limitation — bonus multi-attack sequences auto-target and can't move between strikes.

**Context:** The Attack **action** sequence (Extra Attack) now uses an explicit re-click model — after
each attack the GUI *disarms* target-selection so the player can move, then re-clicks the standing
"⚔ Attack (N)" button to make the next attack (2026-06-04, requested by the user; fixes "clicking your
own sprite mid-sequence reads as a self-attack / out of range"). **Bonus** multi-attack sequences
(Flurry of Blows today; any future feat that grants several bonus attacks) were left on the old
auto-targeting flow: there is no standing mid-sequence *bonus* button (the bonus attack button is gated
on `not bonus_used` + an off-hand weapon), and Flurry's strikes all hit one creature so movement
between them isn't needed.

**Limitation:** A bonus multi-attack cannot move between strikes and effectively must spend all its
strikes on the same target it first clicks.

**When ready:** Give bonus multi-attack sequences the same disarm + standing-button model — add a
`mid_sequence_bonus` analog (count-labelled standing bonus-attack button, not gated on an off-hand
weapon) so the player can move and retarget between bonus strikes. See `_finish_attack` /
`_continue_attack_sequence_after_rider` (the `pending_attack_slot == "bonus"` branches kept the old
`_start_attack` auto-re-arm).

### Rider-laden Attack actions skip Frenzy / unarmed-weapon restore [minor]
The Attack-action sequence advance (disarm between attacks, `action_used`, ending the sequence) is now
done **centrally** in `_finish_attack` right after the attack-count decrement, so it runs for every
valid action attack regardless of which on-hit/on-miss rider (if any) fired — this fixes both the
"clicking your own sprite mid-sequence = self-attack/out of range" report and the re-seed-on-the-last-
attack bug for riders. However, **Berserker Frenzy's bonus attack and the unarmed-weapon restore** still
live only in the *no-rider* branch of `_finish_attack`, so when the triggering attack carried a rider
(brutal/cunning/divine/psionic/smite/etc.) those two side effects are skipped that swing. Rare in
practice (a Berserker's last action attack would need a rider for Frenzy to be missed). When unified,
move Frenzy + the unarmed restore next to the central commit (or route every rider through one complete
`_continue_attack_sequence_after_rider`).

---

### Attacker-rider → defender-reaction chaining ("rider shadows the defender's reaction") [OPUS] [DEFER]
**Status:** v1 limitation across every defender-side on-hit/on-miss reaction — deferred (not planned).

**Problem:** In the GUI, `_finish_attack`'s rider-offer chain is a single mutually-exclusive `if/elif`
ladder. An *attacker* rider (on-hit: Cunning/Brutal/Psionic Strike/Divine Smite/Stunning/Open-Hand/
Guided/Precision/etc.; on-miss: Precision/Guided/Reckless) is checked before the *defender's* reaction
(Riposte on a miss, Protective Field on a hit), which is offered **last**. So whenever the attacker is
also eligible for a rider on the same swing, the attacker rider fires and the defender's reaction is
**shadowed** that swing — only one rider can resolve per swing.

**Why this is acceptable for v1:**
- It's a natural reading of the timing: the attacker's miss→hit (or extra on-hit) conversion resolves
  first; if a miss converts to a hit there's no longer a miss to Riposte.
- It only bites when *both* the attacker and the defender have a same-window reaction on one swing —
  rare in practice.

**Coupled latent bug (would be fixed by the same work):** Riposte's callback calls
`_continue_attack_sequence_after_rider` but Riposte is **not** in the `has_rider` gate, so a synchronous
re-prompt *and* the callback can both advance → latent **double-advance**. Masked today because Riposte
fires on a miss, usually the last attack of the sequence. (Protective Field already uses the correct
pattern — it IS in the `has_rider` gate.)

**When ready (v2):** Offer the defender's reaction *after* the attacker's same-window rider resolves —
i.e. re-check Riposte once the attacker's on-miss rider has run and the attack is *still* a miss, and
re-check Protective Field after the attacker's on-hit riders. Restructure the `elif` ladder into a
proper post-rider chaining step, and fold Riposte into the `has_rider` gate as part of the cleanup
(retiring the double-advance above).

---

# Known Limitations

## Battle Master Fighter

### Riposte (IMPLEMENTED 2026-06-04 — see RIPOSTE_PLAN.md)
**Rule**: Reaction melee attack when a creature misses *you* with a melee attack; on a hit, add the
Superiority Die to the damage. Modeled on Reckless Attack's post-hoc-on-miss path: `applyAttackResult`
flags `conditions.riposte_available` on the **defender** (not the attacker — the one new direction);
the GUI prompts (`_offer_riposte` → `apply_riposte`), and the auto/RL driver consults
`chooseReaction` at an **OnMiss** window inline (`maybeRiposteInline`, the mirror of the OnHit Shield
path). The riposte fires *after* the triggering attack fully resolves, so it's a fresh top-level
`executeAction` — no decision stack.

**v1 limitations (deferred):**
- **Attacker-rider shadowing:** the GUI on-miss rider chain is mutually-exclusive `elif`, and Riposte
  is offered **last**. If the *attacker* is also eligible for an on-miss rider (Precision/Guided/
  Reckless) on the same swing, it shadows the defender's Riposte that swing. (Natural reading: the
  attacker's miss→hit conversion resolves first; if it converts, there's no miss to riposte.) Full
  chaining — offer Riposte *after* the attacker's on-miss rider resolves and the attack is still a
  miss — is v2. Rare in practice (both attacker and defender with on-miss reactions on one swing).
- **No fresh GUI Shield window for the riposte:** `applyRiposte` uses the atomic `executeAction`
  (like `applyRecklessReroll`), so the original attacker is not offered a *suspendable* Shield window
  against the riposte swing (auto/RL inline Shield still fires). Same deferral as Cleave.
- **Reach weapons:** eligibility uses 1-cell (5 ft) reach for the attacker-in-range check
  (`threateningAgents(..., 1)`); reach-weapon defenders (10 ft) are not yet handled.
- **Damage type:** the +Superiority-Die is added directly to `total_damage` with no resistance
  multiplier (consistent with Divine Fury / Berserker Frenzy bonus dice).

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

### Indomitable (L9) — IMPLEMENTED 2026-06-04 (ONSAVEFAIL_PLAN.md)
**Rule**: Reroll a failed saving throw (+ Fighter level on the new roll); uses regain on long rest
(1 at L9, 2 at L13, 3 at L17). Implemented as a consumer of the **OnSaveFail** reaction window: when a
directly-targeted spell save fails, a L9+ Fighter may spend 1 "Indomitable" resource use to reroll its
**own** save. Costs the use only, **not** the reaction (RAW "no action"). Engine `canIndomitable` /
`applyIndomitableToSave` (combat_spells.cpp). *Limited to spell saves this pass* — see the OnSaveFail
entry under Architecture → Post-hoc reaction interrupts for the deferred save sites.

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

### Psi Warrior — Protective Field GUI prompt (IMPLEMENTED 2026-06-04, GUI-only, no build)
The GUI now *offers* Protective Field to a hit Psi Warrior. `_finish_attack` gates eligibility via
`_can_protective_field(target_idx, result)` (Fighter L3+ Psi Warrior, reaction free, not incapacitated,
≥1 Psionic Energy die, hit dealt damage, not down — mirrors `applyProtectiveField`'s own checks) and a
new `has_protective_field` branch routes to `_offer_protective_field(atk_idx, target_idx, …)`, which calls
`apply_protective_field` and logs the prevention. It's a DEFENDER on-hit reaction (reactor = target),
modeled like `_offer_riposte` but using the **correct** sequence-continuation pattern: added to the
`has_rider` gate so only the callback's `_continue_attack_sequence_after_rider` re-prompts (no
double-advance). v1 limits:
- **Attacker-rider shadowing:** offered LAST in the on-hit `elif` chain, so any *attacker* on-hit rider
  (Cunning/Brutal/Psionic Strike/Divine Smite/…) on the same swing shadows the defender's Protective
  Field that swing (same mutually-exclusive-`elif` constraint as Riposte; full chaining is v2).
- **Can't save from a drop:** the engine models Protective Field as a post-hit heal-back and rejects a
  now-incapacitated defender, so the prompt is not offered when the hit drops the target to 0 (gated on
  `not result.target_down`). True damage-prevention-before-drop would need a pre-HP-mutation window.

### Deferred — Battle Master (remaining)
- **Riposte** — IMPLEMENTED 2026-06-04 (see the Riposte section above + RIPOSTE_PLAN.md); v1 limits only.
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

### Countercharm (L7) — IMPLEMENTED 2026-06-04 (ONSAVEFAIL_PLAN.md)
Reaction to reroll (with advantage) an ally's just-failed save that would apply Charmed/Frightened.
Implemented as a consumer of the **OnSaveFail** reaction window: when a directly-targeted charm/frighten
spell save fails, a L7+ Bard within 30 ft + LoS (or the failed creature itself) may spend its
**reaction** to reroll the save with advantage. Engine `canCountercharm` / `applyCountercharmToSave`
(combat_spells.cpp). Modeled as **reaction only, no Bardic die** (the repo's prior definition). *Limited
to spell saves this pass* — see the OnSaveFail entry under Architecture → Post-hoc reaction interrupts.

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
