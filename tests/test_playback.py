#!/usr/bin/env python3
"""The browser playback (M4b.3: B-5 and B-7).

`app.js` is the only place the playback exists, so it is tested where it runs:
`playback_checks.js` loads the real file under node, with a stubbed browser
(`app_harness.js`), and drives frames through its socket one animation frame at a time.

This file adds what node cannot check:

  · **The four timing constants and three flash colours are the DM screen's** (B-5). They
    are copied, not shared, because the client is a static file with no build step. So the
    copy is pinned against `gui/constants.py`, and a change on one side fails here.

The mutants this slice owns, and the checks that kill them:
  · an events frame applied without the `since` check   a frame that does not start at seq …
  · a held agent drawn from the live view                a move is held, then slides …
  · a view mid-playback un-holding an agent              a view mid-playback keeps …
  · the toggle ignored, or switching off the beat too    Animate moves off …
  · fast-forward dropping outcomes, or doubling one      a tap fast-forwards …; fast-forward
                                                         does not flash …
  · a GUI flash holding its agent                        a GUI flash (no HP field) holds nothing
  · a stale ring answer rolling seq back                 the ring's view replaces the board …
  · a constant drifting from constants.py                test_constants_match_the_dm_screen
"""

import ast
import os
import re
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_JS = os.path.join(_ROOT, "gui", "net", "static", "app.js")
_CONSTANTS = os.path.join(_ROOT, "gui", "constants.py")
_CHECKS = os.path.join(_ROOT, "tests", "playback_checks.js")

# app.js name → constants.py name, and how the value is spelled on each side.
_TIMING = {
    "ANIM_CELLS_PER_SEC": "NPC_ANIM_CELLS_PER_SEC",
    "TYPEWRITER_CPS": "NPC_TYPEWRITER_CPS",
    "ANNOUNCE_HOLD_MS": "NPC_ANNOUNCE_HOLD_MS",
    "OUTCOME_BEAT_MS": "NPC_OUTCOME_BEAT_MS",
}
_COLOURS = ("FLASH_GOOD", "FLASH_BAD", "FLASH_CRIT")


def _python_constants() -> dict:
    """`constants.py`'s top-level literals, read from source (it imports nothing we need)."""
    tree = ast.parse(open(_CONSTANTS, encoding="utf-8").read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _js_constant(js: str, name: str) -> str:
    m = re.search(rf"^const {name} = (.+?);", js, re.M)
    assert m, f"app.js has no top-level const {name}"
    return m.group(1).strip()


def test_constants_match_the_dm_screen():
    py = _python_constants()
    js = open(_APP_JS, encoding="utf-8").read()
    for js_name, py_name in _TIMING.items():
        assert float(_js_constant(js, js_name)) == float(py[py_name]), \
            f"{js_name} in app.js is not {py_name} = {py[py_name]}"
    for name in _COLOURS:
        r, g, b = py[name]
        assert _js_constant(js, name) == f'"rgb({r}, {g}, {b})"', \
            f"{name} in app.js is not constants.py's {py[name]}"
    print("✅ test_constants_match_the_dm_screen")


def test_the_playback_in_the_client():
    """`playback_checks.js`, run against the real `app.js`.

    Skipped rather than failed without node, as `test_live.test_the_client_parses` is: the
    image carries node (noVNC's), and this suite should not depend on a tool the plan never
    asked for.
    """
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_playback_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the playback checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_playback_in_the_client")


if __name__ == "__main__":
    test_constants_match_the_dm_screen()
    test_the_playback_in_the_client()
    sys.exit(0)
