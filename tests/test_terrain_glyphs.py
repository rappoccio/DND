#!/usr/bin/env python3
"""Doors, ladders and staircases on the player board.

`view.terrain` has always carried them (net/view.py `_terrain`), fog-filtered; the client
drew none of them. `terrain_glyph_checks.js` loads the real `app.js` under node with the
stubbed browser (`app_harness.js`) and checks each glyph lands on the cells it was sent.
"""

import os
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHECKS = os.path.join(_ROOT, "tests", "terrain_glyph_checks.js")


def test_terrain_glyphs_in_the_client():
    """`terrain_glyph_checks.js`, run against the real `app.js`; skipped without node."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_terrain_glyphs_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the terrain glyph checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_terrain_glyphs_in_the_client")


if __name__ == "__main__":
    test_terrain_glyphs_in_the_client()
    sys.exit(0)
