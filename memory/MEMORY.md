# Repo Memory Index (`./memory/`)

> **The live, maintained memory is the Claude auto-memory** (`~/.claude/projects/…/memory/`),
> not this directory. The files here are durable reference/architecture/feedback docs kept in
> the repo. This index was rebuilt 2026-06-02 after pruning stale status files (the old index
> linked several files that no longer exist).

## Backlog & deferrals
- [TODO.md](TODO.md) — high-level open epics; points to known_limitations for per-feature detail
- [known_limitations.md](known_limitations.md) — **authoritative** per-class `[DEFER]` / not-modeled list

## Architecture (durable direction)
- [architecture_cpp_only.md](architecture_cpp_only.md) — all game logic in C++; Python is UI/IO only
- [architecture_agent_as_character.md](architecture_agent_as_character.md) — toward per-class objects via virtual dispatch (incremental)
- [architecture_decider_flow_state.md](architecture_decider_flow_state.md) — CombatDecider: GUI callback vs RL default policy

## Feedback / working style
- [feedback_model_split_workflow.md](feedback_model_split_workflow.md) — Opus designs/specs, Haiku executes mechanical coding
- [feedback_gui_not_tested.md](feedback_gui_not_tested.md) — main.py GUI isn't in run_all_tests.py; needs manual smoke-test
- [feedback_build_handling.md](feedback_build_handling.md) — build permission is model-gated: Opus 4.8 builds via Docker; Haiku & Sonnet never
- [user_preferences.md](user_preferences.md) — design-discussion / build / git collaboration prefs

## Reference
- [replay_instructions.md](replay_instructions.md) — checked combat replay for deterministic bug regression
