#!/usr/bin/env python3
"""The New Dungeon wizard's shell (plans/DUNGEON_WIZARD_PLAN.md W4, D4–D8).

  · Dungeon → New Dungeon… opens the docked wizard, with no map needed (D4); it is
    refused in combat (D6);
  · the first screen: campaign (existing / New campaign… / No campaign (loose)), name,
    Start from (D8); a missing or taken answer is refused in the panel, never replaced;
  · driven by real clicks and keys through App._handle_events;
  · Premade maps → the next step; Back returns; Cancel closes and saves nothing (D7);
  · Generate builds into the dungeon just named: in a campaign (a new one here), and
    loose in maps/<slug>/, from whatever map was showing (the blank map is loaded);
  · Discard dungeon is offered only once something is saved, and archives the folder;
  · while the wizard is open players are held: no image for them (D6);
  · W5, the premade steps (D10–D16): pick, Set Grid, crop + brush, name, another floor,
    Back to rename, Finish; in a campaign the floors go in its library;
  · W6, placement and alignment (D17–D19): above / below / beside, a landmark pair,
    arrow nudges, Skip;
  · W8, Floors… → Add (D22): the open dungeon's kept sheets, every added floor placed,
    Finish / Cancel reopen the dungeon from disk.
"""

import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

import app_dungeon_gen as gen
import dungeon_wizard as dw
import gui_driver
import save_layout as sl
from main import App
from menus import dm
from net import view as net_view
from net.mapimg import MapImageCache
from scene_store import CampaignStore

BLANK = os.path.join(_ROOT, "maps", "Blank.png")


def _params(**kw):
    p = {"allowed_mobs": None, "boss_mob": None, "cr": 3, "min_room": 9,
         "start": "Easy", "end": "Hard", "boss": True, "seed": 4242, "carve": True,
         "types": None, "languages": None, "floors": 1, "rooms_per_floor": 4,
         "maps_x": 1, "maps_y": 1, "automation": 4, "groups": 0}
    p.update(kw)
    return p


class _Sandbox:
    """tmp/maps/Blank.png as THE blank map (so loose dungeons land in tmp/maps/), a
    second loose map beside it, and tmp/encounters/ as the campaigns root."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="dungeon_wizard_")
        self.maps = os.path.join(self.tmp, "maps")
        os.makedirs(self.maps)
        self.blank = os.path.join(self.maps, "Blank.png")
        shutil.copy(BLANK, self.blank)
        self.other = os.path.join(self.maps, "room.png")
        surf = pygame.Surface((300, 240))
        surf.fill((200, 195, 185))
        pygame.image.save(surf, self.other)
        with open(os.path.join(self.maps, "room_terrain.json"), "w") as f:
            json.dump({"regions": [], "walls_enabled": False,
                       "manual_grid": {"cell_px": 30, "anchor": [0, 0], "square_ft": 5}}, f)
        self.encounters = os.path.join(self.tmp, "encounters")
        self.camp = sl.Campaign.create(os.path.join(self.encounters, "Old"), "Old Camp")
        self._old = gen.BLANK_MAP
        gen.BLANK_MAP = self.blank
        return self

    def __exit__(self, *exc):
        gen.BLANK_MAP = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, png=None):
        app = App(png or self.other, seed=7)
        app._modal_message = lambda lines, blocking=True: setattr(app, "_last_msg", lines)
        app._modal_generate_dungeon = lambda populate=False, generate=False: (
            app.__dict__.setdefault("_gen_calls", []).append((populate, generate)),
            _params())[1]
        return app


def _choice(wiz, label):
    return next(k for k, lab in wiz.choices if lab == label)


def test_opens_from_the_menu_and_refuses_combat():
    with _Sandbox() as sb:
        app = sb.app()
        dm.show_dungeon_menu(app)
        assert app.prompts.choose_label("New Dungeon…").ok
        wiz = app.dungeon_wizard
        assert wiz.visible and wiz.step == "start" and wiz.choice is None
        assert [lab for _k, lab in wiz.choices] == ["Old Camp", "New campaign…",
                                                    "No campaign (loose)"], wiz.choices
        assert net_view.players_held(app)
        wiz.cancel()
        assert not wiz.visible and "nothing was saved" in app._status_msg
        assert not net_view.players_held(app)

        app.combat_active = True
        assert not wiz.start(app)
        assert not wiz.visible and "combat" in app._status_msg
    print("  ✅ New Dungeon… opens the wizard; combat refuses it; Cancel saves nothing")


def test_first_screen_refusals():
    with _Sandbox() as sb:
        app = sb.app()
        loose = dw.LOOSE
        for choice, camp, name, why in ((None, "", "Crypt", "Pick a campaign"),
                                        (loose, "", "  ", "Name the dungeon"),
                                        (dw.NEW_CAMPAIGN, "", "Crypt", "Name the new campaign"),
                                        (loose, "", "!!!", "no usable characters")):
            try:
                dw.resolve_target(app, choice, camp, name, dw.PREMADE)
            except ValueError as e:
                assert why in str(e), (why, e)
            else:
                raise AssertionError(f"accepted {choice!r} / {name!r}")
        os.makedirs(os.path.join(sb.camp.root, "crypt"))
        try:
            dw.resolve_target(app, sb.camp.root, "", "Crypt", dw.GENERATE)
        except ValueError as e:
            assert "Old Camp already has a dungeon 'crypt'" in str(e), e
        else:
            raise AssertionError("a taken dungeon name was accepted")
        # A new campaign's folder is its slug, -2 when taken; nothing is written yet.
        os.makedirs(os.path.join(sb.encounters, "old-camp"))
        t = dw.resolve_target(app, dw.NEW_CAMPAIGN, "Old Camp", "Crypt", dw.PREMADE)
        assert os.path.basename(t.campaign) == "old-camp-2" and t.campaign_name == "Old Camp"
        assert not os.path.exists(t.campaign)
        t = dw.resolve_target(app, loose, "", "The Crypt", dw.PREMADE)
        assert t.manifest_path() == os.path.join(sb.maps, "the-crypt", "the-crypt.dungeon.json")
    print("  ✅ the first screen refuses a missing choice, a bad or taken name")


def _type(app, text):
    for ch in text:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=ord(ch.lower()),
                                             mod=0, unicode=ch))
    app._handle_events()


def _key(app, key):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))
    app._handle_events()


def test_clicks_premade_back_and_cancel():
    with _Sandbox() as sb:
        app = sb.app()
        wiz = app.dungeon_wizard
        assert wiz.start(app)
        pygame.event.clear()
        gui_driver.post_click(app, wiz.button_rect("next").center)
        assert wiz.step == "start" and "Pick a campaign" in wiz.error, wiz.error
        gui_driver.post_click(app, wiz.button_rect(dw.LOOSE).center)
        assert wiz.choice == dw.LOOSE
        gui_driver.post_click(app, wiz.name_input.rect.center)
        _type(app, "Crypt")
        assert wiz.name_input.text == "Crypt", wiz.name_input.text
        gui_driver.post_click(app, wiz.button_rect(dw.PREMADE).center)
        _key(app, pygame.K_RETURN)                       # Enter is Next
        assert wiz.step == "source" and wiz.target.slug == "crypt", (wiz.step, wiz.error)
        assert wiz.button_rect("discard") is None        # nothing saved yet
        gui_driver.post_click(app, wiz.button_rect("back").center)
        assert wiz.step == "start" and wiz.name_input.text == "Crypt"
        _key(app, pygame.K_ESCAPE)                       # Esc is Cancel
        assert not wiz.visible
        assert not os.path.exists(os.path.join(sb.maps, "crypt"))
    print("  ✅ clicks and keys: refusal, Premade → next step, Back, Esc cancels")


def test_new_campaign_click_shows_its_name_field():
    with _Sandbox() as sb:
        app = sb.app()
        wiz = app.dungeon_wizard
        wiz.start(app)
        pygame.event.clear()
        gui_driver.post_click(app, wiz.button_rect(dw.NEW_CAMPAIGN).center)
        assert wiz.camp_input.active and wiz.camp_input.rect.y > wiz.button_rect(dw.LOOSE).y
        _type(app, "Barovia")
        _key(app, pygame.K_TAB)
        _type(app, "Keep")
        assert (wiz.camp_input.text, wiz.name_input.text) == ("Barovia", "Keep")
        wiz.close()
    print("  ✅ New campaign… adds a campaign name field; Tab moves to the dungeon name")


def test_generate_into_a_new_campaign():
    with _Sandbox() as sb:
        app = sb.app()                     # a loose map showing, not the blank one
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = dw.NEW_CAMPAIGN
        wiz.camp_input.text = "Barovia"
        wiz.name_input.text = "The Crypt"
        wiz.start_from = dw.GENERATE
        wiz.next()
        assert app._gen_calls == [(False, True)], app._gen_calls   # the generate shape
        assert not wiz.visible, wiz.error
        camp = sl.Campaign(os.path.join(sb.encounters, "barovia"))
        assert camp.name == "Barovia" and camp.list_dungeons() == ["the-crypt"]
        assert isinstance(app.store, CampaignStore)
        assert app._dungeon_manifest_path == camp.dungeon("the-crypt").manifest_path
        assert app._last_msg[-1] == "Saved: barovia/the-crypt", app._last_msg
        assert not os.path.exists(os.path.join(sb.encounters, gen.RANDOM_CAMPAIGN))
        assert sorted(os.listdir(sb.maps)) == ["Blank.png", "room.png", "room_terrain.json"], \
            os.listdir(sb.maps)
    print("  ✅ Generate builds into a new campaign, from a non-blank map")


def test_generate_loose_and_taken_name():
    with _Sandbox() as sb:
        app = sb.app(sb.blank)
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = dw.LOOSE
        wiz.name_input.text = "Pit"
        wiz.start_from = dw.GENERATE
        wiz.next()
        assert not wiz.visible, wiz.error
        out = os.path.join(sb.maps, "pit")
        assert os.path.isfile(os.path.join(out, "pit.dungeon.json")), os.listdir(sb.maps)
        assert os.path.isfile(os.path.join(out, "Blank.png"))
        assert app._dungeon_manifest_path == os.path.join(out, "pit.dungeon.json")
        assert app.dungeon is not None and app.dungeon.entry_page_id == "floor0"
        assert not [f for f in os.listdir(sb.maps) if f.startswith("gen_dungeon_")]
        assert not [f for f in os.listdir(sb.maps) if f.startswith("Blank_")], \
            os.listdir(sb.maps)

        wiz.start(app)
        wiz.choice = dw.LOOSE
        wiz.name_input.text = "pit"
        wiz.start_from = dw.GENERATE
        wiz.next()
        assert wiz.visible and "already has a dungeon 'pit'" in wiz.error, wiz.error
        assert len(app._gen_calls) == 1, "the generator opened for a taken name"
        wiz.close()
    print("  ✅ Generate loose makes maps/<slug>/; a taken name is refused in the panel")


def test_generate_settings_cancelled_stays_open():
    with _Sandbox() as sb:
        app = sb.app()
        app._modal_generate_dungeon = lambda populate=False, generate=False: None
        wiz = app.dungeon_wizard
        wiz.start(app, campaign=sb.camp.root)
        assert wiz.choice == sb.camp.root
        wiz.name_input.text = "Crypt"
        wiz.start_from = dw.GENERATE
        wiz.next()
        assert wiz.visible and wiz.step == "start"
        assert app._map_path == sb.other, "the scene changed for a cancelled generator"
        assert sb.camp.list_dungeons() == []
        wiz.close()
    print("  ✅ cancelling the generator's settings leaves the wizard and the scene")


def test_discard_archives_the_saved_dungeon():
    with _Sandbox() as sb:
        app = sb.app()
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = sb.camp.root
        wiz.name_input.text = "Crypt"
        wiz.next()
        assert wiz.step == "source"
        os.makedirs(wiz.target.root())                    # what W5's first crop writes
        with open(wiz.target.manifest_path(), "w") as f:
            f.write("{}")
        wiz.mark_saved()
        assert wiz.button_rect("discard") is not None
        pygame.event.clear()
        gui_driver.post_click(app, wiz.button_rect("discard").center)
        assert app.prompts.live is not None and "Discard dungeon Crypt" in app.prompts.live.title
        assert app.prompts.choose_label("Discard").ok
        assert not wiz.visible and "Discarded Crypt" in app._status_msg, app._status_msg
        assert not os.path.exists(os.path.join(sb.camp.root, "crypt"))
        arch = os.listdir(os.path.join(sb.camp.root, "_archive"))
        assert len(arch) == 1 and arch[0].startswith("crypt-"), arch

        # Cancel after a save keeps it, and says where to carry on.
        wiz.start(app)
        wiz.choice = sb.camp.root
        wiz.name_input.text = "Vault"
        wiz.next()
        os.makedirs(wiz.target.root())
        wiz.mark_saved()
        wiz.cancel()
        assert os.path.isdir(os.path.join(sb.camp.root, "vault"))
        assert dw.CONTINUE_HINT in app._status_msg, app._status_msg
    print("  ✅ Discard (after asking) archives a saved dungeon; Cancel keeps it")


def _drag(app, p0, p1, button=1):
    p0, p1 = (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1]))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=p0, button=button))
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=p1, rel=(p1[0] - p0[0],
                                         p1[1] - p0[1]), buttons=(1, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=p1, button=button))
    app._handle_events()


def _sheet_png(path, size=(400, 300), sq=20, anchor=(10, 10)):
    """A light sheet with dark lines every ``sq`` px from ``anchor``."""
    surf = pygame.Surface(size)
    surf.fill((230, 225, 215))
    for x in range(anchor[0], size[0], sq):
        pygame.draw.line(surf, (30, 30, 30), (x, 0), (x, size[1]))
    for y in range(anchor[1], size[1], sq):
        pygame.draw.line(surf, (30, 30, 30), (0, y), (size[0], y))
    pygame.image.save(surf, path)
    return path


def _screen(wiz, x, y):
    return wiz.canvas.to_screen(x, y)


def test_premade_loose_click_through():
    """Pick → Set Grid (a 3×2-square drag) → crop (drag, brush) → name → another floor
    from the sheet (Whole image) → Back renames it → Finish opens the dungeon."""
    with _Sandbox() as sb:
        sheet = _sheet_png(os.path.join(sb.tmp, "levels.png"))
        app = sb.app()
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = dw.LOOSE
        wiz.name_input.text = "Keep"
        wiz.next()
        assert wiz.step == "source" and not wiz._enabled("next")
        pygame.event.clear()
        gui_driver.post_click(app, wiz.button_rect("file").center)
        assert app.file_browser.active
        app.file_browser.active = False
        wiz.on_file_chosen(sheet)                         # what the browser calls back
        assert wiz.step == "grid" and not wiz._enabled("next")

        # Set Grid: a box over 3 × 2 squares, 10-ft squares.
        _drag(app, _screen(wiz, 30, 50), _screen(wiz, 90, 90))
        assert wiz.sheet.grid is not None
        for _ in range(2):
            gui_driver.post_click(app, wiz.button_rect(("across", +1)).center)
        gui_driver.post_click(app, wiz.button_rect(("down", +1)).center)
        gui_driver.post_click(app, wiz.button_rect(10).center)
        g = wiz.sheet.grid
        assert (wiz.across, wiz.down, g.square_ft) == (3, 2, 10), (wiz.across, wiz.down, g)
        tol = 1.5 / wiz.canvas.zoom                      # one screen pixel, in sheet px
        assert abs(g.square_px - 20) < tol and abs(g.anchor[0] - 30) < tol, (g, tol)
        _key(app, pygame.K_RETURN)
        assert wiz.step == "crop" and not wiz._enabled("next")

        # Crop: drag over 4 × 3 squares (it snaps to the lines at x 30…110, y 30…90;
        # square indices count from the anchor (30, 50)); brush one square black.
        _drag(app, _screen(wiz, 32, 28), _screen(wiz, 108, 92))
        assert wiz.cur.squares == (0, -1, 4, 2), wiz.cur.squares
        gui_driver.post_click(app, wiz.button_rect("paint").center)
        _drag(app, _screen(wiz, 40, 40), _screen(wiz, 40, 40))
        assert wiz.cur.blanks == {(0, -1)}, wiz.cur.blanks
        _key(app, pygame.K_RETURN)
        assert wiz.step == "name" and wiz.floor_input.text == "keep-floor-1"
        assert wiz.button_rect("discard") is None
        _key(app, pygame.K_RETURN)                         # writes the floor
        assert wiz.step == "more" and wiz.saved, wiz.error
        root = os.path.join(sb.maps, "keep")
        assert os.path.isfile(os.path.join(root, "keep.dungeon.json"))
        assert wiz.button_rect("discard") is not None

        # Another floor from the same sheet: no grid step; Whole image.
        gui_driver.post_click(app, wiz.button_rect("same").center)
        assert wiz.step == "crop" and wiz.cur.squares is None
        gui_driver.post_click(app, wiz.button_rect("whole").center)
        assert wiz.cur.squares[2] > 5
        _key(app, pygame.K_RETURN)
        assert wiz.floor_input.text == "keep-floor-2"
        _key(app, pygame.K_RETURN)
        assert wiz.step == "place", wiz.error              # W6: a later floor is placed
        _key(app, pygame.K_RETURN)                         # above keep-floor-1 (default)
        assert wiz.step == "align", wiz.error
        _key(app, pygame.K_RETURN)                         # accepted where it is
        assert wiz.step == "more", wiz.error

        # Back reopens the name (through Align and Place): a new one renames the floor.
        for step in ("align", "place", "name"):
            gui_driver.post_click(app, wiz.button_rect("back").center)
            assert wiz.step == step, (wiz.step, step)
        assert wiz.floor_input.text == "keep-floor-2"
        wiz.floor_input.text = "roof"
        for _ in range(3):
            _key(app, pygame.K_RETURN)
        assert wiz.step == "more" and [f.written for f in wiz.floors] == ["keep-floor-1", "roof"]
        assert not os.path.exists(os.path.join(root, "keep-floor-2.png"))

        gui_driver.post_click(app, wiz.button_rect("next").center)     # Finish
        assert not wiz.visible
        assert app._dungeon_manifest_path == os.path.join(root, "keep.dungeon.json")
        assert [(p.id, p.origin) for p in app.dungeon.pages] == \
            [("keep-floor-1", [0, 0, 0]), ("roof", [0, 0, 1])]
        assert app.dungeon_page.id == "keep-floor-1"
        assert (app.bm.grid_cols, app.bm.grid_rows) == (8, 6), (app.bm.grid_cols, app.bm.grid_rows)
        assert app.floor_checklist.visible                             # W7 (D21)
        assert [r.page_id for r in app.floor_checklist.rows] == ["roof", "keep-floor-1"]
    print("  ✅ premade, loose: pick, Set Grid, crop + brush, name, another, rename, Finish")


def test_premade_campaign_discard():
    """In a new campaign: a floor in the library; Discard archives the dungeon and the
    library folders the wizard made, keeping the campaign."""
    with _Sandbox() as sb:
        sheet = _sheet_png(os.path.join(sb.tmp, "Crypt Map.png"))
        app = sb.app()
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = dw.NEW_CAMPAIGN
        wiz.camp_input.text = "Barovia"
        wiz.name_input.text = "Crypt"
        wiz.next()
        wiz.on_file_chosen(sheet)
        wiz.set_grid_box((10, 10), (50, 50))
        wiz.across = wiz.down = 2
        wiz._regrid()
        wiz.next()
        wiz.whole_image()
        wiz.next()
        wiz.next()
        assert wiz.step == "more", wiz.error
        camp = sl.Campaign(os.path.join(sb.encounters, "barovia"))
        assert camp.list_library_maps() == ["crypt-floor-1", "crypt-map"]
        assert camp.list_dungeons() == ["crypt"]
        # The library offers its maps on the next Pick an image, sheets first.
        gui_driver.post_click(app, wiz.button_rect("another").center)
        assert wiz.step == "source" and wiz.library() == ["crypt-map", "crypt-floor-1"]
        wiz.discard()
        assert not wiz.visible
        assert camp.list_dungeons() == [] and camp.list_library_maps() == []
        arch = os.listdir(os.path.join(camp.root, "_archive"))
        assert len(arch) == 1
        kept = os.listdir(os.path.join(camp.root, "_archive", arch[0], "library"))
        assert sorted(kept) == ["crypt-floor-1", "crypt-map"], kept
    print("  ✅ premade, campaign: floors in the library; Discard archives them too")


def _two_level_sheet(path):
    """A 400 × 200 sheet, 20-px squares from (0, 0): two 10 × 10-square levels side by
    side, each with a red landmark square, at (2, 3) on the left and (5, 1) on the right."""
    surf = pygame.Surface((400, 200))
    surf.fill((225, 220, 210))
    pygame.draw.rect(surf, (200, 30, 30), (2 * 20, 3 * 20, 20, 20))
    pygame.draw.rect(surf, (200, 30, 30), (200 + 5 * 20, 1 * 20, 20, 20))
    pygame.image.save(surf, path)
    return path


def test_place_and_align_click_through():
    """W6 (D17–D19): the first floor is floor 0 and the entry; the second is placed
    below it (a chip click), aligned by a landmark pair clicked on the map view and an
    arrow nudge, Enter accepts; a third goes beside the first with Skip."""
    with _Sandbox() as sb:
        sheet = _two_level_sheet(os.path.join(sb.tmp, "two.png"))
        app = sb.app()
        wiz = app.dungeon_wizard
        wiz.start(app)
        wiz.choice = dw.LOOSE
        wiz.name_input.text = "Pit"
        wiz.next()
        wiz.on_file_chosen(sheet)
        wiz.set_grid_box((0, 0), (40, 40))
        wiz.across = wiz.down = 2
        wiz._regrid()
        wiz.next()
        wiz.set_crop((0, 0), (200, 200))                   # the left level
        wiz.next()
        wiz.next()
        assert wiz.step == "more", wiz.error               # D17: nothing to place
        wiz.another_from_sheet()
        wiz.set_crop((200, 0), (400, 200))                 # the right level
        wiz.next()
        _key(app, pygame.K_RETURN)
        assert wiz.step == "place", wiz.error
        assert wiz.cur.ref == "pit-floor-1" and wiz.cur.relation == "above"
        gui_driver.post_click(app, wiz.button_rect("below").center)
        assert wiz.cur.relation == "below"
        assert [z for z, _ids in dw.fp.stack(wiz.place_preview)] == [0, -1]
        assert wiz.align.layers and wiz.align.layers[-1].page_id == "pit-floor-1"
        manifest = os.path.join(sb.maps, "pit", "pit.dungeon.json")
        _key(app, pygame.K_RETURN)
        assert wiz.step == "align", wiz.error
        saved = dw.dg.Dungeon.load(manifest)                # Place saved the stack (D7)
        assert saved.page_by_id("pit-floor-2").origin == [0, 0, -1]

        # Landmark pair: the red square's centre on the new floor (5.5, 1.5), then on
        # the faded floor above (2.5, 3.5): the new floor moves by (-3, +2).
        a = wiz.align
        gui_driver.post_click(app, tuple(round(v) for v in a.to_screen(5.5, 1.5)))
        assert wiz.mark_a is not None and wiz.mark_b is None, wiz.error
        gui_driver.post_click(app, tuple(round(v) for v in a.to_screen(2.5, 3.5)))
        assert wiz.align_page.origin == [-3, 2, -1], wiz.align_page.origin
        _key(app, pygame.K_RIGHT)                          # fine-tune a cell
        assert wiz.align_page.origin == [-2, 2, -1]
        _key(app, pygame.K_LEFT)
        _key(app, pygame.K_RETURN)
        assert wiz.step == "more", wiz.error
        assert dw.dg.Dungeon.load(manifest).page_by_id("pit-floor-2").origin == [-3, 2, -1]

        # A third floor beside the first, Skip: just east of floor 0's pages.
        wiz.another_from_sheet()
        wiz.whole_image()
        wiz.next()
        wiz.next()
        assert wiz.step == "place", wiz.error
        wiz.set_place(ref="pit-floor-1", relation="beside")
        wiz.next()
        assert wiz.step == "align"
        faint = [ly.page_id for ly in wiz.align.layers if ly.alpha < 100]
        assert faint == ["pit-floor-2"], faint             # the floor below, for context
        gui_driver.post_click(app, wiz.button_rect("skip").center)
        assert wiz.step == "more", wiz.error

        gui_driver.post_click(app, wiz.button_rect("next").center)     # Finish
        assert [(p.id, p.origin) for p in app.dungeon.pages] == \
            [("pit-floor-1", [0, 0, 0]), ("pit-floor-2", [-3, 2, -1]),
             ("pit-floor-3", [10, 0, 0])]
        assert app.dungeon.entry_page_id == "pit-floor-1"
        # W7: the entry is not recorded; the landmark-aligned floor is, Skip is not.
        assert [p.aligned for p in app.dungeon.pages] == [None, True, False]
        rows = {r.page_id: r for r in app.floor_checklist.rows}
        assert [rows[p].label("aligned") for p in ("pit-floor-1", "pit-floor-2",
                                                    "pit-floor-3")] == \
            ["Entry", "Aligned ✓", "Aligned ✗"]
    print("  ✅ W6: place below (stack preview), landmark pair + nudge, beside + Skip")


def _build_one_floor(app, choice, name, sheet, camp_name=""):
    """The wizard, start to Finish, with one Whole-image floor from ``sheet``."""
    wiz = app.dungeon_wizard
    wiz.start(app)
    wiz.choice = choice
    wiz.camp_input.text = camp_name
    wiz.name_input.text = name
    wiz.next()
    wiz.on_file_chosen(sheet)
    wiz.set_grid_box((0, 0), (40, 40))
    wiz.across = wiz.down = 2
    wiz._regrid()
    wiz.next()
    wiz.set_crop((0, 0), (200, 200))
    wiz.next()
    wiz.next()
    assert wiz.step == "more", wiz.error
    wiz.finish()
    assert app.dungeon is not None and not wiz.visible
    return wiz


def test_add_loose_from_a_kept_sheet():
    """W8 (D22): Floors… → Add on an open loose dungeon offers its kept sheet with its
    grid (D12), crops another floor from it, places and aligns it, and Finish goes
    back to the dungeon (on the floor that was showing) with the new floor in it."""
    with _Sandbox() as sb:
        sheet = _two_level_sheet(os.path.join(sb.tmp, "two.png"))
        app = sb.app()
        wiz = _build_one_floor(app, dw.LOOSE, "Pit", sheet)
        ck = app.floor_checklist
        assert ck.visible
        add = next(r for r, k, v in ck._hit if v == "add")
        gui_driver.post_click(app, add.center)
        assert not ck.visible and wiz.visible and wiz.adding and wiz.step == "source"
        assert not wiz._enabled("back")
        assert [s.name for s in wiz.sheets] == ["two"], wiz.sheets
        assert wiz.sheets[0].grid is not None and wiz.sheets[0].placed
        gui_driver.post_click(app, wiz.button_rect(0).center)        # the kept sheet
        assert wiz.step == "grid" and wiz._enabled("next")           # no grid asked
        _key(app, pygame.K_RETURN)
        assert wiz.step == "crop"
        assert wiz.floors == []
        wiz.set_crop((200, 0), (400, 200))
        _key(app, pygame.K_RETURN)
        assert wiz.floor_input.text == "pit-floor-2", wiz.floor_input.text
        wiz.floor_input.text = "pit-floor-1"                         # taken: refused
        _key(app, pygame.K_RETURN)
        assert wiz.step == "name" and "already has" in wiz.error, wiz.error
        wiz.floor_input.text = "pit-floor-2"
        _key(app, pygame.K_RETURN)
        assert wiz.step == "place", wiz.error           # an added floor is always placed
        assert wiz.cur.ref == "pit-floor-1"
        assert wiz.button_rect("discard") is None       # never discards the dungeon
        gui_driver.post_click(app, wiz.button_rect("below").center)
        _key(app, pygame.K_RETURN)
        assert wiz.step == "align", wiz.error
        _key(app, pygame.K_RETURN)
        assert wiz.step == "more", wiz.error
        root = os.path.join(sb.maps, "pit")
        made = set(os.listdir(root))
        assert {"pit-floor-2.png", "pit-floor-2_terrain.json", "pit-floor-2_agents.json",
                "two.png", "two_terrain.json"} <= made, made
        assert not any(f.startswith("two-") or f.startswith("two_2") for f in made), made
        gui_driver.post_click(app, wiz.button_rect("next").center)   # Finish
        assert not wiz.visible and app.floor_checklist.visible
        assert [(p.id, p.z, p.aligned) for p in app.dungeon.pages] == \
            [("pit-floor-1", 0, None), ("pit-floor-2", -1, True)]
        assert app.dungeon_page.id == "pit-floor-1"
        assert len(app.dungeon.sources) == 1
        # The app's copy is the disk's: saving it keeps the new floor.
        app._dungeon_save()
        assert dw.dg.Dungeon.load(app._dungeon_manifest_path).page_by_id("pit-floor-2")
    print("  ✅ W8: Add on a loose dungeon crops from its kept sheet, placed and aligned")


def test_add_campaign_cancel_reopens():
    """W8 in a campaign: Add from a new file; Cancel after a floor is written keeps it,
    and the dungeon is reopened from disk, so the run the app saves next has it."""
    with _Sandbox() as sb:
        sheet = _two_level_sheet(os.path.join(sb.tmp, "two.png"))
        other = _sheet_png(os.path.join(sb.tmp, "cellar.png"))
        app = sb.app()
        wiz = _build_one_floor(app, sb.camp.root, "Crypt", sheet)
        assert isinstance(app.store, CampaignStore)
        app.floor_checklist.close()
        app.combat_active = True
        assert not wiz.start_add(app) and "combat" in app._status_msg
        app.combat_active = False
        assert wiz.start_add(app)
        assert wiz.target.slug == "crypt" and wiz.target.campaign == sb.camp.root
        assert [s.name for s in wiz.sheets] == ["two"]               # the crop's sheet
        wiz.on_file_chosen(other)
        wiz.set_grid_box((10, 10), (50, 50))
        wiz.across = wiz.down = 2
        wiz._regrid()
        wiz.next()
        wiz.whole_image()
        wiz.next()
        assert wiz.floor_input.text == "crypt-floor-2"
        wiz.next()
        assert wiz.step == "place", wiz.error
        wiz.next()
        assert wiz.step == "align", wiz.error
        _key(app, pygame.K_ESCAPE)                                   # Cancel
        assert not wiz.visible and "1 floor added" in app._status_msg, app._status_msg
        assert [p.id for p in app.dungeon.pages] == ["crypt-floor-1", "crypt-floor-2"]
        assert app.dungeon_page.id == "crypt-floor-1"
        assert sorted(sb.camp.list_library_maps()) == ["cellar", "crypt-floor-1",
                                                       "crypt-floor-2", "two"]
        app._save_terrain()                     # the app's run must not drop the floor
        layout = sb.camp.dungeon("crypt")
        with open(layout.run_path()) as f:
            run = json.load(f)
        assert "crypt-floor-2" in run["maps"], list(run["maps"])
    print("  ✅ W8: Add in a campaign; Cancel keeps the floor and reopens the dungeon")


def test_players_held_while_open():
    with _Sandbox() as sb:
        app = sb.app()
        cache = MapImageCache()
        cache.publish(net_view.page_image(app, set(), False))
        cache.hold_players(True)
        assert cache.png(False) is None and cache.png(True) is not None
        cache.hold_players(False)
        assert cache.png(False) is not None
    print("  ✅ a held image cache refuses players and serves the DM")


if __name__ == "__main__":
    pygame.init()
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:                 # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"  ❌ {name}: {e}")
                failures += 1
    sys.exit(1 if failures else 0)
