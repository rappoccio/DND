#!/usr/bin/env python3
"""Ranger R5 smoke run: each Ranger subclass, swapped into generated scenarios, a few arena
fights each; counts from the traces how often each subclass feature fires."""
import copy, os, re, sys, tempfile, shutil
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gui"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import arena, party_gen as G, sim_trace

BUILDS = [("Ranger.Hunter", "MT", 11), ("Ranger.GloomStalker", "ST", 11),
          ("Ranger.FeyWanderer", "CC", 15), ("Ranger.BeastMaster", "ST", 11), ("Ranger.BeastMaster", "ST", 4)]
PATTERNS = {
    "Dreadful Strike": r"uses Dreadful Strike:",
    "Sudden Strike": r"Sudden Strike — a free attack",
    "Mass Fear": r"Stalker's Flurry — Mass Fear",
    "Horde Breaker": r"Horde Breaker — an extra attack",
    "Companion commanded": r"commands .* \(Bonus Action\)",
    "Beast's Strike": r"Beast's Strike against",
    "Companion Dodge": r"not commanded",
    "Misty Wanderer": r"Misty Wanderer — casts Misty Step",
    "Dreadful Strikes (Fey)": r"Dreadful Strikes: \+",
}
N = int(os.environ.get("N", "8"))
tmp = tempfile.mkdtemp()
for sub, role, lvl in BUILDS:
    counts, outcomes, spawns = Counter(), Counter(), Counter()
    s, done = 0, 0
    while done < N:
        s += 1
        sc = arena.generate_scenario(5000 + s)
        agents = copy.deepcopy(sc.agents)
        pcs = [i for i, a in enumerate(agents) if a["faction"] == arena.PC_FACTION]
        if any(agents[i].get("agent_class") == "Ranger" for i in pcs[1:]):
            continue          # another Ranger in the party would muddy the counts
        done += 1
        k = pcs[0]
        rec = G.build_pc(sub, role, lvl)
        for key in ("col", "row", "faction", "on_deck"):
            rec[key] = agents[k][key]
        rec["name"] = "Smoke Ranger"
        agents[k] = rec
        sc2 = arena.Scenario(sc.map, sc.terrain, agents, sc.meta)
        path = os.path.join(tmp, f"{s}.jsonl")
        out = arena.run_episode(sc2, s, "level4", "Heuristic", trace_path=path)
        outcomes[out["reason"]] += 1
        tr = sim_trace.load_trace(path)
        for t in tr.turns:
            for r in t.spawned:
                spawns[r["name"]] += 1
            for ln in t.log:
                for name, pat in PATTERNS.items():
                    if re.search(pat, ln):
                        counts[name] += 1
    print(f"{sub} L{lvl} ({N} fights, {dict(outcomes)}):")
    print("   features:", dict(counts) or "none")
    print("   spawns:  ", dict(spawns) or "none")
shutil.rmtree(tmp, ignore_errors=True)
arena.arena().close()
