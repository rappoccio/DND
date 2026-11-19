"""The lighting editor and the encounter's lighting file: load the `_lighting.json`
sidecar onto the battle map (`load_lighting`), save the editor's work
(`save_lighting_no_reload`, `lighting_done`), apply it without a reload
(`apply_light_effects`), open the editor primed from disk (`open_lighting_editor`), import
a chosen file (`on_load_lighting_chosen`) and clear DM-placed lights (`clear_lighting`).

Moved out of `App` in APP_REFACTOR_PLAN.md A7b, the same way as A7: module-level functions
taking the app; all state stays on `app`. `_pixel_to_cell` stays on `App` (board geometry).

`App` keeps a one-line forwarder for `load_lighting`, `parse_light_level`,
`lighting_done`, `open_lighting_editor` and `on_load_lighting_chosen`: they are reached by
name from tests, `autosave`, `app_persist`, `app_dungeon_pages`, `menus/dm`, the lighting
dialog, or bound as a file-browser callback. Calls to `load_lighting` go through the
forwarder so an instance patch still sees them.
"""

import json
import os

import rpg_battle_map as rpg


def load_lighting(app, path: str | None = None):
    """Load lighting data from JSON file if it exists.

    When the encounter has no lighting file, reset to a fully-lit default so a
    previous encounter's darkness/sources don't bleed through on a swap.
    """
    path = path or app.store.lighting_read_path()
    # Clear existing DM-placed light effects before loading new ones
    for eff in app.bm.active_light_effects:
        if eff.source_agent_idx == -1:  # DM-placed
            app.bm.remove_light_effect(eff.id)

    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            # Apply the whole-map default light level (e.g. "Darkness" for a dark
            # dungeon). Per-source lights are placed as explicit light effects below
            # (so each keeps its own level, e.g. Sunlight); pass no sources here.
            default_lvl = parse_light_level(data.get("default_light", "BrightLight"))
            app.bm.apply_base_lighting(default_lvl, [])
            # Load light sources using place_light_effect (same as dialog)
            for src in data.get("light_sources", []):
                # A plain light source (torch/lantern) is ordinary bright light.
                # "Sunlight" is a special level (matters for vampires / sunlight
                # sensitivity) and must be opted into explicitly, not defaulted.
                level_str = src.get("light_level", "BrightLight")
                level = parse_light_level(level_str)
                radius = src.get("bright_radius", 5)

                # Lights can be stored as grid coordinates (col, row) or old pixel format (x, y)
                if "col" in src and "row" in src:
                    # New format: grid coordinates
                    col = src.get("col", 0)
                    row = src.get("row", 0)
                else:
                    # Old format: pixel coordinates - convert to grid
                    x = src.get("x", 0)
                    y = src.get("y", 0)
                    cell = app._pixel_to_cell(x, y)
                    if not cell:
                        continue
                    col = cell.col
                    row = cell.row

                if col < 0 or col >= app.bm.grid_cols or row < 0 or row >= app.bm.grid_rows:
                    continue

                # Create a sphere of cells around the light
                cells = []
                for r in range(max(0, row - radius), min(app.bm.grid_rows, row + radius + 1)):
                    for c in range(max(0, col - radius), min(app.bm.grid_cols, col + radius + 1)):
                        # Chebyshev distance for square radius
                        if abs(c - col) <= radius and abs(r - row) <= radius:
                            cells.append(rpg.Cell(c, r))

                # Place the light effect
                app.bm.place_light_effect(
                    src.get("name", "Light"),
                    cells,
                    level,
                    -1,  # -1 = permanent
                    -1   # -1 = DM-placed (no source agent)
                )
        except Exception as e:
            print(f"[App] Error loading lighting: {e}")
    else:
        # No lighting file for this encounter: reset to a clean, fully-lit default
        # so a previous encounter's darkness/sources don't bleed through on a swap.
        app.bm.apply_base_lighting(rpg.VisibilityLevel.Clear, [])


def parse_light_level(s: str) -> 'rpg.VisibilityLevel':
    """Convert string to VisibilityLevel enum."""
    mapping = {
        "BrightLight": rpg.VisibilityLevel.Clear,
        "DimLight": rpg.VisibilityLevel.Dim,
        "Darkness": rpg.VisibilityLevel.Dark,
        "MagicalDarkness": rpg.VisibilityLevel.MagicalDark,
        "HeavilyObscured": rpg.VisibilityLevel.HeavilyObscured,
        "Sunlight": rpg.VisibilityLevel.Sunlight,
    }
    return mapping.get(s, rpg.VisibilityLevel.Clear)


def save_lighting_no_reload(app, light_sources, default_light):
    """Save lighting data to JSON file without reloading (used by dialog after apply)."""
    # Convert enum to string
    light_str_map = {
        rpg.VisibilityLevel.Clear: "BrightLight",
        rpg.VisibilityLevel.Dim: "DimLight",
        rpg.VisibilityLevel.Dark: "Darkness",
        rpg.VisibilityLevel.MagicalDark: "MagicalDarkness",
        rpg.VisibilityLevel.HeavilyObscured: "HeavilyObscured",
        rpg.VisibilityLevel.Sunlight: "Sunlight",
    }
    default_str = light_str_map.get(default_light, "Darkness")

    # Convert light sources format: "level" (enum) -> "light_level" (string)
    # and store grid coordinates (col, row)
    converted_sources = []
    for src in light_sources:
        level_enum = src.get("level", rpg.VisibilityLevel.Sunlight)
        level_str = light_str_map.get(level_enum, "Sunlight")
        radius = src.get("radius", 5)
        # Use grid coordinates (col, row) with fallback to old (x, y) format
        col = src.get("col", src.get("x", 0))
        row = src.get("row", src.get("y", 0))
        converted_src = {
            "name": src.get("name", "Light"),
            "col": col,
            "row": row,
            "light_level": level_str,
            "bright_radius": radius,
            "dim_radius": radius + 1,
        }
        converted_sources.append(converted_src)

    data = {
        "default_light": default_str,
        "light_sources": converted_sources
    }
    with open(app._lighting_path, 'w') as f:
        json.dump(data, f, indent=2)


def save_lighting(app, light_sources, default_light):
    """Save lighting data to JSON file and reload into battle map."""
    save_lighting_no_reload(app, light_sources, default_light)
    # Reload lighting into battle map
    app._load_lighting()


def lighting_done(app, editor):
    """Lighting editor → Done: apply its work and save the lighting file, after
    asking before overwriting it. Cancel keeps the editor open."""
    def finish():
        editor.active = False
        # Apply base level and effects to the battle map first. The base has to
        # travel with the sources: Done is the only thing that applies the editor's
        # work without a reload, and a base the file knows about but the map does
        # not is a light switch that does nothing.
        apply_light_effects(app, editor.light_sources, editor.default_light)
        # Then save the configuration to disk (no reload, since we just applied)
        save_lighting_no_reload(app, editor.light_sources, editor.default_light)
    app._confirm_overwrite([app._lighting_path], "Lighting", finish)


def apply_light_effects(app, light_sources, default_light=None):
    """Apply the lighting editor's work to the battle map: the whole-map base level
    first, then the DM-placed sources on top of it.

    `default_light` carries the editor's base-light button. It has to come through
    here because Done is the only thing that applies the editor's work WITHOUT a
    reload, and a base level the file knows about but the map does not is a light
    switch that does nothing. Applied exactly as `load_lighting` applies it.
    Optional so the one caller that has no base to offer can still pass sources
    alone."""
    if default_light is not None:
        app.bm.apply_base_lighting(default_light, [])

    # Clear existing DM-placed light effects. This used to sit behind an early return
    # on an empty `light_sources`, which meant two things silently did nothing:
    # removing the LAST light left it burning until the next load, and a base-light
    # change on a map with no torches at all — the case that motivated the button —
    # never reached the map or the fog.
    for eff in app.bm.active_light_effects:
        if eff.source_agent_idx == -1:  # DM-placed
            app.bm.remove_light_effect(eff.id)

    # Place new light effects
    for light in light_sources:
        level = light.get("level", rpg.VisibilityLevel.Sunlight)
        radius = light.get("radius", 5)

        # Lights can be stored as grid coordinates (col, row) or old pixel format (x, y)
        if "col" in light and "row" in light:
            # New format: grid coordinates
            col = light.get("col", 0)
            row = light.get("row", 0)
        else:
            # Old format: pixel coordinates - convert to grid
            x = light.get("x", 0)
            y = light.get("y", 0)
            cell = app._pixel_to_cell(x, y)
            if not cell:
                continue
            col = cell.col
            row = cell.row

        if col < 0 or col >= app.bm.grid_cols or row < 0 or row >= app.bm.grid_rows:
            continue

        # Create a sphere of cells around the light
        cells = []
        for r in range(max(0, row - radius), min(app.bm.grid_rows, row + radius + 1)):
            for c in range(max(0, col - radius), min(app.bm.grid_cols, col + radius + 1)):
                # Chebyshev distance for square radius
                if abs(c - col) <= radius and abs(r - row) <= radius:
                    cells.append(rpg.Cell(c, r))

        # Place the light effect
        app.bm.place_light_effect(
            light.get("name", "Light"),
            cells,
            level,
            -1,  # -1 = permanent
            -1   # -1 = DM-placed (no source agent)
        )

    app._mark_fog_dirty()   # new lighting changes which cells the party can see


def clear_lighting(app):
    """Remove all DM-placed light sources and reset the whole map to the
    fully-lit default (mirrors load_lighting's no-file branch)."""
    for eff in list(app.bm.active_light_effects):
        if eff.source_agent_idx == -1:  # DM-placed
            app.bm.remove_light_effect(eff.id)
    app.bm.apply_base_lighting(rpg.VisibilityLevel.Clear, [])


def open_lighting_editor(app):
    """Open the lighting editor primed with the encounter's saved lighting."""
    light_sources = []
    default_light = rpg.VisibilityLevel.Clear
    lighting = app.store.lighting_read_path()
    if os.path.exists(lighting):
        try:
            with open(lighting, 'r') as f:
                data = json.load(f)
                # Convert saved format (with "light_level" string) to dialog format (with "level" enum)
                saved_sources = data.get("light_sources", [])
                for src in saved_sources:
                    level_str = src.get("light_level", "Sunlight")

                    # Lights can be stored as grid coordinates (col, row) or old pixel format (x, y)
                    if "col" in src and "row" in src:
                        # New format: grid coordinates
                        col = src.get("col", 0)
                        row = src.get("row", 0)
                    else:
                        # Old format: pixel coordinates - convert to grid
                        x = src.get("x", 0)
                        y = src.get("y", 0)
                        cell = app._pixel_to_cell(x, y)
                        if not cell:
                            continue
                        col = cell.col
                        row = cell.row

                    light_sources.append({
                        "name": src.get("name", "Light"),
                        "col": col,
                        "row": row,
                        "level": parse_light_level(level_str),
                        "radius": src.get("bright_radius", 5),
                    })
                default_light_str = data.get("default_light", "BrightLight")
                default_light = parse_light_level(default_light_str)
        except:
            light_sources = []
            default_light = rpg.VisibilityLevel.Clear
    app._reset_zoom()   # open on the whole map; the editor can zoom from there
    app.lighting_editor.open(app.map_surf, app.bm, app, light_sources, default_light)


def on_load_lighting_chosen(app, path: str):
    """Import lighting from a chosen _lighting.json into the current scene (it then
    saves with this encounter)."""
    # Load shows every .json, so refuse a non-lighting pick (no "light_sources" key)
    # rather than clearing the current lighting with an empty source list.
    try:
        with open(path) as f:
            if "light_sources" not in json.load(f):
                app._flash_status(f"Not a lighting file: {os.path.basename(path)}")
                return
    except Exception as e:
        app._flash_status(f"Could not read {os.path.basename(path)}: {e}")
        return
    app._load_lighting(path)
    # Auto-enable the lighting overlay so the user can see the loaded lighting
    app.show_lighting_overlay = True
    app._flash_status(f"Lighting loaded: {os.path.basename(path)}")
