#!/usr/bin/env python3
"""One-shot migration: bestiary `weapons` dict -> flat "Attack N" list.

Phase 1C of MULTIATTACK_RECIPES_PLAN.md. The engine now stores an agent's weapons
as a variable-length list instead of a fixed 3-slot [main_hand, off_hand, ranged]
array, so a monster can carry a 4th/5th distinct attack that a multiattack recipe
references by index. This rewrites each hand-authored record in
gui/DND2024_MonsterStats.json from:

    "weapons": {"main_hand": {...}, "off_hand": "", "ranged": {...}}

to the equivalent flat list (main_hand=index 0, off_hand=1, ranged=2, then any
future extra attacks). Trailing empty slots are dropped; an interior empty slot is
kept as `{}` so later weapons keep their index (a recipe may reference index 2 even
if index 1 is empty). This matches helpers._weapons_to_list exactly.

The migration is:
  - purely a reformat — no weapon field is added, removed, or changed;
  - idempotent — a record already in list form is left untouched;
  - guarded — asserts the record count is unchanged and that every weapon still
    round-trips (same name + damage) before writing.

This is NOT the CSV->JSON converter (that must never be re-run). It only reshapes
the `weapons` key of the already hand-authored JSON.

Usage (run from the repo root):
    python3 tools/migrate_bestiary_weapons_to_list.py            # dry run: report only
    python3 tools/migrate_bestiary_weapons_to_list.py --write    # apply in place (writes a .bak)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gui", "DND2024_MonsterStats.json")

_SLOT_ORDER = ("main_hand", "off_hand", "ranged")


def _slot_is_empty(val) -> bool:
    """A slot is empty if it's "", None, a dict without a name, or the bare "Unarmed"
    sentinel (weapon.hpp defaults Weapon.name = "Unarmed"). "MonkUnarmed" is a real weapon."""
    if isinstance(val, dict):
        return (not val.get("name")) or val.get("name") == "Unarmed"
    return (not val) or val == "Unarmed"


def dict_weapons_to_list(wdict: dict) -> list:
    """Convert a {main_hand,off_hand,ranged} dict to a flat list.

    Empty slots become {} to hold their index; trailing empties are dropped."""
    out = []
    for slot in _SLOT_ORDER:
        val = wdict.get(slot, "")
        out.append({} if _slot_is_empty(val) else val)
    while out and not out[-1]:
        out.pop()
    return out


def _weapon_signature(w):
    """A cheap identity for round-trip verification: (name, physical rolls, magic rolls).
    Empty slots (including the bare "Unarmed" sentinel) have no signature."""
    if not isinstance(w, dict) or _slot_is_empty(w):
        return None
    phys = tuple((r.get("type"), r.get("num_dice"), r.get("die_size"))
                 for r in w.get("physical_damage_types", []))
    mag = tuple((r.get("type"), r.get("num_dice"), r.get("die_size"))
                for r in w.get("magic_damage_types", []))
    return (w.get("name"), phys, mag)


def _dict_signatures(wdict: dict) -> set:
    return {sig for slot in _SLOT_ORDER
            for sig in (_weapon_signature(wdict.get(slot)),) if sig is not None}


def _list_signatures(wlist: list) -> set:
    return {sig for w in wlist for sig in (_weapon_signature(w),) if sig is not None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=DEFAULT_JSON, help="path to DND2024_MonsterStats.json")
    ap.add_argument("--write", action="store_true", help="apply changes in place (writes a .bak)")
    args = ap.parse_args()

    path = os.path.abspath(args.json)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        print(f"ERROR: expected a dict of records, got {type(data).__name__}", file=sys.stderr)
        return 1

    n_records = len(data)
    converted = 0
    already_list = 0
    changed_names = []

    for name, rec in data.items():
        if not isinstance(rec, dict):
            continue
        wfield = rec.get("weapons")
        if isinstance(wfield, list):
            already_list += 1
            continue
        if not isinstance(wfield, dict):
            continue

        new_list = dict_weapons_to_list(wfield)

        # Round-trip guard: every non-empty weapon must survive unchanged.
        before = _dict_signatures(wfield)
        after = _list_signatures(new_list)
        assert before == after, (
            f"{name}: weapon round-trip mismatch\n  before={before}\n  after={after}")

        rec["weapons"] = new_list
        converted += 1
        changed_names.append(name)

    assert len(data) == n_records, "record count changed during migration!"

    print(f"Records:            {n_records}")
    print(f"Already list form:  {already_list}")
    print(f"Converted:          {converted}")
    if changed_names[:10]:
        print("  e.g. " + ", ".join(changed_names[:10]) + (" ..." if len(changed_names) > 10 else ""))

    if not args.write:
        print("\n(dry run — pass --write to apply)")
        return 0

    if converted == 0:
        print("\nNothing to write.")
        return 0

    backup = path + ".bak"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nWrote {converted} converted records to {path}")
    print(f"Backup saved to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
