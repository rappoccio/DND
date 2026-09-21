# Spell Implementation Plan (Reconciled)

_Reconciled 2026-07-24. Supersedes `Spells to wire.md` (hand list) and folds in a
full audit of `gui/spells.json` (405 spells)._

This is the single source of truth for spell wiring. It merges:
1. The hand-maintained `Spells to wire.md` completion log.
2. A programmatic audit of all 405 spells (payload flags + name-keyed code paths).
3. The engine's own authoritative out-of-scope list
   (`npc_classification_ignore_`, `gui/combat_turn.cpp:2616`).

## Functional-classification method

A spell is **functional** if *either*:
- **Payload-bearing** — JSON carries damage, a `conditions` list, or a special
  flag (`terrain_effect`, `teleportation_spell`, `dispels_magic`, `hp_pool`,
  `revives_dead`, `animates_dead`, `effects_on_begin_turn`, …); **or**
- **Name-keyed** — the spell name is a string literal in `gui/*.cpp|hpp|py`.

| Category | Count |
|---|---|
| Functional (JSON payload) | 202 |
| Functional (name-keyed only) | 91 |
| **Not wired (neither)** | **112** |
| Total | 405 |

> ⚠️ Name-keyed ≠ provably complete (a few could be partial stubs). The 112
> "not wired" spells are the real backlog and drive the tiers below.

---

## ✅ Completed (from `Spells to wire.md`, verified against code)

| Spell | Wiring evidence |
|---|---|
| Bless | name-keyed (`"Bless"`) |
| Haste | name-keyed |
| Aid | name-keyed |
| Dispel Magic | name-keyed + `dispels_magic` |
| Animate Dead | `animates_dead` flag |
| Power Word: Fortify | `hp_pool` + `pool_is_temp_hp` |
| Power Word: Stun | `condition_hp_threshold` |
| Power Word: Kill | `instant_kill_threshold` |
| Mass Heal | `hp_pool: 700` |

### ⚠️ Discrepancy — Animal Shapes (marked `[x]` but NOT wired)

`Spells to wire.md` marks **Animal Shapes** done, but the audit finds **no
name-keyed path and no payload** for the spell. The underlying **WildShape
transform machinery does exist** (`activateWildShape`/`deactivateWildShape` in
`combat_resources.cpp`, driven by `beast_forms.json` for Druid Wild Shape), but
nothing routes the *spell* Animal Shapes into it. **Action:** either wire Animal
Shapes onto WildShape (see Tier 3/transform) or correct the checkbox. Treated as
**not done** below.

---

## Tier 1 — Quick wins (combat-relevant, reuse existing mechanics)  ✅ DONE (2026-07-24)

Mostly data + a small flag on machinery that already exists. All 12 implemented via new
`Agent::Stats` buff/debuff flags (round-tripped through agent_loader/main.py/rpg_bindings),
condition apply/clear branches keyed off the condition names below, and JSON payloads.

| Spell | Lvl | Effect | Implementation |
|---|---|---|---|
| False Life | 1 | 2d4+4 temp HP | data-only: `hp_pool:9` + `pool_is_temp_hp` (fixed avg, no dice) |
| Longstrider | 1 | +10 ft speed | `Longstriding` cond → `longstrider_bonus` on `speed_walk` |
| Expeditious Retreat | 1 | Dash as bonus action | `ExpeditiousRetreat` cond → grants `has_cunning_action` (Dash/Disengage/Hide bonus) |
| Blur | 2 | Attackers have disadvantage | `Blurred` cond → `attackers_disadvantage` (Blindsight/Truesight carve-out not modeled) |
| Barkskin | 2 | AC floor 17 | `Barkskinned` cond → raises `base_ac` to 17 (`barkskin_ac_bonus` delta) |
| Ray of Enfeeblement | 2 | CON save → disadv attacks + −1d8 dmg | `Enfeebled` cond → `enfeebled` (attack disadv + rollDamage −1d8); STR-test approx |
| Enlarge/Reduce | 2 | ±1d4 weapon dmg | `Reduced` cond (debuff) via `size_damage_dice`; `Enlarged` handler latent (needs mode selector) |
| Regenerate | 7 | Heal 4d8+15 + 1 HP/turn | `type:Heal` burst + `Regenerating` cond → `regeneration_amount` (turn-start heal) |
| Divine Word | 7 | CHA save, HP-threshold effects | bespoke name-keyed block (die / Blind+Deaf+Stun / Blind+Deaf / Deaf); banish out of scope |
| Dominate Monster | 8 | Charmed control | `Charmed` cond (Wis save, re-save on damage); also fixed Dominate Person/Beast stubs |
| Mind Blank | 8 | Immunity to Psychic + Charmed | `MindBlank` cond → `immune_charm` + Psychic mult 0 |
| Foresight | 9 | Advantage on all + attackers disadvantage | `Foresight` cond → `has_foresight` (attack+save adv) + `attackers_disadvantage` |

## Tier 2 — Control / terrain / ward (reuse existing chokepoints, more work)

Leverage wall `terrain_effect`, Magic Circle movement-ward, petrify snapshots,
and Banishment.

**Status: 11 / 15 DONE + tested** (`tests/test_spells_tier2.py`, all green 2026-07-29).
The 4 remaining are the plan's "new-mechanic" items (see build order step 4).

| Spell | Lvl | Effect | Reuse | Status |
|---|---|---|---|---|
| Antilife Shell | 5 | 10-ft keep-out emanation | Magic Circle `movementWardBlocks` (`ward_all_living`) | ✅ done |
| Wall of Stone | 5 | Solid wall | terrain effect `sets_wall` → `TerrainType::Wall` | ✅ done |
| Flesh to Stone | 6 | CON save → Restrained → petrified | CON save → Restrained + re-saves (petrify simplified out) | ✅ done |
| Eyebite | 6 | WIS save → Asleep / Panicked / Sickened | WIS save → Frightened | ✅ done |
| Irresistible Dance | 6 | WIS save → Charmed + waste movement | WIS save → Incapacitated + re-save | ✅ done |
| Resilient Sphere | 4 | DEX save → enclosed, can't act/be targeted | DEX save → Incapacitated | ✅ done |
| Forcecage | 7 | Trap target in cage | `Forcecaged` cond (+ Box seal, teleport-out CHA gate) | ✅ done |
| Reverse Gravity | 7 | DEX save AoE, fall upward | Sphere: 6d6 bludgeoning + Prone (save-for-half) | ✅ done |
| Symbol | 7 | Harmful glyph AoE | Sphere: 10d10 Necrotic (Death rune, save-for-half) | ✅ done |
| Maze | 8 | Banish to demiplane | INT save → Incapacitated + INT re-save | ✅ done |
| Imprisonment | 9 | WIS save → removed from play | WIS save → Incapacitated (no escape) | ✅ done |
| Holy Aura | 8 | Team emanation: adv saves / disadv attacks vs allies | Paladin / `grants_advantage_aura` framework | ⬜ deferred |
| Globe of Invulnerability | 6 | Blocks spells ≤ L5 in emanation | anti-spell bubble (emanation prune exists) | ⬜ deferred |
| Antimagic Field | 8 | Suppress magic in emanation | **new** — largest item in tier | ⬜ deferred |
| Time Stop | 9 | 1d4+1 extra turns | Haste extra-action / turn-injection | ⬜ deferred |

## Tier 3 — Summon / conjure / transform subsystem

Two frameworks unlock a big cluster at once.

**Summon framework** — ✅ **DONE (data-side, 2026-07-29).** The scaling-spirit
framework (`compute_summon_loadout` + `SUMMON_SPELL_TO_SPIRIT`, auto-loaded from
`gui/summons.json` — renamed from `summon_spirits.json`) is keyed by spell name, so
every spell below is now castable via the existing GUI form-picker / placement /
concentration-dismissal flow with **zero code change** — each is one or more JSON
records in `summons.json`. Tests: `tests/test_summoning.py`.
- ✅ Summon Beast (2), Summon Fey (3), Summon Undead (3), Summon Elemental (4),
  Summon Dragon (5), Summon Shadowspawn (5), Summon Fiend (6) _(already present)_
- ✅ Summon Aberration/Celestial/Construct _(already present)_
- ✅ Conjure Elemental (5), Conjure Celestial (7) _(added; see caveat below)_
- ✅ Giant Insect (4), Arcane Hand / Bigby's (5), Create Undead (6),
  Planar Ally (6), Gate (9) _(added)_
- **Animate Objects (5)** — _explicitly deferred in `Spells to wire.md`; keep deferred._

> **Caveats on the newly-added blocks.** The seven conjure/named summons carry
> `"verified": false` — they are combat-sim approximations, **not** transcribed PHB
> cards, and should be rechecked against the book. In 2024 RAW several of them
> (Conjure Elemental, Conjure Celestial) are AoE/utility effects, not summons; they
> are modeled here as scaling summon-spirits per this tier's design. `Gate` is
> 9th-level-only, so its stat block cannot upcast (HP does not grow). No ally-side
> turn *driver* was added — summoned spirits use the existing NPC/ally automation.

**Transform framework** — WildShape machinery exists (`activateWildShape`); wire
spells onto it:
- Animal Shapes (8) _(resolves the discrepancy above)_, Shapechange (9)
  _(Shapechange is also tracked in Tier 5 Group E — same spell, wire once)_

**Companions (lower combat priority):** Find Familiar (1), Find Steed (2).
_Phantom Steed is out of scope — see below (needs mounts)._

## Tier 4 — Borderline (decide case-by-case before building)

| Spell | Lvl | Note |
|---|---|---|
| Resurrection (7), True Resurrection (9), Reincarnate (5) | — | Revive framework exists (Raise Dead/Revivify wired); variants |
| True Seeing (6), Darkvision (2) | — | Truesight exists (epic boon); quick sense-buffs |
| Pass without Trace | 2 | Stealth +10 — relevant if PreferHide is expanded |
| Goodberry | 1 | 1 HP heal — trivial, marginal value |

---

## Out of scope (utility / exploration / social / illusion / flavor)

Not planned, per the Combat-Sim-Only rule. **Bolded** entries are confirmed by
the engine's own `npc_classification_ignore_` list, several with documented
reasons:

- **Mage Armor** — AC pre-baked into stat blocks.
- **Phantom Steed** — needs a mount system.
- **Feather Fall, Levitate** — need a vertical axis.
- **Creation, Disguise Self,
  Dancing Lights, Elementalism, Druidcraft, Guidance, Thaumaturgy, Mending,
  Detect Magic/Thoughts/Evil and Good, Speak with Animals,
  Animal Messenger, Animal Friendship, Commune, Scrying, Arcane Eye, Locate
  Object, Legend Lore, Tongues, Nondetection, Pass without Trace, Hallucinatory
  Terrain, Unseen Servant, Create or Destroy Water, Control Weather** — flavor /
  out-of-combat utility (engine ignore list).

  > **Promoted out of this list by user (now Tier 5):** Shapechange, Wind Walk,
  > Major Image, Minor Illusion, Light, Mage Hand. When these are built, the
  > engine's `npc_classification_ignore_` list must drop them too.

Other clearly out-of-scope utility not in the ignore list: Comprehend Languages,
Identify, Illusory Script, Silent Image, Alter Self, Arcanist's Magic Aura,
Enthrall, Locate Animals or Plants, Magic Mouth, Rope Trick, Spider Climb, Tiny
Hut, Water Breathing, Private Sanctum, Secret Chest, Awaken, Commune
with Nature, Telepathic Bond, Teleportation Circle, Tree Stride,
Contingency, Find the Path, Guards and Wards, Magic Jar, Programmed
Illusion, Transport via Plants, Word of Recall, Instant Summons,
Magnificent Mansion, Sequester, Clone, Demiplane, Glibness, Astral Projection,
Floating Disk, Message, Prestidigitation.

> **Promoted out of this list by user (now Tier 5):** Fabricate, Passwall, Move
> Earth, Etherealness, Project Image, Simulacrum, Antipathy/Sympathy, Shillelagh.

## Tier 5 — User-promoted (combat relevance confirmed by user)

The user reviewed the out-of-scope list and confirmed the spells below have real
combat relevance. They have been **removed from the out-of-scope lists above** and
are tracked here. Grouped by the mechanic each reuses; the user's original
rationale is preserved as _Why_.

**Group A — Terrain modification** — reuse the wall carve + terrain-paint
machinery from Wall of Stone / `terrain_effect` (create *and* destroy cells
mid-combat):

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Move Earth | 6 | Relocate a ~40 ft wall segment | terrain carve + repaint (move cells) |
| Passwall | 5 | Remove one wall square mid-combat | terrain carve (inverse of Wall of Stone) |
| Fabricate | 4 | Create a bridge over water/chasm | terrain paint floor over Water/Chasm cells |
| Major Image | 3 | CREATE (not destroy) terrain mid-combat | terrain paint, create-only |

_Why (user):_ Move Earth moves 40 ft of wall; Passwall removes one wall square;
Fabricate bridges water/chasms; Major Image can at least create terrain.

**Group B — Illusion lures** — needs a new NPC "investigate the illusion"
behavior: enemies that cannot see the caster (Hiding/Invisible) path toward the
illusion; used to group enemies for AoE (BG-style) or distract:

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Minor Illusion | cantrip | Lure unseeing enemies to a point; Study check to disbelieve | **new** lure/investigate AI |
| Project Image | 7 | Like Minor Illusion, but the lured agent takes the Attack action against it | lure + attack |
| Simulacrum | 7 | Pre-combat self-copy that fights like a summons | summon framework (Tier 3) + halved-stat caster clone |

_Why (user):_ Minor Illusion groups enemies via a Study check; Project Image
draws an Attack action; Simulacrum is a pre-combat self-summons.

**Group C — Mage Hand utility:**

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Mage Hand | cantrip | Grant advantage (Rogue Legerdemain), push agents, open doors | shove/push + door-open + advantage grant |

**Group D — Movement / targetability:**

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Wind Walk | 6 | Fly speed (cross chasms/water) | fly movement (`npcMovementType` fly) |
| Etherealness | 7 | Move up to speed, untargetable until leaving the plane | removed-from-play/untargetable + free move (Blink/Forcecage family) |

**Group E — Transform:**

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Shapechange | 9 | Nearly identical to Wild Shape | `activateWildShape` — **dedup with Tier 3 transform (same spell)** |

**Group F — Buffs / debuffs (near-Tier-1 data):**

| Spell | Lvl | Effect | Reuse / notes |
|---|---|---|---|
| Light | cantrip | Torch-equivalent light source | existing lighting system |
| Antipathy/Sympathy | 8 | Inflict Frightened (antipathy) or Charmed-lure (sympathy) | Frightened + Charmed conditions |
| Shillelagh | cantrip | Bonus-action True-Strike-like buff for bludgeoning weapons; **melee attack + damage use the spellcasting ability, not STR/DEX** | True Strike buff + new spell-ability-override flag on Weapon/Stats |
| Absorb Elements | 1 | Reaction: halve incoming (elemental) damage | damage-halving (resistance) as a reaction |

_Why (user):_ Light = torch in the existing light system; Antipathy/Sympathy
inflicts Frightened/Charmed; Shillelagh ≈ True Strike (bludgeoning, bonus action,
spellcasting-ability melee stat); Absorb Elements should halve damage.




---

## Suggested build order

1. **Tier 1** — near-pure data, biggest count-per-effort.
2. **Tier 2 chokepoint reuses** — Wall of Stone, Flesh to Stone, Maze, Antilife
   Shell, Symbol, Dominate Monster.
3. **Tier 3 summon framework** — one design investment, ~14 spells; then wire
   Animal Shapes/Shapechange onto existing WildShape.
4. **Tier 2 new-mechanic items** — Antimagic Field, Time Stop, Holy Aura.
5. Revisit Tier 4 once transform/verticality/mount scope is decided.
6. **Tier 5 (user-promoted)** — cheapest first: Group F buffs (Light,
   Shillelagh, Absorb Elements, Antipathy/Sympathy) and Group A terrain reuse;
   then Group D fly/ethereal movement; defer Group B illusion-lure AI and
   Group C Mage Hand (both need new NPC behaviors), plus Simulacrum (rides the
   Tier 3 summon framework).




