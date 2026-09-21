# NPC Segmented Multiattack — Implementation Plan

**Status:** Ready to implement. Engine infra only, default-off. Written for a cold reload — self-contained.

## Goal
Let NPCs perform an ordered recipe of "X attacks with weapon slot A, then Y with slot B" per turn
(RAW multiattack, e.g. dragon "one Bite + two Claws"). Engine mechanism only; recipe **data** (the
per-monster JSON) is a **separate later pass**, not part of this cut.

## Decisions (locked)
- **Positioning policy:** *skip unreachable segments.* Position for a segment's weapon; if it can't be
  delivered (out of reach, no movement left to close), drop that segment's remaining swings and advance
  to the next segment. Do **not** end the whole turn.
- **Data source:** infra first; recipes JSON authored separately later. This cut authors **zero** real data.
- **Scope:** engine mechanism, **default-off** (empty recipe ⇒ today's exact behavior).
- **Applies to:** **NPC auto-turns only** (`runWeaponTurn`). PC path untouched.
- **Empty-slot ruling:** if a recipe segment references a slot whose weapon is empty, **skip that segment silently**.
- `num_attacks` is unchanged and remains the fallback; the recipe is authoritative when present.

## Current architecture (verified 2026-07-01)
- `Agent::Stats.num_attacks` (`gui/agent.hpp:119`) is the entire multiattack model today (single int).
- NPCs have 3 weapon slots: main_hand(0), off_hand(1), ranged(2) (`getAgentWeapons` → `std::array<Weapon,3>`).
- `runWeaponTurn` (`gui/combat_turn.cpp:1361`) picks **one** slot via policy (`npcSelectWeapon` /
  `npcSelectRangedWeapon`), seeds `attacks_remaining = num_attacks`, swings that **same** slot N times.
- `NpcTurnState` (`gui/combat.hpp:676`) holds `weapon_idx`, `attacks_remaining`, `target_idx`, `phase`.
- `pybind11/stl.h` is already included (`gui/rpg_bindings.cpp:22`) → `std::vector<std::pair<int,int>>`
  auto-binds to a Python list-of-tuples. Assign the whole vector; never mutate elements in place
  (def_readwrite on containers returns a copy — the pybind array-copy gotcha).
- Serialization round-trip sites confirmed: save block `gui/main.py:9291`, load `gui/agent_loader.py:40`.

---

## Step 1 — Data field (`gui/agent.hpp`, immediately after line 119 `num_attacks`)
```cpp
// NPC multiattack recipe: ordered (weapon_slot 0..2, count) segments.
// Empty ⇒ legacy behavior (num_attacks swings with one auto-selected slot). NPC auto-turn only.
std::vector<std::pair<int,int>> multiattack;
```

## Step 2 — Binding (`gui/rpg_bindings.cpp:279`, beside the `num_attacks` def_readwrite)
```cpp
.def_readwrite("multiattack", &Agent::Stats::multiattack)
```

## Step 3 — Serialization round-trip (BOTH sites — mandatory or it resets on save/reload)
- **Save** — `gui/main.py:9291`, add sibling to the `"num_attacks"` line:
  ```python
  "multiattack": [[int(slot), int(n)] for (slot, n) in s.multiattack],
  ```
- **Load** — `gui/agent_loader.py:40`, after the `stats.num_attacks` line:
  ```python
  stats.multiattack = [(int(a), int(b)) for a, b in stats_dict.get("multiattack", [])]
  ```

## Step 4 — Turn state (`gui/combat.hpp:676` `NpcTurnState`)
Keep `weapon_idx` + `attacks_remaining` as the **current** segment's weapon and remaining swings;
add the queue of segments that follow:
```cpp
// Multiattack recipe segments pending AFTER the current (weapon_idx, attacks_remaining) one.
// Each is (weapon_slot, count). Empty ⇒ legacy single-weapon multiattack.
std::vector<std::pair<int,int>> pending_segments;
```
(These live in `st`, so they survive park→resume automatically.)

## Step 5 — Execution (`gui/combat_turn.cpp`, the only real logic change)

### 5a. Seed from recipe in `PickAndMove`
There are three seed sites that currently do
`st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);`
(lines ~1387, ~1394, ~1403). Add a helper and call it at all three (or seed once before the branch).

Helper (place near the top of `runWeaponTurn` or as a file-local lambda):
```cpp
// Returns true if a non-empty recipe was applied (sets st.weapon_idx / attacks_remaining /
// pending_segments to the first deliverable segment). Skips leading empty-weapon slots.
auto seedFromRecipe = [&](NpcTurnState& s) -> bool {
    const auto& ma = bm.getAgentStats(agent_idx).multiattack;
    if (ma.empty()) return false;
    const auto weapons = bm.getAgentWeapons(agent_idx);
    s.pending_segments.assign(ma.begin(), ma.end());
    // pop leading segments whose slot is invalid or whose weapon is empty (empty-slot ruling)
    while (!s.pending_segments.empty()) {
        auto [slot, cnt] = s.pending_segments.front();
        s.pending_segments.erase(s.pending_segments.begin());
        if (slot < 0 || slot > 2 || cnt <= 0) continue;
        if (weapons[static_cast<std::size_t>(slot)].name.empty()) continue;
        s.weapon_idx = slot;
        s.attacks_remaining = cnt;
        return true;
    }
    return false;   // recipe present but nothing deliverable → caller falls back to legacy
};
```
At each seed site, replace the plain `attacks_remaining = num_attacks` with:
```cpp
if (!seedFromRecipe(st)) st.attacks_remaining = std::max(1, bm.getAgentStats(agent_idx).num_attacks);
```
Note: when the recipe applies, `st.weapon_idx` is set to the FIRST segment's slot BEFORE the
`reachNow`/`findPositionCell` positioning logic runs — so positioning already targets the right weapon.
The recipe overrides `prefer_ranged` weapon selection. `kite` is ignored when a recipe is present
(documented simplification — kite + a melee segment is contradictory). The `st.weapon_idx` initial
selection at `combat_turn.cpp:1368` still runs first; the seed then overwrites it — that's fine.

### 5b. Segment-walking attack loop (replace the `while (st.attacks_remaining > 0)` loop, ~1420–1448)
```cpp
if (st.phase == NpcTurnState::Attacking) {
    while (true) {
        if (st.attacks_remaining <= 0) {
            if (st.pending_segments.empty()) break;          // recipe exhausted (or legacy done)
            // advance to next segment; skip invalid/empty-weapon slots
            const auto weapons = bm.getAgentWeapons(agent_idx);
            bool advanced = false;
            while (!st.pending_segments.empty()) {
                auto [slot, cnt] = st.pending_segments.front();
                st.pending_segments.erase(st.pending_segments.begin());
                if (slot < 0 || slot > 2 || cnt <= 0) continue;
                if (weapons[static_cast<std::size_t>(slot)].name.empty()) continue;
                st.weapon_idx = slot;
                st.attacks_remaining = cnt;
                advanced = true;
                break;
            }
            if (!advanced) break;
            continue;   // re-evaluate reach for the NEW weapon
        }
        // Re-acquire if the current target dropped mid-multiattack.
        if (!npcAttackable(bm, agent_idx, st.target_idx)) {
            const int nt = selectTarget();
            if (nt < 0) break;                                // nobody left
            st.target_idx = nt;
        }
        // Step in with leftover movement if out of reach for THIS segment's weapon.
        if (!inReachOf(st.target_idx, st.weapon_idx)) {
            Cell dest{};
            if (findPositionCell(st.target_idx, st.weapon_idx, dest)) {
                if (dest != curOrigin()) {
                    if (beginMove(bm, agent_idx, dest, MovementType::Walk) == FlowStatus::AwaitingDecision)
                        return FlowStatus::AwaitingDecision;
                }
            }
            if (!inReachOf(st.target_idx, st.weapon_idx)) {
                st.attacks_remaining = 0;   // SKIP this segment (skip-unreachable policy), try next
                continue;
            }
        }
        Attack a;
        a.attacker_idx = agent_idx;
        a.target_idx   = st.target_idx;
        a.weapon_idx   = st.weapon_idx;
        a.attack_slot  = "action";
        --st.attacks_remaining;   // BEFORE beginAttack: a park→resume must not repeat this swing
        renderAttack(agent_idx, st.target_idx);
        if (beginAttack(bm, a) == FlowStatus::AwaitingDecision)
            return FlowStatus::AwaitingDecision;
    }
}
```
**Legacy path is preserved:** with an empty recipe, `pending_segments` is empty and `attacks_remaining`
is seeded from `num_attacks`; the loop degrades to exactly the old single-weapon behavior. The old loop
`break`-on-unreachable becomes `attacks_remaining=0; continue`, which for the empty-recipe case ends the
turn identically (no pending segments to advance to).

## Step 6 — Test (`gui/test_npc_multiattack.py`) — I write it, USER runs it
- **Composition:** NPC `multiattack=[(0,1),(1,2)]`, two distinct weapons (distinguish by damage type or a
  per-weapon hit counter), one enemy in reach → assert exactly 1 swing on slot 0 then 2 on slot 1.
- **Skip-unreachable:** a segment whose weapon can't reach with no movement left → that segment dropped,
  turn ends cleanly, no crash, no repeat; earlier reachable segments still executed.
- **Empty-slot skip:** recipe references an empty slot → that segment silently skipped.
- **Legacy untouched:** empty `multiattack` → identical swing count/behavior vs `num_attacks` today.

## Explicitly OUT of scope this cut
- Recipe JSON authoring + `tools/monster_parser.py` wiring (separate one-time pass; can be done
  independently of engine + main.py).
- PC path (`gui/main.py:3434 / 5776 / 5820`) — unchanged.
- Mixed-reach optimization/reordering — we take the simple skip policy on purpose.

## Handoff / build split
- Steps 1, 2, 4, 5 are C++ → require **one rebuild** (Docker rpg_map; USER builds).
- Step 3 is Python-only.
- Opus edits + writes the test, then STOPS. USER builds and runs the test suite.
- Round-trip rule (memory: stats_serializer_roundtrip): new Stats field MUST be in BOTH agent_loader
  dict_to_stats AND main.py save block — Step 3 covers both.
