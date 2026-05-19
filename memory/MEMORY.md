- [Current Session State](current_session_state.md) — Build fixed, visibility working, map panning added, darkvision/truesight/crawling/prone done
- [All Core Logic in C++](architecture_cpp_only.md) — Game logic must be C++, Python is UI/I/O only for expert mode & RL training
- [D&D Battle Map - Pending Features](pending_features.md) — Next major features: Game Mode Architecture, DM/Player visibility, crowd control spells
- [User handles all builds](feedback_build_handling.md) — Do not attempt C++ builds or Docker; user manages compilation
- [Vision System Implementation](vision_system_implementation.md) — Phase 1, 2, 3 complete: obscuration, visibility computation, darkvision/truesight/devil's sight
- [User work preferences](user_preferences.md) — Design discussions without compaction, user handles builds and git

## Implementation Plans

### ✅ Completed
- [Plan: Hide Action](plan_hide_action.md) — Stealth checks, hidden condition, advantage on first attack, Cunning Action
- [Plan: Frightened Condition](plan_frightened_condition.md) — Fear spell, disadvantage, weapon drop, movement restriction
- [Plan: Lighting System](plan_lighting_system.md) — D&D 5e lighting, vision types, light effects
- [Plan: Unit Test Framework](plan_unit_test.md) — Full combat scenario test with monsters
- [Plan: Lifecycle Management](plan_lifecycle.md) — beginTurn/endTurn, agent method migration, spell effects

### ⏳ Pending
- [Plan: Forced Movement](plan_forced_movement.md) — Shove, spell push (Thunderwave), unarmed strike
- [Plan: Class/Spell-Slot Migration](plan_class_spellslot_migration.md) — C++ class tables, spell levels, slot management
