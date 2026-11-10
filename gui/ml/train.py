#!/usr/bin/env python3
"""Behaviour cloning of Level 4 (NPC_LEARNING_PLAN.md Step 6).

Trains ``model.EntityPolicy`` on ``dataset.py`` shards with cross-entropy over each
decision's legal candidates. Samples from held-out scenarios are never trained on; after
every epoch the held-out top-1 agreement (the gate's first number) is measured, and the
best epoch's weights are kept.

CLI (in the container):
    python3 gui/ml/train.py --data ml_runs/bc_data --out ml_runs/bc.pt --epochs 12
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch

_GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

from ml import features as F               # noqa: E402
from ml import model as Mdl                # noqa: E402
from ml.dataset import Shards              # noqa: E402


def batches(data: Shards, rows: np.ndarray, size: int):
    for i in range(0, len(rows), size):
        yield Mdl.collate([data.sample(int(j)) for j in rows[i:i + size]])


@torch.no_grad()
def evaluate(net, data: Shards, rows: np.ndarray, size: int = 512) -> dict:
    """Top-1 agreement with the label over ``rows``, overall and by label kind / archetype."""
    net.eval()
    hits = np.zeros(len(rows), dtype=bool)
    loss = 0.0
    for k, b in enumerate(batches(data, rows, size)):
        logits = net(b)
        loss += float(torch.nn.functional.cross_entropy(logits, b["label"], reduction="sum"))
        hits[k * size:k * size + len(b["label"])] = (logits.argmax(1) == b["label"]).numpy()
    kinds = np.array([data.kind_of_label(int(j)) for j in rows])
    archs = data.arch[rows]

    def by(keys, names):
        return {names[v]: {"n": int((keys == v).sum()), "acc": round(float(hits[keys == v].mean()), 4)}
                for v in sorted(set(keys.tolist()))}
    return {"n": int(len(rows)), "top1": round(float(hits.mean()), 4) if len(rows) else None,
            "loss": round(loss / max(1, len(rows)), 4),
            "by_kind": by(kinds, F.LABEL_NAMES), "by_archetype": by(archs, F.ARCH_NAMES)}


def train(data: Shards, out: str, *, epochs: int = 12, batch: int = 256, lr: float = 3e-4,
          seed: int = 0, d: int = 128, layers: int = 4, heads: int = 4, ff: int = 256,
          log=print) -> dict:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    train_rows = np.flatnonzero(~data.heldout)
    held_rows = np.flatnonzero(data.heldout)
    net = Mdl.EntityPolicy(d=d, layers=layers, heads=heads, ff=ff)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * math.ceil(len(train_rows) / batch)
    warmup = max(1, min(200, steps // 10))      # linear warmup, then cosine decay to 0
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, steps)))))
    log(f"train {len(train_rows)} samples, held out {len(held_rows)}, "
        f"{sum(p.numel() for p in net.parameters())} parameters")
    best, history = None, []
    for ep in range(epochs):
        net.train()
        t0 = time.perf_counter()
        rows = rng.permutation(train_rows)
        tot = n = 0
        for b in batches(data, rows, batch):
            loss = torch.nn.functional.cross_entropy(net(b), b["label"])
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += float(loss) * len(b["label"])
            n += len(b["label"])
        held = evaluate(net, data, held_rows) if len(held_rows) else {"top1": None}
        rec = {"epoch": ep + 1, "train_loss": round(tot / max(1, n), 4),
               "heldout_top1": held["top1"], "heldout_loss": held.get("loss"),
               "epoch_s": round(time.perf_counter() - t0, 1)}
        history.append(rec)
        log(json.dumps(rec))
        if best is None or (held["top1"] or 0) > (best["heldout"]["top1"] or 0):
            best = {"epoch": ep + 1, "heldout": held}
            Mdl.save(net, out, metrics=best, history=history)
    best["history"] = history
    best["train_top1"] = evaluate(Mdl.load(out)[0], data,
                                  train_rows[rng.permutation(len(train_rows))[:20000]])["top1"]
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Behaviour-clone Level 4 from dataset shards.")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True, help="checkpoint path (.pt)")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0, help="torch threads (0 = torch's default)")
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--layers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.threads:
        torch.set_num_threads(a.threads)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    best = train(Shards(os.path.abspath(a.data)), out, epochs=a.epochs, batch=a.batch, lr=a.lr,
                 seed=a.seed, d=a.d, layers=a.layers)
    print(json.dumps({k: v for k, v in best.items() if k != "history"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
