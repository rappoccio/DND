#!/usr/bin/env python3
"""Headless arena: whole fights with no human and no window (NPC_LEARNING_PLAN.md Step 3).

    run_episode(scenario, seed, npc_policy, pc_mode) -> outcome dict (+ an optional trace)

A **scenario** is a party (saved PCs) against a mob mix drawn from the bestiary by the SRD
5.2 XP budget, placed on a map from ``maps/``. Train and held-out scenarios are split by a
hash of the scenario's content, never by the combat seed, so a held-out fight is one the
policy has never seen under any seed.

How a fight runs. The board is built by a headless ``App`` used **only as a loader**
(``_load_map_png`` / ``_load_terrain`` / ``_load_agents``, the GUI's full-fidelity paths:
spells, class features, armor, NPC spell groups). The fight itself is an engine-only loop
that mirrors the GUI's turn chain (``_proceed_to_new_turn`` → ``_finish_turn_start`` →
``_drive_npc_turn_if_pending`` → ``_advance_turn``) with every creature automated:

  · both sides are driven by ``run_npc_turn``: the NPCs at ``npc_policy``'s level, the PCs at
    Level 4 (``pc_mode`` ``Heuristic``) or, in ``SelfPlay``, at Level 5 through a learned PC
    policy (``pc_model`` / ``pc_policy_factory``, Step 7);
  · a parked reaction window (``AwaitingDecision``) is answered by ``auto_reaction``, the
    side's policy: Level 4 rules take any reaction the engine offers. Episodes never block.

Not modelled (GUI-only, human-driven today): legendary actions, Keeper of Souls, Tides of
Chaos on initiative, Thief's Reflexes' extra first-round turn. Fights end when one side has
no creature standing, or as a draw at the round cap.

CLI (in the container; see ``--help``):
    python3 gui/arena.py run   --episodes 200 --jobs 4 --out arena_runs/l4.jsonl
    python3 gui/arena.py bench --episodes 20 --jobs 1
"""

from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field

_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_GUI_DIR)
for _p in (_GUI_DIR, os.path.join(_REPO, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import party_gen                     # noqa: E402
import rpg_battle_map as rpg          # noqa: E402
import sim_trace                      # noqa: E402
import xp                             # noqa: E402

PC_FACTION, NPC_FACTION = 2, 1        # the GUI's convention (encounter_generator, saves)
SIDES = {PC_FACTION: "pc", NPC_FACTION: "npc"}

NPC_POLICIES = {"level1": 1, "level2": 2, "level3": 3, "level4": 4,
                # Python-driven macro-action policies (Step 5), run at Level 5 through set_npc_policy.
                "l4-macro": 5, "random-macro": 5,
                # Step 6: a trained gui/ml checkpoint (``model=`` / ``--model``), run greedily.
                "bc": 5,
                # Step 7: a PPO checkpoint; the same as "bc" (greedy) unless a trainer installs its
                # own sampling factory. The name is what the outcome records.
                "ppo": 5}
MODEL_POLICIES = ("bc", "ppo")       # NPC policies that run a gui/ml checkpoint
PC_MODES = ("Heuristic", "SelfPlay")
PC_HEURISTIC_LEVEL = 4
PC_POLICY_LEVEL = 5                   # SelfPlay: PCs ask the installed policy (Step 7)
ROUND_CAP = 20                        # a fight still going after this many rounds is a draw
TRACE_SAMPLE = 10                     # D13: arena episodes keep a trace 1 time in 10 (seeded)
HELDOUT_MOD = 5                       # 1 scenario in 5 is held out (by content hash)
PARTY_SIZE = 4
GENERATED = "generated"               # party source: PCs built by party_gen (Step 3b)
GENERATED_SHARE = 0.8                 # B13: its share of draws when other sources are in the pool
MAX_PARKS_PER_TURN = 64               # a reaction loop this long is an engine bug, not a fight

# SRD 5.2 "XP Budget per Character" (SRD_CC_v5.2.pdf p.201-202): level -> (Low, Moderate, High).
XP_BUDGET = {
    1: (50, 75, 100), 2: (100, 150, 200), 3: (150, 225, 400), 4: (250, 375, 500),
    5: (500, 750, 1100), 6: (600, 1000, 1400), 7: (750, 1300, 1700), 8: (1000, 1700, 2100),
    9: (1300, 2000, 2600), 10: (1600, 2300, 3100), 11: (1900, 2900, 4100),
    12: (2200, 3700, 4700), 13: (2600, 4200, 5400), 14: (2900, 4900, 6200),
    15: (3300, 5400, 7800), 16: (3800, 6100, 9800), 17: (4500, 7200, 11700),
    18: (5000, 8700, 14200), 19: (5500, 10700, 17200), 20: (6400, 13200, 22000),
}
DIFFICULTIES = ("Low", "Moderate", "High")

# Mob mixes by role (melee / ranged / caster, the engine's NpcRole split; Step 4 refines it
# into archetypes). A slot's role is drawn from the mix's weights.
MOB_MIXES = {
    "melee":  {"melee": 1.0},
    "ranged": {"ranged": 0.7, "melee": 0.3},
    "caster": {"caster": 0.6, "melee": 0.4},
    "mixed":  {"melee": 0.4, "ranged": 0.3, "caster": 0.3},
}
MOB_COUNTS = (1, 2, 3, 4, 5, 6, 8)
MOB_COUNT_WEIGHTS = (1, 2, 3, 3, 2, 2, 1)

# Placement: the mob group's anchor sits this many cells' walk from the party's.
ANCHOR_DIST = (6, 12)


# ── Scenarios ───────────────────────────────────────────────────────────────

@dataclass
class Scenario:
    map: str                          # repo-relative PNG path
    terrain: str | None               # repo-relative terrain JSON, or None
    agents: list                      # agent records, save format, placed (col/row set)
    meta: dict = field(default_factory=dict)

    @property
    def hash(self) -> str:
        """Content hash: map, terrain, and each creature's name, side and cell. The seed
        that generated it is not part of it, so two seeds landing on the same fight agree."""
        key = {"map": self.map, "terrain": self.terrain,
               "agents": [[a["name"], int(a.get("faction", 0)), int(a["col"]), int(a["row"])]
                          for a in self.agents]}
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()

    @property
    def split(self) -> str:
        return "heldout" if int(self.hash[:8], 16) % HELDOUT_MOD == 0 else "train"

    def to_dict(self) -> dict:
        return asdict(self) | {"hash": self.hash, "split": self.split}

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        return cls(map=d["map"], terrain=d.get("terrain"), agents=d["agents"],
                   meta=d.get("meta", {}))


def _rel(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), _REPO)


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_REPO, path)


def _is_npc(t: dict) -> bool:
    """A saved agent's NPC flag (main.App._saved_is_npc)."""
    sd = t.get("stats") or {}
    return bool(sd["is_npc"] if "is_npc" in sd else t.get("is_npc", False))


def load_party_source(path: str) -> list[dict]:
    """The PCs in a party source: an agents file (its non-NPC agents on the PC side), a
    single-PC file, or a campaign ``pcs/`` directory of single-PC files. Sorted by name."""
    path = _abs(path)
    records = []
    files = sorted(glob.glob(os.path.join(path, "*.json"))) if os.path.isdir(path) else [path]
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        records.extend(d.get("agents", []) if "agents" in d else [d])
    pcs = [r for r in records
           if not _is_npc(r) and int(r.get("faction", PC_FACTION)) == PC_FACTION]
    return sorted(pcs, key=lambda r: r["name"])


def default_party_sources() -> list[str]:
    """Generated parties (Step 3b) and the tracked party, the PCs in
    ``maps/TestDNDMap_agents.json``; ``pick_party_source`` draws them 80 / 20."""
    return [GENERATED, "maps/TestDNDMap_agents.json"]


def pick_party_source(rng: random.Random, parties: list[str]) -> str:
    """``generated`` takes GENERATED_SHARE of the draws when the pool has other sources too
    (B13); a pool without it is drawn uniformly, as before."""
    if GENERATED in parties and len(parties) > 1:
        if rng.random() < GENERATED_SHARE:
            return GENERATED
        return rng.choice([p for p in parties if p != GENERATED])
    return rng.choice(parties)


def default_maps() -> list[tuple[str, str | None]]:
    """Every ``maps/*.png`` big enough for a fight, with its ``_terrain.json`` if any."""
    out = []
    for png in sorted(glob.glob(os.path.join(_REPO, "maps", "*.png"))):
        terr = os.path.splitext(png)[0] + "_terrain.json"
        out.append((_rel(png), _rel(terr) if os.path.exists(terr) else None))
    return out


_char_level = sim_trace.char_level
party_makeup = sim_trace.party_makeup


def _mob_role(rec: dict, has_ranged) -> str:
    if rec.get("spell_indices"):
        return "caster"
    return "ranged" if has_ranged(rec) else "melee"


def _weighted(rng: random.Random, weights: dict) -> str:
    keys = sorted(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


class MobPool:
    """The bestiary as fightable candidates: name -> (xp, role), sorted for determinism."""

    def __init__(self):
        from encounter_generator import Bestiary, make_agent
        self._make_agent = make_agent
        self.bestiary = Bestiary(_GUI_DIR)
        self.entries = []                         # (xp, name, role)
        for name in sorted(self.bestiary.mobs):
            rec = self.bestiary.mobs[name]
            if not rec.get("stats"):
                continue
            if not (rec.get("weapons") or rec.get("spell_indices")):
                continue
            mxp = xp.cr_to_xp((rec.get("meta") or {}).get("cr"))
            if mxp <= 0:
                continue
            self.entries.append((mxp, name, _mob_role(rec, self.bestiary.has_ranged)))
        self.entries.sort()

    def pick(self, rng: random.Random, xp_cap: float, role: str) -> str | None:
        """A monster worth at most ``xp_cap``, preferring the top of what fits (at least
        40% of the cap) and the requested role; any role if that role has nothing."""
        fits = [e for e in self.entries if e[0] <= xp_cap]
        if not fits:
            return None
        for want in (role, None):
            pool = [e for e in fits if want is None or e[2] == want]
            if not pool:
                continue
            top = [e for e in pool if e[0] >= 0.4 * xp_cap] or \
                  [e for e in pool if e[0] == pool[-1][0]]
            return rng.choice(top)[1]
        return None

    def agent(self, name: str) -> dict:
        a = self._make_agent(self.bestiary.mobs[name], 0, NPC_FACTION, 4)
        a["on_deck"] = False
        return a


def _passable(bm, c: int, r: int, size: int) -> bool:
    if c < 0 or r < 0 or c + size > bm.grid_cols or r + size > bm.grid_rows:
        return False
    return not bm.is_blocked(rpg.Cell(c, r), size)


def _largest_region(bm) -> list[tuple[int, int]]:
    """The largest 4-connected set of passable cells, in BFS order from its first cell."""
    seen, best = set(), []
    for r in range(bm.grid_rows):
        for c in range(bm.grid_cols):
            if (c, r) in seen or not _passable(bm, c, r, 1):
                continue
            comp, q = [], deque([(c, r)])
            seen.add((c, r))
            while q:
                cc, rr = q.popleft()
                comp.append((cc, rr))
                for nc, nr in ((cc + 1, rr), (cc - 1, rr), (cc, rr + 1), (cc, rr - 1)):
                    if (nc, nr) not in seen and _passable(bm, nc, nr, 1):
                        seen.add((nc, nr))
                        q.append((nc, nr))
            if len(comp) > len(best):
                best = comp
    return best


def _bfs_dist(bm, start, region: set) -> dict:
    dist, q = {start: 0}, deque([start])
    while q:
        c, r = q.popleft()
        for n in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
            if n in region and n not in dist:
                dist[n] = dist[(c, r)] + 1
                q.append(n)
    return dist


def _place_group(bm, agents: list, anchor, region: set, occupied: set) -> list:
    """Give each agent the nearest free cell (walk order from ``anchor``) whose footprint
    is passable and unoccupied. Returns the agents placed; one that fits nowhere is dropped."""
    order = sorted(_bfs_dist(bm, anchor, region).items(), key=lambda kv: (kv[1], kv[0]))
    placed = []
    for a in agents:
        size = int(a.get("size", 1))
        for (c, r), _ in order:
            foot = {(c + dc, r + dr) for dc in range(size) for dr in range(size)}
            if foot & occupied or not _passable(bm, c, r, size):
                continue
            a["col"], a["row"] = c, r
            occupied |= foot
            placed.append(a)
            break
    return placed


# ── The loader: a headless App, used only to build boards ───────────────────

class Arena:
    """One per process. Holds the headless App whose loaders build each episode's board."""

    def __init__(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ["RPG_AUTOSAVE"] = "0"
        from main import App
        # The App points its session sidecar next to its map, so it is built on a private
        # copy of a tiny map. Scenario maps are only ever read.
        self._tmp = tempfile.mkdtemp(prefix="arena_")
        base = os.path.join(self._tmp, "arena_base.png")
        shutil.copy(os.path.join(_GUI_DIR, "TestGrid12x12.png"), base)
        # The engine and the App load their data JSONs relative to the working directory,
        # as the test runner arranges: an Arena process works from gui/ for good.
        os.chdir(_GUI_DIR)
        self.app = App(base, seed=0)
        self.app.autosave_enabled = False
        rpg.set_battlemap_verbose(False)          # no per-board / per-turn console chatter
        self._mobs: MobPool | None = None
        self._parties: dict[str, list] = {}

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    @property
    def mobs(self) -> MobPool:
        if self._mobs is None:
            self._mobs = MobPool()
        return self._mobs

    def _party(self, source: str) -> list:
        if source not in self._parties:
            self._parties[source] = load_party_source(source)
        return self._parties[source]

    def load_board(self, map_path: str, terrain: str | None, seed: int):
        """Fresh ``bm`` and a bare ``CombatEngine(seed)`` (no RecordingCombat: nothing is
        written to the checked replay log) with its own logger, on the loader App."""
        app = self.app
        app._load_map_png(_abs(map_path))
        if terrain:
            app._load_terrain(_abs(terrain))
        app.combat = rpg.CombatEngine(int(seed) % (2 ** 32))
        app.logger = rpg.MessageLogger()
        app.combat.set_logger(app.logger)
        return app.bm, app.combat

    def load_agents(self, agents: list) -> None:
        tmp = os.path.join(self._tmp, "episode_agents.json")
        with open(tmp, "w") as f:
            json.dump({"agents": agents}, f)
        self.app._load_agents(tmp)
        if len(self.app.bm.placed_agents) != len(agents):
            raise RuntimeError(f"board placed {len(self.app.bm.placed_agents)} of "
                               f"{len(agents)} agents (a blocked start cell?)")

    # ── scenario generator ──
    def generate_scenario(self, scenario_seed: int, *, maps=None, parties=None,
                          party_size: int = PARTY_SIZE) -> Scenario:
        """One scenario, a pure function of ``scenario_seed`` and the pools."""
        rng = random.Random(scenario_seed)
        maps = list(maps or default_maps())
        parties = list(parties or default_party_sources())
        map_path, terrain = rng.choice(maps)
        source = pick_party_source(rng, parties)
        generated = None
        if source == GENERATED:
            party, generated = party_gen.generate_party(rng.randrange(2 ** 31))
        else:
            pool = self._party(source)
            if not pool:
                raise ValueError(f"no PCs in party source {source}")
            party = [copy.deepcopy(p) for p in
                     (rng.sample(pool, party_size) if len(pool) > party_size else pool)]
        level = round(sum(_char_level(p) for p in party) / len(party))
        difficulty = rng.choice(DIFFICULTIES)
        budget = XP_BUDGET[level][DIFFICULTIES.index(difficulty)] * len(party)
        mix = rng.choice(sorted(MOB_MIXES))
        count = rng.choices(MOB_COUNTS, weights=MOB_COUNT_WEIGHTS)[0]

        mobs, remaining = [], float(budget)
        for slot in range(count):
            name = self.mobs.pick(rng, remaining / (count - slot), _weighted(rng, MOB_MIXES[mix]))
            if name is None:
                break
            mobs.append(name)
            remaining -= xp.cr_to_xp(self.mobs.bestiary.mobs[name]["meta"]["cr"])
        if not mobs:                       # the budget buys nothing at its per-slot share
            name = self.mobs.pick(rng, budget, "melee")
            mobs = [name] if name else []

        bm, _ = self.load_board(map_path, terrain, 0)
        region_list = _largest_region(bm)
        if not region_list:
            raise ValueError(f"{map_path}: no passable cells")
        region = set(region_list)
        pc_anchor = rng.choice(region_list)
        dist = _bfs_dist(bm, pc_anchor, region)
        lo, hi = ANCHOR_DIST
        ring = sorted(c for c, d in dist.items() if lo <= d <= hi)
        mob_anchor = rng.choice(ring) if ring else max(dist, key=lambda c: (dist[c], c))

        occupied: set = set()
        for p in party:
            p["faction"] = PC_FACTION
            p["on_deck"] = False
        party = _place_group(bm, party, pc_anchor, region, occupied)
        mob_agents = _place_group(bm, [self.mobs.agent(n) for n in mobs], mob_anchor,
                                  region, occupied)
        _unique_names(party + mob_agents)
        spent = sum(xp.cr_to_xp(self.mobs.bestiary.mobs[a["base_name"]]["meta"]["cr"])
                    for a in mob_agents)
        for a in mob_agents:
            a.pop("base_name", None)
        for a in party:
            a.pop("base_name", None)
        meta = {"scenario_seed": int(scenario_seed), "party_source": source,
                "party": party_makeup(party),
                "party_level": level, "difficulty": difficulty, "xp_budget": budget,
                "xp_spent": spent, "mob_mix": mix, "mobs": [a["name"] for a in mob_agents]}
        if generated:
            meta["generated_party"] = generated
        return Scenario(map=map_path, terrain=terrain, agents=party + mob_agents, meta=meta)

    # ── one fight ──
    def run_episode(self, scenario: Scenario, seed: int, npc_policy: str = "level4",
                    pc_mode: str = "Heuristic", *, trace_path: str | None = None,
                    round_cap: int = ROUND_CAP, model: str | None = None,
                    policy_factory=None, pc_model: str | None = None,
                    pc_policy_factory=None) -> dict:
        """``model``: the checkpoint a ``bc`` / ``ppo`` policy runs. ``policy_factory``: a
        factory (engine, battle map, seed) -> rank installed in place of ``npc_policy``'s own;
        the name still sets the NPCs' level and is what the outcome records.

        ``SelfPlay`` needs a PC policy: ``pc_model`` (a checkpoint, run greedily) or
        ``pc_policy_factory``. The PCs then run at Level 5 and the engine's one policy slot
        holds a dispatcher that hands each decision to its own side's rank."""
        if npc_policy not in NPC_POLICIES:
            raise ValueError(f"unknown npc_policy {npc_policy!r} ({sorted(NPC_POLICIES)})")
        if pc_mode not in PC_MODES:
            raise ValueError(f"unknown pc_mode {pc_mode!r} ({PC_MODES})")
        if npc_policy in MODEL_POLICIES and policy_factory is None:
            if not model:
                raise ValueError(f"npc_policy {npc_policy!r} needs a model checkpoint")
            from ml import policy as ml_policy      # torch is loaded only when a model runs
            policy_factory = ml_policy.factory(model)
        if pc_mode == "SelfPlay" and pc_policy_factory is None:
            if not pc_model:
                raise ValueError("pc_mode 'SelfPlay' needs a PC policy (pc_model or pc_policy_factory)")
            from ml import policy as ml_policy
            pc_policy_factory = ml_policy.factory(pc_model)
        if pc_mode == "Heuristic" and (pc_model or pc_policy_factory is not None):
            raise ValueError("a PC policy needs pc_mode 'SelfPlay'")
        t0 = time.perf_counter()
        bm, eng = self.load_board(scenario.map, scenario.terrain, seed)
        npc_rank = None
        if policy_factory is not None:
            npc_rank = policy_factory(eng, bm, seed)
        elif npc_policy in MACRO_POLICIES:
            npc_rank = MACRO_POLICIES[npc_policy](eng, bm, seed)
        pc_rank = pc_policy_factory(eng, bm, seed) if pc_policy_factory is not None else None
        agents = copy.deepcopy(scenario.agents)
        # Heuristic PCs with signature spells (generated parties, B9a) run Level 4 with their
        # signatures first, through the policy seam at Level 5. PCs without any stay plain Level 4.
        signatures = {}
        if pc_rank is None:
            signatures = {i: list(a["signature_spells"]) for i, a in enumerate(agents)
                          if int(a.get("faction", 0)) == PC_FACTION and a.get("signature_spells")}
        pc_policy_name = ("level4" if pc_rank is None else
                          os.path.basename(pc_model) if pc_model else "policy")
        if signatures:
            pc_rank = signature_policy(eng, bm, signatures)
            pc_policy_name = "level4+signatures"
        if pc_rank is not None:
            eng.set_npc_policy(_side_dispatch(bm, npc_rank, pc_rank))
        elif npc_rank is not None:
            eng.set_npc_policy(npc_rank)
        npc_level = NPC_POLICIES[npc_policy]
        for i, a in enumerate(agents):
            pc_side = int(a.get("faction", 0)) == PC_FACTION
            a["is_npc_automated"] = True
            a["on_deck"] = False
            if not pc_side:
                level = npc_level
            elif pc_policy_factory is not None or i in signatures:
                level = PC_POLICY_LEVEL
            else:
                level = PC_HEURISTIC_LEVEL
            a["npc_automation_difficulty_level"] = level
        self.load_agents(agents)
        t_loaded = time.perf_counter()
        fight = _Fight(self.app, eng, bm, round_cap)
        trace = None
        if trace_path:
            trace = sim_trace.TraceWriter(
                # Absolute, as the GUI records it: Playback opens the PNG from its own cwd.
                trace_path, map_path=_abs(scenario.map), agents={"agents": agents}, seed=seed,
                npc_policy=npc_policy, pc_mode=pc_mode, initiative=(),
                extra={"arena": True, "scenario_hash": scenario.hash,
                       "party": party_makeup(agents),
                       "scenario": {k: v for k, v in scenario.meta.items() if k != "party"},
                       "manual_grid": self.app._manual_grid})
            fight.trace = trace
        outcome = fight.run()
        outcome.update({"scenario_hash": scenario.hash, "split": scenario.split,
                        "seed": int(seed), "npc_policy": npc_policy, "pc_mode": pc_mode,
                        "pc_policy": pc_policy_name,
                        "load_s": round(t_loaded - t0, 4),
                        "fight_s": round(time.perf_counter() - t_loaded, 4)})
        if trace is not None:
            trace.close(outcome)
            outcome["trace"] = trace_path
        return outcome


# ── Python-driven NPC policies (NPC_LEARNING_PLAN.md Step 5) ─────────────────
# Each factory takes (engine, battle map, seed) and returns the rank callable set_npc_policy
# installs: rank(agent_idx, archetype, actions) -> candidate indices, best first.

def same_macro(a, b) -> bool:
    """Two NpcMacroActions name the same choice (``legal`` aside)."""
    return (a.kind == b.kind and a.target_agent == b.target_agent and a.spell_idx == b.spell_idx
            and a.target_cell.col == b.target_cell.col and a.target_cell.row == b.target_cell.row)


def l4_macro_policy(eng, bm, seed: int):
    """Level 4's own choice (``npc_heuristic_macro_action``) run through the macro-action path.
    Its win rate should track ``level4``'s: a check of the macro executors, and the shape of
    Step 6's behaviour-cloning labels."""
    def rank(idx, archetype, actions):
        want = eng.npc_heuristic_macro_action(bm, idx)
        return [i for i, a in enumerate(actions) if same_macro(a, want)][:1]
    return rank


def random_macro_policy(eng, bm, seed: int):
    """A uniformly random legal macro-action, seeded by the episode."""
    rng = random.Random(seed)

    def rank(idx, archetype, actions):
        legal = [i for i, a in enumerate(actions) if a.legal]
        rng.shuffle(legal)
        return legal
    return rank


MACRO_POLICIES = {"l4-macro": l4_macro_policy, "random-macro": random_macro_policy}


def signature_policy(eng, bm, signatures: dict):
    """Level 4 with build-defining spells first (Step 3b, B9a). ``signatures``: agent index ->
    spell names, best first. A creature with any of them castable now (a legal candidate) casts
    the first such spell; otherwise it plays Level 4's own choice through the macro path, like
    ``l4-macro``. A concentration signature is passed over while the caster concentrates, and a
    heal only targets an ally below half HP (Level 4's own threshold)."""
    heal = rpg.NpcMacroKind.Heal

    def rank(idx, archetype, actions):
        names = signatures.get(idx)
        if names:
            me = bm.placed_agents[idx]
            spells = me.spells
            concentrating = me.conditions.concentrating
            agents = bm.placed_agents
            for name in names:
                best, best_key = -1, None
                for i, a in enumerate(actions):
                    si = int(a.spell_idx)
                    if not a.legal or not (0 <= si < len(spells)) or spells[si].name != name:
                        continue
                    if concentrating and spells[si].requires_concentration:
                        continue
                    t = int(a.target_agent)
                    if a.kind == heal:
                        if not (0 <= t < len(agents)):
                            continue
                        st = agents[t].stats
                        frac = st.hp_cur / max(1, st.hp_max)
                        if frac >= 0.5:
                            continue
                        key = frac
                    elif 0 <= t < len(agents):
                        o = agents[t].origin
                        key = float(max(abs(o.col - me.origin.col), abs(o.row - me.origin.row)))
                    else:
                        key = 0.0
                    if best < 0 or key < best_key:
                        best, best_key = i, key
                if best >= 0:
                    return [best]
        want = eng.npc_heuristic_macro_action(bm, idx)
        return [i for i, a in enumerate(actions) if same_macro(a, want)][:1]
    return rank


def _side_dispatch(bm, npc_rank, pc_rank):
    """One rank for the engine's single policy slot: each decision goes to the acting
    creature's side (a summon is on its summoner's). A side with no rank of its own runs at
    Level 4 and is never asked, but answers ``[]`` (the fallback chain) if it is."""
    def rank(idx, archetype, actions):
        r = pc_rank if bm.placed_agents[idx].faction == PC_FACTION else npc_rank
        return r(idx, archetype, actions) if r is not None else []
    return rank


def _unique_names(agents: list) -> None:
    """``Goblin``, ``Goblin 2``, … as the GUI names copies; ``base_name`` keeps the
    bestiary key."""
    seen: dict[str, int] = {}
    for a in agents:
        a["base_name"] = a["name"]
        n = seen.get(a["name"], 0) + 1
        seen[a["name"]] = n
        if n > 1:
            a["name"] = f"{a['name']} {n}"


# ── Reactions, answered by the side's policy ────────────────────────────────

def auto_reaction(bm, ctx) -> "rpg.ReactionResponse":
    """Level 4 rules, both sides: take the first reaction the engine offers. Its options are
    engine-vetted legal, so any non-Skip one is a real reaction. Vitality of the Tree needs a
    target, the most-wounded living ally within 10 ft; with none it is passed over."""
    resp = rpg.ReactionResponse()
    skip = next((i for i, o in enumerate(ctx.options)
                 if o.kind == rpg.ReactionOptionKind.Skip), -1)
    resp.option = skip
    for i, o in enumerate(ctx.options):
        if o.kind == rpg.ReactionOptionKind.Skip:
            continue
        if o.feature == "VitalityOfTheTree":
            tgt = _vitality_target(bm, ctx.source_idx)
            if tgt < 0:
                continue
            resp.target_idx = tgt
        resp.option = i
        break
    return resp


def _vitality_target(bm, src: int) -> int:
    agents = bm.placed_agents
    if not (0 <= src < len(agents)):
        return -1
    me = agents[src]
    best, best_missing = -1, -1
    for i, pt in enumerate(agents):
        if i == src or pt.removed_from_play or pt.faction != me.faction:
            continue
        if pt.stats.hp_cur <= 0 or pt.conditions.dead:
            continue
        gap = max(abs(pt.origin.col - me.origin.col), abs(pt.origin.row - me.origin.row))
        if gap - (max(pt.size, me.size) - 1) > 2:     # 10 ft between footprints
            continue
        missing = pt.stats.hp_max - pt.stats.hp_cur
        if missing > best_missing:
            best, best_missing = i, missing
    return best


# ── The turn loop ───────────────────────────────────────────────────────────

def side_hp_frac(bm, faction: int) -> float:
    """A side's remaining HP as a share of its maximum, over every creature in play (the
    fallen count at 0). Step 7's reward shaping reads it at each decision."""
    cur = tot = 0
    for pt in bm.placed_agents:
        if pt.faction == faction and not pt.removed_from_play:
            cur += max(0, pt.stats.hp_cur)
            tot += max(1, pt.stats.hp_max)
    return cur / tot if tot else 0.0


class _Fight:
    """The GUI's turn chain with every creature automated and no human anywhere."""

    def __init__(self, app, eng, bm, round_cap: int):
        self.app, self.eng, self.bm = app, eng, bm
        self.round_cap = round_cap
        self.trace: sim_trace.TraceWriter | None = None
        self.order: list = []
        self.turn_idx = 0
        self.round_num = 0
        self.turns = 0
        self.reactions = 0
        self._nagents = len(bm.placed_agents)

    # logging: the engine's logger, drained into the trace (no console, no files)
    def _flush(self):
        lines = self.app.logger.flush()
        if self.trace is not None:
            for ln in lines:
                self.trace.add_log(ln)

    def _snapshot(self):
        return {i: {"pos": (float(pt.origin.col), float(pt.origin.row)),
                    "hp": pt.stats.hp_cur, "was_alive": not pt.conditions.dead}
                for i, pt in enumerate(self.bm.placed_agents) if not pt.removed_from_play}

    def _standing(self) -> dict:
        out = {f: 0 for f in SIDES}
        for i, pt in enumerate(self.bm.placed_agents):
            if pt.removed_from_play or self.bm.is_agent_on_deck(i) or pt.faction not in out:
                continue
            if pt.stats.hp_cur > 0 and not pt.conditions.dead:
                out[pt.faction] += 1
        return out

    def _hp_frac(self, faction: int) -> float:
        return round(side_hp_frac(self.bm, faction), 4)

    def _resolve_parks(self, status) -> bool:
        """Answer parked reaction windows until the flow completes. False: it never did."""
        for _ in range(MAX_PARKS_PER_TURN):
            pd = self.eng.pending_decision()
            if status != rpg.FlowStatus.AwaitingDecision or not pd.active:
                return True
            resp = auto_reaction(self.bm, pd.ctx)
            if resp.option >= 0 and pd.ctx.options[resp.option].kind != rpg.ReactionOptionKind.Skip:
                self.reactions += 1
            status = self.eng.submit_decision(self.bm, resp)
            self._flush()
        return False

    def _adopt_spawned(self, actor: int):
        """Creatures the turn added (summons) join initiative right after the actor, sharing
        its count, as the GUI's summon paths do; the trace gets their records."""
        n = len(self.bm.placed_agents)
        if n <= self._nagents:
            return
        pos = next((p for p, e in enumerate(self.order) if e.agent_idx == actor), self.turn_idx)
        base = self.order[pos]
        for k, new_idx in enumerate(range(self._nagents, n)):
            e = rpg.InitiativeEntry()
            e.agent_idx, e.d20, e.modifier, e.total = new_idx, base.d20, base.modifier, base.total
            self.order.insert(pos + 1 + k, e)
        self._nagents = n

    def _spawned_records(self) -> list:
        n = len(self.bm.placed_agents)
        if self.trace is None or n <= self._trace_n:
            return []
        tmp = os.path.join(os.path.dirname(self.trace.path) or ".", ".arena_spawned.tmp")
        try:
            self.app._save_agents(tmp, raw=True)
            with open(tmp) as f:
                recs = json.load(f)["agents"][self._trace_n:]
        except Exception as e:     # the trace is diagnostic; never stop a fight for it
            print(f"[ARENA] spawned agents not recorded: {e}")
            recs = []
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self._trace_n = n
        return recs

    def _take_turn(self, idx: int) -> bool:
        """One creature's turn. False: a reaction loop never closed (the episode aborts)."""
        bm, eng = self.bm, self.eng
        self.turns += 1
        if self.trace is not None:
            self.trace.begin_turn(round_num=self.round_num, actor=idx,
                                  actor_name=bm.placed_agents[idx].name,
                                  driver=sim_trace.DRIVER_NPC, snapshot=self._snapshot(),
                                  spawned=self._spawned_records())
        if not self._resolve_parks(eng.begin_turn_flow(bm, idx, True)):
            return False
        self._flush()
        start = eng.last_turn_start_result()
        eng.tick_agent_conditions_for_caster(bm, idx)
        if start.turn_skipped:
            return True
        eng.tick_terrain_for_turn(bm, idx)
        eng.tick_light_effects_for_turn(bm, idx)
        if bm.is_agent_on_deck(idx):
            return True
        for _ in range(MAX_PARKS_PER_TURN):
            status = eng.run_npc_turn(bm, idx)
            self._flush()
            if idx < len(bm.placed_agents) and bm.placed_agents[idx].conditions.hidden:
                eng.check_hidden_agent_detection(bm, idx, True)
            events = eng.take_npc_visual_events()
            if self.trace is not None:
                self.trace.set_decision(eng.last_npc_decision())
                if events:
                    self.trace.add_events(events)
            if status != rpg.FlowStatus.AwaitingDecision or not eng.pending_decision().active:
                self._adopt_spawned(idx)
                return True
            if not self._resolve_parks(status):
                return False
        return False

    def _advance(self) -> bool:
        """``_advance_turn``: the next living combatant, the round tick, the previous turn's
        end. False: the round cap was reached."""
        bm, eng = self.bm, self.eng
        n = len(self.order)
        prev_turn, prev_idx = self.turn_idx, self.order[self.turn_idx].agent_idx
        for _ in range(n):
            self.turn_idx = (self.turn_idx + 1) % n
            idx = self.order[self.turn_idx].agent_idx
            if bm.is_agent_removed_from_play(idx):
                continue
            st = eng.get_agent_stats(bm, idx)
            if st.hp_cur > 0 or not eng.get_agent_conditions(bm, idx).dead:
                break
            eng.drop_concentration(bm, idx)
        if self.turn_idx < prev_turn:
            self.round_num += 1
            bm.tick_dm_terrain_effects()
        eng.end_turn(bm, prev_idx)
        self._flush()
        return self.round_num < self.round_cap

    def run(self) -> dict:
        bm, eng = self.bm, self.eng
        self._trace_n = self._nagents
        self.order = list(eng.roll_initiative(bm))
        eng.apply_superior_inspiration(bm)
        bm.clear_terrain_effects()
        for i in range(len(bm.placed_agents)):
            eng.apply_armor_multipliers(bm, i)
        self._flush()
        reason = "victory"
        if not self.order:
            reason = "no_initiative"
        else:
            while True:
                standing = self._standing()
                if not all(standing.values()):
                    break
                if not self._take_turn(self.order[self.turn_idx].agent_idx):
                    reason = "stuck"
                    break
                standing = self._standing()
                if not all(standing.values()):
                    break
                if not self._advance():
                    reason = "round_cap"
                    break
        standing = self._standing()
        winner = None
        if reason == "victory":
            alive = [SIDES[f] for f, k in standing.items() if k > 0]
            winner = alive[0] if len(alive) == 1 else None
        # round_num is 0-based, as in the GUI and the trace; at the cap it names the round
        # that was never played.
        played = self.round_num if reason == "round_cap" else self.round_num + 1
        return {"winner": winner, "reason": reason, "rounds": played,
                "turns": self.turns, "reactions": self.reactions,
                "standing": {SIDES[f]: k for f, k in standing.items()},
                "hp_frac": {SIDES[f]: self._hp_frac(f) for f in SIDES}}


# ── Module-level entry points ───────────────────────────────────────────────

_ARENA: Arena | None = None


def arena() -> Arena:
    """This process's Arena (built on first use)."""
    global _ARENA
    if _ARENA is None:
        _ARENA = Arena()
    return _ARENA


def generate_scenario(scenario_seed: int, **kw) -> Scenario:
    return arena().generate_scenario(scenario_seed, **kw)


def run_episode(scenario: Scenario, seed: int, npc_policy: str = "level4",
                pc_mode: str = "Heuristic", **kw) -> dict:
    return arena().run_episode(scenario, seed, npc_policy, pc_mode, **kw)


def keep_trace(seed: int) -> bool:
    """D13: a seeded 1-in-``TRACE_SAMPLE`` sample of episodes keeps its trace."""
    return random.Random(f"trace:{seed}").randrange(TRACE_SAMPLE) == 0


def scenario_for_split(base_seed: int, k: int, split: str | None, **kw) -> Scenario:
    """The k-th scenario of a run, skipping ones in the other split. Deterministic."""
    for j in range(1000):
        sc = generate_scenario(base_seed * 1_000_003 + k * 1009 + j, **kw)
        if split in (None, "any") or sc.split == split:
            return sc
    raise RuntimeError(f"no {split} scenario found for episode {k}")


def _episode_job(job: dict) -> dict:
    """One batch episode: scenario k, combat seed k, a trace when sampled."""
    sc = scenario_for_split(job["base_seed"], job["k"], job["split"],
                            maps=job.get("maps"), parties=job.get("parties"))
    seed = job["base_seed"] * 7919 + job["k"]
    trace_path = None
    if job.get("trace_dir") and (job.get("trace_all") or keep_trace(seed)):
        trace_path = os.path.join(job["trace_dir"], f"ep{job['k']:06d}_{sc.hash[:10]}.jsonl")
    t0 = time.perf_counter()
    out = run_episode(sc, seed, job["npc_policy"], job["pc_mode"], trace_path=trace_path,
                      round_cap=job["round_cap"], model=job.get("model"),
                      pc_model=job.get("pc_model"))
    out["episode"] = job["k"]
    out["wall_s"] = round(time.perf_counter() - t0, 4)
    out["scenario"] = sc.meta
    return out


def _worker_init():
    arena()


def run_batch(jobs: list[dict], n_procs: int):
    """Yield episode outcomes in job order, on ``n_procs`` worker processes (1 = inline)."""
    if n_procs <= 1:
        for j in jobs:
            yield _episode_job(j)
        return
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(n_procs, initializer=_worker_init) as pool:
        yield from pool.imap(_episode_job, jobs)


def _summary(outs: list[dict], wall: float, n_procs: int) -> dict:
    n = len(outs)
    turns = sum(o["turns"] for o in outs)
    fight = sum(o["fight_s"] for o in outs)
    load = sum(o["load_s"] for o in outs)
    by = {w: sum(1 for o in outs if o["winner"] == w) for w in ("npc", "pc", None)}
    return {"episodes": n, "jobs": n_procs, "wall_s": round(wall, 2),
            "npc_wins": by["npc"], "pc_wins": by["pc"], "draws": by[None],
            "reasons": {r: sum(1 for o in outs if o["reason"] == r)
                        for r in sorted({o["reason"] for o in outs})},
            "turns": turns,
            "turns_per_s_fight_one_core": round(turns / fight, 1) if fight else None,
            "s_per_episode_one_core": round((fight + load) / n, 3) if n else None,
            "load_share": round(load / (fight + load), 3) if fight + load else None,
            "episodes_per_hour_one_core": round(3600 * n / (fight + load)) if n else None,
            "episodes_per_hour_all_jobs": round(3600 * n / wall) if wall else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "bench"):
        p = sub.add_parser(name)
        p.add_argument("--episodes", type=int, default=20 if name == "bench" else 100)
        p.add_argument("--jobs", type=int, default=1, help="worker processes")
        p.add_argument("--seed", type=int, default=1, help="base seed for scenarios + fights")
        p.add_argument("--split", choices=("train", "heldout", "any"), default="train")
        p.add_argument("--npc-policy", choices=sorted(NPC_POLICIES), default="level4")
        p.add_argument("--pc-mode", choices=PC_MODES, default="Heuristic")
        p.add_argument("--round-cap", type=int, default=ROUND_CAP)
        p.add_argument("--map", action="append", default=None,
                       help="map PNG (repeatable; its _terrain.json is used if present)")
        p.add_argument("--party", action="append", default=None,
                       help="party source: an agents file or a pcs/ directory (repeatable)")
        p.add_argument("--out", default=None, help="JSONL of every episode's outcome")
        p.add_argument("--trace-dir", default=None,
                       help="keep traces here for a seeded 1-in-10 sample of episodes")
        p.add_argument("--trace-all", action="store_true", help="trace every episode")
        p.add_argument("--model", default=None, help="checkpoint for --npc-policy bc / ppo")
        p.add_argument("--pc-model", default=None, help="PC checkpoint for --pc-mode SelfPlay")
    a = ap.parse_args(argv)
    # Paths are the caller's, relative to where they ran; the Arena then works from gui/.
    a.out = os.path.abspath(a.out) if a.out else None
    a.model = os.path.abspath(a.model) if a.model else None
    a.pc_model = os.path.abspath(a.pc_model) if a.pc_model else None
    a.trace_dir = os.path.abspath(a.trace_dir) if a.trace_dir else None
    a.map = [os.path.abspath(m) for m in a.map] if a.map else None
    a.party = [os.path.abspath(p) for p in a.party] if a.party else None

    maps = None
    if a.map:
        maps = []
        for m in a.map:
            terr = os.path.splitext(_abs(m))[0] + "_terrain.json"
            maps.append((_rel(m), _rel(terr) if os.path.exists(terr) else None))
    if a.trace_dir:
        os.makedirs(a.trace_dir, exist_ok=True)
    jobs = [{"base_seed": a.seed, "k": k, "split": a.split, "maps": maps,
             "parties": a.party, "npc_policy": a.npc_policy, "pc_mode": a.pc_mode,
             "round_cap": a.round_cap, "trace_dir": a.trace_dir, "trace_all": a.trace_all,
             "model": a.model, "pc_model": a.pc_model}
            for k in range(a.episodes)]
    out_f = None
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        out_f = open(a.out, "w")
    t0 = time.perf_counter()
    outs = []
    try:
        for o in run_batch(jobs, a.jobs):
            outs.append(o)
            if out_f:
                out_f.write(json.dumps(o) + "\n")
                out_f.flush()
            print(f"ep {o['episode']:4d}  {o['split']:7s}  winner={str(o['winner']):4s} "
                  f"{o['reason']:9s} rounds={o['rounds']:2d} turns={o['turns']:3d} "
                  f"{o['wall_s']:.2f}s  {o['scenario']['difficulty']:8s} "
                  f"L{o['scenario']['party_level']} "
                  f"[{', '.join(p['class'] for p in o['scenario']['party'])}] "
                  f"vs {', '.join(o['scenario']['mobs'])}",
                  flush=True)
    finally:
        if out_f:
            out_f.close()
    print(json.dumps(_summary(outs, time.perf_counter() - t0, a.jobs), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
