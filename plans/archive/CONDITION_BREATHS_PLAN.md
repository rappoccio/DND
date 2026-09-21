# Condition-Only & Condition-Rider Breath Weapons — Implementation Plan

The follow-up "condition pass" deferred from Step 3 of
[NPC_USES_RECHARGE_PLAN.md](NPC_USES_RECHARGE_PLAN.md). Step 3 shipped the
*damaging* recharge breaths as generic `Breath<Element><Shape><Tier>` catalog
spells. This pass adds the two kinds of breath the deriver skipped:

1. **Condition riders on damaging breaths** — the breath already deals damage
   (catalog spell exists) but ALSO imposes a condition on a failed save
   (Tarrasque Thunderous Bellow → Deafened + Frightened; Demilich Howl →
   Frightened; Sphinx Mind-Rending Roar → Incapacitated; Vrock Spores →
   Poisoned).
2. **Condition-only breaths** — no damage at all, just a control effect
   (Dust Mephit Blinding Breath → Blinded; Modron Pentadrone Paralysis →
   Paralyzed; Jackalwere Sleep Gaze → Unconscious; Giant Spider Web →
   Restrained).

## The key insight: the engine already does this

`executeSpell` (combat_spells.cpp ~line 1530–1645) **already** applies a spell's
`conditions` (`std::vector<AttackCondition>`) to each target in the AoE, rolling
each condition's own save (`requires_save`, `save_ability`, `save_dc_ability`,
`condition_duration`, `save_repeat_turns`, `on_damage`, `push_ft`). It works
independent of whether the spell deals damage. Prior art already in
`gui/spells.json`: `YetiChillingGaze` (Paralyzed), `Sleep` (Unconscious),
`Color Spray` (Blinded), `Fear` (Frightened), `Thunderwave`/`Gust of Wind`
(Push + push_ft), `Web`/`Entangle` (Restrained), `Hold Person` (Paralyzed).

So this pass is **almost entirely data**. No new condition machinery is needed
for the common cases. The one genuine engine gap is the dragon/gorgon
"escalation" breath (a *second* failed save upgrades the condition) — see §4.

## The design problem: shared catalog spells can't carry per-monster conditions

A `Breath<Element><Shape><Tier>` catalog spell is **shared** across many
monsters (every High fire cone is `BreathFireConeHigh`). Conditions vary
per-monster, so we must NOT bake a condition into the shared catalog dict.

**Solution — mirror the `npc_spell_recharge` pattern exactly:** a new
per-monster `npc_spell_conditions` map on each bestiary record:

```jsonc
"npc_spell_conditions": {
  "<spell_name>": [
    {"condition_name": "Frightened", "requires_save": true,
     "save_ability": "SaveWis", "save_dc_ability": "SaveSpellcasterMod",
     "condition_duration": 1, "save_repeat_turns": 1}
  ]
}
```

Because `set_agent_spells` stores a **per-agent copy** of the spell vector, the
loader can layer conditions onto *this monster's instance* of even a shared
catalog spell without affecting any other monster that references the same name.
This keeps the catalog clean (geometry + damage only) while conditions stay
per-monster — the same separation `npc_spell_recharge` already uses for the
recharge value.

---

## Step 1 — Loader: apply `npc_spell_conditions`  (Python, no rebuild)

In `main._load_npc_spells_from_record`, right after the `npc_spell_recharge`
block (where `cpp_spells` are built, before `set_agent_spells`):

```python
cond_map = mob_record.get("npc_spell_conditions", {})
if cond_map:
    for sp in cpp_spells:
        riders = cond_map.get(sp.name)
        if riders:
            conds = list(sp.conditions)          # keep any catalog-defined ones
            for rd in riders:
                c = rpg.AttackCondition()
                c.condition_name   = rd["condition_name"]
                c.requires_save    = bool(rd.get("requires_save", True))
                c.save_ability     = getattr(rpg.SaveAbility, rd.get("save_ability", "SaveCon"))
                c.save_dc_ability  = getattr(rpg.SaveAbility, rd.get("save_dc_ability", "SaveSpellcasterMod"))
                c.condition_duration = int(rd.get("condition_duration", 1))
                c.save_repeat_turns  = int(rd.get("save_repeat_turns", 1))
                c.push_ft            = int(rd.get("push_ft", 0))
                conds.append(c)
            sp.conditions = conds
self.combat.set_agent_spells(self.bm, agent_idx, cpp_spells)
```

There is already a single funnel for the `AttackCondition` dict → object
conversion in `helpers._dict_to_spell` (line ~754). **Reuse it** rather than
hand-rolling the loop above — factor that inner condition-parsing block into a
small `helpers._dict_to_attack_condition(rd)` and call it from both places, so
the field list lives in exactly one spot (same single-source-of-truth rule that
already bit `school`/`light_level`).

Persist `npc_spell_conditions` through the encounter save/restore path **exactly
as `npc_spell_recharge` is persisted** (store it in `_agent_meta`, write it in
the save block ~line 9162, re-apply it in the restore block ~line 9617). NPC
spells reload from the record's catalog references, so the conditions come back
from `npc_spell_conditions` on reload — `_spell_to_dict` does NOT serialize
`conditions` and does not need to.

## Step 2 — Condition-only shells in the catalog  (data)

Condition-only breaths have no damage tier, so the deriver mints damage-less
**shell** spells named by effect, following the `Breath<…>` convention and
tier-by-footprint sizing from Step 3:

| Shell name (example)       | Geometry / size      | Carries                         |
|----------------------------|----------------------|---------------------------------|
| `BreathBlindingConeLow`    | Cone, 15 ft          | Blinded (Con save)              |
| `BreathParalyzingConeMed`  | Cone, 30 ft          | Paralyzed (Con save)            |
| `BreathSleepConeMed`       | Cone, 30 ft          | Unconscious, `on_damage:"end"`  |
| `BreathRestrainingEmanLow` | Sphere/Eman, 15 ft   | Restrained (Dex save)           |

Shell spell shape (no `magic_damage_types`):

```jsonc
{
  "name": "BreathBlindingConeLow", "type": "Harm", "geometry": "Cone",
  "attack_type": "Save", "save_ability": "SaveCon", "radius": 15,
  "duration": 1, "level": 0, "magic_damage_types": [], "physical_damage_types": [],
  "requires_concentration": false, "school": "transmutation",
  "uses_max": 1, "uses_remaining": 1, "recharge_min": 0,
  "conditions": [{"condition_name": "Blinded", "requires_save": true,
                 "save_ability": "SaveCon", "save_dc_ability": "SaveSpellcasterMod",
                 "condition_duration": 1, "save_repeat_turns": 1}]
}
```

Note: condition-only shells CAN carry their condition in the catalog dict (the
condition is intrinsic to the effect, e.g. "Blinding Breath" always blinds), and
`_dict_to_spell` already round-trips `conditions`. Use `npc_spell_conditions`
only when the *same* shell/damage spell needs *different* riders per monster, or
to layer a rider onto a shared **damaging** catalog spell. Prefer baking the
condition into a dedicated shell when it's monster-specific in effect but
one-to-one with the spell name.

**⚠ Verify at build:** confirm `executeSpell` still enumerates AoE targets and
applies conditions when the spell has an empty `magic_damage_types`/
`physical_damage_types` (a pure-control Save AoE). If it early-returns on
"no damage," that's the one small engine fix — let the per-target condition loop
run regardless of damage. (Expected to already work: `Sleep`/`Hold Person`
carry conditions with token/no damage today.)

## Step 3 — Extend the deriver  (`tools/derive_breath_weapons.py`)

Add a condition-parsing pass alongside the existing damage parse:

- **Keyword → condition map** on each breath clause:
  `blind→Blinded`, `paralyz→Paralyzed`, `stun→Stunned`, `frighten→Frightened`,
  `poison→Poisoned`, `restrain→Restrained`, `prone→Prone`, `deafen→Deafened`,
  `sleep|unconsci→Unconscious`, `incapacit→Incapacitated`, `charm→Charmed`,
  `petrif→(escalation, §4)`, `push|repuls→Push` (capture the `Nft` → `push_ft`).
- **Save-ability heuristic** (the condition's *target* save, distinct from the
  damage save): physical restraint/poison/paralysis/petrify/stun → `SaveCon`;
  fear/charm/sleep/incapacitate/blind-by-light → `SaveWis`; Web/Repulsion
  positional → `SaveDex`/`SaveStr`. `save_dc_ability` = `SaveSpellcasterMod`.
  Provide an override hook (see §5) for the inevitable exceptions.
- **Routing:**
  - clause has parsed damage **and** a condition keyword → keep the existing
    `Breath<Element><Shape><Tier>` damage assignment, emit an
    `npc_spell_conditions` rider for that monster keyed on that catalog name.
  - clause has a condition keyword but **no** parsed damage → mint/assign a
    `Breath<Condition><Shape><Tier>` shell (condition baked in), add it to
    `spell_indices` + `npc_spell_recharge`.
- `on_damage`: Sleep/Unconscious → `"end"`; Incapacitate (Hypnotic-style) →
  `"end"`; Hideous-Laughter-style → `"repeat_save"`. Default `None`.

Keep the deriver **idempotent and `--write`-gated**, same as Step 3. Re-running
must reproduce identical `npc_spell_conditions`/shells.

## Step 4 — Escalation breaths (the one real engine gap)

Several breaths escalate on a *second* consecutive failed save:

- Dragon **Paralyzing Breath** (Silver/young/wyrmling): 1st fail → Incapacitated,
  2nd fail → Paralyzed.
- **Gorgon** Petrifying Breath: 1st fail → Restrained, 2nd fail → Petrified.

The current `AttackCondition` applies one condition per failed save and has no
"upgrade on repeat failure" concept. Two options:

- **(Recommended) Approximate now, escalate later.** Apply only the *milder*
  condition (Incapacitated / Restrained) via the normal path; log the deferred
  upgrade in `known_limitations.md`. Zero engine work, faithful enough for the
  sim, ships with the rest of this pass.
- **Full fidelity (later).** Add `std::string escalate_to` +
  `bool escalate_on_repeat_fail` to `AttackCondition`; in the per-turn condition
  re-save tick, on a *failed* repeat save swap `condition_name → escalate_to`
  instead of clearing. New field must round-trip in `helpers._dict_to_attack_condition`
  and the bindings. Defer unless requested.

Treat escalation as out-of-scope for the first cut; ship the approximation.

## Step 5 — Overrides (`tools/monster_breath_overrides.json`)

Extend the existing override schema with a `conditions` key so the special cases
the deriver can't infer are explicit data, not code:

- **Gorgon / Paralyzing-Breath dragons** → `conditions` with the milder
  condition + a `"comment"` noting the deferred escalation (§4).
- **Faerie Dragon** Euphoria Breath → `Incapacitated`; "moves in random
  directions" deferred (comment).
- **Bronze dragons** Repulsion Breath → `Push` with `push_ft` from the notes
  (already supported by the Push path).
- **Satyr Revelmaster** Fey Melody ("charmed OR 10 psychic + frightened") and
  **Sea Hag** Death Glare (HP-threshold instakill) — keep `skip`; genuinely
  bespoke, note in `known_limitations.md`.
- Flip the current `"skip"` entries that are pure-condition (Giant Spider Web,
  Graveyard Revenant paralyze, Swarm of Ravens deafen) into condition shells.

## Step 6 — Tests  (`gui/test_condition_breaths.py`; USER runs the suite)

Mirror `test_condition_saves.py`'s harness (`execute_spell` + `SpellAction` +
`get_agent_conditions`):

- **Condition-only shell:** cast `BreathBlindingConeLow` at a low-save target →
  `conditions.blinded == True`; at a guaranteed-save target (huge CON / forced
  high d20) → not applied.
- **Damaging breath + rider:** cast a damage breath whose monster has an
  `npc_spell_conditions` rider → target takes damage AND gets the condition on a
  failed save; saves block the condition but damage (halved) still lands.
- **Push rider:** Repulsion breath moves the target `push_ft`.
- **Loader integration:** load a bestiary record carrying `npc_spell_conditions`
  via `_load_npc_spells_from_record`, assert the built spell's `conditions`
  include the rider.
- **Data guard:** every name in each record's `npc_spell_conditions` /
  condition-shell `spell_indices` resolves to a catalog spell (no dangling refs),
  and every `condition_name` is a real engine condition flag.

---

## Summary of touch points

| File | Change | Rebuild? |
|------|--------|----------|
| `main.py` `_load_npc_spells_from_record` | apply `npc_spell_conditions` | no |
| `main.py` save/restore + `_agent_meta` | persist `npc_spell_conditions` | no |
| `helpers.py` | factor `_dict_to_attack_condition`, share it | no |
| `tools/derive_breath_weapons.py` | condition-parse pass + shells + riders | no |
| `tools/monster_breath_overrides.json` | `conditions` key for specials | no |
| `gui/spells.json` | condition-shell catalog spells (deriver-written) | no |
| `gui/DND2024_MonsterStats.json` | `npc_spell_conditions` per monster (deriver-written) | no |
| `gui/test_condition_breaths.py` | new tests | no |
| `condition.hpp`/bindings | **only if** §4 full-fidelity escalation is wanted | yes |

The first cut (Steps 1–3, 5, 6 + §4 approximation) is **data + Python only — no
rebuild** — because the engine already applies `sp.conditions`. The only thing
that forces a C++ build is the optional escalation field or, if the build check
in Step 2 surfaces it, allowing condition application on a damage-less Save AoE.

### Monsters in scope (from `action_notes`)

**Damaging + rider:** Demilich (Frightened), Dire Worg (Frightened), Sphinx of
Lore (Incapacitated), Tarrasque (Deafened+Frightened), Mind Flayer Arcanist
(Stunned), Lizardfolk Geomancer (Prone), Primeval Owlbear (Frightened), Vrock
(Poisoned), Violet Fungus Necrohulk (Poisoned), Archpriest (Stunned), Bandit
Deceiver (Blinded), Bone Naga (Charmed), Ultroloth (Stunned), Storm Giant
(condition TBD), Abominable Yeti / Yeti (Paralyzed, near-zero damage).

**Condition-only:** Dust/Smoke Mephit (Blinded), Mud Mephit (Restrained),
Modron Pentadrone (Paralyzed), Jackalwere (Unconscious), Giant Spider /
Ettercap / Vine Blight Tangler (Restrained), Graveyard Revenant (Paralyzed),
Swarm of Ravens (Deafened), Faerie Dragon (Incapacitated), dragon Sleep Breath
(Incapacitated), dragon Repulsion Breath (Push).

**Escalation (approximate now, §4):** Paralyzing-Breath dragons
(Incapacitated→Paralyzed), Gorgon (Restrained→Petrified).

**Stay `skip` (bespoke):** Sea Hag Death Glare, Satyr Fey Melody, Salamander
Inferno Blast, Ghost Possession, Elemental Cataclysm, Air/Water Elemental
Whirlwind/Whelm, Brazen Gorgon Smelting Charge, Gnoll Pack Lord Incite Rampage.
