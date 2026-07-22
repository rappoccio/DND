---
name: build-and-test-workflow
description: Build permission is MODEL-GATED — Opus 4.8 may build via Docker; Haiku & Sonnet must never build. User owns git commits.
metadata:
  type: feedback
---
**Build/test permission depends on which model is running (user decision 2026-06-02):**
- **Opus 4.8 MAY build AND run the test suite.** ("I'm willing to give it a shot with 4.8" /
  "You can run it [tests] in the future.")
- **Haiku & Sonnet MUST NOT build or run tests, ever.** Hand the build/test back to the user.

**Why the original prohibition existed, and why it's relaxed:** The repo used to live in an
iCloud-tracked directory; iCloud syncing `build/` artifacts corrupted the cache and caused git
lock issues. The user fixed the root cause by moving the repo to `~/Claude/DND` (outside iCloud),
so builds no longer corrupt anything.

**How to build (verified env 2026-06-02):**
- No native `cmake`/`ninja` on the macOS host; the produced `.so` is
  `cpython-312-x86_64-linux-gnu` (Linux/py3.12). Always build inside the `rpg_map` Docker image.
- Image `ENTRYPOINT` is `/bin/bash` — pass `-c "..."` directly (do NOT write `bash -c`).
- Build (incremental; reuses the configured `build/`):
  ```
  docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && cmake -S ./gui -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build --parallel && cmake --install build"
  ```
- Tests:
  ```
  docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && python3 tests/run_all_tests.py"
  ```

**Always hands-off regardless of model:** user owns all git commits (never commit/push); never
stage `build/` or `replay_log.txt`. The committed `build.sh`/`test.sh`/`Dockerfile` comments
still point at the stale `~/Documents/...` path — ignore them; the repo is at `~/Claude/DND`.
