"""Structural draw-call recorder for the App-refactor goldens (APP_REFACTOR_PLAN.md A0).

Shared by `test_board_render.py` and `test_dungeon_pages.py`. It records WHAT a draw
method asked pygame to do — every `pygame.draw.*` call, every blit / fill onto the
screen or onto a scratch surface, and every string a font rendered — and never a pixel.
Same idea as `test_combat_panel.py`'s `PanelCapture`, widened from "buttons + text" to
the raw draw API, because the board renderer draws with `pygame.draw` and `blit`
directly instead of through `Button`.

How the hooks reach the code without editing `main.py`:

  · `pygame.draw.*` are module attributes, looked up at call time (`main.py` always
    writes `pygame.draw.rect(...)`, never `from pygame.draw import rect`), so they are
    swapped for recording wrappers for the duration of one capture.
  · `Surface.blit` cannot be patched on the extension type, so `app.screen` is swapped
    for an instance of a `pygame.Surface` SUBCLASS of the same size whose `blit` /
    `fill` record and then delegate. Scratch surfaces the code creates itself are
    ordinary Surfaces; what they get drawn with is still seen through the `pygame.draw`
    hooks, and blitting them onto the screen is seen through the subclass.
  · `pygame.font.Font.render` cannot be patched either, so every Font the App holds is
    wrapped in a proxy for the capture (and `pygame.font.SysFont`, for fonts made
    lazily), as `test_combat_panel.py` does for its three. The surfaces they return
    are remembered, so a later blit of one reads as the string, not as "a 37×14 image".

Surfaces are labelled by order of first appearance within a capture (`surf#1 64x64`),
so two runs of the same code produce the same labels. Text-surface sizes and the
positions of centred text depend on font metrics; the suite only ever runs in the
`rpg_map` container, whose font stack is fixed, so they are stable where it matters.
"""

import pygame

_DRAW_FUNCS = ("rect", "line", "lines", "aaline", "aalines", "circle", "ellipse",
               "arc", "polygon")


def _fmt(v):
    """A stable, compact text form for a draw argument."""
    if isinstance(v, pygame.Rect):
        return f"R({v.x},{v.y},{v.w},{v.h})"
    if isinstance(v, pygame.Color):
        return f"C({v.r},{v.g},{v.b},{v.a})"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, (list, tuple)):
        inner = ",".join(_fmt(x) for x in v)
        return f"({inner})" if isinstance(v, tuple) else f"[{inner}]"
    if isinstance(v, pygame.Surface):
        return f"<surf {v.get_width()}x{v.get_height()}>"
    return repr(v)


class _RecordingFont:
    """Transparent Font proxy; reports each render and the surface it returned."""

    def __init__(self, font, rec):
        object.__setattr__(self, "_font", font)
        object.__setattr__(self, "_rec", rec)

    def render(self, text, *args, **kwargs):
        surf = self._font.render(text, *args, **kwargs)
        self._rec._on_text(text, surf)
        return surf

    def __getattr__(self, name):
        return getattr(self._font, name)


class DrawRecorder:
    """One capture: `with DrawRecorder(app) as rec: ...; rec.lines`."""

    def __init__(self, app):
        self.app = app
        self.lines = []
        self._labels = {}         # id(surface) -> label
        self._texts = {}          # id(surface) -> rendered string
        self._keep = []           # keep labelled surfaces alive so ids are not reused
        self._n = 0
        self.section("-")

    # — labelling —
    def section(self, name):
        self._section = name

    def _emit(self, s):
        self.lines.append(f"{self._section} | {s}")

    def _label(self, surf):
        if surf is self._screen:
            return "screen"
        key = id(surf)
        if key in self._texts:
            return f"text{self._texts[key]!r}"
        if key not in self._labels:
            self._n += 1
            self._labels[key] = f"surf#{self._n} {surf.get_width()}x{surf.get_height()}"
            self._keep.append(surf)
        return self._labels[key]

    def _on_text(self, text, surf):
        self._texts[id(surf)] = text
        self._keep.append(surf)

    # — hooks —
    def _wrap_draw(self, name, real):
        rec = self

        def hooked(surface, *args, **kwargs):
            a = ", ".join([_fmt(x) for x in args]
                          + [f"{k}={_fmt(v)}" for k, v in sorted(kwargs.items())])
            rec._emit(f"draw.{name} {rec._label(surface)} {a}")
            return real(surface, *args, **kwargs)
        return hooked

    def __enter__(self):
        app = self.app
        rec = self
        real_screen = app.screen

        class _RecScreen(pygame.Surface):
            def blit(s, source, dest, area=None, special_flags=0):
                extra = f" area={_fmt(area)}" if area is not None else ""
                extra += f" flags={special_flags}" if special_flags else ""
                rec._emit(f"blit screen <- {rec._label(source)} @ {_fmt(dest)}{extra}")
                return pygame.Surface.blit(s, source, dest, area, special_flags)

            def fill(s, color, rect=None, special_flags=0):
                rec._emit(f"fill screen {_fmt(color)} {_fmt(rect)}")
                return pygame.Surface.fill(s, color, rect, special_flags)

        self._real_screen = real_screen
        self._screen = _RecScreen(real_screen.get_size())
        app.screen = self._screen

        self._real_draw = {n: getattr(pygame.draw, n) for n in _DRAW_FUNCS}
        for n, real in self._real_draw.items():
            setattr(pygame.draw, n, self._wrap_draw(n, real))

        self._real_sysfont = pygame.font.SysFont

        def sysfont(*a, **k):
            return _RecordingFont(rec._real_sysfont(*a, **k), rec)
        pygame.font.SysFont = sysfont

        self._saved_fonts = {a: v for a, v in vars(app).items()
                             if isinstance(v, pygame.font.Font)}
        for a, v in self._saved_fonts.items():
            setattr(app, a, _RecordingFont(v, self))
        self._saved_letter = dict(getattr(app, "_letter_fonts", {}))
        if hasattr(app, "_letter_fonts"):
            app._letter_fonts = {k: _RecordingFont(v, self)
                                 for k, v in self._saved_letter.items()}
        return self

    def __exit__(self, *exc):
        app = self.app
        app.screen = self._real_screen
        for n, real in self._real_draw.items():
            setattr(pygame.draw, n, real)
        pygame.font.SysFont = self._real_sysfont
        for a, v in self._saved_fonts.items():
            setattr(app, a, v)
        if hasattr(app, "_letter_fonts"):
            app._letter_fonts = self._saved_letter
        return False


class FakeClock:
    """`pygame.time.get_ticks` and `pygame.mouse.get_pos`, pinned for a whole test.

    Floating texts, the NPC announcement and the status flash all key on get_ticks; the
    hover cursor and hover names key on the mouse. Neither may drift between runs."""

    def __init__(self, ticks=100_000, mouse=(-1, -1)):
        self.ticks = ticks
        self.mouse = mouse

    def install(self):
        self._real = (pygame.time.get_ticks, pygame.mouse.get_pos)
        pygame.time.get_ticks = lambda: self.ticks
        pygame.mouse.get_pos = lambda: self.mouse

    def uninstall(self):
        pygame.time.get_ticks, pygame.mouse.get_pos = self._real


# `_start_combat` (and some saves) truncate these in the cwd (gui/, per run_all_tests.py).
# They are the live session's logs, not test artifacts — leave whatever was there.
_CWD_LOGS = ("replay_log.txt", "combat_log.txt")


def preserve_cwd_logs():
    saved = {}
    for name in _CWD_LOGS:
        try:
            with open(name, "rb") as f:
                saved[name] = f.read()
        except FileNotFoundError:
            saved[name] = None
    return saved


def restore_cwd_logs(saved):
    import os
    for name, data in saved.items():
        if data is None:
            if os.path.exists(name):
                os.remove(name)
        else:
            with open(name, "wb") as f:
                f.write(data)


def golden_main(build_output, golden_path, suite, unit):
    """The `--update` / compare / write-`.actual` runner both goldens share."""
    import difflib
    import os
    import sys

    update = "--update" in sys.argv
    saved = preserve_cwd_logs()
    try:
        actual = build_output()
    finally:
        restore_cwd_logs(saved)
        pygame.quit()

    if update:
        with open(golden_path, "w") as f:
            f.write(actual)
        print(f"✅ wrote golden: {golden_path} ({actual.count(chr(10))} lines)")
        return 0
    if not os.path.exists(golden_path):
        print(f"❌ no golden file yet: {golden_path}\n"
              f"   Bootstrap it once with --update, inspect it, then commit it.")
        return 1
    with open(golden_path) as f:
        expected = f.read()
    if actual == expected:
        n = sum(1 for ln in expected.splitlines() if ln.startswith("==="))
        print(f"✅ {suite}: {n} {unit} match the golden file")
        return 0
    actual_path = golden_path + ".actual"
    with open(actual_path, "w") as f:
        f.write(actual)
    sys.stdout.writelines(difflib.unified_diff(
        expected.splitlines(keepends=True), actual.splitlines(keepends=True),
        fromfile="golden", tofile="actual"))
    print(f"\n❌ {suite}: output differs from golden.\n"
          f"   Wrote actual output to {actual_path}\n"
          f"   If this change is intentional, re-bootstrap with --update.")
    return 1
