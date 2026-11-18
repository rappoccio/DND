#!/usr/bin/env python3
"""Board-render structural golden (APP_REFACTOR_PLAN.md A0).

The oracle for A1's "Board Rendering & Fog" cut, and a tripwire for every other cut that
touches state the board reads. It stands `App` up headlessly on a fixed map with a fixed
seed, builds one scene, and at a series of checkpoints records every draw call the map
layer of the frame loop makes — in `run()`'s order, one section per method — to a
byte-comparable golden file. Structural, not pixel: see `draw_capture.py` for what is
recorded and how it is hooked without touching `main.py`.

Line shape, per checkpoint:

    <method> | draw.<fn> <target> <args…>
    <method> | blit screen <- <source> @ <dest>
    <method> | fill screen <color> <rect>

where <target>/<source> is `screen`, `text'…'` (a string a font rendered) or
`surf#N WxH` (a scratch surface or image, numbered by first appearance).

Checkpoints walk the branches the board renderer has: idle, selection, hover over a
cell and over a token, fog at full and partial opacity, DM view, zoom/pan, a door and
a chest, combat with movement-reach overlays, a floating flash, and a downed token.

Regenerate after an INTENTIONAL render change (inspect the diff first!):
    python test_board_render.py --update
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

import rpg_battle_map as rpg
from helpers import _dict_to_weapon
from main import App
from draw_capture import DrawRecorder, FakeClock, golden_main

SEED = 20261118
MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_board_render.golden.txt")

PC_TEAM = 2      # constants.PC_FACTION
FOE_TEAM = 1

# The map layer of `App.run()`, in its order, for the no-Playback branch. The panel and
# the modals are not board rendering and are left to their own suites.
LAYERS = (
    "_draw_map",
    "_draw_map_overlays",
    "_draw_fog_overlay",
    "floor_align.draw",
    "_draw_agents",
    "_draw_floating_texts",
    "_draw_npc_announcement",
    "_draw_safe_target_highlights",
    "_draw_hover_cursor",
    "_draw_agent_hover_name",
    "_draw_staircase_hover",
    "_draw_room_label_hover",
    "_draw_dm_view_banner",
    "_draw_zoom_control",
)


def capture(app, title):
    out = [f"=== {title} ==="]
    with DrawRecorder(app) as rec:
        for name in LAYERS:
            rec.section(name)
            if name == "floor_align.draw":
                app.floor_align.draw(app)
            else:
                getattr(app, name)()
    out.extend(rec.lines)
    out.append(f"meta | zoom={app.view_zoom:.3f} pan={app.pan_x},{app.pan_y} "
               f"map_scale={app.map_scale:.4f} selected={app.selected_idx} "
               f"combat={bool(app.combat_active)} fog={bool(app.show_fog)} "
               f"dm_view={bool(app.dm_view)}")
    out.append("")
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Scene
# ─────────────────────────────────────────────────────────────────────────────

def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    raise KeyError(name)


def _stats(app, name, hp, ac, is_npc=False, weapon=None):
    i = _idx(app, name)
    s = app.combat.get_agent_stats(app.bm, i)
    s.hp_max = s.hp_cur = hp
    s.base_ac = ac
    s.is_npc = is_npc
    app.combat.set_agent_stats(app.bm, i, s)
    if weapon:
        app.combat.set_agent_weapons(app.bm, i,
                                     [_dict_to_weapon(app.weapon_name_to_dict[weapon])])


def _build_scene(app):
    """Two PCs and two foes in the left half, and a reserve far off on deck."""
    _place(app, "Aria",    3, 3)
    _place(app, "Skarn",   4, 3)
    _place(app, "Brannor", 2, 6)
    _place(app, "Vex",     9, 9)
    _place(app, "Goblin", 10, 0)
    app.combat.apply_agent_configs(app.bm)
    for who, fac in (("Aria", PC_TEAM), ("Skarn", FOE_TEAM), ("Brannor", PC_TEAM),
                     ("Vex", FOE_TEAM), ("Goblin", FOE_TEAM)):
        app.bm.set_agent_faction(_idx(app, who), fac)
    app.bm.set_agent_on_deck(_idx(app, "Goblin"), True)
    _stats(app, "Aria", 44, 18, weapon="Longsword")
    _stats(app, "Skarn", 60, 15, weapon="Greataxe")
    _stats(app, "Brannor", 25, 16, weapon="Mace")
    _stats(app, "Vex", 30, 13, weapon="Shortsword")
    _stats(app, "Goblin", 7, 15, weapon="Shortsword")


def _cell_centre(app, col, row):
    x0, y0 = app._cell_to_screen(col, row)
    x1, y1 = app._cell_to_screen(col + 1, row + 1)
    return (x0 + x1) // 2, (y0 + y1) // 2


def _set_hp(app, name, hp):
    i = _idx(app, name)
    s = app.combat.get_agent_stats(app.bm, i)
    s.hp_cur = hp
    app.combat.set_agent_stats(app.bm, i, s)


def _refresh_fog(app):
    app._mark_fog_dirty()
    app._refresh_fog()


# ─────────────────────────────────────────────────────────────────────────────
#  Checkpoints
# ─────────────────────────────────────────────────────────────────────────────

def build_output():
    pygame.init()
    clock = FakeClock()
    clock.install()
    try:
        return _run(clock)
    finally:
        clock.uninstall()


def _run(clock):
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    out = []

    out += capture(app, "01 setup — idle, nothing selected, pointer off the board")

    app.selected_idx = _idx(app, "Aria")
    out += capture(app, "02 setup — Aria selected")

    clock.mouse = _cell_centre(app, 6, 6)
    out += capture(app, "03 hover over an empty cell (6,6)")

    clock.mouse = _cell_centre(app, 4, 3)
    out += capture(app, "04 hover over Skarn's token")
    clock.mouse = (-1, -1)
    app.selected_idx = -1

    bm = app.bm
    bm.add_door(rpg.Cell(6, 2), False, False, 15, False)          # closed, unlocked
    bm.add_door(rpg.Cell(6, 4), True, False, 15, False)           # open
    ch = rpg.Chest()
    ch.cell = rpg.Cell(1, 9)
    bm.add_chest(ch)
    out += capture(app, "05 a closed door, an open door and a chest")

    app._set_fog(True)
    _refresh_fog(app)
    out += capture(app, "06 fog ON at 100% — only what the party has seen")

    app._set_fog_opacity(40)
    out += capture(app, "07 fog ON at 40%")

    app._set_dm_view(True)
    out += capture(app, "08 DM view — fog lifted for drawing, banner up")
    app._set_dm_view(False)
    app._set_fog_opacity(100)
    app._set_fog(False)

    app._zoom_by(app.ZOOM_BTN_STEP)
    app._zoom_by(app.ZOOM_BTN_STEP)
    app.pan_x -= 37
    app.pan_y -= 21
    app._clamp_pan()
    out += capture(app, "09 zoomed in two steps and panned")
    app._zoom_by(1.0 / (app.ZOOM_BTN_STEP * app.ZOOM_BTN_STEP))
    app.pan_x = app.pan_y = 0
    app._clamp_pan()

    app._start_combat()
    app.combat.stop_recording()
    aria = _idx(app, "Aria")
    for i, entry in enumerate(app.initiative_order):
        if entry.agent_idx == aria:
            app.turn_idx = i
    app.action_used = False
    app.bonus_used = False
    app.attack_seq.remaining = 0
    app._reset_movement(aria)
    app.selected_idx = aria
    out += capture(app, "10 combat — Aria on turn, reach overlays")

    app._spawn_flash(_idx(app, "Skarn"), "Hit (12)", (255, 80, 80), stream=False)
    clock.ticks += 400
    out += capture(app, "11 a floating 'Hit (12)' over Skarn, 400 ms in")
    clock.ticks += 5000                                     # long past every flash

    _set_hp(app, "Brannor", 4)
    _set_hp(app, "Vex", 0)
    out += capture(app, "12 Brannor bloodied, Vex at 0 HP")

    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(golden_main(build_output, GOLDEN_PATH, "test_board_render",
                         "board-render checkpoints"))
