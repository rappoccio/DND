#!/usr/bin/env python3
"""M3's owed look at `_agent_fogged`, on a real display (MULTIPLAYER_PLAN.md, D-M3-2).

D-M3-2 collapsed three copies of the fog reveal gate into `App._agent_fogged` and
repointed the draw pass, the hover tooltip and NPC playback at it. The oracle for that
extraction was the 71 panel checkpoints — byte-identical across it — and the panel is
precisely the part of the frame the gate does not touch. Everything it DOES touch (a
sprite that must not be painted, a tooltip that must not appear, a slide that must not
play) was only ever verified headlessly, with `SDL_VIDEODRIVER=dummy` and no pixels.

So this is the looking half, as a rig, the way `manual_smoke_xvfb.py` is M2's: a real X
server, real pixels through pygame → X11 → Xvfb, and back via `PIL.ImageGrab`. It is
**not** part of `run_all_tests.py` — it needs a display, and its output is a directory of
PNGs for a human to look at. It does assert the three cheap facts a screenshot cannot
state on its own (the predicate itself, the cell's pixels, the absence of the tooltip),
because an assertion that can fail is worth more than a caption.

The scene is `test_gameview.py`'s, unchanged, and that is the point: it is the scene the
headless checks read, looked at rather than serialized. Fog up, the 7×7 top-left block
explored, and two enemies —

    Gnasher  (5, 3)  explored    — drawn, and names itself on hover
    Skarn    (9, 9)  never seen  — not drawn, silent on hover, no slide in playback

Run it inside the container, which already has Xvfb:

    docker run --rm -v "$HOME":/home/user -v /some/out/dir:/shots rpg_map -c \
      'Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset & sleep 2
        export DISPLAY=:99
        cd /home/user/Claude/DND && python3 tests/manual_fog_xvfb.py /shots'

Then look at the PNGs.
"""

import os
import sys
import types

os.environ.pop("SDL_VIDEODRIVER", None)
os.environ.pop("SDL_AUDIODRIVER", None)
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")     # no sound card in the container
os.environ["DISPLAY"] = ":99"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import tempfile

import pygame
from PIL import ImageGrab

from constants import COL_BG

# test_gameview sets SDL_VIDEODRIVER=dummy at import time — it is a headless suite. This
# pass is the opposite of headless, so the variable goes again after the import and
# before any App is built.
from test_gameview import _scene, _idx
os.environ.pop("SDL_VIDEODRIVER", None)

from main import App

OUT = sys.argv[1] if len(sys.argv) > 1 else "/shots"

_ORIGIN = []


def frame(app):
    """`App.run`'s composition order, for the layers the fog gate reaches."""
    app.screen.fill(COL_BG)
    app._draw_map()
    app._draw_fog_overlay()
    app._draw_agents()
    app._draw_npc_announcement()
    app._draw_hover_cursor()
    app._draw_agent_hover_name()
    app._draw_panel()
    pygame.display.flip()
    pygame.event.pump()


def shot(app, name):
    """The MAP half of the window — the smoke rig crops to the panel, and the panel is
    the one region `_agent_fogged` cannot change."""
    frame(app)
    pygame.time.wait(150)
    img = ImageGrab.grab(xdisplay=":99").convert("RGB")
    if not _ORIGIN:
        bbox = img.getbbox()          # where the app window actually landed on the root
        print("  window bbox on root:", bbox)
        _ORIGIN.append((bbox[0], bbox[1]) if bbox else (0, 0))
    ox, oy = _ORIGIN[0]
    h = app.screen.get_size()[1]
    img = img.crop((ox, oy, min(ox + app._panel_x(), img.width), min(oy + h, img.height)))
    path = os.path.join(OUT, f"{name}.png")
    img.save(path)
    print(f"  saved {path}  ({img.width}x{img.height})")
    return img


def hover(app, col, row):
    """Put the real pointer in the middle of a cell.

    `pygame.mouse.set_pos` is an SDL warp, so SDL's own mouse state moves with it and
    `pygame.mouse.get_pos()` — which is what both hover draws read — agrees. That is why
    this rig can drive the tooltip when the smoke rig could only post clicks.
    """
    sx, sy = app._cell_to_screen(col, row)
    v, hl = app.bm.v_line_positions, app.bm.h_line_positions
    s = app.map_scale
    ex = int(v[col + 1] * s + app.pan_x) if col + 1 < len(v) else sx + 10
    ey = int(hl[row + 1] * s + app.pan_y) if row + 1 < len(hl) else sy + 10
    pos = ((sx + ex) // 2, (sy + ey) // 2)
    pygame.mouse.set_pos(pos)
    pygame.event.pump()
    got = pygame.mouse.get_pos()
    cell = app._screen_to_cell(*got)
    print(f"  pointer at {got} → cell ({cell.col}, {cell.row})" if cell else
          f"  pointer at {got} → off-grid")
    assert cell is not None and (cell.col, cell.row) == (col, row), \
        f"the warp did not land on ({col}, {row}); SDL is not tracking the pointer"
    return pos


def cell_pixels(app, img, col, row):
    """Every pixel of one cell, out of a crop that starts at the window's top-left."""
    sx, sy = app._cell_to_screen(col, row)
    v, hl = app.bm.v_line_positions, app.bm.h_line_positions
    s = app.map_scale
    ex = int(v[col + 1] * s + app.pan_x) if col + 1 < len(v) else sx + 10
    ey = int(hl[row + 1] * s + app.pan_y) if row + 1 < len(hl) else sy + 10
    # Inset by 3 px so the grid line itself is not part of the sample.
    box = (sx + 3, sy + 3, max(sx + 4, ex - 3), max(sy + 4, ey - 3))
    return list(img.crop(box).getdata())


def main():
    tmp = tempfile.mkdtemp()
    app, _kira, _spectator = _scene(tmp)
    print("SDL video driver:", pygame.display.get_driver())
    assert pygame.display.get_driver() != "dummy", "not on the real display"
    print("window", app.screen.get_size(), "panel_x", app._panel_x())

    gnasher, skarn = _idx(app, "Gnasher"), _idx(app, "Skarn")

    # ── 1. the predicate, before any pixels ──
    print("\n[1] the gate itself")
    print("  _fog_active            =", app._fog_active())
    print("  _agent_fogged(Gnasher) =", app._agent_fogged(gnasher), " (5, 3), explored")
    print("  _agent_fogged(Skarn)   =", app._agent_fogged(skarn), " (9, 9), never seen")
    assert app._fog_active()
    assert not app._agent_fogged(gnasher)
    assert app._agent_fogged(skarn)

    # ── 2. the draw pass: one token painted, one cell left as fog ──
    print("\n[2] _draw_agents, on a real display")
    img = shot(app, "01_fog_skarn_unpainted")
    seen = cell_pixels(app, img, 5, 3)
    hidden = cell_pixels(app, img, 9, 9)
    print(f"  cell (5, 3) Gnasher: {len(set(seen))} distinct colours")
    print(f"  cell (9, 9) Skarn:   {len(set(hidden))} distinct colours, {set(hidden)}")
    assert len(set(hidden)) == 1, \
        f"the fogged cell is not one flat colour — something was painted in it: {set(hidden)}"
    assert len(set(seen)) > 1, "the explored enemy was not drawn either — check the rig"

    # ── 3. the tooltip: the control first, so a blank frame cannot pass ──
    print("\n[3] _draw_agent_hover_name")
    hover(app, 5, 3)
    with_name = shot(app, "02_hover_explored_names_gnasher")
    hover(app, 9, 9)
    without = shot(app, "03_hover_fogged_stays_silent")

    # The tooltip is drawn above-right of the pointer, so the difference between the two
    # frames is the tooltip itself — outside both cells, which is why the cell sample
    # above cannot see it.
    diff = sum(1 for a, b in zip(with_name.getdata(), without.getdata()) if a != b)
    print(f"  pixels differing between the two hovers: {diff}")
    hidden_again = cell_pixels(app, without, 9, 9)
    assert len(set(hidden_again)) == 1, \
        "hovering the fogged cell painted something in it"

    # ── 4. playback: a fogged mover commits its destination without sliding ──
    print("\n[4] _advance_npc_playback")
    path = [type("C", (), {"col": 9, "row": 9})(), type("C", (), {"col": 9, "row": 6})()]
    move = types.SimpleNamespace(kind=App._NPC_EV_MOVE, agent_idx=skarn, path=path)
    announce = types.SimpleNamespace(kind=App._NPC_EV_ANNOUNCE, agent_idx=skarn,
                                     text="Skarn howls from the dark")
    done = []
    app._npc_anim_start([move, announce], {skarn: {"pos": (9.0, 9.0), "hp": 10,
                                                   "was_alive": True}},
                        lambda: done.append(True))
    app._advance_npc_playback()
    print("  playback drained in one frame:", app._npc_anim is None, " on_done fired:", bool(done))
    assert app._npc_anim is None, \
        "the fogged mover is still animating — the gate is not reached from playback"
    assert done, "the playback never called back"
    shot(app, "04_after_silent_playback")

    # And the control: the same events for the enemy the party CAN see do not drain in
    # one frame — they slide, which is what makes the assertion above mean something.
    path2 = [type("C", (), {"col": 5, "row": 3})(), type("C", (), {"col": 5, "row": 1})()]
    move2 = types.SimpleNamespace(kind=App._NPC_EV_MOVE, agent_idx=gnasher, path=path2)
    app._npc_anim_start([move2], {gnasher: {"pos": (5.0, 3.0), "hp": 10,
                                            "was_alive": True}}, lambda: None)
    app._advance_npc_playback()
    print("  the SEEN enemy is still sliding:", app._npc_anim is not None)
    assert app._npc_anim is not None, \
        "the visible mover also resolved instantly — the rig proves nothing"
    app._npc_anim = None

    print("\nOK — now look at the PNGs in", OUT)


if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.quit()
