---
name: architecture-agent-as-character
description: ABANDONED per-class C++ objects (multiclassing breaks single inheritance); new direction is character_class as a vector searched via hasClass()
metadata:
  type: project
---

# Direction: Agent as single source of truth → ~~per-class objects~~ multiclass-capable Stats

## ABANDONED (2026-06-22): per-class C++ objects with virtual dispatch

The earlier goal of class objects usable as `Barbarian b(stats); Wizard w(stats); b.hit(w);`
— each C++ class owning its own mechanics via virtual dispatch off the abstract `Agent`
base — **is abandoned.**

**Why it fails:** a D&D character can have **multiple classes at once** (multiclassing:
e.g. Fighter 5 / Wizard 3). A per-class C++ object model would require one agent to *be*
multiple C++ classes simultaneously — multiple inheritance off `Agent` — which is
unworkable (diamond problems, no clean way to compose/dispatch overlapping mechanics, no
single object to instantiate). The single-D&D-class assumption baked into the per-class
object vision does not hold, so the vision is dead.

**What survives:** Step 1 (May 21, 2026) is still good and still the right call —
homogenized stats into `Agent` as the single source of truth (mirroring Conditions),
removed the duplicate `PlacedAgent.stats`. That was a cleanup + latent-bug fix independent
of the class-object idea. Keep it.

## NEW DIRECTION: `character_class` becomes a vector (NOT YET IMPLEMENTED)

To support multiclassing, `Stats.character_class` (currently a single `CharacterClass`
enum, `agent.hpp:141`) must become a **collection of classes** — a
`std::vector<CharacterClass>` (or small set), each with its own level.

Consequently, every single-equality check of the form:

```cpp
attacker.getStats().character_class == CharacterClass::Barbarian
```

must become a **search over the vector**, e.g. a helper on `Stats`:

```cpp
bool hasClass(CharacterClass c) const;   // returns true if c is among the agent's classes
```

so the call site reads `attacker.getStats().hasClass(Barbarian)`.

**Scope of the change (for when we do implement):**
- ~96 `character_class ==` (and `!=`) comparison sites across 9 files:
  `combat_core.cpp`, `combat_resources.cpp`, `combat_state.cpp`, `combat_riders.cpp`,
  `battle_map.cpp`, `combat_attack.cpp`, `rpg_bindings.cpp`, `combat_turn.cpp`,
  `combat_spells.cpp`. Each must route through `hasClass()` (or an equivalent).
- Per-class **level** is also needed (multiclass uses per-class level for feature gating
  and a combined level for things like proficiency bonus / slot table). The current single
  `level` + single `character_class` pairing must generalize to per-class levels; the
  caster-slot logic (`get_caster_type`/`compute_class_slots`, `character_class.hpp`) needs
  a multiclass spell-slot rule.
- Serialization round-trip (dict_to_stats + main.py save block) must handle the class
  vector — see [[stats-serializer-roundtrip]].
- pybind11 bindings (`rpg_bindings.cpp`) expose `character_class`; the Python/GUI side and
  save files assume a single class today.

**NOT YET IMPLEMENTED** — this entry records the decision and the plan only. No code change
has been made. Do not start the vector migration without an explicit go-ahead; it touches
~96 sites plus serialization and GUI.

## How to apply in the meantime
- Class-specific behavior/data still goes in `Agent`/`Stats`, not new `PlacedAgent` fields
  or scattered `combat.cpp` conditionals.
- The combat engine still owns RNG (`roll()`, Diviner/Portent-aware) and the logger.
- Keep changes incremental — the user explicitly wants the pragmatic middle path, not a
  big-bang rewrite. See [[known-limitations]].
- When you add a NEW `character_class ==` site, know that it's debt that the future
  `hasClass()` migration will have to rewrite — keep the comparison in one obvious spot.
