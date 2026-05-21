#!/usr/bin/env python3
"""
Merge spell school data from spells_raw.json into spells.json

Reads the 2024 D&D 5e SRD spell data (spells_raw.json) and adds the school field
to spells.json without overwriting any existing fields.

Usage:
    python3 merge_spell_schools.py

Output:
    - Updates spells.json in-place
    - Prints summary of matched/missing spells
"""

import json
import sys
from pathlib import Path

def main():
    # Paths (relative to this script)
    script_dir = Path(__file__).parent
    spells_json_path = script_dir / "spells.json"
    spells_raw_json_path = script_dir / "spells_raw.json"

    # Load spells
    print(f"Loading {spells_json_path}...")
    with open(spells_json_path, 'r') as f:
        spells = json.load(f)
    print(f"  Loaded {len(spells)} spells")

    print(f"Loading {spells_raw_json_path}...")
    with open(spells_raw_json_path, 'r') as f:
        spells_raw = json.load(f)
    print(f"  Loaded {len(spells_raw)} raw spells")

    # Build name -> school map from raw data
    school_map = {}
    for raw_spell in spells_raw:
        name = raw_spell.get("name")
        school = raw_spell.get("school", {})
        school_key = school.get("key", "").lower()
        if name and school_key:
            school_map[name] = school_key

    print(f"Built school map: {len(school_map)} spells with schools")

    # Merge schools into spells
    matched = 0
    missing = 0
    already_has = 0
    missing_spells = []

    for spell in spells:
        spell_name = spell.get("name")

        if not spell_name:
            print(f"  Warning: spell with no name: {spell}")
            continue

        # Check if school already exists
        if "school" in spell:
            already_has += 1
            continue

        # Look up school from raw data
        if spell_name in school_map:
            spell["school"] = school_map[spell_name]
            matched += 1
        else:
            missing += 1
            missing_spells.append(spell_name)

    # Save updated spells.json
    print(f"\nSaving {spells_json_path}...")
    with open(spells_json_path, 'w') as f:
        json.dump(spells, f, indent=2)

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Matched:       {matched} spells")
    print(f"  Already have:  {already_has} spells")
    print(f"  Missing:       {missing} spells")
    print("=" * 60)

    if missing_spells:
        print("\nMissing spells (not found in spells_raw.json):")
        for name in sorted(missing_spells)[:10]:
            print(f"  - {name}")
        if len(missing_spells) > 10:
            print(f"  ... and {len(missing_spells) - 10} more")

    return 0 if missing == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
