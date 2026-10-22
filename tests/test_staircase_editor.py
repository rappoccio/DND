#!/usr/bin/env python3
"""The Staircase editor: step 3 of plans/STAIRCASES_PLAN.md.

A headless App on a three-floor dungeon (B at z=-1, M at z=0, U at z=+1):

  · the terrain editor's Staircase tool places end A on one floor, and the editor opened
    on the floor above or below offers to finish it there (two-phase, D6); end B on any
    other floor is refused;
  · selecting an end and pressing Delete removes the staircase with both its ends;
  · move, rename, relabel and delete are each undone by Ctrl+Z, and an id handed out and
    undone is not handed out again;
  · Shift+click places a second staircase on a landing that already has one (D2), and a
    plain click there cycles the selection between them;
  · the editor's close writes the manifest; the rename prompt sits above the editor;
  · the Staircases… list shows every staircase, and goes to, renames, relabels and
    deletes them, writing the manifest each time.
"""

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from main import App
from dungeon import Dungeon, MapPage
from menus import dm

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}
PAGES = (("B", -1), ("M", 0), ("U", 1))


def _png(tmp, name):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    for x in range(0, COLS * CELL + 1, CELL):                # grid lines for analyze_grid
        pygame.draw.line(surf, (60, 60, 60), (x, 0), (x, ROWS * CELL), 1)
    for y in range(0, ROWS * CELL + 1, CELL):
        pygame.draw.line(surf, (60, 60, 60), (0, y), (COLS * CELL, y), 1)
    path = os.path.join(tmp, name)
    pygame.image.save(surf, path)
    return path


def _dungeon(tmp):
    """An app on page M, with B below and U above, and the manifest on disk."""
    pages = []
    for pid, z in PAGES:
        png = _png(tmp, f"{pid}.png")
        with open(os.path.join(tmp, f"{pid}_terrain.json"), "w") as f:
            f.write('{"regions": [], "walls_enabled": false, "manual_grid": %s}'
                    % str(GRID).replace("'", '"'))
        pages.append(MapPage(pid, png, f"{pid}_agents.json", [0, 0, z], COLS, ROWS))
    app = App(pages[1].png, seed=1)
    app._dungeon_manifest_path = os.path.join(tmp, "keep.dungeon.json")
    app.dungeon = Dungeon(pages=pages, entry_page_id="M")
    app.dungeon.save(app._dungeon_manifest_path)
    app.dungeon_page = None
    assert app._switch_to_page(pages[1], force=True)
    return app


def _go(app, pid):
    assert app._switch_to_page(app.dungeon.page_by_id(pid))


def _editor(app):
    """Open the terrain editor with the Staircase tool picked."""
    app._open_terrain_editor()
    ed = app.terrain_editor
    assert ed.active
    _key(app, pygame.K_9)
    assert ed.selected_type == "Staircase"
    return ed


def _key(app, key, mod=0, unicode=""):
    """One keypress through the app's own event loop, so routing is part of the test."""
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod,
                                         unicode=unicode, scancode=0))
    assert app._handle_events() is not False


def _type(app, text):
    for ch in text:
        _key(app, 0, unicode=ch)


def _on_disk(app):
    return Dungeon.load(app._dungeon_manifest_path)


def _ends(st):
    return [(e.page, tuple(e.cell)) for e in st.ends]


def test_two_phase_placement():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        ed = _editor(app)
        assert ed.stair_finish_id is None                   # nothing to finish yet
        ed._stair_click(rpg.Cell(2, 2))
        _key(app, pygame.K_ESCAPE)                          # close: the manifest is written
        assert not ed.active
        st = _on_disk(app).staircase_by_id(1)
        assert st is not None and not st.finished and _ends(st) == [("M", (2, 2))]

        _go(app, "U")
        ed = _editor(app)
        assert ed.stair_finish_id == 1                      # the editor offers to finish it
        ed._stair_click(rpg.Cell(6, 5))
        assert ed.stair_finish_id is None
        _key(app, pygame.K_ESCAPE)
        st = _on_disk(app).staircase_by_id(1)
        assert st.finished and _ends(st) == [("M", (2, 2)), ("U", (6, 5))]
    print("  ✅ end A on one floor, end B from the floor above, written on close")


def test_finish_refused_off_adjacent_floor():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        st = app.dungeon.new_staircase("B", (1, 1))         # end A on floor -1
        _go(app, "U")                                       # floor +1: two floors away
        ed = _editor(app)
        assert ed.stair_finish_id is None                   # not offered by default…
        _key(app, pygame.K_f)                               # …but [F] can still pick it
        assert ed.stair_finish_id == st.id
        ed._stair_click(rpg.Cell(3, 3))
        assert not st.finished and ed.stair_message.startswith("Refused")
        assert ed._stair_undo == []                         # a refusal leaves no undo step
        _key(app, pygame.K_f)                               # back to "new staircase"
        assert ed.stair_finish_id is None
    print("  ✅ end B two floors away is refused")


def test_delete_removes_both_ends():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        st = app.dungeon.new_staircase("M", (2, 2))
        app.dungeon.finish_staircase(st.id, "U", (6, 5))
        app._dungeon_save_manifest()
        _go(app, "U")
        ed = _editor(app)
        ed._stair_click(rpg.Cell(6, 5))                     # a click on an end selects it
        assert ed.stair_selected == (st.id, 1)
        _key(app, pygame.K_DELETE)
        assert app.dungeon.staircase_by_id(st.id) is None
        _key(app, pygame.K_ESCAPE)
        on_disk = _on_disk(app)
        assert on_disk.staircases == [] and on_disk.next_staircase_id == st.id + 1
        assert app.dungeon.new_staircase("M", (0, 0)).id == st.id + 1   # never reused
    print("  ✅ deleting from one end removes the whole staircase")


def test_edit_and_undo():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        ed = _editor(app)
        d = app.dungeon

        ed._stair_click(rpg.Cell(2, 2))                     # place: Staircase 1
        _key(app, pygame.K_z, mod=pygame.KMOD_CTRL)
        assert d.staircases == []
        ed._stair_click(rpg.Cell(2, 2))                     # the undone id is not reused
        assert [st.id for st in d.staircases] == [2]

        _key(app, pygame.K_m)                               # move the selected end
        assert ed.stair_moving
        ed._stair_click(rpg.Cell(4, 3))
        assert _ends(d.staircase_by_id(2)) == [("M", (4, 3))] and not ed.stair_moving

        ed._stair_click(rpg.Cell(4, 3))                     # select it again, then rename:
        _key(app, pygame.K_n)                               # the prompt sits above the editor
        assert app.name_prompt.visible
        for _ in range(len("Staircase 2")):
            _key(app, pygame.K_BACKSPACE)
        _type(app, "Grand Stair")
        _key(app, pygame.K_RETURN)
        assert not app.name_prompt.visible and ed.active
        assert d.staircase_by_id(2).name == "Grand Stair"

        _key(app, pygame.K_l)                               # relabel; Esc cancels the prompt
        assert app.name_prompt.visible                      # and leaves the editor open
        _type(app, "K21")
        _key(app, pygame.K_ESCAPE)
        assert ed.active and d.staircase_by_id(2).label == ""
        _key(app, pygame.K_l)
        _type(app, "K21")
        _key(app, pygame.K_RETURN)
        assert d.staircase_by_id(2).label == "K21"

        _key(app, pygame.K_DELETE)
        assert d.staircases == []
        for want in ([("label", "K21")], [("label", "")], [("name", "Staircase 2")]):
            _key(app, pygame.K_z, mod=pygame.KMOD_CTRL)
            st = d.staircase_by_id(2)
            assert st is not None and st.name in ("Grand Stair", "Staircase 2")
            for field, value in want:
                assert getattr(st, field) == value, (field, getattr(st, field), value)
        _key(app, pygame.K_z, mod=pygame.KMOD_CTRL)         # the move
        assert _ends(d.staircase_by_id(2)) == [("M", (2, 2))]
        assert d.next_staircase_id == 3
    print("  ✅ place, move, rename, relabel and delete each undo; ids are not reused")


def test_shared_landing():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        ed = _editor(app)
        d = app.dungeon
        ed._stair_click(rpg.Cell(4, 4))
        ed._stair_click(rpg.Cell(4, 4), place=True)         # Shift+click: a second staircase
        assert [_ends(st) for st in d.staircases] == [[("M", (4, 4))]] * 2
        ed._stair_click(rpg.Cell(4, 4))                     # a plain click cycles the two
        first = ed.stair_selected
        ed._stair_click(rpg.Cell(4, 4))
        assert {first, ed.stair_selected} == {(1, 0), (2, 0)}
        ed.draw(app.screen)                                 # the HUD and the shared glyph draw
    print("  ✅ Shift+click shares a landing; a click cycles its staircases")


def test_staircases_list():
    with tempfile.TemporaryDirectory() as tmp:
        app = _dungeon(tmp)
        d = app.dungeon
        a = d.new_staircase("M", (2, 2), label="K21")
        d.finish_staircase(a.id, "U", (6, 5))
        b = d.new_staircase("B", (1, 1))

        dm.show_staircases_menu(app)
        rows = [o.label for o in app.prompts.live.options]
        assert rows == ["Staircase 1 (K21): M (2, 2) floor 0 ↔ U (6, 5) floor 1 ▸",
                        "Staircase 2: B (1, 1) floor -1, unfinished ▸"], rows
        app.prompts.cancel()

        assert app._staircase_goto(a.id, 1)                 # jump to end B: page U
        assert app.dungeon_page.id == "U"
        assert app._staircase_set_text(b.id, "label", "K83")
        assert app._staircase_set_text(a.id, "name", "  ")  # blank: back to the default
        assert app._staircase_delete(a.id)
        on_disk = _on_disk(app)
        assert [st.id for st in on_disk.staircases] == [b.id]
        assert on_disk.staircase_by_id(b.id).label == "K83"

        app.combat_active = True                            # a page change is refused (D3)
        assert not app._staircase_goto(b.id, 0)
        assert app.dungeon_page.id == "U"
    print("  ✅ the Staircases… list shows, goes to, relabels and deletes, and saves")


def test_without_a_dungeon():
    with tempfile.TemporaryDirectory() as tmp:
        app = App(_png(tmp, "solo.png"), seed=1)
        ed = _editor(app)
        ed._stair_click(rpg.Cell(1, 1))
        assert "need a dungeon" in ed.stair_message
        ed.draw(app.screen)
        _key(app, pygame.K_ESCAPE)
        assert not ed.active
    print("  ✅ without a dungeon the tool says so and places nothing")


def main():
    pygame.init()
    tests = [test_two_phase_placement, test_finish_refused_off_adjacent_floor,
             test_delete_removes_both_ends, test_edit_and_undo, test_shared_landing,
             test_staircases_list, test_without_a_dungeon]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:                               # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
