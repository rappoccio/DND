#!/usr/bin/env python3
"""
Checked combat replay — deterministic bug regression.

Re-creates the CombatEngine with the recorded seed, loads the same agents, rolls
initiative (to match the recorded RNG state), then re-runs every recorded engine
event in order. After each event it asserts the engine reproduces the recorded
state snapshot. Any divergence is reported (agent, field, expected vs actual).

Usage:
    python3 replay.py <map_image> [replay_log.txt] [--check]

    --check : quiet on success, exit nonzero if any snapshot diverges (CI/bug-test).
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import rpg_battle_map as rpg
except ImportError:
    print("ERROR: rpg_battle_map module not found. Build it first (cmake).")
    sys.exit(1)

from agent_loader import load_agents_from_json
from replay_record import engine_snapshot, diff_snapshots, reconstruct_arg

# Recorded engine methods that take BattleMap as their first arg (almost all do).
_NO_BM = {"set_safe_targets"}


class CheckedReplayer:
    def __init__(self, map_image_path, replay_log_path="replay_log.txt", quiet=False):
        self.map_image_path = map_image_path
        self.replay_log_path = replay_log_path
        self.quiet = quiet
        self.bm = None
        self.combat = None
        self.seed = None
        self.events = []

    def log(self, *a):
        if not self.quiet:
            print(*a)

    def load_replay_log(self):
        if not os.path.exists(self.replay_log_path):
            print(f"ERROR: replay log not found: {self.replay_log_path}")
            return False
        with open(self.replay_log_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("SEED:"):
                    self.seed = int(line.split(":", 1)[1])
                elif line.startswith("{"):
                    try:
                        self.events.append(json.loads(line))
                    except json.JSONDecodeError:
                        print(f"WARNING: bad event line: {line}")
        if self.seed is None:
            print("ERROR: no SEED in replay log")
            return False
        self.log(f"[REPLAY] seed={self.seed}, {len(self.events)} events")
        return True

    def setup(self):
        self.bm = rpg.BattleMap(self.map_image_path)
        self.bm.analyze_grid()      # required before placing agents (else placement segfaults)
        self.bm.detect_walls()
        self.combat = rpg.CombatEngine(self.seed)
        agents_json = os.path.splitext(self.map_image_path)[0] + "_agents.json"
        if not load_agents_from_json(agents_json, self.bm, self.combat, sprites_dir=""):
            print(f"ERROR: could not load agents from {agents_json}")
            return False
        # Match the recording: initiative is rolled (consuming RNG) before recording starts.
        self.combat.roll_initiative(self.bm)
        # Mirror _start_combat's RNG-free Bard Superior Inspiration top-up so replay state matches.
        self.combat.apply_superior_inspiration(self.bm)
        self.log(f"[REPLAY] loaded {len(self.bm.placed_agents)} agents; initiative rolled")
        return True

    def _dispatch(self, event):
        name = event["event"]
        raw = event.get("args", [])
        if name == "reckless":
            idx = raw[0]["idx"]
            c = self.combat.get_agent_conditions(self.bm, idx)
            c.reckless_attack = True
            self.combat.set_agent_conditions(self.bm, idx, c)
            return
        method = getattr(self.combat, name, None)
        if not callable(method):
            print(f"  WARNING: unknown event '{name}', skipping (replay may diverge)")
            return
        args = [reconstruct_arg(s, rpg) for s in raw]
        if name in _NO_BM:
            method(*args)
        else:
            method(self.bm, *args)

    def run(self):
        if not self.load_replay_log():
            return False
        if not self.setup():
            return False

        mismatches = 0
        for i, event in enumerate(self.events):
            self._dispatch(event)
            expected = event.get("snap")
            if expected is None:
                continue
            diffs = diff_snapshots(expected, engine_snapshot(self.combat, self.bm))
            if diffs:
                mismatches += 1
                print(f"[MISMATCH] event {i + 1}/{len(self.events)} '{event['event']}':")
                for d in diffs:
                    print(f"    {d}")
            else:
                self.log(f"[ok] event {i + 1}/{len(self.events)} '{event['event']}'")

        if mismatches:
            print(f"\nFAIL: {mismatches}/{len(self.events)} events diverged from the recording.")
            return False
        self.log(f"\nPASS: all {len(self.events)} events reproduced exactly.")
        return True


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    quiet = "--check" in sys.argv
    if not args:
        print("Usage: python3 replay.py <map_image> [replay_log.txt] [--check]")
        sys.exit(2)
    map_image = args[0]
    replay_log = args[1] if len(args) > 1 else "replay_log.txt"
    ok = CheckedReplayer(map_image, replay_log, quiet=quiet).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
