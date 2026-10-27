# Cantrip damage scaling — handoff

**Status:** not started. Written 2026-10-27, right after Blade Ward / Booming Blade (`5b86eca`).

## The gap

The engine never scales cantrip damage with character level. Fire Bolt does 1d10 at level 1
and at level 20. The only cantrips that scale today do it by hand:

- **Eldritch Blast**: beam count, in `getNumTargetsForSpell` (`gui/combat_spells.cpp`, search
  "Eldritch Blast beams scale").
- **Booming Blade**: its own tier math inside its `executeSpell` block (search
  `sp.name == "Booming Blade"`).

`upcast_dice_bonus` doesn't help. It scales by *slot* level above the spell's level, and a
cantrip is cast with `slot_level` 0.

## Rule (2024 PHB / SRD 5.2)

A damaging cantrip gets **one more damage die at character levels 5, 11 and 17** (tier 0–3).
"Character level" means total level across classes: `Agent::Stats::totalLevel()`.

## Which spells (`gui/spells.json`, `level == 0`)

| Behaviour | Spells |
|---|---|
| +1 die per tier (the common case) | Acid Splash (d6), Chill Touch (d10), Fire Bolt (d10), Poison Spray (d12), Produce Flame (d8), Ray of Frost (d8), Sacred Flame (d8), Shocking Grasp (d8), Sorcerous Burst (d8), Starry Wisp (d8), Vicious Mockery (d6), Mind Sliver (d6) |
| Special: extra Radiant on the weapon hit, 1d6/2d6/3d6 at 5/11/17 | True Strike (hand-rolled attack in `executeSpell`, search `sp.name == "True Strike"`) |
| Special: damage die changes d8 → d10 → d12 → 2d6 | Shillelagh (check how it's implemented today before touching it) |
| Already done, leave alone | Eldritch Blast, Booming Blade |
| **Must NOT scale** | Every monster pseudo-spell stored as level 0: `Breath*`, `BalorEmanation`, `BalorDeathThroes`, `ZombieClotEmanation`, `RahadinDeathlyChoir`, `PitFiendFearAura`, `Misty Escape`, the Curses, … |

That last row is why scaling has to be **opt-in per spell**, not "every level-0 spell with
damage dice".

## Recommended design

1. **Add a data field**, `cantrip_dice_per_tier` (int, default 0), to `Spell`. Set it to 1 on
   the twelve common-case cantrips above. A new field has to be added in every place spells
   are defined, loaded or saved:
   - `gui/spell.hpp` (the field, next to `upcast_dice_bonus`)
   - `gui/map_configs.cpp` (C++ JSON load, `j.value("cantrip_dice_per_tier", 0)`)
   - `gui/serialization_mappings.hpp` (snapshot field list)
   - `gui/bind_types.cpp` (`def_readwrite`)
   - `gui/helpers.py` (spell template default near line 799, plus `_dict_to_spell` near line 980)
   - `gui/main.py` spell→dict save (search "Convert magic_damage_rolls to dict format"), so
     custom spells keep the field when saved and reloaded
   - Clear Mind Sliver's meaningless `"upcast_dice_bonus": 1` while you're in there.
2. **Apply it in `executeSpell`**, right next to the upcast block (search "Upcast
   damage/healing scaling"). It works on the local `sp` copy, so every branch (attack, save,
   automatic, Chromatic-Orb-style leaps, Potent Cantrip, Empowered Evocation) sees the bigger
   dice pool with no further changes:
   ```cpp
   if (sp.level == 0 && sp.cantrip_dice_per_tier > 0) {
       const int lvl  = caster_stats.totalLevel();
       const int tier = lvl >= 17 ? 3 : lvl >= 11 ? 2 : lvl >= 5 ? 1 : 0;
       // add tier * cantrip_dice_per_tier to each magic (else physical) damage roll; log it
   }
   ```
   Booming Blade already computes the same tier. Pull out one helper
   (`cantripTier(const Agent::Stats&)`) and use it in both places.
3. **True Strike:** add the 1d6/2d6/3d6 Radiant on a hit inside its existing block.
4. **Shillelagh:** look at how it's implemented first, then apply the die change there.
5. **NPC AI:** `npcSpellAvgDamage` (`gui/combat_turn.cpp`) reads raw `magic_damage_rolls`. It
   only ranks AoE spells, so the only scaling cantrip it sees is Acid Splash. Optional to fix.
6. **Display (optional):** the cast menu and any tooltip that prints a cantrip's dice will
   still show the base die. Check `main.py` and `menus/`.

## Open decision for the user

**NPCs without class levels** (stat-block monsters with a Spellcasting list) have
`totalLevel() == 0`, so with this design their cantrips stay at tier 0. Options: leave them
alone (recommended: it's what the code naturally does), or derive a level from CR. Ask before
building the CR option.

## Separate bug spotted (out of scope)

**Vicious Mockery** is authored as `"attack_type": "AttackRoll"`. In 2024 it's a **Wisdom
save**: 1d6 Psychic, and on a failed save the target has Disadvantage on its next attack roll
before the end of its next turn. Fix it on its own, or with this work if the user agrees.

## Tests

- New suite (pattern: `tests/test_spells_tier1.py`, which loads spells from `spells.json` via
  `helpers._dict_to_spell`). Set levels with `stats.set_class_level(rpg.CharacterClass.Wizard, n)`.
  Cover:
  - levels 1/5/11/17 for an attack cantrip (Fire Bolt), a save cantrip (Sacred Flame) and
    Acid Splash, checking `len(tr.dice_results)` (doubled on a crit for attack rolls)
  - a monster level-0 entry (e.g. `BreathFireConeLow`) cast by a level-17 caster that does
    **not** scale
  - multiclass: Wizard 3 / Cleric 2 is tier 1
- Register it in `tests/run_all_tests.py`.
- **Expect fallout in existing suites.** Any test that casts a cantrip from a caster at level
  5 or higher and checks a damage range or an RNG-sensitive outcome will shift. That includes
  the determinism/golden replay tests, because the extra dice consume extra RNG draws. Treat
  each failure on its merits: update expectations that encoded the old (wrong) damage, and
  don't paper over real regressions.
- Pure-data edits need no suite run; the C++ changes do.

## Running things

All builds and tests run in the `rpg_map` container, never on the macOS host (see
`CLAUDE.md`):

```bash
./build.sh
./test.sh
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd /home/user/Claude/DND/gui && python3 ../tests/test_cantrip_scaling.py"
```

Opus may build and test. Sonnet and Haiku must not: hand these lines back to the user.
Commit only when asked, staging files by name. Never push unasked.
