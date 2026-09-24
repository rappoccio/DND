---
name: build-and-test-workflow
description: Build/test permission is MODEL-GATED — Opus may build and run the suite without asking; Haiku & Sonnet never. Commits happen on request; pushes are a separate ask.
metadata:
  type: feedback
---
**Updated 2026-09-21: building and testing no longer need a per-session go-ahead on Opus**
("You're allowed to build and test now"). `gui/CLAUDE.md`'s "RUNNING COMMANDS" section is
the authority; this file is the background.

**Build/test permission depends on which model is running (user decision 2026-06-02,
widened 2026-09-21):**
- **Opus MAY build AND run the test suite, without asking first.** The gate is the model
  tier, not an exact version — it was first granted to "4.8" and confirmed live on Opus 5.
- **Haiku & Sonnet MUST NOT build or run tests, ever.** Hand the `docker run` line back.
  The user enforces this by switching models (observed: they ran `/model opus` and *then*
  said "build and test" rather than overriding the rule), so treat it as real.

**Why the original prohibition existed, and why it's gone:** the repo used to live in an
iCloud-tracked directory; iCloud syncing `build/` artifacts corrupted the cache and caused
git lock issues. The user fixed the root cause by moving the repo to `~/Claude/DND`
(outside iCloud), so builds no longer corrupt anything.

**How to build (verified env 2026-06-02, still current 2026-09-21):**
- **Everything runs in Linux, in the `rpg_map` image — building, testing AND running the
  app. There is no supported native macOS path** (user decision 2026-09-24: "I don't want
  to run this on the native MacOS, it should always be in Linux"). No native
  `cmake`/`ninja` on the host, and the produced `.so` is a Linux/py3.12 build a host
  Python cannot import.
- **Never reach for a quick host test run.** It fails ~151 suites with
  `ModuleNotFoundError: rpg_battle_map`, which reads like a catastrophic regression and is
  only the host's PYTHONPATH. Two files are deliberate exceptions and license nothing
  else: `tests/test_mapimg.py` (PIL-only, host-runnable, good for fast mutant cycling) and
  `tests/manual_fog_xvfb.py` (container *plus* an Xvfb display, not in the runner).
- Image `ENTRYPOINT` is `/bin/bash` — pass `-c "..."` directly (do NOT write `bash -c`).
- `./test.sh` does configure + build + install + the whole suite. `./build.sh` builds only.
- One suite, incremental:
  ```
  docker run --rm -v "$HOME":/home/user rpg_map -c "cd /home/user/Claude/DND && python3 tests/test_prompts.py"
  ```
- Pure `main.py` edits need no rebuild. Re-running is `./run.sh`, also a container launch.
- A `Dockerfile` change (a new pip dependency — `aiohttp` for M4) needs
  `docker build -t rpg_map .`, which installs, so it is the user's call.

**Git, unchanged:** the user owns git. **Commit only when asked** — a direct request is
enough and is common ("commit and mark it done"); **pushing is a separate ask** and every
refactor commit so far sits unpushed on `main` on purpose. Never `git add -A` (this tree
carries a lot of untracked scratch); stage by name, and never stage `build/` or
`replay_log.txt`.
