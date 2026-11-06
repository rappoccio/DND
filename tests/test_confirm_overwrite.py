#!/usr/bin/env python3
"""Confirm before a save or a big operation writes over an existing file.

Explicit saves (Save Encounter As, Save Terrain As, Save Dungeon, New Dungeon), Quit,
and the operations that rewrite map files wholesale (Toggle Walls, Wall Detection,
Set Grid, Rescale, Generate Terrain / Dungeon, closing the terrain editor, Lighting
Done) go through App._confirm_overwrite, which asks the DM only when a target file
already exists — and only once run() has switched confirm_overwrites on, so a
headless App writes at once as before.

  · an existing file asks; Cancel writes nothing and changes nothing, Overwrite runs;
  · a file that does not exist yet is written without asking;
  · Quit asks Save and quit / Quit without saving / Cancel;
  · the confirm popup over the terrain editor takes the Esc that would close it;
  · the generator's overwrite list names the files the generator writes.
"""

import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")


def _app(tmp):
    png = os.path.join(tmp, "grid.png")
    shutil.copy(MAP_PATH, png)
    app = App(png, seed=7)
    app.confirm_overwrites = True
    return app


def _labels(app):
    return [o.label for o in app.prompts.live.options] if app.prompts.live else None


def _read(path):
    with open(path) as f:
        return f.read()


def test_toggle_walls_asks_only_over_an_existing_file():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        if os.path.exists(app._terrain_path):
            os.remove(app._terrain_path)
        on = app._walls_enabled
        app._confirm_overwrite([app._terrain_path], "Toggle walls", app._toggle_walls)
        assert app.prompts.live is None, "asked before writing a file that did not exist"
        assert app._walls_enabled != on and os.path.exists(app._terrain_path)

        before, on = _read(app._terrain_path), app._walls_enabled
        app._confirm_overwrite([app._terrain_path], "Toggle walls", app._toggle_walls)
        assert _labels(app) == ["Overwrite", "Cancel"], _labels(app)
        assert "grid_terrain.json" in app.prompts.live.title, app.prompts.live.title
        assert app.prompts.choose_label("Cancel").ok
        assert app._walls_enabled == on and _read(app._terrain_path) == before, \
            "Cancel still toggled or wrote"

        app._confirm_overwrite([app._terrain_path], "Toggle walls", app._toggle_walls)
        assert app.prompts.choose_label("Overwrite").ok
        assert app._walls_enabled != on and _read(app._terrain_path) != before
    print("✅ test_toggle_walls_asks_only_over_an_existing_file passed")


def test_headless_app_never_asks():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        app.confirm_overwrites = False
        app._save_terrain()
        on = app._walls_enabled
        app._confirm_overwrite([app._terrain_path], "Toggle walls", app._toggle_walls)
        assert app.prompts.live is None and app._walls_enabled != on
    print("✅ test_headless_app_never_asks passed")


def test_save_terrain_as_cancel_keeps_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        target = os.path.join(tmp, "other_terrain.json")
        with open(target, "w") as f:
            f.write('{"keep": true}')
        app._on_save_terrain_chosen(target)
        assert app.prompts.choose_label("Cancel").ok
        assert _read(target) == '{"keep": true}'
        app._on_save_terrain_chosen(target)
        assert app.prompts.choose_label("Overwrite").ok
        assert _read(target) != '{"keep": true}'
    print("✅ test_save_terrain_as_cancel_keeps_the_file passed")


def test_quit_asks_save_or_not():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        app._save_terrain()
        app._request_quit()
        assert _labels(app) == ["Save and quit", "Quit without saving", "Cancel"], _labels(app)
        assert app.prompts.choose_label("Cancel").ok
        assert app._quit_requested is None, "Cancel still quit"
        app._request_quit()
        assert app.prompts.choose_label("Quit without saving").ok
        assert app._quit_requested == "nosave"

        app = _app(tmp)
        os.remove(app._terrain_path)
        app._request_quit()
        assert app.prompts.live is None and app._quit_requested == "save", \
            "quitting with no terrain file on disk should just save it"
    print("✅ test_quit_asks_save_or_not passed")


def test_confirm_over_the_terrain_editor_takes_its_esc():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        app._save_terrain()
        app._open_terrain_editor()
        esc = dict(key=pygame.K_ESCAPE, mod=0, unicode="\x1b", scancode=0)
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, **esc))
        app._handle_events()
        assert app.terrain_editor.active and _labels(app) == ["Overwrite", "Cancel"], \
            (app.terrain_editor.active, _labels(app))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, **esc))
        app._handle_events()
        assert app.terrain_editor.active, "the second Esc closed the editor under the popup"
        if app.prompts.live is None:              # Esc dismissed the popup: ask again
            app._confirm_overwrite([app._terrain_path], "Close terrain editor",
                                   app._close_terrain_editor)
        assert app.prompts.choose_label("Overwrite").ok
        assert not app.terrain_editor.active
    print("✅ test_confirm_over_the_terrain_editor_takes_its_esc passed")


def test_generation_targets_name_the_generated_files():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        base = app._generated_base()
        got = app._generation_targets({"floors": 2, "maps_x": 2, "maps_y": 1}, multi=True)
        names = sorted(os.path.basename(p) for p in got)
        want = sorted([f"{base}.dungeon.json"] +
                      [f"{base}_f{z}{t}_{k}.json" for z in (0, 1) for t in ("", "_1_0")
                       for k in ("terrain", "agents")])
        assert names == want, names
        single = app._generation_targets({}, multi=False, agents_path="x_agents.json")
        assert single == [app._terrain_path, "x_agents.json"], single
    print("✅ test_generation_targets_name_the_generated_files passed")


def main():
    tests = [test_toggle_walls_asks_only_over_an_existing_file,
             test_headless_app_never_asks,
             test_save_terrain_as_cancel_keeps_the_file,
             test_quit_asks_save_or_not,
             test_confirm_over_the_terrain_editor_takes_its_esc,
             test_generation_targets_name_the_generated_files]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_confirm_overwrite: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_confirm_overwrite: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
