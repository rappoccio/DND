#!/usr/bin/env python3
"""The lighting editor's base-light button (MULTIPLAYER_PLAN_OWED.md item 10).

The editor had no suite at all, and the gap cost a live session. A DM opened
`maps/TestDNDMap.png`, authored `"default_light": "Darkness"`, and found the board fogged
for himself and for every player: `revealFogForFaction` ORs in only what `canSee` accepts,
and in the dark `canSee` is `darkvision_ft > 0 && dist_ft <= darkvision_ft`, so a party
with no darkvision reveals nothing — not even the cell it stands on. The engine was right
and the scene was pitch black, and the editor offered **no way to turn the lights up**:
Add Light, Remove, a level button that sets the level of the NEXT PLACED SOURCE, Done and
Cancel. `default_light` was read from the file and handed straight back to it.

Four checks, and the middle two are the ones that matter:

  · the button cycles the base and says which one it is now;
  · **Done reaches the battle map**, on a map with no light sources at all — the case that
    motivated the button, and the case the old `_apply_light_effects` early-returned out
    of. A base level that only reaches the file is a light switch that does nothing;
  · **Done reaches the file**, so the level survives a reload;
  · the dialog's own default agrees with the two readers of an absent `"default_light"`.

Nothing here draws. The editor's pixels stay `test_gui_headless_smoke.py`'s business; this
asks what the pixels cannot, which is whether the lights actually came on.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260924

_TMP = tempfile.mkdtemp(prefix="lighting_editor_")


def _app():
    """A real App, with its lighting file redirected into a temp dir: Done WRITES, and
    `maps/` already has one tracked fixture a manual pass can clobber (item 8, finding 2)."""
    app = App(MAP_PATH, seed=SEED)
    app._lighting_path = os.path.join(_TMP, "probe_lighting.json")
    return app


def _some_cell(bm):
    return rpg.Cell(bm.grid_cols // 2, bm.grid_rows // 2)


def test_the_base_button_cycles_and_relabels():
    """It walks `light_level_choices` and the label follows it. A button whose text never
    changes is how the existing level button was misread as the base in the first place."""
    app = _app()
    ed = app.lighting_editor
    ed.open(app.map_surf, app.bm, app, [], rpg.VisibilityLevel.Dark)

    assert 'cycle_base' in ed.buttons, "the editor has no base-light button"
    assert ed.buttons['cycle_base'].text == "Base Light: Dark", \
        f"open() did not label the base it was handed: {ed.buttons['cycle_base'].text!r}"

    seen = [ed.default_light]
    for _ in range(len(ed.light_level_choices)):
        ed._handle_button('cycle_base')
        seen.append(ed.default_light)
        name = dict(ed.light_level_choices)[ed.default_light]
        assert ed.buttons['cycle_base'].text == f"Base Light: {name}", \
            f"label out of step with the level: {ed.buttons['cycle_base'].text!r} vs {name}"

    assert set(seen) == {lvl for lvl, _ in ed.light_level_choices}, \
        f"a full cycle did not reach every level: {seen}"
    assert seen[0] == seen[-1], "a full cycle did not come back round"

    # The other button is untouched by it — they are two different levels.
    assert ed.pending_light_level == rpg.VisibilityLevel.Sunlight, \
        "cycling the base moved the next-placed-source level too"
    print("✅ test_the_base_button_cycles_and_relabels passed")


def test_done_lights_the_map_with_no_sources_on_it():
    """The whole point. No torches anywhere — the old `_apply_light_effects` early-returned
    on the empty list, so the base never reached `apply_base_lighting` and the DM's screen
    stayed exactly as dark as before."""
    app = _app()
    ed = app.lighting_editor
    cell = _some_cell(app.bm)

    ed.open(app.map_surf, app.bm, app, [], rpg.VisibilityLevel.Clear)
    ed.default_light = rpg.VisibilityLevel.Dark
    ed._handle_button('done')
    assert app.bm.get_light_level(cell) == rpg.VisibilityLevel.Dark, \
        "Done did not darken the map"

    ed.open(app.map_surf, app.bm, app, [], rpg.VisibilityLevel.Dark)
    ed._handle_button('cycle_base')                      # Dark -> MagicalDark
    ed._handle_button('cycle_base')                      # MagicalDark -> Sunlight
    ed._handle_button('cycle_base')                      # Sunlight -> Clear
    assert ed.default_light == rpg.VisibilityLevel.Clear, f"cycled to {ed.default_light}"
    ed._handle_button('done')
    assert app.bm.get_light_level(cell) == rpg.VisibilityLevel.Clear, \
        "the lights did not come back up: Done reached the file but not the battle map"
    print("✅ test_done_lights_the_map_with_no_sources_on_it passed")


def test_done_writes_the_base_so_it_survives_a_reload():
    """`_save_lighting_no_reload` already took a base; nothing could change it. Now that
    something can, the round trip through the file has to hold, because `_load_lighting`
    is what every later session reads."""
    app = _app()
    ed = app.lighting_editor
    cell = _some_cell(app.bm)

    ed.open(app.map_surf, app.bm, app, [], rpg.VisibilityLevel.Clear)
    ed.default_light = rpg.VisibilityLevel.Dark
    ed._handle_button('done')

    on_disk = json.load(open(app._lighting_path))
    assert on_disk["default_light"] == "Darkness", \
        f"the file kept the old base: {on_disk['default_light']!r}"

    app.bm.apply_base_lighting(rpg.VisibilityLevel.Clear, [])   # scrub, then reload
    app._load_lighting()
    assert app.bm.get_light_level(cell) == rpg.VisibilityLevel.Dark, \
        "a reload did not restore the base the editor saved"

    # And the editor re-opens showing what the file says, not what it last cycled to.
    app._lighting_path = app._lighting_path            # same file
    ed.open(app.map_surf, app.bm, app, [],
            app._parse_light_level(on_disk["default_light"]))
    assert ed.buttons['cycle_base'].text == "Base Light: Dark", \
        f"re-opened on a stale label: {ed.buttons['cycle_base'].text!r}"
    print("✅ test_done_writes_the_base_so_it_survives_a_reload passed")


def test_removing_the_last_light_puts_it_out():
    """The same early return hid a second defect: with no sources left, Done cleared
    nothing, so the light the DM had just deleted went on burning until the next load."""
    app = _app()
    ed = app.lighting_editor

    ed.open(app.map_surf, app.bm, app, [], rpg.VisibilityLevel.Dark)
    ed._add_light_at(app.bm.grid_cols // 2, app.bm.grid_rows // 2)
    ed._handle_button('done')
    lit = _some_cell(app.bm)
    assert app.bm.get_light_level(lit) != rpg.VisibilityLevel.Dark, \
        "the placed light never lit anything — this test proves nothing as written"

    ed.open(app.map_surf, app.bm, app, ed.light_sources, rpg.VisibilityLevel.Dark)
    ed.selected_source_idx = 0
    ed._handle_button('remove')
    assert ed.light_sources == [], "Remove did not remove the only light"
    ed._handle_button('done')
    assert app.bm.get_light_level(lit) == rpg.VisibilityLevel.Dark, \
        "the removed light is still burning"
    assert not [e for e in app.bm.active_light_effects if e.source_agent_idx == -1], \
        "a DM-placed light effect outlived its source"
    print("✅ test_removing_the_last_light_puts_it_out passed")


def test_the_dialog_agrees_with_the_file_readers_on_an_absent_base():
    """The trap item 10 named. `_open_lighting_editor` and `_load_lighting` both read an
    absent `"default_light"` as BrightLight; the dialog started at Dark. `open()` is always
    passed a level today, so nothing reached it — which is exactly what makes it a trap for
    whoever adds a button that shows the value."""
    app = _app()
    fresh = type(app.lighting_editor)(app.font_sm, app.font_md)
    assert fresh.default_light == app._parse_light_level("BrightLight"), \
        (f"the dialog starts at {fresh.default_light}, the file readers at "
         f"{app._parse_light_level('BrightLight')}")
    print("✅ test_the_dialog_agrees_with_the_file_readers_on_an_absent_base passed")


def main():
    tests = [test_the_base_button_cycles_and_relabels,
             test_done_lights_the_map_with_no_sources_on_it,
             test_done_writes_the_base_so_it_survives_a_reload,
             test_removing_the_last_light_puts_it_out,
             test_the_dialog_agrees_with_the_file_readers_on_an_absent_base]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_lighting_editor: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_lighting_editor: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
