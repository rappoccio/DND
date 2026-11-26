# College of Whispers (Bard subclass) — Plan

Drafted 2026-11-26. Source: Xanathar's College of Whispers text supplied by the user.

## Scope (user decision 2026-11-26)

**Psychic Blades only.** Words of Terror (L3), Mantle of Whispers (L6) and Shadow Lore (L14)
are mostly out of combat and are not modelled; recorded in `memory/known_limitations.md`.

## Decisions

- **D1 Enum.** `WhispersPath` appended to `BardCollege` (after `ValorPath`, so stored ints stay
  stable). Python value `"Whispers"`, in the stats-dialog college picker and the D&D Beyond
  importer ("College of Whispers" matches through the `collegeof` prefix strip).
- **D2 Psychic Blades (L3).** After a weapon hit on the bard's own turn (not an Opportunity
  Attack; Unarmed Strikes excluded, as they are not weapon attacks in 2024 rules), the GUI offers:
  spend 1 Bardic Inspiration use → extra Psychic 2d6 / 3d6 @ L5 / 5d6 @ L10 / 8d6 @ L15. Dice
  double on a crit. Once per turn. Deferred `psychic_blades_available` flag + prompt, mirroring
  Psionic Strike (including the weapon-Mastery chain).
- **D3 Scope.** PC only; no NPC policy. Not added to party generation.

## Steps

- **CW1 — Psychic Blades.** Enum, flags, `applyPsychicBlades`, bindings, GUI prompt, importer,
  tests in `tests/test_bard.py`, docs. **Done 2026-11-26.**
- **CW2 — Live check** in `./run.sh` (user-driven).
