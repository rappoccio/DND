"""A dungeon's releases: numbered, read-only snapshots (plans/DUNGEON_RELEASES_PLAN.md D1–D2).

    <dungeon>/releases/V0/
      release.json        name, note, timestamp, the run it came from, current map
      dungeon.json        copy
      maps/<map>/         copy of the dungeon's own files: map.json, lighting.json,
                          encounters and local images. A map.json or lighting.json that
                          resolves to the library is copied here too; library art is not,
                          because nothing inside a dungeon changes the library.
      start/run.json      the board when the release was made, PCs included
      start/effects/

A reset puts a release's design back too (``restore_design``); the design it replaces is
moved to ``<dungeon>/design_backups/<time>/``.

**A release appears whole or not at all.** It is built in a hidden folder beside the others
and renamed into place last, so a crash leaves nothing that lists as a release. Nothing here
overwrites or deletes a release.

Stdlib only. The app saves the live scene and refuses a running fight before calling
``create``; this module works on the files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass

import run_state as rs
import save_layout as sl
from atomic_io import atomic_write_json
from dungeon import Dungeon

RELEASE_VERSION = 1

# Where a reset puts the design it replaces (``restore_design``).
DESIGN_BACKUPS_DIR = "design_backups"

_NAME = re.compile(r"V(\d+)$")


@dataclass(frozen=True)
class Release:
    root: str
    name: str
    note: str
    timestamp: float
    run: str
    current_map: str | None

    @property
    def number(self) -> int:
        return int(_NAME.match(self.name).group(1))

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.root, sl.DUNGEON_FILE)

    @property
    def maps_dir(self) -> str:
        return os.path.join(self.root, sl.MAPS_DIR)

    @property
    def start_run_path(self) -> str:
        return os.path.join(self.root, sl.START_DIR, sl.RUN_FILE)

    @property
    def start_effects_dir(self) -> str:
        return os.path.join(self.root, sl.START_DIR, sl.EFFECTS_DIR)

    def start_run(self) -> dict:
        """The board this release starts from, as a fresh run document."""
        return rs.load_run(self.start_run_path)

    def label(self) -> str:
        """One menu row: name, date, and the note if it has one."""
        when = time.strftime("%b %-d %H:%M", time.localtime(self.timestamp))
        return f"{self.name} · {when}" + (f" · {self.note}" if self.note else "")


def _read(layout: "sl.DungeonLayout", name: str) -> Release | None:
    """The release in folder ``name``, or None if it is not one this version can read."""
    root = layout.release_dir(name)
    try:
        with open(os.path.join(root, sl.RELEASE_FILE)) as f:
            doc = json.load(f)
        if int(doc.get("version", 0)) > RELEASE_VERSION:
            return None
        return Release(root=root, name=name, note=str(doc.get("note") or ""),
                       timestamp=float(doc.get("timestamp", 0)),
                       run=str(doc.get("run") or sl.DEFAULT_RUN),
                       current_map=doc.get("current_map"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _numbered(layout: "sl.DungeonLayout") -> list[str]:
    """Folder names of the form ``V<n>``, lowest number first."""
    names = [n for n in layout.list_release_dirs() if _NAME.match(n)]
    return sorted(names, key=lambda n: int(_NAME.match(n).group(1)))


def list_releases(layout: "sl.DungeonLayout") -> list[Release]:
    """Every readable release, newest first."""
    found = (_read(layout, n) for n in reversed(_numbered(layout)))
    return [r for r in found if r is not None]


def newest(layout: "sl.DungeonLayout") -> Release | None:
    found = list_releases(layout)
    return found[0] if found else None


def get(layout: "sl.DungeonLayout", name: str) -> Release | None:
    return _read(layout, name)


def next_name(layout: "sl.DungeonLayout") -> str:
    """The next ``V<n>``, one past the highest folder, so a number is never reused even
    when that folder cannot be read."""
    names = _numbered(layout)
    return f"V{int(_NAME.match(names[-1]).group(1)) + 1}" if names else "V0"


def _copy_design(layout: "sl.DungeonLayout", dungeon: Dungeon, dest: str) -> None:
    shutil.copyfile(layout.manifest_path, os.path.join(dest, sl.DUNGEON_FILE))
    maps = os.path.join(dest, sl.MAPS_DIR)
    local = os.path.join(layout.root, sl.MAPS_DIR)
    if os.path.isdir(local):
        shutil.copytree(local, maps)
    else:
        os.makedirs(maps)
    for page in dungeon.pages:
        for filename in (sl.MAP_FILE, sl.LIGHTING_FILE):
            src = layout.resolve(page.id, filename)
            out = os.path.join(maps, page.id, filename)
            if src is not None and not os.path.exists(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copyfile(src, out)


def _copy_start(layout: "sl.DungeonLayout", run_name: str, dungeon: Dungeon,
                dest: str) -> str | None:
    """The run's board into ``dest``'s ``start/``. Returns the map it was on."""
    start = os.path.join(dest, sl.START_DIR)
    os.makedirs(start)
    path = layout.run_path(run_name)
    entry = dungeon.entry_page()
    run = (rs.load_run(path) if os.path.exists(path)
           else rs.new_run(entry.id if entry else None))
    rs.save_run(os.path.join(start, sl.RUN_FILE), run)
    effects = layout.effects_dir(run_name)
    if os.path.isdir(effects):
        shutil.copytree(effects, os.path.join(start, sl.EFFECTS_DIR))
    return run.get("current_map") or (entry.id if entry else None)


def image(layout: "sl.DungeonLayout", release: Release, map_name: str) -> str | None:
    """The art ``map_name`` shows once ``release``'s design is back: its own copy, else the
    library's."""
    return (sl.find_image(os.path.join(release.maps_dir, map_name), map_name)
            or sl.find_image(layout.campaign.library_map_dir(map_name), map_name))


def restore_design(layout: "sl.DungeonLayout", release: Release) -> str:
    """Make ``release``'s design the dungeon's: its ``dungeon.json`` and ``maps/``. The design
    replaced is moved to ``design_backups/<time>/`` first, never deleted, so a reset cannot
    destroy a map edit. Returns that folder. On failure the dungeon's design is unchanged."""
    root = os.path.join(layout.root, DESIGN_BACKUPS_DIR, time.strftime("%Y%m%d-%H%M%S"))
    backup, n = root, 1
    while os.path.exists(backup):
        backup, n = f"{root}-{n}", n + 1
    os.makedirs(backup)
    shutil.copyfile(layout.manifest_path, os.path.join(backup, sl.DUNGEON_FILE))

    maps = os.path.join(layout.root, sl.MAPS_DIR)
    old = os.path.join(backup, sl.MAPS_DIR)
    staged = os.path.join(layout.root, f".{sl.MAPS_DIR}.restore.{os.getpid()}")
    manifest_tmp = f"{layout.manifest_path}.restore.{os.getpid()}"
    moved = False
    try:
        shutil.copytree(release.maps_dir, staged)
        shutil.copyfile(release.manifest_path, manifest_tmp)
        if os.path.isdir(maps):
            os.rename(maps, old)
            moved = True
        os.rename(staged, maps)
        os.replace(manifest_tmp, layout.manifest_path)
    except BaseException:
        if moved and not os.path.isdir(maps):
            os.rename(old, maps)
        shutil.rmtree(staged, ignore_errors=True)
        try:
            os.remove(manifest_tmp)
        except OSError:
            pass
        raise
    return backup


def create(layout: "sl.DungeonLayout", run_name: str = sl.DEFAULT_RUN,
           note: str = "") -> Release:
    """Snapshot the dungeon's design and ``run_name``'s board as the next ``V<n>``."""
    name = next_name(layout)
    os.makedirs(layout.releases_dir, exist_ok=True)
    tmp = os.path.join(layout.releases_dir, f".{name}.tmp.{os.getpid()}")
    try:
        os.makedirs(tmp)
        dungeon = Dungeon.load(layout.manifest_path)
        _copy_design(layout, dungeon, tmp)
        current = _copy_start(layout, run_name, dungeon, tmp)
        atomic_write_json(os.path.join(tmp, sl.RELEASE_FILE), {
            "version":     RELEASE_VERSION,
            "name":        name,
            "note":        note,
            "timestamp":   time.time(),
            "run":         run_name,
            "current_map": current,
        })
        os.rename(tmp, layout.release_dir(name))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return _read(layout, name)
