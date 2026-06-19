#!/usr/bin/env python3
"""Augment the engine-ready bestiary with NPC innate spellcasting.

For every record in gui/DND2024_MonsterStats.json, this looks up the matching
row in gui/DND2024_MonsterStats.csv, parses the innate-spell columns (At Will /
3-Day / 2-Day / 1-Day), resolves each name against gui/spells.json, and writes
`spell_indices` + `npc_spell_groups` onto the record (overwriting any that were
there). All other record fields are left untouched, so this is safe to re-run
and does not disturb the hand-tuned stats/weapons.

The resolution logic lives in gui/read_stats_from_csv.py (attach_npc_spells),
which also runs during a full CSV->JSON regeneration, so the two paths agree.

Usage:  python3 tools/add_npc_spells.py            # in-place augment
        python3 tools/add_npc_spells.py --dry-run  # report only, no write
"""
import json
import os
import sys

_GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
sys.path.insert(0, _GUI)

from read_stats_from_csv import (  # noqa: E402
    read_stats_from_csv, attach_npc_spells, _load_spell_catalog,
)

JSON_PATH = os.path.join(_GUI, "DND2024_MonsterStats.json")
CSV_PATH = os.path.join(_GUI, "DND2024_MonsterStats.csv")


def main(dry_run=False):
    with open(JSON_PATH, encoding="utf-8") as f:
        records = json.load(f)
    raw_by_name = read_stats_from_csv(CSV_PATH)
    catalog = _load_spell_catalog()

    unresolved = set()
    missing_rows = []
    casters = 0
    total_spells = 0
    for name, record in records.items():
        raw = raw_by_name.get(name)
        if raw is None:
            missing_rows.append(name)
            record.pop("spell_indices", None)
            record.pop("npc_spell_groups", None)
            continue
        attach_npc_spells(record, raw, catalog, unresolved)
        if record.get("spell_indices"):
            casters += 1
            total_spells += len(record["spell_indices"])

    print(f"Records: {len(records)}   casters: {casters}   "
          f"spells attached: {total_spells}")
    if missing_rows:
        print(f"\n{len(missing_rows)} record(s) had no CSV row (spells cleared):")
        for n in missing_rows:
            print(f"   {n}")
    if unresolved:
        print(f"\n{len(unresolved)} spell token(s) not in catalog (skipped):")
        for tok in sorted(unresolved):
            print(f"   {tok}")

    if dry_run:
        print("\n[dry-run] no file written.")
        return
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {JSON_PATH}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
