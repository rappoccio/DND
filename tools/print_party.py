#!/usr/bin/env python3
"""Print generated PCs (NPC_LEARNING_PLAN.md Step 3b) as short character sheets, for review.

    python3 tools/print_party.py --seed 7                       # the party seed 7 draws
    python3 tools/print_party.py --build Cleric.LightDomain MT --level 5
    python3 tools/print_party.py --all --level 11               # every build at one level

Reads gui/pc_templates.json and the catalogs only (no engine), so it runs anywhere the repo
does; the project rule still says to run it in the container.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import party_gen as G      # noqa: E402

AC_TEXT = {"heavy": "heavy", "medium": "medium", "light": "light", "mage": "Mage Armor",
           "unarmored": "unarmored"}


def _weapon(w) -> str:
    return w["name"] if isinstance(w, dict) else (w or "-")


def sheet(rec: dict) -> str:
    s = rec["stats"]
    key, role = rec["pc_build"]["subclass"], rec["pc_build"]["role"]
    b = G.resolved_build(key, role)
    lines = [f"{rec['name']}  [{key} as {role}]"]
    lines.append("  " + "  ".join(f"{a.upper()[:3]} {s[a]}" for a in G.ABILITIES)
                 + f"   HP {s['hp_max']}  base AC {s['ac']} ({AC_TEXT[b['armor']]})"
                 + f"  speed {s['speed_walk']}  attacks {s['num_attacks']}")
    w = rec["weapons"]
    lines.append(f"  weapons: {_weapon(w['main_hand'])} / {_weapon(w['off_hand'])} / "
                 f"{_weapon(w['ranged'])}    feats: {', '.join(s['feats']) or '-'}")
    if rec["spell_indices"]:
        by: dict[int, list] = {}
        for n in rec["spell_indices"]:
            by.setdefault(G.data().spells[n]["level"], []).append(n)
        lines.append("  spells: " + "  |  ".join(
            f"{'C' if lv == 0 else lv}: {', '.join(ns)}" for lv, ns in sorted(by.items())))
    if rec.get("agent_eldritch_invocations"):
        lines.append(f"  invocations: {rec['agent_eldritch_invocations']}")
    extras = {k: v for k, v in rec.items()
              if k.startswith(("agent_hunter", "agent_defensive", "agent_primal", "agent_blessed",
                               "agent_wild_heart", "druid_land"))}
    extras.update({k: s[k] for k in ("metamagic_options", "draconic_affinity_type") if k in s})
    if extras:
        lines.append(f"  choices: {extras}")
    lines.append(f"  signature spells: {', '.join(rec['signature_spells']) or '-'}"
                 f"    features: {', '.join(rec['signature_features']) or '-'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", type=int, help="print the party this seed draws")
    g.add_argument("--build", nargs=2, metavar=("SUBCLASS", "ROLE"), help="e.g. Wizard.Evoker MT")
    g.add_argument("--all", action="store_true", help="every build in the role table")
    ap.add_argument("--level", type=int, default=None)
    a = ap.parse_args(argv)
    if a.seed is not None:
        party, meta = G.generate_party(a.seed, level=a.level)
        print(f"seed {a.seed}: level {meta['level']}, template {meta['template']}, "
              f"roles {meta['roles']}\n")
        print("\n\n".join(sheet(p) for p in party))
    elif a.build:
        print(sheet(G.build_pc(a.build[0], a.build[1], a.level or 5)))
    else:
        print("\n\n".join(sheet(G.build_pc(k, r, a.level or 5)) for k, r in G.builds()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
