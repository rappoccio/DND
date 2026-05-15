#!/usr/bin/env python3
"""
Master test runner for all Python test suites.
Runs all test scripts and reports overall results.
"""

import subprocess
import sys
import os

test_scripts = [
    "test_conditions.py",
    "test_combat.py",
    "test_spells.py",
    "test_movement.py",
    "test_visibility.py",
]

def run_tests():
    """Run all test scripts and collect results."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    total_passed = 0
    total_failed = 0
    failed_scripts = []

    print("\n" + "=" * 70)
    print("  RUNNING ALL TEST SUITES")
    print("=" * 70 + "\n")

    for script in test_scripts:
        script_path = os.path.join(script_dir, script)
        print(f"\n{'=' * 70}")
        print(f"Running: {script}")
        print(f"{'=' * 70}\n")

        result = subprocess.run([sys.executable, script_path], cwd=script_dir)

        if result.returncode != 0:
            failed_scripts.append(script)
            total_failed += 1
        else:
            total_passed += 1

    print("\n" + "=" * 70)
    print("  OVERALL TEST RESULTS")
    print("=" * 70)
    print(f"Test suites passed: {total_passed}")
    print(f"Test suites failed: {total_failed}")

    if failed_scripts:
        print(f"\nFailed suites:")
        for script in failed_scripts:
            print(f"  - {script}")
    else:
        print("\n✓ All test suites passed!")

    print("=" * 70 + "\n")

    return 0 if total_failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_tests())
