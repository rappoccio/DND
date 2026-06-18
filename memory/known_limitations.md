---
name: known-limitations
description: Comprehensive known limitations and deferred features across all character classes
metadata: 
  type: project
---

# Known Limitations

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

### Weapon on-hit conditions survive save/load + on-hit grapple is logged — FIXED ✅ (2026-06-17, confirmed in live play)
Two coupled fixes for on-hit weapon riders (surfaced by a Vampire Spawn Claw with a `Grappled`/`escape_dc:14`
rider in `DND2024_MonsterStats.json` that "wasn't working" after an encounter reload):
- **Root cause:** `helpers._weapon_to_dict` never serialized `Weapon.conditions`, so the encounter
  save path (`main.py` ~7039, which round-trips every agent's weapons through `_weapon_to_dict`) silently
  **dropped all on-hit riders** (Grappled, `reduceHPMax`, save-based conditions) on save→reload. The data
  and the C++ routing (`combat_attack.cpp` ~2927 → `resolveGrapple` → `applyGrappled`) were always correct;
  the bug was purely the lossy serializer. **Fix:** `_weapon_to_dict` now emits the full `conditions` list
  (name, duration, push_ft, save_repeat_turns, contested, escape_dc, requires_save, save_ability,
  save_dc_ability, on_damage); `_dict_to_weapon` now also parses `requires_save`/`on_damage` (previously
  ignored) so every condition type round-trips. **Caveat:** saves written *before* the fix already lack the
  data — re-place the creature fresh from the bestiary, then re-save.
- **On-hit grapple now logs the contest + outcome.** The on-hit `Grappled` branch previously discarded the
  result (`(void)resolveGrapple(...)`) so the combat log showed nothing. Now it logs at the rider call site:
  contested → "X attempts to grapple Y (Athletics A vs D) — GRAPPLED (escape DC N)/target resists";
  automatic (`contested=false`) → "X grapples Y on the hit (escape DC N)". Logged at the call site (not
  inside `resolveGrapple`) so the standalone Grapple action + Punch-and-Grab paths (which log via Python)
  don't double-log.

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

### Uncanny Dodge + Guided Strike folded into the reaction framework (2026-06-08)
**Status:** DONE — the last two ad-hoc interrupts now route through `chooseReaction`/the window helpers.

- **Uncanny Dodge** (Rogue L5+) is now an **OnHit defender option** (alongside Shield) in
  `defenderOnHitOptions`: auto/RL via `maybeDefenderOnHitInline`, GUI via the `advanceAttack` suspend
  window (`applyAttackReaction` → `applyUncannyDodge`). The inline auto-halving block was removed from
  `applyAttackResult`.
- **Guided Strike** (War Cleric L3+) is now an **OnMiss option**: auto/RL via `maybeGuidedStrikeInline`
  (runs before `maybeRiposteInline`, since a guided hit forecloses the defender's riposte). The GUI keeps
  its existing `guided_strike_available`-flag offer (parallel to Riposte), and `applyAttackResult` sets
  that flag via the shared `canGuidedStrike` gate. `applyGuidedStrike` is unchanged.

**Deliberate behavior change (the cost of consistency):** Uncanny Dodge is now **decider-gated like
every other reaction** — with **no decider installed it is skipped** (it used to auto-apply). Concretely:
in the GUI it fires on the player's main attack (which goes through `begin_attack`/the OnHit window) but
**NOT** on incidental sub-attacks that use the atomic `execute_action` path with no decider —
**Opportunity Attacks, Cleave, and extra/multiattack swings**. This matches how Shield and Riposte
already behave on those sub-attacks (the same "reaction-during-reaction on an atomic sub-attack" deferral
as Cleave). Tests cover all three UD paths (decider auto, no-decider skip, GUI suspend) in
`test_rogue_l1_18.py`; the auto Guided-Strike path is in `test_cleric.py`.

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

### Additional Maneuvers — IMPLEMENTED 2026-06-14 (test_fighter.py)
The 2024 maneuver set is now wired across the three reuse buckets (on-hit save riders, bonus-action, reaction).
All save riders share `applyManeuverEffect`'s dispatch and the save DC `8 + PB + max(STR,DEX) mod`.

- **On-hit save/effect riders** (`applyManeuverEffect` dispatch + `_offer_maneuver` menu):
  - **Goading Attack** (type 3): WIS save or `goaded_by` → Disadvantage attacking anyone but you,
    until the start of your next turn (checked in `determineAdvantage`, cleared in `beginTurn`).
  - **Distracting Strike** (type 4): no save; `distracted_by` on the target → the next attack vs it
    by another creature has Advantage (mirrors Vex; consumed in `applyAttackResult`).
  - **Disarming Attack** (type 5): STR save or `disarmed` → the target's weapon attacks resolve as
    improvised Unarmed Strikes (substituted in `determineAdvantage`) until the start of your next turn.
    *Model note:* no ground-item system — "drops the weapon" is modeled as fighting unarmed for a round.
  - **Sweeping Attack** (`applySweepingAttack`, dedicated fn — needs the original roll + 2nd target):
    if the original attack roll would hit a 2nd creature within 5 ft, it takes superiority-die damage
    of the attack's type. GUI 2nd-target picker mirrors Cleave (`pending_sweep`/`_resolve_sweep`).
- **Bonus-action maneuvers** (one "Maneuver (Bonus Action)" GUI button → context menu):
  - **Rally** (`applyRally`): grant a creature within 30 ft temp HP = die + CHA mod (min 1).
  - **Feinting Attack** (`applyFeintingAttack`): `feint_target_idx` → Advantage on your next attack vs
    it this turn + the die added to that hit's damage (both consumed in `applyAttackResult`).
  - **Quick Toss** (`prepareQuickToss`): arms `quick_toss_die_pending`; the next thrown-weapon attack
    this turn adds the die to damage. GUI then runs the thrown attack via `_start_extra_attack`.
- **Reaction maneuver** (OnHit defender window, live eligibility like Uncanny Dodge — no flag):
  - **Parry** (`canParry`/`applyParry`): on a melee hit that dealt damage, spend reaction + die to
    reduce the damage by die + DEX mod. Offered in `defenderOnHitOptions`; handled in both
    `maybeDefenderOnHitInline` (auto/RL) and `applyAttackReaction` (GUI resume).

**Save DC fixed** to `8 + PB + max(STR,DEX) mod` via the shared `dndMod` (floor) helper, which was
promoted from a file-local static in `combat_core.cpp` to `combat_internal.hpp` for all TUs.

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

### Indomitable (L9) — IMPLEMENTED 2026-06-04
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
- **Divine Smite** (IMPLEMENTED): Bonus-action radiant smite on a melee weapon hit — spends the hit +
  bonus action + a spell slot, `(slot+1)d8` Radiant (+1d8 vs Undead/Fiend), once/turn, ranged excluded,
  interlocked with the one-leveled-spell-per-turn rule. `applyDivineSmiteEffect` / `apply_divine_smite_effect`,
  `divine_smite_used` reset in `turn()`. Tests: `test_paladin.py` (`test_divine_smite_*`).

### Auras (Aura of Protection L6, Aura of Courage L10) — IMPLEMENTED ✅ (2026-06-14, built + 72 suites green, confirmed in live play)
Team-scoped emanations now that factions exist. A Paladin's aura reaches **itself and same-team allies**
(`areAllies`) within **10 ft (30 ft at L18)**; it is suppressed while the Paladin is at 0 HP /
unconscious / incapacitated. Engine in `combat_core.cpp`:
- **`bestPaladinAura(bm, idx, min_level)`** — strongest CHA-mod (min 1) bonus from any qualifying Paladin
  of level ≥ min_level reaching `idx` (no stacking — take the max); `footprintDistance` × 5 ≤ radius.
- **Aura of Protection** = `auraSaveBonus` (= `bestPaladinAura(…, 6)`), folded into the new single
  **`saveModFor(bm, idx, ability)`** helper which **replaced the ~9 duplicated per-site save-mod lambdas**
  (rollSpellSave, the executeSpell condition-rider + zone saves, begin-turn re-saves, weapon-condition
  riders, Cunning Strike, Battle Master maneuvers, Branches of the Tree). So the +CHA applies to **every**
  saving throw, and the OnSaveFail reroll (`reevaluateSave`) carries it via the stored `save_mod`.
- **Aura of Courage** = `hasAuraOfCourage` (= `bestPaladinAura(…, 10) > 0`): immunity to **Frightened**.
  Gated at the central `applyFrightened` chokepoint (covers spell/condition fear) **and** the inline
  Battle Master Menacing-Attack site.
- **No flag/init needed** — read live from `character_class==Paladin && char_level` + CHA + faction, so it
  works automatically once a Paladin has a team set (GUI TeamPicker) and is L6+/L10+.
- **GUI:** a translucent **gold aura ring** is drawn under each L6+ Paladin (`_draw_paladin_auras`, radius
  10 ft / 30 ft at L18, suppressed while the Paladin is down) so the reach is visible during play.
- **Save log now shows the aura (fixed 2026-06-14):** `SpellTargetResult.save_mod` was added + populated
  from `ss.save_mod` (was missing), and the combat-log line (`main.py` Save branch) now prints
  `tr.save_mod` instead of **recomputing the modifier in Python without the aura** — that GUI recompute was
  why the first smoke test showed an un-buffed save (the engine *was* applying it; only the display lied).
  The line now also appends **" (incl. +N Aura of Protection)"** via `aura_save_bonus(bm, tr.target_idx)`
  so the contribution is explicit. **Note:** allies only show the bonus if on the **same team** as the
  Paladin (TeamPicker); an un-teamed (all-neutral) party means only the Paladin's own save shows it.
- Bindings: `aura_save_bonus`, `has_aura_of_courage`, `save_mod_for`, `SpellTargetResult.save_mod`, plus
  `apply_frightened` (test hook).
  Tests: `test_paladin_auras.py` (12: range/L18/enemy-excluded/self/min-1/level-gate/suppressed-when-down/
  strongest-wins/save-mod-fold/courage-levels/courage-blocks-frightened).

**v1 simplifications / deferred:**
- **Other auras not modeled** — Oath-specific auras (Devotion *Aura of Devotion* charm immunity, Ancients
  *Aura of Warding* spell resistance, Vengeance, etc.) and **Aura of Courage's "ends Frightened on those
  already affected"** clause (it only *blocks* new Frightened; a creature frightened before entering the
  aura keeps it until its own re-save). The radius/team machinery (`bestPaladinAura`) is reusable for them.
- **Static/no-LoS** — the aura is pure range+team (no line-of-effect/sight check, matching the other
  range-gated features); it updates continuously as agents move (re-evaluated at each save).
- **Reusable for other team auras** — `bestPaladinAura` + `saveModFor` are the foundation the deferred
  **Crusader's Mantle** (+1d4 Radiant ally aura) and **Sculpt/Evoker** ally-exclusion can build on.

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

## Barbarian subclass L10 "Presence" abilities — IMPLEMENTED ✅ (2026-06-17, built + test_barbarian_l9_17.py green)
Both are Bonus-Action emanations modeled on the Spirit Guardians emanation + Paladin-aura faction
logic (`areAllies`, `saveModFor`). Engine in `combat_resources.cpp`; bound in `rpg_bindings.cpp`;
GUI Bonus-Action buttons in `main.py` (gated on subclass + L10, label shows uses, hidden once
`bonus_used`). Distance uses the **Euclidean** emanation metric `sqrt(dx²+dy²)*5` to match Spirit
Guardians (`resolveAoeTargets`, `Spell::Sphere`) — NOT Chebyshev/Manhattan.
- **Intimidating Presence (Berserker L10):** `useIntimidatingPresence` — 30-ft emanation, enemies
  only (`areAllies` spares allies), each rolls a WIS save (DC 8 + STR mod + PB); on fail →
  Frightened until the end of the Barbarian's next turn via `addAgentCondition("Frightened",
  turns_remaining=2)` (which routes through `applyFrightened`, so Aura of Courage immunity is
  honored automatically — do NOT also call applyFrightened). Resource: PB uses/long rest, falls
  back to spending one Rage use.
- **Zealous Presence (Zealot L10):** `useZealousPresence` — 60-ft emanation, up to 10 allies
  (incl. self), grants Advantage on attack rolls **and** saving throws. New `Conditions.zealous_blessing`
  bool consumed in `determineAdvantage` (attacks) and `rollSpellSave` (spell saves). Resource:
  1 use/long rest or one Rage use.
- **Granter-relative expiry (the right pattern):** the buff lasts "until the start of the GRANTING
  Zealot's next turn", so it is tagged with `Conditions.zealous_blessing_by = caster_idx` and cleared
  in `CombatEngine::beginTurn` when that Zealot's turn begins (mirrors `goaded_by`/`distracted_by`).
  It is NOT reset in the buffed creature's own `Agent::turn()`.
- **Action-economy gotcha (fixed):** `spendBonusAction` re-reads + writes back stats, so it MUST run
  AFTER the function's final `setAgentStats(idx, stats)` or the bonus action gets refunded. Both
  functions persist `stats` first, then call `spendBonusAction` last.
- **Core passives — done:** Fast Movement (L5, `speed_walk += 10`), Extra Attack (L5), Brutal Strike
  (L9/L17 dice) are all seeded in `Stats` level-up (`combat.cpp:43-59`).
- **Relentless Rage (L11) + Primal Champion (L20) — IMPLEMENTED ✅ (2026-06-17, built + test_barbarian_l9_17.py green):**
  - **Primal Champion (L20):** +4 STR & +4 CON, capped at 25, applied in `Stats::initializeClassResources`
    (`combat.cpp:61-67`). Idempotent via a bound+saved `bool primal_champion_applied` (`agent.hpp`),
    gated `if (level >= 20 && !primal_champion_applied)`. Safe across reloads (`agent_loader.dict_to_stats`
    sets the flag *before* it calls `initialize_class_resources`) and dialog reopens (`_on_stats_ok` sources
    `stats` from the live agent, preserving the flag). Old saves migrate cleanly (flag absent → applied once).
  - **Relentless Rage (L11):** while raging, damage that would drop you to 0 HP triggers a CON save
    (`saveModFor(bm, idx, SaveCon)`, so Aura of Protection applies) vs a `relentless_rage_dc` (10, **+5 per
    use in the same Rage**, reset to 10 in `endRage`); success → `hp_cur = 1`. Hooked in `damageAgent`
    (`combat_attack.cpp:401-422`), **before** the concentration-drop block (early-returns so a saved
    Barbarian keeps concentration). `relentless_rage_dc` is a bound+saved `int` on `Stats`.
  - **⚠️ `damageAgent` is now NON-static** (`combat.hpp:673`; binding changed `def_static`→`def`,
    `rpg_bindings.cpp:1720`) so the Relentless Rage hook can use the seeded `roll`, `log_`, `saveModFor`,
    and `agentName` instance members. All C++ callers are non-static members and both Python callers use
    `engine.damage_agent(...)`, so the change is transparent — but future static-context callers must note this.
- **Core Passives: Feral Instinct (L7), Instinctive Pounce (L7), Indomitable Might (L18) — IMPLEMENTED**
  (awaiting build/test by Opus 2026-06-17):
  - **Feral Instinct (L7):** Initiative rolls at Advantage. `combat_turn.cpp:rollInitiative` checks
    `char_level >= 7 && character_class == Barbarian` → `e.d20 = std::max(roll(20), roll(20))`.
  - **Instinctive Pounce (L7):** On Rage activation, grant half-speed movement THIS turn.
    `combat_resources.cpp:activateRage` adds `walkRemaining_[idx] += stats.speed_walk / 2` for L7+.
  - **Indomitable Might (L18):** STR saving throw total can't be lower than STR score. New helper
    `CombatEngine::applyIndomitableMight(bm, saver_idx, ab, total)` declared in `combat.hpp:1049`,
    defined in `combat_core.cpp:265`. Wired into all STR-save sites: `combat_turn.cpp` (lines 384, 504),
    `combat_attack.cpp` (lines 468, 2970), `combat_riders.cpp` (lines 507, 568, 645), `combat_spells.cpp`
    (lines 322, 1128). Tests: `test_barbarian_l9_17.py` (L7 chassis, Pounce deterministic movement delta,
    L18 chassis + STR verification; Feral Instinct is smoke-tested via initiative presence).
- **Deferred (still missing, verified 2026-06-17):** Berserker L14 Retaliation, Zealot L10 (other clauses)
  / L14 Rage of the Gods, and the rest of the Barbarian subclass L14 tier.
- **Persistent Rage (L15) — INERT BY DESIGN, no code (verified against the engine 2026-06-17):** Persistent
  Rage's only mechanical effect is to *remove* Rage's early-end triggers (Rage normally ends if you don't
  attack a hostile creature or take damage on your turn, or after 10 minutes). In this engine Rage has **no
  modeled early-end at all**: `Resource "Rage".duration_remaining` is set to full on `activateRage`/`extendRage`
  and zeroed only by `endRage` (manual), and is **never decremented per-turn anywhere** (`grep duration_remaining`
  = activate/extend/end sites only; no tick in `combat_turn.cpp`). There is no "did you attack / take damage this
  turn" tracking. So the conditions Persistent Rage suppresses do not exist, and the feature is a guaranteed no-op
  in the current model. Writing code for it would be dead code — **documented as inert rather than implemented**
  (per fix-root-cause / combat-sim-scope: don't add a per-turn early-end mechanic just to then suppress it). If a
  real Rage early-end is ever modeled, gate it on `char_level < 15 || subclass-equivalent` to honor this feature.

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

## Summoning — IMPLEMENTED ✅ (2026-06-09, built + green)
Spells that manifest a controllable creature, dismissed when the summoner loses concentration.
**Done:** `Summon Dragon` end-to-end — `bm.spawn_agent` (non-destructive append, rejects walls +
live footprints); `PlacedAgent.{summoner_idx, removed_from_play, summon_spell}`; `dropConcentration`
tombstones the caster's summons (reported in `dismissed_summons`) and `setAgentRemovedFromPlay` also
banishes them off-map to (-1,-1) so their cell frees up (index preserved, never erased); manual
control sharing the summoner's initiative; GUI placement preview (green/red, rule in
`helpers.summon_cell_placeable` / `can_place_agent`); render gate skips dismissed summons;
`_save_agents` skips summoned/tombstoned agents (transient — vanish on reload). Tests:
`test_summoning.py`. Root-cause fix: `concentrationSave` now routes through `dropConcentration`.

**Statblock stand-in:** the RAW 2024 summon "spirit" stat blocks (Draconic/Bestial/Fey/Undead…) are
NOT in `DND2024_MonsterStats.json`, so `Summon Dragon → Spirit Dragon Wyrmling` via
`SUMMON_SPELL_TO_MONSTER` (wrong AC/HP/damage, doesn't scale with slot).

**Deferred:**
- Author the RAW scaling spirit stat blocks (replaces the Spirit-Dragon-Wyrmling stand-in).
- Rest of the 2024 Summon X line (only Summon Dragon is in `spells.json`) — each is just a new
  `SUMMON_SPELL_TO_MONSTER` entry once the spell + stat block exist.
- Conjure Animals / Woodland Beings (multi-creature from one spell — needs a multi-spawn GUI flow);
  Animate Dead (Skeleton/Zombie are in the JSON, but it's non-concentration → permanent control);
  Find Familiar / Find Steed (overlaps the parked Pact of the Chain item).
- Summon auto-control AI (RAW "obey commands; else Dodge") — manual for now.
- Not auto-tested (pygame): `_resolve_summon` placement UX, initiative insertion, the `_save_agents`
  skip (verified by inspection).

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

### L3: Portent (Diviner) — IMPLEMENTED ✅
- `CombatEngine::usePortentDie` (`combat_resources.cpp`): a Diviner Wizard banks a deque of d20 rolls
  (`Stats::portent_dice`, regenerated on long rest via `regenerate_portent_dice`); spending one sets
  `pending_portent_die` so the next `CombatEngine::roll()` returns it (the d20-roll hook this entry once
  said was missing now exists). One use per round (`agent_portent_round_used_`). Bindings
  `use_portent_die` / `regenerate_portent_dice` / `portent_dice` (`rpg_bindings.cpp:2604`).

### L6: Sculpt Spells (Evoker) — IMPLEMENTED ✅
- The faction system this entry waited on now exists. An Evoker's **safe targets**
  (`CombatEngine::safeTargets_`, `caster_idx → excluded indices`; `setSafeTargets`/`getSafeTargets`,
  bindings `set_safe_targets`) are **fully excluded** from that caster's AoE/zone effects — no save, no
  damage, no conditions — checked at the area-resolve sites in `combat_spells.cpp` (~430, 535, 1751).
  Allies are selected manually in the GUI for now (see `[[evoker-safe-targets]]`); the same exclusion
  path backs Careful Spell (`careful_targets`) and faction-based auto-sparing.

### L6: Phantasmal Creatures (Illusionist) [DEFER]
Requires creature summoning system.

---

## Cleric

### Not modeled — Divine Order (L1) 🚫
- **Protector** (Martial weapon + Heavy armor training) grants nothing the engine models
- **Thaumaturge** (extra cantrip + skill checks) is out-of-combat flavor

### Deferred — Trickery Domain
- **Invoke Duplicity** and related features need illusory-entity concept

### Turn Undead (L2) + Sear Undead (L5) — IMPLEMENTED ✅
- **Turn Undead** is a Channel Divinity Magic action (`CombatEngine::useTurnUndead`,
  `combat_resources.cpp`). Gated on Cleric **L2+** with a `Channel Divinity` use available; spends one
  use. Each `is_undead` agent within **30 ft** (Euclidean cell distance, matching Sphere targeting) makes
  a **WIS save** vs `spellSaveDcFromAbility(caster, SaveWis)`; on a fail it gains **Frightened +
  Incapacitated** for 1 minute (`turns_remaining = 10`) with `on_damage = OnDamage_t::End` (any damage
  ends it). `caster_idx` is stored on the `ActiveAgentCondition` as the fear source so the Frightened
  "move as far away as possible" movement rule keys off the cleric.
- **Sear Undead (L5+)** rolls `max(1, WIS mod)` **d8 once**, dealing that Radiant total to *each* undead
  that fails — applied **before** the conditions so the on-damage end-rule doesn't immediately cancel the
  Frightened/Incapacitated it's about to add (matches "this damage doesn't end the turn effect").
- Returns `TurnUndeadResult {valid, save_dc, sear_damage, turned[], resisted[]}`. Bindings
  `use_turn_undead` / `TurnUndeadResult` (`rpg_bindings.cpp`). GUI: `btn_cbt_turn_undead` button calls the
  engine, logs `Turn Undead (DC X): N turned[, M Radiant each]`, and consumes the action (`main.py`).
  Tests: `test_cleric.py` (`test_turn_undead_frightens_sears_and_filters`, `test_turn_undead_ends_on_damage`).
- *Deferred fidelity gaps (v1 simplifications):*
  - Targets **all** undead in range — "Each Undead **of your choice**" isn't modeled, so an allied/friendly
    undead (e.g. a necromancer's summons) can't be spared. Would mirror Spirit Guardians' faction-aware
    `zoneSparesTarget`, or a GUI target picker.
  - Undead with **Frightened immunity** aren't spared (no creature condition-immunity system).
  - "Ends early if the **caster** is Incapacitated or dies" isn't cascaded (only the takes-damage
    end-trigger fires).

### Light Domain — Warding Flare + Corona of Light — IMPLEMENTED ✅ (2026-06-15, built + 72 suites green)
- **Warding Flare (L3)** — a consumer of the **OnD20Seen** reaction window (`combat_attack.cpp`),
  modeled exactly like Silvery Barbs but as Disadvantage = reroll the d20 and take the lower. When a
  creature within **30 ft** that the Cleric can see makes an attack roll **that hits**, the Cleric may
  spend its reaction + 1 **Warding Flare** use to impose Disadvantage (lowering-only, can flip hit→miss).
  Gate `canWardingFlare` reuses `d20ReactorBase` (60 ft + LoS + reaction-free) then tightens to 30 ft;
  apply `applyWardingFlareToAttack`; wired into `d20SeenReactors`/`d20SeenOptions`/`applyD20SeenReaction`/
  `maybeD20SeenInline`. Resource = `max(1, WIS mod)` uses / **Long Rest**, seeded in `initializeClassResources`
  (Cleric `LightDomain && level>=3`). GUI: appears automatically in the generic OnD20Seen reaction menu;
  the log line mentions it. Bindings `can_warding_flare` / `apply_warding_flare_to_attack`. Tests:
  `test_d20seen.py` (`test_warding_flare_disadvantage_can_miss`, `test_warding_flare_gate`).
  - *v1 simplifications:* offered **regardless of faction** (decider/human Skips for enemies — matches the
    other OnD20Seen reactions; no `areAllies` gate); fires **on a hit only** (the window's lowering-only
    contract — RAW imposes Disadvantage on any attack roll, but Disadvantage only matters when it could flip
    a hit to a miss); the 30 ft gate is exercised in `test_warding_flare_gate` (40-ft cleric not offered).
- **Corona of Light (L17)** — a Magic action (`activateCoronaOfLight`, `combat_resources.cpp`) that sets a
  10-round duration (`Stats::corona_of_light_turns`, ticked down in `beginTurn`, mirroring Sacred Weapon).
  While active, **enemies within 60 ft** (`!areAllies` + `footprintDistance`≤60) have **Disadvantage on
  saves vs the caster's Fire/Radiant spells** — applied in `rollSpellSave` (`combat_spells.cpp`) right after
  the Heightened/Eldritch-Strike blocks (sets `target_dis`). GUI: a "Corona of Light (Action)" button gated
  on Cleric/LightDomain/L17/action-available (`_use_corona_of_light`, `btn_cbt_corona`). Bindings
  `activate_corona_of_light` / `Stats.corona_of_light_turns`. Tests: `test_cleric.py`
  (`test_corona_activation_and_duration`, `test_corona_disadvantage_on_fire_radiant_saves` [statistical
  off-vs-on save rate + Force-spell control], `test_corona_spares_allies`).
  - *v1 simplifications:* the actual **bright-light emission** into the lighting/vision system is NOT wired
    (only the combat-relevant save-Disadvantage); the **>60-ft range gate is untested** (the 12×12 test map
    tops out at ~55 ft, same as the Counterspell/d20-window range gaps).
- **Radiance of the Dawn** ally-exclusion: **DONE 2026-06-15** — spares the caster's allies (teamed caster).
  The engine logic was already correct (`combat_spells.cpp:527`, gated on `selective_targeting` + non-neutral
  caster); the GUI just never carried the flag. Fixed: classfeatures.json Radiance entry now has
  `"selective_targeting": true`, and `main.py`'s `_dict_to_spell`/`_spell_to_dict` now read/write the flag
  (loader+data only, no rebuild). Still gated on `caster_faction != 0` — an all-neutral (default) caster
  keeps the legacy affect-everyone behavior by design.

### Deferred — War Domain spells
- **Crusader's Mantle**: needs ally-buff aura for +1d4 Radiant
- **Steel Wind Strike**: needs multi-target teleport/attack
- **War God's Blessing**: underlying spells (Shield of Faith, Spiritual Weapon) are hollow

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

### Phase 3b — Eldritch Invocations (mostly DONE — see the Eldritch Invocations section below)
- Devil's Sight, Eldritch Spear range, and the **Pact of the Blade family** (Pact of the Blade /
  Thirsting Blade / Eldritch Smite / Lifedrinker) are implemented (2026-06-08).
- Still deferred: Devouring Blade (L12 3rd attack), Pact of the Chain (needs summons), Pact of the
  Tome (needs char-building), Gift of the Protectors (needs Death Ward), Lessons of the First Ones
  (needs feats). See the "Warlock Eldritch Invocations" section for details.

### Not modeled (combat simulator only) 🚫
- Telepathy, familiars (Pact of the Chain blocked on a summon system), utility features

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
- **Nick** — action-economy benefit (IMPLEMENTED 2026-06-11): the single per-turn off-hand attack
  relocates into the Attack action (`offhand_attack_used` flag, reset in `turn()`), freeing the bonus
  action; Dual Wielder then adds a 2nd bonus-action off-hand attack (3-attack turn). See the dual-wield
  rework in `feat_system` memory.

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
- **Additional maneuvers** — IMPLEMENTED 2026-06-14 (Goading/Distracting/Disarming/Sweeping/Rally/
  Feinting/Quick Toss/Parry; see the "Additional Maneuvers" section above). Remaining deferrals
  (Lunging, Commander's Strike, Maneuvering, Bait and Switch, Evasive Footwork) need new infra;
  skill maneuvers (Ambush, Commanding Presence, Tactical Assessment) are out of scope.

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

### Countercharm (L7) — IMPLEMENTED 2026-06-04
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
- **Valor L3/L6/L14 — IMPLEMENTED 2026-06-17** (built + 73 suites green, `test_bard.py`):
  - **L3 Combat Inspiration** — a held Bardic die can be spent two new ways. *Damage mode:*
    `useBardicDieForDamage` rolls the die into a new additive `pending_damage_bonus_`
    (`consumePendingDamageBonus()`, mirrors `pending_roll_bonus_`), consumed at the next weapon
    damage roll (`resolveAttack`, shows as a `"combat inspiration"` line in `damage_breakdown`).
    *AC mode:* an OnHit defender reaction mirroring Defensive Duelist — `canCombatInspirationAC` /
    `applyCombatInspirationAC`, offered in `defenderOnHitOptions` + dispatched in
    `maybeDefenderOnHitInline` (rolls the die, flips `r.hit=false` if it covers the margin; the die +
    reaction are spent either way). **Gating is self-contained** (deliberate simplification): the
    engine fns only require the actor to hold a Bardic die — NO cross-creature "which bard granted
    it / is that bard Valor L3+" lookup; the GUI surfaces the buttons for Valor parties only.
  - **L6 Extra Attack** (`num_attacks = 2`) in the `case Bard:` chassis.
  - **L14 Battle Magic** — casting a Bard spell via the Magic action sets
    `Conditions.battle_magic_available` (gated on `result.valid` + Valor L14+ in `executeSpell`),
    reset in `turn()`; the GUI offers one bonus-action weapon attack via the generic
    `_start_extra_attack` flow. **Martial Training (L3) = documented no-op** (weapon proficiency is
    per-weapon `Weapon::proficient`, not class-gated; no armor-proficiency subsystem to hook).
  - Bindings: `use_bardic_die_for_damage`, `can_combat_inspiration_ac`, `apply_combat_inspiration_ac`,
    plus `Conditions.battle_magic_available`. **Also fixed two pre-existing Glamour gaps surfaced by
    these tests:** `Stats::majestic_presence_turns` was never bound (added), and `dropConcentration`
    cleared `mantle_majesty_turns` but NOT `majestic_presence_turns` — Unbreakable Majesty's window
    now ends on concentration drop (step 4a', mirrors Mantle of Majesty). The prior session's
    Unbreakable-Majesty tests had never actually run green; they do now.
  - **TEST NOTE:** `AttackResult` is a read-only output struct — tests build real ones via
    `execute_action` + a finder loop (see `_find_attack` in `test_bard.py`), never by construction.
    And add ALL agents before `set_agent_spells` (`add_agent_to_battle` → `apply_agent_configs` wipes
    the directly-set spell list — the [[agent_dual_list_gotcha]]).
- **Glamour L3** — Mantle of Inspiration: `bard_mantle_of_inspiration(bm, bard_idx, targets)`
  (`combat_riders.cpp`, bound as `apply_mantle_of_inspiration`). Bonus Action, expends one Bardic
  Inspiration use, rolls the die ONCE; each chosen recipient gains temp HP = **2× the roll** via the
  shared `grantTempHp` (max() semantics). Engine caps the target list to the bard's CHA mod (min 1)
  and skips the bard itself (2024 "other creatures"); the GUI validates the 60 ft range per click.
  GUI: "Mantle of Inspiration (Bonus Action)" button (Glamour L3+ with a BI use, drawn under Grant
  Inspiration) → multi-click recipient picker (`_start_mantle`/`_mantle_add_target`/`_finalize_mantle`,
  Enter confirms / Esc cancels, mirrors the Chromatic Orb leap-chain UX with a numbered ring overlay
  `_draw_mantle_overlay`). Tests in `test_bard.py` (double-die temp HP, CHA-mod cap + self-skip,
  Glamour/L3/use gating). **DEFERRED rider:** the 2024 clause letting each recipient use its Reaction
  to move up to its Speed without provoking OAs is NOT modeled (needs a new reaction window + a free
  no-OA move for arbitrary creatures — see Architecture / Infrastructure).
- **Glamour L6** — Mantle of Majesty (DONE): once/long-rest resource `"Mantle of Majesty"` (seeded in
  `case Bard:` for Glamour L6+; long-rest regen), also restorable by spending a **level 3+** slot via
  `bard_restore_mantle_of_majesty_from_slot(bm, idx, slot_level)` (no GUI button yet — see deferred).
  `activate_mantle_of_majesty(bm, idx)` (combat_resources.cpp) spends the use, sets a 10-round window
  `Stats.mantle_majesty_turns` and starts **Concentration on the literal name `"Mantle of Majesty"`**
  (replacing any prior concentration). The window ticks down in `beginTurn` (combat_turn.cpp) and is
  cleared by `dropConcentration` (a later concentration spell / damage-broken save ends it). During the
  window the bard re-casts **Command** as a Bonus Action with **no slot** via `SpellAction.free_cast`
  (executeSpell skips the player slot decrement). **Command is fully modeled** (was inert): a failed WIS
  save applies the chosen word via `applyCommandEffect` (combat_conditions.cpp), `SpellAction.command_word`
  0=Drop/1=Flee/2=Grovel/3=Halt/4=Approach — Drop=drop-weapons+Disarmed (Disarming-Strike path),
  Flee/Approach=1-turn movement restriction toward/away from the bard (`CommandFlee`/`CommandApproach`
  checked in `canMove`, keyed to the bard so they expire at its next turn), Grovel=Prone, Halt=Incapacitated
  for one turn. **Auto-fail rider DONE:** a creature Charmed by THIS bard (`Conditions.charmed_by`, now set
  at every Charmed-application site and cleared on expiry) auto-fails its save vs the bard's Command while
  the window is active (rollSpellSave). Command is always-prepared for Glamour L6 (`_BARD_SUBCLASS_SPELLS`).
  GUI: "Mantle of Majesty (Bonus Action)" button (`_start_mantle_majesty`) → word picker (reuses
  ElementPickerDialog, `COMMAND_WORD_OPTIONS`) → single-target free Command cast. Tests in `test_bard.py`
  (seed gating, activation/window/concentration, free-cast-skips-slot, slot-restore L3+ gating, auto-fail,
  per-word effects, drop-concentration ends window). **DEFERRED sub-clauses:** the GUI slot-restore button
  (engine `bard_restore_mantle_of_majesty_from_slot` is done + bound + tested, just no button yet — needs a
  slot-level picker like Font of Inspiration); `mantle_majesty_turns` is session-only (not save/load
  persisted, mirrors `sacred_weapon_turns`).

**Deferred (per scope / size):**
- **Dance**: Bardic Damage unarmed strike, Agile Strikes, L6 Inspiring Movement, L14 Leading Evasion.
- **Glamour**: Mantle-of-Inspiration Reaction-move rider (above) only. (Mantle of Inspiration L3,
  Beguiling Magic L3, Mantle of Majesty L6, and Unbreakable Majesty L14 are all DONE — see above.
  Glamour is complete except the no-OA Reaction-move clause, which needs new infra.)
- **Lore**: L14 Peerless Skill (re-add die on the bard's own fail).
- **Valor**: fully implemented (L3 Combat Inspiration + L6 Extra Attack + L14 Battle Magic;
  Martial Training = no-op) — see the **Implemented** list above. Nothing deferred.
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

## Warlock Eldritch Invocations (combat-sim modeling)

Implemented (engine + GUI picker `InvocationDialog`): Agonizing Blast, Repelling Blast,
Eldritch Mind, Armor of Shadows, Fiendish Vigor, Devil's Sight, Eldritch Spear, Witch Sight,
One with Shadows, Otherworldly Leap, Gift of the Depths, Master of Myriad Forms, and the
**Pact of the Blade family** (Pact of the Blade, Thirsting Blade, Eldritch Smite, Lifedrinker).
Selected in a scrollable picker; unimplemented/level-locked/feat-deferred entries render greyed.

### Pact of the Blade family (IMPLEMENTED 2026-06-08)
- **Pact of the Blade** (inv 13): a new `Weapon::pact_weapon` flag (mirrors `finesse`). The GUI
  conjures a fixed `"PactBlade"` (1d8 slashing, proficient, `pact_weapon=True`), appended to the
  Warlock's weapons in `_on_stats_ok` + the load path (idempotent). `attackModifier` /
  `damageAbilityMod` (combat_core.cpp) allow CHA for a pact weapon — modeled as
  `max(normal STR/DEX rule, CHA mod)`, i.e. "best of, never worse". The flag also **identifies**
  the pact weapon for the three riders below.
  - *Simplification:* the pact weapon is a fixed 1d8 slashing blade, not "any melee weapon you
    choose" (no weapon-build system).
- **Thirsting Blade** (inv 14, L5+): `num_attacks = 2` in the Warlock chassis
  (`initializeClassResources`) when `hasInvocation(14) && hasInvocation(13) && level >= 5`.
  - *Simplification:* like every other class's Extra Attack this is **global**, not gated to
    pact-weapon attacks only — a Thirsting-Blade Warlock gets two swings with any weapon.
- **Eldritch Smite** (inv 15, L5+): on-hit rider modeled on Divine Smite. Eligibility flag
  `eldritch_smite_available` set in `applyAttackResult` (pact-weapon hit, L5+, inv 13+15, free
  bonus action, a pact slot, no leveled spell this turn); applied out of band via
  `applyEldritchSmiteEffect` (GUI `_offer_eldritch_smite`, bound `apply_eldritch_smite_effect`):
  expend the pact slot (level = `pact_slot_level()`) as a Bonus Action → `(slot+1)d8` Force, knock
  a Huge-or-smaller target (`getSize() <= 3`) Prone. Once per turn (`eldritch_smite_used`).
- **Lifedrinker** (inv 16, L9+): **automatic** (no player choice) inline in `applyAttackResult`
  (like Zealot Divine Fury) — on a pact-weapon hit, once per turn, deal extra Necrotic =
  `max(1, CHA mod)` and grant the Warlock that many temp HP (`grantTempHp`). Flag `lifedrinker_used`.
  - *v1 modeling:* the temp-HP grant uses the standard `max()` semantics (doesn't stack).
- Per-turn flags reset in `Agent::turn()` (canonical) + `runRound` (RL parity). Tests in
  `test_warlock_phase3.py`. `apply_eldritch_smite_effect` added to `replay_record.py`'s recorded set.

- **Devouring Blade** (inv 17, L12+, needs Thirsting Blade): IMPLEMENTED — the Thirsting Blade
  block sets `num_attacks = 3` when `level >= 12 && hasInvocation(17)` (the extra attack becomes two
  extra). Same global-Extra-Attack simplification as Thirsting Blade.

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

### Invisibility / Greater Invisibility spells (data-driven)
Both are now self/touch buffs (JSON `attack_type: Automatic`, `type: Harm` with no damage —
there is no "Buff" SpellType, so Harm-with-no-damage is used) that apply the Invisible
condition via `conditions:[{condition_name:"Invisible"|"GreaterInvisible"}]` (no `save_ability`
⇒ no save). `addAgentCondition` maps those names to `conditions.invisible` (+
`invisible_persists_on_action` for the Greater variant). Duration is modeled as 10 rounds (not
RAW 1 hour / 1 minute) — long enough to outlast a combat. Cast targets self/ally via
`SpellAction.target_indices`; self-targeting in the GUI depends on the click landing on the
caster. One with Shadows reuses the same Invisible condition (non-persistent).

## Monster on-hit riders: Grappled / Prone / Poisoned (2026-06-09)

Synthesized NPC weapons can now carry on-hit riders from `tools/monster_weapon_overrides.json`
(passed through by `monster_parser._weapon_for_slot` into the weapon dict's `conditions` /
`mastery`). How each is modeled:
- **Grappled** — a `{"condition_name":"Grappled", "escape_dc":N, "contested":bool}` entry routes
  through the shared grapple core `CombatEngine::resolveGrapple` (which `executeGrapple` and the
  future Grappler feat also call). Default `contested:false` = automatic on hit; `escape_dc`
  overrides the computed `10 + STR mod + prof`. NOT the generic active-condition path (that only
  tracks duration and would leave the `grappled` flag false).
- **Prone** — modeled as weapon **`"mastery":"Topple"`** (CON save vs `8 + prof + abilityMod` →
  `applyProne`). `to_record` auto-sets the monster's `weapon_mastery=1` so Topple fires; without
  the Weapon Mastery feature it would be inert.
- **Poisoned** — `{"condition_name":"Poisoned", "condition_duration":N}` via the existing
  `addAgentCondition` path (sets the `poisoned` flag).

Deliberate deferrals / approximations:
- **Shambling Mound 5 ft *pull*** is NOT modeled — the engine's weapon push handler requires
  `push_ft > 0`, so negative/pull-toward isn't supported. Deferred until a pull mechanic exists.
- **Approximate save DCs** — Topple/Poison/grapple-escape DCs derive from the attacker's
  ability + prof, not the fixed book numbers (no fixed-DC field without an engine change).
- **Poisoned has no auto-expiry** — `tickAgentConditions` doesn't clear the `poisoned` flag, so a
  "1 turn" poison rider persists (matches the existing Poison weapon-mastery behavior). A
  duration-driven clear would need adding "Poisoned" to the tick-removal switch.
- **`condition_rider`** (beast-form field) is still set in `main.py` but never consumed in C++ —
  inert. Beast-form on-hit conditions would need the same routing if/when wanted.
- Deferred riders (unchanged): Wereboar lycanthropy curse + Tusk charge-conditional extra dice,
  Hobgoblin Warlord Javelin speed −10, Bone Devil "can't regain HP while Poisoned".

## NPC innate spellcasting auto-population (2026-06-09)

Monster stat blocks' innate spells (CSV columns At Will / 3-Day / 2-Day / 1-Day) are auto-loaded
onto placed/summoned NPCs. The CSV names are resolved against `spells.json` and written to each
bestiary record as `spell_indices` + `npc_spell_groups` (`{uses/day: [names]}`) — the same shape
the saved-agent loader already consumes. Resolution lives in `gui/read_stats_from_csv.py`
(`attach_npc_spells`, runs during full regen) and the one-shot `tools/add_npc_spells.py`
(augments the existing JSON in place). GUI glue: `_load_npc_spells_from_record` in `main.py`,
called from the bestiary-placement and summon paths. 161 casters, 886 spells attached.

Deliberate approximations / deferrals:
- **At-Will *leveled* spells use a 99/day budget** (`AT_WILL_USES`), not true unlimited. An NPC
  leveled spell needs `uses_max > 0` to be castable (cantrips are level 0 → always castable and
  stay ungrouped), and the only no-infra way to express "at will" is a large N. The combat panel
  shows e.g. `Detect Magic 99/99`. A real unlimited flag would be an engine change.
- **Fixed spell save DC / spell attack from the CSV are ignored** — the engine computes DC and
  attack from the NPC's spellcasting ability + prof bonus (same as the manual-NPC flow). The
  `Spell Save DC` / `Spell Attack` columns are not wired (no fixed-DC field without an engine change).
- **Upcast level annotations are stripped** — `Melf's Acid Arrow (3rd level)` resolves to the base
  `Acid Arrow`; the NPC casts at base level (no per-listing cast-level override).
- **7 referenced spells are not in `spells.json`** (skipped, reported by `add_npc_spells.py`):
  Beast Sense, Destructive Wave, Friends, Synaptic Static, Summon Fiend, Jallarzi's Storm of
  Radiance. Add them to the catalog to pick them up automatically.
- Source-data spelling fixes live in `_SPELL_ALIASES` (read_stats_from_csv.py); extend as new
  typos surface (monster data is unreliable).

## Origin feats (2026-06-09)

The combat-relevant 2024 Origin feats are wired into the C++ engine. Feats are stored as a
`std::vector<std::string> feats` on `Agent::Stats` with `has_feat()` (mirrors
`eldritch_invocations`/`has_invocation`). `add_feat(name)` grants a feat AND applies its one-time
stat effects (Tough HP, Alert initiative proficiency, Lucky points) — call it after ability
scores/level/prof_bonus are set. On reload, set `feats` directly (the bonuses are already folded
into the persisted `hp_max`/`luck_points`, so re-applying would double-count). Persisted via
`feats`/`luck_points`/`luck_points_max` in the save JSON. Tests: `gui/test_feats.py`.

Implemented:
- **Tough** — `hp_max`/`hp_cur` += 2 × character level on grant.
- **Alert** — sets `initiative_prof` (prof bonus added to initiative); Initiative Swap via
  `CombatEngine::swap_initiative(order, a, b)` (returns the reordered list).
- **Savage Attacker** — once per turn, rerolls the weapon damage in `applyAttackResult` and keeps
  the better roll (compares the "weapon" damage-breakdown entry so flat riders like Rage are fair).
  Gated by `conditions.savage_attacker_used_this_turn`.
- **Tavern Brawler** — Enhanced Unarmed Strike (bare "Unarmed" weapon deals 1d4 + STR Bludgeoning,
  in `rollDamage`) + Damage Rerolls (reroll a 1 on that die) + Push (Unarmed hit shoves 5 ft, once
  per turn, via `forceMoveAgent`). Scoped to the default "Unarmed" weapon — Monk "MonkUnarmed" is
  left untouched.
- **Lucky** — Luck Points = prof bonus (regained on Long Rest); `spend_luck_for_advantage(bm, idx)`
  spends one to grant Advantage on the agent's next d20 (via the existing pending-advantage hook).

Deferred / noted:
- **Lucky — Disadvantage benefit** (impose Disadvantage on an attack roll against you): needs a
  defender reaction window (OnD20Seen imposes a −1d4 penalty, not a reroll-to-disadvantage). Only
  the self-Advantage benefit is wired. The single engine-wide `pending_advantage_` flag means the
  Lucky character must spend immediately before their own roll (fine in the turn-by-turn GUI flow).
- **Healer** — both benefits deferred. Battle Medic needs a Hit-Dice pool (no `hit_dice_*` on Stats
  yet) and a Healer's Kit item; Healing Rerolls (reroll 1s on healing dice) would touch every
  healing dice site (Cure Wounds, Healing Word, Lay on Hands, Healing Light, …).
- **Magic Initiate** — a spell-grant feat; the GUI can already add the cantrips/level-1 spell to a
  character's spell list. The free once-per-long-rest cast without a slot is not separately tracked.
- **Crafter, Skilled, Musician** — out of combat (tool/skill proficiencies, item discount/crafting,
  rest-time Heroic Inspiration). Noted only; not modelled. (Musician's Encouraging Song could later
  reuse the existing Heroic Inspiration mechanic if wanted.)
- **GUI feat picker** — DONE 2026-06-09. The StatsDialog has an "Origin Feat:" cycle picker (PCs
  only, hidden for NPCs); `App._set_origin_feat` applies it idempotently, stripping the prior feat's
  one-time effects (Tough HP, Alert prof, Lucky points) before applying the new one via `add_feat`.
  Edge case: re-confirming the *same* feat is a no-op, so **changing a Tough character's level via
  the dialog does not recompute the +2/level HP** (the HP stepper is editable, so adjust there). One
  feat per PC by design (general/repeatable feats are a future, separate UI).
- **Improvised weapon proficiency** (Tavern Brawler) and the once-per-turn "as part of the Attack
  action" qualifier on Push are not enforced.

## General feats — phase G0 + G1 (2026-06-10)

Foundation + the damage-type on-hit cluster. `Weapon` gained `heavy`/`light` flags (bindings,
`helpers._dict_to_weapon`, `weapons.json` tagged per 2024). A multi-select **FeatDialog** (43
general feats with status tags: `combat`/`soon`/`note`) is launched from the StatsDialog "Feats:"
button (PCs only) and commits names into `Agent.Stats.feats` via `App._set_general_feats` — disjoint
from the single-select origin-feat picker. Tests: `gui/test_general_feats.py`.

Design: **a feat's Ability Score Increase is NOT auto-applied** — set final ability scores via the
stat steppers (decision avoids the strip-on-swap/ripple problem; "Ability Score Improvement" is a
no-op marker). General feats currently carry no one-time stat effects, so `_set_general_feats` is a
plain replace. **Prerequisites are not enforced** (soft, combat-sim convenience).

Implemented combat mechanics (all in `applyAttackResult`, keyed on `r.physical_damage_types` /
`r.critical` / `w.heavy`, with per-turn `Conditions` flags reset in `Agent::turn()`):
- **Crusher** — Bludgeoning hit → push 5 ft once/turn (size-gated ≤ atk+1).
- **Piercer** — Puncture: reroll one damage die once/turn (rerolls the lowest `dice_results` entry
  using the weapon's Piercing die size — approximate on multi-type weapons; "must use new" applied
  unconditionally) + Enhanced Critical: +1 Piercing die on a Piercing crit.
- **Slasher** — Hamstring: Slashing hit → −10 ft Speed once/turn (reuses the `slowed` flag).
- **Great Weapon Master** — Heavy Weapon Mastery: +PB damage on a Heavy melee hit that is part of
  the Attack action (`action.attack_slot != "bonus"`); every qualifying hit, not once/turn.

**G1b — enhanced-crit advantage effects — DONE 2026-06-10.** Crusher crit → `crusher_marked`
(+`crusher_marked_by`) on the victim: attack rolls against it have Advantage. Slasher crit →
`slasher_marked`: the victim's own attacks have Disadvantage. Both checked in `determineAdvantage`
(Reckless-style) and expire at the start of the *feat-user's* next turn — cleared in
`CombatEngine::beginTurn` by scanning for marks whose `*_marked_by == agent_idx` (the GUI reaches
beginTurn via begin_turn_flow, same path as the Shield "+5 AC until your next turn" expiry). NOT
reset in `Agent::turn()` — that expires at the victim's turn, which is wrong (Slasher's disadvantage
must apply *during* the victim's turn). Single source tracked (last critter wins). Tests in
`test_general_feats.py`.

**G2 — Grappler + Sentinel — DONE 2026-06-10.**
- **Sentinel** — all 3 clauses complete (clause 2 Disengage-OA + clause 1 Halt + clause 3 Guardian/
  OnAllyAttacked); see the reaction-window section above.
- **Grappler** — **Punch-and-Grab**: an Unarmed-Strike hit as part of the Attack action
  (`w.name == "Unarmed"|"MonkUnarmed"`, `action.attack_slot != "bonus"`) arms
  `Conditions::grappler_punch_grab_available`; `applyPunchAndGrab` then ALSO runs a grapple through the
  shared `resolveGrapple` core (contested check, computed escape DC — no parallel path), once per turn
  (`grappler_punch_grab_used`). Deferred-flag + apply-effect pattern (like Divine/Psionic Strike): GUI
  `_offer_punch_and_grab`; auto/RL leaves it to the offer (no inline, same as the other attacker on-hit
  riders). **Advantage** on attack rolls vs a creature you've grappled is in `determineAdvantage`
  (tgt grappled + `grappler_idx == attacker` + `hasFeat("Grappler")`). Tests in `test_general_feats.py`.
  *Deferred:* **Fast Wrestler** (no Speed reduction dragging a grappled creature of your size or smaller)
  is a **no-op** — the engine has no drag-movement system (a grappled creature has Speed 0 and the
  grappler can't pull it along), so there's nothing to discount. Revisit if drag-movement is ever added.

**G3 — Reaction feats + shield-in-off-hand foundation — MOSTLY DONE 2026-06-10.**
- **Shield-in-off-hand foundation.** `Weapon.is_shield` (+ existing `ac_bonus`) lets a Shield occupy a
  weapon slot (the off-hand) instead of only the Armor slots — the user's mental model ("holding a
  Shield" = a Shield in the off-hand). `isHoldingShield(bm, idx)` scans weapon slots (is_shield, or a
  weapon named "Shield"); `calculateAC` now scans ALL weapon slots for the shield `ac_bonus` (was: only
  the last slot — that was the bug that made an off-hand shield grant no AC). weapons.json has a "Shield"
  entry (is_shield, ac_bonus 2, off_hand); `helpers._weapon_to_dict`/`_dict_to_weapon` carry is_shield +
  ac_bonus (so equip + save/load round-trip). Shared gate for Shield Master AND the queued shield-gated
  Fighting Styles (Interception, Protection, Unarmed Fighting). *GUI:* a Shield is selected like any
  weapon into the off-hand slot (no is_shield/ac_bonus edit fields in WeaponDialog — it comes
  preconfigured from weapons.json; the dialog deep-copies dicts so the keys survive editing).
- **War Caster** — Advantage on concentration saves: `checkConcentrationOnDamage` + `concentrationSave`
  roll with Advantage when the concentrator `hasFeat("War Caster")` (alongside Eldritch Mind). The
  Reactive-Spell clause (cast a cantrip as an OA) and Somatic-with-full-hands are deferred (out of scope /
  complex).
- **Mage Slayer — Concentration Breaker** — when a Mage Slayer damages a concentrator, the conc save has
  Disadvantage. `checkConcentrationOnDamage` gained an optional `damager_idx`; the weapon-damage site
  passes `action.attacker_idx`. (Spell/terrain damage sites still pass -1 — Mage Slayer is a martial
  feat, so weapon damage is the relevant trigger.) **Guarded Mind** (auto-succeed a failed save, 1/short
  rest) DEFERRED — needs a save-success-override mechanism.
- **Defensive Duelist** — OnHit defender reaction: a Finesse-melee wielder may add its PB to AC vs a
  non-crit MELEE hit, flipping it to a miss (a genuine miss, same DM ruling as Shield). Folded into the
  existing defenderOnHit window: `canDefensiveDuelist` + `applyDefensiveDuelist`, listed in
  `defenderOnHitOptions`, handled in both `maybeDefenderOnHitInline` (auto/RL) and `applyAttackReaction`
  (GUI suspend). Offered only when +PB would actually flip the outcome.
- **Shield Master — Push** — `canShieldBash(bm, idx)` gate (Shield Master feat + isHoldingShield + a free
  Bonus Action); the shove itself reuses `executeShove` (no parallel path). *Deferred:* the GUI
  bonus-action Shield-Bash offer (the generic Shove button already does a bonus-action shove), and
  **Interpose** (reaction when subjected to a Dex-save-for-half effect → no damage on a success) — that
  needs a reaction window at the spell save-for-half damage site (like Rogue Evasion, but as a reaction),
  which isn't built.

Deferred:
- All other general feats per GENERAL_FEATS_PLAN.md phases G5–G6 + the deferred list (Mounted
  Combatant has no mount system; rest-based temp-HP feats; Hit-Dice-pool feats stay deferred).

## General feats — phase G4 (bonus-attack + ranged-penalty) DONE 2026-06-11

Built + green. Test: `gui/test_general_feats_g4.py` (17 cases).

**Ranged-penalty (pure gating, no GUI economy):**
- **Sharpshooter** — in `determineAdvantage` (combat_attack.cpp): clears the long-range Disadvantage
  (`hasDisadvantage` returns only that here, so clearing `disadv` before the engagement check is exact)
  AND the within-5-ft "firing in melee" Disadvantage (any ranged weapon).
- **Crossbow Expert** — same engagement-Disadvantage gate, but **Crossbows only** (`w.name` contains
  "Crossbow"); does NOT touch long range. *Note-only:* Ignore-Loading (Loading isn't modeled — crossbows
  already fire freely) and the off-hand crossbow ability-mod (the engine already adds the ability mod to
  ALL off-hand damage — the 2024 TWF "no off-hand mod" rule isn't modeled, see Two-Weapon Fighting no-op).
- **Spell Sniper** — `rollSpellAttack` (combat_spells.cpp): a nearby enemy imposes no Disadvantage on a
  spell attack roll; **+60 ft range** for attack-roll spells (`sp.attack_type==AttackRoll && range>=10`)
  added in `effectiveSpellRange` (alongside Eldritch Spear). *Note-only:* ignore cover (cover not modeled).

**Bonus-attack:**
- **Great Weapon Master — Hew** — a melee crit OR a kill with a **Heavy** weapon as part of the Attack
  action sets `gwm_hew_available` (Conditions flag, reset in `Agent::turn()`/beginTurn). The GUI offers it
  (`_offer_gwm_hew`, last in the on-hit rider chain, gated on a free bonus action) and routes it through
  the shared `_start_extra_attack` flow (per `reusable_bonus_attack`). *v1 limitation:* accepting Hew
  forgoes any remaining Attack-action attacks (the bonus attack takes over the pending sequence); RAW lets
  you finish your attacks first, then Hew — the mid-sequence interleave is deferred (same fragile GUI
  multi-attack sequencing the other riders share). Headless/RL path just leaves the flag set (informational).
- **Dual Wielder** — `+1 AC` in `calculateAC` while a real, non-Shield **melee weapon** sits in BOTH the
  main-hand and off-hand slots. The off-hand bonus attack itself already works via the `off_hand` weapon
  flag, so Enhanced Dual Wielding needs no new attack path. *Note-only:* Quick Draw (no draw/stow economy).

**Still deferred in G4:** **Polearm Master** — see the dedicated entry below.

- **Polearm Master (DEFERRED).** 2024 PHB general feat (prereq STR or DEX 13). Two clauses, both blocked
  on infra the engine doesn't have yet:
  1. **Pole Strike** — when you take the Attack action with a Quarterstaff, Spear, Glaive, Halberd, or Pike,
     you can make ONE bonus-action attack with the weapon's opposite end, dealing **1d4 bludgeoning**
     (uses the same ability mod; on-hit riders/masteries apply). Needs a synthetic "butt-end" weapon
     profile (a 1d4-bludgeoning variant of the wielded polearm) — new infra. The bonus-attack plumbing
     itself already exists (`_start_extra_attack(slot=)`, the generic reusable-bonus-attack flow per
     [[feedback-reusable-bonus-attack]]), so once a butt-end weapon can be synthesized this is a thin
     bonus-action attack against that profile, gated on the wielded weapon being one of the 5 polearms.
  2. **Reactive Strike (a.k.a. the reach-OA clause)** — while wielding one of those weapons, creatures
     **provoke an opportunity attack from you when they ENTER your reach** (not just when they leave it).
     Needs an *enter-reach* reaction window; the reaction framework currently only has LeftReach/OA
     (leaving reach), not an on-enter-reach trigger ([[reaction-system-plan]] lists the 7 existing
     windows — none fire on entering reach). This is the harder half: it's a new flow-checkpoint window,
     parallel to LeftReach but evaluated as a creature steps INTO a threatened cell, with the usual
     one-reaction-per-round economy. Until that window exists, the clause can't be modeled.
  Marked "soon" in the GUI feat list. When picked up, do clause 1 first (small, reuses existing bonus-attack
  infra) and treat clause 2 as its own reaction-window project.

## General feats — phase G5 (armor / saves / movement passives + Telekinetic) DONE 2026-06-11

Built + green (66 suites). Test: `gui/test_general_feats_g5.py` (14 cases). All passives query `hasFeat`
at the point of use (no stat mutation → idempotent across turns/reloads, like Blind Fighting/Speedy).

- **Heavy Armor Master** — in `applyAttackResult` (combat_attack.cpp), before the single HP application:
  if the hit dealt any B/P/S type (`r.physical_damage_types` non-empty) and the target wears Heavy armor
  (an equipped piece with `dex_mod_cap == 0`), `r.total_damage -= min(PB, total)`. *Approximation:* the
  −PB comes off the whole `r.total_damage`, so a mixed physical+magical hit can trim the magical part too;
  and it's the **weapon-attack path only** — a spell attack that deals B/P/S is not covered.
- **Medium Armor Master** — in `calculateAC`: after the most-restrictive DEX cap is computed, `if (cap == 2
  && hasFeat) cap = 3`. Detects Medium armor as "min equipped cap is 2"; Heavy (cap 0) is left unchanged.
- **Durable** — Advantage on Death Saving Throws (Defy Death): both death-save sites (`beginTurn`'s
  start-of-turn save and the on-damage `rollDeathSave`) take `max(roll(20), roll(20))` when `hasFeat`. The
  HD-based Speedy Recovery clause stays deferred (no Hit-Dice pool).
- **Speedy** — +10 ft walking budget in `beginTurn`'s movement seeding (`stats.speed_walk + 10 - penalty`,
  not a stat mutation). OAs against you have Disadvantage: a new `Attack::opportunity` flag (set on the
  single OA path in `applyReactionResponse`, bound for tests) makes `determineAdvantage` impose `dis` when
  the target `hasFeat("Speedy")`. *Deferred:* the "Dash ignores Difficult Terrain" clause (Dash↔difficult-
  terrain movement-cost interaction isn't wired).
- **Athlete** — `standup` costs only 5 ft (vs half-speed) when `hasFeat`. *Note-only:* Climb Speed = Speed
  (no per-turn climb budget in the seeding — only walk/fly/swim/burrow) and the running High/Long Jump
  distance (no jump system).
- **Skulker** — Blindsight 10 ft, added to `piercesInvisibility` alongside Blind Fighting (`dist_ft <= 10
  && (hasFeat("Blind Fighting") || hasFeat("Skulker"))`). *Note-only:* Stealth/Sniper clauses (no skill rolls).
- **Telekinetic — Telekinetic Shove** — `applyTelekineticShove(bm, caster, target)` (combat_riders.cpp,
  bound as `apply_telekinetic_shove`): a 30-ft-range Bonus Action; STR save (DC = 8 + caster PB + best of
  INT/WIS/CHA mod) or pushed 5 ft via `forceMoveAgent` (the same knockback Thunderwave/Shove use, per the
  user). Returns a `ShoveResult` (attacker_roll=DC, defender_roll=save, success=landed). GUI:
  `btn_cbt_telekinetic` ("🌀 Telekinetic Shove", gated on `hasFeat("Telekinetic")` + bonus available) →
  `_start_telekinetic_shove` → reuses the `pending_shove_*` target-click flow, dispatched in `_resolve_shove`
  by `shove_type == "telekinetic"`. *Note-only:* the Mage Hand grant; the DC uses the caster's strongest
  mental mod rather than a stored per-character ability choice.
- **Weapon Master** — GUI-only: the Nick gate `_nick_offhand_idx` now accepts `has_feat("Weapon Mastery")
  OR has_feat("Weapon Master")`, so a non-martial with the feat can use a weapon's Mastery (Nick). C++
  masteries already fire off `w.mastery` regardless of the feat (monsters rely on this), so no engine gate
  changed. *Note-only:* weapon-proficiency grant (proficiency isn't enforced).
- **Resilient** — marker only: like ASI, the chosen save proficiency is set via the StatsDialog save-prof
  checkboxes (`save_prof_*`), so the feat carries no engine effect of its own. Tagged "note" in the GUI list.

**Binding fix (foundation):** `Armor.dex_mod_cap` was never exposed in pybind, so every Python-built Armor
kept the C++ default 30 — meaning `calculateAC` could not cap DEX for heavy/medium armor at all, and the
armor-master feats had nothing to detect. Now bound (`rpg_bindings.cpp`) and round-tripped in
`_dict_to_armor`/`_armor_to_dict` (helpers.py); armor.json already carried the values (Plate/Chain Mail/
Mithral Plate = 0, Cold Iron Breastplate = 2).

## General feats — phase G5b (resistance-ignore caster feats) DONE 2026-06-11

Built + green (67 suites). Test: `gui/test_general_feats_g5b.py` (9 cases). Two shared engine helpers
(combat_spells.cpp) centralize the logic so each damage site is a 2-line change:
- `effectiveMagicDamageMult(caster, target, type, from_spell)` — returns the target's multiplier, but
  Resistance (`0 < m < 1`) is lifted to **1.0** when the caster ignores it: **Poisoner** (type==Poison,
  any source) or **Elemental Adept** (its chosen elements, `from_spell` only). **Immunity (0.0) and
  Vulnerability are untouched** — the feats ignore Resistance only.
- `rollSpellTypeDamage(caster, type, n, die, out_dice, from_spell)` — rolls the dice applying Elemental
  Adept's **treat-a-1-as-a-2** for the caster's chosen elements (`from_spell` only).

Applied at all **5 spell magic-damage sites** (attack-roll / save / automatic in executeSpell, the zone
`applySpellEffect`, and `tickEffects` — the last two fetch caster stats from `effect.caster_idx` /
`fx.caster_idx`) and the **weapon magic-damage site** in `rollDamage` (with `from_spell=false`, so
Poisoner lifts a weapon's Poison resistance but Elemental Adept — spells-only — does not).

- **Elemental Adept** — chosen elements stored as `Agent::Stats::elemental_adept_types` (`vector<int>` of
  MagicDamage_t indices; `hasElementalAdeptType`), bound + round-tripped in the save (`elemental_adept_types`
  in `_save_agents` / `agent_loader.dict_to_stats`). The feat may be taken per element, so it's a list.
- **Poisoner — Potent Poison** — `caster.hasFeat("Poisoner")` + type==Poison; not spell-gated (covers a
  weapon's Poison damage too). The Brew Poison / Apply Poison clause (CON save 2d8 + Poisoned) stays
  deferred (needs the apply-poison-to-weapon + bonus-action infra). Poison is a MagicDamage_t here.

**Reusable element picker (GUI):** `ElementPickerDialog` (dialogs.py) — a small modal multi/single-select
damage-type chooser, parameterized by `(options, current, multi, title)`; `ELEMENTAL_ADEPT_OPTIONS` lists
the 5 elements. Opened from `StatsDialog._on_feats_chosen` when Elemental Adept is selected (multi-select);
the choice threads through `_confirm` → `App._on_stats_ok(elemental_adept_types=...)` → `stats.
elemental_adept_types`. Also the **cast-time** element picker (single-select) for Chromatic Orb /
Sorcerous Burst — wired into `App` (`_element_dialog`, opened from `_activate`, top modal). See the
"Element-pickable spells" entry above for the `SpellAction.damage_type_override` mechanism. DONE 2026-06-11.

*Deferred within G5b:* treat-1-as-2 is applied via `rollSpellTypeDamage` at the spell sites only (weapons
never get it, per RAW). Spell-attack/automatic/save/zone/tick all covered; healing and the necrotic-rider
site (combat_attack:2120) are intentionally untouched (not elemental spell damage).

## Fighting Style feats (2024 PHB) — Blind Fighting DONE 2026-06-10

Fighting Styles are modeled as feats (`hasFeat("<Name>")`), granted by the Fighting Style feature.

**Blind Fighting — Blindsight 10 ft — DONE.** The engine already models blindsight as exactly one
mechanic: `piercesInvisibility` (combat_visibility.cpp) → `canPerceiveTarget` → gates
`availableAttacks` (an invisible creature is otherwise *unattackable*, stricter than RAW) and the RL
observation LoS flag. Blind Fighting is queried from **`hasFeat("Blind Fighting")` inside
`piercesInvisibility`** (within 10 ft), NOT by setting `blindsight_range=10` — because the Python
save/load layer does NOT serialize the raw sense ranges (`blindsight_range`/`truesight_range`/etc.),
and reload sets the feats list directly without re-running `addFeat`'s one-time effects, so a
stat-mutation approach would silently drop on reload. Feats ARE serialized, so the hasFeat path
round-trips. Two halves:
- *Offense:* within 10 ft a Blind Fighter perceives/targets an invisible creature (the `piercesInvisibility` edit).
- *Defense:* the invisible-attacker advantage in `determineAdvantage` (combat_attack.cpp ~L1221) was
  **unconditional** — even against a Truesight defender (pre-existing gap). Now gated on
  `!canPerceiveTarget(bm, target_idx, attacker_idx)`, so a defender that perceives the attacker
  (Blind Fighting in 10 ft, or any Truesight/Blindsight) denies the advantage. Latent correctness
  fix for all see-invisible defenders, not just Blind Fighting.
- *Limitation:* blindsight's "see in **darkness**" clause has no distinct effect — `canPerceiveTarget`
  only checks the `invisible` axis, not obscuration; darkness already does not gate attacks in this
  engine (consistent with how existing `blindsight_range` behaves).

Tests: `gui/test_fighting_styles.py` (registered in run_all_tests.py) — offense at 5/10/15/20 ft,
available_attacks re-entry, defense (invisible attacker denied advantage vs a Blind Fighting defender;
control keeps advantage vs a sighted one).

**Passive batch — DONE 2026-06-10:**
- **Archery** — `attackModifier` (combat_core.cpp): +2 when `w.type==Ranged && !w.thrown`. Shows in
  `AttackResult.attack_mod`.
- **Defense** — `calculateAC` standard branch (combat_core.cpp): +1 when `has_armor` (the unarmored
  Barbarian/Monk branches return early, so it's armor-only by construction).
- **Dueling** — `applyAttackResult` damage-rider block (combat_attack.cpp): +2 when melee, `!two_handed`,
  and no OTHER *real* weapon is equipped. "Real" = a weapon slot with damage dice that isn't a Shield;
  default/empty `Unarmed` slots (no dice) and Shields don't count. Pushes a `("Dueling",2)` breakdown
  entry. NOTE: the dice-bearing `_mk_weapon("Filler")` padding in `test_feats._arm` would read as a
  second real weapon — Dueling tests use `_solo_arm` (exact slots, true empties).
- **Thrown Weapon Fighting** — same block: +2 when `r.hit && w.thrown`.
- **Great Weapon Fighting** — `rollDamage` physical loop (combat_attack.cpp): with a two-handed melee
  weapon, any die roll of 1 or 2 → 3 (`if (gwf && d < 3) d = 3;`). Verified deterministically via
  `AttackResult.dice_results`.
- **Unarmed Fighting** — `rollDamage` near the Tavern Brawler block: a bare `Unarmed` strike rolls 1d6
  Bludgeoning. Supersedes Tavern Brawler's 1d4 (TB block now gated `&& !hasFeat("Unarmed Fighting")`,
  so exactly one die is added with both feats).
- **Two-Weapon Fighting** — no-op marker: the engine already adds the ability mod to off-hand damage
  (`rollDamage` always adds `damageAbilityMod`; the off-hand penalty is unmodeled), so the style's
  effect is already present.

*Passive-batch simplifications:* Dueling and Thrown Weapon Fighting can BOTH fire on a one-handed
thrown weapon (a creature with both styles double-dips +4) — accepted, rare; the engine can't tell a
melee swing from a throw on a melee-type thrown weapon, so Thrown Weapon Fighting's +2 also applies
when such a weapon is used in melee. GWF gates on `two_handed` only — a Versatile weapon wielded in two
hands isn't distinguished (we don't track current grip). Unarmed Fighting DEFERS the d8-when-empty-handed
upgrade (no weapon-array access in `rollDamage`) and the start-of-turn 1d4 to a creature you've Grappled.

**Interception — DONE 2026-06-10.** OnAllyAttacked bystander damage-reduction reaction: when a creature
you can see hits a target other than you within 5 ft of you, spend your reaction to reduce that target's
damage by 1d10 + PB (must hold a Shield or a Simple/Martial weapon). `canIntercept` (combat_attack.cpp)
gates one bystander; `applyInterception` (combat_riders.cpp) rolls 1d10+PB and **heals the target back**
by min(reduction, damage) — modeled exactly like Psi Warrior Protective Field (post-hit heal-back).
Auto/RL via `maybeInterceptionInline` (executeAction, after applyAttackResult, OnAllyAttacked window +
decider); GUI scans `can_intercept` across agents → `_offer_interception` (bystander reactor, mirrors
`_offer_protective_field`). Bindings: `can_intercept`, `apply_interception`. In the FeatDialog (status
"in"). Tests: test_reactions.py (reduces damage, adjacency-to-target gate, feat gate, direct-apply +
reaction spend). *v1 limitation (shared with Protective Field):* the heal-back can't rescue a target
dropped to 0 by the hit (`canIntercept` requires the target's hp_cur > 0 post-hit). "Shield or Simple/
Martial weapon" is approximated as "holding a Shield OR any weapon with damage dice" (the engine doesn't
classify simple/martial). The damage reduction is a heal-back, so `AttackResult.total_damage` still
reports the gross (unreduced) damage — tests assert on the target's HP, not total_damage.

**Still TODO** — only **Protection** (Fighting Style) remains deferred: it imposes Disadvantage on an
attack roll *before* it resolves (a pre-resolution reaction), and no such reaction window exists — the
hardest one to build. GUI: Fighting Styles share the FeatDialog general-feat list (granted by the
Fighting Style feature; prereqs not enforced) — engine is correct via `hasFeat`.

## Bug fixes 2026-06-10
- **NPC/monster weapons survive save→load.** The GUI saved weapons by NAME and rebuilt them via the
  PC `weapons.json` catalog, so non-catalog weapons (Bite/Claw/custom monster attacks) and per-weapon
  customizations were dropped. `_save_agents` now writes the full `_weapon_to_dict` per slot;
  `_load_agents` reconstructs from the dict (still accepts a bare name string for old saves →
  catalog lookup). `agent_loader.load_agents_from_json` already handled dict weapons. Test:
  `test_save_load_weapons.py`. (Note: weapon `conditions`/on-hit riders are still not serialized.)
- **Self-origin spell range ring.** The cast-time "range circle" drew `sp.range`, which is 0 for
  Cone/Line spells (their reach is in `radius`/`length`), so Cone of Cold showed a 0-ft ring. Fixed
  in `_draw_*` range-circle code: Cone→`radius`, Line→`length`, else→`range`. The AoE cell preview
  (`_aoe_cells`) was already correct (used `radius`), which is why damage applied fine.

## Factions / Teams (2026-06-11)
N-faction team system (`PlacedAgent.faction`, int; 0 = neutral/unassigned). `BattleMap.get/set_agent_faction`
+ readonly `PlacedAgent.faction` property. `CombatEngine::areAllies(bm,a,b)` = same NON-zero faction
(neutral is its own faction, allied with no one). GUI labels in `constants.py` (`FACTION_NAMES/COLORS/CHOICES`,
`faction_name`, `faction_color`); red=1, blue=2. Four rules:
- **Rule 1 (hide):** `checkHide` + `checkHiddenAgentDetection` skip same-faction observers — only enemies
  prevent/spot a hide.
- **Rule 2 (harmful AoE):** friendly fire stays ON by default (Fireball roasts allies). Allies are spared
  only via the existing Evoker `safeTargets_`/Careful, or a spell with the new `Spell.selective_targeting`
  flag ("creatures of your choosing", e.g. Radiance of the Dawn → auto-spares same-faction). Gated on
  caster faction != 0.
- **Rule 3 (beneficial AoE):** `type==Heal`, non-Single geometry, caster faction != 0 → drops non-allies
  (enemies never healed). Neutral caster keeps legacy "affect everyone" behavior (no regression for
  un-teamed encounters / old saves).
- **Rule 4 (GUI confirm):** `_confirm_friendly_harm` pops a ContextMenu before a harmful weapon attack or
  Harm spell on a same-team target (`_pending_spell_is_harm` gates spells; heals never prompt).
- **Rule 5 (opportunity attacks):** `detectProvokes` (combat_movement.cpp) skips `areAllies(bm, mover, r)`
  reactors — teammates don't OA each other when an ally leaves their reach (added 2026-06-13; enemies and
  neutrals still provoke). Regression: `test_reactions.py::test_ally_does_not_provoke_oa`.
GUI: `_show_visible_targets_popup` annotates header + each line with team; `TeamPickerDialog` (dialogs.py,
opened from an agent's right-click menu "Set Teams…") cycles each agent neutral→red→blue. Faction persists
in save/load (top-level `"faction"` key; defaults 0 for old saves). Summons inherit the summoner's faction
in `_resolve_summon`. Tests: `test_factions.py` (7 cases). Built + green 2026-06-11.

**Limitations / deferred:**
- **Claiming neutrals is non-directional** (chosen "simpler option"): the TeamPicker just reassigns a
  neutral's faction to a real team — there is no per-faction directional relationship (faction A treats
  neutral N as friend while faction B still treats N as enemy). A directional claim matrix is the future
  upgrade if needed.
- **Control-mode-per-team not built** (DM/auto/player axis). For now both teams are human-driven; the
  faction tag is the foundation. Game-mode auto-agents must later honor the visibility rules (PCs hide
  from NPCs and vice-versa via stealth-vs-perception contests).
- **Careful Spell pre-existing discrepancy** (not faction-specific): the engine *fully excludes* Careful
  targets from the AoE area, but RAW Careful only lets them auto-succeed the save (still half damage on
  Fireball). Left as-is — out of scope for the faction work.
- `selective_targeting` is loaded from spell JSON (`map_configs.cpp spellFromJson`) + bound; no spells in
  the catalog set it yet (set it on Radiance-of-the-Dawn-type entries when added).

---

## Ranger — Beast Master (Primal Companion) — IMPLEMENTED ✅ (2026-06-13, built + 71 suites green)

L3 spawn wiring (button/menu/summon/dismiss/save/load) + L7/L11/L15 are done. Companion math lives in
`helpers.compute_companion_loadout`; spawn/dismiss in `main.py` (`_summon_companion`/`_dismiss_companion`/
`_find_companion_idx`); the L11 splash rider in `combat_attack.cpp` (after the Hunter's Mark rider).

**Implemented:**
- **L3 Primal Companion** — Land/Sea/Sky stat blocks (`primal_companions.json`); HP=base+per-lvl×level,
  AC=13+PB, to-hit=Ranger spell-attack mod, dmg bonus=PB; faction/summoner-linked, tombstoned on death/
  dismiss; chosen form round-trips (`primal_companion`).
- **L7 Exceptional Training** — companion gains **Cunning Action** (`has_cunning_action=True` → bonus-action
  Dash/Disengage/Hide buttons) and its natural weapon switches to **Force** (moved to `magic_damage_types`).
- **L11 Bestial Fury** — 2 attacks (`num_attacks=2`) + once/turn the first hit on the Ranger's
  Hunter's-Mark target deals +Force = the mark's dice (`bestial_fury_used` flag, reset in `turn()`).
- **L15 Share Spells** — a Self-range buff (Single geometry, range 0) the Ranger casts on itself is
  re-applied to the companion within 30 ft via `execute_spell` (no extra slot; ties to the same
  concentration). GUI path: `_finish_cast` → `_share_spell_with_companion`.

**Deferred / simplifications:**
- **L7 bonus-action menu** is Cunning Action's Dash/Disengage/Hide (per user call); RAW also lists
  **Dodge/Help** — not separately modeled (no per-companion Dodge/Help affordance).
- **L7 Force is the default at L7+ with no opt-out**: against a Force-immune/resistant foe the player
  cannot revert to the normal physical type. Rare; revisit only if it bites.
- **L15 share is GUI-only** (`main.py`, not in the suite) and limited to true Self buffs — self-origin
  AoEs (Burning Hands etc., Cone/Cube geometry) are intentionally excluded; concentration self-buffs work
  because `executeSpell` re-affirms the same caster concentration with no terrain to drop.

## Ranger — Fey Wanderer — IMPLEMENTED ✅ (2026-06-13, combat-core; awaiting build)

`fey_dreadful_strikes`/`fey_dreadful_strikes_die_size` (Stats) + `fey_dreadful_strikes_used` (Conditions,
reset in `turn()`), all bound. Seeded in `combat.cpp initializeClassResources` (FeyWanderer L3+). Tests in
`test_ranger.py` (chassis, rider once/turn + d4→d6, Beguiling Twist statistical advantage + L7 gate).

**Implemented:**
- **L3 Dreadful Strikes** (distinct from Gloom Stalker's): the first weapon hit each turn deals **+1d4
  Psychic (→1d6 at L11)**, no resource. Rider in `combat_attack.cpp` right after the Gloom Stalker
  Dreadful Strike block; gated on `fey_dreadful_strikes && !fey_dreadful_strikes_used`.
- **L7 Beguiling Twist (save half)** — **Advantage on a save vs a spell that applies Charmed/Frightened**.
  Gated inline (no field) at BOTH spell-save sites in `combat_spells.cpp`: the Save-for-half site (scans
  `sp.conditions` for Charmed/Frightened) and the fresh per-condition save site (checks the condition name).
- **Always-prepared spells** via `main.py _grant_class_features` + `_RANGER_SUBCLASS_SPELLS`: Charm Person
  (L3), Misty Step (L5), Dimension Door (L13), Mislead (L17).

**Deferred / simplifications:**
- **L9 Summon Fey** is NOT granted — the spell isn't in `spells.json` (`_grant_class_features` skips missing
  names gracefully). Add a Summon Fey entry (reusing the summon system) to enable it.
- **L7 Beguiling Twist reaction** (when you succeed on the save, a Reaction can turn the charm/fear back on
  another creature within 60 ft) is NOT implemented — only the defensive save-advantage half. Needs an
  OnSaveSucceed-style window + a redirect cast; deferred.
- **L3 Otherworldly Glamour** (+WIS to CHA checks, extra skill prof) — out-of-combat social, not modeled.
- **L11 Fey Reinforcements** (free Summon Fey) / **L15 Misty Wanderer** (free Misty Step + co-teleport a
  willing ally) — utility free-cast resources, deferred (gated on Summon Fey / movement-co-teleport infra).

---

## Ranger — Hunter & Gloom Stalker (Phase 3 leftovers) — IMPLEMENTED ✅ (2026-06-14, built + 71 suites green)

**Implemented:**
- **Hunter L11 Superior Hunter's Prey** — automatic engine rider extending the Hunter's Mark block in
  `applyAttackResult` (`combat_attack.cpp`): once/turn (`superior_prey_used`), after the mark takes its HM
  damage, splash a fresh roll of the same HM dice to the **nearest** eligible enemy within 30 ft of the
  mark (`footprintDistance` + `areAllies`). Applied directly to the splash victim's Stats with its own
  `processDamageTaken`/`checkConcentrationOnDamage`/`applyUnconscious`.
- **Hunter L15 Superior Hunter's Defense** — OnHit DEFENDER reaction (`canSuperiorHunterDefense`/
  `applySuperiorHunterDefense`), modeled like Uncanny Dodge and wired into the same `defenderOnHitOptions`/
  `maybeDefenderOnHitInline`/`applyAttackReaction` window. GUI surfaces it free via the generic OnHit menu.
- **Gloom Stalker L11 Sudden Strike** (one of the two Stalker's Flurry effects) — `sudden_strike_available`
  Conditions flag set when the Dreadful Strike rider consumes at L≥11; GUI `_offer_sudden_strike` grants one
  FREE extra attack (`_start_extra_attack(slot="action")`, no bonus cost).
- **Hunter's Prey / Defensive Tactics in-dialog picker** — StatsDialog cycle pickers (mirror Cleric
  blessed_strike); round-trip through `_on_stats_ok`'s new `hunter_prey_name`/`defensive_tactics_name` kwargs.

**Deferred / simplifications:**
- **Superior Hunter's Defense is v1-simplified to the triggering hit.** RAW grants Resistance to *that
  damage type until the end of the current turn*; we resist only the one triggering instance (halve it,
  like Uncanny Dodge). For a single-type hit this is equivalent; a later same-turn hit of the same type is
  NOT auto-resisted. Lifting this needs a turn-scoped per-type resistance buff.
- **Gloom Stalker L11 Mass Fear** (the OTHER Stalker's Flurry option — each creature within 10 ft of the
  Dreadful Strike target makes a WIS save vs Frightened) is NOT implemented; only **Sudden Strike** is
  offered. Mass Fear needs an AoE-save GUI flow keyed off the Dreadful Strike hit (reuse the AoE-save +
  Frightened path). Sudden Strike covers the L11 extra for now.
- **Gloom Stalker L15 Shadowy Dodge** (reaction: impose **Disadvantage** on an incoming attack roll, then
  teleport up to 30 ft) is NOT implemented. It needs a **pre-roll, defender-side impose-Disadvantage
  window** — a window shape the engine doesn't have (the OnD20Seen window is post-roll/lowering-only and
  third-party; the OnHit window is post-roll). Deferred with the general "post-hoc reaction interrupts"
  work (see the Architecture section) plus a teleport primitive.
- **Gloom Stalker L3 Umbral Sight** (Darkvision +60; Invisible to creatures relying on Darkvision while in
  Darkness) — needs a lighting/darkvision visibility model; deferred.
- **Phase-2 follow-ups still open:** Favored Enemy free-cast GUI accounting (spend the resource instead of
  a slot), re-mark-on-kill Bonus Action, spell-attack-roll marks (the HM rider is weapon-attack-only),
  Roving's "not in Heavy armor" gate (currently unconditional).

## Vampires / monster bite drain (2026-06-16, built + 73 suites green, confirmed in live play)

DONE: `available_hit_points` (Stats) — a non-negative HP-maximum reduction mirroring `temp_hp`;
`effectiveMaxHp()` = `max(0, hp_max - available_hit_points)`; healing caps to it; cleared on long
rest; bound (`available_hit_points` + ro `effective_max_hp`); saved/loaded; GUI shows it on the HP
bar + panel. `VisibilityLevel::Sunlight` — a bright-light category (vision == Clear) for vampire
detection; `brighter()` combine; lighting save/load/overlay. `reduceHPMax` on-hit weapon rider —
drains the target's HP max by the Necrotic damage dealt and heals the attacker (reads
`AttackResult::magic_damage_dealt[Necrotic]`); Vampire Spawn bite wired in its `off_hand` slot
(1d4+STR Piercing + 3d6 Necrotic + `reduceHPMax`). See memory `vampire-support`.

**Vampire Bite auto-hits a Grappled target — DONE ✅ (2026-06-17)**
New data-driven weapon flag `Weapon::auto_hit_if_grappled` (bound, serialized in `helpers._weapon_to_dict`/
`_dict_to_weapon`): when an attack with this flag targets a creature **this attacker has Grappled**
(`tgt_cond.grappled && grappler_idx == attacker`), a missed roll is promoted to a hit. The roll is still
made (a nat 20 still crits; the OnD20Seen / Shield / Uncanny-Dodge defender windows still open — the auto-hit
fires *after* `resolveAttack`, *before* those windows, so a Shield can still negate it). Implemented as
`CombatEngine::forceAutoHit(bm, s)` called at BOTH `resolveAttack` call sites (`executeAction` auto/RL path +
`beginAttack` GUI path); `InFlightAttack::auto_hit` carries the decision computed in `determineAdvantage`.
The Barbarian Reckless-reroll `resolveAttack` (3rd call site) is gated on `!r.hit` + Barbarian, so a forced
bite hit never reaches it. Set `"auto_hit_if_grappled": true` on the 5 vampire drain Bites in
`DND2024_MonsterStats.json` (Vampire, Familiar, Spawn, Umbral Lord, Warden — the off_hand Bites with the
`reduceHPMax` rider; Infernalist/Nightbringer have no Bite). Combo: the vampire's Claw grapples (escape DC 14)
→ the Bite then auto-hits + drains. Tests: `test_vampire.py::test_bite_auto_hits_grappled_target` +
`test_bite_no_auto_hit_when_grappled_by_other`. **Awaiting build.** Still NOT *gated* on Grappled (any
target can be bitten; the auto-hit is just a bonus when the target IS grappled) — per the on-hit-rider direction.

**Deferred / simplifications:**
- **Sunlight Sensitivity / Hypersensitivity NOT modeled** — the Sunlight *category* exists but no
  creature reacts to it yet (no Disadvantage on attacks/ability checks in sunlight, no radiant
  weakness / "destroyed in sunlight"). Needs an in-sunlight check at the attack-advantage and
  per-turn-damage sites. Foundation only, per the prep decision.
- **No lighting-editor UI to paint Sunlight** — set it via the encounter's `_lighting.json`
  `default_light: "Sunlight"` (round-trips); the LightingEditorDialog can't pick a default category.
- **Bite is an attack + on-hit rider, NOT a CON save**, and is **not gated** on the target being
  Grappled/Incapacitated/Restrained (DM discretion). Per user's "on-hit rider" direction. (It does
  now AUTO-HIT a Grappled target via `auto_hit_if_grappled` — see the DONE entry above — but is not
  *restricted* to one.)
- **No per-weapon attack cap** — `num_attacks` is global, so choosing the bite under the Attack
  action offers num_attacks bites; the DM makes one. A per-weapon attack-count system would fix it.
- **reduceHPMax keys on Necrotic only** (the vampiric case). A different drain type would need the
  rider parameterized by damage type.
