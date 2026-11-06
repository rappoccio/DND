"""Release and Reset Dungeon: what the DM does to a run (plans/DUNGEON_RELEASES_PLAN.md).

``releases.py`` holds the files; this module does what the live App needs around them. A
campaign dungeon's design and play state are already separate, so a reset swaps the run and
reloads the scene, and map fixes made since the release stay (D3). Seats stay too, and every
seated player gets a fresh view (D4).
"""

from __future__ import annotations

from collections import Counter

import autosave
import releases
import run_state as rs
import saves
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
    app._ask_dm("action", f"Reset the dungeon to {release.name}?",
                [(f"Reset to {release.name}", lambda: reset_to(app, release)),
                 ("Cancel", lambda: None)], anchor=anchor, parent=parent)


def _lost_on_load(app, run: dict, map_name: str) -> list[str]:
    """Names in the run's section for the map that did not get placed. A wall fix can land
    on a released creature's cell, and the load skips a creature on a blocked cell."""
    wanted = Counter(a.get("name") for a in rs.creatures(run, map_name)["agents"])
    wanted.subtract(pt.name for pt in app.bm.placed_agents)
    return sorted(n for n, count in wanted.items() if count > 0)


def reset_to(app, release) -> bool:
    """Put the run back to ``release``'s starting board. Returns True when it did. A refusal
    flashes its reason and changes nothing."""
    store = _store(app)
    if store is None:
        return False
    why = autosave.restore_blocked(app)
    if why is not None:
        app._flash_status(f"Not reset: {why}")
        return False
    try:
        run = release.start_run()
    except (OSError, ValueError) as e:
        app._flash_status(f"Not reset: {release.name} is unreadable ({e})")
        return False
    page = app.dungeon.page_by_id(release.current_map) or app.dungeon.entry_page()
    if page is None or not store.image(page):
        app._flash_status(f"Not reset: no map to show for {release.name}")
        return False
    # The way back from an accidental reset (D4). No save means no reset.
    try:
        saves.write(app, saves.BEFORE_RESET)
    except (OSError, ValueError) as e:
        app._flash_status(f"Not reset: could not save the board first ({e})")
        return False
    if not saves.swap_run(app, run, release.start_effects_dir, page):
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
