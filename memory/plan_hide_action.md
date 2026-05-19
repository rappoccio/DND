# Hide Action Implementation Plan

## Context
Implementing D&D 5e Hide action (and Rogue Cunning Action variant). An agent can hide if out of LOS of all enemies. Hiding triggers a Stealth contest: pre-combat vs passive Perception, in-combat vs active Perception. If agent beats all enemies, they gain the hidden condition which prevents enemies from seeing them. Hidden agents get advantage on first attack, which then reveals them.

**User requirement:** Core mechanics in C++, Python handles UI only.

## Findings Summary
- `hidden` field exists on `Agent::Conditions` but has zero mechanical effect
- `has_cunning_action` flag exists on `Agent::Stats` but is unused in GUI
- `hasLineOfSight` / `canSee` system fully implemented in `battle_map.cpp`
- `computeVisibility` does NOT check `hidden` — needs update
- Attack resolution does NOT check `hidden` for advantage — needs update
- No `stealth_prof` / `perception_prof` on Stats — need to add
- No `btn_cbt_hide` button in UI — need to add

---

## Implementation Plan

### 1. `agent.hpp` — Add skill proficiency flags
Add to `Agent::Stats`:
```cpp
bool stealth_prof{false};     // proficiency in Stealth (DEX-based)
bool perception_prof{false};  // proficiency in Perception (WIS-based)
```
Add computed helpers:
```cpp
[[nodiscard]] int stealthBonus() const noexcept {
    return (dex - 10) / 2 + (stealth_prof ? prof_bonus : 0);
}
[[nodiscard]] int passivePerception() const noexcept {
    return 10 + (wis - 10) / 2 + (perception_prof ? prof_bonus : 0);
}
```

### 2. `combat.hpp` — Add HideResult struct + declaration
```cpp
struct HideResult {
    bool valid{false};
    bool all_out_of_los{false};
    int  stealth_d20{0};
    int  stealth_total{0};
    bool hidden{false};
    std::string log_message;
};
```
Add declaration:
```cpp
HideResult checkHide(BattleMap& bm, int agent_idx, bool in_combat) noexcept;
```

### 3. `combat.cpp` — Core hide logic (all C++)

#### `applyHidden()` (new, ~lines after applyProne)
```cpp
void CombatEngine::applyHidden(BattleMap& bm, int idx) noexcept {
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.hidden = true;
    bm.setAgentConditions(idx, cond);
}
```

#### `checkHide()` (new)
1. Validate agent idx
2. Collect all other living agents
3. For each: call `bm.hasLineOfSight(agent_origin, agent_size, enemy_origin, enemy_size)`
4. If ANY other agent has LOS → return `{valid=true, all_out_of_los=false}` (can't hide, log which agent sees them)
5. Roll Stealth: `d20 + stealthBonus()`
6. Contest against ALL other living agents (even without LOS — they may hear/sense the hider):
   - If `in_combat`: roll active Perception: `d20 + (wis-10)/2 + (perception_prof ? prof_bonus : 0)`
   - Else: use passive Perception: `10 + (wis-10)/2 + (perception_prof ? prof_bonus : 0)`
   - If any observer perception ≥ stealth → agent spotted, hide fails, log who spotted them
7. If no one spots agent: call `applyHidden(bm, idx)`, return `{hidden=true}`
8. Revealed to ALL if spotted (global flag — simpler, no per-pair tracking)

#### `computeVisibility()` — check hidden condition
After LOS check, add: if `target_agent->getConditions().hidden`, set visibility to `VisibilityLevel::Blocked` (the target is unseen).

#### `executeAction()` — advantage + reveal on attack
After existing charmed/slipped checks, before attack roll:
- If `atk_cond.hidden`: set `has_adv = true`, then clear hidden: `setHidden(false)`

#### `executeSpell()` — reveal on spell cast
- If caster is hidden and spell targets enemies: clear hidden condition

### 4. `rpg_bindings.cpp` — Expose to Python
- `.def_readwrite("stealth_prof", &Agent::Stats::stealth_prof)`
- `.def_readwrite("perception_prof", &Agent::Stats::perception_prof)`
- `.def("check_hide", &CombatEngine::checkHide, py::arg("bm"), py::arg("agent_idx"), py::arg("in_combat"))`
- `.def("apply_hidden", &CombatEngine::applyHidden, ...)`
- Expose `HideResult` struct

### 5. `main.py` — UI only

#### Add buttons (alongside Dash/Dodge/Disengage, lines ~543–585):
```python
self.btn_cbt_hide = Button(..., "Hide")       # action button
self.btn_cbt_hide_bonus = Button(..., "Hide") # bonus action (cunning action)
```

#### Layout (lines ~4067–4078): Draw `btn_cbt_hide` in action buttons row

#### Show cunning action hide button in bonus area when `has_cunning_action` and `not bonus_used`

#### Click handlers (inside `if not self.action_used:` block):
```python
if self.btn_cbt_hide.clicked(event):
    in_combat = self.combat.is_in_combat()  # or check initiative order
    result = self.combat.check_hide(self.bm, idx, in_combat)
    self._flush_combat_log()
    if result.hidden:
        self._combat_log_add(f"{agent.name}: Successfully hidden (stealth {result.stealth_total})")
    else:
        self._combat_log_add(f"{agent.name}: Failed to hide")
    self.action_used = True
```

#### Same for bonus action version (sets `bonus_used = True`, only shown when `has_cunning_action`)

#### Visual indicator: draw a small eye-slash symbol on hidden agents (similar to other condition indicators)

---

## Files to Modify
- `gui/agent.hpp` — stealth_prof, perception_prof, stealthBonus(), passivePerception()
- `gui/combat.hpp` — HideResult struct, checkHide() declaration
- `gui/combat.cpp` — applyHidden(), checkHide(), computeVisibility(), executeAction(), executeSpell()
- `gui/rpg_bindings.cpp` — expose new fields/functions
- `gui/main.py` — Hide buttons, click handlers, visual indicator

## Verification
1. Place agent behind a wall/pillar out of enemy LOS
2. Click Hide (action) → stealth roll logged, agent is hidden
3. Move hidden agent into attack range → still hidden
4. Attack as hidden agent → should see "advantage" on attack roll, hidden clears after
5. Try to Hide while in LOS of enemy → should fail with message
6. Test Cunning Action (when `has_cunning_action=true`) → Hide available as bonus action
