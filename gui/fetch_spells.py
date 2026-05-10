#!/usr/bin/env python3
"""
Fetch D&D 5e spells from open5e.com API v2 and populate spells.json.

This script fetches official D&D 5e SRD spells and converts them to our game format.

Usage:
    python3 fetch_spells.py              # Fetch all official 2024 spells
    python3 fetch_spells.py --limit 50   # Fetch first 50 spells (for testing)
"""

import json
import re
import sys
import urllib.request
from typing import Optional

API_BASE = "https://api.open5e.com/v2/spells/"

def fetch_spells(limit: Optional[int] = None, official_only: bool = True) -> list:
    """Fetch spells from Open5e v2 API with pagination."""
    spells = []

    # Official D&D 5e source documents (v2 API)
    official_docs = ",".join([
        "srd-2024", "phb-2024", "dmg-2024", "xgte", "tce"
    ])

    print(f"Fetching official D&D spells from Open5e API...")

    # Start URL with document filter
    url = f"{API_BASE}?document__key__in={official_docs}&limit=100"

    while url:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "DND-Battle-Map/1.0 (Python)")

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                batch = data.get("results", [])

                spells.extend(batch)

                print(f"  Fetched {len(spells)} official spells total...", end='\r')

                # Stop if we've got enough
                if limit and len(spells) >= limit:
                    spells = spells[:limit]
                    break

                # Follow pagination or stop
                url = data.get("next")

        except Exception as e:
            print(f"\nError fetching spells: {e}")
            break

    print(f"\n✓ Downloaded {len(spells)} official spells")
    return spells

def infer_geometry(spell: dict) -> str:
    """Infer spell geometry from v2 API data."""
    shape_type = (spell.get("shape_type") or "").lower()

    if "sphere" in shape_type:
        return "Sphere"
    elif "cone" in shape_type:
        return "Cone"
    elif "line" in shape_type:
        return "Line"
    elif "cube" in shape_type or "square" in shape_type:
        return "Sphere"  # Treat cubes as spheres for grid purposes
    else:
        return "Single"

def parse_damage(spell: dict) -> tuple:
    """Extract damage info from v2 API spell data."""
    magic_damages = []
    physical_damages = []

    magic_types = {
        "acid": "Acid", "cold": "Cold", "fire": "Fire", "force": "Force",
        "lightning": "Lightning", "necrotic": "Necrotic", "poison": "Poison",
        "psychic": "Psychic", "radiant": "Radiant", "thunder": "Thunder"
    }
    physical_types = {"bludgeoning": "Bludgeoning", "piercing": "Piercing", "slashing": "Slashing"}

    # Parse damage_roll field (e.g., "2d6" or "2d6 + 1d6 for each slot level")
    damage_roll = spell.get("damage_roll", "")
    if damage_roll:
        # Extract dice notation
        match = re.search(r"(\d+)d(\d+)", damage_roll)
        if match:
            num_dice = int(match.group(1))
            die_size = int(match.group(2))

            # Infer damage type from damage_types list
            damage_types = spell.get("damage_types", [])
            if damage_types and isinstance(damage_types, list) and len(damage_types) > 0:
                dmg_type = damage_types[0].lower()
                if dmg_type in magic_types:
                    magic_damages.append({
                        "type": magic_types[dmg_type],
                        "num_dice": num_dice,
                        "die_size": die_size
                    })
                elif dmg_type in physical_types:
                    physical_damages.append({
                        "type": physical_types[dmg_type],
                        "num_dice": num_dice,
                        "die_size": die_size
                    })

    return magic_damages, physical_damages

def infer_los_requirement(spell: dict) -> bool:
    """Check if spell requires line of sight. Only true if spell explicitly mentions 'you can see'."""
    desc = (spell.get("desc", "") + " " + spell.get("higher_level", "")).lower()

    # Spells that explicitly require LOS mention "you can see" or similar
    los_patterns = [
        r"you can see",
        r"that you can see",
        r"within sight",
        r"line of sight",
    ]

    for pattern in los_patterns:
        if re.search(pattern, desc):
            return True

    # By default, spells do NOT require LOS
    return False

def infer_terrain_effect(spell: dict) -> tuple:
    """Infer terrain effect from spell description. Returns (terrain_effect_dict, terrain_color_rgb, hatch_pattern) or (None, None, None)."""
    desc = (spell.get("desc", "") + " " + spell.get("higher_level", "")).lower()
    name = spell.get("name", "").lower()

    # Check for "difficult terrain" first (all such spells mention it explicitly)
    if "difficult terrain" in desc:
        # Pick color/hatch based on spell name or keywords
        if re.search(r"grease|slippery|oil", desc + name):
            color, hatch = (220, 180, 0), "\\\\"  # Gold/yellow
        elif re.search(r"web|entangle", desc + name):
            color, hatch = (150, 75, 0), "xx"  # Dark brown
        elif re.search(r"snow|ice|sleet|frozen|blizzard", desc + name):
            color, hatch = (200, 220, 255), "||"  # Cyan/white
        elif re.search(r"thorns|spikes|caltrops", desc + name):
            color, hatch = (100, 100, 0), "--"  # Olive/dark
        elif re.search(r"fog|mist|obscur", desc + name):
            color, hatch = (180, 180, 180), ".."  # Gray
        else:
            color, hatch = (139, 90, 43), "//"  # Default brown

        return (
            {
                "type": "Difficult Terrain",
                "difficulty": "Halved",  # 2x movement cost
                "duration": 10
            },
            color,
            hatch
        )

    return None, None, None

def spell_to_dict(api_spell: dict) -> dict:
    """Convert Open5e v2 spell to our JSON format."""
    magic_dmg, phys_dmg = parse_damage(api_spell)

    # Parse range
    range_ft = 30  # Default
    range_text = api_spell.get("range_text", "").lower()
    if "self" in range_text:
        range_ft = 0
    elif "touch" in range_text:
        range_ft = 5
    else:
        # Try to extract numeric range
        range_val = api_spell.get("range")
        if isinstance(range_val, int):
            range_ft = range_val

    # Level (v2 returns as integer)
    level = api_spell.get("level", 0)
    if isinstance(level, str):
        match = re.search(r"(\d+)", level)
        level = int(match.group(1)) if match else 0
    else:
        level = int(level) if level else 0

    # Spell type
    desc = api_spell.get("desc", "").lower()
    spell_type = "Harm"
    if re.search(r"heal|restore|recovery", desc):
        spell_type = "Heal"

    # Attack type
    attack_type = "Automatic"
    if api_spell.get("attack_roll"):
        attack_type = "AttackRoll"
    elif api_spell.get("saving_throw_ability"):
        attack_type = "Save"

    # Save ability
    save_ability = "SaveDex"
    if api_spell.get("saving_throw_ability"):
        ability_map = {
            "strength": "SaveStr",
            "dexterity": "SaveDex",
            "constitution": "SaveCon",
            "intelligence": "SaveInt",
            "wisdom": "SaveWis",
            "charisma": "SaveCha"
        }
        save_key = api_spell.get("saving_throw_ability", "").lower()
        save_ability = ability_map.get(save_key, "SaveDex")

    # Upcast bonus (infer from higher_level text)
    upcast_bonus = 0
    higher_level = api_spell.get("higher_level", "").lower()
    # Match patterns like "+1d6" or "increases by 1d6" or "add 1d6"
    if re.search(r"(?:\+|increases by|add|deals an additional)\s*(\d+)d(\d+).*(?:slot level|level above|spell level)", higher_level):
        match = re.search(r"(?:\+|increases by|add|deals an additional)\s*(\d+)d(\d+)", higher_level)
        if match:
            upcast_bonus = int(match.group(1))

    # Infer terrain effect
    terrain_effect, terrain_color, hatch_pattern = infer_terrain_effect(api_spell)

    # Infer LOS requirement
    requires_los = infer_los_requirement(api_spell)

    geometry = infer_geometry(api_spell)

    # Set geometry-appropriate dimensions
    if geometry in ("Sphere", "Cone"):
        radius, width, length = 15, 0, 0
    elif geometry == "Line":
        radius, width, length = 0, 5, 30
    else:  # Single
        radius, width, length = 0, 0, 0

    result = {
        "name": api_spell.get("name", "Unknown Spell"),
        "description": api_spell.get("desc", ""),
        "type": spell_type,
        "geometry": geometry,
        "attack_type": attack_type,
        "save_ability": save_ability,
        "range": range_ft,
        "radius": radius,
        "width": width,
        "length": length,
        "duration": 1,
        "magic_damage_types": magic_dmg,
        "physical_damage_types": phys_dmg,
        "level": level,
        "upcast_dice_bonus": upcast_bonus,
        "requires_concentration": api_spell.get("concentration", False),
        "requires_los": requires_los,
        "check_los_on_center": True,  # Always true by default (D&D 5e standard)
    }

    # Add terrain effect if detected
    if terrain_effect:
        result["terrain_effect"] = terrain_effect
        result["terrain_color"] = terrain_color
        result["hatch_pattern"] = hatch_pattern

    return result

def main():
    """Main entry point."""
    limit = None

    # Parse command line args
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])
            print(f"Limiting to first {limit} spells")

    # Fetch spells
    spells = fetch_spells(limit)

    if not spells:
        print("✗ No spells fetched. Check API connectivity.")
        return

    # Convert to our format
    print("Converting to game format...")
    spell_dicts = [spell_to_dict(s) for s in spells]

    # Write processed spells to file
    output_path = "spells.json"
    with open(output_path, "w") as f:
        json.dump(spell_dicts, f, indent=2)

    print(f"✓ Saved {len(spell_dicts)} spells to {output_path}")

    # Write raw spell data to separate file
    raw_path = "spells_raw.json"
    with open(raw_path, "w") as f:
        json.dump(spells, f, indent=2)

    print(f"✓ Saved raw spell data to {raw_path}")

    # Show sample
    if spell_dicts:
        print(f"\nSample spell:")
        sample = spell_dicts[0]
        print(f"  Name: {sample['name']}")
        print(f"  Level: {sample['level']}")
        print(f"  Type: {sample['type']}")
        print(f"  Attack Type: {sample['attack_type']}")
        print(f"  Range: {sample['range']}ft")

if __name__ == "__main__":
    main()
