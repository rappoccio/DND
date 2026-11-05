#!/usr/bin/env python3
"""The phone prompt sheet (live play 2026-11-04, BUGS_FROM_LIVE_PLAY.md): below 46rem the
prompt no longer stacks above the board and pushes it off the screen. It is a sheet
pinned over the bottom of the board, collapsed to a handle until tapped.

`prompt_sheet_checks.js` drives the state through the real `app.js` under node. This file
adds what node cannot check: app.css hides the handle on wide screens and applies the
sheet only inside the phone query, which is the one the rest of the stylesheet uses.
"""

import os
import re
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_CSS = os.path.join(_ROOT, "gui", "net", "static", "app.css")
_INDEX = os.path.join(_ROOT, "gui", "net", "static", "index.html")
_CHECKS = os.path.join(_ROOT, "tests", "prompt_sheet_checks.js")


def test_the_sheet_is_phone_only():
    css = open(_APP_CSS, encoding="utf-8").read()
    assert re.search(r"^\.prompt-toggle \{ display: none; \}", css, re.M), \
        "app.css must hide the sheet's handle outside the phone query"
    assert "@media (min-width: 46rem)" in css, "the panels' two-column query moved"
    m = re.search(r"@media \(max-width: 45\.99rem\) \{(.*?)\n\}", css, re.S)
    assert m, "app.css has no phone query just below the 46rem breakpoint"
    body = m.group(1)
    for needle in ('.prompt[data-mode="menu"] .prompt-toggle', 'position: fixed',
                   '.prompt[data-sheet="closed"] >', 'max-height: 60vh'):
        assert needle in body, f"the phone query lacks {needle!r}"
    html = open(_INDEX, encoding="utf-8").read()
    for id_ in ("prompt-toggle", "prompt-toggle-label", "prompt-toggle-timer"):
        assert f'id="{id_}"' in html, f"index.html has no #{id_}"
    print("✅ test_the_sheet_is_phone_only")


def test_the_sheet_in_the_client():
    """`prompt_sheet_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_sheet_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the prompt sheet checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_sheet_in_the_client")


if __name__ == "__main__":
    test_the_sheet_is_phone_only()
    test_the_sheet_in_the_client()
    sys.exit(0)
