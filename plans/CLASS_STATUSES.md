# Class Statuses

Checklist of all 12 (2024 PHB) classes and their subclasses. Verified against the
C++ subclass enums (`gui/character_class.hpp`), the `gui/test_*.py` suite, and
reference counts in the combat sources on 2026-07-07.

**Legend:** `[x]` implemented + tested · `[~]` partial / in progress · `[ ]` enum-only stub or not started

**Conventions (from memory):**
- Opus writes C++/Python/JSON; **user runs the Docker build and the test suite**.
- New `rpg.Stats` flags MUST go in BOTH `dict_to_stats` (helpers.py) AND the main.py save block, or they reset on save/reload.
- ALL save modifiers go through `saveModFor()`.
- `DND2024_MonsterStats.json` and the CSV→JSON converter are off-limits.
- Never commit — user owns all git commits.

---

## Summary

| Class     | Chassis | Subclasses | Remaining                               |
| --------- | :-----: | :--------: | --------------------------------------- |
| Barbarian |   [x]   |    4/4     | L14 GUI buttons only                    |
| Bard      |   [x]   |    4/4     | Countercharm, Dance/Lore L14 (deferred) |
| Cleric    |   [x]   |    4/4     | —                                       |
| Druid     |   [x]   |    4/4     | —                                       |
| Fighter   |   [x]   |    4/4     | —                                       |
| Monk      |   [x]   |    4/4     | —                                       |
| Paladin   |   [x]   |    4/4     | —                                       |
| Ranger    |   [x]   |    4/4     | —                                       |
| Rogue     |   [x]   |    4/4     | —                                       |
| Sorcerer  |   [x]   |    4/4     | —                                       |
| Warlock   |   [x]   |    4/4     | Invocation Lessons                      |
| Wizard    |   [x]   |    3/4     | Illusionist                             |

---

## Barbarian
- [x] Base chassis (L1–L20)
- [x] Berserker (Path)
- [x] Wild Heart
- [x] World Tree
- [x] Zealot
- [ ] L14 subclass-capstone GUI buttons (logic done, buttons pending)

## Bard
- [x] Base chassis + Bardic Inspiration (Font / Superior)
- [x] College of Dance
- [x] College of Glamour
- [x] College of Lore
- [x] College of Valor
- [ ] Countercharm (deferred — out of combat-sim scope)
- [ ] Dance / Lore L14 features (deferred)

## Cleric
- [x] Base chassis + Channel Divinity
- [x] Life Domain
- [x] Light Domain
- [x] Trickery Domain
- [x] War Domain

## Druid
- [x] Base chassis + Wild Shape
- [x] Circle of the Moon
- [x] Circle of the Land
- [x] Circle of the Sea
- [x] Circle of the Stars

## Fighter
- [x] Base chassis
- [x] Champion
- [x] Battle Master
- [x] Psi Warrior
- [x] Eldritch Knight (War Magic / Eldritch Strike / Arcane Charge)

## Monk
- [x] Base chassis (L2–L20)
- [x] Warrior of the Open Hand
- [x] Warrior of Mercy
- [x] Warrior of Shadow
- [x] Warrior of the Four Elements

## Paladin
- [x] Base chassis (Lay on Hands, Divine Smite, Aura of Protection/Courage)
- [~] **Oath of Devotion** (see `OATH_OF_DEVOTION_PLAN.md`)
  - [x] L3 Sacred Weapon — attack bonus
  - [ ] L3 Sacred Weapon — Radiant on-hit rider (Slice 1)
  - [ ] L7 Aura of Devotion — Charmed immunity in aura (Slice 2)
  - [ ] L15 Smite of Protection — Half Cover after Divine Smite (Slice 3)
  - [ ] L20 Holy Nimbus — bonus-action aura buff (Slice 4)
  - [ ] Oath spells (always-prepared list) (Slice 5)
- [x] **Oath of Glory 
- [x] **Oath of the Ancients** 
- [x] **Oath of Vengeance** 

## Ranger
- [x] Base chassis (Hunter's Mark rider)
- [x] Hunter
- [x] Beast Master
- [x] Fey Wanderer
- [x] Gloom Stalker
- Deferred (see known_limitations.md): Gloom Shadowy Dodge, Mass Fear, Umbral Sight

## Rogue
- [x] Base chassis (Sneak Attack, Cunning Action)
- [x] Thief
- [x] Soulknife
- [x] Assassin
- [x] Arcane Trickster

## Sorcerer
- [x] Base chassis + Metamagic + Sorcery Points
- [x] Aberrant
- [x] Clockwork
- [x] Draconic
- [x] Wild Magic
- Won't do: Subtle Metamagic

## Warlock
- [x] Base chassis (Pact Magic, Eldritch Invocations, Pacts)
- [x] Fiend
- [x] Celestial
- [x] Great Old One
- [x] Archfey
- [~] Eldritch Invocations — combat-relevant done; Lessons deferred to feat system

## Wizard
- [x] Base chassis + spell slots
- [x] Abjurer (Arcane Ward)
- [x] Diviner (Portent)
- [x] **Evoker** — Potent Cantrip (L3, half on a missed attack cantrip), Sculpt Spells (L6, the
      "safe targets" set), Empowered Evocation (L10, +INT to one Evocation damage roll), Overchannel
      (L14, max damage on a level 1-5 spell; first use free, then escalating Necrotic self-damage).
      Overchannel armed via the Evoker's right-click menu. `test_evoker.py`.
- [ ] **Illusionist** (Illusory Self / Malleable Illusions — stub)

---

## Remaining work, prioritized

1. ~~**Paladin — Oath of Devotion**: finish per `OATH_OF_DEVOTION_PLAN.md` (build order Slice 2 → 3 → 1 → 4 → 5).~~
2. ~~**Paladin — other 3 oaths**~~
3. ~~**Warlock — Archfey** patron~~.
4. **Wizard — Illusionist** subclass mechanics (Evoker done).
5. **Cleanup:** Barbarian L14 GUI buttons; Bard Countercharm / Dance L14 (both scope-deferred).
