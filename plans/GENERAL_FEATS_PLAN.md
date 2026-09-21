# General Feats — Implementation Plan (2024 PHB)

Status: PLANNING (discuss before implementing). Builds on the feat system shipped 2026-06-09
(`feats` vector + `hasFeat`/`addFeat` on `Agent::Stats`, GUI origin-feat picker). See
`memory/feat_system.md` and `memory/known_limitations.md` ("Origin feats").

Scope rule (per `feedback_scope_combat_sim`): implement combat-relevant mechanics; note
out-of-combat/flavor in `known_limitations.md`. Reuse existing engine hooks; don't invent
parallel paths (`feedback_rider_pattern_parity`, `feedback_reusable_bonus_attack`).

---

## Cross-cutting design decisions — LOCKED 2026-06-09

> Confirmed: (1) ASI **not** auto-applied · (2) **multi-select** Feats dialog · (3) soft prereqs ·
> (4) `heavy`/`light` weapon flags · (5) **Hit-Dice pool DEFERRED** — HD-dependent benefits
> (Durable Speedy Recovery, Chef, Healer Battle Medic) stay noted, not built. · Phase order: **G0 + G1 first.**

1. **Ability Score Increase (ASI) is NOT auto-applied by feats.** Almost every general feat
   bundles a +1 (or +2) ability bump. The GUI stat steppers are already the source of truth for
   final ability scores, and ability changes ripple into AC/saves/attacks/HP — stripping them on a
   feat swap (the idempotency problem we solved for Tough HP) would be far worse. So feats
   implement only their *special* benefits; you set final ability scores via the existing steppers.
   The standalone **"Ability Score Improvement"** feat then has no mechanical effect of its own
   (it's a marker / handled by editing scores).

2. **Multiple feats per PC.** Unlike origin feats (exactly one), a PC accrues several general feats.
   The `feats` vector already supports this. The GUI needs to grow from the single origin-feat
   cycle picker into a **multi-select feat dialog** (checkbox list like the Warlock Invocations
   picker). Origin feat stays its own single-select control.

3. **Prerequisites are soft.** Level 4+, ability 13+, armor/spellcasting prereqs are shown as info
   but not hard-blocked (combat-sim convenience). Easy to harden later.

4. **Small weapon-property infra.** Add `heavy` and `light` bool flags to `Weapon`
   (Reach is derivable from `reach_ft > 5`; crossbow from name). Needed by GWM / Dual Wielder /
   Polearm Master / Crossbow Expert. Additive, low-risk.

5. **Hit-Dice pool — DEFERRED.** "Spend a Hit Die to heal" (Durable Speedy Recovery, Chef,
   Healer Battle Medic) is NOT built this pass; those benefits stay in known_limitations.md.
   Durable's Defy Death (Advantage on death saves) still ships — it needs no HD pool.

---

## Per-feat verdict

Legend: **C** = implement combat mechanic · **P** = partial (combat bit in, rest noted) ·
**N** = note only (out of combat / no infra) · reuse = existing hook leaned on.

| Feat | Verdict | Combat mechanic → reuse |
|------|:------:|-------------------------|
| Ability Score Improvement | N | ASI only → stat steppers (decision #1) |
| Actor | N | Cha checks / mimicry — out of combat |
| Athlete | P | Climb Speed = Speed (`speed_climb`); Hop-up (prone-stand 5 ft). Jump = N |
| Charger | P | Improved Dash (+10 on Dash); Charge Attack (+1d8 / push) needs straight-line-10ft move tracking |
| Chef | N→P | Rest food + Bonus-Action treat temp HP — rest-based; treat temp HP needs HD/temp-HP plumbing → defer/note |
| Crossbow Expert | C | Firing in Melee (no melee disadvantage); off-hand crossbow ability mod; ignore Loading |
| Crusher | C | Bludgeoning hit → push 5 ft (once/turn); bludgeoning crit → attackers have Advantage vs target. reuse: on-hit rider + crit hook |
| Defensive Duelist | C | **DONE 2026-06-10** Parry reaction: +PB AC vs a melee hit (finesse), folded into the defenderOnHit window (canDefensiveDuelist/applyDefensiveDuelist) |
| Dual Wielder | C | Enhanced Dual Wielding extra bonus melee attack. reuse: bonus-attack flow. Quick Draw = N |
| Durable | P | Defy Death (Advantage on death saves) via `rollDeathSave`. Speedy Recovery needs HD pool |
| Elemental Adept | C | Spells ignore Resistance to chosen type + treat 1→2 on that type's dice. reuse: damage calc |
| Fey Touched | P | Grant Misty Step + 1 spell (spell picker); free 1/LR cast = light infra → note |
| Grappler | C | **DONE 2026-06-10** Punch-and-Grab (unarmed hit → also Grapple, once/turn) via `resolveGrapple`; Advantage vs grappled. Fast Wrestler = no-op (no drag-movement system). **user-flagged** |
| Great Weapon Master | C | Heavy hit → +PB damage; Hew (crit/kill → bonus attack). reuse: on-hit + bonus-attack flow |
| Heavily Armored | N | Heavy-armor training (engine doesn't enforce armor prof) |
| Heavy Armor Master | C | −PB to B/P/S while in Heavy armor. reuse: `processDamageTaken` |
| Inspiring Leader | N→P | Rest temp HP to allies — rest-based (like Musician/Chef) → defer/note |
| Keen Mind | N | Skill/Expertise + Bonus-Action Study — out of combat |
| Lightly Armored | N | Light-armor/shield training — prof not enforced |
| Mage Slayer | C | **Concentration Breaker DONE 2026-06-10** (damager-feat → Disadvantage on the conc save, via checkConcentrationOnDamage damager_idx). Guarded Mind (OnSaveFail auto-succeed, 1/short rest) DEFERRED |
| Martial Weapon Training | N | Weapon prof grant — not enforced |
| Medium Armor Master | P | +3 (not +2) Dex to AC in Medium armor — AC calc tweak |
| Moderately Armored | N | Medium-armor training — prof not enforced |
| Mounted Combatant | N | No mount system — defer wholesale |
| Observant | N | Skill/Expertise + Bonus-Action Search — out of combat |
| Piercer | C | Piercing hit → reroll 1 damage die (once/turn); piercing crit → +1 damage die. reuse: reroll + crit hook |
| Poisoner | P | Potent Poison (poison ignores Resistance) → damage calc. Brew Poison (apply → CON save 2d8 + Poisoned) = more infra → phase 2 |
| Polearm Master | P | Pole Strike (Bonus-Action d4 attack) via bonus-attack flow; Reactive Strike (OA on enter-reach) = new reaction window → phase 2 |
| Resilient | C | Save proficiency grant (`save_prof_*`). Trivial passive |
| Ritual Caster | N | Ritual spells — out of combat |
| Sentinel | C | **DONE** (clause 2 Disengage-OA + clause 1 Halt + clause 3 Guardian, the OnAllyAttacked window). All 3 clauses complete 2026-06-10 |
| Shadow Touched | P | Grant Invisibility + 1 spell (spell picker); free 1/LR cast → note |
| Sharpshooter | C | No melee disadvantage on ranged; no long-range disadvantage (`hasDisadvantage`); ignore cover (cover not modeled → note) |
| Shield Master | C | **Push DONE 2026-06-10** (canShieldBash gate: feat + holding a Shield + bonus action; shove reuses executeShove). Interpose Shield (OnSave DEX-half → no damage reaction) DEFERRED |
| Skill Expert | N | Skill prof + Expertise — out of combat |
| Skulker | P | Blindsight 10 ft (`blindsight_range`); Stealth advantage / Sniper = N |
| Slasher | C | Slashing hit → −10 Speed (`hamstrung` exists); slashing crit → target Disadvantage on attacks. reuse: on-hit + crit hook |
| Speedy | C | +10 Speed; Dash ignores Difficult Terrain; OA Disadvantage vs you |
| Spell Sniper | C | No melee disadvantage on spell attacks; +60 ft range; ignore cover (note) |
| Telekinetic | P | Telekinetic Shove (Bonus Action, STR save → move 5 ft) — forced move + save. Mage Hand grant = N |
| Telepathic | N | Detect Thoughts / telepathy — out of combat |
| War Caster | C→P | **Concentration Advantage DONE 2026-06-10** (conc CON save, in checkConcentrationOnDamage + concentrationSave). Reactive Spell (OA→cast) = complex, deferred; Somatic = N |
| Weapon Master | P | Use a weapon's Mastery property (set `weapon_mastery`); prof grant = N |

---

## Proposed phasing (group by shared mechanism for efficient, low-risk PRs)

**Phase G0 — Infra + GUI (foundation).**
- `Weapon.heavy` / `Weapon.light` flags (+ bindings, weapon presets, save/load).
- Multi-select **Feats dialog** (checkbox list of general feats) wired into StatsDialog;
  `feats` round-trips; ASI not auto-applied (decision #1).
- (Optional, decision #5) minimal Hit-Dice pool on Stats.

**Phase G1 — Damage-type on-hit riders + GWM (highest combat value, one cohesive pattern).**
Crusher, Piercer, Slasher, Great Weapon Master. All hook `applyAttackResult` (once/turn rider keyed
on `r.physical_damage_types`) + the crit branch. Mirrors Tavern Brawler push / Savage reroll /
`hamstrung`. New per-turn flags + reset in `Agent::turn()`.

**Phase G2 — Grappler + Sentinel (user-flagged + half-built). DONE 2026-06-10.**
~~Grappler onto `resolveGrapple`~~ Punch-and-Grab + Advantage-vs-grappled done (Fast Wrestler = no-op, no
drag-movement system); ~~finish Sentinel (Halt speed-0 + Guardian ally clause)~~ **Sentinel done** (all 3
clauses — Guardian via the OnAllyAttacked window). **Phase G2 complete.**

**Phase G3 — Reaction feats. MOSTLY DONE 2026-06-10.** + shield-in-off-hand foundation (Weapon.is_shield →
a Shield equips in a weapon/off-hand slot; isHoldingShield predicate; calculateAC scans all slots;
weapons.json "Shield" entry; helpers carry is_shield/ac_bonus). Done: War Caster (Advantage on conc saves),
Mage Slayer Concentration Breaker (damager-feat → Disadvantage on conc save, via checkConcentrationOnDamage
damager_idx), Defensive Duelist (OnHit +PB-AC reaction, folded into the existing defenderOnHit window),
Shield Master Push (canShieldBash gate; shove reuses executeShove). **Deferred** (known_limitations.md):
Shield Master Interpose (reaction at the spell save-for-half site), Mage Slayer Guarded Mind (save-override),
Shield Master GUI bonus-shove offer.

**Phase G4 — Bonus-attack + ranged-penalty feats. MOSTLY DONE 2026-06-11** (built + green,
`gui/test_general_feats_g4.py`, 17 cases). Done: Sharpshooter (no long-range / firing-in-melee Disadv),
Crossbow Expert (firing-in-melee for Crossbows; Loading + off-hand mod note-only), Spell Sniper
(firing-in-melee + `effectiveSpellRange` +60 ft), Great Weapon Master Hew (`gwm_hew_available` →
`_offer_gwm_hew` → shared `_start_extra_attack`), Dual Wielder (+1 AC with two melee weapons; off-hand
attack already works). **Deferred:** Polearm Master — Pole Strike (synthetic butt-end 1d4 weapon = new
infra) + Reactive Strike (enter-reach reaction window). See known_limitations.md "phase G4".

**Phase G5 — Damage/resistance/saves + movement passives. MOSTLY DONE 2026-06-11** (built + 66 suites
green, `gui/test_general_feats_g5.py`, 14 cases). Done: Heavy Armor Master (−PB B/P/S in Heavy armor),
Medium Armor Master (+3 DEX cap), Durable (Advantage on death saves), Resilient (marker — save prof via
StatsDialog checkboxes), Speedy (+10 ft + OA Disadvantage via `Attack::opportunity`), Athlete (stand from
prone = 5 ft), Skulker (Blindsight 10 ft), Telekinetic Shove (`apply_telekinetic_shove`, STR save + 5 ft
push via `forceMoveAgent`; GUI button), Weapon Master (Nick gate). Also a binding fix: `Armor.dex_mod_cap`
now round-trips (was always 30). **Phase G5b — resistance-ignore caster feats. DONE 2026-06-11** (built + 67 suites green,
`gui/test_general_feats_g5b.py`, 9 cases). Elemental Adept (caster's spells ignore Resistance to chosen
elements + treat-1-as-2 on those dice; chosen elements stored in `Stats::elemental_adept_types`, bound +
saved) and Poisoner (Potent Poison: Poison damage from any source ignores Poison Resistance). Two shared
helpers — `effectiveMagicDamageMult` (lifts Resistance, leaves Immunity) + `rollSpellTypeDamage`
(treat-1-as-2) — applied across all 5 spell magic-damage sites + the weapon magic site. Reusable
`ElementPickerDialog` opened from the feat picker; built to also serve Chromatic Orb / Sorcerous Burst
cast-time element choice (next consumer, not yet wired). Deferred: Poisoner Brew/Apply Poison. See
known_limitations.md "phase G5b".

**Phase G6 — Spell-grant feats.** Fey Touched, Shadow Touched, Telepathic via the spell picker;
note free-cast tracking. (Mostly data; least engine work.)

**Deferred/phase-2 within feats:** Polearm Reactive Strike (enter-reach reaction window), War Caster
Reactive Spell, Poisoner Brew Poison, Charger Charge Attack (straight-line tracking), Mounted
Combatant (no mount system), all rest-based temp-HP feats (Chef, Inspiring Leader).

**Note-only → known_limitations.md:** Ability Score Improvement, Actor, Keen Mind, Observant,
Skill Expert, Ritual Caster, Telepathic, and the armor/weapon-proficiency feats (Heavily/Lightly/
Moderately Armored, Martial Weapon Training) since proficiency restrictions aren't modeled.

---

## ✅ G0 + G1 — DONE 2026-06-10 (built, 60 suites green)

Shipped: `Weapon.heavy`/`light` flags (+ bindings, `_dict_to_weapon`, weapons.json tagged) ·
multi-select **FeatDialog** (43 general feats, status tags) wired into StatsDialog →
`App._set_general_feats` (disjoint from the origin picker; ASI not applied) · **Crusher** push ·
**Piercer** Puncture reroll + crit extra die · **Slasher** Hamstring (−10 ft via `slowed`) ·
**Great Weapon Master** Heavy +PB damage. Tests: `gui/test_general_feats.py` (9 cases).

**G1b — enhanced-crit advantage effects — DONE 2026-06-10.** Crusher (attack rolls against the
crit target have Advantage) and Slasher (the crit target's attacks have Disadvantage), each a
Conditions mark on the victim + `*_marked_by` source index, checked in `determineAdvantage`
(Reckless-style) and cleared in `beginTurn` at the *feat-user's* next turn (correct "until your next
turn" expiry; the GUI reaches beginTurn via begin_turn_flow). Tests in `test_general_feats.py`.

Still split out of G1 (deferred, see known_limitations.md):
- **GWM Hew** (crit/kill → bonus attack) → folded into the bonus-attack phase (G4).
- Piercer Puncture approximation: rerolls the lowest die in `dice_results` using the weapon's
  Piercing die size (may not be the exact piercing die on multi-type weapons); "must use new roll"
  applied unconditionally.

## (Original) G0 + G1 task breakdown

**G0 — infra + GUI**
- C++: add `bool heavy{false}` / `bool light{false}` to `Weapon` (+ bindings, save/load, presets).
- GUI: a multi-select **Feats dialog** (checkbox list of general feats, like `InvocationDialog`),
  launched from StatsDialog; selected names merged into `stats.feats` alongside the origin feat;
  ASI not applied. Round-trips through existing `feats` save/load.
- Per-feat once/turn flags added to `Conditions` as each feat lands; reset in `Agent::turn()`.

**G1 — damage-type on-hit riders + Great Weapon Master** (all in `applyAttackResult`)
- **Crusher**: Bludgeoning hit → push 5 ft to an unoccupied space, once/turn (`forceMoveAgent`);
  Bludgeoning crit → attackers have Advantage vs the target until your next turn (target condition).
- **Piercer**: Piercing hit → reroll one damage die, once/turn (Savage-style, keep new roll);
  Piercing crit → +1 damage die of the piercing damage.
- **Slasher**: Slashing hit → −10 Speed until start of your next turn (`hamstrung`), once/turn;
  Slashing crit → target has Disadvantage on attacks until start of your next turn.
- **Great Weapon Master**: Heavy-weapon hit (Attack action) → +PB damage; Hew (crit or drop-to-0
  with a melee weapon) → one bonus-action attack via the reusable bonus-attack flow.
- Gating keys off `r.physical_damage_types` / `r.critical` / `w.heavy`. Tests in `test_feats.py`
  (or a new `test_general_feats.py`).

Open follow-ups remain in the phase list above (G2–G6 + deferred).
