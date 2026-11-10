#!/usr/bin/env python3
"""Step 6's gate (NPC_LEARNING_PLAN.md): the behaviour-cloned policy reproduces Level 4.

  1. **Agreement**: top-1 agreement with Level 4's label on the dataset's held-out
     decisions, ≥ 90%.
  2. **Win rate**: on held-out scenarios with paired seeds (same scenario and seed, only the
     NPC policy swapped), the ``bc`` NPCs' win rate is within ±3 points of ``level4``'s.

CLI (in the container):
    python3 gui/ml/gate.py --model ml_runs/bc.pt --data ml_runs/bc_data --episodes 2000 --jobs 16
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

_GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

import arena                                # noqa: E402

AGREEMENT_GATE = 0.90
WINRATE_GATE = 0.03


def agreement(model: str, data: str) -> dict:
    from ml import model as Mdl
    from ml.dataset import Shards
    from ml.train import evaluate
    d = Shards(data)
    return evaluate(Mdl.load(model)[0], d, np.flatnonzero(d.heldout))


def paired_winrate(model: str, episodes: int, *, base_seed: int, jobs: int,
                   round_cap: int = arena.ROUND_CAP, log=print) -> dict:
    def jobs_for(policy):
        return [{"base_seed": base_seed, "k": k, "split": "heldout", "maps": None,
                 "parties": None, "npc_policy": policy, "pc_mode": "Heuristic",
                 "round_cap": round_cap, "trace_dir": None, "trace_all": False,
                 "model": model if policy == "bc" else None} for k in range(episodes)]
    res = {}
    for policy in ("level4", "bc"):
        t0 = time.perf_counter()
        res[policy] = {o["episode"]: o for o in arena.run_batch(jobs_for(policy), jobs)}
        log(f"{policy}: {episodes} held-out episodes in {time.perf_counter() - t0:.0f}s")
    ks = sorted(res["level4"])
    w4 = np.array([res["level4"][k]["winner"] == "npc" for k in ks], dtype=float)
    wb = np.array([res["bc"][k]["winner"] == "npc" for k in ks], dtype=float)
    diff = wb - w4
    se = float(diff.std(ddof=1) / math.sqrt(len(ks))) if len(ks) > 1 else float("nan")
    same = sum(res["level4"][k]["winner"] == res["bc"][k]["winner"] for k in ks)
    return {"episodes": len(ks), "level4_npc_win": round(float(w4.mean()), 4),
            "bc_npc_win": round(float(wb.mean()), 4), "diff": round(float(diff.mean()), 4),
            "diff_ci95": [round(float(diff.mean()) - 1.96 * se, 4),
                          round(float(diff.mean()) + 1.96 * se, 4)],
            "same_winner": round(same / len(ks), 4),
            "draws": {p: sum(res[p][k]["winner"] is None for k in ks) for p in res}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Step 6 gate: agreement + paired win rate vs Level 4.")
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default=None, help="dataset dir for the agreement check")
    ap.add_argument("--episodes", type=int, default=2000)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=101,
                    help="base seed of the held-out evaluation episodes")
    ap.add_argument("--round-cap", type=int, default=arena.ROUND_CAP)
    ap.add_argument("--report", default=None, help="write the report JSON here")
    a = ap.parse_args(argv)
    model = os.path.abspath(a.model)
    report: dict = {"model": model}
    if a.data:
        agr = agreement(model, os.path.abspath(a.data))
        report["agreement"] = agr
        report["agreement_pass"] = bool(agr["top1"] is not None and agr["top1"] >= AGREEMENT_GATE)
    if a.episodes > 0:
        wr = paired_winrate(model, a.episodes, base_seed=a.seed, jobs=a.jobs, round_cap=a.round_cap)
        report["winrate"] = wr
        report["winrate_pass"] = abs(wr["diff"]) <= WINRATE_GATE
    report["pass"] = all(v for k, v in report.items() if k.endswith("_pass"))
    text = json.dumps(report, indent=2)
    print(text)
    if a.report:
        with open(a.report, "w") as f:
            f.write(text + "\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
