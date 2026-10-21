#!/usr/bin/env python3
"""The player's combined initiative/health table and turn highlight (plans/QOL_PLAN.md Q3).

`roster_checks.js` loads the real `app.js` under node with the stubbed browser
(`app_harness.js`) and checks the table's rows and the token outline.

This file adds what node cannot check: the two yellows are the DM screen's own —
`constants.COL_INITIATIVE_CUR` for the ▶ row, and `_draw_agents`' selection rect for the
token outline — copied because the client has no build step.
"""

import ast
import os
import re
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_JS = os.path.join(_ROOT, "gui", "net", "static", "app.js")
_APP_CSS = os.path.join(_ROOT, "gui", "net", "static", "app.css")
_MAIN = os.path.join(_ROOT, "gui", "main.py")
_CONSTANTS = os.path.join(_ROOT, "gui", "constants.py")
_CHECKS = os.path.join(_ROOT, "tests", "roster_checks.js")


def _rgb(text: str) -> tuple:
    return tuple(int(v) for v in re.findall(r"\d+", text))


def test_turn_row_colour_matches_the_dm_screen():
    consts = ast.parse(open(_CONSTANTS, encoding="utf-8").read())
    cur = next(ast.literal_eval(n.value) for n in consts.body
               if isinstance(n, ast.Assign) and len(n.targets) == 1
               and getattr(n.targets[0], "id", None) == "COL_INITIATIVE_CUR")
    css = open(_APP_CSS, encoding="utf-8").read()
    m = re.search(r"--turn:\s*(rgb\([^)]*\))", css)
    assert m, "app.css has no --turn colour"
    assert _rgb(m.group(1)) == tuple(cur), \
        f"app.css --turn is {m.group(1)}, constants.COL_INITIATIVE_CUR is {cur}"
    print("✅ test_turn_row_colour_matches_the_dm_screen")


def test_turn_outline_matches_the_dm_screen():
    src = open(_MAIN, encoding="utf-8").read()
    m = re.search(r"# Selection highlight \(yellow border\)\n.*?\n.*?\n"
                  r"\s*pygame\.draw\.rect\(self\.screen, (\([^)]*\))", src)
    assert m, "main.py _draw_agents has no selection highlight rect"
    js = open(_APP_JS, encoding="utf-8").read()
    j = re.search(r'^const TURN_OUTLINE = "(rgb\([^)]*\))";', js, re.M)
    assert j, "app.js has no top-level const TURN_OUTLINE"
    assert _rgb(j.group(1)) == _rgb(m.group(1)), \
        f"app.js TURN_OUTLINE is {j.group(1)}, main.py's selection rect is {m.group(1)}"
    print("✅ test_turn_outline_matches_the_dm_screen")


def test_the_roster_in_the_client():
    """`roster_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_roster_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the roster checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_roster_in_the_client")


if __name__ == "__main__":
    test_turn_row_colour_matches_the_dm_screen()
    test_turn_outline_matches_the_dm_screen()
    test_the_roster_in_the_client()
    sys.exit(0)
