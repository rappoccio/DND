#!/usr/bin/env python3
"""Turn a dungeon's ladder pairs into staircases (step 4 of plans/STAIRCASES_PLAN.md).

Every ladder is matched with its return: the ladder on the page it leads to that stands
on its landing cell and leads back onto one of its own cells. Each pair becomes one
staircase in the manifest, "Staircase N" with no label, whose two ends are the pair's
two cells, so nothing moves. The ladders are then deleted from the pages' _terrain.json.

A ladder with no return partner (or more than one) is an error: the script reports
every one and stops without writing. So is a pair whose floors are not adjacent. Real
ladders stay ladders: name one end of each with ``--keep PAGE:COL,ROW`` and the pair is
left alone. A ladder that leads somewhere on its own page is never a staircase and is
left alone too.

Without ``--apply`` it only prints the pairs. With it, the manifest and every terrain
file it changes are first copied to ``pre_staircases/`` beside the manifest. Quit the
game first: it saves terrain on quit and on a floor switch, which would put the ladders
back. Labels (K21, K83, …) are filled in afterwards from Dungeon Configuration →
Staircases….

    python3 tools/ladders_to_staircases.py "encounters/Castle Ravenloft/main_floor_ravenloft.dungeon.json" \\
        --keep tower_peaks_map9_10_ravenloft:39,20
    python3 tools/ladders_to_staircases.py <manifest> --keep ... --apply
"""

import argparse
import json
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

from atomic_io import atomic_write_json  # noqa: E402
from dungeon import Dungeon, StaircaseEnd  # noqa: E402


class ConversionError(Exception):
    """The ladders can't be converted as they stand; ``problems`` lists why."""

    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


def terrain_path(manifest_dir, page):
    """The _terrain.json a page loads, resolved like the app does."""
    enc = page.encounter_base
    enc = enc if os.path.isabs(enc) else os.path.join(manifest_dir, enc)
    d, fn = os.path.split(enc)
    base = fn[:-len("_agents.json")] if fn.endswith("_agents.json") else os.path.splitext(fn)[0]
    return os.path.join(d, base + "_terrain.json")


def _cells(lad):
    return [(int(c[0]), int(c[1])) for c in lad.get("cells", [])]


def _target(lad):
    return tuple(int(v) for v in lad["target"][:3])


def plan_conversion(dungeon, ladders, keep=()):
    """Pair the ladders. ``ladders`` maps page id → that page's ladder records, and
    ``keep`` holds ``(page_id, (col, row))`` cells naming ladders to leave alone.

    Returns ``(pairs, kept)``: ``pairs`` is a list of ``((page, index, cell),
    (page, index, cell))``, lower floor first, in staircase-id order; ``kept`` is the
    set of ``(page, index)`` that stay ladders. Raises ConversionError listing every
    unpaired, ambiguous or non-adjacent ladder, and every ``keep`` that names none."""
    problems = []

    def describe(pid, i):
        lad = ladders[pid][i]
        return f"{pid} ladder at {[list(c) for c in _cells(lad)]} -> {list(_target(lad))}"

    keep_idx = set()
    for pid, cell in keep:
        hits = [(pid, i) for i, lad in enumerate(ladders.get(pid, [])) if cell in _cells(lad)]
        if not hits:
            problems.append(f"--keep {pid}:{cell[0]},{cell[1]}: no ladder there")
        keep_idx.update(hits)

    partner = {}
    same_page = set()
    for pid, lads in ladders.items():
        page = dungeon.page_by_id(pid)
        for i, lad in enumerate(lads):
            T = _target(lad)
            there = dungeon.page_at_global(*T)
            if there is None:
                problems.append(f"{describe(pid, i)}: no page at its target")
                continue
            if there.id == pid:
                same_page.add((pid, i))
                continue
            landing = there.global_to_local(*T)
            mine = {page.local_to_global(*c) for c in _cells(lad)}
            found = [(there.id, j) for j, back in enumerate(ladders.get(there.id, []))
                     if landing in _cells(back) and _target(back) in mine]
            if len(found) != 1:
                why = "no return ladder" if not found else f"{len(found)} return ladders"
                problems.append(f"{describe(pid, i)}: {why} on {there.id} at {list(landing)}")
                continue
            partner[(pid, i)] = (found[0], landing)

    # A kept ladder keeps its partner a ladder too.
    kept = set(keep_idx) | same_page
    for k in keep_idx:
        if k in partner:
            kept.add(partner[k][0])

    pairs = []
    seen = set()
    for key, (other, landing) in partner.items():
        if key in kept or key in seen:
            continue
        if partner.get(other, (None,))[0] != key:
            problems.append(f"{describe(*key)}: its return ladder leads elsewhere")
            continue
        seen.update((key, other))
        a = (key[0], key[1], partner[other][1])      # this ladder's cell the return lands on
        b = (other[0], other[1], landing)
        za = dungeon.page_by_id(a[0]).z
        zb = dungeon.page_by_id(b[0]).z
        if abs(za - zb) != 1:
            problems.append(f"{describe(*key)}: floors {za} and {zb} are not adjacent")
            continue
        if zb < za:
            a, b = b, a
        pairs.append((a, b))

    if problems:
        raise ConversionError(problems)
    order = {p.id: n for n, p in enumerate(dungeon.pages)}
    pairs.sort(key=lambda ab: (dungeon.page_by_id(ab[0][0]).z, order[ab[0][0]],
                               ab[0][2], order[ab[1][0]], ab[1][2]))
    return pairs, kept


def apply_conversion(dungeon, ladders, pairs):
    """Add one staircase per pair to ``dungeon`` and drop the paired ladders from
    ``ladders`` (in place). Returns the new staircases, in pair order."""
    made = []
    drop = {}
    for (pa, ia, ca), (pb, ib, cb) in pairs:
        st = dungeon.new_staircase(pa, ca)
        st.ends.append(StaircaseEnd(pb, cb))
        made.append(st)
        drop.setdefault(pa, set()).add(ia)
        drop.setdefault(pb, set()).add(ib)
    for pid, idx in drop.items():
        ladders[pid] = [lad for i, lad in enumerate(ladders[pid]) if i not in idx]
    return made


def _parse_keep(s):
    try:
        pid, cell = s.rsplit(":", 1)
        c, r = cell.split(",")
        return pid, (int(c), int(r))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--keep wants PAGE:COL,ROW, got {s!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest")
    ap.add_argument("--keep", action="append", type=_parse_keep, default=[],
                    metavar="PAGE:COL,ROW", help="a real ladder (one end) to leave alone")
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args(argv)

    mdir = os.path.dirname(os.path.abspath(args.manifest))
    dungeon = Dungeon.load(args.manifest)
    paths, docs, ladders = {}, {}, {}
    for page in dungeon.pages:
        path = terrain_path(mdir, page)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            docs[page.id] = json.load(f)
        paths[page.id] = path
        ladders[page.id] = list(docs[page.id].get("ladders", []))
    before = sum(len(v) for v in ladders.values())

    try:
        pairs, kept = plan_conversion(dungeon, ladders, args.keep)
    except ConversionError as e:
        print("Not converted; fix these first:", file=sys.stderr)
        for p in e.problems:
            print("  " + p, file=sys.stderr)
        return 1

    made = apply_conversion(dungeon, ladders, pairs)
    for st, ((pa, _, ca), (pb, _, cb)) in zip(made, pairs):
        print(f"{st.name:>14}: {pa} {list(ca)}  <->  {pb} {list(cb)}")
    left = sum(len(v) for v in ladders.values())
    print(f"{len(made)} staircases from {before - left} ladders; {left} ladders kept:")
    for pid, i in sorted(kept):
        lad = docs[pid]["ladders"][i]
        print(f"  {pid} {[list(c) for c in _cells(lad)]} -> {list(_target(lad))}")

    if not args.apply:
        print("Dry run; nothing written. Add --apply to convert.")
        return 0
    backup = os.path.join(mdir, "pre_staircases")
    os.makedirs(backup, exist_ok=True)
    changed = [pid for pid in ladders if len(ladders[pid]) != len(docs[pid].get("ladders", []))]
    for path in [os.path.abspath(args.manifest)] + [paths[pid] for pid in changed]:
        shutil.copy2(path, os.path.join(backup, os.path.basename(path)))
    for pid in changed:
        docs[pid]["ladders"] = ladders[pid]
        atomic_write_json(paths[pid], docs[pid])
    atomic_write_json(args.manifest, dungeon.to_dict())
    print(f"Wrote {args.manifest} and {len(changed)} terrain files; originals in {backup}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
