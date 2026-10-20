#!/usr/bin/env python3
"""Rescale every page image of a dungeon so its drawn squares are whole pixels.

The command-line form of Terrain… → Rescale Image to Grid… (see gui/grid_rescale.py for
how it works): for each page with a manual grid it measures the drawn square, re-renders
the image from its original at the corrected size, keeps every cell's index, and updates
the page's cols/rows in the manifest. Everything replaced goes to ``pre_rescale/``.

Without ``--apply`` it only measures and reports. Quit the game first: it saves terrain
on quit and on a floor switch, which would put the old anchors back.

    python3 tools/rescale_to_grid.py "encounters/Castle Ravenloft/main_floor_ravenloft.dungeon.json"
    python3 tools/rescale_to_grid.py <manifest> --apply [--page ID ...]
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import grid_rescale  # noqa: E402


def terrain_path(manifest_dir, page):
    enc = page["encounter_base"]
    enc = enc if os.path.isabs(enc) else os.path.join(manifest_dir, enc)
    d, fn = os.path.split(enc)
    for suf in ("_agents.json", ".json"):
        if fn.endswith(suf):
            fn = fn[: -len(suf)]
            break
    return os.path.join(d, fn + "_terrain.json")


def plan_page(manifest_dir, page):
    png = page["png"] if os.path.isabs(page["png"]) else os.path.join(manifest_dir, page["png"])
    return grid_rescale.plan(png, terrain_path(manifest_dir, page))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest")
    ap.add_argument("--apply", action="store_true", help="write the images (default: report only)")
    ap.add_argument("--page", action="append", help="only these page ids (repeatable)")
    args = ap.parse_args(argv)

    manifest = os.path.abspath(args.manifest)
    mdir = os.path.dirname(manifest)
    with open(manifest) as f:
        dungeon = json.load(f)
    backup_dir = os.path.join(mdir, "pre_rescale")
    changed = False
    for page in dungeon.get("pages", []):
        if args.page and page["id"] not in args.page:
            continue
        p = plan_page(mdir, page)
        if "skip" in p:
            print(f"{page['id']}: skipped — {p['skip']}")
            continue
        (px, py), (dx, dy) = p["period"], p["drift"]
        print(f"{page['id']}: {os.path.basename(p['png'])} {p['size'][0]}×{p['size'][1]}, "
              f"square {px:.2f}×{py:.2f} px (want {p['nominal']}), "
              f"drift across the map {dx:.1f}×{dy:.1f} px")
        if not p["needed"]:
            print("    already within a few px — left alone")
            continue
        if not args.apply:
            print(f"    would scale by {p['scale'][0]:.4f} × {p['scale'][1]:.4f}")
            continue
        if not changed:
            grid_rescale._backup(manifest, backup_dir)   # before the first write
        r = grid_rescale.apply(p, backup_dir)
        page["cols"], page["rows"] = r["cols"], r["rows"]
        changed = True
        note = f", padded/cropped {r['shift']}" if any(r["shift"]) else ""
        print(f"    → {r['size'][0]}×{r['size'][1]} from {os.path.basename(r['source'])}, "
              f"anchor {r['anchor'][0]},{r['anchor'][1]}{note}")
    if changed:
        with open(manifest, "w") as f:
            json.dump(dungeon, f, indent=2)
        print(f"Replaced files copied to {os.path.relpath(backup_dir)}/")
    elif not args.apply:
        print("Report only. Re-run with --apply to rescale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
