#!/usr/bin/env python3
"""Move a campaign's runs to play-state-only PCs (plans/NEW_DUNGEON_PLAN.md D3, step 3).

The app already reads an old run's full PC records as play state over the sheet, and
writes them back split on the next save, so this tool changes nothing the app would not.
What it adds is a look before that happens:

  * for every sheet-backed PC in a run, the sheet keys on which the run's record differs
    from ``pcs/<slug>.json``. Those values are the run's and are dropped: the sheet wins.
    Pass ``--prefer-run NAME@dungeon`` to write that PC's sheet from that dungeon's run
    first (its first run that has it), and that dungeon is then not reported for it.
  * every dungeon whose runs hold some, but not all, of the campaign's sheets. Its
    ``dungeon.json`` gets a ``"party"`` of the PCs it has, so opening it doesn't bring in
    the others. A dungeon with no PCs yet is left to the campaign's party.

Without ``--apply`` it only reports. With it, each changed ``run.json`` and each sheet
written from a run is first copied beside itself with a ``.pre-pc-sheets`` suffix (no
``.json`` ending, so ``pcs/`` doesn't list it as a sheet). Saves and releases are left alone; they convert when
restored and saved.

    python3 tools/migrate_pc_play_state.py "encounters/Curse of Strahd"
    python3 tools/migrate_pc_play_state.py encounters/Sithicus --apply
    python3 tools/migrate_pc_play_state.py "encounters/Curse of Strahd" \
        --prefer-run "Keef Girgo@castle-ravenloft" --apply

Quit the game first: it saves on quit.
"""

import argparse
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import pc_sheets as ps  # noqa: E402
import run_state as rs  # noqa: E402
import save_layout as sl  # noqa: E402
from atomic_io import atomic_write_json  # noqa: E402
from dungeon import Dungeon  # noqa: E402

BACKUP = ".pre-pc-sheets"


def sheet_diff(rec: dict, sheet: dict) -> list[str]:
    """Sheet keys (``stats.<k>`` for stats) on which ``rec`` differs from ``sheet``. A key
    the sheet lacks counts only when the record's value is set (a sheet written before
    the engine saved that key reads it as its default)."""
    out = []
    for k, v in rec.items():
        if k in ps.PLAY_KEYS or k in ps.PLACEMENT_KEYS or k in ps.ID_KEYS:
            continue
        if k == "stats":
            st = sheet.get("stats") or {}
            out += [f"stats.{s}" for s, sv in v.items()
                    if s not in ps.PLAY_STATS and _differs(st, s, sv)]
        elif _differs(sheet, k, v):
            out.append(k)
    return out


def _differs(have: dict, k, v) -> bool:
    if k not in have:
        return bool(v) and v != {"resistance": 0, "resistance_in_lair": 0, "actions": 0,
                                 "actions_in_lair": 0, "has_lair": False, "action_names": [],
                                 "action_costs": {}, "action_spells": {}, "lair_actions": []}
    return have[k] != v


def _runs(layout):
    for name in layout.list_runs():
        yield name, layout.run_path(name)


def migrate(root: str, apply: bool, prefer_run=()) -> int:
    camp = sl.Campaign.open(root)
    sheets = ps.Sheets(camp)
    all_slugs = set(sheets.slugs())
    # NAME@dungeon → {slug: dungeon}
    prefer = {}
    for spec in prefer_run:
        name, _, dungeon = spec.partition("@")
        prefer[ps.slug_of(name)] = dungeon
    print(f"== {camp.name}: sheets {sorted(all_slugs)}")

    for s, d in sorted(prefer.items()):
        found = None
        if d in camp.list_dungeons():
            for _, path in _runs(camp.dungeon(d)):
                for sec in rs.load_run(path)["maps"].values():
                    for rec in sec.get("agents", []) or []:
                        if ps.is_pc(rec) and ps.slug_of(rec.get("name")) == s \
                                and ps.SHEET_TAG not in rec and found is None:
                            found = (rec, path)
        if found is None or sheets.get(s) is None:
            print(f"  --prefer-run {s}@{d}: no full record in that dungeon's runs "
                  f"(or no sheet)")
            continue
        rec, path = found
        print(f"  sheet {s} ← {os.path.relpath(path, camp.root)}")
        if apply:
            if os.path.isfile(sheets.path(s)):
                shutil.copy2(sheets.path(s), sheets.path(s) + BACKUP)
            sheets.put(s, ps.sheet_from(rec, sheets.get(s)))

    changed = 0
    for d in camp.list_dungeons():
        layout = camp.dungeon(d)
        present = set()
        for run_name, path in _runs(layout):
            run = rs.load_run(path)
            present |= ps.present_slugs(run) & all_slugs
            dirty = False
            for map_name, sec in run["maps"].items():
                for rec in sec.get("agents", []) or []:
                    s = ps.slug_of(rec.get("name")) if ps.is_pc(rec) else None
                    if s and prefer.get(s) != d and ps.SHEET_TAG not in rec \
                            and sheets.get(s) is not None:
                        diff = sheet_diff(rec, sheets.get(s))
                        if diff:
                            print(f"  {d}/{run_name}/{map_name} {rec['name']}: run differs "
                                  f"from sheet on {', '.join(diff)}")
                doc = rs.creatures(run, map_name)
                section, _ = ps.collapse(ps.expand(doc, sheets), sheets, write=False)
                if section != doc:
                    rs.set_creatures(run, map_name, section)
                    dirty = True
            if dirty:
                changed += 1
                print(f"  {d}/{run_name}: PCs → play state")
                if apply:
                    shutil.copy2(path, path + BACKUP)
                    rs.save_run(path, run)
        dung = Dungeon.load(layout.manifest_path)
        if present and present != all_slugs and dung.party is None:
            names = sorted(present)
            print(f"  {d}: party pinned to {names} (missing {sorted(all_slugs - present)})")
            if apply:
                shutil.copy2(layout.manifest_path, layout.manifest_path + BACKUP)
                dung.party = names
                atomic_write_json(layout.manifest_path, dung.to_dict())
    print(f"  {changed} run(s) {'migrated' if apply else 'to migrate'}"
          + ("" if apply else " — dry run, nothing written"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("campaigns", nargs="+", help="campaign folders")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prefer-run", action="append", default=[], metavar="NAME@DUNGEON",
                    help="write this PC's sheet from that dungeon's run first")
    args = ap.parse_args(argv)
    for c in args.campaigns:
        migrate(c, args.apply, args.prefer_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
