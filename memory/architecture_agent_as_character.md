---
name: architecture-agent-as-character
description: Direction to consolidate character data/logic into Agent, toward per-class objects (Barbarian/Wizard) with virtual dispatch
metadata:
  type: project
---

# Direction: Agent as the single source of truth → per-class objects

The long-term goal is class objects usable as `Barbarian b(stats); Wizard w(stats); b.hit(w);`, where each class owns its own mechanics instead of `if (character_class == Barbarian)` conditionals scattered through `combat.cpp`.

**Why:** Class-specific logic (~600–700 lines, ~13–15% of combat.cpp) is interleaved into the hottest methods (`executeAction`, `executeSpell`, `resolveAttack`), making them hard to read/extend. Each new feature adds more conditionals.

**Decided approach:** Use **virtual functions** (the abstract `Agent` base already exists with `ConfiguredAgent`), NOT C++20 concepts/duck-typing — concepts would fight the existing design and the team isn't focused on modern-template idioms. See [[known-limitations]].

**Step 1 done (May 21, 2026):** Homogenized stats into `Agent` (single source of truth, mirroring Conditions). Removed the duplicate `PlacedAgent.stats`. This was both a cleanup AND a latent-bug fix (the dual store had diverged). It's a prerequisite for the class-object vision.

**How to apply:**
- When adding class features, prefer putting character data/behavior in `Agent`, not new `PlacedAgent` fields or new `combat.cpp` conditionals.
- Weapons/spells/armor still live on `PlacedAgent` (not yet a bug); they'd move into `Agent` only when pursuing the full class-object refactor.
- The combat engine owns RNG (`roll()`, which is Diviner-aware via Portent) and the logger — any class-method design must account for classes needing that engine context.
- Prefer the pragmatic middle path (encapsulate the *very* class-specific stuff, fix root issues) over big-bang rewrites. User explicitly wants incremental, not a full rewrite up front.
