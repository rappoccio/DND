# Ranger subclasses — gap-closing plan

Source: 2024 PHB text for Beast Master, Fey Wanderer, Gloom Stalker and Hunter (pasted by the
user 2026-11-10). This is the **PIN in `NPC_LEARNING_PLAN.md`**: the Ranger subclasses need to be
right *before* Step 6 training. A Ranger that the arena fights with must use its subclass the
way the rules say, or the trained policy learns a different class.

## Where things stand

All four subclasses have been in the engine since June 2026
(`known_limitations.md` § Ranger, `CLASS_STATUSES.md`). This plan is **not** a from-scratch
build. It covers three kinds of gap:

1. **Deferred features.** These were never built.
2. **Rules drift.** These are implemented, but differently from the 2024 text.
3. **Automation.** These features work only when a human clicks them in the GUI. Automated PCs
   (Level 4, arena, generated parties) never use them. For training, this is the gap that
   matters most.

### Audit against the pasted text

| Subclass | Feature | Status today | Gap |
|---|---|---|---|
| **Hunter** | L3 Hunter's Lore | — | Not shown anywhere. Info only. |
| | L3 Colossus Slayer | ✅ engine, automatic | — |
| | L3 Horde Breaker | ⚠️ flag set **on hit**; the GUI offers the extra attack | The text says "when you **make an attack**", so a miss counts too. Automated PCs never take the extra attack. |
| | L7 Escape the Horde / Multiattack Defense | ✅ engine | — |
| | L11 Superior Hunter's Prey | ✅ engine, splashes to the nearest enemy ≤30 ft | — |
| | L15 Superior Hunter's Defense | ⚠️ resists only the triggering hit | The text gives Resistance to that damage type **until the end of the turn**. |
| **Gloom Stalker** | L3 Ambusher's Leap | ⚠️ tied to the Dread Ambusher button, GUI-side only | It should be automatic: +10 ft on the first turn of every combat, no resource. |
| | L3 Dreadful Strike | ⚠️ a pre-armed button (listed under Bonus Action), GUI only | The text makes it a choice **on hit**, like a smite. Automated PCs never use it. |
| | L3 Initiative Bonus | ✅ | — |
| | L3 Gloom Stalker Spells | ❌ missing from `_RANGER_SUBCLASS_SPELLS` | Disguise Self, Rope Trick, Fear, Greater Invisibility and Seeming. All five are in `spells.json`. |
| | L3 Umbral Sight | ❌ deferred ("lighting model") | Darkvision 60 (or +60). Invisible in Darkness to creatures that rely on Darkvision. |
| | L7 Iron Mind | ✅ WIS save proficiency | The INT/CHA fallback only matters for multiclassing, which isn't supported. Skip it. |
| | L11 Stalker's Flurry, Sudden Strike | ✅ flag; GUI offers | Automated PCs never take it. |
| | L11 Stalker's Flurry, Mass Fear | ❌ deferred | — |
| | L15 Shadowy Dodge | ❌ deferred (needs a pre-roll defender window + teleport) | — |
| **Fey Wanderer** | L3 Dreadful Strikes | ✅ engine, automatic | — |
| | L3 Fey Wanderer Spells | ⚠️ Summon Fey (L9) left out "not in spells.json" | It is now in both `spells.json` and `summons.json`. |
| | L3 Otherworldly Glamour | ❌ | Out-of-combat Charisma checks. Skip it; the importer handles the skill. |
| | L7 Beguiling Twist, Advantage | ✅ at the two spell-save sites | Check that non-spell Charm/Fear sources (Frightful Presence etc.) are covered too. |
| | L7 Beguiling Twist, Reaction | ❌ deferred | Needs an "ally/self succeeded a save vs Charmed/Frightened" trigger. |
| | L11 Fey Reinforcements | ❌ | One free Summon Fey per Long Rest, plus a no-Concentration option (duration 1 minute). |
| | L15 Misty Wanderer | ❌ | WIS-mod free Misty Steps per Long Rest; can bring along 1 willing creature within 5 ft. |
| **Beast Master** | L3 Primal Companion, summon | ⚠️ GUI-only (`main.py` `_summon_primal_companion`) | **Arena and generated Beast Masters fight with no companion at all.** |
| | L3 Primal Companion, action economy | ⚠️ gets its own full turn | The text says it Dodges unless the Ranger spends a **Bonus Action** to command it, or gives up **one attack** for Beast's Strike. If the Ranger is Incapacitated, it acts freely. So today's companion is much stronger than RAW. |
| | L3 Restore (Magic action + slot, within 1 h) | ❌ | Takes 1 minute, so it's out of combat. GUI only. |
| | L3 Vanishes if the Ranger dies | ? | Check. |
| | L7 Exceptional Training | ⚠️ Cunning Action always on; Force always on | The text gives the Bonus Action options (Dash/Disengage/Dodge/Help) **only on a commanded turn**. The damage type is a choice. |
| | L11 Bestial Fury | ⚠️ `num_attacks = 2` always | The text gives two attacks only when Beast's Strike is **commanded**. The Hunter's Mark extra damage is ✅. |
| | L15 Share Spells | ⚠️ GUI-only, true Self-range buffs | Move it into the engine so automated Rangers get it too. |

## Step 0 — before any code (frozen once signed off)

Changes to this set need a dated amendment with a reason, agreed by the user.
Steps 0.1–0.7 only read source and write this doc. They touch no source.

| # | Step | Status |
|---|------|--------|
| 0.1–0.7 | Done 2026-11-10 — see *Step 0 findings* below. | [x] |
| 0.1 | **Companion turn.** Find where the companion's turn is driven, in both the GUI and `arena.py`, and the narrowest place to limit it to "Dodge unless commanded". Check whether it vanishes on the Ranger's death (it should vanish on **death**, not at 0 HP). Find where Share Spells lives today. | [ ] |
| 0.2 | **Automated extra attacks.** Find how automated PCs take the other GUI-offered extra attacks (GWM Hew, Cleave mastery, if any), so Horde Breaker and Sudden Strike can follow the same path. If none do, record the smallest engine-side hook. | [ ] |
| 0.3 | **Shadowy Dodge.** Find out whether a defender reaction window exists **before** the attack roll, or only `OnD20Seen` / `OnHit`. Find out whether a teleport primitive exists (how Misty Step moves the caster). | [ ] |
| 0.4 | **Umbral Sight.** Find out whether `combat_visibility.cpp` can answer "is this cell in Darkness" and "does this creature see only by Darkvision". Reuse the light gating from Boon of the Night Spirit. | [ ] |
| 0.5 | **Beguiling Twist.** Find a single point where a save against Charmed or Frightened succeeds, covering both spell and non-spell sources. Confirm that the Advantage half reaches non-spell sources. | [ ] |
| 0.6 | **Summon Fey.** Check the summon-spell cast path. Find out whether a free cast can skip the slot, and whether a cast can drop Concentration and set a 1-minute duration (10 rounds). | [ ] |
| 0.7 | **Arena companion.** Check whether `arena.py` can call the App's `_summon_primal_companion` headless at fight start. If it can't, find the engine-side spawn that works for both. | [ ] |
| 0.8 | **User sign-off** on D1–D11 below. | [x] 2026-11-10: all agreed, D6 adjusted |

### Step 0 findings (2026-11-10)

- **0.1 Companion turn.** GUI: `main.py` `_summon_companion` spawns a summon-linked creature (summoner_idx, `summon_spell = "Primal Companion"`, faction), inserted in initiative right after the Ranger; the human drives it like any summon. Arena: every creature runs `eng.run_npc_turn`, so a companion would get a full NpcDriver turn. Narrowest limit: engine-side at the top of `runNpcTurn` (a Primal Companion not commanded, with a capable Ranger → Dodge, still moves), plus the GUI's action list (`actions.py`) hiding non-Dodge actions on an uncommanded turn. **Death-vanish is missing:** the only engine tombstoning is `dropConcentration` (`combat_spells.cpp` ~3644), and the companion is not Concentration-linked, so it outlives a dead Ranger. Share Spells is GUI-only: `main.py` `_share_spell_with_companion` (~12816). Cunning Action / `num_attacks = 2` / Force are baked at summon time in `helpers.compute_companion_loadout`.
- **0.2 Automated extra attacks.** None. `runWeaponTurn` (`combat_turn.cpp`) ignores `gwm_hew_available`, `cleave_available`, `sudden_strike_available` and `horde_breaker_available`; only the GUI reads the first three. **Horde Breaker is not even offered in the GUI**: nothing reads `horde_breaker_available`. Smallest hook: a post-attack-loop "free extra attack" step in `runWeaponTurn`, guarded by an `NpcTurnState` flag set before `beginAttack` so a park→resume never repeats it.
- **0.3 Shadowy Dodge.** No pre-roll defender window. `OnD20Seen` (`advanceAttack`) is post-roll, lowering-only, for third-party reactors (`d20ReactorBase` excludes nobody but the roller; Restore Balance uses it). Per D6, R2 adds a pre-roll defender window scoped to Shadowy Dodge. Teleport primitive exists: `CombatEngine::teleportAgent(bm, idx, col, row)` + `isValidTeleportDestination`.
- **0.4 Umbral Sight.** Queryable: `bm.getLightLevel(cell)` / `getLightLevelFor(cell, viewer)` return `VisibilityLevel` (Dim / Dark / MagicalDark); Shadow Step and Night Spirit gate on it. "Relies on Darkvision" = viewer has `darkvision_range` but `piercesInvisibility` (Truesight / Blindsight / Blind Fighting / Skulker) and `devilssight_range` don't reach. D5 is buildable.
- **0.5 Beguiling Twist.** No single save point. The Advantage half is inline at three spell sites (`combat_spells.cpp` ~434, ~2249, ~3194). Non-spell Charm/Fear saves are scattered: Menacing Attack (`combat_riders.cpp` ~1023), turn-start repeat saves (`combat_turn.cpp` ~948), Conquering Presence / Turn-style effects (`combat_turn.cpp` ~248), Beguiling Magic (`combat_resources.cpp` ~3329). R3 adds one helper (save vs a named condition) that these sites call, carrying both the Advantage and the reaction trigger.
- **0.6 Summon Fey.** Summon casting is **GUI-only** (`main.py` `_resolve_summon`); the engine NpcDriver never casts summon spells, so an automated Fey Wanderer can't use Summon Fey at all. A slotless cast exists (`pending_summon_free_cast`, used by Wish). Concentration is set in Python, so skipping it is easy, but there is no summon expiry timer — a no-Concentration summon needs a 10-round tombstone. R3 must add an engine-side (or arena-side) summon cast for the automated path.
- **0.7 Arena companion.** Feasible headless: the arena drives a loader `App`, so after `load_agents` and before `roll_initiative` it can call `app._summon_companion(idx, form)`. `roll_initiative` already slots summons right after their summoner (`bind_types.cpp` ~2457).

## Decisions (signed off 2026-11-10; D6 amended)

- **D1. Scope.** Combat features only. Skipped and recorded in `known_limitations.md`:
  - Otherworldly Glamour.
  - The Iron Mind INT/CHA fallback.
  - The Beast Master restore. The GUI gets an out-of-combat "Restore companion (spend a slot)" menu item, nothing more.
  - Swapping the companion form on a Long Rest. Today's dismiss + resummon already covers it.
- **D2. No new macro actions.** The NPC-learning action space (Step 5 `NpcMacroKind` ×11) and the observation sizes stay frozen. Ranger features are used *inside* macro execution and the Level 4 driver, using the heuristics below. Training then sees a correct Ranger without a retrain of the plumbing.
- **D3. Dreadful Strike (Gloom).** It becomes an on-hit choice:
  - GUI: a rider prompt after a weapon hit, like Divine Strike, while uses remain and it hasn't been used this turn. The pre-armed button goes.
  - Auto: spend it on the first weapon hit of the turn while uses remain.
  - Ambusher's Leap becomes automatic: +10 ft walk at the start of the Ranger's first turn of each combat, independent of Dreadful Strike.
- **D4. Stalker's Flurry option (L11).**
  - GUI: after Dreadful Strike, a choice of Sudden Strike / Mass Fear / neither.
  - Auto: Sudden Strike if a valid second target is within 5 ft of the first, otherwise Mass Fear.
  - Mass Fear: WIS save vs. the Ranger's spell DC for the target and every creature within 10 ft of it (allies included, since the text says "each creature"). Frightened until the start of the Ranger's next turn.
- **D5. Umbral Sight.**
  - Darkvision 60, or +60 if the Ranger already has it.
  - While the Ranger's cell is in Darkness, an attacker that has Darkvision but no Blindsight, Truesight or other non-visual sense treats the Ranger as Invisible: Disadvantage on its attacks, and Advantage on the Ranger's attacks against it.
  - This only works if 0.4 finds a queryable darkness test. If it doesn't, the feature is deferred again, and the reason is recorded.
- **D6. Shadowy Dodge.** A defender reaction before the roll that imposes Disadvantage, then an optional teleport ≤30 ft.
  - GUI: pick a destination cell, or skip the teleport.
  - Auto: always take the reaction against a melee or ranged attack roll. Teleport to a reachable free cell ≤30 ft that, for every enemy, is either out of that enemy's reach or out of its line of sight, if one exists; otherwise stay put. *(Amended 2026-11-10 by the user: "out of reach OR line of sight", was "out of reach".)*
  - If 0.3 finds no pre-roll window, add one (scoped to this feature), modelled on the Shield/OnD20Seen plumbing.
- **D7. Beguiling Twist reaction.** The trigger is the Ranger, or a creature the Ranger can see within 120 ft, succeeding a save to avoid or end Charmed or Frightened.
  - It targets a *different* creature the Ranger can see within 120 ft, which makes a WIS save vs. the spell DC. On a fail it is Charmed or Frightened for 1 minute, repeating the save at the end of each of its turns.
  - Auto: Frightened (it hurts the enemy's attacks), aimed at the enemy with the highest threat, whichever the existing auto-target heuristic picks.
  - GUI: a reaction prompt to pick the target and the condition.
- **D8. Fey Reinforcements and Misty Wanderer.**
  - Summon Fey joins the Fey list at L9.
  - L11: a "Fey Reinforcements" resource (1 per Long Rest) gives a slotless cast. Any Summon Fey cast may be made without Concentration for 1 minute. Auto: always no-Concentration (it frees Concentration for Hunter's Mark).
  - L15: a "Misty Wanderer" resource (max(1, WIS mod) per Long Rest) gives a slotless Misty Step, and can bring 1 willing ally from within 5 ft to a free cell within 5 ft of the destination. Auto: brings an adjacent ally who is in melee with an enemy, if there is one.
- **D9. Beast Master action economy** (the big one):
  - The companion keeps its initiative slot right after the Ranger. That matches "acts during your turn" closely enough, and the arena and GUI already handle it. Its **action** is limited to Dodge unless it was commanded during the Ranger's turn just before. It still moves and uses its Reaction freely.
  - **Command (Bonus Action):** the companion may take any action from its stat block. From L7 it may also Dash/Disengage/Dodge/Help with its Bonus Action, and only on a commanded turn; the always-on Cunning Action goes.
  - **Beast's Strike in place of one attack:** in the Ranger's Attack action, one attack can be traded for the companion's Beast's Strike. It resolves immediately, out of the companion's own turn. From L11 (Bestial Fury) it strikes **twice**, and only this way; the always-on `num_attacks = 2` goes.
  - **Incapacitated Ranger:** the companion acts freely.
  - **L7 damage type:** auto-pick Force unless the target resists or is immune to Force, else the natural type (whichever does more after multipliers). The GUI uses the same rule; there is no prompt.
  - **Auto Ranger:**
    - If the Bonus Action has no better use (Hunter's Mark is the only real competitor, and it's cast once), command the companion.
    - If the companion can reach an enemy, trade the Ranger's last attack for Beast's Strike only when the Ranger has nothing better (no Extra Attack yet, or a ranged Ranger whose companion is in melee). Otherwise keep the attacks and command with the Bonus Action.
    - This is a heuristic; the trained policy may well beat it.
  - **Share Spells (L15):** moves engine-side. A Self-range spell the Ranger casts also applies to the companion if it is within 30 ft.
- **D10. Hunter fixes.**
  - Horde Breaker triggers on making an attack, hit or miss: once on each of *your* turns, against a creature within 5 ft of the original target that you haven't attacked this turn. Auto: always take it when a valid target exists.
  - Superior Hunter's Defense gives Resistance to the triggering damage type until the end of the current turn (a transient per-type multiplier, cleared at the end of the turn).
  - Hunter's Lore: when the mark lands, the combat log lists the target's immunities, resistances and vulnerabilities. GUI only.
- **D11. Arena / generated parties.**
  - A generated or saved Beast Master spawns its companion at fight start, in its stored form (template default: Land).
  - The Fey Wanderer's `signatures` gain Summon Fey at L9+.
  - A traced fight records the companion like any summon.

## Phases (after sign-off; each phase builds both the GUI path and the automated path, adds tests to `tests/test_ranger.py` or a new `tests/test_ranger_subclasses.py`, ends with the full suite green, and commits only on request)

- **R1 — Hunter.** D10.
  - *Committed 8949def (2026-11-10).* Horde Breaker arms on any weapon attack, hit or miss, on the Hunter's own turn (`ctx_.turn_agent_idx_`, set in `beginTurn`), never on an OA; remembers the target and weapon (`horde_breaker_origin/weapon`); every attack records `attacked_this_turn`. `CombatEngine::hordeBreakerTargets` lists the legal creatures. Auto: `runWeaponTurn` takes the swing after its attack loop (weakest target; park-safe via `NpcTurnState::horde_breaker_launched`). GUI: a free "Horde Breaker (Extra Attack)" row outside the bonus band, offered once the Attack sequence has no swings left; the armed pick refuses any click not on the engine's list. Superior Hunter's Defense now records the hit's types (`shd_resist_*_mask`), folded in by `effective*DamageMult` and cleared as the next turn begins. Hunter's Lore logs immunities / resistances / vulnerabilities when the mark lands. Tests: `tests/test_ranger_subclasses.py` (11), `test_action_menu.py` (Horde Breaker row + click check).
- **R2 — Gloom Stalker.**
  - The spell list.
  - D3 (Dreadful Strike on hit + the automatic Leap).
  - D4 (Mass Fear + auto Sudden Strike).
  - D5 (Umbral Sight).
  - D6 (Shadowy Dodge).
  - *Committed (2026-11-10).* Spells: Disguise Self / Rope Trick / Fear / Greater Invisibility / Seeming at 3/5/9/13/17 (`_RANGER_SUBCLASS_SPELLS`). **D3:** a weapon hit with Dread Ambusher uses left, once a turn, sets `dreadful_strike_available` (+ `dreadful_strike_target/weapon`); `applyDreadfulStrikeEffect` spends the use and deals the Psychic. The Dread Ambusher button is gone; the GUI prompts in the rider chain (`riders.offer_dreadful_strike`, before Mastery), the NpcDriver spends it between swings (`autoDreadfulStrike`, skipped if the hit already dropped the target). Ambusher's Leap: `beginTurn` sets `ambushers_leap` on the first turn of combat; all three movement seeds add +10 ft walk. **D4:** at L11 Dreadful Strike leaves `stalkers_flurry_pending`; `chooseStalkersFlurry` 1 = Sudden Strike (arms `sudden_strike_available`; `suddenStrikeTargets`; GUI free row like Horde Breaker, NpcDriver swings at once, park-safe via `NpcTurnState::sudden_strike_launched`), 2 = Mass Fear (`applyMassFear`: WIS vs spell DC, target + every creature within 10 ft, allies too, not the Ranger; Frightened ticked off at the Ranger's next turn). Auto picks Sudden Strike when it has a target, else Mass Fear. **D5:** Darkvision 60 / +60 once (`umbral_sight_dv`); `umbralSightHides` → Advantage/Disadvantage in `determineAdvantage`. **D6:** new `ReactionWindow::OnAttackDeclared` (before the d20 — `advanceAttack` now rolls via `rollInFlightAttack` after it) and `AfterAttack` (the teleport, after `applyAttackResult`); inline twins for a decider. `ReactionResponse` gains `cell_col/row`. Options: safest cell (`shadowyDodgeDestination`: nearest legal cell out of every enemy's reach or LoS; none/already safe → stay) / pick a cell (GUI map pick, `pending_shadowy_dodge_cell`, wired for players) / stay. Tests: `test_ranger_subclasses.py` (+12), `test_ranger.py` (Gloom tests rewritten), `test_action_menu.py` (+2), `test_picks.py` (+1), golden re-bootstrapped (row removed). Suite 234/0.
- **R3 — Fey Wanderer.**
  - Summon Fey on the spell list.
  - D8.
  - D7 (Beguiling Twist reaction + the scope fix for the Advantage half).
  - *Committed (2026-11-10).* Summon Fey at L9 (`_RANGER_SUBCLASS_SPELLS`). **D8:** resources "Fey Reinforcements" (L11, 1/LR) and "Misty Wanderer" (L15, max(1, WIS mod)/LR). New `PlacedAgent::summon_rounds_left`: >0 = a fixed-duration summon, ticked at the summoner's `beginTurn`, tombstoned at 0, spared by `dropConcentration`; part of the engine snapshot (`RPG_PLACED_AGENT_FIELDS`). GUI: a "Fey Reinforcements: Summon Fey" Action row (a slotless 3rd-level cast through the normal summon flow), and an L11 Concentration question on every Summon Fey (No Concentration → 1 minute). `_resolve_summon`'s spawn became `_spawn_summon`, which the GUI and the automated cast share. Automated: `App._auto_summon_fey` (Fey Reinforcements first, else the highest 3rd+ slot; always no-Concentration from L11; below L11 only when not concentrating; the cell nearest an enemy). The arena's `_take_turn` and the GUI's `_drive_npc_turn_if_pending` call it on a fresh turn, and when it casts, that is the turn. Misty Wanderer: `mistyWanderer` (validated ≤30 ft destination, a willing ally within 5 ft landing in a free space within 5 ft of the destination; every check runs before anything moves) with the GUI row + map pick + "who comes along?" prompt. The NpcDriver's use is `autoMistyWanderer` at the start of a fresh `runWeaponTurn` with `prefer_ranged`, while an enemy has the Ranger in reach, bringing an engaged adjacent ally. **D7:** `beguilingTwistAdvantage` (no Incapacitated clause, per the 2024 text) and `charmFearSaveSucceeded` at every Charm/Fear save site (the 3 spell sites, Mass Fear, Menacing Attack, Intimidating Presence, Frightful Aura, Beguiling Magic, both repeat-save loops, Beguiling Twist's own save). Reactors: the saver or a Fey Wanderer L7+ that can see it within 120 ft. An automated one reacts at once (Frightened on the `npcSelectTarget` enemy, else the nearest). A human one is queued (`takeBeguilingTwistOffers`, capped at 16) and prompted by `_offer_beguiling_twist_if_pending` each frame. The effect is a WIS save or Charmed/Frightened for 1 minute, saving again at the end of each of its turns. Tests: `test_ranger_subclasses.py` (+11), `test_action_menu.py` (+5).
- **R4 — Beast Master.** D9, plus the death-vanish fix if 0.1 finds it missing.
- **R5 — Arena.**
  - D11.
  - A smoke run: one generated party per Ranger subclass, a few arena fights each. Check from the trace or log counts that each feature fires: Dreadful Strike, Mass Fear, companion commands, Beast's Strike, Horde Breaker, Summon Fey, Misty Wanderer.
- **Close-out.**
  - Rewrite the Ranger sections of `known_limitations.md`.
  - `CLASS_STATUSES.md`: clear the "Deferred" line.
  - Lift the PIN in `NPC_LEARNING_PLAN.md`.
