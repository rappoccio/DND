# D&D 5e Combat Sim — Backlog

_Last refreshed: 2026-06-15. High-level epics only. **Per-feature deferrals live in
`known_limitations.md`** (the authoritative source) — this file does NOT duplicate it._

Status of live session work (Sorcerer / Bard / Eldritch Knight / Paladin / Bonus-Action
Manager / Divine Smite) is tracked in the auto-memory, not here. Most recent class work is
"awaiting build" — see auto-memory `MEMORY.md`.

---

## Cross-cutting epics (the big open infrastructure)

These gate multiple per-class features; each is a real project, not a quick task.

- [~] **Reaction / interrupt system** — framework SHIPPED + ALL 7 windows live
  (`LeftReach`/OA, `OnHit`/Shield+Protective Field, `OnMiss`/Riposte, `OnDeclareCast`/
  Shield-vs-MM+Counterspell, `OnD20Seen`/Bend Luck+Cutting Words+Silvery Barbs on attack rolls,
  `OnSaveFail`/Countercharm+Indomitable on spell saves, `OnTurnStartNearby`/Branches of the Tree).
  Spec docs retired; status in auto-memory `reaction-system-plan` + `known_limitations.md`.
  **Remaining FOLLOW-UPS only:** extend OnD20Seen / OnSaveFail to the **other inline save sites**
  (beginTurn, concentration, weapon-condition, death saves — the spell-save chokepoint now exists),
  fold Uncanny Dodge + Guided Strike into the OnHit/OnMiss framework, and Sentinel clauses 1 + 3.
- [ ] **Headless / RL default decider** — `CombatDecider` auto-policy for the branches that
  currently require a GUI menu (Reckless, Brutal Strike, OA weapon choice, item pickup).
  See memory `architecture_decider_flow_state`. Interface stub already landed with terrain.
- [ ] **Turn-economy state → C++** — migrate `attacks_remaining` (live in-action attack
  counter, still GUI state) into the engine. Noted in the Eldritch Knight work.
- [ ] **Class-object refactor (incremental)** — move scattered `if (character_class == …)`
  conditionals into per-class virtual dispatch. Step 1 (stats homogenized into `Agent`) is
  done. Pragmatic/incremental, not a big-bang rewrite. See `architecture_agent_as_character`.
- [ ] **Doors & locking (interactable map objects)** — genuinely missing infra. Today cells are
  only passable/wall; there's no door object that can be open/closed/locked/broken, and no
  "interact with an object" action. Needs: a door/object concept on the map (state: open/closed,
  locked + lock DC, optionally trapped), open/close toggling that updates passability + line of
  sight, and a generic "use/interact with an object" action. **Gates Thief L3 Fast Hands**
  (Sleight of Hand to pick a lock / disarm a trap; Use an Object) and is also the right home for
  the BUGS items "OAs should not be triggered if there is a wall between agents" and "If you drop
  weapons you cannot pick them back up" (ground-item pickup is the same interact primitive). Real
  cross-cutting epic (C++ map model + bindings + GUI placement/interaction UI); do as its own design pass.

## Per-class near-term (open mechanics)

- [ ] **Sorcerer** — Wild Magic Surge **trigger** (1/turn after a slot-spell) + GUI
  enforcement of bands 6/8/10; Tides of Chaos; Controlled Chaos (L14); Tamed Surge (L18).
  Still tracked in `known_limitations.md` → Sorcerer.
- [ ] **Bard** — Valor Combat Inspiration (+AC/+damage), Glamour Mantle of Inspiration
  (multi-target temp HP), optional Countercharm. See `known_limitations.md` → Bard.
- [ ] **Everything else** — each class section in `known_limitations.md` carries its own
  `[DEFER]` / `🚫 not modeled` list (Warlock patrons, Rogue subclasses, Wizard L6 subclass
  features, Cleric domains, Wild Shape mechanics, etc.). That file is the checklist.
- [x] **Ranger** — DONE (2024 Ranger COMPLETE: chassis + Hunter's Mark/Hex rider + all 4 subclasses
  Hunter/Gloom Stalker/Beast Master/Fey Wanderer + class utility L10/14/18). See `known_limitations.md`
  Ranger sections + memory `ranger_progress`. Root spec/handoff docs retired.
- [ ] **Multiclassing support** -- needs implementation

## Data / bestiary

- [ ] **Merge with 5e-bits database** — the source `DND2024_MonsterStats.csv/.json` is a
  buggy spreadsheet export (wrong PBs, typo'd damage averages, fabricated riders — see memory
  `feedback-monster-data-unreliable`). The [5e-bits 5e-database](https://github.com/5e-bits/5e-database)
  has structured monster `actions` with real `damage_dice`/`damage_type`/`attack_bonus` — far
  more reliable. BUT the **2024** set (`src/2024/en/`) currently has only **3 monsters** (Aboleth,
  Adult Black/Blue Dragon); the complete set is **2014** edition (~330, different values). When a
  comprehensive 2024 list surfaces, migrate the bestiary to it (or cross-check) and retire the
  hand-built `tools/monster_weapon_overrides.json`. User is hunting for the bigger list.

## Character import / storage

- [x] **D&D Beyond character importer** (2026-06-11) — `tools/import_character.py` fetches a
  public DDB character (`character-service.dndbeyond.com/character/v5/character/<id>`, urllib,
  no deps), *derives* our flat agent record (final ability scores from base+modifiers, AC
  back-solved into `base_ac`, HP, prof, saves, slots from caster table, class/subclass/weapon/
  spell name-mapping), best-effort + warns, saves the raw DDB JSON as a `.ddb.json` sidecar
  (lossless source of truth), and can `--merge` into an existing encounter file by name (keeps
  position/faction). This is "Option A".
- [ ] **Option B — enrich OUR native schema with DDB's good ideas (future epic).** Our agent
  JSON is lossy/provenance-free (stores final WIS 18, not "15 base +3 feats"), so it can't cleanly
  re-derive or re-level. Option B = store `base` ability scores + a small `modifiers` list (and
  item-driven AC) instead of only finals, deriving the flat engine view at load. Adopts the DDB
  *philosophy* without swallowing the proprietary 345 KB blob or mandating a GUI stat-editor
  rewrite. Touches C++ loaders, bindings, `agent_loader.py`, GUI save/load, test fixtures — a real
  cross-cutting refactor; do as its own design epic. (We rejected literal DDB-blob-as-native-store:
  proprietary, server-versioned, requires reimplementing DDB's whole derivation engine.)

## App / non-combat (deferred — out of the combat-sim core scope)

Per the "combat-sim only" scope rule, these are explicitly deferred, not active:

- [ ] Game Mode architecture (DM mode vs. automated Player mode) + team-based visibility
- [ ] Teams / Challenge Rating / encounter-balance tooling
- [ ] XP tracking & level-up progression
- [ ] Better default character sprites
- [ ] Out-of-combat flavor (item identification, etc.) → recorded in `known_limitations.md`

---

## Done (high level)

Classes with chassis + core implemented & tested: Barbarian, Wizard, Rogue, Cleric, Warlock,
Druid, Monk, Fighter (incl. Eldritch Knight), Paladin (incl. Divine Smite, Lay on Hands, Auras),
Sorcerer (Phases 1–3 core), Bard (chassis + Bardic Inspiration + college core), **Ranger (all 4
subclasses, COMPLETE)**. Plus: forced movement, grapple, conditions/exhaustion/death saves, weapon
mastery (9/9), persistent AoE + terrain, visibility/lighting, Bonus-Action Manager, checked combat
replay, **N-faction Teams system**, **summoning**, general feats (G0–G5b), fighting styles, the
**D&D Beyond importer**, and the `combat.cpp` → `combat_*.cpp` translation-unit split. Recent class
work: **Cleric Light Domain — Warding Flare + Corona of Light (2026-06-15)**. See `known_limitations.md`
for the ✅-marked detail per class.
