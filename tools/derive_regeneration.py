#!/usr/bin/env python3
"""One-shot tool: populate Regeneration fields on bestiary records.

This is *tooling*, not a runtime dependency. The combat engine reads
``regeneration_amount`` / ``regen_interrupt_damage_types`` straight off each
agent's Stats; this script just fills those into DND2024_MonsterStats.json so
you don't have to hand-edit every regenerating monster.

Why a curated table instead of parsing the data?  The bestiary only stores trait
*names* ("Regeneration"), not the rule text, so the HP amount and the damage
types that switch regen off (Troll = acid/fire, Vampire = radiant, …) aren't in
the file. They live in REGEN_TABLE below — edit it as you learn the right
numbers; re-running is idempotent.

Usage:
    python3 tools/derive_regeneration.py            # dry run: print what would change
    python3 tools/derive_regeneration.py --write    # apply changes in place
    python3 tools/derive_regeneration.py --write --force   # overwrite existing values too

Run it from the repo root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# MagicDamage_t indices (must match gui/damage.hpp).
ACID, COLD, FIRE, FORCE, LIGHTNING, NECROTIC, POISON, PSYCHIC, RADIANT, THUNDER = range(10)
_NAMES = ["Acid", "Cold", "Fire", "Force", "Lightning",
          "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"]

DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gui", "DND2024_MonsterStats.json")

# Curated regeneration values, keyed by exact creature name.
#   name -> (hp_per_turn, [interrupting MagicDamage_t indices])
# An empty interrupt list means nothing shuts the regeneration off.
REGEN_TABLE: dict[str, tuple[int, list[int]]] = {
    "Troll":            (15, [ACID, FIRE]),
    "Troll Limb":       (15, [ACID, FIRE]),
    "Beast of Malar":   (20, [RADIANT]),
    "Demodragon":       (10, []),   # nothing disables its regen
    "Demogorgon Spawn": (5,  []),   # nothing disables its regen
    "Revenant":         (10, [FIRE, RADIANT]),
    "Oni":              (10, []),
    "Shield Guardian":  (10, []),
    "Blue Slaad":       (10, []),
    "Death Slaad":      (10, []),
    "Gray Slaad":       (10, []),
    "Green Slaad":      (10, []),
    "Red Slaad":        (10, []),
}

# NOTE: 2024 vampires do NOT passively regenerate. The 2014 "Regeneration: regains 20
# HP/turn unless in sunlight/running water" trait was cut in the 2024 redesign — a 2024
# vampire heals only via its Bite's Life Drain (modelled separately by the reduceHPMax
# bite rider + available_hit_points; see the vampire_support memory). So is_vampire is
# intentionally NOT a trigger here; only the explicit "Regeneration" trait is.

# Used for a "Regeneration" trait whose name isn't in REGEN_TABLE. Conservative: heal,
# no interrupt — but every fallback is reported so you can add a real entry.
FALLBACK: tuple[int, list[int]] = (10, [])


def _types_str(types: list[int]) -> str:
    return "[" + ", ".join(_NAMES[t] for t in types) + "]" if types else "[none]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=DEFAULT_JSON, help="bestiary JSON (default: gui/DND2024_MonsterStats.json)")
    ap.add_argument("--write", action="store_true", help="apply changes in place (default: dry run)")
    ap.add_argument("--force", action="store_true", help="overwrite records that already have regeneration_amount set")
    args = ap.parse_args()

    path = os.path.abspath(args.path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    changed = 0
    fallbacks: list[str] = []
    skipped: list[str] = []

    for name, rec in data.items():
        meta = rec.get("meta", {})
        stats = rec.setdefault("stats", {})
        has_trait = "Regeneration" in meta.get("traits", [])
        if not has_trait:
            continue

        if name in REGEN_TABLE:
            amount, types = REGEN_TABLE[name]
        else:
            amount, types = FALLBACK
            fallbacks.append(name)

        already = int(stats.get("regeneration_amount", 0))
        if already and not args.force:
            skipped.append(name)
            continue

        stats["regeneration_amount"] = amount
        stats["regen_interrupt_damage_types"] = types
        changed += 1
        print(f"  {name:30}  {amount:>3} HP/turn  off-by {_types_str(types)}"
              + ("   [FALLBACK — review]" if name in fallbacks else ""))

    print(f"\n{changed} record(s) would change"
          f"{' (already set, kept)' if skipped else ''}.")
    if skipped:
        print(f"  kept {len(skipped)} already-set (use --force to overwrite): {', '.join(skipped)}")
    if fallbacks:
        print(f"  WARNING: {len(fallbacks)} regenerator(s) used FALLBACK values — "
              f"add real entries to REGEN_TABLE: {', '.join(fallbacks)}")

    if not args.write:
        print("\nDry run. Re-run with --write to apply.")
        return 0

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
