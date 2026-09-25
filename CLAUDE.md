# CLAUDE.md

The project's full guidance lives in `gui/CLAUDE.md`, imported here so it loads when a
session starts at the repo root:

@gui/CLAUDE.md

## ⚠️ Never run anything on the macOS host

**Every build, test, and run happens in the `rpg_map` container. No exceptions.** Not the
whole suite, not one suite, not a "pure-Python" file that happens to import cleanly
(`tests/test_mapimg.py` included), not a quick `python3 -c` probe of the engine.

```bash
./test.sh                      # the whole suite, in the container
docker run --rm -v "$HOME":/home/user rpg_map \
  -c "cd /home/user/Claude/DND && python3 tests/<suite>.py"   # one suite
```

A host run is not a cheap first look. It cannot import the Linux/py3.12 `rpg_battle_map.so`,
so it tells you nothing about the code. Don't run one, don't quote its numbers, and don't
suggest one in a handoff, even as a warning of what goes wrong. Host-side tools that only
read files (`git`, `grep`, `sed`, an `ast` scan of source text) are fine; they don't run
the project.
