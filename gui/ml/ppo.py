#!/usr/bin/env python3
"""Reinforcement learning (NPC_LEARNING_PLAN.md Step 7): PPO from the Step 6 weights.

**Rollouts.** Training episodes are arena fights on *train* scenarios. The learning side's
creatures run at Level 5 through a ``Sampler``: each decision draws a candidate (or Defer)
from the model's masked softmax and records the features, the choice, its log-probability,
the critic's value and the reward potential. Every creature on the learning side feeds one
shared trajectory in turn order, so the team shares its reward.

**Reward.** +1 for a win, −1 for a loss, 0 for a draw (the round cap, or a stuck fight), on
the side's last decision. On top of that comes a shaping term, ``shaping × Δφ`` between
consecutive team decisions, where φ = own side's HP share − the other side's HP share
(``arena.side_hp_frac``: HP-weighted, so 10 HP off a 20-HP goblin counts more than off a
200-HP dragon's side). Summed over a fight it telescopes to ``shaping × (φ_end − φ_start)``:
the plan's per-round damage-dealt-minus-taken term, credited to the decision that preceded
each change instead of to round ends.

**Update.** GAE(γ, λ) over the trajectory, then clipped PPO with an entropy bonus and early
stop on approximate KL. The value head is new (BC never trained it), so the first
``value_warmup`` iterations train only the value head and leave the policy untouched.

**Modes** (D5, D11).
  · ``Heuristic``: the NPC side learns against Level 4 PCs (Level 5's teacher).
  · ``SelfPlay``: the sides take turns learning in blocks of ``block`` iterations. At each
    block start the waiting side's current weights join its snapshot pool. Each episode's
    opponent is drawn from that pool, which also holds ``level4`` (the heuristic), so neither
    side overfits to one opponent. The NPC teacher this hardens is Level 6's.

**Evaluation**, every ``eval_every`` iterations: the learner's current weights, run greedily
(``policy.factory``) on *held-out* scenarios with paired seeds against the same fights with
that side at Level 4 (the opponent at Level 4 in both). The Level 4 baseline is computed once
per run and cached. Each evaluated checkpoint is kept, the best by paired win-rate difference
is copied to ``<side>_best.pt``, and the first ``eval_traces`` evaluation fights are saved as
Playback traces under ``traces/it<N>/``.

Run directory (``--out``):
    npc_latest.pt / pc_latest.pt   current weights (rewritten every iteration)
    npc_it<N>.pt / pc_it<N>.pt     each evaluated checkpoint;  <side>_best.pt the best one
    npc_snap<N>.pt / pc_snap<N>.pt SelfPlay pool snapshots;    pool.json the pools
    history.jsonl                  one record per iteration (+ eval results)
    baseline_eval.json             the cached Level 4 evaluation outcomes
    traces/it<N>/*.jsonl           Playback traces of evaluation fights

CLI (in the container):
    python3 gui/ml/ppo.py --init ml_runs/bc.pt --out ml_runs/ppo_h --iterations 200 --jobs 16
    python3 gui/ml/ppo.py --init ml_runs/ppo_h/npc_best.pt --out ml_runs/ppo_sp \\
        --pc-mode SelfPlay --pc-init ml_runs/bc.pt --iterations 400 --jobs 16
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from dataclasses import asdict, dataclass

import numpy as np
import torch

_GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

import arena                          # noqa: E402
from ml import features as F          # noqa: E402
from ml import model as Mdl           # noqa: E402
from ml import policy as P            # noqa: E402

SIDES = ("npc", "pc")
FACTION = {"npc": arena.NPC_FACTION, "pc": arena.PC_FACTION}
OTHER = {"npc": "pc", "pc": "npc"}
HEURISTIC = "level4"                  # a pool entry: that side runs Level 4


@dataclass
class Config:
    episodes_per_iter: int = 64
    gamma: float = 0.99               # per team decision
    lam: float = 0.95
    clip: float = 0.2
    epochs: int = 4
    minibatch: int = 256
    lr: float = 1e-4
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad: float = 0.5
    target_kl: float = 0.03           # stop an update's epochs once approx KL passes 1.5× this
    shaping: float = 0.2              # weight of the HP-share potential term
    value_warmup: int = 1             # first iterations train the value head only
    round_cap: int = arena.ROUND_CAP
    block: int = 10                   # SelfPlay: iterations per side before switching
    eval_every: int = 5
    eval_episodes: int = 200
    eval_seed: int = 101              # base seed of the held-out evaluation fights
    eval_traces: int = 3


# ── Rollouts ────────────────────────────────────────────────────────────────

def potential(bm, faction: int) -> float:
    """φ: the side's HP share minus the other side's."""
    other = arena.PC_FACTION if faction == arena.NPC_FACTION else arena.NPC_FACTION
    return arena.side_hp_frac(bm, faction) - arena.side_hp_frac(bm, other)


class Sampler:
    """The learning side's rank during a rollout. It samples a candidate (or Defer, the last
    column) from the masked softmax with an episode-seeded generator, and records the decision."""

    def __init__(self, net: Mdl.EntityPolicy, faction: int):
        self.net, self.faction = net, faction
        self.steps: list[dict] = []

    def factory(self, eng, bm, seed):
        rng = np.random.default_rng([int(seed) % (2 ** 32), self.faction])

        def rank(idx, archetype, actions):
            if not actions:
                return []
            s = F.featurize(eng, bm, idx, archetype, actions)
            if not s["legal"].any():
                return []          # nothing to choose: the engine falls back whatever we say
            with torch.no_grad():
                logits, value = self.net.forward_value(Mdl.collate([s]))
            logp = torch.log_softmax(logits[0].double(), -1).numpy()
            p = np.exp(logp)
            c = int(rng.choice(len(p), p=p / p.sum()))
            defer = c == len(actions)
            s.update(label=-1 if defer else c, logp=float(logp[c]), value=float(value[0]),
                     phi=potential(bm, self.faction), agent=int(idx))
            self.steps.append(s)
            return [] if defer else [c]
        return rank


def rewards(steps: list[dict], outcome: dict, side: str, shaping: float) -> np.ndarray:
    """Per-decision rewards: shaping × Δφ, plus the terminal ±1 / 0 on the last one."""
    if not steps:
        return np.zeros(0)
    hp = outcome["hp_frac"]
    phi = [s["phi"] for s in steps] + [hp[side] - hp[OTHER[side]]]
    r = shaping * np.diff(np.asarray(phi, dtype=np.float64))
    w = outcome["winner"]
    r[-1] += 1.0 if w == side else -1.0 if w == OTHER[side] else 0.0
    return r


def gae(r: np.ndarray, v: np.ndarray, gamma: float, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """Advantages and returns for one episode's trajectory; the fight ends after the last step."""
    adv = np.zeros(len(r))
    last = 0.0
    for t in reversed(range(len(r))):
        nxt = v[t + 1] if t + 1 < len(r) else 0.0
        last = r[t] + gamma * nxt - v[t] + gamma * lam * last
        adv[t] = last
    return adv, adv + v


def _opponent_kwargs(side: str, opponent: str) -> dict:
    """``run_episode`` keywords for the opponent side: Level 4, or a pool checkpoint (greedy)."""
    heur = opponent == HEURISTIC
    if side == "npc":
        return ({"pc_mode": "Heuristic"} if heur else
                {"pc_mode": "SelfPlay", "pc_policy_factory": P.factory(opponent)})
    return ({"npc_policy": HEURISTIC} if heur else
            {"npc_policy": "ppo", "policy_factory": P.factory(opponent)})


_LEARNER: dict = {}


def _learner_net(path: str, version: int) -> Mdl.EntityPolicy:
    """The learner's weights for this iteration. Keyed by an explicit version, not the file's
    mtime: an inline run rewrites ``<side>_latest.pt`` faster than some clocks tick."""
    key = (path, version)
    if key not in _LEARNER:
        _LEARNER.clear()
        _LEARNER[key] = Mdl.load(path)[0]
    return _LEARNER[key]


def rollout_job(job: dict) -> dict:
    """One training episode for ``job['side']`` with the checkpoint ``job['ckpt']``."""
    side = job["side"]
    sampler = Sampler(_learner_net(job["ckpt"], job["version"]), FACTION[side])
    sc = arena.scenario_for_split(job["base_seed"], job["k"], "train",
                                  maps=job.get("maps"), parties=job.get("parties"))
    seed = job["base_seed"] * 7919 + job["k"]
    # The learner's side runs the sampler (NPCs as "ppo", PCs in SelfPlay); the opponent's
    # side is whatever _opponent_kwargs set.
    kw = {"npc_policy": "ppo", "pc_mode": "SelfPlay"} | _opponent_kwargs(side, job["opponent"])
    kw["policy_factory" if side == "npc" else "pc_policy_factory"] = sampler.factory
    out = arena.run_episode(sc, seed, kw.pop("npc_policy"), kw.pop("pc_mode"),
                            round_cap=job["round_cap"], **kw)
    steps = sampler.steps
    r = rewards(steps, out, side, job["shaping"])
    adv, ret = gae(r, np.array([s["value"] for s in steps]), job["gamma"], job["lam"])
    for s, a, g in zip(steps, adv, ret):
        s["adv"], s["ret"] = float(a), float(g)
        del s["phi"]
    return {"k": job["k"], "steps": steps, "opponent": job["opponent"],
            "winner": out["winner"], "reason": out["reason"], "rounds": out["rounds"],
            "return": float(r.sum()) if len(r) else 0.0}


# ── The update ──────────────────────────────────────────────────────────────

def ppo_update(net: Mdl.EntityPolicy, opt, samples: list[dict], cfg: Config, rng,
               value_only: bool = False, value_opt=None) -> dict:
    """Clipped PPO over ``samples`` (``rollout_job`` steps). ``value_only`` trains the value
    head alone with ``value_opt`` and leaves the policy as it was."""
    net.train()
    adv = np.array([s["adv"] for s in samples])
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    stats = {"pg_loss": [], "v_loss": [], "entropy": [], "kl": [], "clipfrac": []}
    epochs_done = 0
    for _ in range(cfg.epochs):
        order = rng.permutation(len(samples))
        kls = []
        for i in range(0, len(order), cfg.minibatch):
            rows = order[i:i + cfg.minibatch]
            b = Mdl.collate([samples[j] for j in rows])
            old = torch.tensor([samples[j]["logp"] for j in rows], dtype=torch.float32)
            a = torch.tensor(adv[rows], dtype=torch.float32)
            ret = torch.tensor([samples[j]["ret"] for j in rows], dtype=torch.float32)
            logits, v = net.forward_value(b)
            logp_all = torch.log_softmax(logits, -1)
            logp = logp_all.gather(1, b["label"].unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old)
            pg = -torch.min(ratio * a, ratio.clamp(1 - cfg.clip, 1 + cfg.clip) * a).mean()
            v_loss = 0.5 * ((v - ret) ** 2).mean()
            ent = -(logp_all.exp() * logp_all).sum(-1).mean()
            if value_only:
                value_opt.zero_grad()
                (cfg.vf_coef * v_loss).backward()
                torch.nn.utils.clip_grad_norm_(net.value_head.parameters(), cfg.max_grad)
                value_opt.step()
            else:
                loss = pg + cfg.vf_coef * v_loss - cfg.ent_coef * ent
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), cfg.max_grad)
                opt.step()
            with torch.no_grad():
                kl = float((old - logp).mean())
            kls.append(kl)
            stats["pg_loss"].append(float(pg))
            stats["v_loss"].append(float(v_loss))
            stats["entropy"].append(float(ent))
            stats["kl"].append(kl)
            stats["clipfrac"].append(float(((ratio - 1).abs() > cfg.clip).float().mean()))
        epochs_done += 1
        if not value_only and np.mean(kls) > 1.5 * cfg.target_kl:
            break
    net.eval()
    out = {k: round(float(np.mean(v)), 5) for k, v in stats.items() if v}
    out["epochs"] = epochs_done
    return out


# ── Evaluation ──────────────────────────────────────────────────────────────

def _eval_jobs(side: str, ckpt: str | None, cfg: Config, maps, parties, trace_dir=None) -> list:
    """Held-out paired fights: ``side`` greedy on ``ckpt`` (None = Level 4), the other side
    at Level 4."""
    jobs = []
    for k in range(cfg.eval_episodes):
        j = {"base_seed": cfg.eval_seed, "k": k, "split": "heldout", "maps": maps,
             "parties": parties, "npc_policy": HEURISTIC, "pc_mode": "Heuristic",
             "round_cap": cfg.round_cap, "trace_dir": None, "trace_all": False}
        if ckpt and side == "npc":
            j.update(npc_policy="ppo", model=ckpt)
        elif ckpt:
            j.update(pc_mode="SelfPlay", pc_model=ckpt)
        if trace_dir and k < cfg.eval_traces:
            j.update(trace_dir=trace_dir, trace_all=True)
        jobs.append(j)
    return jobs


def paired(base: list[dict], cand: list[dict], side: str) -> dict:
    """``side``'s win rate in ``cand`` vs ``base`` over the same episodes, with a 95% CI on the
    paired difference."""
    b = {o["episode"]: o for o in base}
    c = {o["episode"]: o for o in cand}
    ks = sorted(b.keys() & c.keys())
    wb = np.array([b[k]["winner"] == side for k in ks], dtype=float)
    wc = np.array([c[k]["winner"] == side for k in ks], dtype=float)
    diff = wc - wb
    se = float(diff.std(ddof=1) / np.sqrt(len(ks))) if len(ks) > 1 else float("nan")
    m = float(diff.mean()) if ks else float("nan")
    return {"episodes": len(ks), "level4_win": round(float(wb.mean()), 4) if ks else None,
            "win": round(float(wc.mean()), 4) if ks else None, "diff": round(m, 4),
            "diff_ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)],
            "draws": int(sum(c[k]["winner"] is None for k in ks))}


# ── The training run ────────────────────────────────────────────────────────

def _worker_init():
    torch.set_num_threads(1)
    arena.arena()


class _Runner:
    """Maps a function over jobs, in order: inline (``jobs`` ≤ 1) or on one persistent pool."""

    def __init__(self, jobs: int):
        self.pool = None
        if jobs > 1:
            import multiprocessing as mp
            self.pool = mp.get_context("spawn").Pool(jobs, initializer=_worker_init)

    def map(self, fn, work: list) -> list:
        if self.pool is None:
            return [fn(w) for w in work]
        return self.pool.map(fn, work, chunksize=1)

    def close(self):
        if self.pool is not None:
            self.pool.close()
            self.pool.join()


def _save(net, path: str, **extra) -> None:
    """Write a checkpoint atomically: a worker never reads a half-written file."""
    tmp = path + ".tmp"
    Mdl.save(net, tmp, **extra)
    os.replace(tmp, path)


def train(out: str, init: str, *, iterations: int, cfg: Config | None = None,
          pc_mode: str = "Heuristic", pc_init: str | None = None, jobs: int = 1,
          seed: int = 1, maps=None, parties=None, log=print) -> dict:
    """A PPO run into ``out``. Returns the last iteration's record and each side's best eval."""
    cfg = cfg or Config()
    if pc_mode not in arena.PC_MODES:
        raise ValueError(f"unknown pc_mode {pc_mode!r}")
    os.makedirs(out, exist_ok=True)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    learners = SIDES if pc_mode == "SelfPlay" else ("npc",)
    inits = {"npc": init, "pc": pc_init or init}
    nets, opts, vopts = {}, {}, {}
    for s in learners:
        nets[s] = Mdl.load(inits[s])[0]
        opts[s] = torch.optim.AdamW(nets[s].parameters(), lr=cfg.lr, weight_decay=0.0)
        vopts[s] = torch.optim.AdamW(nets[s].value_head.parameters(), lr=cfg.lr * 10)
    pools = {"npc": [HEURISTIC], "pc": [HEURISTIC]}
    best: dict[str, dict | None] = {s: None for s in learners}
    trained = {s: 0 for s in learners}       # iterations each side has learned for
    with open(os.path.join(out, "config.json"), "w") as f:
        json.dump(asdict(cfg) | {"init": init, "pc_init": pc_init, "pc_mode": pc_mode,
                                 "iterations": iterations, "seed": seed, "jobs": jobs,
                                 "maps": maps, "parties": parties}, f, indent=2)
    runner = _Runner(jobs)
    hist_f = open(os.path.join(out, "history.jsonl"), "a")
    rec: dict = {}
    try:
        baseline = _baseline(out, cfg, maps, parties, runner, log)
        for it in range(iterations):
            t0 = time.perf_counter()
            side = learners[(it // cfg.block) % len(learners)]
            if pc_mode == "SelfPlay" and it % cfg.block == 0:
                # Block start: the waiting side's current weights join its pool.
                other = OTHER[side]
                snap = os.path.join(out, f"{other}_snap{it:04d}.pt")
                _save(nets[other], snap, iteration=it)
                pools[other].append(snap)
                with open(os.path.join(out, "pool.json"), "w") as f:
                    json.dump(pools, f, indent=2)
            net = nets[side]
            ckpt = os.path.join(out, f"{side}_latest.pt")
            _save(net, ckpt, iteration=it)
            opp_rng = random.Random(f"opp:{seed}:{it}")
            work = [{"side": side, "ckpt": ckpt, "version": it, "base_seed": seed,
                     "k": it * cfg.episodes_per_iter + j,
                     "opponent": (opp_rng.choice(pools[OTHER[side]]) if pc_mode == "SelfPlay"
                                  else HEURISTIC),
                     "maps": maps, "parties": parties, "round_cap": cfg.round_cap,
                     "shaping": cfg.shaping, "gamma": cfg.gamma, "lam": cfg.lam}
                    for j in range(cfg.episodes_per_iter)]
            results = runner.map(rollout_job, work)
            t_roll = time.perf_counter()
            samples = [s for r in results for s in r["steps"]]
            if not samples:
                raise RuntimeError(f"iteration {it}: the {side} side made no decisions")
            warm = trained[side] < cfg.value_warmup
            upd = ppo_update(net, opts[side], samples, cfg, rng, value_only=warm,
                             value_opt=vopts[side])
            trained[side] += 1
            _save(net, ckpt, iteration=it + 1)
            n = len(results)
            rec = {"iteration": it + 1, "side": side, "value_only": warm,
                   "episodes": n, "decisions": len(samples),
                   "win": round(sum(r["winner"] == side for r in results) / n, 4),
                   "draw": round(sum(r["winner"] is None for r in results) / n, 4),
                   "return": round(float(np.mean([r["return"] for r in results])), 4),
                   "defer": round(float(np.mean([s["label"] < 0 for s in samples])), 4),
                   **upd, "rollout_s": round(t_roll - t0, 1),
                   "update_s": round(time.perf_counter() - t_roll, 1)}
            if cfg.eval_every and (it + 1) % cfg.eval_every == 0:
                rec["eval"] = _evaluate(out, side, net, it + 1, baseline, cfg, maps, parties,
                                        runner)
                if best[side] is None or rec["eval"]["diff"] > best[side]["diff"]:
                    best[side] = rec["eval"] | {"iteration": it + 1}
                    shutil.copyfile(rec["eval"]["checkpoint"], os.path.join(out, f"{side}_best.pt"))
            hist_f.write(json.dumps(rec) + "\n")
            hist_f.flush()
            log(json.dumps(rec))
    finally:
        hist_f.close()
        runner.close()
    return {"last": rec, "best": best}


def _baseline(out: str, cfg: Config, maps, parties, runner, log) -> list[dict]:
    """Level 4 vs Level 4 on the held-out evaluation fights, cached in the run directory."""
    if not cfg.eval_every:
        return []
    path = os.path.join(out, "baseline_eval.json")
    key = {"eval_seed": cfg.eval_seed, "episodes": cfg.eval_episodes,
           "round_cap": cfg.round_cap, "maps": maps, "parties": parties}
    if os.path.exists(path):
        with open(path) as f:
            d = json.load(f)
        if d.get("key") == key:
            return d["outcomes"]
    t0 = time.perf_counter()
    outs = runner.map(arena._episode_job, _eval_jobs("npc", None, cfg, maps, parties))
    with open(path, "w") as f:
        json.dump({"key": key, "outcomes": outs}, f)
    log(f"Level 4 baseline: {len(outs)} held-out fights in {time.perf_counter() - t0:.0f}s")
    return outs


def _evaluate(out: str, side: str, net, it: int, baseline: list, cfg: Config, maps, parties,
              runner) -> dict:
    ckpt = os.path.join(out, f"{side}_it{it:04d}.pt")
    _save(net, ckpt, iteration=it)
    tdir = os.path.join(out, "traces", f"it{it:04d}") if cfg.eval_traces else None
    if tdir:
        os.makedirs(tdir, exist_ok=True)
    outs = runner.map(arena._episode_job, _eval_jobs(side, ckpt, cfg, maps, parties, tdir))
    return paired(baseline, outs, side) | {"checkpoint": ckpt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PPO from the behaviour-cloned weights (Step 7).")
    ap.add_argument("--init", required=True, help="starting checkpoint (Step 6's bc.pt)")
    ap.add_argument("--out", required=True, help="run directory")
    ap.add_argument("--iterations", type=int, default=100)
    ap.add_argument("--pc-mode", choices=arena.PC_MODES, default="Heuristic")
    ap.add_argument("--pc-init", default=None, help="SelfPlay: the PC side's start (default --init)")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--threads", type=int, default=0, help="torch threads for the update")
    ap.add_argument("--map", action="append", default=None)
    ap.add_argument("--party", action="append", default=None)
    for name, val in asdict(Config()).items():
        ap.add_argument("--" + name.replace("_", "-"), type=type(val), default=val)
    a = ap.parse_args(argv)
    if a.threads:
        torch.set_num_threads(a.threads)
    cfg = Config(**{k: getattr(a, k) for k in asdict(Config())})
    maps = None
    if a.map:
        maps = []
        for m in a.map:
            terr = os.path.splitext(os.path.abspath(m))[0] + "_terrain.json"
            maps.append((arena._rel(m), arena._rel(terr) if os.path.exists(terr) else None))
    parties = [os.path.abspath(p) for p in a.party] if a.party else None
    res = train(os.path.abspath(a.out), os.path.abspath(a.init), iterations=a.iterations,
                cfg=cfg, pc_mode=a.pc_mode,
                pc_init=os.path.abspath(a.pc_init) if a.pc_init else None,
                jobs=a.jobs, seed=a.seed, maps=maps, parties=parties)
    print(json.dumps(res["best"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
