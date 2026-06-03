# D&D 5e Combat Sim — Backlog

_Last refreshed: 2026-06-02. High-level epics only. **Per-feature deferrals live in
`known_limitations.md`** (the authoritative source) — this file does NOT duplicate it._

Status of live session work (Sorcerer / Bard / Eldritch Knight / Paladin / Bonus-Action
Manager / Divine Smite) is tracked in the auto-memory, not here. Most recent class work is
"awaiting build" — see auto-memory `MEMORY.md`.

---

## Cross-cutting epics (the big open infrastructure)

These gate multiple per-class features; each is a real project, not a quick task.

- [ ] **Reaction / interrupt system** — the largest blocker. "React after seeing the
  roll/cast" timing. Unlocks RAW: Bend Luck (Sorcerer), Cutting Words + Countercharm
  (Bard), Riposte (Battle Master), Arcane Deflection (Abjurer), Restore Balance
  (Clockwork Sorcerer), Indomitable (Fighter). Several of these ship now as *pre-roll*
  approximations — see `known_limitations.md` → "Post-hoc reaction interrupts".
- [ ] **Headless / RL default decider** — `CombatDecider` auto-policy for the branches that
  currently require a GUI menu (Reckless, Brutal Strike, OA weapon choice, item pickup).
  See memory `architecture_decider_flow_state`. Interface stub already landed with terrain.
- [ ] **Turn-economy state → C++** — migrate `attacks_remaining` (live in-action attack
  counter, still GUI state) into the engine. Noted in the Eldritch Knight work.
- [ ] **Class-object refactor (incremental)** — move scattered `if (character_class == …)`
  conditionals into per-class virtual dispatch. Step 1 (stats homogenized into `Agent`) is
  done. Pragmatic/incremental, not a big-bang rewrite. See `architecture_agent_as_character`.

## Per-class near-term (open mechanics)

- [ ] **Sorcerer** — Wild Magic Surge **trigger** (1/turn after a slot-spell) + GUI
  enforcement of bands 6/8/10; Tides of Chaos; Controlled Chaos (L14); Tamed Surge (L18).
  Still tracked in `SORCERER_IMPLEMENTATION_PLAN.md` + `known_limitations.md` → Sorcerer.
- [ ] **Bard** — Valor Combat Inspiration (+AC/+damage), Glamour Mantle of Inspiration
  (multi-target temp HP), optional Countercharm. See `known_limitations.md` → Bard.
- [ ] **Everything else** — each class section in `known_limitations.md` carries its own
  `[DEFER]` / `🚫 not modeled` list (Warlock patrons, Rogue subclasses, Wizard L6 subclass
  features, Cleric domains, Wild Shape mechanics, etc.). That file is the checklist.

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
Druid, Monk, Fighter (incl. Eldritch Knight), Paladin (incl. Divine Smite, Lay on Hands),
Sorcerer (Phases 1–3 core), Bard (chassis + Bardic Inspiration + college core). Plus: forced
movement, grapple, conditions/exhaustion/death saves, weapon mastery (9/9), persistent AoE +
terrain, visibility/lighting, Bonus-Action Manager, checked combat replay, and the
`combat.cpp` → `combat_*.cpp` translation-unit split. See `known_limitations.md` for the
✅-marked detail per class.
