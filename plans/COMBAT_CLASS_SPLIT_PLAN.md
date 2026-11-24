# Combat class split (`COMBAT_REFACTOR_PLAN.md` R6)

**Status 2026-11-24: done.** Step 0 (D1–D13 + the D6 smoke test) is 57357f0. The move (S1–S6) is
one commit: proof passed, build clean, `./test.sh` 285/0, goldens byte-identical. See *Done* below.

Split `gui/combat_riders.cpp` and `gui/combat_resources.cpp` by D&D class, so a class's
activations and its on-hit riders sit in one translation unit. This is the follow-on that
`COMBAT_REFACTOR_PLAN.md` left floating after R4 ("split resources by class family", amended
2026-11-18 to take riders along). It became R6 there; this file is its working plan.

Scope rule, same as every combat-refactor step: **structural only.** No behavior changes, no
features, no bug fixes, no tidying bundled in.

## Why now

- The two files are one cluster in the graph: 48 of riders' methods cluster with 92 of
  resources', matching the baseline's 27-call `riders → resources` edge, the second-worst peer
  edge in the engine.
- Both grow with every class feature. Resources went from 84 to 105 `CombatEngine::` defs
  between the R4 measurement and 2026-11-18. Riders took all of Arcane Archer AA2–AA5
  (2026-11-24, four commits in one day).
- Together they are 7,207 lines. Adding a Ranger feature today means reading a 3.2k-line riders
  file and a 4k-line resources file to find the Ranger parts.

## Today (measured 2026-11-24, source text only)

| File | Lines | `CombatEngine::` defs | Not bound to Python | Bound, no suite names it |
| ---- | ----: | --------------------: | ------------------: | -----------------------: |
| `combat_riders.cpp` | 3,211 | 90 | 7 | 8 |
| `combat_resources.cpp` | 3,996 | 105 | 11 | 9 |

- **Top-level items.** Riders: 90 methods, `martialArtsDieSize` (file `static`), and two
  anonymous namespaces (`arcaneShotWeapon`, `masterfulHalfSpeed`). Resources: 105 methods,
  `martialArtsDieCount` (file `static`) and one anonymous namespace (`elementName`). There is
  nothing else at namespace scope: no tables, no statics, no `using`. The splitter accounts for
  every line of both files (3,212 and 3,997 with the trailing newline).
- **Helpers have one destination each.** Every caller of each helper lands in the same file:
  the two Martial Arts die helpers and `elementName` go to Monk, and `arcaneShotWeapon` and
  `masterfulHalfSpeed` go to Fighter. Nothing has to move to `combat_internal.hpp`.
- **Includes.** Both files include `combat.hpp`, `battle_map.hpp`, `combat_internal.hpp`,
  `rules.hpp`. Riders adds `<algorithm> <cmath> <string> <tuple> <vector>`. Resources adds
  `<nlohmann/json.hpp> <algorithm> <cmath> <fstream> <string> <string_view> <unordered_set>
  <vector>`. The JSON and `<fstream>` use is Wild Shape's beast loading (Druid).
- **`combat.hpp`** declares all 195 methods, and none of those declarations change.
  `CMakeLists.txt` lists the TUs at `gui/CMakeLists.txt:41`.

## Step 0: frozen 2026-11-24

- **D1. One file per class.** Twelve class files plus feats plus shared, not four family files.
  A "martial" file would be about 3.5k lines on day one. A subclass goes in its parent class's
  file.
- **D2. Pure move.** No renames, no signature changes, no merging of near-duplicates
  (`martialArtsDieSize` and `martialArtsDieCount` stay two functions), no `combat.hpp` edits, no
  declaration reordering, no body tidying. Only file placement, `#include`s and
  `CMakeLists.txt` change.
- **D3. Shared code stays in `combat_resources.cpp`.** That covers the bonus-action budget,
  `consumeBonusAttack`, `spendResource`, `healAgent`, items and thrown items, slot-from-item,
  terrain and light ticks, and rests. Non-class grants go to a new `combat_feats.cpp`.
  `combat_riders.cpp` is deleted, so no catch-all "riders" file is left to grow back.
- **D4. The grantor owns a feature.** That is the class whose rules text grants it: Divine
  Strike → Cleric, Divine Smite → Paladin, Eldritch Smite → Warlock, War Magic and Arcane Charge
  → Fighter. Species and feat features never go to a class file. Anything that can't be placed
  goes to the user.
- **D5. Oracle.** A throwaway script (scratchpad, not a suite) proves that every non-banner line
  of the two old files lands in exactly one new file, unedited, and that nothing is added outside
  the new file headers and include blocks. Then `./test.sh` runs at the baseline count (285/0)
  with goldens byte-identical.
- **D6. One smoke test first.** `tests/test_arcane_archer_direct.py` pins `piercing_shot_cells`
  and a direct `apply_masterful_shots` call. Those are the newest bodies, which were only reached
  indirectly before. It landed before the move, in 57357f0. The other 15 bound-but-unnamed
  methods are logged under *Follow-ups*, not tested here.
- **D7. Names are `combat_<class>.cpp`.** Not `class_<x>.cpp`, which would sit next to the
  unrelated `class_resources.cpp`.
- **D8. `combat_feats.cpp` scope.** Feats (Telekinetic, Sentinel, Grappler, Lucky), fighting
  styles (Interception), Epic Boons (Peerless Aim, Merge with Shadows), Weapon Mastery (Topple)
  and species. Its header states that scope.
- **D9. A generic hook with a single-class body goes to that class.** `onCreatureDied` (Keeper
  of Souls) → Cleric, `charmFearSaveSucceeded` (Fey Wanderer) → Ranger. If a second class ever
  hooks in, the dispatcher moves to shared then.
- **D10. Source order is kept.** Each new file holds its riders block first, in the old order,
  then its resources block, in the old order.
- **D11. Bindings and header are untouched.** Splitting `bind_combat_resources.cpp`, or
  regrouping the `combat.hpp` declarations, the same way is a possible R6b, not this step.
- **D12. Two commits.** Step 0 (the plan and D6's suite) is one commit, 57357f0. The move is the
  second, with the D5 proof and the suite count recorded here.
- **D13. Banners and the old file headers are dropped.** A doc comment directly above a function
  travels with it. Section banners (the `──` blocks) are positional, and some are already
  misplaced: the "Arcane Archer — on-hit Arcane Shot options" banner sits above Ranger's
  `endBeguilingCharm`. So they don't move. Each new file gets a fresh header (class, subclasses,
  contents), and the shared file's header is rewritten for its remaining role.

## Method → file

Helpers are in parentheses. Line counts include leading doc comments and the banners D13 drops,
so the real files come out a little shorter.

| File | ~Lines | From `combat_riders.cpp` | From `combat_resources.cpp` |
| ---- | -----: | ------------------------ | --------------------------- |
| `combat_barbarian.cpp` | 790 | `applyBrutalStrikeEffect`, `applyRecklessReroll`, `canBranchesOfTree`, `applyBranchesOfTree`, `canVitalityOfTheTree`, `applyVitalityOfTheTree` | `activateRage`, `extendRage`, `endRage`, `useIntimidatingPresence`, `useZealousPresence`, `activateRageOfTheGods`, `travelAlongTree`, `applyRetaliation`, `canUsePrimalKnowledge` |
| `combat_bard.cpp` | 379 | `bardMantleOfInspiration` | `grantBardicDie`, `useBardicDie`, `useBardicDieForDamage`, `bardRegainInspirationFromSlot`, `activateMantleOfMajesty`, `bardRestoreMantleOfMajestyFromSlot`, `activateUnbreakableMajesty`, `bardRestoreUnbreakableMajestyFromSlot`, `bardBeguilingMagic`, `bardRestoreBeguilingMagic`, `applySuperiorInspiration`, `bardCuttingWords` |
| `combat_cleric.cpp` | 634 | `applyDivineStrikeEffect`, `canUseDivineIntervention`, `useDivineIntervention`, `applyGuidedStrike` | `moveDuplicate`, `swapWithDuplicate`, `activateCoronaOfLight`, `useTurnUndead`, `lifeSupremeHealing`, `discipleOfLifeBonus`, `graveCircleOfMortality`, `pullOfDeathDamage`, `canPathToTheGrave`, `usePathToTheGrave`, `pathToTheGraveCleric`, `pathToTheGraveAutoRadiant`, `detonatePathToTheGrave`, `canKeeperOfSouls`, `keeperOfSoulsTargets`, `keeperOfSoulsSlot`, `useKeeperOfSouls`, `onCreatureDied`, `canEnhancedNecromancy`, `usePreserveLife` |
| `combat_druid.cpp` | 264 | — | `activateWildShape`, `deactivateWildShape`, `activateStarryForm`, `deactivateStarryForm`, `activateWrathOfSea`, `deactivateWrathOfSea`, `applyDragonMinRoll` |
| `combat_fighter.cpp` | 1167 | `canUseWarMagic`, `markWarMagicUsed`, `availableWarMagicSpells`, `applyArcaneCharge`, `applyPsionicStrikeEffect`, `applyManeuverEffect`, `applySweepingAttack`, `applyRally`, `applyFeintingAttack`, `prepareQuickToss`, `applyPrecisionAttackEffect`, `applyRiposte`, `applyProtectiveField`, `applyTelekineticMovement`, `heldByGraspingShot`, `applyArcaneShot`, `canUseArcaneShot`, `piercingShotCells`, `(arcaneShotWeapon)`, `seekingShotTargetValid`, `finishArcaneSaveShot`, `piercingShot`, `seekingShot`, `curvingShotTargets`, `applyCurvingShot`, `applyEverReadyShot`, `canIndomitableTeleport`, `isIndomitableTeleportDestination`, `applyIndomitableTeleport`, `indomitableTeleportOptions`, `canMasterfulShots`, `masterfulShotsWeapon`, `(masterfulHalfSpeed)`, `isMasterfulShotsDestination`, `masterfulShotsDestination`, `applyMasterfulShots`, `masterfulShotsOptions`, `escapeGraspingShot` | — |
| `combat_monk.cpp` | 701 | `(martialArtsDieSize)`, `applyHandOfHarmEffect`, `handOfHealing`, `wholenessOfBody`, `applyStunningStrike`, `applyOpenHandRider`, `executeFlurryOfBlows` | `(elementName)`, `shadowStepTeleport`, `cloakOfShadows`, `shadowArtsDarkness`, `(martialArtsDieCount)`, `activateElementalAttunement`, `elementalAttunementMove`, `elementalBurst`, `plantQuiveringPalm` |
| `combat_paladin.cpp` | 379 | `applyDivineSmiteEffect`, `applySoulOfVengeance` | `layOnHands`, `activateSacredWeapon`, `activateVowOfEnmity`, `activateAvengingAngel`, `activateElderChampion`, `activateInspiringSmite`, `activateLivingLegend` |
| `combat_ranger.cpp` | 586 | `applyDreadfulStrikeEffect`, `chooseStalkersFlurry`, `applyMassFear`, `beguilingTwistAdvantage`, `beguilingTwistTargets`, `canBeguilingTwist`, `applyBeguilingTwist`, `charmFearSaveSucceeded`, `takeBeguilingTwistOffers`, `suddenStrikeTargets`, `autoDreadfulStrike`, `companionRanger`, `primalCompanionOf`, `companionRestricted`, `canCommandCompanion`, `commandCompanion`, `armBeastsStrike`, `beastsStrikeTargets`, `beastsStrike`, `vanishOrphanedCompanions`, `endBeguilingCharm` | `mistyWandererAllies`, `isMistyWandererAllyCell`, `mistyWandererAllyCell`, `mistyWanderer`, `autoMistyWanderer` |
| `combat_rogue.cpp` | 405 | `applyCunningStrikeEffect`, `applyCunningStrikeRiders`, `applyHomingStrike`, `canRendMind`, `applyRendMind` | `activatePsychicVeil`, `psychicTeleportation` |
| `combat_sorcerer.cpp` | 372 | — | `activateInnateSorcery`, `sorceryIncarnateActive`, `activateDragonWings`, `activateDraconicResistance`, `activateTranceOfOrder`, `activateBastionOfLaw`, `applyBastionWard`, `clockworkCavalcade`, `activateRevelationInFlesh`, `warpingImplosion` |
| `combat_warlock.cpp` | 499 | `applyEldritchSmiteEffect` | `applyOneWithShadows`, `stepsOfTheFey`, `applyStepsOfFeyRider`, `bewitchingMistyStep`, `activateClairvoyantCombatant`, `triggerSearingVengeance`, `useMagicalCunning`, `useHealingLight` |
| `combat_wizard.cpp` | 97 | — | `usePortentDie`, `regeneratePortentDice` |
| `combat_feats.cpp` | 319 | `applyPunchAndGrab`, `canPeerlessAim`, `applyPeerlessAim`, `applySentinelGuard`, `applyTopple`, `applyInterception`, `applyTelekineticShove` | `applyMergeWithShadows`, `spendLuckForAdvantage`, `itemLuckSource`, `luckAvailable` |
| `combat_resources.cpp` | 541 | `consumeBonusAttack` | `hasBonusAction`, `spendBonusAction`, `resetBonusActions`, `spendResource`, `healAgent`, `useItem`, `resolveThrownItem`, `regainSlotFromItem`, `tickTerrainForTurn`, `tickLightEffectsForTurn`, `applyLongRest`, `applyShortRest` |

## Steps

All of S1–S6 is one commit (D12). Every command runs in the container (`CLAUDE.md`).

- **S1. Generate the new files.** A scratchpad script reads the two old files with the
  splitter (each top-level item = its leading comment lines + its text) and the frozen owner
  map (the table above). It writes each item to its destination in D10 order, with its doc
  comment, and banner blocks removed (D13). Each file gets:
  1. a fresh header comment in the existing style: `combat_<class>.cpp – CombatEngine <Class>
     features`, its subclasses, and a one-line contents list. `combat_feats.cpp` states D8's
     scope, and `combat_resources.cpp` states its shared role (D3). The header also says the
     file was split out of riders/resources in R6.
  2. the four project includes (`combat.hpp`, `battle_map.hpp`, `combat_internal.hpp`,
     `rules.hpp`).
  3. the union of the system includes of the old file(s) it draws from. Trimming unused
     includes is tidying, which is out of scope under D2.
  4. `namespace rpg {` … `} // namespace rpg`.

  The script refuses to write anything if an item has no owner or an owner has no items.
  It writes `combat_resources.cpp` in place, and `combat_riders.cpp` is removed with
  `git rm` (one file, named: not an `rm -rf`).
- **S2. `CMakeLists.txt`.** Replace `combat_riders.cpp` with the 13 new files, alphabetically,
  in its slot. Keep `combat_resources.cpp` where it is.
- **S3. The proof (D5).** A separate scratchpad script, written independently of S1's
  generator so it doesn't share its bugs, checks the following:
  1. Take the multiset of lines of the old files minus their banner blocks, old headers,
     includes and the `namespace rpg` open/close lines. Take the same for the new files minus
     their new headers, includes and namespace lines. The two must be **equal**. That means no
     line is lost, duplicated or edited, and no line is added.
  2. Every `CombatEngine::` definition appears exactly once across the new files, in its table
     file. Every helper appears once, in its table file.
  3. Within each new file, the order of definitions matches their order in the old files
     (D10).
  4. `git diff` shows `combat.hpp`, every `bind_*.cpp` and every `tests/` file untouched.

  Its output goes into this plan's done note.
- **S4. Build.** `./build.sh`. Watch for duplicate symbols (a helper emitted twice), undefined
  ones (a missed method) and new warnings under `-Wall -Wextra -Wpedantic -Wshadow
  -Wconversion`. A new warning means something other than placement changed.
- **S5. Test.** `./test.sh` must reach **285/0**, with goldens byte-identical
  (`test_determinism`, `test_multiattack_recipes`, `test_combat_panel`, `test_board_render`,
  `test_dungeon_pages`). Look at these first:
  1. `test_determinism.py` and `test_multiattack_recipes.py`, which have byte-level goldens.
     They catch any RNG-order change if a body was touched.
  2. `test_arcane_archer_direct.py`, `test_arcane_archer_high.py`, `test_arcane_shot*.py`:
     Fighter is the largest new file and carries both anonymous-namespace helpers.
  3. Monk (`test_monk.py`), which has two helpers from two different old files landing in one
     TU, the only place that happens.
  4. Druid Wild Shape (`test_druid.py`), the only JSON and `<fstream>` user.
  5. `test_snapshot.py`. No state moves, but it is the guard if one ever did.
- **S6. Record and commit.** Update this plan's status line, add a done note under *Steps*
  (per-file line counts, the S3 output, the suite count), and mark R6 done in
  `COMBAT_REFACTOR_PLAN.md`'s phase table. Commit, staging files by name: the 13 new files,
  `combat_resources.cpp`, the `combat_riders.cpp` removal, `CMakeLists.txt` and both plans.
  Never push.

### Done (2026-11-24)

- **S1.** `combat_riders.cpp` (3,211 lines) and `combat_resources.cpp` (3,996) became 14 files,
  generated from the owner table above. Every item had exactly one owner, and every owner had
  items. Lines, with the new headers:

  | File | Lines | | File | Lines |
  | ---- | ----: | - | ---- | ----: |
  | `combat_barbarian.cpp` | 802 | | `combat_ranger.cpp` | 608 |
  | `combat_bard.cpp` | 410 | | `combat_resources.cpp` | 561 |
  | `combat_cleric.cpp` | 666 | | `combat_rogue.cpp` | 432 |
  | `combat_druid.cpp` | 285 | | `combat_sorcerer.cpp` | 402 |
  | `combat_feats.cpp` | 350 | | `combat_warlock.cpp` | 530 |
  | `combat_fighter.cpp` | 1,179 | | `combat_wizard.cpp` | 126 |
  | `combat_monk.cpp` | 729 | | `combat_paladin.cpp` | 410 |

  D13 dropped 24 banners: 13 blocks (rule … rule) and 11 one-line `// ── Title ──` headings. One block
  carried real prose, the "OnTurnStartNearby reactions (beginTurn)" banner above
  `canBranchesOfTree` (now Barbarian). It explains the Branches of the Tree window and why
  Sentinel isn't there. That is a candidate for the comment-only follow-up below.
- **S2.** `CMakeLists.txt`: `combat_riders.cpp` replaced by the 13 new TUs, alphabetically, in
  its slot.
- **S3.** Independent proof script, reading the old files from `HEAD`:
  1. multiset of non-blank content lines (banners, headers, includes and namespace lines out):
     old 6,169 = new 6,169, equal;
  2. 200 definitions (195 methods + 5 helpers) against 200 table entries, each found once, in its
     table file, with its body byte-identical;
  3. definition order matches D10 in all 14 files;
  4. `combat.hpp`, `bind_*.cpp` and `tests/` unchanged.
- **S4.** `./build.sh` inside `./test.sh`: 0 compiler warnings, no duplicate or undefined symbols.
- **S5.** `./test.sh` **285/0**. No golden or `tests/` file changed.

Optional, after the commit: rebuild the graph over `gui/` (code only, as on 2026-11-24) to
confirm the cluster split. The class files should come out as separate communities, and the
`riders → resources` edge should be gone.

## Risks

- **Positional comments that are not banners.** A plain comment that describes the *next*
  function travels with it, which is correct. One that sums up the *previous* group travels
  with the wrong function. S1 prints each moved item's first comment line, so the review can
  catch these. Fixing one is a comment edit, and needs the user's OK under D2.
- **Hidden ordering dependencies.** There are no namespace-scope statics or tables, so there is
  no static-init order to break. Function definitions don't depend on their order within a TU
  as long as `combat.hpp` declares them. File-local helpers must still sit above their first use
  in the new file, and D10 keeps that.
- **Build time.** Thirteen more TUs means more parallel compile jobs; `compile.sh` caps jobs by
  memory. The LTO relink dominates either way (R1's note).
- **Merge pain.** Feature work on any class touches these files. Pause class-feature commits for
  the duration of the move. The move is one sitting.

## Follow-ups (not this plan)

- **R6b.** Split `bind_combat_resources.cpp` and regroup the `combat.hpp` declarations by class,
  the same way, if the binding file starts to hurt.
- **Bound methods no suite names** (D6's list; some are reached indirectly):
  `vanish_orphaned_companions`, `apply_precision_attack_effect`, `can_peerless_aim`,
  `apply_sentinel_guard`, `apply_open_hand_rider`, `consume_bonus_attack`,
  `is_misty_wanderer_ally_cell`, `misty_wanderer_ally_cell`, `tick_light_effects_for_turn`,
  `regenerate_portent_dice`, `activate_starry_form`, `deactivate_starry_form`,
  `activate_wrath_of_sea`, `deactivate_wrath_of_sea`, `apply_dragon_min_roll`.
- **Misplaced banners and comments** that S1 surfaces. If any are worth keeping as headings,
  re-add them in the new files as a separate comment-only commit.

## Success criteria

- `combat_riders.cpp` is gone. No combat TU holds two classes' features, and
  `combat_resources.cpp` holds only D3's shared code.
- The largest new file (Fighter) is about 1.2k lines, down from 4k.
- Adding a class feature touches that class's file, plus `combat.hpp` and a binding.
- The S3 proof passes, the build is clean, and `./test.sh` is 285/0 with goldens byte-identical.
