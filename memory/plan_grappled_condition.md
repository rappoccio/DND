# Plan: Grappled Condition

## Overview

Grappled is a simple bool condition (like Hidden, Dodging) with no duration tracking. Unlike Charmed/Frightened which use ActiveAgentCondition for auto-saves, Grapple requires the player to choose to escape via an action.

## Context

Implementing the Grappled condition from D&D 5e. A grappled creature has:
1. **Speed 0**: Cannot move; Dash and other movement doesn't help
2. **Attack Disadvantage**: Disadvantage on attack rolls against any target except the grappler
3. **Movable**: The grappler pays 1 extra foot of movement per foot moved when dragging/carrying (exceptions: Tiny creatures or 2+ sizes smaller)

Grappling can be initiated by:
- Unarmed Strike with contested Athletics vs Athletics/Acrobatics check
- Spell effects that apply the Grappled condition

Grappling ends when:
- Grappled creature makes successful STR (Athletics) or DEX (Acrobatics) save vs escape DC
- Grappler becomes Incapacitated
- Distance exceeds grapple's range
- Grappler voluntarily releases (no action required)

---

## Implementation Steps (In Order)

### PHASE 1: C++ Data Structures & Bindings

**Step 1.1** — Modify `gui/agent.hpp` (add fields to Conditions struct)
**Step 1.2** — Modify `gui/combat.hpp` (add struct definitions)
**Step 1.3** — Modify `gui/combat.cpp` (implement core logic)
**Step 1.4** — Modify `gui/rpg_bindings.cpp` (expose to Python)

### PHASE 2: Python UI & Integration

**Step 2.1** — Modify `gui/main.py` (add buttons + logic)

---

---

# DETAILED STEP-BY-STEP IMPLEMENTATION

## PHASE 1: C++ Data Structures

### Step 1.1 — `gui/agent.hpp` — Add Grapple Fields to Conditions Struct

**Location:** Find `struct Conditions` in `gui/agent.hpp` (around line 360)

**Action:** Add these four fields at the end of the struct, before the closing brace:

```cpp
bool grappled{false};               // creature is currently grappled
int grappler_idx{-1};               // index of creature doing the grappling (-1 = none)
int grapple_escape_dc{10};          // DC to escape grapple (set by grappler's Athletics)
int grapple_range_ft{5};            // range at which grapple is broken if exceeded (default 5 ft)
```

**Why:** These fields track the grapple state on the target creature. Using simple bool + ints avoids needing ActiveAgentCondition complexity.

---

### Step 1.2 — `gui/combat.hpp` — Add GrappleAction and GrappleResult Structs

**Location:** Find existing result structs like `struct AttackResult` in `gui/combat.hpp`

**Action:** Add these struct definitions (place near the other result structs):

```cpp
// Grapple initiation action
struct GrappleAction {
    int attacker_idx{-1};   // creature initiating the grapple
    int target_idx{-1};     // creature being grappled
};

// Result of grapple attempt
struct GrappleResult {
    bool valid{false};              // action was valid (indices correct, etc.)
    bool success{false};            // grapple succeeded (attacker won contested check)
    int attacker_roll{0};           // attacker's Athletics roll (d20 + str_mod + prof)
    int target_roll{0};             // target's best roll (max of Athletics and Acrobatics)
    int escape_dc{0};               // DC for target to escape later (10 + attacker's Athletics)
    std::string log_message;        // human-readable result message
};

// Result of grapple escape attempt
struct GrappleEscapeResult {
    bool valid{false};              // agent was actually grappled
    bool success{false};            // escape succeeded
    int escape_roll{0};             // roll result (best of STR + DEX mods)
    int escape_dc{0};               // DC attempted against
    std::string log_message;        // human-readable result message
};
```

**Action:** Also add method declarations in the CombatEngine class:

```cpp
// In class CombatEngine declaration:
[[nodiscard]] GrappleResult executeGrapple(BattleMap& bm, const GrappleAction& action) noexcept;
[[nodiscard]] GrappleEscapeResult executeGrappleEscape(BattleMap& bm, int agent_idx) noexcept;
```

---

### Step 1.3 — `gui/combat.cpp` — Implement Grapple Core Logic

**Action A:** Add helper method `applyGrappled()` (place near other condition helpers like `applyCharmed`, `applyFrightened`):

```cpp
void CombatEngine::applyGrappled(BattleMap& bm, int target_idx, int grappler_idx, int escape_dc) noexcept {
    Agent::Conditions cond = bm.getAgentConditions(target_idx);
    cond.grappled = true;
    cond.grappler_idx = grappler_idx;
    cond.grapple_escape_dc = escape_dc;
    cond.grapple_range_ft = 5;
    bm.setAgentConditions(target_idx, cond);
    
    const auto& agents = bm.placedAgents();
    log_(fmt::format("{} is now grappled by {}",
                     agents[target_idx].agent->name(),
                     agents[grappler_idx].agent->name()));
}
```

**Action B:** Add method `executeGrapple()` (place after other action execution methods):

```cpp
GrappleResult CombatEngine::executeGrapple(BattleMap& bm, const GrappleAction& action) noexcept {
    GrappleResult res;
    const auto& agents = bm.placedAgents();
    
    // Validate indices
    if (action.attacker_idx < 0 || action.attacker_idx >= (int)agents.size() ||
        action.target_idx < 0 || action.target_idx >= (int)agents.size()) {
        res.valid = false;
        res.log_message = "Invalid grapple: target out of range";
        return res;
    }
    
    res.valid = true;
    
    // Get attacker stats
    Agent::Stats attacker_stats = bm.getAgentStats(action.attacker_idx);
    int str_mod_att = (attacker_stats.str - 10) / 2;
    int prof_bonus = attacker_stats.prof_bonus;
    
    // Attacker roll: d20 + STR mod + proficiency (assuming Athletics proficiency)
    res.attacker_roll = d20_roll() + str_mod_att + prof_bonus;
    
    // Get target stats
    Agent::Stats target_stats = bm.getAgentStats(action.target_idx);
    int str_mod_tgt = (target_stats.str - 10) / 2;
    int dex_mod_tgt = (target_stats.dex - 10) / 2;
    
    // Target roll: best of STR (Athletics) or DEX (Acrobatics)
    int athletics_roll = d20_roll() + str_mod_tgt;
    int acrobatics_roll = d20_roll() + dex_mod_tgt;
    res.target_roll = std::max(athletics_roll, acrobatics_roll);
    
    // Determine success (ties go to target)
    if (res.attacker_roll > res.target_roll) {
        res.success = true;
        res.escape_dc = 10 + str_mod_att + prof_bonus;
        applyGrappled(bm, action.target_idx, action.attacker_idx, res.escape_dc);
        res.log_message = fmt::format("{} grapples {} (attacker {} vs target {} — DC {})",
                                      agents[action.attacker_idx].agent->name(),
                                      agents[action.target_idx].agent->name(),
                                      res.attacker_roll, res.target_roll, res.escape_dc);
    } else {
        res.log_message = fmt::format("{} fails to grapple {} (attacker {} vs target {})",
                                      agents[action.attacker_idx].agent->name(),
                                      agents[action.target_idx].agent->name(),
                                      res.attacker_roll, res.target_roll);
    }
    
    log_(res.log_message);
    return res;
}
```

**Action C:** Add method `executeGrappleEscape()`:

```cpp
GrappleEscapeResult CombatEngine::executeGrappleEscape(BattleMap& bm, int agent_idx) noexcept {
    GrappleEscapeResult res;
    const auto& agents = bm.placedAgents();
    
    // Validate index
    if (agent_idx < 0 || agent_idx >= (int)agents.size()) {
        res.valid = false;
        res.log_message = "Invalid agent index";
        return res;
    }
    
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    
    // Check if actually grappled
    if (!cond.grappled) {
        res.valid = false;
        res.log_message = "Not grappled";
        return res;
    }
    
    res.valid = true;
    res.escape_dc = cond.grapple_escape_dc;
    
    // Get agent stats
    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int str_mod = (stats.str - 10) / 2;
    int dex_mod = (stats.dex - 10) / 2;
    
    // Roll best of STR (Athletics) or DEX (Acrobatics)
    int str_roll = d20_roll() + str_mod;
    int dex_roll = d20_roll() + dex_mod;
    res.escape_roll = std::max(str_roll, dex_roll);
    
    // Check success
    if (res.escape_roll >= res.escape_dc) {
        res.success = true;
        cond.grappled = false;
        cond.grappler_idx = -1;
        bm.setAgentConditions(agent_idx, cond);
        res.log_message = fmt::format("{} escapes grapple! (rolled {} vs DC {})",
                                      agents[agent_idx].agent->name(),
                                      res.escape_roll, res.escape_dc);
    } else {
        res.log_message = fmt::format("{} fails to escape grapple (rolled {} vs DC {})",
                                      agents[agent_idx].agent->name(),
                                      res.escape_roll, res.escape_dc);
    }
    
    log_(res.log_message);
    return res;
}
```

**Action D:** Modify `moveAgent()` to check grapple conditions

**Location:** Find the `moveAgent()` method in `combat.cpp`

**At the start of the method, add this block after initial validation:**

```cpp
// Check if agent is grappled — cannot move
Agent::Conditions cond = bm.getAgentConditions(agent_idx);
if (cond.grappled) {
    log_("Grappled creature cannot move (Speed = 0)");
    return false;
}

// Check if grapple should auto-end
if (cond.grappler_idx >= 0 && cond.grappler_idx < (int)agents.size()) {
    // Check if grappler is incapacitated
    Agent::Conditions grappler_cond = bm.getAgentConditions(cond.grappler_idx);
    if (grappler_cond.incapacitated) {
        cond.grappled = false;
        cond.grappler_idx = -1;
        bm.setAgentConditions(agent_idx, cond);
        log_("Grapple ended: grappler is incapacitated");
        return true;
    }
    
    // Check if distance exceeds grapple range
    Cell grappler_pos = agents[cond.grappler_idx].origin;
    Cell my_pos = agents[agent_idx].origin;
    int dist_cells = std::max(std::abs(my_pos.col - grappler_pos.col),
                             std::abs(my_pos.row - grappler_pos.row));
    if (dist_cells * 5 > cond.grapple_range_ft) {
        cond.grappled = false;
        cond.grappler_idx = -1;
        bm.setAgentConditions(agent_idx, cond);
        log_("Grapple ended: distance exceeds grapple range");
        return true;
    }
}

// Check if this agent is grappling someone — double movement cost
Cell origin = agents[agent_idx].origin;
int dist_ft = std::max(std::abs(dest.col - origin.col),
                      std::abs(dest.row - origin.row)) * 5;

for (int i = 0; i < (int)agents.size(); ++i) {
    if (i == agent_idx) continue;
    Agent::Conditions target_cond = bm.getAgentConditions(i);
    if (target_cond.grappled && target_cond.grappler_idx == agent_idx) {
        int extra_cost = dist_ft;  // extra movement to drag
        if (movement_budget_walk_ < extra_cost) {
            log_("Not enough movement to drag grappled creature");
            return false;
        }
        movement_budget_walk_ -= extra_cost;
        log_(fmt::format("Extra movement cost ({} ft) to drag grappled creature", extra_cost));
        break;
    }
}
```

**Action E:** Modify `executeAction()` to apply disadvantage for grappled attacks

**Location:** In `executeAction()`, find the attack-roll setup section (where disadvantage is applied for blinded, charmed, etc.)

**After existing disadvantage checks, add:**

```cpp
// Grappled: disadvantage on attacks except vs grappler
if (bm.getAgentConditions(attacker_idx).grappled) {
    if (action.target_idx != bm.getAgentConditions(attacker_idx).grappler_idx) {
        dis = true;
    }
}
```

**Action F:** Modify `executeSpell()` to apply disadvantage for grappled spell attacks

**Location:** In `executeSpell()`, find where attack rolls are set up (look for spell attack sections)

**After existing disadvantage checks, add the same grapple disadvantage logic:**

```cpp
// Grappled: disadvantage on spell attacks except vs grappler
if (spell.attack_type == Spell::AttackRoll) {
    if (bm.getAgentConditions(caster_idx).grappled) {
        if (target_idx != bm.getAgentConditions(caster_idx).grappler_idx) {
            dis = true;
        }
    }
}
```

---

### Step 1.4 — `gui/rpg_bindings.cpp` — Expose Grapple to Python

**Action A:** Add struct bindings for `GrappleAction`, `GrappleResult`, `GrappleEscapeResult`

**Location:** Find where other result structs are bound (look for `py::class_<AttackResult>`)

**Add these bindings:**

```cpp
py::class_<GrappleAction>(m, "GrappleAction")
    .def(py::init<>())
    .def_readwrite("attacker_idx", &GrappleAction::attacker_idx)
    .def_readwrite("target_idx", &GrappleAction::target_idx);

py::class_<GrappleResult>(m, "GrappleResult")
    .def(py::init<>())
    .def_readwrite("valid", &GrappleResult::valid)
    .def_readwrite("success", &GrappleResult::success)
    .def_readwrite("attacker_roll", &GrappleResult::attacker_roll)
    .def_readwrite("target_roll", &GrappleResult::target_roll)
    .def_readwrite("escape_dc", &GrappleResult::escape_dc)
    .def_readwrite("log_message", &GrappleResult::log_message);

py::class_<GrappleEscapeResult>(m, "GrappleEscapeResult")
    .def(py::init<>())
    .def_readwrite("valid", &GrappleEscapeResult::valid)
    .def_readwrite("success", &GrappleEscapeResult::success)
    .def_readwrite("escape_roll", &GrappleEscapeResult::escape_roll)
    .def_readwrite("escape_dc", &GrappleEscapeResult::escape_dc)
    .def_readwrite("log_message", &GrappleEscapeResult::log_message);
```

**Action B:** Add Conditions struct grapple fields binding

**Location:** Find the `Agent::Conditions` binding block

**Add these field bindings:**

```cpp
.def_readwrite("grappled", &Agent::Conditions::grappled)
.def_readwrite("grappler_idx", &Agent::Conditions::grappler_idx)
.def_readwrite("grapple_escape_dc", &Agent::Conditions::grapple_escape_dc)
.def_readwrite("grapple_range_ft", &Agent::Conditions::grapple_range_ft)
```

**Action C:** Update Conditions `__repr__` to include grappled status

**Location:** Find where `Conditions.__repr__` is defined (search for "Conditions" and "__repr__" or lambda binding)

**Update the repr lambda to include grappled:** Add a line like:
```cpp
if (cond.grappled) parts.push_back("grappled");
```

**Action D:** Add CombatEngine method bindings

**Location:** Find the CombatEngine binding block

**Add these method bindings:**

```cpp
.def("execute_grapple", &CombatEngine::executeGrapple, 
     py::arg("bm"), py::arg("action"))
.def("execute_grapple_escape", &CombatEngine::executeGrappleEscape,
     py::arg("bm"), py::arg("agent_idx"))
```

---

## PHASE 2: Python UI & Integration

### Step 2.1 — `gui/main.py` — Add Grapple UI and Logic

**Action A:** Add visual indicator for grappled agents

**Location:** Find `_draw_agents()` method

**Where other condition badges are drawn (like "FR" for Frightened), add:**

```python
# Draw grapple badge
if cur_cond.grappled:
    badge_color = (100, 150, 200)  # light blue
    badge_text = "GR"
    # Draw at position similar to other badges
    # (adjust coordinates as needed to not overlap with others)
```

**Action B:** Add "Grapple" action button

**Location:** Find `_draw_combat_panel()` method where action buttons are drawn

**Add button creation (alongside Attack, Dash, Dodge buttons):**

```python
self.btn_cbt_grapple = Button(..., "Grapple")
```

**Action C:** Add "Escape Grapple" button

**Add button creation (alongside Grapple button):**

```python
self.btn_cbt_escape_grapple = Button(..., "Escape Grapple")
```

**Action D:** Add button visibility logic

**In the section where buttons are shown/hidden, add:**

```python
# Show "Grapple" button when:
# - action not used
# - there's an adjacent enemy
cur_cond = self.combat.get_agent_conditions(self.bm, cur_idx)
can_grapple = (not self.action_used and 
               any(is_adjacent(cur_idx, other_idx) 
                   for other_idx in range(len(self.bm.placed_agents))))
self.btn_cbt_grapple.visible = can_grapple

# Show "Escape Grapple" button when:
# - agent is grappled
# - action not used
self.btn_cbt_escape_grapple.visible = (cur_cond.grappled and not self.action_used)
```

**Action E:** Add click handlers for Grapple button

**In the action button click section, add:**

```python
if self.btn_cbt_grapple.clicked(event):
    # Enter target-select mode
    self._enter_target_select_mode()
    # When target selected, call:
    # result = self.combat.execute_grapple(self.bm, 
    #          rpg.GrappleAction(attacker=cur_idx, target=selected_idx))
    # self._combat_log_add(result.log_message)
    # self.action_used = True
    # self._update_reach()
```

**Action F:** Add click handler for Escape Grapple button

**In the action button click section, add:**

```python
if self.btn_cbt_escape_grapple.clicked(event):
    result = self.combat.execute_grapple_escape(self.bm, cur_idx)
    self._flush_combat_log()
    self._combat_log_add(result.log_message)
    if result.success:
        cur_cond = self.combat.get_agent_conditions(self.bm, cur_idx)
        cur_cond.grappled = False
        self.combat.set_agent_conditions(self.bm, cur_idx, cur_cond)
    self.action_used = True
    self._update_reach()
    self._update_attack_overlay()
```

---

---

## Step 4 — `gui/combat.hpp` (declarations)

Add to combat.hpp:

```cpp
struct GrappleEscapeResult {
    bool valid{false};
    bool success{false};
    int escape_roll{0};
    int escape_dc{0};
    std::string log_message;
};

[[nodiscard]] GrappleEscapeResult executeGrappleEscape(BattleMap& bm, int agent_idx) noexcept;
```

---

## Step 5 — `gui/rpg_bindings.cpp`

In the `Agent::Conditions` binding block:

```cpp
.def_readwrite("grappled", &Agent::Conditions::grappled)
.def_readwrite("grappler_idx", &Agent::Conditions::grappler_idx)
.def_readwrite("grapple_escape_dc", &Agent::Conditions::grapple_escape_dc)
.def_readwrite("grapple_range_ft", &Agent::Conditions::grapple_range_ft)
```

Update the `Conditions.__repr__` lambda to include grappled status.

Add struct bindings:

```cpp
py::class_<GrappleAction>(m, "GrappleAction")
    .def(py::init<>())
    .def_readwrite("attacker_idx", &GrappleAction::attacker_idx)
    .def_readwrite("target_idx", &GrappleAction::target_idx);

py::class_<GrappleResult>(m, "GrappleResult")
    .def(py::init<>())
    .def_readwrite("valid", &GrappleResult::valid)
    .def_readwrite("success", &GrappleResult::success)
    .def_readwrite("attacker_roll", &GrappleResult::attacker_roll)
    .def_readwrite("target_roll", &GrappleResult::target_roll)
    .def_readwrite("escape_dc", &GrappleResult::escape_dc)
    .def_readwrite("log_message", &GrappleResult::log_message);

py::class_<GrappleEscapeResult>(m, "GrappleEscapeResult")
    .def(py::init<>())
    .def_readwrite("valid", &GrappleEscapeResult::valid)
    .def_readwrite("success", &GrappleEscapeResult::success)
    .def_readwrite("escape_roll", &GrappleEscapeResult::escape_roll)
    .def_readwrite("escape_dc", &GrappleEscapeResult::escape_dc)
    .def_readwrite("log_message", &GrappleEscapeResult::log_message);
```

Add CombatEngine method bindings:

```cpp
.def("execute_grapple", &CombatEngine::executeGrapple, py::arg("bm"), py::arg("action"))
.def("execute_grapple_escape", &CombatEngine::executeGrappleEscape, py::arg("bm"), py::arg("agent_idx"))
```

---

## Step 6 — `gui/main.py`

### Visual indicator

In `_draw_agents()`, draw a light blue "GR" badge over grappled agents (similar to "FR" for Frightened).

### Grapple button (Action)

In action buttons section (alongside Attack, Dash, Dodge):
- Show "Grapple" button only when:
  - Agent has not used action yet (`not self.action_used`)
  - There is an adjacent enemy (distance ≤ 1 cell)
- On click: Enter target-select mode → click enemy → call `combat.execute_grapple(bm, GrappleAction(attacker=cur_idx, target=clicked_idx))`
- Display result in combat log (success/failure + escape DC if successful)
- Mark action as used: `self.action_used = True`

### Escape Grapple button (Action)

In action buttons section, show only when:
- Agent is grappled (`cur_cond.grappled == True`)
- Agent has not used action yet (`not self.action_used`)

On click:
- Call `result = combat.execute_grapple_escape(bm, cur_idx)`
- Display result in combat log
- If success, `cur_cond.grappled = False` and update UI
- Mark action as used: `self.action_used = True`

---

## Verification Checklist

1. ✓ Unarmed/weapon attack with Grapple action initiates contested Athletics check
2. ✓ On success, target gains Grappled condition with escape DC = 10 + attacker's Athletics mod
3. ✓ Grappled creature cannot move (moveAgent returns false with "Speed = 0" log)
4. ✓ Grappled creature has disadvantage on attacks except against the grappler
5. ✓ Grappler moving while grappling pays extra movement cost (doubled total)
6. ✓ Grappled creature can use action to "Escape Grapple" (rolls best of STR/DEX vs DC)
7. ✓ Grapple auto-ends if grappler becomes Incapacitated
8. ✓ Grapple auto-ends if distance exceeds 5 ft
9. ✓ Grappler can voluntarily release by setting conditions.grappled = false (no action)
10. ✓ Visual "GR" badge appears on grappled agents
11. ✓ "Grapple" action button only shown when adjacent to enemy and action not used
12. ✓ "Escape Grapple" action button only shown when grappled and action not used
