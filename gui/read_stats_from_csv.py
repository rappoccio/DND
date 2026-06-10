"""Monster stat-block loading + format conversion.

The bestiary on disk (DND2024_MonsterStats.json) is stored in the **engine-ready
record format**: each entry is `Monster.to_record()` from tools/monster_parser
— a `{name, size, stats, weapons, meta}` block where `stats` already matches
agent_loader.dict_to_stats and `weapons` matches helpers._dict_to_weapon. The
GUI loads it directly to auto-populate NPCs (no per-placement conversion).

`save_stats_as_json` regenerates that JSON from the raw spreadsheet export
(CSV, or an older raw JSON) by running every row through the parser. Run this
module directly to (re)generate the bestiary.
"""
import csv
import json
import os
import re
import sys

# tools/ lives at the repo root (sibling of gui/); make the parser importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from tools.monster_parser import parse_monster


# ── NPC innate spellcasting ────────────────────────────────────────────────
# Monster stat blocks list innate spells in four frequency columns (At Will,
# 3/Day, 2/Day, 1/Day). We resolve each name against the engine spell catalog
# (spells.json) and emit the same shape the GUI/saved-agent format already uses:
#   spell_indices    — canonical catalog names the NPC knows
#   npc_spell_groups — {uses/day: [names]} consumed by init_npc_spell_groups
# Cantrips (level 0) are always castable, so they stay out of the groups; an
# at-will *leveled* spell needs a positive uses_max to be castable by an NPC, so
# it is parked in a large-N group (AT_WILL_USES) standing in for "unlimited".
AT_WILL_USES = 99

# Source-data spelling fixes / 2024-name aliases: misspelled or variant names in
# the CSV mapped to their canonical spells.json name (see memory: monster data is
# unreliable). Keyed by the cleaned, lower-cased CSV token.
_SPELL_ALIASES = {
    "arcance lock": "Arcane Lock",
    "counter spell": "Counterspell",
    "detect thouhgts": "Detect Thoughts",
    "disintergrate": "Disintegrate",
    "lighting bolt": "Lightning Bolt",
    "mage armour": "Mage Armor",
    "markness": "Darkness",
    "melf's acid arrow": "Acid Arrow",
    "planeshift": "Plane Shift",
    "tasha's hideous laughter": "Hideous Laughter",
    "invincibility": "Invisibility",
    "major image synaptic static": "Major Image",
    "counterspell or shield": "Counterspell",
    "lesser": "Lesser Restoration",
}

_SPELL_COLUMNS = (("At Will", AT_WILL_USES), ("3/Day", 3), ("2/Day", 2), ("1/Day", 1))

_SPELL_CATALOG = None  # {lower name: (canonical name, level)} — lazily loaded


def _load_spell_catalog():
    """Load spells.json (sibling file) into {lower name: (canonical, level)}."""
    global _SPELL_CATALOG
    if _SPELL_CATALOG is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spells.json")
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
        _SPELL_CATALOG = {s["name"].lower(): (s["name"], int(s.get("level", 0)))
                          for s in catalog}
    return _SPELL_CATALOG


def _resolve_spell(token, catalog):
    """Resolve one raw CSV spell token to (canonical_name, level), or None.

    Strips frequency/level annotations like '(3rd level)' / '(level 2)', then
    matches against the catalog directly or via the alias table."""
    name = re.sub(r"\(.*?\)", "", token).strip()
    if not name:
        return None
    key = name.lower()
    if key in catalog:
        return catalog[key]
    alias = _SPELL_ALIASES.get(key)
    if alias and alias.lower() in catalog:
        return catalog[alias.lower()]
    return None


def npc_spells_from_raw(raw_row, catalog=None, unresolved=None):
    """Parse a raw CSV row's innate-spell columns into (spell_indices, groups).

    Returns ([], {}) for non-casters. `unresolved`, if given, is a set that
    collects CSV tokens that didn't match the catalog (for reporting)."""
    catalog = catalog or _load_spell_catalog()
    spell_indices, groups, seen = [], {}, set()
    for column, uses in _SPELL_COLUMNS:
        for token in (raw_row.get(column) or "").split(","):
            token = token.strip()
            if not token:
                continue
            hit = _resolve_spell(token, catalog)
            if hit is None:
                if unresolved is not None:
                    unresolved.add(token)
                continue
            name, level = hit
            if name in seen:
                continue            # first (highest-frequency) listing wins
            seen.add(name)
            spell_indices.append(name)
            # Cantrips are always castable; only leveled spells need a use budget.
            if level > 0:
                groups.setdefault(str(uses), []).append(name)
    return spell_indices, groups


def attach_npc_spells(record, raw_row, catalog=None, unresolved=None):
    """Add spell_indices / npc_spell_groups to a record in place (when the row
    has innate spells). Overwrites any pre-existing spell keys on the record."""
    indices, groups = npc_spells_from_raw(raw_row, catalog, unresolved)
    record.pop("spell_indices", None)
    record.pop("npc_spell_groups", None)
    if indices:
        record["spell_indices"] = indices
    if groups:
        record["npc_spell_groups"] = groups
    return record


def read_stats_from_csv(filepath):
    """Read the raw spreadsheet export into {name: raw_row_dict}."""
    data = {}
    with open(filepath, mode='r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            data[row['Name']] = row
    return data


def _is_record_format(data):
    """True if `data` is already in the engine-ready record format."""
    if not data:
        return False
    sample = next(iter(data.values()))
    return isinstance(sample, dict) and "stats" in sample and "meta" in sample


def records_from_raw(raw_by_name):
    """Convert {name: raw_row_dict} into {name: engine-ready record}.

    Innate spells (the At Will / N-Day columns) are resolved against the spell
    catalog and attached as spell_indices / npc_spell_groups."""
    catalog = _load_spell_catalog()
    records = {}
    for name, raw in raw_by_name.items():
        record = parse_monster(name, raw).to_record()
        attach_npc_spells(record, raw, catalog)
        records[name] = record
    return records


def save_stats_as_json(source_filepath, json_filepath=None):
    """Regenerate the engine-ready bestiary JSON from a raw CSV or raw JSON.

    Returns the JSON filepath written."""
    if json_filepath is None:
        json_filepath = os.path.splitext(source_filepath)[0] + '.json'

    if source_filepath.lower().endswith('.json'):
        with open(source_filepath, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    else:
        raw = read_stats_from_csv(source_filepath)

    records = records_from_raw(raw)
    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    return json_filepath


def load_stats_from_json(json_filepath):
    """Load the bestiary. Always returns the engine-ready record format,
    transparently upgrading a legacy raw-spreadsheet JSON if encountered."""
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if _is_record_format(data):
        return data
    return records_from_raw(data)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: %s <stats.csv | stats.json> [out.json]" % sys.argv[0])
    else:
        out = save_stats_as_json(sys.argv[1],
                                 sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"Wrote engine-ready bestiary to {out}")
