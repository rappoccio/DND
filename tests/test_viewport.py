#!/usr/bin/env python3
"""The player board's zoom and pan (plans/QOL_PLAN.md Q1) and its wide layout (Q2).

`viewport_checks.js` loads the real `app.js` under node with the stubbed browser
(`app_harness.js`) and drives the viewport through it: the fit, zoom about a point, pan
clamping, the tap/drag/pinch split, and a tap mapped back to its cell at any zoom.

This file adds what node cannot check: the zoom range is the DM screen's own
(`App.ZOOM_MIN` / `App.ZOOM_MAX` in `main.py`), copied because the client has no build step.
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
_CHECKS = os.path.join(_ROOT, "tests", "viewport_checks.js")


def _app_class_constants() -> dict:
    """`App`'s class-level literals in `main.py`, read from source."""
    tree = ast.parse(open(_MAIN, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            out = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                        and isinstance(stmt.targets[0], ast.Name):
                    try:
                        out[stmt.targets[0].id] = ast.literal_eval(stmt.value)
                    except ValueError:
                        pass
            return out
    raise AssertionError("main.py has no class App")


def test_zoom_range_matches_the_dm_screen():
    js = open(_APP_JS, encoding="utf-8").read()
    py = _app_class_constants()
    for name in ("ZOOM_MIN", "ZOOM_MAX"):
        m = re.search(rf"^const {name} = ([0-9.]+);", js, re.M)
        assert m, f"app.js has no top-level const {name}"
        assert float(m.group(1)) == float(py[name]), \
            f"{name} in app.js is {m.group(1)}, main.py App.{name} is {py[name]}"
    print("✅ test_zoom_range_matches_the_dm_screen")


def test_wide_layout_matches_the_dm_screen():
    """QOL Q2: the player's right column is the DM's `PANEL_W`, and app.css and app.js
    switch to it at the same width."""
    css = open(_APP_CSS, encoding="utf-8").read()
    js = open(_APP_JS, encoding="utf-8").read()
    consts = ast.parse(open(_CONSTANTS, encoding="utf-8").read())
    panel_w = next(ast.literal_eval(n.value) for n in consts.body
                   if isinstance(n, ast.Assign) and len(n.targets) == 1
                   and getattr(n.targets[0], "id", None) == "PANEL_W")
    m = re.search(r"grid-template-columns: minmax\(0, 1fr\) (\d+)px;", css)
    assert m, "app.css has no wide-layout grid"
    assert int(m.group(1)) == panel_w, \
        f"app.css's right column is {m.group(1)}px, constants.PANEL_W is {panel_w}"
    q = re.search(r'^const WIDE_QUERY = "\(([^)]*)\)";', js, re.M)
    assert q, "app.js has no top-level const WIDE_QUERY"
    assert f"@media ({q.group(1)})" in css, \
        f"app.css has no @media ({q.group(1)}) to match app.js's WIDE_QUERY"
    print("✅ test_wide_layout_matches_the_dm_screen")


def test_the_viewport_in_the_client():
    """`viewport_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_viewport_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the viewport checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_viewport_in_the_client")


if __name__ == "__main__":
    test_zoom_range_matches_the_dm_screen()
    test_wide_layout_matches_the_dm_screen()
    test_the_viewport_in_the_client()
    sys.exit(0)
