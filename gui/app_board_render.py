"""The board renderer: everything `App.run()` paints on the map layer, below the panel.

Moved out of `App` in APP_REFACTOR_PLAN.md A1.2. Module-level functions taking the app,
the pattern `menus/*.py` already uses. They read `app` state and draw onto `app.screen`;
none of them changes game state.

What stayed on `App`, because code outside this module asks it too:

  · the fog rules — `_fog_active`, `_fog_conceals`, `_party_fog_active`, `_agent_fogged`,
    `_door_visible`, `_any_explored` — shared with `net/` (the player view) and NPC playback;
  · `_staircase_cells_here` / `_staircase_ends_here`, shared with hover and `net/view.py`;
  · the geometry, `_cell_to_screen` / `_cell_to_screen_f` (`playback.py` uses the second);
  · `_get_sprite`, which the mob picker uses as well.

`App` keeps a one-line forwarder for each function here that a test reaches by name
(`App._draw_map`, `App._draw_agents`, …); main.py itself calls this module directly.
"""

import os

import pygame

import rpg_battle_map as rpg

from constants import (COL_HP_HIGH, COL_HP_LOW, COL_HP_MID, FONT_SM, NPC_TYPEWRITER_CPS,
                       PC_FACTION, faction_color)
from helpers import door_touch_cells
from net.mapimg import FOG_OVERLAP
from terrain_dialogs import (draw_chest_glyph, draw_door_glyph, draw_ladder_glyph,
                             draw_stair_glyph, edge_door_rect)


def draw_dm_view_banner(app):
    """A red bar across the top of the map while DM view is on (D1), so the screen the
    table is looking at is never left showing everything by accident."""
    if not app.dm_view:
        return
    t = app.font_md.render("DM VIEW: fog lifted, every token and HP shown",
                            True, (255, 255, 255))
    bar = pygame.Rect(0, 0, app._panel_x(), t.get_height() + 10)
    pygame.draw.rect(app.screen, COL_HP_LOW, bar)
    app.screen.blit(t, (bar.centerx - t.get_width() // 2, bar.y + 5))


def draw_zoom_control(app):
    labels = {"out": "−", "level": f"{app.view_zoom * 100:.0f}%", "in": "+", "fit": "Fit"}
    for key, rect in app._zoom_control_rects().items():
        if key != "level":
            pygame.draw.rect(app.screen, (40, 40, 52), rect, border_radius=5)
            pygame.draw.rect(app.screen, (102, 102, 128), rect, 1, border_radius=5)
        else:
            pygame.draw.rect(app.screen, (28, 28, 38), rect, border_radius=5)
        col = (200, 200, 214) if key == "level" else (236, 236, 246)
        t = app.font_sm.render(labels[key], True, col)
        app.screen.blit(t, (rect.centerx - t.get_width() // 2,
                             rect.centery - t.get_height() // 2))


def _get_caster_color(app, caster_idx: int) -> tuple[int, int, int]:
    """Generate a distinctive color for a caster based on their agent index."""
    # Use different colors for different casters to visually link them to their targets
    colors = [
        (255, 100, 100),  # Red
        (100, 100, 255),  # Blue
        (100, 255, 100),  # Green
        (255, 255, 100),  # Yellow
        (255, 100, 255),  # Magenta
        (100, 255, 255),  # Cyan
        (255, 200, 100),  # Orange
        (200, 100, 255),  # Purple
    ]
    return colors[caster_idx % len(colors)]


def draw_floating_texts(app):
    """Render active floating-outcome flashes above their agents, drifting up
    and fading out over their lifetime. Called each frame after _draw_agents."""
    if not app._floating_texts:
        return
    now = pygame.time.get_ticks()
    # Prune expired entries in place.
    app._floating_texts = [
        f for f in app._floating_texts if now - f["spawn_ms"] < f["dur_ms"]
    ]
    agents = app.bm.placed_agents
    cpx = int(app.bm.cell_pixel_size * app.map_scale)
    font = getattr(app, "font_md", None) or app.font_sm
    for f in app._floating_texts:
        idx = f["agent_idx"]
        if idx < 0 or idx >= len(agents):
            continue
        pt = agents[idx]
        # NPC turn playback holds a just-killed token on screen until it drains, so the
        # killing-blow flash isn't dropped over an empty square.
        if pt.removed_from_play or (pt.conditions.dead and not app._npc_anim_draws_dead(idx)):
            continue
        apos = app._npc_anim_display_pos(idx)   # follow the animated position mid-slide
        if apos is not None:
            sx, sy = app._cell_to_screen_f(apos[0], apos[1])
        else:
            sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        size_px = cpx * pt.size
        p = (now - f["spawn_ms"]) / max(1, f["dur_ms"])   # 0 → 1 over lifetime
        label = font.render(f["text"], True, f["color"]).convert_alpha()
        # Antialiased text has per-pixel alpha, so set_alpha() is ignored — fade by
        # multiplying the whole surface's alpha channel instead.
        alpha = max(0, int(255 * (1.0 - p)))
        label.fill((255, 255, 255, alpha), None, pygame.BLEND_RGBA_MULT)
        lx = sx + size_px // 2 - label.get_width() // 2
        ly = sy - 6 - f["rise"] - int(p * 20)
        app.screen.blit(label, (lx, ly))


def draw_npc_announcement(app):
    """Typewriter-scroll the active Announce event's text above the acting token.
    Drawn each frame right after the floating flashes."""
    a = app._npc_anim
    if a is None or a["ei"] >= len(a["events"]):
        return
    ev = a["events"][a["ei"]]
    if ev.kind != app._NPC_EV_ANNOUNCE:
        return
    idx = ev.agent_idx
    if idx < 0 or idx >= len(app.bm.placed_agents):
        return
    pt = app.bm.placed_agents[idx]
    # A still-concealed actor's announcement bubble would float over an undrawn
    # token and give away its position — suppress it where the token is undrawn.
    if app._concealed_on_screen(idx, pt):
        return
    now   = pygame.time.get_ticks()
    el    = (now - a["t0"]) * app._npc_anim_speed
    shown = ev.text[:max(1, int(el / 1000.0 * NPC_TYPEWRITER_CPS))]
    pos = a["pos"].get(idx, (float(pt.origin.col), float(pt.origin.row)))
    sx, sy = app._cell_to_screen_f(pos[0], pos[1])
    cpx     = int(app.bm.cell_pixel_size * app.map_scale)
    size_px = cpx * pt.size
    font  = getattr(app, "font_md", None) or app.font_sm
    label = font.render(shown, True, (255, 240, 200))
    bg = pygame.Surface((label.get_width() + 10, label.get_height() + 6), pygame.SRCALPHA)
    bg.fill((20, 15, 5, 215))
    bx = sx + size_px // 2 - bg.get_width() // 2
    by = sy - bg.get_height() - 8
    bx = max(4, min(bx, app.screen.get_width() - bg.get_width() - 4))   # keep on screen
    by = max(4, by)
    app.screen.blit(bg, (bx, by))
    app.screen.blit(label, (bx + 5, by + 3))


# FLAG: Move to C++
def draw_spell_aoe_preview(app, cpx: int):
    """Translucent AoE highlight while the player is aiming a non-Single spell."""
    if not app.pending_spell_is_aoe or app.spell_hover_cell is None:
        return
    caster_idx = app._current_agent_idx()
    if caster_idx < 0:
        return
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    if not (0 <= app.pending_spell_idx < len(spells)):
        return
    sp    = spells[app.pending_spell_idx]
    if sp.geometry == rpg.SpellGeometry.Rectangle:
        # Oriented wall: before the anchor is set there is nothing to preview
        # (the hovered cell is the candidate start point). Once anchored, the
        # wall runs from the anchor toward the cursor, clamped to its length.
        if app.spell_anchor_cell is None:
            return
        cells = app.bm.wall_cells(app.spell_anchor_cell, app.spell_hover_cell,
                                   sp.width, sp.length)
        # wall_cells is raw geometry; the engine drops whatever the wall's anchor can't
        # see (Total Cover), so prune the preview the same way or it over-promises.
        caster = app.bm.placed_agents[caster_idx]
        cells = app.bm.prune_blocked_cells(cells, sp, caster.origin, caster.size,
                                            app.spell_anchor_cell)
    else:
        cells = app._area_template(caster_idx, sp, app.spell_hover_cell)

    fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
    fill_s.fill((160, 80, 220, 60))
    border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
    pygame.draw.rect(border_s, (200, 130, 255, 160), border_s.get_rect(), 1)

    # Only render cells that fall within the map viewport
    map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
    cell_set = {(c.col, c.row) for c in cells}
    for c in cells:
        sx, sy = app._cell_to_screen(c.col, c.row)
        # Skip cells drawn wholly outside the map viewport (sx/sy include the pan)
        if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
            continue
        app.screen.blit(fill_s,   (sx, sy))
        app.screen.blit(border_s, (sx, sy))

    # Orange ring around each agent caught in the blast
    for pt in app.bm.placed_agents:
        if (pt.origin.col, pt.origin.row) in cell_set:
            size_px = cpx * pt.size
            sx, sy  = app._cell_to_screen(pt.origin.col, pt.origin.row)
            pygame.draw.rect(app.screen, (255, 140, 0),
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

    # Bright white outline on the aimed cell
    ax, ay = app._cell_to_screen(app.spell_hover_cell.col,
                                  app.spell_hover_cell.row)
    pygame.draw.rect(app.screen, (255, 255, 255),
                     pygame.Rect(ax, ay, cpx, cpx), 2)

    # Green marker on a wall's anchor (the committed first click)
    if sp.geometry == rpg.SpellGeometry.Rectangle and app.spell_anchor_cell is not None:
        gx, gy = app._cell_to_screen(app.spell_anchor_cell.col,
                                      app.spell_anchor_cell.row)
        pygame.draw.rect(app.screen, (60, 220, 90),
                         pygame.Rect(gx, gy, cpx, cpx), 3)

    # Draw spell range circle (thin line showing max reach from caster). Self-origin AoEs
    # (Cone, Line) store their reach in radius/length, not `range` (which is 0 for them), so a
    # 60-ft Cone of Cold would otherwise draw a 0-ft ring. Use the geometry's extent for those.
    caster = app.bm.placed_agents[caster_idx]
    if sp.geometry == rpg.SpellGeometry.Cone:
        reach_ft = sp.radius
    elif sp.geometry == rpg.SpellGeometry.Line:
        reach_ft = sp.length
    else:
        reach_ft = sp.range
    range_cells = reach_ft / 5
    range_px = range_cells * cpx
    caster_sx, caster_sy = app._cell_to_screen(caster.origin.col, caster.origin.row)
    caster_center_x = caster_sx + (caster.size * cpx) / 2
    caster_center_y = caster_sy + (caster.size * cpx) / 2
    pygame.draw.circle(app.screen, (100, 150, 255, 100),
                      (int(caster_center_x), int(caster_center_y)),
                      int(range_px), 1)


def draw_chromatic_chain(app, cpx: int):
    """Overlay the orb's leap path while the player builds it: caster → primary → each hop,
    with a numbered ring on every chosen leap target and a white ring on the primary."""
    if not (app._picking("chromatic") and app.pending_spell_slot):
        return
    agents = app.bm.placed_agents
    caster_idx = app._current_agent_idx()

    def _center(idx):
        if not (0 <= idx < len(agents)):
            return None
        pt = agents[idx]
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        half = pt.size * cpx // 2
        return (sx + half, sy + half)

    path = [caster_idx, app.pending_chromatic_primary] + list(app.pending_chromatic_chain)
    pts = [c for c in (_center(i) for i in path) if c is not None]
    for i in range(len(pts) - 1):
        pygame.draw.line(app.screen, (200, 130, 255), pts[i], pts[i + 1], 3)

    ring = max(8, cpx // 3)
    pc = _center(app.pending_chromatic_primary)
    if pc is not None:
        pygame.draw.circle(app.screen, (255, 255, 255), pc, ring, 2)
    for n, idx in enumerate(app.pending_chromatic_chain, start=1):
        c = _center(idx)
        if c is None:
            continue
        pygame.draw.circle(app.screen, (200, 130, 255), c, ring, 3)
        if getattr(app, "font_sm", None):
            label = app.font_sm.render(str(n), True, (255, 255, 255))
            app.screen.blit(label, (c[0] - label.get_width() // 2,
                                     c[1] - label.get_height() // 2))


def draw_mantle_overlay(app, cpx: int):
    """Overlay a numbered ring on each chosen Mantle of Inspiration recipient while picking."""
    if not app._picking("mantle"):
        return
    agents = app.bm.placed_agents
    ring = max(8, cpx // 3)
    for n, idx in enumerate(app.pending_mantle_targets, start=1):
        if not (0 <= idx < len(agents)):
            continue
        pt = agents[idx]
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        half = pt.size * cpx // 2
        c = (sx + half, sy + half)
        pygame.draw.circle(app.screen, (210, 150, 230), c, ring, 3)
        if getattr(app, "font_sm", None):
            label = app.font_sm.render(str(n), True, (255, 255, 255))
            app.screen.blit(label, (c[0] - label.get_width() // 2,
                                     c[1] - label.get_height() // 2))


def draw_cleave_picker(app, cpx: int):
    """While picking a Cleave second target, ring the first target (white) and every legal
    second target (green), with a line from the attacker to each candidate."""
    info = app._pick_data("cleave")
    if not info:
        return
    agents = app.bm.placed_agents

    def _center(idx):
        if not (0 <= idx < len(agents)):
            return None
        pt = agents[idx]
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        half = pt.size * cpx // 2
        return (sx + half, sy + half)

    ring = max(8, cpx // 3)
    ac = _center(info.get("attacker", -1))
    fc = _center(info.get("first", -1))
    if fc is not None:
        pygame.draw.circle(app.screen, (255, 255, 255), fc, ring, 2)
    for t in info.get("valid", []):
        c = _center(t)
        if c is None:
            continue
        if ac is not None:
            pygame.draw.line(app.screen, (120, 230, 120), ac, c, 2)
        pygame.draw.circle(app.screen, (120, 230, 120), c, ring, 3)


def draw_attack_overlays(app, cpx: int):
    """Draw melee / ranged-normal / ranged-long attack-range overlays."""
    map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
    def _draw_zone(cells, fill_rgba, border_rgba):
        if not cells:
            return
        fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_s.fill(fill_rgba)
        border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_s, border_rgba, border_s.get_rect(), 1)
        for cell in cells:
            sx, sy = app._cell_to_screen(cell.col, cell.row)
            # Skip cells drawn wholly outside the map viewport (sx/sy include the pan)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(fill_s,   (sx, sy))
            app.screen.blit(border_s, (sx, sy))

    # Melee: warm red
    _draw_zone(app._attack_cells_melee, (200, 55, 55, 70), (255, 100, 100, 150))
    # Ranged normal: orange
    _draw_zone(app._attack_cells_rnorm, (200, 120, 40, 55), (255, 165, 60, 130))
    # Ranged long (disadvantage): dull yellow
    _draw_zone(app._attack_cells_rlong, (180, 165, 40, 35), (220, 200, 60, 90))


def draw_fog_overlay(app):
    """Grey out every cell the PC party has never seen (fog of war).

    Mirrors _draw_lighting_overlay's per-cell overlay pattern but keys each cell
    on the persistent C++ explored mask (is_explored) instead of light level, and
    is scale-correct: v/h line positions are raw image px, so multiply by map_scale
    for screen px (same convention as _draw_hover_cursor). A never-explored cell
    gets a dark opaque grey; explored cells are left clear. Drawn on top of the map
    + lighting overlay and beneath agents/UI, so it also hides beneath-agent
    spell/terrain overlays in unexplored areas."""
    if not app._fog_active():
        return
    bm = app.bm
    if not bm or not app.map_rect:
        return
    v_lines = bm.v_line_positions
    h_lines = bm.h_line_positions
    if not v_lines or not h_lines:
        return
    s    = app.map_scale
    cols = bm.grid_cols
    rows = bm.grid_rows
    fog_surf = pygame.Surface((app.map_rect.width, app.map_rect.height), pygame.SRCALPHA)
    # Pure black (net/mapimg.py MASK_RGB); opaque unless the DM turned it down.
    FOG_COL  = (0, 0, 0, round(255 * app.fog_opacity / 100))
    Cell = rpg.Cell
    seen = []
    for r in range(rows):
        if r >= len(h_lines) - 1:
            break
        cy = int(h_lines[r] * s)
        ch = int(h_lines[r + 1] * s) - cy
        for c in range(cols):
            if c >= len(v_lines) - 1:
                break
            cx = int(v_lines[c] * s)
            cw = int(v_lines[c + 1] * s) - cx
            if bm.is_explored(Cell(c, r)):
                seen.append((cx, cy, cw, ch))
                continue
            pygame.draw.rect(fog_surf, FOG_COL, (cx, cy, cw, ch))
    # Each explored cell's reveal reaches FOG_OVERLAP of a cell into its neighbours,
    # the same margin net/mapimg.py punches for the players. pygame.draw writes the
    # clear colour straight through (no blending), so this cuts holes in the fog.
    for cx, cy, cw, ch in seen:
        px = round(cw * FOG_OVERLAP)
        py = round(ch * FOG_OVERLAP)
        pygame.draw.rect(fog_surf, (0, 0, 0, 0),
                         (cx - px, cy - py, cw + 2 * px, ch + 2 * py))
    panned_rect = app.map_rect.copy()
    panned_rect.x += app.pan_x
    panned_rect.y += app.pan_y
    app.screen.blit(fog_surf, panned_rect)


def draw_map(app):
    # Apply pan offset to map drawing
    panned_rect = app.map_rect.copy()
    panned_rect.x += app.pan_x
    panned_rect.y += app.pan_y
    app.screen.blit(app.map_surf, panned_rect)
    # Draw regular overlay unless lighting editor is active
    if not app.lighting_editor.active:
        app.screen.blit(app.overlay, panned_rect)
        # Draw lighting overlay if persistent toggle is on
        if app.show_lighting_overlay:
            draw_lighting_overlay(app)
    elif app.lighting_editor.show_overlay:
        # Draw lighting overlay if editor dialog toggle is on
        draw_lighting_overlay(app)

    # Rubber-band box while sampling a tile for a manual grid
    if (app._grid_sample_mode and app._grid_sample_start is not None
            and app._grid_sample_cur is not None):
        x0, y0 = app._grid_sample_start
        x1, y1 = app._grid_sample_cur
        box = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        pygame.draw.rect(app.screen, (255, 220, 60), box, 2)


def _letter_font(app, size):
    """Cached bold font sized for the on-token first-letter placeholder glyph."""
    f = app._letter_fonts.get(size)
    if f is None:
        f = pygame.font.SysFont("sans", size, bold=True)
        app._letter_fonts[size] = f
    return f


def draw_hover_cursor(app):
    """Highlight the grid cell under the mouse, in and out of combat.

    This is the always-on 'map cursor': a subtle outlined square following the
    pointer so the DM can always see which cell they're aiming at, independent of
    the combat-only reach/attack/targeting overlays. Suppressed while a modal is
    open or the pointer is over the config panel."""
    if app._modal_active():
        return
    raw_v = app.bm.v_line_positions
    raw_h = app.bm.h_line_positions
    if not raw_v or not raw_h:
        return
    mx, my = pygame.mouse.get_pos()
    if mx >= app._panel_x():
        return                     # pointer is over the panel, not the map
    cell = app._screen_to_cell(mx, my)
    if cell is None:
        return
    s = app.map_scale
    sx, sy = app._cell_to_screen(cell.col, cell.row)
    # Per-cell width/height (grid lines aren't perfectly uniform on some maps).
    ex = int(raw_v[cell.col + 1] * s + app.pan_x) if cell.col + 1 < len(raw_v) else sx
    ey = int(raw_h[cell.row + 1] * s + app.pan_y) if cell.row + 1 < len(raw_h) else sy
    w = max(1, ex - sx)
    h = max(1, ey - sy)
    rect = pygame.Rect(sx, sy, w, h)
    fill = pygame.Surface((w, h), pygame.SRCALPHA)
    fill.fill((255, 255, 255, 26))            # faint wash so the cell reads as 'hot'
    app.screen.blit(fill, (sx, sy))
    pygame.draw.rect(app.screen, (235, 235, 250), rect, 2)


def draw_agent_hover_name(app):
    """Show the name of the token under the pointer as a floating tooltip.

    Names are no longer painted on the tokens (they cluttered the cells); instead
    the DM hovers a token to read it. Suppressed while a modal is open or the
    pointer is over the config panel."""
    if app._modal_active():
        return
    if not app.bm or not app.map_rect:
        return
    mx, my = pygame.mouse.get_pos()
    if mx >= app._panel_x():
        return                     # pointer is over the panel, not the map
    cell = app._screen_to_cell(mx, my)
    if cell is None:
        return
    idx = app._agent_at(cell)
    if idx < 0:
        return
    pt = app.bm.placed_agents[idx]
    # Fog of war: don't reveal a hidden non-party token's name.
    if app._agent_fogged(idx, pt):
        return
    # Concealed token on the players' table view: no name tooltip either, or hovering
    # the empty-looking cell would betray the ambush. The DM console keeps it.
    if app._concealed_on_screen(idx, pt):
        return

    label = app.font_md.render(pt.name, True, (240, 240, 240))
    pad = 5
    box_w = label.get_width() + pad * 2
    box_h = label.get_height() + pad * 2
    # Anchor above-right of the cursor, clamped to the map viewport.
    bx = mx + 14
    by = my - box_h - 6
    if bx + box_w > app._panel_x():
        bx = app._panel_x() - box_w - 2
    if by < 0:
        by = my + 18
    box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    box.fill((20, 20, 26, 230))
    app.screen.blit(box, (bx, by))
    pygame.draw.rect(app.screen, faction_color(pt.faction),
                     pygame.Rect(bx, by, box_w, box_h), 2, border_radius=4)
    app.screen.blit(label, (bx + pad, by + pad))


def draw_lighting_overlay(app):
    """Draw the lighting visualization overlay on the map."""
    if not app.bm or not app.map_rect:
        return

    cols = app.bm.grid_cols
    rows = app.bm.grid_rows
    # Grid lines in displayed-map px (the overlay surface is map_rect-sized, so it
    # follows the zoom as well as the pan).
    scale = app.map_scale
    h_lines = [int(y * scale) for y in app.bm.h_line_positions]
    v_lines = [int(x * scale) for x in app.bm.v_line_positions]

    # Create a surface for the lighting overlay
    lighting_surf = pygame.Surface((app.map_rect.width, app.map_rect.height), pygame.SRCALPHA)

    # Draw each cell with its light level
    for r in range(rows):
        for c in range(cols):
            if c >= len(v_lines) - 1 or r >= len(h_lines) - 1:
                continue

            # Get the light level at this cell
            light_level = app.bm.get_light_level(rpg.Cell(c, r))

            # Calculate opacity based on light level
            # BrightLight: 0% opacity (transparent)
            # DimLight: 50% opacity
            # Darkness: 90% opacity
            # MagicalDarkness: 100% opacity
            opacity = {
                rpg.VisibilityLevel.Clear: 0,
                rpg.VisibilityLevel.Dim: 128,      # 50% of 255
                rpg.VisibilityLevel.Dark: 230,      # 90% of 255
                rpg.VisibilityLevel.MagicalDark: 255,
                rpg.VisibilityLevel.HeavilyObscured: 220,  # dense pale fog
                rpg.VisibilityLevel.Sunlight: 45,  # faint warm tint (bright light, just flagged)
            }.get(light_level, 0)

            if opacity > 0:
                # Draw semi-transparent overlay for this cell
                cell_x = v_lines[c]
                cell_y = h_lines[r]
                cell_w = v_lines[c + 1] - v_lines[c]
                cell_h = h_lines[r + 1] - h_lines[r]

                # Color depends on light level
                if light_level == rpg.VisibilityLevel.MagicalDark:
                    color = (0, 0, 0, opacity)  # Black for magical darkness
                elif light_level == rpg.VisibilityLevel.HeavilyObscured:
                    color = (200, 205, 210, opacity)  # pale grey-white for fog/smoke
                elif light_level == rpg.VisibilityLevel.Sunlight:
                    color = (255, 235, 130, opacity)  # warm yellow for sunlight
                else:
                    color = (50, 50, 50, opacity)  # Dark grey for other darkness

                pygame.draw.rect(lighting_surf, color, (cell_x, cell_y, cell_w, cell_h))

    # Blit the lighting overlay onto the screen with pan offset
    panned_rect = app.map_rect.copy()
    panned_rect.x += app.pan_x
    panned_rect.y += app.pan_y
    app.screen.blit(lighting_surf, panned_rect)

    # Draw markers for light sources (golden circles), in screen px. Old-format
    # sources carry native image px, so they are looked up against the raw lines.
    raw_h = app.bm.h_line_positions
    raw_v = app.bm.v_line_positions

    for light_src in app.lighting_editor.light_sources:
        # Handle both old format (x, y pixel coords) and new format (col, row grid coords)
        if "col" in light_src and "row" in light_src:
            grid_c = light_src["col"]
            grid_r = light_src["row"]
        else:
            px = light_src["x"]
            py = light_src["y"]

            # Find grid cell containing this pixel
            grid_c = -1
            grid_r = -1
            for c in range(len(raw_v) - 1):
                if px >= raw_v[c] and px < raw_v[c + 1]:
                    grid_c = c
                    break
            for r in range(len(raw_h) - 1):
                if py >= raw_h[r] and py < raw_h[r + 1]:
                    grid_r = r
                    break

        if 0 <= grid_c < len(raw_v) - 1 and 0 <= grid_r < len(raw_h) - 1:
            # Draw a circle marker at the light source center
            cell_x, cell_y = app._cell_to_screen(grid_c, grid_r)
            end_x, end_y = app._cell_to_screen(grid_c + 1, grid_r + 1)
            cell_w = end_x - cell_x
            cell_h = end_y - cell_y
            center_x = cell_x + cell_w // 2
            center_y = cell_y + cell_h // 2
            radius = max(6, cell_w // 6)

            # Draw outer circle (golden yellow)
            pygame.draw.circle(app.screen, (255, 200, 0), (center_x, center_y), radius, 3)
            # Draw inner circle (bright yellow)
            pygame.draw.circle(app.screen, (255, 255, 100), (center_x, center_y), radius - 2, 1)


def draw_hp_bar(app, screen_x, screen_y, size_px, stats, hp_override=None):
    """Draw a thin at-a-glance HP bar along the bottom edge of an agent's sprite.

    Reuses the panel's HP color convention (COL_HP_HIGH/MID/LOW at 66%/33%).
    Temp HP, if any, is shown as a cyan segment appended at the current-HP end.
    hp_override (NPC turn playback) replaces stats.hp_cur so the bar drops when
    the animated hit lands, not when the engine resolved it.
    """
    hp_max = stats.hp_max
    if hp_max <= 0:
        return  # unknown/uninitialized HP — nothing meaningful to show
    hp_cur = max(0, stats.hp_cur if hp_override is None else hp_override)
    frac   = min(1.0, hp_cur / hp_max)

    inset = 2
    bar_h = max(3, size_px // 12)
    bar_w = size_px - 2 * inset
    bar_x = screen_x + inset
    bar_y = screen_y + size_px - bar_h - inset

    # Track (missing-HP background)
    pygame.draw.rect(app.screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))

    # Current-HP fill, colored by fraction
    hp_col = (COL_HP_HIGH if frac > 0.66 else
              COL_HP_MID  if frac > 0.33 else
              COL_HP_LOW)
    fill_w = int(round(bar_w * frac))
    if fill_w > 0:
        pygame.draw.rect(app.screen, hp_col, (bar_x, bar_y, fill_w, bar_h))

    # Temp HP overlay (cyan), clamped to the remaining bar width
    if stats.temp_hp > 0:
        temp_w = min(bar_w - fill_w, int(round(bar_w * (stats.temp_hp / hp_max))))
        if temp_w > 0:
            pygame.draw.rect(app.screen, (80, 200, 230),
                             (bar_x + fill_w, bar_y, temp_w, bar_h))

    # Drained max-HP overlay (dark red): the slice of the maximum currently unavailable
    # (vampiric Bite life-drain, etc.), pinned to the right end of the bar.
    drained = getattr(stats, "available_hit_points", 0)
    if drained > 0:
        drain_w = min(bar_w, int(round(bar_w * (drained / hp_max))))
        if drain_w > 0:
            pygame.draw.rect(app.screen, (90, 20, 20),
                             (bar_x + bar_w - drain_w, bar_y, drain_w, bar_h))

    # Outline for contrast over varied sprite art
    pygame.draw.rect(app.screen, (10, 10, 10), (bar_x, bar_y, bar_w, bar_h), 1)


def draw_one_agent(app, pt, screen_x, screen_y, cpx, alpha=255, tint=None, agent_idx=-1):
    """Draw a single agent (sprite or placeholder) at the given screen coords."""
    # Render gate: tombstoned agents (e.g. summons dismissed on concentration loss)
    # are kept in placedAgents_ to preserve indices but are no longer drawn.
    # (Future: reuse this gate for the Invisible condition — see known_limitations.md.)
    if getattr(pt, "removed_from_play", False):
        return
    size_px = cpx * pt.size
    team_col = faction_color(pt.faction)   # red / blue / grey by team

    # Down-state, animation-synced via the NPC-playback HP override (None = live).
    # A corpse (conditions.dead) gets the red death hatch and frees its square (see
    # occupancy); an unconscious body (hp<=0, not dead) is greyed out instead and
    # still blocks its cell. Keying the visuals off hp_disp keeps a just-killed token
    # drawing as alive until its death outcome plays during turn playback.
    hp_override = app._npc_anim_hp(agent_idx)
    hp_disp = pt.stats.hp_cur if hp_override is None else hp_override
    is_down = hp_disp <= 0
    is_corpse = is_down and pt.conditions.dead
    is_unconscious = is_down and not pt.conditions.dead
    # Grey multiply for an unconscious token (skipped when a caller passes an explicit
    # tint, e.g. a drag/placement ghost). Reuses the BLEND_RGBA_MULT tint path below.
    grey_tint = (105, 105, 115) if (is_unconscious and not tint) else None
    eff_tint = tint if tint else grey_tint

    # Team-colored background square behind every token. Sprites (which are mostly
    # transparent) sit on top of it, so the whole cell reads as red / blue / grey.
    r = pygame.Rect(screen_x + 1, screen_y + 1, size_px - 2, size_px - 2)
    bg_fill = eff_tint if eff_tint else team_col
    bg = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    bg.fill((*bg_fill[:3], alpha))
    app.screen.blit(bg, r)
    border_col = eff_tint if eff_tint else tuple(min(c + 50, 255) for c in team_col[:3])
    pygame.draw.rect(app.screen, border_col, r, 2, border_radius=3)

    # Skip first-letter placeholder sprites (e.g. sprites/C.png). They're opaque
    # tiles that would hide the team color; a bare team-colored square + hover name
    # reads cleaner. Real art (multi-char filenames) is still drawn.
    stem = os.path.splitext(os.path.basename(pt.sprite_path))[0] if pt.sprite_path else ""
    is_letter_placeholder = len(stem) == 1 and stem.isalpha()
    sprite = None if is_letter_placeholder else app._get_sprite(pt.sprite_path, size_px)
    if sprite:
        if alpha < 255 or eff_tint:
            surf = sprite.copy()
            if eff_tint:
                surf.fill(eff_tint, special_flags=pygame.BLEND_RGBA_MULT)
            surf.set_alpha(alpha)
            app.screen.blit(surf, (screen_x, screen_y))
        else:
            app.screen.blit(sprite, (screen_x, screen_y))
    else:
        # No real art (letter-placeholder file, or an empty/missing path as
        # PCs have) — draw the token's first letter, centered, on the
        # team-colored square. Splits the difference between a bare square
        # and the old opaque letter-tile: keeps the team color, adds an
        # at-a-glance glyph. Full name still shown on hover.
        glyph = (pt.name[:1] if pt.name else stem).upper()
        fsz = max(FONT_SM, int(size_px * 0.55))
        gfont = _letter_font(app, fsz)
        lt = gfont.render(glyph, True, (25, 25, 30))
        if alpha < 255:
            lt = lt.copy()
            lt.set_alpha(alpha)
        app.screen.blit(lt, (screen_x + (size_px - lt.get_width()) // 2,
                              screen_y + (size_px - lt.get_height()) // 2))
    # Red death hatch — corpses only (a greyed-out unconscious body gets none). The
    # NPC-playback HP override folded into is_corpse defers this until the death plays.
    if is_corpse:
        hatch = pygame.Surface((size_px, size_px), pygame.SRCALPHA)
        hatch.fill((0, 0, 0, 0))
        step = max(4, size_px // 8)
        col  = (180, 0, 0, 200)
        for offset in range(-size_px, size_px * 2, step):
            pygame.draw.line(hatch, col, (offset, 0), (offset + size_px, size_px), 2)
            pygame.draw.line(hatch, col, (offset + size_px, 0), (offset, size_px), 2)
        app.screen.blit(hatch, (screen_x, screen_y))

    # HP bar (skip translucent previews, e.g. movement ghosts; an Invisible token is
    # translucent but real, so it keeps its bar; so is a Hidden one). Tracker mode's
    # table view shows party HP only (D1).
    if ((alpha == 255 or (agent_idx >= 0 and (pt.conditions.invisible
                                              or pt.conditions.hidden)))
            and not (app.tracker_mode and not app.dm_view
                     and pt.faction != PC_FACTION)):
        draw_hp_bar(app, screen_x, screen_y, size_px, pt.stats, hp_override=hp_override)

    # Name is shown on hover (see _draw_agent_hover_name), not painted on the token.

    # Accumulate (label, color) for each active condition so it can be
    # rendered as stacked text below the agent, matching the ring color.
    cond_labels = []

    # Boss-finale marker (dungeon generator flags the deepest room's big-bad in
    # _agent_meta). Drawn as a golden square ringing the agent's cell so it reads
    # clearly at any zoom. agent_idx >= 0 excludes movement ghosts (which pass no
    # index); drawn even for On Deck reserves (alpha 110) so the boss is visible
    # before it's deployed into the fight.
    if agent_idx >= 0 and app._agent_meta.get(agent_idx, {}).get("is_boss"):
        pad = max(3, int(size_px * 0.10))
        ring = pygame.Rect(int(screen_x - pad), int(screen_y - pad),
                           int(size_px + 2 * pad), int(size_px + 2 * pad))
        pygame.draw.rect(app.screen, (90, 55, 0),  ring.inflate(4, 4), 5)  # dark backing
        pygame.draw.rect(app.screen, (255, 205, 40), ring, 3)             # gold ring

    # Concentration indicator (circle around agent if concentrating)
    if pt.conditions.concentrating:
        center_x = int(screen_x + size_px / 2)
        center_y = int(screen_y + size_px / 2)
        radius = int(size_px / 2 + 6)
        # Use the agent's own color if they're casting Hold Person, otherwise use orange
        caster_color = _get_caster_color(app, agent_idx) if agent_idx >= 0 else (255, 200, 100)
        pygame.draw.circle(app.screen, caster_color, (center_x, center_y), radius, 2)
        spell_name = pt.conditions.concentrating_on or 'Spell'
        spell_lbl = app.font_sm.render(spell_name, True, caster_color)
        app.screen.blit(spell_lbl, (screen_x + size_px + 5, screen_y))
        cond_labels.append((f"Concentrating ({spell_name})", caster_color))

    # Paralyzed indicator (circle linking to caster)
    if pt.conditions.paralyzed and agent_idx >= 0:
        # Find the caster of the paralysis from active conditions
        for cond in app.combat.active_agent_conditions:
            if cond.agent_idx == agent_idx and cond.condition_name == "Paralyzed":
                # Get caster's color - use a color based on caster index for visual linking
                caster_color = _get_caster_color(app, cond.caster_idx)
                center_x = int(screen_x + size_px / 2)
                center_y = int(screen_y + size_px / 2)
                radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                pygame.draw.circle(app.screen, caster_color, (center_x, center_y), radius, 3)
                cond_labels.append(("Paralyzed", caster_color))
                break

    # Blinded indicator (circle linking to caster)
    if pt.conditions.blinded and agent_idx >= 0:
        # Find the caster of the blinded condition from active conditions
        for cond in app.combat.active_agent_conditions:
            if cond.agent_idx == agent_idx and cond.condition_name == "Blinded":
                # Get caster's color - use a color based on caster index for visual linking
                caster_color = _get_caster_color(app, cond.caster_idx)
                center_x = int(screen_x + size_px / 2)
                center_y = int(screen_y + size_px / 2)
                radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                pygame.draw.circle(app.screen, caster_color, (center_x, center_y), radius, 3)
                cond_labels.append(("Blinded", caster_color))
                break

    # Incapacitated indicator (circle linking to source)
    if pt.conditions.incapacitated and agent_idx >= 0:
        # Find the source of the incapacitated condition from active conditions
        for cond in app.combat.active_agent_conditions:
            if cond.agent_idx == agent_idx and cond.condition_name == "Incapacitated":
                # Get source's color - use a color based on caster index for visual linking
                source_color = _get_caster_color(app, cond.caster_idx)
                center_x = int(screen_x + size_px / 2)
                center_y = int(screen_y + size_px / 2)
                radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                pygame.draw.circle(app.screen, source_color, (center_x, center_y), radius, 3)
                cond_labels.append(("Incapacitated", source_color))
                break

    # Stunned indicator (circle linking to source)
    if pt.conditions.stunned and agent_idx >= 0:
        # Find the source of the stunned condition from active conditions
        for cond in app.combat.active_agent_conditions:
            if cond.agent_idx == agent_idx and cond.condition_name == "Stunned":
                # Get source's color - use a color based on caster index for visual linking
                source_color = _get_caster_color(app, cond.caster_idx)
                center_x = int(screen_x + size_px / 2)
                center_y = int(screen_y + size_px / 2)
                radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                pygame.draw.circle(app.screen, source_color, (center_x, center_y), radius, 3)
                cond_labels.append(("Stunned", source_color))
                break

    # Charmed indicator (circle linking to charmer)
    if pt.conditions.charmed and agent_idx >= 0:
        # Find the charmer from active conditions
        for cond in app.combat.active_agent_conditions:
            if cond.agent_idx == agent_idx and cond.condition_name == "Charmed":
                # Get charmer's color - use a color based on charmer index for visual linking
                charmer_color = _get_caster_color(app, cond.caster_idx)
                center_x = int(screen_x + size_px / 2)
                center_y = int(screen_y + size_px / 2)
                radius = int(size_px / 2 + 10)  # Slightly larger than concentration circle
                pygame.draw.circle(app.screen, charmer_color, (center_x, center_y), radius, 3)
                cond_labels.append(("Charmed", charmer_color))
                break

    # Grappled indicator (brown "GR" badge)
    if pt.conditions.grappled:
        badge_font = app.font_sm
        gr_badge = badge_font.render("GR", True, (210, 150, 80))  # Brown/tan
        badge_x = int(screen_x + 4)
        badge_y = int(screen_y + 4)
        app.screen.blit(gr_badge, (badge_x, badge_y))
        cond_labels.append(("Grappled", (210, 150, 80)))

    # Frightened indicator (purple "FR" badge)
    if pt.conditions.frightened:
        badge_font = app.font_sm
        fr_badge = badge_font.render("FR", True, (180, 100, 200))  # Purple
        badge_x = int(screen_x + 4)
        badge_y = int(screen_y + 22)  # Below grappled badge if both present
        app.screen.blit(fr_badge, (badge_x, badge_y))
        cond_labels.append(("Frightened", (180, 100, 200)))

    # Gaseous Form / Misty Escape indicator (pale-cyan "MIST" badge)
    if getattr(pt.conditions, "gaseous_form", False):
        badge_font = app.font_sm
        mist_badge = badge_font.render("MIST", True, (170, 210, 230))  # Pale cyan
        badge_x = int(screen_x + 4)
        badge_y = int(screen_y + 40)  # Below grappled/frightened badges if present
        app.screen.blit(mist_badge, (badge_x, badge_y))
        cond_labels.append(("Gaseous Form", (170, 210, 230)))

    # Burning indicator (orange "BURN" badge) — Alchemist's Fire
    if getattr(pt.conditions, "burning", False):
        burn_badge = app.font_sm.render("BURN", True, (240, 140, 60))  # Orange
        app.screen.blit(burn_badge, (int(screen_x + 4), int(screen_y + 58)))
        cond_labels.append(("Burning", (240, 140, 60)))

    # Netted indicator (olive "NET" badge) — Restrained until a DC 10 STR check frees it
    if getattr(pt.conditions, "netted", False):
        net_badge = app.font_sm.render("NET", True, (190, 200, 140))  # Olive
        app.screen.blit(net_badge, (int(screen_x + 4), int(screen_y + 76)))
        cond_labels.append(("Netted", (190, 200, 140)))

    if pt.conditions.prone:
        cond_labels.append(("Prone", (230, 200, 120)))
    if pt.conditions.invisible:
        cond_labels.append(("Invisible", (200, 220, 255)))
    if pt.conditions.hidden:
        cond_labels.append(("Hidden", (200, 200, 200)))
    if agent_idx >= 0 and _is_disarmed(app, agent_idx, pt):
        cond_labels.append(("Disarmed", (230, 120, 120)))

    # Death save bubbles (for unconscious agents)
    if pt.conditions.unconscious and pt.stats.hp_cur <= 0:
        bubble_radius = 3
        bubble_spacing = 2
        bubble_y = int(screen_y + size_px + 2)
        bubble_x_start = int(screen_x + size_px // 2 - (3 * (bubble_radius * 2 + bubble_spacing) // 2))

        # Draw 3 green bubbles for successes
        for i in range(3):
            x = bubble_x_start + i * (bubble_radius * 2 + bubble_spacing)
            if i < pt.conditions.death_save_successes:
                pygame.draw.circle(app.screen, (50, 200, 50), (x, bubble_y), bubble_radius)
            else:
                pygame.draw.circle(app.screen, (50, 100, 50), (x, bubble_y), bubble_radius, 1)

        # Draw 3 red bubbles for failures
        bubble_x_start_red = int(screen_x + size_px // 2 - (3 * (bubble_radius * 2 + bubble_spacing) // 2))
        bubble_y_red = bubble_y + bubble_radius * 2 + bubble_spacing
        for i in range(3):
            x = bubble_x_start_red + i * (bubble_radius * 2 + bubble_spacing)
            if i < pt.conditions.death_save_failures:
                pygame.draw.circle(app.screen, (200, 50, 50), (x, bubble_y_red), bubble_radius)
            else:
                pygame.draw.circle(app.screen, (100, 50, 50), (x, bubble_y_red), bubble_radius, 1)

    # Dead indicator (skull-and-crossbones or ⚰️)
    if pt.conditions.dead:
        skull_icon = app.font_lg.render("☠", True, (150, 50, 50))
        skull_x = int(screen_x + size_px // 2 - 8)
        skull_y = int(screen_y + size_px // 2 - 12)
        app.screen.blit(skull_icon, (skull_x, skull_y))

    # Condition text labels, stacked below the agent. Each is drawn in the same
    # color as its ring/badge so the text and the circle read as one indicator.
    if cond_labels:
        label_y = int(screen_y + size_px + 2)
        # If death-save bubbles are drawn below the agent, start beneath them.
        if pt.conditions.unconscious and pt.stats.hp_cur <= 0:
            label_y += 14
        for text, color in cond_labels:
            surf = app.font_sm.render(text, True, color)
            lx = int(screen_x + size_px / 2 - surf.get_width() / 2)
            app.screen.blit(surf, (lx, label_y))
            label_y += surf.get_height() + 1


def _is_disarmed(app, idx: int, pt) -> bool:
    """Whether agent `idx` has lost its weapons this fight, for the "Disarmed" token label.

    Disarmed by an effect (conditions.disarmed), or holding no droppable weapon after having
    held one earlier in this combat: dropped, knocked away, or a frightened drop. A creature
    that never carried a weapon (natural attacks only) is never labelled. `_seen_armed`
    records the armed sightings; it is reset whenever combat starts, ends or is restored."""
    if pt.conditions.disarmed:
        return True
    if not app.combat_active:
        return False
    if any(w.name and w.droppable() for w in app.combat.get_agent_weapons(app.bm, idx)):
        app._seen_armed.add(idx)
        return False
    return idx in app._seen_armed


def draw_reach_overlays(app, cpx: int, raw_h=None, raw_v=None):
    """Draw walk (blue) and fly (gold) reachable-cell overlays."""
    # Get map dimensions if not provided
    if raw_h is None:
        raw_h = app.bm.h_line_positions
    if raw_v is None:
        raw_v = app.bm.v_line_positions

    # Walk range: semi-transparent cornflower blue
    if app._reach_walk:
        walk_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        walk_surf.fill((60, 120, 220, 55))
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, (80, 150, 255, 120),
                         border_surf.get_rect(), 1)
        map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
        for cell in app._reach_walk:
            sx, sy = app._cell_to_screen(cell.col, cell.row)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(walk_surf,   (sx, sy))
            app.screen.blit(border_surf, (sx, sy))

    # Fly range: semi-transparent gold — drawn on top so overlapping
    # cells show both colours (fly usually extends beyond walk).
    if app._reach_fly:
        fly_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fly_surf.fill((220, 180, 0, 45))
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, (255, 210, 0, 110),
                         border_surf.get_rect(), 1)
        map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
        for cell in app._reach_fly:
            sx, sy = app._cell_to_screen(cell.col, cell.row)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(fly_surf,    (sx, sy))
            app.screen.blit(border_surf, (sx, sy))

    # Jump range: semi-transparent cyan (when overlay is active)
    if app.jump_overlay_active and app.jump_reachable_cells:
        jump_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        jump_surf.fill((100, 200, 255, 70))
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, (150, 230, 255, 150),
                         border_surf.get_rect(), 2)
        for cell in app.jump_reachable_cells:
            # Skip cells outside map bounds
            if (cell.col < 0 or cell.row < 0 or
                cell.col >= len(raw_v) or cell.row >= len(raw_h)):
                continue
            sx, sy = app._cell_to_screen(cell.col, cell.row)
            app.screen.blit(jump_surf,   (sx, sy))
            app.screen.blit(border_surf, (sx, sy))


def draw_light_effects(app, cpx: int):
    """Draw light effect overlays (Daylight, Darkness, etc.)."""
    if not app.bm.has_active_light_effects():
        return

    s = app.map_scale
    raw_h = app.bm.h_line_positions
    raw_v = app.bm.v_line_positions

    for effect in app.bm.active_light_effects:
        # Ordinary bright light needs no tint (matches the 0-opacity Clear in the
        # per-cell lighting overlay); only draw levels that alter visibility.
        if effect.light_level == rpg.VisibilityLevel.Clear:
            continue
        # Color by light level: Sunlight (bright yellow), Dark/MagicalDark (dark blue)
        if effect.light_level == rpg.VisibilityLevel.Sunlight:
            color = (255, 255, 100, 50)  # Bright yellow with transparency
        elif effect.light_level == rpg.VisibilityLevel.MagicalDark:
            color = (50, 50, 120, 50)  # Dark blue with transparency
        elif effect.light_level == rpg.VisibilityLevel.Dark:
            color = (40, 40, 80, 50)   # Darker blue
        elif effect.light_level == rpg.VisibilityLevel.Dim:
            color = (100, 100, 150, 40)  # Dim purple
        else:
            color = (150, 150, 150, 30)  # Gray default

        # Create surfaces for fill and border
        fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_surf.fill(color)
        border_color = tuple(min(c + 60, 255) for c in color[:3]) + (color[3],)
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

        # Render each cell of the light effect
        map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
        for cell_idx in effect.cell_indices:
            # Convert flat index back to (col, row)
            col = cell_idx % app.bm.grid_cols
            row = cell_idx // app.bm.grid_cols
            if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                continue
            sx, sy = app._cell_to_screen(col, row)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(fill_surf, (sx, sy))
            app.screen.blit(border_surf, (sx, sy))

        # Draw light effect name and duration as a small label in the first cell
        if effect.cell_indices and effect.turns_remaining >= 0:
            first_idx = effect.cell_indices[0]
            col = first_idx % app.bm.grid_cols
            row = first_idx // app.bm.grid_cols
            if col >= 0 and row >= 0 and col < len(raw_v) and row < len(raw_h):
                sx, sy = app._cell_to_screen(col, row)
                # Draw light name and duration
                txt = app.font_sm.render(
                    f"{effect.name} ({effect.turns_remaining})",
                    True, (255, 255, 255)
                )
                app.screen.blit(txt, (sx + 2, sy + 2))


def draw_temp_terrain_overlays(app, cpx: int):
    """Draw temporary terrain effect overlays."""
    if not app.bm.has_active_terrain_effects():
        return

    s = app.map_scale
    raw_h = app.bm.h_line_positions
    raw_v = app.bm.v_line_positions

    for effect in app.bm.active_terrain_effects:
        # Color by the spell's name. Terrain effect ids share an integer space with
        # persistent spell-effect ids, so keying color off _effect_meta[id] bleeds the
        # latest spell-effect color onto all terrain. Look up terrain_color by name instead.
        color = None
        si = app.spell_name_to_idx.get(effect.name)
        if si is not None:
            rgb = app.all_spells[si].get("terrain_color")
            if rgb:
                color = (rgb[0], rgb[1], rgb[2], 90)
        if color is None:
            # Default colors by difficulty
            if effect.difficulty == rpg.TerrainDifficulty.Halved:
                color = (80, 200, 80, 80)  # Green
            elif effect.difficulty == rpg.TerrainDifficulty.Quartered:
                color = (200, 60, 60, 80)  # Red
            else:
                color = (100, 180, 220, 80)  # Cyan

        # Create surfaces for fill and border
        fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_surf.fill(color)
        border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

        # Render each cell of the effect
        map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
        for cell_idx in effect.cell_indices:
            # Convert flat index back to (col, row)
            col = cell_idx % app.bm.grid_cols
            row = cell_idx // app.bm.grid_cols
            if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                continue
            sx, sy = app._cell_to_screen(col, row)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(fill_surf, (sx, sy))
            app.screen.blit(border_surf, (sx, sy))

        # Draw turns_remaining as a small label in the first cell
        if effect.cell_indices and effect.turns_remaining >= 0:
            first_idx = effect.cell_indices[0]
            col = first_idx % app.bm.grid_cols
            row = first_idx // app.bm.grid_cols
            if col >= 0 and row >= 0 and col < len(raw_v) and row < len(raw_h):
                sx, sy = app._cell_to_screen(col, row)
                # Draw a small number in the top-left corner
                txt = app.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                app.screen.blit(txt, (sx + 2, sy + 2))


def draw_spell_effects(app, cpx: int):
    """Draw persistent spell effect overlays."""
    if not app.show_spell_effects:
        return

    # Sync cache with C++ engine state before rendering
    app._sync_spell_effect_cache()

    active_effects = app.bm.active_spell_effects
    if not active_effects:
        return

    s = app.map_scale
    raw_h = app.bm.h_line_positions
    raw_v = app.bm.v_line_positions
    if not raw_h or not raw_v:
        return

    for effect in active_effects:
        # Build metadata for this effect if not already present
        if effect.effect_id not in app._effect_meta:
            spell_color = None
            for spell_dict in app.all_spells:
                if spell_dict.get("name") == effect.spell.name:
                    if "terrain_color" in spell_dict:
                        rgb = spell_dict["terrain_color"]
                        spell_color = tuple(rgb + [120])
                    break
            if not spell_color:
                spell_color = (100, 180, 220, 120)  # Cyan default
            app._effect_meta[effect.effect_id] = {
                "name": effect.spell.name,
                "color": spell_color,
                "cells": [(c.col, c.row) for c in effect.cells]
            }

        # Get color from metadata
        if effect.effect_id in app._effect_meta:
            color = app._effect_meta[effect.effect_id].get("color", (100, 180, 220, 120))
        else:
            color = (100, 180, 220, 120)  # Cyan default

        # Create surfaces for fill and border
        fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_surf.fill(color)
        border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
        border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

        # Render each cell of the effect
        map_w, map_h = app._panel_x(), app.screen.get_height()   # on-screen map viewport
        for cell in effect.cells:
            col = cell.col
            row = cell.row
            if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                continue
            sx, sy = app._cell_to_screen(col, row)
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            app.screen.blit(fill_surf, (sx, sy))
            app.screen.blit(border_surf, (sx, sy))

        # Draw turns_remaining as a small label in the first cell
        if effect.cells and effect.turns_remaining >= 0:
            first_cell = effect.cells[0]
            sx, sy = app._cell_to_screen(first_cell.col, first_cell.row)
            txt = app.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
            app.screen.blit(txt, (sx + 2, sy + 2))


def draw_concentration_terrain(app, cpx: int):
    """Draw all terrain: permanent features and concentration-based effects."""
    if not app.show_terrain:
        return

    # Draw permanent terrain (walls, chasms, difficult terrain)
    zoom = app.map_scale / app.base_map_scale
    for region in app._terrain_regions:
        # Skip concentration-based terrain for now (draw separately below)
        if "cells" in region or region.get("source", {}).get("requires_concentration"):
            continue

        # Permanent terrain from JSON
        if "x" not in region or "y" not in region:
            continue

        # Regions are stored in fit-scale px; scale them by the user zoom so they
        # track the map (which is re-rendered at base × zoom).
        x = int(region.get("x", 0) * zoom)
        y = int(region.get("y", 0) * zoom)
        w = int(region.get("width", 0) * zoom)
        h = int(region.get("height", 0) * zoom)
        terrain_type = region.get("type", "Difficult Terrain")

        if terrain_type == "Wall":
            color = (0, 0, 0, 255)           # opaque black
        elif terrain_type == "Chasm":
            color = (128, 128, 128, 255)     # opaque grey
        elif terrain_type == "Water":
            color = (50, 100, 230, 128)      # blue, 50% transparent
        else:  # Difficult Terrain
            color = (139, 90, 43, 128)       # brown, 50% transparent

        # Anchor to the map's on-screen top-left, including the pan offset, so terrain
        # moves with the map when scrolling (the map blit also adds pan_x/pan_y).
        ox = app.map_rect.x + app.pan_x
        oy = app.map_rect.y + app.pan_y

        # Draw filled rectangle
        fill_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        fill_surf.fill(color)
        app.screen.blit(fill_surf, (x + ox, y + oy))

        # Water and difficult terrain are a plain fill; only walls and chasms get a border.
        if terrain_type not in ("Wall", "Chasm"):
            continue
        border_rect = pygame.Rect(x + ox, y + oy, w, h)
        border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
        pygame.draw.rect(app.screen, border_color, border_rect, 2)


def draw_doors(app, cpx: int):
    """Draw every door on the map as a slab/lock glyph (reads bm.doors each frame).

    Doors are always drawn (independent of the terrain-visibility toggle): they are
    interactive objects, and a closed door is not part of the painted terrain regions.
    Under fog a door the party has never seen stays hidden: same rule as the player
    view (net/view.py), any door cell explored, or either side of an edge door."""
    fog = app._fog_conceals()
    for door in app.bm.doors:
        if fog and not app._any_explored(
                [(c.col, c.row) for c in (door.cells or door_touch_cells(door))]):
            continue
        if door.edges:
            # An edge door is a bar on its grid line.
            x, y, w, h = edge_door_rect(door, app._cell_to_screen, cpx)
            draw_door_glyph(app.screen, x, y, cpx, door, app.font_sm, w=w, h=h)
            continue
        # A wide door is drawn as one elongated slab over its full bounding rect
        # (the cells are contiguous along a single axis), not a glyph per cell.
        cols = [c.col for c in door.cells]
        rows = [c.row for c in door.cells]
        if not cols:
            continue
        min_col, min_row = min(cols), min(rows)
        sx, sy = app._cell_to_screen(min_col, min_row)
        draw_door_glyph(app.screen, sx, sy, cpx, door, app.font_sm,
                        w=(max(cols) - min_col + 1) * cpx,
                        h=(max(rows) - min_row + 1) * cpx,
                        linked=app._door_link_at(door) is not None)


def draw_chests(app, cpx: int):
    """Chests (plans/ITEMS_AND_CHESTS_PLAN.md I5), under the doors' fog rule. The DM
    console marks a live trap nobody has found with an amber ring, and a found one
    with the red "!" players see."""
    fog = app._fog_conceals()
    for ch in app.bm.chests:
        if fog and not app._any_explored([(ch.cell.col, ch.cell.row)]):
            continue
        t = ch.trap
        live = t.armed and not t.disarmed and not t.fired
        mark = ("found" if t.found else "hidden") if live else None
        sx, sy = app._cell_to_screen(ch.cell.col, ch.cell.row)
        draw_chest_glyph(app.screen, sx, sy, cpx, ch, mark)


def draw_ladders(app, cpx: int):
    """Draw every ladder as a rung-and-rails portal glyph (reads self._ladders).

    Like doors, ladders always draw (they are interactive objects). The arrow
    direction is derived from the target floor vs the active map's z_level."""
    z_here = int(getattr(app.bm, "z_level", 0) or 0)
    fog = app._fog_conceals()
    for lad in app._ladders:
        cells = lad["cells"]
        if fog and not app._any_explored((c[0], c[1]) for c in cells):
            continue                                  # never seen: hidden like the floor under it
        cols = [c[0] for c in cells]
        rows = [c[1] for c in cells]
        if not cols:
            continue
        min_col, min_row = min(cols), min(rows)
        sx, sy = app._cell_to_screen(min_col, min_row)
        going_up = lad["target"][2] > z_here
        draw_ladder_glyph(app.screen, sx, sy, cpx, going_up=going_up,
                          font_sm=app.font_sm,
                          w=(max(cols) - min_col + 1) * cpx,
                          h=(max(rows) - min_row + 1) * cpx)


def draw_staircases(app, cpx: int):
    """Draw every staircase end on this page with its stair glyph: id(s) and an
    up/down arrow per usable staircase (an unfinished one draws greyed out)."""
    for (col, row), ends in app._staircase_cells_here().items():
        sx, sy = app._cell_to_screen(col, row)
        dirs = [app.dungeon.staircase_direction(st, i) for st, i in ends]
        draw_stair_glyph(app.screen, sx, sy, cpx,
                         directions=tuple(d for d in dirs if d is not None),
                         ids=[st.id for st, _ in ends], font_sm=app.font_sm)


def draw_staircase_hover(app):
    """Name, label and destination floor of the staircase end under the pointer,
    as a floating tooltip like the token name's. Not drawn over a token."""
    if app._modal_active() or not app.bm or not app.map_rect:
        return
    mx, my = pygame.mouse.get_pos()
    if mx >= app._panel_x():
        return
    cell = app._screen_to_cell(mx, my)
    if cell is None or app._agent_at(cell) >= 0:
        return
    ends = app._staircase_cells_here().get((cell.col, cell.row))
    if not ends:
        return
    lines = []
    for st, i in ends:
        head = st.name + (f" ({st.label})" if st.label else "")
        direction = app.dungeon.staircase_direction(st, i)
        if direction is None:
            lines.append(f"{head}: unfinished")
        else:
            page = app.dungeon.page_by_id(st.other_end(i).page)
            lines.append(f"{head}: {direction} to floor {page.z}, {page.id}")
    surfs = [app.font_md.render(t, True, (240, 240, 240)) for t in lines]
    pad = 5
    box_w = max(s.get_width() for s in surfs) + pad * 2
    box_h = sum(s.get_height() for s in surfs) + pad * 2
    bx = mx + 14
    by = my - box_h - 6
    if bx + box_w > app._panel_x():
        bx = app._panel_x() - box_w - 2
    if by < 0:
        by = my + 18
    box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    box.fill((20, 20, 26, 230))
    app.screen.blit(box, (bx, by))
    pygame.draw.rect(app.screen, (120, 220, 255),
                     pygame.Rect(bx, by, box_w, box_h), 2, border_radius=4)
    y = by + pad
    for t in surfs:
        app.screen.blit(t, (bx + pad, y))
        y += t.get_height()


def _room_label_surf(app, key: str):
    """The key as light text with a 1px dark outline, so it reads on wall and floor
    alike. Cached per key: the layer redraws every frame."""
    surf = app._room_label_surfs.get(key)
    if surf is None:
        fg = app.font_room.render(key, True, (255, 236, 170))
        bg = app.font_room.render(key, True, (15, 15, 20))
        surf = pygame.Surface((fg.get_width() + 2, fg.get_height() + 2), pygame.SRCALPHA)
        for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2), (0, 0), (2, 0), (0, 2), (2, 2)):
            surf.blit(bg, (dx, dy))
        surf.blit(fg, (1, 1))
        app._room_label_surfs[key] = surf
    return surf


def draw_room_labels(app, cpx: int):
    """Each room key centred on its cell. Drawn whatever the fog (the DM's screen
    shows fogged floor too), and recorded for the hover tooltip."""
    app._room_label_hits = []
    if not app.show_room_labels:
        return
    for room in app._room_labels_here():
        col, row = room.cell
        if not (0 <= col < app.bm.grid_cols and 0 <= row < app.bm.grid_rows):
            continue
        sx, sy = app._cell_to_screen(col, row)
        surf = _room_label_surf(app, room.key)
        rect = surf.get_rect(center=(sx + cpx // 2, sy + cpx // 2))
        app.screen.blit(surf, rect.topleft)
        app._room_label_hits.append((rect, room))


def draw_room_label_hover(app):
    """"K10. Dining Hall" as a floating tooltip over a room key. A token or a
    staircase under the pointer keeps its own tooltip instead."""
    if not app.show_room_labels or app._modal_active() or not app.bm or not app.map_rect:
        return
    mx, my = pygame.mouse.get_pos()
    text = app._room_label_tooltip((mx, my))
    if text is None:
        return
    label = app.font_md.render(text, True, (240, 240, 240))
    pad = 5
    box_w = label.get_width() + pad * 2
    box_h = label.get_height() + pad * 2
    bx = mx + 14
    by = my - box_h - 6
    if bx + box_w > app._panel_x():
        bx = app._panel_x() - box_w - 2
    if by < 0:
        by = my + 18
    box = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    box.fill((20, 20, 26, 230))
    app.screen.blit(box, (bx, by))
    pygame.draw.rect(app.screen, (255, 236, 170),
                     pygame.Rect(bx, by, box_w, box_h), 2, border_radius=4)
    app.screen.blit(label, (bx + pad, by + pad))


def draw_hatching(app, pattern: str, x: float, y: float, w: float, h: float, color: tuple):
    """Draw a hatching pattern on the screen within bounds."""
    screen_x = int(x + app.map_rect.x + app.pan_x)
    screen_y = int(y + app.map_rect.y + app.pan_y)
    screen_w = int(w)
    screen_h = int(h)
    hatch_color = tuple(min(c + 100, 255) for c in color[:3]) + (120,)

    # Create a clipping rectangle for the hatching
    clip_rect = pygame.Rect(screen_x, screen_y, screen_w, screen_h)
    old_clip = app.screen.get_clip()
    app.screen.set_clip(clip_rect)

    if pattern == '//':
        for i in range(-screen_h, screen_w + screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
    elif pattern == '\\\\':
        for i in range(-screen_h, screen_w + screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)
    elif pattern == '||':
        for i in range(0, screen_w, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
    elif pattern == '--':
        for i in range(0, screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
    elif pattern == '++':
        for i in range(0, screen_w, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
        for i in range(0, screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
    elif pattern == 'xx':
        for i in range(-screen_h, screen_w + screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
        for i in range(-screen_h, screen_w + screen_h, 8):
            pygame.draw.line(app.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)

    # Restore the clip rect
    app.screen.set_clip(old_clip)


def draw_items(app, cpx: int):
    """Draw all weapon items sitting on the map grid, under the chests' fog rule."""
    items = app.bm.get_all_items()
    if not items:
        return

    # Group items by cell: dict[(col, row)] -> list[MapItem]
    fog = app._fog_conceals()
    by_cell: dict = {}
    for item in items:
        key = (item.cell.col, item.cell.row)
        if fog and not app._any_explored([key]):
            continue                                  # never seen: hidden like the floor under it
        by_cell.setdefault(key, []).append(item)

    ICON_FRAC = 0.45          # item icon is 45% of cell width
    CASCADE_OFFSET = 3        # pixels per stacked item offset
    ITEM_COL = (200, 170, 40) # amber/gold fill for fallback box
    ITEM_BORDER = (255, 215, 0)

    icon_px = max(8, int(cpx * ICON_FRAC))

    for (col, row), cell_items in by_cell.items():
        sx, sy = app._cell_to_screen(col, row)
        for stack_idx, item in enumerate(cell_items):
            offset = stack_idx * CASCADE_OFFSET
            ix = sx + offset + 2
            iy = sy + offset + 2
            # Try sprite first
            sprite = app._get_sprite(item.sprite_path, icon_px)
            if sprite:
                app.screen.blit(sprite, (ix, iy))
            else:
                # Fallback: amber colored box with weapon name initial
                r = pygame.Rect(ix, iy, icon_px, icon_px)
                pygame.draw.rect(app.screen, ITEM_COL, r, border_radius=2)
                pygame.draw.rect(app.screen, ITEM_BORDER, r, 1, border_radius=2)
                initial = item.name[0].upper() if item.name else "?"
                lbl = app.font_sm.render(initial, True, (255, 255, 255))
                app.screen.blit(lbl, (ix + (icon_px - lbl.get_width()) // 2,
                                       iy + (icon_px - lbl.get_height()) // 2))

    # Ghost of a dropped weapon currently being dragged, plus a target-cell ring.
    if app.drag_item_id >= 0 and app.drag_item is not None and app.drag_item_cell is not None:
        sx, sy = app._cell_to_screen(app.drag_item_cell.col, app.drag_item_cell.row)
        pygame.draw.rect(app.screen, (80, 220, 80),
                         pygame.Rect(sx, sy, cpx, cpx), 2, border_radius=3)
        ix, iy = sx + 2, sy + 2
        sprite = app._get_sprite(app.drag_item.sprite_path, icon_px)
        if sprite:
            ghost = sprite.copy()
            ghost.set_alpha(180)
            app.screen.blit(ghost, (ix, iy))
        else:
            r = pygame.Rect(ix, iy, icon_px, icon_px)
            pygame.draw.rect(app.screen, ITEM_COL, r, border_radius=2)
            pygame.draw.rect(app.screen, ITEM_BORDER, r, 1, border_radius=2)
            initial = app.drag_item.weapon.name[0].upper() if app.drag_item.weapon.name else "?"
            lbl = app.font_sm.render(initial, True, (255, 255, 255))
            app.screen.blit(lbl, (ix + (icon_px - lbl.get_width()) // 2,
                                   iy + (icon_px - lbl.get_height()) // 2))


def draw_safe_target_highlights(app):
    """While editing an Evoker's safe set, outline the Evoker (cyan) and its safe targets (green)."""
    if app.safe_target_edit_idx < 0:
        return
    agents = app.bm.placed_agents
    caster = app.safe_target_edit_idx
    if caster >= len(agents):
        return
    cpx = int(app.bm.cell_pixel_size * app.map_scale)
    safe = set(app.combat.get_safe_targets(caster))

    def _outline(idx, color):
        if idx < 0 or idx >= len(agents):
            return
        pt = agents[idx]
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        size_px = cpx * pt.size
        pygame.draw.rect(app.screen, color, pygame.Rect(sx, sy, size_px, size_px), 3)

    _outline(caster, (100, 180, 220))   # the Evoker being edited (cyan)
    for idx in safe:
        _outline(idx, (60, 220, 80))     # safe allies (green)


def draw_paladin_auras(app, cpx):
    """Translucent gold ring around each Paladin showing its aura reach — Aura of
    Protection (L6+) / Aura of Courage (L10+): 10 ft, or 30 ft at L18. Same-team
    allies (and the Paladin) inside the ring get the aura; it vanishes while the
    Paladin is down (matching the engine's suppression)."""
    bm = app.bm
    GOLD = (255, 215, 90)
    clip = app.screen.get_clip()
    app.screen.set_clip(app.map_rect)
    for pt in bm.placed_agents:
        if pt.removed_from_play:
            continue
        st = pt.stats
        if st.character_class != rpg.CharacterClass.Paladin or st.char_level < 6:
            continue
        if pt.stats.hp_cur <= 0 or pt.conditions.unconscious or pt.conditions.incapacitated:
            continue  # aura suppressed while the Paladin is down
        radius_cells = 6 if st.char_level >= 18 else 2   # 30 ft / 10 ft (5 ft per cell)
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        half = (pt.size * cpx) / 2.0
        r = int(radius_cells * cpx + half)
        if r <= 0:
            continue
        surf = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        pygame.draw.circle(surf, (*GOLD, 22), (r, r), r)          # faint fill
        pygame.draw.circle(surf, (*GOLD, 140), (r, r), r, 2)      # ring outline
        app.screen.blit(surf, (int(sx + half) - r, int(sy + half) - r))
    app.screen.set_clip(clip)


def draw_forcecages(app, cpx):
    """Square cage/box around each Forcecaged creature. The Cage form (20-ft, unsealed) is drawn
    as a barred enclosure (outline + vertical bars — attacks/spells pass through). The Box form
    (10-ft, sealed) is drawn as a solid steel enclosure (heavier outline + translucent fill) to
    signal the two-way seal. Size is derived from the seal: box = 2 cells (10 ft), cage = 4 (20 ft)."""
    bm = app.bm
    STEEL = (150, 205, 225)
    clip = app.screen.get_clip()
    app.screen.set_clip(app.map_rect)
    for pt in bm.placed_agents:
        if pt.removed_from_play:
            continue
        if not getattr(pt.conditions, "forcecaged", False):
            continue
        sealed = getattr(pt.conditions, "forcecage_sealed", False)
        box_cells = 2 if sealed else 4                 # 10 ft (box) vs 20 ft (cage)
        sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        half = (pt.size * cpx) / 2.0
        cx, cy = sx + half, sy + half                  # centre of the occupant's footprint
        side = box_cells * cpx
        left, top = int(cx - side / 2), int(cy - side / 2)
        surf = pygame.Surface((side, side), pygame.SRCALPHA)
        if sealed:
            pygame.draw.rect(surf, (*STEEL, 40), (0, 0, side, side))            # solid-wall fill
            pygame.draw.rect(surf, (*STEEL, 230), (0, 0, side, side), 4)        # heavy outline
        else:
            pygame.draw.rect(surf, (*STEEL, 200), (0, 0, side, side), 2)        # thin outline
            for bx in range(1, box_cells * 2):                                  # vertical bars
                x = int(bx * side / (box_cells * 2))
                pygame.draw.line(surf, (*STEEL, 130), (x, 0), (x, side), 1)
        app.screen.blit(surf, (left, top))
    app.screen.set_clip(clip)


def draw_map_overlays(app):
    """The painted layers that belong to the map itself: light, temporary terrain,
    spell areas and the DM's terrain regions (water, difficult terrain, …). Drawn
    before the fog overlay so the fog covers them; drawn after it, they showed the
    layout of rooms the party has never seen."""
    if not app.bm.h_line_positions or not app.bm.v_line_positions:
        return
    cpx = int(app.bm.cell_pixel_size * app.map_scale)
    draw_light_effects(app, cpx)
    draw_temp_terrain_overlays(app, cpx)
    draw_spell_effects(app, cpx)
    draw_concentration_terrain(app, cpx)


def draw_agents(app):
    bm    = app.bm
    s     = app.map_scale
    cpx   = int(bm.cell_pixel_size * s)
    raw_h = bm.h_line_positions
    raw_v = bm.v_line_positions
    if not raw_h or not raw_v:
        return

    agents = bm.placed_agents

    # ── Movement reach overlays (beneath all agents) ──────────────────
    draw_reach_overlays(app, cpx, raw_h, raw_v)

    # ── Attack range overlays (beneath all agents) ────────────────────
    draw_attack_overlays(app, cpx)

    # ── Doors (slab + lock glyphs; beneath all agents) ─────────────────
    draw_doors(app, cpx)
    draw_chests(app, cpx)

    # Ladders, staircases and room keys come from the DM's scene (terrain, manifest),
    # not the board, so Playback (whose board is a trace's) leaves them out.
    if app.playback is None:
        # ── Ladders (vertical portals; beneath all agents) ────────────
        draw_ladders(app, cpx)

        # ── Staircase ends (manifest portals; beneath all agents) ─────
        draw_staircases(app, cpx)

        # ── Room keys (DM-only label layer; beneath all agents) ───────
        draw_room_labels(app, cpx)

    # ── Paladin aura rings (beneath all agents) ───────────────────────
    draw_paladin_auras(app, cpx)

    # ── Forcecage enclosures (barred cage / solid box) ────────────────
    draw_forcecages(app, cpx)

    # ── Draw items on the map ─────────────────────────────────────────
    draw_items(app, cpx)

    # ── Draw all settled agents ───────────────────────────────────────
    for i, pt in enumerate(agents):
        if i == app.drag_idx:
            continue    # skip the one being dragged (draw as ghost below)
        if pt.removed_from_play:
            continue    # tombstoned (dismissed summon): not rendered, not selectable
        # Dead bodies stay drawn as corpses (red death hatch, square freed for the
        # living to walk over — see occupancy). Unconscious PCs at 0 HP also stay
        # drawn (greyed, rolling death saves) and still block their cell. Only
        # tombstoned tokens (removed_from_play, handled above) vanish. During NPC turn
        # playback _draw_one_agent's hp_override defers the corpse look until the
        # death outcome plays, so a just-killed token still animates its death.
        # Fog of war: hide a non-party token whose whole footprint sits in cells the
        # party has never seen. Party-faction tokens are always drawn. Keyed off the
        # same explored mask as _draw_fog_overlay, so a sprite can never sit on fog.
        if app._agent_fogged(i, pt):
            continue
        # Concealment: the DM always sees a Hidden or Invisible creature, translucent
        # and labeled. Player-facing views (net/view.py, and tracker mode's table
        # view here) drop an enemy the party can't perceive.
        if app._concealed_on_screen(i, pt):
            continue
        table_view = app.tracker_mode and not app.dm_view
        invisible = ((pt.conditions.invisible or pt.conditions.hidden)
                     and not table_view)
        # NPC turn playback: draw at the animated display position (a token mid-slide,
        # or frozen at its pre-turn cell until its Move event plays).
        apos = app._npc_anim_display_pos(i)
        if apos is not None:
            sx, sy = app._cell_to_screen_f(apos[0], apos[1])
        else:
            sx, sy = app._cell_to_screen(pt.origin.col, pt.origin.row)
        # On-deck reserves are still drawn (the DM placed them), but dimmed with an
        # "ON DECK" badge so it's clear they aren't in the initiative yet.
        on_deck = app.bm.is_agent_on_deck(i)
        alpha = 110 if on_deck else (128 if invisible else 255)
        draw_one_agent(app, pt, sx, sy, cpx, alpha=alpha, agent_idx=i)
        if on_deck:
            size_px = cpx * pt.size
            badge = app.font_sm.render("ON DECK", True, (255, 235, 150))
            bg = pygame.Surface((badge.get_width() + 4, badge.get_height() + 2),
                                pygame.SRCALPHA)
            bg.fill((40, 30, 0, 200))
            bx = sx + (size_px - bg.get_width()) // 2
            by = sy - bg.get_height() - 1
            app.screen.blit(bg, (bx, by))
            app.screen.blit(badge, (bx + 2, by + 1))

        # Selection highlight (yellow border)
        if i == app.selected_idx:
            size_px = cpx * pt.size
            pygame.draw.rect(app.screen, (255, 215, 0),
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

    # ── Spell AoE preview (above agents, below drag ghost) ───────────
    draw_spell_aoe_preview(app, cpx)
    draw_chromatic_chain(app, cpx)
    draw_mantle_overlay(app, cpx)
    draw_cleave_picker(app, cpx)

    # ── Draw drag ghost ───────────────────────────────────────────────
    if app.drag_idx >= 0 and app.drag_cell is not None:
        pt  = agents[app.drag_idx]
        sx, sy = app._cell_to_screen(app.drag_cell.col, app.drag_cell.row)
        tint = (100, 255, 100) if app.drag_valid else (255, 80, 80)
        draw_one_agent(app, pt, sx, sy, cpx, alpha=180, tint=tint)
        # Outline
        size_px = cpx * pt.size
        border_col = (80, 220, 80) if app.drag_valid else (220, 60, 60)
        pygame.draw.rect(app.screen, border_col,
                         pygame.Rect(sx, sy, size_px, size_px), 3,
                         border_radius=3)

    # ── Draw placement mode ghost ──────────────────────────────────────
    if app.placement_mode_active and app.placement_cell is not None:
        sx, sy = app._cell_to_screen(app.placement_cell.col, app.placement_cell.row)
        size_px = cpx * app.placement_config.size
        # Draw sprite if it exists
        sprite = app._get_sprite(app.placement_config.sprite_path, size_px)
        if sprite:
            surf = sprite.copy()
            surf.set_alpha(200)
            app.screen.blit(surf, (sx, sy))
        else:
            # Draw placeholder
            r = pygame.Rect(sx + 2, sy + 2, size_px - 4, size_px - 4)
            placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            placeholder.fill((150, 150, 200, 200))
            app.screen.blit(placeholder, r)
        # Red outline if invalid, green if valid
        border_col = (220, 60, 60) if not app.placement_valid else (80, 220, 80)
        pygame.draw.rect(app.screen, border_col,
                         pygame.Rect(sx, sy, size_px, size_px), 3,
                         border_radius=3)

    # ── Summon placement preview ───────────────────────────────────────
    if app.pending_summon_slot and app.summon_hover_cell is not None:
        cell = app.summon_hover_cell
        # Scaling spirits aren't in the bestiary — take the size from the chosen spirit block.
        mob  = (app.pending_summon_spirit if app.pending_summon_spirit is not None
                else app.mob_stats_json.get(app.pending_summon_monster, {}))
        ssize = app._size_category_to_grid_size(mob.get("size", "Medium"))
        valid = app._summon_cell_valid(cell, ssize)
        sx, sy = app._cell_to_screen(cell.col, cell.row)
        size_px = cpx * ssize
        sprite = app._get_sprite(app._get_mob_sprite_path(app.pending_summon_monster), size_px)
        if sprite:
            surf = sprite.copy()
            surf.set_alpha(160)
            if not valid:
                surf.fill((255, 90, 90), special_flags=pygame.BLEND_RGBA_MULT)
            app.screen.blit(surf, (sx, sy))
        else:
            r = pygame.Rect(sx + 2, sy + 2, size_px - 4, size_px - 4)
            ph = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            ph.fill((80, 220, 80, 150) if valid else (220, 60, 60, 150))
            app.screen.blit(ph, r)
        border_col = (80, 220, 80) if valid else (220, 60, 60)
        pygame.draw.rect(app.screen, border_col,
                         pygame.Rect(sx, sy, size_px, size_px), 3, border_radius=3)
