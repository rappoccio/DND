# Divine Intervention — Technical Spec (SRD 5.2 / 2024)

Companion to `DIVINE_INTERVENTION_PLAN.md`. This spec nails down data model, engine API,
GUI flow, serialization, and per-spell contracts so implementation is mechanical. Grounded
in the current code (`gui/`); every hook named below was verified to exist.

**Feature text (SRD 5.2 p.38, Cleric L10):** *As a Magic action, choose any Cleric spell
of level ≤ 5 that doesn't require a Reaction to cast; cast it without a spell slot or Material
components. Recharge on a Long Rest.*
**Greater DI (L20):** the picker may also offer **Wish**; if chosen, DI recharges only after
**2d4 Long Rests**.

---

## 1. Goals / non-goals

**Goals**
- G1. A once/Long-Rest Cleric-L10 action that free-casts a chosen Cleric spell ≤ 5.
- G2. Reuse the Wish free-cast machinery; **no new casting pipeline**.
- G3. L20 Greater DI: Wish offered, 2d4-rest recharge lock.
- G4. Wire 8 currently-stubbed long-cast Cleric spells so DI has worthwhile targets.

**Non-goals**
- N1. Modeling real casting times (engine has none; all JSON spells are Action — see Plan §Key facts).
- N2. Level 6+ long-cast Cleric spells (only reachable via Greater DI → Wish; out of scope).
- N3. Ritual casting, Material-component economy.
- N4. NPC auto-use of DI in v1 (see §6, Open Decision O1).

---

## 2. Data model

### 2.1 `Agent::Stats` (`gui/agent.hpp`)
Add two fields (both must be added to the serializer per `stats_serializer_roundtrip`):

```cpp
// Divine Intervention (Cleric L10). Availability lives in the "Divine Intervention"
// Resource (0/1). This counter is the Greater-DI (L20) recharge lock: while > 0, a
// Long Rest decrements it INSTEAD of refilling the resource. 0 = normal (refills).
uint8_t divine_intervention_lock{0};
```

No boolean "used" flag — the `Resource.current` (0/1) is the single source of availability.

### 2.2 Resource (`gui/combat.cpp`, `Cleric` case in `applyClassResources`, ~line 477)
Alongside the existing Channel Divinity block:

```cpp
if (level >= 10) {
  Resource di("Divine Intervention", 1, 0);   // max 1
  di.long_rest_regen = 1;                       // full recharge on Long Rest (unless locked)
  di.short_rest_regen = 0;                       // NOT on short rest
  resources["Divine Intervention"] = di;
}
```

Mirrors Channel Divinity (already bound to Python via `Stats.get_resource` / `Resource.spend`).

### 2.3 Long-rest interaction (`gui/combat_resources.cpp::applyLongRest`, ~line 1062)
`restore_resources_long_rest()` refills **all** resources generically, so the Greater-DI lock
must be applied *after* it:

```cpp
stats.restore_resources_long_rest();               // existing line
// Greater Divine Intervention lock: a Wish use costs 2d4 Long Rests before DI returns.
if (stats.divine_intervention_lock > 0) {
    stats.divine_intervention_lock -= 1;
    if (stats.divine_intervention_lock > 0)
        if (auto* di = stats.getResource("Divine Intervention")) di->current = 0;
}
```

---

## 3. Engine API (C++)

Two small helpers on `CombatEngine`, bound in `rpg_bindings.cpp`. Keeps availability/spend
logic in the engine (`feedback_fix_root_cause`); the GUI only orchestrates the picker (like Wish).

```cpp
// True if agent is a Cleric L10+ with a DI use available and not under the Greater-DI lock.
bool canUseDivineIntervention(const BattleMap& bm, int agent_idx) const noexcept;

// Spend one DI use. `chose_wish` = true applies the 2d4-Long-Rest lock (Greater DI, L20).
// Returns false (no state change) if unavailable. Caller free-casts the chosen spell.
bool useDivineIntervention(BattleMap& bm, int agent_idx, bool chose_wish) noexcept;
```

`useDivineIntervention` implementation: gate on `canUse…`; `getResource("Divine
Intervention")->spend(1)`; if `chose_wish`, set `divine_intervention_lock = roll 2d4`
(engine RNG). `canUse…` checks `classLevel(Cleric) >= 10`, resource `current > 0`.

*(Greater-DI eligibility for offering Wish is `classLevel(Cleric) >= 20` — checked GUI-side
when building the picker.)*

---

## 4. GUI flow (`gui/main.py`)

Mirrors the Wish flow (`_start_cast_spell` → picker → `_on_wish_duplicate` →
`_activate_spell(free_cast=True)`).

### 4.1 Trigger
- New action-bar button **"Divine Intervention"**, shown only when the current agent
  `has_class(Cleric) and class_level(Cleric) >= 10`.
- **Enable/grey-out gate:** `combat.can_use_divine_intervention(bm, idx)` — gate on the
  resource, **NOT** `not self.action_used`/`bonus_used` (avoid the
  `haste_button_bonus_used_gotcha` dead-key trap; DI is a Magic *action*, so it should also
  respect `action_used` for the turn, but availability greying keys on the resource).
- Undrawn button parks at `x = -10000` (existing convention).

### 4.2 Handler
```python
def _start_divine_intervention(self):
    idx = self._current_agent_idx()
    if idx < 0 or not self.combat.can_use_divine_intervention(self.bm, idx):
        return
    stats = self.combat.get_agent_stats(self.bm, idx)
    greater = stats.class_level(rpg.CharacterClass.Cleric) >= 20
    allow = CLERIC_DI_SPELL_NAMES | ({"Wish"} if greater else set())
    self.spell_selection_dialog.show(
        lambda d, i=idx, g=greater: self._on_divine_intervention_pick(i, g, d),
        max_level=5,
        allow_names=allow,                 # NEW picker param (see §4.4)
        title="Divine Intervention — choose a Cleric spell (≤ 5th level)")
    self._combat_log_add("Divine Intervention — choose a Cleric spell of level 5 or lower.")

def _on_divine_intervention_pick(self, caster_idx, greater, spell_dict):
    chose_wish = spell_dict.get("name") == "Wish"
    if not self.combat.use_divine_intervention(self.bm, caster_idx, chose_wish):
        self._combat_log_add("Divine Intervention is unavailable.")
        return
    spell = _dict_to_spell(spell_dict)
    self.combat.add_spell_to_agent(self.bm, caster_idx, spell)
    spells = self.combat.get_agent_spells(self.bm, caster_idx)
    new_idx = len(spells) - 1
    self._di_temp_spells.add(new_idx)      # mirror of _wish_temp_spells
    stats = self.combat.get_agent_stats(self.bm, caster_idx)
    self.action_used = True                # DI is a Magic action
    self._combat_log_add(f"Divine Intervention: casting {spell.name} for free!")
    self._activate_spell("action", new_idx, spell.level, caster_idx, spells, stats, free_cast=True)
```

- `_di_temp_spells`: new `set` initialized in `__init__` next to `_wish_temp_spells`. Every
  place that skips `_wish_temp_spells` in the cast menu (`_start_cast_spell`, ~9714) must also
  skip `_di_temp_spells`. **Grep `_wish_temp_spells` and pair each site.**
- If the chosen spell IS Wish (Greater DI), `_activate_spell` sees `name=="Wish"` but
  `free_cast=True`, so its Wish-recursion guard (`not free_cast`) is skipped and Wish resolves
  as itself... **contract gap:** Wish's own effect must run. Simplest v1: treat Greater-DI Wish
  as "free-cast Wish which then opens its own duplicate picker" — set `free_cast=False` on the
  Wish injection so the normal Wish flow fires, but skip its slot charge. **Decision O2 below.**

### 4.3 The Cleric ≤5 allow-list (`gui/main.py` or `constants.py`)
`spells.json` entries lack a reliable `classes` field, so use an explicit name set (also the
reason the "no Reaction spell" clause is automatically satisfied — no Cleric SRD spell is
Reaction-cast):

```python
CLERIC_DI_SPELL_NAMES = {
 # cantrips
 "Guidance","Light","Mending","Resistance","Sacred Flame","Spare the Dying","Thaumaturgy",
 # 1
 "Bane","Bless","Command","Create or Destroy Water","Cure Wounds","Detect Evil and Good",
 "Detect Magic","Detect Poison and Disease","Guiding Bolt","Healing Word","Inflict Wounds",
 "Protection from Evil and Good","Purify Food and Drink","Sanctuary","Shield of Faith",
 # 2
 "Aid","Augury","Blindness/Deafness","Calm Emotions","Continual Flame","Enhance Ability",
 "Find Traps","Gentle Repose","Hold Person","Lesser Restoration","Locate Object",
 "Prayer of Healing","Protection from Poison","Silence","Spiritual Weapon","Warding Bond",
 "Zone of Truth",
 # 3
 "Animate Dead","Beacon of Hope","Bestow Curse","Clairvoyance","Create Food and Water",
 "Daylight","Dispel Magic","Glyph of Warding","Magic Circle","Mass Healing Word",
 "Meld into Stone","Protection from Energy","Remove Curse","Revivify","Sending",
 "Speak with Dead","Spirit Guardians","Tongues","Water Walk",
 # 4
 "Aura of Life","Banishment","Control Water","Death Ward","Divination","Freedom of Movement",
 "Guardian of Faith","Locate Creature","Stone Shape",
 # 5
 "Commune","Contagion","Dispel Evil and Good","Flame Strike","Geas","Greater Restoration",
 "Hallow","Insect Plague","Legend Lore","Mass Cure Wounds","Planar Binding","Raise Dead","Scrying",
}
```

### 4.4 Picker change (`gui/dialogs.py::SpellSelectionDialog`)
Add an optional `allow_names: set|None = None` param to `show()` and apply it in
`_update_filtered_spells()` (one line, alongside the existing `max_level` cap):

```python
if self.allow_names is not None:
    self.filtered_spells = [s for s in self.filtered_spells
                            if s.get("name") in self.allow_names]
```
Store `self.allow_names` in `__init__` (default `None`) and reset it in `show()`. Backward
compatible — Wish passes no `allow_names`.

---

## 5. Serialization

Per `stats_serializer_roundtrip`, add `divine_intervention_lock` to **both**:
- `_dict_to_stats` (load, `gui/agent_loader.py`)
- the save block (`main.py`, stats → dict)

Resources already round-trip via `Resource.to_json`/`from_json` (the DI resource persists for
free once created). `_di_temp_spells` is session-only (like `_wish_temp_spells` — not saved).
No `Spell` serializer changes for D0.

---

## 6. NPC behavior & open decisions

- **O1 (NPC auto-use):** v1 is **PC-only** (button). NPC clerics do not auto-fire DI. Follow-up
  can add it to the caster strategy resolver (`npc_prefer_heal_step9` / difficulty resolver) —
  natural home is "free level-5 nuke/heal when DI available."
- **O2 (Greater-DI Wish):** does picking Wish under Greater DI (a) run Wish's full duplicate
  picker for free, or (b) resolve a fixed Wish effect? **Recommend (a):** inject Wish with
  `free_cast=False` but pre-charge nothing (skip `spend_spell_slot`), letting the existing Wish
  duplicate flow run; DI's 2d4 lock is the cost. Needs a small `free_of_slot` flag through
  `_on_wish_duplicate`. Confirm before building L20.
- **O3 (button placement):** beside Channel Divinity in the action bar. Cosmetic.

---

## 7. Per-spell wiring contracts (Phase D1–D4)

All 8 exist in `spells.json` as **wrong** stubs. Each contract = target JSON fields + engine
hook to reuse + a one-line test. Order: D1 → D2 → D3, then **Hallow + Glyph LAST**.

### D1 — highest value — **DONE (2026-07-23, spells.json only, no C++)**
- **Prayer of Healing** (L2). Stub is `Harm`/Single, no dice. → `type: Heal`,
  `attack_type: Automatic`, `geometry: Multiple`, `num_targets: 5`, heal `2d8` +
  spellcasting-mod, `upcast_dice_bonus: 1`. Route through `healAgent` (revives downed,
  `aid_phase3`). Mirror **Mass Healing Word**'s multi-target heal. *Test:* 3 wounded allies,
  DI-cast → all healed, one downed ally revived. **[Built as specified.]**
- **Geas** (L5) — **plus Suggestion (L2) + Mass Suggestion (L6)**, per DM ruling all three
  modeled as one **indefinite control** pattern (NOT the Charmed+5d10-disobedience design below —
  there is no "acts counter to command" hook to hang the 5d10 on). On a failed **Wis** save the
  target gets a **`CommandFlee`** condition → `runFleeTurn` drives it to flee to the farthest cell
  and take no action each turn (`command_flee_active`); it ends when the target takes damage via
  **`on_damage: "end"`** (RAW for the Suggestions: *"until you or your allies deal damage"*). No
  on-cast damage. `geometry: Multiple`, `num_targets` 1/1/12, `condition_duration: 1000`.
  **Deviations from the original design:** `save_repeat_turns: -1` (this engine's "never re-save";
  `0` would re-save every turn), and Suggestion set non-Concentration for a uniform indefinite
  model. *Test:* enemy fails save → `CommandFlee` present and it flees; deal damage → cleared.
  ~~[original: keep Wis save, apply Charmed + compelled behavior; 5d10 as disobedience rider;
  save_repeat_turns 0]~~

### D2 — revive (+ the shared corpse-pick) — **DONE (2026-07-23)**
> Built as specified. New `Spell.revives_dead` bool (spell.hpp + binding + all 3 serializers);
> engine clears `conditions.dead` before `reviveOnHeal` at the heal choke point; GUI corpse-pick
> = `_corpse_at` + `_pending_spell_targets_corpse` + `_resolve_corpse_spell`. **Raise Dead** and
> **Revivify** (same latent bug) both wired in spells.json. `test_raise_dead.py` green. Animate
> Dead (D3) reuses the corpse-pick by extending the `_pending_spell_targets_corpse` predicate.
> **PREREQUISITE — §10 DONE (2026-07-23).** Dead/unconscious display & occupancy split is built
> ([[dead_unconscious_display_spec]]); corpses now persist, are drawn (red hatch), and free their
> square. The one remaining piece D2 must add is the **§10.5 corpse-pick mode**.

- **Corpse-pick mode (§10.5) — build FIRST, REUSABLE.** `_agent_at` deliberately skips corpses,
  so revive/animate spells can't use the normal target click. Build ONE general "select a
  `conditions.dead` body within range" targeting mode. Raise Dead (D2) **and** Animate Dead (D3)
  consume the identical pick — there is no per-spell difference, so do NOT wire a Raise-Dead-only
  mode that D3 would just duplicate.
- **Raise Dead** (L5). Stub `Heal`/Single, no revive. → revive a corpse: mirror **Revivify**'s
  revive path (`healAgent` on a `conditions.dead` target; clear `dead`, restore 1 HP, respect
  `npc_corpse_removal`). Target = the corpse-pick mode above (corpses in range 5 ft).
  *Test:* dead ally in reach → DI Raise Dead → alive at 1 HP, corpse marker cleared.

### D3 — summons
- **Animate Dead** (L3). *(Uses the §10 corpse + the D2 corpse-pick — an undead is raised from a
  visible corpse.)* → spawn undead (Skeleton/Zombie) via **`spawn_agent`** (NOT
  `applyAgentConfigs`, `agent_dual_list_gotcha`); DI-free summon rides
  `pending_summon_free_cast`. Reuse summoning path (`test_summoning.py`). *Test:* DI-cast →
  1 allied Skeleton placed at chosen empty cell.
- **Planar Binding** (L5). → bind/control an existing summoned or Charmed creature (transfer to
  caster's team for the duration). Lower priority; depends on a valid target present.
  *Test:* Charmed creature in range → becomes controllable ally for duration.

### D4 — LAST (heavy infra / low payoff) — the emanation-ward zone family
- **Magic Circle** (L3) — **DONE (2026-07-24).** Built as a creature-type MOVEMENT ward (the
  emanation-ward infra). New `Agent::CreatureTypeBit` mask + `Stats::creatureTypeMask()` (six flags:
  is_undead/is_fiend already existed; added is_celestial/is_elemental/is_fey/is_aberration, auto-set
  from the bestiary `meta.type`). `ActiveTerrainEffect` gained `ward_creature_mask` + `ward_traps`;
  new `BattleMap::movementWardBlocks()` bars a warded type from crossing the zone boundary, wired into
  BOTH `moveAgent` and `pathfindMovement` (walk + fly reachable). Direction: keep-out (default) AND
  trap-inside (reverse). `Spell.creates_movement_ward` + `SpellAction.ward_creature_mask/ward_traps`;
  executeSpell places a Normal-difficulty ward via `placeTerrainEffect` (no damaging zone). GUI:
  multi-select type + Reverse picker in `_activate_spell`. `test_magic_circle.py` green. Attack-roll
  disadvantage / no-Charm-Frighten / Cha-save magical-entry sub-clauses deferred (movement was the
  ask). **Hallow + Glyph reuse this ward infra — still to build.**  ~~[original design below]~~
- ~~**Magic Circle** (L3). Stub empty `AttackRoll`.~~ → 10-ft radius, 20-ft cylinder emanation
  warding a chosen creature type (Fiend/Undead/etc.): that type has disadvantage to enter and
  can't willingly enter; reuse the AoE emanation + total-cover chokepoint (`areaOrigin` +
  `pruneBlockedCells`, `total_cover_chokepoint`); model the zone on **Spirit Guardians**.
  `requires_concentration` per RAW is false (1-hour duration) → treat as timed zone.
  *Test:* summoned Fiend blocked from entering the circle. **(Moved here from D2 — it shares the
  emanation-ward infra with Hallow, so build the two together; Magic Circle is the smaller first
  step of that infra.)**
- **Hallow** (L5, 24 h). → large-radius (up to 60 ft) consecration zone built on the Magic
  Circle emanation: (a) ward vs a chosen creature type, (b) one selectable extra effect (v1:
  just one, e.g. Darkness/Daylight or a resistance ward). *Test:* zone placed, chosen type
  warded inside.
- **Glyph of Warding** (L3, 1 h). → placed trigger glyph: reuse the delayed-effect condition
  (`delayed_effect_condition`, as Quivering Palm) — on enemy entering the glyph's cell, detonate
  a stored burst (v1: damage glyph only, not spell-glyph). *Test:* enemy steps on glyph →
  burst fires, glyph consumed.

---

## 8. Test plan (`tests/test_divine_intervention.py`)
1. **Gate:** Cleric L9 has no DI resource/button; L10 does.
2. **Free cast:** L10 Cleric DI-casts Flame Strike → damage dealt, **no** L5 slot spent, DI
   resource → 0.
3. **Once/rest:** second DI attempt same day → `can_use_divine_intervention` false.
4. **Recharge:** `apply_long_rest` → DI available again; lock is 0.
5. **Greater DI:** L20 Cleric picks Wish → `divine_intervention_lock` set to 2d4; DI stays
   unavailable across N-1 long rests, returns on the Nth.
6. **Scoping:** picker offers only `CLERIC_DI_SPELL_NAMES` (+ Wish at L20); a non-Cleric or
   L6 spell is absent.
7. **Serialization:** save/reload mid-lock preserves `divine_intervention_lock` and DI
   resource `current`.
8. Per-spell tests from §7.

---

## 9. Build/verify
Engine changes (C++) require a rebuild (`feedback_build_handling`: Docker `rpg_map`). The user
runs tests (`feedback_user_runs_tests`); Opus may build. No `build/` staged
(`feedback_never_commit_build`).

---

## 10. Prerequisite for D2/D3 — Dead vs Unconscious display & occupancy

**Why now.** Raise Dead (D2) and Animate Dead (D3) both need a *persistent, visible, selectable
corpse* on the board — the revive target and the "remains" the undead rises from. Today a dead
body is not drawn, not selectable, and its square frees up; worse, the occupancy rules can't tell
"dead" from "unconscious" (both key on `hp_cur <= 0`). This section splits the two states so the
D2/D3 targets exist. **Build this before D2/D3.** Grounded in current code; every hook below verified.

### 10.1 The two states (contract)

| State | Detected by | Sprite | Square (occupancy) | Selectable |
|---|---|---|---|---|
| **Dead** | `conditions.dead` (implies hp ≤ 0) | drawn, **red diagonal hatch** (existing look) | **PASSABLE** — a living creature may move into / be placed on / share the cell | corpse only via the §10.5 corpse-pick; a live creature sharing the square wins normal clicks |
| **Unconscious** | `hp_cur ≤ 0 && !conditions.dead` (= `conditions.unconscious`, rolling death saves) | drawn, **greyed-out** (desaturated/dimmed), **no** red hatch | **IMPASSABLE** — blocks the cell like a living body | yes — click to heal; un-greys on regaining HP |

Intuition: the dead are trampled over (square frees); the dying are stepped around (square holds).
Both stay **visible** — the change from today is that dead bodies no longer vanish, and the two
states now look and behave differently.

### 10.2 Rendering changes (`gui/main.py`) — verified current state
- `_draw_agents` (~15687) currently **skips** `pt.conditions.dead` (line ~15697) so corpses are
  invisible. **Remove that skip** (keep the `removed_from_play`, fog, concealment, and
  `_npc_anim_draws_dead` handling) so dead bodies keep drawing after the death animation drains.
- `_draw_one_agent` down-hatch (~14933) fires on `hp_disp <= 0`, which today covers every drawn
  0-HP token. **Split it by state:**
  - **red hatch → `pt.conditions.dead` only.**
  - **unconscious (`hp<=0 && !dead`) → grey-out** the token instead (no hatch): desaturate/dim the
    sprite surface — reuse the existing `tint` + `BLEND_RGBA_MULT` path (`_draw_one_agent`
    ~14905-14909) with a grey multiply, or greyscale-convert. The team-color background square can
    also be dimmed for legibility.
- `_draw_one_agent` still early-returns on `removed_from_play` (~14883) — unchanged.

### 10.3 Occupancy — the "three places that must agree" (`occupancy_dead_agents`)
All three passability tests currently key on `hp_cur <= 0`, freeing the square for **both** states.
Re-key them on **`conditions.dead`** so only true corpses free their square; unconscious bodies
block again:
- `BattleMap::agentOccupancy` (`battle_map.cpp:811`): `hp_cur <= 0` → `getConditions().dead`.
- The `isBlocked`-companion agent scan (`battle_map.cpp:404`): same re-key.
- `helpers.can_place_agent` (`helpers.py`, the `pt.stats.hp_cur <= 0` skip): → `pt.conditions.dead`
  (shared with the summon-placement preview + tests, so it must match the engine).
- `_agent_at` (`main.py:1822`) **already** keys on `conditions.dead` — no change (a downed body
  stays clickable-to-heal; a corpse is skipped so a live creature sharing its cell is selected). ✓

Engine change ⇒ rebuild (Docker `rpg_map`, `feedback_build_handling`).

### 10.4 Corpse persistence (NPCs)
Today downed NPCs "die outright and their corpses are cleared" (`_draw_agents` comment;
`npc_corpse_removal`). For D2/D3 the corpse must **stay** in `placedAgents_`: on NPC death the
death chokepoint (`death_chokepoint` `applyUnconscious`) may set `conditions.dead` (which now frees
the square via §10.3) but **must not** `removed_from_play` the body, and the draw loop (§10.2) now
renders it. Verify the NPC death path leaves the corpse present; if a later cleanup tombstones NPC
corpses, gate that off so corpses persist for the encounter.

### 10.5 Corpse targeting (flag for D2/D3, not this task)
`_agent_at` deliberately skips corpses, so Raise Dead / Animate Dead can't use the normal target
click. They will need a small **corpse-pick mode** — select a `conditions.dead` body within range.
Out of scope for this display/occupancy task; called out so D2/D3 budget for it.

### 10.6 Tests
- **Occupancy split:** two agents adjacent; drop one to 0 HP (unconscious) → its cell is NOT
  placeable (`can_place_agent` False) and NOT pathable (`agentOccupancy == 2`); then set
  `conditions.dead` → the same cell becomes placeable and pathable.
- **Selectability:** `_agent_at` returns the downed (unconscious) body but skips the dead corpse.
- **Render (manual):** a dead token shows the red hatch and a live token can stand on it; an
  unconscious token is greyed (no hatch) and blocks the cell.
