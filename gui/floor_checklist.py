"""The Floors… checklist (plans/DUNGEON_WIZARD_PLAN.md D21, W7).

One row per floor (page) of the open dungeon, top floor first:

    grid ✓ · aligned ✓ · walls (none / detected / edited) · doors N · staircases N · creatures N

Each item jumps to that floor with the right tool open: Set Grid, Align Floor, Wall
Detection (or the terrain editor's Edge / Wall tool once walls are edited), the terrain
editor's Door or Staircase tool, Populate Floor…. It opens on the wizard's Finish and
from Dungeon → Floors…, and it holds the Overview… (place pages, set the entry, remove)
and Add… that Floors… used to list (D2).

The status is read from the saved files, except for the floor showing, which is read
from the live scene so edits not yet saved count. Nothing here writes a file.

``floor_rows`` / ``jump`` are plain functions, so the suites drive them without the panel;
``FloorChecklist`` is the panel, docked over the right-hand panel like the wizard.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

COLUMNS = ("grid", "aligned", "walls", "doors", "stairs", "creatures")

WALLS_NONE, WALLS_DETECTED, WALLS_EDITED = "none", "detected", "edited"


@dataclass
class FloorStatus:
    page_id: str
    z: int
    entry: bool
    grid: bool
    aligned: bool | None        # None: not recorded (made before W7)
    walls: str                  # WALLS_NONE / WALLS_DETECTED / WALLS_EDITED
    doors: int
    stairs: int
    creatures: int

    def label(self, col: str) -> str:
        if col == "grid":
            return "Grid ✓" if self.grid else "Grid ✗"
        if col == "aligned":
            if self.entry:
                return "Entry"
            return {True: "Aligned ✓", False: "Aligned ✗"}.get(self.aligned, "Aligned ?")
        if col == "walls":
            return f"Walls: {self.walls}"
        if col == "doors":
            return f"Doors {self.doors}"
        if col == "stairs":
            return f"Stairs {self.stairs}"
        return f"Creatures {self.creatures}"

    def done(self, col: str) -> bool:
        """Whether the item reads as done (drawn green)."""
        return {"grid": self.grid,
                "aligned": self.entry or self.aligned is True,
                "walls": self.walls != WALLS_NONE,
                "doors": self.doors > 0,
                "stairs": self.stairs > 0,
                "creatures": self.creatures > 0}[col]


def walls_state(walls_enabled: bool, edge_overrides, regions) -> str:
    """none: walls are OFF and none are painted; edited: the DM painted walls or edited
    the detected edges; detected: walls are ON, as the detector found them."""
    painted = any(isinstance(r, dict) and r.get("type") == "Wall" for r in regions or [])
    ov = edge_overrides or {}
    if walls_enabled:
        return WALLS_EDITED if (painted or ov.get("add") or ov.get("remove")) else WALLS_DETECTED
    return WALLS_EDITED if painted else WALLS_NONE


def _read(fn, page) -> dict:
    try:
        doc = fn(page)
    except (ValueError, OSError):
        return {}
    return doc if isinstance(doc, dict) else {}


def floor_status(app, page) -> FloorStatus:
    dung = app.dungeon
    entry = dung.entry_page()
    stairs = len(dung.staircase_ends_on(page.id))
    live = app.dungeon_page is not None and app.dungeon_page.id == page.id
    if live:
        grid = bool(app._manual_grid) or bool(getattr(app.bm, "grid_cols", 0))
        walls = walls_state(app._walls_enabled, app._edge_overrides, app._terrain_regions)
        doors = len(app.bm.doors)
        creatures = len(app.bm.placed_agents)
    else:
        doc = _read(app.store.terrain, page)
        grid = bool(doc.get("manual_grid")) or (page.cols > 0 and page.rows > 0)
        walls = walls_state(bool(doc.get("walls_enabled", True)), doc.get("edge_overrides"),
                            doc.get("regions"))
        doors = len(doc.get("doors") or [])
        creatures = len(_read(app.store.creatures, page).get("agents") or [])
    return FloorStatus(page.id, page.z, entry is not None and entry.id == page.id, grid,
                       page.aligned, walls, doors, stairs, creatures)


def floor_rows(app) -> list[FloorStatus]:
    """Every floor of the open dungeon, top floor first, manifest order within one."""
    if app.dungeon is None:
        return []
    pages = sorted(app.dungeon.pages, key=lambda p: -p.z)      # stable: manifest order kept
    return [floor_status(app, p) for p in pages]


def jump(app, page_id: str, col: str) -> bool:
    """Go to floor ``page_id`` and open the tool for column ``col``. False when the
    floor is gone or the switch was refused (combat, a missing image)."""
    page = app.dungeon.page_by_id(page_id) if app.dungeon is not None else None
    if page is None:
        return False
    if app.dungeon_page is None or app.dungeon_page.id != page.id:
        if not app._switch_to_page(page):
            return False
    if col == "grid":
        if not app._grid_sample_mode:
            app._toggle_grid_sample_mode()
    elif col == "aligned":
        app.floor_align.start(app)
    elif col == "walls":
        state = walls_state(app._walls_enabled, app._edge_overrides, app._terrain_regions)
        if state == WALLS_EDITED:
            drawn = app._walls_enabled and (app._detection or {}).get("mode") == "dark_fraction"
            _terrain_tool(app, "Edge" if drawn else "Wall")
        elif not app._walls_enabled:
            def on():
                app._toggle_walls()                 # OFF → ON
                app._open_wall_detection()
            app._confirm_overwrite([app._terrain_path], "Turn walls on", on)
        else:
            app._open_wall_detection()
    elif col == "doors":
        _terrain_tool(app, "Door")
    elif col == "stairs":
        _terrain_tool(app, "Staircase")
    elif col == "creatures":
        import app_dungeon_gen
        app_dungeon_gen.on_populate_floor(app)
    return True


def _terrain_tool(app, tool: str):
    app._open_terrain_editor()
    app.terrain_editor.selected_type = tool


class FloorChecklist:
    """The docked checklist panel. ``app.floor_checklist``; ``open(app)`` shows it."""
    PAD = 12
    HDR_H = 30
    NAME_H = 22
    CHIP_H = 24
    GAP = 4
    BTN_H = 30
    PER_LINE = 3

    def __init__(self, font_sm=None, font_md=None):
        self.font_sm = font_sm
        self.font_md = font_md
        self.visible = False
        self.app = None
        self.rect = None
        self.rows: list[FloorStatus] = []
        self.scroll = 0
        self._hit: list[tuple[pygame.Rect, str, object]] = []
        self._names: list[tuple[str, tuple[int, int], bool]] = []
        self._list_rect = None

    def open(self, app) -> bool:
        if app.dungeon is None:
            app._flash_status("No dungeon open.")
            return False
        self.app = app
        self.visible = True
        self.scroll = 0
        self.refresh()
        return True

    def close(self):
        self.visible = False

    def refresh(self):
        self.rows = floor_rows(self.app)
        self._layout()

    # ── Layout ────────────────────────────────────────────────────────────
    def _block_h(self) -> int:
        lines = -(-len(COLUMNS) // self.PER_LINE)
        return self.NAME_H + lines * (self.CHIP_H + self.GAP) + 8

    def _layout(self):
        app = self.app
        panel = app._panel_rect()
        self.rect = pygame.Rect(panel.x + 4, panel.y + 40, panel.w - 8, max(320, panel.h - 80))
        ix, iw = self.rect.x + self.PAD, self.rect.w - 2 * self.PAD
        top = self.rect.y + self.HDR_H + self.PAD
        bottom = self.rect.bottom - self.PAD - self.BTN_H - 8
        self._list_rect = pygame.Rect(ix, top, iw, max(0, bottom - top))
        total = len(self.rows) * self._block_h()
        self.scroll = max(0, min(self.scroll, total - self._list_rect.h))
        self._hit, self._names = [], []
        cw = (iw - (self.PER_LINE - 1) * 6) // self.PER_LINE
        y = top - self.scroll
        for st in self.rows:
            self._names.append((f"{'★ ' if st.entry else ''}{st.page_id}  ·  floor {st.z}",
                                (ix, y + 2), self._list_rect.top <= y + 2 and
                                y + self.NAME_H <= self._list_rect.bottom))
            cy = y + self.NAME_H
            for i, col in enumerate(COLUMNS):
                r = pygame.Rect(ix + (i % self.PER_LINE) * (cw + 6),
                                cy + (i // self.PER_LINE) * (self.CHIP_H + self.GAP),
                                cw, self.CHIP_H)
                if self._list_rect.contains(r):
                    self._hit.append((r, "chip", (st.page_id, col)))
            y += self._block_h()
        bw = (iw - 12) // 3
        by = self.rect.bottom - self.PAD - self.BTN_H
        for i, key in enumerate(("overview", "add", "close")):
            self._hit.append((pygame.Rect(ix + i * (bw + 6), by, bw, self.BTN_H), "btn", key))

    # ── Events ────────────────────────────────────────────────────────────
    def click(self, kind, val):
        app = self.app
        self.close()
        if kind == "chip":
            jump(app, *val)
        elif val == "overview":
            app._dungeon_pages_overview()
        elif val == "add":
            app.dungeon_wizard.start_add(app)        # W8 (D22)

    def handle(self, event) -> bool:
        """True when the panel used the event; map-view events are left to the app."""
        if not self.visible or not self.rect:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll -= event.y * 30
            self._layout()
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for r, kind, val in self._hit:
                if r.collidepoint(event.pos):
                    self.click(kind, val)
                    return True
            return self.rect.collidepoint(event.pos)
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            return self.rect.collidepoint(event.pos)
        return False

    # ── Drawing ───────────────────────────────────────────────────────────
    def draw(self, surf):
        if not self.visible or not self.rect:
            return
        pygame.draw.rect(surf, (28, 28, 44), self.rect, border_radius=8)
        pygame.draw.rect(surf, (110, 90, 170), self.rect, width=2, border_radius=8)
        surf.blit(self.font_md.render("Floors — click an item to work on it", True,
                                      (220, 220, 235)),
                  (self.rect.x + self.PAD, self.rect.y + 7))
        if not self.rows:
            surf.blit(self.font_sm.render("This dungeon has no floors.", True, (185, 185, 200)),
                      self._list_rect.topleft)
        for text, pos, shown in self._names:
            if shown:
                surf.blit(self.font_md.render(text, True, (230, 215, 160)), pos)
        rows = {st.page_id: st for st in self.rows}
        mouse = pygame.mouse.get_pos()
        btns = {"overview": "Overview…", "add": "Add…", "close": "Close"}
        for r, kind, val in self._hit:
            hover = r.collidepoint(mouse)
            if kind == "chip":
                st = rows[val[0]]
                done = st.done(val[1])
                bg = (40, 80, 50) if done else (90, 70, 35)
                text = st.label(val[1])
            else:
                bg, text = (55, 55, 80), btns[val]
            if hover:
                bg = tuple(min(255, c + 30) for c in bg)
            pygame.draw.rect(surf, bg, r, border_radius=5)
            pygame.draw.rect(surf, (120, 120, 150), r, width=1, border_radius=5)
            img = self.font_sm.render(text, True, (230, 230, 240))
            surf.blit(img, (r.centerx - img.get_width() // 2, r.centery - img.get_height() // 2))
