#!/usr/bin/env python3
"""Behaviour cloning of Level 4 (NPC_LEARNING_PLAN.md Step 6, gui/ml/).

The dataset writer records Level 4's labels with arrays that point at the right creatures;
shards read back what was written; the model masks illegal candidates and doesn't care how
a batch is padded; a small model can fit its data; Defer hands the turn to the fallback
chain; and a checkpoint runs as the arena's ``bc`` policy, reproducibly.
"""

import os
import shutil
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import numpy as np
import torch

import rpg_battle_map as rpg
import arena
from ml import dataset as D
from ml import features as F
from ml import model as Mdl
from ml import policy as P
from ml import train as T

_TMP = tempfile.mkdtemp(prefix="ml_bc_")
_DATA = os.path.join(_TMP, "data")
_CKPT = os.path.join(_TMP, "tiny.pt")


def _record(k0=0, k1=3) -> D.Recorder:
    """The dataset writer's recorder over episodes k0..k1-1, in memory."""
    rec = D.Recorder()
    for k in range(k0, k1):
        sc = arena.scenario_for_split(1, k, "any")
        rec.heldout, rec.episode = sc.split == "heldout", k
        arena.run_episode(sc, 7919 + k, "l4-macro", policy_factory=rec.factory)
    return rec


def _data() -> D.Shards:
    if not os.path.isdir(_DATA):
        list(D.write(_DATA, 4, per_shard=2))
    return D.Shards(_DATA)


def _tiny_model() -> str:
    if not os.path.exists(_CKPT):
        torch.manual_seed(0)
        T.train(_data(), _CKPT, epochs=1, batch=64, d=32, layers=1, heads=2, ff=64,
                log=lambda *_: None)
    return _CKPT


# ── Features ─────────────────────────────────────────────────────────────────
def test_featurize_points_at_the_right_creatures():
    """Each candidate's target row is that creature's token, the label is a legal candidate,
    and the shapes match the field lists."""
    seen = []

    def factory(eng, bm, seed):
        def rank(idx, archetype, actions):
            s = F.featurize(eng, bm, idx, archetype, actions)
            obs = eng.get_entity_observation(bm, idx)
            seen.append((s, [a.target_agent for a in actions], list(obs.agent_indices),
                         [int(a.kind) for a in actions], [a.spell_idx for a in actions]))
            return []
        return rank
    sc = arena.scenario_for_split(1, 0, "any")
    arena.run_episode(sc, 11, "l4-macro", policy_factory=factory)
    assert seen, "the policy was never asked"
    for s, targets, rows, kinds, spells in seen:
        assert s["tokens"].shape == (len(rows), F.TOKEN_DIM)
        assert s["map"].shape == (F.MAP_DIM,)
        assert s["cand"].shape == (len(targets), F.CAND_DIM)
        assert s["tokens"][0][F.ENTITY_FIELDS.index("is_self")] == 1.0
        for m, t in enumerate(targets):
            r = s["cand_target"][m]
            assert (r < 0) == (t < 0 or t not in rows)
            if r >= 0:
                assert rows[r] == t
            assert s["cand"][m][kinds[m]] == 1.0 and s["cand"][m][:F.KIND_COUNT].sum() == 1.0
            assert s["cand"][m][F.CAND_FIELDS.index("has_spell")] == float(spells[m] >= 0)
    print("✅ test_featurize_points_at_the_right_creatures passed")


def test_recorder_labels_are_level4s_choice():
    """A stored label is a legal candidate (or Defer); deferred decisions are counted; a
    sample's split is its scenario's."""
    rec = _record(0, 3)
    assert rec.samples
    deferred = 0
    for s in rec.samples:
        if s["label"] == D.DEFER:
            deferred += 1
        else:
            assert s["legal"][s["label"]]
        assert s["legal"].any()
    assert deferred == rec.unlabeled
    splits = {arena.scenario_for_split(1, k, "any").split == "heldout" for k in range(3)}
    assert {s["heldout"] for s in rec.samples} <= splits
    print("✅ test_recorder_labels_are_level4s_choice passed")


def test_shards_read_back_what_was_written():
    d = _data()
    rec = _record(0, 4)                       # the same episodes, recorded again in memory
    assert len(d) == len(rec.samples)
    for i in (0, len(d) // 2, len(d) - 1):
        a, b = d.sample(i), rec.samples[i]
        for key in ("tokens", "map", "cand", "cand_target", "legal"):
            assert np.array_equal(a[key], b[key]), key
        assert a["label"] == b["label"] and a["arch"] == b["arch"]
    assert int(d.heldout.sum()) == sum(s["heldout"] for s in rec.samples)
    print("✅ test_shards_read_back_what_was_written passed")


# ── Model ────────────────────────────────────────────────────────────────────
def test_model_masks_illegal_and_ignores_padding():
    torch.manual_seed(0)
    net = Mdl.EntityPolicy(d=32, layers=2, heads=2, ff=64).eval()
    d = _data()
    small = min(range(len(d)), key=lambda i: (len(d.sample(i)["cand"]), len(d.sample(i)["tokens"])))
    big = max(range(len(d)), key=lambda i: (len(d.sample(i)["cand"]), len(d.sample(i)["tokens"])))
    s, b = d.sample(small), d.sample(big)
    assert len(b["cand"]) > len(s["cand"])
    with torch.no_grad():
        alone = net(Mdl.collate([s]))[0]
        padded = net(Mdl.collate([s, b]))[0]
    m = len(s["cand"])
    assert alone.shape[0] == m + 1 and padded.shape[0] == len(b["cand"]) + 1
    legal = torch.from_numpy(s["legal"])
    assert (alone[:m][~legal] <= Mdl.NEG / 2).all()
    assert torch.allclose(alone[:m][legal], padded[:m][legal], atol=1e-5)
    assert torch.allclose(alone[-1], padded[-1], atol=1e-5)          # Defer
    assert (padded[m:-1] <= Mdl.NEG / 2).all()                        # padding never wins
    print("✅ test_model_masks_illegal_and_ignores_padding passed")


def test_collate_maps_defer_to_the_last_column():
    d = _data()
    i = next(i for i in range(len(d)) if d.label[i] != D.DEFER)
    s, t = d.sample(i), dict(d.sample(i), label=D.DEFER)
    b = Mdl.collate([s, t])
    assert int(b["label"][0]) == s["label"]
    assert int(b["label"][1]) == b["cand"].shape[1]
    print("✅ test_collate_maps_defer_to_the_last_column passed")


def test_a_small_model_fits_its_data():
    """Training lowers the loss: the pipeline learns (the gate itself is a long run)."""
    d = _data()
    rows = np.arange(len(d))
    torch.manual_seed(0)
    before = T.evaluate(Mdl.EntityPolicy(d=32, layers=1, heads=2, ff=64), d, rows)["loss"]
    after = T.evaluate(Mdl.load(_tiny_model())[0], d, rows)["loss"]
    assert after < before, (before, after)
    print(f"✅ test_a_small_model_fits_its_data passed (loss {before} → {after})")


def test_checkpoint_refuses_another_feature_version():
    ck = torch.load(_tiny_model(), weights_only=False)
    ck["feature_version"] = F.FEATURE_VERSION + 1
    bad = os.path.join(_TMP, "bad.pt")
    torch.save(ck, bad)
    try:
        Mdl.load(bad)
    except ValueError as e:
        assert "feature version" in str(e)
    else:
        raise AssertionError("a checkpoint from another feature version loaded")
    print("✅ test_checkpoint_refuses_another_feature_version passed")


# ── Policy ───────────────────────────────────────────────────────────────────
def test_rank_defers_or_orders_legal_candidates():
    legal = np.array([True, False, True, True])
    assert P.rank_from_scores(np.array([0.1, 9.0, 0.5, 0.5, -1.0]), legal) == [2, 3, 0]
    assert P.rank_from_scores(np.array([0.1, 9.0, 0.5, 0.5, 2.0]), legal) == []
    assert P.rank_from_scores(np.array([0.1, 0.0]), np.array([False])) == []
    print("✅ test_rank_defers_or_orders_legal_candidates passed")


def test_bc_policy_runs_and_is_reproducible():
    """``npc_policy='bc'`` installs the checkpoint; NPC turns are Policy decisions; the same
    scenario and seed give the same outcome twice. No model → refused."""
    path = _tiny_model()
    sc = arena.scenario_for_split(5, 0, "heldout")
    calls = []
    base = P.factory(path)

    def counting(eng, bm, seed):
        rank = base(eng, bm, seed)

        def wrapped(idx, archetype, actions):
            out = rank(idx, archetype, actions)
            assert all(actions[i].legal for i in out)
            calls.append(len(out))
            return out
        return wrapped
    a = arena.run_episode(sc, 3, "bc", policy_factory=counting)
    b = arena.run_episode(sc, 3, "bc", model=path)
    c = arena.run_episode(sc, 3, "bc", model=path)
    keep = ("winner", "reason", "rounds", "turns", "standing", "hp_frac")
    assert calls, "the bc policy was never asked"
    assert {k: a[k] for k in keep} == {k: b[k] for k in keep} == {k: c[k] for k in keep}
    assert b["npc_policy"] == "bc"
    try:
        arena.run_episode(sc, 3, "bc")
    except ValueError as e:
        assert "model" in str(e)
    else:
        raise AssertionError("bc without a model ran")
    print("✅ test_bc_policy_runs_and_is_reproducible passed")


if __name__ == "__main__":
    try:
        test_featurize_points_at_the_right_creatures()
        test_recorder_labels_are_level4s_choice()
        test_shards_read_back_what_was_written()
        test_model_masks_illegal_and_ignores_padding()
        test_collate_maps_defer_to_the_last_column()
        test_a_small_model_fits_its_data()
        test_checkpoint_refuses_another_feature_version()
        test_rank_defers_or_orders_legal_candidates()
        test_bc_policy_runs_and_is_reproducible()
    finally:
        arena.arena().close()
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\nAll ML behaviour-cloning tests passed! 🎉")
