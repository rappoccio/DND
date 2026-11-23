"""The New Dungeon wizard's working area (DUNGEON_WIZARD_PLAN W5): a source sheet drawn
over the map view, zoomed and panned on its own, with its grid, the crop being made,
the floors already cut from it, and the squares the blank-outside brush has painted.

The scene's own map is untouched underneath: the sheet is never loaded into the engine.
Sheets can be large (Argynvostholt's lower sheet is 4800 × 6600), so each frame scales
only the visible part, from a ≤ 2048 px preview when zoomed out, and the result is
cached until the view changes.
"""

from __future__ import annotations

import pygame
from PIL import Image

PREVIEW_SIDE = 2048

COL_GRID = (90, 200, 255)
COL_CROP = (255, 215, 80)
COL_OTHER = (150, 230, 150)
COL_BOX = (255, 120, 220)


def _to_surface(img: Image.Image) -> pygame.Surface:
    img = img.convert("RGB")
    frombytes = getattr(pygame.image, "frombytes", None) or pygame.image.fromstring
    return frombytes(img.tobytes(), img.size, "RGB")


class SheetCanvas:
    def __init__(self):
        self.path: str | None = None
        self.size = (0, 0)
        self.full: pygame.Surface | None = None
        self.preview: pygame.Surface | None = None
        self.pf = 1.0                    # preview pixels per sheet pixel
        self.area = pygame.Rect(0, 0, 0, 0)
        self.zoom = 1.0                  # screen pixels per sheet pixel
        self.ox = self.oy = 0.0          # screen position of the sheet's (0, 0)
        self._cache = None

    # ── sheet and view ──
    def set_sheet(self, path: str, area: pygame.Rect) -> None:
        if path != self.path:
            with Image.open(path) as im:
                im.load()
                self.size = im.size
                self.full = _to_surface(im)
                longest = max(im.size)
                if longest > PREVIEW_SIDE:
                    self.pf = PREVIEW_SIDE / longest
                    small = im.resize((max(1, round(im.size[0] * self.pf)),
                                       max(1, round(im.size[1] * self.pf))), Image.LANCZOS)
                    self.preview = _to_surface(small)
                else:
                    self.pf, self.preview = 1.0, self.full
            self.path = path
            self.area = pygame.Rect(area)
            self.fit()
        else:
            self.set_area(area)

    def clear(self) -> None:
        self.path, self.full, self.preview, self._cache = None, None, None, None

    def set_area(self, area: pygame.Rect) -> None:
        if pygame.Rect(area) != self.area:
            self.area = pygame.Rect(area)
            self.fit()

    def fit(self) -> None:
        w, h = self.size
        if not w or not h or self.area.w <= 0 or self.area.h <= 0:
            return
        self.zoom = min(self.area.w / w, self.area.h / h) * 0.96
        self.ox = self.area.x + (self.area.w - w * self.zoom) / 2
        self.oy = self.area.y + (self.area.h - h * self.zoom) / 2
        self._cache = None

    def to_sheet(self, pos) -> tuple[float, float]:
        return ((pos[0] - self.ox) / self.zoom, (pos[1] - self.oy) / self.zoom)

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x * self.zoom, self.oy + y * self.zoom)

    def zoom_at(self, factor: float, pos) -> None:
        x, y = self.to_sheet(pos)
        fit = min(self.area.w / max(1, self.size[0]), self.area.h / max(1, self.size[1]))
        self.zoom = max(fit * 0.25, min(self.zoom * factor, 16.0))
        self.ox, self.oy = pos[0] - x * self.zoom, pos[1] - y * self.zoom

    def pan(self, dx: float, dy: float) -> None:
        self.ox += dx
        self.oy += dy

    # ── drawing ──
    def _image(self):
        """(surface, screen pos) of the visible part of the sheet, cached per view."""
        key = (round(self.zoom, 6), round(self.ox, 2), round(self.oy, 2), tuple(self.area))
        if self._cache and self._cache[0] == key:
            return self._cache[1], self._cache[2]
        W, H = self.size
        x0, y0 = self.to_sheet(self.area.topleft)
        x1, y1 = self.to_sheet(self.area.bottomright)
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(W), x1), min(float(H), y1)
        if x1 <= x0 or y1 <= y0:
            self._cache = (key, None, (0, 0))
            return None, (0, 0)
        src, f = (self.preview, self.pf) if self.zoom <= self.pf else (self.full, 1.0)
        sx0, sy0 = int(x0 * f), int(y0 * f)
        sx1 = min(src.get_width(), int(x1 * f) + 1)
        sy1 = min(src.get_height(), int(y1 * f) + 1)
        sub = src.subsurface(pygame.Rect(sx0, sy0, max(1, sx1 - sx0), max(1, sy1 - sy0)))
        z = self.zoom / f
        out = pygame.transform.scale(sub, (max(1, round(sub.get_width() * z)),
                                           max(1, round(sub.get_height() * z))))
        pos = (round(self.ox + sx0 / f * self.zoom), round(self.oy + sy0 / f * self.zoom))
        self._cache = (key, out, pos)
        return out, pos

    def draw(self, surf, *, grid=None, squares=None, others=(), blanks=(),
             drag_box=None, font=None) -> None:
        """The sheet, then: the grid; floors already cut (``others``: (squares, label));
        the crop (``squares``) with everything outside it dimmed; blanked squares; the
        box being dragged (sheet-pixel corners)."""
        if self.full is None:
            return
        clip = surf.get_clip()
        surf.set_clip(self.area)
        surf.fill((14, 14, 20), self.area)
        img, pos = self._image()
        if img is not None:
            surf.blit(img, pos)
        if grid is not None:
            self._draw_grid(surf, grid)
        for sq, label in others:
            r = self._square_rect(grid, sq)
            pygame.draw.rect(surf, COL_OTHER, r, 2)
            if font is not None and label:
                surf.blit(font.render(label, True, COL_OTHER), (r.x + 4, r.y + 4))
        if grid is not None and squares is not None:
            r = self._square_rect(grid, squares)
            shade = pygame.Surface(self.area.size, pygame.SRCALPHA)
            shade.fill((0, 0, 0, 140))
            shade.fill((0, 0, 0, 0), r.move(-self.area.x, -self.area.y))
            surf.blit(shade, self.area.topleft)
            pygame.draw.rect(surf, COL_CROP, r, 2)
        if grid is not None and blanks:
            paint = pygame.Surface(self.area.size, pygame.SRCALPHA)
            for k, j in blanks:
                r = self._square_rect(grid, (k, j, k + 1, j + 1))
                paint.fill((0, 0, 0, 215), r.move(-self.area.x, -self.area.y))
            surf.blit(paint, self.area.topleft)
        if drag_box is not None:
            (ax, ay), (bx, by) = drag_box
            p, q = self.to_screen(ax, ay), self.to_screen(bx, by)
            r = pygame.Rect(min(p[0], q[0]), min(p[1], q[1]), abs(q[0] - p[0]), abs(q[1] - p[1]))
            pygame.draw.rect(surf, COL_BOX, r, 2)
        surf.set_clip(clip)

    def _square_rect(self, grid, sq) -> pygame.Rect:
        k0, j0, k1, j1 = sq
        x0, y0 = self.to_screen(grid.line(k0, 0), grid.line(j0, 1))
        x1, y1 = self.to_screen(grid.line(k1, 0), grid.line(j1, 1))
        return pygame.Rect(round(x0), round(y0), round(x1 - x0), round(y1 - y0))

    def _draw_grid(self, surf, grid) -> None:
        step_px = grid.square_px * self.zoom
        if step_px <= 0:
            return
        every = max(1, int(6 // step_px) + (1 if step_px < 6 else 0))
        W, H = self.size
        for axis, n in ((0, W), (1, H)):
            lo, hi = grid.index_range(n, axis)
            for k in range(lo, hi + 1, every):
                v = grid.line(k, axis)
                if axis == 0:
                    x = round(self.to_screen(v, 0)[0])
                    if self.area.left <= x <= self.area.right:
                        y0 = round(self.to_screen(0, 0)[1])
                        y1 = round(self.to_screen(0, H)[1])
                        pygame.draw.line(surf, COL_GRID, (x, y0), (x, y1), 1)
                else:
                    y = round(self.to_screen(0, v)[1])
                    if self.area.top <= y <= self.area.bottom:
                        x0 = round(self.to_screen(0, 0)[0])
                        x1 = round(self.to_screen(W, 0)[0])
                        pygame.draw.line(surf, COL_GRID, (x0, y), (x1, y), 1)
