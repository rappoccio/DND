#!/usr/bin/env python3
"""The panel's single FOG button and its menu: on/off, DM-screen opacity, reset.

Translucent fog (opacity below 100%) is drawn on the DM console but conceals nothing
there — tokens, doors and the rest show through — while the players' fog is unchanged.
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

import rpg_battle_map as rpg

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
C = rpg.Cell


def _app(tmp):
    from main import App
    png = os.path.join(tmp, "grid.png")
    shutil.copy(MAP_PATH, png)
    return App(png, seed=7)


def _labels(app):
    return [o.label for o in app.prompts.live.options]


def test_fog_button_menu():
    from menus import board
    from net.roster import DM_PRINCIPAL_ID
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        assert app.btn_fog.text == "Fog: OFF"

        board.show_fog_button_menu(app, (10, 10))
        assert app.prompts.live.owner == DM_PRINCIPAL_ID
        assert _labels(app) == ["Fog: turn ON", "Opacity: 100% ▸", "Reset fog…"]
        assert app.prompts.choose_label("Fog: turn ON").ok
        assert app.show_fog and app.btn_fog.text == "Fog: ON"

        board.show_fog_button_menu(app, (10, 10))
        assert app.prompts.choose_label("Opacity: 100% ▸").ok
        assert _labels(app) == ["✓ 100%", "75%", "50%", "25%"]
        assert app.prompts.choose_label("25%").ok
        assert app.fog_opacity == 25 and app.btn_fog.text == "Fog: ON (25%)"

        board.show_fog_button_menu(app, (10, 10))
        assert _labels(app)[:2] == ["Fog: turn OFF", "Opacity: 25% ▸"]
        assert app.prompts.choose_label("Reset fog…").ok
        assert _labels(app) == ["Reset fog", "Cancel"]
        assert app.prompts.choose_label("Cancel").ok

        app._set_fog(False)
        assert app.btn_fog.text == "Fog: OFF" and app.fog_opacity == 25
    print("✅ test_fog_button_menu")


def test_translucent_fog_conceals_nothing_on_the_dm_screen():
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = "Lurker", 9, 9, 1, ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
        app.combat.apply_agent_configs(app.bm)
        idx = next(i for i, pt in enumerate(app.bm.placed_agents) if pt.name == "Lurker")
        app.bm.set_agent_faction(idx, 1)
        app._set_fog(True)
        app.bm.clear_fog()
        assert not app.bm.is_explored(C(9, 9))

        assert app._fog_active() and app._fog_conceals()
        assert app._agent_fogged(idx) and app._agent_fogged(idx, party=True)

        app._set_fog_opacity(25)
        assert app._fog_active() and not app._fog_conceals()
        assert not app._agent_fogged(idx), "the DM sees through translucent fog"
        assert app._agent_fogged(idx, party=True), "the players' fog is untouched"

        # The overlay is drawn at a quarter of full black over a never-seen cell.
        app.screen.fill((255, 255, 255))
        app._draw_fog_overlay()
        s = app.map_scale
        x = app.map_rect.x + app.pan_x + int((app.bm.v_line_positions[9]
                                               + app.bm.v_line_positions[10]) / 2 * s)
        y = app.map_rect.y + app.pan_y + int((app.bm.h_line_positions[9]
                                               + app.bm.h_line_positions[10]) / 2 * s)
        r = app.screen.get_at((x, y))[0]
        assert 180 <= r <= 200, f"25% black over white should be ~191, got {r}"
    print("✅ test_translucent_fog_conceals_nothing_on_the_dm_screen")


if __name__ == "__main__":
    test_fog_button_menu()
    test_translucent_fog_conceals_nothing_on_the_dm_screen()
