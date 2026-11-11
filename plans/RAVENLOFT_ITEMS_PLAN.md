# Ravenloft Items Plan

The ask (user, 2026-11-10): *"read ITEMS_TO_ADD_TO_RAVENLOFT.md and add those items and weapons."*
Source list: `plans/ITEMS_TO_ADD_TO_RAVENLOFT.md` (11 entries, with the user's simplifications).

Builds on `ENSPELLED_ITEMS_PLAN.md` (item spells, N/day groups, charge pools, attunement, DC
override) and `SPELL_SCROLLS_PLAN.md`. About half of the list is expressible in that machinery
today; the rest needs the new mechanics M1–M11 below.

## Step 0: decisions (frozen 2026-11-10)

Touches no source. Frozen: changes need a dated amendment with a reason, agreed by the user.

### What exists vs. what is new

| Item | Works today (data only) | Needs |
|------|------------------------|-------|
| **+2 Shield of Initiative** | +4 AC shield (`ac_bonus` 4) | M1 initiative bonus |
| **Helm of Brilliance** | Daylight 3/day, Fireball 3/day, Prismatic Spray 1/day, Wall of Fire 1/day at DC 18; Fire resistance (authored as worn armor, like *Fire Resistant Cloak*) | M4 undead aura 1d6 Radiant; M5 flame weapon +1d6 Fire (light postponed) |
| **Rod of the Pact Keeper** | n/a | M1 Warlock spell attack/DC bonus; M10 regain one slot 1/long rest |
| **Potion of Heroism** | n/a | M11: 10 temp HP + a no-concentration Bless copy for 1 hour |
| **Yarik's Shortsword** | Shortsword +1 | M8 Crusader's Mantle (not in `spells.json`) |
| **Saint Markovia's Thighbone** | Mace, Sap mastery, attunement flag | M2 +2d6 Radiant vs Fiend/Undead; M8 "Disruption" 1/day spell (DC 15 WIS; fail: 25 Radiant; success: Frightened to end of next turn) |
| **Staff of Power** | Quarterstaff +2; pool of 10 charges refilled on long rest; costs per the table (Cone of Cold 5, Fireball 5, Globe 6, Hold Monster 5, Levitate 2, Lightning Bolt 5, Magic Missile 1, Ray of Enfeeblement 1, Wall of Force 5) | M1 +2 AC, saves, spell attack. Fireball and Lightning Bolt cast at base level (3rd), not 5th: enspelled D6 limitation |
| **Luck Blade** | +1 weapon | M1 +1 saves; M6 one luck point per day; Wish left out (M7: the DM places Scrolls of Wish) |
| **Vicious weapons** (2024: +2d6 of the weapon's own damage type on every hit) | A Vicious variant per weapon: one extra 2d6 `physical_damage_types` entry | nothing |
| **Scrolls** (Cone of Cold, Fireball, Lightning Bolt) | **Already supported.** The DM makes each one from the item picker (SS2). Nothing to add to the catalog | Q6: pre-place them somewhere? |
| **Holy Symbol of Ravenkind** | pool of 10 charges, attunement | M8 Hold Vampires (1 charge). Postponed: Turn Undead empowerment (M9) and Sunlight (M3) |
| **Sunsword** | Longsword +2, Finesse, Radiant damage instead of Slashing, Sap, attunement | M2 +1d8 Radiant vs Undead. Postponed: sunlight 15/15 (M3) |

### New mechanics (user's sizing, 2026-11-10)

| # | Mechanic | Sketch | Size |
|---|----------|--------|------|
| M1 | **Passive bonuses from items.** | `item_bonuses` on Item/Weapon/Armor: `ac`, `initiative`, `saves`, `spell_attack`, `spell_dc`, optional `spell_class` (Rod = "Warlock"). Active while carried (enspelled D9) and attuned when required (D5). | Easy, possibly JSON only. First check which bonuses already have a hook (AC does: `ac_bonus`). |
| M2 | **Extra weapon damage, optionally vs a creature type.** | Extra dice are just another entry in the weapon's existing `magic_damage_types` / `physical_damage_types` (e.g. `{"type": "Radiant", "num_dice": 2, "die_size": 6}`). **Vicious weapons** need no code: add a 2d6 entry of the weapon's own type to `physical_damage_types`. The only C++ is the creature-type case: an optional `vs_creature_types` on a damage entry (`["Fiend","Undead"]`, checked against `is_undead` / `is_fiend`), so the entry is rolled only against those targets. | Vicious: data only. Vs type: small C++ |
| M3 | **Items that shed light.** | | **Postponed.** Thighbone, Sunsword and the flame-weapon light ship without light. |
| M4 | **Helm undead aura.** | An at-will item spell modeled on `ZombieClotEmanation` (`moves_with_caster`, `duration` 99, radius 30, 1d6 Radiant, Automatic) and Sear Undead. Needs one new spell field restricting targets to Undead, since no spell has a creature-type filter today. | Small |
| M5 | **Flame weapon.** | +1d6 Fire on hit, modeled on Hex's extra damage: an at-will Helm item spell. Light postponed with M3. | Likely data only |
| M6 | **Item luck point.** | 1 Luck Point per long rest, spent through the existing Lucky code (`luck_points`, `foldHeldAdvantage`). | Reuse |
| M7 | **Wish on the Luck Blade.** | **Dropped** (user, 2026-11-10): the item carries no Wish; the DM places Scrolls of Wish separately. | None |
| M8 | **New spell records.** | `Crusader's Mantle` is added (30 ft aura, allies' weapon hits +1d4 Radiant, concentration). Also `Disruption` (Thighbone, item-only, Fiend/Undead, DC 15 WIS: fail 25 Radiant, success Frightened to end of next turn; needs "condition on a successful save"), and the Holy Symbol's `Hold Vampires` (vampires only, DC 15 WIS, Paralyzed 1 min, repeat save). Sunlight is postponed with M3. | Medium |
| M9 | **Turn Undead empowerment.** | | **Postponed.** |
| M10 | **Rod slot regain.** | A Magic action, 1/long rest: regain one expended slot (the pact slot for a Warlock). | Python only? Confirm the slot-restore call is already bound. |
| M11 | **Potion of Heroism.** | 10 temp HP, plus a copy of Bless (`Bless (Potion of Heroism)`) with `requires_concentration: false`, self only, duration 600 rounds. | Easy |

### Simplifications taken from your notes (and two of mine)

- Helm: gems become uses/day (your plan). The "Taking Fire Damage" self-destruct is **dropped**, since there are no gems left to count.
- Staff: 10 charges, refilled in full at dawn; no last-charge d20 roll (your plan).
- Thighbone: never dissolves; the destroy effect becomes the 1/day Disruption spell (your plan).
- Sunsword: the blade is always on (no Bonus Action toggle) and the radius is fixed at 15/15. Sentience is description text only. *(mine)*
- Holy Symbol: the "good-aligned cleric or paladin" requirement is left to the DM's Attuned tick. *(mine)*

### Answers (user, 2026-11-10)

| # | Question | Answer |
|---|----------|--------|
| Q1 | Rod of the Pact Keeper rarity | **All three**: Rod of the Pact Keeper +1 (Uncommon), +2 (Rare), +3 (Very Rare), as separate entries |
| Q2 | Yarik's Shortsword | Crusader's Mantle **1/day**, concentration kept |
| Q3 | Luck Blade base weapon | Any weapon can have a Luck variant; **start with Longsword** (`Luck Blade (Longsword)`) |
| Q4 | Holy Symbol recharge | **Full 10** at dawn (long rest) |
| Q5 | Disruption | **Model it on `Shining Smite`** (user, 2026-11-10): a Frightening smite, item-granted 1/day at DC 15 WIS. Fail: 25 Radiant. Success: Frightened until the end of the wielder's next turn. Fiend/Undead targets only. |
| Q6 | Scrolls | **Left out.** Everything goes into the catalog files (`items.json`, `weapons.json`, `armor.json`, `spells.json`); nothing is pre-placed in an encounter. |
| Q7 | Holy Symbol | **Ship now** with Hold Vampires only |
| Q8 | Vicious weapons | A `<Weapon> (Vicious)` variant for **every base weapon** |

## Postponed (not in this plan)

- M3 item light (Thighbone 20/20, Sunsword sunlight 15/15, flame weapon 10/10, Holy Symbol Sunlight).
- M9 Turn Undead empowerment.

## Steps (after sign-off)

| # | Step | Status |
|---|------|--------|
| RI1 | **Data-only entries**: everything in the "works today" column, including the Vicious weapons, with descriptions; the new fields are not authored yet. Tests: each entry parses; Staff pool costs gate; Helm uses/day and DC 18. | done 2026-11-10: `weapons.json` Shield of Initiative +2 (AC 4), Saint Markovia's Thighbone, Staff of Power (pool 10), Luck Blade (Longsword), Sunsword, Yarik's Shortsword, and 38 `<Weapon> (Vicious)`; `armor.json` Helm of Brilliance (worn helmet, Fire resistance, DC 18, 3/day + 1/day); `items.json` Holy Symbol of Ravenkind (10-charge pool, spells in RI5). Weapon descriptions ride in the JSON (the Weapon struct has no description field). `test_ravenloft_items.py`; suite 243/0 |
| RI2 | **M1 passive bonuses**, then the Shield, Staff, Luck Blade and Rod bonuses. Tests per bonus, plus attunement gating. | done 2026-11-10: `ItemBonuses` (ac, initiative, saves, spell_attack, spell_dc, spell_class) on `ItemSpells`, JSON `item_bonuses`; `rules::carriedItemBonuses` sums carried + attuned-or-free items into `calculateAC` (NPCs too), `saveModFor` (+ the NPC save estimate), both initiative rolls, `spellSaveDcFor` / `spellAttackModFor` (True Strike, spell-condition DCs, Counterspell, the NPC cast log). A class-limited bonus (the Rod) needs that class and skips spells cast from another item. `ItemSpells.magical()` so an attunement-only item (Sunsword) keeps its Attuned tick and toggle; summary line `+2 AC, +2 saves, +2 spell attack` on the side panel, item rows and player sheet; `carried_item_bonuses` binding. Data: Shield +2 Initiative, Staff +2 AC/saves/spell attack, Luck Blade +1 saves, `Rod of the Pact Keeper +1/+2/+3` (items.json; slot regain in RI6). `test_ravenloft_bonuses.py`; suite 244/0 |
| RI3 | **M2**: damage vs creature type; the Sunsword and Thighbone weapon stats done. | done 2026-11-10: `vs_creature_mask` on `MagicDamageRoll` / `PhysicalDamageRoll` (JSON `vs_creature_types`), skipped in `rollDamage` and the NPC damage estimate against other types; round-trips through the weapon dicts. Sunsword +1d8 Radiant vs Undead, Thighbone +2d6 Radiant vs Fiend/Undead. `test_ravenloft_damage.py`; suite 245/0 |
| RI4 | **M4 + M5**: Helm aura and flame weapon; the Helm done. | done 2026-11-10: spell field `affects_creature_types` (`Spell.affects_creature_mask`) filters `resolveAoeTargets`, direct targets and `zoneSparesTarget`; new `CreatureType.Vampire` bit (`is_vampire`). Item-only spells `Diamond Light` (30-ft Undead-only Emanation, 1d6 Radiant at turn start; `effects_on_enter` false now also skips the emanation sweep) and `Fire Opal Flames` (spell field `weapon_rider` → `Stats.weapon_rider_*`: +1d6 Fire on held-weapon hits, 99 rounds, counts down at turn start, cleared on long rest). Helm grants both at will. `Spell` JSON mapping split over two field lists (nlohmann's 63-member macro limit); snapshot coverage test reads both. Wish list count 393 → 395. `test_ravenloft_helm.py`; suite 246/0 |
| RI5 | **M8**: Crusader's Mantle, Disruption, Hold Vampires; Yarik's Shortsword, the Thighbone and the Holy Symbol (minus postponed parts) done. | done 2026-11-10: spell field `no_damage_on_save` and condition flag `applies_on_save_success`. `Disruption` (Shining Smite-style: action + bonus, reach 5, Fiend/Undead only, WIS save: 25 Radiant on a failure, nothing + Frightened on a success; Thighbone 1/day, DC 15). `Hold Vampires` (30-ft Emanation, vampires only via the RI4 Vampire bit, Paralyzed 10 rounds, save at end of turn; Holy Symbol 1 charge, DC 15). `Crusader's Mantle` (Paladin, 30-ft concentration Emanation carrying a `weapon_rider` 1d4 Radiant: `rules::weaponRiderAura` gives it to the caster and allies inside on weapon and unarmed hits, stacking with a personal rider; Yarik's Shortsword 1/day). Wish list count 395 → 398. `test_ravenloft_spells.py`; suite 247/0 |
| RI6 | **M6, M7, M10, M11**: Luck Blade luck, Rod slot regain, Potion of Heroism. | |
| RI7 | **NPC automation pass** (NPCs use item bonuses and spells through the existing chooser) + **live check**, then `known_limitations.md`. | |
