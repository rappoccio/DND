# Multiclass Completion Plan

**Status:** D1–D9 signed off and **FROZEN 2026-11-16**. Changes need a dated amendment with a
reason. Step 0 complete 2026-11-16. Amendments A2 and A3 were accepted the same
day (D6 and D9 below are amended). **Ready for MC1 on the user's go.**

## Where we are

The engine half of multiclassing is done (`plans/archive/MULTICLASSING_PLAN.md`,
Phases 0–5, commits 93bd7c7 and 4acf69f):

- `Stats::class_levels` is the source of truth; `hasClass` / `lacksClass` / `classLevel` /
  `totalLevel` exist and are bound.
- All C++ class-identity gates go through `hasClass`; class-level gates use `classLevel`.
- Multiclass spell slots (`computeMulticlassSlots`) and resource merging
  (`initializeMulticlassResources`) work.
- `StatsDialog` edits a multiclass build; saves carry `agent_class_levels`.
- Four suites cover it: `test_multiclass_{gates,slots,resources,gui_roundtrip}.py`.

What's broken or missing, measured 2026-11-16:

| # | Gap | Evidence | Effect |
|---|---|---|---|
| G1 | **The Python layer is still single-class.** About 85 `.character_class ==/!=` and `.char_level >= N` reads in `main.py` (47), `menus/features.py` (14), `actions.py` (13), `menus/board.py` (6), `menus/riders.py` (4), `arena.py` (1). | e.g. `menus/features.py:81` Arcane Ward gate, `actions.py:451` Wizard menu, `main.py:9657` Second Wind heals by `char_level` | `character_class` mirrors the **lowest-enum** class. A Wizard 7 / Fighter 1 shows up as a *Fighter*, so every Wizard button disappears. Level gates read total level: a Fighter 1 / Monk 10 gets Fighter 11 features. |
| G2 | **A C++ leak was added after the sweep.** `combat_turn.cpp:3919` uses `getRageDamageBonus(as.char_level)`. | grep | A Fighter 10 / Barbarian 1 rages for +3 instead of +2. No test catches a regression like this one. |
| G3 | **There's only one spellcasting ability.** `Stats::spellcasting_ability` is a single int, read at about 51 C++ sites. | `agent.hpp:195` | A Cleric/Wizard casts everything off one stat. Also the root of the Rod of the Pact Keeper limitation in `known_limitations.md`. |
| G4 | **No Pact Magic pool alongside other slots.** It was deferred in the old Phase 3. | archive plan, Phase 3 status | A Warlock/Sorcerer or Warlock/Paladin loses its Pact slots completely. |
| G5 | **The DDB importer drops the secondary classes.** | `tools/import_character.py:410` warns and keeps only the highest class | Our two real multiclass PCs import wrong: **Ezmerelda** (Wizard 7 / Fighter 1) and **Keef Girgo** (Ranger 5 / Rogue 1). |
| G6 | **Displays show one class.** | `menus/board.py:43`, `main.py:11010` | The panel reads "Fighter 8", not "Wizard 7 / Fighter 1". |
| G7 | **Rule interactions nobody has audited.** Unarmored Defense from two classes (2024: you can't gain it a second time), Channel Divinity uses (Cleric + Paladin), starting proficiencies and saving throws (first class only), Extra Attack not stacking (done) | not checked | Unknown. Step 0 measures it. |

## Decisions (frozen 2026-11-16)

- **D1 Ruleset.** ✅ Use the 2024 PHB multiclassing rules.
- **D2 Prerequisites.** ✅ The 13-in-primary-ability prerequisite is **warned, not blocked**.
  This is a DM tool, and the DM can override anything.
- **D3 Python gates follow the C++ discipline.** ✅ Every Python site is judged individually and
  classified as class identity → `has_class`, class level → `class_level(C)`, total level →
  `total_level()`, or display. There is no blind sweep. Once the sweep is done, nothing outside
  the mirror machinery reads `character_class` / `char_level`.
- **D4 Regression guard.** ✅ A new test scans engine and GUI source for `char_level` /
  `character_class` reads outside an explicit allowlist (mirror plumbing, cantrip scaling,
  serialization). This is the backstop the old Phase 2 lacked, and it is what would have caught
  G2.
- **D5 Spellcasting ability by source class (G3).** ✅ Each known spell carries its **source
  class**. `spellAbilityFor(spell)` returns that class's casting ability; `spellSaveDcFor` and
  `spellAttackFor` build on it and replace direct reads of `spellcasting_ability`. A spell with no
  tag falls back to the current field, so every single-class save is unchanged. Classes that
  share a stat (Ranger, Monk, Cleric are all WIS) resolve to the same ability without any
  conflict. The Rod of the Pact Keeper bonus then applies to Warlock spells only.
  *(Briefly amended to "store the ability per spell" and reverted the same day: an ability tag
  can't tell a Warlock's CHA spells from a Sorcerer's.)*
- **D6 Pact pool (G4).** ✅ *Amended 2026-11-16 (A3).* Add a separate `pact_slots_max/remaining`
  pool (plus its slot level) for **every** Warlock, single-class included. Regular slots hold
  only non-Warlock casting. A multiclass caster chooses the pool when casting (Pact slots are
  always cast at the Pact level). A legacy Warlock save's `spell_slots_*` loads into the Pact
  pool. *Reason:* one code path instead of a multiclass branch at every pact site.
- **D7 Importer (G5).** ✅ Import every DDB class into `agent_class_levels`, with each class's
  subclass. Each spell is tagged with its DDB source class (this feeds D5).
- **D8 Out of scope:** ✅ HP by hit dice (still authored or imported), spells-known/prepared
  bookkeeping, `party_gen` multiclass parties, and the ML observation vector.
- **D9 Starting class.** ✅ *Amended 2026-11-16 (A2).* Add `Stats::starting_class` (saved as
  `agent_starting_class`). The importer fills it from DDB `isStartingClass`, the Stats dialog uses
  the first class entered, and a legacy save uses the primary mirror. `applyClassResources`
  grants chassis saving throws only for the starting class. Feature saves (Slippery Mind,
  Disciplined Survival…) stay per class. The `character_class` mirror stays for legacy load only.
  *Reason:* Step 0 found that the engine ORs in every class's chassis saves. RAW gives them
  from the first class only.

## Step 0 — before any code (touches no source; agreed list is frozen)

| ✓ | Step | Output |
|---|---|---|
| [x] | 0.1 Inventory every Python `character_class` / `char_level` read: file:line, feature, category (D3), and its replacement. | Worklist table appended here |
| [x] | 0.2 Re-grep the C++ for `char_level` / `.character_class` added since 4acf69f, and classify each. | Same table |
| [x] | 0.3 Inventory the `spellcasting_ability` read sites (about 51) and every place a spell list is authored or serialized. Size D5. | Site count + touch list |
| [x] | 0.4 Inventory the Pact-slot consumption sites. Size D6. | Site list |
| [x] | 0.5 Audit the G7 rule interactions, with the RAW answer and the engine's current behavior for each. | Table |
| [x] | 0.6 Write expected-behavior oracles for Ezmerelda (Wiz 7 / Ftr 1) and Keef (Rgr 5 / Rog 1): menus present, gates, slots, DCs, resources. | Becomes `test_multiclass_pcs.py` in MC1 |
| [x] | 0.7 The user signs off D1–D9, and amends whatever is wrong. | Frozen 2026-11-16 |

## Step 0 findings (2026-11-16)

### 0.1 Python worklist (≈180 lines, not 85)

The first count missed aliases. `actions.py:661` binds `cls`/`lvl` once, and the bonus-action
menu then gates about 85 more lines on them (`actions.py:694–1128`). Every site is listed below
by category (D3). The class named is the one the replacement reads. "Guard" means the class
comes from the adjacent `== CC.X` check.

| Category | Sites | Replacement |
|---|---|---|
| **Class identity** | `actions.py` 451, 490, 573, 580, 634, 661 (`cls ==` ×~30 through 1128); `menus/board.py` 244, 273; `menus/features.py` 57, 81, 111, 272, 296, 521, 554; `main.py` 5153, 5980, 8012, 8980, 9171, 9206, 9363, 10091, 11820, 12184, 16634, 16638, 16644, 19584, 20620, 20947, 21250 | `has_class(C)` |
| **Class level, from the guard** | `actions.py` 210, 491, 575, 581, `lvl` ×~55 in 694–1128; `menus/board.py` 248 (Wizard), 275 (Warlock); `menus/features.py` 83, 111, 274, 522, 555; `main.py` 5982, 8981/8992 (Cleric), 9172 (Rogue), 9208 (Fighter), 9365 (Rogue), 10093 (Fighter), 11822 (Sorcerer), 12186 (Warlock), 19584/19588 (Paladin), 20622 (Monk), 21251 (Sorcerer) | `class_level(C)` |
| **Class level, subclass-only gate (no class check nearby)** | `actions.py` 262 + `main.py` 20431 (Steps of the Fey → Warlock); `menus/features.py` 89 + `main.py` 9400 (Arcane Ward max → Wizard); `menus/features.py` 141 (Wild Shape CR → Druid), 337 + `main.py` 10751 (Glamour → Bard); `main.py` 9657/9667 (Second Wind → **Fighter**), 13063/13089/20216 (Duplicity → Cleric), 13175 (Primal Companion → Ranger), 13293 (Chain Master → Warlock); `menus/riders.py` 24 (Brutal Strike → Barbarian), 323/349 (Hand of Harm → Monk), 547 (Cunning Strike → Rogue) | `class_level(C)`. These are the ones a blind sweep would get wrong. |
| **Total level (correct as is)** | `main.py` 4685–4703 (origin feat HP), 5760/5786 (XP / level-up), 11583 (`get_num_targets_for_spell`, matching the C++), `sim_trace.py` 120–151, `arena.py` 193/382 | `total_level()`. Allowlisted. |
| **Display (MC4)** | `menus/board.py` 43–44/82, `main.py` 11010–11011, 15030 | build string |
| **Pact (MC6)** | `main.py` 12670 (`_apply_pact_slot_level` keys off the primary class), `actions.py` 734, `menus/riders.py` 469 | pact pool |
| **Mirror / serialization (allowlist)** | `main.py` 4774–4892 (Stats OK), 14654–14658 (legacy save keys), `agent_loader.py` 209–252, `dialogs.py` (stepper plumbing; the focused-class model is already multiclass), `party_gen.py` 302 (D8) | unchanged |

### 0.2 C++ re-grep

- `combat_turn.cpp:3919`: rage bonus from `char_level`. **Leak (G2)**, should be `classLevel(Barbarian)`.
- `combat_spells.cpp:1028`: `getNumTargetsForSpell(…char_level…)`. Total level. Correct.
- `agent.hpp:989`: Tough +2 × `char_level`. Total level. Correct.
- `agent.hpp:1041`: short rest restores slots `if get_caster_type(character_class) == CasterPact`.
  **Leak.** A Warlock/Fighter (primary = Fighter) never regains Pact slots on a short rest, and a
  Warlock/Wizard would regain *all* slots. Fixed by MC6.
- `agent.hpp` 460–590 (`recompute_class_mirrors`, `set_class_level`, the mirror setters) is mirror
  machinery. Allowlisted. `compute_class_slots` no longer reads `char_level` anywhere.

### 0.3 D5 sizing: spellcasting ability

- **The hook already exists.** `rules::spellSaveDcFor(pa, sp)` / `spellAttackModFor(pa, sp)`
  (`rules.hpp:308/315`) take the spell and are used at 7 sites. MC5 makes them read the spell's
  source class.
- **Open-coded ability ladders bypass the helpers.** `combat_spells.cpp` 1469, 1705, 1874,
  1899, 1942, 2062 (healing / damage +mod) and a switch at 3954. Rewrite all 7 through one
  helper.
- **Class features cast without a spell** call `rules::spellSaveDc(stats)`:
  `combat_riders.cpp` 222, 317 (Ranger), `combat_resources.cpp` 3587, `combat_spells.cpp` 5442.
  Sorcerous Burst calls `spellcastingAbilityMod(caster)` at `combat_spells.cpp:154`. These need a
  `…ForClass(stats, C)` variant. Each site names its class.
- **Storage:** the engine holds `std::vector<Spell>` per agent (`setAgentSpells`), saved as
  `spell_indices` (names). Add `Spell::source_class` (default None → fallback) and a parallel
  optional `spell_classes` list in the save. `main.py` 12854 and 13630 (ability display) read the
  helper instead.
- **Fallback field:** `applyClassResources` writes `spellcasting_ability` once per class, so
  the last class in enum order wins. That's acceptable only as the untagged fallback.

### 0.4 D6 sizing: Pact pool

- **Explicit pact sites (10):** `agent.hpp` 593 (`pact_slot_level()` returns the *lowest*
  nonzero regular slot, so it is wrong for any multiclass Warlock), 1041; `combat_attack.cpp`
  942, 961, 3764; `combat_resources.cpp` 1809, 2816; `actions.py` 734; `main.py` 12665–12671;
  `menus/riders.py` 469.
- **Open-coded slot reads/spends (~45)** across `combat_attack`, `combat_riders`,
  `combat_resources`, `combat_spells` and `combat_turn` touch `spell_slots_remaining[i]`
  directly. "Has any slot" checks (e.g. `combat_attack.cpp:1870`, `combat_spells.cpp`
  5227/5260) and "spend lowest slot" loops (5340, 5510) must see both pools. MC6 starts by
  routing them through three helpers (`hasSlotAt`, `anySlotFree`, `spendSlot(level, pool)`),
  then adds the second pool behind them.

### 0.5 Rule audit (SRD 5.2, pp. 24–25, which is the 2024 text)

| Rule | RAW 2024 | Engine today | Action |
|---|---|---|---|
| Spell-slot combined level | full + **half (round up)** Paladin/Ranger (+ ⅓ round down EK/AT, PHB) | `agent.hpp:526` computeMulticlassSlots uses `halfLevels / 2`, **floor** (2014 rule) | **Bug under D1.** Fix in MC1: Paladin 3 / Wizard 3 should be combined 5, not 4. |
| Extra Attack | doesn't stack; Thirsting Blade adds nothing on top | max over classes | ✓ |
| AC formulas | pick one (Unarmored Defense ×2, Draconic Resilience) | first match in fixed order (`rules.hpp` Barbarian → Monk → Dance → Draconic) | Fix in MC1: take the **best**. |
| Proficiency bonus | total level | authored (`prof_bonus`) | ✓ (unchanged) |
| Saving throws / starting proficiencies | initial class only | **every class's chassis saves are ORed in** (`class_resources.cpp` 94, 195, 263, 458, 575, 674…) | **Conflicts with D9.** See A2. |
| Channel Divinity | no special rule | Cleric "Channel Divinity" and Paladin "Channel Oath" are separate resources | ✓ |
| Cantrips | total level | `cantripTier` uses `totalLevel()` | ✓ |
| Spells prepared, each with its class's ability | per class | single ability | D5 / MC5 |
| HP, hit dice | per class | authored | D8, out of scope |

### 0.6 Oracles (become `tests/test_multiclass_pcs.py` in MC1)

**Ezmerelda d'Avenir, Wizard 7 (Evoker, starting) / Fighter 1.** STR 14, DEX 18, CON 16,
INT 18, WIS 12, CHA 18.
- `total_level` 8, PB +3. Slots 4/3/3/1 (Wizard is the only caster, so it keeps its own table).
- Spell DC 15, spell attack +7, from INT. Booming Blade and Fire Bolt use INT.
- Wizard menus **present** (Arcane Recovery, Evoker Safe Targets). Overchannel absent (Wizard 14).
- Second Wind present, heals 1d10 **+ 1** (not +8). Action Surge **absent** (Fighter 2). One
  attack.
- Cantrip tier 1 (total 8).
- Saves: INT, WIS only. *Today the engine also grants STR/CON (A2).*
- *Today: the primary mirror is Fighter, so every Python Wizard gate fails.*

**Keef Girgo, Ranger 5 (Hunter, starting) / Rogue 1.** STR 8, DEX 15, CON 15, INT 8, WIS 15,
CHA 8.
- `total_level` 6, PB +3. Slots 4/2 (Ranger's own half-caster table).
- Spell DC 13, attack +5, from WIS.
- Two attacks (Ranger Extra Attack). Hunter's Prey present.
- Sneak Attack 1d6. Cunning Strike **absent** (Rogue 5; `menus/riders.py:572` reads total 6
  today and offers it). Cunning Action absent (Rogue 2).
- Saves: STR, DEX only (no INT from Rogue).
- *Today: the primary mirror is Rogue, so the Ranger menu rows (`actions.py` 634, 1015) vanish.*

### Amendments the findings forced (accepted 2026-11-16, folded into D6 / D9)

- **A1 (no decision; D1 already covers it):** fix the half-caster rounding and the AC
  best-of in MC1.
- **A2, replaces D9. ✅ Accepted.** RAW and the engine both need the **starting class**: chassis saves come
  from it alone, and the engine currently grants every class's saves. Proposal: add
  `Stats::starting_class` (saved as `agent_starting_class`). The importer fills it from DDB
  `isStartingClass`, the Stats dialog uses the first class entered, and a legacy save uses the
  primary mirror. `applyClassResources` grants chassis saves only for that class. Feature saves
  (Slippery Mind, Disciplined Survival…) stay per class.
- **A3, refines D6. ✅ Accepted.** Should a *single-class* Warlock also move to the Pact pool? Recommended:
  **yes.** One path instead of a multiclass branch at every pact site. A legacy Warlock save's
  `spell_slots_*` loads into the Pact pool. The alternative keeps D6 as written (single-class
  untouched) and costs a branch at the ~10 pact sites.

## Implementation steps (each is one commit, suite green)

- **MC1 Guard and leaks.** Add the D4 allowlist test. Fix G2 (`classLevel(Barbarian)`), the
  half-caster rounding, the AC best-of, and A2 (starting class). Add the 0.6 oracles as tests: some fail now and are expected to pass by
  MC3.
- **MC2 Python gate sweep, part 1.** `actions.py`, `menus/*`, `arena.py`.
- **MC3 Python gate sweep, part 2.** `main.py`, then shrink the allowlist to its final form.
- **MC4 Displays (G6).** Show "Wizard 7 / Fighter 1" everywhere a class is shown, including
  the player-screen Character panel if it shows one.
- **MC5 Per-class spellcasting ability (D5).** Engine helpers, the site rewrite, spell
  tagging in save/load, and the Stats dialog control for a spell's class.
- **MC6 Pact pool (D6).**
- **MC7 Importer (D7).** Re-import Ezmerelda and Keef, and diff them against the 0.6 oracles.
- **MC8 Live check.** Run a short combat with both PCs through `run.sh`, on the DM console
  and the player screen.
