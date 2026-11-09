"""Release and Reset Dungeon: what the DM does to a run (plans/DUNGEON_RELEASES_PLAN.md).

``releases.py`` holds the files; this module does what the live App needs around them. A
reset puts back everything the release holds: the run, its effects and the design, so map
edits made since the release are reverted too (D3, amended 2026-11-09; the replaced design
goes to ``design_backups/``). Seats stay, and every seated player gets a fresh view (D4).
A campaign dungeon opened with no release gets ``V0`` on the spot, so a reset always has
somewhere to go (D11).
"""

from __future__ import annotations

from collections import Counter

import autosave
import releases
import run_state as rs
import saves
from dungeon import Dungeon
from scene_store import CampaignStore

_CAMPAIGN_ONLY = "Only a campaign dungeon has releases."


def _store(app):
    """The campaign store, or None after saying why not (D10)."""
    if isinstance(app.store, CampaignStore):
        return app.store
    app._flash_status(_CAMPAIGN_ONLY)
    return None


# ── Release ──────────────────────────────────────────────────────────────────
def make_release(app):
    """Snapshot the dungeon as the next ``V<n>`` (D2). Returns the release, or None."""
    store = _store(app)
    if store is None:
        return None
    if app.combat_active:
        app._flash_status("Finish combat before making a release.")
        return None
    try:
        app._save_agents()
        app._save_terrain()
        if not app._dungeon_save_manifest():
            return None
        release = releases.create(store.layout, store.run_name)
    except (OSError, ValueError) as e:
        app._flash_status(f"Could not make a release: {e}")
        return None
    app._flash_status(f"Released {release.name}")
    return release


def ensure_first_release(app):
    """``V0`` from the files as they are, when a campaign dungeon has no release yet (D11).
    Called as the dungeon opens, before anything is played. Returns the release made, or
    None. Never raises: a dungeon that cannot be snapshotted still opens."""
    store = app.store
    if not isinstance(store, CampaignStore) or releases.list_releases(store.layout):
        return None
    try:
        release = releases.create(store.layout, store.run_name, note="opened")
    except Exception as e:                       # noqa: BLE001 — see the docstring
        print(f"Warning: could not make the first release: {e}")
        return None
    print(f"Made the first release, {release.name}, of {store.layout.name}")
    return release


def show_releases_menu(app, anchor=None, parent=None):
    """Every release, newest first. Picking one offers a reset to it."""
    store = _store(app)
    if store is None:
        return
    found = releases.list_releases(store.layout)
    if not found:
        app._flash_status("No releases yet.")
        return
    options = [(r.label(), lambda r=r: ask_reset(app, r, anchor=anchor,
                                                 parent=app.prompts.answering))
               for r in found]
    app._ask_dm("action", "Releases", options, anchor=anchor, parent=parent)


# ── Reset ────────────────────────────────────────────────────────────────────
def ask_reset(app, release=None, anchor=None, parent=None):
    """Confirm, then reset to ``release``, by default the newest (D4)."""
    store = _store(app)
    if store is None:
        return
    release = release or releases.newest(store.layout)
    if release is None:
        app._flash_status("Make a Release first.")
        return
    app._ask_dm("action", reset_warning(release),
                [(f"Reset to {release.name}", lambda: reset_to(app, release)),
                 ("Cancel", lambda: None)], anchor=anchor, parent=parent)


def reset_warning(release) -> str:
    return (f"WARNING: reset the dungeon to {release.name}? Creatures, doors, fog, effects "
            f"and every map edit since then are reverted.")


def _lost_on_load(app, run: dict, map_name: str) -> list[str]:
    """Names in the run's section for the map that did not get placed. A wall fix can land
    on a released creature's cell, and the load skips a creature on a blocked cell."""
    wanted = Counter(a.get("name") for a in rs.creatures(run, map_name)["agents"])
    wanted.subtract(pt.name for pt in app.bm.placed_agents)
    return sorted(n for n, count in wanted.items() if count > 0)


def reset_to(app, release) -> bool:
    """Put the dungeon back to ``release``: its design and its starting board. Returns True
    when it did. A refusal flashes its reason and changes nothing."""
    store = _store(app)
    if store is None:
        return False
    why = autosave.restore_blocked(app)
    if why is not None:
        app._flash_status(f"Not reset: {why}")
        return False
    try:
        run = release.start_run()
        design = Dungeon.load(release.manifest_path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        app._flash_status(f"Not reset: {release.name} is unreadable ({e})")
        return False
    page = design.page_by_id(release.current_map) or design.entry_page()
    if page is None or not releases.image(store.layout, release, page.id):
        app._flash_status(f"Not reset: no map to show for {release.name}")
        return False
    # The way back from an accidental reset (D4): play state in a save, the design in a
    # backup folder. No save means no reset.
    try:
        saves.write(app, saves.BEFORE_RESET)
    except (OSError, ValueError) as e:
        app._flash_status(f"Not reset: could not save the board first ({e})")
        return False
    try:
        backup = releases.restore_design(store.layout, release)
        app.dungeon = Dungeon.load(store.layout.manifest_path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        app._flash_status(f"Not reset: could not restore the maps ({e})")
        return False
    print(f"Reset to {release.name}: the replaced design is in {backup}")
    page = app.dungeon.page_by_id(page.id)
    if not saves.swap_run(app, run, release.start_effects_dir, page, reload_map=True):
        return False                      # swap_run has flashed why
    autosave.resync_players(app)

    lost = _lost_on_load(app, run, page.id)
    app._combat_log_add(f"[RESET] dungeon reset to {release.name}")
    app._flush_combat_log()
    app.session_log.add(f"The DM reset the dungeon to {release.name}.")
    if lost:
        names = ", ".join(lost)
        print(f"Warning: reset to {release.name}: blocked cell, not placed: {names}")
        app._flash_status(f"Reset to {release.name}. Blocked cell, not placed: {names}", 6.0)
    else:
        app._flash_status(f"Reset to {release.name}")
    return True
