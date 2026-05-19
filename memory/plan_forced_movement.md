# Forced Movement Implementation Plan

## Context
The D&D battle map currently has no forced movement mechanics. We need:
- Shove (bonus action, contested Athletics → push 5ft or knock prone)
- Spell-based push (Thunderwave, Gust of Wind — push away from caster on failed save)
- Weapon push on hit (requires proficiency, uses new `push_ft` field)
- Unarmed strike (1 + STR bludgeoning, uses proficiency)

**Architecture rule:** All logic lives in C++. Flow: `CombatEngine` resolves contest/save → calls `BattleMap::forceMoveAgent`. Python handles UI only.

---

## Step 1: `condition.hpp` — Add `push_ft` field

Add a dedicated `push_ft` field to `AttackCondition` (NOT reusing `condition_duration`):

```cpp
struct AttackCondition {
    std::string condition_name;       // "Stunned", "Push", "Prone", etc.
    int condition_duration = 0;       // turns lasting (0 = instant for Push)
    int push_ft = 0;                  // feet to push (used by "Push" and future telekinesis etc.)
    int save_repeat_turns = 1;
    SaveAbility_t save_ability = SaveDex;
    SaveAbility_t save_dc_ability = SaveWis;
};
```

Update `helpers.py` `_dict_to_spell()` and weapon JSON loading to read `"push_ft"` from JSON.

---

## Step 2: `battle_map.hpp` / `battle_map.cpp` — `forceMoveAgent()`

Add to `BattleMap`:

```cpp
// Returns cells actually moved (may be less than push_ft/5 if blocked by wall)
int forceMoveAgent(int idx, Cell push_from, int push_ft) noexcept;
```

Logic:
- Compute direction: `sign(target.col - push_from.col)`, `sign(target.row - push_from.row)`
- Move cell-by-cell for `push_ft / 5` steps
- Each step: if next cell is blocked or out of bounds, stop
- Update `pa.origin` and `pa.agent->setPosition(next.col, next.row)` each step
- Does NOT consume movement budget
- If diagonal direction is blocked, try each orthogonal axis as fallback

---

## Step 3: `combat.hpp` — Result structs + ShoveAction/ShoveResult

**Add `push_ft_applied` to results:**

```cpp
struct AttackResult {
    // ... existing fields ...
    int push_ft_applied = 0;
};

struct SpellTargetResult {
    // ... existing fields ...
    int push_ft_applied = 0;
};
```

**New structs:**

```cpp
struct ShoveAction {
    int attacker_idx;
    int target_idx;
    bool knock_prone;   // true = knock prone; false = push 5ft
};

struct ShoveResult {
    bool valid = false;
    bool success = false;
    int attacker_roll = 0;
    int defender_roll = 0;
    int push_ft_applied = 0;
    bool knocked_prone = false;
    std::string log_message;
};

[[nodiscard]] ShoveResult executeShove(BattleMap& bm, const ShoveAction& action);
```

---

## Step 4: `combat.cpp` — Handle "Push" + implement `executeShove()`

**In `executeAction()` — after applying weapon conditions on hit:**
```cpp
if (cond.condition_name == "Push" && cond.push_ft > 0) {
    bool proficient = attack.weapon.proficient;  // only push if proficient
    if (proficient) {
        int moved = bm.forceMoveAgent(target_idx, attacker_origin, cond.push_ft);
        result.push_ft_applied = moved * 5;
    }
}
```

**In `executeSpell()` — after applying spell conditions on failed save:**
```cpp
if (cond.condition_name == "Push" && cond.push_ft > 0) {
    // No proficiency check for spells
    int moved = bm.forceMoveAgent(target_idx, caster_origin, cond.push_ft);
    target_result.push_ft_applied = moved * 5;
}
```

**`executeShove()` logic (C++ — full contest):**
1. Validate: target must be within 5ft (adjacent) of attacker
2. Roll attacker Athletics: `d20 + STR mod + (proficient ? prof_bonus : 0)`
3. Roll defender: `max(d20 + STR mod, d20 + DEX mod)` (Athletics vs Acrobatics, take higher)
4. Attacker wins if `attacker_roll > defender_roll` (ties go to defender)
5. If success and `knock_prone`: call `applyProne(bm, target_idx)`
6. If success and `!knock_prone`: call `bm.forceMoveAgent(target_idx, attacker_origin, 5)`
7. Build and return `ShoveResult` with full log message

**Unarmed strike**: Build synthetic `Attack` in Python with 1+STR bludgeoning, proficiency=true, call `execute_action` — no new C++ struct needed.

---

## Step 5: `rpg_bindings.cpp` — Expose new API

- `bm.force_move_agent(idx, push_from, push_ft)` → int
- `AttackResult.push_ft_applied` read-only
- `SpellTargetResult.push_ft_applied` read-only
- `ShoveAction` struct (attacker_idx, target_idx, knock_prone)
- `ShoveResult` struct (all fields read-only)
- `combat.execute_shove(bm, action)` → ShoveResult

---

## Step 6: `spells.json` — Add push conditions

```json
// Thunderwave (push 10ft on failed CON save)
"conditions": [{"condition_name": "Push", "push_ft": 10, "save_ability": "SaveCon"}]

// Gust of Wind (push 15ft on failed STR save)
"conditions": [{"condition_name": "Push", "push_ft": 15, "save_ability": "SaveStr"}]
```

---

## Step 7: `helpers.py` — Parse `push_ft` in `_dict_to_spell()` and weapon loader

Add `push_ft` to condition parsing:
```python
c.push_ft = cond_dict.get("push_ft", 0)
```

---

## Step 8: `main.py` — UI only

- **Shove button**: Under **Bonus Action** section only. Show when bonus not used AND an enemy is adjacent (≤5ft). Two sub-options: "Push 5ft" and "Knock Prone".
- **Shove flow**: Click Shove → pick option (push/prone) → enter target-select mode → click target → call `execute_shove(bm, ShoveAction(...))` → log result → update overlays
- **Unarmed strike button**: Show alongside weapon attack buttons in Action section. Synthetic attack built in Python from agent STR stat.
- **Post-push update**: Any result with `push_ft_applied > 0` → call `_update_reach()` + `_update_attack_overlay()`

---

## Critical files

| File | Change |
|------|--------|
| `condition.hpp` | Add `push_ft` field to `AttackCondition` |
| `battle_map.hpp` | Declare `forceMoveAgent` |
| `battle_map.cpp` | Implement `forceMoveAgent` |
| `combat.hpp` | Add `push_ft_applied` to results; add `ShoveAction`/`ShoveResult`; declare `executeShove` |
| `combat.cpp` | Handle "Push" condition in `executeAction`/`executeSpell`; implement `executeShove` |
| `rpg_bindings.cpp` | Expose all new methods/structs |
| `helpers.py` | Parse `push_ft` in condition loading |
| `main.py` | Shove (bonus action), unarmed strike, post-push overlay refresh |
| `spells.json` | Add push conditions to Thunderwave, Gust of Wind |

---

## Verification
1. Thunderwave: targets on failed CON save pushed 10ft away from caster
2. Gust of Wind: targets on failed STR save pushed 15ft away
3. Shove (push): target moves 5ft away from attacker
4. Shove (prone): target gets prone condition
5. Shove into wall: target moves 0ft (stops at wall), no crash
6. Diagonal push blocked: falls back to orthogonal
7. Weapon push: only fires if attacker is proficient
8. Unarmed strike: 1 + STR mod bludgeoning damage, proficiency applies

---

## Post-Implementation Notes

### Grapple UI Refactoring (TODO)
The Grapple button is currently a separate button, but it should be an unarmed attack option instead. When implementing unarmed strikes (punch, kick, headbutt, etc.), Grapple should be one of the available unarmed attack options. This will be done when completing the unarmed strike implementation.
