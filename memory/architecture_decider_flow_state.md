---
name: architecture-decider-flow-state
description: Directive for moving main.py logic to C++ — logic lives in C++ with decision points injected via a CombatDecider (GUI=Python callback, RL=default policy)
metadata:
  type: project
---

# Migrating main.py logic to C++: the decider/flow-state pattern

When moving game logic out of `main.py` into C++ (the long-running effort to make
combat headless/RL-trainable), the user's stated rule is:

> "The functionality should live in C++, with flow-state conditionals as inputs.
> For the game it hooks back into Python; for RL/headless it uses some default
> (not yet written)."

**Why:** This is a game *with user input*. Many combat branches currently pop a
GUI context menu (Reckless Attack y/n, Brutal Strike effect choice, opportunity-
attack weapon/spell choice, item pickup). The logic must run in C++ for
reproducible/deterministic rollouts, but the *choice* at each branch comes from
either a human (GUI) or a policy (RL). So the engine must not hardcode the GUI.

**How to apply:**
- Put the mechanics in C++. At each interactive branch, call an injected
  `CombatDecider` abstract interface (in `combat.hpp`). The GUI registers a
  pybind11 trampoline subclass that calls back into Python to show menus; RL/
  headless uses a default auto-policy (`decider_ == nullptr` → built-in defaults).
  Set via `CombatEngine::setDecider(...)`.
- Prefer making a choice part of the discrete action space (`availableAttacks`-
  style) when it cleanly can be, rather than a callback.
- Terrain placement turned out to need **no** interactive decision (deterministic
  from spell + AoE center), which is why terrain was chosen as the first migration.

**Status (2026-05-22):** Terrain migration is the first epic — see
`TERRAIN_MIGRATION_SPEC.md` in repo root (Opus-authored, Haiku to execute the
mechanical steps). The decider interface lands as an unused stub in that epic;
it gets exercised when the Brutal Strike / Reckless / OA menus migrate next.

Related: [[architecture-cpp-only]] (the parent rule), [[feedback-model-split-workflow]]
(Opus writes the spec, Haiku executes), [[architecture-agent-as-character]].
