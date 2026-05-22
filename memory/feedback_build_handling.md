---
name: build-and-test-workflow
description: Building and running tests is now ALLOWED (via Docker). The old prohibition was an iCloud-sync problem, resolved by moving the repo out of ~/Documents.
metadata:
  type: feedback
---
**Building the C++ extension and running tests is permitted** (changed 2026-05-22).

**Why the prohibition existed, and why it's gone:** The repo used to live in
`~/Documents/Claude/Projects/DND`, an iCloud-tracked directory. iCloud syncing the
`build/` artifacts corrupted the build cache and caused git lock issues — that, not
builds per se, was the problem. The user fixed the root cause by moving the repo to
`~/Claude/DND` (outside iCloud). Builds no longer corrupt anything.

**How to build/test (verified working 2026-05-22):**
- Builds happen **inside Docker** — the host is macOS with no local `cmake`/`ninja`,
  and the produced `.so` is `cpython-312-x86_64-linux-gnu` (Linux/py3.12), not
  importable natively on the mac. Always go through the container.
- Image: `rpg_map`. Its `ENTRYPOINT` is `/bin/bash`, so pass `-c "..."` directly —
  do NOT write `bash -c` (that becomes `/bin/bash bash -c` → "cannot execute binary file").
- Mount `$HOME:/home/user`; the repo is at `/home/user/Claude/DND` in-container.
- Build (incremental; reuses the existing `build/` cache, already configured for this path):
  ```
  docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build --parallel && cmake --install build"
  ```
- Tests:
  ```
  docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND/gui && python3 run_all_tests.py"
  ```
- The committed `build.sh`/`test.sh`/`Dockerfile` comments still point at the stale
  `~/Documents/Claude/Projects/DND` path — ignore them; use `~/Claude/DND`.
- The user normally runs the container interactively (`docker run -it ... bash`);
  the non-interactive `-c "..."` form above is the agent-friendly equivalent.

Note: `CLAUDE.md` still carries the old "NEVER run commands" constraint — it predates
this fix. The user verbally overrode it; consider asking whether to update CLAUDE.md.
