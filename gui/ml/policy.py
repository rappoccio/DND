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

_CACHE: dict[tuple, Mdl.EntityPolicy] = {}
_CACHE_MAX = 16


def load(path: str) -> Mdl.EntityPolicy:
    """The checkpoint at ``path``, cached by path *and* modification time: a PPO run rewrites
    its ``*_latest.pt`` every iteration, and a worker must not keep the old weights."""
    path = os.path.abspath(path)
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = Mdl.load(path)[0]
    return _CACHE[key]


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
