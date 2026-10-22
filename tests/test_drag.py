#!/usr/bin/env python3
"""Drag to move on the player board (plans/QOL_PLAN.md Q5).

`drag_checks.js` loads the real `app.js` under node with the stubbed browser
(`app_harness.js`) and drives a token drag through it: no Move button, a drop on a listed
cell, a drop off it, the outline colours, the offer → Move → cell chain, and an own move
that lands without replaying.

This file adds what node cannot check: the client's Move id is the server's
(`net/move.MOVE_ID`), and the outline colours are the DM screen's drag ghost.
"""

import os
import re
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_JS = os.path.join(_ROOT, "gui", "net", "static", "app.js")
_MOVE = os.path.join(_ROOT, "gui", "net", "move.py")
_MAIN = os.path.join(_ROOT, "gui", "main.py")
_CHECKS = os.path.join(_ROOT, "tests", "drag_checks.js")


def test_move_id_matches_the_server():
    js = open(_APP_JS, encoding="utf-8").read()
    py = open(_MOVE, encoding="utf-8").read()
    m = re.search(r'^const MOVE_OPTION = "([^"]+)";', js, re.M)
    p = re.search(r'^MOVE_ID = "([^"]+)"', py, re.M)
    assert m and p, "MOVE_OPTION / MOVE_ID not found"
    assert m.group(1) == p.group(1), f"app.js moves on {m.group(1)!r}, net/move.py on {p.group(1)!r}"
    print("✅ test_move_id_matches_the_server")


def test_outline_colours_match_the_dm_drag_ghost():
    js = open(_APP_JS, encoding="utf-8").read()
    main = open(_MAIN, encoding="utf-8").read()
    m = re.search(r"border_col = \((\d+, \d+, \d+)\) if self\.drag_valid else \((\d+, \d+, \d+)\)",
                  main)
    assert m, "main.py's drag-ghost outline not found"
    for name, want in (("DRAG_OK", m.group(1)), ("DRAG_BAD", m.group(2))):
        c = re.search(rf'^const {name} = "rgb\(([^)]*)\)";', js, re.M)
        assert c, f"app.js has no const {name}"
        assert c.group(1) == want, f"{name} is rgb({c.group(1)}), main.py has ({want})"
    print("✅ test_outline_colours_match_the_dm_drag_ghost")


def test_the_drag_in_the_client():
    """`drag_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_drag_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the drag checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_drag_in_the_client")


if __name__ == "__main__":
    test_move_id_matches_the_server()
    test_outline_colours_match_the_dm_drag_ghost()
    test_the_drag_in_the_client()
    sys.exit(0)
