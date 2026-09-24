#!/usr/bin/env python3
"""F3's owed look at the modal pump, on a real display (MULTIPLAYER_PLAN.md, D-M4d-5).

M4d puts `self._pump_net()` at the top of six blocking modal loops, and `test_modal_pump.py`
proves headlessly that the queue drains and that the screen *surface* is unchanged across a
pump. What neither can show is the thing F3 actually warned about:

    Pumping inside a modal means **a DM authoring modal is no longer a quiescent point** —
    state can advance while *Generate Dungeon* is open.

That is a statement about a screen a DM is looking at while something else happens behind
it, and it had only ever been checked with `SDL_VIDEODRIVER=dummy` and no pixels. So this is
the looking half, as a rig, the way `manual_fog_xvfb.py` is M3's: real pixels through
pygame → X11 → Xvfb, back via `PIL.ImageGrab`.

**The observation point is the command itself.** A command runs on the pygame thread inside
`_pump_net`, inside the modal's own loop — which is precisely the instant worth looking at,
and the only way to be there without a second thread touching SDL. So the rig submits
screenshot-taking commands from the net thread and lets the frame tick's pump run them.

Two frames are grabbed from inside the open modal, back to back:

    A — a bare screenshot
    B — a real `build_view(app, kira)`, the command M4c actually ships, then a screenshot

A must show the dialog (or the rig is looking at nothing), and **A must equal B** — the
projection ran, the party's whole state was read, and not one pixel moved under the modal.
That is D-M4-3's "pumps the command queue and nothing that redraws", as pixels.

The control is the mutant: with `_pump_net` stubbed out, the same command is still sitting
in the queue when the modal closes.

Not registered in `run_all_tests.py` — it needs a display, and its output is a directory of
PNGs for a human to look at. It asserts the cheap facts a screenshot cannot state on its
own, because an assertion that can fail is worth more than a caption.

Run it inside the container, which already has Xvfb:

    docker run --rm -v "$HOME":/home/user -v /some/out/dir:/shots rpg_map -c \\
      'Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset & sleep 2
        export DISPLAY=:99
        cd /home/user/Claude/DND && python3 tests/manual_modal_pump_xvfb.py /shots'

Then look at the PNGs.
"""

import os
import sys

os.environ.pop("SDL_VIDEODRIVER", None)
os.environ.pop("SDL_AUDIODRIVER", None)
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")     # no sound card in the container
os.environ["DISPLAY"] = ":99"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import asyncio
import threading
import time

import pygame
from PIL import ImageGrab

# test_mapserver reaches test_gameview, which sets SDL_VIDEODRIVER=dummy at import time —
# it is a headless suite. This pass is the opposite of headless, so the variable goes again
# after the import and before any App is built.
from test_mapserver import _server
os.environ.pop("SDL_VIDEODRIVER", None)

from net.view import build_view

OUT = sys.argv[1] if len(sys.argv) > 1 else "/shots"

_ORIGIN = []


def grab(app, name=None):
    """The app's window off the real root, optionally saved.

    The whole window, not the map crop `manual_fog_xvfb.py` takes: a modal is drawn over
    everything, and the region this rig is about is the part of the frame that must NOT
    change while it is open.
    """
    pygame.display.flip()
    pygame.event.pump()
    pygame.time.wait(120)
    img = ImageGrab.grab(xdisplay=":99").convert("RGB")
    if not _ORIGIN:
        bbox = img.getbbox()          # where the app window actually landed on the root
        print("  window bbox on root:", bbox)
        _ORIGIN.append((bbox[0], bbox[1]) if bbox else (0, 0))
    ox, oy = _ORIGIN[0]
    w, h = app.screen.get_size()
    img = img.crop((ox, oy, min(ox + w, img.width), min(oy + h, img.height)))
    if name:
        path = os.path.join(OUT, f"{name}.png")
        img.save(path)
        print(f"  saved {path}  ({img.width}x{img.height})")
    return img


def differing(a, b):
    return sum(1 for x, y in zip(a.getdata(), b.getdata()) if x != y)


def submit(s, fn):
    """Queue a command on the net loop and hand back its future.

    Waits until it is on the deque, so the caller cannot race the modal it is about to
    open — scheduling a coroutine onto another loop is not the same as it having run.
    """
    async def _await_it():
        return await s.app._net_commands.submit(fn)

    before = s.app._net_commands.pending
    future = asyncio.run_coroutine_threadsafe(_await_it(), s.srv._loop)
    deadline = time.monotonic() + 5.0
    while s.app._net_commands.pending <= before and time.monotonic() < deadline:
        time.sleep(0.001)
    assert s.app._net_commands.pending > before, "the command never reached the queue"
    return future


def look_from_inside_the_modal(s, results):
    """The net thread's half: submit, wait, submit, then let the modal go.

    Runs on a thread of its own because the main thread is about to block in a modal —
    which is the arrangement the real app is in, with the two threads' roles swapped.
    Nothing here touches SDL; the screenshots are taken *by the commands*, on the pygame
    thread, inside the pump.
    """
    time.sleep(1.0)                      # let the modal open and draw a few frames

    a = submit(s, lambda app: grab(app, "02_during_modal_bare_pump"))
    results["A"] = a.result(10)

    def projection_then_shot(app):
        view = build_view(app, s.kira)
        return view, grab(app, "03_during_modal_after_build_view")

    b = submit(s, projection_then_shot)
    results["view"], results["B"] = b.result(10)

    # The modal's exit, posted from a command so that SDL is only ever touched by the
    # pygame thread. This is also a second proof that the pump ran: nothing else in this
    # process can put an event in that queue.
    submit(s, lambda app: pygame.event.post(pygame.event.Event(pygame.QUIT))).result(10)


def control_no_pump(s):
    """The mutant: `_pump_net` removed, and the command is stranded.

    The modal has to be closed some other way, so this one posts QUIT from the helper
    thread. `SDL_PushEvent` is thread-safe, and it is used only here — in the path where
    the pygame thread is, by construction, not running anything that would do it.
    """
    real = type(s.app)._pump_net
    type(s.app)._pump_net = lambda self: 0
    try:
        future = submit(s, lambda app: "should never run")

        def closer():
            time.sleep(1.5)
            pygame.event.post(pygame.event.Event(pygame.QUIT))

        threading.Thread(target=closer, daemon=True).start()
        s.app._modal_message(["Generating dungeon…", "(control: the pump is removed)"])

        pending, done = s.app._net_commands.pending, future.done()
        print(f"  with the pump removed: pending={pending}  resolved={done}")
        assert pending == 1 and not done, \
            "the queue drained with the pump removed — this rig proves nothing"
    finally:
        type(s.app)._pump_net = real
        s.app._net_commands.pump(s.app)          # tidy: let the stranded future go


def main():
    with _server(pump=False) as s:
        app = s.app
        print("SDL video driver:", pygame.display.get_driver())
        assert pygame.display.get_driver() != "dummy", "not on the real display"
        print("window", app.screen.get_size())
        print("join code:", app.roster.join_code, " player:", s.kira.display_name)

        # ── 1. the board, before any modal ──
        print("\n[1] the DM's screen, no modal")
        app.screen.fill((0, 0, 0))
        app._draw_map()
        app._draw_agents()
        app._draw_panel()
        before = grab(app, "01_no_modal")

        # ── 2/3. the modal, looked at from inside the pump ──
        print("\n[2] a blocking modal, with the net thread asking for a view")
        results = {}
        helper = threading.Thread(target=look_from_inside_the_modal,
                                  args=(s, results), daemon=True)
        helper.start()
        app._modal_message(["Generating dungeon…",
                            "The DM is reading this. A player just asked for their view."])
        helper.join(30)
        assert not helper.is_alive(), "the helper never finished — the modal did not pump"

        a, b = results["A"], results["B"]
        moved = differing(before, a)
        print(f"  the modal changed {moved} pixels against the plain board")
        assert moved > 0, "the frame grabbed inside the modal looks like the plain board"

        print("\n[3] the pump drew nothing — D-M4-3, as pixels")
        drift = differing(a, b)
        print(f"  pixels differing across a real build_view: {drift}")
        assert drift == 0, \
            f"{drift} pixels moved under the modal while a command ran"

        # ...and the comparison is not two blank frames. The board behind the dialog is
        # black (see the finding below), so a whole-frame `drift == 0` would also be
        # satisfied by a frame with nothing in it. The dialog is the only lit region, so
        # it is the region where a stray draw could actually be seen — checked here, and
        # compared again on its own.
        box = a.getbbox()
        lit_a, lit_b = a.crop(box), b.crop(box)
        colours = len(set(lit_a.getdata()))
        print(f"  the lit region is {box}, {colours} distinct colours")
        assert colours > 10, \
            f"the only lit region has {colours} colours — this rig is comparing blank frames"
        assert differing(lit_a, lit_b) == 0, "the dialog itself moved across the pump"

        # The finding, and it is not a bug and not M4d's: `_modal_message.render()` blits
        # its alpha-170 overlay over the PREVIOUS frame on every iteration, so the board
        # behind it is gone after about five frames — 0.333^5 of the original is 0.4%.
        # Every one of the six does this and every one always has; the loop is untouched
        # by M4d. It is recorded because it is invisible headlessly and because it is the
        # answer to "why is the map not dimly visible in these PNGs".
        print(f"  note: the board behind the dialog is saturated black "
              f"({len(set(a.getdata()))} distinct colours in the whole frame) — "
              f"the overlay compounds every frame, and always has")

        view = results["view"]
        print(f"  the view that crossed: t={view['t']!r}  agents={len(view['agents'])}  "
              f"log={len(view['log'])}")
        assert view["t"] == "view", "the command did not build a view"

        # ── 4. the control ──
        print("\n[4] the control: the same modal with the pump removed")
        control_no_pump(s)

        grab(app, "04_after_the_modal_closed")
        print("\nOK — now look at the PNGs in", OUT)


if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.quit()
