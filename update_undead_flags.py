#!/usr/bin/env python3
import json

# Load the JSON file
with open('gui/DND2024_MonsterStats.json', 'r') as f:
    data = json.load(f)

# Track stats
total_entries = 0
undead_updated = 0

# Process each monster entry
for monster_name, monster_data in data.items():
    total_entries += 1

    # Check if meta exists and has a type field
    if isinstance(monster_data, dict) and 'meta' in monster_data:
        meta = monster_data['meta']
        if isinstance(meta, dict) and 'type' in meta:
            monster_type = meta['type']
            # Check if it's an Undead type
            if 'Undead' in monster_type:
                monster_data['is_undead'] = True
                undead_updated += 1
                print(f"✓ {monster_name}: {monster_type}")

# Save the updated JSON file
with open('gui/DND2024_MonsterStats.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"\nDone! Updated {undead_updated} undead creatures out of {total_entries} total entries.")
