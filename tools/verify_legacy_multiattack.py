#!/usr/bin/env python3
"""Phase 2 Bucket C: guard the free-combo monsters that stay LEGACY (no recipe).

Bucket C is implemented by ABSENCE — a bestiary record with no `multiattack` key
falls through to the legacy `num_attacks` path, which is exactly what these monsters
want: free-combo ("X or Y in any combination"), same-weapon xN, ranged-mode choice,
or "replace one attack with Spellcasting/Breath". Authoring a fixed recipe on them
would wrongly pin their attack pattern.

There is therefore no data to write for Bucket C. This script instead LOCKS IN that
intent: it asserts every named legacy monster is present and carries NO `multiattack`
recipe, so a future authoring pass can't silently regress one into a fixed split.

Included beyond the Bucket C roster in MULTIATTACK_RECIPES_PLAN.md:
  - all Dragons (matched by name), which are all replace-one legacy;
  - Barbed Devil and Medusa (Bucket-B candidates deliberately left legacy: both have
    a ranged mode the free-combo path should be free to choose over melee);
  - Roper, whose multiattack is handled by its bespoke Reel rider, not a recipe.

Usage (run from repo root):
    python3 tools/verify_legacy_multiattack.py
Exit 0 if all present legacy monsters are recipe-free; 1 on any stray recipe.
Missing names are reported as warnings (roster drift) but do not fail the run.
"""
from __future__ import annotations

import json
import os
import sys

DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gui", "DND2024_MonsterStats.json")

# Explicit Bucket C names (resolved to the exact bestiary keys):
#   "Veteran" -> "Warrior Veteran"; "Centaur" -> Centaur Trooper/Warden.
LEGACY_NAMES = [
    # true Giants (NOT "Giant <beast>" — Giant Crocodile / Giant Scorpion are Bucket A)
    "Cloud Giant", "Fire Giant", "Frost Giant", "Hill Giant", "Stone Giant",
    "Storm Giant", "Lorwyn Giant", "Shadowmoor Giant",
    # humanoid stat-block casters / captains / free-combo martials
    "Assassin", "Bandit Captain", "Djinni", "Efreeti", "Lich", "Mage", "Archmage",
    "Manticore", "Merrow", "Priest", "Scout", "Spirit Naga", "Wight",
    "Ape", "Ghoul", "Roc", "Solar", "Treant", "Warrior Veteran", "Iron Golem",
    "Gladiator", "Pirate", "Pirate Captain", "Salamander", "Oni", "Mummy Lord",
    "Dryad", "Guard Captain", "Hobgoblin Captain", "Horned Devil", "Ice Devil",
    "Centaur Trooper", "Centaur Warden", "Drider", "Earth Elemental", "Tough Boss",
    # all Weres (replace-one / free-combo)
    "Werewolf", "Wereboar", "Wererat", "Weretiger", "Werebear",
    # Bucket-B candidates kept legacy (ranged-mode choice)
    "Barbed Devil", "Medusa",
    # bespoke handling, not a recipe
    "Roper",
]


def main() -> int:
    path = os.path.abspath(DEFAULT_JSON)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # All Dragons are legacy replace-one; match by name so wyrmlings/adults/ancients
    # are all covered without listing 40 keys.
    names = set(LEGACY_NAMES)
    names.update(k for k in data if "dragon" in k.lower())

    missing: list[str] = []
    stray: list[str] = []
    checked = 0

    for name in sorted(names):
        rec = data.get(name)
        if rec is None:
            if name in LEGACY_NAMES:            # only the explicit roster warns on absence
                missing.append(name)
            continue
        checked += 1
        if rec.get("stats", {}).get("multiattack"):
            stray.append(f"{name}: has recipe {rec['stats']['multiattack']} (should be legacy)")

    if missing:
        print("WARN — roster names not found in bestiary (drift, resolve manually):")
        for m in missing:
            print("  -", m)

    if stray:
        print("\nFAILED — legacy monsters carry a multiattack recipe:")
        for s in stray:
            print("  -", s)
        return 1

    print(f"OK — {checked} legacy monsters verified recipe-free "
          f"(Bucket C stays num_attacks free-combo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
