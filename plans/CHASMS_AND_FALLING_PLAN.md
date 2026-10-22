# Chasms and falling

**Status 2026-10-22: plan only. Nothing painted, nothing built.** Asked for while laddering
Castle Ravenloft: drops are not ladders. The K59 380 ft drop and the Map 8 K20 190 ft pit
drop were ladders. Both are now removed.

## What the user decided (2026-10-22)

- **A drop is never a ladder.** Ladders are for climbing between floors. Pits, shafts and
  open edges are terrain.
- **A creature that goes into a chasm dies.** No saving throw and no damage roll.
- **A shaft has a bottom.** A creature that falls into a shaft lands at the bottom the book
  gives, not on the first floor below. Book examples: the K20 pit on Map 8 drops to the
  Main Floor (190 ft), and the K18 shaft at K59 drops to the Catacombs (380 ft).

## What exists today

- `TerrainType::Chasm` (`gui/battle_map.hpp`): walking, burrowing and swimming can't enter it;
  a jump clears it (`MovementType::Jump`, `battle_map.cpp`). Painted as a pixel-rectangle
  region (`{"type": "Chasm", "x", "y", "width", "height"}`) in a page's `_terrain.json`,
  applied by `_apply_terrain_to_battle_map`. It is a wall you can jump over, so nobody can
  ever fall in.
- Ladders (`_use_ladder` → `_switch_to_page(page, drop_cell, carry)`) already move one
  creature to another page at a global cell. Crossing is refused in combat.
- Nothing applies falling damage, and nothing moves a creature it didn't choose to move
  (no shove, no push spell, no failed-jump fall).

## Two kinds of drop

| Kind | Stored as | Entering it |
|---|---|---|
| **Chasm**: bottomless, or too deep to matter | `Chasm` region (exists) | The creature dies. It is removed from the board as dead, and the log says it fell. |
| **Shaft**: has a known bottom | new `Shaft` region with a `landing` global `[X, Y, Z]` (or a per-region "lands on floor Z, same X, Y") | The creature is carried to the landing page at the landing cell. It takes 1d6 bludgeoning per 10 ft fallen (max 20d6, SRD 5.2) and lands Prone unless it took no damage. Fall height = (from Z − to Z) × the dungeon's storey height, or a per-shaft `drop_ft` (book numbers: 190, 380). |

**D1 (open): is "shaft" its own terrain, or a Chasm with a landing set?** Recommended:
a Chasm region gains an optional `landing`. No landing means it is bottomless and kills; with
a landing it is a shaft. That keeps one paint tool and one terrain type in the engine.

## How a creature gets in

1. **It chooses to.** Walking into a chasm or shaft cell is offered as an explicit action
   ("Jump into the shaft"), like a ladder. Ordinary movement still treats it as impassable,
   so pathing never walks anyone off a ledge by accident.
2. **A failed jump.** A jump that would end on a chasm or shaft cell. Today the engine only
   lets a jump clear it. **D2 (open):** should a jump that falls short drop the creature in?
3. **Forced movement.** Shove and push effects don't exist yet. When they do, being moved
   into a drop cell runs the same fall.

## Combat

Ladders and page changes are refused in combat, because only one page is simulated at a
time. A death in a chasm needs no page change, so it works in and out of combat. A shaft
fall during combat would take the creature off the current page.
**D3 (open):** in combat, does the fallen creature leave initiative (removed from this
fight, placed on the landing page frozen), or is the fall refused until combat ends?

## Castle Ravenloft inventory (to paint once this is built)

| Drop | Floor(s) | Kind | Lands |
|---|---|---|---|
| K20 big tower pit | Maps 6, 7, 8 (Z3–Z5); the pit continues on Rooms of Weeping and the Court | shaft | Main Floor K20 (Z0) |
| K18 High Tower shaft | High Tower Peak K59 (Z6), down through each floor's K18 hole | shaft | Catacombs K18 (Z−2) |
| K18 shaft below the Main Floor ("down 10 ft to new wall, 80 ft to Map 12") | Main (Z0), Larders (Z−1) | shaft | Catacombs (Z−2) |
| Cliff and courtyard edges, the K6 bridge drop (Map 2, not a page yet) | n/a | chasm | none, death |

## Steps (when approved)

1. **Data:** Chasm region gets optional `landing` and `drop_ft`. Terrain editor: the Chasm
   tool asks for the landing (pick a floor; the cell defaults to the same global X, Y).
2. **Engine:** a fall resolver (death, or carry + fall damage + Prone), and an
   "enter drop" action on the creature menu.
3. **GUI:** the landing page switch reuses `_switch_to_page(..., carry=[idx])`.
4. **Tests (container, `./test.sh`):** chasm entry kills; a shaft carries the creature to the
   landing cell; damage is capped at 20d6 and Prone is applied; ordinary movement never
   paths into a drop; a combat fall follows D3.
5. Paint the Ravenloft inventory above.
