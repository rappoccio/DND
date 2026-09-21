# Bugs found in beta testing

* ~~Shields need to be allowed into Off Hand slot~~ DONE
* ~~Paladin classes are 2014?~~
* ~~Eldritch blast needs repelling blast Eldritch Invocation~~ DONE
* ~~Need to be able to turn off automatic detection of the maps, they're janky.~~ DONE
* ~~Need walls to be fully blacked out.~~ DONE
* ~~All actions need to be blocked after an Opportunity Attack possibly inflicts a condition like "stunned"~~ DONE — an OA that leaves the mover Incapacitated (Stunned/Paralyzed/…) now halts the move at the provoke cell and zeroes movement (Speed → 0); the GUI's Incapacitated action-gate then blocks all further actions this turn. Test: `test_oa_incapacitating_condition_halts_mover`.
* ~~The initiative tracker needs to scroll, not be cut off.~~ DONE (scrollable + auto-pages to follow the current turn)
* ~~Needs a "Show Terrain" button before combat starts.~~ DONE
* ~~Only show melee weapons for melee slots and ranged weapons for ranged slots~~
* ~~Healing word not showing up in spell list~~ DONE
* ~~OAs should not be triggered if there is a wall between agents~~ DONE — the OA threat check now applies the 5-ft corner rule: a diagonal reach is blocked when BOTH cells shared by the diagonal are walls (a sealed corner). The earlier `hasLineOfSight` guard was a no-op at 5-ft reach (a distance-1 diagonal's corner is flanked by the two endpoint cells, which LoS always excludes). Tests: `test_no_oa_through_a_walled_corner`, `test_open_corner_still_provokes`.
* ~~If you drop weapons, you cannot pick them back up again "No free weapon slot". ~~
* ~~When an agent is deleted from the map, the weapons are dropped and cannot be deleted.~~ DONE 
* ~~Cleave not working~~ DONE
* ~~Somehow I can walk on water~~ FIXED (crossed off by DM — resolved by another feature). Verified the engine already blocks it: `isBlocked` treats `TerrainType::Water` as impassable to Walk/Burrow (passable only to Swim/Fly/Jump), enforced on every movement path (Dijkstra commit in `moveAgent`, the `reachableCells` preview that gates the drag, and the NPC driver); a painted "Water" region survives the terrain save/load round-trip. The live case was water not painted as the Water terrain type.
* ~~Movement "turns off" mid-turn for a grappler even after a Cunning-Action Dash~~ DONE (grapple drag-surcharge was charged against a separate budget that ignored Dash; now 2× cost charged against the single agent budget — working as intended: dragging halves your reach)
* ~~Incapacitated condition does not get movement speed restored after it clears.~~ DONE — `applyIncapacitated` (shared by Paralyzed/Stunned/Incapacitated) sets Speed→0, but the `onConditionEnded` teardown cleared only the flag and never gave the Speed back, so a creature whose movement budget had been zeroed (e.g. the OA-inflicts-Stun-mid-move path) stayed at 0 movement after the condition cleared. New `restoreMovementAfterIncapacitation()` re-seeds both the Stats remaining-speeds and the Agent's own budget from base speeds on the teardown. Test: `tests/test_incapacitated_movement_restore.py`.
* ~~We need a "immune to disarm" property, especially for our Unarmed "weapons" (that aren't weapons)~~
* ~~Barbarian movement somehow being incremented.~~ 
* ~~Need to be able to Drop Grapple targets.~~
* ~~Multiple target AOE spells should use one single roll for all damaged targets.~~ DONE
* ~~Healing Word not upcasting correctly.~~ DONE
* ~~Spirit Guardians damage at end of turn?~~ VERIFIED CORRECT — damage lands at the START of a creature's turn (default `effects_on_begin_turn`) plus on entering the zone; the "end of turn" read is a GUI perception effect (ending your turn immediately runs the next creature's `beginTurn`, so its tick logs right after).
* ~~True Strike damage not keyed off of spellcasting modifier.~~
* ~~Sanctuary is somehow healing targets, but also not forcing the WIS save.~~ DONE
* ~~Hew is being triggered, but i think it is silent. I don't get a popup for an extra attack.~~ DONE
* ~~Homogenize Command to give the same popup as Mantle of Majesty for Bards.~~  DONE
* ~~Need to fix the Spells interface to make the buttons actually fit on the screen (rows?)~~
* ~~Dash not counting as an action? ~~
* ~~Cleave is not working for large targets. It needs to check EACH cell within an agent's footprint.~~ DONE 
* ~~Branches of the World Tree popup window is blocked by the Vitality of the World Tree popup window on the Barbarian's turn.~~ DONE 
* ~~Potions not healing / "Use Item" not spending the Bonus Action~~ DONE — the engine was correct all along. Three GUI faults: (1) no target prompt after picking the item (see next entry), so no target was ever clicked; (2) a potion drunk at **full HP** rolled its dice, healed 0, and still burned the charge + Bonus Action — now refused before it costs anything; (3) every use was logged **twice** (the GUI re-narrated what the engine already logged) — the GUI now only reports the last charge being used.
* `self.hint` in `main.py` is assigned by ~15 target-pick flows and **rendered nowhere** — those features print no "click a target" direction at all. Known sites: Flurry of Blows, Lay on Hands, Bardic Inspiration, Mantle of Inspiration, Hand of Healing, Telekinetic Movement, Escape Net, Command, Psychic Teleportation, Shadow Step, Shadow Arts: Darkness, Steps of the Fey, Misty Escape, Bewitching Magic, Elemental Burst, Wild Magic Teleport. (Use Item is fixed: it now routes its prompt through `_combat_log_add`.) Fix wholesale by either rendering `hint` in the combat panel's "Pending action hints" block (~`main.py:16524`, which today hand-rolls prompts for attacks/spells only) or converting all sites to combat-log prompts.
* Several `pending_*` target-pick flags are cleared in `_start_combat`/`_end_combat` but **not** in `_proceed_to_new_turn`, so a target-pick armed on one turn leaks into later turns and can swallow the next map click (`pending_cleave`, `pending_sweep`, `pending_rally`, `pending_feint`, `pending_mantle_active`, `pending_clairvoyant`, `pending_vow_of_enmity`, `pending_inspiring_smite`, `pending_use_item`, …). The same class of bug was already patched one-off for `pending_vitality_target` and `pending_beguiling` — worth a single defensive clear at turn start instead.
* ~~Sanctuary seems to not be triggering Wisdom save~~
* ~~Hold Person saves at the END of each turn, not beginning~~ DONE — RAW is end-of-turn; new `save_at_end_of_turn` flag: `beginTurn` skips the save (creature still can't act), `endTurn` rolls it, a success frees the creature next turn. Set on Hold Person + Hold Monster. Test: `tests/test_hold_person_endturn.py`.
* ~~Warding Flare gives 2d6+WIS temp HP~~ VERIFIED CORRECT — 2024 Improved Warding Flare (L6) grants 2d6+WIS temp HP; working as intended.
* ~~State not being saved for current spell slots~~
* ~~Check interplay of Warding Flare with Sanctuary. Warding Flare is not a spell so should be allowable under Sanctuary.~~
* ~~DEX modifier is not accurately being added to AC.~~ DONE — the weapon-attack path (`resolveAttack`) read the target's raw `base_ac`, so a PC's DEX never reached the to-hit roll (spell/Cleave paths already used `calculateAC`). Now `resolveAttack` targets `calculateAC`; DEX/armor/shield/feat layering is gated on `!is_npc` (NPC `base_ac` is the published final AC with DEX already baked in — re-adding would double-count). Also fixes a latent DEX over-add on spells vs monsters. Test: `tests/test_ac_dex.py`. 