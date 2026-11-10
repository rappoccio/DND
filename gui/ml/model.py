"""The entity transformer (NPC_LEARNING_PLAN.md Step 6): scores an NPC's candidate
macro-actions.

The sequence is [archetype token, map token, creature tokens…] (self is the first
creature). A pre-norm transformer encoder contextualizes it. Each candidate is embedded from
its own features (``features.CAND_FIELDS``) and scored together with the encoded token of the
creature it targets (a learned "no target" vector when it has none), the actor's token and
the archetype token. Illegal candidates are masked out of the softmax. One extra output,
Defer, scores handing the turn to the engine's fallback chain (what ``l4-macro`` does when
Level 4's choice matches no legal candidate).
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from ml import features as F

NEG = -1e9


def _mlp(i: int, h: int, o: int) -> nn.Sequential:
    return nn.Sequential(nn.Linear(i, h), nn.GELU(), nn.Linear(h, o))


class EntityPolicy(nn.Module):
    def __init__(self, d: int = 128, layers: int = 4, heads: int = 4, ff: int = 256,
                 dropout: float = 0.0):
        super().__init__()
        self.config = {"d": d, "layers": layers, "heads": heads, "ff": ff, "dropout": dropout}
        self.tok_in = _mlp(F.TOKEN_DIM, d, d)
        self.map_in = _mlp(F.MAP_DIM, d, d)
        self.arch_emb = nn.Embedding(F.ARCH_COUNT, d)
        self.slot_emb = nn.Embedding(3, d)            # 0 archetype, 1 map, 2 creature
        layer = nn.TransformerEncoderLayer(d, heads, ff, dropout, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.cand_in = _mlp(F.CAND_DIM, d, d)
        self.no_target = nn.Parameter(torch.zeros(d))
        self.score = nn.Sequential(nn.Linear(4 * d, d), nn.GELU(), nn.Linear(d, d), nn.GELU(),
                                   nn.Linear(d, 1))
        self.defer = _mlp(2 * d, d, 1)

    def forward(self, b: dict) -> torch.Tensor:
        """``b`` from ``collate``. Returns (B, M + 1) logits: one per candidate (illegal / padded
        ones at NEG), then the Defer logit (hand the turn to the engine's fallback chain)."""
        B, N, _ = b["tokens"].shape
        dev = b["tokens"].device
        x = torch.cat([(self.arch_emb(b["arch"]) + self.slot_emb.weight[0]).unsqueeze(1),
                       (self.map_in(b["map"]) + self.slot_emb.weight[1]).unsqueeze(1),
                       self.tok_in(b["tokens"]) + self.slot_emb.weight[2]], dim=1)
        pad = torch.cat([torch.zeros(B, 2, dtype=torch.bool, device=dev), ~b["tok_valid"]], dim=1)
        h = self.norm(self.encoder(x, src_key_padding_mask=pad))
        arch_h, self_h, crea = h[:, 0], h[:, 2], h[:, 2:]

        tgt = b["cand_target"]                                    # (B, M), -1 = none
        idx = tgt.clamp(min=0).unsqueeze(-1).expand(-1, -1, crea.shape[-1])
        tgt_h = torch.gather(crea, 1, idx)
        tgt_h = torch.where((tgt >= 0).unsqueeze(-1), tgt_h, self.no_target.expand_as(tgt_h))
        M = tgt.shape[1]
        z = torch.cat([self.cand_in(b["cand"]), tgt_h,
                       self_h.unsqueeze(1).expand(-1, M, -1),
                       arch_h.unsqueeze(1).expand(-1, M, -1)], dim=-1)
        logits = self.score(z).squeeze(-1).masked_fill(~b["legal"], NEG)
        return torch.cat([logits, self.defer(torch.cat([self_h, arch_h], dim=-1))], dim=1)


def collate(samples: list[dict], device="cpu") -> dict:
    """Pad a list of ``features.featurize``-shaped samples into one batch."""
    B = len(samples)
    N = max(len(s["tokens"]) for s in samples)
    M = max(len(s["cand"]) for s in samples)
    tokens = np.zeros((B, N, F.TOKEN_DIM), dtype=np.float32)
    tok_valid = np.zeros((B, N), dtype=bool)
    cand = np.zeros((B, M, F.CAND_DIM), dtype=np.float32)
    cand_target = np.full((B, M), -1, dtype=np.int64)
    legal = np.zeros((B, M), dtype=bool)
    for i, s in enumerate(samples):
        n, m = len(s["tokens"]), len(s["cand"])
        tokens[i, :n], tok_valid[i, :n] = s["tokens"], True
        cand[i, :m], cand_target[i, :m], legal[i, :m] = s["cand"], s["cand_target"], s["legal"]
    out = {"tokens": tokens, "tok_valid": tok_valid,
           "map": np.stack([s["map"] for s in samples]).astype(np.float32),
           "arch": np.array([s["arch"] for s in samples], dtype=np.int64),
           "cand": cand, "cand_target": cand_target, "legal": legal}
    if "label" in samples[0]:      # DEFER (-1) is the last column, M
        out["label"] = np.array([M if s["label"] < 0 else s["label"] for s in samples],
                                dtype=np.int64)
    return {k: torch.from_numpy(v).to(device) for k, v in out.items()}


def save(model: EntityPolicy, path: str, **extra) -> None:
    torch.save({"config": model.config, "state_dict": model.state_dict(),
                "feature_version": F.FEATURE_VERSION, **extra}, path)


def load(path: str) -> tuple[EntityPolicy, dict]:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    if ck.get("feature_version") != F.FEATURE_VERSION:
        raise ValueError(f"{path}: trained on feature version {ck.get('feature_version')}, "
                         f"this code builds version {F.FEATURE_VERSION}")
    m = EntityPolicy(**ck["config"])
    m.load_state_dict(ck["state_dict"])
    m.eval()
    return m, ck
