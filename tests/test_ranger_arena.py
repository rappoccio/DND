#!/usr/bin/env python3
"""Ranger subclasses in the arena (RANGER_SUBCLASSES_PLAN.md R5, D11).

A Beast Master starts an arena fight with its Primal Companion out, in its stored form, on its
side, acting right after it, and the trace records the companion as a spawn; a generated Fey
Wanderer carries Summon Fey as a signature from level 9.
"""

import copy
import os
import shutil
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import rpg_battle_map as rpg
import arena
import party_gen as G
import sim_trace


def _scenario_with(rec: dict) -> arena.Scenario:
    """A generated scenario with its first PC swapped for ``rec`` (same cell, same side)."""
    sc = arena.generate_scenario(4242)
    agents = copy.deepcopy(sc.agents)
    k = next(i for i, a in enumerate(agents) if int(a.get("faction", 0)) == arena.PC_FACTION)
    new = copy.deepcopy(rec)
    for key in ("col", "row", "faction", "on_deck"):
        new[key] = agents[k][key]
    new["name"] = "Test Ranger"
    agents[k] = new
    return arena.Scenario(map=sc.map, terrain=sc.terrain, agents=agents, meta=sc.meta), k


def _companions(bm, ranger: int) -> list:
    return [i for i, pt in enumerate(bm.placed_agents)
            if pt.summoner_idx == ranger and pt.summon_spell == "Primal Companion"]


def test_beast_master_starts_with_its_companion():
    rec = G.build_pc("Ranger.BeastMaster", "ST", 5)
    rec["agent_primal_companion"] = "Sky"
    sc, k = _scenario_with(rec)
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "bm.jsonl")
        out = arena.run_episode(sc, 7, "level4", "Heuristic", trace_path=path)
        assert out["reason"] in ("victory", "round_cap"), out
        bm = arena.arena().app.bm
        comps = _companions(bm, k)
        assert len(comps) == 1, comps
        c = comps[0]
        assert c >= len(sc.agents)
        assert bm.placed_agents[c].faction == arena.PC_FACTION
        assert bm.placed_agents[c].name == "Beast of the Sky", bm.placed_agents[c].name
        assert bm.is_agent_npc_automated(c)
        assert (bm.get_agent_npc_automation_difficulty(c)
                == bm.get_agent_npc_automation_difficulty(k))
        tr = sim_trace.load_trace(path)
        # Recorded as a spawn on the very first turn, like any summon.
        assert [r["name"] for r in tr.turns[0].spawned] == ["Beast of the Sky"], tr.turns[0].spawned
        # It shares the Ranger's count: its first turn comes straight after the Ranger's.
        actors = [t.actor for t in tr.turns]
        first = actors.index(c)
        assert first > 0 and actors[first - 1] == k, actors[:first + 1]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_beast_master_starts_with_its_companion passed")


def test_beast_master_defaults_to_land_and_needs_level_3():
    rec = G.build_pc("Ranger.BeastMaster", "ST", 3)
    rec["agent_primal_companion"] = "NONE"
    sc, k = _scenario_with(rec)
    arena.run_episode(sc, 3, "level4", "Heuristic")
    bm = arena.arena().app.bm
    comps = _companions(bm, k)
    assert len(comps) == 1 and bm.placed_agents[comps[0]].name == "Beast of the Land"

    low = G.build_pc("Ranger.BeastMaster", "ST", 2)
    sc, k = _scenario_with(low)
    arena.run_episode(sc, 3, "level4", "Heuristic")
    assert _companions(arena.arena().app.bm, k) == []
    print("✅ test_beast_master_defaults_to_land_and_needs_level_3 passed")


def test_fey_wanderer_summon_fey_signature_from_level_9():
    hi = G.build_pc("Ranger.FeyWanderer", "CC", 9)
    assert "Summon Fey" in hi["signature_spells"], hi["signature_spells"]
    lo = G.build_pc("Ranger.FeyWanderer", "CC", 7)
    assert "Summon Fey" not in lo["signature_spells"], lo["signature_spells"]
    print("✅ test_fey_wanderer_summon_fey_signature_from_level_9 passed")


if __name__ == "__main__":
    try:
        test_beast_master_starts_with_its_companion()
        test_beast_master_defaults_to_land_and_needs_level_3()
        test_fey_wanderer_summon_fey_signature_from_level_9()
    finally:
        arena.arena().close()
    print("\nAll Ranger arena tests passed! 🎉")
