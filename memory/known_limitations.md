---
name: known-limitations
description: Comprehensive known limitations and deferred features across all character classes
metadata: 
  type: project
---

# Known Limitations

<details>
<summary><b>Grapple drag-movement double cost charged against the wrong budget — FIXED ✅ (2026-06-19)</b></summary>

**Symptom:** a Dashing grappler's movement appeared to cut out mid-turn. **Cause:** the 2×-drag surcharge was charged against the engine's separate `walkRemaining_` budget (which never receives a Dash) instead of the agent's own `speed_walk_remaining_` (the one `moveAgent` spends + the GUI shows). **Fix:** charge `actual_cost*2` against the single agent budget in `BattleMap::moveAgent`; removed the broken surcharge block from `CombatEngine::moveAgent`; GUI `_update_reach` halves previewed reach while grappling. Tests `test_grapple.py` (drag-double no-dash + scales-with-dash); suite 14/14. See [[dual_movement_budget]].

</details>


* Weapon property Nick is consuming bonus action. 
---

## Architecture / Infrastructure

### Render gate for the Invisible condition [TODO]
**Status:** The render-suppression chokepoint now EXISTS (built for Summoning): `_draw_one_agent`
returns early on `pt.removed_from_play`, and `_draw_agents` skips it for selection/highlight. What
remains is wiring the **Invisible condition** into that same gate: an invisible creature's sprite
should not be drawn to viewers lacking Truesight/Blindsight (today `Conditions.invisible` is set but
the sprite still renders). Reuse the existing gate rather than adding a second path. (Dismissed
summons no longer need this — they are also moved off-map to (-1,-1), so they render nowhere.)

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
- **OnD20Seen window — attack rolls** (IMPLEMENTED 2026-06-04): the true post-hoc
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
  keeps its slot (2024 rules). **Recursive counter-counterspell IS now supported** (
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
- **OnSaveFail window — spell saves** (IMPLEMENTED 2026-06-04): the true post-hoc
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
- **OnTurnStartNearby window — the LAST of the 7 windows** (IMPLEMENTED 2026-06-05):
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
  attack". **Clause 3 — Guardian** is also done (added 2026-06-10): the `OnAllyAttacked` window. After ANY
  attack resolves (`executeAction`), a Sentinel adjacent to the **attacker** (and not the attack's target)
  may spend its reaction to make a melee attack back. `canSentinelGuard` (combat_attack.cpp) is the gate
  (has_sentinel + reaction free + alive + melee weapon + attacker in 5 ft + target ≠ self and target lacks
  the feat); `maybeSentinelGuardInline` is the auto/RL window (scans, offers `OnAllyAttacked`, calls
  `applySentinelGuard`); the GUI gets the deferred flag `Conditions::sentinel_guard_available` (set on the
  attacker in `applyAttackResult`) → `_offer_sentinel_guard` (scans for the eligible Sentinel). Fires on a
  hit OR a miss; never alters the original attack. `resolving_sentinel_guard_` suppresses a guard-of-a-guard.
  Tests in test_reactions.py (counter-attack, target-is-Sentinel skip, adjacency gate, fires-on-miss,
  spent-reaction block, no-guard-of-a-guard). **Sentinel is now fully complete (all 3 clauses).**
  *v1 Guardian limits:* offered LAST in the single-rider GUI chain (an attacker's own on-hit/on-miss rider
  shadows it this swing, same v1 model as Riposte); 5 ft reach only; no faction system (decider/human Skips
  for allies). *Other v1 limits:* (b) **5 ft
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

<details>
<summary><b>Weapon on-hit conditions survive save/load + on-hit grapple is logged — FIXED ✅ (2026-06-17, confirmed in live play)</b></summary>

Two coupled on-hit-rider fixes (surfaced by a Vampire Spawn Claw Grappled rider lost on reload). **(1)** `helpers._weapon_to_dict` never serialized `Weapon.conditions`, so the save dropped ALL on-hit riders; now emits the full conditions list and `_dict_to_weapon` parses `requires_save`/`on_damage`. *Caveat: pre-fix saves lack the data — re-place from the bestiary.* **(2)** On-hit grapple now logs the contest/outcome at the rider call site (was `(void)resolveGrapple(...)`).

</details>

### Rider-laden Attack actions skip the unarmed-weapon restore [minor]
The Attack-action sequence advance (disarm between attacks, `action_used`, ending the sequence) is now
done **centrally** in `_finish_attack` right after the attack-count decrement, so it runs for every
valid action attack regardless of which on-hit/on-miss rider (if any) fired — this fixes both the
"clicking your own sprite mid-sequence = self-attack/out of range" report and the re-seed-on-the-last-
attack bug for riders. However, **the unarmed-weapon restore** still lives only in the *no-rider* branch
of `_finish_attack`, so when the triggering attack carried a rider (brutal/cunning/divine/psionic/smite/
etc.) that side effect is skipped that swing. When unified, move the unarmed restore next to the central
commit (or route every rider through one complete `_continue_attack_sequence_after_rider`).

NOTE: 2024 Berserker Frenzy is NOT a bonus attack — it is extra Nd6 damage (N = Rage damage bonus),
applied engine-side in `combat_attack.cpp` on the first hit each turn. The old 2014 bonus-attack code
was removed from `main.py` (it double-dipped alongside the engine's 2024 dice).

---

<details>
<summary><b>Uncanny Dodge + Guided Strike folded into the reaction framework (2026-06-08)</b></summary>

The last two ad-hoc interrupts now route through the reaction framework. **Uncanny Dodge** (Rogue L5) = OnHit defender option in `defenderOnHitOptions`; **Guided Strike** (War Cleric L3) = OnMiss option (runs before Riposte). **Deliberate change:** Uncanny Dodge is now decider-gated — with no decider it is SKIPPED (used to auto-apply), so it doesn't fire on OAs/Cleave/extra swings (same as Shield/Riposte). Tests `test_rogue_l1_18.py` / `test_cleric.py`.

</details>

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

<details>
<summary><b>Riposte (IMPLEMENTED 2026-06-04 — see RIPOSTE_PLAN.md)</b></summary>

Reaction melee attack when a creature misses you with melee; +Superiority Die on the hit. Defender-flagged (`riposte_available`) at the OnMiss window — GUI `_offer_riposte`/`apply_riposte`, auto/RL `maybeRiposteInline`; fires after the triggering attack resolves (fresh top-level `executeAction`). v1 limits: an attacker on-miss rider shadows it (mutually-exclusive `elif`); no suspendable Shield window vs the riposte; 5-ft reach only; +die added with no resistance multiplier.

</details>

<details>
<summary><b>Additional Maneuvers — IMPLEMENTED 2026-06-14 (test_fighter.py)</b></summary>

2024 maneuver set wired across the 3 reuse buckets, all sharing `applyManeuverEffect` + save DC `8+PB+max(STR,DEX)`. **On-hit save riders:** Goading (WIS / disadv-vs-others), Distracting (Vex-like), Disarming (STR / fight-unarmed 1 rd), Sweeping (`applySweepingAttack`, 2nd-target picker like Cleave). **Bonus-action:** Rally (temp HP), Feinting (advantage + die), Quick Toss (thrown + die). **Reaction (OnHit defender):** Parry (`canParry`, reduce damage by die+DEX). `dndMod` promoted to `combat_internal.hpp`.

</details>

### Deferred maneuvers — need new engine infra (combat-sim scope: defer-new-infra)
- **Lunging Attack** — +5 ft melee reach for one attack; needs a pre-attack reach-extension toggle
  (no per-attack reach override exists; reach is a weapon property today).
- **Commander's Strike** & **Maneuvering Attack** — grant an *ally* a reaction attack / reaction move
  on command; there is no "grant an ally a reaction on your turn" window (the reaction windows are all
  triggered by an event, not commanded).
- **Bait and Switch** — swap places with a willing creature + temp AC; no position-swap primitive.
- **Evasive Footwork** — add the die to AC *while moving*; no during-movement AC model.

### Out of scope — skill/social maneuvers (no combat-sim mechanical effect)
- **Ambush** (Stealth check / initiative bonus), **Commanding Presence** (Intimidation/Performance/
  Persuasion check), **Tactical Assessment** (Investigation/History/Insight check). These resolve as
  out-of-combat ability checks with no engine-modeled effect; intentionally not implemented.

---

## Fighter — Deferred Features

<details>
<summary><b>Indomitable (L9) — IMPLEMENTED 2026-06-04</b></summary>

Reroll a failed save (+Fighter level); uses regain on long rest (1/2/3 at L9/13/17). Consumer of the OnSaveFail window — on a failed directly-targeted spell save, spend 1 Indomitable use to reroll your own save. Costs the use, NOT the reaction (RAW). `canIndomitable`/`applyIndomitableToSave`. Spell saves only this pass (see the OnSaveFail entry for deferred save sites).

</details>

### Studied Attacks (L13) [DEFER]
**Rule**: Advantage on next attack roll against a creature you missed with a weapon attack.
Will reuse the existing `vex_target_idx` flag — trivial but out of scope for this pass.

---

## Paladin

<details>
<summary><b>Implemented ✅</b></summary>

Paladin chassis: CHA half-caster, Extra Attack (L5), WIS save prof. Channel Oath (2/3/4 uses), Lay on Hands pool (5×level). Oath of Devotion **Sacred Weapon** (BA, 1 Channel Oath → +CHA to attack rolls 1 min, `activateSacredWeapon`). **Divine Smite** (BA radiant on a melee hit: `(slot+1)d8`, +1d8 vs Undead/Fiend, once/turn, ranged excluded, interlocked with one-leveled-spell/turn). Tests `test_paladin.py`.

</details>

<details>
<summary><b>Auras (Aura of Protection L6, Aura of Courage L10) — IMPLEMENTED ✅ (2026-06-14, built + 72 suites green, confirmed in live play)</b></summary>

Team-scoped emanations (10 ft, 30 ft at L18; suppressed while down). `bestPaladinAura` = strongest CHA-mod bonus reaching a target (no stacking). **Protection** = +CHA to every save via the new `saveModFor()` helper that replaced ~9 duplicated per-site save-mod lambdas — **all new save sites MUST use it**. **Courage** = Frightened immunity, gated at the central `applyFrightened`. Read live (no flag/init). GUI gold aura ring + save-log prints `tr.save_mod` ("incl. +N Aura"). Allies only show it on the same team. Tests `test_paladin_auras.py`. Deferred: Oath-specific auras, the "ends existing Frightened" clause.

</details>

---

<details>
<summary><b>Eldritch Knight Fighter — IMPLEMENTED ✅ (2026-06-02, awaiting build)</b></summary>

Attack↔cast interleave done (full breakdown in the Fighter section below). Simplifications: Eldritch Strike (L10) is one-shot (clears on consume / next turn), not the RAW until-end-of-next-turn window; War Bond (L3) not modeled (out-of-combat flavor); RL War-Magic substitution isn't in the action space yet.

</details>

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

<details>
<summary><b>Barbarian Reckless Attack Mechanic — RESOLVED 2026-06-03 (built + green)</b></summary>

Now a choice with two entry points: pre-declare (existing button, gated on raging) and post-hoc on a miss (engine flags `reckless_reroll_available`; GUI `_offer_reckless_reroll`, auto/RL `choose_reckless`). Both set turn-scoped `reckless_attack` (enemies get advantage vs you until your next turn). Replaces the old silent auto-reroll. Tests `test_reckless.py`. Minor gaps: inline reroll doesn't grant Brutal Strike; post-hoc not logged for replay; post-hoc ignores `raging`.

</details>

<details>
<summary><b>Barbarian subclass L10 "Presence" abilities — IMPLEMENTED ✅ (2026-06-17, built + test_barbarian_l9_17.py green)</b></summary>

A batch of Barbarian features (`combat_resources.cpp`/`combat.cpp`), modeled on the Spirit Guardians emanation + Paladin-aura faction logic (`areAllies`, `saveModFor`); **Euclidean** emanation metric.
- **Intimidating Presence (Berserker L10):** 30-ft enemy-only emanation, WIS save or Frightened to end of Barbarian's next turn via `addAgentCondition` (routes through `applyFrightened` → honors Aura of Courage; do NOT also call `applyFrightened`). PB uses/rest, else a Rage use.
- **Zealous Presence (Zealot L10):** 60-ft, ≤10 allies, Advantage on attacks + saves (`Conditions.zealous_blessing`). Granter-relative expiry: `zealous_blessing_by = caster_idx`, cleared in `beginTurn` (NOT the buffed creature's `turn()`).
- **Action-economy gotcha:** `spendBonusAction` re-reads/writes stats, so it MUST run AFTER the final `setAgentStats`.
- **Relentless Rage (L11):** drop-to-0 while raging → CON save (`saveModFor`) vs `relentless_rage_dc` (10, +5/use, reset in `endRage`) → hp=1; hooked in `damageAgent` before the concentration-drop block. **⚠️ `damageAgent` is now NON-static.**
- **Primal Champion (L20):** +4 STR/CON (cap 25), idempotent via saved `primal_champion_applied`.
- **Feral Instinct (L7):** initiative advantage. **Instinctive Pounce (L7):** half-speed on Rage start — **⚠️ latent bug:** bumps the engine `walkRemaining_` map, not the agent budget, so it's invisible to real movement (same dual-budget trap as the grapple fix). **Indomitable Might (L18):** STR-save total ≥ STR score (`applyIndomitableMight`, wired into all STR-save sites).
- **Persistent Rage (L15) = inert by design:** the engine models no Rage early-end to suppress; documented, not coded.
- Tests `test_barbarian_l9_17.py`. Deferred: Berserker L14 Retaliation, Zealot L14 Rage of the Gods, rest of the L14 tier.

</details>

## Spell mechanics
- _(resolved 2026-06-02)_ **Wall of Fire** and other Rectangle "wall" spells are now placed with a two-click flow (anchor → endpoint), any orientation, free angle, length clamped to the spell's max. Geometry computed by `BattleMap::wallCells` (single source of truth); `SpellAction.aoe_col2/aoe_row2` carry the endpoint. NPC/RL casts without an endpoint fall back to the legacy centered box.

### Spell-data fixes + deferrals (2026-06-10)
- **Empty-damage data bug** — several damage spells shipped with `"magic_damage_types": []` (dealt 0
  damage). Fixed in `spells.json`: **Chromatic Orb** (3d8 Thunder — user), **Sorcerous Burst** (1d8
  Thunder), **Dragon's Breath** (3d6 Fire, already Cone/15ft/SaveDex). Worth re-scanning the file if more
  surface during play (most other "Harm + empty dice" entries are correctly non-damage utility spells).
- **Element-pickable spells — Chromatic Orb + Sorcerous Burst DONE 2026-06-11; Dragon's Breath deferred.**
  These spells let the caster CHOOSE the damage type at cast time. Implemented via design (a): a per-cast
  `SpellAction.damage_type_override` (int MagicDamage_t, -1 = none; bound + repr'd). `executeSpell` rewrites
  every `sp.magic_damage_rolls[].type` to the chosen type on its LOCAL mutable copy only — no persistent
  mutation of the stored spell, applied before Metamagic so Transmuted can still further convert. GUI:
  `App._activate` detects the spell via `ELEMENT_CHOICE_SPELLS` (main.py — option lists incl. Poison for
  both, Psychic for Sorcerous Burst only) → opens the reusable `ElementPickerDialog(multi=False)` →
  callback stores `pending_spell_damage_type` + sets up Single-target select → `_resolve_spell_cast`
  copies it onto `action.damage_type_override`. `_element_dialog` is a top modal in App's event/draw loop.
  Tests: test_element_spells.py (chosen type lands; resistance to chosen vs other type; override replaces
  the stored placeholder; per-cast only). **Dragon's Breath still hardcoded to Fire** (Cone/Save geometry,
  not yet wired — same `damage_type_override` mechanism would serve it once `ELEMENT_CHOICE_SPELLS` is
  extended and the AoE resolve path forwards the field).
- **Chromatic Orb "hop" / leap — IMPLEMENTED ✅ (2026-06-14, built + green, confirmed in live play).** RAW:
  if two or more of the d8s roll the same number, the orb leaps to a new creature within 30 ft (fresh
  attack + damage roll), chaining at a level-2+ slot. `executeSpell`'s AttackRoll target loop is index-based
  so leap targets are appended mid-loop and resolved like normal targets; gate `may_leap = (done==0) ||
  slot_level>=2`, match = a duplicate face in the just-rolled d8s. Leap target = the next entry of
  `SpellAction.chromatic_leap_targets` (GUI sequential map-click picker) if legal, else the nearest eligible
  enemy (living non-ally via `areAllies`, not already hit, `footprintDistance`≤30 ft); hard cap 20. NPC/RL/
  headless casts (no picker) still leap via the auto-nearest fallback. Also fixed a general bug: `Spell::
  upcast_dice_bonus` was stored/bound but never applied to damage, so upcast damage spells rolled base dice
  (a L9 Chromatic Orb only got 3d8); `executeSpell` now scales the local spell copy by
  `upcast_dice_bonus * (slot_level - level)`. Tests: `test_chromatic_orb.py` (10 cases). See memory
  `chromatic_orb_leap.md`.
- **Sorcerous Burst "explode on 8" (DEFERRED).** RAW: each d8 that rolls an 8 lets you add another d8 (up
  to your spellcasting modifier). Modeled as a flat 1d8 (no explosion / no level scaling for the cantrip).
- **Ray of Enfeeblement — no direct damage (RAW).** 2024 RoE deals **no** damage; it's a debuff (target
  has Disadvantage on STR-based d20 Tests and subtracts 1d8 from its damage rolls; Con save each turn to
  end). The empty damage array is correct. The debuff itself is **not modeled** (no "subtract 1d8 from
  damage rolls" condition — same gap as **Bane**'s −1d4). TODO: a damage-roll-penalty condition would
  cover both.
- **Cleric Channel Divinity lives in `classfeatures.json`, NOT `spells.json` (2026-06-10).** `Divine Spark
  (Harm)`, `Divine Spark (Heal)`, and `Radiance of the Dawn` are class features (with `resource_name:
  "Channel Divinity"` + `resource_cost`), auto-granted by `App._grant_class_features` keyed on class +
  level + subclass, with level-scaled dice baked by `_apply_feature_scaling` (1d8→4d8 + WIS mod at levels
  1/7/13/18). **Bug fixed:** `_load_agents` previously called `set_agent_spells` WITHOUT
  `_grant_class_features` (only `_apply_spells_to_agent` did), so loaded Clerics didn't get their Channel
  Divinity options, and any class-feature names persisted in a save's `spell_indices` warned "not found"
  (they're not in spells.json). Now `_load_agents` skips class-feature names during spell_indices
  resolution and calls `_grant_class_features` before `set_agent_spells`, matching the configure path.
  (Do NOT add these to spells.json — they belong in classfeatures.json.)

---

<details>
<summary><b>Summoning — IMPLEMENTED ✅ (2026-06-09, built + green)</b></summary>

Spells that manifest a controllable creature, dismissed on concentration loss. `bm.spawn_agent` (non-destructive append); `PlacedAgent.{summoner_idx, removed_from_play, summon_spell}`; `dropConcentration` tombstones the caster's summons + banishes them off-map to (-1,-1) (index preserved, never erased). Manual control on the summoner's initiative; GUI placement preview; render + save skip. Root-cause fix: `concentrationSave` routes through `dropConcentration`. Tests `test_summoning.py`. **Stand-in:** RAW summon spirit stat blocks aren't in the bestiary, so Summon Dragon → Spirit Dragon Wyrmling via `SUMMON_SPELL_TO_MONSTER` (wrong stats, no slot scaling). Deferred: RAW scaling stat blocks, rest of the Summon X line, multi-creature spawn, auto-control AI. See [[summoning_plan]].

</details>

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

## Wizard Features (Various)

### Illusionist L14: Illusory Reality [DEFER]
Requires object system; deferred indefinitely. Would need persistent object/terrain creation system.

### L3: Subclass Savant Features [DEFER]
Requires spellbook system separate from prepared spells.

### L3: Arcane Ward (Abjurer) [DEFER]
Requires parallel ward HP system separate from temp HP.

<details>
<summary><b>L3: Portent (Diviner) — IMPLEMENTED ✅</b></summary>

`CombatEngine::usePortentDie` — a Diviner banks a deque of d20 rolls (`Stats::portent_dice`, long-rest regen); spending one sets `pending_portent_die` so the next `roll()` returns it. One use/round (`agent_portent_round_used_`). Bindings `use_portent_die`/`regenerate_portent_dice`/`portent_dice`.

</details>

<details>
<summary><b>L6: Sculpt Spells (Evoker) — IMPLEMENTED ✅</b></summary>

Evoker **safe targets** (`safeTargets_`, caster→excluded indices; `set/getSafeTargets`) are fully excluded from that caster's AoE/zone effects — no save, no damage, no conditions — checked at the area-resolve sites in `combat_spells.cpp`. Allies are selected manually in the GUI for now; the same exclusion path backs Careful Spell + faction auto-sparing. See [[evoker_safe_targets]].

</details>

### L6: Phantasmal Creatures (Illusionist) [DEFER]
Requires creature summoning system.

---

## Cleric

### Not modeled — Divine Order (L1) 🚫
- **Protector** (Martial weapon + Heavy armor training) grants nothing the engine models
- **Thaumaturge** (extra cantrip + skill checks) is out-of-combat flavor

### Deferred — Trickery Domain
- **Invoke Duplicity** and related features need illusory-entity concept

<details>
<summary><b>Turn Undead (L2) + Sear Undead (L5) — IMPLEMENTED ✅</b></summary>

**Turn Undead** = Channel Divinity Magic action (`useTurnUndead`, Cleric L2+): each `is_undead` within 30 ft makes a WIS save or gains Frightened+Incapacitated 1 min (any damage ends it via `on_damage=End`); fear source = caster. **Sear Undead (L5+):** `max(1,WISmod)` d8 Radiant to each that fails, applied BEFORE the conditions so the on-damage end-rule doesn't cancel them. GUI button + log. Tests `test_cleric.py`. v1: turns ALL undead (no "of your choice" sparing), no Frightened-immunity, no caster-incapacitated cascade.

</details>

<details>
<summary><b>Light Domain — Warding Flare + Corona of Light — IMPLEMENTED ✅ (2026-06-15, built + 72 suites green)</b></summary>

**Warding Flare (L3):** OnD20Seen reaction (like Silvery Barbs, but Disadvantage) — when a creature ≤30 ft you can see hits you, spend reaction + 1 use to impose Disadvantage (can flip hit→miss). `canWardingFlare`/`applyWardingFlareToAttack`; `max(1,WISmod)` uses/long rest. **Corona of Light (L17):** Magic action (`activateCoronaOfLight`, 10-round window), enemies ≤60 ft have Disadvantage on saves vs the caster's Fire/Radiant spells (in `rollSpellSave`). **Radiance of the Dawn** ally-exclusion DONE (`selective_targeting` flag now carried by the GUI loader). Tests `test_cleric.py`/`test_d20seen.py`. v1: no actual bright-light emission for Corona; >60-ft range untested.

</details>

### Deferred — War Domain spells
- **Crusader's Mantle**: needs ally-buff aura for +1d4 Radiant
- **Steel Wind Strike**: needs multi-target teleport/attack
- **War God's Blessing**: underlying spells (Shield of Faith, Spiritual Weapon) are hollow

---

## Warlock (Phased epic, Phase 1 foundation implemented)

<details>
<summary><b>Implemented (Phase 1) ✅</b></summary>

Warlock chassis: CHA spellcasting, WIS+CHA save profs; `WarlockSubclass` enum (Archfey/Celestial/Fiend/GreatOldOne); Pact Magic slots (short-rest recharge), Magical Cunning.

</details>

<details>
<summary><b>Implemented (Phase 3a) ✅</b></summary>

Eldritch Blast multi-beam (1/2/3/4 beams); Agonizing Blast (+CHA/beam); Repelling Blast (10 ft push/beam); Eldritch Mind (advantage on CON saves).

</details>

### Deferred (Phase 2) — Patron subclasses
- Fiend: Dark One's Blessing, Fiendish Resilience (partially implemented)
- Celestial: Healing Light, Radiant Soul (partially implemented)
- Great Old One: Thought Shield (partially implemented)
- Archfey: Steps of the Fey, Misty Escape (need teleport primitive)

<details>
<summary><b>Phase 3b — Eldritch Invocations (mostly DONE — see the Eldritch Invocations section below)</b></summary>

Devil's Sight, Eldritch Spear range, and the **Pact of the Blade family** (Pact of the Blade / Thirsting Blade / Eldritch Smite / Lifedrinker) are implemented (2026-06-08). Still deferred: Pact of the Chain (summons), Pact of the Tome (char-building), Gift of the Protectors (Death Ward), Lessons of the First Ones (feats). See the Warlock Eldritch Invocations section.

</details>

### Not modeled (combat simulator only) 🚫
- Telepathy, familiars (Pact of the Chain blocked on a summon system), utility features

---

## Rogue (Phased epic, Phase 1 + Phase 2 implemented)

<details>
<summary><b>Implemented (Phase 1) ✅</b></summary>

Rogue: `RogueSubclass` enum (ArcaneTrickster/Assassin/Soulknife/Thief); DEX+INT saves, Cunning Action; Sneak Attack (once/turn, advantage + hit with finesse/ranged); Steady Aim, Uncanny Dodge, Evasion, Elusive.

</details>

<details>
<summary><b>Implemented (Phase 2) ✅</b></summary>

Cunning Strike (L5: Poison/Trip/Withdraw, die-cost validation); Improved Cunning Strike (L11: two effects); Devious Strikes (L14: Knock Out/Obscure).

</details>

### Deferred — Phase 2 continued
- **Daze** (Devious Strikes L14): needs per-turn action-economy tracking

<details>
<summary><b>Thief subclass — IMPLEMENTED ✅ (2026-06-19, built + 75 suites green, `test_rogue_thief.py`)</b></summary>

2024 Thief combat slice, mostly reused infra (no 2nd bonus action in 2024). Second-Story Work (L3: climb speed = walk); Supreme Sneak (L9: new Cunning Strike effect 6 — Thief-only AND only from stealth via `attacked_while_invisible`; the rider restores invisibility); Thief's Reflexes (L17: pure-GUI 2nd initiative entry at Init−10 round 1 — no engine call → untested). Deferred: Fast Hands (object infra), Use Magic Device (items).

</details>

<details>
<summary><b>Soulknife subclass — IMPLEMENTED ✅ (2026-06-19, built + 76 suites green + CONFIRMED IN LIVE PLAY, `test_rogue_soulknife.py`)</b></summary>

2024 Soulknife, reusing Psi Warrior Psionic Energy infra. Psychic Blades (synthetic finesse weapons), Homing Strikes (L9: miss→hit via a die), Psychic Teleportation (L9 BA), Psychic Veil (L13 invisible), Rend Mind (L17 stun). **Live-play hardening:** every synthetic class weapon (PsychicBlade/PactBlade/MonkUnarmed/Alter-Self) must be re-granted on load AND survive the Weapon dialog — idempotent `_apply_psychic_blades` now called from `_on_stats_ok`/`_on_weapon_done`/`_load_agents` (`rollDamage` reads only the damage-rolls vectors, so an unset blade deals 0).

</details>

<details>
<summary><b>Assassin subclass — IMPLEMENTED ✅ (2026-06-19, built + 77 suites green, `test_rogue_assassin.py`)</b></summary>

2024 Assassin, no new infra. New per-combat marker `has_taken_turn_this_combat`. Assassinate (L3): initiative advantage + advantage vs not-yet-acted targets + round-1 Sneak hit adds +Rogue-level damage. Envenom Weapons (L13): the Poison Cunning Strike costs 0 dice + deals 2d6 Poison ignoring Resistance. Death Strike (L17): a first-round Sneak hit → CON save or the whole attack's damage is doubled. v1: bonus damage is folded into the Sneak Attack path (fires on a qualifying Sneak hit, not any round-1 hit).

</details>

<details>
<summary><b>Arcane Trickster subclass — IMPLEMENTED ✅ (2026-06-19, built + 78 suites green, `test_rogue_arcane_trickster.py`)</b></summary>

2024 AT (last Rogue subclass), reusing existing infra. Spellcasting (L3): third-caster INT/Wizard (slot override in `case Rogue:`). Mage Hand Legerdemain = a summon (`MAGE_HAND_STATBLOCK`, persists, anchors Versatile Trickster). Magical Ambush (L9): a hidden/invisible AT → target saves at Disadvantage. Versatile Trickster (L13): advantage vs creatures within 5 ft of the Mage Hand. Spell Thief (L17): OnDeclareCast reaction — INT save or the cast is countered + the name added to `stolen_spell_names` (refuses a re-cast, cleared on long rest). v1: the "AT may now cast the stolen spell" half is deferred.

</details>

### Deferred — need NEW hooks
- *Stroke of Luck* (L20): turn failed d20 into 20 → needs roll-replace hook

### Not modeled (combat simulator only) 🚫
- Expertise, Reliable Talent, Thieves' Cant, weapon proficiencies, skill features

---

<details>
<summary><b>Weapon Mastery (Implemented: 9 of 9 types)</b></summary>

All 8 2024 masteries + Poison (custom), with once-per-turn limits: Sap, Slow, Vex, Push, Poison, Topple, Cleave, Graze (passive, per-miss), Nick (2026-06-11: the per-turn off-hand attack relocates into the Attack action, freeing the bonus action; Dual Wielder then adds a 2nd bonus-action off-hand attack → 3-attack turn). See the dual-wield rework in [[feat_system]].

</details>

---

## Druid (Phase 1 implemented)

<details>
<summary><b>Implemented (Phase 1) ✅</b></summary>

Druid: WIS full caster, INT+WIS saves; Wild Shape resource (L2+, 2/3/4 uses, short-rest regen 1); `DruidCircle` enum + GUI picker; Weapon Mastery on beast-form attacks; beast-form AC/STR/DEX/CON swap + restore; original weapons saved/restored on Wild Shape exit.

</details>

### Deferred — Wild Shape mechanics
- **Circle of the Moon L2**: bonus-action shift to beast form (turn-economy)
- **Circle of the Moon L6+**: increased durability, better damage
- **Circle of Wildfire**: Wildfire Spirit summon (needs summoning system)
- **Circle of Spores**: Symbiotic Entity (passive aura feature)
- **Circle of Land**: Land Circle Spells, Preserve Life (circle-specific deferred)

---

## Monk (Phase 1 implemented)

<details>
<summary><b>Implemented (Phase 1) ✅</b></summary>

Monk: DEX+WIS saves, Ki/Focus (= level, short-rest regen); Extra Attack L5; `MonkSubclass` enum; Open Hand Flurry of Blows (2 bonus unarmed strikes); Martial Arts die scaling; Unarmored Defense (10+DEX+WIS); Patient Defense / Step of the Wind; Stunning Strike (on-hit rider, eligibility flag in `executeAction` → `applyStunningStrike` out-of-band).

</details>

### Deferred — Monk features
- **Subclass mechanics**: Four Elements (Shadow is fully implemented — see Phase 1 in MONK_IMPLEMENTATION_PLAN.md).
- **Deflect Attacks — redirect clause** (L3): the damage-reduction half is implemented (`canDeflectAttacks`/`applyDeflectAttacks`, OnHit defender reaction reducing a hit by `1d10 + DEX + level`; B/P/S below L13, any type at L13 Deflect Energy). The RAW redirect — when the damage is reduced to 0, spend 1 Focus to make a ranged Unarmed Strike / throw the caught weapon at a creature within 5 ft — is **deferred** (no follow-up reaction-attack-from-defender plumbing). The reduction is the dominant combat effect; the redirect adds a single conditional attack.

<details>
<summary><b>Warrior of Mercy ✅ COMPLETE (2026-06-22)</b></summary>

Hand of Healing (L3: BA + 1 Focus → heal `MA die + WIS`); Hand of Harm (L3: deferred on-hit rider, `MA die + WIS` Necrotic — coexists with Stunning Strike, both out-of-band); Physician's Touch (L6: Harm also Poisons / Healing also ends one condition); Flurry of Healing and Harm (L11: free, once-per-target Hand of Harm auto-folded into `executeFlurryOfBlows`). `martialArtsDieSize` helper. Tests `test_monk.py`.

</details>

### Deferred — Warrior of Mercy
- **Hand of Ultimate Mercy** (L17): out-of-combat mass revive — flavor/out-of-scope (combat-sim only).
- **Flurry heal-replacement GUI picker** (L11): the engine primitive `handOfHealing(free=true)` exists, but there is no per-strike GUI flow to replace individual Flurry unarmed strikes with Hand of Healing (would need a heal-vs-strike target picker mid-flurry). The free Hand of Harm fold IS wired; the free-heal fold is engine-only for now.

---

## Fighter (Phase 1 implemented)

<details>
<summary><b>Implemented (Phase 1) ✅</b></summary>

Fighter: Extra Attack (2/3/4), `crit_threshold` (Champion 19/18), Second Wind (1d10+level), Action Surge, `FighterSubclass` enum. **Battle Master** (Superiority Dice + `applyManeuverEffect`: Trip/Menacing/Pushing/Precision). **Psi Warrior** (Psionic Energy dice: Psionic Strike on-hit rider, Protective Field reaction = post-hit heal-back, Telekinetic Movement push). Tests `test_fighter.py`.

</details>

<details>
<summary><b>Psi Warrior — Protective Field GUI prompt (IMPLEMENTED 2026-06-04, GUI-only, no build)</b></summary>

The GUI now offers Protective Field to a hit Psi Warrior (`_can_protective_field` gate + a `has_protective_field` branch → `_offer_protective_field` → `apply_protective_field`). It's a DEFENDER on-hit reaction added to the `has_rider` gate (correct callback continuation, no double-advance). v1 limits: an attacker on-hit rider shadows it (mutually-exclusive `elif`); can't rescue a target dropped to 0 (modeled as a post-hit heal-back, gated on `not target_down`).

</details>

### Deferred — Battle Master (remaining)
- **Riposte** — IMPLEMENTED 2026-06-04 (see the Riposte section above + RIPOSTE_PLAN.md); v1 limits only.
- **Additional maneuvers** — IMPLEMENTED 2026-06-14 (Goading/Distracting/Disarming/Sweeping/Rally/
  Feinting/Quick Toss/Parry; see the "Additional Maneuvers" section above). Remaining deferrals
  (Lunging, Commander's Strike, Maneuvering, Bait and Switch, Evasive Footwork) need new infra;
  skill maneuvers (Ambush, Commanding Presence, Tactical Assessment) are out of scope.

### Deferred — Champion extras
- **Remarkable Athlete** (bonus to non-proficient checks)
- **Second Fighting Style** (L3)

<details>
<summary><b>Eldritch Knight — IMPLEMENTED ✅ (2026-06-02, awaiting build)</b></summary>

Spellcasting chassis (L3: third-caster INT/Wizard, `compute_third_caster_slots` + Fighter-chassis override). **War Magic (L7):** engine gate `canUseWarMagic`/`war_magic_used`; GUI `war_magic` pseudo-slot decrements ONE attack instead of the action, once per Attack action (Action Surge permits another). **Improved War Magic (L18):** widens to L1–5 action spells. **Eldritch Strike (L10):** on-hit tag → target's next spell-save at Disadvantage (one-shot). **Arcane Charge (L15):** optional 30-ft teleport after Action Surge. Tests `test_fighter.py`.

</details>

### NOT IMPLEMENTED (Model boundary)
- **[DEFER] Indomitable** (L9): save-reroll resource
- **[DEFER] Studied Attacks** (L13): advantage on next attack vs missed creature

---

## Sorcerer (Phase 1 + 2 + 3 subclasses + 4 surge-engine implemented)

**Implemented:** Chassis (CON/CHA save proficiency), full-caster table-B slots, Sorcery
Points, Innate Sorcery (L1: +1 spell save DC + advantage on spell attacks, 10-round buff,
2 uses), Font of Magic (slot↔SP conversion both directions), and Metamagic foundation
(`SorcererSubclass`/`MetamagicOption` enums, `SpellAction.metamagic`, `metamagic_sp_cost`).

<details>
<summary><b>Metamagic — implemented options</b></summary>

Each applies for one cast via a temp spell copy (stored spell untouched); SP spent only when applicable: Heightened (2 SP, one target disadv save), Seeking (1, reroll a missed spell attack), Careful (1, exclude chosen allies — reuses the safe-target exclusion; save spells only), Distant (1, 2× range), Extended (1, 2× duration; inapplicable to instantaneous), Quickened (2, action→bonus via `cast_as_bonus_action`), Transmuted (1, retype elemental damage), Twinned (1, +1 `targets_per_upcast_level`).

</details>

### Metamagic — deferred / flavor
- **[DEFER] Empowered** (1 SP): reroll up to CHA-mod damage dice — needs the per-type damage
  loop restructured to capture dice before multipliers are applied. Logged, no SP spent.
- **[KNOWN LIMITATION] Subtle** (1 SP): cast without V/S components — purely out-of-combat
  flavor (no combat-sim effect); will not be implemented.

<details>
<summary><b>Subclasses (Phase 3 combat-core + Phase 4 Wild Magic surge engine)</b></summary>

**Draconic:** L3 Resilience AC = 10+DEX+CHA (`computeAC`) + L3 Resilience HP bonus (`hp_max += level`, idempotent via `draconic_hp_applied`); L6 Elemental Affinity (+CHA to first matching-type spell damage roll/turn, `draconic_affinity_type`/`draconic_affinity_used_this_turn`); L14 Dragon Wings (`activateDragonWings` → fly = walk, toggle). **Aberrant Mind:** L3 Psionic Spells (data-only always-prepared list in `main.py`); L6 Psychic Defenses (Psychic 0.5× resist + Charmed/Frightened save advantage at both save sites).

**Wild Magic:** L6 Bend Luck (spend 1 SP, ±1d4 on next d20 via `pending_roll_bonus_` — pre-roll prime; see Architecture post-hoc note). **Surge engine (Phase 4):** `applyWildMagicSurgeEffect` dispatch for bands 1/2/3/6/7/8/9/10 (terrain, +2 AC + Magic-Missile immunity, +5 HP/turn, bonus-cast/teleport windows, skip-turn, extra-action, drop-weapons); bands 4/5 cast a named JSON spell. The surge **TRIGGER** (`maybeWildMagicSurge`) fires after any slot cast (`_finish_cast` + teleport + summon paths): nat-20 → surge, or forced if **Tides of Chaos** (L3, `activateTidesOfChaos` + 1-use Resource) is expended, and a surge recharges Tides. GUI: Bend Luck + Tides of Chaos buttons + all window-band affordances. Tests in `test_sorcerer.py`.

**Clockwork Soul (Phase 5):** L3 Clockwork Spells (data-only always-prepared list in `main.py _SORCERER_SUBCLASS_SPELLS["Clockwork"]`, all 10 in spells.json); **L3 Restore Balance** = `OnD20Seen` reaction (`canRestoreBalance` / `applyRestoreBalanceToAttack`) that cancels **advantage** on an attack roll within 60 ft by reverting `r.d20` to the new `r.d20_primary` field (the first die rolled, captured in `rollToHit`) — a lowering that can flip a hit to a miss; PB uses / long rest, no SP, no new Stats flag (a Resource). Auto-surfaces in the generic reaction menu (no new GUI button). Tests in `test_sorcerer.py`.

**Deferred (with planned dispositions, updated 2026-06-24):**
- **[SONNET-ready — handoff written: `SORCERER_SP_FEATURES_SONNET_HANDOFF.md`]** Draconic L6 Elemental Affinity **SP-resistance half** (spend 1 SP → resistance to chosen type 1 hr) + the **element-picker dialog** in StatsDialog (reuse the Elemental Adept `ElementPickerDialog`; `draconic_affinity_type` round-trips but has no GUI to set it).
- **[SONNET-ready — same handoff]** Aberrant **Psionic Sorcery** (cast the always-prepared psionic spells by spending SP instead of a slot) — reuse the existing Font-of-Magic SP↔slot converter, made automatic for that list.
- **[WON'T DO]** Subtle Metamagic (above); Empowered Metamagic is **DONE**.
- **DONE 2026-06-24 (built clean; user runs tests):** Wild Magic **Controlled Chaos (L14) + Tamed Surge (L18)** (surge `offerWildMagicSurge`/`resolveWildMagicSurge` split + GUI choice menu); Aberrant **L14 Revelation in Flesh + L18 Warping Implosion** (`activateRevelationInFlesh` fly/swim/truesight w/ revert + `warpingImplosion` teleport + 30-ft DEX-save 3d10 Force burst); Clockwork **Restore Balance disadvantage-cancel** (new OnMiss raising direction: `canRestoreBalanceMiss`/`applyRestoreBalanceMissToAttack` + `restore_balance_miss_available` flag + GUI offer). Warping Implosion's "pull toward the space left" rider is deferred (damage+save only).
- **DONE earlier:** Clockwork L6 Bastion of Law, L14 Trance of Order, L18 Clockwork Cavalcade.

</details>

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

<details>
<summary><b>Countercharm (L7) — IMPLEMENTED 2026-06-04</b></summary>

Reaction to reroll (with advantage) an ally's just-failed save that would apply Charmed/Frightened. OnSaveFail window consumer — a L7+ Bard within 30 ft + LoS (or the failed creature itself). `canCountercharm`/`applyCountercharmToSave`. Modeled reaction-only, no Bardic die; spell saves only this pass.

</details>

<details>
<summary><b>College subclasses (Phase 3 — combat-core slice implemented)</b></summary>

**Dance L3** Unarmored Defense (10+DEX+CHA). **Lore L3** Cutting Words (reaction, −die on next d20 via `pending_roll_bonus_`). **Valor (L3/6/14, 2026-06-17):** Combat Inspiration (a held die → damage via `pending_damage_bonus_`, OR an AC defender reaction like Defensive Duelist; gating is self-contained — engine only checks the actor holds a die, GUI surfaces it for Valor parties); L6 Extra Attack; L14 Battle Magic (`battle_magic_available` → one bonus weapon attack after a Bard-spell Magic action). **Glamour:** Mantle of Inspiration (L3, BA, 2× die temp HP via `grantTempHp`, CHA-mod targets), Mantle of Majesty (L6, free Command recasts; Command fully modeled via `applyCommandEffect` + a Charmed-by-this-bard auto-fail), Unbreakable Majesty fixed (concentration drop now ends `majestic_presence_turns`). **Test gotchas:** `AttackResult` is read-only (build via `execute_action`); add ALL agents before `set_agent_spells` ([[agent_dual_list_gotcha]]). Deferred: Mantle-of-Inspiration reaction-move; Dance damage/L6/L14; Lore L14 Peerless Skill.

</details>

### GUI notes for subclasses
- Cutting Words has **no GUI button yet** (it's a reaction during another creature's turn; the
  engine model primes the negative bonus before that creature's roll). Engine fn + binding + tests
  exist; wire a reaction prompt when the out-of-band reaction UI is built (shared with Countercharm).
- **RAW timing simplification:** Cutting Words should trigger *after* a Lore Bard sees the roll, not
  before. This is the same missing mechanism as Counterspell/Countercharm — see
  **Architecture / Infrastructure → "Post-hoc reaction interrupts"**.

<details>
<summary><b>GUI notes (Phase 4 implemented)</b></summary>

College selectable in the stats dialog (`bard_subclass` saved/loaded). "Grant Inspiration" (targets an ally) + "Use Inspiration Die" (any die-holder) buttons. Use Inspiration Die primes the bonus BEFORE the next d20 (engine model), not RAW's post-hoc "spend after a failed roll". Button appears only when a use/die is available (mirrors Lay on Hands).

</details>

## Warlock Eldritch Invocations (combat-sim modeling)

Implemented (engine + GUI picker `InvocationDialog`): Agonizing Blast, Repelling Blast,
Eldritch Mind, Armor of Shadows, Fiendish Vigor, Devil's Sight, Eldritch Spear, Witch Sight,
One with Shadows, Otherworldly Leap, Gift of the Depths, Master of Myriad Forms, and the
**Pact of the Blade family** (Pact of the Blade, Thirsting Blade, Eldritch Smite, Lifedrinker).
Selected in a scrollable picker; unimplemented/level-locked/feat-deferred entries render greyed.

<details>
<summary><b>Pact of the Blade family (IMPLEMENTED 2026-06-08)</b></summary>

**Pact of the Blade** (inv 13): `Weapon::pact_weapon` flag + a fixed 1d8 slashing PactBlade (CHA allowed = best-of vs STR/DEX); appended in `_on_stats_ok` + load (idempotent). **Thirsting Blade** (inv 14, L5): `num_attacks=2` (global, not pact-only). **Eldritch Smite** (inv 15, L5): on-hit rider like Divine Smite — expend a pact slot (BA) → `(slot+1)d8` Force + knock Huge-or-smaller Prone, once/turn. **Lifedrinker** (inv 16, L9): automatic, +`max(1,CHAmod)` Necrotic + that many temp HP. **Devouring Blade** (inv 17, L12): `num_attacks=3`. Per-turn flags reset in `turn()` + `runRound`. Tests `test_warlock_phase3.py`.

</details>

### Deferred: rest of the Pact-boon family
- **Pact of the Chain** (inv 18) + **Investment of the Chain Master** (inv 19): an attacking
  familiar — **deferred until a summon/companion system exists** (same blocker as Wildfire Spirit
  / Phantasmal Creatures). Greyed.
- **Pact of the Tome** (inv 20): bonus cantrips/rituals — **deferred until a character-building /
  free-cantrip-grant system exists**. Greyed.

Modeling simplifications (deliberate, combat-sim scope):
- **Agonizing Blast / Repelling Blast / Eldritch Spear** are hardcoded to **Eldritch Blast**,
  not a freely chosen damage cantrip. EB is the only attack-roll damage cantrip in use here,
  so the "choose a cantrip" + Repeatable clauses are not modeled.
- **Armor of Shadows** is modeled as an always-on unarmored defense (AC 13 + DEX), i.e. the
  Warlock is assumed to keep Mage Armor up. No 8-hour duration / casting step.
- **Fiendish Vigor** grants its 12 temp HP (max 2d4+4) at the Warlock's **first `beginTurn`**
  of the combat, guarded by `fiendish_vigor_applied`. The flag is NOT reset on long rest, so a
  second encounter in the same session won't re-grant unless stats are reset. The pre-buff is
  treated as "already up" — temp HP is not present before the Warlock's first turn.
- **Devil's Sight** materializes `devilssight_range = 120` in `CombatEngine::setAgentStats`
  (idempotent), reusing the existing vision/blinded plumbing.
- **Eldritch Spear** extends EB range via `effectiveSpellRange` (bound `effective_spell_range`)
  and an `executeSpell` `sp.range` bump. The GUI range-circle / `filter_spell_cells` gate does
  NOT yet consult it — **unobservable on the maps in use** (EB base 120 ft >> ~55 ft maps), so
  the GUI plumbing is a deferred cosmetic follow-up (same class as the Counterspell 60 ft note).

### Deferred: Gift of the Protectors (invocation code 9)
Gift of the Protectors = "cast Death Ward CHA-mod times per long rest, for free" (drop to 1 HP
instead of 0). **Deferred** because Death Ward itself has no engine effect (present in
spells.json only — no drop-to-1 hook in the unconscious/death path). Implement Death Ward's
drop-to-1 mechanic + a per-long-rest charge counter first, then this invocation becomes a
free-cast grant. Stays greyed in the InvocationDialog (note: "needs Death Ward").

## Invisible condition (combat-sim modeling)

The Invisible condition now gates targeting and grants advantage (implemented 2026-06-08):
- A creature with `conditions.invisible` cannot be targeted by attacks/spells unless the
  viewer has Truesight or Blindsight in range (`canPerceiveTarget`, enforced in
  `availableAttacks`, `getBattleObservation`'s LoS flag, `computeVisibility`, and the GUI
  spell gate). Devil's Sight and Darkvision do NOT pierce invisibility.
- An invisible attacker rolls attacks with advantage (`AttackResult.advantage`).

Deliberate DM-call simplifications (deferred):
- **Disadvantage when attacking an unseen attacker is NOT modeled.** RAW, attacking a
  creature you can't see is at disadvantage; here, targeting an unseen creature is simply
  blocked, so that case doesn't arise. (DM-interpretation call — left out intentionally.)
- **Reaction eligibility** (`d20ReactorBase`, the save-reactor gate) still uses raw
  geometric `hasLineOfSight` and does NOT consult `canPerceiveTarget` — so an invisible
  creature can still be the subject of those reaction windows. Left out pending a rules call.

<details>
<summary><b>Invisibility / Greater Invisibility spells (data-driven)</b></summary>

Both are self/touch buffs (JSON `attack_type: Automatic`, `type: Harm` no-damage — no "Buff" SpellType exists; no `save_ability` ⇒ no save) applying the Invisible condition via `conditions:[{condition_name:"Invisible"|"GreaterInvisible"}]`. `addAgentCondition` maps those to `conditions.invisible` (+ `invisible_persists_on_action` for Greater). Duration modeled as 10 rounds (not RAW 1 hr / 1 min). One with Shadows reuses the same Invisible condition (non-persistent).

</details>

<details>
<summary><b>Monster on-hit riders: Grappled / Prone / Poisoned (2026-06-09)</b></summary>

Synthesized NPC weapons carry on-hit riders from `tools/monster_weapon_overrides.json` (via `monster_parser._weapon_for_slot`). **Grappled** → shared `resolveGrapple` core (`contested:false` = automatic on hit; `escape_dc` overrides the computed DC). **Prone** → weapon `mastery:Topple` (`to_record` auto-sets `weapon_mastery=1`). **Poisoned** → `addAgentCondition`. **Push/Pull** → on-hit forced move via `forceMoveAgent` (see the Roper Reel entry below; "Pull" data-drives a pull toward the attacker, so the Shambling Mound 5-ft pull is now expressible too). Deferrals: approximate save DCs (attacker-derived, not book), Poisoned has no auto-expiry, the beast-form `condition_rider` field is still inert, lycanthropy/javelin-slow riders.

</details>

<details>
<summary><b>NPC innate spellcasting auto-population (2026-06-09)</b></summary>

Monster innate spells (CSV At-Will/N-Day columns) are auto-loaded onto placed/summoned NPCs as `spell_indices` + `npc_spell_groups`; resolution in `read_stats_from_csv.attach_npc_spells` + `tools/add_npc_spells.py`; GUI glue `_load_npc_spells_from_record`. 161 casters / 886 spells. Approximations: at-will *leveled* spells use a 99/day budget; fixed save DC/attack columns ignored (engine computes); upcast annotations stripped; 7 referenced spells aren't in the catalog (skipped); typo fixes in `_SPELL_ALIASES`. See [[npc_innate_spellcasting]].

</details>

<details>
<summary><b>Origin feats (2026-06-09)</b></summary>

Combat-relevant 2024 Origin feats. `std::vector<std::string> feats` + `has_feat()` on Stats; `add_feat()` grants AND applies one-time effects (Tough HP, Alert init, Lucky points) — **on reload set `feats` directly** (bonuses already folded into persisted hp_max/luck_points, so re-applying double-counts). Implemented: Tough, Alert (+`swap_initiative`), Savage Attacker (reroll-keep-better, once/turn), Tavern Brawler (Unarmed 1d4+STR + reroll-1 + 5-ft push), Lucky (spend for advantage). GUI feat picker (one feat/PC, idempotent strip-then-apply). Deferred: Lucky disadvantage benefit, Healer (needs Hit-Dice pool), Magic Initiate free cast, out-of-combat feats. Tests `test_feats.py`. See [[feat_system]].

</details>

<details>
<summary><b>General feats — phase G0 + G1 (2026-06-10)</b></summary>

Foundation + the on-hit damage-type cluster. `Weapon` gained heavy/light flags; a multi-select FeatDialog (43 feats); **ASI is NOT auto-applied** (set final scores via the stat steppers); prereqs not enforced. In `applyAttackResult`: **Crusher** (Bludgeoning push 5 ft, once/turn), **Piercer** (reroll a die + crit bonus die), **Slasher** (−10 ft, once/turn), **GWM Heavy Weapon Mastery** (+PB on a Heavy Attack-action hit). **G1b enhanced-crit marks:** Crusher crit → advantage vs the victim; Slasher crit → victim's attacks at disadvantage (checked in `determineAdvantage`, expire at the feat-user's `beginTurn`, NOT the victim's `turn()`). **G2:** Sentinel (all 3 clauses), Grappler Punch-and-Grab (`resolveGrapple` core + advantage vs the grappled). **G3:** shield-in-off-hand foundation (`Weapon.is_shield`, `isHoldingShield`, `calculateAC` scans ALL weapon slots), War Caster (advantage conc saves), Mage Slayer (conc save disadvantage on weapon damage), Defensive Duelist (OnHit +PB AC), Shield Master push (`executeShove`). Tests `test_general_feats.py`.

</details>

<details>
<summary><b>General feats — phase G4 (bonus-attack + ranged-penalty) DONE 2026-06-11</b></summary>

**Ranged-penalty (pure gating):** Sharpshooter (clears long-range + within-5-ft disadvantage, any ranged), Crossbow Expert (engagement disadvantage, crossbows only), Spell Sniper (`rollSpellAttack` no-disadvantage + `effectiveSpellRange` +60 ft). **Bonus-attack:** GWM Hew (Heavy melee crit/kill → bonus attack via `_start_extra_attack`; v1 forgoes remaining Attack-action attacks), Dual Wielder (+1 AC with two melee weapons). **Polearm Master DEFERRED** — needs a synthetic butt-end weapon profile (clause 1) + a new *enter-reach* reaction window (clause 2). Tests `test_general_feats_g4.py`.

</details>

<details>
<summary><b>General feats — phase G5 (armor / saves / movement passives + Telekinetic) DONE 2026-06-11</b></summary>

Passives that query `hasFeat` at point of use (idempotent, no stat mutation): Heavy Armor Master (−PB on B/P/S weapon hits in Heavy armor), Medium Armor Master (DEX cap 2→3), Durable (advantage death saves), Speedy (+10 ft + OAs-vs-you disadvantage via `Attack::opportunity`), Athlete (standup 5 ft), Skulker (Blindsight 10 ft, into `piercesInvisibility`), Telekinetic Shove (30-ft BA, STR save or push 5 ft via `forceMoveAgent`), Weapon Master (Nick gate accepts the feat), Resilient (marker). **Binding fix:** `Armor.dex_mod_cap` was never bound (defaulted to 30 → no DEX cap ever applied); now bound + round-tripped. Tests `test_general_feats_g5.py`.

</details>

<details>
<summary><b>General feats — phase G5b (resistance-ignore caster feats) DONE 2026-06-11</b></summary>

Two shared helpers (`combat_spells.cpp`): `effectiveMagicDamageMult` lifts Resistance to 1.0 (Immunity/Vulnerability untouched), `rollSpellTypeDamage` does treat-1-as-2 — applied at all 5 spell magic-damage sites + the weapon magic-damage site. **Elemental Adept** (chosen elements in `elemental_adept_types`, spells only) + **Poisoner Potent Poison** (Poison, any source incl. weapons). Reusable `ElementPickerDialog` (also the cast-time picker for Chromatic Orb / Sorcerous Burst). Tests `test_general_feats_g5b.py`.

</details>

<details>
<summary><b>Fighting Style feats (2024 PHB) — Blind Fighting DONE 2026-06-10</b></summary>

Fighting Styles modeled as feats (`hasFeat`). **Blind Fighting:** Blindsight 10 ft queried inside `piercesInvisibility` (NOT via `blindsight_range` — sense ranges aren't serialized, feats are) + a latent fix gating invisible-attacker advantage on `!canPerceiveTarget`. **Passive batch:** Archery (+2 ranged), Defense (+1 AC armored), Dueling (+2, one-handed solo weapon), Thrown Weapon Fighting (+2), Great Weapon Fighting (reroll 1/2→3), Unarmed Fighting (1d6), Two-Weapon Fighting (no-op marker). **Interception:** OnAllyAttacked bystander damage reduction (1d10+PB heal-back, like Protective Field). **Still deferred: Protection** (needs a pre-resolution impose-disadvantage window — the hardest). Tests `test_fighting_styles.py`/`test_reactions.py`.

</details>

<details>
<summary><b>Bug fixes 2026-06-10</b></summary>

**NPC/monster weapons survive save→load:** `_save_agents` now writes the full `_weapon_to_dict` per slot (was name-only → dropped non-catalog Bite/Claw/custom attacks); `_load_agents` reconstructs from the dict (still accepts a bare name for old saves). Test `test_save_load_weapons.py`. **Self-origin spell range ring:** the cast-time range circle now uses `radius` for Cone / `length` for Line (was `sp.range`=0 → a 0-ft ring for Cone of Cold).

</details>

<details>
<summary><b>Factions / Teams (2026-06-11)</b></summary>

N-faction team system (`PlacedAgent.faction`, int; 0 = neutral, allied with no one). `areAllies(bm,a,b)` = same non-zero faction. Five rules: (1) same-faction observers don't block/spot a hide; (2) harmful AoE friendly-fire stays ON by default, allies spared only via safe-targets/Careful/`selective_targeting`; (3) beneficial (Heal) AoE drops non-allies when caster faction ≠ 0; (4) GUI `_confirm_friendly_harm` prompt; (5) allies don't provoke OAs (`detectProvokes` skips `areAllies`). `TeamPickerDialog`; faction persists; summons inherit the summoner's. Tests `test_factions.py`. Deferred: directional neutral-claim matrix, control-mode-per-team, Careful full-exclude vs RAW half-on-success.

</details>

---

<details>
<summary><b>Ranger — Beast Master (Primal Companion) — IMPLEMENTED ✅ (2026-06-13, built + 71 suites green)</b></summary>

L3 Primal Companion (Land/Sea/Sky stat blocks in `primal_companions.json`, HP/AC/to-hit/dmg scale with level; faction/summoner-linked, tombstoned on death/dismiss; `compute_companion_loadout`). L7 Exceptional Training (companion gains Cunning Action + natural weapon → Force). L11 Bestial Fury (`num_attacks=2` + once/turn the first hit on the HM target deals +Force = the mark's dice). L15 Share Spells (a Self-range buff the Ranger casts is re-applied to the companion ≤30 ft, same concentration, no extra slot). Deferred: L7 Dodge/Help, L7 Force has no opt-out, L15 GUI-only + true-Self-buffs only. See [[ranger_progress]].

</details>

<details>
<summary><b>Ranger — Fey Wanderer — IMPLEMENTED ✅ (2026-06-13, combat-core; awaiting build)</b></summary>

L3 Dreadful Strikes (first weapon hit each turn +1d4→1d6 Psychic at L11, no resource). L7 Beguiling Twist (Advantage on saves vs Charmed/Frightened spells, gated inline at both spell-save sites). Always-prepared spells: Charm Person / Misty Step / Dimension Door / Mislead. Tests `test_ranger.py`. Deferred: L9 Summon Fey (not in spells.json), the L7 redirect Reaction, L11/L15 free-casts, out-of-combat Otherworldly Glamour.

</details>

---

<details>
<summary><b>Ranger — Hunter & Gloom Stalker (Phase 3 leftovers) — IMPLEMENTED ✅ (2026-06-14, built + 71 suites green)</b></summary>

Hunter L11 Superior Hunter's Prey (after the mark takes HM damage, splash a fresh roll of the same dice to the nearest enemy ≤30 ft of the mark, once/turn). Hunter L15 Superior Hunter's Defense (OnHit defender reaction, like Uncanny Dodge — v1 resists only the triggering hit). Gloom L11 Sudden Strike (one free extra attack). In-dialog Hunter's Prey / Defensive Tactics pickers. Deferred: Gloom L11 Mass Fear, L15 Shadowy Dodge (needs a pre-roll defender-disadvantage window + teleport), L3 Umbral Sight (lighting model), Phase-2 follow-ups (favored-enemy free-cast accounting, re-mark-on-kill, spell-attack marks, Roving armor gate). See [[ranger_progress]].

</details>

<details>
<summary><b>Vampires / monster bite drain (2026-06-16, built + 73 suites green, confirmed in live play)</b></summary>

`available_hit_points` (HP-max reduction mirroring `temp_hp`; `effectiveMaxHp()`; healing caps to it; cleared on long rest; saved + GUI bar). `VisibilityLevel::Sunlight` bright-light category. `reduceHPMax` on-hit rider (drains the Necrotic damage dealt off the target's HP max + heals the attacker); Vampire Spawn bite in its `off_hand` slot. See [[vampire_support]].
- **Auto-hit-if-grappled (2026-06-17):** `Weapon::auto_hit_if_grappled` promotes a missed roll to a hit vs a target THIS attacker has grappled (roll still made — nat 20 still crits; fires after `resolveAttack`, before defender windows, so Shield can still negate). Set on the 5 vampire drain Bites. Not *gated* on Grappled — any target can be bitten.
- **Sunlight Vulnerability (2026-06-18):** `is_vampire` flag on 6 true vampire types; `beginTurn` deals 20 radiant if the vampire stands in a Sunlight light effect. See [[vampire_sunlight_vulnerability]].
- **On Deck reinforcements (2026-06-19):** `PlacedAgent.on_deck` reserves are out of initiative until the DM deploys them; they take NO reactions / legendary actions / OAs until deployed (gated in `d20ReactorBase`/`saveReactorBase` + per-predicate `can*` + `detectProvokes`). Round-trips in save/load. See [[on_deck_reinforcements]]. Limitations: reserves are still on the map (targetable before deploy); deploy is one-way during combat.
- Tests `test_vampire.py`. Deferred: Sunlight Sensitivity reactions, no lighting-editor to paint Sunlight, bite not gated on Grappled, no per-weapon attack cap.

</details>

<details>
<summary><b>Regeneration — turn-start HP regain with damage-type interrupt (2026-06-28)</b></summary>

Data-driven Regeneration (Troll, Slaad, …). New `Agent::Stats` fields: `regeneration_amount` (HP regained at the start of each turn, capped at `effectiveMaxHp()`, requires ≥1 HP), `regen_interrupt_damage_types` (vector of `MagicDamage_t` indices that switch regen off — Troll `[Acid, Fire]`), and the transient `regen_suppressed` flag. `beginTurn` (`combat_turn.cpp`) does the heal and consumes `regen_suppressed`.

**2024 vampires do NOT passively regenerate.** Verified against the 5.5e Monster Manual stat block (2026-06-28): the 2014 "regain 20 HP/turn unless in sunlight/running water" Regeneration trait was removed in the 2024 redesign. A 2024 vampire heals only via its **Bite Life Drain** (target's HP-max drops by the necrotic dealt and the vampire heals that much) — already modelled by the `reduceHPMax` bite rider + `available_hit_points`. So this feature is **not** applied to vampires; `derive_regeneration.py` triggers only on the explicit "Regeneration" trait, not `is_vampire`.

**Two interrupts, one mechanism.** (1) **Damage type:** `processDamageTaken` gained a `magic_type_mask` arg (bitmask over `MagicDamage_t`); when it intersects the target's `regen_interrupt_damage_types` it sets `regen_suppressed`, skipping the next turn's regen. All 6 `processDamageTaken` call sites (weapon + Restore-Balance + Hunter's-Mark splash in `combat_attack.cpp`; single-target + zone + ticking-fx in `combat_spells.cpp`) pass the mask via `magicTypeMask` / `magicTypeMaskFromSpell` / `magicTypeBit` helpers in `combat_internal.hpp`. (2) **Sunlight:** *not* a separate field — the existing vampire Sunlight block already deals Radiant at turn start, so it just sets `regen_suppressed` directly. This coupling is general and inert for canon vampires (their `regeneration_amount == 0`); kept so any creature that *does* regenerate is correctly suppressed by sunlight radiant.

Round-trips via `agent_loader.dict_to_stats` + `main.py` save block (`regen_suppressed` is transient, intentionally not saved). Bestiary values are populated by the one-shot tool `tools/derive_regeneration.py` (curated `REGEN_TABLE` keyed by name; dry-run by default, `--write` to apply). Tests: `test_regeneration.py`.

**Deferred (DM ruling): the "dies only at 0 HP" rule.** RAW a Troll/Vampire is destroyed only if it *starts its turn at 0 HP and fails to regenerate* — i.e. a regenerator dropped to 0 isn't truly dead and can revive next turn unless its specific weakness (fire on a downed troll, etc.) was applied. Not modeled: 0 HP follows the normal Unconscious/death path here, so a downed regenerator stays down. Revisit if a campaign needs trolls to claw back from 0.

</details>

<details>
<summary><b>Roper Reel — data-driven on-hit "Pull" rider (2026-06-28)</b></summary>

The Roper's **Reel** ("pull a Grappled target up to 30 ft toward the Roper") is modeled as a new data-driven **`"Pull"`** on-hit weapon condition, the mirror of the existing `"Push"` rider. `combat_attack.cpp` generalizes the Push handler to also accept `"Pull"`, calling the *same* `BattleMap::forceMoveAgent(target, attacker.origin, push_ft, pull=true)` core that the Monk's Elemental Attunement pull uses. `push_ft` already round-trips through both `helpers.py` serializers, so the rider is otherwise pure data: the Roper's Tentacle (`DND2024_MonsterStats.json`) gains `{"condition_name":"Pull","push_ft":30}` alongside its `Grappled`(escape DC 14) + `Poisoned`. Grappled resolves first, then the reel.

A pulled target **stops adjacent to the puller and never moves onto, past, or around it**, and reels **straight in** rather than drifting to a corner. Two geometry fixes were needed for the **Large** 2×2 Roper (both verified in live play 2026-06-28):

1. **Stops on contact (no fly-past / corner-cut).** `forceMoveAgent` gained a `from_size` arg (the puller's footprint side) and ends the reel the instant the victim is *already adjacent* (`footprintDistance <= 1`), checked at the top of each move loop. The earlier "don't step onto the body" guard (`== 0`) was insufficient: a **diagonal** reel cut the corner of the 2×2, holding distance 1 the whole way while crossing clear to the far side ("flying past"). `footprintDistance` moved from `combat_internal.hpp` to `cell.hpp` (the map/geometry layer) so `BattleMap` can share the single-source adjacency gap. Agents are still NOT obstacles for general movement; the clamp is scoped to the pull's own puller.

2. **Reels in one line (no origin-corner drift).** Direction is computed against the puller's whole **footprint span** (`from_size`), not its top-left origin cell — so an axis the victim already shares with the footprint contributes 0 and it pulls straight in. For a size-1 puller this reduces exactly to the old origin-cell logic, so existing push callers are unchanged.

The same `from_size` path also protects the Monk's Elemental Attunement pull (`combat_resources.cpp`). Note `push_ft` is data-driven (the Roper passes `weapon_cond.push_ft` = 30); the hard-coded `10` in other pull call sites belongs to those callers (Monk etc.), not the Roper.

**Deliberate combat-sim simplification:** RAW, Reel is a *separate action* gated on the target already being Grappled. Here it is **folded into the Tentacle's on-hit rider** — one hit grapples, poisons, AND reels the target up to 30 ft inward, halting adjacent (in bite range, the tactical intent). It is not a standalone gated action; promoting Reel to a true separate, grapple-gated GUI action would need a new action button + engine entry point (not data-only). Tests `test_roper.py`.

</details>

<details>
<summary><b>Floating combat-outcome flashes — emanation/zone saves not covered (2026-07-06)</b></summary>

Short-lived on-map text flashes above the involved token: **"Hit (N)" / "Crit (N)" / "Miss"** over an attack's target, **"Saved" / "Failed"** over a saving creature. Pure GUI (pygame), no engine change. Infra in `gui/main.py`: `self._floating_texts` list, `_spawn_flash(agent_idx, text, color, secs=1.5)` (mirrors `_flash_status`; auto-staggers stacked flashes on one token), and `_draw_floating_texts()` (drift-up + fade via `BLEND_RGBA_MULT`, since `set_alpha` is ignored on antialiased text) called each frame after `_draw_agents()`. Colors `FLASH_GOOD`/`FLASH_BAD`/`FLASH_CRIT` in `constants.py`.

**Fire sites (covered):** `_finish_attack` (single attacks), `_log_spell_results` (cast-time spell saves — the flash is hoisted above the `if spell and tgt_agent:` gate so it fires even when the spell-metadata lookup returns None), Flurry sub-hits, Cleave, Riposte, Sweeping, Topple, Stunning Strike, Battle Master save-maneuvers, Flurry knockdown riders. Verified live: weapon Hit/Miss and Fireball Saved/Failed both flash.

**NOT covered — persistent emanations / zones (e.g. Spirit Guardians, Cloudkill).** Their save+damage is applied deep in C++ (`applySpellEffect`, `combat_spells.cpp:2122`) when a creature starts its turn in the zone or enters it — NOT at cast time — and that path emits **only a text log line** (`"{name} took N from {spell} (made/failed save)"`). No structured (target_idx, saved) result reaches Python (`TurnStartResult` carries none), so the GUI has nothing to anchor a flash to — same limitation as **opportunity attacks** (also C++-resolved, text-only). **To fix later (needs a rebuild):** have `applySpellEffect` record `(target_idx, saved)` into a per-turn/per-move member vector, expose it via a binding (e.g. `last_zone_save_outcomes()`), and have the GUI read it after `begin_turn_flow` + movement and call `_spawn_flash`. Index-based, so it survives duplicate-named tokens. A GUI-side log-parse alternative was rejected as brittle (name→index ambiguity, wording-dependent).

</details>



<details>
<summary><b>Petrified reversal loses state across save/reload (2026-07-07)</b></summary>

Remove Curse / Greater Restoration now cure conditions (`cureCurses` / `greaterRestoration` in `combat_spells.cpp`, name-keyed in `executeSpell`). `curePetrified` reverses the Petrified condition — but `applyPetrified` **destroys** the creature's real speeds (→0) and every damage multiplier (→all 0.5×). It is restored from `petrifySnapshots_`, a **session-only** `unordered_map<int, PetrifySnapshot>` populated at petrify time (guarded against a double-apply clobbering a good snapshot).

**Limitation:** a save taken WHILE a creature is petrified loses the snapshot (it is not serialized). On reload, `curePetrified` falls back to normalising the flat 0.5× multipliers back to 1.0× (stripping any innate resistance/immunity/vulnerability the creature had) and **cannot recover the original speeds** (they stay 0). Rare edge case (petrify → save → reload → Greater Restoration). To fix properly: serialize the snapshot alongside `active_conditions` in `main.py`, or store pre-petrify state on a serialized Stats/condition field.

**Also not modelled:** Greater Restoration's RAW "any reduction to an ability score" — there is no ability-score-drain mechanic in the engine, so nothing to restore. Bestow Curse applies no "Cursed" condition yet, so Remove Curse finds nothing on a Bestow-Curse target.

</details>



<details>
<summary><b>Paladin Oath of Vengeance — deferred sub-clauses (2026-07-08)</b></summary>

Oath of Vengeance is implemented (Vow of Enmity L3, Relentless Avenger L7, Soul of Vengeance L15, Avenging Angel L20 + always-prepared oath spells). Three secondary clauses are intentionally deferred as out-of-scope-for-now:

- **Relentless Avenger (L7) — the optional half-Speed follow-move.** The impactful clause (a Vengeance paladin's OA hit reduces the mover's Speed to 0 for the turn) is implemented by reusing the Sentinel `mover_halted`/budget-zero path in `combat_movement.cpp`. The RAW "you can then move up to half your Speed as part of the same Reaction (no OA)" repositioning is **not** implemented — auto-driving a reacting creature's movement mid-OA is involved and low combat value.
- **Avenging Angel (L20) — "attacks against the Frightened creature have Advantage."** The Frightful Aura itself is implemented (enemy WIS save at turn start in the Aura of Protection → Frightened until damaged, modeled as a Turn-Undead-style tracked condition in `beginTurn`). The engine has no generic "attackers have Advantage vs a Frightened creature" mechanism (standard 2024 Frightened doesn't grant it), so this Avenging-Angel-specific rider is not applied.
- **Oath spells — utility-only entries omitted.** `Scrying` (Vengeance L17) is list-only per combat-sim scope; it is simply not added to the always-prepared list (`_PALADIN_OATH_SPELLS` in `main.py`). All combat-relevant oath spells already exist in `spells.json` and are auto-granted.

</details>



<details>
<summary><b>Paladin Oath of the Ancients — deferred sub-clauses (2026-07-08)</b></summary>

Oath of the Ancients implemented (Nature's Wrath L3, Aura of Warding L7, Undying Sentinel L15, Elder Champion L20 + oath spells). Implementing Nature's Wrath also made the previously-inert **Restrained** condition functional (Speed 0 in `canAgentMove`; attackers get Advantage / a Restrained creature's attacks get Disadvantage in `combat_attack.cpp`; Disadvantage on DEX saves in `rollSpellSave`; apply/clear wired into the condition dispatchers). Deferred:

- **Elder Champion (L20) — Swift Spells.** "Diminish Defiance" (enemies in the aura roll saves vs your spells/CD at Disadvantage, via `rollSpellSave`) and "Regeneration" (10 HP at each turn start, in `beginTurn`) are implemented. **Swift Spells** (cast an action-cast spell as a Bonus Action) is NOT — it touches the action-economy plumbing and is low combat value in the sim.
- **Aura of Warding — weapon-damage & some rider/splash sites.** The resistance to Necrotic/Psychic/Radiant is folded into the central `effectiveMagicDamageMult` helper, which covers all **spell / persistent-zone / DoT-tick** damage (where `bm` + the target index are in scope). It is **not** applied on the **weapon-damage path** (`rollDamage` has no `BattleMap`/target-index in scope — threading it through would ripple across every attack caller), nor at a few raw-multiplier rider/splash reads (delayed-blast, curse kickback). Weapon-borne Necrotic/Psychic/Radiant is rare, so this is an accepted edge case.
- **Oath spells — utility omitted.** Speak with Animals (L3), Commune with Nature / Tree Stride (L17) are list-only and not added to `_PALADIN_OATH_SPELLS`.

</details>



<details>
<summary><b>Paladin Oath of Glory — deferred sub-clauses (2026-07-08)</b></summary>

Oath of Glory implemented (Inspiring Smite L3, Aura of Alacrity L7, Glorious Defense L15, Living Legend L20 + oath spells). Deferred / simplified:

- **Peerless Athlete (L3)** — non-combat (Athletics/Acrobatics Advantage, jump distance). Not implemented.
- **Inspiring Smite (L3) — single recipient.** RAW lets you split the 2d8+level temp-HP pool among several creatures within 30 ft; `activateInspiringSmite` grants the whole pool to one chosen creature (temp HP doesn't stack anyway). Gated to once per turn (`inspiring_smite_used`), right after a Divine Smite.
- **Aura of Alacrity (L7) — turn-start membership model + NPC path.** The +10 ft Speed is applied when a creature starts its turn in a Glory L7+ paladin's aura (self always qualifies): seeded into the engine budget (`beginTurn`) and the GUI's own budget (`_reset_movement`). The RAW "enters the aura mid-move" and "lingers until end of next turn" nuances are simplified to per-turn membership. NPC-automated movement paths (`runNpcTurn`/`runFleeTurn` initMovement sites) don't add the bonus — GUI + engine budget only.
- **Glorious Defense (L15) — GUI protect-an-ally case.** The self-protection case (the paladin is the hit creature) flows through the standard OnHit defender reaction window → works in the GUI and auto/RL. The **protect-an-ally-within-10 ft** (bystander) case is auto/RL only (`maybeGloriousDefenseInline`); the GUI does not yet offer a bystander Glorious Defense (the OnHit suspend window is defender-keyed).
- **Living Legend (L20).** Save-Throw Reroll wired into the OnSaveFail reaction window (spell saves only — non-spell saves don't open that window). Unerring Strike (once/turn weapon miss→hit) **auto-fires on the first miss each turn** while active — the RAW "save it for a later attack" player choice is not modeled (it's strictly beneficial). Charismatic (Advantage on CHA checks) is non-combat, not modeled.

</details>



<details>
<summary><b>Epic Boon feats — deferred / partial scopes (2026-07-17)</b></summary>

Planned in `EPIC_BOONS_PLAN.md` (SRD 5.2 p.88, 7 boons). Locked scope decisions:

- **ASI to 30 — manual.** Every Epic Boon raises one score to a max of **30** (not 20). Consistent
  with the general-feat rule (`feat_system.md`: ASI is not auto-applied), boons implement only their
  special benefit; the "+1 to 30" is set via the ability steppers. The stepper cap is left unchanged
  (not raised to 30 automatically for boon-holders).
- **Boon of Fate (Improve Fate) — attacks + saves, self-primed on your turn; NPC auto deferred.**
  RAW triggers on **any D20 Test by you or a creature within 60 ft** (attack rolls, saving throws,
  *and ability checks*), reactively after the roll. Implemented (2026-07-21) as `applyBoonOfFate` —
  a **Boon of Fate (2d4)** GUI button on the holder's turn that primes ±2d4 on the **next** D20 Test
  via the shared `pending_roll_bonus_` primitive (same path as Bend Luck / Bardic Inspiration /
  Cutting Words), 1/short-or-long rest (also refreshed at initiative, `boon_of_fate_used`). Scope
  gaps: (a) **ability checks not covered** (barely modeled in the sim); (b) **prime-before-roll, own
  turn only** — like Bend Luck, the nudge is committed to the *next* d20, so it naturally covers the
  holder's own attack rolls; boosting one's own **saving throw** works only if the holder primed it
  on their turn and their next d20 is that save (saves fire on the enemy's turn, so there is no
  reactive post-save prompt); the "any creature within 60 ft" targeting is not surfaced (you effectively
  aid/hinder whoever rolls the next d20 — normally yourself). (c) **NPC auto-use deferred** — the
  `runNpcTurn` driver never spends Boon of Fate (no heuristic for when the ±2d4 is worth the 1/rest use).
- **Boon of Dimensional Travel (Blink Steps) — PC only (NPC reposition deferred).** The ≤30-ft
  post-action teleport is fully wired for PCs (the **✦ Blink Steps** button + a destination pick that
  reuses `teleport_agent` / `is_valid_teleport_destination` / `has_line_of_sight`), armed after the
  Attack/Magic action via `blink_steps_available`. **Automated NPC boon-holders never blink** — the
  C++ `runNpcTurn` driver does not arm or use Blink Steps (no "pick a safe reposition" heuristic yet).
  Also: the "you can see" clause is modeled as a wall line-of-sight check only (it ignores Invisible/
  Blinded and other perception nuances), and Blink triggers off the Attack/Magic action generically —
  it is not re-gated per Action-Surge extra action.
- **Boon of the Night Spirit (Shadowy Form) — primary damage path only.** The light-gated Resistance
  (all but Psychic/Radiant while the defender is in Dim/Dark) is folded into `effectivePhysicalDamageMult`
  / `effectiveMagicDamageMult` and reaches every site that passes `bm`/`target_idx`: the interactive
  weapon attack path (`resolveAttack` → `rollDamage`, all 3 callers) plus all spell/AoE/item damage.
  **Secondary weapon damage-reroll paths do not pass `bm`/`target_idx`** — a boon-holder hit by
  **Savage Attacker**, **Piercer**, **Brutal Strike**, or a **GWM Hew** reroll has that reroll's damage
  computed at full multiplier (and "keep the higher" can then bypass the Resistance). *Merge with
  Shadows* is also **PC-only** — automated NPCs never activate it (no `runNpcTurn` arming).

</details>
