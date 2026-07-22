#!/usr/bin/env python3
"""
Round-trip test for the checked replay system: record a short combat through the
RecordingCombat wrapper, then verify CheckedReplayer reproduces every snapshot
(PASS), and that a tampered snapshot is detected (FAIL).
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from agent_loader import load_agents_from_json
from replay_record import RecordingCombat
from replay import CheckedReplayer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PNG = os.path.join(_ROOT, "maps", "TestDNDMap.png")
AGENTS_JSON = os.path.join(_ROOT, "maps", "TestDNDMap_agents.json")
SEED = 12345


def _record(log_path):
    """Record a short, deterministic scenario and return how many agents were loaded."""
    bm = rpg.BattleMap(MAP_PNG)
    bm.analyze_grid()
    bm.detect_walls()
    combat = RecordingCombat(rpg.CombatEngine(SEED), rpg)
    assert load_agents_from_json(AGENTS_JSON, bm, combat, sprites_dir=""), "agent load failed"
    n = len(bm.placed_agents)
    assert n >= 2, f"need >=2 agents in fixture, got {n}"
    combat.roll_initiative(bm)  # consumes RNG before recording, like the GUI

    with open(log_path, "w") as f:
        f.write("=== TEST REPLAY LOG ===\n")
        f.write(f"SEED: {SEED}\n")
        f.write("=== EVENTS (JSON) ===\n")
    combat.start_recording(log_path, bm)

    # Exercise the dispatch paths: bm-first method, enum + Cell args, the no-bm
    # method (set_safe_targets), a semantic event (reckless), and a turn boundary.
    combat.begin_turn(bm, 0)
    combat.set_safe_targets(0, [1])
    combat.log_event("reckless", idx=0)
    origin = bm.placed_agents[0].origin
    combat.move_agent(bm, 0, rpg.Cell(origin.col, origin.row), rpg.MovementType.Walk)
    combat.end_turn(bm, 0)
    combat.begin_turn(bm, 1)
    combat.stop_recording()
    return n


def test_replay_roundtrip_matches():
    """A recording replays cleanly: every snapshot is reproduced."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        log_path = tf.name
    try:
        _record(log_path)
        ok = CheckedReplayer(MAP_PNG, log_path, quiet=True).run()
        assert ok, "checked replay should PASS for an untampered recording"
    finally:
        os.unlink(log_path)
    print("✅ test_replay_roundtrip_matches passed")


def test_replay_detects_divergence():
    """Tampering with a recorded snapshot is detected as a mismatch (FAIL)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        log_path = tf.name
    try:
        _record(log_path)
        # Corrupt the snapshot of the first event (bump agent 0's hp_cur).
        lines = open(log_path).read().splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("{"):
                ev = json.loads(ln)
                ev["snap"][0][1] += 999  # hp_cur field
                lines[i] = json.dumps(ev)
                break
        with open(log_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        ok = CheckedReplayer(MAP_PNG, log_path, quiet=True).run()
        assert not ok, "checked replay should FAIL when a snapshot is tampered"
    finally:
        os.unlink(log_path)
    print("✅ test_replay_detects_divergence passed")


if __name__ == "__main__":
    test_replay_roundtrip_matches()
    test_replay_detects_divergence()
    print("\n✅ All replay round-trip tests passed!")
