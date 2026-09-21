# PreferHide — Implementation Spec (NPC Automation Step 7)

Fills **Step 7** of `NPC_AUTOMATION_PLAN.md`. The `PreferHide` enum value + GUI picker
("Prefer Hide") already exist (Step 1); today it falls through to `Simple`. This spec
gives it an executor: a ranged attacker that strikes from stealth and re-conceals each
round.

**Workflow:** Opus edits; the **USER builds and runs the tests**; then the user *clears*
the checkpoint. Do not proceed to the next checkpoint until the current one is cleared.

---

## Behaviour — locked decisions

PreferHide is a **PreferRange attack** (best ranged weapon, focus **lowest-HP** target)
with `kite = false` (spend the *minimum* movement to reach range+LoS, save the rest for
the retreat), followed by a **conceal** step. Entering a turn already Hidden/Invisible
gives the attack advantage automatically (engine already does this at
`combat_attack.cpp:2177` / `combat_spells.cpp:169`) and the swing reveals the attacker —
so from round 2 on the loop self-sustains.

"Move to cover" = a reachable cell with **no opposing agent's line of sight** to the
agent's footprint (same LoS test `checkHide` uses).

### Per-turn decision tree (after target selection)

**No reachable target** → pure ambush: if already Hidden, stay put; else move to the
nearest no-LoS cover cell and **Hide as an Action** (free — no attack was made, so
`has_cunning_action` is NOT required here).

**Target exists** — pick the first viable conceal route, in this priority:

| Route | Condition | Turn |
|-------|-----------|------|
| **A** | Castable self-Invisibility with `casting_time == BonusAction` | attack (action) → retreat to cover → **bonus-cast Invisibility**. Best: full damage *and* stealth every turn, no LoS constraint. Preferred over B. |
| **B** | `has_cunning_action` **and** a reachable no-LoS cover cell exists | attack (action) → move to nearest no-LoS cover → **bonus-action Hide** (`checkHide`) |
| **C** | Knows self-Invisibility as an **Action** cast | *already Invisible:* attack w/ adv (action) → retreat to cover.  *else:* **cast Invisibility (action), NO attack** → retreat to cover. (alternates cast/attack across rounds) |
| **D** | none of the above | plain PreferRange kite (`kite=true`) — never idle |

Route B, when no cover is reachable post-attack, ends exposed (the action is already
spent on the attack; it does **not** fall back to C). It re-tries next round.

"Self-Invisibility spell" = a castable **Help** spell that grants the **Invisible**
condition to the caster. **Prefer Greater Invisibility** when known (it persists through
attacks, so routes A/C don't self-reveal).

---

## Architecture — where the logic lives

Reuse the one shared weapon executor. Add a **`conceal` policy flag** to
`NpcStrategyPolicy`; `runWeaponTurn` is byte-for-byte unchanged when `conceal == false`.
When set, `runWeaponTurn` gains (a) a top-of-turn "skip the attack" short-circuit for
route C-cast, and (b) a **`Conceal` tail phase** after the attack loop. No second turn
driver. Dispatch:

```cpp
case NpcAutomationStrategy::PreferHide:
    policy.prefer_ranged = true;
    policy.priority      = NpcTargetPriority::LowestHp;
    policy.conceal       = true;          // kite stays false; route D flips it on internally
    break;                                 // → runWeaponTurn(bm, idx, policy)
```

**Bucket-D exemption:** add `&& strategy != NpcAutomationStrategy::PreferHide` to the
recharge-AoE auto-route guard in `runNpcTurn` (a hider must not be hijacked into breathing).

### New member helpers (combat.hpp / combat_turn.cpp)
- `int npcFindSelfInvisSpell(const BattleMap&, int idx, Spell::CastingTime_t want) const`
  — index of a castable spell that grants **Invisible** to the caster with casting time
  `want`; prefer Greater Invisibility; `-1` if none. (Uses `availableCastableSpells`.)
- `bool npcFindCoverCell(const BattleMap&, int idx, Cell& out) const` — nearest reachable
  cell (live walk budget) with **no enemy LoS** to the agent's footprint; `false` if none.
  Mirrors `checkHide`'s LoS loop + `reachableCells`; geometry single-sourced.
- `NpcConcealRoute npcClassifyConceal(const BattleMap&, int idx) const` — returns A/B/C/D
  per the table (checks `has_cunning_action`, the two invis finders, current `invisible`).

### `NpcTurnState` additions (mirrors `aoe_cast_launched` / `aoe_moving`)
- extend `enum Phase { PickAndMove, Attacking, Conceal, Done }`
- `int  conceal_route{0};`         — cached route so a park→resume is stable
- `int  conceal_spell_idx{-1};`    — chosen invis spell (route A bonus / route C action)
- `bool conceal_move_launched{false};` — post-attack cover move started (resume: don't re-move)
- `bool conceal_act_launched{false};`  — Hide/cast started (resume after Counterspell: don't re-cast)

All conceal actions use the existing **parkable** primitives (`beginMove`, `beginCast`,
`spendBonusAction`), so OA / reaction / Counterspell windows surface exactly as they do
for player actions. `checkHide` is not itself parkable (a contested roll, no reaction
window) — call it inline after the cover move resolves.

---

## Checkpoints

### CP0 — Scaffolding + PreferHide = focused ranged attacker  ✅ DONE (build green, tests clean 2026-07-03)
- `NpcStrategyPolicy.conceal` flag; `NpcTurnState` `Conceal` phase + the four fields.
- Dispatch case above; Bucket-D exemption.
- Conceal tail is a **no-op** for now (falls straight to `Done`). Route D short-circuit
  not needed yet.
- **Behaviour:** PreferHide picks the best ranged weapon, focus-fires the lowest-HP
  enemy, moves the minimum to reach range+LoS, attacks, ends. (== PreferRange but not
  kiting.)
- **Test** (`test_npc_automation.py`): `test_hide_focus_fires_lowest_hp` — ranged NPC set
  to PreferHide attacks the lowest-HP of two enemies and ends its turn.
- **CLEAR when:** builds; the test passes; no regression in existing NPC tests.

### CP1 — Cover finder + invis-spell finder (pure helpers)  ✅ DONE (build green, tests clean 2026-07-03)
- Implement `npcFindCoverCell` and `npcFindSelfInvisSpell` (+ bind them read-only if
  needed for the test, or test through a route). `npcClassifyConceal` may land here too.
- **Tests:**
  - `test_hide_cover_cell_found` — NPC exposed on open ground with a wall segment nearby:
    finder returns a reachable cell with no enemy LoS; when fully exposed (no wall in
    range) it returns none.
  - `test_hide_invis_finder` — an NPC granted "Invisibility" (Action) → finder(Action)
    hits, finder(BonusAction) misses; add a BonusAction-cast copy → finder(BonusAction)
    hits; with "Greater Invisibility" present the finder prefers it.
- **CLEAR when:** both helpers correct in isolation.

### CP2 — Route B (cunning-action cover Hide)  ✅ DONE (build green, tests clean 2026-07-03)
- Full loop: attack → move to nearest no-LoS cover → `spendBonusAction` + `checkHide`.
  Parkable/resumable via the new state fields.
- **Tests:**
  - `test_hide_route_b_attacks_then_hides` — `has_cunning_action` ranged NPC with cover in
    range: attacks, ends **Hidden**.
  - `test_hide_route_b_advantage_when_prehidden` — start the NPC Hidden; its attack rolls
    with advantage (assert via the attack result / log), then it re-hides.
  - `test_hide_route_b_no_cover_ends_exposed` — no reachable no-LoS cell: attacks, ends
    NOT hidden, no crash, bonus action unspent.
- **CLEAR when:** route B behaves across all three.

### CP3 — Route C (action Invisibility, alternating)  ✅ DONE (build green, tests clean 2026-07-06)
- Top-of-turn skip-attack short-circuit: no `has_cunning_action`, no bonus-invis, knows
  Action-invis, not currently Invisible → cast Invisibility (action) via `beginCast`, no
  attack, then retreat to cover. Already Invisible → attack w/ adv, then retreat.
- **Test:** `test_hide_route_c_alternates` — NPC with Action-Invisibility, no cunning
  action: turn 1 casts Invisibility and makes **no** attack (target HP unchanged), ends
  Invisible; turn 2 (still Invisible at start) attacks **with advantage** and reveals.
- **CLEAR when:** the cast/attack alternation holds and the turn-1 attack is genuinely skipped.

### CP4 — Route A (bonus-action Invisibility)  ✅ DONE (build green, tests clean 2026-07-06)
- attack (action) → retreat to cover → bonus-cast the BonusAction invis spell. Chosen
  over B when both are available.
- **Tests:**
  - `test_hide_route_a_attack_and_bonus_invis` — NPC with a BonusAction invis spell
    attacks (target takes damage) **and** ends Invisible in one turn.
  - `test_hide_route_a_beats_route_b` — NPC has both a BonusAction invis spell and
    `has_cunning_action` → uses A (ends Invisible, not merely Hidden).
- **CLEAR when:** route A fires and outranks B.

### CP5 — No-target ambush + Route D + full sweep  ✅ DONE (build green, tests clean 2026-07-06)
- No attackable target → move to nearest no-LoS cover and **Hide as an Action** (any
  creature); if already Hidden, hold. Route D (no stealth tools, has a target) → set
  `kite=true` and run the plain PreferRange path.
- **Tests:**
  - `test_hide_no_target_ambush` — lone PreferHide NPC (all enemies down/removed) with
    cover reachable ends **Hidden**.
  - `test_hide_route_d_falls_back_to_kite` — PreferHide NPC with no cunning action and no
    invis spell kites like PreferRange (moves to maximise distance, attacks).
- Register every new test in `run_all_tests.py`.
- **CLEAR when:** full `test_npc_automation.py` is green and the user confirms in live play.

---

## Files
`combat.hpp` (`NpcStrategyPolicy.conceal`, `NpcTurnState` phase+fields, `NpcConcealRoute`
enum + 3 helper decls), `combat_turn.cpp` (dispatch case + Bucket-D exemption + the
conceal short-circuit/tail in `runWeaponTurn` + the 3 helpers), `rpg_bindings.cpp`
(`run_npc_turn` docstring; bind any helper a test reaches directly), `test_npc_automation.py`
+ `run_all_tests.py`. No GUI change (picker already lists "Prefer Hide").
