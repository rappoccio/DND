"""The New Dungeon wizard's Place and Align working area (DUNGEON_WIZARD_PLAN W6, D18–D19):
floors drawn over the map view at their global cells, the floor being placed opaque and
the floor it is placed against faded over it, so a landmark can be lined up by eye.

World units are 5-ft cells on the dungeon's global grid. A page's image maps to the
world by its manual grid: pixel ``px`` is global ``X = gx + (px - anchor_x) / cell_px``.
Each layer scales only its visible part, cached until the view changes. Like
``SheetCanvas``, nothing here touches the engine or the scene underneath.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame

PREVIEW_SIDE = 2048

COL_NEW = (255, 215, 80)
COL_FADED = (90, 200, 255)
COL_FAINT = (120, 120, 150)
COL_MARK_A = (255, 120, 220)
COL_MARK_B = (90, 230, 255)


@dataclass(eq=False)
class Layer:
    """One page, drawn. ``origin`` is shared with the caller's page while aligning, so
    a nudge moves the drawing with it."""
    page_id: str
    image: str
    origin: list
    cell_px: float
    anchor: tuple[float, float] = (0.0, 0.0)
    alpha: int = 255
    color: tuple = COL_NEW
    _cache: tuple = field(default=(), repr=False)

    def world_rect(self, size) -> tuple[float, float, float, float]:
        """(x, y, w, h) of the whole image in global cells."""
        return (self.origin[0] - self.anchor[0] / self.cell_px,
                self.origin[1] - self.anchor[1] / self.cell_px,
                size[0] / self.cell_px, size[1] / self.cell_px)


class AlignCanvas:
    def __init__(self):
        self.layers: list[Layer] = []
        self.area = pygame.Rect(0, 0, 0, 0)
        self.zoom = 10.0                 # screen pixels per cell
        self.ox = self.oy = 0.0          # screen position of global (0, 0)
        self._images: dict[str, tuple[pygame.Surface, float, tuple[int, int]]] = {}

    # ── layers and view ──
    def set_layers(self, layers: list[Layer], area: pygame.Rect, fit: bool = True) -> None:
        self.layers = list(layers)
        self.area = pygame.Rect(area)
        if fit:
            self.fit()

    def clear(self) -> None:
        self.layers = []

    def set_area(self, area: pygame.Rect) -> None:
        if pygame.Rect(area) != self.area:
            self.area = pygame.Rect(area)
            self.fit()

    def _image(self, path: str):
        """(surface, preview factor, native size) of ``path``, loaded once."""
        if path not in self._images:
            img = pygame.image.load(path)
            size = img.get_size()
            f = 1.0
            if max(size) > PREVIEW_SIDE:
                f = PREVIEW_SIDE / max(size)
                img = pygame.transform.smoothscale(
                    img, (max(1, round(size[0] * f)), max(1, round(size[1] * f))))
            self._images[path] = (img, f, size)
        return self._images[path]

    def bounds(self):
        xs, ys = [], []
        for ly in self.layers:
            x, y, w, h = ly.world_rect(self._image(ly.image)[2])
            xs += [x, x + w]
            ys += [y, y + h]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def fit(self) -> None:
        b = self.bounds()
        if b is None or self.area.w <= 0 or self.area.h <= 0:
            return
        x0, y0, x1, y1 = b
        w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
        self.zoom = min(self.area.w / w, self.area.h / h) * 0.92
        self.ox = self.area.x + (self.area.w - w * self.zoom) / 2 - x0 * self.zoom
        self.oy = self.area.y + (self.area.h - h * self.zoom) / 2 - y0 * self.zoom

    def to_world(self, pos) -> tuple[float, float]:
        return ((pos[0] - self.ox) / self.zoom, (pos[1] - self.oy) / self.zoom)

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x * self.zoom, self.oy + y * self.zoom)

    def zoom_at(self, factor: float, pos) -> None:
        x, y = self.to_world(pos)
        self.zoom = max(0.5, min(self.zoom * factor, 400.0))
        self.ox, self.oy = pos[0] - x * self.zoom, pos[1] - y * self.zoom

    def pan(self, dx: float, dy: float) -> None:
        self.ox += dx
        self.oy += dy

    # ── drawing ──
    def _blit_layer(self, surf, ly: Layer) -> pygame.Rect | None:
        img, f, size = self._image(ly.image)
        x, y, w, h = ly.world_rect(size)
        left, top = self.to_screen(x, y)
        full = pygame.Rect(round(left), round(top), max(1, round(w * self.zoom)),
                           max(1, round(h * self.zoom)))
        vis = full.clip(self.area)
        if vis.w <= 0 or vis.h <= 0:
            return full
        s = self.zoom / ly.cell_px / f            # screen px per preview px
        key = (tuple(vis), round(left, 2), round(top, 2), round(s, 6), ly.alpha)
        if ly._cache and ly._cache[0] == key:
            surf.blit(ly._cache[1], ly._cache[2])
            return full
        nx0, ny0 = max(0, int((vis.x - left) / s)), max(0, int((vis.y - top) / s))
        nx1 = min(img.get_width(), int((vis.right - left) / s) + 1)
        ny1 = min(img.get_height(), int((vis.bottom - top) / s) + 1)
        if nx1 <= nx0 or ny1 <= ny0:
            return full
        piece = img.subsurface(pygame.Rect(nx0, ny0, nx1 - nx0, ny1 - ny0))
        out = pygame.transform.scale(piece, (max(1, round((nx1 - nx0) * s)),
                                             max(1, round((ny1 - ny0) * s))))
        if ly.alpha < 255:
            out = out.convert() if pygame.display.get_surface() else out
            out.set_alpha(ly.alpha)
        pos = (round(left + nx0 * s), round(top + ny0 * s))
        ly._cache = (key, out, pos)
        surf.blit(out, pos)
        return full

    def draw(self, surf, *, marks=(), font=None) -> None:
        """Each layer in order, outlined and labelled; then the landmark ``marks``
        (``(world point, colour)``)."""
        clip = surf.get_clip()
        surf.set_clip(self.area)
        surf.fill((14, 14, 20), self.area)
        drawn = [(ly, self._blit_layer(surf, ly)) for ly in self.layers]
        for ly, full in drawn:         # outlines and labels above every image
            if full is None:
                continue
            pygame.draw.rect(surf, ly.color, full, 2)
            if font is not None:       # the floor being placed top-left, the others bottom-left
                t = font.render(ly.page_id, True, ly.color)
                x = max(self.area.x, full.x) + 4
                y = (max(self.area.y, full.y) + 4 if ly.alpha == 255 else
                     min(self.area.bottom, full.bottom) - t.get_height() - 4)
                surf.blit(t, (x, y))
        for (wx, wy), col in marks:
            x, y = self.to_screen(wx, wy)
            x, y = round(x), round(y)
            pygame.draw.circle(surf, (0, 0, 0), (x, y), 9, 3)
            pygame.draw.circle(surf, col, (x, y), 8, 2)
            pygame.draw.line(surf, col, (x - 12, y), (x + 12, y), 1)
            pygame.draw.line(surf, col, (x, y - 12), (x, y + 12), 1)
        surf.set_clip(clip)
