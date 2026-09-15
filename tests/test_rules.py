#!/usr/bin/env python3
"""
Runner for the C++ rules.hpp unit tests (gui/test_rules.cpp).

COMBAT_REFACTOR_PLAN.md's success criterion asks for direct unit tests of
rules.hpp that construct no CombatEngine and no BattleMap. Those have to be C++:
rules:: is not bound to pybind11, so anything reachable from Python necessarily
goes through a CombatEngine. This wrapper exists so the C++ suite still reports
through tests/run_all_tests.py alongside every other suite, per the tests/
convention in gui/CLAUDE.md.

The binary is produced by the normal build (`./compile.sh` → build/test_rules);
it is NOT installed next to main.py the way rpg_battle_map.so is, so this looks
for it in the build directory and fails loudly with build instructions if the
tree has not been built yet.
"""

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_binary():
    """Locate build/test_rules, allowing for multi-config generator subdirs."""
    candidates = [
        os.path.join(REPO_ROOT, "build", "test_rules"),
        # Multi-config generators (Xcode / MSVC) put binaries under a config dir.
        os.path.join(REPO_ROOT, "build", "Release", "test_rules"),
        os.path.join(REPO_ROOT, "build", "Debug", "test_rules"),
        os.path.join(REPO_ROOT, "build", "test_rules.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def main():
    binary = find_binary()
    if binary is None:
        print("ERROR: test_rules binary not found.")
        print("       Expected at build/test_rules — build the tree first:")
        print("           ./compile.sh")
        print("       (test_rules is built by the default target; it is not installed")
        print("        into gui/ the way rpg_battle_map.so is.)")
        return 1

    # No cwd requirement: unlike the Python suites, this test reads no data JSONs.
    result = subprocess.run([binary])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
