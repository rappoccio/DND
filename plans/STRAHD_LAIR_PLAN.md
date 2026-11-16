# Strahd lair actions (Castle Ravenloft)

Drafted 2026-11-16. **Status: Step 0 signed off 2026-11-16 with the amendments below. FROZEN. L1–L6b implemented 2026-11-16, suite 257/0, uncommitted; L7 headless check done, DM run.sh pass pending.**

Four Castle Ravenloft abilities for Strahd, plus two buffed stat blocks:

| # | Ability | Short name |
|---|---------|------------|
| A | Pass through walls, doors, ceilings, floors until count 20 next round | **Phase** |
| B | Open/close any number of visible doors/windows; closed ones may be magically locked (DC 20 Str to force) until Strahd ends it or reuses the action | **Doors** |
| C | Apparition (Strahd Specter) appears next to a visible hostile, makes one attack, vanishes | **Apparition** |
| D | Medium-or-smaller creature with a shadow, visible, within 30 ft: DC 17 Cha save or its shadow becomes a Strahd Shadow, acting on count 20; greater restoration / remove curse restores it only once that shadow is destroyed | **Shadow theft** |

New bestiary entries (data only):
- **Strahd Specter**: copy of Specter, Melee +7 to hit, 30 HP, CR 5.
- **Strahd Shadow**: copy of Shadow, Melee +7 to hit, 30 HP, CR 5.

## What already exists (inventory, done 2026-11-16)

- **Legendary phase** (`main.py` `_begin_legendary_phase` … `_begin_legendary_dash`): a menu after
  each enemy turn; options are weapon attacks, Dash/DashHalf, or bestiary `action_spells`.
  Nothing for lair actions; `has_lair` / `is_in_lair` only pick the bigger legendary budgets.
- **Initiative**: `self.initiative_order` is a list of `rpg.InitiativeEntry` with a `total`;
  Thief's Reflexes already inserts an extra entry mid-order (`_thief_reflexes_extra`). That's the pattern for a count-20 entry.
- **Doors** (`battle_map.hpp` `Door`): open / locked / lock_dc / break_dc / broken /
  arcane_lock / secret / hidden; `CombatEngine::attemptBreakDoor` handles Str (Athletics) to force.
- **Summons** (`_spawn_summon`): spawns a bestiary creature linked to a caster and its faction.
- **Weapon** has `bonus_hit` (flat to-hit), so +7 is reachable in data.
- Specter's Life Drain rider (HP max reduction) is **not** in its JSON (`conditions: []`);
  the engine already has a `reduceHPMax` rider (Strahd's Bite uses it).

## Decisions (D1–D9): proposed, need your sign-off

- **D1. Lair actions or legendary actions?** The text you quoted is Strahd's *lair* actions:
  once per round, on initiative count 20 (losing ties). **Proposed:** a real **Lair entry at
  count 20** is inserted into initiative while a `has_lair` creature is in combat and alive.
  On that entry the DM gets a menu with the four lair actions (or Pass). Strahd can't pick
  the same lair action two rounds in a row (RAW); the menu greys out last round's pick.
  Alternative: add them as options to Strahd's legendary-action menu. That's simpler, but
  "count 20" then has no anchor.
- **D2. Which creatures get it.** Proposed: bestiary `legendary.lair_actions: ["Phase",
  "Doors", "Apparition", "Shadow theft"]` on Strahd only. The four are coded as named
  handlers, not a general lair-action language.
- **D3. Phase.** A per-agent flag with an expiry ("until count 20 next round"). While it is
  set, Walk/Fly pathing treats walls and closed doors as passable for that agent only. Line
  of sight is unchanged. Proposed: **a move may not end inside a wall or closed door**, so
  no token gets stuck. *Ceilings/floors* (moving between dungeon levels) is out of scope;
  the DM moves him between pages by hand.
- **D4. Doors.** Proposed: click doors Strahd can see (LOS from his cells to any door cell or
  edge) to cycle each through **Open → Close → Close + Lock → (unchanged)**, then Confirm.
  The lock is a new Door state `lair_lock` (owner = Strahd's idx). While it is set:
  - opening fails;
  - Pick Lock fails;
  - Knock does nothing (proposed: it's Strahd's magic, not Arcane Lock);
  - forcing it is a **DC 20 Str (Athletics)** check through the existing attemptBreakDoor path.
  A successful force **opens the door and ends that lock without breaking it**, so it can be
  shut again. Using Doors again clears all of Strahd's existing lair locks first (RAW). The
  menu also gets "End lair locks". Locks persist after combat until ended, and they save
  with the map's play state.
- **D5. Apparition.** Click a hostile Strahd can see. A Strahd Specter spawns in a free cell
  next to it (Strahd's faction, no initiative). It makes **one** attack through `begin_attack`,
  so Shield and other reactions work, then it is removed from play. Proposed: **give Strahd
  Specter the Life Drain rider** (`reduceHPMax`), since that's the Specter's stat block. The
  plain Specter is left as is.
- **D6. Shadow theft: eligibility.** Medium or smaller, within 30 ft, LOS from Strahd. "Casts
  a shadow" is proposed as: not a vampire (`is_vampire`), not already shadowless, and not
  creature type Undead/Construct with the Amorphous trait. Simpler alternative: anything
  but vampires, with the DM as judge. The DC 17 Cha save goes through the engine's normal
  save path, so Legendary Resistance, Bless and the rest apply.
- **D7. Shadow theft: the shadow.** On a failed save a Strahd Shadow spawns in a free cell
  next to the target (Strahd's faction). It gets its own initiative entry at **20**, ahead of
  the lair entry since the lair loses ties. The target gets a `shadowless` mark with the
  linked shadow's idx. Greater Restoration or Remove Curse on the target clears the mark
  only if that shadow is dead or removed; otherwise the spell logs "the shadow still
  exists". No other mechanical effect of being shadowless (RAW has none).
- **D8. Strahd Shadow's Strength drain.** Check at L1 whether the base Shadow's "-1d4 Str"
  rider is modelled. If it isn't, Strahd Shadow gets a plain attack, and I note the gap.
  Building the drain is out of scope unless you say otherwise.
- **D9. Out of scope:** NPC automation choosing lair actions (DM-driven only); tracker mode
  (real-dice) gets only a "Lair (20)" reminder row, no mechanics; multiplayer player screen
  (lair picks are NPC/DM-only, registered in `net/picks.py` like `_legendary_spell_pick`).

## Sign-off amendments (2026-11-16, user)

- **D1:** lair entry at count 20 as proposed, but **no no-repeat rule**: Strahd may use the
  same lair action in consecutive rounds.
- **D3:** ceilings/floors are **in scope** via a new right-click **"Send to floor…"** item
  that moves any character to another floor of the dungeon, in and out of combat (general
  feature, not Strahd-only). Phase itself stays a same-floor wall/door pass.
- **D4:** as proposed.
- **D5:** as proposed, Life Drain kept.
- **D6/D7 replaced:** Shadow theft works **like the Apparition**. On a failed DC 17 Cha
  save a Strahd Shadow appears next to the target, makes one attack against it, and then
  vanishes (the shadow returns to normal). No initiative entry, no `shadowless` mark, no
  restoration gating. The live game tracks the longer story by hand. Eligibility: Medium
  or smaller, within 30 ft, LOS, not a vampire.
- **D8:** **build the Strength drain**: a `reduceStr1d4` on-hit rider (target's Str −1d4;
  Str 0 → dies). It goes on both Shadow and Strahd Shadow.

## Steps

| Step | Work | Touches source? |
|------|------|-----------------|
| **0** | ✅ Signed off 2026-11-16 (amendments above) | no |
| L1 | Bestiary: Strahd Specter, Strahd Shadow (+7 via `bonus_hit`, 30 HP, CR 5, Life Drain per D5); Strahd `lair_actions`; `reduceStr1d4` rider (D8); test | data + C++ + test |
| L2 | Lair entry at count 20 in initiative, menu, no-repeat rule, Pass; save/restore | main.py, test |
| L3 | Phase: engine flag + pathing through walls/doors, expiry at count 20, no ending in a wall | C++ + bindings + test |
| L4 | Doors: `lair_lock` on Door, DC 20 force-open path, door-cycle pick UI, serialization | C++ + main.py + test |
| L5 | Apparition: spawn → one attack → remove | main.py + test |
| L6 | Shadow theft: save → spawn → one attack → remove (shares L5's code) | main.py + test |
| L6b | Right-click "Send to floor…" (any character, in/out of combat) | main.py + test |
| L7 | Headless GUI check through `tests/gui_driver.py`; then your run.sh pass | — |

Once you've agreed to the decisions, they're frozen. Any change gets a dated amendment here with its reason.

## Implementation notes (2026-11-16)

- `gui/lair.py` holds the lair turn and the four handlers. The Lair entry is an
  `InitiativeEntry` with `agent_idx = -1`, total 20, inserted after every entry ≥ 20.
- Phase: `PlacedAgent.phasing` (`bm.set_agent_phasing`). Walk/fly pathing ignores walls, wall
  edges and closed doors, but a move can't end in a blocked cell. It ends at the next Lair turn and at combat end.
- Doors: `Door.lair_lock` (`bm.set_door_lair_lock`, `bm.clear_lair_locks`). Open, pick and Knock all
  refuse it. `attempt_break_door` forces it at DC 20 and opens it without breaking it. It saves as play state
  only when set. Its glyph is a red padlock. Enter applies the chosen doors and Esc backs out.
- Apparition / Shadow Theft: they spawn the bestiary minion on Strahd's side next to the target,
  `begin_attack` with `attack_slot="legendary"`, then tombstone it. The Shadow Theft save uses the new
  `CombatEngine.roll_fixed_dc_save` (adv/dis, Bless/auras, Indomitable, Legendary Resistance).
- Strength drain: weapon rider `reduceStr1d4`, on Shadow and Strahd Shadow.
- Send to floor: `App._send_to_page` plus the right-click "Send to floor ▸" (the DM menu out of
  combat, the conditions menu in combat). It writes the record into the target page's creatures with
  `land_near`, and `_load_agents` moves such a record off a wall (`_open_cell_near`).
- Tracker mode: a "Lair (Strahd)" reminder row at 20 (after ties), added at Start or when a lair
  creature joins. Next steps onto it and past it, and it does nothing (`lair.ensure_tracker_entry`).
- Not done: mid-combat Send to floor, then an
  autosave restore, would leave the creature on both pages.

