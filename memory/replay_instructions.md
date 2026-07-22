# Checked Combat Replay (deterministic bug regression)

Re-run a recorded combat against a freshly-seeded engine and **assert** the engine
reproduces the recorded state at every step. Any divergence is reported (agent, field,
expected vs actual). Use it to capture and reproduce combat bugs deterministically.

## Files
- `gui/replay_record.py` — `RecordingCombat`, a transparent wrapper around `CombatEngine`.
  During combat it records every state-mutating engine call (method + serialized args +
  a per-agent state snapshot) as one JSON event per line. Also holds the shared
  `engine_snapshot()` / `diff_snapshots()` used by both recorder and checker.
- `gui/replay.py` — the checked replayer (CLI).
- `tests/test_replay_roundtrip.py` — round-trip test (records, replays=PASS, tamper=FAIL).

## Recording (automatic)
The GUI wraps its engine in `RecordingCombat`. Recording starts at combat start (the
seed is written to the header) and stops at End Combat. Every combat overwrites
`gui/replay_log.txt`. The snapshot captured after each event is, per agent:
`[name, hp_cur, temp_hp, col, row, dead, prone, concentrating]`.

What is recorded: every engine mutation — `execute_action`, `execute_spell`, `move_agent`,
`begin_turn`/`end_turn`, the tick calls, `activate_rage`/`end_rage`,
`apply_brutal_strike_effect`, `execute_shove`/`execute_grapple`/`execute_grapple_escape`,
`drop_concentration`, `clear_all_concentration`, `set_safe_targets`, plus a semantic
`reckless` event (the one combat-relevant `set_agent_conditions` toggle).

## Running the check
```
python3 gui/replay.py <map_image> [replay_log.txt] [--check]
```
- Reconstructs the engine with the recorded seed, loads `<map>_agents.json` (via
  `agent_loader`), calls `analyze_grid()`+`detect_walls()`, then `roll_initiative()`
  (to match the RNG the recording consumed before recording started), then replays events.
- After each event it asserts the snapshot matches; on mismatch it prints the diff.
- `--check`: quiet on success, **exit code 1** on any divergence (CI/bug-test friendly).
- Run the round-trip self-test: `cd gui && python3 ../tests/test_replay_roundtrip.py` (also in the suite).

## Workflow for a bug report
1. Launch the GUI, run **one** combat that reproduces the bug, End Combat.
2. Copy `gui/replay_log.txt` somewhere (it's overwritten each combat).
3. `python3 gui/replay.py maps/<Map>.png <saved_log>.txt --check` reproduces it headlessly.

## Caveats / limitations
- **Fresh seed assumption:** the replay rebuilds the engine from the recorded seed, so the
  recorded combat must have started from a fresh engine — i.e. launch → one combat → replay.
  RNG consumed before that combat (e.g. a prior combat in the same session) would desync.
- **Not replayed:** out-of-band `set_agent_conditions` edits (DM conditions dialog) and long
  rest — they aren't normal combat flow. If a combat depends on those, the replay will diverge.
- Snapshots cover hp/position/dead/prone/concentrating. Extend `engine_snapshot()` in
  `replay_record.py` (and recorder+checker stay in sync automatically) to assert more state.
- Agent indices are positional; the same `<map>_agents.json` must be loaded.
