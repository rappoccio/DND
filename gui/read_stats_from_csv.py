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
import sys

# tools/ lives at the repo root (sibling of gui/); make the parser importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from tools.monster_parser import parse_monster


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
    """Convert {name: raw_row_dict} into {name: engine-ready record}."""
    return {name: parse_monster(name, raw).to_record()
            for name, raw in raw_by_name.items()}


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
