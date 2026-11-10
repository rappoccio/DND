#!/usr/bin/env python3
"""The headless arena (NPC_LEARNING_PLAN.md Step 3, gui/arena.py).

Scenarios are a pure function of their seed and split by content hash; a fight runs to a
result with no human (reaction windows answered by policy); the same scenario and seed give
the same outcome twice; the round cap makes a draw; and an arena trace opens in Playback.
"""

import os
import sys
import json
import shutil
import tempfile
from types import SimpleNamespace

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import rpg_battle_map as rpg
import arena
import playback
import sim_trace
from test_sim_playback import _frame

# Timing fields differ run to run; everything else in an outcome must not.
_TIMING = ("load_s", "fight_s", "wall_s", "trace")


def _stable(outcome: dict) -> dict:
    return {k: v for k, v in outcome.items() if k not in _TIMING}


def _scenarios(n, start=1):
    return [arena.generate_scenario(s) for s in range(start, start + n)]


# ── The XP budget is the SRD's ───────────────────────────────────────────────
def test_xp_budget_rows():
    """Spot rows of SRD 5.2's "XP Budget per Character" (Low, Moderate, High)."""
    assert arena.XP_BUDGET[1] == (50, 75, 100)
    assert arena.XP_BUDGET[3] == (150, 225, 400)
    assert arena.XP_BUDGET[9] == (1300, 2000, 2600)
    assert arena.XP_BUDGET[20] == (6400, 13200, 22000)
    assert sorted(arena.XP_BUDGET) == list(range(1, 21))
    print("✅ test_xp_budget_rows passed")


# ── Scenarios ────────────────────────────────────────────────────────────────
def test_scenario_is_a_function_of_its_seed():
    a, b = arena.generate_scenario(7), arena.generate_scenario(7)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    assert arena.generate_scenario(8).hash != a.hash
    # The hash is the content's, so a round trip through a file keeps it (and the split).
    back = arena.Scenario.from_dict(json.loads(json.dumps(a.to_dict())))
    assert back.hash == a.hash and back.split == a.split
    print("✅ test_scenario_is_a_function_of_its_seed passed")


def test_split_is_by_content_hash():
    scs = _scenarios(40)
    splits = {sc.split for sc in scs}
    assert splits == {"train", "heldout"}, f"40 scenarios landed in {splits}"
    for sc in scs:
        assert sc.split == ("heldout" if int(sc.hash[:8], 16) % arena.HELDOUT_MOD == 0
                            else "train")
    # scenario_for_split only hands out the asked-for split.
    for k in range(6):
        assert arena.scenario_for_split(3, k, "heldout").split == "heldout"
        assert arena.scenario_for_split(3, k, "train").split == "train"
    print("✅ test_split_is_by_content_hash passed")


def test_scenario_placement_and_budget():
    """Party on the PC side and mobs on the other, every footprint passable and disjoint,
    the mobs inside the encounter's XP budget, and the whole roster loads index for index."""
    ar = arena.arena()
    for sc in _scenarios(12, start=100):
        pcs = [a for a in sc.agents if a["faction"] == arena.PC_FACTION]
        mobs = [a for a in sc.agents if a["faction"] == arena.NPC_FACTION]
        assert pcs and mobs and len(pcs) + len(mobs) == len(sc.agents)
        assert len(pcs) <= arena.PARTY_SIZE
        assert sc.meta["xp_spent"] <= sc.meta["xp_budget"], sc.meta
        assert sc.meta["difficulty"] in arena.DIFFICULTIES
        assert len({a["name"] for a in sc.agents}) == len(sc.agents), "names must be unique"
        bm, _ = ar.load_board(sc.map, sc.terrain, 0)
        taken = set()
        for a in sc.agents:
            s = int(a["size"])
            assert arena._passable(bm, a["col"], a["row"], s), (sc.map, a["name"])
            foot = {(a["col"] + i, a["row"] + j) for i in range(s) for j in range(s)}
            assert not foot & taken, f"{a['name']} overlaps another creature"
            taken |= foot
        ar.load_agents(sc.agents)
        assert [pt.name for pt in ar.app.bm.placed_agents] == [a["name"] for a in sc.agents]
    print("✅ test_scenario_placement_and_budget passed")


# ── Reactions ────────────────────────────────────────────────────────────────
def _opt(kind, feature=""):
    return SimpleNamespace(kind=kind, feature=feature)


def test_auto_reaction_takes_what_is_offered():
    K = rpg.ReactionOptionKind
    ctx = SimpleNamespace(source_idx=-1, options=[_opt(K.Weapon), _opt(K.Skip)])
    assert arena.auto_reaction(None, ctx).option == 0
    ctx = SimpleNamespace(source_idx=-1, options=[_opt(K.Skip), _opt(K.Feature, "Shield")])
    assert arena.auto_reaction(None, ctx).option == 1
    ctx = SimpleNamespace(source_idx=-1, options=[_opt(K.Skip)])
    assert arena.auto_reaction(None, ctx).option == 0
    # Vitality of the Tree with nobody in reach is passed over, never submitted targetless.
    bm = SimpleNamespace(placed_agents=[])
    ctx = SimpleNamespace(source_idx=0, options=[_opt(K.Feature, "VitalityOfTheTree"),
                                                 _opt(K.Skip)])
    assert arena.auto_reaction(bm, ctx).option == 1
    print("✅ test_auto_reaction_takes_what_is_offered passed")


# ── Episodes ─────────────────────────────────────────────────────────────────
def test_episodes_run_to_a_result():
    """Every fight ends (victory or the cap), never stuck on a reaction window; somebody
    reacts somewhere, so the windows really are answered."""
    outs = [arena.run_episode(sc, 1000 + i) for i, sc in enumerate(_scenarios(12, start=200))]
    reacted = 0
    for o in outs:
        assert o["reason"] in ("victory", "round_cap"), o
        assert o["turns"] > 0 and 1 <= o["rounds"] <= arena.ROUND_CAP
        if o["reason"] == "victory":
            assert o["winner"] in ("pc", "npc")
            loser = "npc" if o["winner"] == "pc" else "pc"
            assert o["standing"][loser] == 0 and o["standing"][o["winner"]] > 0
        else:
            assert o["winner"] is None
        reacted += o["reactions"]
    assert any(o["reason"] == "victory" for o in outs)
    assert reacted > 0, "no reaction window was ever answered in 12 fights"
    print(f"✅ test_episodes_run_to_a_result passed "
          f"({sum(o['winner'] == 'npc' for o in outs)} npc / "
          f"{sum(o['winner'] == 'pc' for o in outs)} pc / {reacted} reactions)")


def test_same_scenario_and_seed_same_outcome():
    """The plan's Step 3 test: a fixed scenario + seed gives an identical outcome twice —
    and the identical event stream, turn for turn."""
    sc = arena.generate_scenario(4242)
    tmp = tempfile.mkdtemp()
    try:
        runs = []
        for k in range(2):
            path = os.path.join(tmp, f"t{k}.jsonl")
            out = arena.run_episode(sc, 99, "level4", "Heuristic", trace_path=path)
            tr = sim_trace.load_trace(path)
            runs.append((_stable(out), [(t.actor, [tuple(vars(e).values()) for e in t.events],
                                         t.log) for t in tr.turns]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert runs[0][0] == runs[1][0], f"{runs[0][0]}\n!=\n{runs[1][0]}"
    assert runs[0][1] == runs[1][1], "the event stream differs between identical runs"
    print("✅ test_same_scenario_and_seed_same_outcome passed")


def test_automated_pcs_pay_for_their_spells():
    """An automated PC pays a slot for every leveled spell (combat_turn.cpp npcCastSlotLevel).
    This fight's Warlock has only 5th-level pact slots; the driver used to charge Command's
    own level, which had none, so she cast it every round for free (18 times in 20 rounds)."""
    ar = arena.arena()
    sc = arena.scenario_for_split(3, 0, "train")
    ar.load_board(sc.map, sc.terrain, 0)
    ar.load_agents(sc.agents)
    bm, eng = ar.app.bm, ar.app.combat
    budget, leveled = {}, {}
    for i, pt in enumerate(bm.placed_agents):
        st = eng.get_agent_stats(bm, i)
        if st.is_npc:
            continue
        budget[pt.name] = sum(st.spell_slots_remaining)
        leveled[pt.name] = {sp.name for sp in eng.get_agent_spells(bm, i)
                            if sp.level > 0 and not sp.resource_name}
    assert any(budget.values()), "the fixture party has no casters"
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "t.jsonl")
        ar.run_episode(sc, 23757, trace_path=path)
        lines = [ln for t in sim_trace.load_trace(path).turns for ln in t.log]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for name, spells in leveled.items():
        casts = sum(1 for ln in lines for sp in spells
                    if ln.startswith(f"NPC {name} ") and f"casts {sp}" in ln)
        assert casts <= budget[name], f"{name} cast {casts} leveled spells on {budget[name]} slots"
    print("✅ test_automated_pcs_pay_for_their_spells passed")


def test_round_cap_is_a_draw():
    sc = arena.generate_scenario(4242)
    o = arena.run_episode(sc, 99, round_cap=1)
    if o["reason"] == "victory":                # decided inside round one
        assert o["rounds"] == 1 and o["winner"] in ("pc", "npc")
    else:
        assert o["reason"] == "round_cap" and o["winner"] is None and o["rounds"] == 1
    print("✅ test_round_cap_is_a_draw passed")


def test_policy_and_mode_are_applied_and_checked():
    # The tracked party: no signature spells, so Heuristic PCs are plain Level 4.
    sc = arena.generate_scenario(4242, parties=["maps/TestDNDMap_agents.json"])
    o = arena.run_episode(sc, 5, "level1", "Heuristic")
    assert o["npc_policy"] == "level1" and o["pc_mode"] == "Heuristic" and o["pc_policy"] == "level4"
    ar = arena.arena()
    bm = ar.app.bm

    def levels(pc_want):
        for i, pt in enumerate(bm.placed_agents):
            if i >= len(sc.agents):
                break                          # a summon placed mid-fight
            assert bm.is_agent_npc_automated(i)
            want = 1 if pt.faction == arena.NPC_FACTION else pc_want
            assert bm.get_agent_npc_automation_difficulty(i) == want, pt.name
    levels(arena.PC_HEURISTIC_LEVEL)

    # SelfPlay (Step 7): the PCs run at Level 5 and only PC decisions reach the PC policy.
    asked = []

    def pc_factory(eng, bm_, seed):
        def rank(idx, archetype, actions):
            asked.append(bm_.placed_agents[idx].faction)
            return [i for i, a in enumerate(actions) if a.legal][:1]
        return rank
    o = arena.run_episode(sc, 5, "level1", "SelfPlay", pc_policy_factory=pc_factory)
    assert o["pc_mode"] == "SelfPlay" and o["pc_policy"] == "policy"
    assert asked and set(asked) == {arena.PC_FACTION}
    bm = ar.app.bm
    levels(arena.PC_POLICY_LEVEL)

    bad_calls = [(("level9", "Heuristic"), {}), (("level4", "Human"), {}),
                 (("level4", "SelfPlay"), {}),                       # SelfPlay with no PC policy
                 (("level4", "Heuristic"), {"pc_policy_factory": pc_factory}),
                 (("ppo", "Heuristic"), {})]                         # a model policy, no model
    for args, kw in bad_calls:
        try:
            arena.run_episode(sc, 5, *args, **kw)
            assert False, f"{args} {kw} accepted"
        except ValueError:
            pass
    print("✅ test_policy_and_mode_are_applied_and_checked passed")


def test_trace_sampling_is_seeded_one_in_ten():
    kept = [s for s in range(2000) if arena.keep_trace(s)]
    assert kept == [s for s in range(2000) if arena.keep_trace(s)]
    assert 140 <= len(kept) <= 260, len(kept)
    print("✅ test_trace_sampling_is_seeded_one_in_ten passed")


def test_arena_trace_opens_in_playback():
    """An arena trace is a Step 1 trace: Playback opens it, every turn's snapshot seeds the
    board, and leaving puts the loader's own board back."""
    ar = arena.arena()
    sc = arena.generate_scenario(4242)
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "arena.jsonl")
        out = ar.run_episode(sc, 99, trace_path=path)
        tr = sim_trace.load_trace(path)
        assert tr.complete and tr.footer["reason"] == out["reason"]
        assert tr.header["arena"] and tr.header["scenario_hash"] == sc.hash
        # The party makeup: every PC, by name, with a class and a level.
        pcs = [a["name"] for a in sc.agents if a["faction"] == arena.PC_FACTION]
        assert [p["name"] for p in tr.header["party"]] == pcs
        assert all(p["class"] and 1 <= p["level"] <= 20 for p in tr.header["party"])
        assert tr.header["party"] == sc.meta["party"]
        assert tr.header["scenario"]["difficulty"] == sc.meta["difficulty"]
        turns = playback.playable_turns(tr)
        # The panel's outcome line reads the arena's footer: a side, and rounds played.
        text = playback.outcome_text(tr)
        assert text.endswith(f"ended in round {out['rounds']}"), text
        assert ({"pc": "PCs won", "npc": "NPCs won"}.get(out["winner"], "no winner")) in text
        assert len(turns) == out["turns"]
        app = ar.app
        bm0 = app.bm
        pb = playback.enter(app, path)
        assert pb is not None, "Playback refused an arena trace"
        assert len(app.bm.placed_agents) == len(playback.roster(tr))
        # The HUD's party box: a title naming the fight, one row per PC, the actor marked.
        rows = pb.party_lines()
        assert rows[0][1] == "title" and sc.meta["difficulty"] in rows[0][0]
        assert [r[0].split(" — ")[0] for r in rows[1:]] == pcs
        pc_turn = next(i for i, t in enumerate(turns) if t.actor_name in pcs)
        pb.goto(pc_turn)
        assert "actor" in {st for _, st in pb.party_lines()}
        for k in range(len(turns) + 1):
            pb.goto(k)
        pb.goto(pc_turn)
        frame = _frame(app, pb, os.environ.get("ARENA_HUD_PNG")      # a look: ARENA_HUD_PNG=x.png
                       or os.path.join(tmp, "hud.png"))
        assert os.path.getsize(frame) > 0
        pb.exit()
        assert app.playback is None and app.bm is bm0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_arena_trace_opens_in_playback passed")


def test_cli_batch_writes_outcomes():
    tmp = tempfile.mkdtemp()
    cwd = os.getcwd()
    try:
        out = os.path.join(tmp, "o.jsonl")
        tdir = os.path.join(tmp, "traces")
        assert arena.main(["run", "--episodes", "4", "--seed", "3", "--out", out,
                           "--trace-dir", tdir, "--trace-all"]) == 0
        rows = [json.loads(ln) for ln in open(out)]
        assert [r["episode"] for r in rows] == [0, 1, 2, 3]
        assert all(r["split"] == "train" for r in rows)
        assert len(os.listdir(tdir)) == 4
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_cli_batch_writes_outcomes passed")


if __name__ == "__main__":
    test_xp_budget_rows()
    test_scenario_is_a_function_of_its_seed()
    test_split_is_by_content_hash()
    test_scenario_placement_and_budget()
    test_auto_reaction_takes_what_is_offered()
    test_episodes_run_to_a_result()
    test_same_scenario_and_seed_same_outcome()
    test_automated_pcs_pay_for_their_spells()
    test_round_cap_is_a_draw()
    test_policy_and_mode_are_applied_and_checked()
    test_trace_sampling_is_seeded_one_in_ten()
    test_arena_trace_opens_in_playback()
    test_cli_batch_writes_outcomes()
    arena.arena().close()
    print("\nAll arena tests passed! 🎉")
