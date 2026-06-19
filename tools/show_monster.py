#!/usr/bin/env python3
"""Read a monster-stats JSON file and pretty-print a single entry.

Usage:
    python tools/show_monster.py [entry] [path]

    entry   Name of the entry to print (default: first entry).
            Matched case-insensitively; partial matches are accepted
            when unambiguous.
    path    JSON file to read (default: gui/DND2024_MonsterStats.json).

With no entry given, lists all available entry names instead.
"""
import json
import sys


def load(path):
    with open(path) as f:
        return json.load(f)


def find_key(data, query):
    """Return the dict key matching query (exact, then case-insensitive,
    then unique partial). Raises KeyError / ValueError otherwise."""
    if query in data:
        return query
    lowered = {k.lower(): k for k in data}
    if query.lower() in lowered:
        return lowered[query.lower()]
    matches = [k for k in data if query.lower() in k.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise KeyError(query)
    raise ValueError(f"'{query}' is ambiguous: {matches}")


def main(argv):
    query = argv[0] if len(argv) > 0 else None
    path = argv[1] if len(argv) > 1 else "gui/DND2024_MonsterStats.json"

    data = load(path)

    if query is None:
        print(f"{len(data)} entries in {path}:")
        for name in data:
            print(f"  {name}")
        return 0

    try:
        key = find_key(data, query)
    except KeyError:
        print(f"No entry matching '{query}' in {path}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"=== {key} ===")
    print(json.dumps(data[key], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
