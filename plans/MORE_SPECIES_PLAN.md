# More Species — Plan

Drafted 2026-11-25. Follows `SPECIES_PLAN.md` (closed 7e4ed8d), which built the table-driven
species framework this plan extends. Sources: trait text pasted by the user, 2026-11-25.
Status: **Step 0 FROZEN 2026-11-25.** The user answered the open questions the same day; the
answers are folded into D3, D4, D6, D7, D8, D10, D13 and D14 below.

## Scope

Six species: **Aasimar, Hexblood, Lupin, Reborn, Bugbear, Fairy.**

- Aasimar, Hexblood, Lupin and Reborn use the 2024-format trait text (no ability scores).
- Bugbear and Fairy use the *Mordenkainen Presents: Monsters of the Multiverse* text. **Their
  ability score increases and languages are ignored**, the same as SP1 did for the SRD species
  (user, 2026-11-25). The general "Creating Your Character" boilerplate is not in scope.

## Where we start

The framework already exists (`memory/architecture_species.md`):

- `gui/species.hpp`: `kSpeciesTable` (Speed, Darkvision, size options, resistances, save
  bits, flags, options), `kSpeciesOptionTable` and `kSpeciesSpellTable`. **A new species is a
  table row. A new mechanic is a flag bit plus the engine code that reads it.** Flags in use
  run up to bit 17 (`kSpeciesLargeForm`).
- `set_species` / `restore_species` with the `SpeciesApplied` strip record.
- Sub-choices: `species_option`, `species_size`, `species_spell_ability` and `species_skill`,
  limited to the four modelled skills (`kSpeciesSkills`: Stealth, Perception, Sleight of Hand,
  Athletics).
- Granted spells, which cover free casts per Long Rest, unlock levels and the casting ability.
- Per-species pools on Stats that reset on a Long Rest.
- Reusable pieces:
  - flags `kSpeciesFeyAncestry` (Adv. vs Charmed) and `kSpeciesPowerfulBuild`;
  - the Draconic Flight pattern (fly = walk for N rounds, ends on Incapacitated);
  - `d20Test` for death saves;
  - `has_taken_turn_this_combat`, used by Assassinate;
  - `unarmed_damage_override`;
  - the once-per-turn `radiant_soul_used` pattern;
  - `bonus_reach_available` and the weapon's `reach_ft`;
  - the Grappler / Tavern Brawler "unarmed hit also does X" offers;
  - the creature-type flags `is_fey` and `is_celestial`;
  - Faerie Fire (SP6), Hex, and `conditionSaveAdvantage`.
- All five species spells are in `spells.json`: Light, Disguise Self, Hex, Druidcraft and
  Enlarge/Reduce. SP0 checks what each one does in the engine.

## Step 0 — decisions (FROZEN 2026-11-25)

- **D1 Creature type.** Add a `creature_type` column to `SpeciesDef`, defaulting to Humanoid.
  Hexblood and Fairy are **Fey**. `set_species` sets `is_fey`, records that it did so in
  `SpeciesApplied`, and the strip clears it only if it set it. Every other species stays
  Humanoid. Bugbear's goblinoid tag is flavor.
- **D2 Choice columns.** These reuse the existing pickers:
  - Size Small/Medium: Aasimar, Hexblood, Lupin and Reborn.
  - Fixed size: Bugbear is Medium and Fairy is Small.
  - `species_spell_ability` (INT, WIS or CHA): Hexblood and Fairy.
  - `species_option`: Reborn's Strange Endurance resistance (Cold, Necrotic or Poison).
  - `species_skill`: Lupin's Werewolf Instincts offers **Perception or Stealth**. Survival is
    not modelled; picking it is allowed and is flavor only. Reborn's Knowledge from a Past Life
    offers the four modelled skills, as Human Skillful does (D12 of the old plan).
- **D3 Passive table rows.**

  | Species | Size | Speed | Darkvision | Resistance | Other passives |
  |---|---|---|---|---|---|
  | Aasimar | S/M | 30 | 60 | Necrotic, Radiant | — |
  | Hexblood | S/M | 30 | 60 | — | Fey |
  | Lupin | S/M | 30 | 60 | — | skill (D2) |
  | Reborn | S/M | 30 | — | by option | Adv. on death saves; skill (D2) |
  | Bugbear | M | 30 | 60 | — | Fey Ancestry (existing flag), Powerful Build (existing flag), Stealth prof. |
  | Fairy | S | 30 | — | — | Fey; Flight (D11) |

  Bugbear Powerful Build only gives carrying capacity in the MotM text, so the existing flag's
  grapple-escape Advantage would be wrong for Bugbear. **The flag stays off**, and carrying
  capacity is not modelled (user, 2026-11-25).
- **D4 Granted spells** (rows in `kSpeciesSpellTable`):
  - Aasimar: Light, a cantrip cast with CHA.
  - Hexblood: Disguise Self and Hex, each 1 free cast per Long Rest, with the chosen ability.
    Both can also be cast with slots.
  - Fairy: Druidcraft (cantrip); Faerie Fire at level 3 and Enlarge/Reduce at level 5, each 1
    free cast per Long Rest, with the chosen ability; slots also work.

  Light, Disguise Self and Druidcraft are flavor (old D4): they are logged and spend their use.
  Light does **not** place a map light source (user, 2026-11-25).
- **D5 Healing Hands (Aasimar).** A Magic action that heals one creature within 5 ft by PB × d4.
  Once per Long Rest; tracked in `healing_hands_used`. It goes through the normal heal path, so
  `cant_heal` (Chill Touch) blocks it. Real-dice mode follows the existing heal-entry pattern.
- **D6 Celestial Revelation (Aasimar, level 3).** A bonus action with three options
  (Heavenly Wings, Inner Radiance or Necrotic Shroud), picked each time. It lasts 10 rounds and
  is once per Long Rest. **It ends only on a free dismiss or when the rounds run out.**
  Incapacitated or Unconscious does not end it, which is RAW and differs from Draconic Flight
  (user, 2026-11-25).
  - **Extra damage, all forms.** Once on each of the PC's turns, the first damaging attack or
    spell hit adds PB damage: Necrotic for Shroud, Radiant otherwise. It is applied
    automatically to the first target hit, using the `radiant_soul_used` per-turn pattern.
  - **Heavenly Wings.** `speed_fly = speed_walk` for the duration, using the Draconic Flight
    `fly_from` restore.
  - **Inner Radiance.** At the end of each of the PC's turns, each **non-ally** creature within
    10 ft takes PB Radiant damage. Allies are skipped (user, 2026-11-25; RAW says "each
    creature"). The bright and dim light is deferred to `known_limitations.md`, because light
    sources are map effects and none follows a token.
  - **Necrotic Shroud.** On transforming, each non-ally within 10 ft makes a CHA save against
    DC 8 + CHA mod + PB. On a failure it is Frightened until the end of the Aasimar's next turn,
    and condition-save Advantage (Brave etc.) applies.
- **D7 Hex Magic (Hexblood).** This is covered by D4: the engine's existing Hex does the work.
  **Eerie Token** (Distant Message, Remote Viewing) is flavor only, with no button (user,
  2026-11-25).
- **D8 Lupin Howl.** A bonus action, PB uses per Long Rest (`howl_used`). Each chosen creature
  within 15 ft makes a WIS save against DC 8 + CON mod + PB. On a failure it gets a new
  condition, `Howled`: Disadvantage on attack rolls and saving throws until the start of the
  Lupin's next turn. **Targets are every hostile in range, with no picker in v1** (user,
  2026-11-25). It is not a Frightened save, so condition-save Advantage does not apply.
- **D9 Lupin Feral Pounce.** Unarmed Strikes deal Slashing damage: a species default under
  `unarmed_damage_override`, which a Monk's override still beats. When an Unarmed Strike hits as
  part of the Attack action on the Lupin's turn, the engine also offers a **Shove** (push 5 ft or
  Prone, using the normal shove save) through the Grappler "punch-grab" offer pattern. Once per
  turn.
- **D10 Reborn Knowledge from a Past Life.** When an **engine-rolled** ability check fails, a
  PC with a use left gets a "Past Life +1d6?" prompt, which re-evaluates the same d20 plus 1d6.
  PB uses per Long Rest. Engine-rolled checks are the shove/grapple contests, the grapple
  escape, and the door and chest Athletics checks. Checks the DM rolls at the table are tracked
  only: a tracker button spends a use. In auto mode it is offered, not automatic, because
  spending a use is a choice (user, 2026-11-25).
- **D11 Fairy Flight.** `speed_fly = speed_walk` at all times, **except while the PC wears
  Medium or Heavy armor**, in which case the fly speed is 0. It is re-derived whenever armor or
  Speed changes. If armor categories are not on Stats, SP0 finds the closest signal.
- **D12 Bugbear Long-Limbed.** On its own turn, the Bugbear's melee attacks get +5 ft reach.
  Opportunity attacks off-turn do not get it. This goes in the reach check the attack path uses,
  not in `reach_ft` on the weapon.
- **D13 Bugbear Surprise Attack. Once per combat**, like the Assassin Rogue (user, 2026-11-25).
  A hit with an attack roll on a creature whose `has_taken_turn_this_combat` is false adds 2d6,
  of the weapon's or spell's damage type. Reuse as much of Assassinate as possible:
  - the same target test as the Assassinate Advantage (`combat_attack.cpp:2647`);
  - the `damage_breakdown` entry and log pattern of the Assassinate bonus damage
    (`combat_rogue.cpp:82`);
  - a new `surprise_attack_used` flag, reset where `has_taken_turn_this_combat` is reset at
    combat start (GUI `_start_combat`). Sneaky's squeeze through Small spaces has no grid effect for a 1-cell Medium
  token, so it is flavor.
- **D14 Deferred / flavor (→ `known_limitations.md`):**
  - Reborn Everlasting: exhaustion, sleep and the 4-hour rest (user, 2026-11-25: flavor);
  - Hexblood Eerie Token (flavor);
  - the Inner Radiance light source;
  - Bugbear Sneaky squeezing;
  - goblinoid tagging;
  - Survival as a Lupin skill.

## Steps

Per-step loop: implement → `./test.sh` in the container → fix → commit on request → handoff.

- **MS0 — Audit, no code.**
  - Record what Light, Disguise Self, Hex, Druidcraft and Enlarge/Reduce do in the engine.
  - Find where these hooks would go:
    - the reach check (D12);
    - the "hasn't acted" check (D13);
    - the unarmed-hit offer chain (D9);
    - every engine-rolled ability check (D10);
    - armor category on Stats (D11);
    - the death-save roll (Reborn);
    - an existing condition that gives Disadvantage on attacks and saves, to reuse for D8.
  - Confirm that Hold Person and the other Humanoid-only effects don't break for a Fey PC.
- **MS1 — Table rows and passives.** Done 2026-11-25 (296/0): Fairy Flight reads
  `Stats::armor_medium_heavy`, kept by `BattleMap::setAgentArmor`; the strip record gained
  `fey`, `fly_from` and `fly_to`; Lupin's skill list comes from `species_skill_options`.
  - Six `kSpeciesTable` rows; Reborn options in `kSpeciesOptionTable`.
  - The `creature_type` column and the `is_fey` apply/strip (D1).
  - Size, skill and spell-ability pickers (D2).
  - Celestial Resistance and Strange Endurance.
  - Bugbear Stealth and Fey Ancestry.
  - Reborn Advantage on death saves.
  - Fairy Flight with the armor gate (D11).
  - Tests: apply, strip and swap for each species.
- **MS2 — Granted spells (D4).**
  - Rows for Aasimar, Hexblood and Fairy, including the unlock levels.
  - Enlarge/Reduce mode picker at cast time (MS0 decision (a)), for every caster, not only
    Fairies.
  - Tests: free casts, slot casts, the casting ability, and the Fairy unlocks at levels 3 and 5.
- **MS3 — Bugbear and Reborn actives.**
  - Long-Limbed (D12) and Surprise Attack (D13), once per combat.
  - Knowledge from a Past Life (D10): the prompt, the pool and the tracker button.
- **MS4 — Lupin.**
  - Feral Pounce (D9).
  - Howl (D8) and the `Howled` condition, with tests for the DC, the duration and the uses.
- **MS5 — Aasimar actives.**
  - Healing Hands (D5).
  - Celestial Revelation (D6): the three forms, once-per-turn extra damage, the Inner Radiance
    end-of-turn tick and the Necrotic Shroud save.
  - Panel buttons. The panel golden must be regenerated.
- **MS6 — Import, generation and docs.**
  - `import_character.map_species`: map the D&D Beyond race names, including the legacy
    "Bugbear" and "Fairy" entries.
  - `party_gen` species roll.
  - `known_limitations.md` gets the D14 list.
  - Update `memory/architecture_species.md`.
- **MS7 — Live check.** A `run.sh` pass with one PC of each species, then close the plan.

## MS0 audit findings (2026-11-25)

Read-only. Paths are under `gui/`.

**Spells.**
- **Light, Disguise Self, Druidcraft.** In `spells.json` these are `Harm`/`Automatic` with no
  damage and no condition, so a cast does nothing beyond logging and spending the use. That
  fits D4's flavor treatment. All three are on the automation ignore list
  (`combat_turn.cpp:3266`). Wood Elf Druidcraft already goes through this path.
- **Hex** works. Casting it sets the marked-target rider to +1d6 Necrotic
  (`combat_spells.cpp:2814`). The Disadvantage on one ability's checks is not modelled.
- **Enlarge/Reduce only reduces.** `spells.json` lists the `Reduced` condition alone, and
  nothing ever applies `Enlarged`, even though apply and teardown handle both
  (`combat_conditions.cpp:1376`, `combat_spells.cpp:4375`). A Fairy can't enlarge itself or an
  ally. **Decided (user, 2026-11-25): option (a).** MS2 adds an Enlarge/Reduce mode picker at
  cast time. Enlarge applies `Enlarged` and needs no save on a willing target; Reduce keeps
  the current save path.

**Hooks.**
- **D12 reach.** `combat_attack.cpp:2572`, next to the Improved Shadow Step +5 ft. Add the
  Bugbear's +5 ft there for a melee weapon when the attacker is the active turn agent. The OA
  and threatened-reach scans (`combat_attack.cpp:170`) are not touched, which keeps the
  off-turn exclusion.
- **D13 Surprise Attack.**
  - Target test: `combat_attack.cpp:2652` (`!has_taken_turn_this_combat`).
  - Damage: Assassinate's line is `combat_rogue.cpp:85`. It adds flat damage straight to HP
    inside the Sneak Attack fold, so Surprise Attack copies its breakdown/log pattern but needs
    its own fold point.
  - Spell attacks: the spell-attack hit path (`combat_spells.cpp` ~196) also needs the hook.
  - Engine correction: Assassinate is gated by `round_num == 0` and has no used flag. The new
    `surprise_attack_used` flag resets in `app_initiative.py:520` (`start_combat`), where
    `has_taken_turn_this_combat` resets, and not in `main.py _start_combat`.
- **D9 Feral Pounce.**
  - **Correction:** `unarmed_damage_override` can't carry Slashing. It holds `MagicDamage_t`
    values only and is read only for `MonkUnarmed` with a Monk class
    (`combat_attack.cpp:401`, `:524`). Lupin needs its own physical-type swap
    (Bludgeoning → Slashing) on `Unarmed`/`MonkUnarmed` in the damage roll. An active Monk
    magic override still wins.
  - Shove offer: copy Grappler's flag at `combat_attack.cpp:3661`, with the same Attack-action
    and once-per-turn gates. Offer it in the `app_attacks.py:737` `elif` chain. That chain
    surfaces only one offer per hit, so when a Lupin Grappler hits, Punch-and-Grab takes
    precedence.
- **D10 engine-rolled checks** (all in `combat_contested.cpp` unless noted):
  - `executeShove` :46 and `resolveGrapple` :547, both contested;
  - `executeGrappleEscape` :651;
  - `attemptBreakDoor` :197 and `attemptPickLock` :131;
  - the chest checks: pick :418, break :451, find trap :479, disarm :512;
  - `escapeNet` (`combat_conditions.cpp:509`).
  
  `consumeStrengthenBonus` already adds a bonus to most of these (11 call sites), but D10 is
  a re-evaluation after a failure. Each check needs to return its d20, total and DC so that
  Python can offer the reroll.
- **D11 armor category.** Stats has no category field. The signal is the minimum
  `dex_mod_cap` over the six `getAgentArmor` slots: ≤ 2 means Medium or Heavy. This is the
  same loop as `rules.hpp:459`. Re-derive it wherever armor is set (`setAgentArmor`) and in
  `set_species`.
- **Reborn death saves.** There are two roll sites: `combat_turn.cpp:825` (on damage) and
  `:1436` (`rollDeathSave`). Each passes `hasFeat("Durable")` as the Advantage argument to
  `d20Test`. OR in the Reborn flag at both.
- **D8 Howled.**
  - No existing condition fits. The generic `has_disadvantage` is read at every attack and
    save site we need (`combat_attack.cpp:2635`, `combat_spells.cpp:196/353`,
    `combat_contested.cpp:343`, `combat_resources.cpp:255`, `combat_turn.cpp:3882/4006`), but
    it is a single shared bool. Darkness-blinding and vampire sunlight set and clear it
    (`combat_conditions.cpp:304/311`, `combat_turn.cpp:613/639`), so it would clobber Howled.
    It also covers ability checks, which Howl doesn't.
  - Plan: a new `howled_by` field (pattern: `grave_cursed_by`), ORed in next to
    `hasDisadvantage()` at those sites and cleared at the start of the Lupin's turn.
- **Fey PC vs Humanoid-only effects.**
  - No engine code gates on Humanoid. Hold Person, Charm Person and Dominate Person are not
    type-checked, so a Fey PC can still be targeted. Nothing breaks.
  - Readers of `is_fey`: the creature-type mask (`agent.hpp:794`), the `CT_*` bits that
    type-gated effects such as the Ward picker test, plus load/save (`agent_loader.py:48`,
    `app_persist.py:391`). That matches what D1 intends.

## Rules constants

| Species | Use pools |
|---|---|
| Aasimar | Healing Hands 1/LR; Celestial Revelation 1/LR (L3); Light at will |
| Hexblood | Disguise Self 1/LR, Hex 1/LR (free casts); Eerie Token flavor |
| Lupin | Howl PB/LR |
| Reborn | Past Life PB/LR |
| Bugbear | — |
| Fairy | Faerie Fire 1/LR (L3), Enlarge/Reduce 1/LR (L5) (free casts) |

DCs: Necrotic Shroud is 8 + CHA + PB. Howl is 8 + CON + PB.
