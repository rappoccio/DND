"""Atomic JSON writes.

Stdlib only, and deliberately so: `main.py` and `net/roster.py` both need this and the
roster is required to stay importable without the GUI.

The bug this exists to remove: ``open(path, "w")`` truncates the file *before* the new
bytes are written, so a crash — or a reader that arrives mid-write — sees a zero-length or
half-written save. Rare when a save is a deliberate menu action; common once NN7 autosaves
at every turn boundary (MULTIPLAYER_PLAN.md, standalone item S1). Serializing to a temp
file in the same directory and then ``os.replace()`` makes the swap atomic: a reader gets
the old file or the new one, never a torn one.
"""

from __future__ import annotations

import json
import os


def atomic_write_json(path: str, doc, *, indent: int = 2) -> None:
    """Serialize `doc` to `path` as JSON, atomically.

    The temp file is a sibling of the target, because ``os.replace`` is only atomic
    within one filesystem. It is removed on any failure, including a `doc` that does not
    serialize, so a failed save never leaves litter next to the real file.
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
