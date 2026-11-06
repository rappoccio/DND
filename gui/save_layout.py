"""Where every saved file lives (plans/SAVE_LAYOUT_PLAN.md, D12).

Stdlib only, like ``atomic_io``: the tools and the roster use it without the GUI. This
module is the only place that builds a save path; nothing else concatenates sidecar
names.

    <campaign>/                          campaign.json marks the root (D1)
      campaign.json  session.json
      pcs/<pc>.json                      one PC per file (D8)
      maps/<map>/<map>.<ext>             the art library (D2), plus optional
                 map.json  lighting.json
      <dungeon>/                         dungeon.json marks a dungeon (D4)
        dungeon.json
        maps/<map>/                      the dungeon's own copy, checked first (D3)
          <map>.<ext>  map.json  lighting.json
          encounters/<encounter>.json    creature groups on this map (D5)
        runs/<run>/                      a traversal's play state (D6)
          run.json  combat.json  autosave/slot_<k>/
          saves/                         one file per save (gui/saves.py)
        releases/<V n>/                  read-only snapshots (gui/releases.py)

**Child-first, copy-on-write (D3).** A dungeon map's file is read from the dungeon's copy
when one exists, else from the campaign library. Writes always go to the dungeon's copy
(``write_path``), so editing inside a dungeon never changes the library.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from atomic_io import atomic_write_json

LAYOUT_VERSION = 1

CAMPAIGN_FILE = "campaign.json"
SESSION_FILE  = "session.json"
DUNGEON_FILE  = "dungeon.json"
MAP_FILE      = "map.json"
LIGHTING_FILE = "lighting.json"
RUN_FILE      = "run.json"
COMBAT_FILE   = "combat.json"

PCS_DIR        = "pcs"
MAPS_DIR       = "maps"
ENCOUNTERS_DIR = "encounters"
RUNS_DIR       = "runs"
AUTOSAVE_DIR   = "autosave"
EFFECTS_DIR    = "effects"
SAVES_DIR      = "saves"
RELEASES_DIR   = "releases"
RELEASE_FILE   = "release.json"
START_DIR      = "start"

DEFAULT_RUN = "main"

# Searched in this order when a map folder holds more than one image.
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def slugify(name: str) -> str:
    """A file-safe name: lower case, runs of anything but letters and digits become one
    ``-``. ``"Java of the Indies"`` → ``"java-of-the-indies"``. Raises ValueError when
    nothing usable is left."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    if not slug:
        raise ValueError(f"no usable characters in name {name!r}")
    return slug


def unique_slug(seed: str, taken) -> str:
    """``slugify(seed)``, suffixed ``-2``, ``-3``, … until it is not in ``taken``."""
    base = slugify(seed)
    taken = set(taken)
    cand, n = base, 2
    while cand in taken:
        cand, n = f"{base}-{n}", n + 1
    return cand


def _check_name(name: str, what: str) -> str:
    """A folder or file name taken from a caller: one path component, nothing hidden.
    Guards every join below against ``..``, separators and empty names."""
    if (not isinstance(name, str) or not name or name in (".", "..")
            or name.startswith(".") or "/" in name or "\\" in name):
        raise ValueError(f"bad {what} name {name!r}")
    return name


def _subdirs(path: str) -> list[str]:
    try:
        return sorted(e.name for e in os.scandir(path)
                      if e.is_dir() and not e.name.startswith((".", "_")))
    except OSError:
        return []


def _json_stems(path: str) -> list[str]:
    try:
        return sorted(e.name[:-len(".json")] for e in os.scandir(path)
                      if e.is_file() and e.name.endswith(".json")
                      and not e.name.startswith("."))
    except OSError:
        return []


def find_image(folder: str, map_name: str) -> str | None:
    """``<folder>/<map_name>.<ext>`` for the first extension in IMAGE_EXTS present."""
    for ext in IMAGE_EXTS:
        p = os.path.join(folder, map_name + ext)
        if os.path.isfile(p):
            return p
    return None


def find_campaign(path: str) -> str | None:
    """The campaign root holding ``path`` (a file or a directory): the nearest directory,
    ``path`` itself included, that contains ``campaign.json``. None outside any campaign."""
    d = os.path.abspath(path)
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while True:
        if os.path.isfile(os.path.join(d, CAMPAIGN_FILE)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


@dataclass(frozen=True)
class Campaign:
    root: str

    @classmethod
    def create(cls, root: str, name: str | None = None) -> "Campaign":
        """Make ``root`` a campaign: write ``campaign.json`` and the empty ``pcs/`` and
        ``maps/``. Refuses a directory that already is one, or sits inside one."""
        root = os.path.abspath(root)
        if find_campaign(root) is not None:
            raise ValueError(f"{root} is already inside a campaign")
        os.makedirs(os.path.join(root, PCS_DIR), exist_ok=True)
        os.makedirs(os.path.join(root, MAPS_DIR), exist_ok=True)
        atomic_write_json(os.path.join(root, CAMPAIGN_FILE),
                          {"version": LAYOUT_VERSION,
                           "name": name or os.path.basename(root)})
        return cls(root)

    @classmethod
    def open(cls, path: str) -> "Campaign":
        """The campaign holding ``path``. Raises ValueError outside any campaign."""
        root = find_campaign(path)
        if root is None:
            raise ValueError(f"{path} is not inside a campaign (no {CAMPAIGN_FILE})")
        return cls(root)

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.root, CAMPAIGN_FILE)

    @property
    def name(self) -> str:
        try:
            with open(self.manifest_path) as f:
                return str(json.load(f).get("name") or os.path.basename(self.root))
        except (OSError, ValueError):
            return os.path.basename(self.root)

    # ── Table and party ───────────────────────────────────────────────────
    @property
    def session_path(self) -> str:
        """Join code and seats, one per campaign (D9)."""
        return os.path.join(self.root, SESSION_FILE)

    @property
    def pcs_dir(self) -> str:
        return os.path.join(self.root, PCS_DIR)

    def pc_path(self, pc_name: str) -> str:
        """``pcs/<slug>.json`` for a character's display name."""
        return os.path.join(self.pcs_dir, slugify(pc_name) + ".json")

    def list_pcs(self) -> list[str]:
        """Paths of every saved PC, by file name."""
        return [os.path.join(self.pcs_dir, s + ".json") for s in _json_stems(self.pcs_dir)]

    # ── Map library ───────────────────────────────────────────────────────
    @property
    def maps_dir(self) -> str:
        return os.path.join(self.root, MAPS_DIR)

    def library_map_dir(self, map_name: str) -> str:
        return os.path.join(self.maps_dir, _check_name(map_name, "map"))

    def list_library_maps(self) -> list[str]:
        return _subdirs(self.maps_dir)

    # ── Dungeons ──────────────────────────────────────────────────────────
    def dungeon(self, dungeon_name: str) -> "DungeonLayout":
        return DungeonLayout(self, _check_name(dungeon_name, "dungeon"))

    def list_dungeons(self) -> list[str]:
        """Child folders holding a ``dungeon.json``."""
        return [d for d in _subdirs(self.root)
                if d not in (PCS_DIR, MAPS_DIR)
                and os.path.isfile(os.path.join(self.root, d, DUNGEON_FILE))]


@dataclass(frozen=True)
class DungeonLayout:
    campaign: Campaign
    name: str

    @property
    def root(self) -> str:
        return os.path.join(self.campaign.root, self.name)

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.root, DUNGEON_FILE)

    # ── Maps (D3) ─────────────────────────────────────────────────────────
    def map_dir(self, map_name: str) -> str:
        """The dungeon's own folder for a map: where its overrides and encounters live."""
        return os.path.join(self.root, MAPS_DIR, _check_name(map_name, "map"))

    def resolve(self, map_name: str, filename: str) -> str | None:
        """The file to read for one of a map's files (``map.json``, ``lighting.json``):
        the dungeon's copy, else the library's, else None."""
        _check_name(filename, "file")
        for d in (self.map_dir(map_name), self.campaign.library_map_dir(map_name)):
            p = os.path.join(d, filename)
            if os.path.isfile(p):
                return p
        return None

    def write_path(self, map_name: str, filename: str) -> str:
        """Where a write of one of a map's files goes: always the dungeon's copy."""
        return os.path.join(self.map_dir(map_name), _check_name(filename, "file"))

    def image(self, map_name: str) -> str | None:
        """The map's art: the dungeon's copy (e.g. rescaled to the grid), else the
        library original, else None."""
        return (find_image(self.map_dir(map_name), map_name)
                or find_image(self.campaign.library_map_dir(map_name), map_name))

    def image_is_local(self, map_name: str) -> bool:
        return find_image(self.map_dir(map_name), map_name) is not None

    def calibration_warning(self, map_name: str) -> str | None:
        """A grid is calibrated for one image. The dungeon's own image read with the
        library's ``map.json`` (or none) is probably misaligned: say so, else None."""
        if not self.image_is_local(map_name):
            return None
        if os.path.isfile(self.write_path(map_name, MAP_FILE)):
            return None
        return (f"{self.name}/{MAPS_DIR}/{map_name} has its own image but no "
                f"{MAP_FILE}; the grid may not match it")

    def list_maps(self) -> list[str]:
        """Maps with a folder in this dungeon. ``dungeon.json`` is the authority on which
        maps the dungeon uses; this lists only those with local files."""
        return _subdirs(os.path.join(self.root, MAPS_DIR))

    # ── Encounters (D5) ───────────────────────────────────────────────────
    def encounters_dir(self, map_name: str) -> str:
        return os.path.join(self.map_dir(map_name), ENCOUNTERS_DIR)

    def encounter_path(self, map_name: str, encounter_name: str) -> str:
        return os.path.join(self.encounters_dir(map_name),
                            _check_name(encounter_name, "encounter") + ".json")

    def list_encounters(self, map_name: str) -> list[str]:
        return _json_stems(self.encounters_dir(map_name))

    # ── Runs (D6, D10) ────────────────────────────────────────────────────
    @property
    def runs_dir(self) -> str:
        return os.path.join(self.root, RUNS_DIR)

    def run_dir(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.runs_dir, _check_name(run_name, "run"))

    def run_path(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.run_dir(run_name), RUN_FILE)

    def combat_path(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.run_dir(run_name), COMBAT_FILE)

    def autosave_dir(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.run_dir(run_name), AUTOSAVE_DIR)

    def effects_dir(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.run_dir(run_name), EFFECTS_DIR)

    def saves_dir(self, run_name: str = DEFAULT_RUN) -> str:
        return os.path.join(self.run_dir(run_name), SAVES_DIR)

    def list_runs(self) -> list[str]:
        """Runs that have been saved (a ``run.json`` exists)."""
        return [r for r in _subdirs(self.runs_dir)
                if os.path.isfile(os.path.join(self.runs_dir, r, RUN_FILE))]

    # ── Releases (gui/releases.py) ────────────────────────────────────────
    @property
    def releases_dir(self) -> str:
        return os.path.join(self.root, RELEASES_DIR)

    def release_dir(self, release_name: str) -> str:
        return os.path.join(self.releases_dir, _check_name(release_name, "release"))

    def list_release_dirs(self) -> list[str]:
        return _subdirs(self.releases_dir)
