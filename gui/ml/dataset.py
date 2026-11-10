#!/usr/bin/env python3
"""Behaviour-cloning data (NPC_LEARNING_PLAN.md Step 6): arena episodes with the NPCs on
Level 4's own choices, every decision recorded with its label.

The NPCs run the ``l4-macro`` policy (Level 4's choice, ``npc_heuristic_macro_action``,
through the macro-action path). Each time the engine asks it, the decision is featurized
(``features.featurize``) and stored with the label: the index of Level 4's choice among
the candidates. A decision whose Level 4 choice matches no legal candidate (Level 4 picks a
turn it can't carry out, e.g. Simple with no enemy it can target) gets the label ``DEFER``
(-1): ``l4-macro`` returns nothing and the engine runs the Step 4 chain from rung 3, and the
model learns to do the same. These are counted as ``unlabeled``. A decision with no legal
candidate at all isn't stored.

Scenarios come from both splits; each sample carries its scenario's split, so training
never sees a held-out scenario. One shard per job, ``shard_<first episode>.npz``:

    tokens (ΣN, TOKEN_DIM)  tok_off (S+1)   map (S, MAP_DIM)   arch (S)
    cand (ΣM, CAND_DIM)     cand_target (ΣM)  legal (ΣM)  cand_off (S+1)
    label (S)  heldout (S)  episode (S)  agent (S)
    meta    JSON: feature version, episode outcomes, unlabeled count

CLI (in the container):
    python3 gui/ml/dataset.py --episodes 4000 --jobs 16 --out ml_runs/bc_data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

import arena                       # noqa: E402
from ml import features as F       # noqa: E402

EPISODES_PER_SHARD = 50
DEFER = -1                         # label: hand the turn to the engine's fallback chain


class Recorder:
    """Collects one shard's decisions."""

    def __init__(self):
        self.samples: list[dict] = []
        self.unlabeled = 0
        self.unlabeled_by: dict[str, int] = {}     # "<kind> <archetype>" of each miss
        self.heldout = False
        self.episode = -1

    def factory(self, eng, bm, seed):
        def rank(idx, archetype, actions):
            if not any(a.legal for a in actions):
                return []            # nothing to choose: the engine falls back whatever we say
            want = eng.npc_heuristic_macro_action(bm, idx)
            hit = next((i for i, a in enumerate(actions)
                        if a.legal and arena.same_macro(a, want)), DEFER)
            if hit == DEFER:
                self.unlabeled += 1
                key = f"{F.KIND_NAMES[int(want.kind)]} {F.ARCH_NAMES[int(archetype)]}"
                self.unlabeled_by[key] = self.unlabeled_by.get(key, 0) + 1
            s = F.featurize(eng, bm, idx, archetype, actions)
            s.update(label=hit, heldout=self.heldout, episode=self.episode, agent=int(idx))
            self.samples.append(s)
            return [] if hit == DEFER else [hit]
        return rank

    def arrays(self) -> dict:
        S = self.samples

        def off(key):
            return np.concatenate([[0], np.cumsum([len(s[key]) for s in S])]).astype(np.int64)

        def cat(key, dim, dtype):
            return (np.concatenate([s[key] for s in S]).astype(dtype) if S
                    else np.zeros((0,) + dim, dtype=dtype))
        return {"tokens": cat("tokens", (F.TOKEN_DIM,), np.float32), "tok_off": off("tokens"),
                "map": np.array([s["map"] for s in S], dtype=np.float32).reshape(-1, F.MAP_DIM),
                "arch": np.array([s["arch"] for s in S], dtype=np.int64),
                "cand": cat("cand", (F.CAND_DIM,), np.float32), "cand_off": off("cand"),
                "cand_target": cat("cand_target", (), np.int64),
                "legal": cat("legal", (), bool),
                "label": np.array([s["label"] for s in S], dtype=np.int64),
                "heldout": np.array([s["heldout"] for s in S], dtype=bool),
                "episode": np.array([s["episode"] for s in S], dtype=np.int64),
                "agent": np.array([s["agent"] for s in S], dtype=np.int64)}


def record_shard(job: dict) -> dict:
    """Episodes ``k0 … k1-1`` of a run → one shard in ``job['out']``."""
    rec = Recorder()
    outcomes = []
    for k in range(job["k0"], job["k1"]):
        sc = arena.scenario_for_split(job["base_seed"], k, "any")
        seed = job["base_seed"] * 7919 + k
        rec.heldout, rec.episode = sc.split == "heldout", k
        out = arena.run_episode(sc, seed, "l4-macro", "Heuristic", round_cap=job["round_cap"],
                                policy_factory=rec.factory)
        outcomes.append({"episode": k, "split": sc.split, "winner": out["winner"],
                         "reason": out["reason"], "rounds": out["rounds"]})
    path = os.path.join(job["out"], f"shard_{job['k0']:06d}.npz")
    meta = {"feature_version": F.FEATURE_VERSION, "base_seed": job["base_seed"],
            "k0": job["k0"], "k1": job["k1"], "unlabeled": rec.unlabeled,
            "unlabeled_by": rec.unlabeled_by,
            "samples": len(rec.samples), "outcomes": outcomes}
    np.savez_compressed(path, meta=np.array(json.dumps(meta)), **rec.arrays())
    return {"path": path, "samples": len(rec.samples), "unlabeled": rec.unlabeled,
            "unlabeled_by": rec.unlabeled_by}


def _worker_init():
    arena.arena()


def write(out: str, episodes: int, *, base_seed: int = 1, jobs: int = 1,
          round_cap: int = arena.ROUND_CAP, per_shard: int = EPISODES_PER_SHARD):
    """Record ``episodes`` episodes into ``out``; yields each shard's summary as it lands."""
    os.makedirs(out, exist_ok=True)
    work = [{"base_seed": base_seed, "k0": k, "k1": min(episodes, k + per_shard),
             "round_cap": round_cap, "out": out} for k in range(0, episodes, per_shard)]
    if jobs <= 1:
        for j in work:
            yield record_shard(j)
        return
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(jobs, initializer=_worker_init) as pool:
        yield from pool.imap_unordered(record_shard, work)


# ── Reading ─────────────────────────────────────────────────────────────────

class Shards:
    """Every shard in a directory, concatenated; ``sample(i)`` gives one decision back."""

    def __init__(self, path: str):
        files = sorted(f for f in os.listdir(path) if f.startswith("shard_") and f.endswith(".npz"))
        if not files:
            raise FileNotFoundError(f"no shard_*.npz in {path}")
        parts = [np.load(os.path.join(path, f)) for f in files]
        self.meta = [json.loads(str(p["meta"])) for p in parts]
        for m in self.meta:
            if m["feature_version"] != F.FEATURE_VERSION:
                raise ValueError(f"shard feature version {m['feature_version']} != "
                                 f"{F.FEATURE_VERSION}; re-record the dataset")

        def joined(key):
            return np.concatenate([p[key] for p in parts])

        def offsets(key):
            out, base = [np.zeros(1, dtype=np.int64)], 0
            for p in parts:
                o = p[key]
                out.append(o[1:] + base)
                base += int(o[-1])
            return np.concatenate(out)
        self.tokens, self.tok_off = joined("tokens"), offsets("tok_off")
        self.cand, self.cand_off = joined("cand"), offsets("cand_off")
        self.cand_target, self.legal = joined("cand_target"), joined("legal")
        self.map, self.arch, self.label = joined("map"), joined("arch"), joined("label")
        self.heldout, self.episode = joined("heldout"), joined("episode")
        self.agent = joined("agent")

    def __len__(self) -> int:
        return len(self.label)

    def sample(self, i: int) -> dict:
        t0, t1 = self.tok_off[i], self.tok_off[i + 1]
        c0, c1 = self.cand_off[i], self.cand_off[i + 1]
        return {"tokens": self.tokens[t0:t1], "map": self.map[i], "arch": int(self.arch[i]),
                "cand": self.cand[c0:c1], "cand_target": self.cand_target[c0:c1],
                "legal": self.legal[c0:c1], "label": int(self.label[i])}

    def kind_of_label(self, i: int) -> int:
        """The label's NpcMacroKind; ``F.KIND_COUNT`` for DEFER."""
        if self.label[i] == DEFER:
            return F.KIND_COUNT
        row = self.cand[self.cand_off[i] + self.label[i]]
        return int(np.argmax(row[:F.KIND_COUNT]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record Level 4 behaviour-cloning shards.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--episodes", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--round-cap", type=int, default=arena.ROUND_CAP)
    ap.add_argument("--per-shard", type=int, default=EPISODES_PER_SHARD)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    t0 = time.perf_counter()
    n = miss = 0
    by: dict[str, int] = {}
    for r in write(out, a.episodes, base_seed=a.seed, jobs=a.jobs, round_cap=a.round_cap,
                   per_shard=a.per_shard):
        n += r["samples"]
        miss += r["unlabeled"]
        for k, v in r["unlabeled_by"].items():
            by[k] = by.get(k, 0) + v
        print(f"{os.path.basename(r['path'])}: {r['samples']} samples, "
              f"{r['unlabeled']} unlabeled  (total {n})", flush=True)
    print(json.dumps({"samples": n, "deferred": miss, "defer_share": round(miss / max(1, n), 4),
                      "unlabeled_by": dict(sorted(by.items(), key=lambda kv: -kv[1])),
                      "wall_s": round(time.perf_counter() - t0, 1), "out": out}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
