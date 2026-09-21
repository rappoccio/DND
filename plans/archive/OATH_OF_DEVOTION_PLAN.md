# Oath of Devotion — Implementation Plan

Paladin subclass from `SRD_CC_v5.2.pdf` (p.56–57). Track by checking boxes.

**Conventions (from memory):**
- Opus writes C++/Python/JSON; **user runs the Docker build and the test suite**.
- New `rpg.Stats` flags MUST be added to BOTH `dict_to_stats` (helpers.py) AND the main.py save block, or they reset on save/reload.
- ALL save modifiers go through `saveModFor()`.
- `DND2024_MonsterStats.json` and the CSV→JSON converter are off-limits.
- Never commit — user owns all git commits.

---

## Already done (baseline)
- [x] `PaladinOath::OathOfDevotionPath` enum, `paladin_oath` Stats field, GUI subclass picker, save/reload
- [x] **L3 Sacred Weapon** attack bonus: `activateSacredWeapon`, `+CHA` mod in `combat_attack.cpp`, turn-decrement in `combat_turn.cpp`, GUI button, `test_paladin.py` cases
- [x] Aura infra `bestPaladinAura(bm, idx, min_level)` (team-scoped emanation; model = `hasAuraOfCourage`)
- [x] Divine Smite hook `applyDivineSmiteEffect` (trigger point for Smite of Protection)

---

## Slice 1 — L3 Sacred Weapon: finish the rider (small)
Currently only the `+CHA` attack bonus is applied. SRD also grants Radiant damage + light.
- [ ] `combat_attack.cpp` (~L216, where `sacred_weapon_turns > 0` adds the mod): route the weapon's on-hit damage type to **Radiant** while active
- [ ] Add/confirm a `test_paladin.py` case asserting the hit deals Radiant while Sacred Weapon is up
- [ ] **DECIDED: DEFER** light emission (20 ft bright / 20 ft dim) → note in `known_limitations.md` (combat-sim scope)

## Slice 2 — L7 Aura of Devotion: Charmed immunity in aura (small)
Clone of `hasAuraOfCourage`, oath-gated.
- [ ] Make `bestPaladinAura` oath-aware (add optional `require_oath` param) OR add sibling `bestDevotionAura(bm, idx, min_level)` in `combat_core.cpp`
- [ ] Add `hasAuraOfDevotion(bm, idx)` = `bestDevotionAura(bm, idx, 7) > 0` (declare in `combat.hpp`)
- [ ] Gate `applyCharmed` (combat_conditions.cpp:156) on it + refusal log (mirror Frightened at combat_conditions.cpp:187)
- [ ] Refuse Charmed at the rider/resource charm sites (the Charmed analogues of the 3 Aura-of-Courage Frightened sites)
- [ ] pybind: expose `has_aura_of_devotion` in `rpg_bindings.cpp`
- [ ] `test_paladin.py`: ally in aura can't be Charmed; out-of-aura can

## Slice 3 — L15 Smite of Protection: Half Cover in aura after Divine Smite (medium)
On casting Divine Smite, allies in Aura of Protection get Half Cover (+2 AC, +2 Dex saves) until start of paladin's next turn.
- [ ] New timed flag on Stats, e.g. `smite_protection_turns` (agent.hpp)
- [ ] Set it in `applyDivineSmiteEffect` (combat_riders.cpp:142) when `paladin_oath == OathOfDevotionPath && char_level >= 15`
- [ ] Decrement at paladin's turn start in `combat_turn.cpp` (alongside `sacred_weapon_turns`)
- [ ] Helper `hasSmiteOfProtectionCover(bm, target_idx)` — allied Devotion paladin with flag active + target in aura range
- [ ] Apply `+2` AC in the to-hit compare (`combat_attack.cpp`)
- [ ] Apply `+2` Dex saves via `saveModFor()` (combat_core.cpp)
- [ ] pybind + `test_paladin.py`
- [ ] Serializer round-trip for `smite_protection_turns` (dict_to_stats + main.py save block)

## Slice 4 — L20 Holy Nimbus: bonus-action aura buff (medium)
Bonus action, 10 min, 1/long-rest (or spend a L5 slot to restore). Three effects while active:
- [ ] **Radiant Damage**: enemy starting turn in aura takes `CHA + PB` radiant — reuse vampire-sunlight / Spirit-Guardians faction-aware turn-start emanation
- [ ] **Holy Ward**: Advantage on saves forced by a Fiend or Undead (source-type check in the save path / `saveModFor`)
- [ ] **Sunlight**: aura filled with sunlight bright light — reuse vampire Sunlight `VisibilityLevel` infra (triggers vampire vulnerability)
- [ ] `activateHolyNimbus` resource fn (mirror `activateSacredWeapon`) with 1/long-rest + L5-slot restore gating
- [ ] New timed flag `holy_nimbus_turns` on Stats; decrement at turn start
- [ ] GUI bonus-action button (mirror Sacred Weapon button in main.py)
- [ ] pybind + `test_paladin.py`
- [ ] Serializer round-trip for `holy_nimbus_turns` (dict_to_stats + main.py save block)

## Slice 5 — L3/5/9/13/17 Oath Spells (always-prepared) (small, data)
| Lvl | Spells |
|-----|--------|
| 3 | Protection from Evil and Good, Shield of Faith |
| 5 | Aid, Zone of Truth |
| 9 | Beacon of Hope, Dispel Magic |
| 13 | Freedom of Movement, Guardian of Faith |
| 17 | Commune, Flame Strike |
- [ ] Add the always-prepared list to `classfeatures.json` keyed by paladin level
- [ ] Audit `spells.json` for which spells are missing; add combat-relevant ones (Shield of Faith, Aid, Dispel Magic, Guardian of Faith, Flame Strike, Beacon of Hope)
- [ ] **DECIDED: DEFER** non-combat/utility spells (Commune, Zone of Truth, Freedom of Movement, Protection from Evil and Good) — list-only, note in `known_limitations.md`

---

## Order (LOCKED)
Slice 2 → 3 → 1 → 4 → 5 (cheapest mechanically-meaningful first; Holy Nimbus is the largest, so last).

## Wrap-up
- [ ] Build (user, in `rpg_map` Docker) + run test suite (user)
- [ ] Update memory: new `[[oath_of_devotion]]` note + MEMORY.md pointer
