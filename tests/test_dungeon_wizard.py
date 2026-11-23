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
  · while the wizard is open players are held: no image for them (D6).
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
