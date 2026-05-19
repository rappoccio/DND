# Plan: Frightened Condition + Fear Spell

## Context
Implementing the Frightened condition to support the Fear spell (level 3, concentration, 30-ft Cone, WIS save). Frightened has two mechanics: (1) disadvantage on attack rolls and ability checks when the fear source is in LOS, (2) cannot willingly move closer to the fear source. The Fear spell also forces Dash+flee each turn and drops held weapons on application.

The Fear spell JSON already exists in `spells.json` (lines 2594–2621) with `"condition_name": "Frightened"`. The `frightened` bool already appears in `dialogs_conditions.py` line 109 but has no C++ backing or movement/attack enforcement.

---

## Files to Change

| File | Change |
|---|---|
| `gui/agent.hpp` | Add `bool frightened{false};` to `Conditions` struct |
| `gui/combat.hpp` | Add `applyFrightened()` and `dropAgentWeapons()` declarations |
| `gui/combat.cpp` | 5 changes: new function, dispatcher, tick, moveAgent, executeAction/Spell |
| `gui/rpg_bindings.cpp` | Bind `conditions.frightened` field + update `__repr__` |
| `gui/main.py` | Visual indicator, Dash-only enforcement |

---

## Step 1 — `gui/agent.hpp`

Add to `Agent::Conditions` struct after `charmed`:
```cpp
bool frightened{false};
```

---

## Step 2 — `gui/combat.hpp`

Add declarations alongside `applyCharmed`:
```cpp
void dropAgentWeapons(BattleMap& bm, int idx) noexcept;
void applyFrightened(BattleMap& bm, int idx) noexcept;
```

---

## Step 3 — `gui/combat.cpp`

### 3a — `dropAgentWeapons()` (new function, before `applyFrightened`)
```cpp
void CombatEngine::dropAgentWeapons(BattleMap& bm, int idx) noexcept {
    auto& pa = bm.getPlacedAgents()[idx];
    for (auto& w : pa.weapons) {
        if (!w.name.empty() && w.name != "Unnamed") {
            bm.placeItem(pa.origin, w, "");
            w = Weapon{};
        }
    }
}
```

### 3b — `applyFrightened()` (new function, after `applyCharmed`)
```cpp
void CombatEngine::applyFrightened(BattleMap& bm, int idx) noexcept {
    dropAgentWeapons(bm, idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.frightened = true;
    bm.setAgentConditions(idx, cond);
    log_("Agent is Frightened: dropped weapons, disadvantage on attacks/checks when fear source in LOS, cannot approach");
}
```

### 3c — `addAgentCondition()` dispatcher
Add after the Charmed branch:
```cpp
else if (cond.condition_name == "Frightened") applyFrightened(bm, cond.agent_idx);
```

### 3d — `tickAgentConditions()` removal
In the condition-expiry block after the Charmed clearing:
```cpp
else if (cond.condition_name == "Frightened") {
    agent_cond.frightened = false;
    log_("Frightened condition ended");
}
```

For the **mid-duration LOS-gated save**: in the save-tick loop, before rolling for "Frightened", check if the victim still has LOS to the fear source. If yes, skip the save (they can't try to end it while they can still see the source):
```cpp
if (cond.condition_name == "Frightened" && cond.caster_idx >= 0) {
    Cell src = bm.getPlacedAgents()[cond.caster_idx].origin;
    Cell vic = bm.getPlacedAgents()[cond.agent_idx].origin;
    if (bm.hasLineOfSight(vic, 1, src, 1)) continue;  // still sees source, no save
}
```

### 3e — `moveAgent()` — block movement toward fear source
After existing Incapacitated/Slipped checks, before executing the move:
```cpp
for (const auto& ac : activeConditions_) {
    if (ac.agent_idx == agent_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
        Cell src  = bm.getPlacedAgents()[ac.caster_idx].origin;
        Cell cur  = bm.getPlacedAgents()[agent_idx].origin;
        int cur_d = std::max(std::abs(cur.col - src.col), std::abs(cur.row - src.row));
        int new_d = std::max(std::abs(dest.col - src.col), std::abs(dest.row - src.row));
        if (new_d < cur_d) {
            log_("Movement blocked: Frightened cannot move closer to fear source");
            return false;
        }
        break;
    }
}
```

### 3f — `executeAction()` / `executeSpell()` — LOS-conditional disadvantage
In the attack-roll setup section of `executeAction()`, after the blinded/charmed dis checks:
```cpp
if (bm.getAgentConditions(attacker_idx).frightened) {
    for (const auto& ac : activeConditions_) {
        if (ac.agent_idx == attacker_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
            if (bm.hasLineOfSight(bm.getPlacedAgents()[attacker_idx].origin, 1,
                                  bm.getPlacedAgents()[ac.caster_idx].origin, 1))
                dis = true;
            break;
        }
    }
}
```
Apply the same block in `executeSpell()` for spell attack rolls (attack_type == AttackRoll).

---

## Step 4 — `gui/rpg_bindings.cpp`

In the `Agent::Conditions` binding block:
```cpp
.def_readwrite("frightened", &Agent::Conditions::frightened)
```
Update the `Conditions.__repr__` lambda to include `frightened`.

---

## Step 5 — `gui/main.py`

### Visual indicator
In `_draw_agents()`, alongside Charmed/Prone overlays, draw a purple "FR" badge over Frightened agents.

### Dash-only enforcement
In `_draw_combat_panel()`, when `cur_cond.frightened` is True:
- Hide all action buttons except `btn_cbt_dash`
- Show a "Frightened — must Dash" label in the action area

---

## Verification

1. Build with `cmake --install build` (user handles).
2. Cast Fear on enemies in the cone — each drops weapons onto the map at their cell.
3. Frightened agent token shows purple "FR" badge.
4. Try to move the Frightened agent toward the caster — blocked with log message.
5. Moving away or laterally succeeds.
6. Frightened agent attacks with the caster in LOS — roll shows Disadvantage.
7. Move Frightened agent to no-LOS cell → end turn → WIS save rolled; on success condition clears.
8. Frightened agent's action panel shows only Dash.
9. Run `python3 run_all_tests.py` — all tests pass.
