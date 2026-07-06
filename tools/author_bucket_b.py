#!/usr/bin/env python3
"""Phase 2 Bucket B: author the multiattack recipes that need a 4th weapon slot.

Two SRD monsters carry more distinct attacks than the legacy 3-slot
[main_hand, off_hand, ranged] weapon layout can hold, so their recipe references a
weapon at index 3. This script therefore does BOTH jobs for just those records:

  1. reshapes `weapons` from the legacy {main_hand,off_hand,ranged} dict to the flat
     "Attack N" list (same convention as tools/migrate_bestiary_weapons_to_list.py:
     0=main_hand, 1=off_hand, 2=ranged, interior empties kept as {} to preserve
     later indices, trailing empties dropped);
  2. appends the missing 4th melee weapon at index 3;
  3. writes the ordered `multiattack` recipe into stats.

  Pit Fiend (na=4): Bite + 2 Devilish Claw + Fiery Mace
      slots {0: Bite, 1: Devilish Claw, 2: (necrotic ranged, unused), 3: Fiery Mace}
      recipe [[0,1],[1,2],[3,1]]
  Chimera  (na=3): Bite + Claw + Ram
      slots {0: Bite, 1: Claw, 2: (empty), 3: Ram}
      recipe [[0,1],[1,1],[3,1]]   (Fire Breath stays a separate recharge spell)

Barbed Devil and Medusa are Bucket-B candidates but are deliberately LEFT LEGACY
(no recipe): both have a ranged mode (Hurl Flame / Poison Ray) they should be free to
choose over melee, which the free-combo `num_attacks` path already handles. They are
listed in tools/verify_legacy_multiattack.py so a stray recipe on them is caught.

Additive, idempotent, guarded (asserts sum(counts)==num_attacks and every referenced
index is a non-empty weapon; writes a .bak). NOT the CSV->JSON converter.

Usage (run from repo root):
    python3 tools/author_bucket_b.py            # dry run: validate + report
    python3 tools/author_bucket_b.py --write    # apply in place (writes a .bak)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gui", "DND2024_MonsterStats.json")

_SLOT_ORDER = ("main_hand", "off_hand", "ranged")

# --- the two new 4th weapons (SRD_CC_v5.2 / 2024 Monster Manual) --------------
FIERY_MACE = {
    "name": "Fiery Mace",
    "type": "melee",
    "reach_ft": 10,
    "normal_range_ft": 80,
    "long_range_ft": 320,
    "proficient": True,
    "bonus_damage": 0,
    "physical_damage_types": [{"type": "Bludgeoning", "num_dice": 2, "die_size": 6}],
    "magic_damage_types": [{"type": "Fire", "num_dice": 6, "die_size": 6}],
    "conditions": [],
    "mastery": "None",
}

# Ram carries Topple mastery (copies the Quarterstaff) so a hit knocks the target
# Prone — the SRD Chimera Ram's inherent prone. The engine gates weapon mastery on the
# wielder's stats.weapon_mastery > 0 (see MIN_WEAPON_MASTERY below).
RAM = {
    "name": "Ram",
    "type": "melee",
    "reach_ft": 5,
    "normal_range_ft": 80,
    "long_range_ft": 320,
    "proficient": True,
    "bonus_damage": 0,
    "physical_damage_types": [{"type": "Bludgeoning", "num_dice": 2, "die_size": 6}],
    "magic_damage_types": [],
    "conditions": [],
    "mastery": "Topple",
}

# monster -> (new weapon to place at index 3, recipe [[slot,count],...])
JOBS = {
    "Pit Fiend": (FIERY_MACE, [[0, 1], [1, 2], [3, 1]]),
    "Chimera":   (RAM,        [[0, 1], [1, 1], [3, 1]]),
}

# monster -> minimum stats.weapon_mastery so a mastery-bearing weapon actually fires
# (Djinni, the other Topple monster, carries weapon_mastery=1).
MIN_WEAPON_MASTERY = {
    "Chimera": 1,
}


def _slot_is_empty(val) -> bool:
    """Mirror tools/migrate_bestiary_weapons_to_list._slot_is_empty."""
    if isinstance(val, dict):
        return (not val.get("name")) or val.get("name") == "Unarmed"
    return (not val) or val == "Unarmed"


def _dict_weapons_to_list(wdict: dict) -> list:
    out = []
    for slot in _SLOT_ORDER:
        val = wdict.get(slot, "")
        out.append({} if _slot_is_empty(val) else val)
    while out and not out[-1]:
        out.pop()
    return out


def _as_list(wfield) -> list:
    """Return the weapons in flat-list form regardless of current shape."""
    if isinstance(wfield, list):
        return list(wfield)
    if isinstance(wfield, dict):
        return _dict_weapons_to_list(wfield)
    return []


def _place_at(wlist: list, index: int, weapon: dict) -> list:
    """Ensure `weapon` sits at `index`, padding earlier slots with {} as needed.

    Idempotent: if a weapon of the same name is already at `index`, leave it."""
    while len(wlist) <= index:
        wlist.append({})
    existing = wlist[index]
    if isinstance(existing, dict) and existing.get("name") == weapon["name"]:
        return wlist  # already authored
    if not _slot_is_empty(existing):
        raise ValueError(
            f"index {index} already holds a different weapon "
            f"({existing.get('name')!r}); refusing to overwrite")
    wlist[index] = weapon
    return wlist


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=DEFAULT_JSON, help="path to DND2024_MonsterStats.json")
    ap.add_argument("--write", action="store_true", help="apply in place (writes a .bak)")
    args = ap.parse_args()

    path = os.path.abspath(args.json)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors: list[str] = []
    plans: dict[str, tuple] = {}

    for name, (weapon, recipe) in JOBS.items():
        rec = data.get(name)
        if rec is None:
            errors.append(f"{name}: not in bestiary")
            continue

        na = rec["stats"].get("num_attacks")
        total = sum(c for _, c in recipe)
        if total != na:
            errors.append(f"{name}: sum(counts)={total} != num_attacks={na}")

        # The recipe reference index for the new weapon is the highest slot used.
        target = max(slot for slot, _ in recipe)
        try:
            wlist = _place_at(_as_list(rec.get("weapons")), target, weapon)
        except ValueError as e:
            errors.append(f"{name}: {e}")
            continue

        # Every referenced slot must be a non-empty weapon.
        for slot, _ in recipe:
            if slot >= len(wlist) or _slot_is_empty(wlist[slot]):
                errors.append(f"{name}: recipe references empty slot {slot}")

        plans[name] = (wlist, recipe)

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  -", e)
        return 1

    for name, (wlist, recipe) in plans.items():
        print(f"{name}: weapons -> {[w.get('name') if isinstance(w, dict) else w for w in wlist]}")
        print(f"    recipe {recipe}  (sum={sum(c for _, c in recipe)} == num_attacks)")

    if not args.write:
        print("\n(dry run — pass --write to apply)")
        return 0

    backup = path + ".bak_bucketB"
    shutil.copy2(path, backup)
    for name, (wlist, recipe) in plans.items():
        data[name]["weapons"] = wlist
        data[name]["stats"]["multiattack"] = recipe
        need = MIN_WEAPON_MASTERY.get(name)
        if need is not None:
            cur = data[name]["stats"].get("weapon_mastery") or 0
            data[name]["stats"]["weapon_mastery"] = max(cur, need)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nWrote {len(plans)} Bucket B recipes to {path}")
    print(f"Backup saved to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
