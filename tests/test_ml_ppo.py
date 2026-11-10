#!/usr/bin/env python3
"""PPO machinery (NPC_LEARNING_PLAN.md Step 7, gui/ml/ppo.py).

Rewards are the terminal ±1/0 plus a telescoping HP-share term; GAE matches its definition;
the sampler only picks legal candidates (or Defer), records log-probabilities the update can
recompute under padding, and is reproducible per seed; a value-only update leaves the policy
alone; a Step 6 checkpoint (no value head) still loads; and tiny Heuristic and SelfPlay runs
write their checkpoints, evaluation, traces and pools. Nothing here is a real training run:
the models are tiny and random, and the runs are two iterations long.
"""

import json
import os
import shutil
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import numpy as np
import torch

import arena
from ml import model as Mdl
from ml import ppo

_TMP = tempfile.mkdtemp(prefix="ml_ppo_")
_INIT = os.path.join(_TMP, "init.pt")


def _init_ckpt() -> str:
    if not os.path.exists(_INIT):
        torch.manual_seed(0)
        Mdl.save(Mdl.EntityPolicy(d=32, layers=1, heads=2, ff=64), _INIT)
    return _INIT


def _tiny_cfg(**kw) -> ppo.Config:
    base = dict(episodes_per_iter=2, epochs=2, minibatch=64, eval_every=1, eval_episodes=2,
                eval_traces=1, value_warmup=1, block=1, round_cap=4)
    return ppo.Config(**(base | kw))


def _rollout(side="npc", k=0, opponent=ppo.HEURISTIC, seed=1) -> dict:
    return ppo.rollout_job({"side": side, "ckpt": _init_ckpt(), "version": 0, "base_seed": seed,
                            "k": k, "opponent": opponent, "round_cap": 6, "shaping": 0.2,
                            "gamma": 0.99, "lam": 0.95})


# ── Rewards and advantages ───────────────────────────────────────────────────
def test_rewards_are_terminal_plus_telescoping_shaping():
    steps = [{"phi": 0.0}, {"phi": 0.1}, {"phi": -0.2}]
    out = {"winner": "npc", "hp_frac": {"npc": 0.5, "pc": 0.2}}
    r = ppo.rewards(steps, out, "npc", 0.5)
    assert np.allclose(r[:2], [0.05, -0.15])
    assert np.isclose(r.sum(), 1.0 + 0.5 * ((0.5 - 0.2) - 0.0))      # φ_end − φ_start
    assert np.isclose(ppo.rewards(steps, out, "pc", 0.5)[-1], -1.0 + 0.5 * ((0.2 - 0.5) + 0.2))
    draw = dict(out, winner=None)
    assert np.isclose(ppo.rewards(steps, draw, "npc", 0.5).sum(), 0.5 * 0.3)
    assert len(ppo.rewards([], out, "npc", 0.5)) == 0
    print("✅ test_rewards_are_terminal_plus_telescoping_shaping passed")


def test_gae_matches_its_definition():
    r = np.array([0.1, -0.2, 1.0])
    v = np.array([0.3, 0.5, 0.2])
    adv, ret = ppo.gae(r, v, 1.0, 1.0)              # λ = γ = 1: return = reward-to-go
    assert np.allclose(ret, [0.9, 0.8, 1.0])
    assert np.allclose(adv, ret - v)
    adv0, _ = ppo.gae(r, v, 0.9, 0.0)               # λ = 0: one-step TD errors
    assert np.allclose(adv0, [0.1 + 0.9 * 0.5 - 0.3, -0.2 + 0.9 * 0.2 - 0.5, 1.0 - 0.2])
    print("✅ test_gae_matches_its_definition passed")


# ── Rollouts ─────────────────────────────────────────────────────────────────
def test_sampler_picks_legal_and_is_reproducible():
    a, b = _rollout(k=0), _rollout(k=0)
    assert a["steps"], "the NPC learner was never asked"
    assert [s["label"] for s in a["steps"]] == [s["label"] for s in b["steps"]]
    assert a["winner"] == b["winner"] and a["rounds"] == b["rounds"]
    for s in a["steps"]:
        assert s["label"] == -1 or s["legal"][s["label"]]
        assert s["logp"] <= 0.0 and np.isfinite(s["value"])
        assert "phi" not in s and np.isfinite(s["adv"]) and np.isfinite(s["ret"])
    print(f"✅ test_sampler_picks_legal_and_is_reproducible passed ({len(a['steps'])} decisions)")


def test_recorded_logp_survives_batch_padding():
    """The update recomputes each choice's log-probability in a padded batch; with unchanged
    weights it must equal what the sampler recorded (Defer maps to the last column)."""
    steps = _rollout(k=1)["steps"] + _rollout(k=2)["steps"]
    net = Mdl.load(_init_ckpt())[0]
    with torch.no_grad():
        b = Mdl.collate(steps)
        logp = torch.log_softmax(net(b), -1).gather(1, b["label"].unsqueeze(1)).squeeze(1)
    assert np.allclose(logp.numpy(), [s["logp"] for s in steps], atol=1e-4)
    print("✅ test_recorded_logp_survives_batch_padding passed")


def test_pc_learner_records_only_pc_decisions():
    r = _rollout(side="pc", k=3)
    assert r["steps"], "the PC learner was never asked"
    assert all(s["tokens"][0][0] == 1.0 for s in r["steps"])            # self first
    assert {arena.arena().app.bm.placed_agents[s["agent"]].faction for s in r["steps"]} \
        == {arena.PC_FACTION}
    print("✅ test_pc_learner_records_only_pc_decisions passed")


# ── The update ───────────────────────────────────────────────────────────────
def test_value_only_update_leaves_the_policy():
    steps = [s for k in range(4, 8) for s in _rollout(k=k)["steps"]]
    cfg = _tiny_cfg(epochs=4)
    net = Mdl.load(_init_ckpt())[0]
    b = Mdl.collate(steps)
    with torch.no_grad():
        logits0, _ = net.forward_value(b)
    ret = torch.tensor([s["ret"] for s in steps], dtype=torch.float32)

    def v_loss():
        with torch.no_grad():
            return float(((net.forward_value(b)[1] - ret) ** 2).mean())
    before = v_loss()
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3)
    vopt = torch.optim.AdamW(net.value_head.parameters(), lr=1e-3)
    ppo.ppo_update(net, opt, steps, cfg, np.random.default_rng(0), value_only=True, value_opt=vopt)
    with torch.no_grad():
        logits1, _ = net.forward_value(b)
    assert torch.equal(logits0, logits1)
    assert v_loss() < before
    stats = ppo.ppo_update(net, opt, steps, cfg, np.random.default_rng(0))
    with torch.no_grad():
        assert not torch.equal(logits0, net.forward_value(b)[0])
    assert {"pg_loss", "v_loss", "entropy", "kl", "clipfrac", "epochs"} <= stats.keys()
    print("✅ test_value_only_update_leaves_the_policy passed")


def test_step6_checkpoint_without_value_head_loads():
    ck = torch.load(_init_ckpt(), weights_only=False)
    ck["state_dict"] = {k: v for k, v in ck["state_dict"].items() if not k.startswith("value_head.")}
    old = os.path.join(_TMP, "step6.pt")
    torch.save(ck, old)
    net = Mdl.load(old)[0]
    ref = Mdl.load(_init_ckpt())[0]
    assert torch.equal(net.score[0].weight, ref.score[0].weight)
    ck["state_dict"]["bogus.weight"] = torch.zeros(1)
    torch.save(ck, old)
    try:
        Mdl.load(old)
    except RuntimeError as e:
        assert "unexpected" in str(e)
    else:
        raise AssertionError("a checkpoint with unknown weights loaded")
    print("✅ test_step6_checkpoint_without_value_head_loads passed")


# ── Runs ─────────────────────────────────────────────────────────────────────
def test_heuristic_run_writes_checkpoints_eval_and_traces():
    out = os.path.join(_TMP, "run_h")
    res = ppo.train(out, _init_ckpt(), iterations=2, cfg=_tiny_cfg(), log=lambda *_: None)
    with open(os.path.join(out, "history.jsonl")) as f:
        hist = [json.loads(ln) for ln in f]
    assert [h["iteration"] for h in hist] == [1, 2]
    assert [h["side"] for h in hist] == ["npc", "npc"]
    assert hist[0]["value_only"] and not hist[1]["value_only"]
    for h in hist:
        assert h["eval"]["episodes"] == 2 and os.path.exists(h["eval"]["checkpoint"])
    for f in ("npc_latest.pt", "npc_best.pt", "baseline_eval.json", "config.json"):
        assert os.path.exists(os.path.join(out, f)), f
    traces = os.listdir(os.path.join(out, "traces", "it0001"))
    assert len(traces) == 1 and traces[0].endswith(".jsonl")
    assert res["best"]["npc"]["iteration"] in (1, 2)
    print("✅ test_heuristic_run_writes_checkpoints_eval_and_traces passed")


def test_selfplay_alternates_sides_and_grows_pools():
    out = os.path.join(_TMP, "run_sp")
    ppo.train(out, _init_ckpt(), iterations=2, cfg=_tiny_cfg(eval_every=0), pc_mode="SelfPlay",
              log=lambda *_: None)
    with open(os.path.join(out, "history.jsonl")) as f:
        hist = [json.loads(ln) for ln in f]
    assert [h["side"] for h in hist] == ["npc", "pc"]
    assert all(h["value_only"] for h in hist)           # each side's first iteration
    with open(os.path.join(out, "pool.json")) as f:
        pools = json.load(f)
    assert pools["pc"][0] == ppo.HEURISTIC and pools["pc"][1].endswith("pc_snap0000.pt")
    assert pools["npc"][0] == ppo.HEURISTIC and pools["npc"][1].endswith("npc_snap0001.pt")
    assert os.path.exists(os.path.join(out, "pc_latest.pt"))
    # A pool snapshot runs as the opponent of either learner.
    r = _rollout(side="pc", k=5, opponent=pools["npc"][1])
    assert r["steps"] and r["opponent"] == pools["npc"][1]
    print("✅ test_selfplay_alternates_sides_and_grows_pools passed")


if __name__ == "__main__":
    try:
        test_rewards_are_terminal_plus_telescoping_shaping()
        test_gae_matches_its_definition()
        test_sampler_picks_legal_and_is_reproducible()
        test_recorded_logp_survives_batch_padding()
        test_pc_learner_records_only_pc_decisions()
        test_value_only_update_leaves_the_policy()
        test_step6_checkpoint_without_value_head_loads()
        test_heuristic_run_writes_checkpoints_eval_and_traces()
        test_selfplay_alternates_sides_and_grows_pools()
    finally:
        arena.arena().close()
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\nAll ML PPO tests passed! 🎉")
