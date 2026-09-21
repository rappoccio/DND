# Sorcerer Subclass — SONNET Handoff (safe additions)

> **STATUS (2026-06-23):** Tasks 1–6 below are DONE, built, green, and **committed**.
> The [OPUS] follow-on **Wild Magic Surge trigger + Tides of Chaos** (listed under
> "OUT OF SCOPE" at the bottom) is now ALSO done (built + green): `maybeWildMagicSurge`
> (nat-20 / Tides-forced surge after a slot cast) + `activateTidesOfChaos` + the
> "Tides of Chaos" Resource, with GUI buttons and the trigger wired into the
> `_finish_cast`/teleport/summon paths. See memory `sorcerer_plan.md` (Phase 4) and
> `known_limitations.md`.
> **Phase 5 [OPUS] (2026-06-23) — DONE, built clean + tests green:** Clockwork Soul subclass: L3
> Clockwork Spells (data) + **Restore Balance** (`OnD20Seen` reaction that cancels *advantage* by
> reverting `r.d20` to the new `r.d20_primary`; PB uses / long rest, no SP, a Resource — no round-trip).
> See memory `sorcerer_plan.md` (Phase 5) and `known_limitations.md` (Clockwork Soul).
> **Phase 6 [OPUS] — IMPLEMENTED 2026-06-23 (edits proposed; USER runs build + tests):** Clockwork
> **L14 Trance of Order** — defender-side advantage-negation (cloned the Rogue Elusive block) +
> `Stats::applyTranceFloor` own-D20 floor-to-10 helper applied at the attack roll + 4 save sites
> (rollSpellSave / condition save / save-for-half / concentration save; auto-fails NOT floored) +
> `activateTranceOfOrder` Bonus-Action activation (free 1/long rest "Trance of Order" Resource, else
> 5 SP), one new round-tripped `trance_of_order_turns` field + GUI button + 6 new tests. See memory
> `sorcerer_plan.md` (Phase 6 — IMPLEMENTED section) for the file-by-file change list.
> **Other [OPUS] candidates:** Aberrant Psionic Sorcery (SP-cast); Empowered/Subtle Metamagic.

Scope: the low-risk, high-reuse subclass features that follow an existing proven pattern.
**Everything here is [SONNET].** Anything that touches the spell/SP economy, the reaction
system, or the surge restructure is **[OPUS]** and explicitly excluded below — STOP at those.

## Ground rules (read first)
- **Do not run builds, tests, git, or any Bash that mutates state.** The user runs all builds.
  Propose edits only. (See gui/CLAUDE.md.)
- **Fix root cause in C++.** Don't add Python-side workarounds. (memory: fix-root-cause)
- **Every new `rpg.Stats` field must round-trip** or it resets on save/reload. That means THREE places:
  1. C++ field on `Stats` (agent.hpp) + bound in `rpg_bindings.cpp`.
  2. Load: `dict_to_stats` in `gui/agent_loader.py`.
  3. Save: the save dict block in `gui/main.py` (~line 8096, where `elemental_adept_types` is written).
  (memory: stats-serializer-roundtrip)
- Subclass choice itself already round-trips (`agent_sorcerer_subclass`); you're only adding feature state.
- Each task lists the **precedent to clone** — match that code's idiom, don't invent a new shape.

---

## TASK 1 — Draconic L3: Draconic Resilience HP bonus  [SONNET]
**Rule:** max HP +3 at L3, +1 per Sorcerer level after 3rd (i.e. `3 + (char_level - 3)` = `char_level`
extra HP at L3+, capped: it's literally `char_level` since 3+(L-3)=L… but RAW phrasing is "+3 then +1/level
beyond 3rd". Compute as `hp_bonus = 3 + max(0, char_level - 3)`.)

**Where:** the AC half already lives at `combat_core.cpp:358`. The HP max is `Stats::hp_max`, and the
usable ceiling is `effectiveMaxHp()` (agent.hpp:175 = `max(0, hp_max - available_hit_points)`).

**Approach:** do NOT mutate `hp_max` repeatedly (it would compound on every recompute). Cleanest:
add the bonus once where the agent's HP is finalized at configuration/level-set time. Find where
class features are granted at config (combat.cpp around line 232 has the Draconic comment block:
"Draconic Elemental Affinity + HP bonus" deferred). Grant the HP bump there, alongside the other
one-time class grants in that function, guarded by `subclass==DraconicPath && char_level>=3` and an
idempotency guard so re-applying config doesn't stack (e.g. only add the delta vs the last-applied
level, or track via a `draconic_hp_applied` bool field — round-trip it).

**Precedent:** the one-time grant block in combat.cpp near :232 (Draconic) and how other classes add
fixed bonuses at config time. **Test:** L3 Draconic sorcerer has hp_max = base + 3; L7 = base + 7.

---

## TASK 2 — Draconic L6: Elemental Affinity (damage half)  [SONNET]
**Rule:** when you cast a spell that deals your chosen draconic damage type, add your CHA mod to one
damage roll of that spell (once per turn).

**New state (round-trip all):**
- `int draconic_affinity_type{-1}` on Stats — a `MagicDamage_t` index (Acid/Cold/Fire/Lightning/Poison),
  chosen via `ElementPickerDialog` exactly like `elemental_adept_types` (dialogs.py:872, used in
  main.py `_on_stats_ok`). Only offer the 5 draconic types.
- `bool draconic_affinity_used_this_turn{false}` — reset in `beginTurn`.

**Where to add the damage:** the spell magic-damage application path. `combat_spells.cpp` has the
spell damage sites (see `rollSpellTypeDamage` / the 5 magic-damage sites referenced in
known_limitations Architecture). Add CHA mod to the FIRST damage instance whose type ==
`draconic_affinity_type`, gated on `subclass==DraconicPath && char_level>=6 && !used_this_turn`, then
set the flag. **Precedent:** how Elemental Adept hooks the spell damage path (`elemental_adept_types`,
combat_spells.cpp) — same gate location, different effect (add flat CHA vs treat-1-as-2).

**DEFER (mark [OPUS] in known_limitations, do not build):** the "spend 1 SP for resistance to that
type for 1 hour" half — it touches the SP economy.

---

## TASK 3 — Draconic L14: Dragon Wings (flight)  [SONNET]
**Rule:** gain a fly speed equal to your walking speed (no concentration), toggleable.

**Approach:** this is a flat fly-speed grant. The field is `Stats::speed_fly`. Precedent:
Zealot Rage of the Gods sets `stats.speed_fly = std::max(stats.speed_fly, stats.speed_walk)`
(combat_resources.cpp:1133), and Wild Heart Falcon flight grants flight similarly. Add a
`activate_dragon_wings` engine method (bound in rpg_bindings.cpp) + a GUI button (mirror the
Falcon/Power-of-the-Wilds button wiring in main.py). Gate on `subclass==DraconicPath && char_level>=14`.
Since it's "no concentration, until you dismiss it," a simple persistent fly-speed grant is fine; if you
add a duration/flag field, round-trip it.

**Precedent:** combat_resources.cpp:1133 (speed_fly grant) + the Wild Heart flight GUI button.

---

## TASK 4 — Aberrant L3: Psionic Spells (always-prepared list)  [SONNET]
**Rule:** fixed list of always-prepared spells (Arms of Hadar, Dissonant Whispers, Mind Sliver, etc.).

**Approach:** data + existing plumbing only. The NPC/innate spell-restore path already grants a named
spell list onto an agent: `spell_indices` + `init_npc_spell_groups` (main.py:1283–1309,
`rpg_bindings.cpp:3047`). Grant the Aberrant fixed list to a L3+ AberrantPath sorcerer through that
same mechanism at config time. Spells must exist in `spells.json` (the engine reads JSON —
`spellFromJson`); add any missing ones as data. **No engine logic** beyond list assignment.

**Precedent:** main.py `_grant_npc_spells`-style path (main.py:1283) and the Ranger/Cleric always-prepared
list grants. **DEFER:** Telepathic Speech = out-of-combat flavor → known_limitations.

---

## TASK 5 — Aberrant L6: Psychic Defenses  [SONNET]
**Rule:** resistance to Psychic damage; advantage on saves vs Charmed and Frightened.

**Two independent, both small:**
1. **Psychic resistance:** set
   `stats.magic_damage_multipliers[(size_t)MagicDamage_t::Psychic] = 0.5f` at config time for
   AberrantPath L6+. **Precedent:** combat_resources.cpp:1136 (exact line that sets Psychic to 0.5).
2. **Save advantage vs Charmed/Frightened:** in the spell-save path, set `target_adv = true` when the
   spell applies Charmed/Frightened and target is AberrantPath L6+. **Precedent:** Fey Wanderer
   Beguiling Twist, combat_spells.cpp:288–297 — copy that block verbatim, swap the class/subclass gate.
   (Note there's a second save site at combat_spells.cpp:1161 — check whether Beguiling Twist is
   handled at both; mirror wherever it is.)

**DEFER (mark [OPUS]):** Psionic Sorcery (cast psionic spells by spending SP) — SP economy.

---

## TASK 6 — Wild Magic GUI surface (no new engine logic)  [SONNET]
The engine already has Bend Luck (`sorcerer_bend_luck`, combat_attack.cpp:1189/1266) and all surge
window-band duration fields (agent.hpp:504–509). Just expose them:
1. **Bend Luck button:** a turn-action/reaction button that calls `sorcerer_bend_luck` (spend 1 SP,
   ±1d4). Mirror an existing SP-spend button. Gate on `subclass==WildMagicPath && char_level>=6`.
2. **Window-band affordances:** `wild_magic_extra_action` (band 8 → offer an extra action),
   `wild_magic_bonus_cast_turns` (band 6 → allow action-cast as bonus), `wild_magic_teleport_bonus_turns`
   (band 10 → 20-ft teleport as bonus). These are GUI-enforced; the fields already tick in beginTurn.

**DEFER (all [OPUS]):** the surge TRIGGER (roll after a slot cast), Tides of Chaos, Controlled Chaos
(L14), Tamed Surge (L18) — cast-economy / surge-roll restructure.

---

## Explicitly OUT OF SCOPE for this handoff (do NOT start — [OPUS])
- Tides of Chaos (recharge-on-cast + auto-surge) and the Wild Magic surge trigger.
- Draconic Elemental Affinity resistance-for-SP half; Aberrant Psionic Sorcery.
- Clockwork subclass entirely (L3 Restore Balance needs the reaction/OnD20Seen interrupt).
- Aberrant L14 Revelation in Flesh / L18 Warping Implosion (compose movement + AoE teleport).
- Empowered/Subtle Metamagic.

## Done-criteria
- New Stats fields bound + round-trip verified in agent_loader.py AND main.py save block.
- Tasks 1–5 covered by new cases in `gui/test_sorcerer.py` (registered in run_all_tests.py).
- Build + tests are the USER's to run — leave them a summary of what to verify.
