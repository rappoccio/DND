"""A trained checkpoint as an NPC policy (``CombatEngine.set_npc_policy``).

    eng.set_npc_policy(policy.factory("ml_runs/bc.pt")(eng, bm, seed))

The rank callable featurizes the decision, scores every candidate and returns the legal
ones, best first (ties by candidate index), so the engine's rung 1/2 logic applies. When the
model's Defer output wins, it returns nothing and the engine runs its fallback chain. Inference
runs on one thread: the same decision always ranks the same way, which keeps a seeded
episode reproducible.
"""

from __future__ import annotations

import os

import numpy as np
import torch

from ml import features as F
from ml import model as Mdl

_CACHE: dict[str, Mdl.EntityPolicy] = {}


def load(path: str) -> Mdl.EntityPolicy:
    path = os.path.abspath(path)
    if path not in _CACHE:
        _CACHE[path] = Mdl.load(path)[0]
    return _CACHE[path]


@torch.no_grad()
def scores(net: Mdl.EntityPolicy, sample: dict) -> np.ndarray:
    return net(Mdl.collate([sample]))[0].numpy()


def factory(path: str):
    """``(engine, battle map, seed) -> rank`` for ``arena.run_episode(policy_factory=…)``."""
    torch.set_num_threads(1)
    net = load(path)

    def make(eng, bm, seed):
        def rank(idx, archetype, actions):
            if not actions:
                return []
            s = F.featurize(eng, bm, idx, archetype, actions)
            if not s["legal"].any():
                return []
            return rank_from_scores(scores(net, s), s["legal"])
        return rank
    return make


def rank_from_scores(z: np.ndarray, legal: np.ndarray) -> list[int]:
    """Legal candidates best first (ties by index), or ``[]`` when Defer (the last score)
    beats them all: the engine then runs its fallback chain."""
    order = sorted(np.flatnonzero(legal).tolist(), key=lambda i: (-float(z[i]), i))
    if not order or z[-1] > z[order[0]]:
        return []
    return order
