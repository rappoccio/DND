---
name: current-session-state
description: Active work and implementation progress
type: project
---

## Session Progress (May 14-21, 2026)

### Completed
- Fixed Docker build and noVNC connectivity
- Fixed visibility popup bug
- Implemented map panning with mouse wheel and arrow keys
- Updated memory with vision system and darkvision/truesight/devil's sight additions
- ✅ Thunderwave Push now working correctly (forceMoveAgent executing)
- ✅ Crowd Control Spells (stun, paralyze, held conditions)
- ✅ Abjurer L3 (Arcane Ward) - Complete with long rest init, auto-charging, bonus action UI
- ✅ **Reckless Attack System** (May 21):
  - C++: Auto-triggers on Barbarian miss (sets flag, re-rolls with advantage)
  - Enemies gain advantage against Reckless Barbarians
  - Removed old Frenzy d6 damage placeholder
- ✅ **Berserker L3: Frenzy Bonus Attack** (May 21):
  - After action attack with Reckless + Rage, grants bonus melee attack
  - Tracked with `berserker_frenzy_used` flag (per-round)
- ✅ **Brutal Strike (L9+)** (May 21):
  - Python context menu after hit with Reckless active
  - Choice between: Forceful Blow (push), Hamstring Blow (speed -15ft)
  - L13+ adds: Staggering Blow (disadv next save), Sundering Blow (+5 next attack)
  - Calls C++ `apply_brutal_strike_effect` with chosen effects
### QoL improvements (May 21)
- ✅ **Barbarian damage breakdown logging** — DONE (rebuild needed): `AttackResult.damage_breakdown` vector of (label, amount); logs e.g. `HIT 7 [4 (weapon) + 3 (rage)]`. Frenzy = own attack line; Brutal Strike = own `+N (NdY)` line.
- ⏳ **PC custom names** — SPEC'd for Haiku: PCs default to `"{class} 1"` at main.py:807 `_on_pc_class_selected`; prompt for a name (reuse `TextInput` widget) and set `cfg.name` before placement. Pure Python.
- ⏳ **Logs show agent[N] instead of names** — SPEC'd for Haiku: add `CombatEngine::agentName(bm, idx)` helper; convert ~20 index-based `log_` calls in combat.cpp (e.g. `[COND] ... agent[0]`). C++ rebuild.

- ✅ **Stats homogenization** (May 21) — VERIFIED: compiled + all tests pass:
  - Removed duplicate `Agent::Stats stats` member from `PlacedAgent`
  - Stats now live solely in `Agent` (single source of truth, mirroring how Conditions already worked)
  - `get/setAgentStats` delegate to `agent->getStats()/setStats()`; added `Agent::setStats()`
  - Fixed a latent dual-store bug: `resolveAttack` had been reading AC/mods from and writing damage to the dead `Agent::stats_` while everything else used `PlacedAgent.stats`
  - `resolveAttack` is now compute-only (`const Agent& target`); `executeAction` applies base damage once to its working copy and persists it

### Forced Movement System - COMPLETE

All push/shove/knockback mechanics implemented. All logic in C++, Python for UI only.

**Completed Steps:**
1. ✅ Added `push_ft` field to `AttackCondition`
2. ✅ Implemented `BattleMap::forceMoveAgent()`
3. ✅ Added result structs (ShoveAction, ShoveResult, push_ft_applied)
4. ✅ Implemented `executeShove()` in combat.cpp
5. ✅ Handle "Push" condition in `executeAction()` and `executeSpell()`
6. ✅ rpg_bindings for ShoveAction/ShoveResult API
7. ✅ helpers.py parses `push_ft` from JSON
8. ✅ spells.json updated (Thunderwave push_ft: 10, Gust of Wind push_ft: 15)
9. ✅ Python UI - Shove buttons (bonus action) + Unarmed Strike menu:
   - "🔨 Shove (Push)" and "⬇ Shove (Prone)" in bonus action section
   - "👊 Unarmed" opens modal with Punch/Grapple/Push options (action)

---

## Architecture

**Flow:** 
- User clicks "Shove" → Python calls `executeShove(ShoveAction(...))` 
- C++ resolves contested Athletics check 
- If success: calls `BattleMap::forceMoveAgent()` 
- Result includes push_ft_applied and log message
- Python refreshes overlays (`_update_reach()`, `_update_attack_overlay()`)

**Key Design:**
- Push is represented as `AttackCondition` with `condition_name == "Push"` and `push_ft` value
- Works for weapons (proficiency required), spells (no proficiency needed)
- Unarmed strike uses same synthetic weapon system with proficiency always true
