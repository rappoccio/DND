# Divine Intervention — Implementation Plan (SRD 5.2 / 2024 PHB)

Status: PLANNING (discuss before implementing).

**Feature (SRD 5.2 p.38, Cleric Level 10):** *"As a Magic action, choose any Cleric
spell of level 5 or lower that doesn't require a Reaction to cast. As part of the same
action, you cast that spell without expending a spell slot or needing Material
components. You can't use this feature again until you finish a Long Rest."*

**Level 20 (Greater Divine Intervention):** the picker may also offer **Wish**; if chosen,
DI can't be used again until **2d4 Long Rests** finish.

Scope rule (`feedback_scope_combat_sim`): combat-relevant mechanics only; reuse existing
engine hooks, don't invent parallel paths (`feedback_fix_root_cause`). The tactical hook is
that DI lets a Cleric drop a **free level-≤5 spell as a Magic action** — including several
spells whose real-world casting time is 1 minute+ (normally uncastable in a fight).

---

## Key engine facts (verified in code before planning)

1. **No long-cast concept exists.** `Spell::casting_time` is only `Action | BonusAction |
   Reaction` (`gui/spell.hpp:32`), and `gui/spells.json` carries **no** `casting_time`
   field — every JSON spell defaults to Action. So there is **no casting-time gate to
   bypass**; DI's job is purely *free cast* + *cleric-≤5 scoping* + *once/long-rest*.
2. **The "doesn't require a Reaction" clause is a near no-op** for our data — **none** of
   the SRD Cleric spells are Reaction-cast. Still code the exclusion defensively
   (`casting_time == Reaction` → filtered from the picker).
3. **Wish is the exact template.** `main.py::_on_wish_duplicate` (~9643) →
   `SpellSelectionDialog` (`dialogs.py:3215`) → inject into the caster's list, remembered in
   `self._wish_temp_spells`, skipped in the cast menu → cast via `_activate_spell` with
   `free_cast=True`. DI is "Wish-lite": same flow, scoped to Cleric ≤5, powered by a
   once/long-rest resource instead of a 9th-level slot.
4. **Free-cast plumbing already exists:** `pending_spell_free_cast`, `pending_summon_free_cast`,
   `action.free_cast` (`main.py`), consumed in the AoE / summon paths.
5. **Long-rest resource model exists:** `Resource` + `Stats.getResource(...)`,
   `restore_resources_long_rest()`, restored in `applyLongRest` (`combat_resources.cpp:1070`).
   Channel Divinity (`combat_riders.cpp:1282`) is the pattern to mirror.
6. **Serializer round-trips are mandatory** for any new `Stats`/`Spell` field
   (`stats_serializer_roundtrip`, `spell_serializer_roundtrip`) or it resets on reload.

---

## The spells (verified casting times from the SRD spell descriptions)

Legend: **wire** = build real mechanics · **skip** = pure out-of-combat, out of scope.

| Lvl | Spell | Cast time | Verdict | Current `spells.json` state |
|-----|-------|-----------|:------:|-----------------------------|
| 2 | Prayer of Healing | 10 min | **wire** | stub: typed `Harm`/Single, no heal dice — **wrong** |
| 5 | Geas | 1 min | **wire** | stub: `Harm` 5d10 psychic, **no compulsion** |
| 5 | Raise Dead | 1 hour | **wire** | stub: `Heal`/Single, no revive logic |
| 3 | Magic Circle | 1 min | **wire** | stub: `AttackRoll`, no damage/effect |
| 3 | Animate Dead | 1 min | **wire** | stub: no summon |
| 5 | Planar Binding | 1 hour | **wire** | stub: no bind |
| 5 | Hallow | **24 hours** | **wire (last)** | stub: no area consecration |
| 3 | Glyph of Warding | 1 hour | **wire (last)** | stub: no trap |
| 0 | Mending | 1 min | skip | repair object |
| 2 | Augury | 1 min | skip | divination |
| 3 | Clairvoyance | 10 min | skip | remote sensor |
| 5 | Commune | 1 min | skip | Q&A |
| 5 | Legend Lore | 10 min | skip | lore |
| 5 | Scrying | 10 min | skip | remote sensor |

> Level 6+ long-cast Cleric spells (Create Undead, Find the Path, Forbiddance, Heroes'
> Feast, Planar Ally, Conjure Celestial, Resurrection, Symbol, Control Weather, Astral
> Projection, True Resurrection) are outside DI's ≤5 range; only reachable via Greater DI →
> Wish at L20. **Out of scope.**

**Decision (2026-07-23):** wire the 6 combat spells (Prayer of Healing, Geas, Raise Dead,
Magic Circle, Animate Dead, Planar Binding), then add **Hallow** and **Glyph of Warding**
**last** (heaviest infra / lowest combat payoff).

---

## Proposed phasing

### Phase D0 — Divine Intervention feature (the headline; reuses Wish)
- New once/long-rest resource `"Divine Intervention"` on the Cleric (mirror Channel
  Divinity); restored in `applyLongRest`.
- Cleric-L10 gate (per-class level via the multiclass level-gate machinery,
  `multiclassing_progress`).
- New picker built from `spells.json` filtered to **Cleric list ∧ level ≤ 5 ∧
  casting_time ≠ Reaction**. (Wish-style overlay; reuse `SpellSelectionDialog`.)
- On pick: spend the DI resource, inject the chosen spell into the caster's list
  (`_di_temp_spells`, mirror of `_wish_temp_spells`), cast via `_activate_spell(free_cast=True)`
  — no slot, no material.
- **Greater DI (L20):** picker also offers Wish; choosing it locks DI for 2d4 long rests
  (track remaining rests on a `Stats` field, decrement in `applyLongRest`).
- GUI action button (grey-out when resource spent — beware the
  `haste_button_bonus_used_gotcha` dead-key pattern; gate on the resource, not `bonus_used`).
- Serialization: DI resource + `_di_temp_spells` + any `Stats` lock-counter field round-trip.

*Ships value immediately: free-cast of already-wired L5 spells (Flame Strike, Mass Cure
Wounds, Greater Restoration, Insect Plague, Contagion, Dispel Evil and Good).*

### Phase D1 — Healing/control (highest combat value)
- **Prayer of Healing** — retype `Heal`, multi-target (≤5), heal dice + upcast. Mirror
  **Mass Cure Wounds** (`Heal`/Sphere) but target-list rather than area. Route heal through
  `healAgent` (revives downed, per `aid_phase3`).
- **Geas** — real compulsion: Wis save → Charmed/compelled condition (mirror Command/Hold
  Person condition path) + the psychic-on-disobedience rider (`condition_rider`). Reuse the
  existing Charmed condition; no new infra.

### Phase D2 — Revive + zone
- **Raise Dead** — revive a corpse (mirror **Revivify** revive path; check `conditions.dead`
  / corpse handling, `npc_corpse_removal`). House-rule the 10-day/-4 penalty as flavor.
- **Magic Circle** — anti-creature-type emanation (10-ft cylinder). Reuse the AoE/emanation
  total-cover chokepoint (`areaOrigin` + `pruneBlockedCells`, `total_cover_chokepoint`);
  effect = ward/impede a chosen creature type entering/leaving. Model on Spirit Guardians'
  zone.

### Phase D3 — Summons
- **Animate Dead** — spawn undead via `spawn_agent` (NOT destructive `applyAgentConfigs`,
  per `agent_dual_list_gotcha`); DI-free summon rides `pending_summon_free_cast`. Reuse the
  summoning path (`test_summoning.py`).
- **Planar Binding** — bind an existing summoned/allied creature (control transfer). Lower
  value; depends on a creature already present.

### Phase D4 — Deferred heavies (LAST, per decision)
- **Hallow** — large-radius consecration zone: (a) ward vs a chosen creature type, (b) one
  bonus "extra effect." Big area-effect infra; build on the Magic Circle emanation work from
  D2. Casting time is 24 h in the book but DI overrides it to a Magic action.
- **Glyph of Warding** — placed trap glyph (stored-spell or damage burst on trigger). Reuse
  the delayed-effect condition (`delayed_effect_condition`, as used by Quivering Palm) for
  the trigger. Lowest combat payoff.

---

## Open questions / locked decisions
- **LOCKED:** spell-wiring order = D1→D2→D3, then Hallow + Glyph of Warding last (2026-07-23).
- **Open:** does the DI resource button live beside Channel Divinity, and should NPC clerics
  auto-use DI (npc caster strategies, `npc_prefer_heal_step9`) or PC-only for now?
- **Open:** Raise Dead / Planar Binding revive-a-specific-target UX (target picker over
  corpses vs. nearest).
